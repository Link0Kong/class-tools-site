# -*- coding: utf-8 -*-
"""v2 通知时间显示与识别 · 独立验收（契约 §7 A1–A9）

对象：
  - 展示层：`web/tools/notice-board-live-demo.html`（内嵌 GROUPS；env NTP_DEMO 可指定）
  - 数据层：`C:\\briefdesk\\data\\board-data.json`（env NTP_BOARD 可指定）
做法：
  1) 复制 demo 到临时目录，注入「固定 now（Date.now + new Date() 无参）+ 错误收集 + 断言脚本」，
     headless Edge 打开，同步 XHR 回传 JSON（不改源文件）；
  2) 断言里的期望标签由**独立参考实现**（本脚本 JS 内按契约 §2/§3 另行实现）算出，
     与产品 statusOf 做差分，不调用产品函数算期望，防「同错同过」；
  3) A1/A3/A4/A6 的数据部分在 Python 侧对 board-data.json 独立核对；
  4) A9 回归：顺序跑 v2_notice_data_check / v2_ui_check / v2_admin_check / overflow_check 430 / export_check，
     与改前基线记录（_qa_nottime/phase2/baseline_regression/summary.json）对照。
环境变量：
  NTP_DEMO  demo html 路径（默认 web/tools/notice-board-live-demo.html）
  NTP_BOARD board-data.json 路径（默认 C:\\briefdesk\\data\\board-data.json）
  NTP_NOW   固定 now ISO（默认 2026-11-05T23:00:00+08:00）
  NTP_A9    0=跳过 A9 回归（快速迭代用）
  NTP_EDGE  msedge 路径
输出：tests/_v2_notice_time_reports/probe.json + report_<ts>.json + report_<ts>.md（并更新 latest.md）
退出码 0 = A1–A9 全绿。

用法：
  cd C:\\Users\\Ko_Li\\.openclaw\\workspace\\web\\tools && python tests\\v2_notice_time_check.py
"""
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
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEMO = os.path.abspath(os.environ.get("NTP_DEMO") or os.path.join(ROOT, "notice-board-live-demo.html"))
BOARD = os.path.abspath(os.environ.get("NTP_BOARD") or r"C:\briefdesk\data\board-data.json")
NOW_ISO = os.environ.get("NTP_NOW") or "2026-11-05T23:00:00+08:00"
RUN_A9 = (os.environ.get("NTP_A9") or "1") != "0"
EDGE = os.environ.get("NTP_EDGE") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
VENV_PY = os.environ.get("NTP_PY") or r"C:\briefdesk\venv\Scripts\python.exe"
REPORT_DIR = os.path.join(HERE, "_v2_notice_time_reports")
BASELINE_REGRESSION = r"C:\briefdesk\data\_qa_nottime\phase2\baseline_regression\summary.json"
CN = timezone(timedelta(hours=8))

# ---------------------------------------------------------------- JS（展示层）
# 注入到 <head>：先于产品脚本执行，固定 now（含 new Date() 无参）
NOW_OVERRIDE_JS = r"""
<script>
(function(){
  try{
    var RealDate=Date;
    var FIXED=RealDate.parse("__NTP_NOW__");
    function QADate(){
      if(!(this instanceof QADate)) return new RealDate(FIXED).toString();
      if(arguments.length===0) return new RealDate(FIXED);
      if(arguments.length===1) return new RealDate(arguments[0]);
      var a=Array.prototype.slice.call(arguments);
      return new (Function.prototype.bind.apply(RealDate,[null].concat(a)))();
    }
    QADate.prototype=RealDate.prototype;
    QADate.now=function(){return FIXED;};
    QADate.parse=RealDate.parse;
    QADate.UTC=RealDate.UTC;
    window.Date=QADate;
    window.__QA_FIXED_NOW=FIXED;
  }catch(e){}
})();
window.__errs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||"error"));});
window.addEventListener("unhandledrejection",function(e){window.__errs.push("rej:"+String(e&&e.reason));});
</script>
"""

ERR_JS = r"""
<script>
window.__errs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||"error"));});
window.addEventListener("unhandledrejection",function(e){window.__errs.push("rej:"+String(e&&e.reason));});
</script>
"""

