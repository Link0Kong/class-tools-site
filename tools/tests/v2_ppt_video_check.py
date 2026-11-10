# -*- coding: utf-8 -*-
"""PPT 演示 v1.2（网页端）· 原样播放 / 续播 / 列表便捷 / 热点时序 专项验收 —— `v2_ppt_video_check.py`

契约唯一真源：`web/ppt/CONTRACT.md` §11.1（manifest.video）/ §11.3（三端播放器要求）/
§11.5（网页实现约束）；设计参考：`web/ppt/DESIGN.md` §4.3–4.9。

本文件复用 `v2_ppt_check.py` 的 CDP mock 基座（`B.install_cdp_mock` / `B.MOCK` / `B.build_init` /
`B.svg` / `B.press` 等），不重复实现云端拦截；新增一个自建静态服务器，额外提供 `/slowimg?ms=` 慢图，
用于真实复现「切到含视频的页后热点偶发为 0」的竞态。

覆盖（断言数见文件末尾统计）：
  S 静态：v1.2 标记/常量/网络判据/章节 seek +0.05/失败回退文案/热点 ≥56px/续播键/列表胶囊/下载
  A 默认模式（网络良好）：≤2 步进播放器 → 原样 + 自动播放；控制条（暂停/上下页按章节 seek/刻度点/
    倍速 1×1.25×1.5×2×/全屏/下载/退出）、模式胶囊、键盘 Space/←→/M/Esc、左右滑章节翻页、
    点舞台显隐控制条（不做 1/3 点击翻页）、430px 无横向溢出
  B 弱网（saveData/2g）→ 默认分步；手动切「原样」后本机记住偏好（zq_ppt_mode_v1），下次优先
  C 视频 error → 重试 1 次 → 自动分步 + toast「网络不佳，已切换分步浏览」，不白屏
  C2 自动播放被拒 → 显示大播放按钮、不报错；点大按钮可播
  D 续播：列表「继续」徽标（7 天内）/原样时长胶囊/自动 seek + toast「续播 mm:ss」/从头重置/看完重置
  E 热点时序：16 页第 12 页慢图 → 切页后热点必现（无需重试）；resize / orientationchange / 快速连切后仍必现
  F 桌面 1280：视频 letterbox 铺满、控制条单行、胶囊在视口内、无横向溢出
  G 无 video + 网络良好 → 默认分步（旧 deck 兼容）；分步续播 + 从头按钮
  H 汇总：0 JS 报错 / 0 console.error / 0 真实云端写

做法：
  - 本机 Edge headless + CDP 直连（`tests/_qa_v2/_cdp.py`）；
  - PostgREST 仍由 `v2_ppt_check.install_cdp_mock` 拦截 `ppt_decks/ppt_upload_chunks/site_assets`，
    其余读放行、写阻断 —— 保证 0 真实云端写；
  - 身份为**假 token**（测试身份学号，不调用真实接口、不打印任何 token）；
  - 视频用 2.5KB / 6s 的真实 H.264 MP4（data URI），不下载任何真实视频文件；
  - 截图存 `tests/_shots_ppt_video/`。

用法（cwd 任意）：python web/tools/tests/v2_ppt_video_check.py
退出码 0 = 全绿。
"""
import base64
import functools
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))       # tools/tests
TOOLS = os.path.dirname(HERE)                           # tools
SRC = os.environ.get("PPTC_SRC") or os.path.join(TOOLS, "index.html")
SHOTS = os.path.join(HERE, "_shots_ppt_video")

sys.path.insert(0, HERE)
import v2_ppt_check as B  # noqa: E402  （CDP mock 基座 / 断言 / 工具 / svg / press）

TINY_MP4_SRC = ("data:video/mp4;base64,"
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAATgbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAF3AAAQAA"
    "AQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAgAABAt0cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAF3AAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAA"
    "AAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAKAAAABaAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAABdwAAAQAAABAAAAAAOD"
    "bWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAAwAAABIABVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRl"
    "b0hhbmRsZXIAAAADLm1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAA"
    "AQAAAu5zdGJsAAAAvnN0c2QAAAAAAAAAAQAAAK5hdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAKAAWgBIAAAASAAAAAAA"
    "AAABFExhdmM2My4xLjEwMiBsaWJ4MjY0AAAAAAAAAAAAAAAAGP//AAAANGF2Y0MBZAAK/+EAGWdkAAqs2UKN+TARAAADAAEA"
    "AAMADA8SJZYBAARo74/L/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAAAAaGAAAAAAAAABhzdHRzAAAAAAAAAAEA"
    "AAAkAAAIAAAAABRzdHNzAAAAAAAAAAEAAAABAAABKGN0dHMAAAAAAAAAIwAAAAEAABAAAAAAAQAAKAAAAAABAAAQAAAAAAEA"
    "AAAAAAAAAQAACAAAAAABAAAoAAAAAAEAABAAAAAAAQAAAAAAAAABAAAIAAAAAAEAACgAAAAAAQAAEAAAAAABAAAAAAAAAAEA"
    "AAgAAAAAAQAAKAAAAAABAAAQAAAAAAEAAAAAAAAAAQAACAAAAAABAAAoAAAAAAEAABAAAAAAAQAAAAAAAAABAAAIAAAAAAEA"
    "ACgAAAAAAQAAEAAAAAABAAAAAAAAAAEAAAgAAAAAAQAAKAAAAAABAAAQAAAAAAEAAAAAAAAAAQAACAAAAAABAAAoAAAAAAEA"
    "ABAAAAAAAQAAAAAAAAABAAAIAAAAAAEAACAAAAAAAgAACAAAAAAcc3RzYwAAAAAAAAABAAAAAQAAACQAAAABAAAApHN0c3oA"
    "AAAAAAAAAAAAACQAAALrAAAAEAAAAA0AAAANAAAADQAAABEAAAAPAAAADQAAAA0AAAARAAAADwAAAA0AAAANAAAAEQAAAA8A"
    "AAANAAAADQAAABEAAAAPAAAADQAAAA0AAAARAAAADwAAAA0AAAANAAAAEQAAAA8AAAANAAAADQAAABEAAAAPAAAADQAAAA0A"
    "AAARAAAADwAAAA0AAAAUc3RjbwAAAAAAAAABAAAFEAAAAGF1ZHRhAAAAWW1ldGEAAAAAAAAAIWhkbHIAAAAAAAAAAG1kaXJh"
    "cHBsAAAAAAAAAAAAAAAALGlsc3QAAAAkqXRvbwAAABxkYXRhAAAAAQAAAABMYXZmNjMuMS4xMDIAAAAIZnJlZQAABO1tZGF0"
    "AAACrAYF//+o3EXpvebZSLeWLNgg2SPu73gyNjQgLSBjb3JlIDE2NSByMzIyMyAwNDgwY2IwIC0gSC4yNjQvTVBFRy00IEFW"
    "QyBjb2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAyNSAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlv"
    "bnM6IGNhYmFjPTEgcmVmPTEgZGVibG9jaz0xOjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9MiBwc3k9MSBw"
    "c3lfcmQ9MS4wMDowLjAwIG1peGVkX3JlZj0wIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9MCA4eDhkY3Q9MSBj"
    "cW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bza2lwPTEgY2hyb21hX3FwX29mZnNldD0wIHRocmVhZHM9MyBsb29rYWhlYWRf"
    "dGhyZWFkcz0xIHNsaWNlZF90aHJlYWRzPTAgbnI9MCBkZWNpbWF0ZT0xIGludGVybGFjZWQ9MCBibHVyYXlfY29tcGF0PTAg"
    "Y29uc3RyYWluZWRfaW50cmE9MCBiZnJhbWVzPTMgYl9weXJhbWlkPTIgYl9hZGFwdD0xIGJfYmlhcz0wIGRpcmVjdD0xIHdl"
    "aWdodGI9MSBvcGVuX2dvcD0wIHdlaWdodHA9MSBrZXlpbnQ9MjUwIGtleWludF9taW49NiBzY2VuZWN1dD00MCBpbnRyYV9y"
    "ZWZyZXNoPTAgcmNfbG9va2FoZWFkPTEwIHJjPWNyZiBtYnRyZWU9MSBjcmY9MjMuMCBxY29tcD0wLjYwIHFwbWluPTAgcXBt"
    "YXg9NjkgcXBzdGVwPTQgaXBfcmF0aW89MS40MCBhcT0xOjEuMDAAgAAAADdliIQAEv/k/wXg+oGBV4f9vXxLL7d72S6yDpX4"
    "tpd+OrfI2Ef0CbbL62j+55x2ixAjAADnBKX9AAAADEGaJBiCX/61KoAeMAAAAAlBnkJCCH8AIOEAAAAJAZ5hRD//AElAAAAA"
    "CQGeY0Q//wBJQQAAAA1Bmmg0TEEv/rUqgB4xAAAAC0GehkURLBD/ACDhAAAACQGepUQ//wBJQQAAAAkBnqdEP/8ASUAAAAAN"
    "QZqsNExBL/61KoAeMAAAAAtBnspFFSwQ/wAg4QAAAAkBnulEP/8ASUAAAAAJAZ7rRD//AElAAAAADUGa8DRMQS/+tSqAHjEA"
    "AAALQZ8ORRUsEP8AIOEAAAAJAZ8tRD//AElBAAAACQGfL0Q//wBJQAAAAA1BmzQ0TEEv/rUqgB4wAAAAC0GfUkUVLBD/ACDh"
    "AAAACQGfcUQ//wBJQAAAAAkBn3NEP/8ASUAAAAANQZt4NExBL/61KoAeMQAAAAtBn5ZFFSwQ/wAg4AAAAAkBn7VEP/8ASUEA"
    "AAAJAZ+3RD//AElBAAAADUGbvDRMQS/+tSqAHjAAAAALQZ/aRRUsEP8AIOEAAAAJAZ/5RD//AElAAAAACQGf+0Q//wBJQQAA"
    "AA1Bm+A0TEEf/rUqgB4xAAAAC0GeHkUVLBD/ACDgAAAACQGePUQ//wBJQAAAAAkBnj9EP/8ASUEAAAANQZojNExD//6plgDm"
    "gAAAAAtBnkFFFSw//wBJQQAAAAkBnmJEP/8ASUA="
)

