# -*- coding: utf-8 -*-
"""性能与缓存专项自检（web 端）—— 2026-11-04 新增

用法：
    cd C:\\Users\\Ko_Li\\.openclaw\\workspace\\web\\tools
    python tests\\perf_check.py
    set PERF_SRC=某副本.html  # 复盘任意副本（如线上字节落盘的 index.html）

背景（见 _perf_task/RECON.md）：
- 通知板 auto groups 约 2MB（9 张 data URI 图片 + 5 个文件），网页每 30s 整表重拉一次、
  cache:"no-store"，进通知 tab 还会重建 64KB 模板 + 2MB JSON 的 iframe；
- 本次优化：IndexedDB 持久缓存 AUTO_NOTICES（按学号 sid 分桶 + TTL + 通知轻量签名重校验）、
  marks 勾选 localStorage 缓存、通知 iframe 懒创建、iframe 内图片懒加载、首次骨架屏、
  大表 TTL 门控 + idle 低优先级刷新。

做法（复用 reset_check.py 的驱动方式）：
- 复制 index.html 到临时预览页，注入「假身份 + fetch mock」：
  * 通知整表约 2.8MB 合成数据（24 组 auto + 19 条 manual，9 张约 300KB 合成图片 data URI、
    5 个 file data URI；全部为合成内容，不含真实班级信息）；
  * homework 12 条、marks 空、members 70 人、tt.json 合法快照；
  * 统计每一种网络请求次数（notices / notices_sig / homework / members / marks / fitrecs / tt / visits / write）
    与外部请求；
- headless Edge + 同源 iframe 固定宽度（headless 视口恒 ~492px，不能靠 --window-size）；
- 断言：
  1) 首次（无缓存）未进通知 tab：不创建 notice iframe、大表 0 请求；
  2) 进通知 tab：先骨架、随后 24 卡渲染、约 2.8MB 合成 payload、iframe 内 9 图 5 文件、
     图片已注入 loading=lazy/decoding=async、modal blur 降级、无横向溢出、无 JS 报错；
  3) 二次加载（有缓存）：通知/作业 0 网络请求、通知 tab 打开即渲染缓存；
  4) 连续 cloudPull（模拟 30s 轮询 ×N）：大表请求不增长；TTL 过期先发 ~2KB 签名，
     签名一致不拉整表；签名变化才整表重建；
  5) 缓存按 sid 隔离：换学号后必须重新拉取，不会读到别人的缓存；
  6) 退出身份：缓存换代清理，重新登录必须重新拉取；
  7) IDB 不可用 + 缓存数据损坏：不崩溃、照常拉取渲染；
  8) 360/390/430/720/1280 无横向溢出；无外部请求；0 console.error；0 JS 报错。
退出码 0 = 全绿。
"""
import functools
import hashlib
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
SRC = os.path.abspath(os.environ.get("PERF_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8931
BASE = "http://127.0.0.1:%d/" % PORT

REPORT_DIR = os.path.join(HERE, "_perf_reports")
SHOTS = os.path.join(HERE, "_perf_shots")

SID_A = "3260709999"
NAME_A = "测试同学"
SID_B = "3260708888"
NAME_B = "另一同学"
MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": ("班长" if i == 1 else ""), "badge": ("班委" if i == 1 else ""),
            "is_admin": (i == 1)} for i in range(1, 71)]

AN_PREFIX = "[[CLASS_NOTICE_V1]]"
PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
           "hKmMIQAAAABJRU5ErkJggg==")
PDF_B64 = "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PC9UeXBlL0NhdGFsb2c+PgplbmRvYmoK"
IMG_CHARS = 310000      # 每张合成图片 data URI 字符数（约 300KB）
FILE_CHARS = 40000      # 每个合成附件 data URI 字符数
BASE_TS = 1762000000000


def b64_pad(head, target):
    if len(head) >= target:
        return head[:target]
    return head + "A" * (target - len(head))


IMG_URI = "data:image/png;base64," + b64_pad(PNG_B64, IMG_CHARS)
FILE_URI = "data:application/pdf;base64," + b64_pad(PDF_B64, FILE_CHARS)


