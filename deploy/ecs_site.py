# -*- coding: utf-8 -*-
"""ECS 班级工具站部署（阿里云云助手 RunCommand，不需要 SSH / 22 端口）。

用途（2026-11-10 迁移第 1 步）：
  把 OSS 上的最新静态站（index.html / tt.json / assets / 图标）同步到阿里云 ECS
  的 /var/www/tool，并把 Caddy 切成「gzip/zstd + 缓存头」配置；同时生成一份
  已就绪的 HTTPS 配置（域名备案通过、DNS 恢复后再启用）。

为什么用云助手：
  ECS 安全组 22 只放行家庭固定 IP（目前连不上），云助手（Cloud Assistant）
  Agent 在线，可通过阿里云 OpenAPI 执行 shell，无需密钥登录。

凭据：
  复用 `deploy/sync_tools.py::load_creds()`（环境变量或 deploy/creds.env 的
  ALIYUN_AK_ID / ALIYUN_AK_SECRET）。本脚本**不打印任何凭据**。

用法（在 web 目录下，用带 aliyunsdkcore 的 Python，例如系统 python）：
  python deploy\\ecs_site.py probe            # 只读：查看 ECS 现状
  python deploy\\ecs_site.py apply            # 部署最新静态站 + HTTP Caddy 配置（gzip/缓存）
  python deploy\\ecs_site.py apply --https    # 同上，但直接启用 tool.furina.fun 的 HTTPS 站点块
  python deploy\\ecs_site.py apply --dry-run  # 只打印将要执行的远端脚本
  python deploy\\ecs_site.py verify           # 从本机校验 ECS 上的字节与 gzip/接口状态（含 /pptfiles/__health）

安全：
  - 所有远端脚本都以 base64 传给云助手，执行内容固定、不含密钥；
  - 部署前自动备份旧 Caddyfile 与旧 index.html；
  - 新 Caddyfile 先 `caddy validate` 通过才替换并 reload。
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

IID = "i-bp1ibr9hs7ewepmm1ugw"
REGION = "cn-hangzhou"
ECS_IP = "121.196.47.2"
OSS_BASE = "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com"
SITE = "https://tool.furina.fun"
LE_EMAIL = "3299207275@qq.com"

# ---------------------------------------------------------------- 阿里云调用


def _client():
    from aliyunsdkcore.client import AcsClient
    import sync_tools
    ak, sk = sync_tools.load_creds()
    return AcsClient(ak, sk, REGION)


def _call(c, action, params):
    from aliyunsdkcore.request import CommonRequest
    req = CommonRequest()
    req.set_domain("ecs.aliyuncs.com")
    req.set_version("2014-05-26")
    req.set_action_name(action)
    req.set_method("POST")
    for k, v in params.items():
        req.add_query_param(k, v)
    return json.loads(c.do_action_with_exception(req).decode("utf-8"))


def run_script(script, timeout=240, wait=420, label="script"):
    """在 ECS 上执行 shell 脚本并回读输出（云助手）。返回 (status, exit_code, output)。"""
    c = _client()
    enc = base64.b64encode(script.encode("utf-8")).decode("ascii")
    d = _call(c, "RunCommand", {
        "RegionId": REGION,
        "Type": "RunShellScript",
        "CommandContent": enc,
        "ContentEncoding": "Base64",
        "InstanceId.1": IID,
        "Timeout": str(int(timeout)),
        "Name": "class-tools-deploy" if label == "apply" else "class-tools-probe",
    })
    inv = d.get("InvokeId")
    if not inv:
        raise SystemExit("RunCommand 未返回 InvokeId: %s" % (d.get("RequestId")))
    print("[云助手] %s InvokeId=%s" % (label, inv))
    t0 = time.time()
    last = None
    while time.time() - t0 < wait:
        time.sleep(3)
        r = _call(c, "DescribeInvocationResults", {
            "RegionId": REGION, "InvokeId": inv, "InstanceId": IID})
        items = (((r.get("Invocation") or {}).get("InvocationResults") or {})
                 .get("InvocationResult") or [])
        for it in items:
            st = it.get("InvocationStatus")
            last = (st, it.get("ExitCode"))
            if st in ("Success", "Failed", "Timeout", "Stopped", "Error"):
                raw = it.get("Output") or ""
                try:
                    out = base64.b64decode(raw).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    out = raw
                return st, it.get("ExitCode"), out
    raise SystemExit("云助手执行超时（%ss），最后状态=%s" % (wait, last))


# ---------------------------------------------------------------- 远端脚本


def _caddy_http():
    return r""":80 {
	encode zstd gzip
	handle /api/* {
		reverse_proxy 127.0.0.1:8090
	}
	# 通知附件服务（签名 URL；见 attachments/CONTRACT.md）
	handle /att/* {
		reverse_proxy 127.0.0.1:8091
	}
	# PPT 文件本地缓存（OSS 香港太慢；见 deploy/ECS_DEPLOY.md §8）
	handle /pptfiles/* {
		uri strip_prefix /pptfiles
		reverse_proxy 127.0.0.1:8092
	}
	# 同源 API 代理（迁移第 3 步就绪；网页切到同源基址后生效）
	handle /v1/rdb/rest/* {
		reverse_proxy https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com {
			header_up Host tool-d4gosudok46e0e081.api.tcloudbasegateway.com
		}
	}
	handle /board* {
		rewrite * /board.html
		root * /opt/briefdesk/data
		file_server
	}
	handle {
		root * /var/www/tool
		file_server
	}
	header /board* Cache-Control "no-cache"
	@noCache path /index.html / /tt.json
	header @noCache Cache-Control "no-cache"
	@static path /assets/* /favicon.ico /apple-touch-icon.png /robots.txt
	header @static Cache-Control "public, max-age=604800"
}
"""


def _caddy_https():
    """HTTPS 站点块（自动 Let's Encrypt，HTTP-01）。DNS 恢复后 Caddy 自动签发。"""
    return r"""{
	email __LE_EMAIL__
}

tool.furina.fun {
	encode zstd gzip
	handle /api/* {
		reverse_proxy 127.0.0.1:8090
	}
	# 通知附件服务（签名 URL；见 attachments/CONTRACT.md）
	handle /att/* {
		reverse_proxy 127.0.0.1:8091
	}
	# PPT 文件本地缓存（OSS 香港太慢；见 deploy/ECS_DEPLOY.md §8）
	handle /pptfiles/* {
		uri strip_prefix /pptfiles
		reverse_proxy 127.0.0.1:8092
	}
	# 同源 API 代理（迁移第 3 步就绪；网页切到同源基址后生效）
	handle /v1/rdb/rest/* {
		reverse_proxy https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com {
			header_up Host tool-d4gosudok46e0e081.api.tcloudbasegateway.com
		}
	}
	handle /board* {
		rewrite * /board.html
		root * /opt/briefdesk/data
		file_server
	}
	handle {
		root * /var/www/tool
		file_server
	}
	header /board* Cache-Control "no-cache"
	@noCache path /index.html / /tt.json
	header @noCache Cache-Control "no-cache"
	@static path /assets/* /favicon.ico /apple-touch-icon.png /robots.txt
	header @static Cache-Control "public, max-age=604800"
}

# IP 直连 / 备案前调试入口（域名 HTTPS 启用后仍保留）
:80 {
	encode zstd gzip
	handle /api/* {
		reverse_proxy 127.0.0.1:8090
	}
	# 通知附件服务（签名 URL；见 attachments/CONTRACT.md）
	handle /att/* {
		reverse_proxy 127.0.0.1:8091
	}
	# PPT 文件本地缓存（OSS 香港太慢；见 deploy/ECS_DEPLOY.md §8）
	handle /pptfiles/* {
		uri strip_prefix /pptfiles
		reverse_proxy 127.0.0.1:8092
	}
	# 同源 API 代理（迁移第 3 步就绪；网页切到同源基址后生效）
	handle /v1/rdb/rest/* {
		reverse_proxy https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com {
			header_up Host tool-d4gosudok46e0e081.api.tcloudbasegateway.com
		}
	}
	handle /board* {
		rewrite * /board.html
		root * /opt/briefdesk/data
		file_server
	}
	handle {
		root * /var/www/tool
		file_server
	}
	header /board* Cache-Control "no-cache"
	@noCache path /index.html / /tt.json
	header @noCache Cache-Control "no-cache"
	@static path /assets/* /favicon.ico /apple-touch-icon.png /robots.txt
	header @static Cache-Control "public, max-age=604800"
}
""".replace("__LE_EMAIL__", LE_EMAIL)



def build_apply_script(https=False):
    caddy_http = _caddy_http()
    caddy_https = _caddy_https()
    caddy_active = caddy_https if https else caddy_http
    mode = "https" if https else "http"
    return r"""#!/bin/bash
set -e
TS=$(date +%Y%m%d-%H%M%S)
BASE="__OSS_BASE__"
TMP="/var/www/tool.new.$TS"
BK="/var/www/tool_backup/$TS"
mkdir -p "$TMP/assets" "$BK" /etc/caddy

echo "=== 1. 备份旧文件 ==="
cp -a /var/www/tool/index.html "$BK/index.html.old" 2>/dev/null || true
cp -a /etc/caddy/Caddyfile "$BK/Caddyfile.old" 2>/dev/null || true
ls -la "$BK" | head -5

echo "=== 2. 从 OSS 拉取最新静态站到临时目录 ==="
curl -fsSL --retry 3 --retry-delay 2 --max-time 180 -o "$TMP/index.html" "$BASE/index.html"
curl -fsSL --retry 3 --retry-delay 2 --max-time 120 -o "$TMP/tt.json" "$BASE/tt.json"
for f in assets/qr_tools.png favicon.ico apple-touch-icon.png robots.txt; do
  mkdir -p "$TMP/$(dirname "$f")"
  curl -fsSL --retry 3 --retry-delay 2 --max-time 120 -o "$TMP/$f" "$BASE/$f" || echo "WARN 跳过 $f"
done
IN_SZ=$(stat -c%s "$TMP/index.html")
if [ "$IN_SZ" -lt 500000 ]; then echo "FATAL index.html 太小: $IN_SZ"; exit 3; fi

echo "=== 3. 原子替换站点文件 ==="
cp -a "$TMP/index.html" /var/www/tool/index.html
cp -a "$TMP/tt.json" /var/www/tool/tt.json
cp -a "$TMP/assets/." /var/www/tool/assets/ 2>/dev/null || true
for f in favicon.ico apple-touch-icon.png robots.txt; do
  [ -f "$TMP/$f" ] && cp -a "$TMP/$f" "/var/www/tool/$f" || true
done
chmod -R a+rX /var/www/tool
sha256sum /var/www/tool/index.html /var/www/tool/tt.json

echo "=== 4. 写入并校验 Caddy 配置（__MODE__） ==="
cat > /etc/caddy/Caddyfile.new <<'CADDY_EOF'
__CADDY_ACTIVE__
CADDY_EOF
caddy validate --config /etc/caddy/Caddyfile.new --adapter caddyfile
# 预生成 HTTPS 就绪配置（域名为 tool.furina.fun；DNS 恢复后可直接切换）
cat > /etc/caddy/Caddyfile.https.ready <<'CADDY_HTTPS_EOF'
__CADDY_HTTPS__
CADDY_HTTPS_EOF
caddy validate --config /etc/caddy/Caddyfile.https.ready --adapter caddyfile
mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile

echo "=== 5. reload Caddy ==="
systemctl reload caddy || systemctl restart caddy
sleep 1
systemctl is-active caddy
echo "done: $(date -Is)"
""".replace("__OSS_BASE__", OSS_BASE) \
   .replace("__CADDY_ACTIVE__", caddy_active) \
   .replace("__CADDY_HTTPS__", caddy_https) \
   .replace("__MODE__", mode)


PROBE_SCRIPT = r"""#!/bin/bash
set +e
echo "=== disk ==="; df -h / | tail -2
echo "=== caddy ==="; caddy version 2>/dev/null; echo "active=$(systemctl is-active caddy)"
echo "=== Caddyfile ==="; sed -n '1,160p' /etc/caddy/Caddyfile 2>/dev/null
echo "=== site file ==="; ls -la /var/www/tool | head -20
echo "=== index size/hash ==="; wc -c /var/www/tool/index.html; sha256sum /var/www/tool/index.html
echo "=== local http ==="; curl -s -m 5 -o /dev/null -w 'root=%{http_code} size=%{size_download}\n' http://127.0.0.1/
curl -s -m 8 -o /dev/null -w 'board=%{http_code}\n' http://127.0.0.1/board
curl -s -m 5 -o /dev/null -w 'api=%{http_code}\n' http://127.0.0.1/api/status
echo "=== gzip ==="; curl -s -m 5 -H 'Accept-Encoding: gzip' -D - -o /dev/null http://127.0.0.1/ | tr -d '\r' | grep -Ei 'content-encoding|content-length'
echo "=== https ready config ==="; ls -la /etc/caddy/Caddyfile.https.ready 2>/dev/null || echo "(尚未生成)"
echo "=== done ==="; exit 0
"""


# ---------------------------------------------------------------- 本机校验


def _fetch(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read()


def verify():
    print("=== 本机校验 ECS ===")
    local_index = os.path.join(os.path.dirname(HERE), "tools", "index.html")
    with open(local_index, "rb") as f:
        local = f.read()
    st, hd, body = _fetch("http://%s/" % ECS_IP, {"Accept-Encoding": "identity"})
    print("GET / -> HTTP %s，%d B" % (st, len(body)))
    print("本地 index.html %d B sha256=%s" % (len(local), hashlib.sha256(local).hexdigest()))
    print("ECS  index.html %d B sha256=%s -> %s" % (
        len(body), hashlib.sha256(body).hexdigest(),
        "MATCH" if body == local else "MISMATCH"))
    st, hd, gz = _fetch("http://%s/" % ECS_IP, {"Accept-Encoding": "gzip"})
    print("gzip: HTTP %s, Content-Encoding=%s, 传输字节=%d（未压缩 %d）"
          % (st, hd.get("Content-Encoding"), len(gz), len(body)))
    for path, name in (("/api/status", "board API"), ("/board", "board 页"), ("/tt.json", "课表")):
        try:
            st, hd, b = _fetch("http://%s%s" % (ECS_IP, path), timeout=60)
            print("%-10s HTTP %s %d B" % (name, st, len(b)))
        except Exception as e:  # noqa: BLE001
            print("%-10s ERR %s" % (name, type(e).__name__))
    try:
        st, hd, b = _fetch("http://%s/pptfiles/__health" % ECS_IP, timeout=15)
        payload = json.loads(b.decode("utf-8", "replace") or "{}")
        print("%-10s HTTP %s files=%s bytes=%.2fMB warming=%s"
              % ("pptfiles", st, payload.get("files"), (payload.get("bytes") or 0) / 1048576.0,
                 payload.get("warming")))
        hd2 = None
        req = urllib.request.Request("http://%s/pptfiles/__health" % ECS_IP, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as r:
            hd2 = dict(r.headers)
        print("pptfiles   HEAD HTTP 200 content-length=%s" % (hd2.get("Content-Length"),))
    except Exception as e:  # noqa: BLE001
        print("%-10s ERR %s" % ("pptfiles", type(e).__name__))
    return 0


# ---------------------------------------------------------------- main


def main(argv=None):
    ap = argparse.ArgumentParser(description="ECS 静态站部署（云助手）")
    ap.add_argument("cmd", choices=["probe", "apply", "verify"])
    ap.add_argument("--https", action="store_true", help="同时启用 tool.furina.fun HTTPS 站点块")
    ap.add_argument("--dry-run", action="store_true", help="只打印远端脚本，不执行")
    ns = ap.parse_args(argv)

    if ns.cmd == "verify":
        return verify()
    if ns.cmd == "probe":
        script = PROBE_SCRIPT
        label = "probe"
    else:
        script = build_apply_script(https=ns.https)
        label = "apply"
    if ns.dry_run:
        print(script)
        if ns.cmd == "apply":
            print("\n# 注意：apply 成功后还会分片上传安装 PPT 文件缓存服务"
                  "（deploy/ecs_pptfiles.py：/opt/class-tools/pptfiles/app.py + "
                  "class-tools-pptfiles.service + 健康检查）")
        return 0
    st, rc, out = run_script(script, label=label,
                             timeout=300 if ns.cmd == "apply" else 120,
                             wait=480 if ns.cmd == "apply" else 180)
    print(out)
    print("[结果] status=%s exit=%s" % (st, rc))
    if st != "Success" or rc not in (0, "0", None):
        return 1
    if ns.cmd == "apply":
        # PPT 文件缓存服务：代码 >16KB，不能塞进单条云助手命令，按分片上传安装
        try:
            import ecs_pptfiles
            print("\n[ecs_site] 安装/更新 PPT 文件缓存服务（分片上传 app.py）...")
            if ecs_pptfiles.install_service() != 0:
                print("[ecs_site] WARN PPT 文件缓存服务安装失败；站已更新，可重试："
                      " python deploy\\ecs_pptfiles.py deploy")
        except Exception as exc:  # noqa: BLE001
            print("[ecs_site] WARN PPT 文件缓存服务安装异常：%s" % exc.__class__.__name__)
        print()
        return verify()
    return 0


if __name__ == "__main__":
    sys.exit(main())

