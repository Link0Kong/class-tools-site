"""Browser portion of conversion_fixture.py; all files and the real Drop handler share a loopback origin."""
import hashlib
import json
import subprocess
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from _test_account import TEST_NAME, TEST_SID
from sync_browser_fixture import click, screenshot, wait
from timetable_refresh_check import Page
from v2_tt_frame_check import EDGE


def with_fixture_page(handler,web,first,second):
    init="""
<script>
localStorage.setItem('zq_class_identity',JSON.stringify({sid:SID,name:NAME,token:location.search==='?second'?SECOND:FIRST,ts:Date.now()}));
window.__DROP_BASE=location.origin+'/drop';window.fixtureErrors=[];
addEventListener('error',e=>{if(e.message)fixtureErrors.push(e.message)});
addEventListener('unhandledrejection',e=>fixtureErrors.push(String(e.reason)));
const fixtureNet=window.fetch.bind(window);
window.fetch=(u,o)=>{const target=new URL(u,location.href);return target.origin===location.origin&&target.pathname.startsWith('/drop/')?fixtureNet(u,o):Promise.resolve(new Response('[]'))};
window.fixtureHash=async href=>{const r=await fetch(href,{credentials:'same-origin'});if(!r.ok)throw Error('download '+r.status);
 const hash=await crypto.subtle.digest('SHA-256',await r.arrayBuffer());return Array.from(new Uint8Array(hash),x=>x.toString(16).padStart(2,'0')).join('')};
</script>"""
    for k,v in (("SID",TEST_SID),("NAME",TEST_NAME),("FIRST",first),("SECOND",second)):
        init=init.replace(k,json.dumps(v))
    raw=(web/"tools/index.html").read_bytes().replace(b"<head>",b"<head>"+init.encode(),1)
    class PageHandler(handler):
        def handle(self):
            try:super().handle()
            except (ConnectionResetError,ConnectionAbortedError):pass  # browser closes idle HTTP sockets at teardown

        def do_GET(self):
            if urlsplit(self.path).path!="/fixture-page":return super().do_GET()
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(raw)))
            self.send_header("Content-Security-Policy","connect-src 'self'; img-src 'self' data: blob:; frame-src 'self' data: blob:")
            self.end_headers()
            self.wfile.write(raw)
    return PageHandler


@contextmanager
def web_sender(endpoint,out):
    with tempfile.TemporaryDirectory(prefix="w05-edge-",ignore_cleanup_errors=True) as profile:
        process=subprocess.Popen([EDGE,"--headless=new","--no-first-run","--disable-background-networking","--disable-sync",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost",
            "--remote-debugging-port=0","--user-data-dir="+profile,"about:blank"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            port_file=Path(profile)/"DevToolsActivePort"
            deadline=time.monotonic()+20
            while not port_file.exists():
                assert process.poll() is None and time.monotonic()<deadline,"Edge startup"
                time.sleep(.05)
            browser="http://127.0.0.1:"+port_file.read_text().splitlines()[0]
            def open_tab(second=False):
                with urllib.request.urlopen(urllib.request.Request(browser+"/json/new?about:blank",method="PUT")) as r:
                    page=Page(json.load(r)["webSocketDebuggerUrl"])
                page.send("Page.enable")
                host=endpoint[:-5].replace("127.0.0.1","localhost") if second else endpoint[:-5]
                page.send("Page.navigate",{"url":host+"/fixture-page"+("?second" if second else "")})
                wait(page,"document.readyState==='complete'&&window.__B2&&window.__diag")
                click(page, '[data-tab="all"]')
                click(page, '#allCards [data-card="file"]')
                wait(page,"document.querySelector('#fileState').textContent.includes('已连接')")
                return page
            first=open_tab()
            first.set_device(390,860,1,True)
            root=first.send("DOM.getDocument",{})["root"]["nodeId"]
            node=first.send("DOM.querySelector",{"nodeId":root,"selector":"#fileUpInput"})["nodeId"]
            first.send("DOM.setFileInputFiles",{"nodeId":node,"files":[str(out/"source.pptx"),str(out/"ordinary.txt")]})
            wait(first,"document.querySelectorAll('#fileList .file-item').length===2&&document.querySelectorAll('[data-fileppt=submit]').length===1")
            assert first.evaluate("document.querySelector('[data-fileppt=submit]').closest('.file-item').querySelector('.file-name').textContent")=="source.pptx"
            click(first,"[data-fileppt=submit]")
            wait(first,"document.querySelector('#fileList').textContent.includes('等待处理')")
            screenshot(first,out,"web-upload-queued")
            receiver=open_tab(True)
            def receive(fid):
                click(receiver,"#fileRefresh")
                wait(receiver,"document.querySelector('[data-fileppt=results]')!==null")
                row=json.dumps(".file-item[data-fid='"+fid+"'] a[href*='/file/']")
                original=receiver.evaluate("fixtureHash(document.querySelector("+row+").href)",True)
                assert original==hashlib.sha256((out/"source.pptx").read_bytes()).hexdigest()
                click(receiver,"[data-fileppt=results]")
                wait(receiver,"document.querySelectorAll('.ppt-file a[download][href*=\"/ppt-result/\"]').length>=2")
                links=receiver.evaluate("Array.from(document.querySelectorAll('.ppt-file a[download][href*=\"/ppt-result/\"]'),a=>a.href)")
                for kind,filename in (("compat","result.pptx"),("pdf","result.pdf")):
                    href=next(x for x in links if "/"+kind+"?" in x)
                    assert receiver.evaluate("fixtureHash("+json.dumps(href)+")",True)==hashlib.sha256((out/filename).read_bytes()).hexdigest()
                screenshot(receiver,out,"web-receiver-ready")
                assert not first.evaluate("fixtureErrors") and not receiver.evaluate("fixtureErrors")
                print("PASS mobile-width Web file input / conversion submit and independent-account-store Web menu / original and artifact hashes",flush=True)
            yield receive
        finally:
            process.terminate()
            process.wait(timeout=15)
