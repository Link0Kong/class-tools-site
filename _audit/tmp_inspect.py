# -*- coding: utf-8 -*-
"""只读查看 oss2 2.19.1 的 CNAME 相关模型/接口（不连接网络、不读凭据）。"""
import inspect
import oss2

print("oss2", oss2.__version__)
print("Bucket cname methods:", [m for m in dir(oss2.Bucket) if "cname" in m.lower()])
for name in ("CnameInfo", "ListBucketCnameResult", "GetBucketCnameTokenResult", "CreateBucketCnameTokenResult"):
    cls = getattr(oss2.models, name, None)
    print("\n---", name, "->", cls)
    if cls is not None:
        try:
            print(inspect.getsource(cls))
        except Exception as e:
            print(type(e).__name__, e)

print("\n=== Bucket.list_bucket_cname ===")
print(inspect.getsource(oss2.Bucket.list_bucket_cname))
print("\n=== Bucket.put_bucket_cname ===")
print(inspect.getsource(oss2.Bucket.put_bucket_cname))
print("\n=== Bucket.create_bucket_cname_token ===")
print(inspect.getsource(oss2.Bucket.create_bucket_cname_token))
