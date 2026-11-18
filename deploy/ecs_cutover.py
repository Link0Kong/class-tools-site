# -*- coding: utf-8 -*-
"""ecs_cutover.py — P4 生产 API 切流/回滚（Caddy 路由一次切换）。

背景：自建 PostgreSQL 18 + PostgREST 13 的 staging 路由 `/v1/rdb/rest-next/*` 已上线（deploy/ecs_pg.py）。
切流时只需把生产 `/v1/rdb/rest/*` 从腾讯云 CloudBase 网关改指 ECS 本地 `127.0.0.1:3000`：
  * `ecs_site.py` 通过 `CLASS_API_MODE=selfhosted` 生成该路由（本地 PostgREST + 剥 Authorization）；
  * 本脚本负责：预检 → 远端备份 Caddyfile → 写入新配置（含 HTTPS ready）→ validate → reload →
    端到端验证；失败/需要时一条命令回滚到 cloudbase。
用法（在 web 仓库根目录；系统 python 带 aliyunsdkcore）::

    python deploy\\ecs_cutover.py status
    python deploy\\ecs_cutover.py switch --to selfhosted --confirm
    python deploy\\ecs_cutover.py switch --to cloudbase --confirm   # 回滚
    python deploy\\ecs_cutover.py switch --to selfhosted --dry-run   # 只打印远端脚本

红线：默认不执行任何切换；必须显式 `--confirm`。切流前先跑 `deploy/migration/CUTOVER.md` 的
最终快照/导入/switch-db 步骤，并确认 staging 影子验证全绿。
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import ecs_site  # noqa: E402

CDB = "class_tools"
PROBE_SCRIPT = r"""#!/bin/bash
set +e
echo "=== Caddyfile 状态 ==="
if [ -f /etc/caddy/Caddyfile ]; then
  sha256sum /etc/caddy/Caddyfile
  echo "lines=$(wc -l < /etc/caddy/Caddyfile)"
  grep -c 'rest-next' /etc/caddy/Caddyfile | sed 's/^/staging_routes=/'
  grep -q 'tool\.furina\.fun {' /etc/caddy/Caddyfile && echo "active=https" || echo "active=http_only"
  grep -n 'handle_path /v1/rdb/rest/\*' /etc/caddy/Caddyfile >/dev/null && echo "prod_mode=selfhosted" || echo "prod_mode=cloudbase"
  grep -n 'reverse_proxy 127.0.0.1:3000' /etc/caddy/Caddyfile | head -4
else
  echo "Caddyfile MISSING"
fi
echo "=== caddy ==="
caddy version 2>/dev/null
echo "active=$(systemctl is-active caddy)"
echo "=== 本地端口 ==="
ss -ltnp 2>/dev/null | grep -E ':(80|443|3000|5432) ' || true
echo "=== PostgREST 当前库（不打印密码） ==="
sed -n 's|^db-uri = "postgres://[^/]*/\([A-Za-z0-9_]*\)".*|db=\1|p' /etc/class-tools/pgrest.conf 2>/dev/null
echo "pgrest_active=$(systemctl is-active class-tools-pgrest 2>/dev/null)" 
echo "=== 环回探针 ==="
curl -s -m 5 -o /dev/null -w 'prod_api=%{http_code}\n' http://127.0.0.1/v1/rdb/rest/
curl -s -m 5 -o /dev/null -w 'staging_api=%{http_code}\n' http://127.0.0.1/v1/rdb/rest-next/
curl -s -m 5 -o /dev/null -w 'root=%{http_code}\n' http://127.0.0.1/
echo done
"""


def _http(url, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(400)
        except Exception:  # noqa: BLE001
            body = b""
        return exc.code, body


def _probe_remote():
    st, rc, out = ecs_site.run_script(PROBE_SCRIPT, label="cutover-probe", timeout=90, wait=180)
    return st, rc, out or ""


def build_switch_script(mode: str) -> str:
    if mode not in ecs_site.PROD_API_MODES:
        raise SystemExit("mode 只能是 %s" % (ecs_site.PROD_API_MODES,))
    # 读远端当前 active 形态，保持同一形态（http-only / https）
    st, rc, probe = _probe_remote()
    active_https = "active=https" in probe
    os.environ["CLASS_API_MODE"] = mode
    caddy_active = ecs_site._caddy_https() if active_https else ecs_site._caddy_http()
    caddy_https = ecs_site._caddy_https()
    script = r"""#!/bin/bash
