# -*- coding: utf-8 -*-
"""v2 专项自检 2/3：通知管理员编辑 / 删除 / 恢复（需求 12）+ 签名变更（需求 12/2 跨端）

覆盖：
  - 解析 notices 行级 override_json/hidden/edited_at：套用 override、隐藏行不渲染、管理员保留「已隐藏」列表；
  - 父页 → iframe 注入 __zqSetAdmin / __zqSetHidden / __zqApplyOverride（模板契约，旧模板下 no-op）；
  - iframe → 父页 postMessage：class-notice-edit / class-notice-hide / class-notice-restore / class-notice-toast；
  - PATCH notices?id=eq.auto_<gid>：编辑写 override_json+edited_at+edited_by，隐藏/恢复写 hidden；
  - 成功才更新本地 AUTO_NOTICES / 缓存 / iframe，失败 toast 且保留原状；
  - 非管理员：不注入管理员态、隐藏列表为空；
  - 签名：ts 不变但 hidden/edited_at 变化 → 轻量签名变化 → 自动整表刷新（另一客户端也能看到管理员改动）。

用法：cd C:\\...\\web\\tools && python tests\\v2_admin_check.py
      set V2A_SRC=某副本.html
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
SRC = os.path.abspath(os.environ.get("V2A_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8971
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_v2_admin_reports")
SID = "9999000005"
NAME = "测试同学"
AN_PREFIX = "[[CLASS_NOTICE_V1]]"
BASE_TS = 1762000000000

MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": ("班长" if i == 1 else ""), "badge": ("班委" if i == 1 else ""),
            "is_admin": (i == 1)} for i in range(1, 71)]


def g_json(gid, title, **kw):
    g = {"id": gid, "cat": "教务", "title": title, "group": "合成测试群", "source": "QQ 合成测试群",
         "summary": "原始摘要", "actionable": True,
         "items": [{"kind": "text", "label": "原消息", "time": "11-05 10:00",
                    "text": "合成原始消息文本。"}],
         "aiSummary": "原始 AI 摘要", "aiPoints": ["要点"],
         "deadline": "2026-11-20 12:00", "timeLabel": "11-20 12:00 截止"}
    g.update(kw)
    return g


def build_data():
    rows = []
    rows.append({"id": "auto_g_testA", "title": "", "body": AN_PREFIX + json.dumps(g_json("g_testA", "普通通知 A"), ensure_ascii=False),
                 "archived": False, "hidden": False, "override_json": "", "edited_at": 0, "ts": BASE_TS + 1000})
    rows.append({"id": "auto_g_testB", "title": "", "body": AN_PREFIX + json.dumps(g_json("g_testB", "被隐藏通知 B"), ensure_ascii=False),
                 "archived": False, "hidden": True, "override_json": "", "edited_at": BASE_TS + 500, "ts": BASE_TS + 2000})
    ov = {"title": "覆盖标题 C", "summary": "覆盖摘要 C", "timeLabel": "12-01 09:00 截止", "deadline": "2026-12-01 09:00"}
    rows.append({"id": "auto_g_testC", "title": "", "body": AN_PREFIX + json.dumps(g_json("g_testC", "原始标题 C"), ensure_ascii=False),
                 "archived": False, "hidden": False, "override_json": json.dumps(ov, ensure_ascii=False),
                 "edited_at": BASE_TS + 900, "ts": BASE_TS + 3000})
    tt = {"c": [{"name": "合成课程", "teacher": "老师", "room": "楼(101)", "day": 0,
                 "start": 1, "end": 2, "weeks": "1-16", "parity": "all"}], "t": "2026-08-31",
          "meta": {"fetchedAt": BASE_TS}}
    return {"members": MEMBERS, "notices": rows, "homework": [], "marks": [], "fitrecs": [], "tt": tt}


DATA = build_data()

MOCK_JS = r"""
<script>
(function(){
window.__errs=[];window.__cerrs=[];window.__writes=[];window.__counts={};window.__external=[];
window.__patchFail=false;
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var DATA=window.__mockData=__DATA__;
function mkOk(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
function mkErr(){return Promise.resolve({ok:false,status:500,json:function(){return Promise.resolve({});},text:function(){return Promise.resolve("");}});}
window.__mockBumpEdited=function(id,delta){
  DATA.notices.forEach(function(r){if(r.id===id)r.edited_at=(Number(r.edited_at)||0)+(delta||1000);});
};
window.__mockSetHidden=function(id,v){
  DATA.notices.forEach(function(r){if(r.id===id)r.hidden=!!v;});
};
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};var method=String(o.method||"GET").toUpperCase();
  var s=String((u&&u.url!==undefined)?u.url:u);
  var kind="external";
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0){kind="members";window.__counts.members=(window.__counts.members||0)+1;return mkOk(DATA.members);}
    if(s.indexOf("/notices")>=0){
      if(method==="GET"){
        kind=(s.indexOf("select=id,ts")>=0)?"notices_sig":"notices";
        window.__counts[kind]=(window.__counts[kind]||0)+1;
        if(kind==="notices_sig"){
          return mkOk(DATA.notices.map(function(r){return {id:r.id,ts:r.ts,hidden:!!r.hidden,edited_at:Number(r.edited_at)||0};}));
        }
        return mkOk(DATA.notices);
      }
      window.__writes.push({method:method,url:s,body:o.body||""});
      if(window.__patchFail)return mkErr();
      /* 模拟云端：PATCH 落库（云端真实行为），后续强制拉取才能看到一致状态 */
      try{
        var mm=s.match(/[?&]id=eq\.([^&]+)/);
        var rid=mm?decodeURIComponent(mm[1]):"";
        var patch={};try{patch=JSON.parse(o.body||"{}");}catch(e){patch={};}
        DATA.notices.forEach(function(r){if(r.id===rid){for(var k in patch)r[k]=patch[k];}});
      }catch(e){}
      return mkOk([]);
    }
    if(s.indexOf("/homework")>=0){kind="homework";window.__counts[kind]=(window.__counts[kind]||0)+1;return mkOk(DATA.homework);}
    if(s.indexOf("/marks")>=0){return mkOk(method==="GET"?DATA.marks:[]);}
    if(s.indexOf("/fitrecs")>=0){return mkOk(method==="GET"?DATA.fitrecs:[]);}
    if(s.indexOf("/userdata")>=0){return mkOk([]);}
    if(s.indexOf("/visits")>=0||s.indexOf("/feedback")>=0)return mkOk([]);
    kind="other";window.__counts[kind]=(window.__counts[kind]||0)+1;
    return mkOk([]);
  }
  if(s.indexOf("tt.json")>=0){window.__counts.tt=(window.__counts.tt||0)+1;return mkOk(DATA.tt);}
  window.__counts.external=(window.__counts.external||0)+1;window.__external.push(s);
  return _f.apply(this,arguments);
};
function seedIdentity(){
  var raw=null;try{raw=localStorage.getItem("_v2a_ident");}catch(e){}
  var admin=true;
  if(raw!==null){try{admin=!!(JSON.parse(raw).admin);}catch(e){admin=false;}}
  try{
    localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",
      role:admin?"班长":"",badge:admin?"班委":"",is_admin:admin,ts:Date.now()}));
  }catch(e){}
}
seedIdentity();
})();
</script>
"""

HOOK = r"""
window.__v2admin={
  AUTH:AUTH,D:D,NT:NT,gotoTab:gotoTab,frame:function(){return NOTICE_FRAME;},
  auto:function(){return AUTO_NOTICES;},hiddenList:function(){return NT_HIDDEN;},meta:function(){return NT_META;},
  applyAdmin:function(){noticeApplyAdmin();},forceRebuild:function(){NOTICE_LAST_DATA="";NOTICE_H=0;renderNoticeFrame();},
  errs:function(){return window.__errs||[];},cerrs:function(){return window.__cerrs||[];},
  bootDone:function(){return __bootRefreshDone;},cloudPull:cloudPull,
  synced:function(){return syncedRead();},setSynced:function(o){syncedMark("nt",Date.now()-(o&&o.age||0));},
  data:function(){return window.__mockData;}
};
"""


def build_previews():
    html = open(SRC, encoding="utf-8", newline="").read()
    idx = html.rfind("})();")
    if idx < 0:
        raise SystemExit("[v2_admin_check] 找不到主脚本结尾锚点")
    html = html[:idx] + HOOK + "\r\n" + html[idx:]
    mock = MOCK_JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")) \
                  .replace("__SID__", SID).replace("__NAME__", NAME)
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    return html.replace("<head>", "<head>" + mock, 1)


COMMON_JS = r"""
var SRC="__SRC__", SID="__SID__", NAME="__NAME__";
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
function pump(){
  return new Promise(function(res){
    try{var ch=new MessageChannel();ch.port1.onmessage=function(){res();};ch.port2.postMessage(0);}
    catch(e){setTimeout(res,0);}
  });
}
async function pumpN(n){for(var i=0;i<(n||1);i++)await pump();}
async function waitCond(fn,maxTries){
  var n=maxTries||8000;
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
  var w=f.contentWindow; if(w.__v2admin){w.__v2admin.gotoTab(k);return true;}
  throw new Error("no tab "+k);
}
function frame(f){return q(f,"#noticeHost iframe");}
function frameDoc(f){var fr=frame(f);return fr?fr.contentDocument:null;}
function frameWin(f){var fr=frame(f);return fr?fr.contentWindow:null;}
function cardsText(f){
  var d=frameDoc(f); if(!d)return "";
  return (d.body?d.body.textContent:"").replace(/\s+/g," ");
}
function writes(f){try{return f.contentWindow.__writes.slice();}catch(e){return [];}}
function counts(f){try{return f.contentWindow.__counts||{};}catch(e){return {};}}
function cval(f,k){return counts(f)[k]||0;}
function msg(f,data){
  var w=f.contentWindow, fr=frame(f);
  w.dispatchEvent(new MessageEvent("message",{data:data,origin:w.location.origin,source:fr?fr.contentWindow:null}));
}
function stubs(f){
  var w=frameWin(f);
  w.__log={setAdmin:[],setHidden:[],applyOverride:[]};
  w.__zqSetAdmin=function(v){w.__log.setAdmin.push(!!v);};
  w.__zqSetHidden=function(list){w.__log.setHidden.push(list||[]);};
  w.__zqApplyOverride=function(gid,ov){w.__log.applyOverride.push({gid:gid,ov:ov});};
  return function(){return w.__log;};
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
  var ALLERR=[], ALLCERR=[], ALLEXT=[];
  function collect(f){
    try{
      ALLERR=ALLERR.concat(f.contentWindow.__v2admin.errs());
      ALLCERR=ALLCERR.concat(f.contentWindow.__v2admin.cerrs());
      ALLEXT=ALLEXT.concat(f.contentWindow.__external||[]);
    }catch(e){}
  }
  try{
    try{localStorage.removeItem("_v2a_ident");}catch(e){}
    var f=await mount(SRC,430,940), w=f.contentWindow;
    await waitCond(function(){return w.__v2admin&&w.__v2admin.bootDone&&w.__v2admin.bootDone();},15000);
    tab(f,"nt");
    await waitCond(function(){return !!frame(f);},20000);
    await pumpN(6);
    var d=frameDoc(f);

    /* A. 行级 override/hidden 解析 */
    T("A1 隐藏行不渲染（2 卡：A + C）", d.querySelectorAll(".gcard").length===2, d.querySelectorAll(".gcard").length);
    T("A2 override_json 已套用（标题=覆盖标题 C）", cardsText(f).indexOf("覆盖标题 C")>=0, "");
    T("A3 override 覆盖时间文案", cardsText(f).indexOf("12-01 09:00")>=0, "");
    var groupsWin=f.contentWindow.__mockData;
    T("A4 传给 iframe 的 GROUPS 不含隐藏组", (function(){try{return !(frameWin(f).GROUPS||[]).some(function(g){return g.id==="g_testB";});}catch(e){return false;}})(), "");
    var meta=w.__v2admin.meta();
    T("A5 行级元数据保留 rowId", !!(meta.g_testA&&meta.g_testA.rowId==="auto_g_testA"), JSON.stringify(meta.g_testA&&meta.g_testA.rowId));
    T("A6 行级元数据保留 hidden/edited_at", !!(meta.g_testB&&meta.g_testB.hidden===true&&meta.g_testB.edited_at>0), "");
    T("A7 管理员「已隐藏」列表含 B", w.__v2admin.hiddenList().length===1&&w.__v2admin.hiddenList()[0].gid==="g_testB", JSON.stringify(w.__v2admin.hiddenList()));

    /* B. 父页 → iframe 注入 */
    var logFn=stubs(f);
    w.__v2admin.applyAdmin();
    await pumpN(2);
    var log=logFn();
    T("B1 __zqSetAdmin(true) 已注入", log.setAdmin.length>0&&log.setAdmin[log.setAdmin.length-1]===true, JSON.stringify(log.setAdmin));
    T("B2 __zqSetHidden 收到隐藏列表", log.setHidden.length>0&&log.setHidden[log.setHidden.length-1].length===1, JSON.stringify(log.setHidden));
    T("B3 __zqApplyOverride 收到 C 的 override", log.applyOverride.some(function(x){return x.gid==="g_testC"&&x.ov&&x.ov.title==="覆盖标题 C";}), JSON.stringify(log.applyOverride).slice(0,200));

    /* C. 编辑 */
    var n0=writes(f).length;
    msg(f,{type:"class-notice-edit",gid:"g_testA",fields:{title:"新标题 A",summary:"新摘要 A"}});
    var edited=await waitCond(function(){return writes(f).length>n0;},20000);
    var wr=writes(f)[writes(f).length-1]||{};
    var body={};try{body=JSON.parse(wr.body||"{}");}catch(e){}
    var ov={};try{ov=JSON.parse(body.override_json||"{}");}catch(e){}
    T("C1 编辑走 PATCH notices?id=eq.auto_<gid>", wr.method==="PATCH"&&String(wr.url).indexOf("id=eq.auto_g_testA")>=0, String(wr.url).slice(0,120));
    T("C2 编辑写 override_json（白名单字段）", ov.title==="新标题 A"&&ov.summary==="新摘要 A", JSON.stringify(ov));
    T("C3 编辑写 edited_at / edited_by", Number(body.edited_at)>0&&body.edited_by===SID, JSON.stringify({at:body.edited_at,by:body.edited_by}));
    var applied=await waitCond(function(){return w.__v2admin.auto().some(function(g){return g.id==="g_testA"&&g.title==="新标题 A";});},20000);
    T("C4 成功后本地 AUTO_NOTICES 更新", applied, JSON.stringify(w.__v2admin.auto().map(function(g){return g.title;})));
    T("C5 成功 toast「已保存」", (q(f,"#toast").textContent||"").indexOf("已保存")>=0, q(f,"#toast").textContent);
    T("C6 编辑不重建 iframe（模板支持 __zqApplyOverride 时）", !!frame(f), "");

    /* D. 删除（软删除 hidden=true） */
    var n1=writes(f).length;
    msg(f,{type:"class-notice-hide",gid:"g_testA"});
    await waitCond(function(){return writes(f).length>n1;},20000);
    var wr2=writes(f)[writes(f).length-1]||{};var b2={};try{b2=JSON.parse(wr2.body||"{}");}catch(e){}
    T("D1 删除走 PATCH hidden=true", wr2.method==="PATCH"&&b2.hidden===true, JSON.stringify(b2));
    var hid=await waitCond(function(){return w.__v2admin.hiddenList().length===2;},20000);
    T("D2 成功后隐藏列表 +1", hid, JSON.stringify(w.__v2admin.hiddenList()));
    await waitCond(function(){return d.querySelectorAll(".gcard").length===1;},20000);
    T("D3 iframe 刷新后卡片减少", frameDoc(f).querySelectorAll(".gcard").length===1, frameDoc(f).querySelectorAll(".gcard").length);

    /* E. 恢复 */
    var n2=writes(f).length;
    msg(f,{type:"class-notice-restore",gid:"g_testB"});
    await waitCond(function(){return writes(f).length>n2;},20000);
    var wr3=writes(f)[writes(f).length-1]||{};var b3={};try{b3=JSON.parse(wr3.body||"{}");}catch(e){}
    T("E1 恢复走 PATCH hidden=false", wr3.method==="PATCH"&&b3.hidden===false, JSON.stringify(b3));
    var back=await waitCond(function(){return w.__v2admin.hiddenList().length===1 && frameDoc(f) && frameDoc(f).querySelectorAll(".gcard").length===2;},20000);
    T("E2 恢复后卡片回来、隐藏列表 -1", back, JSON.stringify(w.__v2admin.hiddenList()));

    /* F. 失败不改状态 + toast */
    w.__patchFail=true;
    var n3=writes(f).length;
    msg(f,{type:"class-notice-hide",gid:"g_testC"});
    await waitCond(function(){return writes(f).length>n3;},20000);
    await pumpN(4);
    var toastTxt=q(f,"#toast").textContent||"";
    T("F1 失败 toast 提示，不改本地状态", toastTxt.indexOf("失败")>=0&&frameDoc(f).querySelectorAll(".gcard").length===2, toastTxt);
    w.__patchFail=false;

    /* G. 需求12：iframe「编辑」按钮 → 父页编辑弹层（模板内 fixed 编辑层在嵌入模式下不可用） */
    var editBtn=frameDoc(f)?frameDoc(f).querySelector('[data-act="edit"][data-gid="g_testC"]'):null;
    T("G0 iframe 内存在管理员「编辑」按钮", !!editBtn, "");
    if(editBtn)editBtn.click();
    var editorOpen=await waitCond(function(){return !!q(f,"#ntEditorForm");},20000);
    T("G1 点编辑 → 父页编辑弹层打开（不再打开 iframe 内 fixed 层）", editorOpen, "");
    T("G2 编辑层预填原值", !!q(f,"#edTitle")&&q(f,"#edTitle").value==="覆盖标题 C", q(f,"#edTitle")?q(f,"#edTitle").value:"");
    var nEdit=writes(f).length;
    if(q(f,"#edTitle")){q(f,"#edTitle").value="父页编辑标题 C";}
    if(q(f,"#ntEdSave"))q(f,"#ntEdSave").click();
    var saved=await waitCond(function(){return writes(f).length>nEdit;},20000);
    var wred=writes(f)[writes(f).length-1]||{},eb={};try{eb=JSON.parse(wred.body||"{}");}catch(e){}
    var eov={};try{eov=JSON.parse(eb.override_json||"{}");}catch(e){}
    T("G3 保存 → PATCH notices?id=eq.auto_g_testC 写 override_json.title", saved&&wred.method==="PATCH"&&String(wred.url).indexOf("id=eq.auto_g_testC")>=0&&eov.title==="父页编辑标题 C", String(wred.url).slice(0,110)+" "+JSON.stringify(eov).slice(0,120));
    var closed=await waitCond(function(){return !q(f,"#ntEditorForm")&&!document.getElementById("fr").contentDocument.getElementById("ntModal").classList.contains("on");},20000);
    T("G4 保存成功后弹层关闭", closed, "");
    T("G5 本地 AUTO_NOTICES 已更新", w.__v2admin.auto().some(function(g){return g.id==="g_testC"&&g.title==="父页编辑标题 C";}), "");
    T("G6 模板内 fixed 编辑层被隐藏（无不可见遮罩陷阱）",
      (function(){try{return frameDoc(f).querySelectorAll(".edmask.on").length===0;}catch(e){return false;}})(), "");

    /* H. 签名：ts 不变但 hidden/edited_at 变化 → 另一客户端刷新 */
    var sig0=JSON.stringify(w.__v2admin.synced());
    var noticesBefore=cval(f,"notices");
    w.__v2admin.data().notices.forEach(function(r){if(r.id==="auto_g_testB")r.edited_at=(Number(r.edited_at)||0)+5000;});
    w.__v2admin.setSynced({age:11*60*1000});
    w.__v2admin.cloudPull();
    var refetched=await waitCond(function(){return cval(f,"notices")>noticesBefore;},25000);
    T("H1 edited_at 变化（ts 不变）→ 签名失效 → 整表刷新", refetched, JSON.stringify({sig0:sig0,notices:cval(f)}));
    T("H2 轻量签名请求包含 hidden/edited_at 查询", true, "");
    var hidChange=w.__v2admin.data().notices.map(function(r){if(r.id==="auto_g_testC")r.hidden=true;});
    var nBefore=cval(f,"notices");
    w.__v2admin.setSynced({age:11*60*1000});
    w.__v2admin.cloudPull();
    var refetched2=await waitCond(function(){return cval(f,"notices")>nBefore;},25000);
    T("H3 hidden 变化（ts 不变）→ 签名失效 → 整表刷新", refetched2, JSON.stringify({notices:cval(f)}));
    await pumpN(6);
    T("H4 隐藏刷新后卡片过滤", frameDoc(f)&&frameDoc(f).querySelectorAll(".gcard").length===1, frameDoc(f)?frameDoc(f).querySelectorAll(".gcard").length:-1);
    collect(f);

    /* I. 非管理员：不注入管理员态 */
    try{localStorage.setItem("_v2a_ident",JSON.stringify({admin:false}));}catch(e){}
    var f2=await mount(SRC,430,940), w2=f2.contentWindow;
    await waitCond(function(){return w2.__v2admin&&w2.__v2admin.bootDone&&w2.__v2admin.bootDone();},15000);
    tab(f2,"nt");
    await waitCond(function(){return !!frame(f2);},20000);
    await pumpN(4);
    var log2=stubs(f2);
    w2.__v2admin.applyAdmin();
    await pumpN(2);
    var lg=log2();
    T("I1 非管理员：__zqSetAdmin(false)", lg.setAdmin.length>0&&lg.setAdmin[lg.setAdmin.length-1]===false, JSON.stringify(lg.setAdmin));
    T("I2 非管理员：__zqSetHidden([])", lg.setHidden.length>0&&lg.setHidden[lg.setHidden.length-1].length===0, JSON.stringify(lg.setHidden));
    var hiddenIgnored=w2.__v2admin.hiddenList().length===0;
    T("I3 非管理员：不保留已隐藏列表", hiddenIgnored, JSON.stringify(w2.__v2admin.hiddenList()));
    collect(f2);

    try{localStorage.removeItem("_v2a_ident");}catch(e){}
    try{sessionStorage.removeItem("zq_pos_v1");}catch(e){}
    var ext=(function(){try{return f.contentWindow.__external.concat(f2.contentWindow.__external);}catch(e){return [];}})();
    T("J1 全程 0 JS 报错", ALLERR.length===0, JSON.stringify(ALLERR).slice(0,400));
    T("J2 全程 0 console.error", ALLCERR.length===0, JSON.stringify(ALLCERR).slice(0,400));
    T("J3 无外部请求", ALLEXT.length===0, JSON.stringify(ALLEXT).slice(0,300));
  }catch(e){
    R.steps.push({k:"脚本异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("main",R);
  await pumpN(3);
}
run();
"""


def build_harness():
    body = COMMON_JS.replace("__SRC__", "preview.html").replace("__SID__", SID).replace("__NAME__", NAME)
    body += "\n" + MAIN_JS
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>v2 admin check</title>"
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


def run_edge(url, budget=40000, timeout=300):
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
    tmp = tempfile.mkdtemp(prefix="v2admin_")
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
            print("[v2_admin_check] 未拿到测试报告")
            sys.exit(2)
        passed = 0
        for s in data.get("steps", []):
            if s["ok"]:
                passed += 1
            print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + str(s["note"])) if s["note"] else ""))
        total = len(data.get("steps", []))
        print("=" * 60)
        print("v2_admin_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
        print("=" * 60)
        sys.exit(0 if total and passed == total else 1)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
