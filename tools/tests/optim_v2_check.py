# -*- coding: utf-8 -*-
"""OPTIM V2 特性冒烟（无头 Edge，自建 harness，不改仓库测试）。

用法：cd web/tools && python tests/optim_v2_check.py [index.html]
两轮：
  main  : 非管理员、普通 UA —— 预设 / hash / 汇总按钮 / 备份存储用量 / toast 错误样式 / 0 报错
  admin : 管理员、微信 UA   —— 大屏 V3（自定义面板/布局编辑/投票投屏+快速发起/PPT 放映+相容包下载+PowerPoint 打开）/ 微信导出图弹层 + inert / 0 报错
退出码 0 = 全绿。
"""
import os
import sys
import json
import time
import threading
import http.server
import socketserver
import subprocess
import functools

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "..", "index.html")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8997
SID = "3260709999"
NAME = "测试同学"
WX_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49(0x1800312f) NetType/WIFI Language/zh_CN")

DATA = {
    "members": [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
                 "role": ("班长" if i == 1 else ""), "badge": ("班委" if i <= 3 else ""), "is_admin": False}
                for i in range(1, 71)],
    "homework": [], "marks": [], "fitrecs": [], "notices": [],
    "tt": {"c": [], "t": "2026-08-31"},
}


def mock_head(admin):
    js = json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")
    return r"""
<script>
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
(function(){var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};})();
var DATA=__DATA__;
var PNOW=Date.now()+600000;
var POLLSET={multi:false,maxChoices:1,anonymous:true,allowChange:true,resultVisibility:"always"};
var POLL={id:"p1",title:"团日活动形式投票",description:"",mode:"quick",owner_name:"测试同学",settings:POLLSET,
  deadline:PNOW,status:"open",closed_at:0,created_at:Date.now(),updated_at:Date.now(),closed:false,
  total:12,counts:{o1:7,o2:5},has_voted:false,my_choices:[],results_hidden:false,mine:true,can_manage:true};
var PDETAIL={ok:true,now:Date.now(),poll:{id:"p1",title:"团日活动形式投票",description:"",mode:"quick",owner_name:"测试同学",
  settings:POLLSET,options:[{id:"o1",text:"参观红色基地"},{id:"o2",text:"主题团课"}],deadline:PNOW,status:"open",closed_at:0,
  created_at:Date.now(),updated_at:Date.now()},closed:false,total:12,counts:{o1:7,o2:5},has_voted:false,my_choices:[],
  results_hidden:false,mine:true,can_manage:true,voters:[]};
function ok(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
window.fetch=function(u,o){
  var s=String((u&&u.url!==undefined)?u.url:u);
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0)return ok(DATA.members);
    if(s.indexOf("/notices")>=0)return ok(s.indexOf("select=id,ts")>=0?[]:DATA.notices);
    if(s.indexOf("/homework")>=0)return ok(DATA.homework);
    if(s.indexOf("/marks")>=0)return ok(DATA.marks);
    if(s.indexOf("/fitrecs")>=0)return ok(DATA.fitrecs);
    if(s.indexOf("/userdata")>=0)return ok([]);
    if(s.indexOf("/ppt_decks")>=0){
      if(s.indexOf("files%3A")>=0 || s.indexOf("files:")>=0){
        return ok([
          {id:"d2",files:{compat:{s:"ppt/a/d2/build/compat.pptx",size:39000000,name:"总结_兼容版.pptx"},
            pdf:{s:"ppt/a/d2/build/preview.pdf",size:1200000,name:"总结.pdf",pages:16}}},
          {id:"d3",files:null}
        ]);
      }
      if(s.indexOf("manifest")>=0){
        if(s.indexOf("id=eq.d2")>=0)return ok([{id:"d2",title:"团支部年度工作总结",slide_count:8,step_count:12,aspect:"16:9",cover_url:"",
          manifest:{base:"https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/",slides:[],
            files:{compat:{s:"ppt/a/d2/build/compat.pptx",size:39000000,name:"总结_兼容版.pptx"},
              pdf:{s:"ppt/a/d2/build/preview.pdf",size:1200000,name:"总结.pdf",pages:16}}}}]);
        return ok([{id:"d1",title:"团日活动演示",slide_count:2,step_count:2,aspect:"16:9",cover_url:"",manifest:{slides:[
          {steps:[{img:"data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="}],tr:"fade"},
          {steps:[{img:"data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="}],tr:"fade"}]}}]);
      }
      return ok([
        {id:"d1",title:"团日活动演示",status:"ready",progress:100,slide_count:2,step_count:2,aspect:"16:9",cover_url:"",owner_name:"测试同学",source_name:"团日活动演示.pptx",created_at:3,converted_at:4},
        {id:"d2",title:"团支部年度工作总结",status:"ready",progress:100,slide_count:8,step_count:12,aspect:"16:9",cover_url:"",owner_name:"李同学",source_name:"总结.pptx",created_at:2,converted_at:3},
        {id:"d3",title:"防诈骗主题班会",status:"ready",progress:100,slide_count:5,step_count:5,aspect:"16:9",cover_url:"",owner_name:"王同学",source_name:"班会.pptx",created_at:1,converted_at:2}]);
    }
    if(s.indexOf("rpc/poll_list")>=0)return ok({ok:true,now:Date.now(),polls:[POLL]});
    if(s.indexOf("rpc/poll_detail")>=0)return ok(PDETAIL);
    if(s.indexOf("rpc/class_league")>=0)return ok({ok:true,count:50,seats:[{seat:1,name:"同学甲"},{seat:2,name:"同学乙"},{seat:3,name:"同学丙"}]});
    if(s.indexOf("rpc/poll_create")>=0)return ok({ok:true,now:Date.now(),
      poll:{id:"pnew",title:"团日现场快投",description:"",mode:"quick",owner_name:"测试同学",settings:POLLSET,
        options:[{id:"o1x",text:"方案A"},{id:"o2x",text:"方案B"}],deadline:Date.now()+1800000,status:"open",closed_at:0,created_at:Date.now(),updated_at:Date.now()},
      closed:false,total:0,counts:{},has_voted:false,my_choices:[],results_hidden:false,mine:true,can_manage:true,voters:[]});
    if(s.indexOf("/site_assets")>=0)return ok([{body:{seen_at:Date.now()},updated_at:Date.now()}]);
    return ok([]);
  }
  if(s.indexOf("/drop/")>=0){
    var ds=null;try{ds=JSON.parse(localStorage.getItem("__mock_drop")||"null");}catch(e){}
    if(s.indexOf("/open")>=0){
      ds={id:"sess-opt",code:"2468",expiresAt:Date.now()+3600000,createdAt:Date.now()};
      try{localStorage.setItem("__mock_drop",JSON.stringify(ds));}catch(e){}
      return ok({ok:true,session:ds});
    }
    if(s.indexOf("/close")>=0){try{localStorage.removeItem("__mock_drop");}catch(e){}return ok({ok:true});}
    if(s.indexOf("/mine")>=0)return ok({ok:true,session:ds});
    if(s.indexOf("/state")>=0){
      if(!ds)return ok({ok:false,reason:"no session"});
      return ok({ok:true,session:ds,events:[{seq:1,kind:"file",at:Date.now(),from:{name:"测试同学"},
        payload:{fileId:"f1",name:"现场照片.jpg",size:2048,mime:"image/jpeg",downloadUrl:"#dl"}}],cursor:1});
    }
    return ok({ok:true});
  }
  if(s.indexOf("tt.json")>=0)return ok(DATA.tt);
  return ok([]);
};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:__ADMIN__,ts:Date.now()}));}catch(e){}
</script>
""".replace("__DATA__", js).replace("__SID__", SID).replace("__NAME__", NAME) \
   .replace("__ADMIN__", "true" if admin else "false")


