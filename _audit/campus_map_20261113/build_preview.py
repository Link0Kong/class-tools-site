# -*- coding: utf-8 -*-
"""把 preview_data.json 内联进模板，生成可双击打开的单文件预览。"""
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "_data")
data = io.open(os.path.join(D, "preview_data.json"), encoding="utf-8").read()
tpl = io.open(os.path.join(HERE, "preview_template.html"), encoding="utf-8").read()
html = tpl.replace("__DATA__", data)
out = os.path.join(HERE, "campus_map_25d.html")
io.open(out, "w", encoding="utf-8", newline="\n").write(html)
print("written", out, len(html.encode("utf-8")), "bytes")
