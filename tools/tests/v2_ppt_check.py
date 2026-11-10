# -*- coding: utf-8 -*-
"""PPT 演示（网页端）专项验收 v1 —— `v2_ppt_check.py`

契约唯一真源：`web/ppt/CONTRACT.md`（§3 表 / §4 接口 / §5 manifest+播放语义 / §7 转场 / §8.2 网页）；
设计参考：`web/ppt/DESIGN.md`（§4.1–4.11 / §4.8 文案 / §11 检查点）。

覆盖：
  A 静态：TOOLS 追加 `ppt`、`#s-ppt`、APP_VER 仍 2.0.0、分片常量（512KiB / 并行4 / 重试2 / 60MiB）、
          轮询（10s / 180s 离线）、转场集合、全屏/黑屏/抽屉/退出确认、无外部资源
  B 列表：工具栏 + 全部页入口、6 张 fixture 卡片渲染、状态文案（上传/排队/转换中/转换失败/就绪无胶囊）、
          别人 uploading 不显示、封面 lazy、空态、离线提示（seen_at>180s）
  C 上传：注入 512KiB File → POST ppt_decks → POST ppt_upload_chunks（base64 校验）→ PATCH status=queued
  D 播放器：fixture manifest（data: 假图 + 假 mp4 data URL）→ 打开/页码按页/步点/顶部进度、
          点击右2/3·左1/3、键盘 →← Space、鼠标拖+触摸滑、缩略图跳页、备注抽屉、黑屏 B、
          全屏按钮、视频热点出现并打开媒体层、退出确认（继续/退出）、退出恢复 tab+滚动
  E 布局：430px 列表 + 播放器无横向溢出；播放器内滑动不改变 top tab（section.on 仍 #s-ppt）

做法（硬性要求）：
  - 本机 Edge headless + CDP 直连（复用 `tests/_qa_v2/_cdp.py` 的 Browser/Page）；
  - **PostgREST 用 CDP `Fetch.fulfillRequest` 拦截**，只 mock 三个路径：
    `ppt_decks` / `ppt_upload_chunks` / `site_assets`；其余请求：读（GET/HEAD/OPTIONS、POST /rpc/）放行，
    写请求直接 fail 并计数 —— 保证 **0 真实云端写**；
  - 注入身份是**假 token**（测试身份 SID/姓名，绝不使用真实 token）；
  - 截图存 `tests/_shots_ppt/`（保留 latest 作为证据；无其它过程文件）。

用法（cwd 任意）：
    python web/tools/tests/v2_ppt_check.py
退出码 0 = 全绿。
"""
import base64
import functools
import http.server
import json
import os
import re
import shutil
import socketserver
import sys
import threading
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))     # tools/tests
TOOLS = os.path.dirname(HERE)                         # tools
WEB = os.path.dirname(TOOLS)                          # web
SRC = os.environ.get("PPTC_SRC") or os.path.join(TOOLS, "index.html")
SHOTS = os.path.join(HERE, "_shots_ppt")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
import _cdp  # noqa: E402

SID = "3260799999"        # 测试身份学号（class_ids 里的 is_test 身份；非真实用户）
NAME = "测试同学"
OTHER_SID = "3260799998"
OTHER_NAME = "陈子麒"
TOKEN = "fake-token-ppt-check"   # 假 token：不写云端、不可用于任何真实接口

NOW = int(time.time() * 1000)
CLOUD_MOCK = ("ppt_decks", "ppt_upload_chunks", "site_assets")


