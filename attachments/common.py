# -*- coding: utf-8 -*-
"""通知附件外置 · 签名 URL 公共算法（服务端与客户端共用）。

约定（与 web/attachments/CONTRACT.md 一致）：
- 附件内容按 sha256 前 32 位十六进制命名（内容寻址、不可枚举）；
- URL = {base}/att/{id}?exp={unix秒}&sig={hex}；
- sig = HMAC-SHA256(key, "{id}\\n{exp}")，key = sha256("{sync_token}|att-v1")；
- GET 无需鉴权头/cookie，文件内容不可变，可长缓存；exp 到期后必须重新签名。
"""
import hashlib
import hmac
import time

ID_LEN = 32
KEY_SALT = "|att-v1"
DEFAULT_EXP_DAYS = 180
SKEW = 300


def content_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:ID_LEN]


def derive_key(sync_token: str) -> bytes:
    if not sync_token:
        raise ValueError("sync_token 为空")
    return hashlib.sha256((sync_token + KEY_SALT).encode("utf-8")).digest()


def sign(att_id: str, exp: int, key: bytes) -> str:
    msg = ("%s\n%d" % (att_id, int(exp))).encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def signed_url(base: str, att_id: str, exp: int, key: bytes) -> str:
    return "%s/att/%s?exp=%d&sig=%s" % (base.rstrip("/"), att_id, int(exp), sign(att_id, exp, key))


def verify(att_id: str, exp, sig: str, key: bytes, now=None) -> bool:
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    now_i = int(now if now is not None else time.time())
    if exp_i + SKEW < now_i:
        return False
    return hmac.compare_digest(sign(att_id, exp_i, key), str(sig or ""))


def parse_att_id(path: str):
    """从 '/att/<id>' 中取出 id（只接受 32 位小写 hex）。"""
    p = str(path or "")
    if not p.startswith("/att/"):
        return None
    rest = p[len("/att/"):]
    if "/" in rest or "?" in rest:
        return None
    if len(rest) != ID_LEN:
        return None
    if any(c not in "0123456789abcdef" for c in rest):
        return None
    return rest
