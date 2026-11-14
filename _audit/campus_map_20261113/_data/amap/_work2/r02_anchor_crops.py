# -*- coding: utf-8 -*-
"""Anchor candidate crops; 2x upscaled, red crosshair at crop centre."""
import os, sys
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]

def crop(name, cx, cy, hw=220, hh=160, scale=2.0):
    x0 = max(0, cx - hw); y0 = max(0, cy - hh)
    x1 = min(W, cx + hw); y1 = min(H, cy + hh)
    c = im[y0:y1, x0:x1].copy()
    c = cv2.resize(c, (int((x1 - x0) * scale), int((y1 - y0) * scale)), interpolation=cv2.INTER_NEAREST)
    # crosshair at requested centre
    px = int((cx - x0) * scale); py = int((cy - y0) * scale)
    cv2.drawMarker(c, (px, py), (0, 0, 255), cv2.MARKER_CROSS, 26, 2)
    cv2.putText(c, f"{cx},{cy}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 1, cv2.LINE_AA)
    p = os.path.join(WORK, name)
    cv2.imwrite(p, c)
    return p

# rough estimates from preview_master_grid (displayed 1200x1405 -> master factor 2.464)
EST = {
    "a_library": (1232, 2164),
    "a_wuxing": (1996, 1257),
    "a_zhishan": (1829, 1301),
    "a_jingcheng": (1370, 1405),
    "a_kangfu": (924, 1412),
    "a_mingde": (1873, 2065),
    "a_b23": (1306, 789),
    "a_b7": (1836, 1158),
}
for k, (x, y) in EST.items():
    print(crop(k + ".png", x, y), (x, y))
