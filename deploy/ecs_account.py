# -*- coding: utf-8 -*-
"""部署「OPPO 账号绑定/快捷登录验证服务」到阿里云 ECS（云助手通道，无需 SSH）。

- 代码：`deploy/account_app.py` → `/opt/class-tools/account/app.py`
- 密钥：publish key（`deploy/cloudbase/publish_key.txt`）、管理员班级 token
  （`C:\\briefdesk\\secrets\\class-token.json`）、OPPO 账号服务凭证
  （`C:\\briefdesk\\secrets\\oppo-account.json`，缺失时写空 {}，服务 configured=false）
- 服务：systemd `class-tools-account.service`，127.0.0.1:8094，Python 标准库
- 路由：`deploy/ecs_site.py` 的 Caddy 配置提供 `/account/*` 反代（strip_prefix）

用法（web 目录，系统 python，需要 aliyunsdkcore）：
  python deploy\\ecs_account.py deploy   # 上传代码/密钥 → 装 unit → 重启 → 本机健康检查
  python deploy\\ecs_account.py probe    # 只读：服务/健康/配置状态/日志
  python deploy\\ecs_account.py verify   # 公网：http://<ip>/account/__health
"""
import argparse
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ecs_site  # noqa: E402

APP_LOCAL = os.path.join(HERE, "account_app.py")
PUBLISH_LOCAL = os.path.join(HERE, "cloudbase", "publish_key.txt")
ADMIN_TOKEN_LOCAL = r"C:\briefdesk\secrets\class-token.json"
OPPO_ACCOUNT_LOCAL = r"C:\briefdesk\secrets\oppo-account.json"
SERVICE = "class-tools-account"
APP_DIR = "/opt/class-tools/account"
BASE_URL = "http://%s/account" % ecs_site.ECS_IP
CHUNK = 9000

UNIT_TEXT = r"""[Unit]
Description=Class tools OPPO account binding / quick-login verifier (Caddy /account)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
Environment=ACCOUNT_PORT=8094
Environment=ACCOUNT_GATEWAY=https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/
Environment=ACCOUNT_PUBLISH_KEY_FILE=/opt/class-tools/account/publish_key
Environment=ACCOUNT_ADMIN_TOKEN_FILE=/opt/class-tools/account/class-token
Environment=ACCOUNT_OPPO_FILE=/opt/class-tools/account/oppo-account.json
Environment=ACCOUNT_MOCK=0
ExecStart=/usr/bin/python3 /opt/class-tools/account/app.py
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/class-tools/account

[Install]
WantedBy=multi-user.target
"""


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _b64_file(path):
    with open(path, "rb") as fh:
        return _b64(fh.read())


def _admin_token_bytes():
    raw = open(ADMIN_TOKEN_LOCAL, "rb").read().decode("utf-8", "replace")
    try:
        obj = json.loads(raw)
        tok = str(obj.get("token") or "").strip()
    except Exception:  # noqa: BLE001
        tok = raw.strip()
    return tok.encode("utf-8")


def _oppo_account_bytes():
    if os.path.isfile(OPPO_ACCOUNT_LOCAL):
        raw = open(OPPO_ACCOUNT_LOCAL, "rb").read()
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
            if isinstance(obj, dict) and str(obj.get("app_key") or "").strip() \
                    and str(obj.get("app_secret") or "").strip():
                return raw
        except Exception:  # noqa: BLE001
            pass
    return b"{}"


def _smart_text(data, limit=600):
    if isinstance(data, bytes):
        s = data.decode("utf-8", "replace")
    else:
        s = str(data or "")
    return s[:limit].strip()


def _upload(name, data, label):
    b64 = _b64(data)
    chunks = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)]
    prep = ("#!/bin/bash\nset -e\nmkdir -p %s\nrm -f /tmp/%s.b64\necho prep-ok\n"
            % (APP_DIR, name))
    st, rc, out = ecs_site.run_script(prep, label=label + "-prep", timeout=120, wait=180)
    print("[%s prep] %s %s" % (name, st, _smart_text(out, 120)))
    if st != "Success":
        return False
    for idx, chunk in enumerate(chunks, start=1):
        script = ("#!/bin/bash\nset -e\necho '%s' >> /tmp/%s.b64\necho chunk-%d-ok\n"
                  % (chunk, name, idx))
        st, rc, out = ecs_site.run_script(script, label="%s-chunk-%d" % (label, idx),
                                          timeout=120, wait=180)
        if st != "Success":
            print("[%s chunk %d] %s %s" % (name, idx, st, _smart_text(out, 160)))
            return False
    script = ("#!/bin/bash\nset -e\nbase64 -d /tmp/%s.b64 > %s/%s\nrm -f /tmp/%s.b64\n"
              "echo uploaded\n" % (name, APP_DIR, name, name))
    st, rc, out = ecs_site.run_script(script, label=label + "-write", timeout=120, wait=180)
    print("[%s write] %s %s" % (name, st, _smart_text(out, 120)))
    return st == "Success"


