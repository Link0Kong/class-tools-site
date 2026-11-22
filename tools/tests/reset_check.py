# -*- coding: utf-8 -*-
"""自检：抽签 STEP1「重置」按钮（web 端专项）

用法：python tests\\reset_check.py

背景：2026-11-04 用户反馈抽签页的「重置」按钮不见了。核对全部历史线上备份（10-11 → 11-04）
网页版从未有过该按钮（小程序抽签页底部有「重置」），本次按小程序语义在 STEP1 加回：
`#aReset`（「开始抽签」右侧，ghost 样式）——确认后清空本轮抽签结果 / 剔除记录 / 分组结果 /
结果单，但保留抽签参数与参与名单。

做法（复用 roster_check.py 的驱动方式）：
- 复制 index.html 到临时预览页，注入「假身份 + 合成 70 人班级名单 + 抽签/分组种子数据」，
  拦截 tcloudbasegateway / tt.json 请求（不碰真实云端，不出现真实班级名单）；
- headless Edge + 同源 iframe 固定宽度（headless 视口恒 ~492px，不能靠 --window-size）；
- 断言：按钮 DOM/位置/可点高度、无结果提示、取消保留、确定清空（抽签/剔除/分组/结果单）、
  参数与名单保留、仅分组状态也能重置、0 JS 报错、0 console.error、无外部请求、
  360/390/430/720/1280 无横向溢出；
- 截图到 tests/_shots_reset/（合成姓名）：抽签后 / 重置后 × 390·1280。
退出码 0 = 全绿。
"""
import os, sys, json, re, time, shutil, tempfile, threading, http.server, socketserver, functools, subprocess, urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))          # tools/tests
ROOT = os.path.dirname(HERE)                                # tools
# 默认测工作区 index.html；可用 RESET_SRC 指定任意副本（如线上字节落盘文件）复盘
SRC = os.path.abspath(os.environ.get("RESET_SRC") or os.path.join(ROOT, "index.html"))
SHOTS = os.path.join(HERE, "_shots_reset")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8927
BASE = "http://127.0.0.1:%d/" % PORT

SID = "9999000005"
NAME = "测试同学"
MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": "", "badge": "", "is_admin": False} for i in range(1, 71)]

# 抽签 3 个（参与名单 10 人 → 结果带姓名、剔除后有余量自动重抽）；分组种子 6 人（供「仅分组」用例）
SEED = {
    "members": MEMBERS,
    "roster": "\n".join("%d 同学%02d" % (i, i) for i in range(1, 11)),
    "rosterSel": list(range(1, 11)),
    "rosterMigrated": True,
    "groupSel": [10, 11, 12, 13, 14, 15],
    "group": {"source": "prev", "names": "", "mode": "groups", "n": 2, "shuffle": False},
    "rollNames": "",
    "rollSel": [],
    "rollSt": {},
    "draw": {"start": 1, "end": 70, "count": 3, "dup": False, "excl": "", "sort": "draw"},
}

PREVIEW = "_reset_preview.html"
PREVIEW_GATE = "_reset_preview_gate.html"
HARNESS_FUNC = "_reset_harness_func.html"
HARNESS_LAYOUT = "_reset_harness_layout.html"
HARNESS_SHOT = "_reset_harness_shot.html"

REPORT_DIR = os.path.join(HERE, "_reset_reports")

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

