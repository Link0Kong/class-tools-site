# -*- coding: utf-8 -*-
"""r24: generate _data/amap/buildings_report.md from the produced JSON + stats."""
import os, json
import numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
DATA = os.path.dirname(AMAP)
WORK = os.path.join(AMAP, "_work2")
bt = json.load(open(os.path.join(AMAP, "buildings_trace.json"), encoding="utf-8"))
ft = json.load(open(os.path.join(AMAP, "features_trace.json"), encoding="utf-8"))
st = json.load(open(os.path.join(WORK, "final_stats.json"), encoding="utf-8"))
old = json.load(open(os.path.join(DATA, "preview_data.json"), encoding="utf-8"))
bld = {b["id"]: b for b in old["buildings"]}

L = []
def w(s=""):
    L.append(s)

w("# AMap 底图建筑 / 水面 / 绿地 / 广场矢量提取与旧数据匹配报告")
w()
w("- 生成时间：2026-11-13")
w("- 底图：`_data/amap/master.png`（2957x3463，AMap 北向，north/south/west 三图拼接）")
w("- 旧数据：`_data/preview_data.json`（848x493 规划示意图坐标）")
w("- 只写 `_data/amap/` 与 `_data/amap/_work2/`，未改动 master.png、preview_data.json、roads_trace.json、模板/页面。")
w()
w("## 0. 产出文件")
w()
w("| 文件 | 说明 |")
w("|---|---|")
w("| `_data/amap/buildings_trace.json` | 建筑多边形（master 像素）+ model→master 仿射 + 锚点 + 残差 |")
w("| `_data/amap/features_trace.json` | water / island / lawn / plaza / track 多边形（master 像素）|")
w("| `_data/amap/buildings_check.png` | 自检图：buildings_trace + 水系/绿地/广场 叠回 master |")
w("| `_data/amap/_work2/` | 中间影像与自检裁切（`selfchk_*.png`、`d_*.png`、脚本 `r*.py`）|")
w()
w("### 0.1 数据结构")
w()
w("- `buildings_trace.json`：`master_size`[w,h]；`model_to_master` 2x3 仿射；"
  "`anchors[]`{label,old_ids,model_point,master_point,resid_px}；`residual`{mean,median,p95,max}；"
  "`buildings[]` 每项 {id,n,no,k,g,points[[x,y],...],cx,cy,confidence}。")
w("- `features_trace.json`：`master_size`；water[] / island[] / lawn[] / plaza[] / track[]，"
  "每项 {area, points[[x,y],...], cx?, cy?}（water/island/lawn 只有 area+points）。")
w()
w("## 1. 坐标系与比例")
w()
w("- 输出全部为 **master 像素坐标**（左上角原点，x 右，y 下），`master_size = [%d, %d]`。" % tuple(bt["master_size"]))
w("- `preview_data.json` 为 848x493 的规划示意图坐标：图幅**北向约朝右上 40–55°**，"
  "楼栋多边形是**翼/屋顶级**（一个复合楼拆成 2–5 个多边形）。")
w("- 拼接图内部并不完全同源：north 图按 1.0 放置，south ×0.9957，west ×0.8778（west 被重采样，比其它两块细 12.3%），"
  "north 图地面底色 `#eff3f6`，south/west 地面 `#e6f0f9`。分割按颜色分别处理，不受影响。")
w("- AMap 图上没有可直接读取的米制比例尺校准；`equivalent_scale = %.4f master px / model unit`（旧模型单位≠米）。" % bt["equivalent_scale"])
w()
w("## 2. 颜色分割方法")
w()
w("实现：`_work2/r20_extract2.py`（OpenCV 5.0 / numpy），全部按 RGB 精确色/近邻色阈值 + 形态学 + 连通域 + `findContours` + `approxPolyDP`。")
w()
w("| 类别 | 判据 | 后处理 |")
w("|---|---|---|")
w("| 建筑 | RGB 与 AMap 建筑填充 `#d9e3ec`(217,227,236) 的 L∞ 距离 ≤ 10 | 3x3 开运算去 1–2px 细线；`RETR_EXTERNAL` 外轮廓（文字/POI 图标形成的洞自动忽略）；过滤 area<900、minRect 短边<8、solidity<0.35 |")
w("| 水面 | B≥200、R≤190、G≥185、B−R≥45、B−G≥12（含 `#83dcfa` 及其抗锯齿变体）| 3x3 开 + 7x7 闭；`RETR_CCOMP`：外层=水体，内部孔洞且面积>4000=岛 |")
w("| 绿地 | G≥185、G−B≥30、G−R≥25（含 `#aee999` 及草地/树冠变体）| 3x3 开 + 7x7 闭；面积≥4000，solidity≥0.10 |")
w("| 运动场 | 本 AMap 样式未给田径场独立底色，拼接图内也**没有**田径场 | track=[]（见 §8）|")
w("| 广场 | 本 AMap 样式广场与地面/道路同色，无法按颜色分割 | plaza 仅含被灰色分割出的停车场/铺装结构 |")
w()
w("建筑轮廓简化 `approxPolyDP(eps=2.0px)`，水/绿地 `eps=3.0px`；L 形/U 形靠外轮廓保留（不做 bbox）；"
  "**注意**：单环 polygon 无法表达内天井，中庭/内院会被填实（图幅内主要是图书馆、厚德楼等内院）。")
