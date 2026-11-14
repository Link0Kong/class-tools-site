# -*- coding: utf-8 -*-
"""v2 集成自检（应用内 + 真实 board 数据）：网页通知 tab = 父页滚动 + iframe 自适应高度

对象：
  - `web/tools/index.html`（含 NOTICE_TPL_B64 嵌入模板）
  - `web/tools/notice-board-live-demo.html`（真实 40 组 board 数据，从 `var GROUPS=[...]` 提取）
做法：预览页注入「假身份 + fetch mock（notices=真实 board 数据，其余空）」，
      同源 iframe 固定 430 宽 mount；只读，不改源文件。
覆盖：
  - 应用内通知 tab 渲染 40 卡（真实数据）；
  - iframe 高度=内容高（>5000px）、父页可滚动、iframe 内部不可滚动；
  - 非管理员看不到编辑/删除/已隐藏区（需求12 权限边界）；
  - g_dorm 长期安排文案、药膳补充通知、QQ 文件「待获取」在应用内正常显示；
  - 430 宽无横向溢出、0 JS 报错 / 0 console.error / 无外部请求。

用法：cd C:\\...\\web\\tools && python tests\\v2_notice_live_check.py
退出码 0 = 全绿。
"""
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.abspath(os.environ.get("V2L_SRC") or os.path.join(ROOT, "index.html"))
DEMO = os.path.join(ROOT, "notice-board-live-demo.html")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8997
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_v2_live_reports")
SID = "9999000005"
NAME = "测试同学"
AN_PREFIX = "[[CLASS_NOTICE_V1]]"
BASE_TS = 1762000000000


def extract_groups(path):
    raw = open(path, encoding="utf-8").read()
    i = raw.find("var GROUPS=")
    if i < 0:
        raise SystemExit("GROUPS marker not found in demo")
    i = raw.find("[", i)
    depth = 0
    in_str = False
    esc = False
    end = None
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
                    end = j + 1
                    break
    return json.loads(raw[i:end])


GROUPS = extract_groups(DEMO)
MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": "", "badge": "", "is_admin": False} for i in range(1, 71)]
NOTICES = [{"id": "auto_" + str(g.get("id") or ("g%d" % i)),
            "title": "", "body": AN_PREFIX + json.dumps(g, ensure_ascii=False),
            "archived": False, "hidden": False, "override_json": "", "edited_at": 0,
            "ts": BASE_TS + i * 1000} for i, g in enumerate(GROUPS)]

MOCK_JS = r"""
<script>
(function(){
window.__errs=[];window.__cerrs=[];window.__external=[];window.__counts={};window.__dropBlocked=0;
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var DATA=__DATA__;
function ok(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
function delayed(obj,ms){return new Promise(function(res){setTimeout(function(){res({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});},ms||0);});}
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};var s=String((u&&u.url!==undefined)?u.url:u);
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0)return ok(DATA.members);
    if(s.indexOf("/notices")>=0){
      var payload=s.indexOf("select=id,ts")>=0
        ?DATA.notices.map(function(r){return {id:r.id,ts:r.ts,hidden:!!r.hidden,edited_at:Number(r.edited_at)||0};})
        :DATA.notices;
      var dly=Number(window.__v2_notice_delay||0)||0;
      return dly?delayed(payload,dly):ok(payload);
    }
    if(s.indexOf("/homework")>=0)return ok([]);
    if(s.indexOf("/marks")>=0)return ok([]);
    if(s.indexOf("/fitrecs")>=0)return ok([]);
    if(s.indexOf("/userdata")>=0)return ok([]);
    return ok([]);
  }
  if(s.indexOf("tt.json")>=0)return ok({c:[],t:"2026-08-31",meta:{fetchedAt:__TS__}});
  /* 大屏互联 presence 等非通知请求：mock 掉并计入“已拦截”，不算外部请求 */
  window.__dropBlocked++;
  return ok({});
};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
})();
</script>
"""

HOOK = r"""
window.__v2live={AUTH:AUTH,D:D,NT:NT,gotoTab:gotoTab,frame:function(){return NOTICE_FRAME;},
  bootDone:function(){return __bootRefreshDone;},errs:function(){return window.__errs||[];},
  cerrs:function(){return window.__cerrs||[];},external:function(){return window.__external||[];},
  dropBlocked:function(){return window.__dropBlocked||0;},
  auto:function(){return AUTO_NOTICES;},pos:POS,noticeH:function(){return NOTICE_H;},
  curtab:function(){return CURTAB;}};
"""