def build_data():
    cats = ["教务", "活动", "班级事务", "缴费"]
    groups = []
    for i in range(24):
        items = [{
            "kind": "text", "label": "原消息",
            "time": "11-%02d 10:%02d" % (1 + i % 9, i % 60),
            "from": "合成测试群", "fromName": "测试发送者", "fromRole": "老师", "fromBadge": "师",
            "text": "合成文本内容 %02d：仅用于性能测试，不含任何真实班级信息。" % i,
        }]
        if i < 9:
            items.append({
                "kind": "img", "label": "群二维码（合成）", "time": "11-02 19:25",
                "from": "测试发送者", "fromName": "测试发送者", "fromRole": "老师", "fromBadge": "师",
                "src": IMG_URI, "caption": "合成图片 %02d" % i,
            })
        elif i < 14:
            items.append({
                "kind": "file", "label": "附件", "time": "11-02 20:10",
                "name": "合成附件 %02d.pdf" % i, "size": "示例 120 KB",
                "src": FILE_URI, "url": FILE_URI, "note": "合成文件",
            })
        g = {
            "id": "auto_test_%02d" % i,
            "cat": cats[i % 4],
            "title": "合成通知 %02d" % i,
            "group": "合成测试群",
            "source": "QQ 合成测试群",
            "summary": "",
            "actionable": False,
            "items": items,
            "aiSegments": [{"type": "时间", "text": "11-05 12:00"}],
            "aiSummary": "第 %02d 条合成通知摘要，仅用于性能与缓存验证。" % i,
            "aiPoints": ["合成要点一 %02d" % i, "合成要点二 %02d" % i],
            "senderName": "测试发送者", "senderRole": "老师", "senderBadge": "师",
        }
        if i % 5 == 0:
            g["deadline"] = "2026-11-20 12:00"
            g["timeLabel"] = "11-20 12:00 截止"
        elif i % 5 == 1:
            g["eventAt"] = "2026-11-05 12:00"
            g["expireAt"] = "2026-11-06 12:00"
            g["timeLabel"] = "报名 11-05 12:00"
        elif i % 5 == 3:
            g["deadline"] = "2026-10-30 12:00"
            g["timeLabel"] = "10-30 12:00 截止"
        elif i % 5 == 4:
            g["eventAt"] = "2026-10-31 10:40"
            g["timeLabel"] = "10-31 10:40"
        groups.append(g)

    notices = []
    for i, g in enumerate(groups):
        notices.append({"id": g["id"], "title": "", "body": AN_PREFIX + json.dumps(g, ensure_ascii=False),
                        "archived": False, "ts": BASE_TS + i * 1000})
    for i in range(19):
        notices.append({"id": "manual_test_%02d" % i, "title": "合成手动通知 %02d" % i,
                        "body": "合成手动通知正文 %02d（性能测试用）" % i, "archived": False,
                        "ts": BASE_TS + 500000 + i * 1000})

    homework = []
    for i in range(12):
        homework.append({"id": "hw_test_%02d" % i, "subject": "合成作业 %02d" % i,
                         "content": "合成作业内容 %02d：仅用于性能测试。" % i,
                         "due": "2026-11-20", "date": "2026-11-1%d" % (i % 9), "time": "23:59",
                         "author": "测试发送者", "owner": "9000000001", "attachments": "",
                         "done": False, "archived": False, "ts": BASE_TS + i})

    tt = {"c": [{"name": "合成课程", "teacher": "测试老师", "room": "合成楼(101)",
                 "day": 0, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"}],
          "t": "2026-08-31", "meta": {"fetchedAt": BASE_TS}}

    return {"members": MEMBERS, "notices": notices, "homework": homework, "marks": [],
            "fitrecs": [], "tt": tt}


DATA = build_data()

# ------------------------------------------------------------------ 预览页注入
MOCK_JS = r"""
<script>
(function(){
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var DATA=__DATA__;
var DELAY=Number(localStorage.getItem("_perf_mock_delay")||0)||0;
window.__net={counts:{},external:[],urls:[]};
function mkResp(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
function respond(obj){if(!DELAY)return mkResp(obj);return new Promise(function(res){setTimeout(function(){res(mkResp(obj));},DELAY);});}
window.__mockBump=function(){DATA.notices.forEach(function(r){r.ts=Number(r.ts)+1000;});};
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};var method=String(o.method||"GET").toUpperCase();
  var s=String((u&&u.url!==undefined)?u.url:u);
  var kind="external",payload=[];
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0){kind="members";payload=DATA.members;}
    else if(s.indexOf("rpc/class_verify")>=0){kind="verify";payload={ok:true,token:"mock-token",sid:"--",name:"--",role:"",badge:"",is_admin:false};}
    else if(s.indexOf("/notices")>=0){
      if(method==="GET"&&s.indexOf("select=id,ts")>=0){kind="notices_sig";payload=DATA.notices.map(function(r){return {id:r.id,ts:r.ts};});}
      else if(method==="GET"){kind="notices";payload=DATA.notices;}
      else{kind="write";payload=[];}
    }
    else if(s.indexOf("/homework")>=0){
      if(method==="GET"){kind="homework";payload=DATA.homework;}else{kind="write";payload=[];}
    }
    else if(s.indexOf("/marks")>=0){
      if(method==="GET"){kind="marks";payload=DATA.marks;}else{kind="write";payload=[];}
    }
    else if(s.indexOf("/fitrecs")>=0){
      if(method==="GET"){kind="fitrecs";payload=DATA.fitrecs;}else{kind="write";payload=[];}
    }
    else if(s.indexOf("/visits")>=0){kind="visits";payload=[];}
    else if(s.indexOf("/feedback")>=0){kind="write";payload=[];}
    else{kind="write";payload=[];}
  } else if(s.indexOf("tt.json")>=0){kind="tt";payload=DATA.tt;}
  window.__net.counts[kind]=(window.__net.counts[kind]||0)+1;
  if(window.__net.urls.length<400)window.__net.urls.push(kind+" "+method+" "+s.slice(0,140));
  if(kind==="external"){window.__net.external.push(s.slice(0,160));return Promise.reject(new Error("external-blocked"));}
  return respond(payload);
};
function seedIdentity(){
  var raw=null;try{raw=localStorage.getItem("_perf_ident");}catch(e){}
  var id=null;
  if(raw===null){id={sid:"__SID_A__",name:"__NAME_A__"};}
  else{try{id=JSON.parse(raw);}catch(e){id=null;}}
  try{
    if(id)localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token-"+id.sid,sid:id.sid,name:id.name,role:"",badge:"",is_admin:false,ts:Date.now()}));
    else localStorage.removeItem("zq_class_identity");
  }catch(e){}
}
seedIdentity();
__EXTRA__
})();
</script>
"""

EXTRA_NORMAL = ""
EXTRA_OFF = r"""
/* IDB 不可用 + 缓存数据损坏：验证静默降级不崩（首次加载才注入损坏数据，方便验证二次加载行为） */
try{Object.defineProperty(window,"indexedDB",{configurable:true,get:function(){throw new Error("idb-blocked");}});}catch(e){}
try{
  var sd="__SID_A__";
  if(!localStorage.getItem("_perf_off_seeded")){
    localStorage.setItem("_perf_off_seeded","1");
    localStorage.setItem("zq_marks_cache_"+sd,"{{{bad json");
    localStorage.setItem("zq_synced_at_"+sd,"{{{bad json");
    localStorage.setItem("zq_visited_"+sd,"null");
    localStorage.setItem("zq_tt_pub","not-json");
  }
}catch(e){}
"""

PREVIEW = "_perf_preview.html"
PREVIEW_OFF = "_perf_preview_off.html"
H_FUNC = "_perf_h_func.html"
H_LAYOUT = "_perf_h_layout.html"
H_SHOT = "_perf_h_shot.html"


def build_previews():
    html = open(SRC, encoding="utf-8", newline="").read()
    # 测试后门：暴露内部函数（仅测试预览页，产品文件不含）
    hook = ('window.__perf={cloudPull:cloudPull,NT:NT,HW:HW,D:D,AUTH:AUTH,TTL:TTL,needPull:needPull,'
            'syncedRead:syncedRead,visitedRead:visitedRead,gotoTab:gotoTab,cacheNoticesGet:cacheNoticesGet,'
            'ttSyncPull:ttSyncPull,bootCached:function(){return __bootCacheDone;},'
            'bootRefreshed:function(){return __bootRefreshDone;}};')
    anchor = "})();\r\n</script>"
    idx = html.rfind(anchor)
    if idx < 0:
        raise SystemExit("[perf_check] 找不到主脚本结尾锚点")
    html = html[:idx] + hook + "\r\n" + html[idx:]
    base = MOCK_JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c"))
    for name, extra in ((PREVIEW, EXTRA_NORMAL), (PREVIEW_OFF, EXTRA_OFF)):
        js = (base.replace("__EXTRA__", extra)
                  .replace("__SID_A__", SID_A).replace("__NAME_A__", NAME_A))
        out = html.replace("<head>", "<head>" + js, 1)
        with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="") as fh:
            fh.write(out)


COMMON_JS = r"""
var SRC="__SRC__", OFF="__OFF__";
var SID_A="__SID_A__", SID_B="__SID_B__", NAME_A="__NAME_A__", NAME_B="__NAME_B__";
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
/* 让出任务队列但不推进虚拟时钟：等 IndexedDB / 渲染等真实异步任务完成 */
function pump(){
  return new Promise(function(res){
    try{
      var ch=new MessageChannel();
      ch.port1.onmessage=function(){res();};
      ch.port2.postMessage(0);
    }catch(e){setTimeout(res,0);}
  });
}
async function pumpN(n){for(var i=0;i<(n||1);i++)await pump();}
async function waitCond(fn,maxTries){
  var n=maxTries||6000;
  for(var i=0;i<n;i++){var v=false;try{v=!!fn();}catch(e){v=false;}if(v)return true;await pump();}
  return false;
}
function waitFor(fn,ms){return new Promise(function(res,rej){var t0=Date.now();
  (function loop(){var v=false;try{v=!!fn();}catch(e){v=false;}
    if(v)return res(true);
    if(Date.now()-t0>(ms||4000))return rej(new Error("waitFor timeout"));
    setTimeout(loop,25);})();});}
function mount(src,w,h){
  return new Promise(function(res,rej){
    /* 需求2 的刷新保位按 sessionStorage 生效：这里清掉，保证每个场景都从「首次访问」开始 */
    try{sessionStorage.removeItem("zq_pos_v1");}catch(e){}
    var old=document.getElementById("fr"); if(old&&old.parentNode)old.parentNode.removeChild(old);
    var f=document.createElement("iframe"); f.id="fr"; f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block";
    f.src=src;
    var done=false;
    f.onload=function(){ if(done)return; done=true; setTimeout(function(){res(f);},80); };
    f.onerror=function(){ if(done)return; done=true; rej(new Error("iframe load failed: "+src)); };
    document.body.appendChild(f);
    setTimeout(function(){ if(!done){done=true;res(f);} },15000);
  });
}
function q(f,s){return f.contentDocument.querySelector(s);}
function qa(f,s){return Array.prototype.slice.call(f.contentDocument.querySelectorAll(s));}
function click(f,s){var e=q(f,s); if(!e)throw new Error("missing element: "+s); e.click(); return e;}
function txt(f,s){var e=q(f,s); return e?e.textContent:"";}
function net(f){try{return f.contentWindow.__net||{counts:{},external:[],urls:[]};}catch(e){return {counts:{},external:[],urls:[]};}}
function counts(f){var c=net(f).counts||{},o={},k;for(k in c)o[k]=c[k];return o;}
function count(f,k){return counts(f)[k]||0;}
function total(f){var c=counts(f),n=0,k;for(k in c)n+=c[k];return n;}
function tab(f,k){
  var b=q(f,'#tabsBar button[data-tab="'+k+'"]');
  if(b){b.click();return true;}
  var w=f.contentWindow; if(w.__perf){w.__perf.gotoTab(k);return true;}
  throw new Error("no tab: "+k);
}
function frame(f){return q(f,"#noticeHost iframe");}
function frameDoc(f){var fr=frame(f);return fr?fr.contentDocument:null;}
function cards(f){var d=frameDoc(f);return d?d.querySelectorAll(".gcard").length:-1;}
function sidOf(f){try{return f.contentWindow.__perf.AUTH.sid;}catch(e){return "";}}
function setSynced(f,obj){try{f.contentWindow.localStorage.setItem("zq_synced_at_"+sidOf(f),JSON.stringify(obj));}catch(e){}}
function getSynced(f){try{return JSON.parse(f.contentWindow.localStorage.getItem("zq_synced_at_"+sidOf(f))||"{}")||{};}catch(e){return {};}}
function setIdent(sid,name){try{if(sid)localStorage.setItem("_perf_ident",JSON.stringify({sid:sid,name:name}));else localStorage.setItem("_perf_ident","false");}catch(e){}}
function setDelay(ms){try{localStorage.setItem("_perf_mock_delay",String(ms));}catch(e){}}
function errsOf(f){try{return (f.contentWindow.__errs||[]).slice();}catch(e){return ["<inaccessible>"];}}
function cerrsOf(f){try{return (f.contentWindow.__cerrs||[]).slice();}catch(e){return ["<inaccessible>"];}}
function report(slot,data){
  data=data||{}; data.slot=slot;
  try{
    var x=new XMLHttpRequest();
    x.open("POST","/_report?slot="+slot,false);
    x.setRequestHeader("Content-Type","application/json");
    x.send(JSON.stringify(data));
  }catch(e){}
}
"""

FUNC_JS = r"""
async function run(){
  var R={steps:[],diag:{}};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  var ALLERR=[], ALLCERR=[], ALLEXT=[];
  function collect(f){
    try{
      ALLERR=ALLERR.concat(errsOf(f));
      ALLCERR=ALLCERR.concat(cerrsOf(f));
      ALLEXT=ALLEXT.concat((f.contentWindow.__net&&f.contentWindow.__net.external)||[]);
    }catch(e){}
  }
  try{
    /* ============ A. 首次加载（无缓存）：大表懒拉，未进 tab 不建 iframe ============ */
    try{localStorage.removeItem("_perf_ident");}catch(e){}
    setDelay(0);
    var f=await mount(SRC,430,940), w=f.contentWindow;
    var booted=await waitCond(function(){return w.__perf&&w.__perf.bootRefreshed();},15000);
    T("首次加载：boot 完成（IDB hydrate → 小表拉取）", booted, booted);
    /* requestIdleCallback 在 headless 里可能不触发：直接调用一次模拟 idle 回调，顺带验证 tt TTL */
    if(count(f,"tt")===0){try{w.__perf.ttSyncPull();}catch(e){}}
    await waitCond(function(){var s=w.__perf.syncedRead();return !!s.tt;},15000);
    await pumpN(3);
    var ttN=count(f,"tt");
    try{w.__perf.ttSyncPull();}catch(e){}
    await pumpN(6);
    var c0=counts(f);
    T("首次无缓存：boot 后未创建通知 iframe", qa(f,"#noticeHost iframe").length===0, qa(f,"#noticeHost iframe").length);
    T("首次无缓存：通知整表 boot 阶段 0 请求", count(f,"notices")===0, JSON.stringify(c0));
    T("首次无缓存：作业整表 boot 阶段 0 请求", count(f,"homework")===0, JSON.stringify(c0));
    T("boot 阶段小表按 TTL 拉取：members=1", count(f,"members")===1, JSON.stringify(c0));
    T("boot 阶段小表按 TTL 拉取：marks=1", count(f,"marks")===1, JSON.stringify(c0));
    T("boot 阶段小表按 TTL 拉取：fitrecs=1", count(f,"fitrecs")===1, JSON.stringify(c0));
    T("tt.json 首次拉取 1 次", ttN===1, JSON.stringify(c0));
    T("tt.json TTL 内再次调用 0 请求", count(f,"tt")===ttN, JSON.stringify(counts(f)));
    T("boot 阶段无外部请求", (net(f).external||[]).length===0, JSON.stringify(net(f).external));

    /* ============ B. 进通知 tab：骨架 → 24 卡（约 2.8MB 合成 payload） ============ */
    tab(f,"nt");
    var skel=qa(f,"#noticeHost .skel-card").length;
    T("首次无缓存进通知 tab：先出现骨架占位", skel>0, skel);
    await waitCond(function(){return !!frame(f);},20000);
    var fr=frame(f), iw=fr.contentWindow, idoc=fr.contentDocument;
    await waitCond(function(){return cards(f)>=24;},20000);
    T("通知 tab：渲染 24 张通知卡", cards(f)===24, cards(f));
    var n1=counts(f);
    T("进通知 tab：整表拉取 1 次", (n1.notices||0)-(c0.notices||0)===1, JSON.stringify(n1));
    T("数据到达后骨架被内容替换", qa(f,"#noticeHost .skel").length===0, qa(f,"#noticeHost .skel").length);
    var payloadLen=0;
    try{payloadLen=JSON.stringify(iw.GROUPS).length;}catch(e){payloadLen=-1;}
    T("合成 payload ≥ 2MB（约 2.8MB 压力数据）", payloadLen>=2*1024*1024, payloadLen);
    var imgCount=idoc.querySelectorAll("img").length;
    var fileCount=idoc.querySelectorAll('[data-act="preview"]').length;
    T("iframe 内 9 张合成图片进入 DOM", imgCount>=9, imgCount);
    T("iframe 内 5 个合成附件进入 DOM", fileCount>=5, fileCount);
    var imgs=Array.prototype.slice.call(idoc.querySelectorAll("img"));
    var lazyOk=imgs.length>0&&imgs.every(function(im){return im.getAttribute("loading")==="lazy"&&(im.getAttribute("decoding")==="async"||!im.hasAttribute("decoding"));});
    T("iframe 内图片已注入 loading=lazy / decoding=async", lazyOk, imgs.length+" imgs");
    var noBlur=false;
    Array.prototype.slice.call(idoc.querySelectorAll("style")).forEach(function(s){if(String(s.textContent||"").indexOf("backdrop-filter:none")>=0)noBlur=true;});
    T("iframe 内 modal backdrop-filter 已降级", noBlur, noBlur);
    var over1=idoc.documentElement.scrollWidth<=iw.innerWidth+1;
    T("iframe 内无横向溢出（430 宽）", over1, idoc.documentElement.scrollWidth+"/"+iw.innerWidth);
    T("通知卡渲染后无 JS 报错", errsOf(f).length===0, errsOf(f).join(" | "));

    /* ============ C. 作业 tab：骨架 → 12 条 ============ */
    tab(f,"hw");
    var hsk=qa(f,"#hList .skel-card").length;
    T("首次无缓存进作业 tab：先出现骨架占位", hsk>0, hsk);
    await waitCond(function(){return qa(f,"#hList .item").length===12;},20000);
    T("作业 tab：渲染 12 条", qa(f,"#hList .item").length===12, qa(f,"#hList .item").length);
    T("作业 tab：骨架被内容替换", qa(f,"#hList .skel").length===0, qa(f,"#hList .skel").length);
    var n2=counts(f);
    T("作业 tab：整表拉取 1 次", (n2.homework||0)-(c0.homework||0)===1, JSON.stringify(n2));

    /* ============ D. 30s 轮询 ×N：TTL 内大表 0 请求 ============ */
    var b=counts(f);
    for(var i=0;i<5;i++)w.__perf.cloudPull();
    await pumpN(6);
    var a=counts(f);
    T("连续 cloudPull ×5：通知整表请求不增长", (a.notices||0)===(b.notices||0), (b.notices||0)+"->"+(a.notices||0));
    T("连续 cloudPull ×5：作业整表请求不增长", (a.homework||0)===(b.homework||0), (b.homework||0)+"->"+(a.homework||0));
    T("连续 cloudPull ×5：TTL 内连签名请求也不发", (a.notices_sig||0)===(b.notices_sig||0), (b.notices_sig||0)+"->"+(a.notices_sig||0));

    /* ============ E. TTL 过期：先 2KB 签名；一致不拉整表 ============ */
    var syn=getSynced(f); syn.nt=Date.now()-11*60*1000; setSynced(f,syn);
    var b2=counts(f); w.__perf.cloudPull(); await pumpN(12);
    var a2=counts(f);
    T("通知 TTL 过期：先发 1 次轻量签名请求", (a2.notices_sig||0)-(b2.notices_sig||0)===1, JSON.stringify(a2));
    T("签名一致：不拉 2MB 整表", (a2.notices||0)-(b2.notices||0)===0, JSON.stringify(a2));
    T("签名一致后：通知 24 卡保持", cards(f)===24, cards(f));
    var b3=counts(f); w.__perf.cloudPull(); await pumpN(6);
    var a3=counts(f);
    T("签名命中后刷新 lastSync：再次轮询 0 请求", (a3.notices_sig||0)===(b3.notices_sig||0) && (a3.notices||0)===(b3.notices||0), JSON.stringify(a3));

    /* ============ F. 数据真的变了：签名不一致才整表重建 ============ */
    w.__mockBump();
    var syn2=getSynced(f); syn2.nt=Date.now()-11*60*1000; setSynced(f,syn2);
    var b4=counts(f); w.__perf.cloudPull();
    await waitCond(function(){return (count(f,"notices")||0)>(b4.notices||0);},12000);
    await pumpN(6);
    var a4=counts(f);
    T("通知内容变化：签名 1 次 + 整表 1 次", (a4.notices_sig||0)-(b4.notices_sig||0)===1 && (a4.notices||0)-(b4.notices||0)===1, JSON.stringify(a4));
    T("整表更新后通知仍 24 卡、无 JS 报错", cards(f)===24, cards(f));
    collect(f);

    /* ============ G. 二次加载（有缓存）：通知/作业 0 请求、缓存秒开 ============ */
    var f2=await mount(SRC,430,940), w2=f2.contentWindow;
    await waitCond(function(){return w2.__perf&&w2.__perf.bootRefreshed();},15000);
    /* 需求16：bootRefresh 现在会强制拉一次 marks（跨端状态）；其余大表仍必须 0 请求 */
    var c2=counts(f2), c2nonMarks=0;
    Object.keys(c2).forEach(function(k){ if(k!=="marks") c2nonMarks+=c2[k]; });
    T("二次加载：boot 阶段除强制拉一次 marks 外 0 网络请求（全表 TTL 内；需求16）",
      c2nonMarks===0 && (c2.marks||0)<=1, JSON.stringify(c2));
    T("二次加载：未进通知 tab 不创建 iframe", qa(f2,"#noticeHost iframe").length===0, qa(f2,"#noticeHost iframe").length);
    await waitCond(function(){return w2.__perf.NT.hydrated||w2.__perf.NT.sig;},12000);
    var t0=performance.now();
    tab(f2,"nt");
    await waitCond(function(){return !!frame(f2);},12000);
    var dt=Math.round(performance.now()-t0);
    T("二次加载：进通知 tab 缓存秒开（iframe <1200ms）", dt<1200, dt+"ms");
    await waitCond(function(){return cards(f2)===24;},20000);
    R.diag.cacheHitMs=dt;
    await sleep(400);
    T("二次加载：通知 24 卡来自缓存", cards(f2)===24, cards(f2));
    T("二次加载：通知整表 0 请求", count(f2,"notices")===0, JSON.stringify(counts(f2)));
    tab(f2,"hw");
    await pumpN(4);
    T("二次加载：作业 12 条来自本机缓存", qa(f2,"#hList .item").length===12, qa(f2,"#hList .item").length);
    T("二次加载：作业整表 0 请求", count(f2,"homework")===0, JSON.stringify(counts(f2)));
    T("二次加载：全程无外部请求", (net(f2).external||[]).length===0, JSON.stringify(net(f2).external));
    collect(f2);

    /* ============ H. 缓存按 sid 隔离 ============ */
    setIdent(SID_B,NAME_B);
    var f3=await mount(SRC,430,940), w3=f3.contentWindow;
    await waitCond(function(){return w3.__perf&&w3.__perf.bootRefreshed();},15000);
    T("换学号：boot 不误用他人缓存创建 iframe", qa(f3,"#noticeHost iframe").length===0, qa(f3,"#noticeHost iframe").length);
    tab(f3,"nt");
    await waitCond(function(){return cards(f3)===24;},20000);
    T("换学号：必须整表拉取（看不到上一个学号的缓存）", count(f3,"notices")===1, JSON.stringify(counts(f3)));
    T("换学号：24 卡正常渲染", cards(f3)===24, cards(f3));
    collect(f3);

    /* ============ I. 退出身份：缓存换代清理 ============ */
    setIdent(SID_A,NAME_A);
    var f4=await mount(SRC,430,940), w4=f4.contentWindow;
    await waitCond(function(){return w4.__perf&&w4.__perf.bootRefreshed();},15000);
    tab(f4,"nt");
    await waitCond(function(){return cards(f4)===24;},20000);
    T("回到原学号：缓存命中 0 请求", count(f4,"notices")===0, JSON.stringify(counts(f4)));
    setIdent("", "");
    w4=f4.contentWindow; w4.confirm=function(){return true;};
    click(f4,"#idChip");
    var gateOk=await waitCond(function(){return f4.contentDocument&&f4.contentDocument.body.classList.contains("id-locked");},20000);
    T("退出身份：回到身份门禁页", gateOk, gateOk);
    collect(f4);
    setIdent(SID_A,NAME_A);
    var f5=await mount(SRC,430,940), w5=f5.contentWindow;
    await waitCond(function(){return w5.__perf&&w5.__perf.bootRefreshed();},15000);
    T("退出后重登：未进通知 tab 不创建 iframe", qa(f5,"#noticeHost iframe").length===0, qa(f5,"#noticeHost iframe").length);
    tab(f5,"nt");
    await waitCond(function(){return cards(f5)===24;},20000);
    T("退出后重登：缓存已清理，通知整表重新拉取 1 次", count(f5,"notices")===1, JSON.stringify(counts(f5)));
    collect(f5);

    /* ============ J. 汇总错误 ============ */
    R.diag.payloadLen=payloadLen;
    R.diag.imgCount=imgCount;
    R.diag.fileCount=fileCount;
    R.diag.cacheHitMs=dt;
    T("全程 0 console.error", ALLCERR.length===0, ALLCERR.slice(0,5).join(" | "));
    T("全程 0 JS 报错", ALLERR.length===0, ALLERR.slice(0,5).join(" | "));
    T("全程无外部请求", ALLEXT.length===0, ALLEXT.slice(0,5).join(" | "));
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("func",R);
}
run();
"""

LAYOUT_JS = r"""
async function run(){
  var R={steps:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  var W=__W__;
  try{
    var f=await mount(SRC,W,940), w=f.contentWindow, doc=f.contentDocument;
    await waitCond(function(){return w.__perf&&w.__perf.bootRefreshed();},15000);
    tab(f,"nt");
    await waitCond(function(){return cards(f)===24;},25000);
    var idoc=frameDoc(f);
    T("通知页 24 卡", cards(f)===24, cards(f));
    T("主页面无横向溢出", doc.documentElement.scrollWidth<=w.innerWidth+1, doc.documentElement.scrollWidth+"/"+w.innerWidth);
    T("通知 iframe 内无横向溢出", idoc.documentElement.scrollWidth<=idoc.defaultView.innerWidth+1, idoc.documentElement.scrollWidth+"/"+idoc.defaultView.innerWidth);
    T("骨架已消失", qa(f,"#noticeHost .skel").length===0, qa(f,"#noticeHost .skel").length);
    T("0 JS 报错", errsOf(f).length===0, errsOf(f).join(" | "));
    T("0 console.error", cerrsOf(f).length===0, cerrsOf(f).join(" | "));
    T("无外部请求", (net(f).external||[]).length===0, JSON.stringify(net(f).external));
    R.diag={width:W,scrollW:doc.documentElement.scrollWidth,innerW:w.innerWidth,
            iframeScrollW:idoc.documentElement.scrollWidth,iframeInnerW:idoc.defaultView.innerWidth};
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("layout_"+W,R);
}
run();
"""

SHOT_JS = r"""
async function run(){
  var R={steps:[],diag:{}};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var hash=(location.hash||"#390").replace("#","");
    var m=hash.match(/^(390|1280)$/); var W=m?+m[1]:390;
    var f=await mount(SRC,W,940), w=f.contentWindow, doc=f.contentDocument;
    await waitCond(function(){return w.__perf&&w.__perf.bootRefreshed();},15000);
    tab(f,"nt");
    await waitCond(function(){return cards(f)===24;},25000);
    await pumpN(4);
    R.diag={width:W,cards:cards(f)};
    T("截图场景就绪："+W+" 宽通知页 24 卡", cards(f)===24, cards(f));
    T("无横向溢出", doc.documentElement.scrollWidth<=w.innerWidth+1, doc.documentElement.scrollWidth+"/"+w.innerWidth);
    T("0 JS 报错", errsOf(f).length===0, errsOf(f).join(" | "));
    report("shot_"+W,R);
    await pumpN(4);
  }catch(e){
    R.steps.push({k:"截图脚本异常",ok:false,note:String(e&&e.stack||e)});
    report("shot_error",R);
  }
}
run();
"""


def build_harness(name, js):
    body = (COMMON_JS.replace("__SRC__", PREVIEW).replace("__OFF__", PREVIEW_OFF)
            .replace("__SID_A__", SID_A).replace("__SID_B__", SID_B)
            .replace("__NAME_A__", NAME_A).replace("__NAME_B__", NAME_B) + "\n" + js)
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>perf check</title>"
            "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
            "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
    open(os.path.join(HERE, name), "w", encoding="utf-8").write(html)


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


def run_edge(url, budget=14000, shot=None, timeout=240, window="492,940", flags=None):
    prof = tempfile.mkdtemp(prefix="edgeprof_", dir=REPORT_DIR)
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=" + window,
            "--virtual-time-budget=%d" % budget, "--user-data-dir=" + prof]
    if flags:
        args.extend(flags)
    if shot:
        args.append("--screenshot=" + shot)
    args.append(url)
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def clear_report(slot):
    p = os.path.join(REPORT_DIR, slot + ".json")
    if os.path.exists(p):
        try:
            os.remove(p)
        except Exception:
            pass


