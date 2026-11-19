# -*- coding: utf-8 -*-
"""ecs_cron.py — 把 CloudBase 云函数（power_sync / xgj_sync / health_probe）替代到阿里云 ECS。

三个云函数原本由 CloudBase 定时触发器驱动（2026-12-10 环境到期），本脚本用**云助手
RunCommand**（复用 deploy/ecs_site.py::run_script，无需 SSH/22 端口）在 ECS 安装：

    /opt/class-tools/jobs/jobs_runner.py            任务分发 + 心跳写盘
    /opt/class-tools/jobs/<job>/*                   源码 = deploy/functions/<job>/（脱敏、不含密钥）
    /etc/class-tools/jobs.env                       600 root:root（凭据从本机 secrets 读入后写入）
    /var/lib/class-tools/jobs/state/<row_id>.json   心跳（www-data 可写；health_beat 读取）
    /etc/systemd/system/class-tools-job-<job>.{service,timer}

时间表（systemd timer）：power_sync 每小时 :01、xgj_sync 每 2h:20、health_probe 每 5 分钟。
**安装 != 启用**：install 只写文件并把 timer `disable --now`（默认全部禁用，不会写库）；
切流（P4）后再 `enable --confirm`。

目标后端：
    staging（默认）  http://121.196.47.2/v1/rdb/rest-next/     ← P1 影子库，可安全写测试数据
    live（切流后）   http://121.196.47.2/v1/rdb/rest/          ← 需显式 --allow-live
    注意：切流前 `/v1/rdb/rest/*` 仍反代 CloudBase，误用 live 会把定时任务写进 CloudBase，
    因此 `--backend live` 必须同时给 `--allow-live`；CloudBase 网关地址一律拒绝。

用法（web 目录，系统 python；需要 aliyunsdkcore，本机 creds.env 提供阿里云 AK）：
    python deploy\\ecs_cron.py install --dry-run            # 只打印计划（env 值全部脱敏，不连 ECS）
    python deploy\\ecs_cron.py install                      # 安装（默认 staging；timer 保持禁用）
    python deploy\\ecs_cron.py install --backend live --allow-live   # 切流后重装（仍不启用）
    python deploy\\ecs_cron.py status                       # 只读：timer/心跳/env 键名/日志尾部
    python deploy\\ecs_cron.py smoke --job health_probe     # 手动跑一轮（timer 仍禁用；仅 staging）
    python deploy\\ecs_cron.py enable --confirm             # 启用三个 timer
    python deploy\\ecs_cron.py disable                      # 停用（保留文件/心跳）
    python deploy\\ecs_cron.py uninstall [--purge --confirm]# 删 unit；--purge 连 env/代码/心跳

安全：
    * 真实凭据只在进程内读取 → 云助手 base64 命令 → ECS 本地 600 文件；**不打印、不入库、不进 git**；
    * `--dry-run` 打印的环境内容全部 `***` 脱敏；
    * 心跳/日志/标记只含状态与耗时，不含 token/key。
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SYSPATH_HERE = HERE
if SYSPATH_HERE not in sys.path:
    sys.path.insert(0, SYSPATH_HERE)

import ecs_site  # noqa: E402  （云助手通道 + creds 读取；本脚本不打印任何凭据）

# ---------------------------------------------------------------- 常量

VERSION = "2026-11-18.p3"
BACKEND = "staging"                      # 默认后端（安全：写影子库）
STAGING_BASE = "http://121.196.47.2/v1/rdb/rest-next/"
LIVE_BASE = "http://121.196.47.2/v1/rdb/rest/"
SITE_BASE = "https://tool.furina.fun/v1/rdb/rest/"

FUNCS_DIR = os.path.join(HERE, "functions")
REPO_ROOT = os.path.dirname(HERE)
TOOLS_INDEX = os.path.join(REPO_ROOT, "tools", "index.html")

BRIEFDESK_ROOT = os.environ.get("BRIEFDESK_ROOT") or r"G:\ClassTools\briefdesk"
BD_SCRIPTS = os.path.join(BRIEFDESK_ROOT, "scripts")
BD_SECRETS = os.path.join(BRIEFDESK_ROOT, "secrets")

JOBS_DIR = "/opt/class-tools/jobs"
STATE_DIR = "/var/lib/class-tools/jobs/state"
ENV_FILE = "/etc/class-tools/jobs.env"
UNIT_DIR = "/etc/systemd/system"
BACKUP_ROOT = "/opt/class-tools/backup"
SERVICE_PREFIX = "class-tools-job-"
UPLOAD_DIR = "/tmp/jobs_upload"

# job → 元数据（on_calendar 为 systemd timer 表达式）
JOBS = {
    "power_sync": {
        "row": "cloud_power_sync",
        "on_calendar": "*-*-* *:01:00",
        "timeout": 300,
        "desc": "宿舍电量同步（替代 CloudBase 云函数 power_sync，每小时 :01）",
    },
    "xgj_sync": {
        "row": "cloud_xgj_sync",
        "on_calendar": "*-*-* 00/2:20:00",
        "timeout": 300,
        "desc": "班级小管家英语作业采集（替代 CloudBase 云函数 xgj_sync，每 2h:20）",
    },
    "health_probe": {
        "row": "cloud_health_probe",
        "on_calendar": "*-*-* *:00/5:00",
        "timeout": 180,
        "desc": "依赖服务健康巡检（替代 CloudBase 云函数 health_probe，每 5 分钟）",
    },
}
JOB_ORDER = ("power_sync", "xgj_sync", "health_probe")

# 上传清单：本地文件 → ECS 目标路径（按 deploy/functions 同源目录结构）
UPLOAD_FILES = [
    ("jobs_runner.py", os.path.join(FUNCS_DIR, "jobs_runner.py"),
     JOBS_DIR + "/jobs_runner.py", 0o755),
    ("cloud_backend.py", os.path.join(FUNCS_DIR, "cloud_backend.py"),
     JOBS_DIR + "/cloud_backend.py", 0o644),
    ("power_sync/index.py", os.path.join(FUNCS_DIR, "power_sync", "index.py"),
     JOBS_DIR + "/power_sync/index.py", 0o644),
    ("power_sync/sync_power_cloud.py", os.path.join(FUNCS_DIR, "power_sync", "sync_power_cloud.py"),
     JOBS_DIR + "/power_sync/sync_power_cloud.py", 0o644),
    ("xgj_sync/index.py", os.path.join(FUNCS_DIR, "xgj_sync", "index.py"),
     JOBS_DIR + "/xgj_sync/index.py", 0o644),
    ("xgj_sync/xgj_homework.py", os.path.join(FUNCS_DIR, "xgj_sync", "xgj_homework.py"),
     JOBS_DIR + "/xgj_sync/xgj_homework.py", 0o644),
    ("health_probe/index.py", os.path.join(FUNCS_DIR, "health_probe", "index.py"),
     JOBS_DIR + "/health_probe/index.py", 0o644),
    ("health_probe/health_beat.py", os.path.join(FUNCS_DIR, "health_probe", "health_beat.py"),
     JOBS_DIR + "/health_probe/health_beat.py", 0o644),
]

CHUNK = 8000  # 单条云助手命令里的 base64 分片长度（总命令 base64 后 < 24KB 上限）

# 非机密键：--dry-run 打印时可以显示真实值（后端地址/路径/开关），其余一律 ***
SAFE_ENV_KEYS = {"CB_BASE", "CLASS_CB_BASE", "CLASS_JOBS_STATE", "CLASS_PG_MONITOR",
                 "CLASS_HEALTH_RUNNER", "CLASS_JOB_HEARTBEAT"}


# ---------------------------------------------------------------- 本地读取（不打印值）
def _read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_publishable_key():
    """从 tools/index.html 的 var CBK 读 publishable key（设计上公开；不打印值）。"""
    text = _read_text(TOOLS_INDEX)
    key_m = re.search(r'var CBK="([^"]+)"', text)
    if not key_m:
        raise SystemExit("cannot parse var CBK from %s" % TOOLS_INDEX)
    return key_m.group(1)


def read_admin_identity():
    """管理员身份（生产服务凭据）：从本机 scripts/sync_power_cloud.py 的常量读取，不打印。"""
    path = os.path.join(BD_SCRIPTS, "sync_power_cloud.py")
    try:
        text = _read_text(path)
    except OSError:
        raise SystemExit("缺少 %s（--backend 需要它换 class_verify token）" % path)
    sid_m = re.search(r'^ADMIN_SID = "([^"]+)"', text, re.M)
    name_m = re.search(r'^ADMIN_NAME = "((?:[^"\\]|\\.)*)"', text, re.M)
    if not sid_m or not name_m:
        raise SystemExit("cannot parse ADMIN_SID/ADMIN_NAME from %s" % path)
    name = name_m.group(1)
    try:  # 源文件里姓名用 \\u 转义
        name = bytes(name, "utf-8").decode("unicode_escape")
    except Exception:  # noqa: BLE001
        pass
    return sid_m.group(1), name


def read_xgj_secret():
    """学工记 token 字段（来自 secrets/xjg-token.json；仅内存使用，不打印、不落仓库）。"""
    path = os.path.join(BD_SECRETS, "xjg-token.json")
    try:
        data = json.loads(_read_text(path))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "XGJ_TOKEN": str(data.get("token") or ""),
        "XGJ_MEMBER_ID": str(data.get("member_id") or ""),
        "XGJ_EXP": str(data.get("exp") or 0),
        "XGJ_EXP_TEXT": str(data.get("exp_text") or ""),
        "XGJ_CID": str(data.get("cid") or ""),
    }


# ---------------------------------------------------------------- 后端选择
def backend_kind(base):
    low = (base or "").lower()
    if not low:
        return "unknown"
    if "tcloudbasegateway.com" in low or ".tcb." in low:
        return "cloudbase"
    if "/rest-next/" in low or low.rstrip("/").endswith("/rest-next"):
        return "staging"
    if low.startswith("http://") or low.startswith("https://"):
        return "selfhosted"
    return "unknown"


def resolve_target(backend, base=None, allow_live=False):
    """决定 jobs.env 里的目标后端；返回 (base, kind)。CloudBase 网关一律拒绝、live 需显式确认。"""
    if base:
        b = base.strip()
        if not (b.lower().startswith("http://") or b.lower().startswith("https://")):
            raise SystemExit("--base 必须是 http(s) 绝对地址")
        b = b.rstrip("/") + "/"
        kind = backend_kind(b)
        if kind == "cloudbase":
            raise SystemExit("拒绝：--base 指向 CloudBase 网关（迁移目标是 ECS 自建后端）")
        if kind == "selfhosted" and backend != "staging" and not allow_live:
            raise SystemExit("拒绝：--base 是生产自建后端，请显式加 --allow-live（切流前会写错库）")
        return b, kind
    if backend == "live":
        if not allow_live:
            raise SystemExit(
                "拒绝：--backend live 需要 --allow-live（切流前 /v1/rdb/rest/* 仍反代 CloudBase，"
                "会误写 CloudBase；确认已切流后再加）")
        return LIVE_BASE, "selfhosted"
    return STAGING_BASE, "staging"


def probe_base(base, timeout=6.0):
    """只读探活（GET <base>service_health?select=id&limit=1）；返回 (http, note)。"""
    url = base + "service_health?select=id&limit=1"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "briefdesk-ecs-cron/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(2048)
            return int(resp.status), "ok"
    except urllib.error.HTTPError as exc:
        return int(exc.code), "http-error"
    except Exception as exc:  # noqa: BLE001
        return 0, (str(exc).strip() or exc.__class__.__name__)[:120]


# ---------------------------------------------------------------- jobs.env
def _q(value):
    """systemd EnvironmentFile 值加引号并转义（值里可能有空格/中文/特殊字符）。"""
    s = "" if value is None else str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")
    return '"' + s + '"'


def build_env_text(base):
    """生成 /etc/class-tools/jobs.env 内容（只在进程内传给云助手；不回显）。"""
    key = read_publishable_key()
    sid, name = read_admin_identity()
    xgj = read_xgj_secret()
    lines = [
        "# /etc/class-tools/jobs.env — generated by deploy/ecs_cron.py v%s at %s"
        % (VERSION, time.strftime("%Y-%m-%d %H:%M:%S")),
        "# chmod 600 root:root; 凭据来自本机 secrets；不打印、不入库、不进 git。",
        "# 目标后端 kind=%s" % backend_kind(base),
        "",
        "# ---- 目标后端（staging 影子库 / live 切流后）----",
        "CB_BASE=" + _q(base),
        "CB_KEY=" + _q(key),
        "CLASS_CB_BASE=" + _q(base),
        "CLASS_CB_KEY=" + _q(key),
        "",
        "# ---- 管理员（生产服务凭据；rpc/class_verify 换 token）----",
        "CLASS_ADMIN_SID=" + _q(sid),
        "CLASS_ADMIN_NAME=" + _q(name),
        "",
    ]
    if xgj.get("XGJ_TOKEN") and xgj.get("XGJ_MEMBER_ID"):
        lines += [
            "# ---- 学工记（xgj_sync）----",
        ] + ["%s=%s" % (k, _q(v)) for k, v in xgj.items()] + [""]
    else:
        lines += ["# ---- 学工记 token 缺失（xgj_sync 会失败；补齐 secrets/xjg-token.json 后重装）----",
                  ""]
    lines += [
        "# ---- 心跳 / 巡检标记（health_beat 读取）----",
        "CLASS_JOB_HEARTBEAT=" + _q("1"),
        "CLASS_JOBS_STATE=" + _q(STATE_DIR),
        "CLASS_HEALTH_RUNNER=" + _q("ecs-timer"),
        "# ---- P4：ECS PG 监控状态文件（round-3 class-tools-pg-monitor.timer 写；health_probe 并入 cloudbase 行）----",
        "CLASS_PG_MONITOR=" + _q("/var/lib/class-tools/pg-monitor.json"),
        "",
    ]
    return "\n".join(lines)


def redact_env_text(text):
    """只读展示用：保留键名与安全键的值，其余值全部 ***。"""
    out = []
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            out.append(line)
            continue
        k, _v = line.split("=", 1)
        k = k.strip()
        if k in SAFE_ENV_KEYS:
            out.append(line)
        else:
            out.append(k + "=" + ('"***"' if k else "***"))
    return "\n".join(out)


# ---------------------------------------------------------------- systemd unit 文本
def _runtime_start_timeout(job):
    """systemd TimeoutStartSec：handler 自身超时 + 120s 余量。"""
    return int(JOBS[job]["timeout"]) + 120


def unit_service(job):
    meta = JOBS[job]
    return """[Unit]
