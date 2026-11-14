# -*- coding: utf-8 -*-
"""Explore master.png colours / save downscaled overview + grid."""
import os, json
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
os.makedirs(WORK, exist_ok=True)

im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]
print("master shape", im.shape, "W,H", W, H)

# ---- colour clusters (kmeans on subsample) ----
rng = np.random.default_rng(0)
idx = rng.choice(H * W, size=200000, replace=False)
pts = im.reshape(-1, 3)[idx].astype(np.float32)
K = 14
crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.5)
compact, labels, centers = cv2.kmeans(pts, K, None, crit, 4, cv2.KMEANS_PP_CENTERS)
counts = np.bincount(labels.ravel(), minlength=K)
order = np.argsort(-counts)
print("\n-- kmeans colours (BGR) --")
for i in order:
    b, g, r = centers[i]
    print(f"#{i:2d}  BGR=({b:5.1f},{g:5.1f},{r:5.1f})  RGB=({r:5.1f},{g:5.1f},{b:5.1f})  {100*counts[i]/len(pts):5.2f}%")

# ---- exact most-common colours ----
flat = im.reshape(-1, 3)
cols, cnt = np.unique(flat, axis=0, return_counts=True)
o = np.argsort(-cnt)[:30]
print("\n-- exact top colours --")
for i in o:
    b, g, r = cols[i]
    print(f"RGB=({r:3d},{g:3d},{b:3d}) HEX=#{r:02x}{g:02x}{b:02x}  {cnt[i]:8d}  {100*cnt[i]/len(flat):6.2f}%")

# ---- overview with 200px grid, labelled every 400 ----
scale = 1400.0 / W
small = cv2.resize(im, (1400, int(round(H * scale))), interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK, "preview_master.png"), small)

g = im.copy()
for x in range(0, W, 100):
    cv2.line(g, (x, 0), (x, H - 1), (150, 120, 220), 1)
for y in range(0, H, 100):
    cv2.line(g, (0, y), (W - 1, y), (150, 120, 220), 1)
for x in range(0, W, 400):
    cv2.line(g, (x, 0), (x, H - 1), (0, 0, 255), 2)
    for ytxt in (30, H // 2, H - 20):
        cv2.putText(g, str(x), (x + 4, ytxt), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(g, str(x), (x + 4, ytxt), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 200), 1, cv2.LINE_AA)
for y in range(0, H, 400):
    cv2.line(g, (0, y), (W - 1, y), (0, 0, 255), 2)
    for xtxt in (30, W // 2, W - 140):
        cv2.putText(g, str(y), (xtxt, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(g, str(y), (xtxt, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 200), 1, cv2.LINE_AA)
gs = cv2.resize(g, (1200, int(round(H * 1200.0 / W))), interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK, "preview_master_grid.png"), gs)
print("\nsaved previews")
