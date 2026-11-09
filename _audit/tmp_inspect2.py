# -*- coding: utf-8 -*-
"""只读查看 oss2 2.19.1 的 CNAME 证书解析字段（不连接网络、不读凭据）。"""
import inspect
import oss2
from oss2 import xml_utils

print("=== CertificateInfo ===")
print(inspect.getsource(oss2.models.CertificateInfo))
print("\n=== parse_list_bucket_cname ===")
print(inspect.getsource(xml_utils.parse_list_bucket_cname))
for fn in ("_find_tag", "_get_int_tag", "_get_bool_tag"):
    f = getattr(xml_utils, fn, None)
    if f is not None:
        print("\n---", fn, "---")
        try:
            print(inspect.getsource(f))
        except Exception as e:
            print(type(e).__name__, e)
