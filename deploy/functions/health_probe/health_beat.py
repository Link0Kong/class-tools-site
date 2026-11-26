# -*- coding: utf-8 -*-
"""依赖服务健康心跳 —— 班级工具站「诊断」页的数据源（采集主机 + 云端巡检）。

契约（唯一标准）:
    G:\\ClassTools\\web\\tools\\tests\\dns_pause_tt_health_spec.md §4
    （原 13 行契约见 health_monitor_spec.md；2026-11-07 起扩为 18 行，新增 5 行均 kind=cloud）

18 个服务行 = 本机 local 10 行（本机 health_beat 写）+ 云端 cloud 8 行（云函数 health_probe 写）:
    cloud: cloudbase / site_static / site_tls / dns_domain / tt_cloud /
           cloud_power_sync / cloud_xgj_sync / cloud_health_probe
    local: collector_host / qqflow / weflow / briefdesk / watcher / ai /
           jwxt / hwauto / qq_client / wechat_client

用法:
    python health_beat.py --once             # 采集本机 local 10 行并写入云端（默认；云端 8 行由云函数写）
    python health_beat.py --once --all-rows  # 回滚/应急：本机代采并写全 18 行
    python health_beat.py --once --dry-run   # 只打印将写入的行（JSON），不写云端
    （不带参数 = --once；watchdog.py 每轮末尾调用 publish_from_watchdog()）

云端迁移（2026-11-06 phase2 / 2026-11-07 18 行）:
    CLOUD_OWNED_IDS（8 行）由 CloudBase 云函数 `health_probe`（每 5 分钟）写入；
    本机只写 local 10 行，避免双写互相覆盖。本机默认 collect() 也**不再探测**站点/DNS/TLS
    等云端行（网页暂停后不会每 5 分钟白等超时）；云函数改用 collect_cloud(base,key,token)。
    回滚：`health_beat.py --once --all-rows` 或环境变量 HEALTH_WRITE_ALL=1
    （watchdog 是每 5 分钟新起的进程，下一轮自动读取环境变量；不必手动重启任务）。

P3 自建后端（2026-11-18，默认行为不变）:
    base/key 统一走 scripts/cloud_backend.py（CLASS_CB_BASE / CLASS_CB_KEY，或
    secrets\\cloud.env 里的同名键；都不设时仍解析 index.html → CloudBase）。
    诊断行 id/状态/契约文本全不变，只新增 meta：
      * cloudbase.meta.backend = cloudbase / staging / selfhosted（探测的当前后端）；
      * cloud_health_probe.meta.runner = cloudbase-function / ecs-timer；
      * CLASS_JOB_HEARTBEAT=1（ECS jobs.env 打开）时，cloud_power_sync / cloud_xgj_sync
        读 ECS timer 心跳 <CLASS_JOBS_STATE>/<row_id>.json → meta.job，上一轮失败降级 warn。
    切换/回滚见 deploy/migration/PIPELINE.md。

P4 ECS PostgreSQL 监控并入 cloudbase 行（2026-11-18，默认行为不变）:
    round-3 的 class-tools-pg-monitor.timer 每 10 分钟写 ECS 本机
    /var/lib/class-tools/pg-monitor.json（pg_active/pgrest_active/pgrest_http/staging_http/
    backup_age_h/disk_use_pct/connections/db_size/backup_count/prod_mode/ok/ts）。
    **仅当 CLASS_CB_BASE 指向自建后端（staging/selfhosted）**时，health_probe job 读取该文件，
    把 PG 状态并入既有 `cloudbase` 行：detail 追加「· PG ok · 15 连接 · 23% 磁盘 · 备份 1h」，
    meta.pg = {ok,status,age_min,connections,disk_use_pct,backup_age_h,...}。
    **不新增 service_health 行（18 行契约不变）**；文件缺失/损坏/ts 超过 30 分钟 → 该行降级 warn；
    本机（Windows，无该目录）在 staging 模式下「优雅跳过」不改状态；CloudBase 模式**完全不读文件**，
    detail/meta 与 P3 完全一致（CloudBase 云函数行为不变）。

写入方式（spec §2）:
    GET  service_health?select=id 拿现有 id 集合 → 存在则逐行 PATCH，不存在则 POST。
    鉴权：Authorization: Bearer <CBK>（publishable key，设计上公开）
          X-Device-Id: <管理员班级 token>（只从 secrets\\class-token.json 读取，
          token 过期/被撤销时用 rpc/class_verify 自动刷新；**绝不打印/落盘到日志**）。

安全与稳健:
    * 纯标准库（urllib / ssl / subprocess / ctypes / socket），不依赖第三方包；
    * 所有子进程（Windows PowerShell / tasklist）一律 CREATE_NO_WINDOW，无可见窗口；
    * 任何异常都只写 G:\\ClassTools\\briefdesk\\logs\\health-beat.log，不向调用方抛出；
    * 日志单文件轮转（>1MB 保留尾部 300 行），日志内容只有状态码/耗时/文案，无 token。
"""

from __future__ import annotations

import json
import os
import re
import ssl
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# 路径 / 常量
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("BRIEFDESK_ROOT") or os.path.dirname(HERE)
LOGS = os.path.join(ROOT, "logs")
LOG = os.path.join(LOGS, "health-beat.log")
STATE = os.path.join(ROOT, "watchdog.state.json")
PAUSE = os.path.join(ROOT, "watchdog.pause")
SECRETS = os.path.join(ROOT, "secrets")
TOKEN_FILE = os.path.join(SECRETS, "class-token.json")

WEB_ROOT = os.environ.get("BRIEFDESK_WEB_ROOT") or r"G:\ClassTools\web"
INDEX = os.path.join(WEB_ROOT, "tools", "index.html")
TT_JSON = os.path.join(WEB_ROOT, "tools", "tt.json")

AI_LOG = os.path.join(LOGS, "ai-cloud.log")
HW_LOG = os.path.join(LOGS, "hw-auto.log")
HW_DATA = os.path.join(ROOT, "data", "auto-homework.json")
WATCH_LOG = os.path.join(LOGS, "docs-detect.log")

SITE_ORIGIN = "https://tool.furina.fun"
SITE_TT_URL = SITE_ORIGIN + "/tt.json"
TLS_HOST = "tool.furina.fun"
TLS_PORT = 443
SITE_HOST = TLS_HOST
SITE_CONFIG_ID = "web"          # public.site_config 行 id（网页暂停开关 value={paused,note,paused_at}）
DEFAULT_PAUSE_NOTE = "备案暂停"

# 云端行阈值（spec §4）
TT_FRESH_HOURS = 30.0           # 课表云端快照 meta.fetchedAt 年龄
TT_STALE_HOURS = 54.0
POWER_FRESH_HOURS = 2.0         # public.power.updated_at 最新行年龄
POWER_STALE_HOURS = 3.0
XGJ_FRESH_HOURS = 3.0           # public.homework xgj 行 ts 年龄
XGJ_STALE_HOURS = 5.0
XGJ_PREFIX = "auto_hw_xgj_en_"  # xgj_sync/index.py 的 OWN_PREFIX（实际前缀，spec 里写的 auto_xgj_en_ 有误）

QQFLOW_PORT = 5032
WEFLOW_PORT = 5033
BRIEFDESK_PORT = 3000
QQFLOW_TOKEN_FILE = os.path.join(SECRETS, "qqflow-token.txt")
WEFLOW_TOKEN_FILE = os.path.join(SECRETS, "weflow-token.txt")

# 管理员身份（class_verify 用）：从环境变量读取，真实学号/姓名不入库。
# 部署时在 CloudBase 函数环境变量里配置 CLASS_ADMIN_SID / CLASS_ADMIN_NAME；
# 未配置时的是占位值，class_verify 会失败（不会误用真实身份）。
ADMIN_SID = (os.environ.get("CLASS_ADMIN_SID") or "2024000001").strip()
ADMIN_NAME = (os.environ.get("CLASS_ADMIN_NAME") or "管理员").strip()

HTTP_TIMEOUT = 8.0          # 普通 HTTP（站点资源 / 云端 / 本地服务）
TLS_TIMEOUT = 15.0          # TLS 握手（实测外网抖动 1~9s，给足余量，避免误报 down）
PUBLISH_TIMEOUT = 15.0      # 云端写单行
PS_TIMEOUT = 25
STALE_STATE_AFTER = 600     # watchdog.state.json 里单项超过 10 分钟未更新 → 改为直连探测
VERY_STALE_STATE_AFTER = 900  # collector_host 判定 watchdog 轮次是否新鲜（仅记录 meta）

LOG_MAX_BYTES = 1_000_000
LOG_TAIL_LINES = 300
UA = "briefdesk-health-beat/1.0"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

PS_EXE = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"),
    "System32", "WindowsPowerShell", "v1.0", "powershell.exe")

