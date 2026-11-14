# -*- coding: utf-8 -*-
"""Sample exact pixel colours at grid of points to understand tile styling."""
import os
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]
pts = [(300, 100), (800, 100), (1500, 100), (2400, 100), (2800, 100),
       (300, 400), (800, 400), (1500, 400), (2400, 400),
       (100, 800), (100, 1500), (100, 2200), (200, 2900), (300, 3300),
       (500, 1000), (500, 2000), (500, 2600), (500, 3100),
       (900, 500), (900, 1200), (900, 1800), (900, 2400), (900, 2900),
       (1200, 1000), (1200, 1500), (1200, 2200), (1200, 2700), (1200, 3200),
       (1600, 1200), (1600, 1700), (1600, 2500), (1600, 3000),
       (2000, 900), (2000, 1500), (2000, 2000), (2000, 2800),
       (2400, 800), (2400, 1300), (2400, 2300), (2400, 3200),
       (2700, 600), (2700, 1200), (2700, 2500), (2850, 3300)]
print("  x     y   RGB       HEX")
for (x, y) in pts:
    b, g, r = im[y, x]
    print(f"{x:5d} {y:5d}  ({r:3d},{g:3d},{b:3d})  #{r:02x}{g:02x}{b:02x}")

# check seam: scan column x=1500 colours vertical
print("\nvertical scan x=1500 every 200px:")
for y in range(0, H, 200):
    b, g, r = im[y, 1500]
    print(f"   y={y:5d} RGB=({r:3d},{g:3d},{b:3d}) #{r:02x}{g:02x}{b:02x}")
