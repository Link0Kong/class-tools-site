# -*- coding: utf-8 -*-
"""r12: propose label anchors = (old building id, nearest POI icon) under chamfer affine."""
import os, json, math
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
DATA = os.path.dirname(AMAP)
WORK = os.path.join(AMAP, "_work2")
old = json.load(open(os.path.join(DATA, "preview_data.json"), encoding="utf-8"))
icons = [tuple(c[:2]) for c in json.load(open(os.path.join(WORK, "poi_icons.json")))]
ch = json.load(open(os.path.join(WORK, "chamfer_fit.json")))
A = np.array(ch["aff"], float)
blds = old["buildings"]
alias = old["alias"]

# group old buildings by display name
groups = {}
for b in blds:
    nm = b["ln"]
    groups.setdefault(nm, []).append(b)

print("%-8s %-22s %-10s %-28s %s" % ("id", "name", "kind", "proj(master)", "nearest icon"))
cands = []
for nm, arr in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    # use centroid of the group (mean of member centres)
    p = np.array([[b["x"], b["y"]] for b in arr], float).mean(0)
    q = p @ A[:, :2].T + A[:, 2]
    ds = [np.hypot(q[0] - ix, q[1] - iy) for ix, iy in icons]
    o = np.argsort(ds)
    near = [(icons[j], ds[j]) for j in o[:2]]
    print("%-8s %-22s %-10s (%7.1f,%7.1f)  best=(%7.1f,%7.1f) d=%5.1f | 2nd d=%5.1f" %
          (arr[0]["id"], nm, arr[0]["k"], q[0], q[1], near[0][0][0], near[0][0][1], near[0][1], near[1][1]))
    cands.append({"name": nm, "ids": [b["id"] for b in arr], "kind": arr[0]["k"],
                  "x": float(p[0]), "y": float(p[1]),
                  "proj": [float(q[0]), float(q[1])],
                  "icon": near[0][0], "dist": float(near[0][1])})
json.dump(cands, open(os.path.join(WORK, "anchor_cands.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved", len(cands), "candidates; alias names:", {k: v for k, v in alias.items()})
