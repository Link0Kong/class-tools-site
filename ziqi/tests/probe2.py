# -*- coding: utf-8 -*-
import os, re, subprocess, threading, http.server, socketserver, functools, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE):
    EDGE = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
PORT = 8959
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
class Q(socketserver.TCPServer): allow_reuse_address = True
httpd = Q(("127.0.0.1", PORT), Handler)
httpd.RequestHandlerClass.log_message = lambda *a, **k: None
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

JS = """
var f=document.getElementById('f');
f.addEventListener('load', function(){
  var w=f.contentWindow, d=f.contentDocument, G=w.getComputedStyle;
  setTimeout(function(){
    var st=d.createElement('style');
    st.textContent='html.js .rv{opacity:1!important;transform:none!important;transition:none!important}#intro{display:none!important}';
    d.head.appendChild(st);
    setTimeout(function(){
      var out=[];
      function walk(sel, depth){
        var e=d.querySelector(sel); if(!e){out.push(sel+' (none)');return;}
        var r=e.getBoundingClientRect(), cs=G(e);
        out.push(sel+'  top='+Math.round(r.top)+' bot='+Math.round(r.bottom)+' h='+Math.round(r.height)+
                 '  pad='+cs.paddingTop+'/'+cs.paddingBottom+'  mg='+cs.marginTop+'/'+cs.marginBottom+
                 '  fs='+cs.fontSize+' lh='+cs.lineHeight+'  disp='+cs.display);
        if(depth>0){ [].forEach.call(e.children, function(c,i){
            var cr=c.getBoundingClientRect(), ccs=G(c);
            out.push('   - '+c.tagName.toLowerCase()+'.'+String(c.className).split(' ')[0]+
                     '  top='+Math.round(cr.top)+' bot='+Math.round(cr.bottom)+' h='+Math.round(cr.height)+
                     '  mg='+ccs.marginTop+'/'+ccs.marginBottom+'  fs='+ccs.fontSize+' lh='+ccs.lineHeight);
          }); }
      }
      walk('.hero', 1);
      walk('.hero .in', 1);
      walk('.flow', 1);
      walk('.hero-l', 1);
      walk('.tag', 0);
      walk('.chips', 0);
      walk('.idcard', 0);
      out.push('scroll-p-remains='+d.querySelectorAll('p.scroll').length);
      document.getElementById('hud').textContent='@@'+out.join('\\n')+'@@';
    }, 700);
  }, 400);
});
"""
page = "_probe2.html"
open(os.path.join(ROOT, page), "w", encoding="utf-8").write("""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0}iframe{border:0;display:block}#hud{padding:6px;white-space:pre;font:11px monospace}</style></head><body>
<iframe id="f" src="../index.html" style="width:390px;height:844px"></iframe>
<div id="hud"></div><script>%s</script></body></html>""" % JS)
r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=420,1300",
                    "--virtual-time-budget=4000", "--dump-dom",
                    "http://127.0.0.1:%d/%s" % (PORT, page)], capture_output=True, timeout=120)
dom = r.stdout.decode("utf-8", "replace")
m = re.search(r"@@(.*?)@@", dom, re.S)
print(m.group(1) if m else dom[-2000:])
httpd.shutdown()
p = os.path.join(ROOT, page)
if os.path.exists(p):
    os.remove(p)
