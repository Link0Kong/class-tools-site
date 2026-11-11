# -*- coding: utf-8 -*-
"""课表「登录教务」专项验收（网页）：登录弹层 / RPC 入队 + 轮询 / 个人课表写入与优先级 /
错误码提示 / 超时停止 / 清除我的课表 / UD v6 同步 / 不回归。

契约：C:\\Users\\Ko_Li\\.openclaw\\workspace\\_diag_task\\CONTRACT.md §1/§2/§4。
做法（复用 reset_check.py / v2_diag_v2_check.py 的注入 / iframe / headless Edge 方式）：
- 复制 tools/index.html 到 tests/_ttlogin_preview.html，注入假身份 + fetch mock
  （rpc/tt_login_enqueue、rpc/tt_login_status、userdata 全 mock，绝不碰真实云端）；
- 场景：success（成功写入 ttLocal + UD 推送）、offline（agent_offline）、failed（教务失败 + 脱敏）、
  timeout（≤120s 语义，测试缩短配置）、clear（清除个人课表回退公共）、layout/截图。

用法（cwd 任意）：
    python web/tools/tests/v2_tt_login_check.py
    环境变量 TTLOGIN_SRC 可指定副本；端口 TTLOGIN_PORT（默认 8943）。
退出码 0 = 全绿；截图存 tools/tests/_shots_tt_login/。
"""
import functools
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
SRC = os.path.abspath(os.environ.get("TTLOGIN_SRC") or os.path.join(ROOT, "index.html"))
SHOTS = os.path.join(HERE, "_shots_tt_login")
REPORT_DIR = os.path.join(HERE, "_ttlogin_reports")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = int(os.environ.get("TTLOGIN_PORT") or 8943)
BASE = "http://127.0.0.1:%d/" % PORT

SID = "9999000005"
NAME = "测试同学"
TOKEN = "test-token-ttlogin"
PWD = "TestPwd#2026"
NOW = int(time.time() * 1000)

MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": "", "badge": "", "is_admin": False} for i in range(1, 71)]

PUBLIC_TT = {"c": [{"name": "公共课A", "teacher": "公共老师", "room": "公教101", "day": 1,
                    "start": 3, "end": 4, "weeks": "1-16", "parity": "all"}],
             "t": "2026-09-07", "meta": {"source": "jwxt", "fetchedAt": NOW - 3600000, "count": 1}}

MINE_C = [
    {"name": "个人课A", "teacher": "张老师", "room": "体教201", "day": 0,
     "start": 1, "end": 2, "weeks": "1-16", "parity": "all"},
    {"name": "个人课B", "teacher": "李老师", "room": "体教302", "day": 2,
     "start": 5, "end": 6, "weeks": "1-16", "parity": "all"},
]
MINE_RESULT = {"c": MINE_C, "t": "2026-09-17",
               "meta": {"source": "jwxt", "fetchedAt": NOW - 1000}}

# UD v6 基线（与页面默认 sections 一致 → boot 不产生多余推送；登录后只推 tt 变更）
UD_BASE = {
    "v": 6,
    "at": {"homeTools": 0, "fit": 0, "draw": 0, "group": 0, "roster": 0, "hide": 0,
           "tt": 0, "prefs": 0, "nick": 0, "power": 0, "water": 0},
    "homeTools": ["draw", "hw", "nt", "tt"],
    "fit": {"sex": "m", "grade": "12", "h": "", "w": "", "vc": "", "r50": "", "sit": "",
            "jump": "", "pull": "", "durM": "", "durS": ""},
    "draw": {"start": 1, "end": 70, "count": 10, "dup": False, "excl": "", "sort": "draw"},
    "group": {"source": "prev", "mode": "groups", "n": 4, "shuffle": False, "sel": []},
    "roster": {"rosterSel": [], "rollSel": [], "rollSt": {}, "rollNames": ""},
    "hide": {"hwHide": {}, "ntHide": {}},
    "tt": {"ttView": "week", "ttUseMine": False, "ttLocal": None, "termStart": "2026-09-07"},
    "prefs": {"hwRemind": {}, "ntSub": False, "ntSubAt": 0},
    "nick": "",
    "power": {"sel": "", "at": 0, "low": 30},
    "water": {"rooms": {}},
}

STORE_SEED = {"homeTools": ["draw", "hw", "nt", "tt"], "termStart": "2026-09-07", "ttView": "week"}

PREVIEW = "_ttlogin_preview.html"
HARNESS_SUCCESS = "_ttlogin_harness_success.html"
HARNESS_OFFLINE = "_ttlogin_harness_offline.html"
HARNESS_FAILED = "_ttlogin_harness_failed.html"
HARNESS_TIMEOUT = "_ttlogin_harness_timeout.html"
HARNESS_CLEAR = "_ttlogin_harness_clear.html"
HARNESS_LAYOUT = "_ttlogin_harness_layout.html"
HARNESS_SHOT = "_ttlogin_harness_shot.html"

