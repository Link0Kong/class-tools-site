# -*- coding: utf-8 -*-
"""pptfiles_app.py — ECS「PPT 文件缓存」本地服务（Python 标准库，127.0.0.1:8092）

用途（2026-11-11，下载加速）：
    兼容包 compat.pptx / preview.pdf / original.pptx 在 OSS 香港，跨境单连接仅 ~74KB/s。
    ECS 杭州 → OSS 约 618KB/s，用户 → ECS 约 4.7MB/s。本服务把 PPT 文件缓存到 ECS
    本地磁盘（/opt/class-tools/pptfiles），Caddy `handle /pptfiles/*` 反代本服务：
      - 命中缓存：本地下发（支持 Range/206、HEAD、immutable 长缓存）；
      - 未命中：从 OSS 拉取并写缓存（.part 临时文件 → 原子 rename；同 path 加锁）；
      - 转换机上传完成后调用 `/__warm/ppt/...` 后台预热，用户下载时通常已命中缓存。

路由（Caddy 已 strip_prefix /pptfiles）：
    GET/HEAD  /ppt/<path>        仅允许 ppt/ 前缀；缓存命中/未命中都可用
    GET       /__warm/ppt/<path> 后台预热：已缓存 200，正在预热 202，启动预热 202
    GET       /__health          200 JSON（版本/缓存文件数/字节/预热中数量/运行时长）

安全：
    - 只监听 127.0.0.1（公网只能经 Caddy `/pptfiles/*` 访问）；
    - 路径白名单前缀 `ppt/`，拒绝 `..` / 反斜杠 / NUL —— 不会穿越出缓存根目录；
    - 上游仅 OSS 公开读地址（无凭据）；本服务不接触 AK/SK/token。

配置（环境变量，systemd unit 里设置）：
    PPTFILES_ROOT         缓存根目录，默认 /opt/class-tools/pptfiles
    PPTFILES_PORT         监听端口，默认 8092
    PPTFILES_OSS_BASE     上游 OSS 基址，默认 tool-furina-fun.oss-cn-hongkong.aliyuncs.com
    PPTFILES_MAX_BYTES    缓存磁盘上限（字节），默认 5GiB（超出按 mtime 清最旧）
    PPTFILES_TIMEOUT      上游连接/读取超时秒数，默认 30
    PPTFILES_LOG_LEVEL    日志级别（INFO 默认；DEBUG 打印每个请求）

运行：`python3 /opt/class-tools/pptfiles/app.py`（生产由 systemd class-tools-pptfiles.service 管理）
"""
import json
import mimetypes
import os
import posixpath
import re
import shutil
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0"
ROOT = os.environ.get("PPTFILES_ROOT", "/opt/class-tools/pptfiles")
PORT = int(os.environ.get("PPTFILES_PORT", "8092"))
OSS_BASE = os.environ.get(
    "PPTFILES_OSS_BASE",
    "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com").rstrip("/")
MAX_BYTES = int(os.environ.get("PPTFILES_MAX_BYTES", str(5 * 1024 * 1024 * 1024)))
TIMEOUT = float(os.environ.get("PPTFILES_TIMEOUT", "30"))
CHUNK = 1024 * 1024
UA = "class-tools-pptfiles/1.0"
ALLOWED_PREFIX = "ppt/"
_IMMUTABLE = "public, max-age=31536000, immutable"
CONTENT_TYPES = {
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pdf": "application/pdf",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}
_LOCK = threading.Lock()
_LOCKS = {}
_WARMING = set()
_STARTED = time.time()
_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f]')
_INVALID_SEGMENT = re.compile(r'^\.{1,2}$')


