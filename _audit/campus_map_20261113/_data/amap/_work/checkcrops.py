import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
im = cv2.imread(os.path.join(BASE, "roads_check.png"))
H, W = im.shape[:2]
def crop(x0, y0, x1, y1, scale, name):
    c = im[y0:y1, x0:x1].copy()
    c = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_NEAREST)
    ch, cw = c.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    for x in range(x0//100*100, x1+1, 100):
        if x < x0: continue
        px = int((x-x0)*scale)
        if 0 <= px < cw:
            cv2.line(c, (px,0), (px,ch-1), (0,200,0), 1)
            cv2.putText(c, str(x), (px+2, 14), font, 0.45, (0,160,0), 1, cv2.LINE_AA)
    for y in range(y0//100*100, y1+1, 100):
        if y < y0: continue
        py = int((y-y0)*scale)
        if 0 <= py < ch:
            cv2.line(c, (0,py), (cw-1,py), (0,200,0), 1)
            cv2.putText(c, str(y), (3, py+14), font, 0.45, (0,160,0), 1, cv2.LINE_AA)
    cv2.imwrite(os.path.join(WORK, name), c, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    print(name, c.shape)
crop(450, 450, 2350, 1450, 0.62, "rk_north.png")
crop(400, 1150, 1600, 1800, 0.94, "rk_central.png")
crop(1250, 1150, 2400, 1900, 0.94, "rk_east.png")
crop(900, 1850, 2000, 2950, 1.0, "rk_south.png")
crop(1500, 2050, 2600, 3200, 0.86, "rk_se.png")
crop(250, 2200, 1400, 3463, 0.85, "rk_west.png")
