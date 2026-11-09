# -*- coding: utf-8 -*-
"""滚动特效回归（用 rAF->setTimeout 垫片，绕开 headless 虚拟时间不推 rAF 的问题）。
检查：进度条 / 顶栏 stuck / 回到顶部 / 提示淡出 / 目录高亮 / 区块 seen·act / 视差。
"""
import os, re, subprocess, threading, http.server, socketserver, functools, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE):
    EDGE = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
PORT = 8983
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
class Q(socketserver.TCPServer): allow_reuse_address = True
httpd = Q(("127.0.0.1", PORT), Handler)
httpd.RequestHandlerClass.log_message = lambda *a, **k: None
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

# 造一个测试副本：把 rAF 换成 setTimeout（仅测试用，线上文件不动）
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
patched = src.replace("window.requestAnimationFrame(frame)", "setTimeout(frame,16)")
assert patched != src, "rAF shim 未命中"
open(os.path.join(ROOT, "_fxtest.html"), "w", encoding="utf-8").write(patched)

JS = """
var f=document.getElementById('f');
f.addEventListener('load', function(){
  var w=f.contentWindow, d=f.contentDocument;
  var out=[];
  function snap(tag, cb){
    setTimeout(function(){
      var prog=d.getElementById('prog'), tbar=d.querySelector('.tbar'), totop=d.getElementById('totop');
      var cue=d.querySelector('.scrollcue'), scene=d.querySelector('.hero .scene');
      out.push(tag+' y='+Math.round(w.pageYOffset||0)+
        ' prog='+(prog?prog.style.width:'-')+
        ' stuck='+(tbar&&tbar.classList.contains('stuck'))+
        ' totop='+(totop&&totop.classList.contains('on'))+
        ' cueGone='+(cue&&cue.classList.contains('gone'))+
        ' navOn='+[].filter.call(d.querySelectorAll('.tnav a'),function(a){return a.classList.contains('on');}).map(function(a){return a.getAttribute('href');}).join(',')+
        ' act='+[].filter.call(d.querySelectorAll('.sec'),function(s){return s.classList.contains('act');}).map(function(s){return s.id;}).join(',')+
        ' seen='+d.querySelectorAll('.sec.seen').length+
        ' sceneTf='+(scene?(scene.style.transform||'(none)'):'-'));
      if(cb) cb();
    }, 200);
  }
  setTimeout(function(){
    d.documentElement.style.scrollBehavior='auto';   /* smooth 在虚拟时间下不会推进 */
    var a=setInterval(function(){
      d.documentElement.style.scrollBehavior='auto';
      if(d.querySelector('.sec') && d.querySelector('.tnav a')) clearInterval(a);
    },50);
    snap('top', function(){
      w.scrollTo(0, 420); w.dispatchEvent(new w.Event('scroll'));
      snap('@420', function(){
        w.scrollTo(0, 3600); w.dispatchEvent(new w.Event('scroll'));
        snap('@3600', function(){
          w.scrollTo(0, 1e6); w.dispatchEvent(new w.Event('scroll'));
          snap('bottom', function(){ document.getElementById('hud').textContent='@@'+out.join('\\n')+'@@'; });
        });
      });
    });
  }, 900);
});
"""
page = "_fxrun.html"
open(os.path.join(ROOT, page), "w", encoding="utf-8").write("""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}iframe{border:0;display:block}#hud{padding:6px;font:11px monospace;white-space:pre-wrap}</style></head><body>
<iframe id="f" src="_fxtest.html" style="width:1280px;height:800px"></iframe>
<div id="hud"></div><script>%s</script></body></html>""" % JS)
r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=1320,1000",
                    "--virtual-time-budget=12000", "--dump-dom",
                    "http://127.0.0.1:%d/%s" % (PORT, page)], capture_output=True, timeout=120)
dom = r.stdout.decode("utf-8", "replace")
m = re.search(r"@@(.*?)@@", dom, re.S)
print((m.group(1) if m else "NO DATA").replace("&gt;", ">").replace("&amp;", "&"))
httpd.shutdown()
for p in (page, "_fxtest.html"):
    q = os.path.join(ROOT, p)
    if os.path.exists(q):
        os.remove(q)
