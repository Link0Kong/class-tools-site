# -*- coding: utf-8 -*-
"""校验线上：index.html 逐字节比对 + 竞选材料/幻灯片预览图的 大小 与 Content-Type。"""
import hashlib, os, urllib.request

ZI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://me.furina.fun/"

def head(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    r = urllib.request.urlopen(req, timeout=30)
    return r.status, r.headers.get("Content-Type", ""), int(r.headers.get("Content-Length", "0"))

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read()

# 1) index.html
local = open(os.path.join(ZI, "index.html"), "rb").read()
remote = get(BASE)
print("index.html  %s  (%d bytes)" % (
    "MATCH" if hashlib.sha256(local).hexdigest() == hashlib.sha256(remote).hexdigest() else "DIFF",
    len(remote)))

# 2) 附件
files = ["files/slides.pdf", "files/slides.pptx", "files/speech.pdf", "files/speech.docx"]
ok = True
for f in files:
    lp = os.path.join(ZI, f.replace("/", os.sep))
    lsize = os.path.getsize(lp)
    try:
        st, ct, cl = head(BASE + f)
    except Exception as e:
        print("ERR  %-24s %s" % (f, e)); ok = False; continue
    good = (st == 200 and cl == lsize)
    if not good:
        ok = False
    print("%-4s %-24s %8d bytes  ct=%s" % ("ok" if good else "BAD", f, cl, ct))
print()
print("ALL FILES OK" if ok else "SOME FILES BAD")

print()
print("=== 已撤下的幻灯片图应返回 404 ===")
for i in range(1, 7):
    u = BASE + "assets/slides/%d.jpg" % i
    try:
        st, ct, cl = head(u)
        print("BAD  %-28s still %s (%d bytes)" % (u, st, cl))
    except Exception as e:
        print("ok   %-28s gone (%s)" % (u, getattr(e, "code", type(e).__name__)))

# 3) 页面里引用的新资源是否都在（粗查）
h = remote.decode("utf-8", "ignore")
for k in ["files/slides.pdf", "files/speech.pdf", "files/slides.pptx", "files/speech.docx",
          "竞选演讲稿", "全文约 490 字", 'class="sp"', "看排版版 PDF", "下载 PPTX"]:
    print(("ok  " if k in h else "MISS"), k)
print()
for k in ["assets/slides/1.jpg", "assets/slides/6.jpg", 'class="strip"', 'class="sld"']:
    print(("ok  " if k not in h else "BAD "), "absent:", k)
