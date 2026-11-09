# -*- coding: utf-8 -*-
"""自检：班级名单选择器 + 简约名单气泡（web 端名单改造专项）
用法：python tests\\roster_check.py

做法：
- 复制 index.html 到临时预览页，注入「假身份 + 合成 70 人班级名单 + 旧自定义名单数据」，
  并拦截 tcloudbasegateway / tt.json 请求（不碰真实云端，不出现真实班级名单）；
- 用 headless Edge + 同源 iframe 固定宽度驱动（headless 视口恒为 ~492px，不能靠 --window-size）；
- 断言：旧数据迁移、弹层 70 气泡 / 全选 / 清空 / 计数 / 确定写回、页面摘要气泡、
  抽签池语义（选名单后只从名单抽）、分组选择名单、点名状态按姓名保留、
  360/390/430/720/1280 无横向溢出、0 JS 报错；
- 截图到 tests/_shots_roster/（合成姓名）。
退出码 0 = 全绿。
"""
import os, sys, io, json, re, time, shutil, tempfile, threading, http.server, socketserver, functools, subprocess, urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))          # tools/tests
ROOT = os.path.dirname(HERE)                                # tools
SRC = os.path.join(ROOT, "index.html")
SHOTS = os.path.join(HERE, "_shots_roster")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8913
BASE = "http://127.0.0.1:%d/" % PORT

SID = "3260709999"
NAME = "测试同学"
MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": "", "badge": "", "is_admin": False} for i in range(1, 71)]

SEED = {
    "members": MEMBERS,
    # 旧自定义/班级名单文本：2 个合法姓名 + 1 个不存在姓名（应被丢弃）
    "roster": "1 同学01\n2 同学02\n99 不存在的同学",
    "group": {"source": "prev", "names": "同学03\n同学05\n不存在的同学",
              "mode": "groups", "n": 2, "shuffle": False},
    "rollNames": "同学07\n同学09\n不存在的同学",
    "rollSt": {"0": "in", "2": "ab"},
    "draw": {"start": 1, "end": 70, "count": 10, "dup": False, "excl": "", "sort": "draw"},
}

PREVIEW = "_roster_preview.html"
PREVIEW_GATE = "_roster_preview_gate.html"
HARNESS_FUNC = "_roster_harness_func.html"
HARNESS_LAYOUT = "_roster_harness_layout.html"
HARNESS_SHOT = "_roster_harness_shot.html"
HARNESS_RM = "_roster_harness_rm.html"

REPORT_DIR = os.path.join(HERE, "_roster_reports")

# ---------------------------------------------------------------- 注入脚本
INJECT = """<script>
(function(){
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));_ce.apply(console,arguments);};
var _f=window.fetch;window.fetch=function(u,o){var s=String(u||"");if(s.indexOf("tcloudbasegateway")>=0||s.indexOf("tt.json")>=0)return Promise.reject(new Error("test-block"));return _f.apply(this,arguments);};
__LOCAL__
})();
</script>"""

LOCAL_MAIN = ('try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"test-token-roster",'
              'sid:"%s",name:"%s",role:"",badge:"",is_admin:false,ts:Date.now()}));'
              'localStorage.setItem("zq_tools_v2_%s",JSON.stringify(%s));}catch(e){}'
              % (SID, NAME, SID, json.dumps(SEED, ensure_ascii=False)))
LOCAL_GATE = 'try{localStorage.removeItem("zq_class_identity");localStorage.removeItem("zq_tools_v2_%s");}catch(e){}' % SID


def build_previews():
    html = open(SRC, encoding="utf-8").read()
    for name, local in ((PREVIEW, LOCAL_MAIN), (PREVIEW_GATE, LOCAL_GATE)):
        inject = INJECT.replace("__LOCAL__", local)
        out = html.replace("<head>", "<head>" + inject, 1)
        open(os.path.join(HERE, name), "w", encoding="utf-8").write(out)


