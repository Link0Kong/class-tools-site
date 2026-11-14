# -*- coding: utf-8 -*-
"""Sample POI icon colours and test blue-icon blob detection."""
import os
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]

# library icon approx (1251,2154)
print("-- library icon window colours --")
win = im[2130:2180, 1228:1275]
cols, cnt = np.unique(win.reshape(-1, 3), axis=0, return_counts=True)
o = np.argsort(-cnt)[:10]
for i in o:
    b, g, r = cols[i]
    print(f"  RGB=({r:3d},{g:3d},{b:3d}) HEX=#{r:02x}{g:02x}{b:02x} {cnt[i]}")

# blue-ish saturated mask
b, g, r = im[:, :, 0].astype(int), im[:, :, 1].astype(int), im[:, :, 2].astype(int)
mask = (b > 180) & (b - r > 50) & (b - g > 30)
print("\nblue px", int(mask.sum()))
n, lab, stats, cents = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
print("components", n - 1)
sizes = stats[1:, cv2.CC_STAT_AREA]
keep = np.where((sizes > 40) & (sizes < 900))[0]
print("candidate icon-like comps", len(keep))
cands = []
for k in keep:
    x, y, w, h, a = stats[k + 1]
    if 0.6 < w / max(1, h) < 1.7 and a / (w * h) > 0.45:
        cands.append((float(cents[k + 1][0]), float(cents[k + 1][1]), int(w), int(h), int(a)))
print("circular-ish comps", len(cands))
for c in cands[:40]:
    print("   ", [round(v, 1) for v in c[:3]], c[3], c[4])
np.save(os.path.join(WORK, "poi_cands.npy"), np.array(cands))
