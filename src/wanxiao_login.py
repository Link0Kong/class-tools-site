# -*- coding: utf-8 -*-
"""完美校园（wanxiao）账密登录 —— CloudPayment fallback 所需的 token / deviceId。

! 本文件 vendor 自 https://github.com/jialiangh/campus-electricity-monitor 的
! wanxiao_login.py（MIT © 2026 jialiangh），已做 Windows / 掩码 / 隐私裁剪等
! 本地化修改。来源与改动清单见 NOTICE。默认主后端是免登录的 cloudpay
! （见 cloudpay.py），只有 config.json 里 `"backend": "wanxiao"` 或
! `"wanxiao_fallback": true` 时才会走到这里。

协议链（实测被服务端接受）：
  1. 本地生成 RSA-1024 密钥对 -> POST exchangeSecretkey.action {"key": <SPKI DER base64>}
  2. 用私钥 RSA PKCS#1 v1.5 解密响应 -> {"session": uuid, "key": <32 hex>}
  3. appKey = key[:24]，其后业务体走 3DES-CBC(IV="66666666", PKCS#5) + base64
  4. 账密登录 loginnew.action：password 字段是逐字符 3DES 加密后的 base64 数组
  5. 新设备被 code_=5 拦下 -> gainMatrixCaptcha543.action 发短信 ->
     registerUsersByTelAndLoginNew.action 用验证码登录并把本机 deviceId 绑成受信设备
  6. 外层信封恒为 {"session": sid, "data": <3DES b64>}，请求头 campusSign =
     sha256(请求体原文).hexdigest()

状态文件 wanxiao_state.json（deviceId + token）默认落在脚本同目录，已列入 .gitignore，
写入时尽力收紧权限。**deviceId 等同于密码**，换机器部署要把它一起带走，别外传。

CLI（run.bat 已封装）：
  python wanxiao_login.py status              # 看配置/token 状态（全部掩码）
  python wanxiao_login.py login               # 纯账密登录（不消耗短信）
  python wanxiao_login.py sms-send            # 给手机发短信验证码
  python wanxiao_login.py sms-code 123456     # 提交验证码完成绑定
  python wanxiao_login.py sms                 # 上两条合一（现场输入验证码）
  python wanxiao_login.py token               # 刷新并显示掩码后的 token
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar

# TripleDES 在 cryptography 45+ 被挪进 decrepit 包，老版本只在 primitives 里。
import warnings as _warnings

try:
    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
except ImportError:
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")
        from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, modes

import util

BASE = "https://app.17wanxiao.com/campus"
IV = b"66666666"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.environ.get("WANXIAO_STATE") or os.path.join(HERE, "wanxiao_state.json")
CONFIG_PATH = (os.environ.get("DIANFEI_CONFIG") or
               os.environ.get("WANXIAO_CONFIG") or
               os.path.join(HERE, "config.json"))

DEFAULT_UA = ("Dalvik/2.1.0 (Linux; U; Android 12; 24031PN0DC Build/ccbda31.0)")
DEFAULT_MODEL = "24031PN0DC"
DEFAULT_VERSION = 10589101
DEFAULT_TOKEN_MAX_AGE = 5400

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE        # 与 App 行为一致；上报服务器证书校验差异见 README 风险

_CONFIG_CACHE = {}


def set_config_path(path):
    """让 electricity_monitor 的 --config 生效（同时清缓存）。"""
    global CONFIG_PATH
    CONFIG_PATH = os.path.abspath(path)
    _CONFIG_CACHE.clear()


def config_data():
    if _CONFIG_CACHE:
        return _CONFIG_CACHE
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            _CONFIG_CACHE.update(data)
    except Exception:
        pass
    return _CONFIG_CACHE


# ---------------------------------------------------------------- crypto ---
def pad8(data: bytes) -> bytes:
    n = 8 - len(data) % 8
    return data + bytes([n]) * n


def unpad8(data: bytes) -> bytes:
    n = data[-1]
    if n < 1 or n > 8 or data[-n:] != bytes([n]) * n:
        raise ValueError("bad PKCS5 padding")
    return data[:-n]


def _des3(key_text: str):
    try:
        algo = TripleDES(key_text.encode("ascii"), adjust_parity=True)
    except TypeError:
        algo = TripleDES(key_text.encode("ascii"))
    return algo


def des3_encrypt(plain: bytes, key_text: str) -> str:
    enc = Cipher(_des3(key_text), modes.CBC(IV)).encryptor()
    return base64.b64encode(enc.update(pad8(plain)) + enc.finalize()).decode("ascii")


def des3_decrypt(b64_text: str, key_text: str) -> bytes:
    raw = base64.b64decode(b64_text)
    dec = Cipher(_des3(key_text), modes.CBC(IV)).decryptor()
    return unpad8(dec.update(raw) + dec.finalize())


def spki_body_b64(priv) -> str:
    der = priv.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo)
    s = base64.b64encode(der).decode("ascii")
    return "\n".join(s[i:i + 64] for i in range(0, len(s), 64)) + "\n"


# ------------------------------------------------------------- transport ---
def _decode_body(raw_bytes, encoding):
    """部分接口返回 gzip/deflate，urllib 不会自动解压。"""
    enc = (encoding or "").lower()
    try:
        if "gzip" in enc:
            import gzip
            return gzip.decompress(raw_bytes)
        if "deflate" in enc:
            import zlib
            try:
                return zlib.decompress(raw_bytes)
            except zlib.error:
                return zlib.decompress(raw_bytes, -zlib.MAX_WBITS)
    except Exception:
        pass
    return raw_bytes


class WanxiaoError(RuntimeError):
    pass


class Wanxiao:
    """一个握手会话 = 一个 session/appKey；token 登录后才有。"""

    def __init__(self, phone, password, device_id, model=DEFAULT_MODEL,
                 ua=DEFAULT_UA, version=DEFAULT_VERSION, verbose=True):
        self.phone = phone
        self.password = password
        self.device_id = device_id
        self.model = model
        self.ua = ua
        self.version = version
        self.verbose = verbose
        self.session = None
        self.app_key = None
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()),
            urllib.request.HTTPSHandler(context=CTX))

    def log(self, *args):
        if self.verbose:
            print(*args)

    def _post(self, path, body_text, headers=None):
        request_headers = {"Content-Type": "application/text", "User-Agent": self.ua}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(
            BASE + path, data=body_text.encode("utf-8"),
            headers=request_headers, method="POST")
        try:
            with self.opener.open(request, timeout=30) as resp:
                return _decode_body(
                    resp.read(), resp.headers.get("Content-Encoding")).decode(
                    "utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return _decode_body(
                exc.read(), exc.headers.get("Content-Encoding")).decode(
                "utf-8", "replace")

    def _envelope(self, path, args):
        body = json.dumps({"session": self.session,
                           "data": des3_encrypt(json.dumps(args).encode("utf-8"),
                                                self.app_key)})
        sign = hashlib.sha256(body.encode("utf-8")).hexdigest()
        raw = self._post(path, body, {"campusSign": sign})
        try:
            resp = json.loads(raw)
        except Exception:
            raise WanxiaoError("%s 返回非 JSON: %s" % (path, raw[:160]))
        if resp.get("data"):
            try:
                resp["_plain"] = json.loads(
                    des3_decrypt(resp["data"], self.app_key).decode("utf-8")
                    .replace("\r", ""))
            except Exception:
                pass
        return resp

    def _base_args(self, request_method, **kwargs):
        args = {
            "appCode": "M002",
            "deviceId": self.device_id,
            "netWork": "wifi",
            "qudao": "guanwang",
            "requestMethod": request_method,
            "shebeixinghao": self.model,
            "systemType": "android",
            "telephoneInfo": "12",
            "telephoneModel": self.model,
        }
        args.update(kwargs)
        return args

    # ------------------------------------------------------------ steps ---
    def handshake(self):
        priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        raw = self._post("/cam_iface46/exchangeSecretkey.action",
                         json.dumps({"key": spki_body_b64(priv)}))
        blob = base64.b64decode(raw.strip())
        info = json.loads(priv.decrypt(blob, padding.PKCS1v15()).decode("utf-8"))
        self.session = info["session"]
        self.app_key = info["key"][:24]
        self.log("[握手] session=%s appKey=%s"
                 % (util.mask_secret(self.session), util.mask_secret(self.app_key)))
        return self.session

    def password_login(self):
        """返回 (ok, token_or_reason)。code_=5 且提示新设备时 ok=False、值为 NEW_DEVICE。"""
        args = self._base_args(
            "cam_iface46/loginnew.action",
            password=[des3_encrypt(ch.encode("utf-8"), self.app_key)
                      for ch in self.password],
            type="1",
            userName=self.phone,
            wanxiaoVersion=self.version,
        )
        resp = self._envelope("/cam_iface46/loginnew.action", args)
        msg = resp.get("message_", "")
        if resp.get("result_"):
            return True, self._token_from(resp)
        self.log("[账密] 失败 code_=%s %s" % (resp.get("code_"), msg))
        if "新设备" in msg:
            return False, "NEW_DEVICE"
        if "密码错误" in msg:
            return False, "BAD_PASSWORD:" + msg
        return False, msg

    def check_phone(self):
        args = self._base_args("cam_iface46/gainMatrixCaptcha.action",
                               action="registAndLogin", confirm=False,
                               mobile=self.phone, type="sms")
        resp = self._envelope("/cam_iface46/checkBeforeSendRegisterCode.action", args)
        self.log("[查号] %s" % resp.get("message_"))
        return resp.get("result_"), resp.get("message_", "")

    def send_sms(self):
        # 543 变体才会真的往手机发短信；不带 543 的那个走聚合图形码，
        # 提交时永远对不上号。
        args = self._base_args("cam_iface46/gainMatrixCaptcha543.action",
                               action="registAndLogin", confirm=False,
                               mobile=self.phone, type="sms")
        resp = self._envelope("/cam_iface46/gainMatrixCaptcha543.action", args)
        self.log("[发短信] code_=%s %s" % (resp.get("code_"), resp.get("message_")))
        return bool(resp.get("result_")), resp.get("message_", "")

    def sms_login(self, code):
        # 参数集与参考实现逐字对齐：这里**不能**带 action / confirm，
        # 多了字段会被服务端当成注册流程去校验验证码，于是报“短信验证码错误”。
        args = self._base_args(
            "cam_iface46/registerUsersByTelAndLoginNew.action",
            mobile=self.phone, sms=str(code), type="2",
            wanxiaoVersion=self.version)
        resp = self._envelope("/cam_iface46/registerUsersByTelAndLoginNew.action", args)
        if resp.get("result_"):
            return True, self._token_from(resp)
        msg = resp.get("message_", "")
        self.log("[验证码登录] 失败 code_=%s %s" % (resp.get("code_"), msg))
        return False, msg

    def _token_from(self, resp):
        plain = resp.get("_plain") or {}
        # CloudPayment 认的是**这次登录所用的握手 session**（抓包铁证：app 登录包
        # 信封里的 session=<本次握手 UUID> 随后原样出现在 pay.do?token=<同一个> 上），
        # 响应体里的 user.token 前 36 位是账号级固定值，拿去 SSO 会被拒。
        token = self.session
        info = {
            "token": token,
            "session": self.session,
            "obtained_at": int(time.time()),
            "handshake_session_is_token": token == self.session,
        }
        self.log("[登录成功] token（掩码）=%s" % util.mask_secret(token))
        # 隐私裁剪：不再把 user 里的姓名/证件号/手机号等写进 state 或日志
        if isinstance(plain, dict) and plain.get("user"):
            self.log("[登录成功] 账号鉴权通过（个人信息不打印、不落盘）")
        return info


# ------------------------------------------------------------- keystore ---
def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state):
    """原子写 + 尽力收紧权限（state 里有 token/deviceId，等同于密码）。"""
    util.write_private_json(STATE_PATH, state)


def load_creds():
    """账号密码优先读环境变量，其次读 config.json（顶层或 wanxiao 小节）。"""
    phone = os.environ.get("WANXIAO_PHONE")
    pwd = os.environ.get("WANXIAO_PASSWORD")
    dev = os.environ.get("WANXIAO_DEVICEID")
    cfg = config_data()
    phone = phone or cfg.get("phone")
    pwd = pwd or cfg.get("password")
    dev = dev or cfg.get("deviceId")
    section = cfg.get("wanxiao")
    if isinstance(section, dict):
        phone = phone or section.get("phone")
        pwd = pwd or section.get("password")
        dev = dev or section.get("deviceId")
    return phone, pwd, dev


def build(phone=None, pwd=None, require_creds=True):
    cfg_phone, cfg_pwd, cfg_dev = load_creds()
    phone = phone or cfg_phone
    pwd = pwd or cfg_pwd
    if require_creds and (not phone or not pwd):
        raise SystemExit(
            "缺少完美校园账号密码（当前后端是 cloudpay 免登录时不需要）：\n"
            "  设环境变量 WANXIAO_PHONE / WANXIAO_PASSWORD，或在 %s 的 "
            "\"phone\"/\"password\" 里填。" % CONFIG_PATH)
    state = load_state()
    device_id = cfg_dev or state.get("deviceId")
    if not device_id and require_creds:
        device_id = str(uuid.uuid4())
        state["deviceId"] = device_id
        save_state(state)
        print("生成新的 deviceId（掩码）：%s（换机器请保留 wanxiao_state.json）"
              % util.mask_secret(device_id))
    return Wanxiao(phone, pwd, device_id), state


def _token_max_age():
    try:
        return int(config_data().get("token_max_age") or DEFAULT_TOKEN_MAX_AGE)
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_MAX_AGE


def fresh_token(max_age=None, force=False):
    """采集器入口：拿一个尽量新的 token，必要时自动账密重登。"""
    wx, state = build()
    if max_age is None:
        max_age = _token_max_age()
    if not force:
        token = state.get("token")
        if token and time.time() - state.get("obtained_at", 0) < max_age:
            return token
    ok, result = wx.password_login() if _handshake(wx, state) else (False, "HANDSHAKE_FAIL")
    if ok:
        state.update(result)
        save_state(state)
        return result["token"]
    if result == "NEW_DEVICE":
        raise SystemExit(
            "deviceId %s 未绑定受信设备。请跑一次（只需一次）：\n"
            "  run.bat sms-send        # 发短信\n"
            "  run.bat sms-code 123456 # 提交验证码完成绑定\n"
            "  run.bat login           # 复查账密可免短信登录"
            % util.mask_secret(wx.device_id))
    raise SystemExit("登录失败：%s" % util.scrub(str(result)))


def _handshake(wx, state):
    try:
        wx.handshake()
        return True
    except Exception as exc:
        print("握手失败：%s" % util.scrub(str(exc)))
        return False


def _reuse_or_handshake(wx, state):
    """验证码是绑在发起那次握手 session 上的，能复用就别重新握手。"""
    pending = state.get("pending_sms") or {}
    if pending.get("session") and pending.get("app_key") \
            and time.time() - pending.get("at", 0) < 600:
        wx.session = pending["session"]
        wx.app_key = pending["app_key"]
        print("复用发短信时的 session（%s，%.0f 秒前）"
              % (util.mask_secret(wx.session), time.time() - pending["at"]))
        return True
    return _handshake(wx, state)


def _mask_token(state):
    token = state.get("token")
    return util.mask_secret(token) if token else "(无)"


def cmd_status():
    state = load_state()
    phone, pwd, dev = load_creds()
    dev = dev or state.get("deviceId")
    age = time.time() - state.get("obtained_at", 0) if state.get("obtained_at") else None
    print("配置文件 : %s%s" % (CONFIG_PATH, "" if os.path.exists(CONFIG_PATH) else "（不存在）"))
    print("phone    : %s" % (util.mask_phone(phone) if phone else "(未配置，cloudpay 免登录后端不需要)"))
    print("password : %s" % ("已配置（不显示）" if pwd else "(未配置)"))
    print("deviceId : %s" % (util.mask_secret(dev) if dev else "(未绑定)"))
    print("token    : %s" % _mask_token(state))
    print("token 年龄: %s" % (("%.0f 分钟前" % (age / 60)) if age else "无"))
    print("state    : %s" % STATE_PATH)
    return 0


def main(argv=None):
    util.setup_console()
    args = list(sys.argv[1:] if argv is None else argv)
    if "--config" in args:
        index = args.index("--config")
        if index + 1 >= len(args):
            raise SystemExit("--config 需要一个配置文件路径")
        set_config_path(args[index + 1])
        del args[index:index + 2]
    if not args or args[0] in ("-h", "--help", "help"):
        print((__doc__ or "").strip())
        return 0
    cmd = args[0]

    if cmd == "status":
        return cmd_status()

    if cmd == "token":
        token = fresh_token(force="--force" in args)
        print("token（掩码）: %s" % util.mask_secret(token))
        print("（出于安全不打印明文；采集器内部直接 import fresh_token 使用）")
        return 0

    wx, state = build()

    if cmd == "login":
        if not _handshake(wx, state):
            return 1
        ok, result = wx.password_login()
        print("=> %s" % ("成功" if ok else "失败"))
        if ok:
            state.update(result)
            save_state(state)
            print("   token（掩码）: %s" % util.mask_secret(result.get("token")))
        else:
            print("   原因: %s" % util.scrub(str(result)))
        return 0 if ok else 1

    if cmd == "sms-send":
        if not _handshake(wx, state):
            return 1
        wx.check_phone()
        ok, msg = wx.send_sms()
        if ok:
            state["pending_sms"] = {"session": wx.session,
                                    "app_key": wx.app_key, "at": int(time.time())}
            save_state(state)
            print("验证码已发往 %s；拿到后执行： run.bat sms-code <验证码>"
                  % util.mask_phone(wx.phone))
        return 0 if ok else 1

    if cmd == "sms-code":
        if len(args) < 2:
            raise SystemExit("用法: python wanxiao_login.py sms-code <验证码>")
        if not _reuse_or_handshake(wx, state):
            return 1
        ok, result = wx.sms_login(args[1])
        print("=> %s" % ("成功" if ok else "失败"))
        if ok:
            state.update(result)
            state.pop("pending_sms", None)
            save_state(state)
            print("\n现在测纯账密是否已免短信： run.bat login")
        else:
            print("   原因: %s" % util.scrub(str(result)))
        return 0 if ok else 1

    if cmd == "sms":
        """一条命令搞定：发短信 -> 现场读验证码 -> 提交，全程同一个 session。"""
        if not _handshake(wx, state):
            return 1
        wx.check_phone()
        ok, msg = wx.send_sms()
        if not ok:
            print("发短信失败：%s" % util.scrub(str(msg)))
            return 1
        code = args[1] if len(args) > 1 else input("收到验证码: ").strip()
        ok, result = wx.sms_login(code)
        print("=> %s" % ("成功" if ok else "失败"))
        if ok:
            state.update(result)
            state.pop("pending_sms", None)
            save_state(state)
        else:
            print("   原因: %s" % util.scrub(str(result)))
        return 0 if ok else 1

    raise SystemExit((__doc__ or "").strip())


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as exc:
        print("[错误] %s: %s" % (type(exc).__name__, util.scrub(str(exc))))
        sys.exit(1)
