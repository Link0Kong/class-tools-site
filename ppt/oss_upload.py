# -*- coding: utf-8 -*-
"""oss_upload.py — 阿里云 OSS 上传（本机转换机专用，凭据绝不打印）

契约：CONTRACT.md §2 / §6。
* bucket ``tool-furina-fun``（``oss-cn-hongkong``），公共读；
* 转换产物 ``ppt/a/<deckId>/<buildId>/...``；原件 ``ppt/src/<deckId>/source.<ext>``；
* 统一 ``Cache-Control: public,max-age=31536000,immutable``（内容哈希路径，长缓存）；
* 凭据复用 ``web/deploy/sync_tools.py::load_creds()``（读 ``creds.env`` 或环境变量），
  **本模块任何日志/异常信息都不得包含 AK/SK**。

测试可传入 ``bucket=FakeBucket`` 注入假实现（见 tests/）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY_DIR = os.path.abspath(os.path.join(HERE, "..", "deploy"))

REGION = "oss-cn-hongkong"
BUCKET_NAME = "tool-furina-fun"
OSS_BASE = "https://%s.%s.aliyuncs.com/" % (BUCKET_NAME, REGION)
CACHE_CONTROL = "public,max-age=31536000,immutable"

CONTENT_TYPES = {
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
}


def content_type_for(name):
    return CONTENT_TYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream")


def asset_url(name, prefix):
    """``prefix`` 是 ``ppt/a/<deckId>/<buildId>/`` 这类 key 前缀（带斜杠）。"""
    return OSS_BASE + prefix.lstrip("/") + name


class OssUploader(object):
    """OSS 上传封装；``bucket`` 可注入（测试用假实现，不触网）。"""

    def __init__(self, bucket=None, log=None, base=OSS_BASE):
        self._bucket = bucket
        self.log = log or (lambda msg: None)
        self.base = base

    # -- 初始化（惰性导入 oss2，测试无需安装） -----------------------------
    def bucket(self):
        if self._bucket is not None:
            return self._bucket
        import oss2  # noqa: F401  延迟导入，避免单测依赖

        if DEPLOY_DIR not in sys.path:
            sys.path.insert(0, DEPLOY_DIR)
        from sync_tools import load_creds  # 复用既有凭据加载（绝不打日志）

        ak, sk = load_creds()
        if not ak or not sk:
            raise RuntimeError("OSS 凭据缺失（creds.env / 环境变量）")
        auth = oss2.Auth(ak, sk)
        self._bucket = oss2.Bucket(auth, "https://%s.aliyuncs.com" % REGION, BUCKET_NAME)
        return self._bucket

    # -- 上传 --------------------------------------------------------------
    def put_file(self, key, path, content_type=None, cache_control=CACHE_CONTROL):
        key = key.lstrip("/").replace("\\", "/")
        ctype = content_type or content_type_for(key)
        headers = {"Content-Type": ctype, "Cache-Control": cache_control}
        self.bucket().put_object_from_file(key, path, headers=headers)
        size = os.path.getsize(path)
        self.log("oss put %s (%d bytes, %s)" % (key, size, ctype))
        return {"key": key, "url": self.base + key, "size": size, "content_type": ctype}

    def put_bytes(self, key, data, content_type=None, cache_control=CACHE_CONTROL):
        key = key.lstrip("/").replace("\\", "/")
        ctype = content_type or content_type_for(key)
        headers = {"Content-Type": ctype, "Cache-Control": cache_control}
        self.bucket().put_object(key, data, headers=headers)
        return {"key": key, "url": self.base + key, "size": len(data), "content_type": ctype}

    def head_ok(self, key):
        """HEAD 对象存在性校验（测试/验收用）。"""
        try:
            meta = self.bucket().head_object(key.lstrip("/"))
            return True, int(getattr(meta, "content_length", 0) or 0)
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:200]

    def delete_prefix(self, prefix):
        """删除整个前缀（重转换清理旧 build 用；失败只记日志，绝不阻塞）。"""
        prefix = prefix.lstrip("/").replace("\\", "/")
        if not prefix.endswith("/"):
            prefix += "/"
        try:
            import oss2
            deleted = 0
            for obj in oss2.ObjectIterator(self.bucket(), prefix=prefix):
                self.bucket().delete_object(obj.key)
                deleted += 1
            self.log("oss delete prefix %s (%d objects)" % (prefix, deleted))
            return deleted
        except Exception as exc:  # noqa: BLE001
            self.log("WARN oss delete prefix %s failed: %s" % (prefix, str(exc)[:160]))
            return -1
