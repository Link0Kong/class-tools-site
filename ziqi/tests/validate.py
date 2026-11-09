# -*- coding: utf-8 -*-
import os, re, sys
p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")
s = open(p, encoding="utf-8").read()
print("bytes:", len(s.encode("utf-8")))
print("span on= :", s.count('span on='))
print("div open/close:", s.count("<div"), s.count("</div>"), "diff", s.count("<div")-s.count("</div>"))
print("span open/close:", s.count("<span"), s.count("</span>"), "diff", s.count("<span")-s.count("</span>"))
print("article open/close:", s.count("<article"), s.count("</article>"))
print("section open/close:", s.count("<section"), s.count("</section>"))
# 结构：<span ...> 自闭合的没有；</span> 应 >= <span
# 外部请求检查
for pat in ["http://", "https://"]:
    for m in re.finditer(pat + r"[^\"')\s]+", s):
        u = m.group(0)
        if "furina.fun" in u or "github.com/Link0Kong" in u or "bilibili.com" in u or "music.163.com" in u or "xiaohongshu.com" in u:
            continue
        print("EXTERNAL?", u)
print("ok")
