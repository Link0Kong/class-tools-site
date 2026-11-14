# -*- coding: utf-8 -*-
"""Detect POI icon circles and inspect one icon's pixels."""
import os, json
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]
B = im[:, :, 0].astype(int); G = im[:, :, 1].astype(int); R = im[:, :, 2].astype(int)

# --- inspect one icon: 7号楼 at (1835,1118)
x, y = 1835, 1118
win = im[y - 14:y + 14, x - 14:x + 14]
print("icon window 28x28 (RGB rows):")
for row in win[::3]:
    print(" ".join(f"{r:3d},{g:3d},{b:3d}" for b, g, r in row[::3]))

# --- blue mask
mask = (B > 170) & (B - R > 40) & (B - G > 20)
n, lab, stats, cents = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
cands = []
for k in range(1, n):
    xx, yy, w, h, a = stats[k]
    if 16 <= w <= 26 and 16 <= h <= 26 and a >= 150 and 0.75 < w / h < 1.33:
        cands.append((float(cents[k][0]), float(cents[k][1]), int(w), int(h), int(a)))
print("\nicon candidates:", len(cands))
cands.sort(key=lambda t: (t[1], t[0]))
for c in cands:
    print(f"  ({c[0]:7.1f},{c[1]:7.1f}) w={c[2]} h={c[3]} a={c[4]}")
json.dump(cands, open(os.path.join(WORK, "poi_icons.json"), "w"))
