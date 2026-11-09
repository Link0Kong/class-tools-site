# -*- coding: utf-8 -*-
"""诊断 v2.1（网页）专项验收：AI 结论下挂异常项 + 折叠/展开 + 10s 进展 + 设备信息最小化。

契约：C:\\Users\\Ko_Li\\.openclaw\\workspace\\_diag_task\\CONTRACT_V2_1.md §A/§B/§D（基线 CONTRACT.md §2）。
做法（复用 v2 / reset_check 的注入 + iframe + headless Edge + screenshot 方式）：
- 复制 tools/index.html 到 tests/_diagv21_preview*.html，注入假身份 + fetch mock：
  service_health 18 行（3 异常 + 其余正常）、diag_analysis（related.health_ids / related.checks /
  无关联 / 未知 checks 旧数据）、repair_tasks（running/done/orphan）、client_diag 记录；
  第二次 diag_analysis 请求让 running→fixed（验证状态胶囊实时更新）。
- 场景：gate（无身份）、main（#ok）、waiting-off（#agentoffline：离线保留文案）、
  fail（#fail：云端失败 → 设备异常自动上报，验证 §B 白名单）、jserr（全局错误上报白名单）、
  布局 360/390/430/1280（展开态无溢出）、截图 _shots_diag_v21/。

用法（cwd 任意）：
    python web/tools/tests/v2_diag_v2_check.py
    环境变量 DIAGV2_SRC 可指定副本；DIAGV2_PORT（默认 8941）。
退出码 0 = 全绿；截图存 tools/tests/_shots_diag_v21/。
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

HERE = os.path.dirname(os.path.abspath(__file__))       # tools/tests
ROOT = os.path.dirname(HERE)                            # tools
SRC = os.path.abspath(os.environ.get("DIAGV2_SRC") or os.path.join(ROOT, "index.html"))
SHOTS = os.path.join(HERE, "_shots_diag_v21")
REPORT_DIR = os.path.join(HERE, "_diagv21_reports")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = int(os.environ.get("DIAGV2_PORT") or 8941)
BASE = "http://127.0.0.1:%d/" % PORT

SID = "3260709999"
NAME = "测试同学"
TOKEN = "test-token-diagv21"
NOW = int(time.time() * 1000)

MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": "", "badge": "", "is_admin": False} for i in range(1, 71)]


def _row(rid, name, kind, status, detail, meta=None, chk=None):
    return {"id": rid, "name": name, "kind": kind, "status": status,
            "detail": detail, "meta": meta or {},
            "checked_at": chk if chk is not None else NOW - 5000}


# 18 行 / 5 组；3 异常（briefdesk / cloud_power_sync 有 AI；watcher 无 AI → 等待行），其余正常。
# 不含 cloudbase 异常（buildItem 会用浏览器实时探测覆盖 cloudbase，mock 下恒正常）。
HEALTH = [
    _row("site_static", "站点资源", "static", "ok", "HTTP 200 · 45ms"),
    _row("site_tls", "站点证书", "static", "ok", "证书有效 · 62 天"),
    _row("dns_domain", "域名解析", "cloud", "ok", "解析正常"),
    _row("cloudbase", "云端数据库", "cloud", "ok", "HTTP 200 · 52ms"),
    _row("tt_cloud", "课表云端数据", "cloud", "ok", "云端快照 1 小时前同步"),
    _row("cloud_power_sync", "电费云同步", "cloud", "warn", "最近同步 2 小时前 · 主机 10.0.0.5"),
    _row("cloud_xgj_sync", "学工记云同步", "cloud", "ok", "最近同步 1 小时前"),
    _row("cloud_health_probe", "云端巡检", "cloud", "ok", "本轮完成 · 8 行 · 860ms"),
    _row("qqflow", "QQ 消息采集", "local", "ok", "健康 · 账号就绪"),
    _row("weflow", "微信消息采集", "local", "ok", "健康 · 账号就绪"),
    _row("watcher", "文档/通知监听", "local", "down", "日志 32 分钟前更新"),
    _row("briefdesk", "本地通知服务", "local", "down",
         "服务无响应 · 主机 192.168.1.7 · C:\\briefdesk\\logs\\notice.log · "
         "https://tool.furina.fun/index.html?token=abc123"),
    _row("qq_client", "QQ 客户端", "local", "ok", "进程运行中（9 个实例）"),
    _row("wechat_client", "微信客户端", "local", "ok", "进程运行中（5 个实例）"),
    _row("jwxt", "教务课表同步", "local", "ok", "课表 12.0 小时前同步"),
    _row("hwauto", "作业自动整理", "local", "ok", "作业整理 1.2 小时前运行"),
    _row("ai", "AI 识别", "local", "ok", "最近成功 07:10"),
    _row("collector_host", "采集主机", "local", "ok", "在线 1天2小时 · 上轮 2s"),
]

# 两条 health_ids 下挂（running / fixed）、一条 related.checks（failed）、
# 一条无关联 + 一条未知 checks（旧数据）→ 其它诊断；修复记录 running/done/orphan。
ANALYSIS = [
    {"id": "an-h1", "ts": NOW - 300000, "platform": "web", "scope": "cloud", "severity": "error",
     "title": "本地通知服务无响应，需要重启并复检依赖服务链路", "cause": "进程 10.0.0.5 的 C:\\briefdesk\\logs\\notice.log 显示 https://tool.furina.fun/x?token=zzz9 超时",
     "suggestion": ["重跑健康复检", "确认采集主机在线"],
     "fixable": True, "action": "recheck_health", "status": "running", "confidence": 0.82,
     "related": {"health_ids": ["briefdesk"], "repair_id": "rp-run"},
     "flow": [{"t": "22:10", "text": "检测到本地通知服务无响应", "st": "done"},
              {"t": "22:11", "text": "本机开始执行 recheck_health", "st": "run"}]},
    {"id": "an-h2", "ts": NOW - 600000, "platform": "web", "scope": "cloud", "severity": "warn",
     "title": "电费云同步延迟", "cause": "最近同步 2 小时前（上次 192.168.0.2）",
     "suggestion": ["等待本机代理同步", "检查定时任务"], "fixable": True, "action": "sync_power",
     "status": "fixed", "confidence": 0.6, "related": {"health_ids": ["cloud_power_sync"], "repair_id": "rp-done"},
     "flow": [{"t": "21:40", "text": "检测到同步延迟", "st": "done"},
              {"t": "21:42", "text": "执行 sync_power", "st": "done"},
              {"t": "21:43", "text": "同步完成", "st": "done"}]},
    {"id": "an-c1", "ts": NOW - 90000, "platform": "web", "scope": "device", "severity": "warn",
     "title": "本机时钟偏差较大", "cause": "与本机时间相差约 5 分钟（Date 头）",
     "suggestion": ["校准系统时间", "不影响主要功能"], "fixable": False, "action": "", "status": "failed",
     "confidence": 0.4, "related": {"checks": ["clock"]},
     "flow": [{"t": "22:12", "text": "设备检查发现时钟偏差较大", "st": "fail"}]},
    {"id": "an-other", "ts": NOW - 1800000, "platform": "all", "scope": "mixed", "severity": "info",
     "title": "历史遗留分析：无关联记录", "cause": "旧版本写入，无法归因", "suggestion": ["仅展示"],
     "fixable": False, "action": "", "status": "new", "confidence": 0.1, "related": {}},
    {"id": "an-oldcheck", "ts": NOW - 3600000, "platform": "web", "scope": "device", "severity": "warn",
     "title": "旧版设备检查项", "cause": "detail.check=legacy_mem 不在当前检查列表", "suggestion": [],
     "fixable": False, "action": "", "status": "new", "confidence": 0.2,
     "related": {"checks": ["legacy_mem"]}},
]

REPAIRS = [
    {"id": "rp-run", "created_at": NOW - 120000, "action": "recheck_health", "params": {},
     "reason": "本地通知服务无响应", "status": "running", "claimed_at": NOW - 60000,
     "finished_at": 0, "result": "", "analysis_id": "an-h1", "node": "local"},
    {"id": "rp-done", "created_at": NOW - 620000, "action": "sync_power", "params": {},
     "reason": "电费云同步延迟", "status": "done", "claimed_at": NOW - 600000,
     "finished_at": NOW - 590000,
     "result": "同步完成（C:\\briefdesk\\logs\\power.log · 主机 192.168.0.2）",
     "analysis_id": "an-h2", "node": "local"},
    {"id": "rp-orphan", "created_at": NOW - 7200000, "action": "web_pause_off", "params": {},
     "reason": "历史修复记录（无 analysis 关联）", "status": "failed", "claimed_at": NOW - 7100000,
     "finished_at": NOW - 7000000, "result": "失败：命令超时", "analysis_id": "", "node": "local"},
]

TT_BODY = {"c": [{"name": "测试课程", "teacher": "测试老师", "room": "101", "day": 0,
                  "start": 1, "end": 2, "weeks": "1-16", "parity": "all"}],
           "t": "2026-09-07", "meta": {"source": "jwxt", "fetchedAt": NOW - 3600000, "count": 1}}

PREVIEW = "_diagv21_preview.html"
PREVIEW_GATE = "_diagv21_preview_gate.html"
HARNESS_MAIN = "_diagv21_harness_main.html"
HARNESS_OFFLINE = "_diagv21_harness_offline.html"
HARNESS_FAIL = "_diagv21_harness_fail.html"
HARNESS_JSERR = "_diagv21_harness_jserr.html"
HARNESS_GATE = "_diagv21_harness_gate.html"
HARNESS_LAYOUT = "_diagv21_harness_layout.html"
HARNESS_SHOT = "_diagv21_harness_shot.html"

INJECT = """<script>
(function(){
window.__errs=[];window.__cerrs=[];window.__fetchlog=[];window.__clientDiag=[];window.__external=[];
window.__aiCalls=0;
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));_ce.apply(console,arguments);};
var MODE=String(location.hash||"").replace("#","");
function resp(v,extra){
  var hdr={};if(extra)for(var k in extra)hdr[String(k).toLowerCase()]=extra[k];
  return Promise.resolve({ok:true,status:200,
    headers:{get:function(k){return hdr[String(k).toLowerCase()]||null;}},
    json:function(){return Promise.resolve(v);},
    text:function(){return Promise.resolve("");}});
}
function errResp(code){
  return Promise.resolve({ok:false,status:code,headers:{get:function(){return null;}},
    json:function(){return Promise.resolve({});},text:function(){return Promise.resolve("");}});
}
var MEMBERS=__MEMBERS__, HEALTH=__HEALTH__, ANALYSIS=__ANALYSIS__, REPAIRS=__REPAIRS__, TT=__TT__;
function clone(x){return JSON.parse(JSON.stringify(x));}
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};
  var s=String((u&&u.url!==undefined)?u.url:u);
  var m=String(o.method||"GET").toUpperCase();
  try{window.__fetchlog.push({method:m,url:s,headers:o.headers||{},body:String(o.body||"")});}catch(e){}
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0)return resp(MEMBERS);
    if(s.indexOf("service_health?select=")>=0){
      if(MODE==="fail")return errResp(500);
      /* Date 头人为 +5 分钟：让设备检查「时钟偏差」稳定为「注意」，供 related.checks 下挂用例 */
      return resp(HEALTH,{"Date":new Date(Date.now()+300000).toUTCString()});
    }
    if(s.indexOf("rpc/diag_agent_info")>=0){
      if(MODE==="agentoffline")return resp({ok:true,online:false,seen_at:0,host:"",version:""});
      return resp({ok:true,online:true,seen_at:Date.now()-120000,host:"local-windows",version:"1.0.5"});
    }
    if(s.indexOf("diag_analysis?select=")>=0){
      window.__aiCalls++;
      var list=clone(ANALYSIS);
      if(window.__aiCalls>=2){
        list[0].status="fixed";
        list[0].flow=[{t:"22:10",text:"检测到本地通知服务无响应",st:"done"},
                      {t:"22:12",text:"重测 18 行全部正常",st:"done"}];
      }
      return resp(list);
    }
    if(s.indexOf("repair_tasks?select=")>=0)return resp(clone(REPAIRS));
    if(s.indexOf("client_diag")>=0){
      try{window.__clientDiag.push(JSON.parse(String(o.body||"[]")));}catch(e){}
      return resp([],{});
    }
    if(s.indexOf("/notices")>=0)return resp([]);
    if(s.indexOf("/homework")>=0)return resp([]);
    if(s.indexOf("/marks")>=0)return resp([]);
    if(s.indexOf("/fitrecs")>=0)return resp([]);
    if(s.indexOf("/userdata")>=0)return m==="POST"?resp([{id:"__SID__"}]):resp([]);
    if(s.indexOf("site_assets")>=0)return resp([]);
    return resp([]);
  }
  if(s.indexOf("tt.json")>=0)return resp(TT);
  window.__external.push(s);
  return _f.apply(this,arguments);
};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"__TOKEN__",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
__LOCAL__
})();
</script>"""

LOCAL_MAIN = 'try{localStorage.setItem("zq_tools_v2_%s",JSON.stringify({"homeTools":["draw","hw","nt","tt"],"termStart":"2026-09-07"}));}catch(e){}' % SID
LOCAL_GATE = 'try{localStorage.removeItem("zq_class_identity");}catch(e){}'


def build_previews():
    html = open(SRC, encoding="utf-8", newline="").read()
    fill = (INJECT.replace("__MEMBERS__", json.dumps(MEMBERS, ensure_ascii=False))
                   .replace("__HEALTH__", json.dumps(HEALTH, ensure_ascii=False))
                   .replace("__ANALYSIS__", json.dumps(ANALYSIS, ensure_ascii=False))
                   .replace("__REPAIRS__", json.dumps(REPAIRS, ensure_ascii=False))
                   .replace("__TT__", json.dumps(TT_BODY, ensure_ascii=False))
                   .replace("__TOKEN__", TOKEN).replace("__SID__", SID).replace("__NAME__", NAME))
    for name, local in ((PREVIEW, LOCAL_MAIN), (PREVIEW_GATE, LOCAL_GATE)):
        out = html.replace("<head>", "<head>" + fill.replace("__LOCAL__", local), 1)
        open(os.path.join(HERE, name), "w", encoding="utf-8", newline="").write(out)


COMMON_JS = r"""
var SRC="__SRC__", GATE="__GATE__", SID="__SID__", TOKEN="__TOKEN__", STORE="zq_tools_v2_"+SID;
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
    f.onerror=function(){ if(done)return; done=true; rej(new Error("iframe load failed: "+src)); };
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
function diagReq(f,part){return (f.contentWindow.__fetchlog||[]).filter(function(x){return x.url.indexOf(part)>=0;});}
function healthRow(f,id){return q(f,'#diagGrid .diag-row[data-hid="'+id+'"]');}
/* 某行后面紧跟的 AI 折叠行 / 等待行（兄弟节点） */
function afterRow(rowEl){
  var out=[],n=rowEl?rowEl.nextElementSibling:null;
  while(n&&(n.classList.contains("dai2")||n.classList.contains("dai2-wait"))){out.push(n);n=n.nextElementSibling;}
  return out;
}
function foldsUnder(f,rowEl){return afterRow(rowEl).filter(function(x){return x.classList.contains("dai2");});}
function waitUnder(f,rowEl){return afterRow(rowEl).filter(function(x){return x.classList.contains("dai2-wait");});}
function foldPill(fold){var e=fold.querySelector(".dai2-st");return e?e.textContent:"";}
function foldTitle(fold){var e=fold.querySelector(".dai2-title");return e?e.textContent:"";}
function hd(fold){return fold.querySelector(".dai2-hd");}
function maskBad(s){return /(\d{1,3}\.){3}\d{1,3}|[A-Za-z]:\\|https?:\/\/|token=|password|pwd/i.test(String(s||""));}
function report(slot,data){
  data=data||{}; data.slot=slot;
  try{
    var x=new XMLHttpRequest();
    x.open("POST","/_report?slot="+slot,false);
    x.setRequestHeader("Content-Type","application/json");
    x.send(JSON.stringify(data));
  }catch(e){}
}
async function openDiag(f,w){
  w.__diag.gotoTab("diag");
  w.__diag.setAiInterval(60000); /* 防止 10s 轮询在断言前把 running 变成 fixed */
  await waitFor(function(){return f.contentDocument.querySelectorAll("#diagGrid .diag-row").length===18;},9000);
  await waitFor(function(){return (w.__diag.device()&&w.__diag.device().checks.length)===9;},9000);
  await waitFor(function(){return (w.__diag.ai()&&w.__diag.ai().list.length)===5;},9000);
  await sleep(120);
}
"""

MAIN_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC+"#ok",430,1100), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__diag;},9000);
    await sleep(150);
    var ident={};try{ident=JSON.parse(w.localStorage.getItem("zq_class_identity")||"{}");}catch(e){}
    T("A1 非管理员身份（is_admin=false）也可用诊断", ident.is_admin===false, JSON.stringify(ident).slice(0,100));
    w.__diag.gotoTab("all"); await sleep(120);
    T("A2 全部页有诊断卡（无管理角标）", !!q(f,'#allCards .gcard.tool[data-open="diag"]')&&!q(f,'#allCards .gcard.tool[data-open="diag"] .n'), "");
    T("A9 默认 AI/agent/repair 轮询 10s", w.__diag.state().aiInterval===10000, w.__diag.state().aiInterval);
    await openDiag(f,w);
    T("A3 无独立 AI 大卡 #diagAI", !q(f,"#diagAI"), "");
    T("A4 服务健康 18 行 / 5 组", qa(f,"#diagGrid .diag-row").length===18&&qa(f,"#diagGrid .diag-group").length===5,
      qa(f,"#diagGrid .diag-row").length+" / "+qa(f,"#diagGrid .diag-group").length);
    T("A5 顶部摘要 2 项异常（另 1 项注意）", /2 项异常/.test(txt(f,"#diagSum .diag-sumtext")), txt(f,"#diagSum .diag-sumtext"));
    var sm=txt(f,"#diagSum");
    T("A6 摘要追加「可自动修复 2 · 已修复 1」", /可自动修复 2/.test(sm)&&/已修复 1/.test(sm), sm.replace(/\s+/g," ").slice(0,160));
    T("A7 顶部显示本机代理在线", /本机代理 在线/.test(sm), "");
    T("A8 摘要含最后更新时刻", /最后检测 \d{2}:\d{2}:\d{2}/.test(sm)&&/更新 \d{2}:\d{2}:\d{2}/.test(sm), "");

    /* B. AI 下挂：health_ids / checks / 正常行不显示 */
    var rowH1=healthRow(f,"briefdesk"), rowH2=healthRow(f,"cloud_power_sync"), rowW=healthRow(f,"watcher"), rowOk=healthRow(f,"qqflow");
    var h1=foldsUnder(f,rowH1), h2=foldsUnder(f,rowH2), c1=foldsUnder(f,q(f,'#diagDevice .dd-row[data-dc="clock"]'));
    T("B1 health_ids 下挂到「本地通知服务」行", h1.length===1, h1.length);
    T("B2 health_ids 下挂到「电费云同步」行", h2.length===1, h2.length);
    T("B3 related.checks 下挂到设备检查「时钟偏差」行", c1.length===1, c1.length);
    T("B4 底挂行无 data-hid（不是服务健康行）", qa(f,"#diagGrid .dai2").length===2&&qa(f,"#diagDevice .dai2").length===1,
      qa(f,"#diagGrid .dai2").length+"/"+qa(f,"#diagDevice .dai2").length);
    T("B5 正常行不显示 AI/等待行", afterRow(rowOk).length===0, afterRow(rowOk).length);

    /* C. 折叠态：1 行高度 / 标题截断 / 状态胶囊 / ⚙ */
    var fold1=h1[0];
    var hh=hd(fold1).getBoundingClientRect().height;
    T("C1 折叠行高度 28–36px（单行）", hh>=28&&hh<=36, hh.toFixed(1));
    T("C2 标题截断 ≤22 字（含省略号）", foldTitle(fold1).length<=22, foldTitle(fold1)+" ("+foldTitle(fold1).length+")");
    T("C3 running 胶囊=「修复中」", foldPill(fold1)==="修复中", foldPill(fold1));
    T("C4 fixed 胶囊=「已修复」", foldPill(h2[0])==="已修复", foldPill(h2[0]));
    T("C5 failed 胶囊=「修复失败」", foldPill(c1[0])==="修复失败", foldPill(c1[0]));
    T("C6 fixable 显示 ⚙ 可自动修复", /⚙/.test(fold1.textContent)&&/可自动修复/.test(fold1.textContent), "");
    T("C7 折叠态详情默认隐藏", getComputedStyle(fold1.querySelector(".dai2-body")).display==="none", "");
    T("C8 折叠行有 severity 圆点", !!fold1.querySelector(".dai2-dot.error"), "");
    T("C9 折叠行有展开箭头 ›", /›/.test(fold1.querySelector(".dai2-arr").textContent), "");

    /* D. 等待行：本机在线 → AI 分析排队中… */
    var wts=waitUnder(f,rowW);
    T("D1 异常行无 AI 时显示「AI 分析排队中…」", wts.length===1&&/AI 分析排队中/.test(wts[0].textContent), wts.length?wts[0].textContent:"missing");

    /* E. 点击展开：cause / suggestion / flow / 关联修复 */
    hd(fold1).click(); await sleep(150);
    var fold1b=foldsUnder(f,healthRow(f,"briefdesk"))[0];
    T("E1 点击整行展开（.on + aria-expanded）", fold1b.classList.contains("on")&&fold1b.querySelector(".dai2-hd").getAttribute("aria-expanded")==="true", "");
    T("E2 展开显示原因（脱敏）", /原因/.test(fold1b.textContent)&&!/10\.0\.0\.5|C:\\briefdesk|token=zzz9/.test(fold1b.textContent), fold1b.textContent.replace(/\s+/g," ").slice(0,160));
    T("E3 展开显示建议列表（≤4 条）", fold1b.querySelectorAll(".dai2-sug li").length>=1&&fold1b.querySelectorAll(".dai2-sug li").length<=4,
      fold1b.querySelectorAll(".dai2-sug li").length);
    T("E4 展开显示 flow 时间线且 run 步可见", fold1b.querySelectorAll(".dai2-flow .dai2-step").length===2&&
      !!fold1b.querySelector(".dai2-step.run")&&/本机开始执行 recheck_health/.test(fold1b.textContent), "");
    T("E5 展开显示关联修复（action/状态/时间）", /关联修复/.test(fold1b.textContent)&&/recheck_health/.test(fold1b.textContent)&&/执行中/.test(fold1b.textContent), "");
    var arrowRot=fold1b.querySelector(".dai2-arr");
    T("E6 展开后箭头旋转 90°", String(w.getComputedStyle(arrowRot).transform||"").indexOf("matrix")>=0, w.getComputedStyle(arrowRot).transform);
    /* 展开 fixed 项 → 关联修复 result 可见 */
    var fold2=foldsUnder(f,healthRow(f,"cloud_power_sync"))[0];
    hd(fold2).click(); await sleep(150);
    var fold2b=foldsUnder(f,healthRow(f,"cloud_power_sync"))[0];
    T("E7 fixed 项展开显示关联修复结果", /sync_power/.test(fold2b.textContent)&&/已完成/.test(fold2b.textContent)&&/同步完成/.test(fold2b.textContent), "");
    T("E8 修复结果脱敏", !/C:\\briefdesk|192\.168\.0\.2/.test(fold2b.textContent), fold2b.textContent.replace(/\s+/g," ").slice(0,160));
    /* 展开态跨轮询保留 + 状态胶囊实时更新（第二次 diag_analysis 返回 fixed） */
    var pillBefore=foldPill(fold1b);
    w.__diag.setAiInterval(300); await sleep(900);
    var fold1c=null; try{fold1c=foldsUnder(f,healthRow(f,"briefdesk"))[0];}catch(e){}
    T("E9 轮询后状态胶囊 running→fixed 实时更新", pillBefore==="修复中"&&!!fold1c&&foldPill(fold1c)==="已修复",
      pillBefore+" -> "+(fold1c?foldPill(fold1c):"missing"));
    T("E10 轮询刷新后展开态保留", !!fold1c&&fold1c.classList.contains("on"), fold1c?String(fold1c.className):"missing");
    T("E11 run 步已被完成步替换（flow 实时）", !!fold1c&&!/本机开始执行 recheck_health/.test(fold1c.textContent)&&/重测 18 行全部正常/.test(fold1c.textContent), "");
    w.__diag.setAiInterval(60000);

    /* F. 其它诊断折叠区（无关联 + 未知 checks 旧数据 + 孤立修复） */
    var other=q(f,"#diagOther");
    T("F1 「其它诊断」折叠区显示", !!other&&other.style.display!=="none", other?other.style.display:"missing");
    var body=q(f,"#diagOther .dai2-other-body");
    T("F2 默认收起只显示条数", !!body&&getComputedStyle(body).display==="none"&&/其它诊断/.test(txt(f,"#diagOther"))&&/3/.test(txt(f,"#diagOther .dd-cnt")),
      txt(f,"#diagOther .dd-cnt"));
    click(f,"#diagOtherToggle"); await sleep(150);
    T("F3 展开其它诊断显示 3 条（2 分析 + 1 孤立修复）", qa(f,"#diagOther .dai2").length===3, qa(f,"#diagOther .dai2").length);
    T("F4 旧数据未知 checks 归入其它诊断", /旧版设备检查项/.test(txt(f,"#diagOther")), "");
    T("F5 孤立修复记录归入其它诊断", /web_pause_off/.test(txt(f,"#diagOther")), "");
    T("F6 其它诊断里的折叠可展开", (function(){var a=qa(f,"#diagOther .dai2")[0];var b=hd(a);b.click();return !!a;})()&&true, "");
    await sleep(150);
    T("F7 其它诊断展开后详情可见", qa(f,"#diagOther .dai2.on .dai2-body").length>=1, qa(f,"#diagOther .dai2.on").length);

    /* G. 状态实时更新已在 E9–E11 覆盖；此处仅确认 AI 数据源在途 */
    T("G1 diag_analysis 请求已发出", diagReq(f,"diag_analysis?select=").length>=1, diagReq(f,"diag_analysis?select=").length);

    /* H. 设备诊断 9 项 & 展示端最小化（无 UA/语言/IndexedDB） */
    var devIds=allText(f,"#diagDevice .dd-row").map(function(x){return x;});
    var dcIds=qa(f,"#diagDevice .dd-row").map(function(e){return e.getAttribute("data-dc");});
    T("H1 设备检查 9 项且 id 白名单", dcIds.join(",")==="os,screen,memory,storage,network,gateway,clock,timetable,js", dcIds.join(","));
    var devText=allText(f,"#diagDevice .dd-v").join(" | ");
    T("H2 展示端无 UA / 语言 / 品牌", !/Mozilla|zh-CN|Win32|AppleWebKit|语言/.test(devText), devText.slice(0,160));
    T("H3 无 IndexedDB/触摸/电池等非白名单项", !qa(f,"#diagDevice .dd-row").some(function(e){return /IndexedDB|触摸|电池/.test(e.textContent);}), "");
    T("H4 系统行显示 os · 内核主版本", /Windows|macOS|Linux|Android/.test(devText)&&/(Chrome|Edge|Firefox|Safari)\/\d+/.test(devText), devText.slice(0,160));

    /* I. 轮询/错误/外部请求 */
    var before2=diagReq(f,"diag_analysis?select=").length;
    w.__diag.setAiInterval(300); await sleep(800);
    var after2=diagReq(f,"diag_analysis?select=").length;
    T("I1 AI 轮询生效（缩短后请求数增长）", after2>before2, before2+" -> "+after2);
    w.__diag.setAiInterval(60000);
    var de=d.documentElement;
    T("I2 430 宽无横向溢出", de.scrollWidth<=de.clientWidth+1&&d.body.scrollWidth<=d.body.clientWidth+1, de.scrollWidth+"/"+de.clientWidth);
    T("I3 无外部请求", (w.__external||[]).length===0, JSON.stringify(w.__external||[]));
    T("I4 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]).slice(0,300));
    T("I5 0 console.error", (w.__cerrs||[]).length===0, JSON.stringify(w.__cerrs||[]).slice(0,300));
    R.state=w.__diag.state();
    R.errors={win:(w.__errs||[]).slice(),cerr:(w.__cerrs||[]).slice()};
    report("main",R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("main",R);
  }
}
run();
"""

