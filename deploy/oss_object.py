# -*- coding: utf-8 -*-
"""OSS 对象读取/校验工具（tool-furina-fun bucket）。

用途（2026-11-07 新增）：furina.fun DNS 暂停期间线上 URL 不可访问，部署前后改用 OSS 对象字节校验；
也用于把线上当前 index.html 备份到 tools/_backup/（回滚用）。

凭据：复用 sync_tools.py 的 load_creds()（环境变量或 deploy/creds.env），本工具不打印凭据。

用法（在 web 目录下）：
  python deploy/oss_object.py sha index.html
  python deploy/oss_object.py get index.html tools/_backup/index_online_20261107-xxxx_preXXX.html
  python deploy/oss_object.py check index.html            # 与本地 tools/index.html 比对 sha256
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sync_tools  # noqa: E402  (同目录；只复用凭据加载，不触发上传)

REGION = sync_tools.REGION
BUCKET = sync_tools.BUCKET


def bucket():
    import oss2
    ak, sk = sync_tools.load_creds()
    return oss2.Bucket(oss2.Auth(ak, sk), "https://%s.aliyuncs.com" % REGION, BUCKET)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    b = bucket()
    if cmd == "sha" and len(argv) >= 2:
        key = argv[1]
        obj = b.get_object(key)
        data = obj.read()
        print("%s %d bytes sha256=%s" % (key, len(data), sha256_bytes(data)))
        return 0
    if cmd == "get" and len(argv) >= 3:
        key, out = argv[1], argv[2]
        data = b.get_object(key).read()
        parent = os.path.dirname(os.path.abspath(out))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(out, "wb") as f:
            f.write(data)
        print("saved %s -> %s (%d bytes sha256=%s)" % (key, out, len(data), sha256_bytes(data)))
        return 0
    if cmd == "check" and len(argv) >= 2:
        key = argv[1]
        local = os.path.join(os.path.dirname(HERE), "tools", argv[1].replace("/", os.sep))
        remote = b.get_object(key).read()
        with open(local, "rb") as f:
            loc = f.read()
        r, l = sha256_bytes(remote), sha256_bytes(loc)
        print("remote %d %s\nlocal  %d %s\n%s" % (len(remote), r, len(loc), l, "MATCH" if r == l else "MISMATCH"))
        return 0 if r == l else 1
    print("unknown/incomplete command", argv)
    return 2


if __name__ == "__main__":
    sys.exit(main())
