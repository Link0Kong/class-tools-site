# -*- coding: utf-8 -*-
"""agent.py — PPT 转换机（本机 Windows + PowerPoint COM + ffmpeg + OSS）

契约唯一真源：``web/ppt/CONTRACT.md``（§3/§4/§6）。一轮流程：

    心跳 → 取 status=queued（created_at asc, limit 1）→ 认领 processing/progress=3
    → 拉分片拼源文件（≤64MiB，.ppt/.pptx）→ 上传原件 ppt/src/<deckId>/source.<ext>
    → 删分片 → convert.convert_deck() 渲染/转码 → 上传资产 ppt/a/<deckId>/<buildId>/
    → PATCH ready + manifest/cover；任何异常 → PATCH failed + 中文 error（≤300 字）

用法::

    python agent.py --once                 # 跑一轮（计划任务每 1 分钟调用）
    python agent.py --once --dry-run       # 只打印：不认领/不写云端/不上传 OSS
    python agent.py --deck <deckId>        # 调试单个 deck（真实链路）
    python agent.py --deck <deckId> --dry-run
    python agent.py --scheduled            # ≡ --once

身份：管理员 token 读 ``C:\\briefdesk\\secrets\\class-token.json``；
过期提前 1h 用 ``rpc/class_verify``（PUBLISHABLE KEY）刷新并写回；
管理员 sid/name 读 ``C:\\briefdesk\\secrets\\cloudbaserc.local.json`` 的
``functions[].envVariables.CLASS_ADMIN_SID/CLASS_ADMIN_NAME``。
**日志/输出绝不打印 token、AK/SK。**

运维：日志 ``web/ppt/logs/agent-YYYYMMDD.log``；暂停开关 ``web/ppt/ppt-agent.pause``；
单实例锁 ``web/ppt/logs/agent.lock``；心跳行 ``public.site_assets.id='ppt_agent'``。
"""
import argparse
import base64
import json
import os
import re
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import convert  # noqa: E402
import oss_upload  # noqa: E402

# ---------------------------------------------------------------------------
# 常量 / 路径
# ---------------------------------------------------------------------------
WEB_ROOT = os.path.abspath(os.path.join(HERE, ".."))
WORKSPACE = os.path.abspath(os.path.join(WEB_ROOT, ".."))

CFG_BASE = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
PUBLISH_KEY_FILE = os.path.join(WEB_ROOT, "deploy", "cloudbase", "publish_key.txt")
TOKEN_FILE = r"C:\briefdesk\secrets\class-token.json"
CLOUDBASE_RC = r"C:\briefdesk\secrets\cloudbaserc.local.json"

# 管理员身份兜底（与 diag_agent.py 一致；非密钥）
FALLBACK_ADMIN_SID = "3260707024"
FALLBACK_ADMIN_NAME = "陈子麒"

LOG_DIR = os.path.join(HERE, "logs")
WORK_DIR = os.path.join(HERE, "work")
LOCK_FILE = os.path.join(LOG_DIR, "agent.lock")
PAUSE_FILE = os.path.join(HERE, "ppt-agent.pause")

AGENT_ID = "ppt_agent"
AGENT_VERSION = "1.0"
UA = "class-ppt-agent/1.0"
HTTP_TIMEOUT = 60.0
MAX_SOURCE_BYTES = 64 * 1024 * 1024          # 契约 §6：≤64MiB
CHUNK_PAGE_LIMIT = 8                          # 分片 GET 每页 8 片（约 5.5MB/响应，稳）
HEARTBEAT_INTERVAL = 30.0
LOG_KEEP_DAYS = 14
WORK_KEEP_HOURS = 24
PROGRESS_MIN_DELTA = 2
PROGRESS_MIN_INTERVAL = 6.0
CLOUD_RETRIES = 2

LOCAL_TZ = timezone(timedelta(hours=8))

EXIT_OK = 0
EXIT_CONFIG = 1


# ---------------------------------------------------------------------------
# 日志 / 脱敏
# ---------------------------------------------------------------------------
_RE_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}")
_RE_DEVICE = re.compile(r"(?i)(x-device-id:\s*)[A-Za-z0-9._\-]{8,}")
_RE_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{48,}\b")


