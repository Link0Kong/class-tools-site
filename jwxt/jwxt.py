# -*- coding: utf-8 -*-
"""jwxt.py — 班级工具站 · 教务系统课表同步核心模块。

链路（2026-11-08 更新；默认纯 requests，无需浏览器）：
  学校统一身份认证 authserver（表单 + AES 加密密码，纯 requests）
  → 门户 e.fjtcm.edu.cn
  → GET http://210.34.74.77/sso.jsp（JS 跳 authserver → 302 链回教务系统，下发 SERVERID_jsxsd 等 cookie）
  → GET /jsxsd/xskb/xskb_list.do?viweType=0 周课表（table.qz-weeklyTable）。
  旧链路（headless Edge 门户点「新教务系统」）仅作纯 requests 失败时的兜底保留。

职责：
  * sso_login_http()：纯 requests 完成统一认证 → 教务系统 SSO（2026-11-08 新增，默认路径）
  * sso_login()：统一认证 → 教务系统，返回可抓取的 requests.Session（先 HTTP，失败回退 Edge）
  * fetch_timetable()：抓课表页 HTML（落盘 _last_timetable.html 便于调试）
  * parse_timetable()：qz-weeklyTable 新版解析 + 旧版 kbcontent 兜底
  * Windows DPAPI 凭据加密存取（无第三方依赖）
  * 生成 #tt= 发布链接（base64url(UTF-8 JSON {c,t})）
  * --manual / headless Edge 的 CDP 客户端（纯标准库 WebSocket）

依赖：requests + pycryptodome（或 cryptography），其余标准库。
安全：本模块不打印、不落盘明文密码；账号只在日志里以掩码出现；
      cookie 缓存只存本机（jwxsd_cookies.json，已 gitignore）。
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import datetime
import html as htmlmod
import json
import logging
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse

try:  # 允许导入本模块做纯解析测试（不装 requests 也能跑 parse_timetable）
    import requests
except ImportError:  # pragma: no cover
    requests = None

logger = logging.getLogger("jwxt")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

BASE_URL = "http://210.34.74.77"
PREFIX = "/jsxsd"
LOGIN_URL = BASE_URL + PREFIX + "/"
LOGIN_POST_URL = BASE_URL + PREFIX + "/xk/LoginToXk"
MAIN_PAGE_URL = BASE_URL + PREFIX + "/framework/xsMainV.jsp"
TIMETABLE_URL = BASE_URL + PREFIX + "/xskb/xskb_list.do"
APP_DO_URL = BASE_URL + PREFIX + "/app.do"

# --- 学校统一身份认证（authserver）---
AUTH_BASE_URL = "https://authserver.fjtcm.edu.cn"
AUTH_SERVICE_URL = "https://e.fjtcm.edu.cn/login"
AUTH_LOGIN_URL = AUTH_BASE_URL + "/authserver/login"
AUTH_CAPTCHA_URL = AUTH_BASE_URL + "/authserver/checkNeedCaptcha.htl"
PORTAL_URL = "https://e.fjtcm.edu.cn/index.html"
PORTAL_TILE_TEXT = "新教务系统"
AES_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

HERE = os.path.dirname(os.path.abspath(__file__))
LAST_HTML_PATH = os.path.join(HERE, "_last_timetable.html")
CREDS_PATH = os.path.join(HERE, "creds.dpapi")
LOG_DIR = os.path.join(HERE, "logs")
JWXT_COOKIE_CACHE = os.path.join(HERE, "jwxsd_cookies.json")
COOKIE_CACHE_TTL = 6 * 3600  # 秒：教务系统 cookie 缓存有效期（过期后自动重新 SSO）

PAGE_TIMEOUT = 20
DEFAULT_WEEKS = "1-20"
PUBLISH_BASE = "https://tool.furina.fun/"

CREDS_ENTROPY = b"tool.furina.fun/jwxt/creds/v1"


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class JwxtError(Exception):
    """模块内通用错误。"""


class LoginError(JwxtError):
    """登录失败（账号/密码/验证码/页面改版）。"""


class FetchError(JwxtError):
    """抓取课表页失败。"""


class ParseError(JwxtError):
    """课表解析失败。"""


# ---------------------------------------------------------------------------
# 文本 / 数字归一化
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")
_FULLWIDTH_MAP = str.maketrans("０１２３４５６７８９，、．；：（）", "0123456789,,.;:()")


def _norm(text) -> str:
    """去标签前的通用归一化：HTML 实体、不换行空格、连续空白。"""
    s = htmlmod.unescape("" if text is None else str(text))
    s = s.replace("\xa0", " ").replace("\u3000", " ")
    return _WS_RE.sub(" ", s).strip()


def _num_norm(text) -> str:
    """数字/周次/节次场景的归一化：全角数字、中文标点、各种破折号。"""
    s = _norm(text).translate(_FULLWIDTH_MAP)
    for ch in ("—", "–", "~", "～", "至"):
        s = s.replace(ch, "-")
    return s


def _text_only(fragment) -> str:
    """去标签取纯文本（单行）。"""
    return _norm(_TAG_RE.sub("", fragment or ""))


def _attr(attrs: str, name: str) -> str:
    """从标签属性串里取某个属性值（支持单/双/无引号）。"""
    m = re.search(
        r"(?:^|\s)" + re.escape(name) + r"""\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
        attrs or "",
        re.I,
    )
    if not m:
        return ""
    return next((g for g in m.groups() if g is not None), "")


# ---------------------------------------------------------------------------
# 登录编码（页面 /jsxsd/js/conwork.js + submitForm1() 的等价实现）
# ---------------------------------------------------------------------------

def encode_inp(value: str) -> str:
    """等价页面里的 encodeInp()：UTF-8 字节的标准 Base64。"""
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def interleave_encode(code: str, scode: str, sxh: str, limit: int = 55) -> str:
    """submitForm1() 的交错加密：前 limit 个字符后插入 scode 的前 int(sxh[i]) 个字符。"""
    out = []
    for i, ch in enumerate(code):
        if i >= limit:
            out.append(code[i:])
            break
        n = int(sxh[i]) if i < len(sxh) and sxh[i].isdigit() else 0
        out.append(ch)
        out.append(scode[:n])
        scode = scode[n:]
    return "".join(out)


def build_login_encoded(account: str, password: str, scode: str, sxh: str) -> str:
    """拼出 POST /jsxsd/xk/LoginToXk 的 encoded 字段。"""
    code = "%%%".join([encode_inp(account), encode_inp(password), encode_inp(" ")])
    return interleave_encode(code, scode, sxh)


_SCODE_SXH_RE = re.compile(
    r"""var\s+scode\s*=\s*"([^"]*)"\s*;\s*var\s+sxh\s*=\s*"([^"]*)\"""",
    re.I,
)


