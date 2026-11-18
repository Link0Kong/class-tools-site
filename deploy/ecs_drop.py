# -*- coding: utf-8 -*-
"""部署「文件传输」服务到阿里云 ECS（云助手通道，无需 SSH）。

用途（v2.1，2026-11-11）：同账号（同 sid）跨设备传输文件/文字/遥控指令的独立工具后端；
**每个文件自上传完成起 72h（3 天）自动删除（逐文件）**，会话空闲 72h 滑动回收；
单文件/单会话大小默认不限（磁盘为唯一限制）。

- 代码：`deploy/drop_app.py` → `/opt/class-tools/drop/app.py`
- 鉴权密钥：`deploy/cloudbase/publish_key.txt` → `/opt/class-tools/drop/publish_key`
  （root:www-data 0640，只用于服务端 `Authorization: Bearer`；**脚本不打印内容**）
- 数据：`/opt/class-tools/drop/{sessions,files,uploads}` + `.secret`（服务自建，0600）
- 服务：systemd `class-tools-drop.service`，127.0.0.1:8093，Python 标准库
- 路由：由 `deploy/ecs_site.py` 的 Caddy 配置提供 `/drop/*` 反代（strip_prefix）

契约：`drop/CONTRACT.md`；部署说明：`deploy/ECS_DEPLOY.md` §9。

用法（web 目录，系统 python，需要 aliyunsdkcore）：
  python deploy\\ecs_drop.py probe       # 只读：systemd / 健康 / 目录 / Caddy 路由 / journal
  python deploy\\ecs_drop.py deploy      # 分片上传 app.py + publish_key → 装 unit → 重启 → 健康检查
  python deploy\\ecs_drop.py verify      # 公网：/drop/__health（ttl/file_ttl/session_idle_ttl=259200）+ CORS + 无 token 401
  python deploy\\ecs_drop.py selftest    # 测试身份真实 E2E（登录/open/20MB 分片/下载 Range/测速/text/cmd/双 token）

安全：真机自测的 token 只保存在进程内存，**不打印、不写文件、不发消息**。
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import ecs_site  # noqa: E402

APP_LOCAL = os.path.join(HERE, "drop_app.py")
PUBLISH_KEY_LOCAL = os.path.join(HERE, "cloudbase", "publish_key.txt")
SERVICE = "class-tools-drop"
APP_DIR = "/opt/class-tools/drop"
BASE_URL = "http://%s/drop" % ecs_site.ECS_IP
HEALTH_URL = BASE_URL + "/__health"
GATEWAY = ("https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com"
           "/v1/rdb/rest/")
TEST_SID, TEST_NAME = "3260799999", "测试账号"
CHUNK_SIZE = 8388608

UNIT_TEXT = r"""[Unit]
Description=Class tools file transfer relay (same-account cross-device; Caddy /drop)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
Environment=DROP_ROOT=/opt/class-tools/drop
Environment=DROP_PORT=8093
Environment=DROP_GATEWAY=https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/
Environment=DROP_TTL_SEC=259200
Environment=DROP_MAX_FILE_BYTES=0
Environment=DROP_MAX_SESSION_BYTES=0
Environment=DROP_MAX_FILES=300
Environment=DROP_UPLOAD_TTL_SEC=86400
Environment=DROP_URL_TTL_SEC=1800
Environment=DROP_AUTH_CACHE_SEC=120
Environment=DROP_PUBLISH_KEY_FILE=/opt/class-tools/drop/publish_key
ExecStart=/usr/bin/python3 /opt/class-tools/drop/app.py
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/class-tools/drop

[Install]
WantedBy=multi-user.target
"""

APP_B64_CHUNK = 9000      # 单条云助手命令建议 <16KB（base64 后），app.py 分片追加


# ---------------------------------------------------------------------------
# 远端安装
# ---------------------------------------------------------------------------
def _b64_file(path):
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def _publish_key_b64():
    try:
        with open(PUBLISH_KEY_LOCAL, "r", encoding="utf-8") as fh:
            key = fh.read().strip()
    except OSError:
        return ""
    if not key:
        return ""
    return base64.b64encode(key.encode("utf-8")).decode("ascii")


def build_final_script():
    return r"""#!/bin/bash
set -e
APP_DIR="__APP_DIR__"
SERVICE="__SERVICE__"
TS=$(date +%Y%m%d-%H%M%S)
BK="/opt/class-tools/drop_backup/$TS"
mkdir -p "$BK" "$APP_DIR"

