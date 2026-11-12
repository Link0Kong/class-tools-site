# -*- coding: utf-8 -*-
"""drop_app.py — ECS「文件传输」服务 v2.1（Python 标准库，127.0.0.1:8093）

用途（2026-11-11 v2/v2.1，用户第 1 条：文件传输做成独立工具 / 上传文件三天后删除 /
不限上传文件大小）：
    同账号（同 sid）的**任意设备之间**（大屏、手机、电脑）传文件、发文字、
    转发遥控指令；不再只是大屏专属。
    **每个文件自上传完成时刻起 72h（3 天）后自动删除**（逐文件独立过期）；
    会话本身按空闲滑动回收（最后活动后 72h 无活动且无未过期文件才删除）。
    Caddy `handle /drop/*`（strip_prefix /drop）反代本服务：
        /drop/__health、/drop/open、/drop/mine、/drop/state、/drop/close、
        /drop/upload/{init,chunk,finish}、/drop/file/<fileId>?签名、/drop/text、/drop/cmd
    完整契约见 `drop/CONTRACT.md`（本仓库），部署见 `deploy/ecs_drop.py`。

安全模型：
    - 监听 127.0.0.1，公网只能经 Caddy；文件下载用 HMAC 签名 URL（30 分钟），
      其余 API 必须 `X-Device-Id: <班级 token>`；
    - token → CloudBase RPC `class_whoami`（Authorization: Bearer <publish_key>）换 sid/name；
      token 缓存 120s；网关不可用一律 503（fail closed）；
    - 访问日志只打印「方法 路径 状态 耗时」，**不打印 token / query / 请求头**；
    - 文件落盘名恒为 `<fileId>.bin`，上传原始名只做展示（sanitize 后用于下载头）。

配置（环境变量，systemd unit 里设置；默认值见下）：
    DROP_ROOT             数据根，默认 /opt/class-tools/drop
    DROP_PORT             监听端口，默认 8093
    DROP_GATEWAY          CloudBase PostgREST 基址（含 /v1/rdb/rest/）
    DROP_PUBLISH_KEY_FILE publish_key 文件（默认 <ROOT>/publish_key，0640）
    DROP_TTL_SEC          文件 TTL / 会话空闲 TTL 秒，默认 259200（72h；文件自上传完成起算，
                          逐文件过期；会话空闲滑动回收）
    DROP_MAX_FILE_BYTES   单文件上限字节，默认 0 = 不限（磁盘余量是唯一限制）
    DROP_MAX_SESSION_BYTES 单会话总量字节，默认 0 = 不限（仅受磁盘限制）
    DROP_MAX_FILES        单会话文件数，默认 300
    DROP_UPLOAD_TTL_SEC   未完成分片保留秒数，默认 86400（24h 后回收，避免占盘）
    DROP_TEXT_MAX         文字上限，默认 10000 字符
    DROP_MAX_EVENTS       每会话事件上限，默认 500
    DROP_URL_TTL_SEC      下载签名有效期，默认 1800
    DROP_AUTH_CACHE_SEC   token 缓存秒数，默认 120
    DROP_PUBLIC_PREFIX    下载 URL 路径前缀，默认 /drop
    DROP_PUBLIC_BASE      下载 URL 基址（整体覆盖，如 https://tool.furina.fun/drop）
    DROP_DISK_RESERVE_BYTES 磁盘保留余量，默认 1GiB
    DROP_LOG_LEVEL        DEBUG/INFO（默认 INFO）

运行：`python3 /opt/class-tools/drop/app.py`（生产由 systemd class-tools-drop.service 管理）
"""
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "2.3"
ROOT = os.path.abspath(os.environ.get("DROP_ROOT", "/opt/class-tools/drop"))
PORT = int(os.environ.get("DROP_PORT", "8093"))
DEFAULT_GATEWAY = ("https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com"
                   "/v1/rdb/rest/")
GATEWAY = os.environ.get("DROP_GATEWAY") or DEFAULT_GATEWAY
if not GATEWAY.endswith("/"):
    GATEWAY += "/"
PRESENCE_TTL_MS = 30 * 1000          # 大屏在线心跳 TTL（30s；网页大屏每 10s POST /presence）
TTL_SEC = int(os.environ.get("DROP_TTL_SEC", "259200"))            # 72h
MAX_FILE_BYTES = int(os.environ.get("DROP_MAX_FILE_BYTES", "0"))    # 0 = 不限
MAX_SESSION_BYTES = int(os.environ.get("DROP_MAX_SESSION_BYTES", "0"))  # 0 = 不限
MAX_FILES = int(os.environ.get("DROP_MAX_FILES", "300"))
UPLOAD_TTL_SEC = int(os.environ.get("DROP_UPLOAD_TTL_SEC", "86400"))  # 未完成分片 24h
TEXT_MAX = int(os.environ.get("DROP_TEXT_MAX", "10000"))
MAX_EVENTS = int(os.environ.get("DROP_MAX_EVENTS", "500"))
URL_TTL_SEC = int(os.environ.get("DROP_URL_TTL_SEC", "1800"))
AUTH_CACHE_SEC = int(os.environ.get("DROP_AUTH_CACHE_SEC", "120"))
PUBLIC_PREFIX = os.environ.get("DROP_PUBLIC_PREFIX", "/drop").rstrip("/")
PUBLIC_BASE = os.environ.get("DROP_PUBLIC_BASE", "").rstrip("/")
DISK_RESERVE = int(os.environ.get("DROP_DISK_RESERVE_BYTES", str(1024 ** 3)))
LOG_LEVEL = (os.environ.get("DROP_LOG_LEVEL", "INFO") or "INFO").upper()
GATEWAY_TIMEOUT = float(os.environ.get("DROP_GATEWAY_TIMEOUT", "8"))
CHUNK_SIZE = 8388608                     # 契约固定 8MiB（响应 /upload/init 的 chunkSize）
JSON_BODY_MAX = 1024 * 1024              # JSON 请求体上限 1MiB
CHUNK_BODY_MAX = CHUNK_SIZE              # 单分片原始字节上限
ARGS_JSON_MAX = 64 * 1024                # /cmd args 序列化上限
MAX_TOTAL_CHUNKS = 65536                 # 8MiB × 65536 = 512GiB 声明上限（磁盘是实际限制）
AUTH_CACHE_MAX = 5000
GW_UA = "class-tools-drop/" + VERSION

SESSION_DIR = os.path.join(ROOT, "sessions")
FILES_DIR = os.path.join(ROOT, "files")
UPLOAD_DIR = os.path.join(ROOT, "uploads")
INDEX_PATH = os.path.join(SESSION_DIR, "index.json")
SECRET_PATH = os.path.join(ROOT, ".secret")
PUBLISH_KEY_FILE = os.environ.get("DROP_PUBLISH_KEY_FILE",
                                  os.path.join(ROOT, "publish_key"))
DEFAULT_ORIGIN = "https://tool.furina.fun"

CMD_OPS = frozenset([
    "focus", "focus_clear", "timer", "draw", "vote_select", "ppt",
    "toast", "restore_fs", "stage_close",
])

_LOCK = threading.RLock()
_AUTH_CACHE = {}
_UPLOAD_LOCKS = {}
_SECRET_LOCK = threading.Lock()
_SECRET = None

