# -*- coding: utf-8 -*-
"""部署「PPT 文件缓存服务」到阿里云 ECS（云助手通道，无需 SSH）。

- 代码：`deploy/pptfiles_app.py` → `/opt/class-tools/pptfiles/app.py`
- 缓存：`/opt/class-tools/pptfiles/ppt/...`（www-data 可写，上限 5GiB 自动清最旧）
- 服务：systemd `class-tools-pptfiles.service`，127.0.0.1:8092，Python 标准库
- 路由：由 `deploy/ecs_site.py` 的 Caddy 配置提供 `/pptfiles/*` 反代（strip_prefix）

用途：OSS 香港 → 本机单连接 ~74KB/s 太慢；ECS 杭州 → OSS ~618KB/s、用户 → ECS ~4.7MB/s。
转换机上传 compat 资产后调用 `/pptfiles/__warm/...` 预热，用户下载时直接由 ECS 本地磁盘下发。

用法（web 目录，系统 python，需要 aliyunsdkcore）：
  python deploy\\ecs_pptfiles.py deploy     # 安装/更新服务 + 重启 + 本机健康检查
  python deploy\\ecs_pptfiles.py probe      # 只读：服务状态/缓存大小/磁盘/日志
  python deploy\\ecs_pptfiles.py verify --path ppt/a/<deck>/<build>/compat.pptx
                                            # 公网 HEAD/GET/Range + 预热 + 下载测速
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ecs_site  # noqa: E402

APP_LOCAL = os.path.join(HERE, "pptfiles_app.py")
SERVICE = "class-tools-pptfiles"
APP_DIR = "/opt/class-tools/pptfiles"
HEALTH_URL = "http://%s/pptfiles/__health" % ecs_site.ECS_IP

UNIT_TEXT = r"""[Unit]
Description=Class tools PPT files cache (OSS -> local disk, Caddy /pptfiles)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
Environment=PPTFILES_ROOT=/opt/class-tools/pptfiles
Environment=PPTFILES_PORT=8092
Environment=PPTFILES_MAX_BYTES=5368709120
Environment=PPTFILES_TIMEOUT=30
ExecStart=/usr/bin/python3 /opt/class-tools/pptfiles/app.py
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/class-tools/pptfiles
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"""


def _b64_file(path):
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


APP_B64_CHUNK = 9000  # 单条云助手命令建议 <16KB（base64 后），app.py 分片追加

FINAL_SCRIPT = r"""#!/bin/bash
set -e
APP_DIR="__APP_DIR__"
SERVICE="__SERVICE__"

echo "=== 1. 解码 app.py ==="
if [ ! -s /tmp/pptfiles_app.b64 ]; then echo "FATAL 分片文件为空"; exit 4; fi
base64 -d /tmp/pptfiles_app.b64 > "$APP_DIR/app.py"
python3 -m py_compile "$APP_DIR/app.py"
rm -rf "$APP_DIR/__pycache__"
chown root:root "$APP_DIR/app.py"
chmod 755 "$APP_DIR/app.py"
rm -f /tmp/pptfiles_app.b64

echo "=== 2. 缓存目录 ==="
install -d -o www-data -g www-data -m 755 "$APP_DIR/ppt"

echo "=== 3. systemd unit ==="
cat > "/etc/systemd/system/$SERVICE.service" <<'PPTFILES_UNIT_EOF'
__UNIT_TEXT__
PPTFILES_UNIT_EOF
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1 || true
systemctl restart "$SERVICE"
sleep 1

echo "=== 4. 健康检查 ==="
OK=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS -m 3 http://127.0.0.1:8092/__health >/tmp/pptfiles_health.json 2>/dev/null; then OK=1; break; fi
  sleep 1
done
if [ "$OK" != "1" ]; then
  echo "FATAL pptfiles 健康检查失败"
  journalctl -u "$SERVICE" -n 40 --no-pager || true
  exit 5
