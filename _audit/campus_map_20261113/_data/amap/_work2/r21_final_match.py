# -*- coding: utf-8 -*-
"""r21: final building matching.

1) label(AMap POI icon) -> component -> old unit  (high confidence)
2) geometric matching for the rest: nearest old unit centre + area ratio + overlap
3) write match result + check image (for review)
"""
import os, json, math
import cv2, numpy as np
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from scipy.optimize import linear_sum_assignment

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
DATA = os.path.dirname(AMAP)
WORK = os.path.join(AMAP, "_work2")
raw = json.load(open(os.path.join(WORK, "extract_raw2.json"), encoding="utf-8"))
old = json.load(open(os.path.join(DATA, "preview_data.json"), encoding="utf-8"))
fit = json.load(open(os.path.join(WORK, "anchor_fit.json"), encoding="utf-8"))
A = np.array(fit["model_to_master_affine"], float)
S = fit["equivalent_scale"]
bld = {b["id"]: b for b in old["buildings"]}
feat = {f["id"]: f for f in old["features"]}

# ---------------- units ----------------
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
    used |= set(ids)
    units.append({"head": head, "ids": ids})
for b in old["buildings"]:
    if b["id"] not in used:
        units.append({"head": b["id"], "ids": [b["id"]]})
for u in units:
    u["model_center"] = np.array([[bld[i]["x"], bld[i]["y"]] for i in u["ids"]]).mean(0)
    u["model_area"] = sum(Polygon(feat[i]["p"]).area for i in u["ids"] if i in feat)
    u["master_center"] = u["model_center"] @ A[:, :2].T + A[:, 2]
    u["geom"] = unary_union([Polygon(feat[i]["p"] @ A[:, :2].T + A[:, 2]) for i in u["ids"] if i in feat])
    u["names"] = sorted({bld[i]["n"] for i in u["ids"]})
    u["display"] = bld[u["ids"][0]]["ln"]
    u["px_area"] = u["model_area"] * S * S
unit_by_head = {u["head"]: u for u in units}
NAME2UNIT = {
    "图书馆": "B50", "厚德楼": "B20", "精诚楼": "B28", "至善楼": "B36",
    "五行楼": "B32", "自强楼": "B40", "明德楼": "B59", "求真楼": "B60",
    "修园楼": "B66", "实验动物中心": "B64", "康复产业研究院": "B24",
    "学生活动中心": "B04", "体育馆": "B70", "名师苑25号楼": "B81",
}
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

# ---------------- components ----------------
comps = []
for k, c in enumerate(raw["buildings"]):
    poly = Polygon(c["points"])
    if not poly.is_valid:
        poly = poly.buffer(0)
    comps.append({"k": k, "poly": poly, "centroid": np.array([c["cx"], c["cy"]]),
                  "area": poly.area, "bbox": c["bbox"], "points": c["points"]})
print("components", len(comps))

# ---------------- campus clip ----------------
s01 = Polygon(feat["S01"]["p"] @ A[:, :2].T + A[:, 2])
campus = s01.buffer(40)
for c in comps:
    inter = c["poly"].intersection(campus).area
    c["in_campus"] = bool(c["poly"].representative_point().within(campus) or inter > 0.5 * c["area"])
nin = sum(1 for c in comps if c["in_campus"])
print("in campus:", nin, "outside:", len(comps) - nin, " campus bounds", campus.bounds)

# ---------------- label matching ----------------
label_matches = {}   # comp index -> list of (label, head, dist, where)
for name, mx, my in LABELS:
    head = NAME2UNIT.get(name)
    if head is None:
        continue
    pt = Point(mx, my)
    inside = [ci for ci, c in enumerate(comps) if c["poly"].contains(pt)]
    if inside:
        ci = min(inside, key=lambda k: comps[k]["area"])
        d = 0.0; how = "inside"
    else:
        ds = sorted([(c["poly"].distance(pt), ci) for ci, c in enumerate(comps)])
        d, ci = ds[0]; how = "near"
        if d > 60:
            print("  label %-12s too far from any footprint (%.0f px) - skipped" % (name, d))
            continue
    label_matches.setdefault(ci, []).append((name, head, d, how))

print("\nlabel matches:")
for ci, lst in sorted(label_matches.items()):
    print("  comp %3d area=%7d c=(%5.0f,%5.0f) -> %s" % (ci, comps[ci]["area"], comps[ci]["centroid"][0],
                                                          comps[ci]["centroid"][1], lst))

# ---------------- geometric matching (remaining) ----------------
label_comp = set(label_matches.keys())
label_units = set(h for lst in label_matches.values() for _, h, _, _ in lst)
rem_comps = [ci for ci in range(len(comps)) if ci not in label_comp and comps[ci]["in_campus"]]
rem_units = [u for u in units if u["head"] not in label_units]
print("\ngeometric: %d components vs %d units" % (len(rem_comps), len(rem_units)))

DIST_MAX = 230.0
cm = np.full((len(rem_comps), len(rem_units)), 4000.0)
det = {}
for i, ci in enumerate(rem_comps):
    c = comps[ci]
    for j, u in enumerate(rem_units):
        d = float(np.linalg.norm(c["centroid"] - u["master_center"]))
        ar = (c["area"] / (S * S)) / u["model_area"] if u["model_area"] > 0 else 99
        try:
            inter = c["poly"].intersection(u["geom"]).area
        except Exception:
            inter = 0.0
        cov = inter / c["area"] if c["area"] > 0 else 0.0
        cov_u = inter / u["geom"].area if u["geom"].area > 0 else 0.0
        ok = (d <= DIST_MAX) and (0.30 <= ar <= 3.2) and (cov > 0.10)
        cost = d + 180.0 * (1.0 - min(cov, 1.0)) + 70.0 * abs(math.log(max(ar, 1e-9)))
        if not ok:
            cost = 4000.0
        cm[i, j] = cost
        det[(i, j)] = dict(dist=d, area_ratio=ar, cov=cov, cov_u=cov_u, ok=ok)
