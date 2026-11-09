# -*- coding: utf-8 -*-
"""v2 专项自检 1/4：滚动、滑动与锁（需求 2 / 4 / 5）—— 固定视口 iframe + iframe 原生滚动架构

覆盖：
  需求4 通知页可滚：iframe 固定视口高度（calc(100vh-140px) 手机）、内部原生滚动（touch / wheel 均可滚），
         父页不随通知内容变长/滚动；JS scrollBy 兜底未触发（原生路径有效）；
         通知页左右滑仍切工具，斜向手势不劫持纵向；桌面 1280 同样正常；
  需求4 模板展开/收起：固定视口下不改变 iframe 视口高度（仅内部内容变），可正常滚动；
  需求2 刷新保位：父页 tab + 普通页面滚动位置恢复；通知 tab 恢复 tab、iframe 内部滚动位置自存自恢；
         首次访问仍落工具栏第一格；用户滚动/触摸即取消恢复、不抢滚动；
  需求5 body 锁审计（打开弹层时切页/重建 iframe/关弹层/名单弹层）、fly() 回调抛错后手势仍可用；
  全局：0 JS 报错 / 0 console.error / 无外部请求。

用法：cd C:\\...\\web\\tools && python tests\\v2_scroll_check.py
      set V2_SRC=某副本.html   # 可复盘任意副本
退出码 0 = 全绿。
"""
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import websocket
except Exception:
    print("[v2_scroll_check] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.abspath(os.environ.get("V2_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HTTP_PORT = 8961
CDP_PORT = 9461
W, H = 390, 844
SID = "3260709999"
NAME = "测试同学"
AN_PREFIX = "[[CLASS_NOTICE_V1]]"
RESULTS = []


def T(key, ok, note=""):
    RESULTS.append({"k": key, "ok": bool(ok)})
    print(("[PASS] " if ok else "[FAIL] ") + key + ((" | " + str(note)) if note != "" else ""))


MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": ("班长" if i == 1 else ""), "badge": ("班委" if i == 1 else ""),
            "is_admin": (i == 1)} for i in range(1, 71)]


def build_data():
    groups = []
    for i in range(10):
        g = {"id": "auto_test_%02d" % i, "cat": "教务", "title": "合成通知 %02d" % i,
             "group": "合成测试群", "source": "QQ 合成测试群", "summary": "", "actionable": False,
             "items": [{"kind": "text", "label": "原消息", "time": "11-%02d 10:00" % (1 + i),
                        "text": "合成文本内容 %02d，仅用于 v2 滚动自检，不含真实信息。" % i}],
             "aiSummary": "第 %02d 条合成通知摘要，用于 v2 滚动自检（长页面）。" % i,
             "aiPoints": ["合成要点 %02d" % i],
             "aiSegments": [{"type": "时间", "text": "11-20 12:00"},
                            {"type": "地点", "text": "合成楼(101)"},
                            {"type": "对象", "text": "全体同学"}],
             "deadline": "2026-11-20 12:00", "timeLabel": "11-20 12:00 截止"}
        groups.append(g)
    notices = [{"id": "auto_" + g["id"], "title": "", "body": AN_PREFIX + json.dumps(g, ensure_ascii=False),
                "archived": False, "hidden": False, "override_json": "", "edited_at": 0,
                "ts": 1762000000000 + i * 1000} for i, g in enumerate(groups)]
    homework = [{"id": "hw_%02d" % i, "subject": "合成作业 %02d" % i, "content": "内容 %02d" % i,
                 "due": "2026-11-20", "date": "2026-11-1%d" % (i % 9), "time": "23:59",
                 "author": "测试", "owner": "9000000001", "attachments": "", "done": False,
                 "archived": False, "ts": 1762000000000 + i} for i in range(8)]
    tt = {"c": [{"name": "合成课程", "teacher": "测试老师", "room": "合成楼(101)", "day": 0,
                 "start": 1, "end": 2, "weeks": "1-16", "parity": "all"}], "t": "2026-08-31",
          "meta": {"fetchedAt": 1762000000000}}
    return {"members": MEMBERS, "notices": notices, "homework": homework, "marks": [],
            "fitrecs": [], "tt": tt}


