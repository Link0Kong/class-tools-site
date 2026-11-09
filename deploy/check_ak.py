# -*- coding: utf-8 -*-
"""检查阿里云 AK 是否可用，并列出香港地域已有 Bucket。"""
import os, sys, oss2

AK = os.environ.get("ALIYUN_AK_ID")
SK = os.environ.get("ALIYUN_AK_SECRET")
if not AK or not SK:
    print("MISSING_ENV"); sys.exit(2)

auth = oss2.Auth(AK, SK)
ep = "https://oss-cn-hongkong.aliyuncs.com"
svc = oss2.Service(auth, ep)
try:
    print("buckets in oss-cn-hongkong:")
    n = 0
    for b in oss2.BucketIterator(svc):
        print("  -", b.name, b.location)
        n += 1
    print("total:", n)
except Exception as e:
    print("ERR", type(e).__name__, e)