# ---------------------------------------------------------------- 前端测试 JS
COMMON_JS = r"""
var SRC="__SRC__", GATE="__GATE__", SID="__SID__", STORE="zq_tools_v2_"+SID;
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
function waitFor(fn,ms){return new Promise(function(res,rej){var t0=Date.now();
  (function loop(){var v=false;try{v=!!fn();}catch(e){v=false;}
    if(v)return res(true);
    if(Date.now()-t0>(ms||4000))return rej(new Error("waitFor timeout"));
    setTimeout(loop,25);})();});}
function mount(src,w,h){
  return new Promise(function(res,rej){
    var old=document.getElementById("fr"); if(old&&old.parentNode)old.parentNode.removeChild(old);
    var f=document.createElement("iframe"); f.id="fr"; f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block";
    f.src=src;
    var done=false;
    f.onload=function(){ if(done)return; done=true; setTimeout(function(){res(f);},100); };
    f.onerror=function(){ if(done)return; done=true; rej(new Error("iframe load failed: "+src)); };
    document.body.appendChild(f);
    setTimeout(function(){ if(!done){done=true;res(f);} },8000);
  });
}
function q(f,s){return f.contentDocument.querySelector(s);}
function qa(f,s){return Array.prototype.slice.call(f.contentDocument.querySelectorAll(s));}
function click(f,s){var e=q(f,s); if(!e)throw new Error("missing element: "+s); e.click(); return e;}
function txt(f,s){var e=q(f,s); return e?e.textContent:"";}
function cntRst(f){var t=q(f,"#rosterModal .rst-cnt"); return t?t.textContent.replace(/\s+/g," ").trim():"";}
function loadState(f){try{return JSON.parse(f.contentWindow.localStorage.getItem(STORE)||"null")||{};}catch(e){return {};}}
function jsonEq(a,b){return JSON.stringify(a)===JSON.stringify(b);}
function report(slot,data){
  data=data||{}; data.slot=slot;
  /* 同步 XHR：headless --virtual-time-budget 在 budget 用尽即退出，异步 fetch 可能来不及送出 */
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
  var R={steps:[],errors:null,files:{}};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    /* ---- A. 门禁回归：无身份仍停在身份页 ---- */
    var g=await mount(GATE,430,900);
    await sleep(250);
    var gd=g.contentDocument;
    T("未登录仍停在身份页", gd.body.classList.contains("id-locked") && gd.querySelector("#idgate") && getComputedStyle(gd.querySelector("#idgate")).display!=="none");

    /* ---- B. 注入假身份 + 合成名单 + 旧数据 ---- */
    var f=await mount(SRC,430,900), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},6000);
    await sleep(200);

    var ext=(w.performance.getEntriesByType("resource")||[]).filter(function(e){
      return !/^https?:\/\/127\.0\.0\.1[:/]/.test(e.name) && !/^data:/.test(e.name) && !/^blob:/.test(e.name);
    }).map(function(e){return e.name;});
    T("页面无外部请求", ext.length===0, ext.join(","));

    /* ---- C. 旧数据迁移 ---- */
    var st=loadState(f);
    T("迁移：旧 roster 文本 → rosterSel（丢弃不存在姓名）", jsonEq(st.rosterSel,[1,2]), JSON.stringify(st.rosterSel));
    T("迁移：rosterMigrated 标记", st.rosterMigrated===true);
    T("迁移：派生 roster 文本 2 行", (st.roster||"")==="1 同学01\n2 同学02", JSON.stringify(st.roster));
    T("迁移：旧 group.names → groupSel", jsonEq(st.groupSel,[3,5]), JSON.stringify(st.groupSel));
    T("迁移：group.names 派生（仅姓名，按座号升序）", st.group && st.group.names==="同学03\n同学05", st.group && JSON.stringify(st.group.names));
    T("迁移：旧 rollNames → rollSel", jsonEq(st.rollSel,[7,9]), JSON.stringify(st.rollSel));
    T("迁移：rollNames 派生（座号升序）", st.rollNames==="7 同学07\n9 同学09", JSON.stringify(st.rollNames));
    T("迁移：rollSt 按姓名保留并重排索引", jsonEq(st.rollSt,{"0":"in"}), JSON.stringify(st.rollSt));
    T("旧 classRoster 字段已清空", !st.classRoster);

    /* ---- D. 页面摘要气泡（不可输入） ---- */
    T("页面摘要气泡 2 个", qa(f,"#aRosterSum button.rchip").length===2, qa(f,"#aRosterSum button.rchip").length);
    T("摘要显示名字不含座号", txt(f,"#aRosterSum").indexOf("同学01")>=0 && txt(f,"#aRosterSum").indexOf("1 同学")<0, txt(f,"#aRosterSum"));
    T("名单行无 textarea", qa(f,"#p1 textarea").length===0);

    /* ---- E. 弹层：70 气泡 / 计数 / 清空 / 全选 / 确定 ---- */
    click(f,"#aRosterPick");
    await waitFor(function(){var m=q(f,"#rosterModal");return m&&m.style.display!=="none";},4000);
    await sleep(120);
    T("弹层打开 + 标题", q(f,"#rosterModal").classList.contains("on") && q(f,"#rstTitle").textContent==="选择抽签名单", jsonEq(q(f,"#rstTitle").textContent,"选择抽签名单"));
    T("弹层 70 个气泡", qa(f,"#rstTxt .rst-b").length===70, qa(f,"#rstTxt .rst-b").length);
    var b1=q(f,'#rstTxt .rst-b[data-seat="1"]');
    var c1=w.getComputedStyle(b1);
    T("气泡是简约 option chip（平铺实底 / 无渐变 / 无高光伪元素 / 无持续动画）",
      c1.backgroundColor!=="rgba(0, 0, 0, 0)" && c1.backgroundImage==="none"
        && w.getComputedStyle(b1,"::before").backgroundImage==="none" && c1.animationName==="none",
      c1.backgroundColor+" | "+c1.backgroundImage+" | anim="+c1.animationName);
    T("无 goo 层 / SVG 滤镜（无白洞风险）", q(f,"#rstGoo")===null && !/url\(/.test((q(f,"#rstTxt").parentNode.style.filter||"")));
    T("气泡含名字与小号座号", q(f,'#rstTxt .rst-b[data-seat="1"] .nm').textContent==="同学01" && q(f,'#rstTxt .rst-b[data-seat="1"] .ss').textContent==="1");
    T("座号小字低调（10.5px / 未选 opacity .45 / 与名字间隔 4px）",
      (function(){var s=w.getComputedStyle(q(f,'#rstTxt .rst-b[data-seat="70"] .ss'));return s.fontSize==="10.5px" && s.opacity==="0.45";})()
        && w.getComputedStyle(q(f,'#rstTxt .rst-b[data-seat="70"]')).gap==="4px",
      (function(){var s=w.getComputedStyle(q(f,'#rstTxt .rst-b[data-seat="70"] .ss'));return s.fontSize+"/"+s.opacity;})()+" gap="+w.getComputedStyle(q(f,'#rstTxt .rst-b[data-seat="70"]')).gap);
    T("计数 已选 2 / 70", /已选 2 \/ 70/.test(cntRst(f)), cntRst(f));
    click(f,"#rstNoneBtn");
    T("清空 → 0 / 70", /已选 0 \/ 70/.test(cntRst(f)) && qa(f,"#rstTxt .rst-b.on").length===0, cntRst(f));
    click(f,"#rstAllBtn");
    T("全选 → 70 / 70", /已选 70 \/ 70/.test(cntRst(f)) && qa(f,"#rstTxt .rst-b.on").length===70, cntRst(f));
    click(f,"#rstOk");
    await sleep(120);
    T("确定后关闭弹层", q(f,"#rosterModal").style.display==="none");
    st=loadState(f);
    T("确定写回 rosterSel=70（升序 1..70）", st.rosterSel.length===70 && st.rosterSel[0]===1 && st.rosterSel[69]===70);
    T("确定写回派生 roster 70 行", (st.roster||"").split("\n").length===70);
    T("页面摘要：12 气泡 + 「+58」", qa(f,"#aRosterSum button.rchip").length===12 && /\+58/.test(txt(f,"#aRosterSum")), txt(f,"#aRosterSum").slice(0,60));
    T("提示：已选 70 人 · 抽签池 70", /已选 70 人/.test(txt(f,"#aPoolHint")) && /抽签池 70/.test(txt(f,"#aPoolHint")), txt(f,"#aPoolHint"));

    /* ---- F. 抽签：结果全部带姓名且属于名单 ---- */
    q(f,"#aStart").value="1"; q(f,"#aEnd").value="70"; q(f,"#aCount").value="10";
    click(f,"#aRun");
    await sleep(80);
    var cells=qa(f,"#aOut .rcell");
    var allNamed=cells.length===10 && cells.every(function(c){var n=c.querySelector(".rname");return n&&n.textContent.trim();});
    T("抽 10 个且全部带姓名", allNamed, cells.length);
    T("抽签结果均属于参与名单", cells.every(function(c){var n=+c.getAttribute("data-n");return n>=1&&n<=70;}));

    /* ---- G. 只选 3 人 → 抽签池=3；超池明确提示 ---- */
    click(f,"#aRosterPick"); await waitFor(function(){return q(f,"#rosterModal").style.display!=="none";},4000); await sleep(80);
    click(f,"#rstNoneBtn");
    [3,8,21].forEach(function(seat){var b=q(f,'#rstTxt .rst-b[data-seat="'+seat+'"]'); if(b)b.click();});
    T("逐个点气泡计数 3 / 70", /已选 3 \/ 70/.test(cntRst(f)), cntRst(f));
    click(f,"#rstOk"); await sleep(120);
    st=loadState(f);
    T("3 人写回 rosterSel=[3,8,21]", jsonEq(st.rosterSel,[3,8,21]), JSON.stringify(st.rosterSel));
    T("提示：已选 3 人 · 抽签池 3", /已选 3 人/.test(txt(f,"#aPoolHint")) && /抽签池 3/.test(txt(f,"#aPoolHint")), txt(f,"#aPoolHint"));
    q(f,"#aCount").value="10";
    click(f,"#aRun"); await sleep(60);
    T("超池提示（抽签池只有 3 人）", /抽签池只有 3 人/.test(txt(f,"#toast")), txt(f,"#toast"));
    T("超池不产生新结果", qa(f,"#aOut .rcell").length===10);
    q(f,"#aCount").value="3";
    click(f,"#aRun"); await sleep(60);
    var nums3=qa(f,"#aOut .rcell").map(function(c){return +c.getAttribute("data-n");});
    T("3 人抽签池抽 3 个且都在名单内", nums3.length===3 && nums3.every(function(n){return [3,8,21].indexOf(n)>=0;}), JSON.stringify(nums3));

    /* ---- H. 分组：选择名单（5 人 → 2 组 5 人） ---- */
    click(f,"[data-step='2']");
    click(f,'input[name=gsrc][value="names"]');
    T("分组来源「选择名单」显示摘要区", q(f,"#gNamesWrap").style.display!=="none" && txt(f,"#gNamesWrap").indexOf("选择名单")>=0);
    click(f,"#gRosterPick"); await waitFor(function(){return q(f,"#rosterModal").style.display!=="none";},4000); await sleep(80);
    T("分组弹层标题", q(f,"#rstTitle").textContent==="选择分组名单", q(f,"#rstTitle").textContent);
    T("分组初始选中 = 当前 groupSel（2）", /已选 2 \/ 70/.test(cntRst(f)), cntRst(f));
    click(f,"#rstNoneBtn");
    [2,4,6,8,10].forEach(function(seat){var b=q(f,'#rstTxt .rst-b[data-seat="'+seat+'"]'); if(b)b.click();});
    click(f,"#rstOk"); await sleep(120);
    st=loadState(f);
    T("分组 5 人写回 groupSel", jsonEq(st.groupSel,[2,4,6,8,10]), JSON.stringify(st.groupSel));
    q(f,"#gNum").value="2";
    click(f,"#gRun"); await sleep(80);
    var gc=qa(f,"#gOut .gcard"), spans=qa(f,"#gOut .gcard .bd span");
    T("分组结果 2 组共 5 人", gc.length===2 && spans.length===5, gc.length+"组/"+spans.length+"人");
    T("分组结果带姓名", spans.length===5 && spans.every(function(s){var b=s.querySelector("b");return b&&b.textContent.trim();}), spans.map(function(s){return s.textContent;}).join("|"));

    /* ---- I. 点名：迁移状态 / 选择名单 / 沿用抽签名单 ---- */
    click(f,"[data-tab='all']"); await sleep(60);
    click(f,"[data-open='roll']"); await sleep(100);
    T("点名页渲染迁移名单 2 人", qa(f,"#rGrid .rcard").length===2, qa(f,"#rGrid .rcard").length);
    T("点名状态按姓名保留（同学07 = 已到）", qa(f,"#rGrid .rcard.in").length===1 && txt(f,"#rGrid .rcard.in .rnm").indexOf("同学07")>=0, txt(f,"#rGrid"));
    T("点名名单行无 textarea", qa(f,"#s-roll textarea").length===0);
    click(f,"#rPickSel"); await waitFor(function(){return q(f,"#rosterModal").style.display!=="none";},4000); await sleep(80);
    T("点名弹层标题", q(f,"#rstTitle").textContent==="选择点名名单", q(f,"#rstTitle").textContent);
    click(f,"#rstNoneBtn");
    [7,8,9,10,11].forEach(function(seat){var b=q(f,'#rstTxt .rst-b[data-seat="'+seat+'"]'); if(b)b.click();});
    click(f,"#rstOk"); await sleep(120);
    st=loadState(f);
    T("点名新名单 5 人（座号升序）", (st.rollNames||"").split("\n").length===5 && (st.rollNames||"").indexOf("7 同学07")===0, JSON.stringify(st.rollNames));
    T("点名状态跨名单按姓名保留（新索引 0 仍是同学07）", jsonEq(st.rollSt,{"0":"in"}), JSON.stringify(st.rollSt));
    T("点名网格 5 人 + 1 已到", qa(f,"#rGrid .rcard").length===5 && qa(f,"#rGrid .rcard.in").length===1);
    click(f,"#rImportDraw"); await sleep(80);
    st=loadState(f);
    T("沿用抽签名单 → rollSel=[3,8,21]", jsonEq(st.rollSel,[3,8,21]), JSON.stringify(st.rollSel));
    T("沿用后点名网格 3 人", qa(f,"#rGrid .rcard").length===3, qa(f,"#rGrid .rcard").length);

    /* ---- J. 取消 / Esc / 遮罩 不写回；清空占位 ---- */
    click(f,"[data-tab='draw']"); await sleep(60);
    var before=JSON.stringify(loadState(f).rosterSel);
    click(f,"#aRosterPick"); await waitFor(function(){return q(f,"#rosterModal").style.display!=="none";},4000); await sleep(60);
    var b5=q(f,'#rstTxt .rst-b[data-seat="5"]'); if(b5)b5.click();
    click(f,"#rstCancel"); await sleep(120);
    T("取消不写回", JSON.stringify(loadState(f).rosterSel)===before && q(f,"#rosterModal").style.display==="none", before+"→"+JSON.stringify(loadState(f).rosterSel));
    click(f,"#aRosterPick"); await waitFor(function(){return q(f,"#rosterModal").style.display!=="none";},4000); await sleep(60);
    d.dispatchEvent(new (w.KeyboardEvent)("keydown",{key:"Escape",bubbles:true}));
    await sleep(100);
    T("Esc 关闭（取消）", q(f,"#rosterModal").style.display==="none");
    click(f,"#aRosterPick"); await waitFor(function(){return q(f,"#rosterModal").style.display!=="none";},4000); await sleep(60);
    q(f,"#rosterModal").dispatchEvent(new (w.MouseEvent)("click",{bubbles:true}));
    await sleep(100);
    T("遮罩点击关闭", q(f,"#rosterModal").style.display==="none");
    T("关闭后滚动恢复", !d.body.classList.contains("rst-lock"));
    click(f,"#aRosterClear"); await sleep(80);
    st=loadState(f);
    T("清空参与名单 → 空数组 + 灰字占位", jsonEq(st.rosterSel,[]) && /未选择/.test(txt(f,"#aRosterSum")), txt(f,"#aRosterSum"));
    T("空名单提示抽签池 70 个序号", /抽签池 70 个序号/.test(txt(f,"#aPoolHint")), txt(f,"#aPoolHint"));

    /* ---- K. 0 JS 报错 ---- */
    R.errors={win:(w.__errs||[]).slice(),cerr:(w.__cerrs||[]).slice()};
    T("0 JS 报错", R.errors.win.length===0, R.errors.win.join(" | "));
    T("0 console.error", R.errors.cerr.length===0, R.errors.cerr.join(" | "));
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("func",R);
}
run();
"""

