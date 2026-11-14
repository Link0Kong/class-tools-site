# -*- coding: utf-8 -*-
"""把地图编辑器 + 共享状态服务部署到 ECS（云助手通道）。

用法（web 目录，系统 python）：
  python deploy\\ecs_map.py probe
  python deploy\\ecs_map.py deploy
"""
import argparse
import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ecs_site  # noqa: E402

APP = os.path.join(HERE, "map_app.py")
OSS = ecs_site.OSS_BASE
SERVICE = "class-tools-map"

REMOTE = r"""#!/bin/bash
set -euo pipefail
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p /var/www/tool/map /opt/class-tools/map /opt/class-tools/map_backup/$TS
cp -a /etc/caddy/Caddyfile /opt/class-tools/map_backup/$TS/Caddyfile.old 2>/dev/null || true

echo "=== static ==="
for f in campus_builder.html campus_builder_loaded.html; do
  curl -fsSL "__OSS__/map/$f" -o "/var/www/tool/map/$f"
  ls -l "/var/www/tool/map/$f"
done
chmod 644 /var/www/tool/map/*.html

echo "=== seed ==="
curl -fsSL "__OSS__/map/campus-manual-202611140223_organized.json" -o /opt/class-tools/map/seed.json
ls -l /opt/class-tools/map/seed.json

echo "=== app.py ==="
if [ -s /tmp/map_app.b64 ]; then
  base64 -d /tmp/map_app.b64 > /opt/class-tools/map/app.py.new
  python3 -m py_compile /opt/class-tools/map/app.py.new
  mv /opt/class-tools/map/app.py.new /opt/class-tools/map/app.py
  rm -f /tmp/map_app.b64
  chown root:root /opt/class-tools/map/app.py; chmod 755 /opt/class-tools/map/app.py
  echo "app.py: $(stat -c%s /opt/class-tools/map/app.py) bytes"
else
  echo "FATAL app.py missing"; exit 4
fi
chown -R www-data:www-data /opt/class-tools/map
chmod 750 /opt/class-tools/map

echo "=== systemd ==="
cat > /etc/systemd/system/__SERVICE__.service <<'UNIT'
[Unit]
Description=Class tools campus map shared state
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
Environment=MAP_ROOT=/opt/class-tools/map
Environment=MAP_PORT=8095
ExecStart=/usr/bin/python3 /opt/class-tools/map/app.py
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/class-tools/map

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable __SERVICE__
systemctl restart __SERVICE__
sleep 1
systemctl is-active __SERVICE__
curl -fsS http://127.0.0.1:8095/__health; echo

echo "=== caddy route ==="
python3 - <<'PY'
p='/etc/caddy/Caddyfile'
s=open(p,encoding='utf-8').read()
if '/map/api/*' not in s:
    lines=s.splitlines()
    idx=[i for i,l in enumerate(lines) if l.strip()=='handle {']
    for i in reversed(idx):
        lines[i:i]=['\thandle /map/api/* {','\t\turi strip_prefix /map/api','\t\treverse_proxy 127.0.0.1:8095','\t}']
    s='\n'.join(lines)+'\n'
    open(p,'w',encoding='utf-8').write(s)
    print('inserted',len(idx),'blocks')
else:
    print('route already present')
PY
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy
sleep 1
echo "=== public api ==="
curl -fsS http://127.0.0.1/map/api/state | head -c 200; echo
echo DONE
"""


def deploy():
    app_b64 = base64.b64encode(open(APP, "rb").read()).decode("ascii")
    script = REMOTE.replace("__OSS__", OSS).replace("__SERVICE__", SERVICE)
    # app.py 用 base64 分片写入远端临时文件
    head = "printf '%s' '" + app_b64[:8000] + "' > /tmp/map_app.b64\n"
    rest = "".join(["printf '%s' '" + app_b64[i:i + 8000] + "' >> /tmp/map_app.b64\n"
                    for i in range(8000, len(app_b64), 8000)])
    full = head + rest + script
    st, code, out = ecs_site.run_script(full, timeout=300, wait=600, label="apply")
    print(out)
    print("status=%s exit=%s" % (st, code))
    return 0 if st == "Success" and str(code) == "0" else 1


def probe():
    st, code, out = ecs_site.run_script(
        "systemctl is-active caddy; systemctl is-active __SERVICE__ 2>/dev/null || true; "
        "grep -n 'map/api' /etc/caddy/Caddyfile || true; "
        "ls -l /var/www/tool/map 2>/dev/null || true; "
        "curl -fsS http://127.0.0.1:8095/__health 2>/dev/null || true".replace("__SERVICE__", SERVICE),
        timeout=90, wait=180, label="probe")
    print(out)
    return 0 if st == "Success" else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["probe", "deploy"])
    a = ap.parse_args()
    sys.exit(probe() if a.cmd == "probe" else deploy())
