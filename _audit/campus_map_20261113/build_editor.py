# -*- coding: utf-8 -*-
"""生成单文件 2D 布局编辑器：preview_data.json + editor_template.html -> campus_map_editor.html"""
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(io.open(os.path.join(HERE, "_data", "preview_data.json"), encoding="utf-8"))
polys = {f["id"]: f["p"] for f in data["features"] if f["k"] == "bld"}
for b in data["buildings"]:
    if not b.get("p"):
        b["p"] = polys.get(b["id"], [])
if not any(b["id"] == "MUS" for b in data["buildings"]):
    data["buildings"].append({
        "id": "MUS", "n": "博物馆", "ln": "博物馆", "no": "", "k": "图书馆", "g": "civic",
        "h": 12.5, "fl": 2, "x": 523, "y": 430, "lb": 1, "u": "",
        "p": [[500, 414], [546, 414], [546, 446], [500, 446]],
    })
tpl = io.open(os.path.join(HERE, "editor_template.html"), encoding="utf-8").read()
html = tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
out = os.path.join(HERE, "campus_map_editor.html")
io.open(out, "w", encoding="utf-8", newline="\n").write(html)
print("written", out, len(html.encode("utf-8")), "bytes")
