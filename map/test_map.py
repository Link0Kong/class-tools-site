"""Exercise the bundled map through its public page and timetable interfaces."""

import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
import time
from urllib.parse import quote
from urllib.request import urlopen

import websocket


HERE = Path(__file__).resolve().parent
PAGE = 'campus_final_25d.html'
VIEWPORTS = ((360, 760), (430, 900), (780, 420), (800, 980), (1280, 800))


def until(check, message):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.06)
    raise AssertionError(message)


class Browser:
    def __init__(self, socket):
        self.socket = socket
        self.id = 0
        self.errors = []

    def call(self, method, **params):
        self.id += 1
        self.socket.send(json.dumps({'id': self.id, 'method': method, 'params': params}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get('method') == 'Runtime.exceptionThrown':
                self.errors.append(message['params']['exceptionDetails'])
            if message.get('id') == self.id:
                if 'error' in message:
                    raise RuntimeError(message['error'])
                return message.get('result', {})

    def js(self, expression):
        result = self.call('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'])
        return result['result'].get('value')

    def open(self, url):
        self.call('Page.navigate', url=url)
        until(lambda: self.js('location.href') == url and self.js('window.zqMapReady === true'), url)

    def capture(self, path):
        path.write_bytes(base64.b64decode(self.call('Page.captureScreenshot', format='png')['data']))


def run(browser, base, evidence):
    browser.call('Page.enable')
    browser.call('Runtime.enable')
    browser.call('Emulation.setEmulatedMedia', features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    page = f'{base}/{PAGE}'
    for width, height in VIEWPORTS:
        browser.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        for theme, room, level in (('light', '1102A', 1), ('dark', '０２５０２', 5)):
            browser.open(f'{page}?theme={theme}&room={quote(room)}')
            assert browser.js('document.documentElement.dataset.theme') == theme
            assert not browser.js('document.querySelector("#floor").hidden')
            assert browser.js('document.querySelector("#fFloors .on").textContent') == f'{level} 层'
            assert browser.js('!!document.querySelector("#fRooms .on")')
            assert browser.js('document.documentElement.scrollWidth') <= width
            assert browser.js('document.querySelector(".floorCard").scrollWidth <= document.querySelector(".floorCard").clientWidth')
            if evidence:
                browser.capture(evidence / f'floor-{width}-{theme}.png')
            assert browser.js('zqMapDismiss()')
            assert browser.js('document.querySelector("#floor").hidden')
            assert browser.js('!document.querySelector("#selection").hidden')
        print(f'{width}×{height}: floor link, dark/light, map restored')

    legacy_webview = browser.call('Page.addScriptToEvaluateOnNewDocument',
                                  source='delete Element.prototype.replaceChildren')['identifier']
    for room, code in (('自强楼(教室01204)', '01204'), ('厚德楼 （０２２０１室）', '02201')):
        browser.open(f'{page}?room={quote(room)}')
        assert browser.js('document.querySelector("#fFloors .on").textContent') == '2 层'
        assert browser.js('document.querySelector("#fRoomInfo").textContent').startswith(code)
    browser.js('zqMapDismiss(); zqMapTarget("自强楼（教室01999）")')
    assert browser.js('document.querySelector("#floor").hidden && document.querySelector("#cSub").textContent.includes("未收录")')
    browser.call('Page.removeScriptToEvaluateOnNewDocument', identifier=legacy_webview)

    browser.open(f'{page}?room=07X206')
    assert browser.js('document.querySelector("#floor").hidden && document.querySelectorAll("#results .ritem").length === 2')
    browser.js('document.querySelectorAll("#results .ritem")[1].click()')
    assert browser.js('document.querySelector("#fFloors .on").textContent') == '3 层'
    assert browser.js('document.querySelector("#fPlan").hidden')
    assert browser.js('document.querySelector("#fRoomInfo").textContent.includes("护理学院")')
    browser.js('zqMapDismiss(); zqMapTarget("01999")')
    assert browser.js('document.querySelector("#floor").hidden && document.querySelector("#cSub").textContent.includes("未收录")')
    browser.js('document.querySelector("[data-origin=east]").click()')
    assert browser.js('document.querySelector("#routePath").textContent.startsWith("东侧门")')
    assert browser.js('document.querySelector("#routePath").textContent.endsWith("自强楼附近")')
    browser.js('document.querySelector("[data-origin=cur]").click(); zqMapTarget("B20")')
    assert browser.js('document.querySelector("#routePath").textContent.startsWith("自强楼")')
    browser.open(f'{base}/embed.html')
    until(lambda: browser.js('window.mapFrame.contentWindow.zqMapReady === true'), 'map iframe')
    browser.js('mapFrame.contentWindow.postMessage({type:"zq-map-target",room:"01217"}, location.origin)')
    until(lambda: browser.js('mapFrame.contentDocument.querySelector("#fRoomInfo").textContent.startsWith("01217")'), 'timetable message')
    browser.js('mapFrame.contentWindow.zqMapDismiss(); mapFrame.contentDocument.getElementById("btnTt").click()')
    until(lambda: browser.js('window.backToTimetable === true'), 'timetable return message')

    if evidence:
        for name, key in [('ziqiang', 'B217202'), ('houde', 'B154012'), ('wuxing', 'B202061')]:
            for phase, filename in [('before', 'baseline.html'), ('after', PAGE)]:
                browser.open(f'{base}/{filename}?theme=light&b={key}')
                browser.js(f'fixedMapView({json.dumps(key)})')
                time.sleep(.27)
                browser.capture(evidence / f'{name}-{phase}.png')

    assert not browser.errors, browser.errors
    print('Ambiguous room, institution, missing room, alternate gate and building origins: OK')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--edge', type=Path, default=Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'))
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=True)
    old = subprocess.check_output(['git', 'show', f'HEAD:map/{PAGE}'], cwd=HERE.parent)
    embed = f'''<iframe id="mapFrame" src="/{PAGE}?embed=1" width="960" height="690"></iframe>
    <script>window.zqMapReady=true; window.backToTimetable=false;
    addEventListener('message',e=>{{if(e.origin===location.origin&&e.source===mapFrame.contentWindow&&e.data.type==='zq-map-open')
      window.backToTimetable=e.data.tab==='tt';}});</script>'''.encode()
    fixed_view = b'''  window.fixedMapView = function (key) {
    var building = BYID[key], p = raw(building.x, building.y, 0), area = viewArea();
    var scale = 2.45, zoom = scale / BASE.s;
    flyTo(zoom, area.x - BASE.ox - p[0] * scale, area.y - BASE.oy - p[1] * scale);
  };
'''

    class Handler(BaseHTTPRequestHandler):
        def handle(self):
            try:
                super().handle()
            except (ConnectionResetError, BrokenPipeError):
                pass

        def do_GET(self):
            name = self.path.split('?')[0]
            if name not in (f'/{PAGE}', '/baseline.html', '/embed.html'):
                self.send_error(404)
                return
            if name == '/embed.html':
                body = embed
            else:
                body = old if name == '/baseline.html' else (HERE / PAGE).read_bytes()
                hook = b'  window.addEventListener("resize",'
                body = body.replace(hook, fixed_view + hook, 1)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server, tempfile.TemporaryDirectory(prefix='ct-map-') as profile:
        Thread(target=server.serve_forever, daemon=True).start()
        process = subprocess.Popen([str(args.edge), '--headless=new', '--no-first-run', '--disable-background-networking',
                                    '--remote-debugging-port=0', f'--user-data-dir={profile}', 'about:blank'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            active = Path(profile) / 'DevToolsActivePort'
            until(active.exists, 'Edge debugging port')
            port = active.read_text().splitlines()[0]
            with urlopen(f'http://127.0.0.1:{port}/json/list', timeout=4) as response:
                pages = json.load(response)
            target = next(page for page in pages if page['type'] == 'page')
            socket = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=6, suppress_origin=True)
            try:
                run(Browser(socket), f'http://127.0.0.1:{server.server_port}', args.evidence)
            finally:
                socket.close()
        finally:
            process.terminate()
            process.wait(timeout=8)
            server.shutdown()


if __name__ == '__main__':
    main()