PROBE_JS = r"""
<script>
(function(){
var OUT={now:null,dateNow:null,nowText:"",steps:[],groups:[],chipTable:[],a7Exceptions:[],a8Hits:[],
         a8NoAnchor:[],domChips:[],targets:{},errs:[],counts:{}};
function P(k,ok,note){OUT.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
function norm(s){return String(s==null?"":s).replace(/\s+/g," ").trim();}
function pad2(n){return n<10?"0"+n:""+n;}
function parseTs(v){if(v==null||v==="")return null;var t=Date.parse(String(v));return isNaN(t)?null:t;}
var NOW=(window.__QA_FIXED_NOW!=null)?window.__QA_FIXED_NOW:Date.now();
OUT.now=NOW;OUT.dateNow=Date.now();OUT.nowText=new Date(NOW).toString();
// ---------------- 契约 §2.1 fmtWhen 参考实现（独立于产品） ----------------
function refFmtWhen(ts,now){
  if(ts==null||isNaN(ts))return "";
  if(ts<now){var d=new Date(ts);return pad2(d.getMonth()+1)+"-"+pad2(d.getDate())+" "+pad2(d.getHours())+":"+pad2(d.getMinutes());}
  var left=ts-now;
  if(left<3600000)return Math.max(1,Math.ceil(left/60000))+" 分钟后";
  if(left<86400000)return Math.max(1,Math.ceil(left/3600000))+" 小时后";
  if(left<7*86400000)return Math.max(1,Math.ceil(left/86400000))+" 天后";
  var d2=new Date(ts);return pad2(d2.getMonth()+1)+"-"+pad2(d2.getDate())+" "+pad2(d2.getHours())+":"+pad2(d2.getMinutes());
}
// ---------------- 契约 §0.2 _short_action 参考实现（与 build_notice_board._short_action 同源） ----------------
function refShortAction(a){
  var t=norm(a);if(!t)return "";
  var map={"报送姓名截止":"报送截止","活动开始":"开始","集合点名":"点名","签到签退":"签到","比赛开始":"比赛"};
  if(map[t])return map[t];
  return t.length>6?t.slice(0,6):t;
}
// ---------------- 契约 §2.2 statusOf label 参考实现（独立于产品） ----------------
function refStatus(g,now){
  if(g.recurrence&&g.recurrence.freq){
    var lab=norm(g.recurrence.label);
    return {key:"recur",label:lab?("长期安排 · "+lab):"长期安排"};
  }
  var ss=parseTs(g.signupStart),se=parseTs(g.signupEnd);
  if(ss!=null||se!=null){
    if(ss!=null&&now<ss)return {key:"signup",label:refFmtWhen(ss,now)+" 报名开始"};
    if(se!=null&&now<se)return {key:"signup",label:refFmtWhen(se,now)+" 报名截止"};
    if(se!=null)return {key:"signup",label:refFmtWhen(se,now)+" 报名截止"};
  }
  var real=parseTs(g.deadline);
  if(g.extensions&&g.extensions.length){
    var ext=g.extensions[g.extensions.length-1];
    if(ext&&ext.deadline)real=parseTs(ext.deadline);
  }
  if(real!=null){
    if(now>real&&g.alert)return {key:"alert",label:"已截止 · 有新名单"};
    return {key:"deadline",label:refFmtWhen(real,now)+" "+(refShortAction(g.deadlineAction)||"截止")};
  }
  var ev=parseTs(g.eventAt);
  if(ev!=null)return {key:"event",label:refFmtWhen(ev,now)+" "+(refShortAction(g.eventAction)||"开始")};
  return {key:"none",label:"无时间"};
}
var A7_TIME_RE=/^(?:[1-9]\d* 分钟后|[1-9]\d* 小时后|[1-9]\d* 天后|\d{2}-\d{2} \d{2}:\d{2}) .+$/;
var A7_EXCEPTION_RE=/^(无时间|长期安排( · .+)?|已处理|已截止 · 有新名单)$/;
var A7_BAN_RE=/(今天|明天|后天)/;
var A7_OLD=["已截止 · 自动完成","已结束 · 自动归档","已延长 ·"];
var REL_RE=/(今天|今日|今晚|明早|明天|明日|明晚|后天|大后天|本周[一二三四五六日天]|这周[一二三四五六日天]|下周[一二三四五六日天]|下星期[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天]|周[一二三四五六日天])/g;
function relHits(s){
  var out=[],m;REL_RE.lastIndex=0;
  while((m=REL_RE.exec(s))){
    out.push({word:m[0],snippet:s.slice(Math.max(0,m.index-16),Math.min(s.length,m.index+m[0].length+18))});
    if(out.length>=30)break;
  }
  return out;
}
var gs=(typeof GROUPS!=="undefined")?GROUPS:((window.GROUPS)||[]);
var byId={};gs.forEach(function(g){byId[g.id]=g;});
OUT.counts={groups:gs.length};
function cardOf(id){try{return document.querySelector('.gcard[data-gid="'+id+'"]');}catch(e){return null;}}
function domChip(id){var c=cardOf(id);var s=c?c.querySelector('.st'):null;return s?norm(s.textContent):null;}
function cardText(id){var c=cardOf(id);return c?norm(c.textContent):"";}
function anchorOf(g){ // 契约 §3：同一卡片取第一条 item 的 time（MM-DD HH:MM）解析发送时刻
  var items=g.items||[];
  for(var i=0;i<items.length;i++){
    var m=/^(\d{1,2})-(\d{2})[ T](\d{2}):(\d{2})$/.exec(norm(items[i].time));
    if(!m)continue;
    var y=new Date(NOW).getFullYear();
    var t=new Date(y,Number(m[1])-1,Number(m[2]),Number(m[3]),Number(m[4]),0,0).getTime();
    if(t>NOW+180*86400000)t=new Date(y-1,Number(m[1])-1,Number(m[2]),Number(m[3]),Number(m[4]),0,0).getTime();
    return t;
  }
  return null;
}
function textFields(g){
  var out=[];
  function add(field,s){if(typeof s==="string"&&norm(s))out.push({field:field,text:s});}
  add("aiSummary",g.aiSummary);
  (g.aiPoints||[]).forEach(function(p,i){add("aiPoints["+i+"]",p);});
  (g.aiSegments||[]).forEach(function(s,i){add("aiSegments["+i+"].text",s&&s.text);});
  (g.items||[]).forEach(function(it,i){
    add("items["+i+"].text",it&&it.text);
    add("items["+i+"].name",it&&it.name);
    add("items["+i+"].note",it&&it.note);
    ((it&&it.messages)||[]).forEach(function(m,j){add("items["+i+"].messages["+j+"].text",m&&m.text);});
  });
  (g.messages||[]).forEach(function(m,j){add("messages["+j+"].text",m&&m.text);});
  add("summary",g.summary);
  return out;
}
// 打开「原始消息」弹层取文本（contract §3 要求弹层也替换），随后关闭
function withModalText(gid,cb){
  var c=cardOf(gid);
  var btn=c?c.querySelector('[data-act="original"]'):null;
  if(!btn)return cb(null);
  try{
    btn.click();
    var box=document.querySelector('#mcard')||document.querySelector('.modal-card');
    var t=box?norm(box.textContent):null;
    var mo=document.querySelector('#modal');if(mo)mo.classList.remove('on');
    return cb(t);
  }catch(e){return cb(null);}
}
try{
  // ---------------- A0 固定 now / 基础 ----------------
  P("A0.1 固定 now 注入生效（2026-11-05 23:00 +08:00）",
    Math.abs(OUT.dateNow-NOW)<1000 && Math.abs(NOW-Date.parse("__NTP_NOW__"))<1000,
    "Date.now()="+OUT.dateNow+" / "+OUT.nowText);
  P("A0.2 页面内嵌 GROUPS 可读", gs.length>0, "groups="+gs.length);
  P("A0.3 页面已渲染卡片列表", document.querySelectorAll('.gcard').length>0,
    "rendered="+document.querySelectorAll('.gcard').length);

  // ---------------- A1 申报材料合并 ----------------
  function shenbaoGroups(){
    return gs.filter(function(g){
      var blob=norm(g.title)+" "+norm(g.aiSummary)+" "+(g.items||[]).map(function(it){return norm(it.text)+" "+norm(it.name);}).join(" ");
      return blob.indexOf("申报材料")>=0;
    });
  }
  var sb=shenbaoGroups();
  P("A1.1 申报材料只剩 1 张卡（已合并）", sb.length===1,
    "命中="+sb.length+" -> "+JSON.stringify(sb.map(function(g){return g.id+" | "+g.title;})));
  var sbg=sb.length?sb[0]:null;
  var sbItems=(sbg&&sbg.items)||[];
  var sbTimes=sbItems.map(function(it){return norm(it.time);});
  var sbTexts=sbItems.map(function(it){return norm(it.text)+" "+norm(it.name);}).join(" \n ");
  P("A1.2 合并卡含 ≥3 条原始 item", sbItems.length>=3, "items="+sbItems.length+" times="+JSON.stringify(sbTimes));
  P("A1.3 合并卡 items 同时覆盖 20:47 报送姓名 / 21:07 电子版 / 21:07 纸质版",
    sbTimes.some(function(t){return t.indexOf("20:47")>=0;}) &&
    sbTimes.some(function(t){return t.indexOf("21:07")>=0;}) &&
    /报送姓名|报送/.test(sbTexts) && /电子版/.test(sbTexts) && /纸质版/.test(sbTexts),
    "times="+JSON.stringify(sbTimes)+" texts="+sbTexts.slice(0,160));
  var sbCardAll="";
  var sbDom="";
  if(sbg){
    sbDom=cardText(sbg.id);
    withModalText(sbg.id,function(mt){sbCardAll=(sbDom||"")+" "+(mt||"");});
  }
  P("A1.4 申报材料卡内（含原始消息弹层）不再出现裸「明天/周日」",
    !!sbg && !/明天|明日|周日晚|周日/.test(sbCardAll.replace(/11-0[68]/g,"")),
    sbCardAll.slice(0,320));
  P("A1.5 申报材料卡内显示 11-06 / 11-08 日期",
    !!sbg && /11-06/.test(sbCardAll) && /11-08/.test(sbCardAll),
    "含11-06="+(/11-06/.test(sbCardAll))+" 含11-08="+(/11-08/.test(sbCardAll))+" 文本="+sbCardAll.slice(0,320));
  P("A1.6 申报材料卡内保留「中午前」「晚点名」语义",
    !!sbg && /中午前/.test(sbCardAll) && /晚点名/.test(sbCardAll), sbCardAll.slice(0,260));

  // ---------------- A2 申报材料主时间 ----------------
  var sbRef=sbg?refStatus(sbg,NOW):null;
  var sbProd=sbg?statusOf(sbg):null;
  var sbChip=sbg?domChip(sbg.id):null;
  OUT.targets.shenbao=sbg?{id:sbg.id,deadline:sbg.deadline,deadlineAction:sbg.deadlineAction,
      productLabel:sbProd&&sbProd.label,refLabel:sbRef&&sbRef.label,domChip:sbChip}:null;
  P("A2.1 主时间是 deadline+截止动作（参考实现=产品 label）",
    !!(sbg&&sbProd&&sbRef&&norm(sbProd.label)===norm(sbRef.label)),
    sbg?("产品="+(sbProd&&sbProd.label)+" / 参考="+(sbRef&&sbRef.label)):"无卡");
  P("A2.2 chip = 相对/绝对时间 + 报送截止（契约 §0.2 短动作）",
    !!(sbg&&/^(?:[1-9]\d* 小时后|\d{2}-\d{2} \d{2}:\d{2}) 报送截止$/.test(norm(sbChip||""))||/报送截止$/.test(norm(sbChip||""))),
    "chip="+sbChip+"（期望 13 小时后 报送截止，按固定 now）");
  P("A2.3 申报材料卡不得出现「今天 12:00」字样（P1 回归）",
    !!(sbg&&!/今天 12:00/.test((sbChip||"")+" "+(sbCardAll||""))),
    "chip="+sbChip);
  P("A2.4 data.deadlineAction 含「截止」", !!(sbg&&/截止/.test(norm(sbg.deadlineAction))),
    sbg?String(sbg.deadlineAction):"");

  // ---------------- A3 药膳报名优先 ----------------
  var med=null;gs.forEach(function(g){if(String(g.id||"").indexOf("g_qqm_7704134971497063025_c0")===0)med=g;});
  var medRef=med?refStatus(med,NOW):null,medProd=med?statusOf(med):null,medChip=med?domChip(med.id):null;
  var medTxt=med?cardText(med.id):"";
  OUT.targets.med=med?{id:med.id,signupStart:med.signupStart,signupEnd:med.signupEnd,deadline:med.deadline,
      eventAt:med.eventAt,productLabel:medProd&&medProd.label,refLabel:medRef&&medRef.label,domChip:medChip}:null;
  P("A3.1 药膳卡存在", !!med, med?med.id:"");
  P("A3.2 药膳主 chip = 报名类动作（报名开始/报名截止，§0.2 无「已」字后缀）",
    !!(med&&/(报名开始|报名截止)$/.test(norm(medChip||""))),
    "chip="+medChip+" 参考="+(medRef&&medRef.label));
  P("A3.3 药膳 statusOf 与参考实现一致（报名优先于活动/截止）",
    !!(med&&medProd&&medRef&&norm(medProd.label)===norm(medRef.label)),
    med?(norm(medProd&&medProd.label)+" vs "+norm(medRef&&medRef.label)):"");
  P("A3.4 药膳数据含 signupStart/signupEnd",
    !!(med&&(med.signupStart||med.signupEnd)),
    med?JSON.stringify({signupStart:med.signupStart,signupEnd:med.signupEnd}):"");
  P("A3.5 正文/摘要仍保留活动时间 11-07~11-14",
    !!(med&&/(11-07|11月7日)/.test(medTxt)&&/(11-14|11月14日)/.test(medTxt)),
    medTxt.slice(0,200));

  // ---------------- A4 手抄报（报名截止，§0.2 无「已」字后缀） ----------------
  var food=null;gs.forEach(function(g){
    var blob=norm(g.title)+" "+(g.items||[]).map(function(it){return norm(it.text)+norm(it.name);}).join(" ");
    if(blob.indexOf("手抄报")>=0)food=g;
  });
  var foodRef=food?refStatus(food,NOW):null,foodProd=food?statusOf(food):null,foodChip=food?domChip(food.id):null;
  OUT.targets.food=food?{id:food.id,deadline:food.deadline,signupStart:food.signupStart,signupEnd:food.signupEnd,
      productLabel:foodProd&&foodProd.label,refLabel:foodRef&&foodRef.label,domChip:foodChip}:null;
  P("A4.1 手抄报卡存在且 chip 以报名时间为准（报名截止）",
    !!(food&&/报名截止$/.test(norm(foodChip||""))),
    "chip="+foodChip+" 参考="+(foodRef&&foodRef.label));
  P("A4.2 手抄报 chip 不是 11-12 作品提交",
    !!(food&&!/^11-12/.test(norm(foodChip||""))), "chip="+foodChip);
  P("A4.3 手抄报 statusOf 与参考实现一致",
    !!(food&&foodProd&&foodRef&&norm(foodProd.label)===norm(foodRef.label)),
    food?(norm(foodProd&&foodProd.label)+" vs "+norm(foodRef&&foodRef.label)):"");

  // ---------------- A5 花名册发送者 ----------------
  var fileG=null;gs.forEach(function(g){if(String(g.id||"").indexOf("g_qqfile_1a81286a3a")===0)fileG=g;});
  var fileCard=fileG?cardOf(fileG.id):null;
  var filePub=fileCard?norm((fileCard.querySelector('.pubname')||{}).textContent||""):"";
  var fileBadge=fileCard?norm((fileCard.querySelector('.pubbadge')||{}).textContent||""):"";
  var fileTxt=fileG?cardText(fileG.id):"";
  OUT.targets.file=fileG?{id:fileG.id,senderName:fileG.senderName,senderRole:fileG.senderRole,
      senderBadge:fileG.senderBadge,fromName:fileG.fromName,fromRaw:fileG.fromRaw,
      pubname:filePub,pubbadge:fileBadge}:null;
  P("A5.1 花名册 senderName = 同学B", !!(fileG&&norm(fileG.senderName)==="同学B"),
    fileG?("senderName="+fileG.senderName+" role="+fileG.senderRole+" badge="+fileG.senderBadge):"");
  P("A5.2 花名册 senderRole/senderBadge 体现职务或班委",
    !!(fileG&&(/学习委员/.test(norm(fileG.senderRole))||/班委/.test(norm(fileG.senderBadge))||/学习委员/.test(fileBadge))),
    fileG?("role="+fileG.senderRole+" badge="+fileG.senderBadge+" DOMbadge="+fileBadge):"");
  P("A5.3 页面署名行为「同学B」，不显示「网名B」",
    !!(fileG&&filePub.indexOf("同学B")>=0&&fileTxt.indexOf("网名B")<0),
    "pubname="+filePub+" card含网名B="+(fileTxt.indexOf("网名B")>=0));

  // ---------------- A6 本人献血转发上板（Lead 口径：并入既有献血卡；独立新卡=FAIL） ----------------
  var xx=gs.filter(function(g){return JSON.stringify(g).indexOf("献血")>=0;});
  var xCard=xx.length?xx[0]:null;
  var hasSupText=false,hasMyLink=false,hasNote=false;
  (xCard&&xCard.items||[]).forEach(function(it){
    var blob=norm(it.text)+" "+norm(it.name)+" "+norm(it.from)+" "+norm(it.fromName)+" "+norm(it.note);
    var mine=/管理员/.test(blob);
    if(it.label==="补充通知"&&mine&&norm(it.time)==="11-05 10:18"&&/11月14日|下周六|献血/.test(blob))hasSupText=true;
    if(mine&&it.url&&/11月14日|下周六|献血/.test(blob))hasMyLink=true;
    if(mine&&/本人转发/.test(norm(it.note)))hasNote=true;
  });
  OUT.targets.xianxue=xx.map(function(g){return {id:g.id,title:g.title,source:g.source,eventAt:g.eventAt,
      eventAction:g.eventAction,supplement:g.supplement,updatedAt:g.updatedAt,itemCount:(g.items||[]).length,
      items:(g.items||[]).map(function(it){return {label:it.label,time:it.time,from:it.from,fromName:it.fromName,
          kind:it.kind,text:norm(it.text||it.name||'').slice(0,90),url:norm(it.url||'').slice(0,50),note:norm(it.note||'')};})};});
  P("A6.1 本人 11-05 10:18 献血转发已并入献血卡（补充通知 text item，管理员）",
    xx.length===1&&hasSupText,
    "献血组="+xx.length+" 补充通知text="+hasSupText+" card="+(xCard&&xCard.id));
  P("A6.2 献血卡含本人转发的可点链接 item（公众号 URL，note 含「本人转发」）",
    xx.length===1&&hasMyLink&&hasNote, "可点链接="+hasMyLink+" 本人转发note="+hasNote);
  P("A6.3 献血卡标题/摘要含「献血」，且无独立「本人转发」新卡（独立新卡=FAIL）",
    xx.length===1&&!!xCard&&/献血/.test(norm(xCard.title)+" "+norm(xCard.summary)+" "+norm(xCard.aiSummary)),
    "献血组数="+xx.length+" title="+(xCard&&xCard.title));
  P("A6.4 献血卡已渲染到列表（可见）", !!(xCard&&cardOf(xCard.id)),
    xCard?("可见="+!!cardOf(xCard.id)+" chip="+domChip(xCard.id)):"");

  // ---------------- A7 全部 chip 时间格式 ----------------
  var chipRows=[],bad=[];
  gs.forEach(function(g){
    var prod=null;try{prod=statusOf(g);}catch(e){prod={label:"ERR:"+String(e)};}
    var ref=refStatus(g,NOW);
    var label=norm(prod&&prod.label);
    var eq=(label===norm(ref.label));
    chipRows.push({id:g.id,cat:g.cat,title:g.title,label:label,ref:norm(ref.label),key:prod&&prod.key,eq:eq,
                   actionable:g.actionable,recur:!!(g.recurrence&&g.recurrence.freq),deadline:g.deadline,eventAt:g.eventAt,
                   timeLabel:g.timeLabel,signupStart:g.signupStart,signupEnd:g.signupEnd});
    if(!eq)bad.push({id:g.id,title:g.title,label:label,ref:norm(ref.label),type:"差分"});
    if(A7_BAN_RE.test(label))bad.push({id:g.id,title:g.title,label:label,type:"今天/明天混排"});
    A7_OLD.forEach(function(old){if(label.indexOf(old)>=0)bad.push({id:g.id,title:g.title,label:label,type:"旧文案:"+old});});
    var safe=label.replace(/^已截止 · 有新名单$/,"").replace(/^无时间$/,"").replace(/^长期安排.*$/,"");
    if(label!=="无时间"&&!/^长期安排/.test(label)&&label!=="已截止 · 有新名单"&&!/^已处理$/.test(label)){
      if(!A7_TIME_RE.test(label))bad.push({id:g.id,title:g.title,label:label,type:"格式不符A7"});
    }
    if(g.recurrence&&g.recurrence.freq){
      var c=cardOf(g.id);
      if(!c||!/下次/.test(norm(c.textContent)))bad.push({id:g.id,title:g.title,label:label,type:"长期安排缺「下次」行"});
      if(!/^长期安排( · .+)?$/.test(label))bad.push({id:g.id,title:g.title,label:label,type:"长期安排label"});
    }
  });
  OUT.chipTable=chipRows;
  P("A7.1 全部有时间的卡 chip 满足 ^(N 分钟后|N 小时后|N 天后|MM-DD HH:MM) .+$（长期安排/无时间/已截止有新名单例外）",
    !bad.some(function(b){return b.type==="格式不符A7";}),
    JSON.stringify(bad.filter(function(b){return b.type==="格式不符A7";}).slice(0,8)));
  P("A7.2 无「今天/明天/后天」混排（硬失败）", !bad.some(function(b){return b.type==="今天/明天混排";}),
    JSON.stringify(bad.filter(function(b){return b.type==="今天/明天混排";}).slice(0,8)));
  P("A7.3 无旧文案「已截止 · 自动完成」「已结束 · 自动归档」「已延长 ·」",
    !bad.some(function(b){return b.type.indexOf("旧文案")===0;}),
    JSON.stringify(bad.filter(function(b){return b.type.indexOf("旧文案")===0;}).slice(0,8)));
  P("A7.4 每组 chip 与独立参考实现一致（差分，共 "+gs.length+" 组）",
    !bad.some(function(b){return b.type==="差分";}),
    JSON.stringify(bad.filter(function(b){return b.type==="差分";}).slice(0,10)));
  P("A7.5 长期安排卡仍显示「下次」时间行", !bad.some(function(b){return b.type==="长期安排缺「下次」行";}),
    JSON.stringify(bad.filter(function(b){return b.type==="长期安排缺「下次」行";}).slice(0,5)));
  // DOM chip 与 statusOf 一致性（渲染路径没走偏）
  var domBad=[];
  Array.prototype.slice.call(document.querySelectorAll('.gcard[data-gid]')).forEach(function(c){
    var gid=c.getAttribute('data-gid'),g=byId[gid];if(!g)return;
    var s=c.querySelector('.st');if(!s)return;
    var t=norm(s.textContent),prod=null;try{prod=statusOf(g);}catch(e){prod={label:""};}
    if(t!==norm(prod.label))domBad.push({gid:gid,dom:t,status:norm(prod.label)});
  });
  OUT.domChips=domBad;
  P("A7.6 可见卡片 DOM chip 与 statusOf 一致", domBad.length===0, JSON.stringify(domBad.slice(0,8)));

  // A7.7（Lead 热修回归）：药膳手记 c1 数据修正后 chip 应为 11-05 18:00 报名截止
  var c1=null;gs.forEach(function(g){if(String(g.id||"").indexOf("g_qqm_7704134971497063025_c1")===0)c1=g;});
  var c1Chip=c1?domChip(c1.id):null,c1Prod=c1?statusOf(c1):null,c1Ref=c1?refStatus(c1,NOW):null;
  OUT.targets.c1=c1?{id:c1.id,deadline:c1.deadline,signupStart:c1.signupStart,signupEnd:c1.signupEnd,
      productLabel:c1Prod&&c1Prod.label,refLabel:c1Ref&&c1Ref.label,domChip:c1Chip}:null;
  P("A7.7 药膳手记 c1 chip = 11-05 18:00 报名截止（热修后，不再是 11-14 报名截止）",
    !!(c1&&norm(c1Chip)==="11-05 18:00 报名截止"&&norm(c1Prod&&c1Prod.label)===norm(c1Ref&&c1Ref.label)),
    "chip="+c1Chip+" 参考="+(c1Ref&&c1Ref.label)+" 数据 signup="+(c1&&c1.signupStart)+" ~ "+(c1&&c1.signupEnd));

  // ---------------- A8 相对日期替换（契约 §3：显示层） ----------------
  // 说明：契约 §3 是「显示层」替换；A8.1/A8.2 验渲染结果，A8.6/A8.7 验数据层（ai_brief 交付的
  // aiSummary/aiPoints/aiSegments 期望替换；item.text/messages 为原始消息，显示层替换即可）。
  var REL_HARD=/(今天|今日|今晚|明早|明天|明日|明晚|后天|大后天|本周[一二三四五六日天]|这周[一二三四五六日天]|下周[一二三四五六日天]|下星期[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天])/g;
  function annotationExempt(whole,offset,all){
    var b=whole.slice(Math.max(0,offset-12),offset);
    if(/\d{1,2}\s*月\s*\d{1,2}\s*日[^，。；;]{0,8}$/.test(b))return "绝对日期注记";
    if(/\d{1,2}\s*[\.\-]\s*\d{1,2}[^，。；;]{0,8}$/.test(b))return "绝对日期注记";
    if(/每[^，。；、\s]{0,6}$/.test(b))return "每周/长期语境";
    if(all==="今日"&&whole.slice(offset+2,offset+4)==="校园")return "专名今日校园";
    return "";
  }
  function scanRelHard(text){
    var out=[],m;REL_HARD.lastIndex=0;
    while((m=REL_HARD.exec(String(text||"")))){
      var word=m[0],off=m.index;
      if(annotationExempt(text,off,word))continue;
      out.push({word:word,snippet:String(text).slice(Math.max(0,off-16),Math.min(String(text).length,off+word.length+18))});
      if(out.length>=20)break;
    }
    // 无前缀「周X」：最近未来星期几，也要求显示层替换（排除绝对日期注记/每周语境）
    var bare=/(?<![下本这])(?:周|星期|礼拜)([一二三四五六日天])/g;
    var m2;bare.lastIndex=0;
    while((m2=bare.exec(String(text||"")))){
      var w=m2[0],o=m2.index;
      if(annotationExempt(text,o,w))continue;
      out.push({word:w,snippet:String(text).slice(Math.max(0,o-16),Math.min(String(text).length,o+w.length+18))});
      if(out.length>=20)break;
    }
    return out;
  }
  // A8.1 渲染后卡片正文（排除标题/来源/长期安排行/chip：标题与来源不在契约替换范围）
  var dispHits=[];
  Array.prototype.slice.call(document.querySelectorAll('.gcard[data-gid]')).forEach(function(c){
    var clone=c.cloneNode(true);
    clone.querySelectorAll('.gtitle,.recurline,.srcline,.ghd .st').forEach(function(n){n.parentNode.removeChild(n);});
    scanRelHard(norm(clone.textContent)).forEach(function(h){
      dispHits.push({gid:c.getAttribute('data-gid'),word:h.word,snippet:h.snippet});
    });
  });
  OUT.a8Hits=dispHits;
  P("A8.1 渲染后卡片正文（排除标题/来源/长期安排/chip）无剩余裸相对词", dispHits.length===0,
    "剩余="+dispHits.length+" "+JSON.stringify(dispHits.slice(0,10)));
  // A8.2 「原始消息」弹层：对有裸相对词的卡逐一打开核对（contract §3 要求弹层也替换）
  var modalHits=[],modalChecked=0,modalMissing=[];
  gs.forEach(function(g){
    var rawHas=false;
    textFields(g).forEach(function(f){if(!rawHas&&REL_HARD.test(f.text)){rawHas=true;}});
    if(!rawHas)return;
    var c=cardOf(g.id),btn=c?c.querySelector('[data-act="original"]'):null;
    if(!btn){modalMissing.push(g.id);return;}
    withModalText(g.id,function(mt){
      modalChecked++;
      if(mt==null){modalMissing.push(g.id);return;}
      var t=norm(mt);
      [g.source,g.group].forEach(function(x){if(x)t=t.split(norm(x)).join(" ");});
      scanRelHard(t).forEach(function(h){modalHits.push({gid:g.id,word:h.word,snippet:h.snippet});});
    });
  });
  P("A8.2 「原始消息」弹层文本无剩余裸相对词（核对 "+modalChecked+" 张有裸词的卡）", modalHits.length===0,
    "剩余="+modalHits.length+" 未找到弹层="+JSON.stringify(modalMissing.slice(0,5))+" "+JSON.stringify(modalHits.slice(0,10)));
  // A8.3 申报材料锚点=11-05 20:47 → 明天=11-06，周日=11-08
  P("A8.3 申报材料「明天中午前」→ 11-06 中午前、「周日晚点名」→ 11-08 晚点名（整卡同一锚点）",
    !!sbg&&/11-06\s*中午前/.test(sbCardAll.replace(/\s+/g," "))&&/11-08\s*晚点名/.test(sbCardAll.replace(/\s+/g," ")),
    sbCardAll.slice(0,380));
  if(sbg){
    withModalText(sbg.id,function(mt){
      P("A8.4 「原始消息」弹层文本已替换相对日期", mt!=null&&!/明天|明日|周日晚|周日晚点名/.test(mt),
        mt==null?"未找到原始消息按钮/弹层":norm(mt).slice(0,240));
    });
  }else{
    P("A8.4 「原始消息」弹层文本已替换相对日期", false, "无申报材料卡");
  }
  // A8.5 无锚点卡单列（契约 §3：解析失败/无锚点→原样显示，不报错）
  var noAnchor=[];
  gs.forEach(function(g){if(anchorOf(g)==null)noAnchor.push({id:g.id,title:g.title});});
  OUT.a8NoAnchor=noAnchor;
  P("A8.5 无 item.time 锚点卡片（白名单）", true,
    noAnchor.length?JSON.stringify(noAnchor):"（白名单为空，全部卡有锚点）");
  // A8.6 数据层：aiSummary/aiPoints/aiSegments（pipeline ai_brief 负责替换）应为 0
  var dataHitsSum=[],dataHitsItem=[],dataHitsLegacy=[];
  gs.forEach(function(g){
    var fields=textFields(g);
    fields.forEach(function(f){
      var isSum=/^(aiSummary|aiPoints\[|aiSegments\[)/.test(f.field);
      var isLegacy=(f.field==="summary"); /* 旧字段 summary：不在契约 §3 作用对象，模板有 aiSummary 时不显示 */
      scanRelHard(f.text).forEach(function(h){
        var rec={gid:g.id,title:g.title,field:f.field,word:h.word,snippet:h.snippet};
        if(isSum)dataHitsSum.push(rec);else if(isLegacy)dataHitsLegacy.push(rec);else dataHitsItem.push(rec);
      });
    });
  });
  P("A8.6 数据层 aiSummary/aiPoints/aiSegments 无裸相对词（ai_brief 交付，Lead 口径「预期 0」）",
    dataHitsSum.length===0,
    "剩余="+dataHitsSum.length+" "+JSON.stringify(dataHitsSum.slice(0,10)));
  P("A8.7 数据层 item.text/messages + 旧字段 summary 保留原始文本（契约 §3 为显示层替换，仅记录）", true,
    "item/messages 剩余="+dataHitsItem.length+"，旧 summary 剩余="+dataHitsLegacy.length+
    "（显示层已由 A8.1/A8.2 覆盖）");

  // ---------------- 其它 ----------------
  OUT.errs=window.__errs||[];
  P("A9.0 页面 0 JS 报错", OUT.errs.length===0, JSON.stringify(OUT.errs).slice(0,300));
}catch(e){
  P("脚本异常",false,String(e&&e.stack||e));
}
try{
  var x=new XMLHttpRequest();x.open("POST","/_report?slot=probe",false);
  x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(OUT));
}catch(e){}
})();
</script>
"""


