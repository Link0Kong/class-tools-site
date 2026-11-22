# -*- coding: utf-8 -*-
"""v2 专项自检：军事理论组队/分组与组名报送（2026-11-23）。

用户反馈：「穴位打卡寻宝分组及组名报送识别错误，分组是军事理论的分组」。
现象与根因：
  · 11-19「军事理论组队每队6人」先成了一张卡；
  · 11-22 23:32 两条活动宣发名（「穴位打卡寻宝」「识艾护己，闯关同行」）连同 23:43 的 @分组名单、
    23:47「分组结果已出，明天中午12点前把组名给学委」又被 AI 归成一张「穴位打卡寻宝分组及组名报送」；
  · 分组其实是军事理论课（每队6人、11-22 晚自习后未组队者随机分组）的后续，活动名只是碎片。
修复口径：
  · 同一来源群里「组队 → 随机分组 → 组名报送」并成一张（保留最早发布卡，后续消息作为补充通知，
    更晚的报送截止覆盖旧的；纯活动名/[image] 碎片丢弃）；
  · 该卡 11-23 12:00 前把组名报给学委；活动宣发名与分组无关，穴位打卡寻宝活动卡保持独立。

运行（需要 briefdesk venv + 本机 Edge）：
  G:\\ClassTools\\briefdesk\\venv\\Scripts\\python.exe G:\\ClassTools\\web\\tools\\tests\\v2_notice_grouping_check.py
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
FIX_NOW = "2026-11-23T07:45:00+08:00"
STEPS = []

# 失败模式：分组/组名报送卡挂了别的活动名（穴位打卡寻宝 / 识艾护己）
_BAD_TITLE_RE = re.compile(r"(穴位|识艾|防艾|慢跑).{0,12}(分组|组名)")
_FRAGMENTS = ("穴位打卡寻宝", "识艾护己，闯关同行", "[image]")


def T(k, ok, note=""):
    STEPS.append(bool(ok))
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def load_board():
    return json.load(open(BOARD, encoding="utf-8"))


def card_text(g):
    parts = []
    for it in g.get("items") or []:
        if isinstance(it, dict):
            parts.append(str(it.get("text") or it.get("name") or ""))
    return "\n".join(parts)


def data_checks():
    data = load_board()
    groups = data.get("groups") or []
    titles = [str(g.get("title") or "") for g in groups]
    bad = [t for t in titles if _BAD_TITLE_RE.search(t)]
    T("D1 没有挂活动名的分组/组名报送卡", not bad, bad)
    teams = [g for g in groups if "军事理论" in str(g.get("title") or "")]
    T("D2 军事理论组队/分组只有一张卡", len(teams) == 1, [g.get("id") for g in teams])
    if not teams:
        return None
    g = teams[0]
    gid = str(g.get("id") or "")
    text = card_text(g)
    T("D3 组队通知 + 随机分组 + 组名报送在同一张卡", "每队6人" in text and "@" in text
      and "分组结果已出" in text and "组名" in text, text[:200])
    T("D4 报送截止 = 11-23 12:00 报送截止",
      str(g.get("deadline") or "").startswith("2026-11-23T12:00") and g.get("deadlineAction") == "报送截止",
      {"deadline": g.get("deadline"), "deadlineAction": g.get("deadlineAction")})
    summary = str(g.get("aiSummary") or g.get("summary") or "")
    points = " ".join(str(x) for x in (g.get("aiPoints") or []))
    segs = " ".join(str(s.get("text") or "") for s in (g.get("aiSegments") or []) if isinstance(s, dict))
    T("D5 摘要写明组队 + 随机分组 + 组名报学委",
      "军事理论" in summary and "随机分组" in summary and "组名" in summary and "12:00" in summary, summary)
    T("D6 要点/分段写 11-23 12:00 与组名报学委",
      "11-23 12:00" in points and "组名" in points and "组名报给学委" in segs, {"points": points, "segs": segs[:160]})
    T("D7 活动名碎片（穴位打卡寻宝/识艾护己/[image]）不在该卡",
      not any(f in text for f in _FRAGMENTS), [f for f in _FRAGMENTS if f in text])
    T("D8 标「已更新」", bool(g.get("supplement") is True or g.get("updatedAt")),
      {"supplement": g.get("supplement"), "updatedAt": g.get("updatedAt")})
    # 穴位打卡活动卡保持独立、不含分组内容
    act = [x for x in groups if "穴位" in str(x.get("title") or "")]
    T("D9 穴位打卡寻宝活动卡仍独立存在", len(act) == 1, [x.get("id") for x in act])
    if act:
        atext = card_text(act[0])
        T("D10 活动卡不含分组/组名报送内容",
          "@" not in atext and "组名" not in atext and "分组结果" not in atext, atext[:160])
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
          var s=V.statusOf(g), el=document.querySelector('#list article.gcard[data-gid="%s"]');
          var badTitles=W.GROUPS.filter(function(x){return /(穴位|识艾|防艾|慢跑).{0,12}(分组|组名)/.test(x.title||'')});
          return {key:s.key,label:s.label,inMain:!!el,
                  chip:el&&el.querySelector('.st')?el.querySelector('.st').textContent:'',
                  txt:el?el.textContent.slice(0,420):'',
                  badN:badTitles.length,
                  badInList:badTitles.filter(function(x){return !!document.querySelector('#list article.gcard[data-gid="'+x.id+'"]')}).length};})()"""
                   % (gid, gid))
        T("B1 军事理论卡在主列表、未过期", not st.get("miss")
          and st.get("key") in ("active", "today", "soon", "urgent") and st.get("inMain"), st)
        T("B2 chip 显示报送截止", "报送截止" in (st.get("chip") or ""), st.get("chip"))
        T("B3 卡片正文含组队与组名报学委",
          "每队6人" in (st.get("txt") or "") and "组名" in (st.get("txt") or "")
          and "随机分组" in (st.get("txt") or ""), (st.get("txt") or "")[:200])
        T("B4 卡片正文不含穴位打卡寻宝/识艾护己碎片",
          "穴位打卡寻宝" not in (st.get("txt") or "") and "识艾护己" not in (st.get("txt") or ""),
          (st.get("txt") or "")[:200])
        T("B5 主列表没有挂活动名的分组卡", st.get("badN") == 0 and st.get("badInList") == 0, st)
        errs = p.all_errors()
        T("B6 0 JS 报错", sum(len(v) for v in errs.values()) == 0,
          {k: v[:3] for k, v in errs.items() if v})
        try:
            os.makedirs(os.path.join(HERE, "_v2_notice_reports"), exist_ok=True)
            p.evaluate("""(function(){var el=document.querySelector('#list article.gcard[data-gid="%s"]');
              if(el){el.scrollIntoView({block:'start'});el.classList.add('flash');}})()""" % gid)
            p.sleep(0.6)
            p.screenshot(os.path.join(HERE, "_v2_notice_reports", "grouping_card.png"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        b.close()


def static_checks():
    demo = open(DEMO, encoding="utf-8").read()
    T("S1 demo 含军事理论组队与分组结果", "军事理论" in demo and "分组结果已出" in demo)


def main():
    gid = data_checks()
    static_checks()
    if gid:
        run_browser(gid)
    bad = sum(1 for x in STEPS if not x)
    print("=" * 60)
    print("v2_notice_grouping_check: %d 项，PASS %d，FAIL %d" % (len(STEPS), len(STEPS) - bad, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