LAYOUT_JS = r"""
async function run(){
  var R={steps:[],errors:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var W=__W__, f=await mount(SRC,W,820), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},7000);
    await sleep(150);
    /* 布局审计不掺入入场/浮动动画（动画只影响 transform，不改变布局） */
    var ns=d.createElement("style");
    ns.textContent=".roster-modal.on .rst-sheet{animation:none!important}.rst-b{animation:none!important}.rchip{animation:none!important}";
    d.head.appendChild(ns);
    var de=d.documentElement;
    function ov(){return {sw:de.scrollWidth,cw:de.clientWidth,iw:w.innerWidth,bsw:d.body.scrollWidth,bcw:d.body.clientWidth};}
    var o=ov();
    T("页面无横向溢出（关闭弹层）", o.sw<=o.cw+1 && o.bsw<=o.bcw+1, JSON.stringify(o));
    click(f,"#aRosterPick");
    await waitFor(function(){var m=q(f,"#rosterModal");return m&&m.style.display!=="none";},5000);
    await sleep(650);
    o=ov();
    T("弹层打开无横向溢出", o.sw<=o.cw+1 && o.bsw<=o.bcw+1, JSON.stringify(o));
    var sr=q(f,"#rstSheet").getBoundingClientRect();
    T("弹层在视口内", sr.left>=-1 && sr.right<=w.innerWidth+1 && sr.top>=-1 && sr.bottom<=w.innerHeight+1, JSON.stringify({l:sr.left,r:sr.right,t:sr.top,b:sr.bottom,vw:w.innerWidth,vh:w.innerHeight}));
    T("弹层高度 ≤ 88vh", sr.height<=w.innerHeight*0.881+1, sr.height+"/"+w.innerHeight);
    T("弹层 70 个气泡", qa(f,"#rstTxt .rst-b").length===70, qa(f,"#rstTxt .rst-b").length);
    var bh=q(f,"#rstTxt .rst-b").getBoundingClientRect().height;
    T("气泡可点区域 ≥ 40px", bh>=39.5, bh);
    var sc=q(f,"#rstScroll");
    T("弹层内部滚动区可用", sc.scrollHeight>=sc.clientHeight, sc.scrollHeight+"/"+sc.clientHeight);
    T("弹层滚动区无横向溢出", sc.scrollWidth<=sc.clientWidth+1, sc.scrollWidth+"/"+sc.clientWidth);
    click(f,"#rstCancel"); await sleep(120);
    T("取消后关闭并恢复滚动", q(f,"#rosterModal").style.display==="none" && !d.body.classList.contains("rst-lock"));
    o=ov(); T("关闭弹层后仍无横向溢出", o.sw<=o.cw+1, JSON.stringify(o));
    /* 点名页（含摘要气泡） */
    click(f,"[data-tab='all']"); await sleep(60); click(f,"[data-open='roll']"); await sleep(120);
    o=ov(); T("点名页无横向溢出", o.sw<=o.cw+1 && o.bsw<=o.bcw+1, JSON.stringify(o));
    R.errors=(w.__errs||[]).slice();
    T("0 JS 报错", R.errors.length===0, R.errors.join(" | "));
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("layout_"+__W__,{width:__W__,steps:R.steps});
}
run();
"""

