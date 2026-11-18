# -*- coding: utf-8 -*-
"""drop/tests/test_drop_app.py — 文件传输服务（deploy/drop_app.py）本机单元测试

纯标准库 unittest，**不连真实 CloudBase**：
- 鉴权注入假校验器（替换 `drop_app.validate_token`），覆盖缺失/无效 token、同 sid 多 token 互见；
- 另有一组用本机假网关（http.server）直接测 `validate_token` 的网关协议：
  成功解析、120s 缓存、ok:false→401、5xx/坏 JSON/缺 sid/不可达→503（fail closed）；
- 覆盖 CORS、会话隔离、分片上传（含 20MiB 大文件 3 片）、下载 Range/HEAD/签名过期/篡改、
  文字/指令白名单、限制（413）、事件上限 500、TTL 清理、健康统计；
- **v2（2026-11-11）新增**：默认会话 TTL = 259200s（3 天）、默认单文件/单会话**不限大小**
  （磁盘余量是唯一限制；env 仍可覆盖上限）、磁盘不足 507、未完成分片 24h 回收、
  `/__health` 暴露 ttl=259200 / max_file_bytes=0 / max_session_bytes=0。

运行（web 目录）：
    python -m unittest drop.tests.test_drop_app -v
    python drop\\tests\\test_drop_app.py -v
"""
import contextlib
import hashlib
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
DEPLOY = os.path.join(WEB, "deploy")

TMP_ROOT = tempfile.mkdtemp(prefix="drop_app_test_")
os.environ["DROP_ROOT"] = TMP_ROOT
os.environ["DROP_PORT"] = "0"
os.environ["DROP_PUBLIC_PREFIX"] = ""
os.environ["DROP_PUBLIC_BASE"] = ""
os.environ["DROP_GATEWAY"] = "http://127.0.0.1:9/unreachable/"
os.environ["DROP_PUBLISH_KEY"] = "test-publish-key"
sys.path.insert(0, DEPLOY)

import drop_app as app  # noqa: E402

FAKE_IDENTITIES = {
    "tok_alice": {"sid": "sid_alice", "name": "甲同学", "seat": 1},
    "tok_alice2": {"sid": "sid_alice", "name": "甲同学", "seat": 1},
    "tok_bob": {"sid": "sid_bob", "name": "乙同学", "seat": 2},
    "tok_carol": {"sid": "sid_carol", "name": "丙同学", "seat": 3},
}
FAKE_CALLS = []


def fake_validate(token):
    FAKE_CALLS.append(token)
    info = FAKE_IDENTITIES.get(str(token or ""))
    if not info:
        raise app.AuthError(401, "身份无效")
    return dict(info)


ORIG_VALIDATE = app.validate_token
FAKE_GATEWAY = {"base": "", "calls": [], "queue": [], "server": None,
                "thread": None}
ORIG_LOG = app.log


# ---------------------------------------------------------------------------
# 本机假 CloudBase 网关（只实现 rpc/class_whoami）
# ---------------------------------------------------------------------------
class _GwHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(length)
        with app._LOCK:
            FAKE_GATEWAY["calls"].append({
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
            })
            queue = FAKE_GATEWAY["queue"]
            status, payload = queue.pop(0) if queue else (500, {"error": "empty"})
        data = payload if isinstance(payload, bytes) else json.dumps(
            payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_fake_gateway():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _GwHandler)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    FAKE_GATEWAY["server"] = srv
    FAKE_GATEWAY["thread"] = thread
    FAKE_GATEWAY["base"] = "http://127.0.0.1:%d/" % srv.server_address[1]


# ---------------------------------------------------------------------------
# HTTP 客户端（每次新建连接，Connection: close，便于测 HEAD/Range）
# ---------------------------------------------------------------------------
class Client(object):
    def __init__(self, host, port):
        self.host = host
        self.port = port

    def request(self, method, path, body=None, headers=None, token=None):
        hdrs = dict(headers or {})
        if token is not None:
            hdrs["X-Device-Id"] = token
        conn = http.client.HTTPConnection(self.host, self.port, timeout=60)
        try:
            conn.request(method, path, body=body, headers=hdrs)
            resp = conn.getresponse()
            data = resp.read()
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, resp_headers, data
        finally:
            conn.close()

    def request_without_length(self, method, path, token=None):
        """不发送 Content-Length 的原始请求（测 411）。"""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=60)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", "%s:%d" % (self.host, self.port))
            if token is not None:
                conn.putheader("X-Device-Id", token)
            conn.endheaders()
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    def json_of(self, status, data):
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise AssertionError("响应不是 JSON: %r" % data[:200])


# ---------------------------------------------------------------------------
# 模块级：起服务 + 假网关（整个测试文件共用一套）
# ---------------------------------------------------------------------------
SERVER = {"srv": None, "client": None}


def setUpModule():
    app.log = lambda *a, **k: None          # 测试不输出访问日志
    app.ensure_dirs()
    srv = app.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    SERVER["srv"] = srv
    SERVER["client"] = Client("127.0.0.1", srv.server_address[1])
    start_fake_gateway()


def tearDownModule():
    srv = SERVER.get("srv")
    if srv is not None:
        srv.shutdown()
        srv.server_close()
    gw = FAKE_GATEWAY.get("server")
    if gw is not None:
        gw.shutdown()
        gw.server_close()
    app.log = ORIG_LOG
    app.validate_token = ORIG_VALIDATE
    shutil.rmtree(TMP_ROOT, ignore_errors=True)


class Base(unittest.TestCase):
    @property
    def client(self):
        return SERVER["client"]

    def setUp(self):
        app.validate_token = fake_validate
        del FAKE_CALLS[:]
        with app._LOCK:
            app._AUTH_CACHE.clear()
            app._UPLOAD_LOCKS.clear()
        for path in (app.SESSION_DIR, app.FILES_DIR, app.UPLOAD_DIR):
            shutil.rmtree(path, ignore_errors=True)
        app.ensure_dirs()
        FAKE_GATEWAY["calls"] = []
        FAKE_GATEWAY["queue"] = []

    # -- 便捷请求 ----------------------------------------------------------
    @contextlib.contextmanager
    def disk_free(self, free_bytes):
        """临时替换磁盘可用空间（测磁盘余量/507；不真的占用磁盘）。"""
        orig = app._disk_free
        app._disk_free = lambda: int(free_bytes)
        try:
            yield
        finally:
            app._disk_free = orig

    def age_session(self, session_id, seconds, age_files=True):
        """把会话最后活动（可选：全部文件上传时间）回拨 N 秒，模拟 TTL 到期。"""
        old_ms = app._now_ms() - int(seconds) * 1000
        with app._LOCK:
            sess = app._load_session(session_id)
            sess["lastActivityAt"] = old_ms
            sess["updatedAt"] = old_ms
            if age_files:
                for item in sess.get("files") or []:
                    item["at"] = old_ms
            app._save_session(sess)

    def age_file(self, session_id, file_id, seconds):
        """只回拨某一个文件的上传时间（逐文件 TTL 用）。"""
        old_ms = app._now_ms() - int(seconds) * 1000
        with app._LOCK:
            sess = app._load_session(session_id)
            for item in sess.get("files") or []:
                if item.get("id") == file_id:
                    item["at"] = old_ms
            app._save_session(sess)

    def req(self, method, path, body=None, headers=None, token=None):
        return self.client.request(method, path, body=body, headers=headers,
                                   token=token)

    def get(self, path, token=None):
        return self.req("GET", path, token=token)

    def post_json(self, path, payload, token=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.req("POST", path, body=body,
                        headers={"Content-Type": "application/json"}, token=token)

    def open_session(self, token):
        status, _hd, data = self.post_json("/open", {}, token=token)
        self.assertEqual(status, 200, data[:200])
        payload = self.client.json_of(status, data)
        self.assertTrue(payload.get("ok"))
        return payload["session"]

    def state(self, token, session_id, since=0):
        status, _hd, data = self.get(
            "/state?sessionId=%s&since=%d" % (urllib.parse.quote(session_id), since),
            token=token)
        return status, self.client.json_of(status, data)

    def upload(self, token, session_id, name, blob, mime="application/octet-stream",
               chunk_size=None):
        chunk_size = chunk_size or app.CHUNK_SIZE
        chunks = [blob[i:i + chunk_size] for i in range(0, len(blob), chunk_size)]
        if not chunks:
            chunks = [b""]
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": session_id, "name": name, "size": len(blob),
            "mime": mime, "totalChunks": len(chunks)}, token=token)
        self.assertEqual(status, 200, data[:300])
        init = self.client.json_of(status, data)
        self.assertEqual(init["chunkSize"], app.CHUNK_SIZE)
        upload_id = init["uploadId"]
        for index, chunk in enumerate(chunks):
            status, _hd, data = self.req(
                "POST",
                "/upload/chunk?uploadId=%s&index=%d" % (upload_id, index),
                body=chunk, token=token)
            self.assertEqual(status, 200, data[:300])
            got = self.client.json_of(status, data)
            self.assertTrue(got.get("ok"))
        status, _hd, data = self.post_json("/upload/finish", {
            "sessionId": session_id, "uploadId": upload_id}, token=token)
        self.assertEqual(status, 200, data[:300])
        return self.client.json_of(status, data)["file"]

    def download(self, url, headers=None):
        parts = urllib.parse.urlsplit(url)
        path = parts.path + ("?" + parts.query if parts.query else "")
        return self.req("GET", path, headers=headers or {})

    @staticmethod
    def fail_payload(test, status, data, expect_status, expect_reason_part=None):
        test.assertEqual(status, expect_status, data[:300])
        payload = json.loads(data.decode("utf-8"))
        test.assertIs(payload.get("ok"), False)
        if expect_reason_part is not None:
            test.assertIn(expect_reason_part, payload.get("reason") or "")
        return payload


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------
class TestHelpers(unittest.TestCase):
    def test_safe_filename_strips_path_backslash_control(self):
        self.assertEqual(app._safe_filename("../../etc/passwd"), "passwd")
        self.assertEqual(app._safe_filename(r"..\..\evil.txt"), "evil.txt")
        self.assertEqual(app._safe_filename("a\x00b\x1f.txt"), "ab.txt")
        self.assertEqual(app._safe_filename(".."), "文件")
        self.assertEqual(app._safe_filename(""), "文件")
        self.assertEqual(app._safe_filename(None), "文件")

    def test_safe_filename_length_keeps_extension(self):
        name = app._safe_filename("长" * 300 + ".pdf")
        self.assertLessEqual(len(name), 180)
        self.assertTrue(name.endswith(".pdf"))
        self.assertTrue(name.startswith("长"))

    def test_safe_mime(self):
        self.assertEqual(app._safe_mime("image/png"), "image/png")
        self.assertEqual(app._safe_mime("Text/Plain; charset=x"), "application/octet-stream")
        self.assertEqual(app._safe_mime(""), "application/octet-stream")

    def test_parse_range_variants(self):
        self.assertEqual(app._parse_range("bytes=0-9", 100), (0, 9))
        self.assertEqual(app._parse_range("bytes=90-", 100), (90, 99))
        self.assertEqual(app._parse_range("bytes=-5", 100), (95, 99))
        self.assertEqual(app._parse_range("bytes=90-200", 100), (90, 99))
        self.assertIsNone(app._parse_range("bytes=0-1,3-4", 100))
        self.assertIsNone(app._parse_range("bytes=200-300", 100))
        self.assertIsNone(app._parse_range("", 100))
        self.assertIsNone(app._parse_range("bytes=abc", 100))

    def test_sign_stable_and_bound_to_fields(self):
        sig = app._sign("a" * 16, "b" * 16, 1700000000000)
        self.assertEqual(sig, app._sign("a" * 16, "b" * 16, 1700000000000))
        self.assertEqual(len(sig), 64)
        self.assertNotEqual(sig, app._sign("a" * 16, "b" * 16, 1700000000001))
        self.assertNotEqual(sig, app._sign("c" * 16, "b" * 16, 1700000000000))
        self.assertNotEqual(sig, app._sign("a" * 16, "c" * 16, 1700000000000))