DATA = build_data()

MOCK_JS = r"""
<script>
(function(){
window.__errs=[];window.__cerrs=[];window.__net={counts:{},writes:[],external:[]};
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var DATA=__DATA__;
function mkResp(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};var method=String(o.method||"GET").toUpperCase();
  var s=String((u&&u.url!==undefined)?u.url:u);
  var kind="external";
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0)kind="members";
    else if(s.indexOf("rpc/class_verify")>=0)kind="verify";
    else if(s.indexOf("/notices")>=0){kind=(method==="GET")?"notices":"write";if(method!=="GET")window.__net.writes.push({t:"notices",m:method,u:s,b:o.body||""});}
    else if(s.indexOf("/homework")>=0)kind=(method==="GET")?"homework":"write";
    else if(s.indexOf("/marks")>=0)kind=(method==="GET")?"marks":"write";
    else if(s.indexOf("/fitrecs")>=0)kind=(method==="GET")?"fitrecs":"write";
    else if(s.indexOf("/userdata")>=0)kind=(method==="GET")?"userdata":"write";
    else kind=(method==="GET")?"other":"write";
    window.__net.counts[kind]=(window.__net.counts[kind]||0)+1;
    if(kind==="external")window.__net.external.push(s);
    return mkResp(kind==="members"?DATA.members:(kind==="verify"?{ok:true}:DATA[kind]||[]));
  }
  if(s.indexOf("tt.json")>=0){window.__net.counts.tt=(window.__net.counts.tt||0)+1;return mkResp(DATA.tt);}
  window.__net.counts.external=(window.__net.counts.external||0)+1;
  window.__net.external.push(s);
  return _f.apply(this,arguments);
};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"班长",badge:"班委",is_admin:true,ts:Date.now()}));}catch(e){}
})();
</script>
"""

HOOK = r"""
window.__v2={
  AUTH:AUTH,D:D,NT:NT,gotoTab:gotoTab,pos:POS,frame:function(){return NOTICE_FRAME;},curtab:function(){return CURTAB;},
  auto:function(){return AUTO_NOTICES;},hiddenList:function(){return NT_HIDDEN;},
  meta:function(){return NT_META;},applyAdmin:function(){noticeApplyAdmin();},
  forceRebuild:function(){NOTICE_LAST_DATA="";NOTICE_H=0;renderNoticeFrame();},
  openPicker:function(){openPicker("draw");},rstClose:function(){rstClose(false);},
  errs:function(){return window.__errs||[];},cerrs:function(){return window.__cerrs||[];},
  bootDone:function(){return __bootRefreshDone;},swipeCommit:function(d){return window.__zqSwipeCommit(d);},
  marksPull:marksPull,marksApply:marksApply,UD:UD
};
/* 测试专用：若 localStorage.__v2_user_cancel=1，POS 一开始恢复（armed）就派发一次 wheel 模拟用户滚动 */
(function(){
  try{ if(localStorage.getItem("__v2_user_cancel")!=="1")return; }catch(e){return;}
  var n=0,t=setInterval(function(){
    try{
      if(window.__v2&&window.__v2.pos&&window.__v2.pos.armed){
        window.dispatchEvent(new WheelEvent("wheel",{deltaY:120}));
        window.__v2UserCanceled=true;
        clearInterval(t);
      }
    }catch(e){}
    if(++n>1200)clearInterval(t);
  },8);
})();
"""


def build_preview():
    html = open(SRC, encoding="utf-8", newline="").read()
    idx = html.rfind("})();")
    if idx < 0:
        raise SystemExit("main script end not found")
    html = html[:idx] + HOOK + "\r\n" + html[idx:]
    mock = MOCK_JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")) \
                  .replace("__SID__", SID).replace("__NAME__", NAME)
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    return html.replace("<head>", "<head>" + mock, 1)


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Q(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=40)
        self._id = 0

    def send(self, method, params=None, timeout=40):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                time.sleep(0.01)
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s -> %s" % (method, json.dumps(msg["error"], ensure_ascii=False)))
                return msg.get("result", {})
        raise TimeoutError(method)

    def eval(self, expr, timeout=40):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True}, timeout=timeout)
        res = r.get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError("JS: " + str(res.get("description"))[:500])
        return res.get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def wait_until(cdp, expr, timeout=20, interval=0.12):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        try:
            v = cdp.eval(expr)
            if v:
                return True
            last = v
        except Exception as e:
            last = str(e)[:120]
        time.sleep(interval)
    return False