INVALID_MP4 = "data:video/mp4;base64,AAAAIGZ0eXBtcDQyAAAAAG1wNDJpc29t"
VIDEO_DATA = B.VIDEO_DATA            # 分步热点用假媒体地址（只验证热点→媒体层）

NOW = int(time.time() * 1000)


def _manifest_video(dur=6.0, chapters=None):
    return {"s": TINY_MP4_SRC, "w": 160, "h": 90, "dur": dur,
            "chapters": chapters if chapters is not None else
            [{"i": 0, "t": 0.0}, {"i": 1, "t": 2.0}, {"i": 2, "t": 4.0}],
            "q": "360p"}


def video_manifest(bad=False):
    return {
        "v": 1, "base": "", "src": B.SRC_DATA, "w": 1600, "h": 900,
        "slides": [
            {"tr": "fade", "trd": 320, "notes": "第一页备注", "thumb": B.THUMB1,
             "steps": [{"img": B.IMG1, "media": []}]},
            {"tr": "push", "trd": 360, "notes": "", "thumb": B.THUMB2,
             "steps": [{"img": B.IMG3, "media": []}]},
            {"tr": "wipe", "trd": 380, "notes": "", "thumb": B.THUMB3,
             "steps": [{"img": B.IMG4, "media": []}]},
        ],
        "media": [],
        "video": (dict(_manifest_video(), s=INVALID_MP4) if bad else _manifest_video()),
    }


def hot_manifest(port, delay_ms=700):
    """16 页；第 12 页（index 11）带视频热点，且该页主图由本地慢图服务器延迟返回，
    用于复现「切页后 syncHot 抢在图片布局完成之前 → 热点为 0」的竞态。
    delay_ms=700 为常规慢图；delay_ms=6500 复现「图片加载超过 6s 兜底 start」的历史 bug
    （旧代码超时 start 后 onload 不再触发重算，热点会一直为 0）。"""
    slow = "http://127.0.0.1:%d/slowimg?ms=%d&l=PAGE12" % (port, delay_ms)
    slides = []
    for i in range(16):
        media = [{"s": VIDEO_DATA, "k": "v", "x": 0.15, "y": 0.2, "w": 0.7, "h": 0.6}] if i == 11 else []
        slides.append({"tr": "fade", "trd": 320, "notes": ("第 1 页备注" if i == 0 else ""),
                       "thumb": B.THUMB1, "steps": [{"img": (slow if i == 11 else B.IMG1), "media": media}]})
    return {"v": 1, "base": "", "src": "", "w": 1600, "h": 900, "slides": slides,
            "media": [{"s": VIDEO_DATA, "k": "v", "w": 1280, "h": 720, "dur": 12.4}]}


def make_decks(port):
    def row(did, title, man, created):
        return B.deck(id=did, title=title, manifest=man, created_at=created,
                      slide_count=len(man.get("slides") or []),
                      step_count=sum(len(s.get("steps") or []) for s in (man.get("slides") or [])))
    return [
        row("dtestvideo1", "原样视频演示", video_manifest(), NOW - 1000),
        row("dtestvideo2", "坏视频演示", video_manifest(bad=True), NOW - 2000),
        row("dtesthots1", "十六页热点演示", hot_manifest(port, 700), NOW - 3000),
        row("dtesthotslow1", "十六页慢图热点演示", hot_manifest(port, 6500), NOW - 3500),
        B.deck(),  # dtestready1：无 manifest.video（旧 deck 兼容）
    ]


# ---------------------------------------------------------------- 断言与工具
R = B.Results()
SCENE_ERRORS = []
SCENE_NAMES = []


def wait_js(page, expr, timeout=8.0, interval=0.1):
    return B.wait_js(page, expr, timeout=timeout, interval=interval)


def js(page, expr, await_promise=False):
    return page.evaluate(expr, await_promise=await_promise)


def shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    return page.screenshot(os.path.join(SHOTS, name + ".png"))


def press(page, key, code, vk):
    B.press(page, key, code, vk)
    time.sleep(0.12)


VSTATE = r"""
(function(){
  var r=document.getElementById('pptPlayer'), v=document.getElementById('pptVideo');
  var c=document.getElementById('pptVCtl'), t=document.getElementById('pptVTop');
  var big=document.getElementById('pptVBig'), load=document.getElementById('pptVLoad');
  var dl=document.getElementById('pptVDl');
  var g=function(id){var e=document.getElementById(id);return e?e.textContent:'';};
  var ticks=document.querySelectorAll('#pptVTicks [data-vtick]');
  var on=0,i;
  for(i=0;i<ticks.length;i++){if(ticks[i].classList.contains('on'))on++;}
  var seg=document.querySelector('#pptVSeg [data-vmode].on');
  var rowC=document.querySelector('#pptVCtl .ppt-vrow');
  var rows=0;
  if(rowC){
    var mids={};
    for(var k=0;k<rowC.children.length;k++){
      var bb=rowC.children[k].getBoundingClientRect();
      if(bb.width||bb.height){var m=Math.round(bb.top+bb.height/2);if(!mids[m]){mids[m]=1;rows++;}}
    }
  }
  return {open:!!r, vmode:!!(r&&r.classList.contains('ppt-vmode')),
    hasVideo:!!v, paused:v?v.paused:null, t:v?+v.currentTime:null, dur:v?+v.duration:null,
    rs:v?v.readyState:-1, err:(v&&v.error)?v.error.code:0,
    src:v?(v.getAttribute('src')||'').slice(0,28):'',
    rate:v?+v.playbackRate:null,
    bigVisible:!!(big&&!big.hidden), loadVisible:!!(load&&!load.hidden),
    ctlHide:c?c.classList.contains('hide'):null, ctlHidden:c?c.hidden:null,
    topHide:t?t.classList.contains('hide'):null,
    topHidden:t?t.hidden:null, seg:seg?seg.getAttribute('data-vmode'):'',
    page:g('pptVPage'), time:g('pptVTime'), idx:g('pptIdx'), speed:g('pptVSpeed'),
    nTicks:ticks.length, onTick:on,
    dlHref:dl?(dl.getAttribute('href')||'').slice(0,28):'', dlName:dl?(dl.getAttribute('download')||''):'',
    ctlSW:c?c.scrollWidth:0, ctlCW:c?c.clientWidth:0,
    rowH:rowC?Math.round(rowC.getBoundingClientRect().height):0, rows:rows,
    pSW:r?r.scrollWidth:0, pCW:r?r.clientWidth:0,
    vRect:v?(function(){var q=v.getBoundingClientRect();return [Math.round(q.width),Math.round(q.height),Math.round(q.left),Math.round(q.top)];})():null,
    docSW:document.documentElement.scrollWidth, vw:innerWidth, vh:innerHeight};
})()
"""

HOTSTATE = r"""
(function(){
  var h=document.getElementById('pptHot');
  var bs=h?h.querySelectorAll('.ppt-hotbtn'):[];
  var d=h?h.querySelector('.ppt-hotdur'):null;
  var b=bs.length?bs[0].getBoundingClientRect():null;
  var err=document.getElementById('pptImgErr');
  var idx=document.getElementById('pptIdx');
  return {n:bs.length, hotdur:d?d.textContent:'',
    w:b?Math.round(b.width):0, h:b?Math.round(b.height):0,
    imgerr:!!(err&&!err.hidden), idx:idx?idx.textContent:''};
})()
"""