# ---------------------------------------------------------------------------
# CORS / 健康 / 鉴权入口
# ---------------------------------------------------------------------------
class TestCorsAndHealth(Base):
    def test_defaults_are_three_days_and_unlimited(self):
        """v2.1 契约默认值：文件/会话空闲 TTL 3 天、单文件/单会话不限大小、分片 24h 回收。"""
        self.assertEqual(app.TTL_SEC, 259200)
        self.assertEqual(app.TTL_SEC // 3600, 72)
        self.assertEqual(app.MAX_FILE_BYTES, 0)      # 0 = 不限
        self.assertEqual(app.MAX_SESSION_BYTES, 0)   # 0 = 不限
        self.assertEqual(app.UPLOAD_TTL_SEC, 86400)
        self.assertEqual(app.VERSION, "2.5")

    def test_health_no_auth_and_shape(self):
        status, headers, data = self.get("/__health")
        self.assertEqual(status, 200)
        payload = self.client.json_of(status, data)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload["version"], "2.5")
        self.assertEqual(payload["sessions"], 0)
        self.assertEqual(payload["files"], 0)
        self.assertEqual(payload["bytes"], 0)
        # v2/v2.1：health 暴露 文件 TTL / 会话空闲 TTL / 大小上限（前端文案与自动化用）
        self.assertEqual(payload["ttl"], 259200)
        self.assertEqual(payload["ttl_hours"], 72)
        self.assertEqual(payload["file_ttl"], 259200)
        self.assertEqual(payload["session_idle_ttl"], 259200)
        self.assertEqual(payload["max_file_bytes"], 0)
        self.assertEqual(payload["max_session_bytes"], 0)
        self.assertEqual(payload["max_files"], 300)
        self.assertIsInstance(payload["disk_free"], int)
        self.assertIsInstance(payload["disk_reserve"], int)
        for key in ("ok", "version", "sessions", "files", "bytes", "ttl",
                    "ttl_hours", "file_ttl", "session_idle_ttl",
                    "max_file_bytes", "max_session_bytes",
                    "max_files", "upload_ttl", "disk_free", "disk_reserve"):
            self.assertIn(key, payload)
        self.assertIn("application/json", headers.get("content-type", ""))

    def test_health_tolerates_drop_prefix(self):
        status, _hd, _data = self.get("/drop/__health")
        self.assertEqual(status, 200)

    def test_options_echo_origin_and_headers(self):
        status, headers, _data = self.req(
            "OPTIONS", "/upload/init",
            headers={"Origin": "http://121.196.47.2",
                     "Access-Control-Request-Method": "POST"})
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("access-control-allow-origin"),
                         "http://121.196.47.2")
        self.assertEqual(headers.get("vary"), "Origin")
        allow_headers = headers.get("access-control-allow-headers", "").lower()
        for name in ("content-type", "x-device-id", "x-upload-id"):
            self.assertIn(name, allow_headers)
        allow_methods = headers.get("access-control-allow-methods", "")
        for name in ("GET", "POST", "DELETE", "OPTIONS"):
            self.assertIn(name, allow_methods)
        expose = headers.get("access-control-expose-headers", "").lower()
        self.assertIn("content-length", expose)
        self.assertIn("content-range", expose)

    def test_options_no_origin_star(self):
        status, headers, _data = self.req("OPTIONS", "/state")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("access-control-allow-origin"), "*")

    def test_401_carries_cors_and_chinese_reason(self):
        status, headers, data = self.post_json("/open", {}, token=None)
        self.fail_payload(self, status, data, 401, "身份")
        origin = "https://tool.furina.fun"
        status, headers, data = self.req(
            "POST", "/open", body=b"{}",
            headers={"Content-Type": "application/json", "Origin": origin})
        self.assertEqual(status, 401)
        self.assertEqual(headers.get("access-control-allow-origin"), origin)

    def test_missing_token_401(self):
        status, _hd, data = self.get("/mine")
        self.fail_payload(self, status, data, 401, "缺少")

    def test_invalid_token_401(self):
        status, _hd, data = self.get("/mine", token="tok_nobody")
        self.fail_payload(self, status, data, 401, "身份无效")

    def test_wrong_method_405(self):
        status, _hd, data = self.get("/open", token="tok_alice")
        self.fail_payload(self, status, data, 405)

    def test_unknown_route_404(self):
        status, _hd, data = self.get("/nope")
        self.fail_payload(self, status, data, 404)

    # -- token 透传给校验器（级联缓存见 TestGatewayAuth） ------------------
    def test_token_forwarded_to_validator(self):
        self.open_session("tok_alice")
        self.assertEqual(FAKE_CALLS, ["tok_alice"])
        self.get("/mine", token="tok_bob")
        self.assertEqual(FAKE_CALLS, ["tok_alice", "tok_bob"])


