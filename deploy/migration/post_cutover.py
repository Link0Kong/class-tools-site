# -*- coding: utf-8 -*-
"""post_cutover.py — 切流后动作编排/演练（ECS 定时任务 + 健康行联动）。

切流当天顺序（见 CUTOVER.md §2）：Caddy 切自建 → 三端验证 → 重装 ECS jobs 为 live → 启用 timer →
触发一轮健康巡检 → 诊断页可见 18 行 + cloudbase 行含 PG 指标 → 开附件外置（人工确认 env）。

本脚本：
  rehearsal（默认，安全）：在 staging 后端上启用 ECS jobs timer → 立即触发 health_probe → 用测试账号读
    staging `service_health` 验证 18 行 + `cloudbase` 行含 PG 指标 → finally 重新禁用 timer。
  apply（切流后）：需 --confirm；校验生产已切自建（200 + 测试账号 members 70）→ `ecs_cron.py install
    --backend live --allow-live` → enable timer → 触发 health_probe → 生产 API 验证 18 行/cloudbase/PG →
    打印附件外置与 CloudBase 下线提醒。

用法（web 仓库根目录，系统 python）::

    python deploy\\migration\\post_cutover.py --dry-run
    python deploy\\migration\\post_cutover.py rehearsal
    python deploy\\migration\\post_cutover.py apply --confirm
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
TEST_SID = "3260799999"
TEST_NAME = "测试账号"
ECS = "http://121.196.47.2"
STAGING = ECS + "/v1/rdb/rest-next/"
PROD = ECS + "/v1/rdb/rest/"
UNITS = [
    "class-tools-job-health-probe.service",
    "class-tools-job-power-sync.service",
    "class-tools-job-xgj-sync.service",
]
TIMERS = [u.replace(".service", ".timer") for u in UNITS]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

LOG_PATH = None
RESULTS = []


def log(msg=""):
    print(msg, flush=True)
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(str(msg) + "\n")
        except OSError:
            pass


def check(name, ok, note=""):
    RESULTS.append((name, bool(ok)))
    log(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)[:300]) if note else ""))


def run(label, cmd, timeout=600, allow_fail=False, env=None):
    log("\n$ " + " ".join(str(c) for c in cmd))
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    e["PYTHONUTF8"] = "1"
    if env:
        e.update(env)
    try:
        pr = subprocess.run(cmd, cwd=WEB, env=e, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
        out = (pr.stdout or "") + (pr.stderr or "")
        rc = pr.returncode
    except subprocess.TimeoutExpired as exc:
        out = "TIMEOUT %ss\n%s" % (timeout, (exc.stdout or ""))
        rc = 124
    log(out.rstrip())
    log("[%s] rc=%s" % (label, rc))
    if rc != 0 and not allow_fail:
        raise SystemExit("[x] 步骤失败：%s rc=%s" % (label, rc))
    return rc, out


def ecs_cron(*args, timeout=900, allow_fail=False):
    return run("ecs_cron " + args[0], [PY, os.path.join(WEB, "deploy", "ecs_cron.py")] + list(args),
               timeout, allow_fail)


def remote(script, label="remote", timeout=120):
    sys.path.insert(0, os.path.join(WEB, "deploy"))
    import ecs_site
    st, rc, out = ecs_site.run_script(script, label=label, timeout=timeout, wait=max(300, timeout * 2))
    log(out or "")
    return st == "Success" and rc in (0, "0"), out or ""


def post_json(url, body, headers=None, timeout=40):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def test_token(base):
    ver = post_json(base + "rpc/class_verify", {"p_sid": TEST_SID, "p_name": TEST_NAME}, timeout=30)
    tok = (ver or {}).get("token") or ""
    if not tok:
        raise RuntimeError("class_verify 无 token")
    return tok


def read_health(base):
    tok = test_token(base)
    req = urllib.request.Request(base + "service_health?select=id,name,status,detail,meta&order=id",
                                 headers={"X-Class-Token": tok, "X-Device-Id": tok})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def poll_health(base, want_pg=True, timeout=100):
    """轮询直到 service_health 行数>=18 且 cloudbase 行有 PG 指标；返回 (ok, rows, detail)。"""
    t0 = time.time()
    rows = []
    while time.time() - t0 < timeout:
        try:
            rows = read_health(base) or []
            row = next((r for r in rows if str(r.get("id")) == "cloudbase"), None)
            if isinstance(rows, list) and len(rows) >= 18 and row and (not want_pg or row.get("meta")):
                return True, rows, row.get("detail") or ""
        except Exception as exc:  # noqa: BLE001
            log("[poll] %s" % type(exc).__name__)
        time.sleep(5)
    return False, rows, ""


def trigger_health_job():
    script = r"""#!/bin/bash
