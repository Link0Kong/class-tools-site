# -*- coding: utf-8 -*-
"""v2 专项自检 4/4：版本号与克制动效（需求 1 / 13）

覆盖：
  需求1：`var APP_VER="2.0.0"`；身份页页脚与「使用说明」页展示版本（克制，无说明段）；
  需求13：切页/步骤/卡片/弹层动效统一 `.22–.32s cubic-bezier(.2,.8,.3,1)`（CSS 变量 --ui-dur/--ui-ease）；
          `prefers-reduced-motion` 降级；不改品牌/版式（无新增说明文字）。

用法：cd C:\\...\\web\\tools && python tests\\v2_ui_check.py
      set V2U_SRC=某副本.html
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
SRC = os.path.abspath(os.environ.get("V2U_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8991
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_v2_ui_reports")
SID = "9999000005"
NAME = "测试同学"
AN_PREFIX = "[[CLASS_NOTICE_V1]]"
BASE_TS = 1762000000000

DATA = {
    "members": [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
                 "role": "", "badge": "", "is_admin": False} for i in range(1, 71)],
    "notices": [{"id": "auto_g_ui", "title": "",
                 "body": AN_PREFIX + json.dumps({"id": "g_ui", "cat": "教务", "title": "合成通知",
                                                 "group": "合成群", "summary": "", "items": [],
                                                 "aiSummary": "", "aiPoints": []}, ensure_ascii=False),
                 "archived": False, "hidden": False, "override_json": "", "edited_at": 0, "ts": BASE_TS}],
    "homework": [], "marks": [], "fitrecs": [],
    "tt": {"c": [], "t": "2026-08-31", "meta": {"fetchedAt": BASE_TS}},
}

MOCK_JS = r"""
<script>
(function(){
window.__errs=[];window.__cerrs=[];window.__external=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var DATA=__DATA__;
function ok(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};var s=String((u&&u.url!==undefined)?u.url:u);
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0)return ok(DATA.members);
    if(s.indexOf("/notices")>=0)return ok(s.indexOf("select=id,ts")>=0?DATA.notices.map(function(r){return {id:r.id,ts:r.ts,hidden:!!r.hidden,edited_at:Number(r.edited_at)||0};}):DATA.notices);
    if(s.indexOf("/homework")>=0)return ok(DATA.homework);
    if(s.indexOf("/marks")>=0)return ok(DATA.marks);
    if(s.indexOf("/fitrecs")>=0)return ok(DATA.fitrecs);
    if(s.indexOf("/userdata")>=0)return ok([]);
    return ok([]);
  }
  if(s.indexOf("tt.json")>=0)return ok(DATA.tt);
  window.__external.push(s);
  return _f.apply(this,arguments);
};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
})();
</script>
"""

HOOK = r"""
window.__v2ui={APP_VER:APP_VER,bootDone:function(){return __bootRefreshDone;},
  errs:function(){return window.__errs||[];},cerrs:function(){return window.__cerrs||[];},
  external:function(){return window.__external||[];}};