# ---------------------------------------------------------------------------
# 会话 / 隔离 / /state 游标
# ---------------------------------------------------------------------------
class TestSessions(Base):
    def test_open_returns_contract_fields(self):
        session = self.open_session("tok_alice")
        self.assertEqual(set(session.keys()), {"id", "code", "expiresAt", "createdAt", "seq"})
        self.assertRegex(session["id"], r"^[0-9a-f]{16}$")
        self.assertRegex(session["code"], r"^\d{6}$")
        now = int(time.time() * 1000)
        self.assertLessEqual(session["createdAt"], now)
        self.assertGreater(session["expiresAt"], now)
        # v2.1：创建时 expiresAt = max(最后活动(创建)+72h, 文件过期)；之后随活动/文件滑动
        self.assertEqual(session["expiresAt"] - session["createdAt"],
                         app.TTL_SEC * 1000)
        self.assertGreaterEqual(session["expiresAt"] - now, 71 * 3600 * 1000)

    def test_mine_null_then_session(self):
        status, _hd, data = self.get("/mine", token="tok_bob")
        payload = self.client.json_of(status, data)
        self.assertEqual(status, 200)
        self.assertIsNone(payload["session"])
        session = self.open_session("tok_bob")
        status, _hd, data = self.get("/mine", token="tok_bob")
        payload = self.client.json_of(status, data)
        self.assertEqual(payload["session"]["id"], session["id"])

    def test_open_reuses_session(self):
        first = self.open_session("tok_alice")
        second = self.open_session("tok_alice")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["code"], second["code"])

    def test_same_sid_two_tokens_share_session(self):
        first = self.open_session("tok_alice")
        second = self.open_session("tok_alice2")
        self.assertEqual(first["id"], second["id"])

    def test_other_account_has_own_session(self):
        alice = self.open_session("tok_alice")
        bob = self.open_session("tok_bob")
        self.assertNotEqual(alice["id"], bob["id"])

    def test_state_requires_ownership(self):
        alice = self.open_session("tok_alice")
        status, _hd, data = self.get(
            "/state?sessionId=%s" % alice["id"], token="tok_bob")
        self.fail_payload(self, status, data, 403, "无权")

    def test_state_unknown_session_404(self):
        self.open_session("tok_alice")
        status, _hd, data = self.get(
            "/state?sessionId=%s" % ("0" * 16), token="tok_alice")
        self.fail_payload(self, status, data, 404)

    def test_state_bad_session_id_400(self):
        self.open_session("tok_alice")
        status, _hd, data = self.get(
            "/state?sessionId=not-a-session", token="tok_alice")
        self.fail_payload(self, status, data, 400)

    def test_state_cursor_and_events(self):
        session = self.open_session("tok_alice")
        status, payload = self.state("tok_alice", session["id"])
        self.assertEqual(payload["cursor"], 0)
        self.assertEqual(payload["events"], [])
        self.assertFalse(payload["session"]["closed"])
        for i in range(3):
            status, _hd, data = self.post_json(
                "/text", {"sessionId": session["id"], "text": "第%d条" % i},
                token="tok_alice")
            self.assertEqual(status, 200)
            self.assertEqual(self.client.json_of(status, data)["seq"], i + 1)
        status, payload = self.state("tok_alice", session["id"], since=1)
        self.assertEqual([ev["seq"] for ev in payload["events"]], [2, 3])
        self.assertEqual(payload["cursor"], 3)
        ev = payload["events"][0]
        self.assertEqual(set(ev.keys()), {"seq", "kind", "at", "from", "payload"})
        self.assertEqual(ev["kind"], "text")
        self.assertEqual(ev["from"]["name"], "甲同学")
        self.assertEqual(ev["payload"], {"text": "第1条"})

    def test_same_sid_other_token_sees_events(self):
        session = self.open_session("tok_alice")
        self.post_json("/text", {"sessionId": session["id"], "text": "大屏收到"},
                       token="tok_alice")
        status, payload = self.state("tok_alice2", session["id"])
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["events"]), 1)
        # 反向：第二个 token 发文字，第一个 token 拉取
        self.post_json("/text", {"sessionId": session["id"], "text": "手机回复"},
                       token="tok_alice2")
        status, payload = self.state("tok_alice", session["id"], since=1)
        self.assertEqual([ev["payload"]["text"] for ev in payload["events"]],
                         ["手机回复"])

    def test_cross_account_text_and_cmd_403(self):
        alice = self.open_session("tok_alice")
        for path, body in (
                ("/text", {"sessionId": alice["id"], "text": "x"}),
                ("/cmd", {"sessionId": alice["id"], "op": "focus", "args": {}}),
                ("/upload/init", {"sessionId": alice["id"], "name": "a.txt",
                                  "size": 1, "mime": "text/plain", "totalChunks": 1}),
                ("/close", {"sessionId": alice["id"]}),
        ):
            status, _hd, data = self.post_json(path, body, token="tok_bob")
            self.fail_payload(self, status, data, 403, "无权")

    def test_close_deletes_session_and_files(self):
        session = self.open_session("tok_alice")
        file_info = self.upload("tok_alice", session["id"], "a.txt", b"hello")
        self.assertEqual(self.download(file_info["downloadUrl"])[0], 200)
        status, _hd, data = self.post_json("/close", {}, token="tok_alice")
        payload = self.client.json_of(status, data)
        self.assertTrue(payload["ok"])
        status, _hd, data = self.get("/mine", token="tok_alice")
        self.assertIsNone(self.client.json_of(status, data)["session"])
        status, _hd, data = self.download(file_info["downloadUrl"])
        self.assertEqual(status, 404)
        health = self.client.json_of(200, self.get("/__health")[2])
        self.assertEqual(health["sessions"], 0)
        self.assertEqual(health["files"], 0)
        self.assertFalse(os.path.isdir(os.path.join(app.FILES_DIR, session["id"])))

    def test_delete_session_alias(self):
        session = self.open_session("tok_alice")
        status, _hd, data = self.req(
            "DELETE", "/session/" + session["id"], token="tok_alice")
        self.assertEqual(status, 200)
        self.assertFalse(os.path.exists(app._session_path(session["id"])))

    def test_expired_session_replaced_on_open(self):
        old = self.open_session("tok_alice")
        blob = b"old-file"
        self.upload("tok_alice", old["id"], "old.bin", blob)
        # v2.1：会话空闲 72h（且无未过期文件）→ /open 回收旧会话建新会话
        self.age_session(old["id"], app.TTL_SEC + 60)
        new = self.open_session("tok_alice")
        self.assertNotEqual(new["id"], old["id"])
        self.assertFalse(os.path.exists(app._session_path(old["id"])))
        self.assertFalse(os.path.isdir(os.path.join(app.FILES_DIR, old["id"])))


