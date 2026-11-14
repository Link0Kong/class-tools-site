import cv2, numpy as np, os, json

BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
im = cv2.imread(os.path.join(BASE, "master.png"))
H, W = im.shape[:2]

def interp(pts, step=70):
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

traced = json.load(open(os.path.join(WORK, "traced_paths.json"), encoding="utf-8"))
def T(name):
    return [[round(float(a), 1), round(float(b), 1)] for a, b in np.array(traced[name]["simplified"], np.float64)]

roads = []
def add(name, pts, width_px, wclass, conf, note=""):
    roads.append({"name": name, "points": pts, "width_px": width_px, "width_class": wclass,
                  "confidence": conf, "note": note})

# 1 修园北路 -- traced, gentle north shift on wide eastern section
xyb = T("修园北路")
fixed = []
for x, y in xyb:
    if x >= 1880 and x < 2150:
        y = y - 8
    fixed.append([x, round(y, 1)])
add("修园北路", fixed, 11, "secondary", "high",
    "环湖路北段：自西北端（联心村道口）沿湖岸向东北，东端接东侧小环岛；东段路幅偏宽（含滨水铺装），中心线取路幅中线")

# 2 修园东路 -- traced (wide diagonal)
add("修园东路", T("修园东路"), 14, "primary", "high",
    "宽幅斜向主干路：修园北路环岛→明德楼西侧→图书馆西侧→棋盘广场东侧→学生服务中心北，标签在图上出现3处")

# 3 修园西路 -- traced upper + straight extension through dorm area
add("修园西路", interp([[702,1294],[681,1378],[664,1467],[657,1556],[650,1645],[643,1734],[645,1805],
                        [646,1877],[657,1941],[656,2007],[675,2110],[695,2213],[700,2300],[700,2400],[703,2500],[708,2530]], 70),
    10, "secondary", "medium",
    "沿湖西岸南北向；北段自望果西路交叉口，南段进入西区宿舍区（南端具体止点不确定）")

# 4 望果西路
add("望果西路", interp([[473,1317],[571,1322],[637,1325],[700,1300],[780,1265],[900,1262],[1050,1260],[1200,1258],[1225,1258]], 70),
    10, "secondary", "medium",
    "湖西东西向次干路；名称分界约在 x=1225（无路口标志，按标签位置推断）")

# 5 望果东路
add("望果东路", interp([[1225,1258],[1350,1262],[1470,1265],[1600,1253],[1750,1250],[1900,1250],[2000,1249],[2070,1249],
                        [2130,1255],[2180,1290],[2215,1330],[2245,1360]], 70),
    10, "secondary", "medium", "东西向次干路，东端下弯接修园北路环岛")

# 6 银杏西路
add("银杏西路", interp([[662,1545],[760,1548],[880,1550],[1000,1552],[1150,1554],[1300,1555],[1430,1556],[1525,1556]], 70),
    10, "secondary", "high", "西起修园西路，东至仲景路；中心线 y≈1545-1556（按路面灰度线实测）")

# 7 银杏东路
add("银杏东路", interp([[1525,1556],[1650,1554],[1800,1552],[1950,1551],[2100,1549]], 70),
    10, "secondary", "high", "自仲景路向东，东端接修园东路")

# 8 仲景路
add("仲景路", interp([[1525,1258],[1525,1350],[1525,1450],[1525,1556],[1524,1630],[1518,1670],[1512,1690]], 60),
    9, "tertiary", "high", "南北向支路：望果东路↔银杏东路，南端分叉为仲景东路/仲景西路")

# 9 仲景西路
add("仲景西路", interp([[1512,1690],[1470,1715],[1452,1745],[1452,1830],[1452,1920],[1453,2010],[1455,2100]], 70),
    8, "tertiary", "low", "仲景路西分支，南北向；仅上段有路名标签，南端止点不确定")

# 10 仲景东路
add("仲景东路", interp([[1512,1690],[1496,1750],[1487,1830],[1484,1930],[1484,2030]], 70),
    8, "tertiary", "low", "仲景路东分支，南北向；南端止点不确定")

# 11 杏林大道
add("杏林大道", interp([[1372,2385],[1440,2332],[1520,2282],[1600,2237],[1680,2192],[1755,2150],[1830,2110]], 70),
    12, "primary", "low",
    "图书馆南侧斜向主干道，西南端接修园东路，东北端去向未出图（明德楼西侧）；仅一处路名标签")

# 12 学府北路 (NE + 环岛 + SE)
xuefu = [[2880,1052],[2770,1200],[2695,1300],[2620,1400],[2534,1500],[2456,1600],[2382,1700],
         [2298,1800],[2229,1900],[2155,2000],[2083,2100],[2016,2200],[1937,2300],[1871,2400],[1831,2480],[1806,2510],
         [1815,2530],[1850,2560],[1885,2600],[1960,2660],[2025,2700],[2090,2760],[2149,2800],
         [2225,2860],[2301,2900],[2380,2960],[2440,3000],[2478,3035]]
add("学府北路", interp(xuefu, 60), 42, "arterial", "high",
    "城市主干道（双向+中央绿化带）：东北端入图→东侧门→东南门环岛→东南（西南2门/北2门/东北门方向）；东南端止于覆盖边界")

# 13 学府西路
add("学府西路", interp([[1780,2530],[1750,2555],[1734,2600],[1658,2700],[1584,2800],[1509,2900],[1434,3000],
                        [1365,3100],[1300,3200],[1240,3300],[1180,3400],[1140,3455]], 60),
    34, "arterial", "high",
    "城市主干道：东南门环岛向西南经东南2门出图，与学府北路在环岛相接")

out = {"master_size": [W, H], "north_offset": [137, 0],
       "coordinate_note": "所有坐标为 master.png 像素坐标（北向上）。master 坐标 = amap_north 坐标 + (137,0)。",
       "roads": roads}
json.dump(out, open(os.path.join(BASE, "roads_trace.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("roads:", len(roads))

PAL = [(0,0,230),(0,140,255),(0,170,0),(200,0,0),(200,0,200),(0,190,190),(120,0,120),
       (0,90,0),(220,120,0),(110,60,0),(160,0,100),(0,60,170),(0,150,110),(90,90,230)]
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
# distance stats
dist = np.load(os.path.join(WORK, "thin_dist.npy")).astype(np.float32)
print("%-8s %6s %6s %6s %6s %6s" % ("road", "npts", "medD", "p10", "p90", "off%"))
for r in roads:
    pts = np.array(r["points"])
    samples = []
    for i in range(len(pts)-1):
        p, q = pts[i], pts[i+1]
        L = np.linalg.norm(q-p); n = max(1, int(L//10))
        for k in range(n+1): samples.append(p + (q-p)*k/n)
    samples = np.array(samples)
    xs = np.clip(np.round(samples[:,0]).astype(int), 0, W-1); ys = np.clip(np.round(samples[:,1]).astype(int), 0, H-1)
    vals = dist[ys, xs]
    print("%-8s %6d %6.1f %6.1f %6.1f %5.2f" % (r["name"], len(r["points"]), np.median(vals), np.percentile(vals,10), np.percentile(vals,90), (vals>25).mean()))