def extract_scode_sxh(html_text: str):
    """从登录页 HTML 里抓随机的 scode / sxh（每次加载都不同，禁止写死）。"""
    if not html_text:
        return None
    candidates = [
        (scode, sxh)
        for scode, sxh in _SCODE_SXH_RE.findall(html_text)
        if len(scode) >= 10 and len(sxh) >= 10
    ]
    if not candidates:
        return None
    # 交错加密最多用到 sxh 的前 55 位；优先取足够长的
    candidates.sort(key=lambda p: (len(p[1]) >= 55, len(p[0])), reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# 发布链接
# ---------------------------------------------------------------------------

def b64url_encode(raw: bytes) -> str:
    """base64url：+ -> -，/ -> _，去掉 =（等价 JS 的 btoa(...).replace(...)）。"""
    return base64.b64encode(raw).decode("ascii").replace("+", "-").replace("/", "_").rstrip("=")


def b64url_decode(text: str) -> bytes:
    """base64url 解码（测试用）。"""
    s = str(text or "").strip().replace("-", "+").replace("_", "/")
    while len(s) % 4:
        s += "="
    return base64.b64decode(s)


def build_publish_url(courses, term_start: str, base: str = PUBLISH_BASE) -> str:
    """生成站点发布链接：<base>#tt=<base64url(UTF-8 JSON {c,t})>（不带 meta，链接要短）。"""
    payload = json.dumps(
        {"c": courses, "t": term_start or ""}, ensure_ascii=False, separators=(",", ":")
    )
    return str(base) + "#tt=" + b64url_encode(payload.encode("utf-8"))


def mask_account(account: str) -> str:
    """日志里账号脱敏：只保留首尾各 2 位。"""
    s = str(account or "")
    if len(s) <= 4:
        return "***"
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


def normalize_term_start(value) -> str:
    """把 2026-08-31 / 2026.9.7 / 2026年9月7日 统一成 YYYY-MM-DD；非法返回空串。"""
    s = _num_norm(value)
    for ch in ("年", "月", "日"):
        s = s.replace(ch, "-")
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    try:
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# HTTP 基础
# ---------------------------------------------------------------------------

def _request(session, method: str, url: str, *, timeout: int = PAGE_TIMEOUT,
             retries: int = 1, **kwargs):
    """带一次重试的请求（只在超时/连接异常时重试）。"""
    if requests is None:
        raise JwxtError("缺少依赖 requests，请先执行：pip install requests")
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return session.request(method, url, timeout=timeout, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            if attempt < retries:
                logger.warning("网络异常（%s），1.5 秒后重试一次", type(exc).__name__)
                time.sleep(1.5)
        except requests.exceptions.RequestException as exc:
            raise JwxtError("请求失败 %s %s：%s" % (method, url, exc)) from exc
    raise JwxtError("网络请求失败（已重试 %d 次）%s %s：%s" % (retries, method, url, last_exc))


def _looks_like_login(text: str) -> bool:
    if not text:
        return False
    if re.search(r"<title>\s*登录", text):
        return True
    return ("userAccount" in text) and ("LoginToXk" in text)


def parse_error_message(text: str):
    """从登录失败页里取错误文案（<font id="showMsg"> / alert 文案）。"""
    if not text:
        return None
    m = re.search(r"""id\s*=\s*["']showMsg["'][^>]*>(.*?)</font\s*>""", text, re.I | re.S)
    if m:
        msg = _text_only(m.group(1))
        if msg:
            return msg
    for pat in (
        r"(该账号不存在或密码错误[^<\n\r\"']*)",
        r"(用户名或密码不能为空[^<\n\r\"']*)",
        r"(密码不能为空[^<\n\r\"']*)",
        r"(验证码[^<\n\r\"']{0,20})",
        r"(用户已锁定[^<\n\r\"']*)",
    ):
        m = re.search(pat, text)
        if m:
            return _norm(m.group(1))
    return None


def check_logged_in(session, *, timeout: int = PAGE_TIMEOUT) -> bool:
    """用 GET /jsxsd/framework/xsMainV.jsp 验证登录态是否有效。"""
    try:
        r = _request(session, "GET", MAIN_PAGE_URL, timeout=timeout, retries=0,
                     allow_redirects=True)
    except JwxtError:
        return False
    text = r.text or ""
    if _looks_like_login(text):
        return False
    if "xsMainV.jsp" in r.url or "xsMainV.jsp" in text:
        return True
    return any(k in text for k in ("退出", "注销", "主菜单", "学生首页"))


def login(account: str, password: str, *, timeout: int = PAGE_TIMEOUT, session=None):
    """按教务系统协议登录；成功返回 requests.Session，失败抛 LoginError。"""
    if requests is None:
        raise JwxtError("缺少依赖 requests，请先执行：pip install requests")
    account = str(account or "").strip()
    password = "" if password is None else str(password)
    if not account:
        raise LoginError("账号为空")
    if not password:
        raise LoginError("密码为空（未提供密码，也不会去猜）")

    s = session or requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        "Referer": LOGIN_URL,
        "Connection": "keep-alive",
    })

    logger.info("GET 登录页 %s（获取随机 scode/sxh）", LOGIN_URL)
    r = _request(s, "GET", LOGIN_URL, timeout=timeout)
    consts = extract_scode_sxh(r.text or "")
    if not consts:
        raise LoginError("登录页结构异常：未找到 scode/sxh 随机参数（可能改版或被网关拦截）")
    scode, sxh = consts
    logger.info("已取得 scode=%d 字符 / sxh=%d 字符", len(scode), len(sxh))
    encoded = build_login_encoded(account, password, scode, sxh)

    data = {
        "userAccount": account,
        "encoded": encoded,
        "loginMethod": "LoginToXk",
        "userlanguage": "0",
    }
    logger.info("POST 登录 %s account=%s encoded=%d 字符", LOGIN_POST_URL,
                mask_account(account), len(encoded))
    r2 = _request(
        s, "POST", LOGIN_POST_URL, data=data, timeout=timeout, allow_redirects=True,
        headers={
            "Referer": LOGIN_URL,
            "Origin": BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    msg = parse_error_message(r2.text or "")
    if msg:
        raise LoginError(msg)
    if _looks_like_login(r2.text or "") or not check_logged_in(s, timeout=timeout):
        raise LoginError("登录未成功：返回的仍是登录页（可能账号被限制、需要验证码或页面改版）")
    logger.info("登录成功 account=%s", mask_account(account))
    return s


# ---------------------------------------------------------------------------
# 学校统一身份认证（authserver）SSO
#
# 链路（2026-11-08 更新，优先纯 requests）：
#   authserver 表单 + AES 加密密码（纯 requests）→ 门户 e.fjtcm.edu.cn
#   → GET http://210.34.74.77/sso.jsp（返回 JS 跳转到 authserver 的 service 地址）
#   → 带着门户 cookie（CASTGC）跟随 302 链回到 sso.jsp，服务端下发
#     SERVERID_jsxsd / bzb_jsxsd 等教务 cookie
#   → requests 直接抓课表（不再需要 headless Edge）
#
# 旧链路（仅兜底，保留兼容）：门户 cookie 注入 headless Edge → 点「新教务系统」
#   → 从浏览器里取教务 cookie。2026-11-07 Edge 自更新后 HKLM 策略
#   LocalNetworkAccessAllowedForUrls 不含 210.34.74.77 → headless Edge 报
#   ERR_BLOCKED_BY_CLIENT，故默认改为纯 requests（见 README §0/§11 与 11-08 记录）。
# 密码语义：这里的密码是**学校统一身份认证密码**，不是旧 jsxsd 直登密码。
# ---------------------------------------------------------------------------

# 教务系统 SSO 入口：返回一段 JS（window.location.href='authserver...?service=...'）
SSO_JSP_URL = BASE_URL + "/sso.jsp"
_JS_REDIRECT_RE = re.compile(
    r"""location(?:\.href)?\s*=\s*['"]([^'"]+)['"]""", re.I
)


def _extract_js_redirect(html_text: str):
    """从 <script>window.location.href='...'</script> 里取跳转目标；没有返回 None。"""
    m = _JS_REDIRECT_RE.search(html_text or "")
    if not m:
        return None
    target = htmlmod.unescape(m.group(1)).strip()
    if not target or target.lower().startswith(("javascript:", "#")):
        return None
    return target


def _session_domain_cookies(session, needle: str = "210.34.74.77") -> dict:
    """取 session cookie jar 里属于教务系统域名的 cookie（{name: value}，不打印值）。"""
    out = {}
    for c in getattr(session, "cookies", []) or []:
        name = getattr(c, "name", "")
        value = getattr(c, "value", "")
        domain = getattr(c, "domain", "") or ""
        if name and value and needle in domain:
            out[str(name)] = str(value)
    return out


def _looks_like_any_login(text: str) -> bool:
    """登录页判定（统一认证登录页或教务系统登录页）。"""
    return _looks_like_auth_login(text) or _looks_like_login(text)


def sso_login_http(account: str, password: str, *, timeout: int = PAGE_TIMEOUT,
                   session=None, max_hops: int = 6, save_cookies: bool = True):
    """纯 requests 完成「统一认证 → 教务系统」SSO，返回可抓课表的 requests.Session。

    链路：authserver 表单登录 → GET sso.jsp（JS 跳 authserver）→ 带门户 cookie
    跟随跳转回到教务系统（302 链下发 SERVERID_jsxsd 等 cookie）→ check_logged_in。
    **不需要 headless Edge**（2026-11-08 实测可用；Edge 被本机策略拦截时这是唯一路径）。

    失败语义：
      * 账号/密码/验证码问题 → LoginError（调用方不应再走浏览器重试）；
      * 网络/门户/教务系统结构问题 → JwxtError/FetchError（可回退旧 Edge 链路）。
    """
    if requests is None:
        raise JwxtError("缺少依赖 requests，请先执行：pip install requests")
    account = str(account or "").strip()
    password = "" if password is None else str(password)
    if not account:
        raise LoginError("统一认证账号为空")
    if not password:
        raise LoginError("统一认证密码为空（未提供，也不会去猜）")

    # 1) 统一认证表单登录（纯 requests；失败直接抛 LoginError）
    s = authserver_login(account, password, timeout=max(15, timeout), session=session)
    logger.info("统一认证成功，纯 requests 走教务系统 sso.jsp SSO…")

    # 2) sso.jsp → JS 跳 authserver → 302 链回教务系统
    url = SSO_JSP_URL
    last_text = ""
    last_url = url
    for hop in range(1, max(1, int(max_hops)) + 1):
        try:
            r = _request(s, "GET", url, timeout=timeout, retries=1, allow_redirects=True)
        except JwxtError as exc:
            if hop == 1:
                raise FetchError("教务系统 sso.jsp 不可达：%s" % exc) from exc
            raise
        last_text, last_url = r.text or "", r.url
        cookies = _session_domain_cookies(s)
        if cookies and check_logged_in(s, timeout=timeout):
            logger.info("教务系统登录成功（纯 requests SSO，第 %d 跳，cookie：%s）",
                        hop, ", ".join(sorted(cookies)))
            if save_cookies:
                save_jwxsd_cookies(cookies)
            return s
        if _looks_like_any_login(last_text):
            err = _extract_auth_error(last_text) or parse_error_message(last_text) or ""
            raise LoginError("统一认证/教务系统登录失败%s"
                             % ("：" + err if err else "（账号密码错误或页面改版）"))
        target = _extract_js_redirect(last_text)
        if not target:
            break
        url = urllib.parse.urljoin(last_url, target)
        logger.info("SSO 第 %d 跳：JS 跳转 → %s", hop,
                    urllib.parse.urlsplit(url).netloc)

    # 3) 兜底：直接探测教务系统登录态（可能 302 已把 cookie 带全但页面不是主页面）
    if _session_domain_cookies(s) and check_logged_in(s, timeout=timeout):
        cookies = _session_domain_cookies(s)
        if save_cookies:
            save_jwxsd_cookies(cookies)
        logger.info("教务系统登录成功（纯 requests SSO，兜底探测）")
        return s

    if _looks_like_any_login(last_text):
        raise LoginError(_extract_auth_error(last_text) or
                         "统一认证/教务系统登录失败（页面仍是登录页）")
    raise FetchError("纯 requests SSO 未拿到教务系统 cookie（最后页面：%s）"
                     % (urllib.parse.urlsplit(last_url or "").netloc or "?"))

def _auth_login_page_url() -> str:
    return AUTH_LOGIN_URL + "?service=" + urllib.parse.quote(AUTH_SERVICE_URL, safe="")


def _extract_input_value(html_text: str, *, name: str = None, elem_id: str = None) -> str:
    """从 HTML 的 <input> 里取 value（按 name 或 id 匹配，属性顺序无关）。"""
    for m in re.finditer(r"<input\b([^>]*)>", html_text or "", re.I):
        attrs = m.group(1)
        if name and not re.search(
                r"""\bname\s*=\s*["']%s["']""" % re.escape(name), attrs, re.I):
            continue
        if elem_id and not re.search(
                r"""\bid\s*=\s*["']%s["']""" % re.escape(elem_id), attrs, re.I):
            continue
        return _attr(attrs, "value")
    return ""


def _random_aes_string(n: int) -> str:
    n = int(n)
    if n <= 0:
        return ""
    rng = random.SystemRandom()
    return "".join(rng.choice(AES_CHARS) for _ in range(n))


def aes_encrypt_password(password: str, salt: str) -> str:
    """等价 authserver encrypt.js: AES-CBC-Pkcs7(randomString(64)+密码, key=salt, iv=randomString16)。

    CryptoJS 的 key/iv 用 Utf8 解析 salt/iv（都是 ASCII 字符集，等价于 UTF-8 字节）。
    优先 pycryptodome，其次 cryptography；都没有则报错提示安装。
    """
    plain = (_random_aes_string(64) + str(password)).encode("utf-8")
    key = str(salt).encode("utf-8")
    iv = _random_aes_string(16).encode("utf-8")
    try:
        from Crypto.Cipher import AES  # pycryptodome
        from Crypto.Util.Padding import pad
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return base64.b64encode(cipher.encrypt(pad(plain, 16))).decode("ascii")
    except ImportError:
        pass
    try:
        from cryptography.hazmat.primitives import padding as sym_padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        padder = sym_padding.PKCS7(128).padder()
        padded = padder.update(plain) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("ascii")
    except ImportError as exc:
        raise JwxtError(
            "统一认证密码加密需要 pycryptodome（或 cryptography）：pip install pycryptodome"
        ) from exc


def check_need_captcha(session, account: str, *, timeout: int = PAGE_TIMEOUT):
    """GET checkNeedCaptcha.htl → True/False；接口异常返回 None。"""
    try:
        r = _request(session, "GET", AUTH_CAPTCHA_URL, timeout=timeout, retries=0,
                     params={"username": account})
        data = r.json()
        return bool(data.get("isNeed"))
    except (ValueError, JwxtError, AttributeError):
        return None


_AUTH_ERROR_PATTERNS = (
    r"""<span[^>]*id=["']showErrorTip["'][^>]*>(.*?)</span>""",
    r"""<div[^>]*class=["'][^"']*auth_error[^"']*["'][^>]*>(.*?)</div>""",
    r"""<div[^>]*class=["'][^"']*login-error[^"']*["'][^>]*>(.*?)</div>""",
)


def _extract_auth_error(html_text: str) -> str:
    text = html_text or ""
    for pat in _AUTH_ERROR_PATTERNS:
        m = re.search(pat, text, re.I | re.S)
        if m:
            msg = _text_only(m.group(1))
            if msg:
                return msg
    for kw in ("用户名或密码", "密码错误", "账号或密码", "用户不存在", "账号不存在",
               "验证码", "账户被锁定", "账号被锁定"):
        m = re.search(r"([^<>{}]{0,30}%s[^<>{}]{0,60})" % re.escape(kw), text)
        if m:
            return _norm(m.group(1))
    return ""


def _looks_like_auth_login(html_text: str) -> bool:
    text = html_text or ""
    return ("pwdEncryptSalt" in text) and ("loginFromId" in text or "saltPassword" in text)


def authserver_login(account: str, password: str, *, timeout: int = 20, session=None):
    """纯 requests 完成 authserver 登录，返回已持有门户 cookie 的 Session。"""
    if requests is None:
        raise JwxtError("缺少依赖 requests，请先执行：pip install requests")
    account = str(account or "").strip()
    password = "" if password is None else str(password)
    if not account:
        raise LoginError("统一认证账号为空")
    if not password:
        raise LoginError("统一认证密码为空（未提供，也不会去猜）")

    s = session or requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        "Connection": "keep-alive",
    })

    logger.info("GET 统一认证登录页（获取 execution / pwdEncryptSalt）")
    r = _request(s, "GET", _auth_login_page_url(), timeout=timeout)
    html_text = r.text or ""
    if not _looks_like_auth_login(html_text):
        raise LoginError("统一认证登录页结构异常（未找到 loginFromId/pwdEncryptSalt，可能改版）")
    salt = _extract_input_value(html_text, elem_id="pwdEncryptSalt")
    execution = _extract_input_value(html_text, elem_id="execution")
    if not salt or not execution:
        raise LoginError("统一认证登录页缺少 pwdEncryptSalt / execution")

    need_captcha = check_need_captcha(s, account, timeout=timeout)
    if need_captcha:
        raise LoginError("统一认证要求输入验证码，无法自动登录；请用 python sync.py --manual")

    encrypted = aes_encrypt_password(password, salt)
    data = {
        "username": account,
        "password": encrypted,
        "captcha": "",
        "rememberMe": "false",
        "_eventId": "submit",
        "cllt": "userNameLogin",
        "dllt": "generalLogin",
        "lt": "",
        "execution": execution,
        "pwdEncryptSalt": salt,
        "rmShown": "1",
    }
    logger.info("POST 统一认证 login account=%s（密码已 AES 加密）", mask_account(account))
    r2 = _request(
        s, "POST", _auth_login_page_url(), data=data, timeout=timeout,
        allow_redirects=True,
        headers={
            "Referer": _auth_login_page_url(),
            "Origin": AUTH_BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    if _looks_like_auth_login(r2.text or ""):
        raise LoginError(_extract_auth_error(r2.text or "") or
                         "统一认证登录失败（账号或密码错误，或该账号未开通）")
    logger.info("统一认证登录成功 → 门户：%s", urllib.parse.urlsplit(r2.url).netloc)
    return s


def _requests_cookies(session) -> list:
    """把 requests 的 cookie jar 转成 CDP Network.setCookies 需要的格式（只带 fjtcm 域）。"""
    out = []
    for c in getattr(session, "cookies", []) or []:
        if not c.domain or not c.value:
            continue
        if "fjtcm.edu.cn" not in (c.domain or ""):
            continue
        http_only = False
        try:
            http_only = bool(c.has_nonstandard_attr("HttpOnly"))
        except Exception:
            http_only = False
        out.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": http_only,
            "sameSite": "Lax",
        })
    return out


