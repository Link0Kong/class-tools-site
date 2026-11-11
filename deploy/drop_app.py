# -*- coding: utf-8 -*-
"""drop_app.py — ECS「大屏临时互联通道」服务（Python 标准库，127.0.0.1:8093）

用途（2026-11-11，团日活动大屏跨端互联）：
    同账号（同 sid）的大屏 / 手机之间临时传文件、发文字、转发遥控指令。
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
    DROP_TTL_SEC          会话 TTL 秒，默认 7200
    DROP_MAX_FILE_BYTES   单文件上限，默认 2GiB
    DROP_MAX_SESSION_BYTES 单会话总量，默认 8GiB
    DROP_MAX_FILES        单会话文件数，默认 300
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

VERSION = "1.0"
ROOT = os.path.abspath(os.environ.get("DROP_ROOT", "/opt/class-tools/drop"))
PORT = int(os.environ.get("DROP_PORT", "8093"))
DEFAULT_GATEWAY = ("https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com"
                   "/v1/rdb/rest/")
GATEWAY = os.environ.get("DROP_GATEWAY") or DEFAULT_GATEWAY
if not GATEWAY.endswith("/"):
    GATEWAY += "/"
TTL_SEC = int(os.environ.get("DROP_TTL_SEC", "7200"))
MAX_FILE_BYTES = int(os.environ.get("DROP_MAX_FILE_BYTES", str(2 * 1024 ** 3)))
MAX_SESSION_BYTES = int(os.environ.get("DROP_MAX_SESSION_BYTES", str(8 * 1024 ** 3)))
MAX_FILES = int(os.environ.get("DROP_MAX_FILES", "300"))
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
MAX_TOTAL_CHUNKS = 65536
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


def _public_session(sess):
    return {"id": sess["id"], "code": sess["code"],
            "createdAt": int(sess["createdAt"]),
            "expiresAt": int(sess["expiresAt"])}


def _append_event_locked(sess, kind, payload, from_name):
    seq = int(sess.get("seq") or 0) + 1
    sess["seq"] = seq
    events = sess.setdefault("events", [])
    events.append({
        "seq": seq,
        "kind": kind,
        "at": _now_ms(),
        "from": {"name": str(from_name or "")[:40]},
        "payload": payload,
    })
    if len(events) > MAX_EVENTS:
        del events[:len(events) - MAX_EVENTS]
    sess["updatedAt"] = _now_ms()
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
    if (sess is None or sess.get("closed")
            or int(sess.get("expiresAt") or 0) <= now):
        _delete_session_locked(session_id)
        return None
    return sess


def _open_session_locked(auth):
    sid = auth["sid"]
    existing = _find_active_session_locked(sid)
    if existing is not None:
        # 复用：顺带刷新展示用姓名/座号（同 sid 的多端可能先后登录）
        existing["name"] = auth.get("name") or existing.get("name") or ""
        if auth.get("seat") is not None:
            existing["seat"] = auth.get("seat")
        existing["updatedAt"] = _now_ms()
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
        "expiresAt": now + TTL_SEC * 1000,
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
    if sess.get("closed") or int(sess.get("expiresAt") or 0) <= _now_ms():
        _delete_session_locked(session_id)
        raise HttpError(404, "会话已结束")
    return sess


def _session_bytes_locked(sess):
    total = 0
    for item in sess.get("files") or []:
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
            if not sess or sess.get("closed"):
                continue
            if int(sess.get("expiresAt") or 0) <= now:
                continue
            sessions += 1
            items = sess.get("files") or []
            files += len(items)
            total += _session_bytes_locked(sess)
    return {"ok": True, "version": VERSION, "sessions": sessions,
            "files": files, "bytes": total}


def _disk_free():
    try:
        return shutil.disk_usage(ROOT).free
    except OSError:
        return 0


def _check_disk(need):
    if _disk_free() - max(0, int(need)) < DISK_RESERVE:
        raise HttpError(507, "服务器磁盘空间不足，请稍后再试或先关闭其它互联会话")


def cleanup_once():
    """清理过期/已关闭会话与其文件、超 TTL 的孤儿分片；每 60s 由后台线程调用。"""
    now = _now_ms()
    removed = 0
    with _LOCK:
        index = _load_index()
        for sid_hash, session_id in list(index.items()):
            sess = _load_session(session_id)
            if sess is None:
                index.pop(sid_hash, None)
                continue
            if (sess.get("closed")
                    or int(sess.get("expiresAt") or 0) <= now):
                _delete_session_locked(session_id)
                index.pop(sid_hash, None)
                removed += 1
                log("session cleanup session=%s" % session_id)
        _save_index(index)
    # 孤儿分片：会话已不存在或创建超过 TTL
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
                stale = (time.time() - os.path.getmtime(path)) > TTL_SEC
            except OSError:
                stale = True
        else:
            created = int(meta.get("createdAt") or 0)
            session_id = meta.get("sessionId")
            if not session_id or _load_session(session_id) is None:
                stale = True
            elif created and (now - created) > TTL_SEC * 1000:
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
            self._body_read = True
            self.close_connection = True
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
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "方法不支持")
                return self._route_file(path[len("/file/"):], query)

            if path == "/open":
                if method != "POST":
                    raise HttpError(405, "方法不支持")
                return self._route_open()
            if path == "/mine":
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, "方法不支持")
                return self._route_mine()
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
            events = [dict(ev) for ev in (sess.get("events") or [])
                      if int(ev.get("seq") or 0) > since]
            cursor = int(events[-1]["seq"]) if events else since
            payload = {
                "ok": True,
                "session": {"id": sess["id"], "code": sess["code"],
                            "expiresAt": int(sess["expiresAt"]),
                            "closed": bool(sess.get("closed"))},
                "events": events,
                "cursor": cursor,
            }
        self._send_json(200, payload)

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
        if size > MAX_FILE_BYTES:
            raise HttpError(413, "文件超过单文件上限（%d MiB）"
                            % (MAX_FILE_BYTES // (1024 * 1024)))
        try:
            total_chunks = int(body.get("totalChunks"))
        except (TypeError, ValueError):
            raise HttpError(400, "分片数非法")
        if total_chunks < 1 or total_chunks > MAX_TOTAL_CHUNKS:
            raise HttpError(400, "分片数非法")
        mime = _safe_mime(body.get("mime") or "")
        with _LOCK:
            sess = _sess_owned_locked(auth, session_id)
            if len(sess.get("files") or []) >= MAX_FILES:
                raise HttpError(413, "该会话文件数已达上限（%d 个）" % MAX_FILES)
            if _session_bytes_locked(sess) + size > MAX_SESSION_BYTES:
                raise HttpError(413, "该会话文件总量已达上限（%d MiB）"
                                % (MAX_SESSION_BYTES // (1024 * 1024)))
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
            data = self._read_body(CHUNK_BODY_MAX)
            part_path = os.path.join(_upload_dir(upload_id), "%d.part" % index)
            tmp = part_path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            os.replace(tmp, part_path)
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
                if _session_bytes_locked(sess) + actual > MAX_SESSION_BYTES:
                    raise HttpError(413, "该会话文件总量已达上限（%d MiB）"
                                    % (MAX_SESSION_BYTES // (1024 * 1024)))
            file_id = secrets.token_hex(8)
            final_path = os.path.join(FILES_DIR, sess["id"], file_id + ".bin")
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            part_tmp = final_path + ".part"
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
            if file_id and final_path:
                try:
                    os.remove(final_path)
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
        path = os.path.join(FILES_DIR, session_id, file_id + ".bin")
        try:
            size = os.path.getsize(path)
        except OSError:
            raise HttpError(404, "文件不存在")
        inline = str(_query_one(query, "inline", "0")).lower() in ("1", "true", "yes")
        self._serve_file(path, record, size, inline)

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
    log("start v%s root=%s port=%d ttl=%ss max_file=%dMiB max_session=%dMiB "
        "whoami_key=%s" % (
            VERSION, ROOT, PORT, TTL_SEC, MAX_FILE_BYTES // (1024 * 1024),
            MAX_SESSION_BYTES // (1024 * 1024),
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