def svg(label, bg, fg="#FFFFFF", w=1600, h=900):
    body = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d">'
            '<rect width="%d" height="%d" fill="%s"/>'
            '<text x="%d" y="%d" font-size="180" font-family="sans-serif" fill="%s" '
            'text-anchor="middle">%s</text></svg>') % (w, h, w, h, bg, w // 2, h // 2 + 60, fg, label)
    return "data:image/svg+xml;base64," + base64.b64encode(body.encode("utf-8")).decode("ascii")


IMG1 = svg("STEP-1-1", "#1F3B36")
IMG2 = svg("STEP-1-2", "#26485F")
IMG3 = svg("STEP-2-1", "#5A4632")
IMG4 = svg("STEP-3-1", "#3B2B4A")
THUMB1 = svg("P1", "#1F3B36", w=400, h=225)
THUMB2 = svg("P2", "#26485F", w=400, h=225)
THUMB3 = svg("P3", "#3B2B4A", w=400, h=225)
VIDEO_DATA = "data:video/mp4;base64,AAAAIGZ0eXBtcDQyAAAAAG1wNDJpc29t"   # 假 mp4（只验证热点→媒体层）
SRC_DATA = "data:application/octet-stream;base64,AAAA"

MANIFEST = {
    "v": 1,
    "base": "",
    "src": SRC_DATA,
    "w": 1600, "h": 900,
    "slides": [
        {"tr": "fade", "trd": 450, "notes": "第一页备注：开场讲两句", "thumb": THUMB1,
         "steps": [{"img": IMG1, "media": []}, {"img": IMG2, "media": []}]},
        {"tr": "push", "trd": 360, "notes": "", "thumb": THUMB2,
         "steps": [{"img": IMG3, "media": [
             {"s": VIDEO_DATA, "k": "v", "x": 0.12, "y": 0.15, "w": 0.76, "h": 0.70}]}]},
        {"tr": "wipe", "trd": 380, "notes": "第三页备注：收尾", "thumb": THUMB3,
         "steps": [{"img": IMG4, "media": []}]},
    ],
    "media": [{"s": VIDEO_DATA, "k": "v", "w": 1280, "h": 720, "dur": 12.4}],
}


def deck(**kw):
    row = {"id": "dtestready1", "title": "班会演示", "owner_sid": OTHER_SID, "owner_name": OTHER_NAME,
           "status": "ready", "progress": 100, "error": "", "slide_count": 3, "step_count": 4,
           "aspect": "16:9", "cover_url": THUMB1, "source_name": "班会.pptx", "source_size": 1234567,
           "created_at": NOW - 3600000, "converted_at": NOW - 3000000, "client": "web",
           "deleted": False, "manifest": MANIFEST}
    row.update(kw)
    return row


FIXTURE_DECKS = [
    deck(id="dtestup01", title="我正在上传", owner_sid=SID, owner_name=NAME, status="uploading",
         progress=34, slide_count=0, step_count=0, cover_url="", manifest={},
         source_name="上传中.pptx", created_at=NOW - 60000),
    deck(id="dtestup02", title="别人上传中-不应显示", owner_sid=OTHER_SID, owner_name=OTHER_NAME,
         status="uploading", progress=50, slide_count=0, step_count=0, cover_url="", manifest={},
         created_at=NOW - 50000),
    deck(id="dtestqueue1", title="排队演示", owner_sid=SID, owner_name=NAME, status="queued",
         progress=0, slide_count=0, step_count=0, cover_url="", manifest={},
         created_at=NOW - 90000),
    deck(id="dtestproc1", title="转换中的演示", owner_sid=SID, owner_name=NAME, status="processing",
         progress=61, slide_count=0, step_count=0, cover_url="", manifest={},
         created_at=NOW - 80000),
    deck(id="dtestfail1", title="失败的演示", owner_sid=SID, owner_name=NAME, status="failed",
         progress=0, error="转换超时", slide_count=0, step_count=0, cover_url="", manifest={},
         created_at=NOW - 120000),
    deck(),
]

MOCK = {
    "decks": [dict(d) for d in FIXTURE_DECKS],
    "agent": {"online": True, "seen_at": NOW - 5000, "queued": 2, "version": "1.0", "host": "test"},
    "posts": [],        # POST ppt_decks
    "patches": [],      # PATCH ppt_decks
    "chunks": [],       # POST ppt_upload_chunks
    "agent_gets": 0,
    "list_gets": 0,
    "man_gets": 0,
    "blocked_writes": [],
    "mocked": 0,
}
MOCK_LOCK = threading.Lock()


def _find_deck(did):
    for d in MOCK["decks"]:
        if str(d.get("id")) == str(did):
            return d
    return None


def _query_first(qs, key):
    v = qs.get(key) or []
    return v[0] if v else ""


def mock_serve(method, url, body_text):
    """只处理三个 mock 路径；返回 (status, payload)。"""
    u = urllib.parse.urlsplit(url)
    qs = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    path = u.path
    with MOCK_LOCK:
        if "ppt_upload_chunks" in path and method == "POST":
            try:
                rows = json.loads(body_text or "[]")
            except Exception:
                rows = []
            for r in rows:
                data = str(r.get("data") or "")
                MOCK["chunks"].append({
                    "deck_id": r.get("deck_id"), "owner_sid": r.get("owner_sid"),
                    "idx": r.get("idx"), "data_len": len(data),
                    "b64": bool(re.match(r"^[A-Za-z0-9+/=]*$", data)),
                    "head": data[:16], "tail": data[-16:],
                    "decode_len": (len(base64.b64decode(data)) if data else 0),
                })
            return 201, []
        if "ppt_decks" in path:
            if method == "GET":
                sel = _query_first(qs, "select")
                # v2.0：列表标签用的轻量子查询 select=id,files:manifest->files（只有文件元数据，无 slides）
                if "manifest->files" in sel or "files:manifest" in sel:
                    MOCK["hint_gets"] = MOCK.get("hint_gets", 0) + 1
                    out = []
                    for d in MOCK["decks"]:
                        if d.get("deleted"):
                            continue
                        man = d.get("manifest")
                        if isinstance(man, str):
                            try:
                                man = json.loads(man)
                            except Exception:
                                man = None
                        files = man.get("files") if isinstance(man, dict) else None
                        out.append({"id": d.get("id"), "files": files})
                    return 200, out
                if "manifest" in sel:
                    MOCK["man_gets"] += 1
                    did = _query_first(qs, "id").replace("eq.", "")
                    row = _find_deck(did)
                    return 200, ([row] if row else [])
                MOCK["list_gets"] += 1
                rows = [d for d in MOCK["decks"] if not d.get("deleted")]
                rows.sort(key=lambda d: -int(d.get("created_at") or 0))
                return 200, rows
            if method == "POST":
                try:
                    rows = json.loads(body_text or "[]")
                except Exception:
                    rows = []
                for r in rows:
                    r = dict(r)
                    r.setdefault("manifest", {})
                    MOCK["posts"].append(dict(r))
                    MOCK["decks"].append(r)
                return 201, rows
            if method == "PATCH":
                did = _query_first(qs, "id").replace("eq.", "")
                try:
                    obj = json.loads(body_text or "{}")
                except Exception:
                    obj = {}
                row = _find_deck(did)
                if row is not None:
                    row.update(obj)
                    MOCK["patches"].append({"id": did, "body": obj})
                    return 200, [row]
                MOCK["patches"].append({"id": did, "body": obj, "miss": True})
                return 200, []
        if "site_assets" in path and method == "GET":
            qid = _query_first(qs, "id")
            if qid in ("eq.ppt_agent", "ppt_agent"):
                MOCK["agent_gets"] += 1
                return 200, [{"body": MOCK["agent"], "updated_at": NOW}]
            return 200, []
    return 200, []


def is_cloud_url(url):
    return "tcloudbasegateway.com" in (url or "")


def is_mocked_path(url):
    return any(k in (url or "") for k in CLOUD_MOCK)


def install_cdp_mock(page):
    """CDP Fetch 拦截：只 mock 三个 ppt 路径；其它读取放行、写入阻断（0 真实云端写）。"""
    orig = page._dispatch
    state = {"seen": 0, "mocked": 0, "blocked": 0, "passed": 0}

    def send_raw(method, params):
        page._id += 1
        page.ws.send(json.dumps({"id": page._id, "method": method, "params": params}))

    def fulfill(rid, code, payload, extra_headers=None):
        headers = [{"name": "Content-Type", "value": "application/json"},
                   {"name": "Access-Control-Allow-Origin", "value": "*"},
                   {"name": "Access-Control-Allow-Headers", "value": "*"},
                   {"name": "Access-Control-Allow-Methods", "value": "*"},
                   {"name": "Cache-Control", "value": "no-store"}]
        if extra_headers:
            headers.extend(extra_headers)
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        send_raw("Fetch.fulfillRequest", {
            "requestId": rid, "responseCode": int(code), "responseHeaders": headers,
            "body": base64.b64encode(body).decode("ascii"),
        })

    def patched(msg):
        if msg.get("method") == "Fetch.requestPaused":
            p = msg.get("params", {}) or {}
            rid = p.get("requestId")
            req = p.get("request", {}) or {}
            url = req.get("url") or ""
            method = (req.get("method") or "GET").upper()
            post = req.get("postData") or ""
            state["seen"] += 1
            try:
                if not is_cloud_url(url):
                    send_raw("Fetch.continueRequest", {"requestId": rid})
                    return
                if method == "OPTIONS":
                    send_raw("Fetch.fulfillRequest", {
                        "requestId": rid, "responseCode": 204,
                        "responseHeaders": [
                            {"name": "Access-Control-Allow-Origin", "value": "*"},
                            {"name": "Access-Control-Allow-Headers", "value": "*"},
                            {"name": "Access-Control-Allow-Methods", "value": "*"},
                        ], "body": "",
                    })
                    return
                if is_mocked_path(url):
                    state["mocked"] += 1
                    code, payload = mock_serve(method, url, post)
                    fulfill(rid, code, payload)
                    return
                # 其余路径：读放行（GET/HEAD/OPTIONS、POST /rpc/），写阻断（0 真实云端写）
                read_like = method in ("GET", "HEAD", "OPTIONS") or (method == "POST" and "/rpc/" in url)
                if read_like:
                    state["passed"] += 1
                    send_raw("Fetch.continueRequest", {"requestId": rid})
                else:
                    state["blocked"] += 1
                    with MOCK_LOCK:
                        MOCK["blocked_writes"].append(method + " " + url)
                    send_raw("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"})
            except Exception as e:  # noqa: BLE001
                try:
                    send_raw("Fetch.failRequest", {"requestId": rid, "errorReason": "Failed"})
                except Exception:
                    pass
                state["err"] = repr(e)
            return
        orig(msg)

    page._dispatch = patched
    page.send("Fetch.enable", {"patterns": [{"urlPattern": "*tcloudbasegateway.com*",
                                             "requestStage": "Request"}]})
    return state


INIT_JS = r"""
(function(){
  window.__errs=[]; window.__cerrs=[]; window.__net=[];
  window.addEventListener("error",function(e){
    window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
  window.addEventListener("unhandledrejection",function(e){
    var r=e&&e.reason; window.__errs.push("rejection:"+String((r&&r.message)||r));});
  try{
    var _ce=console.error;
    console.error=function(){
      try{window.__cerrs.push(Array.prototype.map.call(arguments,function(x){
        try{return String(x);}catch(e){return "?";}}).join(" "));}catch(e){}
      try{_ce.apply(console,arguments);}catch(e){}
    };
  }catch(e){}
  try{
    localStorage.setItem("zq_class_identity",JSON.stringify({
      token:"__TOKEN__",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));
    localStorage.setItem("zq_tools_v2___SID__",JSON.stringify({
      homeTools:["ppt","draw","hw","nt"],termStart:"2026-09-07"}));
    sessionStorage.removeItem("zq_pos_v1");
  }catch(e){}
  window.confirm=function(){return true;};
  /* 记录 mock 路径的请求体（CDP Fetch 负责返回，页面侧只旁路记录，不参与 mock） */
  try{
    var of=window.fetch;
    window.fetch=function(u,o){
      o=o||{};
      var s=String((u&&u.url!==undefined)?u.url:u);
      var m=String(o.method||"GET").toUpperCase();
      try{
        if(s.indexOf("ppt_decks")>=0||s.indexOf("ppt_upload_chunks")>=0||s.indexOf("site_assets")>=0){
          var b=String(o.body||""), rec={m:m,url:s};
          try{
            var arr=JSON.parse(b||"[]");
            if(s.indexOf("ppt_upload_chunks")>=0){
              var r=(arr instanceof Array&&arr[0])||{};
              var d=String(r.data||"");
              rec.chunk={deck_id:r.deck_id,idx:r.idx,owner_sid:r.owner_sid,data_len:d.length,
                b64:/^[A-Za-z0-9+/=]*$/.test(d),head:d.slice(0,12),tail:d.slice(-12)};
            }else if(s.indexOf("ppt_decks")>=0&&m==="POST"){
              rec.post=(arr instanceof Array&&arr[0])||null;
            }else if(s.indexOf("ppt_decks")>=0&&m==="PATCH"){
              rec.patch=(arr instanceof Array)?arr[0]:arr;
              rec.qid=(s.match(/id=eq\.([^&]+)/)||[])[1]||"";
            }
          }catch(e){rec.parse_err=String(e);}
          window.__net.push(rec);
        }
      }catch(e){}
      return of.apply(this,arguments);
    };
  }catch(e){}
})();
"""


def build_init():
    return (INIT_JS.replace("__TOKEN__", TOKEN).replace("__SID__", SID).replace("__NAME__", NAME))