# ---------------------------------------------------------------------------
# 分片上传 / 下载 / Range / 签名
# ---------------------------------------------------------------------------
class TestUploadDownload(Base):
    def test_small_upload_event_file_and_download(self):
        session = self.open_session("tok_alice")
        blob = "同学你好，这是测试文件。".encode("utf-8") * 10
        file_info = self.upload("tok_alice", session["id"], "汇报.txt", blob,
                                mime="text/plain")
        self.assertRegex(file_info["id"], r"^[0-9a-f]{16}$")
        self.assertEqual(file_info["size"], len(blob))
        self.assertEqual(file_info["name"], "汇报.txt")
        self.assertIn("/file/", file_info["downloadUrl"])
        self.assertIn("sig=", file_info["downloadUrl"])
        status, _hd, data = self.get(
            "/state?sessionId=%s" % session["id"], token="tok_alice")
        events = self.client.json_of(status, data)["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "file")
        self.assertEqual(events[0]["payload"]["fileId"], file_info["id"])
        self.assertEqual(events[0]["payload"]["name"], "汇报.txt")
        self.assertEqual(events[0]["payload"]["size"], len(blob))
        self.assertEqual(events[0]["payload"]["mime"], "text/plain")
        # v2：/state 读取时会对仍存在的文件重新签发下载链接（30min 有效），
        # 因此事件里的 URL 与 finish 返回的 URL 可能是不同签名，但都必须可用。
        state_url = events[0]["payload"]["downloadUrl"]
        self.assertIn("/file/", state_url)
        self.assertIn("sig=", state_url)
        status, _hd, data = self.download(state_url)
        self.assertEqual(status, 200)
        self.assertEqual(data, blob)
        status, headers, data = self.download(file_info["downloadUrl"])
        self.assertEqual(status, 200)
        self.assertEqual(data, blob)
        self.assertEqual(headers.get("content-type"), "text/plain")
        self.assertIn("attachment", headers.get("content-disposition", ""))
        self.assertIn("filename*=UTF-8''", headers.get("content-disposition", ""))
        self.assertEqual(headers.get("accept-ranges"), "bytes")

    def test_state_resigns_file_download_urls(self):
        """/state 读取时对仍存在的文件重签下载 URL（3 天文件保留的关键）。"""
        session = self.open_session("tok_alice")
        blob = b"resign-me" * 100
        file_info = self.upload("tok_alice", session["id"], "旧文件.bin", blob)
        expired_exp = int(time.time() * 1000) - 1000
        stale_url = "/file/%s?s=%s&exp=%d&sig=%s" % (
            file_info["id"], session["id"], expired_exp,
            app._sign(file_info["id"], session["id"], expired_exp))
        with app._LOCK:
            sess = app._load_session(session["id"])
            for ev in sess["events"]:
                if ev["kind"] == "file":
                    ev["payload"]["downloadUrl"] = stale_url
            app._save_session(sess)
        # 旧（过期）链接确实不可用
        self.assertEqual(self.download(stale_url)[0], 403)
        # /state 返回重新签发的链接：exp 在未来且可直接下载
        status, payload = self.state("tok_alice", session["id"])
        self.assertEqual(status, 200)
        fresh = payload["events"][0]["payload"]["downloadUrl"]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(fresh).query)
        self.assertGreater(int(query["exp"][0]), int(time.time() * 1000))
        status, _hd, data = self.download(fresh)
        self.assertEqual(status, 200)
        self.assertEqual(data, blob)
        # 事件本身（磁盘上的）不被修改：只影响本次响应
        with app._LOCK:
            sess = app._load_session(session["id"])
            self.assertEqual(sess["events"][0]["payload"]["downloadUrl"], stale_url)

    def test_utf8_filename_in_content_disposition(self):
        session = self.open_session("tok_alice")
        file_info = self.upload("tok_alice", session["id"], "../../班级 汇报.pdf",
                                b"%PDF-1.4 test", mime="application/pdf")
        self.assertEqual(file_info["name"], "班级 汇报.pdf")
        status, headers, data = self.download(file_info["downloadUrl"])
        self.assertEqual(status, 200)
        disposition = headers.get("content-disposition", "")
        self.assertIn("filename*=UTF-8''", disposition)
        self.assertIn(urllib.parse.quote("班级 汇报.pdf", safe=""), disposition)
        self.assertNotIn("..%2F", disposition)
        self.assertNotIn("../", disposition)

    def test_big_file_20mb_three_chunks_sha256(self):
        session = self.open_session("tok_alice")
        # 20 MiB 确定性内容：3 片（8MiB + 8MiB + 4MiB，超过单分片 2 倍）
        blob = bytes(range(256)) * 81920
        self.assertEqual(len(blob), 20 * 1024 * 1024)
        started = time.time()
        file_info = self.upload("tok_alice", session["id"], "大屏素材.bin", blob)
        upload_seconds = time.time() - started
        self.assertEqual(file_info["size"], len(blob))
        self.assertEqual(file_info["mime"], "application/octet-stream")
        status, headers, data = self.download(file_info["downloadUrl"])
        self.assertEqual(status, 200)
        self.assertEqual(len(data), len(blob))
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         hashlib.sha256(blob).hexdigest())
        self.assertLess(upload_seconds, 30)
        # 服务端只保留一个文件，且分片目录已清理
        files_dir = os.path.join(app.FILES_DIR, session["id"])
        self.assertEqual(os.listdir(files_dir), [file_info["id"] + ".bin"])
        self.assertEqual(os.listdir(app.UPLOAD_DIR), [])

    def test_chunk_index_out_of_range(self):
        session = self.open_session("tok_alice")
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": session["id"], "name": "a.bin", "size": 4,
            "mime": "application/octet-stream", "totalChunks": 1}, token="tok_alice")
        upload_id = self.client.json_of(status, data)["uploadId"]
        status, _hd, data = self.req(
            "POST", "/upload/chunk?uploadId=%s&index=1" % upload_id,
            body=b"abcd", token="tok_alice")
        self.fail_payload(self, status, data, 400, "范围")

    def test_chunk_without_content_length_411(self):
        session = self.open_session("tok_alice")
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": session["id"], "name": "a.bin", "size": 4,
            "mime": "application/octet-stream", "totalChunks": 1}, token="tok_alice")
        upload_id = self.client.json_of(status, data)["uploadId"]
        status, _hd, data = self.client.request_without_length(
            "POST", "/upload/chunk?uploadId=%s&index=0" % upload_id,
            token="tok_alice")
        self.fail_payload(self, status, data, 411)

    def test_chunk_too_large_413(self):
        old_chunk, old_max = app.CHUNK_SIZE, app.CHUNK_BODY_MAX
        app.CHUNK_SIZE, app.CHUNK_BODY_MAX = 32, 32
        try:
            session = self.open_session("tok_alice")
            status, _hd, data = self.post_json("/upload/init", {
                "sessionId": session["id"], "name": "a.bin", "size": 33,
                "mime": "application/octet-stream", "totalChunks": 2},
                token="tok_alice")
            upload_id = self.client.json_of(status, data)["uploadId"]
            status, _hd, data = self.req(
                "POST", "/upload/chunk?uploadId=%s&index=0" % upload_id,
                body=b"x" * 33, token="tok_alice")
            self.fail_payload(self, status, data, 413)
        finally:
            app.CHUNK_SIZE, app.CHUNK_BODY_MAX = old_chunk, old_max

    def test_finish_incomplete_400(self):
        session = self.open_session("tok_alice")
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": session["id"], "name": "a.bin", "size": 8,
            "mime": "application/octet-stream", "totalChunks": 2}, token="tok_alice")
        upload_id = self.client.json_of(status, data)["uploadId"]
        self.req("POST", "/upload/chunk?uploadId=%s&index=0" % upload_id,
                 body=b"abcd", token="tok_alice")
        status, _hd, data = self.post_json("/upload/finish", {
            "sessionId": session["id"], "uploadId": upload_id}, token="tok_alice")
        self.fail_payload(self, status, data, 400, "分片")

    def test_finish_size_mismatch_400(self):
        session = self.open_session("tok_alice")
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": session["id"], "name": "a.bin", "size": 3,
            "mime": "application/octet-stream", "totalChunks": 1}, token="tok_alice")
        upload_id = self.client.json_of(status, data)["uploadId"]
        self.req("POST", "/upload/chunk?uploadId=%s&index=0" % upload_id,
                 body=b"abcd", token="tok_alice")
        status, _hd, data = self.post_json("/upload/finish", {
            "sessionId": session["id"], "uploadId": upload_id}, token="tok_alice")
        self.fail_payload(self, status, data, 400, "大小")

    def test_upload_foreign_account_403(self):
        alice = self.open_session("tok_alice")
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": alice["id"], "name": "a.bin", "size": 4,
            "mime": "application/octet-stream", "totalChunks": 1}, token="tok_bob")
        self.fail_payload(self, status, data, 403, "无权")

    def test_upload_finish_by_foreign_upload_id_403(self):
        alice = self.open_session("tok_alice")
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": alice["id"], "name": "a.bin", "size": 4,
            "mime": "application/octet-stream", "totalChunks": 1}, token="tok_alice")
        upload_id = self.client.json_of(status, data)["uploadId"]
        status, _hd, data = self.post_json("/upload/finish", {
            "sessionId": alice["id"], "uploadId": upload_id}, token="tok_bob")
        self.fail_payload(self, status, data, 403, "无权")

    def test_upload_bad_upload_id_400(self):
        self.open_session("tok_alice")
        status, _hd, data = self.req(
            "POST", "/upload/chunk?uploadId=zzz&index=0", body=b"x",
            token="tok_alice")
        self.fail_payload(self, status, data, 400)

    def test_download_head(self):
        session = self.open_session("tok_alice")
        blob = b"0123456789"
        file_info = self.upload("tok_alice", session["id"], "a.bin", blob)
        parts = urllib.parse.urlsplit(file_info["downloadUrl"])
        path = parts.path + "?" + parts.query
        status, headers, data = self.req("HEAD", path)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("content-length"), str(len(blob)))
        self.assertEqual(data, b"")
        self.assertEqual(headers.get("accept-ranges"), "bytes")

    def test_download_range_206(self):
        session = self.open_session("tok_alice")
        blob = bytes(range(256)) * 4
        file_info = self.upload("tok_alice", session["id"], "range.bin", blob)
        status, headers, data = self.download(
            file_info["downloadUrl"], headers={"Range": "bytes=10-19"})
        self.assertEqual(status, 206)
        self.assertEqual(data, blob[10:20])
        self.assertEqual(headers.get("content-range"),
                         "bytes 10-19/%d" % len(blob))
        self.assertEqual(headers.get("content-length"), "10")

    def test_download_suffix_range(self):
        session = self.open_session("tok_alice")
        blob = b"abcdefghij"
        file_info = self.upload("tok_alice", session["id"], "s.bin", blob)
        status, headers, data = self.download(
            file_info["downloadUrl"], headers={"Range": "bytes=-4"})
        self.assertEqual(status, 206)
        self.assertEqual(data, b"ghij")
        self.assertEqual(headers.get("content-range"), "bytes 6-9/10")

    def test_download_invalid_range_416(self):
        session = self.open_session("tok_alice")
        file_info = self.upload("tok_alice", session["id"], "a.bin", b"0123456789")
        status, headers, _data = self.download(
            file_info["downloadUrl"], headers={"Range": "bytes=100-200"})
        self.assertEqual(status, 416)
        self.assertEqual(headers.get("content-range"), "bytes */10")

    def test_download_inline_disposition(self):
        session = self.open_session("tok_alice")
        file_info = self.upload("tok_alice", session["id"], "图片.png",
                                b"\x89PNG-test", mime="image/png")
        status, headers, _data = self.download(
            file_info["downloadUrl"] + "&inline=1")
        self.assertEqual(status, 200)
        self.assertIn("inline", headers.get("content-disposition", ""))

    def test_download_expired_403(self):
        session = self.open_session("tok_alice")
        blob = b"expired"
        file_info = self.upload("tok_alice", session["id"], "a.bin", blob)
        exp = int(time.time() * 1000) - 1000
        sig = app._sign(file_info["id"], session["id"], exp)
        url = "/file/%s?s=%s&exp=%d&sig=%s" % (
            file_info["id"], session["id"], exp, sig)
        status, _hd, data = self.get(url)
        self.fail_payload(self, status, data, 403, "过期")

    def test_download_tampered_signature_403(self):
        session = self.open_session("tok_alice")
        file_info = self.upload("tok_alice", session["id"], "a.bin", b"x")
        exp = int(time.time() * 1000) + 60000
        url = "/file/%s?s=%s&exp=%d&sig=%s" % (
            file_info["id"], session["id"], exp, "0" * 64)
        status, _hd, data = self.get(url)
        self.fail_payload(self, status, data, 403, "签名")

    def test_download_unknown_file_404(self):
        session = self.open_session("tok_alice")
        exp = int(time.time() * 1000) + 60000
        file_id = "f" * 16
        sig = app._sign(file_id, session["id"], exp)
        status, _hd, data = self.get(
            "/file/%s?s=%s&exp=%d&sig=%s" % (file_id, session["id"], exp, sig))
        self.fail_payload(self, status, data, 404)

    def test_download_path_traversal_rejected(self):
        session = self.open_session("tok_alice")
        evil = [
            "/file/..%2F..%2Fetc%2Fpasswd?s=" + session["id"],
            "/file/" + ("a" * 16) + "/../x?s=" + session["id"],
            "/file/..%00x?s=" + session["id"],
        ]
        for path in evil:
            status, _hd, data = self.get(path)
            self.assertIn(status, (400, 403, 404), data[:200])


