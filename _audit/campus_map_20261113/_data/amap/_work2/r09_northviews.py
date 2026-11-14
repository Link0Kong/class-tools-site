# -*- coding: utf-8 -*-
"""Inspect north part of master: find track / sports facilities."""
import os
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]

def crop(name, x0, y0, x1, y1, scale=0.7):
    c = im[y0:y1, x0:x1].copy()
    if scale != 1:
        c = cv2.resize(c, (int((x1 - x0) * scale), int((y1 - y0) * scale)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(os.path.join(WORK, name), c)
    print(name, (x0, y0, x1, y1), "->", c.shape)

crop("v_north_top.png", 1200, 150, 2800, 900, 0.62)
crop("v_north_west.png", 100, 400, 1400, 1200, 0.7)
crop("v_track_guess.png", 1500, 200, 2300, 800, 1.0)
crop("v_gym_area.png", 200, 1200, 1000, 1800, 0.9)
