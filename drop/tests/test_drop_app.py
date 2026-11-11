# -*- coding: utf-8 -*-
"""drop/tests/test_drop_app.py — 大屏临时互联服务（deploy/drop_app.py）本机单元测试

纯标准库 unittest，**不连真实 CloudBase**：
- 鉴权注入假校验器（替换 `drop_app.validate_token`），覆盖缺失/无效 token、同 sid 多 token 互见；
- 另有一组用本机假网关（http.server）直接测 `validate_token` 的网关协议：
  成功解析、120s 缓存、ok:false→401、5xx/坏 JSON/缺 sid/不可达→503（fail closed）；
- 覆盖 CORS、会话隔离、分片上传（含 20MiB 大文件 3 片）、下载 Range/HEAD/签名过期/篡改、
  文字/指令白名单、限制（413）、事件上限 500、TTL 清理、健康统计。

运行（web 目录）：
    python -m unittest drop.tests.test_drop_app -v
    python drop\\tests\\test_drop_app.py -v
"""
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
    def test_health_no_auth_and_shape(self):
        status, headers, data = self.get("/__health")
        self.assertEqual(status, 200)
        payload = self.client.json_of(status, data)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(set(payload.keys()),
                         {"ok", "version", "sessions", "files", "bytes"})
        self.assertEqual(payload["sessions"], 0)
        self.assertEqual(payload["files"], 0)
        self.assertEqual(payload["bytes"], 0)
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
        self.assertEqual(set(session.keys()), {"id", "code", "expiresAt", "createdAt"})
        self.assertRegex(session["id"], r"^[0-9a-f]{16}$")
        self.assertRegex(session["code"], r"^\d{6}$")
        now = int(time.time() * 1000)
        self.assertLessEqual(session["createdAt"], now)
        self.assertGreater(session["expiresAt"], now)

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
        with app._LOCK:
            sess = app._load_session(old["id"])
            sess["expiresAt"] = int(time.time() * 1000) - 1
            app._save_session(sess)
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
        self.assertEqual(events[0]["payload"]["downloadUrl"], file_info["downloadUrl"])
        status, headers, data = self.download(file_info["downloadUrl"])
        self.assertEqual(status, 200)
        self.assertEqual(data, blob)
        self.assertEqual(headers.get("content-type"), "text/plain")
        self.assertIn("attachment", headers.get("content-disposition", ""))
        self.assertIn("filename*=UTF-8''", headers.get("content-disposition", ""))
        self.assertEqual(headers.get("accept-ranges"), "bytes")

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
class TestLimitsAndText(Base):
    def test_file_too_large_413(self):
        session = self.open_session("tok_alice")
        status, _hd, data = self.post_json("/upload/init", {
            "sessionId": session["id"], "name": "huge.bin",
            "size": app.MAX_FILE_BYTES + 1, "mime": "application/octet-stream",
            "totalChunks": 1}, token="tok_alice")
        self.fail_payload(self, status, data, 413, "上限")

    def test_session_bytes_limit_413(self):
        old = app.MAX_SESSION_BYTES
        app.MAX_SESSION_BYTES = 1000
        try:
            session = self.open_session("tok_alice")
            status, _hd, data = self.post_json("/upload/init", {
                "sessionId": session["id"], "name": "b.bin", "size": 2000,
                "mime": "application/octet-stream", "totalChunks": 1},
                token="tok_alice")
            self.fail_payload(self, status, data, 413, "总量")
        finally:
            app.MAX_SESSION_BYTES = old

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
        with app._LOCK:
            sess = app._load_session(session["id"])
            sess["expiresAt"] = int(time.time() * 1000) - 1
            app._save_session(sess)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