# 18 个依赖服务：id → (显示名, kind)，顺序：站点与网页 / 云端后台 / 采集主机 / 本机服务
# kind=cloud 的 8 行由云函数 health_probe 写；static 2 行 + local 10 行由本机写。
SERVICE_DEFS = [
    ("cloudbase", "云端数据库", "cloud"),
    ("site_static", "站点资源", "static"),
    ("site_tls", "站点证书", "static"),
    ("dns_domain", "域名解析", "cloud"),
    ("tt_cloud", "课表云端数据", "cloud"),
    ("cloud_power_sync", "电费云同步", "cloud"),
    ("cloud_xgj_sync", "学工记云同步", "cloud"),
    ("cloud_health_probe", "云端巡检", "cloud"),
    ("collector_host", "采集主机", "local"),
    ("qqflow", "QQ 消息采集", "local"),
    ("weflow", "微信消息采集", "local"),
    ("briefdesk", "本地通知服务", "local"),
    ("watcher", "文档/通知监听", "local"),
    ("ai", "AI 识别", "local"),
    ("jwxt", "教务课表同步", "local"),
    ("hwauto", "作业自动整理", "local"),
    ("qq_client", "QQ 客户端", "local"),
    ("wechat_client", "微信客户端", "local"),
]
SERVICE_META = {sid: (name, kind) for sid, name, kind in SERVICE_DEFS}

# 云端迁移（2026-11-07 扩为 18 行）：这 8 行由 CloudBase 云函数 `health_probe`（每 5 分钟）写入；
# 本机只写其余 local 10 行，避免两边互相覆盖（两处写同一行会来回跳变 updated_at/status）。
CLOUD_OWNED_IDS = ("cloudbase", "site_static", "site_tls", "dns_domain", "tt_cloud",
                   "cloud_power_sync", "cloud_xgj_sync", "cloud_health_probe")
LOCAL_WRITE_IDS = tuple(sid for sid, _name, _kind in SERVICE_DEFS
                        if sid not in CLOUD_OWNED_IDS)
CLOUD_ROW_COUNT = len(CLOUD_OWNED_IDS)   # 云函数每轮写 8 行

# 每次 collect()/collect_cloud() 统一的检测时刻（unix ms）；本轮所有行共用，保证时间一致。
_CHECKED_AT = int(time.time() * 1000)

_TS_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
_CB_RE = re.compile(r'var CB="([^"]+)"')
_CBK_RE = re.compile(r'var CBK="([^"]+)"')


