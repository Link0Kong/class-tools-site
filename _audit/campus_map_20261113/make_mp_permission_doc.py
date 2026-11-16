# -*- coding: utf-8 -*-
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113"
OUT = os.path.join(BASE, "校园地图_定位权限申请_20261116.docx")
IMG_LOC = os.path.join(BASE, "mp_location_demo.png")
IMG_MAP = os.path.join(BASE, "小程序_地图2.5D.png")
IMG_AUX = os.path.join(BASE, "申请材料_辅助图_定位与地图.png")

LONG_REASON = (
    "本小程序为福建中医药大学班级工具，校内地图用于帮助同学在旗山校区寻找教学楼、图书馆、食堂、宿舍等目的地。"
    "校园面积较大、建筑和道路较多，用户仅靠平面图容易走错。地图页提供 2.5D 校园地图和按道路的步行导航；"
    "用户主动点击“定位”时，需要获取一次当前位置，用于在地图上显示“我的位置”蓝点、判断用户与目标楼的相对位置，并计算步行路线和距离。"
    "该定位仅在前台、由用户主动触发，不后台持续获取，不追踪用户移动轨迹；拒绝授权时仍可正常浏览地图、搜索楼栋和查看静态路线。"
)

SHORT_REASON = (
    "校园地图需要显示用户当前位置并计算到教学楼的步行路线。仅在用户点击“定位”时前台获取一次位置，"
    "用于地图蓝点和路线距离；不后台持续定位、不追踪轨迹。拒绝授权不影响地图浏览与搜索。"
)

privacy = (
    "1. 仅申请 wx.getLocation（前台单次定位），未使用 wx.onLocationChange、wx.startLocationUpdate，不申请后台定位。\n"
    "2. 位置仅在小程序前台、用户主动点击“定位”后获取；用于地图蓝点、目标楼相对位置和步行路线计算。\n"
    "3. 不将经纬度上传到服务器、不写入云端、不提供给第三方、不用于广告或用户画像；退出页面后不保留连续定位。\n"
    "4. 用户拒绝授权时，地图浏览、楼栋搜索、静态路线等功能仍可使用，不会阻断其他班级工具。\n"
    "5. 已在 app.json 声明 scope.userLocation 用途说明，并在小程序隐私保护指引中声明位置信息用途。"
)

doc = Document()
sec = doc.sections[0]
sec.top_margin = Cm(2.0); sec.bottom_margin = Cm(2.0)
sec.left_margin = Cm(2.2); sec.right_margin = Cm(2.2)

style = doc.styles["Normal"]
style.font.name = "Microsoft YaHei"
style.font.size = Pt(10.5)
style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

def para(text="", bold=False, size=10.5, after=6, align=None):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = bold; r.font.size = Pt(size)
    r.font.name = "Microsoft YaHei"; r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    p.paragraph_format.space_after = Pt(after)
    if align is not None: p.alignment = align
    return p

def heading(text, size=14):
    p = doc.add_paragraph()
    r = p.add_run(text); r.bold = True; r.font.size = Pt(size)
    r.font.color.rgb = RGBColor(0x2E, 0x6B, 0x5E)
    r.font.name = "Microsoft YaHei"; r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    p.paragraph_format.space_before = Pt(10); p.paragraph_format.space_after = Pt(5)
    return p

def cell_text(cell, text, bold=False):
    cell.text = ""
    p = cell.paragraphs[0]
    r = p.add_run(text); r.bold = bold; r.font.size = Pt(10)
    r.font.name = "Microsoft YaHei"; r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = title.add_run("微信小程序接口权限申请材料")
r.bold = True; r.font.size = Pt(20); r.font.color.rgb = RGBColor(0x23, 0x30, 0x2E)
r.font.name = "Microsoft YaHei"; r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
sub = doc.add_paragraph(); sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = sub.add_run("申请接口：wx.getLocation｜校园 2.5D 地图 · 步行导航")
r.font.size = Pt(10.5); r.font.color.rgb = RGBColor(0x7C, 0x8A, 0x86)
r.font.name = "Microsoft YaHei"; r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

fields = [
    ("小程序名称", "班级工具（福建中医药大学班级工具）"),
    ("AppID", "wx3df9869d229b96c4"),
    ("申请接口", "wx.getLocation"),
    ("是否申请持续/后台定位", "否。未使用 wx.onLocationChange、wx.startLocationUpdate。"),
    ("定位触发方式", "仅用户进入“校内地图”并主动点击“定位”时，前台获取一次当前位置。"),
    ("使用目的", "显示“我的位置”蓝点；判断与目标教学楼的相对位置；计算到目标楼的步行路线和距离。"),
    ("是否上传位置", "否。经纬度仅在小程序本地参与地图投影和路线计算，不上传服务器、不写云端、不共享给第三方。"),
]

table = doc.add_table(rows=0, cols=2)
table.alignment = WD_TABLE_ALIGNMENT.CENTER
table.style = "Table Grid"
for k, v in fields:
    row = table.add_row()
    cell_text(row.cells[0], k, True)
    cell_text(row.cells[1], v)
    row.cells[0].width = Cm(4.2); row.cells[1].width = Cm(12.0)

heading("一、申请原因（可直接复制到后台）")
para(LONG_REASON)

heading("二、短版申请原因（如后台有字数限制）")
para(SHORT_REASON)

heading("三、用户使用路径")
for t in [
    "1. 打开小程序 → 完成班级身份验证 → 进入“全部 → 地图”。",
    "2. 点击地图工具栏“定位”，微信弹出位置权限说明，用户可选择允许或拒绝。",
    "3. 允许后，地图显示“我的位置”蓝点，并自动定位到用户附近；用户搜索/点选目标楼（如图书馆、自强楼）。",
    "4. 地图按校园道路计算步行路线，显示路线、预计分钟数和距离；可切换正大门/东侧门/宿舍区等起点。",
    "5. 拒绝授权时，仍可浏览 2.5D 地图、搜索楼栋、查看从校门出发的静态路线，不影响其他工具。",
]:
    para(t, after=3)

heading("四、隐私与合规说明")
for line in privacy.split("\n"):
    para(line, after=3)

heading("五、辅助图片")
para("图 1：用户点击“定位”后显示“我的位置”蓝点；图 2：校内 2.5D 地图与按道路步行路线。定位坐标为测试坐标，仅用于演示界面效果。", after=4)
doc.add_picture(IMG_AUX, width=Cm(9.5))
doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
cap = doc.add_paragraph(); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = cap.add_run("图 1  定位蓝点与楼栋信息　｜　图 2  2.5D 地图与步行导航"); r.font.size = Pt(9); r.font.color.rgb = RGBColor(0x7C,0x8A,0x86)

heading("六、审核测试路径")
for t in [
    "测试版本：开发版/体验版（无需真实班级数据即可打开地图页）。",
    "路径：工具 → 地图 → 定位 → 允许位置权限 → 地图出现“我的位置”蓝点；搜索“图书馆”或“自强楼” → 查看步行路线。",
    "说明：开发版中可用开发者工具模拟位置；正式版由用户真机授权。",
]:
    para(t, after=3)

heading("七、补充说明")
para("本接口只服务于校园地图的“我在哪里、怎么走”场景，不做用户轨迹记录、不做后台定位、不做广告投放。地图页为班级工具内的辅助功能，定位权限被拒绝时不影响课表、作业、通知等其他功能。")

doc.save(OUT)
print("saved", OUT, os.path.getsize(OUT))
