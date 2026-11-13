# -*- coding: utf-8 -*-
"""v2.0.0 「教务」入口（__JW_ENTRY_V1__）专项自检
契约：_audit/jw_entry_20261113/CONTRACT.md §1/§2.1
覆盖：
  静态：入口标记成对且位置正确（#s-jw 在 #s-vote 之后、__WEB_B2_FILE_BEGIN__ 之前）/ 逐字文案 /
        主按钮真实锚点 href+target+rel / 复制按钮 / TOOLS 末尾 jw / ALL_TONE.jw /
        CSS 块与 JS 块位置 / JS 块无定时器与网络请求 / window.JW 只读 / UG CARDS jw 卡（18 张）/
        APP_VER 不变 / 零外部资源 / 全 HTML 仅 3 处教务 URL 且均在入口块 / 页面加载阶段不请求教务站；
  运行时（430×940 / 360×780 / 390×844 / 1280×900）：两条进入路径（gotoTab("jw") 与「全部」页点
        #allCards [data-card="jw"]）→ #s-jw 可见；#jwOpen href/target/rel；#jwCopy 点击 → mock 剪贴板
        收到教务 URL 且 toast「链接已复制」；0 JS 报错、0 console.error、0 外部请求（页面加载与切页
        阶段均不请求 210.34.74.77）、无横向溢出、点按高度 ≥40px、锚点 inline-flex 居中无下划线；
  截图：430/360/390/1280 四档 + 全部页 jw 卡，落盘 tools/tests/_shots_jw/。

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
window.__errs=[];window.__cerrs=[];window.__external=[];window.__copied=null;
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
/* 复制路径 mock：不依赖无头浏览器的剪贴板权限/用户激活，记录写入值供断言 */
try{
  Object.defineProperty(navigator,"clipboard",{configurable:true,value:{
    writeText:function(t){window.__copied=String(t);return Promise.resolve();},
    readText:function(){return Promise.resolve(String(window.__copied||""));}
  }});
}catch(e){
  try{Object.defineProperty(Navigator.prototype,"clipboard",{configurable:true,get:function(){
    return {writeText:function(t){window.__copied=String(t);return Promise.resolve();}};
  }});}catch(e2){}
}
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
  copied:function(){return window.__copied;},
  toastScope:function(){try{return (typeof toast)+","+(typeof copy)+","+(typeof window.toast);}catch(e){return "err:"+e;}},
  toast:function(){var t=document.getElementById("toast");return t?{on:t.classList.contains("on"),text:String(t.textContent||"")}:null;},
  resources:function(){try{return (performance.getEntriesByType("resource")||[]).map(function(r){return String((r&&r.name)||"");});}catch(e){return [];}}};}catch(e){}
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
function report(slot,data){
  data=data||{};data.slot=slot;
  try{var x=new XMLHttpRequest();x.open("POST","/_report?slot="+slot,false);
      x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(data));}catch(e){}
}
async function bootAt(w,h){
  var f=await mount(SRC,w,h), win=f.contentWindow;
  await waitCond(function(){return win.__jwtest&&win.__jwtest.bootDone&&win.__jwtest.bootDone();},15000);
  await sleep(600);
  return f;
}
"""

