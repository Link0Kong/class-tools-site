import cv2, numpy as np, os, json
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
im = cv2.imread(os.path.join(BASE, "master.png"))
H, W = im.shape[:2]
paths = json.load(open(os.path.join(WORK, "traced_paths.json"), encoding="utf-8"))
PALETTE = [
    (0,0,255),(0,128,255),(0,200,0),(255,0,0),(255,0,255),(0,255,255),(128,0,128),
    (0,100,0),(255,128,0),(128,64,0),(200,0,120),(0,64,200),(0,180,120),(100,100,255),
]
vis = im.copy()
order = list(paths.keys())
for i, name in enumerate(order):
    pts = np.array(paths[name]["simplified"], np.float64)
    c = PALETTE[i % len(PALETTE)]
    cv2.polylines(vis, [np.round(pts).astype(np.int32)], False, c, 4, cv2.LINE_AA)
    mid = pts[len(pts)//2]
    cv2.putText(vis, name, (int(mid[0])+6, int(mid[1])-6), cv2.FONT_HERSHEY_SIMPLEX, 0.9, c, 2, cv2.LINE_AA)
small = cv2.resize(vis, None, fx=0.42, fy=0.42, interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK, "trace_overview.png"), small)
# crops for detail
def crop(x0,y0,x1,y1,scale,name):
    c = vis[max(0,y0):min(H,y1), max(0,x0):min(W,x1)].copy()
    c = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    ch, cw = c.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    for x in range(x0//100*100, x1+1, 100):
        if x < x0: continue
        px = int((x-x0)*scale)
        if not (0 <= px < cw): continue
        cv2.line(c, (px,0), (px,ch-1), (0,0,255), 1)
        cv2.putText(c, str(x), (px+2, 14), font, 0.5, (0,0,255), 1, cv2.LINE_AA)
        cv2.putText(c, str(x), (px+2, ch-3), font, 0.5, (0,0,255), 1, cv2.LINE_AA)
    for y in range(y0//100*100, y1+1, 100):
        if y < y0: continue
        py = int((y-y0)*scale)
        if not (0 <= py < ch): continue
        cv2.line(c, (0,py), (cw-1,py), (0,0,255), 1)
        cv2.putText(c, str(y), (3, py+14), font, 0.5, (0,0,255), 1, cv2.LINE_AA)
        cv2.putText(c, str(y), (cw-60, py+14), font, 0.5, (0,0,255), 1, cv2.LINE_AA)
    cv2.imwrite(os.path.join(WORK, name), c, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    print(name, c.shape)
crop(400, 1150, 1600, 1800, 1.0, "chk_central_n.png")
crop(1250, 1400, 2350, 2050, 1.0, "chk_east.png")
crop(900, 1950, 2000, 2950, 1.0, "chk_south.png")
crop(700, 2750, 2600, 3463, 0.75, "chk_sw_se.png")
crop(500, 450, 2350, 1450, 0.75, "chk_north.png")
print("done")
