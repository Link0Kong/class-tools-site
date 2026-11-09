# -*- coding: utf-8 -*-
"""诊断：找出指定宽度下真正横向溢出的元素（排除 SVG 内部与 fixed 层）。
用法: python tests\\overflow_diag.py 320
"""
import os, sys, subprocess, threading, http.server, socketserver, functools, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(OUT, exist_ok=True)
W = int(sys.argv[1]) if len(sys.argv) > 1 else 320
H = 900

EDGE = None
for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
          r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
    if os.path.exists(p):
        EDGE = p; break
if not EDGE:
    sys.exit("no edge")

PAGE = "_diag_%s.html" % time.strftime("%H%M%S")
JS = """
var f=document.getElementById('f');
f.addEventListener('load', function(){
  var w=f.contentWindow, d=f.contentDocument;
  setTimeout(function(){
    var st=d.createElement('style');
    st.textContent='html.js .rv{opacity:1!important;transform:none!important;transition:none!important}#intro{display:none!important}';
    d.head.appendChild(st);
    setTimeout(function(){
      var vw=d.documentElement.clientWidth, rows=[];
      d.querySelectorAll('body *').forEach(function(e){
        if(e.closest('svg')) return;                     // SVG 内部坐标系不算
        var cs=getComputedStyle(e);
        if(cs.position==='fixed') return;
        var r=e.getBoundingClientRect();
        if(r.width<1) return;
        var over=Math.round(r.right-vw);
        if(over>1) rows.push(over+'px  <'+e.tagName.toLowerCase()+' class="'+String(e.className)+'">  w='+Math.round(r.width)+' L='+Math.round(r.left)+' R='+Math.round(r.right));
      });
      rows.sort(function(a,b){return parseInt(b)-parseInt(a);});
      document.getElementById('hud').textContent =
        'viewport='+vw+'  scrollWidth='+d.documentElement.scrollWidth+'  offenders='+rows.length+'\\n\\n'+rows.slice(0,14).join('\\n');
    }, 700);
  }, 400);
});
"""
body = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:#DDE3E1;font:12px monospace}
iframe{border:0;display:block;background:#fff}
#hud{padding:8px;background:#101A18;color:#7BD0B0;font:11.5px monospace;white-space:pre-wrap;min-height:400px}</style></head><body>
<iframe id="f" src="../index.html" style="width:%dpx;height:%dpx"></iframe>
<div id="hud">running</div>
<script>%s</script></body></html>""" % (W, H, JS)
open(os.path.join(ROOT, PAGE), "w", encoding="utf-8").write(body)

PORT = 8931
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
class Q(socketserver.TCPServer): allow_reuse_address = True
httpd = Q(("127.0.0.1", PORT), Handler)
httpd.RequestHandlerClass.log_message = lambda *a, **k: None
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.5)
out = os.path.join(OUT, "diag_%d.png" % W)
try:
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=%d,%d" % (W, H + 460),
                    "--screenshot=" + out, "--virtual-time-budget=4000",
                    "http://127.0.0.1:%d/%s" % (PORT, PAGE)],
                   capture_output=True, timeout=120)
    print("shot ->", out)
finally:
    httpd.shutdown()
    p = os.path.join(ROOT, PAGE)
    if os.path.exists(p):
        os.remove(p)
