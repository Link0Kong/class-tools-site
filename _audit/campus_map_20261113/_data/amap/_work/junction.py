import cv2, numpy as np, os, json
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
im = cv2.imread(os.path.join(BASE, "master.png"))
vis = np.load(os.path.join(WORK, "thin_vis.npy"))
paths = json.load(open(os.path.join(WORK, "traced_paths.json"), encoding="utf-8"))
colors = {"修园东路": (0, 128, 255), "杏林大道": (255, 0, 255), "学府北路": (0, 0, 255), "学府西路": (0, 128, 0), "仲景西路": (0, 255, 255), "仲景东路": (128, 0, 128)}
x0, y0, x1, y1, s = 1250, 2050, 1900, 2650, 1.55
c = vis[y0:y1, x0:x1].copy()
c = cv2.resize(c, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST)
for name, pts in paths.items():
    if name not in colors: continue
    arr = np.array(pts["simplified"], np.float64)
    arr = ((arr - np.array([x0, y0])) * s).astype(np.int32)
    cv2.polylines(c, [arr], False, colors[name], 3, cv2.LINE_AA)
font = cv2.FONT_HERSHEY_SIMPLEX
ch, cw = c.shape[:2]
for x in range(x0//100*100, x1+1, 100):
    if x < x0: continue
    px = int((x-x0)*s)
    if 0 <= px < cw:
        cv2.line(c, (px,0), (px,ch-1), (0,0,255), 1)
        for yy in (16, ch//2, ch-4): cv2.putText(c, str(x), (px+2,yy), font, 0.55, (0,0,255), 1, cv2.LINE_AA)
for y in range(y0//100*100, y1+1, 100):
    if y < y0: continue
    py = int((y-y0)*s)
    if 0 <= py < ch:
        cv2.line(c, (0,py), (cw-1,py), (0,0,255), 1)
        for xx in (4, cw//2, cw-60): cv2.putText(c, str(y), (xx,py+16), font, 0.55, (0,0,255), 1, cv2.LINE_AA)
cv2.imwrite(os.path.join(WORK, "AA_libjunction.png"), c, [cv2.IMWRITE_PNG_COMPRESSION, 6])
print(c.shape)