def sanitize(text, limit=300):
    """脱敏 + 截断（日志/云端 error 共用；绝不包含 token）。"""
    s = str(text or "")
    s = _RE_BEARER.sub(r"\1***", s)
    s = _RE_DEVICE.sub(r"\1***", s)
    s = _RE_LONG_TOKEN.sub("***", s)
    s = s.replace(TOKEN_FILE, "***")
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit - 1] + "…"
    return s


class Logger(object):
    """按天日志文件（UTF-8）。pythonw 下无控制台也能记录。"""

    def __init__(self, log_dir=LOG_DIR, echo=True):
        self.log_dir = log_dir
        self.echo = echo
        os.makedirs(log_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._cleanup_old()
        self.path = self._path()

    @staticmethod
    def _day():
        return datetime.now(LOCAL_TZ).strftime("%Y%m%d")

    def _path(self):
        return os.path.join(self.log_dir, "agent-%s.log" % self._day())

    def _cleanup_old(self):
        cutoff = time.time() - LOG_KEEP_DAYS * 86400
        try:
            for name in os.listdir(self.log_dir):
                if not (name.startswith("agent-") and name.endswith(".log")):
                    continue
                path = os.path.join(self.log_dir, name)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except OSError:
                    pass
        except OSError:
            pass

    def log(self, msg, level="I"):
        ts = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
        line = "%s [%s] %s" % (ts, level, sanitize(msg, limit=4000))
        with self._lock:
            path = self._path()
            if path != self.path:
                self.path = path
                self._cleanup_old()
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass
            if self.echo:
                try:
                    print(line, flush=True)
                except Exception:  # noqa: BLE001
                    pass

    def warn(self, msg):
        self.log(msg, "W")

    def error(self, msg):
        self.log(msg, "E")

    def __call__(self, msg, level="I"):
        self.log(msg, level)


# ---------------------------------------------------------------------------
# CloudBase PostgREST（管理员 token；绝不打印 token/key）
# ---------------------------------------------------------------------------
class CloudError(Exception):
    pass


def _read_publish_key():
    try:
        with open(PUBLISH_KEY_FILE, encoding="utf-8") as fh:
            key = fh.read().strip()
    except OSError as exc:
        raise CloudError("缺少 publishable key 文件：%s" % exc.__class__.__name__)
    if not key:
        raise CloudError("publishable key 为空")
    return key


def _read_admin_identity():
    """管理员 sid/name：优先 cloudbaserc.local.json 的 functions[].envVariables。"""
    try:
        with open(CLOUDBASE_RC, encoding="utf-8") as fh:
            doc = json.load(fh)
        for fn in doc.get("functions") or []:
            env = (fn or {}).get("envVariables") or {}
            sid = str(env.get("CLASS_ADMIN_SID") or "").strip()
            name = str(env.get("CLASS_ADMIN_NAME") or "").strip()
            if sid and name:
                return sid, name
    except (OSError, ValueError, TypeError):
        pass
    return FALLBACK_ADMIN_SID, FALLBACK_ADMIN_NAME


class Cloud(object):
    """CloudBase PostgREST 客户端：管理员 token 自动缓存/刷新（401/403 强刷一次）。"""

    def __init__(self, base=None, key=None, log=None, dry_run=False):
        self.base = base or CFG_BASE
        self.key = key or _read_publish_key()
        self.token = ""
        self.admin_sid, self.admin_name = _read_admin_identity()
        self.log = log or (lambda msg, **kw: None)
        self.dry_run = bool(dry_run)
        self._lock = threading.Lock()

    # -- 原始请求 ----------------------------------------------------------
    def raw(self, path, body=None, method="GET", token="", prefer=None,
            timeout=HTTP_TIMEOUT):
        headers = {"Authorization": "Bearer " + self.key,
                   "Accept": "application/json",
                   "User-Agent": UA}
        if token:
            headers["X-Device-Id"] = token
        if prefer:
            headers["Prefer"] = prefer
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return int(resp.status), (json.loads(raw) if raw.strip() else None)
        except urllib.error.HTTPError as exc:
            try:
                text = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                text = ""
            return int(exc.code), sanitize(text, 300)
        except Exception as exc:  # noqa: BLE001
            return 0, sanitize("%s: %s" % (exc.__class__.__name__, exc), 200)

    # -- token -------------------------------------------------------------
    def ensure_token(self, force=False):
        if self.token and not force:
            return self.token
        if not force:
            try:
                with open(TOKEN_FILE, encoding="utf-8") as fh:
                    obj = json.load(fh)
                token = str(obj.get("token") or "").strip()
                exp = float(obj.get("exp") or 0)
                if token and exp > time.time() + 3600:
                    self.token = token
                    return token
            except (OSError, ValueError, TypeError):
                pass
        status, out = self.raw("rpc/class_verify",
                               {"p_sid": self.admin_sid, "p_name": self.admin_name},
                               "POST")
        if status != 200 or not isinstance(out, dict) or not out.get("token"):
            raise CloudError("管理员 token 刷新失败（class_verify HTTP %s）" % status)
        self.token = str(out["token"])
        try:
            os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
            payload = {"token": self.token, "exp": time.time() + 86400 * 25}
            try:
                with open(TOKEN_FILE, encoding="utf-8") as fh:
                    old = json.load(fh)
                if isinstance(old, dict):
                    old.update(payload)
                    payload = old
            except (OSError, ValueError, TypeError):
                pass
            with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
        except OSError:
            pass
        self.log("cloud: 管理员 token 已刷新（值不落日志）")
        return self.token

    # -- 管理员请求（401/403 自动刷新一次；瞬时错误重试） -------------------
    def admin(self, path, body=None, method="GET", prefer=None, timeout=HTTP_TIMEOUT,
              retries=CLOUD_RETRIES):
        with self._lock:
            token = self.ensure_token()
            attempt = 0
            while True:
                status, data = self.raw(path, body, method, token, prefer, timeout)
                if status in (401, 403):
                    self.log("cloud: 管理员 token 被拒（HTTP %s）→ 强刷重试" % status)
                    token = self.ensure_token(force=True)
                    status, data = self.raw(path, body, method, token, prefer, timeout)
                transient = status in (0, 429) or (isinstance(status, int) and 500 <= status < 600)
                if transient and attempt < retries:
                    attempt += 1
                    wait = 1.2 * (2 ** (attempt - 1))
                    self.log("cloud: HTTP %s，%.1fs 后重试（%d/%d）%s"
                             % (status, wait, attempt, retries, sanitize(data, 120)))
                    time.sleep(wait)
                    continue
                return status, data

    # -- 便捷封装 ----------------------------------------------------------
    def get(self, path, timeout=HTTP_TIMEOUT):
        return self.admin(path, None, "GET", timeout=timeout)

    def patch(self, path, body, prefer="return=representation"):
        return self.admin(path, body, "PATCH", prefer=prefer)

    def delete(self, path):
        return self.admin(path, None, "DELETE")

    def upsert(self, table, rows, on_conflict="id"):
        body = rows if isinstance(rows, list) else [rows]
        return self.admin(table + "?on_conflict=" + on_conflict, body, "POST",
                          prefer="resolution=merge-duplicates,return=minimal")


# ---------------------------------------------------------------------------
# 心跳
# ---------------------------------------------------------------------------
def get_queued_count(cloud, log):
    status, rows = cloud.get("ppt_decks?select=id&deleted=eq.false&status=eq.queued&limit=500")
    if status == 200 and isinstance(rows, list):
        return len(rows)
    log("WARN 统计排队数失败：HTTP %s" % status)
    return 0


def send_heartbeat(cloud, log, host, queued=0):
    body = {
        "id": AGENT_ID,
        "body": {
            "online": True,
            "seen_at": int(time.time() * 1000),
            "queued": int(queued),
            "version": AGENT_VERSION,
            "host": host,
        },
    }
    status, data = cloud.upsert("site_assets", body)
    ok = status in (200, 201, 204)
    if not ok:
        log("WARN 心跳写入失败：HTTP %s %s" % (status, sanitize(data, 160)))
    return ok


class HeartbeatThread(threading.Thread):
    """长任务期间每 30s 心跳（online/seen_at/queued/version/host）。"""

    def __init__(self, cloud, log, host):
        super(HeartbeatThread, self).__init__(name="ppt-heartbeat", daemon=True)
        self.cloud = cloud
        self.log = log
        self.host = host
        self._stop = threading.Event()
        self.queued = 0

    def run(self):
        while not self._stop.wait(HEARTBEAT_INTERVAL):
            try:
                send_heartbeat(self.cloud, self.log, self.host, self.queued)
            except Exception as exc:  # noqa: BLE001
                self.log("WARN 心跳线程异常：%s" % sanitize(exc, 160))

    def stop(self):
        self._stop.set()


# ---------------------------------------------------------------------------
# 单实例锁 / 暂停
# ---------------------------------------------------------------------------
def acquire_lock():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = open(LOCK_FILE, "a+")
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        try:
            fh.close()
        except OSError:
            pass
        return None


def release_lock(fh):
    if fh is None:
        return
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        fh.close()
    except OSError:
        pass


def is_paused():
    return os.path.exists(PAUSE_FILE)


# ---------------------------------------------------------------------------
# 工作目录
# ---------------------------------------------------------------------------
def cleanup_stale_work(log):
    if not os.path.isdir(WORK_DIR):
        return
    cutoff = time.time() - WORK_KEEP_HOURS * 3600
    try:
        for name in os.listdir(WORK_DIR):
            path = os.path.join(WORK_DIR, name)
            try:
                if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                    import shutil
                    shutil.rmtree(path, ignore_errors=True)
                    log("清理陈旧工作目录：%s" % name)
            except OSError:
                pass
    except OSError:
        pass


def new_work_dir(deck_id, log):
    os.makedirs(WORK_DIR, exist_ok=True)
    cleanup_stale_work(log)
    path = os.path.join(WORK_DIR, "%s-%d" % (re.sub(r"[^A-Za-z0-9_-]", "_", deck_id),
                                             int(time.time())))
    os.makedirs(path, exist_ok=True)
    return path


def cleanup_work_dir(path, log):
    if not path:
        return
    try:
        import shutil
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 分片
# ---------------------------------------------------------------------------
def fetch_chunks(cloud, deck_id, chunk_count, log):
    """按 idx 升序分页拉取全部分片并 base64 解码拼装为 bytes。"""
    out = {}
    offset = 0
    while True:
        limit = CHUNK_PAGE_LIMIT
        path = ("ppt_upload_chunks?deck_id=eq.%s&select=idx,data&order=idx.asc&limit=%d&offset=%d"
                % (_q(deck_id), limit, offset))
        status, rows = cloud.get(path)
        if status != 200 or not isinstance(rows, list):
            raise CloudError("读取分片失败（HTTP %s）" % status)
        if not rows:
            break
        for row in rows:
            try:
                idx = int(row.get("idx"))
                data = base64.b64decode(str(row.get("data") or ""))
            except (TypeError, ValueError, KeyError) as exc:
                raise CloudError("分片数据损坏（idx=%s）：%s"
                                 % (row.get("idx"), exc.__class__.__name__))
            out[idx] = data
        offset += len(rows)
        if chunk_count and offset >= chunk_count:
            break
        if not chunk_count and len(rows) < limit:
            break
    if chunk_count:
        missing = [i for i in range(int(chunk_count)) if i not in out]
        if missing:
            raise CloudError("上传中断：云端分片不完整（缺 %d 片，如 idx=%s），请重新上传"
                             % (len(missing), missing[:5]))
    if not out:
        raise CloudError("没有找到上传分片")
    data = b"".join(out[i] for i in sorted(out))
    return data


def delete_chunks(cloud, deck_id, log, warn=True):
    status, _ = cloud.delete("ppt_upload_chunks?deck_id=eq.%s" % _q(deck_id))
    if status not in (200, 204):
        if warn:
            log("WARN 删除分片失败：HTTP %s（不阻塞）" % status)
        return False
    return True


def _q(value):
    """PostgREST 过滤值转义（deck_id 是 base36 字母数字，安全兜底）。"""
    return urllib.request.quote(str(value), safe=":")


# ---------------------------------------------------------------------------
# 转换 / 上传
# ---------------------------------------------------------------------------
def source_ext_from_name(source_name, log):
    ext = os.path.splitext(str(source_name or ""))[1].lower()
    if ext in (".ppt", ".pptx"):
        return ext
    if not ext:
        log("WARN 源文件无扩展名，按 .pptx 处理")
        return ".pptx"
    raise convert.ConvertError("仅支持 .ppt/.pptx（收到 %s）" % ext)


def upload_source(cloud, uploader, deck_id, src_path, ext, log, dry_run=False):
    key = "ppt/src/%s/source%s" % (deck_id, ext)
    if dry_run:
        log("[dry-run] 跳过原件上传：%s" % key)
        return {"key": key, "url": oss_upload.OSS_BASE + key}
    return uploader.put_file(key, src_path,
                             content_type=oss_upload.content_type_for("source" + ext))


def upload_assets(uploader, deck_id, build_id, assets, log, progress=None,
                  dry_run=False):
    """上传转换资产（先图片后媒体，key 带 buildId 目录）；返回 key 列表。"""
    prefix = "ppt/a/%s/%s/" % (deck_id, build_id)
    uploaded = []
    total = max(1, len(assets))
    for i, asset in enumerate(assets):
        key = prefix + asset["name"]
        if dry_run:
            log("[dry-run] 跳过资产上传：%s (%d bytes)" % (key, asset.get("size") or 0))
        else:
            uploader.put_file(key, asset["path"],
                              content_type=asset.get("content_type"))
        uploaded.append(key)
        if progress:
            progress(90 + int(8.0 * (i + 1) / total), "上传资产 %d/%d" % (i + 1, total))
    return uploaded


def format_error(exc, elapsed=None):
    """异常 → 云端 error 中文短句（≤300 字，脱敏）。"""
    if isinstance(exc, convert.ConvertTimeout):
        text = "转换超时（超过 15 分钟）"
    elif isinstance(exc, convert.ConvertBusyError):
        text = "PowerPoint 正被占用（用户正在编辑），稍后自动重试"
    elif isinstance(exc, convert.ConvertError):
        text = str(exc) or "转换失败"
    elif isinstance(exc, CloudError):
        text = "云端错误：%s" % exc
    else:
        text = "转换失败（%s）" % exc.__class__.__name__
    return sanitize(text, 300)


# ---------------------------------------------------------------------------
# 单个 deck 处理
# ---------------------------------------------------------------------------
class DeckJob(object):
    def __init__(self, cloud, uploader, log, host, dry_run=False, queued_hint=0):
        self.cloud = cloud
        self.uploader = uploader
        self.log = log
        self.host = host
        self.dry_run = bool(dry_run)
        self.queued_hint = int(queued_hint or 0)
        self._last_progress = {"pct": -100, "ts": 0.0}

    # -- 云端小的辅助 ------------------------------------------------------
    def patch_progress(self, deck_id, pct, phase=""):
        pct = max(0, min(99, int(pct)))
        now = time.monotonic()
        if (pct - self._last_progress["pct"] < PROGRESS_MIN_DELTA
                and now - self._last_progress["ts"] < PROGRESS_MIN_INTERVAL):
            return
        if self.dry_run:
            return
        self._last_progress = {"pct": pct, "ts": now}
        status, data = self.cloud.patch(
            "ppt_decks?id=eq.%s" % _q(deck_id),
            {"progress": pct, "updated_at": int(time.time() * 1000)},
            prefer="return=minimal")
        if status not in (200, 204):
            self.log("WARN 进度 PATCH 失败：HTTP %s %s" % (status, sanitize(data, 120)))

    def patch_deck(self, deck_id, body, prefer="return=representation"):
        body = dict(body or {})
        body.setdefault("updated_at", int(time.time() * 1000))
        if self.dry_run:
            self.log("[dry-run] 跳过 PATCH：%s" % sanitize(json.dumps(body, ensure_ascii=False), 300))
            return 200, [{"id": deck_id}]
        return self.cloud.patch("ppt_decks?id=eq.%s" % _q(deck_id), body, prefer=prefer)

    # -- 主流程 ------------------------------------------------------------
    def run(self, deck):
        deck_id = str(deck.get("id"))
        t0 = time.monotonic()
        work_dir = None
        hb = None
        job = {"deck": deck_id, "title": deck.get("title") or "",
               "status": str(deck.get("status") or ""), "action": "skipped",
               "elapsed_s": 0.0, "error": ""}
        try:
            self.log("=== deck %s 开始（title=%r, status=%s, size=%s, chunks=%s）"
                     % (deck_id, job["title"][:40], job["status"],
                        deck.get("source_size"), deck.get("chunk_count")))
            # 1) 拼装源文件
            self.patch_progress(deck_id, 4, "拉取分片")
            chunk_count = int(deck.get("chunk_count") or 0)
            source_size = int(deck.get("source_size") or 0)
            t_fetch = time.monotonic()
            source_bytes = fetch_chunks(self.cloud, deck_id, chunk_count, self.log)
            self.log("分片拼装完成：%d 片 / %d bytes（%.1fs）"
                     % (chunk_count or 0, len(source_bytes), time.monotonic() - t_fetch))
            if len(source_bytes) > MAX_SOURCE_BYTES:
                raise convert.ConvertError("源文件过大（%dMB，上限 64MB）"
                                           % (len(source_bytes) // (1024 * 1024)))
            if source_size and len(source_bytes) != source_size:
                raise convert.ConvertError("源文件大小不一致（云端 %d / 实际 %d）"
                                           % (source_size, len(source_bytes)))
            ext = source_ext_from_name(deck.get("source_name"), self.log)
            work_dir = new_work_dir(deck_id, self.log)
            src_path = os.path.join(work_dir, "source" + ext)
            with open(src_path, "wb") as fh:
                fh.write(source_bytes)
            del source_bytes

            # 2) 上传原件 → 删分片（契约 §6 顺序）
            self.patch_progress(deck_id, 6, "上传原件")
            try:
                up = upload_source(self.cloud, self.uploader, deck_id, src_path, ext,
                                   self.log, dry_run=self.dry_run)
                source_key = up.get("key") or ""
                if not self.dry_run and source_key:
                    self.patch_deck(deck_id, {"source_key": source_key},
                                    prefer="return=minimal")
            except Exception as exc:  # noqa: BLE001
                raise convert.ConvertError("原件上传失败：%s" % sanitize(exc, 120))
            if not self.dry_run:
                delete_chunks(self.cloud, deck_id, self.log, warn=True)

            # 3) 长任务心跳线程
            if not self.dry_run:
                hb = HeartbeatThread(self.cloud, self.log, self.host)
                hb.queued = max(0, int(self.queued_hint or 0))
                hb.start()

            # 4) 转换
            self.patch_progress(deck_id, 8, "转换中")
            copy_path = os.path.join(work_dir, "input" + ext)
            try:
                import shutil
                shutil.copyfile(src_path, copy_path)
            except OSError:
                copy_path = src_path
            opts = {
                "deck_id": deck_id,
                "converter": self.host,
                "timeout_s": 900.0,
                "log": lambda msg: self.log("[convert] " + str(msg)),
                "progress": lambda pct, phase="": self.patch_progress(
                    deck_id, 8 + int(72.0 * max(0, min(100, pct)) / 100.0), phase),
            }
            result = convert.convert_deck(copy_path, work_dir, opts)
            stats = result["stats"]
            self.log("转换完成：%d 页 / %d 步 / %d 图片 / %d 媒体，耗时 %.1fs，build=%s"
                     % (stats["slides"], stats["steps"], stats["images"],
                        stats["media"], stats["elapsed_s"], result["build_id"]))
            for warning in result.get("warnings") or []:
                self.log("convert warn: %s" % warning)

            # 5) 上传资产（先传资产再 PATCH ready，避免半成品可播）
            self.patch_progress(deck_id, 90, "上传资产")
            keys = upload_assets(self.uploader, deck_id, result["build_id"],
                                 result["assets"], self.log,
                                 progress=lambda p, ph="": self.patch_progress(deck_id, p, ph),
                                 dry_run=self.dry_run)
            if self.dry_run:
                self.log("[dry-run] 资产 %d 个（未上传）；manifest: %s"
                         % (len(keys), sanitize(json.dumps(result["manifest"],
                                                          ensure_ascii=False), 600)))
                job["action"] = "dry-run"
                job["elapsed_s"] = round(time.monotonic() - t0, 2)
                return job

            # 6) PATCH ready
            manifest = result["manifest"]
            body = {
                "status": "ready",
                "progress": 100,
                "error": "",
                "manifest": manifest,
                "slide_count": int(result["slide_count"]),
                "step_count": int(result["step_count"]),
                "aspect": result["aspect"],
                "cover_url": manifest["base"] + (result.get("cover") or ""),
                "source_key": source_key,
                "converter": self.host,
                "converted_at": int(time.time() * 1000),
            }
            status, data = self.patch_deck(deck_id, body)
            if status not in (200, 204, 201):
                raise CloudError("PATCH ready 失败（HTTP %s）" % status)
            self.log("PATCH ready 成功：%s（%d 页 / %d 步 / %d 资产）"
                     % (deck_id, result["slide_count"], result["step_count"],
                        len(result["assets"])))
            job["action"] = "converted"
            job["elapsed_s"] = round(time.monotonic() - t0, 2)
            return job
        except convert.ConvertBusyError as exc:
            # PowerPoint 被占用：退回 queued（保持排队），下一轮再试
            self.log("跳过转换（PowerPoint busy）：%s" % exc)
            self.patch_deck(deck_id, {"status": "queued", "progress": 0, "error": ""},
                            prefer="return=minimal")
            job["action"] = "busy"
            job["error"] = sanitize(exc, 200)
            return job
        except Exception as exc:  # noqa: BLE001
            err = format_error(exc)
            self.log("ERROR deck %s 转换失败：%s" % (deck_id, err))
            self.log(traceback.format_exc()[-2500:])
            try:
                self.patch_deck(deck_id, {"status": "failed", "error": err,
                                          "progress": 0}, prefer="return=minimal")
            except Exception as exc2:  # noqa: BLE001
                self.log("ERROR PATCH failed 也失败：%s" % sanitize(exc2, 200))
            job["action"] = "failed"
            job["error"] = err
            return job
        finally:
            if not self.dry_run:
                try:
                    delete_chunks(self.cloud, deck_id, self.log, warn=False)
                except Exception:  # noqa: BLE001
                    pass
            if hb is not None:
                hb.stop()
                try:
                    send_heartbeat(self.cloud, self.log, self.host,
                                   hb.queued if hb else 0)
                except Exception:  # noqa: BLE001
                    pass
            if not self.dry_run:
                cleanup_work_dir(work_dir, self.log)
            else:
                self.log("[dry-run] 工作目录保留：%s" % work_dir)
            job["elapsed_s"] = job.get("elapsed_s") or round(time.monotonic() - t0, 2)


# ---------------------------------------------------------------------------
# 一轮
# ---------------------------------------------------------------------------
def find_deck_by_id(cloud, deck_id, log):
    status, rows = cloud.get(
        "ppt_decks?select=id,title,status,source_name,source_size,chunk_count,"
        "owner_sid,progress,deleted&id=eq.%s" % _q(deck_id))
    if status != 200 or not isinstance(rows, list):
        raise CloudError("查询 deck 失败（HTTP %s）" % status)
    if not rows:
        return None
    return rows[0]


def claim_deck(cloud, deck_id, host, log):
    """PATCH processing；返回 True 表示认领成功。"""
    body = {"status": "processing", "progress": 3, "error": "",
            "converter": host, "updated_at": int(time.time() * 1000)}
    status, rows = cloud.patch(
        "ppt_decks?id=eq.%s&status=eq.queued" % _q(deck_id), body,
        prefer="return=representation")
    if status not in (200, 201):
        log("WARN 认领失败：HTTP %s" % status)
        return False
    if isinstance(rows, list) and rows:
        return True
    # return=representation 但空数组 → 已被别人认领
    return False


def force_status_processing(cloud, deck_id, host, log):
    body = {"status": "processing", "progress": 3, "error": "",
            "converter": host, "updated_at": int(time.time() * 1000)}
    status, rows = cloud.patch("ppt_decks?id=eq.%s" % _q(deck_id), body,
                               prefer="return=minimal")
    if status not in (200, 204):
        raise CloudError("设置 processing 失败（HTTP %s）" % status)
    return True


def run_once(cloud, uploader, log, host, deck_id=None, dry_run=False):
    """跑一轮；返回 summary dict。"""
    t0 = time.monotonic()
    summary = {"action": "none", "deck": "", "queued": 0, "busy": False,
               "elapsed_s": 0.0, "dry_run": bool(dry_run)}
    queued = get_queued_count(cloud, log) if not dry_run else 0
    summary["queued"] = queued
    if not dry_run:
        try:
            send_heartbeat(cloud, log, host, queued)
        except Exception as exc:  # noqa: BLE001
            log("WARN 心跳失败：%s" % sanitize(exc, 160))

    # deck 选择
    if deck_id:
        deck = find_deck_by_id(cloud, deck_id, log)
        if deck is None:
            raise CloudError("deck 不存在：%s" % deck_id)
        if deck.get("deleted"):
            raise CloudError("deck 已删除：%s" % deck_id)
        if str(deck.get("status")) == "ready" and not dry_run:
            log("deck %s 已经是 ready；如需重转，先把 status PATCH 回 queued" % deck_id)
            summary["action"] = "ready-skip"
            summary["deck"] = deck_id
            summary["elapsed_s"] = round(time.monotonic() - t0, 2)
            return summary
        if str(deck.get("status")) == "uploading" and not dry_run:
            raise CloudError("deck 仍在 uploading（分片未提交），不能转换")
    else:
        status, rows = cloud.get(
            "ppt_decks?select=id,title,status,source_name,source_size,chunk_count,"
            "owner_sid,progress&deleted=eq.false&status=eq.queued"
            "&order=created_at.asc&limit=1")
        if status != 200 or not isinstance(rows, list):
            raise CloudError("查询排队队列失败（HTTP %s）" % status)
        if not rows:
            log("本轮无 queued 任务（queued=%d）" % queued)
            summary["elapsed_s"] = round(time.monotonic() - t0, 2)
            return summary
        deck = rows[0]

    # PowerPoint 忙检测（在认领之前 → 忙则 deck 保持 queued）
    busy, reason = convert.powerpoint_busy()
    if busy:
        log("[skip] PowerPoint busy：%s（deck 保持 queued）" % reason)
        summary["busy"] = True
        summary["action"] = "busy"
        summary["deck"] = str(deck.get("id"))
        summary["elapsed_s"] = round(time.monotonic() - t0, 2)
        return summary

    deck_id = str(deck.get("id"))
    summary["deck"] = deck_id
    log("认领 deck：%s（title=%r）" % (deck_id, (deck.get("title") or "")[:50]))
    if dry_run:
        log("[dry-run] 不认领、不写云端；本地转换后打印 manifest 摘要")
    else:
        if str(deck.get("status")) == "queued":
            if not claim_deck(cloud, deck_id, host, log):
                log("WARN 认领未成功（可能被抢占），本轮跳过")
                summary["action"] = "claim-lost"
                summary["elapsed_s"] = round(time.monotonic() - t0, 2)
                return summary
        else:
            force_status_processing(cloud, deck_id, host, log)

    job = DeckJob(cloud, uploader, log, host, dry_run=dry_run,
                  queued_hint=max(0, queued - 1))
    result = job.run(deck)
    summary.update(result)
    summary["elapsed_s"] = round(time.monotonic() - t0, 2)
    if not dry_run:
        try:
            send_heartbeat(cloud, log, host, get_queued_count(cloud, log))
        except Exception as exc:  # noqa: BLE001
            log("WARN 收尾心跳失败：%s" % sanitize(exc, 160))
    return summary


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="PPT 转换机（本机）")
    parser.add_argument("--once", action="store_true", help="跑一轮（计划任务用）")
    parser.add_argument("--scheduled", action="store_true", help="≡ --once")
    parser.add_argument("--deck", default="", help="调试指定 deck id")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印：不认领/不写云端/不上传 OSS")
    parser.add_argument("--verbose", action="store_true", help="同时打印到控制台")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not (args.once or args.scheduled or args.deck or args.dry_run):
        print("用法：python agent.py --once | --deck <id> | --dry-run（可组合）")
        return EXIT_CONFIG
    log = Logger(echo=bool(sys.stdout))
    lock = None
    try:
        if is_paused():
            log.log("[pause] 检测到 %s，本轮跳过" % os.path.basename(PAUSE_FILE))
            return EXIT_OK
        lock = acquire_lock()
        if lock is None:
            log.log("[skip] 已有转换轮次在跑（单实例锁），本轮跳过")
            return EXIT_OK
        host = socket.gethostname()
        log.log("round start：args=%s host=%s version=%s%s"
                % (sanitize(vars(args), 300), host, AGENT_VERSION,
                   " [dry-run]" if args.dry_run else ""))
        try:
            cloud = Cloud(log=log.log, dry_run=args.dry_run)
            uploader = oss_upload.OssUploader(log=log.log)
            summary = run_once(cloud, uploader, log, host,
                               deck_id=(args.deck or None), dry_run=args.dry_run)
        except CloudError as exc:
            log.error("云端/配置错误：%s" % sanitize(exc, 300))
            return EXIT_CONFIG
        except Exception as exc:  # noqa: BLE001
            log.error("未捕获异常：%s" % sanitize(exc, 300))
            log.error(traceback.format_exc()[-2500:])
            return EXIT_OK
        log.log("round done：action=%s deck=%s elapsed=%.1fs%s"
                % (summary.get("action"), summary.get("deck"),
                   summary.get("elapsed_s") or 0.0,
                   " error=" + summary.get("error") if summary.get("error") else ""))
        return EXIT_OK
    finally:
        release_lock(lock)


if __name__ == "__main__":
    sys.exit(main())