# ---------------------------------------------------------------- Python 侧数据断言
def read_demo_groups(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"var GROUPS\s*=\s*(\[)", raw)
    if not m:
        return None, raw
    dec = json.JSONDecoder()
    obj, _ = dec.raw_decode(raw[m.start(1):])
    return obj, raw


def read_board(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def dt(v):
    """ISO → datetime（+08:00）；解析失败 None。"""
    if v in (None, ""):
        return None
    s = str(v).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try:
            d = datetime.strptime(s, "%Y-%m-%dT%H:%M")
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=CN)
    return d


def contains_any(blob, words):
    return any(w in blob for w in words)


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def gblob(g):
    parts = [norm(g.get("title")), norm(g.get("aiSummary")), norm(g.get("summary"))]
    for it in g.get("items") or []:
        parts += [norm(it.get("text")), norm(it.get("name")), norm(it.get("note"))]
    return " ".join(p for p in parts if p)


def py_data_steps(board, now):
    """A1/A2/A3/A4/A6 数据侧 + 新字段核对。返回 steps。"""
    steps = []

    def S(k, ok, note=""):
        steps.append({"k": k, "ok": bool(ok), "note": str(note)})

    if not board:
        S("D0 board-data.json 可读", False, BOARD)
        return steps
    groups = board.get("groups") or []
    S("D0 board-data.json 可读", True, "groups=%d generatedAt=%s" % (len(groups), board.get("generatedAt")))
    by_id = {str(g.get("id")): g for g in groups}

    # ---- A1 数据：申报材料合并为 1 组
    cand = [g for g in groups if "申报材料" in gblob(g)]
    S("D1.1 申报材料在 board-data 中只剩 1 组（已合并）", len(cand) == 1,
      "命中=%d -> %s" % (len(cand), [(g.get("id"), g.get("title")) for g in cand]))
    if cand:
        g = cand[0]
        items = g.get("items") or []
        times = [norm(it.get("time")) for it in items]
        blob = gblob(g)
        S("D1.2 合并组 items ≥3（20:47 报送姓名 / 21:07 电子版 / 21:07 纸质版）",
          len(items) >= 3 and any("20:47" in t for t in times) and any("21:07" in t for t in times)
          and contains_any(blob, ["报送姓名", "报送"]) and "电子版" in blob and "纸质版" in blob,
          "items=%d times=%s" % (len(items), times))
        d = dt(g.get("deadline"))
        S("D1.3 合并组保留较早已有 deadline 2026-11-06 12:00（契约 §6.4）",
          d is not None and d.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-11-06 12:00",
          "deadline=%s" % g.get("deadline"))
        S("D1.4 合并组 deadlineAction 含「截止」", "截止" in norm(g.get("deadlineAction")),
          "deadlineAction=%s" % g.get("deadlineAction"))
        S("D1.5 标题/摘要覆盖两件事（电子版+纸质版 或 报送+提交）",
          contains_any(norm(g.get("title")) + norm(g.get("aiSummary")), ["电子版", "纸质版", "报送", "提交"]),
          "%s | %s" % (g.get("title"), norm(g.get("aiSummary"))[:80]))

    # ---- A2 数据：deadline 11-06 12:00 + deadlineAction
    g5396 = by_id.get("g_ait_5396a55f24") or next(
        (g for g in groups if "g_ait_5396a55f24" in str(g.get("id"))), None)
    if g5396:
        d = dt(g5396.get("deadline"))
        S("D2.1 申报材料 deadline=2026-11-06 12:00", d is not None and d.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-11-06 12:00",
          str(g5396.get("deadline")))
        S("D2.2 申报材料 deadlineAction 含「截止」", "截止" in norm(g5396.get("deadlineAction")),
          str(g5396.get("deadlineAction")))
    else:
        S("D2.1 申报材料 id=g_ait_5396a55f24 存在", False, "合并后 id 可能变化，先按旧 id 检查")

    # ---- A3 数据：药膳 signup 窗口
    med = next((g for g in groups if str(g.get("id", "")).startswith("g_qqm_7704134971497063025_c0")), None)
    if med:
        ss, se = dt(med.get("signupStart")), dt(med.get("signupEnd"))
        S("D3.1 药膳含 signupStart/signupEnd（至少 signupEnd）", ss is not None or se is not None,
          "signupStart=%s signupEnd=%s" % (med.get("signupStart"), med.get("signupEnd")))
        S("D3.2 药膳报名窗口落在 2026-11-07（12:00/18:00）",
          (ss is not None and ss.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-11-07 12:00") or
          (se is not None and se.astimezone(CN).strftime("%Y-%m-%d %H:%M") in ("2026-11-07 18:00", "2026-11-07 12:00")),
          "signup=%s ~ %s" % (med.get("signupStart"), med.get("signupEnd")))
        S("D3.3 药膳 deadline 仍保留（活动/作品语义，不删）", med.get("deadline") not in (None, ""),
          str(med.get("deadline")))
    else:
        S("D3.1 药膳卡存在", False, "")

    # ---- A4 数据：手抄报 signupEnd 已过
    food = next((g for g in groups if "手抄报" in gblob(g)), None)
    if food:
        se = dt(food.get("signupEnd"))
        S("D4.1 手抄报含 signupStart/signupEnd（报名 11-03 12:00→20:30）",
          food.get("signupStart") is not None or se is not None,
          "signupStart=%s signupEnd=%s" % (food.get("signupStart"), food.get("signupEnd")))
        S("D4.2 手抄报 signupEnd 已过（能显示「报名截止」，不得被误解析成 11-12 作品提交）",
          se is not None and se < now,
          "signupEnd=%s now=%s" % (food.get("signupEnd"), now.isoformat()))
        S("D4.3 手抄报 deadline 仍保作品提交 11-12 20:00",
          dt(food.get("deadline")) is not None and dt(food.get("deadline")).astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-11-12 20:00",
          str(food.get("deadline")))
    else:
        S("D4.1 手抄报卡存在", False, "")

    # ---- A5 数据：花名册发送者映射
    fileg = next((g for g in groups if str(g.get("id", "")).startswith("g_qqfile_1a81286a3a")), None)
    if fileg:
        S("D5.1 花名册 fromName=同学B", norm(fileg.get("senderName")) == "同学B" or norm(fileg.get("fromName")) == "同学B",
          "senderName=%s fromName=%s" % (fileg.get("senderName"), fileg.get("fromName")))
        S("D5.2 花名册 fromRole=学习委员 或 fromBadge=班委",
          "学习委员" in norm(fileg.get("senderRole")) or "班委" in norm(fileg.get("senderBadge")),
          "senderRole=%s senderBadge=%s" % (fileg.get("senderRole"), fileg.get("senderBadge")))
        S("D5.3 保留 fromRaw（原始网名，调试用，前端不显示）", True,
          "fromRaw=%s" % fileg.get("fromRaw"))
    else:
        S("D5.1 花名册卡存在", False, "")

    # ---- A6 数据：本人献血转发并入既有献血卡（Lead 口径：独立新卡=FAIL）
    xx = [g for g in groups if "献血" in json.dumps(g, ensure_ascii=False)]
    S("D6.1 board-data 中献血通知仅 1 组（本人转发并入既有卡，无独立新卡）", len(xx) == 1,
      "献血组=%s" % [(g.get("id"), g.get("title"), g.get("source")) for g in xx])
    if len(xx) == 1:
        g = xx[0]
        its = g.get("items") or []

        def itblob(it):
            return (norm(it.get("text")) + " " + norm(it.get("name")) + " " + norm(it.get("from"))
                    + " " + norm(it.get("fromName")) + " " + norm(it.get("note")))

        sup_text = [it for it in its if norm(it.get("label")) == "补充通知" and "管理员" in itblob(it)
                    and norm(it.get("time")) == "11-05 10:18"
                    and contains_any(itblob(it), ["11月14日", "下周六", "献血"])]
        my_link = [it for it in its if "管理员" in itblob(it) and norm(it.get("url"))
                   and "mp.weixin" in norm(it.get("url"))]
        note_ok = any("本人转发" in norm(it.get("note")) for it in its)
        S("D6.2 献血卡标题/摘要含「献血」",
          "献血" in norm(g.get("title")) + norm(g.get("summary")) + norm(g.get("aiSummary")),
          "%s | %s" % (g.get("title"), norm(g.get("aiSummary"))[:80]))
        S("D6.3 献血卡含本人 10:18「补充通知」文本 item（11月14日 献血活动）", len(sup_text) >= 1,
          json.dumps([{"time": it.get("time"), "from": it.get("from"),
                       "text": norm(it.get("text"))[:40]} for it in sup_text], ensure_ascii=False))
        S("D6.4 献血卡含本人转发的可点公众号链接 item（note 含「本人转发」）", len(my_link) >= 1 and note_ok,
          "link=%d note本人转发=%s" % (len(my_link), note_ok))
        ev = dt(g.get("eventAt"))
        S("D6.5 献血卡 eventAt=2026-11-14 且 eventAction=开始（§0.2 短动作，chip 可显示「开始」）",
          ev is not None and ev.astimezone(CN).strftime("%Y-%m-%d") == "2026-11-14"
          and "开始" in norm(g.get("eventAction")),
          "eventAt=%s eventAction=%s" % (g.get("eventAt"), g.get("eventAction")))
        steps.append({"k": "D6.5b 献血卡类型（报告注明）", "ok": True, "note": "merged into " + str(g.get("id"))})
    # ai-triage-state processed：isSend=1 消息 key 是否已被采集
    state_p = r"C:\briefdesk\data\ai-triage-state.json"
    try:
        state = json.load(open(state_p, encoding="utf-8"))
        proc = set((state.get("processed") or {}).keys())
        keys = [k for k in proc if k.startswith("qq:823917023:")]
        hit = "qq:823917023:7704506055794865211" in proc or "qq:823917023:7704506031235373224" in proc
        S("D6.6 ai-triage-state.processed 含本人 10:18 献血消息 key（isSend=1 不再跳过）", hit,
          "该群 processed key 数=%d；目标 key 在=%s" % (len(keys), hit))
    except Exception as e:  # noqa: BLE001
        S("D6.6 ai-triage-state.processed 读取", False, str(e)[:120])

    # ---- D8（Lead 热修回归）：药膳手记 c1 时间字段
    c1 = next((g for g in groups if str(g.get("id", "")).startswith("g_qqm_7704134971497063025_c1")), None)
    if c1:
        ss8, se8, dl8 = dt(c1.get("signupStart")), dt(c1.get("signupEnd")), dt(c1.get("deadline"))
        S("D8.1 药膳手记 c1 signupStart=11-05 12:00 / signupEnd=11-05 18:00（不再被错刷成 11-14 23:59）",
          ss8 is not None and se8 is not None
          and ss8.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-11-05 12:00"
          and se8.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-11-05 18:00",
          "signup=%s ~ %s" % (c1.get("signupStart"), c1.get("signupEnd")))
        S("D8.2 药膳手记 c1 deadline=11-05 18:00 且 deadlineAction=报名截止",
          dl8 is not None and dl8.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-11-05 18:00"
          and "报名截止" in norm(c1.get("deadlineAction")),
          "deadline=%s action=%s" % (c1.get("deadline"), c1.get("deadlineAction")))
    else:
        S("D8.1 药膳手记 c1 存在", False, "g_qqm_7704134971497063025_c1")
    # ---- 新字段总体核对
    has_fields = [g for g in groups if any(g.get(k) not in (None, "") for k in
                                          ("deadlineAction", "eventAction", "signupStart", "signupEnd"))]
    S("D7.1 board-data 已产生新时间字段（deadlineAction/eventAction/signupStart/signupEnd）",
      len(has_fields) >= 3, "带新字段组=%d/%d" % (len(has_fields), len(groups)))
    S("D7.2 deadlineAction 全部含「截止」（契约 §1）",
      all(("截止" in norm(g.get("deadlineAction"))) for g in groups if norm(g.get("deadlineAction"))),
      "样例=%s" % [g.get("deadlineAction") for g in has_fields[:6]])
    S("D7.3 signupStart/signupEnd 为 ISO+08:00 或 null",
      all(dt(g.get("signupStart")) is not None or g.get("signupStart") in (None, "") for g in groups)
      and all(dt(g.get("signupEnd")) is not None or g.get("signupEnd") in (None, "") for g in groups),
      "")
    return steps


# ---------------------------------------------------------------- 运行 headless Edge
class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        qs = urllib.parse.urlparse(self.path).query
        m = re.search(r"slot=([A-Za-z0-9_\-]+)", qs)
        slot = m.group(1) if m else "default"
        os.makedirs(REPORT_DIR, exist_ok=True)
        with open(os.path.join(REPORT_DIR, slot + ".json"), "wb") as f:
            f.write(body)
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


def run_edge(url, budget=30000, timeout=240):
    prof = tempfile.mkdtemp(prefix="edgeprof_")
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=492,940",
            "--virtual-time-budget=%d" % budget, "--user-data-dir=" + prof, url]
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout)
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def run_probe():
    """返回 JS 探针报告 dict。"""
    raw = open(DEMO, encoding="utf-8", errors="replace").read()
    override = NOW_OVERRIDE_JS.replace("__NTP_NOW__", NOW_ISO)
    if "</head>" in raw:
        raw = raw.replace("</head>", override + "</head>", 1)
    else:
        raw = override + raw
    if "</body>" in raw:
        raw = raw.replace("</body>", PROBE_JS.replace("__NTP_NOW__", NOW_ISO) + "</body>", 1)
    else:
        raw += PROBE_JS.replace("__NTP_NOW__", NOW_ISO)

    for f in ("probe.json",):
        try:
            os.remove(os.path.join(REPORT_DIR, f))
        except Exception:
            pass
    tmp = tempfile.mkdtemp(prefix="qanottime_")
    srv = None
    try:
        with open(os.path.join(tmp, "demo.html"), "w", encoding="utf-8", newline="") as f:
            f.write(raw)
        os.chdir(tmp)
        srv = Q(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/demo.html" % port
        run_edge(url)
        p = os.path.join(REPORT_DIR, "probe.json")
        data = None
        t0 = time.time()
        while time.time() - t0 < 30:
            if os.path.exists(p):
                time.sleep(0.25)
                try:
                    data = json.load(open(p, encoding="utf-8"))
                    break
                except Exception:
                    time.sleep(0.3)
            time.sleep(0.2)
        return data
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- A9 回归
REGRESSIONS = [
    ("v2_notice_data_check", ["tests\\v2_notice_data_check.py"]),
    ("v2_ui_check", ["tests\\v2_ui_check.py"]),
    ("v2_admin_check", ["tests\\v2_admin_check.py"]),
    ("overflow_check_430", ["tests\\overflow_check.py", "430"]),
    ("export_check", ["tests\\export_check.py"]),
]


def run_a9():
    steps, details = [], []
    base = {}
    try:
        base = json.load(open(BASELINE_REGRESSION, encoding="utf-8")).get("tests") or []
        base = {b["name"]: b for b in base}
    except Exception:
        base = {}
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    reg_dir = os.path.join(REPORT_DIR, "regression")
    os.makedirs(reg_dir, exist_ok=True)
    for name, args in REGRESSIONS:
        logp = os.path.join(reg_dir, name + ".log")
        t0 = time.time()
        try:
            r = subprocess.run([VENV_PY] + args, cwd=ROOT, capture_output=True, timeout=900, env=env)
            out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
            code = r.returncode
        except subprocess.TimeoutExpired:
            out, code = "TIMEOUT", -9
        dt_ = round(time.time() - t0, 1)
        open(logp, "w", encoding="utf-8").write(out)
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-4:]
        b = base.get(name)
        base_note = ("；改前基线：%s" % ("PASS" if b and b.get("exit") == 0 else ("FAIL" if b else "无记录")))
        hint = ""
        if code != 0 and name == "v2_notice_data_check":
            low = out
            hint = "；注意：若仅 D1/D9–D16 等旧断言因「合并/药膳字段变化」失败，属断言需更新（Lead 决定是否改产品测试），QA 未擅改"
            details.append({"test": name, "exit": code, "tail": tail, "needsUpdateMaybe": True})
        else:
            details.append({"test": name, "exit": code, "tail": tail})
        steps.append({"k": "A9.%d 回归 %s" % (len(steps) + 1, name), "ok": code == 0,
                      "note": "exit=%s %.1fs%s%s ; tail=%s" % (code, dt_, base_note, hint, " | ".join(tail[-2:]))})
    steps.append({"k": "A9.6 回归 5 项全部通过（0 退出码）", "ok": all(d["exit"] == 0 for d in details),
                  "note": "PASS=%d/5" % sum(1 for d in details if d["exit"] == 0)})
    return steps, details


