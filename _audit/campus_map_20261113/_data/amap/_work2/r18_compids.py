# -*- coding: utf-8 -*-
"""r18: component index overlay in 4 quadrant crops for visual identification."""
import os, json
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
raw = json.load(open(os.path.join(WORK, "extract_raw.json"), encoding="utf-8"))
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]

vis = im.copy()
for k, c in enumerate(raw["buildings"]):
    pts = np.array(c["points"], np.int32)
    cv2.polylines(vis, [pts], True, (0, 0, 255), 2)
    cx, cy = int(c["cx"]), int(c["cy"])
    txt = "%d" % k
    cv2.putText(vis, txt, (cx - 8, cy + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 4, cv2.LINE_AA)
    cv2.putText(vis, txt, (cx - 8, cy + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 220), 2, cv2.LINE_AA)

quads = {
    "q_nw": (0, 0, W // 2 + 150, H // 2 + 100),
    "q_ne": (W // 2 - 150, 0, W, H // 2 + 100),
    "q_sw": (0, H // 2 - 100, W // 2 + 150, H),
    "q_se": (W // 2 - 150, H // 2 - 100, W, H),
}
for name, (x0, y0, x1, y1) in quads.items():
    c = vis[y0:y1, x0:x1]
    c = cv2.resize(c, (int(c.shape[1] * 0.82), int(c.shape[0] * 0.82)), interpolation=cv2.INTER_AREA)
    p = os.path.join(WORK, name + ".png")
    cv2.imwrite(p, c)
    print(p, c.shape)
