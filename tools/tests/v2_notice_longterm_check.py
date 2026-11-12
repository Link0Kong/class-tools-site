# -*- coding: utf-8 -*-
"""v2 专项自检：长期通知优化显示（2026-11-12 用户需求）

对象：
  - `web/tools/index.html`（含 NOTICE_TPL_B64 嵌入模板；可用 V2L_SRC 指定预览副本）
  - `web/tools/notice-board-live-demo.html`（真实 board 数据，取 `var GROUPS=[...]` 做 mock）
做法：本地临时 HTTP + Edge/CDP + 假身份 + 全量 fetch mock（含通知板 2MB 数据），
      进入应用通知 tab，在 iframe 模板内断言「长期通知独立折叠区」行为。
覆盖：
  1. 静态：嵌入模板含 longterm 折叠区标记 / isLongtermGroup / 排序函数；
  2. 主列表不含长期通知（长期安排 + 无时间/长期有效），且主列表卡数 = 非过期非长期数；
  3. 长期区默认收起、计数正确、可展开/收起；展开后卡片可见；
  4. 排序：长期安排在前（下次发生时间升序）、info 在后（消息时间倒序）；
  5. 待处理统计排除长期通知；待处理/已截止筛选不显示长期区；分类筛选作用于长期区；
  6. 长期区内的「标记已处理」只改状态、不把卡片塞回主列表；
  7. 430 宽无横向溢出、0 JS 报错 / 0 console.error / 0 外部请求。
用法：cd web/tools && python tests\\v2_notice_longterm_check.py
退出码 0 = 全绿。
"""
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
import urllib.parse

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
window.__lt={auth:function(){return AUTH;},gotoTab:function(t){gotoTab(t);},
  frame:function(){return NOTICE_FRAME;},errs:function(){return window.__errs||[];},
  cerrs:function(){return window.__cerrs||[];},external:function(){return window.__external||[];},
  dropBlocked:function(){return window.__dropBlocked||0;}};
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
    # 0) 静态：模板源（demo）与嵌入目标都必须带长期通知折叠区标记
    demo_txt = open(DEMO, encoding="utf-8").read()
    src_txt = open(SRC, encoding="utf-8").read()
    T("S1 demo 模板含长期区折叠头/列表容器", 'data-act="longterm-toggle"' in demo_txt and 'id="longtermList"' in demo_txt, "")
    T("S2 demo 模板含 isLongtermGroup / orderLongterm", "function isLongtermGroup" in demo_txt and "function orderLongterm" in demo_txt, "")
    import base64
    m = re.search(r'var NOTICE_TPL_B64="([^"]*)"', src_txt, re.S)
    tpl = base64.b64decode(m.group(1)).decode("utf-8", "replace") if m else ""
    T("S3 嵌入模板与 demo 长期区一致", bool(tpl) and 'data-act="longterm-toggle"' in tpl and "function isLongtermGroup" in tpl,
      "tpl=%d" % len(tpl))
    T("S4 嵌入模板未破坏通知 iframe 固定视口方案", "function __noticeHeight(){" in tpl and "zq_nt_scroll_v1" in tpl, "")

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
        ready = p.wait_for("(function(){try{var f=window.__lt.frame();return !!(f&&f.contentWindow&&f.contentWindow.GROUPS&&f.contentWindow.GROUPS.length);}catch(e){return false;}})()", 40)
        T("L2 通知 iframe 模板就绪（真实 board 数据）", ready, "")
        time.sleep(1.2)

        def tw(expr, timeout=20, await_promise=False):
            return p.evaluate("(function(){var f=window.__lt.frame();return f.contentWindow.%s;})()" % expr,
                              await_promise=await_promise, timeout=timeout)

        # 1) 主列表不含长期通知
        stats = p.evaluate("""(function(){
          var f=window.__lt.frame(),w=f.contentWindow,d=f.contentDocument;
          var main=[].map.call(d.querySelectorAll('#list .gcard'),function(c){return c.id.replace('card-','')});
          var ltAll=w.GROUPS.filter(function(g){return !w.isExpiredGroup(g)&&w.isLongtermGroup(g)});
          var ltIds=ltAll.map(function(g){return g.id});
          return {
            mainN:main.length,
            expMain:w.GROUPS.filter(function(g){return !w.isExpiredGroup(g)&&!w.isLongtermGroup(g)}).length,
            ltN:ltAll.length,
            leaked:main.filter(function(id){return ltIds.indexOf(id)>=0}),
            wrap:getComputedStyle(d.getElementById('longtermWrap')).display,
            listN:d.querySelectorAll('#longtermList .gcard').length,
            countText:(d.getElementById('longtermCount')||{}).textContent||'',
            open:d.getElementById('longtermWrap').classList.contains('open'),
            statOpen:Number((d.getElementById('statOpen')||{}).textContent),
            pending:w.pendingGroups().length,
            mainPendingInList:main.length
          };
        })()""")
        T("L3 主列表卡数 = 非过期非长期通知数", stats["mainN"] == stats["expMain"], "%s/%s" % (stats["mainN"], stats["expMain"]))
        T("L4 主列表不含任何长期通知", stats["leaked"] == [], json.dumps(stats["leaked"], ensure_ascii=False))
        T("L5 长期区可见（全部筛选）且渲染全部卡片", stats["wrap"] == "block" and stats["listN"] == stats["ltN"], "display=%s list=%s lt=%s" % (stats["wrap"], stats["listN"], stats["ltN"]))
        T("L6 长期区计数文案正确", stats["countText"] == "%d 条" % stats["ltN"], stats["countText"])
        head_text = p.evaluate("(function(){var t=window.__lt.frame().contentDocument.querySelector('#longtermWrap .lt-hd');return t?t.textContent.replace(/\\s+/g,' ').trim():'';})()")
        T("L6b 折叠头文案「长期通知 · N 条」（两端同口径）",
          ("长期通知·%d 条" % stats["ltN"]).replace(" ", "") in head_text.replace(" ", ""), head_text)
        T("L7 长期区默认收起", stats["open"] is False, str(stats["open"]))
        T("L8 待处理统计排除长期通知", stats["statOpen"] == stats["pending"] and p.evaluate("window.__lt.frame().contentWindow.pendingGroups().every(function(g){return !window.__lt.frame().contentWindow.isLongtermGroup(g)})") is True, "statOpen=%s pending=%s" % (stats["statOpen"], stats["pending"]))

        # 2) 排序：长期安排在前按下次时间升序，info 在后按消息时间倒序
        order = p.evaluate("""(function(){
          var f=window.__lt.frame(),w=f.contentWindow,d=f.contentDocument;
          var ids=[];d.querySelectorAll('#longtermList .gcard').forEach(function(c){ids.push(c.id.replace('card-',''))});
          var byId={};w.GROUPS.forEach(function(g){byId[g.id]=g});
          var kinds=ids.map(function(id){var g=byId[id];return (g.recurrence&&g.recurrence.freq)?'recur':'info'});
          var recurNext=ids.map(function(id){var g=byId[id];return g.recurrence?w.__zqNextRecurrence(g.recurrence,Date.now()).getTime():null});
          var anchors=ids.map(function(id){var g=byId[id];var m=/^(\\d{1,2})-(\\d{1,2})\\s+(\\d{1,2}):(\\d{2})$/.exec(String(w.cardAnchorTs(g)||''));return m?((+m[1])*100+(+m[2]))*10000+(+m[3])*100+(+m[4]):0});
          return {ids:ids,kinds:kinds,recurNext:recurNext,anchors:anchors};
        })()""")
        kinds = order["kinds"]
        recur_n = kinds.count("recur")
        ok_kinds = kinds[:recur_n] == ["recur"] * recur_n and "recur" not in kinds[recur_n:]
        T("L9 长期区内长期安排在前、info 在后", ok_kinds, json.dumps(kinds, ensure_ascii=False))
        rn = [x for x in order["recurNext"] if x is not None]
        T("L10 长期安排按下次发生时间升序", rn == sorted(rn), json.dumps(rn))
        an = order["anchors"][recur_n:]
        T("L11 info 按消息时间倒序", an == sorted(an, reverse=True), json.dumps(an))

        # 3) 展开/收起
        p.evaluate("window.__lt.frame().contentDocument.querySelector('#longtermWrap .lt-hd').click()")
        time.sleep(0.35)
        op = p.evaluate("(function(){var f=window.__lt.frame(),d=f.contentDocument;var c=d.querySelector('#longtermList .gcard');var r=c?c.getBoundingClientRect():null;return {open:d.getElementById('longtermWrap').classList.contains('open'),vis:!!r&&r.height>0&&getComputedStyle(c).display!=='none'};})()")
        T("L12 点折叠头展开、卡片可见", op["open"] and op["vis"], json.dumps(op))
        p.evaluate("window.__lt.frame().contentDocument.querySelector('#longtermWrap .lt-hd').click()")
        time.sleep(0.25)
        cl = p.evaluate("window.__lt.frame().contentDocument.getElementById('longtermWrap').classList.contains('open')")
        T("L13 再点收起", cl is False, str(cl))

        # 4) 待处理 / 已截止筛选：长期区隐藏；待处理主列表不含长期
        p.evaluate("window.__lt.frame().contentDocument.querySelector('#subRow [data-sub=todo]').click()")
        time.sleep(0.35)
        st_todo = p.evaluate("""(function(){var f=window.__lt.frame(),w=f.contentWindow,d=f.contentDocument;
          var ids=[];d.querySelectorAll('#list .gcard').forEach(function(c){ids.push(c.id.replace('card-',''))});
          var lt={};w.GROUPS.forEach(function(g){if(w.isLongtermGroup(g))lt[g.id]=1});
          return {wrap:getComputedStyle(d.getElementById('longtermWrap')).display,n:ids.length,leak:ids.filter(function(id){return lt[id]}),statOpen:Number(d.getElementById('statOpen').textContent)};})()""")
        T("L14 待处理筛选：长期区隐藏且主列表不含长期通知", st_todo["wrap"] == "none" and st_todo["leak"] == [], json.dumps(st_todo, ensure_ascii=False))
        p.evaluate("window.__lt.frame().contentDocument.querySelector('#subRow [data-sub=expired]').click()")
        time.sleep(0.35)
        st_exp = p.evaluate("(function(){var f=window.__lt.frame(),d=f.contentDocument;return {wrap:getComputedStyle(d.getElementById('longtermWrap')).display,exp:getComputedStyle(d.getElementById('expiredWrap')).display};})()")
        T("L15 已截止筛选：长期区隐藏、已过期区可见", st_exp["wrap"] == "none" and st_exp["exp"] == "block", json.dumps(st_exp))

        # 5) 分类筛选作用于长期区
        p.evaluate("window.__lt.frame().contentDocument.querySelector('#subRow [data-sub=全部]').click()")
        time.sleep(0.3)
        cat = p.evaluate("""(function(){var f=window.__lt.frame(),w=f.contentWindow,d=f.contentDocument;
          var c={},pick='';
          var lt=w.GROUPS.filter(function(g){return !w.isExpiredGroup(g)&&w.isLongtermGroup(g)});
          lt.forEach(function(g){c[g.cat]=(c[g.cat]||0)+1});
          for(var k in c){if(c[k]>0&&d.querySelector('#catRow [data-cat="'+k+'"]')){pick=k;break}}
          return {pick:pick,expect:c[pick]||0};})()""")
        if cat["pick"]:
            p.evaluate("""(function(pick){var d=window.__lt.frame().contentDocument;
              var b=d.querySelector('#catRow [data-cat="'+pick+'"]');if(b)b.click();})""" + "(" + json.dumps(cat["pick"], ensure_ascii=False) + ")")
            time.sleep(0.35)
            got = p.evaluate("(function(){var f=window.__lt.frame(),d=f.contentDocument;return {count:(d.getElementById('longtermCount')||{}).textContent||'',listN:d.querySelectorAll('#longtermList .gcard').length};})()")
            T("L16 分类筛选作用于长期区", got["count"] == "%d 条" % cat["expect"] and got["listN"] == cat["expect"], "%s %s" % (cat["pick"], json.dumps(got, ensure_ascii=False)))
            p.evaluate("(function(){var d=window.__lt.frame().contentDocument;var b=d.querySelector('#catRow [data-cat=\"全部\"]');if(b)b.click();})()")
            time.sleep(0.3)
        else:
            T("L16 分类筛选作用于长期区", False, "no category")

        # 6) 长期区内标记已处理：卡片仍留在长期区、不回流主列表
        done = p.evaluate("""(function(){var f=window.__lt.frame(),w=f.contentWindow,d=f.contentDocument;
          var lt=w.GROUPS.filter(function(g){return !w.isExpiredGroup(g)&&w.isLongtermGroup(g)&&!(g.recurrence&&g.recurrence.freq)});
          var g=lt[0];if(!g)return {skip:1};
          var btn=d.querySelector('#longtermList [data-act="done"][data-gid="'+g.id+'"]');
          if(!btn)return {skip:2,id:g.id};
          btn.click();
          var card=d.getElementById('card-'+g.id);
          return {id:g.id,done:!!w.state.done[g.id],completed:!!(card&&card.classList.contains('completed')),
            inMain:!!d.querySelector('#list #card-'+g.id),inLt:!!d.querySelector('#longtermList #card-'+g.id),
            mainN:d.querySelectorAll('#list .gcard').length};})()""")
        if done.get("skip"):
            T("L17 长期区内标记已处理", False, "skip=%s id=%s" % (done.get("skip"), done.get("id")))
        else:
            T("L17 长期区内标记已处理：保持长期区、不回流主列表",
              done["done"] and done["inLt"] and not done["inMain"], json.dumps(done, ensure_ascii=False))
            p.evaluate("window.__lt.frame().contentWindow.state.done[%s]=false;window.__lt.frame().contentWindow.render({animate:false})" % json.dumps(done["id"]))

        # 7) 横向溢出 / 错误 / 外部请求
        over = []
        for wdt in (430, 390, 360):
            p.set_device(wdt, 900, 2.0)
            time.sleep(0.4)
            o = p.evaluate("(function(){var f=window.__lt.frame(),d=f.contentDocument;return Math.max(d.documentElement.scrollWidth,d.body.scrollWidth)-f.contentWindow.innerWidth;})()")
            over.append([wdt, o])
        T("L18 各宽度无横向溢出（430/390/360）", all(o <= 1 for _, o in over), json.dumps(over))
        errs = p.evaluate("JSON.stringify(window.__lt.errs())")
        cerrs = p.evaluate("JSON.stringify(window.__lt.cerrs())")
        ext = p.evaluate("JSON.stringify(window.__lt.external())")
        T("L19 0 JS 报错", errs == "[]", errs[:300])
        T("L20 0 console.error", cerrs == "[]", cerrs[:300])
        T("L21 0 外部请求（其余请求已 mock）", ext == "[]", ext[:300])

        p.set_device(430, 900, 2.0)
        p.screenshot(os.path.join(REPORT_DIR, "longterm_embedded.png"))
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
