# -*- coding: utf-8 -*-
"""
把 web\\ziqi 里的页面文件同步到线上 https://me.furina.fun/

用法：
    python sync.py              # 同步 index.html + og.png
    python sync.py 其他文件...  # 额外同步指定文件（相对 web\\ziqi）

凭据：从环境变量 ALIYUN_AK_ID / ALIYUN_AK_SECRET 读取；
      未设置时尝试读取同目录 creds.env（每行 KEY=VALUE）。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "ziqi"))
REGION = "oss-cn-hongkong"
BUCKET = "me-furina-fun"
DEFAULT_FILES = ["index.html", "og.png"]

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
    raise SystemExit("缺少凭据：请设置环境变量 ALIYUN_AK_ID / ALIYUN_AK_SECRET")

CTYPE = {".html": "text/html; charset=utf-8", ".png": "image/png",
         ".jpg": "image/jpeg", ".css": "text/css; charset=utf-8",
         ".js": "application/javascript; charset=utf-8",
         ".svg": "image/svg+xml", ".ico": "image/x-icon",
         ".pdf": "application/pdf",
         ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}

def main():
    import oss2
    ak, sk = load_creds()
    bucket = oss2.Bucket(oss2.Auth(ak, sk), "https://%s.aliyuncs.com" % REGION, BUCKET)
    files = sys.argv[1:] or DEFAULT_FILES
    for name in files:
        path = os.path.join(SRC, name)
        if not os.path.exists(path):
            print("跳过（不存在）:", name); continue
        ext = os.path.splitext(name)[1].lower()
        headers = {"Content-Type": CTYPE.get(ext, "application/octet-stream"),
                   "Cache-Control": "no-cache"}
        bucket.put_object_from_file(name, path, headers=headers)
        print("已同步 %-16s %8d bytes  ->  https://me.furina.fun/%s" %
              (name, os.path.getsize(path), name))
    print("完成。")

if __name__ == "__main__":
    main()
