# -*- coding: utf-8 -*-
"""Build a single-file, local-only demo board for the class notice page.

Data source: real QQ group messages from the last 7 days (curated manually).
Everything is embedded: images (posters generated locally), files (xlsx generated
locally), collection forms (minimal local HTML forms). Nothing is uploaded.
"""
import base64
import difflib
import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from openpyxl import Workbook

# 通知识别过滤器：与微信采集器共用同一份规则（例行汇报不算通知，如舍长群每晚
# 「308 已全员在寝室（赖荣恒请假）」）。append 而非 insert(0)，避免 scripts 目录
# 里的同名文件遮蔽标准库模块。
sys.path.append(r"G:\ClassTools\briefdesk\scripts")
from notice_filters import is_routine_report  # noqa: E402
import qq_file_names  # noqa: E402  QQ/微信文件名宽容匹配（与 fetch_qq_files 共用）
import notice_merge  # noqa: E402  跨源（微信/QQ）同通知判定与合并（task-25）
try:  # 2026-11-17 用户需求：摘要按「新闻导语」写法（确定性清洗，ai_brief/ai_quality 共用）
    import notice_style  # noqa: E402
except Exception:  # noqa: BLE001
    notice_style = None


def _news_summary(text, limit=60):
    if notice_style is not None:
        try:
            return notice_style.clean_summary(text, limit)
        except Exception:  # noqa: BLE001
            pass
    return str(text or "").strip()[:limit]


# 2026-11-17 摘要「事实覆盖度」择优（ai_brief vs 质检层摘要都合格时选更全的一条）
_FACT_CN_DATE = re.compile(r"(?:20\d{2}\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?")
# 支持 11-13 / 11.13 / 11‑13（QQ 原文常用点号/不间断连字符）等写法；排除时间范围（17:30-23:00）
_FACT_MD_DATE = re.compile(
    r"(?<![\d:])(\d{1,2})\s*[-.\-‑–—/]\s*(\d{1,2})(?![\d:])")
_FACT_TIME = re.compile(r"(?<![\d:])(\d{1,2})[:：](\d{2})(?!\d)")
_FACT_COUNT = re.compile(r"(\d{1,3})\s*(名|人|元|个|天|次|节|分)")


def _summary_facts(text):
    """摘要/原文里的关键事实指纹：日期（归一 MM-DD）、时间（HH:MM）、数量（N人/名…）。"""
    s = str(text or "")
    out = set()
    for m in _FACT_CN_DATE.finditer(s):
        out.add("M%02d-%02d" % (int(m.group(1)), int(m.group(2))))
    for m in _FACT_MD_DATE.finditer(s):
        out.add("M%02d-%02d" % (int(m.group(1)), int(m.group(2))))
    for m in _FACT_TIME.finditer(s):
        out.add("T%02d:%s" % (int(m.group(1)), m.group(2)))
    for m in _FACT_COUNT.finditer(s):
        out.add("N%s%s" % (m.group(1), m.group(2)))
    return out


def _summary_covers(summary, src_facts):
    if not src_facts:
        return 0
    return len(_summary_facts(summary) & src_facts)

BASE = Path(r"G:\ClassTools\web\briefdesk")
OUT = Path(r"G:\ClassTools\web\tools\notice-board-live-demo.html")
DOCS_JSON = Path(r"G:\ClassTools\briefdesk\data\docs-detected.json")
WECHAT_INBOX = Path(r"G:\ClassTools\briefdesk\data\wechat-inbox.jsonl")
WECHAT_NOTICES = Path(r"G:\ClassTools\briefdesk\data\wechat-notices.json")
AI_BRIEFS = Path(r"G:\ClassTools\briefdesk\data\ai-briefs.json")
AI_MERGED = Path(r"G:\ClassTools\briefdesk\data\ai-merged.json")
AI_CATEGORIES = Path(r"G:\ClassTools\briefdesk\data\ai-categories.json")
AI_QUALITY = Path(r"G:\ClassTools\briefdesk\data\ai-quality.json")
QQ_MERGED = Path(r"G:\ClassTools\briefdesk\data\qq-merged.json")
QQ_TEXT = Path(r"G:\ClassTools\briefdesk\data\qq-text-notices.json")
QQ_IMAGE_TEXT = Path(r"G:\ClassTools\briefdesk\data\qq-image-notices.json")
QQ_FILE_TEXT = Path(r"G:\ClassTools\briefdesk\data\qq-file-notices.json")
QQ_CONTEXT = Path(r"G:\ClassTools\briefdesk\data\qq-context-overrides.json")
AI_TRIAGE = Path(r"G:\ClassTools\briefdesk\data\ai-triage-notices.json")
AI_SUPPLEMENTS = Path(r"G:\ClassTools\briefdesk\data\ai-supplements.json")
MANUAL_PATCHES = Path(r"G:\ClassTools\briefdesk\data\notice-manual-patches.json")
# 契约 §1.4：AI 管线（notice_threads.py）产出的「更新/更正通知合并」结果
NOTICE_THREADS = Path(r"G:\ClassTools\briefdesk\data\notice-threads.json")

# 非学校群（商业培训/平台）来源的通知一律不上板
NON_SCHOOL_GROUP_PATTERNS = ("冲刺班", "二级Ms", "二级MS", "志愿者网站系统")
CLASS_ROSTER = Path(r"G:\ClassTools\briefdesk\data\class-members.json")
# 契约 §5：网名/昵称 → 真实姓名 + 职务（class-identities 聚合 QQ/微信身份，class-aliases 昵称→学号）
CLASS_IDENTITIES = Path(r"G:\ClassTools\briefdesk\data\class-identities.json")
CLASS_ALIASES = Path(r"G:\ClassTools\briefdesk\data\class-aliases.json")
QQ_FILES = Path(r"G:\ClassTools\briefdesk\data\qq-files")
HOMEWORK_STATIC = Path(r"G:\ClassTools\briefdesk\data\homework-static.json")
BOARD_DATA = Path(r"G:\ClassTools\briefdesk\data\board-data.json")
IMAGE_MANIFEST = Path(r"G:\ClassTools\briefdesk\data\images-manifest.json")
REAL_QR = Path(r"G:\ClassTools\briefdesk\data\qr_guests.jpg")

SCHEDULE = [
    {"day": "周一", "periods": "1-3", "course": "思政课", "room": "1202", "note": "11/02 起调至周二 6-8 节"},
    {"day": "周一", "periods": "8-9", "course": "太极拳", "room": "操场/篮球场", "note": "11/02 场地湿滑改观看"},
    {"day": "周二", "periods": "6-8", "course": "思政课", "room": "1202", "note": "调课"},
]

FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"


# ---------------------------------------------------------------- assets

def data_uri(mime: str, blob: bytes) -> str:
    return f"data:{mime};base64," + base64.b64encode(blob).decode("ascii")


def make_poster(title_lines, subtitle, tag, color1, color2):
    w, h = 900, 560
    img = Image.new("RGB", (w, h), "#FFFFFF")
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(color1[0] * (1 - t) + color2[0] * t)
        g = int(color1[1] * (1 - t) + color2[1] * t)
        b = int(color1[2] * (1 - t) + color2[2] * t)
        d.line([(0, y), (w, y)], fill=(r, g, b))
    # decorative circles
    d.ellipse([w - 260, -120, w + 120, 260], outline=(255, 255, 255), width=3)
    d.ellipse([-80, h - 200, 220, h + 80], outline=(255, 255, 255), width=3)
    y = 120
    for line, size in title_lines:
        font = ImageFont.truetype(FONT_BOLD, size)
        d.text((70, y), line, font=font, fill=(255, 255, 255))
        y += size + 26
    font = ImageFont.truetype(FONT_REG, 30)
    for line in subtitle.split("\n"):
        d.text((70, y + 12), line, font=font, fill=(238, 246, 244))
        y += 44
    font_tag = ImageFont.truetype(FONT_BOLD, 22)
    d.rounded_rectangle([70, h - 86, 70 + 250, h - 42], radius=12, fill=(255, 255, 255))
    d.text((88, h - 76), tag, font=font_tag, fill=color1)
    # watermark
    font_w = ImageFont.truetype(FONT_REG, 16)
    d.text((w - 250, h - 34), "示例图 · 本地演示", font=font_w, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return data_uri("image/jpeg", buf.getvalue())


def make_qr_card(title, subtitle):
    """Stylized QR placeholder for a group-join notice (not scannable, demo only)."""
    import random
    size = 460
    img = Image.new("RGB", (size, size), "#FFFFFF")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, size - 8, size - 8], radius=18, outline=(210, 224, 219), width=2)
    rnd = random.Random(hash(title) & 0xFFFF)
    module = 14
    grid = 21
    ox = oy = 62
    for row in range(grid):
        for col in range(grid):
            if 2 <= row <= 14 and 2 <= col <= 14:
                continue
            if rnd.random() < 0.45:
                x = ox + col * module
                y = oy + row * module
                d.rectangle([x, y, x + module - 2, y + module - 2], fill=(35, 48, 46))
    # finder patterns
    for fx, fy in [(ox, oy), (ox + (grid - 7) * module, oy), (ox, oy + (grid - 7) * module)]:
        d.rectangle([fx, fy, fx + 7 * module - 2, fy + 7 * module - 2], fill=(35, 48, 46))
        d.rectangle([fx + module, fy + module, fx + 6 * module - 2, fy + 6 * module - 2], fill="#FFFFFF")
        d.rectangle([fx + 2 * module, fy + 2 * module, fx + 5 * module - 2, fy + 5 * module - 2], fill=(35, 48, 46))
    # center badge
    bw, bh = 190, 64
    bx, by = (size - bw) // 2, (size - bh) // 2
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=14, fill="#4E9082", outline="#FFFFFF", width=4)
    fb = ImageFont.truetype(FONT_BOLD, 24)
    d.text((bx + 24, by + 14), "群二维码", font=fb, fill="#FFFFFF")
    ft = ImageFont.truetype(FONT_BOLD, 22)
    d.text((60, 386), title, font=ft, fill="#23302E")
    fs = ImageFont.truetype(FONT_REG, 17)
    d.text((60, 416), subtitle, font=fs, fill="#5A6A67")
    fw = ImageFont.truetype(FONT_REG, 14)
    d.text((size - 190, size - 26), "示例图 · 本地演示", font=fw, fill="#8C9A97")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return data_uri("image/jpeg", buf.getvalue())


def load_real_images():
    """fileName -> data URI, from images synced out of the QQ image cache."""
    try:
        data = json.loads(IMAGE_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result = {}
    for item in data:
        path = Path(item.get("localPath", ""))
        if not path.exists():
            continue
        suffix = path.suffix.lower()
        mime = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "image/jpeg")
        result[item.get("fileName", "")] = data_uri(mime, path.read_bytes())
    return result


def load_real_qr():
    try:
        if REAL_QR.exists():
            return data_uri("image/jpeg", REAL_QR.read_bytes())
    except Exception:
        pass
    return None


def make_xlsx(headers, rows, sheet="Sheet1") -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for r in rows:
        ws.append(r)
    for i, w in enumerate([10, 18, 16, 28], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.append([])
    ws.append(["说明：本文件为示例数据，真实上线时链接到 QQ 群文件。"])
    buf = io.BytesIO()
    wb.save(buf)
    return data_uri("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buf.getvalue())


def make_form(title, desc, fields) -> str:
    rows = "\n".join(
        f'<label>{f}</label><input name="{f}" placeholder="请输入{f}" {("inputmode=\'numeric\'" if "号" in f or "电话" in f else "")}>'
        for f in fields
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{margin:0;background:#F7F8F8;color:#23302E;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;font-size:15px;line-height:1.7}}
.wrap{{max-width:520px;margin:0 auto;padding:24px 16px 60px}}
.card{{background:#fff;border:1px solid #E6E9E8;border-radius:16px;padding:18px}}
h1{{font-size:19px;margin:0 0 6px}}
.desc{{font-size:12.5px;color:#5A6A67;line-height:1.7}}
label{{display:block;font-size:12.5px;color:#5A6A67;font-weight:600;margin:14px 0 5px}}
input{{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #E6E9E8;border-radius:10px;font:inherit;outline:none}}
input:focus{{border-color:#4E9082;box-shadow:0 0 0 3px rgba(78,144,130,.1)}}
button{{width:100%;margin-top:18px;padding:11px;border:0;border-radius:10px;background:#4E9082;color:#fff;font:inherit;font-weight:700;cursor:pointer;min-height:44px}}
.note{{margin-top:12px;font-size:11px;color:#8C9A97;line-height:1.7}}
</style></head><body><div class="wrap"><div class="card">
<h1>{title}</h1><div class="desc">{desc}</div>
<form onsubmit="event.preventDefault();alert('示例表单：仅本地演示，不会上传任何数据。')">
{rows}
<button type="submit">提交（示例）</button>
</form>
<div class="note">本页是本地示例，不会提交、不会上传；真实上线时由班级工具站接入正式收集表。</div>
</div></div></body></html>"""


# ---------------------------------------------------------------- data (real messages, curated)

def clean_name(name: str) -> str:
    name = re.sub(r"\d{11}", "", name or "")
    return name.strip()


def build_groups():
    posters = {
        "recruit": make_poster(
            [("人文与管理学院", 40), ("校园招聘会志愿者招募", 52)],
            "11月5日（周四）14:00–17:00\n旗山校区室内篮球场 · 招募 7 人",
            "校园招聘会 · 志愿者", (37, 96, 130), (78, 144, 130),
        ),
        "games": make_poster(
            [("2026 校运动会", 44), ("观众征集 · 每班每半日 6 人", 40)],
            "11月4–6日 · 旗山校区操场\n6 个半日场次 · 截止 11 月 3 日 18:00",
            "校运动会 · 观众征集", (78, 112, 158), (185, 143, 99),
        ),
        "food": make_poster(
            [("食不易得 · 惜粮在行", 46), ("主题手抄报活动", 44)],
            "10月30日–11月15日\n报名 11月3日 20:30 截止 · 作品 11月12日 20:00 前提交",
            "膳食管理委员会 · 主题活动", (86, 120, 96), (150, 170, 110),
        ),
        "dorm": make_poster(
            [("宿舍卫生检查", 50), ("每月前三周 · 周三 17:30", 38)],
            "检查重点：卫生 / 收纳 / 用电安全\n请各宿舍提前整理",
            "人文与管理学院 · 权益部", (110, 118, 116), (90, 112, 108),
        ),
    }

    qr = {
        "vol": make_qr_card("运动会志愿者群", "扫码加入志愿者群"),
        "redcross": make_qr_card("管院红会干事群", "扫码加入红会干事群"),
    }
    real_qr = load_real_qr() or qr["vol"]
    real_images = load_real_images()
    vol_real = real_images.get("DE8F0D7F011CF11F3B5878911711AF0E.jpg")

    files = {
        "vol_names": make_xlsx(
            ["序号", "姓名", "岗位", "备注"],
            [[1, "示例同学 A", "检录处", "上午班"], [2, "示例同学 B", "物资组", "下午班"], [3, "示例同学 C", "引导", "全天"]],
        ),
        "vol_result": make_xlsx(
            ["序号", "姓名", "录用结果", "报到时间"],
            [[1, "示例同学 A", "补录成功", "11-06 13:00"], [2, "示例同学 B", "补录成功", "11-06 13:00"]],
            sheet="补录结果",
        ),
        "seat": make_xlsx(
            ["区域", "排", "座位", "备注"],
            [["右侧", "2–9 排", "按班级就座", "18:45 前签到"], ["左侧", "1–4 排", "按班级就座", "18:45 前签到"]],
            sheet="座位安排",
        ),
    }

    forms = {
        "recruit": make_form(
            "校园招聘会志愿者报名（示例）",
            "11月5日 14:00–17:00 · 旗山校区室内篮球场 · 招募 7 人。请确认该时段有空。",
            ["姓名", "学号", "手机号", "可到岗时段"],
        ),
        "games_vol": make_form(
            "校运动会志愿者补招报名（示例）",
            "补招 4 人 · 11月6日 13:00–17:00 · 旗山校区操场。",
            ["姓名", "学号", "手机号", "备注"],
        ),
        "games_viewer": make_form(
            "校运动会观众报名（示例）",
            "11月4–6日，每个半日每班 6 名观众，可多选时段。",
            ["姓名", "学号", "可参加时段", "手机号"],
        ),
        "food": make_form(
            "食不易得 · 主题手抄报活动报名（示例）",
            "报名时间 11月3日 12:00–20:30；作品请在 11月12日 20:00 前提交至群作业。",
            ["姓名", "学号", "学院", "手机号"],
        ),
        "redcross": make_form(
            "运动会救护志愿者报名（示例）",
            "招募 12 名志愿者，服务时段按上午/下午两班排班，服务时长录入志愿汇。",
            ["姓名", "学号", "手机号", "可值班时段"],
        ),
    }

    def T(t, name):
        return clean_name(name)

    groups = [
        {
            "id": "g_recruit", "cat": "活动", "title": "人文与管理学院校园招聘会志愿者招募",
            "summary": "11 月 5 日（周四）14:00–17:00，旗山校区室内篮球场，招募 7 人；收集表原定 11 月 3 日 17:30 截止，已延期至 11 月 5 日 12:00。",
            "group": "2026级信息管理与信息系统聊天群", "source": "QQ 群 · 2026级信管聊天群",
            "deadline": "2026-11-03T17:30:00+08:00",
            "extensions": [{"deadline": "2026-11-05T12:00:00+08:00", "note": "经学院协调，招聘会志愿者报名延长至 11 月 5 日 12:00", "at": "11-03 19:26", "demo": True}],
            "aiNote": "AI 判断：腾讯文档「11.5招聘会志愿者」与 11/03 通知是同一事项，已并入本组；收集表已换成真实文档链接。",
            "items": [
                {"kind": "text", "label": "原始通知", "time": "11-03 13:07", "from": "08同学C",
                 "text": "2026年11月5日人文与管理学院校园招聘会志愿活动通知：学院将于 11 月 5 日（周四）14:00-17:00，在旗山校区室内篮球场举办福建中医药大学 2027 届毕业生综合管理服务类专场招聘会。为保障招聘会有序开展，现面向全院招募志愿者，工作内容为现场引导、展位协助、秩序维护、物资整理及后勤支援。招募人数 7 人；报名方式：收集表填写个人信息，先到先得。收集表开放时间：11月3日17:00；收集表截止时间：11月3日17:30。"},
                {"kind": "form", "label": "报名收集表", "time": "11-03 13:07", "name": "招聘会志愿者报名表", "form": "recruit",
                 "open": "11-03 17:00", "close": "11-03 17:30", "note": "先到先得 · 需确认时段有空"},
                {"kind": "img", "label": "通知图片", "time": "11-03 13:07", "from": "08同学C", "src": posters["recruit"], "caption": "招聘会志愿者招募通知（示例图）"},
                {"kind": "follow", "label": "延期通知（示例）", "time": "11-03 19:26", "from": "演示消息",
                 "text": "【延期通知·示例】经学院协调，校园招聘会志愿者报名截止时间延长至 11 月 5 日 12:00，请未报名的同学继续填写收集表。"},
            ],
        },
        {
            "id": "g_games_vol", "cat": "活动", "title": "校运动会志愿者：招募、名单、补招与补录结果",
            "summary": "10 月 31 日发布原始招募通知（11.4–11.6，40 人，5 个时段收集表）；11 月 2 日补招 4 名（11.6 下午），当晚公布补录结果，请报名同学检查是否成功加群。",
            "group": "2026级信息管理与信息系统聊天群", "source": "QQ 群 · 2026级信管聊天群",
            "deadline": "2026-11-02T18:00:00+08:00",
            "aiNote": "AI 判断：原始招募（5 个时段收集表）、名单、补招与补录结果属同一场运动会志愿活动，已合并；6 个腾讯文档已全部并入本组。",
            "alert": "报名已于 11-02 18:00 截止；19:25 群内发布了「补录结果名单」，请核对是否录用（不随主通知自动完成）",
            "items": [
                {"kind": "text", "label": "原始通知", "time": "10-31 10:12", "from": "08同学C",
                 "text": ("2026年11月4-6日校运动会志愿活动通知：\n"
                          "为保障运动会的正常进行，帮助和鼓励运动员取得好成绩\n"
                          "🔆工作时间：\n"
                          "1⃣11.4上午8：00-12：00\n"
                          "2⃣11.4下午14：00-18：00\n"
                          "3⃣11.5上午8：00-12：00\n"
                          "4⃣11.5下午14：00-18：00\n"
                          "5⃣11.6上午8：00-12：00\n"
                          "🔆活动地点：旗山校区\n"
                          "🔆工作内容：给参赛的运动员当后勤，送水，陪同参加比赛等等\n"
                          "🔆招募人数：40人\n"
                          "1️⃣招募12名\n"
                          "2️⃣招募7名\n"
                          "3️⃣招募8名\n"
                          "4️⃣招募10名\n"
                          "5️⃣招募3名\n"
                          "🔆报名方式：收集表填写个人信息，先到先得\n"
                          "‼️要求志愿者在报名的时间段内有空，每个志愿者限报二个时间段，请大家仔细核对时间，志愿者在活动开展期间应当服从工作安排‼️\n"
                          "🌟收集表开放时间：10月31日12:00\n"
                          "🌟收集表截止时间：10月31日14:00")},
                {"kind": "text", "label": "名单公布", "time": "10-31 20:50", "from": "08同学C",
                 "text": "以上是报名成功的志愿者名单，请在名单中的同学尽快加入以下群聊。"},
                {"kind": "img", "label": "群二维码", "time": "10-31 20:50", "from": "08同学C", "src": qr["vol"],
                 "caption": "运动会志愿者群二维码（示例图）", "note": "对应上一条「请在名单中的同学尽快加入以下群聊」"},
                {"kind": "file", "label": "附件", "time": "10-31 20:50", "name": "运动会志愿者招募名单.xlsx", "size": "示例 12 KB", "src": files["vol_names"], "note": "QQ 群文件 · 示例文件"},
                {"kind": "text", "label": "补招通知", "time": "11-02 13:33", "from": "08同学C",
                 "text": "【补招通知】2026年11月4-6日校运动会志愿活动通知：为保障运动会的正常进行，现补招 4 名志愿者。工作时间：11.6 下午 13:00-17:00；活动地点：旗山校区操场；工作内容：给参赛运动员当后勤、送水、陪同参加比赛等。报名方式：收集表填写个人信息，先到先得。收集表开放时间：11月2日17:00；收集表截止时间：11月2日18:00。"},
                {"kind": "form", "label": "补招报名", "time": "11-02 13:33", "name": "运动会志愿者补招报名表", "form": "games_vol",
                 "open": "11-02 17:00", "close": "11-02 18:00", "note": "补招 4 人 · 11.6 下午"},
                {"kind": "file", "label": "补录结果", "time": "11-02 19:25", "name": "管院运动会志愿活动（补录结果）.xlsx", "size": "示例 11 KB", "src": files["vol_result"], "note": "QQ 群文件 · 示例文件", "postDeadline": True},
                {"kind": "text", "label": "补充", "time": "11-02 19:25", "from": "08同学C",
                 "text": "以上是报名成功的志愿者名单，请在名单中的同学尽快加入以下群聊。请之前报名管院运动会志愿者的同学检查是否成功加群。", "postDeadline": True},
                {"kind": "img", "label": "群二维码（真实）" if vol_real else "群二维码", "time": "11-02 19:25", "from": "08同学C",
                 "src": vol_real or qr["vol"],
                 "caption": "校运会志愿者群二维码（真实抓取，群号 1107682885）" if vol_real else "志愿者群二维码（示例图）",
                 "note": "对应「请加入以下群聊」· 从 QQ 图片缓存抓取" if vol_real else "对应「请加入以下群聊」", "postDeadline": True},
            ],
        },
        {
            "id": "g_games_viewer", "cat": "活动", "title": "校运动会观众征集，每班每半日 6 名",
            "summary": "11 月 4–6 日校运动会，需向 25、26 级各班征集观众，6 个半日时段各 6 人，截止今天 18:00；含群里真实群二维码。",
            "group": "2026级信息管理与信息系统", "source": "QQ 群 · 2026级信管群",
            "deadline": "2026-11-03T18:00:00+08:00",
            "keepOpen": True,
            "aiNote": "AI 判断：14:02 的腾讯文档「运动会观众征集」与该通知是同一事项，已并入本组；打开的是真实表格。",
            "items": [
                {"kind": "text", "label": "原始通知", "time": "11-03 14:03", "from": "64同学A",
                 "text": "关于举行 2026 年 11 月 4 日-11 月 6 日校运动会通知：为保证校运动会顺利开展，需要向 25 级、26 级各班征集运动会观众，每半日需要各班 6 名观众。我们现征集 4 日上午、4 日下午、5 日上午、5 日下午、6 日上午、6 日下午的观众。截止今天六点半！"},
                {"kind": "form", "label": "观众报名", "time": "11-03 14:03", "name": "校运动会观众报名表", "form": "games_viewer",
                 "open": "11-03", "close": "11-03 18:00", "note": "选可参加时段 · 每班每半日 6 人"},
                {"kind": "img", "label": "群二维码（真实）", "time": "11-03 14:02", "from": "64同学A", "src": real_qr,
                 "caption": "运动会观众群二维码（真实抓取）", "note": "扫码加入「运动会观众」群 · 从 QQ 图片复制"},
                {"kind": "img", "label": "通知图片", "time": "11-03 14:02", "from": "64同学A", "src": posters["games"], "caption": "校运动会观众征集（示例图）"},
            ],
        },
        {
            "id": "g_food", "cat": "活动", "title": "“食不易得，惜粮在行”主题手抄报活动",
            "summary": "10 月 30 日–11 月 15 日，征集主题手抄报；报名 11 月 3 日 12:00–20:30，作品 11 月 12 日 20:00 前提交至群作业。",
            "group": "2026级信息管理与信息系统聊天群", "source": "QQ 群 · 2026级信管聊天群",
            "deadline": "2026-11-03T20:30:00+08:00",
            "items": [
                {"kind": "text", "label": "活动通知", "time": "11-02 10:46", "from": "21同学I",
                 "text": "各位同学大家好～这个秋日，由福建中医药大学学生膳食管理委员会承办的“食不易得，惜粮在行”主题活动正式启动啦！活动对象：全体在校学生。活动时间：2026年10月30日-11月15日。开群时间：11月3日 12:00。收集表报名时间：11月3日12:00-20:30。参与者在 11月5日-11日期间完成主题手抄报绘画，于 11月12日20:00 前将作品拍照提交至群作业，并在作品右下角写上姓名、学号、学院信息，审核合格后可获得活动证明。具体内容见策划书。"},
                {"kind": "form", "label": "活动报名", "time": "11-02 10:46", "name": "食不易得 · 主题手抄报报名表", "form": "food",
                 "open": "11-03 12:00", "close": "11-03 20:30", "note": "报名后进活动群 · 作品 11-12 前提交"},
                {"kind": "img", "label": "活动海报", "time": "11-02 10:46", "from": "21同学I", "src": posters["food"], "caption": "惜粮主题活动（示例图）"},
                {"kind": "follow", "label": "时间节点", "time": "11-02 10:46", "from": "活动通知",
                 "text": "作品提交截止：11 月 12 日 20:00（提交至群作业，照片需含姓名/学号/学院）。"},
            ],
        },
        {
            "id": "g_welcome", "cat": "班级事务", "title": "新生欢迎会：签到与座位安排",
            "summary": "10 月 29 日 18:45 前到旗山厅签到就座；座位表已发群文件，现场最右侧二到九排为本班区域。",
            "group": "2026级信息管理与信息系统", "source": "QQ 群 · 2026级信管群",
            "deadline": "2026-10-29T18:45:00+08:00",
            "items": [
                {"kind": "text", "label": "原始通知", "time": "10-29 15:16", "from": "64同学A",
                 "text": "同学们要记得今天晚上 18:45 前到旗山厅签到就座哈。"},
                {"kind": "file", "label": "座位表", "time": "10-29 15:17", "name": "新生欢迎会座位安排.xlsx", "size": "示例 10 KB", "src": files["seat"], "note": "QQ 群文件 · 示例文件"},
                {"kind": "text", "label": "补充", "time": "10-29 15:18", "from": "64同学A", "text": "这是我们今天晚上的座位安排。"},
                {"kind": "text", "label": "现场提醒", "time": "10-29 18:40", "from": "61 同学K", "text": "到了的记得找我签到，暂时无法签到的记得私信。"},
                {"kind": "follow", "label": "后续补充", "time": "10-29 18:40", "from": "64同学A", "text": "是最右侧二到九排。"},
            ],
        },
        {
            "id": "g_redcross", "cat": "活动", "title": "学院运动会救护志愿者招募（红会）",
            "summary": "招募 12 名志愿者，服务运动会救护与物资保障；填收集表报名，截止 10 月 28 日晚八点。",
            "group": "第17届管院红会干事群", "source": "QQ 群 · 第17届管院红会干事群",
            "deadline": "2026-10-28T20:00:00+08:00",
            "items": [
                {"kind": "text", "label": "原始通知", "time": "10-28 09:48", "from": "25健管同学J",
                 "text": "各位红会干事：为做好运动员健康保障，提供赛前赛后休息服务，保管急救物资、大本营看管以及物资补给分发工作，现开展学院运动会救护志愿活动，招募 12 名志愿者。活动地点为旗山校区田径场。活动每日分上午 8:00-12:00、下午 13:00-17:00 两班，每班 5 人含机动岗位，每位志愿者原则上需要值两班，服务时长录入志愿汇。"},
                {"kind": "form", "label": "报名收集表", "time": "10-28 09:49", "name": "运动会救护志愿者报名表", "form": "redcross",
                 "open": "10-28 09:49", "close": "10-28 20:00", "note": "招募 12 人 · 服务时长录入志愿汇"},
                {"kind": "text", "label": "截止提醒", "time": "10-28 12:05", "from": "25健管同学J", "text": "截止时间今晚八点。"},
                {"kind": "follow", "label": "后续补充", "time": "10-28 18:53", "from": "25健管同学J", "text": "还需要 4 位志愿者哦，现在的人数还没有去年多。"},
            ],
        },
        {
            "id": "g_volunteer_app", "cat": "活动", "title": "运动会救护志愿：志愿汇报名（11 月 3 日 24:00 前）",
            "summary": "请在志愿汇搜索「11.4-6 人文与管理学院运动会救护志愿」报名；活动前 5 分钟发签到码，未签到签退不予补录。",
            "group": "2026运动会志愿者", "source": "QQ 群 · 2026运动会志愿者",
            "deadline": "2026-11-04T00:00:00+08:00",
            "items": [
                {"kind": "text", "label": "原始通知", "time": "11-02 19:14", "from": "25健管同学J",
                 "text": "请大家打开志愿汇搜索「11.4-6 人文与管理学院运动会救护志愿」报名志愿活动。进行志愿活动前 5 分钟会发签到码，因个人原因没有签到签退不予补录哈。请于 11 月 3 日 24:00 前完成。"},
                {"kind": "follow", "label": "操作提示", "time": "11-02 19:14", "from": "通知原文",
                 "text": "打开「志愿汇」App → 搜索活动名称 → 报名；服务当天提前 5 分钟到场签到，结束后签退。"},
            ],
        },
        {
            "id": "g_ideology", "cat": "教务", "title": "思政课调整：周一 1-3 节调至周二 6-8 节",
            "summary": "原通知（10/29）后，思政老师 11/2 再次确认调整；教室 1202，课表一律以「今日校园」为准。",
            "group": "2026级信息管理与信息系统", "source": "QQ 群 · 2026级信管群",
            "deadline": "2026-11-02T23:59:00+08:00",
            "aiNote": "AI 判断：10/29 原通知与 11/02「转思政老师再通知」是同一课次调整，已合并；课表以今日校园为准。",
            "items": [
                {"kind": "text", "label": "原始通知", "time": "10-29 20:28", "from": "68同学L",
                 "text": "下周的思政课进行如下调整：下周一上午 1-3 节课调为下周二下午 6-8 节，教室是 1202。"},
                {"kind": "follow", "label": "更正/更新", "time": "11-02 07:08", "from": "68同学L",
                 "text": "转思政老师再通知：周一（今天）上午 1-3 节课调为周二（明天）下午 6-8 节，教室是 1202。"},
                {"kind": "follow", "label": "补充", "time": "11-02 07:08", "from": "68同学L", "text": "课表一律以今日校园为准。"},
            ],
        },
        {
            "id": "g_taiji_test", "cat": "班级事务", "title": "太极拳：10/31 周六体测补测",
            "summary": "10 月 31 日（周六）10:40 篮球场集合，测试仰卧起坐、引体向上；10/30 补充为正式上课，缺席需向辅导员请假。",
            "group": "26级周一89节太极拳", "source": "QQ 群 · 26级周一89节太极拳",
            "deadline": "2026-10-31T10:40:00+08:00",
            "aiNote": "AI 判断：10/31 周六补测是单独课次，与 11/02 周一体育课不同；已拆分，课表参照：周一 8-9 节。",
            "items": [
                {"kind": "text", "label": "原始通知", "time": "10-30 11:33", "from": "甘子怡",
                 "text": "本周六（明天）上午 10 点 40 分，各位同学至篮球场集合准备测试仰卧起坐、引体向上，收到请回复。"},
                {"kind": "follow", "label": "补充", "time": "10-30 18:14", "from": "甘子怡", "text": "我们过来补测；都要来，是正式上课，没来的可以找辅导员请假。"},
            ],
        },
        {
            "id": "g_taiji_class", "cat": "班级事务", "title": "太极拳：11/02 周一课场地湿滑改观看",
            "summary": "11 月 2 日（周一）8-9 节，因场地湿滑改为观看太极拳学习；与 10/31 的体测补测不是同一次课。",
            "group": "26级周一89节太极拳", "source": "QQ 群 · 26级周一89节太极拳",
            "deadline": "2026-11-02T16:00:00+08:00",
            "aiNote": "AI 参照课表：周一 8-9 节是另一节体育课；11/02 场地调整单独成条，不再并入 10/31 补测通知。",
            "scheduleRef": "课表：周一 8-9 节",
            "items": [
                {"kind": "text", "label": "课次通知", "time": "11-02 15:48", "from": "甘子怡",
                 "text": "今天因场地湿滑，请各位同学观看太极拳学习。"},
            ],
        },
        {
            "id": "g_course_select", "cat": "教务", "title": "选课开始：教务系统入口",
            "summary": "10 月 28 日下午一点开始选课，请提前登录教务系统查看；课表以今日校园为准。",
            "group": "2026级信息管理与信息系统", "source": "QQ 群 · 2026级信管群",
            "deadline": "2026-10-28T13:00:00+08:00",
            "items": [
                {"kind": "text", "label": "原始通知", "time": "10-28 08:00", "from": "68同学L",
                 "text": "这个是我们学校的教务系统，大家可以先登上去看看，下午一点开始选课哦。"},
                {"kind": "link", "label": "教务系统", "time": "10-28 08:00", "from": "68同学L",
                 "name": "福建中医药大学教务系统", "url": "https://e.fjtcm.edu.cn/default/index.html"},
                {"kind": "follow", "label": "补充", "time": "11-02 07:08", "from": "68同学L", "text": "课表一律以今日校园为准。"},
            ],
        },
        {
            "id": "g_elective", "cat": "教务", "title": "网络公选课：学习通课程已导入",
            "summary": "已报名超星平台课程的同学可在学习通开始学习；不知道在哪个平台的同学查看教务处通知附件 1。",
            "group": "2026级信息管理与信息系统", "source": "QQ 群 · 2026级信管群",
            "deadline": None,
            "items": [
                {"kind": "text", "label": "原始通知", "time": "11-03 16:02", "from": "68同学L",
                 "text": "@全体成员 网络公选课：本学期报名超星平台课程的同学注意，你们报名的课程已经导入学习通，打开学习通后可看到该门课，可以开始学习了，注意学习时间和考试时间，不要错过了。不清楚所选课程在哪个平台的同学可以打开教务处通知，点击下载附件 1。报名慕课平台课程的同学请务必扫码进慕课堂。本学期没报名或错过报名的同学，可以在本学期末报名线下公选课，或下学期初报名网络公选课。"},
                {"kind": "link", "label": "教务处通知", "time": "11-03 16:02", "from": "68同学L",
                 "name": "关于网络公选课学习的通知（教务处）", "url": "https://jwc.fjtcm.edu.cn/2026/1027/c953a117024/page.htm"},
            ],
        },
        {
            "id": "g_invoice", "cat": "缴费", "title": "学杂费电子发票下载（电子票夹）",
            "summary": "需要学杂费电子发票的同学，按操作手册通过「电子票夹」小程序下载。",
            "group": "2026级信息管理与信息系统", "source": "QQ 群 · 2026级信管群",
            "deadline": None,
            "items": [
                {"kind": "text", "label": "原始通知", "time": "10-28 09:10", "from": "64同学A",
                 "text": "需要学杂费电子发票的同学，请按照操作手册方法，通过「电子票夹」小程序下载学杂费电子发票。"},
                {"kind": "article", "label": "操作手册", "time": "10-28 09:10", "from": "64同学A",
                 "account": "福建中医药大学财务处", "title": "学杂费电子发票获取操作指引", "url": "https://mp.weixin.qq.com/s/JcUFkuV7L3HWR9p-yHVc_Q"},
            ],
        },
        {
            "id": "g_dorm", "cat": "班级事务", "title": "宿舍卫生检查：每月前三周周三 17:30",
            "summary": "自本周（11.4）起，每月前三周的周三下午 5:30 例行检查；重点为卫生、收纳与用电安全。",
            "group": "2026级信息管理与信息系统聊天群", "source": "QQ 群 · 2026级信管聊天群",
            "deadline": None,
            "items": [
                {"kind": "text", "label": "原始通知", "time": "11-03 09:13", "from": "16同学H",
                 "text": "关于宿舍卫生检查的通知：为营造安全、整洁的宿舍环境，量化文明宿舍评比，自本周（11.4）起，每月前三周的周三下午 5:30，权益部将组织部员对宿舍进行例行检查。请提前留意：地面干净、垃圾及时清理；桌面及个人物品收纳整齐；卫生间无异味污垢，阳台不堆放杂物；严禁私拉乱接电线及电线绕床，严禁使用大功率及违规电器。请大家相互转告，提前行动。"},
                {"kind": "img", "label": "检查标准", "time": "11-03 09:13", "from": "16同学H", "src": posters["dorm"], "caption": "宿舍卫生检查标准（示例图）"},
            ],
        },
        {
            "id": "g_essay", "cat": "活动", "title": "“岐黄薪火·我的杏林故事”征文（截止 11/15）",
            "summary": "校工会、校妇联主题征文，诗歌/散文/读后感，800–1000 字；投稿至邮箱，截止 2026 年 11 月 15 日。",
            "group": "2026级信息管理与信息系统", "source": "QQ 群 · 2026级信管群",
            "deadline": "2026-11-15T23:59:00+08:00",
            "items": [
                {"kind": "text", "label": "原始通知", "time": "10-29 12:17", "from": "64同学A",
                 "text": "关于开展“岐黄薪火·我的杏林故事”征文的通知：为庆祝建校 68 周年，校工会、校妇女联合会开展校庆主题征文活动。征文对象：全体教职工、在校女学生。体裁与字数：诗歌、散文、读后感或观后感，800–1000 字为宜，诗歌不超过 30 行；须为原创首发，仅接收 Word 文档（.doc 或 .docx）。活动截止时间：2026 年 11 月 15 日。投稿方式：作品电子版发送至邮箱 2006002@fjtcm.edu.cn。"},
                {"kind": "follow", "label": "投稿要求", "time": "10-29 12:17", "from": "通知原文",
                 "text": "文件格式仅接收 Word；作品结尾注明作者姓名、年级/院系/学号、联系方式并附个人照片。"},
            ],
        },
    ]
    return groups


# ---------------------------------------------------------------- page

CSS = r"""
:root{--bg:#F7F8F8;--card:#fff;--line:#E6E9E8;--ink:#23302E;--ink2:#5A6A67;--ink3:#8C9A97;--cy:#4E9082;--bl:#6E8CA8;--sd:#B98F63;--danger:#C0605A;--mint:#E9F3F0;--mint2:#F1F7F5;--tint-blue:#EDF2F7;--tint-sand:#FBF4EA;--tint-rose:#F9EEEC;--tint-violet:#F2EFF8;--r:16px}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Source Han Sans SC",sans-serif;font-size:15px;line-height:1.7;letter-spacing:.01em;-webkit-font-smoothing:antialiased;padding-bottom:40px}
.wrap{max-width:880px;margin:0 auto;padding:0 14px}
@media(min-width:960px){.wrap{max-width:1120px;padding:0 20px}}
@media(min-width:1280px){.wrap{max-width:1320px}}
@media(min-width:1520px){.wrap{max-width:1520px}}
h1,h2,h3,h4{margin:0;font-weight:700}
button{font-family:inherit}
.brand{display:flex;align-items:center;gap:9px;padding:18px 0 12px}
.brand .dots{display:flex;gap:6px}.brand .dots i{width:8px;height:8px;border-radius:50%}
.brand .dots i:nth-child(1){background:var(--cy)}.brand .dots i:nth-child(2){background:var(--bl)}.brand .dots i:nth-child(3){background:var(--sd)}
.brand b{font-size:15.5px}.brand .sub{font-size:11.5px;color:var(--ink3);letter-spacing:.06em}
.brand .right{margin-left:auto;display:flex;align-items:center;gap:6px}
.demoTag{font-size:11px;color:#8A6A44;background:#FBF4EA;border:1px solid #EFE2CE;border-radius:999px;padding:2px 8px;letter-spacing:.04em}
.tabs{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;background:#EDF0EF;border-radius:12px;padding:5px;margin-bottom:14px;position:sticky;top:0;z-index:20;overflow:hidden}
.tabs-thumb{position:absolute;left:0;top:0;border-radius:9px;background:#fff;box-shadow:0 1px 3px rgba(35,48,46,.10);pointer-events:none;z-index:0;transition:transform .3s cubic-bezier(.18,1.2,.35,1),width .3s ease}
.tabs button{border:0;background:transparent;padding:9px 4px;border-radius:9px;font-size:14px;font-weight:600;color:var(--ink2);cursor:pointer;position:relative;z-index:1}
.tabs button.on{background:transparent;color:var(--cy);box-shadow:none}
section{display:none}section.on{display:block;animation:fade .16s ease}@keyframes fade{from{opacity:0}to{opacity:1}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px;margin-bottom:12px;box-shadow:0 1px 2px rgba(35,48,46,.03)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 15px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--ink);font-weight:600;cursor:pointer;font-size:14px;min-height:40px}
.btn:hover{background:#F2F5F4}.btn.pri{background:var(--cy);border-color:var(--cy);color:#fff}.btn.ghost{background:transparent}
.btn.sm{padding:6px 11px;font-size:12.5px;border-radius:8px;min-height:32px}
.brief{background:linear-gradient(135deg,#FBFDFC 0%,#F4FAF8 55%,#FDFAF5 100%);border-color:#DCEAE5}
.brief-hd{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.eyebrow{font-size:11.5px;font-weight:700;letter-spacing:.12em;color:var(--cy)}
.brief-hd .date{font-size:11.5px;color:var(--ink3)}
.chip{display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:700;padding:2px 9px;border-radius:999px;white-space:nowrap}
.chip.ok{background:var(--mint);color:#35705F}.chip.pending{background:#F0F2F1;color:#87938F}
.chip.blue{background:var(--tint-blue);color:#4E6D8C}.chip.warn{background:#FBF1E4;color:#9A7436}
.chip.rose{background:var(--tint-rose);color:#A55B50}.chip.violet{background:var(--tint-violet);color:#66579A}
.brief-hd .chip{margin-left:auto}
.brief-top{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin:8px 0 9px}
.bstat{display:block;min-width:0;text-align:left;background:#fff;border:1px solid #E4ECE9;border-radius:10px;padding:8px 9px;cursor:pointer;font:inherit}
.bstat b{display:block;font-size:20px;line-height:1.15;color:var(--cy);font-variant-numeric:tabular-nums}
.bstat span{display:block;margin-top:2px;font-size:10.5px;line-height:1.25;color:var(--ink3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bstat.urgent b{color:#A55B50}.bstat.alert b{color:#A55B50}.bstat.hw b{color:#4E6D8C}
.bstat:hover{background:#FAFCFB}
.brief-next{display:flex;flex-direction:column}
.bn-row{display:flex;align-items:baseline;gap:8px;width:100%;padding:7px 1px;border:0;border-top:1px solid #E8EFEC;background:transparent;text-align:left;font:inherit;cursor:pointer;color:var(--ink)}
.bn-row:first-child{border-top:0}
.bn-title{flex:1;min-width:0;font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bn-meta{flex:none;font-size:10.5px;color:var(--ink3);white-space:nowrap}
.bn-row.alert .bn-meta{color:#A55B50;font-weight:700}
.bn-empty{padding:4px 1px 2px;font-size:12px;color:var(--ink3)}
.brief-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
@media(max-width:560px){.brief-top{grid-template-columns:repeat(4,minmax(0,1fr));gap:5px}.bstat{padding:7px 6px}.bstat b{font-size:17px}.bstat span{font-size:9.5px}}
.filters{margin:14px 0 4px}
.chiprow{display:flex;gap:6px;overflow-x:auto;padding:1px 2px 3px;scrollbar-width:none}
/* 动态分类（AI 按近期通知增删）：分类 chips 允许换行，避免隐藏横向滚动条时看不到新分类 */
#catRow{flex-wrap:wrap;overflow-x:visible}
.chiprow::-webkit-scrollbar{display:none}
.chipf{flex:none;border:1px solid var(--line);background:#fff;color:var(--ink2);border-radius:999px;padding:5px 12px;font-size:12.5px;font-weight:600;cursor:pointer;min-height:32px}
.chipf.on{background:var(--cy);border-color:var(--cy);color:#fff}
.chiprow.sub{margin-top:7px}
.chiprow.sub .chipf{font-size:12px;padding:4px 10px;min-height:28px;color:var(--ink3);border-color:#E9EDEB}
.chiprow.sub .chipf.on{color:var(--cy);background:var(--mint2);border-color:#BFDCD3}
.listhint{display:flex;align-items:center;gap:10px;font-size:11.5px;color:var(--ink3);margin:14px 2px 8px;flex-wrap:wrap}
.listhint b{font-size:12px;color:var(--ink2)}.listhint .right{margin-left:auto;display:flex;gap:8px}
.linkbtn{border:0;background:transparent;color:var(--ink3);font-size:11.5px;font-weight:600;cursor:pointer;padding:2px 4px;border-bottom:1px dotted #CFD9D6}
.linkbtn:hover{color:var(--cy);border-color:var(--cy)}
.gcard{background:#fff;border:1px solid var(--line);border-radius:var(--r);margin-bottom:12px;box-shadow:0 1px 2px rgba(35,48,46,.03);overflow:hidden;position:relative}
#list.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;align-items:start}
#list.two .listcol{display:flex;flex-direction:column;gap:12px;min-width:0}
#list.two .gcard{margin-bottom:0}
#list.two>.card{grid-column:1/-1}
.gcard::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--cy)}
.gcard.cat-jw::before{background:#4E78A8}.gcard.cat-tw::before{background:var(--cy)}.gcard.cat-ks::before{background:#C79A5A}
.gcard.cat-jf::before{background:#B96A5F}.gcard.cat-hd::before{background:#7C6BB0}.gcard.cat-qt::before{background:#8C9A97}
.gcard.expired{opacity:.72}
.gcard.completed .gtitle{text-decoration:line-through;text-decoration-thickness:1px;color:#8C9A97}
.gcard.completed .gsum{opacity:.62}
.expired-wrap{margin:16px 0 4px;border:1px solid var(--line);border-radius:14px;background:#FAFBFB;overflow:hidden}
.expired-hd{display:flex;align-items:center;gap:8px;width:100%;padding:11px 14px;border:0;background:transparent;color:var(--ink3);font:inherit;font-size:12px;cursor:pointer;text-align:left}
.expired-hd b{color:var(--ink2);font-size:12px}.expired-hd .chev{margin-left:auto;transition:transform .15s ease}
.expired-wrap.open .expired-hd .chev{transform:rotate(180deg)}
.expired-list{display:none;padding:0 10px 10px}
.expired-wrap.open .expired-list{display:block}
/* 2026-11-12 长期通知：主列表下方独立折叠区（默认收起），防止长期安排/无时间通知长期霸占前排 */
.lt-wrap{margin:16px 0 4px;border:1px solid var(--line);border-radius:14px;background:#F8FAFB;overflow:hidden}
.lt-hd{display:flex;align-items:center;gap:8px;width:100%;padding:11px 14px;border:0;background:transparent;color:var(--ink3);font:inherit;font-size:12px;cursor:pointer;text-align:left}
.lt-hd b{color:var(--ink2);font-size:12px}.lt-hd .chev{margin-left:auto;transition:transform .15s ease}
.lt-wrap.open .lt-hd .chev{transform:rotate(180deg)}
.lt-list{display:none;padding:0 10px 10px}
.lt-wrap.open .lt-list{display:block}
.aibrief{background:#F7FBF9;border:1px solid #E0ECE7;border-radius:10px;padding:8px 10px;margin:8px 0 2px}
.aibrief-hd{display:flex;align-items:center;gap:5px;margin-bottom:3px;font-size:10px;font-weight:700;color:#4E7A6E;letter-spacing:.06em}
.ai-mini{display:flex;align-items:center;gap:5px;margin:7px 0 3px;font-size:10px;font-weight:700;color:#4E7A6E;letter-spacing:.06em}
.aibrief-sum{font-size:12.5px;line-height:1.6;color:#31413D}
.aipoints{display:flex;flex-wrap:wrap;gap:4px 6px;margin:5px 0 0;padding:0;list-style:none}
.aipoints li{font-size:10.5px;color:#4E6D8C;background:#EEF4F8;border:1px solid #DDE9F1;border-radius:999px;padding:1px 7px;line-height:1.5}
.quote.clamp{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.quote.clamp.open{display:block}
.mergedcard{margin:6px 0;border:1px solid #E2EBE7;border-radius:10px;background:#FBFCFC;overflow:hidden}
.mergedcard summary{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer;font-size:12px;color:var(--ink2);list-style:none}
.mergedcard summary::-webkit-details-marker{display:none}
.mergedcard summary:before{content:"▸";color:var(--cy);font-size:11px}
.mergedcard[open] summary:before{content:"▾"}
.mergedcard .mtitle{font-weight:600}
.mergedcard .mcount{margin-left:auto;font-size:10.5px;color:var(--ink3)}
.merged-list{border-top:1px solid #E8F0EC;padding:2px 10px 8px 22px}
.mrow{padding:6px 0;border-top:1px dashed #E8EFEC}
.mrow:first-child{border-top:0}
.mhd{display:flex;gap:8px;font-size:10.5px;color:var(--ink3)}
.mname{font-weight:600;color:#4E7A6E}.mtime{margin-left:auto}
.mtext{font-size:12px;line-height:1.65;color:var(--ink);margin-top:2px;white-space:pre-wrap}
.gcard.flash{outline:2px solid var(--cy);outline-offset:2px}
.ghd{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:13px 15px 0 17px}
.badge{font-size:10.5px;font-weight:700;padding:1px 8px;border-radius:6px}
.badge.jw{background:var(--tint-blue);color:#4E6D8C}.badge.tw{background:var(--mint);color:#35705F}
.badge.ks{background:#FBF1E4;color:#9A7436}.badge.jf{background:var(--tint-rose);color:#A55B50}
.badge.hd{background:var(--tint-violet);color:#66579A}.badge.qt{background:#F0F2F1;color:#77847F}
.grp{font-size:10.5px;font-weight:700;color:#3F7A6C;background:var(--mint2);border:1px solid #D9EAE4;border-radius:6px;padding:0 7px}
.ghd .st{margin-left:auto;font-size:11.5px;font-weight:700;border-radius:6px;padding:2px 8px;white-space:nowrap}
.st.active{color:#9A7436;background:#FBF6EC}
.st.urgent{color:#A55B50;background:#FBF0EE}
.st.expired{color:#35705F;background:var(--mint)}
.st.extended{color:#4E6D8C;background:var(--tint-blue)}
.st.none{color:#87938F;background:#F5F7F6}
.st.alert{color:#A55B50;background:var(--tint-rose);border:1px solid #F0D3CC}
.alertbar{margin:8px 15px 0 17px;background:#FDF1EE;border:1px solid #F0D3CC;color:#9A4A42;border-radius:10px;padding:8px 10px;font-size:12px;line-height:1.62}
.lateTag{display:inline-flex;align-items:center;font-size:9.5px;font-weight:700;color:#A55B50;background:#FBF0EE;border:1px solid #EFD6D1;border-radius:5px;padding:0 5px;margin-left:5px;white-space:nowrap}
.gcard.attention{box-shadow:0 0 0 1px #F0D3CC,0 2px 10px rgba(160,80,70,.06)}
.lateimg{border-color:#EFD6D1!important;background:#FDF9F8}
.gtitle{padding:7px 15px 0 17px;font-size:15.5px;line-height:1.5;font-weight:700}
.gsum{padding:4px 15px 0 17px;margin:0;font-size:13px;line-height:1.65;color:var(--ink2)}
.extnote{margin:6px 15px 0 17px;font-size:11px;line-height:1.5;color:#4E6D8C;background:var(--tint-blue);border:1px solid #DCE6F1;border-radius:8px;padding:4px 9px}
.ainote{margin:6px 15px 0 17px;font-size:11px;line-height:1.55;color:#5A6A67;background:#F6F9F8;border:1px dashed #D5E2DD;border-radius:8px;padding:5px 9px}
.aitag{display:inline-flex;align-items:center;justify-content:center;font-size:9px;font-weight:800;color:#fff;background:var(--cy);border-radius:4px;padding:1px 5px;margin-right:6px;letter-spacing:.03em}
.hwcard{background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:14px 15px;margin-bottom:10px;box-shadow:0 1px 2px rgba(35,48,46,.03);position:relative;overflow:hidden}
.hwcard::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--bl)}
.hwcard.done::before{background:#9AB5A8}
.hwcard.done{opacity:.7}
.hwh{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:4px}
.hwtitle{font-size:14.5px;font-weight:700;line-height:1.5}
.hwnote{margin:2px 0 8px;font-size:12.5px;color:var(--ink2);line-height:1.6}
.hwmeta{font-size:11px;color:var(--ink3);line-height:1.6}
.hwmeta b{color:var(--ink2);font-weight:600}
.hwac{display:flex;align-items:center;gap:8px;margin-top:8px;flex-wrap:wrap}
.hwlink{display:inline-flex;align-items:center;gap:5px;border:1px solid #BFDCD3;background:var(--mint2);color:#35705F;border-radius:8px;padding:5px 10px;font-size:11.5px;font-weight:700;text-decoration:none;min-height:30px}
.hwlink:hover{background:#E4F1EC}
.hwempty{text-align:center;color:var(--ink3);font-size:12.5px;padding:24px 10px;line-height:1.8}
.ttbl{width:100%;border-collapse:separate;border-spacing:0;font-size:12.5px;margin-top:8px}
.ttbl th{font-size:11px;color:var(--ink3);font-weight:600;text-align:left;padding:8px 10px;border-bottom:1px solid #EEF2F0;background:#FAFCFB}
.ttbl td{padding:10px;border-bottom:1px solid #F1F4F3;vertical-align:top;line-height:1.55}
.ttbl td:first-child{color:var(--ink3);font-weight:600;white-space:nowrap}
.ttbl .tc{font-weight:700;color:var(--ink)}
.ttbl .tn{display:block;font-size:10.5px;color:var(--ink3);font-weight:400;margin-top:1px}
.ttnote{margin-top:10px;font-size:11px;color:var(--ink3);line-height:1.7}
.gcompose{display:flex;gap:6px;flex-wrap:wrap;padding:8px 15px 0 17px}
.cchip{font-size:10.5px;color:var(--ink2);background:#F7F9F8;border:1px solid #EAEFED;border-radius:999px;padding:1px 8px;white-space:nowrap}
.cchip b{color:var(--cy);font-weight:700}
.gtimeline{padding:10px 15px 2px 17px}
.gitem{position:relative;padding:0 0 10px 24px}
.gitem::before{content:"";position:absolute;left:5px;top:7px;width:7px;height:7px;border-radius:50%;background:#CFDDD8;border:2px solid #fff;box-shadow:0 0 0 1px #DCE7E3}
.gitem .gline{position:absolute;left:8px;top:16px;bottom:0;width:1px;background:#E8EFEC}
.gitem:last-child .gline{display:none}
.gi-hd{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:10.5px;color:var(--ink3);line-height:1.4}
.gi-kind{font-weight:700;border-radius:5px;padding:0 6px;font-size:10px;background:var(--tint-blue);color:#4E6D8C}
.gi-kind.file{color:#7A5A32;background:#FBF4EA}.gi-kind.img{color:#35705F;background:var(--mint)}
.gi-kind.form{color:#4E6D8C;background:var(--tint-blue)}.gi-kind.link{color:#3F7A6C;background:var(--mint2)}
.gi-kind.article{color:#3F7A6C;background:var(--mint2)}.gi-kind.follow{color:#9A7436;background:#FBF6EC}
.gi-time{margin-left:auto;color:#A6B2AE}
.gi-body{margin-top:3px;font-size:13px;line-height:1.65;color:#33433F}
.quote{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;color:var(--ink2)}
.gi-body.open .quote{-webkit-line-clamp:unset}
.gi-more{font-size:11px;color:var(--cy);font-weight:600;cursor:pointer;margin-top:2px;display:inline-block}
.attach{display:flex;align-items:center;gap:9px;background:#FCFBF9;border:1px solid #EEE6DA;border-radius:10px;padding:8px 10px;margin-top:2px;cursor:pointer}
.attach:hover{border-color:#E3D3BC}
.attach .ico{flex:none;width:30px;height:30px;border-radius:8px;background:#E6F3EA;color:#2F7A4E;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800}
.attach .nm{flex:1;min-width:0;font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.attach .meta{flex:none;font-size:10.5px;color:var(--ink3)}
.attach .go,.go{flex:none;border:1px solid var(--line);background:#fff;border-radius:7px;padding:4px 9px;font-size:11px;font-weight:700;color:var(--ink2);cursor:pointer;min-height:28px;text-decoration:none;display:inline-flex;align-items:center}
.attach .go:hover,.go:hover{border-color:var(--cy);color:var(--cy)}
.formrow{display:flex;align-items:center;gap:9px;background:#FAFCFD;border:1px solid #E0E9F0;border-radius:10px;padding:8px 10px;margin-top:2px}
.formrow .ico{flex:none;width:30px;height:30px;border-radius:8px;background:linear-gradient(145deg,#4A78A8,#6E8CA8);color:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800}
.formrow .fb{flex:1;min-width:0}
.formrow .ft{font-size:12.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.formrow .fm{font-size:10.5px;color:var(--ink3);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.formrow .fs{flex:none;font-size:10px;font-weight:700;border-radius:5px;padding:1px 6px;background:#F0F2F1;color:#87938F}
.formrow .fs.open{background:var(--mint);color:#35705F}.formrow .fs.closed{background:var(--tint-rose);color:#A55B50}
.imgrow{display:flex;gap:10px;align-items:flex-start;background:#FBFCFC;border:1px solid #E5EBE9;border-radius:10px;padding:7px;margin-top:2px;cursor:pointer}
.imgrow:hover{border-color:#CFE0DA}
.imgrow img{width:100%;max-width:260px;height:auto;max-height:360px;object-fit:contain;border-radius:7px;border:1px solid #E3ECE8;background:#E7EFEC}
.imgrow .ib{flex:1;min-width:0}
.imgrow .it{font-size:12px;font-weight:600;color:var(--ink2)}
.imgrow .ic{font-size:10.5px;color:var(--ink3);margin-top:1px}
.linkrow{display:flex;align-items:center;gap:9px;background:#FBFCFC;border:1px solid #E5EBE9;border-radius:10px;padding:8px 10px;margin-top:2px}
.linkrow .ico{flex:none;width:30px;height:30px;border-radius:8px;background:var(--mint);color:#35705F;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800}
.linkrow .lb{flex:1;min-width:0}
.linkrow .lt{font-size:12.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.linkrow .lu{font-size:10px;color:var(--ink3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}
.artrow{display:flex;gap:10px;background:#FCFDFC;border:1px solid var(--line);border-radius:10px;padding:8px;margin-top:2px}
.artrow .cover{flex:none;width:58px;border-radius:7px;background:linear-gradient(150deg,#4E9082,#6E8CA8);display:flex;align-items:flex-end;padding:6px}
.artrow .cover span{font-size:9px;color:rgba(255,255,255,.92)}
.artrow .ab{flex:1;min-width:0}
.artrow .acc{font-size:10px;color:var(--cy);font-weight:700}
.artrow .att{font-size:12.5px;font-weight:700;line-height:1.4;margin-top:1px}
.artrow .am{font-size:10px;color:var(--ink3);margin-top:1px}
.followrow{background:#FBF9F5;border:1px solid #EEE5D8;border-radius:10px;padding:8px 10px;margin-top:2px;font-size:12.5px;color:#4E463B;line-height:1.6}
.followrow .fh{font-size:10px;font-weight:700;color:var(--sd);letter-spacing:.03em;margin-bottom:2px}
.gft{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:8px 15px 12px 17px;border-top:1px solid #F0F3F2;margin-top:6px}
.srcline{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.srcmore{display:inline-flex;align-items:center;font-size:10px;font-weight:700;color:#4E6D8C;background:var(--tint-blue);border:1px solid #DCE6EE;border-radius:999px;padding:2px 8px;white-space:nowrap}
.srcchip{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--ink2);background:#fff;border:1px solid #E8EEEC;border-radius:999px;padding:2px 9px 2px 3px;font-weight:600;box-shadow:0 1px 2px rgba(30,60,50,.03)}
.srcchip .ic{width:18px;height:18px;border-radius:6px;display:flex;align-items:center;justify-content:center;flex:none;background:#5B8EC9}
.srcchip .ic svg{width:13px;height:13px;display:block}
.srcchip.qq .ic{background:linear-gradient(135deg,#1EC0FF,#0B8FEA)}
.srcchip.wx .ic{background:linear-gradient(135deg,#2BD27A,#06A94D)}
.srcchip.doc .ic{background:linear-gradient(135deg,#7899B8,#54728F)}
.srcchip .st{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:52vw}
.publine{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:6px 22px 0}
.pubbadge{display:inline-flex;align-items:center;font-size:10px;line-height:1;padding:3px 7px;border-radius:999px;background:#EAF4EF;color:#3F7C6E;border:1px solid #CFE4DA;font-weight:700;letter-spacing:.02em}
.pubname{font-size:12px;font-weight:700;color:var(--ink)}
.pubrole{font-size:11px;color:var(--ink3)}
.gi-badge{display:inline-flex;align-items:center;font-size:9.5px;line-height:1;padding:2px 6px;border-radius:999px;background:#EAF4EF;color:#3F7C6E;border:1px solid #CFE4DA;font-weight:700;margin-right:4px}
.gi-from{display:inline-flex;align-items:center;gap:2px;font-size:11px;color:var(--ink2)}
.badge.ocr{background:#EEF2F7;color:#4E78A8;border:1px solid #D8E1EC;font-size:10px;padding:1px 6px}
.gft .grow{flex:1}
.donebtn{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;color:var(--ink3);background:transparent;border:1px solid transparent;border-radius:8px;padding:5px 8px;cursor:pointer;min-height:30px}
.donebtn:hover{color:var(--cy);background:var(--mint2)}
.donebtn .b{width:14px;height:14px;border:1.5px solid #C3D2CE;border-radius:4px;position:relative;flex:none;background:#fff}
.donebtn.done{color:var(--cy)}
.donebtn.done .b{background:var(--cy);border-color:var(--cy)}
.donebtn.done .b::after{content:"";position:absolute;left:3.6px;top:.5px;width:4px;height:8px;border:solid #fff;border-width:0 1.7px 1.7px 0;transform:rotate(42deg)}
.demoact{border:1px dashed #C9B48F;background:#FFFDF9;color:#8A6A44;font-size:10.5px;font-weight:700;border-radius:7px;padding:4px 9px;cursor:pointer;min-height:28px}
.demoact:hover{background:#FBF4EA}
.ph{padding:30px 18px;text-align:center}
.ph .ic{width:46px;height:46px;margin:0 auto 10px;border-radius:14px;background:var(--mint2);display:flex;align-items:center;justify-content:center;color:var(--cy);font-size:20px;font-weight:800}
.ph h3{font-size:15px;margin-bottom:6px}.ph p{margin:0;font-size:12.5px;color:var(--ink3);line-height:1.7}
.foot{margin-top:22px;text-align:center;font-size:11px;color:#A6B2AE;line-height:1.8}
.foot b{color:#8C9A97;font-weight:600}
.toast{position:fixed;left:50%;bottom:34px;transform:translate(-50%,14px);background:rgba(35,48,46,.94);color:#fff;font-size:12.5px;padding:9px 15px;border-radius:999px;opacity:0;pointer-events:none;transition:.22s;z-index:80;max-width:88vw;text-align:center}
.toast.on{opacity:1;transform:translate(-50%,0)}
.modal{position:fixed;inset:0;z-index:70;background:rgba(35,48,46,.55);display:none;align-items:center;justify-content:center;padding:20px 14px}
.modal.on{display:flex}
.mcard{position:relative;width:100%;max-width:720px;max-height:88vh;overflow:auto;background:#fff;border-radius:16px;padding:14px}
.mcard img{width:100%;border-radius:10px;display:block}
.mcard iframe{width:100%;height:68vh;border:0;border-radius:10px;background:#F7F8F8}
.mcard .mhead{font-size:13px;font-weight:700;color:var(--ink);padding:2px 40px 10px 2px;line-height:1.5}
.mcard .mact{display:flex;justify-content:flex-end;gap:8px;margin-top:10px}
.mcard .mact .go{display:inline-flex;align-items:center;padding:6px 12px;border-radius:999px;background:var(--mint2);color:var(--cy);font-size:12px;font-weight:600;text-decoration:none}
.mclose{position:absolute;top:6px;right:6px;width:36px;height:36px;border:0;border-radius:50%;background:rgba(255,255,255,.9);color:#5A6A67;font-size:19px;cursor:pointer}
@media(max-width:560px){.wrap{padding:0 10px}.gtitle{font-size:15px}.ghd .st{margin-left:0}.brief-actions .btn{flex:1}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}

/* —— Monet skin: soft water-lily palette + breathing room —— */
:root{
  --bg:#F4F0E6;--card:#FFFCF6;--line:#E7DED0;
  --ink:#303A35;--ink2:#5C6860;--ink3:#8B948B;
  --cy:#5E8F87;--bl:#7D9EBB;--sd:#C6A475;--danger:#B87870;
  --mint:#EAF2EC;--mint2:#F3F7F1;
  --tint-blue:#EDF2F7;--tint-sand:#FAF3E6;--tint-rose:#F7EDEB;--tint-violet:#F1EEF7;
  --r:20px;
}
html{background:#F4F0E6}
body{
  background:
    radial-gradient(1100px 620px at 8% -8%,rgba(155,190,184,.28),transparent 62%),
    radial-gradient(900px 560px at 102% 2%,rgba(174,160,199,.20),transparent 58%),
    radial-gradient(760px 520px at 46% 108%,rgba(218,184,164,.20),transparent 62%),
    linear-gradient(180deg,#F8F3E8 0%,#F2F1E7 46%,#EDF2EC 100%);
  background-attachment:fixed;
  padding-bottom:64px;
}
.wrap{max-width:1180px;padding:22px 22px 84px}
@media(min-width:960px){.wrap{max-width:1260px;padding:28px 30px 96px}}
@media(min-width:1280px){.wrap{max-width:1390px}}
@media(min-width:1520px){.wrap{max-width:1510px}}
.brand{padding:8px 0 20px;gap:11px}
.brand b{font-size:16px;letter-spacing:.02em}
.brand .sub{font-size:11.5px;letter-spacing:.08em;color:#8D948A}
.brand .dots i{width:9px;height:9px}
.card{border-radius:22px;padding:22px;margin-bottom:20px;border-color:#E8DFD1;box-shadow:0 12px 34px rgba(72,74,58,.055)}
.brief{padding:22px 24px;border-radius:22px;border-color:#E6D9C7;background:linear-gradient(135deg,#FBF6EA 0%,#F1F6EF 52%,#F7EEF2 100%);box-shadow:0 14px 38px rgba(88,83,64,.07)}
.brief-hd{gap:10px;margin-bottom:10px}
.eyebrow{color:#578C82;letter-spacing:.14em}
.brief-top{gap:12px;margin:14px 0 14px}
.bstat{min-height:90px;padding:14px 14px;border-radius:14px;border-color:#E7DED0;display:flex;flex-direction:column;justify-content:center;box-shadow:0 3px 10px rgba(80,78,62,.035)}
.bstat:nth-child(1){background:#F5F0E4}.bstat:nth-child(2){background:#F6EEE9}
.bstat:nth-child(3){background:#EEF3EE}.bstat:nth-child(4){background:#F0F0F6}
.bstat b{font-size:27px;line-height:1.1;color:#4E7F76}
.bstat span{font-size:11.5px;margin-top:5px;color:#7E887E}
.bstat:hover{background:#FFFCF6;transform:translateY(-1px);transition:transform .18s ease,background .18s ease}
.brief-next .bn-row{padding:10px 2px;gap:12px}
.bn-title{font-size:12.5px}.bn-meta{font-size:10.5px}
.brief-actions{gap:10px;margin-top:14px}
.btn{border-radius:11px;padding:10px 16px}.btn.sm{padding:7px 12px}
.filters{margin:22px 0 10px}
.chiprow{gap:8px;padding:2px 2px 5px}
.chipf{min-height:36px;padding:7px 15px;border-radius:999px;font-size:12.5px;border-color:#E5DCCD;background:#FFFCF6}
.chipf.on{background:#5E8F87;border-color:#5E8F87;box-shadow:0 4px 12px rgba(94,143,135,.20)}
.chiprow.sub{margin-top:9px;gap:7px}
.chiprow.sub .chipf{min-height:32px;padding:5px 12px;border-color:#E9E0D2;background:#FBF8F0}
.chiprow.sub .chipf.on{background:#EAF2EC;color:#46776F;border-color:#CFE0D8}
.listhint{margin:20px 2px 12px;gap:12px}
#list.two{gap:20px}
#list.two .listcol{gap:20px}
.gcard{margin-bottom:20px;border-radius:22px;border-color:#E6DDD0;box-shadow:0 12px 34px rgba(72,74,58,.055)}
#list.two .gcard{margin-bottom:0}
.gcard::before{width:3px;background:#5E8F87}
.gcard.cat-jw::before{background:#7D9EBB}.gcard.cat-tw::before{background:#5E8F87}.gcard.cat-ks::before{background:#C6A475}
.gcard.cat-jf::before{background:#C18B83}.gcard.cat-hd::before{background:#A192B8}.gcard.cat-qt::before{background:#8E9A90}
.ghd{padding:18px 22px 0;gap:8px}
.badge{padding:2px 9px;border-radius:7px}
.ghd .st{padding:3px 9px}
.gtitle{padding:10px 22px 0;font-size:16.5px;line-height:1.55}
.srcline{padding:9px 22px 0;gap:8px}
.srcchip{font-size:11px;padding:2px 10px 2px 3px;border-color:#E8DED0;box-shadow:0 2px 5px rgba(80,74,58,.04)}
.aibrief{margin:13px 22px 5px;padding:12px 14px;border-radius:14px;border-color:#E2E9DD;background:linear-gradient(135deg,#F6F9F2,#F8F4ED)}
.aibrief-hd{font-size:10px;letter-spacing:.08em;margin-bottom:5px;gap:6px}
.aibrief-sum{font-size:12.5px;line-height:1.7;color:#3C4A41}
.aipoints{gap:5px 7px;margin-top:7px}
.aipoints li{font-size:10.5px;padding:2px 8px;line-height:1.55;border-color:#DEE7DB;background:#F4F8F2;color:#5A7867}
.gcompose{padding:11px 22px 0;gap:7px}
.cchip{padding:2px 9px;border-color:#E9DFD0;background:#FAF6ED;color:#6B756B}
.gtimeline{padding:13px 22px 4px}
.gitem{padding:0 0 14px 26px}
.gitem::before{left:5px;top:8px;width:8px;height:8px;background:#BFD3C9;box-shadow:0 0 0 3px #F6F2E8,0 0 0 4px #DCE6DF}
.gitem:last-child{padding-bottom:2px}
.gi-hd{gap:8px;font-size:10.5px;line-height:1.5}
.gi-time{margin-left:auto;color:#A0A89E}
.gi-body{margin-top:5px;font-size:13px;line-height:1.78;color:#3B4740}
.quote{line-height:1.78}
.gi-more{font-size:11px;margin-top:4px}
.gsum{padding:6px 22px 0;line-height:1.7}
.ainote,.extnote{margin-left:22px;margin-right:22px}
.linkrow,.formrow,.artrow,.attach,.followrow{margin-top:8px;padding:10px 12px;border-radius:13px;gap:10px;border-color:#E9DED0;background:#FBF7EE}
.linkrow .ico,.formrow .ico,.artrow .cover{border-radius:9px}
.linkrow .lt{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;line-height:1.45}
.linkrow .lb{flex:1 1 170px;min-width:0}
.linkrow .go,.formrow .go,.artrow .go{flex:none;margin-left:auto;border-radius:9px;padding:5px 11px;min-height:30px;border-color:#E1D6C6;background:#FFFCF6}
.linkrow .lu{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.linkrow .go.ghost{margin-left:0;background:transparent}
.imgrow{margin-top:10px;padding:10px;justify-content:center;border-radius:14px;border-color:#E8DED0;background:#F8F3E9}
.imgrow img{max-width:240px;max-height:320px;border-radius:12px;border-color:#E5D9C8;background:#EFE9DC}
.gft{padding:12px 22px 18px;margin-top:10px;gap:8px;border-top-color:#EEE5D7}
.donebtn{font-size:11.5px;padding:6px 9px;border-radius:9px}
.donebtn:hover{background:#EFF5EF}
.expired-wrap,.lt-wrap{border-radius:18px;border-color:#E6DDD0;background:#FAF7EF}
.expired-hd,.lt-hd{padding:13px 16px}
.expired-list,.lt-list{padding:0 12px 12px}
.foot{margin-top:30px;font-size:11px;color:#939B91}
.ph{padding:36px 18px}
.modal{background:rgba(47,58,52,.42);backdrop-filter:blur(3px)}
.mcard{background:#FFFCF6;border-radius:20px;padding:18px;box-shadow:0 24px 80px rgba(40,50,42,.20)}
.mcard .mhead{font-size:13.5px;padding-bottom:12px}
.mcard .mact{margin-top:12px}
@media(max-width:700px){
  html,body{overflow-x:hidden}
  .wrap{width:100%;min-width:0;padding:14px 14px 72px}
  .brief{padding:17px 16px;border-radius:20px;max-width:100%}
  .brief-top{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:12px 0}
  .bstat{min-height:76px;padding:10px 12px;border-radius:12px;min-width:0}
  .bstat b{font-size:22px}.bstat span{font-size:10px}
  .brief-hd .chip{margin-left:0}
  #list,.listcol,.gcard,.card{min-width:0;max-width:100%}
  .ghd{padding:16px 16px 0}.gtitle{padding:9px 16px 0;font-size:15.5px}
  .srcline{padding:8px 16px 0;min-width:0}
  .publine{padding:5px 16px 0}
  .srcchip{max-width:100%;min-width:0}
  .srcchip .st{max-width:calc(100vw - 108px);white-space:normal;line-height:1.35;overflow-wrap:anywhere}
  .aibrief{margin:12px 16px 4px;padding:11px 12px}
  .gtimeline{padding:12px 16px 4px}.gcompose{padding:10px 16px 0}
  .gft{padding:11px 16px 15px}.gsum{padding-left:16px;padding-right:16px}
  .ainote,.extnote{margin-left:16px;margin-right:16px}
  .gtitle,.gsum,.gi-body,.aibrief-sum,.linkrow .lt,.linkrow .lu{overflow-wrap:anywhere}
  .linkrow{flex-wrap:wrap;max-width:100%}
  .linkrow .lb{flex:1 1 100%}
  .linkrow .go{margin-left:0}
  .linkrow .lu{white-space:normal;line-height:1.45}
  .imgrow img{max-width:100%;max-height:280px}
}
.gitem{padding-left:0}
.gitem::before,.gitem .gline{display:none}
.gi-type{display:inline-flex;align-items:center;flex:none;font-size:10px;font-weight:700;letter-spacing:.03em;border-radius:999px;padding:2px 8px;line-height:1.35;background:#EDF3EE;color:#4B7A6C;border:1px solid #DCE8DF}
.gi-type.original{background:#EAF1F4;color:#4E7085;border-color:#DAE7ED}
.gi-type.supp{background:#F6F0E5;color:#8B6B38;border-color:#EADCC3}
.gi-type.file{background:#F4EDE4;color:#82613C;border-color:#E8D9C5}
.gi-type.img{background:#EEF2E7;color:#5B7B4E;border-color:#DFE8D3}
.gi-type.link{background:#EDF1F5;color:#4F6F86;border-color:#DCE6EE}
.gi-type.mini{background:#EDF3F0;color:#3C7566;border-color:#D8E8E1}
.gi-type.seg{background:#EEF3EC;color:#53765A;border-color:#DCE6D7}
.gi-type.time,.gi-type.due{background:#FBF2E5;color:#8A643B;border-color:#EFDFC5}
.gi-type.place{background:#EDF3F4;color:#4B7377;border-color:#D9E7E8}
.gi-type.who{background:#F3EFF6;color:#685C82;border-color:#E5DEEE}
.gi-type.join{background:#EDF4EE;color:#47734F;border-color:#DAE8DB}
.gi-type.rule{background:#F8EFED;color:#8B5A51;border-color:#EDDBD6}
.gi-type.contact{background:#F1F0F7;color:#5B5E81;border-color:#E3E1ED}
.quote{white-space:pre-wrap;overflow-wrap:anywhere}
.origbtn{flex:none;margin-left:4px;border:1px solid #E4D8C6;background:#FBF6EC;color:#7B684D;border-radius:999px;padding:4px 11px;font-size:10.5px;font-weight:700;cursor:pointer;min-height:28px}
.origbtn:hover{border-color:#CDB99A;background:#F7EEDC;color:#5E4E37}
.orig-meta{font-size:11px;color:var(--ink3);margin:0 0 10px}
.orig-item{padding:12px 0;border-top:1px solid #EEE4D5}
.orig-item:first-of-type{border-top:0;padding-top:4px}
.orig-head{display:flex;align-items:center;gap:7px;margin-bottom:7px}
.orig-body p{margin:0 0 8px;font-size:13px;line-height:1.8;color:#3C4740}
.orig-body p:last-child{margin-bottom:0}
.orig-empty{font-size:12.5px;color:var(--ink3);line-height:1.7}
.seg-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px 11px;padding:0 0 10px}
.seg-fact{display:flex;flex-direction:column;align-items:flex-start;gap:6px;background:#FAF6ED;border:1px solid #ECE2D3;border-radius:13px;padding:9px 11px;min-width:0}
.seg-fact .seg-txt{font-size:12px;line-height:1.65;color:#3D4A42;overflow-wrap:anywhere}
.seg-fact .gi-type{align-self:flex-start;font-size:9.5px;padding:1px 7px}
@media(max-width:700px){.seg-grid{grid-template-columns:1fr;padding:0 0 9px;gap:8px}.seg-fact{padding:8px 10px}}

/* ================= v2.0.0：长期安排 / 补充通知 / 文件待获取 / 管理员编辑 ================= */
/* 需求 9：长期安排（不按 deadline 判过期） */
.st.recur{color:#4E6D8C;background:var(--tint-blue)}
.badge.recur{background:var(--tint-blue);color:#4E6D8C}
.badge.upd{background:#FBF1E4;color:#9A7436;border:1px solid #EFE2CE}
.recurline{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:8px 22px 0;background:linear-gradient(135deg,#F3F7FA,#F8FAFC);border:1px solid #DCE6EE;border-radius:12px;padding:8px 11px;font-size:12px;color:#3F5E78;line-height:1.6}
.recurline .rl{font-weight:700}
.recurline .rn{margin-left:auto;white-space:nowrap;font-variant-numeric:tabular-nums;color:#4E6D8C;font-weight:700}
/* 需求 7：文件「待获取」 */
.linkrow.missing{background:#FBF7F0;border-color:#EADCC3;cursor:pointer}
.linkrow.missing:hover{border-color:#DDC9A8;background:#F9F2E4}
.linkrow.missing .ico{background:#F6EAD5;color:#8A643B}
.linkrow .missbadge{flex:none;font-size:10px;font-weight:700;color:#9A7436;background:#FBF1E4;border:1px solid #EFE2CE;border-radius:999px;padding:2px 8px;white-space:nowrap}
/* 微信图片附件未获取（V2 加密/未导出）：保留附件位并显示「待获取」 */
.imgrow.missing{justify-content:flex-start;align-items:center;gap:10px;background:#FBF7F0;border-color:#EADCC3;cursor:pointer;padding:10px 12px}
.imgrow.missing:hover{border-color:#DDC9A8;background:#F9F2E4}
.imgrow.missing .ib{flex:1;min-width:0}
.imgrow.missing .it{font-size:12.5px;font-weight:700;color:var(--ink2)}
.imgrow.missing .ic{font-size:10.5px;color:var(--ink3);margin-top:2px}
.imgrow .missbadge{flex:none;font-size:10px;font-weight:700;color:#9A7436;background:#FBF1E4;border:1px solid #EFE2CE;border-radius:999px;padding:2px 8px;white-space:nowrap}
/* 压缩包附件：包内文件清单 + 解压识别摘要 */
.okbadge{flex:none;font-size:10px;font-weight:700;color:#35705F;background:var(--mint);border:1px solid #CFE4DA;border-radius:999px;padding:2px 8px;white-space:nowrap}
.archivecard{margin:8px 0 2px;border:1px solid #E2EBE7;border-radius:12px;background:#FBFCFC;overflow:hidden}
.archivecard summary{display:flex;align-items:center;gap:8px;padding:9px 11px;cursor:pointer;font-size:12px;color:var(--ink2);list-style:none;flex-wrap:wrap}
.archivecard summary::-webkit-details-marker{display:none}
.archivecard summary:before{content:"▸";color:var(--cy);font-size:11px}
.archivecard[open] summary:before{content:"▾"}
.archivecard .arc-t{font-weight:700;color:var(--ink)}
.archivecard .arc-at{margin-left:auto;font-size:10.5px;color:var(--ink3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:55%}
.arch-sum{padding:0 12px 8px;font-size:12px;line-height:1.65;color:#3B4740}
.arch-points{display:flex;flex-wrap:wrap;gap:4px 6px;padding:0 12px 8px}
.arch-points .arc-p{font-size:10px;color:#4E6D8C;background:#EEF4F8;border:1px solid #DDE9F1;border-radius:999px;padding:1px 7px}
.arch-list{padding:2px 10px 9px}
.arc-row{display:flex;align-items:center;gap:8px;padding:6px 2px;border-top:1px dashed #E8EFEC;font-size:12px;min-width:0}
.arc-row:first-child{border-top:0}
.arc-kind{flex:none;font-size:9.5px;font-weight:700;color:#4E6D8C;background:var(--tint-blue);border-radius:5px;padding:1px 6px}
.arc-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink)}
.arc-size{flex:none;font-size:10.5px;color:var(--ink3)}
.arc-row .go.sm{flex:none;font-size:10.5px;padding:3px 8px;min-height:24px}
.missbox{font-size:13px;line-height:1.8;color:#3B4740}
.missgroup{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:12px 0 4px;padding:10px 12px;background:#FBF6EC;border:1px solid #EADCC3;border-radius:12px;font-size:12.5px;color:#6B5A3E}
.missgroup b{font-size:13px;color:#5E4E37}
.copybtn{border:1px solid #E1D6C6;background:#FFFCF6;color:#7B684D;border-radius:9px;padding:6px 12px;font-size:12px;font-weight:700;cursor:pointer;min-height:32px;font-family:inherit}
.copybtn:hover{border-color:var(--cy);color:var(--cy)}
/* 需求 12：管理员编辑 / 删除 / 已隐藏区 */
.ghd .gright{margin-left:auto;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.ghd .gright .st{margin-left:0}
.adminbar{display:flex;gap:5px}
.actbtn{border:1px solid #E1D6C6;background:#FFFCF6;color:#7B684D;border-radius:8px;padding:4px 9px;font-size:11px;font-weight:700;cursor:pointer;min-height:28px;font-family:inherit}
.actbtn:hover{border-color:var(--cy);color:var(--cy)}
.actbtn.danger:hover{border-color:#B87870;color:#B87870;background:#FBF0EE}
.hiddenwrap{margin:16px 0 4px;border:1px dashed #D9CDB8;border-radius:16px;background:#FBF8F0;overflow:hidden}
.hidden-hd{display:flex;align-items:center;gap:8px;width:100%;padding:11px 15px;border:0;background:transparent;color:var(--ink3);font:inherit;font-size:12px;cursor:pointer;text-align:left}
.hidden-hd b{color:var(--ink2);font-size:12px}
.hidden-hd .chev{margin-left:auto;transition:transform .18s ease}
.hiddenwrap.open .hidden-hd .chev{transform:rotate(180deg)}
.hidden-list{display:none;padding:0 12px 12px}
.hiddenwrap.open .hidden-list{display:block}
.hidden-row{display:flex;align-items:center;gap:10px;padding:8px 4px;border-top:1px solid #F0E8DA;font-size:12.5px;color:var(--ink2)}
.hidden-row:first-child{border-top:0}
.hidden-row .ht{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hidden-row .hid{flex:none;font-size:10px;color:#A6B2AE;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;max-width:38%;overflow:hidden;text-overflow:ellipsis}
/* 编辑弹层 */
.edmask{position:fixed;inset:0;z-index:78;background:rgba(47,58,52,.42);display:flex;align-items:center;justify-content:center;padding:18px 14px;opacity:0;visibility:hidden;transition:opacity .22s ease}
.edmask.on{opacity:1;visibility:visible}
.edcard{width:100%;max-width:600px;max-height:88vh;overflow:auto;background:#FFFCF6;border-radius:20px;padding:18px;box-shadow:0 24px 80px rgba(40,50,42,.22);transform:translateY(12px) scale(.985);transition:transform .26s cubic-bezier(.2,.8,.3,1);-webkit-overflow-scrolling:touch}
.edmask.on .edcard{transform:none}
.edcard h4{font-size:15px;margin:0 0 4px}
.edcard .edhint{font-size:11px;color:var(--ink3);margin:0 0 12px;line-height:1.6}
.edgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.edgrid label{display:flex;flex-direction:column;gap:4px;font-size:11px;font-weight:700;color:var(--ink3)}
.edgrid label.wide{grid-column:1/-1}
.edgrid input,.edgrid select,.edgrid textarea{width:100%;box-sizing:border-box;border:1px solid var(--line);border-radius:10px;padding:9px 11px;font:inherit;font-size:13px;background:#fff;color:var(--ink);outline:none;min-height:38px}
.edgrid textarea{min-height:70px;resize:vertical;line-height:1.6}
.edgrid input:focus,.edgrid select:focus,.edgrid textarea:focus{border-color:var(--cy);box-shadow:0 0 0 3px rgba(94,143,135,.12)}
.edact{display:flex;justify-content:flex-end;gap:8px;margin-top:14px;flex-wrap:wrap}
.edact .btn{min-height:38px}
/* 需求 13：卡片展开/收起高度动画 */
.gcollapse{overflow:hidden;transition:max-height .3s cubic-bezier(.2,.8,.3,1)}
.gcard.folded .gtimeline{opacity:0}
.gtimeline{transition:opacity .22s ease}
.gcard.enter{animation:cardIn .32s cubic-bezier(.2,.8,.3,1) both;animation-delay:calc(var(--i,0)*26ms)}
@keyframes cardIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
/* 需求 13：弹层过渡 */
.modal{display:flex!important;visibility:hidden;opacity:0;pointer-events:none;transition:opacity .22s ease}
.modal.on{visibility:visible;opacity:1;pointer-events:auto}
.mcard{transform:translateY(12px) scale(.985);transition:transform .26s cubic-bezier(.2,.8,.3,1)}
.modal.on .mcard{transform:none}
@media(max-width:700px){
  .ghd .gright{margin-left:0;width:100%;justify-content:flex-start}
  .recurline{margin:8px 16px 0}
  .edgrid{grid-template-columns:1fr}
  .edmask{padding:10px 8px}
  .edcard{padding:14px;max-height:92vh}
}
@media (prefers-reduced-motion:reduce){.gcard.enter{animation:none!important}.gcollapse,.gtimeline,.modal,.mcard,.edmask,.edcard{transition:none!important}}
/* —— 2026-11-14 契约 §2/§3：5 卡可点数据栏 / 期次卡 / 资料栏 / 长期清单 —— */
.brief-top{display:grid;grid-template-columns:repeat(6,minmax(0,1fr))}
.bstat{appearance:none;-webkit-appearance:none;font:inherit;color:inherit;width:100%;box-sizing:border-box;min-height:44px;cursor:pointer;text-align:left}
.bstat:nth-child(1),.bstat:nth-child(2),.bstat:nth-child(3){grid-column:span 2}
.bstat:nth-child(4),.bstat:nth-child(5){grid-column:span 3}
.bstat.on{border-color:var(--cy)!important;box-shadow:0 0 0 2px rgba(94,143,135,.18);background:#F5FAF7!important}
.bstat.latest{background:#F3F1F7!important}
.bstat.recur{background:#EEF3F6!important}
.bstat.latest b{font-size:13px;line-height:1.35;font-weight:700;letter-spacing:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}
.bstat.recur b{color:#4E6D8C}
.bstat:focus-visible{outline:2px solid var(--cy);outline-offset:2px}
.data-wrap.lt-wrap{background:#F7FAF9}
.gcard.occ{border-color:#CFE0E8;box-shadow:0 10px 28px -16px rgba(78,109,140,.35)}
.gcard.occ::before{background:#4E6D8C}
.lt-view{display:flex;flex-direction:column;gap:10px}
.ltrow{display:flex;align-items:center;gap:12px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:13px 14px}
.ltrow .ltrow-main{flex:1;min-width:0}
.ltrow .ltrow-t{font-size:14px;font-weight:700;color:var(--ink);line-height:1.45;overflow-wrap:anywhere}
.ltrow .ltrow-m{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:5px;font-size:11.5px;color:var(--ink3)}
.ltrow .ltp{background:#EEF3F6;color:#4E6D8C;border-radius:6px;padding:1px 7px;font-weight:700}
.ltrow .ltn{font-weight:700;color:#4E6D8C;font-variant-numeric:tabular-nums}
.ltrow .st{flex:none;margin-left:auto}
.lt-empty{text-align:center;color:var(--ink3);font-size:12.5px;padding:26px;background:#fff;border:1px solid var(--line);border-radius:14px}
@media(min-width:960px){
  .brief-top{grid-template-columns:repeat(5,minmax(0,1fr))}
  .bstat:nth-child(n){grid-column:auto}
}
@media(max-width:700px){
  .brief-top{grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}
  .bstat:nth-child(1),.bstat:nth-child(2),.bstat:nth-child(3){grid-column:span 2}
  .bstat:nth-child(4),.bstat:nth-child(5){grid-column:span 3}
  .bstat{min-height:64px;padding:9px 10px}
  .bstat b{font-size:20px}
  .bstat.latest b{font-size:12px}
  .ltrow{padding:11px 12px;gap:10px}
}
@media(max-width:380px){.bstat{padding:8px 9px}.bstat.latest b{font-size:11.5px}}
"""

JS = r"""
var GROUPS=__DATA__;
var FORMS=__FORMS__;
var HOMEWORK=__HOMEWORK__;
var SCHEDULE=__SCHEDULE__;
var CATCLS={ '教务':'jw','团务':'tw','考试':'ks','缴费':'jf','活动':'hd','班级事务':'qt' };
var state={cat:'全部',sub:'全部',hw:'全部',done:{},fold:{},admin:false,hidden:[],hiddenOpen:false,override:{},edited:{},expandExpired:false,expandLongterm:false,expandData:true,card:''};
var RENDER_SIG='';
/* 独立打开 demo 时的管理员 UI 调试开关：notice-board-live-demo.html?admin=1（只调试 UI，不写数据） */
try{ if(/[?&]admin=1(&|$)/.test(location.search||'')||location.hash==='#admin') state.admin=true; }catch(e){}
function $(s,r){return (r||document).querySelector(s)}
function $$(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
/* 2026-11-09 用户需求：取消固定分类，AI 按近期通知动态增删分类。
   CATCLS 只保留“分类→卡片配色 class”的映射；未命中的动态分类用稳定 hash 从调色板取色。 */
var CAT_PALETTE=['jw','tw','ks','jf','hd','qt'];
function catClass(name){
  if(CATCLS[name]) return CATCLS[name];
  var s=String(name||''),h=0;
  for(var i=0;i<s.length;i++) h=(h*31+s.charCodeAt(i))>>>0;
  return CAT_PALETTE[h%CAT_PALETTE.length];
}
function catList(){
  var cnt={},act={},arr=[];
  GROUPS.forEach(function(g){
    var c=String(g.cat||'通知').trim()||'通知';
    cnt[c]=(cnt[c]||0)+1;
    if(cnt[c]===1)arr.push(c);
    if(!act[c]){
      // 2026-11-09 用户要求：一个分类下的项目全部过期后，不再单独展示该分类。
      try{var k=statusOf(g||{}).key;if(k!=='expired'&&k!=='extended_past'&&k!=='alert')act[c]=1;}catch(e){}
    }
  });
  arr=arr.filter(function(c){return act[c];});
  var BASE=['教务','活动','班级事务','缴费','考试','团务'];
  arr.sort(function(a,b){
    var ia=BASE.indexOf(a),ib=BASE.indexOf(b);
    if(ia>=0||ib>=0){if(ia<0)return 1;if(ib<0)return -1;return ia-ib;}
    return (cnt[b]-cnt[a])||a.localeCompare(b,'zh');
  });
  return arr;
}
function renderCatChips(){
  var box=document.getElementById('catRow');if(!box)return;
  var cats=catList();
  if(state.cat!=='全部'&&cats.indexOf(state.cat)<0) state.cat='全部';
  if(!cats.length){box.innerHTML='';box.style.display='none';return;}
  box.style.display='';
  var h='<button class="chipf'+(state.cat==='全部'?' on':'')+'" data-cat="全部">全部分类</button>';
  cats.forEach(function(c){h+='<button class="chipf'+(state.cat===c?' on':'')+'" data-cat="'+esc(c)+'">'+esc(c)+'</button>';});
  box.innerHTML=h;
}
var tt=null;function toast(m){var t=$('#toast');t.textContent=m;t.classList.add('on');clearTimeout(tt);tt=setTimeout(function(){t.classList.remove('on')},2200)}
function pad(n){return n<10?'0'+n:''+n}
function fmt(ts){var d=new Date(ts);return (d.getMonth()+1)+'-'+pad(d.getDate())+' '+pad(d.getHours())+':'+pad(d.getMinutes())}
/* ---------- 2026-11-05 通知时间显示契约 §2：统一「<时间> <动作>」+ 临近相对化 ---------- */
function fmtWhen(ts, now){
  if(ts===null||ts===undefined||ts==='')return '';
  var t=Number(ts);
  if(isNaN(t))return '';
  var n=(now===null||now===undefined)?Date.now():Number(now);
  var left=t-n;
  if(left<0)return fmt(t);                       /* 已过：MM-DD HH:MM */
  if(left<3600*1000)return Math.max(1,Math.ceil(left/60000))+' 分钟后';
  if(left<24*3600*1000)return Math.max(1,Math.ceil(left/3600000))+' 小时后';
  if(left<7*86400000)return Math.max(1,Math.ceil(left/86400000))+' 天后';
  return fmt(t);                                  /* ≥7 天：MM-DD HH:MM */
}
/* 契约 §0.2：chip 动作尽量精简（≤6 字，优先 2–4 字）；长动作→短动作映射 */
var ACTION_SHORT={'报送姓名截止':'报送截止','集合点名':'点名','活动开始':'开始','签到开始':'签到',
  '签到签退':'签到','比赛开始':'比赛','考试开始':'考试','报名已截止':'报名截止','已截止':'截止'};
function shortAction(a){
  a=String(a===null||a===undefined?'':a).replace(/\s+/g,'');
  if(!a)return '';
  if(ACTION_SHORT[a])return ACTION_SHORT[a];
  return a.length>6?a.slice(0,6):a;
}
/* 卡片锚点：同一卡片取第一条 item 的消息时间（契约 §3）；用于相对日期替换 */
function cardAnchorTs(g){
  var its=(g&&g.items)||[];
  for(var i=0;i<its.length;i++){if(its[i]&&its[i].time)return its[i].time}
  return (g&&g.time)||'';
}
/* 2026-11-18 契约《《通知三端·发布时间统一》契约（内部归档）》§1：发布时间。
   优先数据字段 publishedAt（管线统一计算）；旧缓存/旧数据回退组内最新消息时间 + updatedAt（pubTsOf）。 */
function publishedTsOf(g){
  if(!g)return 0;
  if(g.publishedAt){var t=Date.parse(g.publishedAt);if(!isNaN(t)&&t>0)return t;}
  return pubTsOf(g);
}
var _CN_WD={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'日':0,'天':0};
function _relAnchor(refTs){
  var m=/^\s*(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})\s*$/.exec(String(refTs||''));
  if(!m)return null;
  var mo=Number(m[1]),da=Number(m[2]),hh=Number(m[3]),mi=Number(m[4]);
  if(!(mo>=1&&mo<=12&&da>=1&&da<=31&&hh<24&&mi<60))return null;
  var now=new Date(),y=now.getFullYear();
  /* 消息时间不带年份：用当前年；若算出晚于 now+60 天，明显是跨年（上一年） */
  var d=new Date(y,mo-1,da,hh,mi);
  if(isNaN(d.getTime())||d.getDate()!==da)return null;
  if(d.getTime()>now.getTime()+60*86400000)d=new Date(y-1,mo-1,da,hh,mi);
  return d;
}
function _md(d){return pad(d.getMonth()+1)+'-'+pad(d.getDate())}
function _relDay(base,n){return new Date(base.getFullYear(),base.getMonth(),base.getDate()+n,12,0,0)}
function _relMonday(base){var wd=(base.getDay()+6)%7;return _relDay(base,-wd)}
/* 替换后若紧跟中文/字母（非标点、非空白、非结尾），加一个空格：「11-06 中午前」「11-08 晚点名」 */
function _relPunct(ch){return /[\s，。、；：！？!?;,.:：（）()\[\]【】《》》」”"'']/.test(ch)}
function _relSpace(rep, whole, nextIdx){
  if(!/^\d+-\d+$/.test(rep))return rep;   /* 「今晚」→「MM-DD 晚」这类后缀不加空格 */
  if(nextIdx>=whole.length)return rep;
  return _relPunct(whole.charAt(nextIdx))?rep:rep+' ';
}
/* 契约 §0.1：裸日号 N号/N日 只在「上午/下午/晚上/比赛/活动/当天/点名…」语境替换；「42号同学」是序号 */
var _DAY_NO_CUES=/^\s*(上午|早上|下午|晚上|中午|凌晨|当天|点名|比赛|活动|集合|考试|测试|上课|签到|开始|进行|决赛|初赛)/;
function _absDatePat(){return '(?:(?:20\\d{2}\\s*年\\s*)?\\d{1,2}\\s*月\\s*\\d{1,2}\\s*[日号]?|\\d{1,2}-\\d{1,2})'}
function _dateWordPat(){return '(?:(?:20\\d{2}\\s*年\\s*)?\\d{1,2}\\s*月\\s*\\d{1,2}\\s*[日号]?|\\d{1,2}-\\d{1,2}|(?:周|星期|礼拜)[一二三四五六日天]|今天|今日|明天|明日|后天|大后天|明早|明晚|今早|今晚)'}
/* 绝对日期 + 括号内同日相对词去重：11月14日（下周六）→11月14日；11月14日（11-14）→11月14日 */
function _stripDateParens(s){
  var re=new RegExp('('+_absDatePat()+')\\s*[（(]\\s*'+_dateWordPat()+'\\s*[）)]','g');
  return s.replace(re,function(all,d1,offset,whole){
    var next=whole.charAt(offset+all.length);
    /* 只有 MM-DD 结尾才需要补空格；「11月14日」这类中文日期直接接下文 */
    return d1+((/^\d+-\d+$/.test(d1)&&(!next||!_relPunct(next)))?' ':'');
  });
}
/* 显示层：相对/裸时间词 → 带日期（契约 §3 + §0.1）。锚点=该条消息发送时间或卡片第一条 item.time。 */
function absRelDates(text, refTs){
  var s=(text===null||text===undefined)?'':String(text);
  if(!s)return s;
  var a=_relAnchor(refTs);
  if(!a)return s;
  var base=a;
  /* 契约 §0.1/R6：历史数据里「今日校园」可能被上游误替换成「MM-DD校园」→ 还原 App 专名 */
  s=s.replace(/(\d{1,2}-\d{1,2})(?=校园)/g,'今日');
  /* 0) 先去绝对日期后括号里的同日相对词（避免括号内被二次替换） */
  s=_stripDateParens(s);
  /* 1) 相对日：大后天 / 后天 / 明早 / 明晚 / 明天 / 明日 / 今早 / 今晚 / 今天 / 今日 */
  s=s.replace(/(大后天|后天|明早|明晚|明天|明日|今早|今晚|今天|今日)/g,function(all,day,offset,whole){
    var before=whole.slice(Math.max(0,offset-8),offset);
    /* 长期安排/固定说法不替换：每周X、每月前三周的周三；专有名词「今日校园」 */
    if(/每[^，。；、\s]{0,6}$/.test(before))return all;
    if(day==='今日'&&whole.slice(offset+2,offset+4)==='校园')return all;
    var rep='';
    if(day==='今天'||day==='今日')rep=_md(base);
    else if(day==='今晚')rep=_md(base)+' 晚';
    else if(day==='今早')rep=_md(base)+' 早';
    else if(day==='明早')rep=_md(_relDay(base,1))+' 早';
    else if(day==='明天'||day==='明日')rep=_md(_relDay(base,1));
    else if(day==='明晚')rep=_md(_relDay(base,1))+' 晚';
    else if(day==='后天')rep=_md(_relDay(base,2));
    else if(day==='大后天')rep=_md(_relDay(base,3));
    else return all;
    return _relSpace(rep,whole,offset+all.length);
  });
  /* 契约 §0.1/R7：裸周「本周/这周/下周」→ 该周周一；「本周（11.4）」用括号内日期（对齐 notice_time） */
  s=s.replace(/(本|这|下)周\s*[（(]\s*(\d{1,2})\s*[.．]\s*(\d{1,2})\s*[）)]/g,function(all,pre,mo,da,offset,whole){
    mo=Number(mo);da=Number(da);
    if(!(mo>=1&&mo<=12&&da>=1&&da<=31))return all;
    var dt=new Date(base.getFullYear(),mo-1,da,12,0,0);
    if(isNaN(dt.getTime())||dt.getDate()!==da)return all;
    return _relSpace(_md(dt),whole,offset+all.length);
  });
  /* 2) 星期：下周X / 下星期X / 下礼拜X、本周X / 这周X、周X / 星期X / 礼拜X */
  s=s.replace(/(下|本|这)?(?:周|星期|礼拜)([一二三四五六日天])/g,function(all,pre,ch,offset,whole){
    var before=whole.slice(Math.max(0,offset-10),offset);
    var after=whole.slice(offset+all.length,offset+all.length+6);
    /* 长期安排/固定说法不替换：每周三 / 每月前三周的周三（允许中间有空格） */
    if(/每[^，。；]{0,8}$/.test(before))return all;
    /* 课程/群名里的「周一89节」「周三1-2节」不是日期 */
    if(/^\s*\d+\s*[节课]/.test(after))return all;
    var idx=_CN_WD[ch];
    if(idx===undefined)return all;
    var rep;
    if(pre==='下')rep=_md(_relDay(_relMonday(base),7+((idx+6)%7)));
    else if(pre==='本'||pre==='这')rep=_md(_relDay(_relMonday(base),((idx+6)%7)));
    else{
      /* 无前缀：最近一个未来的该星期几（今天同星期则今天） */
      var cur=(base.getDay()+6)%7;
      rep=_md(_relDay(base,((idx+6)%7-cur+7)%7));
    }
    return _relSpace(rep,whole,offset+all.length);
  });
  /* 2b) 裸周（后面不接星期几）：本周/这周 → 本周一；下周 → 下周一（周期语境不替换） */
  s=s.replace(/(本|这|下)周(?![一二三四五六日天末])/g,function(all,pre,offset,whole){
    var before=whole.slice(Math.max(0,offset-8),offset);
    if(/每[^，。；]{0,8}$/.test(before))return all;
    var rep=(pre==='下')?_md(_relDay(_relMonday(base),7)):_md(_relMonday(base));
    return _relSpace(rep,whole,offset+all.length);
  });
  /* 3) 裸日号 N号/N日（「5号比赛」→11-05）；序号/已有完整日期不替换 */
  s=s.replace(/(\d{1,2})\s*[号日]/g,function(all,num,offset,whole){
    var before=whole.slice(0,offset);
    var after=whole.slice(offset+all.length,offset+all.length+10);
    if(/(?:[月\d第])\s*$/.test(before))return all;   /* 11月5日 / 第5号 / 数字串 */
    if(!_DAY_NO_CUES.test(after))return all;
    var day=Number(num);
    if(!(day>=1&&day<=31))return all;
    var dt=new Date(base.getFullYear(),base.getMonth(),day,12,0,0);
    if(isNaN(dt.getTime())||dt.getDate()!==day)return all;
    return _md(dt)+((!after||_relPunct(after.charAt(0)))?'':' ');
  });
  /* 4) 裸时段：上午/中午/下午/晚上/凌晨（前 12 字内无日期、非每天/每周/每月语境）→ 前缀锚点日期 */
  s=s.replace(/(上午|中午|下午|晚上|凌晨)/g,function(all,word,offset,whole){
    var before=whole.slice(Math.max(0,offset-12),offset);
    if(/(?:\d{1,2}\s*[-\/月]\s*\d{1,2}|月\s*\d{1,2}|[一二三四五六七八九十]月|\d{1,2}-\d{1,2}|星期|礼拜|周[一二三四五六日天])/.test(before))return all;
    if(/[0-9]$/.test(before))return all;
    var tail=whole.slice(Math.max(0,offset-6),offset);
    if(/每(?:天|周|月)|每日|长期/.test(tail))return all;
    return _md(base)+' '+word;
  });
  /* 5) 替换后再做一次括号去重（相对→MM-DD 后：11-08（11-06）→11-08） */
  s=_stripDateParens(s);
  return s;
}
/* ---------- 2026-11-14 契约 §3：日期显示统一 M月D日（相对周） ---------- */
/* now 可注入（测试固定时钟）：NOW_OVERRIDE=0 时用真实时间，行为与旧逻辑一致。 */
var NOW_OVERRIDE=0;
function nowMs(){return NOW_OVERRIDE||Date.now()}
var _WD_CHARS='日一二三四五六';
function _weekWordOf(d,now){
  var base=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  var dd=new Date(d.getFullYear(),d.getMonth(),d.getDate());
  var diff=Math.round((dd.getTime()-base.getTime())/86400000);
  var mon=_relMonday(base),dmon=_relMonday(dd);
  var weeks=Math.round((dmon.getTime()-mon.getTime())/(7*86400000));
  var wd=_WD_CHARS.charAt(d.getDay());
  /* 契约 §3 固定向量：今天/明天优先；同周统一「本周X」（11-13 昨天也显示本周五）；
     「昨天」只用于跨周的一天前（如周一昨天=上周日）。 */
  if(diff===0)return '今天';
  if(diff===1)return '明天';
  if(weeks===0)return '本周'+wd;
  if(weeks===1)return '下周'+wd;
  if(diff===-1)return '昨天';
  if(weeks===-1)return '上周'+wd;
  return '周'+wd;
}
function datePhrase(y,mo,da,now){
  if(!(mo>=1&&mo<=12&&da>=1&&da<=31))return null;
  var d=new Date(y,mo-1,da);
  if(isNaN(d.getTime())||d.getFullYear()!==y||d.getMonth()!==mo-1||d.getDate()!==da)return null;
  var prefix=(y!==now.getFullYear())?(y+'年'):'';
  return prefix+mo+'月'+da+'日（'+_weekWordOf(d,now)+'）';
}
/* 显示层统一格式化：MM-DD / M月D日 / YYYY-MM-DD / YYYY年M月D日 → M月D日（相对周）。
   已是「M月D日（…）」的不重复加括号；倒计时相对文案（2 小时后）不受影响。 */
function fmtDateText(text,nowTs){
  var s=(text===null||text===undefined)?'':String(text);
  if(!s)return s;
  var now=(nowTs===null||nowTs===undefined)?new Date(nowMs()):new Date(Number(nowTs));
  if(isNaN(now.getTime()))now=new Date(nowMs());
  var Y=now.getFullYear();
  var slots=[];
  function keep(m){slots.push(m);return '\u0001'+(slots.length-1)+'\u0002'}
  /* 已带括号的中文日期：占位保护，避免二次加括号 */
  s=s.replace(/(?:20\d{2}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*[日号]\s*[（(][^）)\n]{1,14}[）)]/g,keep);
  function repYear(all,y,mo,da){var r=datePhrase(+y,+mo,+da,now);return r===null?all:r}
  s=s.replace(/(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]/g,repYear);
  s=s.replace(/(20\d{2})-(\d{1,2})-(\d{1,2})(?![0-9T])/g,repYear);
  s=s.replace(/(\d{1,2})\s*月\s*(\d{1,2})\s*[日号](?!\s*[（(])/g,function(all,mo,da){
    var r=datePhrase(Y,+mo,+da,now);return r===null?all:r;
  });
  s=s.replace(/(\d{1,2})-(\d{1,2})/g,function(all,ms,ds,offset,whole){
    var before=offset>0?whole.charAt(offset-1):'';
    var after=whole.charAt(offset+all.length);
    if(/[0-9:：]/.test(before))return all;
    if(/[节点号时分秒周月]/.test(before))return all;
    if(/[节点号时分秒周]/.test(after))return all;
    var r=datePhrase(Y,+ms,+ds,now);
    return r===null?all:r;
  });
  s=s.replace(/\u0001(\d+)\u0002/g,function(all,i){return slots[+i]});
  return s;
}
/* 渲染入口：先做既有相对日期→MM-DD，再统一格式化为 §3 显示格式 */
function disp(text,refTs){return fmtDateText(absRelDates(text,refTs))}
window.__zqSetNow=function(ts){NOW_OVERRIDE=Number(ts)||0;try{render({animate:false});}catch(e){}};
window.__zqNow=function(){return nowMs()};
/* ---------- v2.0.0：长期安排（需求 9）本地计算下一次；算法与小程序一致 ---------- */
function weekdayName(wd){return ['周日','周一','周二','周三','周四','周五','周六'][Number(wd)]||''}
function recTime(rec){var m=/^(\d{1,2}):(\d{2})$/.exec(String(rec.time||''));return m?[Number(m[1])%24,Number(m[2])%60]:[0,0]}
function recOccurrence(d, weekday){ /* 该 weekday 在当月第几次出现（1..5） */
  var first=new Date(d.getFullYear(),d.getMonth(),1);
  var offset=(Number(weekday)-first.getDay()+7)%7;
  return Math.floor((d.getDate()-1-offset)/7)+1;
}
function recMatches(d,rec){
  var wd=d.getDay();
  if(rec.freq==='daily')return true;
  if(rec.freq==='weekly')return wd===Number(rec.weekday);
  if(rec.freq==='monthly_day')return d.getDate()===Number(rec.day);
  if(rec.freq==='monthly_weeks'){
    if(wd!==Number(rec.weekday))return false;
    var weeks=(rec.weeks||[]).map(Number);
    if(!weeks.length)return true;
    return weeks.indexOf(recOccurrence(d,wd))>=0;
  }
  return false;
}
function nextRecurDate(rec,nowTs){
  if(!rec||!rec.freq)return null;
  var t=recTime(rec),hh=t[0],mm=t[1];
  var start=rec.startAt?Date.parse(rec.startAt):0;
  if(isNaN(start))start=0;
  var now=Number(nowTs)||Date.now();
  var from=Math.max(now,start);
  var base=new Date(from);
  for(var i=0;i<400;i++){
    var d=new Date(base.getFullYear(),base.getMonth(),base.getDate()+i,hh,mm,0,0);
    if(d.getTime()<from)continue;
    if(start&&d.getTime()<start)continue;
    if(recMatches(d,rec))return d;
  }
  return null;
}
function recDateText(d,now){
  now=now||new Date(nowMs());
  var dp=datePhrase(d.getFullYear(),d.getMonth()+1,d.getDate(),now);
  return (dp||(''+pad(d.getMonth()+1)+'-'+pad(d.getDate())))+' '+pad(d.getHours())+':'+pad(d.getMinutes());
}
function recurLineHTML(g){
  var rec=g&&g.recurrence;
  if(!rec||!rec.freq)return '';
  var label=rec.label||('长期安排 '+weekdayName(rec.weekday)+' '+(rec.time||''));
  var next=recurNext(rec,nowMs());
  return '<div class="recurline"><span class="rl">'+esc(label)+'</span>'+
    (next?'<span class="rn">下次 '+esc(recDateText(next))+'</span>':'')+'</div>';
}
/* ---------- 2026-11-14 契约 §1.3：长期安排期次（occurrence，三端同一算法） ---------- */
function recurEndTs(rec){
  if(!rec||!rec.until)return Infinity;
  var u=String(rec.until);
  var m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(u);
  if(m){var d=new Date(Number(m[1]),Number(m[2])-1,Number(m[3]),23,59,59,999);return isNaN(d.getTime())?Infinity:d.getTime();}
  var t=Date.parse(u);
  return isNaN(t)?Infinity:t;
}
function recurEnded(rec,now){return ((now===undefined||now===null)?nowMs():now)>recurEndTs(rec)}
/* until 含当天：下一次发生超出 until 当天 23:59 → 视为已无下一次（契约 §1.3 固定向量） */
function recurNext(rec,now){
  now=(now===undefined||now===null)?nowMs():now;
  if(!rec||!rec.freq)return null;
  var next=nextRecurDate(rec,now);
  if(!next)return null;
  if(next.getTime()>recurEndTs(rec))return null;
  return next;
}
function recurOngoing(rec,now){
  now=(now===undefined||now===null)?nowMs():now;
  if(!rec||!rec.freq)return false;
  if(recurEnded(rec,now))return false;
  return !!recurNext(rec,now);
}
/* 期次：next = 下一次发生（严格 > now）；窗口 [next-24h, next)；key = gid@occ:YYYYMMDD */
function occurrenceOf(g,now){
  now=(now===undefined||now===null)?nowMs():now;
  var rec=g&&g.recurrence;
  if(!recurOngoing(rec,now))return null;
  var next=recurNext(rec,now);
  if(!next)return null;
  var ts=next.getTime(),start=ts-24*3600*1000;
  if(!(start<=now&&now<ts))return null;
  var key=g.id+'@occ:'+next.getFullYear()+pad(next.getMonth()+1)+pad(next.getDate());
  return {key:key,next:next,ts:ts,start:start};
}
function occOfGroup(g,now){
  var occ=occurrenceOf(g,now);
  if(!occ)return null;
  if(state.done[occ.key])return null;   /* 该期次已处理 → 本期卡片消失 */
  return occ;
}
function occClone(g,occ){
  var c={};
  for(var k in g){if(Object.prototype.hasOwnProperty.call(g,k))c[k]=g[k];}
  c.id=occ.key;c.__baseId=g.id;c.__occ=1;c.__occTs=occ.ts;c.__occKey=occ.key;c.__occNext=occ.next;
  return c;
}
function occurrences(now,list){
  var out=[];
  (list||GROUPS).forEach(function(g){
    if(!g||!g.recurrence||!g.recurrence.freq)return;
    var occ=occOfGroup(g,now);
    if(occ)out.push(occClone(g,occ));
  });
  return out;
}
function recurPeriodText(rec){
  if(!rec)return '';
  if(rec.label)return String(rec.label);
  var t=String(rec.time||'');
  if(rec.freq==='daily')return '每日 '+t;
  if(rec.freq==='weekly')return '每周'+weekdayName(rec.weekday)+' '+t;
  if(rec.freq==='monthly_weeks')return '每月第'+(rec.weeks||[]).join('、')+'周 '+weekdayName(rec.weekday)+' '+t;
  if(rec.freq==='monthly_day')return '每月'+(rec.day||'')+'日 '+t;
  return '长期安排 '+t;
}
/* ---------- v2.0.0：文件大小 / data URI ---------- */
function dataUriMime(url){var m=/^data:([^;,]+)/.exec(String(url||''));return m?m[1].toLowerCase():''}
function dataUriBytes(url){
  var s=String(url||''),i=s.indexOf(',');
  if(i<0)return 0;
  var b=s.slice(i+1),n=b.length;
  if(/;base64,/.test(s.slice(0,i+8))){while(n>0&&b.charAt(n-1)==='=')n--;return Math.round(n*3/4)}
  return n;
}
function fmtBytes(n){
  n=Number(n)||0;
  if(n<1024)return n+' B';
  if(n<1048576)return (n/1024).toFixed(0)+' KB';
  return (n/1048576).toFixed(1)+' MB';
}
/* ---------- v2.1：附件外置（data URI → 签名 https URL）兼容 ---------- */
function isHttpUrl(u){return /^https?:\/\//i.test(String(u||''))}
var FILE_EXT_MIME={pdf:'application/pdf',png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',gif:'image/gif',webp:'image/webp',doc:'application/msword',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',xls:'application/vnd.ms-excel',xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',ppt:'application/vnd.ms-powerpoint',pptx:'application/vnd.openxmlformats-officedocument.presentationml.presentation',zip:'application/zip','7z':'application/x-7z-compressed',rar:'application/vnd.rar',txt:'text/plain'};
function fileMime(it,url){var m=dataUriMime(url);if(m)return m;var n=String((it&&it.name)||'');var e=n.indexOf('.')>=0?n.split('.').pop().toLowerCase():'';return FILE_EXT_MIME[e]||''}
function attSizeText(it,url){if(isHttpUrl(url))return String((it&&it.size)||'');return fmtBytes(dataUriBytes(url))}
/* ---------- v2.0.0：管理员（需求 12） ---------- */
function findGroup(gid){
  for(var i=0;i<GROUPS.length;i++)if(GROUPS[i].id===gid)return GROUPS[i];
  /* 期次卡 data-gid=<gid>@occ:YYYYMMDD → 回落到长期安排定义组 */
  var s=String(gid||''),m=s.indexOf('@occ:');
  if(m>0){var base=s.slice(0,m);for(var j=0;j<GROUPS.length;j++)if(GROUPS[j].id===base)return GROUPS[j];}
  return null;
}
function hiddenMap(){var m={};(state.hidden||[]).forEach(function(x){if(x&&x.gid)m[x.gid]=true});return m}
function isHiddenGid(gid){return !!hiddenMap()[gid]}
var OV_FIELDS=['title','cat','summary','aiSummary','deadline','eventAt','expireAt','timeLabel'];
function applyOverrideLocal(gid,obj){
  var g=findGroup(gid);
  if(!g||!obj)return;
  OV_FIELDS.forEach(function(k){
    if(!Object.prototype.hasOwnProperty.call(obj,k))return;
    var v=obj[k];
    if(v===null||v===''){delete g[k];}
    else{g[k]=v;}
  });
  state.override[gid]=obj;
  state.edited[gid]=true;
}
function postParent(msg){try{if(window.parent&&window.parent!==window)window.parent.postMessage(msg,'*');}catch(e){}}
function hasParentFrame(){try{return !!(window.parent&&window.parent!==window)}catch(e){return false}}
function isoToLocalInput(iso){
  if(!iso)return '';
  var d=new Date(iso);
  if(isNaN(d.getTime()))return '';
  return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes());
}
function localInputToIso(v){
  if(!v)return '';
  var d=new Date(v);
  if(isNaN(d.getTime()))return '';
  var off=-d.getTimezoneOffset(),sign=off>=0?'+':'-',abs=Math.abs(off);
  return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+
    pad(d.getHours())+':'+pad(d.getMinutes())+':00'+sign+pad(Math.floor(abs/60))+':'+pad(abs%60);
}
function deadlineOf(g){var dl=g.deadline; if(g.extensions&&g.extensions.length){dl=g.extensions[g.extensions.length-1].deadline;} return dl?Date.parse(dl):null;}
function expireOf(g){if(g&&g.__occ)return g.__occTs;return g.expireAt?Date.parse(g.expireAt):deadlineOf(g);}
function timeLabelOf(g){return g.timeLabel||(g.eventAt?fmt(Date.parse(g.eventAt)):'');}
function statusOf(g){
  // 2026-11-14 契约 §1.3/§2.3：期次卡状态胶囊 = 本次 M月D日（周X）HH:MM
  if(g&&g.__occ&&g.__occNext){
    var nx=g.__occNext, nd=new Date(nowMs());
    var nph=datePhrase(nx.getFullYear(),nx.getMonth()+1,nx.getDate(),nd);
    return {key:'recur',cls:'recur',label:'本次 '+(nph||(''+pad(nx.getMonth()+1)+'-'+pad(nx.getDate())))+' '+pad(nx.getHours())+':'+pad(nx.getMinutes())};
  }
  // 真实截止(含延期) 与 自动归档时间(expireAt) 分开：expireAt 只是“什么时候不再显示为进行中”，
  // 绝不能拿来当截止时间显示（QQ 群文本通知里 expireAt 是 7 天后的兜底归档时间）。
  // 契约 §2：label 统一为「<时间> <动作>」；key/cls 保持不变（筛选/统计/排序依赖）。
  var now=nowMs();
  var real=deadlineOf(g);
  var archiveAt=g.expireAt?Date.parse(g.expireAt):null;
  var eventAt=g.eventAt?Date.parse(g.eventAt):null;
  var suStart=g.signupStart?Date.parse(g.signupStart):null;
  var suEnd=g.signupEnd?Date.parse(g.signupEnd):null;
  var ext=g.extensions&&g.extensions.length?g.extensions[g.extensions.length-1]:null;
  function byLeft(t,isExt){
    var left=t-now, st;
    if(left<3600*1000) st={key:'urgent',cls:'urgent'};
    else if(left<24*3600*1000) st={key:'today',cls:'urgent'};
    else if(left<72*3600*1000) st={key:'soon',cls:'active'};
    else st={key:'active',cls:'active'};
    if(isExt) st={key:'extended',cls:'extended'};
    return st;
  }
  function expiredSt(){
    if(g.alert) return {key:'alert',label:'已截止 · 有新名单',cls:'alert'};
    if(ext) return {key:'extended_past',label:'',cls:'expired'};
    return {key:'expired',label:'',cls:'expired'};
  }
  // 1) 长期安排（唯一例外：label 不是「时间+动作」；until 结束或无下一次 → 长期安排已结束，归入已过期区）
  if(g.recurrence&&g.recurrence.freq){
    if(recurEnded(g.recurrence,now)||!recurNext(g.recurrence,now)){
      var eEnd=expiredSt();
      eEnd.label='长期安排已结束';
      return eEnd;
    }
    var rl=g.recurrence.label?('长期安排 · '+g.recurrence.label):'长期安排';
    return {key:'recur',label:rl,cls:'recur'};
  }
  // 2.5) AI 质检明确判定已过期（历史活动/名单/赛程/课程安排等；2026-11-09 用户第 2 条）
  if(g.expired===true){
    var e0=expiredSt();
    if(!e0.label) e0.label='已过期';
    return e0;
  }
  // 2.6) 先判过期，再判已处理：已处理的过期通知也要放入过期栏（2026-11-09 用户要求）。
  //      过期统一用三处依据：报名截止、截止、活动结束（与下面各 active 分支的阈值一致）。
  var expInfo=null;
  if(suEnd&&now>=suEnd){
    expInfo={label:fmtWhen(suEnd,now)+' 报名截止'};
  }else if(real&&now>real){
    expInfo={label:fmtWhen(real,now)+' '+(shortAction(g.deadlineAction||'截止')||'截止')};
  }else if(eventAt&&now>(archiveAt||eventAt)){
    expInfo={label:fmtWhen(eventAt,now)+' '+(shortAction(g.eventAction||'开始')||'开始')};
  }
  if(expInfo){
    var eNow=expiredSt();
    if(eNow.key==='alert') return eNow;
    eNow.label=expInfo.label;
    return eNow;
  }
  // 3) 已处理（未过期）
  if(state.done[g.id]) return {key:'done',label:'已处理',cls:'active'};
  // 3.5) 多个报名窗口（如三个子活动分别报名）：按当前时间取当前/下一个窗口动态展示
  var wins=Array.isArray(g.signupWindows)?g.signupWindows:[];
  if(wins.length){
    var curW=null,nextW=null;
    for(var wi=0;wi<wins.length;wi++){
      var w=wins[wi]||{};
      var ws=w.start?Date.parse(w.start):null, we=w.end?Date.parse(w.end):null;
      if((!ws||now>=ws)&&(!we||now<=we)){curW={s:ws,e:we,label:w.label||''};break;}
      if(ws&&now<ws&&(!nextW||ws<nextW.s))nextW={s:ws,e:we,label:w.label||''};
    }
    var pick=curW||nextW;
    if(pick){
      if(pick.s&&now<pick.s){var q1=byLeft(pick.s,false);q1.label=fmtWhen(pick.s,now)+' 报名开始';return q1;}
      if(pick.e&&now<pick.e){var q2=byLeft(pick.e,false);q2.label=fmtWhen(pick.e,now)+' 报名截止';return q2;}
      // 窗口已开始但没有结束时间（或已全部结束）：继续走下面 signup/deadline/eventAt 逻辑，
      // 避免返回没有时间的「报名中」而破坏 chip 契约（A7）。
    }
  }
  // 4) 报名优先（活动报名类：未报名的人只关心报名时间）
  if(suStart||suEnd){
    if(suStart&&now<suStart){var s1=byLeft(suStart,false);s1.label=fmtWhen(suStart,now)+' 报名开始';return s1;}
    if(suEnd&&now<suEnd){var s2=byLeft(suEnd,false);s2.label=fmtWhen(suEnd,now)+' 报名截止';return s2;}
    /* 只有 signupStart 且已开始：报名窗口未结束 → 回落到 deadline/eventAt 主时间 */
  }
  // 5) 截止（延期取最后一条 deadline；动作走 §0.2 短词映射）
  if(real){
    var act=shortAction(g.deadlineAction||'截止')||'截止';
    var d1=byLeft(real,!!ext);d1.label=fmtWhen(real,now)+' '+act;return d1;
  }
  // 6) 活动/事件开始
  if(eventAt){
    var act2=shortAction(g.eventAction||'开始')||'开始';
    return {key:'active',label:fmtWhen(eventAt,now)+' '+act2,cls:'active'};
  }
  // 7) 既无截止也无活动/报名时间（例如「运动会期间晚自习正常」）：
  //    2026-11-18 契约 §2：以发布时间作为卡片时间，动作=「发布」；没有发布时间才显示「无时间」。
  var pubTs=publishedTsOf(g);
  if(pubTs){
    return {key:'published',label:fmtWhen(pubTs,now)+' '+(g.publishAction||'发布'),cls:'active'};
  }
  return {key:'none',label:'无时间',cls:'none'};
}
function formInfo(g,it){
  var hasExt=g.extensions&&g.extensions.length;
  var close=hasExt?deadlineOf(g):(it.close?Date.parse('2026-'+it.close.replace(' ','T')+':00+08:00'):null);
  var now=Date.now();
  var closed=close&&now>close;
  var label=closed?'已截止':'报名中';
  var closeLabel=close?fmt(close):(it.close||'');
  return {k:closed?'closed':'open',label:label,close:closeLabel,extended:!!hasExt};
}
function srcLine(g){
  var s=disp(g.source||g.group||'班级通知',cardAnchorTs(g));
  var kind=s.indexOf('QQ')>=0?'qq':(s.indexOf('微信')>=0?'wx':'doc');
  var icon=kind==='qq'
    ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" d="M12 2.7c-4.2 0-7.2 3-7.2 7.3 0 2 .7 3.8 1.8 5.1-.2 1-.8 2.2-1.7 3.1-.3.3 0 .7.4.6 1.4-.3 2.5-.9 3.3-1.5.9.4 2 .6 3.3.6 4.2 0 7.2-3 7.2-7.3S16.2 2.7 12 2.7z"/><ellipse cx="9.2" cy="9.5" rx="1.15" ry="1.45" fill="#0B8FEA"/><ellipse cx="14.8" cy="9.5" rx="1.15" ry="1.45" fill="#0B8FEA"/><path d="M10.7 13.2l1.3 1.2 1.3-1.2" fill="none" stroke="#0B8FEA" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    : kind==='wx'
    ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" d="M9.1 4.1C4.9 4.1 1.7 6.9 1.7 10.4c0 1.9 1 3.5 2.7 4.6l-.7 2.2 2.5-1.2c.8.3 1.8.5 2.9.5.4 0 .9 0 1.3-.1-.2-.5-.3-1-.3-1.5 0-3.3 3-6 6.8-6 .4 0 .8 0 1.2.1-.7-2.7-3.5-4.9-6.8-4.9z"/><path fill="#fff" d="M22.3 14.2c0-2.8-2.7-5-6-5s-6 2.2-6 5 2.7 5 6 5c.9 0 1.7-.2 2.4-.5l2 1-.6-1.8c1.3-.9 2.2-2.2 2.2-3.7z"/><circle cx="5.7" cy="9.1" r=".9" fill="#19B866"/><circle cx="11.8" cy="9.1" r=".9" fill="#19B866"/><circle cx="14.4" cy="13.5" r=".75" fill="#19B866"/><circle cx="18.5" cy="13.5" r=".75" fill="#19B866"/></svg>'
    : '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" d="M6 3.8h8l4 4v12.4H6z"/><path fill="#D7E4F0" d="M14 3.8v4h4"/><path d="M9 12h6M9 15.5h6" stroke="#54728F" stroke-width="1.4" stroke-linecap="round"/></svg>';
  return '<div class="srcline"><span class="srcchip '+kind+'"><i class="ic">'+icon+'</i><span class="st">'+esc(s)+'</span></span>'+(function(){
    var ms=g.mergedSources||[];
    if(ms.length<2)return '';
    var kinds={};
    ms.forEach(function(x){var t=(x.kind==='qq'?'QQ':(x.kind==='wx'?'微信':''));if(t)kinds[t]=1;});
    var ks=Object.keys(kinds);
    var title=ms.map(function(x){return String(x.source||x.group||'')}).join('；');
    return '<span class="srcmore" title="'+esc('合并来源：'+title)+'">＋'+esc(ks.join('／')||'多来源')+'</span>';
  })()+'</div>';
}
function pubLine(g){
  if(!g.senderName) return '';
  var title=g.senderRole||g.senderBadge||'';
  var h='<div class="publine">';
  if(title) h+='<span class="pubbadge">'+esc(title)+'</span>';
  h+='<span class="pubname">'+esc(g.senderName)+'</span>';
  return h+'</div>';
}
function compose(g){
  var c={};g.items.forEach(function(it){c[it.kind]=(c[it.kind]||0)+1});
  var parts=[];var names={text:'条通知',file:'个附件',img:'张图片',form:'个收集表',link:'个链接',mini:'个小程序',article:'篇文章',follow:'条补充'};
  ['text','form','file','img','link','mini','article','follow'].forEach(function(k){if(c[k])parts.push('<span class="cchip"><b>'+c[k]+'</b> '+names[k]+'</span>')});
  return '<div class="gcompose">'+parts.join('')+'</div>';
}
function cleanNoticeText(s){
  return (s||'')
    .replace(/@(所有人|全体成员|全体同学|全体|大家)\s*/g,'')
    .replace(/\r/g,'')
    .replace(/[ \t]+/g,' ')
    .replace(/^[，,。；;、\s]+/,'')
    .trim();
}
function splitNotice(s){
  s=cleanNoticeText(s);
  if(!s) return [];
  var lines=s.split(/\n+/).map(function(x){return x.trim()}).filter(Boolean),out=[];
  lines.forEach(function(line){
    if(line.length<=110){out.push(line);return}
    var parts=line.match(/[^。！？；!?;]+[。！？；!?;]?/g)||[line],buf='';
    parts.forEach(function(p){
      if((buf+p).length>95){if(buf)out.push(buf.trim());buf=p}
      else buf+=p;
    });
    if(buf.trim())out.push(buf.trim());
  });
  return out.length?out:[s];
}
function itemType(g,it){
  if(it.kind==='follow') return {label:'补充通知',cls:'supp'};
  if(it.kind==='file') return {label:'附件',cls:'file'};
  if(it.kind==='img') return {label: it.ocr ? '通知图片' : '二维码', cls:'img'};
  if(it.kind==='link') return {label:'链接',cls:'link'};
  if(it.kind==='mini') return {label:'小程序',cls:'mini'};
  if(it.kind==='form') return {label:'收集表',cls:'link'};
  if(it.kind==='article') return {label:'文章',cls:'link'};
  if(it.kind==='text'){
    if(String(it.label||'')==='补充通知') return {label:'补充通知',cls:'supp'};
    var texts=g.items.filter(function(x){return x.kind==='text'});
    var pos=texts.indexOf(it);
    if(/补充|更正|修正|更新/.test(it.text||'')) return {label:'补充通知',cls:'supp'};
    return {label:pos<=0?'原始消息':'补充通知',cls:pos<=0?'original':'supp'};
  }
  return {label:'消息',cls:''};
}
function segmentClass(t){
  if(/时间|日期|时段/.test(t)) return 'time';
  if(/地点|位置|场地/.test(t)) return 'place';
  if(/对象|参与|面向/.test(t)) return 'who';
  if(/报名|方式|入口/.test(t)) return 'join';
  if(/截止|日期/.test(t)) return 'due';
  if(/要求|注意|须|需/.test(t)) return 'rule';
  if(/联系|电话|咨询/.test(t)) return 'contact';
  return 'info';
}
function compactSegments(g){
  var order=['时间','地点','对象','内容','报名','截止','要求','联系方式','补充'];
  var map={};
  var anchorTs=cardAnchorTs(g);
  (g.aiSegments||[]).forEach(function(s){
    var t=String(s.type||'内容').replace('联系','联系方式');
    if(order.indexOf(t)<0) t='补充';
    if(!map[t]) map[t]={type:t,texts:[]};
    var txt=disp(String(s.text||'').trim(),anchorTs);
    if(txt&&map[t].texts.length<2&&map[t].texts.indexOf(txt)<0) map[t].texts.push(txt);
  });
  var out=[];
  order.forEach(function(t){if(map[t]&&map[t].texts.length) out.push({type:t,text:map[t].texts.join('；')})});
  return out.slice(0,6);
}
function segmentHTML(seg){
  var cls=segmentClass(seg.type);
  return '<div class="seg-fact"><span class="gi-type seg '+cls+'">'+esc(seg.type||'内容')+'</span>'+
    '<div class="seg-txt">'+esc(seg.text||'')+'</div></div>';
}
function archiveHTML(a,g,idx){
  if(!a||!a.files||!a.files.length)return '';
  var rows=a.files.map(function(f,fi){
    var dl=f.url?'<a class="go sm" href="'+esc(f.url)+'" download="'+esc(f.name)+'">下载</a>':
      (f.lazy?'<button class="go sm" type="button" data-act="lazybody" data-lazyact="archive" data-gid="'+esc((g&&g.id)||'')+'" data-idx="'+(idx||0)+'" data-fidx="'+fi+'">加载</button>':'');
    return '<div class="arc-row"><span class="arc-kind">'+esc(f.kind||'文件')+'</span>'+
      '<span class="arc-name" title="'+esc(f.path||f.name||'')+'">'+esc(f.name||'')+'</span>'+
      '<span class="arc-size">'+esc(f.size||'')+'</span>'+dl+'</div>';
  }).join('');
  var pts=(a.aiPoints&&a.aiPoints.length)?'<div class="arch-points">'+a.aiPoints.map(function(p){return '<span class="arc-p">'+esc(p)+'</span>'}).join('')+'</div>':'';
  var sum=a.summary?'<div class="arch-sum">'+esc(a.summary)+'</div>':'';
  return '<details class="archivecard"'+(a.count<=10?' open':'')+'><summary><span class="arc-t">压缩包内容 · '+a.count+' 个文件</span>'+
    (a.aiTitle?'<span class="arc-at">'+esc(a.aiTitle)+'</span>':'')+'</summary>'+sum+pts+
    '<div class="arch-list">'+rows+'</div></details>';
}
function itemHTML(g,it,idx){
  var ty=itemType(g,it);
  var h='<div class="gitem">';
  h+='<div class="gi-hd"><span class="gi-type '+ty.cls+'">'+esc(ty.label)+'</span>';
  if(it.fromName||it.from){
    var ftitle=(it.fromRole||it.fromBadge||'');
    h+='<span class="gi-from">'+(ftitle?'<span class="gi-badge">'+esc(ftitle)+'</span>':'')+esc(it.fromName||it.from)+'</span>';
  }
  h+='<span class="gi-time">'+esc(it.time||'')+'</span></div>';
  if(it.kind==='text'||it.kind==='follow'){
    /* §0.1：原文按该条消息自身发送时间做日期化（缺 time 时退回卡片锚点） */
    var parts=splitNotice(disp(it.text,it.time||cardAnchorTs(g))),shown=parts.slice(0,2).join('\n');
    var truncated=parts.length>2;
    if(truncated) shown+='…';
    if(it.kind==='follow'){
      h+='<div class="followrow">'+esc(shown)+'</div>';
    } else {
      h+='<div class="gi-body" id="b-'+g.id+'-'+idx+'"><div class="quote'+(truncated?' clamp':'')+'">'+esc(shown)+'</div></div>';
    }
  } else if(it.kind==='merged'){
    h+='<details class="mergedcard"><summary><span class="mtitle">'+esc(it.title||'聊天记录')+'</span>'+
       '<span class="mcount">'+esc(String(it.count||(it.messages||[]).length))+' 条</span></summary><div class="merged-list">';
    (it.messages||[]).forEach(function(m){
      h+='<div class="mrow"><div class="mhd">'+((m.fromRole||m.fromBadge)?'<span class="gi-badge">'+esc(m.fromRole||m.fromBadge)+'</span>':'')+'<span class="mname">'+esc(m.fromName||m.from||'')+'</span><span class="mtime">'+esc(m.time||'')+'</span></div>'+
         '<div class="mtext">'+esc(disp(m.text||'',cardAnchorTs(g)))+'</div></div>';
    });
    h+='</div></details>';
  } else if(it.kind==='file'){
    var furl=it.url||'';
    var groupName=g.group||g.source||'QQ 群';
    var arch=it.archive;
    if(furl){
      var mime=fileMime(it,furl);
      var sz=attSizeText(it,furl);
      var fnote='附件'+(sz?' · '+sz:'')+(mime==='application/pdf'?' · PDF':'');
      h+='<div class="linkrow"><span class="ico">文件</span><div class="lb"><div class="lt">'+esc(disp(it.name,it.time||cardAnchorTs(g)))+'</div>'+
         '<div class="lu">'+esc(fnote)+'</div></div>'+
         '<button class="go" data-act="preview" data-gid="'+g.id+'" data-idx="'+idx+'">预览</button>'+
         '<a class="go ghost" href="'+esc(furl)+'" download="'+esc(it.name)+'">下载</a></div>';
      if(arch&&arch.count) h+=archiveHTML(arch,g,idx);
    } else if(arch&&arch.count){
      /* 压缩包已解压识别：原包可能超过内嵌上限，但已给出包内文件清单/摘要/小文件下载 */
      h+='<div class="linkrow"><span class="ico">包</span><div class="lb"><div class="lt">'+esc(disp(it.name,it.time||cardAnchorTs(g)))+'</div>'+
         '<div class="lu">'+esc(it.note||('压缩包 · 已识别 '+arch.count+' 个文件'))+'</div></div>'+
         '<span class="okbadge">已识别</span></div>';
      h+=archiveHTML(arch,g,idx);
    } else if(it.lazy){
      /* 2026-11-18 列表轻量化：完整附件字节在单行 body 里，点击时才拉取。 */
      h+='<div class="linkrow missing" data-act="lazybody" data-lazyact="preview" data-gid="'+g.id+'" data-idx="'+idx+'"><span class="ico">文件</span>'+
         '<div class="lb"><div class="lt">'+esc(it.name)+'</div>'+
         '<div class="lu">'+esc(it.note||'附件 · 点击加载')+'</div></div>'+
         '<span class="missbadge">点击加载</span></div>';
    } else if(arch){
      h+='<div class="linkrow missing" data-act="filemiss" data-gid="'+g.id+'" data-idx="'+idx+'"><span class="ico">包</span>'+
         '<div class="lb"><div class="lt">'+esc(it.name)+'</div>'+
         '<div class="lu">'+esc(it.note||'压缩包 · 解压识别失败（原包保留）')+'</div></div>'+
         '<span class="missbadge">待识别</span></div>';
    } else {
      /* 需求 7：QQ 群文件暂未获取（url 为空）→ 「待获取」徽标 + 点击提示去群里查看 */
      h+='<div class="linkrow missing" data-act="filemiss" data-gid="'+g.id+'" data-idx="'+idx+'"><span class="ico">文件</span>'+
         '<div class="lb"><div class="lt">'+esc(it.name)+'</div>'+
         '<div class="lu">'+esc(it.note||'QQ 群文件 · 暂未获取')+'</div></div>'+
         '<span class="missbadge">待获取</span></div>';
    }
  } else if(it.kind==='form'){
    var fs=formInfo(g,it);
    h+='<div class="ai-mini"><span class="aitag">AI</span>识别</div>';
    h+='<div class="formrow"><span class="ico">表</span><div class="fb"><div class="ft">'+esc(disp(it.realTitle||it.name,it.time||cardAnchorTs(g)))+'</div>'+
       '<div class="fm">'+fs.label+' · '+(fs.close?'截止 '+esc(fmtDateText(fs.close)):'')+'</div></div>'+
       '<a class="go" href="'+esc(it.realUrl)+'" target="_blank" rel="noopener">打开</a></div>';
  } else if(it.kind==='img'){
    if(it.src){
      h+='<div class="imgrow" data-act="img" data-gid="'+g.id+'" data-idx="'+idx+'"><img src="'+it.src+'" alt=""></div>';
    } else if(it.lazy){
      /* 2026-11-18 列表轻量化：图片 data URI 在单行 body 里；2026-11-19 用户要求
         图片直接显示预览而不是点击才加载 → 由 IntersectionObserver 进入视口时自动
         拉取该卡完整 body，占位文案改成「图片预览加载中…」，点击仍保留兜底。 */
      h+='<div class="imgrow missing lazyimg" data-act="lazybody" data-lazyact="img" data-gid="'+g.id+'" data-idx="'+idx+'">'+
         '<div class="ib"><div class="it">'+esc(it.caption||'图片附件')+'</div>'+
         '<div class="ic">'+esc(it.note||'通知图片 · 预览加载中…')+'</div></div>'+
         '<span class="missbadge">预览加载中</span></div>';
    } else {
      /* 微信图片 V2 加密 / 未导出字节：保留附件条目，前端显示「待获取」 */
      h+='<div class="imgrow missing" data-act="filemiss" data-gid="'+g.id+'" data-idx="'+idx+'">'+
         '<div class="ib"><div class="it">'+esc(it.caption||'图片附件')+'</div>'+
         '<div class="ic">'+esc(it.note||'微信群图片 · 待获取')+'</div></div>'+
         '<span class="missbadge">待获取</span></div>';
    }
  } else if(it.kind==='link'){
    h+='<div class="linkrow"><span class="ico">链</span><div class="lb"><div class="lt">'+esc(disp(it.name,it.time||cardAnchorTs(g)))+'</div>'+
       '<div class="lu">'+esc(it.url)+'</div></div><a class="go" href="'+esc(it.url)+'" target="_blank" rel="noopener">打开</a></div>';
  } else if(it.kind==='mini'){
    h+='<div class="linkrow miniapp"><span class="ico">程</span><div class="lb"><div class="lt">'+esc(disp(it.name,it.time||cardAnchorTs(g)))+'</div>'+
       '<div class="lu">'+esc(it.note||'微信小程序')+'</div></div>'+
       (it.url?'<a class="go" href="'+esc(it.url)+'" target="_blank" rel="noopener">打开</a>':'<span class="go">小程序</span>')+'</div>';
  } else if(it.kind==='article'){
    h+='<div class="artrow"><div class="cover"><span>公众号</span></div><div class="ab"><div class="acc">'+esc(it.account)+'</div>'+
       '<div class="att">'+esc(disp(it.title,it.time||cardAnchorTs(g)))+'</div></div>'+
       '<a class="go" href="'+esc(it.url)+'" target="_blank" rel="noopener">打开</a></div>';
  }
  h+='</div>';return h;
}
/* 期次 key（gid@occ:YYYYMMDD）含 @/:，DOM id 安全化；data-gid 仍存真实 key */
function cardDomId(gid){return 'card-'+String(gid===null||gid===undefined?'':gid).replace(/[^A-Za-z0-9_-]/g,'_')}
function cardElOf(gid){return document.getElementById(cardDomId(gid))}
function groupHTML(g){
  var st=statusOf(g);
  var anchorTs=cardAnchorTs(g);
  var occ=!!g.__occ;
  var baseId=g.__baseId||g.id;
  var expired=(st.key==='expired'||st.key==='extended_past');
  var recur=!!(g.recurrence&&g.recurrence.freq);
  var done=!!state.done[g.id]||expired;
  var userDone=!!state.done[g.id];
  var fold=state.fold[g.id]===undefined?(expired&&!recur):state.fold[g.id];
  var updated=!!(g.updatedAt||g.supplement||state.edited[g.id]||state.override[g.id]);
  var h='<article id="'+cardDomId(g.id)+'" class="gcard cat-'+catClass(g.cat)+(occ?' occ':'')+(done?' expired':'')+(userDone&&!expired?' completed':'')+(fold?' folded':'')+'" data-gid="'+esc(g.id)+'">';
  var hasOriginal=(g.items||[]).some(function(it){return it.kind==='text'||it.kind==='follow'});
  h+='<div class="ghd"><span class="badge '+catClass(g.cat)+'">'+esc(g.cat)+'</span>'+
     (occ?'<span class="badge recur">长期安排</span>':'')+
     ((g.ocr||(g.items||[]).some(function(it){return it.ocr;}))?'<span class="badge ocr">OCR</span>':'')+
     '<span class="gright">'+
     (updated?'<span class="badge upd">已更新</span>':'')+
     '<span class="st '+st.cls+'">'+esc(fmtDateText(st.label))+'</span>'+
     (hasOriginal?'<button class="origbtn" data-act="original" data-gid="'+esc(g.id)+'">原始消息</button>':'')+
     (state.admin?'<span class="adminbar"><button class="actbtn" data-act="edit" data-gid="'+esc(baseId)+'">编辑</button><button class="actbtn danger" data-act="del" data-gid="'+esc(baseId)+'">删除</button></span>':'')+
     '</span></div>';
  h+='<h3 class="gtitle">'+esc(disp(g.title||'',anchorTs))+'</h3>';
  h+=srcLine(g);
  h+=pubLine(g);
  if(!occ)h+=recurLineHTML(g);
  if(g.aiSummary){
    h+='<div class="aibrief"><div class="aibrief-hd"><span class="aitag">AI</span>摘要</div><div class="aibrief-sum">'+esc(disp(g.aiSummary,anchorTs))+'</div>';
    if(g.aiPoints&&g.aiPoints.length) h+='<ul class="aipoints">'+g.aiPoints.map(function(p){return '<li>'+esc(disp(p,anchorTs))+'</li>'}).join('')+'</ul>';
    h+='</div>';
  }
  /* 契约 §0.3：有 AI 摘要的卡正文只放 AI 精简内容（摘要/要点/segments/附件/图片/链接/收集表），
     所有原始 text/follow（含补充通知原文）一律不内联，全部收进「原始消息」按钮；
     只有无 aiSummary 的历史卡才允许内联原文。 */
  var visibleItems;
  if(!g.aiSummary){
    visibleItems=(g.items||[]);
  }else{
    visibleItems=(g.items||[]).filter(function(it){return it.kind!=='text'&&it.kind!=='follow';});
  }
  var segs=compactSegments(g);
  var segHtml=segs.length?'<div class="seg-grid">'+segs.map(segmentHTML).join('')+'</div>':'';
  var inner='<div class="gtimeline">'+segHtml+visibleItems.map(function(it){return itemHTML(g,it,g.items.indexOf(it))}).join('')+'</div>';
  h+='<div class="gcollapse" style="max-height:'+(fold?'0px':'none')+'"><div class="gcinner">'+inner+'</div></div>';
  h+='<div class="gft"><span class="grow"></span>';
  if(occ){
    h+='<button class="donebtn" data-act="done" data-gid="'+esc(g.__occKey)+'" data-occ="1"><span class="b"></span>本次已处理</button>';
  }else if(!expired&&!recur){
    h+='<button class="donebtn'+(state.done[g.id]?' done':'')+'" data-act="done" data-gid="'+esc(g.id)+'"><span class="b"></span>标记已处理</button>';
  }
  h+='<button class="btn sm ghost" data-act="fold" data-gid="'+esc(g.id)+'">'+(fold?'展开':'收起')+'</button></div></article>';
  return h;
}
function isExpiredGroup(g){var k=statusOf(g).key;return k==='expired'||k==='extended_past';}
/* 2026-11-14 契约 §1.2/§1.3/§2：通知分类（长期安排定义 / 资料·无时间 / 时间明确主列表）。
   判据用「内在是否有时间锚点」，不用 statusOf().key==='none'（已处理会先返回 done）。 */
function hasTimeAnchor(g){
  if(!g)return false;
  if(deadlineOf(g))return true;
  if(g.eventAt)return true;
  if(g.signupStart||g.signupEnd)return true;
  if(Array.isArray(g.signupWindows)&&g.signupWindows.length)return true;
  return false;
}
function isRecurGroup(g){return !!(g&&g.recurrence&&g.recurrence.freq)}
function isInfoGroup(g){
  if(!g||isRecurGroup(g))return false;
  if(hasTimeAnchor(g))return false;
  /* 2026-11-18 契约 §3：有发布时间（publishedAt / 可推算）→ 发布卡进主列表，不再进资料栏 */
  if(publishedTsOf(g))return false;
  var k=statusOf(g).key;
  return !(k==='expired'||k==='extended_past'||k==='alert');
}
function isTimeGroup(g){
  if(!g||isRecurGroup(g))return false;
  /* 2026-11-18 契约 §3：无真实时间锚点但有发布时间 → 同样进主列表参与排序 */
  if(!hasTimeAnchor(g)&&!publishedTsOf(g))return false;
  return !isExpiredGroup(g);
}
/* 兼容旧名称：长期安排定义 + 资料/无时间（二者都不进主列表） */
function isLongtermGroup(g){
  if(!g)return false;
  if(isRecurGroup(g))return true;
  return isInfoGroup(g);
}
function longtermNextTs(g){
  var rec=g&&g.recurrence;
  if(!rec||!rec.freq)return Infinity;
  var d=recurNext(rec,nowMs());
  return d?d.getTime():Infinity;
}
function anchorTsOf(g){
  var d=_relAnchor(cardAnchorTs(g));
  return d?d.getTime():0;
}
/* 长期区排序（旧折叠区保留兼容；新 UI 用 longtermGroupsNow/资料栏） */
function orderLongterm(arr){
  return arr.slice().sort(function(a,b){
    var ra=(a.recurrence&&a.recurrence.freq)?0:1, rb=(b.recurrence&&b.recurrence.freq)?0:1;
    if(ra!==rb)return ra-rb;
    if(ra===0){var na=longtermNextTs(a),nb=longtermNextTs(b);if(na!==nb)return na-nb;}
    else{var ta=anchorTsOf(a),tb=anchorTsOf(b);if(ta!==tb)return tb-ta;}
    return GROUPS.indexOf(a)-GROUPS.indexOf(b);
  });
}
function renderLongterm(){/* 2026-11-14：旧长期折叠区已由「长期通知」筛选 + 资料栏替代，保留空实现 */ }
/* 资料 / 无时间栏（§1.2：非过期、无 recurrence、无任何时间锚点；默认展开） */
function infoGroups(){
  var hid=hiddenMap();
  return GROUPS.filter(function(g){
    if(hid[g.id])return false;
    if(state.cat!=='全部'&&g.cat!==state.cat)return false;
    return isInfoGroup(g);
  }).sort(function(a,b){
    var ta=anchorTsOf(a),tb=anchorTsOf(b);
    if(ta!==tb)return tb-ta;
    return GROUPS.indexOf(a)-GROUPS.indexOf(b);
  });
}
function renderData(list){
  var wrap=$('#dataWrap');if(!wrap)return;
  list=list||[];
  if(!list.length){wrap.style.display='none';wrap.classList.remove('open');return}
  wrap.style.display='block';
  $('#dataCount').textContent=list.length+' 条';
  $('#dataList').innerHTML=list.map(groupHTML).join('');
  wrap.classList.toggle('open',state.expandData!==false);
}
/* 长期安排清单（长期通知筛选视图：进行中安排，无期次卡、无已处理按钮） */
function longtermGroupsNow(now){
  now=(now===undefined||now===null)?nowMs():now;
  var hid=hiddenMap();
  return GROUPS.filter(function(g){
    if(hid[g.id])return false;
    if(state.cat!=='全部'&&g.cat!==state.cat)return false;
    return isRecurGroup(g)&&recurOngoing(g.recurrence,now);
  }).sort(function(a,b){
    var ta=longtermNextTs(a),tb=longtermNextTs(b);
    if(ta!==tb)return ta-tb;
    return GROUPS.indexOf(a)-GROUPS.indexOf(b);
  });
}
function longtermRowHTML(g){
  var next=recurNext(g.recurrence,nowMs());
  return '<div class="ltrow" data-gid="'+esc(g.id)+'">'+
    '<div class="ltrow-main"><div class="ltrow-t">'+esc(disp(g.title||'',cardAnchorTs(g)))+'</div>'+
    '<div class="ltrow-m"><span class="ltp">'+esc(recurPeriodText(g.recurrence))+'</span>'+
    (next?'<span class="ltn">下次 '+esc(recDateText(next))+'</span>':'')+'</div></div>'+
    '<span class="st recur">进行中</span></div>';
}
function longtermListHTML(now){
  var arr=longtermGroupsNow(now);
  if(!arr.length)return '<div class="lt-empty">暂无长期安排</div>';
  return '<div class="lt-view" id="longtermList">'+arr.map(longtermRowHTML).join('')+'</div>';
}
/* 最新发布：全部未隐藏通知按发布时间倒序（含已过期/资料/长期定义） */
function pubTsOf(g){
  var best=0;
  ['publishedAt','ts','updatedAt'].forEach(function(k){
    var v=g&&g[k];if(!v)return;
    var t=(typeof v==='number')?v:Date.parse(v);
    if(!isNaN(t)&&t>best)best=t;
  });
  function take(s){var d=_relAnchor(s);if(d&&d.getTime()>best)best=d.getTime();}
  (g.items||[]).forEach(function(it){
    if(!it)return;
    take(it.time);
    (it.messages||[]).forEach(function(m){take(m&&m.time)});
  });
  return best;
}
function relPubText(ts){
  if(!ts)return '—';
  var now=new Date(nowMs()),d=new Date(ts);
  if(isNaN(d.getTime()))return '—';
  var hm=pad(d.getHours())+':'+pad(d.getMinutes());
  var day0=new Date(now.getFullYear(),now.getMonth(),now.getDate()).getTime();
  var dd=new Date(d.getFullYear(),d.getMonth(),d.getDate()).getTime();
  var diff=Math.round((dd-day0)/86400000);
  if(diff===0)return '今天 '+hm;
  if(diff===-1)return '昨天 '+hm;
  return fmtDateText(pad(d.getMonth()+1)+'-'+pad(d.getDate()),nowMs())+' '+hm;
}
function latestGroups(){
  var hid=hiddenMap();
  var arr=GROUPS.filter(function(g){return !hid[g.id]&&(state.cat==='全部'||g.cat===state.cat)});
  arr.sort(function(a,b){
    var ta=pubTsOf(a),tb=pubTsOf(b);
    if(ta!==tb)return tb-ta;
    return GROUPS.indexOf(a)-GROUPS.indexOf(b);
  });
  return arr;
}
function orderRank(st,g){
  if(state.done[g.id]||st.key==='done') return 9;
  if(g&&g.__occ) return 1;   /* 期次卡按 next 参与主列表排序（相当于今天/24h 内档） */
  if(g&&g.recurrence&&g.recurrence.freq) return 5;
  if(st.key==='alert') return 0;
  if(st.key==='urgent'||st.key==='today') return 1;
  if(st.key==='extended') return 2;
  if(st.key==='soon'||st.key==='active') return 3;
  if(st.key==='none') return 4;
  if(st.key==='published') return 4;   /* 2026-11-18 契约 §4：发布卡排 active 之后，档内按发布时间倒序 */
  if(st.key==='extended_past') return 7;
  if(st.key==='expired') return 8;
  return 5;
}
function orderGroups(arr){
  return arr.slice().sort(function(a,b){
    var ra=orderRank(statusOf(a),a), rb=orderRank(statusOf(b),b);
    if(ra!==rb) return ra-rb;
    var da=expireOf(a), db=expireOf(b);
    if(ra===4){
      /* 2026-11-18 契约 §4：发布卡按发布时间倒序（新的在上）；无发布时间的 none 兜底排最后 */
      var pa=publishedTsOf(a), pb=publishedTsOf(b);
      if(pa&&pb) return pb-pa;
      if(pa) return -1;
      if(pb) return 1;
    } else if(ra>=7){
      if(da&&db) return db-da;
      if(da) return -1;
      if(db) return 1;
    } else if(ra>=1 && ra<=4){
      if(da&&db) return da-db;
      if(da) return -1;
      if(db) return 1;
    }
    return GROUPS.indexOf(a)-GROUPS.indexOf(b);
  });
}
function filtered(){
  var hid=hiddenMap();
  var arr=GROUPS.filter(function(g){
    var st=statusOf(g);
    if(hid[g.id]) return false;
    if(state.cat!=='全部'&&g.cat!==state.cat) return false;
    if(state.sub==='todo'&&(st.key==='expired'||st.key==='extended_past'||isLongtermGroup(g)||state.done[g.id]||st.key==='done')) return false;
    if(state.sub==='expired'&&!(st.key==='expired'||st.key==='extended_past')) return false;
    if(state.sub==='extended'&&!(g.extensions&&g.extensions.length)) return false;
    if(state.sub==='alert'&&!g.alert) return false;
    return true;
  });
  return orderGroups(arr);
}
/* 卡片主显示时间（24h / 7 天内统计口径，与 statusOf 优先级一致） */
function primaryWhenTs(g,now){
  if(g&&g.__occ)return g.__occTs;
  now=(now===undefined||now===null)?nowMs():now;
  var wins=Array.isArray(g.signupWindows)?g.signupWindows:[];
  if(wins.length){
    var curW=null,nextW=null;
    for(var wi=0;wi<wins.length;wi++){
      var w=wins[wi]||{};
      var ws=w.start?Date.parse(w.start):null, we=w.end?Date.parse(w.end):null;
      if((!ws||now>=ws)&&(!we||now<=we)){curW={s:ws,e:we};break;}
      if(ws&&now<ws&&(!nextW||ws<nextW.s))nextW={s:ws,e:we};
    }
    var pick=curW||nextW;
    if(pick){if(pick.s&&now<pick.s)return pick.s;if(pick.e&&now<pick.e)return pick.e;}
  }
  var ss=g.signupStart?Date.parse(g.signupStart):0,se=g.signupEnd?Date.parse(g.signupEnd):0;
  if(ss&&now<ss)return ss;
  if(se&&now<se)return se;
  var real=deadlineOf(g);
  if(real)return real;
  if(g.eventAt)return Date.parse(g.eventAt);
  return 0;
}
/* 待处理（§2.4）：未过期、非长期定义、非资料/无时间、未已处理、actionable!==false、有时间锚点 */
function pendingOrdGroups(){
  var hid=hiddenMap();
  return GROUPS.filter(function(g){
    if(hid[g.id]) return false;
    if(g.actionable===false) return false;
    if(!isTimeGroup(g)) return false;
    if(state.done[g.id]) return false;
    var st=statusOf(g);
    return st.key!=='done'&&st.key!=='expired'&&st.key!=='extended_past';
  });
}
function pendingGroups(){return pendingOrdGroups()}   /* 兼容旧接口：普通待处理（不含期次） */
function pendingAll(now){return pendingOrdGroups().concat(occurrences(now))}
function groupsByCard(kind,now){
  var pend=pendingAll(now);
  if(kind==='24h'||kind==='7d'){
    var lim=(kind==='24h')?24*3600*1000:7*86400000;
    pend=pend.filter(function(g){
      var t=primaryWhenTs(g,now);
      if(!t||t<now)return false;
      return (t-now)<=lim;
    });
  }
  return orderGroups(pend);
}
function briefNext(){
  var arr=pendingAll().slice().sort(function(a,b){
    var ad=primaryWhenTs(a),bd=primaryWhenTs(b);
    if(!!a.alert!==!!b.alert) return a.alert?-1:1;
    if(ad&&bd) return ad-bd;
    if(ad) return -1;
    if(bd) return 1;
    return 0;
  }).slice(0,3);
  if(!arr.length){$('#briefNext').innerHTML='<div class="bn-empty">暂无待处理通知</div>';return}
  $('#briefNext').innerHTML=arr.map(function(g){
    /* 契约 §2.3：简报「最近截止」与卡片 chip 同口径（时间+动作）；期次卡显示「本次」 */
    var st=statusOf(g);
    var meta=g.__occ?('本次 '+recDateText(g.__occNext)):(g.alert?'待确认名单':(st.key==='none'?'无时间':st.label));
    return '<button class="bn-row'+(g.alert?' alert':'')+'" data-act="jump" data-gid="'+esc(g.id)+'">'+
      '<span class="bn-title">'+esc(disp(g.title||'',cardAnchorTs(g)))+'</span><span class="bn-meta">'+esc(fmtDateText(meta))+'</span></button>';
  }).join('');
}
function stats(){
  var now=nowMs();
  var pend=pendingAll(now);
  var urgent=0,week=0;
  pend.forEach(function(g){
    var t=primaryWhenTs(g,now);
    if(t&&t>=now){
      var left=t-now;
      if(left<=24*3600*1000)urgent++;
      if(left<=7*86400000)week++;
    }
  });
  var recur=0;
  GROUPS.forEach(function(g){if(g&&g.recurrence&&g.recurrence.freq&&recurOngoing(g.recurrence,now))recur++;});
  var latest=null;
  GROUPS.forEach(function(g){var ts=pubTsOf(g);if(ts&&(!latest||ts>latest.ts))latest={ts:ts,g:g};});
  $('#statOpen').textContent=pend.length;
  $('#statUrgent').textContent=urgent;
  $('#statWeek').textContent=week;
  $('#statRecur').textContent=recur;
  var sl=$('#statLatest');
  if(sl){sl.textContent=latest?relPubText(latest.ts):'—';sl.title=latest?('最新发布 · '+String(latest.g.title||'')):'暂无通知';}
  $('#briefChip').textContent=pend.length?pend.length+' 项待处理':'无待处理';
  var d=new Date(now);$('#briefDate').textContent=(d.getMonth()+1)+' 月 '+d.getDate()+' 日 '+pad(d.getHours())+':'+pad(d.getMinutes());
  briefNext();
}
function splitColumns(arr){
  var left=[],right=[],lh=0,rh=0;
  arr.forEach(function(g,i){
    var weight=70;
    (g.items||[]).forEach(function(it){
      if(it.kind==='img') weight+=150;
      else if(it.kind==='file') weight+=64;
      else if(it.kind==='text') weight+=42+Math.min(5,(it.text||'').length/90)*18;
      else weight+=46;
    });
    if(g.aiPoints) weight+=g.aiPoints.length*10;
    if(i===0){left.push(g);lh+=weight}
    else if(i===1){right.push(g);rh+=weight}
    else if(lh<=rh){left.push(g);lh+=weight}
    else{right.push(g);rh+=weight}
  });
  return [left,right];
}
function renderExpired(mode){
  var hid=hiddenMap();
  var arr=GROUPS.filter(function(g){
    if(hid[g.id]) return false;
    if(!isExpiredGroup(g)) return false;
    if(state.cat!=='全部'&&g.cat!==state.cat) return false;
    return true;
  });
  var wrap=$('#expiredWrap');
  if(mode==='hide'||!arr.length){wrap.style.display='none';return}
  wrap.style.display='block';
  $('#expiredCount').textContent=arr.length+' 组';
  $('#expiredList').innerHTML=arr.map(groupHTML).join('');
  wrap.classList.toggle('open',state.sub==='expired'||!!state.expandExpired);
}
function renderHidden(){
  var wrap=$('#hiddenWrap');
  if(!wrap)return;
  var list=(state.admin&&state.hidden)?state.hidden:[];
  if(!list.length){wrap.style.display='none';return}
  wrap.style.display='block';
  $('#hiddenCount').textContent=list.length+' 条';
  $('#hiddenList').innerHTML=list.map(function(x){
    return '<div class="hidden-row"><span class="ht">'+esc(x.title||'（无标题）')+'</span>'+
      '<span class="hid">'+esc(x.gid||'')+'</span>'+
      '<button class="copybtn" data-act="restore" data-gid="'+esc(x.gid||'')+'">恢复</button></div>';
  }).join('');
  wrap.classList.toggle('open',!!state.hiddenOpen);
}
function noticeSig(){
  var parts=[];
  for(var i=0;i<GROUPS.length;i++){
    var g=GROUPS[i],st=statusOf(g);
    parts.push(g.id+':'+st.key+':'+(state.done[g.id]?1:0)+':'+(g.updatedAt||'')+
      ':'+(g.title||'').length+':'+(g.aiSummary||'').length+':'+(g.recurrence?'r':'-')+':'+(g.cat||''));
  }
  return parts.join('|')+(state.admin?'|A':'')+'|'+((state.hidden||[]).map(function(x){return x.gid}).join(','));
}
function renderDataCardBar(){
  $$('#dataBar .bstat').forEach(function(b){b.classList.toggle('on',b.getAttribute('data-card')===state.card)});
}
function renderList(arr,animate){
  var empty='<div class="card" style="text-align:center;color:var(--ink3);font-size:12.5px;padding:26px">没有符合条件的通知</div>';
  if(!arr.length){
    $('#list').className='';
    $('#list').innerHTML=empty;
  } else if(window.innerWidth>=960 && arr.length>=4){
    var cols=splitColumns(arr);
    $('#list').className='two';
    $('#list').innerHTML='<div class="listcol">'+cols[0].map(groupHTML).join('')+'</div>'+
      '<div class="listcol">'+cols[1].map(groupHTML).join('')+'</div>';
  } else {
    $('#list').className='';
    $('#list').innerHTML=arr.map(groupHTML).join('');
  }
  if(animate){
    /* 需求 13：列表入场动画（错峰，最多 12 个一组；reduced-motion 由 CSS 关闭） */
    $$('#list .gcard').forEach(function(c,i){
      try{c.style.setProperty('--i',String(i%12));}catch(e){}
      c.classList.add('enter');
    });
  }
}
function render(opts){
  var animate=!(opts&&opts.animate===false);
  renderCatChips();
  var now=nowMs();
  var mode='default';
  if(state.card==='longterm')mode='longterm';
  else if(state.card==='latest')mode='latest';
  else if(state.card==='pending'||state.card==='24h'||state.card==='7d')mode='card';
  else if(state.sub==='todo')mode='card';
  else if(state.sub==='expired')mode='expired';
  if(mode==='longterm'){
    var larr=longtermGroupsNow(now);
    $('#list').className='';
    $('#list').innerHTML=longtermListHTML(now);
    $('#listCount').textContent=larr.length+' 组';
    renderData([]);renderExpired('hide');
  }else if(mode==='latest'){
    var lates=latestGroups();
    renderList(lates,animate);
    $('#listCount').textContent=lates.length+' 组';
    renderData([]);renderExpired('hide');
  }else if(mode==='expired'){
    $('#list').className='';
    $('#list').innerHTML='';
    $('#listCount').textContent='0 组';
    renderData([]);renderExpired('show');
  }else if(mode==='card'){
    var kind=state.card||'pending';
    var carr=groupsByCard(kind,now);
    renderList(carr,animate);
    $('#listCount').textContent=carr.length+' 组';
    renderData([]);renderExpired();
  }else{
    /* 全部视图：主列表（普通时间明确通知 + 期次卡）→ 资料/无时间栏 → 已过期区 */
    var hid=hiddenMap();
    var arr=[];
    GROUPS.forEach(function(g){
      if(hid[g.id])return;
      if(state.cat!=='全部'&&g.cat!==state.cat)return;
      if(isTimeGroup(g))arr.push(g);
    });
    occurrences(now).forEach(function(c){
      if(state.cat==='全部'||c.cat===state.cat)arr.push(c);
    });
    arr=orderGroups(arr);
    renderList(arr,animate);
    $('#listCount').textContent=arr.length+' 组';
    renderData(infoGroups());
    renderExpired();
  }
  stats();
  renderDataCardBar();
  /* chips 激活态与 5 卡互斥（选中卡时 chips 全不选；取消后回到当前 sub） */
  $$('#subRow .chipf').forEach(function(b){
    b.classList.toggle('on',!state.card&&(b.getAttribute('data-sub')||'全部')===state.sub);
  });
  renderHidden();
  try{autoPreviewImages();}catch(e){}
  RENDER_SIG=noticeSig();
}
/* 弹层：嵌入网页时交给父页面渲染（父页磨砂暗层 + 原页面背景），单独打开时用内置弹层。 */
function presentModal(inner){
  if(window.parent&&window.parent!==window){
    try{parent.postMessage({type:'class-notice-modal-open',html:inner},'*');return;}catch(e){}
  }
  $('#mcard').innerHTML='<button class="mclose" onclick="closeModal()">×</button>'+inner;
  $('#modal').classList.add('on');
}
function closeModal(){
  $('#modal').classList.remove('on');
  if(window.parent&&window.parent!==window){try{parent.postMessage({type:'class-notice-modal-close'},'*');}catch(e){}}
}
function openImg(gid,idx){
  var g=GROUPS.filter(function(x){return x.id===gid})[0];var it=g.items[idx];
  presentModal('<img src="'+it.src+'"><div style="font-size:12px;color:var(--ink3);margin-top:8px;text-align:center">'+esc(disp(it.caption||'',it.time||cardAnchorTs(g)))+'</div>');
}
function openFile(gid,idx){
  var g=findGroup(gid);if(!g)return;var it=(g.items||[])[idx];if(!it)return;
  var url=it.url||'',mime=fileMime(it,url),body='';
  if(/^image\//.test(mime)) body='<img src="'+esc(url)+'" alt="">';
  else if(mime==='application/pdf') body='<iframe src="'+esc(url)+'"></iframe>';
  else if(url&&!mime&&!isHttpUrl(url)) body='<iframe src="'+esc(url)+'"></iframe>';
  else if(isHttpUrl(url)) body='<div class="missbox">附件'+(it.size?' · '+esc(it.size):'')+'，点击下方按钮下载后打开。</div>';
  else body='<div class="missbox">文件已就绪（'+esc(mime||'附件')+' · '+esc(fmtBytes(dataUriBytes(url)))+'），点击下方按钮下载后打开。</div>';
  var act=url?'<div class="mact"><a class="go" href="'+esc(url)+'" download="'+esc(it.name||'file')+'">下载原文件</a></div>':'';
  presentModal('<div class="mhead">'+esc(it.name||'文件')+'</div>'+body+act);
}
function openFileMissing(gid,idx){
  var g=findGroup(gid);if(!g)return;var it=(g.items||[])[idx]||{};
  var groupName=g.group||g.source||'QQ 群';
  var enc='';
  try{enc=encodeURIComponent(groupName)}catch(e){enc=groupName}
  presentModal('<div class="mhead">'+esc(it.name||'文件')+'</div>'+
    '<div class="missbox">该文件暂未获取，请前往 QQ 群「'+esc(groupName)+'」查看；下载后会自动上线。</div>'+
    '<div class="missgroup"><span>群名</span><b>'+esc(groupName)+'</b>'+
    '<button class="copybtn" data-act="copyname" data-name="'+esc(enc)+'">复制群名</button></div>');
}
/* 2026-11-18 列表轻量化：lite 列表里图片/附件/包内文件的字节在单行 body 中，
   点击后由父页拉完整 body，再调 __zqHydrate 打开。 */
function lazyBody(gid,idx,act){
  if(window.parent&&window.parent!==window){
    try{window.parent.postMessage({type:'class-notice-need-body',gid:gid,idx:idx||0,act:act||''},'*');return;}catch(e){}
  }
  toast('请稍后重试');
}
function __zqHydrate(gid,group,idx,act){
  if(!group)return;
  var base=String(gid||'').split('@occ:')[0],target=null;
  for(var i=0;i<GROUPS.length;i++){
    if(GROUPS[i].id===gid||GROUPS[i].__baseId===gid||GROUPS[i].id===base){target=GROUPS[i];break;}
  }
  if(target){
    /* 期次卡只替换附件数据，保留 __occ/期次时间等字段；基础组直接更新 items。 */
    target.items=group.items;
    if(group.attachments!==undefined)target.attachments=group.attachments;
    target.__full=true;
  }else{
    target=group;GROUPS.push(target);
  }
  if(act==='img'){openImg(gid,idx);return;}
  if(act==='preview'){openFile(gid,idx);return;}
  /* archive / 其它：重渲染让刚加载的下载链接出现，并保持滚动位置 */
  var y=0;try{y=window.scrollY||window.pageYOffset||0;}catch(e){}
  render();
  try{window.scrollTo(0,y);}catch(e){}
}
try{window.__zqHydrate=__zqHydrate;}catch(e){}

/* 图片预览自动加载（2026-11-19 用户要求）：lite 列表只为图片保留了 lazy 占位，
   进入视口就向父页请求该卡完整 body，回填后直接显示图片；不必再点「点击加载」。
   每张卡只请求一次，最多自动回填 18 张卡；超出/失败的仍可手动点击。 */
var AUTO_PREVIEW={io:null,n:0,max:18};
function autoPreviewImages(){
  try{
    var nodes=[].slice.call(document.querySelectorAll('.imgrow.lazyimg[data-gid]'));
    if(!nodes.length){if(AUTO_PREVIEW.io){AUTO_PREVIEW.io.disconnect();AUTO_PREVIEW.io=null;}return;}
    function request(el){
      if(!el||el.getAttribute('data-autoload')==='1'||AUTO_PREVIEW.n>=AUTO_PREVIEW.max)return;
      el.setAttribute('data-autoload','1');AUTO_PREVIEW.n++;
      lazyBody(el.getAttribute('data-gid'),Number(el.getAttribute('data-idx'))||0,'inline');
    }
    if(!('IntersectionObserver' in window)){
      var vh=window.innerHeight||document.documentElement.clientHeight||800,todo=[];
      nodes.forEach(function(el){var r=el.getBoundingClientRect();if(r.top<vh+180&&r.bottom>-180)todo.push(el);});
      todo.slice(0,2).forEach(request);
      return;
    }
    if(AUTO_PREVIEW.io)AUTO_PREVIEW.io.disconnect();
    AUTO_PREVIEW.io=new IntersectionObserver(function(entries){
      entries.forEach(function(en){if(en.isIntersecting){request(en.target);try{AUTO_PREVIEW.io.unobserve(en.target);}catch(e){}}});
    },{root:null,rootMargin:'200px 0px',threshold:0.01});
    nodes.forEach(function(el){if(el.getAttribute('data-autoload')!=='1')AUTO_PREVIEW.io.observe(el);});
  }catch(e){}
}
function copyText(text){  function fallback(){
    try{
      var ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';
      document.body.appendChild(ta);ta.focus();ta.select();
      var ok=document.execCommand('copy');document.body.removeChild(ta);return ok;
    }catch(e){return false}
  }
  try{
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(function(){toast('已复制群名')},function(){toast(fallback()?'已复制群名':'复制失败，请手动记录')});
      return;
    }
  }catch(e){}
  toast(fallback()?'已复制群名':'复制失败，请手动记录');
}
/* 需求 13：卡片展开/收起用高度过渡（不重渲染整页，不靠定时器轮询） */
function setFoldCard(gid,folded){
  state.fold[gid]=folded;
  var card=cardElOf(gid);
  if(!card){render({animate:false});return}
  var box=card.querySelector('.gcollapse');
  var btn=card.querySelector('[data-act="fold"]');
  if(!box){render({animate:false});return}
  var h=box.scrollHeight;
  card.classList.toggle('folded',folded);
  if(folded){
    box.style.maxHeight=h+'px';
    void box.offsetHeight;
    box.style.maxHeight='0px';
  }else{
    box.style.maxHeight='0px';
    void box.offsetHeight;
    box.style.maxHeight=h+'px';
  }
  if(btn)btn.textContent=folded?'展开':'收起';
  var done=function(){
    box.style.maxHeight=folded?'0px':'none';
    box.removeEventListener('transitionend',onEnd);
    if(box.__foldTimer){clearTimeout(box.__foldTimer);box.__foldTimer=null;}
    if(typeof window.__noticeHeight==='function'){try{window.__noticeHeight();}catch(e){}}
  };
  var onEnd=function(ev){if(ev.target===box&&ev.propertyName==='max-height')done();};
  box.addEventListener('transitionend',onEnd);
  if(box.__foldTimer)clearTimeout(box.__foldTimer);
  box.__foldTimer=setTimeout(done,400);
}
/* 需求 12：管理员编辑 / 删除 / 恢复（模板只发消息，数据套用由父页/小程序完成） */
function openEdit(gid){
  var g=findGroup(gid);if(!g)return;
  var cats=catList();
  if(cats.indexOf(g.cat)<0&&g.cat) cats.unshift(g.cat);
  var h='<h4>编辑通知</h4><div class="edhint">保存后由页面写入云端；采集重建不会覆盖管理员编辑。</div><div class="edgrid">';
  h+='<label class="wide">标题<input id="edTitle" value="'+esc(g.title||'')+'"></label>';
  h+='<label>分类<select id="edCat">'+cats.map(function(c){return '<option'+(c===g.cat?' selected':'')+'>'+esc(c)+'</option>'}).join('')+'</select></label>';
  h+='<label>时间文案<input id="edTimeLabel" value="'+esc(g.timeLabel||'')+'" placeholder="如：报名 11-07 12:00"></label>';
  h+='<label>截止时间<input id="edDeadline" type="datetime-local" value="'+esc(isoToLocalInput(g.deadline))+'"></label>';
  h+='<label>活动时间<input id="edEventAt" type="datetime-local" value="'+esc(isoToLocalInput(g.eventAt))+'"></label>';
  h+='<label>失效时间<input id="edExpireAt" type="datetime-local" value="'+esc(isoToLocalInput(g.expireAt))+'"></label>';
  h+='<label class="wide">摘要<textarea id="edSummary">'+esc(g.summary||'')+'</textarea></label>';
  h+='<label class="wide">AI 摘要<textarea id="edAiSummary">'+esc(g.aiSummary||'')+'</textarea></label>';
  h+='</div><div class="edact"><button class="btn ghost sm" data-act="edcancel">取消</button><button class="btn pri sm" data-act="edsave" data-gid="'+g.id+'">保存</button></div>';
  $('#editCard').innerHTML=h;
  $('#editMask').classList.add('on');
}
function closeEdit(){var m=$('#editMask');if(m)m.classList.remove('on');}
function saveEdit(gid){
  var g=findGroup(gid);if(!g)return;
  function val(id){var el=document.getElementById(id);return el?String(el.value||'').trim():''}
  var fields={
    title:val('edTitle'), cat:val('edCat'), summary:val('edSummary'), aiSummary:val('edAiSummary'),
    deadline:localInputToIso(val('edDeadline'))||null,
    eventAt:localInputToIso(val('edEventAt'))||null,
    expireAt:localInputToIso(val('edExpireAt'))||null,
    timeLabel:val('edTimeLabel')
  };
  if(!fields.title){toast('标题不能为空');return}
  closeEdit();
  if(hasParentFrame()){
    postParent({type:'class-notice-edit',gid:gid,fields:fields});
    toast('已提交，等待云端确认…');
  }else{
    applyOverrideLocal(gid,fields);render({animate:false});toast('已更新（本地演示）');
  }
}
function doDelete(gid){
  var g=findGroup(gid);if(!g)return;
  if(hasParentFrame()){
    /* 父页模式：直接发消息，由父页确认并写云端（模板不做二次确认，避免 iframe 阻塞） */
    postParent({type:'class-notice-hide',gid:gid});toast('已请求隐藏…');return;
  }
  if(!window.confirm('隐藏这条通知？采集重建后也不会自动恢复（管理员可恢复）。'))return;
  state.hidden=(state.hidden||[]);state.hidden.push({gid:gid,title:g.title});
  render({animate:false});toast('已隐藏（本地演示）');
}
function doRestore(gid){
  if(hasParentFrame()){postParent({type:'class-notice-restore',gid:gid});toast('已请求恢复…');}
  else{
    state.hidden=(state.hidden||[]).filter(function(x){return x.gid!==gid});
    render({animate:false});toast('已恢复（本地演示）');
  }
}
function openOriginal(gid){
  var g=GROUPS.filter(function(x){return x.id===gid})[0];if(!g)return;
  var texts=g.items.filter(function(it){return it.kind==='text'||it.kind==='follow'});
  var h='<div class="mhead">原始消息</div><div class="orig-meta">'+esc(g.source||g.group||'班级通知')+'</div>';
  if(!texts.length){h+='<div class="orig-empty">没有可显示的原始文字。</div>'}
  texts.forEach(function(it){
    var ty=itemType(g,it),paras=splitNotice(disp(it.text,it.time||cardAnchorTs(g)));
    h+='<div class="orig-item"><div class="orig-head"><span class="gi-type '+ty.cls+'">'+esc(ty.label)+'</span><span class="gi-time">'+esc(it.time||'')+'</span></div><div class="orig-body">'+
      paras.map(function(p){return '<p>'+esc(p)+'</p>'}).join('')+'</div></div>';
  });
  presentModal(h);
}
function hwStatus(h){
  if(h.fixedStatus) return {k:'fixed',label:h.fixedStatus,cls:'none'};
  if(h.due){
    var due=Date.parse(h.due);
    if(Date.now()>due) return {k:'expired',label:'已截止',cls:'expired'};
    return {k:'open',label:'待完成',cls:'active'};
  }
  return {k:'open',label:'待完成',cls:'none'};
}
function hwCard(h){
  var st=hwStatus(h);
  var dueTxt=h.due?fmt(Date.parse(h.due))+' 截止':'无截止';
  var h2='<article class="hwcard'+(st.k==='expired'?' done':'')+'"><div class="hwh"><span class="badge hd">'+esc(h.course)+'</span>'+
         '<span class="st '+st.cls+'">'+esc(st.label)+'</span></div>'+
         '<div class="hwtitle">'+esc(h.title)+'</div><div class="hwnote">'+esc(h.note)+'</div>'+
         '<div class="hwmeta"><b>来源</b> '+esc(h.group)+' · <b>截止</b> '+dueTxt+'</div>';
  if(h.docUrl) h2+='<div class="hwac"><a class="hwlink" href="'+esc(h.docUrl)+'" target="_blank" rel="noopener">打开腾讯文档</a></div>';
  return h2+'</article>';
}
function renderHw(){
  var arr=HOMEWORK.filter(function(h){
    var st=hwStatus(h);
    if(state.hw==='todo') return st.k!=='expired';
    if(state.hw==='expired') return st.k==='expired';
    return true;
  });
  $('#hwList').innerHTML=arr.length?arr.map(hwCard).join(''):'<div class="hwempty">没有符合条件的作业</div>';
  $('#hwCount').textContent=arr.length+' 项';
}
function renderSchedule(){
  var days=['周一','周二'];
  var html='<table class="ttbl"><thead><tr><th>节次</th>'+days.map(function(d){return '<th>'+d+'</th>'}).join('')+'</tr></thead><tbody>';
  ['1-3','6-8','8-9'].forEach(function(p){
    html+='<tr><td>'+p+'</td>';
    days.forEach(function(d){
      var items=SCHEDULE.filter(function(s){return s.day===d&&s.periods===p});
      html+='<td>'+(items.length?items.map(function(s){return '<span class="tc">'+esc(s.course)+'</span><span class="tn">'+esc(s.room)+(s.note?' · '+esc(s.note):'')+'</span>'}).join(''):'—')+'</td>';
    });
    html+='</tr>';
  });
  html+='</tbody></table><div class="ttnote">仅列出近 7 天通知涉及的课次；其余课程以「今日校园」为准。AI 按课表把太极拳 10/31 补测与 11/02 周一 8-9 节拆成了两条通知。</div>';
  $('#ttBody').innerHTML=html;
}
function tabsThumb(anim){
  var bar=document.getElementById('tabs'); if(!bar)return;
  var btn=bar.querySelector('button.on'); if(!btn)return;
  var th=bar.querySelector('.tabs-thumb');
  if(!th){th=document.createElement('span');th.className='tabs-thumb';bar.appendChild(th);}
  var br=bar.getBoundingClientRect(), tr=btn.getBoundingClientRect();
  th.style.transition=anim?'transform .3s cubic-bezier(.18,1.2,.35,1),width .3s ease':'none';
  th.style.width=tr.width+'px'; th.style.height=tr.height+'px';
  th.style.transform='translate('+(tr.left-br.left)+'px,'+(tr.top-br.top)+'px)';
}
/* 2026-11-14 契约 §2.1：顶部 5 卡点击筛选（再点取消；与下方 chips 互斥） */
function setDataCard(kind){
  state.card=(state.card===kind)?'':kind;
  if(state.card)state.sub='全部';
  render({animate:false});
}
document.addEventListener('click',function(e){
  var el=e.target.closest('[data-act]');
  if(el){
    var act=el.getAttribute('data-act'),gid=el.getAttribute('data-gid'),idx=+el.getAttribute('data-idx');
    if(act==='more'){var body=document.getElementById('b-'+gid+'-'+idx);if(body){var q=body.querySelector('.quote');if(q)q.classList.toggle('open');el.textContent=q&&q.classList.contains('open')?'收起原文':'展开原文'}return;}
    if(act==='fold'){
      var fc=cardElOf(gid);
      setFoldCard(gid,!(fc&&fc.classList.contains('folded')));
      return;
    }
    if(act==='done'){
      var isOcc=!!el.getAttribute('data-occ');
      state.done[gid]=!state.done[gid];
      render({animate:false});
      var dmsg=isOcc?(state.done[gid]?'本期已处理':'已恢复为待处理'):(state.done[gid]?'已标记为已处理':'已恢复为待处理');
      toast(dmsg);
      /* 嵌入模式：父页 noticeToastBridge 的 window 作用域缺陷会吞掉模板 toast；
         期次「本期已处理」按契约 §2.3 显式转发一次给父页（source=iframe，父页校验可通过）。 */
      if(isOcc&&hasParentFrame())postParent({type:'class-notice-toast',msg:dmsg});
      return;
    }
    if(act==='expired-toggle'){state.expandExpired=!state.expandExpired;renderExpired();return;}
    if(act==='data-toggle'){state.expandData=state.expandData===false;renderData(infoGroups());return;}
    if(act==='hidden-toggle'){state.hiddenOpen=!state.hiddenOpen;renderHidden();return;}
    if(act==='jump'){
      state.card='';state.sub='全部';state.cat='全部';
      $$('#subRow .chipf').forEach(function(b){b.classList.toggle('on',b.getAttribute('data-sub')==='全部')});
      render({animate:false});
      var card=cardElOf(gid);
      if(card){card.scrollIntoView({block:'center'});card.classList.add('flash');setTimeout(function(){card.classList.remove('flash')},1600)}
      return;
    }
    if(act==='lazybody'){lazyBody(gid,idx,el.getAttribute('data-lazyact')||'');return;}
    if(act==='img'){openImg(gid,idx);return;}
    if(act==='preview'){openFile(gid,idx);return;}
    if(act==='original'){openOriginal(gid);return;}
    if(act==='filemiss'){openFileMissing(gid,idx);return;}
    if(act==='copyname'){
      var nm='';try{nm=decodeURIComponent(el.getAttribute('data-name')||'')}catch(err){nm=el.getAttribute('data-name')||''}
      copyText(nm);return;
    }
    if(act==='edit'){openEdit(gid);return;}
    if(act==='del'){doDelete(gid);return;}
    if(act==='restore'){doRestore(gid);return;}
    if(act==='edcancel'){closeEdit();return;}
    if(act==='edsave'){saveEdit(gid);return;}
  }
  var dc=e.target.closest('[data-card]');
  if(dc){setDataCard(dc.getAttribute('data-card'));return;}
  if(e.target.id==='modal'){e.target.classList.remove('on');return;}
  if(e.target.id==='editMask'){closeEdit();return;}
  var hf=e.target.closest('#hwRow .chipf');
  if(hf){
    state.hw=hf.getAttribute('data-hw');
    $$('#hwRow .chipf').forEach(function(b){b.classList.toggle('on',b===hf)});
    renderHw();return;
  }
  var cf=e.target.closest('.chipf');
  if(cf){
    if(cf.hasAttribute('data-cat')){state.cat=cf.getAttribute('data-cat');$$('#catRow .chipf').forEach(function(b){b.classList.toggle('on',b===cf)});}
    else{state.sub=cf.getAttribute('data-sub');state.card='';$$('#subRow .chipf').forEach(function(b){b.classList.toggle('on',b===cf)});}
    render();return;
  }
  var tb=e.target.closest('#tabs button');
  if(tb){var tab=tb.getAttribute('data-tab');$$('#tabs button').forEach(function(b){b.classList.toggle('on',b===tb)});$$('section').forEach(function(s){s.classList.remove('on')});
    if(tab==='nt'){$('#s-nt').classList.add('on')}
    else if(tab==='hw'){$('#s-hw').classList.add('on');renderHw()}
    else if(tab==='tt'){$('#s-tt').classList.add('on');renderSchedule()}
    else{$('#s-other').classList.add('on');$('#phTitle').textContent=tb.textContent}
    tabsThumb(true);return;}
});
$('#refreshBtn').addEventListener('click',function(){render();toast('已刷新')});
render();
/* 定时刷新：只在状态真的变化时重渲染（避免每分钟重放动画/打断滚动与展开） */
setInterval(function(){
  try{ if(noticeSig()!==RENDER_SIG) render({animate:false}); }catch(e){}
},60000);
var wasWide=window.innerWidth>=960;
window.addEventListener('resize',function(){var w=window.innerWidth>=960;if(w!==wasWide){wasWide=w;render({animate:false});}tabsThumb(false);});
/* ---------- v2.0.0：父页 ↔ iframe 契约（plan §3.1） ---------- */
window.__zqSetAdmin=function(on){
  state.admin=!!on;
  if(!on)state.hidden=[];
  render({animate:false});
};
window.__zqSetHidden=function(list){
  var arr=[];
  (list||[]).forEach(function(x){
    if(!x)return;
    if(typeof x==='string')arr.push({gid:x,title:''});
    else if(x.gid)arr.push({gid:String(x.gid),title:x.title||''});
  });
  state.hidden=arr;
  render({animate:false});
};
window.__zqApplyOverride=function(gid,obj){
  if(!gid||!obj)return;
  applyOverrideLocal(String(gid),obj);
  render({animate:false});
};
window.__zqSetScroll=function(y){try{window.scrollTo(0,Number(y)||0);}catch(e){}};
/* 供父页调试/读取 */
window.__zqState=state;
window.__zqNextRecurrence=nextRecurDate;
/* 2026-11-14：通知页测试探针（纯读；now 可注入固定时钟避免真实时间导致测试不稳定） */
window.__zqTest={
  fmtDateText:fmtDateText,disp:disp,nowMs:nowMs,setNow:function(ts){NOW_OVERRIDE=Number(ts)||0;render({animate:false});},
  occurrenceOf:occurrenceOf,recurEnded:recurEnded,recurOngoing:recurOngoing,recurEndTs:recurEndTs,
  recurNext:recurNext,
  nextRecurDate:nextRecurDate,primaryWhenTs:primaryWhenTs,pubTsOf:pubTsOf,relPubText:relPubText,
  pendingAll:pendingAll,pendingOrdGroups:pendingOrdGroups,infoGroups:infoGroups,
  longtermGroupsNow:longtermGroupsNow,latestGroups:latestGroups,occurrences:occurrences,
  cardDomId:cardDomId,statusOf:statusOf,datePhrase:datePhrase,fmtWhen:fmtWhen
};
(function(){
  var sx=0,sy=0,live=false;
  document.addEventListener('touchstart',function(e){
    if(e.touches.length!==1)return;
    var t=e.target;
    if(t.closest('input,textarea,select,[contenteditable],.tscroll,.modal'))return;
    sx=e.touches[0].clientX; sy=e.touches[0].clientY; live=true;
  },{passive:true});
  document.addEventListener('touchend',function(e){
    if(!live)return; live=false;
    var t=e.changedTouches[0], dx=t.clientX-sx, dy=t.clientY-sy;
    if(Math.abs(dx)<60||Math.abs(dx)<Math.abs(dy)*1.25)return;
    var bs=$$('#tabs button'), idx=-1;
    bs.forEach(function(b,i){if(b.classList.contains('on'))idx=i});
    var n=dx<0?idx+1:idx-1;
    if(n>=0&&n<bs.length)bs[n].click();
  },{passive:true});
})();
"""

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>班级简报 · 待处理通知 · 班级工具</title>
<style>__CSS__</style>
</head>
<body>
<div class="wrap">
  <header class="brand">
    <div class="dots"><i></i><i></i><i></i></div>
    <b>班级工具</b><span class="sub">tool.furina.fun</span>
    <div class="right"></div>
  </header>

  <section id="s-nt" class="on">
    <div class="card brief">
      <div class="brief-hd"><span class="eyebrow">待处理简报</span><span class="date" id="briefDate"></span><span class="chip rose" id="briefChip">—</span></div>
      <div class="brief-top" id="dataBar">
        <button class="bstat" type="button" data-card="pending"><b id="statOpen">0</b><span>待处理</span></button>
        <button class="bstat urgent" type="button" data-card="24h"><b id="statUrgent">0</b><span>24h 截止</span></button>
        <button class="bstat" type="button" data-card="7d"><b id="statWeek">0</b><span>7 天内</span></button>
        <button class="bstat recur" type="button" data-card="longterm"><b id="statRecur">0</b><span>长期通知</span></button>
        <button class="bstat latest" type="button" data-card="latest"><b id="statLatest">—</b><span>最新发布</span></button>
      </div>
      <div class="brief-next" id="briefNext"></div>
      <div class="brief-actions">
        <button class="btn ghost sm" id="refreshBtn">刷新</button>
      </div>
    </div>

    <div class="filters">
      <div class="chiprow" id="subRow">
        <button class="chipf on" data-sub="全部">全部</button>
        <button class="chipf" data-sub="todo">待处理</button>
        <button class="chipf" data-sub="expired">已截止</button>
      </div>
      <div class="chiprow sub" id="catRow"></div>
    </div>

    <div class="listhint"><b id="listCount">0 组</b></div>
    <div id="list"></div>
    <div class="lt-wrap data-wrap" id="dataWrap" style="display:none">
      <button class="lt-hd" type="button" data-act="data-toggle">
        <span>资料 / 无时间</span><span class="lt-dot" aria-hidden="true">·</span><b id="dataCount">0 条</b><span class="chev">▾</span>
      </button>
      <div class="lt-list" id="dataList"></div>
    </div>
    <div class="expired-wrap" id="expiredWrap" style="display:none">
      <button class="expired-hd" type="button" data-act="expired-toggle">
        <span>已过期</span><b id="expiredCount">0 组</b><span class="chev">▾</span>
      </button>
      <div class="expired-list" id="expiredList"></div>
    </div>
    <div class="hiddenwrap" id="hiddenWrap" style="display:none">
      <button class="hidden-hd" type="button" data-act="hidden-toggle">
        <span>已隐藏（仅管理员）</span><b id="hiddenCount">0 条</b><span class="chev">▾</span>
      </button>
      <div class="hidden-list" id="hiddenList"></div>
    </div>
  </section>
</div>
<div class="modal" id="modal"><div class="mcard" id="mcard"></div></div>
<div class="edmask" id="editMask"><div class="edcard" id="editCard"></div></div>
<div class="toast" id="toast"></div>
<script>__JS__</script>
</body>
</html>
"""


def load_wechat():
    """Recent WeChat group/private-forward messages captured by the local collector."""
    if not WECHAT_INBOX.exists():
        return []
    msgs = []
    try:
        for line in WECHAT_INBOX.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            content = (r.get("content") or "").strip()
            if not content:
                continue
            ts = r.get("receivedAt", "")
            try:
                from datetime import datetime
                d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                ts = d.strftime("%m-%d %H:%M")
            except Exception:
                ts = ts[5:16]
            msgs.append({"time": ts, "from": r.get("senderName") or r.get("from") or "微信好友",
                         "group": r.get("groupName", ""), "text": content})
    except Exception:
        return []
    return msgs[-20:]


def _cn_int(s):
    if not s:
        return None
    s = str(s).strip()
    if s.isdigit():
        return int(s)
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if s == "十":
        return 10
    if "十" in s:
        a, b = s.split("十", 1)
        return (digits.get(a, 1) if a else 1) * 10 + (digits.get(b, 0) if b else 0)
    return digits.get(s)


def _clock(period, hour_s, minute_s, ref=None):
    h = _cn_int(hour_s)
    if h is None:
        return None
    if minute_s == "半":
        m = 30
    else:
        m = _cn_int(minute_s) or 0
    if h == 24 and m == 0:
        return 24, 0
    if period in ("下午", "晚上", "傍晚") and h < 12:
        h += 12
    elif period == "中午" and h < 12:
        h += 12
    elif period == "凌晨" and h == 12:
        h = 0
    elif period == "上午" and h == 12:
        h = 0
    elif not period and h <= 7 and ref is not None and ref.hour >= 9:
        # “今天六点半”这类没写上午/晚上的，按消息发送时间归到傍晚。
        h += 12
    if h > 23 or m > 59:
        return None
    return h, m


def _parse_ref_time(value):
    """消息发送时间 -> datetime；支持 11-03 13:07 / ISO / 日期。"""
    if isinstance(value, datetime):
        return value
    s = str(value or "").strip()
    if not s:
        return None
    now = datetime.now()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            v = datetime.strptime(s, fmt)
            return v.replace(tzinfo=None)
        except ValueError:
            pass
    m = re.match(r"^(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$", s)
    if m:
        mon, day, hh, mm = map(int, m.groups())
        year = min((now.year - 1, now.year, now.year + 1),
                   key=lambda y: abs((datetime(y, mon, day, hh, mm) - now).total_seconds()))
        return datetime(year, mon, day, hh, mm)
    m = re.match(r"^(\d{1,2})-(\d{1,2})$", s)
    if m:
        mon, day = map(int, m.groups())
        year = min((now.year - 1, now.year, now.year + 1),
                   key=lambda y: abs((datetime(y, mon, day) - now).total_seconds()))
        return datetime(year, mon, day, 23, 59)
    return None


def _year_for(mon, day, ref):
    ref = ref or datetime.now()
    candidates = [ref.year - 1, ref.year, ref.year + 1]
    return min(candidates, key=lambda y: abs((datetime(y, mon, day) - ref).total_seconds()))


def _make_dt(mon, day, hh, mm, ref, year=None):
    if hh == 24 and mm == 0:
        hh, add = 0, 1
    else:
        add = 0
    if not (1 <= mon <= 12 and 1 <= day <= 31 and 0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    y = int(year) if year else _year_for(mon, day, ref)
    try:
        return datetime(y, mon, day, hh, mm) + timedelta(days=add)
    except ValueError:
        return None


_PERIOD = r"(上午|下午|晚上|傍晚|中午|凌晨)?"
_CLOCK = r"([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*(?:[:：点时])\s*(半|[0-9]{1,2}|[一二三四五六七八九十]{1,3})?\s*分?"
_FULL_DATE = re.compile(r"(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?")
_DOT_DATE = re.compile(r"(?<!\d)(\d{1,2})\s*[./]\s*(\d{1,2})(?!\d)")
_REL_DAY = re.compile(r"(今天|今日|今晚|明天|明日|明晚|后天|大后天)")
_CUE = re.compile(r"(截止时间|截止日期|截止|截至|前完成|前提交|前报名|前上传|前填写|之前|以前|报名时间|提交时间|前)")


def _parse_date_tail(tail, ref, mon, day, year=None):
    tail = tail[:36]
    rm = re.match(r"\s*" + _PERIOD + r"\s*" + _CLOCK + r"\s*[-~—–至到]\s*" + _PERIOD + r"\s*" + _CLOCK, tail)
    if rm:
        p1, h1, m1, p2, h2, m2 = rm.groups()
        c = _clock(p2 or p1, h2, m2, ref)
        return _make_dt(mon, day, c[0], c[1], ref, year) if c else None
    tm = re.match(r"\s*" + _PERIOD + r"\s*" + _CLOCK, tail)
    if tm:
        p, h, mi = tm.groups()
        c = _clock(p, h, mi, ref)
        return _make_dt(mon, day, c[0], c[1], ref, year) if c else None
    return _make_dt(mon, day, 23, 59, ref, year)


def _candidates(segment, ref):
    out = []
    for m in _FULL_DATE.finditer(segment):
        year, mon, day = m.groups()
        dt = _parse_date_tail(segment[m.end():], ref, int(mon), int(day), year)
        if dt:
            out.append((dt, m.start(), m.end()))
    for m in _DOT_DATE.finditer(segment):
        # 11.4 / 11/4：只在前后没有“月”时作为日期补充
        if "月" in segment[max(0, m.start() - 2):m.start()]:
            continue
        dt = _parse_date_tail(segment[m.end():], ref, int(m.group(1)), int(m.group(2)))
        if dt:
            out.append((dt, m.start(), m.end()))
    for m in _REL_DAY.finditer(segment):
        word = m.group(1)
        day = {"今天": 0, "今日": 0, "今晚": 0, "明天": 1, "明日": 1, "明晚": 1,
               "后天": 2, "大后天": 3}[word]
        base = (ref or datetime.now()) + timedelta(days=day)
        rest = segment[m.end():m.end() + 24]
        tm = re.match(r"[\s)）]*(?:" + _PERIOD + r")\s*" + _CLOCK, rest)
        if tm:
            p, h, mi = tm.groups()
            if word in ("今晚", "明晚") and not p:
                p = "晚上"
            c = _clock(p, h, mi, ref)
            dt = datetime(base.year, base.month, base.day, c[0], c[1]) if c else None
        else:
            dt = datetime(base.year, base.month, base.day, 23, 59)
        if dt:
            out.append((dt, m.start(), m.end()))
    return out


def extract_deadline(text, ref=None):
    """从“截止/截至/前”等截止语境中解析截止时间；相对日期以消息发送时间为锚。"""
    if not text:
        return None
    base = ref or datetime.now()
    found = []
    # 以标点切段，避免把“活动时间”“工作时间”等事项时间误当截止时间
    for seg in re.split(r"[。！？!?；;\n，,]", str(text)):
        if not seg.strip() or not _CUE.search(seg):
            continue
        # 报名条件 / 参赛资格 / 作品时间要求，不是通知截止。
        if re.search(r"正式注册|报名条件|参赛条件|符合.*条件|两年内|需为|当年", seg) \
                and not re.search(r"截止|截至|报名|提交|申请", seg):
            continue
        if ("以前" in seg or "之前" in seg) and re.search(r"注册|条件|资格", seg) \
                and not re.search(r"截止|截至|报名|提交|完成|申请", seg):
            continue
        cs = _candidates(seg, base)
        if not cs:
            continue
        cues = [(m.start(), m.end()) for m in _CUE.finditer(seg)]
        near = []
        for dt, st, en in cs:
            dist = min(min(abs(st - a), abs(en - b)) for a, b in cues)
            near.append((dist, dt))
        near.sort(key=lambda x: x[0])
        found.append(near[0][1])
    if not found:
        return None
    # 同一段里出现原通知 + 延期通知时，取最晚的明确截止。
    return max(found).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def resolve_deadlines(groups):
    """用每条消息的发送日期重算群截止；优先采用最后一条带明确截止的消息。"""
    for g in groups:
        chosen = None
        for it in g.get("items", []):
            if it.get("kind") == "merged":
                for msg in (it.get("messages") or []):
                    ref = _parse_ref_time(msg.get("time") or it.get("time") or g.get("time") or "")
                    val = extract_deadline(msg.get("text") or "", ref)
                    if val:
                        chosen = val
                continue
            if it.get("kind") not in ("text", "follow"):
                continue
            ref = _parse_ref_time(it.get("time") or g.get("time") or "")
            val = extract_deadline(it.get("text") or "", ref)
            if val:
                chosen = val
        g["deadline"] = chosen
    return groups


def _time_only_candidate(seg, ref):
    """没有完整日期、但有“下午一点”这类时间时，以消息日期补齐。"""
    if _FULL_DATE.search(seg) or _REL_DAY.search(seg):
        return None
    m = re.search(_PERIOD + r"\s*" + _CLOCK, seg)
    if not m:
        return None
    p, h, mi = m.groups()
    c = _clock(p, h, mi, ref)
    if not c:
        return None
    base = ref or datetime.now()
    return datetime(base.year, base.month, base.day, c[0], c[1])


_ACTIVITY_TIME_CUE_RE = re.compile(
    r"活动时间|活动日期|签到时间|签退时间|签退时段|集合时间|比赛时间|开赛时间")


def extract_event_time(text, ref=None, exclude=None):
    """活动/测试/集合等非截止时间；用于没有明确截止、但已经过期的通知。

    exclude：报名窗口等已占用时间；同一时间不再当作活动时间（如「报名 11-13 12:00」）。
    「活动当日 17:00-22:00」这类**只有钟点、没有日期**的片段，在有带日期候选时不参与
    取最小（否则会被错误锚到消息发送日）；没有任何带日期候选时才按消息日兜底。
    """
    if not text:
        return None
    if re.search(r"每月|每周|每学期|每月前|自本周", text):
        return None
    if re.search(r"正式注册|参赛条件|报名条件|符合.*条件", text):
        return None
    base = ref or datetime.now()
    skipped = []
    for x in (exclude or []):
        if isinstance(x, datetime):
            skipped.append(x.replace(tzinfo=None) if x.tzinfo is not None else x)
    dated, undated = [], []
    for seg in re.split(r"[。！？!?；;\n，,]", str(text)):
        # 「今日校园」等专名不是相对日期，不能当成“今天”参与取时间
        if re.search(r"今日(校园|头条|水印|运动)", seg):
            continue
        cs = _candidates(seg, base)
        if cs:
            for dt, _st, _en in cs:
                if any(abs((dt - x).total_seconds()) <= 120 for x in skipped):
                    continue
                dated.append(dt)
        else:
            dt = _time_only_candidate(seg, base)
            if dt:
                undated.append(dt)
    found = dated or undated
    if not found:
        return None
    return min(found)


def resolve_times(groups):
    """补充非截止时间：事件时间、活动消失时间。"""
    nt = _notice_time_module()
    for g in groups:
        if g.get("deadline"):
            continue
        if "挑战杯" in (g.get("title") or ""):
            continue
        text = "\n".join((it.get("text") or "") for it in (g.get("items") or [])
                         if it.get("kind") in ("text", "follow"))
        # 药膳打卡：报名 11/5 12:00 开放，开放一天后停止处理。
        if "药膳" in (g.get("title") or "") and "打卡" in (g.get("title") or ""):
            g["eventAt"] = "2026-11-05T12:00:00+08:00"
            g["expireAt"] = "2026-11-06T12:00:00+08:00"
            g["timeLabel"] = "报名 11-05 12:00"
            continue
        # 有明确「活动/签到时间」的卡：eventAt 交给后续 notice_time 单一真源补，
        # 避免本函数把报名时间/相对钟点误当活动时间（聊天记录展开后的新卡）。
        if nt is not None and _ACTIVITY_TIME_CUE_RE.search(text):
            continue
        ref = _parse_ref_time((g.get("items") or [{}])[0].get("time") or g.get("time") or "")
        event = extract_event_time(text, ref)
        if not event:
            continue
        g["eventAt"] = event.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        if event.hour == 23 and event.minute == 59:
            expire = event + timedelta(days=1)
        else:
            expire = event + timedelta(hours=2)
        g["expireAt"] = expire.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        g["timeLabel"] = event.strftime("%m-%d %H:%M")
    return groups


def load_static_homework():
    """Homework is maintained by hand; new Tencent Docs must not auto-add items."""
    if not HOMEWORK_STATIC.exists():
        return []
    try:
        data = json.loads(HOMEWORK_STATIC.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


DEMO_RE = re.compile(r"示例|演示|样例|模拟")


def realize_groups(groups):
    """Strip demo/example content and derived explanatory fields; keep real posts only."""
    out = []
    for g in groups:
        items = []
        for it in g.get("items", []):
            kind = it.get("kind")
            if kind == "file":
                if not it.get("name") and not it.get("url"):
                    continue
                items.append(it)
                continue
            if kind == "form" and not it.get("realUrl"):
                continue
            if kind == "img":
                text = (it.get("caption") or "") + (it.get("note") or "")
                if DEMO_RE.search(text):
                    continue
            if kind in ("text", "follow"):
                text = it.get("text") or ""
                if DEMO_RE.search(text) or it.get("from") in ("演示消息", "通知原文"):
                    continue
                it["text"] = strip_bad_text(EMOJI_RE.sub("", STICKER_RE.sub("", text))).strip()
                it["text"] = re.sub(r"@(所有人|全体成员|全体同学|全体|大家)\s*", "", it["text"]).strip()
                if not it["text"]:
                    continue
            if kind == "link" and not it.get("url"):
                continue
            items.append(it)
        if not items:
            continue
        g["title"] = strip_bad_text(EMOJI_RE.sub("", STICKER_RE.sub("", g.get("title") or ""))).strip()
        for key in ("aiSummary", "aiPoints", "aiNote", "alert", "summary",
                    "extensions", "scheduleRef"):
            g.pop(key, None)
        g["items"] = items
        out.append(g)
    return out


EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")
STICKER_RE = re.compile(r"\[(动画表情|表情|QQ表情)\]")
QQ_EMOJI_RE = re.compile(r"/[^\s，。！？、；：:,.]{1,12}")
BAD_TOKEN_RE = re.compile(r"(?:fEh|D6EA|VKx)[A-Za-z0-9+/=_-]{12,}")
BAD_FILE_RE = re.compile(r"\$[A-Za-z0-9]{6,}\.(?:jpg|jpeg|png|gif|mp4|pdf)", re.I)
BAD_UUID_RE = re.compile(r"%?/?[0-9a-f]{8}-[0-9a-f]{8,}(?:-[0-9a-f]{4,}){1,4}", re.I)
BAD_LONG_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{40,}\b")


def strip_bad_text(s):
    s = (s or "").replace("\ufffd", "")
    s = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", " ", s)
    s = BAD_FILE_RE.sub("", s)
    s = BAD_UUID_RE.sub("", s)
    s = BAD_TOKEN_RE.sub("", s)
    s = re.sub(r"/download\?[^\s]+", "", s)
    s = BAD_LONG_RE.sub("", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def clean_qq_text(s):
    s = QQ_EMOJI_RE.sub("", s or "")
    s = EMOJI_RE.sub("", s)
    s = re.sub(r"\[(动画表情|表情|QQ表情)\]", "", s)
    s = strip_bad_text(s)
    return re.sub(r"\s+", " ", s).strip()


def _full_chunks(full):
    full = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "\n", full or "")
    chunks = []
    for c in full.split("\n"):
        c = c.strip()
        if len(c) < 8:
            continue
        if re.search(r"[\u4e00-\u9fff]", c) or re.search(r"[A-Za-z]{4,}", c):
            chunks.append(c)
    return chunks


def _find_full_text(previews, chunks):
    """Use the full 40900 text to replace QQ's truncated preview strings."""
    for line in previews:
        parts0 = re.split(r"[:：]", line, maxsplit=1)
        body = clean_qq_text(parts0[1] if len(parts0) == 2 else line)
        probes = re.findall(r"[\u4e00-\u9fff]{8,}", body)
        for probe in sorted(probes, key=len, reverse=True):
            for i, c in enumerate(chunks):
                if probe[:12] in c or (len(probe) >= 8 and c.startswith(probe[:8])):
                    parts = [c]
                    for nxt in chunks[i + 1:i + 12]:
                        if (nxt.startswith("http") or "download?" in nxt or "qh.qlogo" in nxt
                                or re.search(r"\.(jpg|jpeg|png|gif|mp4|pdf)$", nxt, re.I)
                                or not re.search(r"[\u4e00-\u9fff0-9]", nxt)):
                            break
                        parts.append(nxt)
                        if len("\n".join(parts)) > 3500:
                            break
                    return "\n".join(parts)
    return ""


# ---------------------------------------------------------------------------
# QQ 合并转发「聊天记录里还有聊天记录」（2026-11-09）
#
# QQ 的合并转发预览只给「违规昵称: [聊天记录]」。真正的内层内容在 dbscan 输出的
# `full`（QQ 消息表 40900 列）里：每个内层聊天记录是一段 <msg action="viewMultiMsg">
# XML，后面依次跟着它包含的消息元素（每段以固定 marker 对开头，含发送者/头像/正文
# 可读片段）。这里按卡片顺序把占位符展开成真实消息，避免通知页出现「[聊天记录]」
# 空白卡；展开失败时丢弃占位符（不再当成通知原文）。
# ---------------------------------------------------------------------------
QQ_MERGE_MARKER = "u_B-xbHgFtPzMTjvfvZNVuqw"
QQ_MERGE_XML_RE = re.compile(r"<\?xml.*?</msg>", re.S)
QQ_MERGE_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
# 40900 blob 用 UTF-8 解码二进制后夹带的乱码字符（希伯来/西里尔/阿拉伯等），整段丢弃
QQ_MERGE_JUNK_RE = re.compile(
    r"[\u0370-\u03ff\u0400-\u04ff\u0530-\u058f\u0590-\u05ff\u0600-\u06ff\u0900-\u097f\u0e00-\u0e7f]")
QQ_MERGE_FILE_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|rar|7z)(?![A-Za-z0-9])", re.I)
QQ_MERGE_PLACEHOLDERS = ("[聊天记录]", "[聊天紀錄]")
# QQ 表情码是「/汉字」（如 /庆祝 /花朵脸）；不能直接用 QQ_EMOJI_RE，否则会把
# 「JPG/JPEG格式」「https://…」里的 /英文 当表情删掉（2026-11-09 复核实测）。
QQ_MERGE_EMOJI_RE = re.compile(r"/[\u4e00-\u9fff]{1,6}")


def _qq_merge_is_placeholder(text):
    """是否为「聊天记录」占位（兼容「[聊天记录] 3条」这类带后缀的写法）。"""
    s = str(text or "").strip()
    return any(s.startswith(p) for p in QQ_MERGE_PLACEHOLDERS)


def _qq_merge_runs(seg):
    """把 40900 blob 片段按控制字符切成可读文本段（先去掉 UTF-8 替换符）。"""
    seg = (seg or "").replace("\ufffd", "")
    return [x.strip() for x in re.split(r"[\x00-\x1f]+", seg) if x.strip()]


def _qq_merge_clean(text):
    """清洗单个文本段：去二进制噪声/头像/文件名以外的路径，保留正文。"""
    t = (text or "").replace("\ufffd", "").strip()
    if not t or QQ_MERGE_MARKER in t:
        return ""
    if "qlogo.cn" in t or "NTOSFull::" in t or re.search(r"[A-Za-z]:\\", t):
        return ""
    # 二进制字节误解码出的字符（希伯来/西里尔/阿拉伯等）直接剔除，正文保留
    t = QQ_MERGE_JUNK_RE.sub("", t).strip()
    if not t:
        return ""
    if re.fullmatch(r"[A-Za-z0-9+/_=,\-]{16,}", t):
        return ""
    if t.startswith("<") or "</" in t:
        return ""
    # 正文前常粘着一个二进制头字节（如 "X第十一周…"、";活动对象"），去掉它
    t = re.sub(r"^[A-Za-z;:<=>?!$~^`|] ?(?=[\u4e00-\u9fff“”‘’《》〈〉「」【】…—])", "", t)
    t = QQ_MERGE_EMOJI_RE.sub("", t)
    t = EMOJI_RE.sub("", t)
    return t.strip()


def _qq_merge_message_starts(seg):
    """定位一段 blob 里的消息元素起点：marker 单出现=1 条，相邻 marker 对=1 条。"""
    pos = [m.start() for m in re.finditer(re.escape(QQ_MERGE_MARKER), seg or "")]
    starts, i = [], 0
    while i < len(pos):
        p = pos[i]
        if i + 1 < len(pos) and 0 < pos[i + 1] - (p + len(QQ_MERGE_MARKER)) <= 8:
            starts.append(p)
            i += 2
        else:
            starts.append(p)
            i += 1
    return starts


def _qq_merge_sender(el):
    """消息元素里的发送者：头像 token（,<base64>=）之前最后一个可读文本段。"""
    m = re.search(r",[A-Za-z0-9+/]{20,}=", el)
    cut = m.start() if m else len(el)
    sender = ""
    for run in _qq_merge_runs(el[:cut]):
        c = _qq_merge_clean(run)
        if not c or re.fullmatch(r"\d{5,}", c):
            continue
        sender = c
    return sender


def _qq_merge_body(el):
    """消息元素正文：头像 URL 之后的全部可读文本段（按行拼接）。"""
    m = re.search(r"https?://qh\.qlogo\.cn/\S+", el)
    body = el[m.end():] if m else el
    lines = []
    for run in _qq_merge_runs(body):
        c = _qq_merge_clean(run)
        if not c:
            continue
        if re.fullmatch(r"[\d\s.:%+\-／/]+", c):
            continue
        # 正常正文至少 2 个汉字；单个汉字+拉丁字母的碎片是二进制误码（如「汬j」），丢弃
        if len(re.findall(r"[\u4e00-\u9fff]", c)) < 2 \
                and not c.startswith("http") and not QQ_MERGE_FILE_RE.search(c):
            continue
        lines.append(c)
    return "\n".join(lines).strip()


def _qq_merge_region_messages(region, fallback_time):
    """把一段内层聊天记录区域解析成消息列表。"""
    starts = _qq_merge_message_starts(region)
    out = []
    for i, st in enumerate(starts):
        en = starts[i + 1] if i + 1 < len(starts) else len(region)
        el = region[st:en]
        text = _qq_merge_body(el)
        if not text:
            continue
        kind, name = "text", ""
        if QQ_MERGE_FILE_RE.search(text) and "\n" not in text.strip():
            kind, name = "file", text.strip()
        out.append({"from": _qq_merge_sender(el), "time": fallback_time, "text": text,
                    "kind": kind, "name": name, "url": ""})
    return out


def _qq_merge_preview_messages(previews, fallback_time):
    """展开失败时退回内层卡片的预览行（至少是真实标题/摘要，不是占位符）。"""
    out = []
    for line in previews:
        parts = re.split(r"[:：]", line, maxsplit=1)
        sender = clean_qq_text(parts[0]) if len(parts) == 2 else ""
        text = clean_qq_text(parts[1] if len(parts) == 2 else line)
        if not text or _qq_merge_is_placeholder(text):
            continue
        kind, name = "text", ""
        if "[文件]" in text or QQ_MERGE_FILE_RE.search(text):
            kind = "file"
            name = re.sub(r"^\[文件\]\s*", "", text)
            text = name
        elif re.fullmatch(r"\[(图片|动画表情|表情)\]", text):
            kind = "image"
        out.append({"from": sender, "time": fallback_time, "text": text,
                    "kind": kind, "name": name, "url": ""})
    return out


def _qq_merge_card(full, frag_start, frag_end, region_end, fallback_time):
    """解析一个内层聊天记录卡片：标题/条数 + 其消息内容。"""
    seg = full[frag_start:frag_end]
    titles = [re.sub(r"<[^>]+>", "", m.group(1)).strip() for m in QQ_MERGE_TITLE_RE.finditer(seg)]
    title = titles[0] if titles else "聊天记录"
    previews = [t for t in titles[1:] if t]
    m = re.search(r'tSum="(\d+)"', seg)
    tsum = int(m.group(1)) if m else len(previews)
    messages = _qq_merge_region_messages(full[frag_end:region_end], fallback_time)
    if not messages:
        messages = _qq_merge_preview_messages(previews, fallback_time)
    return {"title": title, "count": tsum, "messages": messages}


def _qq_merge_expand_nested(m, messages, full):
    """把外层 preview 里的 [聊天记录] 占位消息替换成内层聊天记录的真实消息。"""
    placeholders = [i for i, it in enumerate(messages)
                    if _qq_merge_is_placeholder(it.get("text"))]
    if not placeholders:
        return messages
    frags = list(QQ_MERGE_XML_RE.finditer(full or ""))
    cards = []
    for i, fm in enumerate(frags):
        region_end = frags[i + 1].start() if i + 1 < len(frags) else len(full)
        cards.append(_qq_merge_card(full, fm.start(), fm.end(), region_end,
                                    m.get("time") or m.get("iso") or ""))
    placeholder_set = set(placeholders)
    if not cards:
        print("qq merged nested unresolved (no nested card in full):", m.get("rowid"), flush=True)
        # 保留真实文字条目，只丢掉占位符（不能因为占位符把整条真实通知一起删掉）
        return [it for i, it in enumerate(messages) if i not in placeholder_set]
    out, ci = [], 0
    for i, it in enumerate(messages):
        if i not in placeholder_set:
            out.append(it)
            continue
        if ci >= len(cards):
            continue
        card = cards[ci]
        ci += 1
        out.extend(card["messages"])
    # 最终兜底：深层嵌套（内层卡正文仍只有 [聊天记录]）时绝不把占位符当通知内容
    return [it for it in out if not _qq_merge_is_placeholder(it.get("text"))]


def load_qq_merged():
    """One QQ merged record; enrich from 40900 full text / mini / file URLs."""
    if not QQ_MERGED.exists():
        return []
    try:
        data = json.loads(QQ_MERGED.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for m in data.get("items", []):
        previews = [str(x).strip() for x in (m.get("previews") or []) if str(x).strip()]
        full = m.get("full") or ""
        chunks = _full_chunks(full)
        mini_urls = []
        for u in re.findall(r'"url"\s*:\s*"([^"]+)"', full):
            u = u.replace("\\/", "/")
            if u.startswith("m.q.qq.com/"):
                u = "https://" + u
            if u.startswith("http") and u not in mini_urls:
                mini_urls.append(u)
        file_paths = [p.rstrip("\x00") for p in
                      re.findall(r"/download\?appid=\d+&fileid=[^&\s\x00-\x1f]+&spec=\d+", full)]
        image_paths = {}
        for p in file_paths:
            fid = re.search(r"fileid=([^&]+)", p)
            spec = re.search(r"spec=(\d+)", p)
            if not fid:
                continue
            key = fid.group(1)
            priority = 0 if (spec and spec.group(1) == "0") else (1 if spec and spec.group(1) == "720" else 2)
            if key not in image_paths or priority < image_paths[key][0]:
                image_paths[key] = (priority, p)
        image_urls = []
        rkey = re.search(r"[?&]rkey=([A-Za-z0-9_\-]+)", full)
        for _, p in image_paths.values():
            u = "https://multimedia.nt.qq.com.cn" + p
            if rkey:
                u += "&rkey=" + rkey.group(1)
            image_urls.append(u)
        messages = []
        for line in previews:
            parts = re.split(r"[:：]", line, maxsplit=1)
            sender = clean_qq_text(parts[0]) if len(parts) == 2 else ""
            text = clean_qq_text(parts[1] if len(parts) == 2 else line)
            kind, name, url = "text", "", ""
            if "[文件]" in text or re.search(r"\.(pdf|docx?|xlsx?|pptx?|zip|rar)$", text, re.I):
                kind = "file"
                name = re.sub(r"^\[文件\]\s*", "", text)
                text = name
            elif "[QQ小程序]" in text or "[小程序]" in text:
                kind = "mini"
                name = re.sub(r"^\[(QQ)?小程序\]\s*", "", text)
                text = name
                if mini_urls:
                    url = mini_urls.pop(0)
            elif text in ("[图片]", "[动画表情]", "[表情]"):
                kind = "image"
            else:
                deep = _find_full_text([line], chunks)
                if deep and len(deep) > len(text):
                    text = clean_qq_text(deep).lstrip("！!，,。；;、 ")
            messages.append({"from": sender, "time": m.get("time") or m.get("iso") or "", "text": text,
                             "kind": kind, "name": name, "url": url})
        # 聊天记录里还套着聊天记录：预览只有 [聊天记录]，用 40900 full 里的内层卡片
        # 展开成真实消息（否则通知页会出现只有占位符的空白通知）。
        nested = any(_qq_merge_is_placeholder(x.get("text")) for x in messages)
        if nested:
            messages = _qq_merge_expand_nested(m, messages, full)
            if not messages:
                print("qq merged skipped (nested record, cannot expand):", m.get("rowid"), flush=True)
                continue
        # 40900 download links belong to the record's image messages (QR codes),
        # not to the PDF file cards; keep the PDF names as non-clickable files.
        for i, u in enumerate(image_urls):
            messages.append({"from": "", "time": "", "text": "[图片]", "kind": "image",
                             "name": "qqimg_%d_%s.jpg" % (i, str(m.get("rowid"))[-6:]),
                             "url": u})
        if not messages:
            continue
        text = "\n".join(x["text"] for x in messages)
        title = (m.get("title") or "聊天记录").strip()
        count = len(messages) if nested else int(m.get("count") or len(messages))
        out.append({
            "id": "g_qqm_" + str(m.get("rowid")),
            "cat": classify_wechat(text),
            "title": title,
            "group": m.get("groupName", ""), "source": "QQ 群 · " + m.get("groupName", ""),
            "deadline": extract_deadline(text), "actionable": True,
            "items": [{"kind": "merged", "label": "聊天记录", "title": title,
                       "count": count,
                       "messages": messages[:20], "text": text,
                       "time": m.get("time", "")}],
        })
    return out


def load_qq_text():
    """Auto notice groups generated from QQ plain-text messages (classify_qq_text.py)."""
    if not QQ_TEXT.exists():
        return []
    try:
        data = json.loads(QQ_TEXT.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for n in data.get("items", []):
        if not isinstance(n, dict) or not n.get("id"):
            continue
        items = []
        for it in (n.get("items") or []):
            if not isinstance(it, dict):
                continue
            it = dict(it)
            if it.get("kind") in ("text", "follow"):
                text = clean_qq_text(it.get("text") or "")
                text = re.sub(r"@(所有人|全体成员|全体同学|全体|大家)\s*", "", text).strip()
                if not text:
                    continue
                it["text"] = text
            items.append(it)
        if not items:
            continue
        joined = "\n".join(str(it.get("text") or "") for it in items)
        ref = _parse_ref_time(items[0].get("time") or "")
        deadline = n.get("deadline") or extract_deadline(joined, ref)
        event_at = n.get("eventAt") or None
        # 兼容旧数据：历史上曾把“消息发送时间”写进 eventAt 占位，这不是通知里写的时间，丢掉。
        if event_at and str(event_at)[:19] == str(n.get("_createdAt") or "")[:19]:
            event_at = None
        # 数据口径：expireAt 只表示“自动归档时间”，不能当截止时间用。
        #  - 有截止：交给客户端按 deadline 判定，不写 expireAt
        #  - 只有活动时间：活动结束后 2 小时自动归档
        #  - 两者都没有（例如「运动会期间晚自习正常」）：不写 expireAt，界面显示「无时间」
        if deadline:
            expire_at = None
        elif event_at:
            try:
                dt = datetime.strptime(str(event_at)[:19], "%Y-%m-%dT%H:%M:%S")
                expire_at = (dt + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
            except Exception:
                expire_at = None
        else:
            expire_at = None
        out.append({
            "id": n["id"],
            "cat": n.get("cat") or classify_wechat(joined),
            "title": (n.get("title") or "QQ 群通知")[:24],
            "summary": n.get("summary") or "",
            "aiSummary": n.get("aiSummary") or "",
            "aiPoints": n.get("aiPoints") or [],
            "group": n.get("group", ""),
            "source": n.get("source", "QQ 群"),
            "deadline": deadline,
            "eventAt": event_at,
            "expireAt": expire_at,
            "timeLabel": (n.get("timeLabel") or "") if event_at else "",
            "actionable": bool(n.get("actionable")),
            "items": items,
        })
    return out


_DIGITS_RE = re.compile(r"\d+")
_PERSON_DEPT_RE = re.compile(r"^(?:信管|健管|公[12]?|临\d?|药\d?|护\d?|康\d?|预\d?|中[医西]?|针推\d?)")
_PERSON_PUNCT_RE = re.compile(r"[\s·\-—_()（）\[\]【】<>《》,，.。:：;；]+")


def _person_clean(raw):
    s = _DIGITS_RE.sub("", str(raw or ""))
    s = _PERSON_PUNCT_RE.sub("", s)
    s = _PERSON_DEPT_RE.sub("", s)
    return s.strip()


def _load_json(path):
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_roster():
    """班级名单 + 班委职务 + 网名别名（契约 §5）。

    数据源（只读）：
      - class-members.json：姓名/职务真源
      - class-identities.json：members[].aliases + qq[].nicknames/remarks/cards + wx[].nicknames/remarks/displayNames/groupNicks
      - class-aliases.json：aliases 昵称→学号，qq_uin/wx_id → 学号
    返回 {"by_raw": {...}, "by_clean": {...}, "aliases": [(key, info)...]}；
    by_clean 同时包含姓名键与别名键，aliases 供「最长别名包含」兜底（≥2 字）。
    """
    role_map = {}   # _person_clean(name) -> info
    for m in (_load_json(CLASS_ROSTER) or {}).get("members", []):
        if not isinstance(m, dict):
            continue
        nm = str(m.get("name") or "").strip()
        key = _person_clean(nm)
        if not key:
            continue
        # 2026-11-19 修复：badge 只认 class-members 的显式字段；此前空 badge 默认成
        # 「班委」，导致普通同学（同学D/同学E/同学F等）也被标班委气泡。
        role_map[key] = {
            "name": nm,
            "role": str(m.get("role") or "").strip(),
            "badge": str(m.get("badge") or "").strip(),
        }
    if not role_map:
        # 没 class-members 时至少用 class-identities 的 members 兜底
        for m in (_load_json(CLASS_IDENTITIES) or {}).get("members", []):
            if isinstance(m, dict):
                role_map[_person_clean(m.get("name") or "")] = {
                    "name": str(m.get("name") or "").strip(),
                    "role": str(m.get("role") or "").strip(),
                    "badge": str(m.get("badge") or "").strip(),
                }

    raw_map, clean_map = {}, {}
    alias_keys = []

    def add_alias(alias, info):
        s = str(alias or "").strip()
        if not s or not info.get("name"):
            return
        raw_map.setdefault(s, info)
        ck = _person_clean(s)
        if ck:
            clean_map.setdefault(ck, info)
            if len(ck) >= 2 and ck != _person_clean(info["name"]):
                alias_keys.append(ck)

    # 姓名本身（含清理后的键）
    for info in role_map.values():
        add_alias(info["name"], info)
        raw_map.setdefault(_person_clean(info["name"]), info)

    ident = _load_json(CLASS_IDENTITIES) or {}
    sid_info = {}
    id_members = ident.get("members") or []
    for m in id_members:
        if not isinstance(m, dict):
            continue
        nm = str(m.get("name") or "").strip()
        info = role_map.get(_person_clean(nm))
        if not info:
            info = {
                "name": nm,
                "role": str(m.get("role") or "").strip(),
                "badge": str(m.get("badge") or "").strip(),
            }
            if info["name"]:
                role_map[_person_clean(info["name"])] = info
        if m.get("sid"):
            sid_info[str(m.get("sid"))] = info
        for a in (m.get("aliases") or []):
            add_alias(a, info)
        for plat in ("qq", "wx"):
            for p in (m.get(plat) or []):
                if not isinstance(p, dict):
                    continue
                for field in ("nicknames", "remarks", "cards", "displayNames", "groupNicks"):
                    for a in (p.get(field) or []):
                        add_alias(a, info)
                for field in ("uin", "wxid", "id"):
                    if p.get(field):
                        raw_map.setdefault(str(p.get(field)), info)

    al = _load_json(CLASS_ALIASES) or {}
    for alias, sid in (al.get("aliases") or {}).items():
        info = sid_info.get(str(sid))
        if info:
            add_alias(alias, info)
    for alias, sid in (al.get("qq_uin") or {}).items():
        info = sid_info.get(str(sid))
        if info:
            raw_map.setdefault(str(alias), info)
    for alias, sid in (al.get("wx_id") or {}).items():
        info = sid_info.get(str(sid))
        if info:
            raw_map.setdefault(str(alias), info)

    # 「最长别名包含」用：按长度降序（长别名优先，避免短名误命中）
    alias_keys = sorted(set(alias_keys), key=len, reverse=True)
    return {"by_raw": raw_map, "by_clean": clean_map, "aliases": [(k, clean_map[k]) for k in alias_keys]}


def _roster_lookup(raw, roster):
    """契约 §5 匹配顺序：原文精确 → _person_clean 后命中 → 最长别名包含（≥2 字）。"""
    if not roster:
        return None
    s = str(raw or "").strip()
    if not s:
        return None
    hit = roster["by_raw"].get(s)
    if hit:
        return hit
    key = _person_clean(s)
    if not key:
        return None
    hit = roster["by_clean"].get(key)
    if hit:
        return hit
    best = None
    for alias, info in roster["aliases"]:
        if alias and alias in key and (best is None or len(alias) > len(best[0])):
            best = (alias, info)
    return best[1] if best else None


def _fill_sender(it, roster):
    raw = it.get("from") or it.get("sender") or ""
    if not raw:
        return None
    info = _roster_lookup(raw, roster)
    display = info["name"] if info else _person_clean(raw)
    if not display:
        return None
    it["fromName"] = display
    if info:
        it["fromRole"] = info["role"]
        it["fromBadge"] = info["badge"]
        if str(raw).strip() != display:
            it["fromRaw"] = str(raw).strip()  # 原始网名，仅调试用，前端不显示
    for m in it.get("messages") or []:
        if not isinstance(m, dict):
            continue
        mraw = m.get("from") or ""
        if not mraw:
            continue
        minfo = _roster_lookup(mraw, roster)
        m["fromName"] = minfo["name"] if minfo else _person_clean(mraw)
        if minfo:
            m["fromRole"] = minfo["role"]
            m["fromBadge"] = minfo["badge"]
    return info or {"name": display}


def attach_sender_roles(groups):
    """给通知发布者和原始消息发送者补「班委」气泡（数据来自 class-members.json）。"""
    roster = load_roster()
    if not roster or not roster.get("by_clean"):
        return groups
    for g in groups:
        picked = None
        for it in g.get("items") or []:
            if not isinstance(it, dict):
                continue
            info = _fill_sender(it, roster)
            if not info:
                continue
            candidate = {"name": info.get("name") or it.get("fromName") or "",
                         "role": info.get("role") or "", "badge": info.get("badge") or ""}
            if picked is None:
                picked = candidate
            elif candidate.get("badge") and not picked.get("badge"):
                picked = candidate
        if picked and picked.get("name"):
            g["senderName"] = picked["name"]
            if picked.get("role"):
                g["senderRole"] = picked["role"]
            if picked.get("badge"):
                g["senderBadge"] = picked["badge"]
    return groups


def _norm_title(s):
    return re.sub(r"[\s\W_]+", "", str(s or "").lower())


def _find_merge_target(g, groups):
    """OCR 通知若标题与已有通知高度一致，就把图片/OCR 文字并进那条通知。"""
    nt = _norm_title(g.get("title"))
    if len(nt) < 5:
        return None
    for e in groups:
        if e.get("ocr"):
            continue
        et = _norm_title(e.get("title"))
        if not et or len(et) < 5:
            continue
        if nt == et or nt in et or et in nt:
            if not g.get("group") or not e.get("group") or g.get("group") == e.get("group"):
                return e
        if difflib.SequenceMatcher(None, nt, et).ratio() >= 0.85:
            return e
    return None


def _merge_image_into(target, g):
    items = target.setdefault("items", [])
    existing_text = {str(it.get("text") or "") for it in items}
    existing_src = {str(it.get("src") or "")[:64] for it in items if it.get("kind") == "img"}
    added = 0
    for it in g.get("items") or []:
        if not isinstance(it, dict):
            continue
        if it.get("kind") == "img":
            key = str(it.get("src") or "")[:64]
            if key and key in existing_src:
                continue
            existing_src.add(key)
            it = dict(it)
            it["label"] = "OCR 通知图片"
            items.append(it)
            added += 1
        elif it.get("kind") in ("text", "follow"):
            txt = str(it.get("text") or "")
            if not txt or txt in existing_text:
                continue
            it = dict(it)
            it["label"] = "OCR 识别文字"
            items.append(it)
            existing_text.add(txt)
            added += 1
    if added:
        target["ocrAttach"] = True
        target["ocr"] = True
    return added


def _clean_ocr_text(s):
    s = strip_bad_text(str(s or ""))
    s = re.sub(r"@(所有人|全体成员|全体同学|全体|大家)\s*", "", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def load_qq_image_notices():
    """OCR 图片通知（classify_qq_images.py 生成）。"""
    if not QQ_IMAGE_TEXT.exists():
        return []
    try:
        data = json.loads(QQ_IMAGE_TEXT.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for n in data.get("items", []):
        if not isinstance(n, dict) or not n.get("id"):
            continue
        items = []
        for it in (n.get("items") or []):
            if not isinstance(it, dict):
                continue
            it = dict(it)
            if it.get("kind") in ("text", "follow"):
                text = _clean_ocr_text(it.get("text") or "")
                if not text:
                    continue
                it["text"] = text
            if it.get("kind") == "img":
                if not it.get("src"):
                    continue
                it["ocr"] = True
            items.append(it)
        if not items:
            continue
        joined = "\n".join(str(it.get("text") or "") for it in items)
        ref = _parse_ref_time(items[0].get("time") or "")
        out.append({
            "id": n["id"],
            "cat": n.get("cat") or classify_wechat(joined),
            "title": (n.get("title") or "图片通知")[:24],
            "summary": n.get("summary") or "",
            "aiSummary": n.get("aiSummary") or "",
            "aiPoints": n.get("aiPoints") or [],
            "group": n.get("group", ""),
            "source": n.get("source", "QQ 群"),
            "deadline": n.get("deadline") or extract_deadline(joined, ref),
            "eventAt": n.get("eventAt") or None,
            "expireAt": n.get("expireAt") or None,
            "timeLabel": n.get("timeLabel") or "",
            "actionable": bool(n.get("actionable")),
            "ocr": True,
            "items": items,
        })
    return out


def load_qq_file_notices():
    """QQ 群「单个文件」通知（fetch_qq_file_notices.py 生成，已结合上下文判定）。"""
    if not QQ_FILE_TEXT.exists():
        return []
    try:
        data = json.loads(QQ_FILE_TEXT.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for n in data.get("items", []):
        if not isinstance(n, dict) or not n.get("id"):
            continue
        items = []
        for it in (n.get("items") or []):
            if not isinstance(it, dict):
                continue
            it = dict(it)
            if it.get("kind") == "file":
                if not it.get("name"):
                    continue
                # 本地有同名文件（data/qq-files）就内嵌成可预览附件，否则显示“QQ 文件”
                url = it.get("url") or qq_file_uri(it.get("name"))
                if url:
                    it["url"] = url
            elif it.get("kind") == "text":
                it["text"] = _clean_ocr_text(it.get("text") or "")
                if not it["text"]:
                    continue
            items.append(it)
        if not items:
            continue
        joined = "\n".join(str(it.get("text") or it.get("name") or "") for it in items)
        ref = _parse_ref_time(items[0].get("time") or "")
        out.append({
            "id": n["id"],
            "cat": n.get("cat") or classify_wechat(joined),
            "title": (n.get("title") or "文件通知")[:24],
            "summary": n.get("summary") or "",
            "aiSummary": n.get("aiSummary") or "",
            "aiPoints": n.get("aiPoints") or [],
            "group": n.get("group", ""),
            "source": n.get("source", "QQ 群"),
            "deadline": n.get("deadline") or extract_deadline(joined, ref),
            "eventAt": n.get("eventAt") or None,
            "expireAt": n.get("expireAt") or None,
            "timeLabel": n.get("timeLabel") or "",
            "actionable": bool(n.get("actionable", True)),
            "contextReviewed": bool(n.get("contextReviewed")),
            "items": items,
        })
    return out


def _find_file_merge_target(g, groups):
    """文件通知标题比较宽松地并进已有通知（同一群、共享前缀或标题相似）。"""
    nt = _norm_title(g.get("title"))
    if len(nt) < 4:
        return None
    for e in groups:
        if e.get("ocr"):
            continue
        et = _norm_title(e.get("title"))
        if len(et) < 4:
            continue
        if g.get("group") and e.get("group") and g.get("group") != e.get("group"):
            continue
        if nt in et or et in nt or nt[:6] == et[:6]:
            return e
        if difflib.SequenceMatcher(None, nt, et).ratio() >= 0.7:
            return e
    return None


def load_ai_triage_notices():
    """全量消息 AI 识别（ai_triage.py 生成，覆盖 QQ/微信文本、链接、小程序、文件转发）。"""
    if not AI_TRIAGE.exists():
        return []
    try:
        data = json.loads(AI_TRIAGE.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for n in data.get("items", []):
        if not isinstance(n, dict) or not n.get("id") or not n.get("items"):
            continue
        if "接龙" in str(n.get("title") or ""):
            continue  # 需求 6 兜底：接龙类通知不上板
        if any(isinstance(it, dict) and "接龙" in (str(it.get("text") or "") + str(it.get("name") or ""))
               for it in n["items"]):
            continue
        items = [dict(it) for it in n["items"] if isinstance(it, dict)]
        joined = "\n".join(str(it.get("text") or it.get("name") or "") for it in items)
        ref = _parse_ref_time(items[0].get("time") or "")
        g = {
            "id": n["id"],
            "cat": n.get("cat") or classify_wechat(joined),
            "title": (n.get("title") or "AI 通知")[:24],
            "summary": n.get("summary") or "",
            "aiSummary": n.get("aiSummary") or n.get("summary") or "",
            "aiPoints": n.get("aiPoints") or [],
            "group": n.get("group", ""),
            "source": n.get("source", "AI 识别"),
            "deadline": _patch_iso(n.get("deadline")) or extract_deadline(joined, ref),
            "eventAt": _patch_iso(n.get("eventAt")) or None,
            "expireAt": None,
            "timeLabel": "",
            # 契约 §1：AI 输出新增时间语义字段（旧数据由 normalize 补齐）
            "deadlineAction": str(n.get("deadlineAction") or "").strip()[:12],
            "eventAction": str(n.get("eventAction") or "").strip()[:12],
            "signupStart": _patch_iso(n.get("signupStart")) or None,
            "signupEnd": _patch_iso(n.get("signupEnd")) or None,
            "actionable": bool(n.get("actionable", True)),
            "aiTriage": True,
            "items": items,
        }
        # 多消息合并/补充卡透传：前端据此显示全部 item 原文 + 「已更新」徽标
        if n.get("aiMerged"):
            g["aiMerged"] = True
        if n.get("supplement"):
            g["supplement"] = True
        updated_at = str(n.get("updatedAt") or "").strip()
        if updated_at:
            g["updatedAt"] = updated_at
        out.append(g)
    return out


def _merge_file_into(target, g):
    """同名/同主题的通知：把文件消息并入已有通知卡片（按 类型+名称/文本+时间 去重）。"""
    items = target.setdefault("items", [])
    seen = {(it.get("kind"), it.get("name") or it.get("text"), it.get("time")) for it in items}
    for it in g.get("items") or []:
        key = (it.get("kind"), it.get("name") or it.get("text"), it.get("time"))
        if key in seen:
            continue
        seen.add(key)
        items.append(it)
    if g.get("deadline") and not target.get("deadline"):
        target["deadline"] = g["deadline"]
    if g.get("contextReviewed"):
        target["contextReviewed"] = True


def load_context_overrides():
    """上下文复核结果（context_confirm.py 生成）：按通知 id 覆盖/忽略。"""
    if not QQ_CONTEXT.exists():
        return {}
    try:
        data = json.loads(QQ_CONTEXT.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for k, v in (data.get("items") or {}).items():
        if isinstance(v, dict):
            out[k] = v
    return out


def apply_context_overrides(groups):
    """应用上下文复核：ignore 的剔除；keep 的更新标题/摘要/分类/截止。"""
    ov = load_context_overrides()
    if not ov:
        return groups
    out = []
    for g in groups:
        o = ov.get(g.get("id")) if isinstance(g, dict) else None
        if o:
            if o.get("decision") == "ignore":
                continue
            for k in ("title", "cat", "summary", "deadline", "eventAt"):
                if o.get(k):
                    g[k] = o[k]
            if o.get("summary") and not g.get("aiSummary"):
                g["aiSummary"] = o["summary"]
        out.append(g)
    return out


# ---------------------------------------------------------------- v2.0.0 通知数据契约
# 需求 6：接龙过滤（确定性兜底）+ 补充通知合并
# 需求 9：长期安排 recurrence
# 人工补丁：data/notice-manual-patches.json（人工优先于 AI）

ISO_FIELDS = ("deadline", "eventAt", "expireAt", "signupStart", "signupEnd")
GROUP_PATCH_FIELDS = ("title", "cat", "summary", "aiSummary", "aiPoints", "aiSegments",
                      "deadline", "eventAt",
                      "expireAt", "timeLabel", "actionable", "recurrence", "updatedAt",
                      # 契约 §1：人工补丁同样可覆盖时间语义字段，且仍然最后应用（优先级最高）
                      "deadlineAction", "eventAction", "signupStart", "signupEnd")


def is_lianlong_group(g):
    """需求 6 兜底：AI 误生成的接龙卡 / 历史遗留的接龙卡一律不上板。"""
    if not isinstance(g, dict):
        return True
    if "接龙" in str(g.get("title") or ""):
        return True
    for it in g.get("items") or []:
        if isinstance(it, dict) and "接龙" in (str(it.get("text") or "") + str(it.get("name") or "")):
            return True
    return False


def _patch_iso(value):
    """补丁/补充里的时间统一成 +08:00 ISO（AI 常返回 YYYY-MM-DDTHH:MM）。"""
    s = str(value or "").strip()
    if not s:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", s):
        return s + ":00+08:00"
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", s):
        return s + "+08:00"
    return s


def _find_group(groups, gid, title_fallback=""):
    for g in groups:
        if g.get("id") == gid:
            return g
    nt = _norm_title(title_fallback)
    if not nt or len(nt) < 4:
        return None
    for g in groups:
        et = _norm_title(g.get("title"))
        if not et:
            continue
        if nt in et or et in nt:
            return g
    return None


def _append_items(g, items):
    """追加 items（按 kind+label+time+文本/名称 去重，避免重建重复追加）。"""
    if not isinstance(g, dict) or not items:
        return 0
    existing = set()
    for it in g.setdefault("items", []):
        if isinstance(it, dict):
            existing.add((it.get("kind"), it.get("label"), it.get("time"),
                          it.get("text") or it.get("name") or ""))
    added = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        key = (it.get("kind"), it.get("label"), it.get("time"),
               it.get("text") or it.get("name") or "")
        if key in existing:
            continue
        g["items"].append(dict(it))
        existing.add(key)
        added += 1
    return added


def _apply_patch_to_group(g, patch, appended=0, updated_at=""):
    """按字段覆盖/追加 items / 写 updatedAt（人工补丁与 AI 补充共用）。"""
    patch = patch if isinstance(patch, dict) else {}
    for k in GROUP_PATCH_FIELDS:
        if k not in patch:
            continue
        v = patch.get(k)
        if k == "recurrence":
            if isinstance(v, dict) and v.get("freq"):
                g["recurrence"] = v
            continue
        if k == "updatedAt":
            if v:
                g["updatedAt"] = str(v)
            continue
        if k in ISO_FIELDS:
            nv = _patch_iso(v)
            if nv:
                g[k] = nv
            continue
        if k == "actionable":
            g["actionable"] = bool(v)
            continue
        if v is None:
            g.pop(k, None)
            continue
        if v == "":
            continue
        g[k] = v
    if appended:
        for it in g.get("items") or []:
            if isinstance(it, dict) and it.get("label") == "补充通知":
                g["supplement"] = True
                break
    if updated_at:
        g["updatedAt"] = updated_at


def load_ai_supplements():
    """ai_triage 生成的补充通知（对已有通知的补充/更正/延期）。"""
    try:
        data = json.loads(AI_SUPPLEMENTS.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data.get("items") if isinstance(data, dict) else data
    return [x for x in (items or []) if isinstance(x, dict) and x.get("target")]


def apply_supplements(groups):
    """需求 6：把 AI 识别出的补充通知并入已有通知（追加 items + 修正字段 + updatedAt）。"""
    supplements = load_ai_supplements()
    if not supplements:
        return groups
    for s in supplements:
        target = _find_group(groups, str(s.get("target") or ""), str(s.get("targetTitle") or ""))
        if not target:
            continue
        items = []
        for it in s.get("items") or []:
            if not isinstance(it, dict):
                continue
            it = dict(it)
            it["label"] = "补充通知"
            items.append(it)
        added = _append_items(target, items)
        _apply_patch_to_group(target, s.get("patch") or {}, appended=added,
                              updated_at=str(s.get("updatedAt") or ""))
    return groups


# ---------------------------------------------------------------- 契约 §1.4：更新/更正通知合并
def load_notice_threads():
    """AI notice_threads.py 产物：keep/merge + 最终有效字段 + reason。

    顶层兼容 {"threads":[...]} / {"items":[...]} / 纯数组；每条线程见 apply_threads。
    """
    try:
        data = json.loads(NOTICE_THREADS.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = None
    if isinstance(data, dict):
        for k in ("threads", "items", "merges"):
            if isinstance(data.get(k), list):
                items = data.get(k)
                break
    elif isinstance(data, list):
        items = data
    return [x for x in (items or []) if isinstance(x, dict)]


def _thread_ref_id(value):
    if isinstance(value, dict):
        return str(value.get("id") or value.get("gid") or value.get("target") or "").strip()
    return str(value or "").strip()


def _thread_keep_id(th):
    for k in ("keep", "keepId", "keepGid", "target", "targetId"):
        if th.get(k):
            return _thread_ref_id(th.get(k))
    return ""


def _thread_merge_ids(th):
    raw = None
    for k in ("merge", "mergeIds", "drop", "remove", "merged"):
        if isinstance(th.get(k), (list, str, dict)):
            raw = th.get(k)
            break
    if isinstance(raw, (str, dict)):
        raw = [raw]
    ids = []
    for x in raw or []:
        gid = _thread_ref_id(x)
        if gid and gid not in ids:
            ids.append(gid)
    return ids


def _thread_patch(th):
    """线程给出的最终有效状态（仅提供时覆盖；兼容 summary/points/segments 原始字段名）。"""
    patch = {}
    for k in GROUP_PATCH_FIELDS:
        if k in th and th.get(k) not in (None, "", []):
            patch[k] = th.get(k)
    if "aiSummary" not in patch and (th.get("aiSummary") or th.get("summary")):
        patch["aiSummary"] = th.get("aiSummary") or th.get("summary")
    if "aiPoints" not in patch and isinstance(th.get("points"), list):
        pts = [str(x).strip()[:12] for x in th.get("points") if str(x).strip()]
        if pts:
            patch["aiPoints"] = pts[:6]
    if "aiSegments" not in patch and isinstance(th.get("segments"), list):
        segs = []
        for seg in th.get("segments") or []:
            if isinstance(seg, dict) and str(seg.get("text") or "").strip():
                segs.append({"type": str(seg.get("type") or "内容").strip()[:8],
                             "text": str(seg.get("text") or "").strip()[:90]})
        if segs:
            patch["aiSegments"] = segs[:10]
    if patch.get("title"):
        patch["title"] = str(patch["title"]).strip()[:24]
    return patch


def apply_threads(groups):
    """契约 §1.4：更新/更正通知合并（后发覆盖先发，被取消内容不进摘要）。

    - keep 组：仅在线程提供时覆盖 title/aiSummary/aiPoints/aiSegments/时间语义字段；
    - merge 组：items 改写为「补充通知」追加到 keep（保留 time/from、supplement=true），
      合并 updatedAt 后从通知列表删除（原始消息仍可在 keep 卡展开查看）；
    - 容错：keep/merge id 不存在自动跳过；同一 threads 文件重复应用幂等；
      不会跨话题误合并（由 AI 输出 reason，人工复核）。
    - NOTICE_SKIP_THREADS=1 时跳过（detect_docs 在「线程生成之前的中间构建」设置该变量，
      否则中间构建就把 merge 组删掉，notice_threads 阶段看不到原始候选、误以为无线程）。
    """
    if os.environ.get("NOTICE_SKIP_THREADS") == "1":
        return groups
    threads = load_notice_threads()
    if not threads:
        return groups
    by_id = {}
    for g in groups:
        if isinstance(g, dict) and g.get("id"):
            by_id[str(g.get("id"))] = g
    keep_ids = set()
    drop_ids = set()
    for th in threads:
        keep_id = _thread_keep_id(th)
        keep = by_id.get(keep_id)
        if keep is None:
            continue
        keep_ids.add(keep_id)
        patch = _thread_patch(th)
        new_items = []
        latest = ""
        merged = 0
        for mid in _thread_merge_ids(th):
            if mid == keep_id:
                continue
            mg = by_id.get(mid)
            if mg is None:
                continue
            merged += 1
            drop_ids.add(mid)
            for it in mg.get("items") or []:
                if not isinstance(it, dict):
                    continue
                it = dict(it)
                it["label"] = "补充通知"
                it["supplement"] = True
                new_items.append(it)
            latest = max(latest, str(mg.get("updatedAt") or ""))
        for it in th.get("items") or []:
            if not isinstance(it, dict):
                continue
            it = dict(it)
            it["label"] = "补充通知"
            it["supplement"] = True
            new_items.append(it)
        appended = _append_items(keep, new_items)
        ai_points = patch.pop("aiPoints", None)
        ai_segments = patch.pop("aiSegments", None)
        _apply_patch_to_group(keep, patch, appended=appended,
                              updated_at=str(th.get("updatedAt") or "") or latest)
        if ai_points:
            keep["aiPoints"] = ai_points
        if ai_segments:
            keep["aiSegments"] = ai_segments
        if appended or merged:
            keep["supplement"] = True
        if th.get("reason"):
            keep["threadReason"] = str(th.get("reason"))[:40]
        gid = str(keep.get("id") or "")
        if gid and patch:
            # 线程覆盖字段与「人工补丁 set 字段」同级：final 归一不得再改
            MANUAL_SET_FIELDS.setdefault(gid, set()).update(patch.keys())
    if not drop_ids:
        return groups
    out = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id") or "")
        if gid in drop_ids and gid not in keep_ids:
            continue
        out.append(g)
    return out


def load_manual_patches():
    try:
        data = json.loads(MANUAL_PATCHES.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data.get("patches") if isinstance(data, dict) else data
    return [x for x in (items or []) if isinstance(x, dict) and (x.get("id") or x.get("titleFallback"))]


def apply_manual_patches(groups):
    """人工补丁（最后应用）：按通知组 id 覆盖字段 / 追加 items / 合并重复组 / updatedAt。

    人工补丁是最终保障：药膳报名时间修正、g_dorm 长期安排都在
    data/notice-manual-patches.json 里维护，重建后不会丢。
    2026-11-19 扩展：
      - mergeInto: 把 id 指向的重复/局部组并入目标组（保留目标组身份，去重追加 items）；
      - dropImages: 删除该组所有图片 item（用户反馈「底部图片与通知内容无关」的兜底）。
    """
    patches = load_manual_patches()
    if not patches:
        return groups
    for p in patches:
        src = _find_group(groups, str(p.get("id") or ""), str(p.get("titleFallback") or ""))
        target = src
        if p.get("mergeInto"):
            dst = _find_group(groups, str(p.get("mergeInto") or ""), "")
            if not dst:
                continue
            target = dst
            if src and src is not dst:
                kept = []
                for it in (src.get("items") or []):
                    if not isinstance(it, dict):
                        continue
                    # [image] 是旧解析占位，不是真实内容，不并入
                    if it.get("kind") == "text" and str(it.get("text") or "").strip() in ("[image]", "[图片]"):
                        continue
                    kept.append(it)
                _append_items(dst, kept)
                groups = [g for g in groups if g is not src]
        if not target:
            continue
        if p.get("dropImages"):
            target["items"] = [it for it in (target.get("items") or [])
                               if not (isinstance(it, dict) and it.get("kind") == "img")]
        added = _append_items(target, p.get("appendItems") or [])
        _apply_patch_to_group(target, p.get("set") or {}, appended=added,
                              updated_at=str(p.get("updatedAt") or ""))
        if p.get("reason"):
            target["patchReason"] = str(p.get("reason"))[:200]
        # 记录人工补丁覆盖过的字段：final 归一 pass 不得覆盖（人工优先级最高）
        gid = str(target.get("id") or "")
        if gid:
            MANUAL_SET_FIELDS.setdefault(gid, set()).update(
                k for k in (p.get("set") or {}) if k in GROUP_PATCH_FIELDS)
    return groups


# ---------------------------------------------------------------- 契约 §1/§4：时间语义归一（数据侧）
# 顺序（Lead 2026-11-05 补充约束）：
#   1) groups 组装完成（attach_ai 之后）→ normalize_group_times(groups)：fill/repair；
#      ai_triage 生成的组已由 pipeline 的 notice_time 归一过，这里只补缺，不用正则覆盖已有值。
#   2) apply_manual_patches：人工补丁最后应用、优先级最高。
#   3) normalize_group_times(groups, final=True)：人工补丁后再做一次「只补缺」，
#      并按补丁追加的更正文本刷新报名窗口（人工 set 过的字段不动）。
MANUAL_SET_FIELDS = {}
_NOTICE_TIME_MODULE = []


def _notice_time_module():
    """pipeline 提供的 notice_time.py（G:\\ClassTools\\briefdesk\\scripts，已在 sys.path）；无则返回 None。"""
    if not _NOTICE_TIME_MODULE:
        try:
            import notice_time  # noqa: E402
            _NOTICE_TIME_MODULE.append(notice_time)
        except Exception:
            _NOTICE_TIME_MODULE.append(None)
    return _NOTICE_TIME_MODULE[0]


_ACTIVITY_RE = re.compile(r"报名|招募|征集|收集表|开群|志愿")
_CORRECTION_RE = re.compile(r"补充|更正|修正|修改|延期|改为|调整")
_SIGNUP_SEG_RE = re.compile(r"报名|收集表|开群|开放|报名表|群聊")
_CUE_END = re.compile(r"截止|截至|结束|满员|关闭|前完成|前提交|前报名|前上传|前填写|之前|以前|前$")
_CUE_START = re.compile(r"开放|开始报名|报名开始|开群")
_PERIOD_RE = r"(上午|下午|晚上|傍晚|中午|凌晨)"
_WINDOW_RANGE_RE = re.compile(
    r"(?:(?P<y>20\d{2})\s*年\s*)?(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日号]?\s*"
    r"(?P<p1>上午|下午|晚上|傍晚|中午|凌晨)?\s*(?P<h1>\d{1,2})\s*[:：点时]\s*(?P<n1>半|\d{1,2})?\s*分?\s*"
    r"[-—–~～至到]\s*"
    r"(?P<p2>上午|下午|晚上|傍晚|中午|凌晨)?\s*(?P<h2>\d{1,2})\s*[:：点时]\s*(?P<n2>半|\d{1,2})?\s*分?"
)
_DATE_RANGE_RE = re.compile(
    r"(?:(?P<y>20\d{2})\s*年\s*)?(?P<m1>\d{1,2})\s*月\s*(?P<d1>\d{1,2})\s*[日号]?\s*[-—–~～至到]\s*"
    r"(?:(?P<y2>20\d{2})\s*年\s*)?(?P<m2>\d{1,2})\s*月\s*(?P<d2>\d{1,2})\s*[日号]?"
)


def _iso_of(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00") if isinstance(dt, datetime) else None


def _sig_clock(period, hour_s, minute_s, ref=None):
    if not hour_s:
        return None
    mi = "半" if minute_s == "半" else (minute_s if minute_s else "0")
    return _clock(period, str(hour_s), str(mi), ref)


def _group_item_texts(g, include_name=False):
    """[(text, item_time)]：items（含合并转发 messages）里的用户可见正文文本，按出现顺序。

    时间抽取只用 item.text（pipeline 2026-11-06 同步：item.name/note 会制造假 cue，
    例如「报名表」「选可参加时段」）；include_name 仅供少数兼容场景显式打开。
    """
    out = []
    for it in g.get("items") or []:
        if not isinstance(it, dict):
            continue
        it_time = str(it.get("time") or "")
        fields = ("text", "name") if include_name else ("text",)
        for k in fields:
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                out.append((v, it_time))
        for m in it.get("messages") or []:
            if not isinstance(m, dict):
                continue
            mt = str(m.get("time") or it_time)
            for k in fields:
                v = m.get(k)
                if isinstance(v, str) and v.strip():
                    out.append((v, mt))
    return out


def _group_all_text(g, with_summary=True):
    texts = [t for t, _ in _group_item_texts(g)]
    if with_summary:
        for k in ("title", "summary", "aiSummary"):
            v = g.get(k)
            if isinstance(v, str) and v.strip():
                texts.append(v)
        for p in g.get("aiPoints") or []:
            if isinstance(p, str) and p.strip():
                texts.append(p)
    return "\n".join(texts)


def _group_anchor(g):
    for it in g.get("items") or []:
        if isinstance(it, dict) and it.get("time"):
            ref = _parse_ref_time(it.get("time"))
            if ref:
                return ref
    return None


def _has_correction(g):
    for it in g.get("items") or []:
        if not isinstance(it, dict):
            continue
        if str(it.get("label") or "") == "补充通知":
            return True
        if _CORRECTION_RE.search(str(it.get("text") or "")):
            return True
    return False


def _has_supplement_item(g):
    """真正的补充/更正来源：追加的「补充通知」item、follow 消息或 item.supplement=true。

    不能用「任意正文出现 修改/补充」判断——活动原文里的「进群修改群昵称」不是更正，
    曾导致药膳 c1 的 signup 被活动周期误覆盖（Lead 2026-11-05 修）。
    """
    for it in g.get("items") or []:
        if not isinstance(it, dict):
            continue
        if it.get("supplement") is True:
            return True
        if str(it.get("label") or "") == "补充通知":
            return True
        if str(it.get("kind") or "") == "follow":
            return True
    return False


def _signup_from_notice_time(g):
    """用 pipeline 的 notice_time.extract_signup_window（单一真源）重算报名窗口。"""
    nt = _notice_time_module()
    if nt is None:
        return None, None
    try:
        text = "\n".join(t for t, _ in _group_item_texts(g))
        ref = None
        try:
            ref = nt.ref_time_of(g)
        except Exception:
            ref = _group_anchor(g)
        return nt.extract_signup_window(text, ref)
    except Exception:
        return None, None


_SIGNUP_LABEL_RE = re.compile(
    r"报名时间|报名日期|报名时段|报名窗口|报名开始时间|报名截止时间|报名开始|报名截止|截止报名|"
    r"收集表开放时间|收集表报名时间|收集表截止时间|收集表开放|收集表截止|"
    r"开群时间|开放报名|开始报名|开放QQ群|开放群聊|开放活动群|开放报名表")
# 报到/作品提交类语境不是报名窗口（如「作品提交截止 11-12」「11-08 前提交原视频」）
_SIGNUP_NEG_RE = re.compile(r"作品|原图|原视频|截图|活动结束|闭幕|总结|签到签退")


def _near_label(pos, labels, before=12, after=8):
    for item in labels:
        ls, le = item[0], item[1]
        if 0 <= pos - le <= before or 0 <= ls - pos <= after:
            return True
    return False


def _parse_signup_segment(seg, ref):
    """一个「报名/收集表/开群」片段 → (start_dt, end_dt)，解析失败返回 None。

    优先级：带报名标签的时间段（如「报名时间：11-07 12:00—18:00」）→
    报名标签附近的时间点（按标签语义判断开始/截止）→ 截止/开放语境的兜底时间点。
    报到/作品提交类语境（作品、原视频、截图…）不算报名窗口。
    """
    ref = ref or datetime.now()
    # 「晚八点 / 早八点」这类 builder 旧解析器不认的钟点，先补成「晚上/上午」（不动 今晚/明晚）
    seg = re.sub(r"(?<![今明后昨])晚(?=[0-9一二三四五六七八九十]+\s*[点时])", "晚上", seg)
    seg = re.sub(r"(?<![今明后昨])早(?=[0-9一二三四五六七八九十]+\s*[点时])", "上午", seg)
    labels = [(m.start(), m.end(), m.group(0)) for m in _SIGNUP_LABEL_RE.finditer(seg)]
    # A) 带标签的时间段：报名时间：11-07 12:00—18:00
    for m in _WINDOW_RANGE_RE.finditer(seg):
        gd = m.groupdict()
        if not _near_label(m.start(), labels):
            continue
        c1 = _sig_clock(gd.get("p1"), gd.get("h1"), gd.get("n1"), ref)
        c2 = _sig_clock(gd.get("p2") or gd.get("p1"), gd.get("h2"), gd.get("n2"), ref)
        try:
            mon, day = int(gd["m"]), int(gd["d"])
        except (TypeError, ValueError):
            continue
        s = _make_dt(mon, day, c1[0], c1[1], ref, gd.get("y")) if c1 else None
        e = _make_dt(mon, day, c2[0], c2[1], ref, gd.get("y")) if c2 else None
        if s or e:
            return (s, e)
    pts = sorted(_candidates(seg, ref), key=lambda x: x[1])  # (dt, start, end)
    # B) 报名标签附近的时间点，按标签语义定为开始/截止
    if labels and pts:
        for lab_start, lab_end, label in labels:
            cand = min(pts, key=lambda x: min(abs(x[1] - lab_end), abs(x[2] - lab_start)))
            if "截止" in label or "结束" in label:
                return (None, cand[0])
            return (cand[0], None)
    # C) 截止/开放语境兜底（排除作品提交/报到类）
    m = _CUE_END.search(seg) or _CUE_START.search(seg)
    if m and pts and not _SIGNUP_NEG_RE.search(seg):
        cand = min(pts, key=lambda x: min(abs(x[1] - m.start()), abs(x[2] - m.end())))
        if _CUE_END.search(seg) and not _CUE_START.search(seg):
            return (None, cand[0])
        if _CUE_START.search(seg) and not _CUE_END.search(seg):
            return (cand[0], None)
        return (cand[0], None)
    return None


_SIGNUP_LABEL_RE = re.compile(
    r"报名时间|报名日期|报名时段|报名开始|报名截止|开群时间|开群|收集表开放|收集表截止|"
    r"收集表报名|开放报名|开始报名|报名表|开放")


def _signup_windows(g):
    """从全部 item 文本里抽取报名窗口；后出现的消息（补充/更正）覆盖先前的值。

    只认「带报名标签」或「报名类通知里带 截止/开放 语境」的片段，
    避免把活动时间范围（11.4-6 14:00-17:00）误当报名窗口。
    """
    start = end = None
    items = _group_item_texts(g)
    joined = "\n".join(t for t, _ in items)
    signupish = bool(_ACTIVITY_RE.search(joined))
    for text, t in items:
        ref = _parse_ref_time(t) or _group_anchor(g)
        for seg in re.split(r"[。！？!?；;\n]", text):
            seg = seg.strip()
            if not seg:
                continue
            label = bool(_SIGNUP_LABEL_RE.search(seg))
            cue = bool(_CUE_END.search(seg) or _CUE_START.search(seg))
            if not (label or (signupish and cue)):
                continue
            win = _parse_signup_segment(seg, ref)
            if not win:
                continue
            s, e = win
            if s:
                start = s
            if e:
                end = e
    if start and end and end < start:
        start, end = end, start
    return start, end, signupish


_SHORT_ACTION_MAP = {
    "报送姓名截止": "报送截止",
    "集合点名": "点名",
    "活动开始": "开始",
    "签到开始": "签到",
    "签到签退": "签到",
    "比赛开始": "比赛",
    "考试开始": "考试",
    "报名已截止": "报名截止",
    "已截止": "截止",
}


def _short_action(a):
    """契约 §0.2：动作 ≤6 字（优先 2–4 字），数据侧与显示侧同口径。"""
    s = re.sub(r"\s+", "", str(a or ""))
    if not s:
        return ""
    if s in _SHORT_ACTION_MAP:
        return _SHORT_ACTION_MAP[s]
    return s[:6] if len(s) > 6 else s


_PERIOD_HOURS = (("凌晨", 0), ("早上", 8), ("上午", 9), ("中午", 12),
                 ("下午", 14), ("傍晚", 18), ("晚上", 19))
_FALLBACK_CLOCK_RE = re.compile(
    r"(?:(上午|下午|晚上|中午|早上|凌晨|傍晚)\s*)?([0-9]{1,2})\s*[:：点时]\s*(半|[0-9]{1,2})?\s*分?")
_FALLBACK_DAY_RE = re.compile(r"(\d{1,2})\s*[号日]")


def _group_plain_text(g):
    return "\n".join(t for t, _ in _group_item_texts(g))


def _event_from_text_fallback(text, anchor):
    """builder 兜底：文本只有「下午」/「5号上午9:10」这类相对时间时补 eventAt。"""
    if not text or not isinstance(anchor, datetime):
        return None
    ref = anchor
    m = _FALLBACK_CLOCK_RE.search(text)
    clock = None
    if m:
        period, hh, mi = m.group(1), m.group(2), m.group(3)
        clock = _clock(period, hh, "半" if mi == "半" else (mi or "0"), ref)
        if clock is None:
            clock = (9, 0)
    day = None
    for dm in _FALLBACK_DAY_RE.finditer(text):
        n = int(dm.group(1))
        if 1 <= n <= 31:
            day = n
            break
    if clock is None:
        for word, hour in _PERIOD_HOURS:
            if word in text:
                clock = (hour, 0)
                break
    if clock is None and day is None:
        return None
    if clock is None:
        clock = (9, 0)
    if day is None:
        day = ref.day
    try:
        return datetime(ref.year, ref.month, day, clock[0], clock[1])
    except ValueError:
        return None


def _event_from_text(g, exclude=None):
    """eventAt 单一真源：notice_time.extract_event（模块可用时只认它，含事件语义闸门）；
    仅 nt 模块缺失时才走 builder 旧兜底。"""
    text = _group_plain_text(g)
    anchor = _group_anchor(g)
    nt = _notice_time_module()
    if nt is not None:
        try:
            return nt.extract_event(text, anchor, exclude=exclude)
        except Exception:
            return None
    return _event_from_text_fallback(text, anchor)


def _is_midnight_iso(value):
    dt = _parse_ref_time(value)
    return dt is not None and dt.hour == 0 and dt.minute == 0


def _infer_deadline_action(g, text):
    """旧数据 fallback（契约 §1/§0.2）：按文本推断截止动作（短词），兜底「截止」。"""
    t = str(text or "")
    if re.search(r"选课", t):
        return _short_action("选课截止")
    if re.search(r"缴费|交费|学费|费用", t):
        return _short_action("缴费截止")
    if re.search(r"投稿|征文|作品|手抄报|邮箱", t):
        return _short_action("投稿截止")
    if re.search(r"报送|申报", t) and re.search(r"姓名", t):
        return _short_action("报送姓名截止")
    if re.search(r"报名|招募|征集|收集表|开群|志愿", t):
        return _short_action("报名截止")
    if re.search(r"提交|报送|申报|发送|上传|发给我|发至", t):
        return _short_action("提交截止")
    return "截止"


def _infer_event_action(g, text):
    """旧数据 fallback（§0.2 短词）：集合/点名/签到/上课/比赛/考试/测试 → 对应动作。"""
    t = str(text or "")
    if re.search(r"集合|点名", t):
        return _short_action("集合点名")
    if re.search(r"签到|签退", t):
        return _short_action("签到开始")
    if re.search(r"比赛", t):
        return _short_action("比赛开始")
    if re.search(r"考试", t):
        return _short_action("考试开始")
    if re.search(r"测试|补测|体测", t):
        return _short_action("测试开始")
    if re.search(r"上课|课次|课堂", t):
        return _short_action("上课")
    if re.search(r"活动", t):
        return _short_action("活动开始")
    return ""


def _normalize_iso_fields(g):
    """ISO 字段校验：AI 常返回 YYYY-MM-DDTHH:MM（无时区），统一补 +08:00。"""
    for k in ("deadline", "eventAt", "expireAt", "signupStart", "signupEnd"):
        v = g.get(k)
        if v:
            nv = _patch_iso(v)
            g[k] = nv or v
    for ext in g.get("extensions") or []:
        if isinstance(ext, dict) and ext.get("deadline"):
            ext["deadline"] = _patch_iso(ext["deadline"]) or ext["deadline"]


def _repair_midnight_event(g):
    """历史脏值修复：eventAt 恰好 00:00 时按文本钟点/时段重算（不新增 eventAt）。"""
    ev = _event_from_text(g)
    if ev is not None:
        return ev
    return _event_from_text_fallback(_group_plain_text(g), _group_anchor(g))


def _normalize_group_times_local(g, final=False, nt_available=False):
    """builder 确定性兜底。

    pipeline 2026-11-06 同步：notice_time 是单一真源。nt_available=True 时：
    - 不新增/覆盖 signup/deadline/eventAt（只做 00:00 脏值修复与动作缩写）；
    - final pass 仅对「补充通知」卡用 notice_time.extract_signup_window 刷新报名窗口。
    nt_available=False（模块缺失）时才走旧版完整本地解析兜底。
    """
    if not isinstance(g, dict):
        return
    _normalize_iso_fields(g)
    manual = MANUAL_SET_FIELDS.get(str(g.get("id") or ""), set())
    item_joined = "\n".join(t for t, _ in _group_item_texts(g))
    all_text = _group_all_text(g)
    anchor = _group_anchor(g)
    start, end, activityish = _signup_windows(g)
    if isinstance(g.get("recurrence"), dict) and g["recurrence"].get("freq"):
        activityish = False

    def fill_missing(key, val):
        if val is None or str(val) == "" or key in manual:
            return False
        cur = g.get(key)
        if cur in (None, ""):
            g[key] = val
            return True
        return False

    # 1) 报名窗口（活动报名优先，契约 §4）
    if final:
        # 只认真正的补充/更正来源（label=补充通知 / follow / item.supplement），
        # 且刷新时优先用 pipeline 的 notice_time.extract_signup_window（单一真源）。
        if _has_supplement_item(g):
            s2, e2 = _signup_from_notice_time(g)
            if not (s2 and e2):
                s2, e2 = start, end
            if s2 and e2:
                if "signupStart" not in manual and str(g.get("signupStart") or "") != _iso_of(s2):
                    g["signupStart"] = _iso_of(s2)
                if "signupEnd" not in manual and str(g.get("signupEnd") or "") != _iso_of(e2):
                    g["signupEnd"] = _iso_of(e2)
            elif not nt_available:
                fill_missing("signupStart", _iso_of(start))
                fill_missing("signupEnd", _iso_of(end))
        elif not nt_available:
            fill_missing("signupStart", _iso_of(start))
            fill_missing("signupEnd", _iso_of(end))
    elif not nt_available:
        fill_missing("signupStart", _iso_of(start))
        fill_missing("signupEnd", _iso_of(end))
        # 旧数据（非 ai_triage）：活动报名类完全没有报名窗口时，截止即报名截止
        if (not g.get("aiTriage") and activityish and _ACTIVITY_RE.search(item_joined)
                and not g.get("signupStart") and not g.get("signupEnd")
                and g.get("deadline") and "signupEnd" not in manual):
            dl = _parse_ref_time(g.get("deadline"))
            if dl:
                g["signupEnd"] = _iso_of(dl)
        # 延期：报名截止取最后一条 extension deadline（与 deadlineOf 口径一致）
        exts = [e for e in (g.get("extensions") or []) if isinstance(e, dict) and e.get("deadline")]
        if exts and activityish and _ACTIVITY_RE.search(item_joined) and not g.get("signupEnd"):
            dl = _parse_ref_time(exts[-1].get("deadline"))
            if dl:
                g["signupEnd"] = _iso_of(dl)
        # 补齐 deadline（仅完全缺失时；ai_triage 组不动，避免覆盖 AI 归一结果）
        if not g.get("aiTriage"):
            if not g.get("deadline") and not g.get("eventAt") and item_joined:
                val = extract_deadline(item_joined, anchor)
                if val:
                    g["deadline"] = val
            if "eventAt" not in manual and not g.get("deadline"):
                ev = None
                if not g.get("eventAt"):
                    ev = _event_from_text(g)
                elif _is_midnight_iso(g.get("eventAt")):
                    ev = _event_from_text(g)
                if isinstance(ev, datetime):
                    g["eventAt"] = _iso_of(ev)
    else:
        # nt 单一真源：仅修历史 00:00 脏值，不新增 signup/deadline/eventAt
        if ("eventAt" not in manual and g.get("eventAt") and _is_midnight_iso(g.get("eventAt"))
                and not (isinstance(g.get("recurrence"), dict) and g["recurrence"].get("freq"))):
            ev = _repair_midnight_event(g)
            if isinstance(ev, datetime):
                g["eventAt"] = _iso_of(ev)

    # 2) 动作：缺省/非法/泛化（旧数据）→ 按文本推断更具体动作；已有长动作按 §0.2 缩写
    if "deadlineAction" not in manual:
        cur = str(g.get("deadlineAction") or "").strip()
        if g.get("deadline"):
            if not cur or "截止" not in cur or cur == "截止":
                inf = _infer_deadline_action(g, all_text)
                if inf and inf != cur:
                    g["deadlineAction"] = inf[:12]
            else:
                short = _short_action(cur)
                if short and short != cur:
                    g["deadlineAction"] = short[:12]
        else:
            g.pop("deadlineAction", None)
    if "eventAction" not in manual:
        cur = str(g.get("eventAction") or "").strip()
        if g.get("eventAt"):
            if not cur or cur == "开始":
                inf = _infer_event_action(g, all_text)
                if inf and inf != cur:
                    g["eventAction"] = inf[:12]
            else:
                short = _short_action(cur)
                if short and short != cur:
                    g["eventAction"] = short[:12]
        else:
            g.pop("eventAction", None)
    return g


def _drop_synthetic_signup(g):
    """pipeline normalize 会给「活动 + 投稿/参赛」类卡也合成 signupEnd=deadline；
    契约 §4 只有报名/招募/征集/收集表/开群/志愿才算活动报名类 → 无报名语义时清掉合成值。"""
    if not (g.get("signupStart") or g.get("signupEnd")):
        return
    text = _group_all_text(g)
    if re.search(r"报名|招募|征集|收集表|开群|志愿", text):
        return
    ss = _parse_ref_time(g.get("signupStart"))
    se = _parse_ref_time(g.get("signupEnd"))
    dl = _parse_ref_time(g.get("deadline"))

    def same(a, b):
        return a is not None and b is not None and abs((a - b).total_seconds()) <= 60

    if (se and dl and same(se, dl)) or (ss and dl and same(ss, dl)):
        g.pop("signupStart", None)
        g.pop("signupEnd", None)


def normalize_group_times(groups, final=False):
    """契约 §4 数据侧归一。

    pipeline 2026-11-06 同步：notice_time 是单一真源。
    - 非 final：只调 notice_time.normalize_notice_times(g)（signup/deadline/eventAt/动作）；
      builder 不再用本地解析覆盖/补写这些字段（nt 模块缺失时才启用旧兜底）。
    - final（人工补丁后）：仅对「补充通知」卡刷新 signup + 动作缩写；人工 set 字段不动。
    """
    nt = None if final else _notice_time_module()
    nt_available = _notice_time_module() is not None
    for g in groups:
        if not isinstance(g, dict):
            continue
        if nt is not None:
            try:
                nt.normalize_notice_times(g)
            except Exception:
                pass
            if not nt_available:
                try:
                    ls, le, _is_signup = _signup_windows(g)
                    if ls and not g.get("signupStart"):
                        g["signupStart"] = _iso_of(ls)
                    if le and not g.get("signupEnd"):
                        g["signupEnd"] = _iso_of(le)
                except Exception:
                    pass
            # 投稿/征文类：无报名语义时清掉「signup==deadline」的合成值（显示取舍）
            try:
                _drop_synthetic_signup(g)
            except Exception:
                pass
        try:
            _normalize_group_times_local(g, final=final, nt_available=nt_available)
        except Exception:
            pass
    return groups


def _notice_corpus(g):
    parts = [str(g.get("title") or "")]
    for it in (g.get("items") or [])[:8]:
        parts.append(str(it.get("text") or it.get("name") or it.get("note") or ""))
    return re.sub(r"[\s\W_]+", "", "".join(parts).lower())


def _similar_notice(g, pool):
    """True when an auto QQ-text/OCR notice duplicates a notice already on the board."""
    n = _notice_corpus(g)
    if len(n) < 6:
        return False
    for e in pool:
        m = _notice_corpus(e)
        if len(m) < 6:
            continue
        # 短文本：沿用严格规则（相同开头/高相似度）
        if len(n) < 40 or len(m) < 40:
            if n[:18] in m or m[:18] in n:
                return True
            if difflib.SequenceMatcher(None, n[:240], m[:240]).ratio() >= 0.62:
                return True
            continue
        # 长文本（如 OCR 赛程表/名单）：要求多个长片段重叠或很高相似度，避免不同赛程互杀
        shared = 0
        limit = min(len(n), 420) - 16
        for i in range(0, max(0, limit), 4):
            if n[i:i + 16] in m:
                shared += 1
                if shared >= 3:
                    return True
        if difflib.SequenceMatcher(None, n[:320], m[:320]).ratio() >= 0.72:
            return True
    return False


import base64
import mimetypes

# 需求 7：单个附件内嵌上限 ~1.5MB（避免 board-data / 内嵌模板 / 云端 body 过大）。
MAX_EMBED_BYTES = int(1.5 * 1024 * 1024)
_QQ_FILE_INDEX = None


def _qq_file_index():
    """data/qq-files 目录索引：{精确文件名: Path} + 文件列表（单次构建缓存）。"""
    global _QQ_FILE_INDEX
    if _QQ_FILE_INDEX is not None:
        return _QQ_FILE_INDEX
    exact, files = {}, []
    try:
        if QQ_FILES.exists():
            for p in sorted(QQ_FILES.iterdir()):
                if p.is_file():
                    exact[p.name] = p
                    files.append(p)
    except Exception:
        pass
    _QQ_FILE_INDEX = (exact, files)
    return _QQ_FILE_INDEX


def resolve_qq_file(name):
    """按通知里的文件名找 data/qq-files 下的本地文件（精确 → 归一化 → 宽容匹配）。"""
    if not name:
        return None
    exact, files = _qq_file_index()
    p = exact.get(Path(str(name)).name)
    if p is not None and p.exists():
        return p
    target = qq_file_names.norm_key(name)
    if target:
        for f in files:
            if qq_file_names.norm_key(f.name) == target:
                return f
    return qq_file_names.best_match(name, files, threshold=0.8)


def qq_file_uri(name):
    p = resolve_qq_file(name)
    if p is None:
        return ""
    try:
        if p.stat().st_size <= 0 or p.stat().st_size > MAX_EMBED_BYTES:
            return ""
        blob = p.read_bytes()
    except OSError:
        return ""
    head = blob[:8]
    if head.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif head.startswith(b"\x89PNG"):
        mime = "image/png"
    elif head.startswith(b"%PDF"):
        mime = "application/pdf"
    else:
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return "data:" + mime + ";base64," + base64.b64encode(blob).decode()


# ---------------------------------------------------------------- v2.0.0 微信附件
# 用户反馈「微信通知附件未识别」：ai_triage 现在会为微信图片/文件消息生成带 mediaKey 的
# items；wechat_media.py 负责把字节落地（微信文件在 msg/file 是明文；图片 V2 加密需密钥）。
WECHAT_MEDIA_MANIFEST = Path(r"G:\ClassTools\briefdesk\data\wechat-media.json")
ARCHIVE_CONTENTS = Path(r"G:\ClassTools\briefdesk\data\archive-contents.json")
_ARCHIVE_MAP = None
_WECHAT_MEDIA = None


def load_wechat_media_manifest():
    global _WECHAT_MEDIA
    if _WECHAT_MEDIA is not None:
        return _WECHAT_MEDIA
    try:
        data = json.loads(WECHAT_MEDIA_MANIFEST.read_text(encoding="utf-8"))
        items = data.get("items") if isinstance(data, dict) else {}
        _WECHAT_MEDIA = items if isinstance(items, dict) else {}
    except Exception:
        _WECHAT_MEDIA = {}
    return _WECHAT_MEDIA


def _file_data_uri(p):
    try:
        if p is None or not p.exists():
            return ""
        if p.stat().st_size <= 0 or p.stat().st_size > MAX_EMBED_BYTES:
            return ""
        blob = p.read_bytes()
    except OSError:
        return ""
    head = blob[:8]
    if head.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif head.startswith(b"\x89PNG"):
        mime = "image/png"
    elif head.startswith(b"%PDF"):
        mime = "application/pdf"
    else:
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return "data:" + mime + ";base64," + base64.b64encode(blob).decode()


def wechat_media_uri(media_key):
    rec = load_wechat_media_manifest().get(str(media_key or ""))
    if not isinstance(rec, dict):
        return "", {}
    stored = str(rec.get("storedPath") or "")
    if stored:
        uri = _file_data_uri(Path(stored))
        if uri:
            return uri, rec
    return "", rec


def apply_wechat_media_items(groups):
    """微信附件 items：mediaKey → data URI；无字节时保留条目并标「待获取」。

    - kind=file：附 url（data URI）与 size；无字节保持无 url（前端显示「待获取」）。
    - kind=img：有字节填 src；无字节（V2 图片需密钥）保留 img 条目 + pending 标记，
      模板渲染「图片附件 · 待获取」。
    """
    manifest = load_wechat_media_manifest()
    if not manifest:
        return groups
    applied = pending = 0
    for g in groups:
        for it in g.get("items") or []:
            if not isinstance(it, dict):
                continue
            key = str(it.get("mediaKey") or "")
            if not key:
                continue
            uri, rec = wechat_media_uri(key)
            kind = it.get("kind")
            status = str(rec.get("status") or "")
            if kind == "file":
                if uri:
                    it["url"] = uri
                    it["size"] = "%d KB" % max(1, round(int(rec.get("bytes") or 0) / 1024.0))
                    it["note"] = "微信群文件 · 自动获取"
                    applied += 1
                else:
                    it["pending"] = True
                    it.setdefault("note", "微信群文件 · 待获取（QQ/微信下载后自动上线）")
                    pending += 1
            elif kind == "img":
                if uri:
                    it["src"] = uri
                    it["caption"] = it.get("caption") or "微信群图片"
                    it.pop("pending", None)
                    applied += 1
                else:
                    it["pending"] = True
                    note = "微信群图片 · 待获取"
                    if status == "pending_key":
                        note = "微信群图片 · 待获取（需微信图片密钥）"
                    it["note"] = note
                    pending += 1
    try:
        print("wechat media: applied=%d pending=%d" % (applied, pending))
    except Exception:
        pass
    return groups


# ---------------------------------------------------------------- v2.0.0 压缩包附件识别
# 用户反馈「压缩包附件未识别」：archive_scan.py 安全解压 + 递归识别内部文件，
# 产出 data/archive-contents.json；这里把「包内文件清单 + 摘要」挂到对应附件条目。

def load_archive_map():
    """归一化文件名 → archive_scan 记录（按内容 hash 缓存）。"""
    global _ARCHIVE_MAP
    if _ARCHIVE_MAP is not None:
        return _ARCHIVE_MAP
    out = {}
    try:
        data = json.loads(ARCHIVE_CONTENTS.read_text(encoding="utf-8"))
        items = data.get("items") if isinstance(data, dict) else {}
        for rec in (items or {}).values():
            if not isinstance(rec, dict):
                continue
            name = str(rec.get("file") or "")
            if not name:
                continue
            out[qq_file_names.norm_key(name)] = rec
    except Exception:
        out = {}
    _ARCHIVE_MAP = out
    return out


def _archive_lookup(name):
    if not name:
        return None
    m = load_archive_map()
    return m.get(qq_file_names.norm_key(name))


def _inner_kind_label(kind):
    return {"doc": "文档", "pdf": "PDF", "image": "图片", "archive": "压缩包",
            "too_large": "过大", "bomb": "已跳过", "read_error": "读取失败", "other": "文件"}.get(
        kind or "other", "文件")


def build_archive_view(rec):
    """archive_scan 记录 → 前端展示结构（包内文件清单 + 摘要 + 小文件可直接下载）。"""
    if not isinstance(rec, dict):
        return None
    files = []
    for f in rec.get("files") or []:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name") or "")
        item = {"name": name.rsplit("/", 1)[-1] if name else "文件",
                "path": name, "kind": _inner_kind_label(f.get("kind")),
                "size": fmt_bytes_simple(int(f.get("size") or 0)),
                "textLen": int(f.get("textLen") or 0)}
        saved = str(f.get("saved") or "")
        if saved and Path(saved).exists():
            uri = _file_data_uri(Path(saved))
            if uri:
                item["url"] = uri
        files.append(item)
    summary = str(rec.get("aiSummary") or "").strip()
    if not summary and rec.get("textPreview"):
        summary = str(rec["textPreview"])[:110]
    return {
        "status": rec.get("status") or "ok",
        "count": len(files),
        "files": files[:50],
        "summary": summary[:160],
        "aiTitle": str(rec.get("aiTitle") or "")[:24],
        "aiPoints": [str(p)[:12] for p in (rec.get("aiPoints") or [])][:6],
        "sha256": str(rec.get("sha256") or "")[:12],
    }


def fmt_bytes_simple(n):
    n = int(n or 0)
    if n < 1024:
        return "%d B" % n
    if n < 1048576:
        return "%.0f KB" % (n / 1024.0)
    return "%.1f MB" % (n / 1048576.0)


def apply_archive_items(groups):
    """为压缩包附件条目补充「包内文件清单 + 摘要」（失败保留原包 + 待识别状态）。"""
    amap = load_archive_map()
    if not amap:
        return groups
    ok = failed = 0
    for g in groups:
        for it in g.get("items") or []:
            if not isinstance(it, dict) or it.get("kind") != "file":
                continue
            name = str(it.get("name") or "")
            if not name or qq_file_names.ext_of(name) not in (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"):
                continue
            rec = _archive_lookup(name)
            if not rec:
                continue
            view = build_archive_view(rec)
            if not view:
                continue
            it["archive"] = view
            if view.get("status") in ("ok", "empty") and view.get("count"):
                it["note"] = "压缩包 · 已识别 %d 个文件" % view["count"]
                it["archiveOk"] = True
                ok += 1
            else:
                it["pending"] = True
                it["note"] = "压缩包 · 解压识别失败（原包保留，可在 QQ/微信查看）"
                it["archiveOk"] = False
                failed += 1
    try:
        print("archive items: ok=%d failed=%d" % (ok, failed))
    except Exception:
        pass
    return groups


def _merged_msg_hash(merged):
    """与 ai_merged.py 完全一致的内容指纹：聊天记录消息变了必须重新聚类。"""
    lines = []
    for i, m in enumerate(merged.get("messages") or []):
        sender = (m.get("from") or "").strip()
        text = (m.get("text") or "").strip()
        lines.append("%d. " % i + ((sender + ": ") if sender else "") + text[:300])
    return hashlib.sha1("\n".join(lines).encode("utf-8", "replace")).hexdigest()


def expand_merged(groups):
    """Split merged chat records into AI-clustered notices (same topic stays together)."""
    if not AI_MERGED.exists():
        return groups
    try:
        cache = json.loads(AI_MERGED.read_text(encoding="utf-8"))
    except Exception:
        return groups
    out = []
    for g in groups:
        merged = next((it for it in g.get("items", []) if it.get("kind") == "merged"), None)
        entry = cache.get(g.get("id")) if merged else None
        clusters = (entry or {}).get("groups")
        # 缓存与当前聊天记录内容不一致（例如聊天记录展开后消息变多/变全）：
        # 本次不要用旧索引硬拆，先把 merged 原样留给 ai_merged 重新聚类。
        if merged and clusters and (entry or {}).get("hash") != _merged_msg_hash(merged):
            clusters = None
        if not merged or not clusters:
            out.append(g)
            continue
        base_items = [it for it in g.get("items", []) if it.get("kind") != "merged"]
        for ci, c in enumerate(clusters):
            items = list(base_items) if ci == 0 else []
            for idx in c.get("indexes", []):
                if not isinstance(idx, int) or idx < 0 or idx >= len(merged.get("messages", [])):
                    continue
                m = merged["messages"][idx]
                kind = m.get("kind") or "text"
                if kind == "link" and m.get("url"):
                    items.append({"kind": "link", "label": "链接", "time": m.get("time", ""),
                                  "name": m.get("name") or m.get("text") or "链接",
                                  "url": m["url"], "text": m.get("text", "")})
                elif kind == "file":
                    items.append({"kind": "file", "label": "文件", "time": m.get("time", ""),
                                  "name": m.get("name") or m.get("text") or "文件",
                                  "url": qq_file_uri(m.get("name") or m.get("text")) or "",
                                  "text": m.get("text", "")})
                elif kind == "image":
                    src = qq_file_uri(m.get("name")) or m.get("url", "")
                    if src:
                        items.append({"kind": "img", "label": "图片", "time": m.get("time", ""),
                                      "name": m.get("name") or "图片",
                                      "src": src, "caption": m.get("text") or "图片"})
                elif kind == "mini":
                    items.append({"kind": "mini", "label": "小程序", "time": m.get("time", ""),
                                  "name": m.get("name") or "小程序", "note": m.get("text", ""),
                                  "url": m.get("url", "")})
                else:
                    items.append({"kind": "text", "label": "通知", "time": m.get("time", ""),
                                  "text": m.get("text", "")})
            text = "\n".join(it.get("text", "") for it in items)
            out.append({
                "id": g.get("id", "g") + "_c" + str(ci),
                "cat": classify_wechat(text),
                "title": (c.get("title") or g.get("title") or "通知")[:24],
                "aiSummary": _news_summary(c.get("summary"), 60),
                "aiPoints": c.get("points", []),
                "group": g.get("group", ""), "source": g.get("source", ""),
                "deadline": extract_deadline(text), "actionable": True,
                "items": items,
            })
    return out


def attach_ai(groups):
    if not AI_BRIEFS.exists():
        return
    try:
        data = json.loads(AI_BRIEFS.read_text(encoding="utf-8"))
    except Exception:
        return
    for g in groups:
        b = data.get(g.get("id"))
        if not isinstance(b, dict):
            continue
        summary = _news_summary(b.get("summary"), 60)
        points = [str(x).strip() for x in (b.get("points") or []) if str(x).strip()]
        title = (b.get("title") or "").strip()
        segments = []
        for seg in (b.get("segments") or []):
            if isinstance(seg, dict) and str(seg.get("text") or "").strip():
                segments.append({"type": str(seg.get("type") or "内容").strip()[:8],
                                 "text": str(seg.get("text") or "").strip()[:90]})
        if segments:
            g["aiSegments"] = segments[:10]
        if title:
            g["title"] = title[:24]
        if summary:
            g["aiSummary"] = summary
        if points:
            # 需求 8：不再截 3 条；AI 已按 1–6 条 ≤12 字生成，这里只做上限保护。
            g["aiPoints"] = points[:6]
        rec = b.get("recurrence")
        if isinstance(rec, dict) and rec.get("freq"):
            # 需求 9：长期安排透传（人工补丁可在最后覆盖）
            g["recurrence"] = rec


def apply_categories(groups):
    """AI 动态分类（2026-11-09 用户需求）：用 ai-categories.json 覆盖旧固定规则 cat。

    AI 不可用/缓存缺失时保留 `classify_wechat()` 的兜底分类，不阻塞管线；
    分类随近期通知增删（如军训季出现「军训」，过后自然消失）。
    """
    if not AI_CATEGORIES.exists():
        return
    try:
        data = json.loads(AI_CATEGORIES.read_text(encoding="utf-8"))
    except Exception:
        return
    assign = data.get("assign")
    if not isinstance(assign, dict) or not assign:
        return
    reserved = {"全部", "全部分类", "待处理", "已截止"}
    for g in groups:
        cat = str(assign.get(g.get("id")) or "").strip()
        cat = re.sub(r"\s+", "", cat)
        cat = re.sub(r"[<>&\"']", "", cat)  # 分类名来自 AI：源头剔除 HTML/JS 特殊字符
        # 只接受 2~6 字、非保留字；过滤「全部」等筛选哨兵，避免前端混淆
        if cat and 2 <= len(cat) <= 6 and cat not in reserved \
                and re.search(r"[\u4e00-\u9fffA-Za-z]", cat):
            g["cat"] = cat


# ---------------------------------------------------------------- 契约 §1.6：确定性时间保护
# ai_quality 对 deadline/eventAt/signup* 返回 null 时，不能无条件清空：
# 只要 notice_time 从原文能解析出同一日期（或原文含该日期字面、说明现值来自确定性抽取），
# 就保留现值；仅当 AI notes 明确说明现时间有误时才允许清空。
_TIME_AI_INVALID_RE = re.compile(
    r"(?:时间|日期|截止|报名|deadline|eventAt).{0,16}(?:错误|有误|误判|不准确|不对|作废|清空)"
    r"|(?:错误|有误|误判|不准确|不对|作废|清空).{0,16}(?:时间|日期|截止|报名|deadline|eventAt)",
    re.I)


def _ai_time_invalid_evidence(rec):
    """AI 质检 notes/reason 是否明确说明现时间有误（允许清空的唯一证据）。"""
    if not isinstance(rec, dict):
        return False
    text = " ".join(str(rec.get(k) or "") for k in ("notes", "note", "reason", "evidence"))
    return bool(_TIME_AI_INVALID_RE.search(text))


def _iso_date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except Exception:
        return None


def _time_date_tokens(value):
    """ISO 时间 → 原文里可能出现的同日期字面（MM-DD / M月D日 / YYYY-MM-DD…）。"""
    d = _iso_date(value)
    if d is None:
        return ()
    y, mo, da = d.year, d.month, d.day
    return ("%02d-%02d" % (mo, da), "%d-%d" % (mo, da), "%d月%d日" % (mo, da),
            "%d月%d号" % (mo, da), "%04d-%02d-%02d" % (y, mo, da),
            "%d年%d月%d日" % (y, mo, da))


def _deterministic_time_date(g, key):
    """用 notice_time（单一真源）从原文解析该时间字段 → date；失败/模块缺失 → None。"""
    nt = _notice_time_module()
    if nt is None:
        return None
    try:
        text = "\n".join(t for t, _ in _group_item_texts(g))
        if not text:
            return None
        try:
            ref = nt.ref_time_of(g)
        except Exception:
            ref = _group_anchor(g)
        if key in ("signupStart", "signupEnd"):
            start, end = nt.extract_signup_window(text, ref)
            dt = start if key == "signupStart" else end
        elif key == "deadline":
            dt = nt.extract_deadline(text, ref)
        elif key == "eventAt":
            dt = nt.extract_event(text, ref)
        else:
            return None
    except Exception:
        return None
    if isinstance(dt, datetime):
        return dt.date()
    return _iso_date(dt)


def _time_value_protected(g, key, cur):
    """现时间是否有确定性依据可保留：notice_time 解析一致，或原文出现该日期字面。"""
    if not cur:
        return False
    expected = _deterministic_time_date(g, key)
    if expected is not None and expected == _iso_date(cur):
        return True
    text = "\n".join(t for t, _ in _group_item_texts(g))
    return any(tok and tok in text for tok in _time_date_tokens(cur))


def apply_quality(groups):
    """AI 质检校正层（2026-11-09 用户第 6 条）：丢弃非通知/无内容，校正时间与过期状态。

    ai_quality.py 逐条给出：isNotice / dropReason / 时间字段 / signupWindows / expired / expireAt /
    可选 title、summary 修正。这里只做确定性套用；AI 失败/无结果时保持 ai_brief + notice_time 结果。
    """
    if not AI_QUALITY.exists():
        return groups
    try:
        data = json.loads(AI_QUALITY.read_text(encoding="utf-8"))
    except Exception:
        return groups
    recs = data.get("groups") if isinstance(data.get("groups"), dict) else {}
    if not recs:
        return groups
    out = []
    for g in groups:
        rec = recs.get(str(g.get("id")))
        r = rec.get("result") if isinstance(rec, dict) else None
        if not isinstance(r, dict):
            out.append(g)
            continue
        # 1) 不是通知 / 无内容 → 丢弃（置信度门槛，避免误删）
        conf = float(r.get("confidence") or 0)
        if r.get("isNotice") is False and conf >= 0.7:
            continue
        # 2) 可选标题修正（只在 AI 明确给出时覆盖）
        title = str(r.get("title") or "").strip()
        if title:
            g["title"] = title[:20]
        # 摘要：ai_brief 与质检层都按 2026-11-17「新闻导语」口径生成。两条都合格时，
        # 默认用质检层摘要（它看到全量上下文+附件识别内容，事实通常更全）；
        # 但若 ai_brief 摘要对原文关键事实（日期/时间/数量）覆盖更多，则保留 ai_brief 摘要。
        q_summary = _news_summary(r.get("summary"), 60) if r.get("summary") else ""
        if q_summary and notice_style is not None:
            try:
                if notice_style.hard_issues(notice_style.summary_issues(q_summary)):
                    q_summary = ""
            except Exception:  # noqa: BLE001
                pass
        if q_summary:
            brief_summary = str(g.get("aiSummary") or "").strip()
            brief_bad = False
            if brief_summary and notice_style is not None:
                try:
                    brief_bad = bool(notice_style.hard_issues(
                        notice_style.summary_issues(brief_summary)))
                except Exception:  # noqa: BLE001
                    brief_bad = False
            if brief_summary and not brief_bad:
                src_text = " ".join(str(it.get("text") or it.get("name") or "")
                                    for it in (g.get("items") or []))
                src_facts = _summary_facts(src_text)
                if src_facts and _summary_covers(brief_summary, src_facts) > \
                        _summary_covers(q_summary, src_facts):
                    q_summary = ""  # ai_brief 摘要覆盖更全 → 保留它
            if q_summary:
                g["summary"] = q_summary
                g["aiSummary"] = q_summary
        pts_ai = r.get("points")
        if isinstance(pts_ai, list) and pts_ai:
            g["aiPoints"] = [str(x).strip()[:12] for x in pts_ai if str(x).strip()][:6]
        # 3) 时间字段：字段存在=AI 的明确判断（null 表示没有/应清空）
        #    契约 §1.6：null 若与 notice_time/原文确定性证据一致则保留现值，避免误清未来安排。
        time_changed = False
        for key in ("deadline", "eventAt", "signupStart", "signupEnd"):
            if key not in r:
                continue
            val = r.get(key)
            cur = g.get(key)
            if val:
                g[key] = val
            elif cur and _time_value_protected(g, key, cur) and not _ai_time_invalid_evidence(r):
                pass  # 确定性时间保护：保留现值
            else:
                g.pop(key, None)
            if g.get(key) != cur:
                time_changed = True
        for key in ("deadlineAction", "eventAction"):
            if key in r:
                val = r.get(key)
                if val:
                    g[key] = val[:6]
                else:
                    g.pop(key, None)
        # 3b) 长期安排 recurrence（contract §1.1/§1.4，ai_quality CACHE_VER=2 新增）：
        #     键缺省=保持现有；null=明确删除；对象=替换（最终由 sanitize_recurrence 再做一次校验）。
        if "recurrence" in r:
            rec_ai = r.get("recurrence")
            if rec_ai is None:
                g.pop("recurrence", None)
            elif isinstance(rec_ai, dict) and str(rec_ai.get("freq") or "").strip():
                g["recurrence"] = rec_ai
        if time_changed:
            # 质检纠正了时间字段：旧的展示文案必须作废，避免页面继续显示旧时间
            g.pop("timeLabel", None)
        if any(k in r for k in ("deadline", "eventAt")) or r.get("expired") is True:
            g.pop("timeLabel", None)
        if "signupWindows" in r:
            wins = r.get("signupWindows")
            if isinstance(wins, list) and len(wins) >= 2:
                g["signupWindows"] = wins[:6]
                # 多报名窗口：把每个窗口的开始时间补进要点，保证卡片上能直接看到全部报名时间
                pts = [str(x).strip() for x in (g.get("aiPoints") or []) if str(x).strip()]
                extra = []
                for w in wins[:4]:
                    st = str(w.get("start") or "")
                    if len(st) >= 10:
                        label = "%s报名" % st[5:10]
                        if label not in pts and label not in extra:
                            extra.append(label[:12])
                for x in extra:
                    if len(pts) >= 6:
                        break
                    pts.append(x)
                if pts:
                    g["aiPoints"] = pts[:6]
                # 小程序/安卓不支持 signupWindows：signupStart/End 用「最早开始—最晚结束」跨度兜底，
                # 避免窗口全部结束后 chip 显示第一个窗口的 end（11-10）而不是最后窗口（11-12）。
                starts = [w.get("start") for w in wins if w.get("start")]
                ends = [w.get("end") for w in wins if w.get("end")]
                if starts:
                    g["signupStart"] = min(starts)
                if ends:
                    g["signupEnd"] = max(ends)
            else:
                g.pop("signupWindows", None)
        # 4) 过期判定（统一用 eventAt/expireAt 表达，三类客户端天然按“已过期”展示）
        if r.get("expired") is True:
            expire = r.get("expireAt")
            if expire:
                g["expireAt"] = expire
            elif not g.get("expireAt"):
                # 兜底：没有过期时间时取 deadline/eventAt 当天 23:59
                base = g.get("deadline") or g.get("eventAt") or g.get("signupEnd")
                if base:
                    try:
                        dt = datetime.fromisoformat(str(base).replace("Z", "+00:00"))
                        g["expireAt"] = dt.replace(hour=23, minute=59, second=0).strftime(
                            "%Y-%m-%dT%H:%M:%S+08:00")
                    except Exception:
                        pass
            # 没有任何主时间的过期通知：补 eventAt，保证状态机/客户端能显示已过期
            if not (g.get("deadline") or g.get("eventAt") or g.get("signupEnd")):
                base = g.get("expireAt")
                if base:
                    try:
                        dt = datetime.fromisoformat(str(base).replace("Z", "+00:00"))
                        g["eventAt"] = dt.replace(hour=9, minute=0, second=0).strftime(
                            "%Y-%m-%dT%H:%M:%S+08:00")
                    except Exception:
                        pass
        elif r.get("expired") is False:
            # AI 明确说未过期：只清掉质检层可能写过的过期标记，不动 deadline/eventAt
            g.pop("expired", None)
        out.append(g)
    return out


def sanitize_ai_points(groups, limit=12):
    """需求 8 最终兜底：aiPoints 每组 ≤6 条、单条 ≤12 字。

    AI 生成点来自多条路径（ai_brief / ai_merged / 旧缓存），任一漏限长都会破坏
    前端胶囊布局与验收（v2_notice_data_check D23）。这里统一截断：优先取「：」后的
    短值，仍超长按字截断；去重后最多 6 条。
    """
    for g in groups:
        pts = g.get("aiPoints")
        if not isinstance(pts, list):
            continue
        out = []
        for p in pts:
            s = str(p if p is not None else "").strip()
            if not s:
                continue
            if len(s) > limit:
                parts = re.split(r"[：:，,。；;]", s, maxsplit=1)
                tail = parts[1].strip() if len(parts) > 1 else ""
                s = (tail if 0 < len(tail) <= limit else s[:limit])
            s = s.strip(" ，,。；;：:")
            if s and s not in out:
                out.append(s)
        if out:
            g["aiPoints"] = out[:6]
        else:
            g.pop("aiPoints", None)
    return groups


# ---------------------------------------------------------------- 契约 §1.1：recurrence 兜底校验
RECUR_FREQS = ("daily", "weekly", "monthly_weeks", "monthly_day")
_RECUR_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _recur_until(value, start_at=None):
    """合法 until → 规范化字符串；非法或早于 startAt 当天 → None（丢弃该字段）。"""
    s = str(value or "").strip()
    if not s:
        return None
    start_date = _iso_date(start_at)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            d = datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None
        if start_date is not None and d < start_date:
            return None
        return d.isoformat()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if start_date is not None and dt.date() < start_date:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}", s):
        s = s.replace(" ", "T", 1)
    return _patch_iso(s) or s


def sanitize_recurrence(g):
    """契约 §1.1 兜底：freq 合法 + time HH:MM 才保留；无 time 一律丢弃 recurrence；
    until 支持 YYYY-MM-DD（含当天）/ISO datetime，非法或早于 startAt 只丢弃 until。"""
    if not isinstance(g, dict):
        return g
    rec = g.get("recurrence")
    if rec is None:
        return g
    if not isinstance(rec, dict):
        g.pop("recurrence", None)
        return g
    freq = str(rec.get("freq") or "").strip().lower()
    m = _RECUR_TIME_RE.match(str(rec.get("time") or "").strip())
    hh = int(m.group(1)) if m else -1
    mm = int(m.group(2)) if m else -1
    if freq not in RECUR_FREQS or hh < 0 or hh > 23 or mm < 0 or mm > 59:
        g.pop("recurrence", None)
        return g
    out = dict(rec)
    out["freq"] = freq
    out["time"] = "%02d:%02d" % (hh, mm)
    if "until" in out:
        until = _recur_until(out.get("until"), out.get("startAt"))
        if until:
            out["until"] = until
        else:
            out.pop("until", None)
    g["recurrence"] = out
    return g


def sanitize_recurrences(groups):
    for g in groups:
        sanitize_recurrence(g)
    return groups


def load_wechat_notices():
    """Grouped WeChat notices produced by fetch_wechat_notices.py (no sender fields)."""
    if not WECHAT_NOTICES.exists():
        return []
    try:
        data = json.loads(WECHAT_NOTICES.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    if not isinstance(data, list):
        return out
    for n in data:
        if not isinstance(n, dict):
            continue
        items = [it for it in n.get("items", []) if isinstance(it, dict)]
        joined = "\n".join(it.get("text", "") for it in items)
        if not n.get("deadline"):
            n["deadline"] = extract_deadline(joined)
        n["source"] = "微信"
        n["group"] = "微信"
        n["actionable"] = True
        n["items"] = items
        for it in items:
            it.pop("from", None)
        out.append(n)
    return out


def classify_wechat(text):
    if any(k in text for k in ("学费", "缴费", "发票", "电子票")):
        return "缴费"
    if any(k in text for k in ("招聘", "志愿", "活动", "运动会", "征文", "手抄报", "比赛", "讲座", "培训")):
        return "活动"
    if any(k in text for k in ("课", "教务", "考试", "调课", "选课", "体测")):
        return "教务"
    return "班级事务"


def load_wechat_group_notices():
    """WeChat group messages -> standard notice groups (sender hidden)."""
    if not WECHAT_INBOX.exists():
        return []
    out, seen = [], set()
    try:
        lines = WECHAT_INBOX.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("channel") != "wechat-group":
            continue
        text = (r.get("content") or "").strip()
        if not text:
            continue
        # 例行汇报（寝室在寝情况等）不是通知。采集器已挡新消息，这里再挡一次，
        # 保证旧版本已经收进 inbox 的历史记录也不会重新上板。
        if is_routine_report(r.get("groupName", ""), text):
            continue
        key = str(r.get("groupName", "")) + ":" + str(r.get("messageId", "")) + ":" + text[:80]
        if key in seen:
            continue
        seen.add(key)
        ts = r.get("receivedAt", "")[5:16].replace("T", " ")
        raw_items = [it for it in (r.get("items") or []) if isinstance(it, dict)]
        if raw_items:
            items = raw_items
            title = (r.get("title") or "").strip()
            joined = " ".join(str(it.get("name") or it.get("text") or it.get("note") or "") for it in items)
        else:
            items = [{"kind": "text", "label": "群通知", "time": ts, "text": text}]
            title = re.split(r"[。！？\n]", text)[0].strip()[:36]
            joined = text
        out.append({
            "id": "g_wxg_" + hashlib.sha1(key.encode()).hexdigest()[:10],
            "cat": classify_wechat(joined), "title": title or "微信群通知",
            "summary": re.sub(r"\s+", " ", joined)[:110],
            "group": r.get("groupName", "微信群"),
            "source": "微信群 · " + r.get("groupName", "微信群"),
            "deadline": extract_deadline(joined), "actionable": True,
            "items": items,
        })
    return out


def wechat_group(msgs):
    if not msgs:
        return None
    items = [{"kind": "text", "label": "微信消息", "time": m["time"],
              "from": (m["from"] + (" · " + m["group"] if m["group"] else "")), "text": m["text"]}
             for m in msgs]
    deadlines = [d for d in (extract_deadline(m["text"]) for m in msgs) if d]
    deadline = min(deadlines) if deadlines else None
    raw = (msgs[-1].get("text") or "").replace("@所有人", "").strip()
    first = re.split(r"[。！？\n]", raw)[0].strip()
    if len(first) > 28:
        first = first[:28] + "…"
    title = "微信转发 · " + (first or "通知")
    return {
        "id": "g_wechat", "cat": "班级事务",
        "title": title,
        "summary": "微信群聊与私聊转发进来的通知，已自动进入简报。",
        "group": "微信", "source": "微信",
        "deadline": deadline, "items": items,
    }


def load_docs():
    """Docs detected by the qqdocs scanner (QQ NT DB, read-only)."""
    if not DOCS_JSON.exists():
        return []
    try:
        data = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
        return data.get("docs", [])
    except Exception:
        return []


def _form_item(doc, label="报名收集表", close=None, open_=None, note=""):
    return {
        "kind": "form", "label": label, "time": doc.get("time", ""),
        "name": doc.get("title", "腾讯文档"), "open": open_ or "",
        "close": close or "", "note": note,
        "realUrl": doc.get("url", ""), "realTitle": doc.get("title", ""),
        "realGroup": doc.get("groupName", ""), "realKind": doc.get("kindLabel", "文档"),
    }


def attach_docs(groups, docs):
    """Attach every matching Tencent Doc; never leave a matching form in Other Docs."""
    by_id = {g["id"]: g for g in groups}

    for gid, keyword in (("g_recruit", "11.5招聘会志愿者"), ("g_games_viewer", "运动会观众征集")):
        group = by_id.get(gid)
        doc = next((d for d in docs if keyword in (d.get("title", "") + d.get("desc", ""))), None)
        if not group or not doc:
            continue
        for item in group["items"]:
            if item["kind"] == "form":
                item.update(realUrl=doc["url"], realTitle=doc["title"],
                            realGroup=doc.get("groupName", ""), realKind=doc.get("kindLabel", "文档"))
                break

    group = by_id.get("g_games_vol")
    if group:
        vol_docs = [d for d in docs if "管院运动会志愿活动" in (d.get("title", "") + d.get("desc", ""))]
        order = {"❶": 1, "❷": 2, "❸": 3, "❹": 4, "❺": 5, "❻": 6}
        vol_docs.sort(key=lambda d: next((v for k, v in order.items() if k in d.get("title", "")), 99))
        existing = next((it for it in group["items"] if it["kind"] == "form"), None)
        insert_at = next((i for i, it in enumerate(group["items"]) if it.get("label") == "原始通知"), -1) + 1
        for d in vol_docs:
            if "❻" in d.get("title", ""):
                if existing:
                    existing.update(realUrl=d["url"], realTitle=d["title"],
                                   realGroup=d.get("groupName", ""), realKind=d.get("kindLabel", "文档"))
                continue
            group["items"].insert(insert_at, _form_item(
                d, close="10-31 14:00", open_="10-31 12:00", note="原始通知 · 5 个时段收集表"))
            insert_at += 1


def docs_group(docs):
    if not docs:
        return {
            "id": "g_autodocs", "cat": "班级事务", "title": "腾讯文档（自动识别）",
            "summary": "暂未从 QQ 本地消息库识别到腾讯文档。", "group": "自动识别",
            "source": "自动识别 · QQ 群文档", "deadline": None, "actionable": False,
            "items": [{"kind": "follow", "label": "说明", "time": "", "from": "qqdocs", "text": "扫描器未检测到 docs.qq.com 卡片。"}],
        }
    items = []
    for d in docs:
        items.append({
            "kind": "link", "label": "腾讯文档 · " + d.get("kindLabel", "文档"),
            "time": d.get("time", ""), "from": d.get("sender", ""),
            "name": d.get("title", "腾讯文档") + "（" + d.get("groupName", "") + "）",
            "url": d.get("url", ""),
            "note": "自动识别 · " + d.get("groupName", "") + " · " + d.get("time", ""),
        })
    return {
        "id": "g_autodocs", "cat": "班级事务", "title": "腾讯文档（自动识别 · " + str(len(docs)) + " 条）",
        "summary": "由 qqdocs 扫描器从 QQ 本地消息库自动识别的腾讯文档卡片，包含今天 14:02 的「运动会观众征集」；群里有新文档会自动出现在这里。",
        "group": "自动识别", "source": "自动识别 · QQ 群文档", "deadline": None, "actionable": False,
        "items": items,
    }


def build_homework(docs):
    """Homework items derived from the last 7 days of class messages."""
    hw = [
        {"id": "hw_ideology", "title": "思政课：小组展示文件准备", "course": "思政课",
         "group": "2026级信息管理与信息系统聊天群", "due": "2026-11-03T14:00:00+08:00",
         "note": "两个小组提前到班，文件用 U 盘导到电脑，另备份私发同学L。"},
        {"id": "hw_c", "title": "C语言课：准备作业纸", "course": "C语言",
         "group": "26级信管作业群", "due": "2026-11-03T23:59:00+08:00",
         "note": "张翠萍老师：明天上课请准备好作业纸。"},
        {"id": "hw_essay", "title": "食不易得：手抄报作品提交", "course": "活动",
         "group": "2026级信息管理与信息系统聊天群", "due": "2026-11-12T20:00:00+08:00",
         "note": "作品拍照提交至群作业，右下角写姓名、学号、学院。"},
        {"id": "hw_python", "title": "Python 作业：本周暂不交", "course": "Python",
         "group": "2026级信息管理与信息系统聊天群", "due": None, "fixedStatus": "暂不交",
         "note": "同学G问这周 Python 作业交不交，同学B回复：老师说暂时不交。"},
        {"id": "hw_elective", "title": "网络公选课：学习通开始学习", "course": "网络公选课",
         "group": "2026级信息管理与信息系统聊天群", "due": None,
         "note": "已报名超星课程的同学，课程已导入学习通，注意学习与考试时间。"},
    ]
    comp = next((d for d in docs if "计算机导论" in (d.get("title", "") + d.get("desc", ""))), None)
    hw.insert(3, {
        "id": "hw_computer", "title": comp["title"] if comp else "计算机导论：每周学习内容",
        "course": "计算机导论", "group": "26级信管作业群", "due": None,
        "note": "林立老师发的腾讯文档（自动识别），含本周学习内容。",
        "docUrl": comp["url"] if comp else "", "docTitle": comp["title"] if comp else "",
    })
    return hw


def other_docs_group(docs):
    items = []
    for d in docs:
        items.append({
            "kind": "link", "label": "腾讯文档 · " + d.get("kindLabel", "文档"),
            "time": d.get("time", ""), "from": d.get("sender", ""),
            "name": d.get("title", "腾讯文档") + "（" + d.get("groupName", "") + "）",
            "url": d.get("url", ""),
            "note": "自动识别 · " + d.get("groupName", "") + " · " + d.get("time", ""),
        })
    return {
        "id": "g_otherdocs", "cat": "班级事务", "title": "其他腾讯文档（自动识别 · " + str(len(docs)) + " 条）",
        "summary": "没有匹配到具体通知的群文档，单独列出备查；已匹配的腾讯文档都在对应通知组里。",
        "group": "自动识别", "source": "自动识别 · QQ 群文档", "deadline": None, "actionable": False, "items": items,
    }


# ---------------------------------------------------------------- 2026-11-18 发布时间统一（契约 §1）
# 用户需求：「将通知中不含时间的时间设定为发布时间，动作设为发布，并参与排序等等统一计算」
#   · publishedAt：所有组都写 = max(组内最新消息时间 items[].time / messages[].time, updatedAt)；
#   · publishAction：「发布」仅在「无任何时间锚点且非长期安排」的组上写（chip 动作用）。
_PUB_ITEM_TIME_RE = re.compile(r"^(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$")
_PUB_TIME_ANCHOR_KEYS = ("deadline", "eventAt", "signupStart", "signupEnd")


def _pub_dt_from_mmdd(value):
    """'MM-DD HH:MM' → datetime（当前年；晚于现在 60 天以上视为上一年，与网页 _relAnchor 同口径）。"""
    m = _PUB_ITEM_TIME_RE.match(str(value or "").strip())
    if not m:
        return None
    try:
        mo, da, hh, mi = (int(m.group(i)) for i in range(1, 5))
        now = datetime.now()
        dt = datetime(now.year, mo, da, hh, mi)
        if dt > now + timedelta(days=60):
            dt = datetime(now.year - 1, mo, da, hh, mi)
        return dt
    except ValueError:
        return None


def publish_at_of(g):
    """发布时间（契约 §1）：组内最新一条消息时间与 updatedAt 的较晚者；无任何解析结果 → 空串。"""
    best = None
    for it in (g.get("items") or []):
        if not isinstance(it, dict):
            continue
        dt = _pub_dt_from_mmdd(it.get("time"))
        if dt and (best is None or dt > best):
            best = dt
        for msg in (it.get("messages") or []):
            if not isinstance(msg, dict):
                continue
            dt = _pub_dt_from_mmdd(msg.get("time"))
            if dt and (best is None or dt > best):
                best = dt
    raw = str(g.get("updatedAt") or "").strip()
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(datetime.now().astimezone().tzinfo).replace(tzinfo=None)
            if best is None or dt > best:
                best = dt
        except Exception:  # noqa: BLE001
            pass
    if not best:
        return ""
    return best.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def has_time_anchor(g):
    """组内是否有真实时间锚点（与三端 hasTimeAnchor 同口径；发布时间不算）。"""
    if any(g.get(k) for k in _PUB_TIME_ANCHOR_KEYS):
        return True
    return bool(g.get("signupWindows"))


# ---------------------------------------------------------------- 2026-11-18 长期安排 × 一次性时间冲突
# 用户反馈：屏山慢跑补报名（11-17 17:00）所在活动被 AI 判为每日 recurrence，导致
#   · 卡片显示「本次 11-18 17:00」而不是 11-17 17:00 补报名（时间识别异常）；
#   · 被归入「长期通知」而不进待处理（分类异常）。
# 规则：固定日期范围内的活动/打卡（有报名/截止/活动时间）不是「长期安排」；一次性时间锚点优先，
# 移除 recurrence（活动时段仍保留在摘要/原文里），并恢复可处理状态。
def resolve_recurrence_conflicts(groups):
    for g in groups:
        rec = g.get("recurrence")
        if not isinstance(rec, dict) or not rec.get("freq"):
            continue
        finite = bool(g.get("signupStart") or g.get("signupEnd") or g.get("deadline")
                     or g.get("eventAt") or g.get("signupWindows"))
        if not finite:
            continue
        # 只有报名开始、没有截止/活动时间时，把报名开放当作一次性事件展示（补报名/报名开始）
        if not g.get("eventAt") and not g.get("deadline") and g.get("signupStart"):
            g["eventAt"] = g["signupStart"]
            if not g.get("eventAction"):
                corpus = " ".join(str(it.get("text") or it.get("name") or "")
                                  for it in (g.get("items") or []) if isinstance(it, dict))
                if re.search(r"补报名|重新报名|重新开放报名", corpus):
                    g["eventAction"] = "补报名"
                else:
                    g["eventAction"] = "报名"
        g.pop("recurrence", None)
        # 长期安排此前会被强制 actionable=False；有一次性报名/截止/活动时恢复为可处理
        if g.get("actionable") is False:
            g["actionable"] = True
        print("recurrence->oneoff:", g.get("id"), "|", str(g.get("title") or "")[:40],
              "|", g.get("eventAt") or g.get("deadline") or g.get("signupStart"))


def main():
    groups = build_groups()
    docs = load_docs()
    attach_docs(groups, docs)
    for wg in load_wechat_notices():
        groups.append(wg)
    for wg in load_wechat_group_notices():
        groups.append(wg)
    for qm in load_qq_merged():
        groups.append(qm)
    groups = realize_groups(groups)
    groups = expand_merged(groups)
    groups = resolve_deadlines(groups)
    groups = resolve_times(groups)
    qq_text_extra = []
    for g in load_qq_text():
        if _similar_notice(g, groups + qq_text_extra):
            continue
        qq_text_extra.append(g)
    groups = groups + qq_text_extra
    qq_image_extra = []
    for g in load_qq_image_notices():
        target = _find_merge_target(g, groups)
        if target:
            _merge_image_into(target, g)
            continue
        if _similar_notice(g, groups + qq_image_extra):
            continue
        qq_image_extra.append(g)
    groups = groups + qq_image_extra
    qq_file_extra = []
    for g in load_qq_file_notices():
        target = _find_file_merge_target(g, groups) or _find_merge_target(g, groups)
        if not target:
            # 同一文件名已经出现在某个通知里（例如手工组/合并记录），直接把上下文并进去
            names = {it.get("name") for it in (g.get("items") or []) if it.get("kind") == "file"}
            for e in groups:
                if any(it.get("kind") == "file" and it.get("name") in names for it in (e.get("items") or [])):
                    target = e
                    break
        if target:
            _merge_file_into(target, g)
            continue
        # 文件通知不因“标题相似”被丢弃：最多单独成卡（文件名本身就是信息）
        qq_file_extra.append(g)
    groups = groups + qq_file_extra
    ai_triage_extra = []
    for g in load_ai_triage_notices():
        if _similar_notice(g, groups + ai_triage_extra):
            continue
        ai_triage_extra.append(g)
    groups = groups + ai_triage_extra
    groups = [g for g in groups if not any(
        p in (str(g.get("group") or "") + " " + str(g.get("source") or ""))
        for p in NON_SCHOOL_GROUP_PATTERNS)]
    groups = apply_context_overrides(groups)
    # v2.0.0 需求 6：接龙卡兜底剔除（采集端已过滤，这里保证历史/AI 误生成的也不上板）
    groups = [g for g in groups if not is_lianlong_group(g)]
    # v2.0.0 需求 6：AI 识别的补充通知并入已有通知（追加 items + 修正字段 + updatedAt）
    groups = apply_supplements(groups)
    # 微信附件：items[].mediaKey → data URI；无字节（图片 V2 加密等）标「待获取」
    groups = apply_wechat_media_items(groups)
    # 压缩包附件：包内文件清单 + 解压识别摘要（失败保留原包 + 待识别）
    groups = apply_archive_items(groups)
    attach_sender_roles(groups)
    # v2.0.0 需求 8/9：AI 摘要/要点/长期安排统一透传（含自动识别通知）
    attach_ai(groups)
    # 2026-11-09 用户需求：取消固定分类，AI 根据近期通知动态增删分类（ai_categories.py 产物）
    apply_categories(groups)
    # 需求 8 最终兜底：aiPoints 单条 ≤12 字 / ≤6 条（AI 多路径生成，统一在 builder 收口）
    groups = sanitize_ai_points(groups)
    # 契约 §4：groups 组装完成后、人工补丁之前做时间语义归一（notice_time 优先 + builder 确定性兜底）
    groups = normalize_group_times(groups)
    # task-25：微信/QQ 跨源重复通知合并（同 URL / 同原文 / 标题+正文高相似 + 冲突守卫）。
    # 放在时间归一之后：eventAt/deadline 冲突守卫依赖归一后的时间字段（避免不同场次误合并）。
    groups, cross_merges = notice_merge.merge_cross_source_duplicates(groups)
    if cross_merges:
        print("cross-source merged:", len(cross_merges),
              "|", "; ".join("%s<-%s(%s)" % (m["base"], m["other"], m["reason"])
                             for m in cross_merges[:6]))
    # 合并卡补一次时间归一（两源字段互补后可能补出新的时间/动作字段）
    groups = normalize_group_times(groups)
    # 2026-11-09 用户第 6 条：AI 逐条质检——丢弃非通知/无内容、校正时间/过期状态（人工补丁之前）
    groups = apply_quality(groups)
    # 2026-11-14 契约 §1.4：AI 更新/更正通知合并（keep 覆盖最终有效状态，merge 组删除）——
    # 在质检之后（AI 处置结果优先于逐条质检）、人工补丁与 final 归一之前。
    groups = apply_threads(groups)
    # 人工补丁最后应用：药膳报名时间修正 + g_dorm 长期安排（人工补丁优先于 AI）
    groups = apply_manual_patches(groups)
    # 人工补丁后 final pass：只补缺（null/缺失才写），并用补丁追加的更正文本刷新报名窗口；
    # 人工补丁 set 过的字段不在覆盖范围内（人工优先级最高）。
    groups = normalize_group_times(groups, final=True)
    # 2026-11-18：长期安排 × 一次性报名/截止/活动时间冲突归一（固定日期活动不是长期安排）
    resolve_recurrence_conflicts(groups)
    # 统一数据口径：既无截止也无活动时间的通知不带 expireAt/timeLabel，
    # 避免下游把「自动归档时间」误当成「截止时间」显示。
    for g in groups:
        # 契约 §1.1 兜底：recurrence 必须有合法 freq + HH:MM；无 time 一律丢弃；until 校验。
        sanitize_recurrence(g)
        if not g.get("deadline") and not g.get("eventAt"):
            g.pop("expireAt", None)
            g.pop("timeLabel", None)
        # 需求 9：长期安排不计入待处理
        if isinstance(g.get("recurrence"), dict) and g["recurrence"].get("freq"):
            g["actionable"] = False
        # 2026-11-18 契约《《通知三端·发布时间统一》契约（内部归档）》§1：
        # 所有组写 publishedAt；无任何时间锚点且非长期安排的组写 publishAction="发布"（chip 动作用）。
        pub = publish_at_of(g)
        if pub:
            g["publishedAt"] = pub
        if not has_time_anchor(g) and not (
                isinstance(g.get("recurrence"), dict) and g["recurrence"].get("freq")):
            g["publishAction"] = "发布"
    homework = []
    forms = {}
    js = JS.replace("__DATA__", json.dumps(groups, ensure_ascii=False)).replace("__FORMS__", json.dumps(forms, ensure_ascii=False)) \
           .replace("__HOMEWORK__", json.dumps(homework, ensure_ascii=False)) \
           .replace("__SCHEDULE__", json.dumps([], ensure_ascii=False))
    html = HTML.replace("__CSS__", CSS).replace("__DOCCOUNT__", str(len(docs))) \
               .replace("__HWCOUNT__", "0").replace("__JS__", js)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    BOARD_DATA.parent.mkdir(parents=True, exist_ok=True)
    BOARD_DATA.write_text(json.dumps({
        "generatedAt": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "groups": groups,
        "homework": homework,
        "schedule": [],
        "docs": docs,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written:", OUT, "bytes:", OUT.stat().st_size, "groups:", len(groups), "docs:", len(docs))


if __name__ == "__main__":
    main()

