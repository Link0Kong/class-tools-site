# -*- coding: utf-8 -*-
"""v2 专项自检：冬季傍晚慢跑打卡活动（限期活动 + 报名）不得被判成长期通知（2026-11-21）。

用户反馈：「修复将冬季傍晚慢跑打卡活动识别成长期通知的问题，实际该内容也为活动之一，需要报名，
通知内应该展示的是活动报名开始和截止时间」。

修复口径：
  · 同一活动的「活动介绍全文」与「补报名 + 策划书附件」合并成一张卡（AI 聚类拆成两张）；
  · 限期活动（11-16 至 11-27，每日 17:00-20:00）不是长期安排：recurrence 必须为空；
  · 报名开始 = 11-16 17:00（策划书「报名时间：2026年11月16日17:00」），原文只写「报满即止」，
    不虚构报名截止（signupEnd / deadline 留空），摘要与要点写出「报满即止」；
  · 卡片进主列表（状态 active，chip「11月16日（本周一） 17:00 报名开始」），长期通知计数不含该组。

运行（需要 briefdesk venv + 本机 Edge）：
  G:\\ClassTools\\briefdesk\\venv\\Scripts\\python.exe G:\\ClassTools\\web\\tools\\tests\\v2_notice_slowrun_check.py
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
import _cdp  # noqa: E402

DEMO = os.path.join(ROOT, "notice-board-live-demo.html")
BOARD = r"C:\briefdesk\data\board-data.json"
TITLE_KEY = "冬季傍晚慢跑"
FIX_NOW = "2026-11-21T21:40:00+08:00"
STEPS = []

# 限期活动（正文写死起止日期 + 活动语义）不可能是长期安排：与 builder 的确定性规则同口径
_ACTIVITY_WORD_RE = re.compile(r"活动|打卡|比赛|赛事|运动会|培训|讲座|课程|征集|展演|演出|沙龙|决赛|选拔|体验")
_RECUR_CHORE_RE = re.compile(r"请假|报备|卫生检查|例行检查|值班|例会|考勤|查寝|点名")
_DATE_RANGE_RE = re.compile(
    r"(?:(?:20\d{2})\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*[日号]?\s*[-—–~～至到]\s*"
    r"(?:(?:20\d{2})\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*[日号]?")


def T(k, ok, note=""):
    STEPS.append(bool(ok))
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def load_board():
    return json.load(open(BOARD, encoding="utf-8"))


def find_group(data):
    hits = [g for g in data.get("groups") or [] if TITLE_KEY in str(g.get("title") or "")]
    return hits


def group_text(g):
    return "\n".join(str(it.get("text") or it.get("name") or "")
                     for it in (g.get("items") or []) if isinstance(it, dict))


def data_checks():
    data = load_board()
    hits = find_group(data)
    T("D1 慢跑打卡活动只有一张卡（介绍 + 补报名 + 策划书已合并）", len(hits) == 1,
      [g.get("id") for g in hits])
    if not hits:
        return None
    g = hits[0]
    gid = str(g.get("id") or "")
    T("D2 不再是长期安排（recurrence 为空）",
      not (isinstance(g.get("recurrence"), dict) and g["recurrence"].get("freq")), g.get("recurrence"))
    T("D3 报名开始 = 11-16 17:00（策划书「报名时间」）",
      str(g.get("signupStart") or "").startswith("2026-11-16T17:00"), g.get("signupStart"))
    T("D4 不虚构报名截止（signupEnd / deadline 留空，原文是报满即止）",
      not g.get("signupEnd") and not g.get("deadline"),
      {"signupEnd": g.get("signupEnd"), "deadline": g.get("deadline")})
    T("D5 活动开始 = 11-16 17:00，动作=报名开始（卡片 chip 用）",
      str(g.get("eventAt") or "").startswith("2026-11-16T17:00") and g.get("eventAction") == "报名开始",
      {"eventAt": g.get("eventAt"), "eventAction": g.get("eventAction")})
    T("D6 活动期至 11-27 20:00（expireAt 保留），可处理",
      str(g.get("expireAt") or "").startswith("2026-11-27T20:00") and g.get("actionable") is True,
      {"expireAt": g.get("expireAt"), "actionable": g.get("actionable")})
    summary = str(g.get("aiSummary") or g.get("summary") or "")
    points = " ".join(str(x) for x in (g.get("aiPoints") or []))
    segs = " ".join(str(x.get("text") or "") for x in (g.get("aiSegments") or []) if isinstance(x, dict))
    T("D7 摘要/要点/分段写出报名开始与「报满即止」",
      "报名" in summary and "报满即止" in summary and "报名" in points and "报满即止" in points
      and "报名" in segs and "报满即止" in segs, {"summary": summary, "points": points})
    text = group_text(g)
    T("D8 合并卡保留补报名原文与策划书附件（报名信息随卡可见）",
      "重新开放报名" in text and any(it.get("kind") == "file" for it in (g.get("items") or [])),
      [it.get("kind") for it in (g.get("items") or [])])
    # 通用守卫：任何组都不得既写死活动起止日期、又保留长期安排（本次修复的失败模式）
    bad = []
    for x in data.get("groups") or []:
        if not (isinstance(x.get("recurrence"), dict) and x["recurrence"].get("freq")):
            continue
        tx = group_text(x)
        if _RECUR_CHORE_RE.search(tx) or not _ACTIVITY_WORD_RE.search(str(x.get("title") or "") + tx):
            continue
        if _DATE_RANGE_RE.search(tx):
            bad.append(x.get("id"))
    T("D9 通用守卫：无「限期活动 + 长期安排」并存组", not bad, bad)
    return gid


def run_browser(gid):
    b = _cdp.Browser(window=(430, 900))
    try:
        p = b.new_page()
        p.set_device(430, 900, 2.0)
        p.navigate("file:///" + DEMO.replace("\\", "/"))
        p.wait_load(90)
        p.wait_for("typeof GROUPS !== 'undefined' && typeof __zqTest !== 'undefined'", 90)
        p.sleep(0.8)
        p.evaluate("window.__zqTest.setNow(Date.parse('%s'))" % FIX_NOW)
        p.sleep(0.3)
        st = p.evaluate("""(function(){var W=window,V=W.__zqTest;
          var g=W.GROUPS.filter(function(x){return x.id==='%s'})[0];
          if(!g)return {miss:true};
          var s=V.statusOf(g), dom=document.querySelector('#list article.gcard[data-gid="%s"]');
          var chip=dom&&dom.querySelector('.st')?dom.querySelector('.st').textContent:'';
          var cardTxt=dom?dom.textContent:'';
          return {key:s.key,label:s.label,chip:chip,cardTxt:cardTxt.slice(0,400),
                  isTime:!!W.isTimeGroup&&W.isTimeGroup(g),isInfo:!!W.isInfoGroup&&W.isInfoGroup(g),
                  isLongterm:!!W.isLongtermGroup&&W.isLongtermGroup(g),
                  inInfo:V.infoGroups().map(function(x){return x.id}).indexOf('%s')>=0,
                  inLongterm:V.longtermGroupsNow().map(function(x){return x.id}).indexOf('%s')>=0,
                  statRecur:+document.querySelector('#statRecur').textContent,
                  recurN:W.GROUPS.filter(function(x){return x.recurrence&&x.recurrence.freq}).length,
                  ongoingN:W.GROUPS.filter(function(x){return x.recurrence&&x.recurrence.freq&&V.recurOngoing(x.recurrence,V.nowMs())}).length,
                  mainN:document.querySelectorAll('#list article.gcard').length};})()"""
                   % (gid, gid, gid, gid))
        T("B1 卡片在 GROUPS 中、状态 active（不是长期安排/已过期）",
          not st.get("miss") and st.get("key") == "active", st.get("key") or st)
        T("B2 chip = 11月16日（本周一） 17:00 报名开始",
          "11月16日" in (st.get("chip") or "") and "报名开始" in (st.get("chip") or ""), st.get("chip"))
        T("B3 进主列表：inTime、不在资料栏/长期通知清单",
          st.get("isTime") and not st.get("isInfo") and not st.get("isLongterm")
          and not st.get("inInfo") and not st.get("inLongterm"), st)
        T("B4 卡片正文写出报名与报满即止",
          "报名" in (st.get("cardTxt") or "") and "报满即止" in (st.get("cardTxt") or ""),
          st.get("cardTxt", "")[:120])
        T("B5 长期通知计数 = 进行中安排数，且不含该组",
          st.get("statRecur") == st.get("ongoingN") and not st.get("inLongterm"), st)
        errs = p.all_errors()
        nerr = sum(len(v) for v in errs.values())
        T("B6 0 JS 报错", nerr == 0, {k: v[:3] for k, v in errs.items() if v})
        try:
            os.makedirs(os.path.join(HERE, "_v2_notice_reports"), exist_ok=True)
            p.screenshot(os.path.join(HERE, "_v2_notice_reports", "slowrun_card.png"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        b.close()


def static_checks():
    if not os.path.exists(DEMO):
        T("S1 本地通知模板存在", False, DEMO)
        return
    demo = open(DEMO, encoding="utf-8").read()
    T("S1 模板含「报名开始」状态语义与长期通知筛选", "报名开始" in demo and "longtermGroupsNow" in demo)


def main():
    gid = data_checks()
    static_checks()
    if gid:
        run_browser(gid)
    bad = sum(1 for x in STEPS if not x)
    print("=" * 60)
    print("v2_notice_slowrun_check: %d 项，PASS %d，FAIL %d" % (len(STEPS), len(STEPS) - bad, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
