# -*- coding: utf-8 -*-
"""检查：建筑与水面重叠、道路连通性，辅助修贴地与道路导航。"""
import json
import math

D = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data"
geo = json.load(open(D + r"\geometry.json", encoding="utf-8-sig"))
F = geo["features"]


def in_poly(x, y, pts):
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


buildings = [f for f in F if f["category"] == "building"]
waters = [f for f in F if f["category"] == "water"]
print("buildings", len(buildings), "waters", len(waters))

print("\n--- 建筑与水面：顶点/中心落入水中的 ---")
for b in buildings:
    pts = b["points"]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    hits = []
    for w in waters:
        if in_poly(cx, cy, w["points"]) or any(in_poly(x, y, w["points"]) for x, y in pts):
            hits.append(w["id"])
    if hits:
        print(b["id"], b["name"], "center", (round(cx, 1), round(cy, 1)), "water", hits)

roads = [f for f in F if f["category"] == "road_centerline"]
print("\n--- 道路 ---")
for r in roads:
    p = r["points"]
    print(r["id"], r["name"], "pts", len(p), "start", tuple(p[0]), "end", tuple(p[-1]))


def seg_dist(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(cx - ax, cy - ay)
    t = ((cx - ax) * dx + (cy - ay) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))
    return math.hypot(cx - (ax + t * dx), cy - (ay + t * dy))


print("\n--- 道路端点与其他道路的最小距离（<12 认为可连接） ---")
for r in roads:
    for which, pt in (("start", r["points"][0]), ("end", r["points"][-1])):
        best = (1e9, None)
        for r2 in roads:
            if r2 is r:
                continue
            for i in range(len(r2["points"]) - 1):
                d = seg_dist(r2["points"][i], r2["points"][i + 1], pt)
                if d < best[0]:
                    best = (d, r2["id"])
        if best[0] < 20:
            print(r["id"], which, "->", best[1], round(best[0], 1))
