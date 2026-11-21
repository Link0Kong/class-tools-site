# -*- coding: utf-8 -*-
"""ECS 账号服务 · 二维码跨设备登录接口自检（deploy/account_app.py v1.2）

契约：web/docs/QR_LOGIN_CONTRACT.md
覆盖：
  - /__health 暴露 qr/qrTtl/version；
  - /qr/create 票据格式（128-bit t/k）、TTL 边界、CORS；
  - /qr/poll：wait → ok / deny / expired、错误 k → 404、未知票据 → expired；
  - /qr/authorize：无 token → 401；有效 token → 票据写入 fresh token/role/badge/is_admin；
    过期票据 → ticket_expired；重复授权 → already；
  - /qr/deny；OPTIONS 预检；
  - 票据只在内存、服务不返回手机 token/openid。

运行：python -m pytest web/deploy/tests/test_account_qr.py -q
（不访问外网：_whoami/_class_verify_full 全部 monkeypatch，数据库/网关 0 请求）
"""
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

DEPLOY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if DEPLOY_DIR not in sys.path:
    sys.path.insert(0, DEPLOY_DIR)

os.environ.setdefault("ACCOUNT_MOCK", "1")
os.environ.setdefault("ACCOUNT_QR_TTL", "180")

import account_app as A  # noqa: E402

HEX32 = re.compile(r"^[0-9a-f]{32}$")
IDENT = {"token": "qa-fresh-token", "sid": "9999000001", "name": "测试同学",
         "role": "班长", "badge": "班委", "is_admin": True}


@pytest.fixture()
def server():
    A._QR.clear()
    A._RATE.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), A.Handler)
    srv.daemon_threads = True
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        A._QR.clear()
        A._RATE.clear()


def req(base, method, path, body=None, token=""):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Class-Token"] = token
    r = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, dict(resp.headers), (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw) if raw.strip() else None
        except Exception:  # noqa: BLE001
            payload = {"raw": raw[:200]}
        return e.code, dict(e.headers), payload


def fake_identity(monkeypatch):
    monkeypatch.setattr(A, "_whoami", lambda tok: {"sid": IDENT["sid"], "name": IDENT["name"]}
                        if str(tok).strip() == "qa-phone-token" else None)
    monkeypatch.setattr(A, "_class_verify_full", lambda sid, name: (dict(IDENT), ""))
    monkeypatch.setattr(A, "_class_verify", lambda sid, name: (IDENT["token"], ""))


def create(base, provider="oppo"):
    status, headers, payload = req(base, "POST", "/qr/create", {"p": provider})
    assert status == 200 and payload["ok"] is True
    return payload


def test_health_exposes_qr(server):
    status, headers, payload = req(server, "GET", "/__health")
    assert status == 200
    assert payload["ok"] is True
    assert payload["version"] == "1.2"
    assert payload["qr"] is True
    assert payload["qrTtl"] == A.QR_TTL
    assert 60 <= A.QR_TTL <= 600


def test_create_ticket_format_and_cors(server):
    status, headers, payload = req(server, "POST", "/qr/create", {"p": "oppo"})
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == "*"
    assert HEX32.match(payload["t"]) and HEX32.match(payload["k"])
    assert payload["t"] != payload["k"]
    assert payload["ttl"] == A.QR_TTL
    assert payload["exp"] >= int(A._qr_now())


def test_create_unique_and_provider_sanitized(server):
    a = create(server, "oppo")
    b = create(server, "harmony")
    c = create(server, "https://evil.example/")
    assert len({a["t"], b["t"], c["t"]}) == 3
    assert A._QR[a["t"]]["provider"] == "oppo"
    assert A._QR[b["t"]]["provider"] == "harmony"
    assert A._QR[c["t"]]["provider"] == ""


def test_poll_wait_and_wrong_key(server):
    tk = create(server)
    status, headers, payload = req(server, "GET", "/qr/poll?t=%s&k=%s" % (tk["t"], tk["k"]))
    assert status == 200 and payload["status"] == "wait"
    assert headers.get("Cache-Control") == "no-store"
    status, _, payload = req(server, "GET", "/qr/poll?t=%s&k=%s" % (tk["t"], "0" * 32))
    assert status == 404 and payload["code"] == "not_found"
    status, _, payload = req(server, "GET", "/qr/poll?t=%s&k=%s" % ("f" * 32, "0" * 32))
    assert status == 200 and payload["status"] == "expired"