def install_service():
    st, rc, out = ecs_site.run_script("#!/bin/bash\nset -e\nmkdir -p %s\necho ok\n" % APP_DIR,
                                      label="account-prep", timeout=120, wait=180)
    print("[prep] %s %s" % (st, _smart_text(out, 120)))
    if st != "Success":
        return 1
    if not _upload("app.py", open(APP_LOCAL, "rb").read(), "account-app"):
        return 1
    files = [
        ("publish_key", open(PUBLISH_LOCAL, "rb").read()),
        ("class-token", _admin_token_bytes()),
        ("oppo-account.json", _oppo_account_bytes()),
    ]
    for name, data in files:
        if not _upload(name, data, "account-" + name.replace(".", "-")):
            return 1
    b64_unit = _b64(UNIT_TEXT.encode("utf-8"))
    final = r"""#!/bin/bash
set -e
APP_DIR="__APP_DIR__"
SERVICE="__SERVICE__"
chown -R www-data:www-data "$APP_DIR" 2>/dev/null || true
chmod 755 "$APP_DIR"
chmod 640 "$APP_DIR/class-token" "$APP_DIR/oppo-account.json" "$APP_DIR/publish_key" 2>/dev/null || true
chown root:www-data "$APP_DIR/class-token" "$APP_DIR/oppo-account.json" "$APP_DIR/publish_key" 2>/dev/null || true
chmod 755 "$APP_DIR/app.py"
python3 -m py_compile "$APP_DIR/app.py"
rm -rf "$APP_DIR/__pycache__"
echo "__UNIT_B64__" | base64 -d > "/etc/systemd/system/$SERVICE.service"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1 || true
systemctl restart "$SERVICE"
sleep 1
OK=0
for i in $(seq 1 10); do
  if curl -fsS -m 3 http://127.0.0.1:8094/__health >/tmp/account_health.json 2>/dev/null; then OK=1; break; fi
  sleep 1
done
if [ "$OK" != "1" ]; then
  echo "FATAL account health failed"
  journalctl -u "$SERVICE" -n 60 --no-pager || true
  exit 5
fi
echo "active=$(systemctl is-active "$SERVICE") enabled=$(systemctl is-enabled "$SERVICE" 2>/dev/null || true)"
cat /tmp/account_health.json; echo ""
echo "done: $(date -Is)"
""".replace("__APP_DIR__", APP_DIR).replace("__SERVICE__", SERVICE).replace("__UNIT_B64__", b64_unit)
    st, rc, out = ecs_site.run_script(final, label="account-final", timeout=240, wait=360)
    print(out or "")
    print("[结果] status=%s exit=%s" % (st, rc))
    return 0 if (st == "Success" and rc in (0, "0", None)) else 1


def probe():
    script = r"""#!/bin/bash
set +e
echo "=== service ==="
systemctl is-active __SERVICE__ 2>/dev/null; systemctl is-enabled __SERVICE__ 2>/dev/null
echo "=== health ==="
curl -s -m 5 http://127.0.0.1:8094/__health; echo ""
echo "=== files ==="
ls -la __APP_DIR__ 2>/dev/null | head -12
echo "=== journal ==="
journalctl -u __SERVICE__ -n 20 --no-pager 2>/dev/null | tail -20
""".replace("__SERVICE__", SERVICE).replace("__APP_DIR__", APP_DIR)
    st, rc, out = ecs_site.run_script(script, label="account-probe", timeout=120, wait=180)
    print(out or "")
    print("[结果] status=%s exit=%s" % (st, rc))
    return 0


def verify():
    import urllib.request
    url = BASE_URL + "/__health"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            body = r.read().decode("utf-8", "replace")
            print("GET %s -> %s %s" % (url, r.status, body[:400]))
            return 0 if r.status == 200 and '"ok": true' in body else 1
    except Exception as exc:  # noqa: BLE001
        print("GET %s FAIL %r" % (url, exc))
        return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["deploy", "probe", "verify"])
    args = ap.parse_args()
    if args.action == "deploy":
        return install_service()
    if args.action == "probe":
        return probe()
    return verify()


if __name__ == "__main__":
    sys.exit(main())
