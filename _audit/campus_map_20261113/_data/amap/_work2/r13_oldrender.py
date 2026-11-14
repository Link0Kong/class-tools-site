# -*- coding: utf-8 -*-
"""Render old model (preview_data) as a standalone diagram, with ids, and
render its affine projection over master at 1:1 for comparison."""
import os, json
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
DATA = os.path.dirname(AMAP)
WORK = os.path.join(AMAP, "_work2")
old = json.load(open(os.path.join(DATA, "preview_data.json"), encoding="utf-8"))
ch = json.load(open(os.path.join(WORK, "chamfer_fit.json")))
A = np.array(ch["aff"], float)
bld_by_id = {b["id"]: b for b in old["buildings"]}

# ---- render old model standalone (848x493) at 3x ----
S = 3
canvas = np.full((493 * S, 848 * S, 3), 255, np.uint8)
for f in old["features"]:
    k = f.get("k")
    p = np.array(f["p"], np.float64) * S
    pts = p.astype(np.int32).reshape(-1, 1, 2)
    if k == "bld":
        cv2.fillPoly(canvas, [pts], (230, 230, 230))
        cv2.polylines(canvas, [pts], True, (0, 0, 0), 1)
    elif k in ("water", "river"):
        cv2.fillPoly(canvas, [pts], (255, 200, 120))
    elif k in ("lawn", "green"):
        cv2.fillPoly(canvas, [pts], (150, 220, 150))
    elif k == "plaza" or k == "court":
        cv2.fillPoly(canvas, [pts], (200, 230, 250))
    elif f.get("t") == "polyline":
        cv2.polylines(canvas, [pts], False, (80, 120, 200), 2)
for b in old["buildings"]:
    c = (int(b["x"] * S), int(b["y"] * S))
    cv2.putText(canvas, b["id"], c, cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 1, cv2.LINE_AA)
cv2.imwrite(os.path.join(WORK, "old_model_render.png"), canvas)
print("old model render", canvas.shape)

# ---- project old model over master at 1:1 with names ----
im = cv2.imread(os.path.join(AMAP, "master.png"))
vis = im.copy()
# fade master
vis = cv2.addWeighted(vis, 0.45, np.full_like(vis, 255), 0.55, 0)
for f in old["features"]:
    k = f.get("k")
    p = np.array(f["p"], np.float64)
    xy = p @ A[:, :2].T + A[:, 2]
    pts = xy.astype(np.int32).reshape(-1, 1, 2)
    if k == "bld":
        cv2.polylines(vis, [pts], True, (0, 0, 220), 2)
    elif k in ("water", "river"):
        cv2.polylines(vis, [pts], True, (200, 80, 0), 2)
    elif k in ("lawn", "green"):
        cv2.fillPoly(vis, [pts], (170, 235, 170))
for b in old["buildings"]:
    p = np.array([[b["x"], b["y"]]], np.float64)
    c = (p @ A[:, :2].T + A[:, 2])[0].astype(int)
    cv2.putText(vis, b["id"], tuple(c), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 220), 2, cv2.LINE_AA)
small = cv2.resize(vis, (1600, int(im.shape[0] * 1600.0 / im.shape[1])), interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK, "old_over_master.png"), small)
print("overlay saved")
