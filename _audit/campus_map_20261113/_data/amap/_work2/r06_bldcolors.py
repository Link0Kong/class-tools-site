# -*- coding: utf-8 -*-
"""Sample interior points of known building shapes in each tile."""
import os
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
im = cv2.imread(os.path.join(AMAP, "master.png"))

def s(label, x, y, r=2):
    win = im[y - r:y + r + 1, x - r:x + r + 1].reshape(-1, 3)
    b, g, rr = np.median(win, axis=0).astype(int)
    print(f"{label:28s} ({x:4d},{y:4d})  RGB=({rr:3d},{g:3d},{b:3d}) #{rr:02x}{g:02x}{b:02x}")

# south tile building interiors (from a_wuxing / a_library crops, crop origin known)
s("wuxing-L interior", 1976, 1172)
s("wuxing-L interior2", 1880, 1140)
s("zhishan building", 1840, 1360)
s("library west wing", 1137, 2129)
s("library mid", 1190, 2200)
s("library east wing", 1420, 2250)
s("jingcheng bld", 1370, 1390)
s("kangfu bld", 1010, 1400)
s("mingde bld", 1900, 2090)
s("dorm 21 bld", 400, 2360)
s("dorm 18 bld", 430, 2470)
s("track infield", 1500, 400)
s("track stands?", 1620, 300)
# north tile buildings (top-left village area, from src_north: buildings near 联心村)
s("north bld (联心村)", 300, 120)
s("north land", 700, 150)
s("north bld2", 1200, 60)
# west tile
s("west land?", 600, 2800)
s("west bld", 505, 2790)
s("west bld2", 400, 2700)
s("west bld3", 300, 2600)
s("sw bld (餐饮?)", 1200, 3000)
# roads
s("road white", 1600, 2300)
s("north road", 900, 800)
