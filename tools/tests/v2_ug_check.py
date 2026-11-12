# -*- coding: utf-8 -*-
"""v2.0.0 使用说明卡片化重构专项自检（__UG_CARDS_V1__）
覆盖：
  静态：卡片轮播结构 / 一键总览 / 上下一张 / 分类 chips / 11 个配图 symbol / 无 <p> / 零外部资源 /
        17 张卡片数据 / 滑动引擎排除 / .ugver 版本位 / APP_VER 不变；
  运行时（430×940 / 360×780 / 390×844 / 1280×900）：卡片数、页码、上一张/下一张、分类跳转、
        总览开关与跳转、键盘、Esc、无横向溢出、0 JS 报错、0 console.error、0 外部请求、不误切工具；
  截图：430 初始卡 / 430 总览 / 1280 桌面卡，落盘 tools/tests/_shots_ug/。

用法：cd C:\\...\\web\\tools && python tests\\v2_ug_check.py
      set V2UG_SRC=某副本.html
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
SRC = os.path.abspath(os.environ.get("V2UG_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8997
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_v2_ug_reports")
SHOT_DIR = os.path.join(HERE, "_shots_ug")
SID = "9999000005"
NAME = "测试同学"
BASE_TS = 1762000000000

DATA = {
    "members": [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
                 "role": "", "badge": "", "is_admin": False} for i in range(1, 71)],
    "notices": [], "homework": [], "marks": [], "fitrecs": [],
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
    if(s.indexOf("/notices")>=0)return ok(DATA.notices);
    if(s.indexOf("/homework")>=0)return ok(DATA.homework);
    if(s.indexOf("/marks")>=0)return ok(DATA.marks);
    if(s.indexOf("/fitrecs")>=0)return ok(DATA.fitrecs);
    if(s.indexOf("/userdata")>=0)return ok([]);
    return ok([]);
  }
  if(s.indexOf("tt.json")>=0)return ok(DATA.tt);
  if(s.indexOf("/drop/presence")>=0)return ok({ok:true,stage:false,at:0});
  if(s.indexOf("/pptfiles/")>=0||s.indexOf("/drop/")>=0)return ok({ok:true});
  window.__external.push(s);
  return _f.apply(this,arguments);
};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
try{localStorage.removeItem("zq_pos_v1");}catch(e){}
})();
</script>
"""