def get_ws(port):
    t0 = time.time()
    while time.time() - t0 < 30:
        try:
            data = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=2).read())
            for t in data:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("no CDP page")


def touch(cdp, points, kind):
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [
        {"x": p[0], "y": p[1], "id": i + 1} for i, p in enumerate(points)]})


def swipe(cdp, x0, y0, x1, y1, steps=10):
    touch(cdp, [(x0, y0)], "touchStart")
    for i in range(1, steps + 1):
        touch(cdp, [(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)], "touchMove")
        time.sleep(0.016)
    touch(cdp, [], "touchEnd")


def wheel(cdp, x, y, dy):
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y,
                                          "deltaX": 0, "deltaY": dy})


GEO_JS = r"""
(function(){
  var host=document.querySelector('#noticeHost');
  var fr=host?host.querySelector('iframe'):null;
  var r=fr?fr.getBoundingClientRect():null;
  var d=fr?fr.contentDocument:null;
  return {
    vw:innerWidth, vh:innerHeight,
    scrollY:Math.round(window.pageYOffset||window.scrollY||0),
    scrollH:Math.max(document.documentElement.scrollHeight,document.body.scrollHeight),
    tab:(function(){var b=document.querySelector('#tabsBar button.on');return (b&&b.dataset)?b.dataset.tab:"";})(),
    bodyClass:String(document.body.className||""),
    bodyOverflow:getComputedStyle(document.body).overflow,
    frame:r?{x:r.x,y:r.y,w:r.width,h:r.height}:null,
    frameScrollY:d?Math.round(d.defaultView.scrollY||d.defaultView.pageYOffset||0):-1,
    frameScrollH:d?Math.max(d.documentElement.scrollHeight,d.body.scrollHeight):-1,
    frameClientH:d?d.documentElement.clientHeight:-1,
    frameCards:d?d.querySelectorAll('.gcard').length:-1,
    frameCount:host?host.querySelectorAll('iframe').length:0,
    overflowX:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth
  };
})()
"""


def geo(cdp):
    return cdp.eval(GEO_JS)


def boot_ready(cdp, timeout=25):
    wait_until(cdp, "!!(window.__v2&&__v2.bootDone&&__v2.bootDone())", timeout)


def notice_frame_ready(cdp, timeout=30):
    wait_until(cdp, "(function(){try{var g=%s;return !!(g&&g.frameCount&&g.frameCards>=8);}catch(e){return false}})()" % GEO_JS, timeout)


def frame_win_eval(cdp, expr):
    """在通知 iframe 的 window 上执行表达式（同源）。"""
    return cdp.eval("(function(){try{var f=document.querySelector('#noticeHost iframe');return f?f.contentWindow.eval(%s):null;}catch(e){return null;}})()"
                    % json.dumps(expr))


def frame_call(cdp, js):
    return cdp.eval("(function(){try{var f=document.querySelector('#noticeHost iframe');if(!f)return null;return f.contentWindow.eval(%s);}catch(e){return 'ERR:'+e;}})()" % json.dumps(js))


def scroll_frame(cdp, y):
    frame_call(cdp, "window.scrollTo(0,%d); window.scrollY||0" % int(y))


def boot_wait_reload(cdp, timeout=30):
    wait_until(cdp, "!!(window.__v2&&__v2.bootDone&&__v2.bootDone())", timeout)