SHOT_JS = r"""
async function run(){
  var R={steps:[],diag:{},ok:false,mode:""};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var hash=(location.hash||"#mixed390").replace("#","");
    var m=hash.match(/^(all|mixed|none|page)(1280|390)$/);
    var state=m?m[1]:"mixed", desktop=m?m[2]==="1280":false;
    R.mode=hash;
    var W=desktop?1280:390, H=desktop?900:844;
    var f=await mount(SRC,W,H), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},7000);
    await sleep(300);
    /* iframe 尺寸变化时顶部工具栏会播放液体重排动画：截图前定格并清掉内联位移，避免截到飞出状态 */
    var base=d.createElement("style");
    base.textContent=".tabs button,.tabs-thumb{transition:none!important;animation:none!important}";
    d.head.appendChild(base);
    if(desktop){ try{w.dispatchEvent(new w.Event("resize"));}catch(e){} await sleep(250); }
    qa(f,"#tabsBar button").forEach(function(b){b.style.transition="none";b.style.transform="";b.style.opacity="";});
    await sleep(120);
    R.diag.tabs=qa(f,"#tabsBar button").length;
    R.diag.iw=w.innerWidth;
    if(desktop) T("桌面 1280 工具栏 5 格（4 工具 + 全部）", R.diag.tabs===5, R.diag.tabs+" 格 / iw="+R.diag.iw);

    if(state==="page"){
      click(f,"#aRosterPick");
      await waitFor(function(){var mm=q(f,"#rosterModal");return mm&&mm.style.display!=="none";},5000);
      click(f,"#rstAllBtn"); await sleep(100);
      click(f,"#rstOk"); await sleep(300);
    }else{
      click(f,"#aRosterPick");
      await waitFor(function(){var mm=q(f,"#rosterModal");return mm&&mm.style.display!=="none";},5000);
      /* 定格动画帧：浮动暂停后截图稳定；关掉入场动画避免半透明中间帧 */
      var ns=d.createElement("style");
      ns.textContent=".roster-modal.on .rst-sheet{animation:none!important}.rst-b,.rchip{animation-play-state:paused !important}";
      d.head.appendChild(ns);
      await sleep(150);
      if(state==="all"){ click(f,"#rstAllBtn"); await sleep(150); }
      else if(state==="none"){ click(f,"#rstNoneBtn"); await sleep(150); }
      else if(state==="mixed"){
        for(var i=1;i<=36;i++){var b=q(f,'#rstTxt .rst-b[data-seat="'+i+'"]'); if(b&&!b.classList.contains("on"))b.click();}
        await sleep(150);
      }
      /* 视觉校验：简约 option chip 规格 */
      var on=qa(f,"#rstTxt .rst-b.on").length;
      T(state+" 选中数正确", state==="all"?on===70:(state==="mixed"?on===36:on===0), on);
      var tb=q(f,'#rstTxt .rst-b[data-seat="70"]'), tb1=q(f,'#rstTxt .rst-b[data-seat="1"]');
      var cs70=w.getComputedStyle(tb), cs1=w.getComputedStyle(tb1);
      T("气泡平铺实底（未选奶白 / 无渐变）",
        cs70.backgroundColor!=="rgba(0, 0, 0, 0)" && cs70.backgroundColor!=="transparent" && cs70.backgroundImage==="none",
        cs70.backgroundColor+"|"+cs70.backgroundImage);
      T("已选=浅青底 + teal 边/字", state==="none" ? true :
        (cs1.backgroundColor==="rgb(241, 247, 245)" && cs1.borderTopColor==="rgb(94, 143, 135)" && cs1.color==="rgb(94, 143, 135)"),
        cs1.backgroundColor+"/"+cs1.borderTopColor+"/"+cs1.color);
      T("选中/未选视觉可区分", state==="mixed" ? cs1.backgroundColor!==cs70.backgroundColor : true);
      T("无高光伪元素 / 无持续动画",
        w.getComputedStyle(tb1,"::before").backgroundImage==="none" && cs70.animationName==="none");
      T("弹层无横向溢出", d.documentElement.scrollWidth<=w.innerWidth+1 && d.body.scrollWidth<=w.innerWidth+1, d.documentElement.scrollWidth+"/"+w.innerWidth);
      T("气泡可点区域 ≥ 40px", tb1.getBoundingClientRect().height>=39.5);
    }
    R.errors=(w.__errs||[]).slice();
    T("0 JS 报错", R.errors.length===0, R.errors.join(" | "));
    T("截图场景就绪", true);
    R.ok=true;
    report("shot_"+R.mode,R);
    await sleep(600);
  }catch(e){
    R.steps.push({k:"截图脚本异常",ok:false,note:String(e&&e.stack||e)});
    report("shot_"+R.mode,R);
  }
}
run();
"""


