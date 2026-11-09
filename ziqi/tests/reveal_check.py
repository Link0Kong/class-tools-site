# -*- coding: utf-8 -*-
import os, re, subprocess, threading, http.server, socketserver, functools, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE):
    EDGE = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
PORT = 8967
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
class Q(socketserver.TCPServer): allow_reuse_address = True
httpd = Q(("127.0.0.1", PORT), Handler)
httpd.RequestHandlerClass.log_message = lambda *a, **k: None
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

# 不注入任何样式：直接看页面自身的淡入逻辑有没有跑起来
JS = """
var f=document.getElementById('f');
f.addEventListener('load', function(){
  var w=f.contentWindow, d=f.contentDocument;
  setTimeout(function(){
    var els=[].slice.call(d.querySelectorAll('.rv'));
    var withIn=els.filter(function(e){return e.classList.contains('rv-in');}).length;
    var opac=els.map(function(e){return w.getComputedStyle(e).opacity;});
    var zeros=opac.filter(function(o){return o==='0';}).length;
    var intro=d.getElementById('intro');
    document.getElementById('hud').textContent='@@'+JSON.stringify({
      rvTotal:els.length, rvIn:withIn, opacityZero:zeros,
      sampleOpacity:opac.slice(0,6), introDisplay:intro?w.getComputedStyle(intro).display:'-'})+ '@@';
  }, 3000);
});
"""
page = "_reveal.html"
open(os.path.join(ROOT, page), "w", encoding="utf-8").write("""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}iframe{border:0;display:block}#hud{padding:6px;font:12px monospace}</style></head><body>
<iframe id="f" src="../index.html" style="width:390px;height:844px"></iframe>
<div id="hud"></div><script>%s</script></body></html>""" % JS)
r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=420,1100",
                    "--virtual-time-budget=6000", "--dump-dom",
                    "http://127.0.0.1:%d/%s" % (PORT, page)], capture_output=True, timeout=120)
dom = r.stdout.decode("utf-8", "replace")
m = re.search(r"@@(.*?)@@", dom, re.S)
print(m.group(1) if m else "NO DATA")
httpd.shutdown()
p = os.path.join(ROOT, page)
if os.path.exists(p):
    os.remove(p)
