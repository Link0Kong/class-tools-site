# -*- coding: utf-8 -*-
"""自检 A：交互冒烟 —— 本地 HTTP 打开页面（种子=旧版数据结构，验证迁移），模拟点击全部按钮，断言 0 JS 报错。
用法：python tests\\selfcheck.py
"""
import os, json, subprocess, threading, http.server, socketserver, functools, time, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "index.html")
EDGE = None
for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
          r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
    if os.path.exists(p):
        EDGE = p
        break
if not EDGE:
    sys.exit("找不到 Edge")

# 故意写「旧版」数据结构（ziqi.tools.v1），顺带验证自动迁移
OLD_SEED = {
    "names": "张伟\n王芳\n李娜\n刘洋",
    "termStart": "2026-08-31",
    "courses": [{"name": "高等数学", "teacher": "王老师", "room": "A301", "day": 0, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"}],
    "homework": [{"subject": "英语", "content": "Unit 3 练习", "due": "长期", "date": "2099-01-01", "done": False}],
    "notices": [{"title": "班会通知", "body": "周五 19:00 A301", "pin": True, "imp": True, "ts": 1759900000000}],
    "settings": {"kind": "webhook", "url": ""},
}

html = open(SRC, encoding="utf-8").read()
html = html.replace("<head>",
    '<head><script>window.__err="";window.addEventListener("error",function(e){window.__err+="["+e.message+"]";});'
    'var _f=window.fetch;window.fetch=function(u,o){if(String(u).indexOf("tcloudbasegateway")>=0||String(u).indexOf("tt.json")>=0)return Promise.reject(new Error("test-block"));return _f.apply(this,arguments);};'
    'window.addEventListener("unhandledrejection",function(e){window.__err+="[rej:"+(e.reason&&e.reason.message||e.reason)+"]";});'
    'window.__dl=0;var __c=HTMLAnchorElement.prototype.click;HTMLAnchorElement.prototype.click=function(){if(this.download){window.__dl++;return;}return __c.apply(this,arguments);};'
    'window.confirm=function(){return true;};</script>')
html = html.replace('<div id="toast"></div>',
    '<div id="toast"></div>\n<script>try{localStorage.removeItem("zq_tools_v2");localStorage.removeItem("zq_tools_v2_t7");localStorage.setItem("ziqi.tools.v1",JSON.stringify(%s));'
    'localStorage.setItem("zq_class_identity",JSON.stringify({token:"test-token",sid:"3260707024",name:"测试",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}</script>'
    % json.dumps(OLD_SEED, ensure_ascii=False))
html = html.replace("</body>", """<script>window.addEventListener("load",function(){setTimeout(function(){
  var log=[];
  function c(sel){var e=document.querySelector(sel);if(!e){log.push("MISS"+sel);return;}e.click();}
  try{
    // 抽签工作流
    c("#aRun");
    function nums(){return Array.prototype.map.call(document.querySelectorAll("#aOut .rcell"),function(e){return parseInt(e.getAttribute("data-n"),10);});}
    c("#aSortRow [data-asort='desc']"); var _d=nums(); window.__descOK=_d.every(function(v,i){return i===0||_d[i-1]>=v;});
    c("#aSortRow [data-asort='asc']"); var _a=nums(); window.__ascOK=_a.every(function(v,i){return i===0||_a[i-1]<=v;});
    c("#aSortRow [data-asort='rand']");
    var rn=[]; for(var i=1;i<=70;i++) rn.push("名字"+i);
    document.querySelector("#aRoster").value=rn.join("\\n");
    document.querySelector("#aRoster").dispatchEvent(new Event("input",{bubbles:true}));
    var fc=document.querySelector("#aOut .rcell"); var fn=parseInt(fc.getAttribute("data-n"),10);
    var fnm=fc.querySelector(".rname");
    window.__mapOK=!!fnm&&fnm.textContent==="名字"+fn;
    var ta=document.querySelector("#aRoster"); ta.setSelectionRange(ta.value.length,ta.value.length);
    ta.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",bubbles:true,cancelable:true}));
    window.__entOK=/\\n71\\s$/.test(ta.value);
    c("#aImg");
    var rx=document.querySelector("#aOut .rx"); if(rx)rx.click();
    window.__rmOK=document.querySelector("#aOut").getAttribute("data-log")==="1"&&document.querySelectorAll("#aOut .rcell").length===10;
    c("[data-step='2']"); c("#gRun");
    window.__grpOK=!!document.querySelector("#gOut .gcard .bd b");
    var g1=document.querySelector("#gOut").textContent;
    c("#gRun");
    window.__detOK=document.querySelector("#gOut").textContent===g1;
    c("#gImg"); c("#gCopy");
    c("[data-step='3']");
    window.__sumOK=document.querySelectorAll("#sOut .dn").length>0;
    c("#sImg"); c("#sCopy");
    // 其它工具
    c("[data-tab='all']"); c("[data-open='tt']"); c("#tImg");
    c("[data-tab='hw']"); c("#hImg");
    var t1=document.querySelector("#hList [data-tg]"); t1.click();
    var d1=document.querySelector("#hList .item.done [data-tg]");
    window.__doneOK=!!d1; if(d1)d1.click();
    window.__doneOK=window.__doneOK&&!document.querySelector("#hList .item.done");
    c("[data-tab='nt']"); document.querySelector("#nTitle").value="测试通知";document.querySelector("#nBody").value="测试正文";
    c("#nImg");
    var p1=document.querySelector("#nList [data-pin]"); p1.click();
    window.__pinOK=!document.querySelector("#nList .item.pin");
    var p2=document.querySelector("#nList [data-pin]"); p2.click();
    window.__pinOK=window.__pinOK&&!!document.querySelector("#nList .item.pin");
    var ta2=document.querySelector("#aRoster"); ta2.value="甲\\n乙"; ta2.setSelectionRange(3,3);
    ta2.dispatchEvent(new Event("input",{bubbles:true}));
    window.__preOK=ta2.value.split("\\n")[0]==="1 甲"&&ta2.value.split("\\n")[1]==="2 乙";
    c("#aClear");
    window.__clrOK=ta2.value===""&&!document.querySelector("#aOut .rname");
    // 体测（男·大一大二，全 80 分档 → 标准分 83.0）
    c("[data-tab='all']"); c("[data-open='ft']");
    var ftv={fH:"175",fW:"65",fVc:"4300",fR50:"7.1",fSit:"17.7",fJump:"248",fPull:"15",fDurM:"3",fDurS:"42"};
    for(var fk in ftv){var fe=document.querySelector("#"+fk);fe.value=ftv[fk];fe.dispatchEvent(new Event("input",{bubbles:true}));}
    window.__ftOK=document.querySelector("#fSum .big").textContent==="83.0"&&/良好/.test(document.querySelector("#fSum").textContent);
    window.__ftRows=document.querySelectorAll("#fRows .ftrow").length;
    window.__ftSub=document.querySelector("#fSub").textContent;
    window.__ftLblM=document.querySelector("#fPullL").textContent;
    c("#fImg"); c("#fCopy");
    var fsex=document.querySelector("input[name=ftsex][value=f]"); fsex.checked=true;
    fsex.dispatchEvent(new Event("change",{bubbles:true}));
    window.__ftLblF=document.querySelector("#fPullL").textContent;
    window.__ftDurF=document.querySelector("#fDurL").textContent;
    var fgr=document.querySelector("#fGrade"); fgr.value="34"; fgr.dispatchEvent(new Event("change",{bubbles:true}));
    window.__ftSc=document.querySelector("#fRows .ftrow:nth-child(2) .s").textContent;
    document.querySelector("#fVc").value=""; document.querySelector("#fVc").dispatchEvent(new Event("input",{bubbles:true}));
    window.__prtOK=document.querySelector("#fSum .big").textContent!=="—"&&/按 0 计/.test(document.querySelector("#fSub").textContent);
    document.querySelector("#fVc").value="4300"; document.querySelector("#fVc").dispatchEvent(new Event("input",{bubbles:true}));
    c("#fWipe");
    window.__ftClrOK=document.querySelector("#fSum .big").textContent==="—"&&document.querySelectorAll("#fRows .ftrow").length===7&&/未填 7 项/.test(document.querySelector("#fSum").textContent);
    c("#fImg");
    window.__ftGuard=!/未填/.test(document.querySelector("#toast").textContent);
    window.__snap={groups:document.querySelectorAll("#gOut .gcard").length,
      drawN:(document.querySelector("#aOut .rnum")?document.querySelector("#aOut .rnum").textContent.trim().split(/\\s+/).length:0),
      hwItems:document.querySelectorAll("#hList .item").length,
      ntItems:document.querySelectorAll("#nList .item").length,
      ttCourses:document.querySelectorAll("#tList .item").length};
  }catch(e){log.push("THROW:"+e.message);}
  setTimeout(function(){
    var d=document.createElement("div");d.id="TEST";
    /* 下面 6 项读的是退出登录前的快照（见 __snap 注释），其余为实时读数 */
    var S=window.__snap||{};
    function sv(k){return S[k]==null?"NA":S[k];}
    d.textContent="LOG="+log.join(",")+" | ERR="+(window.__err||"(none)")+" | downloads="+window.__dl
      +" | groups="+sv("groups")
      +" | drawN="+sv("drawN")
      +" | descOK="+(window.__descOK?1:0)+" | ascOK="+(window.__ascOK?1:0)+" | mapOK="+(window.__mapOK?1:0)
      +" | entOK="+(window.__entOK?1:0)+" | preOK="+(window.__preOK?1:0)
      +" | grpOK="+(window.__grpOK?1:0)+" | sumOK="+(window.__sumOK?1:0)+" | detOK="+(window.__detOK?1:0)
      +" | clrOK="+(window.__clrOK?1:0)+" | doneOK="+(window.__doneOK?1:0)+" | pinOK="+(window.__pinOK?1:0)
      +" | rmOK="+(window.__rmOK?1:0)
      +" | ftOK="+(window.__ftOK?1:0)+" | ftRows="+window.__ftRows+" | ftClrOK="+(window.__ftClrOK?1:0)
      +" | ftGuard="+(window.__ftGuard?1:0)+" | prtOK="+(window.__prtOK?1:0)+" | ftSub="+window.__ftSub
      +" | ftLblM="+window.__ftLblM+" | ftLblF="+window.__ftLblF+" | ftDurF="+window.__ftDurF+" | ftSc="+window.__ftSc
      +" | hwItems="+sv("hwItems")
      +" | ntItems="+sv("ntItems")
      +" | ttCourses="+sv("ttCourses")
      +" | navCount="+document.querySelectorAll("nav").length;
    document.body.appendChild(d);
    try{fetch("/_report",{method:"POST",body:d.textContent});}catch(e){}
  },800);
},200);});</script>\n</body>""")
tmpname = "_selfcheck_preview.html"
open(os.path.join(ROOT, tmpname), "w", encoding="utf-8").write(html)

PORT = 8902
REPORT = os.path.join(ROOT, "_report_%d.txt" % PORT)


class _H(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        open(REPORT, "wb").write(self.rfile.read(n))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


Handler = functools.partial(_H, directory=ROOT)


class Q(socketserver.TCPServer):
    allow_reuse_address = True


httpd = Q(("127.0.0.1", PORT), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.5)
if os.path.exists(REPORT):
    os.remove(REPORT)
try:
    r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                        "--virtual-time-budget=3000",
                        "http://127.0.0.1:%d/%s#edit" % (PORT, tmpname)], capture_output=True, timeout=90)
    out = "NOT FOUND"
    for _ in range(40):
        if os.path.exists(REPORT):
            time.sleep(0.3)
            out = open(REPORT, encoding="utf-8", errors="replace").read()
            break
        time.sleep(0.5)
    print("RESULT:", out)
    ok = ("ERR=(none)" in out and "THROW" not in out and "MISS" not in out
          and "groups=4" in out and "hwItems=1" in out and "ntItems=1" in out
          and "ttCourses=1" in out and "navCount=0" in out
          and "descOK=1" in out and "ascOK=1" in out and "mapOK=1" in out
          and "entOK=1" in out and "preOK=1" in out
          and "grpOK=1" in out and "sumOK=1" in out and "detOK=1" in out
          and "clrOK=1" in out and "doneOK=1" in out and "pinOK=1" in out
          and "rmOK=1" in out
          and "ftOK=1" in out and "ftRows=7" in out and "ftClrOK=1" in out and "ftGuard=1" in out and "prtOK=1" in out
          and "ftSub=标准分 83.0  ·  附加分 0.0" in out
          and "ftLblM=引体向上（次）" in out and "ftLblF=1 分钟仰卧起坐（次）" in out
          and "ftDurF=800 米跑（分 : 秒）" in out and "ftSc=100" in out)
    print("PASS" if ok else "FAIL")
finally:
    httpd.shutdown()
    os.remove(os.path.join(ROOT, tmpname))