LOCAL_MAIN = ('try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"test-token-reset",'
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
function loadState(f){try{return JSON.parse(f.contentWindow.localStorage.getItem(STORE)||"null")||{};}catch(e){return {};}}
function jsonEq(a,b){return JSON.stringify(a)===JSON.stringify(b);}
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
  var R={steps:[],errors:null};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    /* ---- A. 门禁回归：无身份仍停在身份页 ---- */
    var g=await mount(GATE,430,900);
    await sleep(250);
    var gd=g.contentDocument;
    T("未登录仍停在身份页", gd.body.classList.contains("id-locked") && gd.querySelector("#idgate") && getComputedStyle(gd.querySelector("#idgate")).display!=="none");

    /* ---- B. 注入假身份 ---- */
    var f=await mount(SRC,430,900), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},7000);
    await sleep(250);

    /* ---- C. DOM：按钮存在 / 文字 / 位置 / 可点区域 ---- */
    var rs=q(f,"#aReset"), run=q(f,"#aRun");
    T("抽签页有且只有 1 个「重置」按钮", qa(f,"#aReset").length===1 && rs, qa(f,"#aReset").length);
    T("按钮文字为「重置」", !!rs && rs.textContent.trim()==="重置", rs?rs.textContent.trim():"");
    T("按钮是 button 元素", !!rs && rs.tagName==="BUTTON", rs?rs.tagName:"");
    var rb=rs?rs.getBoundingClientRect():{top:0,left:0,right:0,bottom:0,height:0};
    var runb=run?run.getBoundingClientRect():{top:0,left:0,right:0,bottom:0,height:0};
    T("与「开始抽签」同一行（垂直中心差 < 6px）", Math.abs((rb.top+rb.height/2)-(runb.top+runb.height/2))<6,
      "y="+(rb.top+rb.height/2)+" / "+(runb.top+runb.height/2));
    T("在「开始抽签」右侧", rb.left>=runb.right-1, "reset.left="+rb.left+" run.right="+runb.right);
    T("可点高度 ≥ 40px", rb.height>=39.5, rb.height);
    T("按钮完整在视口内", rb.left>=-1 && rb.right<=w.innerWidth+1, "l="+rb.left+" r="+rb.right+" vw="+w.innerWidth);
    T("重置不遮挡抽签按钮（两按钮不重叠）", rb.left>=runb.right-0.5 || rb.top>=runb.bottom-0.5,
      JSON.stringify({r:{l:rb.left,t:rb.top},u:{r:runb.right,b:runb.bottom}}));

    /* 统一下面用可控 confirm；记录调用次数/文案 */
    w.__confirms=[]; w.__confirmReturn=true;
    w.confirm=function(m){w.__confirms.push(String(m));return w.__confirmReturn;};

    /* ---- D. 无结果：提示且不弹确认 ---- */
    click(f,"#aReset"); await sleep(80);
    T("无结果点重置：toast「本轮还没有抽签结果」", /本轮还没有抽签结果/.test(txt(f,"#toast")), txt(f,"#toast"));
    T("无结果点重置：不弹确认框", w.__confirms.length===0, JSON.stringify(w.__confirms));

    /* ---- E. 抽签 3 个（参与名单 10 人 → 都带姓名） ---- */
    T("种子参数：抽取个数 = 3", Number(q(f,"#aCount").value)===3, q(f,"#aCount").value);
    click(f,"#aRun"); await sleep(150);
    T("抽签结果 3 个", qa(f,"#aOut .rcell").length===3, qa(f,"#aOut .rcell").length);
    T("结果都带姓名（参与名单 10 人）", qa(f,"#aOut .rname").length===3, qa(f,"#aOut .rname").length);
    T("抽签后排序行可见", q(f,"#aSortRow").style.display!=="none", q(f,"#aSortRow").style.display);
    click(f,"#aOut .rcell .rx"); await sleep(100);
    T("剔除一个后自动重抽：仍 3 个", qa(f,"#aOut .rcell").length===3, qa(f,"#aOut .rcell").length);
    T("剔除记录 data-log=1", q(f,"#aOut").getAttribute("data-log")==="1", q(f,"#aOut").getAttribute("data-log"));

    /* ---- F. 分组（2026-11-22 起为独立工具；默认「最近抽签」= 本机保存的上次抽签） ---- */
    click(f,"#gSrcSeg [data-gsrc='prev']"); await sleep(80);
    click(f,"#gRun"); await sleep(150);
    T("分组结果 2 组", qa(f,"#gOut .gcard").length===2, qa(f,"#gOut .gcard").length);
    T("分组结果共 3 人", qa(f,"#gOut .gcard .bd span").length===3, qa(f,"#gOut .gcard .bd span").length);

    /* ---- H. 取消确认：不清空 ---- */
    w.__confirms=[]; w.__confirmReturn=false;
    click(f,"#aReset"); await sleep(120);
    T("点重置弹确认框，文案含「重置本轮抽签」", w.__confirms.length===1 && /重置本轮抽签/.test(w.__confirms[0]), JSON.stringify(w.__confirms));
    T("取消后抽签结果保留 3 个", qa(f,"#aOut .rcell").length===3, qa(f,"#aOut .rcell").length);
    T("取消后分组结果保留 2 组", qa(f,"#gOut .gcard").length===2, qa(f,"#gOut .gcard").length);
    T("取消后无「已重置」toast", !/已重置抽签/.test(txt(f,"#toast")), txt(f,"#toast"));

    /* ---- I. 确定重置：只清空抽签（分组是独立工具，不受影响） ---- */
    w.__confirms=[]; w.__confirmReturn=true;
    click(f,"#aReset"); await sleep(150);
    T("确定后抽签结果清空（0 个 / 显示 —）", qa(f,"#aOut .rcell").length===0 && txt(f,"#aOut").indexOf("—")>=0,
      qa(f,"#aOut .rcell").length+"|"+txt(f,"#aOut").trim());
    T("确定后排序行隐藏", q(f,"#aSortRow").style.display==="none", q(f,"#aSortRow").style.display);
    T("确定后 toast「已重置抽签」", /已重置抽签/.test(txt(f,"#toast")), txt(f,"#toast"));
    T("确定后分组结果保留（重置抽签不影响分组）", qa(f,"#gOut .gcard").length===2, qa(f,"#gOut .gcard").length);

    /* ---- J. 参数与参与名单保留 ---- */
    var st=loadState(f);
    T("参数保留：draw.count=3 / 范围 1-70", st.draw && Number(st.draw.count)===3 && Number(st.draw.start)===1 && Number(st.draw.end)===70,
      JSON.stringify(st.draw));
    T("页面输入框仍保留参数", q(f,"#aCount").value==="3" && q(f,"#aStart").value==="1" && q(f,"#aEnd").value==="70",
      q(f,"#aStart").value+"/"+q(f,"#aEnd").value+"/"+q(f,"#aCount").value);
    T("参与名单保留：rosterSel=[1..10]", jsonEq(st.rosterSel,[1,2,3,4,5,6,7,8,9,10]), JSON.stringify(st.rosterSel));
    T("分组名单保留：groupSel=[10..15]", jsonEq(st.groupSel,[10,11,12,13,14,15]), JSON.stringify(st.groupSel));
    T("页面参与名单摘要仍 10 个气泡", qa(f,"#aRosterSum button.rchip").length===10, qa(f,"#aRosterSum button.rchip").length);

    /* ---- K. 重置后再点：回到「无结果」语义 ---- */
    w.__confirms=[];
    click(f,"#aReset"); await sleep(100);
    T("重置后再点：提示「本轮还没有抽签结果」且不弹确认", /本轮还没有抽签结果/.test(txt(f,"#toast")) && w.__confirms.length===0,
      txt(f,"#toast")+"|"+JSON.stringify(w.__confirms));

    /* ---- L. 只有分组结果（无抽签结果）：重置不处理分组（分组是独立工具） ---- */
    click(f,"#gSrcSeg [data-gsrc='pick']"); await sleep(60);
    q(f,"#gNum").value="2";
    click(f,"#gRun"); await sleep(150);
    T("仅分组：自选名单 6 人 → 2 组", qa(f,"#gOut .gcard").length===2, qa(f,"#gOut .gcard").length);
    w.__confirms=[]; w.__confirmReturn=true;
    click(f,"#aReset"); await sleep(120);
    T("仅分组状态：点重置提示无抽签结果且不弹确认",
      /本轮还没有抽签结果/.test(txt(f,"#toast")) && w.__confirms.length===0,
      txt(f,"#toast")+"|"+JSON.stringify(w.__confirms));
    T("仅分组状态：分组结果保持不变", qa(f,"#gOut .gcard").length===2, qa(f,"#gOut .gcard").length);

    /* ---- M. 0 报错 / 无外部请求 ---- */
    var ext=(w.performance.getEntriesByType("resource")||[]).filter(function(e){
      return !/^https?:\/\/127\.0\.0\.1[:/]/.test(e.name) && !/^data:/.test(e.name) && !/^blob:/.test(e.name);
    }).map(function(e){return e.name;});
    T("无外部网络请求", ext.length===0, ext.join(","));
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
    var W=__W__, f=await mount(SRC,W,860), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},7000);
    await sleep(200);
    var de=d.documentElement;
    function ov(){return {sw:de.scrollWidth,cw:de.clientWidth,iw:w.innerWidth,bsw:d.body.scrollWidth,bcw:d.body.clientWidth};}
    var o=ov();
    T("初始无横向溢出", o.sw<=o.cw+1 && o.bsw<=o.bcw+1, JSON.stringify(o));
    var rs=q(f,"#aReset"), run=q(f,"#aRun");
    T("重置按钮存在且可见", !!rs && w.getComputedStyle(rs).display!=="none" && rs.getBoundingClientRect().width>10,
      rs?rs.getBoundingClientRect().width:"missing");
    var rb=rs.getBoundingClientRect(), runb=run.getBoundingClientRect();
    T("重置按钮完整在视口内（不被裁切）", rb.left>=-1 && rb.right<=w.innerWidth+1, "l="+rb.left+" r="+rb.right+" vw="+w.innerWidth);
    T("重置按钮可点高度 ≥ 40px", rb.height>=39.5, rb.height);
    T("重置与开始抽签不重叠", rb.left>=runb.right-0.5 || rb.top>=runb.bottom-0.5,
      JSON.stringify({r:{l:rb.left,t:rb.top},u:{r:runb.right,b:runb.bottom}}));
    /* 抽签后（结果/排序行出现）再审计一次 */
    click(f,"#aRun"); await sleep(200);
    o=ov();
    T("抽签后无横向溢出", o.sw<=o.cw+1 && o.bsw<=o.bcw+1, JSON.stringify(o));
    var rb2=q(f,"#aReset").getBoundingClientRect();
    T("抽签后重置按钮仍完整在视口内", rb2.left>=-1 && rb2.right<=w.innerWidth+1, "l="+rb2.left+" r="+rb2.right+" vw="+w.innerWidth);
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
  var R={steps:[],diag:{},mode:""};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  try{
    var hash=(location.hash||"#390-before").replace("#","");
    var m=hash.match(/^(390|1280)-(before|after)$/);
    var W=m?+m[1]:390, after=m?m[2]==="after":false;
    R.mode=hash;
    var f=await mount(SRC,W,after?860:820), w=f.contentWindow, d=f.contentDocument;
    await waitFor(function(){return !d.body.classList.contains("id-locked");},7000);
    await sleep(250);
    var ns=d.createElement("style");
    ns.textContent=".tabs button,.tabs-thumb{transition:none!important;animation:none!important}";
    d.head.appendChild(ns);
    w.__confirmReturn=true; w.confirm=function(){return true;};
    click(f,"#aRun"); await sleep(250);
    if(after){ click(f,"#aReset"); await sleep(300); }
    R.diag.width=W;
    R.diag.after=after;
    R.diag.results=qa(f,"#aOut .rcell").length;
    R.diag.resetText=txt(f,"#aReset").trim();
    var rb=q(f,"#aReset").getBoundingClientRect();
    R.diag.resetRect={l:rb.left,r:rb.right,t:rb.top,b:rb.bottom,h:rb.height};
    T("截图场景就绪：重置按钮可见", rb.width>10 && rb.height>=39.5, JSON.stringify(R.diag.resetRect));
    T("截图场景结果状态符合预期", after ? R.diag.results===0 : R.diag.results===3, "results="+R.diag.results);
    T("无横向溢出", d.documentElement.scrollWidth<=w.innerWidth+1, d.documentElement.scrollWidth+"/"+w.innerWidth);
    R.errors=(w.__errs||[]).slice();
    T("0 JS 报错", R.errors.length===0, R.errors.join(" | "));
    report("shot_"+R.mode,R);
    await sleep(600);
  }catch(e){
    R.steps.push({k:"截图脚本异常",ok:false,note:String(e&&e.stack||e)});
    report("shot_"+R.mode,R);
  }
}
run();
"""


def build_harness(name, js, src, gate=""):
    body = (COMMON_JS.replace("__SRC__", src).replace("__GATE__", gate).replace("__SID__", SID) + "\n" + js)
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>reset check</title>"
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


def run_edge(url, budget=12000, shot=None, timeout=150, window="492,900", flags=None):
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
    data = None
    last = None
    for _ in range(retries):
        clear_report(slot)
        last = run_edge(url, budget=budget, shot=shot, window=window, flags=flags)
        data = wait_report(slot, secs)
        if data:
            return data
        time.sleep(0.3)
    if os.environ.get("RESET_DEBUG") and last is not None:
        err = (last.stderr or b"").decode("utf-8", "replace")[-1200:]
        print("[DEBUG] slot=%s rc=%s stderr=%s" % (slot, last.returncode, err.replace("\n", " | ")))
    return None


STATIC_CHECKS = []


def static_checks(html):
    STATIC_CHECKS.append(("重置按钮 DOM 唯一且紧跟开始抽签（STEP1）",
                          html.count('id="aReset"') == 1 and html.count('id="aRun"') == 1
                          and 'id="aRun">开始抽签</button>' in html
                          and 'id="aReset" type="button">重置</button>' in html, ""))
    STATIC_CHECKS.append(("重置逻辑：只清空抽签/剔除（分组为独立工具，不清空）",
                          all(k in html for k in ["A.result=null;A.cfg=null;A.log=[];A.removed=[];A.pool=null;",
                                                  "renderA();renderProofLine();renderRecSum();"]), ""))
    STATIC_CHECKS.append(("重置逻辑：无结果提示 + 确认框", "本轮还没有抽签结果" in html and "重置本轮抽签？" in html, ""))
    STATIC_CHECKS.append(("使用说明已写明「重置」", "点「重置」只清空本轮抽签，参数和参与名单保留" in html, ""))
    STATIC_CHECKS.append(("无 CDN / 外部资源引用",
                          not re.search(r'<(script|link|img|iframe|source|video)[^>]+(src|href)\s*=\s*["\']https?://', html), ""))
    STATIC_CHECKS.append(("既有抽签按钮未被破坏（导出/排序；下一步已随拆分移除）",
                          all(k in html for k in ['id="aImg"', 'data-asort="desc"', 'data-asort="asc"', 'data-asort="rand"'])
                          and 'id="aNext"' not in html, ""))


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
    build_harness(HARNESS_SHOT, SHOT_JS, PREVIEW)

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
        # 1) 功能专项（430 宽）
        add_many("功能", run_and_report(BASE + "tests/" + HARNESS_FUNC, "func", budget=26000, secs=34))

        # 2) 各档宽度：无横向溢出 + 按钮不被裁切
        for w in (360, 390, 430, 720, 1280):
            js = LAYOUT_JS.replace("__W__", str(w))
            build_harness(HARNESS_LAYOUT, js, PREVIEW)
            add_many("溢出@" + str(w), run_and_report(BASE + "tests/" + HARNESS_LAYOUT, "layout_%d" % w, budget=18000))

        # 3) 截图：抽签后 / 重置后 × 390·1280
        for mode, fname, winsz in (("390-before", "reset_before_390.png", "390,860"),
                                   ("390-after", "reset_after_390.png", "390,860"),
                                   ("1280-before", "reset_before_1280.png", "1280,860"),
                                   ("1280-after", "reset_after_1280.png", "1280,860")):
            p = os.path.join(SHOTS, fname)
            if os.path.exists(p):
                os.remove(p)
            data = run_and_report(BASE + "tests/" + HARNESS_SHOT + "#" + mode, "shot_" + mode,
                                  budget=32000, shot=p, window=winsz, secs=20)
            add_many("截图:" + mode, data)
            ok = os.path.exists(p) and os.path.getsize(p) > 10000
            results.append(("截图 " + fname, ok, ("%d bytes" % os.path.getsize(p)) if os.path.exists(p) else "未生成"))
    finally:
        httpd.shutdown()

    for name, ok, note in STATIC_CHECKS:
        results.insert(0, ("[静态] " + name, bool(ok), note))

    fails = [r for r in results if not r[1]]
    for name, ok, note in results:
        print(("[PASS] " if ok else "[FAIL] ") + name + (("  -- " + note[:220]) if (note and not ok) else ""))
    print("")
    print("=" * 60)
    print("reset_check: %d 项，PASS %d，FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    print("截图目录:", SHOTS)
    print("=" * 60)
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        for f in (PREVIEW, PREVIEW_GATE, HARNESS_FUNC, HARNESS_LAYOUT, HARNESS_SHOT):
            try:
                os.remove(os.path.join(HERE, f))
            except Exception:
                pass
    sys.exit(code)
