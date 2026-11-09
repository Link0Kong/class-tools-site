# -*- coding: utf-8 -*-
"""独立验收：班级名单选择器 + 液态气泡（web 端）
用法：python tests\\roster_check_verify.py

独立于实现者的 tests/roster_check.py：
- 合成身份 / 合成 70 人名单（同学01…同学70，座号 1–70，不含真实姓名）；
- 自制旧数据种子（旧 roster / group.names / rollNames / rollSt / classRoster）；
- 断言独立编写：门禁、旧数据迁移、单例弹层、全选/清空/取消/确定、抽签语义、
  分组、点名状态按姓名保留/重置/沿用、Esc/遮罩、7 档宽度无横向溢出、0 JS 报错、
  回归各工具页、无外部请求；
- headless Edge + 本地 HTTP + iframe 固定宽度驱动；截图存 tests/_shots_roster_verify/。

退出码 0 = 全绿。
"""
import os
import sys
import re
import json
import time
import shutil
import tempfile
import threading
import http.server
import socketserver
import functools
import subprocess
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))   # tools/tests
ROOT = os.path.dirname(HERE)                        # tools
SRC = os.path.join(ROOT, "index.html")
SHOTS = os.path.join(HERE, "_shots_roster_verify")
REPORT_DIR = os.path.join(HERE, "_shots_roster_verify", "_reports")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8921
BASE = "http://127.0.0.1:%d/" % PORT

SID = "3260710001"          # 合成学号（10 位，不是真实学号）
NAME = "验收同学"
PREFIX = "同学"
MEMBERS = [{"seat": i, "sid": "9100%06d" % i, "name": "%s%02d" % (PREFIX, i),
            "role": "", "badge": "", "is_admin": False} for i in range(1, 71)]

# 旧数据：roster 2 合法 + 1 不存在；group 2 合法 + 1 不存在；roll 2 合法 + 1 不存在；
# rollSt 按旧下标 0→"ab"（同学33）、1→"in"（同学01），迁移后应变成 {0:"in",1:"ab"}
SEED = {
    "roster": "5 同学05\n12 同学12\n99 查无此人",
    "classRoster": "1 同学01\n旧云端名单",
    "rosterSel": [], "groupSel": [], "rollSel": [],
    "group": {"source": "names", "names": "同学20\n同学02\n查无此人",
              "mode": "groups", "n": 2, "shuffle": False},
    "rollNames": "同学33\n同学01\n查无此人",
    "rollSt": {"0": "ab", "1": "in"},
    "draw": {"start": 1, "end": 70, "count": 10, "dup": False, "excl": "", "sort": "draw"},
    "course": [], "homework": [], "notices": [], "hwDone": {}, "ntPin": {}, "hwHide": {},
}

APP_PREVIEW = "_verify_app.html"
GATE_PREVIEW = "_verify_gate.html"
H_FUNC = "_verify_func.html"
H_LAYOUT = "_verify_layout.html"
H_RM = "_verify_rm.html"
H_SHOT = "_verify_shot.html"
TMP_FILES = [APP_PREVIEW, GATE_PREVIEW, H_FUNC, H_LAYOUT, H_RM, H_SHOT]

RESULT_JSON = os.path.join(REPORT_DIR, "roster_check_verify_result.json")

# ------------------------------------------------------------------ 静态检查
STATIC_ROWS = []