INJECT = """<script>
(function(){
window.__errs=[];window.__cerrs=[];window.__external=[];window.__rpcLog=[];window.__udPosts=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));_ce.apply(console,arguments);};
var MODE=String(location.hash||"").replace("#","");
var POLL=0;
function resp(v){return Promise.resolve({ok:true,status:200,
  headers:{get:function(){return null;}},
  json:function(){return Promise.resolve(v);},text:function(){return Promise.resolve("");}});}
var MEMBERS=__MEMBERS__;
var PUBLIC_TT=__PUBLIC_TT__;
var MINE=__MINE_RESULT__;
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};
  var s=String((u&&u.url!==undefined)?u.url:u);
  var m=String(o.method||"GET").toUpperCase();
  var body=String(o.body||"");
  function log(extra){
    var rec={method:m,url:s,headers:o.headers||{},body:body};
    if(extra)for(var k in extra)rec[k]=extra[k];
    window.__rpcLog.push(rec);
  }
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/tt_login_enqueue")>=0){
      log();
      var p={};try{p=JSON.parse(body);}catch(e){}
      if(MODE==="offline")return resp({ok:false,reason:"agent_offline"});
      if(!p.p_pwd)return resp({ok:false,reason:"pwd"});
      return resp({ok:true,job_id:"job-test-1"});
    }
    if(s.indexOf("rpc/tt_login_status")>=0){
      POLL++;window.__pollCount=POLL;log({poll:POLL});
      if(MODE==="success"){
        if(POLL<=1)return resp({ok:true,status:"pending",finished:0,error:"",result:null});
        return resp({ok:true,status:"done",finished:Date.now(),error:"",result:MINE});
      }
      if(MODE==="failed"){
        if(POLL<=1)return resp({ok:true,status:"claimed",finished:0,error:"",result:null});
        return resp({ok:true,status:"failed",finished:Date.now(),
          error:"教务认证失败：密码错误 10.1.2.3 C:\\\\jwxt\\\\secret.log https://auth.example/x?token=abc",result:null});
      }
      return resp({ok:true,status:"pending",finished:0,error:"",result:null});
    }
    if(s.indexOf("rpc/class_members")>=0)return resp(MEMBERS);
    if(s.indexOf("rpc/diag_agent_info")>=0)return resp({ok:true,online:false,seen_at:0,host:"",version:""});
    if(s.indexOf("diag_analysis?select=")>=0)return resp([]);
    if(s.indexOf("repair_tasks?select=")>=0)return resp([]);
    if(s.indexOf("client_diag")>=0)return resp([]);
    if(s.indexOf("/userdata")>=0){
      if(m==="POST"){try{window.__udPosts.push(JSON.parse(body));}catch(e){}return resp([{id:"__SID__"}]);}
      return resp([]);
    }
    if(s.indexOf("/notices")>=0)return resp([]);
    if(s.indexOf("/homework")>=0)return resp([]);
    if(s.indexOf("/marks")>=0)return resp([]);
    if(s.indexOf("/fitrecs")>=0)return resp([]);
    if(s.indexOf("site_assets")>=0)return resp([]);
    return resp([]);
  }
  if(s.indexOf("tt.json")>=0)return resp(PUBLIC_TT);
  window.__external.push(s);
  return _f.apply(this,arguments);
};
try{
  localStorage.setItem("zq_class_identity",JSON.stringify({token:"__TOKEN__",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));
  localStorage.setItem("zq_tools_v2___SID__",JSON.stringify(__STORE__));
  localStorage.setItem("zq_udcache___SID__",JSON.stringify(__UD__));
  localStorage.setItem("zq_udat___SID__",String(Date.now()));
  var SEED_LOCAL=__SEED_LOCAL__;
  if(SEED_LOCAL.length){
    var st=JSON.parse(localStorage.getItem("zq_tools_v2___SID__"));
    st.ttLocal={c:SEED_LOCAL,t:"2026-09-17",at:Date.now()};
    localStorage.setItem("zq_tools_v2___SID__",JSON.stringify(st));
  }
}catch(e){}
})();
</script>"""


