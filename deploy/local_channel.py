# -*- coding: utf-8 -*-
"""班级工具站 · 本地临时通道（域名暂停期间在本机正常登录/使用网站）

背景（2026-11-09/10）：furina.fun 的 DNS 记录全部暂停（备案期间），https://tool.furina.fun 公网不可解析；
但网站本体仍在阿里云 OSS 上，云数据仍走 CloudBase PostgREST。直接用 OSS 默认域名打开网页时，
浏览器 Origin 变成 https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com，不在 CloudBase 网关 CORS 白名单里，
于是身份校验/数据接口会被浏览器拦截（登录不了）。

本脚本提供一个**只在本机**的临时通道：
    浏览器访问 http://127.0.0.1:<port>/  →  本脚本把页面里的 CloudBase 基址替换成同源 /__cb/，
    并在服务端转发到 CloudBase，附带 Origin: https://tool.furina.fun（网关白名单内），
    响应再原样回给浏览器 —— 对浏览器而言全部同源，不存在 CORS 问题，登录/所有工具/PPT 都可用。

安全边界：
  * 默认只绑定 127.0.0.1（仅本机可访问）；不要随意改成 0.0.0.0。
  * 不保存、不打印任何 token/密钥；身份 token 仍由浏览器 localStorage 管理。
  * 除了“替换 CB 基址”这一处，index.html 原文件不改动（在内存里替换后返回给浏览器）。

用法：
    python deploy/local_channel.py                # http://127.0.0.1:8787/
    python deploy/local_channel.py --open         # 启动并自动打开浏览器
    python deploy/local_channel.py --port 8899 --open
    python deploy/local_channel.py --host 0.0.0.0 # 同一局域网其它设备也可访问（谨慎）

停止：终端窗口 Ctrl+C，或直接关闭窗口。域名恢复解析后就不需要本脚本了。
"""
import argparse
import http.client
import json
import mimetypes
import os
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "tools"))   # web/tools

# 线上 CloudBase 网关（与 index.html 里的 CB 完全一致）
CB_UPSTREAM_HOST = "tool-d4gosudok46e0e081.api.tcloudbasegateway.com"
CB_UPSTREAM_PATH = "/v1/rdb/rest/"
CB_BASE = "https://" + CB_UPSTREAM_HOST + CB_UPSTREAM_PATH
CB_FAKE_ORIGIN = "https://tool.furina.fun"

# 需要从浏览器原样转发给 CloudBase 的请求头（大小写不敏感匹配）
FORWARD_REQ_HEADERS = {
    "authorization", "content-type", "accept", "prefer", "x-device-id",
    "x-class-token", "cache-control", "if-none-match",
}
# 响应头白名单（其余丢弃；同源请求也不需要 CORS 头）
FORWARD_RESP_HEADERS = {"content-type", "cache-control", "etag", "content-range", "location"}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def log(msg):
    print("[local-channel] " + msg, flush=True)


def _read_file(rel):
    path = os.path.abspath(os.path.join(ROOT, rel.replace("/", os.sep)))
    if not path.startswith(ROOT + os.sep) and path != ROOT:
        return None
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (OSError, IOError):
        return None


