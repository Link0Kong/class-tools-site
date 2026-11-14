# -*- coding: utf-8 -*-
"""r17: label-identified correspondences + ICP refinement of the affine.

Readable AMap label inventory (from montage sheets) is used to pair old-model
building groups with the extracted AMap footprints; the affine is then
least-squares refit on (old centre -> footprint centroid) pairs, iterated.
"""
import os, json, math
import cv2, numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
DATA = os.path.dirname(AMAP)
WORK = os.path.join(AMAP, "_work2")
raw = json.load(open(os.path.join(WORK, "extract_raw.json"), encoding="utf-8"))
old = json.load(open(os.path.join(DATA, "preview_data.json"), encoding="utf-8"))
fit = json.load(open(os.path.join(WORK, "anchor_fit.json"), encoding="utf-8"))
A0 = np.array(fit["model_to_master_affine"], float)
bld = {b["id"]: b for b in old["buildings"]}
feat = {f["id"]: f for f in old["features"]}

# ---------- units ----------
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
    if b["id"] in used:
        continue
    units.append({"head": b["id"], "ids": [b["id"]]})
for u in units:
    u["model_center"] = np.array([[bld[i]["x"], bld[i]["y"]] for i in u["ids"]]).mean(0)
    u["model_area"] = sum(Polygon(feat[i]["p"]).area for i in u["ids"] if i in feat)
    u["names"] = sorted({bld[i]["n"] for i in u["ids"]})
    u["display"] = bld[u["ids"][0]]["ln"]
unit_by_name = {}
for u in units:
    for i in u["ids"]:
        unit_by_name.setdefault(bld[i]["n"], u)
        unit_by_name.setdefault(bld[i]["ln"], u)

# ---------- readable AMap labels ----------
LABELS = [
    ("联心村老人会", 463, 205), ("P", 2781, 421), ("23号楼", 1251, 743),
    ("名师苑25号楼", 1369, 800), ("修园楼", 2564, 846), ("P", 805, 915),
    ("实验动物中心", 2468, 939), ("7号楼", 1835, 1118), ("后勤管理处", 2346, 1131),
    ("求真楼", 2510, 1182), ("五行楼", 1849, 1200), ("6号楼", 2427, 1287),
    ("体育部", 348, 1392), ("至善楼", 1787, 1400), ("精诚楼", 1296, 1402),
    ("康复产业研究院", 910, 1409), ("体育馆", 431, 1442), ("教学区", 2619, 1525),
    ("自强楼", 1713, 1662), ("厚德楼", 1029, 1676), ("学生活动中心", 547, 1800),
    ("P", 1960, 1826), ("P", 2909, 1893), ("明德楼", 1884, 2066), ("图书馆", 1253, 2154),
    ("体育教研部", 2339, 2158), ("融媒体中心", 552, 2527), ("P", 887, 2649),
    ("P", 2432, 2708), ("成人教育学院", 1340, 2824), ("上街校区四号岗亭", 2354, 2833),
    ("P", 1455, 2862), ("P", 1286, 2890), ("学生服务中心", 916, 2895), ("16号楼", 792, 2914),
    ("易班工作站", 2356, 3213), ("青年广场", 1680, 3257), ("校报记者团", 1499, 3336),
]
# name -> old unit
NAME2UNIT = {
    "图书馆": "B50", "厚德楼": "B20", "精诚楼": "B28", "至善楼": "B36",
    "五行楼": "B32", "自强楼": "B40", "明德楼": "B59", "求真楼": "B60",
    "修园楼": "B66", "实验动物中心": "B64", "康复产业研究院": "B24",
    "学生活动中心": "B04", "体育馆": "B70", "名师苑25号楼": "B81",
}
unit_by_head = {u["head"]: u for u in units}

# components (raw dicts with shapely polygon)
comps = []
for k, c in enumerate(raw["buildings"]):
    poly = Polygon(c["points"])
    if not poly.is_valid:
        poly = poly.buffer(0)
    comps.append({"k": k, "poly": poly, "centroid": np.array([c["cx"], c["cy"]]),
                  "area": poly.area, "bbox": c["bbox"]})


def apply(M, P):
    P = np.atleast_2d(np.asarray(P, float))
    return P @ M[:, :2].T + M[:, 2]


def fit_affine(P, Q, w=None):
    n = len(P)
    Amat = np.zeros((2 * n, 6)); b = np.zeros(2 * n)
    Amat[0::2, 0] = P[:, 0]; Amat[0::2, 1] = P[:, 1]; Amat[0::2, 4] = 1; b[0::2] = Q[:, 0]
    Amat[1::2, 2] = P[:, 0]; Amat[1::2, 3] = P[:, 1]; Amat[1::2, 5] = 1; b[1::2] = Q[:, 1]
    if w is not None:
        ww = np.repeat(np.sqrt(w), 2)
        Amat = Amat * ww[:, None]; b = b * ww
    sol, *_ = np.linalg.lstsq(Amat, b, rcond=None)
    return np.array([[sol[0], sol[1], sol[4]], [sol[2], sol[3], sol[5]]])