set +e
systemctl start class-tools-job-health-probe.service
sleep 4
echo "result=$(systemctl show -p Result --value class-tools-job-health-probe.service 2>/dev/null)"
journalctl -u class-tools-job-health-probe.service -n 12 --no-pager 2>/dev/null
TEST=$(grep -c 'CLASS_PG_MONITOR' /etc/class-tools/jobs.env 2>/dev/null)
echo "pg_monitor_env=$TEST"
echo done
"""
    return remote(script, "postcut-health-trigger")


def timer_states():
    script = r"""#!/bin/bash
set +e
for t in class-tools-job-health-probe.timer class-tools-job-power-sync.timer class-tools-job-xgj-sync.timer; do
  echo "$t=$(systemctl is-active $t 2>/dev/null) enabled=$(systemctl is-enabled $t 2>/dev/null)"
done
echo done
"""
    ok, out = remote(script, "postcut-timer-state")
    return out


def rehearsal():
    log("\n########## POST-CUTOVER REHEARSAL（staging，不切生产） ##########")
    log("当前 timer：" + timer_states().replace("\n", " | ")[:500])
    enabled = False
    try:
        rc, _ = ecs_cron("enable", "--confirm", timeout=600, allow_fail=True)
        check("R1 ECS jobs timer 启用", rc == 0, "rc=%s" % rc)
        if rc != 0:
            return 1
        enabled = True
        ok, _ = trigger_health_job()
        check("R2 手动触发 health_probe 任务", ok)
        ok, rows, detail = poll_health(STAGING, want_pg=True, timeout=120)
        check("R3 staging 健康行 18 行且 cloudbase 含 PG 指标", ok,
              "rows=%s detail=%s" % (len(rows) if isinstance(rows, list) else rows, detail))
        blk = timer_states()
        log(blk)
        check("R4 timer 处于 active", all(("=active enabled=enabled" in line) for line in blk.splitlines()
                                           if line.startswith("class-tools-job-")), "")
        return 0 if all(ok for _n, ok in RESULTS) else 1
    finally:
        if enabled:
            log("\n[rehearsal] finally 禁用 ECS jobs timer（恢复禁用态）")
            ecs_cron("disable", timeout=600, allow_fail=True)
            log(timer_states())


def apply(confirm):
    if not confirm:
        raise SystemExit("[x] apply 必须显式 --confirm（会启用 ECS 定时任务写生产库）")
    log("\n########## POST-CUTOVER APPLY（生产） ##########")
    st, _body = 0, b""
    try:
        req = urllib.request.Request(PROD, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            st = r.status
    except urllib.error.HTTPError as exc:
        st = exc.code
    except Exception:  # noqa: BLE001
        st = 0
    check("A1 生产路由已是自建（HTTP 200）", st == 200, "HTTP %s" % st)
    if st != 200:
        log("[x] 生产路由不是 200，可能还没切流；先执行 cutover_run execute")
        return 1
    try:
        tok = test_token(PROD)
        req = urllib.request.Request(PROD + "rpc/class_members", data=b"{}",
                                     headers={"X-Class-Token": tok, "X-Device-Id": tok,
                                              "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            members = json.loads(r.read().decode("utf-8") or "null")
        check("A2 生产测试账号 members=70", isinstance(members, list) and len(members) == 70, len(members) if isinstance(members, list) else members)
    except Exception as exc:  # noqa: BLE001
        check("A2 生产测试账号 members=70", False, type(exc).__name__)
    rc, _ = ecs_cron("install", "--backend", "live", "--allow-live", timeout=900, allow_fail=True)
    check("A3 ECS jobs 重装为 live 后端", rc == 0, "rc=%s" % rc)
    if rc != 0:
        return 1
    rc, _ = ecs_cron("enable", "--confirm", timeout=600, allow_fail=True)
    check("A4 ECS jobs timer 启用", rc == 0, "rc=%s" % rc)
    if rc != 0:
        return 1
    ok, _ = trigger_health_job()
    check("A5 触发 health_probe", ok)
    ok, rows, detail = poll_health(PROD, want_pg=True, timeout=150)
    check("A6 生产健康行 18 行且 cloudbase 含 PG 指标", ok,
          "rows=%s detail=%s" % (len(rows) if isinstance(rows, list) else rows, detail))
    # PG monitor 的 prod_mode 应为 selfhosted
    try:
        pr = subprocess.run([PY, os.path.join(WEB, "deploy", "ecs_pg.py"), "monitor", "--json"],
                            cwd=WEB, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=240, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        doc = None
        for line in (pr.stdout or "").splitlines():
            if line.strip().startswith("{"):
                try:
                    doc = json.loads(line.strip())
                except Exception:  # noqa: BLE001
                    pass
        mode = ((doc or {}).get("metrics") or {}).get("prod_mode")
        check("A7 monitor prod_mode=selfhosted", mode == "selfhosted", mode)
    except Exception as exc:  # noqa: BLE001
        check("A7 monitor prod_mode=selfhosted", False, type(exc).__name__)
    log("""