w()
w("分割统计：建筑像素（3x3 开运算后）%d，连通域 **%d** 个；按旧红线 `S01` 投影（缓冲 40px）裁剪后 **%d** 个在校园内，"
  "其中 %d 个被判为停车场/铺装（长条停车棚等），最终输出建筑 **%d** 个。" % (
      1236662, st["components_total"], st["components_in_campus"],
      st["parking_or_paved"], st["buildings_out"]))
w()
w("## 3. 锚点与 model→master 仿射拟合")
w()
w("### 3.1 锚点读取")
w()
w("在 master 上自动检测 AMap 蓝色 POI 图标（39 个 21–22px 圆形），再逐块 2.5x 放大裁切人工读标签文字，"
  "共读取 25 个校园标签；其中能与 `preview_data.json` 旧建筑唯一对应的 14 个作为控制点：")
w()
w("| # | master 标签 | 旧模型楼栋组 | 旧模型点 (x,y) | master 标签中心 (px) | 残差 (px) |")
w("|---|---|---|---|---|---|")
for i, a in enumerate(bt["anchors"], 1):
    w("| %d | %s | %s | (%s, %s) | (%s, %s) | %.2f |" % (
        i, a["label"], "、".join(a["old_ids"]), a["model_point"][0], a["model_point"][1],
        a["master_point"][0], a["master_point"][1], a["resid_px"]))
w()
w("> 复合楼（厚德楼、精诚楼、至善楼、五行楼、自强楼、求真楼、康复、实验动物中心、图书馆、名师苑）"
  "的旧模型点是“该标签所在翼”的多边形中心；拟合时先以组中心为初值，再迭代吸附到最近翼，收敛后固定。")
w()
w("### 3.2 最小二乘仿射（6 自由度，含旋转/缩放/剪切）")
w()
M = bt["model_to_master"]
w("```")
w("p_master_x = %.6f * x + %.6f * y %+.6f" % (M[0][0], M[0][1], M[0][2]))
w("p_master_y = %.6f * x + %.6f * y %+.6f" % (M[1][0], M[1][1], M[1][2]))
w("")
w("model_to_master = [[%.6f, %.6f, %.6f], [%.6f, %.6f, %.6f]]" % (
    M[0][0], M[0][1], M[0][2], M[1][0], M[1][1], M[1][2]))
w("```")
w()
r = bt["residual"]
w("残差统计（14 个锚点，master px）：**mean %.2f / median %.2f / p95 %.2f / max %.2f**；"
  "等价均匀尺度 %.4f，旋转 %.2f°。" % (r["mean"], r["median"], r["p95"], r["max"],
                                     bt["equivalent_scale"], bt["rotation_deg"]))
w()
w("残差来源（已核对）：① 旧数据来自总体规划示意图，与实际建成布局存在系统性偏差；"
  "② 旧模型楼栋是“翼级”多边形，标签落在复合楼整体中心附近，两者天然有 20–60px 偏移；"
  "③ AMap 标签是 POI 标注点，不一定落在建筑几何中心。")
w("另外用 old-model 楼栋轮廓对 master 建筑掩膜做过 chamfer/ICP 校验（平均轮廓距离 6.8px，`_work2/chamfer_fit.json`），"
  "与锚点仿射结果一致（~2–3% 差异），可作为交叉验证。")