dummy = np.full((len(rem_comps), len(rem_comps)), 1200.0)
for i in range(len(rem_comps)):
    dummy[i, i] = 300.0
CM = np.hstack([cm, dummy])
ri, ci2 = linear_sum_assignment(CM)
geom_assign = {}
for i, j in zip(ri, ci2):
    if j < len(rem_units) and CM[i, j] < 1000.0:
        geom_assign[rem_comps[i]] = (rem_units[j], det[(i, j)])

# ---------------- assemble rows ----------------
rows = []
wing_used = {}
for ci in range(len(comps)):
    c = comps[ci]
    if ci in label_matches:
        lst = label_matches[ci]
        # choose head with shortest label distance; extend to multiple wings if needed
        lst_sorted = sorted(lst, key=lambda t: t[2])
        name, head, d, how = lst_sorted[0]
        u = unit_by_head[head]
        wings = []
        for nid in u["ids"]:
            wp = np.array([bld[nid]["x"], bld[nid]["y"]]) @ A[:, :2].T + A[:, 2]
            wings.append((float(np.linalg.norm(c["centroid"] - wp)), nid))
        wings.sort()
        # pick first not already used by another component of the same unit
        pick = None
        for dd, nid in wings:
            if (u["head"], nid) not in wing_used:
                pick = (dd, nid); break
        if pick is None:
            pick = wings[0]
        _, wid = pick
        wing_used[(u["head"], wid)] = ci
        # sanity: compare with nearest wing footprint area
        wpoly = Polygon(feat[wid]["p"] @ A[:, :2].T + A[:, 2])
        ar = c["area"] / wpoly.area if wpoly.area > 0 else 0
        shape_pen = 1.0 if 0.25 <= ar <= 4.0 else 0.6
        conf = (0.94 if how == "inside" else 0.86) * shape_pen
        rows.append({"comp": ci, "id": wid, "confidence": round(float(conf), 3), "how": "label:" + how,
                     "dist": d, "area_ratio": ar, "cov": 1.0, "labels": [x[0] for x in lst]})
    elif ci in geom_assign:
        u, dd = geom_assign[ci]
        wings = []
        for nid in u["ids"]:
            wp = np.array([bld[nid]["x"], bld[nid]["y"]]) @ A[:, :2].T + A[:, 2]
            wings.append((float(np.linalg.norm(c["centroid"] - wp)), nid))
        wings.sort()
        wid = wings[0][1]
        conf = math.exp(-dd["dist"] / 90.0) * min(1.0, 0.25 + 0.75 * min(dd["cov"], 1.0)) \
            * min(1.0, max(dd["area_ratio"], 1.0 / max(dd["area_ratio"], 1e-9)))
        rows.append({"comp": ci, "id": wid, "confidence": round(float(conf), 3), "how": "geom",
                     "dist": dd["dist"], "area_ratio": dd["area_ratio"], "cov": dd["cov"], "labels": []})
    else:
        rows.append({"comp": ci, "id": None, "confidence": 0.0, "how": "generic",
                     "dist": None, "area_ratio": None, "cov": None, "labels": []})

nm = sum(1 for r in rows if r["id"])
print("\nmatched %d / %d components (campus %d)" % (nm, len(rows), nin))
print("\nlabel rows:")
for r in sorted(rows, key=lambda r: (r["how"].startswith("generic"), r["how"])):
    c = comps[r["comp"]]
    print("  comp %3d %-4s conf=%.2f how=%-12s c=(%5.0f,%5.0f) area=%7d bbox=%s labels=%s" % (
        r["comp"], r["id"], r["confidence"], r["how"], c["centroid"][0], c["centroid"][1],
        c["area"], c["bbox"], r["labels"]))
print("\ngeneric components:")
for r in rows:
    if not r["id"]:
        c = comps[r["comp"]]
        print("  comp %3d area=%7d c=(%5.0f,%5.0f) bbox=%s campus=%s" % (
            r["comp"], c["area"], c["centroid"][0], c["centroid"][1], c["bbox"], c["in_campus"]))

json.dump({"rows": rows, "comps": [{"centroid": c["centroid"].tolist(), "area": c["area"],
                                    "bbox": c["bbox"], "in_campus": c["in_campus"],
                                    "points": c["points"]} for c in comps]},
          open(os.path.join(WORK, "match_pass2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---------------- visual ----------------
im = cv2.imread(os.path.join(AMAP, "master.png"))
vis = im.copy()
for r in rows:
    c = comps[r["comp"]]
    pts = np.array(c["points"], np.int32)
    if r["id"]:
        col = (0, 0, 255) if r["how"].startswith("label") else (0, 140, 255)
        cv2.polylines(vis, [pts], True, col, 2)
        cv2.putText(vis, "%s %.2f" % (r["id"], r["confidence"]),
                    (int(c["centroid"][0]) - 22, int(c["centroid"][1])),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2, cv2.LINE_AA)
    else:
        cv2.polylines(vis, [pts], True, (180, 180, 180), 1)
cv2.polylines(vis, [np.array(feat["S01"]["p"], np.float64) @ A[:, :2].T + A[:, 2]].astype(np.int32),
              True, (0, 220, 0), 2)
cv2.imwrite(os.path.join(WORK, "d_match2.png"),
            cv2.resize(vis, (1600, int(im.shape[0] * 1600.0 / im.shape[1])), interpolation=cv2.INTER_AREA))
print("\nsaved match_pass2.json / d_match2.png")
