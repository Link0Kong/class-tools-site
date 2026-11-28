"""Run on ECS from ecs_home_context.py with a verified, private staging bundle."""

import base64
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


APP = Path("/opt/class-tools/home-context")
STATE = Path("/var/lib/class-tools-home-context")
UNIT_DIR = Path("/etc/systemd/system")
UNIT = "class-tools-home-context-api.service"
DAILY = "class-tools-home-context-daily.service"
TIMER = "class-tools-home-context-daily.timer"
CONFIGS = (Path("/etc/caddy/Caddyfile"), Path("/etc/caddy/Caddyfile.https.ready"))
DOMAIN = "tool.furina.fun"
PATHS = ("/home-context/content/v1", "/home-context/weather/v1")
ROUTES = "\n".join("\thandle " + path + " {\n\t\treverse_proxy 127.0.0.1:8097\n\t}" for path in PATHS)
ROOT = Path("/var/www/tool_backup")


def command(*args, check=True):
    return subprocess.run(args, check=check)


def state(option, unit):
    return subprocess.run(("systemctl", option, "--quiet", unit), check=False).returncode == 0


def http(path, secure=False):
    if secure:
        args = ("--resolve", DOMAIN + ":443:127.0.0.1", "https://" + DOMAIN + path)
    else:
        args = ("http://127.0.0.1:8097" + path,)
    data = subprocess.check_output(("curl", "--noproxy", "*", "-sS", "--max-time", "12",
                                    "-w", "\n%{http_code}", *args))
    raw, status = data.rsplit(b"\n", 1)
    return int(status), json.loads(raw)


def publication_day(stamp):
    return stamp.astimezone(ZoneInfo("Asia/Shanghai")).date()


