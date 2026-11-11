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
  python deploy\\ecs_pptfiles.py force-selftest  # 强制刷新自测（同 key 换内容）\n  python deploy\\ecs_pptfiles.py verify --path ppt/a/<deck>/<build>/compat.pptx
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


def force_selftest():
    """真实缓存一致性自测：同 key 换内容 → force=1 预热后 GET 必须拿到新内容。

    步骤：上传 A 到 OSS 测试 key → 预热 → GET=A；同 key 覆盖为 B → 普通 GET 仍为 A（旧缓存）；
    ``?force=1`` 预热 → GET=B。最后删除 OSS 测试对象与 ECS 缓存文件（不污染业务数据）。
    """
    import hashlib
    import oss_object
    bucket = oss_object.bucket()
    base = "http://%s/pptfiles" % ecs_site.ECS_IP
    key = "ppt/_selftest/force_refresh_%d.bin" % int(time.time())
    url = base + "/" + key
    data_a = (b"CACHE-A-" + b"A" * 300) * 600          # ~190KB
    data_b = (b"CACHE-B-" + b"B" * 400) * 700          # ~290KB（同时改变长度）
    sha_a = hashlib.sha256(data_a).hexdigest()
    sha_b = hashlib.sha256(data_b).hexdigest()
    fails = 0

    def get_sha(_url):
        r = _http("GET", _url, timeout=20)
        return r["status"], hashlib.sha256(r["body"]).hexdigest() if r["status"] == 200 else ""

    def wait_sha(expect, label):
        for i in range(60):
            st, got = get_sha(url)
            if st == 200 and got == expect:
                print("%s：GET sha=%s（%ds）" % (label, got[:16], i + 1))
                return True
            time.sleep(1)
        print("%s：超时未拿到期望内容（最后一次 %s sha=%s）" % (label, st, got[:16]))
        return False

    try:
        print("=== 1. 上传测试对象 A（%d bytes） ===" % len(data_a))
        bucket.put_object(key, data_a, headers={"Cache-Control": "no-cache"})
        print("PUT %s sha=%s" % (key, sha_a[:16]))

        print("\n=== 2. force 预热（首次） ===")
        r = _http("GET", base + "/__warm/" + key + "?force=1", timeout=10)
        print("WARM HTTP %s %s" % (r["status"],
                                   r["body"][:200].decode("utf-8", "replace")))
        if r["status"] not in (200, 202):
            fails += 1
        if not wait_sha(sha_a, "A 缓存"):
            fails += 1

        print("\n=== 3. 同 key 覆盖为 B（新内容） ===")
        bucket.put_object(key, data_b, headers={"Cache-Control": "no-cache"})
        print("PUT %s sha=%s" % (key, sha_b[:16]))
        st, got = get_sha(url)
        print("普通 GET（未 force）：HTTP %s sha=%s → %s"
              % (st, got[:16], "仍是旧缓存（符合预期，暴露问题）"
                 if got == sha_a else "已变（意外）"))
        if got != sha_a:
            print("WARN 覆盖后普通 GET 已是新内容（可能缓存未命中/服务已刷新）")

        print("\n=== 4. force=1 预热刷新 ===")
        r = _http("GET", base + "/__warm/" + key + "?force=1", timeout=10)
        print("WARM HTTP %s %s" % (r["status"],
                                   r["body"][:260].decode("utf-8", "replace")))
        if r["status"] not in (200, 202):
            fails += 1
        if not wait_sha(sha_b, "B 缓存（force 后）"):
            fails += 1

        print("\n=== 5. 再次 force（内容未再变）应返回 unchanged/200 ===")
        r = _http("GET", base + "/__warm/" + key + "?force=1", timeout=10)
        print("WARM HTTP %s %s" % (r["status"],
                                   r["body"][:220].decode("utf-8", "replace")))
    finally:
        try:
            bucket.delete_object(key)
            print("已删除 OSS 测试对象 %s" % key)
        except Exception as exc:  # noqa: BLE001
            print("WARN 删除 OSS 测试对象失败：%s" % exc.__class__.__name__)
        remote = "rm -f /opt/class-tools/pptfiles/%s /opt/class-tools/pptfiles/%s.meta" % (key, key)
        try:
            ecs_site.run_script("#!/bin/bash\n%s\necho cache-cleaned\n" % remote,
                                label="pptfiles-force-cleanup", timeout=120, wait=180)
        except Exception:  # noqa: BLE001
            pass
    print("\n%s" % ("FORCE_SELFTEST PASS" if fails == 0
                     else "FORCE_SELFTEST FAIL（%d 项）" % fails))
    return 0 if fails == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="ECS PPT 文件缓存服务部署（云助手）")
    ap.add_argument("cmd", choices=["deploy", "probe", "verify", "force-selftest"])
    ap.add_argument("--path", default="ppt/a/dmwalrdlgevz90l/c0e5834805/compat.pptx",
                    help="verify 用的缓存路径（相对 /pptfiles，仅 ppt/ 前缀）")
    ap.add_argument("--timeout", type=int, default=25, help="下载测速采样秒数")
    ns = ap.parse_args(argv)
    if ns.cmd == "deploy":
        return install_service()
    if ns.cmd == "probe":
        return probe()
    if ns.cmd == "force-selftest":
        return force_selftest()
    return verify(ns.path, timeout=max(5, int(ns.timeout)))


if __name__ == "__main__":
    sys.exit(main())
