# -*- coding: utf-8 -*-
import os, re, subprocess, threading, http.server, socketserver, functools, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE):
    EDGE = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
PORT = 8971
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
    var el=d.querySelector('.hero .tag');
    var rules=[];
    [].forEach.call(d.styleSheets, function(ss){
      try{ [].forEach.call(ss.cssRules, function(r){ if(r.cssText && /rv-in|rv-all/.test(r.cssText)) rules.push(r.cssText); }); }catch(e){}
    });
    // 关掉过渡后再看最终态（排除"过渡不推进"的干扰）
    var st=d.createElement('style'); st.textContent='.rv{transition:none!important}'; d.head.appendChild(st);
    setTimeout(function(){
      var ops=[].slice.call(d.querySelectorAll('.rv')).map(function(e){return w.getComputedStyle(e).opacity;});
      document.getElementById('hud').textContent='@@'+JSON.stringify({
        htmlClass:d.documentElement.className,
        matches_js_rv_rvin: el.matches('html.js .rv.rv-in'),
        hasRvinClass: el.classList.contains('rv-in'),
        rulesFound: rules,
        opacityAfterNoTransition: Array.from(new Set(ops)),
        zeros: ops.filter(function(o){return o==='0';}).length,
        total: ops.length
      })+'@@';
    }, 300);
  }, 2800);
});
"""
page = "_reveal2.html"
open(os.path.join(ROOT, page), "w", encoding="utf-8").write("""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}iframe{border:0;display:block}#hud{padding:6px;font:11px monospace;white-space:pre-wrap}</style></head><body>
<iframe id="f" src="../index.html" style="width:390px;height:844px"></iframe>
<div id="hud"></div><script>%s</script></body></html>""" % JS)
r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=430,1100",
                    "--virtual-time-budget=8000", "--dump-dom",
                    "http://127.0.0.1:%d/%s" % (PORT, page)], capture_output=True, timeout=120)
dom = r.stdout.decode("utf-8", "replace")
m = re.search(r"@@(.*?)@@", dom, re.S)
print(m.group(1) if m else "NO DATA")
httpd.shutdown()
p = os.path.join(ROOT, page)
if os.path.exists(p):
    os.remove(p)