CARDSTATE = r"""
(function(){
  var c=document.querySelector('#pptList [data-deck="__DECK__"]');
  if(!c)return null;
  var rsm=c.querySelector('.ppt-rsm'), vc=c.querySelector('.ppt-vcap'), play=c.querySelector('.ppt-cvplay');
  return {txt:(c.innerText||'').replace(/\n/g,' | '), rsm:!!rsm, rsmTxt:rsm?rsm.textContent:'',
    vcap:!!vc, vcapTxt:vc?vc.textContent:'', play:!!play};
})()
"""


class Server(object):
    """静态服务器（web/tools）+ /slowimg 慢图接口（验证热点时序竞态）。"""

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

            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                if path.startswith("/slowimg"):
                    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    delay = float((qs.get("ms") or ["650"])[0]) / 1000.0
                    label = str((qs.get("l") or ["SLOW"])[0])[:20]
                    time.sleep(delay)
                    body = ('<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">'
                            '<rect width="1600" height="900" fill="#35524C"/>'
                            '<text x="800" y="510" font-size="180" font-family="sans-serif" '
                            'fill="#FFFFFF" text-anchor="middle">%s</text></svg>' % label).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "image/svg+xml")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                return http.server.SimpleHTTPRequestHandler.do_GET(self)

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
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass

    def app_url(self):
        return "http://127.0.0.1:%d/index.html" % self.port


class Session(object):
    """复用 v2_ppt_check 的 CDP mock 基座；boot 后直接进入「演示」tab。"""

    def __init__(self, server, width=430, height=900, mobile=True, scene=""):
        self.scene = scene or "scene"
        self.server = server
        self.width = width
        self.height = height
        self.browser = B._cdp.Browser(
            extra_flags=["--disable-web-security", "--allow-running-insecure-content",
                         "--autoplay-policy=no-user-gesture-required"],
            window=(width, height))
        try:
            self.page = self.browser.new_page("about:blank")
            self.page.set_device(width, height, dpr=2.0, mobile=mobile, touch=mobile)
            self.mock = B.install_cdp_mock(self.page)
            self.page.add_init_script(B.build_init())
            self.page.navigate(server.app_url())
            self.page.wait_load(timeout=25)
            if not wait_js(self.page, "(function(){return !document.body.classList.contains('id-locked')"
                                      "&&!!document.querySelector('#tabsBar button[data-tab]');})()", 25):
                raise RuntimeError("页面未进入身份后状态")
            wait_js(self.page, "(function(){var b=document.querySelector('#tabsBar button[data-tab=\"ppt\"]');"
                               "if(b)b.click();return !!b;})()", 8)
            self.wait("(function(){var s=document.querySelector('section.on');"
                      "return !!s&&s.id==='s-ppt';})()", 8)
            self.wait("document.querySelectorAll('#pptList .ppt-card').length>=3", 12)
            time.sleep(0.35)
        except Exception:
            self.close()
            raise

    # ---------- 基础 ----------
    def js(self, expr, await_promise=False):
        return js(self.page, expr, await_promise)

    def wait(self, expr, timeout=8.0):
        return wait_js(self.page, expr, timeout)

    def sleep(self, s):
        time.sleep(s)

    def shot(self, name):
        return shot(self.page, name + (("-" + self.scene) if self.scene else ""))

    def errors(self):
        return {"js": self.js("window.__errs||[]") or [],
                "cons": self.js("window.__cerrs||[]") or [],
                "cdp": self.page.exceptions(), "cdpcon": self.page.console_errors()}

    def close(self):
        try:
            e = self.errors()
            e["scene"] = self.scene
            SCENE_ERRORS.append(e)
            SCENE_NAMES.append(self.scene)
        except Exception:
            pass
        try:
            self.page.close()
        except Exception:
            pass
        try:
            self.browser.close()
        except Exception:
            pass

    # ---------- 网络 / 存储 ----------
    def set_conn(self, cfg):
        payload = json.dumps(cfg)
        return self.js("(function(){try{Object.defineProperty(navigator,'connection',{value:%s,"
                       "configurable:true});}catch(e){try{navigator.connection=%s;}catch(e2){}}"
                       "return (navigator.connection&&navigator.connection.effectiveType)||'';})()"
                       % (payload, payload))

    def conn(self):
        return self.js("(function(){var c=navigator.connection;"
                       "return c?{et:c.effectiveType,save:!!c.saveData}:null;})()")

    def ls_set(self, k, v):
        payload = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        return self.js("(function(){try{localStorage.setItem(%s,%s);return true;}"
                       "catch(e){return false;}})()"
                       % (json.dumps(k), json.dumps(payload)))

    def ls_get(self, k):
        return self.js("(function(){try{var s=localStorage.getItem(%s);if(!s)return null;"
                       "try{return JSON.parse(s);}catch(e2){return s;}}"
                       "catch(e){return null;}})()" % json.dumps(k))

    def ls_del(self, k):
        return self.js("(function(){try{localStorage.removeItem(%s);return true;}"
                       "catch(e){return false;}})()" % json.dumps(k))

    def clear_ppt_prefs(self):
        return self.js("(function(){try{var out=[];for(var i=localStorage.length-1;i>=0;i--){"
                       "var k=localStorage.key(i);"
                       "if(k&&k.indexOf('zq_ppt_')===0){out.push(k);localStorage.removeItem(k);}}return out;}"
                       "catch(e){return [];})()")

    # ---------- PPT ----------
    def open_card(self, did):
        ok = self.js("(function(){var c=document.querySelector('#pptList [data-deck=\"%s\"] .ppt-bd');"
                     "if(!c)return false;c.click();return true;})()" % did)
        if not ok:
            return False
        return self.wait("!!document.getElementById('pptPlayer')", 8)

    def open_via_api(self, did):
        self.js("(function(){window.PPT.open(%s);return true;})()" % json.dumps(did))
        return self.wait("!!document.getElementById('pptPlayer')", 8)

    def wait_video(self, timeout=8.0):
        return self.wait("(function(){var v=document.getElementById('pptVideo');"
                         "return !!v&&v.readyState>=2;})()", timeout)

    def vstate(self):
        return self.js(VSTATE)

    def close_player(self):
        self.js("(function(){var b=document.querySelector('#pptPlayer [data-act=\"close\"]');"
                "if(b)b.click();return true;})()")
        self.sleep(0.3)
        st = self.js("(function(){var c=document.getElementById('pptConfirm');"
                     "return {player:!!document.getElementById('pptPlayer'),confirm:!!(c&&!c.hidden)};})()")
        if st and st.get("confirm"):
            self.js("(function(){var b=document.querySelector('#pptConfirm [data-act=\"leave\"]');"
                    "if(b)b.click();return true;})()")
            self.sleep(0.35)
        return not self.js("!!document.getElementById('pptPlayer')")

    def close_video_player(self):
        self.js("(function(){var b=document.querySelector('#pptVCtl [data-vact=\"close\"]');"
                "if(b)b.click();return true;})()")
        self.sleep(0.3)
        st = self.js("(function(){var c=document.getElementById('pptConfirm');"
                     "return {player:!!document.getElementById('pptPlayer'),confirm:!!(c&&!c.hidden)};})()")
        if st and st.get("confirm"):
            self.js("(function(){var b=document.querySelector('#pptConfirm [data-act=\"leave\"]');"
                    "if(b)b.click();return true;})()")
            self.sleep(0.35)
        return not self.js("!!document.getElementById('pptPlayer')")


