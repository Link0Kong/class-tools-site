# -*- coding: utf-8 -*-
"""自检：访问统计 / 反馈写入（统计修复专项）
用法：python tests\\stats_check.py

背景（2026-11-04）：
- visits / feedback 的 SELECT RLS 只允许管理员（或本人行，修复后）；
- 网页写这两张表时带 Prefer: return=representation，PostgREST 的 returning 要求新行可被 SELECT，
  非管理员会被 401 拒绝且前端静默失败 → 统计只有管理员自己。
- 修复：网页新增 cbPostNoRep()，visits 埋点与反馈提交改为不请求 representation；云端 RLS 同时放行本人行。

本脚本用「假身份 + 拦截云端 fetch」在 headless Edge 里验证：
1) 非管理员进入页面：visits POST 发生、无 Prefer/return=representation、带 X-Device-Id、body 含本人 sid；
2) 非管理员提交反馈：feedback POST 发生、无 Prefer、body acc=本人 sid；
3) 管理员打开「统计」：GET visits（带 token）→ 按姓名聚合出多个账号（不显示学号），今天/近 7 天切换正常；
4) 全程 0 JS 报错、无外部请求（除被 mock 的 CloudBase）。
退出码 0 = 全绿；截图落 tests\\_shots_stats\\。
"""
import os, sys, json, time, shutil, tempfile, threading, http.server, socketserver, functools, subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "index.html")
SHOTS = os.path.join(HERE, "_shots_stats")
REPORT_DIR = os.path.join(HERE, "_stats_reports")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8917
BASE = "http://127.0.0.1:%d/" % PORT

NONADMIN = {"token": "test-token-stats-nonadmin", "sid": "9999000005", "name": "测试同学",
            "role": "", "badge": "", "is_admin": False, "ts": int(time.time() * 1000)}
ADMIN = {"token": "test-token-stats-admin", "sid": "9999000009", "name": "测试管理员",
         "role": "团支书", "badge": "班委", "is_admin": True, "ts": int(time.time() * 1000)}

PREVIEW_NON = "_stats_preview_nonadmin.html"
PREVIEW_ADMIN = "_stats_preview_admin.html"
HARNESS = "_stats_harness.html"

INJECT = """<script>
(function(){
window.__reqs=[];window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));_ce.apply(console,arguments);};
/* headless + virtual-time 下 IndexedDB 回调可能不推进：让缓存层快速回退（不影响被测逻辑） */
try{ Object.defineProperty(window,"indexedDB",{value:undefined,configurable:true}); }catch(e){}
function d(n){return new Date(Date.now()-n*86400000);}
function pad2(n){return ("0"+n).slice(-2);}
function ymd(x){return x.getFullYear()+"-"+pad2(x.getMonth()+1)+"-"+pad2(x.getDate());}
function at(dayOffset,h,m){
  var x=d(dayOffset); x.setHours(h,m,0,0); return x.getTime();
}
var TODAY=ymd(new Date()), YEST=ymd(d(1));
var FAKE_VISITS=[
  {slot:TODAY+"-09",sid:"9000000001",name:"张三",ts:at(0,9,7),client:"web",ver:"2.0.0",dev:"Windows · Edge 131",did:"d100000000000001"},
  {slot:TODAY+"-10",sid:"9000000002",name:"李四",ts:at(0,10,42),client:"mp",ver:"2.0.0",dev:"Apple iPhone 15 · iOS 18.1",did:"d100000000000002"},
  {slot:TODAY+"-11",sid:"9000000001",name:"张三",ts:at(0,11,5),client:"android",ver:"1.0.0-beta14",dev:"Xiaomi 23127PN0CC · Android 15",did:"d100000000000003"},
  {slot:TODAY+"-12",sid:"9000000003",name:"王五",ts:at(0,12,0),client:"win",ver:"0.1.0",dev:"Windows 11 · x64",did:"d100000000000004"},
  {slot:TODAY+"-12",sid:"3260799999",name:"测试账号",ts:at(0,12,30),client:"web",ver:"2.0.0",dev:"Windows · Edge 131"},
  {slot:TODAY+"-12",sid:"9999000001",name:"测试同学",ts:at(0,12,40),client:"mp",ver:"2.0.0",dev:"Apple iPhone 15 · iOS 18.1"},
  {slot:YEST+"-20",sid:"9000000004",name:"赵六",ts:at(1,20,15),client:"harmony",ver:"1.0.8",dev:"Mate 60 · HarmonyOS 5.0.0",did:"d100000000000005"},
  {slot:YEST+"-08",sid:"9000000005",name:"周八"}   /* 旧行：无 ts/client/ver/dev，回退 slot 整点 + 未记录 */
];
function fake(status,body){return Promise.resolve({ok:status>=200&&status<300,status:status,
  json:function(){return Promise.resolve(body);},text:function(){return Promise.resolve(JSON.stringify(body));}});}
var _f=window.fetch;
window.fetch=function(u,o){
  var s=String(u||""), m=(o&&o.method)||"GET", h=(o&&o.headers)||{};
  if(s.indexOf("tcloudbasegateway")<0){ return _f.apply(this,arguments); }
  var hdr={}; for(var k in h)hdr[k.toLowerCase()]=h[k];
  var rec={url:s,method:m,headers:hdr,body:o&&o.body?String(o.body):""};
  window.__reqs.push(rec);
  if(s.indexOf("/rpc/class_members")>=0) return fake(200,[{seat:1,sid:"__SID__",name:"__NAME__",role:"__ROLE__",badge:"__BADGE__",is_admin:__ADMIN__}]);
  if(s.indexOf("/rpc/class_set_role")>=0) return fake(200,{ok:true});
  if(s.indexOf("/visits")>=0){ if(m==="POST"){rec.status=201;return fake(201,[]);} rec.status=200;return fake(200,FAKE_VISITS); }
  if(s.indexOf("/feedback")>=0){ if(m==="POST"){rec.status=201;return fake(201,[]);} rec.status=200;return fake(200,[]); }
  rec.status=200;
  return fake(200,[]);
};
__LOCAL__
})();
</script>"""