Description=%s
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=www-data
Group=www-data
EnvironmentFile=%s
WorkingDirectory=%s
ExecStart=/usr/bin/python3 %s/jobs_runner.py %s
TimeoutStartSec=%d
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/class-tools/jobs
PrivateTmp=true
""" % (meta["desc"], ENV_FILE, JOBS_DIR, JOBS_DIR, job, _runtime_start_timeout(job))


def unit_timer(job):
    meta = JOBS[job]
    svc = "%s%s" % (SERVICE_PREFIX, job.replace("_", "-"))
    return """[Unit]
Description=Timer: %s

[Timer]
OnCalendar=%s
Persistent=true
RandomizedDelaySec=30
Unit=%s.service

[Install]
WantedBy=timers.target
""" % (meta["desc"], meta["on_calendar"], svc)


def service_name(job):
    return "%s%s" % (SERVICE_PREFIX, job.replace("_", "-"))


# ---------------------------------------------------------------- 远程脚本
def script_prep():
    return (
        "#!/bin/bash\n"
        "set -e\n"
        "umask 077\n"
        "rm -rf " + UPLOAD_DIR + "\n"
        "mkdir -p " + UPLOAD_DIR + "\n"
        "echo prep-ok\n"
    )


def script_chunk(index, chunk):
    return (
        "#!/bin/bash\n"
        "set -e\n"
        "printf '%s' '" + chunk + "' >> " + UPLOAD_DIR + "/f%d.b64\n" % index +
        "echo chunk-%d-ok\n" % index
    )


def script_decode(files):
    """把分片解码到最终路径 + py_compile + 权限。"""
    lines = ["#!/bin/bash", "set -e", "umask 022"]
    for idx, (label, local, remote, mode) in enumerate(files):
        d = os.path.dirname(remote)
        lines += [
            "install -d -o root -g root -m 755 " + d,
            "base64 -d " + UPLOAD_DIR + "/f%d.b64 > %s" % (idx, remote),
            "python3 -m py_compile " + remote,
            "chown root:root " + remote,
            "chmod %o %s" % (mode, remote),
            "echo decoded %s" % label,
        ]
    lines += [
        "rm -rf " + UPLOAD_DIR,
        "rm -rf " + JOBS_DIR + "/__pycache__ " + JOBS_DIR + "/*/__pycache__",
        "echo decode-ok",
    ]
    return "\n".join(lines) + "\n"


def script_units(sha_map):
    """写 systemd unit + 状态目录 + 安装标记；所有 timer 强制 disable --now（默认禁用）。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    services = [service_name(j) for j in JOB_ORDER]
    lines = [
        "#!/bin/bash",
        "set -e",
        "TS=%s" % ts,
        "BK=%s/$TS" % BACKUP_ROOT,
        "mkdir -p \"$BK\" " + STATE_DIR + "/logs " + JOBS_DIR,
        "chown -R www-data:www-data /var/lib/class-tools/jobs",
        "chmod 750 /var/lib/class-tools/jobs " + STATE_DIR + " " + STATE_DIR + "/logs",
        "for u in " + " ".join(services) + "; do cp -a " + UNIT_DIR + "/$u.service \"$BK/\" 2>/dev/null || true; "
        "cp -a " + UNIT_DIR + "/$u.timer \"$BK/\" 2>/dev/null || true; done",
    ]
    for job in JOB_ORDER:
        svc = service_name(job)
        lines += [
            "cat > " + UNIT_DIR + "/%s.service <<'UNIT_SVC_EOF'" % svc,
            unit_service(job),
            "UNIT_SVC_EOF",
            "cat > " + UNIT_DIR + "/%s.timer <<'UNIT_TIMER_EOF'" % svc,
            unit_timer(job),
            "UNIT_TIMER_EOF",
        ]
    marker = {
        "version": VERSION,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "jobs": {j: {"row": JOBS[j]["row"], "on_calendar": JOBS[j]["on_calendar"],
                     "service": service_name(j)} for j in JOB_ORDER},
        "files": sha_map,
        "timers": "disabled",
        "note": "install 不启用 timer；切流后 deploy/ecs_cron.py enable --confirm",
    }
    lines += [
        "systemctl daemon-reload",
        "for u in " + " ".join(services) + "; do "
        "systemctl disable --now \"$u.timer\" >/dev/null 2>&1 || true; done",
        "cat > " + JOBS_DIR + "/INSTALLED.json <<'MARKER_EOF'",
        json.dumps(marker, ensure_ascii=False, indent=1),
        "MARKER_EOF",
        "chmod 644 " + JOBS_DIR + "/INSTALLED.json",
        "echo '=== timer 状态（应为 disabled/inactive）==='",
        "for u in " + " ".join(services) + "; do "
        "printf '%s ' \"$u\"; systemctl is-enabled \"$u.timer\" 2>/dev/null || true; "
        "printf ' active='; systemctl is-active \"$u.timer\" 2>/dev/null || true; done",
        "echo '=== 文件 ==='",
        "ls -la " + JOBS_DIR + " " + JOBS_DIR + "/power_sync " + JOBS_DIR + "/xgj_sync "
        + JOBS_DIR + "/health_probe | head -40",
        "echo units-ok",
    ]
    return "\n".join(lines) + "\n"


