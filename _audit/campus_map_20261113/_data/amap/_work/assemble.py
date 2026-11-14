import cv2, numpy as np, os, heapq, json, time

BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
im = cv2.imread(os.path.join(BASE, "master.png"))
H, W = im.shape[:2]
dist = np.load(os.path.join(WORK, "thin_dist.npy")).astype(np.float32)
DIRS = [(1,0,1.0),(-1,0,1.0),(0,1,1.0),(0,-1,1.0),(1,1,1.41421),(1,-1,1.41421),(-1,1,1.41421),(-1,-1,1.41421)]

def build_cost(target):
    c = 1.0 + np.minimum((dist - target)**2, 900.0)*0.15 + np.maximum(dist - 10.0, 0.0)*0.6
    return np.minimum(c, 60.0).astype(np.float32)

def snap(x, y, target, r=7):
    x = int(round(x)); y = int(round(y)); best = None
    for dy in range(-r, r+1):
        for dx in range(-r, r+1):
            xx, yy = x+dx, y+dy
            if 0 <= xx < W and 0 <= yy < H:
                c = abs(float(dist[yy, xx]) - target)
                if best is None or c < best[0]:
                    best = (c, xx, yy)
    return best[1], best[2]

def astar(p0, p1, target, maxsec=25.0):
    cost = build_cost(target)
    sx, sy = snap(*p0, target); gx, gy = snap(*p1, target)
    INF = 1e9
    gs = np.full((H, W), INF, dtype=np.float32)
    prev = np.full((H, W), -1, dtype=np.int64)
    gs[sy, sx] = 0.0
    pq = [(abs(gx-sx)+abs(gy-sy), 0.0, sx, sy)]
    done = np.zeros((H, W), dtype=bool)
    t0 = time.time(); n = 0
    while pq:
        f, g, x, y = heapq.heappop(pq)
        if done[y, x]: continue
        done[y, x] = True; n += 1
        if x == gx and y == gy: break
        if n % 300000 == 0 and time.time()-t0 > maxsec: return None
        for dx, dy, dc in DIRS:
            nx, ny = x+dx, y+dy
            if nx < 0 or ny < 0 or nx >= W or ny >= H or done[ny, nx]: continue
            ng = g + dc*float(cost[ny, nx])
            if ng < gs[ny, nx]:
                gs[ny, nx] = ng; prev[ny, nx] = y*W+x
                heapq.heappush(pq, (ng + abs(gx-nx)+abs(gy-ny), ng, nx, ny))
    if prev[gy, gx] < 0 and (gx != sx or gy != sy): return None
    path = []; cx, cy = gx, gy
    while True:
        path.append((cx, cy))
        if cx == sx and cy == sy: break
        p = int(prev[cy, cx])
        if p < 0: break
        cx, cy = p % W, p // W
    path.reverse()
    return path

def resample(path, step=10.0):
    pts = np.array(path, np.float64)
    d = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(d)]); L = s[-1]
    if L < 1: return pts
    ns = np.arange(0, L, step)
    if len(ns) == 0 or ns[-1] < L: ns = np.append(ns, L)
    return np.stack([np.interp(ns, s, pts[:, 0]), np.interp(ns, s, pts[:, 1])], axis=1)

def smooth_path(path):
    pts = resample(path, 10.0)
    if len(pts) < 8: return pts
    x, y = pts[:, 0].copy(), pts[:, 1].copy()
    hw = 2
    xm, ym = x.copy(), y.copy()
    for i in range(len(x)):
        a, b = max(0, i-hw), min(len(x), i+hw+1)
        xm[i], ym[i] = np.median(x[a:b]), np.median(y[a:b])
    sigma = 6.0; k = int(3*sigma)
    g = np.exp(-0.5*((np.arange(-k, k+1))/sigma)**2); g /= g.sum()
    xs = np.convolve(np.pad(xm, k, mode="edge"), g, mode="valid")
    ys = np.convolve(np.pad(ym, k, mode="edge"), g, mode="valid")
    xs[0], ys[0] = pts[0]; xs[-1], ys[-1] = pts[-1]
    return np.stack([xs, ys], axis=1)