LOCAL_SEED = ('try{localStorage.setItem("zq_class_identity",JSON.stringify(%s));'
              'localStorage.removeItem("zq_visit_slot_%s");'
              'localStorage.setItem("zq_tools_v2_%s",JSON.stringify({homeTools:["draw","tt","hw","nt"]}));'
              '}catch(e){}')


def build_previews():
    html = open(SRC, encoding="utf-8").read()
    for name, ident in ((PREVIEW_NON, NONADMIN), (PREVIEW_ADMIN, ADMIN)):
        inject = (INJECT.replace("__SID__", ident["sid"]).replace("__NAME__", ident["name"])
                  .replace("__ROLE__", ident["role"]).replace("__BADGE__", ident["badge"])
                  .replace("__ADMIN__", "true" if ident["is_admin"] else "false")
                  .replace("__LOCAL__", (LOCAL_SEED % (json.dumps(ident, ensure_ascii=False), ident["sid"], ident["sid"]))))
        out = html.replace("<head>", "<head>" + inject, 1)
        open(os.path.join(HERE, name), "w", encoding="utf-8").write(out)


COMMON_JS = r"""
var SRC_NON="__SRC_NON__", SRC_ADMIN="__SRC_ADMIN__";
var NON_SID="__NON_SID__", ADMIN_SID="__ADMIN_SID__";
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
    f.onload=function(){ if(done)return; done=true; setTimeout(function(){res(f);},120); };
    document.body.appendChild(f);
    setTimeout(function(){ if(!done){done=true;res(f);} },8000);
  });
}
function q(f,s){return f.contentDocument.querySelector(s);}
function qa(f,s){return Array.prototype.slice.call(f.contentDocument.querySelectorAll(s));}
function report(slot,data){
  try{
    var x=new XMLHttpRequest();
    x.open("POST","/_report?slot="+slot,false);
    x.setRequestHeader("Content-Type","application/json");
    x.send(JSON.stringify(data||{}));
  }catch(e){}
}
function reqs(w){return (w.__reqs||[]);}
function findReq(w,method,part){return reqs(w).filter(function(r){return r.method===method&&r.url.indexOf(part)>=0;});}
function hasRep(r){var p=r.headers&&r.headers["prefer"];return !!p&&String(p).indexOf("return=representation")>=0;}
"""


