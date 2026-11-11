# -*- coding: utf-8 -*-
"""v2 专项回归：滑动手感 / 手势帧率（CDP 合成 touch）

背景：用户反馈 v2 后网页滑动「阻滞、不跟手、抽动」。v2 曾把手势 touchmove 的样式写入改成
rAF 合并（主线程忙时延迟一帧以上），并把 sessionStorage 写入放进滚动 rAF 节流。
本脚本用 CDP 合成 touch 量测并对比三个版本：
  - `baseline`：v2 之前冻结版 `tools/_backup/index_local_20261105_v2_pre.html`（同步直写）；
  - `prefix`  ：v2 冻结版 `tools/_backup/index_local_20261105_2030_preSwipeFeel.html`（rAF 合并，待修复的“卡”版本）；
  - `fixed`   ：当前 `tools/index.html`（本次修复：同步直写 + 几何缓存校验 + 滚动停止后落盘）。

指标：
  - reactionRate：跟手锁定的每次 touchmove 中，样式在**本次事件处理结束时**已更新的比例；
  - applyLatencyP50/P95：touchmove 事件 → style 变更（MutationObserver）的延迟；
  - longFrames：手势期间帧间隔 >32ms 的帧数；frameP95：手势期间 rAF 帧间隔 p95；
  - firstReactionMs：touchstart → 首次 transform 变化；
  - posWritesDuringScroll / posWritesAfterSettle：滚动期间与停止后的 zq_pos_v1 写入次数
    （要求：滚动期间 0 次，停止后 1 次；baseline 无 POS，记为 0）。

用法：
  python tests\\v2_swipe_perf.py                 # 跑三档对比 + 断言
  python tests\\v2_swipe_perf.py --only fixed    # 只跑一档并输出指标
退出码 0 = 断言全过。
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
    print("[v2_swipe_perf] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HTTP_PORT = 8998
CDP_PORT = 9498
W, H = 390, 844
SID = "9999000005"
NAME = "测试同学"
AN_PREFIX = "[[CLASS_NOTICE_V1]]"

BASELINE = os.path.join(ROOT, "_backup", "index_local_20261105_v2_pre.html")
PREFIX = os.path.join(ROOT, "_backup", "index_local_20261105_2030_preSwipeFeel.html")
FIXED = os.path.join(ROOT, "index.html")

MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": "", "badge": "", "is_admin": False} for i in range(1, 71)]


def build_notices():
    rows = []
    for i in range(10):
        g = {"id": "g_sw_%02d" % i, "cat": "教务", "title": "合成通知 %02d" % i,
             "group": "合成群", "source": "QQ 合成群", "summary": "摘要",
             "actionable": True,
             "items": [{"kind": "text", "label": "原消息", "time": "11-05 10:00", "text": "合成文本。"}],
             "aiSummary": "合成摘要 用于滑动手感量测。" * 3,
             "aiPoints": ["要点一", "要点二"],
             "aiSegments": [{"type": "时间", "text": "11-20 12:00"},
                            {"type": "地点", "text": "合成楼 101"},
                            {"type": "对象", "text": "全体同学"}],
             "deadline": "2026-11-20 12:00", "timeLabel": "11-20 12:00 截止"}
        rows.append({"id": "auto_" + g["id"], "title": "", "body": AN_PREFIX + json.dumps(g, ensure_ascii=False),
                     "archived": False, "hidden": False, "override_json": "", "edited_at": 0,
                     "ts": 1762000000000 + i * 1000})
    return rows


NOTICES = build_notices()

MOCK_JS = r"""
<script>
(function(){
window.__errs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||"error"));});
var DATA=__DATA__;
function ok(o){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(o);},text:function(){return Promise.resolve("");}});}
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};var s=String((u&&u.url!==undefined)?u.url:u);
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0)return ok(DATA.members);
    if(s.indexOf("/notices")>=0)return ok(s.indexOf("select=id,ts")>=0
      ?DATA.notices.map(function(r){return {id:r.id,ts:r.ts,hidden:!!r.hidden,edited_at:Number(r.edited_at)||0};})
      :DATA.notices);
    if(s.indexOf("/homework")>=0)return ok([]);
    if(s.indexOf("/marks")>=0)return ok([]);
    if(s.indexOf("/fitrecs")>=0)return ok([]);
    if(s.indexOf("/userdata")>=0)return ok([]);
    return ok([]);
  }
  if(s.indexOf("tt.json")>=0)return ok({c:[],t:"2026-08-31",meta:{fetchedAt:1762000000000}});
  return _f.apply(this,arguments);
};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
})();
</script>
"""

HOOK = r"""
window.__swipe={AUTH:AUTH,gotoTab:gotoTab,curtab:function(){return CURTAB;},
  bootDone:function(){return __bootRefreshDone;},errs:function(){return window.__errs||[];},
  frame:function(){try{return document.querySelector('#noticeHost iframe');}catch(e){return null;}}};
