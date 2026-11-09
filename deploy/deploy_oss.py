# -*- coding: utf-8 -*-
"""
Step 1: 在香港地域建立 OSS Bucket，开公共读 + 静态网站托管，上传页面文件。
用法: python deploy_oss.py
"""
import os, sys, oss2

AK = os.environ["ALIYUN_AK_ID"]
SK = os.environ["ALIYUN_AK_SECRET"]
REGION = "oss-cn-hongkong"
EP = "https://%s.aliyuncs.com" % REGION
BUCKET_NAME = os.environ.get("BUCKET_NAME", "me-furina-fun")
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ziqi"))

auth = oss2.Auth(AK, SK)
svc = oss2.Service(auth, EP)

existing = {b.name for b in oss2.BucketIterator(svc)}
print("existing:", existing)

bucket = oss2.Bucket(auth, EP, BUCKET_NAME)

if BUCKET_NAME not in existing:
    print("creating bucket:", BUCKET_NAME)
    try:
        bucket.create_bucket(permission=oss2.BUCKET_ACL_PUBLIC_READ)
        print("created (public-read)")
    except Exception as e:
        print("public-read create failed:", type(e).__name__, e)
        bucket.create_bucket(permission=oss2.BUCKET_ACL_PRIVATE)
        print("created (private)")
else:
    print("bucket exists, reusing")

# 公共读（静态网站必须）
try:
    bucket.put_bucket_acl(oss2.BUCKET_ACL_PUBLIC_READ)
    print("acl -> public-read")
except Exception as e:
    print("!! put acl failed:", type(e).__name__, e)

# 静态网站托管：首页 index.html，404 也回 index.html
bucket.put_bucket_website(oss2.models.BucketWebsite(
    index_file="index.html", error_file="index.html"))
print("website hosting on (index.html)")

# 上传
for name in ["index.html", "og.png"]:
    p = os.path.join(SRC, name)
    ct = "text/html; charset=utf-8" if name.endswith(".html") else "image/png"
    bucket.put_object_from_file(name, p, headers={"Content-Type": ct, "Cache-Control": "no-cache"})
    print("uploaded:", name, os.path.getsize(p), "bytes")

print("STATIC_URL=http://%s.%s.aliyuncs.com/" % (BUCKET_NAME, REGION))
print("CNAME_TARGET=%s.%s.aliyuncs.com" % (BUCKET_NAME, REGION))
print()
print("== cname-related methods on bucket ==")
print([m for m in dir(bucket) if "cname" in m.lower()])