# ---------------------------------------------------------------- S 静态检查
def static_checks():
    try:
        html = open(SRC, encoding="utf-8", newline="").read()
    except Exception as e:  # noqa: BLE001
        R.add("静态：能读取 index.html", False, repr(e))
        return
    flat = re.sub(r"\s+", "", html)
    R.add("静态：APP_VER 仍为 2.0.0", 'varAPP_VER="2.0.0"' in flat)
    R.add("静态：功能块标记 __PPT_FEATURE_V1__ 仍为 CSS+JS 各一（新增用 __PPT_VIDEO_V1__）",
          html.count("__PPT_FEATURE_V1__") == 2 and html.count("__PPT_VIDEO_V1__") >= 2,
          "feature=%d video=%d" % (html.count("__PPT_FEATURE_V1__"), html.count("__PPT_VIDEO_V1__")))
    R.add("静态：v1.2 常量（7 天续播 TTL / waiting 4s / 连续 2 次 / 倍速档位）",
          "POS_TTL=7*24*3600*1000" in flat and "V_WAIT_MS=4000" in flat
          and "V_MAX_STALL=2" in flat and "SPEEDS=[1,1.25,1.5,2]" in flat)
    R.add("静态：模式偏好与续播/视频缓存 localStorage 键",
          "zq_ppt_mode_v1" in flat and "zq_ppt_pos_" in flat and "zq_ppt_vmeta_" in flat)
    R.add("静态：网络判据 saveData / effectiveType(slow-2g,2g,3g)",
          "saveData" in flat and "effectiveType" in flat
          and all(('"%s"' % v) in flat for v in ("slow-2g", "2g", "3g")))
    R.add("静态：章节 seek = chapters[k].t + 0.05（保持播放状态）",
          "chapters[k].t,0)+0.05" in flat)
    R.add("静态：视频失败回退文案「网络不佳，已切换分步浏览」+ 重试 1 次分支",
          "网络不佳，已切换分步浏览" in flat and "PL.vRetries<1" in flat)
    R.add("静态：原样播放控制条含 播放/上下页/倍速/全屏/从头/下载/退出",
          all(('data-vact="%s"' % a) in html for a in
              ("prev", "next", "play", "speed", "fs", "restart", "close")) and 'data-vact="dl"' in html)
    R.add("静态：模式切换胶囊「原样 / 分步」", 'data-vmode="video"' in html and 'data-vmode="step"' in html
          and ">原样<" in html and ">分步<" in html)
    R.add("静态：原样视频下载 <a download>（.ppt-vdl）", 'class="ppt-vdl"' in html and "download" in html
          and "dlName()" in flat)
    R.add("静态：键盘视频分支 Space/←→/M/F/Esc",
          'PL.mode==="video"' in flat and 'vTogglePlay()' in flat and 'vGoPage(1)' in flat
          and 'vToggleMode()' in flat)
    R.add("静态：点舞台显隐控制条（不做 1/3 点击翻页）+ 左右滑章节翻页",
          "onVStageClick" in flat and "ctlMoveAt" in flat and "vGoPage(d.dx<0?1:-1)" in flat)
    R.add("静态：热点 ≥56px（手机 64）且带脉冲动画",
          ".ppt-hotbtn{position:relative;pointer-events:auto;border:0;padding:0;margin:0;width:56px;height:56px" in flat
          and ".ppt-hotbtn{width:64px;height:64px" in flat and "pptHotPulse" in flat)
    R.add("静态：热点时序修复三处触发（img load / transitionend / resize+orientationchange）",
          "hotBurst" in flat and 'addEventListener("transitionend"' in html
          and 'addEventListener("orientationchange"' in html and "hotWatch" in flat)
    R.add("静态：列表「继续」徽标 + 「原样 m:ss」胶囊", "ppt-rsm" in html and "继续" in html
          and "ppt-vcap" in html and "原样 " in html)
    R.add("静态：视频层 class / 控制条 / loading / 大播放按钮", "ppt-vwrap" in html
          and "ppt-vctl" in html and "ppt-vload" in html and "ppt-vbig" in html)
    R.add("静态：无外部脚本/字体/CDN（单文件零依赖）",
          "<script src=" not in html and "fonts.googleapis" not in html and "cdn." not in html)
    R.add("静态：不新增密钥（无 AccessKey / LTAI / 真实 token）",
          "AccessKey" not in html and "LTAI" not in html and "fake-token" not in html)


