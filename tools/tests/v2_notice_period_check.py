# -*- coding: utf-8 -*-
"""v2 专项自检：通知「长期期次 + 5 卡可点筛选 + 资料栏 + 时间显示」（2026-11-14 契约 §1/§2/§3）

对象：
  - `web/tools/index.html`（含 NOTICE_TPL_B64 嵌入模板）
  - `web/tools/notice-board-live-demo.html`（真实 board 数据，取 `var GROUPS=[...]` 做 mock）
做法：本地临时 HTTP + Edge/CDP + 假测试身份（9999 段）+ 全量 fetch mock（含通知板数据），
      进入应用通知 tab，在 iframe 模板内注入固定时钟 `__zqTest.setNow` 后断言。
覆盖：
  S. 静态：demo/嵌入模板含 5 卡/期次/资料栏/时间格式化标记，且 iframe 固定视口架构未变；
  T. 时间显示 §3.4 固定向量（now=2026-11-14 13:31 周六）+ 已带括号不重复 + 倒计时不动；
  W. 期次窗口 §1.3 固定向量（monthly_weeks / until 含当天 / until 已过）；
  F. 5 卡数字口径 §2.4 + 点击筛选/再点取消/激活态/与 chips 互斥；
  D. 列表分区：主列表（含期次卡）→ 资料/无时间栏（默认展开、可折叠、分类生效）→ 已过期区；
  L. 长期通知筛选 = 长期安排清单（周期/下次 M月D日（周X）HH:MM/进行中、无 done）；
  P. 最新发布筛选 = 全部未隐藏通知按发布时间倒序（含已过期）；
  O. 期次卡视觉（长期安排徽标/本次时间胶囊/本次已处理）+ 期次 done 隔离（不影响下一期/长期定义）；
  E. until 结束的长期安排归入已过期区（「长期安排已结束」）；
  X. 430/390/360 无横向溢出、5 卡点按区 ≥40px、0 JS 报错 / 0 console.error / 0 外部请求。
用法：cd web/tools && python tests\\v2_notice_period_check.py
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

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)            # web/tools
WEB = os.path.dirname(ROOT)             # web
sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
import _cdp  # noqa: E402

SRC = os.path.abspath(os.environ.get("V2P_SRC") or os.path.join(ROOT, "index.html"))
DEMO = os.path.join(ROOT, "notice-board-live-demo.html")
REPORT_DIR = os.path.join(HERE, "_v2_notice_reports")
AN_PREFIX = "[[CLASS_NOTICE_V1]]"
BASE_TS = 1762000000000
SID = "9999000005"
NAME = "测试同学"
# 契约固定时钟：2026-11-14 13:31 周六（+08:00）
from datetime import datetime, timedelta, timezone  # noqa: E402

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
  /* 大屏互联 presence 等其它请求：mock 掉，统计为“已拦截”而不是外部请求 */
  window.__dropBlocked++;
  return ok({});
};
try{localStorage.setItem('zq_class_identity',JSON.stringify({token:'mock-token',sid:'__SID__',name:'__NAME__',role:'',badge:'',is_admin:false,ts:Date.now()}));}catch(e){}
})();
</script>
"""

HOOK = r"""
window.__pl={auth:function(){return AUTH;},gotoTab:function(t){gotoTab(t);},
  frame:function(){return NOTICE_FRAME;},errs:function(){return window.__errs||[];},
  cerrs:function(){return window.__cerrs||[];},external:function(){return window.__external||[];},
  dropBlocked:function(){return window.__dropBlocked||0;}};
"""

# 合成夹具（固定时钟 2026-11-14 13:31 周六）：
#   g_until      daily until 2026-11-15 → 期次 11-15 07:30（窗口已开始）
#   g_until_dead daily until 2026-11-12 → 已结束 → 已过期区「长期安排已结束」
#   g_month      monthly_weeks 每月前三周周三 17:30 → 下次 11-18 17:30（窗口未开始，无期次）
#   g_plain      deadline 11-14 18:00 → 主列表 / 待处理
#   g_info       无任何时间锚点 → 资料/无时间栏
#   g_exp        deadline 11-10 18:00 → 已过期
FIXTURES = [
    {"id": "g_until", "cat": "军训", "title": "每日07:30前私发导员请假",
     "aiSummary": "11-10 起每日 07:30 前私发导员请假", "aiPoints": ["每日07:30前"],
     "items": [{"kind": "text", "time": "11-13 10:00", "text": "11-10 起每日 07:30 前私发导员请假"}],
     "recurrence": {"freq": "daily", "time": "07:30", "startAt": "2026-11-10T07:30:00+08:00",
                    "until": "2026-11-15", "label": "每日 07:30"}},
    {"id": "g_until_dead", "cat": "军训", "title": "已结束的每日安排",
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
     "deadlineAction": "交表", "aiSummary": "11-13 前交报名表",
     "items": [{"kind": "text", "time": "11-12 09:00", "text": "11-13 前交报名表到 1202"}]},
    {"id": "g_info", "cat": "班级事务", "title": "2026年学生军训实施方案",
     "aiSummary": "详见方案附件", "items": [{"kind": "text", "time": "11-10 08:00", "text": "方案见附件"}]},
    {"id": "g_exp", "cat": "教务", "title": "过期通知 · 材料提交",
     "deadline": "2026-11-10T18:00:00+08:00", "deadlineAction": "提交",
     "items": [{"kind": "text", "time": "11-09 08:00", "text": "11-10 18:00 前提交材料"}]},
]