def run():
    devnull = open(os.devnull, "wb")
    tmp = tempfile.mkdtemp(prefix="v2scroll_")
    prof = tempfile.mkdtemp(prefix="edgeprof_")
    srv = None
    proc = None
    cdp = None
    seed_ids = []
    try:
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(build_preview())
        os.chdir(tmp)
        srv = Q(("127.0.0.1", HTTP_PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/preview.html" % HTTP_PORT
        proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                                 "--no-default-browser-check", "--disable-extensions",
                                 "--remote-debugging-port=%d" % CDP_PORT,
                                 "--user-data-dir=" + prof, "about:blank"],
                                stdout=devnull, stderr=devnull)
        cdp = CDP(get_ws(CDP_PORT))
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": W, "height": H,
                                                        "deviceScaleFactor": 2, "mobile": True})
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        cdp.send("Page.navigate", {"url": url})
        boot_ready(cdp)

        # ============ A. 通知页：固定视口 iframe + 内部原生滚动 ============
        cdp.eval("__v2.gotoTab('nt')")
        notice_frame_ready(cdp)
        time.sleep(0.6)
        g = geo(cdp)
        exp_h = g["vh"] - 140  # @media(max-width:700px)：calc(100vh - 140px)
        T("A1 通知页：iframe 为固定视口高度（calc(100vh-140px)）", abs(g["frame"]["h"] - exp_h) <= 3,
          "%s / expect %s" % (g["frame"]["h"], exp_h))
        T("A2 通知页：iframe 内部可滚动（内容高 > 视口）", g["frameScrollH"] > g["frameClientH"] + 1000,
          "%s/%s" % (g["frameScrollH"], g["frameClientH"]))
        T("A3 通知页：父页不随内容变长（页面高≈视口）", g["scrollH"] <= g["vh"] + 160, "%s/%s" % (g["scrollH"], g["vh"]))
        # 记录 JS scrollBy 兜底是否被调用（正常应走原生滚动）
        frame_call(cdp, "window.__sbCount=0; if(!window.__sbWired){window.__sbWired=true;var _sb=window.scrollBy;window.scrollBy=function(){window.__sbCount++;return _sb.apply(this,arguments);};}")
        fx = g["frame"]["x"] + g["frame"]["w"] / 2
        fy0 = g["frame"]["y"] + min(620, g["frame"]["h"] - 80)
        fy1 = g["frame"]["y"] + 120
        touch(cdp, [(fx, fy0)], "touchStart")
        for i in range(1, 17):
            touch(cdp, [(fx, fy0 + (fy1 - fy0) * i / 16)], "touchMove")
            time.sleep(0.018)
        touch(cdp, [], "touchEnd")
        time.sleep(0.8)
        g2 = geo(cdp)
        T("A4 通知页：iframe 上纵向触摸 → iframe 原生滚动（内部 scrollY 增加）", g2["frameScrollY"] > 80,
          "%s->%s" % (g["frameScrollY"], g2["frameScrollY"]))
        T("A5 通知页：纵向滚动不驱动父页（父页 scrollY≈0）", abs(g2["scrollY"] - g["scrollY"]) <= 2,
          "%s->%s" % (g["scrollY"], g2["scrollY"]))
        T("A6 通知页：正常路径不触发 JS scrollBy 兜底", int(frame_call(cdp, "window.__sbCount") or 0) == 0,
          frame_call(cdp, "window.__sbCount"))
        s0 = g2["frameScrollY"]
        wheel(cdp, fx, g["frame"]["y"] + 300, 400)
        time.sleep(0.6)
        g3 = geo(cdp)
        T("A7 通知页：iframe 上滚轮 → iframe 内部滚动", g3["frameScrollY"] > s0 + 30,
          "%s->%s" % (s0, g3["frameScrollY"]))
        T("A8 通知页：滚轮不滚父页", abs(g3["scrollY"] - g2["scrollY"]) <= 2, "%s/%s" % (g2["scrollY"], g3["scrollY"]))
        # 模板展开/收起：固定视口下 iframe 视口高度不变，内部内容折叠正常
        h_before = geo(cdp)["frame"]["h"]
        fold_ok = cdp.eval("""(function(){try{var d=document.querySelector('#noticeHost iframe').contentDocument;
          var b=d.querySelector('[data-act="fold"]'); if(!b)return false; b.click(); return true;}catch(e){return false;}})()""")
        time.sleep(0.9)
        g4 = geo(cdp)
        T("A9 模板收起：iframe 视口高度不变（固定视口）", bool(fold_ok) and abs(g4["frame"]["h"] - h_before) <= 1,
          "%s->%s" % (h_before, g4["frame"]["h"]))
        T("A10 模板收起：内部仍可滚动", g4["frameScrollH"] > g4["frameClientH"] + 1000, "")
        cdp.eval("""(function(){try{var d=document.querySelector('#noticeHost iframe').contentDocument;
          var b=d.querySelector('[data-act="fold"]'); if(b)b.click();}catch(e){}})()""")
        time.sleep(0.5)

        # ============ B. 通知页横向切工具 + 斜向不劫持 ============
        g = geo(cdp)
        before = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
        swipe(cdp, g["frame"]["x"] + g["frame"]["w"] - 40, g["frame"]["y"] + 260,
              g["frame"]["x"] + 40, g["frame"]["y"] + 260, steps=12)
        time.sleep(0.9)
        after = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
        T("B1 通知页 iframe 上左滑 → 切换工具", after != before and after != "", "%r->%r" % (before, after))
        cdp.eval("__v2.gotoTab('nt')")
        notice_frame_ready(cdp)
        time.sleep(0.5)
        g = geo(cdp)
        before = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
        swipe(cdp, g["frame"]["x"] + 40, g["frame"]["y"] + 260,
              g["frame"]["x"] + g["frame"]["w"] - 40, g["frame"]["y"] + 260, steps=12)
        time.sleep(0.9)
        after = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
        T("B2 通知页 iframe 上右滑 → 切回上一个工具", after != before, "%r->%r" % (before, after))
        # 斜向：横向 2px/步、纵向 8px/步（合成 TouchEvent，不受真实 touch slop 限制）
        cdp.eval("__v2.gotoTab('nt')")
        notice_frame_ready(cdp)
        sy0 = geo(cdp)["frameScrollY"]
        diag = cdp.eval("""(function(){
          try{
            var f=document.querySelector('#noticeHost iframe'),D=f.contentDocument,W=f.contentWindow;
            function mk(x,y){return new Touch({identifier:1,target:D.body,clientX:x,clientY:y});}
            function fire(type,x,y,list){var ev=new TouchEvent(type,{bubbles:true,cancelable:true,touches:list,changedTouches:list,targetTouches:list});
              D.dispatchEvent(ev);return ev;}
            var x=200,y=300,t0=mk(x,y);fire('touchstart',x,y,[t0]);
            var prevented=0,res=[];
            for(var i=1;i<=6;i++){
              x-=2;y-=8;var t=mk(x,y);var ev=fire('touchmove',x,y,[t]);
              if(ev.defaultPrevented)prevented++;
            }
            fire('touchend',x,y,[]);
            return JSON.stringify({prevented:prevented,tab:(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''});
          }catch(e){return JSON.stringify({err:String(e)});}
        })()""")
        diag = json.loads(diag)
        T("B3 斜向手势不劫持纵向（合成 touch：全程不 preventDefault）", int(diag.get("prevented", 9)) == 0,
          json.dumps(diag, ensure_ascii=False))
        T("B4 斜向手势不切工具", diag.get("tab") == "nt", diag.get("tab"))

        # ============ C. 刷新保位 ============
        # C1/C2 通知 tab：父页恢复 tab；iframe 内部滚动自存自恢
        cdp.eval("__v2.gotoTab('nt')")
        notice_frame_ready(cdp)
        time.sleep(0.5)
        scroll_frame(cdp, 2000)
        time.sleep(0.8)
        saved_nt = cdp.eval("(function(){try{return sessionStorage.getItem('zq_nt_scroll_v1');}catch(e){return null;}})()")
        cdp.send("Page.reload", {"ignoreCache": False})
        boot_wait_reload(cdp)
        notice_frame_ready(cdp)
        ok_restore = False
        t0 = time.time()
        while time.time() - t0 < 8:
            g5 = geo(cdp)
            if abs(g5["frameScrollY"] - 2000) <= 90:
                ok_restore = True
                break
            time.sleep(0.2)
        g5 = geo(cdp)
        T("C1 刷新恢复：通知 tab 恢复", g5["tab"] == "nt", g5["tab"])
        T("C2 刷新恢复：通知 iframe 内部滚动位置恢复（2000±90）", ok_restore,
          "saved=%r scrollY=%s" % (saved_nt, g5["frameScrollY"]))
        T("C3 通知 tab 的父页由 iframe 自管（父页 scrollY≈0）", g5["scrollY"] <= 3, g5["scrollY"])

        # C4/C5 普通页面（使用说明）父页滚动位置恢复
        cdp.eval("__v2.gotoTab('ug')")
        time.sleep(0.5)
        maxs = cdp.eval("Math.max(document.documentElement.scrollHeight,document.body.scrollHeight)-innerHeight")
        target = int(min(1200, max(200, (maxs or 300) - 100)))
        cdp.eval("window.scrollTo(0,%d)" % target)
        time.sleep(1.0)
        saved = cdp.eval("(function(){try{return JSON.parse(sessionStorage.getItem('zq_pos_v1')||'null');}catch(e){return null;}})()")
        T("C4 普通页面滚动后 zq_pos_v1 记录 tab/y",
          bool(saved) and saved.get("tab") == "ug" and abs(int(saved.get("y") or 0) - target) <= 40,
          json.dumps(saved, ensure_ascii=False))
        cdp.send("Page.reload", {"ignoreCache": False})
        wait_until(cdp, "(function(){return !!(document.querySelector('#tabsBar button.on')&&window.__v2&&__v2.bootDone&&__v2.bootDone());})()", 30)
        time.sleep(1.5)
        g6 = geo(cdp)
        cur5 = cdp.eval("__v2.curtab()")
        T("C5 刷新恢复：普通页面 tab + 滚动位置恢复", cur5 == "ug" and abs(g6["scrollY"] - target) <= 60,
          "%r/%s vs %s" % (cur5, g6["scrollY"], target))
        # C6 恢复后用户滚动仍被记录（滚动停止 480ms 单次落盘）
        cdp.eval("window.scrollTo(0,520)")
        time.sleep(1.0)
        saved2 = cdp.eval("(function(){try{return JSON.parse(sessionStorage.getItem('zq_pos_v1')||'{}').y;}catch(e){return -1;}})()")
        T("C6 恢复后用户滚动会被记录（不与用户滚动打架）", abs(int(saved2 or 0) - 520) <= 40, saved2)

        # C7 首次访问：清 sessionStorage → 落工具栏第一格、顶部
        sid = cdp.send("Page.addScriptToEvaluateOnNewDocument", {
            "source": 'try{sessionStorage.removeItem("zq_pos_v1");sessionStorage.removeItem("zq_nt_scroll_v1");}catch(e){}'})["identifier"]
        seed_ids.append(sid)
        cdp.send("Page.reload", {"ignoreCache": False})
        wait_until(cdp, "(function(){return !!(document.querySelector('#tabsBar button.on')&&window.__v2&&__v2.bootDone&&__v2.bootDone());})()", 30)
        time.sleep(0.9)
        g7 = geo(cdp)
        first_tab = cdp.eval("(document.querySelector('#tabsBar button[data-tab]')||{}).dataset.tab||''")
        T("C7 首次访问仍落工具栏第一格", g7["tab"] == first_tab and first_tab != "", "%r/%r" % (g7["tab"], first_tab))
        T("C8 首次访问不恢复旧位置（scrollY≈0）", g7["scrollY"] <= 4, g7["scrollY"])
        cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": sid})
        seed_ids.remove(sid)

        # C9 用户手势取消恢复（普通页面）
        sid = cdp.send("Page.addScriptToEvaluateOnNewDocument", {
            "source": ("try{sessionStorage.setItem('zq_pos_v1',JSON.stringify({v:1,sid:'%s',tab:'ug',y:1200,ts:Date.now()}));"
                       "localStorage.setItem('__v2_user_cancel','1');}catch(e){}") % SID})["identifier"]
        seed_ids.append(sid)
        cdp.send("Page.reload", {"ignoreCache": False})
        wait_until(cdp, "(function(){return !!(document.querySelector('#tabsBar button.on')&&window.__v2&&__v2.bootDone&&__v2.bootDone());})()", 30)
        time.sleep(1.6)
        canceled = cdp.eval("!!window.__v2UserCanceled")
        g8 = geo(cdp)
        T("C9 用户滚动取消恢复（不被强行拉回 1200）", bool(canceled) and g8["scrollY"] < 400,
          "canceled=%r scrollY=%s" % (canceled, g8["scrollY"]))
        cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": sid})
        seed_ids.remove(sid)
        cdp.eval("try{localStorage.removeItem('__v2_user_cancel');}catch(e){}")

        # ============ D. body 锁审计 ============
        cdp.eval("__v2.gotoTab('nt')")
        notice_frame_ready(cdp)
        cdp.eval("""(function(){var d=document.querySelector('#noticeHost iframe').contentDocument;
                     var b=d.querySelector('[data-act="original"]'); if(b)b.click();})()""")
        time.sleep(0.4)
        lock1 = cdp.eval("document.body.classList.contains('nt-modal-open')")
        modal_on = cdp.eval("document.getElementById('ntModal').classList.contains('on')")
        T("D1 打开通知弹层：显示 + body 锁", lock1 and modal_on, "%r/%r" % (lock1, modal_on))
        cdp.eval("__v2.gotoTab('draw')")
        time.sleep(0.5)
        g9 = geo(cdp)
        T("D2 弹层打开时切 tab：弹层关闭、body 锁解除",
          (not cdp.eval("document.body.classList.contains('nt-modal-open')")) and
          (not cdp.eval("document.getElementById('ntModal').classList.contains('on')")) and
          ("nt-modal-open" not in g9["bodyClass"]), g9["bodyClass"])
        T("D3 切页后 body 可滚动（overflow visible）", g9["bodyOverflow"] in ("visible", ""), g9["bodyOverflow"])
        cdp.eval("__v2.gotoTab('nt')")
        notice_frame_ready(cdp)
        cdp.eval("""(function(){var d=document.querySelector('#noticeHost iframe').contentDocument;
                     var b=d.querySelector('[data-act="original"]'); if(b)b.click();})()""")
        time.sleep(0.4)
        rebuilt_ok = cdp.eval("document.getElementById('ntModal').classList.contains('on')")
        cdp.eval("__v2.forceRebuild()")
        time.sleep(0.6)
        T("D4 弹层打开时重建 iframe：弹层关闭、body 锁解除",
          rebuilt_ok and (not cdp.eval("document.body.classList.contains('nt-modal-open')")) and
          (not cdp.eval("document.getElementById('ntModal').classList.contains('on')")), rebuilt_ok)
        T("D5 重建 iframe 后通知卡仍在 / 0 JS 报错",
          geo(cdp)["frameCards"] >= 8 and len(cdp.eval("__v2.errs()")) == 0,
          "errs=%s" % json.dumps(cdp.eval("__v2.errs()"), ensure_ascii=False)[:200])
        cdp.eval("__v2.gotoTab('draw')")
        time.sleep(0.3)
        cdp.eval("__v2.openPicker()")
        time.sleep(0.5)
        r1 = cdp.eval("document.body.classList.contains('rst-lock')")
        cdp.eval("__v2.gotoTab('nt')")
        time.sleep(0.5)
        r2 = cdp.eval("document.body.classList.contains('rst-lock')")
        r3 = cdp.eval("document.getElementById('rosterModal').style.display")
        T("D6 名单弹层打开：body 锁", r1 is True, r1)
        T("D7 名单弹层打开时切页：锁解除、弹层关闭", (not r2) and r3 == "none", "%r/%r" % (r2, r3))
        # fly() 回调抛错 → animating 兜底释放
        cdp.eval("__v2.gotoTab('draw')")
        time.sleep(0.4)
        cdp.eval("window.__tabThumbBak=window.__tabThumb; window.__tabThumb=function(){throw new Error('boom-anim');};")
        swipe_toolbar(cdp, 1)
        time.sleep(0.8)
        tab_mid = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
        cdp.eval("window.__tabThumb=window.__tabThumbBak;")
        swipe_toolbar(cdp, 1)
        tab_after = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
        T("D8 fly() 回调抛错后手势仍可用（animating 未永久卡死）",
          tab_after != tab_mid and tab_after != "", "%r->%r" % (tab_mid, tab_after))

        # ============ E. 桌面 1280 ============
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 800,
                                                        "deviceScaleFactor": 1, "mobile": False})
        cdp.eval("__v2.gotoTab('nt')")
        notice_frame_ready(cdp)
        time.sleep(0.8)
        g10 = geo(cdp)
        T("E1 桌面 1280：通知 iframe 固定视口高度（calc(100vh-150px)）",
          abs(g10["frame"]["h"] - (g10["vh"] - 150)) <= 3, "%s / expect %s" % (g10["frame"]["h"], g10["vh"] - 150))
        T("E2 桌面 1280：无横向溢出", g10["overflowX"] <= 1, g10["overflowX"])
        T("E3 桌面 1280：父页不随通知内容滚动", g10["scrollH"] <= g10["vh"] + 160, "%s/%s" % (g10["scrollH"], g10["vh"]))
        s1 = g10["frameScrollY"]
        wheel(cdp, g10["frame"]["x"] + 400, g10["frame"]["y"] + 300, 500)
        time.sleep(0.6)
        T("E4 桌面 1280：iframe 上滚轮 → iframe 内部滚动", geo(cdp)["frameScrollY"] > s1 + 30,
          "%s->%s" % (s1, geo(cdp)["frameScrollY"]))
        g11 = geo(cdp)
        before = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
        swipe(cdp, g11["frame"]["x"] + g11["frame"]["w"] - 40, g11["frame"]["y"] + 260,
              g11["frame"]["x"] + 40, g11["frame"]["y"] + 260, steps=12)
        time.sleep(0.9)
        after = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
        T("E5 桌面 1280：iframe 上左滑 → 切换工具", after != before, "%r->%r" % (before, after))

        # ============ F. reduced-motion 降级 ============
        cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        cdp.eval("__v2.gotoTab('draw')")
        time.sleep(0.4)
        anim = cdp.eval("getComputedStyle(document.querySelector('#s-draw')).animationName")
        T("F1 reduced-motion：切页动画降级为 none", anim == "none", anim)
        cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "no-preference"}]})

        # ============ G. 全局 ============
        errs = cdp.eval("__v2.errs()") or []
        cerrs = cdp.eval("__v2.cerrs()") or []
        ext = cdp.eval("window.__net.external") or []
        T("G1 全程 0 JS 报错", len(errs) == 0, json.dumps(errs, ensure_ascii=False)[:400])
        T("G2 全程 0 console.error", len(cerrs) == 0, json.dumps(cerrs, ensure_ascii=False)[:400])
        T("G3 无外部请求", len(ext) == 0, json.dumps(ext, ensure_ascii=False)[:300])
    finally:
        for sid in list(seed_ids):
            try:
                cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": sid})
            except Exception:
                pass
        if cdp:
            cdp.close()
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        if srv:
            srv.shutdown()
            srv.server_close()
        try:
            devnull.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(prof, ignore_errors=True)


def free_boxes(cdp):
    return cdp.eval("""
(function(){
  var bar=document.getElementById('tabsBar'); if(!bar)return [];
  var br=bar.getBoundingClientRect();
  return Array.prototype.map.call(bar.querySelectorAll('button'),function(b){
    var r=b.getBoundingClientRect();
    return {tab:b.dataset.tab,x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height};
  });
})()
""")


def swipe_toolbar(cdp, direction):
    bs = free_boxes(cdp)
    if not bs:
        return False
    on = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
    cur = None
    for b in bs:
        if b["tab"] == on:
            cur = b
    if not cur:
        return False
    x0 = cur["x"] + (cur["w"] / 2 - 6) * direction
    x1 = cur["x"] - (cur["w"] / 2 - 6) * direction
    swipe(cdp, x0, cur["y"], x1, cur["y"], steps=8)
    time.sleep(0.8)
    return True


def main():
    run()
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 60)
    print("v2_scroll_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
