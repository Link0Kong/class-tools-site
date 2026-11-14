# -*- coding: utf-8 -*-
"""r20: extraction v2 - thinner morphology so that adjacent buildings stay separate."""
import os, json, time
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
t0 = time.time()
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]
RGB = cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.int16)
R, G, B = RGB[:, :, 0], RGB[:, :, 1], RGB[:, :, 2]

# ---------------- masks ----------------
d = np.maximum.reduce([np.abs(R - 217), np.abs(G - 227), np.abs(B - 236)])
bld = (d <= 10).astype(np.uint8)
bld = cv2.morphologyEx(bld, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
print("building px", int(bld.sum()))

water = ((B >= 200) & (R <= 190) & (G >= 185) & ((B - R) >= 45) & ((B - G) >= 12)).astype(np.uint8)
water = cv2.morphologyEx(water, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
water = cv2.morphologyEx(water, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
green = ((G >= 185) & ((G - B) >= 30) & ((G - R) >= 25)).astype(np.uint8)
green = cv2.morphologyEx(green, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
print("water px", int(water.sum()), "green px", int(green.sum()))


def comps(mask, min_area, simplify_eps=2.0, min_side_min=8.0, min_solidity=0.35):
    n, lab, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for k in range(1, n):
        x, y, w, h, a = [int(v) for v in stats[k]]
        if a < min_area or w < 6 or h < 6:
            continue
        sub = (lab[y:y + h, x:x + w] == k).astype(np.uint8)
        cnts, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea) + np.array([[x, y]], dtype=np.int32)
        ca = float(cv2.contourArea(c))
        if ca < min_area:
            continue
        hull = cv2.convexHull(c)
        ha = float(cv2.contourArea(hull))
        sol = ca / ha if ha > 0 else 0.0
        (rw, rh) = cv2.minAreaRect(c)[1]
        if min(rw, rh) < min_side_min or sol < min_solidity:
            continue
        approx = cv2.approxPolyDP(c, simplify_eps, True)
        pts = [[int(round(p[0][0])), int(round(p[0][1]))] for p in approx]
        if len(pts) < 3:
            continue
        out.append({"area": ca, "points": pts, "cx": float(cents[k][0]), "cy": float(cents[k][1]),
                    "bbox": [x, y, w, h], "solidity": sol,
                    "min_side": float(min(rw, rh)), "max_side": float(max(rw, rh)), "nvert": len(pts)})
    return out


buildings = comps(bld, 900)
print("building comps", len(buildings))

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
            continue
        c = c + np.array([[x, y]], dtype=np.int32)
        ca = float(cv2.contourArea(c))
        if ca < 5000:
            continue
        ap = cv2.approxPolyDP(c, 3.0, True)
        water_polys.append({"area": ca, "points": [[int(round(p[0][0])), int(round(p[0][1]))] for p in ap]})
        child = hier[ci][2]
        while child != -1:
            ch = cnts[child] + np.array([[x, y]], dtype=np.int32)
            cha = float(cv2.contourArea(ch))
            if cha > 4000:
                ap2 = cv2.approxPolyDP(ch, 3.0, True)
                islands.append({"area": cha,
                                "points": [[int(round(p[0][0])), int(round(p[0][1]))] for p in ap2]})
            child = hier[child][0]
greens = comps(green, 4000, simplify_eps=3.0, min_side_min=6.0, min_solidity=0.10)
print("water polys", len(water_polys), "islands", len(islands), "green comps", len(greens))

json.dump({"master_size": [W, H], "buildings": buildings, "water": water_polys,
           "islands": islands, "green": greens},
          open(os.path.join(WORK, "extract_raw2.json"), "w", encoding="utf-8"), ensure_ascii=False)

# debug overlay
vis = im.copy()
for k, c in enumerate(buildings):
    pts = np.array(c["points"], np.int32)
    cv2.polylines(vis, [pts], True, (0, 0, 255), 2)
    cv2.putText(vis, str(k), (int(c["cx"]) - 8, int(c["cy"]) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                (255, 255, 255), 4, cv2.LINE_AA)
    cv2.putText(vis, str(k), (int(c["cx"]) - 8, int(c["cy"]) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                (0, 0, 220), 1, cv2.LINE_AA)
cv2.imwrite(os.path.join(WORK, "d_buildings2.png"),
            cv2.resize(vis, (1500, int(H * 1500.0 / W)), interpolation=cv2.INTER_AREA))
print("done in %.1fs" % (time.time() - t0))