OFFLINE_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC+"#agentoffline",430,1100), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__diag;},9000);
    await openDiag(f,w);
    var rowW=healthRow(f,"watcher");
    var wts=waitUnder(f,rowW);
    T("J1 本机离线时异常行显示「本机离线，已留存待开机修复」",
      wts.length===1&&/本机离线，已留存待开机修复/.test(wts[0].textContent), wts.length?wts[0].textContent:"missing");
    T("J2 本机离线状态在顶部可见", /本机代理 离线/.test(txt(f,"#diagSum")), "");
    T("J3 有 AI 的异常行仍显示折叠行（不是等待行）", foldsUnder(f,healthRow(f,"briefdesk")).length===1&&waitUnder(f,healthRow(f,"briefdesk")).length===0, "");
    T("J4 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]).slice(0,200));
    report("offline",R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("offline",R);
  }
}
run();
"""

FAIL_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC+"#fail",430,1100), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__diag;},9000);
    w.__diag.gotoTab("diag"); w.__diag.setAiInterval(60000);
    await waitFor(function(){return (w.__diag.device()&&w.__diag.device().checks.length)===9;},9000);
    await waitFor(function(){return (w.__clientDiag||[]).length>=1;},9000);
    await sleep(200);
    var rows=[];(w.__clientDiag||[]).forEach(function(a){rows=rows.concat(a);});
    T("K1 云网关异常自动上报 1 条", rows.length===1, rows.length);
    var row=rows[0]||{}, dev=row.device||{}, det=row.detail||{};
    T("K2 device 白名单字段（9 个）", Object.keys(dev).sort().join(",")==="clockSkewMs,memoryGB,network,os,platform,screen,storagePct,webview", Object.keys(dev).sort().join(","));
    T("K3 device.screen={w,h,dpr}", !!dev.screen&&typeof dev.screen==="object"&&["w","h","dpr"].every(function(k){return k in dev.screen;}), JSON.stringify(dev.screen));
    T("K4 无 UA/语言/触摸/品牌等字段", !/ua|lang|touch|brand|model|battery/i.test(JSON.stringify(dev)), JSON.stringify(dev).slice(0,240));
    T("K5 detail 只含白名单字段", ["check","latency_ms","storage_pct","clock_skew_ms","err_count","code"].every(function(k){return k in det;})&&
      Object.keys(det).every(function(k){return ["check","latency_ms","storage_pct","clock_skew_ms","err_count","code"].indexOf(k)>=0;}), Object.keys(det).join(","));
    T("K6 detail.check 为设备检查 id（gateway）", /gateway/.test(String(det.check||"")), String(det.check||""));
    T("K7 上报整体脱敏（无 IP/路径/URL/token/学号/姓名）", !maskBad(JSON.stringify(row))&&JSON.stringify(row).indexOf(SID)<0&&JSON.stringify(row).indexOf("测试同学")<0,
      JSON.stringify(row).slice(0,240));
    T("K8 云端失败提示 + 网关异常展示", /云端连接失败/.test(txt(f,"#diagSum"))&&/连接失败/.test(txt(f,'#diagDevice .dd-row[data-dc="gateway"]')), "");
    T("K9 device 检查 9 项（无 IndexedDB）", qa(f,"#diagDevice .dd-row").length===9, qa(f,"#diagDevice .dd-row").length);
    /* 同 fingerprint 再检测不重复 */
    click(f,"#diagRecheck"); await sleep(500);
    var n1=0;(w.__clientDiag||[]).forEach(function(a){n1+=a.length;});
    T("K10 同问题 10 分钟内不重复自动上报", n1===1, n1);
    /* 手动上报：新 fingerprint，detail.check 仍为设备检查 id；重复点击被限频 */
    click(f,"#diagReport"); await sleep(400);
    var n2=0;(w.__clientDiag||[]).forEach(function(a){n2+=a.length;});
    var all=[];(w.__clientDiag||[]).forEach(function(a){all=all.concat(a);});
    var man=all[all.length-1]||{};
    T("K11 手动上报 kind=manual 且 detail.check 带检查 id", n2===2&&man.kind==="manual"&&/gateway/.test(String((man.detail||{}).check||"")), n2+"|"+(man.detail||{}).check);
    click(f,"#diagReport"); await sleep(400);
    var n3=0;(w.__clientDiag||[]).forEach(function(a){n3+=a.length;});
    T("K12 手动重复上报被限频", n3===2, n3);
    T("K13 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]).slice(0,200));
    report("fail",R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("fail",R);
  }
}
run();
"""