def to_polyline(pts, eps=2.0, min_step=42, max_step=110):
    ap = cv2.approxPolyDP(pts.astype(np.float32).reshape(-1, 1, 2), eps, False).reshape(-1, 2)
    out = [ap[0]]
    for i in range(1, len(ap)):
        p, q = out[-1], ap[i]
        d = np.linalg.norm(q-p)
        if d > max_step:
            nseg = int(np.ceil(d/max_step))
            for kk in range(1, nseg):
                out.append(p + (q-p)*kk/nseg)
        out.append(q)
    res = [out[0]]
    for p in out[1:]:
        if p is out[-1] or np.linalg.norm(p-res[-1]) >= min_step:
            res.append(p)
    if not np.allclose(res[-1], out[-1]): res.append(out[-1])
    return [[round(float(a), 1), round(float(b), 1)] for a, b in res]

def trace_via(via, target):
    full = []
    for i in range(len(via)-1):
        p = astar(via[i], via[i+1], target)
        if p is None:
            print("  WARN astar seg fail", via[i], via[i+1]); return None
        if full: p = p[1:]
        full += p
    return full

def interp_line(pts, step=80):
    pts = np.array(pts, np.float64)
    out = [pts[0]]
    for i in range(1, len(pts)):
        d = np.linalg.norm(pts[i]-out[-1])
        if d > step:
            n = int(np.ceil(d/step))
            for k in range(1, n):
                out.append(out[-1] + (pts[i]-out[-1])/n)
        out.append(pts[i])
    return [[round(float(a), 1), round(float(b), 1)] for a, b in out]

print("retrace 修园西路 ...")
xyx = trace_via([[700,1300],[675,1420],[662,1540],[660,1680],[668,1820],[685,1960],[700,2100],
                 [700,2200],[700,2300],[712,2400],[728,2500],[748,2600],[765,2700],[778,2800],[790,2900]], 3.5)
xyx_pts = to_polyline(smooth_path(xyx)) if xyx else None
print("  修园西路 pts:", len(xyx_pts) if xyx_pts else None)

traced = json.load(open(os.path.join(WORK, "traced_paths.json"), encoding="utf-8"))

def T(name):
    return [[round(float(a), 1), round(float(b), 1)] for a, b in np.array(traced[name]["simplified"], np.float64)]

# ---------- final road table ----------
roads = []
def add(name, pts, width_px, wclass, conf, note=""):
    roads.append({"name": name, "points": pts, "width_px": width_px, "width_class": wclass,
                  "confidence": conf, "note": note})

# 1 修园北路 (traced, high)
add("修园北路", T("修园北路"), 11, "secondary", "high",
    "环湖路北段，沿湖岸自西北向东北，东端接修园北路小环岛")

# 2 修园东路 (traced, high) - wide diagonal
p = T("修园东路")
add("修园东路", p, 14, "primary", "high",
    "自修园北路小环岛向西南的宽幅斜向主干路，经明德楼西侧、图书馆西侧；标签出现3处")

# 3 修园西路 (retraced)
if xyx_pts:
    add("修园西路", xyx_pts, 10, "secondary", "medium",
        "沿湖西岸自望果西路交叉口向南；南段进入西区宿舍区，走向不确定")
else:
    add("修园西路", T("修园西路")[:12], 10, "secondary", "low", "沿湖西岸，南段未定")

# 4 望果西路 (traced) - split at x=1225
w_res = T("望果西路")
add("望果西路", w_res, 10, "secondary", "medium",
    "湖西侧东西向次干路；名称分界点约在 x=1225（未见路口标志，按标签推断）")

# 5 望果东路
add("望果东路", T("望果东路"), 10, "secondary", "medium",
    "东西向次干路，东端接入修园北路小环岛")

# 6 银杏西路
yxs = T("银杏西路")
# fix detour at end: keep points until x<1390 then straight to 1508,1505
pts = [pp for pp in yxs if pp[0] < 1390]
pts += [[1445, 1520], [1508, 1505]]
add("银杏西路", pts, 10, "secondary", "high", "西起修园西路，东至仲景路；名称分界约 x=1430")