FUNC_JS = r"""
async function run(){
  var R={steps:[]};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note).slice(0,400)});}
  try{
    /* ================= A. 非管理员：访问埋点 ================= */
    var f=await mount(SRC_NON,430,900), w=f.contentWindow, d=f.contentDocument;
    await sleep(6000);   /* visitLog 在 bootRefresh 里同步触发（依赖 bootCache 的 Promise） */
    var vp=findReq(w,"POST","/visits");
    T("非管理员进入页面会写 visits 埋点", vp.length===1,
      "POST /visits x"+vp.length+" | all="+reqs(w).map(function(r){return r.method+" "+r.url.split("/rest/")[1];}).join(" , "));
    if(vp.length){
      var r=vp[0];
      T("visits 请求不带 Prefer: return=representation", !hasRep(r), JSON.stringify(r.headers));
      T("visits 请求带 X-Device-Id（班级 token）", !!r.headers["x-device-id"], JSON.stringify(r.headers));
      var body=[];try{body=JSON.parse(r.body);}catch(e){}
      T("visits body 是数组且 sid=本人", Array.isArray(body)&&body[0]&&body[0].sid===NON_SID, r.body.slice(0,200));
      T("visits slot 形如 YYYY-MM-DD-HH", !!(body[0]&&/^\d{4}-\d{2}-\d{2}-\d{2}$/.test(body[0].slot||"")), body[0]&&body[0].slot);
      T("visits 记录登录端 client=web", !!(body[0]&&body[0].client==="web"), body[0]&&body[0].client);
      T("visits 记录应用版本 ver", !!(body[0]&&/^\d+\.\d+\.\d+/.test(String(body[0].ver||""))), body[0]&&body[0].ver);
      T("visits 记录设备 dev（≤48，不含姓名/学号）", !!(body[0]&&String(body[0].dev||"").length>0&&String(body[0].dev||"").length<=48)
        && String(body[0].dev).indexOf(NON_SID)<0&&String(body[0].dev).indexOf("测试同学")<0, body[0]&&body[0].dev);
      T("visits 响应按成功处理（本地已记录 slot）", !!f.contentWindow.localStorage.getItem("zq_visit_slot_"+NON_SID), f.contentWindow.localStorage.getItem("zq_visit_slot_"+NON_SID));
    }

    /* ================= B. 非管理员：反馈提交 ================= */
    var ft=q(f,"#fbText"), fc=q(f,"#fbContact"), fg=q(f,"#fbGo");
    T("反馈 DOM 存在", !!ft&&!!fc&&!!fg);
    if(ft&&fc&&fg){
      ft.value="统计自检反馈（不会真的提交）"; fc.value="";
      fg.click();
      await sleep(700);
      var fp=findReq(w,"POST","/feedback");
      T("提交反馈会写 feedback", fp.length===1, "POST /feedback x"+fp.length);
      if(fp.length){
        var rr=fp[0], fb=[];try{fb=JSON.parse(rr.body);}catch(e){}
        T("feedback 请求不带 Prefer: return=representation", !hasRep(rr), JSON.stringify(rr.headers));
        T("feedback 请求带 X-Device-Id", !!rr.headers["x-device-id"], JSON.stringify(rr.headers));
        T("feedback body acc=本人 sid", !!(fb[0]&&fb[0].acc===NON_SID), rr.body.slice(0,200));
      }
      T("提交后输入框被清空（成功回调）", ft.value==="", ft.value);
    }
    T("非管理员页面 0 JS 报错", (w.__errs||[]).length===0, JSON.stringify(w.__errs||[]));
    T("非管理员页面 0 console.error", (w.__cerrs||[]).length===0, JSON.stringify(w.__cerrs||[]));

    /* ================= C. 管理员：统计页 ================= */
    var g=await mount(SRC_ADMIN,430,900), w2=g.contentWindow, d2=g.contentDocument;
    await sleep(1500);
    var allBtn=q(g,'#tabsBar button[data-tab="all"]');
    T("管理员工具栏有「全部」", !!allBtn);
    if(allBtn) allBtn.click();
    await sleep(400);
    var statsBtn=q(g,'#allCards [data-open="stats"]');
    T("「全部」页有统计入口", !!statsBtn);
    if(statsBtn) statsBtn.click();
    await sleep(1200);
    var gp=findReq(w2,"GET","/visits");
    T("统计页会 GET visits", gp.length>=1, "GET /visits x"+gp.length);
    if(gp.length){
      T("GET visits 带 X-Device-Id", !!gp[0].headers["x-device-id"], JSON.stringify(gp[0].headers));
      T("GET visits 带 slot 起始过滤", gp[0].url.indexOf("slot=gte.")>=0, gp[0].url);
      T("GET visits 选取 ts/client", gp[0].url.indexOf("select=slot,sid,name,ts,client")>=0, gp[0].url);
      T("GET visits 选取 ver/dev/did", gp[0].url.indexOf("select=slot,sid,name,ts,client,ver,dev,did")>=0, gp[0].url);
      T("GET visits 按 ts 倒序", gp[0].url.indexOf("order=ts.desc")>=0, gp[0].url);
      T("GET visits 上限 5000", gp[0].url.indexOf("limit=5000")>=0, gp[0].url);
    }
    var rows=qa(g,"#stOut .strow");
    T("今天口径：聚合出 3 个账号（张三/李四/王五）", rows.length===3, "rows="+rows.length);
    var txt=q(g,"#stOut")?q(g,"#stOut").textContent:"";
    T("统计按姓名展示", txt.indexOf("张三")>=0&&txt.indexOf("李四")>=0&&txt.indexOf("王五")>=0, txt.slice(0,120));
    T("统计不展示学号", txt.indexOf("9000000")<0&&txt.indexOf("3260")<0, txt.slice(0,120));
    T("忽略官方测试账号 3260799999", txt.indexOf("测试账号")<0, txt.slice(0,160));
    T("忽略 9999 段 QA 测试身份", txt.indexOf("测试同学")<0, txt.slice(0,160));
    var sum=(q(g,"#stSum")||{textContent:""}).textContent;
    T("摘要：访问账号=3 / 访问次数=4 / 今日活跃=3", sum.indexOf("3")>=0&&sum.indexOf("4")>=0, sum.replace(/\s+/g," "));
    T("摘要四格含访问设备", qa(g,"#stSum .s").length===4&&sum.indexOf("访问设备")>=0, sum.replace(/\s+/g," "));
    T("今天口径下赵六（昨天）不出现", txt.indexOf("赵六")<0, txt.slice(0,120));
    /* 排序：访问次数优先；次数相同再按最近访问（张三 2 次 > 王五 1 次 12:00 > 李四 1 次 10:42） */
    var names=qa(g,"#stOut .strow .lb").map(function(x){return x.textContent;});
    T("按访问次数优先（张三→王五→李四）", names.length===3&&names[0].indexOf("张三")>=0&&names[1].indexOf("王五")>=0&&names[2].indexOf("李四")>=0, names.join(" | "));
    T("时间精确到分钟（11:05 / 10:42，而不是整点）", txt.indexOf("11:05")>=0&&txt.indexOf("10:42")>=0, txt.slice(0,200));
    var clis=qa(g,"#stOut .stcli").map(function(x){return x.textContent;});
    T("记录具体登录端（安卓/Windows/小程序）", clis.indexOf("Windows")>=0&&clis.indexOf("安卓")>=0&&clis.indexOf("小程序")>=0, clis.join(" | "));
    T("同一账号取最近登录端（张三最近=安卓）", names.length===3&&names[0].indexOf("张三")>=0&&clis[0]==="安卓", names.join(" | ")+" :: "+clis.join(" | "));

    /* —— 可视化：趋势 / 登录端 / 版本 / 设备 —— */
    T("今天趋势为 24 小时柱", qa(g,"#stTrend .st-tcol").length===24, "bars="+qa(g,"#stTrend .st-tcol").length);
    T("趋势柱有高度与数值", qa(g,"#stTrend .st-tbar").some(function(x){return parseFloat(x.style.height)>0;})&&
      qa(g,"#stTrend .st-tv").some(function(x){return x.textContent.trim().length>0;}), q(g,"#stTrend").textContent.slice(0,120));
    T("登录端堆叠条与图例", qa(g,"#stCli .st-cli-seg").length>=3&&qa(g,"#stCli .st-leg").length>=3,
      "seg="+qa(g,"#stCli .st-cli-seg").length+" leg="+qa(g,"#stCli .st-leg").length);
    var verTxt=q(g,"#stVer")?q(g,"#stVer").textContent:"";
    T("版本分布含 2.0.0 / 1.0.0-beta14 / 0.1.0", verTxt.indexOf("2.0.0")>=0&&verTxt.indexOf("1.0.0-beta14")>=0&&verTxt.indexOf("0.1.0")>=0, verTxt.slice(0,200));
    var devTxt=q(g,"#stDev")?q(g,"#stDev").textContent:"";
    T("设备分布含 Windows / 安卓机型 / iPhone", devTxt.indexOf("Windows")>=0&&devTxt.indexOf("Xiaomi")>=0&&devTxt.indexOf("iPhone")>=0, devTxt.slice(0,240));
    T("账号行显示版本/设备标签", qa(g,"#stOut .stver").length>=1&&qa(g,"#stOut .stdev").length>=1,
      "ver="+qa(g,"#stOut .stver").length+" dev="+qa(g,"#stOut .stdev").length);

    /* —— 账号明细展开 —— */
    var firstRow=q(g,"#stOut .strow");
    if(firstRow) firstRow.click();
    await sleep(150);
    var detail=q(g,"#stOut .st-acc-detail:not([hidden])");
    var detailTxt=detail?detail.textContent:"";
    T("点击账号展开明细", !!detail, detailTxt.slice(0,160));
    T("明细含活跃/首次/最近", detailTxt.indexOf("首次")>=0&&detailTxt.indexOf("最近")>=0, detailTxt.slice(0,200));
    T("明细含登录端/版本/设备分组", detailTxt.indexOf("登录端")>=0&&detailTxt.indexOf("版本")>=0&&detailTxt.indexOf("设备")>=0, detailTxt.slice(0,240));
    T("明细含具体设备与次数", detailTxt.indexOf("Windows · Edge 131")>=0&&detailTxt.indexOf("次")>=0, detailTxt.slice(0,240));
    if(firstRow) firstRow.click();
    await sleep(120);
    T("再次点击账号收起明细", !q(g,"#stOut .st-acc-detail:not([hidden])"));
    T("430 宽无横向溢出", d2.documentElement.scrollWidth<=432, "scrollWidth="+d2.documentElement.scrollWidth);

    /* 近 7 天：出现赵六（4 个账号） */
    var week=qa(g,'input[name="strange"]').filter(function(x){return x.value==="week";})[0];
    T("有近 7 天切换", !!week);
    if(week){ week.click(); await sleep(400);
      var txt2=q(g,"#stOut")?q(g,"#stOut").textContent:"";
      T("近 7 天口径包含昨天账号（赵六）", txt2.indexOf("赵六")>=0, txt2.slice(0,160));
      T("近 7 天聚合出 5 个账号（含旧行）", qa(g,"#stOut .strow").length===5, "rows="+qa(g,"#stOut .strow").length);
      T("近 7 天显示赵六登录端=鸿蒙", txt2.indexOf("鸿蒙")>=0, txt2.slice(0,200));
      T("旧行无 client 显示未记录、无 ts 回退整点 08:00", txt2.indexOf("未记录")>=0&&txt2.indexOf("08:00")>=0, txt2.slice(0,240));
      T("近 7 天趋势为 7 天柱", qa(g,"#stTrend .st-tcol").length===7, "bars="+qa(g,"#stTrend .st-tcol").length);
      T("近 7 天登录端图例含未记录", (q(g,"#stCli")||{textContent:""}).textContent.indexOf("未记录")>=0, (q(g,"#stCli")||{textContent:""}).textContent.slice(0,200));
      T("近 7 天版本分布含鸿蒙 1.0.8", (q(g,"#stVer")||{textContent:""}).textContent.indexOf("1.0.8")>=0, (q(g,"#stVer")||{textContent:""}).textContent.slice(0,200));
      T("近 7 天版本分布含未记录（旧数据）", (q(g,"#stVer")||{textContent:""}).textContent.indexOf("未记录")>=0, (q(g,"#stVer")||{textContent:""}).textContent.slice(0,200));
    }
    /* 默认打开今天：切去别的 tab 再进统计，范围回到今天 */
    var allBtn2=q(g,'#tabsBar button[data-tab="all"]'); if(allBtn2) allBtn2.click(); await sleep(300);
    var statsBtn2=q(g,'#allCards [data-open="stats"]'); if(statsBtn2) statsBtn2.click(); await sleep(500);
    var dayRadio=qa(g,'input[name="strange"]').filter(function(x){return x.value==="day";})[0];
    T("再次进入统计默认回到今天（radio 选中）", !!dayRadio&&dayRadio.checked, dayRadio?String(dayRadio.checked):"missing");
    T("再次进入统计只显示今天 3 个账号", qa(g,"#stOut .strow").length===3, "rows="+qa(g,"#stOut .strow").length);
    T("管理员页面 0 JS 报错", (w2.__errs||[]).length===0, JSON.stringify(w2.__errs||[]));
    var ext=[];
    [w,w2].forEach(function(win){
      try{ (win.performance.getEntriesByType("resource")||[]).forEach(function(e){
        var u=String(e.name||"");
        if(!/^https?:\/\/127\.0\.0\.1[:/]/.test(u)&&!/^data:/.test(u)&&!/^blob:/.test(u)
           &&!/^https?:\/\/121\.196\.47\.2\/drop\/presence/.test(u))ext.push(u);
      }); }catch(e){}
    });
    T("全程无第三方外部请求（只允许 127.0.0.1 + 被 mock 的云端 + 大屏互联 presence）", ext.length===0, ext.join(","));
    /* 截图用：拉高 iframe 并展开第一个账号，便于人工检查版本/设备与明细 */
    try{
      var fr=document.getElementById("fr");
      if(fr){fr.style.height="1500px"; if(fr.contentWindow)fr.contentWindow.scrollTo(0,0);
        var r0=fr.contentDocument.querySelector("#stOut .strow"); if(r0)r0.click();}
    }catch(e){}
  }catch(e){
    R.steps.push({k:"脚本异常",ok:false,note:String((e&&e.message)||e)});
  }
  report("func",R);
}
run();
"""