fi
echo "active=$(systemctl is-active "$SERVICE") enabled=$(systemctl is-enabled "$SERVICE" 2>/dev/null || true)"
cat /tmp/pptfiles_health.json; echo ""
echo "--- cache ---"; du -sh "$APP_DIR/ppt" 2>/dev/null || true
df -h / | tail -2
echo "done: $(date -Is)"
""".replace("__APP_DIR__", APP_DIR).replace("__SERVICE__", SERVICE) \
   .replace("__UNIT_TEXT__", UNIT_TEXT)


def install_service():
    """分片上传 app.py（>16KB），再安装 systemd unit / 缓存目录 / 健康检查。返回 0=成功。"""
    app_b64 = _b64_file(APP_LOCAL)
    chunks = [app_b64[i:i + APP_B64_CHUNK]
              for i in range(0, len(app_b64), APP_B64_CHUNK)]
    prep = ("#!/bin/bash\nset -e\nmkdir -p %s\nrm -f /tmp/pptfiles_app.b64\n"
            "echo prep-ok\n" % APP_DIR).replace("__APP_DIR__", APP_DIR)
    # 兼容 shell 字符串格式（不要受 Python % 格式影响）
    prep = "#!/bin/bash\nset -e\nmkdir -p " + APP_DIR + "\nrm -f /tmp/pptfiles_app.b64\necho prep-ok\n"
    st, rc, out = ecs_site.run_script(prep, label="pptfiles-prep", timeout=120, wait=180)
    print("[prep] status=%s exit=%s %s" % (st, rc, (out or "").strip()[:200]))
    if st != "Success":
        return 1
    for idx, chunk in enumerate(chunks, start=1):
        script = "#!/bin/bash\nset -e\necho '" + chunk + "' >> /tmp/pptfiles_app.b64\necho chunk-%d-ok\n" % idx
        st, rc, out = ecs_site.run_script(script, label="pptfiles-chunk-%d" % idx,
                                          timeout=120, wait=180)
        print("[chunk %d/%d] status=%s exit=%s %s"
              % (idx, len(chunks), st, rc, (out or "").strip()[:120]))
        if st != "Success":
            return 1
    st, rc, out = ecs_site.run_script(FINAL_SCRIPT, label="pptfiles-final",
                                      timeout=240, wait=360)
    print(out or "")
    print("[结果] status=%s exit=%s" % (st, rc))
    return 0 if (st == "Success" and rc in (0, "0", None)) else 1


PROBE_SCRIPT = r"""#!/bin/bash
set +e
echo "=== service ==="
systemctl is-active __SERVICE__ 2>/dev/null; systemctl is-enabled __SERVICE__ 2>/dev/null
echo "=== health ==="
curl -s -m 5 http://127.0.0.1:8092/__health; echo ""
echo "=== cache dir ==="
ls -la __APP_DIR__ 2>/dev/null | head -10
du -sh __APP_DIR__/ppt 2>/dev/null || echo "(cache dir 不存在)"
echo "=== cache files ==="
find __APP_DIR__/ppt -type f ! -name '*.part*' -printf '%s %p\n' 2>/dev/null | sort -nr | head -12
find __APP_DIR__/ppt -name '*.part*' -type f 2>/dev/null | head -5
echo "=== disk ==="; df -h / | tail -2
echo "=== caddy pptfiles route ==="
grep -n "pptfiles" /etc/caddy/Caddyfile /etc/caddy/Caddyfile.https.ready 2>/dev/null || echo "(no pptfiles route)"
echo "=== journal ==="
journalctl -u __SERVICE__ -n 10 --no-pager 2>/dev/null || true
echo "=== done ==="; exit 0
""".replace("__SERVICE__", SERVICE).replace("__APP_DIR__", APP_DIR)


def probe():
    st, rc, out = ecs_site.run_script(PROBE_SCRIPT, label="pptfiles-probe",
                                      timeout=120, wait=240)
    print(out)
    return 0 if st == "Success" else 1


# ---------------------------------------------------------------------------
# 本机（公网）验证：health / HEAD / GET / Range / 预热 / 下载测速
# ---------------------------------------------------------------------------
def _http(method, url, headers=None, timeout=60):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read() if method != "HEAD" else b""
            return {"status": resp.status, "headers": dict(resp.headers),
                    "bytes": len(data), "seconds": round(time.time() - started, 3),
                    "body": data}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "headers": dict(exc.headers or {}),
                "bytes": 0, "seconds": round(time.time() - started, 3), "body": b""}


def verify(path, timeout=25):
    base = "http://%s/pptfiles" % ecs_site.ECS_IP
    url = "%s/%s" % (base, path.lstrip("/"))
    fails = 0

    print("=== 1. /__health ===")
    r = _http("GET", base + "/__health", timeout=10)
    print("HTTP %s %.2fs %s" % (r["status"], r["seconds"],
                                r["body"][:400].decode("utf-8", "replace")))
    if r["status"] != 200:
        fails += 1

    print("\n=== 2. HEAD 未缓存/已缓存 ===")
    r = _http("HEAD", url, timeout=timeout)
    hd = r["headers"]
    print("HEAD HTTP %s len=%s type=%s ranges=%s cache=%s"
          % (r["status"], hd.get("Content-Length"), hd.get("Content-Type"),
             hd.get("Accept-Ranges"), hd.get("Cache-Control")))
    if r["status"] != 200:
        fails += 1

    print("\n=== 3. 预热 /__warm ===")
    warm_url = base + "/__warm/" + path.lstrip("/")
    r = _http("GET", warm_url, timeout=10)
    print("WARM HTTP %s %.2fs %s" % (r["status"], r["seconds"],
                                     r["body"][:300].decode("utf-8", "replace")))
    if r["status"] not in (200, 202):
        fails += 1
    # 轮询直到缓存落盘（HEAD 返回后立即 GET 前 1 字节测试）
    warmed = False
    for i in range(60):
        time.sleep(1.0)
        rr = _http("HEAD", url, timeout=15)
        if rr["status"] == 200 and rr["headers"].get("Content-Length"):
            # 用 Range 0-0 验证缓存已可服务
            rg = _http("GET", url, headers={"Range": "bytes=0-0"}, timeout=10)
            if rg["status"] == 206:
                warmed = True
                print("预热完成（%ds，%.2fMB）"
                      % (i + 1, int(rr["headers"]["Content-Length"]) / 1048576.0))
                break
    if not warmed:
        print("WARN 预热 60s 内未完成（首次冷启动会慢，可稍后重试 GET）")

    print("\n=== 4. GET + Range（缓存后） ===")
    rg = _http("GET", url, headers={"Range": "bytes=0-1023"}, timeout=20)
    print("Range GET HTTP %s len=%s content-range=%s"
          % (rg["status"], rg["headers"].get("Content-Length"),
             rg["headers"].get("Content-Range")))
    if rg["status"] != 206:
        fails += 1

    print("\n=== 5. 下载测速（--max-time %ss 采样，不落地） ===" % timeout)
    import subprocess
    curl = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
    if not os.path.exists(curl):
        curl = "curl"
    out = subprocess.run([curl, "-sS", "-o", "NUL", "--max-time", str(timeout),
                          "-w", "%{http_code} %{size_download} %{speed_download} %{time_total}",
                          url], capture_output=True, text=True)
    print("curl:", (out.stdout or "").strip(), ("stderr=" + out.stderr.strip()[:200])
          if out.stderr.strip() else "")
    try:
        code, size, speed, total = (out.stdout or "").split()
        print("→ HTTP %s，下载 %.2fMB / %.2fs，速度 %.2fMB/s"
              % (code, int(size) / 1048576.0, float(total), float(speed) / 1048576.0))
        if float(speed) < 1024 * 1024 and int(size) < 30 * 1024 * 1024:
            fails += 1
    except ValueError:
        fails += 1

    print("\n=== 6. GET 完整下载（若 25s 内未完成则只记部分） ===")
    part = _http("GET", url, timeout=timeout)
    print("GET HTTP %s，%.2fs，收到 %.2fMB（%.2fMB/s）"
          % (part["status"], part["seconds"], part["bytes"] / 1048576.0,
             (part["bytes"] / 1048576.0) / max(0.001, part["seconds"])))
    return 0 if fails == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="ECS PPT 文件缓存服务部署（云助手）")
    ap.add_argument("cmd", choices=["deploy", "probe", "verify"])
    ap.add_argument("--path", default="ppt/a/dmwalrdlgevz90l/c0e5834805/compat.pptx",
                    help="verify 用的缓存路径（相对 /pptfiles，仅 ppt/ 前缀）")
    ap.add_argument("--timeout", type=int, default=25, help="下载测速采样秒数")
    ns = ap.parse_args(argv)
    if ns.cmd == "deploy":
        return install_service()
    if ns.cmd == "probe":
        return probe()
    return verify(ns.path, timeout=max(5, int(ns.timeout)))


if __name__ == "__main__":
    sys.exit(main())
