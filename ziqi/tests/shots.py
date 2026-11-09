# -*- coding: utf-8 -*-
"""个人主页自检：多分辨率 / 多比例截图 + 横向溢出审计。
用法: python tests\\shots.py
"""
import os, sys, subprocess, threading, http.server, socketserver, functools, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # web/ziqi
OUT  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(OUT, exist_ok=True)

EDGE = None
for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
          r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
    if os.path.exists(p):
        EDGE = p; break
if not EDGE:
    sys.exit("找不到 Edge")

RUNID = time.strftime("%H%M%S")

def wrap(name, w, h):
    body = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#DDE3E1;font:12px monospace}
iframe{border:0;display:block;background:#fff}
#hud{padding:4px 8px;background:#23302E;color:#fff;font:11.5px monospace;white-space:pre-wrap}</style></head><body>
<iframe id="f" src="../index.html" style="width:%dpx;height:%dpx"></iframe>
<div id="hud">measuring...</div>
<script>
document.getElementById("f").addEventListener("load",function(){
  var w=this.contentWindow,d=this.contentDocument;
  setTimeout(function(){
    /* 截图确定性：关掉装饰性淡入（否则虚拟时间下会拍到半透明帧） */
    var st=d.createElement('style');
    st.textContent='html.js .rv{opacity:1!important;transform:none!important;transition:none!important}';
    d.head.appendChild(st);
    var de=d.documentElement,bad=[];
    d.querySelectorAll("*").forEach(function(e){
      var r=e.getBoundingClientRect();
      if(r.width>0 && r.right>de.clientWidth+1 && !e.closest("table") && getComputedStyle(e).position!=="fixed")
        bad.push(e.tagName+"."+String(e.className).split(" ")[0]);
    });
    document.getElementById("hud").textContent="viewport="+de.clientWidth+"  scrollW="+de.scrollWidth+"  overflow="+bad.length+(bad.length?"  ["+bad.slice(0,10).join(", ")+"]":"");
  },900);
});
</script></body></html>""" % (w, h)
    p = os.path.join(ROOT, "_frame_%s_%s.html" % (name, RUNID))
    open(p, "w", encoding="utf-8").write(body)
    return os.path.basename(p)

PORT = 8917
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
class Q(socketserver.TCPServer): allow_reuse_address = True
httpd = Q(("127.0.0.1", PORT), Handler)
httpd.RequestHandlerClass.log_message = lambda *a, **k: None
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.5)

# name, w, h, virtual-time-budget(ms)
shots = [
    ("intro_phone",    390,  844, 1250),
    ("intro_desktop",  1280, 800, 1250),
    ("phone_390",      390,  844, 3200),
    ("narrow_320",     320,  900, 3200),
    ("phone_430",      430,  932, 3200),
    ("tablet_768",     768, 1024, 3200),
    ("laptop_1280",   1280,  800, 8000),
    ("desktop_1920",  1920, 1080, 3200),
    ("ultrawide_2560",2560, 1080, 3200),
    ("land_800x400",   800,  400, 8000),
    ("full_390",       390, 6300, 3200),
    ("full_430",       430, 6300, 3200),
    ("full_1280",     1280, 4600, 3200),
]
try:
    for name, w, h, vt in shots:
        page = wrap(name, w, h)
        out = os.path.join(OUT, name + ".png")
        r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=1", "--window-size=%d,%d" % (w, h + 130),
                            "--screenshot=" + out, "--virtual-time-budget=%d" % vt,
                            "http://127.0.0.1:%d/%s" % (PORT, page)],
                           capture_output=True, timeout=120)
        print("%-16s -> %s" % (name, os.path.getsize(out) if os.path.exists(out) else "FAIL"))
finally:
    httpd.shutdown()
    for f in os.listdir(ROOT):
        if f.startswith("_frame_") and f.endswith(".html"):
            os.remove(os.path.join(ROOT, f))
print("shots ->", OUT)
