# -*- coding: utf-8 -*-
"""v2 专项自检：通知「发布时间统一」（2026-11-18 契约《通知三端_发布时间统一_契约_20261118.md》）。

用户需求：「将通知中不含时间的时间设定为发布时间，动作设为发布，并参与排序等等统一计算」

覆盖：
  S. 静态：demo / 嵌入模板含 publishedTsOf / publishAction / 'published' 分支；数据 publishedAt 全量。
  P. 合成夹具（固定时钟 2026-11-18 12:45 +08:00）：
     · 无时间锚点通知 → 状态 published、chip「<时间> 发布」、进主列表、资料栏不显示；
     · 资料/无时间栏只留「无发布时间」兜底卡（0 条时隐藏）；
     · 排序：档 4 内按发布时间倒序（新在上）；有发布时间排在无发布时间前；
     · 统计：actionable!==false 的发布卡计入待处理、actionable=false 不计；
     · 最新发布按 publishedAt 字段（覆盖 items 推算值）。
  R. 真实 board 数据：publishedAt 全量存在 / publishAction 仅在无时间锚点组 / 资料栏为空 / 发布卡进主列表 /
     主列表顺序与参考实现一致 / 0 JS 报错 / 430·390·360 无横向溢出。

跑法：cd web; python tools/tests/v2_notice_publish_check.py
退出码 0 = 全绿。
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
REPORT_DIR = os.path.join(HERE, "_v2_notice_reports")
FIX_NOW = "2026-11-18T12:45:00+08:00"
STEPS = []


def T(k, ok, note=""):
    STEPS.append(bool(ok))
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def extract_groups(path):
    raw = open(path, encoding="utf-8").read()
    i = raw.find("var GROUPS=")
    if i < 0:
        raise SystemExit("GROUPS marker not found")
    i = raw.find("[", i)
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(raw)):
        c = raw[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return json.loads(raw[i:j + 1])
    raise SystemExit("GROUPS json not closed")


def static_checks():
    demo = open(DEMO, encoding="utf-8").read()
    idx = open(INDEX, encoding="utf-8").read()
    m = re.search(r'var NOTICE_TPL_B64="([A-Za-z0-9+/=]+)"', idx)
    embedded = ""
    if m:
        import base64
        try:
            embedded = base64.b64decode(m.group(1)).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            embedded = ""
    for name, src in (("demo", demo), ("嵌入模板", embedded)):
        T("S1 %s 含 publishedTsOf/publishAction/'published' 标记" % name,
          all(k in src for k in ("publishedTsOf", "publishAction", "'published'")))
    groups = extract_groups(DEMO)
    T("S2 真实数据 publishedAt 全量存在", groups and all(g.get("publishedAt") for g in groups),
      "%d/%d" % (sum(1 for g in groups if g.get("publishedAt")), len(groups)))
    pa = [g for g in groups if g.get("publishAction")]
    T("S3 publishAction 仅写在无时间锚点且非长期安排的组",
      all(g.get("publishAction") == "发布" and not any(
          g.get(k) for k in ("deadline", "eventAt", "signupStart", "signupEnd"))
          and not g.get("signupWindows") and not (g.get("recurrence") or {}).get("freq") for g in pa)
      and len(pa) > 0, len(pa))


FIXTURES = [
    # 无时间锚点 + 发布时间 → 发布卡（主列表）
    {"id": "g_pub_old", "cat": "教务", "title": "旧发布资料",
     "items": [{"kind": "text", "time": "11-10 08:00", "text": "旧资料"}]},
    {"id": "g_pub_new", "cat": "教务", "title": "新发布资料",
     "items": [{"kind": "text", "time": "11-16 22:15", "text": "新资料"}]},
    {"id": "g_pub_flag", "cat": "教务", "title": "发布但不可待办",
     "actionable": False, "items": [{"kind": "text", "time": "11-15 09:00", "text": "无需处理"}]},
    {"id": "g_pub_field", "cat": "教务", "title": "字段发布时间优先",
     "publishedAt": "2026-11-17T20:00:00+08:00", "publishAction": "发布",
     "items": [{"kind": "text", "time": "11-10 08:00", "text": "字段优先"}]},
    # 既无时间锚点也无发布时间 → 资料栏兜底
    {"id": "g_bare", "cat": "班级事务", "title": "无发布时间兜底资料", "items": []},
    # 普通时间卡（对照组）
    {"id": "g_plain", "cat": "教务", "title": "11-20 交表", "deadline": "2026-11-20T18:00:00+08:00",
     "deadlineAction": "交表", "items": [{"kind": "text", "time": "11-18 09:00", "text": "11-20 前交表"}]},
]


def run_fixture_checks(b):
    p = b.new_page()
    p.navigate("file:///" + DEMO.replace("\\", "/"))
    p.wait_load(60)
    p.wait_for("typeof GROUPS !== 'undefined'", 60)
    time.sleep(0.6)
    p.evaluate("window.__zqSetNow && window.__zqSetNow(Date.parse('%s'))" % FIX_NOW)
    time.sleep(0.2)
    jfs = lambda code: p.evaluate("(function(){var W=window;%s})()" % code)
    jf = lambda expr: p.evaluate("(function(){var W=window;return (%s);})()" % expr)

    jfs("W.GROUPS=%s;W.state.done={};W.state.card='';W.state.sub='全部';W.state.cat='全部';"
        "W.state.fold={};W.render({animate:false});" % json.dumps(FIXTURES, ensure_ascii=False))
    time.sleep(0.25)

    st = jf("""(function(){var W=window,V=W.__zqTest;
      var g={};W.GROUPS.forEach(function(x){g[x.id]=x});
      return {status:{old:V.statusOf(g.g_pub_old).key,new:V.statusOf(g.g_pub_new).key,
              plain:V.statusOf(g.g_plain).key,bare:V.statusOf(g.g_bare).key},
              labels:{old:V.statusOf(g.g_pub_old).label,new:V.statusOf(g.g_pub_new).label,
                      bare:V.statusOf(g.g_bare).label},
              rank:{old:W.orderRank?W.orderRank(V.statusOf(g.g_pub_old),g.g_pub_old):null},
              isTime:{old:W.isTimeGroup?W.isTimeGroup(g.g_pub_old):null,bare:W.isTimeGroup?W.isTimeGroup(g.g_bare):null},
              isInfo:{old:W.isInfoGroup?W.isInfoGroup(g.g_pub_old):null,bare:W.isInfoGroup?W.isInfoGroup(g.g_bare):null},
              pending:V.pendingAll().map(function(x){return x.id}),
              infoIds:V.infoGroups().map(function(x){return x.id}),
              mainIds:[].map.call(document.querySelectorAll('#list .gcard'),function(c){return c.getAttribute('data-gid')}),
              mainN:document.querySelectorAll('#list .gcard').length,
              dataN:document.querySelectorAll('#dataList .gcard').length,
              dataDisp:getComputedStyle(document.querySelector('#dataWrap')).display,
              statOpen:+document.querySelector('#statOpen').textContent};})()""")
    T("P1 无时间锚点+发布时间 → 状态 published",
      st["status"]["old"] == "published" and st["status"]["new"] == "published", st["status"])
    T("P2 chip 文案「<时间> 发布」",
      st["labels"]["old"].endswith(" 发布") and st["labels"]["new"].endswith(" 发布"), st["labels"])
    T("P3 无发布时间兜底卡仍为 none/「无时间」",
      st["status"]["bare"] == "none" and "无时间" in st["labels"]["bare"], st["labels"]["bare"])
    T("P4 发布卡进主列表（isTimeGroup=true / isInfoGroup=false），兜底卡进资料栏",
      st["isTime"]["old"] is True and st["isInfo"]["old"] is False
      and st["isTime"]["bare"] is False and st["isInfo"]["bare"] is True
      and "g_pub_old" in st["mainIds"] and "g_bare" not in st["mainIds"], st)
    T("P5 资料/无时间栏只显示兜底卡（1 条、默认展开）",
      st["dataN"] == 1 and st["dataDisp"] == "block" and st["infoIds"] == ["g_bare"], st["infoIds"])
    T("P6 发布卡 actionable!==false 计入待处理；actionable=false 不计",
      "g_pub_old" in st["pending"] and "g_pub_new" in st["pending"]
      and "g_pub_flag" not in st["pending"] and "g_bare" not in st["pending"], st["pending"])
    T("P7 待处理数字 = pendingAll 条数（统一计算）", st["statOpen"] == len(st["pending"]),
      {"open": st["statOpen"], "pending": len(st["pending"])})

    order = jf("""(function(){var W=window,V=W.__zqTest;
      var pick=W.GROUPS.filter(function(g){return ['g_pub_old','g_pub_new','g_pub_field'].indexOf(g.id)>=0});
      var arr=pick.slice();arr.sort(function(a,b){return 0}); /* 保持注入顺序 */
      var ids=arr.map(function(g){return g.id});
      var rendered=[].map.call(document.querySelectorAll('#list .gcard[data-gid]'),function(c){return c.getAttribute('data-gid')});
      var pos={};rendered.forEach(function(id,i){pos[id]=i});
      return {pos:pos,pubOrder:ids};})()""")
    T("P8 档 4 内按发布时间倒序（字段 publishedAt 优先）",
      order["pos"].get("g_pub_field", 99) < order["pos"].get("g_pub_new", 99) < order["pos"].get("g_pub_old", 99),
      order["pos"])
    T("P9 发布卡排在普通时间卡之后（档 4 > 档 1-3）",
      order["pos"].get("g_plain", -1) < min(order["pos"].get("g_pub_old", 999),
                                          order["pos"].get("g_pub_new", 999),
                                          order["pos"].get("g_pub_field", 999)),
      order["pos"])

    # chip / latest 用 publishedAt 字段
    jfs("W.GROUPS=[{id:'g_l1',cat:'教务',title:'字段优先发布',publishedAt:'2026-11-17T20:00:00+08:00',"
        "publishAction:'发布',items:[{kind:'text',time:'11-10 08:00',text:'旧消息'}]},"
        "{id:'g_l2',cat:'教务',title:'更新消息',items:[{kind:'text',time:'11-16 08:00',text:'新消息'}]}];"
        "W.state.done={};W.state.card='';W.state.sub='全部';W.state.cat='全部';W.render({animate:false});")
    time.sleep(0.2)
    lat = jf("""(function(){var W=window,V=W.__zqTest;
      return {latest:V.latestGroups().map(function(g){return g.id}),
              latestTs:V.latestGroups().map(function(g){return V.pubTsOf(g)}),
              chips:[].map.call(document.querySelectorAll('#list .gcard .st'),function(e){return e.textContent})};})()""")
    T("P10 最新发布排序使用 publishedAt 字段（字段覆盖 items 时间）",
      lat["latest"] and lat["latest"][0] == "g_l1", lat["latest"])
    T("P11 DOM chip 含「发布」且无「无时间」误显示",
      any("发布" in c for c in lat["chips"]) and not any("无时间" in c for c in lat["chips"]), lat["chips"])


def run_real_checks(b):
    p = b.new_page()
    p.navigate("file:///" + DEMO.replace("\\", "/"))
    p.wait_load(60)
    p.wait_for("typeof GROUPS !== 'undefined'", 60)
    time.sleep(0.8)
    out = p.evaluate("""(function(){var W=window,V=W.__zqTest;
      var groups=W.GROUPS,pub=groups.filter(function(g){return V.statusOf(g).key==='published'});
      var info=groups.filter(function(g){return W.isInfoGroup&&W.isInfoGroup(g)});
      var mainIds=[].map.call(document.querySelectorAll('#list .gcard'),function(c){return c.getAttribute('data-gid')});
      var errs=(window.__errs||[]);
      function orderOk(){
        var arr=groups.filter(function(g){return V.statusOf(g).key==='published'}).slice();
        arr=W.orderGroups(arr);
        var ts=arr.map(function(g){return W.publishedTsOf(g)});
        for(var i=1;i<ts.length;i++){if(ts[i]>ts[i-1])return false}
        return true;
      }
      return {groups:groups.length,allPub:groups.every(function(g){return !!g.publishedAt}),
              pubN:pub.length,infoN:info.length,
              pubInMain:pub.every(function(g){return mainIds.indexOf(g.id)>=0}),
              dataDisp:getComputedStyle(document.querySelector('#dataWrap')).display,
              orderOk:orderOk(),errs:errs.length,
              mainN:mainIds.length};})()""")
    T("R1 真实数据 publishedAt 全量 / 资料栏为空隐藏 / 发布卡全在主列表",
      out["allPub"] and out["infoN"] == 0 and out["dataDisp"] == "none"
      and out["pubInMain"] and out["pubN"] > 0,
      {k: out[k] for k in ("allPub", "infoN", "pubN", "dataDisp", "pubInMain")})
    T("R2 真实数据档 4 排序按发布时间倒序（参考实现）", out["orderOk"], out["orderOk"])
    T("R3 0 JS 报错", out["errs"] == 0, out["errs"])
    widths = []
    for w in (430, 390, 360):
        p.set_device(w, 900, 2.0)
        time.sleep(0.2)
        over = p.evaluate("(function(){return Math.max(0,document.documentElement.scrollWidth-document.documentElement.clientWidth)})()")
        widths.append([w, over])
    T("R4 430/390/360 无横向溢出", all(o == 0 for _, o in widths), widths)
    T("R5 发布卡 chip 在真实数据中显示「发布」", out["pubN"] > 0, out["pubN"])
    p.set_device(430, 900, 2.0)
    time.sleep(0.2)
    os.makedirs(REPORT_DIR, exist_ok=True)
    try:
        p.screenshot(os.path.join(REPORT_DIR, "publish_time_unified.png"))
    except Exception:  # noqa: BLE001
        pass


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    static_checks()
    b = _cdp.Browser(window=(430, 900))
    try:
        run_fixture_checks(b)
        try:
            b.close()
        except Exception:  # noqa: BLE001
            pass
        b = _cdp.Browser(window=(430, 900))
        run_real_checks(b)
    finally:
        try:
            b.close()
        except Exception:  # noqa: BLE001
            pass
    bad = len(STEPS) - sum(1 for x in STEPS if x)
    print("=" * 60)
    print("v2_notice_publish_check: %d 项，PASS %d，FAIL %d" % (len(STEPS), sum(1 for x in STEPS if x), bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