# initial label-based pairs using current transform
M = A0.copy()
pairs = []   # (unit head, comp idx)
for name, mx, my in LABELS:
    head = NAME2UNIT.get(name)
    if head is None:
        continue
    u = unit_by_head[head]
    ctr = apply(M, u["model_center"])[0]
    # find component whose polygon contains the label point, else nearest centroid
    best = None; bd = 1e9
    for ci, c in enumerate(comps):
        d = math.hypot(*(c["centroid"] - np.array([mx, my])))
        contains = c["poly"].contains(__import__("shapely").geometry.Point(mx, my))
        score = d - (60 if contains else 0)
        if score < bd:
            bd = score; best = ci
    pairs.append((head, best))
print("initial label pairs:", [(p[0], p[1]) for p in pairs])

for it in range(6):
    P, Q, W, used_heads = [], [], [], set()
    for head, ci in pairs:
        u = unit_by_head[head]
        P.append(u["model_center"]); Q.append(comps[ci]["centroid"]); W.append(1.0)
        used_heads.add(head)
    P = np.array(P); Q = np.array(Q); W = np.array(W)
    M = fit_affine(P, Q, W)
    # re-pair: nearest component (allow contains bonus) to projected unit centre
    newpairs = []
    for (name, mx, my), (head, ci_old) in zip([(a, b, c) for a in LABELS for b in []], []):
        pass
    newpairs = []
    for name, mx, my in LABELS:
        head = NAME2UNIT.get(name)
        if head is None:
            continue
        u = unit_by_head[head]
        ctr = apply(M, u["model_center"])[0]
        d = np.array([np.linalg.norm(c["centroid"] - ctr) for c in comps])
        # bonus for containing the actual label point
        from shapely.geometry import Point
        for ci, c in enumerate(comps):
            if c["poly"].contains(Point(mx, my)):
                d[ci] -= 80
        ci = int(np.argmin(d))
        newpairs.append((head, ci))
    if newpairs == pairs:
        print("pairs converged at iter", it)
    pairs = newpairs
    res = np.linalg.norm(apply(M, P) - Q, axis=1)
    print("iter %d pairs=%d residual mean %.2f max %.2f" % (it, len(pairs), res.mean(), res.max()))

M = fit_affine(np.array([unit_by_head[h]["model_center"] for h, _ in pairs]),
               np.array([comps[c]["centroid"] for _, c in pairs]))
print("\nrefined affine:\n", np.round(M, 5))
det = M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]
S = math.sqrt(abs(det))
print("scale %.5f rot %.3f deg det %.4f" % (S, math.degrees(math.atan2(M[1, 0], M[0, 0])), det))

# final label-anchor residual with refined matrix (icon positions vs projected unit centre)
lab_pts = []
for name, mx, my in LABELS:
    head = NAME2UNIT.get(name)
    if head is None:
        continue
    u = unit_by_head[head]
    pr = apply(M, u["model_center"])[0]
    lab_pts.append((name, mx, my, pr, math.hypot(pr[0] - mx, pr[1] - my)))
print("\nlabel residual under refined matrix:")
for name, mx, my, pr, r in lab_pts:
    print("  %-10s icon=(%7.1f,%7.1f) proj=(%7.1f,%7.1f) resid=%5.1f" % (name, mx, my, pr[0], pr[1], r))
r = np.array([x[4] for x in lab_pts])
print("label residual: mean %.2f median %.2f p95 %.2f max %.2f" % (r.mean(), np.median(r), np.percentile(r, 95), r.max()))

json.dump({
    "model_to_master": M.tolist(),
    "equivalent_scale": S,
    "pairs": [{"head": h, "comp": int(c), "unit_center": unit_by_head[h]["model_center"].tolist(),
               "comp_centroid": comps[c]["centroid"].tolist()} for h, c in pairs],
    "icp_residual": {"mean": float(np.linalg.norm(apply(M, np.array([unit_by_head[h]["model_center"] for h, _ in pairs])) -
                                                  np.array([comps[c]["centroid"] for _, c in pairs]), axis=1).mean())},
    "label_residual": {"mean": float(r.mean()), "median": float(np.median(r)),
                       "p95": float(np.percentile(r, 95)), "max": float(r.max()),
                       "list": [{"name": n, "icon": [mx, my], "proj": pr.tolist(), "resid": rr}
                                for n, mx, my, pr, rr in lab_pts]},
}, open(os.path.join(WORK, "refine_fit.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved refine_fit.json")