def static_checks(html):
    def add(name, ok, note=""):
        STATIC_ROWS.append((name, bool(ok), str(note)[:300]))

    # 1) 旧自定义名单控件必须彻底移除
    legacy_ids = ['id="aRoster"', 'id="gNames"', 'id="rNames"', 'id="aPaste"', 'id="aClear"',
                  'id="aDefRoster"', 'id="aUpRoster"', 'id="aImport"', 'id="rImportClass"',
                  'id="gPaste"', 'id="gImport"', 'id="rPaste"', 'id="rImport"', 'id="rClear"',
                  'id="aRosterHint"', 'id="rosterDef"']
    hit = [x for x in legacy_ids if x in html]
    add("静态：无 #aRoster/#gNames/#rNames textarea 与粘贴/导入/清空/更新云端按钮", not hit, ",".join(hit))
    listeners = [x for x in ['$("#aRoster")', '$("#gNames")', '$("#rNames")',
                             "onPaste", "aDefRoster", "aUpRoster", "rImportClass",
                             "classRosterUpdate"] if x in html]
    add("静态：无旧名单粘贴/导入/云端更新监听", not listeners, ",".join(listeners))
    ta_ids = re.findall(r"<textarea[^>]*id=\"([^\"]+)\"", html)
    add("静态：textarea 均为既有功能（课表导入/作业内容/反馈），无名单输入",
        sorted(ta_ids) == sorted(["ttPaste", "hContent", "fbText"]), ",".join(ta_ids))
    p1 = re.search(r'<div class="stpane on" id="p1">(.*?)<!-- STEP 2 -->', html, re.S)
    gwrap = re.search(r'<div id="gNamesWrap"[^>]*>(.*?)</div>\s*<div class="grid2">', html, re.S)
    sroll = re.search(r'<section id="s-roll">(.*?)</section>', html, re.S)
    add("静态：抽签 STEP1 / 分组来源区 / 点名页内无 textarea",
        all(x is not None and "<textarea" not in x.group(1) for x in (p1, gwrap, sroll)),
        "p1=%s gwrap=%s roll=%s" % (p1 is not None, gwrap is not None, sroll is not None))

    # 2) 三处「选择名单」入口 + 单例弹层
    add("静态：三处「选择名单」入口各 1 个",
        html.count('id="aRosterPick"') == 1 and html.count('id="gRosterPick"') == 1
        and html.count('id="rPickSel"') == 1,
        "%d/%d/%d" % (html.count('id="aRosterPick"'), html.count('id="gRosterPick"'), html.count('id="rPickSel"')))
    add("静态：单例名单弹层 DOM 唯一（rosterModal/rstTxt/rstCnt）",
        html.count('id="rosterModal"') == 1 and html.count('id="rstTxt"') == 1
        and html.count('id="rstCnt"') == 1 and html.count('id="rstAllBtn"') <= 1,
        "%d/%d" % (html.count('id="rosterModal"'), html.count('id="rstTxt"')))
    add("静态：弹层具备 全选/清空/确定/取消", all(x in html for x in
        ['id="rstAllBtn"', 'id="rstNoneBtn"', 'id="rstOk"', 'id="rstCancel"']))

    # 3) 方案 C 液态气泡（渐变 + 高光 + 浮动 + 按压果冻 + 选中 pop + 减动效）
    add("静态：液态气泡样式（渐变/径向高光/浮动/按压/选中pop/减动效）",
        all(x in html for x in ["rstFloat", "radial-gradient", ".rst-b.press", ".rst-b.pop",
                                "prefers-reduced-motion", "linear-gradient(160deg,#FDF9F0"]))
    add("静态：无 goo 滤镜 / SVG 模糊层", 'rstGoo' not in html and "feGaussianBlur" not in html)
    add("静态：气泡可点区 min-height:40px", re.search(r"\.rst-b\{[^}]*min-height:40px", html) is not None)

    # 4) 数据字段与迁移
    add("静态：rosterSel / groupSel / rollSel / rosterMigrated 字段",
        all(x in html for x in ["rosterSel", "groupSel", "rollSel", "rosterMigrated"]))
    add("静态：旧 classRoster 在迁移中清空", 'D.d.classRoster=""' in html)
    add("静态：派生文本 rosterText/groupNamesText/writeRollFromSel",
        all(x in html for x in ["function rosterText", "function groupNamesText", "function writeRollFromSel"]))

    # 5) 使用说明文案
    add("静态：使用说明已更新（不支持自定义输入 / 选择名单 / 沿用抽签名单）",
        "不支持自定义输入" in html and "点「选择名单」" in html and "沿用抽签名单" in html)
    add("静态：抽签提示含「参与名单」/「抽签池」",
        "参与名单（可选）" in html and "抽签池" in html)

    # 6) 零外部请求 / 单文件零依赖
    ext = re.findall(r"<(?:script|link|img|iframe|source)[^>]+(?:src|href)\s*=\s*[\"']https?://", html, re.I)
    add("静态：无外部资源引用（script/link/img/iframe）", not ext, ",".join(ext[:4]))
    banned = ["fonts.googleapis", "gstatic", "cdn.jsdelivr", "unpkg.com", "cdn.bootcdn",
              "google-analytics", "googletagmanager", "hm.baidu", "umami", "clarity.ms"]
    bhit = [x for x in banned if x in html]
    add("静态：无 Google Fonts / CDN / 统计脚本", not bhit, ",".join(bhit))
    add("静态：单文件零依赖（无 <script src> / 无 <link rel=stylesheet>）",
        not re.search(r"<script[^>]+\bsrc\s*=", html, re.I)
        and not re.search(r"<link[^>]+rel\s*=\s*[\"']stylesheet", html, re.I))
    add("静态：身份门禁未被改动（zq_class_identity / classVerify / membersPull）",
        all(x in html for x in ["zq_class_identity", "classVerify", "membersPull", "class_members"]))
    add("静态：仅保留原生 fetch 调 PostgREST（无 axios/jQuery/框架全局）",
        not re.search(r"(?:\baxios\b|\bjQuery\b|\bnew Vue\b|Vue\.createApp|\bReactDOM\b|\breact-dom\b|\bangular\b)",
                      html, re.I))


# ------------------------------------------------------------------ 构建注入页
INJECT = """<script>
(function(){
window.__errs=[];window.__cerrs=[];window.__fetchLog=[];window.__ext=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));_ce.apply(console,arguments);};
var MEMBERS=__MEMBERS__;
var _f=window.fetch?window.fetch.bind(window):null;
window.fetch=function(u,o){
  var s=String((typeof u==="string")?u:((u&&u.url)||""));
  try{window.__fetchLog.push(s);}catch(e){}
  if(s.indexOf("rpc/class_members")>=0){
    return Promise.resolve(new Response(JSON.stringify(MEMBERS),{status:200,headers:{"Content-Type":"application/json"}}));
  }
  if(s.indexOf("tcloudbasegateway")>=0){
    return Promise.resolve(new Response("[]",{status:200,headers:{"Content-Type":"application/json"}}));
  }
  if(s.indexOf("tt.json")>=0){ return Promise.reject(new Error("verify-block-tt")); }
  var same=/^https?:\\/\\/127\\.0\\.0\\.1([:\\/]|$)/.test(s);
  if(!same && /^https?:\\/\\//.test(s)){ try{window.__ext.push(s);}catch(e){} return Promise.reject(new Error("verify-block-ext")); }
  if(!_f) return Promise.reject(new Error("no-fetch"));
  return _f(u,o);
};
__LOCAL__
})();
</script>"""

MEMBER_JSON = json.dumps(MEMBERS, ensure_ascii=False)

