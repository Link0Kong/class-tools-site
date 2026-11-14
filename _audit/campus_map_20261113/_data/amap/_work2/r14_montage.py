# -*- coding: utf-8 -*-
"""r14: make montage sheets of all detected POI icons + their label text,
so the operator can read the Chinese names."""
import os, json
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]
icons = json.load(open(os.path.join(WORK, "poi_icons.json")))
# keep only standard 22px icons (drop partial ones)
ic = [tuple(c[:2]) for c in icons if c[2] >= 20 and c[3] >= 20 and c[4] >= 200]
print("icons used", len(ic))

SCALE = 2.5
CW, CH = 340, 84   # crop size around icon
cols = 2
rows = 7
per = cols * rows
sheets = (len(ic) + per - 1) // per

for s in range(sheets):
    sheet = np.full((rows * int(CH * SCALE) + 10, cols * int(CW * SCALE) + 10, 3), 255, np.uint8)
    for j in range(per):
        idx = s * per + j
        if idx >= len(ic):
            break
        ix, iy = ic[idx]
        x0 = int(max(0, min(W - CW, ix - 45)))
        y0 = int(max(0, min(H - CH, iy - 42)))
        crop = im[y0:y0 + CH, x0:x0 + CW]
        crop = cv2.resize(crop, (int(CW * SCALE), int(CH * SCALE)), interpolation=cv2.INTER_CUBIC)
        # mark the icon centre
        cx = int((ix - x0) * SCALE); cy = int((iy - y0) * SCALE)
        cv2.rectangle(crop, (cx - 14, cy - 14), (cx + 14, cy + 14), (0, 0, 255), 1)
        cv2.putText(crop, "#%d (%.0f,%.0f)" % (idx, ix, iy), (6, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
        r, c = divmod(j, cols)
        yy = r * int(CH * SCALE); xx = c * int(CW * SCALE)
        sheet[yy:yy + crop.shape[0], xx:xx + crop.shape[1]] = crop
    p = os.path.join(WORK, "lbl_sheet_%d.png" % s)
    cv2.imwrite(p, sheet)
    print(p, sheet.shape, "icons", s * per, "..", min(len(ic) - 1, s * per + per - 1))
