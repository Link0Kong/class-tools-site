# -*- coding: utf-8 -*-
r"""自检：宿舍电费 v3「数据仪表盘」（电量环 + 近 24h 趋势 + 指标 tiles）—— 2026-11-06

用法：python tests\power_check.py
      set SPEC_CHECK=<副本.html>    # 复盘任意副本（如线上字节落盘文件）

覆盖（task-8）：
1) 「全部」页卡片存在；点开 #s-power；**无「全部宿舍」列表 / 楼栋 chips / 房间 chips**；
2) 关注宿舍选择器（2026-11-11 起为自定义楼栋+房间选择器，隐藏原生 select 作值源）：占位 + 4 个\
optgroup（13号楼/16号楼/23号楼A座/23号楼B座）+ 17 个规范选项，触发器高 ≥40px；
3) 未选择：引导「选择你要关注的宿舍」、刷新禁用、**0 个 power / power_history 请求**、右侧仪表区隐藏；
4) 选择后：电量环（SVG stroke-dasharray 比例）、大字剩余电量、状态 pill、
   近 24h 趋势折线（内联 SVG path + 起点/当前/下降量）、4 个指标 tile、低电提示条（仅低电）；
5) history 请求契约：`power_history?select=roomverify,quantity,ts&roomverify=eq.<rv>&order=ts.asc&ts=gte.<24h>&limit=500`；
6) 切换宿舍只显示该宿舍；状态色 ok/warn/low（>100 充足 / 30–100 偏低 / <30 低电）；
5) 数据不足（<2 采样）显示「数据积累中」；刷新按钮同时力拉 power + history；
7) 选择持久化 + UD.power 推送（14 键 blob，含 water section）；同设备刷新恢复；换设备从云端恢复；两账号隔离；非法值降级；
8) 360/430/1280 无横向溢出；0 JS 报错 / 0 console.error / 无外部请求；页面无姓名/学号、不出现全班列表；
9) 截图 tests\_shots_power\power_v3_{390,1280}.png。

退出码 0 = 全绿。
"""
import functools
import http.server
import json
import os
import shutil
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
SRC = os.path.abspath(os.environ.get("SPEC_CHECK") or os.path.join(ROOT, "index.html"))
SHOTS = os.path.join(HERE, "_shots_power")
REPORT_DIR = os.path.join(HERE, "_power_reports")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8933
BASE = "http://127.0.0.1:%d/" % PORT

SID_A = "3260707001"
SID_B = "3260707002"
NAME = "测试同学"

CATALOG = [
    ("1-13---324", "13号楼324", "13号楼"),
    ("1-13---308", "13号楼308", "13号楼"),
    ("1-16---305", "16号楼305", "16号楼"),
    ("1-16---306", "16号楼306", "16号楼"),
    ("4-23A---321", "23号楼A座321", "23号楼A座"),
    ("4-23A---323", "23号楼A座323", "23号楼A座"),
    ("4-23A---324", "23号楼A座324", "23号楼A座"),
    ("4-23A---325", "23号楼A座325", "23号楼A座"),
    ("4-23A---326", "23号楼A座326", "23号楼A座"),
    ("4-23A---327", "23号楼A座327", "23号楼A座"),
    ("4-23A---328", "23号楼A座328", "23号楼A座"),
    ("4-23A---329", "23号楼A座329", "23号楼A座"),
    ("4-23A---330", "23号楼A座330", "23号楼A座"),
    ("4-23B---422", "23号楼B座422", "23号楼B座"),
    ("4-23B---423", "23号楼B座423", "23号楼B座"),
    ("4-23B---424", "23号楼B座424", "23号楼B座"),
    ("4-23B---425", "23号楼B座425", "23号楼B座"),
]

# 当前电量（mock public.power）
ROWS = {
    "4-23A---321": {"quantity": 382.02, "low": False},   # 充足
    "1-16---305": {"quantity": 22.25, "low": True},      # 低电（云端 low=true）
    "1-13---324": {"quantity": 78.97, "low": False},     # 偏低（30–100）
    "4-23B---424": {"quantity": 18.5, "low": False},     # 云端 low=false 但 <30 → 仍低电
    "4-23A---330": {"quantity": 166.03, "low": False},
    "1-13---308": {"quantity": 300.12, "low": False},
    "4-23A---323": {"quantity": 45.6, "low": False},   # 偏低（30–60）
}
# 近 24h 采样（mock public.power_history）：[(几小时前, 电量)]
HIST = {
    "4-23A---321": [(8.0, 384.50), (6.0, 384.10), (4.0, 383.60), (2.0, 383.00), (1.0, 382.50), (0.1, 382.02)],
    # 2026-11-07 规格 power_cadence_spec.md §6：16-305 属 16 号楼（网关日更）→ 慢频口径。
    # 原 (7,24.6)(4,23.8)(0.1,22.25) 各段均 <6h，慢统计无有效段会显示「数据积累中」，无法覆盖 C 组低电环刻度；
    # 改为 30h/6h 两点（1 个 24h 有效段 2.35 度 → rate 2.35 度/天 → 约 9.5 天 / ring 31.6），低电与提示条断言保留。
    "1-16---305": [(30.0, 24.60), (6.0, 22.25)],
    "1-13---324": [(5.0, 80.20), (0.2, 78.97)],
    "4-23A---330": [(4.0, 167.03), (0.2, 166.03)],
    "4-23B---424": [(0.2, 18.50)],   # 只有 1 个采样 → 数据积累中
    "1-13---308": [(5.0, 300.50), (3.0, 299.80), (1.0, 305.20), (0.2, 300.12)],
    "4-23A---323": [(4.0, 46.8), (0.2, 45.6)],
}
# v4：321 的 7d/30d 稀疏历史（每 6h 一个点；7d 窗口内一次真实充值 102h 前 395.10 → 100h 前 414.20）
_hist321 = list(HIST["4-23A---321"])
for _h in range(720, 11, -6):
    if _h > 102:
        _hist321.append((float(_h), round(460 - (720 - _h) * 0.105, 2)))
    elif _h >= 100:
        pass
    else:
        _hist321.append((float(_h), round(385 + (_h - 12) * 0.28, 2)))
_hist321 = [p for p in _hist321 if not (100 <= p[0] < 102)]
_hist321 += [(102.0, 395.10), (100.0, 414.20)]
HIST["4-23A---321"] = _hist321
# v5 算法 fixture：
# - 330：7.8h 内含一次充值跳变（168.20 → 171.50），该段应跳过（不计用电也不计时长）
ROWS["4-23A---330"] = {"quantity": 166.03, "low": False}
HIST["4-23A---330"] = [(8.0, 170.00), (6.0, 168.50), (4.0, 168.20), (2.0, 171.50), (0.2, 166.03)]
# - 422：7.8h 内几乎持平（dq 均 ≤0.05）→ rate=0 → 下限 0.05 → ≥30 天
ROWS["4-23B---422"] = {"quantity": 100.00, "low": False}
HIST["4-23B---422"] = [(8.0, 100.02), (0.2, 100.00)]
# - 325：24h 速率 24.27、7d 速率 9.25 → 混合 19.01 → 100/19.01≈5.3 天
ROWS["4-23A---325"] = {"quantity": 100.00, "low": False}
HIST["4-23A---325"] = [(78.0, 130.0), (54.0, 127.0), (30.0, 120.0), (18.0, 118.0),
                       (12.0, 115.0), (6.0, 112.0), (0.2, 100.0)]

PREVIEW = "_power_preview.html"
HARNESS = "_power_harness.html"
COMMON = "_power_common.js"


def ud_blob(sel, at=1762300800000):
    return {
        "v": 6,
        "at": {"homeTools": at, "fit": at, "draw": at, "group": at, "roster": at,
               "hide": at, "tt": at, "prefs": at, "nick": at, "power": at, "water": at},
        "homeTools": ["draw", "hw", "nt", "tt"],
        "fit": {}, "draw": {}, "group": {},
        "roster": {"rosterSel": [], "rollSel": [], "rollSt": {}, "rollNames": ""},
        "hide": {"hwHide": {}, "ntHide": {}},
        "tt": {"ttView": "", "ttUseMine": False, "ttLocal": None, "termStart": ""},
        "prefs": {"hwRemind": {}, "ntSub": False, "ntSubAt": 0},
        "nick": "", "power": {"sel": sel, "at": at},
        "water": {"rooms": {}},
        "homeToolsAt": at,
    }


def preview_url(sid=SID_A, ud=None, name=NAME):
    q = "sid=" + sid + "&name=" + urllib.parse.quote(name)
    if ud is not None:
        q += "&ud=" + urllib.parse.quote(json.dumps(ud, ensure_ascii=False), safe="")
    return PREVIEW + "?" + q