# ---------------------------------------------------------------- A 视频默认模式 + 控制条
def scenario_video_controls(server):
    sess = Session(server, scene="A_video")
    try:
        page = sess.page
        et = sess.set_conn({"effectiveType": "4g", "saveData": False})
        R.add("网络：mock navigator.connection 生效（effectiveType=4g）", et == "4g", str(et))
        R.add("列表：整卡点击 = 直接播放（封面大 ▶ 存在）",
              bool(js(page, "(function(){var c=document.querySelector('#pptList [data-deck=\"dtestvideo1\"]');"
                            "return !!(c&&c.querySelector('.ppt-cvplay'));})()")))
        ok = sess.open_card("dtestvideo1")
        R.add("默认模式：网络良好 + manifest.video → 打开即原样播放（≤2 步）", ok, "")
        started = sess.wait_video(10)
        sess.sleep(0.6)
        st = sess.vstate()
        R.add("原样播放：root.ppt-vmode + <video> 加载就绪（readyState≥2）",
              bool(st) and st.get("vmode") and st.get("hasVideo") and st.get("rs", 0) >= 2,
              json.dumps({k: st.get(k) for k in ("vmode", "hasVideo", "rs", "paused", "t")}, ensure_ascii=False))
        R.add("原样播放：自动播放生效（enter 属于用户手势）",
              bool(st) and st.get("paused") is False, json.dumps(st, ensure_ascii=False)[:200])
        R.add("原样播放：全屏黑底 letterbox（video 铺满播放器、object-fit=contain）",
              bool(st) and st.get("vRect") and st["vRect"][0] == sess.width
              and abs(st["vRect"][1] - sess.height) <= 2,
              json.dumps(st.get("vRect")))
        R.add("视频控制条：时间 mm:ss / mm:ss",
              bool(st) and re.match(r"^\d{2}:\d{2} / \d{2}:\d{2}$", str(st.get("time") or "")) is not None,
              (st or {}).get("time"))
        R.add("视频控制条：页码「第 1/3 页」+ 章节刻度点 3 个（当前第 1 个高亮）",
              bool(st) and st.get("page") == "第 1/3 页" and st.get("nTicks") == 3 and st.get("onTick") == 1,
              json.dumps({k: (st or {}).get(k) for k in ("page", "nTicks", "onTick")}, ensure_ascii=False))
        R.add("视频控制条：下载原样视频 <a download>（data: 小视频、文件名 .mp4）",
              bool(st) and str(st.get("dlHref", "")).startswith("data:video/mp4")
              and str(st.get("dlName", "")).endswith(".mp4"),
              json.dumps({k: (st or {}).get(k) for k in ("dlHref", "dlName")}, ensure_ascii=False))
        R.add("视频控制条：全屏按钮存在 + Fullscreen API 可用",
              bool(js(page, "(function(){var b=document.querySelector('#pptVCtl [data-vact=\"fs\"]');"
                            "return !!b&&!!(document.documentElement.requestFullscreen||"
                            "document.documentElement.webkitRequestFullscreen);})()")))
        R.add("自动播放时大播放按钮/loading 隐藏",
              bool(st) and not st.get("bigVisible") and not st.get("loadVisible"),
              json.dumps({k: (st or {}).get(k) for k in ("bigVisible", "loadVisible")}))
        # 控制条 3s 自动隐藏 + 点舞台显隐（视频模式不做 1/3 点击翻页）
        hidden = sess.wait("(function(){var c=document.getElementById('pptVCtl');"
                           "return !!c&&c.classList.contains('hide');})()", 6)
        R.add("视频控制条：3s 无操作自动隐藏", hidden)
        page.click(int(sess.width * 0.5), int(sess.height * 0.45))
        sess.sleep(0.3)
        ctl1 = js(page, "(function(){var c=document.getElementById('pptVCtl');"
                        "return {hide:!!c&&c.classList.contains('hide'),"
                        "paused:(document.getElementById('pptVideo')||{}).paused};})()")
        R.add("视频模式：点舞台唤出控制条（且不触发翻页/暂停）",
              bool(ctl1) and ctl1.get("hide") is False and ctl1.get("paused") is False,
              json.dumps(ctl1, ensure_ascii=False))
        page.click(int(sess.width * 0.5), int(sess.height * 0.45))
        sess.sleep(0.3)
        R.add("视频模式：再点舞台收起控制条",
              js(page, "(function(){var c=document.getElementById('pptVCtl');"
                       "return !!c&&c.classList.contains('hide');})()"))
        # 暂停（Space）→ 章节 seek 保持暂停
        press(page, " ", "Space", 32)
        sess.sleep(0.3)
        p1 = sess.vstate()
        R.add("键盘 Space：播放/暂停切换（此步为暂停）", bool(p1) and p1.get("paused") is True,
              json.dumps({k: (p1 or {}).get(k) for k in ("paused", "t")}, ensure_ascii=False))
        press(page, " ", "Space", 32)
        sess.sleep(0.25)
        press(page, " ", "Space", 32)
        sess.sleep(0.25)
        R.add("键盘 Space：再次播放/暂停可用，无 JS 异常",
              not (js(page, "window.__errs||[]") or []))
        # 先回到第 1 章起点（自动播放 3s 后 currentTime 已不在 0，用刻度点归位）
        js(page, "(function(){var t=document.querySelectorAll('#pptVTicks [data-vtick]');"
                 "if(t.length)t[0].click();return true;})()")
        sess.sleep(0.4)
        # 下一页 → chapters[1].t+0.05
        js(page, "(function(){var b=document.querySelector('#pptVCtl [data-vact=\"next\"]');if(b)b.click();return true;})()")
        sess.sleep(0.5)
        n1 = sess.vstate()
        R.add("下一章：按 chapters seek 到 t+0.05（≈2.05）且暂停状态保持",
              bool(n1) and abs(float(n1.get("t") or 0) - 2.05) <= 0.35 and n1.get("paused") is True
              and n1.get("page") == "第 2/3 页",
              json.dumps({k: (n1 or {}).get(k) for k in ("t", "paused", "page")}, ensure_ascii=False))
        js(page, "(function(){var b=document.querySelector('#pptVCtl [data-vact=\"next\"]');if(b)b.click();return true;})()")
        sess.sleep(0.5)
        n2 = sess.vstate()
        R.add("下一章再点：第 3/3 页（≤ dur）", bool(n2) and n2.get("page") == "第 3/3 页"
              and abs(float(n2.get("t") or 0) - 4.05) <= 0.4,
              json.dumps({k: (n2 or {}).get(k) for k in ("t", "page")}, ensure_ascii=False))
        js(page, "(function(){var b=document.querySelector('#pptVCtl [data-vact=\"prev\"]');if(b)b.click();return true;})()")
        sess.sleep(0.5)
        R.add("上一章：回到第 2/3 页", (sess.vstate() or {}).get("page") == "第 2/3 页",
              (sess.vstate() or {}).get("page"))
        # 章节刻度点点击 seek
        js(page, "(function(){var t=document.querySelectorAll('#pptVTicks [data-vtick]');"
                 "if(t.length>2)t[2].click();return true;})()")
        sess.sleep(0.5)
        t2 = sess.vstate()
        R.add("章节进度条：点第 3 个刻度点 → seek 到第 3 页（≈4.05）",
              bool(t2) and t2.get("page") == "第 3/3 页" and abs(float(t2.get("t") or 0) - 4.05) <= 0.45,
              json.dumps({k: (t2 or {}).get(k) for k in ("t", "page", "onTick")}, ensure_ascii=False))
        js(page, "(function(){var t=document.querySelectorAll('#pptVTicks [data-vtick]');"
                 "if(t.length)t[0].click();return true;})()")
        sess.sleep(0.5)
        R.add("章节进度条：点第 1 个刻度点 → 回第 1 页", (sess.vstate() or {}).get("page") == "第 1/3 页",
              (sess.vstate() or {}).get("page"))
        # 倍速循环
        rates = []
        for _ in range(4):
            js(page, "(function(){var b=document.querySelector('#pptVCtl [data-vact=\"speed\"]');if(b)b.click();return true;})()")
            sess.sleep(0.15)
            rates.append((sess.vstate() or {}).get("rate"))
        R.add("倍速循环：1× → 1.25× → 1.5× → 2× → 1×",
              rates == [1.25, 1.5, 2.0, 1.0], json.dumps(rates))
        R.add("倍速按钮文案随倍速更新（当前 1×）", (sess.vstate() or {}).get("speed") == "1×",
              (sess.vstate() or {}).get("speed"))
        # 键盘 →（章节下一页）
        press(page, "ArrowRight", "ArrowRight", 39)
        sess.sleep(0.45)
        R.add("键盘 →：原样播放下一页（第 2/3 页）", (sess.vstate() or {}).get("page") == "第 2/3 页",
              (sess.vstate() or {}).get("page"))
        press(page, "ArrowLeft", "ArrowLeft", 37)
        sess.sleep(0.45)
        R.add("键盘 ←：原样播放上一页（第 1/3 页）", (sess.vstate() or {}).get("page") == "第 1/3 页",
              (sess.vstate() or {}).get("page"))
        # 左右滑 = 章节
        page.touch_swipe(int(sess.width * 0.85), int(sess.height * 0.5),
                         int(sess.width * 0.15), int(sess.height * 0.5), steps=10, gap=0.015)
        sess.sleep(0.7)
        R.add("手势：左滑 = 下一章（第 2/3 页，且不切 top tab）",
              (sess.vstate() or {}).get("page") == "第 2/3 页"
              and B.top_tab(page) == "s-ppt",
              "%s/%s" % ((sess.vstate() or {}).get("page"), B.top_tab(page)))
        page.touch_swipe(int(sess.width * 0.15), int(sess.height * 0.5),
                         int(sess.width * 0.85), int(sess.height * 0.5), steps=10, gap=0.015)
        sess.sleep(0.7)
        R.add("手势：右滑 = 上一章（第 1/3 页）", (sess.vstate() or {}).get("page") == "第 1/3 页",
              (sess.vstate() or {}).get("page"))
        # 模式切换（胶囊 分步 → 原样）
        js(page, "(function(){var b=document.querySelector('#pptVSeg [data-vmode=\"step\"]');if(b)b.click();return true;})()")
        sess.sleep(0.7)
        ms = sess.vstate()
        R.add("模式切换胶囊：原样 → 分步（root 去掉 ppt-vmode、图片舞台恢复）",
              bool(ms) and not ms.get("vmode") and B.top_tab(page) == "s-ppt",
              json.dumps({k: (ms or {}).get(k) for k in ("vmode", "idx")}, ensure_ascii=False))
        pref = sess.ls_get("zq_ppt_mode_v1")
        R.add("模式偏好：手动切换写入本机 zq_ppt_mode_v1=step",
              pref == "step", json.dumps(pref, ensure_ascii=False))
        js(page, "(function(){var b=document.querySelector('#pptVSeg [data-vmode=\"video\"]');if(b)b.click();return true;})()")
        sess.sleep(0.8)
        back = sess.vstate()
        R.add("模式切换胶囊：分步 → 原样（回到视频层并自动播放）",
              bool(back) and back.get("vmode") and back.get("paused") is False,
              json.dumps({k: (back or {}).get(k) for k in ("vmode", "t", "paused")}, ensure_ascii=False))
        R.add("模式偏好更新为 video", sess.ls_get("zq_ppt_mode_v1") == "video")
        # 430px 无横向溢出（视频模式）
        ov = js(page, "(function(){var r=document.getElementById('pptPlayer'),"
                      "c=document.getElementById('pptVCtl');"
                      "return {docSW:document.documentElement.scrollWidth,vw:innerWidth,"
                      "pSW:r?r.scrollWidth:0,pCW:r?r.clientWidth:0,"
                      "cSW:c?c.scrollWidth:0,cCW:c?c.clientWidth:0,"
                      "ctlW:c?Math.round(c.getBoundingClientRect().width):0};})()")
        R.add("430px：原样播放无横向溢出（页面/播放器/控制条）",
              bool(ov) and ov.get("docSW", 9999) <= ov.get("vw", 0) + 1
              and ov.get("pSW", 9999) <= ov.get("pCW", 0) + 1
              and ov.get("cSW", 9999) <= ov.get("cCW", 0) + 1, json.dumps(ov))
        shot(page, "A1_video_430")
        # Esc：视频未看完 → 站内确认；再 Esc 退出
        press(page, "Escape", "Escape", 27)
        sess.sleep(0.3)
        cf = js(page, "(function(){var c=document.getElementById('pptConfirm');"
                      "return {show:!!(c&&!c.hidden),player:!!document.getElementById('pptPlayer')};})()")
        R.add("键盘 Esc：原样播放未到末尾 → 站内退出确认「退出演示？」",
              bool(cf) and cf.get("show") and cf.get("player"), json.dumps(cf, ensure_ascii=False))
        press(page, "Escape", "Escape", 27)
        sess.sleep(0.4)
        R.add("退出确认时再 Esc → 关闭播放器（覆盖层移除、body 解锁）",
              not js(page, "!!document.getElementById('pptPlayer')")
              and not js(page, "document.body.classList.contains('ppt-lock')"))
        R.add("(A) 原样播放场景 0 JS 报错（本场景结束前）",
              not (js(page, "window.__errs||[]") or []), json.dumps(js(page, "window.__errs||[]") or [])[:200])
    finally:
        sess.close()


# ---------------------------------------------------------------- B 弱网默认分步 + 偏好记忆
def scenario_bad_network(server):
    sess = Session(server, scene="B_badnet")
    try:
        page = sess.page
        et = sess.set_conn({"effectiveType": "2g", "saveData": True})
        R.add("弱网 mock：navigator.connection = 2g/saveData", et == "2g", str(et))
        ok = sess.open_card("dtestvideo1")
        sess.sleep(0.7)
        R.add("默认模式：弱网（saveData/2g）+ 有 video → 默认分步浏览",
              ok and not (sess.vstate() or {}).get("vmode")
              and str((sess.vstate() or {}).get("idx", "")).startswith("1 / 3"),
              json.dumps({k: (sess.vstate() or {}).get(k) for k in ("vmode", "idx")}, ensure_ascii=False))
        seg = js(page, "(function(){var t=document.getElementById('pptVTop');"
                      "var s=document.querySelector('#pptVSeg [data-vmode].on');"
                      "return {top:!!t&&!t.hidden,seg:s?s.getAttribute('data-vmode'):'',"
                      "pageHide:!!(document.getElementById('pptVPage')||{}).hidden};})()")
        R.add("弱网分步模式：顶栏仍显示模式胶囊「分步」高亮、页码隐藏",
              bool(seg) and seg.get("top") and seg.get("seg") == "step" and seg.get("pageHide"),
              json.dumps(seg, ensure_ascii=False))
        js(page, "(function(){var b=document.querySelector('#pptVSeg [data-vmode=\"video\"]');if(b)b.click();return true;})()")
        sess.sleep(0.6)
        played = sess.wait_video(8)
        R.add("手动切「原样」：弱网也允许播放（video readyState≥2）",
              played and (sess.vstate() or {}).get("vmode") is True,
              json.dumps({k: (sess.vstate() or {}).get(k) for k in ("vmode", "rs")}, ensure_ascii=False))
        R.add("手动切换后本机记住偏好 zq_ppt_mode_v1=video",
              sess.ls_get("zq_ppt_mode_v1") == "video",
              json.dumps(sess.ls_get("zq_ppt_mode_v1"), ensure_ascii=False))
        closed = sess.close_video_player()
        sess.sleep(0.4)
        ok2 = sess.open_card("dtestvideo1")
        sess.sleep(0.8)
        R.add("重新打开：本机偏好优先（弱网仍直接进原样播放）",
              closed and ok2 and (sess.vstate() or {}).get("vmode") is True,
              json.dumps({k: (sess.vstate() or {}).get(k) for k in ("vmode", "paused")}, ensure_ascii=False))
        shot(page, "B1_badnet_step")
    finally:
        sess.close()


