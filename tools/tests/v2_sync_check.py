# -*- coding: utf-8 -*-
"""v2 专项自检 3/3：跨端同步（需求 14 体测男女/年级 + 需求 16 通知已处理/作业完成）

覆盖：
  需求14：UD.userdata v6 的 fit section 必含 sex/grade ——
          A. 本机改体测性别/年级 → 推送 blob.fit.sex/grade 正确；
          B. 远端 blob 改 sex/grade → 拉取后应用并刷新体测页 UI（radio/select/输入框）；
          C. 两端往返：应用远端后的再次推送不丢 sex/grade；
  需求16：
          D. iframe 点「已处理」→ POST marks(kind=ntdone)（id=<sid>|ntdone|<ref>）；
          E. 另一设备写入 marks → 强制拉取后父页 NT.done / iframe 状态 / 列表刷新；
          F. 离线写入失败 → markPend 待补发；云端旧状态不得冲掉本地勾选（pending overlay）；恢复后补发成功；
          G. 回到前台（visibilitychange）强制拉一次 marks；切页（hw/nt）强制拉一次 marks（5s 防抖内合并）；
          H. 作业完成同理：远端 marks(kind=hw) → 作业列表显示已完成；本机勾选 → 写 marks。

用法：cd C:\\...\\web\\tools && python tests\\v2_sync_check.py
      set V2S_SRC=某副本.html
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
SRC = os.path.abspath(os.environ.get("V2S_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8981
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_v2_sync_reports")
SID = "9999000005"
NAME = "测试同学"
AN_PREFIX = "[[CLASS_NOTICE_V1]]"
BASE_TS = 1762000000000

MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": ("班长" if i == 1 else ""), "badge": ("班委" if i == 1 else ""),
            "is_admin": False} for i in range(1, 71)]


def build_data():
    groups = []
    for gid, title in (("g_testA", "合成通知 A"), ("g_testB", "合成通知 B"), ("g_testC", "合成通知 C")):
        g = {"id": gid, "cat": "教务", "title": title, "group": "合成测试群", "source": "QQ 合成测试群",
             "summary": "摘要", "actionable": True,
             "items": [{"kind": "text", "label": "原消息", "time": "11-05 10:00", "text": "合成文本。"}],
             "aiSummary": "AI 摘要", "aiPoints": ["要点"],
             "deadline": "2026-11-20 12:00", "timeLabel": "11-20 12:00 截止"}
        groups.append(g)
    notices = [{"id": "auto_" + g["id"], "title": "", "body": AN_PREFIX + json.dumps(g, ensure_ascii=False),
                "archived": False, "hidden": False, "override_json": "", "edited_at": 0,
                "ts": BASE_TS + i * 1000} for i, g in enumerate(groups)]
    homework = [{"id": "hwA", "subject": "合成作业 A", "content": "内容 A", "due": "2026-11-20",
                 "date": "2026-11-20", "time": "23:59", "author": "测试", "owner": "9000000001",
                 "attachments": "", "done": False, "archived": False, "ts": BASE_TS + 10},
                {"id": "hwB", "subject": "合成作业 B", "content": "内容 B", "due": "2026-11-21",
                 "date": "2026-11-21", "time": "23:59", "author": "测试", "owner": "9000000001",
                 "attachments": "", "done": False, "archived": False, "ts": BASE_TS + 11}]
    tt = {"c": [{"name": "合成课程", "teacher": "老师", "room": "楼(101)", "day": 0,
                 "start": 1, "end": 2, "weeks": "1-16", "parity": "all"}], "t": "2026-08-31",
          "meta": {"fetchedAt": BASE_TS}}
    return {"members": MEMBERS, "notices": notices, "homework": homework, "tt": tt}


DATA = build_data()

MOCK_JS = r"""
<script>
(function(){
window.__errs=[];window.__cerrs=[];window.__external=[];window.__counts={};
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var DATA=window.__mockData=__DATA__;
window.__mk={
  ud:null, udPosts:[], marks:[], markPosts:[], markFail:false, markGet:0,
  bump:function(key){window.__counts[key]=(window.__counts[key]||0)+1;},
  setUd:function(v){window.__mk.ud=v;},
  getUd:function(){return window.__mk.ud;},
  setMark:function(kind,ref,val){window.__mk.marks=window.__mk.marks.filter(function(r){return !(r.kind===kind&&r.ref===ref);});
    window.__mk.marks.push({id:"__SID__|"+kind+"|"+ref,seat:"__SID__",kind:kind,ref:ref,val:!!val,ts:Date.now()});},
  fail:function(v){window.__mk.markFail=!!v;}
};
function mkOk(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
function mkErr(){return Promise.resolve({ok:false,status:500,json:function(){return Promise.resolve({});},text:function(){return Promise.resolve("");}});}
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};var method=String(o.method||"GET").toUpperCase();
  var s=String((u&&u.url!==undefined)?u.url:u);
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0){window.__mk.bump("members");return mkOk(DATA.members);}
    if(s.indexOf("rpc/class_verify")>=0)return mkOk({ok:true,token:"t",sid:"__SID__",name:"__NAME__",is_admin:false});
    if(s.indexOf("/notices")>=0){
      if(method==="GET"){
        var sig=(s.indexOf("select=id,ts")>=0);
        window.__mk.bump(sig?"notices_sig":"notices");
        if(sig)return mkOk(DATA.notices.map(function(r){return {id:r.id,ts:r.ts,hidden:!!r.hidden,edited_at:Number(r.edited_at)||0};}));
        return mkOk(DATA.notices);
      }
      return mkOk([]);
    }
    if(s.indexOf("/homework")>=0){if(method==="GET"){window.__mk.bump("homework");return mkOk(DATA.homework);}return mkOk([]);}
    if(s.indexOf("/marks")>=0){
      if(method==="GET"){window.__mk.markGet++;return mkOk(window.__mk.marks.slice());}
      var rows=[];try{rows=JSON.parse(o.body||"[]");}catch(e){rows=[];}
      window.__mk.markPosts.push(rows);
      if(window.__mk.markFail)return mkErr();
      rows.forEach(function(r){
        window.__mk.marks=window.__mk.marks.filter(function(x){return x.id!==r.id;});
        window.__mk.marks.push(r);
      });
      return mkOk(rows);
    }
    if(s.indexOf("/fitrecs")>=0){return mkOk(method==="GET"?[]:[]);}
    if(s.indexOf("/userdata")>=0){
      if(method==="GET"){
        window.__mk.bump("userdata");
        return mkOk(window.__mk.ud?[{id:"__SID__",blob:JSON.stringify(window.__mk.ud),ts:Date.now()}]:[]);
      }
      var body=[];try{body=JSON.parse(o.body||"[]");}catch(e){body=[];}
      var rec=body[0]||null;
      if(rec){
        try{window.__mk.ud=JSON.parse(rec.blob);}catch(e){}
        window.__mk.udPosts.push(rec.blob);
      }
      return mkOk([]);
    }
    if(s.indexOf("/visits")>=0){window.__mk.bump("visits");return mkOk([]);}
    if(s.indexOf("/feedback")>=0)return mkOk([]);
    window.__mk.bump("other");return mkOk([]);
  }
  if(s.indexOf("tt.json")>=0){window.__mk.bump("tt");return mkOk(DATA.tt);}
  window.__external.push(s);window.__mk.bump("external");
  return _f.apply(this,arguments);
};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
})();
</script>
"""

HOOK = r"""
window.__v2sync={
  AUTH:AUTH,D:D,NT:NT,HW:HW,UD:UD,
  marksPull:marksPull, marksApply:marksApply, resyncPending:resyncPending,
  noticePushDone:noticePushDone, noticeSetDone:noticeSetDone,
  gotoTab:gotoTab, cloudPull:cloudPull, frame:function(){return NOTICE_FRAME;},
  AN_DONE:function(){return AN_DONE;}, markPend:function(){return D.d.markPend;},
  hwDoneOf:hwDoneOf, renderHW:renderHW, bootDone:function(){return __bootRefreshDone;},
  errs:function(){return window.__errs||[];},cerrs:function(){return window.__cerrs||[];},
  mk:function(){return window.__mk;}, counters:function(){return window.__counts;},
  resetMarksForce:function(){marksPull._forceAt=0;}, savedMarksTime:function(){return syncedRead();},
  setMarksFresh:function(){syncedMark("marks");}
};
"""


def build_previews():
    html = open(SRC, encoding="utf-8", newline="").read()
    idx = html.rfind("})();")
    if idx < 0:
        raise SystemExit("[v2_sync_check] 找不到主脚本结尾锚点")
    html = html[:idx] + HOOK + "\r\n" + html[idx:]
    mock = MOCK_JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")) \
                  .replace("__SID__", SID).replace("__NAME__", NAME)
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    return html.replace("<head>", "<head>" + mock, 1)


COMMON_JS = r"""
var SRC="__SRC__", SID="__SID__";
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
function pump(){
  return new Promise(function(res){
    try{var ch=new MessageChannel();ch.port1.onmessage=function(){res();};ch.port2.postMessage(0);}
    catch(e){setTimeout(res,0);}
  });
}
async function pumpN(n){for(var i=0;i<(n||1);i++)await pump();}
async function waitCond(fn,maxTries){
  var n=maxTries||12000;
  for(var i=0;i<n;i++){var v=false;try{v=!!fn();}catch(e){v=false;}if(v)return true;await pump();}
  return false;
}
function mount(src,w,h){
  return new Promise(function(res,rej){
    try{sessionStorage.removeItem("zq_pos_v1");}catch(e){}
    var old=document.getElementById("fr"); if(old&&old.parentNode)old.parentNode.removeChild(old);
    var f=document.createElement("iframe"); f.id="fr"; f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block";
    f.src=src;
    var done=false;
    f.onload=function(){if(done)return;done=true;setTimeout(function(){res(f);},80);};
    f.onerror=function(){if(done)return;done=true;rej(new Error("iframe load failed"));};
    document.body.appendChild(f);
    setTimeout(function(){if(!done){done=true;res(f);}},15000);
  });
}
function q(f,s){return f.contentDocument.querySelector(s);}
function qa(f,s){return Array.prototype.slice.call(f.contentDocument.querySelectorAll(s));}
function tab(f,k){
  var b=q(f,'#tabsBar button[data-tab="'+k+'"]');
  if(b){b.click();return true;}
  var w=f.contentWindow; if(w.__v2sync){w.__v2sync.gotoTab(k);return true;}
  throw new Error("no tab "+k);
}
function frame(f){return q(f,"#noticeHost iframe");}
function frameDoc(f){var fr=frame(f);return fr?fr.contentDocument:null;}
function frameWin(f){var fr=frame(f);return fr?fr.contentWindow:null;}
function posts(f,p){try{return f.contentWindow.__mk[p].slice();}catch(e){return [];}}
function blobs(f){return posts(f,"udPosts").map(function(s){try{return JSON.parse(s);}catch(e){return null;}});}
function mk(f){return f.contentWindow.__mk;}
function counters(f){try{return f.contentWindow.__counts;}catch(e){return {};}}
function clickEl(f,sel){
  var el=q(f,sel); if(!el)throw new Error("missing "+sel); el.click(); return el;
}
function report(slot,data){
  data=data||{}; data.slot=slot;
  try{var x=new XMLHttpRequest();x.open("POST","/_report?slot="+slot,false);
      x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(data));}catch(e){}
}
"""

MAIN_JS = r"""
async function run(){
  var R={steps:[],diag:{}};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  var ALLERR=[],ALLCERR=[],ALLEXT=[];
  function collect(f){
    try{ALLERR=ALLERR.concat(f.contentWindow.__v2sync.errs());}catch(e){}
    try{ALLCERR=ALLCERR.concat(f.contentWindow.__v2sync.cerrs());}catch(e){}
    try{ALLEXT=ALLEXT.concat(f.contentWindow.__external||[]);}catch(e){}
  }
  try{
    try{localStorage.clear();}catch(e){}
    var f=await mount(SRC,430,940), w=f.contentWindow, S=w.__v2sync;
    await waitCond(function(){return S&&S.bootDone&&S.bootDone();},15000);
    await pumpN(4);

    /* ============ A. 需求14：体测 sex/grade 同步（本机 → 云端） ============ */
    var sec=S.UD.sections();
    T("A1 UD.sections().fit 含 sex/grade", sec.fit&&"sex" in sec.fit&&"grade" in sec.fit, JSON.stringify(sec.fit).slice(0,120));
    tab(f,"ft");
    await pumpN(4);
    var fem=q(f,'input[name=ftsex][value="f"]');
    fem.click();
    var gs=q(f,"#fGrade"); gs.value="34"; gs.dispatchEvent(new Event("change",{bubbles:true}));
    await sleep(2200);
    await pumpN(4);
    var b1=blobs(f), last=b1[b1.length-1]||null;
    T("A2 本机改体测性别 → 推送 blob.fit.sex=f", !!last&&last.fit&&last.fit.sex==="f", last?JSON.stringify(last.fit).slice(0,160):"");
    T("A3 本机改年级 → 推送 blob.fit.grade=34", !!last&&last.fit&&last.fit.grade==="34", last?String(last.fit.grade):"");
    T("A4 fit.at 已更新（脏检测生效）", !!last&&last.at&&Number(last.at.fit)>0, last&&last.at?String(last.at.fit):"");

    /* ============ B. 需求14：云端 → 本机（应用并刷新 UI） ============ */
    var remote={v:6,at:{homeTools:0,fit:Date.now()+60000,draw:0,group:0,roster:0,hide:0,tt:0,prefs:0,nick:0},
      homeTools:["draw","hw","nt","tt"],fit:{sex:"m",grade:"12",h:"176",w:"",vc:"",r50:"",sit:"",jump:"",pull:"",durM:"",durS:""},
      draw:{},group:{},roster:{rosterSel:[],rollSel:[],rollSt:{},rollNames:""},hide:{hwHide:{},ntHide:{}},
      tt:{ttView:"",ttUseMine:false,ttLocal:null,termStart:""},prefs:{hwRemind:{},ntSub:false,ntSubAt:0},nick:""};
    mk(f).setUd(remote);
    S.cloudPull(true);
    var gotSex=await waitCond(function(){return S.D.d.fit.sex==="m"&&S.D.d.fit.grade==="12";},20000);
    T("B1 远端 fit.sex=m → 本机数据已应用", gotSex, S.D.d.fit.sex+"/"+S.D.d.fit.grade);
    await pumpN(4);
    var domSex = q(f,'input[name=ftsex][value="m"]').checked;
    T("B2 远端 sex 应用后体测页 radio 刷新", domSex===true, domSex);
    T("B3 远端 grade 应用后体测页 select 刷新", q(f,"#fGrade").value==="12", q(f,"#fGrade").value);
    T("B4 远端 fit 其它字段也应用（h=176）", S.D.d.fit.h==="176", S.D.d.fit.h);
    T("B5 远端应用后 h 输入框刷新", q(f,"#fH").value==="176", q(f,"#fH").value);

    /* C. 往返：应用远端后再推一次，sex/grade 不丢 */
    await sleep(300);
    q(f,'input[name=ftsex][value="f"]').click();
    await sleep(2000);
    await pumpN(4);
    var b2=blobs(f); var last2=b2[b2.length-1]||null;
    T("C1 应用远端后再推送：sex/grade 保留（f）", !!last2&&last2.fit&&last2.fit.sex==="f", last2?String(last2.fit.sex):"");
    T("C2 往返后 fit.h 未被清空", !!last2&&last2.fit&&last2.fit.h==="176", last2&&last2.fit?String(last2.fit.h):"");

    /* ============ D. 需求16：通知已处理（本机写 marks） ============ */
    tab(f,"nt");
    await waitCond(function(){return !!frame(f);},20000);
    await pumpN(4);
    var idoc=frameDoc(f), iw=frameWin(f);
    var btn=idoc.querySelector('[data-act="done"][data-gid="g_testA"]');
    T("D1 iframe 内存在「标记已处理」按钮", !!btn, "");
    if(btn)btn.click();
    var wroteA=await waitCond(function(){
      return posts(f,"markPosts").some(function(rows){return rows.some(function(r){return r.id===SID+"|ntdone|g_testA"&&r.val===true;});});
    },20000);
    T("D2 点「已处理」→ POST marks(id=<sid>|ntdone|<gid>, val=true)", wroteA, JSON.stringify(posts(f,"markPosts").slice(-1)));
    var rowA=null;posts(f,"markPosts").forEach(function(rows){rows.forEach(function(r){if(r.id===SID+"|ntdone|g_testA")rowA=r;});});
    T("D3 marks 行结构符合契约(id/seat/kind/ref/val)",
      !!(rowA&&rowA.seat===SID&&rowA.kind==="ntdone"&&rowA.ref==="g_testA"&&rowA.val===true), rowA?JSON.stringify(rowA):"");
    T("D4 父页 NT.done 已更新", !!(S.NT.done&&S.NT.done.g_testA===true), JSON.stringify(S.NT.done));
    T("D5 旧 AN_DONE 镜像已更新", !!(S.AN_DONE()&&S.AN_DONE().g_testA===true), "");

    /* ============ E. 另一设备写入 → 强制拉取后刷新 ============ */
    mk(f).setMark("ntdone","g_testB",true);
    S.resetMarksForce(); S.setMarksFresh();
    var beforeGet=mk(f).markGet;
    S.marksPull(true);
    var gotB=await waitCond(function(){return S.NT.done&&S.NT.done.g_testB===true;},20000);
    T("E1 另一设备写入 marks → 强制拉取后父页 NT.done 一致", gotB, JSON.stringify(S.NT.done));
    T("E2 强制拉取确实发出 marks GET", mk(f).markGet>beforeGet, beforeGet+"->"+mk(f).markGet);
    await pumpN(4);
    T("E3 iframe 内状态同步（已处理）", !!(iw.state&&iw.state.done&&iw.state.done.g_testB===true), "");
    var cardB=idoc.querySelector('.gcard[data-gid="g_testB"]');
    T("E4 通知卡显示已处理（completed）", !!cardB&&cardB.className.indexOf("completed")>=0, cardB?cardB.className:"");

    /* ============ F. 离线写失败 → markPend 补发 + 不被云端旧状态冲掉 ============ */
    mk(f).fail(true);
    S.noticePushDone("g_testC",true);
    var pend=await waitCond(function(){return S.markPend().some(function(p){return p.kind==="ntdone"&&p.ref==="g_testC"&&p.val===true;});},20000);
    T("F1 写入失败 → 进入 markPend 待补发", pend, JSON.stringify(S.markPend()));
    S.resetMarksForce(); S.setMarksFresh();
    S.marksPull(true);
    await pumpN(8);
    T("F2 云端旧状态（无 C）被待补发值覆盖，本地勾选不丢", S.NT.done&&S.NT.done.g_testC===true, JSON.stringify(S.NT.done));
    mk(f).fail(false);
    var resendBefore=posts(f,"markPosts").length;
    S.resetMarksForce();
    S.marksPull(true);
    var resent=await waitCond(function(){return !S.markPend().some(function(p){return p.ref==="g_testC";});},25000);
    T("F3 恢复后自动补发 markPend 并清空", resent, JSON.stringify(S.markPend()));
    T("F4 补发写入 marks(kind=ntdone,ref=g_testC,val=true)",
      posts(f,"markPosts").slice(resendBefore).some(function(rows){return rows.some(function(r){return r.id===SID+"|ntdone|g_testC"&&r.val===true;});}), "");

    /* ============ G. 回前台 / 切页 强制拉 marks ============ */
    S.setMarksFresh(); S.resetMarksForce();
    var g0=mk(f).markGet;
    /* 在 app 文档上派发：headless 里 document.hidden 可能为 true，先定义成 false 模拟“回到前台” */
    var adoc=f.contentDocument;
    try{Object.defineProperty(adoc,"hidden",{configurable:true,get:function(){return false;}});}catch(e){}
    adoc.dispatchEvent(new Event("visibilitychange"));
    var visPulled=await waitCond(function(){return mk(f).markGet>g0;},20000);
    T("G1 visibilitychange（回前台）→ 强制拉一次 marks", visPulled, "hidden="+String(adoc.hidden)+" "+g0+"->"+mk(f).markGet);
    S.setMarksFresh(); S.resetMarksForce();
    var g1=mk(f).markGet;
    tab(f,"hw");
    var tabPulled=await waitCond(function(){return mk(f).markGet>g1;},20000);
    T("G2 切页（通知→作业）→ 强制拉 marks", tabPulled, g1+"->"+mk(f).markGet);
    S.setMarksFresh(); S.resetMarksForce();
    var g2=mk(f).markGet;
    tab(f,"nt");
    var tabPulled2=await waitCond(function(){return mk(f).markGet>g2;},20000);
    T("G3 切页（作业→通知）→ 强制拉 marks", tabPulled2, g2+"->"+mk(f).markGet);

    /* ============ H. 作业完成跨端 ============ */
    tab(f,"hw");
    await pumpN(4);
    T("H1 作业列表渲染 2 条", qa(f,"#hList .item").length===2, qa(f,"#hList .item").length);
    mk(f).setMark("hw","hwA",true);
    S.resetMarksForce(); S.setMarksFresh();
    S.marksPull(true);
    var hwDone=await waitCond(function(){return qa(f,"#hList .item.done").length>=1;},20000);
    T("H2 远端 marks(kind=hw) → 作业列表显示已完成", hwDone, qa(f,"#hList .item.done").length);
    var chk=q(f,'#hList .item.done .chk');
    T("H3 已完成勾选状态渲染", !!chk&&chk.className.indexOf("on")>=0, chk?chk.className:"");
    var postsBefore=posts(f,"markPosts").length;
    var chk2=q(f,"#hList .item:not(.done) .chk");
    T("H4 存在未完成作业可勾选", !!chk2, "");
    if(chk2)chk2.click();
    var wroteHw=await waitCond(function(){
      return posts(f,"markPosts").slice(postsBefore).some(function(rows){return rows.some(function(r){return r.kind==="hw"&&r.val===true;});});
    },20000);
    T("H5 本机勾选作业 → 写 marks(kind=hw)", wroteHw, JSON.stringify(posts(f,"markPosts").slice(postsBefore)));
    collect(f);

    try{sessionStorage.removeItem("zq_pos_v1");}catch(e){}
    T("I1 全程 0 JS 报错", ALLERR.length===0, JSON.stringify(ALLERR).slice(0,400));
    T("I2 全程 0 console.error", ALLCERR.length===0, JSON.stringify(ALLCERR).slice(0,400));
    T("I3 无外部请求", ALLEXT.length===0, JSON.stringify(ALLEXT).slice(0,300));
    R.diag.counts=counters(f);
  }catch(e){
    R.steps.push({k:"脚本异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("main",R);
  await pumpN(3);
}
run();
"""


def build_harness():
    body = COMMON_JS.replace("__SRC__", "preview.html").replace("__SID__", SID)
    body += "\n" + MAIN_JS
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 sync check</title>"
            "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
            "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
    return html


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


def run_edge(url, budget=90000, timeout=420):
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
    tmp = tempfile.mkdtemp(prefix="v2sync_")
    srv = None
    try:
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(build_previews())
        open(os.path.join(tmp, "harness.html"), "w", encoding="utf-8", newline="").write(build_harness())
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
        if not data:
            print("[v2_sync_check] 未拿到测试报告")
            sys.exit(2)
        passed = 0
        for s in data.get("steps", []):
            if s["ok"]:
                passed += 1
            print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + str(s["note"])) if s["note"] else ""))
        total = len(data.get("steps", []))
        print("=" * 60)
        print("v2_sync_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
        print("=" * 60)
        sys.exit(0 if total and passed == total else 1)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