echo "=== 1. 解码 app.py（先 py_compile 再替换） ==="
if [ ! -s /tmp/drop_app.b64 ]; then echo "FATAL 分片文件为空"; exit 4; fi
base64 -d /tmp/drop_app.b64 > "$APP_DIR/app.py.new"
python3 -m py_compile "$APP_DIR/app.py.new"
[ -f "$APP_DIR/app.py" ] && cp -a "$APP_DIR/app.py" "$BK/app.py.old" || true
mv "$APP_DIR/app.py.new" "$APP_DIR/app.py"
chown root:root "$APP_DIR/app.py"
chmod 755 "$APP_DIR/app.py"
rm -rf "$APP_DIR/__pycache__"
rm -f /tmp/drop_app.b64

echo "=== 2. publish_key（whoami 鉴权用，不打印内容） ==="
if [ -s /tmp/drop_pubkey.b64 ]; then
  base64 -d /tmp/drop_pubkey.b64 > "$APP_DIR/publish_key"
  chown root:www-data "$APP_DIR/publish_key"
  chmod 640 "$APP_DIR/publish_key"
  echo "publish_key: set ($(stat -c%s "$APP_DIR/publish_key") bytes)"
else
  echo "WARN 未上传 publish_key（whoami 鉴权会 503 fail closed）"
fi
rm -f /tmp/drop_pubkey.b64

echo "=== 3. 数据目录 ==="
install -d -o www-data -g www-data -m 750 "$APP_DIR/sessions"
install -d -o www-data -g www-data -m 750 "$APP_DIR/files"
install -d -o www-data -g www-data -m 750 "$APP_DIR/uploads"
chown www-data:www-data "$APP_DIR"
chmod 750 "$APP_DIR"
ls -la "$APP_DIR" | head -12

echo "=== 4. systemd unit ==="
[ -f "/etc/systemd/system/$SERVICE.service" ] && cp -a "/etc/systemd/system/$SERVICE.service" "$BK/$SERVICE.service.old" || true
cat > "/etc/systemd/system/$SERVICE.service" <<'DROP_UNIT_EOF'
__UNIT_TEXT__
DROP_UNIT_EOF
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1 || true
systemctl restart "$SERVICE"
sleep 1

echo "=== 5. 本机健康检查 ==="
OK=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS -m 3 http://127.0.0.1:8093/__health >/tmp/drop_health.json 2>/dev/null; then OK=1; break; fi
  sleep 1
done
if [ "$OK" != "1" ]; then
  echo "FATAL drop 健康检查失败"
  journalctl -u "$SERVICE" -n 60 --no-pager || true
  exit 5