def build_previews():
    html = open(SRC, encoding="utf-8", newline="").read()
    for name, seed_local in ((PREVIEW, []),):
        fill = (INJECT.replace("__MEMBERS__", json.dumps(MEMBERS, ensure_ascii=False))
                       .replace("__PUBLIC_TT__", json.dumps(PUBLIC_TT, ensure_ascii=False))
                       .replace("__MINE_RESULT__", json.dumps(MINE_RESULT, ensure_ascii=False))
                       .replace("__STORE__", json.dumps(STORE_SEED, ensure_ascii=False))
                       .replace("__UD__", json.dumps(UD_BASE, ensure_ascii=False))
                       .replace("__SEED_LOCAL__", json.dumps(seed_local, ensure_ascii=False))
                       .replace("__TOKEN__", TOKEN).replace("__SID__", SID).replace("__NAME__", NAME))
        out = html.replace("<head>", "<head>" + fill, 1)
        open(os.path.join(HERE, name), "w", encoding="utf-8", newline="").write(out)


COMMON_JS = r"""
var SRC="__SRC__", SID="__SID__", TOKEN="__TOKEN__", PWD="__PWD__", STORE="zq_tools_v2_"+SID;
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
function waitFor(fn,ms){return new Promise(function(res,rej){var t0=Date.now();
  (function loop(){var v=false;try{v=!!fn();}catch(e){v=false;}
    if(v)return res(true);
    if(Date.now()-t0>(ms||6000))return rej(new Error("waitFor timeout"));
    setTimeout(loop,25);})();});}
function mount(src,w,h){
  return new Promise(function(res,rej){
    var old=document.getElementById("fr"); if(old&&old.parentNode)old.parentNode.removeChild(old);
    var f=document.createElement("iframe"); f.id="fr"; f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block";
    f.src=src;
    var done=false;
    f.onload=function(){ if(done)return; done=true; setTimeout(function(){res(f);},120); };
    f.onerror=function(){ if(done)return; done=true; rej(new Error("iframe load failed")); };
    document.body.appendChild(f);
    setTimeout(function(){ if(!done){done=true;res(f);} },10000);
  });
}
function q(f,s){return f.contentDocument.querySelector(s);}
function qa(f,s){return Array.prototype.slice.call(f.contentDocument.querySelectorAll(s));}
function click(f,s){var e=q(f,s); if(!e)throw new Error("missing element: "+s); e.click(); return e;}
function txt(f,s){var e=q(f,s); return e?e.textContent:"";}
function allText(f,s){return qa(f,s).map(function(e){return e.textContent||"";});}
function loadState(f){try{return JSON.parse(f.contentWindow.localStorage.getItem(STORE)||"null")||{};}catch(e){return {};}}
function statusReq(f){return (f.contentWindow.__rpcLog||[]).filter(function(x){return x.url.indexOf("rpc/tt_login_status")>=0;});}
function enqReq(f){return (f.contentWindow.__rpcLog||[]).filter(function(x){return x.url.indexOf("rpc/tt_login_enqueue")>=0;});}
function storeHas(f,needle){
  try{for(var i=0;i<f.contentWindow.localStorage.length;i++){var k=f.contentWindow.localStorage.key(i);var v=f.contentWindow.localStorage.getItem(k);
    if(String(k).indexOf(needle)>=0||String(v).indexOf(needle)>=0)return true;}}catch(e){}
  return false;
}
function ttNames(f){return allText(f,"#tList .ttl").map(function(x){return x.trim();});}
function openTT(f){f.contentWindow.__diag.gotoTab("tt");}
function submitLogin(f){
  click(f,"#tLogin");
  q(f,"#ttLoginPwd").value=PWD;
  click(f,"#ttLoginGo");
}
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

SUCCESS_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC+"#success",430,1000), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__ttLogin;},9000);
    openTT(f);
    await waitFor(function(){return d.querySelector("#s-tt").classList.contains("on")&&ttNames(f).length>=1;},9000);
    T("A1 初始课表为公共课表（无个人课表）", w.__ttLogin.state().src==="pub"&&ttNames(f).indexOf("公共课A")>=0, w.__ttLogin.state().src+"|"+ttNames(f).join(","));
    click(f,"#tLogin");
    await waitFor(function(){return q(f,"#ttLoginPanel").style.display!=="none";},4000);
    T("A2 登录弹层打开", q(f,"#ttLoginPanel").style.display!=="none", q(f,"#ttLoginPanel").style.display);
    T("A3 学号默认当前身份 sid", q(f,"#ttLoginSid").value===SID, q(f,"#ttLoginSid").value);
    T("A4 密码输入框 type=password", q(f,"#ttLoginPwd").getAttribute("type")==="password", q(f,"#ttLoginPwd").getAttribute("type"));
    T("A5 有「清除我的课表」入口", !!q(f,"#ttLoginClear")&&/清除我的课表/.test(txt(f,"#ttLoginClear")), txt(f,"#ttLoginClear"));
    w.__ttLogin.cfg(250,8000);
    q(f,"#ttLoginPwd").value=PWD;
    click(f,"#ttLoginGo");
    await waitFor(function(){return (w.__rpcLog||[]).some(function(x){return x.url.indexOf("rpc/tt_login_enqueue")>=0;});},4000);
    var enq=enqReq(f)[0]||{};
    var b={};try{b=JSON.parse(enq.body||"{}");}catch(e){}
    T("A6 POST rpc/tt_login_enqueue 带 p_pwd/p_platform=web", b.p_pwd===PWD&&b.p_platform==="web", JSON.stringify(b).slice(0,80));
    T("A7 RPC 带 X-Device-Id 班级 token", String((enq.headers||{})["X-Device-Id"]||"")===TOKEN, String((enq.headers||{})["X-Device-Id"]||""));
    T("A8 提交后密码输入框立即清空", q(f,"#ttLoginPwd").value==="", q(f,"#ttLoginPwd").value);
    T("A9 密码不落 localStorage", !storeHas(f,PWD), "");
    await waitFor(function(){return w.__ttLogin.state().job!=="";},4000);
    T("A10 轮询已启动（job 记录 + timer）", w.__ttLogin.state().job!==""&&w.__ttLogin.state().timer===true, JSON.stringify(w.__ttLogin.state()));
    await waitFor(function(){return w.__ttLogin.state().local===2&&w.__ttLogin.state().job==="";},9000);
    await sleep(300);
    T("A11 done 后写入本机 D.d.ttLocal（2 门）", loadState(f).ttLocal&&loadState(f).ttLocal.c.length===2, JSON.stringify(loadState(f).ttLocal).slice(0,120));
    T("A12 ttLocal 学期起始来自 result.t", loadState(f).ttLocal&&loadState(f).ttLocal.t==="2026-09-17", loadState(f).ttLocal&&loadState(f).ttLocal.t);
    T("A13 立即重渲染，个人课表优先于公共课表", w.__ttLogin.state().src==="mine"&&ttNames(f).indexOf("个人课A")>=0&&ttNames(f).indexOf("公共课A")<0,
      w.__ttLogin.state().src+"|"+ttNames(f).join(","));
    T("A14 课表来源标注「个人课表」", /个人课表/.test(txt(f,"#tSyncSt")), txt(f,"#tSyncSt"));
    T("A15 弹层显示「已同步 2 门」", /已同步 2 门/.test(txt(f,"#ttLoginSt")), txt(f,"#ttLoginSt"));
    await waitFor(function(){return q(f,"#ttLoginPanel").style.display==="none";},4000);
    T("A16 成功后自动关闭弹层", q(f,"#ttLoginPanel").style.display==="none", q(f,"#ttLoginPanel").style.display);
    /* 轮询停止：done 后不再发 rpc/tt_login_status */
    var n1=statusReq(f).length;
    await sleep(1200);
    var n2=statusReq(f).length;
    T("A17 done 后轮询停止", n1===n2, n1+" -> "+n2);
    /* UD v6 同步：tt section 推送 blob.tt.ttLocal */
    var posts=w.__udPosts||[];
    var last=posts.length?posts[posts.length-1]:null;
    var blob=null;
    try{blob=last&&last[0]?JSON.parse(last[0].blob):null;}catch(e){}
    T("A18 触发 UD v6 同步（POST userdata）", posts.length>=1, posts.length);
    T("A19 云端 blob.tt.ttLocal 写入 2 门且 at>0", !!blob&&blob.tt&&blob.tt.ttLocal&&blob.tt.ttLocal.c&&blob.tt.ttLocal.c.length===2&&Number(blob.at&&blob.at.tt)>0,
      blob?JSON.stringify(blob.tt||{}).slice(0,140):"no blob");
    /* 不回归：周切换 / 导入入口 / 导出按钮 */
    var wk0=txt(f,"#tWeekLbl");
    click(f,"#tNextW"); await sleep(120);
    T("A20 下一周按钮仍可用（周次变化）", txt(f,"#tWeekLbl")!==wk0, wk0+" -> "+txt(f,"#tWeekLbl"));
    click(f,"#tImport"); await sleep(120);
    T("A21 导入弹层仍可用", q(f,"#ttImportPanel").style.display!=="none", q(f,"#ttImportPanel").style.display);
    click(f,"#ttImportClose"); await sleep(80);
    T("A22 导出/详情入口仍存在", !!q(f,"#tImg")&&!!q(f,"#ttCPanel"), "");
    var de=d.documentElement;
    T("A23 430 宽无横向溢出", de.scrollWidth<=de.clientWidth+1, de.scrollWidth+"/"+de.clientWidth);
    T("A24 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]).slice(0,300));
    T("A25 0 console.error", (w.__cerrs||[]).length===0, JSON.stringify(w.__cerrs||[]).slice(0,300));
    T("A26 无外部请求", (w.__external||[]).length===0, JSON.stringify(w.__external||[]).slice(0,200));
    R.errors={win:(w.__errs||[]).slice(),cerr:(w.__cerrs||[]).slice()};
    R.state=w.__ttLogin.state();
    report("success",R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("success",R);
  }
}
run();
"""

