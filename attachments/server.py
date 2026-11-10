# -*- coding: utf-8 -*-
"""通知附件服务（ECS 端，纯标准库）。

部署位置：/opt/class-tools/attachments_server.py
监听：127.0.0.1:8091（由 Caddy 的 /att/* 反代，不直接暴露）
存储：ATT_DIR（默认 /opt/class-tools/attachments/<id> 与 <id>.json）
鉴权：
  - GET/HEAD /att/<id>?exp=&sig=   签名 URL（见 common.py），无需请求头；
  - POST /att/upload               X-Sync-Token 必须等于 SYNC_TOKEN 环境变量；
  - GET /att/healthz               健康检查（不含敏感信息）。
环境变量：SYNC_TOKEN、ATT_DIR、ATT_PORT、ATT_MAX_BYTES（默认 25MB）。
"""
import json
import os
import re
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import content_id, derive_key, parse_att_id, verify  # noqa: E402

ATT_DIR = os.path.abspath(os.environ.get("ATT_DIR", "/opt/class-tools/attachments"))
ATT_PORT = int(os.environ.get("ATT_PORT", "8091"))
ATT_MAX_BYTES = int(os.environ.get("ATT_MAX_BYTES", str(25 * 1024 * 1024)))
SYNC_TOKEN = os.environ.get("SYNC_TOKEN", "")
KEY = derive_key(SYNC_TOKEN) if SYNC_TOKEN else b""
MIME_RE = re.compile(r"^[-\w.+/]+$")


def _meta_path(att_id):
    return os.path.join(ATT_DIR, att_id + ".json")


def _blob_path(att_id):
    return os.path.join(ATT_DIR, att_id)


def _load_meta(att_id):
    try:
        with open(_meta_path(att_id), "r", encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def _safe_name(name):
    name = str(name or "").strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[\x00-\x1f]", "", name)
    return name[:160] or "附件"


def _json(handler, code, obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "class-att/1.0"

    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), fmt % args))

    # ---------------- GET/HEAD ----------------
    def do_HEAD(self):
        self._serve(head_only=True)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path in ("/att/healthz", "/healthz"):
            try:
                n = len([x for x in os.scandir(ATT_DIR) if x.is_file() and not x.name.endswith(".json")])
            except OSError:
                n = 0
            return _json(self, 200, {"ok": True, "attachments": n, "auth": bool(KEY and SYNC_TOKEN), "ts": int(time.time())})
        self._serve(head_only=False)

    def _serve(self, head_only=False):
        parsed = urllib.parse.urlsplit(self.path)
        att_id = parse_att_id(parsed.path)
        if not att_id:
            return _json(self, 404, {"ok": False, "error": "not_found"})
        if not KEY:
            return _json(self, 500, {"ok": False, "error": "server_key_missing"})
        q = urllib.parse.parse_qs(parsed.query)
        exp = (q.get("exp") or [""])[0]
        sig = (q.get("sig") or [""])[0]
        if not verify(att_id, exp, sig, KEY):
            return _json(self, 403, {"ok": False, "error": "bad_signature"})
        path = _blob_path(att_id)
        try:
            size = os.path.getsize(path)
            fh = open(path, "rb")
        except OSError:
            return _json(self, 404, {"ok": False, "error": "missing_blob"})
        meta = _load_meta(att_id)
        mime = meta.get("mime") or "application/octet-stream"
        name = _safe_name(meta.get("name") or att_id)
        start, end = 0, size - 1
        code = 200
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
                else:
                    end = size - 1
                if start > end or start >= size:
                    fh.close()
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.end_headers()
                    return
                code = 206
        length = end - start + 1
        disp = "inline" if mime.startswith(("image/", "application/pdf", "video/", "audio/")) else "attachment"
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Content-Disposition", "%s; filename*=UTF-8''%s" % (disp, urllib.parse.quote(name)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if head_only:
            fh.close()
            return
        try:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(left, 256 * 1024))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            fh.close()

    # ---------------- POST /att/upload ----------------
    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path not in ("/att/upload", "/upload"):
            return _json(self, 404, {"ok": False, "error": "not_found"})
        if not SYNC_TOKEN:
            return _json(self, 500, {"ok": False, "error": "server_token_missing"})
        token = self.headers.get("X-Sync-Token", "")
        if not hmac_compare(token, SYNC_TOKEN):
            return _json(self, 403, {"ok": False, "error": "bad_token"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > ATT_MAX_BYTES:
            return _json(self, 413, {"ok": False, "error": "bad_size", "max": ATT_MAX_BYTES})
        data = self.rfile.read(length)
        if len(data) != length:
            return _json(self, 400, {"ok": False, "error": "short_body"})
        att_id = content_id(data)
        name = _safe_name(urllib.parse.unquote(self.headers.get("X-Att-Name", "")))
        mime = urllib.parse.unquote(self.headers.get("X-Att-Mime", "") or "application/octet-stream").lower()
        if not MIME_RE.match(mime):
            mime = "application/octet-stream"
        os.makedirs(ATT_DIR, exist_ok=True)
        tmp = _blob_path(att_id) + ".tmp.%d" % os.getpid()
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _blob_path(att_id))
        meta = {"id": att_id, "name": name, "mime": mime, "size": len(data),
                "sha256": content_id(data), "ts": int(time.time())}
        with open(_meta_path(att_id), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        return _json(self, 200, {"ok": True, "id": att_id, "size": len(data)})


def hmac_compare(a, b):
    try:
        import hmac
        return hmac.compare_digest(str(a), str(b))
    except Exception:  # noqa: BLE001
        return False


def main():
    os.makedirs(ATT_DIR, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", ATT_PORT), Handler)
    sys.stderr.write("class-att listening on 127.0.0.1:%d dir=%s token=%s\n"
                     % (ATT_PORT, ATT_DIR, "set" if SYNC_TOKEN else "MISSING"))
    srv.serve_forever()


if __name__ == "__main__":
    main()