RUNNER = r"""
<script>
(function(){
  window.__MODE="__MODE__";
  window.__opt={steps:[]};
  function T(k,ok,note){window.__opt.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
  function q(s){return document.querySelector(s);}
  function click(s){var e=q(s);if(e){e.click();return true;}return false;}
  function txt(s){var e=q(s);return e?String(e.textContent||"").trim():"";}
  function waitFor(fn,ms){return new Promise(function(res){var t0=Date.now();(function step(){try{if(fn())return res(true);}catch(e){}if(Date.now()-t0>=ms)return res(false);setTimeout(step,100);})();});}
  function toastInfo(){var t=q("#toast");return t?{text:String(t.textContent||""),err:t.classList.contains("err"),on:t.classList.contains("on"),role:t.getAttribute("role"),live:t.getAttribute("aria-live")}:null;}
  function report(slot){
    try{var x=new XMLHttpRequest();x.open("POST","/_report?slot="+slot,false);
        x.setRequestHeader("Content-Type","application/json");
        x.send(JSON.stringify({steps:window.__opt.steps,errs:window.__errs||[],cerrs:window.__cerrs||[]}));}catch(e){}
  }
  window.addEventListener("load",function(){
    setTimeout(async function(){
      try{
        for(var i=0;i<60;i++){ if(q("#aRun")&&q("#allCards"))break; await sleep(150); }
        T("页面启动（身份门禁通过）", !!q("#aRun")&&!!q("#allCards"), "");
        if(window.__MODE==="hash"){
          /* ===== 带 #tab= 直接打开 ===== */
          for(var hi=0;hi<40;hi++){ var hs=q("#s-hw"); if(hs&&hs.classList.contains("on"))break; await sleep(150); }
          var hsec=q("#s-hw");
          T("带 #tab= 打开可直达工具", !!hsec&&hsec.classList.contains("on"), String(location.hash||"")+" | "+(hsec?hsec.className:"none"));
        }else if(window.__MODE==="admin"){          /* ===== 管理员 + 微信 UA ===== */
          T("数据备份入口存在", !!q("#optBkBtn"), "");
          click('[data-tab="all"]'); await sleep(300);
          T("大屏入口（管理员）存在", !!q("#opt2StageBtn") && txt("#opt2StageBtn")==="大屏", txt("#opt2StageBtn"));
          click("#opt2StageBtn"); await sleep(400);
          var st=q("#opt2Stage");
          T("大屏弹层可打开", !!st && st.style.display!=="none", st?st.style.display:"none");
          var t1=txt("#o2sTime");
          T("右上角实时时间（时:分:秒）", /\d{2}:\d{2}:\d{2}/.test(t1), t1);
          T("顶栏日期（年月日 + 星期）", /\d{4}年\d{1,2}月\d{1,2}日/.test(txt("#o2sDate")) && /周[日一二三四五六]/.test(txt("#o2sDate")), txt("#o2sDate"));
          await sleep(1200);
          T("实时时间每秒更新", txt("#o2sTime")!==t1, t1+" -> "+txt("#o2sTime"));
          var panels=document.querySelectorAll("#opt2Stage [data-panel]");
          T("可自定义面板（演示/投票/计时/抽签）", panels.length>=4 && txt("#opt2Stage").indexOf("演示")>=0 && txt("#opt2Stage").indexOf("投票")>=0 && txt("#opt2Stage").indexOf("计时")>=0 && txt("#opt2Stage").indexOf("抽签")>=0, "panels="+panels.length);
          T("已去掉「下一节」「作业」", !q("#o2sNext") && !q("#o2sHw") && txt("#opt2Stage").indexOf("下一节")<0 && txt("#opt2Stage").indexOf("作业")<0, "");
          /* 计时面板 */
          T("大屏计时器存在", /05:00/.test(txt("#o2sTimer")), txt("#o2sTimer"));
          click('[data-o2timer="1"]'); await sleep(1300);
          T("计时器可开始倒计时", txt("#o2sTimer")!=="05:00", txt("#o2sTimer"));
          click('[data-stg="timerset"][data-min="10"]'); await sleep(150);
          T("计时快捷时长（10 分）", txt("#o2sTimer")==="10:00", txt("#o2sTimer"));
          /* 抽签面板 */
          var pick=q('[data-o2pick="1"]'); if(pick)pick.click(); await sleep(120);
          T("抽签可点（无名单也不报错）", ["—","无名单"].indexOf(txt("#o2sPick"))>=0 || String(txt("#o2sPick")).length>0, txt("#o2sPick"));
          /* PPT 面板：放映 / 兼容包下载 */
          await waitFor(function(){return !!q('#opt2Stage [data-panel="ppt"] [data-pptact="play"]');},6000);
          T("PPT 面板：主位放映按钮", !!q('#opt2Stage [data-panel="ppt"] [data-pptact="play"]'), "");
          click('#opt2Stage [data-panel="ppt"] [data-pptact="play"]');
          await waitFor(function(){return !!q("#pptPlayer");},6000);
          T("大屏在线放映 → 播放器打开", !!q("#pptPlayer"), "");
          click('#pptPlayer [data-act="close"]'); await sleep(180);
          var lv=q('#pptPlayer [data-act="leave"]'); if(lv)lv.click();
          await waitFor(function(){return !q("#pptPlayer");},5000);
          T("退出放映自动回到大屏", !q("#pptPlayer") && q("#opt2Stage").style.display!=="none", "");
          await waitFor(function(){return txt('#opt2Stage [data-panel="ppt"]').indexOf("兼容包")>=0;},5000);
          T("PPT 面板：兼容包标签（v2 下载语义）", txt('#opt2Stage [data-panel="ppt"]').indexOf("兼容包")>=0, "");
          var dlBtn=q('#opt2Stage [data-panel="ppt"] [data-pptact="dl"][data-ppt-id="d2"]');
          if(dlBtn)dlBtn.click();
          await waitFor(function(){var d=q("#pptDl");return d&&!d.hidden&&txt("#pptDl").indexOf("兼容版")>=0;},6000);
          T("PPT 面板：打开下载详情（兼容版/PDF）", !!q("#pptDl") && !q("#pptDl").hidden && txt("#pptDl").indexOf("兼容版")>=0, "btn="+!!dlBtn+" dl="+(q("#pptDl")?String(q("#pptDl").hidden):"none")+" toast="+txt("#toast").slice(0,20));
          T("PPT 详情：PowerPoint 打开（本机 Office 联动）", txt("#pptDl").indexOf("PowerPoint 打开")>=0 && !!q('#pptDl a[href^="ms-powerpoint:ofv|u|"]'), "");
          var dlx=q('#pptDl [data-dlact="close"]'); if(dlx)dlx.click();
          await sleep(250);
          T("PPT 详情可关闭", !q("#pptDl") || q("#pptDl").hidden, "");
          /* PPT：下载后按钮变「打开」（Office URI 由 hrefOf 提供） */
          try{localStorage.setItem("zq_stage_ppt_dl_v1",JSON.stringify({d2:{at:Date.now(),kind:"compat"}}));}catch(e){}
          var d1row=q('#opt2Stage [data-panel="ppt"] [data-pptsel="d1"]'); if(d1row)d1row.click(); await sleep(200);
          var d2row=q('#opt2Stage [data-panel="ppt"] [data-pptsel="d2"]'); if(d2row)d2row.click(); await sleep(250);
          var heroOpen=q('#opt2Stage [data-panel="ppt"] [data-pptact="open"]');
          var hrefOk="";try{hrefOk=String(window.PPT&&window.PPT.hrefOf?window.PPT.hrefOf("d2","compat"):"");}catch(e){}
          T("PPT：已下载 → 主按钮变「打开」", !!heroOpen && txt('#opt2Stage [data-panel="ppt"]').indexOf("已下载")>=0, "");
          T("PPT：Office 打开链接（ECS 加速）可用", hrefOk.indexOf("/pptfiles/ppt/")>=0, hrefOk.slice(0,60));
          /* 模块聚焦 / 灵动岛 / 直拖 / 模块管理（V5） */
          T("灵动岛：进行中模块汇总", !!q("#o2sIsland") && !q("#o2sIsland").hidden && txt("#o2sIsland").indexOf("进行中")>=0, txt("#o2sIsland"));
          T("顶部无「退出聚焦」按钮", !q("#o2sFocusExit"), "");
          var zb=q('#opt2Stage [data-panel="ppt"] .opt2-zbtn'); if(zb)zb.click(); await sleep(350);
          T("聚焦按钮：单面板聚焦 + 图标变缩小", !!q('#opt2Stage [data-panel="ppt"].opt2-focused') &&
            q('#opt2Stage [data-panel="vote"]').hidden===true && txt('#opt2Stage [data-panel="ppt"] .opt2-zbtn')==="⤡", txt('#opt2Stage [data-panel="ppt"] .opt2-zbtn'));
          T("聚焦时灵动岛无「退出聚焦」", txt("#o2sIsland").indexOf("退出聚焦")<0, txt("#o2sIsland"));
          T("聚焦态：演示专属全屏 UI（大标题/大按钮）", !!q('#opt2Stage [data-fv="ppt"] .opt2-ppt-ttl') && !!q('#opt2Stage [data-fv="ppt"] .opt2-play'), "");
          click('#opt2Stage [data-panel="ppt"] .opt2-zbtn'); await sleep(300);
          T("聚焦按钮：再点还原多面板", q('#opt2Stage [data-panel="vote"]').hidden===false, "");
          /* 顶部无布局按钮；直拖排序（鼠标按住表头）+ 右下拖宽 */
          T("顶部无布局/编辑模式按钮", !q("#o2sLay") && !q("#o2sLbar"), "");
          T("模块管理：顶栏「＋ 模块」入口", !!q("#o2sModBtn"), "");
          (function(){
            var root=q("#opt2Stage");
            function pe(el,type,x,y){var e=new PointerEvent(type,{bubbles:true,cancelable:true,clientX:x,clientY:y,pointerId:1,button:0,pointerType:"mouse"});el.dispatchEvent(e);}
            var h=root.querySelector('[data-panel="ppt"] [data-panelhd]');var r=h.getBoundingClientRect();
            pe(h,"pointerdown",r.left+8,r.top+8);
            var t2=root.querySelector('[data-panel="vote"]');var tr=t2.getBoundingClientRect();
            document.dispatchEvent(new PointerEvent("pointermove",{bubbles:true,cancelable:true,clientX:tr.left+Math.max(20,tr.width*0.4),clientY:tr.top+Math.max(20,tr.height*0.4),pointerId:1,button:0,pointerType:"mouse"}));
            document.dispatchEvent(new PointerEvent("pointerup",{bubbles:true,cancelable:true,clientX:tr.left+40,clientY:tr.top+40,pointerId:1,button:0,pointerType:"mouse"}));
          })(); await sleep(400);
          var hdOrder="";try{hdOrder=JSON.parse(localStorage.getItem("zq_stage_layout_v1")).order.join(",");}catch(e){}
          T("直拖：鼠标按住卡片表头可换位", hdOrder.indexOf("vote,ppt")===0, hdOrder);
          T("直拖：落位写入本机离线缓存", !!localStorage.getItem("zq_stage_layout_v1"), "");
          var rz=q('#opt2Stage [data-panel="vote"] [data-resize]');
          T("拖宽：右下角手柄存在（V5 不再依赖编辑模式；手机单列隐藏）", !!rz && document.querySelectorAll('#opt2Stage [data-resize]').length===4, "");
          (function(){
            var panel=q('#opt2Stage [data-panel="vote"]'),grip=panel.querySelector("[data-resize]");
            var r=grip.getBoundingClientRect(),colW=document.querySelector("#o2sBody").clientWidth/12;
            function pe(el,type,x,y){el.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,clientX:x,clientY:y,pointerId:2,button:0,pointerType:"mouse"}));}
            pe(grip,"pointerdown",r.left+r.width/2,r.top+r.height/2);
            document.dispatchEvent(new PointerEvent("pointermove",{bubbles:true,cancelable:true,clientX:r.left+r.width/2+colW*3,clientY:r.top+r.height/2,pointerId:2,button:0,pointerType:"mouse"}));
            document.dispatchEvent(new PointerEvent("pointerup",{bubbles:true,cancelable:true,clientX:r.left+r.width/2+colW*3,clientY:r.top+r.height/2,pointerId:2,button:0,pointerType:"mouse"}));
          })(); await sleep(300);
          var spanNow="";try{spanNow=String(JSON.parse(localStorage.getItem("zq_stage_layout_v1")).span.vote);}catch(e){}
          T("拖宽：改变宽度并持久化", spanNow!=="4" && spanNow!=="", spanNow);
          /* 模块管理弹层：移除 / 加回 */
          click("#o2sModBtn"); await sleep(250);
          T("模块管理：弹层列出 4 个模块且可增删", !!q("#o2sModModal") && !q("#o2sModModal").hidden && document.querySelectorAll("#o2sModBody .opt2-modrow").length===4, "");
          click('#o2sModBody [data-stg="modtoggle"][data-k="timer"]'); await sleep(250);
          T("模块管理：移除模块生效", q('#opt2Stage [data-panel="timer"]').hidden===true, "");
          click('#o2sModBody [data-stg="modtoggle"][data-k="timer"]'); await sleep(250);
          T("模块管理：添加回模块", q('#opt2Stage [data-panel="timer"]').hidden===false, "");
          click('#o2sModModal [data-stg="modclose"]'); await sleep(200);
          T("模块管理：关闭弹层", q("#o2sModModal").hidden===true, "");
          T("卡片表头移除按钮存在", !!q('#opt2Stage [data-panel="draw"] [data-stg="modremove"]'), "");
          /* 聚焦专属全屏 UI：计时 / 抽签 / 投票 */
          q('#opt2Stage [data-panel="timer"] .opt2-zbtn').click(); await sleep(300);
          T("聚焦态：计时超大数字 + 大按钮 + 快捷时长", !!q('#opt2Stage [data-fv="timer"]') &&
            parseFloat(getComputedStyle(q("#o2sTimer")).fontSize)>=80 && !!q('#opt2Stage [data-fv="timer"] .opt2-fv-big') &&
            document.querySelectorAll('#opt2Stage [data-fv="timer"] .opt2-tchip').length>=5, "");
          q('#opt2Stage [data-panel="timer"] .opt2-zbtn').click(); await sleep(250);
          q('#opt2Stage [data-panel="draw"] .opt2-zbtn').click(); await sleep(300);
          T("聚焦态：抽签超大结果 + 大按钮", !!q('#opt2Stage [data-fv="draw"] .opt2-fv-pick') &&
            parseFloat(getComputedStyle(q('#opt2Stage [data-fv="draw"] .opt2-fv-pick')).fontSize)>=60 &&
            !!q('#opt2Stage [data-fv="draw"] .opt2-fv-big'), "");
          click('#opt2Stage [data-fv="draw"] [data-o2pick="1"]'); await sleep(250);
          T("聚焦态：抽签结果进「最近」列表", !!q('#opt2Stage [data-fv="draw"] .opt2-fv-recent'), "");
          q('#opt2Stage [data-panel="draw"] .opt2-zbtn').click(); await sleep(250);
          q('#opt2Stage [data-panel="vote"] .opt2-zbtn').click(); await sleep(400);
          T("聚焦态：投票大号结果条 + 倒计时", !!q('#opt2Stage [data-fv="vote"]') && !!q("#o2sVoteCd") &&
            parseFloat(getComputedStyle(q("#o2sVoteCd")).fontSize)>=18, "");
          q('#opt2Stage [data-panel="vote"] .opt2-zbtn').click(); await sleep(250);
          /* 抽签名单：快捷选择团员并应用 */
          click('#opt2Stage [data-panel="draw"] [data-stg="drawroster"]'); await sleep(300);
          T("抽签名单：弹层打开", !!q("#o2sRoster") && !q("#o2sRoster").hidden, "");
          click('#o2sRoster [data-rstquick="league"]'); await sleep(500);
          T("抽签名单：团员快捷选择", q("#o2sRstSum") && txt("#o2sRstSum").indexOf("已选 3")>=0, txt("#o2sRstSum"));
          click("#o2sRstOk"); await sleep(250);
          T("抽签名单：应用并关闭", (!q("#o2sRoster") || q("#o2sRoster").hidden) && txt("#toast").indexOf("名单已更新")>=0, "");
          /* 恢复全班名单，避免后续抽签池只剩团员 */
          click('#opt2Stage [data-panel="draw"] [data-stg="drawroster"]'); await sleep(250);
          click('#o2sRoster [data-rstquick="all"]'); await sleep(150);
          click("#o2sRstOk"); await sleep(250);
          /* 互联：手机控制器（同账号自动发现会话） */
          var db2=q("#opt2DropBtn"); if(db2)db2.click(); await sleep(500);
          T("大屏互联：控制器打开并自动连上", !!q("#dropCtl") && q("#dropCtl").classList.contains("on") && txt("#dropCtl").indexOf("已连接大屏")>=0, txt("#dropCtl").slice(0,40));
          T("大屏互联：控制器含遥控/传文件/发文字", txt("#dropCtl").indexOf("遥控大屏")>=0 && txt("#dropCtl").indexOf("选择文件")>=0 && txt("#dropCtl").indexOf("发文字")>=0, "");
          click("#dropCtlClose"); await sleep(200);
          T("大屏互联：控制器可关闭", !q("#dropCtl").classList.contains("on"), "");
          /* 互联：大屏面板 */
          click("#o2sDropBtn"); await sleep(500);
          T("大屏互联：面板显示通道/房间码/链接", !!q("#o2sDropModal") && !q("#o2sDropModal").hidden &&
            txt("#o2sDropModal").indexOf("通道已开启")>=0 && txt("#o2sDropModal").indexOf("2468")>=0, "");
          T("大屏互联：收到文件/文字列表", txt("#o2sDropModal").indexOf("收到的文件")>=0 && txt("#o2sDropModal").indexOf("现场照片.jpg")>=0, "");
          try{q("#o2sDropModal").hidden=true;}catch(e){}
          click("#o2sClose"); await sleep(250);
          T("大屏可关闭", q("#opt2Stage").style.display==="none", q("#opt2Stage").style.display);
          T("关闭后恢复页面滚动", document.body.classList.contains("opt2-lock")===false, "opt2-lock="+document.body.classList.contains("opt2-lock"));
          /* 退出清理（重开后验证）：计时归零 / 抽签结果清空 / 聚焦清空；布局偏好保留 */
          var orderKeep="";try{orderKeep=JSON.parse(localStorage.getItem("zq_stage_layout_v1")).order.join(",");}catch(e){}
          click("#opt2StageBtn"); await sleep(500);
          T("退出后重开：计时归零", txt("#o2sTimer")==="05:00", txt("#o2sTimer"));
          T("退出后重开：抽签结果清空", txt("#o2sPick")==="?", txt("#o2sPick"));
          T("退出后重开：聚焦状态清空", !q('#opt2Stage .opt2-focused') && !q('#o2sBody').classList.contains("opt2-focusmode"), "");
          var orderNow="";try{orderNow=JSON.parse(localStorage.getItem("zq_stage_layout_v1")).order.join(",");}catch(e){}
          T("退出后重开：布局偏好保留", orderNow===orderKeep && !!orderKeep, orderNow+" vs "+orderKeep);
          click("#o2sClose"); await sleep(200);
          /* 微信内导出图：显示图 + 长按保存 */
          click('[data-tab="draw"]'); await sleep(200);
          click("#aRun"); await sleep(400);
          var cells=document.querySelectorAll("#aOut .rcell").length;
          T("抽签出结果", cells===10, "rcell="+cells);
          click("#aImg");
          await waitFor(function(){var o=q("#opt2ExpOv");return o&&o.style.display!=="none";},6000);
          await sleep(150);
          var ov=q("#opt2ExpOv"), img=q("#opt2ExpImg");
          T("微信内导出：出现图片弹层", !!ov && ov.style.display!=="none", ov?ov.style.display:"none");
          T("微信内导出：图片已生成", !!img && /^(blob:|data:)/.test(String(img.getAttribute("src")||"")), img?String(img.getAttribute("src")).slice(0,24):"");
          T("微信内导出：提示长按保存", txt("#opt2ExpOv").indexOf("长按")>=0, txt("#opt2ExpOv").slice(0,40));
          var w2=q(".wrap");
          T("导出弹层打开时背景 inert", w2&&("inert" in w2)&&w2.inert===true, w2&&("inert" in w2)?String(w2.inert):"no-inert");
          click("#opt2ExpClose");
          await waitFor(function(){var o=q("#opt2ExpOv");return !o||o.style.display==="none";},3000);
          T("导出弹层可关闭 + inert 复原", (!q("#opt2ExpOv")||q("#opt2ExpOv").style.display==="none") && (!("inert" in w2) || w2.inert===false), q("#opt2ExpOv")?q("#opt2ExpOv").style.display:"none");
          /* 名单工具：班委 / 团员 / 全班 */
          var cmCard=document.querySelector('#allCards [data-open="committee"]'); if(cmCard)cmCard.click();
          await waitFor(function(){var s=q("#s-committee");return s&&s.classList.contains("on");},5000);
          T("名单工具：三 tab（班委/团员/全班）", document.querySelectorAll("#cmTabs [data-cmtab]").length===3, "");
          T("名单工具：班委 tab 计数与列表", txt("#cmCntC")==="3" && document.querySelectorAll("#cmOut .cmrow").length===3, txt("#cmCntC")+"/"+document.querySelectorAll("#cmOut .cmrow").length);
          T("名单工具：行内无重复「班委」badge（保留职务文字）", document.querySelectorAll("#cmOut .cmbadge").length===0 &&
            document.querySelectorAll("#cmOut .cmrole").length>=1, "cmbadge="+document.querySelectorAll("#cmOut .cmbadge").length+" cmrole="+document.querySelectorAll("#cmOut .cmrole").length);
          click('#cmTabs [data-cmtab="league"]');
          await waitFor(function(){return txt("#cmCntL")!=="";},6000);
          await sleep(300);
          T("名单工具：团员 tab（class_league）", txt("#cmCntL")==="3" && document.querySelectorAll("#cmOut .cmrow").length===3, "cnt="+txt("#cmCntL")+" rows="+document.querySelectorAll("#cmOut .cmrow").length+" txt="+txt("#cmOut").slice(0,40));
          click('#cmTabs [data-cmtab="all"]'); await sleep(300);
          T("名单工具：全班 tab 70 人", txt("#cmCntA")==="70" && document.querySelectorAll("#cmOut .cmrow").length===70, txt("#cmCntA")+"/"+document.querySelectorAll("#cmOut .cmrow").length);

        }else{
          /* ===== 非管理员、普通 UA ===== */
          T("toast 具备 ARIA live", !!q("#toast") && q("#toast").getAttribute("role")==="status" && q("#toast").getAttribute("aria-live")==="polite", q("#toast")?q("#toast").getAttribute("role"):"none");
          /* 抽签错误 → 错误样式 toast */
          q("#aStart").value="1"; q("#aEnd").value="1"; q("#aCount").value="5";
          click("#aRun"); await sleep(250);
          var ti=toastInfo();
          T("抽签校验错误 → toast.err", !!ti && ti.err===true, ti?ti.text:"none");
          /* 预设保存/载入 */
          T("预设控件存在", !!q("#opt2PresetRow")&&!!q("#opt2PreSave")&&!!q("#opt2PreLoad"), "");
          q("#aStart").value="3"; q("#aEnd").value="9"; q("#aCount").value="4";
          click("#opt2PreSave"); await sleep(150);
          q("#aStart").value="1"; q("#aEnd").value="2"; q("#aCount").value="1";
          click("#opt2PreLoad"); await sleep(150);
          T("预设保存后可载入", q("#aStart").value==="3" && q("#aEnd").value==="9" && q("#aCount").value==="4",
            [q("#aStart").value,q("#aEnd").value,q("#aCount").value].join("/"));
          /* 汇总入口 + 无数据错误 */
          T("点名汇总入口存在", !!q("#opt2RollSum"), "");
          T("水量汇总入口存在", !!q("#opt2WaterSum"), "");
          click("#opt2RollSum"); await sleep(200);
          T("点名无名单 → 错误提示", toastInfo() && toastInfo().err && String(toastInfo().text).indexOf("点名名单")>=0, toastInfo()?toastInfo().text:"");
          click("#opt2WaterSum"); await sleep(200);
          T("水量无记录 → 错误提示", toastInfo() && String(toastInfo().text).indexOf("抄表")>=0, toastInfo()?toastInfo().text:"");
          /* hash 直达 */
          click('[data-tab="hw"]'); await sleep(300);
          T("切工具写入 #tab= 直达", String(location.hash||"")==="#tab=hw", String(location.hash||""));
          var hset="";
          try{ history.replaceState(history.state||{},"","#tab=draw"); hset=String(location.hash||""); window.dispatchEvent(new Event("hashchange")); }catch(e){ hset="ERR:"+(e&&e.message||e); }
          await waitFor(function(){var s=q("#s-draw");return s&&s.classList.contains("on");},3000);
          var sec=q("#s-draw");
          T("hashchange 可切回工具", !!sec && sec.classList.contains("on"), "set="+hset+" now="+String(location.hash||"")+" cls="+(sec?sec.className:"none"));
          /* 打印按钮 + 备份存储用量 */
          T("打印入口存在（作业/结果单）", !!q("#opt2Print_hImg")&&!!q("#opt2Print_sImg"), "");
          T("非管理员无大屏入口", !q("#opt2StageBtn"), "");
          click('[data-tab="all"]'); await sleep(300);
          click("#optBkBtn"); await sleep(500);
          T("备份弹层显示本机存储用量", txt("#opt2BkUsage").indexOf("本机存储")>=0, txt("#opt2BkUsage"));
          click("#optBkClose"); await sleep(120);
        }
        T("0 JS 报错", (window.__errs||[]).length===0, JSON.stringify(window.__errs||[]).slice(0,400));
        T("0 console.error", (window.__cerrs||[]).length===0, JSON.stringify(window.__cerrs||[]).slice(0,400));
      }catch(e){
        window.__opt.steps.push({k:"脚本异常",ok:false,note:String(e&&e.stack||e)});
      }
      report(window.__MODE||"main");
    }, 900);
  });
})();
</script>
"""