class Server(object):
    def __init__(self):
        self.port = None
        self.httpd = None

    def start(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()

        class H(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def end_headers(self):
                self.send_header("Cache-Control", "no-store")
                http.server.SimpleHTTPRequestHandler.end_headers(self)

        class S(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass

        handler = functools.partial(H, directory=TOOLS)
        self.httpd = S(("127.0.0.1", self.port), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        time.sleep(0.2)

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            try:
                self.httpd.server_close()
            except Exception:
                pass

    def app_url(self):
        return "http://127.0.0.1:%d/index.html" % self.port


# ---------------------------------------------------------------- 断言与工具
class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, name, ok, note=""):
        ok = bool(ok)
        self.rows.append({"k": name, "ok": ok, "note": str(note)[:500]})
        print(("[PASS] " if ok else "[FAIL] ") + name + (("  | " + str(note)[:280]) if (note or not ok) else ""))
        return ok

    def summary(self):
        p = sum(1 for r in self.rows if r["ok"])
        return len(self.rows), p, len(self.rows) - p


R = Results()


def wait_js(page, expr, timeout=8.0, interval=0.1):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if page.evaluate(expr):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def js(page, expr, await_promise=False):
    return page.evaluate(expr, await_promise=await_promise)


def shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    return page.screenshot(os.path.join(SHOTS, name + ".png"))


def press(page, key, code=None, vk=None):
    p = {"key": key, "code": code or key, "windowsVirtualKeyCode": vk or 0,
         "nativeVirtualKeyCode": vk or 0}
    page.send("Input.dispatchKeyEvent", dict({"type": "keyDown"}, **p))
    page.send("Input.dispatchKeyEvent", dict({"type": "keyUp"}, **p))


def mouse_drag(page, x1, y1, x2, y2, steps=8):
    page.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x1, "y": y1,
                                           "button": "left", "clickCount": 1})
    for i in range(1, steps + 1):
        t = float(i) / steps
        page.send("Input.dispatchMouseEvent", {"type": "mouseMoved",
                                               "x": x1 + (x2 - x1) * t, "y": y1 + (y2 - y1) * t,
                                               "button": "left"})
        time.sleep(0.012)
    page.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x2, "y": y2,
                                           "button": "left", "clickCount": 1})


def active_img_src(page):
    return js(page, "(function(){var ls=[].slice.call(document.querySelectorAll('#pptPlayer .ppt-layer'));"
                    "for(var i=0;i<ls.length;i++){if(ls[i].style.visibility!=='hidden'){"
                    "var im=ls[i].querySelector('img');return im?(im.getAttribute('src')||''):'';}}"
                    "return '';})()") or ""


def player_idx(page):
    return js(page, "(function(){var e=document.getElementById('pptIdx');return e?e.textContent:'';})()") or ""


def open_detail(page, deck_id):
    """v2.0：点击列表卡片 = 打开下载详情（懒拉 manifest）。"""
    ok = js(page, "(function(){var c=document.querySelector('#pptList [data-deck=\"%s\"] .ppt-bd');"
                  "if(!c)return false;c.click();return true;})()" % deck_id)
    if not ok:
        return False
    return wait_js(page, "(function(){var d=document.getElementById('pptDl');"
                         "return !!d&&!d.hidden;})()", 6)


def close_detail(page):
    js(page, "(function(){var b=document.querySelector('#pptDl [data-dlact=\"close\"]');"
             "if(b)b.click();return true;})()")
    time.sleep(0.25)


def open_player(page, deck_id="dtestready1"):
    """v2.0：点击卡片 → 下载详情 → 「在线预览」进入旧播放器（原播放器覆盖不变）。"""
    if not open_detail(page, deck_id):
        return False
    if not wait_js(page, "!!document.querySelector('#pptDl [data-dlact=\"preview\"]')", 8):
        return False
    js(page, "(function(){var b=document.querySelector('#pptDl [data-dlact=\"preview\"]');"
             "if(b)b.click();return true;})()")
    return wait_js(page, "!!document.getElementById('pptPlayer')", 6)


def close_player(page):
    js(page, "(function(){try{window.PPT&&window.PPT.open&&0;}catch(e){}return true;})()")
    js(page, "(function(){var b=document.querySelector('#pptPlayer [data-act=\"close\"]');"
             "if(b)b.click();return true;})()")
    time.sleep(0.35)


def top_tab(page):
    return js(page, "(function(){var s=document.querySelector('section.on');"
                    "return s?s.id:'';})()") or ""


# ---------------------------------------------------------------- 静态检查
def static_checks():
    try:
        html = open(SRC, encoding="utf-8", newline="").read()
    except Exception as e:  # noqa: BLE001
        R.add("静态：能读取 index.html", False, repr(e))
        return
    flat = re.sub(r"\s+", "", html)
    m = re.search(r'var TOOLS=\[(.*?)\];', html, re.S)
    tools = m.group(1) if m else ""
    R.add("静态：TOOLS 追加 {k:\"ppt\",n:\"演示\",d:...}",
          '{k:"ppt",n:"演示",d:"PPT上传自动转换·分步+视频·任意设备流畅播放"}' in re.sub(r"\s+", "", tools),
          tools[-90:])
    R.add("静态：#s-ppt section 存在且与 TOOLS 对应",
          'id="s-ppt"' in html and "gotoTab" in html and 'k==="ppt"' in flat)
    R.add("静态：APP_VER 仍为 2.0.0", 'varAPP_VER="2.0.0"' in flat)
    R.add("静态：功能块标记 __PPT_FEATURE_V1__（CSS+JS 各一）",
          html.count("__PPT_FEATURE_V1__") == 2, html.count("__PPT_FEATURE_V1__"))
    R.add("静态：分片 512KiB / 并行 ≤4 / 重试 2 次 / 上限 60MiB",
          "512*1024" in flat and "PARALLEL=4" in flat and "RETRY_MS=[400,1200]" in flat
          and "60*1024*1024" in flat)
    R.add("静态：轮询 10s / 心跳 180s 离线阈值",
          "POLL_MS=10000" in flat and "OFFLINE_MS=180000" in flat)
    R.add("静态：转场集合 none/fade/push/wipe/zoom/cover",
          all(('"%s"' % t) in flat for t in ("fade", "push", "wipe", "zoom", "cover", "none"))
          and "TR_DUR={" in flat)
    R.add("静态：上传只接受 .ppt/.pptx（accept 属性 + 扩展名校验）",
          'accept=".ppt,.pptx"' in html and "/\\.pptx?$/i" in js_static(html))
    R.add("静态：播放器 position:fixed / z-index:110 / 独立 section 不存在滚动",
          ".ppt-player{position:fixed" in flat.replace("\r\n", "") or
          "position:fixed;top:0;right:0;bottom:0;left:0;z-index:110" in flat, "")
    R.add("静态：键盘 Esc/F/N/S/T/B 与 全屏 Fullscreen API",
          "requestFullscreen" in flat and 'k==="Escape"' in flat and
          all(('"%s"' % k) in flat for k in ("f", "n", "t", "b")) and
          "(k===\"b\"||k===\"B\"||k===\".\")" in flat)
    R.add("静态：退出确认站内样式（退出演示？/继续/退出，无浏览器原生 confirm）",
          "退出演示？" in html and 'data-act="stay"' in html and 'data-act="leave"' in html)
    R.add("静态：状态/空态文案与 DESIGN §4.8 一致",
          all(t in html for t in ("排队转换", "转换机离线 · 排队中", "转换中 ", "转换失败",
                                  "上传 ", "上传中 · 勿退出", "已取消", "还没有演示文件",
                                  "本页无备注", "还没转换完成", "图片加载失败 · 重试",
                                  "视频不可用")))
    R.add("静态：无外部脚本/字体/CDN（零依赖）",
          "<script src=" not in html and "fonts.googleapis" not in html and "cdn." not in html)
    R.add("静态：不新增任何密钥（无 OSS 写凭据 / 无 AccessKey）",
          "AccessKey" not in html and "LTAI" not in html)
    R.add("静态：播放器宿主元素不参与站点滑动（resolveStart 排除 #pptPlayer）",
          'closest(t,"#pptPlayer")' in flat)
    # v2.0 下载中心（契约 §12.4.1）：点击卡片=下载详情、三行文件下载、兼容提示、旧 deck 三态
    R.add("静态：v2.0 下载中心块标记 __PPT_DL_V1__（CSS+JS）",
          html.count("__PPT_DL_V1__") >= 2, html.count("__PPT_DL_V1__"))
    R.add("静态：列表无列表级播放按钮（点击卡片=下载详情）",
          'data-act="play"' not in html and "data-dlact=\"preview\"" in html)
    R.add("静态：详情三行下载（兼容版/PDF/原始）+ <a download> + 文件元数据来自 manifest.files",
          all(('fileRow("%s"' % k) in html for k in ("compat", "pdf", "source"))
          and 'download="' in flat and "manifest->files" in flat and "兼容提示" in html)
    R.add("静态：旧 deck 详情三态文案（兼容版未生成 / 在线预览 / 重新处理）",
          all(t in html for t in ("兼容版未生成", "在线预览", "重新处理")))