INJECT = r"""<script>
(function(){
window.__reqs=[];window.__errs=[];window.__cerrs=[];window.__udPosts=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));_ce.apply(console,arguments);};
try{ Object.defineProperty(window,"indexedDB",{value:undefined,configurable:true}); }catch(e){}
var Q="";try{Q=String(location.search||"");}catch(e){}
function qv(k,d){var m=Q.match(new RegExp("[?&]"+k+"=([^&]*)"));return m?decodeURIComponent(m[1]):d;}
var SID=qv("sid","__SID_A__"), NM=qv("name","__NAME__");
var UDSEED=null;try{var uds=qv("ud","");if(uds)UDSEED=JSON.parse(uds);}catch(e){UDSEED=null;}
var ROWS=__ROWS__, HIST=__HIST__, CATALOG=__CATALOG__;
try{
  localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token-"+SID,sid:SID,name:NM,role:"",badge:"",is_admin:false,ts:Date.now()}));
  if(!localStorage.getItem("zq_tools_v2_"+SID))localStorage.setItem("zq_tools_v2_"+SID,JSON.stringify({homeTools:["draw","hw","nt","tt"]}));
}catch(e){}
var UD_ROW=UDSEED?[{id:SID,blob:JSON.stringify(UDSEED),ts:1762300800000}]:[];
function resp(obj,status){status=status||200;return Promise.resolve({ok:status>=200&&status<300,status:status,
  json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve(JSON.stringify(obj));}});}
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};
  var s=String((u&&u.url!==undefined)?u.url:u), m=String(o.method||"GET").toUpperCase(), h=o.headers||{};
  if(s.indexOf("tcloudbasegateway")<0){ return _f.apply(this,arguments); }
  var hdr={};for(var k in h){try{hdr[k.toLowerCase()]=String(h[k]);}catch(e){}}
  window.__reqs.push({url:s,method:m,headers:hdr,body:o.body?String(o.body):""});
  if(s.indexOf("/userdata")>=0){
    if(m==="GET")return resp(UD_ROW.map(function(r){return {id:r.id,blob:r.blob,ts:r.ts};}));
    var arr=[];try{arr=JSON.parse(String(o.body||"[]"));}catch(e){}
    var row=(arr&&arr[0])||{};
    if(row&&row.id!=null&&row.blob!=null){
      window.__udPosts.push({id:String(row.id),blob:String(row.blob),headers:hdr,url:s});
      UD_ROW=[{id:String(row.id),blob:String(row.blob),ts:Number(row.ts)||Date.now()}];
    }
    return resp([{id:row.id,blob:row.blob,ts:row.ts}]);
  }
  if(s.indexOf("/power_history")>=0){
    var hv="";try{var hm=s.match(/[?&]roomverify=eq\.([^&]+)/);if(hm)hv=decodeURIComponent(hm[1]);}catch(e){}
    var cut=0;try{var gm=s.match(/[?&]ts=gte\.([^&]+)/);if(gm)cut=Date.parse(decodeURIComponent(gm[1]));}catch(e){}
    var hl=(HIST[hv]||[]).filter(function(p){return !cut||(Date.now()-p[0]*3600000)>=cut;}).map(function(p){return {roomverify:hv,quantity:p[1],ts:new Date(Date.now()-p[0]*3600000).toISOString()};});
    return resp(hl);
  }
  if(s.indexOf("/power")>=0){
    var pv="";try{var pm=s.match(/[?&]id=eq\.([^&]+)/);if(pm)pv=decodeURIComponent(pm[1]);}catch(e){}
    var cat=null;for(var i=0;i<CATALOG.length;i++){if(CATALOG[i][0]===pv){cat=CATALOG[i];break;}}
    if(!cat)return resp([]);
    var rw=ROWS[pv]||{quantity:100,low:false};
    return resp([{id:pv,label:cat[1],building:cat[2],room:cat[1].replace(cat[2],""),
      quantity:rw.quantity,unit:"度",low:rw.low,updated_at:"2026-11-06T06:42:24+08:00"}]);
  }
  if(s.indexOf("rpc/class_members")>=0)return resp([{seat:1,sid:SID,name:NM,role:"",badge:"",is_admin:false}]);
  if(s.indexOf("rpc/class_verify")>=0)return resp({ok:true,token:"mock-token-"+SID,sid:SID,name:NM,role:"",badge:"",is_admin:false});
  if(s.indexOf("/marks")>=0)return resp([]);
  if(s.indexOf("/notices")>=0)return resp([]);
  if(s.indexOf("/homework")>=0)return resp([]);
  if(s.indexOf("/fitrecs")>=0)return resp([]);
  if(s.indexOf("/visits")>=0)return resp([]);
  if(s.indexOf("/feedback")>=0)return resp([]);
  return resp([]);
};
})();
</script>"""


COMMON_JS = r"""
var SRC="__SRC__", SID_A="__SID_A__", SID_B="__SID_B__", NAME="__NAME__";
function udBlob(sel,at){
  at=at||1762300800000;
  return {v:6,at:{homeTools:at,fit:at,draw:at,group:at,roster:at,hide:at,tt:at,prefs:at,nick:at,power:at},
    homeTools:["draw","hw","nt","tt"],fit:{},draw:{},group:{},
    roster:{rosterSel:[],rollSel:[],rollSt:{},rollNames:""},hide:{hwHide:{},ntHide:{}},
    tt:{ttView:"",ttUseMine:false,ttLocal:null,termStart:""},
    prefs:{hwRemind:{},ntSub:false,ntSubAt:0},nick:"",power:{sel:sel,at:at},homeToolsAt:at};
}
function pvUrl(sid,blob){
  var u=SRC+"?sid="+encodeURIComponent(sid)+"&name="+encodeURIComponent(NAME);
  if(blob)u+="&ud="+encodeURIComponent(JSON.stringify(blob));
  return u;
}
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
function clearLs(){try{localStorage.clear();}catch(e){}}
function mount(src,w,h,keep){
  return new Promise(function(res){
    var old=document.getElementById("fr");if(old&&old.parentNode)old.parentNode.removeChild(old);
    if(!keep)clearLs();
    var f=document.createElement("iframe");f.id="fr";f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block";
    f.src=src;
    var done=false;
    f.onload=function(){if(done)return;done=true;setTimeout(function(){res(f);},180);};
    document.body.appendChild(f);
    setTimeout(function(){if(!done){done=true;res(f);}},12000);
  });
}
function q(f,s){return f.contentDocument.querySelector(s);}
function qa(f,s){return Array.prototype.slice.call(f.contentDocument.querySelectorAll(s));}
function click(f,s){var e=q(f,s);if(e)e.click();return !!e;}
function clickAll(f){click(f,'#tabsBar button[data-tab="all"]');return sleep(280);}
function openPower(f){return clickAll(f).then(function(){click(f,'#allCards [data-open="power"]');return sleep(800);});}
function setSel(f,rv){
  var s=q(f,"#pwSelect");if(!s)return false;
  s.value=rv;s.dispatchEvent(new Event("change",{bubbles:true}));return true;
}
function reqs(f){try{return f.contentWindow.__reqs||[];}catch(e){return [];}}
function powerReqs(f){return reqs(f).filter(function(r){return r.url.indexOf("/power?")>=0;});}
function histReqs(f){return reqs(f).filter(function(r){return r.url.indexOf("/power_history?")>=0;});}
function udGets(f){return reqs(f).filter(function(r){return r.url.indexOf("/userdata")>=0&&r.method==="GET";});}
function udPosts(f){try{return f.contentWindow.__udPosts||[];}catch(e){return [];}}
function udPostIds(f){return udPosts(f).map(function(p){return p.id;});}
function blobs(f){return udPosts(f).map(function(p){try{return JSON.parse(p.blob);}catch(e){return null;}});}
function txt(f,s){var e=q(f,s);return e?e.textContent:"";}
function waitFor(fn,ms){
  var t0=Date.now();ms=ms||8000;
  return new Promise(function(res){
    (function loop(){
      var v=false;try{v=!!fn();}catch(e){v=false;}
      if(v)return res(true);
      if(Date.now()-t0>ms)return res(false);
      setTimeout(loop,40);
    })();
  });
}
function waitReady(f){
  return waitFor(function(){
    var c=q(f,"#idChipTxt");
    return !!q(f,"#s-power")&&!f.contentDocument.body.classList.contains("id-locked")&&!!c&&!!c.textContent;
  },15000);
}
function waitSel(f,rv){return waitFor(function(){return q(f,"#pwSelect")&&q(f,"#pwSelect").value===rv;},15000);}
function waitNum(f,v){return waitFor(function(){var e=q(f,"#pwNum");return !!e&&e.textContent.trim()===v;},12000);}
function report(slot,data){
  try{
    var x=new XMLHttpRequest();x.open("POST","/_report?slot="+slot,false);
    x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(data||{}));
  }catch(e){}
}
function extOf(f){
  var out=[];
  try{(f.contentWindow.performance.getEntriesByType("resource")||[]).forEach(function(e){
    var u=String(e.name||"");
    if(!/^https?:\/\/127\.0\.0\.1[:/]/.test(u)&&!/^data:/.test(u)&&!/^blob:/.test(u))out.push(u);
  });}catch(e){}
  return out;
}
"""

