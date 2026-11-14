# -*- coding: utf-8 -*-
"""把参考站授权的几何/高度数据整理成本地预览用的紧凑 JSON。
输出：_data/preview_data.json（随后内联进单文件 HTML）
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "_data")

geo = json.load(open(os.path.join(D, "geometry.json"), encoding="utf-8-sig"))
params = json.load(open(os.path.join(D, "model_parameters.json"), encoding="utf-8-sig"))
plan = json.load(open(os.path.join(D, "campus-reconstruction-plan.json"), encoding="utf-8-sig"))

# ---------- 楼名（依据「福中医（旗山校区）地图」河洛易班版 + 参考站数据校对） ----------
NAME = {
    "B01": ("22#", "residential", "宿舍"), "B02": ("23#A", "residential", "宿舍"),
    "B03": ("23#B", "residential", "宿舍"),
    "B04": ("延平学生活动中心", "residential", "生活"),
    "B05": ("12#", "residential", "宿舍"), "B06": ("11#", "residential", "宿舍"),
    "B07": ("10#", "residential", "宿舍"), "B08": ("8#", "residential", "宿舍"),
    "B09": ("学生公寓", "residential", "宿舍"), "B10": ("学生公寓", "residential", "宿舍"),
    "B11": ("学生公寓", "residential", "宿舍"), "B12": ("学生公寓", "residential", "宿舍"),
    "B13": ("学生公寓", "residential", "宿舍"), "B14": ("学生公寓", "residential", "宿舍"),
    "B15": ("学生公寓", "residential", "宿舍"), "B16": ("9#", "residential", "宿舍"),
    "B17": ("后勤配套", "residential", "生活"),
    "B20": ("厚德楼", "academic", "教学楼"), "B21": ("厚德楼", "academic", "教学楼"),
    "B22": ("厚德楼", "academic", "教学楼"), "B23": ("厚德楼", "academic", "教学楼"),
    "B24": ("康复大楼", "academic", "科研"), "B25": ("康复大楼", "academic", "科研"),
    "B26": ("康复大楼", "academic", "科研"), "B27": ("康复大楼", "academic", "科研"),
    "B28": ("精诚楼", "academic", "教学楼"), "B29": ("精诚楼", "academic", "教学楼"),
    "B30": ("精诚楼", "academic", "教学楼"), "B31": ("精诚楼", "academic", "教学楼"),
    "B32": ("五行楼", "academic", "教学楼"), "B33": ("五行楼", "academic", "教学楼"),
    "B34": ("五行楼", "academic", "教学楼"), "B35": ("五行楼", "academic", "教学楼"),
    "B36": ("至善楼", "academic", "教学楼"), "B37": ("至善楼", "academic", "教学楼"),
    "B38": ("至善楼", "academic", "教学楼"), "B39": ("至善楼", "academic", "教学楼"),
    "B40": ("自强楼", "academic", "教学楼"), "B41": ("自强楼", "academic", "教学楼"),
    "B42": ("自强楼", "academic", "教学楼"), "B43": ("自强楼", "academic", "教学楼"),
    "B44": ("综合楼", "academic", "教学楼"), "B45": ("综合楼", "academic", "教学楼"),
    "B46": ("综合楼", "academic", "教学楼"), "B47": ("综合楼", "academic", "教学楼"),
    "B50": ("图书馆", "civic", "图书馆"), "B51": ("图书馆", "civic", "图书馆"),
    "B52": ("河洛时光", "civic", "图书馆"),
    "B53": ("食堂", "civic", "食堂"), "B54": ("食堂", "civic", "食堂"),
    "B55": ("后勤配套", "civic", "生活"), "B56": ("后勤配套", "civic", "生活"),
    "B57": ("快递站", "civic", "生活"),
    "B58": ("培训中心", "civic", "培训"), "B59": ("明德楼", "civic", "教学楼"),
    "B60": ("求真楼", "civic", "教学楼"), "B61": ("求真楼", "civic", "教学楼"),
    "B62": ("求真楼", "civic", "教学楼"), "B63": ("求真楼", "civic", "教学楼"),
    "B64": ("实验动物中心", "civic", "科研"), "B65": ("实验动物中心", "civic", "科研"),
    "B66": ("修园楼", "civic", "教学楼"), "B67": ("时珍园配套", "civic", "生活"),
    "B70": ("体育馆", "sports", "运动"), "B71": ("田径场看台", "sports", "运动"),
    "B72": ("田径场看台", "sports", "运动"),
    "B81": ("名师苑", "landscape", "住宅"), "B82": ("名师苑", "landscape", "住宅"),
    "B83": ("名师苑", "landscape", "住宅"), "B84": ("名师苑", "landscape", "住宅"),
    "B85": ("名师苑", "landscape", "住宅"),
    "B86": ("中药炮制实验室", "landscape", "科研"), "B87": ("湖岸附属体", "landscape", "生活"),
}
# 楼栋号（官方 1-8 / 33 号楼）
NO = {"B20": "2", "B24": "8", "B28": "4", "B32": "7", "B36": "3", "B40": "1", "B44": "33"}
LABEL_IDS = {"B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B16", "B20", "B24", "B28", "B32", "B36", "B40",
             "B44", "B50", "B52", "B53", "B57", "B58", "B59", "B60", "B66", "B70"}
LONG = {
    "B01": "22号楼", "B02": "23号楼（a区）", "B03": "23号楼（b区）",
    "B04": "延平学生活动中心", "B05": "12号楼", "B06": "11号楼", "B07": "10号楼", "B08": "8号楼", "B16": "9号楼", "B20": "厚德楼", "B24": "康复大楼",
    "B28": "精诚楼", "B32": "五行楼", "B36": "至善楼", "B40": "自强楼",
    "B44": "综合楼", "B50": "图书馆", "B52": "河洛时光（图书馆临湖附体）",
    "B53": "食堂", "B57": "快递站", "B58": "国际中医药培训中心", "B59": "明德楼（行政楼）",
    "B60": "求真楼", "B66": "修园楼", "B70": "体育馆", "B71": "田径场看台", "B72": "田径场看台",
    "B81": "名师苑", "B82": "名师苑", "B83": "名师苑", "B84": "名师苑", "B85": "名师苑",
    "B86": "中药炮制实验室", "B87": "湖岸附属体",
}

# ---------- 高度 ----------
H = {}
for b in params.get("buildings", []):
    bid = b.get("id")
    if not bid:
        continue
    H[bid] = {"h": round(float(b.get("height_model_units") or 0), 2),
              "fl": b.get("assumed_floors")}
for f in geo["features"]:
    if f.get("category") == "building" and f["id"] not in H:
        grp = f.get("group") or "civic"
        H[f["id"]] = {"h": {"residential": 15.25, "academic": 12.2, "civic": 9.15,
                            "sports": 6.1, "landscape": 6.1}.get(grp, 9.0), "fl": None}

# ---------- 要素（去掉说明字段，坐标保留 1 位） ----------
fmap = {
    "site_boundary": "bnd", "water": "water", "land_island": "island",
    "road_centerline": "road", "sports_track": "track", "sports_field": "field",
    "sports_court": "court", "landscape_surface": "lawn", "plaza": "plaza",
    "hill_contour": "hill", "landscape_terrace": "terrace", "contour_candidate": "contour",
    "context_building": "context", "building": "bld",
}
feats = []
for f in geo["features"]:
    cat = fmap.get(f.get("category"))
    if not cat:
        continue
    pts = [[round(float(x), 1), round(float(y), 1)] for x, y in (f.get("points") or [])]
    if not pts:
        continue
    feats.append({"id": f["id"], "k": cat, "t": f.get("geometry_type"),
                  "g": f.get("group") or "", "p": pts})

buildings = []
for f in geo["features"]:
    if f.get("category") != "building":
        continue
    bid = f["id"]
    nm, grp, kind = NAME.get(bid, ("", f.get("group") or "civic", "其他"))
    hh = H.get(bid, {})
    buildings.append({
        "id": bid, "n": nm, "lb": 1 if bid in LABEL_IDS else 0, "no": NO.get(bid, ""),
        "u": bid if bid in LABEL_IDS else "",
        "k": kind, "g": grp,
        "h": hh.get("h", 9.0), "fl": hh.get("fl"),
        "x": round(sum(p[0] for p in f["points"]) / len(f["points"]), 1),
        "y": round(sum(p[1] for p in f["points"]) / len(f["points"]), 1),
    })
# 信息卡用的完整楼名
for b in buildings:
    if not b["n"]:
        b["n"] = NAME.get(b["id"], ("", "", "其他"))[0]
# 选中/搜索用完整楼名
for b in buildings:
    b["ln"] = LONG.get(b["id"]) or NAME.get(b["id"], ("", "", "其他"))[0]

# ---------- 搜索别名 ----------
ALIAS = {
    "B40": ["自强楼", "1号楼"], "B20": ["厚德楼", "2号楼"],
    "B36": ["至善楼", "3号楼"], "B28": ["精诚楼", "4号楼"],
    "B32": ["五行楼", "7号楼"], "B24": ["康复大楼", "康复研究院", "8号楼"],
    "B44": ["综合楼", "教学综合楼", "33号楼"], "B50": ["图书馆"],
    "B53": ["食堂", "食堂综合楼"], "B58": ["培训中心", "国际中医药培训中心"],
    "B59": ["明德楼", "行政楼"], "B60": ["求真楼"], "B66": ["修园楼"],
    "B70": ["体育馆"], "B52": ["河洛时光"], "B57": ["快递站"], "B05": ["12号楼"], "B06": ["11号楼"], "B07": ["10号楼"], "B08": ["8号楼"], "B16": ["9号楼"], "B01": ["22号楼"], "B02": ["23号楼", "23A"], "B03": ["23号楼", "23B"],
}

# ---------- 教室（来自班级课表 tt.json） ----------
ROOM = {
    "B40": {"no": "01", "name": "自强楼", "floors": [1, 2, 5],
            "rooms": ["01101", "01104", "01105", "01202", "01203", "01204",
                      "01217", "01506", "01509", "01514"]},
    "B20": {"no": "02", "name": "厚德楼", "floors": [1, 2, 3, 4],
            "rooms": ["02101", "02111", "02210", "02309", "02405"]},
}
NEXT = {"time": "08:45", "course": "高等数学", "room": "01217", "bid": "B40",
        "where": "自强楼 2 层 17 教室", "note": "示例数据（课表接入后为真实下一节）"}
GATE = [326, 458]

# ---------- 干净路网（连续、避开建筑；宽度单位为模型单位） ----------
_roads_path = os.path.join(D, "roads_amap.json")
if os.path.exists(_roads_path):
    ROADS = json.load(open(_roads_path, encoding="utf-8"))["roads"]
else:
    ROADS = []

out = {"vb": [848, 493], "features": feats, "buildings": buildings, "roads": ROADS,
       "alias": ALIAS, "rooms": ROOM, "next": NEXT, "gate": GATE,
       "src": "建筑轮廓/高度：旗山校园三维空间研究（用户授权）；总平面图：用户提供"}
p = os.path.join(D, "preview_data.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("features", len(feats), "buildings", len(buildings))
print("json bytes", len(open(p, "rb").read()))