def run_edge(url, budget=20000, shot=None, window="492,900", timeout=120):
    prof = tempfile.mkdtemp(prefix="edgeprof_stats_", dir=REPORT_DIR)
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


def build_harness(js):
    page = ('<!doctype html><html><head><meta charset="utf-8"><title>stats harness</title></head>'
            '<body style="margin:0;background:#eee">'
            '<script src="_stats_common.js"></script>'
            '<script>' + js + '</script></body></html>')
    open(os.path.join(HERE, HARNESS), "w", encoding="utf-8").write(page)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    for f in os.listdir(REPORT_DIR):
        try:
            os.remove(os.path.join(REPORT_DIR, f))
        except Exception:
            pass
    build_previews()
    common = (COMMON_JS.replace("__SRC_NON__", PREVIEW_NON).replace("__SRC_ADMIN__", PREVIEW_ADMIN)
              .replace("__NON_SID__", NONADMIN["sid"]).replace("__ADMIN_SID__", ADMIN["sid"]))
    open(os.path.join(HERE, "_stats_common.js"), "w", encoding="utf-8").write(common)
    build_harness(FUNC_JS)

    httpd = http.server.ThreadingHTTPServer
    handler = functools.partial(Handler, directory=ROOT)
    server = httpd(("127.0.0.1", PORT), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.4)

    results = []
    try:
        clear_report("func")
        run_edge(BASE + "tests/" + HARNESS, budget=26000)
        data = wait_report("func", 30)
        if not data:
            results.append(("自检脚本未返回结果", False, "report 缺失（浏览器未上报）"))
        else:
            for s in data.get("steps", []):
                results.append((s.get("k", "?"), bool(s.get("ok")), s.get("note", "")))
        # 截图（管理员统计页）：直接跑截图 harness
        shot = os.path.join(SHOTS, "stats_admin_430.png")
        if os.path.exists(shot):
            os.remove(shot)
        run_edge(BASE + "tests/" + HARNESS, budget=26000, shot=shot, window="492,1560")
        ok = os.path.exists(shot) and os.path.getsize(shot) > 8000
        results.append(("统计页截图 stats_admin_430.png", ok,
                        ("%d bytes" % os.path.getsize(shot)) if os.path.exists(shot) else "未生成"))
    finally:
        server.shutdown()

    fails = [r for r in results if not r[1]]
    for name, ok, note in results:
        print(("[PASS] " if ok else "[FAIL] ") + name + (("  -- " + str(note)[:300]) if (note and not ok) else ""))
    print("")
    print("=" * 60)
    print("stats_check: %d 项，PASS %d，FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    print("截图目录:", SHOTS)
    print("=" * 60)
    return 0 if not fails else 1


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        u = self.path.split("?")[0]
        if u == "/_report":
            slot = self.path.split("slot=")[1] if "slot=" in self.path else "x"
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(n)
                open(os.path.join(REPORT_DIR, slot + ".json"), "wb").write(body)
            except Exception:
                pass
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(404)

    def do_GET(self):
        if self.path.startswith("/_report"):
            self.send_error(404)
            return
        return super().do_GET()


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


if __name__ == "__main__":
    try:
        code = main()
    finally:
        for f in (PREVIEW_NON, PREVIEW_ADMIN, HARNESS, "_stats_common.js"):
            try:
                os.remove(os.path.join(HERE, f))
            except Exception:
                pass
    sys.exit(code)
