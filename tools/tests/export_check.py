# -*- coding: utf-8 -*-
"""自检 C：导出图片检查 —— 拦截 canvas 产出的 Blob，落盘成 PNG 供肉眼/视觉模型核查。
用法：python tests\\export_check.py
"""
import os, json, subprocess, threading, http.server, socketserver, functools, time, re, base64, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get("EXPORT_SRC") or os.path.join(ROOT, "index.html")
OUT = os.environ.get("EXPORT_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(OUT, exist_ok=True)
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

WHICH = sys.argv[1] if len(sys.argv) > 1 else "draw"   # draw | group | flow | tt | hw | ft
WITH_ROSTER = len(sys.argv) > 2 and sys.argv[2] == "roster"   # 可选：种子带 50 人名单，验证带名字的导出层级

html = open(SRC, encoding="utf-8").read()
html = html.replace("<head>",
    '<head><script>window.__err="";window.addEventListener("error",function(e){window.__err+="["+e.message+"]";});'
    'var _f=window.fetch;window.fetch=function(u,o){if(String(u).indexOf("tcloudbasegateway")>=0||String(u).indexOf("tt.json")>=0)return Promise.reject(new Error("test-block"));return _f.apply(this,arguments);};'
    'try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"test-export",sid:"9999000005",name:"测试同学",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}'
    'window.__blobs=[];var _c=URL.createObjectURL;URL.createObjectURL=function(b){window.__blobs.push(b);return _c.call(URL,b);};'
    'HTMLCanvasElement.prototype.toBlob=function(cb,t){var d=this.toDataURL(t||"image/png");var s=atob(d.split(",")[1]);var a=new Uint8Array(s.length);for(var i=0;i<s.length;i++)a[i]=s.charCodeAt(i);cb(new Blob([a],{type:t||"image/png"}));};'
    'window.__name="";var _a=HTMLAnchorElement.prototype.click;'
    'HTMLAnchorElement.prototype.click=function(){if(this.download){window.__name=this.download;return;}return _a.apply(this,arguments);};</script>')
html = html.replace('<div id="toast"></div>',
    '<div id="toast"></div>\n<script>try{localStorage.setItem("zq_session",JSON.stringify({acc:"t7",h:"x"}));}catch(e){}</script>')
if WITH_ROSTER:
    html = html.replace('<div id="toast"></div>',
        '<div id="toast"></div>\n<script>try{localStorage.setItem("zq_tools_v2",JSON.stringify(%s));localStorage.setItem("zq_session",JSON.stringify({acc:"t7",h:"x"}));}catch(e){}</script>'
        % json.dumps({"roster": "\n".join("同学%d" % (i + 1) for i in range(50))}, ensure_ascii=False))
if WHICH == "tt":
    # 课表已改为只读（不再有添加课程入口），导出测试直接种一门课
    html = html.replace('<div id="toast"></div>',
        '<div id="toast"></div>\n<script>try{localStorage.setItem("zq_tools_v2",JSON.stringify(%s));}catch(e){}</script>'
        % json.dumps({"course": [{"name": "高等数学", "teacher": "王老师", "room": "A301", "day": 0, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"}], "termStart": "2026-08-31"}, ensure_ascii=False))
html = html.replace("</body>", """<script>window.addEventListener("load",function(){setTimeout(function(){
  function c(s){var e=document.querySelector(s);if(e)e.click();}
  c("#aRun");
  if("%s"==="drawqr"){var rm=document.querySelector("[data-rm]");if(rm)rm.click();}
  if("%s"==="group"||"%s"==="flow"){c("#gSrcSeg [data-gsrc='prev']");c("#gRun");}
  var btn={draw:"#aImg",drawqr:"#aImg",group:"#gImg",flow:"#gImg",tt:"#tImg",hw:"#hImg",ft:"#fImg",nt:"#nImg"}["%s"];
  if("%s"==="tt"){c("[data-tab='all']");c("[data-open='tt']");}
  if("%s"==="ft"){c("[data-tab='all']");c("[data-open='ft']");var ftv={fH:"175",fW:"65",fVc:"4300",fR50:"7.1",fSit:"17.7",fJump:"248",fPull:"15",fDurM:"3",fDurS:"42"};for(var fk in ftv){var fe=document.querySelector("#"+fk);fe.value=ftv[fk];fe.dispatchEvent(new Event("input",{bubbles:true}));}}
  if("%s"==="hw"){document.querySelector("#hSubject").value="英语";document.querySelector("#hContent").value="Unit 3 课后练习";document.querySelector("#hDate").value="2099-01-01";c("#hAdd");}
  if("%s"==="nt"){c("[data-tab='nt']");document.querySelector("#nTitle").value="班会通知";document.querySelector("#nBody").value="周五 19:00 A301";c("#nAdd");}
  c(btn);
  setTimeout(function(){
    if(!window.__blobs.length){var d=document.createElement("div");d.id="OUT";d.textContent="NOBLOB err="+window.__err+" | gc="+document.querySelectorAll("#gOut .gcard").length+" | aOut="+(document.querySelector("#aOut .rnum")?"Y":"N")+" | toast="+document.querySelector("#toast").textContent+" | blobs="+window.__blobs.length;document.body.appendChild(d);try{fetch("/_report",{method:"POST",body:d.textContent});}catch(e){}return;}
    var r=new FileReader();
    r.onload=function(){var d=document.createElement("div");d.id="OUT";d.textContent="NAME="+window.__name+"\\n"+r.result;document.body.appendChild(d);try{fetch("/_report",{method:"POST",body:d.textContent});}catch(e){}};
    r.readAsDataURL(window.__blobs[0]);
  },700);
},200);});</script>""" % (WHICH, WHICH, WHICH, WHICH, WHICH, WHICH, WHICH, WHICH))
tmp = "_export_preview.html"
open(os.path.join(ROOT, tmp), "w", encoding="utf-8").write(html)

PORT = 8903
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
    r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                        "--virtual-time-budget=4000",
                        "http://127.0.0.1:%d/%s#edit" % (PORT, tmp)], capture_output=True, timeout=120)
    body = "NOT FOUND"
    for _ in range(60):
        if os.path.exists(REPORT):
            time.sleep(0.3)
            body = open(REPORT, encoding="utf-8", errors="replace").read()
            break
        time.sleep(0.5)
    if body == "NOT FOUND":
        print("OUT NOT FOUND"); sys.exit(1)
    nm = re.search(r'NAME=([^\\\n]*)', body)
    print("下载文件名:", nm.group(1) if nm else "?")
    dm = re.search(r'data:image/png;base64,([A-Za-z0-9+/=]+)', body)
    if not dm:
        print("无 PNG 数据:", body[:200]); sys.exit(1)
    data = base64.b64decode(dm.group(1))
    p = os.path.join(OUT, "export_%s.png" % WHICH)
    open(p, "wb").write(data)
    print("已保存", p, len(data), "bytes")
finally:
    httpd.shutdown()
    os.remove(os.path.join(ROOT, tmp))