# ---------------------------------------------------------------- 报告
HINTS = {
    "A1": "检查 ai_triage supplements sameEvent 合并（20:47 报送提醒 + 21:07 电子版/纸质版）与 builder 合并逻辑；最小复现已看 board-data.json 中「申报材料」组数与 items。",
    "A2": "检查 statusOf deadline 分支是否用 deadlineAction，且 fmtWhen 按 24h/7d 分段、不再硬编码「今天」；复现：固定 now=11-05T23:00 看 5396 卡 chip。",
    "A3": "检查 builder 是否写入 signupStart/signupEnd，statusOf 是否「报名优先」先于 deadline/eventAt；复现：药膳 c0 卡 chip。",
    "A4": "检查「收集表报名时间 11月3日12:00-20:30」是否被正确解析为 signupEnd（不要误用 11-12 作品提交截止）；复现：g_food 卡 chip。",
    "A5": "检查 class-identities/class-aliases 的「网名B」→同学B匹配（_person_clean/最长别名包含）；复现：g_qqfile_1a81286a3a 卡 publine。",
    "A6": "检查 ai_triage 本人转发 rescue（isSelf 聚类 → 同主题 supplements 并入）：应并入 g_ait_d3117057d2（补充通知 text+link，note 含「本人转发」）而不是独立新卡；若出现独立献血卡=FAIL。复现：board-data 里数「献血」组数应=1。",
    "A7": "检查 statusOf label 组装是否统一「时间 动作」、fmtWhen 分段边界（1h/24h/7d）、去掉「今天/明天」与「已截止·自动完成/已结束·自动归档/已延长」旧文案。",
    "A8": "检查显示层相对日期替换：作用对象 aiSummary/aiPoints/aiSegments/item.text/messages/原始消息弹层，锚点=该卡第一条 item.time；复现：申报材料「明天中午前/周日晚点名」。",
    "A9": "回归失败先看 tests/_v2_notice_time_reports/regression/<name>.log；若是旧断言随新数据变化，报告给 Lead 决定是否更新产品测试。",
}