fi
echo "active=$(systemctl is-active "$SERVICE") enabled=$(systemctl is-enabled "$SERVICE" 2>/dev/null || true)"
cat /tmp/drop_health.json; echo ""
echo "--- data dir ---"
du -sh "$APP_DIR/sessions" "$APP_DIR/files" "$APP_DIR/uploads" 2>/dev/null || true
df -h / | tail -2
echo "done: $(date -Is)"
""".replace("__APP_DIR__", APP_DIR).replace("__SERVICE__", SERVICE) \
   .replace("__UNIT_TEXT__", UNIT_TEXT)


def install_service():
    """分片上传 app.py + publish_key，安装 unit 并重启。返回 0=成功。"""
    app_b64 = _b64_file(APP_LOCAL)
    chunks = [app_b64[i:i + APP_B64_CHUNK]
              for i in range(0, len(app_b64), APP_B64_CHUNK)]
    key_b64 = _publish_key_b64()
    prep = ("#!/bin/bash\nset -e\nmkdir -p " + APP_DIR + "\n"
            "rm -f /tmp/drop_app.b64 /tmp/drop_pubkey.b64\n"
            "echo prep-ok\n")
    st, rc, out = ecs_site.run_script(prep, label="drop-prep", timeout=120, wait=180)
    print("[prep] status=%s exit=%s %s" % (st, rc, (out or "").strip()[:200]))
    if st != "Success":
        return 1
    for idx, chunk in enumerate(chunks, start=1):
        script = ("#!/bin/bash\nset -e\necho '" + chunk +
                  "' >> /tmp/drop_app.b64\necho chunk-%d-ok\n" % idx)
        st, rc, out = ecs_site.run_script(script, label="drop-chunk-%d" % idx,
                                          timeout=120, wait=180)
        print("[chunk %d/%d] status=%s exit=%s %s"
              % (idx, len(chunks), st, rc, (out or "").strip()[:120]))
        if st != "Success":
            return 1
    if key_b64:
        script = ("#!/bin/bash\nset -e\necho '" + key_b64 +
                  "' > /tmp/drop_pubkey.b64\necho pubkey-ok\n")
        st, rc, out = ecs_site.run_script(script, label="drop-pubkey",
                                          timeout=120, wait=180)
        print("[publish_key] status=%s exit=%s %s"
              % (st, rc, (out or "").strip()[:120]))
        if st != "Success":
            return 1
    else:
        print("[publish_key] WARN 本地缺少 deploy/cloudbase/publish_key.txt，跳过")
    st, rc, out = ecs_site.run_script(build_final_script(), label="drop-final",
                                      timeout=240, wait=360)
    print(out or "")
    print("[结果] status=%s exit=%s" % (st, rc))
    return 0 if (st == "Success" and rc in (0, "0", None)) else 1


PROBE_SCRIPT = r"""#!/bin/bash
set +e
echo "=== service ==="
systemctl is-active __SERVICE__ 2>/dev/null; systemctl is-enabled __SERVICE__ 2>/dev/null
systemctl status __SERVICE__ --no-pager -n 3 2>/dev/null | head -8
echo "=== health (local) ==="
curl -s -m 5 http://127.0.0.1:8093/__health; echo ""
echo "=== app dir ==="
ls -la __APP_DIR__ 2>/dev/null | head -14
du -sh __APP_DIR__/sessions __APP_DIR__/files __APP_DIR__/uploads 2>/dev/null
echo "=== sessions/files ==="
find __APP_DIR__/sessions -maxdepth 1 -type f -name '*.json' 2>/dev/null | head -8
find __APP_DIR__/files -maxdepth 2 -type f 2>/dev/null | head -8
echo "=== disk ==="; df -h / | tail -2
echo "=== caddy drop route ==="
grep -n "drop" /etc/caddy/Caddyfile /etc/caddy/Caddyfile.https.ready 2>/dev/null || echo "(no drop route)"
echo "=== journal ==="
journalctl -u __SERVICE__ -n 12 --no-pager 2>/dev/null || true
echo "=== done ==="; exit 0
""".replace("__SERVICE__", SERVICE).replace("__APP_DIR__", APP_DIR)


def probe():
    st, rc, out = ecs_site.run_script(PROBE_SCRIPT, label="drop-probe",
                                      timeout=120, wait=240)
    print(out)
    return 0 if st == "Success" else 1


# ---------------------------------------------------------------------------
# 一次性诊断（只读）：为什么「文件传输」看不到文件
#   - 当前 drop 版本 / 运行单元的会话 TTL（若 TTL_SEC 被调小，空闲会话会被提前回收，文件随之消失）；
#   - 每个会话的 lastActivity / seq / 事件类型计数 / 文件数（只打印 sid 哈希前缀，不打印 token/name）；
#   - journal 里的 session open / idle cleanup / file ttl cleanup 记录。
# ---------------------------------------------------------------------------
DIAG_SCRIPT = r"""#!/bin/bash
set +e
echo "=== service ==="
systemctl is-active __SERVICE__
echo "active_since: $(systemctl show __SERVICE__ -p ActiveEnterTimestamp --value 2>/dev/null)"
grep -E "^Environment=DROP_" /etc/systemd/system/__SERVICE__.service 2>/dev/null
echo "=== health (local) ==="
curl -s -m 5 http://127.0.0.1:8093/__health; echo ""
echo "=== sessions ==="
ls -1 __APP_DIR__/sessions 2>/dev/null
echo "--- index ---"
cat __APP_DIR__/sessions/index.json 2>/dev/null; echo ""
python3 - <<'PY'
import glob, json, os
from collections import Counter
root = "__APP_DIR__/sessions"
for p in sorted(glob.glob(os.path.join(root, "*.json"))):
    if os.path.basename(p) == "index.json":
        continue
    try:
        s = json.load(open(p))
    except Exception as e:
        print(os.path.basename(p), "UNREADABLE", e); continue
    evs = s.get("events") or []
    files = s.get("files") or []
    print("session", os.path.basename(p)[:8],
          "created", s.get("createdAt"), "lastAct", s.get("lastActivityAt"),
          "seq", s.get("seq"), "events", len(evs), dict(Counter([e.get("kind") for e in evs])),
          "files", len(files),
          "file_names", [str(f.get("name"))[:20] for f in files][:6])
