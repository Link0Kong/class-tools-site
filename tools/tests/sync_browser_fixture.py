"""Isolated Edge fixture for the Web synchronization suites. Only the supplied HTML and mock API are served."""
import base64
import json
import subprocess
import tempfile
import threading
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic, sleep

from _test_account import TEST_NAME, TEST_SID, assert_test_identity
from timetable_refresh_check import Page
from v2_tt_frame_check import EDGE

HERE = Path(__file__).resolve().parent
INIT = """
const owner=IDENTITY;
if(!localStorage.zq_class_identity)localStorage.zq_class_identity=JSON.stringify({...owner,ts:Date.now()});
window.confirm=()=>true;window.jsErrors=[];window.calls=[];
window.addEventListener('error',e=>{if(e.message)jsErrors.push(e.message)});
window.addEventListener('unhandledrejection',e=>jsErrors.push(String(e.reason)));
const network=window.fetch.bind(window);
window.fetch=async(u,o={})=>{
 const path=new URL(u,location.href),table=path.pathname.split('/').pop(),method=o.method||'GET';
 if(!TABLES.includes(table))return new Response('[]');
 const req={table,method,query:Object.fromEntries(path.searchParams),token:o.headers?.['X-Device-Id'],
   prefer:o.headers?.Prefer,body:o.body?JSON.parse(o.body):null,range:o.headers?.Range};
 calls.push(req);
 if(window.hold&&hold(req)){window.hold=null;await new Promise(r=>window.release=r);window.release=null;}
 if(window.fail&&fail(req))return new Response('{}',{status:503});
 const r=await network('/fixture',{method:'POST',body:JSON.stringify(req)});
 if(window.lose&&lose(req)){window.lose=null;throw Error('network response lost');}
 if(window.fake){const f=fake(req);if(f)return f;}
 return r;
};
"""


@contextmanager
def browser_fixture(service, html=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] != "/index.html":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "connect-src 'self'; img-src 'self' data: blob:; frame-src 'self' data: blob:")
            self.end_headers()
            self.wfile.write(html_bytes)

        def do_POST(self):
            if self.path != "/fixture":
                self.send_error(404)
                return
            try:
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with lock:
                    status, data, headers = service(req)
            except Exception as error:
                errors.append(str(error))
                status, data, headers = 500, {}, {}
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def log_message(self, *args):
            pass

    html_bytes = html if html is not None else (HERE.parent / "index.html").read_bytes()
    errors, lock = [], threading.Lock()
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        process = subprocess.Popen([EDGE, "--headless=new", "--no-first-run", "--disable-background-networking",
            "--disable-sync", "--remote-debugging-port=0", "--user-data-dir="+profile,
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            active = Path(profile) / "DevToolsActivePort"
            deadline = monotonic()+15
            while not active.exists():
                assert monotonic()<deadline and process.poll() is None, "DevTools startup"
                sleep(.05)
            browser = "http://127.0.0.1:"+active.read_text().splitlines()[0]

            def open_page(host="127.0.0.1", sid=TEST_SID, token="fixture-a", seed=""):
                assert_test_identity(sid)
                identity = {"sid":sid, "name":TEST_NAME, "token":token, "is_admin":False}
                url = f"http://{host}:{server.server_port}/index.html"
                request = urllib.request.Request(browser+"/json/new?about:blank", method="PUT")
                with urllib.request.urlopen(request) as result:
                    page = Page(json.load(result)["webSocketDebuggerUrl"])
                page.send("Page.enable")
                page.send("Page.addScriptToEvaluateOnNewDocument", {"source":
                    INIT.replace("IDENTITY",json.dumps(identity)).replace("TABLES",json.dumps(service.tables))+seed})
                page.send("Page.navigate", {"url":url})
                wait(page,"document.readyState==='complete'&&window.TASKSYNC&&window.__diag")
                return page
            open_page.endpoint = f"http://127.0.0.1:{server.server_port}/fixture"
            yield open_page
            assert not errors, errors
        finally:
            process.terminate()
            process.wait(timeout=10)
            server.shutdown()


def wait(page, expr):
    assert page.wait_for(expr, 8), (expr, page.evaluate("window.jsErrors"))


def click(page, selector):
    page.evaluate("document.querySelector(%s).click()" % json.dumps(selector))


def screenshot(page, directory, name):
    if directory:
        directory.mkdir(parents=True, exist_ok=True)
        data = page.send("Page.captureScreenshot", {"format":"png"})["data"]
        (directory/(name+".png")).write_bytes(base64.b64decode(data))