HOOK = r"""
try{window.__ugtest={APP_VER:APP_VER,bootDone:function(){return __bootRefreshDone;},
  errs:function(){return window.__errs||[];},cerrs:function(){return window.__cerrs||[];},
  external:function(){return window.__external||[];},gotoTab:function(k){gotoTab(k);},
  curtab:function(){return CURTAB;}};}catch(e){}
"""

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
function txt(f,s){var e=q(f,s);return e?String(e.textContent||"").trim():"";}
function click(f,s){var e=q(f,s);if(!e)throw new Error("no element "+s);e.click();return e;}
function report(slot,data){
  data=data||{};data.slot=slot;
  try{var x=new XMLHttpRequest();x.open("POST","/_report?slot="+slot,false);
      x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(data));}catch(e){}
}
async function bootAt(w,h){
  var f=await mount(SRC,w,h), win=f.contentWindow;
  await waitCond(function(){return win.__ugtest&&win.__ugtest.bootDone&&win.__ugtest.bootDone();},15000);
  await sleep(600);
  return f;
}
"""

MAIN_JS = r"""
async function run(){
  var R={steps:[],shot:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    /* ===== 430：主交互 ===== */
    var f=await bootAt(430,940), w=f.contentWindow;
    w.__ugtest.gotoTab("ug");
    await sleep(500);
    var cards=qa(f,"#s-ug .ug-card");
    T("R1 430 下渲染 17 张卡片", cards.length===17, cards.length);
    T("R2 初始页码 1 / 17", txt(f,"#ugCount")==="1 / 17", txt(f,"#ugCount"));
    T("R3 初始「上一张」禁用、「下一张」可用", q(f,"#ugPrev").disabled===true && q(f,"#ugNext").disabled===false, "");
    T("R4 轮播容器可横滑（scrollWidth>clientWidth）", q(f,"#ugTrack").scrollWidth>q(f,"#ugTrack").clientWidth+10, "");
    T("R5 每张卡都有配图（svg use → #ugIco*）", qa(f,"#s-ug .ug-card .ug-hero svg use").length===17 &&
        qa(f,"#s-ug .ug-card .ug-hero svg use").every(function(u){return String(u.getAttribute("href")||"").indexOf("#ugIco")===0;}), 
        qa(f,"#s-ug .ug-card .ug-hero svg use").length);
    T("R6 每张卡有分类胶囊 + 3 条步骤 + 提示", qa(f,"#s-ug .ug-card .ug-pill").length===17 &&
        qa(f,"#s-ug .ug-card .ug-steps li").length===51 && qa(f,"#s-ug .ug-card .ug-tip").length===17, 
        qa(f,"#s-ug .ug-card .ug-steps li").length);

    click(f,"#ugNext"); await sleep(120);
    T("R7 点「下一张」→ 2 / 17", txt(f,"#ugCount")==="2 / 17", txt(f,"#ugCount"));
    click(f,"#ugPrev"); await sleep(120);
    T("R8 点「上一张」→ 1 / 17 且上一张再次禁用", txt(f,"#ugCount")==="1 / 17" && q(f,"#ugPrev").disabled===true, txt(f,"#ugCount"));

    var chips=qa(f,"#s-ug .ug-cat");
    T("R9 分类 chips 5 个且存在 on 态", chips.length===5 && qa(f,"#s-ug .ug-cat.on").length===1, chips.length);
    click(f,'#s-ug .ug-cat[data-cat="life"]'); await sleep(160);
    T("R10 点「生活」→ 跳到第 11 张（宿舍电费）", txt(f,"#ugCount")==="11 / 17", txt(f,"#ugCount"));
    T("R11 当前分类高亮跟随（生活 on）", q(f,'#s-ug .ug-cat[data-cat="life"]').classList.contains("on"), "");

    click(f,"#ugOvBtn"); await sleep(160);
    T("R12 一键总览打开", q(f,"#ugOv").classList.contains("on"), "");
    T("R13 总览含 17 个条目 / 5 个分组", qa(f,"#ugOv .ug-ov-row").length===17 && qa(f,"#ugOv .ug-ov-grp").length===5,
        qa(f,"#ugOv .ug-ov-row").length+"/"+qa(f,"#ugOv .ug-ov-grp").length);
    click(f,'#ugOv .ug-ov-row[data-i="3"]'); await sleep(260);
    T("R14 点总览条目 → 关闭并跳到第 4 张", !q(f,"#ugOv").classList.contains("on") && txt(f,"#ugCount")==="4 / 17",
        txt(f,"#ugCount"));

    var kd=f.contentDocument; 
    function key(k){var e=new w.KeyboardEvent("keydown",{key:k,bubbles:true,cancelable:true});kd.dispatchEvent(e);}
    key("ArrowRight"); await sleep(160);
    T("R15 → 键切到下一张（5 / 17）", txt(f,"#ugCount")==="5 / 17", txt(f,"#ugCount"));
    key("ArrowLeft"); await sleep(160);
    T("R16 ← 键切回上一张（4 / 17）", txt(f,"#ugCount")==="4 / 17", txt(f,"#ugCount"));
    click(f,"#ugOvBtn"); await sleep(120); key("Escape"); await sleep(160);
    T("R17 Esc 关闭总览", !q(f,"#ugOv").classList.contains("on"), "");

    /* R29/R30：关闭总览不误触「再按一次返回退出」；浏览器返回键先关总览 */
    click(f,"#ugOvBtn"); await sleep(150);
    click(f,"#ugOvClose"); await sleep(360);
    var toastTxt=String((q(f,"#toast")&&q(f,"#toast").textContent)||"");
    T("R29 关闭总览不误弹「再按一次返回退出」", toastTxt.indexOf("再按一次")<0, toastTxt);
    var cntBefore=txt(f,"#ugCount");
    click(f,"#ugOvBtn"); await sleep(150);
    f.contentWindow.history.back(); await sleep(460);
    T("R30 浏览器返回键先关总览、不切走页面", !q(f,"#ugOv").classList.contains("on") && w.__ugtest.curtab()==="ug",
        w.__ugtest.curtab()+"/"+txt(f,"#ugCount"));
    T("R31 返回键关总览后页码不变", txt(f,"#ugCount")===cntBefore, txt(f,"#ugCount"));
    var shortBtns=qa(f,"#s-ug button").filter(function(b){var r=b.getBoundingClientRect();return r.height>0&&r.height<39.5;});
    T("R32 #s-ug 内按钮点按高度均 ≥40px（含 5 个分类 chips）", shortBtns.length===0,
        shortBtns.map(function(b){return (b.id||b.className)+":"+Math.round(b.getBoundingClientRect().height);}).join(","));

    T("R18 不误切工具（仍为 ug）", w.__ugtest.curtab()==="ug", w.__ugtest.curtab());
    T("R19 .ugver 显示版本 2.0.0", txt(f,"#s-ug .ugver").indexOf("2.0.0")>=0, txt(f,"#s-ug .ugver"));
    T("R20 0 JS 报错", (w.__ugtest.errs()||[]).length===0, JSON.stringify(w.__ugtest.errs()).slice(0,240));
    T("R21 0 console.error", (w.__ugtest.cerrs()||[]).length===0, JSON.stringify(w.__ugtest.cerrs()).slice(0,240));
    T("R22 0 外部请求", (w.__ugtest.external()||[]).length===0, JSON.stringify(w.__ugtest.external()).slice(0,240));

    /* ===== 多宽度：无横向溢出 ===== */
    for (var i=0;i<3;i++){
      var W=[360,390,430][i], H=W===360?780:844;
      var f2=await bootAt(W,H);
      f2.contentWindow.__ugtest.gotoTab("ug");
      await sleep(420);
      var de=f2.contentDocument.documentElement, win2=f2.contentWindow;
      var ovf=Math.max(de.scrollWidth, f2.contentDocument.body.scrollWidth) - win2.innerWidth;
      T("R23-"+(i+1)+" "+W+" 宽无横向溢出", ovf<=1, "overflow="+ovf);
      T("R24-"+(i+1)+" "+W+" 宽卡片宽=容器宽", Math.abs(q(f2,"#s-ug .ug-card").getBoundingClientRect().width - q(f2,"#s-ug .ug-track").clientWidth)<=1.5, "");
      f2.parentNode.removeChild(f2);
    }

    /* ===== 1280：桌面 ===== */
    var fd=await bootAt(1280,900);
    fd.contentWindow.__ugtest.gotoTab("ug");
    await sleep(420);
    var deD=fd.contentDocument.documentElement;
    T("R25 1280 宽无横向溢出", deD.scrollWidth<=fd.contentWindow.innerWidth+1, deD.scrollWidth+"/"+fd.contentWindow.innerWidth);
    T("R26 1280 下内容限宽 ≤ 900px", q(fd,"#s-ug .ug-shell").getBoundingClientRect().width<=900.5, q(fd,"#s-ug .ug-shell").getBoundingClientRect().width);
    click(fd,"#ugOvBtn"); await sleep(200);
    T("R27 1280 下总览可开且条目 17", q(fd,"#ugOv").classList.contains("on") && qa(fd,"#ugOv .ug-ov-row").length===17, "");
    click(fd,"#ugOvClose"); await sleep(160);
    T("R28 1280 下总览可关", !q(fd,"#ugOv").classList.contains("on"), "");
    fd.parentNode.removeChild(fd);
  }catch(e){
    R.steps.push({k:"脚本异常",ok:false,note:String((e&&e.stack)||e)});
  }
  report("main",R);
  await pumpN(3);
}
run();
"""

STATIC_CHECKS = []


def section_slice(html):
    s = html.find('<section id="s-ug">')
    e = html.find('<div class="modal" id="ftTablePanel"', s)
    if s < 0 or e < 0:
        return ""
    return html[s:e]


def static_checks(html):
    out = []
    sec = section_slice(html)

    def add(k, ok, note=""):
        out.append({"k": k, "ok": bool(ok), "note": str(note)})

    add("S1 源码含 __UG_CARDS_V1__ 标记", "__UG_CARDS_V1__" in html)
    add("S2 #s-ug 已改为卡片轮播（ugTrack/ugOvBtn/ugPrev/ugNext）",
        all(x in sec for x in ('id="ugTrack"', 'id="ugOvBtn"', 'id="ugPrev"', 'id="ugNext"', 'id="ugCats"')))
    add("S3 一键总览弹层存在（#ugOv + 关闭按钮）",
        'id="ugOv"' in sec and 'id="ugOvClose"' in sec and 'id="ugOvList"' in sec)
    add("S4 11 个内联 SVG 配图 symbol", len(re.findall(r'<symbol id="ugIco[A-Za-z]+"', sec)) == 11,
        len(re.findall(r'<symbol id="ugIco[A-Za-z]+"', sec)))
    add("S5 #s-ug 内无 <p> 段落（保持克制说明）", len(re.findall(r"<p[\s>]", sec)) == 0, len(re.findall(r"<p[\s>]", sec)))
    add("S6 无外部脚本 / 字体 / 外链图片",
        "<script src=" not in html and "fonts.googleapis" not in html and "cdn." not in html
        and not re.search(r'<img[^>]+src="(https?:)?//', sec))
    add("S7 .ugver 版本位保留", 'class="ugver"' in sec)
    add("S8 APP_VER 仍为 2.0.0", 'var APP_VER="2.0.0"' in html)
    ug_block = ""
    m = re.search(r"var UG=\(function\(\)\{(.*?)\}\)\(\);", html, re.S)
    if m:
        ug_block = m.group(1)
    add("S9 卡片数据 17 张（UG CARDS）", ug_block.count('{id:"') == 17, ug_block.count('{id:"'))
    add("S10 分类 5 个（入门/学习/生活/协作/更多）",
        all(('k:"%s"' % k) in ug_block for k in ("start", "study", "life", "team", "more")))
    add("S11 场景 11 种映射齐全",
        all(('picks' in ug_block, 'steps' in ug_block, 'grid' in ug_block, 'list' in ug_block, 'chart' in ug_block,
             'people' in ug_block, 'transfer' in ug_block, 'ballot' in ug_block, 'droplet' in ug_block,
             'shield' in ug_block, 'slides' in ug_block)))
    add("S12 全局滑动引擎排除 #ugPager/#ugOv",
        '#ugPager")||closest(t,"#ugOv")' in html)
    add("S13 总览接入 history 返回键（openModal；手动关闭自行 pop 并抑制根层误提示）",
        'HIST.openModal("ugov"' in ug_block and "history.back()" in ug_block and "HIST._closing" in ug_block)
    add("S14 键盘 ← → / Esc 支持", 'ArrowRight' in ug_block and 'ArrowLeft' in ug_block and 'Escape' in ug_block)
    add("S15 上一张/下一张 disabled 首尾处理", "prevB.disabled" in ug_block and "nextB.disabled" in ug_block)
    add("S16 无旧 .ugsec/.uggrid 列表样式残留", ".ugsec" not in html and ".uggrid" not in html)
    add("S17 响应式断点存在（960 / 380）", "@media (min-width:960px)" in html and "@media (max-width:380px)" in html)
    add("S18 reduced-motion 降级", "prefers-reduced-motion:reduce" in html and ".ug-track{scroll-behavior:auto}" in html)
    add("S19 滑动跟手用 scroll-snap", "scroll-snap-type:x mandatory" in html and "scroll-snap-align:start" in html)
    add("S20 点按高度 ≥40px（总览按钮/上下一张 40+42）",
        "min-height:40px" in html and "min-height:42px" in html)
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


def build_preview():
    html = open(SRC, encoding="utf-8", newline="").read()
    idx = html.rfind("})();")
    if idx < 0:
        raise SystemExit("[v2_ug_check] 找不到主脚本结尾锚点")
    html = html[:idx] + HOOK.replace("\n", "\r\n") + "\r\n" + html[idx:]
    mock = MOCK_JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")) \
                  .replace("__SID__", SID).replace("__NAME__", NAME)
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    return html.replace("<head>", "<head>" + mock, 1)


def run_edge(url, budget=30000, timeout=240, screenshot=None, win=None):
    prof = tempfile.mkdtemp(prefix="edgeprof_ug_", dir=REPORT_DIR)
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=%s" % (win or "492,940"),
            "--virtual-time-budget=%d" % budget]
    if screenshot:
        args.append("--screenshot=" + screenshot)
    args.append(url)
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        shutil.rmtree(prof, ignore_errors=True)


SHOT_JS = r"""
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
async function waitCond(fn,maxTries){for(var i=0;i<(maxTries||600);i++){var v=false;try{v=!!fn();}catch(e){v=false;}if(v)return true;await sleep(60);}return false;}
(async function(){
  try{
    var qs=new URLSearchParams(location.search);
    var w=parseInt(qs.get("w")||"430",10), h=parseInt(qs.get("h")||"940",10);
    var ov=qs.get("ov")==="1";
    var f=document.createElement("iframe");
    f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block;margin:0 auto;background:#fff";
    f.src="preview.html";
    document.body.appendChild(f);
    await new Promise(function(res){var done=false;f.onload=function(){if(!done){done=true;setTimeout(res,60);}};setTimeout(function(){if(!done){done=true;res();}},9000);});
    var win=f.contentWindow;
    await waitCond(function(){return win&&win.__ugtest&&win.__ugtest.bootDone&&win.__ugtest.bootDone();});
    await sleep(500);
    try{win.__ugtest.gotoTab("ug");}catch(e){}
    await sleep(700);
    if(ov){try{f.contentDocument.getElementById("ugOvBtn").click();}catch(e){} await sleep(500);}
    if(qs.get("chip")){try{f.contentDocument.querySelector('#s-ug .ug-cat[data-cat="'+qs.get("chip")+'"]').click();}catch(e){} await sleep(500);}
    document.title="ready";
  }catch(e){document.title="err:"+e;}
})();
"""


def build_shot(html):
    body = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 ug shot</title>"
            "<style>html,body{margin:0;background:#F7F8F8}</style></head><body>"
            "<script>" + SHOT_JS + "</script></body></html>")
    return body


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    os.makedirs(SHOT_DIR, exist_ok=True)
    raw = open(SRC, encoding="utf-8", newline="").read()
    results = static_checks(raw)
    tmp = tempfile.mkdtemp(prefix="v2ug_")
    srv = None
    try:
        preview = build_preview()
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(preview)
        body = COMMON_JS + "\n" + MAIN_JS
        harness = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 ug check</title>"
                   "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
                   "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
        open(os.path.join(tmp, "harness.html"), "w", encoding="utf-8", newline="").write(harness)
        open(os.path.join(tmp, "shot.html"), "w", encoding="utf-8", newline="").write(build_shot(preview))
        os.chdir(tmp)
        srv = Q(("127.0.0.1", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run_edge(BASE + "harness.html", budget=40000, win="430,940")
        p = os.path.join(REPORT_DIR, "main.json")
        data = None
        t0 = time.time()
        while time.time() - t0 < 30:
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
        # 截图
        shots = [
            ("01_mobile_430.png", "w=430&h=940", "430,940"),
            ("02_mobile_430_overview.png", "w=430&h=940&ov=1", "430,940"),
            ("03_mobile_430_life.png", "w=430&h=940&chip=life", "430,940"),
            ("04_desktop_1280.png", "w=1280&h=900", "1300,940"),
        ]
        for name, qs, win in shots:
            out = os.path.join(SHOT_DIR, name)
            try:
                if os.path.exists(out):
                    os.remove(out)
            except Exception:
                pass
            run_edge(BASE + "shot.html?" + qs, budget=20000, win=win, screenshot=out, timeout=120)
            print("[shot] %s -> %s" % (name, "OK" if os.path.exists(out) else "MISSING"))
        passed = 0
        for s in results:
            if s["ok"]:
                passed += 1
            print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + str(s["note"])) if s.get("note") else ""))
        total = len(results)
        print("=" * 64)
        print("v2_ug_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
        print("=" * 64)
        sys.exit(0 if total and passed == total else 1)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