def dates(raw):
    try:
        data = json.loads(raw)
        start = datetime.fromisoformat(data["generatedAt"].replace("Z", "+00:00"))
        expiry = datetime.fromisoformat(data["expiresAt"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if start <= now < expiry and expiry - start <= timedelta(hours=72) and data["entries"]:
            return start, expiry
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    return None


def write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    info = path.stat() if path.exists() else None
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        tmp = Path(out.name)
        out.write(data)
    try:
        if info:
            os.chown(tmp, info.st_uid, info.st_gid)
            mode = info.st_mode & 0o777
        elif path.parent == STATE:
            owner = STATE.stat()
            os.chown(tmp, owner.st_uid, owner.st_gid)
        tmp.chmod(mode)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def route_config(path):
    raw = path.read_text(encoding="utf-8")
    marker = DOMAIN + " {\n"
    if raw.count(marker) != 1:
        raise ValueError("Expected one HTTPS site in " + str(path))
    before, after = raw.split(marker)
    if ROUTES in after.split("\n}", 1)[0]:
        return None
    if any(route in raw for route in PATHS):
        raise ValueError("Different home context route in " + str(path))
    revised = (before + marker + ROUTES + "\n" + after).encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent) as next_file:
        next_file.write(revised)
        next_file.flush()
        command("caddy", "validate", "--adapter", "caddyfile", "--config", next_file.name)
    return revised


def install(bundle):
    files = {
        APP / "home_context_app.py": bundle["home_context_app.py"],
        APP / "task_ai_app.py": bundle["task_ai_app.py"],
        APP / "home_regions.tsv": bundle["home_regions.tsv"],
        UNIT_DIR / UNIT: bundle[UNIT],
        UNIT_DIR / DAILY: bundle[DAILY],
        UNIT_DIR / TIMER: bundle[TIMER],
    }
    for path, raw in files.items():
        if path.suffix == ".py":
            compile(raw, str(path), "exec")
    routes = {}
    for path in CONFIGS:
        if path.exists():
            revised = route_config(path)
            if revised:
                routes[path] = revised
    ROOT.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="home-context.", dir=ROOT))
    saved = {}
    for path in [*files, *routes]:
        if path.exists():
            copy = backup / path.name
            shutil.copy2(path, copy)
            saved[path] = copy
    live = {unit: state("is-active", unit) for unit in (UNIT, TIMER)}
    enabled = {unit: state("is-enabled", unit) for unit in (UNIT, TIMER)}
    touched = []
    seed = bundle.get("content.json")
    stamp = dates(seed) if seed else None
    path = STATE / "content.json"
    original = dates(path.read_bytes()) if path.is_file() else None
    if stamp and (not original or original[0] < stamp[0]):
        files[path] = seed
        if path.is_file():
            copy = backup / path.name
            shutil.copy2(path, copy)
            saved[path] = copy
    try:
        for target, raw in files.items():
            write(target, raw)
            touched.append(target)
        if stamp and path in files:
            marker = STATE / ("attempt-" + publication_day(stamp[0]).isoformat())
            if not marker.exists():
                write(marker, b"reviewed\n", 0o640)
                touched.append(marker)
        command("systemctl", "daemon-reload")
        command("systemd-analyze", "verify", str(UNIT_DIR / UNIT), str(UNIT_DIR / DAILY), str(UNIT_DIR / TIMER))
        command("systemctl", "restart", UNIT)
        if not original and not stamp:
            command("systemctl", "start", DAILY)
        for _ in range(8):
            try:
                status, batch = http(PATHS[0])
                if status == 200 and dates(json.dumps(batch)): break
            except (ValueError, OSError, subprocess.CalledProcessError):
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Local content endpoint did not return a current batch")
        for target, raw in routes.items():
            write(target, raw)
            touched.append(target)
        if routes:
            command("systemctl", "reload", "caddy")
        content_status, content = http(PATHS[0], secure=True)
        weather_status, weather = http(PATHS[1] + "?region=minhou", secure=True)
        if content_status != 200 or not dates(json.dumps(content)):
            raise RuntimeError("Unexpected public content response")
        if not ((weather_status == 200 and weather.get("regionId") == "minhou") or
                (weather_status == 503 and weather.get("error") == "unavailable")):
            raise RuntimeError("Unexpected public weather response")
        command("systemctl", "enable", UNIT)
        command("systemctl", "enable", "--now", TIMER)
    except (Exception, KeyboardInterrupt):
        for unit in (TIMER, UNIT):
            command("systemctl", "stop", unit, check=False)
            if not enabled[unit]:
                command("systemctl", "disable", unit, check=False)
        for target in reversed(touched):
            if target in saved:
                write(target, saved[target].read_bytes())
            else:
                target.unlink(missing_ok=True)
        command("systemctl", "daemon-reload")
        for unit in (UNIT, TIMER):
            if live[unit]:
                command("systemctl", "start", unit, check=False)
        if any(path in touched for path in CONFIGS):
            command("systemctl", "reload", "caddy", check=False)
        raise
    print(f"HOME_CONTEXT_OK content={content_status} entries={len(content['entries'])} weather={weather_status}")
    print("Backup:", backup)
    command("systemctl", "list-timers", TIMER, "--no-pager")


def publish_presentation(value):
    path = STATE / "presentation.json"
    original = path.read_bytes() if path.is_file() else None
    write(path, (json.dumps({"englishTypography": value}) + "\n").encode("ascii"))
    try:
        status, batch = http(PATHS[0], secure=True)
        if status != 200 or batch.get("englishTypography") != value:
            raise RuntimeError("Public content endpoint did not return the new presentation")
    except (Exception, KeyboardInterrupt):
        if original is not None:
            write(path, original)
        else:
            path.unlink(missing_ok=True)
        raise
    print(f"HOME_CONTEXT_PRESENTATION_OK englishTypography={value}")


if __name__ == "__main__":
    if sys.argv[1] == "--english-typography":
        publish_presentation(sys.argv[2])
        raise SystemExit(0)
    stage = Path(sys.argv[1])
    expected = sys.argv[2]
    archive = base64.b64decode(b"".join(item.read_bytes() for item in sorted(stage.glob("*.part"))), validate=True)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise SystemExit("Staging checksum mismatch")
    decoded = json.loads(gzip.decompress(archive))
    install({key: base64.b64decode(value, validate=True) for key, value in decoded.items()})