OFFLINE_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC+"#offline",430,1000), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__ttLogin;},9000);
    openTT(f);
    await waitFor(function(){return ttNames(f).length>=1;},9000);
    w.__ttLogin.cfg(250,8000);
    submitLogin(f);
    await waitFor(function(){return /本机代理不在线/.test(txt(f,"#ttLoginSt"));},5000);
    T("B1 agent_offline 提示「本机代理不在线」", /本机代理不在线/.test(txt(f,"#ttLoginSt")), txt(f,"#ttLoginSt"));
    T("B2 agent_offline 时不发起轮询", statusReq(f).length===0, statusReq(f).length);
    T("B3 个人课表未写入（保留公共课表）", !loadState(f).ttLocal||!loadState(f).ttLocal.c||!loadState(f).ttLocal.c.length, JSON.stringify(loadState(f).ttLocal).slice(0,80));
    T("B4 公共课表仍显示", ttNames(f).indexOf("公共课A")>=0, ttNames(f).join(","));
    T("B5 密码未落 localStorage", !storeHas(f,PWD), "");
    T("B6 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]).slice(0,200));
    report("offline",R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("offline",R);
  }
}
run();
"""

FAILED_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC+"#failed",430,1000), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__ttLogin;},9000);
    openTT(f);
    await waitFor(function(){return ttNames(f).length>=1;},9000);
    w.__ttLogin.cfg(250,8000);
    submitLogin(f);
    await waitFor(function(){return /教务认证失败|失败|错误/.test(txt(f,"#ttLoginSt"));},7000);
    var st=txt(f,"#ttLoginSt");
    T("C1 failed 状态展示脱敏错误", /教务认证失败/.test(st), st.slice(0,120));
    T("C2 错误文本无 IP/路径/URL/token=", !/(\d{1,3}\.){3}\d{1,3}/.test(st)&&!st.match(/[A-Za-z]:\\/)&&!/https?:\/\//.test(st)&&!/token=/.test(st), st.slice(0,160));
    T("C3 失败保留公共课表（不写 ttLocal）", (!loadState(f).ttLocal||!loadState(f).ttLocal.c||!loadState(f).ttLocal.c.length)&&ttNames(f).indexOf("公共课A")>=0,
      JSON.stringify(loadState(f).ttLocal||null)+"|"+ttNames(f).join(","));
    var n1=statusReq(f).length;
    await sleep(900);
    var n2=statusReq(f).length;
    T("C4 失败后轮询停止", n1===n2, n1+" -> "+n2);
    T("C5 job 已清理/timer 停止", w.__ttLogin.state().job===""&&w.__ttLogin.state().timer===false, JSON.stringify(w.__ttLogin.state()));
    T("C6 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]).slice(0,200));
    report("failed",R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("failed",R);
  }
}
run();
"""