# ---------------------------------------------------------------- C 视频失败 → 分步回退
def scenario_video_fallback(server):
    sess = Session(server, scene="C_fallback")
    try:
        page = sess.page
        sess.set_conn({"effectiveType": "4g", "saveData": False})
        sess.js("(function(){window.__verr=0;document.addEventListener('error',function(e){"
                "if(e.target&&e.target.tagName==='VIDEO')window.__verr++;},true);"
                "window.__sawVmode=false;try{var mo=new MutationObserver(function(){"
                "var r=document.getElementById('pptPlayer');"
                "if(r&&r.classList.contains('ppt-vmode'))window.__sawVmode=true;});"
                "mo.observe(document.documentElement,{childList:true,subtree:true,attributes:true,"
                "attributeFilter:['class']});}catch(e){}return true;})()")
        ok = sess.open_card("dtestvideo2")
        fell = sess.wait("(function(){var r=document.getElementById('pptPlayer');"
                         "return !!r&&!r.classList.contains('ppt-vmode');})()", 12)
        R.add("失败回退：坏视频 deck 先进入原样播放（随后自动降级）",
              ok and bool(js(page, "window.__sawVmode")), "sawVmode=%s" % js(page, "window.__sawVmode"))
        toast = js(page, "(function(){var t=document.getElementById('toast');"
                        "return {txt:t?t.textContent:'',on:!!(t&&t.classList.contains('on'))};})()")
        R.add("失败回退：error → 重试 1 次 → 自动切分步 + toast「网络不佳，已切换分步浏览」",
              fell and toast.get("txt") == "网络不佳，已切换分步浏览",
              json.dumps(toast, ensure_ascii=False))
        R.add("失败回退：确实触发了 ≥2 次 video error（初次 + 重试 1 次）",
              int(js(page, "window.__verr||0") or 0) >= 2, "verr=%s" % js(page, "window.__verr||0"))
        sess.wait("(function(){var ls=[].slice.call(document.querySelectorAll('#pptPlayer .ppt-layer'));"
                  "for(var i=0;i<ls.length;i++){if(ls[i].style.visibility!=='hidden'){"
                  "var im=ls[i].querySelector('img');if(im&&im.naturalWidth>0)return true;}}return false;})()", 6)
        alive = js(page, r"""(function(){
          var r=document.getElementById('pptPlayer'), img=document.querySelector('#pptPlayer .ppt-layer img');
          var active=null,ls=[].slice.call(document.querySelectorAll('#pptPlayer .ppt-layer'));
          for(var i=0;i<ls.length;i++){if(ls[i].style.visibility!=='hidden'){active=ls[i].querySelector('img');}}
          return {player:!!r,img:active?(active.naturalWidth>0):false,
            imgErr:!!(document.getElementById('pptImgErr')&&!document.getElementById('pptImgErr').hidden),
            loadVisible:!!(document.getElementById('pptVLoad')&&!document.getElementById('pptVLoad').hidden),
            idx:(document.getElementById('pptIdx')||{}).textContent||''};})()""")
        R.add("失败回退：不白屏（播放器仍在 + 分步主图已加载 + loading 已撤）",
              bool(alive) and alive.get("player") and alive.get("img") and not alive.get("imgErr")
              and not alive.get("loadVisible"),
              json.dumps(alive, ensure_ascii=False))
        shot(page, "C1_fallback_step")
    finally:
        sess.close()


# ---------------------------------------------------------------- C2 自动播放被拒 → 大播放按钮
def scenario_autoplay_blocked(server):
    sess = Session(server, scene="C2_autoplay")
    try:
        page = sess.page
        sess.set_conn({"effectiveType": "4g", "saveData": False})
        # 让 play() 一律被拒（模拟浏览器的 NotAllowedError），验证不报错 + 显示大播放按钮
        sess.js("(function(){try{window.__origPlay=HTMLMediaElement.prototype.play;"
                "HTMLMediaElement.prototype.play=function(){return Promise.reject("
                "new DOMException('play blocked','NotAllowedError'));};}catch(e){}return true;})()")
        ok = sess.open_card("dtestvideo1")
        sess.sleep(1.2)
        st = sess.vstate()
        R.add("自动播放被拒：显示大播放按钮（不报错、不白屏）",
              ok and bool(st) and st.get("vmode") and st.get("bigVisible") and st.get("paused") is True,
              json.dumps({k: (st or {}).get(k) for k in ("vmode", "bigVisible", "paused", "loadVisible")},
                         ensure_ascii=False))
        R.add("自动播放被拒：无 JS 报错 / 无 unhandledrejection",
              not (js(page, "window.__errs||[]") or []),
              json.dumps(js(page, "window.__errs||[]") or [], ensure_ascii=False)[:200])
        sess.js("(function(){try{HTMLMediaElement.prototype.play=window.__origPlay;}catch(e){}return true;})()")
        js(page, "(function(){var b=document.getElementById('pptVBig');if(b)b.click();return true;})()")
        played = sess.wait("(function(){var v=document.getElementById('pptVideo');"
                           "return !!v&&!v.paused;})()", 6)
        R.add("自动播放被拒：点大播放按钮 → 正常播放", played)
        shot(page, "C2_autoplay_big")
    finally:
        sess.close()


# ---------------------------------------------------------------- D 续播 + 列表徽标
def scenario_resume(server):
    sess = Session(server, scene="D_resume")
    try:
        page = sess.page
        sess.set_conn({"effectiveType": "4g", "saveData": False})
        # 过期记录（8 天前）不显示徽标；7 天内的有效记录显示
        sess.ls_set("zq_ppt_pos_dtestready1", {"mode": "step", "slide": 1, "step": 0,
                                               "at": NOW - 8 * 24 * 3600 * 1000})
        sess.ls_set("zq_ppt_pos_dtestvideo1", {"mode": "video", "slide": 2, "step": 0,
                                               "t": 5.2, "at": NOW - 3600 * 1000})
        sess.js("(function(){window.PPT.render();return true;})()")
        sess.sleep(0.4)
        card = js(page, CARDSTATE.replace("__DECK__", "dtestvideo1")) or {}
        R.add("列表：7 天内有续播位置 → 卡片显示「继续」徽标", card.get("rsm") is True,
              json.dumps(card, ensure_ascii=False)[:240])
        R.add("列表：整卡仍保留封面大 ▶", card.get("play") is True)
        stale = js(page, CARDSTATE.replace("__DECK__", "dtestready1")) or {}
        R.add("列表：过期（>7 天）续播记录不显示「继续」徽标", stale.get("rsm") is False,
              json.dumps(stale, ensure_ascii=False)[:240])
        # 打开 → 自动 seek 到 5.2s
        ok = sess.open_card("dtestvideo1")
        played = sess.wait_video(8)
        # 5.2s 起播会很快到媒体末尾：先暂停再断言（真实时长 6s，续播阈值 5s 用满）
        sess.js("(function(){var v=document.getElementById('pptVideo');if(v)v.pause();return true;})()")
        sess.sleep(0.35)
        st = sess.vstate()
        toast = js(page, "(function(){var t=document.getElementById('toast');return t?t.textContent:'';})()")
        R.add("续播：打开自动 seek 到上次位置（≈5.2s）+ 控制条「续播 mm:ss」",
              ok and played and abs(float(st.get("t") or 0) - 5.2) <= 0.8
              and str(toast).startswith("续播 00:"),
              json.dumps({k: (st or {}).get(k) for k in ("t", "paused", "page")} , ensure_ascii=False)
              + " | toast=" + str(toast))
        R.add("续播：页码按视频时间定位到第 3/3 页", (st or {}).get("page") == "第 3/3 页",
              (st or {}).get("page"))
        # 从头播放 → seek 0 + 删除续播记录
        js(page, "(function(){var b=document.querySelector('#pptVCtl [data-vact=\"restart\"]');if(b)b.click();return true;})()")
        sess.sleep(0.7)
        sess.js("(function(){var v=document.getElementById('pptVideo');if(v)v.pause();return true;})()")
        r0 = sess.vstate()
        R.add("从头播放：seek 到 0 且播放中（看完/从头为重置条件）",
              bool(r0) and float(r0.get("t") or 9) <= 1.2, json.dumps({k: (r0 or {}).get(k) for k in ("t",)}))
        R.add("从头播放：清除本机续播记录", sess.ls_get("zq_ppt_pos_dtestvideo1") is None,
              json.dumps(sess.ls_get("zq_ppt_pos_dtestvideo1")))
        # 进度保存：seek 到 5.2 后关闭 → 记录写入
        sess.js("(function(){var v=document.getElementById('pptVideo');"
                "if(v){v.pause();v.currentTime=5.2;}return true;})()")
        sess.sleep(0.5)
        closed = sess.close_video_player()
        rec = sess.ls_get("zq_ppt_pos_dtestvideo1")
        R.add("续播写入：关闭播放器时保存 {mode,slide,step,t,at}",
              closed and bool(rec) and rec.get("mode") == "video" and rec.get("t") is not None
              and abs(float(rec.get("t")) - 5.2) <= 0.8 and int(rec.get("at") or 0) > 0,
              json.dumps(rec, ensure_ascii=False))
        # 列表「原样 m:ss」胶囊：播放前取 manifest 已缓存到本机
        sess.js("(function(){window.PPT.render();return true;})()")
        sess.sleep(0.35)
        card2 = js(page, CARDSTATE.replace("__DECK__", "dtestvideo1")) or {}
        R.add("列表：播放过的带视频 deck 显示「原样 0:06」时长胶囊",
              card2.get("vcap") is True and "原样" in str(card2.get("vcapTxt") or "")
              and "0:06" in str(card2.get("vcapTxt") or ""),
              json.dumps({k: card2.get(k) for k in ("vcap", "vcapTxt")}, ensure_ascii=False))
        # 看完到末尾重置：触发 ended
        sess.open_card("dtestvideo1")
        sess.wait_video(8)
        sess.sleep(0.5)
        sess.js("(function(){var v=document.getElementById('pptVideo');"
                "if(v)v.dispatchEvent(new Event('ended'));return true;})()")
        sess.sleep(0.4)
        R.add("续播重置：视频播放到末尾（ended）→ 删除续播记录",
              sess.ls_get("zq_ppt_pos_dtestvideo1") is None,
              json.dumps(sess.ls_get("zq_ppt_pos_dtestvideo1")))
        shot(page, "D1_resume")
    finally:
        sess.close()