def js_static(html):
    m = re.search(r"<script>(.*?)</script>", html, re.S)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- 会话
class Session(object):
    def __init__(self, server, width=430, height=900, mobile=True):
        self.server = server
        self.width = width
        self.height = height
        self.browser = _cdp.Browser(
            extra_flags=["--disable-web-security", "--allow-running-insecure-content",
                         "--autoplay-policy=no-user-gesture-required"],
            window=(width, height))
        try:
            self.page = self.browser.new_page("about:blank")
            self.page.set_device(width, height, dpr=2.0, mobile=mobile, touch=mobile)
            self.mock = install_cdp_mock(self.page)
            self.page.add_init_script(build_init())
            self.page.navigate(server.app_url())
            self.page.wait_load(timeout=25)
            if not wait_js(self.page, "(function(){return !document.body.classList.contains('id-locked')"
                                      "&&!!document.querySelector('#tabsBar button[data-tab]');})()", 25):
                raise RuntimeError("页面未进入身份后状态（身份门禁未解除 / tabsBar 未渲染）")
            time.sleep(0.6)
        except Exception:
            self.close()
            raise

    def js(self, expr, await_promise=False):
        return js(self.page, expr, await_promise)

    def wait(self, expr, timeout=8.0):
        return wait_js(self.page, expr, timeout)

    def sleep(self, s):
        time.sleep(s)

    def shot(self, name):
        return shot(self.page, name)

    def errors(self):
        return {
            "js_errs": self.js("window.__errs||[]") or [],
            "console_errs": self.js("window.__cerrs||[]") or [],
            "cdp_exc": self.page.exceptions(),
            "cdp_console": self.page.console_errors(),
        }

    def close(self):
        try:
            self.page.close()
        except Exception:
            pass
        try:
            self.browser.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 场景
