# -*- coding: utf-8 -*-
"""Compare local tools/index.html with the live site (byte-exact)."""
import hashlib, urllib.request

LIVE = "https://tool.furina.fun/"
LOCAL = r"C:\Users\Ko_Li\.openclaw\workspace\web\tools\index.html"

r = urllib.request.urlopen(urllib.request.Request(LIVE, headers={"Cache-Control": "no-cache"})).read()
l = open(LOCAL, "rb").read()
print("online", len(r), hashlib.sha256(r).hexdigest())
print("local ", len(l), hashlib.sha256(l).hexdigest())
print("MATCH" if r == l else "DIFF")
for marker in (b"cbPostNoRep(", b'cbPostNoRep("visits"', b'cbPostNoRep("feedback"',
               b'cbPost("visits"', b'cbPost("feedback"'):
    print(("  %-28s" % marker.decode()), "x%d" % r.count(marker))
