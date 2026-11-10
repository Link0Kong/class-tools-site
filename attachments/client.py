# -*- coding: utf-8 -*-
"""通知附件外置 · 本机客户端（上传 + 生成签名 URL）。

被本机数据管线调用（例如 C:\\briefdesk\\scripts\\sync_notices_cloud.py），
把通知 items 里的 base64 `data:` URI 换成签名 URL；失败时保留原 data URI（fail-open）。

凭据：
  - 上传令牌 `CLOUD_SYNC_TOKEN`：环境变量优先，否则读 `C:\\briefdesk\\secrets\\cloud.env`
    （与 push_to_cloud.py / briefdesk-board 共用，不打印、不落日志）。
  - 签名 key = sha256(token + "|att-v1")（见 common.py），服务端同样从 SYNC_TOKEN 推导。

用法（本机）：
  python attachments\\client.py --scan C:\\briefdesk\\data\\board-data.json
  python attachments\\client.py --url <id>          # 打印一个 30 天测试 URL（不给 token）
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import DEFAULT_EXP_DAYS, content_id, derive_key, signed_url  # noqa: E402

DEFAULT_BASE = "https://tool.furina.fun"
TMP_LIMIT = 25 * 1024 * 1024
DATA_URI_RE = re.compile(r"^data:([^;,]{0,120});base64,([A-Za-z0-9+/=\s]+)$")
EXT_MIME = {
    "pdf": "application/pdf", "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "zip": "application/zip", "7z": "application/x-7z-compressed", "rar": "application/vnd.rar",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "txt": "text/plain",
}


def load_sync_token():
    tok = os.environ.get("CLOUD_SYNC_TOKEN", "").strip()
    if tok:
        return tok
    p = os.environ.get("BRIEFDESK_CLOUD_ENV", r"C:\briefdesk\secrets\cloud.env")
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("CLOUD_SYNC_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    raise RuntimeError("缺少 CLOUD_SYNC_TOKEN（环境变量或 briefdesk 的 cloud.env）")


def base_url(default=DEFAULT_BASE):
    return (os.environ.get("ATT_BASE_URL") or default).rstrip("/")


def decode_data_uri(uri):
    m = DATA_URI_RE.match(str(uri or "").strip())
    if not m:
        return None
    mime = m.group(1).split(";")[0].lower() or "application/octet-stream"
    raw = re.sub(r"\s+", "", m.group(2))
    try:
        data = base64.b64decode(raw)
    except Exception:  # noqa: BLE001
        return None
    return mime, data


def guess_mime(name, mime=None):
    if mime and mime.startswith(("image/", "application/", "video/", "audio/", "text/")):
        return mime
    ext = str(name or "").rsplit(".", 1)[-1].lower() if "." in str(name or "") else ""
    return EXT_MIME.get(ext, "application/octet-stream")


def upload(data, name, mime, base, token, timeout=120):
    req = urllib.request.Request(base.rstrip("/") + "/att/upload", data=data, method="POST")
    req.add_header("X-Sync-Token", token)
    req.add_header("X-Att-Name", urllib.parse.quote(str(name or "附件")))
    req.add_header("X-Att-Mime", urllib.parse.quote(guess_mime(name, mime)))
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("Content-Length", str(len(data)))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Uploader:
    """一次运行内的去重上传器；失败只记一次，不重复打网络。"""

    def __init__(self, base, token, exp_days=DEFAULT_EXP_DAYS, dry_run=False, verbose=True):
        self.base = base.rstrip("/")
        self.token = token
        self.key = derive_key(token)
        self.exp = int(time.time()) + int(exp_days) * 86400
        self.dry_run = dry_run
        self.verbose = verbose
        self.cache = {}
        self.failed = set()
        self.stats = {"files": 0, "bytes": 0, "uploaded": 0, "dedup": 0, "failed": 0, "replaced": 0}

    def _log(self, msg):
        if self.verbose:
            print("[att] " + msg, flush=True)

    def url_for_data_uri(self, uri, name="附件"):
        parsed = decode_data_uri(uri)
        if not parsed:
            return None
        mime, data = parsed
        if len(data) > TMP_LIMIT:
            self._log("跳过超大附件 %s (%d bytes)" % (name, len(data)))
            return None
        att_id = content_id(data)
        if att_id not in self.cache and att_id not in self.failed:
            self.stats["files"] += 1
            self.stats["bytes"] += len(data)
            if self.dry_run:
                self.cache[att_id] = True
                self._log("dry-run 将上传 %s (%d B, %s)" % (att_id, len(data), mime))
            else:
                try:
                    res = upload(data, name, mime, self.base, self.token)
                    if not res.get("ok"):
                        raise RuntimeError("upload not ok: %s" % res)
                    self.stats["uploaded"] += 1
                    self.cache[att_id] = True
                except Exception as e:  # noqa: BLE001
                    self.failed.add(att_id)
                    self.stats["failed"] += 1
                    self._log("上传失败 %s: %s" % (att_id[:10], type(e).__name__))
                    return None
        elif att_id in self.cache:
            self.stats["dedup"] += 1
        else:
            return None
        self.stats["replaced"] += 1
        return signed_url(self.base, att_id, self.exp, self.key)


def externalize_groups(groups, uploader, log=None):
    """原地把 groups 里 items 的 data URI 换成签名 URL，返回统计。只动三处字段。"""
    if log is None:
        log = lambda m: None  # noqa: E731

    def conv(uri, name):
        if not isinstance(uri, str) or not uri.startswith("data:"):
            return uri
        url = uploader.url_for_data_uri(uri, name)
        return url or uri

    for g in groups or []:
        for it in (g.get("items") or []):
            if not isinstance(it, dict):
                continue
            kind = it.get("kind")
            if kind == "img":
                it["src"] = conv(it.get("src"), it.get("caption") or it.get("name") or "图片")
            elif kind == "file":
                it["url"] = conv(it.get("url"), it.get("name") or "附件")
                if isinstance(it.get("src"), str) and it["src"].startswith("data:"):
                    it["src"] = conv(it["src"], it.get("name") or "附件")
                arch = it.get("archive")
                if isinstance(arch, dict):
                    for f in arch.get("files") or []:
                        if isinstance(f, dict):
                            f["url"] = conv(f.get("url"), f.get("name") or "压缩包内文件")
    return uploader.stats


def scan_file(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    groups = data.get("groups") or []
    n = 0
    total = 0
    by_mime = {}
    for g in groups:
        for it in (g.get("items") or []):
            vals = []
            if it.get("kind") == "img":
                vals.append(it.get("src"))
            elif it.get("kind") == "file":
                vals.append(it.get("url"))
                if str(it.get("src") or "").startswith("data:"):
                    vals.append(it.get("src"))
                for f in ((it.get("archive") or {}).get("files") or []):
                    vals.append(f.get("url"))
            for v in vals:
                parsed = decode_data_uri(v) if isinstance(v, str) else None
                if not parsed:
                    continue
                mime, blob = parsed
                n += 1
                total += len(blob)
                by_mime[mime] = by_mime.get(mime, 0) + len(blob)
    print("扫描 %s：groups=%d 内嵌附件 %d 个 / %.2f MB" % (path, len(groups), n, total / 1048576))
    for mime, b in sorted(by_mime.items(), key=lambda kv: -kv[1]):
        print("  %-60s %8.2f MB" % (mime, b / 1048576))


def main(argv=None):
    ap = argparse.ArgumentParser(description="通知附件外置客户端")
    ap.add_argument("--scan")
    ap.add_argument("--url", help="打印该 id 的 30 天测试签名 URL（不需要 token 上传）")
    ap.add_argument("--base")
    ns = ap.parse_args(argv)
    if ns.scan:
        scan_file(ns.scan)
        return 0
    if ns.url:
        token = load_sync_token()
        print(signed_url(ns.base or base_url(), ns.url, int(time.time()) + 30 * 86400, derive_key(token)))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