def scenario_main(sess):
    page = sess.page
    # ---- B1 工具栏 + 全部页入口
    R.add("工具栏：投放到首页槽位后出现「演示」tab",
          js(page, "(function(){var b=document.querySelector('#tabsBar button[data-tab=\"ppt\"]');"
                   "return b?b.textContent:'';})()") == "演示")
    js(page, "(function(){var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');"
             "if(b)b.click();return true;})()")
    sess.sleep(0.45)
    card = js(page, "(function(){var c=document.querySelector('#allCards [data-card=\"ppt\"]');"
                    "if(!c)return null;return {n:c.querySelector('.hd span')?c.querySelector('.hd span').textContent:'',"
                    "d:c.querySelector('.tdesc')?c.querySelector('.tdesc').textContent:''};})()")
    R.add("全部页：出现「演示」卡片（名称/描述自动收录）",
          bool(card) and card.get("n") == "演示" and "PPT" in str(card.get("d")),
          json.dumps(card, ensure_ascii=False))
    js(page, "(function(){var b=document.querySelector('#allCards [data-open=\"ppt\"]');"
             "if(b)b.click();return true;})()")
    sess.sleep(0.5)
    R.add("全部页：点卡片进入 #s-ppt", top_tab(page) == "s-ppt")

    # ---- B2 列表渲染
    ok = sess.wait("(function(){return document.querySelectorAll('#pptList .ppt-card').length>=5;})()", 10)
    R.add("列表：fixture 5 张卡片渲染（别人 uploading 被隐藏）", ok,
          "cards=%s" % js(page, "document.querySelectorAll('#pptList .ppt-card').length"))
    texts = js(page, "(function(){return document.getElementById('pptList').innerText||'';})()") or ""
    R.add("列表：状态文案 上传 34% / 排队转换 / 转换中 61% / 转换失败+error",
          ("上传 34%" in texts) and ("排队转换" in texts) and ("转换中 61%" in texts)
          and ("转换失败" in texts) and ("转换超时" in texts), texts.replace("\n", " ")[:220])
    R.add("列表：别人 uploading 的行不显示",
          "别人上传中" not in texts)
    ready_card = js(page, "(function(){var c=document.querySelector('#pptList [data-deck=\"dtestready1\"]');"
                          "if(!c)return null;return {chip:!!c.querySelector('.ppt-st'),"
                          "play:!!c.querySelector('[data-act=\"play\"]'),"
                          "cvplay:!!c.querySelector('.ppt-cvplay'),"
                          "meta:c.querySelector('.ppt-meta')?c.querySelector('.ppt-meta').textContent:''};})()")
    R.add("列表：ready 不显示状态胶囊（页数/大小/上传者）+ 无列表播放按钮（v2.0 点击卡片=下载详情）",
          bool(ready_card) and not ready_card.get("chip") and not ready_card.get("play")
          and not ready_card.get("cvplay") and "3 页" in str(ready_card.get("meta")),
          json.dumps(ready_card, ensure_ascii=False))
    # v2.0：点击卡片 = 下载详情（旧 deck → 兼容版未生成 + 在线预览 + 重新处理 + 原始文件）
    det_open = open_detail(page, "dtestready1")
    sess.sleep(0.4)
    dstate = js(page, r"""
(function(){
  var o=document.getElementById('pptDl');
  if(!o||o.hidden)return null;
  var body=document.getElementById('pptDlBody');
  return {open:!o.hidden,txt:body?body.innerText:'',
    preview:!!o.querySelector('[data-dlact="preview"]'),
    retry:!!o.querySelector('[data-dlact="retry"]'),
    source:o.querySelectorAll('.ppt-file-source a[download]').length,
    files:o.querySelectorAll('.ppt-file').length,
    player:!!document.getElementById('pptPlayer')};
})()
""")
    R.add("详情：点击卡片 → 下载详情（懒拉 manifest，不直接进播放器）",
          det_open and bool(dstate) and dstate.get("open") and not dstate.get("player"),
          json.dumps(dstate, ensure_ascii=False)[:240])
    R.add("详情：旧 deck（无 files）「兼容版未生成」+「在线预览」+「重新处理」+ 原始文件下载",
          bool(dstate) and "兼容版未生成" in str(dstate.get("txt") or "")
          and dstate.get("preview") and dstate.get("retry") and dstate.get("source") == 1,
          json.dumps({k: (dstate or {}).get(k) for k in ("preview", "retry", "source", "files")},
                     ensure_ascii=False))
    close_detail(page)
    sess.sleep(0.25)
    cover_lazy = js(page, "(function(){var c=document.querySelector('#pptList [data-deck=\"dtestready1\"] img');"
                          "return c?{lazy:c.getAttribute('loading'),src:(c.getAttribute('src')||'').slice(0,16)}:null;})()")
    R.add("列表：封面图懒加载（loading=lazy）", bool(cover_lazy) and cover_lazy.get("lazy") == "lazy",
          json.dumps(cover_lazy, ensure_ascii=False))
    mine_fail = js(page, "(function(){var c=document.querySelector('#pptList [data-deck=\"dtestfail1\"]');"
                         "if(!c)return null;return {retry:!!c.querySelector('[data-act=\"retry\"]'),"
                         "del:!!c.querySelector('[data-act=\"del\"]')};})()")
    R.add("列表：本人失败卡片有「重试 / 删除」", bool(mine_fail) and mine_fail.get("retry") and mine_fail.get("del"),
          json.dumps(mine_fail, ensure_ascii=False))
    order = js(page, "[].map.call(document.querySelectorAll('#pptList .ppt-card'),function(c){"
                     "return c.getAttribute('data-deck');})")
    R.add("列表：本人进行中置顶（rank=0 在首位）",
          bool(order) and order[0] in ("dtestup01", "dtestqueue1", "dtestproc1"), json.dumps(order))
    layout = js(page, "(function(){return {sw:document.documentElement.scrollWidth,vw:innerWidth};})()")
    R.add("布局 430px：列表无横向溢出",
          bool(layout) and layout.get("sw", 9999) <= layout.get("vw", 0) + 1, json.dumps(layout))
    shot(page, "01_list_430")

    # ---- B3 离线提示（seen_at > 180s）
    with MOCK_LOCK:
        MOCK["agent"]["seen_at"] = NOW - 400000
    js(page, "window.PPT.pull()", await_promise=True)
    sess.sleep(0.3)
    stat = js(page, "(function(){var e=document.getElementById('pptStat');"
                    "return {hidden:!e||e.hidden,txt:e?e.textContent:''};})()")
    chip_off = js(page, "(function(){var c=document.querySelector('#pptList [data-deck=\"dtestqueue1\"] .ppt-st');"
                        "return c?c.textContent:'';})()")
    R.add("列表：转换机离线提示「转换机离线 · 排队中」（seen_at>180s）",
          bool(stat) and not stat.get("hidden") and "转换机离线 · 排队中" in str(stat.get("txt")),
          json.dumps(stat, ensure_ascii=False))
    R.add("列表：排队中卡片在离线时显示「转换机离线 · 排队中」", "转换机离线" in str(chip_off), chip_off)
    shot(page, "02_offline")
    with MOCK_LOCK:
        MOCK["agent"]["seen_at"] = NOW
    js(page, "window.PPT.pull()", await_promise=True)
    sess.sleep(0.25)

    # ---- C 上传 mock 流程（512KiB File 注入 → mock 201 → 进度 → PATCH queued）
    prep = js(page, r"""
(function(){
  var inp=document.getElementById('pptFile');
  if(!inp)return {err:"no input"};
  var n=524288, bytes=new Uint8Array(n);
  for(var i=0;i<n;i++)bytes[i]=i%251;
  var f=new File([bytes],"测试演示.pptx",{type:"application/vnd.openxmlformats-officedocument.presentationml.presentation"});
  var dt=new DataTransfer(); dt.items.add(f);
  inp.files=dt.files;
  inp.dispatchEvent(new Event("change",{bubbles:true}));
  return {size:f.size,name:f.name,panel:!document.getElementById('pptUpBox').hidden,
          title:document.getElementById('pptUpName').value};
})()
""")
    R.add("上传：选文件后显示标题面板（默认=文件名去扩展名）",
          bool(prep) and prep.get("panel") and prep.get("title") == "测试演示"
          and prep.get("size") == 524288, json.dumps(prep, ensure_ascii=False))
    js(page, "(function(){document.getElementById('pptUpGo').click();return true;})()")
    ok = sess.wait("(function(){var n=window.__net||[];"
                   "return !!(n.filter(function(r){return r.m==='POST'&&r.url.indexOf('ppt_decks')>=0&&r.post;}).length"
                   "&&n.filter(function(r){return r.chunk;}).length"
                   "&&n.filter(function(r){return r.patch&&r.patch.status==='queued';}).length);})()", 15)
    net = js(page, "window.__net||[]") or []
    posts = [r for r in net if r.get("m") == "POST" and "ppt_decks" in r.get("url", "") and r.get("post")]
    chunks = [r["chunk"] for r in net if r.get("chunk")]
    patches = [r for r in net if r.get("patch")]
    queued = [p for p in patches if str(p["patch"].get("status")) == "queued"]
    with MOCK_LOCK:
        posted_decks = list(MOCK["posts"])
    created = posted_decks[-1] if posted_decks else {}
    R.add("上传：先 POST ppt_decks 建行（uploading/owner_sid=本人/chunk_count=1/60MiB 内）",
          bool(posts) and created.get("status") == "uploading"
          and created.get("owner_sid") == SID and created.get("chunk_count") == 1
          and created.get("client") == "web" and created.get("source_size") == 524288,
          json.dumps({k: created.get(k) for k in ("id", "status", "owner_sid", "chunk_count", "source_size", "client")},
                     ensure_ascii=False))
    R.add("上传：分片 POST /ppt_upload_chunks（512KiB→base64，idx=0，owner_sid=本人）",
          len(chunks) == 1 and chunks[0].get("idx") == 0 and chunks[0].get("owner_sid") == SID
          and chunks[0].get("data_len", 0) == 699052 and chunks[0].get("b64") is True,
          json.dumps(chunks[0] if chunks else {}, ensure_ascii=False))
    with MOCK_LOCK:
        srv_chunks = list(MOCK["chunks"])
    R.add("上传：分片 base64 解码后字节数 = 524288（真实切片）",
          bool(srv_chunks) and srv_chunks[0].get("decode_len") == 524288,
          (srv_chunks[0] or {}).get("decode_len"))
    R.add("上传：完成后 PATCH status=queued + chunk_count + source_size",
          bool(queued) and queued[-1]["patch"].get("chunk_count") == 1
          and queued[-1]["patch"].get("source_size") == 524288,
          json.dumps((queued[-1]["patch"] if queued else {}), ensure_ascii=False)[:240])
    R.add("上传：进度文案到达「上传 100%」",
          js(page, "(function(){var e=document.getElementById('pptUpLabel');"
                   "return e?e.textContent:'';})()") == "上传 100%",
          js(page, "(function(){var e=document.getElementById('pptUpLabel');return e?e.textContent:'';})()"))
    R.add("上传：成功后上传面板关闭 + 列表出现「排队转换」卡片",
          js(page, "(function(){return document.getElementById('pptUpBox').hidden;})()")
          and "排队转换" in (js(page, "(function(){return document.getElementById('pptList').innerText||'';})()") or ""))
    shot(page, "03_uploaded")

    # ---- D 播放器
    with MOCK_LOCK:
        MOCK["agent"]["seen_at"] = NOW
    ok = open_player(page)
    R.add("播放器：详情「在线预览」打开 #pptPlayer（v2.0 旧播放器入口保留）", ok)
    if not ok:
        return
    sess.sleep(0.7)

    st = js(page, r"""
(function(){
  var p=document.getElementById('pptPlayer');
  if(!p)return null;
  var cs=getComputedStyle(p), stage=document.getElementById('pptStage');
  return {pos:cs.position,z:cs.zIndex,bg:stage?getComputedStyle(stage).backgroundColor:'',
          lock:document.body.classList.contains('ppt-lock'),
          ctl:!!document.querySelector('#pptCtl [data-act="prev"]')&&
              !!document.querySelector('#pptCtl [data-act="next"]')&&
              !!document.querySelector('#pptCtl [data-act="thumbs"]')&&
              !!document.querySelector('#pptCtl [data-act="notes"]')&&
              !!document.querySelector('#pptCtl [data-act="close"]')&&
              !!document.querySelector('#pptCtl [data-act="fs"]')&&
              !!document.querySelector('#pptCtl [data-act="black"]'),
          dl:!!document.querySelector('#pptCtl [data-act="dl"]')&&
             !document.querySelector('#pptCtl [data-act="dl"]').hidden,
          idx:document.getElementById('pptIdx')?document.getElementById('pptIdx').textContent:'',
          dots:document.querySelectorAll('#pptDots i').length,
          dotOn:document.querySelectorAll('#pptDots i.on').length,
          prog:document.getElementById('pptProg')?document.getElementById('pptProg').style.width:'',
          name:document.getElementById('pptName')?document.getElementById('pptName').textContent:'',
          ctlH:document.getElementById('pptCtl')?getComputedStyle(document.getElementById('pptCtl')).height:'',
          ctlRows:(function(){var c=document.getElementById('pptCtl');if(!c)return -1;
            var mids={},n=0,ch=c.children;
            for(var i=0;i<ch.length;i++){var r=ch[i].getBoundingClientRect();
              var m=Math.round(r.top+r.height/2);if(!mids[m]){mids[m]=1;n++;}}
            return n;})()};
})()
""")
    R.add("播放器：position:fixed + z-index 110 + 锁定 body 滚动",
          bool(st) and st.get("pos") == "fixed" and st.get("z") == "110" and st.get("lock"),
          json.dumps({k: st.get(k) for k in ("pos", "z", "lock")} if st else {}, ensure_ascii=False))
    R.add("播放器：纯黑舞台（background rgb(0, 0, 0)）", bool(st) and st.get("bg") == "rgb(0, 0, 0)",
          (st or {}).get("bg"))
    R.add("播放器：控制条含 上一/下一/缩略图/备注/黑屏/全屏/关闭 且单行（桌面 52 / 手机 48）",
          bool(st) and st.get("ctl") and st.get("ctlH") in ("52px", "48px") and st.get("ctlRows") == 1,
          json.dumps({k: (st or {}).get(k) for k in ("ctl", "ctlH", "ctlRows")}, ensure_ascii=False))
    R.add("播放器：有 src 时显示「下载原件」", bool(st) and st.get("dl"))
    R.add("播放器：页码按「页」+ 页内步点（第 1 页 2 步 → 2 个点）",
          bool(st) and st.get("idx") == "1 / 3 · 1/2" and st.get("dots") == 2 and st.get("dotOn") == 1,
          json.dumps({k: (st or {}).get(k) for k in ("idx", "dots", "dotOn")}, ensure_ascii=False))
    R.add("播放器：顶部进度条按 step 推进（1/4 → 25%）",
          bool(st) and abs(float(str(st.get("prog") or "0").replace("%", "")) - 25.0) < 1.5,
          (st or {}).get("prog"))
    R.add("播放器：左上文件名 = 卡片标题，3s 后淡出",
          bool(st) and st.get("name") == "班会演示"
          and sess.wait("(function(){var n=document.getElementById('pptName');"
                        "return !!n&&n.classList.contains('out');})()", 5),
          (st or {}).get("name"))
    R.add("播放器：首帧加载 steps[0].img（data: 假图）", active_img_src(page) == IMG1,
          (active_img_src(page)[:40]))
    shot(page, "04_player_page1")

    # 控制条自动隐藏（3s）+ 移动唤出
    hid = sess.wait("(function(){var c=document.getElementById('pptCtl');"
                    "return !!c&&c.classList.contains('hide');})()", 6)
    R.add("播放器：控制条 3s 无操作自动隐藏", hid)
    page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": sess.width // 2, "y": sess.height // 2})
    sess.sleep(0.25)
    R.add("播放器：鼠标移动唤出控制条",
          js(page, "(function(){var c=document.getElementById('pptCtl');"
                   "return !!c&&!c.classList.contains('hide');})()"))

    # 点击右 2/3 前进一个 step；再前进到第 2 页；左 1/3 后退一个 step
    page.click(int(sess.width * 0.90), int(sess.height * 0.45))
    sess.sleep(0.45)
    R.add("播放器：点击右 2/3 → 下一步（页内 step 2/2）", player_idx(page) == "1 / 3 · 2/2", player_idx(page))
    R.add("播放器：页内切步后图片为 steps[1].img", active_img_src(page) == IMG2, active_img_src(page)[:40])
    page.click(int(sess.width * 0.90), int(sess.height * 0.45))
    sess.sleep(0.6)
    R.add("播放器：再点右 2/3 → 下一页（2 / 3）", player_idx(page) == "2 / 3", player_idx(page))
    page.click(int(sess.width * 0.08), int(sess.height * 0.45))
    sess.sleep(0.6)
    R.add("播放器：点击左 1/3 → 上一步（后退粒度=step，回到上页末步 1 / 3 · 2/2）",
          player_idx(page) == "1 / 3 · 2/2", player_idx(page))

    # 键盘
    # 注：v1.2 起跨页转场按 manifest.trd（本 fixture 450ms）执行，固定的 0.5s 睡眠只有 10ms 余量，
    # 负载高时 idx 更新会晚于断言；这里改为「等 idx 到达目标值（≤2s）」的等价断言，语义不变、消除抖动。
    press(page, "ArrowRight", "ArrowRight", 39)
    sess.wait("(function(){return (document.getElementById('pptIdx')||{}).textContent==='2 / 3';})()", 2)
    R.add("播放器：键盘 → 下一步", player_idx(page) == "2 / 3", player_idx(page))
    press(page, "ArrowLeft", "ArrowLeft", 37)
    sess.wait("(function(){return (document.getElementById('pptIdx')||{}).textContent==='1 / 3 · 2/2';})()", 2)
    R.add("播放器：键盘 ← 上一步（step 粒度）", player_idx(page) == "1 / 3 · 2/2", player_idx(page))
    press(page, " ", "Space", 32)
    sess.wait("(function(){return (document.getElementById('pptIdx')||{}).textContent==='2 / 3';})()", 2)
    R.add("播放器：键盘 Space 下一步", player_idx(page) == "2 / 3", player_idx(page))
    press(page, "ArrowLeft", "ArrowLeft", 37)
    sess.wait("(function(){return (document.getElementById('pptIdx')||{}).textContent==='1 / 3 · 2/2';})()", 2)
    R.add("播放器：键盘 PageUp/← 后退可用（→← 已经覆盖，此处回到上页末步）",
          player_idx(page) == "1 / 3 · 2/2", player_idx(page))

    # 鼠标拖（pointer 手势）+ 触摸滑：切页且不改变 top tab
    before_tab = top_tab(page)
    mouse_drag(page, int(sess.width * 0.85), int(sess.height * 0.5),
               int(sess.width * 0.15), int(sess.height * 0.5))
    sess.sleep(0.6)
    R.add("播放器：鼠标左右拖 → 切换（下一页 2 / 3）", player_idx(page) == "2 / 3", player_idx(page))
    R.add("播放器：鼠标拖后 top tab 仍为 #s-ppt（不切工具）", top_tab(page) == before_tab == "s-ppt",
          "%s/%s" % (before_tab, top_tab(page)))
    page.touch_swipe(int(sess.width * 0.85), int(sess.height * 0.5),
                     int(sess.width * 0.15), int(sess.height * 0.5), steps=12, gap=0.013)
    sess.sleep(0.7)
    R.add("播放器：触摸左滑 → 下一页（3 / 3）", player_idx(page) == "3 / 3", player_idx(page))
    R.add("播放器：触摸滑动后 top tab 仍为 #s-ppt（站点切工具逻辑被阻止）",
          top_tab(page) == "s-ppt", top_tab(page))
    shot(page, "05_player_page3")

    # 缩略图抽屉
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"thumbs\"]').click();return true;})()")
    sess.sleep(0.4)
    th = js(page, r"""
(function(){
  var d=document.getElementById('pptThumbs');
  return {on:!!d&&d.classList.contains('on'),
          n:document.querySelectorAll('#pptThumbsRow .ppt-thumb').length,
          cur:document.querySelectorAll('#pptThumbsRow .ppt-thumb.on').length};
})()
""")
    R.add("播放器：缩略图抽屉打开（3 页，当前页高亮）",
          bool(th) and th.get("on") and th.get("n") == 3 and th.get("cur") == 1,
          json.dumps(th, ensure_ascii=False))
    shot(page, "06_player_thumbs")
    js(page, "(function(){var b=document.querySelectorAll('#pptThumbsRow .ppt-thumb')[1];"
             "if(b)b.click();return true;})()")
    sess.sleep(0.6)
    R.add("播放器：点缩略图跳页（第 2 页 → 2 / 3）", player_idx(page) == "2 / 3", player_idx(page))
    R.add("播放器：跳页后抽屉自动收起",
          js(page, "(function(){var d=document.getElementById('pptThumbs');return !d||!d.classList.contains('on');})()"))

    # 备注抽屉
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"notes\"]').click();return true;})()")
    sess.sleep(0.35)
    nt = js(page, "(function(){var d=document.getElementById('pptNotes');"
                  "return {on:!!d&&d.classList.contains('on'),"
                  "txt:document.getElementById('pptNoteBody')?document.getElementById('pptNoteBody').textContent:''};})()")
    R.add("播放器：第 2 页无备注 → 备注抽屉显示「本页无备注」",
          bool(nt) and nt.get("on") and nt.get("txt") == "本页无备注", json.dumps(nt, ensure_ascii=False))
    shot(page, "07_player_notes")
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"notes\"]').click();return true;})()")
    sess.sleep(0.2)
    js(page, "(function(){var b=document.querySelectorAll('#pptThumbsRow .ppt-thumb');return true;})()")
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"thumbs\"]').click();return true;})()")
    sess.sleep(0.3)
    js(page, "(function(){var b=document.querySelectorAll('#pptThumbsRow .ppt-thumb')[0];if(b)b.click();return true;})()")
    sess.sleep(0.6)
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"notes\"]').click();return true;})()")
    sess.sleep(0.3)
    nt1 = js(page, "(function(){var e=document.getElementById('pptNoteBody');return e?e.textContent:'';})()")
    R.add("播放器：第 1 页备注抽屉显示 notes 原文", "第一页备注" in str(nt1), nt1)
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"notes\"]').click();return true;})()")
    sess.sleep(0.2)

    # 黑屏 B（任意键恢复）
    press(page, "b", "KeyB", 66)
    sess.sleep(0.25)
    black = js(page, "(function(){var b=document.getElementById('pptBlack');return !!b&&!b.hidden;})()")
    R.add("播放器：B 键黑屏", black)
    press(page, "x", "KeyX", 88)
    sess.sleep(0.2)
    R.add("播放器：任意键恢复黑屏（恢复不显示 UI）",
          js(page, "(function(){var b=document.getElementById('pptBlack');"
                   "return !!b&&b.hidden;})()"))
    R.add("播放器：全屏按钮存在（Fullscreen API）",
          js(page, "(function(){var b=document.querySelector('#pptCtl [data-act=\"fs\"]');"
                   "return !!b&&typeof document.getElementById('pptPlayer').requestFullscreen==='function';})()"))

    # 视频热点（第 2 页）
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"thumbs\"]').click();return true;})()")
    sess.sleep(0.3)
    js(page, "(function(){var b=document.querySelectorAll('#pptThumbsRow .ppt-thumb')[1];if(b)b.click();return true;})()")
    sess.sleep(0.6)
    hot = js(page, r"""
(function(){
  var hs=document.querySelectorAll('#pptHot .ppt-hotbtn');
  var v=null; for(var i=0;i<hs.length;i++)if(hs[i].classList.contains('v'))v=hs[i];
  if(!v)return {n:hs.length};
  var r=v.getBoundingClientRect();
  return {n:hs.length,v:1,x:r.left+r.width/2,y:r.top+r.height/2,
          dur:document.querySelector('#pptHot .ppt-hotdur')?document.querySelector('#pptHot .ppt-hotdur').textContent:''};
})()
""")
    R.add("播放器：视频热点出现（图片实际渲染区域内的圆钮 + 时长角标）",
          bool(hot) and hot.get("v") == 1 and "视频 0:12" in str(hot.get("dur")),
          json.dumps(hot, ensure_ascii=False))
    if hot and hot.get("v") == 1:
        page.click(int(hot["x"]), int(hot["y"]))
        sess.sleep(0.6)
        mv = js(page, "(function(){var o=document.getElementById('pptMediaOv');"
                      "if(!o)return null;var v=o.querySelector('video');"
                      "return {hidden:o.hidden,hasVideo:!!v,src:v?(v.getAttribute('src')||''):'',"
                      "preload:v?v.getAttribute('preload'):'',autoplay:v?!!v.autoplay:null};})()")
        R.add("播放器：点视频热点 → 打开媒体层（<video controls>，点击才 load/play、不自动播）",
              bool(mv) and not mv.get("hidden") and mv.get("hasVideo")
              and "video/mp4" in str(mv.get("src")) and mv.get("preload") == "none",
              json.dumps(mv, ensure_ascii=False))
        shot(page, "08_player_video")
        js(page, "(function(){var b=document.querySelector('#pptMediaOv .ppt-mclose');if(b)b.click();return true;})()")
        sess.sleep(0.3)
        R.add("播放器：关闭媒体层 → 回到当前步（媒体层卸载）",
              js(page, "(function(){var o=document.getElementById('pptMediaOv');"
                       "return !!o&&o.hidden&&!o.querySelector('video');})()"))

    # 退出确认（站内样式，不用原生 confirm）
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"thumbs\"]').click();return true;})()")
    sess.sleep(0.3)
    js(page, "(function(){var b=document.querySelectorAll('#pptThumbsRow .ppt-thumb')[0];if(b)b.click();return true;})()")
    sess.sleep(0.5)
    press(page, "Escape", "Escape", 27)
    sess.sleep(0.3)
    cf = js(page, "(function(){var c=document.getElementById('pptConfirm');"
                  "if(!c)return null;return {hidden:c.hidden,txt:c.textContent,"
                  "stay:!!c.querySelector('[data-act=\"stay\"]'),leave:!!c.querySelector('[data-act=\"leave\"]')};})()")
    R.add("播放器：有进度时 Esc → 站内退出确认「退出演示？/继续/退出」",
          bool(cf) and not cf.get("hidden") and "退出演示？" in str(cf.get("txt"))
          and cf.get("stay") and cf.get("leave"), json.dumps(cf, ensure_ascii=False))
    js(page, "(function(){document.querySelector('#pptConfirm [data-act=\"stay\"]').click();return true;})()")
    sess.sleep(0.25)
    R.add("播放器：点「继续」留在播放器",
          js(page, "(function(){var c=document.getElementById('pptConfirm');"
                   "return !!c&&c.hidden&&!!document.getElementById('pptPlayer');})()"))

    # 退出恢复 tab + 滚动位置
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"close\"]').click();return true;})()")
    sess.sleep(0.25)
    js(page, "(function(){document.querySelector('#pptConfirm [data-act=\"leave\"]').click();return true;})()")
    sess.sleep(0.4)
    R.add("播放器：退出后覆盖层移除 / body 解锁 / 恢复原 tab",
          js(page, "(function(){return !document.getElementById('pptPlayer')"
                   "&&!document.body.classList.contains('ppt-lock')"
                   "&&!!document.querySelector('#s-ppt.on');})()"), top_tab(page))
    # 打开前滚动位置记录 → 退出恢复
    js(page, "window.scrollTo(0, 60);")
    sess.sleep(0.2)
    js(page, "window.PPT.open('dtestready1');")
    sess.wait("!!document.getElementById('pptPlayer')", 6)
    sess.sleep(0.5)
    saved = js(page, "(function(){return Math.round(window.scrollY||0);})()")
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"close\"]').click();return true;})()")
    sess.sleep(0.25)
    js(page, "(function(){document.querySelector('#pptConfirm [data-act=\"leave\"]').click();return true;})()")
    sess.sleep(0.4)
    restored = js(page, "(function(){return Math.round(window.scrollY||0);})()")
    R.add("播放器：退出恢复打开前的滚动位置（±4px）", abs(int(restored) - int(saved)) <= 4,
          "saved=%s restored=%s" % (saved, restored))

    # 播放器布局无横向溢出（重开一次检查）
    js(page, "window.PPT.open('dtestready1');")
    sess.wait("!!document.getElementById('pptPlayer')", 6)
    sess.sleep(0.7)
    ply = js(page, r"""
(function(){
  var p=document.getElementById('pptPlayer'), c=document.getElementById('pptCtl');
  return {sw:document.documentElement.scrollWidth,vw:innerWidth,
          psw:p?p.scrollWidth:0,pcw:p?p.clientWidth:0,
          csw:c?c.scrollWidth:0,ccw:c?c.clientWidth:0};
})()
""")
    R.add("布局 430px：播放器无横向溢出（页面 scrollWidth ≤ 视口、控制条不溢出）",
          bool(ply) and ply.get("sw", 9999) <= ply.get("vw", 0) + 1
          and ply.get("psw", 9999) <= ply.get("pcw", 0) + 1
          and ply.get("csw", 9999) <= ply.get("ccw", 0) + 1, json.dumps(ply))
    shot(page, "09_player_430")
    js(page, "(function(){document.querySelector('#pptCtl [data-act=\"close\"]').click();return true;})()")
    sess.sleep(0.25)
    js(page, "(function(){var b=document.querySelector('#pptConfirm [data-act=\"leave\"]');if(b)b.click();"
             "else{document.querySelector('#pptCtl [data-act=\"close\"]');}return true;})()")
    sess.sleep(0.3)