MAIN_JS = r"""
async function run(){
  var R={steps:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  function visible(f,sel){
    var e=q(f,sel); if(!e)return false;
    var r=e.getBoundingClientRect();
    return e.classList.contains("on")&&r.height>0&&r.width>0;
  }
  function ovf(f){
    var de=f.contentDocument.documentElement;
    return Math.max(de.scrollWidth,f.contentDocument.body.scrollWidth)-f.contentWindow.innerWidth;
  }
  function badExternal(w){
    var ext=(w.__jwtest.external()||[]);
    var res=(w.__jwtest.resources()||[]).filter(function(u){return u.indexOf("210.34.74.77")>=0;});
    return {ext:ext,res:res,ok:(ext.length===0&&res.length===0)};
  }
  function errs(w){return w.__jwtest.errs()||[];}
  function cerrs(w){return w.__jwtest.cerrs()||[];}
  function hh(e){var r=e.getBoundingClientRect();return Math.round(r.height);}
  try{
    var URL="__URL__";
    /* ===== 430：主交互 ===== */
    var f=await bootAt(430,940), w=f.contentWindow;
    w.__jwtest.gotoTab("jw"); await sleep(500);
    T("J1 430 gotoTab(\"jw\") → #s-jw 可见", visible(f,"#s-jw"), q(f,"#s-jw")?q(f,"#s-jw").className:"");
    T("J2 标题「教务管理系统」", txt(f,"#s-jw .jw-head-t b")==="教务管理系统", txt(f,"#s-jw .jw-head-t b"));
    T("J3 短描述「成绩 · 选课 · 考试」", txt(f,"#s-jw .jw-head-t span")==="成绩 · 选课 · 考试", txt(f,"#s-jw .jw-head-t span"));
    var open=q(f,"#jwOpen"), copy=q(f,"#jwCopy");
    T("J4 主按钮文案「打开教务系统」", !!open&&String(open.textContent||"").trim()==="打开教务系统", open?String(open.textContent||"").trim():"");
    T("J5 #jwOpen href 正确", !!open&&open.getAttribute("href")===URL, open?open.getAttribute("href"):"");
    T("J6 #jwOpen target=_blank", !!open&&open.getAttribute("target")==="_blank", open?open.getAttribute("target"):"");
    var rel=open?String(open.getAttribute("rel")||""):"";
    T("J7 #jwOpen rel 含 noopener + noreferrer", rel.indexOf("noopener")>=0&&rel.indexOf("noreferrer")>=0, rel);
    T("J8 #jwCopy 为 button[type=button]、文案「复制链接」", !!copy&&copy.tagName==="BUTTON"&&copy.getAttribute("type")==="button"&&String(copy.textContent||"").trim()==="复制链接", copy?copy.tagName+"/"+copy.getAttribute("type"):"");
    T("J9 URL 小字正确", txt(f,"#jwUrl")===URL, txt(f,"#jwUrl"));
    T("J10 提示行「统一身份认证登录 · 打不开时先连学校 VPN」", txt(f,"#s-jw .jw-hint")==="统一身份认证登录 · 打不开时先连学校 VPN", txt(f,"#s-jw .jw-hint"));
    var jw=w.__jwtest.jw();
    T("J11 window.JW 只读探针 url 正确", !!jw&&jw.url===URL&&Object.isFrozen(jw), jw?String(jw.url):"null");
    T("J12 主按钮 / 复制按钮点按高度 ≥40px", !!open&&!!copy&&hh(open)>=40&&hh(copy)>=40, (open?hh(open):0)+"/"+(copy?hh(copy):0));
    var cs=w.getComputedStyle(open);
    /* 注：.jw-acts 是 flex 容器，flex 子项的 inline-flex 会按 CSS Display 规范 blockify 成 flex；
       这里同时接受 inline-flex/flex，真正要锁的是「居中 + 无下划线」。 */
    T("J13 锚点按钮弹性盒居中（inline-flex/flex）且无下划线",
      (cs.display==="inline-flex"||cs.display==="flex")&&cs.alignItems==="center"&&cs.justifyContent==="center"&&String(cs.textDecorationLine||cs.textDecoration||"").indexOf("underline")<0,
      cs.display+"/"+cs.alignItems+"/"+cs.justifyContent+"/"+String(cs.textDecorationLine||""));
    T("J14 加载/渲染阶段未发生顶层导航（仍在本地预览页）", String(w.location.href).indexOf("preview.html")>=0, String(w.location.href));
    copy.click(); await sleep(260);
    T("J15 点「复制链接」→ 剪贴板收到教务 URL", w.__jwtest.copied()===URL, String(w.__jwtest.copied()));
    var t=w.__jwtest.toast();
    T("J16 点「复制链接」→ toast「链接已复制」", !!t&&t.on&&t.text==="链接已复制", t?t.text:"null");
    /* 作用域断言：闭包内 toast/copy 是函数；window.toast 只是 id=toast 的 DOM 元素（命名访问，非函数）。
       JW 块若被移到主 IIFE 之外，`toast(...)` 会拿到那个 DOM 元素并抛 TypeError（被 catch 吞掉）→
       J16 的 toast 文案断言必然失败，所以这里一并锁住。 */
    var sc=w.__jwtest.toastScope(), scp=String(sc).split(",");
    T("J34 JW 块与主 IIFE 同作用域（闭包 toast/copy 为函数，window.toast 只是同名 DOM 元素）",
      scp[0]==="function"&&scp[1]==="function"&&scp[2]!=="function", "scope="+sc);
    T("J17 复制后 0 JS 报错", errs(w).length===0, JSON.stringify(errs(w)).slice(0,240));
    T("J18 0 console.error", cerrs(w).length===0, JSON.stringify(cerrs(w)).slice(0,240));
    T("J19 430 无横向溢出", ovf(f)<=1, "overflow="+ovf(f));
    var be=badExternal(w);
    T("J20 430 页加载 + 切页 0 外部请求（含 210.34.74.77）", be.ok, JSON.stringify(be.ext).slice(0,200)+" | "+JSON.stringify(be.res));
    /* ===== 第二条进入路径：全部页 jw 卡 ===== */
    w.__jwtest.gotoTab("all"); await sleep(450);
    var cards=qa(f,'#allCards [data-card="jw"]');
    T("J21 「全部」页有且仅有 1 张 jw 卡", cards.length===1, cards.length);
    var ct=cards.length?String(cards[0].textContent||""):"";
    T("J22 jw 卡 data-tone=blue 且含「教务 / 成绩 · 选课 · 考试；统一身份认证直达教务系统」",
      !!cards.length&&cards[0].getAttribute("data-tone")==="blue"&&ct.indexOf("教务")>=0&&ct.indexOf("成绩 · 选课 · 考试；统一身份认证直达教务系统")>=0,
      ct.slice(0,140));
    if(cards.length)cards[0].click();
    await sleep(450);
    T("J23 点 jw 卡 → CURTAB=jw 且 #s-jw 可见", w.__jwtest.curtab()==="jw"&&visible(f,"#s-jw"), w.__jwtest.curtab());
    be=badExternal(w);
    T("J24 卡路径进入后 0 外部请求（含 210.34.74.77）", be.ok, JSON.stringify(be.ext).slice(0,200));
    T("J25 卡路径进入后 0 JS 报错 / 0 console.error", errs(w).length===0&&cerrs(w).length===0, JSON.stringify(errs(w).concat(cerrs(w))).slice(0,240));
    T("J26 卡路径进入后无横向溢出", ovf(f)<=1, "overflow="+ovf(f));
    f.parentNode.removeChild(f);
    /* ===== 多宽度：两条路径 + 无溢出 + 无外部请求 ===== */
    var WS=[[360,780],[390,844],[1280,900]];
    for(var i=0;i<WS.length;i++){
      var W=WS[i][0], H=WS[i][1], tag=(i+1)+"-"+W;
      var f2=await bootAt(W,H), w2=f2.contentWindow;
      w2.__jwtest.gotoTab("jw"); await sleep(450);
      T("J27-"+tag+" gotoTab(\"jw\") → #s-jw 可见", visible(f2,"#s-jw"));
      T("J28-"+tag+" 主按钮高度 ≥40px 且 href 正确",
        (function(){var o=q(f2,"#jwOpen");return !!o&&hh(o)>=40&&o.getAttribute("href")===URL;})());
      T("J29-"+tag+" 无横向溢出", ovf(f2)<=1, "overflow="+ovf(f2));
      w2.__jwtest.gotoTab("all"); await sleep(450);
      var c2=qa(f2,'#allCards [data-card="jw"]');
      if(c2.length)c2[0].click();
      await sleep(450);
      T("J30-"+tag+" 「全部」卡路径进入 → CURTAB=jw 且 #s-jw 可见", w2.__jwtest.curtab()==="jw"&&visible(f2,"#s-jw"), w2.__jwtest.curtab());
      var be2=badExternal(w2);
      T("J31-"+tag+" 0 外部请求（含 210.34.74.77）", be2.ok, JSON.stringify(be2.ext).slice(0,160)+" | "+JSON.stringify(be2.res));
      T("J32-"+tag+" 0 JS 报错 / 0 console.error", errs(w2).length===0&&cerrs(w2).length===0, JSON.stringify(errs(w2).concat(cerrs(w2))).slice(0,200));
      T("J33-"+tag+" 无横向溢出（卡路径进入后）", ovf(f2)<=1, "overflow="+ovf(f2));
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


def section_slice(html):
    b = html.find("<!-- __JW_ENTRY_V1_BEGIN__ -->")
    e = html.find("<!-- __JW_ENTRY_V1_END__ -->")
    if b < 0 or e < 0:
        return ""
    return html[b:e]


def jw_js_block(html):
    s = html.find("/* ========== __JW_ENTRY_V1_JS__")
    if s < 0:
        return ""
    e = html.find("</script>", s)
    if e < 0:
        return ""
    return html[s:e]


def jw_css_block(html):
    s = html.find("/* ========== __JW_ENTRY_V1_CSS__")
    if s < 0:
        return ""
    e = html.find("</style>", s)
    if e < 0:
        return ""
    return html[s:e]


def static_checks(html):
    out = []

    def add(k, ok, note=""):
        out.append({"k": k, "ok": bool(ok), "note": str(note)})

    sec = section_slice(html)
    css = jw_css_block(html)
    js = jw_js_block(html)

    # S1 标记成对
    b = html.count("<!-- __JW_ENTRY_V1_BEGIN__ -->")
    e = html.count("<!-- __JW_ENTRY_V1_END__ -->")
    add("S1 入口标记成对（BEGIN/END 各 1 且顺序正确）",
        b == 1 and e == 1 and html.find("<!-- __JW_ENTRY_V1_BEGIN__ -->") < html.find("<!-- __JW_ENTRY_V1_END__ -->"),
        "begin=%d/end=%d" % (b, e))

    # S2 位置：#s-vote 之后、__WEB_B2_FILE_BEGIN__ 之前
    vote_i = html.find('<section id="s-vote">')
    jw_i = html.find('<section id="s-jw">')
    b2_i = html.find("<!-- __WEB_B2_FILE_BEGIN__ -->")
    add("S2 #s-jw 位于 #s-vote 之后、__WEB_B2_FILE_BEGIN__ 之前",
        vote_i >= 0 and jw_i >= 0 and b2_i >= 0 and vote_i < jw_i < b2_i,
        "vote=%d jw=%d b2=%d" % (vote_i, jw_i, b2_i))

    # S3 逐字文案
    need = ["<b>教务管理系统</b>", "<span>成绩 · 选课 · 考试</span>",
            ">http://210.34.74.77/sso.jsp<", ">统一身份认证登录 · 打不开时先连学校 VPN<"]
    add("S3 标题 / 短描述 / URL 小字 / 提示行逐字一致",
        sec != "" and all(x in sec for x in need), [x for x in need if x not in sec])

    # S4 主按钮 = 真实锚点（href/target/rel 全正确）
    anchor = ('<a class="btn pri" id="jwOpen" href="http://210.34.74.77/sso.jsp" '
              'target="_blank" rel="noopener noreferrer">打开教务系统</a>')
    add("S4 主按钮为真实锚点（href + target=_blank + rel=noopener noreferrer + 文案）",
        anchor in sec, "")

    # S5 次按钮
    add("S5 复制按钮 <button id=jwCopy type=button>复制链接</button>",
        '<button class="btn ghost" id="jwCopy" type="button">复制链接</button>' in sec, "")

    # S6 TOOLS 末尾追加 jw（不插中间）
    m = re.search(r"var TOOLS=\[(.*?)\];", html, re.S)
    tools = m.group(1) if m else ""
    jw_entry = '{k:"jw",n:"教务",d:"成绩 · 选课 · 考试；统一身份认证直达教务系统"}'
    add("S6 TOOLS 数组末尾追加 jw（逐字 d，未插中间）",
        tools.rstrip().endswith(jw_entry) and tools.count(jw_entry) == 1, tools[-120:].replace("\n", " "))

    # S7 ALL_TONE.jw
    add("S7 ALL_TONE.jw=\"blue\"", 'jw:"blue"' in html and re.search(r"var ALL_TONE=\{[^}]*jw:\"blue\"", html) is not None,
        "")

    # S8 CSS 块位置与内容
    style_close = html.find("</style>")
    add("S8 __JW_ENTRY_V1_CSS__ 在 </style> 之前、含 .jw-* 规则、无外部资源",
        css != "" and style_close > 0 and html.find("/* ========== __JW_ENTRY_V1_CSS__") < style_close
        and "#s-jw .jw-acts .btn{min-height:44px" in css and "text-decoration:none" in css
        and "url(" not in css and "http" not in css,
        "")

    # S9 JS 块位置与内容（无定时器 / 无网络请求）
    ug_i = html.find("/* ========== __UG_CARDS_V1__")
    js_i = html.find("/* ========== __JW_ENTRY_V1_JS__")
    body_i = html.find("</body>")
    add("S9 __JW_ENTRY_V1_JS__ 在 UG 块之后、</body> 之前，含 toast(\"链接已复制\")/window.JW/Object.freeze 且无定时器/网络请求",
        js != "" and ug_i >= 0 and js_i > ug_i and body_i > js_i
        and 'toast("链接已复制")' in js and '"JW"' in js and "Object.freeze" in js
        and all(x not in js for x in ("setInterval", "setTimeout", "fetch(", "XMLHttpRequest", "sendBeacon")),
        "")

    # S10 UG CARDS jw 卡
    m = re.search(r"var UG=\(function\(\)\{(.*?)\}\)\(\);", html, re.S)
    ug = m.group(1) if m else ""
    n_cards = ug.count('{id:"')
    scene_ok = 'scene:"list"' in ug or 'scene:"grid"' in ug
    jw_card_ok = ('{id:"jw",cat:"study",title:"教务入口"' in ug
                  and 'steps:["工具栏或「全部」页打开教务入口","点「打开教务系统」在新窗口打开","统一身份认证登录后进入教务系统"]' in ug
                  and 'tip:"打不开时先连学校 VPN；链接可复制后在手机浏览器打开"' in ug)
    add("S10 UG CARDS 18 张（含 jw / cat=study / scene 复用现有 / 3 步 + tip）",
        n_cards == 18 and jw_card_ok and scene_ok, "cards=%d" % n_cards)

    # S11 版本号不变
    add("S11 APP_VER 仍为 2.0.0", 'var APP_VER="2.0.0"' in html, "")

    # S12 零外部资源 / 不嵌 iframe
    add("S12 零外部资源（无 <script src / 外部字体 / CDN），入口不嵌 iframe、不引外部图片",
        "<script src=" not in html and "fonts.googleapis" not in html and "cdn." not in html
        and "<iframe" not in sec and not re.search(r'<img[^>]+src="(https?:)?//', sec), "")

    # S13 全 HTML 只有 3 处教务 URL，且都在入口块（section 2 + JS 1）
    cnt = html.count(URL)
    in_sec = sec.count(URL)
    in_js = js.count(URL)
    add("S13 全 HTML 仅 3 处教务 URL（section 2 + JS 1，无其它资源引用）",
        cnt == 3 and in_sec == 2 and in_js == 1, "cnt=%d sec=%d js=%d" % (cnt, in_sec, in_js))

    # S14 不采集账号密码
    add("S14 入口页无账号密码输入（不采集 / 不存储）",
        "password" not in sec.lower() and "input" not in sec.lower() and sec.count("href=") == 1,
        "")

    # S15 点按尺寸 / 锚点按钮声明 / 只读探针定义
    add("S15 点按高度 ≥40px（min-height:44px）+ 锚点按钮声明 inline-flex 居中无下划线 + 只读探针 writable:false",
        "min-height:44px" in css and "#s-jw #jwOpen{display:inline-flex" in css
        and "text-decoration:none" in css
        and 'defineProperty(window,"JW",{value:probe,writable:false' in js, "")

    # S16 JW JS 块在主 IIFE 作用域内（UG 之后、自身 IIFE 收尾后紧跟主 IIFE 收尾）
    tail = html[js_i:html.find("</script>")] if js_i >= 0 else ""
    add("S16 JW JS 块位于主 IIFE 内（UG 块之后；其后仅 JW IIFE + 主 IIFE 两个 `})();` 收尾）",
        js_i > ug_i >= 0 and tail.count("})();") == 2 and tail.rstrip().endswith("})();"),
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
    var tab=qs.get("tab")||"jw";
    var f=document.createElement("iframe");
    f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block;margin:0 auto;background:#fff";
    f.src="preview.html";
    document.body.appendChild(f);
    await new Promise(function(res){var done=false;f.onload=function(){if(!done){done=true;setTimeout(res,60);}};setTimeout(function(){if(!done){done=true;res();}},9000);});
    var win=f.contentWindow;
    await waitCond(function(){return win&&win.__jwtest&&win.__jwtest.bootDone&&win.__jwtest.bootDone();});
    await sleep(500);
    try{win.__jwtest.gotoTab(tab);}catch(e){}
    await sleep(700);
    if(tab==="all"){
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
    raw = open(SRC, encoding="utf-8", newline="").read()
    results = static_checks(raw)
    tmp = tempfile.mkdtemp(prefix="v2jw_")
    srv = None
    try:
        preview = build_preview()
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(preview)
        body = COMMON_JS + "\n" + MAIN_JS.replace("__URL__", URL)
        harness = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 jw check</title>"
                   "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
                   "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
        open(os.path.join(tmp, "harness.html"), "w", encoding="utf-8", newline="").write(harness)
        open(os.path.join(tmp, "shot.html"), "w", encoding="utf-8", newline="").write(build_shot())
        os.chdir(tmp)
        srv = Q(("127.0.0.1", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run_edge(BASE + "harness.html", budget=60000, win="430,940")
        p = os.path.join(REPORT_DIR, "main.json")
        data = None
        t0 = time.time()
        while time.time() - t0 < 40:
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
            ("01_mobile_430.png", "w=430&h=940&tab=jw", "430,940"),
            ("02_mobile_360.png", "w=360&h=780&tab=jw", "360,780"),
            ("03_mobile_390.png", "w=390&h=844&tab=jw", "390,844"),
            ("04_desktop_1280.png", "w=1280&h=900&tab=jw", "1300,940"),
            ("05_mobile_430_all_cards.png", "w=430&h=940&tab=all", "430,940"),
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