PY
echo "=== files dir ==="
find __APP_DIR__/files -type f 2>/dev/null | head -20
echo "=== journal: start/open/cleanup ==="
journalctl -u __SERVICE__ --no-pager 2>/dev/null | grep -E "start v|session open|session close|idle cleanup|ttl cleanup|session cleanup" | tail -40
echo "=== done ==="; exit 0
""".replace("__SERVICE__", SERVICE).replace("__APP_DIR__", APP_DIR)


def diag():
    st, rc, out = ecs_site.run_script(DIAG_SCRIPT, label="drop-diag",
                                      timeout=120, wait=240)
    print(out)
    return 0 if st == "Success" else 1


# ---------------------------------------------------------------------------
# 本机（公网）HTTP 工具
# ---------------------------------------------------------------------------
def _http(method, url, headers=None, body=None, timeout=60):
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=headers or {})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return {"status": resp.status,
                    "headers": {k.lower(): v for k, v in resp.headers.items()},
                    "body": data, "seconds": round(time.time() - started, 3)}
    except urllib.error.HTTPError as exc:
        data = b""
        try:
            data = exc.read()
        except Exception:  # noqa: BLE001
            pass
        return {"status": exc.code,
                "headers": {k.lower(): v for k, v in (exc.headers or {}).items()},
                "body": data, "seconds": round(time.time() - started, 3)}


def _json_of(result):
    try:
        return json.loads(result["body"].decode("utf-8", "replace"))
    except (UnicodeDecodeError, ValueError):
        return {}


def _post_json(path, payload, token=None, timeout=60):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Device-Id"] = token
    return _http("POST", BASE_URL + path, headers=headers,
                 body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                 timeout=timeout)


def verify():
    print("=== 公网 /drop 校验（%s） ===" % BASE_URL)
    fails = 0
    r = _http("GET", HEALTH_URL, timeout=15)
    payload = _json_of(r)
    print("1) /__health HTTP %s %.2fs %s" % (r["status"], r["seconds"],
                                              json.dumps(payload, ensure_ascii=False)))
    if r["status"] != 200 or payload.get("ok") is not True:
        fails += 1
    if not {"version", "sessions", "files", "bytes", "ttl",
            "max_file_bytes", "max_session_bytes"} <= set(payload.keys()):
        print("   缺少 v2 健康字段")
        fails += 1
    ttl_ok = (payload.get("ttl") == 259200
              and payload.get("file_ttl") == 259200
              and payload.get("session_idle_ttl") == 259200)
    print("1b) health ttl=%s file_ttl=%s session_idle_ttl=%s（期望均 259200 = 72h = 3 天）-> %s"
          % (payload.get("ttl"), payload.get("file_ttl"),
             payload.get("session_idle_ttl"), "OK" if ttl_ok else "FAIL"))
    if not ttl_ok:
        fails += 1
    unlimited = (payload.get("max_file_bytes") == 0
                 and payload.get("max_session_bytes") == 0)
    print("1c) 大小上限 max_file_bytes=%s max_session_bytes=%s（0=不限）-> %s"
          % (payload.get("max_file_bytes"), payload.get("max_session_bytes"),
             "OK" if unlimited else "FAIL"))
    if not unlimited:
        fails += 1

    origin = "http://121.196.47.2"
    r = _http("OPTIONS", BASE_URL + "/upload/init", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-device-id"}, timeout=15)
    hd = r["headers"]
    cors_ok = (r["status"] in (200, 204)
               and hd.get("access-control-allow-origin") in (origin, "*")
               and "x-device-id" in (hd.get("access-control-allow-headers") or "").lower()
               and "content-range" in (hd.get("access-control-expose-headers") or "").lower())
    print("2) OPTIONS 预检 HTTP %s ACAO=%s ACAH=%s -> %s"
          % (r["status"], hd.get("access-control-allow-origin"),
             hd.get("access-control-allow-headers"), "OK" if cors_ok else "FAIL"))
    if not cors_ok:
        fails += 1

    r = _post_json("/open", {}, token=None, timeout=20)
    payload = _json_of(r)
    if r["status"] == 401 and payload.get("ok") is False:
        print("3) 无 token /open -> 401 %s（fail closed OK）" % payload.get("reason"))
    elif r["status"] == 503:
        print("3) 无 token /open -> 503 %s（鉴权网关/函数暂不可用）"
              % payload.get("reason"))
        fails += 1
    else:
        print("3) 无 token /open -> HTTP %s（预期 401）" % r["status"])
        fails += 1

    r = _post_json("/open", {}, token="drop_selftest_invalid_token", timeout=20)
    payload = _json_of(r)
    if r["status"] == 401 and payload.get("ok") is False:
        print("4) 无效 token /open -> 401 %s" % payload.get("reason"))
    elif r["status"] == 503:
        print("4) 无效 token /open -> 503 %s（网关暂不可用）" % payload.get("reason"))
        fails += 1
    else:
        print("4) 无效 token /open -> HTTP %s（预期 401）" % r["status"])
        fails += 1
    print("\n%s" % ("VERIFY PASS" if fails == 0 else "VERIFY FAIL（%d 项）" % fails))
    return 0 if fails == 0 else 1


# ---------------------------------------------------------------------------
# 真实公网 E2E（测试身份；token 仅内存，不打印/不落盘）
# ---------------------------------------------------------------------------
def _publish_key():
    try:
        with open(PUBLISH_KEY_LOCAL, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def gateway_rpc(name, payload, token=None, timeout=40):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = _publish_key()
    if key:
        headers["Authorization"] = "Bearer " + key
    if token:
        headers["X-Device-Id"] = token
    req = urllib.request.Request(GATEWAY + "rpc/" + name,
                                 data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except Exception:  # noqa: BLE001
        return 0, {}


def login_test_identity():
    status, payload = gateway_rpc("class_verify",
                                  {"p_sid": TEST_SID, "p_name": TEST_NAME})
    token = str(payload.get("token") or "")
    sid = str(payload.get("sid") or "")
    if status != 200 or not token or not sid:
        raise SystemExit("测试身份登录失败（status=%s，网关/名单需可用）" % status)
    if sid != TEST_SID:
        raise SystemExit("测试身份登录返回的 sid 与预期不符")
    return token, sid


def upload_chunks(token, session_id, name, blob, mime):
    """按契约 8MiB 分片上传；返回 finish 的 file 对象。"""
    chunks = [blob[i:i + CHUNK_SIZE] for i in range(0, len(blob), CHUNK_SIZE)]
    if not chunks:
        chunks = [b""]
    r = _post_json("/upload/init", {"sessionId": session_id, "name": name,
                                    "size": len(blob), "mime": mime,
                                    "totalChunks": len(chunks)}, token=token)
    payload = _json_of(r)
    if r["status"] != 200 or not payload.get("uploadId"):
        raise RuntimeError("upload/init 失败 HTTP %s %s" % (r["status"], r["body"][:200]))
    upload_id = payload["uploadId"]
    chunk_size = int(payload.get("chunkSize") or 0)
    for index, chunk in enumerate(chunks):
        rr = _http("POST", "%s/upload/chunk?uploadId=%s&index=%d"
                   % (BASE_URL, upload_id, index),
                   headers={"X-Device-Id": token}, body=chunk, timeout=300)
        if rr["status"] != 200:
            raise RuntimeError("upload/chunk[%d] 失败 HTTP %s %s"
                               % (index, rr["status"], rr["body"][:200]))
    r = _post_json("/upload/finish", {"sessionId": session_id,
                                      "uploadId": upload_id}, token=token)
    payload = _json_of(r)
    if r["status"] != 200 or not payload.get("file"):
        raise RuntimeError("upload/finish 失败 HTTP %s %s" % (r["status"], r["body"][:300]))
    return payload["file"], chunk_size


class Report(object):
    def __init__(self):
        self.items = []

    def check(self, name, ok, note=""):
        self.items.append(bool(ok))
        print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))
        return bool(ok)

    def summary(self):
        total = len(self.items)
        passed = sum(1 for item in self.items if item)
        print("\n%s（%d/%d）" % ("SELFTEST PASS" if passed == total
                                 else "SELFTEST FAIL", passed, total))
        return 0 if passed == total else 1


def _download(url, headers=None, timeout=180):
    return _http("GET", url, headers=headers or {}, timeout=timeout)


def selftest():
    report = Report()
    session_id = ""
    token = ""
    boundary_upload_id = ""
    try:
        print("=== 0. 登录测试身份（token 不打印） ===")
        token, sid = login_test_identity()
        token2, sid2 = login_test_identity()
        report.check("测试身份两次登录成功、同 sid、token 不同",
                     bool(token and token2 and sid == sid2)
                     and token != token2, "sid 一致/双 token")

        r = _http("GET", HEALTH_URL, timeout=15)
        health = _json_of(r)
        baseline = health
        report.check("公网 /drop/__health 200 且 ok",
                     r["status"] == 200 and health.get("ok") is True,
                     "v=%s sessions=%s files=%s bytes=%s"
                     % (health.get("version"), health.get("sessions"),
                        health.get("files"), health.get("bytes")))
        report.check("health v2.5：file_ttl=session_idle_ttl=259200 / max_file_bytes=0 / max_session_bytes=0",
                     health.get("ttl") == 259200
                     and health.get("file_ttl") == 259200
                     and health.get("session_idle_ttl") == 259200
                     and health.get("max_file_bytes") == 0
                     and health.get("max_session_bytes") == 0
                     and health.get("version") == "2.5",
                     "version=%s file_ttl=%s session_idle_ttl=%s "
                     "max_file=%s max_session=%s"
                     % (health.get("version"), health.get("file_ttl"),
                        health.get("session_idle_ttl"),
                        health.get("max_file_bytes"),
                        health.get("max_session_bytes")))

        print("\n=== 1. 会话 /open /mine（双 token 同 sid 互见） ===")
        r = _post_json("/open", {}, token=token)
        payload = _json_of(r)
        ok = r["status"] == 200 and payload.get("ok") is True
        session = payload.get("session") or {}
        session_id = str(session.get("id") or "")
        report.check("token1 /open 成功", ok,
                     "code=%s expiresIn=%ss" % (
                         session.get("code"),
                         int((session.get("expiresAt") or 0) / 1000 - time.time())))
        r = _post_json("/open", {}, token=token2)
        payload2 = _json_of(r)
        same = (payload2.get("session") or {}).get("id") == session_id
        report.check("token2（同 sid）复用同一会话（双端互见）", same)
        r = _http("GET", BASE_URL + "/mine", headers={"X-Device-Id": token}, timeout=20)
        report.check("token1 /mine 返回同一会话",
                     (_json_of(r).get("session") or {}).get("id") == session_id)

        print("\n=== 1b. v2.1：文件/会话空闲 TTL 3 天 / 无大小上限（元数据边界，不实际传 2GiB） ===")
        ttl_ms = int(session.get("expiresAt") or 0) - int(session.get("createdAt") or 0)
        report.check("会话创建时 expiresAt = 创建时刻 + 259200s（72h 空闲滑动基准）",
                     ttl_ms == 259200 * 1000, "%ss" % (ttl_ms // 1000))
        old_limit = 2 * 1024 ** 3                 # v1 单文件上限 2GiB
        declared = old_limit + 8 * 1024 ** 2      # 旧上限 + 8MiB
        declared_chunks = (declared + CHUNK_SIZE - 1) // CHUNK_SIZE
        r = _post_json("/upload/init", {
            "sessionId": session_id, "name": "自测-超大声明.iso",
            "size": declared, "mime": "application/octet-stream",
            "totalChunks": declared_chunks}, token=token)
        payload = _json_of(r)
        boundary_upload_id = str(payload.get("uploadId") or "")
        report.check("声明 > 旧单文件上限 2GiB 的文件 init 成功（不再 413）",
                     r["status"] == 200 and payload.get("ok") is True
                     and bool(boundary_upload_id),
                     "size=%d (>2GiB) chunks=%d" % (declared, declared_chunks))

        print("\n=== 1c. v2.3：大屏在线状态（/presence） ===")
        r = _http("GET", "%s/presence" % BASE_URL, headers={"X-Device-Id": token}, timeout=20)
        p0 = _json_of(r)
        report.check("初始 /presence stage=false", r["status"] == 200 and p0.get("stage") is False,
                     "stage=%s" % p0.get("stage"))
        r = _post_json("/presence", {"stage": True}, token=token)
        report.check("POST /presence stage=true", r["status"] == 200 and _json_of(r).get("stage") is True,
                     _json_of(r).get("stage"))
        r = _http("GET", "%s/presence" % BASE_URL, headers={"X-Device-Id": token2}, timeout=20)
        report.check("同 sid 第二 token 看到大屏在线", _json_of(r).get("stage") is True,
                     "stage=%s" % _json_of(r).get("stage"))
        r = _http("GET", "%s/presence" % BASE_URL, headers={"X-Device-Id": "drop_selftest_invalid_token"}, timeout=20)
        report.check("无效 token /presence -> 401", r["status"] == 401, "HTTP %s" % r["status"])
        r = _post_json("/presence", {"stage": False}, token=token)
        report.check("POST /presence stage=false 立即下线", _json_of(r).get("stage") is False)
        r = _http("GET", "%s/presence" % BASE_URL, headers={"X-Device-Id": token}, timeout=20)
        report.check("下线后 /presence stage=false", _json_of(r).get("stage") is False,
                     "stage=%s" % _json_of(r).get("stage"))

        print("\n=== 2. 小文件分片上传 + 事件 + 下载 ===")
        small = ("drop-selftest-%d\n" % int(time.time())).encode() + b"x" * 4096
        file1, chunk_size = upload_chunks(token, session_id, "自测-小文件.txt",
                                          small, "text/plain")
        report.check("小文件 finish 返回契约字段",
                     bool(file1.get("downloadUrl"))
                     and set(file1.keys()) == {"id", "name", "size", "mime",
                                               "downloadUrl"},
                     "size=%s chunkSize=%s" % (file1.get("size"), chunk_size))
        r = _download(file1["downloadUrl"])
        report.check("小文件下载内容一致（sha256）",
                     r["status"] == 200
                     and hashlib.sha256(r["body"]).hexdigest()
                     == hashlib.sha256(small).hexdigest())
        hd = r["headers"]
        report.check("下载头 attachment + filename*",
                     "attachment" in hd.get("content-disposition", "")
                     and "filename*=UTF-8''" in hd.get("content-disposition", ""),
                     hd.get("content-disposition", "")[:80])

        print("\n=== 3. 20MiB 大文件（3 片）+ 下载/测速/Range/HEAD ===")
        big = bytes(range(256)) * 81920          # 20 MiB
        started = time.time()
        file2, _cs = upload_chunks(token, session_id, "自测-大文件.bin", big,
                                   "application/octet-stream")
        up_seconds = time.time() - started
        report.check("20MiB 分片上传完成（3 片）",
                     file2.get("size") == len(big),
                     "%.2fs（%.2fMB/s）" % (up_seconds, len(big) / 1048576.0 / max(0.001, up_seconds)))
        started = time.time()
        r = _download(file2["downloadUrl"], timeout=300)
        down_seconds = time.time() - started
        speed = len(r["body"]) / 1048576.0 / max(0.001, down_seconds)
        report.check("20MiB 下载 sha256 一致",
                     r["status"] == 200
                     and hashlib.sha256(r["body"]).hexdigest()
                     == hashlib.sha256(big).hexdigest(),
                     "%.2fs（%.2fMB/s）" % (down_seconds, speed))
        report.check("下载速度 ≥ 1MiB/s（ECS 直连预期 2MB/s+）", speed >= 1.0,
                     "%.2fMB/s" % speed)
        r = _download(file2["downloadUrl"], headers={"Range": "bytes=100-1123"})
        report.check("Range 206 且内容一致",
                     r["status"] == 206 and r["body"] == big[100:1124]
                     and r["headers"].get("content-range")
                     == "bytes 100-1123/%d" % len(big),
                     r["headers"].get("content-range"))
        r = _http("HEAD", file2["downloadUrl"], timeout=60)
        report.check("HEAD 200 且 Content-Length 正确",
                     r["status"] == 200
                     and r["headers"].get("content-length") == str(len(big)))

        print("\n=== 3b. 临时云空间：单文件删除（DELETE /file/<fileId>） ===")
        r = _http("DELETE", "%s/file/%s?sessionId=%s" % (BASE_URL, file1["id"], session_id),
                  headers={"X-Device-Id": token}, timeout=30)
        payload = _json_of(r)
        report.check("DELETE /file/<id> 成功（deleted=true）",
                     r["status"] == 200 and payload.get("ok") is True
                     and payload.get("deleted") is True,
                     "HTTP %s deleted=%s" % (r["status"], payload.get("deleted")))
        r = _http("GET", "%s/state?sessionId=%s&since=0" % (BASE_URL, session_id),
                  headers={"X-Device-Id": token}, timeout=20)
        events = _json_of(r).get("events") or []
        kinds = [ev.get("kind") for ev in events]
        file1_ev = [ev for ev in events
                    if ev.get("kind") == "file"
                    and ev.get("payload", {}).get("fileId") == file1["id"]]
        report.check("删除后 /state：原 file 事件 expired 无链接 + 新增 filedel 事件",
                     "filedel" in kinds and bool(file1_ev)
                     and file1_ev[0]["payload"].get("expired") is True
                     and not file1_ev[0]["payload"].get("downloadUrl"),
                     "kinds=%s" % kinds)
        r = _download(file1["downloadUrl"], timeout=30)
        report.check("删除后旧下载链接失效（403/404）", r["status"] in (403, 404),
                     "HTTP %s" % r["status"])
        r = _http("DELETE", "%s/file/%s?sessionId=%s" % (BASE_URL, file1["id"], session_id),
                  headers={"X-Device-Id": token}, timeout=30)
        report.check("重复删除幂等（deleted=false）",
                     r["status"] == 200 and _json_of(r).get("deleted") is False)

        print("\n=== 4. 事件 / 文字 / 指令（跨端互见） ===")
        r = _http("GET", "%s/state?sessionId=%s&since=0" % (BASE_URL, session_id),
                  headers={"X-Device-Id": token2}, timeout=20)
        events = _json_of(r).get("events") or []
        kinds = [ev.get("kind") for ev in events]
        report.check("token2 /state 可见双端文件事件（file x2）",
                     kinds.count("file") == 2,
                     "kinds=%s cursor=%s" % (kinds, _json_of(r).get("cursor")))
        # 删除过的 file 事件会被标记 expired 且无 downloadUrl，只挑仍可用的链接
        event_urls = [ev.get("payload", {}).get("downloadUrl")
                      for ev in events if ev.get("kind") == "file"
                      and ev.get("payload", {}).get("downloadUrl")]
        rr = _download(event_urls[0], timeout=60) if event_urls else {"status": 0}
        report.check("/state 文件事件带可用下载链接（读取时重签）",
                     bool(event_urls) and rr["status"] == 200,
                     "HTTP %s" % rr["status"])
        # v2.5：all=1 的文件清单与事件无关（事件为空也返回有效文件），且每个都带可用下载链接
        r = _http("GET", "%s/state?sessionId=%s&all=1&since=999999" % (BASE_URL, session_id),
                  headers={"X-Device-Id": token2}, timeout=20)
        payload_all = _json_of(r)
        files_all = payload_all.get("files") or []
        names_all = sorted(str(f.get("name")) for f in files_all)
        r2 = _download(files_all[0]["downloadUrl"], timeout=60) if files_all else {"status": 0}
        report.check("v2.5 /state?all=1 在事件为空时仍返回有效文件清单（可用下载链接）",
                     not (payload_all.get("events") or [])
                     and len(files_all) == 1 and bool(r2["status"] == 200),
                     "files=%s HTTP %s" % (names_all, r2["status"]))
        r = _post_json("/text", {"sessionId": session_id,
                                 "text": "大屏你好（自测）"}, token=token2)
        seq_text = _json_of(r).get("seq") or 0
        report.check("token2 /text 发送成功", r["status"] == 200 and seq_text > 0,
                     "seq=%s" % seq_text)
        r = _http("GET", "%s/state?sessionId=%s&since=%d"
                  % (BASE_URL, session_id, int(seq_text) - 1),
                  headers={"X-Device-Id": token}, timeout=20)
        got = [ev for ev in (_json_of(r).get("events") or [])
               if ev.get("kind") == "text"]
        report.check("token1 /state 收到 token2 的文字（跨端互见）",
                     bool(got) and got[0]["payload"].get("text") == "大屏你好（自测）"
                     and got[0]["from"].get("name") == TEST_NAME,
                     "from=%s" % (got[0]["from"].get("name") if got else "?"))
        r = _post_json("/cmd", {"sessionId": session_id, "op": "toast",
                                "args": {"text": "自测提示"}}, token=token2)
        report.check("合法遥控指令 toast 成功", r["status"] == 200)
        r = _post_json("/cmd", {"sessionId": session_id, "op": "rm_rf",
                                "args": {}}, token=token2)
        payload = _json_of(r)
        report.check("未知遥控指令 400 中文 reason",
                     r["status"] == 400 and payload.get("ok") is False
                     and "指令" in (payload.get("reason") or ""),
                     payload.get("reason"))

        print("\n=== 5. 鉴权 / 隔离 / 关闭清理 ===")
        r = _http("GET", "%s/state?sessionId=%s" % (BASE_URL, session_id),
                  headers={"X-Device-Id": "drop_selftest_invalid_token"}, timeout=20)
        report.check("无效 token 访问 /state -> 401",
                     r["status"] == 401, _json_of(r).get("reason"))
        r = _post_json("/close", {"sessionId": session_id}, token=token)
        report.check("token1 /close 成功", r["status"] == 200)
        session_id = ""
        r = _http("GET", BASE_URL + "/mine", headers={"X-Device-Id": token2}, timeout=20)
        report.check("关闭后 /mine 为空", _json_of(r).get("session") is None)
        r = _download(file1["downloadUrl"])
        report.check("关闭后旧下载链接 404（文件已删除）", r["status"] == 404,
                     "HTTP %s" % r["status"])
        if boundary_upload_id:
            # 关闭会话时未完成分片任务也一并删除（v2 清理语义）
            r = _http("POST", "%s/upload/chunk?uploadId=%s&index=0"
                      % (BASE_URL, boundary_upload_id),
                      headers={"X-Device-Id": token}, body=b"x", timeout=20)
            report.check("关闭会话后未完成分片任务一并删除（chunk -> 404）",
                         r["status"] == 404, "HTTP %s" % r["status"])
        r = _http("GET", HEALTH_URL, timeout=15)
        health = _json_of(r)
        # sessions 不是「残留」判据：全服务只有 2 个真实账号会话，窗口里用户正常打开云空间/大屏
        # 都会让它 +1（与自测无关）；真正的判据是自测会话已关闭、文件数为 0。
        report.check("健康统计无残留文件（自测文件已全部删除）",
                     health.get("files") == 0 and health.get("bytes") == 0,
                     "sessions=%s files=%s bytes=%s（基线 %s/%s/%s）"
                     % (health.get("sessions"), health.get("files"), health.get("bytes"),
                        baseline.get("sessions"), baseline.get("files"),
                        baseline.get("bytes")))
    finally:
        if session_id and token:
            try:
                _post_json("/close", {"sessionId": session_id}, token=token)
            except Exception:  # noqa: BLE001
                pass
    return report.summary()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="ECS 大屏临时互联服务部署（云助手）")
    ap.add_argument("cmd", choices=["deploy", "probe", "verify", "selftest", "diag"])
    ns = ap.parse_args(argv)
    if ns.cmd == "deploy":
        rc = install_service()
        if rc != 0:
            return rc
        print("\n[deploy] 服务已安装并本机健康检查通过；"
              "若尚未加 Caddy 路由请执行： python deploy\\ecs_site.py apply")
        return 0
    if ns.cmd == "probe":
        return probe()
    if ns.cmd == "verify":
        return verify()
    if ns.cmd == "diag":
        return diag()
    return selftest()


if __name__ == "__main__":
    sys.exit(main())
