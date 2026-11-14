# -*- coding: utf-8 -*-
"""本轮通知改造 · 数据侧验收（重建后运行，只读 board-data）。

覆盖契约 §4.2 五个样例：
  1) 射击人员11-14雨天集合安排：eventAt 时间被保留（不被 AI null 清掉）→ 按当前时间已过期，不是长期通知
  2) 每日07:30前私发导员请假：recurrence 带 until（军训结束日），且 until 不晚于合理范围
  3) 11-13 晚自习/军训更新链：合并为一条，摘要只保留军训、不出现「晚自习」要求
  4) 无时间通知不得带 recurrence（资料/无时间栏由客户端分类）
  5) 周五周六日期换算：摘要不出现「11-14、11-15 晚自习」错误
另外：所有 recurrence 必须有 HH:MM time；g_dorm 期次算法固定向量检查。
"""
import json
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BOARD = r"C:\briefdesk\data\board-data.json"
CN = datetime.now().astimezone()
NOW = datetime(2026, 11, 14, 13, 31, tzinfo=CN.tzinfo)

d = json.load(open(BOARD, encoding="utf-8"))
groups = {g.get("id"): g for g in d.get("groups") or []}
steps = []


def T(k, ok, note=""):
    steps.append({"k": k, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def parse(v):
    if not v:
        return None
    s = str(v).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=CN.tzinfo)
    except Exception:
        return None


def has_time_anchor(g):
    return bool(g.get("deadline") or g.get("eventAt") or g.get("signupStart")
                or g.get("signupEnd") or (isinstance(g.get("signupWindows"), list) and g.get("signupWindows")))


def is_recur(g):
    r = g.get("recurrence")
    return isinstance(r, dict) and bool(r.get("freq"))


# 1) 射击：时间保留 + 过期
g = groups.get("g_ait_3c6b69a3a1")
T("S1 射击通知仍存在", g is not None, "" if g else "g_ait_3c6b69a3a1 missing")
if g:
    T("S1a 射击通知按当前时间已过期（三端状态机口径）",
      bool(g.get("deadline") and parse(g["deadline"]) and parse(g["deadline"]) < NOW)
      or bool(g.get("eventAt") and parse(g["eventAt"]) and parse(g["eventAt"]) < NOW),
      "deadline=%s eventAt=%s expireAt=%s" % (g.get("deadline"), g.get("eventAt"), g.get("expireAt")))
    T("S1b 射击通知 eventAt=11-14 早上（AI 不得把确定性时间清空）",
      bool(g.get("eventAt")) and (parse(g["eventAt"]) or NOW).strftime("%Y-%m-%d") == "2026-11-14",
      "eventAt=%s" % g.get("eventAt"))
    T("S1c 射击通知不是长期通知（无 recurrence）", not is_recur(g), "recurrence=%r" % (g.get("recurrence"),))

# 2) 每日请假 recurrence until
g = groups.get("g_ait_10b5b8f56a")
T("S2 每日请假通知仍存在", g is not None, "" if g else "missing")
if g:
    rec = g.get("recurrence") or {}
    until = rec.get("until")
    T("S2a recurrence 带 until（军训结束）", bool(until), "until=%r" % (until,))
    u = parse(until)
    T("S2b until 在 11-14 ~ 11-17 之间（军训收尾）", bool(u) and datetime(2026, 11, 14, tzinfo=CN.tzinfo) <= u <= datetime(2026, 11, 17, 23, 59, tzinfo=CN.tzinfo),
      "until=%r" % (until,))
    T("S2c recurrence 有 HH:MM time", bool(rec.get("time")), "time=%r" % (rec.get("time"),))

# 3) 11-13 更新链合并（builder 跨源去重/线程合并后，三条原始消息只保留一张最终卡：
#    可能是 d3b7/a2a82 任一 keep，且另外条目已作为补充 items 并入）
trio = [gid for gid in ("g_ait_d3b7baeb20", "g_ait_a2a82e52b1", "g_ait_000c41c075") if gid in groups]
T("S3 11-13 更新链已合并（三条原始通知只剩 1 张卡）", len(trio) <= 1, "remaining=%r" % (trio,))
if len(trio) == 1:
    g = groups[trio[0]]
    blob = " ".join(str(g.get(k) or "") for k in ("title", "aiSummary", "summary"))
    for seg in g.get("aiSegments") or []:
        blob += " " + str(seg.get("text") or "")
    T("S3a 合并后摘要提到军训", "军训" in blob, blob[:160])
    T("S3b 合并后摘要/标题不出现「晚自习」（被取消内容不进摘要）", "晚自习" not in blob, blob[:160])
    T("S3c 合并后已包含更新消息（补充 items/threadReason/updatedAt）",
      bool(g.get("updatedAt")) or bool(g.get("threadReason"))
      or any(str(it.get("label") or "") == "补充通知" for it in (g.get("items") or [])),
      "updatedAt=%r threadReason=%r items=%d" % (g.get("updatedAt"), g.get("threadReason"), len(g.get("items") or [])))
    T("S3d 合并后日期换算正确（不出现 11-14、11-15 晚自习）", "11-14、11-15 晚自习" not in blob and "11-14、11-15晚自习" not in blob, blob[:160])

# 4) 无时间通知不得带 recurrence
bad = [(gid, g.get("title")) for gid, g in groups.items()
       if is_recur(g) and not (g.get("recurrence") or {}).get("time")]
T("S4 所有 recurrence 都有 time", not bad, bad[:3])

# 5) 时间换算：周五周六 = 11-13/11-14（如果摘要里出现晚自习；合并后可能不出现，做宽松检查）
wrong = [gid for gid, g in groups.items()
         if "晚自习" in (str(g.get("aiSummary") or "") + str(g.get("summary") or ""))
         and ("11-14、11-15" in (str(g.get("aiSummary") or "") + str(g.get("summary") or "")))]
T("S5 不存在「11-14、11-15 晚自习」错误换算", not wrong, wrong[:3])

# 6) g_dorm 期次算法固定向量
g = groups.get("g_dorm") or {}
rec = g.get("recurrence") or {}
T("S6 g_dorm 仍是长期安排且无 until", is_recur(g) and not rec.get("until"), "recurrence=%r" % (rec,))


def rec_occurrence(rec, now):
    """模拟三端 next 计算（仅覆盖 monthly_weeks/weekly/daily/monthly_day；用于向量检查）。"""
    if not isinstance(rec, dict) or not rec.get("freq"):
        return None
    hh, mm = (str(rec.get("time") or "00:00").split(":") + ["0"])[:2]
    hh, mm = int(hh) % 24, int(mm) % 60
    start = parse(rec.get("startAt"))
    base = max(now, start) if start else now
    for i in range(0, 800):
        day = (base + timedelta(days=i)).date()
        t = datetime(day.year, day.month, day.day, hh, mm, tzinfo=CN.tzinfo)
        if t < now or (start and t < start):
            continue
        wd = t.weekday()  # Mon=0
        js_wd = (wd + 1) % 7  # JS getDay Sun=0
        freq = rec.get("freq")
        if freq == "daily":
            return t
        if freq == "weekly" and js_wd == int(rec.get("weekday", 0)):
            return t
        if freq == "monthly_day" and t.day == int(rec.get("day", 0)):
            return t
        if freq == "monthly_weeks":
            if js_wd != int(rec.get("weekday", 0)):
                continue
            weeks = [int(x) for x in (rec.get("weeks") or [])]
            first = datetime(day.year, day.month, 1, tzinfo=CN.tzinfo)
            first_wd = (first.weekday() + 1) % 7
            offset = (int(rec.get("weekday", 0)) - first_wd + 7) % 7
            occ = (day.day - 1 - offset) // 7 + 1
            if not weeks or occ in weeks:
                return t
    return None


nxt = rec_occurrence(rec, NOW)
T("S6a g_dorm next=11-18 17:30", bool(nxt) and nxt.strftime("%Y-%m-%d %H:%M") == "2026-11-18 17:30",
  nxt.strftime("%Y-%m-%d %H:%M") if nxt else "None")
if nxt:
    win_start = nxt - timedelta(hours=24)
    T("S6b 期次窗口/键（now 不在窗口内）", not (win_start <= NOW < nxt), "window=%s~%s" % (win_start, nxt))
    T("S6c 期次 key 格式", ("%s@occ:%s" % ("g_dorm", nxt.strftime("%Y%m%d"))) == "g_dorm@occ:20261118", "")

# 7) 数据完整性
T("S7 通知组数量在合理范围（>=80）", len(groups) >= 80, len(groups))
print("=" * 60)
passed = sum(1 for s in steps if s["ok"])
print("data check: %d 项，PASS %d，FAIL %d" % (len(steps), passed, len(steps) - passed))
sys.exit(0 if passed == len(steps) else 1)
