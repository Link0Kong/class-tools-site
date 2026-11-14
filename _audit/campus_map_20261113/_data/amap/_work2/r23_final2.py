# -*- coding: utf-8 -*-
"""r23: final v2 - add sibling-wing assignment for label-matched complexes,
write buildings_trace.json / features_trace.json / check images + stats json.
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
W, H = raw["master_size"]

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
    u["model_center"] = np.array([[bld[i]["x"], bld[i]["y"]] for i in u["ids"]]) .mean(0)
    u["model_area"] = sum(Polygon(feat[i]["p"]).area for i in u["ids"] if i in feat)
    u["master_center"] = u["model_center"] @ A[:, :2].T + A[:, 2]
    u["geom"] = unary_union([Polygon(feat[i]["p"] @ A[:, :2].T + A[:, 2]) for i in u["ids"] if i in feat])
    u["wing_master"] = {i: (np.array([bld[i]["x"], bld[i]["y"]]) @ A[:, :2].T + A[:, 2]) for i in u["ids"]}
    u["wing_px_area"] = {i: Polygon(feat[i]["p"]).area * S * S for i in u["ids"] if i in feat}
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
P_LABELS = [(2781, 421), (805, 915), (1960, 1826), (2909, 1893), (887, 2649),
            (2432, 2708), (1455, 2862), (1286, 2890)]

comps = []
for k, c in enumerate(raw["buildings"]):
    poly = Polygon(c["points"])
    if not poly.is_valid:
        poly = poly.buffer(0)
    comps.append({"k": k, "poly": poly, "centroid": np.array([c["cx"], c["cy"]]),
                  "area": poly.area, "bbox": c["bbox"], "points": c["points"],
                  "min_side": c["min_side"], "max_side": c["max_side"]})
s01 = Polygon(feat["S01"]["p"] @ A[:, :2].T + A[:, 2])
campus = s01.buffer(40)
for c in comps:
    c["in_campus"] = bool(c["poly"].representative_point().within(campus) or
                          c["poly"].intersection(campus).area > 0.5 * c["area"])

# ---------------- label matching ----------------
label_hits = {}
for name, mx, my in LABELS:
    head = NAME2UNIT.get(name)
    if head is None:
        continue
    pt = Point(mx, my)
    inside = [ci for ci, c in enumerate(comps) if c["poly"].contains(pt)]
    if inside:
        ci = min(inside, key=lambda k: comps[k]["area"]); d, how = 0.0, "inside"
    else:
        ds = sorted([(c["poly"].distance(pt), ci) for ci, c in enumerate(comps)])
        d, ci = ds[0]; how = "near"
        if d > 60:
            continue
    label_hits.setdefault(ci, []).append((name, head, d, how))

label_comp = set(label_hits)
label_units = set(h for lst in label_hits.values() for _, h, _, _ in lst)
rem_c = [ci for ci in range(len(comps)) if ci not in label_comp and comps[ci]["in_campus"]]
rem_u = [u for u in units if u["head"] not in label_units]
cm = np.full((len(rem_c), len(rem_u)), 4000.0); det = {}
for i, ci in enumerate(rem_c):
    c = comps[ci]
    for j, u in enumerate(rem_u):
        d = float(np.linalg.norm(c["centroid"] - u["master_center"]))
        ar = (c["area"] / (S * S)) / u["model_area"] if u["model_area"] > 0 else 99
        try:
            cov = c["poly"].intersection(u["geom"]).area / c["area"]
        except Exception:
            cov = 0.0
        ok = (d <= 230.0) and (0.30 <= ar <= 3.2) and (cov > 0.10)
        cm[i, j] = (d + 180.0 * (1.0 - min(cov, 1.0)) + 70.0 * abs(math.log(max(ar, 1e-9)))) if ok else 4000.0
        det[(i, j)] = (d, ar, cov, ok)
dummy = np.full((len(rem_c), len(rem_c)), 1200.0)
for i in range(len(rem_c)):
    dummy[i, i] = 300.0
ri, cj = linear_sum_assignment(np.hstack([cm, dummy]))
geom_hits = {}
for i, j in zip(ri, cj):
    if j < len(rem_u) and cm[i, j] < 1000.0:
        geom_hits[rem_c[i]] = (rem_u[j], det[(i, j)])

comp_unit, comp_conf, comp_how, comp_extra = {}, {}, {}, {}
for ci, lst in label_hits.items():
    name, head, d, how = sorted(lst, key=lambda t: t[2])[0]
    comp_unit[ci] = head
    comp_how[ci] = "label:" + how
    comp_conf[ci] = 0.94 if how == "inside" else 0.86
for ci, (u, (d, ar, cov, ok)) in geom_hits.items():
    conf = math.exp(-d / 90.0) * min(1.0, 0.25 + 0.75 * min(cov, 1.0)) * \
        min(1.0, max(ar, 1.0 / max(ar, 1e-9)))
    if conf < 0.20:
        continue
    comp_unit[ci] = u["head"]; comp_conf[ci] = round(float(conf), 3); comp_how[ci] = "geom"
    comp_extra[ci] = {"dist": round(d, 1), "area_ratio": round(ar, 3), "coverage": round(cov, 3)}

# ---------------- sibling wings for label-matched complexes ----------------
def upx(w):
    return Polygon(feat[w]["p"]).area * S * S
sib = 0
SIBLING_UNITS = {"B81"}   # 名师苑: old model has 5 separate houses, AMap shows separate footprints
for head in label_units:
    u = unit_by_head[head]
    if len(u["ids"]) < 2 or head not in SIBLING_UNITS:
        continue
    for ci, c in enumerate(comps):
        if ci in comp_unit or not c["in_campus"]:
            continue
        if c["max_side"] / max(c["min_side"], 1e-6) > 7.0 and c["max_side"] > 150:
            continue
        # nearest unused wing
        cand = sorted(((float(np.linalg.norm(c["centroid"] - u["wing_master"][w])), w) for w in u["ids"]))
        dd, w = cand[0]
        if dd > 190:
            continue
        ar = c["area"] / upx(w) if upx(w) > 0 else 99
        if not (0.20 <= ar <= 5.0):
            continue
        comp_unit[ci] = head; comp_conf[ci] = 0.55; comp_how[ci] = "label:sibling"
        comp_extra[ci] = {"dist": round(dd, 1), "area_ratio": round(ar, 3), "coverage": None}
        sib += 1
print("sibling assignments:", sib)

# ---------------- wing ids ----------------
by_unit = {}
for ci, head in comp_unit.items():
    by_unit.setdefault(head, []).append(ci)
comp_id = {}
for head, cis in by_unit.items():
    u = unit_by_head[head]
    if len(cis) == 1:
        comp_id[cis[0]] = head
    else:
        free = list(u["ids"])
        for ci in sorted(cis, key=lambda c: np.linalg.norm(comps[c]["centroid"] - u["master_center"])):
            cand = sorted(free, key=lambda nid: np.linalg.norm(comps[ci]["centroid"] - u["wing_master"][nid]))
            comp_id[ci] = cand[0]
            if cand:
                free.remove(cand[0])
            if not free:
                free = list(u["ids"])

# ---------------- parking / paved ----------------
parking = set()
for (px, py) in P_LABELS:
    best, bd = None, 1e9
    for ci, c in enumerate(comps):
        if ci in comp_unit or not c["in_campus"]:
            continue
        d = math.hypot(c["centroid"][0] - px, c["centroid"][1] - py)
        if d < bd:
            bd, best = d, ci
    if best is not None and bd < 130:
        parking.add(best)
bar_like = set()
for ci, c in enumerate(comps):
    if ci in comp_unit or ci in parking or not c["in_campus"]:
        continue
    if c["max_side"] / max(c["min_side"], 1e-6) > 7.0 and c["max_side"] > 150:
        bar_like.add(ci)
plaza = []
for ci in sorted(parking | bar_like):
    c = comps[ci]
    if c["area"] < 3000 or c["min_side"] < 20:
        continue   # drop thin lake-edge lines / tiny sheds
    plaza.append({"kind": "parking" if ci in parking else "paved", "area": round(c["area"], 1),
                  "points": c["points"], "cx": round(float(c["centroid"][0]), 1),
                  "cy": round(float(c["centroid"][1]), 1)})

# ---------------- assemble ----------------
out_buildings = []
for ci, c in enumerate(comps):
    if not c["in_campus"] or ci in parking or ci in bar_like:
        continue
    rec = {"points": c["points"], "cx": round(float(c["centroid"][0]), 1),
           "cy": round(float(c["centroid"][1]), 1)}
    if ci in comp_id:
        b = bld[comp_id[ci]]
        rec.update({"id": comp_id[ci], "n": b["n"], "no": b["no"], "k": b["k"], "g": b["g"],
                    "confidence": comp_conf[ci]})
        rec["_how"] = comp_how[ci]
        if ci in comp_extra:
            rec["_detail"] = comp_extra[ci]
    else:
        rec.update({"id": None, "n": "", "no": "", "k": "", "g": "generic", "confidence": 0.0,
                    "_how": "generic"})
    out_buildings.append(rec)
out_buildings.sort(key=lambda r: (r["id"] is None, r["id"] or "", -r["confidence"]))

# matched old unit heads / unmatched units
matched_heads = set(comp_unit.values())
unmatched_units = [u for u in units if u["head"] not in matched_heads]
print("\nbuildings output:", len(out_buildings),
      "matched:", sum(1 for r in out_buildings if r["id"]),
      "generic:", sum(1 for r in out_buildings if not r["id"]))
print("\nmatched buildings:")
for r in out_buildings:
    if r["id"]:
        print("  %-4s %-14s conf=%.2f %-14s c=(%5.0f,%5.0f) verts=%d" % (
            r["id"], bld[r["id"]]["n"], r["confidence"], r["_how"], r["cx"], r["cy"], len(r["points"])))
print("\nold units with NO matched footprint (%d):" % len(unmatched_units))
for u in unmatched_units:
    print("  %-4s %-16s (%s)" % (u["head"], bld[u["head"]]["ln"], ",".join(u["ids"])))

# ---------------- write buildings_trace.json ----------------
# anchors = the EXACT least-squares correspondences used to fit the matrix (r15):
# the old wing nearest each AMap label icon after the iterative snap.
af = json.load(open(os.path.join(WORK, "anchor_fit.json"), encoding="utf-8"))
anchors = []
for lab, ids, mp, q in zip(af["labels"], af["anchor_old_ids"], af["anchor_model_points"], af["anchor_master_points"]):
    pr = A[:, :2] @ np.array(mp) + A[:, 2]
    anchors.append({"label": lab, "old_ids": ids,
                    "model_point": [round(float(v), 2) for v in mp],
                    "master_point": [round(float(q[0]), 1), round(float(q[1]), 1)],
                    "resid_px": round(float(np.hypot(pr[0] - q[0], pr[1] - q[1])), 2)})
resid_l = [a["resid_px"] for a in anchors]
res = {"mean": round(float(np.mean(resid_l)), 2), "median": round(float(np.median(resid_l)), 2),
       "p95": round(float(np.percentile(resid_l, 95)), 2), "max": round(float(max(resid_l)), 2)}

def clean(r):
    d = {k: v for k, v in r.items() if not k.startswith("_")}
    return d

bt = {
    "master_size": [W, H],
    "model_to_master": [[round(float(v), 6) for v in row] for row in A.tolist()],
    "model_space": {"source": "preview_data.json", "size": [848, 493],
                    "note": "affine least squares fitted from 14 AMap label anchors; "
                            "maps preview_data model (x,y) -> master pixel (x,y)"},
    "equivalent_scale": round(float(S), 5),
    "rotation_deg": round(float(math.degrees(math.atan2(A[1, 0], A[0, 0]))), 3),
    "anchors": anchors,
    "residual": res,
    "buildings": [clean(r) for r in out_buildings],
}
json.dump(bt, open(os.path.join(AMAP, "buildings_trace.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

features = {
    "master_size": [W, H],
    "water": [{"area": round(p["area"], 1), "points": [[int(x), int(y)] for x, y in p["points"]]}
              for p in raw["water"]],
    "island": [{"area": round(p["area"], 1), "points": [[int(x), int(y)] for x, y in p["points"]]}
               for p in raw["islands"]],
    "lawn": [{"area": round(p["area"], 1), "points": [[int(x), int(y)] for x, y in p["points"]]}
             for p in raw["green"]],
    "track": [],
    "plaza": plaza,
    "notes": {
        "track": "AMap mosaic does not render the athletics track (old-model T01/T02 project onto an "
                 "empty parking/land area around x 155-690, y 880-1560); track list intentionally empty",
        "plaza": "AMap style paints plazas with the same ground colour as land/roads, so squares cannot "
                 "be separated by colour; plaza[] only contains paved/parking surfaces that were "
                 "segmented as non-building grey patches",
    },
}
json.dump(features, open(os.path.join(AMAP, "features_trace.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\nfeatures: water=%d island=%d lawn=%d plaza=%d track=%d" % (
    len(features["water"]), len(features["island"]), len(features["lawn"]),
    len(features["plaza"]), len(features["track"])))

# stats for report
stats = {
    "components_total": len(comps),
    "components_in_campus": sum(1 for c in comps if c["in_campus"]),
    "parking_or_paved": len(parking | bar_like),
    "buildings_out": len(out_buildings),
    "matched": sum(1 for r in out_buildings if r["id"]),
    "generic": sum(1 for r in out_buildings if not r["id"]),
    "unmatched_units": [{"head": u["head"], "ln": bld[u["head"]]["ln"], "ids": u["ids"]} for u in unmatched_units],
    "label_rows": [{"comp": ci, "labels": [x[0] for x in lst], "unit": lst[0][1]} for ci, lst in label_hits.items()],
    "matched_rows": [{"id": r["id"], "n": bld[r["id"]]["n"], "ln": bld[r["id"]]["ln"],
                      "conf": r["confidence"], "how": r["_how"], "cx": r["cx"], "cy": r["cy"],
                      "detail": r.get("_detail")} for r in out_buildings if r["id"]],
    "generic_rows": [{"cx": r["cx"], "cy": r["cy"], "area": round(Polygon(r["points"]).area, 1),
                      "bbox": [int(min(p[0] for p in r["points"])), int(min(p[1] for p in r["points"])),
                               int(max(p[0] for p in r["points"])), int(max(p[1] for p in r["points"]))]}
                     for r in out_buildings if not r["id"]],
}
json.dump(stats, open(os.path.join(WORK, "final_stats.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# ---------------- check image from written trace (round-trip) ----------------
im = cv2.imread(os.path.join(AMAP, "master.png"))
trace = json.load(open(os.path.join(AMAP, "buildings_trace.json"), encoding="utf-8"))
vis = im.copy()
for r in trace["buildings"]:
    pts = np.array(r["points"], np.int32)
    col = (0, 0, 255) if r["id"] else (0, 165, 255)
    cv2.polylines(vis, [pts], True, col, 2)
    if r["id"]:
        txt = "%s %s" % (r["id"], r["n"])
        cv2.putText(vis, txt, (int(r["cx"]) - 24, int(r["cy"]) + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(vis, txt, (int(r["cx"]) - 24, int(r["cy"]) + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 0, 220), 1, cv2.LINE_AA)
for p in features["water"]:
    cv2.polylines(vis, [np.array(p["points"], np.int32)], True, (255, 0, 0), 2)
for p in features["island"]:
    cv2.polylines(vis, [np.array(p["points"], np.int32)], True, (255, 255, 0), 2)
for p in features["lawn"]:
    cv2.polylines(vis, [np.array(p["points"], np.int32)], True, (0, 150, 0), 2)
for p in features["plaza"]:
    cv2.polylines(vis, [np.array(p["points"], np.int32)], True, (200, 120, 0), 2)
cv2.imwrite(os.path.join(AMAP, "buildings_check.png"), vis)
sm = cv2.resize(vis, (1500, int(H * 1500.0 / W)), interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK, "selfcheck_trace_small.png"), sm)
for name, (x0, y0, x1, y1) in {
        "selfchk_north": (1000, 500, 2250, 1350), "selfchk_mid": (650, 1250, 1950, 1950),
        "selfchk_lib": (950, 1750, 1600, 2500), "selfchk_east": (2250, 650, 2900, 1500),
        "selfchk_dorm": (180, 1950, 1150, 3300)}.items():
    c = vis[y0:y1, x0:x1]
    sc = min(1.0, 1300.0 / max(c.shape[0], c.shape[1]))
    cv2.imwrite(os.path.join(WORK, name + ".png"),
                cv2.resize(c, (int(c.shape[1] * sc), int(c.shape[0] * sc)), interpolation=cv2.INTER_AREA))
print("\nsaved buildings_trace.json features_trace.json buildings_check.png and self-check crops")
