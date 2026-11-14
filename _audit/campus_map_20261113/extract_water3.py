# -*- coding: utf-8 -*-
"""从规划图提取水面轮廓 -> 简化多边形（仅生成示意图形，不发布原图像素）。
改进：闭运算填字洞 + 开运算去掉细窄水道，再抽轮廓 + Chaikin 平滑 + RDP 简化。"""
import json
import math
import os

from PIL import Image
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ref_map.png")
OUT = os.path.join(HERE, "_ref", "water_paths.json")

im = Image.open(SRC).convert("RGB")
a = np.asarray(im).astype(np.int16)
r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
mask = (b > 118) & (b - r > 25) & (b - g > 5) & (g < 195)


def dilate(m, n=1):
    out = m.copy()
    for _ in range(n):
        o = out.copy()
        o[1:, :] |= out[:-1, :]
        o[:-1, :] |= out[1:, :]
        o[:, 1:] |= out[:, :-1]
        o[:, :-1] |= out[:, 1:]
        out = o
    return out


def erode(m, n=1):
    out = m.copy()
    for _ in range(n):
        o = out.copy()
        o[:-1, :] &= out[1:, :]
        o[1:, :] &= out[:-1, :]
        o[:, :-1] &= out[:, 1:]
        o[:, 1:] &= out[:, :-1]
        out = o
    return out


mask = dilate(mask, 3)
mask = erode(mask, 3)      # closing：填字洞
mask = erode(mask, 6)
mask = dilate(mask, 6)     # opening：去掉细窄水道
mask = dilate(mask, 9)
mask = erode(mask, 9)      # closing2：圆滑岸线海湾

h, w = mask.shape
lab = np.zeros((h, w), np.int32)
comps = []
cid = 0
for y in range(h):
    for x in range(w):
        if mask[y, x] and lab[y, x] == 0:
            cid += 1
            stack = [(y, x)]
            lab[y, x] = cid
            cnt = 0
            xs0 = xs1 = x
            ys0 = ys1 = y
            while stack:
                cy, cx = stack.pop()
                cnt += 1
                if cx < xs0: xs0 = cx
                if cx > xs1: xs1 = cx
                if cy < ys0: ys0 = cy
                if cy > ys1: ys1 = cy
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and lab[ny, nx] == 0:
                        lab[ny, nx] = cid
                        stack.append((ny, nx))
            if cnt > 1500:
                comps.append({"cid": cid, "n": cnt, "bbox": [xs0, ys0, xs1, ys1]})
comps.sort(key=lambda c: -c["n"])
print("water comps:", [(c["cid"], c["n"], c["bbox"]) for c in comps[:8]])

CASE = {
    1: [("L", "T")], 2: [("T", "R")], 3: [("L", "R")], 4: [("R", "B")],
    5: [("L", "T"), ("R", "B")], 6: [("T", "B")], 7: [("L", "B")],
    8: [("B", "L")], 9: [("B", "T")], 10: [("L", "B"), ("T", "R")], 11: [("B", "R")],
    12: [("R", "L")], 13: [("R", "T")], 14: [("T", "L")], 15: [],
}
PT = {"T": (0.5, 0.0), "R": (1.0, 0.5), "B": (0.5, 1.0), "L": (0.0, 0.5)}


def trace_component(m):
    pad = np.zeros((m.shape[0] + 2, m.shape[1] + 2), bool)
    pad[1:-1, 1:-1] = m
    hh, ww = pad.shape
    segs = []
    for y in range(hh - 1):
        for x in range(ww - 1):
            c = (pad[y, x], pad[y, x + 1], pad[y + 1, x + 1], pad[y + 1, x])
            case = (1 if c[0] else 0) | (2 if c[1] else 0) | (4 if c[2] else 0) | (8 if c[3] else 0)
            for e0, e1 in CASE.get(case, []):
                segs.append(((x + PT[e0][0] - 1, y + PT[e0][1] - 1),
                             (x + PT[e1][0] - 1, y + PT[e1][1] - 1)))
    key = lambda p: (round(p[0] * 2) / 2, round(p[1] * 2) / 2)
    adj = {}
    for p0, p1 in segs:
        adj.setdefault(key(p0), []).append((key(p0), key(p1)))
        adj.setdefault(key(p1), []).append((key(p1), key(p0)))
    loops = []
    used = set()
    for k in list(adj.keys()):
        for p0, p1 in adj[k]:
            if (p0, p1) in used or (p1, p0) in used:
                continue
            loop = [p0, p1]
            used.add((p0, p1))
            cur, prev = p1, p0
            ok = True
            while cur != loop[0] and len(loop) < 100000:
                nxt = None
                for s in adj.get(cur, []):
                    if s[1] != prev and (s[0], s[1]) not in used and (s[1], s[0]) not in used:
                        nxt = s[1]
                        break
                if nxt is None:
                    ok = False
                    break
                used.add((cur, nxt))
                loop.append(nxt)
                prev, cur = cur, nxt
            if ok and len(loop) > 8:
                loops.append(loop)
    if not loops:
        return None
    loops.sort(key=len, reverse=True)
    return loops[0]


def chaikin(pts, it=2):
    for _ in range(it):
        out = []
        n = len(pts)
        for i in range(n):
            p, q = pts[i], pts[(i + 1) % n]
            out.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            out.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        pts = out
    return pts


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = math.hypot(dx, dy)
    idx, dmax = 0, -1
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        dist = math.hypot(x - x0, y - y0) if norm == 0 else abs(dy * x - dx * y + x1 * y0 - y1 * x0) / norm
        if dist > dmax:
            dmax, idx = dist, i
    if dmax > eps:
        return rdp(pts[:idx + 1], eps)[:-1] + rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]


paths = []
for c in comps:
    loop = trace_component(lab == c["cid"])
    if not loop:
        continue
    pts = [(p[0] / 2.0, p[1] / 2.0) for p in loop]
    pts = chaikin(pts, 2)
    pts.append(pts[0])
    pts = rdp(pts, 1.1)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    s = "M %.1f,%.1f " % (pts[0][0], pts[0][1])
    s += " ".join("L %.1f,%.1f" % (p[0], p[1]) for p in pts[1:])
    s += " Z"
    paths.append(s)
    print("path bbox", c["bbox"], "pts", len(pts))

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(paths, f, ensure_ascii=False, indent=1)
print("saved", OUT, len(paths))
