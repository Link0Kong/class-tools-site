# -*- coding: utf-8 -*-
"""v2 专项自检：龙狮系列活动的「报名成功后扫码进群」上下文（2026-11-22）。

用户反馈：「我发现11月22日（今天） 12:00 前进打卡群的上下文联系有问题」。
现象与根因：
  · 同一条 QQ 合并转发里，「成功报名的同学加入对应的二维码，在11月22日12点之前进群，到点即锁群」
    被 AI 聚类拆成单独一张卡（标题直接变成时间 + 动作、分类成班级事务）；
  · 它说的三张群二维码图片被 redistribute_images 挂到了同记录里有附件的活动卡上；
  · 活动卡（龙狮系列主题活动）因报名 11-21 22:00 截止被状态机判成「已截止」移出主列表，
    于是主列表只剩那张没有上下文的进群卡。
修复口径：
  · 「报名成功/扫码/进群/锁群」的单条短补充片段并回同记录唯一的活动主体卡（条目记为补充通知）；
  · 进群要求写进摘要/要点/分段（11-22 12:00 前扫码进群，到点锁群）；
  · 主截止仍是作品提交 11-25 23:00（不是进群），报名截止已过不再让整卡提前过期
    （去掉已过的 signupEnd，卡片跟踪剩下的截止；报名窗口仍在分段里）；
  · 三张群二维码与说明在同一张卡上。

运行（需要 briefdesk venv + 本机 Edge）：
  G:\\ClassTools\\briefdesk\\venv\\Scripts\\python.exe G:\\ClassTools\\web\\tools\\tests\\v2_notice_qrgroup_check.py
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
FIX_NOW = "2026-11-22T08:40:00+08:00"
STEPS = []

# 没有上下文的「补充片段」卡：标题只有时间 + 进群/锁群动作，不含活动名/报名等主体信息
_FRAGMENT_TITLE_RE = re.compile(r"^\s*\d{1,2}[-.]\d{1,2}.*(进群|进打卡群|扫码|锁群)")


def T(k, ok, note=""):
    STEPS.append(bool(ok))
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def load_board():
    return json.load(open(BOARD, encoding="utf-8"))


def find_activity(data):
    hits = []
    for g in data.get("groups") or []:
        text = str(g.get("title") or "") + " " + str(g.get("aiSummary") or "")
        if ("龙狮" in text or "翰墨腾龙韵" in text) and "进群" not in str(g.get("title") or ""):
            hits.append(g)
    return hits


def all_text(g):
    return "\n".join(str(it.get("text") or it.get("name") or it.get("caption") or "")
                     for it in (g.get("items") or []) if isinstance(it, dict))


def segment_text(g):
    return " ".join(str(s.get("text") or "") for s in (g.get("aiSegments") or []) if isinstance(s, dict))


def data_checks():
    data = load_board()
    titles = [str(g.get("title") or "") for g in data.get("groups") or []]
    frag = [t for t in titles if _FRAGMENT_TITLE_RE.search(t)]
    T("D1 不再有「时间 + 进群/锁群」的孤立补充卡", not frag, frag)
    hits = find_activity(data)
    T("D2 龙狮系列活动只有一张活动卡", len(hits) == 1, [g.get("id") for g in hits])
    if not hits:
        return None
    g = hits[0]
    gid = str(g.get("id") or "")
    T("D3 分类是活动（不再是班级事务）", g.get("cat") in ("活动", "文体", "志愿"), g.get("cat"))
    items = [it for it in (g.get("items") or []) if isinstance(it, dict)]
    kinds = [it.get("kind") for it in items]
    T("D4 说明与三张群二维码在同一张卡", "file" in kinds and kinds.count("img") >= 3
      and any("重新开放" not in str(it.get("text") or "") and "进群" in str(it.get("text") or "")
              for it in items), {"kinds": kinds})
    T("D5 补充片段条目标记为「补充通知」",
      any(it.get("kind") == "text" and it.get("label") == "补充通知" and "锁群" in str(it.get("text") or "")
          for it in items),
      [(it.get("label"), str(it.get("text") or "")[:20]) for it in items if it.get("kind") == "text"])
    summary = str(g.get("aiSummary") or g.get("summary") or "")
    points = " ".join(str(x) for x in (g.get("aiPoints") or []))
    segs = segment_text(g)
    T("D6 摘要写明 11-22 12:00 前扫码进群", "12:00" in summary and "扫码进群" in summary, summary)
    T("D7 要点/分段写进群与到点锁群",
      "进群" in points and "进群" in segs and "锁群" in segs, {"points": points, "segs": segs[:120]})
    T("D8 主截止是作品提交（不是进群），活动期内不提前过期",
      str(g.get("deadline") or "").startswith("2026-11-25T23:00") and g.get("deadlineAction") == "提交截止"
      and not g.get("signupEnd") and str(g.get("expireAt") or "").startswith("2026-11-25"),
      {"deadline": g.get("deadline"), "deadlineAction": g.get("deadlineAction"),
       "signupEnd": g.get("signupEnd"), "expireAt": g.get("expireAt")})
    T("D9 报名窗口（11-21 18:00-22:00）仍保留在分段里",
      "11-21 18:00-22:00" in segs and "报名" in segs, segs[:200])
    text = all_text(g)
    T("D10 进群原文与活动原文都在同一张卡上",
      "到点即锁群" in text and "活动时间" in text and "报名" in text, text[:160])
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
          var frag=W.GROUPS.filter(function(x){return /^\\s*\\d{1,2}[-.]\\d{1,2}.*(进群|扫码|锁群)/.test(x.title||'')});
          return {key:s.key,label:s.label,inMain:!!el,
                  chip:el&&el.querySelector('.st')?el.querySelector('.st').textContent:'',
                  imgs:el?el.querySelectorAll('.imgrow img').length:0,
                  txt:el?el.textContent.slice(0,500):'',
                  fragN:frag.length,
                  fragInList:frag.filter(function(x){return !!document.querySelector('#list article.gcard[data-gid="'+x.id+'"]')}).length};})()"""
                   % (gid, gid))
        T("B1 活动卡在主列表、状态 active（不是已截止）",
          not st.get("miss") and st.get("key") == "active" and st.get("inMain"), st)
        T("B2 卡片显示作品提交截止（11-25 23:00）",
          "提交截止" in (st.get("chip") or "")
          and ("11月25日" in (st.get("chip") or "") or "天后" in (st.get("chip") or "")), st.get("chip"))
        T("B3 卡片正文有「扫码进群」和今天 12:00",
          "扫码进群" in (st.get("txt") or "") and "11月22日（今天） 12:00" in (st.get("txt") or ""),
          (st.get("txt") or "")[:200])
        T("B4 卡片里能看到群二维码图片", (st.get("imgs") or 0) >= 3, st.get("imgs"))
        T("B5 主列表没有孤立的进群补充卡", st.get("fragN") == 0 and st.get("fragInList") == 0, st)
        errs = p.all_errors()
        T("B6 0 JS 报错", sum(len(v) for v in errs.values()) == 0,
          {k: v[:3] for k, v in errs.items() if v})
        try:
            os.makedirs(os.path.join(HERE, "_v2_notice_reports"), exist_ok=True)
            p.evaluate("""(function(){var el=document.querySelector('#list article.gcard[data-gid="%s"]');
              if(el){el.scrollIntoView({block:'center'});el.classList.add('flash');}})()""" % gid)
            p.sleep(0.6)
            p.screenshot(os.path.join(HERE, "_v2_notice_reports", "qrgroup_card.png"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        b.close()


def static_checks():
    demo = open(DEMO, encoding="utf-8").read()
    T("S1 demo 含龙狮活动与进群要求", "龙狮" in demo and "扫码进群" in demo)


def main():
    gid = data_checks()
    static_checks()
    if gid:
        run_browser(gid)
    bad = sum(1 for x in STEPS if not x)
    print("=" * 60)
    print("v2_notice_qrgroup_check: %d 项，PASS %d，FAIL %d" % (len(STEPS), len(STEPS) - bad, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