RM_JS = r"""
async function run(){
  var R={steps:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC,390,844), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},7000);
    await sleep(200);
    click(f,"#aRosterPick");
    await waitFor(function(){var mm=q(f,"#rosterModal");return mm&&mm.style.display!=="none";},5000);
    await sleep(150);
    var b=q(f,'#rstTxt .rst-b[data-seat="1"]');
    T("prefers-reduced-motion：气泡无持续动画、弹层入场关闭", w.getComputedStyle(b).animationName==="none" && w.getComputedStyle(q(f,"#rstSheet")).animationName==="none", w.getComputedStyle(b).animationName+"/"+w.getComputedStyle(q(f,"#rstSheet")).animationName);
    T("prefers-reduced-motion：弹层仍正常（70 气泡 / 可见）",
      qa(f,"#rstTxt .rst-b").length===70 && q(f,"#rosterModal").style.display!=="none");
    click(f,"#rstAllBtn");
    T("prefers-reduced-motion：全选计数正常", /已选 70 \/ 70/.test(cntRst(f)), cntRst(f));
  }catch(e){
    R.steps.push({k:"reduced-motion 脚本异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("rm",R);
}
run();
"""


def build_harness(name, js, src, gate=""):
    body = (COMMON_JS.replace("__SRC__", src).replace("__GATE__", gate).replace("__SID__", SID) + "\n" + js)
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>roster check</title>"
            "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
            "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
    open(os.path.join(HERE, name), "w", encoding="utf-8").write(html)