def script_env(env_text):
    """写 /etc/class-tools/jobs.env（600；secrets 内容不 echo）。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    return (
        "#!/bin/bash\n"
        "set -e\n"
        "umask 077\n"
        "mkdir -p " + os.path.dirname(ENV_FILE) + "\n"
        "BK=%s/%s/jobs.env.old\n" % (BACKUP_ROOT, ts) +
        "if [ -f " + ENV_FILE + " ]; then mkdir -p \"$(dirname \"$BK\")\"; "
        "cp -a " + ENV_FILE + " \"$BK\"; chmod 600 \"$BK\"; fi\n"
        "cat > " + ENV_FILE + " <<'JOBS_ENV_EOF'\n" + env_text + "\nJOBS_ENV_EOF\n"
        "chown root:root " + ENV_FILE + "\n"
        "chmod 600 " + ENV_FILE + "\n"
        "echo 'env installed: keys='$(sed -n 's/^\\([A-Za-z_][A-Za-z0-9_]*\\)=.*/\\1/p' "
        + ENV_FILE + " | tr '\\n' ',')\n"
        "echo env-ok\n"
    )


def script_verify():
    return r"""#!/bin/bash
set +e
echo "=== jobs_runner self-check ==="
set -a
. /etc/class-tools/jobs.env 2>/dev/null
set +a
setpriv --reuid=www-data --regid=www-data --clear-groups \
  /usr/bin/python3 /opt/class-tools/jobs/jobs_runner.py --self-check 2>&1 | head -30