TIMEOUT_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC+"#timeout",430,1000), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__ttLogin;},9000);
    openTT(f);
    await waitFor(function(){return ttNames(f).length>=1;},9000);
    w.__ttLogin.cfg(200,1200); /* 缩短超时窗口：语义仍是「等待上限内未完成即停止」 */
    submitLogin(f);
    await waitFor(function(){return /等待超时/.test(txt(f,"#ttLoginSt"));},8000);
    T("D1 等待超时后提示「等待超时」", /等待超时/.test(txt(f,"#ttLoginSt")), txt(f,"#ttLoginSt"));
    var n1=statusReq(f).length;
    T("D2 超时前轮询有界（<=12 次）", n1>=2&&n1<=12, n1);
    await sleep(900);
    var n2=statusReq(f).length;
    T("D3 超时后轮询停止", n1===n2, n1+" -> "+n2);
    T("D4 超时不清空/不覆盖课表（保留公共课表）", ttNames(f).indexOf("公共课A")>=0&&(!loadState(f).ttLocal||!loadState(f).ttLocal.c||!loadState(f).ttLocal.c.length),
      ttNames(f).join(","));
    T("D5 job/timer 已清理", w.__ttLogin.state().job===""&&w.__ttLogin.state().timer===false, JSON.stringify(w.__ttLogin.state()));
    T("D6 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]).slice(0,200));
    report("timeout",R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("timeout",R);
  }
}
run();
"""

CLEAR_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC+"#clear",430,1000), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__ttLogin;},9000);
    /* 本场景在 preview 里预置了个人课表（2 门）→ 优先显示个人 */
    openTT(f);
    await waitFor(function(){return ttNames(f).length>=2;},9000);
    T("E1 个人课表优先于公共课表（预置 ttLocal）", w.__ttLogin.state().src==="mine"&&ttNames(f).indexOf("个人课A")>=0&&ttNames(f).indexOf("公共课A")<0,
      w.__ttLogin.state().src+"|"+ttNames(f).join(","));
    click(f,"#tLogin");
    await waitFor(function(){return q(f,"#ttLoginPanel").style.display!=="none";},4000);
    /* 取消：保留 */
    w.confirm=function(){return false;};
    click(f,"#ttLoginClear"); await sleep(150);
    T("E2 取消清除时保留个人课表", w.__ttLogin.state().local===2&&ttNames(f).indexOf("个人课A")>=0, w.__ttLogin.state().local+"|"+ttNames(f).join(","));
    /* 确定：清除并回退公共 */
    w.confirm=function(){return true;};
    click(f,"#ttLoginClear"); await sleep(250);
    T("E3 清除个人课表（ttLocal=null）", !loadState(f).ttLocal, JSON.stringify(loadState(f).ttLocal));
    await waitFor(function(){return w.__ttLogin.state().src!=="mine"&&ttNames(f).indexOf("公共课A")>=0;},4000);
    T("E4 清除后回退公共课表", w.__ttLogin.state().src==="pub"&&ttNames(f).indexOf("公共课A")>=0, w.__ttLogin.state().src+"|"+ttNames(f).join(","));
    T("E5 清除提示", /已清除个人课表/.test(txt(f,"#ttLoginSt")), txt(f,"#ttLoginSt"));
    var posts=w.__udPosts||[];
    var last=posts.length?posts[posts.length-1]:null;
    var blob=null;
    try{blob=last&&last[0]?JSON.parse(last[0].blob):null;}catch(e){}
    T("E6 清除同步到 UD v6（blob.tt.ttLocal=null）", !!blob&&blob.tt&&blob.tt.ttLocal===null, blob?JSON.stringify(blob.tt||{}).slice(0,120):"no blob");
    T("E7 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]).slice(0,200));
    report("clear",R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("clear",R);
  }
}
run();
"""