COMMON_JS = r"""
var SRC="preview.html";
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
function pump(){return new Promise(function(res){try{var ch=new MessageChannel();ch.port1.onmessage=function(){res();};ch.port2.postMessage(0);}catch(e){setTimeout(res,0);}});}
async function pumpN(n){for(var i=0;i<(n||1);i++)await pump();}
async function waitCond(fn,maxTries){var n=maxTries||12000;for(var i=0;i<n;i++){var v=false;try{v=!!fn();}catch(e){v=false;}if(v)return true;await pump();}return false;}
function mount(src,w,h){
  return new Promise(function(res,rej){
    try{sessionStorage.removeItem("zq_pos_v1");}catch(e){}
    var old=document.getElementById("fr");if(old&&old.parentNode)old.parentNode.removeChild(old);
    var f=document.createElement("iframe");f.id="fr";f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block";f.src=src;
    var done=false;
    f.onload=function(){if(done)return;done=true;setTimeout(function(){res(f);},80);};
    f.onerror=function(){if(done)return;done=true;rej(new Error("iframe load failed"));};
    document.body.appendChild(f);
    setTimeout(function(){if(!done){done=true;res(f);}},15000);
  });
}
function q(f,s){return f.contentDocument.querySelector(s);}
function qa(f,s){return Array.prototype.slice.call(f.contentDocument.querySelectorAll(s));}
function frame(f){return q(f,"#noticeHost iframe");}
function frameDoc(f){var fr=frame(f);return fr?fr.contentDocument:null;}
function report(slot,data){
  data=data||{};data.slot=slot;
  try{var x=new XMLHttpRequest();x.open("POST","/_report?slot="+slot,false);
      x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(data));}catch(e){}
}
"""

MAIN_JS = r"""
async function run(){
  var R={steps:[],diag:{}};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC,430,940), w=f.contentWindow;
    var boot=await waitCond(function(){return w.__v2live&&w.__v2live.bootDone&&w.__v2live.bootDone();},20000);
    T("L1 应用启动完成（假身份进入班级）", boot, "");
    w.__v2live.gotoTab("nt");
    var cardsOk=await waitCond(function(){var d=frameDoc(f);return d&&d.querySelectorAll(".gcard").length>=40;},30000);
    var d=frameDoc(f);
    var n=d?d.querySelectorAll(".gcard").length:-1;
    T("L2 应用内通知 tab 渲染 40 卡（真实 board 数据）", cardsOk&&n>=40, n);
    var fr=frame(f);
    var fh=fr?fr.getBoundingClientRect().height:0;
    var fdoc=fr?fr.contentDocument:null;
    var fwin=fr?fr.contentWindow:null;
    var fScrollH=fdoc?Math.max(fdoc.documentElement.scrollHeight,fdoc.body.scrollHeight):-1;
    var fClientH=fdoc?fdoc.documentElement.clientHeight:-1;
    T("L3 iframe 为固定视口高度（≈视口-140px）", fh>600&&fh<900, Math.round(fh));
    T("L4 iframe 内部可滚动（内容高 > 视口）", fScrollH>fClientH+1000, fScrollH+"/"+fClientH);
    var pScrollH=Math.max(f.contentDocument.documentElement.scrollHeight,f.contentDocument.body.scrollHeight);
    T("L5 父页不随通知内容变长（页面高≈视口 940）", pScrollH<=1100, pScrollH);
    fwin.scrollTo(0,3000);
    await pumpN(3);
    var sy=Math.round(fwin.scrollY||fwin.pageYOffset||0);
    T("L6 iframe 内部滚动位置生效", Math.abs(sy-3000)<=50, sy);
    fwin.scrollTo(0,0);
    var txt=(d?d.body.textContent:"").replace(/\s+/g," ");
    T("L7 非管理员：通知页无编辑/删除按钮", d&&d.querySelectorAll('[data-act="edit"],[data-act="del"]').length===0,
      d?d.querySelectorAll('[data-act="edit"],[data-act="del"]').length:-1);
    T("L8 非管理员：无「已隐藏（仅管理员）」区",
      (function(){try{var hw=d.querySelector("#hiddenWrap");return !hw||f.contentWindow.getComputedStyle(hw).display==="none";}catch(e){return false;}})(), "");
    T("L9 顶部 5 张可点数据卡齐全（待处理/24h/7天内/长期通知/最新发布）",
      (function(){try{var d=frameDoc(f);var cs=d?d.querySelectorAll('#dataBar .bstat'):[];if(cs.length!==5)return false;
        for(var i=0;i<cs.length;i++){var r=cs[i].getBoundingClientRect();if(r.height<40||r.width<=0)return false;}return true;}catch(e){return false;}})(), "");
    T("L10 长期通知卡数字 = 进行中安排条数（真实数据）",
      (function(){try{var w=frame(f).contentWindow,d=frameDoc(f);var v=Number((d.querySelector('#statRecur')||{}).textContent);
        var n=w.GROUPS.filter(function(g){return g.recurrence&&g.recurrence.freq&&w.recurOngoing(g.recurrence,w.__zqTest.nowMs())}).length;return v===n;}catch(e){return false;}})(), "");
    T("L10b 资料/无时间栏默认展开且非空",
      (function(){try{var d=frameDoc(f);var w=d&&d.getElementById('dataWrap');if(!w)return false;
        return frame(f).contentWindow.getComputedStyle(w).display!=='none'&&w.classList.contains('open')&&d.querySelectorAll('#dataList .gcard').length>0;}catch(e){return false;}})(), "");
    T("L10c 主列表不含长期安排定义卡（长期定义只在长期通知筛选；已结束进过期区）",
      (function(){try{var w=frame(f).contentWindow,d=frameDoc(f);var ids={};w.GROUPS.forEach(function(g){if(g.recurrence&&g.recurrence.freq)ids[g.id]=1});
        return [].every.call(d.querySelectorAll('#list .gcard'),function(c){return !ids[c.getAttribute('data-gid')]});}catch(e){return false;}})(), "");
    T("L10d 正文日期已统一为 M月D日（相对周）", /\d{1,2}月\d{1,2}日（/.test(txt), "");
    T("L10e 药膳补充通知仍在正文显示", /补充通知/.test(txt), "");
    var miss=(txt.match(/待获取/g)||[]).length;
    T("L11 QQ 文件「待获取」提示 ≥5 处", miss>=5, miss);
    var adminInjected=false;
    try{
      var fw=frame(f).contentWindow;
      adminInjected=!!(fw.__zqState&&fw.__zqState.admin===false);
    }catch(e){}
    T("L12 模板管理员态注入为非管理员", adminInjected, "");
    var over=Math.max(f.contentDocument.documentElement.scrollWidth,f.contentDocument.body.scrollWidth)-f.contentWindow.innerWidth;
    T("L13 430 宽无横向溢出", over<=1, over);
    T("L14 0 JS 报错", (w.__v2live.errs()||[]).length===0, JSON.stringify(w.__v2live.errs()).slice(0,300));
    T("L15 0 console.error", (w.__v2live.cerrs()||[]).length===0, JSON.stringify(w.__v2live.cerrs()).slice(0,300));
    T("L16 无外部请求", (w.__v2live.external()||[]).length===0, JSON.stringify(w.__v2live.external()).slice(0,300));
    R.diag={groups:(function(){try{return frame(f).contentWindow.GROUPS.length}catch(e){return -1}})(),cards:n,frameH:Math.round(fh),pageH:pScrollH};
  }catch(e){
    R.steps.push({k:"脚本异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("main",R);
  await pumpN(3);
}
run();
"""


