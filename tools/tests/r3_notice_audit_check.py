# -*- coding: utf-8 -*-
"""R3 第三轮验收（契约 §0.5 R1–R9 + 旧 A1–A9 语义回归 + 5 项回归）。

做法：
  1) 以 audit_baseline.py（注入审计探针）对当前 demo 采集全量事实 → accept/accept_audit.json；
  2) Python 侧按 R1–R9 断言（数据字段/渲染正文/原始消息弹层/版式/chip），并跑 5 项产品回归；
  3) 输出逐卡 44 组表格 + PASS/FAIL 清单 + 失败最小复现/定位建议 + 截图证据。
env：
  R3_DEMO    被测 demo（默认 web/tools/notice-board-live-demo.html）
  R3_OUT     证据目录（默认 C:\\briefdesk\\data\\_qa_nottime\\round3\\accept）
  R3_SKIP_AUDIT=1 复用已有 accept/accept_audit.json（快速重跑断言）
退出码 0 = R1–R9 全绿。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
DEMO = os.environ.get("R3_DEMO") or os.path.join(TOOLS, "notice-board-live-demo.html")
OUT = os.environ.get("R3_OUT") or r"C:\briefdesk\data\_qa_nottime\round3\accept"
BOARD = os.environ.get("R3_BOARD") or r"C:\briefdesk\data\board-data.json"
BRIEFS = os.environ.get("R3_BRIEFS") or r"C:\briefdesk\data\ai-briefs.json"
BASE_BOARD = os.environ.get("R3_BASE_BOARD") or \
    r"C:\briefdesk\data\_backup_nottime_20261105\pre_final_run\board-data.json"
PY = os.environ.get("R3_PY") or r"C:\briefdesk\venv\Scripts\python.exe"
AUDIT_PY = os.path.join(HERE, "r3_notice_audit_probe.py")

# 相对 round-2 基线的 signup 字段变化白名单（仅第2轮已确认的热修；其它任何 signup 变化=FAIL）
SIGNUP_CHANGE_WHITELIST = {
    "g_qqm_7704134971497063025_c1":
        "第2轮热修：signupEnd 11-14T23:59 → 11-05T18:00（契约 C1 修正，属预期）",
}

STEPS = []

ALLOWED_ACTIONS = {
    "报名截止", "提交截止", "报送截止", "投稿截止", "缴费截止", "选课截止", "签到截止", "截止",
    "开始", "点名", "签到", "上课", "考试", "比赛", "集合", "开会",
}
LONG_ACTIONS = {"活动开始", "比赛开始", "集合点名", "签到签退", "签到开始", "考试开始",
                "报名已截止", "报送姓名截止", "提交截止公示"}
A7_TIME_RE = re.compile(r"^(?:[1-9]\d* (?:分钟后|小时后|天后)|\d{2}-\d{2} \d{2}:\d{2}) (.+)$")


def S(k, ok, note=""):
    STEPS.append({"k": k, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def dt(v):
    from datetime import datetime, timedelta, timezone
    CN = timezone(timedelta(hours=8))
    if v in (None, ""):
        return None
    s = str(v).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try:
            d = datetime.strptime(s, "%Y-%m-%dT%H:%M")
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=CN)
    return d


def run_audit():
    os.makedirs(OUT, exist_ok=True)
    env = dict(os.environ, AUDIT_DEMO=DEMO, AUDIT_OUT=OUT, PYTHONIOENCODING="utf-8")
    print("[r3_accept] 采集当前 demo 事实（headless Edge 注入审计）...")
    r = subprocess.run([PY, AUDIT_PY], cwd=HERE, capture_output=True, timeout=900, env=env)
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    open(os.path.join(OUT, "audit_run.log"), "w", encoding="utf-8").write(out)
    print("\n".join(out.strip().splitlines()[-6:]))
    p = os.path.join(OUT, "baseline_audit.json")
    if not os.path.exists(p):
        print("[FATAL] 未生成", p)
        sys.exit(2)
    return json.load(open(p, encoding="utf-8"))


def scope_of(h):
    f = h.get("field") or h.get("region") or ""
    if f.startswith(("title", "aiSummary", "aiPoints", "aiSegments")):
        return "data"
    if f.startswith("rendered_"):
        return "rendered"
    if f == "modal":
        return "modal"
    return "raw"


def chip_action(chip):
    s = norm(chip)
    m = A7_TIME_RE.match(s)
    if m:
        return m.group(1), True
    return "", False


def build_index(a):
    recs = {str(g.get("id")): g for g in a.get("groups") or []}
    hits = {"data": {}, "rendered": {}, "modal": {}, "raw": {}}
    for h in a.get("hits") or []:
        gid = str(h.get("gid"))
        hits[scope_of(h)].setdefault(gid, []).append(h)
    return recs, hits


def check_r1(recs, hits):
    gid = "g_wxg_c66a85ae46"
    g = recs.get(gid)
    if not g:
        S("R1 g_wxg_c66a85ae46 存在", False, "缺卡")
        return
    ev = dt(g.get("eventAt"))
    S("R1.1 「下午招聘会请准时到场」eventAt=11-05 14:00 左右",
      ev is not None and ev.strftime("%Y-%m-%d %H:%M")[:13] == "2026-11-05 14",
      "eventAt=%s" % g.get("eventAt"))
    chip = norm(g.get("chip"))
    act, okfmt = chip_action(chip)
    S("R1.2 chip 含日期且动作简短", okfmt and "11-05" in chip and act in ALLOWED_ACTIONS,
      "chip=%s action=%s" % (chip, act))
    dh = hits["data"].get(gid) or []
    S("R1.3 标题/摘要/要点/segments 无裸时段词", len(dh) == 0,
      json.dumps([{"field": h.get("field"), "word": h.get("word")} for h in dh[:6]], ensure_ascii=False))
    blob = norm(g.get("title")) + " " + norm(g.get("aiSummary")) + " " + " ".join(g.get("aiPoints") or []) \
        + " " + " ".join(g.get("aiSegments") or [])
    S("R1.4 标题/摘要/要点/segments 含 11-05", "11-05" in blob or "11月5日" in blob,
      blob[:160])


def check_r2(recs, hits):
    for gid, name in [("g_ait_7a3370c5a7", "下午招聘会准时到场"), ("g_ait_7ebae6c1da", "下午室内篮球场招聘会")]:
        g = recs.get(gid)
        if not g:
            S("R2 %s 存在" % gid, False, "缺卡")
            continue
        chip = norm(g.get("chip"))
        act, okfmt = chip_action(chip)
        S("R2.1 %s chip 有日期+短动作" % name, okfmt and "-" in chip and act in ALLOWED_ACTIONS,
          "chip=%s" % chip)
        dh = hits["data"].get(gid) or []
        S("R2.2 %s 标题/摘要/要点无裸「下午」" % name, len(dh) == 0,
          json.dumps([{"field": h.get("field"), "word": h.get("word")} for h in dh[:6]], ensure_ascii=False))
        blob = norm(g.get("title")) + " " + norm(g.get("aiSummary")) + " " + " ".join(g.get("aiPoints") or [])
        S("R2.3 %s 标题/摘要/要点含 11-05" % name, "11-05" in blob or "11月5日" in blob, blob[:140])


def check_r3(recs, hits):
    gid = "g_qqm_7704134971497063025_c0"
    g = recs.get(gid)
    if not g:
        S("R3 药膳 c0 存在", False, "缺卡")
        return
    S("R3.1 药膳 c0 卡内无内联原始消息", (g.get("inline") or 0) == 0,
      "inline=%s labels=%s" % (g.get("inline"), g.get("inlineLabels")))
    S("R3.2 药膳 c0 卡内无「补充通知」内联行", (g.get("supInline") or 0) == 0, "supInline=%s" % g.get("supInline"))
    S("R3.3 药膳 c0 卡内无 /花朵脸 长原文", "/花朵脸" not in norm(g.get("cardText")),
      norm(g.get("cardText"))[:160])
    S("R3.4 药膳 c0「原始消息」按钮存在且含 3 条", bool(g.get("hasOriginalBtn")) and g.get("origItemCount") == 3,
      "hasBtn=%s origItems=%s" % (g.get("hasOriginalBtn"), g.get("origItemCount")))
    S("R3.5 药膳 c0 chip 为报名类动作", "报名" in norm(g.get("chip")), "chip=%s" % g.get("chip"))


def check_r4(recs, hits):
    gid = "g_ait_5396a55f24"
    g = recs.get(gid)
    if not g:
        S("R4 申报合并卡存在", False, "缺卡")
        return
    S("R4.1 申报合并卡内无内联原文", (g.get("inline") or 0) == 0,
      "inline=%s labels=%s" % (g.get("inline"), g.get("inlineLabels")))
    S("R4.2 申报合并卡「原始消息」按钮含 3 条", g.get("origItemCount") == 3,
      "origItems=%s" % g.get("origItemCount"))
    act, _ = chip_action(norm(g.get("chip")))
    S("R4.3 chip 动作=报送截止（≤6 字、无「已」）", act == "报送截止", "chip=%s action=%s" % (g.get("chip"), act))
    dh = hits["data"].get(gid) or []
    S("R4.4 标题/摘要/要点/segments 无裸时间词", len(dh) == 0,
      json.dumps([{"field": h.get("field"), "word": h.get("word")} for h in dh[:6]], ensure_ascii=False))


def check_r5(recs, hits):
    cases = [("g_qqimg_6d052014c3", "11-05", 5), ("g_qqimg_def2524e9f", "11-04", 4)]
    for gid, date_s, daynum in cases:
        g = recs.get(gid)
        if not g:
            S("R5 %s 存在" % gid, False, "缺卡")
            continue
        blob = norm(g.get("title")) + " " + norm(g.get("aiSummary")) + " " + " ".join(g.get("aiPoints") or []) \
            + " " + " ".join(g.get("aiSegments") or [])
        S("R5.1 %s 标题/摘要/要点/segments 的 %d号→%s" % (gid, daynum, date_s),
          date_s in blob and ("%d号" % daynum) not in blob, blob[:180])
        dh = hits["data"].get(gid) or []
        S("R5.2 %s 数据字段无裸日号/时段" % gid, len(dh) == 0,
          json.dumps([{"field": h.get("field"), "word": h.get("word")} for h in dh[:6]], ensure_ascii=False))
        ev = dt(g.get("eventAt"))
        S("R5.3 %s eventAt 不为 00:00（取文本首个钟点）" % gid,
          ev is not None and ev.hour != 0 and ev.strftime("%Y-%m-%d") == "2026-" + date_s,
          "eventAt=%s" % g.get("eventAt"))


def check_r6(recs, hits):
    gid = "g_ideology"
    g = recs.get(gid)
    if not g:
        S("R6 g_ideology 存在", False, "缺卡")
        return
    blob = " ".join(g.get("aiPoints") or []) + " " + " ".join(g.get("aiSegments") or [])
    S("R6.1 「今日校园」专名保留", "今日校园" in blob, blob[:180])
    S("R6.2 不再出现「10-29校园」类误替换", not re.search(r"\d{2}-\d{2}\s*校园", blob), blob[:180])
    S("R6.3 不再出现「11-03（10-30）」矛盾括号",
      not re.search(r"\d{2}-\d{2}\s*[（(]\s*\d{2}-\d{2}\s*[）)]", blob), blob[:180])
    S("R6.3b aiPoints/segments 不再残留 10-29/10-30 旧日期（应 11-03）",
      not re.search(r"10-(29|30)(?!\d)", blob.replace("今日校园", "")),
      blob[:200])
    dh = hits["data"].get(gid) or []
    S("R6.4 数据字段无裸星期/时段", len(dh) == 0,
      json.dumps([{"field": h.get("field"), "word": h.get("word")} for h in dh[:8]], ensure_ascii=False))


def check_r7(recs, hits):
    gid = "g_dorm"
    g = recs.get(gid)
    if not g:
        S("R7 g_dorm 存在", False, "缺卡")
        return
    S("R7.1 chip=长期安排 · 每月前三周 周三 17:30",
      norm(g.get("chip")) == "长期安排 · 每月前三周 周三 17:30", "chip=%s" % g.get("chip"))
    summary = norm(g.get("aiSummary"))
    # 契约 R7 示例写「自 11-02 起」，但 Lead 2026-11-06 07:2x 确认：以数据 recurrence.startAt=2026-11-04 为准 → 自 11-04 起
    m = re.search(r"自\s*(11-0[24])\s*起", summary)
    S("R7.2 摘要含「自 11-04 起」+ 每月前三周 + 周三 17:30",
      bool(m) and "每月前三周" in summary and "周三" in summary and "17:30" in summary,
      summary[:200])
    steps_i = S  # noqa: F841
    STEPS.append({"k": "R7.3 备注：dorm eventAt / 契约 R7 示例",
                  "ok": True,
                  "note": "eventAt=%s（recurrence 卡 chip 走长期安排分支不参与）；契约 R7 示例写 11-02，按 Lead 口径以 recurrence.startAt=11-04 为准" % g.get("eventAt")})
    dh = hits["data"].get(gid) or []
    S("R7.4 数据字段无裸相对词", len(dh) == 0,
      json.dumps([{"field": h.get("field"), "word": h.get("word")} for h in dh[:6]], ensure_ascii=False))
    blob7 = " ".join(g.get("aiPoints") or []) + " " + " ".join(g.get("aiSegments") or [])
    S("R7.5 aiPoints/segments 不残留 11-03（消息日期；起始日应 11-04）",
      "11-03" not in blob7, norm(blob7)[:180])


def check_r8(recs, hits, a):
    bad_chip, bad_data, bad_rendered, bad_modal, bad_title = [], [], [], [], []
    for gid, g in recs.items():
        chip = norm(g.get("chip"))
        if chip and not (chip.startswith("长期安排") or chip in ("无时间", "已处理", "已截止 · 有新名单")):
            act, okfmt = chip_action(chip)
            if not okfmt:
                bad_chip.append({"gid": gid, "chip": chip, "why": "格式"})
            else:
                if len(act) > 6:
                    bad_chip.append({"gid": gid, "chip": chip, "why": "动作>6字(%d)" % len(act)})
                if "已" in act:
                    bad_chip.append({"gid": gid, "chip": chip, "why": "含已"})
                if act in LONG_ACTIONS:
                    bad_chip.append({"gid": gid, "chip": chip, "why": "未缩写:" + act})
                if act not in ALLOWED_ACTIONS and len(act) > 6:
                    bad_chip.append({"gid": gid, "chip": chip, "why": "非标准:" + act})
        if (g.get("titleLen") or 0) > 20:
            bad_title.append({"gid": gid, "len": g.get("titleLen"), "title": g.get("title")})
        for scope, bucket in (("data", bad_data), ("rendered", bad_rendered), ("modal", bad_modal)):
            for h in hits[scope].get(gid) or []:
                bucket.append({"gid": gid, "field": h.get("field") or h.get("region"),
                               "word": h.get("word"), "snippet": (h.get("snippet") or "")[:80]})
    S("R8.1 全部 %d 组 chip 动作 ≤6 字 / 无「已」/ 已缩写" % len(recs), len(bad_chip) == 0,
      json.dumps(bad_chip[:8], ensure_ascii=False))
    S("R8.2 标题/摘要/要点/segments 裸时间词=0", len(bad_data) == 0,
      "命中=%d %s" % (len(bad_data), json.dumps(bad_data[:8], ensure_ascii=False)))
    S("R8.3 渲染正文裸时间词=0", len(bad_rendered) == 0,
      "命中=%d %s" % (len(bad_rendered), json.dumps(bad_rendered[:8], ensure_ascii=False)))
    S("R8.4 原始消息弹层裸时间词=0", len(bad_modal) == 0,
      "命中=%d %s" % (len(bad_modal), json.dumps(bad_modal[:8], ensure_ascii=False)))
    S("R8.5 标题 ≤20 字", len(bad_title) == 0, json.dumps(bad_title[:6], ensure_ascii=False))
    S("R8.6 无「报名已截止」", all("报名已截止" not in norm(g.get("chip")) for g in recs.values()), "")
    S("R8.7 0 JS 报错（审计页面）", len(a.get("errs") or []) == 0, json.dumps((a.get("errs") or [])[:5], ensure_ascii=False))


def check_r9(recs, a):
    # 合并卡
    sb = [g for gid, g in recs.items() if "申报材料" in norm(g.get("title")) + norm(g.get("aiSummary"))
          or any("申报材料" in t for t in (g.get("itemTexts") or []))]
    S("R9.1 申报材料仅 1 卡", len(sb) == 1, "count=%d" % len(sb))
    if sb:
        g = sb[0]
        kinds = [k for k in (g.get("itemKinds") or []) if k in ("text", "follow")]
        S("R9.2 申报合并卡含 3 条 text/follow 原文", len(kinds) >= 3, "text/follow=%d" % len(kinds))
        S("R9.3 申报 deadline=11-06 12:00 附近", dt(g.get("deadline")) is not None
          and dt(g.get("deadline")).strftime("%Y-%m-%d %H:%M") == "2026-11-06 12:00",
          str(g.get("deadline")))
    med = recs.get("g_qqm_7704134971497063025_c0")
    S("R9.4 药膳 c0 报名优先（chip 含报名）", bool(med) and "报名" in norm(med.get("chip")),
      med.get("chip") if med else "")
    fg = recs.get("g_qqfile_1a81286a3a")
    S("R9.5 花名册 sender=兰佳杰/学习委员", bool(fg) and norm(fg.get("senderName")) == "兰佳杰"
      and ("学习委员" in norm(fg.get("senderRole")) or "班委" in norm(fg.get("senderBadge"))),
      fg and "%s/%s/%s" % (fg.get("senderName"), fg.get("senderRole"), fg.get("senderBadge")))
    xx = [g for gid, g in recs.items() if "献血" in norm(g.get("title")) + norm(g.get("aiSummary"))
          or any("献血" in t for t in (g.get("itemTexts") or []))]
    S("R9.6 献血通知仅 1 卡（本人转发并入，无独立新卡）", len(xx) == 1, "count=%d" % len(xx))
    if xx:
        S("R9.7 献血卡含本人 10:18 补充通知/链接",
          any("10:18" in t or "11月14日" in t for t in (xx[0].get("itemTexts") or [])),
          json.dumps((xx[0].get("itemTexts") or [])[:5], ensure_ascii=False))


REGRESSIONS = [
    ("v2_notice_data_check", ["tests\\v2_notice_data_check.py"]),
    ("v2_ui_check", ["tests\\v2_ui_check.py"]),
    ("v2_admin_check", ["tests\\v2_admin_check.py"]),
    ("overflow_check_430", ["tests\\overflow_check.py", "430"]),
    ("export_check", ["tests\\export_check.py"]),
]


def run_regressions():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    reg_dir = os.path.join(OUT, "regression")
    os.makedirs(reg_dir, exist_ok=True)
    details = []
    for name, args in REGRESSIONS:
        logp = os.path.join(reg_dir, name + ".log")
        t0 = time.time()
        try:
            r = subprocess.run([PY] + args, cwd=TOOLS, capture_output=True, timeout=900, env=env)
            out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
            code = r.returncode
        except subprocess.TimeoutExpired:
            out, code = "TIMEOUT", -9
        open(logp, "w", encoding="utf-8").write(out)
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-2:]
        details.append({"test": name, "exit": code, "seconds": round(time.time() - t0, 1), "tail": tail})
        S("R9.%d 回归 %s" % (9 + len(details), name), code == 0,
          "exit=%s | %s" % (code, " | ".join(tail)))
    S("R9.20 回归 5 项全部通过", all(d["exit"] == 0 for d in details),
      "PASS=%d/5" % sum(1 for d in details if d["exit"] == 0))
    return details


def run_old_a_check():
    """旧 v2_notice_time_check（A1–A9）兼容性：仅记录其 FAIL（A2/A7 旧 chip 文案被 §0.2 取代，属预期）。
    注：旧脚本固定端口 8995 + 自带 Edge 探针，偶发与并发 Edge/端口冲突 → 失败时重试 1 次并落盘日志。"""
    p = os.path.join(TOOLS, "tests", "v2_notice_time_check.py")
    if not os.path.exists(p):
        return None
    env = dict(os.environ, PYTHONIOENCODING="utf-8", NTP_A9="0")
    last = None
    for attempt in range(2):
        try:
            r = subprocess.run([PY, p], cwd=TOOLS, capture_output=True, timeout=600, env=env)
            out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
            open(os.path.join(OUT, "oldA_v2_notice_time_check.log"), "w", encoding="utf-8").write(out)
            fails = [ln for ln in out.splitlines() if ln.startswith("[FAIL]")]
            last = {"exit": r.returncode, "fails": fails,
                    "note": "A2.2/A7.4 等旧 chip 文案断言与 §0.2「动作精简」冲突，属预期；其余 FAIL 需关注"}
            if r.returncode in (0, 1):
                return last
        except Exception as e:  # noqa: BLE001
            last = {"exit": -1, "fails": ["ERR:" + type(e).__name__]}
        time.sleep(2)
    return last


# ---------------------------------------------------------------- 数据层 ai-briefs 断言（Lead 要求：mp 同享）
DATE_NEAR_RE = re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日|\d{2}-\d{2}|\d{1,2}\.\d{1,2}")
REL_DAY_RE = re.compile(r"(大后天|后天|明早|明晚|明天|明日|今晚|今天|今日)")
PERIOD_RE = re.compile(r"(上午|中午|下午|晚上|凌晨|今早)")
DAYNUM_RE = re.compile(r"(\d{1,2})(号|日)")
PROPER_CORRUPT_RE = re.compile(r"(?:\d{2}-\d{2}|\d{1,2}月\d{1,2}日)\s*校园")


def _clause_before(s, off):
    """取 off 之前同一句（以。；;！？!? 换行分隔）的文本。"""
    start = 0
    for m in re.finditer(r"[。；;！？!?\n]", s[:off]):
        start = m.end()
    return s[start:off]


def _has_date_clock_before(s, off):
    """同句已有 MM-DD/月日 且有时钟 HH:MM（Lead 要求：时段词紧随其后时保留白名单，避免误报）。"""
    c = _clause_before(s, off)
    return bool(re.search(r"\d{2}-\d{2}|\d{1,2}\s*月\s*\d{1,2}\s*日", c)) and bool(re.search(r"\d{1,2}:\d{2}", c))


def scan_brief_text(s):
    """数据层文案裸时间词扫描（契约 §0.1），返回 [{cat,word,snippet}]。"""
    s = str(s or "")
    out = []

    def add(cat, word, off):
        out.append({"cat": cat, "word": word,
                    "snippet": s[max(0, off - 16):min(len(s), off + len(word) + 20)]})

    for m in REL_DAY_RE.finditer(s):
        if m.group(1) == "今日" and s[m.end():m.end() + 2] == "校园":
            continue
        add("relative", m.group(1), m.start())
    for m in re.finditer(r"(?:下|本|这)?(?:周|星期|礼拜)[一二三四五六日天]", s):
        off = m.start()
        before = s[max(0, off - 14):off]
        if re.search(r"每[^，。；、\s]{0,6}$", before):
            continue
        if DATE_NEAR_RE.search(before) and re.search(r"[（(]\s*$", before):
            add("weekday_annotation", m.group(0), off)   # §0.1 括号注记需去重
        else:
            add("weekday", m.group(0), off)
    for m in PERIOD_RE.finditer(s):
        off = m.start()
        before = s[max(0, off - 12):off]
        if re.search(r"每天|每周|每月|每日|长期", before):
            continue
        if DATE_NEAR_RE.search(before):
            continue
        if _has_date_clock_before(s, off):
            continue  # 同句已有日期+钟点：时段词保留（白名单）
        add("period", m.group(1), off)
    for m in DAYNUM_RE.finditer(s):
        off = m.start()
        before = s[max(0, off - 12):off]
        if before.endswith("月"):
            continue
        if re.search(r"学号|座号|宿舍|楼|班|第|几$", before[-4:]):
            continue
        after = s[m.end():m.end() + 8]
        if not re.match(r"\s*(上午|下午|晚上|早上|比赛|活动|当天|点名|中午|凌晨|的|场|日)", after):
            continue
        add("daynum", m.group(0), off)
    for m in PROPER_CORRUPT_RE.finditer(s):
        add("proper_noun_corrupted", m.group(0), m.start())
    return out


# 数据层重点卡期望（契约 §0.4 + R1–R7 + Lead 指出的 aiPoints 错位）：
# (gid, 字段范围, must_contain[], forbid_contain[])
# 字段范围：blob=title+summary+points+segments；title_summary；points；segments
BRIEFS_EXPECT = [
    ("g_wxg_c66a85ae46", "blob", ["11-05"], []),
    ("g_ait_7a3370c5a7", "blob", ["11-05"], []),
    ("g_ait_7ebae6c1da", "blob", ["11-05"], []),
    ("g_qqm_7704134971497063025_c0", "blob", ["11-07"], []),
    ("g_qqm_7704134971497063025_c0", "points", ["11-07"], ["11-04"]),
    ("g_ait_5396a55f24", "title_summary", ["11-06", "11-08"], []),
    ("g_ait_5396a55f24", "points", ["11-08"], ["11-05"]),
    ("g_ait_5396a55f24", "segments", ["11-08"], []),
    ("g_qqimg_6d052014c3", "title_summary", ["11-05"], ["5号"]),
    ("g_qqimg_6d052014c3", "points", ["11-05"], ["11-04"]),
    ("g_qqimg_6d052014c3", "segments", ["11-05"], ["11-04"]),
    ("g_qqimg_def2524e9f", "title_summary", ["11-04"], ["4号"]),
    ("g_qqimg_def2524e9f", "points", ["11-04"], ["11-03"]),
    ("g_qqimg_def2524e9f", "segments", ["11-04"], ["11-03"]),
    ("g_ideology", "blob", ["今日校园", "11-03", "11-02"],
     ["10-29校园", "10-28校园", "10-29", "10-30"]),
    ("g_course_select", "blob", ["今日校园", "10-28"], []),
    ("g_dorm", "blob", ["11-04", "每月前三周", "17:30"], ["11-03"]),
    ("g_ait_30fbc46e20", "blob", ["11-06"], []),
    ("g_ait_4a2dcb5dfe", "blob", ["11-05"], []),
    ("g_ait_c6da6536ac", "blob", ["11-04"], []),
    ("g_ait_d3117057d2", "blob", ["11-14"], []),
]


def brief_blob(b):
    pts = b.get("points") or []
    segs = [(x.get("text") or "") for x in (b.get("segments") or []) if isinstance(x, dict)]
    return " | ".join([str(b.get("title") or ""), str(b.get("summary") or ""),
                       " ; ".join(map(str, pts)), " ; ".join(segs)])


def brief_fields(b, kind):
    if kind == "blob":
        return brief_blob(b)
    if kind == "title_summary":
        return str(b.get("title") or "") + " | " + str(b.get("summary") or "")
    if kind == "points":
        return " ; ".join(map(str, b.get("points") or []))
    if kind == "segments":
        return " ; ".join((x.get("text") or "") for x in (b.get("segments") or []) if isinstance(x, dict))
    return brief_blob(b)


def check_briefs():
    """数据层 ai-briefs 硬断言：裸词=0 / 重点卡日期正确 / 文案长度（§0.4）。"""
    try:
        briefs = json.load(open(BRIEFS, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        S("R8.8 数据层 ai-briefs 可读", False, "%s (%s)" % (BRIEFS, type(e).__name__))
        return
    S("R8.8a 数据层 ai-briefs 可读且非空", len(briefs) > 0, "entries=%d" % len(briefs))
    # 裸词
    bad = []
    for gid, b in briefs.items():
        if not isinstance(b, dict):
            continue
        for field, text in [("title", b.get("title")), ("summary", b.get("summary"))]:
            for h in scan_brief_text(text):
                bad.append({"gid": gid, "field": field, **h})
        for i, p in enumerate(b.get("points") or []):
            for h in scan_brief_text(p):
                bad.append({"gid": gid, "field": "points[%d]" % i, **h})
        for i, seg in enumerate(b.get("segments") or []):
            for h in scan_brief_text((seg or {}).get("text")):
                bad.append({"gid": gid, "field": "segments[%d]" % i, **h})
    S("R8.8 数据层 ai-briefs 裸时间/模糊词=0（title/summary/points/segments，含今日校园专名）",
      len(bad) == 0, "命中=%d %s" % (len(bad), json.dumps(bad[:10], ensure_ascii=False)))
    # 重点卡日期
    datebad = []
    for gid, kind, must, forbid in BRIEFS_EXPECT:
        b = briefs.get(gid)
        if not b:
            datebad.append({"gid": gid, "why": "缺 brief 条目"})
            continue
        blob = brief_fields(b, kind)
        miss = [x for x in must if x not in blob]
        hit = [x for x in forbid if x in blob]
        if miss or hit:
            datebad.append({"gid": gid, "field": kind, "missing": miss, "forbidden": hit,
                            "value": norm(blob)[:140]})
    # 括号冗余去重（11月14日（11-14））
    redundant = [gid for gid, b in briefs.items() if isinstance(b, dict)
                 and re.search(r"\d{1,2}月\d{1,2}日\s*[（(]\s*\d{2}-\d{2}\s*[）)]", brief_blob(b))]
    S("R8.9 数据层重点卡日期正确（R1–R7/§0.4：11-05/11-06/11-07/11-14/今日校园/自11-02起）",
      len(datebad) == 0, json.dumps(datebad[:10], ensure_ascii=False))
    S("R8.10 数据层无「11月14日（11-14）」冗余括号", len(redundant) == 0, json.dumps(redundant[:8], ensure_ascii=False))
    S("R8.11 数据层无「下午11-05」类日期前置错位",
      not any(re.search(r"(?:上午|中午|下午|晚上|凌晨|今早)\s*\d{2}-\d{2}", brief_blob(b))
              for b in briefs.values() if isinstance(b, dict)),
      json.dumps([gid for gid, b in briefs.items() if isinstance(b, dict)
                  and re.search(r"(?:上午|中午|下午|晚上|凌晨|今早)\s*\d{2}-\d{2}", brief_blob(b))][:8],
                 ensure_ascii=False))
    # 长度（§0.4：title≤20 / summary≤60 / points≤12 / segments≤40）
    lenbad = []
    for gid, b in briefs.items():
        if not isinstance(b, dict):
            continue
        if len(norm(b.get("title"))) > 20:
            lenbad.append({"gid": gid, "field": "title", "len": len(norm(b.get("title")))})
        if len(norm(b.get("summary"))) > 60:
            lenbad.append({"gid": gid, "field": "summary", "len": len(norm(b.get("summary")))})
        for i, p in enumerate(b.get("points") or []):
            if len(norm(p)) > 12:
                lenbad.append({"gid": gid, "field": "points[%d]" % i, "len": len(norm(p))})
        for i, seg in enumerate(b.get("segments") or []):
            t = norm((seg or {}).get("text"))
            if len(t) > 40:
                lenbad.append({"gid": gid, "field": "segments[%d]" % i, "len": len(t)})
    S("R8.12 数据层文案长度（title≤20/summary≤60/point≤12/segment≤40，契约 §0.4）",
      len(lenbad) == 0, "超限=%d %s" % (len(lenbad), json.dumps(lenbad[:10], ensure_ascii=False)))


def check_time_fields_regression():
    """相对 round-2 基线 board-data 的时间字段回归：除白名单（动作短词/eventAt 补全/同日 00:00→钟点/
    第2轮已确认的 signup 热修）外，任何 deadline/eventAt/signupStart/signupEnd 变化=FAIL（Lead 要求）。"""
    try:
        base = json.load(open(BASE_BOARD, encoding="utf-8"))
        cur = json.load(open(BOARD, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        S("R8.13 时间字段回归对比（vs round-2 基线 board-data）", False,
          "读取失败 %s (%s)" % (type(e).__name__, str(e)[:80]))
        return
    bg = {str(g.get("id")): g for g in base.get("groups") or []}
    cg = {str(g.get("id")): g for g in cur.get("groups") or []}
    fails, allowed = [], []
    for gid in sorted(set(bg) & set(cg)):
        for f in ("deadline", "eventAt", "signupStart", "signupEnd"):
            old, new = bg[gid].get(f), cg[gid].get(f)
            if old == new:
                continue
            ok, why = False, ""
            if f == "eventAt":
                if old in (None, ""):
                    ok, why = True, "eventAt 补全(None→%s)" % new
                elif new in (None, ""):
                    ok, why = True, "eventAt 清理（假时间清除，Lead 口径：太极拳/课程表）"
                elif old and new and str(old)[:10] == str(new)[:10] and str(old)[11:16] == "00:00":
                    ok, why = True, "eventAt 同日钟点修正(00:00→%s)" % str(new)[11:16]
                elif old and new and str(old)[:10] == str(new)[:10]:
                    ok, why = True, "eventAt 同日时间修正(%s→%s)" % (str(old)[11:16], str(new)[11:16])
            elif f == "deadline":
                ok, why = False, "deadline 变化（不允许）"
            else:  # signup*
                if gid in SIGNUP_CHANGE_WHITELIST:
                    ok, why = True, SIGNUP_CHANGE_WHITELIST[gid]
                elif f == "signupStart" and new in (None, "") and old not in (None, ""):
                    cur_g = cg[gid]
                    if str(old) in (str(cur_g.get("signupEnd")), str(cur_g.get("deadline"))):
                        ok, why = True, "假 signupStart 清理（旧值与 signupEnd/deadline 同点）"
            rec = {"gid": gid, "title": cg[gid].get("title"), "field": f, "old": old, "new": new, "why": why}
            (allowed if ok else fails).append(rec)
    S("R8.13 时间字段回归：除白名单外 deadline/eventAt/signup 无未预期变化（vs pre_final_run 基线）",
      len(fails) == 0,
      "未预期变化=%d %s；白名单通过=%d" % (len(fails), json.dumps(fails[:10], ensure_ascii=False), len(allowed)))
    STEPS.append({"k": "R8.13a 时间字段白名单变化（信息）", "ok": True,
                  "note": json.dumps(allowed[:14], ensure_ascii=False)})


def check_games_viewer(recs):
    """Lead 指定：g_games_viewer（校运动会观众征集）报名已截止，chip 必须是「报名截止」而非未来时间。"""
    g = recs.get("g_games_viewer")
    if not g:
        S("R8.14 g_games_viewer 存在", False, "缺卡")
        return
    chip = norm(g.get("chip"))
    se = dt(g.get("signupEnd"))
    dl = dt(g.get("deadline"))
    S("R8.14 g_games_viewer chip=报名截止（已过，不显示未来相对时间）",
      chip.endswith("报名截止") and "11-03" in chip and "小时后" not in chip and "天后" not in chip
      and not re.search(r"11-0[4-9]", chip),
      "chip=%s" % chip)
    S("R8.15 g_games_viewer signupEnd 未被误算（应=2026-11-03 18:30）",
      se is not None and se.strftime("%Y-%m-%d %H:%M") == "2026-11-03 18:30",
      "signupEnd=%s" % g.get("signupEnd"))
    S("R8.16 g_games_viewer deadline=2026-11-03 18:30 且已过",
      dl is not None and dl.strftime("%Y-%m-%d %H:%M") == "2026-11-03 18:30",
      "deadline=%s" % g.get("deadline"))


def lead_notes(recs):
    """Lead 要求记录的已知例外（不判失败）：dorm eventAt、ideology 旧调课卡 chip。"""
    dorm = recs.get("g_dorm") or {}
    ideo = recs.get("g_ideology") or {}
    STEPS.append({"k": "R8.17 备注：dorm eventAt / ideology chip（Lead 已知例外）", "ok": True,
                  "note": "dorm eventAt=%s（recurrence 卡 chip 走长期安排，不参与；契约 R7 示例 11-02 按 Lead 口径以 11-04 为准）；"
                          "ideology chip=%s（旧调课卡历史时间，Lead 确认 OK）" % (
                              dorm.get("eventAt"), ideo.get("chip"))})


def write_report(a, recs, hits, reg_details, olda):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    passed = sum(1 for s in STEPS if s["ok"])
    total = len(STEPS)
    L = ["# R3 第三轮验收报告（契约 §0.5 R1–R9 + 旧 A1–A9 回归）", "",
         "- 时间：%s" % ts,
         "- 被测 demo：`%s`" % DEMO,
         "- 固定口径：真实时钟（审计时 now=%s）" % a.get("nowText"),
         "- 结果：**%d/%d PASS，%d FAIL**" % (passed, total, total - passed), "",
         "## PASS/FAIL 清单", ""]
    for s in STEPS:
        L.append("- [%s] %s%s" % ("PASS" if s["ok"] else "FAIL", s["k"],
                                  (" — `" + s["note"] + "`") if s["note"] else ""))
    fails = [s for s in STEPS if not s["ok"]]
    L += ["", "## 失败项与定位建议", ""]
    if not fails:
        L.append("- 无")
    else:
        hints = {
            "R1": "检查 notice_time 对 legacy 微信卡「下午」的 eventAt 补全 + ai_brief v6 摘要/标题日期化 + board absRelDates 标题兜底",
            "R2": "检查 7a3370c5a7/7ebae6c1da 的 aiSummary/points 日期化（pipeline v6）与 chip 短动作",
            "R3": "检查 board §0.3 版式：有 aiSummary 的卡不内联 text/follow；按钮含 3 条",
            "R4": "检查合并卡版式 + deadlineAction 缩写（报送姓名截止→报送截止）",
            "R5": "检查 notice_time 日号解析（5号→11-05）与 eventAt 钟点候选（不得被 00:00 抢占）",
            "R6": "检查 replace_relative_dates 专有名词白名单（今日校园）与括号去重",
            "R7": "检查长期安排卡 aiSummary 格式（自 11-02 起 + 周期）与 chip label",
            "R8": "逐卡看 data/rendered/modal 命中与 chip 动作（pipeline v6 + board 短动作/absRelDates）",
            "R9": "看回归日志 accept/regression/*.log 与旧 v2_notice_time_check 兼容性记录",
        }
        for s in fails:
            key = s["k"].split(" ")[0]
            L.append("- **%s**：%s" % (s["k"], (s["note"] or "")[:400]))
            L.append("  - 定位建议：%s" % hints.get(key, "见明细"))
    L += ["", "## 逐卡 44 组审计表", "",
          "| id | chip | 动作 | 动作长度 | 数据裸词 | 渲染裸词 | 弹层裸词 | 内联原文 | 按钮条数 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for gid, g in recs.items():
        act, _ = chip_action(norm(g.get("chip")))
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            gid, g.get("chip"), act, len(act),
            len(hits["data"].get(gid) or []), len(hits["rendered"].get(gid) or []),
            len(hits["modal"].get(gid) or []), g.get("inline"), g.get("origItemCount")))
    L += ["", "## 回归明细", ""]
    for d in reg_details:
        L.append("- %s：exit=%s %.1fs | %s" % (d["test"], d["exit"], d["seconds"], " | ".join(d["tail"])))
    if olda is not None:
        L += ["", "## 旧 A1–A9 脚本兼容性（信息）", "",
              "- exit=%s" % olda.get("exit"),
              "- %s" % olda.get("note")]
        for f in olda.get("fails") or []:
            L.append("  - %s" % f[:220])
    L += ["", "## 证据", "- accept_audit.json（审计原始事实）/ audit_run.log",
          "- shots/*.png（药膳 c0、申报合并、下午招聘会、qqimg 5号卡）", "- regression/*.log"]
    open(os.path.join(OUT, "acceptance_report.md"), "w", encoding="utf-8").write("\n".join(L))
    json.dump({"generatedAt": ts, "demo": DEMO, "now": a.get("now"),
               "passed": passed, "total": total, "steps": STEPS,
               "groups": a.get("groups"), "hits": a.get("hits"),
               "regressions": reg_details, "oldA": olda},
              open(os.path.join(OUT, "acceptance_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def main():
    os.makedirs(OUT, exist_ok=True)
    a = json.load(open(os.path.join(OUT, "baseline_audit.json"), encoding="utf-8")) \
        if os.environ.get("R3_SKIP_AUDIT") == "1" else run_audit()
    recs, hits = build_index(a)
    S("R0.1 被测 demo 44 组可审计（headless Edge）", len(recs) == 44, "groups=%s" % len(recs))
    check_r1(recs, hits)
    check_r2(recs, hits)
    check_r3(recs, hits)
    check_r4(recs, hits)
    check_r5(recs, hits)
    check_r6(recs, hits)
    check_r7(recs, hits)
    check_r8(recs, hits, a)
    check_briefs()
    check_time_fields_regression()
    check_games_viewer(recs)
    lead_notes(recs)
    check_r9(recs, a)
    reg_details = run_regressions()
    olda = run_old_a_check()
    write_report(a, recs, hits, reg_details, olda)
    passed = sum(1 for s in STEPS if s["ok"])
    total = len(STEPS)
    print("=" * 64)
    print("r3_accept: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("报告：%s" % os.path.join(OUT, "acceptance_report.md"))
    print("=" * 64)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