def scenario_empty(server):
    with MOCK_LOCK:
        MOCK["decks"] = []
    sess = Session(server)
    try:
        js(sess.page, "window.PPT.pull()", await_promise=True)
        sess.sleep(0.4)
        em = js(sess.page, "(function(){var e=document.getElementById('pptEmpty');"
                           "return {hidden:!e||e.hidden,txt:e?e.textContent:''};})()")
        R.add("空态：列表为空时显示「还没有演示文件」+ 上传入口",
              bool(em) and not em.get("hidden") and "还没有演示文件" in str(em.get("txt"))
              and "上传 PPT" in str(em.get("txt")), json.dumps(em, ensure_ascii=False))
        shot(sess.page, "10_empty")
    finally:
        sess.close()


def scenario_offline(server):
    with MOCK_LOCK:
        MOCK["decks"] = [dict(d) for d in FIXTURE_DECKS]
        MOCK["agent"]["seen_at"] = NOW - 10 * 60000
    sess = Session(server)
    try:
        sess.wait("(function(){var s=document.getElementById('pptStat');"
                  "return !!s&&!s.hidden;})()", 8)
        stat = js(sess.page, "(function(){var e=document.getElementById('pptStat');"
                             "return e?e.textContent:'';})()")
        R.add("轮询：心跳 seen_at>180s → 首次列表加载即提示「转换机离线 · 排队中」",
              "转换机离线 · 排队中" in str(stat), stat)
        sess.shot("11_boot_offline")
    finally:
        sess.close()