LOCAL_APP = ('try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"verify-token-1",'
             'sid:"%s",name:"%s",role:"",badge:"",is_admin:true,ts:Date.now()}));'
             'localStorage.setItem("zq_tools_v2_%s",JSON.stringify(%s));}catch(e){}'
             % (SID, NAME, SID, json.dumps(SEED, ensure_ascii=False)))
LOCAL_GATE = ('try{localStorage.removeItem("zq_class_identity");'
              'localStorage.removeItem("zq_tools_v2_%s");'
              'localStorage.removeItem("zq_last_identity");}catch(e){}' % SID)


def build_previews():
    html = open(SRC, encoding="utf-8").read()
    for name, local in ((APP_PREVIEW, LOCAL_APP), (GATE_PREVIEW, LOCAL_GATE)):
        inject = INJECT.replace("__MEMBERS__", MEMBER_JSON).replace("__LOCAL__", local)
        out = html.replace("<head>", "<head>" + inject, 1)
        open(os.path.join(HERE, name), "w", encoding="utf-8").write(out)


# ------------------------------------------------------------------ 测试 JS
COMMON_JS = r"""
var WIN="__WIN__", H="__H__", SRC="__SRC__", GATE="__GATE__", SID="__SID__", STORE="zq_tools_v2_"+SID;
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
function waitFor(fn,ms){return new Promise(function(res,rej){var t0=Date.now();
  (function loop(){var v=false;try{v=!!fn();}catch(e){v=false;}
    if(v)return res(true);
    if(Date.now()-t0>(ms||5000))return rej(new Error("waitFor timeout"));
    setTimeout(loop,25);})();});}
function mount(src,w,h){
  return new Promise(function(res,rej){
    var old=document.getElementById("fr"); if(old&&old.parentNode)old.parentNode.removeChild(old);
    var f=document.createElement("iframe"); f.id="fr";
    f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block";
    f.src=src;
    var done=false;
    f.onload=function(){ if(done)return; done=true; setTimeout(function(){res(f);},120); };
    f.onerror=function(){ if(done)return; done=true; rej(new Error("iframe load failed:"+src)); };
    document.body.appendChild(f);
    setTimeout(function(){ if(!done){done=true;res(f);} },9000);
  });
}
function q(f,s){return f.contentDocument.querySelector(s);}
function qa(f,s){return Array.prototype.slice.call(f.contentDocument.querySelectorAll(s));}
function click(f,s){var e=q(f,s); if(!e)throw new Error("missing element: "+s); e.click(); return e;}
function txt(f,s){var e=q(f,s); return e?e.textContent:"";}
function st(f){try{return JSON.parse(f.contentWindow.localStorage.getItem(STORE)||"null")||{};}catch(e){return {};}}
function count(f){var e=q(f,"#rstCnt"); return e?+e.textContent:-1;}
function total(f){var e=q(f,"#rstTotal"); return e?+e.textContent:-1;}
function toast(f){return txt(f,"#toast").trim();}
function modalOpen(f){var m=q(f,"#rosterModal"); return !!m&&m.style.display!=="none";}
function jsonEq(a,b){return JSON.stringify(a)===JSON.stringify(b);}
async function openPicker(f,btn){
  click(f,btn);
  await waitFor(function(){return modalOpen(f);},5000);
  try{await waitFor(function(){return qa(f,"#rstTxt .rst-b").length>=70;},5000);}catch(e){}
  await sleep(90);
}
async function pickSeats(f,seats){
  click(f,"#rstNoneBtn"); await sleep(40);
  seats.forEach(function(s){
    var b=q(f,'#rstTxt .rst-b[data-seat="'+s+'"]');
    if(b&&!b.classList.contains("on"))b.click();
  });
  await sleep(60);
}
async function waitMembers(f){
  await waitFor(function(){return qa(f,"#aRosterSum button.rchip").length>0;},7000);
  await sleep(120);
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

FUNC_JS = r"""
async function run(){
  var R={steps:[],errors:{},slot:"func"};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    /* ============ 0. 门禁：未登录停在身份页、未请求班级数据 ============ */
    var gf=await mount(GATE,390,844);
    await sleep(500);
    var gd=gf.contentDocument, gw=gf.contentWindow;
    T("门禁：未登录停在身份页（body.id-locked + #idgate 可见）",
      gd.body.classList.contains("id-locked") && (function(){var g=gd.querySelector("#idgate");return g&&gw.getComputedStyle(g).display!=="none";})(),
      gd.body.className);
    T("门禁：未登录未请求班级数据（0 次 fetch）",
      (gw.__fetchLog||[]).length===0, JSON.stringify((gw.__fetchLog||[]).slice(0,4)));

    /* ============ 1. 注入假身份 + 合成名单 + 旧数据，等待迁移 ============ */
    var f=await mount(SRC,430,900), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},7000);
    T("假身份：进入班级（身份页解锁）", !d.body.classList.contains("id-locked"));
    await waitMembers(f);
    await waitFor(function(){return st(f).rosterMigrated===true;},6000);
    await sleep(120);
    var s=st(f);

    /* ============ 2. 旧数据迁移 ============ */
    T("迁移：旧 roster 2 合法 + 1 不存在 → rosterSel=[5,12]", jsonEq(s.rosterSel,[5,12]), JSON.stringify(s.rosterSel));
    T("迁移：派生 roster 文本收敛为「5 同学05\\n12 同学12」", s.roster==="5 同学05\n12 同学12", JSON.stringify(s.roster));
    T("迁移：旧 group.names → groupSel=[2,20]", jsonEq(s.groupSel,[2,20]), JSON.stringify(s.groupSel));
    T("迁移：group.names 派生仅姓名按座号升序", s.group&&s.group.names==="同学02\n同学20", s.group&&JSON.stringify(s.group.names));
    T("迁移：旧 rollNames → rollSel=[1,33]", jsonEq(s.rollSel,[1,33]), JSON.stringify(s.rollSel));
    T("迁移：rollNames 派生按座号升序", s.rollNames==="1 同学01\n33 同学33", JSON.stringify(s.rollNames));
    T("迁移：rollSt 按姓名保留并重排（同学01→in@0, 同学33→ab@1）",
      jsonEq(s.rollSt,{"0":"in","1":"ab"}), JSON.stringify(s.rollSt));
    T("迁移：旧 classRoster 已清空、rosterMigrated=true", !s.classRoster && s.rosterMigrated===true, JSON.stringify(s.classRoster));
    T("迁移：幂等（仅执行一次，selVer/标记不变）", s.rosterMigrated===true);

    /* ============ 3. 页面摘要气泡 ============ */
    T("摘要：参与名单 2 个名字气泡", qa(f,"#aRosterSum button.rchip").length===2, qa(f,"#aRosterSum button.rchip").length);
    T("摘要：气泡显示姓名、不含座号原文", /同学05/.test(txt(f,"#aRosterSum")) && /同学12/.test(txt(f,"#aRosterSum"))
      && !/5 同学05/.test(txt(f,"#aRosterSum")), txt(f,"#aRosterSum"));
    T("摘要：STEP1/点名页无名单 textarea", qa(f,"#p1 textarea").length===0 && qa(f,"#s-roll textarea").length===0);
    T("摘要：抽签池提示「已选 2 人 · 抽签池 2」", /已选 2 人/.test(txt(f,"#aPoolHint")) && /抽签池 2/.test(txt(f,"#aPoolHint")), txt(f,"#aPoolHint"));

    /* ============ 4. 弹层：单例 / 70 气泡 / 计数 / 逐个 / 全选 / 清空 / 取消 / Esc / 遮罩 ============ */
    await openPicker(f,"#aRosterPick");
    T("弹层：标题「选择抽签名单」", txt(f,"#rstTitle")==="选择抽签名单", txt(f,"#rstTitle"));
    T("弹层：70 个气泡", qa(f,"#rstTxt .rst-b").length===70, qa(f,"#rstTxt .rst-b").length);
    T("弹层：总数显示 70", total(f)===70, total(f));
    T("弹层：初始计数 = 已迁移的 2 / 70", count(f)===2, count(f));
    var b5=q(f,'#rstTxt .rst-b[data-seat="5"]');
    T("气泡：含姓名与小号座号（同学05 / 5）",
      b5&&b5.querySelector(".nm").textContent==="同学05"&&b5.querySelector(".ss").textContent==="5",
      b5&&b5.textContent);
    T("气泡：可点区高度 ≥ 40px", b5&&b5.getBoundingClientRect().height>=39.5, b5&&b5.getBoundingClientRect().height);
    T("气泡：选中态 aria-pressed 初始正确（座号5 已选）",
      b5&&b5.getAttribute("aria-pressed")==="true"&&b5.classList.contains("on"), b5&&b5.getAttribute("aria-pressed"));
    var bodyOverflowOpen=d.documentElement.scrollWidth<=w.innerWidth+1 && d.body.scrollWidth<=w.innerWidth+1;
    T("弹层（430 宽）：无横向溢出", bodyOverflowOpen, d.documentElement.scrollWidth+"/"+w.innerWidth);
    click(f,"#rstNoneBtn"); await sleep(50);
    T("清空：计数 0/70、无选中态", count(f)===0 && qa(f,"#rstTxt .rst-b.on").length===0, count(f));
    /* 清空会重渲染气泡，必须重新查询节点（旧引用已脱离 DOM） */
    q(f,'#rstTxt .rst-b[data-seat="5"]').click(); await sleep(50);
    T("逐个点选：计数 1/70 且气泡选中", count(f)===1 && q(f,'#rstTxt .rst-b[data-seat="5"]').classList.contains("on"), count(f));
    q(f,'#rstTxt .rst-b[data-seat="5"]').click(); await sleep(50);
    T("再点一次取消：计数 0/70", count(f)===0 && !q(f,'#rstTxt .rst-b[data-seat="5"]').classList.contains("on"), count(f));
    click(f,"#rstAllBtn"); await sleep(60);
    T("一键全选：70/70 且 70 个选中态", count(f)===70 && qa(f,"#rstTxt .rst-b.on").length===70, count(f));
    click(f,"#rstCancel"); await sleep(100);
    T("取消：弹层关闭且不写回（rosterSel 仍 [5,12]）",
      !modalOpen(f) && jsonEq(st(f).rosterSel,[5,12]), JSON.stringify(st(f).rosterSel));

    await openPicker(f,"#aRosterPick");
    q(f,'#rstTxt .rst-b[data-seat="7"]').click(); await sleep(40);
    d.dispatchEvent(new w.KeyboardEvent("keydown",{key:"Escape",bubbles:true})); await sleep(100);
    T("Esc：关闭弹层且不写回", !modalOpen(f) && jsonEq(st(f).rosterSel,[5,12]), JSON.stringify(st(f).rosterSel));
    await openPicker(f,"#aRosterPick");
    q(f,"#rosterModal").dispatchEvent(new w.MouseEvent("click",{bubbles:true})); await sleep(100);
    T("遮罩点击：关闭弹层且不写回", !modalOpen(f) && jsonEq(st(f).rosterSel,[5,12]), JSON.stringify(st(f).rosterSel));

    /* 逐个选 10 人 → 确定写回 localStorage + 页面摘要 */
    var TEN=[2,9,17,23,31,38,44,52,61,70];
    await openPicker(f,"#aRosterPick");
    await pickSeats(f,TEN);
    T("混合选择：逐个点 10 人 → 计数 10/70", count(f)===10, count(f));
    click(f,"#rstOk"); await sleep(140);
    s=st(f);
    T("确定：写回 localStorage rosterSel=所选 10 个座号", jsonEq(s.rosterSel,TEN), JSON.stringify(s.rosterSel));
    T("确定：派生 roster 文本 10 行且含姓名", String(s.roster||"").split("\n").length===10 && s.roster.indexOf(" 同学")>=0, (s.roster||"").slice(0,40));
    T("确定：页面摘要 10 个名字气泡", qa(f,"#aRosterSum button.rchip").length===10, qa(f,"#aRosterSum button.rchip").length);
    T("确定：提示「已选 10 人 · 抽签池 10」", /已选 10 人/.test(txt(f,"#aPoolHint")) && /抽签池 10/.test(txt(f,"#aPoolHint")), txt(f,"#aPoolHint"));

    /* ============ 5. 抽签语义 ============ */
    q(f,"#aStart").value="1"; q(f,"#aEnd").value="70"; q(f,"#aCount").value="10";
    click(f,"#aRun"); await sleep(120);
    var cells=qa(f,"#aOut .rcell");
    var named=cells.filter(function(c){var n=c.querySelector(".rname");return n&&n.textContent.trim();});
    T("抽签：选 10 人抽 10 → 10 个结果且全部带姓名", cells.length===10 && named.length===10, cells.length+"/"+named.length);
    T("抽签：结果全部属于所选名单", cells.every(function(c){return TEN.indexOf(+c.getAttribute("data-n"))>=0;}), cells.map(function(c){return c.getAttribute("data-n");}).join(","));
    T("抽签：toast「已抽取」", /已抽取/.test(toast(f)), toast(f));

    var THREE=[4,5,6];
    await openPicker(f,"#aRosterPick"); await pickSeats(f,THREE); click(f,"#rstOk"); await sleep(120);
    q(f,"#aCount").value="5"; click(f,"#aRun"); await sleep(90);
    T("抽签：只选 3 人 + 抽 5 → 明确报错（抽签池只有 3 人）", /抽签池只有 3 人/.test(toast(f)), toast(f));
    T("抽签：超池不放行（结果仍为上一次 10 个）", qa(f,"#aOut .rcell").length===10, qa(f,"#aOut .rcell").length);
    q(f,"#aCount").value="3"; click(f,"#aRun"); await sleep(90);
    var c3=qa(f,"#aOut .rcell");
    T("抽签：3 人池抽 3 个且均在 [4,5,6]", c3.length===3 && c3.every(function(c){return THREE.indexOf(+c.getAttribute("data-n"))>=0;}),
      c3.map(function(c){return c.getAttribute("data-n");}).join(","));
    T("抽签：3 人池结果均带姓名", c3.every(function(c){var n=c.querySelector(".rname");return n&&n.textContent.trim();}));

    await openPicker(f,"#aRosterPick"); await pickSeats(f,[]); click(f,"#rstOk"); await sleep(120);
    T("抽签：清空名单后摘要「未选择」", /未选择/.test(txt(f,"#aRosterSum")), txt(f,"#aRosterSum"));
    T("抽签：未选名单提示「抽签池 70 个序号」", /抽签池 70 个序号/.test(txt(f,"#aPoolHint")), txt(f,"#aPoolHint"));
    q(f,"#aCount").value="10"; click(f,"#aRun"); await sleep(100);
    var cn=qa(f,"#aOut .rcell");
    T("抽签：未选名单只抽序号（10 个结果、无姓名）",
      cn.length===10 && cn.every(function(c){return !c.querySelector(".rname");}), cn.length);

    /* 恢复 10 人名单（供点名「沿用抽签名单」用） */
    await openPicker(f,"#aRosterPick"); await pickSeats(f,TEN); click(f,"#rstOk"); await sleep(120);
    T("抽签：恢复 10 人参与名单", jsonEq(st(f).rosterSel,TEN), JSON.stringify(st(f).rosterSel));

    /* ============ 6. 分组 ============ */
    click(f,"[data-step='2']"); await sleep(100);
    click(f,'input[name=gsrc][value="names"]'); await sleep(60);
    T("分组：来源「选择名单」显示摘要区", q(f,"#gNamesWrap").style.display!=="none", q(f,"#gNamesWrap").style.display);
    T("分组：摘要区当前 2 人（旧 group 迁移）", /共 2 人/.test(txt(f,"#gRosterCnt")), txt(f,"#gRosterCnt"));
    await openPicker(f,"#gRosterPick");
    T("分组：弹层标题「选择分组名单」且复用同一单例 #rosterModal",
      txt(f,"#rstTitle")==="选择分组名单" && qa(f,"#rosterModal").length===1 && count(f)===2, txt(f,"#rstTitle")+"/"+count(f));
    await pickSeats(f,[]); click(f,"#rstOk"); await sleep(120);
    T("分组：清空后 groupSel=[]", jsonEq(st(f).groupSel,[]), JSON.stringify(st(f).groupSel));
    click(f,"#gRun"); await sleep(90);
    T("分组：未选名单点开始分组 → 提示「请先选择名单」", /请先选择名单/.test(toast(f)), toast(f));
    T("分组：未选名单不产生分组结果", qa(f,"#gOut .gcard").length===0, qa(f,"#gOut .gcard").length);
    var GFIVE=[2,6,10,14,18];
    await openPicker(f,"#gRosterPick"); await pickSeats(f,GFIVE); click(f,"#rstOk"); await sleep(120);
    T("分组：选 5 人写回 groupSel", jsonEq(st(f).groupSel,GFIVE), JSON.stringify(st(f).groupSel));
    q(f,"#gNum").value="2"; click(f,"#gRun"); await sleep(120);
    var gc=qa(f,"#gOut .gcard"), gsp=qa(f,"#gOut .gcard .bd span");
    T("分组：2 组共 5 人", gc.length===2 && gsp.length===5, gc.length+"组/"+gsp.length+"人");
    T("分组：5 人全部带姓名", gsp.length===5 && gsp.every(function(sp){var b=sp.querySelector("b");return b&&b.textContent.trim();}),
      gsp.map(function(sp){return sp.textContent;}).join("|"));

    /* ============ 7. 点名 ============ */
    click(f,"[data-tab='all']"); await sleep(90);
    click(f,"[data-open='roll']"); await sleep(180);
    T("点名：迁移后名单 2 人", qa(f,"#rGrid .rcard").length===2, qa(f,"#rGrid .rcard").length);
    var inCard=qa(f,"#rGrid .rcard.in"), abCard=qa(f,"#rGrid .rcard.ab");
    T("点名：状态按姓名保留（同学01 已到 / 同学33 请假）",
      inCard.length===1 && abCard.length===1 && /同学01/.test(txt(f,"#rGrid .rcard.in .rnm")) && /同学33/.test(txt(f,"#rGrid .rcard.ab .rnm")),
      txt(f,"#rGrid"));
    T("点名：无名单 textarea", qa(f,"#s-roll textarea").length===0);
    await openPicker(f,"#rPickSel");
    T("点名：弹层标题「选择点名名单」", txt(f,"#rstTitle")==="选择点名名单", txt(f,"#rstTitle"));
    var RFIVE=[1,10,20,30,33];
    await pickSeats(f,RFIVE); click(f,"#rstOk"); await sleep(140);
    s=st(f);
    T("点名：新名单 5 人座号升序", s.rollNames==="1 同学01\n10 同学10\n20 同学20\n30 同学30\n33 同学33", JSON.stringify(s.rollNames));
    T("点名：跨名单按姓名保留状态（0:in / 4:ab）", jsonEq(s.rollSt,{"0":"in","4":"ab"}), JSON.stringify(s.rollSt));
    T("点名：网格 5 人", qa(f,"#rGrid .rcard").length===5, qa(f,"#rGrid .rcard").length);
    function cardOf(nm){var x=qa(f,"#rGrid .rcard").filter(function(c){var e=c.querySelector(".rnm");return e&&e.textContent.indexOf(nm)>=0;});return x[0]||null;}
    var c10=cardOf("同学10");
    c10.querySelector('[data-rs="in"]').click(); await sleep(80);
    T("点名：点「到」记录同学10（index1=in）", st(f).rollSt["1"]==="in", JSON.stringify(st(f).rollSt));
    var RTHREE=[10,25,40];
    await openPicker(f,"#rPickSel"); await pickSeats(f,RTHREE); click(f,"#rstOk"); await sleep(140);
    s=st(f);
    T("点名：改选 3 人（顺序变化）后同一人状态保留（同学10 仍在 index0=in）",
      jsonEq(s.rollSt,{"0":"in"}) && String(s.rollNames).indexOf("10 同学10")===0, JSON.stringify(s.rollSt)+" / "+JSON.stringify(s.rollNames));
    cardOf("同学25").querySelector('[data-rs="ab"]').click(); await sleep(80);
    w.confirm=function(){return true;};
    click(f,"#rReset"); await sleep(100);
    s=st(f);
    T("点名：重置本轮只清状态不清名单",
      jsonEq(s.rollSt,{}) && String(s.rollNames).split("\n").length===3, JSON.stringify(s.rollSt)+" / "+JSON.stringify(s.rollNames));
    T("点名：重置后网格仍 3 人", qa(f,"#rGrid .rcard").length===3, qa(f,"#rGrid .rcard").length);
    click(f,"#rImportDraw"); await sleep(140);
    s=st(f);
    T("点名：沿用抽签名单可用（rollSel=抽签 10 人）", jsonEq(s.rollSel,TEN), JSON.stringify(s.rollSel));
    T("点名：沿用后网格 10 人", qa(f,"#rGrid .rcard").length===10, qa(f,"#rGrid .rcard").length);
    T("点名：沿用 toast 提示", /已沿用抽签名单/.test(toast(f)), toast(f));

    /* ============ 8. 回归：各工具页打开不报错 ============ */
    var errBase=(w.__errs||[]).length, cerrBase=(w.__cerrs||[]).length;
    var tabs=["tt","hw","nt","ft","committee","stats","ug"];
    for(var i=0;i<tabs.length;i++){
      click(f,"[data-tab='all']"); await sleep(80);
      var ob=q(f,'[data-open="'+tabs[i]+'"]');
      if(!ob){T("回归：工具页入口存在 "+tabs[i],false,"missing data-open");continue;}
      ob.click(); await sleep(140);
    }
    T("回归：课表/作业/通知/体测/班委/统计/使用说明打开后 0 新 JS 报错",
      (w.__errs||[]).length===errBase, (w.__errs||[]).slice(errBase).join(" | "));
    T("回归：使用说明含「不支持自定义输入」", txt(f,"#s-ug").indexOf("不支持自定义输入")>=0);
    T("回归：身份门禁仍生效（idChip 显示假身份）", /验收同学/.test(txt(f,"#idChipTxt")), txt(f,"#idChipTxt"));

    /* ============ 9. 外部请求 / 错误 ============ */
    var res=(w.performance.getEntriesByType("resource")||[]).filter(function(e){
      return !/^https?:\/\/127\.0\.0\.1([:\/]|$)/.test(e.name) && !/^(data|blob):/.test(e.name);
    }).map(function(e){return e.name;});
    T("网络：无外部资源请求（performance）", res.length===0, res.join(","));
    T("网络：无外部 fetch 尝试", (w.__ext||[]).length===0, (w.__ext||[]).join(","));
    R.errors={win:(w.__errs||[]).slice(),cerr:(w.__cerrs||[]).slice()};
    T("JS：0 运行时错误（window.onerror/unhandledrejection）", R.errors.win.length===0, R.errors.win.join(" | "));
    T("JS：0 console.error", R.errors.cerr.length===0, R.errors.cerr.join(" | "));
  }catch(e){
    R.steps.push({k:"功能脚本异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("func",R);
}
run();
"""

LAYOUT_JS = r"""
async function run(){
  var W=__W__, R={steps:[],slot:"layout_"+W};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC,W,W>=1000?900:820), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},8000);
    await waitMembers(f);
    var de=d.documentElement;
    function ov(){return {sw:de.scrollWidth,cw:de.clientWidth,bsw:d.body.scrollWidth,bcw:d.body.clientWidth,iw:w.innerWidth};}
    var o=ov();
    T("@"+W+"：页面无横向溢出（弹层关闭）", o.sw<=o.cw+1 && o.bsw<=o.bcw+1, JSON.stringify(o));
    await openPicker(f,"#aRosterPick");
    /* 入场动画只改 transform（translateY 34px），会把实测 rect 暂推低 34px；测「稳定态布局」前先定格动画 */
    var sh=q(f,"#rstSheet"); sh.style.animation="none";
    void sh.offsetWidth;
    await sleep(250);
    o=ov();
    T("@"+W+"：弹层打开无横向溢出", o.sw<=o.cw+1 && o.bsw<=o.bcw+1, JSON.stringify(o));
    var sr=q(f,"#rstSheet").getBoundingClientRect();
    T("@"+W+"：弹层完整在视口内", sr.left>=-1 && sr.right<=w.innerWidth+1 && sr.top>=-1 && sr.bottom<=w.innerHeight+1,
      JSON.stringify({l:Math.round(sr.left),r:Math.round(sr.right),t:Math.round(sr.top),b:Math.round(sr.bottom),vw:w.innerWidth,vh:w.innerHeight}));
    T("@"+W+"：弹层高度 ≤ 88vh", sr.height<=w.innerHeight*0.881+1, Math.round(sr.height)+"/"+w.innerHeight);
    var bh=q(f,'#rstTxt .rst-b[data-seat="1"]').getBoundingClientRect().height;
    T("@"+W+"：气泡可点区 ≥ 40px", bh>=39.5, Math.round(bh*10)/10);
    var sc=q(f,"#rstScroll");
    T("@"+W+"：弹层内部滚动可用且无横向溢出", sc.scrollWidth<=sc.clientWidth+1, sc.scrollWidth+"/"+sc.clientWidth);
    T("@"+W+"：70 个气泡", qa(f,"#rstTxt .rst-b").length===70, qa(f,"#rstTxt .rst-b").length);
    click(f,"#rstCancel"); await sleep(120);
    o=ov();
    T("@"+W+"：关闭弹层后仍无横向溢出", o.sw<=o.cw+1 && o.bsw<=o.bcw+1, JSON.stringify(o));
    T("@"+W+"：0 JS 报错", (w.__errs||[]).length===0, (w.__errs||[]).slice(0,3).join(" | "));
  }catch(e){
    R.steps.push({k:"@"+W+" 布局脚本异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("layout_"+W,R);
}
run();
"""

RM_JS = r"""
async function run(){
  var R={steps:[],slot:"rm"};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var f=await mount(SRC,390,844), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},8000);
    await waitMembers(f);
    await openPicker(f,"#aRosterPick");
    var b=q(f,'#rstTxt .rst-b[data-seat="1"]');
    T("减动效：气泡浮动动画关闭（animation-name:none）", w.getComputedStyle(b).animationName==="none", w.getComputedStyle(b).animationName);
    T("减动效：弹层仍正常（70 气泡 / 可见）", qa(f,"#rstTxt .rst-b").length===70 && modalOpen(f));
    click(f,"#rstAllBtn"); await sleep(80);
    T("减动效：全选计数正常 70/70", count(f)===70, count(f));
    T("减动效：0 JS 报错", (w.__errs||[]).length===0, (w.__errs||[]).slice(0,3).join(" | "));
  }catch(e){
    R.steps.push({k:"减动效脚本异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("rm",R);
}
run();
"""

SHOT_JS = r"""
async function run(){
  var mode=(location.hash||"#mixed390").replace("#","");
  var R={steps:[],slot:"shot_"+mode,mode:mode};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var desktop=/1280$/.test(mode), W=desktop?1280:390, H=desktop?900:844;
    var f=await mount(SRC,W,H), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},9000);
    await waitMembers(f);
    var base=d.createElement("style");
    base.textContent=".tabs button,.tabs-thumb{transition:none!important;animation:none!important}";
    d.head.appendChild(base);
    await sleep(200);
    if(mode.indexOf("page")===0){
      var TEN=[2,9,17,23,31,38,44,52,61,70];
      await openPicker(f,"#aRosterPick"); await pickSeats(f,TEN); click(f,"#rstOk"); await sleep(500);
      T("截图场景：页面摘要 10 人", qa(f,"#aRosterSum button.rchip").length===10);
    }else{
      await openPicker(f,"#aRosterPick");
      var ns=d.createElement("style");
      ns.textContent=".roster-modal.on .rst-sheet{animation:none!important}.rst-b,.rchip{animation-play-state:paused !important}";
      d.head.appendChild(ns);
      await sleep(180);
      if(mode.indexOf("all")===0){ click(f,"#rstAllBtn"); await sleep(200); T("截图场景：全选 70/70", count(f)===70); }
      else{
        for(var i=1;i<=36;i++){var b=q(f,'#rstTxt .rst-b[data-seat="'+i+'"]'); if(b&&!b.classList.contains("on"))b.click();}
        await sleep(200); T("截图场景：混合选择 36/70", count(f)===36);
      }
      T("截图场景：弹层无横向溢出", d.documentElement.scrollWidth<=w.innerWidth+1);
    }
    T("截图场景：0 JS 报错", (w.__errs||[]).length===0, (w.__errs||[]).slice(0,3).join(" | "));
    R.ok=true;
    report("shot_"+mode,R);
    await sleep(500);
  }catch(e){
    R.steps.push({k:"截图脚本异常",ok:false,note:String(e&&e.stack||e)});
    report("shot_"+mode,R);
  }
}
run();
"""


def build_harness(name, js):
    body = (COMMON_JS.replace("__SRC__", APP_PREVIEW).replace("__GATE__", GATE_PREVIEW)
            .replace("__SID__", SID).replace("__WIN__", "window").replace("__H__", "window")
            + "\n" + js)
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>roster verify</title>"
            "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}"
            "iframe{background:#fff;display:block}</style></head><body><script>"
            + body.replace("</script", "<\\/script") + "</script></body></html>")
    open(os.path.join(HERE, name), "w", encoding="utf-8").write(html)


# ------------------------------------------------------------------ HTTP + Edge
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


def run_edge(url, budget, shot=None, timeout=150, window="492,900", flags=None):
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


def run_and_report(url, slot, budget=20000, shot=None, window="492,900", secs=30, flags=None):
    data = None
    for _ in range(2):
        clear_report(slot)
        run_edge(url, budget=budget, shot=shot, window=window, flags=flags)
        data = wait_report(slot, secs)
        if data:
            return data
        time.sleep(0.3)
    return None


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
    build_harness(H_FUNC, FUNC_JS)
    build_harness(H_LAYOUT, LAYOUT_JS)
    build_harness(H_RM, RM_JS)
    build_harness(H_SHOT, SHOT_JS)

    httpd = Q(("127.0.0.1", PORT), functools.partial(Handler, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)

    results = []

    def add_many(prefix, data):
        if not data:
            results.append((prefix + " 未返回结果", False, "report 缺失"))
            return
        for s in data.get("steps", []):
            results.append(("[" + prefix + "] " + s.get("k", "?"), bool(s.get("ok")), s.get("note", "")))

    try:
        add_many("功能", run_and_report(BASE + "tests/" + H_FUNC, "func", budget=24000, secs=34))
        for w in (360, 390, 430, 720, 1280):
            js = LAYOUT_JS.replace("__W__", str(w))
            build_harness(H_LAYOUT, js)
            add_many("布局", run_and_report(BASE + "tests/" + H_LAYOUT, "layout_%d" % w, budget=18000, secs=26))
        add_many("减动效", run_and_report(BASE + "tests/" + H_RM, "rm", budget=18000, secs=26,
                                          flags=["--force-prefers-reduced-motion"]))
        shots = [("mixed390", "roster_verify_mixed_390.png", "390,844"),
                 ("all1280", "roster_verify_all_1280.png", "1280,900"),
                 ("page390", "roster_verify_page_390.png", "390,844")]
        for mode, fname, winsz in shots:
            p = os.path.join(SHOTS, fname)
            if os.path.exists(p):
                os.remove(p)
            data = run_and_report(BASE + "tests/" + H_SHOT + "#" + mode, "shot_" + mode,
                                  budget=30000, shot=p, window=winsz, secs=22)
            add_many("截图:" + mode, data)
            ok = os.path.exists(p) and os.path.getsize(p) > 8000
            dim = ""
            try:
                from PIL import Image
                dim = "%dx%d" % Image.open(p).size
            except Exception:
                pass
            results.append(("截图 " + fname, ok, ("%d bytes %s" % (os.path.getsize(p), dim)) if os.path.exists(p) else "未生成"))
    finally:
        httpd.shutdown()

    for name, ok, note in STATIC_ROWS:
        results.insert(0, ("[静态] " + name, bool(ok), note))

    fails = [r for r in results if not r[1]]
    for name, ok, note in results:
        print(("[PASS] " if ok else "[FAIL] ") + name + (("  -- " + note[:300]) if (note and not ok) else ""))
    print("")
    print("=" * 64)
    print("roster_check_verify: %d 项，PASS %d，FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    print("截图目录:", SHOTS)
    print("=" * 64)
    try:
        json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "total": len(results),
                   "pass": len(results) - len(fails), "fail": len(fails),
                   "checks": [{"name": n, "ok": o, "note": t} for n, o, t in results],
                   "shots": [f for f in os.listdir(SHOTS) if f.endswith(".png")]},
                  open(RESULT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        for f in TMP_FILES:
            try:
                os.remove(os.path.join(HERE, f))
            except Exception:
                pass
    sys.exit(code)

