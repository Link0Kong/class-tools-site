import cv2, numpy as np, os, json
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
im = cv2.imread(os.path.join(BASE, "master.png"))
d = json.load(open(os.path.join(BASE, "roads_trace.json"), encoding="utf-8"))
by = {r["name"]: np.array(r["points"]) for r in d["roads"]}
def crop(x0, y0, x1, y1, scale, name, roads, grid=100):
    c = im[y0:y1, x0:x1].copy()
    c = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    font = cv2.FONT_HERSHEY_SIMPLEX
    colors = [(255,0,0),(0,0,255),(0,180,0),(255,0,255),(0,140,255)]
    for i, rn in enumerate(roads):
        if rn not in by: continue
        pts = (by[rn] - np.array([x0, y0])) * scale
        cv2.polylines(c, [pts.astype(np.int32)], False, colors[i % 5], 2, cv2.LINE_AA)
    ch, cw = c.shape[:2]
    for x in range(x0//50*50, x1+1, grid):
        if x < x0: continue
        px = int((x-x0)*scale)
        if 0 <= px < cw:
            cv2.line(c, (px,0), (px,ch-1), (0,200,0), 1)
            for yy in (16, ch//2, ch-4): cv2.putText(c, str(x), (px+2,yy), font, 0.5, (0,150,0), 1, cv2.LINE_AA)
    for y in range(y0//50*50, y1+1, grid):
        if y < y0: continue
        py = int((y-y0)*scale)
        if 0 <= py < ch:
            cv2.line(c, (0,py), (cw-1,py), (0,200,0), 1)
            for xx in (4, cw//2, cw-60): cv2.putText(c, str(y), (xx,py+16), font, 0.5, (0,150,0), 1, cv2.LINE_AA)
    cv2.imwrite(os.path.join(WORK, name), c, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    print(name, c.shape)
crop(1800, 620, 2350, 1120, 2.0, "zz_xyb_east.png", ["修园北路"])
crop(2020, 1150, 2480, 1480, 2.2, "zz_wangguo_e.png", ["望果东路", "修园北路"])
