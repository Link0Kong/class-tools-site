# -*- coding: utf-8 -*-
r"""任务（作业升级）专项自检 —— 2026-11-22

覆盖：
  1) 任务页：工具名「任务」、个人任务/班级作业双段、默认「全部」、分组/智能列表计数；
  2) 快速添加：回车/按钮、本机持久化、列表归属；
  3) 终态编辑：标题/备注/截止/提醒/重复/分组/标签/步骤/我的一天/重要；
  4) 完成与撤销：重复任务完成后生成下一次、撤销时回收下一次；
  5) 分组：新建/重命名/删除（任务移回「任务」）；
  6) 搜索：标题/标签命中、标签点按进入搜索；
  7) 提醒：页内横幅、稍后 10 分钟、完成、提醒设置弹层；
  8) 导出：ICS 内容（VEVENT/VALARM/CRLF）、任务图片、JSON 备份/恢复；
  9) 班级作业：自动同步列表保留、勾选写 marks(kind=hw)、取消写 false、角标计数；
 10) 390px 移动端：无横向溢出、点击区与输入宽度正常；
 11) 0 JS 报错 / 0 console.error / 0 外部请求。

用法：cd web/tools && python tests\task_check.py
      set TASK_SRC=某副本.html
退出码 0 = 全绿。
"""
import functools
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.abspath(os.environ.get("TASK_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8997
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_task_reports")
os.makedirs(REPORT_DIR, exist_ok=True)
REPORT = os.path.join(REPORT_DIR, "task_report.json")
PREVIEW = os.path.join(REPORT_DIR, "task_preview.html")
PREVIEW_M = os.path.join(REPORT_DIR, "task_preview_mobile.html")
PREVIEW_CLASS = os.path.join(REPORT_DIR, "task_preview_class.html")

SID = "3260799999"
NAME = "测试账号"
NOW = int(time.time() * 1000)
TODAY = datetime.now().strftime("%Y-%m-%d")
TOMORROW = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
IN2 = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

TASKS = {
    "v": 1,
    "lists": [
        {"id": "inbox", "name": "任务", "color": "cy", "order": 0},
        {"id": "lstudy", "name": "学习", "color": "bl", "order": 1},
        {"id": "llife", "name": "生活", "color": "sd", "order": 2},
    ],
    "items": [
        {"id": "t1", "title": "复习高数第三章", "notes": "重点看例题 3.2–3.5", "list": "lstudy",
         "due": TODAY, "dueTime": "20:00", "remindMode": "30", "starred": True,
         "myDay": TODAY, "tags": ["复习", "高数"],
         "steps": [{"text": "看例题", "done": True, "note": "先看 3.2 节例题"}, {"text": "做课后习题", "done": False}],
         "createdAt": NOW - 10000, "updatedAt": NOW - 10000, "order": 0},
        {"id": "t2", "title": "买牙膏和洗衣液", "notes": "", "list": "llife",
         "due": TOMORROW, "dueTime": "", "remindMode": "none", "starred": False,
         "myDay": "", "tags": [], "steps": [],
         "createdAt": NOW - 20000, "updatedAt": NOW - 20000, "order": -1},
        {"id": "t3", "title": "整理英语 Unit 3 单词", "notes": "", "list": "lstudy",
         "due": YESTERDAY, "dueTime": "", "remindMode": "none", "starred": False,
         "myDay": "", "tags": ["英语"], "steps": [],
         "createdAt": NOW - 30000, "updatedAt": NOW - 30000, "order": -2},
        {"id": "t5", "title": "交班费", "notes": "", "list": "inbox",
         "due": "", "dueTime": "", "remindMode": "custom", "remindCustom": NOW - 60000,
         "remindAt": NOW - 60000, "lastNotifyAt": NOW, "starred": False,
         "myDay": "", "tags": [], "steps": [],
         "createdAt": NOW - 40000, "updatedAt": NOW - 40000, "order": -3},
        {"id": "t4", "title": "已完成的示例任务", "notes": "", "list": "inbox",
         "done": True, "doneAt": NOW - 86400000, "createdAt": NOW - 50000,
         "updatedAt": NOW - 86400000, "order": 2},
    ],
    "prefs": {"sound": True, "defaultRemind": "none"},
}

DATA = {
    "members": [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
                 "role": "", "badge": "", "is_admin": False} for i in range(1, 71)],
    "homework": [
        {"id": "hw1", "subject": "英语", "content": "Unit 3 练习册 P22–P25", "due": "",
         "date": "2099-01-01", "time": "", "done": False,
         "attachments": json.dumps([{"n": "作业资料.txt", "t": "text/plain", "s": 5, "d": "aGVsbG8="}], ensure_ascii=False)},
        {"id": "hw2", "subject": "数学", "content": "习题 3.1 第 1–8 题", "due": "上课前",
         "date": "2099-01-02", "time": "", "done": False},
    ],
    "marks": [], "fitrecs": [], "notices": [
        {"id": "row_nt1", "ts": NOW, "hidden": False, "edited_at": 0, "override_json": None,
         "body": "[[CLASS_NOTICE_V1]]" + json.dumps({
             "id": "nt1", "title": "测试通知加入任务", "cat": "班级事务", "ts": NOW,
             "summary": "通知摘要", "deadline": "2099-02-03T18:30:00+08:00",
             "items": [{"kind": "text", "text": "通知正文内容"}]
         }, ensure_ascii=False)}
    ],
    "tt": {"c": [], "t": "2026-08-31"},
}

MOCK = r"""
<script>
window.__errs=[];window.__cerrs=[];window.__external=[];window.__posts=[];window.__dl=0;
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
(function(){var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};})();
window.confirm=function(){return true;};
try{var _ac=HTMLAnchorElement.prototype.click;HTMLAnchorElement.prototype.click=function(){if(this.download){window.__dl++;return;}return _ac.apply(this,arguments);};}catch(e){}
var DATA=__DATA__;
function ok(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
window.fetch=function(u,o){
  o=o||{};var s=String((u&&u.url!==undefined)?u.url:u),m=String(o.method||"GET").toUpperCase();
  if(s.indexOf("tcloudbasegateway")>=0||s.indexOf("/v1/rdb/rest")>=0){
    if(s.indexOf("rpc/class_members")>=0)return ok(DATA.members);
    if(s.indexOf("class_notices_meta")>=0)return Promise.resolve({ok:false,status:404,json:function(){return Promise.resolve([]);},text:function(){return Promise.resolve("");}});
    if(s.indexOf("/notices")>=0){
      if(s.indexOf("select=id,ts")>=0)return ok(DATA.notices.map(function(g){return {id:g.id,ts:g.ts,hidden:false,edited_at:0};}));
      return ok(DATA.notices);
    }
    if(s.indexOf("/homework")>=0)return ok(DATA.homework);
    if(s.indexOf("/marks")>=0){
      if(m==="POST"){try{window.__posts.push({url:s,method:m,body:JSON.parse(o.body||"[]")});}catch(e){}}
      return ok(DATA.marks);
    }
    if(s.indexOf("/fitrecs")>=0)return ok(DATA.fitrecs);
    if(s.indexOf("/userdata")>=0)return ok([]);
    if(s.indexOf("/visits")>=0)return ok([]);
    return ok([]);
  }
  if(s.indexOf("tt.json")>=0)return ok(DATA.tt);
  window.__external.push(s);
  return ok([]);
};
try{
localStorage.clear();
localStorage.setItem("zq_appearance_v1","light");
localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));
__UI_SEG__
localStorage.setItem("zq_tools_v2___SID__",JSON.stringify({task:__TASK__,homework:[]}));
}catch(e){}
</script>
"""

RUNNER = r"""
<script>
(function(){
  var R={steps:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
  async function waitFor(fn,ms){
    var end=Date.now()+(ms||10000);
    while(Date.now()<end){var v=false;try{v=!!fn();}catch(e){}if(v)return true;await sleep(80);}
    return false;
  }
  function q(s){return document.querySelector(s);}
  function qa(s){return Array.prototype.slice.call(document.querySelectorAll(s));}
  function click(s){var e=q(s);if(e){e.click();return true;}return false;}
  function txt(s){var e=q(s);return e?String(e.textContent||""):"";}
  function setv(s,v){
    var e=q(s);if(!e)return false;
    e.value=v;e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));
    return true;
  }
  function fileOf(name,content,mime){
    var body=content;
    if(typeof content==="string")body=[content];
    return new File(body,name,{type:mime||"text/plain"});
  }
  function pngFile(){
    var b=atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=");
    var u=new Uint8Array(b.length);for(var i=0;i<b.length;i++)u[i]=b.charCodeAt(i);
    return new File([u],"dot.png",{type:"image/png"});
  }
  function setFiles(sel,files){
    var inp=q(sel);if(!inp)return false;
    var dt=new DataTransfer();files.forEach(function(f){dt.items.add(f);});
    inp.files=dt.files;inp.dispatchEvent(new Event("change",{bubbles:true}));
    return true;
  }
  function attsOf(t){
    try{return JSON.parse(t&&t.attachments||"[]")||[];}catch(e){return [];}
  }
  function dragHold(handle,targetEl,down){
    var h=q(handle);if(!h||!targetEl)return null;
    var hr=h.getBoundingClientRect(),tr=targetEl.getBoundingClientRect();
    var x=tr.left+tr.width/2,y=down?tr.bottom-2:tr.top+2;
    h.dispatchEvent(new PointerEvent("pointerdown",{bubbles:true,cancelable:true,pointerId:77,button:0,buttons:1,clientX:hr.left+5,clientY:hr.top+5}));
    document.dispatchEvent(new PointerEvent("pointermove",{bubbles:true,cancelable:true,pointerId:77,button:0,buttons:1,clientX:x,clientY:y}));
    return {x:x,y:y};
  }
  function dragEnd(p){
    document.dispatchEvent(new PointerEvent("pointerup",{bubbles:true,cancelable:true,pointerId:77,button:0,buttons:0,clientX:p.x,clientY:p.y}));
  }
  function dragByPointer(handle,targetEl,down){
    var p=dragHold(handle,targetEl,down);if(!p)return false;
    dragEnd(p);return true;
  }
  function rowByTitle(title){
    var rows=qa("#tkList .tk-item");
    for(var i=0;i<rows.length;i++){
      var t=rows[i].querySelector(".tk-ititle");
      if(t&&String(t.textContent)===title)return rows[i];
    }
    return null;
  }
  function doneRowByTitle(title){
    var rows=qa("#tkDoneList .tk-item");
    for(var i=0;i<rows.length;i++){
      var t=rows[i].querySelector(".tk-ititle");
      if(t&&String(t.textContent)===title)return rows[i];
    }
    return null;
  }
  function taskByTitle(title){
    try{var a=TASK.items();for(var i=0;i<a.length;i++)if(a[i].title===title)return a[i];}catch(e){}
    return null;
  }
  function report(){
    try{var x=new XMLHttpRequest();x.open("POST","/_report",false);x.setRequestHeader("Content-Type","application/json");
      x.send(JSON.stringify({steps:R.steps,errs:window.__errs||[],cerrs:window.__cerrs||[],
        external:window.__external||[],posts:window.__posts||[],dl:window.__dl||0}));}catch(e){}
  }
  window.addEventListener("load",function(){
    setTimeout(async function(){
      try{
        click('[data-tab="hw"]');await sleep(900);
        T("工具名显示「任务」", txt('[data-tab="hw"]')==="任务", txt('[data-tab="hw"]'));
        T("任务页激活", !!q("#s-hw")&&q("#s-hw").classList.contains("on"), "");
        T("默认视图=全部", txt("#tkTitle")==="全部", txt("#tkTitle"));
        T("全部待完成 4 条", qa("#tkList .tk-item").length===4, qa("#tkList .tk-item").length);
        T("已完成区 1 条", !!(q("#tkDoneWrap")&&!q("#tkDoneWrap").hidden)&&txt("#tkDoneN")==="1", txt("#tkDoneN"));
        T("侧栏分组计数存在", txt("#tkLists").indexOf("学习")>=0&&txt("#tkLists").indexOf("生活")>=0, txt("#tkLists").slice(0,80));
        T("默认「任务」分组已移除", !qa("#tkLists [data-tklist]").some(function(b){return b.getAttribute("data-tklist")==="inbox";}), txt("#tkLists").slice(0,80));
        T("支持未分组任务", TASK.items().some(function(t){return t.list==="";}), TASK.items().length);
        T("班级作业角标=2", txt("#tkSegClassN")==="2", txt("#tkSegClassN"));
        T("桌面无横向溢出", document.documentElement.scrollWidth<=document.documentElement.clientWidth+1,
          document.documentElement.scrollWidth+"/"+document.documentElement.clientWidth);
        T("空搜索/排序控件就位", !!q("#tkSort")&&!!q("#tkQuick"), "");

        /* ---- 时间选择器 ---- */
        click("#tkQuickDueBtn");await sleep(120);
        T("快速添加日期/时间入口可见", !!q("#tkQuickDateBtn")&&!!q("#tkQuickTimeBtn")&&!q("#tkQuickDateRow").hidden, "");
        click("#tkQuickDateBtn");await sleep(120);
        T("日期面板打开并默认今天", !!q("#tkDatePanel")&&!q("#tkDatePanel").hidden&&window.__DATE_PICK().open&&window.__DATE_PICK().sel===__TODAY__, JSON.stringify(window.__DATE_PICK()));
        var dayEl=qa("#tkDpGrid [data-tkdp-day]").filter(function(b){return !b.classList.contains("is-out")&&b.getAttribute("data-tkdp-day")!==__TODAY__;})[0];
        if(dayEl){dayEl.click();await sleep(40);}
        T("日期网格可直接选日", !!dayEl&&window.__DATE_PICK().sel===dayEl.getAttribute("data-tkdp-day"), dayEl?dayEl.getAttribute("data-tkdp-day"):"none");
        q('[data-tkdp-quick="tomorrow"]').click();await sleep(60);
        T("日期面板选中明天", txt("#tkDpSelected").indexOf("已选")>=0&&window.__DATE_PICK().sel===__TOMORROW__, txt("#tkDpSelected"));
        click("#tkDpOk");await sleep(100);
        T("日期选择写入隐藏值/按钮", q("#tkQuickDate").value===__TOMORROW__&&txt("#tkQuickDateBtn").indexOf("月")>=0,
          q("#tkQuickDate").value+" | "+txt("#tkQuickDateBtn"));
        click("#tkQuickDateBtn");await sleep(80);
        var oldMonth=window.__DATE_PICK().month;q('[data-tkdp-nav="1"]').click();await sleep(40);
        T("日期面板可翻月", window.__DATE_PICK().month!==oldMonth, oldMonth+" -> "+window.__DATE_PICK().month);
        q('[data-tkdp-nav="-1"]').click();await sleep(30);
        click("#tkDpClear");await sleep(80);
        T("日期面板清除日期", q("#tkQuickDate").value===""&&txt("#tkQuickDateBtn").indexOf("选择日期")>=0,
          q("#tkQuickDate").value+" | "+txt("#tkQuickDateBtn"));
        click("#tkQuickDateBtn");await sleep(80);q('[data-tkdp-quick="tomorrow"]').click();click("#tkDpOk");await sleep(80);
        T("快速添加日期入口可见", !!q("#tkQuickTimeBtn")&&!q("#tkQuickDateRow").hidden, "");
        click("#tkQuickTimeBtn");await sleep(120);
        T("时间面板打开", !!q("#tkTimePanel")&&!q("#tkTimePanel").hidden&&window.__TIME_PICK().open, "");
        q('[data-tkp-h="18"]').click();q('[data-tkp-m="30"]').click();await sleep(60);
        T("时间面板实时预览", txt("#tkTpPreview")==="18:30", txt("#tkTpPreview"));
        click("#tkTpOk");await sleep(120);
        T("时间选择写入隐藏值/按钮", q("#tkQuickTime").value==="18:30"&&txt("#tkQuickTimeBtn").indexOf("18:30")>=0,
          q("#tkQuickTime").value+" | "+txt("#tkQuickTimeBtn"));
        T("时间选择后面板关闭", q("#tkTimePanel").hidden, "");
        click("#tkQuickTimeBtn");await sleep(80);
        setv("#tkTpExact","2030");await sleep(40);click("#tkTpOk");await sleep(100);
        T("时间直接输入 2030 归一为 20:30", q("#tkQuickTime").value==="20:30", q("#tkQuickTime").value);
        click("#tkQuickTimeBtn");await sleep(80);
        q("#tkTpAllDay").click();await sleep(30);click("#tkTpOk");await sleep(100);
        T("选择全天清空时间", q("#tkQuickTime").value===""&&txt("#tkQuickTimeBtn").indexOf("全天")>=0,
          q("#tkQuickTime").value+" | "+txt("#tkQuickTimeBtn"));
        click("#tkQuickDateClear");await sleep(60);
        click("#tkQuickDateBtn");await sleep(80);q('[data-tkdp-quick="tomorrow"]').click();click("#tkDpOk");await sleep(80);
        click("#tkQuickTimeBtn");await sleep(80);q('[data-tkp-h="18"]').click();q('[data-tkp-m="30"]').click();click("#tkTpOk");await sleep(80);

        /* ---- 快速添加 ---- */
        setv("#tkQuick","测试快速添加");
        q("#tkQuickAdd").click();await sleep(250);
        T("快速添加后 5 条", qa("#tkList .tk-item").length===5, qa("#tkList .tk-item").length);
        T("快速添加任务在列表中", !!rowByTitle("测试快速添加"), "");
        T("快速添加默认未分组", (function(){var qk=TASK.items().filter(function(t){return t.title==="测试快速添加";})[0];return !!qk&&qk.list==="";})(), "");
        T("快速添加保留时间选择", (function(){var qk=TASK.items().filter(function(t){return t.title==="测试快速添加";})[0];return !!qk&&qk.due===__TOMORROW__&&qk.dueTime==="18:30";})(), "");
        var raw=localStorage.getItem("zq_tools_v2___SID__")||"";
        T("快速添加写入本机存储", raw.indexOf("测试快速添加")>=0, String(raw.length));

        /* ---- 编辑 ---- */
        var row=rowByTitle("测试快速添加");row.click();await sleep(300);
        T("点击任务打开详情", q("#tkDetailPanel").style.display!=="none"&&q("#tkPanel").style.display==="none"&&txt("#tkDtTitle")==="测试快速添加", txt("#tkDtTitle"));
        T("详情有独立编辑图标", !!q("#tkDtEdit")&&q("#tkDtEdit").getAttribute("aria-label")==="编辑任务", "");
        click("#tkDtEdit");await sleep(300);
        T("编辑器打开且标题回填", q("#tkPanel").style.display!=="none"&&q("#tkFTitle").value==="测试快速添加", q("#tkFTitle").value);
        T("分组下拉含未分组", !!q('#tkFList option[value=""]'), q("#tkFList").value);
        T("编辑器日期按钮回填", q("#tkFDate").value===__TOMORROW__&&txt("#tkFDateBtn").indexOf("月")>=0,
          q("#tkFDate").value+" | "+txt("#tkFDateBtn"));
        T("编辑器时间按钮沿用快速添加值", txt("#tkFTimeBtn").indexOf("18:30")>=0&&q("#tkFTime").value==="18:30", txt("#tkFTimeBtn"));
        click("#tkFTimeBtn");await sleep(100);
        q('[data-tkp-h="20"]').click();q('[data-tkp-m="15"]').click();click("#tkTpOk");await sleep(120);
        T("编辑器时间选择生效", q("#tkFTime").value==="20:15"&&txt("#tkFTimeBtn").indexOf("20:15")>=0,
          q("#tkFTime").value+" | "+txt("#tkFTimeBtn"));
        setv("#tkFTitle","测试编辑任务");
        setv("#tkFNotes","备注内容 ABC");
        setv("#tkFDate",__IN2__);
        setv("#tkFTime","09:30");
        setv("#tkFRepeat","weekly");
        setv("#tkFList","lstudy");
        setv("#tkFTags","甲, 乙");
        setv("#tkFStepAdd","步骤一");q("#tkFStepAddBtn").click();await sleep(80);
        setv("#tkFStepAdd","步骤二");q("#tkFStepAddBtn").click();await sleep(80);
        T("步骤渲染 2 条", qa("#tkFSteps [data-tksteptext]").length===2, qa("#tkFSteps [data-tksteptext]").length);
        setv('#tkFSteps [data-tkstepnote="0"]',"先看例题");
        T("步骤备注可填写", q('#tkFSteps [data-tkstepnote="0"]').value==="先看例题", q('#tkFSteps [data-tkstepnote="0"]').value);
        click('#tkFSteps [data-tkstepdone="0"]');await sleep(50);
        click("#tkFStar");click("#tkFMyDay");await sleep(50);
        click("#tkFSave");await sleep(300);
        T("编辑器保存后关闭", q("#tkPanel").style.display==="none", q("#tkPanel").style.display);
        var et=taskByTitle("测试编辑任务");
        T("字段保存：截止/时间/重复/分组", !!et&&et.due===__IN2__&&et.dueTime==="09:30"&&et.repeat==="weekly"&&et.list==="lstudy",
          et?JSON.stringify({due:et.due,time:et.dueTime,rep:et.repeat,list:et.list}):"null");
        T("字段保存：标签/步骤/重要/我的一天", !!et&&et.tags.join(",")==="甲,乙"&&et.steps.length===2&&et.steps[0].done&&et.starred&&et.myDay===__TODAY__,
          et?JSON.stringify({tags:et.tags,steps:et.steps,star:et.starred,my:et.myDay}):"null");
        T("步骤备注写入数据", !!et&&et.steps[0].note==="先看例题", et?String(et.steps[0].note):"missing");
        T("行内展示截止与步骤进度", txt("#tkList").indexOf("09:30")>=0&&txt("#tkList").indexOf("1/2")>=0, txt("#tkList").slice(0,120));

        /* ---- 步骤展开 / 详情 ---- */
        var etRow=rowByTitle("测试编辑任务");
        T("有步骤任务显示展开按钮", !!etRow&&!!etRow.querySelector("[data-tkexpand]"), "");
        if(etRow&&etRow.querySelector("[data-tkexpand]")){etRow.querySelector("[data-tkexpand]").click();await sleep(150);}
        T("任务步骤可展开", !!q("#tkList .tk-substeps")&&txt("#tkList").indexOf("步骤一")>=0, txt("#tkList").slice(0,120));
        T("展开保留原行与键盘焦点目标", etRow===rowByTitle("测试编辑任务")&&etRow.querySelector("[data-tkexpand]").getAttribute("aria-expanded")==="true","");
        T("展开后显示步骤备注", txt("#tkList").indexOf("先看例题")>=0, "");
        var exRow=rowByTitle("测试编辑任务");
        if(exRow&&exRow.querySelector("[data-tkexpand]")){exRow.querySelector("[data-tkexpand]").click();await sleep(120);}
        rowByTitle("测试编辑任务").click();await sleep(250);
        T("任务详情显示步骤与备注", q("#tkDetailPanel").style.display!=="none"&&txt("#tkDtBody").indexOf("步骤一")>=0&&txt("#tkDtBody").indexOf("先看例题")>=0,
          txt("#tkDtBody").slice(0,120));
        click('#tkDtBody [data-tkdtsdone="1"]');await sleep(120);
        T("详情内可勾选步骤", !!et&&et.steps[1].done===true, et?String(et.steps[1].done):"missing");
        click('#tkDtBody [data-tkdtsdone="1"]');await sleep(120);
        T("详情内可取消步骤", !!et&&et.steps[1].done===false, et?String(et.steps[1].done):"missing");
        click("#tkDtClose");await sleep(120);
        T("任务详情可关闭", q("#tkDetailPanel").style.display==="none", "");

        /* ---- 重复完成 / 撤销 ---- */
        var before=TASK.items().length;
        et.due="2020-01-01";
        rowByTitle("测试编辑任务").querySelector("[data-tkcheck]").click();await sleep(350);
        var parent=taskByTitle("测试编辑任务");
        var kids=TASK.items().filter(function(x){return x.fromId===(parent&&parent.id)&&!x.done;});
        T("完成重复任务生成下一次", !!parent&&parent.done&&kids.length===1&&TASK.items().length===before+1,
          "parent="+(parent&&parent.done)+" kids="+kids.length+" n="+TASK.items().length);
        T("下一次日期顺延 7 天", kids[0]&&kids[0].due>parent.due, kids[0]?kids[0].due:"");
        T("长期逾期的每周任务补到未来并保留星期",kids[0]&&new Date(kids[0].due+"T"+kids[0].dueTime)>Date.now()&&new Date(kids[0].due+"T12:00:00").getDay()===3,"");
        T("重复任务保留步骤备注并重置勾选",kids[0]&&kids[0].steps[0].note===et.steps[0].note&&!kids[0].steps[0].done,"");
        click("#tkDoneToggle");await sleep(120);
        var dr=doneRowByTitle("测试编辑任务");
        T("已完成区展开出现该任务", !!dr, "");
        if(dr)dr.querySelector("[data-tkcheck]").click();await sleep(300);
        T("撤销完成回收下一次", TASK.items().filter(function(x){return x.fromId===(parent&&parent.id)&&!x.done;}).length===0,
          TASK.items().filter(function(x){return x.fromId===(parent&&parent.id)&&!x.done;}).length);

        /* ---- 我的一天 ---- */
        click('[data-tkview="myday"]');await sleep(200);
        T("我的一天含 t1 与编辑任务", qa("#tkList .tk-item").length===2, qa("#tkList .tk-item").length);
        setv("#tkQuick","我的一天任务");q("#tkQuickAdd").click();await sleep(200);
        var md=taskByTitle("我的一天任务");
        T("我的一天内快速添加自动归入今天", !!md&&md.myDay===__TODAY__, md?md.myDay:"");
        click('[data-tkview="all"]');await sleep(150);
        var mrow=rowByTitle("测试编辑任务");
        if(mrow&&mrow.querySelector("[data-tkedit]"))mrow.querySelector("[data-tkedit]").click();
        await sleep(250);
        T("任务行编辑图标直接进编辑器", q("#tkPanel").style.display!=="none", q("#tkPanel").style.display);
        click("#tkFMyDay");click("#tkFSave");await sleep(200);
        click('[data-tkview="myday"]');await sleep(150);
        T("移出我的一天后不再显示", !rowByTitle("测试编辑任务"), "");
        click('[data-tkview="all"]');await sleep(100);

        /* ---- 分组 ---- */
        click("[data-tknewlist]");await sleep(200);
        T("新建分组弹层打开", q("#tkListPanel").style.display!=="none", q("#tkListPanel").style.display);
        setv("#tkLName","社团");click('#tkLColors [data-tkc="violet"]');click("#tkLSave");await sleep(250);
        T("新建分组后切到该分组", txt("#tkTitle")==="社团", txt("#tkTitle"));
        T("分组写入侧栏", txt("#tkLists").indexOf("社团")>=0, txt("#tkLists").slice(0,100));
        var cgRow=qa("#tkLists .tk-navrow").filter(function(r){return r.textContent.indexOf("社团")>=0;})[0];
        T("新分组行有删除按钮和拖动把手", !!cgRow&&!!cgRow.querySelector("[data-tkgdel]")&&!!cgRow.querySelector("[data-tksidedrag]"),
          cgRow?cgRow.textContent.slice(0,40):"missing");
        setv("#tkQuick","社团任务");q("#tkQuickAdd").click();await sleep(200);
        var st=taskByTitle("社团任务");
        T("分组内任务归属正确", !!st&&st.list!==undefined&&st.list.indexOf("l")===0, st?st.list:"");
        click("#tkListEdit");await sleep(200);
        setv("#tkLName","社团活动");click("#tkLSave");await sleep(200);
        T("分组重命名", txt("#tkLists").indexOf("社团活动")>=0, txt("#tkLists").slice(0,100));
        var renameRow=qa("#tkLists .tk-navrow").filter(function(r){return r.textContent.indexOf("社团活动")>=0;})[0];
        var delBtn=renameRow?renameRow.querySelector("[data-tkgdel]"):null;
        if(delBtn)delBtn.click();
        else {click("#tkListEdit");await sleep(200);click("#tkLDelete");}
        await sleep(250);
        var moved=taskByTitle("社团任务");
        T("删除分组任务移回未分组", !!moved&&moved.list==="", moved?moved.list:"");
        T("删除分组后回全部", txt("#tkTitle")==="全部", txt("#tkTitle"));

        /* ---- 搜索 / 标签 ---- */
        click("#tkSearchBtn");await sleep(100);setv("#tkSearch","高数");await sleep(200);
        T("搜索命中 1 条", qa("#tkList .tk-item").length===1, qa("#tkList .tk-item").length);
        click("#tkSearchClear");await sleep(100);click("#tkSearchBtn");await sleep(100);
        var tagEl=q('#tkList [data-tktag="复习"]');
        T("标签元素存在", !!tagEl, "");
        if(tagEl){tagEl.click();await sleep(200);T("点标签进入搜索", q("#tkSearch").value==="复习"&&qa("#tkList .tk-item").length===1, q("#tkSearch").value);}
        click("#tkSearchClear");click("#tkSearchBtn");await sleep(100);

        /* ---- 提醒 ---- */
        var rbClose=q('#tkRemindBar [data-tkrb="close"]');if(rbClose)rbClose.click();
        var t1r=taskByTitle("复习高数第三章");
        if(t1r){t1r.remindMode="none";t1r.remindAt=0;t1r.lastNotifyAt=0;t1r.snoozeUntil=0;}
        var t5=taskByTitle("交班费");
        if(t5){t5.lastNotifyAt=0;t5.snoozeUntil=0;t5.remindAt=Date.now()-60000;t5.remindMode="custom";}
        try{TASK.tick();}catch(e){}
        await sleep(250);
        T("到期提醒显示页内横幅", !!(q("#tkRemindBar")&&!q("#tkRemindBar").hidden)&&txt("#tkRbTitle")==="交班费", txt("#tkRbTitle"));
        T("横幅三个动作齐全", !!q('[data-tkrb="done"]')&&!!q('[data-tkrb="snooze"]')&&!!q('[data-tkrb="close"]'), "");
        click('[data-tkrb="snooze"]');await sleep(200);
        T("稍后 10 分钟关闭横幅", q("#tkRemindBar").hidden&&t5.snoozeUntil>Date.now()+9*60000, t5.snoozeUntil);
        try{TASK.tick();}catch(e){}
        await sleep(150);
        T("稍后期间不重复弹", q("#tkRemindBar").hidden, q("#tkRemindBar").hidden);
        t5.snoozeUntil=Date.now()-1;try{TASK.tick();}catch(e){}
        await sleep(200);
        T("稍后到点再次提醒", !q("#tkRemindBar").hidden, "");
        click('[data-tkrb="done"]');await sleep(250);
        T("横幅点完成=任务完成", !!t5.done&&q("#tkRemindBar").hidden, t5.done);
        click("#tkMore");await sleep(120);click('[data-tkm="remind"]');await sleep(200);
        T("提醒设置弹层状态", q("#tkRemindPanel").style.display!=="none"&&txt("#tkRemindState").length>0, txt("#tkRemindState"));
        click("#tkRemindClose");await sleep(100);
        if(t1r){t1r.remindMode="30";t1r.remindAt=Date.now()+1800000;t1r.lastNotifyAt=0;t1r.snoozeUntil=0;}

        /* ---- 导出 / 备份 ---- */
        var ics=window.TASK.ics();
        T("ICS 含 VCALENDAR/VEVENT/VALARM", ics.indexOf("BEGIN:VCALENDAR")>=0&&ics.indexOf("BEGIN:VEVENT")>=0&&ics.indexOf("BEGIN:VALARM")>=0, String(ics.length));
        T("ICS 使用 CRLF 换行", ics.indexOf("\r\n")>=0&&ics.indexOf("\n\n")<0, "");
        T("ICS 中文标题已转义行折叠不破", ics.indexOf("SUMMARY:")>=0, "");
        click("#tkMore");await sleep(120);
        T("更多菜单含新建任务", !!q('[data-tkm="new"]'), "");
        click('[data-tkm="new"]');await sleep(250);
        T("菜单新建任务打开编辑器", q("#tkPanel").style.display!=="none", q("#tkPanel").style.display);
        click("#tkFCancel");await sleep(100);
        var dl0=window.__dl;
        click("#tkMore");await sleep(120);click('[data-tkm="ics"]');await sleep(150);
        T("菜单导出日历经下载出口", window.__dl===dl0+1, dl0+"->"+window.__dl);
        dl0=window.__dl;
        click("#tkMore");await sleep(120);click('[data-tkm="img"]');await sleep(2200);
        T("导出任务图片走下载出口", window.__dl===dl0+1, dl0+"->"+window.__dl);
        dl0=window.__dl;
        click("#tkMore");await sleep(120);click('[data-tkm="export"]');await sleep(150);
        T("任务 JSON 备份走下载出口", window.__dl===dl0+1, dl0+"->"+window.__dl);
        var payload={kind:"task-backup",lists:[{id:"limport",name:"导入组",color:"rose",order:9}],
          items:[{id:"timport1",title:"导入任务一",list:"limport",createdAt:Date.now(),updatedAt:Date.now(),order:-99},
                 {id:"timport2",title:"导入任务二",list:"limport",createdAt:Date.now(),updatedAt:Date.now(),order:-100}]};
        var file=new File([JSON.stringify(payload)],"tasks.json",{type:"application/json"});
        var dt=new DataTransfer();dt.items.add(file);
        var inp=q("#tkImportFile");inp.files=dt.files;inp.dispatchEvent(new Event("change",{bubbles:true}));
        await waitFor(function(){return txt("#tkLists").indexOf("导入组")>=0;},7000);
        T("恢复任务：分组", txt("#tkLists").indexOf("导入组")>=0, txt("#tkLists").slice(0,120)+" | toast="+txt("#toast"));
        T("恢复任务：条目", !!taskByTitle("导入任务一")&&!!taskByTitle("导入任务二"), "toast="+txt("#toast"));

        /* ---- 班级作业 ---- */
        click('[data-tkseg="class"]');await sleep(800);
        T("班级段激活且个人段取消", !!(q('#tkSeg [data-tkseg="class"]')||{}).classList.contains("on")&&!(q('#tkSeg [data-tkseg="my"]')||{}).classList.contains("on"), "");
        T("班级作业列表 2 条", qa("#hList .item").length===2, qa("#hList .item").length);
        var first=q("#hList .item [data-tg]");
        T("班级作业勾选入口存在", !!first, "");
        if(first){first.click();await sleep(500);}
        var post=(window.__posts||[]).filter(function(p){return p.url.indexOf("/marks")>=0;});
        T("勾选写 marks(kind=hw,val=true)", post.length>0&&JSON.stringify(post[post.length-1].body).indexOf('"kind":"hw"')>=0&&JSON.stringify(post[post.length-1].body).indexOf('"val":true')>=0,
          JSON.stringify(post[post.length-1]||{}).slice(0,200));
        var doneItem=q("#hList .item.done [data-tg]");
        T("班级作业 UI 标记完成", !!doneItem, "");
        if(doneItem){doneItem.click();await sleep(500);}
        var post2=(window.__posts||[]).filter(function(p){return p.url.indexOf("/marks")>=0;});
        T("取消勾选写 val=false", post2.length>post.length&&JSON.stringify(post2[post2.length-1].body).indexOf('"val":false')>=0,
          JSON.stringify(post2[post2.length-1]||{}).slice(0,200));

        /* ---- 班级作业直接加入任务 + 来源/附件 ---- */
        T("班级作业逐项加入按钮 2 个", qa("[data-add-hw-task]").length===2, qa("[data-add-hw-task]").length);
        var tc0=TASK.items().length;
        var addBtns=qa("[data-add-hw-task]");
        addBtns[0].click();await sleep(450);
        T("逐项加入任务 +1", TASK.items().length===tc0+1, TASK.items().length);
        var src1=TASK.items().filter(function(t){return t.sourceHwId==="hw1";})[0];
        T("来源字段/标题/备注已带入", !!src1&&src1.sourceTitle.indexOf("英语")>=0&&src1.title.indexOf("英语")>=0&&src1.notes.indexOf("Unit 3")>=0,
          src1?JSON.stringify({title:src1.title,src:src1.sourceHwId,st:src1.sourceTitle}):"missing");
        T("班级作业转入的任务默认未分组", !!src1&&src1.list==="", src1?src1.list:"missing");
        T("班级项显示「已在任务」", !!q('#hList [data-hw-id="hw1"]')&&q('#hList [data-hw-id="hw1"]').textContent.indexOf("已在任务")>=0,
          q('#hList [data-hw-id="hw1"]')?q('#hList [data-hw-id="hw1"]').textContent.slice(0,60):"missing");
        click("#hToTask");await sleep(600);
        T("班级头「加入任务」批量补齐剩余 1 条", TASK.items().filter(function(t){return t.sourceHwId==="hw2";}).length===1,
          TASK.items().filter(function(t){return t.sourceHwId;}).length);
        TASK.open(src1.id);await sleep(350);
        T("任务详情显示来源区", !!q("#tkFSource")&&!q("#tkFSource").hidden&&txt("#tkFSource").indexOf("来自班级作业")>=0, txt("#tkFSource").slice(0,80));
        var srcAtt=q('#tkFSource [data-tk-hwatt]');
        T("来源附件按钮存在", !!srcAtt, "");
        if(srcAtt){srcAtt.click();await sleep(200);T("来源附件可打开预览", q("#attPanel").style.display!=="none", q("#attPanel").style.display);q("#attClose").click();}
        var locate=q('#tkFSource [data-tk-hwopen]');
        if(locate){locate.click();await sleep(1000);}
        T("定位回班级作业并关闭详情", q("#tkPanel").style.display==="none"&&!!q('#tkSeg [data-tkseg="class"]').classList.contains("on"),
          "panel="+q("#tkPanel").style.display);
        T("原班级卡片高亮定位", !!q('#hList [data-hw-id="hw1"]')&&q('#hList [data-hw-id="hw1"]').classList.contains("tk-hw-flash"), "");
        click('[data-tkseg="my"]');await sleep(250);

        /* ---- 任务附件：上传/压缩/限额/持久化 ---- */
        var attTask=taskByTitle("买牙膏和洗衣液");
        TASK.open(attTask.id);await sleep(350);
        T("无来源任务不显示来源区", q("#tkFSource").hidden===true, q("#tkFSource").hidden);
        var dtDrop=new DataTransfer();dtDrop.items.add(fileOf("拖入.txt","drag"));
        var dropEv=new Event("drop",{bubbles:true,cancelable:true});dropEv.dataTransfer=dtDrop;
        q("#tkAttDrop").dispatchEvent(dropEv);
        await waitFor(function(){return qa("#taskFilesList .att-card").length===1;},10000);
        T("拖拽到附件区可添加", qa("#taskFilesList .att-card").length===1, qa("#taskFilesList .att-card").length);
        setFiles("#taskFiles",[fileOf("任务资料.txt","附件内容")]);await waitFor(function(){return qa("#taskFilesList .att-card").length===2;},10000);
        T("任务附件卡片 2 个", qa("#taskFilesList .att-card").length===2, qa("#taskFilesList .att-card").length);
        T("任务附件计数 2/2", txt("#taskFilesCount")==="2/2", txt("#taskFilesCount"));
        qa("#taskFilesList [data-att-rm]")[1].click();await sleep(120);
        T("移除附件后 1 个", qa("#taskFilesList .att-card").length===1, qa("#taskFilesList .att-card").length);
        setFiles("#taskFiles",[fileOf("a.txt","a"),fileOf("b.txt","b")]);await waitFor(function(){return qa("#taskFilesList .att-card").length===2;},10000);
        T("超过上限只加 1 个并提示", qa("#taskFilesList .att-card").length===2&&txt("#taskFilesNote").indexOf("已忽略")>=0,
          qa("#taskFilesList .att-card").length+" | "+txt("#taskFilesNote"));
        qa("#taskFilesList [data-att-rm]")[0].click();await sleep(120);
        T("再次移除后 1 个", qa("#taskFilesList .att-card").length===1, qa("#taskFilesList .att-card").length);
        setFiles("#taskFiles",[new File([new Uint8Array(325*1024)],"big.txt",{type:"text/plain"})]);await waitFor(function(){return qa("#taskFilesList .att-card").length===2;},16000);
        T("任务附件超过旧 320KB 上限", qa("#taskFilesList .att-card").length===2&&txt("#taskFilesNote").indexOf("已添加")>=0,
          qa("#taskFilesList .att-card").length+" | "+txt("#taskFilesNote"));
        qa("#taskFilesList [data-att-rm]")[0].click();await sleep(120);
        setFiles("#taskFiles",[fileOf("补充.txt","补充")]);await waitFor(function(){return qa("#taskFilesList .att-card").length===2;},12000);
        T("大附件后可继续补附件", qa("#taskFilesList .att-card").length===2, qa("#taskFilesList .att-card").length+" | "+txt("#taskFilesNote"));
        qa("#taskFilesList .att-card")[0].click();await sleep(300);
        T("任务附件可预览", q("#attPanel").style.display!=="none"&&!!q("#attBody pre,.att-full"), q("#attBody").textContent.slice(0,40));
        q("#attClose").click();
        click("#tkFSave");await sleep(500);
        var savedAtt=taskByTitle("买牙膏和洗衣液");
        T("任务附件写入数据 2 个", attsOf(savedAtt).length===2, attsOf(savedAtt).length);
        TASK.open(savedAtt.id);await sleep(350);
        T("重开详情恢复附件 2 个", qa("#taskFilesList .att-card").length===2, qa("#taskFilesList .att-card").length);
        qa("#taskFilesList [data-att-rm]")[0].click();await sleep(120);
        click("#tkFSave");await sleep(500);
        T("保存后任务附件剩 1 个", attsOf(taskByTitle("买牙膏和洗衣液")).length===1, attsOf(taskByTitle("买牙膏和洗衣液")).length);

        /* ---- 发布作业附件：图片压缩 + 发布持久化 ---- */
        click('[data-tkseg="class"]');await sleep(300);
        click("#hPub");await sleep(250);
        T("发布作业附件拖拽区存在", !!q("#hDrop")&&!!q("#hFilesCount"), "");
        setFiles("#hFiles",[pngFile()]);await waitFor(function(){return qa("#hFilesList .att-card img").length===1;},12000);
        T("作业图片附件显示缩略图", qa("#hFilesList .att-card img").length===1, qa("#hFilesList .att-card img").length+" | "+JSON.stringify(window.__ATT_PROBE&&window.__ATT_PROBE()));
        T("作业附件计数 1/2", txt("#hFilesCount")==="1/2", txt("#hFilesCount"));
        setFiles("#hFiles",[fileOf("说明.txt","说明")]);await waitFor(function(){return qa("#hFilesList .att-card").length===2;},12000);
        T("作业第二附件加入", qa("#hFilesList .att-card").length===2&&txt("#hFilesCount")==="2/2",
          qa("#hFilesList .att-card").length+" | "+txt("#hFilesCount"));
        qa("#hFilesList [data-att-rm]")[1].click();await sleep(150);
        setv("#hContent","附件发布测试");
        click("#hAdd");await sleep(900);
        var hwNew=TASK.homework().filter(function(h){return h.content==="附件发布测试";})[0];
        T("发布作业带压缩图片附件", !!hwNew&&attsOf(hwNew).length===1&&attsOf(hwNew)[0].t==="image/jpeg",
          hwNew?JSON.stringify(attsOf(hwNew).map(function(a){return {n:a.n,t:a.t,s:a.s};})):"missing");
        T("班级列表出现新作业", qa("#hList .item").length===3, qa("#hList .item").length);
        click('[data-tkseg="my"]');await sleep(250);

        /* ---- 详细编辑：预填/行内错误/日期快捷/提醒提示/未保存拦截 ---- */
        var tc1=TASK.items().length;
        setv("#tkQuick","详细预填任务");
        setv("#tkQuickDate",__TOMORROW__);
        setv("#tkQuickList","lstudy");
        click("#tkQuickStar");
        click("#tkQuickMore");await sleep(350);
        T("详细编辑打开并预填标题", q("#tkPanel").style.display!=="none"&&q("#tkFTitle").value==="详细预填任务", q("#tkFTitle").value);
        T("详细编辑预填截止/分组/重要", q("#tkFDate").value===__TOMORROW__&&q("#tkFList").value==="lstudy"&&q("#tkFStar").classList.contains("on"),
          q("#tkFDate").value+"/"+q("#tkFList").value);
        T("详细编辑清空快速输入", q("#tkQuick").value===""&&q("#tkQuickDateRow").hidden, "");
        setv("#tkFTitle","");
        click("#tkFSave");await sleep(160);
        T("空标题显示行内错误且不关闭", q("#tkPanel").style.display!=="none"&&q("#tkFTitleErr").classList.contains("on"), txt("#tkFTitleErr"));
        setv("#tkFTitle","详细预填任务");
        click('[data-tkdateset="today"]');await sleep(100);
        T("日期快捷「今天」生效", q("#tkFDate").value===__TODAY__, q("#tkFDate").value);
        T("日期快捷同步日期按钮", txt("#tkFDateBtn").indexOf("月")>=0, txt("#tkFDateBtn"));
        setv("#tkFRemind","30");await sleep(100);
        T("提醒提示显示预计时间", txt("#tkFRemindHint").indexOf("提醒")>=0, txt("#tkFRemindHint"));
        var oldConfirm=window.confirm;
        window.confirm=function(){return false;};
        click("#tkFCancel");await sleep(180);
        T("未保存修改关闭被拦截", q("#tkPanel").style.display!=="none", q("#tkPanel").style.display);
        window.confirm=oldConfirm;
        click("#tkFCancel");await sleep(220);
        T("确认放弃后关闭且不新增任务", q("#tkPanel").style.display==="none"&&TASK.items().length===tc1, TASK.items().length);

        /* ---- 左侧栏目 / 任务拖动排序 ---- */
        click('[data-tkview="all"]');await sleep(250);
        if(q("#tkSort")){setv("#tkSort","default");await sleep(200);}
        var dragHandles=qa("#tkList [data-tkdrag]");
        T("任务行有拖动把手", dragHandles.length>=2, dragHandles.length);
        var beforeTasks=TASK.items().filter(function(t){return !t.done;}).sort(function(a,b){return (Number(a.order)||0)-(Number(b.order)||0);});
        var oldFirst=beforeTasks[0]?beforeTasks[0].title:"";
        var secondRow=q("#tkList .tk-item:nth-of-type(2)")||qa("#tkList .tk-item")[1];
        var animHold=null;
        if(dragHandles.length>=2&&secondRow)animHold=dragHold("#tkList [data-tkdrag]",secondRow,true);
        await sleep(30);
        var animCount=qa("#tkList .tk-item").filter(function(el){return el.getAnimations().length>0;}).length;
        T("任务拖动有让位动画", animCount>0, animCount);
        if(animHold){dragEnd(animHold);await sleep(350);}
        var afterTasks=TASK.items().filter(function(t){return !t.done;}).sort(function(a,b){return (Number(a.order)||0)-(Number(b.order)||0);});
        T("任务拖动改变顺序并保存", !!oldFirst&&afterTasks[0]&&afterTasks[0].title!==oldFirst,
          "old="+oldFirst+" new="+(afterTasks[0]?afterTasks[0].title:""));

        var smartRows=qa("#tkSmart .tk-navrow");
        var oldSmart=smartRows[0]?smartRows[0].querySelector("[data-tkview]").getAttribute("data-tkview"):"";
        if(smartRows.length>=2){dragByPointer("#tkSmart [data-tksidedrag]",smartRows[1],true);await sleep(350);}
        var newSmart=q("#tkSmart [data-tkview]")?q("#tkSmart [data-tkview]").getAttribute("data-tkview"):"";
        T("左侧「视图」可拖动排序", !!oldSmart&&newSmart&&newSmart!==oldSmart, oldSmart+" -> "+newSmart);
        var uiSaved={};try{uiSaved=JSON.parse(localStorage.getItem("zq_task_ui_v1")||"{}");}catch(e){}
        T("视图顺序写入本机偏好", Array.isArray(uiSaved.smartOrder)&&uiSaved.smartOrder[0]===newSmart,
          JSON.stringify(uiSaved.smartOrder||[]).slice(0,100));
        var sbSaved=TASK.sidebar();
        T("视图顺序写入任务数据", Array.isArray(sbSaved.order)&&sbSaved.order[0]===newSmart&&sbSaved.at>0,
          JSON.stringify(sbSaved).slice(0,120));

        var groupRows=qa("#tkLists .tk-navrow").filter(function(r){return !!r.querySelector("[data-tksidedrag]");});
        var oldLists=TASK.lists().filter(function(l){return l.id!=="inbox";}).map(function(l){return l.id;});
        T("分组拖动前置", groupRows.length>=2, "rows="+groupRows.length+" handles="+qa("#tkLists [data-tksidedrag]").length+" list="+JSON.stringify(oldLists));
        if(groupRows.length>=2){dragByPointer("#tkLists [data-tksidedrag]",groupRows[1],true);await sleep(350);}
        var newLists=TASK.lists().filter(function(l){return l.id!=="inbox";}).map(function(l){return l.id;});
        var domLists=qa("#tkLists .tk-navrow").map(function(r){var b=r.querySelector("[data-tklist]");return b?b.getAttribute("data-tklist"):"";});
        T("左侧「分组」可拖动排序", oldLists.length>=2&&newLists[0]!==oldLists[0], oldLists.slice(0,3).join(",")+" -> "+newLists.slice(0,3).join(",")+" dom="+domLists.join(","));

        /* ---- 通知加入任务 ---- */
        click('[data-tab="nt"]');await sleep(2600);
        var ntf=q("#noticeHost iframe"),ntd=ntf&&ntf.contentDocument;
        var ntBtn=ntd?ntd.querySelector(".nt-taskbtn"):null;
        if(!ntBtn){await sleep(1200);ntf=q("#noticeHost iframe");ntd=ntf&&ntf.contentDocument;ntBtn=ntd?ntd.querySelector(".nt-taskbtn"):null;}
        T("通知卡片有加入任务按钮", !!ntBtn, ntd?ntd.body.textContent.slice(0,60):"no iframe");
        if(ntBtn){ntBtn.click();await sleep(600);}
        var ntTask=TASK.items().filter(function(t){return t.sourceNoticeId==="nt1";})[0];
        T("通知可加入任务且未分组", !!ntTask&&ntTask.list===""&&ntTask.title.indexOf("测试通知")>=0, ntTask?JSON.stringify({t:ntTask.title,l:ntTask.list}):"missing");
        T("通知按钮变为已在任务", !!ntBtn&&ntBtn.textContent.indexOf("已在任务")>=0&&ntBtn.disabled, ntBtn?ntBtn.textContent:"");
        if(ntTask){
          T("通知内容带入备注", String(ntTask.notes||"").indexOf("通知正文内容")>=0, String(ntTask.notes||"").slice(0,60));
          click('[data-tab="hw"]');await sleep(300);
          TASK.open(ntTask.id);await sleep(350);
          T("任务详情显示来自通知", txt("#tkFSource").indexOf("来自班级通知")>=0, txt("#tkFSource").slice(0,60));
          var nopen=q('#tkFSource [data-tk-ntopen]');
          T("通知来源有查看入口", !!nopen, "");
          if(nopen){nopen.click();await sleep(500);}
        }

        /* ---- 390px iframe ---- */
        await new Promise(function(res){
          var f=document.createElement("iframe");
          f.id="mfr";f.style.cssText="position:fixed;left:0;top:0;width:390px;height:844px;border:0;z-index:9999;background:#fff";
          f.src="task_preview_mobile.html?embed=1";
          f.onload=function(){setTimeout(res,900);};
          document.body.appendChild(f);
          setTimeout(res,4000);
        });
        try{
          var mf=document.getElementById("mfr"),md=mf.contentDocument,mw=mf.contentWindow;
          mw.document.querySelector('[data-tab="hw"]').click();
          await sleep(700);
          var de=md.documentElement;
          T("390px 视口宽度正确", mw.innerWidth>=380&&mw.innerWidth<=400, mw.innerWidth);
          T("390px 无横向溢出", de.scrollWidth<=de.clientWidth+2, de.scrollWidth+"/"+de.clientWidth);
          T("390px 任务列表可见", md.querySelectorAll("#tkList .tk-item").length>0, md.querySelectorAll("#tkList .tk-item").length);
          T("390px 快速输入宽度正常", (md.querySelector("#tkQuick")||{}).getBoundingClientRect().width>=100,
            (md.querySelector("#tkQuick")||{getBoundingClientRect:function(){return {width:0};}}).getBoundingClientRect().width);
          T("390px 智能列表/分组 chip 可见", md.querySelectorAll("#tkSmart .tk-navbtn").length>=5, md.querySelectorAll("#tkSmart .tk-navbtn").length);
          T("390px 无 JS 报错", (mw.__errs||[]).length===0, JSON.stringify(mw.__errs||[]).slice(0,300));
          var mrow=md.querySelector("#tkList .tk-item");
          if(mrow){mrow.click();await sleep(250);}
          T("390px 任务详情打开", !!md.querySelector("#tkDetailPanel")&&md.querySelector("#tkDetailPanel").style.display!=="none", "");
          var med=md.querySelector("#tkDtEdit");if(med){med.click();await sleep(300);}
          var saveBtn=md.querySelector("#tkFSave");
          T("390px 编辑器保存键在首屏可见", !!saveBtn&&saveBtn.getBoundingClientRect().bottom<=mw.innerHeight+1&&saveBtn.getBoundingClientRect().top>0,
            saveBtn?JSON.stringify(saveBtn.getBoundingClientRect()):"missing");
          var closeBtn=md.querySelector("#tkFClose");
          T("390px 编辑器关闭键存在", !!closeBtn, "");
          if(closeBtn)closeBtn.click();
        }catch(e){T("390px iframe 检查", false, String(e));}

        /* ---- 无个人任务时：班级作业加载后自动落在「班级作业」 ---- */
        await new Promise(function(res){
          var f=document.createElement("iframe");
          f.id="cfr";f.style.cssText="position:fixed;left:0;top:0;width:390px;height:844px;border:0;z-index:9998;background:#fff";
          f.src="task_preview_class.html?embed=1";
          f.onload=function(){setTimeout(res,900);};
          document.body.appendChild(f);
          setTimeout(res,4000);
        });
        try{
          var cf=document.getElementById("cfr"),cd=cf.contentDocument,cw=cf.contentWindow;
          cd.querySelector('[data-tab="hw"]').click();
          await sleep(1600);
          T("无个人任务时自动落在班级作业", cd.querySelector("#tkClass").hidden===false&&cd.querySelector("#tkMy").hidden===true,
            "classHidden="+cd.querySelector("#tkClass").hidden+" myHidden="+cd.querySelector("#tkMy").hidden);
          T("自动分段时班级按钮激活", !!(cd.querySelector('#tkSeg [data-tkseg="class"]')||{}).classList.contains("on"), "");
          T("自动分段后班级作业可见", cd.querySelectorAll("#hList .item").length===2, cd.querySelectorAll("#hList .item").length);
        }catch(e){T("自动分段 iframe 检查", false, String(e));}

        T("0 JS 报错", (window.__errs||[]).length===0, JSON.stringify(window.__errs||[]).slice(0,400));
        T("0 console.error", (window.__cerrs||[]).length===0, JSON.stringify(window.__cerrs||[]).slice(0,400));
        T("0 外部请求", (window.__external||[]).length===0, JSON.stringify(window.__external||[]).slice(0,300));
      }catch(e){
        R.steps.push({k:"脚本异常",ok:false,note:String(e&&e.stack||e)});
      }
      report();
    },1400);
  });
})();
</script>
"""


def build_preview(with_runner, tasks=None, with_ui=True):
    tasks = TASKS if tasks is None else tasks
    html = open(SRC, encoding="utf-8", newline="").read()
    ui_line = ('localStorage.setItem("zq_task_ui_v1",JSON.stringify({seg:"my",view:"all",list:"inbox",'
               'sort:"default",quickStar:false,quickList:"inbox",doneOpen:false,sound:true}));') if with_ui else ""
    mock = MOCK.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")) \
        .replace("__TASK__", json.dumps(tasks, ensure_ascii=False).replace("<", "\\u003c")) \
        .replace("__UI_SEG__", ui_line) \
        .replace("__SID__", SID).replace("__NAME__", NAME)
    html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    if with_runner:
        runner = RUNNER.replace("__IN2__", json.dumps(IN2)).replace("__TODAY__", json.dumps(TODAY)) \
            .replace("__TOMORROW__", json.dumps(TOMORROW)).replace("__SID__", SID)
        html = html.replace("</body>", runner + "\n</body>", 1)
    return html


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        open(REPORT, "wb").write(self.rfile.read(n))
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def main():
    empty_tasks = {"v": 1, "lists": [{"id": "inbox", "name": "任务", "color": "cy", "order": 0}],
                   "items": [], "prefs": {"sound": True, "defaultRemind": "none"}}
    open(PREVIEW, "w", encoding="utf-8", newline="").write(build_preview(True))
    open(PREVIEW_M, "w", encoding="utf-8", newline="").write(build_preview(False))
    open(PREVIEW_CLASS, "w", encoding="utf-8", newline="").write(build_preview(False, empty_tasks, False))
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), functools.partial(Handler, directory=REPORT_DIR))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(.4)
    if os.path.exists(REPORT):
        os.remove(REPORT)
    url = BASE + os.path.basename(PREVIEW)
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--force-device-scale-factor=1",
            "--window-size=1280,900", "--virtual-time-budget=150000",
            "--screenshot=" + os.path.join(REPORT_DIR, "task_check.png"), url]
    subprocess.run(args, capture_output=True, timeout=300)
    data = None
    for _ in range(40):
        if os.path.exists(REPORT):
            time.sleep(.2)
            data = json.loads(open(REPORT, encoding="utf-8", errors="replace").read())
            break
        time.sleep(.3)
    if not data:
        print("FAIL: 未收到报告（页面可能未启动/提前崩溃）")
        return 1
    bad = 0
    for s in data.get("steps", []):
        if not s["ok"]:
            bad += 1
        print(("PASS  " if s["ok"] else "FAIL  ") + s["k"] + (("  [" + s["note"] + "]") if s["note"] else ""))
    if data.get("errs"):
        print("JS-ERR ", data["errs"][:5])
    if data.get("cerrs"):
        print("CONSOLE-ERR ", data["cerrs"][:5])
    if data.get("external"):
        print("EXTERNAL ", data["external"][:5])
    print("RESULT %s (%d fails)" % ("GREEN" if bad == 0 else "RED", bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