def build_preview(name, admin, mode):
    html = open(SRC, encoding="utf-8", newline="").read()
    html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock_head(admin), 1)
    runner = RUNNER.replace("__MODE__", mode)
    html = html.replace("</body>", runner + "\n</body>", 1)
    path = os.path.join(HERE, name)
    open(path, "w", encoding="utf-8", newline="").write(html)
    return name


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        slot = "main"
        try:
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            slot = (q.get("slot") or ["main"])[0]
        except Exception:
            pass
        open(os.path.join(HERE, "report_%s.json" % slot), "wb").write(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def run_one(page, slot, wx, suffix="", timeout=100):
    report = os.path.join(HERE, "report_%s.json" % slot)
    if os.path.exists(report):
        os.remove(report)
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
            "--force-device-scale-factor=1", "--window-size=430,940",
            "--virtual-time-budget=45000"]
    if wx:
        args.append("--user-agent=" + WX_UA)
    args.append("http://127.0.0.1:%d/%s%s" % (PORT, page, suffix))
    subprocess.run(args, capture_output=True, timeout=timeout)
    data = None
    for _ in range(40):
        if os.path.exists(report):
            time.sleep(0.2)
            try:
                data = json.loads(open(report, encoding="utf-8", errors="replace").read())
                break
            except Exception:
                pass
        time.sleep(0.3)
    return data


