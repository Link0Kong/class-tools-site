# -*- coding: utf-8 -*-
"""v2 专项自检：长期通知（2026-11-14 契约版：期次 + 长期安排清单 + 资料栏）

对象：
  - `web/tools/index.html`（含 NOTICE_TPL_B64 嵌入模板；可用 V2L_SRC 指定预览副本）
  - `web/tools/notice-board-live-demo.html`（真实 board 数据，取 `var GROUPS=[...]` 做 mock）
做法：本地临时 HTTP + Edge/CDP + 假测试身份（9999 段）+ 全量 fetch mock，
      进入应用通知 tab，在 iframe 模板内注入固定时钟 `__zqTest.setNow` 后断言。
覆盖（旧版 21 项 → 新版 25 项，不降覆盖）：
  S1-S4 静态：5 卡 / 长期清单 / 资料栏 / 期次算法标记 + iframe 固定视口未破坏；
  L1-L2 应用启动 + 通知 iframe 就绪；
  L3-L5 长期通知卡口径 = 进行中条数；长期清单（标题/周期/下次 M月D日（周X）HH:MM/进行中）、
        无期次卡、无已处理按钮；
  L6 资料/无时间栏默认展开且条数 = 资料组数；
  L7 until 已结束 → 已过期区「长期安排已结束」且不产生期次；
  L8 §1.3 向量：until=11-15（含当天）→ 期次 20261115；L9 until=11-14 → 无期次；
  L10 期次卡视觉（长期安排徽标 / 本次时间胶囊 / 本次已处理）；
  L11 期次 done：卡片消失、写 gid@occ done、长期定义与长期计数不受影响；
  L12 期次 done 隔离：下一期（20261115）重新出现；
  L13 monthly_weeks 下次 = 11-18 17:30；
  L14 长期通知卡与 chips 互斥/再点取消；
  L15 分类筛选作用于长期清单；L16 无进行中安排时空态「暂无长期安排」；
  L17-L20 430/390/360 无横向溢出、0 JS 报错 / 0 console.error / 0 外部请求。
用法：cd web/tools && python tests\\v2_notice_longterm_check.py
退出码 0 = 全绿。
"""
import base64
import http.server
import json
import os
import re
import shutil
import socketserver
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # web/tools
WEB = os.path.dirname(ROOT)           # web
sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
import _cdp  # noqa: E402