# 独立参考实现（不调用产品函数算期望，防「同错同过」）
REF = r"""
function refPending(g){
  if(g.actionable===false)return false;
  if(g.recurrence&&g.recurrence.freq)return false;
  var anchor=!!(g.deadline||g.eventAt||g.signupStart||g.signupEnd||(g.signupWindows&&g.signupWindows.length));
  if(!anchor)return false;
  var now=Date.now();
  var dl=g.deadline?Date.parse(g.deadline):null;
  var ev=g.eventAt?Date.parse(g.eventAt):null;
  if(dl&&now>dl)return false;
  if(ev&&!dl&&now>ev)return false;
  return true;
}
"""


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
    demo_txt = open(DEMO, encoding="utf-8").read()
    src_txt = open(SRC, encoding="utf-8").read()
    m = re.search(r'var NOTICE_TPL_B64="([^"]*)"', src_txt, re.S)
    tpl = base64.b64decode(m.group(1)).decode("utf-8", "replace") if m else ""
    T("S1 demo 模板含 5 张可点数据卡（data-card：pending/24h/7d/longterm/latest）",
      all(('data-card="%s"' % c) in demo_txt for c in ("pending", "24h", "7d", "longterm", "latest")), "")
    T("S2 demo 模板含期次算法/时间格式化/资料栏标记",
      all(k in demo_txt for k in ("function occurrenceOf", "function fmtDateText", "function recurEnded",
                                  'id="dataWrap"', "function longtermListHTML", "function latestGroups")), "")
    T("S3 嵌入模板与 demo 同步（5 卡 + 期次 + 时间格式）",
      bool(tpl) and all(k in tpl for k in ('data-card="latest"', "function occurrenceOf", "function fmtDateText")),
      "tpl=%d" % len(tpl))
    T("S4 嵌入模板未破坏通知 iframe 固定视口方案",
      "function __noticeHeight(){" in tpl and "zq_nt_scroll_v1" in tpl, "")

    tmp = tempfile.mkdtemp(prefix="period_notice_")
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
        boot = p.wait_for("window.__pl && window.__pl.auth && window.__pl.auth().acc", 30)
        T("L1 应用启动完成（假测试身份）", boot, "")
        p.evaluate("window.__pl.gotoTab('nt')")
        ready = p.wait_for(
            "(function(){try{var f=window.__pl.frame();return !!(f&&f.contentWindow&&f.contentWindow.GROUPS&&f.contentWindow.GROUPS.length);}catch(e){return false;}})()",
            40)
        T("L2 通知 iframe 模板就绪（真实 board 数据）", ready, "")
        time.sleep(1.0)

        def _run_in_frame(code):
            """在通知 iframe 的 realm 里 eval（document/W/state 均为 iframe 内），返回结果。"""
            return p.evaluate(
                "(function(){var f=window.__pl.frame();if(!f)return null;"
                "return f.contentWindow.eval(%s);})()" % json.dumps(code))

        def jf(expr):
            return _run_in_frame("(function(){var W=window;return (%s);})()" % expr)

        def jfs(stmts):
            return _run_in_frame("(function(){var W=window;%s})()" % stmts)

        # ---------------- 固定时钟 + 时间显示 §3.4 向量 ----------------
        jfs("W.__plOrig=W.GROUPS; W.__zqTest.setNow(%d);" % FIX_NOW)
        vec = jf("""(function(){var V=W.__zqTest;return [
          V.fmtDateText('11-13'),V.fmtDateText('11-14'),V.fmtDateText('11-15'),V.fmtDateText('11-12'),
          V.fmtDateText('11-08'),V.fmtDateText('11-16'),V.fmtDateText('11-20'),V.fmtDateText('12-01'),
          V.fmtDateText('2026-11-14'),V.fmtDateText('2027-01-03'),
          V.fmtDateText('11月13日（下周五）'),V.fmtDateText('5 天后 截止'),V.fmtDateText('8-9节 10-12点')
        ];})()""")
        expect = ["11月13日（本周五）", "11月14日（今天）", "11月15日（明天）", "11月12日（本周四）",
                  "11月8日（上周日）", "11月16日（下周一）", "11月20日（下周五）", "12月1日（周二）",
                  "11月14日（今天）", "2027年1月3日（周日）",
                  "11月13日（下周五）", "5 天后 截止", "8-9节 10-12点"]
        T("T1 §3.4 时间显示固定向量全部一致", vec == expect, json.dumps(vec, ensure_ascii=False))
        T("T2 已带括号日期不重复加括号 / 倒计时与节次不受影响",
          vec[10] == "11月13日（下周五）" and vec[11] == "5 天后 截止" and vec[12] == "8-9节 10-12点", "")

        # ---------------- 期次窗口 §1.3 固定向量 ----------------
        win = jf("""(function(){var V=W.__zqTest,now=Date.parse('%s');
          var g1={id:'g1',recurrence:{freq:'monthly_weeks',weekday:3,weeks:[1,2,3],time:'17:30',startAt:'2026-11-04T17:30:00+08:00'}};
          var g2={id:'g2',recurrence:{freq:'daily',time:'07:30',startAt:'2026-11-10T07:30:00+08:00',until:'2026-11-15'}};
          var g3={id:'g3',recurrence:{freq:'daily',time:'07:30',startAt:'2026-11-10T07:30:00+08:00',until:'2026-11-14'}};
          function fmt(d){return d?d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')+' '+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0'):null}
          var n1=V.recurNext(g1.recurrence,now),o2=V.occurrenceOf(g2,now),o3=V.occurrenceOf(g3,now);
          return {n1:fmt(n1),o2:o2?{key:o2.key,next:fmt(o2.next)}:null,o3:o3,
                  g3ended:!V.recurOngoing(g3.recurrence,now)};})()""" % FIX_NOW_ISO)
        T("W1 monthly_weeks 下次 = 11-18 17:30（每月前三周周三）", win["n1"] == "2026-11-18 17:30", win["n1"])
        T("W2 daily until=11-15：期次 20261115 窗口已开始",
          bool(win["o2"]) and win["o2"]["key"] == "g2@occ:20261115" and win["o2"]["next"] == "2026-11-15 07:30",
          json.dumps(win["o2"], ensure_ascii=False))
        T("W3 daily until=11-14：无期次（已结束）", win["o3"] is None and win["g3ended"] is True,
          json.dumps(win, ensure_ascii=False))

        # ---------------- 注入合成夹具，固定时钟下验证 5 卡/分区/筛选 ----------------
        jfs("W.state.card='';W.state.sub='全部';W.state.cat='全部';W.state.done={};W.state.fold={};"
            "W.GROUPS=%s;W.render({animate:false});" % json.dumps(FIXTURES, ensure_ascii=False))
        time.sleep(0.3)
        st = jf("""(function(){var q=function(s){return document.querySelector(s)};
          var V=W.__zqTest;
          return {cards:{open:+q('#statOpen').textContent,urgent:+q('#statUrgent').textContent,
                  week:+q('#statWeek').textContent,recur:+q('#statRecur').textContent,
                  latest:q('#statLatest').textContent},
            pendingAll:V.pendingAll().length, infoN:V.infoGroups().length,
            longtermN:V.longtermGroupsNow().length,
            mainN:document.querySelectorAll('#list .gcard').length,
            occN:document.querySelectorAll('#list .gcard.occ').length,
            dataN:document.querySelectorAll('#dataList .gcard').length,
            dataDisp:getComputedStyle(q('#dataWrap')).display, dataOpen:q('#dataWrap').classList.contains('open'),
            expN:document.querySelectorAll('#expiredList .gcard').length,
            expDisp:getComputedStyle(q('#expiredWrap')).display,
            listCount:q('#listCount').textContent};})()""")
        T("F1 待处理 = 普通待处理 + 期次（1 普通 + 2 期次 = 3）", st["cards"]["open"] == 3 and st["pendingAll"] == 3,
          json.dumps(st["cards"], ensure_ascii=False))
        T("F2 24h 截止 / 7 天内计数正确（夹具 3 / 3）",
          st["cards"]["urgent"] == 3 and st["cards"]["week"] == 3, json.dumps(st["cards"], ensure_ascii=False))
        T("F3 长期通知 = 进行中安排条数（g_until + g_month + g_period = 3；已结束不计）", st["cards"]["recur"] == 3,
          st["cards"]["recur"])
        T("F4 最新发布显示相对发布时间（今天 HH:MM）", bool(re.match(r"^(今天|昨天) \d{2}:\d{2}$", st["cards"]["latest"])),
          st["cards"]["latest"])
        T("F5 全部视图分区：主列表 3（普通 + 2 期次）/ 资料 1 / 已过期区 2",
          st["mainN"] == 3 and st["occN"] == 2 and st["dataN"] == 1 and st["expN"] == 2,
          json.dumps({"main": st["mainN"], "occ": st["occN"], "data": st["dataN"], "exp": st["expN"]}, ensure_ascii=False))
        T("F6 资料/无时间栏默认展开且计数 1 条", st["dataDisp"] == "block" and st["dataOpen"] and st["dataN"] == 1,
          json.dumps({"disp": st["dataDisp"], "open": st["dataOpen"]}, ensure_ascii=False))
        T("F7 已过期区默认折叠（标题计数 2 组）",
          st["expDisp"] == "block" and jf("document.querySelector('#expiredWrap').classList.contains('open')") is False
          and jf("document.querySelector('#expiredCount').textContent") == "2 组",
          st["expDisp"])
        T("F8 列表底部统计 = 主列表条目数（3 组）", st["listCount"] == "3 组", st["listCount"])

        # 5 卡点击筛选 / 再点取消 / 激活态
        jf("document.querySelector('[data-card=\"pending\"]').click()")
        time.sleep(0.25)
        c1 = jf("""(function(){var q=function(s){return document.querySelector(s)};
          return {on:q('[data-card=\"pending\"]').classList.contains('on'),
                  mainN:document.querySelectorAll('#list .gcard').length,
                  dataDisp:getComputedStyle(q('#dataWrap')).display,
                  expDisp:getComputedStyle(q('#expiredWrap')).display,
                  leak:W.__zqTest.pendingAll().length!==document.querySelectorAll('#list .gcard').length};})()""")
        T("F9 点「待处理」卡：仅待处理主列表、资料栏隐藏、已过期区保留折叠",
          c1["on"] and c1["mainN"] == 3 and c1["dataDisp"] == "none" and c1["expDisp"] == "block" and not c1["leak"],
          json.dumps(c1, ensure_ascii=False))
        jf("document.querySelector('[data-card=\"pending\"]').click()")
        time.sleep(0.2)
        c2 = jf("""(function(){var q=function(s){return document.querySelector(s)};
          return {on:q('[data-card=\"pending\"]').classList.contains('on'),mainN:document.querySelectorAll('#list .gcard').length,
                  dataDisp:getComputedStyle(q('#dataWrap')).display};})()""")
        T("F10 再点一次取消筛选，恢复全部视图", (not c2["on"]) and c2["mainN"] == 3 and c2["dataDisp"] == "block",
          json.dumps(c2, ensure_ascii=False))

        for card, lim, want in (("24h", 24 * 3600 * 1000, 3), ("7d", 7 * 86400000, 3)):
            jfs("W.state.card='';W.render({animate:false});document.querySelector('[data-card=\"%s\"]').click();" % card)
            time.sleep(0.2)
            cc = jf("""(function(){var V=W.__zqTest,now=V.nowMs(),ids=[];
              document.querySelectorAll('#list .gcard').forEach(function(c){ids.push(c.getAttribute('data-gid'))});
              var bad=[];ids.forEach(function(id){
                var g=null;V.pendingAll(now).forEach(function(x){if(x.id===id)g=x});
                if(!g){bad.push('missing:'+id);return}
                var t=V.primaryWhenTs(g,now);
                if(!(t&&t>=now&&(t-now)<=%d))bad.push(id);});
              return {ids:ids,bad:bad,on:document.querySelector('[data-card=\"%s\"]').classList.contains('on')};})()""" % (lim, card))
            T("F11 %s 卡筛选：列表内全部剩余 ≤%s 且激活" % (card, "24h" if card == "24h" else "7 天"),
              cc["on"] and cc["bad"] == [] and len(cc["ids"]) == want, json.dumps(cc, ensure_ascii=False))
        jfs("W.state.card='';W.render({animate:false});")

        # 长期通知筛选 = 长期安排清单
        jf("document.querySelector('[data-card=\"longterm\"]').click()")
        time.sleep(0.25)
        lt = jf("""(function(){var rows=[].map.call(document.querySelectorAll('#list .ltrow'),function(r){
            return {t:(r.querySelector('.ltrow-t')||{}).textContent||'',
                    p:(r.querySelector('.ltp')||{}).textContent||'',
                    n:(r.querySelector('.ltn')||{}).textContent||'',
                    s:(r.querySelector('.st')||{}).textContent||''};});
          return {rows:rows,listCount:document.querySelector('#listCount').textContent,
                  occN:document.querySelectorAll('#list .gcard').length,
                  doneN:document.querySelectorAll('#list [data-act=\"done\"]').length,
                  dataDisp:getComputedStyle(document.querySelector('#dataWrap')).display};})()""")
        T("L1 长期通知筛选：主区=长期安排清单（3 条，无期次卡/无 done），资料栏隐藏",
          len(lt["rows"]) == 3 and lt["occN"] == 0 and lt["doneN"] == 0 and lt["dataDisp"] == "none",
          json.dumps(lt, ensure_ascii=False))
        T("L2 长期清单含 标题 / 周期 label / 下次 M月D日（周X）HH:MM / 进行中",
          all(r["t"] and r["p"] and re.match(r"^下次 \d{1,2}月\d{1,2}日（.+） \d{2}:\d{2}$", r["n"]) and r["s"] == "进行中"
              for r in lt["rows"]),
          json.dumps(lt["rows"], ensure_ascii=False))
        T("L3 长期清单底部统计 = 长期条数（3 组）", lt["listCount"] == "3 组", lt["listCount"])
        jf("document.querySelector('[data-card=\"longterm\"]').click()")
        time.sleep(0.2)

        # 最新发布筛选：按发布时间倒序、含已过期
        jf("document.querySelector('[data-card=\"latest\"]').click()")
        time.sleep(0.25)
        la = jf("""(function(){var V=W.__zqTest,ids=[];
          document.querySelectorAll('#list .gcard').forEach(function(c){ids.push(c.getAttribute('data-gid'))});
          var ts=ids.map(function(id){var g=null;W.GROUPS.forEach(function(x){if(x.id===id)g=x});return g?V.pubTsOf(g):0});
          var sorted=ts.slice().sort(function(a,b){return b-a});
          return {n:ids.length,sorted:ts.join(',')===sorted.join(','),exp:document.querySelectorAll('#list .gcard.expired').length,
                  dataDisp:getComputedStyle(document.querySelector('#dataWrap')).display};})()""")
        T("L4 最新发布筛选：全部未隐藏通知（7 条）按发布时间倒序、含已过期卡",
          la["n"] == len(FIXTURES) and la["sorted"] and la["exp"] == 2 and la["dataDisp"] == "none",
          json.dumps(la, ensure_ascii=False))
        jf("document.querySelector('[data-card=\"latest\"]').click()")
        time.sleep(0.2)

        # 资料栏折叠/展开 + 分类筛选
        jf("document.querySelector('#dataWrap .lt-hd').click()")
        time.sleep(0.2)
        T("D1 资料/无时间栏可折叠", jf("document.querySelector('#dataWrap').classList.contains('open')") is False, "")
        jf("document.querySelector('#dataWrap .lt-hd').click()")
        time.sleep(0.2)
        cat_ok = jf("""(function(){var b=document.querySelector('#catRow [data-cat=\"班级事务\"]');if(!b)return {skip:1};b.click();
          var n=document.querySelectorAll('#dataList .gcard').length;
          var all=g=>1;return {skip:0,n:n,disp:getComputedStyle(document.querySelector('#dataWrap')).display};})()""")
        if cat_ok.get("skip"):
            T("D2 分类筛选作用于资料栏", False, "no cat chip")
        else:
            T("D2 分类筛选作用于资料栏（班级事务 → 1 条）", cat_ok["n"] == 1 and cat_ok["disp"] == "block",
              json.dumps(cat_ok, ensure_ascii=False))
            jf("(function(){var b=document.querySelector('#catRow [data-cat=\"全部\"]');if(b)b.click();})()")
            time.sleep(0.2)

        # 期次卡视觉 + done 隔离（不影响下一期/长期定义）
        occ = jf("""(function(){var q=function(s){return document.querySelector(s)};
          var c=q('#list .gcard.occ');
          if(!c)return null;
          return {gid:c.getAttribute('data-gid'),chip:(c.querySelector('.st')||{}).textContent||'',
                  badge:(c.querySelector('.badge.recur')||{}).textContent||'',
                  done:(c.querySelector('.donebtn')||{}).textContent||'',
                  title:(c.querySelector('.gtitle')||{}).textContent||''};})()""")
        T("O1 期次卡视觉：长期安排徽标 + 本次 M月D日（周X）HH:MM + 本次已处理",
          bool(occ) and occ["badge"] == "长期安排" and re.match(r"^本次 \d{1,2}月\d{1,2}日（.+） \d{2}:\d{2}$", occ["chip"])
          and occ["done"] == "本次已处理" and occ["gid"] == "g_period@occ:20261114",
          json.dumps(occ, ensure_ascii=False))
        before = jf("({open:+document.querySelector('#statOpen').textContent,recur:+document.querySelector('#statRecur').textContent})")
        jf("document.querySelector('#list .gcard.occ .donebtn').click()")
        time.sleep(0.25)
        od = jf("""(function(){return {occN:document.querySelectorAll('#list .gcard.occ').length,
            done:Object.keys(W.state.done),statOpen:+document.querySelector('#statOpen').textContent,
            baseDone:!!W.state.done['g_period'],
            longterm:+document.querySelector('#statRecur').textContent};})()""")
        # 嵌入模式下模板 toast 由父页 noticeToastBridge 承接：断言父页 toast 文案
        time.sleep(0.2)
        parent_toast = p.evaluate("(function(){var t=document.querySelector('#toast');return t?t.textContent:''})()")
        T("O2 期次「本次已处理」：该期卡片消失、写 gid@occ done、待处理 -1、长期定义不受影响",
          od["occN"] == 1 and od["done"] == ["g_period@occ:20261114"] and od["statOpen"] == before["open"] - 1
          and not od["baseDone"] and od["longterm"] == before["recur"] and parent_toast == "本期已处理",
          json.dumps(dict(od, parentToast=parent_toast), ensure_ascii=False))
        # 下一期：推进到对应窗口，旧 done 不阻塞（g_period 无 until；daily 21:00 → 11-15 21:00）
        jf("W.__zqTest.setNow(Date.parse('2026-11-15T08:00:00+08:00'))")
        time.sleep(0.25)
        nxt = jf("""(function(){var c=document.querySelector('#list .gcard.occ');
          return {gid:c?c.getAttribute('data-gid'):null,chip:c?(c.querySelector('.st')||{}).textContent:null};})()""")
        T("O3 期次 done 隔离：下一期（20261115）重新出现、不被上一期 done 阻塞",
          nxt["gid"] == "g_period@occ:20261115", json.dumps(nxt, ensure_ascii=False))
        jf("W.__zqTest.setNow(%d)" % FIX_NOW)
        time.sleep(0.15)

        # until 结束的长期安排 → 已过期区「长期安排已结束」
        jfs("W.state.done={};W.render({animate:false});")
        time.sleep(0.2)
        ended = jf("""(function(){var out=null;
          document.querySelectorAll('#expiredList .gcard').forEach(function(c){
            if(c.getAttribute('data-gid')==='g_until_dead')out={label:(c.querySelector('.st')||{}).textContent||''};
          });
          return out;})()""")
        T("E1 until 结束的长期安排归入已过期区并显示「长期安排已结束」", bool(ended) and ended["label"] == "长期安排已结束",
          json.dumps(ended, ensure_ascii=False))
        T("E2 已结束的长期安排不产生期次卡", jf("!!W.__zqTest.occurrenceOf(W.GROUPS.filter(function(g){return g.id==='g_until_dead'})[0],W.__zqTest.nowMs())") is False, "")

        # 空态：无长期安排
        jfs("W.GROUPS=[{id:'g_onlyinfo',cat:'班级事务',title:'资料通知',items:[{kind:'text',time:'11-10 08:00',text:'无时间资料'}]}];W.state.done={};W.state.card='';W.render({animate:false});")
        time.sleep(0.2)
        jf("document.querySelector('[data-card=\"longterm\"]').click()")
        time.sleep(0.2)
        T("L5 长期通知筛选空态：暂无长期安排",
          jf("!!document.querySelector('#list .lt-empty')&&document.querySelector('#list .lt-empty').textContent==='暂无长期安排'") is True, "")

        # ---------------- 时间格式在 DOM 的落地（title/摘要/状态胶囊/原文条目） ----------------
        jfs("W.state.card='';W.state.sub='全部';W.state.cat='全部';W.state.done={};W.GROUPS=%s;W.render({animate:false});"
            % json.dumps(FIXTURES, ensure_ascii=False))
        time.sleep(0.2)
        dom = jf("""(function(){var c=null,exp=null;
          document.querySelectorAll('#list .gcard').forEach(function(x){if(x.getAttribute('data-gid')==='g_plain')c=x;});
          document.querySelectorAll('#expiredList .gcard').forEach(function(x){if(x.getAttribute('data-gid')==='g_exp')exp=x;});
          if(!c)return null;
          return {title:(c.querySelector('.gtitle')||{}).textContent||'',
                  chip:(c.querySelector('.st')||{}).textContent||'',
                  sum:(c.querySelector('.aibrief-sum')||{}).textContent||'',
                  expChip:exp?(exp.querySelector('.st')||{}).textContent:''};})()""")
        T("T3 title/摘要日期统一为 M月D日（相对周）；24h 内倒计时文案保持倒计时",
          bool(dom) and "11月13日（本周五）" in dom["title"] and "11月13日（本周五）" in dom["sum"]
          and dom["chip"] == "5 小时后 交表",
          json.dumps(dom, ensure_ascii=False))
        T("T4 已过期卡的绝对日期状态文案已格式化（11-10 → 11月10日（本周二））",
          bool(dom) and "11月10日（本周二） 18:00 提交" in dom["expChip"], dom["expChip"] if dom else "")
        # 原文条目（无 AI 摘要的内联原文）同样格式化
        jfs("W.GROUPS=[{id:'g_txt',cat:'教务',title:'交材料',items:[{kind:'text',time:'11-12 09:00',text:'11-13 前交材料'}]}];"
            "W.state.card='';W.state.sub='全部';W.state.cat='全部';W.state.done={};W.render({animate:false});")
        time.sleep(0.2)
        item_txt = jf("(function(){var e=document.querySelector('#dataList .gi-body');return e?e.textContent:''})()")
        T("T5 原文条目的日期同格式（11-13 → 11月13日（本周五））", "11月13日（本周五）" in (item_txt or ""),
          (item_txt or "")[:80])

        # chips 与 5 卡互斥 + 全部 chip
        jf("document.querySelector('#subRow [data-sub=\"todo\"]').click()")
        time.sleep(0.2)
        mix = jf("""(function(){return {cardOn:document.querySelectorAll('#dataBar .bstat.on').length,
            chipOn:document.querySelectorAll('#subRow .chipf.on').length,
            dataDisp:getComputedStyle(document.querySelector('#dataWrap')).display};})()""")
        T("M1 待处理 chip：与 5 卡互斥（卡无激活）、资料栏隐藏", mix["cardOn"] == 0 and mix["chipOn"] == 1 and mix["dataDisp"] == "none",
          json.dumps(mix, ensure_ascii=False))
        jf("document.querySelector('[data-card=\"pending\"]').click()")
        time.sleep(0.2)
        mix2 = jf("""(function(){return {cardOn:document.querySelectorAll('#dataBar .bstat.on').length,
            allChipOn:document.querySelectorAll('#subRow [data-sub=\"全部\"].on').length};})()""")
        T("M2 点 5 卡后 chips 全不选中（互斥）", mix2["cardOn"] == 1 and mix2["allChipOn"] == 0,
          json.dumps(mix2, ensure_ascii=False))
        jf("document.querySelector('#subRow [data-sub=\"全部\"]').click()")
        time.sleep(0.15)

        # ---------------- 恢复真实数据：真实 board 数据回归 ----------------
        jfs("W.GROUPS=W.__plOrig;W.state.card='';W.state.sub='全部';W.state.cat='全部';W.state.done={};W.state.fold={};"
            "W.__zqTest.setNow(%d);W.render({animate:false});" % FIX_NOW)
        time.sleep(0.35)
        real = jf("""(function(){var V=W.__zqTest,q=function(s){return document.querySelector(s)};
          var now=V.nowMs();
          return {groups:W.GROUPS.length,mainN:document.querySelectorAll('#list .gcard').length,
            dataN:document.querySelectorAll('#dataList .gcard').length,
            recurN:W.GROUPS.filter(function(g){return g.recurrence&&g.recurrence.freq}).length,
            longtermN:V.longtermGroupsNow(now).length,
            occ:[].map.call(document.querySelectorAll('#list .gcard.occ'),function(c){return c.getAttribute('data-gid')}),
            occExpect:V.occurrences(now).map(function(g){return g.id}),
            statOpen:+q('#statOpen').textContent,statRecur:+q('#statRecur').textContent,
            statLatest:q('#statLatest').textContent,
            titleHasFmt:[].some.call(document.querySelectorAll('#list .gcard .gtitle'),function(t){return /\d{1,2}月\d{1,2}日（/.test(t.textContent||'')})};})()""")
        T("R1 真实 board 数据：全部组渲染、主列表与资料栏非空",
          real["groups"] == len(GROUPS) and real["mainN"] > 0 and real["dataN"] > 0,
          json.dumps({k: real[k] for k in ("groups", "mainN", "dataN")}, ensure_ascii=False))
        T("R2 真实数据长期通知计数与筛选清单一致；期次卡与期次算法结果一致",
          real["longtermN"] == real["recurN"] and real["statRecur"] == real["longtermN"]
          and real["occ"] == real["occExpect"],
          json.dumps({"recurN": real["recurN"], "longtermN": real["longtermN"], "occ": real["occ"]}, ensure_ascii=False))
        T("R3 真实数据待处理/最新发布卡有值且标题已格式化",
          real["statOpen"] > 0 and real["statLatest"] not in ("", "—") and real["titleHasFmt"],
          json.dumps({k: real[k] for k in ("statOpen", "statLatest", "titleHasFmt")}, ensure_ascii=False))

        # 既有通知交互不回退：折叠 / 原始消息按钮 / 普通 done
        foldok = jf("""(function(){var before=document.querySelectorAll('#list .gcard.folded').length;
          var b=document.querySelector('#list .gcard [data-act=\"fold\"]');
          if(!b)return {skip:1};b.click();
          var after=document.querySelectorAll('#list .gcard.folded').length;
          return {skip:0,before:before,after:after};})()""")
        if foldok.get("skip"):
            T("R4 卡片折叠交互不回退", False, "no fold button")
        else:
            T("R4 卡片折叠/展开交互不回退", foldok["after"] != foldok["before"], json.dumps(foldok, ensure_ascii=False))
        orig = jf("(function(){return {btns:document.querySelectorAll('#list [data-act=\"original\"]').length,parent:!!window.parent};})()")
        T("R5 「原始消息」入口保留（嵌入模式由父页弹层承接）", orig["btns"] > 0 and orig["parent"], json.dumps(orig, ensure_ascii=False))

        # ---------------- 响应式：430/390/360 无横向溢出 + 点按区 ----------------
        over = []
        for wdt in (430, 390, 360):
            p.set_device(wdt, 900, 2.0)
            time.sleep(0.4)
            o = p.evaluate("(function(){var f=window.__pl.frame(),d=f.contentDocument;return Math.max(d.documentElement.scrollWidth,d.body.scrollWidth)-f.contentWindow.innerWidth;})()")
            over.append([wdt, o])
        T("X1 各宽度无横向溢出（430/390/360）", all(o <= 1 for _, o in over), json.dumps(over))
        p.set_device(430, 900, 2.0)
        time.sleep(0.3)
        tap = jf("""(function(){var out=[];document.querySelectorAll('#dataBar .bstat').forEach(function(b){
            var r=b.getBoundingClientRect();out.push([Math.round(r.width),Math.round(r.height)]);});return out;})()""")
        T("X2 5 张数据卡点按区 ≥40px 高、宽度 >0",
          len(tap) == 5 and all(h >= 40 and w > 0 for w, h in tap), json.dumps(tap))

        # 桌面宽屏：5 卡同一行、无横向溢出（§2.1 允许桌面等宽 5 列）
        p.set_device(1280, 900, 1.0)
        time.sleep(0.4)
        desk = p.evaluate("""(function(){var f=window.__pl.frame(),d=f.contentDocument;
          var tops=[].map.call(d.querySelectorAll('#dataBar .bstat'),function(b){return Math.round(b.getBoundingClientRect().top)});
          var sameRow=tops.every(function(t){return Math.abs(t-tops[0])<=1});
          var over=Math.max(d.documentElement.scrollWidth,d.body.scrollWidth)-f.contentWindow.innerWidth;
          return {sameRow:sameRow,tops:tops,over:over};})()""")
        T("X2b 桌面宽屏 5 卡同一行且无横向溢出", desk["sameRow"] and desk["over"] <= 1,
          json.dumps(desk, ensure_ascii=False))
        p.set_device(430, 900, 2.0)
        time.sleep(0.2)

        errs = p.evaluate("JSON.stringify(window.__pl.errs())")
        cerrs = p.evaluate("JSON.stringify(window.__pl.cerrs())")
        ext = p.evaluate("JSON.stringify(window.__pl.external())")
        T("X3 0 JS 报错", errs == "[]", errs[:300])
        T("X4 0 console.error", cerrs == "[]", cerrs[:300])
        T("X5 0 外部请求（其余请求已 mock）", ext == "[]", ext[:300])

        jfs("W.__zqTest.setNow(0);")
        p.screenshot(os.path.join(REPORT_DIR, "period_default_430.png"))
        jfs("W.__zqTest.setNow(%d);document.querySelector('[data-card=\"longterm\"]').click();" % FIX_NOW)
        time.sleep(0.3)
        p.screenshot(os.path.join(REPORT_DIR, "period_longterm_430.png"))
        jfs("document.querySelector('[data-card=\"longterm\"]').click();document.querySelector('[data-card=\"latest\"]').click();")
        time.sleep(0.3)
        p.screenshot(os.path.join(REPORT_DIR, "period_latest_430.png"))
        jfs("document.querySelector('[data-card=\"latest\"]').click();document.querySelector('[data-card=\"pending\"]').click();")
        time.sleep(0.3)
        p.screenshot(os.path.join(REPORT_DIR, "period_pending_430.png"))
        p.set_device(360, 900, 2.0)
        time.sleep(0.4)
        jfs("document.querySelector('[data-card=\"pending\"]').click();")
        time.sleep(0.2)
        p.screenshot(os.path.join(REPORT_DIR, "period_default_360.png"))
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
    with open(os.path.join(REPORT_DIR, "period_result.json"), "w", encoding="utf-8") as fh:
        json.dump({"src": SRC, "demo": DEMO, "steps": STEPS, "passed": passed, "total": total}, fh,
                  ensure_ascii=False, indent=1)
    print("=" * 60)
    print("v2_notice_period_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 60)
    return 0 if total and passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