def main():
    socketserver.TCPServer.allow_reuse_address = True
    Handler2 = functools.partial(Handler, directory=HERE)
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler2)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    bad = 0
    try:
        p1 = build_preview("v2_check_main.html", False, "main")
        p2 = build_preview("v2_check_admin.html", True, "admin")
        p3 = build_preview("v2_check_hash.html", False, "hash")
        for page, slot, wx, suf in ((p1, "main", False, ""), (p2, "admin", True, ""), (p3, "hash", False, "#tab=hw")):
            print("===== %s =====" % slot)
            data = run_one(page, slot, wx, suf)
            if not data:
                print("FAIL: 未收到 %s 报告" % slot)
                bad += 1
                continue
            for s in data.get("steps", []):
                ok = bool(s.get("ok"))
                if not ok:
                    bad += 1
                print("%s  %s%s" % ("PASS" if ok else "FAIL", s.get("k", ""),
                                    ("  [" + str(s.get("note", "")) + "]") if s.get("note") else ""))
            if data.get("errs"):
                print("JS-ERR ", data["errs"][:5])
            if data.get("cerrs"):
                print("CONSOLE-ERR ", data["cerrs"][:5])
        print("RESULT %s (%d fails)" % ("GREEN" if bad == 0 else "RED", bad))
        return 0 if bad == 0 else 1
    finally:
        httpd.shutdown()
        for n in ("v2_check_main.html", "v2_check_admin.html", "v2_check_hash.html"):
            try:
                os.remove(os.path.join(HERE, n))
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
