# -*- coding: utf-8 -*-
import os, re, subprocess, threading, http.server, socketserver, functools, time, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE):
    EDGE = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
PORT = 8953
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
class Q(socketserver.TCPServer): allow_reuse_address = True
httpd = Q(("127.0.0.1", PORT), Handler)
httpd.RequestHandlerClass.log_message = lambda *a, **k: None
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

JS = """
var f=document.getElementById('f');
f.addEventListener('load', function(){
  var w=f.contentWindow, d=f.contentDocument;
  setTimeout(function(){
    var st=d.createElement('style');
    st.textContent='html.js .rv{opacity:1!important;transform:none!important;transition:none!important}#intro{display:none!important}';
    d.head.appendChild(st);
    setTimeout(function(){
      function info(sel){var e=d.querySelector(sel); if(!e) return sel+': (none)';
        var cs=getComputedStyle(e); var r=e.getBoundingClientRect();
        return sel+' {fs:'+cs.fontSize+' lh:'+cs.lineHeight+' mt:'+cs.marginTop+' mb:'+cs.marginBottom+
               ' pt:'+cs.paddingTop+' pb:'+cs.paddingBottom+' h:'+Math.round(r.height)+' rects:'+e.getClientRects().length+'}';}
      var lines=[info('h1'),info('.hero .tag'),info('.chips'),info('.chip'),info('.eyebrow'),
                 info('.idcard'),info('.scrollcue'),info('.hero .in'),info('.hero')];
      document.getElementById('hud').textContent='@@'+lines.join('\\n')+'@@';
    }, 700);
  }, 400);
});
"""
page = "_probe.html"
open(os.path.join(ROOT, page), "w", encoding="utf-8").write("""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}iframe{border:0;display:block}#hud{padding:6px;white-space:pre}</style></head><body>
<iframe id="f" src="../index.html" style="width:390px;height:844px"></iframe>
<div id="hud"></div><script>%s</script></body></html>""" % JS)
r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=390,1104",
                    "--virtual-time-budget=4000", "--dump-dom",
                    "http://127.0.0.1:%d/%s" % (PORT, page)], capture_output=True, timeout=120)
dom = r.stdout.decode("utf-8", "replace")
m = re.search(r"@@(.*?)@@", dom, re.S)
print(m.group(1) if m else dom[-1500:])
httpd.shutdown()
p = os.path.join(ROOT, page)
if os.path.exists(p):
    os.remove(p)