[下一步人工确认]
1) 附件外置（用户已授权第②步）：本机 G:\\ClassTools\\briefdesk\\secrets\\cloud.env 设
   NOTICE_ATTACH_EXTERNALIZE=1 与 ATT_BASE_URL=https://tool.furina.fun，跑一次 sync_notices_cloud.py 回填存量；
   演练证据 deploy/migration/e2e_attach_staging.py 8/8 PASS。
2) 小程序/安卓：发布使用 https://tool.furina.fun/v1/rdb/rest/ 的新版（备案+HTTPS 后）。
3) CloudBase：保留 ≥2 周回滚窗口后再停云函数/退订；期间旧版客户端仍可能走旧网关。
4) 回滚：python deploy\\migration\\cutover_run.py rollback --confirm（会自动停用 ECS jobs timer 吗？不会；必要时先 ecs_cron.py disable）。
""")
    return 0 if all(ok for _n, ok in RESULTS) else 1


def main(argv=None):
    global LOG_PATH
    ap = argparse.ArgumentParser(description="切流后动作编排/演练（ECS jobs/健康行）")
    ap.add_argument("mode", nargs="?", default="rehearsal", choices=["rehearsal", "apply"])
    ap.add_argument("--confirm", action="store_true", help="apply 必须显式确认")
    ap.add_argument("--dry-run", action="store_true", help="只打印步骤")
    ns = ap.parse_args(argv)
    LOG_PATH = os.path.join(r"G:\ClassTools\briefdesk\data\cloudbase_migration",
                            "post-cutover-%s-%s.log" % (ns.mode, time.strftime("%Y%m%d-%H%M%S")))
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log("=== post_cutover %s start %s ===" % (ns.mode, time.strftime("%Y-%m-%dT%H:%M:%S")))
    try:
        import aliyunsdkcore  # noqa: F401
    except ImportError:
        raise SystemExit("[x] 请用系统 python 运行（需 aliyunsdkcore）")
    if ns.dry_run:
        if ns.mode == "rehearsal":
            log("dry-run：enable staging timers → 触发 health_probe → 测试账号读 staging service_health（18 行 + PG 指标）→ finally disable timers")
        else:
            log("dry-run：校验生产 200/members70 → ecs_cron install --backend live --allow-live → enable → 触发 health_probe → 生产 service_health 18 行/PG → monitor prod_mode=selfhosted")
        return 0
    if ns.mode == "rehearsal":
        return rehearsal()
    return apply(ns.confirm)


if __name__ == "__main__":
    sys.exit(main())