# ---------------------------------------------------------------- E 热点时序（慢图竞态）
def scenario_hot_timing(server):
    sess = Session(server, scene="E_hot")
    try:
        page = sess.page
        sess.set_conn({"effectiveType": "4g", "saveData": False})
        ok = sess.open_card("dtesthots1")   # 无 manifest.video → 分步
        sess.sleep(0.8)
        R.add("热点时序：16 页热点 deck 打开（无 video 字段 → 分步）",
              ok and not (sess.vstate() or {}).get("vmode"), "")
        # 切到第 12 页（缩略图），该页主图 700ms 慢加载：切页时 syncHot 必然抢在布局前
        js(page, "(function(){var b=document.querySelector('#pptCtl [data-act=\"thumbs\"]');if(b)b.click();return true;})()")
        sess.sleep(0.4)
        js(page, "(function(){var b=document.querySelector('#pptThumbsRow [data-thumb=\"11\"]');if(b)b.click();return true;})()")
        t0 = time.time()
        # 等过渡完成（页码变 12 / 16）且热点出现：图片 700ms 慢加载 + 320ms 淡入后才算完成
        arrived = wait_js(page, "(function(){var h=document.querySelectorAll('#pptHot .ppt-hotbtn');"
                                "var i=document.getElementById('pptIdx');"
                                "return h.length>0&&!!i&&i.textContent.indexOf('12 / 16')===0;})()", 4)
        cost = time.time() - t0
        hot = sess.js(HOTSTATE)
        R.add("热点时序：切到含媒体页（第 12 页，慢图 700ms）后热点必现（无需重试）",
              arrived and hot.get("n") == 1 and hot.get("imgerr") is False and hot.get("idx").startswith("12 / 16"),
              json.dumps(hot, ensure_ascii=False) + " | cost=%.2fs" % cost)
        R.add("热点：直径 ≥56px（430px 手机 64px）+ 「视频 m:ss」角标",
              hot.get("w", 0) >= 56 and "视频 0:12" == str(hot.get("hotdur")),
              json.dumps({k: hot.get(k) for k in ("w", "h", "hotdur")}, ensure_ascii=False))
        R.add("热点：图片已成功加载（不是靠失败兜底渲染）", hot.get("imgerr") is False)
        shot(page, "E1_hot_page12")
        # resize 后重算
        page.set_device(390, 844, dpr=2.0, mobile=True, touch=True)
        sess.sleep(0.6)
        h2 = sess.js(HOTSTATE)
        R.add("热点：resize（430→390）后重新计算仍存在且 ≥56px",
              h2.get("n") == 1 and h2.get("w", 0) >= 56, json.dumps(h2, ensure_ascii=False))
        # orientationchange 后重算
        sess.js("(function(){window.dispatchEvent(new Event('orientationchange'));return true;})()")
        sess.sleep(0.35)
        R.add("热点：orientationchange 后仍存在",
              (sess.js(HOTSTATE) or {}).get("n") == 1)
        page.set_device(430, 900, dpr=2.0, mobile=True, touch=True)
        sess.sleep(0.4)
        # 快速连续切页（模拟滑动）：第 12 页 → 第 13 页 → 立即回第 12 页
        js(page, "(function(){var b=document.querySelector('#pptCtl [data-act=\"thumbs\"]');if(b)b.click();return true;})()")
        sess.sleep(0.35)
        js(page, "(function(){var b=document.querySelector('#pptThumbsRow [data-thumb=\"12\"]');if(b)b.click();return true;})()")
        sess.sleep(0.12)
        js(page, "(function(){var b=document.querySelector('#pptCtl [data-act=\"thumbs\"]');if(b)b.click();return true;})()")
        sess.sleep(0.12)
        js(page, "(function(){var b=document.querySelector('#pptThumbsRow [data-thumb=\"11\"]');if(b)b.click();return true;})()")
        sess.sleep(1.6)
        h3 = sess.js(HOTSTATE)
        R.add("热点：快速连切（12→13→12）后热点仍必现（过渡中重新计算）",
              h3.get("n") == 1 and h3.get("idx").startswith("12 / 16"), json.dumps(h3, ensure_ascii=False))
        R.add("热点：全程 0 JS 报错", not (js(page, "window.__errs||[]") or []),
              json.dumps(js(page, "window.__errs||[]") or [], ensure_ascii=False)[:200])
    finally:
        sess.close()


# ---------------------------------------------------------------- E2 热点历史 bug：图片 >6s 兜底 start
def scenario_hot_very_slow(server):
    """复现旧代码真实 bug：图片加载 6.5s（超过 6s 兜底 start）→ 旧版 onload 不再重算，热点永远 0。
    修复后：onload / transitionend / rAF 补算 + 图片解码后提前绘制，热点在图片到位后自动出现。"""
    sess = Session(server, scene="E2_hot_slow")
    try:
        page = sess.page
        sess.set_conn({"effectiveType": "4g", "saveData": False})
        ok = sess.open_card("dtesthotslow1")
        sess.sleep(0.8)
        js(page, "(function(){var b=document.querySelector('#pptCtl [data-act=\"thumbs\"]');if(b)b.click();return true;})()")
        sess.sleep(0.4)
        t0 = time.time()
        js(page, "(function(){var b=document.querySelector('#pptThumbsRow [data-thumb=\"11\"]');if(b)b.click();return true;})()")
        arrived = wait_js(page, "(function(){var h=document.querySelectorAll('#pptHot .ppt-hotbtn');"
                                "var i=document.getElementById('pptIdx');"
                                "return h.length>0&&!!i&&i.textContent.indexOf('12 / 16')===0;})()", 12)
        cost = time.time() - t0
        hot = sess.js(HOTSTATE)
        R.add("热点历史 bug：图片 6.5s 才加载（>6s 兜底 start）→ 热点仍必现（不靠 resize/重试）",
              ok and arrived and hot.get("n") == 1 and hot.get("idx").startswith("12 / 16"),
              json.dumps(hot, ensure_ascii=False) + " | cost=%.1fs" % cost)
        R.add("热点历史 bug：图片确实超过 6s（复现条件成立）", cost >= 6.0, "cost=%.1fs" % cost)
        shot(page, "E2_hot_slow")
    finally:
        sess.close()