w()
w("## 4. 建筑匹配方法")
w()
w("步骤（`_work2/r23_final2.py`）：")
w()
w("1. **单元划分**：旧数据里同一复合楼的多个翼（如 `B20–B23 厚德楼`、`B32–B35 五行楼`）先合并为"
  " 43 个“匹配单元”（11 个复合组 + 32 个单栋），避免整个复合楼和一个翼比面积。")
w("2. **标签匹配**：25 个已读 AMap 标签中 14 个能对上旧建筑，直接把“标签所在/最近的建筑连通域”"
  " 判给对应单元，confidence 0.86（图标在轮廓内时 0.94，如求真楼）。")
w("3. **几何匹配**：其余校园内连通域与其余单元做匈牙利指派，代价 = 中心距离 + 180×(1−IoU覆盖) + 70×|ln(面积比)|，"
  " 硬门槛：中心距离 ≤230px、面积比（连通域面积 ÷ 旧组面积·scale²）∈[0.3,3.2]、覆盖 >0.1；"
  " confidence = exp(−d/90)·(0.25+0.75·coverage)·min(1, 面积比, 1/面积比)，**<0.20 判 generic**。")
w("4. **名师苑补充**：标签只覆盖 1 栋，另外把岛上 190px 内、面积比合理的 2 个未匹配轮廓补为 B81/B82（confidence 0.55）。")
w("5. 复合楼只有一个连通域时输出组 head id（B20/B24/…）；多连通域时按最近翼分配不重复 id。")
w()
w("## 5. 匹配结果")
w()
mw = [b for b in bt["buildings"] if b["id"]]
gw = [b for b in bt["buildings"] if not b["id"]]
w("输出建筑 **%d** 栋：**已匹配 %d**（标签匹配 14、名师苑补充 2、几何匹配 13），**generic %d**。" % (
    len(bt["buildings"]), len(mw), len(gw)))
w()
w("| id | 旧名称 n | 置信度 | 方法 | 中心 (cx,cy) | 顶点数 |")
w("|---|---|---|---|---|---|")
rows = sorted(mw, key=lambda b: -b["confidence"])
how_map = {}
for r_ in st["matched_rows"]:
    how_map[(r_["id"], r_["cx"], r_["cy"])] = r_["how"]
for b in rows:
    how = how_map.get((b["id"], b["cx"], b["cy"]), "")
    w("| %s | %s | %.2f | %s | (%.0f, %.0f) | %d |" % (
        b["id"], b["n"], b["confidence"], how, b["cx"], b["cy"], len(b["points"])))
w()
w("> 所有已匹配建筑的轮廓都在自检图 `buildings_check.png` 中逐栋核对：轮廓贴合 AMap 灰色建筑块（含 L/U 形复合楼、"
  "阶梯状图书馆、圆形河洛时光等），未出现 bbox 代替问题。")
w()
w("### 5.1 旧数据中**对不上**的建筑（16 个单元）")
w()
w("| 旧 id(s) | 旧名称 | 原因判断 |")
w("|---|---|---|")
reasons = {
    "B44": "旧模型此处为教学综合楼组（4 翼），AMap 现状为空地/道路，无可对应轮廓",
    "B01": "旧 22# 在旧模型西侧，AMap 对应位置为空地；现状 22/23 号楼在湖心岛（名师苑区），与旧 23#A/B 不是同一组",
    "B02": "同上（旧 23 号楼 a 区与现状 AMap“23号楼”不是同一栋）",
    "B03": "同上（旧 23 号楼 b 区）",
    "B05": "宿舍编号体系不同（旧 12# 与现状 21 号楼一带拼合），无独立可配轮廓",
    "B11": "宿舍编号体系不同，剩余轮廓无法唯一对应",
    "B16": "宿舍编号体系不同（旧 9#）",
    "B17": "旧 后勤配套（西区）位置在 AMap 拼接范围边缘/无可辨析轮廓",
    "B54": "食堂第二栋，已合并为一个食堂轮廓（B53）",
    "B55": "旧 后勤配套小楼，拼接图内无对应",
    "B57": "旧 快递站位置无 POI 图标，AMap 对应处为顺丰/京东网点（橙色图标，未纳入锚点）",
    "B67": "旧 时珍园配套，AMap 对应位置为后勤管理处/绿地小建筑，名称无法互证",
    "B71": "田径场看台：拼接图内无田径场（见 §8）",
    "B72": "田径场看台：拼接图内无田径场（见 §8）",
    "B86": "旧 中药炮制实验室，投影落在北侧公园绿地内，拼接图内无该建筑",
    "B87": "旧 湖岸附属体，投影落在北侧公园绿地内，拼接图内无该建筑",
}
for u in st["unmatched_units"]:
    w("| %s | %s | %s |" % ("、".join(u["ids"]), u["ln"], reasons.get(u["head"], "")))
