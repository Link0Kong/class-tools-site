# -*- coding: utf-8 -*-
"""v2 专项自检：网页移植 v1（task-64，2026-11-15）

覆盖本次网页可完整移植项：
  A. 外观：跟随系统 / 浅色 / 深色（本机 localStorage，三选一；首帧防闪白；深色覆盖层；通知 iframe 同步）
  B. 通知「自动全部加载」网页语义：整表一次拉取 + 加载进度 + 失败保留/重试 + 无「加载更多」按钮
  C. 工具卡片描述两行完整显示（430/960/1320 无裁切、≤2 行）
  D. 浅色主题底部弹层无纯黑硬影（.dropctl-card 暖色柔和投影）
  E. 顶部留白（桌面 ≥960 呼吸位加大，手机 safe-area 逻辑不变）
  F. 平板/桌面 ≥960/1320 响应式：容器宽度/卡片列数/底部行对齐/无横向溢出
  G. 红线：APP_VER 仍 2.0.0、无外部请求、0 JS 报错

用法：cd C:\\Users\\Ko_Li\\.openclaw\\workspace\\web\\tools && python tests\\v2_port_ui_check.py
      可用 V2PORT_SRC 指向副本；退出码 0 = 全绿。
"""
import base64
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
SRC = os.path.abspath(os.environ.get("V2PORT_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE):
    EDGE = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
PORT = 8996
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_v2_port_reports")
SID = "9999000005"
NAME = "测试同学"
AN_PREFIX = "[[CLASS_NOTICE_V1]]"
BASE_TS = 1762000000000
NOTICE_N = 8


def members():
    out = []
    for i in range(1, 72):
        out.append({"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
                    "role": "班长" if i == 1 else "", "badge": "班委" if i == 1 else "",
                    "is_admin": i == 1})
    return out


def notice_rows():
    rows = []
    cats = ["学习", "考试", "生活", "志愿", "教务", "活动", "提醒", "其他"]
    for i in range(NOTICE_N):
        g = {"id": "g_p%d" % i, "cat": cats[i % len(cats)], "title": "合成通知 %02d" % (i + 1),
             "summary": "第 %d 条合成通知摘要" % (i + 1), "deadline": "",
             "items": [{"kind": "text", "label": "原始通知", "time": "12-01 10:00",
                        "from": "班委", "text": "合成通知正文 %d" % (i + 1)}],
             "source": "QQ 群", "group": "班群"}
        rows.append({"id": "auto_g%d" % i, "title": "", "archived": False,
                     "body": AN_PREFIX + json.dumps(g, ensure_ascii=False),
                     "hidden": False, "override_json": "", "edited_at": 0,
                     "ts": BASE_TS + i * 1000})
    return rows


DATA = {
    "members": members(),
    "notices": notice_rows(),
    "homework": [
        {"id": "hw1", "subject": "英语", "content": "Unit 3 课后练习", "due": "12-01 上课前",
         "date": "2026-12-01", "time": "", "done": False, "author": "学委", "ts": BASE_TS, "attachments": ""},
    ],
    "marks": [], "fitrecs": [],
    "tt": {"c": [], "t": "2026-08-31"},
}

MOCK_JS = r"""
<script>
(function(){
window.__errs=[];window.__cerrs=[];window.__external=[];window.__noticeCalls=0;
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var DATA=__DATA__;
var P=new URLSearchParams(location.search||"");
var AP=P.get("ap");
try{
  if(AP)localStorage.setItem("zq_appearance_v1",AP); else localStorage.removeItem("zq_appearance_v1");
}catch(e){}
/* 跟随系统：可控的 matchMedia mock（只在测试页生效；其它查询走真实实现） */
var __SYS=(P.get("sys")||"light")==="dark", __mqCbs=[];
var _mm=window.matchMedia?window.matchMedia.bind(window):null;
window.matchMedia=function(q){
  if(String(q).indexOf("prefers-color-scheme")>=0){
    return {media:q,matches:__SYS,onchange:null,
      addEventListener:function(t,cb){if(t==="change")__mqCbs.push(cb);},
      removeEventListener:function(t,cb){__mqCbs=__mqCbs.filter(function(x){return x!==cb;});},
      addListener:function(cb){__mqCbs.push(cb);},removeListener:function(){},
      dispatchEvent:function(){return false;}};
  }
  return _mm?_mm(q):{media:q,matches:false,addEventListener:function(){},removeEventListener:function(){},addListener:function(){},removeListener:function(){}};
};
window.__setSysDark=function(v){__SYS=!!v;__mqCbs.forEach(function(cb){try{cb({matches:__SYS,media:"(prefers-color-scheme: dark)"});}catch(e){}});};
var SID=P.get("sid")||"__SID__";
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:SID,name:"__NAME__",role:"班长",badge:"班委",is_admin:true,ts:Date.now()}));}catch(e){}
function ok(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
var __slow=P.get("slow")==="1", __fail=P.get("fail")==="1";
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};var s=String((u&&u.url!==undefined)?u.url:u);
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0)return ok(DATA.members);
    if(s.indexOf("rpc/class_league")>=0)return ok({ok:true,members:DATA.members.slice(0,20)});
    if(s.indexOf("rpc/class_whoami")>=0)return ok({ok:true,sid:SID,name:"__NAME__"});
    if(s.indexOf("/notices")>=0){
      if(s.indexOf("select=id,ts")>=0)return ok(DATA.notices.map(function(r){return {id:r.id,ts:r.ts,hidden:!!r.hidden,edited_at:Number(r.edited_at)||0};}));
      window.__noticeCalls++;
      if(__fail&&window.__noticeCalls===1)return Promise.reject(new Error("mock-notice-fail"));
      if(__slow)return new Promise(function(res){setTimeout(function(){res(ok(DATA.notices));},500);});
      return ok(DATA.notices);
    }
    if(s.indexOf("/homework")>=0)return ok(DATA.homework);
    if(s.indexOf("/marks")>=0)return ok(DATA.marks);
    if(s.indexOf("/fitrecs")>=0)return ok(DATA.fitrecs);
    if(s.indexOf("/userdata")>=0)return ok([]);
    if(s.indexOf("/visits")>=0)return ok([]);
    if(s.indexOf("/power")>=0)return ok([]);
    if(s.indexOf("ppt_decks")>=0)return ok([]);
    if(s.indexOf("rpc/poll_list")>=0)return ok({ok:true,polls:[]});
    if(s.indexOf("rpc/")>=0)return ok({ok:true,rows:[],items:[]});
    return ok([]);
  }
  if(s.indexOf("tt.json")>=0)return ok(DATA.tt);
  if(s.indexOf("/drop/presence")>=0)return ok({ok:true,stage:false,at:0});
  window.__external.push(s);
  return _f.apply(this,arguments);
};
})();
</script>
"""

HOOK = r"""
window.__v2port={APP_VER:APP_VER,errs:function(){return window.__errs||[];},
  cerrs:function(){return window.__cerrs||[];},external:function(){return window.__external||[];},
  noticeCalls:function(){return window.__noticeCalls||0;},bootDone:function(){return !!__bootRefreshDone;}};
"""

COMMON_JS = r"""
var SRC="preview.html";
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
async function pump(){return new Promise(function(res){try{var ch=new MessageChannel();ch.port1.onmessage=function(){res();};ch.port2.postMessage(0);}catch(e){setTimeout(res,0);}});}
async function raf(n){for(var i=0;i<(n||3);i++){await new Promise(function(r){var done=false;function go(){if(done)return;done=true;r();}try{requestAnimationFrame(go);}catch(e){}setTimeout(go,50);});}}
async function waitCond(fn,ms){
  var t0=Date.now();
  while(Date.now()-t0<(ms||8000)){
    var v=false;try{v=!!fn();}catch(e){v=false;}
    if(v)return true;
    await sleep(60);
  }
  return false;
}
function mount(src,w,h){
  return new Promise(function(res,rej){
    try{sessionStorage.removeItem("zq_pos_v1");}catch(e){}
    var old=document.getElementById("fr");if(old&&old.parentNode)old.parentNode.removeChild(old);
    var f=document.createElement("iframe");f.id="fr";
    f.style.cssText="position:absolute;left:0;top:0;width:"+w+"px;height:"+h+"px;border:0;display:block";
    f.src=src;
    var done=false;
    f.onload=function(){if(done)return;done=true;setTimeout(function(){res(f);},80);};
    f.onerror=function(){if(done)return;done=true;rej(new Error("iframe load failed"));};
    document.body.appendChild(f);
    setTimeout(function(){if(!done){done=true;res(f);}},15000);
  });
}
function report(slot,data){
  data=data||{};data.slot=slot;
  try{var x=new XMLHttpRequest();x.open("POST","/_report?slot="+slot,false);
      x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(data));}catch(e){}
}
function lum(c){
  var m=String(c||"").match(/rgba?\(([^)]+)\)/);
  if(!m)return -1;
  var p=m[1].split(",").map(function(x){return parseFloat(x);});
  var r=p[0]/255,g=p[1]/255,b=p[2]/255,a=p.length>3?p[3]:1;
  if(a<=0.05)return -1;
  function f(v){return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);}
  return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b);
}
function contrast(c1,c2){
  var l1=lum(c1),l2=lum(c2);
  if(l1<0||l2<0)return -1;
  var hi=Math.max(l1,l2),lo=Math.min(l1,l2);
  return (hi+0.05)/(lo+0.05);
}
"""

MAIN_JS = r"""
async function run(){
  var R={steps:[]}, allErrs=[], allCerrs=[], allExternal=[];
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  function q(f,s){return f.contentDocument.querySelector(s);}
  function qa(f,s){return Array.prototype.slice.call(f.contentDocument.querySelectorAll(s));}
  async function open(query,w,h){
    try{localStorage.removeItem("zq_appearance_v1");}catch(e){}
    var f=await mount(SRC+query,w,h);
    var ww=f.contentWindow;
    await waitCond(function(){return ww.__v2port&&ww.__v2port.bootDone();},15000);
    await sleep(650);
    return f;
  }
  function collect(f){
    try{
      var w=f.contentWindow;
      allErrs=allErrs.concat(w.__v2port.errs()||[]);
      allCerrs=allCerrs.concat(w.__v2port.cerrs()||[]);
      allExternal=allExternal.concat(w.__v2port.external()||[]);
    }catch(e){}
  }
  try{
    /* ---------- A. 外观三态 ---------- */
    var f=await open("?ap=light",430,1200);
    collect(f);
    /* 外观计算样式断言前关闭过渡（headless 虚拟时间下 transition 可能停在首帧，测的是最终皮肤而非动画中间态） */
    (function(){try{var st=f.contentDocument.createElement("style");st.id="__v2port_notrans";
      st.textContent="*{transition:none!important;animation:none!important}";
      f.contentDocument.head.appendChild(st);}catch(e){}})();
    var de=f.contentDocument.documentElement;
    T("A1 默认浅色：html[data-appearance=light]", de.getAttribute("data-appearance")==="light", de.getAttribute("data-appearance"));
    T("A2 本机存储键 zq_appearance_v1=light", (function(){try{return localStorage.getItem("zq_appearance_v1")==="light";}catch(e){return false;}})(), "");
    var apBtn=q(f,"#apBtn"), bkBtn=q(f,"#optBkBtn");
    T("A3 全部页底部有「外观」「数据备份」入口", !!apBtn&&!!bkBtn, (apBtn?apBtn.textContent:"-")+"/"+(bkBtn?bkBtn.textContent:"-"));
    apBtn.click(); await sleep(120);
    var ov=q(f,"#apOv"), opts=qa(f,"#apOv [data-ap]");
    T("A4 外观弹层可打开且三选一", !!ov&&ov.style.display!=="none"&&opts.length===3,
      opts.map(function(b){return b.getAttribute("data-ap");}).join(","));
    T("A5 三选项文案=跟随系统/浅色/深色",
      opts.length===3&&String(opts[0].textContent).indexOf("跟随系统")>=0&&String(opts[1].textContent).indexOf("浅色")>=0&&String(opts[2].textContent).indexOf("深色")>=0,
      opts.map(function(b){return String(b.textContent).trim();}).join("|"));
    opts[2].click(); await sleep(60); await raf(8); await sleep(260);
    T("A6 选深色即时生效（html[data-appearance=dark]）", de.getAttribute("data-appearance")==="dark", de.getAttribute("data-appearance"));
    T("A7 深色写入本机 zq_appearance_v1", (function(){try{return localStorage.getItem("zq_appearance_v1")==="dark";}catch(e){return false;}})(), "");
    T("A8 深色选中态 aria-checked=true", opts[2].getAttribute("aria-checked")==="true"&&opts[0].getAttribute("aria-checked")==="false", "");
    var bodyCS=f.contentWindow.getComputedStyle(q(f,"body"));
    var bodyBgImg=String(bodyCS.backgroundImage||"");
    var bgs=(bodyBgImg.match(/rgba?\([^)]+\)/g)||[]);
    var bgLums=bgs.map(lum).filter(function(x){return x>=0;});
    var maxBgLum=bgLums.length?Math.max.apply(null,bgLums):-1;
    T("A9 深色页面底色变暗（背景渐变各色相对亮度<0.25）", maxBgLum>=0&&maxBgLum<0.25,
      "maxLum="+maxBgLum.toFixed(3)+" n="+bgLums.length);
    var cardCS=f.contentWindow.getComputedStyle(q(f,".card"));
    var cardBg=cardCS.backgroundColor, cardInk=cardCS.color;
    var cr=contrast(cardInk,cardBg);
    T("A10 深色卡片正文对比度≥4.5", cr>=4.5, "ratio="+(cr>=0?cr.toFixed(2):cr)+" bg="+cardBg+" ink="+cardInk);
    var tc=q(f,"#themeColorMeta");
    T("A11 theme-color 随深色更新", !!tc&&tc.getAttribute("content")==="#111614", tc?tc.getAttribute("content"):"");
    /* 回到浅色 / 关闭弹层 */
    opts[1].click(); await sleep(120);
    T("A12 切回浅色即时生效", de.getAttribute("data-appearance")==="light", de.getAttribute("data-appearance"));
    q(f,"#apClose").click(); await sleep(80);
    T("A13 外观弹层可关闭", ov.style.display==="none", ov.style.display);
    collect(f);

    /* ---------- B. 跟随系统（matchMedia mock 可控） ---------- */
    f=await open("?ap=system&sys=dark",430,1200);
    collect(f);
    de=f.contentDocument.documentElement;
    T("B1 跟随系统：系统深色→解析深色", de.getAttribute("data-appearance")==="dark"&&de.getAttribute("data-appearance-mode")==="system",
      de.getAttribute("data-appearance")+"/"+de.getAttribute("data-appearance-mode"));
    await f.contentWindow.eval("__setSysDark(false)");
    await waitCond(function(){return de.getAttribute("data-appearance")==="light";},3000);
    T("B2 系统切浅色→自动跟随变浅色", de.getAttribute("data-appearance")==="light", de.getAttribute("data-appearance"));
    await f.contentWindow.eval("__setSysDark(true)");
    await waitCond(function(){return de.getAttribute("data-appearance")==="dark";},3000);
    T("B3 系统切深色→自动跟随变深色", de.getAttribute("data-appearance")==="dark", de.getAttribute("data-appearance"));
    collect(f);

    /* ---------- C. 深色持久化（重开仍深色，首帧脚本应用） ---------- */
    f=await open("?ap=dark",430,1200);
    collect(f);
    de=f.contentDocument.documentElement;
    T("C1 本机存深色时重开保持深色", de.getAttribute("data-appearance")==="dark"&&de.getAttribute("data-appearance-mode")==="dark",
      de.getAttribute("data-appearance")+"/"+de.getAttribute("data-appearance-mode"));

    /* ---------- D. 通知：自动全部加载 / 进度 / 重试 / iframe 深色 ---------- */
    f=await open("?ap=light&slow=1&sid=9999000201",430,1400);
    collect(f);
    q(f,'[data-tab="nt"]').click();
    var ww=f.contentWindow;
    var sawLoading=await waitCond(function(){return ww.__NT_PROGRESS&&ww.__NT_PROGRESS().loading;},5000);
    var prog=q(f,"#noticeHost .nt-progress"), hint=q(f,"#noticeHost .nt-loadtxt");
    T("D1 加载中显示进度（.nt-progress + 文案）", sawLoading&&!!prog&&!!hint&&String(hint.textContent).indexOf("正在加载全部通知")>=0,
      sawLoading?("prog="+!!prog+" hint="+(hint?hint.textContent:"")):"no-loading");
    T("D2 加载中不出现「加载更多」按钮", !q(f,"#noticeHost .notice-empty button")&&String(f.contentDocument.body.textContent||"").indexOf("加载更多")<0, "");
    var okAll=await waitCond(function(){try{return q(f,"#noticeHost iframe")&&q(f,"#noticeHost iframe").contentDocument.querySelectorAll(".gcard").length>=8;}catch(e){return false;}},9000);
    var nCards=0;try{nCards=q(f,"#noticeHost iframe").contentDocument.querySelectorAll(".gcard").length;}catch(e){}
    T("D3 自动全部加载：8 条通知全部渲染（无需点更多）", okAll&&nCards>=8, "cards="+nCards);
    T("D4 加载完成后进度消失", !q(f,"#noticeHost .nt-progress"), "");
    T("D5 通知 iframe 内无「加载更多/加载全部」按钮",
      (function(){try{var doc=q(f,"#noticeHost iframe").contentDocument;return String(doc.body.textContent||"").indexOf("加载更多")<0&&String(doc.body.textContent||"").indexOf("加载全部")<0;}catch(e){return false;}})(), "");
    T("D6 浅色下通知 iframe 保持浅色", (function(){try{return !q(f,"#noticeHost iframe").contentDocument.documentElement.getAttribute("data-appearance");}catch(e){return false;}})(), "");
    await ww.eval("APPEARANCE.apply('dark',true)");
    await sleep(200);
    T("D7 切深色后通知 iframe 同步深色", (function(){try{return q(f,"#noticeHost iframe").contentDocument.documentElement.getAttribute("data-appearance")==="dark";}catch(e){return false;}})(), "");
    collect(f);

    /* 失败重试 */
    f=await open("?ap=light&fail=1&sid=9999000202",430,1400);
    collect(f);
    q(f,'[data-tab="nt"]').click();
    var sawFail=await waitCond(function(){return !!q(f,"#noticeHost .notice-fail");},9000);
    var retry=q(f,"#ntRetry");
    T("D8 通知加载失败显示失败态 + 重试按钮", sawFail&&!!retry, sawFail?("text="+String(q(f,"#noticeHost .notice-fail").textContent)):"no-fail-ui");
    if(retry){retry.click();}
    var recovered=await waitCond(function(){try{return q(f,"#noticeHost iframe")&&q(f,"#noticeHost iframe").contentDocument.querySelectorAll(".gcard").length>=8;}catch(e){return false;}},9000);
    T("D9 点重试后成功加载全部通知", recovered, "calls="+f.contentWindow.__v2port.noticeCalls());
    collect(f);

    /* ---------- E. 描述两行 / 底部软影 / 顶部留白 / 响应式 ---------- */
    async function descChecks(label,w,h){
      var ff=await open("?ap=light&sid=99990003"+String(w).slice(-2),w,h);
      collect(ff);
      q(ff,'[data-tab="all"]').click(); await sleep(250);
      var ds=qa(ff,"#allCards .tdesc"), bad=[], long=[];
      ds.forEach(function(el){
        var cs=ff.contentWindow.getComputedStyle(el), lh=parseFloat(cs.lineHeight)||19.2;
        var r=el.getBoundingClientRect();
        var lines=Math.round(r.height/lh);
        if(el.scrollHeight>el.clientHeight+1)bad.push(el.textContent.slice(0,12));
        if(lines>2)long.push(el.textContent.slice(0,12)+":"+lines);
      });
      T("E"+label+"1 工具卡片描述无裁切（"+(label==="1"?"430":"960/1320")+"）", ds.length>=17&&bad.length===0, "n="+ds.length+" bad="+JSON.stringify(bad));
      T("E"+label+"2 工具卡片描述≤2 行（不省略号截断当前文案）", long.length===0, JSON.stringify(long));
      T("E"+label+"3 描述两行盒模型生效（-webkit-line-clamp:2）",
        (function(){try{return String(ff.contentWindow.getComputedStyle(q(ff,"#allCards .tdesc")).webkitLineClamp)==="2";}catch(e){return false;}})(), "");
      var de2=ff.contentDocument.documentElement;
      T("E"+label+"4 无横向溢出", de2.scrollWidth<=de2.clientWidth+1, de2.scrollWidth+"/"+de2.clientWidth);
      var brand=q(ff,".brand"), bp=brand?parseFloat(ff.contentWindow.getComputedStyle(brand).paddingTop)||0:0;
      if(label==="1"){
        T("E14 手机顶部留白=15+safe-area 逻辑", bp>=14&&bp<=17, "padTop="+bp);
      }else{
        T("E"+label+"5 桌面顶部留白≥22px", bp>=22, "padTop="+bp);
      }
      var isDesktop=(label!=="1");
      var wrap=q(ff,".wrap"), wrapW=wrap?Math.round(wrap.getBoundingClientRect().width):0;
      var cards=q(ff,"#allCards"), cardsR=cards?cards.getBoundingClientRect():null;
      var row=q(ff,"#optBkRow"), rowR=row?row.getBoundingClientRect():null;
      if(label==="1"){
        T("E15 手机容器宽度=min(880,vW)（居中）", Math.abs(wrapW-Math.min(880,w))<=2, "wrap="+wrapW);
      }else if(label==="2"){
        T("E25 ≥960 容器宽度=min(1120,vw-48)", Math.abs(wrapW-Math.min(1120,w-48))<=2, "wrap="+wrapW);
        var cols=(ff.contentWindow.getComputedStyle(cards).gridTemplateColumns||"").split(" ").filter(Boolean).length;
        T("E26 ≥960 全部页卡片≥3 列", cols>=3, "cols="+cols);
      }else{
        var iw=0,fw=0;try{iw=ff.contentWindow.innerWidth||0;fw=ff.clientWidth||0;}catch(e){}
        T("E36 ≥1320 容器宽度跟随档位", Math.abs(wrapW-Math.min(1320,w-64))<=2, "wrap="+wrapW+" innerWidth="+iw+" iframe="+fw+" want="+Math.min(1320,w-64));
        var cols2=(ff.contentWindow.getComputedStyle(cards).gridTemplateColumns||"").split(" ").filter(Boolean).length;
        T("E37 ≥1320 全部页卡片≥4 列", cols2>=4, "cols="+cols2);
      }
      T("E"+label+"6 底部「外观/数据备份」行与卡片网格右缘对齐",
        !!cardsR&&!!rowR&&Math.abs(rowR.right-cardsR.right)<=2,
        rowR?Math.round(rowR.right)+" vs "+Math.round(cardsR.right):"missing");
      T("E"+label+"7 底部行含外观+数据备份", !!q(ff,"#optBkRow #apBtn")&&!!q(ff,"#optBkRow #optBkBtn")&&q(ff,"#optBkRow").querySelectorAll("button").length===2,
        row?(row.querySelectorAll("button").length+"btn"):"none");
      /* 浅色底部弹层阴影：无纯黑硬影 */
      var probeEl=ff.contentDocument.createElement("div");probeEl.className="dropctl-card";
      ff.contentDocument.body.appendChild(probeEl);
      var sh=ff.contentWindow.getComputedStyle(probeEl).boxShadow||"";
      probeEl.parentNode.removeChild(probeEl);
      T("E"+label+"8 浅色底部弹层阴影非纯黑（柔和暖影）", !!sh&&sh.indexOf("rgb(0, 0, 0)")<0&&sh.indexOf("rgba(0, 0, 0")<0, sh.slice(0,80));
      collect(ff);
    }
    await descChecks("1",430,1400);
    await descChecks("2",960,1500);
    await descChecks("3",1320,1600);

    /* ---------- F. 红线 ---------- */
    T("F1 APP_VER 仍 2.0.0", (function(){var f0=document.getElementById("fr");try{return f0.contentWindow.__v2port.APP_VER==="2.0.0";}catch(e){return false;}})(), "");
    T("F2 全程 0 JS 报错", allErrs.length===0, JSON.stringify(allErrs).slice(0,300));
    T("F3 全程 0 console.error", allCerrs.length===0, JSON.stringify(allCerrs).slice(0,300));
    T("F4 全程 0 外部请求", allExternal.length===0, JSON.stringify(allExternal).slice(0,300));
  }catch(e){
    R.steps.push({k:"脚本异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("main",R);
}
run();
"""


def build_preview():
    html = open(SRC, encoding="utf-8", newline="").read()
    idx = html.rfind("})();")
    if idx < 0:
        raise SystemExit("[v2_port_ui_check] 找不到主脚本结尾锚点")
    html = html[:idx] + HOOK + "\n" + html[idx:]
    mock = MOCK_JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")) \
                  .replace("__SID__", SID).replace("__NAME__", NAME)
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    return html.replace("<head>", "<head>" + mock, 1)


def static_checks(raw):
    out = []

    def has(pat, label, neg=False):
        ok = bool(re.search(pat, raw, re.S))
        if neg:
            ok = not ok
        out.append({"k": label, "ok": ok, "note": ""})

    has(r'var APP_VER="2\.0\.0"', "S1 源码 var APP_VER=\"2.0.0\"")
    boot = raw.find("__APPEARANCE_BOOT_V1__")
    style = raw.find("<style>")
    has(r"__APPEARANCE_BOOT_V1__", "S2 存在外观首帧脚本")
    out.append({"k": "S3 首帧脚本在样式表之前（防深色闪白）", "ok": boot > 0 and style > 0 and boot < style,
                "note": "boot=%d style=%d" % (boot, style)})
    has(r"zq_appearance_v1", "S4 本机存储键 zq_appearance_v1")
    has(r'data-appearance="dark"', "S5 深色覆盖选择器存在")
    dark_start = raw.find("/* __DARK_THEME_BEGIN__ */")
    dark_end = raw.find("/* __DARK_THEME_END__ */")
    dark_len = (dark_end - dark_start) if (dark_start >= 0 and dark_end > dark_start) else 0
    out.append({"k": "S6 深色生成覆盖层体量（>15000 字符）", "ok": dark_len > 15000, "note": "len=%d" % dark_len})
    has(r"--bg:#111614", "S7 深色基线变量 --bg:#111614")
    has(r"-webkit-line-clamp:2", "S8 工具卡片描述两行盒模型")
    has(r"\.dropctl-card\{box-shadow:0 -14px 36px rgba\(35,48,46,\.18\)\}", "S9 浅色底部弹层暖色柔和投影")
    has(r"@media \(min-width:960px\)\{\.brand\{padding:22px 0 14px\}\}", "S10 桌面顶部留白（≥960 22px）")
    has(r"function noticeLoadingHTML\(", "S11 通知加载进度实现")
    has(r"function noticeFailHTML\(", "S12 通知失败重试实现")
    has(r"function noticeApplyAppearance\(", "S13 通知 iframe 深色同步函数")
    has(r"noticeApplyAppearance\(doc\)", "S14 renderNoticeFrame 调用深色同步")
    has(r'id="themeColorMeta"', "S15 theme-color meta 存在")
    has(r'data-ap="system"', "S16 外观三选一：跟随系统")
    has(r'data-ap="dark"', "S17 外观三选一：深色")
    has(r"<script src=", "S18 无外部脚本引用", neg=True)
    has(r"fonts\.googleapis|cdn\.", "S19 无外部字体/CDN 引用", neg=True)

    # 通知模板（NOTICE_TPL_B64）：无「加载更多/加载全部」按钮；含深色覆盖
    m = re.search(r'var NOTICE_TPL_B64="([^"]*)"', raw)
    tpl = ""
    if m:
        try:
            tpl = base64.b64decode(m.group(1)).decode("utf-8", "replace")
        except Exception:
            tpl = ""
    out.append({"k": "S20 通知模板无「加载更多/加载全部」按钮文案",
                "ok": bool(tpl) and "加载更多" not in tpl and "加载全部" not in tpl, "note": "tpl=%d" % len(tpl)})
    out.append({"k": "S21 通知模板内置深色覆盖（data-appearance=dark）",
                "ok": 'html[data-appearance="dark"]' in tpl, "note": ""})
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


def run_edge(url, budget=60000, timeout=300):
    prof = tempfile.mkdtemp(prefix="edgeprof_", dir=REPORT_DIR)
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=520,940",
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
    except OSError:
        pass
    raw = open(SRC, encoding="utf-8", newline="").read()
    results = static_checks(raw)
    tmp = tempfile.mkdtemp(prefix="v2port_")
    srv = None
    try:
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(build_preview())
        body = COMMON_JS + "\n" + MAIN_JS
        harness = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 port ui check</title>"
                   "<style>html,body{margin:0;height:100%;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
                   "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
        open(os.path.join(tmp, "harness.html"), "w", encoding="utf-8", newline="").write(harness)
        os.chdir(tmp)
        srv = Q(("127.0.0.1", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run_edge(BASE + "harness.html")
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
        else:
            results.append({"k": "运行时结果上报", "ok": False, "note": "未收到报告（页面可能未启动/崩溃）"})
        passed = 0
        for s in results:
            if s["ok"]:
                passed += 1
            else:
                print(("[FAIL] " if True else "") + s["k"] + ((" | " + str(s["note"])) if s.get("note") else ""))
        print("=" * 64)
        print("v2_port_ui_check: %d 项，PASS %d，FAIL %d" % (len(results), passed, len(results) - passed))
        print("=" * 64)
        sys.exit(0 if results and passed == len(results) else 1)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
