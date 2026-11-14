# -*- coding: utf-8 -*-
"""Test colour-based masks for building / water / green on master.png."""
import os
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]
B = im[:, :, 0].astype(np.int16); G = im[:, :, 1].astype(np.int16); R = im[:, :, 2].astype(np.int16)

# candidate masks (exact / small tolerance)
def near(target, tol=6):
    b, g, r = target
    return (np.abs(B - b) <= tol) & (np.abs(G - g) <= tol) & (np.abs(R - r) <= tol)

m_d9 = near((236, 227, 217), 8)   # #d9e3ec -> BGR (236,227,217)
m_ef = near((246, 243, 239), 8)   # #eff3f6
m_fa = near((246, 248, 250), 8)   # #faf8f6 road
m_water = (B > 210) & (G > 170) & (G < 240) & (R < 180) & (B - R > 60)
m_green = (G > 180) & (G - B > 20) & (G - R > 25)
m_bg = near((249, 240, 230), 6)   # #e6f0f9 ground

print("counts: d9=%d ef=%d fa=%d water=%d green=%d bg=%d total=%d" % (
    m_d9.sum(), m_ef.sum(), m_fa.sum(), m_water.sum(), m_green.sum(), m_bg.sum(), H * W))

vis = im.copy()
vis[m_d9] = (0, 0, 255)      # red = building candidate A
vis[m_ef] = (0, 255, 255)    # yellow = candidate B
vis[m_water] = (255, 0, 0)   # blue = water
vis[m_green] = (0, 200, 0)   # green
vis = cv2.resize(vis, (1200, int(H * 1200.0 / W)), interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK, "mask_vis1.png"), vis)

# per-mask binary small previews
for name, m, col in [("d9", m_d9, 255), ("ef", m_ef, 255), ("water", m_water, 255), ("green", m_green, 255)]:
    mv = np.zeros((H, W, 3), np.uint8)
    mv[m] = col
    mv = cv2.resize(mv, (700, int(H * 700.0 / W)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(os.path.join(WORK, "mask_%s.png" % name), mv)
print("saved")