"""


def build_preview():
    html = open(SRC, encoding="utf-8", newline="").read()
    idx = html.rfind("})();")
    if idx < 0:
        raise SystemExit("[v2_ui_check] 找不到主脚本结尾锚点")
    html = html[:idx] + HOOK + "\r\n" + html[idx:]
    mock = MOCK_JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")) \
                  .replace("__SID__", SID).replace("__NAME__", NAME)
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    return html.replace("<head>", "<head>" + mock, 1)


COMMON_JS = r"""
var SRC="preview.html";
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
function pump(){return new Promise(function(res){try{var ch=new MessageChannel();ch.port1.onmessage=function(){res();};ch.port2.postMessage(0);}catch(e){setTimeout(res,0);}});}
async function pumpN(n){for(var i=0;i<(n||1);i++)await pump();}
async function waitCond(fn,maxTries){var n=maxTries||8000;for(var i=0;i<n;i++){var v=false;try{v=!!fn();}catch(e){v=false;}if(v)return true;await pump();}return false;}
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
function cs(f,sel,prop){return f.contentWindow.getComputedStyle(q(f,sel))[prop];}
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
  function durInRange(s,lo,hi){
    var m=String(s||"").match(/([0-9.]+)s/g)||[];
    return m.some(function(x){var v=parseFloat(x);return v>=lo-0.001&&v<=hi+0.001;});
  }
  try{
    var f=await mount(SRC,430,940), w=f.contentWindow;
    await waitCond(function(){return w.__v2ui&&w.__v2ui.bootDone&&w.__v2ui.bootDone();},15000);
    await sleep(900); /* 等 renderTabs 的临时内联过渡清掉 */
    await pumpN(4);

    /* A. 需求1：版本号 */
    T("A1 APP_VER=2.0.0", w.__v2ui.APP_VER==="2.0.0", w.__v2ui.APP_VER);
    var idfoot=q(f,".idfoot"), idver=q(f,".idfoot .idver");
    T("A2 身份页页脚展示版本", !!idver&&String(idver.textContent).indexOf("2.0.0")>=0, idver?String(idver.textContent):"");
    T("A3 身份页页脚文案保持克制（无新增说明段）", !!idfoot&&String(idfoot.textContent).replace(/\s+/g,"").length<60, idfoot?String(idfoot.textContent).length:0);
    var ug=q(f,"#s-ug .ugver");
    T("A4 使用说明页展示版本", !!ug&&String(ug.textContent).indexOf("2.0.0")>=0, ug?String(ug.textContent):"");
    T("A5 使用说明页无新增说明段落", qa(f,"#s-ug p").length===0, qa(f,"#s-ug p").length);

    /* B. 需求13：统一克制动效 */
    T("B1 CSS 动效 token 已定义（.26s / cubic-bezier(.2,.8,.3,1)）",
      String(w.getComputedStyle(f.contentDocument.documentElement).getPropertyValue("--ui-dur")).trim()===".26s" &&
      String(w.getComputedStyle(f.contentDocument.documentElement).getPropertyValue("--ui-ease")).trim()==="cubic-bezier(.2,.8,.3,1)",
      "");
    var sec=cs(f,"#s-draw","animationName"), stp=cs(f,".stpane.on","animationName");
    T("B2 切页不再用 fade 动画（animationName=none，切页视觉交给 fly）", sec=="none", sec);
    T("B3 步骤切换不再用 fade 动画（animationName=none）", stp=="none", stp);
    var modalDur=cs(f,"#ntModal","transitionDuration");
    T("B4 通知弹层过渡在 .22–.32s 区间", durInRange(modalDur,0.22,0.32), modalDur);
    var tabDur=cs(f,".tabs button","transitionDuration");
    T("B5 工具栏按钮过渡使用 .22s（--ui-dur-fast）", String(tabDur).indexOf("0.22s")>=0, tabDur);
    var itemDur=cs(f,"#s-draw .card","transitionDuration");
    T("B6 卡片/列表状态过渡使用统一 token", String(itemDur).indexOf("0.22s")>=0, itemDur);
    T("B7 品牌/版式未改（品牌区与标题存在）", !!q(f,".brand")&&!!q(f,".brand b"), "");

    /* C. reduced-motion 降级：规则存在性由静态检查（S8–S12）覆盖，
         运行时生效由 v2_scroll_check 的 Emulation.setEmulatedMedia 覆盖。 */

    /* D. 0 JS 报错 / 无外部请求 */
    T("D1 0 JS 报错", (w.__v2ui.errs()||[]).length===0, JSON.stringify(w.__v2ui.errs()).slice(0,300));
    T("D2 0 console.error", (w.__v2ui.cerrs()||[]).length===0, JSON.stringify(w.__v2ui.cerrs()).slice(0,300));
    T("D3 无外部请求", (w.__v2ui.external()||[]).length===0, JSON.stringify(w.__v2ui.external()).slice(0,300));
  }catch(e){
    R.steps.push({k:"脚本异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("main",R);
  await pumpN(3);
}
run();
"""

STATIC_CHECKS = []


def static_checks(html):
    main = re.findall(r"<script>(.*?)</script>", html, re.S)[-1]
    slim = re.sub(r'var NOTICE_TPL_B64="[^"]*"', 'var NOTICE_TPL_B64="";', main)
    out = []

    def has(pat, label):
        out.append({"k": label, "ok": bool(re.search(pat, slim if "<" not in pat else html)), "note": ""})

    out.append({"k": "S1 源码有 var APP_VER=\"2.0.0\"", "ok": 'var APP_VER="2.0.0"' in slim, "note": ""})
    out.append({"k": "S2 源码有 --ui-dur:.26s 变量", "ok": "--ui-dur:.26s" in html, "note": ""})
    out.append({"k": "S3 源码有 --ui-ease:cubic-bezier(.2,.8,.3,1)", "ok": "--ui-ease:cubic-bezier(.2,.8,.3,1)" in html, "note": ""})
    out.append({"k": "S4 fly() 动效使用统一 token", "ok": 'var(--ui-dur-fast)' in html and "armAnimFail" in slim, "note": ""})
    out.append({"k": "S5 身份页页脚含 idver 版本位", "ok": 'class="idver"' in html and "班级工具 v2.0.0" in html, "note": ""})
    out.append({"k": "S6 使用说明页含 ugver 版本位", "ok": 'class="ugver"' in html, "note": ""})
    out.append({"k": "S7 无外部脚本/字体引用", "ok": "<script src=" not in html and "fonts.googleapis" not in html and "cdn." not in html, "note": ""})
    flat = re.sub(r"\s+", "", html)
    out.append({"k": "S8 prefers-reduced-motion 媒体查询存在", "ok": "@media(prefers-reduced-motion:reduce)" in flat, "note": ""})
    out.append({"k": "S9 已移除 fade 关键帧/切页 opacity 动画", "ok": "@keyframesfade" not in flat and "animation:fade" not in flat and "zq-flying" not in flat, "note": ""})
    out.append({"k": "S10 reduced-motion 关闭通知弹层过渡", "ok": ".nt-modal,.nt-modal-card" in flat and "transition:none!important" in flat, "note": ""})
    out.append({"k": "S11 reduced-motion 关闭工具栏滑块过渡", "ok": ".tabs-thumb{transition:none!important}" in flat, "note": ""})
    out.append({"k": "S12 reduced-motion 关闭骨架动画", "ok": ".skel-line{animation:none}" in flat, "note": ""})
    return out


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


def run_edge(url, budget=30000, timeout=240):
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
    raw = open(SRC, encoding="utf-8", newline="").read()
    results = static_checks(raw)
    tmp = tempfile.mkdtemp(prefix="v2ui_")
    srv = None
    try:
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(build_preview())
        body = COMMON_JS + "\n" + MAIN_JS
        harness = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 ui check</title>"
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
        while time.time() - t0 < 20:
            if os.path.exists(p):
                time.sleep(0.2)
                try:
                    data = json.load(open(p, encoding="utf-8"))
                    break
                except Exception:
                    time.sleep(0.3)
            time.sleep(0.2)
        if data:
            results = results + data.get("steps", [])
        passed = 0
        for s in results:
            if s["ok"]:
                passed += 1
            print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + str(s["note"])) if s.get("note") else ""))
        total = len(results)
        print("=" * 60)
        print("v2_ui_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
        print("=" * 60)
        sys.exit(0 if total and passed == total else 1)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