# ---------------------------------------------------------------------------
# 限制 / 文本 / 指令 / 事件上限 / 清理
# ---------------------------------------------------------------------------
class TestFileDelete(Base):
    """临时云空间：单文件删除（DELETE /file/<fileId>）。"""

    def test_delete_file_removes_entity_and_emits_filedel(self):
        session = self.open_session("tok_alice")
        blob = b"delete-me-" * 100
        info = self.upload("tok_alice", session["id"], "待删除.bin", blob)
        path = os.path.join(app.FILES_DIR, session["id"], info["id"] + ".bin")
        self.assertTrue(os.path.isfile(path))
        status, _hd, data = self.req(
            "DELETE", "/file/%s?sessionId=%s" % (info["id"], session["id"]),
            token="tok_alice")
        self.assertEqual(status, 200, data[:200])
        payload = self.client.json_of(status, data)
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("deleted"))
        self.assertEqual(payload.get("size"), len(blob))
        self.assertFalse(os.path.exists(path))
        # /state：原 file 事件标 expired 无 downloadUrl；新增 filedel 事件
        status, state = self.state("tok_alice", session["id"])
        self.assertEqual(status, 200)
        kinds = [ev.get("kind") for ev in state["events"]]
        self.assertIn("filedel", kinds)
        file_ev = [ev for ev in state["events"] if ev.get("kind") == "file"][0]
        self.assertNotIn("downloadUrl", file_ev["payload"])
        self.assertTrue(file_ev["payload"].get("expired"))
        filedel = [ev for ev in state["events"] if ev.get("kind") == "filedel"][0]
        self.assertEqual(filedel["payload"]["fileId"], info["id"])
        # 旧下载链接失效（记录已移除 → 404；签名过期 → 403，两者都可接受）
        self.assertIn(self.download(info["downloadUrl"])[0], (403, 404))
        # 幂等：再删一次返回 deleted=false
        status, _hd, data = self.req(
            "DELETE", "/file/%s?sessionId=%s" % (info["id"], session["id"]),
            token="tok_alice")
        self.assertEqual(status, 200)
        self.assertFalse(self.client.json_of(status, data).get("deleted"))

    def test_delete_foreign_session_or_bad_id_rejected(self):
        alice = self.open_session("tok_alice")
        info = self.upload("tok_alice", alice["id"], "a.bin", b"aaa")
        self.open_session("tok_bob")
        status, _hd, data = self.req(
            "DELETE", "/file/%s?sessionId=%s" % (info["id"], alice["id"]),
            token="tok_bob")
        self.assertIn(status, (403, 404), data[:200])
        # 非法 fileId / 缺少身份
        self.assertEqual(self.req("DELETE", "/file/not-a-hex", token="tok_alice")[0], 404)
        self.assertEqual(self.req("DELETE", "/file/%s" % info["id"])[0], 401)
        # 原文件仍在（未被他人删除）
        self.assertTrue(os.path.isfile(
            os.path.join(app.FILES_DIR, alice["id"], info["id"] + ".bin")))


class TestPresence(Base):
    """大屏在线状态（/presence，2026-11-12 v2.3；v2.4 增加 sinceSeq 本次起点）。"""

    def test_requires_auth(self):
        self.assertEqual(self.get("/presence")[0], 401)
        self.assertEqual(self.post_json("/presence", {"stage": True})[0], 401)

    def test_no_session_is_offline(self):
        status, pay = self._get_json("/presence", "tok_alice")
        self.assertEqual(status, 200)
        self.assertTrue(pay.get("ok"))
        self.assertFalse(pay.get("stage"))

    def test_heartbeat_and_expiry_and_off(self):
        session = self.open_session("tok_alice")
        status, pay = self._get_json("/presence", "tok_alice")
        self.assertFalse(pay.get("stage"))
        status, _hd, data = self.post_json("/presence", {"stage": True}, token="tok_alice")
        self.assertEqual(status, 200)
        self.assertTrue(self.client.json_of(status, data).get("stage"))
        status, pay = self._get_json("/presence", "tok_alice")
        self.assertTrue(pay.get("stage"))
        # 心跳过期（stageAt 回拨 >30s）
        with app._LOCK:
            sess = app._load_session(session["id"])
            sess["stageAt"] = app._now_ms() - app.PRESENCE_TTL_MS - 1000
            app._save_session(sess)
        status, pay = self._get_json("/presence", "tok_alice")
        self.assertFalse(pay.get("stage"))
        # 立即下线
        self.post_json("/presence", {"stage": True}, token="tok_alice")
        status, _hd, data = self.post_json("/presence", {"stage": False}, token="tok_alice")
        self.assertFalse(self.client.json_of(status, data).get("stage"))
        status, pay = self._get_json("/presence", "tok_alice")
        self.assertFalse(pay.get("stage"))

    def test_same_sid_other_token_sees_online_other_account_not(self):
        self.open_session("tok_alice")
        self.post_json("/presence", {"stage": True}, token="tok_alice")
        status, pay = self._get_json("/presence", "tok_alice2")
        self.assertTrue(pay.get("stage"))
        self.open_session("tok_bob")
        status, pay = self._get_json("/presence", "tok_bob")
        self.assertFalse(pay.get("stage"))

    def test_session_payload_has_current_seq(self):
        """v2.4：/open、/mine 的 session.seq = 当前最大事件 seq（大屏据此从「现在」收事件）。"""
        session = self.open_session("tok_alice")
        self.assertIn("seq", session)
        self.assertEqual(int(session.get("seq") or 0), 0)
        sid = session["id"]
        self.post_json("/text", {"sessionId": sid, "text": "一"}, token="tok_alice")
        self.post_json("/text", {"sessionId": sid, "text": "二"}, token="tok_alice")
        status, pay = self._get_json("/mine", "tok_alice")
        self.assertEqual(int((pay.get("session") or {}).get("seq") or 0), 2)
        status, _hd, data = self.post_json("/open", {}, token="tok_alice")
        self.assertEqual(status, 200)
        self.assertEqual(int((self.client.json_of(status, data).get("session") or {}).get("seq") or 0), 2)

    def test_presence_since_seq_roundtrip(self):
        """v2.4：大屏打开时上报 sinceSeq，控制器读到同一 sinceSeq；下线后归零。"""
        session = self.open_session("tok_alice")
        sid = session["id"]
        for t in ("甲", "乙", "丙"):
            self.post_json("/text", {"sessionId": sid, "text": t}, token="tok_alice")
        # 打开大屏时已存在 3 条历史；大屏从 seq=2 开始收（只把之后的当“本次”）
        self.post_json("/presence", {"stage": True, "sinceSeq": 2}, token="tok_alice")
        status, pay = self._get_json("/presence", "tok_alice")
        self.assertTrue(pay.get("stage"))
        self.assertEqual(int(pay.get("sinceSeq")), 2)
        self.assertEqual(int(pay.get("stageSince")), 2)
        # 其它同账号 token 读到同一个值
        status, pay2 = self._get_json("/presence", "tok_alice2")
        self.assertEqual(int(pay2.get("sinceSeq")), 2)
        # 旧页面不带 sinceSeq：服务端取当前 seq（向后兼容）
        self.post_json("/presence", {"stage": True}, token="tok_alice")
        status, pay = self._get_json("/presence", "tok_alice")
        self.assertEqual(int(pay.get("sinceSeq")), 3)
        # 下线：stage/sinceSeq 都归零，但会话与文件保留（72h 云空间语义）
        self.post_json("/presence", {"stage": False}, token="tok_alice")
        status, pay = self._get_json("/presence", "tok_alice")
        self.assertFalse(pay.get("stage"))
        self.assertEqual(int(pay.get("sinceSeq")), 0)
        status, mine = self._get_json("/mine", "tok_alice")
        self.assertTrue((mine.get("session") or {}).get("id"))
        # sinceSeq 非法/越界：归一化到 [0, 当前 seq]
        self.post_json("/presence", {"stage": True, "sinceSeq": -5}, token="tok_alice")
        status, pay = self._get_json("/presence", "tok_alice")
        self.assertEqual(int(pay.get("sinceSeq")), 0)
        self.post_json("/presence", {"stage": True, "sinceSeq": 999999}, token="tok_alice")
        status, pay = self._get_json("/presence", "tok_alice")
        self.assertEqual(int(pay.get("sinceSeq")), 3)

    def _get_json(self, path, token):
        status, _hd, data = self.get(path, token=token)
        return status, self.client.json_of(status, data)