def build_report(steps, js, data_steps, a9_steps, a9_details):
    all_steps = list(steps) + list(data_steps)
    if RUN_A9:
        all_steps += list(a9_steps)
    total = len(all_steps)
    passed = sum(1 for s in all_steps if s["ok"])
    now = datetime.now(CN)
    lines = ["# 通知时间显示与识别 · 独立验收报告（契约 §7 A1–A9）", "",
             "- 生成时间：%s" % now.strftime("%Y-%m-%d %H:%M:%S"),
             "- 被测 demo：`%s`（sha256 %s）" % (DEMO, sha256(DEMO)),
             "- 被测 board-data：`%s`（sha256 %s）" % (BOARD, sha256(BOARD)),
             "- 固定 now：`%s`（注入 Date.now + new Date() 无参）" % NOW_ISO,
             "- 结果：**%d/%d PASS，%d FAIL**%s" % (passed, total, total - passed,
                                                  "（A9 回归未跑）" if not RUN_A9 else ""), ""]
    # A1–A9 汇总
    lines += ["## A1–A9 汇总", "", "| 用例 | 结果 | 关键信息 |", "|---|---|---|"]
    groups = {}
    for s in all_steps:
        gid = s["k"].split(" ")[0].split(".")[0]
        groups.setdefault(gid, []).append(s)
    for gid in ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "A9"]:
        if gid not in groups:
            continue
        gs_ = groups[gid]
        ok = all(x["ok"] for x in gs_)
        first_fail = next((x for x in gs_ if not x["ok"]), None)
        note = (first_fail["k"] + " | " + first_fail["note"][:120]) if first_fail else (
            gs_[0]["note"][:120] if gs_ else "")
        lines.append("| %s | %s | %s |" % (gid, "PASS" if ok else "FAIL", note.replace("|", "/")))
    lines += ["", "## 逐项明细", ""]
    for s in all_steps:
        mark = "PASS" if s["ok"] else "FAIL"
        lines.append("- [%s] %s%s" % (mark, s["k"], (" — `" + s["note"] + "`") if s["note"] else ""))
    # 失败项与定位建议
    fails = [s for s in all_steps if not s["ok"]]
    lines += ["", "## 失败项与定位建议（QA 不直接改产品）", ""]
    if not fails:
        lines.append("- 无")
    else:
        for s in fails:
            gid = s["k"].split(" ")[0].split(".")[0]
            hint = HINTS.get(gid, "见明细")
            lines.append("- **%s**：%s" % (s["k"], (s["note"] or "")[:400]))
            lines.append("  - 定位建议：%s" % hint)
    # 数据侧细节
    lines += ["", "## A7 全量 chip 表（产品 vs 参考实现）", "", "| id | cat | 产品 label | 参考 label | 一致 |", "|---|---|---|---|---|"]
    for c in (js or {}).get("chipTable", []):
        lines.append("| %s | %s | %s | %s | %s |" % (c.get("id"), c.get("cat"), c.get("label"), c.get("ref"),
                                                    "Y" if c.get("eq") else "**N**"))
    lines += ["", "## A8 剩余裸相对词（有锚点卡）", "```json",
              json.dumps((js or {}).get("a8Hits", []), ensure_ascii=False, indent=1)[:6000], "```"]
    lines += ["", "## A8 无锚点白名单", "```json",
              json.dumps((js or {}).get("a8NoAnchor", []), ensure_ascii=False, indent=1)[:3000], "```"]
    lines += ["", "## 关键卡数据（JS 侧观测）", "```json",
              json.dumps((js or {}).get("targets", {}), ensure_ascii=False, indent=1)[:6000], "```"]
    if RUN_A9:
        lines += ["", "## A9 回归明细", ""]
        for d in a9_details:
            lines.append("- %s：exit=%s%s；tail=%s" % (d["test"], d["exit"],
                                                       "（疑似产品测试断言需更新）" if d.get("needsUpdateMaybe") else "",
                                                       " | ".join(d.get("tail", [])[-2:])))
    lines += ["", "## 证据/产物", "- probe 原始 JSON：`%s`" % os.path.join(REPORT_DIR, "probe.json"),
              "- 回归日志目录：`%s`" % os.path.join(REPORT_DIR, "regression"),
              "- 改前基线证据：`C:\\briefdesk\\data\\_qa_nottime\\baseline\\`"]
    return "\n".join(lines), all_steps


