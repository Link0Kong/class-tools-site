"""Public timetable refresh regression. Run with python -B tools/tests/timetable_refresh_check.py.

Requires Microsoft Edge, websocket-client and Pillow. Only the application HTML and local fixtures are served.
"""
import argparse
import base64
import json
import subprocess
import tempfile
import threading
import urllib.request
from datetime import date, timedelta
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic, sleep
from PIL import Image

from _test_account import TEST_NAME, TEST_SID
from v2_tt_frame_check import CDP, EDGE, wait_until

HERE = Path(__file__).resolve().parent


class Page(CDP):
    def evaluate(self, expr, await_promise=False):
        result = self.send("Runtime.evaluate", {"expression":expr,"returnByValue":True,"awaitPromise":await_promise})
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result["result"].get("value")

    def wait_for(self, expr, timeout):
        return wait_until(self, expr, timeout)

    def set_device(self, width, height, scale, mobile):
        self.send("Emulation.setDeviceMetricsOverride", {"width":width,"height":height,"deviceScaleFactor":scale,"mobile":mobile})

    def close(self):
        self.send("Page.close")
        super().close()


class PageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/fixture/userdata":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(self.server.userdata).encode())
            return
        if self.path != "/index.html":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", "connect-src 'self'; img-src 'self' data: blob:; frame-src 'self' blob: data:")
        self.end_headers()
        self.wfile.write(self.server.index_html)

    def do_POST(self):
        if self.path != "/fixture/userdata":
            self.send_error(404)
            return
        rows = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert len(rows) == 1 and rows[0]["id"] == TEST_SID
        self.server.userdata = rows
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(rows).encode())

    def log_message(self, *args):
        pass


def snapshot(name, stamp=None, term="term-a"):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    courses = [
        {"name": name, "room": "Test-101", "day": today.weekday(), "start": 1, "end": 2,
         "weeks": "1-2", "parity": "odd"},
        {"name": name + "-later", "room": "Test-202", "day": today.weekday(), "start": 5,
         "end": 6, "weeks": "1-2", "parity": "all"},
    ]
    body = {"c": courses, "t": monday.isoformat(), "meta": {"term": term, "source": "jwxt"}}
    if stamp is not None:
        body["meta"]["fetchedAt"] = stamp
    return body


INIT = """
localStorage.setItem('zq_class_identity',JSON.stringify(Object.assign(IDENT,{ts:Date.now()})));
if(!localStorage.getItem('zq_tt_pub'))localStorage.setItem('zq_tt_pub',JSON.stringify(CACHE));
window.confirm=()=>true;
window.jsErrors=[];window.addEventListener('error',e=>{if(e.message)jsErrors.push(e.message);});
window.requests={static:[],cloud:[]};
const fixtureFetch=window.fetch.bind(window),realNow=Date.now.bind(Date);
window.clockOffset=0;Date.now=()=>realNow()+clockOffset;
window.fetch=(url,opts)=>{
  const path=new URL(url,location.href);
  if(path.pathname.endsWith('/userdata')){
    return fixtureFetch('/fixture/userdata',{method:opts.method||'GET',body:opts.body});
  }
  const source=path.pathname.endsWith('/tt.json')?'static':
    path.pathname.endsWith('/site_assets')&&path.searchParams.get('id')==='eq.tt'?'cloud':null;
  if(!source)return Promise.resolve(new Response('[]'));
  return new Promise(resolve=>requests[source].push((body,status)=>resolve(new Response(body,{status}))));
};
window.canvasTexts=[];
const drawText=CanvasRenderingContext2D.prototype.fillText;
CanvasRenderingContext2D.prototype.fillText=function(value,...rest){
  canvasTexts.push(String(value));return drawText.call(this,value,...rest);
};
document.addEventListener('click',e=>{
  const link=e.target.closest('a[download]');
  if(!link)return;
  e.preventDefault();
  if(!window.exportBlob)return;
  const reader=new FileReader();
  reader.onload=()=>window.downloaded={name:link.download,data:reader.result};
  reader.readAsDataURL(window.exportBlob);
},true);
const objectURL=URL.createObjectURL.bind(URL);URL.createObjectURL=blob=>{
  if(blob.type==='image/png')window.exportBlob=blob;
  return objectURL(blob);
};
"""


