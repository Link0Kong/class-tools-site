# -*- coding: utf-8 -*-
"""线上校验：与本地 index.html 逐字节比对 + 关键词检查。"""
import hashlib, urllib.request, os, sys

LOCAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")
URL = "https://me.furina.fun/"

def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read()

local = open(LOCAL, "rb").read()
remote = get(URL)
print("local  sha256:", hashlib.sha256(local).hexdigest()[:16], len(local), "bytes")
print("remote sha256:", hashlib.sha256(remote).hexdigest()[:16], len(remote), "bytes")
print("VERDICT:", "MATCH" if hashlib.sha256(local).hexdigest() == hashlib.sha256(remote).hexdigest() else "DIFF")

h = remote.decode("utf-8", "ignore")
must = ["Ko_Link@outlook.com", 'id="campaign"', 'id="games"', "210684727", "107523297",
        "273432196", "SW-3771-0460-3336", "1801625604", "我为班里做什么", "一起玩", "点开看我的游戏联系方式"]
mustnot = ["3299207275@qq.com", "小红书", "钢琴"]
for k in must:
    print(("ok  " if k in h else "MISS"), "contains:", k)
for k in mustnot:
    print(("ok  " if k not in h else "LEAK"), "absent:", k)
