# -*- coding: utf-8 -*-
"""整理用户手拼的道路：端点吸附、T 形接入、断片串联、按 AMap 参考路命名、补缺失主路。"""
import json
import math
import os
import sys

SRC = r"C:\Users\Ko_Li\Downloads\campus-manual-202611140223.json"
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113"
AMAP = os.path.join(BASE, "_data", "amap")
SNAP = 55.0
NAME_DIST = 180.0


def d2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def seg_proj(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return a[:], 0.0, math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    q = [a[0] + t * dx, a[1] + t * dy]
    return q, t, math.hypot(p[0] - q[0], p[1] - q[1])


def dedupe(pts):
    out = []
    for p in pts:
        if not out or d2(p, out[-1]) > 0.8:
            out.append([round(float(p[0]), 2), round(float(p[1]), 2)])
    return out


def clean_roads(roads):
    roads = [dedupe(r.get("p", [])) for r in roads]
    roads = [r for r in roads if len(r) >= 2]
    # 吸附端点：到其它路的线段（优先）或端点
    for _ in range(3):
        for i, r in enumerate(roads):
            if len(r) < 2:
                continue
            for idx in (0, -1):
                p = r[idx]
                best = None
                for j, o in enumerate(roads):
                    if i == j:
                        continue
                    for k in range(1, len(o)):
                        q, t, d = seg_proj(p, o[k - 1], o[k])
                        if d <= SNAP and (best is None or d < best[0]):
                            best = (d, j, k, q, t)
                    for q in (o[0], o[-1]):
                        dd = d2(p, q)
                        if dd <= SNAP and (best is None or dd < best[0]):
                            best = (dd, j, 0, q, -1)
                if not best:
                    continue
                d, j, k, q, t = best
                if t >= 0:
                    o = roads[j]
                    if t > 0.02 and t < 0.98:
                        # 目标线段内：插入节点（避免重复）
                        if all(d2(q, z) > 1.5 for z in o):
                            o.insert(k, [round(q[0], 2), round(q[1], 2)])
                r[idx] = [round(q[0], 2), round(q[1], 2)]
        roads = [dedupe(r) for r in roads]

    # 合并度为 2 的端点：把断片串成长路
    changed = True
    while changed:
        changed = False
        for i in range(len(roads)):
            if changed:
                break
            for j in range(len(roads)):
                if i == j or changed:
                    continue
                A, B = roads[i], roads[j]
                for ai, ap in ((0, A[0]), (-1, A[-1])):
                    for bi, bp in ((0, B[0]), (-1, B[-1])):
                        if d2(ap, bp) > 1.2:
                            continue
                        # 该节点只能有这两条路（度=2），避免在路口乱串
                        cnt = sum(1 for R in roads for p in (R[0], R[-1]) if d2(p, ap) < 1.5)
                        if cnt > 2:
                            continue
                        if ai == 0:
                            A = A[::-1]
                        if bi == -1:
                            B = B[::-1]
                        merged = A + B[1:]
                        roads[i] = dedupe(merged)
                        roads.pop(j)
                        changed = True
                        break
                    if changed:
                        break
    # 去太短的碎段
    roads = [r for r in roads if sum(d2(r[k], r[k - 1]) for k in range(1, len(r))) > 12]
    return roads


def simplify(pts, eps=1.2):
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[i], pts[i + 1]
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(cross) > eps:
            out.append(b)
    out.append(pts[-1])
    return out


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    user_roads = [{"id": r.get("id"), "name": r.get("name", ""), "w": r.get("w", 10), "p": r.get("p", [])}
                  for r in d.get("roads", [])]
    before = len(user_roads)
    raw = clean_roads(user_roads)
    roads = []
    for i, pts in enumerate(raw):
        roads.append({"id": "R%03d" % (i + 1), "name": "", "w": 10, "p": simplify(pts)})

    rt = json.load(open(os.path.join(AMAP, "roads_trace.json"), encoding="utf-8"))
    guides = [{"name": g.get("name", ""), "p": g.get("points", [])} for g in rt["roads"] if g.get("name")]
    used = set()
    for r in roads:
        votes = {}
        dists = {}
        for p in r["p"]:
            best = None
            for g in guides:
                md = min(seg_proj(p, g["p"][k - 1], g["p"][k])[2] for k in range(1, len(g["p"])))
                if best is None or md < best[0]:
                    best = (md, g["name"])
            if best and best[0] <= NAME_DIST:
                votes[best[1]] = votes.get(best[1], 0) + 1
                dists.setdefault(best[1], []).append(best[0])
        if votes:
            name = max(votes.items(), key=lambda kv: kv[1])[0]
            avg = sum(dists[name]) / len(dists[name])
            if avg <= NAME_DIST:
                r["name"] = name
                used.add(name)
        if not r["name"]:
            r["name"] = "校内支路"
    # 合并同名且端点相接的
    changed = True
    while changed:
        changed = False
        for i in range(len(roads)):
            for j in range(i + 1, len(roads)):
                if roads[i]["name"] != roads[j]["name"]:
                    continue
                A, B = roads[i]["p"], roads[j]["p"]
                if d2(A[-1], B[0]) < 2:
                    roads[i]["p"] = dedupe(A + B[1:])
                    roads.pop(j); changed = True; break
                if d2(A[-1], B[-1]) < 2:
                    roads[i]["p"] = dedupe(A + B[::-1][1:])
                    roads.pop(j); changed = True; break
                if d2(A[0], B[-1]) < 2:
                    roads[i]["p"] = dedupe(B + A[1:])
                    roads.pop(j); changed = True; break
                if d2(A[0], B[0]) < 2:
                    roads[i]["p"] = dedupe(B[::-1] + A[1:])
                    roads.pop(j); changed = True; break

    # 缺失的 AMap 主路：用参考路线补上
    for g in guides:
        if g["name"] not in used:
            roads.append({"id": "G" + str(len(roads) + 1), "name": g["name"], "w": 12,
                          "p": [[round(float(q[0]), 2), round(float(q[1]), 2)] for q in g["p"]]})
            used.add(g["name"])

    # 编号
    for i, r in enumerate(roads):
        r["id"] = "R%03d" % (i + 1)
    # 建筑：修平小凹坑（凸包面积比 < 1.25 时）
    def area(pts):
        s = 0
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            s += a[0] * b[1] - b[0] * a[1]
        return abs(s) / 2
    def hull(pts):
        a = sorted(pts, key=lambda p: (p[0], p[1]))
        def cross(o, p, q):
            return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
        lo = []
        for p in a:
            while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
                lo.pop()
            lo.append(p)
        up = []
        for p in reversed(a):
            while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
                up.pop()
            up.append(p)
        return lo[:-1] + up[:-1]
    fixed = 0
    for b in d.get("buildings", []):
        fp = b.get("p", [])
        if len(fp) < 4:
            continue
        h = hull(fp)
        if area(fp) > 0 and area(h) > 0 and area(h) / area(fp) < 1.25:
            b["p"] = h
            b["x"] = sum(p[0] for p in h) / len(h)
            b["y"] = sum(p[1] for p in h) / len(h)
            fixed += 1

    d["roads"] = roads
    d["meta"] = {"src": os.path.basename(SRC), "roads_before": before, "roads_after": len(roads),
                 "buildings_cleaned": fixed, "notes": "道路端点吸附/T接/断片串联/AMap 参考路命名"}
    out = os.path.join(BASE, "campus-manual-202611140223_organized.json")
    json.dump(d, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    # 统计
    names = {}
    for r in roads:
        names[r["name"]] = names.get(r["name"], 0) + 1
    print("roads", before, "->", len(roads), "buildings cleaned", fixed)
    print("names:", dict(sorted(names.items(), key=lambda kv: -kv[1])))
    print("out", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