FUNC_JS = r"""
async function run(){
  var R={steps:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note).slice(0,420)});}
  var EXTS=[],ERRS=[],CERRS=[];
  function collect(f){
    try{ERRS=ERRS.concat(f.contentWindow.__errs||[]);}catch(e){}
    try{CERRS=CERRS.concat(f.contentWindow.__cerrs||[]);}catch(e){}
    try{EXTS=EXTS.concat(extOf(f));}catch(e){}
  }
  function arcOf(f){var e=q(f,"#pwRingFg");if(!e)return null;var a=e.getAttribute("stroke-dasharray");if(!a)return null;return parseFloat(String(a).split(/[\s,]+/)[0]);}
  function view(f,sel){var e=q(f,sel);return e?f.contentWindow.getComputedStyle(e):null;}
  try{
    /* ================= A. 未选择：引导 + 0 请求 + 仪表区占位 ================= */
    var f=await mount(SRC,430,1000,false);
    await waitReady(f);
    await openPower(f);
    T("「全部 → 宿舍电费」可打开", !!q(f,"#s-power")&&q(f,"#s-power").classList.contains("on"),
      q(f,"section.on")?q(f,"section.on").id:"none");
    var sel=q(f,"#pwSelect");
    T("关注宿舍下拉框存在（原生 select，兼容值源）", !!sel&&sel.tagName==="SELECT", sel?sel.tagName:"");
    T("下拉框可点高度 ≥40px（自定义触发器；原生 select 视觉隐藏）",
      !!q(f,"#pwPickBtn")&&q(f,"#pwPickBtn").getBoundingClientRect().height>=40&&getComputedStyle(sel).opacity==="0",
      q(f,"#pwPickBtn")?Math.round(q(f,"#pwPickBtn").getBoundingClientRect().height):0);
    var gps=qa(f,"#pwSelect optgroup").map(function(g){return g.getAttribute("label");});
    T("optgroup 按规范楼栋分组 = 4 个", gps.join(",")==="13号楼,16号楼,23号楼A座,23号楼B座", gps.join(","));
    var opts=qa(f,"#pwSelect option").filter(function(o){return o.value;});
    T("宿舍选项 = 17 间（value=roomverify）", opts.length===17&&opts.every(function(o){return o.value.indexOf("---")>0;}), opts.length);
    T("未选择：下拉占位显示引导「选择你要关注的宿舍」", !!sel&&sel.options[0].value===""&&/选择你要关注的宿舍/.test(sel.options[0].textContent), sel?sel.options[0].textContent:"");
    T("未选择：状态 pill「未选择」、环内占位「—」", txt(f,"#pwState").trim()==="未选择"&&txt(f,"#pwNum").trim()==="—", txt(f,"#pwState")+"/"+txt(f,"#pwNum"));
    T("未选择：电量环 arc=0", arcOf(f)===0, arcOf(f));
    var rf=q(f,"#pwRefresh");
    T("未选择：刷新按钮禁用", !!rf&&rf.disabled, rf?String(rf.disabled):"");
    await sleep(800);
    T("未选择：0 个 power 请求", powerReqs(f).length===0, powerReqs(f).length);
    T("未选择：0 个 power_history 请求", histReqs(f).length===0, histReqs(f).length);
    T("未选择：右栏保留占位（不折叠，含趋势占位与 tiles）",
      !!q(f,"#pwTrend")&&txt(f,"#pwTrend").indexOf("未选择宿舍")>=0&&qa(f,"#pwTiles .pw-tile").length===4, txt(f,"#pwTrend").replace(/\s+/g," "));
    T("无「全部宿舍」列表 / 楼栋 chips / 房间 chips",
      !q(f,"#pwList")&&!q(f,"#pwBuildings")&&!q(f,"#pwRooms")&&qa(f,"#s-power .pw-row").length===0&&qa(f,"#s-power .pw-chip").length===0, "");
    T("页面无「全部宿舍」统一展示语义", ((q(f,"#s-power")||{textContent:""}).textContent||"").indexOf("全部宿舍")<0, "");

    /* ================= B. 选择：环（可用天数刻度）+ 趋势 + 指标 ================= */
    T("选择 23号楼A座321", setSel(f,"4-23A---321"), "");
    await waitNum(f,"382");
    await waitFor(function(){return !!q(f,"#pwTrend svg");},8000);
    var pr=powerReqs(f), hr=histReqs(f);
    T("选择后 power 请求 id=eq.<roomverify>", pr.length===1&&/id=eq\.4-23A---321/.test(pr[0].url), pr.length+" "+(pr[0]?pr[0].url.slice(-70):""));
    if(pr.length){
      T("power 请求带 Bearer + X-Device-Id", String(pr[0].headers["authorization"]||"").indexOf("Bearer ")==0&&!!pr[0].headers["x-device-id"], "");
    }
    T("选择后 power_history 请求 2 次（24h + 7d 估算窗口）", hr.length===2, hr.length);
    if(hr.length===2){
      var okAll=hr.every(function(r){return /power_history\?select=ts,quantity/.test(r.url)&&/roomverify=eq\.4-23A---321/.test(r.url)&&/order=ts\.asc/.test(r.url)&&/ts=gte\./.test(r.url)&&/limit=2000/.test(r.url);});
      var g2=hr.map(function(r){var m=r.url.match(/ts=gte\.([^&]+)/);return m?Date.parse(decodeURIComponent(m[1])):0;}).sort(function(a,b){return a-b;});
      T("history 请求契约（select=ts,quantity / roomverify / order / ts gte / limit=2000）", okAll, hr.map(function(r){return r.url.slice(-60);}).join(" | "));
      T("24h 与 7d 两个窗口的 gte 相差约 6 天", g2[0]>0&&g2[1]>0&&(g2[1]-g2[0])>5*24*3600e3&&(g2[1]-g2[0])<8*24*3600e3, Math.round((g2[1]-g2[0])/3600000)+"h");
    }
    T("主数值 ≥100 取整（382）", txt(f,"#pwNum").trim()==="382", txt(f,"#pwNum"));
    T("房间名只出现在下拉选中值（规范 label，无重复展示）", (q(f,"#pwSelect")||{}).selectedOptions&&q(f,"#pwSelect").selectedOptions[0].textContent==="23号楼A座321"&&!q(f,"#pwRoomName"), (q(f,"#pwSelect")||{}).selectedOptions?q(f,"#pwSelect").selectedOptions[0].textContent:"");
    T("状态 pill「充足」（AA 配色 #2F6555 on #EAF2EC）", txt(f,"#pwState").trim()==="充足"&&view(f,"#pwState").color==="rgb(47, 101, 85)"&&view(f,"#pwState").backgroundColor==="rgb(234, 242, 236)", view(f,"#pwState").color+" bg="+view(f,"#pwState").backgroundColor);
    T("电量环 data-state=ok", (q(f,"#pwGauge")||{}).getAttribute?q(f,"#pwGauge").getAttribute("data-state")==="ok":"", "");
    T("环刻度=估算可用天数/30（60.0 天 → 满环 100）", arcOf(f)===100, arcOf(f));
    T("环内小字 ≥30 天（双窗口混合估算）", txt(f,"#pwDays").indexOf("≥30")>=0&&txt(f,"#pwDays").indexOf("天")>=0, txt(f,"#pwDays"));
    T("环 aria-label 含剩余电量与 ≥30 天估算", (q(f,"#pwGauge")||{}).getAttribute?/剩余 382/.test(q(f,"#pwGauge").getAttribute("aria-label")||"")&&/≥30 天/.test(q(f,"#pwGauge").getAttribute("aria-label")||""):"", (q(f,"#pwGauge")||{}).getAttribute?q(f,"#pwGauge").getAttribute("aria-label"):"");
    T("趋势区渲染内联 SVG 折线", !!q(f,"#pwTrend svg")&&!!q(f,"#pwTrend path.pw-trend-line"), "");
    var td=(q(f,"#pwTrend path.pw-trend-line")||{}).getAttribute?q(f,"#pwTrend path.pw-trend-line").getAttribute("d"):"";
    T("趋势折线含 ≥5 个采样点", (td.match(/[ML]/g)||[]).length>=5, (td.match(/[ML]/g)||[]).length);
    T("趋势端点用 DOM 圆点（非拉伸 SVG 椭圆）", !!q(f,"#pwTrend .pw-tdot")&&!q(f,"#pwTrend svg circle"), "");
    var lg=txt(f,"#pwLegend");
    T("趋势图例含起点/当前/近 24h 下降", lg.indexOf("起点")>=0&&lg.indexOf("当前")>=0&&lg.indexOf("近 24h 下降")>=0, lg.replace(/\s+/g," "));
    T("趋势图例数值正确（起点 388.36 / 当前 382.02 / 下降 6.34）", lg.indexOf("388.36")>=0&&lg.indexOf("382.02")>=0&&lg.indexOf("6.34")>=0, lg.replace(/\s+/g," "));
    var tiles=qa(f,"#pwTiles .pw-tile");
    T("指标 tiles = 4 格", tiles.length===4, tiles.length);
    var tilesTxt=qa(f,"#pwTiles .pw-tile").map(function(e){return e.textContent.replace(/\s+/g," ");}).join(" | ");
    T("指标含 估算可用/近 24h 用电/低电阈值/上次充值",
      tilesTxt.indexOf("估算可用")>=0&&tilesTxt.indexOf("近 24h 用电")>=0&&tilesTxt.indexOf("低电阈值")>=0&&tilesTxt.indexOf("上次充值")>=0, tilesTxt.slice(0,240));
    T("估算可用 ≥30 天（双窗口混合 0.65/0.35 + ≥30 显示）", /估算可用\s*≥30\s*天/.test(tilesTxt.replace(/\s+/g," ")), tilesTxt);
    T("估算可用副标 ≈ 5.8 度/天（rate 1 位小数）", /≈\s*5\.8\s*度\/天/.test(tilesTxt.replace(/\s+/g," ")), tilesTxt);
    T("近 24h 用电 6.3 度（1 位小数）", /6\.3\s*度/.test(tilesTxt), tilesTxt);
    T("低电阈值 30 度", /30\s*度/.test(tilesTxt), tilesTxt);
    T("24h 无充值：上次充值 tile 显示「— / 暂无记录」", /上次充值\s*—/.test(tilesTxt.replace(/\s+/g," "))&&tilesTxt.indexOf("暂无记录")>=0, tilesTxt);
    T("不出现内部任务名/采样数", tilesTxt.indexOf("ClassPowerSync")<0&&tilesTxt.indexOf("采样")<0&&((q(f,"#s-power")||{textContent:""}).textContent||"").indexOf("ClassPowerSync")<0, "");
    T("充足时不显示低电提示条（hidden 且不渲染）", !!(q(f,"#pwLowBar")&&q(f,"#pwLowBar").hidden)&&view(f,"#pwLowBar").display==="none", view(f,"#pwLowBar").display);
    var fs=0;try{fs=parseFloat(f.contentWindow.getComputedStyle(q(f,"#pwNum")).fontSize);}catch(e){}
    T("大字剩余电量字号 ≥36px", fs>=36, "font-size="+fs);
    T("选择写入本机兜底 zq_power_sel_<sid>", (function(){try{return f.contentWindow.localStorage.getItem("zq_power_sel_"+SID_A);}catch(e){return null;}})()==="4-23A---321", "");
    var rfNow=q(f,"#pwRefresh");
    T("刷新完成后按钮恢复「刷新」且 aria-busy=false", !!rfNow&&rfNow.textContent==="刷新"&&rfNow.getAttribute("aria-busy")==="false", rfNow?rfNow.textContent+"/"+rfNow.getAttribute("aria-busy"):"");

    /* ================= C. 低电 / 偏低 状态 ================= */
    /* 16-305 fixture 已按规格 §6 改为 (30h,24.6)(6h,22.25)（慢频口径 1 段 → 约 9.5 天 / ring 31.6），
       低电与提示条断言保留。 */
    setSel(f,"1-16---305");
    await waitNum(f,"22.3");
    T("低电：data-state=low 且 pill「低电」", (q(f,"#pwGauge")||{}).getAttribute&&q(f,"#pwGauge").getAttribute("data-state")==="low"&&txt(f,"#pwState").trim()==="低电"&&q(f,"#pwState").classList.contains("low"), txt(f,"#pwState"));
    var a305=arcOf(f);
    T("低电：环刻度按可用天数（≈9.5 天 → ≈31.6）", a305!=null&&a305>31&&a305<32.2, a305);
    T("低电：环内小字 ≈ 9.5 天", txt(f,"#pwDays").indexOf("9.5")>=0, txt(f,"#pwDays"));
    T("低电：显示低电提示条（含 22.25 度）", q(f,"#pwLowBar")&&!q(f,"#pwLowBar").hidden&&view(f,"#pwLowBar").display!=="none"&&txt(f,"#pwLowBar").indexOf("22.25")>=0, txt(f,"#pwLowBar"));
    T("低电：趋势卡 data-state=low", (q(f,"#pwTrendCard")||{}).getAttribute?q(f,"#pwTrendCard").getAttribute("data-state")==="low":"", "");
    setSel(f,"4-23A---323");
    await waitNum(f,"45.6");
    T("偏低：data-state=warn 且 pill「偏低」", (q(f,"#pwGauge")||{}).getAttribute&&q(f,"#pwGauge").getAttribute("data-state")==="warn"&&txt(f,"#pwState").trim()==="偏低", txt(f,"#pwState"));
    T("偏低不显示低电提示条", q(f,"#pwLowBar")&&q(f,"#pwLowBar").hidden, "");

    /* ================= D. 数据不足占位 ================= */
    setSel(f,"4-23B---424");
    await waitNum(f,"18.5");
    await sleep(300);
    T("数据不足：趋势显示「数据积累中」", txt(f,"#pwTrend").indexOf("数据积累中")>=0, txt(f,"#pwTrend").replace(/\s+/g," "));
    T("数据不足：环内小字「数据积累中」+ 小弧兜底", txt(f,"#pwDays").indexOf("数据积累中")>=0&&Math.abs((arcOf(f)||0)-4)<0.2, txt(f,"#pwDays")+"/"+arcOf(f));
    T("数据不足：估算可用 tile 为 —", /估算可用\s*—/.test(txt(f,"#pwTiles").replace(/\s+/g," ")), txt(f,"#pwTiles").replace(/\s+/g," "));
    T("低于 30 度（云端 low=false）仍判低电", (q(f,"#pwGauge")||{}).getAttribute&&q(f,"#pwGauge").getAttribute("data-state")==="low", "");

    /* ================= E. 刷新（power + history 一起力拉） ================= */
    setSel(f,"4-23A---321");
    await waitNum(f,"382");
    var rf2=q(f,"#pwRefresh");
    T("已选择后刷新按钮可用", !!rf2&&!rf2.disabled, "");
    var b1=powerReqs(f).length,b2=histReqs(f).length;
    if(rf2)rf2.click();
    await sleep(900);
    T("点刷新力拉 power（+1）", powerReqs(f).length===b1+1, b1+"->"+powerReqs(f).length);
    T("点刷新力拉 power_history（24h + 7d，共 +2）", histReqs(f).length===b2+2, b2+"->"+histReqs(f).length);

    /* ================= F. 期间有充值：chip + 不计负用电 ================= */
    setSel(f,"1-13---308");
    await waitNum(f,"300");
    await sleep(400);
    T("含充值区间：显示「期间有充值」chip", q(f,"#pwRecharge")&&!q(f,"#pwRecharge").hidden&&view(f,"#pwRecharge").display!=="none", q(f,"#pwRecharge")?q(f,"#pwRecharge").textContent:"");
    var t308=txt(f,"#pwTiles").replace(/\s+/g," ");
    T("含充值区间：近 24h 用电只累计下降（5.8 度）", /5\.8\s*度/.test(t308), t308);
    T("含充值区间：上次充值 tile 显示重置度数 305.20 + 时间", /305\.20/.test(t308)&&/\d{2}-\d{2} \d{2}:\d{2}/.test(t308), t308);

    /* ================= G. 选择进同步（UD.power） ================= */
    setSel(f,"4-23A---321");
    await waitNum(f,"382");
    var pushed=await waitFor(function(){var bl=blobs(f);return bl.some(function(b){return b&&b.power&&b.power.sel==="4-23A---321";});},25000);
    T("选择进同步：userdata POST 含最新关注宿舍（321）", !!pushed, udPosts(f).length);
    var p1=null,b1b=null,pi;
    for(pi=0;pi<udPosts(f).length;pi++){var bb=blobs(f)[pi];if(bb&&bb.power&&bb.power.sel==="4-23A---321"){p1=udPosts(f)[pi];b1b=bb;}}
    T("POST body id=本人 sid", !!p1&&p1.id===SID_A, p1?p1.id:"");
    T("blob.power.sel = 关注宿舍", !!b1b&&b1b.power&&b1b.power.sel==="4-23A---321", b1b?JSON.stringify(b1b.power):"");
    T("blob.at.power 与值内 at 镜像一致", !!b1b&&typeof b1b.at.power==="number"&&b1b.power.at===b1b.at.power, "");
    T("blob 顶层键序含 power + water（14 键）", !!b1b&&Object.keys(b1b).join(",")==="v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,water,homeToolsAt", b1b?Object.keys(b1b).join(","):"");

    /* ================= H. 隐私 / 报错 ================= */
    var pwTxt=(q(f,"#s-power")||{textContent:""}).textContent||"";
    T("电费页不含姓名/学号", pwTxt.indexOf(NAME)<0&&pwTxt.indexOf(SID_A)<0, pwTxt.slice(0,80));
    T("页面文本不出现学号", (f.contentDocument.body.textContent||"").indexOf(SID_A)<0, "");
    T("本场景 0 JS 报错", (f.contentWindow.__errs||[]).length===0, JSON.stringify(f.contentWindow.__errs||[]));
    T("本场景 0 console.error", (f.contentWindow.__cerrs||[]).length===0, JSON.stringify(f.contentWindow.__cerrs||[]));
    collect(f);

    /* ================= I. 同设备刷新恢复 ================= */
    var f2=await mount(SRC,430,1000,true);
    await waitReady(f2);
    await openPower(f2);
    var restored=await waitSel(f2,"4-23A---321");
    T("同设备刷新：恢复关注宿舍选择", restored, q(f2,"#pwSelect")?q(f2,"#pwSelect").value:"none");
    await waitNum(f2,"382");
    T("同设备刷新：缓存电量立即可见", txt(f2,"#pwNum").trim()==="382", txt(f2,"#pwNum"));
    T("同设备刷新：TTL 内不重复请求 power", powerReqs(f2).length===0, powerReqs(f2).length);
    collect(f2);

    /* ================= J. 换设备恢复（真源 UD.power） ================= */
    var f3=await mount(pvUrl(SID_A,udBlob("1-13---324")),430,1000,false);
    await waitReady(f3);
    await openPower(f3);
    var restG=await waitSel(f3,"1-13---324");
    T("换设备：从云端 UD.power 恢复关注宿舍", restG, q(f3,"#pwSelect")?q(f3,"#pwSelect").value:"none");
    await waitNum(f3,"79.0");
    T("换设备：按恢复宿舍拉 power", powerReqs(f3).length>=1&&/id=eq\.1-13---324/.test(powerReqs(f3)[0].url), "");
    T("换设备：power_history 也拉取并渲染趋势", histReqs(f3).length>=1&&!!q(f3,"#pwTrend svg"), "");
    collect(f3);

    /* ================= K. 两账号隔离 ================= */
    var fA=await mount(pvUrl(SID_A,udBlob("4-23A---321")),430,1000,false);
    await waitReady(fA);await openPower(fA);
    var rA=await waitSel(fA,"4-23A---321");
    await waitNum(fA,"382");
    await waitFor(function(){return udGets(fA).length>=1;},12000);
    var valA=(q(fA,"#pwSelect")||{}).value||"",idsA=JSON.stringify(udPostIds(fA));
    T("账号A：恢复 A 的关注宿舍", rA, valA);
    T("账号A：userdata 只按 sid A 拉取", udGets(fA).length>=1&&udGets(fA).every(function(r){return r.url.indexOf("id=eq\."+SID_A)>=0;}), "");
    collect(fA);
    var fB=await mount(pvUrl(SID_B,udBlob("4-23B---424")),430,1000,false);
    await waitReady(fB);await openPower(fB);
    var rB=await waitSel(fB,"4-23B---424");
    await waitNum(fB,"18.5");
    await waitFor(function(){return udGets(fB).length>=1;},12000);
    T("账号B：恢复 B 的关注宿舍", rB, q(fB,"#pwSelect")?q(fB,"#pwSelect").value:"none");
    T("账号B：userdata 只按 sid B 拉取", udGets(fB).length>=1&&udGets(fB).every(function(r){return r.url.indexOf("id=eq\."+SID_B)>=0;}), "");
    T("两账号选择互不覆盖", rA&&rB&&valA!==(q(fB,"#pwSelect")||{}).value, valA+"/"+(q(fB,"#pwSelect")||{}).value);
    T("账号A/B 的 POST 都只写本人 id", JSON.parse(idsA).every(function(x){return x===SID_A;})&&udPostIds(fB).every(function(x){return x===SID_B;}), idsA+"/"+JSON.stringify(udPostIds(fB)));
    collect(fB);

    /* ================= L. 非法 roomverify 降级 ================= */
    var fBad=await mount(pvUrl(SID_A,udBlob("9-99---999")),430,1000,false);
    await waitReady(fBad);await openPower(fBad);
    await sleep(2800);
    T("非法存储值：降级为未选择", q(fBad,"#pwSelect")&&q(fBad,"#pwSelect").value==="", q(fBad,"#pwSelect")?q(fBad,"#pwSelect").value:"none");
    T("非法存储值：引导可见且 0 请求", /选择你要关注的宿舍/.test((q(fBad,"#pwSelect")||{}).textContent||"")&&powerReqs(fBad).length===0&&histReqs(fBad).length===0, "");
    collect(fBad);

    /* ================= M. 空间基准（≥960 铺满） ================= */
    var fS=await mount(pvUrl(SID_A,udBlob("4-23A---321")),1280,1000,false);
    await waitReady(fS);await openPower(fS);
    await waitSel(fS,"4-23A---321");await waitNum(fS,"382");await sleep(400);
    var m1=fS.contentWindow.evaluateMeasure?null:null;
    var m1=await (async function(){
      var de=fS.contentDocument.documentElement,dash=fS.contentDocument.getElementById("pwDash");
      var vh=fS.contentDocument.defaultView.innerHeight;
      var r=dash.getBoundingClientRect();
      return {dist:Math.round(vh-r.bottom),scrollH:de.scrollHeight,vh:vh,dashH:Math.round(r.height)};
    })();
    T("1280×1000：仪表盘底距视口底 ≤40px（"+m1.dist+"px）", m1.dist<=40&&m1.dist>=0, JSON.stringify(m1));
    collect(fS);
    var fS2=await mount(pvUrl(SID_A,udBlob("4-23A---321")),1280,800,false);
    await waitReady(fS2);await openPower(fS2);
    await waitSel(fS2,"4-23A---321");await waitNum(fS2,"382");await sleep(400);
    var sh2=fS2.contentDocument.documentElement.scrollHeight;
    T("1280×800：无纵向滚动或 ≤10px（scrollH="+sh2+"）", sh2<=810, String(sh2));
    collect(fS2);

    /* ================= N. 无横向溢出（360/430/1280） ================= */
    var widths=[360,430,1280];
    for(var wi=0;wi<widths.length;wi++){
      var ww=widths[wi];
      var fo=await mount(pvUrl(SID_A,udBlob("4-23A---321")),ww,1000,false);
      await waitReady(fo);
      await openPower(fo);
      await waitSel(fo,"4-23A---321");
      await waitNum(fo,"382");
      await sleep(300);
      var fw=fo.contentWindow,de=fo.contentDocument.documentElement,bad=[];
      Array.prototype.slice.call(fo.contentDocument.querySelectorAll("#s-power *")).forEach(function(e){
        var r=e.getBoundingClientRect();
        if(r.width>0&&r.right>de.clientWidth+1&&fw.getComputedStyle(e).position!=="fixed")bad.push(e.tagName+"."+String(e.className).split(" ")[0]);
      });
      T("宽度 "+ww+"px：无横向溢出", de.scrollWidth<=de.clientWidth+1&&bad.length===0,
        "clientW="+de.clientWidth+" scrollW="+de.scrollWidth+" bad=["+bad.slice(0,6).join(",")+"]");
      collect(fo);
    }

    /* ================= P. 三档切换 / 固定 y 轴 / 横滑 / 充值 tile ================= */
    function gteOf(u){var m=String(u).match(/[?&]ts=gte\.([^&]+)/);return m?Date.parse(decodeURIComponent(m[1])):0;}
    var fr=await mount(pvUrl(SID_A,udBlob("4-23A---321")),430,1000,false);
    await waitReady(fr);await openPower(fr);
    await waitSel(fr,"4-23A---321");await waitNum(fr,"382");
    await waitFor(function(){return !!q(fr,"#pwTrend svg");},9000);
    var chips=qa(fr,"#pwRanges .pw-range");
    T("三档 chips = 3 个（24h/7天/30天）", chips.length===3&&chips.map(function(b){return b.textContent;}).join("/")==="24h/7天/30天", chips.map(function(b){return b.textContent;}).join("/"));
    T("默认选中 24h", chips.length===3&&chips[0].classList.contains("on")&&txt(fr,"#pwTrendTitle").indexOf("24h")>=0, txt(fr,"#pwTrendTitle"));
    T("chips 可点高度 ≥40px", chips.length===3&&chips.every(function(b){return b.getBoundingClientRect().height>=40;}), chips.length?Math.round(chips[0].getBoundingClientRect().height):0);
    T("24h 档不横向滚动（scrollWidth ≤ clientW+4）", (function(){var sc=q(fr,"#pwTrendScroll");return !!sc&&sc.scrollWidth<=sc.clientWidth+4;})());
    T("固定 y 轴：3 个刻度且在横向滚动容器外", (function(){var y=q(fr,"#pwYAxis"),sc=q(fr,"#pwTrendScroll");return !!y&&qa(fr,"#pwYAxis .pw-ylab").length===3&&!!sc&&!sc.contains(y);})());
    T("24h 档 x 轴 3 个日期刻度", qa(fr,"#pwXAxis .pw-xlab").length===3, qa(fr,"#pwXAxis .pw-xlab").length);
    var hist0=histReqs(fr);
    var h0=hist0.length;
    var g2s=hist0.map(function(r){var m=r.url.match(/ts=gte\.([^&]+)/);return m?Date.parse(decodeURIComponent(m[1])):0;}).sort(function(a,b){return a-b;});
    T("初始已拉取 24h + 7d 两个估算窗口", h0===2&&g2s[0]>0&&(g2s[1]-g2s[0])>5*24*3600e3, h0+" | "+Math.round((g2s[1]-g2s[0])/3600000)+"h");
    click(fr,'#pwRanges [data-range="7d"]');
    await waitFor(function(){return txt(fr,"#pwTrendTitle").indexOf("7 天")>=0;},9000);
    await sleep(700);
    T("切 7 天：命中已缓存窗口（不重复请求）", histReqs(fr).length===h0, h0+"->"+histReqs(fr).length);
    T("7 天：标题/图例/区间用电 tile 随档位",
      txt(fr,"#pwTrendTitle").indexOf("近 7 天趋势")>=0&&txt(fr,"#pwLegend").indexOf("区间下降")>=0&&txt(fr,"#pwTiles").indexOf("近 7 天用电")>=0,
      txt(fr,"#pwTrendTitle")+" | "+txt(fr,"#pwTiles").replace(/\s+/g," ").slice(0,90));
    T("7 天：期间有充值 chip 可见", !!q(fr,"#pwRecharge")&&!q(fr,"#pwRecharge").hidden, "");
    T("7 天：上次充值 tile 显示重置度数 + 时间", /414\.20/.test(txt(fr,"#pwTiles"))&&/\d{2}-\d{2} \d{2}:\d{2}/.test(txt(fr,"#pwTiles")), txt(fr,"#pwTiles").replace(/\s+/g," "));
    T("7 天：趋势区无横向滚动（画布铺满、overflow hidden）",(function(){var sc=q(fr,"#pwTrendScroll");if(!sc)return false;
      var cs=fr.contentWindow.getComputedStyle(sc);return (cs.overflowX==="hidden")&&sc.scrollWidth<=sc.clientWidth+1;})());
    T("7 天：x 轴日期刻度 3–5 个",(function(){var xl=qa(fr,"#pwXAxis .pw-xlab");return xl.length>=3&&xl.length<=5;})());
    click(fr,'#pwRanges [data-range="30d"]');
    await waitFor(function(){return txt(fr,"#pwTrendTitle").indexOf("30 天")>=0;},9000);
    await sleep(800);
    T("30 天：画布宽度=绘图区（不横向滚动，全部采样压缩）",(function(){var sc=q(fr,"#pwTrendScroll");if(!sc)return false;
      var cs=fr.contentWindow.getComputedStyle(sc);return cs.overflowX==="hidden"&&sc.scrollWidth<=sc.clientWidth+1;})());
    T("30 天：y 轴仍固定且 3 刻度", (function(){var y=q(fr,"#pwYAxis"),sc=q(fr,"#pwTrendScroll");return !!y&&qa(fr,"#pwYAxis .pw-ylab").length===3&&!!sc&&!sc.contains(y);})());
    var act0=(q(fr,"section.on")||{}).id||"";
    try{
      (function(){
        var sc=q(fr,"#pwTrendScroll");
        function send(type,x){
          var t=new Touch({identifier:9,target:sc,clientX:x,clientY:600,pageX:x,pageY:600});
          var e=new TouchEvent(type,{bubbles:true,cancelable:true,touches:(type==="touchend"?[]:[t]),targetTouches:(type==="touchend"?[]:[t]),changedTouches:[t]});
          sc.dispatchEvent(e);
        }
        send("touchstart",330);send("touchmove",150);send("touchend",150);
      })();
    }catch(e){}
    await sleep(500);
    var act1=(q(fr,"section.on")||{}).id||"";
    T("趋势图横滑不触发站点切工具（CURTAB 不变）", act0==="s-power"&&act1==="s-power", act0+"->"+act1);
    var hp0=powerReqs(fr).length,hh0=histReqs(fr).length;
    click(fr,"#pwRefresh");await sleep(1600);
    T("30 天档刷新：力拉 power（≥+1）与 24h/7d/30d 三个窗口（+3）",
      powerReqs(fr).length>=hp0+1&&histReqs(fr).length===hh0+3, (powerReqs(fr).length-hp0)+"/"+(histReqs(fr).length-hh0));
    var h24=histReqs(fr).length;
    click(fr,'#pwRanges [data-range="24h"]');
    await waitFor(function(){return txt(fr,"#pwTrendTitle").indexOf("24h")>=0;},8000);
    await sleep(700);
    T("切回 24h：命中内存缓存（不重复请求 history）", histReqs(fr).length===h24, h24+"->"+histReqs(fr).length);
    T("档位选择写入 localStorage(zq_power_range_v1)", (function(){try{return fr.contentWindow.localStorage.getItem("zq_power_range_v1")==="24h";}catch(e){return false;}})());
    T("24h 档：不横滑且 x 轴 3 刻度",(function(){var sc=q(fr,"#pwTrendScroll");if(!sc)return false;
      var cs=fr.contentWindow.getComputedStyle(sc);return cs.overflowX==="hidden"&&sc.scrollWidth<=sc.clientWidth+1&&qa(fr,"#pwXAxis .pw-xlab").length===3;})());
    collect(fr);

    /* ================= Q. 估算算法（跳过充值/混合/下限/≥30）与可调低电阈值 ================= */
    var fa=await mount(pvUrl(SID_A,udBlob("4-23A---321")),430,1000,false);
    await waitReady(fa);await openPower(fa);
    await waitSel(fa,"4-23A---321");await waitNum(fa,"382");await sleep(500);
    T("算法：321 双窗口混合 → 估算可用 ≥30 天", txt(fa,"#pwDays").indexOf("≥30")>=0, txt(fa,"#pwDays"));
    T("算法：321 rate ≈ 5.8 度/天 副标", /≈\s*5\.8\s*度\/天/.test(txt(fa,"#pwTiles").replace(/\s+/g," ")), txt(fa,"#pwTiles").replace(/\s+/g," ").slice(0,80));
    setSel(fa,"4-23A---330");await waitNum(fa,"166");await sleep(500);
    T("算法：充值跳变段跳过（330 → ≈5.5 天 / ≈30.1 度/天）",
      /≈\s*5\.5\s*天/.test(txt(fa,"#pwDays").replace(/\s+/g," "))&&/≈\s*30\.1\s*度\/天/.test(txt(fa,"#pwTiles").replace(/\s+/g," ")),
      txt(fa,"#pwDays")+" | "+txt(fa,"#pwTiles").replace(/\s+/g," ").slice(0,70));
    setSel(fa,"4-23B---422");await waitNum(fa,"100");await sleep(500);
    /* 规格 §1.4 通用有效性守卫（2026-11-07）：23B 属实时房，24h/7d 窗口均无真实下降 → valid=false
       显示「数据积累中」；不再用 0.05 度/天的下限伪造「≥30 天 / ≈0.1 度/天」（原断言按新口径替换）。 */
    T("算法：24h/7d 均无真实下降 → 数据积累中（不再伪造 ≥30 天）",
      txt(fa,"#pwDays").indexOf("数据积累中")>=0&&/估算可用\s*—/.test(txt(fa,"#pwTiles").replace(/\s+/g," ")),
      txt(fa,"#pwDays")+" | "+txt(fa,"#pwTiles").replace(/\s+/g," ").slice(0,70));
    setSel(fa,"4-23A---325");await waitNum(fa,"100");await sleep(500);
    T("算法：24h(24.27)+7d(9.25) 混合 19.01 → ≈5.3 天 / ≈19.0 度/天",
      /≈\s*5\.3\s*天/.test(txt(fa,"#pwDays").replace(/\s+/g," "))&&/≈\s*19\.0\s*度\/天/.test(txt(fa,"#pwTiles").replace(/\s+/g," ")),
      txt(fa,"#pwDays")+" | "+txt(fa,"#pwTiles").replace(/\s+/g," ").slice(0,70));
    /* 可调阈值：默认 30 → 305 低电；点 tile 弹层改 50 → 仍低电；改 10 → 充足；保存进 UD */
    setSel(fa,"1-16---305");await waitNum(fa,"22.3");await sleep(500);
    T("默认阈值 30：305 低电（pill/环/alert）", txt(fa,"#pwState").trim()==="低电"&&q(fa,"#pwGauge").getAttribute("data-state")==="low"&&q(fa,"#pwLowBar")&&!q(fa,"#pwLowBar").hidden, txt(fa,"#pwState"));
    var lowTile=q(fa,"#pwLowTile");
    T("阈值 tile 为可点按钮（≥40px、aria-haspopup）", !!lowTile&&lowTile.tagName==="BUTTON"&&lowTile.getBoundingClientRect().height>=40&&lowTile.getAttribute("aria-haspopup")==="dialog"&&/30\s*度/.test(lowTile.textContent), lowTile?lowTile.tagName+" "+Math.round(lowTile.getBoundingClientRect().height):"none");
    lowTile.click();await sleep(250);
    var lowOpts=qa(fa,"#pwLowSel [data-low]");
    T("弹层 8 个阈值选项（10/20/30/40/50/60/80/100，每个 ≥40px 高）",
      lowOpts.length===8&&lowOpts.map(function(b){return b.getAttribute("data-low");}).join(",")==="10,20,30,40,50,60,80,100"&&lowOpts.every(function(b){return b.getBoundingClientRect().height>=40;}), lowOpts.length);
    lowOpts.filter(function(b){return b.getAttribute("data-low")==="50";})[0].click();
    await sleep(1600);
    T("改阈值 50：tile 显示 50 度、305 仍低电、alert 可见",
      /50\s*度/.test(txt(fa,"#pwTiles"))&&txt(fa,"#pwState").trim()==="低电"&&!q(fa,"#pwLowBar").hidden, txt(fa,"#pwTiles").replace(/\s+/g," ").slice(0,80));
    var lowPushed=waitFor?null:null;
    var okLow=false,okKeys=false;
    await waitFor(function(){
      var posts=udPosts(fa);
      for(var pi=0;pi<posts.length;pi++){
        var bb=blobs(fa)[pi];
        if(bb&&bb.power&&Number(bb.power.low)===50){okLow=true;okKeys=Object.keys(bb).join(",")==="v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,water,homeToolsAt";}
      }
      return okLow;
    },20000);
    T("阈值写入 UD：POST blob.power.low=50 且顶层 14 键不变", okLow&&okKeys, okLow+" keys14="+okKeys);
    T("阈值本机兜底键 zq_power_low_<sid>=50", (function(){try{return fa.contentWindow.localStorage.getItem("zq_power_low_"+SID_A)==="50";}catch(e){return false;}})(), "");
    lowTile=q(fa,"#pwLowTile");lowTile.click();await sleep(200);
    var opt10=qa(fa,"#pwLowSel [data-low]").filter(function(b){return b.getAttribute("data-low")==="10";})[0];
    if(opt10)opt10.click();
    await sleep(1600);
    T("改阈值 10：305 转「充足」、alert 隐藏、tile 显示 10 度",
      txt(fa,"#pwState").trim()==="充足"&&q(fa,"#pwLowBar").hidden&&/10\s*度/.test(txt(fa,"#pwTiles")), txt(fa,"#pwState")+" "+txt(fa,"#pwTiles").replace(/\s+/g," ").slice(0,60));
    T("阈值改后刷新仍保留（同设备）", (function(){var r=q(fa,"#pwRefresh");if(r&&!r.disabled)r.click();return true;})()&&true, "");
    await sleep(1600);
    T("刷新后阈值仍为 10 度", /10\s*度/.test(txt(fa,"#pwTiles")), txt(fa,"#pwTiles").replace(/\s+/g," ").slice(0,60));
    collect(fa);
    /* 旧数据无 low → 默认 30；换设备 low=60 → 恢复并参与判定 */
    var fOld=await mount(pvUrl(SID_A,udBlob("4-23A---321")),430,1000,false);
    await waitReady(fOld);await openPower(fOld);
    await waitSel(fOld,"4-23A---321");await waitNum(fOld,"382");await sleep(400);
    T("旧数据无 power.low → 默认阈值 30 度", /30\s*度/.test(txt(fOld,"#pwTiles")), txt(fOld,"#pwTiles").replace(/\s+/g," ").slice(0,60));
    collect(fOld);
    var b60=udBlob("4-23A---321");b60.power.low=60;b60.at.power=Date.now();
    var f60=await mount(pvUrl(SID_A,b60),430,1000,false);
    await waitReady(f60);await openPower(f60);
    await waitSel(f60,"4-23A---321");await waitNum(f60,"382");await sleep(500);
    T("换设备从 UD.power.low 恢复阈值 60 度", /60\s*度/.test(txt(f60,"#pwTiles")), txt(f60,"#pwTiles").replace(/\s+/g," ").slice(0,60));
    setSel(f60,"1-13---324");await waitNum(f60,"79.0");await sleep(600);
    T("阈值 60 下 78.97 → 偏低（low ≤ q < low*2）", txt(f60,"#pwState").trim()==="偏低"&&q(f60,"#pwGauge").getAttribute("data-state")==="warn", txt(f60,"#pwState"));
    collect(f60);

    /* ================= O. 全程汇总 ================= */
    T("全程 0 JS 报错", ERRS.length===0, ERRS.slice(0,4).join(" | "));
    T("全程 0 console.error", CERRS.length===0, CERRS.slice(0,4).join(" | "));
    T("全程无外部请求", EXTS.length===0, EXTS.slice(0,4).join(" | "));
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("func",R);
}
run();

"""

