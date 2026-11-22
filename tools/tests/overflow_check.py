# -*- coding: utf-8 -*-
"""自检 D：横向溢出审计 —— 报告页面是否横向溢出，并列出超出视口的元素。
用法：python tests\\overflow_check.py [宽,默认 430]
"""
import os, json, subprocess, threading, http.server, socketserver, functools, time, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "index.html")
W = int(sys.argv[1]) if len(sys.argv) > 1 else 430
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

SEED = {"course": [{"name": "高等数学", "teacher": "王老师", "room": "A301", "day": 0, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"}],
        "homework": [{"subject": "英语", "content": "Unit 3", "due": "10-12", "date": "2026-10-12", "done": False}],
        "notices": [{"title": "班会通知", "body": "周五 19:00", "pin": True, "imp": True, "ts": 1759900000000}],
        "draw": {"start": 1, "end": 50, "count": 10, "dup": False, "excl": "", "sort": "desc"},
        "group": {"source": "prev", "names": "", "mode": "groups", "n": 4, "shuffle": False}}

html = open(SRC, encoding="utf-8").read()
html = html.replace('<div id="toast"></div>',
    '<div id="toast"></div>\n<script>var _f=window.fetch;window.fetch=function(u,o){if(String(u).indexOf("tcloudbasegateway")>=0||String(u).indexOf("tt.json")>=0)return Promise.reject(new Error("test-block"));return _f.apply(this,arguments);};try{localStorage.setItem("zq_tools_v2",JSON.stringify(%s));}catch(e){}</script>'
    % json.dumps(SEED, ensure_ascii=False))
html = html.replace("</body>", """<script>window.addEventListener("load",function(){setTimeout(function(){
  var log=[];
  function c(s){var e=document.querySelector(s);if(e)e.click();}
  function ot(k){if(k==="tt"||k==="ft"||k==="group"){c("[data-tab='all']");c("[data-open='"+k+"']");if(k==="tt")c("[data-ttview='week']");}else{c("[data-tab='"+k+"']");}}
  c("#aRun");c("#gSrcSeg [data-gsrc='prev']");c("#gRun");
  setTimeout(function(){
    ot("tt");
    setTimeout(function(){
      var hintNow=getComputedStyle(document.querySelector("#tHint")).display!=="none"?1:0;
      var tsw=document.querySelector("#tGrid").scrollWidth+"/"+document.querySelector("#tGrid").clientWidth;
      /* 体测页先填一组成绩，保证在「有数据」状态下参与审计 */
      ot("ft");
      var ftv={fH:"175",fW:"65",fVc:"4300",fR50:"7.1",fSit:"17.7",fJump:"248",fPull:"15",fDurM:"3",fDurS:"42"};
      for(var fk in ftv){var fe=document.querySelector("#"+fk);fe.value=ftv[fk];fe.dispatchEvent(new Event("input",{bubbles:true}));}
      var de=document.documentElement, total=0, per=[], all=[];
      ["draw","group","tt","hw","nt","ft"].forEach(function(t){
        ot(t);
        var bad=[];
        document.querySelectorAll("*").forEach(function(e){
          var r=e.getBoundingClientRect();
          if(r.width>0 && r.right>window.innerWidth+1 && !e.closest("table.tt")) bad.push(e.tagName+"."+(e.className||"")+"["+Math.round(r.left)+"→"+Math.round(r.right)+"]");
        });
        total+=bad.length; per.push(t+"="+bad.length);
        all=all.concat(bad.map(function(x){return t+":"+x;}));
      });
      c("[data-tab='draw']");
      var d=document.createElement("div");d.id="OVF";
      d.textContent="innerW="+window.innerWidth+" scrollW="+de.scrollWidth+" bodyScrollW="+document.body.scrollWidth
        +" | overflowCount="+total+" | per="+per.join(",")
        +" | hint="+hintNow+" | tscrollSW="+tsw
        +" | "+all.slice(0,12).join(" ;; ");
      document.body.appendChild(d);
      try{fetch("/_report",{method:"POST",body:d.textContent});}catch(e){}
    },80);
  },300);
},250);});</script>\n</body>""")
tmp = "_ovf_preview.html"
open(os.path.join(ROOT, tmp), "w", encoding="utf-8").write(html)

PORT = 8905
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
    r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--force-device-scale-factor=1",
                        "--window-size=%d,1400" % W, "--virtual-time-budget=3000",
                        "http://127.0.0.1:%d/%s#edit" % (PORT, tmp)], capture_output=True, timeout=90)
    out = "NOT FOUND"
    for _ in range(40):
        if os.path.exists(REPORT):
            time.sleep(0.3)
            out = open(REPORT, encoding="utf-8", errors="replace").read()
            break
        time.sleep(0.5)
    print("宽度", W, "->", out)
finally:
    httpd.shutdown()
    os.remove(os.path.join(ROOT, tmp))
