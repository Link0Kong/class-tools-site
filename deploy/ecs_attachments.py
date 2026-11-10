# -*- coding: utf-8 -*-
"""部署「通知附件服务」到阿里云 ECS（云助手通道，无需 SSH）。

- 代码：web/attachments/{common.py,server.py} → /opt/class-tools/att-code/
- 数据：/opt/class-tools/attachments/（www-data 可写）
- 服务：systemd `class-tools-att.service`，127.0.0.1:8091，EnvironmentFile=/etc/briefdesk-board.env
  （复用 briefdesk-board 的 SYNC_TOKEN；不新增密钥传输）
- Caddy 路由：由 deploy/ecs_site.py 的配置提供 `/att/*` 反代（本脚本不直接改 Caddyfile）

用法（web 目录，系统 python）：
  python deploy\\ecs_attachments.py deploy
  python deploy\\ecs_attachments.py probe
"""
import base64
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ecs_site  # noqa: E402

LOCAL = os.path.join(os.path.dirname(HERE), "attachments")

PROBE = r"""#!/bin/bash
set +e
echo "=== service ==="; systemctl is-active class-tools-att 2>/dev/null; systemctl is-enabled class-tools-att 2>/dev/null
echo "=== health ==="; curl -s -m 5 http://127.0.0.1:8091/att/healthz
echo ""
echo "=== dir ==="; ls -la /opt/class-tools/att-code /opt/class-tools/attachments 2>/dev/null | head -20
echo "=== caddy att route ==="; grep -n "/att/" /etc/caddy/Caddyfile 2>/dev/null || echo "(no att route)"
echo "=== journal tail ==="; journalctl -u class-tools-att -n 6 --no-pager 2>/dev/null || true
echo "=== done ==="; exit 0
"""