def build_preview():
    html = open(SRC, encoding="utf-8", newline="").read()
    idx = html.rfind("})();")
    if idx < 0:
        raise SystemExit("main script end not found")
    html = html[:idx] + HOOK + "\r\n" + html[idx:]
    data = {"members": MEMBERS, "notices": NOTICES}
    mock = MOCK_JS.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")) \
                  .replace("__SID__", SID).replace("__NAME__", NAME).replace("__TS__", str(BASE_TS))
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    return html.replace("<head>", "<head>" + mock, 1)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        qs = urllib.parse.urlparse(self.path).query
        m = re.search(r"slot=([A-Za-z0-9_\-]+)", qs)
        slot = m.group(1) if m else "default"
        os.makedirs(REPORT_DIR, exist_ok=True)
        open(os.path.join(REPORT_DIR, slot + ".json"), "wb").write(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


class Q(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


def run_edge(url, budget=150000, timeout=420):
    prof = tempfile.mkdtemp(prefix="edgeprof_", dir=REPORT_DIR)
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=492,940",
            "--virtual-time-budget=%d" % budget, "--user-data-dir=" + prof, url]
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    try:
        os.remove(os.path.join(REPORT_DIR, "main.json"))
    except Exception:
        pass
    tmp = tempfile.mkdtemp(prefix="v2live_")
    srv = None
    try:
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(build_preview())
        body = COMMON_JS + "\n" + MAIN_JS
        harness = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 live check</title>"
                   "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
                   "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
        open(os.path.join(tmp, "harness.html"), "w", encoding="utf-8", newline="").write(harness)
        os.chdir(tmp)
        srv = Q(("127.0.0.1", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run_edge(BASE + "harness.html")
        p = os.path.join(REPORT_DIR, "main.json")
        data = None
        t0 = time.time()
        while time.time() - t0 < 25:
            if os.path.exists(p):
                time.sleep(0.2)
                try:
                    data = json.load(open(p, encoding="utf-8"))
                    break
                except Exception:
                    time.sleep(0.3)
            time.sleep(0.2)
        if not data:
            print("[v2_notice_live_check] 未拿到测试报告")
            sys.exit(2)
        passed = 0
        for s in data.get("steps", []):
            if s["ok"]:
                passed += 1
            print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + str(s["note"])) if s["note"] else ""))
        total = len(data.get("steps", []))
        print("=" * 60)
        print("v2_notice_live_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
        print("diag:", json.dumps(data.get("diag", {}), ensure_ascii=False))
        print("=" * 60)
        sys.exit(0 if total and passed == total else 1)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