w()
w("### 5.2 generic 建筑（%d 个）" % len(gw))
w()
w("这些是 AMap 上有、但旧数据没有的建筑/结构，或校园内无法可靠归属的轮廓；`id=null, n=\"\", g=\"generic\", confidence=0`：")
w()
w("| # | 中心 (cx,cy) | 说明（按图判读） |")
w("|---|---|---|")
notes = {
    (2214, 1620): "中医文化博物馆（椭圆形建筑，旧数据无此楼）",
    (2213, 1056): "后勤管理处一带小楼",
    (2277, 1130): "后勤管理处 / 时珍园旁小建筑",
    (1153, 1609): "厚德楼东北侧小楼（许家卤味一带）",
    (1256, 2721): "大学生创新创业标准园区 / 创业孵化园大型建筑群",
    (2706, 824): "校外东北侧建筑（百氏大厦/守正楼方向）",
    (2468, 748): "修园楼北侧附属小楼",
    (922, 793): "公园/名师苑一带小建筑",
    (188, 1323): "校外西侧建筑（福州可贞印刷方向）",
    (576, 2357): "现状 19 号楼（旧数据无 19 号楼编号）",
    (344, 2503): "现状 18 号楼西侧建筑",
    (390, 2772): "现状 13/15 号楼一带（旧编号不同）",
    (1103, 3315): "校园南侧（溪源江边）小建筑",
    (1080, 3441): "校园南侧（溪源江边）小建筑",
}
for i, b in enumerate(gw, 1):
    key = (round(b["cx"]), round(b["cy"]))
    note = notes.get(key, "")
    if not note:
        if b["cy"] < 260:
            note = "北侧校外（联心村/园区）建筑"
        elif b["cy"] < 500:
            note = "北侧公园/校外零星建筑"
        else:
            note = "无法归属（旧数据无对应）"
    w("| %d | (%.0f, %.0f) | %s |" % (i, b["cx"], b["cy"], note))
w()
w("## 6. 水面 / 绿地 / 岛屿 / 广场")
w()
w("| 类别 | 数量 | 面积（master px²） | 说明 |")
w("|---|---|---|---|")
wa = [p["area"] for p in ft["water"]]
la = [p["area"] for p in ft["lawn"]]
w("| water | %d | %s | 宋慈湖被湖堤/桥分成南北 2 块（401696 + 258598 px²），其余为北侧公园湖（75417）、"
  "时珍园水系、3 个小水塘、图幅左下角溪源江（99143）|" % (
      len(ft["water"]), "、".join("%.0f" % a for a in wa)))
w("| island | %d | %.0f | 湖心岛（23 号楼/名师苑 所在岛），为水体内部孔洞 |" % (
    len(ft["island"]), ft["island"][0]["area"] if ft["island"] else 0))
w("| lawn | %d | %s | 北侧时珍园大绿地（401188）、时珍园小丘（55068）、5 处绿化带 |" % (
    len(ft["lawn"]), "、".join("%.0f" % a for a in la)))
w("| plaza | %d | %s | 仅两处西侧停车棚长条铺装（AMap 广场与地面同色，无法分割）|" % (
    len(ft["plaza"]), "、".join("%.0f" % p["area"] for p in ft["plaza"])))
w("| track | 0 | — | 拼接图内没有田径场/看台（见 §8）|")
w()
w("## 7. 自检")
w()
w("1. `buildings_check.png` = 读回 `buildings_trace.json` 的 polygon，逐栋叠画到 **master.png** 上（红=已命名、橙=generic），"
  "并叠加 water（蓝）、island（青）、lawn（绿）、plaza（橙棕）。已用 `read_image` 检查整图 + 5 张 1:1 裁切"
  "（`_work2/selfchk_north|mid|lib|east|dorm.png`）：建筑轮廓贴合灰色建筑块，未包含道路/文字/水面。")