def wait_report(slot, secs=40):
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


def run_and_report(url, slot, budget=60000, shot=None, window="492,940", secs=45, retries=2, flags=None):
    data = None
    last = None
    for _ in range(retries):
        clear_report(slot)
        last = run_edge(url, budget=budget, shot=shot, window=window, flags=flags)
        data = wait_report(slot, secs)
        if data:
            return data
        time.sleep(0.3)
    if os.environ.get("PERF_DEBUG") and last is not None:
        err = (last.stderr or b"").decode("utf-8", "replace")[-1500:]
        print("[DEBUG] slot=%s rc=%s stderr=%s" % (slot, last.returncode, err.replace("\n", " | ")))
    return None


STATIC_CHECKS = []


def static_checks(html):
    main = re.findall(r"<script>(.*?)</script>", html, re.S)[-1]
    slim = re.sub(r'var NOTICE_TPL_B64="[^"]*"', 'var NOTICE_TPL_B64="";', main)

    def no(pat, label):
        STATIC_CHECKS.append((label, not re.search(pat, slim), ""))

    no(r"=\s*>\s*|\barrow\b|=>", "主脚本无箭头函数（ES5 兼容）")
    no(r"\bconst\s+[A-Za-z_$]", "主脚本无 const（ES5 兼容）")
    no(r"\blet\s+[A-Za-z_$]", "主脚本无 let（ES5 兼容）")
    no(r"\basync\s+function\b|\bawait\s+", "主脚本无 async/await（ES5 兼容）")
    no(r"\?\.", "主脚本无可选链（ES5 兼容）")
    no(r"\?\?", "主脚本无 ??（ES5 兼容）")
    no(r'type\s*=\s*"module"', "无 ES module / 构建链")
    ext = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)', html)
    STATIC_CHECKS.append(("零外部资源引用（src/href 无 http/https）", len(ext) == 0, str(ext[:3])))
    STATIC_CHECKS.append(("缓存版本/ TTL 集中定义", "var CACHE_VER=" in html and "var TTL={" in html, ""))
    STATIC_CHECKS.append(("通知轻量签名请求存在", "function cbSig()" in html and "select=id,ts" in html, ""))
    STATIC_CHECKS.append(("通知 iframe 懒创建（CURTAB 门控）", 'if(CURTAB!=="nt")return;' in html, ""))
    STATIC_CHECKS.append(("iframe 内图片懒加载注入", 'setAttribute("loading","lazy")' in html, ""))
    STATIC_CHECKS.append(("iframe 内 modal blur 降级", "backdrop-filter:none" in html, ""))
    STATIC_CHECKS.append(("退出身份清理缓存", "cacheKill()" in html, ""))
    STATIC_CHECKS.append(("持久缓存只存通知大表（IndexedDB）", 'CACHE_DB="zq_cache_v1"' in html and 'IDBQ.put("notices"' in html, ""))
    STATIC_CHECKS.append(("大表 TTL 门控（needPull）", "function needPull(name)" in html and "!needPull(" in html, ""))
    STATIC_CHECKS.append(("既有本机持久层键未改（zq_tools_v2）", 'KEY="zq_tools_v2"' in html, ""))


