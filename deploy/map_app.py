# -*- coding: utf-8 -*-
"""极简共享布局状态服务（标准库，127.0.0.1:8095，Caddy /map/api 反代）。"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.environ.get("MAP_ROOT", "/opt/class-tools/map")
STATE = os.path.join(ROOT, "state.json")
SEED = os.path.join(ROOT, "seed.json")
PORT = int(os.environ.get("MAP_PORT", "8095"))
MAX = 16 * 1024 * 1024


def empty():
    return {"buildings": [], "roads": [], "water": [], "islands": [], "green": [], "plaza": []}


def load():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            obj = json.load(f)
            return int(obj.get("rev") or 0), obj.get("state") or empty()
    except Exception:
        pass
    try:
        with open(SEED, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = empty()
    rev = int(time.time() * 1000)
    save(rev, state)
    return rev, state


def save(rev, state):
    os.makedirs(ROOT, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"rev": rev, "state": state}, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE)


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path.startswith("/__health"):
            return self._send(200, {"ok": True, "service": "class-tools-map", "root": ROOT})
        if self.path.startswith("/state"):
            rev, state = load()
            return self._send(200, {"rev": rev, "state": state})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/state"):
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX:
                return self._send(413, {"error": "bad length"})
            raw = self.rfile.read(n)
            obj = json.loads(raw.decode("utf-8"))
            state = obj.get("state")
            base = int(obj.get("baseRev") or 0)
            if not isinstance(state, dict):
                return self._send(400, {"error": "state required"})
            cur, _ = load()
            if base and base != cur:
                return self._send(409, {"error": "conflict", "rev": cur})
            rev = max(int(time.time() * 1000), cur + 1)
            save(rev, state)
            return self._send(200, {"ok": True, "rev": rev})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    os.makedirs(ROOT, exist_ok=True)
    load()
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