# --- 教务系统 cookie 缓存（本机快速复用；含时间戳，文件已 gitignore）----------

def save_jwxsd_cookies(cookies: dict, path: str = JWXT_COOKIE_CACHE) -> None:
    """保存教务系统 cookie 缓存（只写本机，不打印 cookie 值）。"""
    if not cookies:
        return
    doc = {"savedAt": int(time.time()), "cookies": dict(cookies)}
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, path)
    logger.info("教务系统 cookie 已缓存：%s（%d 个）", path, len(cookies))


def load_jwxsd_cookies(path: str = JWXT_COOKIE_CACHE, max_age: int = COOKIE_CACHE_TTL):
    """读取 cookie 缓存；不存在/过期/损坏返回 None。"""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    cookies = doc.get("cookies") or {}
    if not isinstance(cookies, dict) or not cookies:
        return None
    saved_at = int(doc.get("savedAt") or 0)
    if max_age and saved_at and (time.time() - saved_at) > max_age:
        logger.info("教务系统 cookie 缓存已过期（>%d 秒），将重新 SSO", max_age)
        return None
    return {str(k): str(v) for k, v in cookies.items() if k and v}


def clear_jwxsd_cookies(path: str = JWXT_COOKIE_CACHE) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def session_from_cookies(cookies: dict) -> "requests.Session":
    """用 cookie 字典构造访问教务系统的 requests.Session。"""
    if requests is None:
        raise JwxtError("缺少依赖 requests，请先执行：pip install requests")
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        "Referer": LOGIN_URL,
        "Connection": "keep-alive",
    })
    for name, value in (cookies or {}).items():
        s.cookies.set(str(name), str(value), domain="210.34.74.77", path="/")
    return s


# --- 门户 → 新教务系统：headless Edge 里点击入口并取 210.34.74.77 cookie ------

_PORTAL_HAS_TILE_JS = r"""(function(){
  try{
    function find(doc){
      if(!doc) return null;
      var hs = doc.querySelectorAll('h3');
      for(var i=0;i<hs.length;i++){
        if(((hs[i].textContent||'').trim()) === %s) return hs[i];
      }
      return null;
    }
    var f = document.getElementById('template-container');
    var doc = f ? (f.contentDocument || (f.contentWindow && f.contentWindow.document)) : null;
    return !!(find(doc) || find(document));
  }catch(e){ return false; }
})()"""

_PORTAL_CLICK_TILE_JS = r"""(function(){
  try{
    function find(doc){
      if(!doc) return null;
      var hs = doc.querySelectorAll('h3');
      for(var i=0;i<hs.length;i++){
        if(((hs[i].textContent||'').trim()) === %s) return hs[i];
      }
      return null;
    }
    var f = document.getElementById('template-container');
    var doc = f ? (f.contentDocument || (f.contentWindow && f.contentWindow.document)) : null;
    var h = find(doc) || find(document);
    if(!h) return {ok:false, reason:'tile not found'};
    var card = h.closest('.recuseapp-center') || h.closest('a,li,button,[onclick]') || h.parentElement || h;
    card.click();
    return {ok:true, tag:String(card.tagName||''), cls:String(card.className||'').slice(0,60)};
  }catch(e){ return {ok:false, reason:String(e)}; }
})()"""


def _portal_js(template: str) -> str:
    return template % json.dumps(PORTAL_TILE_TEXT)