def main():
    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    for fn in os.listdir(REPORT_DIR):
        try:
            os.remove(os.path.join(REPORT_DIR, fn))
        except Exception:
            pass
    html = open(SRC, encoding="utf-8").read()
    static_checks(html)
    build_previews()
    build_harness(H_FUNC, FUNC_JS)
    httpd = Q(("127.0.0.1", PORT), functools.partial(Handler, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)

    results = []

    def add_many(prefix, data):
        if not data:
            results.append((prefix + " 未返回结果", False, "report 缺失（浏览器未上报）"))
            return
        for s in data.get("steps", []):
            results.append(("[" + prefix + "] " + s.get("k", "?"), bool(s.get("ok")), s.get("note", "")))

    try:
        # 1) 功能专项（缓存/懒渲染/签名/TTL/隔离/退出清理）
        add_many("功能", run_and_report(BASE + "tests/" + H_FUNC, "func", budget=150000, window="492,940", secs=90))

        # 2) 缓存损坏 / IDB 不可用（同一功能脚本，跑 OFF 预览页）
        build_harness(H_LAYOUT, LAYOUT_JS.replace("__W__", "430"))
        # func 脚本里 SRC 指向 PREVIEW；OFF 用例单独脚本
        off_js = r"""
async function run(){
  var R={steps:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(OFF,430,940), w=f.contentWindow, doc=f.contentDocument;
    await waitCond(function(){return w.__perf&&w.__perf.bootRefreshed();},15000);
    T("IDB 不可用/缓存损坏：页面正常进入班级", !doc.body.classList.contains("id-locked"), doc.body.className);
    T("IDB 不可用/缓存损坏：未进通知 tab 不建 iframe", qa(f,"#noticeHost iframe").length===0, qa(f,"#noticeHost iframe").length);
    tab(f,"nt");
    await waitCond(function(){return cards(f)===24;},25000);
    T("IDB 不可用/缓存损坏：仍整表拉取并渲染 24 卡", cards(f)===24 && count(f,"notices")===1, cards(f)+"/"+count(f,"notices"));
    tab(f,"hw");
    await waitCond(function(){return qa(f,"#hList .item").length===12;},20000);
    T("IDB 不可用/缓存损坏：作业照常渲染", qa(f,"#hList .item").length===12, qa(f,"#hList .item").length);
    T("IDB 不可用/缓存损坏：0 JS 报错", errsOf(f).length===0, errsOf(f).join(" | "));
    T("IDB 不可用/缓存损坏：0 console.error", cerrsOf(f).length===0, cerrsOf(f).join(" | "));
    T("IDB 不可用/缓存损坏：无外部请求", (net(f).external||[]).length===0, JSON.stringify(net(f).external));
    /* 二次加载：TTL 内但 IDB 不可用 → 内存无通知数据，必须重新整表拉取（静默退回原行为，不能空屏） */
    var f2=await mount(OFF,430,940), w2=f2.contentWindow;
    await waitCond(function(){return w2.__perf&&w2.__perf.bootRefreshed();},15000);
    T("IDB 不可用二次加载：boot 不误创建 iframe", qa(f2,"#noticeHost iframe").length===0, qa(f2,"#noticeHost iframe").length);
    tab(f2,"nt");
    await waitCond(function(){return cards(f2)===24;},25000);
    T("IDB 不可用二次加载：仍整表拉取并渲染（不空屏）", cards(f2)===24 && count(f2,"notices")===1, cards(f2)+"/"+count(f2,"notices"));
    T("IDB 不可用二次加载：0 JS 报错", errsOf(f2).length===0, errsOf(f2).join(" | "));
    T("IDB 不可用二次加载：0 console.error", cerrsOf(f2).length===0, cerrsOf(f2).join(" | "));
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("off",R);
}
run();
"""
        build_harness(H_SHOT, off_js)  # 复用文件名位
        add_many("降级", run_and_report(BASE + "tests/" + H_SHOT, "off", budget=60000, secs=45))

        # 3) 各档宽度：无横向溢出 + 通知页 24 卡
        for w in (360, 390, 430, 720, 1280):
            js = LAYOUT_JS.replace("__W__", str(w))
            build_harness(H_LAYOUT, js)
            add_many("宽度@" + str(w), run_and_report(BASE + "tests/" + H_LAYOUT, "layout_%d" % w,
                                                     budget=40000, secs=30))

        # 4) 截图：390（手机）/ 1280（桌面）通知页
        for w, fname, winsz in ((390, "perf_notice_390.png", "500,940"),
                                (1280, "perf_notice_1280.png", "1300,940")):
            p = os.path.join(SHOTS, fname)
            if os.path.exists(p):
                os.remove(p)
            build_harness(H_SHOT, SHOT_JS)
            data = run_and_report(BASE + "tests/" + H_SHOT + "#" + str(w), "shot_" + str(w),
                                  budget=70000, shot=p, window=winsz, secs=30)
            add_many("截图:" + fname, data)
            ok = os.path.exists(p) and os.path.getsize(p) > 10000
            results.append(("截图 " + fname, ok, ("%d bytes" % os.path.getsize(p)) if os.path.exists(p) else "未生成"))
    finally:
        httpd.shutdown()

    for name, ok, note in STATIC_CHECKS:
        results.insert(0, ("[静态] " + name, bool(ok), note))

    fails = [r for r in results if not r[1]]
    for name, ok, note in results:
        print(("[PASS] " if ok else "[FAIL] ") + name + (("  -- " + note[:240]) if (note and not ok) else ""))
    print("")
    print("=" * 60)
    print("perf_check: %d 项，PASS %d，FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    print("截图目录:", SHOTS)
    print("=" * 60)
    return 0 if not fails else 1


def cleanup():
    for f in (PREVIEW, PREVIEW_OFF, H_FUNC, H_LAYOUT, H_SHOT):
        try:
            os.remove(os.path.join(HERE, f))
        except Exception:
            pass


if __name__ == "__main__":
    try:
        code = main()
    finally:
        cleanup()
    sys.exit(code)
