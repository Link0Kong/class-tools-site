# -*- coding: utf-8 -*-
"""v2 专项自检：屏山慢跑「补报名」通知识别修正（2026-11-18）。

用户反馈：屏山慢跑打卡 11 月 17 日（本周二）补报名的消息识别出现
  · 分组异常（重复转发的全文被并进同一卡、标题被局部「补报名」替换）
  · 时间识别异常（AI 把「每日 17:00-20:00」判成长期安排，卡片显示「本次 11-18 17:00」）
  · 通知分类异常（归入长期通知、不进待处理）
修复口径（契约 `通知三端_长期通知与时间显示_契约_20261114.md` §1.2 + 本次数据修正）：
  · 固定日期范围内的活动不是长期安排（recurrence 不得与 signup/deadline/eventAt 并存）；
  · 标题回到活动主体，补报名作为一次性活动时间（11-17 17:00 补报名），活动至 11-27；
  · 补报名卡进主列表（活动分类），chip「11月17日（本周二） 17:00 补报名」，不再显示「长期安排」；
  · 合并去重：重复转发的全文只保留一份，补报名原文保留。
"""
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
import _cdp  # noqa: E402

DEMO = os.path.join(ROOT, "notice-board-live-demo.html")
INDEX = os.path.join(ROOT, "index.html")
BOARD = r"C:\briefdesk\data\board-data.json"
GID = "g_qqm_7707958493357894546_c0"
STEPS = []


def T(k, ok, note=""):
    STEPS.append(bool(ok))
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def load_board_group():
    d = json.load(open(BOARD, encoding="utf-8"))
    for g in d.get("groups") or []:
        if g.get("id") == GID:
            return g
    return None


def _norm(s):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(s or ""))


def data_checks():
    g = load_board_group()
    T("D1 目标通知组存在", bool(g), GID)
    if not g:
        return
    T("D2 标题回到活动主体（不再以「补报名」当标题）",
      "冬季" in g.get("title", "") and "慢跑" in g.get("title", "")
      and "补报名" not in g.get("title", ""), g.get("title"))
    T("D3 分类 = 活动（不是长期安排）", g.get("cat") == "活动", g.get("cat"))
    T("D4 长期安排 recurrence 已移除", not (isinstance(g.get("recurrence"), dict) and g["recurrence"].get("freq")),
      g.get("recurrence"))
    T("D5 时间识别 = 11-17 17:00 补报名（一次性活动时间）",
      str(g.get("eventAt") or "").startswith("2026-11-17T17:00") and g.get("eventAction") == "补报名",
      {"eventAt": g.get("eventAt"), "eventAction": g.get("eventAction")})
    T("D6 活动期至 11-27 20:00（expireAt 保留）",
      str(g.get("expireAt") or "").startswith("2026-11-27T20:00"), g.get("expireAt"))
    T("D7 actionable = true（补报名可处理，不再被长期安排强制不可处理）",
      g.get("actionable") is True, g.get("actionable"))
    texts = [str(it.get("text") or "") for it in (g.get("items") or []) if it.get("kind") in ("text", "follow")]
    long_texts = [t for t in texts if len(_norm(t)) >= 40]
    dup = len(long_texts) - len({_norm(t) for t in long_texts})
    T("D8 重复转发的同原文只保留一份（无重复长文；活动原文 + 补报名原文各 1）",
      dup == 0 and sum(1 for t in long_texts if "阳气内藏" in t) == 1
      and sum(1 for t in long_texts if "重新开放报名" in t) == 1,
      [t[:24] for t in long_texts])
    T("D9 补报名原文保留、附件保留",
      any("重新开放报名" in t for t in texts)
      and any(it.get("kind") == "file" for it in (g.get("items") or [])))
    segs = g.get("aiSegments") or []
    seg_txt = " ".join(str(x.get("text") or "") for x in segs if isinstance(x, dict))
    T("D10 AI 段落时间修正：11-16至11-27、补报名 11-17（不再 11-16至11-16 / 11-16 17:00）",
      "11-16至11-27" in seg_txt and "11-16至11-16" not in seg_txt
      and "11-17 17:00补报名" in seg_txt and "11-16 17:00重新开放" not in seg_txt,
      [x.get("text") for x in segs if isinstance(x, dict)][:4])
    # 通用守卫：任何组都不得同时有 recurrence 和一次性时间（修复前的冲突模式）
    bad = []
    for x in json.load(open(BOARD, encoding="utf-8")).get("groups") or []:
        if not (isinstance(x.get("recurrence"), dict) and x["recurrence"].get("freq")):
            continue
        finite = any(x.get(k) for k in ("signupStart", "signupEnd", "deadline", "eventAt")) or bool(x.get("signupWindows"))
        if finite:
            bad.append(x.get("id"))
    T("D11 通用守卫：无「长期安排 + 一次性时间」并存组", not bad, bad)


