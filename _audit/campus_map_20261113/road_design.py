# -*- coding: utf-8 -*-
"""设计并校验一套连续、避让建筑/水面的校园路网（真值坐标与 geometry.json 一致）。"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = json.load(open(os.path.join(HERE, "_data", "geometry.json"), encoding="utf-8-sig"))
BUILD = [f for f in GEO["features"] if f["category"] == "building"]
WATER = [f for f in GEO["features"] if f["category"] == "water"]

ROADS = [
  dict(id="R02", name="修园南路", w=6.0, pts=[(123,385),(202,385),(280,385),(331,385),(388,385),(419,385),(467,388),(507,399),(552,399),(587,398),(635,398),(692,399)]),
  dict(id="R03", name="杏林大道", w=6.0, pts=[(326,459),(326,427),(326,394),(326,385)]),
  dict(id="R01", name="环湖路", w=6.0, pts=[(202,385),(203,355),(218,315),(241,272),(269,236),(303,207),(341,183),(381,162),(415,148),(454,140),(496,137),(537,143),(575,158),(603,181),(620,209),(630,240),(630,273),(622,310),(608,343),(584,379),(562,408),(552,399)]),
  dict(id="R04", name="杏林大道", w=5.0, pts=[(326,385),(332,372),(363,351),(401,324),(440,297),(480,268),(510,246),(527,246)]),
  dict(id="R05", name="修园北路", w=5.0, pts=[(415,148),(436,192),(463,228),(483,253),(527,246),(597,192),(603,181)]),
  dict(id="R06", name="仲景路", w=5.0, pts=[(341,183),(351,180),(382,220),(409,259),(430,289),(461,330),(493,375),(507,399)]),
  dict(id="R13", name="体育场支路", w=4.0, pts=[(291,104),(317,137),(342,170),(341,183)]),
  dict(id="S3", name="修园西路", w=5.0, pts=[(202,385),(150,382),(120,380),(95,370),(75,355),(70,330),(70,300),(72,270),(78,240),(88,210),(105,190),(130,175),(160,163),(190,155),(220,150),(245,150)]),
  dict(id="S4", name="宿舍支路", w=3.5, pts=[(130,175),(170,175),(235,175)]),
  dict(id="S5", name="图书馆支路", w=3.5, pts=[(331,385),(330,362),(300,360)]),
  dict(id="S7", name="修园东路", w=5.0, pts=[(552,399),(575,385),(590,372),(600,352),(620,350),(640,348),(660,352),(700,352),(705,360),(705,398),(692,399)]),
]
def pip(x, y, pts):
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


def seg_len(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def check_roads(roads):
    errors = []
    water_hits = []
    for r in roads:
        p = r["pts"]
        for i in range(1, len(p)):
            a, b = p[i - 1], p[i]
            L = seg_len(a, b)
            steps = max(2, int(L / 1.5))
            for k in range(steps + 1):
                t = k / steps
                x = a[0] + (b[0] - a[0]) * t
                y = a[1] + (b[1] - a[1]) * t
                for bf in BUILD:
                    if pip(x, y, bf["points"]):
                        errors.append((r["id"], bf["id"], round(x, 1), round(y, 1)))
                for wf in WATER:
                    if pip(x, y, wf["points"]):
                        water_hits.append((r["id"], wf["id"], round(x, 1), round(y, 1)))
    # 连通性（端点 3 单位内、端点到线段 3 单位内视为连通）
    nodes = []  # (road index, endpoint 0/1, x,y)
    for ri, r in enumerate(roads):
        nodes.append([ri, 0, r["pts"][0][0], r["pts"][0][1]])
        nodes.append([ri, 1, r["pts"][-1][0], r["pts"][-1][1]])
    parent = list(range(len(roads)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(roads)):
        for j in range(i + 1, len(roads)):
            pa, pb = roads[i]["pts"], roads[j]["pts"]
            d = 999
            # 端点-端点
            for a in (pa[0], pa[-1]):
                for b in (pb[0], pb[-1]):
                    d = min(d, math.hypot(a[0] - b[0], a[1] - b[1]))
            # 端点到线段
            for a in (pa[0], pa[-1]):
                for k in range(1, len(pb)):
                    ax, ay = a
                    bx, by = pb[k - 1]
                    cx, cy = pb[k]
                    dx, dy = cx - bx, cy - by
                    L2 = dx * dx + dy * dy
                    t = 0 if L2 < 1e-9 else max(0, min(1, ((ax - bx) * dx + (ay - by) * dy) / L2))
                    px, py = bx + t * dx, by + t * dy
                    d = min(d, math.hypot(ax - px, ay - py))
            for b in (pb[0], pb[-1]):
                for k in range(1, len(pa)):
                    bx, by = b
                    ax, ay = pa[k - 1]
                    cx, cy = pa[k]
                    dx, dy = cx - ax, cy - ay
                    L2 = dx * dx + dy * dy
                    t = 0 if L2 < 1e-9 else max(0, min(1, ((bx - ax) * dx + (by - ay) * dy) / L2))
                    px, py = ax + t * dx, ay + t * dy
                    d = min(d, math.hypot(bx - px, by - py))
            if d <= 3.0:
                union(i, j)
    comps = {}
    for i in range(len(roads)):
        comps.setdefault(find(i), []).append(roads[i]["id"])
    return errors, water_hits, list(comps.values())


if __name__ == "__main__":
    errs, waters, comps = check_roads(ROADS)
    print("building errors:", len(errs))
    for e in errs[:40]:
        print("  ", e)
    print("water hits:", len(waters))
    for w in waters[:40]:
        print("  ", w)
    print("components:", comps)