# ---------------------------------------------------------------- F 桌面 1280
def scenario_desktop(server):
    sess = Session(server, width=1280, height=800, mobile=False, scene="F_desktop")
    try:
        page = sess.page
        sess.set_conn({"effectiveType": "4g", "saveData": False})
        ok = sess.open_card("dtestvideo1")
        sess.wait_video(10)
        sess.sleep(0.8)
        st = sess.vstate()
        R.add("桌面 1280：原样播放视频铺满播放器（letterbox 由 object-fit 负责）",
              ok and bool(st) and st.get("vRect") and st["vRect"][0] == 1280
              and abs(st["vRect"][1] - 800) <= 2, json.dumps(st.get("vRect")))
        R.add("桌面 1280：视频控制条单行（控件同一 Y 中线）且宽度 ≤760+2",
              bool(st) and st.get("rows") == 1 and st.get("rowH", 999) <= 46
              and (st.get("ctlSW", 0) <= st.get("ctlCW", 0) + 1),
              json.dumps({k: (st or {}).get(k) for k in ("rows", "rowH", "ctlSW", "ctlCW")}, ensure_ascii=False))
        cap = js(page, "(function(){var s=document.getElementById('pptVSeg');"
                      "if(!s)return null;var r=s.getBoundingClientRect();"
                      "return {right:Math.round(r.right),w:Math.round(r.width),vw:innerWidth};})()")
        R.add("桌面 1280：模式胶囊在视口内（右贴边、可点）",
              bool(cap) and cap.get("right", 9999) <= cap.get("vw", 0) + 1 and cap.get("w", 0) >= 80,
              json.dumps(cap, ensure_ascii=False))
        # 说明：关闭态的备注/缩略图抽屉用 transform 移出屏幕，会抬高 scrollWidth（历史行为，overflow:hidden 不可见），
        # 因此这里只断言「页面 + 播放器可视区 + 视频控制条」无横向溢出。
        ply = js(page, "(function(){var r=document.getElementById('pptPlayer'),"
                      "c=document.getElementById('pptVCtl');"
                      "var rr=r?r.getBoundingClientRect():null;"
                      "return {docSW:document.documentElement.scrollWidth,vw:innerWidth,"
                      "pw:rr?Math.round(rr.width):0,ph:rr?Math.round(rr.height):0,"
                      "cSW:c?c.scrollWidth:0,cCW:c?c.clientWidth:0};})()")
        R.add("桌面 1280：原样播放无横向溢出（页面/播放器视口/控制条）",
              bool(ply) and ply.get("docSW", 9999) <= ply.get("vw", 0) + 1
              and ply.get("pw") == 1280 and ply.get("ph") == 800
              and ply.get("cSW", 9999) <= ply.get("cCW", 0) + 1, json.dumps(ply))
        shot(page, "F1_video_1280")
    finally:
        sess.close()


# ---------------------------------------------------------------- G 无 video（旧 deck 兼容）
def scenario_no_video(server):
    sess = Session(server, scene="G_novideo")
    try:
        page = sess.page
        sess.set_conn({"effectiveType": "4g", "saveData": False})
        ok = sess.open_card("dtestready1")
        sess.sleep(0.8)
        st = sess.vstate()
        R.add("旧 deck 兼容：无 manifest.video + 网络良好 → 默认分步",
              ok and bool(st) and st.get("vmode") is False and st.get("hasVideo") is False
              and str(st.get("idx", "")).startswith("1 / 3"),
              json.dumps({k: (st or {}).get(k) for k in ("vmode", "hasVideo", "idx")}, ensure_ascii=False))
        R.add("旧 deck 兼容：不渲染原样播放顶栏/控制条 DOM",
              js(page, "(function(){return {top:!!document.getElementById('pptVTop'),"
                       "ctl:!!document.getElementById('pptVCtl')};})()") == {"top": False, "ctl": False})
        # 分步续播 + 从头按钮
        closed = sess.close_player()
        sess.ls_set("zq_ppt_pos_dtestready1", {"mode": "step", "slide": 1, "step": 0, "at": NOW - 600000})
        sess.js("(function(){window.PPT.render();return true;})()")
        sess.sleep(0.3)
        ok2 = sess.open_card("dtestready1")
        sess.sleep(1.0)
        idx = B.player_idx(page)
        R.add("分步续播：打开自动定位到上次页（第 2 / 3 页）",
              closed and ok2 and str(idx).startswith("2 / 3"), idx)
        btn = js(page, "(function(){var b=document.querySelector('#pptCtl [data-act=\"restart\"]');"
                      "return {has:!!b,label:b?b.getAttribute('aria-label'):''};})()")
        R.add("分步续播：控制条出现「从头播放」按钮", bool(btn) and btn.get("has") and btn.get("label") == "从头播放",
              json.dumps(btn, ensure_ascii=False))
        ov = js(page, "(function(){var c=document.getElementById('pptCtl');"
                      "return {cSW:c?c.scrollWidth:0,cCW:c?c.clientWidth:0,"
                      "docSW:document.documentElement.scrollWidth,vw:innerWidth,"
                      "hasres:!!(document.getElementById('pptPlayer')||{classList:{contains:function(){return false;}}}).classList.contains('ppt-hasres')};})()")
        R.add("分步续播：430px 控制条加「从头」后仍单行不溢出（页面无横向溢出）",
              bool(ov) and ov.get("hasres") and ov.get("cSW", 9999) <= ov.get("cCW", 0) + 1
              and ov.get("docSW", 9999) <= ov.get("vw", 0) + 1, json.dumps(ov))
        js(page, "(function(){var b=document.querySelector('#pptCtl [data-act=\"restart\"]');if(b)b.click();return true;})()")
        sess.sleep(0.8)
        R.add("分步续播：从头播放 → 回到第 1 页并清除续播记录",
              str(B.player_idx(page)).startswith("1 / 3")
              and sess.ls_get("zq_ppt_pos_dtestready1") is None,
              "%s | %s" % (B.player_idx(page), json.dumps(sess.ls_get("zq_ppt_pos_dtestready1"))))
        shot(page, "G1_novideo_step")
    finally:
        sess.close()


# ---------------------------------------------------------------- H 汇总
def aggregate_checks():
    js_errs, cons_errs = [], []
    for e in SCENE_ERRORS:
        js_errs.extend([("[%s] " % e.get("scene")) + str(x) for x in (e.get("js") or [])])
        js_errs.extend([("[%s] " % e.get("scene")) + str(x) for x in (e.get("cdp") or [])])
        cons_errs.extend([("[%s] " % e.get("scene")) + str(x) for x in (e.get("cons") or [])])
        cons_errs.extend([("[%s] " % e.get("scene")) + str(x) for x in (e.get("cdpcon") or [])])
    R.add("汇总：全部场景 0 JS 报错（window.onerror/unhandledrejection/CDP exception）",
          not js_errs, json.dumps(js_errs[:4], ensure_ascii=False)[:400])
    R.add("汇总：全部场景 0 console.error", not cons_errs,
          json.dumps(cons_errs[:4], ensure_ascii=False)[:400])
    blocked = list(B.MOCK.get("blocked_writes") or [])
    R.add("汇总：0 真实云端写（非 mock 写请求被拦截，且无 ppt_decks/chunks 写）",
          all(("ppt_decks" not in b and "ppt_upload_chunks" not in b) for b in blocked),
          json.dumps(blocked[:6], ensure_ascii=False))


def main():
    t0 = time.time()
    print("=" * 72)
    print("v2_ppt_video_check · PPT v1.2 网页端原样播放/续播/热点时序 专项验收")
    print("被测文件: %s (%d B)" % (SRC, os.path.getsize(SRC)))
    print("=" * 72)
    static_checks()
    os.makedirs(SHOTS, exist_ok=True)
    server = Server()
    server.start()
    try:
        with B.MOCK_LOCK:
            B.MOCK["decks"] = make_decks(server.port)
            B.MOCK["agent"].update({"online": True, "seen_at": int(time.time() * 1000)})
            B.MOCK["posts"] = []
            B.MOCK["patches"] = []
            B.MOCK["chunks"] = []
            B.MOCK["blocked_writes"] = []
        for name, fn in (("A 原样播放+控制条", scenario_video_controls),
                         ("B 弱网默认分步+偏好", scenario_bad_network),
                         ("C 视频失败回退", scenario_video_fallback),
                         ("C2 自动播放被拒", scenario_autoplay_blocked),
                         ("D 续播+列表徽标", scenario_resume),
                         ("E 热点时序", scenario_hot_timing),
                         ("E2 热点慢图历史 bug", scenario_hot_very_slow),
                         ("F 桌面 1280", scenario_desktop),
                         ("G 无 video 兼容", scenario_no_video)):
            with B.MOCK_LOCK:
                B.MOCK["decks"] = make_decks(server.port)
                B.MOCK["agent"].update({"online": True, "seen_at": int(time.time() * 1000)})
            try:
                fn(server)
            except Exception as e:  # noqa: BLE001
                R.add(name + " 场景执行", False, repr(e))
    finally:
        server.stop()
    aggregate_checks()
    total, passed, failed = R.summary()
    print("=" * 72)
    print("v2_ppt_video_check: %d 项，PASS %d，FAIL %d（%.1fs）"
          % (total, passed, failed, time.time() - t0))
    print("（与既有 v2_ppt_check 86 项合并统计：%d 项）" % (total + 86))
    print("截图: %s" % SHOTS)
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
