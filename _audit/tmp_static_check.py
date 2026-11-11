# -*- coding: utf-8 -*-
"""静态检查：抽取 index.html 内联 <script> 逐块 node --check；统计可疑外链/请求。"""
import re
import subprocess
import sys
import tempfile
import os

PATH = r"C:\Users\Ko_Li\.openclaw\workspace\web\tools\index.html"
NODE = r"C:\nvm4w\nodejs\node.exe"
html = open(PATH, encoding="utf-8", errors="replace").read()
blocks = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.S)
print("script blocks:", len(blocks))
bad = 0
for i, b in enumerate(blocks):
    if not b.strip():
        continue
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(b)
        name = fh.name
    try:
        r = subprocess.run([NODE, "--check", name], capture_output=True, text=True)
        if r.returncode != 0:
            bad += 1
            print("[FAIL] block %d: %s" % (i, (r.stderr or "")[:300]))
    finally:
        os.unlink(name)
print("SYNTAX %s (%d bad)" % ("OK" if bad == 0 else "FAIL", bad))

# 外链域名统计
urls = re.findall(r"https?://([A-Za-z0-9._:-]+)", html)
from collections import Counter
c = Counter(urls)
print("\nHTTPS/HTTP host counts:")
for host, n in c.most_common(30):
    print("  %-40s %d" % (host, n))

# fetch 目标统计（粗粒度）
fetches = re.findall(r"fetch\(\s*([^,\n]{0,80})", html)
h = Counter()
for f in fetches:
    f = f.strip()
    if f.startswith("CB") or f.startswith("CB+"):
        h["CB+..."] += 1
    elif "location.origin" in f or f.startswith("location"):
        h["location.*"] += 1
    elif f.startswith('"') or f.startswith("'"):
        h[f[:40]] += 1
    else:
        h[f[:40]] += 1
print("\nfetch target prefixes (top 20):")
for k, n in h.most_common(20):
    print("  %-50s %d" % (k, n))