def _b64_file(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def build_deploy_script():
    common_b64 = _b64_file(os.path.join(LOCAL, "common.py"))
    server_b64 = _b64_file(os.path.join(LOCAL, "server.py"))
    selftest = r'''
import hashlib, json, os, sys, time, urllib.request, urllib.parse
sys.path.insert(0, "/opt/class-tools/att-code")
from common import content_id, derive_key, signed_url

def read_token():
    tok = os.environ.get("SYNC_TOKEN") or ""
    if tok:
        return tok
    try:
        with open("/etc/briefdesk-board.env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("SYNC_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""

tok = read_token()
if not tok:
    print("ATT_SELFTEST " + json.dumps({"ok": False, "err": "no SYNC_TOKEN (env or /etc/briefdesk-board.env)"}))
    sys.exit(0)
data = ("dsh-attachment-selftest-%d" % int(time.time())).encode()
req = urllib.request.Request("http://127.0.0.1:8091/att/upload", data=data, method="POST")
req.add_header("X-Sync-Token", tok)
req.add_header("X-Att-Name", urllib.parse.quote("selftest.txt"))
req.add_header("X-Att-Mime", "text/plain")
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        res = json.loads(r.read().decode())
except Exception as e:  # noqa: BLE001
    print("ATT_SELFTEST " + json.dumps({"ok": False, "err": "upload %s: %s" % (type(e).__name__, e)}))
    sys.exit(0)
att_id = res.get("id")
key = derive_key(tok)
exp = int(time.time()) + 3600
sig = signed_url("", att_id, exp, key).split("sig=")[1]
try:
    with urllib.request.urlopen("http://127.0.0.1:8091/att/%s?exp=%d&sig=%s" % (att_id, exp, sig), timeout=10) as r:
        got = r.read()
except Exception as e:  # noqa: BLE001
    print("ATT_SELFTEST " + json.dumps({"ok": False, "err": "get %s: %s" % (type(e).__name__, e)}))
    sys.exit(0)
print("ATT_SELFTEST " + json.dumps({
    "ok": got == data and res.get("size") == len(data),
    "id": att_id, "exp": exp, "sig": sig,
    "sha_expect": hashlib.sha256(data).hexdigest()[:16],
    "sha_got": hashlib.sha256(got).hexdigest()[:16]}))
'''
    return r"""#!/bin/bash
set -e
TS=$(date +%Y%m%d-%H%M%S)
BK=/opt/class-tools/backup/$TS
mkdir -p /opt/class-tools/att-code /opt/class-tools/attachments "$BK"
[ -f /opt/class-tools/att-code/server.py ] && cp -a /opt/class-tools/att-code/server.py "$BK/server.py.old" || true
[ -f /opt/class-tools/att-code/common.py ] && cp -a /opt/class-tools/att-code/common.py "$BK/common.py.old" || true

echo "=== 1. 写代码 ==="
echo '__COMMON_B64__' | base64 -d > /opt/class-tools/att-code/common.py
echo '__SERVER_B64__' | base64 -d > /opt/class-tools/att-code/server.py
python3 -m py_compile /opt/class-tools/att-code/common.py /opt/class-tools/att-code/server.py
chown -R root:root /opt/class-tools/att-code
chown -R www-data:www-data /opt/class-tools/attachments
chmod 755 /opt/class-tools /opt/class-tools/att-code
chmod 775 /opt/class-tools/attachments

echo "=== 2. systemd ==="
cat > /etc/systemd/system/class-tools-att.service <<'UNIT_EOF'
[Unit]
Description=Class tools attachment server (signed URLs)
After=network.target

[Service]
User=www-data
Group=www-data
EnvironmentFile=/etc/briefdesk-board.env
Environment=ATT_DIR=/opt/class-tools/attachments
Environment=ATT_PORT=8091
ExecStart=/usr/bin/python3 /opt/class-tools/att-code/server.py
Restart=always
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT_EOF
systemctl daemon-reload
systemctl enable class-tools-att >/dev/null 2>&1 || true
systemctl restart class-tools-att
sleep 1
systemctl is-active class-tools-att
curl -s -m 5 http://127.0.0.1:8091/att/healthz || true
echo ""

echo "=== 3. 本机自测（上传→签名 GET→校验） ==="
python3 - <<'PY_SELFTEST'
__SELFTEST__
PY_SELFTEST
echo "done: $(date -Is)"
""".replace("__COMMON_B64__", common_b64) \
   .replace("__SERVER_B64__", server_b64) \
   .replace("__SELFTEST__", selftest)


def _fetch(url, timeout=20):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read()


def local_verify(sig_line):
    """用本机经 Caddy 的公网入口验证签名 URL 链路。"""
    try:
        obj = json.loads(sig_line)
    except ValueError:
        print("[verify] 无法解析自测结果")
        return 1
    if not obj.get("ok"):
        print("[verify] 服务端自测失败:", obj.get("err"))
        return 1
    url = "http://%s/att/%s?exp=%s&sig=%s" % (ecs_site.ECS_IP, obj["id"], obj["exp"], obj["sig"])
    try:
        st, hd, body = _fetch(url)
    except Exception as e:  # noqa: BLE001
        print("[verify] 经 Caddy 访问失败:", type(e).__name__, e)
        return 1
    import hashlib
    sha = hashlib.sha256(body).hexdigest()[:16]
    good = st == 200 and sha == obj.get("sha_expect") and hd.get("Cache-Control", "").startswith("public")
    print("[verify] HTTP %s，%d B，sha=%s vs %s -> %s，Cache-Control=%s"
          % (st, len(body), sha, obj.get("sha_expect"), "MATCH" if good else "MISMATCH", hd.get("Cache-Control")))
    bad = url.replace("sig=", "sig=0")
    try:
        _fetch(bad)
        print("[verify] 篡改签名仍可访问（异常！）")
        good = False
    except urllib.error.HTTPError as e:
        print("[verify] 篡改签名被拒 HTTP %s -> OK" % e.code)
    return 0 if good else 1


def main(argv=None):
    argv = argv or sys.argv[1:]
    cmd = argv[0] if argv else "deploy"
    if cmd == "probe":
        st, rc, out = ecs_site.run_script(PROBE, label="att-probe", timeout=60, wait=120)
        print(out)
        return 0 if st == "Success" else 1
    if cmd == "deploy":
        st, rc, out = ecs_site.run_script(build_deploy_script(), label="att-deploy", timeout=300, wait=480)
        print(out)
        if st != "Success" or rc not in (0, "0", None):
            print("[deploy] 失败 status=%s exit=%s" % (st, rc))
            return 1
        line = ""
        for ln in out.splitlines():
            if ln.startswith("ATT_SELFTEST "):
                line = ln[len("ATT_SELFTEST "):]
        if not line:
            print("[deploy] 未找到自测输出")
            return 1
        return local_verify(line)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