_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_HEX_ID = re.compile(r"^[0-9a-f]{16}$")
_MIME_RE = re.compile(r"^[-\w.+/]{1,120}$")
_STARTED = time.time()


def _load_publish_key():
    key = os.environ.get("DROP_PUBLISH_KEY") or ""
    if key:
        return key.strip()
    try:
        with open(PUBLISH_KEY_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


PUBLISH_KEY = _load_publish_key()


# ---------------------------------------------------------------------------
# 日志 / 异常
# ---------------------------------------------------------------------------
def log(msg, level="I"):
    if level == "D" and LOG_LEVEL != "DEBUG":
        return
    try:
        sys.stdout.write("%s [%s] %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), level, msg))
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def warn(msg):
    log(msg, "W")


class HttpError(Exception):
    """可映射为 HTTP 状态码 + 中文 reason 的业务错误。"""

    def __init__(self, status, reason):
        Exception.__init__(self, reason)
        self.status = int(status)
        self.reason = str(reason or "请求失败")


class AuthError(HttpError):
    """鉴权失败：401 token 无效 / 503 鉴权服务不可用（fail closed）。"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _now_ms():
    return int(time.time() * 1000)


def _valid_hex_id(value):
    return (isinstance(value, str) and len(value) == 16
            and _HEX_ID.match(value) is not None)


def _query_one(query, name, default=""):
    values = query.get(name)
    if not values:
        return default
    return values[0]


def _atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.tmp.%d.%d" % (path, os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def _read_json_file(path, limit=32 * 1024 * 1024):
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _safe_filename(raw_name):
    """文件名 sanitize：去路径 / 控制字符、限长 180、保留扩展名。"""
    raw = str(raw_name or "")
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = _BAD_CHARS.sub("", raw).strip()
    raw = raw.replace("\x00", "").strip()
    if raw in ("", ".", ".."):
        raw = "文件"
    ext = os.path.splitext(raw)[1]
    if len(ext) > 16:
        ext = ""                                  # 过长“扩展名”视作正文
    stem = raw[:-len(ext)] if ext else raw
    stem = stem.strip(". ") or "文件"
    if len(stem) + len(ext) > 180:
        stem = stem[:max(1, 180 - len(ext))]
    return (stem + ext) or "文件"


def _safe_mime(raw_mime):
    mime = str(raw_mime or "").strip().lower()
    if _MIME_RE.match(mime):
        return mime
    return "application/octet-stream"


def _content_type_for(name, mime):
    if mime:
        return mime
    guessed, _ = mimetypes.guess_type(str(name or ""))
    return guessed or "application/octet-stream"


def _parse_range(header, size):
    """解析单段 Range（bytes=a-b / a- / -n）；非法或多段返回 None。"""
    text = (header or "").strip()
    if not text or not text.lower().startswith("bytes=") or "," in text:
        return None
    spec = text[6:].strip()
    if "-" not in spec:
        return None
    left, right = spec.split("-", 1)
    try:
        if left == "":
            suffix = int(right)
            if suffix <= 0:
                return None
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(left)
            end = int(right) if right != "" else size - 1
    except ValueError:
        return None
    if start < 0 or end < start or (size > 0 and start >= size):
        return None
    if size == 0:
        return None
    return start, min(end, size - 1)


# ---------------------------------------------------------------------------
# secret / 签名
# ---------------------------------------------------------------------------
def _write_secret():
    os.makedirs(ROOT, exist_ok=True)
    value = secrets.token_hex(32)
    fd = os.open(SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(value + "\n")
    try:
        os.chmod(SECRET_PATH, 0o600)
    except OSError:
        pass
    return value


def _secret():
    """服务端随机 secret（<数据根>/.secret，0600）；丢失则已发下载链接全部失效。"""
    global _SECRET
    with _SECRET_LOCK:
        if _SECRET:
            return _SECRET
        value = ""
        try:
            with open(SECRET_PATH, "r", encoding="ascii") as fh:
                value = fh.read().strip()
        except OSError:
            value = ""
        if len(value) < 32:
            value = _write_secret()
        _SECRET = value.encode("utf-8")
        return _SECRET


def _sign(file_id, session_id, exp_ms):
    msg = ("%s|%s|%d" % (file_id, session_id, int(exp_ms))).encode("utf-8")
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def _sign_ok(file_id, session_id, exp_ms, sig):
    expected = _sign(file_id, session_id, exp_ms)
    try:
        return hmac.compare_digest(str(sig or ""), expected)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 存储：目录 / 会话 / 事件 / 上传
# ---------------------------------------------------------------------------
def ensure_dirs():
    for path in (ROOT, SESSION_DIR, FILES_DIR, UPLOAD_DIR):
        os.makedirs(path, exist_ok=True)


def _acquire_instance_lock():
    """单实例保护：对 <数据根>/.instance 加进程内排他锁。

    端口绑定在 Linux 上已能挡住重复实例；这里再补一层文件锁，避免
    （例如 Windows 开发机 SO_REUSEADDR 语义）两个实例抢同一数据根。成功返回 fd。
    """
    ensure_dirs()
    path = os.path.join(ROOT, ".instance")
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
        except OSError:
            pass
        return fd
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        return None


def _sid_hash(sid):
    return hashlib.sha256(str(sid).encode("utf-8")).hexdigest()[:24]


def _session_path(session_id):
    return os.path.join(SESSION_DIR, session_id + ".json")


def _load_index():
    data = _read_json_file(INDEX_PATH, limit=4 * 1024 * 1024)
    return data if isinstance(data, dict) else {}


def _save_index(index):
    _atomic_write_json(INDEX_PATH, index)


def _load_session(session_id):
    if not _valid_hex_id(session_id):
        return None
    return _read_json_file(_session_path(session_id))


def _save_session(sess):
    _atomic_write_json(_session_path(sess["id"]), sess)


def _session_last_activity(sess):
    """会话最后活动时间（毫秒）：活动 = open / 上传 init·finish / 文字 / 指令。"""
    return int(sess.get("lastActivityAt")
               or sess.get("updatedAt") or sess.get("createdAt") or 0)


def _session_files(sess):
    items = sess.get("files") or []
    return items if isinstance(items, list) else []


def _file_uploaded_at(file_rec):
    return int(file_rec.get("at") or 0)


def _file_expired(file_rec, now=None):
    """文件是否已过 TTL：**从上传完成时刻（file.at）起算 72h**，逐文件独立过期。"""
    at = _file_uploaded_at(file_rec)
    if at <= 0:
        return True
    now = _now_ms() if now is None else now
    return (now - at) > TTL_SEC * 1000


def _live_files(sess, now=None):
    now = _now_ms() if now is None else now
    return [item for item in _session_files(sess) if not _file_expired(item, now)]


def _session_alive(sess, now=None):
    """会话是否仍有效（v2.1）：
    - 还有未过期文件 → 有效（文件各自 72h 过期，期间会话保留，便于继续下载）；
    - 无文件 → 距最后活动 ≤ TTL（会话空闲 72h 滑动回收）。
    """
    if not sess or sess.get("closed"):
        return False
    now = _now_ms() if now is None else now
    if _live_files(sess, now):
        return True
    return (now - _session_last_activity(sess)) <= TTL_SEC * 1000


def _session_expires_at(sess):
    """对外展示的 expiresAt（毫秒）：= max(最后活动 + TTL, 各文件上传时刻 + TTL)，至少不早于现在。"""
    now = _now_ms()
    base = _session_last_activity(sess) + TTL_SEC * 1000
    for item in _session_files(sess):
        at = _file_uploaded_at(item)
        if at > 0:
            base = max(base, at + TTL_SEC * 1000)
    return max(base, now)


def _public_session(sess):
    return {"id": sess["id"], "code": sess["code"],
            "createdAt": int(sess["createdAt"]),
            "expiresAt": _session_expires_at(sess)}


def _append_event_locked(sess, kind, payload, from_name):
    seq = int(sess.get("seq") or 0) + 1
    now = _now_ms()
    sess["seq"] = seq
    events = sess.setdefault("events", [])
    events.append({
        "seq": seq,
        "kind": kind,
        "at": now,
        "from": {"name": str(from_name or "")[:40]},
        "payload": payload,
    })
    if len(events) > MAX_EVENTS:
        del events[:len(events) - MAX_EVENTS]
    # 文字 / 指令 / 上传完成都算会话活动 → 滑动续期空闲计时
    sess["lastActivityAt"] = now
    sess["updatedAt"] = now
    return seq


def _load_upload_meta(upload_id):
    if not _valid_hex_id(upload_id):
        return None
    return _read_json_file(os.path.join(UPLOAD_DIR, upload_id, "meta.json"),
                           limit=1024 * 1024)


def _save_upload_meta(upload_id, meta):
    _atomic_write_json(os.path.join(UPLOAD_DIR, upload_id, "meta.json"), meta)


def _upload_dir(upload_id):
    return os.path.join(UPLOAD_DIR, upload_id)


def _upload_lock(upload_id):
    with _LOCK:
        lock = _UPLOAD_LOCKS.get(upload_id)
        if lock is None:
            lock = _UPLOAD_LOCKS[upload_id] = threading.Lock()
        return lock


def _release_upload_lock(upload_id):
    with _LOCK:
        _UPLOAD_LOCKS.pop(upload_id, None)


def _delete_uploads_for_session_locked(session_id):
    try:
        names = os.listdir(UPLOAD_DIR)
    except OSError:
        return
    for name in names:
        meta = _load_upload_meta(name)
        if meta and meta.get("sessionId") == session_id:
            shutil.rmtree(_upload_dir(name), ignore_errors=True)


def _delete_session_locked(session_id):
    """删除会话 JSON + 文件目录 + 该会话未完成分片 + 索引项（调用方已持 _LOCK）。"""
    try:
        os.remove(_session_path(session_id))
    except OSError:
        pass
    shutil.rmtree(os.path.join(FILES_DIR, session_id), ignore_errors=True)
    _delete_uploads_for_session_locked(session_id)
    index = _load_index()
    changed = False
    for sid_hash, value in list(index.items()):
        if value == session_id:
            index.pop(sid_hash, None)
            changed = True
    if changed:
        _save_index(index)


def _find_active_session_locked(sid):
    index = _load_index()
    session_id = index.get(_sid_hash(sid))
    if not session_id:
        return None
    sess = _load_session(session_id)
    now = _now_ms()
    if sess is None or not _session_alive(sess, now):
        _delete_session_locked(session_id)
        return None
    return sess


def _open_session_locked(auth):
    sid = auth["sid"]
    existing = _find_active_session_locked(sid)
    if existing is not None:
        # 复用：顺带刷新展示用姓名/座号（同 sid 的多端可能先后登录），并算一次活动
        existing["name"] = auth.get("name") or existing.get("name") or ""
        if auth.get("seat") is not None:
            existing["seat"] = auth.get("seat")
        now = _now_ms()
        existing["lastActivityAt"] = now
        existing["updatedAt"] = now
        _save_session(existing)
        return existing
    now = _now_ms()
    for _ in range(5):
        session_id = secrets.token_hex(8)
        if _load_session(session_id) is None:
            break
    sess = {
        "id": session_id,
        "code": "%06d" % secrets.randbelow(1000000),
        "sid": sid,
        "seat": auth.get("seat"),
        "name": auth.get("name") or "",
        "createdAt": now,
        "lastActivityAt": now,
        "expiresAt": now + TTL_SEC * 1000,     # 兼容字段；对外以 _session_expires_at() 计算为准
        "closed": False,
        "seq": 0,
        "events": [],
        "files": [],
        "updatedAt": now,
    }
    _save_session(sess)
    index = _load_index()
    index[_sid_hash(sid)] = session_id
    _save_index(index)
    log("session open sid_hash=%s session=%s" % (_sid_hash(sid)[:8], session_id))
    return sess


def _sess_owned_locked(auth, session_id):
    if not isinstance(session_id, str) or not session_id.strip():
        raise HttpError(400, "缺少 sessionId")
    session_id = session_id.strip()
    if not _valid_hex_id(session_id):
        raise HttpError(400, "sessionId 格式错误")
    sess = _load_session(session_id)
    if sess is None:
        raise HttpError(404, "会话不存在或已过期")
    if sess.get("sid") != auth.get("sid"):
        raise HttpError(403, "无权访问该会话")
    if not _session_alive(sess):
        _delete_session_locked(session_id)
        raise HttpError(404, "会话已结束")
    return sess


def _session_bytes_locked(sess):
    """会话内**未过期**文件的总字节数（过期文件在清理前也不再计入上限）。"""
    total = 0
    for item in _live_files(sess):
        try:
            total += int(item.get("size") or 0)
        except (TypeError, ValueError):
            continue
    return total


# ---------------------------------------------------------------------------
# 鉴权：CloudBase rpc/class_whoami（fail closed）
# ---------------------------------------------------------------------------
def _gateway_whoami(token):
    if not PUBLISH_KEY:
        raise AuthError(503, "鉴权服务暂不可用")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": GW_UA,
        "X-Device-Id": token,
        "Authorization": "Bearer " + PUBLISH_KEY,
        "Origin": os.environ.get("DROP_ORIGIN", DEFAULT_ORIGIN),
    }
    req = urllib.request.Request(GATEWAY + "rpc/class_whoami", data=b"{}",
                                 method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=GATEWAY_TIMEOUT) as resp:
            status = resp.status
            raw = resp.read(65536)
    except urllib.error.HTTPError:
        raise AuthError(503, "鉴权服务暂不可用")
    except (urllib.error.URLError, OSError, ValueError):
        raise AuthError(503, "鉴权服务暂不可用")
    if status != 200:
        raise AuthError(503, "鉴权服务暂不可用")
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise AuthError(503, "鉴权服务响应异常")
    if not isinstance(data, dict):
        raise AuthError(503, "鉴权服务响应异常")
    if data.get("ok") is not True:
        reason = _BAD_CHARS.sub("", str(data.get("reason") or "")).strip()[:80]
        raise AuthError(401, reason or "身份无效")
    sid = str(data.get("sid") or "").strip()
    name = _BAD_CHARS.sub("", str(data.get("name") or "")).strip()[:40]
    if not sid:
        raise AuthError(503, "鉴权服务响应异常")
    return {"sid": sid, "name": name, "seat": data.get("seat")}


def validate_token(token):
    """token → {sid,name,seat}；成功缓存 AUTH_CACHE_SEC 秒；失败抛 AuthError。"""
    token = str(token or "").strip()
    if not token:
        raise AuthError(401, "缺少身份令牌")
    if len(token) > 600:
        raise AuthError(401, "身份令牌非法")
    now = time.time()
    with _LOCK:
        hit = _AUTH_CACHE.get(token)
        if hit is not None and hit[1] > now:
            return dict(hit[0])
        if hit is not None:
            _AUTH_CACHE.pop(token, None)
    payload = _gateway_whoami(token)
    with _LOCK:
        if len(_AUTH_CACHE) > AUTH_CACHE_MAX:
            _AUTH_CACHE.clear()
        _AUTH_CACHE[token] = (payload, time.time() + AUTH_CACHE_SEC)
    return dict(payload)


# ---------------------------------------------------------------------------
# 健康统计 / 清理
# ---------------------------------------------------------------------------
def health_stats():
    sessions = 0
    files = 0
    total = 0
    now = _now_ms()
    with _LOCK:
        for session_id in set(_load_index().values()):
            sess = _load_session(session_id)
            if not _session_alive(sess, now):
                continue
            sessions += 1
            items = _live_files(sess, now)
            files += len(items)
            total += sum(int(item.get("size") or 0) for item in items)
    # 公开字段（契约 §1.3）：ttl = **文件 TTL**秒（259200 = 3 天，自上传完成起算）；
    # session_idle_ttl = **会话空闲** TTL（滑动，最后活动后 72h 无活动且无未过期文件才回收）；
    # max_file_bytes / max_session_bytes = 0 表示不限（磁盘为唯一限制）。
    return {"ok": True, "version": VERSION, "sessions": sessions,
            "files": files, "bytes": total,
            "ttl": TTL_SEC, "ttl_hours": TTL_SEC // 3600,
            "file_ttl": TTL_SEC, "session_idle_ttl": TTL_SEC,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_session_bytes": MAX_SESSION_BYTES,
            "max_files": MAX_FILES,
            "upload_ttl": UPLOAD_TTL_SEC,
            "disk_free": _disk_free(), "disk_reserve": DISK_RESERVE}


def _disk_free():
    try:
        return shutil.disk_usage(ROOT).free
    except OSError:
        return 0


def _fmt_mib(value):
    return "%d MiB" % (int(value) // (1024 * 1024))


def _check_disk(need, reason=None):
    """磁盘安全余量检查：可用空间 - need 必须仍 ≥ DISK_RESERVE，否则 507。"""
    need = max(0, int(need))
    free = _disk_free()
    if free - need < DISK_RESERVE:
        raise HttpError(507, reason or (
            "服务器磁盘空间不足（可用 %s，需要 %s，保留余量 %s），"
            "请稍后再试或先关闭其它文件传输会话"
            % (_fmt_mib(free), _fmt_mib(need), _fmt_mib(DISK_RESERVE))))


def _file_limit():
    """单文件上限（字节）；0 = 不限。"""
    return MAX_FILE_BYTES if MAX_FILE_BYTES > 0 else 0


def _session_limit():
    """单会话总量上限（字节）；0 = 不限。"""
    return MAX_SESSION_BYTES if MAX_SESSION_BYTES > 0 else 0



def _expire_files_locked(sess, now):
    """逐文件 TTL 清理（v2.1）：`now - file.at > TTL_SEC` → 删文件实体 + 从会话文件表移除。

    文件按「各自上传完成时刻 + 72h」独立过期（不是会话统一过期）；返回 (个数, 释放字节)。
    file 事件保留 seq（历史不丢），/state 会把它标记为 expired 并不再重签下载链接。
    """
    expired = []
    keep = []
    for item in _session_files(sess):
        if _file_expired(item, now):
            expired.append(item)
        else:
            keep.append(item)
    if not expired:
        return 0, 0
    freed = 0
    for item in expired:
        file_id = str(item.get("id") or "")
        if _valid_hex_id(file_id):
            try:
                os.remove(os.path.join(FILES_DIR, sess["id"], file_id + ".bin"))
            except OSError:
                pass
        try:
            freed += int(item.get("size") or 0)
        except (TypeError, ValueError):
            pass
    sess["files"] = keep
    return len(expired), freed


def cleanup_once():
    """清理（每 60s 后台线程调用）：
    ① 逐文件 TTL：文件自上传完成起 72h 后删实体并移出会话文件表；
    ② 会话空闲 TTL：无未过期文件且最后活动 > 72h → 删除整个会话（含残留文件/未完成分片）；
    ③ 长时间无活动的孤儿分片（24h）；
    会话「有未过期文件」期间不会因空闲被删（保证文件可下载），文件全部过期后再按空闲规则收尾。
    """
    now = _now_ms()
    removed = 0
    with _LOCK:
        index = _load_index()
        for sid_hash, session_id in list(index.items()):
            sess = _load_session(session_id)
            if sess is None:
                index.pop(sid_hash, None)
                continue
            expired_count, freed = _expire_files_locked(sess, now)
            if expired_count:
                log("file ttl cleanup session=%s files=%d bytes=%d"
                    % (session_id, expired_count, freed))
            if sess.get("closed"):
                _delete_session_locked(session_id)
                index.pop(sid_hash, None)
                removed += 1
                log("session cleanup session=%s (closed)" % session_id)
                continue
            if not _session_alive(sess, now):
                _delete_session_locked(session_id)
                index.pop(sid_hash, None)
                removed += 1
                log("session idle cleanup session=%s" % session_id)
                continue
            if expired_count:
                _save_session(sess)       # 文件表变化落盘
        _save_index(index)
    # 孤儿分片：会话已不存在、或长时间无活动（UPLOAD_TTL_SEC，默认 24h）后回收。
    # 注意：会话 TTL 是 72h，但未完成分片不属于「已上传文件」，用更短 TTL 避免占满磁盘。
    try:
        names = os.listdir(UPLOAD_DIR)
    except OSError:
        names = []
    for name in names:
        path = _upload_dir(name)
        meta = _load_upload_meta(name)
        stale = False
        if meta is None:
            try:
                stale = (time.time() - os.path.getmtime(path)) > UPLOAD_TTL_SEC
            except OSError:
                stale = True
        else:
            # 每次传分片都会重写 meta.json → 用 meta mtime 表示「最后活动时间」
            last_touch = int(meta.get("createdAt") or 0)
            try:
                last_touch = max(last_touch, int(
                    os.path.getmtime(os.path.join(path, "meta.json")) * 1000))
            except OSError:
                pass
            session_id = meta.get("sessionId")
            if not session_id or _load_session(session_id) is None:
                stale = True
            elif last_touch and (now - last_touch) > UPLOAD_TTL_SEC * 1000:
                stale = True
        if stale:
            shutil.rmtree(path, ignore_errors=True)
            _release_upload_lock(name)
    # 清理内存中过期的 upload 锁
    with _LOCK:
        if len(_UPLOAD_LOCKS) > 64:
            _UPLOAD_LOCKS.clear()
    return removed


def _cleanup_loop():
    while True:
        try:
            time.sleep(60)
            cleanup_once()
        except Exception as exc:  # noqa: BLE001
            warn("cleanup 异常：%s: %s" % (exc.__class__.__name__, str(exc)[:160]))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _public_base(handler):
    if PUBLIC_BASE:
        return PUBLIC_BASE
    headers = handler.headers
    proto = (headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    if proto not in ("http", "https"):
        proto = "http"
    host = ((headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
            or (headers.get("Host") or "").strip())
    if not host:
        host = "127.0.0.1"
    return "%s://%s%s" % (proto, host, PUBLIC_PREFIX)


def _download_url(handler, file_id, session_id, exp_ms=None):
    exp = int(exp_ms if exp_ms is not None else _now_ms() + URL_TTL_SEC * 1000)
    sig = _sign(file_id, session_id, exp)
    query = urllib.parse.urlencode({"s": session_id, "exp": exp, "sig": sig})
    return "%s/file/%s?%s" % (_public_base(handler), file_id, query)


class Handler(BaseHTTPRequestHandler):
    server_version = "class-tools-drop/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: D401  统一走下方 _dispatch 的访问日志
        pass

    # -- 基础响应 ----------------------------------------------------------
    def _cors_headers(self):
        origin = (self.headers.get("Origin") or "").strip()
        return {
            "Access-Control-Allow-Origin": origin or "*",
            "Vary": "Origin",
            "Access-Control-Allow-Headers":
                "Content-Type,X-Device-Id,X-Upload-Id",
            "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
            "Access-Control-Expose-Headers": "Content-Length,Content-Range",
        }

    def _base_headers(self):
        headers = self._cors_headers()
        headers["X-Content-Type-Options"] = "nosniff"
        return headers

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._status = status
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in self._base_headers().items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _send_error_json(self, status, reason):
        if self.command in ("POST", "DELETE") and not getattr(self, "_body_read", False):
            self.close_connection = True          # 未读 body 时不能复用连接
        self._send_json(status, {"ok": False, "reason": str(reason or "请求失败")})

    def _send_options(self):
        self._status = 204
        try:
            self.send_response(204)
            for key, value in self._base_headers().items():
                self.send_header(key, value)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    # -- 请求体 ------------------------------------------------------------
    def _content_length(self, required=True):
        raw = self.headers.get("Content-Length")
        if raw is None:
            if required:
                raise HttpError(411, "缺少 Content-Length")
            return 0
        try:
            length = int(str(raw).strip())
        except ValueError:
            raise HttpError(400, "Content-Length 非法")
        if length < 0:
            raise HttpError(400, "Content-Length 非法")
        return length

    def _read_body(self, limit, required=True):
        length = self._content_length(required=required)
        if length > limit:
            # 拒绝前尽力把客户端已发送的 body 读掉（有界），否则直接关连接会让客户端 write 收到 RST
            # （表现为 ConnectionAbortedError；测试/浏览器上传超限时也更友好）。
            self._body_read = True
            self.close_connection = True
            try:
                remain = min(int(length), 16 * 1024 * 1024)
                while remain > 0:
                    chunk = self.rfile.read(min(256 * 1024, remain))
                    if not chunk:
                        break
                    remain -= len(chunk)
            except OSError:
                pass
            raise HttpError(413, "请求体过大")
        data = self.rfile.read(length) if length else b""
        self._body_read = True
        if len(data) != length:
            raise HttpError(400, "请求体不完整")
        return data

    def _read_json(self, limit=JSON_BODY_MAX):
        data = self._read_body(limit, required=False)
        if not data:
            return {}
        try:
            obj = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HttpError(400, "JSON 格式错误")
        if not isinstance(obj, dict):
            raise HttpError(400, "JSON 必须是对象")
        return obj

    # -- 鉴权 --------------------------------------------------------------
    def _auth(self):
        token = (self.headers.get("X-Device-Id") or "").strip()
        if not token:
            raise AuthError(401, "缺少身份令牌")
        return validate_token(token)

    # -- 路由 --------------------------------------------------------------
    def do_OPTIONS(self):
        try:
            self._send_options()
        except HttpError as exc:
            self._send_error_json(exc.status, exc.reason)

    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def _dispatch(self):
        started = time.time()
        self._status = 500
        self._body_read = False
        path_for_log = "?"
        try:
            parsed = urllib.parse.urlsplit(self.path or "/")
            path = urllib.parse.unquote(parsed.path or "/")
            path_for_log = path
            # 兼容「Caddy 已 strip_prefix /drop」与「未 strip」两种入口
            if path in ("/drop", "/drop/"):
                path = "/"
            elif path.startswith("/drop/"):
                path = path[len("/drop"):]
            query = urllib.parse.parse_qs(parsed.query or "", keep_blank_values=True)
            method = self.command

            if method == "OPTIONS":
                return self._send_options()
            if path in ("/__health", "/__health/"):
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "方法不支持")
                return self._send_json(200, health_stats())
            if path.startswith("/file/"):
                if method in ("GET", "HEAD"):
                    return self._route_file(path[len("/file/"):], query)
                if method == "DELETE":
                    return self._route_file_delete(path[len("/file/"):], query)
                raise HttpError(405, "方法不支持")

            if path == "/open":
                if method != "POST":
                    raise HttpError(405, "方法不支持")
                return self._route_open()
            if path == "/mine":
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "方法不支持")
                return self._route_mine()
            if path == "/presence":
                if method == "GET":
                    return self._route_presence_get()
                if method == "POST":
                    return self._route_presence_post()
                raise HttpError(405, "方法不支持")
            if path == "/state":
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "方法不支持")
                return self._route_state(query)
            if path == "/close":
                if method != "POST":
                    raise HttpError(405, "方法不支持")
                return self._route_close()
            if path == "/upload/init":
                if method != "POST":
                    raise HttpError(405, "方法不支持")
                return self._route_upload_init()
            if path == "/upload/chunk":
                if method != "POST":
                    raise HttpError(405, "方法不支持")
                return self._route_upload_chunk(query)
            if path == "/upload/finish":
                if method != "POST":
                    raise HttpError(405, "方法不支持")
                return self._route_upload_finish()
            if path == "/text":
                if method != "POST":
                    raise HttpError(405, "方法不支持")
                return self._route_text()
            if path == "/cmd":
                if method != "POST":
                    raise HttpError(405, "方法不支持")
                return self._route_cmd()
            if path.startswith("/session/"):
                if method != "DELETE":
                    raise HttpError(405, "方法不支持")
                return self._route_delete_session(path[len("/session/"):])
            raise HttpError(404, "接口不存在")
        except HttpError as exc:
            self._send_error_json(exc.status, exc.reason)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as exc:  # noqa: BLE001
            warn("请求异常 %s %s：%s: %s" % (
                self.command, path_for_log, exc.__class__.__name__, str(exc)[:160]))
            warn(traceback.format_exc()[-900:])
            try:
                self._send_error_json(500, "服务内部错误")
            except Exception:  # noqa: BLE001
                self.close_connection = True
        finally:
            log("%s %s -> %s %.0fms" % (
                self.command, path_for_log, self._status,
                (time.time() - started) * 1000))

    # -- 会话 --------------------------------------------------------------
    def _route_open(self):
        auth = self._auth()
        self._read_json()                         # body 可为空 / {}
        with _LOCK:
            sess = _open_session_locked(auth)
            payload = {"ok": True, "session": _public_session(sess)}
        self._send_json(200, payload)

    def _route_mine(self):
        auth = self._auth()
        with _LOCK:
            sess = _find_active_session_locked(auth["sid"])
            payload = {"ok": True,
                       "session": _public_session(sess) if sess else None}
        self._send_json(200, payload)

    def _route_state(self, query):
        auth = self._auth()
        session_id = _query_one(query, "sessionId")
        since_raw = _query_one(query, "since", "0")
        try:
            since = max(0, int(str(since_raw or "0")))
        except ValueError:
            raise HttpError(400, "since 非法")
        with _LOCK:
            sess = _sess_owned_locked(auth, session_id)
            now = _now_ms()
            events = []
            for ev in sess.get("events") or []:
                if int(ev.get("seq") or 0) <= since:
                    continue
                item = dict(ev)
                payload = dict(ev.get("payload") or {})
                # v2.1：文件各自「上传完成 + 72h」过期；每次读事件列表时只对
                # **未过期且实体仍在** 的文件重新签发下载 URL（解决「文件保留 3 天但签名仅 30 分钟」）；
                # 过期文件保留 seq（历史不丢），标记 expired 且不再给 downloadUrl。
                if ev.get("kind") == "file":
                    file_id = str(payload.get("fileId") or "")
                    path = os.path.join(FILES_DIR, sess["id"], file_id + ".bin")
                    record = None
                    for f in _session_files(sess):
                        if f.get("id") == file_id:
                            record = f
                            break
                    if (record is not None and not _file_expired(record, now)
                            and _valid_hex_id(file_id) and os.path.isfile(path)):
                        payload["downloadUrl"] = _download_url(
                            self, file_id, sess["id"])
                        payload.pop("expired", None)
                    else:
                        payload.pop("downloadUrl", None)
                        payload["expired"] = True
                item["payload"] = payload
                events.append(item)
            cursor = int(events[-1]["seq"]) if events else since
            payload = {
                "ok": True,
                "session": {"id": sess["id"], "code": sess["code"],
                            "expiresAt": _session_expires_at(sess),
                            "closed": bool(sess.get("closed"))},
                "events": events,
                "cursor": cursor,
            }
        self._send_json(200, payload)

    def _route_presence_get(self):
        """大屏在线状态：同一班级账号（同 sid）任意设备可查。30s 内 heartbeat 视为在线。"""
        auth = self._auth()
        with _LOCK:
            sess = _find_active_session_locked(auth["sid"])
            now = _now_ms()
            at = int(sess.get("stageAt") or 0) if sess is not None else 0
            stage = bool(sess is not None and at > 0 and (now - at) <= PRESENCE_TTL_MS)
        self._send_json(200, {"ok": True, "stage": stage, "at": at})

    def _route_presence_post(self):
        """大屏心跳：{stage:true} 标记在线（30s 有效），{stage:false} 立即下线。"""
        auth = self._auth()
        body = self._read_json()
        want = bool(body.get("stage", True))
        with _LOCK:
            sess = _find_active_session_locked(auth["sid"])
            now = _now_ms()
            if sess is None:
                self._send_json(200, {"ok": False, "stage": False,
                                      "reason": "云空间会话不存在；请先打开大屏/文件传输"})
                return
            sess["stageAt"] = now if want else 0
            sess["lastActivityAt"] = now
            sess["updatedAt"] = now
            _save_session(sess)
        self._send_json(200, {"ok": True, "stage": want, "at": now})

    def _route_close(self):
        auth = self._auth()
        body = self._read_json()
        session_id = str(body.get("sessionId") or "").strip()
        with _LOCK:
            if session_id:
                sess = _sess_owned_locked(auth, session_id)
            else:
                sess = _find_active_session_locked(auth["sid"])
            if sess is not None:
                _delete_session_locked(sess["id"])
                log("session close session=%s" % sess["id"])
        self._send_json(200, {"ok": True})

    def _route_delete_session(self, session_id):
        auth = self._auth()
        with _LOCK:
            sess = _sess_owned_locked(auth, session_id)
            _delete_session_locked(sess["id"])
        self._send_json(200, {"ok": True})

    # -- 分片上传 ----------------------------------------------------------
    def _route_upload_init(self):
        auth = self._auth()
        body = self._read_json()
        session_id = str(body.get("sessionId") or "").strip()
        name = _safe_filename(body.get("name"))
        try:
            size = int(body.get("size"))
        except (TypeError, ValueError):
            raise HttpError(400, "文件大小非法")
        if size <= 0:
            raise HttpError(400, "文件大小非法")
        if _file_limit() and size > _file_limit():
            raise HttpError(413, "文件超过单文件上限（%s）" % _fmt_mib(_file_limit()))
        try:
            total_chunks = int(body.get("totalChunks"))
        except (TypeError, ValueError):
            raise HttpError(400, "分片数非法")
        if total_chunks < 1 or total_chunks > MAX_TOTAL_CHUNKS:
            raise HttpError(400, "分片数非法（1..%d）" % MAX_TOTAL_CHUNKS)
        mime = _safe_mime(body.get("mime") or "")
        with _LOCK:
            sess = _sess_owned_locked(auth, session_id)
            if len(_live_files(sess)) >= MAX_FILES:
                raise HttpError(413, "该会话文件数已达上限（%d 个）" % MAX_FILES)
            if (_session_limit()
                    and _session_bytes_locked(sess) + size > _session_limit()):
                raise HttpError(413, "该会话文件总量已达上限（%s）"
                                % _fmt_mib(_session_limit()))
            _check_disk(size)
            for _ in range(5):
                upload_id = secrets.token_hex(8)
                if not os.path.exists(_upload_dir(upload_id)):
                    break
            meta = {
                "uploadId": upload_id,
                "sessionId": sess["id"],
                "sid": auth["sid"],
                "name": name,
                "size": size,
                "mime": mime,
                "totalChunks": total_chunks,
                "received": {},
                "createdAt": _now_ms(),
            }
            os.makedirs(_upload_dir(upload_id), exist_ok=True)
            _save_upload_meta(upload_id, meta)
            # 上传发起算会话活动（滑动空闲 TTL）
            now = _now_ms()
            sess["lastActivityAt"] = now
            sess["updatedAt"] = now
            _save_session(sess)
        self._send_json(200, {"ok": True, "uploadId": upload_id,
                              "chunkSize": CHUNK_SIZE})

    def _route_upload_chunk(self, query):
        auth = self._auth()
        upload_id = (_query_one(query, "uploadId")
                     or (self.headers.get("X-Upload-Id") or "").strip())
        if not _valid_hex_id(upload_id):
            raise HttpError(400, "uploadId 非法")
        try:
            index = int(_query_one(query, "index", "-1"))
        except ValueError:
            raise HttpError(400, "分片编号非法")
        length = self._content_length()
        if length <= 0:
            raise HttpError(400, "空分片")
        if length > CHUNK_BODY_MAX:
            self.close_connection = True
            raise HttpError(413, "分片超过 %d MiB" % (CHUNK_BODY_MAX // (1024 * 1024)))
        lock = _upload_lock(upload_id)
        acquired = lock.acquire(timeout=120)
        try:
            if not acquired:
                raise HttpError(500, "分片写入繁忙，请重试")
            meta = _load_upload_meta(upload_id)
            if meta is None:
                raise HttpError(404, "上传任务不存在或已过期")
            if meta.get("sid") != auth.get("sid"):
                raise HttpError(403, "无权访问该上传任务")
            total_chunks = int(meta.get("totalChunks") or 0)
            if index < 0 or index >= total_chunks:
                raise HttpError(400, "分片编号超出范围")
            with _LOCK:
                if _load_session(str(meta.get("sessionId") or "")) is None:
                    raise HttpError(404, "会话已结束")
            # 大文件 / 无单文件上限时唯一的硬约束：磁盘余量。写入前先检查，
            # 不足返回 507（中文 reason），避免半途 ENOSPC 留下损坏分片。
            _check_disk(length, reason=(
                "服务器磁盘空间不足，无法继续上传该分片（单分片 %s，保留余量 %s）"
                % (_fmt_mib(length), _fmt_mib(DISK_RESERVE))))
            data = self._read_body(CHUNK_BODY_MAX)
            part_path = os.path.join(_upload_dir(upload_id), "%d.part" % index)
            tmp = part_path + ".tmp"
            try:
                with open(tmp, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    try:
                        os.fsync(fh.fileno())
                    except OSError:
                        pass
                os.replace(tmp, part_path)
            except OSError:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise HttpError(507, "服务器磁盘空间不足，分片写入失败，请稍后重试")
            with _LOCK:
                meta = _load_upload_meta(upload_id) or meta
                received = meta.setdefault("received", {})
                received[str(index)] = len(data)
                _save_upload_meta(upload_id, meta)
                total_received = sum(int(v or 0) for v in received.values())
            self._send_json(200, {"ok": True, "received": total_received})
        finally:
            if acquired:
                lock.release()

    def _route_upload_finish(self):
        auth = self._auth()
        body = self._read_json()
        session_id = str(body.get("sessionId") or "").strip()
        upload_id = str(body.get("uploadId") or "").strip()
        if not _valid_hex_id(upload_id):
            raise HttpError(400, "uploadId 非法")
        lock = _upload_lock(upload_id)
        acquired = lock.acquire(timeout=600)
        file_id = ""
        final_path = ""
        part_tmp = ""
        try:
            if not acquired:
                raise HttpError(500, "上传繁忙，请重试")
            meta = _load_upload_meta(upload_id)
            if meta is None:
                raise HttpError(404, "上传任务不存在或已过期")
            if meta.get("sid") != auth.get("sid"):
                raise HttpError(403, "无权访问该上传任务")
            with _LOCK:
                sess = _sess_owned_locked(auth, session_id or str(meta.get("sessionId")))
                if sess["id"] != meta.get("sessionId"):
                    raise HttpError(403, "无权访问该会话")
                files = sess.get("files") or []
                if len(files) >= MAX_FILES:
                    raise HttpError(413, "该会话文件数已达上限（%d 个）" % MAX_FILES)
            total_chunks = int(meta.get("totalChunks") or 0)
            size = int(meta.get("size") or 0)
            received = meta.get("received") or {}
            parts = []
            actual = 0
            for idx in range(total_chunks):
                part_path = os.path.join(_upload_dir(upload_id), "%d.part" % idx)
                if not os.path.exists(part_path):
                    raise HttpError(400, "分片不完整（缺少第 %d 片）" % idx)
                part_size = os.path.getsize(part_path)
                if str(idx) in received and int(received[str(idx)] or 0) != part_size:
                    raise HttpError(400, "分片大小不一致（第 %d 片）" % idx)
                parts.append(part_path)
                actual += part_size
            if actual != size:
                raise HttpError(400, "文件大小不符（声明 %d / 实际 %d）" % (size, actual))
            with _LOCK:
                sess = _sess_owned_locked(auth, session_id or str(meta.get("sessionId")))
                if (_session_limit()
                        and _session_bytes_locked(sess) + actual > _session_limit()):
                    raise HttpError(413, "该会话文件总量已达上限（%s）"
                                    % _fmt_mib(_session_limit()))
            # 拼接需要「分片 + 成品」双份空间；磁盘不足直接 507，不留半成品。
            _check_disk(actual, reason=(
                "服务器磁盘空间不足，无法完成文件拼接（需要额外 %s，保留余量 %s）"
                % (_fmt_mib(actual), _fmt_mib(DISK_RESERVE))))
            file_id = secrets.token_hex(8)
            final_path = os.path.join(FILES_DIR, sess["id"], file_id + ".bin")
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            part_tmp = final_path + ".part"
            try:
                with open(part_tmp, "wb") as out:
                    for part_path in parts:
                        with open(part_path, "rb") as src:
                            while True:
                                chunk = src.read(1024 * 1024)
                                if not chunk:
                                    break
                                out.write(chunk)
                    out.flush()
                    try:
                        os.fsync(out.fileno())
                    except OSError:
                        pass
            except OSError:
                try:
                    os.remove(part_tmp)
                except OSError:
                    pass
                raise HttpError(507, "服务器磁盘空间不足，文件拼接失败，请稍后重试")
            os.replace(part_tmp, final_path)
            with _LOCK:
                sess = _sess_owned_locked(auth, session_id or str(meta.get("sessionId")))
                name = _safe_filename(meta.get("name"))
                mime = _safe_mime(meta.get("mime") or "")
                payload = {
                    "fileId": file_id,
                    "name": name,
                    "size": actual,
                    "mime": mime,
                    "downloadUrl": _download_url(self, file_id, sess["id"]),
                }
                sess.setdefault("files", []).append({
                    "id": file_id, "name": name, "size": actual,
                    "mime": mime, "at": _now_ms(),
                })
                seq = _append_event_locked(sess, "file", payload, auth.get("name"))
                _save_session(sess)
            shutil.rmtree(_upload_dir(upload_id), ignore_errors=True)
            log("upload finish session=%s file=%s size=%d seq=%d"
                % (sess["id"], file_id, actual, seq))
            self._send_json(200, {"ok": True, "file": {
                "id": file_id, "name": name, "size": actual, "mime": mime,
                "downloadUrl": payload["downloadUrl"]}})
        except Exception:
            for path in (part_tmp, final_path):
                if path:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            raise
        finally:
            if acquired:
                lock.release()

    # -- 下载 --------------------------------------------------------------
    def _route_file(self, file_id, query):
        file_id = str(file_id or "").strip()
        if "/" in file_id or not _valid_hex_id(file_id):
            raise HttpError(404, "文件不存在")
        session_id = str(_query_one(query, "s") or "").strip()
        exp_raw = str(_query_one(query, "exp") or "").strip()
        sig = str(_query_one(query, "sig") or "").strip()
        if not session_id or not exp_raw or not sig:
            raise HttpError(403, "下载链接缺少参数")
        try:
            exp = int(exp_raw)
        except ValueError:
            raise HttpError(403, "下载链接无效")
        if exp <= _now_ms():
            raise HttpError(403, "下载链接已过期，请重新上传或刷新")
        if not _sign_ok(file_id, session_id, exp, sig):
            raise HttpError(403, "下载签名无效")
        with _LOCK:
            sess = _load_session(session_id)
            if sess is None:
                raise HttpError(404, "文件不存在或会话已结束")
            record = None
            for item in sess.get("files") or []:
                if item.get("id") == file_id:
                    record = item
                    break
        if record is None:
            raise HttpError(404, "文件不存在")
        # v2.1：逐文件 TTL —— 上传完成超过 72h 即视为已删除（即使清理线程还没轮到）
        if _file_expired(record):
            raise HttpError(404, "文件已过期（上传超过 72 小时，已自动删除）")
        path = os.path.join(FILES_DIR, session_id, file_id + ".bin")
        try:
            size = os.path.getsize(path)
        except OSError:
            raise HttpError(404, "文件不存在")
        inline = str(_query_one(query, "inline", "0")).lower() in ("1", "true", "yes")
        self._serve_file(path, record, size, inline)

    def _route_file_delete(self, file_id, query):
        """临时云空间：删除单个文件（仅本账号会话 owner；幂等）。

        - 删除实体 + 从会话 files 表移除，并追加 `filedel` 事件（其它同账号设备收到后从列表移除）；
        - 原 file 事件保留 seq（/state 会把它标记 expired、不再重签链接）；
        - 网络/磁盘异常不影响幂等语义：记录不存在返回 {ok:true,deleted:false}。
        """
        auth = self._auth()
        file_id = str(file_id or "").strip()
        if "/" in file_id or not _valid_hex_id(file_id):
            raise HttpError(404, "文件不存在")
        session_id = str(_query_one(query, "sessionId") or "").strip()
        name = ""
        size = 0
        with _LOCK:
            if session_id:
                sess = _sess_owned_locked(auth, session_id)
            else:
                sess = _find_active_session_locked(auth["sid"])
            if sess is None:
                raise HttpError(404, "云空间不存在或已回收")
            record = None
            keep = []
            for item in _session_files(sess):
                if str(item.get("id") or "") == file_id:
                    record = item
                else:
                    keep.append(item)
            if record is not None:
                name = str(record.get("name") or "")
                size = int(record.get("size") or 0)
                sess["files"] = keep
                now = _now_ms()
                sess["lastActivityAt"] = now
                sess["updatedAt"] = now
                _append_event_locked(sess, "filedel",
                                     {"fileId": file_id, "name": name, "size": size},
                                     auth.get("name"))
                _save_session(sess)
        if record is not None:
            try:
                os.remove(os.path.join(FILES_DIR, sess["id"], file_id + ".bin"))
            except OSError:
                pass
            log("file delete session=%s file=%s size=%d" % (sess["id"], file_id, size))
        self._send_json(200, {"ok": True, "deleted": record is not None,
                              "name": name, "size": size})

    def _serve_file(self, path, record, size, inline):
        name = _safe_filename(record.get("name"))
        mime = _content_type_for(name, _safe_mime(record.get("mime") or ""))
        quoted = urllib.parse.quote(name, safe="")
        disposition = "%s; filename*=UTF-8''%s" % (
            "inline" if inline else "attachment", quoted)
        range_header = self.headers.get("Range")
        selected = None
        if range_header and self.command == "GET":
            selected = _parse_range(range_header, size)
            if selected is None:
                self._status = 416
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                for key, value in self._base_headers().items():
                    self.send_header(key, value)
                self.end_headers()
                return
        start, end = selected if selected else (0, size - 1)
        length = end - start + 1 if size > 0 else 0
        status = 206 if selected else 200
        self._status = status
        try:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Disposition", disposition)
            self.send_header("Cache-Control", "no-store")
            if selected:
                self.send_header("Content-Range",
                                 "bytes %d-%d/%d" % (start, end, size))
            for key, value in self._base_headers().items():
                self.send_header(key, value)
            self.end_headers()
            if self.command == "HEAD" or length <= 0:
                return
            with open(path, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    # -- 文字 / 指令 -------------------------------------------------------
    def _route_text(self):
        auth = self._auth()
        body = self._read_json()
        session_id = str(body.get("sessionId") or "").strip()
        text = body.get("text")
        if not isinstance(text, str):
            raise HttpError(400, "文字格式错误")
        if len(text) < 1:
            raise HttpError(400, "文字不能为空")
        if len(text) > TEXT_MAX:
            raise HttpError(400, "文字超过 %d 字上限" % TEXT_MAX)
        with _LOCK:
            sess = _sess_owned_locked(auth, session_id)
            seq = _append_event_locked(sess, "text", {"text": text},
                                       auth.get("name"))
            _save_session(sess)
        self._send_json(200, {"ok": True, "seq": seq})

    def _route_cmd(self):
        auth = self._auth()
        body = self._read_json()
        session_id = str(body.get("sessionId") or "").strip()
        op = str(body.get("op") or "").strip()
        if op not in CMD_OPS:
            raise HttpError(400, "不支持的指令：%s" % (op or "(空)"))
        args = body.get("args")
        if args is None:
            args = {}
        if not isinstance(args, (dict, list, str, int, float, bool)):
            raise HttpError(400, "指令参数非法")
        try:
            encoded = json.dumps(args, ensure_ascii=False)
        except (TypeError, ValueError):
            raise HttpError(400, "指令参数非法")
        if len(encoded.encode("utf-8")) > ARGS_JSON_MAX:
            raise HttpError(413, "指令参数过大")
        with _LOCK:
            sess = _sess_owned_locked(auth, session_id)
            seq = _append_event_locked(sess, "cmd", {"op": op, "args": args},
                                       auth.get("name"))
            _save_session(sess)
        self._send_json(200, {"ok": True, "seq": seq})


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
def make_server(host="127.0.0.1", port=None):
    ensure_dirs()
    srv = ThreadingHTTPServer((host, int(PORT if port is None else port)), Handler)
    srv.daemon_threads = True
    return srv


def main():
    ensure_dirs()
    instance_fd = _acquire_instance_lock()
    if instance_fd is None:
        warn("FATAL 数据根 %s 已被另一个实例占用（.instance 锁），退出" % ROOT)
        return 1
    log("start v%s root=%s port=%d file_ttl=%ss(%.0fh) session_idle_ttl=%ss "
        "max_file=%s max_session=%s max_files=%d upload_ttl=%ss whoami_key=%s" % (
            VERSION, ROOT, PORT, TTL_SEC, TTL_SEC / 3600.0, TTL_SEC,
            "unlimited" if MAX_FILE_BYTES <= 0 else _fmt_mib(MAX_FILE_BYTES),
            "unlimited" if MAX_SESSION_BYTES <= 0 else _fmt_mib(MAX_SESSION_BYTES),
            MAX_FILES, UPLOAD_TTL_SEC,
            "set" if PUBLISH_KEY else "MISSING"))
    try:
        srv = make_server("127.0.0.1", PORT)
    except OSError as exc:
        warn("FATAL 监听 127.0.0.1:%d 失败（端口被占用？）：%s" % (PORT, exc))
        return 1
    try:
        cleanup_once()
    except Exception as exc:  # noqa: BLE001
        warn("启动清理失败：%s" % exc.__class__.__name__)
    thread = threading.Thread(target=_cleanup_loop, name="drop-cleanup", daemon=True)
    thread.start()
    log("listening on 127.0.0.1:%d" % PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("stop")
    finally:
        srv.server_close()
        try:
            os.close(instance_fd)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