# ---------------------------------------------------------------------------
# 日志（单文件轮转：>1MB 保留尾部 300 行；pythonw 下无 stdout 也不崩）
# ---------------------------------------------------------------------------
def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = "[%s] %s" % (_now_str(), msg)
    try:
        os.makedirs(LOGS, exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX_BYTES:
            with open(LOG, "r", encoding="utf-8", errors="ignore") as fh:
                tail = fh.readlines()[-LOG_TAIL_LINES:]
            with open(LOG, "w", encoding="utf-8") as fh:
                fh.writelines(tail)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _emit(msg: str) -> None:
    """手动 CLI 输出；pythonw（sys.stdout is None）下静默。"""
    try:
        if sys.stdout is not None:
            sys.stdout.write(str(msg) + "\n")
            sys.stdout.flush()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _clip(text, limit: int = 60) -> str:
    s = "" if text is None else str(text)
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fmt_uptime(seconds) -> str:
    if seconds is None:
        return "未知"
    sec = int(max(0, seconds))
    days, rem = divmod(sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return "%d天%d小时" % (days, hours)
    if hours:
        return "%d小时%d分" % (hours, minutes)
    if minutes:
        return "%d分钟" % minutes
    return "%d秒" % sec


def _fmt_hhmm(epoch) -> str:
    try:
        return time.strftime("%H:%M", time.localtime(float(epoch)))
    except Exception:
        return "?"


def _fmt_age(seconds) -> str:
    sec = int(max(0, seconds))
    if sec < 120:
        return "%d 秒" % sec
    if sec < 7200:
        return "%d 分钟" % (sec // 60)
    if sec < 172800:
        return "%.1f 小时" % (sec / 3600.0)
    return "%.1f 天" % (sec / 86400.0)


_TS_ISO_TZ_RE = re.compile(r"^(.*[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?)([+-]\d{2})$")


def _parse_ts(value):
    """把 PostgREST 返回的时间戳解析为 epoch 秒；失败返回 None。

    兼容：unix 秒/毫秒（int/float/数字字符串）、ISO 字符串（Z / +08:00 / +08 / 空格分隔）。
    云函数运行时是 Python3.9（datetime.fromisoformat 不认 'Z' 与 '+08'，故先归一化）。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        return num / 1000.0 if num > 1e11 else num
    s = str(value).strip()
    if not s:
        return None
    if re.match(r"^\d+(?:\.\d+)?$", s):
        num = float(s)
        return num / 1000.0 if num > 1e11 else num
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = _TS_ISO_TZ_RE.match(s)
    if m:
        s = m.group(1) + m.group(2) + ":00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _age_hours(ts) -> float:
    return max(0.0, (time.time() - float(ts)) / 3600.0)


def _mtime(path: str):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _file_age(path: str):
    m = _mtime(path)
    return None if m is None else max(0.0, time.time() - m)


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def _read_secret_file(path: str) -> str:
    """只读拼接头用的 token 文件；内容绝不写日志。"""
    try:
        with open(path, "r", encoding="ascii", errors="ignore") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _tail_lines(path: str, count: int):
    """读文件尾部 count 行（最多读末尾 256KB）；文件不存在返回 None。"""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            span = min(size, 256 * 1024)
            fh.seek(size - span)
            data = fh.read()
    except OSError:
        return None
    try:
        text = data.decode("utf-8", "replace")
    except Exception:
        text = data.decode("latin-1", "replace")
    return text.splitlines()[-count:]


def _line_epoch(line: str):
    """从日志行 '[YYYY-MM-DD HH:MM:SS] ...' 解析 epoch 秒；失败返回 None。"""
    if not line:
        return None
    m = _TS_RE.search(line)
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 行构造
# ---------------------------------------------------------------------------
def _row(sid: str, status: str, detail: str, meta=None) -> dict:
    name, kind = SERVICE_META[sid]
    return {
        "id": sid,
        "name": name,
        "kind": kind,
        "status": status,
        "detail": _clip(detail, 60),
        "meta": meta if isinstance(meta, dict) else {},
        "checked_at": _CHECKED_AT,
    }


def _status_counts(rows) -> dict:
    counts = {"ok": 0, "warn": 0, "down": 0, "unknown": 0}
    for row in rows or []:
        key = row.get("status")
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def http_get(url: str, headers=None, timeout: float = HTTP_TIMEOUT):
    """GET 并读全部响应体。返回 (status, raw_bytes, latency_ms, error_text)。

    status=0 表示网络/协议异常（error_text 说明原因）；非 0 为 HTTP 状态码。
    绝不把 headers 内容写日志。
    """
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers=hdrs, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ms = int((time.perf_counter() - t0) * 1000)
            return int(resp.status), raw, ms, None
    except urllib.error.HTTPError as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        try:
            exc.read()
        except Exception:
            pass
        return int(exc.code), b"", ms, "HTTP %s" % int(exc.code)
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return 0, b"", ms, (str(exc).strip() or exc.__class__.__name__)[:160]


def _http_status_row(sid: str, status: int, ms: int, err, ok_detail: str,
                     meta_extra=None) -> dict:
    """cloudbase / site_static 共用阈值：2xx 且 <3000ms → ok；2xx 慢 → warn；失败 → down。"""
    meta = {"latency_ms": ms}
    if meta_extra:
        meta.update(meta_extra)
    if status and 200 <= status < 300:
        if ms < 3000:
            return _row(sid, "ok", "%s · %dms" % (ok_detail, ms), meta)
        return _row(sid, "warn", "%s · %dms（响应慢）" % (ok_detail, ms), meta)
    detail = "不可用：%s" % (err or ("HTTP %s" % status if status else "网络异常"))
    meta["error"] = (err or "HTTP %s" % status)[:160]
    return _row(sid, "down", detail, meta)


# ---------------------------------------------------------------------------
# CloudBase / 管理员 token（绝不打印 token）
# ---------------------------------------------------------------------------
def _cb_config():
    """后端基址/匿名 key（默认 index.html → CloudBase；CLASS_CB_BASE/KEY 可覆盖）。

    P3 迁移（2026-11-18）：统一走 scripts/cloud_backend.py；覆盖未设置时行为与原来完全
    一致（仍解析 index.html）。覆盖来源：进程环境变量 → secrets\\cloud.env 文件。
    """
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import cloud_backend as cb  # noqa: WPS433（同目录统一入口）
        return cb.resolve(INDEX)
    except ImportError:  # pragma: no cover - 同目录文件缺失时退回旧实现
        pass
    except Exception as exc:  # noqa: BLE001
        log("WARN cloud_backend.resolve failed: %r" % (exc,))
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import sync_notices_cloud as snc  # noqa: WPS433（同目录现成实现）
        return snc.cb_config()
    except Exception:
        pass
    text = _read_text(INDEX)
    base_m = _CB_RE.search(text)
    key_m = _CBK_RE.search(text)
    if not base_m or not key_m:
        raise RuntimeError("cannot parse CB/CBK from %s" % INDEX)
    return base_m.group(1), key_m.group(1)


def _ensure_token(base: str, key: str) -> str:
    """返回管理员班级 token：优先 sync_notices_cloud.get_token（exp 过期自动 class_verify）。"""
    try:
        sys.path.insert(0, HERE)
        import sync_notices_cloud as snc  # noqa: WPS433
        return snc.get_token(base, key)
    except Exception as exc:
        log("WARN get_token via sync_notices_cloud failed: %r" % (exc,))
    obj = _read_json(TOKEN_FILE)
    token = (obj.get("token") or "").strip()
    if not token:
        raise RuntimeError("no token in %s" % TOKEN_FILE)
    try:
        if float(obj.get("exp") or 0) <= time.time():
            raise RuntimeError("admin token expired")
    except (TypeError, ValueError):
        pass
    return token


def _force_refresh_token(base: str, key: str) -> str:
    """token 被撤销/仍过期时强制 class_verify 刷新并写回 secrets（不打印内容）。"""
    sys.path.insert(0, HERE)
    import sync_notices_cloud as snc  # noqa: WPS433
    status, out = snc.request(
        base, key, "rpc/class_verify",
        {"p_sid": ADMIN_SID, "p_name": ADMIN_NAME}, "POST")
    if status != 200 or not isinstance(out, dict) or not out.get("token"):
        raise RuntimeError("class_verify failed: HTTP %s" % status)
    token = out["token"]
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps({"token": token, "exp": time.time() + 86400 * 25},
                   ensure_ascii=False),
        encoding="utf-8")
    log("admin token refreshed via class_verify (exp renewed 25d; value not logged)")
    return token


def _cb_request(base, key, path, body=None, method="GET", token=None,
                timeout=PUBLISH_TIMEOUT):
    """CloudBase PostgREST 请求。返回 (status, parsed_or_text, latency_ms)；status=0=网络异常。"""
    headers = {"Authorization": "Bearer " + key,
               "Accept": "application/json",
               "User-Agent": UA}
    if token:
        headers["X-Device-Id"] = token
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ms = int((time.perf_counter() - t0) * 1000)
            parsed = None
            if raw:
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except Exception:
                    parsed = raw[:300].decode("utf-8", "replace")
            return int(resp.status), parsed, ms
    except urllib.error.HTTPError as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        try:
            exc.read()
        except Exception:
            pass
        return int(exc.code), None, ms
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return 0, (str(exc).strip() or exc.__class__.__name__)[:200], ms


def _list_health_ids(base, key, token):
    """GET service_health?select=id。返回 (status, set_ids_or_None, latency_ms)。"""
    status, parsed, ms = _cb_request(base, key, "service_health?select=id", token=token)
    if status == 200 and isinstance(parsed, list):
        return status, {row.get("id") for row in parsed if isinstance(row, dict)}, ms
    if status == 200:
        return status, set(), ms
    return status, None, ms


# ---------------------------------------------------------------------------
# P3 迁移：后端归类 + ECS 定时任务心跳（默认关闭，切流时启用）
# ---------------------------------------------------------------------------
# ECS 定时任务（替代 CloudBase 云函数，deploy/ecs_cron.py 部署）每轮写一个心跳 JSON：
#   /opt/class-tools/jobs/state/<row_id>.json
#   {"row":"cloud_power_sync","job":"power_sync","at_ms":<ms>,"ok":true,"rc":0,"ms":1234,
#    "runner":"ecs-timer","host":"..."}
# 开关：CLASS_JOB_HEARTBEAT=1（ecs_cron.py 写进 /etc/class-tools/jobs.env，默认不启用）。
# 未启用时本机/云函数行为完全不变（仍按 public.power / public.homework 数据年龄判定）。
JOB_HEARTBEAT_ROWS = {
    "cloud_power_sync": "power_sync",
    "cloud_xgj_sync": "xgj_sync",
    "cloud_health_probe": "health_probe",
}
DEFAULT_JOBS_STATE = "/opt/class-tools/jobs/state"
HEARTBEAT_FRESH_HOURS = {"cloud_power_sync": 6.0, "cloud_xgj_sync": 8.0}
HEALTH_RUNNER_DEFAULT = "cloudbase-function"


def _jobs_state_dir():
    return os.environ.get("CLASS_JOBS_STATE") or DEFAULT_JOBS_STATE


def job_heartbeat_enabled() -> bool:
    """CLASS_JOB_HEARTBEAT=1/true/yes/on 时启用 ECS timer 心跳判定（默认关闭）。"""
    return (os.environ.get("CLASS_JOB_HEARTBEAT") or "").strip().lower() in (
        "1", "true", "yes", "on")


def health_runner() -> str:
    """本进程写 cloud_health_probe 时的执行器标签：cloudbase-function / ecs-timer。"""
    return (os.environ.get("CLASS_HEALTH_RUNNER") or "").strip() or HEALTH_RUNNER_DEFAULT


def read_job_heartbeat(row_id: str, state_dir=None):
    """读 ECS 定时任务心跳 <state>/<row_id>.json；不存在/损坏/无时间 → None。绝不抛出。"""
    path = os.path.join(state_dir or _jobs_state_dir(), str(row_id) + ".json")
    try:
        data = _read_json(path)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    try:
        at_ms = int(data.get("at_ms") or 0)
    except (TypeError, ValueError):
        return None
    if at_ms <= 0:
        return None
    return {
        "row": str(data.get("row") or row_id),
        "job": str(data.get("job") or JOB_HEARTBEAT_ROWS.get(row_id, "")),
        "at_ms": at_ms,
        "ok": bool(data.get("ok")),
        "rc": data.get("rc"),
        "ms": data.get("ms"),
        "runner": str(data.get("runner") or ""),
        "host": str(data.get("host") or ""),
    }


def collect_job_heartbeats(state_dir=None) -> dict:
    """CLASS_JOB_HEARTBEAT 开启时返回 {row_id: heartbeat}；关闭（默认）返回 {}。"""
    if not job_heartbeat_enabled():
        return {}
    out = {}
    for row_id in JOB_HEARTBEAT_ROWS:
        hb = read_job_heartbeat(row_id, state_dir)
        if hb:
            out[row_id] = hb
    return out


def backend_info(base=None) -> dict:
    """后端归类（cloudbase/staging/selfhosted），供诊断行 meta 使用。"""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import cloud_backend as cb  # noqa: WPS433（同目录统一入口）
        return {"backend": cb.backend_kind(base or "")}
    except Exception:  # noqa: BLE001
        low = str(base or "").lower()
        if "tcloudbasegateway.com" in low:
            return {"backend": "cloudbase"}
        if "/rest-next/" in low:
            return {"backend": "staging"}
        return {"backend": "selfhosted" if low.startswith("http") else "unknown"}


def apply_job_heartbeat(row, heartbeat, row_id=None, max_age_hours=None):
    """把 ECS timer 心跳合并进 cloud_* 行；无心跳时原样返回。

    * 只加 meta["job"]（时间/结果/耗时，**不含任何凭据**），detail 契约文本保持不变；
    * 心跳新鲜且 ok=false 时把 ok 降为 warn，detail 追加「（ECS 定时任务上轮失败）」；
    * 心跳过期（> max_age_hours）只标 meta["job"]["stale"]=true，不改状态。
    """
    if not isinstance(heartbeat, dict) or not heartbeat.get("at_ms"):
        return row
    row_id = row_id or str((row or {}).get("id") or heartbeat.get("row") or "")
    age_h = max(0.0, (time.time() - float(heartbeat["at_ms"]) / 1000.0) / 3600.0)
    limit = float(max_age_hours if max_age_hours is not None
                  else HEARTBEAT_FRESH_HOURS.get(row_id, 6.0))
    stale = age_h > limit
    job = {
        "runner": heartbeat.get("runner") or "ecs-timer",
        "job": heartbeat.get("job") or JOB_HEARTBEAT_ROWS.get(row_id, ""),
        "age_min": int(age_h * 60),
        "ok": bool(heartbeat.get("ok")),
        "stale": stale,
    }
    for key in ("rc", "ms"):
        if heartbeat.get(key) is not None:
            job[key] = heartbeat.get(key)
    out = dict(row or {})
    meta = dict(out.get("meta") or {})
    meta["job"] = job
    out["meta"] = meta
    if not stale and not job["ok"] and out.get("status") == "ok":
        out["status"] = "warn"
        out["detail"] = _clip((out.get("detail") or "") + "（ECS 定时任务上轮失败）", 60)
    return out


# ---------------------------------------------------------------------------
# P4：ECS PostgreSQL 监控并入 cloudbase 行（仅 staging/selfhosted；CloudBase 默认不读）
# ---------------------------------------------------------------------------
# 文件由 round-3 的 class-tools-pg-monitor.timer 每 10 分钟写（ECS 本机）：
#   {"pg_active":"active","pgrest_active":"active","pgrest_http":"200","staging_http":"200",
#    "backup_file":"...","backup_age_h":"1","disk_use_pct":"23","connections":"15",
#    "db_size":"73MB","backup_count":"3","prod_mode":"cloudbase","ok":true,
#    "ts":"2026-11-18T07:12:42+00:00"}
# 注意：除 ok(bool)/ts(str) 外字段值是**字符串**，这里统一宽容转数字。
PG_MONITOR_FILE = os.environ.get("CLASS_PG_MONITOR") or "/var/lib/class-tools/pg-monitor.json"
PG_MONITOR_STALE_MIN = 30.0
PG_MONITOR_KEYS = ("pg_active", "pgrest_active", "pgrest_http", "staging_http",
                   "backup_age_h", "disk_use_pct", "connections", "db_size",
                   "backup_count", "prod_mode")


def _pg_monitor_path(path=None):
    return path or os.environ.get("CLASS_PG_MONITOR") or PG_MONITOR_FILE


def _num(value):
    """宽容转数字（监控 JSON 数字是字符串）；非法 → None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("%", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pg_monitor_expected(path=None):
    """本机是否「应该」有该监控文件：ECS 上目录 /var/lib/class-tools 存在；Windows 本机不存在 → 跳过。

    显式开关 CLASS_PG_MONITOR_STRICT=1 时强制视为 expected（离线单测/排障用）。
    """
    if (os.environ.get("CLASS_PG_MONITOR_STRICT") or "").strip().lower() in (
            "1", "true", "yes", "on"):
        return True
    return os.path.isdir(os.path.dirname(_pg_monitor_path(path)) or ".")


def read_pg_monitor(path=None):
    """读取并归一化 ECS PG 监控 JSON；不存在/损坏 → None。绝不抛出。"""
    path = _pg_monitor_path(path)
    try:
        data = _read_json(path)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    ts = _parse_ts(data.get("ts"))
    rec = {
        "source": path,
        "ts": data.get("ts"),
        "at": (int(ts * 1000) if ts is not None else None),
        "age_min": (round(max(0.0, (time.time() - float(ts)) / 60.0), 1)
                    if ts is not None else None),
        "ok": bool(data.get("ok")),
    }
    for key in PG_MONITOR_KEYS:
        value = data.get(key)
        if key in ("pg_active", "pgrest_active", "db_size", "prod_mode"):
            rec[key] = str(value or "")[:40]
        else:
            rec[key] = _num(value)
    backup_file = str(data.get("backup_file") or "")
    if backup_file:
        rec["backup_file"] = os.path.basename(backup_file)[:80]  # 只留文件名，不暴露服务器目录
    return rec


def pg_monitor_status(rec):
    """纯函数：(state, suffix, reasons)。state ∈ ok / warn / missing / stale / invalid。"""
    if rec is None:
        return "missing", "PG 监控缺失", []
    age_min = rec.get("age_min")
    if age_min is None:
        return "invalid", "PG 监控时间无效", []
    if float(age_min) > PG_MONITOR_STALE_MIN:
        return "stale", "PG 监控过期 %d 分钟" % int(float(age_min)), []
    if not rec.get("ok"):
        reasons = []
        if rec.get("pg_active") and rec["pg_active"] != "active":
            reasons.append("PG")
        if rec.get("pgrest_active") and rec["pgrest_active"] != "active":
            reasons.append("PGrest")
        backup_age = rec.get("backup_age_h")
        if backup_age is not None and backup_age > 36:
            reasons.append("备份%dh" % int(backup_age))
        disk_pct = rec.get("disk_use_pct")
        if disk_pct is not None and disk_pct > 85:
            reasons.append("磁盘%d%%" % int(disk_pct))
        conns = rec.get("connections")
        if conns is not None and conns >= 72:
            reasons.append("连接%d" % int(conns))
        return "warn", "PG 异常(%s)" % ("/".join(reasons) or "监控 ok=false"), reasons
    suffix = "PG ok"
    conns = rec.get("connections")
    if conns is not None:
        suffix += " · %d 连接" % int(conns)
    disk_pct = rec.get("disk_use_pct")
    if disk_pct is not None:
        suffix += " · %d%% 磁盘" % int(disk_pct)
    backup_age = rec.get("backup_age_h")
    if backup_age is not None:
        suffix += " · 备份 %dh" % int(backup_age)
    return "ok", suffix, []


def attach_pg_monitor(row, backend, monitor=None, path=None, expected=None):
    """把 ECS PG 监控并入 cloudbase 行（**仅 staging/selfhosted**；返回新 dict，不改入参）。

    * CloudBase 模式直接原样返回（不读文件，行为与 P3 一致）；
    * 本机无监控目录（Windows）→ meta.pg={"skipped":true}，状态不变（优雅跳过）；
    * 文件缺失/损坏/ts 过期(>30min)/监控 ok=false → 该行由 ok 降级 warn，detail 注明原因；
    * 18 行契约不变：只改既有 cloudbase 行，不新增 id。
    """
    if backend not in ("staging", "selfhosted"):
        return row
    path = _pg_monitor_path(path)
    if expected is None:
        expected = _pg_monitor_expected(path)
    out = dict(row or {})
    meta = dict(out.get("meta") or {})
    if not expected:
        meta["pg"] = {"skipped": True, "reason": "no-monitor-file-on-host", "source": path}
        out["meta"] = meta
        return out
    rec = read_pg_monitor(path) if monitor is None else monitor
    state, suffix, reasons = pg_monitor_status(rec)
    pg = dict(rec or {})
    pg.update({"status": state, "expected": True})
    if reasons:
        pg["reasons"] = reasons
    meta["pg"] = pg
    out["meta"] = meta
    out["detail"] = _clip((out.get("detail") or "") + " · " + suffix, 60)
    if state != "ok" and out.get("status") == "ok":
        out["status"] = "warn"
    if state != "ok":
        log("pg monitor %s: %s" % (state, suffix))
    return out


# ---------------------------------------------------------------------------
# 主机信息（开机时长 + QQ/微信进程）—— 一律无窗口
# ---------------------------------------------------------------------------
_PS_HOST_SCRIPT = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$os = Get-CimInstance Win32_OperatingSystem;"
    "if ($os) { 'UPTIME ' + [int64]((Get-Date) - $os.LastBootUpTime).TotalSeconds }"
    " else { 'UPTIME ?' };"
    "Get-Process -Name QQ,Weixin | ForEach-Object {"
    " 'PROC ' + $_.ProcessName + ' ' + $_.Id }"
)


def _run_ps(script: str, timeout: float = PS_TIMEOUT):
    """隐藏执行 Windows PowerShell，返回 stdout 文本；不可用/失败返回 None。"""
    if not os.path.exists(PS_EXE):
        return None
    try:
        cp = subprocess.run(
            [PS_EXE, "-NoProfile", "-NonInteractive", "-Command", script],
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
        if cp.returncode != 0 and not (cp.stdout or "").strip():
            return None
        return cp.stdout or ""
    except Exception as exc:
        log("WARN powershell probe failed: %r" % (exc,))
        return None


def _uptime_via_ctypes():
    """GetTickCount64（纯标准库，比 CIM 快且同样无窗口）。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        try:
            kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        except Exception:
            pass
        return float(kernel32.GetTickCount64()) / 1000.0
    except Exception:
        return None


def _tasklist_procs():
    """退化扫描 QQ.exe / Weixin.exe（没有命令行，只有名字+pid）。返回 dict 或 None。"""
    try:
        cp = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="mbcs", errors="replace",
            timeout=30, creationflags=CREATE_NO_WINDOW,
        )
        out = {"QQ": [], "Weixin": []}
        for line in (cp.stdout or "").splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) < 2:
                continue
            name = parts[0].strip('"').lower()
            if name not in ("qq.exe", "weixin.exe"):
                continue
            try:
                pid = int(parts[1].strip('"'))
            except ValueError:
                continue
            out["QQ" if name == "qq.exe" else "Weixin"].append(pid)
        return out
    except Exception as exc:
        log("WARN tasklist probe failed: %r" % (exc,))
        return None


def scan_host():
    """返回 (uptime_s or None, {'QQ': [pid...], 'Weixin': [pid...]} or None)。

    procs 为 None 表示进程枚举不可用（此时客户端状态应为 unknown 而不是 down）。
    """
    text = _run_ps(_PS_HOST_SCRIPT)
    if text is not None:
        uptime = None
        procs = {"QQ": [], "Weixin": []}
        for line in text.splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == "UPTIME" and len(parts) >= 2:
                try:
                    uptime = float(parts[1])
                except ValueError:
                    uptime = None
            elif parts[0] == "PROC" and len(parts) >= 3:
                try:
                    pid = int(parts[2])
                except ValueError:
                    continue
                procs.setdefault(parts[1], []).append(pid)
        if uptime is None:
            uptime = _uptime_via_ctypes()
        return uptime, procs
    return _uptime_via_ctypes(), _tasklist_procs()


# ---------------------------------------------------------------------------
# watchdog.state.json
# ---------------------------------------------------------------------------
def load_state() -> dict:
    try:
        data = _read_json(STATE)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _state_service(state, key: str) -> dict:
    try:
        rec = ((state or {}).get("services") or {}).get(key)
        return rec if isinstance(rec, dict) else {}
    except Exception:
        return {}


def _rec_age(rec: dict):
    """watchdog 记录 lastCheck（'%Y-%m-%d %H:%M:%S'）距今秒数；无记录返回 None。"""
    last = (rec or {}).get("lastCheck")
    if not last:
        return None
    try:
        ts = time.mktime(time.strptime(last, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None
    return max(0.0, time.time() - ts)


def _state_fresh(rec: dict) -> bool:
    age = _rec_age(rec)
    return age is not None and age <= STALE_STATE_AFTER


# ---------------------------------------------------------------------------
# 探测器：站点 / 云端（spec §4；云端行由云函数 health_probe 调用）
# ---------------------------------------------------------------------------
def detect_cloudbase(base: str, key: str, token) -> dict:
    if not base or not key:
        return _row("cloudbase", "unknown", "云端配置缺失（CB/CBK 未解析）", {})
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
    if token:
        headers["X-Device-Id"] = token
    status, _raw, ms, err = http_get(
        base + "service_health?select=id&limit=1", headers=headers)
    row = _http_status_row("cloudbase", status, ms, err, "HTTP 200",
                           {"url": base + "service_health"})
    # P3：id 保持 cloudbase（页面契约不变），meta 标出当前探测的后端（cloudbase/staging/selfhosted）。
    backend = backend_info(base)["backend"]
    row["meta"]["backend"] = backend
    # P4：自建后端模式下并入 ECS PG 监控（CloudBase 模式不读文件，行为与 P3 完全一致）。
    return attach_pg_monitor(row, backend)


def read_site_config(base: str, key: str, token=None) -> dict:
    """读 public.site_config 行 id='web' 的 value（网页暂停开关）。

    读不到/无权限/网络异常一律返回 {}（调用方按 paused=false 处理，绝不因配置缺失而误报暂停）。
    """
    if not base or not key:
        return {}
    try:
        status, parsed, _ms = _cb_request(
            base, key, "site_config?select=value&id=eq." + SITE_CONFIG_ID, token=token)
    except Exception as exc:
        log("WARN read site_config failed: %r" % (exc,))
        return {}
    if status == 200 and isinstance(parsed, list) and parsed:
        value = parsed[0].get("value") if isinstance(parsed[0], dict) else None
        if isinstance(value, dict):
            return value
    return {}


def _paused_row(sid: str, note: str) -> dict:
    """暂停语义行（spec §4）：site_static/site_tls 在网页暂停时 warn 并跳过真实探测。"""
    note = _clip(note or DEFAULT_PAUSE_NOTE, 40)
    detail = "网页已按备案安排暂停（%s）" % note
    return _row(sid, "warn", detail, {"paused": True, "note": note})


def detect_site_static(paused: bool = False, note: str = "") -> dict:
    """站点资源：paused=true 时直接 warn「网页已按备案安排暂停」并跳过探测。"""
    if paused:
        return _paused_row("site_static", note)
    row = _probe_site_static()
    row["meta"]["paused"] = False
    return row


def _probe_site_static() -> dict:
    status, raw, ms, err = http_get(SITE_TT_URL)
    return _http_status_row("site_static", status, ms, err, "HTTP 200",
                            {"url": SITE_TT_URL, "bytes": len(raw)})


def detect_site_tls(paused: bool = False, note: str = "") -> dict:
    """站点证书：paused=true 时直接 warn「网页已按备案安排暂停」并跳过 TLS 探测。"""
    if paused:
        return _paused_row("site_tls", note)
    row = _probe_site_tls()
    row["meta"]["paused"] = False
    return row


def _probe_site_tls() -> dict:
    """TLS 握手 + 证书剩余天数：>21 ok；8–21 warn；≤7 或握手失败 down。"""
    t0 = time.perf_counter()
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((TLS_HOST, TLS_PORT), timeout=TLS_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=TLS_HOST) as tls:
                cert = tls.getpeercert()
                protocol = tls.version()
        ms = int((time.perf_counter() - t0) * 1000)
        not_after = (cert or {}).get("notAfter")
        if not not_after:
            return _row("site_tls", "down", "证书信息缺失",
                        {"latency_ms": ms, "host": TLS_HOST})
        exp = ssl.cert_time_to_seconds(not_after)
        days = (exp - time.time()) / 86400.0
        meta = {"days_left": round(days, 2), "not_after": not_after,
                "latency_ms": ms, "host": TLS_HOST, "protocol": protocol,
                "verified": True}
        if days > 21:
            return _row("site_tls", "ok", "证书剩余 %d 天" % int(days), meta)
        if days > 7:
            return _row("site_tls", "warn", "证书仅剩 %d 天" % int(days), meta)
        return _row("site_tls", "down", "证书 %d 天后到期" % max(0, int(days)), meta)
    except ssl.SSLCertVerificationError as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return _row("site_tls", "down", "证书校验失败",
                    {"latency_ms": ms, "host": TLS_HOST,
                     "error": (str(exc) or "SSLCertVerificationError")[:120]})
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return _row("site_tls", "down", "TLS 握手失败",
                    {"latency_ms": ms, "host": TLS_HOST,
                     "error": (str(exc) or exc.__class__.__name__)[:120]})


def detect_dns_domain(paused: bool = False) -> dict:
    """域名解析（spec §4）：paused 状态下解析失败=符合预期(ok)、仍解析=warn。"""
    addrs = []
    err = None
    try:
        infos = socket.getaddrinfo(SITE_HOST, TLS_PORT, proto=socket.IPPROTO_TCP)
        for info in infos or []:
            try:
                ip = info[4][0]
            except (IndexError, TypeError):
                continue
            if ip and ip not in addrs:
                addrs.append(ip)
    except Exception as exc:  # noqa: BLE001  DNS 失败是常态（暂停后）
        err = (str(exc).strip() or exc.__class__.__name__)[:120]
    resolved = bool(addrs)
    meta = {"host": SITE_HOST, "addrs": addrs[:8], "paused": bool(paused)}
    if err:
        meta["error"] = err
    if paused:
        if resolved:
            return _row("dns_domain", "warn", "仍在解析（请检查暂停操作）", meta)
        return _row("dns_domain", "ok", "已暂停（符合预期）", meta)
    if resolved:
        return _row("dns_domain", "ok", "解析正常", meta)
    return _row("dns_domain", "down", "无法解析", meta)


def detect_tt_cloud(base: str, key: str, token=None) -> dict:
    """课表云端数据（spec §4）：site_assets 行 id='tt' 的 meta.fetchedAt 年龄。"""
    if not base or not key:
        return _row("tt_cloud", "unknown", "云端配置缺失（CB/CBK 未解析）", {})
    status, parsed, ms = _cb_request(
        base, key, "site_assets?select=meta,updated_at&id=eq.tt", token=token)
    if status != 200:
        return _row("tt_cloud", "unknown", "读取云端课表失败（HTTP %s）" % status,
                    {"http": status, "latency_ms": ms})
    if not isinstance(parsed, list) or not parsed:
        return _row("tt_cloud", "down", "云端未发布课表快照", {"http": 200})
    rec = parsed[0] if isinstance(parsed[0], dict) else {}
    meta_in = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
    ts = _parse_ts(meta_in.get("fetchedAt")) or _parse_ts(rec.get("updated_at"))
    if ts is None:
        return _row("tt_cloud", "down", "云端课表缺少同步时间",
                    {"http": 200, "updated_at": rec.get("updated_at")})
    hours = _age_hours(ts)
    meta = {"fetchedAt": int(float(ts) * 1000), "age_hours": round(hours, 2),
            "count": meta_in.get("count"), "termStart": meta_in.get("termStart"),
            "updated_at": rec.get("updated_at")}
    if hours <= TT_FRESH_HOURS:
        return _row("tt_cloud", "ok", "云端快照 %.1f 小时前同步" % hours, meta)
    if hours <= TT_STALE_HOURS:
        return _row("tt_cloud", "warn", "云端快照 %.1f 小时前同步（偏旧）" % hours, meta)
    return _row("tt_cloud", "down", "云端快照 %.1f 天未同步" % (hours / 24.0), meta)


def detect_cloud_power_sync(base: str, key: str, token=None, heartbeat=None) -> dict:
    """电费云同步（spec §4）：public.power 最新行 updated_at 年龄。

    P3：heartbeat（ECS timer 心跳）可选；传入时只补 meta["job"]/失败降级，detail 契约不变。
    """
    row = _detect_cloud_power_sync_row(base, key, token)
    return apply_job_heartbeat(row, heartbeat, "cloud_power_sync")


def _detect_cloud_power_sync_row(base: str, key: str, token=None) -> dict:
    """按 public.power 最新行 updated_at 判定（原逻辑，行为不变）。"""
    if not base or not key:
        return _row("cloud_power_sync", "unknown", "云端配置缺失（CB/CBK 未解析）", {})
    status, parsed, ms = _cb_request(
        base, key, "power?select=updated_at&order=updated_at.desc&limit=1", token=token)
    if status != 200:
        return _row("cloud_power_sync", "unknown", "读取电费数据失败（HTTP %s）" % status,
                    {"http": status, "latency_ms": ms})
    if not isinstance(parsed, list) or not parsed:
        return _row("cloud_power_sync", "warn", "电费无数据", {"http": 200})
    rec = parsed[0] if isinstance(parsed[0], dict) else {}
    ts = _parse_ts(rec.get("updated_at"))
    if ts is None:
        return _row("cloud_power_sync", "warn", "电费数据缺少更新时间",
                    {"http": 200, "updated_at": rec.get("updated_at")})
    age = max(0.0, time.time() - float(ts))
    hours = age / 3600.0
    meta = {"updated_at": rec.get("updated_at"), "age_min": int(age // 60)}
    if hours <= POWER_FRESH_HOURS:
        return _row("cloud_power_sync", "ok", "最近同步 %s前" % _fmt_age(age), meta)
    if hours <= POWER_STALE_HOURS:
        return _row("cloud_power_sync", "warn", "最近同步 %s前（偏旧）" % _fmt_age(age), meta)
    return _row("cloud_power_sync", "down", "最近同步 %s前（已停滞）" % _fmt_age(age), meta)


def detect_cloud_xgj_sync(base: str, key: str, token=None, heartbeat=None) -> dict:
    """学工记云同步（spec §4）：public.homework 中 auto_hw_xgj_en_* 最新行的 ts 年龄。

    P3：heartbeat（ECS timer 心跳）可选；传入时只补 meta["job"]/失败降级，detail 契约不变。
    """
    row = _detect_cloud_xgj_sync_row(base, key, token)
    if (row.get("meta", {}).get("job") or {}).get("at_ms"):
        return row
    return apply_job_heartbeat(row, heartbeat, "cloud_xgj_sync")


def _detect_cloud_xgj_sync_row(base: str, key: str, token=None) -> dict:
    """优先按写入回执判断作业任务；旧作业只用来显示内容发布时间。"""
    rid = "cloud_xgj_sync"
    if not base or not key:
        return _row(rid, "unknown", "云端配置缺失（CB/CBK 未解析）", {})
    status, rows, ms = _cb_request(
        base, key, "site_assets?select=id,body&id=in.(xgj-sync-status,xgj-sync-status-local)",
        token=token)
    if status != 200 or not isinstance(rows, list):
        return _row(rid, "unknown", "读取学工记同步回执失败（HTTP %s）" % status,
                    {"http": status, "latency_ms": ms})

    jobs = {}
    for row in rows:
        job = row.get("body") if isinstance(row, dict) else None
        if not isinstance(job, dict) or type(job.get("ok")) is not bool:
            continue
        at = _parse_ts(job.get("at_ms"))
        if at is not None:
            jobs[row["id"]] = (job, _age_hours(at))
    if jobs:
        cloud = jobs.get("xgj-sync-status")
        local = jobs.get("xgj-sync-status-local")
        if cloud and cloud[0]["ok"] and cloud[1] <= XGJ_FRESH_HOURS:
            job, hours = cloud
            note = "同步成功，暂无待同步作业" if job.get("pending") == 0 else "同步成功"
            return _row(rid, "ok", "学工记%s（%.1f 小时前）" % (note, hours),
                        {"job": job, "age_hours": round(hours, 2)})
        if local and local[0]["ok"] and local[1] <= XGJ_FRESH_HOURS:
            job, hours = local
            return _row(rid, "warn", "云任务回执异常，本机 %.1f 小时前已补同步" % hours,
                        {"job": cloud[0] if cloud else {}, "fallback": job,
                         "age_hours": round(hours, 2)})
        if cloud:
            job, hours = cloud
            label = "上轮同步失败" if not job["ok"] else "已 %.1f 小时无同步回执" % hours
            state = "warn" if job["ok"] and hours <= XGJ_STALE_HOURS else "down"
            return _row(rid, state, "学工记" + label, {"job": job, "age_hours": round(hours, 2)})

    status, rows, _ = _cb_request(
        base, key, "homework?select=ts&id=like." + XGJ_PREFIX + "*&order=ts.desc&limit=1", token=token)
    ts = _parse_ts(rows[0].get("ts")) if status == 200 and isinstance(rows, list) and rows else None
    note = "尚无学工记同步回执"
    if ts is not None:
        note += "；最新作业发布于 %.1f 小时前" % _age_hours(ts)
    return _row(rid, "unknown", note, {"http": status})


def detect_cloud_health_probe(rows: int = CLOUD_ROW_COUNT, patched: int = 0,
                              posted: int = 0, ms: int = 0, runner: str = None) -> dict:
    """云端巡检（spec §4）：云函数/ECS timer 每轮写自身行，status=ok + 本轮行数/耗时。

    P3：runner 标记执行器（cloudbase-function / ecs-timer），只进 meta，detail 契约不变。
    """
    return _row("cloud_health_probe", "ok",
                "本轮完成 · %d 行 · %dms" % (int(rows), int(ms)),
                {"rows": int(rows), "patched": int(patched),
                 "posted": int(posted), "ms": int(ms),
                 "runner": runner or health_runner()})



# ---------------------------------------------------------------------------
# 探测器：采集主机 / 本地服务
# ---------------------------------------------------------------------------
def detect_collector_host(state, round_info, pause: bool) -> dict:
    round_info = round_info or {}
    uptime = round_info.get("uptime_s")
    if uptime is None:
        uptime = _uptime_via_ctypes()
    state = state or {}
    round_secs = round_info.get("round_secs")
    meta = {
        "uptime_s": int(uptime) if uptime is not None else None,
        "boot_ts": int((time.time() - uptime) * 1000) if uptime is not None else None,
        "watchdog_updated": state.get("updated"),
        "round_secs": round(float(round_secs), 1) if round_secs is not None else None,
        "scanner": state.get("scanner"),
        "pause": bool(pause),
        "pid": os.getpid(),
    }
    if pause:
        return _row("collector_host", "warn", "采集已暂停", meta)
    detail = "在线 %s" % _fmt_uptime(uptime)
    if round_secs is not None:
        detail += " · 上轮 %.0fs" % float(round_secs)
    return _row("collector_host", "ok", detail, meta)


def _probe_health_account(key: str):
    """直连探测 qqflow/weflow：/health + /api/v1/accounts。返回 dict 或 None。"""
    port = QQFLOW_PORT if key == "qqflow" else WEFLOW_PORT
    status, _raw, ms, err = http_get("http://127.0.0.1:%d/health" % port, timeout=6.0)
    if status != 200:
        return {"healthy": False, "ready": None, "latency_ms": ms,
                "error": err or "HTTP %s" % status}
    token = _read_secret_file(
        QQFLOW_TOKEN_FILE if key == "qqflow" else WEFLOW_TOKEN_FILE)
    ready = None
    message_count = None
    latency = ms
    if token:
        st2, raw2, ms2, _err2 = http_get(
            "http://127.0.0.1:%d/api/v1/accounts" % port,
            headers={"Authorization": "Bearer " + token}, timeout=8.0)
        latency = ms2
        if st2 == 200:
            try:
                data = json.loads(raw2.decode("utf-8")) if raw2 else {}
            except Exception:
                data = {}
            accounts = data.get("accounts") if isinstance(data, dict) else None
            if isinstance(accounts, list):
                ready = any(isinstance(a, dict) and a.get("state") == "ready"
                            for a in accounts)
                for a in accounts:
                    if isinstance(a, dict) and a.get("state") == "ready":
                        message_count = a.get("message_count")
                        break
    return {"healthy": True, "ready": ready, "latency_ms": latency,
            "message_count": message_count}


def detect_account_service(state, key: str) -> dict:
    """qqflow / weflow：健康 + 账号 ready → ok；健康但账号不 ready → warn；HTTP 不通 → down。"""
    rec = _state_service(state, key)
    probe = None
    if not _state_fresh(rec):
        probe = _probe_health_account(key)
    if probe is not None:
        healthy = probe["healthy"]
        ready = probe["ready"]
        meta = {"source": "probe", "latency_ms": probe.get("latency_ms"),
                "message_count": probe.get("message_count")}
        if not healthy:
            meta["error"] = probe.get("error")
    else:
        healthy = bool(rec.get("healthy"))
        ready = rec.get("accountReady")
        meta = {"source": "watchdog.state",
                "last_check": rec.get("lastCheck"),
                "failures": rec.get("failures"),
                "account_ready": ready,
                "last_error": (rec.get("lastError") or "")[:120]}
    label = "QQ" if key == "qqflow" else "微信"
    if not healthy:
        return _row(key, "down", "%s消息服务 HTTP 不通" % label, meta)
    if ready is True:
        detail = "健康 · 账号就绪"
        if meta.get("message_count") is not None:
            detail = "健康 · 账号就绪（%s 条消息）" % meta["message_count"]
        return _row(key, "ok", detail, meta)
    if ready is False:
        return _row(key, "warn", "健康，但账号未就绪", meta)
    return _row(key, "unknown", "健康，账号状态未知", meta)


def _probe_briefdesk():
    status, _raw, ms, err = http_get(
        "http://127.0.0.1:%d/api/status" % BRIEFDESK_PORT, timeout=6.0)
    return status == 200, ms, err


def detect_briefdesk(state) -> dict:
    rec = _state_service(state, "briefdesk")
    if _state_fresh(rec):
        healthy = bool(rec.get("healthy"))
        meta = {"source": "watchdog.state", "last_check": rec.get("lastCheck"),
                "failures": rec.get("failures"),
                "last_error": (rec.get("lastError") or "")[:120]}
    else:
        healthy, ms, err = _probe_briefdesk()
        meta = {"source": "probe", "latency_ms": ms}
        if err:
            meta["error"] = err
    if healthy:
        return _row("briefdesk", "ok", "服务正常（HTTP 200）", meta)
    return _row("briefdesk", "down", "本地通知服务不可用", meta)


def detect_watcher(state) -> dict:
    rec = _state_service(state, "detect_docs")
    fresh = _state_fresh(rec)
    alive = bool(rec.get("healthy")) if fresh else None
    log_age = _file_age(WATCH_LOG)
    meta = {"log_age_s": int(log_age) if log_age is not None else None,
            "alive": alive, "source": "watchdog.state" if fresh else "log-only",
            "last_check": rec.get("lastCheck"), "failures": rec.get("failures")}
    if alive is False:
        return _row("watcher", "down", "监听进程未运行", meta)
    if log_age is None:
        return _row("watcher", "unknown", "无监听日志", meta)
    if log_age <= 300:
        return _row("watcher", "ok", "日志 %s前更新" % _fmt_age(log_age), meta)
    if log_age <= 600:
        return _row("watcher", "warn", "日志 %s未更新" % _fmt_age(log_age), meta)
    return _row("watcher", "down", "日志 %s未更新" % _fmt_age(log_age), meta)


# ---------------------------------------------------------------------------
# 探测器：日志/文件新鲜度
# ---------------------------------------------------------------------------
def detect_ai() -> dict:
    lines = _tail_lines(AI_LOG, 50)
    if lines is None:
        return _row("ai", "unknown", "无 AI 调用日志", {"log": AI_LOG})
    last_ok = None
    last_err = None
    for line in lines:
        low = line.lower()
        if "cloud ok" in low:
            last_ok = line
        elif any(tag in low for tag in ("error", "failed", "exception", "timed out")):
            last_err = line
    ok_ts = _line_epoch(last_ok) if last_ok else None
    err_ts = _line_epoch(last_err) if last_err else None
    meta = {"log": AI_LOG,
            "last_ok_at": ok_ts,
            "last_ok": (last_ok or "")[:160],
            "last_error_at": err_ts,
            "last_error": (last_err or "")[:160]}
    if err_ts is not None and (ok_ts is None or err_ts > ok_ts):
        return _row("ai", "warn", "最近识别失败 %s" % _fmt_hhmm(err_ts), meta)
    if last_ok:
        return _row("ai", "ok", "最近成功 %s" % _fmt_hhmm(ok_ts), meta)
    return _row("ai", "ok", "暂无识别调用记录", meta)


def detect_jwxt() -> dict:
    try:
        data = _read_json(TT_JSON)
        meta_in = data.get("meta") if isinstance(data, dict) else None
        fetched = int((meta_in or {}).get("fetchedAt") or 0)
    except Exception as exc:
        return _row("jwxt", "down", "课表文件缺失或损坏",
                    {"path": TT_JSON, "error": (str(exc) or "?")[:120]})
    if fetched <= 0:
        return _row("jwxt", "down", "课表同步时间缺失", {"path": TT_JSON})
    age_hours = max(0.0, (time.time() * 1000 - fetched) / 3600000.0)
    meta = {"fetched_at": fetched, "age_hours": round(age_hours, 2),
            "term": (meta_in or {}).get("term"),
            "count": (meta_in or {}).get("count")}
    if age_hours <= 30:
        return _row("jwxt", "ok", "课表 %.1f 小时前同步" % age_hours, meta)
    if age_hours <= 54:
        return _row("jwxt", "warn", "课表 %.1f 小时前同步（偏旧）" % age_hours, meta)
    return _row("jwxt", "down", "课表 %.1f 天未同步" % (age_hours / 24.0), meta)


def detect_hwauto() -> dict:
    ages = []
    mtimes = {}
    for path in (HW_LOG, HW_DATA):
        age = _file_age(path)
        mtimes[path] = _mtime(path)
        if age is not None:
            ages.append(age)
    if not ages:
        return _row("hwauto", "down", "无作业整理记录",
                    {"log": HW_LOG, "data": HW_DATA})
    age = min(ages)
    age_hours = age / 3600.0
    meta = {"age_hours": round(age_hours, 2), "log": HW_LOG, "data": HW_DATA,
            "log_mtime": mtimes.get(HW_LOG), "data_mtime": mtimes.get(HW_DATA)}
    if age_hours <= 3:
        return _row("hwauto", "ok", "作业整理 %.1f 小时前运行" % age_hours, meta)
    if age_hours <= 8:
        return _row("hwauto", "warn", "作业整理 %.1f 小时未运行" % age_hours, meta)
    return _row("hwauto", "down", "作业整理 %.1f 小时未运行" % age_hours, meta)


def detect_client(procs, sid: str) -> dict:
    if procs is None:
        return _row(sid, "unknown", "进程扫描不可用", {"scanner": "unavailable"})
    proc_name = "QQ" if sid == "qq_client" else "Weixin"
    pids = procs.get(proc_name) or []
    meta = {"process": proc_name, "count": len(pids),
            "pids": pids[:8], "scanner": "powershell-cim"}
    if pids:
        detail = "进程运行中（%d 个实例）" % len(pids) if len(pids) > 1 \
            else "进程运行中（pid %d）" % pids[0]
        return _row(sid, "ok", detail, meta)
    return _row(sid, "down", "客户端进程未运行", meta)


# ---------------------------------------------------------------------------
# 采集：local 10 行（本机）/ cloud 8 行（云函数）
# ---------------------------------------------------------------------------
def collect_cloud(base=None, key=None, token=None, runner=None, heartbeats=None) -> list:
    """云函数/ECS timer 每轮调用：读 site_config 暂停开关 + 探测 8 个云端行，返回 8 行（不抛出）。

    返回顺序：cloudbase / site_static / site_tls / dns_domain / tt_cloud /
    cloud_power_sync / cloud_xgj_sync / cloud_health_probe。
    最后一行 cloud_health_probe 是占位（本轮行数=8、采集耗时）；写入方写完后会用
    detect_cloud_health_probe() 重建它并覆盖 stats（见 cloudbase/functions/health_probe/index.py
    与 deploy/functions/jobs_runner.py）。
    任何单项异常降级为 unknown，绝不抛出。

    P3 双后端：
      * base 由调用方给定（CloudBase 云函数给 CloudBase；ECS jobs 给自建 PostgREST）；
      * runner 默认取 CLASS_HEALTH_RUNNER（cloudbase-function / ecs-timer），只进 meta；
      * heartbeats 默认：CLASS_JOB_HEARTBEAT=1 时读 ECS timer 心跳，否则为空（默认行为不变）。
    """
    global _CHECKED_AT
    t0 = time.time()
    _CHECKED_AT = int(time.time() * 1000)
    runner = runner or health_runner()
    if heartbeats is None:
        heartbeats = collect_job_heartbeats()
    if not isinstance(heartbeats, dict):
        heartbeats = {}

    paused = False
    note = ""
    try:
        value = read_site_config(base, key, token)
        paused = bool(value.get("paused"))
        note = str(value.get("note") or "")
    except Exception as exc:  # noqa: BLE001
        log("WARN collect_cloud read site_config failed: %r" % (exc,))

    rows = []

    def add(sid: str, fn, *args):
        try:
            rows.append(fn(*args))
        except Exception as exc:  # noqa: BLE001
            log("WARN detect %s failed: %r" % (sid, exc))
            rows.append(_row(sid, "unknown", "检测异常", {"error": (str(exc) or "?")[:120]}))

    add("cloudbase", detect_cloudbase, base, key, token)
    add("site_static", detect_site_static, paused, note)
    add("site_tls", detect_site_tls, paused, note)
    add("dns_domain", detect_dns_domain, paused)
    add("tt_cloud", detect_tt_cloud, base, key, token)
    add("cloud_power_sync", detect_cloud_power_sync, base, key, token,
        heartbeats.get("cloud_power_sync"))
    add("cloud_xgj_sync", detect_cloud_xgj_sync, base, key, token,
        heartbeats.get("cloud_xgj_sync"))
    elapsed = int((time.time() - t0) * 1000)
    rows.append(detect_cloud_health_probe(CLOUD_ROW_COUNT, 0, 0, elapsed, runner=runner))

    counts = _status_counts(rows)
    log("collect_cloud: %d rows ok=%d warn=%d down=%d unknown=%d in %dms "
        "(paused=%s backend=%s runner=%s job_heartbeat=%d)"
        % (len(rows), counts["ok"], counts["warn"], counts["down"],
           counts["unknown"], elapsed, paused, backend_info(base)["backend"],
           runner, len(heartbeats)))
    for row in rows:
        if row["status"] not in ("ok",):
            log("cloud row %s=%s: %s" % (row["id"], row["status"], row["detail"]))
    return rows


def collect(state=None, round_info=None, include_cloud=False) -> list:
    """检测依赖服务，返回行列表（dict 列表）；任何单项异常降级为 unknown，不抛出。

    默认只探测/返回本机 local 10 行（微信暂停后不再白等站点/DNS/TLS 探测超时）；
    include_cloud=True 时**额外**由本机代采云端 8 行（仅 --all-rows/HEALTH_WRITE_ALL 应急回滚用）。
    """
    global _CHECKED_AT
    t0 = time.time()
    _CHECKED_AT = int(time.time() * 1000)
    state = state if isinstance(state, dict) else load_state()
    round_info = dict(round_info or {})
    pause = os.path.exists(PAUSE)

    uptime, procs = scan_host()
    round_info.setdefault("uptime_s", uptime)

    rows = []

    def add(sid: str, fn, *args):
        try:
            row = fn(*args)
            rows.append(row)
        except Exception as exc:
            log("WARN detect %s failed: %r" % (sid, exc))
            rows.append(_row(sid, "unknown", "检测异常", {"error": (str(exc) or "?")[:120]}))

    add("collector_host", detect_collector_host, state, round_info, pause)
    add("qqflow", detect_account_service, state, "qqflow")
    add("weflow", detect_account_service, state, "weflow")
    add("briefdesk", detect_briefdesk, state)
    add("watcher", detect_watcher, state)
    add("ai", detect_ai)
    add("jwxt", detect_jwxt)
    add("hwauto", detect_hwauto)
    add("qq_client", detect_client, procs, "qq_client")
    add("wechat_client", detect_client, procs, "wechat_client")

    if include_cloud:
        base = key = None
        token = None
        try:
            base, key = _cb_config()
        except Exception as exc:
            log("WARN cb_config failed (all-rows): %r" % (exc,))
        if base and key:
            try:
                token = _ensure_token(base, key)
            except Exception as exc:
                log("WARN admin token unavailable for cloud rows: %r" % (exc,))
        rows.extend(collect_cloud(base, key, token))

    counts = _status_counts(rows)
    elapsed = int((time.time() - t0) * 1000)
    log("collect: %d rows ok=%d warn=%d down=%d unknown=%d in %dms (pause=%s, cloud=%s)"
        % (len(rows), counts["ok"], counts["warn"], counts["down"],
           counts["unknown"], elapsed, pause, bool(include_cloud)))
    for row in rows:
        if row["status"] not in ("ok",):
            log("row %s=%s: %s" % (row["id"], row["status"], row["detail"]))
    return rows


# ---------------------------------------------------------------------------
# 写入云端
# ---------------------------------------------------------------------------
def publish(rows, include_cloud=False) -> dict:
    """把 rows 写入云端（存在 PATCH，不存在 POST）。失败只写日志，返回结果 dict，不抛出。

    include_cloud=False（默认）：跳过 CLOUD_OWNED_IDS 的 8 行（cloudbase/site_static/site_tls/
    dns_domain/tt_cloud/cloud_power_sync/cloud_xgj_sync/cloud_health_probe）—— 它们由云端
    `health_probe` 云函数负责；True 时写全 18 行（--all-rows 回滚/应急）。
    """
    rows = list(rows or [])
    skipped = 0
    if not include_cloud:
        before = len(rows)
        rows = [r for r in rows if (r or {}).get("id") not in CLOUD_OWNED_IDS]
        skipped = before - len(rows)
    if not rows:
        log("ERROR publish: no rows")
        return {"ok": False, "error": "no rows"}
    t0 = time.time()
    try:
        base, key = _cb_config()
    except Exception as exc:
        log("ERROR publish: cb_config failed: %r" % (exc,))
        return {"ok": False, "error": "cb_config"}
    try:
        token = _ensure_token(base, key)
    except Exception as exc:
        log("ERROR publish: admin token unavailable: %r" % (exc,))
        return {"ok": False, "error": "token"}

    status, existing, ms = _list_health_ids(base, key, token)
    if status in (401, 403):
        log("WARN publish: list ids HTTP %d -> force refresh admin token" % status)
        try:
            token = _force_refresh_token(base, key)
            status, existing, ms = _list_health_ids(base, key, token)
        except Exception as exc:
            log("ERROR publish: token refresh failed: %r" % (exc,))
            return {"ok": False, "error": "token-refresh"}
    if status != 200 or existing is None:
        log("ERROR publish: list existing ids failed (HTTP %s)" % status)
        return {"ok": False, "error": "list-ids", "http": status}

    updated_at = _utc_iso()
    patched = posted = failed = 0
    for row in rows:
        rid = row.get("id") or "?"
        body = dict(row)
        body["updated_at"] = updated_at
        try:
            if rid in existing:
                st, _out, _ms = _cb_request(
                    base, key, "service_health?id=eq." + urllib.parse.quote(str(rid)),
                    body, "PATCH", token)
                if st in (200, 204):
                    patched += 1
                else:
                    failed += 1
                    log("WARN publish PATCH %s HTTP %s" % (rid, st))
            else:
                st, _out, _ms = _cb_request(
                    base, key, "service_health", [body], "POST", token)
                if st in (200, 201, 204):
                    posted += 1
                else:
                    failed += 1
                    log("WARN publish POST %s HTTP %s" % (rid, st))
        except Exception as exc:
            failed += 1
            log("WARN publish %s exception: %r" % (rid, exc))

    total_ms = int((time.time() - t0) * 1000)
    log("publish: %d/%d rows (patch=%d post=%d failed=%d skipped_cloud=%d list_ms=%s) in %dms"
        % (len(rows) - failed, len(rows), patched, posted, failed, skipped, ms, total_ms))
    return {"ok": failed == 0, "rows": len(rows), "patched": patched,
            "posted": posted, "failed": failed, "skipped_cloud": skipped, "ms": total_ms}


# ---------------------------------------------------------------------------
# watchdog 集成入口（任何异常绝不外抛）
# ---------------------------------------------------------------------------
def publish_from_watchdog(state, round_info=None) -> dict:
    """watchdog.py 每轮末尾调用：采集本机 local 10 行并上报（云端 8 行归 health_probe）。永不抛异常。"""
    t0 = time.time()
    try:
        rows = collect(state=state, round_info=round_info)
        result = publish(rows)
        log("beat from watchdog: %s (total %dms)"
            % (json.dumps(result, ensure_ascii=False),
               int((time.time() - t0) * 1000)))
        return result
    except Exception:
        log("ERROR publish_from_watchdog crashed (ignored):\n%s" % traceback.format_exc())
        return {"ok": False, "error": "crashed"}


def report_pause() -> dict:
    """watchdog PAUSE 分支调用：只上报 collector_host=warn（采集已暂停）。永不抛异常。"""
    global _CHECKED_AT
    try:
        _CHECKED_AT = int(time.time() * 1000)
        row = detect_collector_host({}, {"paused": True}, True)
        result = publish([row])
        log("pause report: collector_host=warn (%s)"
            % json.dumps(result, ensure_ascii=False))
        return result
    except Exception:
        log("ERROR report_pause crashed (ignored):\n%s" % traceback.format_exc())
        return {"ok": False, "error": "crashed"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    try:
        import argparse
        parser = argparse.ArgumentParser(
            prog="health_beat.py",
            description="依赖服务健康心跳（18 行 → CloudBase public.service_health；"
                        "本机写 local 10 行，云端 8 行归云函数 health_probe）")
        parser.add_argument("--once", action="store_true",
                            help="采集本机 local 10 行并写入云端后退出（默认行为）")
        parser.add_argument("--dry-run", action="store_true",
                            help="只打印将写入的行（JSON），不写云端")
        parser.add_argument("--all-rows", action="store_true",
                            help="回滚/应急：本机代采并写全 18 行（默认只写 local 10 行，云端 8 行归 health_probe）")
        ns = parser.parse_args(argv)
    except SystemExit as exc:  # --help / 参数错误
        return int(getattr(exc, "code", 0) or 0)

    include_cloud = bool(ns.all_rows) or os.environ.get("HEALTH_WRITE_ALL") == "1"
    try:
        rows = collect(include_cloud=include_cloud)
    except Exception:
        log("ERROR collect crashed (CLI):\n%s" % traceback.format_exc())
        _emit("FAILED: collect crashed, see %s" % LOG)
        return 1

    counts = _status_counts(rows)
    scope = "all 18 rows (--all-rows/HEALTH_WRITE_ALL)" if include_cloud else \
        "local %d rows (cloud %d rows by health_probe)" % (len(LOCAL_WRITE_IDS), CLOUD_ROW_COUNT)
    summary = ("collect: %d rows ok=%d warn=%d down=%d unknown=%d | write scope: %s"
               % (len(rows), counts["ok"], counts["warn"],
                  counts["down"], counts["unknown"], scope))
    _emit(summary)

    if ns.dry_run:
        try:
            _emit(json.dumps(rows, ensure_ascii=False, indent=2))
        except Exception:
            _emit(str(rows))
        _emit("dry-run: nothing written")
        return 0

    result = publish(rows, include_cloud=include_cloud)
    if result.get("ok"):
        msg = ("published %d rows (patch=%s post=%s) in %sms"
               % (result.get("rows", 0), result.get("patched"),
                  result.get("posted"), result.get("ms")))
        _emit("OK " + msg)
        return 0
    _emit("FAILED: %s (see %s)"
          % (json.dumps(result, ensure_ascii=False), LOG))
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        log("FATAL: %s" % traceback.format_exc())
        raise SystemExit(1)
