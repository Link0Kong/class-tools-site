# -*- coding: utf-8 -*-
"""
把 web\\tools 里的静态文件同步到独立 Bucket -> https://tool.furina.fun/

用法：
    python C:\\Users\\Ko_Li\\.openclaw\\workspace\\web\\deploy\\sync_tools.py
可只同步指定文件：
    python sync_tools.py index.html

凭据：环境变量 ALIYUN_AK_ID / ALIYUN_AK_SECRET，或同目录 creds.env
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "tools"))
REGION = "oss-cn-hongkong"
BUCKET = "tool-furina-fun"
BASE = "https://tool.furina.fun/"

CTYPE = {".html": "text/html; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
         ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
         ".svg": "image/svg+xml", ".ico": "image/x-icon", ".json": "application/json; charset=utf-8",
         ".txt": "text/plain; charset=utf-8"}


def load_creds():
    if os.environ.get("ALIYUN_AK_ID") and os.environ.get("ALIYUN_AK_SECRET"):
        return os.environ["ALIYUN_AK_ID"], os.environ["ALIYUN_AK_SECRET"]
    p = os.path.join(HERE, "creds.env")
    if os.path.exists(p):
        d = {}
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
        return d.get("ALIYUN_AK_ID"), d.get("ALIYUN_AK_SECRET")
    raise SystemExit("缺少凭据：请设置环境变量 ALIYUN_AK_ID / ALIYUN_AK_SECRET，或建 web/deploy/creds.env")


def main():
    import oss2
    ak, sk = load_creds()
    bucket = oss2.Bucket(oss2.Auth(ak, sk), "https://%s.aliyuncs.com" % REGION, BUCKET)
    assets = os.path.join(SRC, "assets")
    files = ["index.html"]
    if os.path.isdir(assets):
        files += ["assets/" + f for f in sorted(os.listdir(assets))]
    # 教务课表同步产物（jwxt/sync.py 生成，同源 fetch 读取）
    if os.path.exists(os.path.join(SRC, "tt.json")):
        files.append("tt.json")
    only = sys.argv[1:]
    for name in files:
        name = name.replace("\\", "/")
        if only and name not in only:
            continue
        path = os.path.join(SRC, name.replace("/", os.sep))
        if not os.path.exists(path):
            print("跳过(不存在):", name)
            continue
        ext = os.path.splitext(name)[1].lower()
        bucket.put_object_from_file(name, path, headers={
            "Content-Type": CTYPE.get(ext, "application/octet-stream"), "Cache-Control": "no-cache"})
        print("已同步 %-22s %8d bytes -> %s%s" % (name, os.path.getsize(path), BASE, name))
    print("完成。线上地址：%s" % BASE)


if __name__ == "__main__":
    main()
