# -*- coding: utf-8 -*-
"""tests/test_sso_http.py — 纯 requests SSO 单元测试（全部 mock，不联网、不碰密码）。

覆盖：
  * sso.jsp 的 JS 跳转解析（单/双引号、location/location.href、无效值）
  * 教务系统域 cookie 过滤（不把门户/authserver cookie 混进缓存）
  * sso_login_http() 正常链路：authserver → sso.jsp → 302 回教务系统 → 拿到 cookie
  * sso_login_http() 失败语义（LoginError 不再回退浏览器；FetchError 可回退）
  * sso_login() 优先纯 requests；仅在 JwxtError/FetchError 时回退旧 Edge 链路

用法：
    python tests/test_sso_http.py
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import jwxt  # noqa: E402


# ---------------------------------------------------------------------------
# 假对象 / 工具
# ---------------------------------------------------------------------------

class FakeCookie(object):
    def __init__(self, name, value, domain="210.34.74.77"):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = "/"
        self.secure = False

    def has_nonstandard_attr(self, _name):
        return False


class FakeSession(object):
    """只带 headers/cookies 的假请求会话（绝不发真实请求）。"""

    def __init__(self, cookies=None):
        self.headers = {}
        self.cookies = list(cookies or [])

    def add(self, *cookies):
        self.cookies.extend(cookies)
        return self


class FakeResp(object):
    def __init__(self, url, text, status=200):
        self.url = url
        self.text = text
        self.status_code = status


class Patcher(object):
    """临时替换模块属性，退出时恢复（不用 pytest fixture）。"""

    def __init__(self, **attrs):
        self.attrs = attrs
        self.old = {}

    def __enter__(self):
        for key, value in self.attrs.items():
            self.old[key] = getattr(jwxt, key)
            setattr(jwxt, key, value)
        return self

    def __exit__(self, *exc):
        for key, value in self.old.items():
            setattr(jwxt, key, value)
        return False


SENTINEL = object()


def _logged_in_with(cookie_name):
    def _check(session, timeout=None):
        return any(getattr(c, "name", "") == cookie_name
                   for c in getattr(session, "cookies", []) or [])
    return _check


# ---------------------------------------------------------------------------
# 1) JS 跳转解析
# ---------------------------------------------------------------------------

def test_extract_js_redirect_single_quote():
    html = ("<script languge='javascript'>window.location.href="
            "'https://authserver.fjtcm.edu.cn/authserver/login"
            "?service=http%3A%2F%2F210.34.74.77%2Fsso.jsp'</script>")
    assert jwxt._extract_js_redirect(html) == (
        "https://authserver.fjtcm.edu.cn/authserver/login"
        "?service=http%3A%2F%2F210.34.74.77%2Fsso.jsp")


def test_extract_js_redirect_double_quote_spaces():
    html = '<script>  location.href = "https://a.example/x?a=1&amp;b=2" ; </script>'
    assert jwxt._extract_js_redirect(html) == "https://a.example/x?a=1&b=2"


def test_extract_js_redirect_location_without_href():
    html = "<script>window.location = 'http://210.34.74.77/sso.jsp';</script>"
    assert jwxt._extract_js_redirect(html) == "http://210.34.74.77/sso.jsp"


def test_extract_js_redirect_invalid():
    assert jwxt._extract_js_redirect("") is None
    assert jwxt._extract_js_redirect("<html>no redirect</html>") is None
    assert jwxt._extract_js_redirect("<script>location.href='javascript:void(0)'</script>") is None
    assert jwxt._extract_js_redirect("<script>location.href='#'</script>") is None


# ---------------------------------------------------------------------------
# 2) 教务系统 cookie 过滤
# ---------------------------------------------------------------------------

def test_session_domain_cookies_filter():
    sess = FakeSession([
        FakeCookie("SERVERID_jsxsd", "v1", "210.34.74.77"),
        FakeCookie("bzb_jsxsd", "v2", "210.34.74.77"),
        FakeCookie("CASTGC", "portal", ".fjtcm.edu.cn"),
        FakeCookie("WISCPSID", "portal2", "e.fjtcm.edu.cn"),
        FakeCookie("JSESSIONID", "auth", "authserver.fjtcm.edu.cn"),
        FakeCookie("EMPTY", "", "210.34.74.77"),
    ])
    got = jwxt._session_domain_cookies(sess)
    assert got == {"SERVERID_jsxsd": "v1", "bzb_jsxsd": "v2"}, got


# ---------------------------------------------------------------------------
# 3) sso_login_http 正常链路
# ---------------------------------------------------------------------------

def test_sso_login_http_happy_path():
    portal = FakeSession([
        FakeCookie("CASTGC", "portal-token", "authserver.fjtcm.edu.cn"),
        FakeCookie("WISCPSID", "portal-cookie", "e.fjtcm.edu.cn"),
    ])
    calls = []
    sso_url = jwxt.SSO_JSP_URL
    js_body = ("<script>window.location.href='https://authserver.fjtcm.edu.cn/"
               "authserver/login?service=http%3A%2F%2F210.34.74.77%2Fsso.jsp'</script>")
    auth_url = ("https://authserver.fjtcm.edu.cn/authserver/login"
                "?service=http%3A%2F%2F210.34.74.77%2Fsso.jsp")

    def fake_auth_login(account, password, *, timeout=20, session=None):
        assert account == "1234567890" and password == "pwd-x"
        return portal

    def fake_request(session, method, url, *, timeout=None, retries=1, **kwargs):
        calls.append((method, url))
        if url == sso_url:
            session.add(FakeCookie("SERVERID_gld", "gld"))
            return FakeResp(sso_url, js_body)
        if url == auth_url:
            session.add(FakeCookie("SERVERID_jsxsd", "jx1"))
            session.add(FakeCookie("bzb_jsxsd", "jx2"))
            return FakeResp("http://210.34.74.77/jsxsd/framework/xsMainV.htmlx",
                            "<html>学生首页 退出 主菜单</html>")
        raise AssertionError("unexpected url: %s" % url)

    saved = {}

    def fake_save(cookies):
        saved.update(cookies)

    with Patcher(authserver_login=fake_auth_login, _request=fake_request,
                 check_logged_in=_logged_in_with("SERVERID_jsxsd"),
                 save_jwxsd_cookies=fake_save):
        sess = jwxt.sso_login_http("1234567890", "pwd-x", timeout=20)

    assert sess is portal
    assert session_has(portal, "SERVERID_jsxsd")
    # 缓存只收教务系统域 cookie（门户/authserver cookie 不能混进来）
    assert saved.get("SERVERID_jsxsd") == "jx1", saved
    assert saved.get("bzb_jsxsd") == "jx2", saved
    assert all("fjtcm" not in name for name in saved), saved
    assert [c[1] for c in calls] == [sso_url, auth_url], calls


def session_has(session, name):
    return any(getattr(c, "name", "") == name for c in session.cookies)


# ---------------------------------------------------------------------------
# 4) sso_login_http 失败语义
# ---------------------------------------------------------------------------

def test_sso_login_http_wrong_password_raises_login_error():
    def fake_auth_login(account, password, *, timeout=20, session=None):
        raise jwxt.LoginError("统一认证登录失败（账号或密码错误）")

    def no_request(*_a, **_k):
        raise AssertionError("密码错误时不应继续请求 sso.jsp")

    with Patcher(authserver_login=fake_auth_login, _request=no_request):
        try:
            jwxt.sso_login_http("1234567890", "bad")
        except jwxt.LoginError as exc:
            assert "密码错误" in str(exc)
        else:
            raise AssertionError("expected LoginError")


def test_sso_login_http_no_cookie_raises_fetch_error():
    portal = FakeSession()
    sso_url = jwxt.SSO_JSP_URL

    def fake_auth_login(account, password, *, timeout=20, session=None):
        return portal

    def fake_request(session, method, url, *, timeout=None, retries=1, **kwargs):
        return FakeResp(sso_url, "<html>空的 sso.jsp（无跳转也无 cookie）</html>")

    saved = []
    with Patcher(authserver_login=fake_auth_login, _request=fake_request,
                 check_logged_in=lambda *a, **k: False,
                 save_jwxsd_cookies=lambda c: saved.append(c)):
        try:
            jwxt.sso_login_http("1234567890", "pwd-x")
        except jwxt.FetchError:
            pass
        else:
            raise AssertionError("expected FetchError")
    assert saved == [], saved


# ---------------------------------------------------------------------------
# 5) sso_login 优先纯 requests / 失败回退 Edge / LoginError 不回退
# ---------------------------------------------------------------------------

def test_sso_login_prefers_http():
    with Patcher(load_jwxsd_cookies=lambda *a, **k: None,
                 sso_login_http=lambda *a, **k: SENTINEL,
                 portal_to_jwxt_cookies=lambda *a, **k: (_ for _ in ()).throw(
                     AssertionError("不应回退到 Edge"))) as _p:
        assert jwxt.sso_login("1234567890", "pwd-x") is SENTINEL


def test_sso_login_falls_back_to_edge_on_transport_error():
    portal = FakeSession([FakeCookie("CASTGC", "portal", "authserver.fjtcm.edu.cn")])
    edge_cookies = {"SERVERID_jsxsd": "from-edge"}
    saved = []
    sessions = []

    def fake_auth_login(account, password, *, timeout=20, session=None):
        return portal

    def fake_session_from_cookies(cookies):
        s = FakeSession()
        sessions.append(s)
        return s

    def fake_sso_http(*_a, **_k):
        raise jwxt.FetchError("sso.jsp 结构变化")

    with Patcher(load_jwxsd_cookies=lambda *a, **k: None,
                 sso_login_http=fake_sso_http,
                 authserver_login=fake_auth_login,
                 _requests_cookies=lambda s: [],
                 portal_to_jwxt_cookies=lambda *a, **k: edge_cookies,
                 save_jwxsd_cookies=lambda c: saved.append(c),
                 session_from_cookies=fake_session_from_cookies,
                 check_logged_in=lambda *a, **k: True):
        sess = jwxt.sso_login("1234567890", "pwd-x")

    assert sess is sessions[0]
    assert saved == [edge_cookies], saved


def test_sso_login_does_not_fall_back_on_login_error():
    def fake_sso_http(*_a, **_k):
        raise jwxt.LoginError("验证码")

    def no_edge(*_a, **_k):
        raise AssertionError("登录类错误不应回退 Edge")

    with Patcher(load_jwxsd_cookies=lambda *a, **k: None,
                 sso_login_http=fake_sso_http,
                 authserver_login=no_edge,
                 portal_to_jwxt_cookies=no_edge):
        try:
            jwxt.sso_login("1234567890", "pwd-x")
        except jwxt.LoginError as exc:
            assert "验证码" in str(exc)
        else:
            raise AssertionError("expected LoginError")


# ---------------------------------------------------------------------------

def main():
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS  %s" % name)
        except Exception:
            failed += 1
            print("FAIL  %s" % name)
            traceback.print_exc()
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
