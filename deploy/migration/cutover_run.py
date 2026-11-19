# -*- coding: utf-8 -*-
"""cutover_run.py — P4 切流总编排（快照 → cut 库 → 优化 SQL → switch-db → smoke → Caddy 切换）。

设计目标：把 `deploy/migration/CUTOVER.md` 的手工步骤收敛成一条可复现命令，减少切流窗口的人为失误；
默认只做 **rehearsal（演练）**：使用/生成快照 → 导入 `class_tools_cut` → 应用优化 SQL → 切换 PostgREST 指到 cut 库 →
测试账号 smoke → **finally 切回 `class_tools`**，不碰生产 Caddy 路由。
只有 `execute --confirm-cutover` 才会真正切 Caddy 生产路由；`rollback` 用于一键回退。

用法（web 仓库根目录，系统 python；需要 aliyunsdkcore + oss2）::

    python deploy\\migration\\cutover_run.py --dry-run
    python deploy\\migration\\cutover_run.py rehearsal --artifact G:\\ClassTools\\briefdesk\\data\\cloudbase_migration\\p4-final-20261118-1526
    python deploy\\migration\\cutover_run.py execute --artifact <dir> --confirm-cutover
    python deploy\\migration\\cutover_run.py rollback --confirm

约定：只读 CloudBase；测试只用 3260799999/测试账号；不打印任何 secret。
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
CUT_DB = "class_tools_cut"
BASE_DB = "class_tools"
SQL_FILES = [
    os.path.join(WEB, "deploy", "migration", "2026-11-18_notice_meta_lite.sql"),
    os.path.join(WEB, "deploy", "migration", "2026-11-18_notice_meta_cache.sql"),
]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

LOG_PATH = None
STEP_TIMES = []


def log(msg=""):
    print(msg, flush=True)
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(str(msg) + "\n")
        except OSError:
            pass


def _http_status(url, timeout=15):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(300)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(300)
        except Exception:  # noqa: BLE001
            body = b""
        return exc.code, body
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc).encode("utf-8", "replace")[:200]


def _post_json(url, body, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8") or "null")


def run(label, cmd, timeout, env=None, allow_fail=False):
    """执行子命令：输出同时写日志；返回 (rc, out)。"""
    log("\n$ " + " ".join(str(c) for c in cmd))
    t0 = time.time()
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    e["PYTHONUTF8"] = "1"
    if env:
        e.update(env)
    try:
        proc = subprocess.run(cmd, cwd=WEB, env=e, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        rc = proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = "TIMEOUT after %ss\n%s" % (timeout, (exc.stdout or ""))
        rc = 124
    except Exception as exc:  # noqa: BLE001
        out = "EXEC ERROR: %s: %s" % (exc.__class__.__name__, exc)
        rc = 125
    log(out.rstrip())
    dur = time.time() - t0
    STEP_TIMES.append((label, dur, rc))
    log("[%s] rc=%s %.1fs" % (label, rc, dur))
    if rc != 0 and not allow_fail:
        raise SystemExit("[x] 步骤失败：%s（rc=%s）" % (label, rc))
    return rc, out


def ecs_pg(*args, timeout=1800, **kwargs):
    return run("ecs_pg " + args[0], [PY, os.path.join(WEB, "deploy", "ecs_pg.py")] + list(args), timeout, **kwargs)


def ecs_cutover(*args, timeout=600, **kwargs):
    return run("ecs_cutover " + args[0], [PY, os.path.join(WEB, "deploy", "ecs_cutover.py")] + list(args), timeout, **kwargs)


def test_api(base, need_members=True):
    """测试账号真实 API 冒烟（只读 RPC/表；登录会写 class_sessions，仅目标库）。"""
    try:
        _st, ver = _post_json(base + "rpc/class_verify", {"p_sid": TEST_SID, "p_name": TEST_NAME}, timeout=30)
        tok = (ver or {}).get("token") or ""
        if not tok:
            return False, "class_verify 无 token"
        hdr = {"X-Class-Token": tok, "X-Device-Id": tok}
        req = urllib.request.Request(base + "rpc/class_members", data=b"{}",
                                     headers={**hdr, "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            members = json.loads(r.read().decode("utf-8") or "null")
        req = urllib.request.Request(base + "rpc/class_notices_meta", data=b"{}",
                                     headers={**hdr, "Content-Type": "application/json"}, method="POST")
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=60) as r:
            meta = json.loads(r.read().decode("utf-8") or "null")
        ms = int((time.time() - t0) * 1000)
        n = len(meta) if isinstance(meta, list) else -1
        ok = (not need_members) or (isinstance(members, list) and len(members) == 70)
        return ok, "members=%s meta=%s meta_ms=%sms" % (
            len(members) if isinstance(members, list) else members, n, ms)
    except Exception as exc:  # noqa: BLE001
        return False, "%s: %s" % (exc.__class__.__name__, str(exc)[:160])


def fresh_snapshot(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    run("export_schema", [PY, os.path.join(WEB, "deploy", "migration", "export_schema.py"), "--out", out_dir], 900)
    run("export_data", [PY, os.path.join(WEB, "deploy", "migration", "export_data.py"), "--out", out_dir], 1200)
    run("verify_export", [PY, os.path.join(WEB, "deploy", "migration", "verify_export.py"), "--out", out_dir], 900)
    man = os.path.join(out_dir, "manifest.json")
    if not os.path.isfile(man):
        raise SystemExit("[x] 快照缺少 manifest.json：%s" % out_dir)
    log("[snapshot] OK：%s" % out_dir)
    return out_dir


def rehearsal(artifact, skip_snapshot, with_e2e=False):
    log("\n########## P4 REHEARSAL（不切生产 Caddy） ##########")
    if not artifact:
        artifact = os.path.join(r"G:\ClassTools\briefdesk\data\cloudbase_migration",
                                "cutover-rehearsal-" + time.strftime("%Y%m%d-%H%M"))
    if skip_snapshot:
        if not os.path.isfile(os.path.join(artifact, "manifest.json")):
            raise SystemExit("[x] --skip-snapshot 需要存在 artifact/manifest.json：%s" % artifact)
        log("[rehearsal] 复用快照：%s" % artifact)
    else:
        artifact = fresh_snapshot(artifact)
    # 预检 staging
    st, body = _http_status(STAGING)
    log("[preflight] staging 路由 HTTP %s" % st)
    if st != 200:
        raise SystemExit("[x] staging 路由不可用，停止")
    # 导入 cut 库
    ecs_pg("import", "--artifact", artifact, "--db", CUT_DB, "--reset", timeout=2400)
    ecs_pg("verify", "--db", CUT_DB, "--expect", os.path.join(artifact, "manifest.json"), timeout=900)
    for sql in SQL_FILES:
        ecs_pg("apply-sql", "--db", CUT_DB, "--file", sql, timeout=900)
    # 切 cut 库 + smoke
    switched = False
    try:
        ecs_pg("switch-db", "--db", CUT_DB, timeout=600)
        switched = True
        ecs_pg("smoke", timeout=600)
        ok, detail = test_api(STAGING)
        log("[rehearsal] 测试账号 smoke：%s | %s" % ("PASS" if ok else "FAIL", detail))
        if not ok:
            raise SystemExit("[x] rehearsal smoke 失败")
        if with_e2e:
            run("e2e_staging_web", [PY, os.path.join(WEB, "deploy", "migration", "e2e_staging_web.py")], 600)
    finally:
        if switched:
            log("\n[rehearsal] 切回 staging 库 %s" % BASE_DB)
            try:
                ecs_pg("switch-db", "--db", BASE_DB, timeout=600)
            except SystemExit:
                log("[x] WARNING rehearsal 切回 staging 失败，请立即手动执行："
                    "python deploy\\ecs_pg.py switch-db --db %s" % BASE_DB)
                raise
    st, _ = _http_status(STAGING)
    log("[rehearsal] staging 恢复 HTTP %s" % st)
    return 0 if st == 200 else 1


def execute(artifact, skip_snapshot, confirm):
    if not confirm:
        raise SystemExit("[x] execute 必须显式 --confirm-cutover（生产会切 Caddy 路由）")
    log("\n########## P4 EXECUTE（生产切流） ##########")
    log("[preflight] 切流前置检查（FAIL 会中止；DNS/ICP 未过是 WARN）")
    pf_rc, _ = run("preflight", [PY, os.path.join(WEB, "deploy", "migration", "preflight_cutover.py"),
                                "--drift", "--check-remotes"], 300, allow_fail=True)
    if pf_rc != 0:
        raise SystemExit("[x] preflight 存在 FAIL，已中止切流（见上方输出）")
    if not artifact:
        artifact = os.path.join(r"G:\ClassTools\briefdesk\data\cloudbase_migration",
                                "cutover-" + time.strftime("%Y%m%d-%H%M"))
    if not skip_snapshot:
        artifact = fresh_snapshot(artifact)
    elif not os.path.isfile(os.path.join(artifact, "manifest.json")):
        raise SystemExit("[x] artifact 缺少 manifest.json：%s" % artifact)
    st, _ = _http_status(STAGING)
    log("[preflight] staging HTTP %s" % st)
    if st != 200:
        raise SystemExit("[x] staging 不可用")
    ecs_pg("import", "--artifact", artifact, "--db", CUT_DB, "--reset", timeout=2400)
    ecs_pg("verify", "--db", CUT_DB, "--expect", os.path.join(artifact, "manifest.json"), timeout=900)
    for sql in SQL_FILES:
        ecs_pg("apply-sql", "--db", CUT_DB, "--file", sql, timeout=900)
    ecs_pg("switch-db", "--db", CUT_DB, timeout=600)
    ok, detail = test_api(STAGING)
    log("[execute] cut 库 smoke：%s | %s" % ("PASS" if ok else "FAIL", detail))
    if not ok:
        ecs_pg("switch-db", "--db", BASE_DB, timeout=600, allow_fail=True)
        raise SystemExit("[x] cut 库 smoke 失败，已切回 staging")
    # 真正切生产 Caddy
    ecs_cutover("switch", "--to", "selfhosted", "--confirm", timeout=600)
    st, body = _http_status(PROD)
    log("[execute] 生产 /v1/rdb/rest/ HTTP %s %s" % (st, body[:80]))
    ok2, detail2 = test_api(PROD)
    log("[execute] 生产测试账号 smoke：%s | %s" % ("PASS" if ok2 else "FAIL", detail2))
    if st != 200 or not ok2:
        log("[x] 切流后验证失败；执行回滚：python deploy\\migration\\cutover_run.py rollback --confirm")
        return 1
    log("\n[execute] 切流完成。回滚命令：python deploy\\migration\\cutover_run.py rollback --confirm")
    return 0


def rollback(confirm):
    if not confirm:
        raise SystemExit("[x] rollback 必须显式 --confirm")
    log("\n########## P4 ROLLBACK ##########")
    ecs_cutover("switch", "--to", "cloudbase", "--confirm", timeout=600)
    ecs_pg("switch-db", "--db", BASE_DB, timeout=600, allow_fail=True)
    st, body = _http_status(PROD)
    s2, _ = _http_status(STAGING)
    log("[rollback] 生产 /v1/rdb/rest/ HTTP %s（期望 401 CloudBase）" % st)
    log("[rollback] staging HTTP %s（期望 200）" % s2)
    return 0 if (st == 401 and s2 == 200) else 1


def main(argv=None):
    global LOG_PATH
    ap = argparse.ArgumentParser(description="P4 切流总编排（rehearsal/execute/rollback）")
    ap.add_argument("mode", nargs="?", default="rehearsal",
                    choices=["rehearsal", "execute", "rollback"], help="默认 rehearsal")
    ap.add_argument("--artifact", help="快照目录（含 manifest.json）；rehearsal 可复用")
    ap.add_argument("--skip-snapshot", action="store_true", help="复用 --artifact（不重新导出）")
    ap.add_argument("--with-e2e", action="store_true", help="rehearsal 后跑网页 staging E2E")
    ap.add_argument("--confirm-cutover", action="store_true", help="execute 必须显式确认会切生产 Caddy")
    ap.add_argument("--confirm", action="store_true", help="rollback 必须显式确认")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的步骤/命令，不执行")
    ns = ap.parse_args(argv)

    LOG_PATH = os.path.join(r"G:\ClassTools\briefdesk\data\cloudbase_migration",
                            "cutover-run-%s-%s.log" % (ns.mode, time.strftime("%Y%m%d-%H%M%S")))
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log("=== cutover_run %s start %s ===" % (ns.mode, time.strftime("%Y-%m-%dT%H:%M:%S")))
    log("log: %s" % LOG_PATH)
    try:
        import aliyunsdkcore  # noqa: F401
    except ImportError:
        raise SystemExit("[x] 请用系统 python 运行（需 aliyunsdkcore）：python deploy\\migration\\cutover_run.py ...")

    t0 = time.time()
    if ns.dry_run:
        if ns.mode == "rehearsal":
            log("dry-run 步骤：快照(%s) → import --db %s --reset → verify → apply-sql ×%d → switch-db %s → smoke → switch-db %s"
                % ("reuse" if ns.skip_snapshot else "fresh", CUT_DB, len(SQL_FILES), CUT_DB, BASE_DB))
        elif ns.mode == "execute":
            log("dry-run 步骤：快照 → import/verify/apply-sql ×%d → switch-db %s → smoke → ecs_cutover switch --to selfhosted --confirm → 生产 smoke"
                % (len(SQL_FILES), CUT_DB))
        else:
            log("dry-run 步骤：ecs_cutover switch --to cloudbase --confirm → switch-db %s → 复核" % BASE_DB)
        return 0
    if ns.mode == "rehearsal":
        rc = rehearsal(ns.artifact, ns.skip_snapshot, with_e2e=ns.with_e2e)
    elif ns.mode == "execute":
        rc = execute(ns.artifact, ns.skip_snapshot, ns.confirm_cutover)
    else:
        rc = rollback(ns.confirm)
    total = time.time() - t0
    log("\n=== cutover_run %s done rc=%s %.1fs ===" % (ns.mode, rc, total))
    log("步骤耗时：" + ", ".join("%s=%.1fs" % (n, d) for n, d, _c in STEP_TIMES))
    return rc


if __name__ == "__main__":
    sys.exit(main())