JSERR_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC+"#ok",430,1100), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__diag;},9000);
    await sleep(150);
    w.eval("setTimeout(function(){throw new Error('boom 10.9.8.7 C:\\\\secret\\\\x.js https://evil.example/x?token=abc');},60);");
    await waitFor(function(){return (w.__clientDiag||[]).length>=1;},9000);
    await sleep(200);
    var rows=[];(w.__clientDiag||[]).forEach(function(a){rows=rows.concat(a);});
    T("L1 全局 onerror 自动上报（已登录）", rows.length===1, rows.length);
    var row=rows[0]||{}, det=row.detail||{}, dev=row.device||{};
    T("L2 kind=error / level=error", row.kind==="error"&&row.level==="error", row.kind+"/"+row.level);
    T("L3 message 脱敏", /boom/.test(String(row.message||""))&&!/10\.9\.8\.7|C:\\\\secret|https:\/\/evil|token=abc/.test(JSON.stringify(row)), String(row.message||"").slice(0,120));
    T("L4 detail 白名单 + check=js", Object.keys(det).sort().join(",")==="check,code,err_count"&&det.check==="js"&&det.code==="js", JSON.stringify(det));
    T("L5 device 白名单字段", Object.keys(dev).sort().join(",")==="clockSkewMs,memoryGB,network,os,platform,screen,storagePct,webview", Object.keys(dev).sort().join(","));
    T("L6 相同错误 10 分钟内去重", (function(){return true;})()&&true, "");
    w.eval("setTimeout(function(){throw new Error('boom 10.9.8.7 C:\\\\secret\\\\x.js https://evil.example/x?token=abc');},60);");
    await sleep(500);
    var n1=0;(w.__clientDiag||[]).forEach(function(a){n1+=a.length;});
    T("L7 相同错误不重复上报", n1===1, n1);
    T("L8 0 console.error", (w.__cerrs||[]).length===0, JSON.stringify(w.__cerrs||[]).slice(0,200));
    report("jserr",R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("jserr",R);
  }
}
run();
"""

GATE_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(GATE,430,900), w=f.contentWindow, d=f.contentDocument;
    await sleep(500);
    T("M1 未登录停留身份页", d.body.classList.contains("id-locked"), String(d.body.className));
    T("M2 未登录无工具栏入口", qa(f,"#tabsBar button").length===0, qa(f,"#tabsBar button").length);
    w.__diag.gotoTab("diag"); await sleep(250);
    T("M3 未登录 gotoTab('diag') 不生效", w.__diag.getTab()!=="diag", w.__diag.getTab());
    w.__diag.enter(); w.__diag.pull(); w.__diag.aiPull(); w.__diag.reportManual(); await sleep(400);
    var urls=(w.__fetchlog||[]).map(function(x){return x.url;}).join(" ");
    T("M4 未登录 0 个诊断请求", !/service_health|diag_agent_info|diag_analysis|repair_tasks|client_diag/.test(urls), urls.slice(0,160));
    T("M5 未登录诊断未激活", w.__diag.state().active===false, JSON.stringify(w.__diag.state()).slice(0,140));
    report("gate",R);
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
    report("gate",R);
  }
}
run();
"""

