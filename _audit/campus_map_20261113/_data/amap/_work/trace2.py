import cv2, numpy as np, os, heapq, json, time
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
im = cv2.imread(os.path.join(BASE, "master.png"))
H, W = im.shape[:2]
dist = np.load(os.path.join(WORK, "thin_dist.npy")).astype(np.float32)
DIRS = [(1,0,1.0),(-1,0,1.0),(0,1,1.0),(0,-1,1.0),(1,1,1.41421),(1,-1,1.41421),(-1,1,1.41421),(-1,-1,1.41421)]

def build_cost(target):
    c = 1.0 + np.minimum((dist - target)**2, 900.0) * 0.15 + np.maximum(dist - 10.0, 0.0) * 0.6
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
        if n % 300000 == 0 and time.time()-t0 > maxsec:
            return None, "timeout"
        for dx, dy, dc in DIRS:
            nx, ny = x+dx, y+dy
            if nx < 0 or ny < 0 or nx >= W or ny >= H or done[ny, nx]: continue
            ng = g + dc*float(cost[ny, nx])
            if ng < gs[ny, nx]:
                gs[ny, nx] = ng; prev[ny, nx] = y*W+x
                heapq.heappush(pq, (ng + abs(gx-nx)+abs(gy-ny), ng, nx, ny))
    if prev[gy, gx] < 0 and (gx != sx or gy != sy):
        return None, "nopath"
    path = []; cx, cy = gx, gy
    while True:
        path.append((cx, cy))
        if cx == sx and cy == sy: break
        p = int(prev[cy, cx])
        if p < 0: break
        cx, cy = p % W, p // W
    path.reverse()
    return path, {"n": n, "secs": time.time()-t0}

def resample(path, step=10.0):
    pts = np.array(path, np.float64)
    # cumulative length
    d = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(d)])
    L = s[-1]
    if L < 1: return pts
    ns = np.arange(0, L, step)
    if ns[-1] < L: ns = np.append(ns, L)
    xs = np.interp(ns, s, pts[:, 0]); ys = np.interp(ns, s, pts[:, 1])
    return np.stack([xs, ys], axis=1)

def smooth_path(path, step=10.0, med_win=5, gauss_sigma=6.0):
    pts = resample(path, step)
    if len(pts) < med_win+2: return pts
    # median filter coordinates (removes spikes/detours)
    x = pts[:, 0].copy(); y = pts[:, 1].copy()
    hw = med_win//2
    xm = x.copy(); ym = y.copy()
    for i in range(len(x)):
        a = max(0, i-hw); b = min(len(x), i+hw+1)
        xm[i] = np.median(x[a:b]); ym[i] = np.median(y[a:b])
    k = int(3*gauss_sigma)
    g = np.exp(-0.5*((np.arange(-k, k+1))/gauss_sigma)**2); g /= g.sum()
    xs = np.convolve(np.pad(xm, k, mode="edge"), g, mode="valid")
    ys = np.convolve(np.pad(ym, k, mode="edge"), g, mode="valid")
    # keep endpoints exact
    xs[0], ys[0] = pts[0, 0], pts[0, 1]
    xs[-1], ys[-1] = pts[-1, 0], pts[-1, 1]
    return np.stack([xs, ys], axis=1)

def polyline(pts, eps=2.0, min_step=45, max_step=120):
    arr = pts.astype(np.float32).reshape(-1, 1, 2)
    ap = cv2.approxPolyDP(arr, eps, False).reshape(-1, 2)
    out = [ap[0]]
    for i in range(1, len(ap)):
        p = out[-1]; q = ap[i]
        d = np.linalg.norm(q-p)
        if d > max_step:
            nseg = int(np.ceil(d/max_step))
            for kk in range(1, nseg):
                out.append(p + (q-p)*kk/nseg)
        out.append(q)
    res = [out[0]]
    for p in out[1:]:
        if np.linalg.norm(p-res[-1]) >= min_step or p is out[-1]:
            res.append(p)
    # ensure last point present
    if not np.allclose(res[-1], out[-1]):
        res.append(out[-1])
    return [[round(float(a), 1), round(float(b), 1)] for a, b in res]

draft = json.load(open(os.path.join(WORK, "roads_draft2.json"), encoding="utf-8"))
paths = {}
for road in draft:
    name = road["name"]; target = road["target"]; via = road["via"]
    full = []; ok = True; infos = []
    for i in range(len(via)-1):
        p, meta = astar(via[i], via[i+1], target)
        if p is None:
            print(name, "FAIL seg", i, via[i], via[i+1], meta); ok = False; break
        infos.append(meta)
        if full: p = p[1:]
        full += p
    if ok and len(full) > 5:
        sm = smooth_path(full)
        simp = polyline(sm)
        paths[name] = {"raw": len(full), "simplified": simp, "smooth": [[round(float(a),1), round(float(b),1)] for a,b in sm[::5]]}
        print("%-8s OK raw=%d simp=%d  secs=%.1f" % (name, len(full), len(simp), sum(x["secs"] for x in infos)))
    else:
        print(name, "FAILED")
json.dump(paths, open(os.path.join(WORK, "traced_paths.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved", len(paths), "roads")