class TestLimitsAndText(Base):
    def _init(self, token, session_id, name, size, total_chunks=None):
        total_chunks = total_chunks or max(
            1, (int(size) + app.CHUNK_SIZE - 1) // app.CHUNK_SIZE)
        return self.post_json("/upload/init", {
            "sessionId": session_id, "name": name, "size": int(size),
            "mime": "application/octet-stream",
            "totalChunks": total_chunks}, token=token)

    def test_default_unlimited_file_size_over_old_2gib(self):
        """v2：默认无单文件上限 —— 声明 > 旧上限 2GiB 的元数据也能 init（不再 413）。"""
        session = self.open_session("tok_alice")
        size = 2 * 1024 ** 3 + 8 * 1024 ** 2          # 旧上限 +8MiB
        with self.disk_free(100 * 1024 ** 3):
            status, _hd, data = self._init("tok_alice", session["id"],
                                           "超大素材.iso", size)
        payload = self.client.json_of(status, data)
        self.assertEqual(status, 200, data[:300])
        self.assertTrue(payload.get("ok"))
        self.assertRegex(payload["uploadId"], r"^[0-9a-f]{16}$")
        self.assertEqual(payload["chunkSize"], app.CHUNK_SIZE)
        self.assertTrue(os.path.isdir(app._upload_dir(payload["uploadId"])))
        # 关闭会话 → 该会话未完成分片一并删除（元数据不残留）
        self.assertEqual(self.post_json("/close", {}, token="tok_alice")[0], 200)
        self.assertEqual(os.listdir(app.UPLOAD_DIR), [])

    def test_default_unlimited_session_bytes_over_old_8gib(self):
        """v2：默认无单会话总量上限 —— 已声明 5GiB 后再声明 4GiB 仍可 init。"""
        session = self.open_session("tok_alice")
        with self.disk_free(100 * 1024 ** 3):
            first = self._init("tok_alice", session["id"], "a.iso", 5 * 1024 ** 3)
            second = self._init("tok_alice", session["id"], "b.iso", 4 * 1024 ** 3)
        self.assertEqual(first[0], 200, first[2][:300])
        self.assertEqual(second[0], 200, second[2][:300])
        self.assertNotEqual(self.client.json_of(first[0], first[2])["uploadId"],
                            self.client.json_of(second[0], second[2])["uploadId"])
        self.assertEqual(self.post_json("/close", {}, token="tok_alice")[0], 200)
        self.assertEqual(os.listdir(app.UPLOAD_DIR), [])

    def test_file_limit_env_override_still_413(self):
        """env 覆盖上限仍生效（DROP_MAX_FILE_BYTES>0 时照旧 413）。"""
        old = app.MAX_FILE_BYTES
        app.MAX_FILE_BYTES = 1024 * 1024
        try:
            session = self.open_session("tok_alice")
            status, _hd, data = self._init("tok_alice", session["id"],
                                           "over.bin", app.MAX_FILE_BYTES + 1)
            self.fail_payload(self, status, data, 413, "上限")
        finally:
            app.MAX_FILE_BYTES = old

    def test_session_bytes_limit_env_override_still_413(self):
        old = app.MAX_SESSION_BYTES
        app.MAX_SESSION_BYTES = 1000
        try:
            session = self.open_session("tok_alice")
            status, _hd, data = self._init("tok_alice", session["id"],
                                           "b.bin", 2000)
            self.fail_payload(self, status, data, 413, "总量")
        finally:
            app.MAX_SESSION_BYTES = old

    def test_max_file_and_session_bytes_env_override_are_optional(self):
        """0 = 不限（默认）；负值同样视作不限，不会误伤正常上传。"""
        old_file, old_sess = app.MAX_FILE_BYTES, app.MAX_SESSION_BYTES
        app.MAX_FILE_BYTES, app.MAX_SESSION_BYTES = -1, -1
        try:
            session = self.open_session("tok_alice")
            with self.disk_free(100 * 1024 ** 3):
                status, _hd, data = self._init("tok_alice", session["id"],
                                               "ok.bin", 3 * 1024 ** 3)
            self.assertEqual(status, 200, data[:300])
        finally:
            app.MAX_FILE_BYTES, app.MAX_SESSION_BYTES = old_file, old_sess

    # -- 磁盘余量（唯一硬限制） ------------------------------------------
    def test_disk_reserve_init_507(self):
        session = self.open_session("tok_alice")
        with self.disk_free(app.DISK_RESERVE + 100):
            status, _hd, data = self._init("tok_alice", session["id"],
                                           "big.bin", 1024)
        self.fail_payload(self, status, data, 507, "磁盘")

    def test_disk_reserve_chunk_507(self):
        session = self.open_session("tok_alice")
        with self.disk_free(100 * 1024 ** 3):
            status, _hd, data = self._init("tok_alice", session["id"],
                                           "a.bin", 4)
            upload_id = self.client.json_of(status, data)["uploadId"]
        with self.disk_free(app.DISK_RESERVE + 1):
            status, _hd, data = self.req(
                "POST", "/upload/chunk?uploadId=%s&index=0" % upload_id,
                body=b"abcd", token="tok_alice")
        self.fail_payload(self, status, data, 507, "磁盘")
        # 失败分片不落盘（没有 0.part）
        self.assertEqual(os.listdir(app._upload_dir(upload_id)), ["meta.json"])
        self.post_json("/close", {}, token="tok_alice")

    def test_disk_reserve_finish_507(self):
        session = self.open_session("tok_alice")
        with self.disk_free(100 * 1024 ** 3):
            status, _hd, data = self._init("tok_alice", session["id"], "a.bin", 4)
            upload_id = self.client.json_of(status, data)["uploadId"]
            self.assertEqual(self.req(
                "POST", "/upload/chunk?uploadId=%s&index=0" % upload_id,
                body=b"abcd", token="tok_alice")[0], 200)
        with self.disk_free(app.DISK_RESERVE + 1):
            status, _hd, data = self.post_json("/upload/finish", {
                "sessionId": session["id"], "uploadId": upload_id},
                token="tok_alice")
        self.fail_payload(self, status, data, 507, "磁盘")
        # 失败不留半成品文件（拼接前就拒绝，连会话文件目录都不会建）
        files_dir = os.path.join(app.FILES_DIR, session["id"])
        self.assertFalse(os.path.isdir(files_dir))
        self.post_json("/close", {}, token="tok_alice")

    def test_session_files_limit_413(self):
        old = app.MAX_FILES
        app.MAX_FILES = 2
        try:
            session = self.open_session("tok_alice")
            self.upload("tok_alice", session["id"], "1.bin", b"1")
            self.upload("tok_alice", session["id"], "2.bin", b"2")
            status, _hd, data = self.post_json("/upload/init", {
                "sessionId": session["id"], "name": "3.bin", "size": 3,
                "mime": "application/octet-stream", "totalChunks": 1},
                token="tok_alice")
            self.fail_payload(self, status, data, 413, "文件数")
        finally:
            app.MAX_FILES = old

    def test_text_limits(self):
        session = self.open_session("tok_alice")
        for bad in ("", "x" * (app.TEXT_MAX + 1)):
            status, _hd, data = self.post_json(
                "/text", {"sessionId": session["id"], "text": bad},
                token="tok_alice")
            self.fail_payload(self, status, data, 400, "文字")
        status, _hd, data = self.post_json(
            "/text", {"sessionId": session["id"], "text": "x" * app.TEXT_MAX},
            token="tok_alice")
        self.assertEqual(status, 200)
        self.assertEqual(self.client.json_of(status, data)["seq"], 1)

    def test_cmd_whitelist_all_ops(self):
        session = self.open_session("tok_alice")
        expected_seq = 0
        for op in sorted(app.CMD_OPS):
            expected_seq += 1
            status, _hd, data = self.post_json(
                "/cmd", {"sessionId": session["id"], "op": op,
                         "args": {"from": "test"}}, token="tok_alice")
            self.assertEqual(status, 200, data[:200])
            self.assertEqual(self.client.json_of(status, data)["seq"], expected_seq)
        status, _hd, data = self.post_json(
            "/cmd", {"sessionId": session["id"], "op": "rm_rf", "args": {}},
            token="tok_alice")
        self.fail_payload(self, status, data, 400, "不支持")
        self.assertEqual(len(app.CMD_OPS), 9)

    def test_cmd_args_too_large_413(self):
        session = self.open_session("tok_alice")
        status, _hd, data = self.post_json(
            "/cmd", {"sessionId": session["id"], "op": "toast",
                     "args": {"text": "x" * 70000}}, token="tok_alice")
        self.fail_payload(self, status, data, 413, "参数")

    def test_events_capped_at_500(self):
        session = self.open_session("tok_alice")
        for i in range(505):
            status, _hd, _data = self.post_json(
                "/text", {"sessionId": session["id"], "text": "n%d" % i},
                token="tok_alice")
            self.assertEqual(status, 200)
        with app._LOCK:
            sess = app._load_session(session["id"])
            self.assertEqual(len(sess["events"]), 500)
            self.assertEqual(sess["seq"], 505)
        status, payload = self.state("tok_alice", session["id"])
        self.assertEqual(len(payload["events"]), 500)
        self.assertEqual(payload["events"][0]["seq"], 6)
        self.assertEqual(payload["events"][-1]["seq"], 505)

    def test_health_counts_files_and_bytes(self):
        session = self.open_session("tok_alice")
        self.upload("tok_alice", session["id"], "a.bin", b"x" * 100)
        self.upload("tok_alice", session["id"], "b.bin", b"y" * 200)
        health = self.client.json_of(200, self.get("/__health")[2])
        self.assertEqual(health["sessions"], 1)
        self.assertEqual(health["files"], 2)
        self.assertEqual(health["bytes"], 300)

    def test_cleanup_expired_session_removes_files(self):
        session = self.open_session("tok_alice")
        self.upload("tok_alice", session["id"], "a.bin", b"cleanup-me")
        # v2.1：文件与会话活动都超过 72h → 文件先过期、会话空闲回收（整目录删除）
        self.age_session(session["id"], app.TTL_SEC + 60)
        app.cleanup_once()
        self.assertFalse(os.path.exists(app._session_path(session["id"])))
        self.assertFalse(os.path.isdir(os.path.join(app.FILES_DIR, session["id"])))
        status, _hd, data = self.get("/mine", token="tok_alice")
        self.assertIsNone(self.client.json_of(status, data)["session"])
        health = self.client.json_of(200, self.get("/__health")[2])
        self.assertEqual(health["sessions"], 0)
        self.assertEqual(health["files"], 0)

    def test_cleanup_removes_orphan_upload(self):
        session = self.open_session("tok_alice")
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": session["id"], "name": "a.bin", "size": 4,
            "mime": "application/octet-stream", "totalChunks": 1},
            token="tok_alice")
        upload_id = self.client.json_of(status, data)["uploadId"]
        self.assertTrue(os.path.isdir(os.path.join(app.UPLOAD_DIR, upload_id)))
        with app._LOCK:
            app._delete_session_locked(session["id"])
        app.cleanup_once()
        self.assertFalse(os.path.isdir(os.path.join(app.UPLOAD_DIR, upload_id)))

    def test_cleanup_reclaims_inactive_unfinished_upload_after_upload_ttl(self):
        """未完成分片按 DROP_UPLOAD_TTL_SEC（默认 24h）回收，不等会话 72h。"""
        session = self.open_session("tok_alice")
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": session["id"], "name": "a.iso", "size": 4,
            "mime": "application/octet-stream", "totalChunks": 1},
            token="tok_alice")
        upload_id = self.client.json_of(status, data)["uploadId"]
        old_ms = app._now_ms() - (app.UPLOAD_TTL_SEC + 3600) * 1000
        with app._LOCK:
            meta = app._load_upload_meta(upload_id)
            meta["createdAt"] = old_ms
            app._save_upload_meta(upload_id, meta)
        meta_path = os.path.join(app._upload_dir(upload_id), "meta.json")
        old_ts = old_ms / 1000.0
        os.utime(meta_path, (old_ts, old_ts))
        app.cleanup_once()
        self.assertFalse(os.path.isdir(app._upload_dir(upload_id)))
        # 会话本身 72h 内仍有效
        self.assertTrue(os.path.exists(app._session_path(session["id"])))

    def test_cleanup_keeps_recent_unfinished_upload(self):
        session = self.open_session("tok_alice")
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": session["id"], "name": "a.iso", "size": 4,
            "mime": "application/octet-stream", "totalChunks": 1},
            token="tok_alice")
        upload_id = self.client.json_of(status, data)["uploadId"]
        app.cleanup_once()
        self.assertTrue(os.path.isdir(app._upload_dir(upload_id)))
        self.post_json("/close", {}, token="tok_alice")
        self.assertFalse(os.path.isdir(app._upload_dir(upload_id)))

    def test_total_chunks_boundary(self):
        """分片数上限保留（1..65536 = 8MiB×65536 = 512GiB 声明上限，超过磁盘实际可用）。"""
        session = self.open_session("tok_alice")
        with self.disk_free(2 * 1024 ** 4):
            status, _hd, data = self._init(
                "tok_alice", session["id"], "max.iso", 4,
                total_chunks=app.MAX_TOTAL_CHUNKS)
            self.assertEqual(status, 200, data[:300])
            status, _hd, data = self._init(
                "tok_alice", session["id"], "too-many.iso", 4,
                total_chunks=app.MAX_TOTAL_CHUNKS + 1)
        self.fail_payload(self, status, data, 400, "分片数")
        self.post_json("/close", {}, token="tok_alice")


