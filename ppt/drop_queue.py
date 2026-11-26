"""File transfer adapter for the scheduled PowerPoint queue."""
import os
import re
import secrets
from urllib.parse import urlsplit

import requests


class QueueError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__("文件传输转换接口 HTTP %d" % status)


class DropQueue:
    def __init__(self, base, key):
        url = urlsplit(base)
        local = url.hostname in ("localhost", "127.0.0.1", "::1")
        if not url.hostname or (url.scheme != "https" and not (local and url.scheme == "http")):
            raise ValueError("转换机接口需要 HTTPS")
        self.base = base.rstrip("/") + "/ppt-worker/"
        self.http = requests.Session()
        self.http.headers["X-PPT-Worker-Key"] = key

    def _request(self, method, path, claim="", timeout=(3, 15), **kwargs):
        try:
            response = self.http.request(
                method, self.base + path, headers={"X-PPT-Claim": claim},
                allow_redirects=False, timeout=timeout, **kwargs)
        except requests.RequestException:
            raise QueueError(503) from None
        if response.status_code != 200:
            status = response.status_code
            response.close()
            raise QueueError(status)
        return response

    def next(self):
        with self._request("GET", "next", timeout=(3, 4)) as response:
            return response.json().get("job")

    def claim(self, job):
        path = "%s/%s/" % (job["sessionId"], job["fileId"])
        claim = secrets.token_hex(16)
        body = {"attempt": job["attempt"]}
        for attempt in (1, 2):
            try:
                with self._request("POST", path + "claim", claim, json=body) as response:
                    return path, claim, response.json()
            except QueueError as exc:
                if exc.status != 503 or attempt == 2:
                    raise

    def download_source(self, path, claim, dest, size):
        actual = 0
        with self._request("GET", path + "source", claim, timeout=(5, 90),
                           stream=True) as response, open(dest, "wb") as out:
            for block in response.iter_content(256 * 1024):
                actual += len(block)
                if actual > size:
                    raise QueueError(422)
                out.write(block)
        if actual != size:
            raise QueueError(422)

    def update(self, path, claim, status, **fields):
        with self._request("POST", path + "update", claim, json=dict(fields, status=status)):
            pass

    def upload(self, path, claim, key, file_path):
        # Send bytes once from disk. The server verifies the claim again before rename.
        with open(file_path, "rb") as fh, self._request(
                "POST", path + "artifact/" + key, claim, timeout=(5, 180), data=fh):
            pass


def configured(workspace):
    key_file = os.environ.get("PPT_DROP_WORKER_KEY_FILE") or os.path.join(
        workspace, "briefdesk", "secrets", "drop-ppt-worker.key")
    try:
        with open(key_file, encoding="ascii") as fh:
            key = fh.read(128).strip()
    except FileNotFoundError:
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("文件传输转换机密钥格式错误")
    return DropQueue(os.environ.get("PPT_DROP_BASE") or "https://tool.furina.fun/drop", key)


def downloadable_assets(result):
    manifest = result["manifest"]
    by_path = {item["name"]: item["path"] for item in result["assets"]}
    files = manifest.get("files") or {}
    for key in ("compat", "pdf"):
        item = files.get(key)
        if item and item.get("s") in by_path:
            yield key, item, by_path[item["s"]]
    for index, item in enumerate(manifest.get("media_files") or [], 1):
        if item.get("s") in by_path:
            yield "media-%d" % index, item, by_path[item["s"]]
