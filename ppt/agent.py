# -*- coding: utf-8 -*-
"""agent.py — PPT 转换机（本机 Windows + PowerPoint COM + OSS）

契约唯一真源：``web/ppt/CONTRACT.md``（§3/§4/§6/§7/§11/§12）。

**v2.0 默认流程（compat）**：一轮流程：

    心跳 → 取 status=queued（created_at asc, limit 1）→ 认领 processing/progress=3
    → 拉分片拼源文件（≤64MiB，.ppt/.pptx）→ 上传原件 ppt/src/<deckId>/source.<ext>
    → 删分片 → convert.convert_compat()（compat.pptx 字体嵌入/规范化 + preview.pdf +
    cover.webp + original.<ext>，**不重编码媒体**）→ 上传资产（单对象重试 2 次）
    → PATCH ready + manifest v2（files/compat）；任何异常 → PATCH failed + 中文 error（≤300 字）

旧流程 `--legacy`（v1.2 分步图片 + 原样播放视频）保留，仅运维调试。

用法::

    python agent.py --once                 # 跑一轮（计划任务每 1 分钟调用；默认 compat）
    python agent.py --once --dry-run       # 只打印：不认领/不写云端/不上传 OSS
    python agent.py --deck <deckId>        # 调试单个 deck（默认 compat）
    python agent.py --deck <deckId> --dry-run
    python agent.py --deck <deckId> --compat-only           # 存量 ready deck 补兼容文件
    python agent.py --deck <deckId> --compat-only --dry-run # 本地演练（保留产物供核对），不写云端
    python agent.py --once --legacy        # 旧分步图/原样播放视频链路（运维调试）
    python agent.py --deck <deckId> --video-only            # v1.2 补 deck.mp4
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
import pptx_xml  # noqa: E402

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
VIDEO_ONLY_TIMEOUT_S = 1800.0                 # --video-only 单任务预算（契约 §11.2.2 30min）
COMPAT_TIMEOUT_S = 1800.0                     # v2.0 compat 单任务预算（契约 §12.3 ≥20min）
# v2.1 下载加速：ECS 本地缓存预热（http://121.196.47.2/pptfiles/__warm/ppt/...）
WARM_BASE = os.environ.get("PPT_WARM_BASE", "http://121.196.47.2").rstrip("/")
WARM_TIMEOUT_S = 3.0
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
                  dry_run=False, retries=0):
    """上传转换资产（key 带 buildId 目录）；返回 key 列表。

    ``retries``：单个对象失败后的重试次数（v2.0 compat 上传要求重试 2 次）。
    """
    prefix = "ppt/a/%s/%s/" % (deck_id, build_id)
    uploaded = []
    total = max(1, len(assets))
    for i, asset in enumerate(assets):
        key = prefix + asset["name"]
        if dry_run:
            log("[dry-run] 跳过资产上传：%s (%d bytes)" % (key, asset.get("size") or 0))
        else:
            _put_with_retry(uploader, key, asset, log, retries=retries)
        uploaded.append(key)
        if progress:
            progress(90 + int(8.0 * (i + 1) / total), "上传资产 %d/%d" % (i + 1, total))
    return uploaded


def _put_with_retry(uploader, key, asset, log, retries=2):
    """OSS 单对象上传 + 重试（``retries`` 次，指数退避 1s/2s）；最终失败抛中文错误。"""
    attempts = max(0, int(retries)) + 1
    last_exc = None
    for attempt in range(attempts):
        try:
            return uploader.put_file(key, asset["path"],
                                     content_type=asset.get("content_type"))
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts - 1:
                wait = 1.0 * (2 ** attempt)
                log("WARN OSS 上传失败（%s），%.1fs 后重试 %d/%d：%s"
                    % (os.path.basename(key), wait, attempt + 1, attempts - 1,
                       sanitize(exc, 120)))
                time.sleep(wait)
    raise convert.ConvertError("上传 %s 失败（已重试 %d 次）：%s"
                               % (os.path.basename(key), attempts - 1,
                                  sanitize(last_exc, 160)))


def upload_compat_assets(uploader, prefix, assets, log, retries=2):
    """把 v2.0 compat 资产上传到**指定前缀**（新 deck 的 build 目录 / 旧 deck 原 build 目录）。"""
    if not prefix.endswith("/"):
        prefix += "/"
    uploaded = []
    for i, asset in enumerate(assets):
        key = prefix + asset["name"]
        _put_with_retry(uploader, key, asset, log, retries=retries)
        uploaded.append(key)
        log("oss put %s/%d（%d bytes）" % (key, len(assets), asset.get("size") or 0))
    return uploaded


def warm_ppt_files(base_url, cache_prefix, names, log=None, opener=None,
                   timeout=WARM_TIMEOUT_S, force=True):
    """兼容文件上传后调用 ECS `/pptfiles/__warm/...` 预热（best-effort，失败只告警）。

    ``cache_prefix``：``ppt/a/<deckId>/<buildId>/``（manifest.base 相对 OSS 的路径前缀）；
    ``names``：要预热的文件名（compat.pptx / preview.pdf / original.* / cover.webp）；
    ``force``：默认 True → 带 ``?force=1`` 强制按 OSS HEAD 比对刷新（同一 build 重转后
    内容会变，必须强制刷新缓存，否则用户可能下载旧包）。
    返回 ``[{"name","url","ok","status"/"error"}...]``；**绝不抛异常**（不影响 PATCH ready）。
    """
    log = log or (lambda *_a, **_k: None)
    base = str(base_url or "").rstrip("/")
    prefix = str(cache_prefix or "").strip("/")
    if not base or not prefix:
        return []
    if opener is None:
        opener = urllib.request.urlopen
    results = []
    seen = set()
    for name in names or []:
        name = str(name or "").strip()
        if not name or name in seen or "/" in name or "\\" in name:
            continue
        seen.add(name)
        url = "%s/pptfiles/__warm/%s/%s" % (base, prefix, urllib.request.quote(name))
        if force:
            url += "?force=1"
        item = {"name": name, "url": url, "ok": False, "status": 0, "error": ""}
        try:
            with opener(url, timeout=float(timeout)) as resp:
                item["ok"] = int(getattr(resp, "status", 200) or 0) in (200, 202)
                item["status"] = int(getattr(resp, "status", 200) or 0)
                try:
                    resp.read(256)  # 小 JSON，避免连接悬挂
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            item["error"] = sanitize(exc, 120) or exc.__class__.__name__
        results.append(item)
    ok = sum(1 for item in results if item["ok"])
    if results:
        log("预热 ECS 缓存：%d/%d 已受理（base=%s）"
            % (ok, len(results), base))
    for item in results:
        if not item["ok"]:
            log("WARN 预热失败（best-effort，不影响 ready）：%s %s"
                % (item["name"], item["error"] or ("HTTP %s" % item["status"])))
    return results


def _split_cache_asset_names(assets):
    """资产拆成（build 根目录文件名, media/ 子目录文件名），供 ECS 预热用。"""
    root_names = []
    media_names = []
    for asset in assets or []:
        name = str(asset.get("name") or "").strip()
        if not name:
            continue
        if name.startswith("media/"):
            media_names.append(name[len("media/"):])
        else:
            root_names.append(name)
    return root_names, media_names


def warm_media_assets(base_url, cache_prefix, assets, log=None, force=True,
                      timeout=WARM_TIMEOUT_S, opener=None):
    """预热 media/ 子目录下的独立视频/音频（CONTRACT §12.8；best-effort）。"""
    _root, media_names = _split_cache_asset_names(assets)
    if not media_names:
        return []
    prefix = str(cache_prefix or "").rstrip("/") + "/media/"
    return warm_ppt_files(base_url, prefix, media_names, log=log, force=force,
                          timeout=timeout, opener=opener)


def format_error(exc, elapsed=None):
    """异常 → 云端 error 中文短句（≤300 字，脱敏）。"""
    if isinstance(exc, convert.ConvertTimeout):
        text = "转换超时（超过 30 分钟）"
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
    def __init__(self, cloud, uploader, log, host, dry_run=False, queued_hint=0,
                 mode="compat", source_name=""):
        self.cloud = cloud
        self.uploader = uploader
        self.log = log
        self.host = host
        self.dry_run = bool(dry_run)
        self.queued_hint = int(queued_hint or 0)
        self.mode = "legacy" if str(mode) == "legacy" else "compat"
        self.source_name = str(source_name or "")
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

    # -- v2.0 compat 默认流程（CONTRACT §12.3）------------------------------
    def _run_compat(self, deck_id, src_path, ext, source_key, work_dir, job, t0):
        """新 deck 默认流程：不降质兼容性处理 + 上传 compat/original/pdf/cover + ready。"""
        copy_path = os.path.join(work_dir, "input" + ext)
        try:
            import shutil
            shutil.copyfile(src_path, copy_path)
        except OSError:
            copy_path = src_path
        self.patch_progress(deck_id, 10, "下载源文件")
        opts = {
            "deck_id": deck_id,
            "title": job.get("title") or "",
            "source_name": self.source_name or os.path.basename(src_path),
            "converter": self.host,
            "timeout_s": COMPAT_TIMEOUT_S,
            "log": lambda msg: self.log("[compat] " + str(msg)),
            "progress": lambda pct, phase="": self.patch_progress(
                deck_id, max(10, min(95, int(pct))), phase),
        }
        t_conv = time.monotonic()
        result = convert.convert_compat(copy_path, work_dir, opts)
        stats = result["stats"]
        self.log("compat 完成：%d 页 / compat %.2fMB sha=%s / pdf %d 页 %.2fMB / "
                 "字体 %d / 外链媒体 %d / 耗时 %.1fs / build=%s"
                 % (stats["slides"], stats["compat_size"] / 1048576.0,
                    (stats.get("compat_sha256") or "")[:12], stats["pdf_pages"],
                    stats["pdf_size"] / 1048576.0, stats["fonts_embedded"],
                    stats["external_media"], time.monotonic() - t_conv,
                    result["build_id"]))
        for warning in result.get("warnings") or []:
            self.log("compat warn: %s" % warning)
        if self.dry_run:
            self.log("[dry-run] 资产 %d 个（未上传）；manifest: %s"
                     % (len(result["assets"]),
                        sanitize(json.dumps(result["manifest"], ensure_ascii=False), 600)))
            job["action"] = "dry-run"
            job["elapsed_s"] = round(time.monotonic() - t0, 2)
            return job
        self.patch_progress(deck_id, 85, "上传兼容文件")
        upload_assets(self.uploader, deck_id, result["build_id"], result["assets"],
                      self.log,
                      progress=lambda p, ph="": self.patch_progress(deck_id, p, ph),
                      dry_run=False, retries=2)
        # ECS 本地缓存预热（best-effort，小超时；失败不影响 ready）
        root_names, _media_names = _split_cache_asset_names(result["assets"])
        warm_ppt_files(WARM_BASE,
                       "ppt/a/%s/%s/" % (deck_id, result["build_id"]),
                       root_names, log=self.log, timeout=WARM_TIMEOUT_S)
        warm_media_assets(WARM_BASE,
                          "ppt/a/%s/%s/" % (deck_id, result["build_id"]),
                          result["assets"], log=self.log)
        self.patch_progress(deck_id, 95, "写入 ready")
        manifest = result["manifest"]
        cover = result.get("cover") or ""
        body = {
            "status": "ready",
            "progress": 100,
            "error": "",
            "manifest": manifest,
            "slide_count": int(result["slide_count"]),
            "step_count": int(result.get("step_count") or 0),
            "aspect": result["aspect"],
            "cover_url": (manifest["base"] + cover) if cover else "",
            "source_key": source_key or result.get("source_key") or "",
            "converter": self.host,
            "converted_at": int(time.time() * 1000),
        }
        status, data = self.patch_deck(deck_id, body)
        if status not in (200, 204, 201):
            raise CloudError("PATCH ready 失败（HTTP %s）" % status)
        self.log("PATCH ready 成功（compat）：%s（%d 页 / %d 文件 / compat %.2fMB / PDF %d 页）"
                 % (deck_id, result["slide_count"], len(result["assets"]),
                    stats["compat_size"] / 1048576.0, stats["pdf_pages"]))
        job["action"] = "converted"
        job["elapsed_s"] = round(time.monotonic() - t0, 2)
        return job

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

            # 4) 转换：v2.0 默认走 compat（--legacy 保留旧分步图片/视频流程）
            if self.mode == "compat":
                return self._run_compat(deck_id, src_path, ext, source_key,
                                        work_dir, job, t0)
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
                "timeout_s": 1800.0,  # 契约 §11.2.2：单 deck 30min 预算（含原样播放视频）
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
            if stats.get("video"):
                self.log("video: dur=%.2fs %dx%d audio=%s bytes=%d export=%.1fs "
                         "chapters=%d reencoded=%s"
                         % (stats.get("video_dur") or 0.0,
                            int((result.get("video") or {}).get("w") or 0),
                            int((result.get("video") or {}).get("h") or 0),
                            stats.get("video_audio") or "无",
                            int(stats.get("video_bytes") or 0),
                            float(stats.get("video_export_s") or 0.0),
                            int(stats.get("video_chapters") or 0),
                            bool(stats.get("video_reencoded"))))
            else:
                self.log("video: 未生成原样播放视频（%s）；分步模式照常 ready"
                         % (stats.get("video_skipped") or "无 video 输出"))

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
        "owner_sid,progress,deleted,manifest,source_key,slide_count,aspect,"
        "cover_url,converted_at&id=eq.%s" % _q(deck_id))
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


def run_once(cloud, uploader, log, host, deck_id=None, dry_run=False, legacy=False, heartbeat=True):
    """跑一轮；返回 summary dict。

    v2.0：默认走 **compat 兼容性处理**（不降质 + 多端下载）；``legacy=True`` 仅运维调试，
    保留旧「分步图片 + 原样播放视频」流程。
    """
    t0 = time.monotonic()
    summary = {"action": "none", "deck": "", "queued": 0, "busy": False,
               "elapsed_s": 0.0, "dry_run": bool(dry_run)}
    queued = get_queued_count(cloud, log) if not dry_run else 0
    summary["queued"] = queued
    if not dry_run and heartbeat:
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
                  queued_hint=max(0, queued - 1),
                  mode=("legacy" if legacy else "compat"),
                  source_name=str(deck.get("source_name") or ""))
    result = job.run(deck)
    summary.update(result)
    summary["elapsed_s"] = round(time.monotonic() - t0, 2)
    if not dry_run and heartbeat:
        try:
            send_heartbeat(cloud, log, host, get_queued_count(cloud, log))
        except Exception as exc:  # noqa: BLE001
            log("WARN 收尾心跳失败：%s" % sanitize(exc, 160))
    return summary


# ---------------------------------------------------------------------------
# --video-only：为已 ready 的 deck 只补「原样播放」视频（CONTRACT §11.2.3）
# ---------------------------------------------------------------------------
def _manifest_prefix(manifest, log):
    """从 manifest.base 反推 OSS 前缀（ppt/a/<deckId>/<buildId>/）。"""
    base = str((manifest or {}).get("base") or "")
    oss_base = oss_upload.OSS_BASE
    if not base.startswith(oss_base):
        raise CloudError("manifest.base 非法，无法确定视频上传目录（请重新转换该 deck）")
    prefix = base[len(oss_base):]
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix


def run_video_only(cloud, uploader, log, host, deck_id, dry_run=False):
    """只补视频：用 source_key 从 OSS 下载原件 → 导出视频 → 传进**原 build 目录** →
    只新增 ``manifest.video``（slides/img/media/notes 原样保留），不重传图片/媒体。"""
    t0 = time.monotonic()
    summary = {"action": "none", "deck": str(deck_id or ""), "elapsed_s": 0.0,
               "dry_run": bool(dry_run), "video_dur": 0.0, "video_bytes": 0,
               "export_s": 0.0, "skipped": "", "error": ""}
    deck = find_deck_by_id(cloud, deck_id, log)
    if deck is None:
        raise CloudError("deck 不存在：%s" % deck_id)
    if deck.get("deleted"):
        raise CloudError("deck 已删除：%s" % deck_id)
    status = str(deck.get("status") or "")
    if status != "ready":
        raise CloudError("只有 ready 的 deck 才能补视频（当前 status=%s）"
                         % (status or "空；如需转换请先 PATCH queued"))
    manifest = deck.get("manifest")
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("slides"), list)
            or not manifest["slides"]):
        raise CloudError("该 deck 的 manifest 为空/不完整，无法补视频（请重新上传转换）")
    if manifest.get("video"):
        log("deck %s 已有 manifest.video，本次将重新导出并覆盖（旧视频对象保留）" % deck_id)
    ext = source_ext_from_name(deck.get("source_name"), log)
    source_key = str(deck.get("source_key") or "")
    if not source_key:
        source_key = "ppt/src/%s/source%s" % (deck_id, ext)
        log("WARN 云端没有 source_key，按约定路径尝试：%s" % source_key)
    log("=== deck %s 补视频开始（title=%r, slides=%s, status=%s）"
        % (deck_id, (deck.get("title") or "")[:40], len(manifest["slides"]), status))
    work_dir = new_work_dir(deck_id + "-video", log)
    hb = None
    try:
        src_path = os.path.join(work_dir, "source" + ext)
        log("下载源文件：%s → %s" % (source_key, os.path.basename(src_path)))
        try:
            got = uploader.download_to(source_key, src_path)
        except Exception as exc:  # noqa: BLE001
            log("WARN 下载源文件失败：%s" % sanitize(exc, 200))
            raise convert.ConvertError(
                "源文件缺失：OSS 上找不到 %s（无法补转视频，请重新上传源文件后转换）"
                % source_key)
        size = int(got.get("size") or os.path.getsize(src_path))
        if size > MAX_SOURCE_BYTES:
            raise convert.ConvertError("源文件过大（%dMB，上限 64MB）" % (size // (1024 * 1024)))
        if not dry_run:
            hb = HeartbeatThread(cloud, log, host)
            hb.start()
        t_export = time.monotonic()
        opts = {
            "deck_id": deck_id,
            "timeout_s": VIDEO_ONLY_TIMEOUT_S,
            "log": lambda msg: log("[convert] " + str(msg)),
            "progress": lambda pct, phase="": log(
                "[video] %d%% %s" % (max(0, min(100, int(pct))), phase)),
        }
        result = convert.export_video_only(src_path, work_dir, opts)
        video = result.get("video")
        stats = result.get("stats") or {}
        summary["export_s"] = round(time.monotonic() - t_export, 2)
        if not video:
            reason = result.get("skipped") or "未生成视频（见日志 warning）"
            log("补视频跳过：%s（deck 保持 ready，分步模式不受影响）" % reason)
            for warning in result.get("warnings") or []:
                log("convert warn: %s" % warning)
            summary["action"] = "video-skip"
            summary["skipped"] = str(reason)[:300]
            return summary
        for warning in result.get("warnings") or []:
            log("convert warn: %s" % warning)
        prefix = _manifest_prefix(manifest, log)
        assets = result.get("assets") or []
        asset = assets[0] if assets else {}
        key = prefix + "deck.mp4"
        video_bytes = int(asset.get("size") or 0)
        new_manifest = dict(manifest)
        new_manifest["video"] = video  # 只新增 video，其余字段原样保留
        errors = pptx_xml.validate_manifest(new_manifest)
        if errors:
            raise convert.ConvertError("合并视频后的 manifest 校验失败：%s"
                                       % "; ".join(errors[:4]))
        if dry_run:
            log("[dry-run] 跳过视频上传：%s (%d bytes)；manifest 校验通过（slides=%d 原样保留）；"
                "manifest.video=%s"
                % (key, video_bytes, len(manifest["slides"]),
                   sanitize(json.dumps(video, ensure_ascii=False), 500)))
            summary.update({"action": "dry-run",
                            "video_dur": float(video.get("dur") or 0.0),
                            "video_bytes": video_bytes})
            return summary
        log("上传 deck.mp4 → %s（%.2fMB）" % (key, video_bytes / 1048576.0))
        uploader.put_file(key, asset["path"], content_type="video/mp4")
        code, data = cloud.patch(
            "ppt_decks?id=eq.%s" % _q(deck_id),
            {"manifest": new_manifest, "updated_at": int(time.time() * 1000)},
            prefer="return=minimal")
        if code not in (200, 204):
            raise CloudError("PATCH manifest 失败（HTTP %s）" % code)
        log("补视频完成：deck %s 视频 %.1fs / %.2fMB / %dx%d / chapters=%d / audio=%s / "
            "导出耗时 %.1fs；manifest 仅新增 video（slides=%d 未改动）"
            % (deck_id, float(video.get("dur") or 0.0), video_bytes / 1048576.0,
               int(video.get("w") or 0), int(video.get("h") or 0),
               len(video.get("chapters") or []), stats.get("audio") or "无",
               summary["export_s"], len(manifest["slides"])))
        summary.update({"action": "video-added",
                        "video_dur": float(video.get("dur") or 0.0),
                        "video_bytes": video_bytes})
        return summary
    finally:
        if hb is not None:
            hb.stop()
            try:
                send_heartbeat(cloud, log, host, 0)
            except Exception:  # noqa: BLE001
                pass
        if dry_run:
            log("[dry-run] 工作目录保留：%s" % work_dir)
        else:
            cleanup_work_dir(work_dir, log)
        summary["elapsed_s"] = summary.get("elapsed_s") or round(time.monotonic() - t0, 2)


# ---------------------------------------------------------------------------
# --compat-only：为存量 ready deck 补 v2.0 兼容文件并合并 manifest（CONTRACT §12.3）
# ---------------------------------------------------------------------------
def run_compat_only(cloud, uploader, log, host, deck_id, dry_run=False):
    """用 source_key 从 OSS 下载原件 → compat 兼容性处理 → 传进**原 build 目录** →
    合并 manifest（只新增 ``files``/``compat``，保留旧 ``slides``/``video``/``src`` 等）。"""
    t0 = time.monotonic()
    summary = {"action": "none", "deck": str(deck_id or ""), "elapsed_s": 0.0,
               "dry_run": bool(dry_run), "compat_bytes": 0, "compat_sha256": "",
               "pdf_bytes": 0, "pdf_pages": 0, "fonts_embedded": 0,
               "warnings": 0, "skipped": "", "error": ""}
    deck = find_deck_by_id(cloud, deck_id, log)
    if deck is None:
        raise CloudError("deck 不存在：%s" % deck_id)
    if deck.get("deleted"):
        raise CloudError("deck 已删除：%s" % deck_id)
    status = str(deck.get("status") or "")
    if status != "ready":
        raise CloudError("只有 ready 的 deck 才能补兼容文件（当前 status=%s）"
                         % (status or "空；如需转换请先 PATCH queued"))
    manifest = deck.get("manifest")
    if not isinstance(manifest, dict) or not manifest.get("base"):
        raise CloudError("该 deck 的 manifest 为空/不完整，无法补兼容文件（请重新上传转换）")
    if manifest.get("files"):
        log("deck %s 已有 manifest.files，本次将重新生成并覆盖" % deck_id)
    ext = source_ext_from_name(deck.get("source_name"), log)
    source_key = str(deck.get("source_key") or "")
    if not source_key:
        source_key = "ppt/src/%s/source%s" % (deck_id, ext)
        log("WARN 云端没有 source_key，按约定路径尝试：%s" % source_key)
    log("=== deck %s 补兼容文件开始（title=%r, status=%s, 已有 slides=%s, video=%s）"
        % (deck_id, (deck.get("title") or "")[:40], status,
           len(manifest.get("slides") or []), bool(manifest.get("video"))))
    work_dir = new_work_dir(deck_id + "-compat", log)
    hb = None
    try:
        src_path = os.path.join(work_dir, "source" + ext)
        log("下载源文件：%s → %s" % (source_key, os.path.basename(src_path)))
        try:
            got = uploader.download_to(source_key, src_path)
        except Exception as exc:  # noqa: BLE001
            log("WARN 下载源文件失败：%s" % sanitize(exc, 200))
            raise convert.ConvertError(
                "源文件缺失：OSS 上找不到 %s（无法补转兼容文件，请重新上传源文件后转换）"
                % source_key)
        size = int(got.get("size") or os.path.getsize(src_path))
        if size > MAX_SOURCE_BYTES:
            raise convert.ConvertError("源文件过大（%dMB，上限 64MB）"
                                       % (size // (1024 * 1024)))
        if not dry_run:
            hb = HeartbeatThread(cloud, log, host)
            hb.start()
        t_conv = time.monotonic()
        opts = {
            "deck_id": deck_id,
            "title": deck.get("title") or "",
            "source_name": deck.get("source_name") or "",
            "timeout_s": COMPAT_TIMEOUT_S,
            "log": lambda msg: log("[compat] " + str(msg)),
            "progress": lambda pct, phase="": log(
                "[compat] %d%% %s" % (max(0, min(100, int(pct))), phase)),
        }
        result = convert.convert_compat(src_path, work_dir, opts)
        files = result["files"]
        compat_meta = result["compat"]
        stats = result["stats"]
        for warning in result.get("warnings") or []:
            log("compat warn: %s" % warning)
        merged = dict(manifest)
        merged["files"] = files
        merged["compat"] = compat_meta  # 只新增/覆盖 files+compat，其余字段原样保留
        # v2.3：media_files 以本次转换结果为准（旧值清掉，避免下载到不存在的独立媒体）
        new_media_files = (result.get("manifest") or {}).get("media_files") or []
        if new_media_files:
            merged["media_files"] = new_media_files
        else:
            merged.pop("media_files", None)
        errors = pptx_xml.validate_manifest(merged)
        if errors:
            raise convert.ConvertError("合并兼容文件后的 manifest 校验失败：%s"
                                       % "; ".join(errors[:4]))
        prefix = _manifest_prefix(manifest, log)
        summary.update({
            "compat_bytes": int(stats.get("compat_size") or 0),
            "compat_sha256": str(stats.get("compat_sha256") or ""),
            "pdf_bytes": int(stats.get("pdf_size") or 0),
            "pdf_pages": int(stats.get("pdf_pages") or 0),
            "fonts_embedded": int(stats.get("fonts_embedded") or 0),
            "warnings": len(compat_meta.get("warnings") or []),
            "media_files": len(new_media_files),
        })
        if dry_run:
            log("[dry-run] 跳过上传/写云端：目标前缀 %s；compat %.2fMB sha=%s / PDF %d 页 "
                "%.2fMB / 字体 %d / 外链告警 %d 条 / 单独下载媒体 %d 个；"
                "manifest 合并校验通过（保留 slides=%d, keys=%s）"
                % (prefix, summary["compat_bytes"] / 1048576.0,
                   summary["compat_sha256"][:16], summary["pdf_pages"],
                   summary["pdf_bytes"] / 1048576.0, summary["fonts_embedded"],
                   summary["warnings"], summary["media_files"],
                   len(manifest.get("slides") or []),
                   ",".join(sorted(merged.keys()))))
            log("[dry-run] 本地产物保留（供核对 size/sha256/页数/媒体）：%s" % work_dir)
            summary["action"] = "dry-run"
            summary["export_s"] = round(time.monotonic() - t_conv, 2)
            return summary
        log("上传兼容文件 %d 个 → %s（单对象重试 2 次）"
            % (len(result["assets"]), prefix))
        upload_compat_assets(uploader, prefix, result["assets"], log, retries=2)
        # ECS 本地缓存预热（存量 deck 写回原 build 目录；best-effort）
        root_names, _media_names = _split_cache_asset_names(result["assets"])
        warm_ppt_files(WARM_BASE, prefix, root_names,
                       log=log, timeout=WARM_TIMEOUT_S)
        warm_media_assets(WARM_BASE, prefix, result["assets"], log=log)
        code, data = cloud.patch(
            "ppt_decks?id=eq.%s" % _q(deck_id),
            {"manifest": merged, "updated_at": int(time.time() * 1000)},
            prefer="return=minimal")
        if code not in (200, 204):
            raise CloudError("PATCH manifest 失败（HTTP %s）" % code)
        log("补兼容文件完成：deck %s compat %.2fMB sha=%s / PDF %d 页 / 字体 %d / "
            "外链告警 %d 条 / 耗时 %.1fs；manifest 仅新增 files+compat"
            "（slides=%d, video=%s 原样保留）"
            % (deck_id, summary["compat_bytes"] / 1048576.0,
               summary["compat_sha256"][:16], summary["pdf_pages"],
               summary["fonts_embedded"], summary["warnings"],
               time.monotonic() - t_conv, len(manifest.get("slides") or []),
               bool(manifest.get("video"))))
        summary["action"] = "compat-added"
        return summary
    finally:
        if hb is not None:
            hb.stop()
            try:
                send_heartbeat(cloud, log, host, 0)
            except Exception:  # noqa: BLE001
                pass
        if dry_run:
            log("[dry-run] 工作目录保留（供核对 size/sha256/页数/媒体）：%s" % work_dir)
        else:
            cleanup_work_dir(work_dir, log)
        summary["elapsed_s"] = summary.get("elapsed_s") or round(time.monotonic() - t0, 2)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="PPT 转换机（本机，v2.0 compat）")
    parser.add_argument("--once", action="store_true", help="跑一轮（计划任务用）")
    parser.add_argument("--scheduled", action="store_true", help="≡ --once")
    parser.add_argument("--deck", default="", help="调试指定 deck id")
    parser.add_argument("--video-only", action="store_true",
                        help="为已 ready 的 deck 只补原样播放视频（需 --deck；旧 v1.2 功能）")
    parser.add_argument("--compat-only", action="store_true",
                        help="为已 ready 的 deck 只补 v2.0 兼容文件/PDF/原件并合并 manifest"
                             "（需 --deck）")
    parser.add_argument("--legacy", action="store_true",
                        help="运维调试：走旧「分步图片+原样播放视频」流程（默认 compat）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印：不认领/不写云端/不上传 OSS")
    parser.add_argument("--verbose", action="store_true", help="同时打印到控制台")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if args.video_only and not args.deck:
        print("用法：python agent.py --deck <deckId> --video-only [--dry-run]")
        return EXIT_CONFIG
    if args.compat_only and not args.deck:
        print("用法：python agent.py --deck <deckId> --compat-only [--dry-run]")
        return EXIT_CONFIG
    if args.compat_only and args.video_only:
        print("--compat-only 与 --video-only 不能同时使用")
        return EXIT_CONFIG
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
            if args.video_only:
                summary = run_video_only(cloud, uploader, log, host, args.deck,
                                         dry_run=args.dry_run)
            elif args.compat_only:
                summary = run_compat_only(cloud, uploader, log, host, args.deck,
                                          dry_run=args.dry_run)
            else:
                summary = run_once(cloud, uploader, log, host,
                                   deck_id=(args.deck or None), dry_run=args.dry_run,
                                   legacy=bool(args.legacy))
        except CloudError as exc:
            log.error("云端/配置错误：%s" % sanitize(exc, 300))
            return EXIT_CONFIG
        except convert.ConvertError as exc:
            # --video-only / --compat-only 等补转/转换失败的明确中文错误（不写 ready deck 状态）
            log.error("补转失败：%s" % sanitize(exc, 300))
            return EXIT_CONFIG
        except Exception as exc:  # noqa: BLE001
            log.error("未捕获异常：%s" % sanitize(exc, 300))
            log.error(traceback.format_exc()[-2500:])
            return EXIT_OK
        log.log("round done：action=%s deck=%s compat=%s pdf=%s elapsed=%.1fs%s"
                % (summary.get("action"), summary.get("deck"),
                   summary.get("compat_bytes") or 0,
                   summary.get("pdf_pages") or 0,
                   summary.get("elapsed_s") or 0.0,
                   " error=" + summary.get("error") if summary.get("error") else ""))
        return EXIT_OK
    finally:
        release_lock(lock)


if __name__ == "__main__":
    sys.exit(main())
