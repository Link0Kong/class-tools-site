# -*- coding: utf-8 -*-
"""Crop candidate building / water / green / track regions at full res."""
import os
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]

def crop(name, x0, y0, w, h, scale=2.0):
    x0 = max(0, x0); y0 = max(0, y0)
    c = im[y0:y0 + h, x0:x0 + w].copy()
    if scale != 1.0:
        c = cv2.resize(c, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)
    p = os.path.join(WORK, name)
    cv2.imwrite(p, c)
    # colour stats of the un-resized crop
    raw = im[y0:y0 + h, x0:x0 + w].reshape(-1, 3)
    cols, cnt = np.unique(raw, axis=0, return_counts=True)
    o = np.argsort(-cnt)[:8]
    print(f"--- {name} ({w}x{h} at {x0},{y0}) ---")
    for i in o:
        b, g, r = cols[i]
        print(f"   RGB=({r:3d},{g:3d},{b:3d}) HEX=#{r:02x}{g:02x}{b:02x} {100*cnt[i]/len(raw):6.2f}%")
    return p

# measured from preview: master = preview_display * 2957/1207 ~ 2.449
# library approx (1494,2241)
crop("c_library.png", 1240, 2080, 520, 420)
# 五行楼/至善楼 approx displayed (930,520)->(2277,1273)
crop("c_wuxing.png", 2000, 1100, 700, 500)
# 23号楼 displayed(600,320)->(1469,784)
crop("c_bld23.png", 1250, 650, 700, 450)
# 精诚楼 displayed (600,600)->(1469,1469)
crop("c_jingcheng.png", 1200, 1300, 700, 500)
# 学生公寓 11-15 displayed (200,1150)->(490,2816)
crop("c_dorm.png", 250, 2600, 700, 600)
# 田径场 displayed (660,140)->(1616,343) big green
crop("c_track.png", 1350, 150, 700, 500)
# 求真楼/修园楼 east displayed(1150,530)->(2816,1298)
crop("c_qiuzhen.png", 2400, 1150, 550, 450)
# 明德楼 displayed(870,960)->(2131,2351)
crop("c_mingde.png", 1900, 2200, 600, 420)
print("done, W,H=", W, H)