BAD_MANIFEST = {
    "v": 1, "base": "", "src": "",
    "w": 1600, "h": 900,
    "slides": [
        {"tr": "fade", "trd": 300, "notes": "", "thumb": THUMB1,
         "steps": [{"img": IMG1, "media": []},
                   {"img": "https://bad.invalid/step2.webp", "media": []}]},
    ],
    "media": [],
}


def scenario_img_error(server):
    """图片加载失败：保留上一张图 + 「图片加载失败 · 重试」，不白屏、不阻塞翻页。"""
    with MOCK_LOCK:
        MOCK["decks"] = [deck(id="dbadimg1", title="坏图演示", manifest=BAD_MANIFEST,
                              slide_count=1, step_count=2, cover_url=THUMB1)]
    sess = Session(server)
    try:
        page = sess.page
        js(page, "window.PPT.open('dbadimg1');")
        if not sess.wait("!!document.getElementById('pptPlayer')", 8):
            R.add("坏图：播放器可打开", False)
            return
        sess.sleep(0.8)
        page.click(int(sess.width * 0.90), int(sess.height * 0.45))
        sess.sleep(1.4)
        st = js(page, r"""
(function(){
  var e=document.getElementById('pptImgErr');
  return {err:!!e&&!e.hidden, txt:e?e.textContent:'',
          idx:(document.getElementById('pptIdx')||{}).textContent,
          img:(function(){var ls=[].slice.call(document.querySelectorAll('#pptPlayer .ppt-layer'));
            for(var i=0;i<ls.length;i++){if(ls[i].style.visibility!=='hidden'){
              var im=ls[i].querySelector('img');return im?(im.getAttribute('src')||''):'';}}return '';})()};
})()
""")
        R.add("播放器：图片加载失败 → 提示「图片加载失败 · 重试」且保留上一张图（不白屏）",
              bool(st) and st.get("err") and "图片加载失败 · 重试" in str(st.get("txt"))
              and st.get("img") == IMG1, json.dumps(st, ensure_ascii=False)[:260])
        tgt = js(page, "(function(){var e=document.getElementById('pptImgErr');"
                       "if(!e)return null;var r=e.getBoundingClientRect();"
                       "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()")
        if tgt:
            page.click(int(tgt["x"]), int(tgt["y"]))
            sess.sleep(0.9)
        R.add("播放器：失败提示可点重试且不产生 JS 报错（重试仍失败也保留画面）",
              not (js(page, "window.__errs||[]") or []),
              json.dumps(js(page, "window.__errs||[]") or [], ensure_ascii=False)[:200])
        shot(page, "12_img_error")
    finally:
        sess.close()


