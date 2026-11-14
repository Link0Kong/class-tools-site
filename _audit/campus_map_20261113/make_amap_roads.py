# -*- coding: utf-8 -*-
"""把 AMap 重描的道路（master 像素坐标）反变换到现有模型坐标，生成 roads_amap.json。"""
import io
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
AMAP = os.path.join(HERE, "_data", "amap")
fit = json.load(io.open(os.path.join(AMAP, "_work2", "anchor_fit.json"), encoding="utf-8"))
M = np.array(fit["model_to_master_affine"], dtype=float)  # model -> master
Mi = np.linalg.inv(np.vstack([M, [0, 0, 1]]))[:2]
paths = json.load(io.open(os.path.join(AMAP, "_work", "traced_paths.json"), encoding="utf-8"))

MAIN = {"修园西路", "修园北路", "修园东路", "望果西路", "望果东路", "银杏西路",
        "银杏东路", "仲景路", "杏林大道", "学府北路"}
WIDTH = {
    "修园西路": 5.5, "修园北路": 5.5, "修园东路": 5.5, "望果西路": 5.5, "望果东路": 5.0,
    "银杏西路": 5.0, "银杏东路": 5.0, "仲景路": 5.0, "杏林大道": 5.5,
    "仲景西路": 4.0, "仲景东路": 4.5, "学府北路": 6.0,
}

roads = []
seen = {}
for idx, (name, obj) in enumerate(paths.items()):
    pts = obj.get("simplified") if isinstance(obj, dict) else obj
    if not pts:
        continue
    out = []
    for u, v in pts:
        x, y = Mi @ np.array([float(u), float(v), 1.0])
        out.append([round(float(x) * 10) / 10, round(float(y) * 10) / 10])
    # 去掉连续重复点
    clean = []
    for p in out:
        if not clean or abs(p[0] - clean[-1][0]) + abs(p[1] - clean[-1][1]) > 1.0:
            clean.append(p)
    if len(clean) < 2:
        continue
    rid = "A%02d" % (idx + 1)
    seen[rid] = name
    roads.append({"id": rid, "name": name, "w": WIDTH.get(name, 4.5), "p": clean})

out = {"model_to_master": M.tolist(), "roads": roads}
io.open(os.path.join(AMAP, "..", "roads_amap.json"), "w", encoding="utf-8").write(
    json.dumps(out, ensure_ascii=False, indent=1))
print("roads", len(roads))
for r in roads:
    print(r["id"], r["name"], len(r["p"]), r["w"], "start", r["p"][0], "end", r["p"][-1])
