# -*- coding: utf-8 -*-
"""r19: label(icon) -> extracted component assignment, then name->old unit map."""
import os, json, math
import cv2, numpy as np
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
DATA = os.path.dirname(AMAP)
WORK = os.path.join(AMAP, "_work2")
raw = json.load(open(os.path.join(WORK, "extract_raw.json"), encoding="utf-8"))
old = json.load(open(os.path.join(DATA, "preview_data.json"), encoding="utf-8"))
fit = json.load(open(os.path.join(WORK, "anchor_fit.json"), encoding="utf-8"))
A = np.array(fit["model_to_master_affine"], float)
S = fit["equivalent_scale"]
bld = {b["id"]: b for b in old["buildings"]}
feat = {f["id"]: f for f in old["features"]}

# ---- labels read from montage sheets ----
LABELS = [
    ("23号楼", 1251, 743), ("名师苑25号楼", 1369, 800), ("修园楼", 2564, 846),
    ("实验动物中心", 2468, 939), ("7号楼", 1835, 1118), ("后勤管理处", 2346, 1131),
    ("求真楼", 2510, 1182), ("五行楼", 1849, 1200), ("6号楼", 2427, 1287),
    ("体育部", 348, 1392), ("至善楼", 1787, 1400), ("精诚楼", 1296, 1402),
    ("康复产业研究院", 910, 1409), ("体育馆", 431, 1442),
    ("自强楼", 1713, 1662), ("厚德楼", 1029, 1676), ("学生活动中心", 547, 1800),
    ("明德楼", 1884, 2066), ("图书馆", 1253, 2154), ("体育教研部", 2339, 2158),
    ("融媒体中心", 552, 2527), ("成人教育学院", 1340, 2824), ("学生服务中心", 916, 2895),
    ("16号楼", 792, 2914), ("青年广场", 1680, 3257),
]
# plain-text dorm labels (read from v_dorm1/v_dorm2 crops; text centre coordinates)
DORM_TEXT = [
    ("21号楼", 433, 2112), ("20号楼", 445, 2235), ("18号楼", 375, 2383),
    ("19号楼", 575, 2381), ("17号楼", 430, 2521), ("11号楼", 447, 2647),
    ("12号楼", 669, 2644), ("13号楼", 456, 2779), ("14号楼", 773, 2756),
    ("15号楼", 533, 2911),
]
LABELS = LABELS + DORM_TEXT

COMPLEX = {
    "B20": ["B20", "B21", "B22", "B23"], "B24": ["B24", "B25", "B26", "B27"],
    "B28": ["B28", "B29", "B30", "B31"], "B32": ["B32", "B33", "B34", "B35"],
    "B36": ["B36", "B37", "B38", "B39"], "B40": ["B40", "B41", "B42", "B43"],
    "B44": ["B44", "B45", "B46", "B47"], "B60": ["B60", "B61", "B62", "B63"],
    "B64": ["B64", "B65"], "B50": ["B50", "B51"], "B81": ["B81", "B82", "B83", "B84", "B85"],
}
used = set()
units = []
for head, ids in COMPLEX.items():
    used |= set(ids); units.append({"head": head, "ids": ids})
for b in old["buildings"]:
    if b["id"] not in used:
        units.append({"head": b["id"], "ids": [b["id"]]})
for u in units:
    u["model_center"] = np.array([[bld[i]["x"], bld[i]["y"]] for i in u["ids"]]).mean(0)
    u["model_area"] = sum(Polygon(feat[i]["p"]).area for i in u["ids"] if i in feat)
    u["names"] = sorted({bld[i]["n"] for i in u["ids"]})
    u["display"] = bld[u["ids"][0]]["ln"]
    u["master_center"] = (u["model_center"] @ A[:, :2].T + A[:, 2])
unit_by_head = {u["head"]: u for u in units}
NAME2UNIT = {
    "图书馆": "B50", "厚德楼": "B20", "精诚楼": "B28", "至善楼": "B36",
    "五行楼": "B32", "自强楼": "B40", "明德楼": "B59", "求真楼": "B60",
    "修园楼": "B66", "实验动物中心": "B64", "康复产业研究院": "B24",
    "学生活动中心": "B04", "体育馆": "B70", "名师苑25号楼": "B81",
    "23号楼": "B81",
}

comps = []
for k, c in enumerate(raw["buildings"]):
    poly = Polygon(c["points"])
    if not poly.is_valid:
        poly = poly.buffer(0)
    comps.append({"k": k, "poly": poly, "centroid": np.array([c["cx"], c["cy"]]),
                  "area": poly.area, "bbox": c["bbox"], "points": c["points"]})

print("%-3s %-10s %-8s %-30s %s" % ("idx", "name", "dist", "component bbox/centroid/area", "old unit"))
assign = {}
for name, mx, my in LABELS:
    pt = Point(mx, my)
    inside = [ci for ci, c in enumerate(comps) if c["poly"].contains(pt)]
    if inside:
        ci = min(inside, key=lambda k: comps[k]["area"])  # smallest containing
        d = 0.0
    else:
        ds = [(c["poly"].distance(pt), ci) for ci, c in enumerate(comps)]
        ds.sort()
        d, ci = ds[0]
    c = comps[ci]
    head = NAME2UNIT.get(name)
    info = "%-28s c=(%4d,%4d) a=%6d" % (str(c["bbox"]), c["centroid"][0], c["centroid"][1], c["area"])
    print("%-3d %-10s %-8.1f %-30s %s" % (ci, name, d, info, head or ""))
    if head is not None:
        assign.setdefault(ci, []).append((name, head, d))

print("\ncomponent assignments:")
for ci, lst in sorted(assign.items()):
    print("  comp %d -> %s" % (ci, lst))

json.dump({"assign": {str(k): v for k, v in assign.items()},
           "labels": LABELS,
           "units": [{"head": u["head"], "ids": u["ids"], "names": u["names"], "display": u["display"],
                      "master_center": u["master_center"].tolist(),
                      "model_area": u["model_area"]} for u in units]},
          open(os.path.join(WORK, "label_assign.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