def scenario_desktop(server):
    """≥960 桌面：列表多列、缩略图抽屉在左、备注抽屉在右、无横向溢出。"""
    with MOCK_LOCK:
        MOCK["decks"] = [dict(d) for d in FIXTURE_DECKS]
        MOCK["agent"]["seen_at"] = NOW
    sess = Session(server, width=1280, height=800, mobile=False)
    try:
        page = sess.page
        sess.wait("document.querySelectorAll('#pptList .ppt-card').length>=5", 10)
        sess.sleep(0.3)
        cards = js(page, r"""
(function(){
  var cs=[].slice.call(document.querySelectorAll('#pptList .ppt-card'));
  var a=cs[0]?cs[0].getBoundingClientRect():null, b=cs[1]?cs[1].getBoundingClientRect():null;
  return {n:cs.length, aTop:a?Math.round(a.top):null, bTop:b?Math.round(b.top):null,
          aLeft:a?Math.round(a.left):null, bLeft:b?Math.round(b.left):null,
          sw:document.documentElement.scrollWidth, vw:innerWidth};
})()
""")
        R.add("桌面 1280px：列表多列排布（前两张同排、左右并排）",
              bool(cards) and cards.get("n") >= 5 and cards.get("aTop") == cards.get("bTop")
              and cards.get("bLeft") > cards.get("aLeft"),
              json.dumps(cards, ensure_ascii=False))
        R.add("桌面 1280px：列表无横向溢出", cards.get("sw", 9999) <= cards.get("vw", 0) + 1)
        shot(page, "13_desktop_list")
        open_player(page)
        sess.sleep(0.8)
        js(page, "(function(){document.querySelector('#pptCtl [data-act=\"thumbs\"]').click();return true;})()")
        sess.sleep(0.4)
        th = js(page, "(function(){var d=document.getElementById('pptThumbs');"
                      "if(!d)return null;var r=d.getBoundingClientRect();"
                      "return {on:d.classList.contains('on'),x:Math.round(r.left),y:Math.round(r.top),"
                      "w:Math.round(r.width),h:Math.round(r.height),vw:innerWidth,vh:innerHeight};})()")
        R.add("桌面：缩略图抽屉从左侧滑入（左贴边 / 宽 288 / 全高）",
              bool(th) and th.get("on") and abs(th.get("x", 9)) <= 2
              and abs(th.get("w", 0) - 288) <= 2 and abs(th.get("h", 0) - th.get("vh", 0)) <= 2,
              json.dumps(th, ensure_ascii=False))
        shot(page, "14_desktop_thumbs")
        js(page, "(function(){document.querySelector('#pptCtl [data-act=\"thumbs\"]').click();return true;})()")
        sess.sleep(0.3)
        js(page, "(function(){document.querySelector('#pptCtl [data-act=\"notes\"]').click();return true;})()")
        sess.sleep(0.4)
        nt = js(page, "(function(){var d=document.getElementById('pptNotes');"
                      "if(!d)return null;var r=d.getBoundingClientRect();"
                      "return {on:d.classList.contains('on'),right:Math.round(r.right),x:Math.round(r.left),"
                      "w:Math.round(r.width),vw:innerWidth,txt:document.getElementById('pptNoteBody')?"
                      "document.getElementById('pptNoteBody').textContent:''};})()")
        R.add("桌面：备注抽屉从右侧滑入（右贴边 / 宽 320 / 不透明底）",
              bool(nt) and nt.get("on") and abs(nt.get("right", 0) - nt.get("vw", 0)) <= 2
              and abs(nt.get("w", 0) - 320) <= 2 and "第一页备注" in str(nt.get("txt")),
              json.dumps(nt, ensure_ascii=False)[:240])
        shot(page, "15_desktop_notes")
        ply = js(page, "(function(){var p=document.getElementById('pptPlayer');"
                       "return {sw:document.documentElement.scrollWidth,vw:innerWidth,"
                       "psw:p?p.scrollWidth:0,pcw:p?p.clientWidth:0};})()")
        R.add("桌面 1280px：播放器无横向溢出", ply.get("sw", 9999) <= ply.get("vw", 0) + 1
              and ply.get("psw", 9999) <= ply.get("pcw", 0) + 1, json.dumps(ply))
    finally:
        sess.close()


def main():
    t0 = time.time()
    print("=" * 68)
    print("v2_ppt_check · PPT 演示（网页端）专项验收")
    print("被测文件: %s (%d B)" % (SRC, os.path.getsize(SRC)))
    print("=" * 68)
    static_checks()
    if not os.path.isdir(SHOTS):
        os.makedirs(SHOTS, exist_ok=True)
    with MOCK_LOCK:
        MOCK["decks"] = [dict(d) for d in FIXTURE_DECKS]
        MOCK["agent"]["seen_at"] = NOW - 5000
        MOCK["posts"] = []
        MOCK["patches"] = []
        MOCK["chunks"] = []
        MOCK["blocked_writes"] = []
    server = Server()
    server.start()
    sess = None
    try:
        sess = Session(server)
        scenario_main(sess)
        errs = sess.errors()
        R.add("0 JS 报错（window.onerror / unhandledrejection / CDP exception）",
              not errs["js_errs"] and not errs["cdp_exc"],
              json.dumps({"js": errs["js_errs"][:3], "cdp": errs["cdp_exc"][:3]}, ensure_ascii=False))
        R.add("0 console.error（页面代码未打印错误）", not errs["console_errs"] and not errs["cdp_console"],
              json.dumps({"js": errs["console_errs"][:3], "cdp": errs["cdp_console"][:3]}, ensure_ascii=False))
        with MOCK_LOCK:
            blocked = list(MOCK["blocked_writes"])
        R.add("0 真实云端写（假 token + 非 mock 写请求全部阻断）",
              all(("ppt_decks" not in b and "ppt_upload_chunks" not in b) for b in blocked),
              json.dumps(blocked[:6], ensure_ascii=False))
        print("  · mock 统计: requests=%d mocked=%d blocked_writes=%d passed_reads=%d"
              % (sess.mock["seen"], sess.mock["mocked"], sess.mock["blocked"], sess.mock["passed"]))
        print("  · 云端 mock 记录: decks=%d posts=%d chunks=%d patches=%d agent_gets=%d list_gets=%d"
              % (len(MOCK["decks"]), len(MOCK["posts"]), len(MOCK["chunks"]),
                 len(MOCK["patches"]), MOCK["agent_gets"], MOCK["list_gets"]))
    finally:
        if sess:
            sess.close()
    for _name, _fn in (("空态", scenario_empty), ("离线", scenario_offline),
                       ("图片失败降级", scenario_img_error), ("桌面布局", scenario_desktop)):
        try:
            _fn(server)
        except Exception as e:  # noqa: BLE001
            R.add(_name + "场景执行", False, repr(e))
    server.stop()

    total, passed, failed = R.summary()
    print("=" * 68)
    print("v2_ppt_check: %d 项，PASS %d，FAIL %d（%.1fs）" % (total, passed, failed, time.time() - t0))
    print("截图: %s" % SHOTS)
    print("=" * 68)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
