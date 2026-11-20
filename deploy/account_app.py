# -*- coding: utf-8 -*-
"""第三方账号绑定 / 快捷登录验证服务（ECS 127.0.0.1:8094；Caddy /account/* 反代）。

背景：
  - 2026-11-17 用户要求 OPPO 账号绑定学号（同一学号最多 3 个）+ OPPO 账号快捷登录；
  - 2026-11-20 用户要求按 honorid-opensdk 接入荣耀账号服务（同一学号最多 3 个 + 快捷登录）。

安全模型：
  - 客户端只拿厂商 OAuth SDK 返回的 authCode；本服务用服务端凭证换 openId；
    OPPO: `POST https://api.uc.oppomobile.com/oauth2/token/token-code`（appKey/appSecret/code）；
    Honor: `POST https://hnoauth-login.cloud.honor.com/oauth2/v3/token`
           （grant_type/code/client_id/client_secret/redirect_uri）→ access_token
           → `GOpen.User.getInfo` 换 openID（荣耀不把 openid 放在 token 响应里）；
  - openId 只在本服务/云端私有表中使用，不返回给客户端；
  - 绑定表 `public.account_bindings` 仅管理员 token 可读写（服务持有），客户端不可直连；
  - 快捷登录成功时由本服务调现有 `rpc/class_verify` 发班级 token，客户端无法伪造身份。

接口（JSON；客户端 `X-Class-Token` 头）：
  GET  /__health                    → {ok,configured,providers,version}
  POST /oppo/login  {code}          → {ok,token,sid,name,nickname} | {ok:false,code,message}
  POST /oppo/bind   {code}          → {ok,binding,count}（需 X-Class-Token）
  GET  /oppo/bindings               → {ok,max,count,items[]}（需 X-Class-Token）
  POST /oppo/unbind {id}            → {ok,count}（需 X-Class-Token）
  POST /honor/login {code}          → 同 OPPO
  POST /honor/bind  {code}          → 同 OPPO
  GET  /honor/bindings              → 同 OPPO
  POST /honor/unbind {id}           → 同 OPPO

环境变量：
  ACCOUNT_PORT=8094
  ACCOUNT_GATEWAY=https://.../v1/rdb/rest/
  ACCOUNT_PUBLISH_KEY_FILE=/opt/class-tools/account/publish_key
  ACCOUNT_ADMIN_TOKEN_FILE=/opt/class-tools/account/class-token   # 纯 token 或 {"token":...}
  ACCOUNT_OPPO_FILE=/opt/class-tools/account/oppo-account.json    # {"app_id","app_key","app_secret"}
  ACCOUNT_HONOR_FILE=/opt/class-tools/account/honor-account.json  # {"client_id","client_secret","redirect_uri"}
  ACCOUNT_MOCK=1   # 仅本地自测：code 以 MOCK: 开头时不再请求厂商；生产必须为 0
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

VERSION = "1.1"
PORT = int(os.environ.get("ACCOUNT_PORT") or "8094")
GATEWAY = os.environ.get("ACCOUNT_GATEWAY") or (
    "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/")
PUBLISH_KEY_FILE = os.environ.get("ACCOUNT_PUBLISH_KEY_FILE") or "/opt/class-tools/account/publish_key"
ADMIN_TOKEN_FILE = os.environ.get("ACCOUNT_ADMIN_TOKEN_FILE") or "/opt/class-tools/account/class-token"
OPPO_FILE = os.environ.get("ACCOUNT_OPPO_FILE") or "/opt/class-tools/account/oppo-account.json"
HONOR_FILE = os.environ.get("ACCOUNT_HONOR_FILE") or "/opt/class-tools/account/honor-account.json"
MOCK = (os.environ.get("ACCOUNT_MOCK") or "0").strip() in ("1", "true", "yes", "on")
# OPPO 账号服务端接口（官方文档《OPPO 账号OAuth授权SDK服务端API》id=10155）：
#   国内生产 https://api.uc.oppomobile.com
#   POST /oauth2/token/token-code  {appKey, appSecret, code}（JSON）
# 注意：appSecret 是「账号服务」应用的 appSecret，不是推送 AppSecret / MasterSecret。
OPPO_TOKEN_URL = "https://api.uc.oppomobile.com/oauth2/token/token-code"
OPPO_PROFILE_URL = "https://api.uc.oppomobile.com/oauth2/userinfo/profile"
HONOR_TOKEN_URL = "https://hnoauth-login.cloud.honor.com/oauth2/v3/token"
HONOR_USERINFO_URL = (
    "https://account-drcn.platform.hihonorcloud.com/rest.php?nsp_svc=GOpen.User.getInfo")
HONOR_TOKEN_INFO_URL = (
    "https://hnoauth-login.cloud.honor.com/rest.php?nsp_svc=hihonor.oauth2.user.getTokenInfo")
HONOR_DEFAULT_REDIRECT = "honorid://redirect_url"
PROVIDERS = {
    "oppo": {"label": "OPPO", "default_nickname": "OPPO 用户"},
    "honor": {"label": "荣耀", "default_nickname": "荣耀用户"},
}
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
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    key = str(data.get("app_key") or "").strip()
    secret = str(data.get("app_secret") or "").strip()
    server_secret = str(data.get("app_server_secret") or data.get("master_secret") or "").strip()
    if not key or (not secret and not server_secret):
        return None
    return {
        "app_id": str(data.get("app_id") or "").strip(),
        "app_key": key,
        "app_secret": secret,
        "app_server_secret": server_secret,
    }


def _load_honor_config():
    raw = _read_file(HONOR_FILE)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    client_id = str(data.get("client_id") or data.get("app_id") or "").strip()
    client_secret = str(data.get("client_secret") or data.get("app_secret") or "").strip()
    if not client_id or not client_secret:
        return None
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": str(data.get("redirect_uri") or HONOR_DEFAULT_REDIRECT).strip(),
    }


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


def _http_form(url, fields, timeout=20):
    """POST application/x-www-form-urlencoded（Honor OAuth/用户信息接口要求表单体）。"""
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Cache-Control": "no-store",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw) if raw.strip() else None
            except Exception:  # noqa: BLE001
                return r.status, {"raw": raw[:200]}
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


def _binding_by_openid(provider, openid):
    st, out = _rest("GET", "account_bindings?provider=eq." + urllib.parse.quote(provider, safe="") +
                    "&openid=eq." + urllib.parse.quote(openid, safe="") +
                    "&select=id,sid,name,nickname", token=_load_admin_token())
    if st == 200 and isinstance(out, list) and out:
        return out[0]
    return None


def _bindings_of_sid(provider, sid):
    st, out = _rest("GET", "account_bindings?provider=eq." + urllib.parse.quote(provider, safe="") +
                    "&sid=eq." + urllib.parse.quote(sid, safe="") +
                    "&select=id,nickname,created_at&order=created_at.asc", token=_load_admin_token())
    if st == 200 and isinstance(out, list):
        fallback = PROVIDERS.get(provider, {}).get("label", provider) + "账号"
        return [{"id": r.get("id"), "nickname": str(r.get("nickname") or fallback),
                 "createdAt": str(r.get("created_at") or "")} for r in out]
    return None, st


def _add_binding(provider, sid, name, openid, nickname):
    st, out = _rest("POST", "account_bindings", {
        "sid": sid, "name": name, "provider": provider, "openid": openid, "nickname": nickname,
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
    if not cfg.get("app_secret"):
        return None, "not_configured", "账号服务 AppSecret 未配置（与推送 AppSecret 不是同一套）"
    st, out = _http("POST", OPPO_TOKEN_URL, {
        "appKey": cfg["app_key"], "appSecret": cfg["app_secret"], "code": code,
    }, timeout=20)
    if st != 200 or not isinstance(out, dict) or not out.get("success"):
        err = (out or {}).get("error") if isinstance(out, dict) else None
        code_text = str((err or {}).get("code") or st or "")
        msg = str((err or {}).get("message") or "OPPO 授权码换取失败")
        detail = ("%s %s" % (code_text, msg)).strip()[:100]
        if str((err or {}).get("code")) == "2020003":
            detail += "（账号服务未激活/未申请 openid 权限，或 appSecret 非账号服务应用）"
        return None, "oppo_exchange_failed", detail[:120]
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


# ---------------------------------------------------------------- Honor 授权码兑换

def _honor_error_text(status, data):
    """Honor 错误体：{error: 1101, sub_error: 20152, error_description: "invalid code"}。"""
    if isinstance(data, dict):
        err = data.get("error")
        sub = data.get("sub_error")
        desc = str(data.get("error_description") or data.get("message") or "").strip()
        parts = [str(x) for x in (err, sub) if x not in (None, "")]
        code = "/".join(parts) if parts else str(status)
        return ("%s %s" % (code, desc)).strip()[:120]
    return str(status)


def _honor_exchange(code):
    """authCode → {openid,nickname}；失败返回 (None, code, message)。"""
    if MOCK:
        if not code.startswith("MOCK:"):
            return None, "mock_required", "mock 模式只接受 MOCK: 前缀"
        digest = hashlib.sha1(code.encode("utf-8", "replace")).hexdigest()[:16]
        return {"openid": "mock_honor_" + digest, "nickname": "测试荣耀用户"}, "", ""
    cfg = _load_honor_config()
    if cfg is None:
        return None, "not_configured", "荣耀账号服务凭证未配置"
    attempts = []
    for redirect in (cfg["redirect_uri"], ""):
        fields = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }
        if redirect:
            fields["redirect_uri"] = redirect
        st, out = _http_form(HONOR_TOKEN_URL, fields)
        if st == 200 and isinstance(out, dict) and out.get("access_token"):
            return _honor_profile(out, cfg)
        attempts.append(_honor_error_text(st, out))
        # 1101 invalid code 是授权码本身的问题，换 redirect_uri 无意义；
        # 仅当错误明确指向 redirect_uri 时才继续尝试省略参数。
        if isinstance(out, dict) and str(out.get("error")) == "1101" and "invalid code" in str(
                out.get("error_description") or ""):
            break
    return None, "honor_exchange_failed", "；".join(attempts)[:120] or "荣耀授权码换取失败"


def _honor_profile(tokens, cfg):
    access = str((tokens or {}).get("access_token") or "").strip()
    if not access:
        return None, "honor_exchange_failed", "荣耀未返回 access_token"
    openid = str(tokens.get("openid") or tokens.get("open_id") or "").strip()
    nickname = ""
    st, out = _http_form(HONOR_USERINFO_URL, {"access_token": access, "getNickName": "1"})
    if st == 200 and isinstance(out, dict):
        openid = openid or str(out.get("openID") or out.get("openId") or out.get("openid") or "").strip()
        nickname = str(out.get("displayName") or out.get("nickName") or "").strip()
        if not openid and str(out.get("error") or ""):
            pass  # 常见：未授予 profile → 用下方 tokenInfo 兜底 openid
    if not openid:
        st2, out2 = _http_form(HONOR_TOKEN_INFO_URL, {"access_token": access})
        if st2 == 200 and isinstance(out2, dict):
            openid = str(out2.get("open_id") or out2.get("openid") or out2.get("openID") or "").strip()
    if not openid:
        return None, "honor_exchange_failed", "荣耀未返回 openID（请确认已授予 openid scope）"
    return {"openid": openid, "nickname": nickname or PROVIDERS["honor"]["default_nickname"]}, "", ""


# ---------------------------------------------------------------- 通用登录/绑定

def _exchange(provider, code):
    return _honor_exchange(code) if provider == "honor" else _oppo_exchange(code)


def _login_payload(provider, code):
    """authCode → 班级 token（不信任客户端 openid；绑定关系以云端表为准）。"""
    label = PROVIDERS.get(provider, {}).get("label", provider)
    ident, err, msg = _exchange(provider, code)
    if not ident:
        return 400, {"ok": False, "code": err or (provider + "_error"),
                     "message": msg or (label + "授权失败")}
    b = _binding_by_openid(provider, ident["openid"])
    if not b:
        return 200, {"ok": False, "code": "unbound",
                     "message": "该%s账号未绑定学号，请先用学号+姓名登录后在『我的』绑定" % label}
    token, err = _class_verify(str(b.get("sid") or ""), str(b.get("name") or ""))
    if not token:
        return 200, {"ok": False, "code": "verify_failed",
                     "message": "绑定信息校验失败，请用学号+姓名登录后重新绑定"}
    return 200, {"ok": True, "token": token, "sid": b.get("sid"),
                 "name": b.get("name"), "nickname": ident["nickname"]}


def _bind_payload(provider, code, class_token):
    """绑定当前第三方账号到当前学号；上限 / 已被其他学号绑定均返回可展示错误。"""
    label = PROVIDERS.get(provider, {}).get("label", provider)
    who = _whoami(class_token)
    if not who:
        return 401, {"ok": False, "code": "unauthorized", "message": "请先登录"}
    ident, err, msg = _exchange(provider, code)
    if not ident:
        return 400, {"ok": False, "code": err or (provider + "_error"),
                     "message": msg or (label + "授权失败")}
    exist = _binding_by_openid(provider, ident["openid"])
    if exist:
        if str(exist.get("sid")) == who["sid"]:
            current = _bindings_of_sid(provider, who["sid"])
            count = len(current) if isinstance(current, list) else 1
            return 200, {"ok": True, "binding": {"id": exist.get("id"),
                                                 "nickname": ident["nickname"], "createdAt": ""},
                         "count": count}
        return 200, {"ok": False, "code": "openid_bound_else",
                     "message": "该%s账号已绑定其他学号" % label}
    current = _bindings_of_sid(provider, who["sid"])
    if isinstance(current, tuple):
        return 502, {"ok": False, "code": "db_error", "message": "读取绑定失败"}
    if len(current) >= MAX_BINDINGS:
        return 200, {"ok": False, "code": "limit",
                     "message": "一个学号最多绑定%d个%s账号" % (MAX_BINDINGS, label)}
    ok, extra = _add_binding(provider, who["sid"], who["name"], ident["openid"], ident["nickname"])
    if not ok:
        if extra == "limit":
            return 200, {"ok": False, "code": "limit",
                         "message": "一个学号最多绑定%d个%s账号" % (MAX_BINDINGS, label)}
        if extra == "dup":
            return 200, {"ok": False, "code": "openid_bound_else",
                         "message": "该%s账号已绑定其他学号" % label}
        return 502, {"ok": False, "code": "db_error", "message": "保存绑定失败"}
    return 200, {"ok": True,
                 "binding": {"id": extra.get("id"), "nickname": ident["nickname"],
                             "createdAt": str(extra.get("created_at") or "")},
                 "count": len(current) + 1}


def _bindings_page(provider, class_token):
    who = _whoami(class_token)
    if not who:
        return 401, {"ok": False, "code": "unauthorized", "message": "请先登录"}
    res = _bindings_of_sid(provider, who["sid"])
    if isinstance(res, tuple):
        return 502, {"ok": False, "code": "db_error", "message": "读取绑定失败"}
    return 200, {"ok": True, "max": MAX_BINDINGS, "count": len(res), "items": res}


def _unbind_payload(provider, class_token, body):
    who = _whoami(class_token)
    if not who:
        return 401, {"ok": False, "code": "unauthorized", "message": "请先登录"}
    try:
        bid = int(body.get("id"))
    except Exception:  # noqa: BLE001
        return 400, {"ok": False, "code": "bad_request", "message": "缺少绑定 id"}
    st, _ = _rest("DELETE", "account_bindings?id=eq.%d&sid=eq.%s&provider=eq.%s" % (
        bid, urllib.parse.quote(who["sid"], safe=""), urllib.parse.quote(provider, safe="")),
        token=_load_admin_token())
    if st not in (200, 204):
        return 502, {"ok": False, "code": "db_error", "message": "解绑失败"}
    left = _bindings_of_sid(provider, who["sid"])
    count = len(left) if isinstance(left, list) else 0
    return 200, {"ok": True, "count": count}


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
            oppo = MOCK or bool(_load_oppo_config())
            honor = MOCK or bool(_load_honor_config())
            configured = bool(_load_publish_key() and _load_admin_token() and (oppo or honor))
            return self._json(200, {
                "ok": True,
                "configured": configured,
                "providers": {"oppo": bool(oppo), "honor": bool(honor)},
                "version": VERSION,
            })
        for provider in PROVIDERS:
            if path == "/%s/bindings" % provider:
                status, payload = _bindings_page(provider, self._token())
                return self._json(status, payload)
        return self._json(404, {"ok": False, "code": "not_found", "message": "not found"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        ip = self.client_address[0]
        if not _rate_ok(ip):
            return self._json(429, {"ok": False, "code": "rate_limited", "message": "请求过于频繁，请稍后再试"})
        body = self._body()
        code = str(body.get("code") or "").strip()
        provider = next((p for p in PROVIDERS if path.startswith("/%s/" % p)), "")
        action = path.rsplit("/", 1)[-1] if provider else ""
        if provider and action in ("login", "bind") and not code:
            return self._json(400, {"ok": False, "code": "bad_request", "message": "缺少授权码"})
        if provider and action == "login":
            status, payload = _login_payload(provider, code)
            return self._json(status, payload)
        if provider and action == "bind":
            status, payload = _bind_payload(provider, code, self._token())
            return self._json(status, payload)
        if provider and action == "unbind":
            status, payload = _unbind_payload(provider, self._token(), body)
            return self._json(status, payload)
        return self._json(404, {"ok": False, "code": "not_found", "message": "not found"})


def main():
    pub = bool(_load_publish_key())
    adm = bool(_load_admin_token())
    oppo_cfg = _load_oppo_config()
    honor_cfg = _load_honor_config()
    _log("account service v%s on 127.0.0.1:%d mock=%s publish=%s admin=%s oppo_cfg=%s honor_cfg=%s"
         % (VERSION, PORT, MOCK, pub, adm, bool(oppo_cfg), bool(honor_cfg)))
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