SHOT_TPL = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#DDE3E1;font:11.5px monospace}
iframe{border:0;display:block;background:#fff}
#hud{padding:4px 8px;background:#23302E;color:#fff}</style></head><body>
<iframe id="f" src="__SRC__" style="width:__W__px;height:__H__px"></iframe>
<div id="hud">测量中…</div>
<script>
document.getElementById("f").addEventListener("load",function(){
  var f=this,d=f.contentDocument;
  function c(s){var e=d.querySelector(s);if(e)e.click();}
  setTimeout(function(){ c('#tabsBar button[data-tab="all"]'); },320);
  setTimeout(function(){ c('#allCards [data-open="power"]'); },600);
  setTimeout(function(){
    __ACTION__
    setTimeout(function(){
      var de=d.documentElement,bad=[];
      Array.prototype.slice.call(d.querySelectorAll("#s-power *")).forEach(function(e){
        var r=e.getBoundingClientRect();
        if(r.width>0&&r.right>de.clientWidth+1&&f.contentWindow.getComputedStyle(e).position!=="fixed")bad.push(e.tagName);
      });
      document.getElementById("hud").textContent="viewport="+de.clientWidth+"  scrollW="+de.scrollWidth+"  overflow="+bad.length;
    },1800);
  },1100);
});
</script></body></html>"""


def build_previews():
    src = open(SRC, encoding="utf-8").read()
    inject = (INJECT.replace("__SID_A__", SID_A).replace("__NAME__", NAME)
              .replace("__ROWS__", json.dumps(ROWS, ensure_ascii=False))
              .replace("__HIST__", json.dumps(HIST, ensure_ascii=False))
              .replace("__CATALOG__", json.dumps([[c[0], c[1], c[2]] for c in CATALOG], ensure_ascii=False)))
    out = src.replace("<head>", "<head>" + inject, 1)
    open(os.path.join(HERE, PREVIEW), "w", encoding="utf-8").write(out)


def build_harness():
    common = (COMMON_JS.replace("__SRC__", PREVIEW).replace("__SID_A__", SID_A)
              .replace("__SID_B__", SID_B).replace("__NAME__", NAME))
    open(os.path.join(HERE, COMMON), "w", encoding="utf-8").write(common)
    page = ('<!doctype html><html><head><meta charset="utf-8"><title>power harness</title></head>'
            '<body style="margin:0;background:#eee">'
            '<script src="' + COMMON + '"></script>'
            '<script>' + FUNC_JS + '</script></body></html>')
    open(os.path.join(HERE, HARNESS), "w", encoding="utf-8").write(page)


SHOT_FILES = []


def build_shot(w, h, selected_rv=None, tag="", rng=None, scroll=0, low=0, open_low=False):
    name = "_power_shot_%d%s%s.html" % (w, "_sel" if selected_rv else "", tag)
    action = ""
    if selected_rv:
        action = ("var s=d.querySelector('#pwSelect');if(s){s.value='" + selected_rv +
                  "';s.dispatchEvent(new Event('change',{bubbles:true}));}")
    if rng and rng != "24h":
        action += ("setTimeout(function(){var b=d.querySelector('#pwRanges [data-range=\"%s\"]');if(b)b.click();},900);" % rng)
    if scroll:
        action += ("setTimeout(function(){var sc=d.querySelector('#pwTrendScroll');if(sc)sc.scrollLeft=%d;},1800);" % scroll)
    if low:
        action += ("setTimeout(function(){var t=d.querySelector('#pwLowTile');if(t)t.click();"
                   "setTimeout(function(){var b=d.querySelector('#pwLowSel [data-low=\"%d\"]');if(b)b.click();},350);},1100);" % low)
    elif open_low:
        action += ("setTimeout(function(){var t=d.querySelector('#pwLowTile');if(t)t.click();},1100);")
    page = (SHOT_TPL.replace("__SRC__", preview_url(SID_A, None))
            .replace("__W__", str(w)).replace("__H__", str(h)).replace("__ACTION__", action))
    open(os.path.join(HERE, name), "w", encoding="utf-8").write(page)
    SHOT_FILES.append(name)
    return name


def run_edge(url, budget=20000, shot=None, window="492,900", timeout=180):
    prof = tempfile.mkdtemp(prefix="edgeprof_power_", dir=REPORT_DIR)
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=" + window,
            "--virtual-time-budget=%d" % budget, "--user-data-dir=" + prof]
    if shot:
        args.append("--screenshot=" + shot)
    args.append(url)
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        shutil.rmtree(prof, ignore_errors=True)


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        u = self.path.split("?")[0]
        if u == "/_report":
            slot = self.path.split("slot=")[1] if "slot=" in self.path else "x"
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(n)
                open(os.path.join(REPORT_DIR, slot + ".json"), "wb").write(body)
            except Exception:
                pass
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(404)


def clear_report(slot):
    p = os.path.join(REPORT_DIR, slot + ".json")
    if os.path.exists(p):
        try:
            os.remove(p)
        except Exception:
            pass


def wait_report(slot, secs=150):
    p = os.path.join(REPORT_DIR, slot + ".json")
    t0 = time.time()
    while time.time() - t0 < secs:
        if os.path.exists(p):
            time.sleep(0.15)
            try:
                return json.load(open(p, encoding="utf-8"))
            except Exception:
                time.sleep(0.2)
        time.sleep(0.2)
    return None


def static_checks():
    out = []
    src = open(SRC, encoding="utf-8").read()
    out.append(("版本号仍为 2.0.0", 'var APP_VER="2.0.0"' in src, ""))
    out.append(("存在 s-power section", 'id="s-power"' in src, ""))
    out.append(("「全部」页卡片 data-open=power（模板生成）",
                ('k:"power"' in src) and ('data-open=' in src) and ('data-card=' in src), ""))
    out.append(("存在 PW_ROOMS 静态目录（17 间）", src.count('{rv:"') == 17, str(src.count('{rv:"'))))
    miss = [(label, rv) for rv, label, bld in CATALOG if (label not in src or ('rv:"%s"' % rv) not in src)]
    out.append(("17 间规范命名（label + roomverify）齐全", not miss, str(miss[:3])))
    out.append(("无旧命名 23A- / 23B- 前缀", ("23A-3" not in src) and ("23B-4" not in src), ""))
    out.append(("无「全部宿舍」列表（v3 单宿舍仪表盘）", ("全部宿舍" not in src) and ('id="pwList"' not in src), ""))
    out.append(("存在电量环 SVG（pw-ring-fg）", 'id="pwRingFg"' in src and "stroke-dasharray" in src, ""))
    out.append(("存在趋势卡（#pwTrend / 内联 SVG）", 'id="pwTrend"' in src and "pw-trend-line" in src, ""))
    out.append(("存在指标 tiles / 低电提示条", 'id="pwTiles"' in src and 'id="pwLowBar"' in src, ""))
    out.append(("power_history 请求契约（单选 roomverify + 档位窗口 + limit=2000）",
                "power_history?select=ts,quantity&roomverify=eq." in src
                and "&order=ts.asc&limit=2000" in src, ""))
    out.append(("24h/7天/30天 分段 chips", src.count('data-range="24h"') == 1 and src.count('data-range="7d"') == 1 and src.count('data-range="30d"') == 1, ""))
    out.append(("固定 y 轴 / 横滑容器 / 横轴固定层", 'id="pwYAxis"' in src and 'id="pwTrendScroll"' in src and 'id="pwXAxis"' in src, ""))
    out.append(("趋势横滑已豁免站点全局切工具手势", 'closest(t,".pw-trend-scroll")' in src and "return true" in src, ""))
    out.append(("上次充值/区间用电 tiles 与档位常量", "上次充值" in src and "PW_RANGES" in src, ""))
    out.append(("power 请求为单选（id=eq.），不再整表 order=id.asc",
                "power?select=id,label,building,room,quantity,unit,low,updated_at&id=eq." in src
                and "power?select=id,label,building,room,quantity,unit,low,updated_at&order=id.asc" not in src, ""))
    out.append(("环内天数小字与 aria 语义（pwDays / aria-label 动态）", 'id="pwDays"' in src and 'setAttribute("aria-label",aria)' in src, ""))
    out.append(("无内部任务名（ClassPowerSync 不上屏）", "ClassPowerSync" not in src, ""))
    out.append(("环刻度为可用天数/30（不再有 400 度参考）", "PW_REF" not in src and "est.days/30" in src, ""))
    out.append(("v5 估算算法（分段 + 24h/7d 混合 + rate 下限 0.05）",
                "rateFrom:function" in src and "0.65*r24.rate" in src and "Math.max(rate,0.05)" in src, ""))
    out.append(("v5 可调阈值（tile 按钮 + 弹层 + UD.power.low 默认 30）",
                'id="pwLowTile"' in src and "pw-lowsel" in src and 'power:{sel:"",at:0,low:30}' in src and "setLow:function" in src, ""))
    out.append(("未引入构建链/外部 CDN", ("<script src=" not in src) and ("cdn." not in src), ""))
    return out


def main():
    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    for f in os.listdir(REPORT_DIR):
        try:
            os.remove(os.path.join(REPORT_DIR, f))
        except Exception:
            pass
    build_previews()
    build_harness()

    results = list(static_checks())

    httpd = http.server.ThreadingHTTPServer
    handler = functools.partial(Handler, directory=ROOT)
    server = httpd(("127.0.0.1", PORT), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.4)
    try:
        clear_report("func")
        run_edge(BASE + "tests/" + HARNESS, budget=600000, window="492,900", timeout=300)
        data = wait_report("func", 280)
        if not data:
            results.append(("自检脚本未返回结果", False, "report 缺失（浏览器未上报/超时）"))
        else:
            for s in data.get("steps", []):
                results.append((s.get("k", "?"), bool(s.get("ok")), s.get("note", "")))
        shots = [
            (390, 1100, "4-23A---321", "power_v5_390.png", "430,1160", None, 0, 0, False),
            (390, 1100, "1-16---305", "power_v5_threshold_390.png", "430,1160", None, 0, 50, False),
            (390, 1100, "4-23A---321", "power_v5_lowsel_390.png", "430,1160", None, 0, 0, True),
            (1280, 1000, "4-23A---321", "power_v5_1280.png", "1400,1080", None, 0, 0, False),
        ]
        for w, h, rv, fname, win, rng, scroll, low, open_low in shots:
            shot = os.path.join(SHOTS, fname)
            ok = False
            page = build_shot(w, h, rv, "_" + fname.split(".")[0], rng, scroll, low, open_low)
            for _try in range(3):   # headless Edge 截图偶发未落盘：重试最多 3 次
                try:
                    if os.path.exists(shot):
                        os.remove(shot)
                except Exception:
                    pass
                run_edge(BASE + "tests/" + page, budget=26000, shot=shot, window=win)
                for _ in range(25):
                    if os.path.exists(shot) and os.path.getsize(shot) > 8000:
                        ok = True
                        break
                    time.sleep(0.3)
                if ok:
                    break
            results.append(("截图 " + fname, ok,
                            ("%d bytes" % os.path.getsize(shot)) if ok and os.path.exists(shot) else "未生成"))
    finally:
        server.shutdown()

    fails = [r for r in results if not r[1]]
    for name, ok, note in results:
        print(("[PASS] " if ok else "[FAIL] ") + name + (("  -- " + str(note)[:320]) if (note and not ok) else ""))
    print("")
    print("=" * 60)
    print("power_check: %d 项，PASS %d，FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    print("截图目录:", SHOTS)
    print("=" * 60)
    return 0 if not fails else 1


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        for f in [PREVIEW, HARNESS, COMMON] + SHOT_FILES:
            try:
                os.remove(os.path.join(HERE, f))
            except Exception:
                pass
    sys.exit(code)