class _Browser:
    """带远程调试端口的 Edge/Chrome；临时 profile 用后即删（不留在仓库）。"""

    def __init__(self, url: str = "about:blank", *, headless: bool = True, browser: str = None):
        self.browser_path = browser or find_browser()
        if not self.browser_path:
            raise JwxtError("未找到 Edge / Chrome（可加 --browser 指定 msedge.exe 路径）")
        self.port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="jwxt_profile_", dir=tempfile.gettempdir())
        self.headless = bool(headless)
        self.proc = None
        self.browser_ws = None
        self._page_cdp = None
        args = [
            self.browser_path,
            "--remote-debugging-port=%d" % self.port,
            "--user-data-dir=%s" % self.profile,
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--disable-features=Translate",
        ]
        if self.headless:
            args.append("--headless=new")
        args.append(url or "about:blank")
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            self._connect()
        except Exception:
            self.close()
            raise

    def _connect(self):
        deadline = time.time() + 20
        page_ws = None
        while time.time() < deadline:
            version = _json_get("http://127.0.0.1:%d/json/version" % self.port)
            if version:
                self.browser_ws = version.get("webSocketDebuggerUrl")
            targets = _json_get("http://127.0.0.1:%d/json/list" % self.port) or []
            pages = [t for t in targets if t.get("type") == "page"]
            chosen = pages[0] if pages else None
            if chosen and chosen.get("webSocketDebuggerUrl"):
                page_ws = chosen["webSocketDebuggerUrl"]
                break
            time.sleep(0.4)
        if not page_ws:
            raise FetchError("无法连接浏览器调试端口（%d）" % self.port)
        self._page_cdp = _CDP(page_ws)
        self._page_cdp.call("Network.enable", timeout=10)

    @property
    def page(self) -> "_CDP":
        return self._page_cdp

    def targets(self) -> list:
        return _json_get("http://127.0.0.1:%d/json/list" % self.port, timeout=2) or []

    def find_target(self, predicate, *, timeout: float = 30.0):
        deadline = time.time() + max(0.5, timeout)
        while time.time() < deadline:
            for t in self.targets():
                try:
                    if t.get("type") == "page" and predicate(t):
                        return t
                except Exception:
                    continue
            time.sleep(1.0)
        return None

    def connect_target(self, target) -> "_CDP":
        ws = (target or {}).get("webSocketDebuggerUrl")
        if not ws:
            raise FetchError("目标页面缺少 webSocketDebuggerUrl")
        cdp = _CDP(ws)
        try:
            cdp.call("Network.enable", timeout=10)
        except JwxtError:
            pass
        return cdp

    def close(self):
        if self.browser_ws:
            try:
                bc = _CDP(self.browser_ws, timeout=5)
                try:
                    bc.call("Browser.close", timeout=5)
                finally:
                    bc.close()
            except Exception:
                pass
        if self._page_cdp is not None:
            self._page_cdp.close()
            self._page_cdp = None
        if self.proc is not None:
            try:
                self.proc.wait(timeout=8)
            except Exception:
                _run_hidden(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"])
            if self.proc.poll() is None:
                _run_hidden(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"])
        # 临时 profile 是几千个小文件，必须清掉
        for _ in range(10):
            shutil.rmtree(self.profile, ignore_errors=True)
            if not os.path.exists(self.profile):
                break
            time.sleep(0.5)
        if os.path.exists(self.profile):
            logger.warning("临时浏览器 profile 未能完全清理：%s（可手动删除）", self.profile)


def _jwxt_cookies_from_cdp(cdp: _CDP) -> dict:
    result = cdp.call(
        "Network.getCookies",
        {"urls": [BASE_URL + PREFIX + "/", BASE_URL + "/"]},
        timeout=20,
    )
    cookies = result.get("cookies") or []
    mapping = {}
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        if name and value:
            mapping[str(name)] = str(value)
    if not mapping:
        raise FetchError("浏览器里没有拿到教务系统 cookie（SSO 可能未完成）")
    logger.info("已取得教务系统 cookie：%s", ", ".join(sorted(mapping)))
    return mapping


def portal_to_jwxt_cookies(portal_cookie_list: list, *, browser: str = None,
                           timeout: float = 180.0) -> dict:
    """headless Edge：注入门户 cookie → 打开门户 → 点「新教务系统」→ 取教务 cookie。"""
    br = _Browser("about:blank", headless=True, browser=browser)
    try:
        page = br.page
        page.call("Network.setCookies", {"cookies": portal_cookie_list}, timeout=15)
        page.call("Page.navigate", {"url": PORTAL_URL}, timeout=20)
        logger.info("已打开门户，等待「%s」入口出现…", PORTAL_TILE_TEXT)
        deadline = time.time() + max(30.0, timeout * 0.5)
        has_tile = False
        while time.time() < deadline:
            try:
                has_tile = bool(page.eval(_portal_js(_PORTAL_HAS_TILE_JS), timeout=10))
            except JwxtError:
                has_tile = False
            if has_tile:
                break
            time.sleep(1.2)
        if not has_tile:
            raise FetchError("门户里没找到「%s」入口（门户可能改版或登录态无效）" % PORTAL_TILE_TEXT)
        clicked = page.eval(_portal_js(_PORTAL_CLICK_TILE_JS), timeout=15)
        logger.info("已点击「%s」：%s", PORTAL_TILE_TEXT, clicked)
        target = br.find_target(lambda t: BASE_URL in (t.get("url") or ""),
                                timeout=max(20.0, timeout * 0.4))
        if target is None:
            href = ""
            try:
                href = page.eval("String(location.href)", timeout=8) or ""
            except JwxtError:
                pass
            if BASE_URL not in href:
                raise FetchError("点击「%s」后没有打开教务系统页面" % PORTAL_TILE_TEXT)
            return _jwxt_cookies_from_cdp(page)
        cdp = br.connect_target(target)
        try:
            return _jwxt_cookies_from_cdp(cdp)
        finally:
            cdp.close()
    finally:
        br.close()


def sso_login(account: str, password: str, *, use_cache: bool = True, force: bool = False,
              browser: str = None, timeout: int = PAGE_TIMEOUT, http_first: bool = True):
    """统一认证 → 教务系统；返回可用的 requests.Session。

    优先用本地 cookie 缓存（快）；失效/强制时走完整 SSO 并刷新缓存。
    http_first=True（2026-11-08 起默认）：先用纯 requests 的 sso_login_http()
    （本机 Edge 被策略拦截时仍可用）；仅在网络/结构类失败时回退旧 headless Edge 链路。
    """
    if use_cache and not force:
        cached = load_jwxsd_cookies()
        if cached:
            sess = session_from_cookies(cached)
            if check_logged_in(sess, timeout=timeout):
                logger.info("教务系统 cookie 缓存有效（%d 个），跳过统一认证", len(cached))
                return sess
            logger.info("教务系统 cookie 缓存已失效，重新走统一认证")
            clear_jwxsd_cookies()
    logger.info("统一认证登录 account=%s", mask_account(account))
    if http_first:
        try:
            return sso_login_http(account, password, timeout=max(15, timeout))
        except LoginError:
            raise
        except JwxtError as exc:
            logger.warning("纯 requests SSO 失败（%s），回退 headless Edge 链路", exc)
    logger.info("门户登录成功，使用 headless Edge 完成「门户 → 新教务系统」SSO…")
    portal = authserver_login(account, password, timeout=max(15, timeout))
    cookie_list = _requests_cookies(portal)
    cookies = portal_to_jwxt_cookies(cookie_list, browser=browser)
    save_jwxsd_cookies(cookies)
    sess = session_from_cookies(cookies)
    if not check_logged_in(sess, timeout=timeout):
        clear_jwxsd_cookies()
        raise LoginError("SSO 完成但教务系统会话无效（cookie 未生效），请重试或用 --manual")
    logger.info("教务系统登录成功（统一认证 SSO）")
    return sess


def manual_get_jwxt_cookies(*, login_timeout: float = 300.0, browser: str = None) -> dict:
    """人工辅助：可见 Edge 打开统一认证，用户手动登录后自动点「新教务系统」取 cookie。"""
    if requests is None:
        raise JwxtError("缺少依赖 requests，请先执行：pip install requests")
    if os.name != "nt":
        raise JwxtError("--manual 仅支持 Windows（依赖 Edge/Chrome + CDP）")
    br = _Browser(_auth_login_page_url(), headless=False, browser=browser)
    try:
        page = br.page
        logger.info("请在打开的浏览器窗口里用统一身份认证登录（最多等待 %d 秒）…",
                    int(login_timeout))
        deadline = time.time() + max(10.0, login_timeout)
        in_portal = False
        while time.time() < deadline:
            try:
                href = page.eval("String(location.href)", timeout=8) or ""
            except JwxtError:
                href = ""
            if "e.fjtcm.edu.cn" in href and "authserver" not in href:
                in_portal = True
                break
            time.sleep(1.5)
        if not in_portal:
            raise LoginError("手动登录超时（%d 秒内未检测到门户登录成功）" % int(login_timeout))
        logger.info("检测到门户登录成功，自动打开「%s」…", PORTAL_TILE_TEXT)

        target = None
        auto_clicked = False
        while time.time() < deadline:
            target = br.find_target(lambda t: BASE_URL in (t.get("url") or ""), timeout=1)
            if target:
                break
            if not auto_clicked:
                try:
                    if page.eval(_portal_js(_PORTAL_HAS_TILE_JS), timeout=8):
                        page.eval(_portal_js(_PORTAL_CLICK_TILE_JS), timeout=12)
                        auto_clicked = True
                except JwxtError:
                    pass
            if not auto_clicked:
                logger.info("如果没自动打开教务系统，请在门户页手动点击「%s」…", PORTAL_TILE_TEXT)
            time.sleep(1.5)
        if target is None:
            href = ""
            try:
                href = page.eval("String(location.href)", timeout=8) or ""
            except JwxtError:
                pass
            if BASE_URL in href:
                return _jwxt_cookies_from_cdp(page)
            raise FetchError("未能进入教务系统（请在门户页点「%s」后重试）" % PORTAL_TILE_TEXT)
        cdp = br.connect_target(target)
        try:
            return _jwxt_cookies_from_cdp(cdp)
        finally:
            cdp.close()
    finally:
        br.close()


# ---------------------------------------------------------------------------
# 课表抓取
# ---------------------------------------------------------------------------

def _looks_like_timetable(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    low = text.lower()
    if "kbtable" in low or "kbcontent" in low or "qz-weeklytable" in low:
        return True
    if "<table" in low and ("周次" in text or "课程表" in text):
        return True
    return False


def _discover_timetable_links(html_text: str):
    """从 xsMainV.jsp（或任意页面）里找课表相关链接。"""
    found = []
    for m in re.finditer(r"""["']([^"']*xskb[^"']*\.do[^"']*)["']""", html_text or "", re.I):
        found.append(m.group(1))
    for m in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", html_text or "", re.I):
        u = m.group(1)
        if re.search(r"(xskb|kbcx|kbxx)", u, re.I):
            found.append(u)
    out = []
    for u in found:
        u = htmlmod.unescape(u).strip()
        if not u or u.lower().startswith(("javascript:", "#")):
            continue
        full = urllib.parse.urljoin(MAIN_PAGE_URL, u)
        if full.startswith(BASE_URL) and full not in out:
            out.append(full)
    return out


def _save_fetched_html(text: str, url: str, term: str, path=LAST_HTML_PATH) -> None:
    """把抓到的课表 HTML 落盘，便于拿真实页面校准解析器（该文件已被 .gitignore）。"""
    if not path:
        return
    try:
        folder = os.path.dirname(os.path.abspath(path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = "<!-- jwxt fetch: url=%s term=%s at=%s -->\n" % (url, term, stamp)
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(header + (text or ""))
        logger.info("课表 HTML 已落盘：%s", path)
    except OSError as exc:  # 落盘失败不能影响主流程
        logger.warning("课表 HTML 落盘失败：%s", exc)


def fetch_timetable(session, term: str, *, save_path=LAST_HTML_PATH,
                    timeout: int = PAGE_TIMEOUT) -> str:
    """自动发现并抓取课表页 HTML（成功返回 HTML 字符串）。"""
    term = str(term or "").strip()
    quoted = urllib.parse.quote(term)
    candidates = [
        # 新教务系统（2026 改版）：周表视图
        ("GET", TIMETABLE_URL + "?viweType=0", None),
        ("GET", TIMETABLE_URL + "?viweType=0&xnxq01id=" + quoted, None),
        # 旧版（强智 jsxsd）候选，保留兜底
        ("GET", TIMETABLE_URL + "?Ves632DSdyV=NEW_XSD_PYGL&xnxq01id=" + quoted, None),
        ("GET", TIMETABLE_URL, None),
        ("POST", TIMETABLE_URL + "?Ves632DSdyV=NEW_XSD_PYGL",
         {"xnxq01id": term, "zc": "", "sfFd": ""}),
        ("POST", TIMETABLE_URL, {"xnxq01id": term}),
    ]

    last_text, last_url = None, None
    for method, url, data in candidates:
        try:
            r = _request(session, method, url, data=data, timeout=timeout)
        except JwxtError as exc:
            logger.warning("候选课表页请求失败 %s：%s", url, exc)
            continue
        text = r.text or ""
        if _looks_like_login(text):
            raise LoginError("课表页返回登录页：登录状态已失效（请重新 --save-creds 或 --check）")
        last_text, last_url = text, r.url
        if _looks_like_timetable(text):
            _save_fetched_html(text, r.url, term, save_path)
            logger.info("课表页命中：%s（%d 字节）", r.url, len(text))
            return text
        logger.info("候选页无课表标记：%s（%d 字节）", r.url, len(text))

    # 兜底：从登录后主页面菜单里发现课表链接
    try:
        main = _request(session, "GET", MAIN_PAGE_URL, timeout=timeout)
        if _looks_like_login(main.text or ""):
            raise LoginError("主页面返回登录页：登录状态已失效")
        for url in _discover_timetable_links(main.text or "")[:6]:
            try:
                r = _request(session, "GET", url, timeout=timeout)
            except JwxtError as exc:
                logger.warning("菜单课表链接请求失败 %s：%s", url, exc)
                continue
            if _looks_like_login(r.text or ""):
                raise LoginError("课表页返回登录页：登录状态已失效")
            last_text, last_url = r.text or "", r.url
            if _looks_like_timetable(last_text):
                _save_fetched_html(last_text, r.url, term, save_path)
                logger.info("课表页命中（菜单发现）：%s", r.url)
                return last_text
            logger.info("菜单链接无课表标记：%s", r.url)
    except LoginError:
        raise
    except JwxtError as exc:
        logger.warning("主页面发现失败：%s", exc)

    if last_text:
        _save_fetched_html(last_text, last_url or "", term, save_path)
    raise FetchError("未找到课表页：已尝试 %d 个候选地址（可把 _last_timetable.html 发给 Lead 校准）"
                     % len(candidates))


# --- app.do JSON 兜底（同一套教务系统的课表 JSON 接口） --------------------

def _json_item_key(item: dict) -> tuple:
    return (
        _norm(item.get("kcmc")), _norm(item.get("jsxm")), _norm(item.get("jsmc")),
        str(item.get("kcsj") or ""), _norm(item.get("kkzc")),
        str(item.get("sjbz") or ""),
    )


def fetch_timetable_json(session, account: str, term: str, *, timeout: int = PAGE_TIMEOUT):
    """尝试 app.do?method=getKbcxAzc 的 JSON 课表接口；不可用返回 None。"""
    account = str(account or "").strip()
    if not account:
        return None

    def call(zc):
        r = _request(
            session, "GET", APP_DO_URL, timeout=timeout,
            params={"method": "getKbcxAzc", "xh": account, "xnxqid": term, "zc": str(zc)},
        )
        txt = (r.text or "").strip()
        if not txt.startswith("["):
            logger.info("app.do 未返回 JSON 数组（可能需 token 鉴权），跳过 JSON 兜底")
            return None
        try:
            data = json.loads(txt)
        except ValueError:
            logger.info("app.do 返回内容不是合法 JSON，跳过")
            return None
        return data if isinstance(data, list) else None

    data = call(0)
    if data is None:
        return None
    items = {_json_item_key(x): x for x in data if isinstance(x, dict)}
    if not items:
        # 有些实现只认具体周次：逐周取并集
        for zc in range(1, 21):
            got = call(zc)
            if got is None:
                break
            for x in got:
                if isinstance(x, dict):
                    items[_json_item_key(x)] = x
    logger.info("app.do JSON 课表取得 %d 条", len(items))
    return list(items.values()) or None


# ---------------------------------------------------------------------------
# 课表解析
# ---------------------------------------------------------------------------

_KB_DIV_RE = re.compile(
    r"""<div\b[^>]*\bclass\s*=\s*["'][^"']*kbcontent[^"']*["'][^>]*>(.*?)</div\s*>""",
    re.I | re.S,
)
_TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table\s*>", re.I | re.S)
_KBTABLE_RE = re.compile(
    r"""<table\b[^>]*\bid\s*=\s*["']?kbtable["']?[^>]*>(.*?)</table\s*>""", re.I | re.S
)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr\s*>", re.I | re.S)
_CELL_RE = re.compile(r"<t([dh])\b([^>]*)>(.*?)</t\1\s*>", re.I | re.S)
_FONT_RE = re.compile(r"<font\b([^>]*)>(.*?)</font\s*>", re.I | re.S)

_DAY_NAMES = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_TEACHER_HINT_RE = re.compile(r"(老师|教师|教授|讲师|助教|研究员|工程师|博士)")
_ROOM_HINT_RE = re.compile(r"(楼|室|场|馆|教室|机房|实验|中心|校区|号|栋|区|厅|阶梯|报告厅)")


def _split_lines(fragment: str):
    """按 <br>/<hr> 切行并去标签。"""
    lines = []
    for part in re.split(r"<hr\b[^>]*>", fragment or "", flags=re.I):
        for seg in re.split(r"<br\b[^>]*>", part, flags=re.I):
            t = _text_only(seg)
            if t:
                lines.append(t)
    return lines


def _split_hr(fragment: str):
    return [seg for seg in re.split(r"<hr\b[^>]*>", fragment or "", flags=re.I) if seg.strip()]


def _extract_blocks(cell_html: str):
    """单元格里的课程块：优先 div.kbcontent（同格多课就是多个 div）；无则整格视作一块。"""
    divs = _KB_DIV_RE.findall(cell_html or "")
    if divs:
        blocks = []
        for d in divs:
            blocks.extend(_split_hr(d))
        return [b for b in blocks if _text_only(b) or _FONT_RE.search(b)]
    return []


def _day_of(text: str):
    m = re.search(r"(?:星期|周)\s*([一二三四五六日天])", text or "")
    return _DAY_NAMES.get(m.group(1)) if m else None


def _parse_sections_in_text(text: str):
    """从文本里找「第X-Y节」/「第X节」/「X-Y节」，返回 (start, end) 或 None。"""
    t = _num_norm(text)
    m = re.search(r"第\s*(\d{1,2})\s*(?:[-,、])\s*(\d{1,2})\s*节", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"第\s*(\d{1,2})\s*节", t)
    if m:
        return int(m.group(1)), int(m.group(1))
    m = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s*节", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def _weeks_from_text(s: str):
    """从已归一化文本里抽周次集合（可能为空集）。"""
    weeks = set()
    if not s:
        return weeks
    odd = "单" in s
    even = "双" in s
    for m in re.finditer(r"(\d{1,2})\s*(?:-\s*(\d{1,2}))?", s):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if b < a:
            a, b = b, a
        if b - a > 40:  # 明显是误匹配（比如时间 08:00）
            b = a
        for n in range(a, b + 1):
            if 1 <= n <= 30:
                weeks.add(n)
    if odd:
        weeks = {n for n in weeks if n % 2 == 1}
    if even:
        weeks = {n for n in weeks if n % 2 == 0}
    return weeks


def weeks_to_set(text, default: str = DEFAULT_WEEKS):
    """把「3-5,7-14(周)」「1-16周(单)」等解析成周次集合。"""
    weeks = _weeks_from_text(_num_norm(text))
    if not weeks:
        weeks = _weeks_from_text(_num_norm(default))
    if not weeks:
        weeks = set(range(1, 21))
    return weeks


def compress_weeks(weeks) -> str:
    """把周次集合压成英文逗号/短横线格式：2-4,6,9-18。"""
    nums = sorted({int(w) for w in weeks if str(w).strip().isdigit() and 1 <= int(w) <= 30})
    if not nums:
        return ""
    parts = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        run = j - i + 1
        if run >= 2:
            parts.append("%d-%d" % (nums[i], nums[j]))
        else:
            parts.append(str(nums[i]))
        i = j + 1
    return ",".join(parts)


def _parse_weeks_text(text, default: str = DEFAULT_WEEKS) -> str:
    return compress_weeks(weeks_to_set(text, default)) or default


def _parse_block(block_html: str):
    """解析单元格里的一个课程块 → {name, teacher, room, weeks, sections}。"""
    fonts = []
    for attrs, inner in _FONT_RE.findall(block_html or ""):
        title = _attr(attrs, "title")
        val = _text_only(inner)
        if val:
            fonts.append((title, val))

    name = ""
    teachers, weeks_vals, rooms = [], [], []
    for title, val in fonts:
        t = re.sub(r"\s+", "", title or "")
        if ("课程" in t and ("名称" in t or "名" in t)) or t in ("课程", "科目", "课程名"):
            name = name or val
        elif "老师" in t or "教师" in t or "授课" in t or "任课" in t:
            teachers.append(val)
        elif "周次" in t:
            weeks_vals.append(val)
        elif "教室" in t or "地点" in t or "场地" in t:
            rooms.append(val)

    plain = _FONT_RE.sub("", block_html or "")
    lines = _split_lines(plain)
    if not name and lines:
        name = lines.pop(0)

    # 周次（没有 font 标注时从普通行里找）
    if not weeks_vals:
        for ln in list(lines):
            if "周" in ln and re.search(r"\d", ln):
                weeks_vals.append(ln)
                lines.remove(ln)
                break

    # 教师
    if not teachers:
        idx = next((i for i, ln in enumerate(lines) if _TEACHER_HINT_RE.search(ln)), None)
        if idx is None:
            idx = next((i for i, ln in enumerate(lines)
                        if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", ln)), None)
        if idx is not None:
            teachers.append(lines.pop(idx))

    # 教室（优先从后往前找像地点的行）
    if not rooms:
        room_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if _ROOM_HINT_RE.search(lines[i]):
                room_idx = i
                break
        if room_idx is None and lines:
            room_idx = len(lines) - 1
        if room_idx is not None:
            rooms.append(lines.pop(room_idx))

    if not name and lines:
        name = lines[0]

    text_for_sections = " ".join([v for _, v in fonts] + lines)
    sections = _parse_sections_in_text(text_for_sections)

    teacher = "、".join(dict.fromkeys(t for t in teachers if t))
    room = "、".join(dict.fromkeys(r for r in rooms if r))
    weeks = _parse_weeks_text(weeks_vals[0] if weeks_vals else "")
    return {
        "name": _norm(name),
        "teacher": teacher,
        "room": room,
        "weeks": weeks,
        "sections": sections,
    }


def _make_cell(attrs: str, inner: str, has_kbcontent: bool):
    rowspan = _int_attr(attrs, "rowspan", 1)
    colspan = _int_attr(attrs, "colspan", 1)
    if has_kbcontent:
        blocks = _extract_blocks(inner)
    else:
        blocks = [inner] if _text_only(inner) else []
    return {
        "rowspan": max(1, rowspan),
        "colspan": max(1, colspan),
        "html": inner,
        "lines": _split_lines(inner),
        "blocks": blocks,
        "col": 0,
    }


_NUM_ATTR_RE = re.compile(r"(\d+)")


def _int_attr(attrs: str, name: str, default: int) -> int:
    val = _attr(attrs, name)
    m = _NUM_ATTR_RE.search(val or "")
    if not m:
        return default
    try:
        return max(1, int(m.group(1)))
    except ValueError:
        return default


def _merge_courses(courses):
    """同一门课（同名/师/地/星期/节次）合并周次；parity 固定 all。"""
    merged = {}
    order = []
    for c in courses:
        key = (c["name"], c["teacher"], c["room"], c["day"], c["start"], c["end"])
        if key not in merged:
            merged[key] = dict(c)
            merged[key]["_weeks"] = weeks_to_set(c.get("weeks"))
            order.append(key)
        else:
            merged[key]["_weeks"] |= weeks_to_set(c.get("weeks"))
    out = []
    for key in order:
        c = merged[key]
        weeks = compress_weeks(c.pop("_weeks")) or DEFAULT_WEEKS
        out.append({
            "name": c["name"],
            "teacher": c["teacher"],
            "room": c["room"],
            "day": c["day"],
            "start": c["start"],
            "end": c["end"],
            "weeks": weeks,
            "parity": "all",
        })
    out.sort(key=lambda x: (x["day"], x["start"], x["end"], x["name"]))
    return out


def _extract_timetable_fragment(html_text: str):
    m = _KBTABLE_RE.search(html_text or "")
    if m:
        return m.group(1)
    tables = list(_TABLE_RE.finditer(html_text or ""))
    for m in tables:
        if "kbcontent" in m.group(1).lower():
            return m.group(1)
    # 没有 kbcontent 的朴素课表（仍是 7 列的周课表）
    for m in tables:
        body = m.group(1)
        if ("星期" in body or "周一" in body) and "节" in body and body.count("<tr") >= 3:
            return body
    if "kbcontent" in (html_text or "").lower():
        return html_text
    return None


def _fallback_blocks_parse(fragment: str):
    """没有 <tr> 时（极端兜底）：按每 7 个课程块一行硬排。"""
    divs = _KB_DIV_RE.findall(fragment or "")
    if not divs:
        return []
    courses = []
    for i, div in enumerate(divs):
        parsed = _parse_block(div)
        if not parsed["name"]:
            continue
        big = i // 7
        day = i % 7
        start, end = big * 2 + 1, big * 2 + 2
        if start > 12:
            continue
        courses.append({
            "name": parsed["name"], "teacher": parsed["teacher"], "room": parsed["room"],
            "day": day, "start": start, "end": min(12, end),
            "weeks": parsed["weeks"], "parity": "all",
        })
    return _merge_courses(courses)


def _parse_table_fragment(fragment: str):
    """解析课表表格片段 → 课程列表。"""
    has_kbcontent = "kbcontent" in (fragment or "").lower()
    rows = []
    for m in _ROW_RE.finditer(fragment or ""):
        cells = [_make_cell(attrs, inner, has_kbcontent)
                 for _tag, attrs, inner in _CELL_RE.findall(m.group(1))]
        if cells:
            rows.append(cells)
    if not rows:
        return _fallback_blocks_parse(fragment)

    # 1) 处理 rowspan/colspan 占位，给每格定列号
    occupied = set()
    for r, cells in enumerate(rows):
        col = 0
        for cell in cells:
            while (r, col) in occupied:
                col += 1
            cell["col"] = col
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    occupied.add((r + dr, col + dc))
            col += cell["colspan"]

    # 2) 找表头（含星期几），建立「列号 → day」映射
    header_rows = set()
    day_map = {}
    for r, cells in enumerate(rows):
        mapped = {}
        for cell in cells:
            day = _day_of(" ".join(cell["lines"])) or _day_of(_text_only(cell["html"]))
            if day is not None:
                mapped[cell["col"]] = day
        if len(mapped) >= 5:
            header_rows.add(r)
            if not day_map:
                day_map = mapped

    max_cols = max((len(row) for row in rows), default=0)
    time_col = (min(day_map) >= 1) if day_map else (max_cols >= 8)

    # 3) 每行的节次范围（从时间列文字解析；解析不到按大节顺序 1-2/3-4/...）
    section_map = {}
    big = 0
    for r, cells in enumerate(rows):
        if r in header_rows:
            continue
        sections = None
        for cell in cells:
            if cell["blocks"]:
                continue
            sections = _parse_sections_in_text(" ".join(cell["lines"]))
            if sections:
                break
        if not sections:
            sections = (big * 2 + 1, big * 2 + 2)
        section_map[r] = sections
        big += 1

    # 4) 逐格解析课程
    courses = []
    for r, cells in enumerate(rows):
        if r in header_rows:
            continue
        for cell in cells:
            if time_col and cell["col"] == 0:
                continue
            if not cell["blocks"]:
                continue

            if day_map:
                day = day_map.get(cell["col"])
            else:
                day = cell["col"] - (1 if time_col else 0)
            if day is None or day < 0 or day > 6:
                continue

            covered = [section_map[rr] for rr in range(r, r + cell["rowspan"])
                       if rr in section_map]
            if covered:
                sec_start = min(x[0] for x in covered)
                sec_end = max(x[1] for x in covered)
            elif r in section_map:
                sec_start, sec_end = section_map[r]
            else:
                continue

            for block in cell["blocks"]:
                parsed = _parse_block(block)
                if not parsed["name"]:
                    continue
                if re.fullmatch(r"(无课|空|休息|自习|—+|-+)", parsed["name"]):
                    continue
                start, end = sec_start, sec_end
                if parsed["sections"]:
                    start, end = parsed["sections"]
                if start > 12 or end < 1:
                    continue
                start = max(1, min(12, start))
                end = max(1, min(12, end))
                if end < start:
                    end = start
                courses.append({
                    "name": parsed["name"],
                    "teacher": parsed["teacher"],
                    "room": parsed["room"],
                    "day": day,
                    "start": start,
                    "end": end,
                    "weeks": parsed["weeks"],
                    "parity": "all",
                })
    return _merge_courses(courses)


def _detect_term(html_text: str) -> str:
    """从课表页/学期下拉框里识别当前学期，例如 2026-2027-1。"""
    text = html_text or ""
    patterns = (
        r"""<option[^>]*\bvalue\s*=\s*["'](\d{4}-\d{4}-[12])["'][^>]*\bselected\b""",
        r"""<option[^>]*\bselected\b[^>]*\bvalue\s*=\s*["'](\d{4}-\d{4}-[12])["']""",
        r"""<option[^>]*\bselected\b[^>]*>\s*(\d{4}-\d{4}-[12])\s*</option>""",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1)
    m = re.search(r"xnxq01id[\s\S]{0,200}?(\d{4}-\d{4}-[12])", text)
    if m:
        return m.group(1)
    return ""


# ---------------------------------------------------------------------------
# 新版（2026.11 起）课表解析：table.qz-weeklyTable
#
# 结构：thead 一行 8 个 th：周次 / 星期日 / 星期一 / … / 星期六
#       tbody 每行首列是节次标签（如「一（1-2节） 08:10~09:40」），后 7 列是课程格；
#       每个 td 里有若干 li.courselists-item：
#         <div class="qz-hasCourse-title">高等数学</div>
#         <span class="qz-hasCourse-abbrinfo">老师:龚志伟;时间:2-3周[1-3节];地点:自强楼(教室01104)</span>
#       （同 td 里的 .qz-tooltip 是重复信息，本解析只认 li.courselists-item）
#
# ⚠️ 重要实测结论（2026-11-03，用「有课表课程」列表 viweType=1 交叉核对）：
#   thead 的 th 顺序是服务器模板 bug（"星期日"打头），tbody 数据列实际是
#   **周一在前**：col1=周一(day0) … col7=周日(day6)。例如高等数学在 col1，
#   列表视图明确写「周一第1-3节」「周一第1、2节」「周三第6-8节」「周五第1-3节」。
#   因此默认 day_order="position"（按列位置），而不是按 th 文本。可用 --day-order header
#   在极端情况下覆盖为按 th 文本映射。
# ---------------------------------------------------------------------------

_QZ_TABLE_RE = re.compile(
    r"""<table\b[^>]*\bclass\s*=\s*["'][^"']*qz-weeklyTable[^"']*["'][^>]*>(.*?)</table\s*>""",
    re.I | re.S,
)
_QZ_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr\s*>", re.I | re.S)
_QZ_LI_RE = re.compile(
    r"""<li\b[^>]*\bclass\s*=\s*["'][^"']*\bcourselists-item\b[^"']*["'][^>]*>(.*?)</li\s*>""",
    re.I | re.S,
)
_QZ_TITLE_RE = re.compile(
    r"""<div\b[^>]*\bclass\s*=\s*["'][^"']*\bqz-hasCourse-title\b[^"']*["'][^>]*>(.*?)</div\s*>""",
    re.I | re.S,
)
_QZ_ABBR_RE = re.compile(
    r"""<span\b[^>]*\bclass\s*=\s*["'][^"']*\bqz-hasCourse-abbrinfo\b[^"']*["'][^>]*>(.*?)</span\s*>""",
    re.I | re.S,
)
_QZ_TIME_RE = re.compile(
    r"""(\d{1,2}(?:\s*-\s*\d{1,2})?(?:\s*,\s*\d{1,2}(?:\s*-\s*\d{1,2})?)*)\s*周\s*[\[［]\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*节\s*[\]］]""",
    re.I,
)
_QZ_ROW_PERIOD_RE = re.compile(r"[（(]\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*节\s*[)）]")
_QZ_INDEX_TITLE_RE = re.compile(
    r"""<div\b[^>]*\bclass\s*=\s*["'][^"']*\bindex-title\b[^"']*["'][^>]*>(.*?)</div\s*>""",
    re.I | re.S,
)


def _parse_qz_abbr(abbr_text: str):
    """解析「老师:龚志伟;时间:2-3周[1-3节];地点:自强楼(教室01104)」→ (老师, 时间, 地点)。"""
    fields = {}
    for part in re.split(r"[;；]", abbr_text or ""):
        if ":" in part or "：" in part:
            key, value = re.split(r"[:：]", part, 1)
            fields[key.strip()] = value.strip()
    teacher = fields.get("老师") or fields.get("教师") or fields.get("任课教师") or ""
    time_text = fields.get("时间") or fields.get("上课时间") or ""
    room = fields.get("地点") or fields.get("教室") or fields.get("上课地点") or ""
    return teacher, time_text, room


def _parse_qz_row_period(cell_html: str):
    """从节次标签格（如「一（1-2节） 08:10~09:40」）取 (start, end)。"""
    m = _QZ_INDEX_TITLE_RE.search(cell_html or "")
    text = _num_norm(_text_only(m.group(1))) if m else _num_norm(_text_only(cell_html))
    mm = _QZ_ROW_PERIOD_RE.search(text)
    if not mm:
        return None
    start = int(mm.group(1))
    end = int(mm.group(2)) if mm.group(2) else start
    return start, end


def _extract_qz_table(html_text: str):
    m = _QZ_TABLE_RE.search(html_text or "")
    return m.group(1) if m else None


def _parse_qz_weekly_table(fragment: str, *, day_order: str = "column"):
    """解析 qz-weeklyTable 片段 → 课程列表（day/start/end/weeks/teacher/room）。"""
    rows = []
    for m in _QZ_ROW_RE.finditer(fragment or ""):
        cells = _CELL_RE.findall(m.group(1))
        if cells:
            rows.append(cells)
    if not rows:
        return []

    header_cells = None
    body_rows = []
    for cells in rows:
        if header_cells is None and any(tag.lower() == "h" for tag, _a, _i in cells):
            header_cells = cells
            continue
        body_rows.append(cells)
    if not body_rows:
        return []

    # 表头：列号 → day（只用于 sanity 检查 / --day-order header）
    header_day = {}
    if header_cells:
        for idx, (_tag, _attrs, inner) in enumerate(header_cells):
            d = _day_of(_text_only(inner))
            if d is not None:
                header_day[idx] = d
    offset = min(header_day) if header_day else 1
    header_order = [header_day.get(i) for i in range(offset, offset + 7)]
    if header_order == [0, 1, 2, 3, 4, 5, 6]:
        logger.debug("qz 周表表头顺序：周一在前（与数据列一致）")
    elif header_order and set(header_order) == {0, 1, 2, 3, 4, 5, 6}:
        logger.warning("qz 周表表头顺序为 %s（服务器模板 bug）；实测 tbody 数据列是「周一在前」，"
                       "按列位置映射", header_order)

    # rowspan/colspan 还原二维网格
    occupied = set()
    grid = {}
    row_period = {}
    for r, cells in enumerate(body_rows):
        col = 0
        for _tag, attrs, inner in cells:
            while (r, col) in occupied:
                col += 1
            rowspan = _int_attr(attrs, "rowspan", 1)
            colspan = _int_attr(attrs, "colspan", 1)
            for dr in range(rowspan):
                for dc in range(colspan):
                    occupied.add((r + dr, col + dc))
            grid[(r, col)] = (attrs, inner, rowspan)
            col += colspan

    # 每行节次（首列 timeTd 的「一（1-2节）」）；解析不到按大节兜底
    for r, cells in enumerate(body_rows):
        period = None
        for _tag, attrs, inner in cells:
            if re.search(r"""\bname\s*=\s*["']timeTd["']""", attrs, re.I):
                period = _parse_qz_row_period(inner)
                if period:
                    break
        if period is None and cells:
            period = _parse_qz_row_period(cells[0][2])
        row_period[r] = period or (r * 2 + 1, r * 2 + 2)

    courses = []
    for (r, col), (attrs, inner, rowspan) in grid.items():
        if "courselists-item" not in inner:
            continue
        if day_order == "header" and header_day:
            day = header_day.get(col)
        else:
            day = col - offset
        if day is None or day < 0 or day > 6:
            continue

        covered = [row_period[rr] for rr in range(r, r + rowspan) if rr in row_period]
        if covered:
            row_start = min(p[0] for p in covered)
            row_end = max(p[1] for p in covered)
        else:
            row_start, row_end = row_period[r]

        for li_html in _QZ_LI_RE.findall(inner):
            title_m = _QZ_TITLE_RE.search(li_html)
            name = _text_only(title_m.group(1)) if title_m else ""
            if not name:
                continue
            abbr_m = _QZ_ABBR_RE.search(li_html)
            teacher, time_text, room = _parse_qz_abbr(
                _text_only(abbr_m.group(1)) if abbr_m else "")

            matches = list(_QZ_TIME_RE.finditer(_num_norm(time_text)))
            if not matches:
                # 只写了周次没写节次：用行标签的节次兜底
                weeks_set = _weeks_from_text(_num_norm(time_text))
                if not weeks_set:
                    continue
                courses.append({
                    "name": name, "teacher": teacher, "room": room,
                    "day": day, "start": row_start, "end": row_end,
                    "weeks": compress_weeks(weeks_set), "parity": "all",
                })
                continue

            for match in matches:
                weeks_set = _weeks_from_text(_num_norm(match.group(1)))
                if not weeks_set:
                    continue
                start = int(match.group(2))
                end = int(match.group(3)) if match.group(3) else start
                if start > 12 or end < 1:
                    continue
                start = max(1, start)
                end = min(12, max(start, end))
                courses.append({
                    "name": name, "teacher": teacher, "room": room,
                    "day": day, "start": start, "end": end,
                    "weeks": compress_weeks(weeks_set), "parity": "all",
                })
    return _merge_courses(courses)


_LIST_VIEW_ITEM_RE = re.compile(
    r"周([一二三四五六日天])\s*第\s*([\d、,，\-~—–]+)\s*节\s*[｛{]\s*([\d,\-]+)\s*[｝}]"
)


def parse_list_view_time(text: str):
    """解析「有课表课程」列表的上课时间文案，用于交叉校验周表 day 映射。

    例：「周二第3-5节{2,15}全周;周二第3-5节{3,7,9,13}全周」
      → [{"day":1,"start":3,"end":5,"weeks":"2,15"}, {"day":1,...,"weeks":"3,7,9,13"}]
    """
    out = []
    normalized = _num_norm(text).replace("、", ",")
    for match in _LIST_VIEW_ITEM_RE.finditer(normalized):
        day = _DAY_NAMES.get(match.group(1))
        if day is None:
            continue
        nums = [int(x) for x in re.findall(r"\d+", match.group(2))]
        if not nums:
            continue
        start, end = min(nums), max(nums)
        if not (1 <= start <= end <= 12):
            continue
        weeks_set = _weeks_from_text(match.group(3))
        if not weeks_set:
            continue
        out.append({"day": day, "start": start, "end": end,
                    "weeks": compress_weeks(weeks_set)})
    return out


def parse_timetable(html_text: str, term_start: str = "", *, day_order: str = "column") -> dict:
    """把课表 HTML 解析成站点结构：{"c":[...], "t":"YYYY-MM-DD", "meta":{...}}。

    day_order: "column"（默认，按周表数据列位置：col1=周一）| "header"（按 th 文本，仅调试）。
    """
    if not html_text or not str(html_text).strip():
        raise ParseError("课表 HTML 为空")
    html_text = str(html_text)

    qz_fragment = _extract_qz_table(html_text)
    if qz_fragment is not None:
        courses = _parse_qz_weekly_table(qz_fragment, day_order=day_order)
        parser = "qz-weekly"
        if not courses:
            raise ParseError("找到 qz-weeklyTable 但未解析出课程（结构可能变化，请把 "
                             "_last_timetable.html 发给 Lead）")
    else:
        fragment = _extract_timetable_fragment(html_text)
        if fragment is None:
            raise ParseError("HTML 里未找到课表表格（qz-weeklyTable / #kbtable / .kbcontent）")
        courses = _parse_table_fragment(fragment)
        parser = "kbcontent"
        if not courses:
            raise ParseError("找到课表表格但未解析出课程（结构可能变化，请把 "
                             "_last_timetable.html 发给 Lead）")
    return {
        "c": courses,
        "t": normalize_term_start(term_start),
        "meta": {
            "source": "html",
            "parser": parser,
            "term": _detect_term(html_text),
            "count": len(courses),
        },
    }


def parse_api_timetable(items, term_start: str = "") -> dict:
    """把 app.do?method=getKbcxAzc 的 JSON 解析成站点结构。"""
    courses = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = _norm(it.get("kcmc"))
        if not name:
            continue
        teacher = _norm(it.get("jsxm"))
        room = _norm(it.get("jsmc"))
        kcsj = re.sub(r"\D", "", str(it.get("kcsj") or ""))
        if len(kcsj) < 5:
            continue
        day = int(kcsj[0]) - 1
        start = int(kcsj[1:3])
        end = int(kcsj[3:5])
        if day < 0 or day > 6 or start < 1 or start > 12:
            continue
        end = max(start, min(12, end))
        weeks = _parse_weeks_text(_norm(it.get("kkzc")))
        sjbz = str(it.get("sjbz") or "0").strip()
        if sjbz in ("1", "2"):
            ws = weeks_to_set(weeks)
            keep_odd = sjbz == "1"
            weeks = compress_weeks({n for n in ws if (n % 2 == 1) == keep_odd}) or weeks
        courses.append({
            "name": name, "teacher": teacher, "room": room,
            "day": day, "start": start, "end": end,
            "weeks": weeks, "parity": "all",
        })
    if not courses:
        raise ParseError("app.do JSON 里没有可用的课程数据")
    return {
        "c": _merge_courses(courses),
        "t": normalize_term_start(term_start),
        "meta": {"source": "app.do", "term": "", "count": len(courses)},
    }


def clean_courses(courses) -> list:
    """最终输出前再兜底清洗一遍（防止个别脏数据让站点渲染出错）。"""
    out = []
    seen = set()
    for c in courses or []:
        try:
            name = _norm(c.get("name"))
            if not name:
                continue
            day = int(c.get("day"))
            start = int(c.get("start"))
            end = int(c.get("end"))
        except (TypeError, ValueError):
            continue
        if not (0 <= day <= 6 and 1 <= start <= 12):
            continue
        end = max(start, min(12, end))
        weeks = compress_weeks(weeks_to_set(c.get("weeks")))
        if not weeks:
            continue
        key = (name, day, start, end, weeks, _norm(c.get("teacher")), _norm(c.get("room")))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name": name,
            "teacher": _norm(c.get("teacher")),
            "room": _norm(c.get("room")),
            "day": day,
            "start": start,
            "end": end,
            "weeks": weeks,
            "parity": "all",
        })
    out.sort(key=lambda x: (x["day"], x["start"], x["end"], x["name"]))
    return out


# ---------------------------------------------------------------------------
# 凭据存储：Windows DPAPI（无第三方依赖）
# ---------------------------------------------------------------------------

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _make_blob(data: bytes):
    buf = ctypes.create_string_buffer(data, max(1, len(data)))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    return blob, buf


def _crypt32():
    if os.name != "nt":
        raise JwxtError("DPAPI 凭据加密仅支持 Windows")
    dll = ctypes.WinDLL("crypt32", use_last_error=True)
    dll.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.c_wchar_p, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    dll.CryptProtectData.restype = wt.BOOL
    dll.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    dll.CryptUnprotectData.restype = wt.BOOL
    return dll


def dpapi_protect(data: bytes, entropy: bytes = CREDS_ENTROPY) -> bytes:
    """CryptProtectData：密文只能由当前 Windows 用户解开。"""
    dll = _crypt32()
    in_blob, _in_buf = _make_blob(data)
    ent_blob, _ent_buf = _make_blob(entropy)
    out_blob = _DATA_BLOB()
    ok = dll.CryptProtectData(
        ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None, 0x01,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise JwxtError("CryptProtectData 失败（%s）" % ctypes.get_last_error())
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.WinDLL("kernel32", use_last_error=True).LocalFree(out_blob.pbData)


def dpapi_unprotect(data: bytes, entropy: bytes = CREDS_ENTROPY) -> bytes:
    dll = _crypt32()
    in_blob, _in_buf = _make_blob(data)
    ent_blob, _ent_buf = _make_blob(entropy)
    out_blob = _DATA_BLOB()
    ok = dll.CryptUnprotectData(
        ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None, 0x01,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise JwxtError("CryptUnprotectData 失败（%s）：凭据文件损坏或换过 Windows 用户"
                        % ctypes.get_last_error())
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.WinDLL("kernel32", use_last_error=True).LocalFree(out_blob.pbData)


def save_credentials(account: str, password: str, path: str = CREDS_PATH) -> None:
    """DPAPI 加密写入凭据文件（原子替换）。"""
    payload = json.dumps({"v": 1, "account": account, "password": password},
                         ensure_ascii=False).encode("utf-8")
    blob = dpapi_protect(payload)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)
    logger.info("凭据已加密保存：%s（仅当前 Windows 用户可解，勿上传/勿进 Git）", path)


def load_credentials(path: str = CREDS_PATH):
    """读取凭据；文件不存在返回 None，损坏抛 JwxtError。"""
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        blob = f.read()
    try:
        data = json.loads(dpapi_unprotect(blob).decode("utf-8"))
    except (ValueError, JwxtError) as exc:
        raise JwxtError("凭据文件无法解析（%s）：请重新运行 --save-creds" % exc) from exc
    account = str(data.get("account") or "")
    password = str(data.get("password") or "")
    if not account or not password:
        raise JwxtError("凭据文件内容不完整：请重新运行 --save-creds")
    return account, password


def credentials_path() -> str:
    return CREDS_PATH


# ---------------------------------------------------------------------------
# 剪贴板 / 隐藏进程小工具
# ---------------------------------------------------------------------------

def copy_to_clipboard(text: str) -> bool:
    """把文本写入 Windows 剪贴板（ctypes CF_UNICODETEXT，不启动外部进程）。"""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = wt.BOOL
        user32.EmptyClipboard.restype = wt.BOOL
        user32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.CloseClipboard.restype = wt.BOOL
        kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = wt.BOOL

        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            data = str(text).encode("utf-16-le") + b"\x00\x00"
            handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            if not handle:
                return False
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                kernel32.GlobalFree(handle)
                return False
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            return bool(user32.SetClipboardData(13, handle))  # CF_UNICODETEXT
        finally:
            user32.CloseClipboard()
    except Exception as exc:  # pragma: no cover - 仅 Windows 交互环境
        logger.warning("写剪贴板失败：%s", exc)
        return False


_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _run_hidden(cmd, timeout: int = 20) -> bool:
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=timeout, creationflags=_NO_WINDOW)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# --manual：Edge 远程调试 (CDP) 人工辅助模式（纯标准库 WebSocket 客户端）
# ---------------------------------------------------------------------------

class _WebSocket:
    """最小 WebSocket 客户端（仅用于本机 CDP，文本帧 + ping/pong）。"""

    def __init__(self, url: str, timeout: float = 20.0):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "ws":
            raise JwxtError("仅支持 ws:// 调试地址：%s" % url)
        host = parts.hostname or "127.0.0.1"
        port = parts.port or 80
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ) % (path, host, port, key)
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise JwxtError("WebSocket 握手失败：连接被关闭")
            response += chunk
        head, _, rest = response.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        if " 101" not in status and not status.startswith("HTTP/1.1 101"):
            raise JwxtError("WebSocket 握手失败：%s" % status)
        self._buf = bytearray(rest)

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise JwxtError("WebSocket 连接已关闭")
            self._buf.extend(chunk)
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        frame = bytearray([0x80 | opcode])
        n = len(payload)
        mask = os.urandom(4)
        if n < 126:
            frame.append(0x80 | n)
        elif n < 65536:
            frame.append(0x80 | 126)
            frame += struct.pack(">H", n)
        else:
            frame.append(0x80 | 127)
            frame += struct.pack(">Q", n)
        frame += mask
        frame += bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(frame))

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def recv_text(self) -> str:
        chunks = []
        while True:
            b1, b2 = self._read_exact(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length)
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise JwxtError("WebSocket 已被浏览器关闭")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x0, 0x1, 0x2):
                chunks.append(payload)
            if fin:
                break
        return b"".join(chunks).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


class _CDP:
    """极简 CDP 客户端：call(method, params) / eval(expression)。"""

    def __init__(self, ws_url: str, timeout: float = 20.0):
        self._ws = _WebSocket(ws_url, timeout=timeout)
        self._id = 0

    def call(self, method: str, params=None, timeout: float = 45.0):
        self._id += 1
        mid = self._id
        self._ws.send_text(json.dumps({"id": mid, "method": method,
                                       "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = json.loads(self._ws.recv_text())
            except socket.timeout:
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise JwxtError("CDP 调用失败 %s：%s" % (method, msg["error"]))
                return msg.get("result") or {}
        raise JwxtError("CDP 调用超时：%s" % method)

    def eval(self, expression: str, timeout: float = 45.0):
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": False,
            "userGesture": True,
        }, timeout=timeout)
        return (result.get("result") or {}).get("value")

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


def find_browser():
    """找 Edge（优先）或 Chrome 的可执行文件。"""
    names = ["msedge.exe", "chrome.exe"]
    candidates = []
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
        candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _json_get(url: str, timeout: float = 1.5):
    try:
        return requests.get(url, timeout=timeout).json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

def setup_logger(verbose: bool = False, quiet: bool = False,
                 log_dir: str = LOG_DIR) -> str:
    """控制台 + logs/sync-YYYYMMDD.log 双写；返回日志文件路径。"""
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(
        log_dir, "sync-%s.log" % datetime.datetime.now().strftime("%Y%m%d")
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    if not quiet and sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.DEBUG if verbose else logging.INFO)
        console.setFormatter(fmt)
        logger.addHandler(console)
    return log_path


__all__ = [
    "JwxtError", "LoginError", "FetchError", "ParseError",
    "encode_inp", "interleave_encode", "build_login_encoded", "extract_scode_sxh",
    "b64url_encode", "b64url_decode", "build_publish_url", "mask_account",
    "normalize_term_start", "login", "check_logged_in", "fetch_timetable",
    "fetch_timetable_json", "parse_timetable", "parse_api_timetable",
    "parse_list_view_time", "clean_courses", "compress_weeks", "weeks_to_set",
    "dpapi_protect", "dpapi_unprotect", "save_credentials", "load_credentials",
    "credentials_path", "copy_to_clipboard",
    "aes_encrypt_password", "authserver_login", "sso_login", "sso_login_http",
    "SSO_JSP_URL",
    "save_jwxsd_cookies", "load_jwxsd_cookies", "clear_jwxsd_cookies",
    "session_from_cookies", "portal_to_jwxt_cookies", "manual_get_jwxt_cookies",
    "find_browser", "setup_logger", "LAST_HTML_PATH", "CREDS_PATH", "LOG_DIR",
]
