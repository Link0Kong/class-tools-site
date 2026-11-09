# -*- coding: utf-8 -*-
"""开屏遮罩回归测试：模拟"同一会话第二次打开"（旧的锁滚动 bug 就发生在这一支）。
判据：intro display=none、html/body 的 overflow-y 不是 hidden、页面确实能滚。
用法: python tests\\scrolltest.py
"""
import os, sys, subprocess, threading, http.server, socketserver, functools, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(OUT, exist_ok=True)

EDGE = None
for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
          r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
    if os.path.exists(p):
        EDGE = p; break
if not EDGE:
    sys.exit("no edge")

W, H = 390, 844
PAGE = "_scrolltest_%s.html" % time.strftime("%H%M%S")

JS = """
var f=document.getElementById('f'), stage=0;
f.addEventListener('load', function(){
  var w=f.contentWindow, d=f.contentDocument;
  if(stage===0){                       /* 第一次：写上 sessionStorage 后刷新 -> 复现第二次打开 */
    stage=1;
    try{ w.sessionStorage.setItem('zq_intro','1'); }catch(e){}
    setTimeout(function(){ f.contentWindow.location.reload(); }, 250);
    return;
  }
  setTimeout(function(){                /* 第二次：断言 */
    var intro=d.getElementById('intro');
    var iD = intro ? getComputedStyle(intro).display : '(missing)';
    var oyH = getComputedStyle(d.documentElement).overflowY;
    var oyB = getComputedStyle(d.body).overflowY;
    d.documentElement.style.scrollBehavior='auto';   /* smooth 会测不出即时 scrollY */
    var canScroll = d.documentElement.scrollHeight > d.documentElement.clientHeight + 50;
    w.scrollTo(0, 700);
    var sy = w.scrollY || d.documentElement.scrollTop || d.body.scrollTop || 0;
    var ok = (iD==='none') && oyH!=='hidden' && oyB!=='hidden' && canScroll && sy>50;
    document.getElementById('hud').textContent =
      (ok?'PASS':'FAIL') + '\\n' +
      'intro.display=' + iD + '\\n' +
      'html.overflowY=' + oyH + '   body.overflowY=' + oyB + '\\n' +
      'scrollHeight=' + d.documentElement.scrollHeight + '  clientHeight=' + d.documentElement.clientHeight + '\\n' +
      'after scrollTo(0,700) scrollY=' + sy;
  }, 1500);
});
"""

body = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:#DDE3E1;font:12px monospace}
iframe{border:0;display:block;background:#fff}
#hud{padding:6px 8px;background:#23302E;color:#7BD0B0;font:12px monospace;white-space:pre-wrap}</style></head><body>
<iframe id="f" src="../index.html" style="width:%dpx;height:%dpx"></iframe>
<div id="hud">running...</div>
<script>%s</script></body></html>""" % (W, H, JS)
open(os.path.join(ROOT, PAGE), "w", encoding="utf-8").write(body)

PORT = 8923
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
class Q(socketserver.TCPServer): allow_reuse_address = True
httpd = Q(("127.0.0.1", PORT), Handler)
httpd.RequestHandlerClass.log_message = lambda *a, **k: None
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.5)
out = os.path.join(OUT, "scrolltest.png")
try:
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=%d,%d" % (W, H + 160),
                    "--screenshot=" + out, "--virtual-time-budget=7000",
                    "http://127.0.0.1:%d/%s" % (PORT, PAGE)],
                   capture_output=True, timeout=120)
    print("shot ->", out, os.path.getsize(out) if os.path.exists(out) else "FAIL")
finally:
    httpd.shutdown()
    p = os.path.join(ROOT, PAGE)
    if os.path.exists(p):
        os.remove(p)
