# -*- coding: utf-8 -*-
"""r11: chamfer/ICP fit of old-model building polygons to master building mask.

Gives robust similarity + affine initialisation; saves visual overlay.
"""
import os, json, math
import cv2, numpy as np
from scipy.optimize import minimize

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
DATA = os.path.dirname(AMAP)
WORK = os.path.join(AMAP, "_work2")
im = cv2.imread(os.path.join(AMAP, "master.png"))
H, W = im.shape[:2]
raw = json.load(open(os.path.join(WORK, "extract_raw.json"), encoding="utf-8"))
old = json.load(open(os.path.join(DATA, "preview_data.json"), encoding="utf-8"))
feats = {f["id"]: f for f in old["features"]}
blds = [b for b in old["buildings"]]

# master building mask: rebuild exact same way as r10
RGB = cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.int16)
R, G, B = RGB[:, :, 0], RGB[:, :, 1], RGB[:, :, 2]
d = np.maximum.reduce([np.abs(R - 217), np.abs(G - 227), np.abs(B - 236)])
bm = (d <= 10).astype(np.uint8)
bm = cv2.morphologyEx(bm, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
bm = cv2.morphologyEx(bm, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
DT = cv2.distanceTransform(1 - bm, cv2.DIST_L2, 5)
DT = np.minimum(DT, 30.0)
print("building mask px", int(bm.sum()))

# sample points from old building polygon edges
pts = []
for b in blds:
    f = feats.get(b["id"])
    if not f:
        continue
    p = np.array(f["p"], np.float32)
    for i in range(len(p)):
        a = p[i]; c = p[(i + 1) % len(p)]
        n = max(2, int(np.hypot(*(c - a)) / 1.5))
        for t in np.linspace(0, 1, n, endpoint=False):
            pts.append(a + (c - a) * t)
P = np.array(pts, np.float32)
print("chamfer sample points", len(P))
# subsample for speed
idx = np.random.default_rng(1).choice(len(P), size=min(9000, len(P)), replace=False)
PS = P[idx]

DTi = cv2.remap(DT.astype(np.float32), np.zeros((1, 1), np.float32), np.zeros((1, 1), np.float32), cv2.INTER_LINEAR)  # noop
def sample_dt(xy):
    x = np.clip(xy[:, 0], 0, W - 1).astype(np.float32)
    y = np.clip(xy[:, 1], 0, H - 1).astype(np.float32)
    mapx = x.reshape(1, -1); mapy = y.reshape(1, -1)
    v = cv2.remap(DT, mapx, mapy, cv2.INTER_LINEAR)
    return v.ravel()

def tf_sim(params):
    s, th, tx, ty = params
    c, si = math.cos(th), math.sin(th)
    A = s * np.array([[c, -si, 0], [si, c, 0]], np.float64)
    A[0, 2] = tx; A[1, 2] = ty
    return A

def cost_sim(params):
    A = tf_sim(params)
    xy = PS @ A[:, :2].T + A[:, 2]
    v = sample_dt(xy)
    return float(np.mean(np.minimum(v, 18.0)))

p0 = np.array([4.8943, math.radians(-53.86), -997.8, 2460.4])
print("initial cost", cost_sim(p0))
res = minimize(cost_sim, p0, method="Nelder-Mead",
               options={"maxiter": 8000, "xatol": 1e-4, "fatol": 1e-5, "adaptive": True})
print("sim fit", res.x, "cost", res.fun, "nit", res.nit)
p = res.x
A_sim = tf_sim(p)
print("A_sim=\n", np.round(A_sim, 4))

def tf_aff(params):
    return np.array([[params[0], params[1], params[4]],
                     [params[2], params[3], params[5]]], np.float64)

def cost_aff(params):
    A = tf_aff(params)
    xy = PS @ A[:, :2].T + A[:, 2]
    v = sample_dt(xy)
    return float(np.mean(np.minimum(v, 18.0)))

q0 = np.array([A_sim[0, 0], A_sim[0, 1], A_sim[1, 0], A_sim[1, 1], A_sim[0, 2], A_sim[1, 2]])
res2 = minimize(cost_aff, q0, method="Nelder-Mead",
                options={"maxiter": 20000, "xatol": 1e-4, "fatol": 1e-5, "adaptive": True})
print("affine fit", np.round(res2.x, 4), "cost", res2.fun, "nit", res2.nit)
A_aff = tf_aff(res2.x)

json.dump({"sim": A_sim.tolist(), "aff": A_aff.tolist(),
           "sim_cost": res.fun, "aff_cost": res2.fun},
          open(os.path.join(WORK, "chamfer_fit.json"), "w"))

# ---- visual check: draw old building polygons transformed onto master ----
vis = im.copy()
b2 = bm > 0
vis[b2] = (200, 220, 255)
for b in blds:
    f = feats.get(b["id"])
    if not f:
        continue
    p = np.array(f["p"], np.float64)
    xy = p @ A_aff[:, :2].T + A_aff[:, 2]
    cv2.polylines(vis, [xy.astype(np.int32).reshape(-1, 1, 2)], True, (0, 0, 255), 2)
    c = xy.mean(0).astype(int)
    cv2.putText(vis, b["id"], tuple(c), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
cv2.imwrite(os.path.join(WORK, "d_chamfer_aff.png"),
            cv2.resize(vis, (1500, int(H * 1500.0 / W)), interpolation=cv2.INTER_AREA))
# 2 half crops at higher res for checking
vis2 = im.copy()
for b in blds:
    f = feats.get(b["id"])
    if not f:
        continue
    p = np.array(f["p"], np.float64)
    xy = p @ A_aff[:, :2].T + A_aff[:, 2]
    cv2.polylines(vis2, [xy.astype(np.int32).reshape(-1, 1, 2)], True, (0, 0, 255), 2)
    c = xy.mean(0).astype(int)
    cv2.putText(vis2, b["id"], tuple(c), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
cv2.imwrite(os.path.join(WORK, "d_chamfer_top.png"), vis2[600:1800, 500:2200])
cv2.imwrite(os.path.join(WORK, "d_chamfer_bottom.png"), vis2[1900:3300, 200:2100])
print("saved")
