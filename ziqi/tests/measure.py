# -*- coding: utf-8 -*-
"""测量首屏关键元素位置（用 --dump-dom 直接读数值，不靠肉眼）。
用法: python tests\\measure.py [w h ...]
"""
import os, sys, re, subprocess, threading, http.server, socketserver, functools, time, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = None
for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
          r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
    if os.path.exists(p):
        EDGE = p; break
if not EDGE:
    sys.exit("no edge")

PORT = 8947
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
class Q(socketserver.TCPServer): allow_reuse_address = True
httpd = Q(("127.0.0.1", PORT), Handler)
httpd.RequestHandlerClass.log_message = lambda *a, **k: None
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.5)

JS = """
var f=document.getElementById('f');
f.addEventListener('load', function(){
  var w=f.contentWindow, d=f.contentDocument;
  setTimeout(function(){
    var st=d.createElement('style');
    st.textContent='html.js .rv{opacity:1!important;transform:none!important;transition:none!important}#intro{display:none!important}';
    d.head.appendChild(st);
    setTimeout(function(){
      function box(sel){var e=d.querySelector(sel); if(!e) return null; var r=e.getBoundingClientRect();
        return [Math.round(r.top), Math.round(r.bottom), Math.round(r.height)];}
      var out={vw:d.documentElement.clientWidth, vh:w.innerHeight,
               h1:box('h1'), tag:box('.hero .tag'), chips:box('.chips'),
               card:box('.idcard'), cue:box('.scrollcue'),
               heroBottom:Math.round(d.querySelector('.hero').getBoundingClientRect().bottom)};
      document.getElementById('hud').textContent='@@'+JSON.stringify(out)+'@@';
    }, 700);
  }, 400);
});
"""

def run(w, h):
    page = "_measure2_%d_%d.html" % (w, h)
    body = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}iframe{border:0;display:block}#hud{padding:6px}</style></head><body>
<iframe id="f" src="../index.html" style="width:%dpx;height:%dpx"></iframe>
<div id="hud"></div><script>%s</script></body></html>""" % (w, h, JS)
    open(os.path.join(ROOT, page), "w", encoding="utf-8").write(body)
    try:
        r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=1", "--window-size=%d,%d" % (w, h + 260),
                            "--virtual-time-budget=4000", "--dump-dom",
                            "http://127.0.0.1:%d/%s" % (PORT, page)],
                           capture_output=True, timeout=120)
        dom = r.stdout.decode("utf-8", "replace")
        m = re.search(r"@@(\{.*?\})@@", dom, re.S)
        return json.loads(m.group(1)) if m else None
    finally:
        p = os.path.join(ROOT, page)
        if os.path.exists(p):
            os.remove(p)

sizes = [(int(sys.argv[1]), int(sys.argv[2]))] if len(sys.argv) > 2 else [
    (320, 480), (360, 560), (375, 553), (390, 700), (390, 750), (412, 780)]
print("%-11s %-6s %-22s %-22s %-22s %-22s" % ("size", "vh", "h1[t,b,h]", "chips[t,b,h]", "card[t,b,h]", "cue[t,b,h]"))
for w, h in sizes:
    d = run(w, h)
    if not d:
        print("%-11s read-failed" % ("%dx%d" % (w, h))); continue
    def f(k):
        v = d.get(k)
        return "-" if v is None else "%d/%d/%d" % tuple(v)
    print("%-11s %-6s %-22s %-22s %-22s %-22s  heroBottom=%s" % (
        "%dx%d" % (w, h), d["vh"], f("h1"), f("chips"), f("card"), f("cue"), d["heroBottom"]))
httpd.shutdown()
