# -*- coding: utf-8 -*-
"""通知 × 课表联动（notice_course_link）单测。

运行：
  C:\\ClassTools\\briefdesk\\venv\\Scripts\\python.exe G:\\ClassTools\\web\\briefdesk\\tests\\test_course_link.py

覆盖：
  A. 节次时间与网页 tools/index.html 的 PERIODS 一致（12 节）；
  B. 课程别名 / 课前动作 / 日期解析（今天明天、MM-DD、11月23日、今日校园专名）；
  C. 真实案例「思政三组 11-23 提前到教室拷演讲内容」→ 2026-11-23 08:10 / 「思政课前」；
  D. 不改写明确更早的截止；长期安排 / 已过期 / 无课前动作 / 当天没课 → 不锚定；
  E. 幂等 + 旧 courseAnchor 失效清理。

只读产品数据（tt.json / board-data.json），不写任何文件。
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(r"G:\ClassTools\web\briefdesk")
WEB = BASE.parent
sys.path.insert(0, str(BASE))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import notice_course_link as ncl  # noqa: E402

PASS = 0
FAIL = 0
FAILED = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS " + name)
    else:
        FAIL += 1
        FAILED.append(name)
        print("FAIL " + name + ("  " + str(detail) if detail else ""))


def eq(name, actual, expected):
    check(name, actual == expected, "expected=%r actual=%r" % (expected, actual))


NOW = datetime(2026, 11, 22, 23, 30)
TT = ncl.load_timetable()
check("A1 课表快照可读（web/tools/tt.json）", TT is not None)
if not TT:
    print("FATAL: 课表不可读，后续用例跳过")
    raise SystemExit(1)
eq("A2 学期首周周一", str(TT["termStart"]), "2026-08-31")
check("A3 课程数 ≥ 20", len(TT["courses"]) >= 20, len(TT["courses"]))

print("---- A. 节次时间契约 ----")
idx = (WEB / "tools" / "index.html").read_text(encoding="utf-8")
m = re.search(r"var PERIODS=\[(.*?)\];", idx, re.S)
check("A4 index.html 找到 PERIODS", m is not None)
if m:
    pairs = re.findall(r'\["(\d{2}:\d{2})","(\d{2}:\d{2})"\]', m.group(1))
    eq("A5 12 节与网页 PERIODS 完全一致", tuple(pairs), ncl.PERIODS)

print("---- B. 课程 / 课前动作 / 日期解析 ----")
for text, short in [
    ("上次思政的那三组 明天提前到教室", "思政"),
    ("高数作业记得带", "高数"),
    ("C语言上机课", "C语言"),
    ("英语课前交", "英语"),
    ("Python 课展示", "计算机"),
    ("今天食堂加餐", None),
]:
    got = ncl.match_course(text)
    eq("B1 课程识别 %r" % text[:12], got[0] if got else None, short)

check("B2 课前动作：提前到教室", ncl.has_preclass_cue("明天提前到教室，用u盘拷演讲"))
check("B3 课前动作：思政课前", ncl.has_preclass_cue("思政课前把文件放桌面"))
check("B4 课前动作：上课之前", ncl.has_preclass_cue("上课之前交纸质版"))
check("B5 非课前动作：提前完成不误判", not ncl.has_preclass_cue("请大家提前完成作业"))
check("B6 非课前动作：提前交不误判", not ncl.has_preclass_cue("可以提前提交"))

ref = datetime(2026, 11, 22, 23, 4)
eq("B7 明天 → 11-23", [str(d) for d in ncl._text_dates("明天提前到教室", ref)], ["2026-11-23"])
eq("B8 今天 → 11-22", [str(d) for d in ncl._text_dates("今天下午开会", ref)], ["2026-11-22"])
eq("B9 MM-DD 直写", [str(d) for d in ncl._text_dates("11-25 前提交", ref)], ["2026-11-25"])
eq("B10 11月23日", [str(d) for d in ncl._text_dates("11月23日提前到教室", ref)], ["2026-11-23"])
eq("B11 今日校园不算日期", [str(d) for d in ncl._text_dates("课表以今日校园为准", ref)], [])
eq("B12 周X → 最近一次", [str(d) for d in ncl._text_dates("周日班会", ref)], ["2026-11-22"])

print("---- C. 真实案例：思政三组 11-23 提前到教室 ----")
case = {
    "id": "g_ait_f5f992561a",
    "cat": "教务",
    "title": "思政三组11-23提前到教室拷演讲内容",
    "summary": "11-23 思政课三组同学需提前到教室，用 U 盘将演讲内容拷到桌面并备份一份给老师。",
    "aiSummary": "11-23 思政课三组同学需提前到教室，用 U 盘将演讲内容拷到桌面并备份一份给老师。",
    "deadline": "2026-11-23T23:59:00+08:00",
    "deadlineAction": "截止",
    "items": [{"kind": "text", "time": "11-22 23:04",
               "text": "上次思政的那三组 明天提前到教室，用u盘将演讲内容考到桌面，并备份一份给我"}],
}
anchor = ncl.detect_course_anchor(case, TT, now=NOW)
check("C1 命中课表锚点", anchor is not None, anchor)
if anchor:
    eq("C2 课程名", anchor["name"], "思想道德与法治")
    eq("C3 日期", anchor["date"], "2026-11-23")
    eq("C4 第 1-3 节", (anchor["start"], anchor["end"]), (1, 3))
    eq("C5 上课时间 08:10", anchor["startAt"], "2026-11-23T08:10:00+08:00")
    eq("C6 动作文案", anchor["label"], "思政课前")
    eq("C7 教室", anchor["room"], "自强楼(教室01104)")

ncl.apply_course_anchors([case], TT, now=NOW)
eq("C8 截止改为上课时间", case.get("deadline"), "2026-11-23T08:10:00+08:00")
eq("C9 动作改成思政课前", case.get("deadlineAction"), "思政课前")
check("C10 courseAnchor 字段写入", isinstance(case.get("courseAnchor"), dict)
      and case["courseAnchor"].get("label") == "思政课前")

again = json.loads(json.dumps(case, ensure_ascii=False))
ncl.apply_course_anchors([again], TT, now=NOW)
eq("C11 幂等：重复执行结果不变", again.get("deadline"), case.get("deadline"))

print("---- D. 不覆盖的边界 ----")
early = json.loads(json.dumps(case, ensure_ascii=False))
early["deadline"] = "2026-11-23T07:30:00+08:00"
early["deadlineAction"] = "提交截止"
ncl.apply_course_anchors([early], TT, now=NOW)
eq("D1 明确更早的截止保持", early.get("deadline"), "2026-11-23T07:30:00+08:00")
eq("D2 明确更早的动作保持", early.get("deadlineAction"), "提交截止")
check("D3 仍补 courseAnchor 供展示", isinstance(early.get("courseAnchor"), dict))

recur = json.loads(json.dumps(case, ensure_ascii=False))
recur["deadline"] = "2026-11-23T23:59:00+08:00"
recur["recurrence"] = {"freq": "weekly", "weekday": 0, "time": "08:10", "label": "每周一"}
ncl.apply_course_anchors([recur], TT, now=NOW)
eq("D4 长期安排不锚定", recur.get("deadline"), "2026-11-23T23:59:00+08:00")
check("D5 长期安排无 courseAnchor", "courseAnchor" not in recur)

expired = json.loads(json.dumps(case, ensure_ascii=False))
expired["deadline"] = "2026-11-23T23:59:00+08:00"
expired["expired"] = True
ncl.apply_course_anchors([expired], TT, now=NOW)
eq("D6 AI 判过期不锚定", expired.get("deadline"), "2026-11-23T23:59:00+08:00")

nocue = json.loads(json.dumps(case, ensure_ascii=False))
nocue["deadline"] = "2026-11-23T23:59:00+08:00"
nocue["title"] = "思政三组名单公示"
nocue["summary"] = "思政三组名单见附件。"
nocue["aiSummary"] = "思政三组名单见附件。"
nocue["items"] = [{"kind": "text", "time": "11-22 23:04", "text": "思政三组名单公示，见附件"}]
ncl.apply_course_anchors([nocue], TT, now=NOW)
eq("D7 无课前动作不锚定", nocue.get("deadline"), "2026-11-23T23:59:00+08:00")

wrongday = json.loads(json.dumps(case, ensure_ascii=False))
wrongday["deadline"] = "2026-11-24T23:59:00+08:00"
wrongday["items"] = [{"kind": "text", "time": "11-23 20:00",
                      "text": "明天思政课提前到教室拷演讲内容"}]
ncl.apply_course_anchors([wrongday], TT, now=datetime(2026, 11, 23, 20, 30))
eq("D8 次日没有思政课 → 不锚定", wrongday.get("deadline"), "2026-11-24T23:59:00+08:00")

print("---- E. 失效清理 / 课表变动 ----")
stale = json.loads(json.dumps(case, ensure_ascii=False))
stale["courseAnchor"] = {"label": "思政课前", "date": "2026-11-01"}
stale["title"] = "思政三组名单公示"
stale["summary"] = "思政三组名单见附件。"
stale["aiSummary"] = "思政三组名单见附件。"
stale["items"] = [{"kind": "text", "time": "11-22 23:04", "text": "思政三组名单公示，见附件"}]
ncl.apply_course_anchors([stale], TT, now=NOW)
check("E1 不再符合条件时清掉旧 courseAnchor", "courseAnchor" not in stale)

moved = json.loads(json.dumps(case, ensure_ascii=False))
fake_moved = {"termStart": TT["termStart"], "courses": [
    {"name": "思想道德与法治", "day": 0, "start": 6, "end": 8, "weeks": "13-18", "parity": "all",
     "room": "自强楼(教室01104)"},
]}
ncl.apply_course_anchors([moved], fake_moved, now=NOW)
eq("E2 课表改到 6-8 节 → 跟着改到 14:30", moved.get("deadline"), "2026-11-23T14:30:00+08:00")
eq("E3 课表变动后动作仍为思政课前", moved.get("deadlineAction"), "思政课前")

gone = json.loads(json.dumps(case, ensure_ascii=False))
fake_gone = {"termStart": TT["termStart"], "courses": [
    {"name": "思想道德与法治", "day": 2, "start": 1, "end": 3, "weeks": "13-18", "parity": "all",
     "room": "自强楼(教室01104)"},
]}
ncl.apply_course_anchors([gone], fake_gone, now=NOW)
eq("E4 当天没课 → 还原原截止 23:59", gone.get("deadline"), "2026-11-23T23:59:00+08:00")
eq("E5 当天没课 → 还原原动作 截止", gone.get("deadlineAction"), "截止")
check("E6 当天没课 → 清掉 courseAnchor", "courseAnchor" not in gone)

expired_keep = json.loads(json.dumps(case, ensure_ascii=False))
expired_keep["expired"] = True
ncl.apply_course_anchors([expired_keep], TT, now=NOW)
eq("E7 AI 判过期后保留已有锚点（仍显示思政课前）", expired_keep.get("deadlineAction"), "思政课前")

print()
print("PASS %d  FAIL %d" % (PASS, FAIL))
if FAILED:
    print("FAILED:", ", ".join(FAILED))
sys.exit(0 if FAIL == 0 else 1)
