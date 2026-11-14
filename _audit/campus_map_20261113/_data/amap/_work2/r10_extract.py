# -*- coding: utf-8 -*-
"""r10: colour segmentation of master.png -> building / water / green components.

Outputs (in _work2):
  extract_raw.json     raw component data (pixel coords, master frame)
  d_buildings.png      building mask + component ids
  d_watergreen.png     water / green overlay
  d_full_overlay.png   all masks over master (downscaled)
"""
import os, json, time
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
t0 = time.time()

im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]
RGB = cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.int16)
R, G, B = RGB[:, :, 0], RGB[:, :, 1], RGB[:, :, 2]

def lin(a):
    return np.maximum.reduce([np.zeros_like(a), a])

# ---------------- building mask ----------------
# AMap building fill #d9e3ec = RGB(217,227,236)
d = np.maximum.reduce([np.abs(R - 217), np.abs(G - 227), np.abs(B - 236)])
bld = (d <= 10).astype(np.uint8)
print("raw building px", int(bld.sum()))
# remove thin lines (park contour lines etc.), then close tiny gaps
bld = cv2.morphologyEx(bld, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
bld = cv2.morphologyEx(bld, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
print("cleaned building px", int(bld.sum()))

# ---------------- water mask ----------------
water = ((B >= 200) & (R <= 190) & (G >= 185) & ((B - R) >= 45) & ((B - G) >= 12)).astype(np.uint8)
water = cv2.morphologyEx(water, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
water = cv2.morphologyEx(water, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
print("water px", int(water.sum()))

# ---------------- green mask ----------------
green = ((G >= 185) & ((G - B) >= 30) & ((G - R) >= 25)).astype(np.uint8)
green = cv2.morphologyEx(green, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
print("green px", int(green.sum()))

# ---------------- component extraction ----------------
def comps(mask, min_area, max_frac=0.6, simplify_eps=2.0, open_extra=1):
    """connected components with external contour polygonisation.
    returns list of dict(points, area, cx, cy, bbox, solidity, rect)."""
    n, lab, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for k in range(1, n):
        x, y, w, h, a = [int(v) for v in stats[k]]
        if a < min_area:
            continue
        if w < 6 or h < 6:
            continue
        sub = (lab[y:y + h, x:x + w] == k).astype(np.uint8)
        cnts, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea)
        c = c + np.array([[x, y]], dtype=np.int32)
        ca = float(cv2.contourArea(c))
        if ca < min_area:
            continue
        hull = cv2.convexHull(c)
        ha = float(cv2.contourArea(hull))
        sol = ca / ha if ha > 0 else 0.0
        rect = cv2.minAreaRect(c)
        (rw, rh) = rect[1]
        eps = simplify_eps
        approx = cv2.approxPolyDP(c, eps, True)
        pts = [[int(round(p[0][0])), int(round(p[0][1]))] for p in approx]
        if len(pts) < 3:
            continue
        out.append({
            "area": ca, "points": pts, "cx": float(cents[k][0]), "cy": float(cents[k][1]),
            "bbox": [x, y, w, h], "solidity": sol,
            "min_side": float(min(rw, rh)), "max_side": float(max(rw, rh)),
            "nvert": len(pts),
        })
    return out

buildings = comps(bld, min_area=900)
print("building comps", len(buildings))

# water: external contours + holes (islands)
nw, labw, statsw, centsw = cv2.connectedComponentsWithStats(water, 8)
water_polys, islands = [], []
for k in range(1, nw):
    x, y, w, h, a = [int(v) for v in statsw[k]]
    if a < 5000:
        continue
    sub = (labw[y:y + h, x:x + w] == k).astype(np.uint8)
    cnts, hier = cv2.findContours(sub, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        continue
    hier = hier[0]
    for ci, c in enumerate(cnts):
        if hier[ci][3] != -1:
            continue  # not an outer contour
        c = c + np.array([[x, y]], dtype=np.int32)
        ca = float(cv2.contourArea(c))
        if ca < 5000:
            continue
        approx = cv2.approxPolyDP(c, 3.0, True)
        pts = [[int(round(p[0][0])), int(round(p[0][1]))] for p in approx]
        water_polys.append({"area": ca, "points": pts, "cx": float(centsw[k][0]) if ci == 0 else None})
        # holes of this outer contour -> islands
        child = hier[ci][2]
        while child != -1:
            ch = cnts[child] + np.array([[x, y]], dtype=np.int32)
            cha = float(cv2.contourArea(ch))
            if cha > 4000:
                ap = cv2.approxPolyDP(ch, 3.0, True)
                islands.append({"area": cha,
                                "points": [[int(round(p[0][0])), int(round(p[0][1]))] for p in ap]})
            child = hier[child][0]

greens = comps(green, min_area=4000, simplify_eps=3.0)
print("water polys", len(water_polys), "islands", len(islands), "green comps", len(greens))

# ---------------- debug images ----------------
dbg = im.copy()
for b in buildings:
    cv2.polylines(dbg, [np.array(b["points"], np.int32)], True, (0, 0, 255), 2)
    px, py = b["points"][0]
    cv2.putText(dbg, str(len(b["points"])), (px, py), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
for w_ in water_polys:
    cv2.polylines(dbg, [np.array(w_["points"], np.int32)], True, (255, 0, 0), 2)
for isl in islands:
    cv2.polylines(dbg, [np.array(isl["points"], np.int32)], True, (255, 255, 0), 2)
for g_ in greens:
    cv2.polylines(dbg, [np.array(g_["points"], np.int32)], True, (0, 160, 0), 2)

cv2.imwrite(os.path.join(WORK, "d_full_overlay.png"),
            cv2.resize(dbg, (1400, int(H * 1400.0 / W)), interpolation=cv2.INTER_AREA))

# building check image on master, 2 crops for resolution
cv2.imwrite(os.path.join(WORK, "d_buildings_crop1.png"), dbg[0:H // 2, 0:W // 2])
cv2.imwrite(os.path.join(WORK, "d_buildings_crop2.png"), dbg[H // 2:, W // 2:])

json.dump({"master_size": [W, H],
           "buildings": buildings, "water": water_polys, "islands": islands, "green": greens},
          open(os.path.join(WORK, "extract_raw.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("done in %.1fs" % (time.time() - t0))