"""


def build_preview(src):
    html = open(src, encoding="utf-8", newline="").read()
    idx = html.rfind("})();")
    if idx < 0:
        raise SystemExit("main script end not found: " + src)
    html = html[:idx] + HOOK + "\r\n" + html[idx:]
    mock = MOCK_JS.replace("__DATA__", json.dumps({"members": MEMBERS, "notices": NOTICES},
                                                  ensure_ascii=False).replace("<", "\\u003c")) \
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
            raise RuntimeError("JS: " + str(res.get("description"))[:400])
        return res.get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


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


def wait_until(cdp, expr, timeout=25, interval=0.1):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cdp.eval(expr):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def touch(cdp, points, kind):
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [
        {"x": p[0], "y": p[1], "id": i + 1} for i, p in enumerate(points)]})


INSTRUMENT = r"""
(function(){
  if(window.__swInstalled)return true;
  window.__swInstalled=true;
  var SW=window.__sw={moves:[],muts:[],frames:[],startT:0,stopT:0,touchStartT:0,firstMutT:0,
    posWrites:0,posWritesAfter:0,el:null,pane:null,tt:null,sx:0,tracking:false};
  /* 统计 zq_pos_v1 写入次数 */
  try{
    var proto=window.Storage&&window.Storage.prototype;
    if(proto&&proto.setItem){
      var _si=proto.setItem;
      proto.setItem=function(k,v){
        if(String(k)==="zq_pos_v1"){SW.posWrites++;}
        return _si.apply(this,arguments);
      };
    }
  }catch(e){}
  /* MutationObserver：记录内联 style 变化（transform），用于首帧反应延迟（辅助指标） */
  try{
    var mo=new MutationObserver(function(ms){
      for(var i=0;i<ms.length;i++){
        var t=ms[i].target;
        if(!t||t.nodeType!==1)continue;
        var st=t.getAttribute&&t.getAttribute("style")||"";
        var m=st.match(/transform:[^;]+/);
        if(!m)continue;
        var now=performance.now();
        if(!SW.firstMutT)SW.firstMutT=now;
        SW.muts.push([now,m[0],t.id||t.className||t.tagName]);
      }
    });
    mo.observe(document.body,{attributes:true,attributeFilter:["style"],subtree:true});
  }catch(e){}
  function frameLoop(){
    if(SW.tracking)SW.frames.push(performance.now());
    if(SW.tracking)requestAnimationFrame(frameLoop);
  }
  function txX(el){
    if(!el)return 0;
    var s=String(el.style.transform||""),m=s.match(/(?:translateX|translate3d)\((-?[0-9.]+)px/);
    return m?parseFloat(m[1]):0;
  }
  document.addEventListener("touchstart",function(e){
    SW.touchStartT=performance.now();
    SW.el=document.querySelector("section.on");
    SW.pane=document.querySelector(".stpane.on");
    SW.tt=document.querySelector(".ttmain");
    SW.moves.length=0;SW.muts.length=0;SW.frames.length=0;SW.firstMutT=0;
    SW.sx=e.touches&&e.touches[0]?e.touches[0].clientX:0;
    SW.tracking=true;
    requestAnimationFrame(frameLoop);
  },{passive:true});
  document.addEventListener("touchmove",function(e){
    if(!SW.tracking)return;
    var tp=e.touches&&e.touches[0];
    var dx=tp?(tp.clientX-SW.sx):0;
    SW.moves.push([performance.now(),dx,txX(SW.el),txX(SW.pane),txX(SW.tt)]);
  },{passive:true});
  document.addEventListener("touchend",function(){
    SW.tracking=false;SW.stopT=performance.now();
  },{passive:true});
  return true;
})()
"""

STATS_JS = r"""
(function(){
  var SW=window.__sw;
  function pct(arr,p){if(!arr.length)return -1;var a=arr.slice().sort(function(x,y){return x-y;});
    var i=Math.min(a.length-1,Math.max(0,Math.round((a.length-1)*p)));return a[i];}
  var moves=SW.moves||[],muts=SW.muts||[],frames=SW.frames||[];
  var total=0,sync=0,errs=[],lat=[];
  for(var i=0;i<moves.length;i++){
    total++;
    var dx=moves[i][1];
    var xs=[moves[i][2],moves[i][3],moves[i][4]];
    var chosen=0;
    for(var q=0;q<xs.length;q++){if(Math.abs(xs[q])>Math.abs(chosen))chosen=xs[q];}
    /* 手势锁定后 damp=1（有目标页时）：期望 transformX==dx；rAF 合并版会落后一帧（差一次移动步长） */
    var err=Math.abs(chosen-dx);
    errs.push(err);
    if(err<=2)sync++;
    var t=moves[i][0],best=-1;
    for(var j=0;j<muts.length;j++){
      if(muts[j][0]>=t&&muts[j][0]-t<120){best=muts[j][0]-t;break;}
    }
    if(best>=0)lat.push(best);
  }
  var gaps=[];
  for(var k=1;k<frames.length;k++)gaps.push(frames[k]-frames[k-1]);
  var long=0;
  for(k=0;k<gaps.length;k++)if(gaps[k]>32)long++;
  return {
    moves:total,
    muts:(muts||[]).length,
    elTag:SW.el?(SW.el.id||SW.el.tagName):"",
    reactionRate:total?sync/total:0,
    syncErrP50:Math.round(pct(errs,0.5)*100)/100,
    syncErrP95:Math.round(pct(errs,0.95)*100)/100,
    applyLatencyP50:Math.round(pct(lat,0.5)*100)/100,
    applyLatencyP95:Math.round(pct(lat,0.95)*100)/100,
    applyCount:lat.length,
    frameP50:Math.round(pct(gaps,0.5)*100)/100,
    frameP95:Math.round(pct(gaps,0.95)*100)/100,
    frameMax:Math.round(pct(gaps,1)*100)/100,
    frameCount:gaps.length,
    longFrames:long,
    firstReactionMs:SW.firstMutT?Math.round((SW.firstMutT-SW.touchStartT)*100)/100:-1,
    posWrites:SW.posWrites||0
  };
})()
"""



SLOW_JS = r"""
(function(){
  window.__slowSwipe=function(){
    function touch(x,y){return new Touch({identifier:1,target:document.body,clientX:x,clientY:y});}
    function fire(type,x,y,list){var ev=new TouchEvent(type,{bubbles:true,cancelable:true,touches:list,changedTouches:list,targetTouches:list});
      document.dispatchEvent(ev);return ev;}
    function readTx(){
      var el=document.querySelector(".stpane.on")||document.querySelector("section.on");
      if(!el)return 0;var s=String(el.style.transform||""),m=s.match(/(?:translateX|translate3d)\((-?[0-9.]+)px/);
      return m?parseFloat(m[1]):0;}
    var out=[],x=330,y=560,t0=touch(x,y);fire("touchstart",x,y,[t0]);
    for(var i=1;i<=10;i++){x-=4;var t=touch(x,y);var ev=fire("touchmove",x,y,[t]);
      out.push({dx:x-330,tx:readTx(),prevented:!!ev.defaultPrevented});}
    fire("touchend",x,y,[]);
    return out;
  };
  window.__diagSwipe=function(){
    function touch(x,y){return new Touch({identifier:1,target:document.body,clientX:x,clientY:y});}
    function fire(type,x,y,list){var ev=new TouchEvent(type,{bubbles:true,cancelable:true,touches:list,changedTouches:list,targetTouches:list});
      document.dispatchEvent(ev);return ev;}
    function readTx(){var el=document.querySelector(".stpane.on")||document.querySelector("section.on");if(!el)return 0;
      var s=String(el.style.transform||""),m=s.match(/(?:translateX|translate3d)\((-?[0-9.]+)px/);return m?parseFloat(m[1]):0;}
    var x=330,y=560,prevented=0,maxTx=0,t0=touch(x,y);fire("touchstart",x,y,[t0]);
    for(var i=1;i<=6;i++){x-=2;y-=8;var t=touch(x,y);var ev=fire("touchmove",x,y,[t]);
      if(ev.defaultPrevented)prevented++;var tx=readTx();if(Math.abs(tx)>Math.abs(maxTx))maxTx=tx;}
    fire("touchend",x,y,[]);
    return {prevented:prevented,maxTx:maxTx};
  };
  return true;
})()
"""

NOTICE_SLOW_JS = r"""
(function(){
  window.__noticeSlowH=function(){
    try{
      var f=document.querySelector('#noticeHost iframe');if(!f)return JSON.stringify({err:'no-frame'});
      var D=f.contentDocument;
      function touch(x,y){return new Touch({identifier:1,target:D.body,clientX:x,clientY:y});}
      function fire(type,x,y,list){var ev=new TouchEvent(type,{bubbles:true,cancelable:true,touches:list,changedTouches:list,targetTouches:list});
        D.dispatchEvent(ev);return ev;}
      function ptx(){try{var el=document.querySelector('section.on');if(!el)return "";return String(el.style.transform||"");}catch(e){return "";}}
      function pth(){try{var el=document.querySelector('.tabs-thumb');return el?String(el.style.transform||""):"";}catch(e){return "";}}
      var sx=200,sy=300,out=[],t0=touch(sx,sy);fire('touchstart',sx,sy,[t0]);
      for(var i=1;i<=10;i++){var x=sx-4*i;var t=touch(x,sy);var ev=fire('touchmove',x,sy,[t]);
        out.push({dx:x-sx,sectionTx:ptx(),thumbTx:pth(),prevented:!!ev.defaultPrevented});}
      fire('touchend',sx-40,sy,[]);
      return JSON.stringify(out);
    }catch(e){return JSON.stringify({err:String(e)});}
  };
  window.__noticeVCount=0;
  window.__noticeNative=function(){
    try{
      var f=document.querySelector('#noticeHost iframe');var W=f.contentWindow;
      W.__sb=0;W.__psb=0;
      try{var _sb=W.scrollBy;W.scrollBy=function(){W.__sb++;return _sb.apply(this,arguments);};}catch(e){}
      try{var p=W.parent;var _p=p.scrollBy;p.scrollBy=function(){W.__psb++;return _p.apply(this,arguments);};}catch(e){}
      return true;
    }catch(e){return false;}
  };
  window.__noticeVStats=function(){
    try{
      var f=document.querySelector('#noticeHost iframe');var W=f.contentWindow;
      return JSON.stringify({iframeY:Math.round(W.scrollY||0),parentY:Math.round(parent.pageYOffset||0),
        sb:W.__sb||0,psb:W.__psb||0});
    }catch(e){return JSON.stringify({err:String(e)});}
  };
  return true;
})()
"""


def do_slow_swipe(cdp):
    cdp.eval("__swipe.gotoTab('draw')")
    time.sleep(0.6)
    cdp.eval(SLOW_JS)
    time.sleep(0.2)
    moves = json.loads(cdp.eval("JSON.stringify(window.__slowSwipe())"))
    time.sleep(0.5)
    diag = json.loads(cdp.eval("JSON.stringify(window.__diagSwipe())"))
    first = None
    sync_after = []
    for m in moves:
        ok = abs(m["tx"] - m["dx"]) <= 2 and abs(m["tx"]) > 0
        if ok and first is None:
            first = m["dx"]
        if first is not None:
            sync_after.append(1 if ok else 0)
    return {"moves": moves, "firstFollowDx": first,
            "followRateAfterLock": (sum(sync_after) / len(sync_after)) if sync_after else 0,
            "diagPrevented": diag.get("prevented"), "diagMaxTx": diag.get("maxTx")}


def do_notice_slow_h(cdp):
    cdp.eval("__swipe.gotoTab('nt')")
    wait_until(cdp, "(function(){try{var f=__swipe.frame();return !!(f&&f.contentDocument&&f.contentDocument.querySelectorAll('.gcard').length>=8);}catch(e){return false;}})()", 25)
    time.sleep(0.4)
    cdp.eval(NOTICE_SLOW_JS)
    time.sleep(0.2)
    raw = cdp.eval("window.__noticeSlowH()")
    try:
        moves = json.loads(raw)
    except Exception:
        moves = [{"err": str(raw)}]
    thumb_first = None
    section_transformed = False
    prevented = 0
    if isinstance(moves, list):
        for m in moves:
            if "dx" not in m:
                continue
            if m.get("sectionTx"):
                section_transformed = True
            if thumb_first is None and m.get("thumbTx"):
                thumb_first = m["dx"]
            if m.get("prevented"):
                prevented += 1
    return {"moves": moves, "thumbFollowDx": thumb_first,
            "sectionTransformed": section_transformed, "prevented": prevented}


def do_notice_vertical(cdp):
    cdp.eval("__swipe.gotoTab('nt')")
    wait_until(cdp, "(function(){try{var f=__swipe.frame();return !!(f&&f.contentDocument&&f.contentDocument.querySelectorAll('.gcard').length>=8);}catch(e){return false;}})()", 25)
    time.sleep(0.4)
    cdp.eval(NOTICE_SLOW_JS)
    cdp.eval("window.__noticeNative()")
    fr = cdp.eval("(function(){var f=__swipe.frame();var r=f.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})()")
    if not fr:
        return None
    x = fr["x"] + fr["w"] / 2
    y0 = fr["y"] + min(520, fr["h"] - 80)
    touch(cdp, [(x, y0)], "touchStart")
    for i in range(1, 17):
        touch(cdp, [(x, y0 - 10 * i)], "touchMove")
        time.sleep(0.02)
    touch(cdp, [], "touchEnd")
    time.sleep(0.7)
    st = json.loads(cdp.eval("window.__noticeVStats()") or "{}")
    return {"iframeY": st.get("iframeY"), "parentY": st.get("parentY"),
            "iframeScrollBy": st.get("sb"), "parentScrollBy": st.get("psb")}


def do_step_swipe(cdp):
    """抽签页内容左滑（STEP1→STEP2）：起点在内容卡片上，避免命中横向滚动区。"""
    x0, y0 = 330, 520
    touch(cdp, [(x0, y0)], "touchStart")
    for i in range(1, 13):
        touch(cdp, [(x0 - 20 * i, y0)], "touchMove")
        time.sleep(0.016)
    touch(cdp, [], "touchEnd")
    time.sleep(0.5)
    return cdp.eval(STATS_JS)


def do_toolbar_swipe(cdp):
    box = cdp.eval("""(function(){var b=document.querySelector('#tabsBar button.on');if(!b)return null;
      var r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()""")
    if not box:
        return None
    touch(cdp, [(box["x"] + 20, box["y"])], "touchStart")
    for i in range(1, 13):
        touch(cdp, [(box["x"] + 20 - 16 * i, box["y"])], "touchMove")
        time.sleep(0.016)
    touch(cdp, [], "touchEnd")
    time.sleep(0.5)
    return cdp.eval(STATS_JS)


def do_scroll_writes(cdp):
    """在可滚动的普通页面滚动 ~1s，统计 zq_pos_v1 写入；停止 0.7s 后再统计。"""
    cdp.eval("__swipe.gotoTab('ug')")
    time.sleep(0.5)
    cdp.eval("window.__sw.posWrites=0")
    # 按页面最大滚动量均分 12 步、每步 80ms（约 0.96s 持续滚动；避免中途触底导致提前停止）
    cdp.eval("""(function(){
      var maxs=Math.max(0,Math.max(document.documentElement.scrollHeight,document.body.scrollHeight)-innerHeight);
      var step=Math.max(20,Math.floor(maxs/14));
      var i=0;
      function run(){ i++; window.scrollTo(0, i*step); if(i<12)setTimeout(run,80); }
      setTimeout(run,10);
    })()""")
    time.sleep(1.35)
    during = cdp.eval("window.__sw.posWrites")
    time.sleep(0.7)
    after = cdp.eval("window.__sw.posWrites")
    return {"during": int(during or 0), "afterSettle": int(after or 0)}


def run_case(src, name):
    tmp = tempfile.mkdtemp(prefix="swperf_")
    prof = tempfile.mkdtemp(prefix="edgeprof_")
    srv = None
    proc = None
    cdp = None
    out = {"name": name, "src": os.path.basename(src)}
    try:
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(build_preview(src))
        os.chdir(tmp)
        srv = Q(("127.0.0.1", HTTP_PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                                 "--no-default-browser-check", "--disable-extensions",
                                 "--remote-debugging-port=%d" % CDP_PORT,
                                 "--user-data-dir=" + prof, "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cdp = CDP(get_ws(CDP_PORT))
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": W, "height": H,
                                                        "deviceScaleFactor": 2, "mobile": True})
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        cdp.send("Page.navigate", {"url": "http://127.0.0.1:%d/preview.html" % HTTP_PORT})
        boot = wait_until(cdp, "!!(window.__swipe&&__swipe.bootDone&&__swipe.bootDone())", 25)
        out["boot"] = bool(boot)
        time.sleep(0.6)
        cdp.eval(INSTRUMENT)
        time.sleep(0.2)
        out["step"] = do_step_swipe(cdp)
        cdp.eval("__swipe.gotoTab('draw')")
        time.sleep(0.6)
        out["toolbar"] = do_toolbar_swipe(cdp)
        out["slow"] = do_slow_swipe(cdp)
        out["noticeSlowH"] = do_notice_slow_h(cdp)
        out["noticeV"] = do_notice_vertical(cdp)
        out["scroll"] = do_scroll_writes(cdp)
        out["errs"] = cdp.eval("JSON.stringify(window.__errs||[])")
    finally:
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
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(prof, ignore_errors=True)
    return out


def fmt(v):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return ("%.2f" % v)
    return str(v)


def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    cases = [("baseline", BASELINE), ("prefix", PREFIX), ("fixed", FIXED)]
    for name, path in cases:
        if not os.path.exists(path):
            print("missing:", path)
            sys.exit(2)
    res = {}
    for name, path in cases:
        if only and name != only:
            continue
        print("[run]", name, os.path.basename(path))
        res[name] = run_case(path, name)

    def cell(r, key, sub):
        try:
            return r[key][sub]
        except Exception:
            return None

    def getv(r, *path):
        cur2 = r
        for k in path:
            if not isinstance(cur2, dict):
                return None
            cur2 = cur2.get(k)
        return cur2

    print("")
    print("=" * 100)
    print("指标")
    print("%-28s %-12s %-12s %-12s" % ("metric", "baseline", "prefix", "fixed"))
    rows = [
        ("step reactionRate", ("step", "reactionRate")),
        ("step syncErrP50(px)", ("step", "syncErrP50")),
        ("step applyLatencyP50(ms)", ("step", "applyLatencyP50")),
        ("step frameP95(ms)", ("step", "frameP95")),
        ("slow4px firstFollowDx", ("slow", "firstFollowDx")),
        ("slow4px followRate", ("slow", "followRateAfterLock")),
        ("slow4px diagPrevented", ("slow", "diagPrevented")),
        ("noticeH thumbFollowDx", ("noticeSlowH", "thumbFollowDx")),
        ("noticeH sectionTransformed", ("noticeSlowH", "sectionTransformed")),
        ("noticeV iframeScrollY", ("noticeV", "iframeY")),
        ("noticeV parentScrollY", ("noticeV", "parentY")),
        ("noticeV iframeScrollBy", ("noticeV", "iframeScrollBy")),
        ("toolbar reactionRate", ("toolbar", "reactionRate")),
        ("posWrites duringScroll", ("scroll", "during")),
        ("posWrites afterSettle", ("scroll", "afterSettle")),
    ]
    for label, path in rows:
        vals = [getv(res.get(n) or {}, *path) for n in ("baseline", "prefix", "fixed")]
        print("%-28s %-12s %-12s %-12s" % (label, *[fmt(x) for x in vals]))
    print("=" * 100)
    for name in ("baseline", "prefix", "fixed"):
        r = res.get(name)
        if not r:
            continue
        print("[%s] boot=%s slowMoves=%s noticeMoves=%s errs=%s"
              % (name, r.get("boot"),
                 len((getv(r, "slow", "moves") or [])),
                 len((getv(r, "noticeSlowH", "moves") or [])),
                 str(r.get("errs"))[:120]))

    fails = []
    fixed = res.get("fixed")
    base = res.get("baseline")
    prefix = res.get("prefix")
    if not fixed:
        print("[v2_swipe_perf] 未跑 fixed")
        sys.exit(2)
    if not fixed.get("boot"):
        fails.append("fixed 启动失败")
    fs = fixed.get("step") or {}
    bs = (base or {}).get("step") or {}
    if (fs.get("reactionRate") or 0) < 0.9:
        fails.append("fixed 手势同步命中率 < 0.9：%s" % fs.get("reactionRate"))
    if fs.get("syncErrP50", 999) > 2:
        fails.append("fixed syncErrP50 > 2px：%s" % fs.get("syncErrP50"))
    if fs.get("applyLatencyP50", 999) > 8:
        fails.append("fixed applyLatencyP50 > 8ms：%s" % fs.get("applyLatencyP50"))
    if base and fs.get("frameP95", 999) > max((bs.get("frameP95") or 0) + 12, 45):
        fails.append("fixed frameP95 明显差于 baseline：fixed=%s baseline=%s"
                     % (fs.get("frameP95"), bs.get("frameP95")))
    # 4px 慢速滑动：从第一个 >=4px 移动起必须同步跟手（旧版 12px 死区会在 12~16px 才跟上）
    sl = fixed.get("slow") or {}
    ff = sl.get("firstFollowDx")
    if ff is None or abs(ff) > 5:
        fails.append("fixed 慢速 4px 滑动首个跟手位移 > 5px（仍有死区跳变）：firstFollowDx=%s" % ff)
    if (sl.get("followRateAfterLock") or 0) < 0.9:
        fails.append("fixed 慢速滑动锁定后跟手率 < 0.9：%s" % sl.get("followRateAfterLock"))
    if int(sl.get("diagPrevented") or 0) != 0:
        fails.append("fixed 斜向手势在锁定前被劫持（preventDefault=%s）" % sl.get("diagPrevented"))
    if abs(float(sl.get("diagMaxTx") or 0)) > 0.5:
        fails.append("fixed 斜向手势产生了横向 transform：%s" % sl.get("diagMaxTx"))
    # 通知页：X5 残影修复后 section/iframe 不做 transform，只驱动 toolbar thumb
    nh = fixed.get("noticeSlowH") or {}
    nff = nh.get("thumbFollowDx")
    if nff is None or abs(nff) > 5:
        fails.append("fixed 通知页拖动 toolbar thumb 未从 >=4~5px 跟手：%s" % nff)
    if nh.get("sectionTransformed"):
        fails.append("fixed 通知页拖动仍对含 iframe 的 section 做了 transform（X5 残影风险）")

    # 通知页纵向：原生滚动（iframe scrollY 增加、父页不滚、无 JS scrollBy 兜底）
    nv = fixed.get("noticeV") or {}
    if int(nv.get("iframeY") or 0) < 80:
        fails.append("fixed 通知页纵向触摸未滚 iframe：iframeY=%s" % nv.get("iframeY"))
    if abs(int(nv.get("parentY") or 0)) > 2:
        fails.append("fixed 通知页纵向滚动带动父页：parentY=%s" % nv.get("parentY"))
    if int(nv.get("iframeScrollBy") or 0) != 0:
        fails.append("fixed 通知页纵向走了 JS scrollBy 兜底：calls=%s" % nv.get("iframeScrollBy"))
    # 灵敏度：旧版（baseline/prefix）4px 慢速应在 12px 左右才跟手
    if base:
        bff = (base.get("slow") or {}).get("firstFollowDx")
        if bff is not None and abs(bff) < 8:
            fails.append("用例灵敏度不足：baseline 慢速首跟手位移=%s（应 ~12px）" % bff)
        ps = prefix.get("step") if prefix else None
        if prefix and (prefix.get("step") or {}).get("reactionRate") is not None:
            pr = (prefix.get("step") or {}).get("reactionRate") or 0
            target_r = (fs.get("reactionRate") or 0)
            if target_r >= 0.9 and pr > target_r - 0.3:
                fails.append("用例灵敏度不足：prefix step reactionRate=%s 未明显低于 fixed=%s"
                             % (pr, target_r))
    tb = fixed.get("toolbar") or {}
    if tb.get("reactionRate") is not None and tb.get("reactionRate") < 0.9:
        fails.append("fixed 工具栏滑动 reactionRate < 0.9：%s" % tb.get("reactionRate"))
    sc = fixed.get("scroll") or {}
    if int(sc.get("during") or 0) != 0:
        fails.append("fixed 滚动期间仍有 zq_pos_v1 写入：%s" % sc.get("during"))
    if int(sc.get("afterSettle") or 0) < 1:
        fails.append("fixed 滚动停止后未落盘 zq_pos_v1：%s" % sc.get("afterSettle"))
    if fixed.get("errs") not in ("[]", None):
        fails.append("fixed 有 JS 报错：" + str(fixed.get("errs"))[:200])

    print("")
    if fails:
        for f in fails:
            print("[FAIL] " + f)
        print("v2_swipe_perf: FAIL %d" % len(fails))
        sys.exit(1)
    print("[PASS] fixed 手势跟手/帧率/滚动落盘指标达标（对比 baseline 已恢复同步直写手感）")
    print("v2_swipe_perf: PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