def test_poll_missing_params(server):
    status, _, payload = req(server, "GET", "/qr/poll")
    assert status == 400 and payload["code"] == "bad_request"


def test_authorize_requires_token(server):
    tk = create(server)
    status, _, payload = req(server, "POST", "/qr/authorize", {"t": tk["t"]})
    assert status == 401 and payload["code"] == "unauthorized"
    status, _, payload = req(server, "GET", "/qr/poll?t=%s&k=%s" % (tk["t"], tk["k"]))
    assert payload["status"] == "wait"


def test_authorize_then_poll_ok(server, monkeypatch):
    fake_identity(monkeypatch)
    tk = create(server, "harmony")
    status, headers, payload = req(server, "POST", "/qr/authorize",
                                   {"t": tk["t"], "p": "harmony", "via": "app"}, token="qa-phone-token")
    assert status == 200 and payload["ok"] is True and payload["name"] == IDENT["name"]
    assert "token" not in payload
    assert headers.get("Access-Control-Allow-Origin") == "*"

    status, _, polled = req(server, "GET", "/qr/poll?t=%s&k=%s" % (tk["t"], tk["k"]))
    assert status == 200 and polled["status"] == "ok"
    assert polled["token"] == IDENT["token"]
    assert polled["sid"] == IDENT["sid"] and polled["name"] == IDENT["name"]
    assert polled["role"] == IDENT["role"] and polled["badge"] == IDENT["badge"]
    assert polled["is_admin"] is True
    assert polled["provider"] == "harmony" and polled["via"] == "app"

    # 重复轮询仍返回同一份身份（发起端可在网络抖动后重试）
    _, _, again = req(server, "GET", "/qr/poll?t=%s&k=%s" % (tk["t"], tk["k"]))
    assert again["status"] == "ok" and again["token"] == IDENT["token"]


def test_authorize_twice_is_idempotent(server, monkeypatch):
    fake_identity(monkeypatch)
    tk = create(server)
    first = req(server, "POST", "/qr/authorize", {"t": tk["t"]}, token="qa-phone-token")[2]
    second = req(server, "POST", "/qr/authorize", {"t": tk["t"]}, token="qa-phone-token")[2]
    assert first["ok"] is True and second["ok"] is True and second.get("already") is True


def test_authorize_expired_ticket(server, monkeypatch):
    fake_identity(monkeypatch)
    tk = create(server)
    real_now = A._qr_now
    monkeypatch.setattr(A, "_qr_now", lambda: real_now() + A.QR_TTL + 5)
    status, _, payload = req(server, "POST", "/qr/authorize", {"t": tk["t"]}, token="qa-phone-token")
    assert status == 200 and payload["ok"] is False and payload["code"] == "ticket_expired"
    monkeypatch.setattr(A, "_qr_now", real_now)


def test_deny_flow(server, monkeypatch):
    fake_identity(monkeypatch)
    tk = create(server)
    status, _, payload = req(server, "POST", "/qr/deny", {"t": tk["t"]}, token="qa-phone-token")
    assert status == 200 and payload["ok"] is True
    _, _, polled = req(server, "GET", "/qr/poll?t=%s&k=%s" % (tk["t"], tk["k"]))
    assert polled["status"] == "deny"
    # 拒绝后手机端可重新确认（票据仍有效）
    again = req(server, "POST", "/qr/authorize", {"t": tk["t"]}, token="qa-phone-token")[2]
    assert again["ok"] is True
    _, _, polled = req(server, "GET", "/qr/poll?t=%s&k=%s" % (tk["t"], tk["k"]))
    assert polled["status"] == "ok"


def test_options_preflight(server):
    r = urllib.request.Request(server + "/qr/authorize", method="OPTIONS", headers={
        "Origin": "https://example.com",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-class-token",
    })
    with urllib.request.urlopen(r, timeout=10) as resp:
        assert resp.status == 204
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"
        allow = (resp.headers.get("Access-Control-Allow-Headers") or "").lower()
        assert "x-class-token" in allow and "content-type" in allow
        assert resp.headers.get("Access-Control-Max-Age") == "600"


def test_purge_caps_memory():
    A._QR.clear()
    for i in range(A.QR_MAX + 5):
        A._QR["%032x" % i] = {"k": "k", "at": A._qr_now() - 1, "exp": A._qr_now() + 60, "state": "wait"}
    A._qr_create("")
    assert len(A._QR) <= A.QR_MAX