# ---------------------------------------------------------------- HTTP server + Edge
class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        qs = urllib.parse.urlparse(self.path).query
        m = re.search(r"slot=([A-Za-z0-9_]+)", qs)
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


def run_edge(url, budget=12000, shot=None, timeout=150, window="492,900", flags=None):
    # 每次用独立 profile：复用同一 user-data-dir 时 Edge 偶发被残留进程占用，页面不加载
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


def wait_report(slot, secs=20):
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


def run_and_report(url, slot, budget=14000, shot=None, window="492,900", secs=24, retries=2, flags=None):
    """跑一次 headless Edge 并取回该 slot 的上报；偶发未上报时自动重试一次。"""
    data = None
    last = None
    for _ in range(retries):
        clear_report(slot)
        last = run_edge(url, budget=budget, shot=shot, window=window, flags=flags)
        data = wait_report(slot, secs)
        if data:
            return data
        time.sleep(0.3)
    if os.environ.get("ROSTER_DEBUG") and last is not None:
        err = (last.stderr or b"").decode("utf-8", "replace")[-1200:]
        print("[DEBUG] slot=%s rc=%s stderr=%s" % (slot, last.returncode, err.replace("\n", " | ")))
    return None


STATIC_CHECKS = []


def static_checks(html):
    bad = []
    for ident in ['id="aRoster"', 'id="gNames"', 'id="rNames"', 'id="aPaste"', 'id="aClear"',
                  'id="aDefRoster"', 'id="aUpRoster"', 'id="rImportClass"', 'id="aRosterHint"']:
        if ident in html:
            bad.append(ident)
    STATIC_CHECKS.append(("无名单自定义 textarea / 粘贴 / 导入按钮", not bad, ",".join(bad)))
    STATIC_CHECKS.append(("三处「选择名单」入口", html.count('id="aRosterPick"') == 1 and html.count('id="gRosterPick"') == 1
                          and html.count('id="rPickSel"') == 1, ""))
    STATIC_CHECKS.append(("全局单例弹层 DOM 唯一", html.count('id="rosterModal"') == 1 and html.count('id="rstTxt"') == 1, ""))
    STATIC_CHECKS.append(("方案 C：已删除 goo 层与 SVG 滤镜（无白洞风险）",
                          'id="rstGoo"' not in html and "feGaussianBlur" not in html and "#rosterGoo" not in html, ""))
    STATIC_CHECKS.append(("简约名单气泡：无渐变 / 无高光伪元素 / 无持续动画 / 轻按压 / 减动效 / 浅青选中态",
                          all(k in html for k in ["#F1F7F5", "transform:scale(.985)", "prefers-reduced-motion"])
                          and "rst-b::before" not in html and "rstFloat" not in html
                          and "rstPop" not in html and "rsumFloat" not in html, ""))
    STATIC_CHECKS.append(("使用说明已更新（选择名单 / 不能自定义）",
                          "不支持自定义输入" in html and "抽签选了名单后" in html, ""))
    STATIC_CHECKS.append(("STEP2 来源文案「选择名单」", 'value="names"> 选择名单' in html, ""))
    STATIC_CHECKS.append(("点名沿用抽签名单按钮", "沿用抽签名单" in html and "用抽签页名单" not in html, ""))
    STATIC_CHECKS.append(("模型字段 rosterSel/groupSel/rollSel", all(k in html for k in
                          ['rosterSel', 'groupSel', 'rollSel', 'rosterMigrated']), ""))
    STATIC_CHECKS.append(("旧身份门禁未被改动", "zq_class_identity" in html and "classVerify" in html and "id-gate" not in html, ""))
    STATIC_CHECKS.append(("无 CDN / 外部资源引用", not re.search(r'(src|href)\s*=\s*["\']https?://', html), ""))