LAYOUT_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var W=__W__, f=await mount(SRC+"#success",W,1000), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__ttLogin;},9000);
    openTT(f);
    await waitFor(function(){return ttNames(f).length>=1;},9000);
    click(f,"#tLogin");
    await waitFor(function(){return q(f,"#ttLoginPanel").style.display!=="none";},4000);
    await sleep(150);
    var de=d.documentElement;
    var p=q(f,"#ttLoginPanel .mcard").getBoundingClientRect();
    T("F"+W+"-1 页面无横向溢出", de.scrollWidth<=de.clientWidth+1, de.scrollWidth+"/"+de.clientWidth);
    T("F"+W+"-2 登录弹层完整在视口内", p.left>=-1&&p.right<=w.innerWidth+1&&p.top>=-1&&p.bottom<=w.innerHeight+1,
      "l="+Math.round(p.left)+" r="+Math.round(p.right)+" t="+Math.round(p.top)+" b="+Math.round(p.bottom)+" vw="+w.innerWidth+" vh="+w.innerHeight);
    var gb=q(f,"#ttLoginGo").getBoundingClientRect();
    T("F"+W+"-3 登录按钮可点高度 ≥40px", gb.height>=39.5, gb.height);
    T("F"+W+"-4 关闭按钮存在", !!q(f,"#ttLoginClose"), "");
    T("F"+W+"-5 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]).slice(0,200));
    report("layout_"+W,R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("layout_"+W,R);
  }
}
run();
"""

SHOT_JS = r"""
async function run(){
  var R={steps:[],errs:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var h=String(location.hash||"").replace("#","");
    var m=h.match(/^(390|1280)-(open|success|failed)$/), W=m?+m[1]:390, mode=m?m[2]:"open";
    var hash=mode==="success"?"#success":(mode==="failed"?"#failed":"#success");
    var f=await mount(SRC+hash,W,1200), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__ttLogin;},9000);
    openTT(f);
    await waitFor(function(){return ttNames(f).length>=1;},9000);
    if(mode==="success"){
      w.__ttLogin.cfg(150,8000);
      submitLogin(f);
      await waitFor(function(){return w.__ttLogin.state().local===2&&w.__ttLogin.state().job==="";},9000);
      await sleep(1100); /* 等弹层自动关闭 */
    }else if(mode==="failed"){
      w.__ttLogin.cfg(150,8000);
      submitLogin(f);
      await waitFor(function(){return /教务认证失败/.test(txt(f,"#ttLoginSt"));},9000);
      await sleep(200);
    }else{
      click(f,"#tLogin");
      await waitFor(function(){return q(f,"#ttLoginPanel").style.display!=="none";},4000);
      await sleep(250);
    }
    try{
      var st=d.createElement("style");
      st.textContent=".tabs button,.tabs-thumb{transition:none!important;animation:none!important}";
      d.head.appendChild(st);
    }catch(e){}
    R.state=w.__ttLogin.state();
    T("截图页面就绪 "+mode, true, "");
    report("shot_"+h.replace("-","_"),R);
    await sleep(500);
  }catch(e){
    R.steps.push({k:"截图脚本异常",ok:false,note:String(e&&e.stack||e)});
    report("shot_err",R);
  }
}
run();
"""


def build_harness(name, js, src):
    body = (COMMON_JS.replace("__SRC__", src).replace("__SID__", SID)
            .replace("__TOKEN__", TOKEN).replace("__PWD__", PWD) + "\n" + js)
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>tt login check</title>"
            "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
            "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
    open(os.path.join(HERE, name), "w", encoding="utf-8", newline="").write(html)


# 清除场景需要预置 ttLocal：单独预览（同一 INJECT，替换 __SEED_LOCAL__）
PREVIEW_CLEAR = "_ttlogin_preview_clear.html"


def build_preview_clear():
    html = open(os.path.join(HERE, PREVIEW), encoding="utf-8", newline="").read()
    html = html.replace("var SEED_LOCAL=[];", "var SEED_LOCAL=" + json.dumps(MINE_C, ensure_ascii=False) + ";")
    open(os.path.join(HERE, PREVIEW_CLEAR), "w", encoding="utf-8", newline="").write(html)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        qs = urllib.parse.urlparse(self.path).query
        mm = re.search(r"slot=([A-Za-z0-9_\-]+)", qs)
        slot = mm.group(1) if mm else "default"
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


def run_edge(url, budget=30000, shot=None, timeout=240, window="492,1000"):
    prof = tempfile.mkdtemp(prefix="edgeprof_", dir=REPORT_DIR)
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


def clear_report(slot):
    p = os.path.join(REPORT_DIR, slot + ".json")
    if os.path.exists(p):
        try:
            os.remove(p)
        except Exception:
            pass


def wait_report(slot, secs=25):
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


def run_and_report(url, slot, budget=30000, shot=None, window="492,1000", secs=28, retries=2):
    data = None
    for _ in range(retries):
        clear_report(slot)
        run_edge(url, budget=budget, shot=shot, window=window)
        data = wait_report(slot, secs)
        if data:
            return data
        time.sleep(0.3)
    return None


STATIC = []


def static_checks(html):
    STATIC.append(("[静态] 课表头部有「登录教务」按钮",
                   'id="tLogin"' in html and "登录教务" in html, ""))
    STATIC.append(("[静态] 登录弹层：学号 + type=password 密码 + 清除入口",
                   'id="ttLoginSid"' in html and 'id="ttLoginPwd"' in html and
                   'type="password"' in html and 'id="ttLoginClear"' in html and "清除我的课表" in html, ""))
    STATIC.append(("[静态] POST rpc/tt_login_enqueue（p_platform=web）",
                   'CB+"rpc/tt_login_enqueue"' in html and 'p_platform:"web"' in html, ""))
    STATIC.append(("[静态] POST rpc/tt_login_status 轮询（1.5s / 120s 上限）",
                   'CB+"rpc/tt_login_status"' in html and "poll:1500" in html and "limit:120000" in html, ""))
    STATIC.append(("[静态] done 写入 D.d.ttLocal 并立即 renderTT", "D.d.ttLocal={c:cs,t:" in html and "renderTT()" in html, ""))
    STATIC.append(("[静态] ttData 优先级：个人 ttLocal 先于公共课表",
                   html.find("function ttData(){") > 0 and
                   html.find("var m=ttMineCourse();", html.find("function ttData(){")) <
                   html.find("var p=ttPubCourse();", html.find("function ttData(){")) > 0, ""))
    STATIC.append(("[静态] 错误码提示（agent_offline/rate/pwd/auth）",
                   all(x in html for x in ['"agent_offline"', '"rate"', '"pwd"', '"auth"', "本机代理不在线"]), ""))
    STATIC.append(("[静态] 密码不落 localStorage（无 zq_tt_pwd 等键）",
                   "zq_tt_pwd" not in html and "localStorage.setItem" in html and
                   not re.search(r'localStorage\.setItem\([^)]*pwd', html, re.I), ""))
    STATIC.append(("[静态] 失败文本显示前脱敏（sensMask）", "sensMask(String(j.error" in html, ""))
    STATIC.append(("[静态] APP_VER 保持 2.0.0", 'var APP_VER="2.0.0"' in html, ""))
    STATIC.append(("[静态] 无外部脚本/字体引用", not re.search(r'(src|href)\s*=\s*["\']https?://', html), ""))


def add_many(results, prefix, data):
    if not data:
        results.append((prefix + " 未返回结果", False, "report 缺失（浏览器未上报）"))
        return
    for s in data.get("steps", []):
        results.append(("[" + prefix + "] " + s.get("k", "?"), bool(s.get("ok")), s.get("note", "")))


def main():
    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    for fn in os.listdir(REPORT_DIR):
        try:
            os.remove(os.path.join(REPORT_DIR, fn))
        except Exception:
            pass
    html = open(SRC, encoding="utf-8", newline="").read()
    static_checks(html)
    build_previews()
    build_preview_clear()
    build_harness(HARNESS_SUCCESS, SUCCESS_JS, PREVIEW)
    build_harness(HARNESS_OFFLINE, OFFLINE_JS, PREVIEW)
    build_harness(HARNESS_FAILED, FAILED_JS, PREVIEW)
    build_harness(HARNESS_TIMEOUT, TIMEOUT_JS, PREVIEW)
    build_harness(HARNESS_CLEAR, CLEAR_JS, PREVIEW_CLEAR)
    build_harness(HARNESS_LAYOUT, LAYOUT_JS, PREVIEW)
    build_harness(HARNESS_SHOT, SHOT_JS, PREVIEW)

    httpd = Q(("127.0.0.1", PORT), functools.partial(Handler, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    results = []
    try:
        add_many(results, "成功", run_and_report(BASE + "tests/" + HARNESS_SUCCESS, "success", budget=40000, secs=40))
        add_many(results, "离线", run_and_report(BASE + "tests/" + HARNESS_OFFLINE, "offline", budget=30000, secs=32))
        add_many(results, "失败", run_and_report(BASE + "tests/" + HARNESS_FAILED, "failed", budget=30000, secs=32))
        add_many(results, "超时", run_and_report(BASE + "tests/" + HARNESS_TIMEOUT, "timeout", budget=30000, secs=32))
        add_many(results, "清除", run_and_report(BASE + "tests/" + HARNESS_CLEAR, "clear", budget=30000, secs=32))
        for w in (360, 390, 1280):
            build_harness(HARNESS_LAYOUT, LAYOUT_JS.replace("__W__", str(w)), PREVIEW)
            add_many(results, "布局@" + str(w),
                     run_and_report(BASE + "tests/" + HARNESS_LAYOUT, "layout_%d" % w, budget=30000, secs=32))
        for mode, fname, winsz, h in (("390-open", "tt_login_390_open.png", "492,1300", 1200),
                                      ("390-success", "tt_login_390_success.png", "492,1300", 1200),
                                      ("390-failed", "tt_login_390_failed.png", "492,1300", 1200),
                                      ("1280-open", "tt_login_1280_open.png", "1320,1300", 1200)):
            p = os.path.join(SHOTS, fname)
            if os.path.exists(p):
                os.remove(p)
            build_harness(HARNESS_SHOT, SHOT_JS, PREVIEW)
            data = run_and_report(BASE + "tests/" + HARNESS_SHOT + "#" + mode, "shot_" + mode.replace("-", "_"),
                                  budget=42000, shot=p, window=winsz, secs=32)
            add_many(results, "截图:" + mode, data)
            ok = os.path.exists(p) and os.path.getsize(p) > 20000
            results.append(("截图 " + fname, ok, ("%d bytes" % os.path.getsize(p)) if os.path.exists(p) else "未生成"))
    finally:
        httpd.shutdown()
    for name, ok, note in STATIC:
        results.insert(0, (name, bool(ok), note))
    fails = [r for r in results if not r[1]]
    for name, ok, note in results:
        print(("[PASS] " if ok else "[FAIL] ") + name + (("  -- " + str(note)[:220]) if (note and not ok) else ""))
    print("")
    print("=" * 66)
    print("v2_tt_login_check: %d 项，PASS %d，FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    print("截图目录:", SHOTS)
    print("=" * 66)
    return 0 if not fails else 1


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        for fn in (PREVIEW, PREVIEW_CLEAR, HARNESS_SUCCESS, HARNESS_OFFLINE, HARNESS_FAILED,
                   HARNESS_TIMEOUT, HARNESS_CLEAR, HARNESS_LAYOUT, HARNESS_SHOT):
            try:
                os.remove(os.path.join(HERE, fn))
            except Exception:
                pass
    sys.exit(code)
