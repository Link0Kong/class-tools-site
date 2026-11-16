# -*- coding: utf-8 -*-
"""v2.0.0 数据校验（临时脚本，收尾删除）。"""
import json
import re
import sys
from pathlib import Path

DATA = Path(r"C:\briefdesk\data")
BOARD = DATA / "board-data.json"
DEMO = Path(r"C:\Users\Ko_Li\.openclaw\workspace\web\tools\notice-board-live-demo.html")


def main():
    b = json.loads(BOARD.read_text(encoding="utf-8"))
    groups = b.get("groups", [])
    problems = []

    # 1) 接龙卡 0 张
    chains = [g for g in groups if "接龙" in json.dumps(g, ensure_ascii=False)]
    print("groups:", len(groups), "| 接龙相关组:", len(chains))
    if chains:
        problems.append("存在接龙组: %s" % [g.get("id") for g in chains])

    # 2) 药膳答题活动（g_qqm_7704134971497063025_c0）
    med = next((g for g in groups if g.get("id") == "g_qqm_7704134971497063025_c0"), None)
    if not med:
        problems.append("找不到药膳答题活动组 g_qqm_7704134971497063025_c0")
    else:
        print("药膳组:", json.dumps({k: med.get(k) for k in
              ("id", "title", "deadline", "eventAt", "expireAt", "timeLabel", "updatedAt", "actionable")},
              ensure_ascii=False))
        print("  补充条目:", [(it.get("label"), it.get("time")) for it in med.get("items") or []])
        print("  aiSummary:", med.get("aiSummary"))
        print("  aiPoints:", med.get("aiPoints"))
        blob = json.dumps({k: med.get(k) for k in ("aiSummary", "aiPoints", "aiSegments")},
                          ensure_ascii=False)
        if "11-05 12:00" in blob or "11月5日12:00" in blob or "11月5日 12:00" in blob:
            problems.append("药膳摘要/要点仍含 11-05 12:00")
        if med.get("deadline") != "2026-11-07T18:00:00+08:00":
            problems.append("药膳 deadline 不对: %s" % med.get("deadline"))
        if med.get("eventAt") != "2026-11-07T12:00:00+08:00":
            problems.append("药膳 eventAt 不对: %s" % med.get("eventAt"))
        if med.get("timeLabel") != "报名 11-07 12:00":
            problems.append("药膳 timeLabel 不对: %s" % med.get("timeLabel"))
        if not any(it.get("label") == "补充通知" for it in med.get("items") or []):
            problems.append("药膳缺「补充通知」条目")

    # 3) g_dorm 长期安排
    dorm = next((g for g in groups if g.get("id") == "g_dorm"), None)
    if not dorm:
        problems.append("找不到 g_dorm")
    else:
        rec = dorm.get("recurrence") or {}
        print("g_dorm recurrence:", json.dumps(rec, ensure_ascii=False), "| actionable:", dorm.get("actionable"))
        if rec.get("freq") != "monthly_weeks" or rec.get("weekday") != 3 or rec.get("weeks") != [1, 2, 3]:
            problems.append("g_dorm recurrence 结构不对: %s" % rec)
        if rec.get("time") != "17:30" or not str(rec.get("startAt") or "").startswith("2026-11-04T17:30"):
            problems.append("g_dorm recurrence time/startAt 不对")
        if dorm.get("actionable") is not False:
            problems.append("g_dorm actionable 应为 false")

    # 4) QQ 文件内嵌状态
    files = []
    for g in groups:
        for it in g.get("items") or []:
            if isinstance(it, dict) and it.get("kind") == "file":
                files.append((g.get("id"), it.get("name"), "url" if it.get("url") else "MISSING"))
    print("\nfile items:")
    for f in files:
        print("  ", f)
    for name in ("信息管理与信息系统专业本科人才培养方案（2026级）.docx",
                 "军训动员大会场地划分.xls",
                 "级信息管理与信息系统-花名册学生名单.xls"):
        hit = next((f for f in files if f[1] == name), None)
        if not hit or hit[2] != "url":
            problems.append("文件未内嵌 url: %s" % name)
    # 其余无 url 的文件应保留（不是错误，仅打印）

    # 5) aiPoints 数量/长度
    bad = []
    for g in groups:
        pts = g.get("aiPoints")
        if not pts:
            continue
        if len(pts) > 6:
            bad.append((g.get("id"), "count=%d" % len(pts)))
        for p in pts:
            if len(str(p)) > 12:
                bad.append((g.get("id"), "len=%d:%s" % (len(str(p)), p)))
    print("\naiPoints 超标:", bad[:10], "共", len(bad))
    if bad:
        problems.append("aiPoints 超 6 条或超 12 字: %d 条" % len(bad))

    # 6) 补充通知条目 label
    print("\n含「补充通知」条目的组:", [g.get("id") for g in groups
                                  if any(it.get("label") == "补充通知" for it in g.get("items") or [])])

    # 7) 大小
    print("\nboard-data:", round(BOARD.stat().st_size / 1048576, 2), "MB |",
          "demo html:", round(DEMO.stat().st_size / 1048576, 2), "MB")
    # 8) 文件清单（供人工核对）
    print("\n分组清单:")
    for g in groups:
        print(" ", g.get("id"), "|", g.get("cat"), "|", (g.get("title") or "")[:30],
              "| dl=", g.get("deadline"), "| updatedAt=", g.get("updatedAt", ""))
    print("\n== PROBLEMS ==" if problems else "\n== ALL CHECKS PASS ==")
    for p in problems:
        print(" -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