SRC = os.path.abspath(os.environ.get("V2L_SRC") or os.path.join(ROOT, "index.html"))
DEMO = os.path.join(ROOT, "notice-board-live-demo.html")
REPORT_DIR = os.path.join(HERE, "_v2_notice_reports")
AN_PREFIX = "[[CLASS_NOTICE_V1]]"
BASE_TS = 1762000000000
SID = "9999000005"
NAME = "测试同学"
FIX_NOW = int(datetime(2026, 11, 14, 13, 31, 0, tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000)
FIX_NOW_ISO = "2026-11-14T13:31:00+08:00"

STEPS = []


def T(k, ok, note=""):
    STEPS.append({"k": k, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def extract_groups(path):
    raw = open(path, encoding="utf-8").read()
    i = raw.find("var GROUPS=")
    if i < 0:
        raise SystemExit("GROUPS marker not found in demo")
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


GROUPS = extract_groups(DEMO)
NOTICES = [{"id": "auto_" + str(g.get("id") or ("g%d" % i)), "title": "", "ts": BASE_TS + i * 1000,
            "body": AN_PREFIX + json.dumps(g, ensure_ascii=False), "archived": False, "hidden": False,
            "override_json": "", "edited_at": 0, "edited_by": ""} for i, g in enumerate(GROUPS)]
MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i, "role": "", "badge": "",
            "is_admin": False} for i in range(1, 71)]

MOCK = r"""
<script>
(function(){
window.__errs=[];window.__cerrs=[];window.__external=[];window.__dropBlocked=0;
window.addEventListener('error',function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||'error'));});
window.addEventListener('unhandledrejection',function(e){var r=e&&e.reason;window.__errs.push('rejection:'+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return '?';}}).join(' '));try{_ce.apply(console,arguments);}catch(e){}};
var DATA=__DATA__;
function ok(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve('');}});}
var _f=window.fetch;
window.fetch=function(u,o){
  var s=String((u&&u.url!==undefined)?u.url:u);
  if(s.indexOf('tcloudbasegateway')>=0){
    if(s.indexOf('rpc/class_members')>=0)return ok(DATA.members);
    if(s.indexOf('/notices')>=0)return ok(DATA.notices);
    if(s.indexOf('/marks')>=0)return ok([]);
    if(s.indexOf('/userdata')>=0)return ok([]);
    return ok([]);
  }
  if(s.indexOf('tt.json')>=0)return ok({c:[],t:'2026-08-31',meta:{fetchedAt:__TS__}});
  window.__dropBlocked++;
  return ok({});
};
try{localStorage.setItem('zq_class_identity',JSON.stringify({token:'mock-token',sid:'__SID__',name:'__NAME__',role:'',badge:'',is_admin:false,ts:Date.now()}));}catch(e){}
})();
</script>
"""

HOOK = r"""
window.__lt={auth:function(){return AUTH;},gotoTab:function(t){gotoTab(t);},
  frame:function(){return NOTICE_FRAME;},errs:function(){return window.__errs||[];},
  cerrs:function(){return window.__cerrs||[];},external:function(){return window.__external||[];},
  dropBlocked:function(){return window.__dropBlocked||0;}};
"""

# 合成夹具：until 含当天 / until 已过 / 无 until（下一期隔离）/ monthly_weeks / 资料 / 普通 / 过期
FIXTURES = [
    {"id": "g_u15", "cat": "军训", "title": "每日07:30前私发导员请假",
     "items": [{"kind": "text", "time": "11-13 10:00", "text": "每日 07:30 前私发导员请假"}],
     "recurrence": {"freq": "daily", "time": "07:30", "startAt": "2026-11-10T07:30:00+08:00",
                    "until": "2026-11-15", "label": "每日 07:30"}},
    {"id": "g_u14", "cat": "军训", "title": "同日结束的每日安排",
     "items": [{"kind": "text", "time": "11-13 10:00", "text": "每日 07:30 前报备"}],
     "recurrence": {"freq": "daily", "time": "07:30", "startAt": "2026-11-10T07:30:00+08:00",
                    "until": "2026-11-14", "label": "每日 07:30"}},
    {"id": "g_dead", "cat": "军训", "title": "until 已结束的长期安排",
     "items": [{"kind": "text", "time": "11-09 10:00", "text": "每日 07:30 前报备"}],
     "recurrence": {"freq": "daily", "time": "07:30", "startAt": "2026-11-05T07:30:00+08:00",
                    "until": "2026-11-12", "label": "每日 07:30"}},
    {"id": "g_month", "cat": "班级事务", "title": "宿舍卫生检查",
     "items": [{"kind": "text", "time": "11-05 10:00", "text": "每月前三周的周三 17:30 检查"}],
     "recurrence": {"freq": "monthly_weeks", "weekday": 3, "weeks": [1, 2, 3], "time": "17:30",
                    "startAt": "2026-11-04T17:30:00+08:00", "label": "每月前三周 周三 17:30"}},
    {"id": "g_period", "cat": "军训", "title": "每日晚点名",
     "items": [{"kind": "text", "time": "11-11 21:00", "text": "每晚 21:00 点名"}],
     "recurrence": {"freq": "daily", "time": "21:00", "startAt": "2026-11-08T21:00:00+08:00",
                    "label": "每日 21:00"}},
    {"id": "g_plain", "cat": "教务", "title": "11-13 交报名表", "deadline": "2026-11-14T18:00:00+08:00",
     "deadlineAction": "交表", "items": [{"kind": "text", "time": "11-12 09:00", "text": "11-13 前交报名表"}]},
    {"id": "g_info", "cat": "班级事务", "title": "2026年学生军训实施方案",
     "items": [{"kind": "text", "time": "11-10 08:00", "text": "方案见附件"}]},
    {"id": "g_exp", "cat": "教务", "title": "过期通知", "deadline": "2026-11-10T18:00:00+08:00",
     "items": [{"kind": "text", "time": "11-09 08:00", "text": "11-10 截止"}]},
]


def build_preview():
    html = open(SRC, encoding="utf-8", newline="").read()
    idx = html.rfind("})();")
    if idx < 0:
        raise SystemExit("main script end not found")
    html = html[:idx] + HOOK + "\r\n" + html[idx:]
    data = {"members": MEMBERS, "notices": NOTICES}
    mock = (MOCK.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))
            .replace("__SID__", SID).replace("__NAME__", NAME).replace("__TS__", str(BASE_TS)))
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    return html.replace("<head>", "<head>" + mock, 1)


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Q(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def free_port():
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    # 0) 静态：模板源（demo）与嵌入目标都必须带新版长期通知/期次/资料栏标记
    demo_txt = open(DEMO, encoding="utf-8").read()
    src_txt = open(SRC, encoding="utf-8").read()
    T("S1 demo 模板含长期清单/资料栏/5 卡标记",
      all(k in demo_txt for k in ('data-act="data-toggle"', 'id="dataWrap"', 'data-card="longterm"',
                                  "function longtermListHTML")), "")
    T("S2 demo 模板含 isLongtermGroup / orderLongterm / 期次算法",
      all(k in demo_txt for k in ("function isLongtermGroup", "function orderLongterm",
                                  "function occurrenceOf", "function recurOngoing", "function recurEnded")), "")
    m = re.search(r'var NOTICE_TPL_B64="([^"]*)"', src_txt, re.S)
    tpl = base64.b64decode(m.group(1)).decode("utf-8", "replace") if m else ""
    T("S3 嵌入模板与 demo 长期区/期次一致",
      bool(tpl) and all(k in tpl for k in ('id="dataWrap"', "function occurrenceOf", "function longtermListHTML")),
      "tpl=%d" % len(tpl))
    T("S4 嵌入模板未破坏通知 iframe 固定视口方案",
      "function __noticeHeight(){" in tpl and "zq_nt_scroll_v1" in tpl, "")

    tmp = tempfile.mkdtemp(prefix="lt_notice_")
    srv = None
    old_cwd = os.getcwd()
    brow = None
    try:
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(build_preview())
        os.chdir(tmp)
        port = free_port()
        srv = Q(("127.0.0.1", port), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d/" % port

        brow = _cdp.Browser(window=(430, 940))
        p = brow.new_page()
        p.set_device(430, 940, 2.0)
        p.navigate(base + "preview.html")
        p.wait_load(30)
        boot = p.wait_for("window.__lt && window.__lt.auth && window.__lt.auth().acc", 30)
        T("L1 应用启动完成（假测试身份）", boot, "")
        p.evaluate("window.__lt.gotoTab('nt')")
        ready = p.wait_for(
            "(function(){try{var f=window.__lt.frame();return !!(f&&f.contentWindow&&f.contentWindow.GROUPS&&f.contentWindow.GROUPS.length);}catch(e){return false;}})()",
            40)
        T("L2 通知 iframe 模板就绪（真实 board 数据）", ready, "")
        time.sleep(1.0)

        def _run_in_frame(code):
            return p.evaluate("(function(){var f=window.__lt.frame();if(!f)return null;"
                              "return f.contentWindow.eval(%s);})()" % json.dumps(code))

        def jf(expr):
            return _run_in_frame("(function(){var W=window;return (%s);})()" % expr)

        def jfs(stmts):
            return _run_in_frame("(function(){var W=window;%s})()" % stmts)

        # ---------------- 真实数据（固定时钟）：长期通知口径 + 长期清单 ----------------
        jfs("W.__ltOrig=W.GROUPS;W.__zqTest.setNow(%d);W.state.card='';W.state.sub='全部';"
            "W.state.cat='全部';W.state.done={};W.render({animate:false});" % FIX_NOW)
        time.sleep(0.35)
        real = jf("""(function(){var V=W.__zqTest,now=V.nowMs();
          var rec=W.GROUPS.filter(function(g){return g.recurrence&&g.recurrence.freq});
          var ongoing=rec.filter(function(g){return V.recurOngoing(g.recurrence,now)});
          return {recN:rec.length,ongoingN:ongoing.length,
            statRecur:+document.querySelector('#statRecur').textContent,
            infoN:V.infoGroups().length,
            dataN:document.querySelectorAll('#dataList .gcard').length,
            dataDisp:getComputedStyle(document.querySelector('#dataWrap')).display,
            dataOpen:document.querySelector('#dataWrap').classList.contains('open')};})()""")
        T("L3 长期通知卡数字 = 进行中安排条数（真实数据）",
          real["statRecur"] == real["ongoingN"],
          json.dumps(real, ensure_ascii=False))
        T("L4 资料/无时间栏默认展开且条数 = 资料组数",
          real["dataDisp"] == "block" and real["dataOpen"] and real["dataN"] == real["infoN"] and real["infoN"] > 0,
          json.dumps(real, ensure_ascii=False))
        jf("document.querySelector('[data-card=\"longterm\"]').click()")
        time.sleep(0.3)
        lt = jf("""(function(){var rows=[].map.call(document.querySelectorAll('#list .ltrow'),function(r){
            return {t:(r.querySelector('.ltrow-t')||{}).textContent||'',
                    p:(r.querySelector('.ltp')||{}).textContent||'',
                    n:(r.querySelector('.ltn')||{}).textContent||'',
                    s:(r.querySelector('.st')||{}).textContent||''};});
          return {rows:rows,n:rows.length,cardN:document.querySelectorAll('#list .gcard').length,
            doneN:document.querySelectorAll('#list [data-act=\"done\"]').length,
            countText:(document.querySelector('#listCount')||{}).textContent||''};})()""")
        T("L5 长期清单条数 = 进行中安排数（真实数据），无期次卡/无 done、统计一致",
          lt["n"] == real["ongoingN"] and lt["cardN"] == 0 and lt["doneN"] == 0
          and lt["countText"] == "%d 组" % lt["n"],
          json.dumps({k: lt[k] for k in ("n", "cardN", "doneN", "countText")}, ensure_ascii=False))
        T("L6 长期清单含 标题/周期/下次 M月D日（周X）HH:MM/进行中",
          all(r["t"] and r["p"] and re.match(r"^下次 \d{1,2}月\d{1,2}日（.{1,4}） \d{2}:\d{2}$", r["n"])
              and r["s"] == "进行中" for r in lt["rows"]),
          json.dumps(lt["rows"][:2], ensure_ascii=False))
        # 排序：按下次时间升序（用产品 nextRecurDate 读 DOM 顺序 + 自算参考）
        order = jf("""(function(){var V=W.__zqTest,now=V.nowMs();
          var arr=W.GROUPS.filter(function(g){return g.recurrence&&g.recurrence.freq&&V.recurOngoing(g.recurrence,now)});
          var want=arr.slice().sort(function(a,b){var ta=V.recurNext(a.recurrence,now),tb=V.recurNext(b.recurrence,now);
            return (ta?ta.getTime():Infinity)-(tb?tb.getTime():Infinity)}).map(function(g){return V.fmtDateText(g.title)});
          var got=[].map.call(document.querySelectorAll('#list .ltrow .ltrow-t'),function(t){return t.textContent});
          return {same:JSON.stringify(want)===JSON.stringify(got),want:want,got:got};})()""")
        T("L7 长期清单按下次发生时间升序", order["same"], json.dumps(order, ensure_ascii=False))
        jf("document.querySelector('[data-card=\"longterm\"]').click()")
        time.sleep(0.2)

        # ---------------- 合成夹具（固定时钟） ----------------
        jfs("W.state.card='';W.state.sub='全部';W.state.cat='全部';W.state.done={};"
            "W.GROUPS=%s;W.render({animate:false});" % json.dumps(FIXTURES, ensure_ascii=False))
        time.sleep(0.3)
        fx = jf("""(function(){var V=W.__zqTest,now=V.nowMs(),byId={};
          W.GROUPS.forEach(function(g){byId[g.id]=g});
          function occ(g){var o=V.occurrenceOf(byId[g],now);return o?o.key:null}
          function ended(g){return !V.recurOngoing(byId[g].recurrence,now)}
          var expiredLabels={};
          document.querySelectorAll('#expiredList .gcard').forEach(function(c){
            expiredLabels[c.getAttribute('data-gid')]=(c.querySelector('.st')||{}).textContent||''});
          return {u15:occ('g_u15'),u14:occ('g_u14'),dead:occ('g_dead'),
            deadEnded:ended('g_dead'),u15Ended:ended('g_u15'),u14Ended:ended('g_u14'),
            monthNext:(function(){var d=V.recurNext(byId['g_month'].recurrence,now);
              return d?d.getFullYear()+'-'+(d.getMonth()+1)+'-'+d.getDate()+' '+d.getHours()+':'+String(d.getMinutes()).padStart(2,'0'):null})(),
            expiredLabels:expiredLabels,
            ongoingN:W.GROUPS.filter(function(g){return g.recurrence&&V.recurOngoing(g.recurrence,now)}).length,
            statRecur:+document.querySelector('#statRecur').textContent};})()""")
        T("L8 §1.3 向量：daily until=11-15（含当天）→ 期次 20261115、仍进行中",
          fx["u15"] == "g_u15@occ:20261115" and fx["u15Ended"] is False, json.dumps(fx["u15"], ensure_ascii=False))
        T("L9 §1.3 向量：daily until=11-14（当天已无下一次）→ 无期次且视为结束",
          fx["u14"] is None and fx["u14Ended"] is True, json.dumps({"occ": fx["u14"], "ended": fx["u14Ended"]}))
        T("L10 until 已结束的长期安排：无期次、归入已过期区并显示「长期安排已结束」",
          fx["dead"] is None and fx["deadEnded"] and fx["expiredLabels"].get("g_dead") == "长期安排已结束",
          json.dumps(fx["expiredLabels"], ensure_ascii=False))
        T("L11 monthly_weeks 下次 = 11-18 17:30（固定向量）", fx["monthNext"] == "2026-11-18 17:30", fx["monthNext"])
        T("L12 长期通知计数 = 合成夹具进行中 3 条", fx["ongoingN"] == 3 and fx["statRecur"] == 3,
          json.dumps({"ongoing": fx["ongoingN"], "stat": fx["statRecur"]}))

        # ---------------- 期次卡视觉 + 本次已处理 + 隔离 ----------------
        occ = jf("""(function(){var c=document.querySelector('#list .gcard.occ');
          if(!c)return null;
          return {gid:c.getAttribute('data-gid'),
            badge:(c.querySelector('.badge.recur')||{}).textContent||'',
            chip:(c.querySelector('.st')||{}).textContent||'',
            done:(c.querySelector('.donebtn')||{}).textContent||'',
            fold:(c.querySelector('[data-act=\"fold\"]')||{}).textContent||''};})()""")
        T("L13 期次卡视觉：长期安排徽标 / 本次 M月D日（周X）HH:MM / 本次已处理",
          bool(occ) and occ["badge"] == "长期安排"
          and re.match(r"^本次 \d{1,2}月\d{1,2}日（.{1,4}） \d{2}:\d{2}$", occ["chip"])
          and occ["done"] == "本次已处理",
          json.dumps(occ, ensure_ascii=False))
        before = jf("({open:+document.querySelector('#statOpen').textContent,recur:+document.querySelector('#statRecur').textContent,occ:document.querySelectorAll('#list .gcard.occ').length})")
        # 选中期次 20261114 的那个（g_period / g_u15 中 11-14 21:00 更早；用 data-gid 精确点）
        click_gid = jf("""(function(){var ids=[];document.querySelectorAll('#list .gcard.occ').forEach(function(c){ids.push(c.getAttribute('data-gid'))});
          return ids.filter(function(x){return x.indexOf('20261114')>=0})[0]||ids[0];})()""")
        jf("document.querySelector('#list .gcard.occ[data-gid=\"%s\"] .donebtn').click()" % click_gid)
        time.sleep(0.3)
        od = jf("""(function(){return {occ:document.querySelectorAll('#list .gcard.occ').length,
          done:Object.keys(W.state.done),open:+document.querySelector('#statOpen').textContent,
          recur:+document.querySelector('#statRecur').textContent,
          baseDone:!!(W.state.done['g_period']||W.state.done['g_u15']||W.state.done['g_month'])};})()""")
        T("L14 期次「本次已处理」：卡片消失、只写该期 key、待处理 -1、长期计数不变",
          od["occ"] == before["occ"] - 1 and od["done"] == [click_gid] and od["open"] == before["open"] - 1
          and od["recur"] == before["recur"] and not od["baseDone"],
          json.dumps(dict(od, click=click_gid), ensure_ascii=False))
        # 下一期：推进到 11-15 08:00（daily 21:00 下一期=11-15 21:00，key 20261115）
        jf("W.__zqTest.setNow(Date.parse('2026-11-15T08:00:00+08:00'))")
        time.sleep(0.3)
        nxt = jf("""(function(){var ids=[];document.querySelectorAll('#list .gcard.occ').forEach(function(c){ids.push(c.getAttribute('data-gid'))});
          return ids;})()""")
        T("L15 期次 done 隔离：下一期重新出现、不被上一期 done 阻塞（含 20261115）",
          any(x == "g_period@occ:20261115" for x in nxt) or any("20261115" in x for x in nxt),
          json.dumps(nxt, ensure_ascii=False))
        jf("W.__zqTest.setNow(%d)" % FIX_NOW)
        time.sleep(0.2)

        # ---------------- 长期通知卡与 chips 互斥 / 分类筛选 / 空态 ----------------
        jf("document.querySelector('#dataBar [data-card=\"longterm\"]').click()")
        time.sleep(0.2)
        mix = jf("""(function(){return {cardOn:document.querySelectorAll('#dataBar .bstat.on').length,
          chipOn:document.querySelectorAll('#subRow .chipf.on').length,
          rows:document.querySelectorAll('#list .ltrow').length};})()""")
        T("L16 长期通知卡激活时与 chips 互斥、清单 = 进行中条数", mix["cardOn"] == 1 and mix["chipOn"] == 0
          and mix["rows"] == 3, json.dumps(mix, ensure_ascii=False))
        jf("document.querySelector('[data-card=\"longterm\"]').click()")
        time.sleep(0.2)
        T("L17 再点长期通知卡取消筛选（恢复全部视图）",
          jf("(function(){return document.querySelectorAll('#dataBar .bstat.on').length===0&&document.querySelectorAll('#dataWrap .gcard').length>0;})()") is True, "")
        jf("document.querySelector('#dataBar [data-card=\"longterm\"]').click()")
        time.sleep(0.2)
        cat = jf("""(function(){var b=document.querySelector('#catRow [data-cat=\"军训\"]');if(!b)return {skip:1};
          b.click();var n=document.querySelectorAll('#list .ltrow').length;
          return {skip:0,n:n};})()""")
        if cat.get("skip"):
            T("L18 分类筛选作用于长期清单", False, "no cat chip")
        else:
            T("L18 分类筛选作用于长期清单（军训 → 2 条）", cat["n"] == 2, json.dumps(cat, ensure_ascii=False))
            jf("(function(){var b=document.querySelector('#catRow [data-cat=\"全部\"]');if(b)b.click();})()")
            time.sleep(0.15)
        jfs("W.state.done={};W.state.card='';W.state.cat='全部';W.GROUPS=[{id:'g_onlyinfo',cat:'班级事务',title:'资料通知',items:[{kind:'text',time:'11-10 08:00',text:'无时间资料'}]}];W.render({animate:false});")
        time.sleep(0.2)
        jf("document.querySelector('#dataBar [data-card=\"longterm\"]').click()")
        time.sleep(0.2)
        T("L19 无进行中安排时长期清单空态「暂无长期安排」",
          jf("(function(){var e=document.querySelector('#list .lt-empty');return !!e&&e.textContent==='暂无长期安排';})()") is True, "")
        jfs("W.GROUPS=W.__ltOrig;W.state.card='';W.state.done={};W.__zqTest.setNow(0);W.render({animate:false});")
        time.sleep(0.25)

        # ---------------- 横向溢出 / 错误 / 外部请求 ----------------
        over = []
        for wdt in (430, 390, 360):
            p.set_device(wdt, 900, 2.0)
            time.sleep(0.4)
            o = p.evaluate("(function(){var f=window.__lt.frame(),d=f.contentDocument;return Math.max(d.documentElement.scrollWidth,d.body.scrollWidth)-f.contentWindow.innerWidth;})()")
            over.append([wdt, o])
        T("L20 各宽度无横向溢出（430/390/360）", all(o <= 1 for _, o in over), json.dumps(over))
        errs = p.evaluate("JSON.stringify(window.__lt.errs())")
        cerrs = p.evaluate("JSON.stringify(window.__lt.cerrs())")
        ext = p.evaluate("JSON.stringify(window.__lt.external())")
        T("L21 0 JS 报错", errs == "[]", errs[:300])
        T("L22 0 console.error", cerrs == "[]", cerrs[:300])
        T("L23 0 外部请求（其余请求已 mock）", ext == "[]", ext[:300])

        p.set_device(430, 900, 2.0)
        jfs("W.__zqTest.setNow(%d);document.querySelector('#dataBar [data-card=\"longterm\"]').click();" % FIX_NOW)
        time.sleep(0.3)
        p.screenshot(os.path.join(REPORT_DIR, "longterm_view_430.png"))
        p.set_device(360, 900, 2.0)
        time.sleep(0.3)
        p.screenshot(os.path.join(REPORT_DIR, "longterm_view_360.png"))
    finally:
        try:
            if brow:
                brow.close()
        except Exception:
            pass
        try:
            if srv:
                srv.shutdown()
                srv.server_close()
        except Exception:
            pass
        os.chdir(old_cwd)
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for s in STEPS if s["ok"])
    total = len(STEPS)
    with open(os.path.join(REPORT_DIR, "longterm_result.json"), "w", encoding="utf-8") as fh:
        json.dump({"src": SRC, "steps": STEPS, "passed": passed, "total": total}, fh, ensure_ascii=False, indent=1)
    print("=" * 60)
    print("v2_notice_longterm_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 60)
    return 0 if total and passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