def log(msg, level="I"):
    try:
        sys.stdout.write("%s [%s] %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), level, msg))
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def warn(msg):
    log(msg, "W")


# ---------------------------------------------------------------------------
# 路径 / 缓存
# ---------------------------------------------------------------------------
def safe_rel_path(raw_path):
    """把 URL 路径里的 ``ppt/...`` 转成安全相对路径；非法返回 None（防穿越）。"""
    text = urllib.parse.unquote(str(raw_path or ""))
    text = text.replace("\\", "/").strip("/")
    if not text or _BAD_CHARS.search(text):
        return None
    parts = text.split("/")
    for part in parts:
        if not part or _INVALID_SEGMENT.match(part):
            return None
    rel = posixpath.normpath(text)
    if rel.startswith("../") or rel == ".." or rel.startswith("/"):
        return None
    if not rel.startswith(ALLOWED_PREFIX):
        return None
    return rel


def cache_path(rel):
    full = os.path.abspath(os.path.join(ROOT, rel.replace("/", os.sep)))
    root = os.path.abspath(ROOT)
    if full != root and not full.startswith(root + os.sep):
        raise ValueError("path escaped cache root")
    return full


def content_type(rel):
    ext = os.path.splitext(rel)[1].lower()
    if ext in CONTENT_TYPES:
        return CONTENT_TYPES[ext]
    guessed, _ = mimetypes.guess_type(rel)
    return guessed or "application/octet-stream"


def _path_lock(rel):
    with _LOCK:
        lock = _LOCKS.get(rel)
        if lock is None:
            lock = _LOCKS[rel] = threading.Lock()
        return lock


def _is_warming(rel):
    with _LOCK:
        return rel in _WARMING


def cache_stats():
    """缓存目录统计（只统计 ``ROOT/ppt`` 下的缓存文件，不含 app.py/__pycache__）。"""
    files = 0
    total = 0
    cache_root = os.path.join(ROOT, "ppt")
    walk_root = cache_root if os.path.isdir(cache_root) else ROOT
    try:
        for dirpath, _dirnames, filenames in os.walk(walk_root):
            for name in filenames:
                if name.endswith(".part") or ".part." in name:
                    continue
                try:
                    files += 1
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    continue
    except OSError:
        pass
    with _LOCK:
        warming = len(_WARMING)
    return {"files": files, "bytes": total, "warming": warming,
            "root": ROOT, "cache_dir": walk_root, "max_bytes": MAX_BYTES,
            "uptime_s": round(time.time() - _STARTED, 1), "version": VERSION}


def _evict_if_needed():
    """缓存超过上限时按 mtime 从旧到新删除（只删缓存文件，不动 .part）。"""
    try:
        st = cache_stats()
        if st["bytes"] <= MAX_BYTES:
            return
        entries = []
        for dirpath, _dirnames, filenames in os.walk(ROOT):
            for name in filenames:
                if name.endswith(".part") or ".part." in name:
                    continue
                path = os.path.join(dirpath, name)
                try:
                    entries.append((os.path.getmtime(path), os.path.getsize(path), path))
                except OSError:
                    continue
        entries.sort()
        removed = 0
        freed = 0
        for _mtime, size, path in entries:
            if st["bytes"] - freed <= MAX_BYTES:
                break
            try:
                os.remove(path)
                freed += size
                removed += 1
            except OSError:
                continue
        if removed:
            log("cache evict：删除 %d 个最旧文件，释放 %.1fMB"
                % (removed, freed / 1048576.0))
    except Exception as exc:  # noqa: BLE001
        warn("cache evict 失败：%s" % exc.__class__.__name__)


def oss_url(rel):
    return OSS_BASE + "/" + urllib.parse.quote(rel, safe="/")


def _download_to_cache(rel):
    """从 OSS 下载到 ``<cache>.part.<pid>.<tid>``，成功后原子 rename。返回字节数。"""
    final = cache_path(rel)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    part = "%s.part.%d.%d" % (final, os.getpid(), threading.get_ident())
    url = oss_url(rel)
    size = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            length = resp.headers.get("Content-Length")
            with open(part, "wb") as fh:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    size += len(chunk)
        if length is not None and str(length).isdigit() and int(length) != size:
            raise IOError("长度不一致（期望 %s / 实际 %d）" % (length, size))
        os.replace(part, final)
        log("cache 写入 %s（%.2fMB）" % (rel, size / 1048576.0))
        _evict_if_needed()
        return size
    except Exception:
        try:
            if os.path.exists(part):
                os.remove(part)
        except OSError:
            pass
        raise


def _warm_async(rel):
    """后台预热（返回 True=已启动/正在进行，False=已在缓存）。"""
    if os.path.exists(cache_path(rel)):
        return False
    with _LOCK:
        if rel in _WARMING:
            return True
        _WARMING.add(rel)

    def worker():
        try:
            with _path_lock(rel):
                if not os.path.exists(cache_path(rel)):
                    _download_to_cache(rel)
                else:
                    log("warm 命中缓存（他人已完成）%s" % rel)
        except Exception as exc:  # noqa: BLE001
            warn("warm 失败 %s：%s: %s" % (rel, exc.__class__.__name__, str(exc)[:160]))
        finally:
            with _LOCK:
                _WARMING.discard(rel)

    threading.Thread(target=worker, name="warm-" + rel[-40:], daemon=True).start()
    return True


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _parse_range(header, size):
    """解析 ``bytes=`` Range；返回 (start,end) 闭区间；无/多段/非法返回 None。"""
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
            return start, size - 1
        start = int(left)
        end = int(right) if right != "" else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


def _etag(path):
    try:
        stat = os.stat(path)
        return '"%x-%x"' % (int(stat.st_mtime), stat.st_size)
    except OSError:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "class-tools-pptfiles/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: D401  只走自己的 journal 日志
        log("%s %s" % (self.address_string(), fmt % args))

    # -- 基础响应 ----------------------------------------------------------
    def _send_json(self, status, payload, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_error_json(self, status, message, rel=""):
        log("%s %s -> %s %s" % (self.command, self.path, status, message), "W")
        self._send_json(status, {"ok": False, "status": status, "error": message,
                                 "path": rel})

    def _send_file(self, path, rel, head_only=False):
        try:
            size = os.path.getsize(path)
        except OSError:
            self._send_error_json(404, "文件不存在", rel)
            return
        ctype = content_type(rel)
        etag = _etag(path)
        range_header = self.headers.get("Range")
        selected = _parse_range(range_header, size) if range_header else None
        if range_header and selected is None:
            self.send_response(416)
            self.send_header("Content-Range", "bytes */%d" % size)
            self.send_header("Content-Length", "0")
            for key, value in (("Accept-Ranges", "bytes"),
                               ("Cache-Control", _IMMUTABLE),
                               ("Content-Type", ctype)):
                self.send_header(key, value)
            self.end_headers()
            log("GET %s -> 416 (invalid range)" % rel)
            return
        start, end = selected if selected else (0, size - 1)
        length = end - start + 1
        self.send_response(206 if selected else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", _IMMUTABLE)
        if etag:
            self.send_header("ETag", etag)
        if selected:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        if head_only or self.command == "HEAD":
            return
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            log("GET %s -> %s %d/%d bytes (cache)"
                % (rel, 206 if selected else 200, length, size))
        except (BrokenPipeError, ConnectionResetError):
            log("GET %s 客户端中断（剩余 %d bytes）" % (rel, remaining), "W")

    # -- 上游 HEAD（未缓存时） ----------------------------------------------
    def _upstream_head(self, rel):
        try:
            req = urllib.request.Request(oss_url(rel), method="HEAD",
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                size = resp.headers.get("Content-Length") or "0"
                self.send_response(200)
                self.send_header("Content-Type",
                                 resp.headers.get("Content-Type") or content_type(rel))
                self.send_header("Content-Length", size)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", _IMMUTABLE)
                self.end_headers()
                log("HEAD %s -> 200 (upstream, %s bytes)" % (rel, size))
        except urllib.error.HTTPError as exc:
            self._send_error_json(404 if exc.code == 404 else 502,
                                  "上游 HTTP %s" % exc.code, rel)
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(502, "上游不可用：%s" % exc.__class__.__name__, rel)

    # -- 未缓存 GET：流式下发 + 写缓存 --------------------------------------
    def _fetch_and_stream(self, rel, head_only=False):
        """获取未缓存文件：边下边发（写 .part），完成后原子 rename；客户端可先拿到字节。"""
        final = cache_path(rel)
        os.makedirs(os.path.dirname(final), exist_ok=True)
        part = "%s.part.%d.%d" % (final, os.getpid(), threading.get_ident())
        url = oss_url(rel)
        size = 0
        sent_headers = False
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                length = resp.headers.get("Content-Length")
                try:
                    length_int = int(length) if length and str(length).isdigit() else None
                except (TypeError, ValueError):
                    length_int = None
                ctype = resp.headers.get("Content-Type") or content_type(rel)
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                if length_int is not None:
                    self.send_header("Content-Length", str(length_int))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", _IMMUTABLE)
                self.end_headers()
                sent_headers = True
                with open(part, "wb") as fh:
                    while True:
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        fh.write(chunk)
                        size += len(chunk)
                        if not head_only:
                            self.wfile.write(chunk)
            if length_int is not None and int(length_int) != size:
                raise IOError("上游长度不一致（期望 %d / 实际 %d）" % (length_int, size))
            os.replace(part, final)
            log("cache 写入 %s（%.2fMB，边下边发）" % (rel, size / 1048576.0))
            _evict_if_needed()
        except (BrokenPipeError, ConnectionResetError):
            warn("GET %s 客户端中断，丢弃未完成缓存（已收 %d bytes）" % (rel, size))
            try:
                if os.path.exists(part):
                    os.remove(part)
            except OSError:
                pass
        except Exception as exc:  # noqa: BLE001
            try:
                if os.path.exists(part):
                    os.remove(part)
            except OSError:
                pass
            if not sent_headers:
                self._send_error_json(502, "拉取失败：%s" % exc.__class__.__name__, rel)
            else:
                warn("GET %s 上游中断，连接将提前结束：%s" % (rel, exc.__class__.__name__))

    # -- 路由 --------------------------------------------------------------
    def do_HEAD(self):
        self._dispatch(head_only=True)

    def do_GET(self):
        self._dispatch(head_only=False)

    def do_POST(self):
        # 预热允许 POST（部分客户端/脚本）；其它 POST 404
        if self.path.startswith("/__warm/"):
            self._dispatch(head_only=False)
        else:
            self._send_error_json(404, "not found")

    def _dispatch(self, head_only=False):
        started = time.time()
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            if path in ("/__health", "/__health/"):
                payload = {"ok": True}
                payload.update(cache_stats())
                self._send_json(200, payload)
                return
            if path.startswith("/__warm/"):
                rel = safe_rel_path(path[len("/__warm/"):])
                if rel is None:
                    self._send_error_json(400, "非法缓存路径（仅允许 ppt/ 前缀）")
                    return
                if os.path.exists(cache_path(rel)):
                    payload = {"ok": True, "cached": True, "path": rel}
                    self._send_json(200, payload)
                    return
                started_warm = _warm_async(rel)
                payload = {"ok": True, "cached": False,
                           "warming": True, "started": bool(started_warm),
                           "path": rel}
                self._send_json(202, payload)
                return
            rel = safe_rel_path(path)
            if rel is None:
                self._send_error_json(400, "非法缓存路径（仅允许 ppt/ 前缀）")
                return
            target = cache_path(rel)
            if os.path.exists(target):
                self._send_file(target, rel, head_only=head_only)
                return
            if head_only:
                self._upstream_head(rel)
                _warm_async(rel)  # 顺带后台缓存，方便随后的 GET
                return
            # 未缓存 GET：单 path 串行（第二个请求等待，之后直接命中缓存）
            lock = _path_lock(rel)
            acquired = lock.acquire(timeout=300)
            try:
                if os.path.exists(target):
                    self._send_file(target, rel, head_only=head_only)
                    return
                if self.headers.get("Range"):
                    # Range 请求：先完整落盘缓存，再按 Range 下发 206（保证后续请求命中）
                    try:
                        _download_to_cache(rel)
                    except Exception as exc:  # noqa: BLE001
                        self._send_error_json(
                            502, "拉取失败：%s" % exc.__class__.__name__, rel)
                        return
                    self._send_file(target, rel, head_only=head_only)
                    return
                self._fetch_and_stream(rel, head_only=head_only)
            finally:
                if acquired:
                    lock.release()
        except Exception as exc:  # noqa: BLE001
            warn("请求异常 %s %s：%s" % (self.command, self.path,
                                       exc.__class__.__name__))
            warn(traceback.format_exc()[-800:])
            try:
                self._send_error_json(500, "内部错误")
            except Exception:  # noqa: BLE001
                pass
        finally:
            if "rel" in locals():
                log("%s %s %.0fms" % (self.command, rel,
                                      (time.time() - started) * 1000))


def main():
    os.makedirs(ROOT, exist_ok=True)
    st = cache_stats()
    log("start v%s root=%s port=%d max=%.1fGB cached=%.2fMB/%d files"
        % (VERSION, ROOT, PORT, MAX_BYTES / 1073741824.0,
           st["bytes"] / 1048576.0, st["files"]))
    _evict_if_needed()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("stop")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
