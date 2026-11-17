# -*- coding: utf-8 -*-
"""OPPO 账号绑定 / 快捷登录验证服务（ECS 127.0.0.1:8094；Caddy /account/* 反代）。

背景（用户 2026-11-17 要求）：允许 OPPO 账号绑定学号（同一学号最多 3 个不同 OPPO 账号），
允许 OPPO 账号快捷登录。

安全模型：
  - 客户端只拿 OPPO OAuth SDK 返回的 authCode；本服务用账号服务 AppSecret 调
    OPPO `POST https://api.uc.oppomobile.com/oauth2/token/token-code` 换 openId；
  - openId 只在本服务/云端私有表中使用，不返回给客户端；
  - 绑定表 `public.account_bindings` 仅管理员 token 可读写（服务持有），客户端不可直连；
  - 快捷登录成功时由本服务调现有 `rpc/class_verify` 发班级 token，客户端无法伪造身份。

接口（JSON；客户端 `X-Class-Token` 头）：
  GET  /__health                    → {ok,configured,version}
  POST /oppo/login {code}           → {ok,token,sid,name,nickname} | {ok:false,code,message}
  POST /oppo/bind {code}            → {ok,binding,count}（需 X-Class-Token）
  GET  /oppo/bindings               → {ok,max,count,items[]}（需 X-Class-Token）
  POST /oppo/unbind {id}            → {ok,count}（需 X-Class-Token）

环境变量：
  ACCOUNT_PORT=8094
  ACCOUNT_GATEWAY=https://.../v1/rdb/rest/
  ACCOUNT_PUBLISH_KEY_FILE=/opt/class-tools/account/publish_key
  ACCOUNT_ADMIN_TOKEN_FILE=/opt/class-tools/account/class-token   # 纯 token 或 {"token":...}
  ACCOUNT_OPPO_FILE=/opt/class-tools/account/oppo-account.json    # {"app_id","app_key","app_secret"}
  ACCOUNT_MOCK=1   # 仅本地自测：code 以 MOCK: 开头时不再请求 OPPO；生产必须为 0
"""
import base64
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

VERSION = "1.0"
PORT = int(os.environ.get("ACCOUNT_PORT") or "8094")
GATEWAY = os.environ.get("ACCOUNT_GATEWAY") or (
    "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/")
PUBLISH_KEY_FILE = os.environ.get("ACCOUNT_PUBLISH_KEY_FILE") or "/opt/class-tools/account/publish_key"
ADMIN_TOKEN_FILE = os.environ.get("ACCOUNT_ADMIN_TOKEN_FILE") or "/opt/class-tools/account/class-token"
OPPO_FILE = os.environ.get("ACCOUNT_OPPO_FILE") or "/opt/class-tools/account/oppo-account.json"
MOCK = (os.environ.get("ACCOUNT_MOCK") or "0").strip() in ("1", "true", "yes", "on")
OPPO_TOKEN_URL = "https://api.uc.oppomobile.com/oauth2/token/token-code"
OPPO_PROFILE_URL = "https://api.uc.oppomobile.com/oauth2/userinfo/profile"
MAX_BINDINGS = 3
MAX_BODY = 64 * 1024
RATE_LIMIT = 30  # 每 IP 每分钟 login+bind 次数

_LOCK = threading.Lock()
_RATE = {}  # ip -> [timestamps]
_HEADERS = {"Content-Type": "application/json", "Cache-Control": "no-store"}


def _read_file(path, limit=2 * 1024 * 1024):
    try:
        with open(path, "rb") as f:
            return f.read(limit)
    except Exception:  # noqa: BLE001
        return b""


def _load_publish_key():
    return _read_file(PUBLISH_KEY_FILE).decode("utf-8", "replace").strip()