def sha256(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except Exception:
        return "MISSING"


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    print("[v2_notice_time_check] demo=%s" % DEMO)
    print("[v2_notice_time_check] board=%s" % BOARD)
    print("[v2_notice_time_check] fixed now=%s" % NOW_ISO)
    if not os.path.exists(DEMO):
        print("[FAIL] demo 不存在：%s" % DEMO)
        sys.exit(2)
    now = dt(NOW_ISO)
    board = read_board(BOARD) if os.path.exists(BOARD) else None
    demo_groups, _ = read_demo_groups(DEMO)
    steps = []
    if not demo_groups:
        steps.append({"k": "A0.0 demo 内嵌 GROUPS 可解析", "ok": False, "note": "未找到 var GROUPS"})
    js = run_probe()
    if not js:
        print("[FAIL] 未拿到 JS 探针报告")
        sys.exit(2)
    for s in js.get("steps", []):
        steps.append({"k": s.get("k"), "ok": bool(s.get("ok")), "note": s.get("note", "")})
    # 数据一致性（demo GROUPS 与 board-data 是否同源）
    data_steps = py_data_steps(board, now)
    if demo_groups is not None and board:
        ids_demo = [str(g.get("id")) for g in demo_groups]
        ids_board = [str(g.get("id")) for g in board.get("groups") or []]
        data_steps.insert(1, {"k": "D0.1 demo GROUPS 与 board-data 同源（id 集合一致）",
                              "ok": set(ids_demo) == set(ids_board),
                              "note": "demo=%d board=%d 差异=%s" % (
                                  len(ids_demo), len(ids_board), list(set(ids_demo) ^ set(ids_board))[:8])})
    a9_steps, a9_details = ([], [])
    if RUN_A9:
        print("[v2_notice_time_check] 跑 A9 回归（5 项，约 15-30s）...")
        a9_steps, a9_details = run_a9()
    report_md, all_steps = build_report(steps, js, data_steps, a9_steps, a9_details)
    passed = sum(1 for s in all_steps if s["ok"])
    total = len(all_steps)
    for s in all_steps:
        print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + s["note"]) if s["note"] else ""))
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_json = os.path.join(REPORT_DIR, "report_%s.json" % ts)
    out_md = os.path.join(REPORT_DIR, "report_%s.md" % ts)
    json.dump({"generatedAt": datetime.now(CN).isoformat(), "demo": DEMO, "board": BOARD,
               "now": NOW_ISO, "passed": passed, "total": total, "steps": all_steps,
               "a9": a9_details, "chipTable": (js or {}).get("chipTable", []),
               "a8Hits": (js or {}).get("a8Hits", []), "targets": (js or {}).get("targets", {})},
              open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(out_md, "w", encoding="utf-8").write(report_md)
    open(os.path.join(REPORT_DIR, "latest.md"), "w", encoding="utf-8").write(report_md)
    print("=" * 60)
    print("v2_notice_time_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("报告：%s" % out_md)
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