echo "=== timers（应全部 disabled）==="
for u in class-tools-job-power-sync class-tools-job-xgj-sync class-tools-job-health-probe; do
  printf '%s enabled=' "$u"; systemctl is-enabled "$u.timer" 2>/dev/null
  printf ' active='; systemctl is-active "$u.timer" 2>/dev/null
done
echo "=== done ==="
exit 0
"""


def script_status():
    return r"""#!/bin/bash
set +e
echo "=== timers ==="
for u in class-tools-job-power-sync class-tools-job-xgj-sync class-tools-job-health-probe; do
  printf '%-36s enabled=%-9s active=%-9s' "$u.timer" \
    "$(systemctl is-enabled "$u.timer" 2>/dev/null)" "$(systemctl is-active "$u.timer" 2>/dev/null)"
  systemctl show -p NextElapseUSecRealtime --value "$u.timer" 2>/dev/null
done
echo ""
echo "=== list-timers ==="
systemctl list-timers --all --no-pager 2>/dev/null | grep -E "class-tools-job|NEXT" || echo "(none)"
echo "=== env keys (names only) ==="
sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' /etc/class-tools/jobs.env 2>/dev/null | tr '\n' ' '; echo
echo "=== backend (public URL only) ==="
grep -E '^(CB_BASE|CLASS_CB_BASE)=' /etc/class-tools/jobs.env 2>/dev/null
echo "=== heartbeat ==="
for f in /var/lib/class-tools/jobs/state/*.json; do
  [ -f "$f" ] || continue
  echo "-- $f"; cat "$f" 2>/dev/null; echo
done
echo "=== logs (tail) ==="
tail -n 4 /var/lib/class-tools/jobs/state/logs/*.log 2>/dev/null
echo "=== installed marker ==="
head -c 800 /opt/class-tools/jobs/INSTALLED.json 2>/dev/null; echo
echo "=== disk ==="; df -h / | tail -2
echo "=== done ==="
exit 0
"""


def script_smoke(job):
    return r"""#!/bin/bash
set +e
JOB=__JOB__
set -a
. /etc/class-tools/jobs.env 2>/dev/null
set +a
BASE="${CLASS_CB_BASE:-$CB_BASE}"
case "$BASE" in
  *rest-next*) echo "smoke backend=staging ($BASE)" ;;
  *) echo "REFUSE: smoke 只允许 staging 后端（当前 $BASE）；切流后请用真实 timer"; exit 3 ;;
esac
for u in class-tools-job-power-sync class-tools-job-xgj-sync class-tools-job-health-probe; do
  if systemctl is-active "$u.timer" >/dev/null 2>&1; then
    echo "WARN: $u.timer 正在运行（手动 smoke 与定时任务可能并发）"
  fi
done
echo "=== run $JOB ==="
runuser -u www-data -- /usr/bin/python3 /opt/class-tools/jobs/jobs_runner.py "$JOB"
RC=$?
echo "=== heartbeat after run ==="
cat /var/lib/class-tools/jobs/state/*.json 2>/dev/null | tail -c 1200; echo
exit $RC
""".replace("__JOB__", job)


def script_enable():
    return r"""#!/bin/bash
set -e
for u in class-tools-job-power-sync class-tools-job-xgj-sync class-tools-job-health-probe; do
  systemctl enable --now "$u.timer"
done
sleep 1
echo "=== backend (public URL only) ==="
grep -E '^(CB_BASE|CLASS_CB_BASE)=' /etc/class-tools/jobs.env
echo "=== next run ==="
systemctl list-timers --all --no-pager | grep -E "class-tools-job|NEXT"
echo "WARN: timer 已启用，会按时间表写库（确认后端是期望的库）"
echo enable-ok
"""


def script_disable():
    return r"""#!/bin/bash
set +e
for u in class-tools-job-power-sync class-tools-job-xgj-sync class-tools-job-health-probe; do
  systemctl disable --now "$u.timer" 2>/dev/null
  printf '%s enabled=' "$u"; systemctl is-enabled "$u.timer" 2>/dev/null
done
echo disable-ok
"""


def script_uninstall(purge=False):
    lines = [
        "#!/bin/bash",
        "set +e",
        "for u in class-tools-job-power-sync class-tools-job-xgj-sync class-tools-job-health-probe; do "
        "systemctl disable --now \"$u.timer\" 2>/dev/null; "
        "rm -f " + UNIT_DIR + "/$u.service " + UNIT_DIR + "/$u.timer; done",
        "systemctl daemon-reload",
        "echo units-removed",
    ]
    if purge:
        lines += [
            "rm -rf " + JOBS_DIR + " /var/lib/class-tools/jobs",
            "rm -f " + ENV_FILE,
            "echo purged (jobs dir + state + env)",
        ]
    lines += ["echo uninstall-ok", "exit 0"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 执行封装
def _run(script, label, timeout=180, wait=300, dry_run=False):
    if dry_run:
        print("[dry-run] %s（%d B，不执行）" % (label, len(script.encode("utf-8"))))
        return "Success", 0, ""
    st, rc, out = ecs_site.run_script(script, label=label, timeout=timeout, wait=wait)
    head = (out or "").strip()
    if len(head) > 4000:
        head = head[:1800] + "\n...\n" + head[-2200:]
    print("[%s] status=%s exit=%s\n%s" % (label, st, rc, head))
    return st, rc, out


def _ok(st, rc):
    return st == "Success" and rc in (0, "0", None)


# ---------------------------------------------------------------- install
def build_plan(base, kind):
    print("=== 目标 ===")
    print("backend=%s base=%s" % (kind, base))
    print("ECS 实例=%s（云助手 RunCommand；无需 SSH）" % ecs_site.ECS_IP)
    print("jobs=%s" % ", ".join("%s(%s)" % (j, JOBS[j]["on_calendar"]) for j in JOB_ORDER))
    print("timers=安装后全部 disabled（切流后 enable --confirm）")
    print()
    print("=== 文件（deploy/functions → ECS）===")
    total = 0
    sha_map = {}
    for label, local, remote, mode in UPLOAD_FILES:
        size = os.path.getsize(local)
        total += size
        sha = _sha256(local)
        sha_map[remote] = sha
        print("  %-38s %7d B  %o  %s" % (label, size, mode, remote))
    print("  合计 %d B（分片上传 %d 条命令）" % (total, sum(
        (os.path.getsize(f[1]) * 4 // 3 + CHUNK - 1) // CHUNK for f in UPLOAD_FILES)))
    print()
    print("=== systemd ===")
    for job in JOB_ORDER:
        print("  %s.service  TimeoutStartSec=%s" % (service_name(job), _runtime_start_timeout(job)))
        print("  %s.timer    OnCalendar=%s  Persistent=true" % (service_name(job), JOBS[job]["on_calendar"]))
    print()
    print("=== %s（脱敏）===" % ENV_FILE)
    print(redact_env_text(build_env_text(base)))
    print()
    return sha_map


def cmd_install(ns):
    base, kind = resolve_target(ns.backend, ns.base, ns.allow_live)
    if ns.dry_run:
        build_plan(base, kind)
        print("=== install: dry-run 结束（未连接 ECS、未写任何文件）===")
        return 0

    print("=== 0. 探活目标后端（只读）===")
    http, note = probe_base(base)
    if http == 0:
        print("[warn] 目标后端不可达：%s -> 任务会失败（timer 仍禁用）" % note)
    else:
        print("[probe] %s -> HTTP %s（%s）" % (base, http, note))
        if http == 404:
            print("[warn] 404：staging 路由可能还没就绪（P1 未完成）；安装继续，timer 保持禁用")

    print("\n=== 1. 准备上传目录 ===")
    st, rc, _ = _run(script_prep(), "jobs-prep", timeout=120, wait=180)
    if not _ok(st, rc):
        print("[install] prep 失败")
        return 1

    print("\n=== 2. 分片上传代码（deploy/functions → ECS）===")
    sha_map = {}
    for idx, (label, local, remote, mode) in enumerate(UPLOAD_FILES):
        with open(local, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        sha_map[remote] = _sha256(local)
        chunks = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)]
        for ci, chunk in enumerate(chunks, start=1):
            st, rc, _ = _run(script_chunk(idx, chunk), "jobs-chunk-%d-%d" % (idx, ci),
                             timeout=120, wait=180)
            if not _ok(st, rc):
                print("[install] 上传失败 file=%s chunk=%d/%d" % (label, ci, len(chunks)))
                return 1
        print("  [%d/%d] %s 上传完成（%d 片）" % (idx + 1, len(UPLOAD_FILES), label, len(chunks)))

    print("\n=== 3. 解码 + py_compile ===")
    st, rc, _ = _run(script_decode(UPLOAD_FILES), "jobs-decode", timeout=240, wait=360)
    if not _ok(st, rc):
        print("[install] 解码失败")
        return 1

    print("\n=== 4. 写 %s（600；不回显值）===" % ENV_FILE)
    st, rc, _ = _run(script_env(build_env_text(base)), "jobs-env", timeout=180, wait=300)
    if not _ok(st, rc):
        print("[install] jobs.env 写入失败")
        return 1

    print("\n=== 5. systemd unit + 状态目录 + 标记（timer 保持禁用）===")
    st, rc, _ = _run(script_units(sha_map), "jobs-units", timeout=240, wait=360)
    if not _ok(st, rc):
        print("[install] unit 安装失败")
        return 1

    print("\n=== 6. 自检 ===")
    st, rc, _ = _run(script_verify(), "jobs-verify", timeout=180, wait=300)
    print("\n[install] 完成：backend=%s；timer 全部禁用。"
          " 下一步：staging 冒烟 `smoke --job health_probe` → 切流后 `enable --confirm`" % kind)
    return 0 if _ok(st, rc) else 1


# ---------------------------------------------------------------- 其他子命令
def cmd_status(ns):
    st, rc, _ = _run(script_status(), "jobs-status", timeout=120, wait=240)
    return 0 if st == "Success" else 1


def cmd_smoke(ns):
    if ns.job not in JOBS:
        print("unknown job: %s (choose %s)" % (ns.job, ", ".join(JOB_ORDER)))
        return 2
    if ns.dry_run:
        print(script_smoke(ns.job))
        return 0
    # 本地先确认远端 env 后端是 staging（远端脚本内还有一道守卫）
    st, rc, out = _run(script_smoke(ns.job), "jobs-smoke-%s" % ns.job,
                       timeout=JOBS[ns.job]["timeout"], wait=600)
    if "REFUSE:" in (out or ""):
        print("[smoke] 远端拒绝：只允许 staging 后端")
        return 3
    return 0 if _ok(st, rc) and '"ok": true' in (out or "") else 1


def cmd_enable(ns):
    if not ns.confirm:
        print("拒绝：enable 会让定时任务真的写库；确认切流后加 --confirm")
        return 2
    if ns.dry_run:
        print(script_enable())
        return 0
    st, rc, _ = _run(script_enable(), "jobs-enable", timeout=120, wait=240)
    return 0 if _ok(st, rc) else 1


def cmd_disable(ns):
    if ns.dry_run:
        print(script_disable())
        return 0
    st, rc, _ = _run(script_disable(), "jobs-disable", timeout=120, wait=240)
    return 0 if _ok(st, rc) else 1


def cmd_uninstall(ns):
    if ns.purge and not ns.confirm:
        print("拒绝：--purge 会删 env/代码/心跳；确认后加 --confirm")
        return 2
    if ns.dry_run:
        print(script_uninstall(ns.purge))
        return 0
    st, rc, _ = _run(script_uninstall(ns.purge), "jobs-uninstall", timeout=120, wait=240)
    return 0 if _ok(st, rc) else 1


# ---------------------------------------------------------------- main
def main(argv=None):
    # 管道/重定向下强制 UTF-8（Windows 控制台默认 GBK 会让下游日志解码失败）
    try:
        if sys.stdout is not None and not sys.stdout.isatty():
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(
        prog="ecs_cron.py",
        description="CloudBase 云函数 → ECS systemd timer（云助手部署；默认禁用；默认 staging 后端）")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("install", help="安装代码/环境/systemd timer（默认 staging、timer 禁用）")
    p.add_argument("--backend", choices=["staging", "live"], default="staging")
    p.add_argument("--base", default=None, help="显式目标基址（默认按 --backend 选 staging/live）")
    p.add_argument("--allow-live", action="store_true", help="显式允许 live/自建生产后端")
    p.add_argument("--dry-run", action="store_true", help="只打印计划（env 脱敏），不连 ECS")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("status", help="只读：timer/心跳/env 键名/日志尾部")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("smoke", help="手动跑一轮（timer 仍禁用；只允许 staging 后端）")
    p.add_argument("--job", default="health_probe", choices=list(JOBS))
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_smoke)

    p = sub.add_parser("enable", help="启用三个 timer（需 --confirm）")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_enable)

    p = sub.add_parser("disable", help="停用三个 timer（保留文件/心跳）")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_disable)

    p = sub.add_parser("uninstall", help="删除 systemd unit；--purge 连 env/代码/心跳")
    p.add_argument("--purge", action="store_true")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_uninstall)

    ns = ap.parse_args(argv)
    if not getattr(ns, "func", None):
        ap.print_help()
        return 0
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
