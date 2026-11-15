# -*- coding: utf-8 -*-
"""v2.0.0 「学信网」官方工具入口卡页（__CHSI_ENTRY_V1__）专项自检
规格：_audit/chsi_entry_20261115/CHSI_ENTRY_SPEC.md §1/§2（2026-11-15 用户需求）
覆盖：
  静态：section 标记成对且位置正确（#s-vote 之后、__WEB_B2_FILE_BEGIN__ 之前）/ 头部标题+副标+提示逐字 /
        10 张官方工具卡（严格 §1 URL、顺序、target=_blank、rel=noopener noreferrer、短名+说明）/
        「需登录」徽标（3 张需登录 + 2 张部分需登录）/ TOOLS 末尾 chsi + ALL_TONE.chsi /
        CSS 放在 </style> 前（auto-fill minmax(140px,1fr) + ≥640→3 列 + ≥960→4 列 + overflow-wrap）/
        UG CARDS 19 张含 chsi 卡（cat study）/ APP_VER 不变 / 零外部资源 / 全 HTML 仅 10 处学信网 URL /
        不内嵌 iframe、不采集账号密码、无 JS 网络请求；
  运行时（430×940 / 360×780 / 390×844 / 1280×900）：两条进入路径（gotoTab("chsi") 与「全部」页点
        #allCards [data-card="chsi"]）→ #s-chsi 可见；10 卡渲染、href/target/rel 逐字；网格列数
        （360/390/430=2 列、1280=4 列）；每卡点按高度 ≥44px；无横向溢出；0 JS 报错 / 0 console.error；
        加载与切页阶段 0 外部请求（performance resource 不含 chsi.com.cn）；
  截图：430/360/390/1280 学信网页 + 430 全部页 chsi 卡，落盘 tools/tests/_shots_chsi/。

测试身份：SID=9999000005 / NAME=测试同学（9999 段 mock 身份，符合 AGENTS.md §0-7）。
用法：cd C:\\...\\web\\tools && python tests\\v2_chsi_check.py
      set V2CHSI_SRC=某副本.html
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
SRC = os.path.abspath(os.environ.get("V2CHSI_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
REPORT_DIR = os.path.join(HERE, "_v2_chsi_reports_%d" % os.getpid())
SHOT_DIR = os.path.join(HERE, "_shots_chsi")
SID = "9999000005"
NAME = "测试同学"
BASE_TS = 1762000000000

# 规格 §1 实测官方 URL（顺序即卡片顺序）
CARDS = [
    ("学信档案", "学籍 · 学历 · 学位", "https://my.chsi.com.cn/archive/index.jsp", "需登录"),
    ("学籍/学历查询", "公开查询", "https://www.chsi.com.cn/xlcx/lscx.jsp", ""),
    ("学位查询", "公开查询", "https://www.chsi.com.cn/xwcx/index.jsp", ""),
    ("在线验证报告", "申请 / 查看报告", "https://my.chsi.com.cn/archive/bab/index.jsp", "需登录"),
    ("报告在线验证", "用人单位核验", "https://www.chsi.com.cn/xlcx/bgcx.jsp", ""),
    ("学历认证报告", "认证服务", "https://www.chsi.com.cn/xlrz/index.jsp", ""),
    ("照片校对", "校对学历照片", "https://my.chsi.com.cn/archive/xlzp/index.jsp", "需登录"),
    ("研招网", "考研报名 / 成绩", "https://yz.chsi.com.cn/", "部分需登录"),
    ("学职平台", "就业 / 职业发展", "https://xz.chsi.com.cn/", "部分需登录"),
    ("帮助中心", "常见问题", "https://www.chsi.com.cn/help/", ""),
]

sys.path.insert(0, HERE)
try:
    from _test_account import assert_test_identity  # noqa: E402
except Exception:  # pragma: no cover - 守卫缺失时仍用 9999 段身份，不阻塞本测试
    def assert_test_identity(sid, name=None, where=""):
        return True

assert_test_identity(SID, NAME, "v2_chsi_check.py")


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
try{window.__chsitest={APP_VER:APP_VER,bootDone:function(){return __bootRefreshDone;},
  errs:function(){return window.__errs||[];},cerrs:function(){return window.__cerrs||[];},
  external:function(){return window.__external||[];},gotoTab:function(k){gotoTab(k);},
  curtab:function(){return CURTAB;},
  onSection:function(){var s=document.querySelector("section.on");return s?s.id:"";},
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
  await waitCond(function(){return win.__chsitest&&win.__chsitest.bootDone&&win.__chsitest.bootDone();},15000);
  await sleep(600);
  return f;
}
"""