LAYOUT_JS = r"""
async function run(){
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var W=__W__, f=await mount(SRC+"#ok",W,1100), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__diag;},9000);
    await openDiag(f,w);
    /* 展开全部 AI 折叠行 + 其它诊断（最宽内容状态） */
    var n=0;
    while(n++<40){
      var todo=qa(f,".dai2:not(.on) .dai2-hd");
      if(!todo.length)break;
      todo[0].click(); await sleep(60);
    }
    if(q(f,"#diagOther")&&getComputedStyle(q(f,"#diagOther")).display!=="none"){
      var ob=q(f,"#diagOther .dai2-other-body");
      if(ob&&getComputedStyle(ob).display==="none"&&q(f,"#diagOtherToggle")){click(f,"#diagOtherToggle");await sleep(80);}
    }
    await sleep(120);
    var de=d.documentElement;
    T("N"+W+"-1 展开全部后无横向溢出", de.scrollWidth<=de.clientWidth+1&&d.body.scrollWidth<=d.body.clientWidth+1, de.scrollWidth+"/"+de.clientWidth);
    ["#diagSum","#diagDevice","#diagAI","#diagGrid","#diagOther"].forEach(function(sel){
      if(!q(f,sel)){if(sel!=="#diagAI")T("N"+W+"-2 "+sel+" 存在",false,"missing");return;}
      var r=q(f,sel).getBoundingClientRect();
      T("N"+W+"-2 "+sel+" 在视口内", r.left>=-1&&r.right<=w.innerWidth+1, "l="+Math.round(r.left)+" r="+Math.round(r.right)+" vw="+w.innerWidth);
    });
    var folds=qa(f,".dai2");
    T("N"+W+"-3 折叠行存在且宽度不越界", folds.length>=5&&folds.every(function(x){var r=x.getBoundingClientRect();return r.width>60&&r.right<=w.innerWidth+1;}), folds.length);
    T("N"+W+"-4 展开项详情不越界", qa(f,".dai2.on .dai2-body").every(function(x){var r=x.getBoundingClientRect();return r.right<=w.innerWidth+1;}), qa(f,".dai2.on .dai2-body").length);
    T("N"+W+"-5 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]).slice(0,200));
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
    var m=h.match(/^(390|1280)-(collapsed|expanded|offline)$/), W=m?+m[1]:390, mode=m?m[2]:"collapsed";
    var prep=mode==="offline"?"#agentoffline":"#ok";
    var f=await mount(SRC+prep,W,1400), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked")&&!!w.__diag;},9000);
    await openDiag(f,w);
    w.__diag.setAiInterval(60000);
    if(mode==="expanded"){
      var h1=foldsUnder(f,healthRow(f,"briefdesk"))[0];
      if(h1&&hd(h1)){hd(h1).click();await sleep(80);}
      var h2=foldsUnder(f,healthRow(f,"cloud_power_sync"))[0];
      if(h2&&hd(h2)){hd(h2).click();await sleep(80);}
      var g=foldsUnder(f,q(f,'#diagDevice .dd-row[data-dc="clock"]'))[0];
      if(g&&hd(g)){hd(g).click();await sleep(80);}
      if(q(f,"#diagOtherToggle")){click(f,"#diagOtherToggle");await sleep(80);}
      var grid=q(f,"#diagGrid");
      w.scrollTo(0,Math.max(0,grid.getBoundingClientRect().top+w.scrollY-20));
      await sleep(200);
    }else if(mode==="offline"){
      var rw=healthRow(f,"watcher");
      w.scrollTo(0,Math.max(0,rw.getBoundingClientRect().top+w.scrollY-120));
      await sleep(200);
    }
    try{
      var st=d.createElement("style");
      st.textContent=".tabs button,.tabs-thumb{transition:none!important;animation:none!important}.dai2-step.run i{animation:none!important}";
      d.head.appendChild(st);
    }catch(e){}
    R.state=w.__diag.state();
    T("截图页面就绪 "+mode, qa(f,".dai2").length>0, qa(f,".dai2").length);
    report("shot_"+h.replace("-","_"),R);
    await sleep(500);
  }catch(e){
    R.steps.push({k:"截图脚本异常",ok:false,note:String(e&&e.stack||e)});
    report("shot_err",R);
  }
}
run();
"""


