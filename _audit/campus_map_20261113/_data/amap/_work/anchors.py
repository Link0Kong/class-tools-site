import cv2, numpy as np, os, json

BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
master = cv2.imread(os.path.join(BASE, "master.png"))
south = cv2.imread(os.path.join(BASE, "amap_south.jpg"))
west = cv2.imread(os.path.join(BASE, "amap_west.jpg"))
north = cv2.imread(os.path.join(BASE, "amap_north.jpg"))
Msn = np.load(os.path.join(WORK, "Msn.npy"))  # south -> north
Mws = np.load(os.path.join(WORK, "Mws.npy"))  # west -> south
Mwn = np.load(os.path.join(WORK, "Mwn.npy"))  # west -> north
DX = 137.0
def H34(M, dx=DX, dy=0.0):
    return np.array([[M[0,0], M[0,1], M[0,2]+dx], [M[1,0], M[1,1], M[1,2]+dy], [0,0,1]], np.float64)
Ms_m = H34(Msn)          # south -> master
Mw_m = H34(Mwn)          # west -> master
Ms_inv = np.linalg.inv(Ms_m)
Mw_inv = np.linalg.inv(Mw_m)

def to_master(P, src):
    M = {"south": Ms_m, "west": Mw_m, "north": H34(np.array([[1.,0,0],[0,1.,0]]))}[src]
    return cv2.perspectiveTransform(np.array(P, np.float64).reshape(-1,1,2), M).reshape(-1,2)

def measure(master_pt, src):
    """template-match a patch from master into source image; return measured source point"""
    M_inv = {"south": Ms_inv, "west": Mw_inv}[src]
    p = np.array(master_pt, np.float64)
    # scale factor source px per master px
    M = {"south": Ms_m, "west": Mw_m}[src]
    s = M[0,0]
    half = 34
    x, y = int(round(p[0])), int(round(p[1]))
    patch = master[y-half:y+half+1, x-half:x+half+1]
    if patch.shape[0] != 2*half+1 or patch.shape[1] != 2*half+1: return None
    # predicted source point
    pp = cv2.perspectiveTransform(p.reshape(1,1,2), M_inv).reshape(-1)[:2]
    # patch in source scale
    pw = int(round(patch.shape[1]/s)); ph = int(round(patch.shape[0]/s))
    patch_r = cv2.resize(patch, (pw, ph), interpolation=cv2.INTER_AREA if s > 1 else cv2.INTER_LINEAR)
    win_x = pw//2 + 14; win_y = ph//2 + 14
    sx, sy = int(round(pp[0])), int(round(pp[1]))
    img = {"south": south, "west": west}[src]
    Hh, Ww = img.shape[:2]
    x0 = max(0, sx-win_x); y0 = max(0, sy-win_y); x1 = min(Ww, sx+win_x+1); y1 = min(Hh, sy+win_y+1)
    search = img[y0:y1, x0:x1]
    if search.shape[0] < ph or search.shape[1] < pw: return None
    res = cv2.matchTemplate(search, patch_r, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(res)
    cx = x0 + loc[0] + pw/2.0; cy = y0 + loc[1] + ph/2.0
    score = mx
    # residual in master px: map measured source point to master and compare
    meas_m = cv2.perspectiveTransform(np.array([[cx, cy]], np.float64).reshape(-1,1,2), M).reshape(-1)[:2]
    res_px = float(np.linalg.norm(meas_m - p))
    return {"src_measured": [round(float(cx),1), round(float(cy),1)],
            "src_predicted": [round(float(pp[0]),1), round(float(pp[1]),1)],
            "master_measured": [round(float(meas_m[0]),1), round(float(meas_m[1]),1)],
            "residual_master_px": round(res_px, 2), "score": round(float(score),3)}

landmarks = [
    ("图书馆", (1240,2155)),
    ("五行楼", (1845,1222)),
    ("精诚楼", (1265,1405)),
    ("至善楼", (1810,1400)),
    ("厚德楼", (990,1630)),
    ("自强楼", (1725,1650)),
    ("明德楼", (1880,2055)),
    ("河洛时光", (1240,1790)),
    ("23号楼", (1245,745)),
    ("棋盘广场", (1100,2640)),
    ("成人教育学院", (1440,2810)),
    ("学生服务中心", (1010,2880)),
    ("13号楼", (430,2830)),
    ("16号楼", (790,2960)),
    ("东南门(环岛)", (1782,2537)),
    ("大学生创新", (1560,2600)),
]
anchors = []
for name, p in landmarks:
    rec = {"name": name, "master": [float(p[0]), float(p[1])], "north": None, "south": None, "west": None}
    # which images contain it
    nh, nw = north.shape[:2]; sh, sw = south.shape[:2]; wh, ww = west.shape[:2]
    pn = to_master(p, "north")[0]
    ps = cv2.perspectiveTransform(np.array([p], np.float64).reshape(-1,1,2), Ms_inv).reshape(-1)[:2]
    pw = cv2.perspectiveTransform(np.array([p], np.float64).reshape(-1,1,2), Mw_inv).reshape(-1)[:2]
    if 0 <= pn[0] < nw and 0 <= pn[1] < nh:
        rec["north"] = [round(float(pn[0]),1), round(float(pn[1]),1)]
    for src, pt, img in (("south", ps, south), ("west", pw, west)):
        hh, ww2 = img.shape[:2]
        if 0 <= pt[0] < ww2 and 0 <= pt[1] < hh:
            rec[src] = [round(float(pt[0]),1), round(float(pt[1]),1)]
            m = measure(p, src)
            if m: rec[src+"_check"] = m
    anchors.append(rec)
json.dump(anchors, open(os.path.join(WORK, "anchors.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for a in anchors:
    print(a["name"], "master", a["master"])
    for src in ("south", "west"):
        if src+"_check" in a:
            c = a[src+"_check"]
            print("   %s pred %s meas %s resid %.2f px score %.2f" % (src, c["src_predicted"], c["src_measured"], c["residual_master_px"], c["score"]))