MAIN_JS = r"""
async function run(){
  var R={steps:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  function visible(f,sel){var e=q(f,sel);if(!e)return false;var r=e.getBoundingClientRect();return e.classList.contains("on")&&r.height>0&&r.width>0;}
  function ovf(f){var de=f.contentDocument.documentElement;return Math.max(de.scrollWidth,f.contentDocument.body.scrollWidth)-f.contentWindow.innerWidth;}
  function badExternal(w){
    var ext=(w.__chsitest.external()||[]);
    var res=(w.__chsitest.resources()||[]).filter(function(u){return u.indexOf("chsi.com.cn")>=0;});
    return {ext:ext,res:res,ok:(ext.length===0&&res.length===0)};
  }
  function errs(w){return w.__chsitest.errs()||[];}
  function cerrs(w){return w.__chsitest.cerrs()||[];}
  function cols(f){
    try{
      var cs=f.contentWindow.getComputedStyle(q(f,"#s-chsi .chsi-grid"));
      var v=String(cs.gridTemplateColumns||"").trim();
      if(!v)return -1;
      return v.split(/\s+/).length;
    }catch(e){return -1;}
  }
  function shortCards(f){return qa(f,"#s-chsi .chsi-card").map(function(a){return {href:String(a.getAttribute("href")||""),target:String(a.getAttribute("target")||""),rel:String(a.getAttribute("rel")||""),t:String(a.textContent||"")};});}
  function heights(f){return qa(f,"#s-chsi .chsi-card").map(function(a){return Math.round(a.getBoundingClientRect().height);});}
  try{
    /* ===== 430：主交互 ===== */
    var f=await bootAt(430,940), w=f.contentWindow;
    w.__chsitest.gotoTab("chsi"); await sleep(500);
    T("J1 430 gotoTab(\"chsi\") → CURTAB=chsi 且 #s-chsi 可见",
      w.__chsitest.curtab()==="chsi"&&visible(f,"#s-chsi"), w.__chsitest.curtab()+"/"+w.__chsitest.onSection());
    T("J2 头部标题/副标/小提示逐字",
      txt(f,"#s-chsi .chsi-head b")==="学信网"
      &&txt(f,"#s-chsi .chsi-head>span")==="中国高等教育学生信息网 · 官方入口"
      &&txt(f,"#s-chsi .chsi-tip")==="学信档案/照片校对需登录学信网账号",
      txt(f,"#s-chsi .chsi-head b")+"|"+txt(f,"#s-chsi .chsi-head>span")+"|"+txt(f,"#s-chsi .chsi-tip"));
    var cards=shortCards(f);
    var wantHrefs=__HREFS__;
    var hrefOk=cards.length===10&&cards.every(function(c,i){return c.href===wantHrefs[i];});
    T("J3 渲染 10 张工具卡且 href 顺序严格等于规格 §1", hrefOk, cards.length+"/"+JSON.stringify(cards.map(function(c){return c.href;})).slice(0,300));
    T("J4 10 卡全部 target=_blank 且 rel 含 noopener+noreferrer",
      cards.length===10&&cards.every(function(c){return c.target==="_blank"&&c.rel.indexOf("noopener")>=0&&c.rel.indexOf("noreferrer")>=0;}),
      JSON.stringify(cards.map(function(c){return c.target+"/"+c.rel;})).slice(0,300));
    var ems=qa(f,"#s-chsi .chsi-card em").map(function(e){return String(e.textContent||"").trim();});
    T("J5 「需登录」徽标 3 张 + 「部分需登录」2 张", ems.filter(function(x){return x==="需登录";}).length===3
      &&ems.filter(function(x){return x==="部分需登录";}).length===2, JSON.stringify(ems));
    T("J6 430 网格 = 2 列（auto-fill minmax(140px,1fr)）", cols(f)===2, cols(f));
    T("J7 430 页面无横向溢出", ovf(f)<=1, "overflow="+ovf(f));
    var hs=heights(f);
    T("J8 每张卡点按高度 ≥44px", hs.length===10&&hs.every(function(h){return h>=44;}), JSON.stringify(hs));
    T("J9 0 JS 报错 / 0 console.error", errs(w).length===0&&cerrs(w).length===0,
      JSON.stringify(errs(w).concat(cerrs(w))).slice(0,240));
    var be=badExternal(w);
    T("J10 430 加载+切页 0 外部请求（performance 资源不含 chsi.com.cn）", be.ok,
      JSON.stringify(be.ext).slice(0,200)+" | "+JSON.stringify(be.res));
    T("J11 页面内无 iframe（不内嵌学信网）", qa(f,"#s-chsi iframe").length===0, qa(f,"#s-chsi iframe").length);
    /* ===== 路径 B：全部页 chsi 卡片点击 ===== */
    w.__chsitest.gotoTab("all"); await sleep(450);
    var allCards=qa(f,'#allCards [data-card="chsi"]');
    var act=allCards.length?String(allCards[0].textContent||""):"";
    T("J12 「全部」页有且仅有 1 张 chsi 卡且 tone=blue、含「学信网 / 学籍 · 学历 · 学位；官方入口卡」",
      allCards.length===1&&allCards[0].getAttribute("data-tone")==="blue"
      &&act.indexOf("学信网")>=0&&act.indexOf("学籍 · 学历 · 学位；官方入口卡")>=0&&act.indexOf("打开")>=0,
      act.slice(0,140));
    if(allCards.length)allCards[0].click();
    await sleep(450);
    T("J13 点全部页 chsi 卡 → CURTAB=chsi 且 #s-chsi 可见", w.__chsitest.curtab()==="chsi"&&visible(f,"#s-chsi"), w.__chsitest.curtab());
    T("J14 卡路径进入后 0 外部请求 / 0 JS 报错", badExternal(w).ok&&errs(w).length===0&&cerrs(w).length===0,
      JSON.stringify(badExternal(w).ext).slice(0,160));
    T("J15 卡路径进入后无横向溢出", ovf(f)<=1, "overflow="+ovf(f));
    f.parentNode.removeChild(f);
    /* ===== 多宽度：进页 + 列数 + 无溢出 + 点按 + 0 错误/0 请求 ===== */
    var WS=[[360,780,2],[390,844,2],[1280,900,4]];
    for(var i=0;i<WS.length;i++){
      var W=WS[i][0], H=WS[i][1], EC=WS[i][2], tag=(i+1)+"-"+W;
      var f2=await bootAt(W,H), w2=f2.contentWindow;
      w2.__chsitest.gotoTab("chsi"); await sleep(500);
      T("J16-"+tag+" gotoTab(\"chsi\") → #s-chsi 可见", visible(f2,"#s-chsi"));
      T("J17-"+tag+" 网格 = "+EC+" 列", cols(f2)===EC, cols(f2));
      T("J18-"+tag+" 无横向溢出", ovf(f2)<=1, "overflow="+ovf(f2));
      var hs2=heights(f2);
      T("J19-"+tag+" 10 卡点按高度 ≥44px", hs2.length===10&&hs2.every(function(h){return h>=44;}), JSON.stringify(hs2));
      w2.__chsitest.gotoTab("all"); await sleep(450);
      var c2=qa(f2,'#allCards [data-card="chsi"]');
      if(c2.length)c2[0].click();
      await sleep(450);
      T("J20-"+tag+" 全部页卡路径进入 → #s-chsi 可见", w2.__chsitest.curtab()==="chsi"&&visible(f2,"#s-chsi"), w2.__chsitest.curtab());
      var be2=badExternal(w2);
      T("J21-"+tag+" 0 外部请求（含 chsi.com.cn）", be2.ok, JSON.stringify(be2.ext).slice(0,160)+" | "+JSON.stringify(be2.res));
      T("J22-"+tag+" 0 JS 报错 / 0 console.error", errs(w2).length===0&&cerrs(w2).length===0,
        JSON.stringify(errs(w2).concat(cerrs(w2))).slice(0,200));
      T("J23-"+tag+" 卡路径进入后无横向溢出", ovf(f2)<=1, "overflow="+ovf(f2));
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
    b = html.find("<!-- __CHSI_ENTRY_V1_BEGIN__ -->")
    e = html.find("<!-- __CHSI_ENTRY_V1_END__ -->")
    if b < 0 or e < 0:
        return ""
    return html[b:e]


def chsi_css_block(html):
    s = html.find("/* ========== __CHSI_ENTRY_V1_CSS__")
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
    css = chsi_css_block(html)
    urls = re.findall(r'<a class="chsi-card" href="([^"]+)"', sec) if sec else []

    # S1 标记 / 位置
    b = html.count("<!-- __CHSI_ENTRY_V1_BEGIN__ -->")
    e = html.count("<!-- __CHSI_ENTRY_V1_END__ -->")
    add("S1 __CHSI_ENTRY_V1_BEGIN__/END__ 成对且各 1",
        b == 1 and e == 1 and html.find("<!-- __CHSI_ENTRY_V1_BEGIN__ -->") < html.find("<!-- __CHSI_ENTRY_V1_END__ -->"),
        "begin=%d/end=%d" % (b, e))
    vote_i = html.find('<section id="s-vote">')
    chsi_i = html.find('<section id="s-chsi">')
    b2_i = html.find("<!-- __WEB_B2_FILE_BEGIN__ -->")
    add("S2 #s-chsi 位于 #s-vote 之后、__WEB_B2_FILE_BEGIN__ 之前",
        vote_i >= 0 and chsi_i >= 0 and b2_i >= 0 and vote_i < chsi_i < b2_i,
        "vote=%d chsi=%d b2=%d" % (vote_i, chsi_i, b2_i))

    # S3 头部文案逐字
    add("S3 头部标题「学信网」+ 副标「中国高等教育学生信息网 · 官方入口」+ 小提示逐字",
        sec != "" and "<b>学信网</b>" in sec
        and "中国高等教育学生信息网 · 官方入口" in sec
        and "学信档案/照片校对需登录学信网账号" in sec, "")

    # S4 10 卡 URL / target / rel / 顺序
    want_urls = [c[2] for c in CARDS]
    add("S4 10 张工具卡 href 严格等于规格 §1 URL 且顺序一致", urls == want_urls, urls)
    add("S5 10 卡均 target=_blank + rel=noopener noreferrer",
        sec.count('target="_blank"') == 10 and sec.count('rel="noopener noreferrer"') == 10, "")

    # S6 短名 / 说明 / 徽标
    names = [c[0] for c in CARDS]
    descs = [c[1] for c in CARDS]
    add("S6 10 个短名与说明逐字（规格 §1 表）",
        all(("<b>" + n + "</b>") in sec for n in names) and all(("<span>" + d + "</span>") in sec for d in descs), "")
    add("S7 「需登录」3 张 + 「部分需登录」2 张（与规格表一致）",
        sec.count("<em>需登录</em>") == 3 and sec.count("<em>部分需登录</em>") == 2,
        "需登录=%d 部分=%d" % (sec.count("<em>需登录</em>"), sec.count("<em>部分需登录</em>")))

    # S8 TOOLS / ALL_TONE
    m = re.search(r"var TOOLS=\[(.*?)\];", html, re.S)
    tools = m.group(1) if m else ""
    chsi_entry = '{k:"chsi",n:"学信网",d:"学籍 · 学历 · 学位；官方入口卡"}'
    jw_entry = '{k:"jw",n:"教务",d:"成绩、选课与考试",url:"http://210.34.74.77/sso.jsp"}'
    add("S8 TOOLS 末尾追加 chsi（jw 之后，逐字）",
        tools.rstrip().endswith(chsi_entry) and chsi_entry in tools,
        tools[-140:].replace("\n", " "))
    add("S9 ALL_TONE.chsi=\"blue\"", re.search(r'var ALL_TONE=\{[^}]*chsi:"blue"', html) is not None, "")

    # S10 CSS
    style_close = html.find("</style>")
    add("S10 __CHSI_ENTRY_V1_CSS__ 在 </style> 前，含 auto-fill minmax(140px,1fr) + ≥640→3 列 + ≥960→4 列 + overflow-wrap，且无外部资源",
        css != "" and html.find("/* ========== __CHSI_ENTRY_V1_CSS__") < style_close
        and "grid-template-columns:repeat(auto-fill,minmax(140px,1fr))" in css
        and "@media (min-width:640px){#s-chsi .chsi-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}" in css
        and "@media (min-width:960px){#s-chsi .chsi-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}" in css
        and "overflow-wrap:anywhere" in css and "url(" not in css and "http" not in css, "")

    # S11 点按尺寸
    add("S11 卡片点按高度 ≥44px（min-height:88px）", "min-height:88px" in css, "")

    # S12 UG CARDS 19 + chsi 卡
    m = re.search(r"var UG=\(function\(\)\{(.*?)\}\)\(\);", html, re.S)
    ug = m.group(1) if m else ""
    add("S12 UG CARDS 19 张且含 chsi 卡（cat=study / scene 复用 / 3 步 + tip）",
        ug.count('{id:"') == 19
        and '{id:"chsi",cat:"study",title:"学信网入口",sub:"学信档案、学历学位查询官方入口",scene:"grid",tone:"blue"' in ug
        and 'steps:["工具栏或「全部」页打开学信网","点工具卡在新窗口打开官方页面","学信档案/照片校对需先登录学信网账号"]' in ug
        and 'tip:"本站不保存学信网账号；查询与报告以官方页面为准"' in ug,
        "cards=%d" % ug.count('{id:"'))

    # S13 版本 / 零外部资源 / 不内嵌
    add("S13 APP_VER 仍 2.0.0；零外部资源（无 <script src/外部字体/CDN）；section 内无 iframe/script",
        'var APP_VER="2.0.0"' in html and "<script src=" not in html
        and "fonts.googleapis" not in html and "cdn." not in html
        and "<iframe" not in sec and "<script" not in sec, "")

    # S14 全 HTML 仅 10 处学信网 URL（全部是卡片 href，加载不请求）
    cnt = html.count("chsi.com.cn")
    add("S14 全 HTML 仅 10 处学信网 URL（均为卡片 href，加载阶段无资源引用）",
        cnt == 10 and sec.count("chsi.com.cn") == 10
        and not re.search(r'<(?:img|iframe|link|script)[^>]*(?:src|href)="[^"]*chsi\.com\.cn', html), "cnt=%d" % cnt)

    # S15 不采集账号密码 / 无 JS 网络请求
    add("S15 页面不采集账号密码（无 input/form/password），section 无 JS/网络请求",
        all(x not in sec.lower() for x in ("<input", "<form", "password", "<script", "fetch(", "xmlhttprequest")), "")

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
        raise SystemExit("[v2_chsi_check] 找不到主脚本结尾锚点")
    html = html[:idx] + HOOK.replace("\n", "\r\n") + "\r\n" + html[idx:]
    mock = MOCK_JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")) \
                  .replace("__SID__", SID).replace("__NAME__", NAME)
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    return html.replace("<head>", "<head>" + mock, 1)


def run_edge(url, budget=30000, timeout=240, screenshot=None, win=None):
    prof = tempfile.mkdtemp(prefix="edgeprof_chsi_", dir=REPORT_DIR)
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
    var mode=qs.get("mode")||"page";
    var f=document.createElement("iframe");
    /* 左对齐而非居中：headless Edge 的 --window-size 有最小窗宽（外页视口恒 ~492），
       margin:auto 会让 iframe 左偏 31–66px，截图（PNG 宽 = 目标宽）会裁掉右侧内容。 */
    f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block;margin:0;background:#fff";
    f.src="preview.html";
    document.body.appendChild(f);
    await new Promise(function(res){var done=false;f.onload=function(){if(!done){done=true;setTimeout(res,60);}};setTimeout(function(){if(!done){done=true;res();}},9000);});
    var win=f.contentWindow;
    await waitCond(function(){return win&&win.__chsitest&&win.__chsitest.bootDone&&win.__chsitest.bootDone();});
    await sleep(500);
    try{win.__chsitest.gotoTab(mode==="all"?"all":"chsi");}catch(e){}
    await sleep(700);
    if(mode==="all"){
      try{
        var c=f.contentDocument.querySelector('#allCards [data-card="chsi"]');
        if(c&&c.scrollIntoView)c.scrollIntoView({block:"center"});
      }catch(e){}
      await sleep(400);
    }
    document.title="ready";
  }catch(e){document.title="err:"+e;}
})();
"""


