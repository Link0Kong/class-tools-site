# -*- coding: utf-8 -*-
"""在"整页可见"的高视口下检查：7 个区块是否都被标记 seen；游戏折叠卡是否存在且可展开。"""
import os, re, subprocess, threading, http.server, socketserver, functools, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE):
    EDGE = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
PORT = 8991
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
    var det=d.querySelector('.gcard');
    var before = det ? det.open : null;
    if(det) det.open = true;
    setTimeout(function(){
      var out={
        sections: d.querySelectorAll('.sec').length,
        seen: d.querySelectorAll('.sec.seen').length,
        seenIds: [].map.call(d.querySelectorAll('.sec.seen'), function(s){return s.id;}),
        gcardExists: !!det,
        gcardOpenBefore: before,
        gcardOpenAfter: det ? det.open : null,
        rows: d.querySelectorAll('.glist .grow').length,
        rowText: [].map.call(d.querySelectorAll('.glist .grow'), function(r){return r.textContent.trim();}),
        emailLinks: [].map.call(d.querySelectorAll('a[href^="mailto:"]'), function(a){return a.getAttribute('href');}),
        emailText: (function(){var e=d.querySelector('.lk.b .tx span'); return e?e.textContent:'-';})()
      };
      document.getElementById('hud').textContent='@@'+JSON.stringify(out)+'@@';
    }, 400);
  }, 1200);
});
"""
page = "_seen.html"
open(os.path.join(ROOT, page), "w", encoding="utf-8").write("""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}iframe{border:0;display:block}#hud{padding:6px;font:11px monospace;white-space:pre-wrap}</style></head><body>
<iframe id="f" src="../index.html" style="width:390px;height:6400px"></iframe>
<div id="hud"></div><script>%s</script></body></html>""" % JS)
r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=430,7000",
                    "--virtual-time-budget=9000", "--dump-dom",
                    "http://127.0.0.1:%d/%s" % (PORT, page)], capture_output=True, timeout=120)
dom = r.stdout.decode("utf-8", "replace")
m = re.search(r"@@(.*?)@@", dom, re.S)
print(m.group(1) if m else "NO DATA")
httpd.shutdown()
p = os.path.join(ROOT, page)
if os.path.exists(p):
    os.remove(p)