def _load_admin_token():
    raw = _read_file(ADMIN_TOKEN_FILE).decode("utf-8", "replace").strip()
    if raw.startswith("{"):
        try:
            return str(json.loads(raw).get("token") or "").strip()
        except Exception:  # noqa: BLE001
            return ""
    return raw


def _load_oppo_config():
    raw = _read_file(OPPO_FILE)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    key = str(data.get("app_key") or "").strip()
    secret = str(data.get("app_secret") or "").strip()
    if not key or not secret:
        return None
    return {"app_id": str(data.get("app_id") or "").strip(), "app_key": key, "app_secret": secret}


def _log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)


def _rate_ok(ip):
    now = time.time()
    with _LOCK:
        items = [t for t in _RATE.get(ip, []) if now - t < 60]
        if len(items) >= RATE_LIMIT:
            _RATE[ip] = items
            return False
        items.append(now)
        _RATE[ip] = items
    return True


# ---------------------------------------------------------------- PostgREST

def _http(method, url, body=None, headers=None, timeout=20):
    data = None
    hdrs = {"Accept": "application/json", "Cache-Control": "no-store"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw.strip() else None
        except Exception:  # noqa: BLE001
            parsed = {"raw": raw[:200]}
        return e.code, parsed
    except Exception as e:  # noqa: BLE001
        return 0, {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}


def _rest(method, path, body=None, token=None, prefer=None):
    """调用云端 PostgREST；token=用户班级 token 或管理员 token（X-Device-Id）。"""
    key = _load_publish_key()
    headers = {"Authorization": "Bearer " + key}
    if token:
        headers["X-Device-Id"] = token
    if prefer:
        headers["Prefer"] = prefer
    return _http(method, GATEWAY + path.lstrip("/"), body, headers)


def _rpc(name, body, token=None):
    return _rest("POST", "rpc/" + name, body, token)


def _whoami(user_token):
    if not user_token:
        return None
    st, out = _rpc("class_whoami", {}, user_token)
    if st == 200 and isinstance(out, dict) and out.get("ok"):
        return {"sid": str(out.get("sid") or ""), "name": str(out.get("name") or "")}
    return None


def _class_verify(sid, name):
    st, out = _rpc("class_verify", {"p_sid": sid, "p_name": name})
    if st != 200 or not isinstance(out, dict):
        return None, "verify_failed"
    if out.get("ok") is False:
        return None, str(out.get("reason") or "verify_failed")[:60]
    token = str(out.get("token") or "")
    if not token:
        return None, "verify_failed"
    return token, ""


def _binding_by_openid(openid):
    st, out = _rest("GET", "account_bindings?provider=eq.oppo&openid=eq." +
                    urllib.parse.quote(openid, safe="") + "&select=id,sid,name,nickname", token=_load_admin_token())
    if st == 200 and isinstance(out, list) and out:
        return out[0]
    return None


def _bindings_of_sid(sid):
    st, out = _rest("GET", "account_bindings?provider=eq.oppo&sid=eq." +
                    urllib.parse.quote(sid, safe="") +
                    "&select=id,nickname,created_at&order=created_at.asc", token=_load_admin_token())
    if st == 200 and isinstance(out, list):
        return [{"id": r.get("id"), "nickname": str(r.get("nickname") or "OPPO 账号"),
                 "createdAt": str(r.get("created_at") or "")} for r in out]
    return None, st


def _add_binding(sid, name, openid, nickname):
    st, out = _rest("POST", "account_bindings", {
        "sid": sid, "name": name, "provider": "oppo", "openid": openid, "nickname": nickname,
    }, token=_load_admin_token(), prefer="return=representation")
    if st in (200, 201):
        return True, (out[0] if isinstance(out, list) and out else {})
    msg = ""
    if isinstance(out, dict):
        msg = str(out.get("message") or out.get("code") or "")
    if "binding_limit_reached" in msg or "23514" in msg or "check_violation" in msg:
        return False, "limit"
    if "23505" in msg or "duplicate" in msg:
        return False, "dup"
    return False, "db_error"


# ---------------------------------------------------------------- OPPO 授权码兑换

def _oppo_exchange(code):
    """authCode → {openid,nickname}；失败返回 (None, code, message)。"""
    if MOCK:
        if not code.startswith("MOCK:"):
            return None, "mock_required", "mock 模式只接受 MOCK: 前缀"
        digest = hashlib.sha1(code.encode("utf-8", "replace")).hexdigest()[:16]
        return {"openid": "mock_" + digest, "nickname": "测试OPPO用户"}, "", ""
    cfg = _load_oppo_config()
    if cfg is None:
        return None, "not_configured", "账号服务凭证未配置"
    st, out = _http("POST", OPPO_TOKEN_URL, {
        "appKey": cfg["app_key"], "appSecret": cfg["app_secret"], "code": code,
    }, timeout=20)
    if st != 200 or not isinstance(out, dict) or not out.get("success"):
        err = (out or {}).get("error") if isinstance(out, dict) else None
        return None, "oppo_exchange_failed", str((err or {}).get("message") or "OPPO 授权码换取失败")[:80]
    data = out.get("data") or {}
    openid = str(data.get("openId") or "").strip()
    access = str(data.get("accessToken") or "").strip()
    if not openid:
        return None, "oppo_exchange_failed", "OPPO 未返回 openId"
    nickname = "OPPO 用户"
    if access:
        st2, out2 = _http("POST", OPPO_PROFILE_URL, {
            "appKey": cfg["app_key"], "openId": openid, "accessToken": access,
        }, timeout=15)
        if st2 == 200 and isinstance(out2, dict) and out2.get("success"):
            nickname = str(((out2.get("data") or {}) or {}).get("nickname") or nickname)[:40]
    return {"openid": openid, "nickname": nickname}, "", ""


# ---------------------------------------------------------------- HTTP handler

class Handler(BaseHTTPRequestHandler):
    server_version = "ClassToolsAccount/" + VERSION

    def log_message(self, fmt, *args):  # noqa: A003
        # 不打印请求体/Authorization/token
        _log("%s %s" % (self.command, self.path.split("?")[0]))

    def _json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        for k, v in _HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:  # noqa: BLE001
            pass

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:  # noqa: BLE001
            n = 0
        if n <= 0 or n > MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            return {}

    def _token(self):
        raw = (self.headers.get("X-Class-Token") or self.headers.get("X-Device-Id") or "").strip()
        return raw

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/__health", "/health"):
            configured = bool(_load_publish_key() and _load_admin_token() and
                              (MOCK or _load_oppo_config()))
            return self._json(200, {"ok": True, "configured": configured, "version": VERSION})
        if path == "/oppo/bindings":
            who = _whoami(self._token())
            if not who:
                return self._json(401, {"ok": False, "code": "unauthorized", "message": "请先登录"})
            res = _bindings_of_sid(who["sid"])
            if isinstance(res, tuple):
                return self._json(502, {"ok": False, "code": "db_error", "message": "读取绑定失败"})
            return self._json(200, {"ok": True, "max": MAX_BINDINGS, "count": len(res), "items": res})
        return self._json(404, {"ok": False, "code": "not_found", "message": "not found"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        ip = self.client_address[0]
        if not _rate_ok(ip):
            return self._json(429, {"ok": False, "code": "rate_limited", "message": "请求过于频繁，请稍后再试"})
        body = self._body()
        code = str(body.get("code") or "").strip()
        if path == "/oppo/login":
            if not code:
                return self._json(400, {"ok": False, "code": "bad_request", "message": "缺少授权码"})
            oid, err, msg = _oppo_exchange(code)
            if not oid:
                return self._json(400, {"ok": False, "code": err or "oppo_error", "message": msg or "OPPO 授权失败"})
            b = _binding_by_openid(oid["openid"])
            if not b:
                return self._json(200, {"ok": False, "code": "unbound",
                                        "message": "该 OPPO 账号未绑定学号，请先用学号+姓名登录后在『我的』绑定"})
            token, err = _class_verify(str(b.get("sid") or ""), str(b.get("name") or ""))
            if not token:
                return self._json(200, {"ok": False, "code": "verify_failed",
                                        "message": "绑定信息校验失败，请用学号+姓名登录后重新绑定"})
            return self._json(200, {"ok": True, "token": token, "sid": b.get("sid"),
                                    "name": b.get("name"), "nickname": oid["nickname"]})
        if path == "/oppo/bind":
            who = _whoami(self._token())
            if not who:
                return self._json(401, {"ok": False, "code": "unauthorized", "message": "请先登录"})
            if not code:
                return self._json(400, {"ok": False, "code": "bad_request", "message": "缺少授权码"})
            oid, err, msg = _oppo_exchange(code)
            if not oid:
                return self._json(400, {"ok": False, "code": err or "oppo_error", "message": msg or "OPPO 授权失败"})
            exist = _binding_by_openid(oid["openid"])
            if exist:
                if str(exist.get("sid")) == who["sid"]:
                    return self._json(200, {"ok": True, "binding": {"id": exist.get("id"),
                                                                    "nickname": oid["nickname"],
                                                                    "createdAt": ""},
                                            "count": 1})
                return self._json(200, {"ok": False, "code": "openid_bound_else",
                                        "message": "该 OPPO 账号已绑定其他学号"})
            current = _bindings_of_sid(who["sid"])
            if isinstance(current, tuple):
                return self._json(502, {"ok": False, "code": "db_error", "message": "读取绑定失败"})
            if len(current) >= MAX_BINDINGS:
                return self._json(200, {"ok": False, "code": "limit",
                                        "message": "一个学号最多绑定3个OPPO账号"})
            ok, extra = _add_binding(who["sid"], who["name"], oid["openid"], oid["nickname"])
            if not ok:
                if extra == "limit":
                    return self._json(200, {"ok": False, "code": "limit",
                                            "message": "一个学号最多绑定3个OPPO账号"})
                if extra == "dup":
                    return self._json(200, {"ok": False, "code": "openid_bound_else",
                                            "message": "该 OPPO 账号已绑定其他学号"})
                return self._json(502, {"ok": False, "code": "db_error", "message": "保存绑定失败"})
            return self._json(200, {"ok": True,
                                    "binding": {"id": extra.get("id"), "nickname": oid["nickname"],
                                                "createdAt": str(extra.get("created_at") or "")},
                                    "count": len(current) + 1})
        if path == "/oppo/unbind":
            who = _whoami(self._token())
            if not who:
                return self._json(401, {"ok": False, "code": "unauthorized", "message": "请先登录"})
            try:
                bid = int(body.get("id"))
            except Exception:  # noqa: BLE001
                return self._json(400, {"ok": False, "code": "bad_request", "message": "缺少绑定 id"})
            st, _ = _rest("DELETE", "account_bindings?id=eq.%d&sid=eq.%s" % (
                bid, urllib.parse.quote(who["sid"], safe="")), token=_load_admin_token())
            if st not in (200, 204):
                return self._json(502, {"ok": False, "code": "db_error", "message": "解绑失败"})
            left = _bindings_of_sid(who["sid"])
            count = len(left) if isinstance(left, list) else 0
            return self._json(200, {"ok": True, "count": count})
        return self._json(404, {"ok": False, "code": "not_found", "message": "not found"})


def main():
    pub = bool(_load_publish_key())
    adm = bool(_load_admin_token())
    cfg = _load_oppo_config()
    _log("account service v%s on 127.0.0.1:%d mock=%s publish=%s admin=%s oppo_cfg=%s"
         % (VERSION, PORT, MOCK, pub, adm, bool(cfg)))
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