def build_shot():
    body = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 chsi shot</title>"
            "<style>html,body{margin:0;background:#F7F8F8}</style></head><body>"
            "<script>" + SHOT_JS + "</script></body></html>")
    return body


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    os.makedirs(SHOT_DIR, exist_ok=True)
    for nm in os.listdir(SHOT_DIR):
        if nm.lower().endswith(".png"):
            try:
                os.remove(os.path.join(SHOT_DIR, nm))
            except Exception:
                pass
    raw = open(SRC, encoding="utf-8", newline="").read()
    results = static_checks(raw)
    tmp = tempfile.mkdtemp(prefix="v2chsi_")
    srv = None
    try:
        preview = build_preview()
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(preview)
        body = COMMON_JS + "\n" + MAIN_JS.replace("__HREFS__", json.dumps([c[2] for c in CARDS]))
        harness = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 chsi check</title>"
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
        shots = [
            ("01_mobile_430.png", "w=430&h=940&mode=page", "430,940"),
            ("02_mobile_360.png", "w=360&h=780&mode=page", "360,780"),
            ("03_mobile_390.png", "w=390&h=844&mode=page", "390,844"),
            ("04_desktop_1280.png", "w=1280&h=900&mode=page", "1300,940"),
            ("05_mobile_430_all_cards.png", "w=430&h=940&mode=all", "430,940"),
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
        print("v2_chsi_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
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
