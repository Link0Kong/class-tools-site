# -*- coding: utf-8 -*-
"""r16: match extracted building components to old records (nearest centre +
area ratio + footprint overlap), clip to campus boundary, write first-pass JSON."""
import os, json, math
import cv2, numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from scipy.optimize import linear_sum_assignment

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

def tf(pts):
    p = np.array(pts, float)
    return p @ A[:, :2].T + A[:, 2]

def unit_geom(u):
    polys = []
    for i in u["ids"]:
        f = feat.get(i)
        if not f:
            continue
        polys.append(Polygon(tf(f["p"])))
    return unary_union(polys)

for u in units:
    g = unit_geom(u)
    u["geom"] = g
    u["model_area"] = sum(Polygon(feat[i]["p"]).area for i in u["ids"] if i in feat)
    u["model_center"] = np.array([[bld[i]["x"], bld[i]["y"]] for i in u["ids"]]).mean(0)
    u["master_center"] = tf([u["model_center"]])[0]
    u["px_area"] = u["model_area"] * S * S
    u["names"] = sorted({bld[i]["n"] for i in u["ids"]})

# campus boundary (S01 old site boundary) projected, slightly buffered
s01 = Polygon(tf(feat["S01"]["p"]))
campus = s01.buffer(40)
print("campus projected bbox", campus.bounds)

comps = []
for k, c in enumerate(raw["buildings"]):
    poly = Polygon(c["points"])
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        continue
    centroid = np.array([c["cx"], c["cy"]])
    inside = campus.contains(poly.representative_point()) or campus.intersection(poly).area > 0.5 * poly.area
    comps.append({"k": k, "poly": poly, "centroid": centroid, "area": poly.area,
                  "bbox": c["bbox"], "in_campus": inside, "points": c["points"]})

campus_comps = [c for c in comps if c["in_campus"]]
print("components total", len(comps), "in campus", len(campus_comps))

# cost matrix
DIST_MAX = 260.0
cm = np.zeros((len(campus_comps), len(units)))
detail = {}
for i, c in enumerate(campus_comps):
    for j, u in enumerate(units):
        d = float(np.linalg.norm(c["centroid"] - u["master_center"]))
        ar = (c["area"] / (S * S)) / u["model_area"] if u["model_area"] > 0 else 99
        inter = c["poly"].intersection(u["geom"]).area
        cov = inter / c["area"] if c["area"] > 0 else 0.0
        cov_u = inter / u["geom"].area if u["geom"].area > 0 else 0.0
        ok = (d <= DIST_MAX) and (0.3 <= ar <= 3.2)
        cost = d + 220.0 * (1.0 - min(cov, 1.0)) + 90.0 * abs(math.log(max(ar, 1e-6)))
        if not ok:
            cost = 4000.0
        cm[i, j] = cost
        detail[(i, j)] = {"dist": d, "area_ratio": ar, "cov": cov, "cov_u": cov_u, "ok": ok, "cost": cost}

# add dummy columns for unmatched
dummy = np.full((len(campus_comps), len(campus_comps)), 1000.0)
for i in range(len(campus_comps)):
    dummy[i, i] = 260.0
CM = np.hstack([cm, dummy])
ri, ci = linear_sum_assignment(CM)
assign = {}
for i, j in zip(ri, ci):
    if j < len(units) and CM[i, j] < 1000.0:
        assign[i] = j

matched = [i for i in range(len(campus_comps)) if i in assign]
print("assignments", len(matched), "of", len(campus_comps), "campus components; units", len(units))

rows = []
for i, c in enumerate(campus_comps):
    if i in assign:
        j = assign[i]
        u = units[j]
        d = detail[(i, j)]
        # specific wing = nearest wing master centre to component centroid
        wings = [(nid, float(np.linalg.norm(c["centroid"] - tf([[bld[nid]["x"], bld[nid]["y"]]])[0]))) for nid in u["ids"]]
        wings.sort(key=lambda t: t[1])
        wid = wings[0][0]
        b = bld[wid]
        conf = math.exp(-d["dist"] / 90.0) * min(1.0, 0.3 + 0.7 * min(d["cov"], 1.0)) * min(1.0, max(d["area_ratio"], 1 / d["area_ratio"]))
        rows.append({"comp": i, "id": wid, "n": b["n"], "no": b["no"], "k": b["k"], "g": b["g"],
                     "ln": b["ln"], "dist": d["dist"], "area_ratio": d["area_ratio"],
                     "cov": d["cov"], "confidence": round(float(conf), 4)})
    else:
        rows.append({"comp": i, "id": None, "n": "", "no": "", "k": "", "g": "",
                     "ln": "", "dist": None, "area_ratio": None, "cov": None, "confidence": 0.0})

rows.sort(key=lambda r: -(r["confidence"]))
print("\nmatched (sorted by confidence):")
for r in rows:
    if r["id"]:
        print("  %-4s %-16s d=%5.1f ar=%5.2f cov=%.2f conf=%.2f area=%6d bbox=%s" %
              (r["id"], r["ln"], r["dist"], r["area_ratio"], r["cov"], r["confidence"],
               campus_comps[r["comp"]]["area"], campus_comps[r["comp"]]["bbox"]))
print("\ngeneric:", sum(1 for r in rows if not r["id"]))
for r in rows:
    if not r["id"]:
        c = campus_comps[r["comp"]]
        print("  area=%6d bbox=%s c=(%.0f,%.0f)" % (c["area"], c["bbox"], c["centroid"][0], c["centroid"][1]))

json.dump({"rows": rows,
           "campus_comps": [{"centroid": c["centroid"].tolist(), "area": c["area"], "bbox": c["bbox"]} for c in campus_comps],
           "units": [{"head": u["head"], "ids": u["ids"], "names": u["names"],
                      "master_center": u["master_center"].tolist()} for u in units]},
          open(os.path.join(WORK, "match_pass1.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# visual
im = cv2.imread(os.path.join(AMAP, "master.png"))
vis = im.copy()
colors = [(0, 0, 255), (0, 128, 255), (0, 200, 200), (200, 0, 200)]
for r in rows:
    c = campus_comps[r["comp"]]
    pts = np.array(c["points"], np.int32)
    if r["id"]:
        cv2.polylines(vis, [pts], True, (0, 0, 255), 2)
        cv2.putText(vis, "%s %.2f" % (r["id"], r["confidence"]), (int(c["centroid"][0]) - 20, int(c["centroid"][1])),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
    else:
        cv2.polylines(vis, [pts], True, (0, 165, 255), 2)
# campus boundary
cv2.polylines(vis, [np.array(feat["S01"]["p"], np.float64) @ A[:, :2].T + A[:, 2]], True, (0, 255, 0), 2)
small = cv2.resize(vis, (1500, int(im.shape[0] * 1500.0 / im.shape[1])), interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK, "d_match1.png"), small)
print("\nsaved match_pass1.json / d_match1.png")
