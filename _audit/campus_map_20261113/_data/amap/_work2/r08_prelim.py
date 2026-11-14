# -*- coding: utf-8 -*-
"""Preliminary similarity fit from a few hand-identified label pairs, then
project all old building centres and list nearest detected POI icons."""
import os, json, math
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(AMAP, "_work2")
DATA = os.path.dirname(AMAP)
old = json.load(open(os.path.join(DATA, "preview_data.json"), encoding="utf-8"))
bld = {b["id"]: b for b in old["buildings"]}
icons = [tuple(c[:2]) for c in json.load(open(os.path.join(WORK, "poi_icons.json")))]

# preliminary correspondences: old-model points -> master icon centres
prelim = [
    ("B32", (1848.9, 1200.5), "五行楼 complex label"),
    ("B36", (1787.4, 1399.6), "至善楼 complex label"),
    ("B50", (1252.7, 2154.0), "图书馆 label"),
    ("B59", (1883.6, 2065.5), "明德楼 label"),
    ("B70", (431.1, 1442.3), "体育馆 label?"),
]
P = np.array([[bld[i]["x"], bld[i]["y"]] for i, _, _ in prelim], float)
Q = np.array([q for _, q, _ in prelim], float)

def fit_sim(P, Q):
    # least squares similarity: Q = s R P + t
    pc = P.mean(0); qc = Q.mean(0)
    P0 = P - pc; Q0 = Q - qc
    # complex least squares
    a = (P0[:, 0] * Q0[:, 0] + P0[:, 1] * Q0[:, 1]).sum()
    b = (P0[:, 0] * Q0[:, 1] - P0[:, 1] * Q0[:, 0]).sum()
    den = (P0 ** 2).sum()
    s = math.hypot(a, b) / den
    th = math.atan2(b, a)
    R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    t = qc - s * R @ pc
    M = np.hstack([s * R, t.reshape(-1, 1)])
    return M, s, math.degrees(th), t

M, s, th, t = fit_sim(P, Q)
print("prelim similarity: s=%.4f rot=%.2f deg t=(%.1f,%.1f)" % (s, th, t[0], t[1]))
Qp = cv2.transform(P.reshape(-1, 1, 2), M).reshape(-1, 2)
for (bid, q, name), qp in zip(prelim, Qp):
    print("  %s %-12s -> (%7.1f,%7.1f) vs (%7.1f,%7.1f) err %5.1f" %
          (bid, bld[bid]["ln"], qp[0], qp[1], q[0], q[1], np.hypot(*(qp - q))))

# project all old buildings
print("\n-- per old building nearest icons --")
rows = []
for bid, b in bld.items():
    p = np.array([[b["x"], b["y"]]], float)
    q = cv2.transform(p.reshape(-1, 1, 2), M).reshape(-1, 2)[0]
    ds = [np.hypot(q[0] - ix, q[1] - iy) for ix, iy in icons]
    o = np.argsort(ds)[:2]
    rows.append((bid, b["n"], b["k"], q, [(icons[j], ds[j]) for j in o]))
for r in rows:
    bid, n, k, q, near = r
    s1, s2 = near[0], near[1]
    print("  %-4s %-14s proj=(%7.1f,%7.1f)  best=(%7.1f,%7.1f)d=%5.1f  2nd=(%7.1f,%7.1f)d=%5.1f" %
          (bid, n, q[0], q[1], s1[0][0], s1[0][1], s1[1], s2[0][0], s2[0][1], s2[1]))