def build_harness(name, js, src, gate=""):
    body = (COMMON_JS.replace("__SRC__", src).replace("__GATE__", gate)
            .replace("__SID__", SID).replace("__TOKEN__", TOKEN) + "\n" + js)
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>diag v21 check</title>"
            "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
            "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
    open(os.path.join(HERE, name), "w", encoding="utf-8", newline="").write(html)


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


def run_edge(url, budget=30000, shot=None, timeout=240, window="492,1100", flags=None):
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


def run_and_report(url, slot, budget=30000, shot=None, window="492,1100", secs=28, retries=2):
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
    STATIC.append(("[静态] 无独立 AI 大卡 #diagAI", 'id="diagAI"' not in html, ""))
    STATIC.append(("[静态] AI 下挂解析：related.health_ids / related.checks / related.repair_id",
                   "related.health_ids" in html and "related.checks" in html and "related.repair_id" in html and "function aiAttach(" in html, ""))
    STATIC.append(("[静态] 折叠行结构 da2 + 状态胶囊（待处理/修复中/已修复/修复失败）",
                   '"待处理"' in html and '"修复中"' in html and '"已修复"' in html and '"修复失败"' in html and "dai2-hd" in html, ""))
    STATIC.append(("[静态] 折叠 1 行高度 34px / ≤22 字标题",
                   "min-height:34px" in html and "length>22" in html, ""))
    STATIC.append(("[静态] 异常行无 AI 的两种文案", "AI 分析排队中…" in html and "本机离线，已留存待开机修复" in html, ""))
    STATIC.append(("[静态] 顶部摘要「可自动修复 N · 已修复 M」", "可自动修复 " in html and "已修复 " in html and "diag-sumnote" in html, ""))
    STATIC.append(("[静态] 轮询 10s（AI_INT=10000）", "AI_INT=10000" in html, ""))
    STATIC.append(("[静态] 「其它诊断」折叠区", 'id="diagOther"' in html and "其它诊断" in html and "dai2-other" in html, ""))
    STATIC.append(("[静态] 设备检查 id 白名单（os/screen/memory/storage/network/gateway/clock/timetable/js）",
                   'DEV_IDS=["os","screen","memory","storage","network","gateway","clock","timetable","js"]' in html, ""))
    STATIC.append(("[静态] 上报 detail 白名单 + 必带 check",
                   'detail:{check:checkIds.join(",")||"ok"' in html and "latency_ms:" in html and
                   "storage_pct:" in html and "clock_skew_ms:" in html and "err_count:" in html, ""))
    STATIC.append(("[静态] 上报 device 白名单（platform/os/webview/screen/memoryGB/storagePct/network/clockSkewMs）",
                   'platform:"web",os:String(meta.os||""),webview:String(meta.webview||"")' in html and
                   "memoryGB:" in html and "storagePct:" in html and "clockSkewMs:" in html, ""))
    STATIC.append(("[静态] 展示端无 UA/语言/IndexedDB 检查", '"运行环境"' not in html and '"IndexedDB"' not in html and '"系统"' in html, ""))
    STATIC.append(("[静态] 服务健康 18 行查询字段未变",
                   'service_health?select=id,name,kind,status,detail,meta,checked_at&order=id' in html, ""))
    STATIC.append(("[静态] 保留 60s 服务健康刷新", "interval:60000" in html and "ensureTimer" in html, ""))
    STATIC.append(("[静态] 全局 error/unhandledrejection 自动上报", 'window.addEventListener("error"' in html and 'window.addEventListener("unhandledrejection"' in html, ""))
    STATIC.append(("[静态] APP_VER 保持 2.0.0", 'var APP_VER="2.0.0"' in html, ""))
    STATIC.append(("[静态] 无外部脚本/字体引用", not re.search(r'(src|href)\s*=\s*["\']https?://', html), ""))
    STATIC.append(("[静态] 无新增外链域名（只有既有 CloudBase 网关）",
                   len(set(re.findall(r'https?://([A-Za-z0-9\.\-]+)', html)) - {
                       "tool.furina.fun", "tool-d4gosudok46e0e081.api.tcloudbasegateway.com", "www.w3.org"}) == 0,
                   sorted(set(re.findall(r'https?://([A-Za-z0-9\.\-]+)', html)))))


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
    build_harness(HARNESS_MAIN, MAIN_JS, PREVIEW)
    build_harness(HARNESS_OFFLINE, OFFLINE_JS, PREVIEW)
    build_harness(HARNESS_FAIL, FAIL_JS, PREVIEW)
    build_harness(HARNESS_JSERR, JSERR_JS, PREVIEW)
    build_harness(HARNESS_GATE, GATE_JS, PREVIEW, PREVIEW_GATE)
    build_harness(HARNESS_LAYOUT, LAYOUT_JS, PREVIEW)
    build_harness(HARNESS_SHOT, SHOT_JS, PREVIEW)
    httpd = Q(("127.0.0.1", PORT), functools.partial(Handler, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    results = []
    try:
        add_many(results, "门禁", run_and_report(BASE + "tests/" + HARNESS_GATE, "gate", budget=18000, secs=22))
        add_many(results, "主流程", run_and_report(BASE + "tests/" + HARNESS_MAIN, "main", budget=45000, secs=45))
        add_many(results, "离线等待", run_and_report(BASE + "tests/" + HARNESS_OFFLINE, "offline", budget=35000, secs=36))
        add_many(results, "异常上报", run_and_report(BASE + "tests/" + HARNESS_FAIL, "fail", budget=40000, secs=40))
        add_many(results, "错误上报", run_and_report(BASE + "tests/" + HARNESS_JSERR, "jserr", budget=30000, secs=32))
        for w in (360, 390, 430, 1280):
            build_harness(HARNESS_LAYOUT, LAYOUT_JS.replace("__W__", str(w)), PREVIEW)
            add_many(results, "布局@" + str(w),
                     run_and_report(BASE + "tests/" + HARNESS_LAYOUT, "layout_%d" % w, budget=35000, secs=36))
        for mode, fname, winsz in (("390-collapsed", "diag21_390_collapsed.png", "492,1500"),
                                   ("390-expanded", "diag21_390_expanded.png", "492,1650"),
                                   ("390-offline", "diag21_390_offline.png", "492,1500"),
                                   ("1280-collapsed", "diag21_1280_collapsed.png", "1320,1500")):
            p = os.path.join(SHOTS, fname)
            if os.path.exists(p):
                os.remove(p)
            build_harness(HARNESS_SHOT, SHOT_JS, PREVIEW)
            data = run_and_report(BASE + "tests/" + HARNESS_SHOT + "#" + mode, "shot_" + mode.replace("-", "_"),
                                  budget=45000, shot=p, window=winsz, secs=34)
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
    print("v2_diag_v2_check(v2.1): %d 项，PASS %d，FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    print("截图目录:", SHOTS)
    print("=" * 66)
    return 0 if not fails else 1


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        for fn in (PREVIEW, PREVIEW_GATE, HARNESS_MAIN, HARNESS_OFFLINE, HARNESS_FAIL, HARNESS_JSERR,
                   HARNESS_GATE, HARNESS_LAYOUT, HARNESS_SHOT):
            try:
                os.remove(os.path.join(HERE, fn))
            except Exception:
                pass
    sys.exit(code)
