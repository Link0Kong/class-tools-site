# -*- coding: utf-8 -*-
"""把 AMap 重描的建筑/水面/绿地（master 像素）反变换到现有模型坐标，生成 AMap 版数据。"""
import io
import json
import os
import shutil

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "_data")
AMAP = os.path.join(D, "amap")

old = json.load(io.open(os.path.join(D, "preview_data.json"), encoding="utf-8"))
bt = json.load(io.open(os.path.join(AMAP, "buildings_trace.json"), encoding="utf-8"))
ft = json.load(io.open(os.path.join(AMAP, "features_trace.json"), encoding="utf-8"))
roads = json.load(io.open(os.path.join(D, "roads_amap.json"), encoding="utf-8"))["roads"]

M = np.array(bt["model_to_master"], dtype=float)  # model -> master
Mi = np.linalg.inv(np.vstack([M, [0, 0, 1]]))[:2]  # master -> model


def inv(pts):
    out = []
    for u, v in pts:
        x, y = Mi @ np.array([float(u), float(v), 1.0])
        out.append([round(float(x) * 10) / 10, round(float(y) * 10) / 10])
    return out


old_b = {b["id"]: b for b in old["buildings"]}
new_b = []
for i, b in enumerate(bt["buildings"]):
    p = inv(b["points"])
    if len(p) < 3:
        continue
    xs = [q[0] for q in p]; ys = [q[1] for q in p]
    cx = round(sum(xs) / len(xs), 1); cy = round(sum(ys) / len(ys), 1)
    oid = b.get("id") or ""
    ob = old_b.get(oid)
    if ob and b.get("confidence", 0) >= 0.18:
        nb = dict(ob)
        nb["p"] = p; nb["x"] = cx; nb["y"] = cy
    else:
        oid = "G%02d" % (i + 1)
        nb = {"id": oid, "n": "建筑", "ln": "建筑", "no": "", "k": "其他", "g": "civic",
              "h": 12.0, "fl": 4, "lb": 0, "u": "", "p": p, "x": cx, "y": cy}
    new_b.append(nb)

# 保留旧数据里有、AMap 没描到的关键建筑（博物馆/看台等），避免功能缺失
have = {b["id"] for b in new_b}
for keep in ("MUS",):
    if keep not in have:
        p = [[500, 414], [546, 414], [546, 446], [500, 446]]
        new_b.append({"id": "MUS", "n": "博物馆", "ln": "博物馆", "no": "", "k": "图书馆",
                      "g": "civic", "h": 12.5, "fl": 2, "lb": 1, "u": "", "p": p,
                      "x": 523, "y": 430})

features = []
for k in ("water", "island", "lawn", "plaza"):
    for i, poly in enumerate(ft.get(k, [])):
        p = inv(poly.get("points", []) if isinstance(poly, dict) else poly)
        if len(p) >= 3:
            features.append({"id": "%s_%02d" % (k, i + 1), "k": k, "t": "polygon", "g": "", "p": p})
for b in new_b:
    features.append({"id": b["id"], "k": "bld", "t": "polygon", "g": b["g"], "p": b["p"]})

data = dict(old)
data["features"] = features
data["buildings"] = new_b
data["roads"] = roads
data["src"] = ("建筑轮廓/道路/水系：按用户提供 AMap 三图重描（OpenStreetMap/AMap 参考）；"
               "楼名/楼栋号：手绘图+实景照片；坐标已由 master 像素反变换到模型系")
shutil.copyfile(os.path.join(D, "preview_data.json"), os.path.join(D, "preview_data_v5_backup.json"))
io.open(os.path.join(D, "preview_data.json"), "w", encoding="utf-8").write(
    json.dumps(data, ensure_ascii=False, separators=(",", ":")))
print("buildings", len(new_b), "features", len(features), "roads", len(roads),
      "water", sum(1 for f in features if f["k"] == "water"))