w("2. 数量核对：建筑连通域 %d → 校园内 %d → 去掉停车场/铺装 %d → 输出 %d（matched %d / generic %d）；"
  "water %d、island %d、lawn %d、plaza %d、track %d。" % (
      st["components_total"], st["components_in_campus"], st["parking_or_paved"],
      st["buildings_out"], len(mw), len(gw), len(ft["water"]), len(ft["island"]),
      len(ft["lawn"]), len(ft["plaza"]), len(ft["track"])))
w("3. JSON 已校验：polygon 均为整数 master 像素、闭合、≥3 顶点；`model_to_master` 为 2x3；"
  "`points` 顺序为 `approxPolyDP` 的输出顺序（顺时针/逆时针不保证）。")
w()
w("## 8. 已知问题与限制（如实）")
w()
w("1. **田径场缺失**：三张原图拼接范围覆盖校园主体 + 北侧公园，但**没有田径场/看台**。旧模型 `T01/T02/B70/B71/B72` "
  "变换后落到 master (155–690, 880–1560) 的空白停车/荒地（见 `_work2/selfchk_north.png` 左侧），该地块在 AMap 上未绘运动场。"
  "新布局若需要田径场，只能沿用旧模型投影或补截一张更西/更高 zoom 的 AMap 图。")
w("2. **广场无法按色提取**：AMap 本样式广场、道路、地面同为 `#e6f0f9/#faf8f6`，没有独立填充。plaza 只包含灰色停车/铺装结构；"
  "需要的广场（棋盘广场、青年广场、厚德楼前广场等）建议后续手描或用旧数据 G02/G03 投影。")
w("3. **规划示意图 vs 实景差异**：旧数据是总体规划设计图（北向约右上 40–55°），不是实景测量图；"
  "`B01–B03`(22#/23#A/B)、`B44–B47`(综合楼)、`B86/B87`、田径场等与现状无法对应；"
  "锚点残差 mean 34px 也主要来自这类系统性差异。")
w("4. **宿舍编号体系不一致**：旧数据为 `8#/9#/10#/11#/12# + 学生公寓×7`，AMap 现状为 `11–21 号楼`。"
  "`B05–B16` 的 9 个匹配是按位置/面积做的（confidence 0.20–0.81），**编号含义不可靠**；"
  "新布局若要显示“11 号楼/21 号楼”等现状名，需要另行按 AMap 文字标签校正。")
w("5. **低置信几何匹配**：B52 河洛时光 0.43、B53 食堂 0.38、B58 培训中心 0.36、B56 后勤配套 0.24 等为邻近位置匹配，"
  "其中 B58↔AMap“成人教育学院”楼、B56 的具体归属存在不确定性；使用前建议按 confidence 过滤（≥0.5 可视为可靠）。")
w("6. **园区外结构**：由于旧校园红线 `S01` 是多边形近似投影（缓冲 40px），少量校园外结构（北侧联心村一带 3 栋、"
  "东北百氏大厦旁 1 栋、西侧 1 栋）也进入了输出（均为 generic），如不需要可在渲染端按坐标裁掉。")
w("7. **内院被填实**：单环 polygon 无法表达孔洞（图书馆、厚德楼等中庭），如需精确轮廓需改为多环 polygon。")
w("8. **west 图重采样**：拼接时 west 图被缩放到 87.8%，该区域建筑轮廓边缘有 1px 级抖动；建筑整体形状不受影响。")
w()
w("## 9. 使用说明 / 下游建议")
w()
w("- 渲染多边形：直接取 `buildings_trace.json.buildings[].points`（master px），按 `[w,h]=master_size` 做视口变换；"
  "`id/n/no/k/g` 可直接做标签和配色（`g` 分组：residential/academic/civic/sports/landscape）。")
w("- 只有 `id != null` 的建筑有旧数据身份；`g=\"generic\"` 的需要新 ID。")
w("- 若要做 3D/体块，可用旧数据 `h/fl` 通过 `id` 关联 `preview_data.json` 的 `buildings` 表。")
w("- 水系/绿地多边形是单环外轮廓（面积已给出），可直接用 `features_trace.json.water/lawn/island`。")
w("- 中间脚本（`_work2/r00–r24*.py`）可复现全部结果；调试图含 `d_full_overlay.png`、`mask_vis1.png` 等。")
w()

open(os.path.join(AMAP, "buildings_report.md"), "w", encoding="utf-8").write("\n".join(L))
print("report written, %d lines" % len(L))