set -e
TS=$(date +%Y%m%d-%H%M%S)
BK="/var/www/tool_backup/$TS"
mkdir -p "$BK" /etc/caddy
echo "=== 1. 备份当前 Caddyfile ==="
cp -a /etc/caddy/Caddyfile "$BK/Caddyfile.old" 2>/dev/null || true
cp -a /etc/caddy/Caddyfile.https.ready "$BK/Caddyfile.https.ready.old" 2>/dev/null || true
sha256sum "$BK/Caddyfile.old" 2>/dev/null || true
echo "$BK" > /tmp/class-tools-cutover-last-backup

echo "=== 2. 写入并校验新 Caddy 配置（__MODE__） ==="
cat > /etc/caddy/Caddyfile.new <<'CADDY_EOF'
__CADDY_ACTIVE__
CADDY_EOF
caddy validate --config /etc/caddy/Caddyfile.new --adapter caddyfile
cat > /etc/caddy/Caddyfile.https.ready <<'CADDY_HTTPS_EOF'
__CADDY_HTTPS__
CADDY_HTTPS_EOF
caddy validate --config /etc/caddy/Caddyfile.https.ready --adapter caddyfile
mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile

echo "=== 3. reload Caddy ==="
systemctl reload caddy || systemctl restart caddy
sleep 1
systemctl is-active caddy

echo "=== 4. 切换后探针 ==="
curl -s -m 8 -o /dev/null -w 'prod_api=%{http_code}\n' http://127.0.0.1/v1/rdb/rest/
curl -s -m 8 -o /dev/null -w 'staging_api=%{http_code}\n' http://127.0.0.1/v1/rdb/rest-next/
curl -s -m 8 -o /dev/null -w 'root=%{http_code}\n' http://127.0.0.1/
echo "backup=$BK"
echo "done: $(date -Is)"
""".replace("__CADDY_ACTIVE__", caddy_active).replace("__CADDY_HTTPS__", caddy_https).replace("__MODE__", mode)
    return script


def validate_config(mode: str):
    """远端只写 /tmp 临时文件做 caddy validate，不触碰 active Caddyfile（P4 演练用）。"""
    if mode not in ecs_site.PROD_API_MODES:
        raise SystemExit("mode 只能是 %s" % (ecs_site.PROD_API_MODES,))
    st, rc, probe = _probe_remote()
    if st != "Success" or rc not in (0, "0"):
        print("[x] 远端探测失败")
        return 1
    active_https = "active=https" in probe
    os.environ["CLASS_API_MODE"] = mode
    active = ecs_site._caddy_https() if active_https else ecs_site._caddy_http()
    https_cfg = ecs_site._caddy_https()
    script = r"""#!/bin/bash