def open_page(browser, url):
    identity = {"sid": TEST_SID, "name": TEST_NAME, "token": "fixture-only", "is_admin": False}
    with urllib.request.urlopen(urllib.request.Request(browser + "/json/new?about:blank",method="PUT")) as result:
        page = Page(json.load(result)["webSocketDebuggerUrl"])
    page.send("Page.enable")
    page.send("Page.addScriptToEvaluateOnNewDocument", {"source":
        INIT.replace("IDENT", json.dumps(identity)).replace("CACHE", json.dumps(snapshot("legacy-cache")))})
    page.send("Page.navigate", {"url":url})
    assert page.wait_for("document.readyState==='complete'&&typeof window.__ttLogin==='object'", 10)
    return page


def run(browser, url, evidence_dir):
    page = open_page(browser, url)

    def wait(expr):
        assert page.wait_for(expr, 5), expr

    def click(selector):
        page.evaluate("document.querySelector(%s).click()" % json.dumps(selector))

    def reply(source, pos, value, status=200, raw=False):
        wait("requests.%s.length>%d" % (source, pos))
        body = value if raw else json.dumps(value)
        page.evaluate("requests.%s[%d](%s,%d)" % (source, pos, json.dumps(body), status))

    def cached(name):
        wait("JSON.parse(localStorage.zq_tt_pub).c[0].name===%s" % json.dumps(name))

    def text(selector, part):
        wait("document.querySelector(%s).textContent.includes(%s)" % (json.dumps(selector), json.dumps(part)))

    def refresh():
        click("#ttFromPub")

    # Startup shows an unversioned cache, then runs a real background pull.
    wait("requests.static.length===1")
    text("#tList", "legacy-cache")
    reply("static", 0, {"c": []})
    reply("cloud", 0, [{"body": json.dumps(snapshot("cloud-1", 100))}])
    cached("cloud-1")
    page.evaluate("window.__diag.gotoTab('tt')")
    click("#tImport")
    # Each invalid static input must trigger its own cloud fallback, including a 200 invalid course.
    for i, (value, status, raw) in enumerate([
        ("down", 503, True), ("not-json", 200, True), ({"unexpected": []}, 200, False),
        ({"c": [{"day": 1}]}, 200, False),
    ], start=1):
        refresh()
        reply("static", i, value, status, raw)
        name = "fallback-" + str(i)
        reply("cloud", i, [{"body": snapshot(name, 100 + i)}])
        cached(name)
        text("#ttSyncInfo", "2 门")
    # A later manual refresh succeeds first; the late response cannot replace its data.
    refresh()
    refresh()
    reply("static", 6, snapshot("current", 200))
    cached("current")
    reply("static", 5, snapshot("late"))
    assert page.evaluate("requests.cloud.length") == 5
    cached("current")
    # Reloaded old revisions (and unversioned replicas) cannot replace a versioned snapshot.
    refresh()
    reply("static", 7, snapshot("stale", 105))
    reply("cloud", 5, [{"body": snapshot("unversioned")}])
    text("#toast", "已保留较新的教务课表")
    cached("current")
    refresh()
    reply("static", 8, None, 503)
    reply("cloud", 6, [{"body": {"c": []}}])
    text("#toast", "没有取到教务课表")
    cached("current")
    # A new term can start without a producer timestamp. Static success makes no cloud request.
    refresh()
    reply("static", 9, snapshot("new-term", term="term-b"))
    cached("new-term")
    assert page.evaluate("requests.cloud.length") == 7
    # A personal import stays selected through public refresh; clearing it restores that public revision.
    personal = snapshot("personal")
    page.evaluate("document.querySelector('#ttPaste').value=%s" % json.dumps(json.dumps(personal)))
    click("#ttDoImport")
    text("#tSyncSt", "个人课表")
    read_personal = """(async()=>{
      const rows=await (await fetch('/fixture/userdata',{})).json();
      return rows.length && JSON.parse(rows[0].blob).tt.ttLocal;
    })()"""
    deadline = monotonic() + 5
    while not page.evaluate(read_personal, await_promise=True):
        assert monotonic() < deadline, "个人课表没有进入模拟 userdata"
        sleep(0.05)
    # A different loopback origin has fresh browser storage but reads the same simulated userdata row.
    remote = open_page(browser, url.replace("127.0.0.1", "localhost"))
    assert remote.wait_for("window.__ttLogin.state().src==='mine'", 5)
    remote.evaluate("window.__diag.gotoTab('tt')")
    assert remote.wait_for("document.querySelector('#tList').textContent.includes('personal')", 5), remote.evaluate(
        "[window.__ttLogin.state(),document.querySelector('#tList').textContent,document.querySelector('#tSyncSt').textContent]")
    click("#tImport")
    refresh()
    reply("static", 10, snapshot("public-final", 300, "term-b"))
    cached("public-final")
    text("#tList", "personal")
    click("#ttImportClose")
    click("#tImg")
    wait("canvasTexts.some(t=>t.includes('personal'))")
    click("#ttLoginClear")
    text("#tList", "public-final")
    deadline = monotonic() + 5
    while page.evaluate(read_personal, await_promise=True):
        assert monotonic() < deadline, "清除个人课表没有到达模拟 userdata"
        sleep(0.05)
    remote.evaluate("clockOffset+=65000;document.dispatchEvent(new Event('visibilitychange'))")
    assert remote.wait_for("window.__ttLogin.state().src==='pub'", 5)
    remote.close()
    page.send("Page.bringToFront")
    text("#tWeekLbl", "第 1 周")
    click('#tViewSeg [data-ttview="week"]')
    wait("!!document.querySelector('#tGrid [data-cname=\"public-final\"]')")
    click("#tNextW")
    text("#tWeekLbl", "第 2 周")
    assert page.evaluate("!document.querySelector('#tGrid [data-cname=\"public-final\"]')")
    wait("!!document.querySelector('#tGrid [data-cname=\"public-final-later\"]')")
    click("#tThisW")
    click('#tList [data-cname="public-final"]')
    text("#ttCBody", "public-final")
    wait("document.querySelector('[data-tt-map-room]').dataset.ttMapRoom==='Test-101'")
    click("#ttCClose")
    page.evaluate("window.downloaded=null;canvasTexts.length=0")
    click("#tImg")
    wait("canvasTexts.some(t=>t.includes('public-final'))")
    wait("!!window.downloaded")
    download = page.evaluate("window.downloaded")
    assert download["name"].endswith(".png")
    data = base64.b64decode(download["data"].split(",")[1], validate=True)
    with Image.open(BytesIO(data)) as picture:
        size = picture.size
        assert picture.format == "PNG" and min(size) >= 400
        picture.load()
    drawn = page.evaluate("canvasTexts")
    for field in ("参数配置","tool.furina.fun","生成时间","编号"):
        assert any(field in line for line in drawn), field
    if evidence_dir:
        (evidence_dir / "timetable-export.png").write_bytes(data)
    print("PNG", size, len(data), "bytes")
    for width in (390, 430, 1100):
        page.set_device(width, 860, 1, mobile=width < 600)
        wait("innerWidth===%d" % width)
        for tab in ("tt", "workbench"):
            page.evaluate("window.__diag.gotoTab(%s)" % json.dumps(tab))
            widths = page.evaluate("[innerWidth,document.documentElement.scrollWidth,document.body.scrollWidth]")
            assert max(widths) == width, (tab, widths)
            if evidence_dir:
                result = page.send("Page.captureScreenshot",{"format":"png"})
                (evidence_dir / ("%s-%d.png" % (tab,width))).write_bytes(base64.b64decode(result["data"]))
        print("timetable/workbench viewport=scrollWidth=", width)
    page.evaluate("window.__diag.gotoTab('workbench')")
    text("#wbCourses", "public-final")
    # A day boundary must update the workbench from the same accepted public snapshot.
    page.evaluate("""window.realDate=Date; window.wallTime='2026-11-23T23:59:00';
        window.Date=class extends realDate {
          constructor(...args){super(...(args.length?args:[wallTime]));}
        };""")
    midnight = snapshot("monday-course", 400, "midnight")
    midnight["t"] = "2026-11-23"
    midnight["c"][0]["day"] = 0
    midnight["c"][1].update(day=1, name="tuesday-course")
    refresh()
    reply("static", 11, midnight)
    text("#wbCourseNote", "明天")
    text("#wbCourseNote", "tuesday-course")
    page.evaluate("wallTime='2026-11-24T00:01:00';document.dispatchEvent(new Event('visibilitychange'))")
    text("#wbCourses", "tuesday-course")
    assert "monday-course" not in page.evaluate("document.querySelector('#wbCourses').textContent")
    page.evaluate("window.Date=realDate")
    # A new request must not accept a stale mirror from an earlier, identifiable teaching term.
    current = snapshot("second-term", 200, "2026-2027-2")
    current["t"] = "2027-03-01"
    refresh()
    reply("static", 12, current)
    cached("second-term")
    old = snapshot("previous-term", 900, "2026-2027-1")
    old["t"] = "2026-08-31"
    refresh()
    reply("static", 13, old)
    reply("cloud", 7, [{"body":current}])
    cached("second-term")
    # Two same-origin tabs share the disk cache. A stale open tab sees the newer durable revision.
    other = open_page(browser, url)
    other.evaluate("document.querySelector('#ttFromPub').click()")
    assert other.wait_for("requests.static.length>0", 5)
    later = dict(current, c=[dict(current["c"][0],name="other-tab-new")], meta=dict(current["meta"],fetchedAt=550))
    refresh()
    reply("static", 14, later)
    cached("other-tab-new")
    other.evaluate("requests.static.at(-1)(%s,200)" % json.dumps(json.dumps(current)))
    assert other.wait_for("requests.cloud.length>0", 5)
    other.evaluate("requests.cloud.at(-1)('[]',200)")
    assert other.wait_for("document.querySelector('#tList').textContent.includes('other-tab-new')", 5)
    cached("other-tab-new")
    other.close()
    page.send("Page.bringToFront")
    # A different producer can use its own revision clock in the same semester.
    distinct = dict(current,c=[dict(current["c"][0],name="other-producer")],meta=dict(current["meta"],source="alternate",fetchedAt=1))
    refresh()
    reply("static", 15, distinct)
    cached("other-producer")
    # Legacy producer replies have no comparable version, so retain the most recent accepted request.
    legacy = dict(current, c=[dict(current["c"][0], name="legacy-later")], meta={"source":"unversioned","term":"2026-2027-2"})
    refresh()
    refresh()
    reply("static",17,legacy)
    cached("legacy-later")
    reply("static",16,dict(legacy,c=[dict(current["c"][0], name="legacy-earlier")]))
    cached("legacy-later")
    # Even when Web Locks are unavailable, recheck durable state before applying the last reply.
    page.evaluate("Object.defineProperty(navigator,'locks',{value:undefined,configurable:true})")
    refresh()
    refresh()
    newer = dict(distinct,meta=dict(distinct["meta"],fetchedAt=850))
    reply("static",19,dict(newer,c=[dict(current["c"][0], name="newer-request")]))
    cached("newer-request")
    reply("static",18,dict(newer,c=[dict(current["c"][0], name="newest-publication")],
                           meta=dict(newer["meta"],fetchedAt=900)))
    cached("newest-publication")
    shared = base64.urlsafe_b64encode(json.dumps(snapshot("shared-course")).encode()).decode().rstrip("=")
    shared_page = open_page(browser, url + "#tt=" + shared)
    assert shared_page.wait_for("window.__ttLogin.state().src==='link'", 5)
    assert shared_page.wait_for("document.querySelector('#tList').textContent.includes('shared-course')", 5)
    shared_page.close()
    assert not page.evaluate("jsErrors"), page.evaluate("jsErrors")
    print("JS exceptions: 0; PNG contains timetable, parameters, domain, time and receipt id")


def main(index_html=None, evidence_dir=None):
    if evidence_dir:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    with ThreadingHTTPServer(("127.0.0.1", 0), PageHandler) as server, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        server.index_html = index_html if index_html is not None else (HERE.parent / "index.html").read_bytes()
        server.userdata = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        process = subprocess.Popen([EDGE,"--headless=new","--disable-background-networking","--disable-sync",
            "--no-first-run","--window-size=1100,860","--remote-debugging-port=0","--user-data-dir="+profile,"about:blank"],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            active_port = Path(profile) / "DevToolsActivePort"
            deadline = monotonic()+15
            while not active_port.exists():
                assert monotonic()<deadline and process.poll() is None, "Edge DevTools 未就绪"
                sleep(0.05)
            browser = "http://127.0.0.1:" + active_port.read_text().splitlines()[0]
            run(browser, "http://127.0.0.1:%d/index.html" % server.server_port, evidence_dir)
        finally:
            process.terminate()
            process.wait(timeout=10)
            server.shutdown()
    print("PASS public timetable refresh, source selection and display")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir",type=Path,help="Optional destination for PNG evidence")
    main(evidence_dir=parser.parse_args().evidence_dir)
