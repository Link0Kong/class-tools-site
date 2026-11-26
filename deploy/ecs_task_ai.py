"""Deploy the task AI service through ECS Cloud Assistant without uploading secrets."""

import argparse
import base64
import gzip
import hashlib
from pathlib import Path

import ecs_site


APP = Path(__file__).with_name("task_ai_app.py")
PROBE = """#!/bin/bash
set -euo pipefail
systemctl is-active class-tools-task-ai.service
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8096/__health; echo
if grep -Fq 'handle /task-ai/suggest {' /etc/caddy/Caddyfile; then echo 'route configured'; fi
"""

INSTALL = """#!/bin/bash
set -euo pipefail
umask 077
APP=/opt/class-tools/task-ai
UNIT=/etc/systemd/system/class-tools-task-ai.service
KEY=/etc/class-tools/task-ai.deepseek-key
install -d -m 0755 "$APP"
mkdir -p /etc/class-tools
if [ ! -s /opt/class-tools/drop/publish_key ]; then
    echo "CloudBase publish key is missing from the existing ECS gateway setup"
    exit 1
fi
if [ ! -e "$KEY" ]; then install -m 0600 /dev/null "$KEY"; fi
stage=$(mktemp -d "$APP/.stage.XXXXXXXX")
trap 'rm -f "$stage"/app.py "$stage"/app.previous "$stage"/service "$stage"/service.previous; rmdir "$stage"' EXIT
printf '%s' '__APP_B64__' | base64 -d | gzip -dc > "$stage/app.py"
printf '%s  %s\\n' '__APP_SHA__' "$stage/app.py" | sha256sum -c --status
python3 -c 'import sys; compile(open(sys.argv[1], "rb").read(), "app.py", "exec")' "$stage/app.py"
cat > "$stage/service" <<'UNIT_EOF'
[Unit]
Description=ClassTools task AI draft service
After=network-online.target

[Service]
Type=simple
DynamicUser=yes
LoadCredential=deepseek-api-key:/etc/class-tools/task-ai.deepseek-key
LoadCredential=cloudbase-publish-key:/opt/class-tools/drop/publish_key
ExecStart=/usr/bin/python3 -B /opt/class-tools/task-ai/app.py
Restart=on-failure
RestartSec=3
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT_EOF
if [ -e "$APP/app.py" ]; then cp -a "$APP/app.py" "$stage/app.previous"; fi
if [ -e "$UNIT" ]; then cp -a "$UNIT" "$stage/service.previous"; fi
chmod 0644 "$stage/app.py" "$stage/service"
mv "$stage/app.py" "$APP/app.py"
mv "$stage/service" "$UNIT"
check_health() {
    for attempt in 1 2 3 4 5; do
        if health=$(curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8096/__health) &&
                printf '%s' "$health" | python3 -c 'import json, sys; assert json.load(sys.stdin)["service"] == "task-ai"'; then
            printf '%s\\n' "$health"
            return 0
        fi
        sleep 1
    done
    return 1
}
if ! systemctl daemon-reload || ! systemctl restart class-tools-task-ai.service || ! check_health; then
    if [ -e "$stage/app.previous" ]; then mv "$stage/app.previous" "$APP/app.py"; else rm -f "$APP/app.py"; fi
    if [ -e "$stage/service.previous" ]; then mv "$stage/service.previous" "$UNIT"; else rm -f "$UNIT"; fi
    systemctl daemon-reload
    if [ -e "$UNIT" ]; then systemctl restart class-tools-task-ai.service; fi
    exit 1
fi
systemctl enable class-tools-task-ai.service
"""

ROUTE = """#!/bin/bash
set -euo pipefail
curl --noproxy '*' -fsS --max-time 4 http://127.0.0.1:8096/__health > /dev/null
python3 - <<'PY'
import shutil
import subprocess
import tempfile
from pathlib import Path

anchor = "tool.furina.fun {\\n"
route = __ROUTE_REPR__
configs = [Path("/etc/caddy/Caddyfile"), Path("/etc/caddy/Caddyfile.https.ready")]
backup_root = Path("/var/backups")
backup_root.mkdir(exist_ok=True)
backup = Path(tempfile.mkdtemp(prefix="class-tools-task-ai.", dir=backup_root))
staged = []
changed = []
try:
    for path in configs:
        if path == configs[1] and not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        if original.count(anchor) != 1:
            raise SystemExit("Expected one official HTTPS site in " + str(path))
        before, after = original.split(anchor, 1)
        site = after.split("\\n}", 1)[0]
        if route in site:
            continue
        if "/task-ai/suggest" in original:
            raise SystemExit("Found a different task AI route in " + str(path))
        temporary = path.with_name(path.name + ".task-ai-next")
        staged.append((path, temporary))
        shutil.copy2(path, backup / path.name)
        shutil.copy2(path, temporary)
        temporary.write_text(before + anchor + route + "\\n" + after, encoding="utf-8")
        subprocess.run(["caddy", "validate", "--config", str(temporary), "--adapter", "caddyfile"], check=True)
    for path, temporary in staged:
        temporary.replace(path)
        changed.append(path)
    if changed:
        subprocess.run(["systemctl", "reload", "caddy"], check=True)
    result = subprocess.check_output([
        "curl", "--noproxy", "*", "-sS", "--max-time", "5", "-o", "/dev/null", "-w", "%{http_code}",
        "--resolve", "tool.furina.fun:443:127.0.0.1", "-X", "POST", "https://tool.furina.fun/task-ai/suggest",
    ], text=True)
    if result != "401":
        raise SystemExit("Expected 401 for anonymous task AI POST, received " + result)
except (Exception, SystemExit):
    for path in changed:
        shutil.copy2(backup / path.name, path)
    if changed:
        subprocess.run(["systemctl", "reload", "caddy"], check=True)
    raise
finally:
    for _, temporary in staged:
        temporary.unlink(missing_ok=True)
print("Task AI HTTPS route returns 401 without a class token")
if changed:
    print("Previous Caddy config saved in", backup)
else:
    backup.rmdir()
PY
"""


def install_script():
    app = APP.read_bytes()
    packed = base64.b64encode(gzip.compress(app, mtime=0)).decode("ascii")
    return INSTALL.replace("__APP_B64__", packed).replace("__APP_SHA__", hashlib.sha256(app).hexdigest())


def route_script():
    return ROUTE.replace("__ROUTE_REPR__", repr(ecs_site.TASK_AI_ROUTE))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["deploy", "route", "probe"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    script = {"deploy": install_script, "route": route_script, "probe": lambda: PROBE}[args.action]()
    if args.dry_run:
        print(script.replace("\r\n", "\n"))
        return 0
    status, code, output = ecs_site.run_script(script, timeout=60, wait=100, label="task-ai-" + args.action)
    print(output or "")
    return 0 if status == "Success" and str(code) == "0" else 1


if __name__ == "__main__":
    raise SystemExit(main())