def run_browser():
    b = _cdp.Browser(window=(430, 900))
    try:
        p = b.new_page()
        p.set_device(430, 900, 2.0)
        p.navigate("file:///" + DEMO.replace("\\", "/"))
        p.wait_load(60)
        p.wait_for("typeof GROUPS !== 'undefined'", 60)
        time.sleep(0.7)
        # 固定到用户反馈当天（11-18 12:45）——补报名已过、活动仍在进行
        p.evaluate("window.__zqSetNow && window.__zqSetNow(Date.parse('2026-11-18T12:45:00+08:00'))")
        time.sleep(0.3)
        st = p.evaluate("""(function(){var W=window,V=W.__zqTest;
          var g=W.GROUPS.filter(function(x){return x.id==='%s'})[0];
          if(!g)return {miss:true};
          var s=V.statusOf(g), dom=document.querySelector('#list .gcard[data-gid="%s"]');
          var chip=dom?(dom.querySelector('.st')||{}).textContent:'';
          var info=W.infoGroups().map(function(x){return x.id});
          return {key:s.key,label:s.label,chip:chip,isTime:W.isTimeGroup(g),isInfo:W.isInfoGroup(g),
                  isLongterm:W.isLongtermGroup(g),rank:W.orderRank(s,g),inMain:!!dom,inInfo:info.indexOf('%s')>=0,
                  statRecur:+document.querySelector('#statRecur').textContent,
                  recurN:W.GROUPS.filter(function(x){return x.recurrence&&x.recurrence.freq}).length,
                  ongoingN:W.GROUPS.filter(function(x){return x.recurrence&&x.recurrence.freq&&W.recurOngoing(x.recurrence,V.nowMs())}).length,
                  mainN:document.querySelectorAll('#list .gcard').length,
                  errs:(window.__errs||[]).length};})()""" % (GID, GID, GID))
        T("B1 状态 = active（不是长期安排/本次）", st.get("key") == "active", st)
        T("B2 chip = 11-17 17:00 补报名", "11月17日（本周二） 17:00 补报名" in (st.get("chip") or ""), st.get("chip"))
        T("B3 主列表包含该卡、不在资料栏、不算长期通知", st.get("inMain") and not st.get("inInfo")
          and not st.get("isLongterm") and st.get("isTime") and not st.get("isInfo"), st)
        T("B4 排序档 3（活动/进行中，非长期安排档 5）", st.get("rank") == 3, st.get("rank"))
        T("B5 长期通知卡数字 = 进行中安排数（该组已移除；11-18 当天军训请假日程已结束）",
          st.get("statRecur") == st.get("ongoingN") and st.get("recurN") == 2, st)
        T("B6 0 JS 报错", st.get("errs") == 0, st.get("errs"))
        os.makedirs(os.path.join(HERE, "_v2_notice_reports"), exist_ok=True)
        try:
            p.screenshot(os.path.join(HERE, "_v2_notice_reports", "slowrun_fix.png"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        b.close()


def static_checks():
    demo = open(DEMO, encoding="utf-8").read()
    idx = open(INDEX, encoding="utf-8").read()
    m = re.search(r'var NOTICE_TPL_B64="([A-Za-z0-9+/=]+)"', idx)
    emb = ""
    if m:
        import base64
        try:
            emb = base64.b64decode(m.group(1)).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            emb = ""
    T("S1 demo 含活动标题与 resolve 修正后的数据", "冬季傍晚慢跑打卡" in demo and "屏山11-17 17:00补报名" in demo)
    if emb:
        T("S2 嵌入模板与 demo 一致（含发布时间统一/活动状态逻辑）",
          "publishedTsOf" in emb and "published" in emb)


def main():
    data_checks()
    static_checks()
    run_browser()
    bad = sum(1 for x in STEPS if not x)
    print("=" * 60)
    print("v2_notice_slowrun_check: %d 项，PASS %d，FAIL %d" % (len(STEPS), len(STEPS) - bad, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
