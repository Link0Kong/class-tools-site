# -*- coding: utf-8 -*-
"""v2.0.0 「教务」链接型工具（__JW_ENTRY_V1__，增量 55：点卡片直接进入）专项自检
契约：_audit/jw_entry_20261113/CONTRACT.md §5.0/§5.1/§5.2（2026-11-13 21:38 用户新要求）
覆盖：
  静态：中间入口页已删除（#s-jw / jwOpen / jwCopy / 旧 CSS / BEGIN-END 标记全无）/ TOOLS jw 含 url 且末尾 /
        ALL_TONE.jw 保留 / 新 JS 块（JW_URL / isLinkTool / openJwDirect / firstPageTab / window.JW 只读探针）
        在主 IIFE 内且无定时器无网络请求 / gotoTab 包装 / <a target=_blank rel=noopener noreferrer> click +
        location.href 兜底 / 滑动引擎 targetFor 跳过链接型工具（STEP 边界同函数）/ 卡片按钮「进入」/
        恢复路径（POS / popstate / renderTabs）不落到链接型工具 / UG jw 卡逐字文案 /
        APP_VER 不变 / 零外部资源 / 全 HTML 仅 2 处教务 URL / 不采集账号密码；
  运行时（430×940 / 360×780 / 390×844 / 1280×900，mock anchor click / window.open 不真实导航）：
        两条用户路径（「全部」页点 jw 卡；顶部工具栏 jw tab）都直接触发打开（href/target/rel 正确）且
        不切页（CURTAB / section.on / history 不变）；程序化 gotoTab("jw") 同路径；isLinkTool('jw')===true；
        window.JW 只读探针；POS 恢复旧数据 tab=jw 不会无手势打开外站；0 JS 报错 / 0 console.error /
        0 外部请求（不请求 210.34.74.77 / authserver）；无横向溢出；
  截图：430/360/390/1280 全部页 jw 卡 + 430 顶部工具栏含教务 tab，落盘 tools/tests/_shots_jw/。

测试身份：SID=9999000005 / NAME=测试同学（9999 段 mock 身份，符合 AGENTS.md §0-7）。
用法：cd C:\\...\\web\\tools && python tests\\v2_jw_check.py
      set V2JW_SRC=某副本.html
退出码 0 = 全绿。
"""
import http.server
import json
import os
import re
import shutil
import socket
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
SRC = os.path.abspath(os.environ.get("V2JW_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
REPORT_DIR = os.path.join(HERE, "_v2_jw_reports_%d" % os.getpid())
SHOT_DIR = os.path.join(HERE, "_shots_jw")
SID = "9999000005"
NAME = "测试同学"
URL = "http://210.34.74.77/sso.jsp"
AUTH_URL = "authserver.fjtcm.edu.cn"
BASE_TS = 1762000000000

sys.path.insert(0, HERE)
try:
    from _test_account import assert_test_identity  # noqa: E402
except Exception:  # pragma: no cover - 守卫缺失时仍用 9999 段身份，不阻塞本测试
    def assert_test_identity(sid, name=None, where=""):
        return True

assert_test_identity(SID, NAME, "v2_jw_check.py")


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


PORT = _free_port()
BASE = "http://127.0.0.1:%d/" % PORT

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
window.__anchorLog=[];window.__windowOpenLog=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
/* 打开路径 mock：不真实导航/不开新窗口（避免测试请求 210.34.74.77 或 authserver），只记录锚点参数 */
try{
  HTMLAnchorElement.prototype.click=function(){
    window.__anchorLog.push({
      href:String(this.getAttribute("href")||""),
      target:String(this.getAttribute("target")||""),
      rel:String(this.getAttribute("rel")||""),
      text:String(this.textContent||""),
      connected:!!this.parentNode
    });
  };
}catch(e){}
try{window.open=function(u){window.__windowOpenLog.push(String(u||""));return null;};}catch(e){}
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
try{window.__jwtest={APP_VER:APP_VER,bootDone:function(){return __bootRefreshDone;},
  errs:function(){return window.__errs||[];},cerrs:function(){return window.__cerrs||[];},
  external:function(){return window.__external||[];},gotoTab:function(k){gotoTab(k);},
  curtab:function(){return CURTAB;},jw:function(){return window.JW||null;},
  isLinkTool:function(k){return isLinkTool(k);},
  anchors:function(){return (window.__anchorLog||[]).slice();},
  clearAnchors:function(){window.__anchorLog=[];},
  opened:function(){return (window.__windowOpenLog||[]).slice();},
  setHome:function(h){try{D.d.homeTools=h;D.save();renderTabs();return true;}catch(e){return false;}},
  tabs:function(){return Array.prototype.slice.call(document.querySelectorAll("#tabsBar button")).map(function(b){return b.dataset.tab;});},
  histLen:function(){return history.length;},
  histState:function(){try{return JSON.stringify(history.state||null);}catch(e){return "";}},
  onSection:function(){var s=document.querySelector("section.on");return s?s.id:"";},
  pos:function(){try{return JSON.parse(sessionStorage.getItem("zq_pos_v1")||"null");}catch(e){return null;}},
  resources:function(){try{return (performance.getEntriesByType("resource")||[]).map(function(r){return String((r&&r.name)||"");});}catch(e){return [];}}};}catch(e){}
"""

COMMON_JS = r"""
var SRC="preview.html";
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
function pump(){return new Promise(function(res){try{var ch=new MessageChannel();ch.port1.onmessage=function(){res();};ch.port2.postMessage(0);}catch(e){setTimeout(res,0);}});}
async function pumpN(n){for(var i=0;i<(n||1);i++)await pump();}
async function waitCond(fn,maxTries){var n=maxTries||8000;for(var i=0;i<n;i++){var v=false;try{v=!!fn();}catch(e){v=false;}if(v)return true;await pump();}return false;}
function mount(src,w,h,pos){
  return new Promise(function(res,rej){
    try{sessionStorage.removeItem("zq_pos_v1");if(pos)sessionStorage.setItem("zq_pos_v1",JSON.stringify(pos));}catch(e){}
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
function report(slot,data){
  data=data||{};data.slot=slot;
  try{var x=new XMLHttpRequest();x.open("POST","/_report?slot="+slot,false);
      x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(data));}catch(e){}
}
async function bootAt(w,h,pos){
  var f=await mount(SRC,w,h,pos), win=f.contentWindow;
  await waitCond(function(){return win.__jwtest&&win.__jwtest.bootDone&&win.__jwtest.bootDone();},15000);
  await sleep(600);
  if(pos){try{sessionStorage.removeItem("zq_pos_v1");}catch(e){}}
  return f;
}
"""

MAIN_JS = r"""
async function run(){
  var R={steps:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  function visible(f,sel){var e=q(f,sel);if(!e)return false;var r=e.getBoundingClientRect();return r.height>0&&r.width>0;}
  function ovf(f){var de=f.contentDocument.documentElement;return Math.max(de.scrollWidth,f.contentDocument.body.scrollWidth)-f.contentWindow.innerWidth;}
  function badExternal(w){
    var ext=(w.__jwtest.external()||[]);
    var res=(w.__jwtest.resources()||[]).filter(function(u){return u.indexOf("210.34.74.77")>=0||u.indexOf("authserver")>=0;});
    return {ext:ext,res:res,ok:(ext.length===0&&res.length===0)};
  }
  function errs(w){return w.__jwtest.errs()||[];}
  function cerrs(w){return w.__jwtest.cerrs()||[];}
  function anchorOK(a){
    return !!a&&a.href==="__URL__"&&a.target==="_blank"&&a.rel.indexOf("noopener")>=0&&a.rel.indexOf("noreferrer")>=0;
  }
  try{
    var URL="__URL__";
    /* ===== 430：主交互 ===== */
    var f=await bootAt(430,940), w=f.contentWindow;
    T("J1 启动落地页不是链接型工具（非 jw、有 section.on、无 #s-jw）",
      w.__jwtest.curtab()!=="jw"&&!!w.__jwtest.onSection()&&w.__jwtest.onSection()!=="s-jw"&&!q(f,"#s-jw"),
      w.__jwtest.curtab()+"/"+w.__jwtest.onSection());
    var jw=w.__jwtest.jw();
    T("J2 window.JW 只读探针：url 正确 / frozen / open 为函数",
      !!jw&&jw.url===URL&&Object.isFrozen(jw)&&typeof jw.open==="function", jw?String(jw.url):"null");
    T("J3 isLinkTool：jw=true，draw/all/空=false",
      w.__jwtest.isLinkTool("jw")===true&&w.__jwtest.isLinkTool("draw")===false
      &&w.__jwtest.isLinkTool("all")===false&&w.__jwtest.isLinkTool("")===false,
      [w.__jwtest.isLinkTool("jw"),w.__jwtest.isLinkTool("draw"),w.__jwtest.isLinkTool("all")].join("/"));
    /* ===== 路径 A：全部页 jw 卡片（用户点击） ===== */
    w.__jwtest.gotoTab("all"); await sleep(450);
    var cards=qa(f,'#allCards [data-card="jw"]');
    T("J4 「全部」页有且仅有 1 张 jw 卡", cards.length===1, cards.length);
    var cardTxt=cards.length?String(cards[0].textContent||""):"";
    var cardBtn=cards.length?q(f,'#allCards [data-card="jw"] button[data-open="jw"]'):null;
    T("J5 jw 卡 tone=blue、文案含「教务 / 成绩、选课与考试」、按钮「进入」",
      !!cards.length&&cards[0].getAttribute("data-tone")==="blue"
      &&cardTxt.indexOf("教务")>=0&&cardTxt.indexOf("成绩、选课与考试")>=0
      &&!!cardBtn&&String(cardBtn.textContent||"").trim()==="进入",
      cardTxt.slice(0,120)+" | btn="+(cardBtn?String(cardBtn.textContent||"").trim():"null"));
    var cur0=w.__jwtest.curtab(), sec0=w.__jwtest.onSection(), hl0=w.__jwtest.histLen(), hs0=w.__jwtest.histState();
    w.__jwtest.clearAnchors();
    if(cards.length)cards[0].click();
    await sleep(300);
    var as=w.__jwtest.anchors();
    T("J6 点 jw 卡 → 创建 <a href=教务URL target=_blank rel=noopener noreferrer> 并 click", as.length===1&&anchorOK(as[0]),
      JSON.stringify(as));
    T("J7 点 jw 卡不切页（CURTAB / section.on / history.length / history.state 全部不变）",
      w.__jwtest.curtab()===cur0&&w.__jwtest.onSection()===sec0&&w.__jwtest.histLen()===hl0&&w.__jwtest.histState()===hs0,
      w.__jwtest.curtab()+"/"+w.__jwtest.onSection()+"|"+hl0+"->"+w.__jwtest.histLen());
    T("J8 点 jw 卡不产生任何外部请求（含 210.34.74.77 / authserver）", badExternal(w).ok, JSON.stringify(badExternal(w).ext).slice(0,200));
    w.__jwtest.clearAnchors();
    if(cards.length)cards[0].click(); await sleep(200);
    T("J9 可重复打开（再点一次仍有 1 条锚点记录）", w.__jwtest.anchors().length===1, JSON.stringify(w.__jwtest.anchors()).slice(0,200));
    /* 卡片内「进入」按钮点击：按钮 + 容器的冒泡不得双触发（链接型工具会双开窗口） */
    w.__jwtest.clearAnchors();
    var enterBtn=q(f,'#allCards [data-card="jw"] button[data-open="jw"]');
    if(enterBtn)enterBtn.click(); await sleep(250);
    T("J28 点卡片内「进入」按钮只打开 1 次（不双开窗口）", !!enterBtn&&w.__jwtest.anchors().length===1,
      JSON.stringify(w.__jwtest.anchors()).slice(0,300));
    w.__jwtest.clearAnchors();
    var handle=q(f,'#allCards [data-card="jw"] [data-handle]');
    if(handle)handle.click(); await sleep(200);
    T("J29 点拖动手柄不打开教务站", !!handle&&w.__jwtest.anchors().length===0, JSON.stringify(w.__jwtest.anchors()).slice(0,200));
    T("J10 打开后 0 JS 报错 / 0 console.error", errs(w).length===0&&cerrs(w).length===0,
      JSON.stringify(errs(w).concat(cerrs(w))).slice(0,240));
    /* ===== 路径 B：顶部工具栏 jw tab ===== */
    w.__jwtest.clearAnchors();
    var homeOK=w.__jwtest.setHome(["jw","draw","hw","nt"]);
    await sleep(500);
    var tabs=w.__jwtest.tabs()||[];
    T("J11 工具栏可含 jw tab（homeTools 允许教务）", homeOK&&tabs.indexOf("jw")>=0, JSON.stringify(tabs));
    var jwTab=q(f,'#tabsBar button[data-tab="jw"]');
    var curB=w.__jwtest.curtab(), secB=w.__jwtest.onSection(), hlB=w.__jwtest.histLen(), hsB=w.__jwtest.histState();
    if(jwTab)jwTab.click();
    await sleep(300);
    var asB=w.__jwtest.anchors();
    T("J12 点工具栏「教务」tab → 直接打开（锚点 href/target/rel 正确）", asB.length===1&&anchorOK(asB[0]), JSON.stringify(asB));
    T("J13 点工具栏 tab 不切页（CURTAB / section.on / history 不变）",
      w.__jwtest.curtab()===curB&&w.__jwtest.onSection()===secB&&w.__jwtest.histLen()===hlB&&w.__jwtest.histState()===hsB,
      w.__jwtest.curtab()+"/"+w.__jwtest.onSection());
    T("J14 工具栏路径 0 外部请求（含 210.34.74.77 / authserver）", badExternal(w).ok, JSON.stringify(badExternal(w).ext).slice(0,200));
    /* ===== 程序化 gotoTab("jw") 同路径 + 探针 open() ===== */
    w.__jwtest.clearAnchors();
    w.__jwtest.gotoTab("jw"); await sleep(250);
    var asC=w.__jwtest.anchors();
    T("J15 程序化 gotoTab(\"jw\") → 直接打开且不切页", asC.length===1&&anchorOK(asC[0])&&w.__jwtest.curtab()===curB,
      JSON.stringify(asC));
    w.__jwtest.clearAnchors();
    try{w.__jwtest.jw().open();}catch(e){}
    await sleep(200);
    T("J16 window.JW.open() 可用（复用同一打开逻辑）", w.__jwtest.anchors().length===1, JSON.stringify(w.__jwtest.anchors()).slice(0,200));
    /* 全部页：无溢出 + 0 请求 + 0 错误 */
    w.__jwtest.gotoTab("all"); await sleep(350);
    T("J17 430 全部页无横向溢出", ovf(f)<=1, "overflow="+ovf(f));
    T("J18 430 页加载 + 全流程 0 外部请求（含 210.34.74.77 / authserver）", badExternal(w).ok,
      JSON.stringify(badExternal(w).ext).slice(0,200)+" | "+JSON.stringify(badExternal(w).res));
    T("J19 430 页加载 + 全流程 0 JS 报错 / 0 console.error", errs(w).length===0&&cerrs(w).length===0,
      JSON.stringify(errs(w).concat(cerrs(w))).slice(0,240));
    f.parentNode.removeChild(f);
    /* ===== 恢复路径：旧数据 sessionStorage 记录 tab=jw，不得无手势自动打开外站 ===== */
    var f3=await bootAt(430,940,{v:1,sid:"__SID__",tab:"jw",y:0,ts:Date.now()});
    await sleep(300);
    var w3=f3.contentWindow;
    T("J20 旧数据恢复（zq_pos_v1 tab=jw）→ 不打开教务站、不落到链接型工具",
      (w3.__jwtest.anchors()||[]).length===0&&w3.__jwtest.curtab()!=="jw"
      &&w3.__jwtest.onSection()!=="s-jw"&&!!w3.__jwtest.onSection(),
      w3.__jwtest.curtab()+"/"+w3.__jwtest.onSection()+" anchors="+JSON.stringify(w3.__jwtest.anchors()));
    T("J21 恢复路径 0 外部请求（含 210.34.74.77 / authserver）", badExternal(w3).ok, JSON.stringify(badExternal(w3).ext).slice(0,200));
    f3.parentNode.removeChild(f3);
    /* ===== 多宽度：卡片路径 + 工具栏路径 + 无溢出 + 0 错误/0 请求 ===== */
    var WS=[[360,780],[390,844],[1280,900]];
    for(var i=0;i<WS.length;i++){
      var W=WS[i][0], H=WS[i][1], tag=(i+1)+"-"+W;
      var f2=await bootAt(W,H), w2=f2.contentWindow;
      T("J22-"+tag+" 启动落地页不是链接型工具", w2.__jwtest.curtab()!=="jw"&&!!w2.__jwtest.onSection(), w2.__jwtest.curtab());
      w2.__jwtest.gotoTab("all"); await sleep(450);
      var c2=qa(f2,'#allCards [data-card="jw"]');
      w2.__jwtest.clearAnchors();
      var cur2=w2.__jwtest.curtab(), sec2=w2.__jwtest.onSection();
      if(c2.length)c2[0].click();
      await sleep(300);
      var a2=w2.__jwtest.anchors();
      T("J23-"+tag+" 全部页卡路径直接打开且不切页", c2.length===1&&a2.length===1&&anchorOK(a2[0])
        &&w2.__jwtest.curtab()===cur2&&w2.__jwtest.onSection()===sec2, JSON.stringify(a2));
      w2.__jwtest.clearAnchors();
      w2.__jwtest.setHome(["jw","draw","hw","nt"]); await sleep(400);
      var jt2=q(f2,'#tabsBar button[data-tab="jw"]');
      if(jt2)jt2.click();
      await sleep(300);
      var a2b=w2.__jwtest.anchors();
      T("J24-"+tag+" 工具栏 tab 路径直接打开", !!jt2&&a2b.length===1&&anchorOK(a2b[0]), JSON.stringify(a2b));
      T("J25-"+tag+" 无横向溢出（全部页）", ovf(f2)<=1, "overflow="+ovf(f2));
      T("J26-"+tag+" 0 外部请求（含 210.34.74.77 / authserver）", badExternal(w2).ok, JSON.stringify(badExternal(w2).ext).slice(0,160));
      T("J27-"+tag+" 0 JS 报错 / 0 console.error", errs(w2).length===0&&cerrs(w2).length===0,
        JSON.stringify(errs(w2).concat(cerrs(w2))).slice(0,200));
      f2.parentNode.removeChild(f2);
    }
  }catch(e){
    R.steps.push({k:"脚本异常",ok:false,note:String((e&&e.stack)||e)});
  }
  report("main",R);
  await pumpN(3);
}
run();
"""


def jw_js_block(html):
    s = html.find("/* ========== __JW_ENTRY_V1_JS__")
    if s < 0:
        return ""
    e = html.find("</script>", s)
    if e < 0:
        return ""
    return html[s:e]


def static_checks(html):
    out = []

    def add(k, ok, note=""):
        out.append({"k": k, "ok": bool(ok), "note": str(note)})

    js = jw_js_block(html)
    js_i = html.find("/* ========== __JW_ENTRY_V1_JS__")
    ug_i = html.find("/* ========== __UG_CARDS_V1__")
    body_i = html.find("</body>")
    tail = html[js_i:html.find("</script>")] if js_i >= 0 else ""

    # S1 中间入口页已删除
    gone = ["<section id=\"s-jw\">", 'id="jwOpen"', 'id="jwCopy"', 'id="jwUrl"',
            "<!-- __JW_ENTRY_V1_BEGIN__ -->", "<!-- __JW_ENTRY_V1_END__ -->",
            "/* ========== __JW_ENTRY_V1_CSS__", "jw-acts", "jw-head"]
    add("S1 中间入口页/旧按钮/旧 CSS/旧标记已全部删除（点卡片直进）",
        all(x not in html for x in gone), [x for x in gone if x in html])

    # S2 TOOLS 含 jw 条目（增量 57 精简说明；2026-11-16 工具精简后 jw 回到数组末尾）；ALL_TONE 保留
    m = re.search(r"var TOOLS=\[(.*?)\];", html, re.S)
    tools = m.group(1) if m else ""
    jw_entry = '{k:"jw",n:"教务",d:"成绩、选课与考试",url:"http://210.34.74.77/sso.jsp"}'
    add("S2 TOOLS 含 jw 条目（逐字含 url 教务链接，且为数组末尾），ALL_TONE.jw=\"blue\" 保留",
        tools.count(jw_entry) == 1 and tools.rstrip().endswith(jw_entry)
        and re.search(r'var ALL_TONE=\{[^}]*jw:"blue"', html) is not None, tools[-200:].replace("\n", " "))

    # S3 新 JS 块：内容 + 位置 + 无定时器/网络请求/密码
    add("S3 __JW_ENTRY_V1_JS__ 在新 JS（JW_URL/isLinkTool/openJwDirect/firstPageTab/window.JW）且无定时器/网络请求/密码存储",
        js != "" and all(x in js for x in (
            'var JW_URL="http://210.34.74.77/sso.jsp";', "function isLinkTool(k){", "function openJwDirect(){",
            "function firstPageTab(home){", 'Object.defineProperty(window,"JW"',
            "Object.freeze({url:JW_URL,open:openJwDirect})"))
        and all(x not in js for x in ("setInterval", "setTimeout", "fetch(", "XMLHttpRequest", "sendBeacon",
                                      "password", "localStorage")),
        "")

    # S4 gotoTab 包装
    add("S4 包装 gotoTab：isLinkTool(k) → openJwDirect() 后 return（不切页）",
        "var _gotoTab=gotoTab;" in js
        and "gotoTab=function(k,noScroll){" in js
        and "if(isLinkTool(k)){try{openJwDirect();}catch(e){}return;}" in js, "")

    # S5 打开方式：真实锚点 + target/rel + click + location.href 兜底
    add("S5 打开方式 = <a href target=_blank rel=noopener noreferrer> + click，兜底 location.href",
        js != "" and all(x in js for x in ('a.href=JW_URL;', 'a.target="_blank";',
                                           'a.rel="noopener noreferrer";', "a.click();",
                                           "location.href=JW_URL")), "")

    # S6 滑动引擎跳过链接型工具（tool + STEP 边界）
    add("S6 滑动引擎 targetFor 跳过链接型工具（nextPageTabIdx；tool/STEP 边界两处生效）",
        "function nextPageTabIdx(bs,i,dir){" in html
        and "while(j>=0&&j<bs.length&&isLinkTool(bs[j].dataset.tab))j+=dir;" in html
        and "var j=nextPageTabIdx(bs,i,dir);" in html
        and "var b2=tabBtns(), j2=nextPageTabIdx(b2,idx,dir);" in html, "")

    # S7 卡片按钮「进入」
    add("S7 全部页 jw 卡按钮文案「进入」（label:(t.url?\"进入\":\"打开\")）",
        'label:(t.url?"进入":"打开")' in html, "")

    # S8 恢复路径防护（POS / popstate / renderTabs）
    add("S8 恢复路径不落到链接型工具：POS url 无效 / popstate 跳过 / renderTabs 用 firstPageTab",
        "if(tool&&tool.url)valid=false;" in html
        and "if(isLinkTool(String(st.zqTab)))return;" in html
        and "if(LANDING&&AUTH.ready){ CURTAB=firstPageTab(home);" in html
        and "if(!ok||isLinkTool(CURTAB)) CURTAB=firstPageTab(home);" in html, "")

    # S9 UG jw 卡文案逐字
    m = re.search(r"var UG=\(function\(\)\{(.*?)\}\)\(\);", html, re.S)
    ug = m.group(1) if m else ""
    add("S9 UG jw 卡逐字文案（sub/steps/tip 指向直进 + 浏览器自动填充；2026-11-16 工具精简后共 18 张）",
        ug.count('{id:"') == 18
        and '{id:"jw",cat:"study",title:"教务入口",sub:"点卡片直接打开教务系统"' in ug
        and 'steps:["点『教务』卡片直接打开教务系统","首次登录时勾选浏览器『保存密码』","之后打开即自动填充账号密码"]' in ug
        and 'tip:"自动填充由浏览器完成；校外打不开时先连学校 VPN"' in ug, "cards=%d" % ug.count('{id:"'))

    # S10 版本 / 零外部资源 / 不嵌 iframe 直连教务
    add("S10 APP_VER 仍 2.0.0；零外部资源（无 <script src/外部字体/CDN）；无 iframe 直连教务",
        'var APP_VER="2.0.0"' in html and "<script src=" not in html
        and "fonts.googleapis" not in html and "cdn." not in html
        and not re.search(r'<iframe[^>]+(210\.34\.74\.77|authserver)', html), "")

    # S11 全 HTML 仅 2 处教务 URL（TOOLS url + JW_URL）
    cnt = html.count(URL)
    add("S11 全 HTML 仅 2 处教务 URL（TOOLS.url + JW_URL，无资源引用）", cnt == 2, "cnt=%d" % cnt)

    # S12 不采集/不保存教务账号密码
    low = js.lower()
    add("S12 入口 JS 不接触账号密码（无 password/input/localStorage/clipboard）",
        all(x not in low for x in ("password", "input", "localstorage", "clipboard", "credential")), "")

    # S13 只读探针
    add("S13 window.JW 只读（Object.freeze + writable:false，url+open）",
        'Object.defineProperty(window,"JW",{value:Object.freeze({url:JW_URL,open:openJwDirect}),' in js
        and "writable:false" in js and "configurable:false" in js, "")

    # S14 JS 块在主 IIFE 内（UG 之后）
    add("S14 __JW_ENTRY_V1_JS__ 位于主 IIFE 内（UG 块之后；其后仅本块+主 IIFE 两个 `})();` 收尾）",
        js_i > ug_i >= 0 and body_i > js_i and tail.count("})();") == 2 and tail.rstrip().endswith("})();"),
        "closes=%d" % tail.count("})();"))

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
        raise SystemExit("[v2_jw_check] 找不到主脚本结尾锚点")
    html = html[:idx] + HOOK.replace("\n", "\r\n") + "\r\n" + html[idx:]
    mock = MOCK_JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")) \
                  .replace("__SID__", SID).replace("__NAME__", NAME)
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    return html.replace("<head>", "<head>" + mock, 1)


def run_edge(url, budget=30000, timeout=240, screenshot=None, win=None):
    prof = tempfile.mkdtemp(prefix="edgeprof_jw_", dir=REPORT_DIR)
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
    var mode=qs.get("mode")||"all";
    var f=document.createElement("iframe");
    f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block;margin:0 auto;background:#fff";
    f.src="preview.html";
    document.body.appendChild(f);
    await new Promise(function(res){var done=false;f.onload=function(){if(!done){done=true;setTimeout(res,60);}};setTimeout(function(){if(!done){done=true;res();}},9000);});
    var win=f.contentWindow;
    await waitCond(function(){return win&&win.__jwtest&&win.__jwtest.bootDone&&win.__jwtest.bootDone();});
    await sleep(500);
    if(mode==="toolbar"){
      try{win.__jwtest.setHome(["jw","draw","hw","nt"]);}catch(e){}
      await sleep(700);
    }else{
      try{win.__jwtest.gotoTab("all");}catch(e){}
      await sleep(700);
      try{
        var c=f.contentDocument.querySelector('#allCards [data-card="jw"]');
        if(c&&c.scrollIntoView)c.scrollIntoView({block:"center"});
      }catch(e){}
      await sleep(400);
    }
    document.title="ready";
  }catch(e){document.title="err:"+e;}
})();
"""


def build_shot():
    body = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 jw shot</title>"
            "<style>html,body{margin:0;background:#F7F8F8}</style></head><body>"
            "<script>" + SHOT_JS + "</script></body></html>")
    return body


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    os.makedirs(SHOT_DIR, exist_ok=True)
    # 清掉旧截图（避免旧版中间页截图残留）
    for nm in os.listdir(SHOT_DIR):
        if nm.lower().endswith(".png"):
            try:
                os.remove(os.path.join(SHOT_DIR, nm))
            except Exception:
                pass
    raw = open(SRC, encoding="utf-8", newline="").read()
    results = static_checks(raw)
    tmp = tempfile.mkdtemp(prefix="v2jw_")
    srv = None
    try:
        preview = build_preview()
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(preview)
        body = COMMON_JS + "\n" + MAIN_JS.replace("__URL__", URL).replace("__SID__", SID)
        harness = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 jw check</title>"
                   "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
                   "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
        open(os.path.join(tmp, "harness.html"), "w", encoding="utf-8", newline="").write(harness)
        open(os.path.join(tmp, "shot.html"), "w", encoding="utf-8", newline="").write(build_shot())
        os.chdir(tmp)
        srv = Q(("127.0.0.1", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run_edge(BASE + "harness.html", budget=70000, win="430,940")
        p = os.path.join(REPORT_DIR, "main.json")
        data = None
        t0 = time.time()
        while time.time() - t0 < 45:
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
            ("01_mobile_430_all_cards.png", "w=430&h=940&mode=all", "430,940"),
            ("02_mobile_360_all_cards.png", "w=360&h=780&mode=all", "360,780"),
            ("03_mobile_390_all_cards.png", "w=390&h=844&mode=all", "390,844"),
            ("04_desktop_1280_all_cards.png", "w=1280&h=900&mode=all", "1300,940"),
            ("05_mobile_430_toolbar_jw.png", "w=430&h=940&mode=toolbar", "430,940"),
        ]
        for name, qs, win in shots:
            out = os.path.join(SHOT_DIR, name)
            try:
                if os.path.exists(out):
                    os.remove(out)
            except Exception:
                pass
            run_edge(BASE + "shot.html?" + qs, budget=25000, win=win, screenshot=out, timeout=120)
            print("[shot] %s -> %s" % (name, "OK" if os.path.exists(out) else "MISSING"))
        passed = 0
        for s in results:
            if s["ok"]:
                passed += 1
            print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + str(s["note"])) if s.get("note") else ""))
        total = len(results)
        print("=" * 64)
        print("v2_jw_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
        print("=" * 64)
        sys.exit(0 if total and passed == total else 1)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(REPORT_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