set -e
echo "=== 写入临时配置并 validate（mode=__MODE__，不动 active） ==="
cat > /tmp/cutover.Caddyfile <<'CADDY_EOF'
__CADDY_ACTIVE__
CADDY_EOF
cat > /tmp/cutover.Caddyfile.https.ready <<'CADDY_HTTPS_EOF'
__CADDY_HTTPS__
CADDY_HTTPS_EOF
caddy validate --config /tmp/cutover.Caddyfile --adapter caddyfile
caddy validate --config /tmp/cutover.Caddyfile.https.ready --adapter caddyfile
echo "active_sha=$(sha256sum /etc/caddy/Caddyfile | cut -d' ' -f1)"
echo "tmp_sha=$(sha256sum /tmp/cutover.Caddyfile | cut -d' ' -f1)"
rm -f /tmp/cutover.Caddyfile /tmp/cutover.Caddyfile.https.ready
echo done
""".replace("__CADDY_ACTIVE__", active).replace("__CADDY_HTTPS__", https_cfg).replace("__MODE__", mode)
    print("=== validate mode=%s（临时文件，仅 validate，不改 active） ===" % mode)
    st, rc, out = ecs_site.run_script(script, label="cutover-validate-%s" % mode, timeout=120, wait=240)
    print(out)
    print("[validate] status=%s exit=%s" % (st, rc))
    return 0 if (st == "Success" and rc in (0, "0") and "done" in (out or "")) else 1


def switch(mode: str, confirm: bool, dry_run: bool, print_script: bool):
    print("=== 预检（只读） ===")
    st, rc, probe = _probe_remote()
    print(probe)
    print("[预检] status=%s exit=%s" % (st, rc))
    if st != "Success" or rc not in (0, "0"):
        print("[x] 远端探测失败，拒绝切换")
        return 1
    prod_mode = "selfhosted" if "prod_mode=selfhosted" in probe else "cloudbase"
    print("[预检] 当前生产模式 = %s，目标模式 = %s" % (prod_mode, mode))
    if prod_mode == mode:
        print("[=] 已经是目标模式，无需切换")
        return 0
    if mode == "selfhosted":
        if "pgrest_active=active" not in probe:
            print("[x] PostgREST 未 active，拒绝切自建后端")
            return 1
        p_st, p_body = _http("http://%s/v1/rdb/rest-next/" % ecs_site.ECS_IP, timeout=20)
        print("[预检] staging 路由 HTTP %s（期望 200 OpenAPI）" % p_st)
        if p_st != 200:
            print("[x] staging 路由不可用，拒绝切自建后端")
            return 1
    script = build_switch_script(mode)
    if print_script or dry_run:
        print("\n===== 远端切换脚本（%s） =====\n%s" % (mode, script))
    if dry_run:
        print("[dry-run] 未执行")
        return 0
    if not confirm:
        print("[x] 生产切换必须显式 --confirm（先 --dry-run 检查脚本）")
        return 3
    print("\n=== 执行远端切换（%s） ===" % mode)
    st, rc, out = ecs_site.run_script(script, label="cutover-switch-%s" % mode, timeout=180, wait=300)
    print(out)
    print("[执行] status=%s exit=%s" % (st, rc))
    if st != "Success" or rc not in (0, "0"):
        print("[x] 远端切换命令失败；按上面备份路径回滚：python deploy\\ecs_cutover.py switch --to %s --confirm"
              % ("cloudbase" if mode == "selfhosted" else "selfhosted"))
        return 1
    # 公网端到端复核
    ok = True
    try:
        p_st, p_body = _http("http://%s/v1/rdb/rest/" % ecs_site.ECS_IP)
        detail = p_body[:80].decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        p_st, detail = 0, type(exc).__name__
    s_st, _ = _http("http://%s/v1/rdb/rest-next/" % ecs_site.ECS_IP)
    print("\n=== 公网复核 ===")
    print("生产 /v1/rdb/rest/ HTTP %s %s（selfhosted 期望 200 OpenAPI；cloudbase 期望 401）"
          % (p_st, detail))
    print("staging /v1/rdb/rest-next/ HTTP %s（期望 200）" % s_st)
    if mode == "selfhosted" and p_st != 200:
        ok = False
    if mode == "cloudbase" and p_st == 200:
        ok = False
    if s_st != 200:
        ok = False
    print("[结果]", "OK" if ok else "FAIL")
    return 0 if ok else 1


def status():
    st, rc, probe = _probe_remote()
    print(probe)
    print("[status] status=%s exit=%s" % (st, rc))
    try:
        p_st, body = _http("http://%s/v1/rdb/rest/" % ecs_site.ECS_IP)
        print("公网生产 /v1/rdb/rest/ HTTP %s %s"
              % (p_st, body[:90].decode("utf-8", "replace")))
    except Exception as exc:  # noqa: BLE001
        print("公网生产 /v1/rdb/rest/ ERR %s" % type(exc).__name__)
    try:
        s_st, _ = _http("http://%s/v1/rdb/rest-next/" % ecs_site.ECS_IP)
        print("公网 staging /v1/rdb/rest-next/ HTTP %s" % s_st)
    except Exception as exc:  # noqa: BLE001
        print("公网 staging ERR %s" % type(exc).__name__)
    return 0 if st == "Success" and rc in (0, "0") else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="P4 生产 API 切流（Caddy 路由，云助手）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("status", help="只读查看当前路由/服务/探针")
    sw = sub.add_parser("switch", help="切换生产 API 上游")
    sw.add_argument("--to", required=True, choices=list(ecs_site.PROD_API_MODES))
    sw.add_argument("--confirm", action="store_true", help="生产切换必须显式确认")
    sw.add_argument("--dry-run", action="store_true", help="只打印远端脚本，不执行")
    sw.add_argument("--print-script", action="store_true", help="打印远端切换脚本")
    va = sub.add_parser("validate", help="远端临时文件 caddy validate（P4 演练，不改 active）")
    va.add_argument("--to", required=True, choices=list(ecs_site.PROD_API_MODES))
    ns = ap.parse_args(argv)
    if ns.cmd == "status":
        return status()
    if ns.cmd == "validate":
        return validate_config(ns.to)
    return switch(ns.to, ns.confirm, ns.dry_run, ns.print_script)


if __name__ == "__main__":
    sys.exit(main())
