import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
g = cv2.imread(os.path.join(BASE, "master_grid.png"))
m = cv2.imread(os.path.join(BASE, "master.png"))
print("grid", g.shape, "master", m.shape)
# grid readability: 1:1 crop
cv2.imwrite(os.path.join(WORK, "v_grid.png"), g[2100:2600, 1100:1900], [cv2.IMWRITE_PNG_COMPRESSION, 6])
# seam check: north/south seam at master y ~1051, x 1000-2000
cv2.imwrite(os.path.join(WORK, "v_seam.png"), m[950:1250, 1000:2000], [cv2.IMWRITE_PNG_COMPRESSION, 6])
# west/south seam at master y ~2150
cv2.imwrite(os.path.join(WORK, "v_seam2.png"), m[2050:2350, 700:1700], [cv2.IMWRITE_PNG_COMPRESSION, 6])
print("saved views")