# ---------------------------------------------------------------------------
# v2.1：逐文件 TTL（自上传完成起 72h）+ 会话空闲滑动 TTL
# ---------------------------------------------------------------------------
class TestPerFileTtl(Base):
    def test_file_a_expires_while_file_b_survives(self):
        """文件 A 上传后 >72h 被删除；之后上传的文件 B 仍在（逐文件独立过期）。"""
        session = self.open_session("tok_alice")
        file_a = self.upload("tok_alice", session["id"], "旧文件.bin", b"A" * 1000)
        self.age_file(session["id"], file_a["id"], app.TTL_SEC + 60)
        file_b = self.upload("tok_alice", session["id"], "新文件.bin", b"B" * 2000)
        # 清理前：A 的实体还在但已过期 → 下载应 404（按文件 at 判定，不等清理线程）
        self.assertEqual(self.download(file_a["downloadUrl"])[0], 404)
        app.cleanup_once()
        files_dir = os.path.join(app.FILES_DIR, session["id"])
        self.assertEqual(sorted(os.listdir(files_dir)), [file_b["id"] + ".bin"])
        # B 仍可下载、sha 一致；会话仍在
        status, _hd, data = self.download(file_b["downloadUrl"])
        self.assertEqual(status, 200)
        self.assertEqual(data, b"B" * 2000)
        health = self.client.json_of(200, self.get("/__health")[2])
        self.assertEqual(health["files"], 1)
        self.assertEqual(health["bytes"], 2000)
        # /state：A 事件保留 seq 但标记 expired、无 downloadUrl；B 有可用链接
        status, payload = self.state("tok_alice", session["id"])
        self.assertEqual(status, 200)
        f_events = [ev for ev in payload["events"] if ev["kind"] == "file"]
        self.assertEqual(len(f_events), 2)
        ev_a, ev_b = f_events[0], f_events[1]
        self.assertEqual(ev_a["payload"]["fileId"], file_a["id"])
        self.assertIs(ev_a["payload"].get("expired"), True)
        self.assertNotIn("downloadUrl", ev_a["payload"])
        self.assertEqual(ev_b["payload"]["fileId"], file_b["id"])
        self.assertNotIn("expired", ev_b["payload"])
        status, _hd, data = self.download(ev_b["payload"]["downloadUrl"])
        self.assertEqual(status, 200)
        self.assertEqual(data, b"B" * 2000)

    def test_cleanup_removes_expired_file_entity_and_table_row(self):
        session = self.open_session("tok_alice")
        file_a = self.upload("tok_alice", session["id"], "a.bin", b"a" * 10)
        self.age_file(session["id"], file_a["id"], app.TTL_SEC + 1)
        app.cleanup_once()
        with app._LOCK:
            sess = app._load_session(session["id"])
            self.assertEqual(sess["files"], [])
        files_dir = os.path.join(app.FILES_DIR, session["id"])
        self.assertEqual(os.listdir(files_dir), [])

    def test_session_idle_reclaimed_without_files(self):
        session = self.open_session("tok_alice")
        self.age_session(session["id"], app.TTL_SEC + 60, age_files=False)
        app.cleanup_once()
        self.assertFalse(os.path.exists(app._session_path(session["id"])))
        status, _hd, data = self.get("/mine", token="tok_alice")
        self.assertIsNone(self.client.json_of(status, data)["session"])

    def test_session_with_live_file_survives_idle_then_expires(self):
        """有未过期文件时会话不因空闲被删；文件过期后再按空闲规则收尾。"""
        session = self.open_session("tok_alice")
        self.upload("tok_alice", session["id"], "a.bin", b"keep")
        # 会话空闲已超 72h，但文件刚上传 → 会话必须保留、文件可下载
        self.age_session(session["id"], app.TTL_SEC + 60, age_files=False)
        app.cleanup_once()
        self.assertTrue(os.path.exists(app._session_path(session["id"])))
        status, payload = self.state("tok_alice", session["id"])
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["events"]), 1)
        self.assertIn("downloadUrl", payload["events"][0]["payload"])
        # 现在把文件也变老 → 文件过期 + 会话空闲超时 → 整体回收
        self.age_session(session["id"], app.TTL_SEC + 60, age_files=True)
        app.cleanup_once()
        self.assertFalse(os.path.exists(app._session_path(session["id"])))

    def test_activity_slides_session_idle_ttl(self):
        session = self.open_session("tok_alice")
        self.age_session(session["id"], app.TTL_SEC // 2, age_files=False)
        # state 读取本身不算活动：仍临近过期，但未过期
        status, _hd, _data = self.get(
            "/state?sessionId=%s" % session["id"], token="tok_alice")
        self.assertEqual(status, 200)
        # 文字/上传算活动 → 滑动续期到 now + TTL
        self.post_json("/text", {"sessionId": session["id"], "text": "活动一下"},
                       token="tok_alice")
        status, _hd, data = self.get("/mine", token="tok_alice")
        payload = self.client.json_of(status, data)
        expires = int(payload["session"]["expiresAt"])
        remain = expires - int(time.time() * 1000)
        self.assertGreaterEqual(remain, app.TTL_SEC * 1000 - 5000)
        with app._LOCK:
            sess = app._load_session(session["id"])
            last = int(sess["lastActivityAt"])
        self.assertGreater(last, app._now_ms() - 5000)

    def test_open_also_slides_and_expires_reflects_file(self):
        from_file = self.open_session("tok_alice")
        file_info = self.upload("tok_alice", from_file["id"], "a.bin", b"x")
        # 会话空闲时刻：activity 更新后 → expiresAt 跟随最后活动 + TTL
        self.age_session(from_file["id"], app.TTL_SEC // 2, age_files=False)
        session2 = self.open_session("tok_alice")       # /open 算活动 → 续期
        self.assertEqual(session2["id"], from_file["id"])
        self.assertGreater(session2["expiresAt"],
                           int(time.time() * 1000) + app.TTL_SEC * 1000 - 10000)
        # 文件 TTL 独立：文件较老时 expiresAt 仍取最大值（文件过期时间）
        self.age_file(from_file["id"], file_info["id"], 3600)
        status, _hd, data = self.get("/mine", token="tok_alice")
        mine = self.client.json_of(status, data)["session"]
        self.assertGreaterEqual(int(mine["expiresAt"]),
                                int(time.time() * 1000) + app.TTL_SEC * 1000 - 7200 * 1000)


# ---------------------------------------------------------------------------
# validate_token → 本机假网关协议（真实 CloudBase 行为在此替身）
# ---------------------------------------------------------------------------
class TestGatewayAuth(Base):
    def setUp(self):
        Base.setUp(self)
        app.GATEWAY = FAKE_GATEWAY["base"]
        app.PUBLISH_KEY = "pk-test"
        app.validate_token = ORIG_VALIDATE
        app._AUTH_CACHE.clear()

    def tearDown(self):
        app.validate_token = fake_validate
        app.PUBLISH_KEY = "test-publish-key"
        app.GATEWAY = "http://127.0.0.1:9/unreachable/"
        app._AUTH_CACHE.clear()

    def _queue(self, status, payload):
        with app._LOCK:
            FAKE_GATEWAY["queue"].append((status, payload))

    def test_valid_whoami_parsed_and_headers_sent(self):
        self._queue(200, {"ok": True, "sid": "sid_x", "seat": 9, "name": "张三"})
        info = app.validate_token("tok_gateway_valid")
        self.assertEqual(info, {"sid": "sid_x", "seat": 9, "name": "张三"})
        with app._LOCK:
            calls = list(FAKE_GATEWAY["calls"])
        self.assertEqual(len(calls), 1)
        sent = calls[0]
        self.assertTrue(sent["path"].endswith("/rpc/class_whoami"))
        self.assertEqual(sent["headers"].get("x-device-id"), "tok_gateway_valid")
        self.assertEqual(sent["headers"].get("authorization"), "Bearer pk-test")
        self.assertEqual(sent["body"], b"{}")

    def test_success_cached_for_120s(self):
        self._queue(200, {"ok": True, "sid": "sid_x", "name": "张三"})
        self._queue(200, {"ok": True, "sid": "sid_x", "name": "张三"})
        first = app.validate_token("tok_cache")
        second = app.validate_token("tok_cache")
        self.assertEqual(first, second)
        with app._LOCK:
            self.assertEqual(len(FAKE_GATEWAY["calls"]), 1)

    def test_ok_false_maps_to_401(self):
        self._queue(200, {"ok": False, "reason": "未登录"})
        with self.assertRaises(app.AuthError) as ctx:
            app.validate_token("tok_invalid")
        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(ctx.exception.reason, "未登录")

    def test_gateway_5xx_maps_to_503(self):
        self._queue(500, {"error": "boom"})
        with self.assertRaises(app.AuthError) as ctx:
            app.validate_token("tok_500")
        self.assertEqual(ctx.exception.status, 503)

    def test_gateway_bad_json_maps_to_503(self):
        self._queue(200, b"<html>not json</html>")
        with self.assertRaises(app.AuthError) as ctx:
            app.validate_token("tok_badjson")
        self.assertEqual(ctx.exception.status, 503)

    def test_gateway_ok_without_sid_maps_to_503(self):
        self._queue(200, {"ok": True, "name": "无sid"})
        with self.assertRaises(app.AuthError) as ctx:
            app.validate_token("tok_nosid")
        self.assertEqual(ctx.exception.status, 503)

    def test_gateway_unreachable_maps_to_503(self):
        app.GATEWAY = "http://127.0.0.1:1/unreachable/"
        with self.assertRaises(app.AuthError) as ctx:
            app.validate_token("tok_down")
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("鉴权服务", ctx.exception.reason)

    def test_503_end_to_end_through_api(self):
        self._queue(500, {"error": "boom"})
        status, _hd, data = self.get("/mine", token="tok_real_user")
        self.fail_payload(self, status, data, 503, "鉴权服务")

    def test_api_identity_cache_120s(self):
        """真实链路（服务端 validate_token + 假网关）：同 token 两次 API 只调一次网关。"""
        self._queue(200, {"ok": True, "sid": "sid_cache", "name": "缓存同学"})
        for _ in range(2):
            status, _hd, data = self.get("/mine", token="tok_cache_e2e")
            self.assertEqual(status, 200, data[:200])
            payload = self.client.json_of(status, data)
            self.assertTrue(payload["ok"])
        with app._LOCK:
            self.assertEqual(len(FAKE_GATEWAY["calls"]), 1)


# ---------------------------------------------------------------------------
# v2.5：鉴权失败分类（X-Drop-Reason）+ 失败缓存
# ---------------------------------------------------------------------------
class TestAuthFailKind(Base):
    def setUp(self):
        Base.setUp(self)
        app.GATEWAY = FAKE_GATEWAY["base"]
        app.PUBLISH_KEY = "pk-test"
        app.validate_token = ORIG_VALIDATE
        app._AUTH_CACHE.clear()

    def tearDown(self):
        app.validate_token = fake_validate
        app.PUBLISH_KEY = "test-publish-key"
        app.GATEWAY = "http://127.0.0.1:9/unreachable/"
        app._AUTH_CACHE.clear()

    def _queue(self, status, payload):
        with app._LOCK:
            FAKE_GATEWAY["queue"].append((status, payload))

    def _gateway_calls(self):
        with app._LOCK:
            return len(FAKE_GATEWAY["calls"])

    def test_gateway_reject_is_token_kind_and_cached(self):
        self._queue(200, {"ok": False, "reason": "身份已失效"})
        status, headers, data = self.get("/mine", token="tok_expired_1")
        self.assertEqual(status, 401)
        self.assertEqual(headers.get("x-drop-reason"), "token")
        payload = self.client.json_of(status, data)
        self.assertEqual(payload.get("reason"), "身份已失效")
        # 失败缓存：同 token 再请求不再打网关
        status2, headers2, _data2 = self.get("/mine", token="tok_expired_1")
        self.assertEqual(status2, 401)
        self.assertEqual(headers2.get("x-drop-reason"), "token")
        self.assertEqual(self._gateway_calls(), 1)

    def test_gateway_down_is_unavailable_kind(self):
        self._queue(500, {"error": "boom"})
        status, headers, data = self.get("/mine", token="tok_down_1")
        self.assertEqual(status, 503)
        self.assertEqual(headers.get("x-drop-reason"), "unavailable")
        self.fail_payload(self, status, data, 503, "鉴权服务")

    def test_fail_cache_expires_after_ttl(self):
        self._queue(200, {"ok": False, "reason": "身份已失效"})
        orig = app.AUTH_FAIL_TTL_SEC
        app.AUTH_FAIL_TTL_SEC = 0
        try:
            self.get("/mine", token="tok_expired_2")
            self._queue(200, {"ok": True, "sid": "sid_ok2", "name": "恢复"})
            status, headers, _data = self.get("/mine", token="tok_expired_2")
        finally:
            app.AUTH_FAIL_TTL_SEC = orig
        self.assertEqual(status, 200)
        self.assertFalse(headers.get("x-drop-reason"))

    def test_ok_after_success_not_marked(self):
        self._queue(200, {"ok": True, "sid": "sid_ok3", "name": "正常"})
        status, headers, _data = self.get("/mine", token="tok_ok_3")
        self.assertEqual(status, 200)
        self.assertFalse(headers.get("x-drop-reason"))


# ---------------------------------------------------------------------------
# v2.5：/state?all=1 返回「当前有效文件清单」（事件表截断/空事件也不丢文件）
# ---------------------------------------------------------------------------
class TestStateAll(Base):
    def _state_all(self, token, session_id, since=0):
        status, _hd, data = self.get(
            "/state?sessionId=%s&since=%d&all=1"
            % (urllib.parse.quote(session_id), since), token=token)
        self.assertEqual(status, 200, data[:200])
        return self.client.json_of(status, data)

    def test_files_listed_after_events_truncated(self):
        session = self.open_session("tok_alice")
        small = self.upload("tok_alice", session["id"], "小文件.txt", b"hello")
        big = self.upload("tok_alice", session["id"], "大文件.bin", b"y" * 9000)
        # 制造 600 条事件（> MAX_EVENTS 500）→ 两条 file 事件都被挤出窗口
        orig = app.MAX_EVENTS
        app.MAX_EVENTS = 25
        try:
            for i in range(40):
                status, _hd, _d = self.post_json(
                    "/text", {"sessionId": session["id"], "text": "t%d" % i},
                    token="tok_alice")
                self.assertEqual(status, 200)
        finally:
            app.MAX_EVENTS = orig
        # 旧口径（不带 all）：file 事件已不在窗口内 → 事件列表里看不到文件
        status, plain = self.state("tok_alice", session["id"], 0)
        self.assertEqual(status, 200)
        kinds = [ev["kind"] for ev in plain["events"]]
        self.assertNotIn("file", kinds)
        self.assertNotIn("files", plain)          # 不带 all 时保持 v2.4 形状
        # v2.5：all=1 仍能拿到两个有效文件 + 可用下载链接
        payload = self._state_all("tok_alice", session["id"], 0)
        names = sorted(f["name"] for f in payload["files"])
        self.assertEqual(names, sorted([small["name"], big["name"]]))
        for item in payload["files"]:
            self.assertTrue(item["downloadUrl"].startswith("http"))
            self.assertGreater(int(item["at"]), 0)
        # 下载链接可用（范围签名与普通下载一致）
        status, _hd, body = self.download(payload["files"][0]["downloadUrl"])
        self.assertEqual(status, 200)
        self.assertIn(len(body), (5, 9000))

    def test_files_and_expired_notice(self):
        session = self.open_session("tok_alice")
        keep = self.upload("tok_alice", session["id"], "保留.txt", b"keep")
        gone = self.upload("tok_alice", session["id"], "过期.bin", b"gone")
        payload = self._state_all("tok_alice", session["id"], 0)
        self.assertEqual(payload["expiredNotice"], 0)
        self.assertEqual(sorted(f["name"] for f in payload["files"]),
                         ["保留.txt", "过期.bin"])
        self.assertEqual(payload["session"]["seq"], 2)
        self.assertEqual(sorted(payload["fileSeq"].keys()),
                         sorted([keep["id"], gone["id"]]))
        # 让其中一个文件过期 → 有效清单只剩一个，expiredNotice 计数 1
        self.age_file(session["id"], gone["id"], app.TTL_SEC + 30)
        payload2 = self._state_all("tok_alice", session["id"], 0)
        self.assertEqual([f["name"] for f in payload2["files"]], ["保留.txt"])
        self.assertEqual(payload2["expiredNotice"], 1)

    def test_other_account_cannot_read_state_all(self):
        session = self.open_session("tok_alice")
        self.upload("tok_alice", session["id"], "a.txt", b"a")
        status, _hd, data = self.get(
            "/state?sessionId=%s&all=1" % session["id"], token="tok_bob")
        self.fail_payload(self, status, data, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