def main():
    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    for f in os.listdir(REPORT_DIR):
        try:
            os.remove(os.path.join(REPORT_DIR, f))
        except Exception:
            pass
    html = open(SRC, encoding="utf-8").read()
    static_checks(html)
    build_previews()
    build_harness(HARNESS_FUNC, FUNC_JS, PREVIEW, PREVIEW_GATE)
    build_harness(HARNESS_LAYOUT, LAYOUT_JS, PREVIEW)
    build_harness(HARNESS_SHOT, SHOT_JS, PREVIEW)
    build_harness(HARNESS_RM, RM_JS, PREVIEW)

    httpd = Q(("127.0.0.1", PORT), functools.partial(Handler, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)

    results = []   # (name, ok, note)

    def add_many(prefix, data):
        if not data:
            results.append((prefix + " 未返回结果", False, "report 缺失（浏览器未上报）"))
            return
        for s in data.get("steps", []):
            results.append(("[" + prefix + "] " + s.get("k", "?"), bool(s.get("ok")), s.get("note", "")))

    try:
        # 1) 功能专项（430 宽）
        add_many("功能", run_and_report(BASE + "tests/" + HARNESS_FUNC, "func", budget=20000, secs=30))

        # 2) 各档宽度：页面/弹层无横向溢出
        for w in (360, 390, 430, 720, 1280):
            js = LAYOUT_JS.replace("__W__", str(w))
            build_harness(HARNESS_LAYOUT, js, PREVIEW)
            add_many("溢出@" + str(w), run_and_report(BASE + "tests/" + HARNESS_LAYOUT, "layout_%d" % w, budget=16000))

        # 3) prefers-reduced-motion：气泡无持续动画 / 弹层入场关闭，弹层与计数正常
        add_many("减动效", run_and_report(BASE + "tests/" + HARNESS_RM, "rm", budget=16000,
                                         flags=["--force-prefers-reduced-motion"]))

        # 4) 截图：全选 / 混合选择 / 未选 × 390·1280 宽（合成姓名）+ 页面摘要
        for old in ("roster_picker_selected.png", "roster_picker_all.png", "roster_goo_frame_0.png",
                    "roster_goo_frame_25.png", "roster_goo_frame_50.png", "roster_picker_desktop1280.png",
                    "roster_picker_goo_fusion.png", "roster_page_summary.png"):
            try:
                os.remove(os.path.join(SHOTS, old))
            except Exception:
                pass
        shots = [("all390", "roster_all_390.png", "390,900"),
                 ("mixed390", "roster_mixed_390.png", "390,900"),
                 ("none390", "roster_none_390.png", "390,900"),
                 ("all1280", "roster_all_1280.png", "1280,900"),
                 ("mixed1280", "roster_mixed_1280.png", "1280,900"),
                 ("none1280", "roster_none_1280.png", "1280,900"),
                 ("page390", "roster_page_summary_390.png", "390,900")]
        for mode, fname, winsz in shots:
            p = os.path.join(SHOTS, fname)
            if os.path.exists(p):
                os.remove(p)
            data = run_and_report(BASE + "tests/" + HARNESS_SHOT + "#" + mode, "shot_" + mode,
                                  budget=30000, shot=p, window=winsz, secs=20)
            add_many("截图:" + mode, data)
            ok = os.path.exists(p) and os.path.getsize(p) > 10000
            results.append(("截图 " + fname, ok, ("%d bytes" % os.path.getsize(p)) if os.path.exists(p) else "未生成"))
    finally:
        httpd.shutdown()

    # ---- 汇总 ----
    for name, ok, note in STATIC_CHECKS:
        results.insert(0, ("[静态] " + name, bool(ok), note))

    fails = [r for r in results if not r[1]]
    for name, ok, note in results:
        print(("[PASS] " if ok else "[FAIL] ") + name + (("  -- " + note[:220]) if (note and not ok) else ""))
    print("")
    print("=" * 60)
    print("roster_check: %d 项，PASS %d，FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    print("截图目录:", SHOTS)
    print("=" * 60)
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        for f in (PREVIEW, PREVIEW_GATE, HARNESS_FUNC, HARNESS_LAYOUT, HARNESS_SHOT, HARNESS_RM):
            try:
                os.remove(os.path.join(HERE, f))
            except Exception:
                pass
    sys.exit(code)