# 7 银杏东路 (manual straighten)
add("银杏东路", interp_line([[1508,1505],[1650,1510],[1850,1515],[2050,1519],[2105,1521]]), 10, "secondary", "high",
    "自仲景路向东，东端接修园东路斜向主干路")

# 8 仲景路
add("仲景路", T("仲景路"), 9, "tertiary", "high", "南北向支路，望果东路←→银杏东路")

# 9 仲景西路
add("仲景西路", [[1502,1688],[1468,1712],[1449,1750],[1448,1830],[1448,1920],[1449,2010],[1450,2100]], 8, "tertiary", "low",
    "仲景路西分支，南北向；南端去向不确定（与杏林大道/图书馆南环路相交处难辨）")

# 10 仲景东路
add("仲景东路", [[1502,1688],[1494,1760],[1486,1850],[1483,1950],[1483,2050]], 8, "tertiary", "low",
    "仲景路东分支，南北向；南端去向不确定")

# 11 杏林大道
add("杏林大道", interp_line([[1372,2372],[1440,2320],[1520,2270],[1600,2220],[1680,2180],[1755,2140],[1830,2100]]), 12, "primary", "low",
    "图书馆南侧斜向主干道，西南端接修园东路，东北端去向不确定（未出图）")

# 12 学府北路 (NE + roundabout + SE), manual centerline from mask probes
xuefu_n = [[2880,1052],[2770,1200],[2695,1300],[2620,1400],[2534,1500],[2456,1600],[2382,1700],
           [2298,1800],[2229,1900],[2155,2000],[2083,2100],[2016,2200],[1937,2300],[1871,2400],[1831,2480],[1806,2510]]
xuefu_se = [[1815,2530],[1850,2560],[1885,2600],[1960,2660],[2025,2700],[2090,2760],[2149,2800],
            [2225,2860],[2301,2900],[2380,2960],[2440,3000],[2478,3035]]
xuefu = interp_line(xuefu_n + xuefu_se, 60)
add("学府北路", xuefu, 42, "arterial", "high",
    "城市主干道（带中央绿化带）：东北端入图处→东侧门→东南门环岛→东南（西南2门/北2门/东北门方向），东南端止于覆盖边界")

# 13 学府西路
xx = [[1780,2530],[1750,2555],[1734,2600],[1658,2700],[1584,2800],[1509,2900],[1434,3000],
      [1365,3100],[1300,3200],[1240,3300],[1180,3400],[1140,3455]]
add("学府西路", interp_line(xx, 60), 34, "arterial", "high",
    "城市主干道：东南门环岛向西南，经东南2门，出图于覆盖边界；与学府北路在环岛相接")

out = {"master_size": [W, H], "north_offset": [137, 0],
       "coordinate_note": "除特别说明外所有坐标为 master.png 像素坐标（北向上）。master = amap_north 坐标系 +(137,0)。",
       "roads": roads}
json.dump(out, open(os.path.join(BASE, "roads_trace.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("roads written:", len(roads))

# ---------- check image ----------
PAL = [
    (0,0,230),(0,140,255),(0,170,0),(200,0,0),(200,0,200),(0,190,190),(120,0,120),
    (0,90,0),(220,120,0),(110,60,0),(160,0,100),(0,60,170),(0,150,110),(90,90,230),
]
overlay = im.copy()
for i, r in enumerate(roads):
    pts = np.array(r["points"], np.float64)
    c = PAL[i % len(PAL)]
    cv2.polylines(overlay, [np.round(pts).astype(np.int32)], False, c, 3, cv2.LINE_AA)
    mid = pts[len(pts)//2]
    cv2.putText(overlay, r["name"], (int(mid[0])+8, int(mid[1])-8), cv2.FONT_HERSHEY_SIMPLEX, 1.0, c, 2, cv2.LINE_AA)
check = cv2.addWeighted(overlay, 0.55, im, 0.45, 0)
cv2.imwrite(os.path.join(BASE, "roads_check.png"), check, [cv2.IMWRITE_PNG_COMPRESSION, 6])
print("roads_check.png", check.shape)
