import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
m = cv2.imread(os.path.join(BASE, "master.png"))
def save(img, x0, y0, x1, y1, scale, name, grid=True):
    c = cv2.resize(img[y0:y1, x0:x1], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    font = cv2.FONT_HERSHEY_SIMPLEX
    if grid:
        ch, cw = c.shape[:2]
        for x in range(x0//50*50, x1+1, 100):
            if x < x0: continue
            px = int((x-x0)*scale)
            if 0 <= px < cw:
                cv2.line(c, (px,0), (px,ch-1), (0,0,255), 1)
                for yy in (18, ch-4): cv2.putText(c, str(x), (px+2,yy), font, 0.6, (0,0,255), 2, cv2.LINE_AA)
        for y in range(y0//50*50, y1+1, 100):
            if y < y0: continue
            py = int((y-y0)*scale)
            if 0 <= py < ch:
                cv2.line(c, (0,py), (cw-1,py), (0,0,255), 1)
                for xx in (4, cw-50): cv2.putText(c, str(y), (xx,py+18), font, 0.6, (0,0,255), 2, cv2.LINE_AA)
    cv2.putText(c, name, (8, 40), font, 0.9, (0,0,255), 2, cv2.LINE_AA)
    cv2.imwrite(os.path.join(WORK, name + ".png"), c, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    print(name, c.shape)
save(m, 2040, 1980, 2340, 2180, 4.0, "U_xuefu_label_check")
save(m, 2350, 1380, 2650, 1620, 4.0, "V_dongcemen_check")