def _rewrite_index_html(data):
    """把 CloudBase 基址替换为同源 /__cb/（只改这一处，其它逻辑零改动）。"""
    text = data.decode("utf-8", "replace")
    before = text.count(CB_BASE)
    text = text.replace(CB_BASE, "/__cb/")
    # 兜底：若以后改成不带末尾斜杠的写法，也一并替换
    text = text.replace(CB_BASE.rstrip("/"), "/__cb")
    if before:
        log("index.html: 已注入同源代理基址（替换 %d 处）" % before)
    return text.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ClassToolsLocalChannel/1.0"

    # ---------------- 基础 ----------------
    def log_message(self, fmt, *args):  # 静音默认日志；只打印代理错误
        pass

    def _send(self, code, body=b"", content_type="application/octet-stream", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    # ---------------- 入口 ----------------
    def do_OPTIONS(self):
        if self.path.startswith("/__cb/"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Prefer, X-Device-Id, X-Class-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send(204)

    def do_GET(self):
        if self.path.startswith("/__cb/"):
            return self._proxy()
        if self.path.startswith("/__chan/health"):
            return self._send(200, json.dumps({"ok": True, "upstream": CB_UPSTREAM_HOST}).encode(),
                              "application/json; charset=utf-8")
        return self._serve_static()

    def do_HEAD(self):
        if self.path.startswith("/__cb/"):
            return self._proxy()
        return self._serve_static()

    def do_POST(self):
        if self.path.startswith("/__cb/"):
            return self._proxy()
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_PATCH(self):
        if self.path.startswith("/__cb/"):
            return self._proxy()
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_DELETE(self):
        if self.path.startswith("/__cb/"):
            return self._proxy()
        self._send(404, b"not found", "text/plain; charset=utf-8")

    # ---------------- 静态文件 ----------------
    def _serve_static(self):
        parsed = urllib.parse.urlparse(self.path)
        rel = urllib.parse.unquote(parsed.path or "/").lstrip("/")
        if not rel or rel.endswith("/"):
            rel = (rel + "index.html").lstrip("/")
        data = _read_file(rel)
        if data is None:
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ext = os.path.splitext(rel)[1].lower()
        ctype = MIME.get(ext) or mimetypes.guess_type(rel)[0] or "application/octet-stream"
        if rel.lower() in ("index.html", "index.htm"):
            data = _rewrite_index_html(data)
        self._send(200, data, ctype)

    # ---------------- CloudBase 代理 ----------------
    def _proxy(self):
        parsed = urllib.parse.urlparse(self.path)
        rest = parsed.path[len("/__cb/"):]
        upstream = CB_UPSTREAM_PATH + rest
        if parsed.query:
            upstream += "?" + parsed.query

        # 读请求体
        body = None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 0:
            body = self.rfile.read(length)

        headers = {}
        for k, v in self.headers.items():
            if k.lower() in FORWARD_REQ_HEADERS:
                headers[k] = v
        headers["Origin"] = CB_FAKE_ORIGIN
        headers["Referer"] = CB_FAKE_ORIGIN + "/"
        headers["Accept-Encoding"] = "identity"
        headers["Host"] = CB_UPSTREAM_HOST

        try:
            conn = http.client.HTTPSConnection(CB_UPSTREAM_HOST, timeout=60)
            conn.request(self.command, upstream, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            out_headers = {}
            for k, v in resp.getheaders():
                if k.lower() in FORWARD_RESP_HEADERS:
                    out_headers[k] = v
            conn.close()
        except Exception as e:  # noqa: BLE001
            log("代理失败 %s %s -> %r" % (self.command, upstream, e))
            return self._send(502, json.dumps({"error": "local_channel_upstream_failed", "detail": str(e)[:200]}).encode(),
                              "application/json; charset=utf-8")
        # 透传状态码与响应体（同源，无需 CORS 头）
        self._send(resp.status, data, out_headers.get("Content-Type", "application/json; charset=utf-8"),
                   extra={k: v for k, v in out_headers.items() if k.lower() != "content-type"})


def _already_running(host, port):
    """若该端口已经跑着本通道（或别的服务），返回 health 结果；无服务返回 None。"""
    import urllib.request as _u
    try:
        with _u.urlopen("http://%s:%d/__chan/health" % (host, port), timeout=1.5) as r:
            if r.status == 200:
                return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    return None


def main():
    ap = argparse.ArgumentParser(description="班级工具站本地临时通道（域名暂停期间本机使用）")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1，仅本机）")
    ap.add_argument("--port", type=int, default=8787, help="端口（默认 8787；占用时自动顺延）")
    ap.add_argument("--open", action="store_true", help="启动后自动打开默认浏览器")
    args = ap.parse_args()

    if not os.path.isdir(ROOT):
        log("找不到站点目录: %s" % ROOT)
        return 1

    # 0) 已有一个通道在跑：直接打开浏览器（避免重复启动报端口占用）
    host_open = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    existing = _already_running(host_open, args.port)
    if existing:
        url = "http://%s:%d/" % (host_open, args.port)
        log("检测到临时通道已在运行： %s" % url)
        if args.open:
            webbrowser.open(url)
        return 0

    # 1) 绑定端口；被占用则顺延（最多 +10）
    srv = None
    last_err = None
    for port in range(args.port, args.port + 11):
        try:
            srv = ThreadingHTTPServer((args.host, port), Handler)
            break
        except OSError as e:
            last_err = e
            log("端口 %d 不可用（%s），尝试下一个…" % (port, e))
    if srv is None:
        log("没有可用端口（从 %d 起 11 个均被占用）：%s" % (args.port, last_err))
        return 1
    srv.daemon_threads = True
    actual = srv.server_address[1]
    url = "http://%s:%d/" % (host_open, actual)
    log("临时通道已启动： %s" % url)
    log("站点目录: %s" % ROOT)
    log("原理: 页面 CloudBase 基址 -> 同源 /__cb/ -> 服务端带 Origin=%s 转发（绕开 DNS 与 CORS）" % CB_FAKE_ORIGIN)
    log("停止: Ctrl+C 或关闭本窗口；域名恢复解析后不再需要本脚本。")
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("已停止")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
