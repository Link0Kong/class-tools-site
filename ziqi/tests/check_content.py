# -*- coding: utf-8 -*-
import os, re
p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")
s = open(p, encoding="utf-8").read()
keys = ['id="campaign"', 'id="games"', 'Ko_Link@outlook.com', '210684727', '107523297',
        '273432196', 'SW-3771-0460-3336', '1801625604', 'grow', '3299207275@qq.com',
        'election.html', 'mailto:']
for k in keys:
    print(("ok  " if k in s else "MISS"), k, "x", s.count(k))
print("rail numbers:", re.findall(r'class="n mono">(\d+)</span><h2>([^<]+)</h2>', s))
print("nav:", re.findall(r'<a href="(#[a-z]+)">([^<]+)</a>', s))
