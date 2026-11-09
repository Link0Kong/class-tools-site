# -*- coding: utf-8 -*-
"""v2 专项：网页课表「横向滑动内容超出白卡框」修复验收（裁剪 + 无泄漏）

背景：用户反馈「网页课表功能，滑动时会超出课表框」。
课表页横滑（拖动跟手 / 松手回弹 / 换周飞出飞入）时全局滑动引擎把 `transform:translate3d(±W px)`
直接写在 `.ttmain` 上，而 `.ttcard/.ttbody/.ttmain` 都没有 `overflow` 裁剪 → 拖动与换周动画期间
`.ttmain` 里的 7 天周表会画到白色圆角卡片（`.ttcard`）之外（手机左右页边、桌面右侧 `.ttside`）。
小程序 `pages/tt/tt.wxss` 早已 `.ttcard{overflow:hidden}` 并在注释里说明「左右滑动飞出/飞入时裁剪在卡片内」。

做法（复用 `v2_swipe_perf.py` 的 CDP 合成 touch / Emulation 与 `reset_check.py` 的注入方式）：
- 复制 `tools/index.html`（或 --src 指定副本）到临时 preview.html，在 <head> 注入：
  假身份（localStorage zq_class_identity）+ 合成 7 天课表（含周六/周日，14 门）+ fetch mock
  （拦截 tcloudbasegateway / tt.json，绝不碰真实云端 API）+ 固定时间（保证截图逐像素可复现）；
- headless Edge + CDP：Emulation 设 360/390/430/1280 视口，Input.dispatchTouchEvent 合成真实触摸；
- 每档流程：静止截图 → 小拖回弹各帧 → 拖动按住不放（截图）→ 松手换周飞出/飞入各帧 → 回位静止；
  用 PIL 逐像素对比：
    * `.ttcard` 矩形之外的相邻区域必须与静止帧**完全一致**（无泄漏）；
    * 卡片内部必须有明显变化（证明动画在动，而不是把滑动动画关掉）；
    * 1280 桌面额外断言右侧 `.ttside`（周导航/下一节/全部课程）区域与静止帧一致（动画不盖侧栏）；
- 功能断言：7 天星期列 / 14 个课程格与数据一致、周末列可通过 `.tscroll` 横向滚动看到、
  横滑切周（#tWeekLbl 周次变化）、课程点击弹层、上一周/下一周按钮、周/日视图按钮；
- 四档 360/390/430/1280：静止与拖动中均无页面横向溢出、0 JS 错误、0 console.error。
- 「静止帧与修复前静止帧逐像素一致」只比较 `.tthead` 以下的课表主体（2026-11-08 诊断/登录增量后
  `.ttacts` 新增「登录教务」按钮，头部相对旧基线整体位移；裁剪/泄漏/手感断言不受影响、不删减）。

用法：
  python tests\\v2_tt_frame_check.py                       # 测当前 tools/index.html（tag=post）
  python tests\\v2_tt_frame_check.py --src <副本.html>     # 测任意副本（修复前基线复现）
  python tests\\v2_tt_frame_check.py --tag pre             # 截图/报告前缀（默认 post）
  TT_FRAME_SRC / TT_FRAME_TAG 环境变量等价。
  端口默认 HTTP 8937 / CDP 9537（可用 TTF_HTTP_PORT / TTF_CDP_PORT 覆盖）。
退出码 0 = 全绿；输出 PASS/FAIL 计数。
截图存 tools/tests/_shots_tt_frame/{tag}_{宽}_{场景}.png
"""
import base64
import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import websocket
except Exception:
    print("[v2_tt_frame_check] 缺少 websocket-client（pip install websocket-client）")
    sys.exit(2)
try:
    from PIL import Image, ImageChops
except Exception:
    print("[v2_tt_frame_check] 缺少 Pillow（pip install pillow）")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))       # tools/tests
ROOT = os.path.dirname(HERE)                            # tools
SHOTS = os.path.join(HERE, "_shots_tt_frame")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HTTP_PORT = int(os.environ.get("TTF_HTTP_PORT") or 8937)
CDP_PORT = int(os.environ.get("TTF_CDP_PORT") or 9537)
PREVIEW = "preview.html"

SID = "3260709999"
NAME = "测试同学"
TOKEN = "test-token-ttframe"

# 固定「当前时间」：2026-11-06（周五）09:30 +08:00 —— 第 9 周、今天还有下一节课
# 目的：周次/日期/「下一节」倒计时/今天高亮全部确定，修复前/后两次跑能逐像素对比
FIXED_MS = int(datetime(2026, 11, 6, 9, 30, 0, tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000)

VIEWPORTS = [(360, 780, True), (390, 844, True), (430, 932, True), (1280, 800, False)]

# 合成 7 天课表：包含周六/周日（每天 2 门、不冲突、全部 1-16 周）
COURSES = [
    {"name": "高等数学", "teacher": "龚志伟", "room": "自强楼(教室01104)", "day": 0, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"},
    {"name": "大学英语", "teacher": "花爱阳", "room": "自强楼(教室01202)", "day": 0, "start": 3, "end": 4, "weeks": "1-16", "parity": "all"},
    {"name": "数据结构", "teacher": "林立", "room": "厚德楼(教室02210)", "day": 1, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"},
    {"name": "大学物理", "teacher": "沈国俊", "room": "厚德楼(教室02111)", "day": 1, "start": 6, "end": 7, "weeks": "1-16", "parity": "all"},
    {"name": "线性代数", "teacher": "张翠萍", "room": "自强楼(教室01105)", "day": 2, "start": 3, "end": 4, "weeks": "1-16", "parity": "all"},
    {"name": "概率论与数理统计", "teacher": "陈玉鹏", "room": "自强楼(教室01203)", "day": 2, "start": 8, "end": 9, "weeks": "1-16", "parity": "all"},
    {"name": "中国近现代史纲要", "teacher": "林绸花", "room": "厚德楼(教室02405)", "day": 3, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"},
    {"name": "计算机基础", "teacher": "张翠萍", "room": "自强楼(01514-计算机实验室2)", "day": 3, "start": 5, "end": 6, "weeks": "1-16", "parity": "all"},
    {"name": "形势与政策", "teacher": "林心影", "room": "厚德楼(教室02405)", "day": 4, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"},
    {"name": "大学体育", "teacher": "甘子怡", "room": "体育场篮球区(篮球场1-3)", "day": 4, "start": 6, "end": 7, "weeks": "1-16", "parity": "all"},
    {"name": "化学实验", "teacher": "陈丽晶", "room": "教学综合楼(实验楼302)", "day": 5, "start": 3, "end": 4, "weeks": "1-16", "parity": "all"},
    {"name": "音乐鉴赏", "teacher": "谢舒婷", "room": "教学综合楼(音乐教室)", "day": 5, "start": 8, "end": 9, "weeks": "1-16", "parity": "all"},
    {"name": "心理健康教育", "teacher": "温建恩", "room": "厚德楼(教室02101)", "day": 6, "start": 2, "end": 3, "weeks": "1-16", "parity": "all"},
    {"name": "美术鉴赏", "teacher": "汤艳丽", "room": "教学综合楼(美术教室)", "day": 6, "start": 6, "end": 7, "weeks": "1-16", "parity": "all"},
]
COURSE_NAMES = sorted(c["name"] for c in COURSES)
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
BASE_WEEK = 9  # termStart=2026-09-07 + FIXED_MS(2026-11-06) → 第 9 周

MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": "", "badge": "", "is_admin": False} for i in range(1, 71)]

SEED = {
    "course": COURSES,
    "termStart": "2026-09-07",
    "ttView": "week",
    "homeTools": ["draw", "hw", "nt", "tt"],
}

# ---------------------------------------------------------------------------
# 注入：错误收集 / console.error 收集 / 固定时间 / fetch mock / 假身份 + 课表种子
# ---------------------------------------------------------------------------
INJECT_TPL = """<script>
(function(){
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||e));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));_ce.apply(console,arguments);};
/* 固定时间（截图逐像素可复现；不影响浏览器内部计时/动画） */
(function(){
  var _D=window.Date, FIXED=__FIXED__;
  function D2(){
    var a=Array.prototype.slice.call(arguments);
    if(!(this instanceof D2))return new _D(FIXED).toString();
    if(!a.length)return new _D(FIXED);
    return new (Function.prototype.bind.apply(_D,[null].concat(a)));
  }
  D2.prototype=_D.prototype; D2.now=function(){return FIXED;}; D2.parse=_D.parse; D2.UTC=_D.UTC;
  window.Date=D2;
})();
var _f=window.fetch;
window.fetch=function(u,o){
  var s=String((u&&u.url!==undefined)?u.url:u);
  function ok(v){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(v);},text:function(){return Promise.resolve("");}});}
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("class_members")>=0)return ok(__MEMBERS__);
    if(s.indexOf("/notices")>=0)return ok([]);
    if(s.indexOf("/homework")>=0)return ok([]);
    if(s.indexOf("/marks")>=0)return ok([]);
    if(s.indexOf("/fitrecs")>=0)return ok([]);
    if(s.indexOf("/userdata")>=0)return ok([]);
    return ok([]);
  }
  if(s.indexOf("tt.json")>=0)return ok({c:[],t:"2026-09-07",meta:{fetchedAt:__FIXED__}});
  return _f.apply(this,arguments);
};
try{
  localStorage.setItem("zq_class_identity",JSON.stringify({token:"__TOKEN__",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:__FIXED__}));
  localStorage.setItem("zq_tools_v2___SID__",JSON.stringify(__SEED__));
}catch(e){}
})();
</script>"""

# 在主 IIFE 结束前注入调试钩子（与 v2_swipe_perf.py 相同做法）
HOOK = r"""
window.__ttf={bootDone:function(){return typeof __bootRefreshDone!=="undefined"&&__bootRefreshDone;},
  gotoTab:gotoTab,renderTT:renderTT,
  animating:function(){return animating;},
  errs:function(){return window.__errs||[];},cerrs:function(){return window.__cerrs||[];}};
"""

FREEZE_JS = r"""(function(){if(document.getElementById('__ttf_noanim'))return true;
var st=document.createElement('style');st.id='__ttf_noanim';
st.textContent='*{animation:none!important}*::before,*::after{animation:none!important}';
document.head.appendChild(st);return true;})()"""

PROBE_JS = r"""
window.__ttfProbe=function(){
  var q=function(s){return document.querySelector(s);};
  function R(el){if(!el)return null;var r=el.getBoundingClientRect();
    return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom};}
  var card=q('.ttcard'),grid=q('#tGrid'),main=q('.ttmain'),frame=q('.ttframe'),
      side=q('.ttside'),wk=q('#tWeekLbl'),body=q('.ttbody'),hint=q('#tHint'),daybar=q('#tDayBar'),
      head=q('.tthead'),acts=q('.ttacts');
  function cs(el,p){if(!el)return '';try{return getComputedStyle(el)[p]||'';}catch(e){return '';}}
  function tx(){var s=String((main&&main.style&&main.style.transform)||'');
    var m=s.match(/translate3d\((-?[0-9.]+)px/);return m?parseFloat(m[1]):0;}
  return {
    card:R(card),main:R(main),frame:R(frame),side:R(side),grid:R(grid),
    head:R(head),acts:R(acts),
    frameOverflow:frame?cs(frame,'overflow'):'(none)',
    cardOverflow:card?cs(card,'overflow'):'(none)',
    bodyDisplay:body?cs(body,'display'):'',
    sideDisplay:side?cs(side,'display'):'',
    frameParentCls:(frame&&frame.parentNode)?String(frame.parentNode.className):'',
    mainParentCls:(main&&main.parentNode)?String(main.parentNode.className):'',
    frameHasGrid:!!(frame&&grid&&frame.contains(grid)),
    gridInMain:!!(main&&grid&&main.contains(grid)),
    week:(wk?wk.textContent:''),
    day:(function(){var n=new Date();return (n.getDay()===0?6:n.getDay()-1);})(),
    cols:document.querySelectorAll('#tGrid thead th:not(.pd)').length,
    colTexts:Array.prototype.map.call(document.querySelectorAll('#tGrid thead th:not(.pd)'),
      function(e){return String((e.firstChild&&e.firstChild.nodeValue)||'').trim();}),
    crs:document.querySelectorAll('#tGrid .crs').length,
    crsNames:Array.prototype.map.call(document.querySelectorAll('#tGrid .crs'),
      function(e){return e.getAttribute('data-cname')||'';}),
    tx:tx(),
    innerW:window.innerWidth,
    scrollW:document.documentElement.scrollWidth,
    bodyScrollW:document.body.scrollWidth,
    tscrollSW:grid?grid.scrollWidth:0,
    tscrollCW:grid?grid.clientWidth:0,
    hintDisplay:hint?cs(hint,'display'):'',
    dayBarDisplay:daybar?cs(daybar,'display'):'',
    gridDisplay:grid?cs(grid,'display'):'',
    panelDisplay:(function(){var p=document.getElementById('ttCPanel');return p?cs(p,'display'):'(none)';})(),
    panelText:(function(){var p=document.getElementById('ttCBody');return p?p.textContent:' ';})(),
    errs:(window.__errs||[]).length,
    cerrs:(window.__cerrs||[]).length
  };
};
"""

# ---------------------------------------------------------------------------
# CDP
# ---------------------------------------------------------------------------
class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=40)
        self._id = 0

    def send(self, method, params=None, timeout=40):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                time.sleep(0.01)
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s -> %s" % (method, json.dumps(msg["error"], ensure_ascii=False)))
                return msg.get("result", {})
        raise TimeoutError(method)

    def eval(self, expr, timeout=40):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True}, timeout=timeout)
        res = r.get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError("JS: " + str(res.get("description"))[:400])
        return res.get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def get_ws(port):
    t0 = time.time()
    while time.time() - t0 < 30:
        try:
            data = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=2).read())
            for t in data:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("no CDP page on %d" % port)


def wait_until(cdp, expr, timeout=25, interval=0.08):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cdp.eval(expr):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def touch(cdp, points, kind):
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [
        {"x": p[0], "y": p[1], "id": i + 1} for i, p in enumerate(points)]})


def mouse_click(cdp, x, y):
    for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
        params = {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1}
        cdp.send("Input.dispatchMouseEvent", params)


# ---------------------------------------------------------------------------
# 截图 / 像素对比
# ---------------------------------------------------------------------------
class Pixels:
    def __init__(self):
        self.cache = {}

    def img(self, path):
        if path not in self.cache:
            self.cache[path] = Image.open(path).convert("RGB")
        return self.cache[path]

    def diff(self, path_a, path_b, box=None, tol=3):
        """区域像素差计数（单通道差 > tol 记 1 像素）。box=None 全图。"""
        a, b = self.img(path_a), self.img(path_b)
        if a.size != b.size:
            return 10 ** 9
        if box is not None:
            W, H = a.size
            x0 = max(0, int(box[0]))
            y0 = max(0, int(box[1]))
            x1 = min(W, int(box[2]))
            y1 = min(H, int(box[3]))
            if x1 <= x0 or y1 <= y0:
                return 0
            a, b = a.crop((x0, y0, x1, y1)), b.crop((x0, y0, x1, y1))
        d = ImageChops.difference(a, b)
        r, g, bl = d.split()
        m = ImageChops.lighter(ImageChops.lighter(r, g), bl)
        hist = m.histogram()
        return sum(hist[tol + 1:])

    def outside_boxes(self, card, img_size):
        """卡片矩形之外的 4 条相邻带（top/bottom/left/right）。"""
        W, H = img_size
        x0 = max(0, int(card["x"]))
        y0 = max(0, int(card["y"]))
        x1 = min(W, int(card["right"] + 0.999))
        y1 = min(H, int(card["bottom"] + 0.999))
        return [(0, 0, W, y0), (0, y1, W, H), (0, y0, x0, y1), (x1, y0, W, y1)]

    def outside_diff(self, static_path, frame_path, card):
        a = self.img(static_path)
        total = 0
        for box in self.outside_boxes(card, a.size):
            total += self.diff(static_path, frame_path, box)
        return total


def shot(cdp, tag, W, name):
    r = cdp.send("Page.captureScreenshot", {"format": "png", "fromSurface": True,
                                            "captureBeyondViewport": False})
    path = os.path.join(SHOTS, "%s_%d_%s.png" % (tag, W, name))
    with open(path, "wb") as f:
        f.write(base64.b64decode(r["data"]))
    return path


# ---------------------------------------------------------------------------
# 页面构建
# ---------------------------------------------------------------------------
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Q(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


def build_preview(src, out_path):
    html = open(src, encoding="utf-8", newline="").read()
    idx = html.rfind("})();")
    if idx < 0:
        raise SystemExit("main script end not found: " + src)
    hook = HOOK
    inject = (INJECT_TPL
              .replace("__FIXED__", str(FIXED_MS))
              .replace("__MEMBERS__", json.dumps(MEMBERS, ensure_ascii=False))
              .replace("__SEED__", json.dumps(SEED, ensure_ascii=False))
              .replace("__TOKEN__", TOKEN)
              .replace("__SID__", SID)
              .replace("__NAME__", NAME))
    html = html[:idx] + hook + "\r\n" + html[idx:]
    if '<meta charset="utf-8">' in html:
        html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + inject, 1)
    else:
        html = html.replace("<head>", "<head>" + inject, 1)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    return html


# ---------------------------------------------------------------------------
# 单视口检查
# ---------------------------------------------------------------------------
class Report:
    def __init__(self, W):
        self.W = W
        self.items = []

    def chk(self, name, ok, note=""):
        self.items.append({"name": "[%d] %s" % (self.W, name), "ok": bool(ok),
                           "note": str(note)[:400]})
        icon = "PASS" if ok else "FAIL"
        print("  [%s] [%d] %s%s" % (icon, self.W, name, (("  | " + str(note)) if note else "")))
        return bool(ok)


def _label_week(txt):
    m = re.search(r"(\d+)", str(txt or ""))
    return int(m.group(1)) if m else None


def run_viewport(cdp, W, H, mobile, tag, save_all, pix):
    R = Report(W)
    stats = {}
    cdp.send("Emulation.setDeviceMetricsOverride",
             {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": bool(mobile)})
    cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
    cdp.send("Page.navigate", {"url": "http://127.0.0.1:%d/%s" % (HTTP_PORT, PREVIEW)})
    boot = wait_until(cdp, "!!(window.__ttf&&__ttf.bootDone&&__ttf.bootDone())", 30)
    R.chk("页面启动 + 假身份通过（身份门禁后进入应用）", boot)
    if not boot:
        return R, stats
    cdp.eval(PROBE_JS)
    cdp.eval("__ttf.gotoTab('tt')")
    time.sleep(0.35)
    cdp.eval("(function(){var b=document.querySelector('#tViewSeg button[data-ttview=\"week\"]');"
             "if(b&&!b.classList.contains('on'))b.click();return true;})()")
    wait_until(cdp, "document.querySelectorAll('#tGrid thead th:not(.pd)').length>0", 10)
    time.sleep(0.2)
    cdp.eval(FREEZE_JS)          # 冻结装饰性 CSS 动画（crsIn / 下一节圆点），保证像素对比稳定
    cdp.eval("window.scrollTo(0,0)")
    time.sleep(0.45)

    # ---------------- 静止状态：DOM 完整性 ----------------
    st = cdp.eval("__ttfProbe()")
    stats["static"] = {k: st.get(k) for k in ("week", "cols", "colTexts", "crs", "card",
                                              "frame", "side", "frameOverflow", "bodyDisplay",
                                              "innerW", "scrollW", "tscrollSW", "tscrollCW",
                                              "hintDisplay", "gridDisplay")}
    base_week = _label_week(st.get("week"))
    R.chk("静止：周次标签解析为第 %d 周" % BASE_WEEK, base_week == BASE_WEEK,
          st.get("week"))
    R.chk("静止：星期列 = 7（含周六/周日）", st.get("cols") == 7,
          "cols=%s texts=%s" % (st.get("cols"), ",".join(st.get("colTexts") or [])))
    R.chk("静止：星期列顺序 = 周一..周日", (st.get("colTexts") or []) == WEEKDAYS,
          str(st.get("colTexts")))
    R.chk("静止：课程格 = 14（7 天 × 2 门）", st.get("crs") == 14, "crs=%s" % st.get("crs"))
    R.chk("静止：课程名与合成数据一致", sorted(st.get("crsNames") or []) == COURSE_NAMES,
          "missing=%s" % (set(COURSE_NAMES) - set(st.get("crsNames") or [])))
    card = st.get("card") or {}
    inner_w = int(st.get("innerW") or W)
    R.chk("静止：无页面横向溢出", int(st.get("scrollW") or 0) <= inner_w + 1,
          "innerW=%s scrollW=%s" % (st.get("innerW"), st.get("scrollW")))
    R.chk("静止：白卡在视口内（左右不越界）",
          card.get("x", -1) >= 0 and card.get("right", 9999) <= inner_w + 1,
          "card=%s" % json.dumps({k: round(card.get(k, 0), 1) for k in ("x", "right")}))

    # 7 天表在 .tscroll 里横向可滚动时，周末列必须能滚动到完整可见（无裁剪损失）
    weekend = cdp.eval(r"""(function(){
      var g=document.getElementById('tGrid');
      var ths=g.querySelectorAll('thead th:not(.pd)');
      if(!ths.length)return {ok:false};
      var gr=g.getBoundingClientRect();
      g.scrollLeft=g.scrollWidth;
      var last=ths[ths.length-1].getBoundingClientRect();
      var first=ths[0].getBoundingClientRect();
      var ok=last.right<=gr.right+1.5&&last.width>4;
      var atEndOk=first.left<gr.left;  /* 说明确实发生了横向滚动 */
      g.scrollLeft=0;
      return {ok:ok,atEndOk:atEndOk,lastRight:last.right,grRight:gr.right,
        sw:g.scrollWidth,cw:g.clientWidth};
    })()""")
    R.chk("静止：周末列可横向滚到完整可见（.tscroll 裁剪正常）",
          bool(weekend and weekend.get("ok")), json.dumps(weekend))
    time.sleep(0.25)

    static_path = shot(cdp, tag, W, "static")
    stats["static_shot"] = static_path
    # 修复前后静止帧逐像素一致（无裁剪损失）—— 若目录里已有 pre 帧则自动比对。
    # 2026-11-08 诊断/登录增量后 .ttacts 新增「登录教务」按钮 → .tthead 操作区相对旧基线整体位移；
    # 本断言只用于证明「静止课表主体无裁剪损失」，因此仅比较 .tthead 以下的课表主体（白卡以内），
    # 全帧裁剪 / 框外泄漏 / 手感断言均保持不变（见下方场景）。
    pre_static = os.path.join(SHOTS, "pre_%d_static.png" % W)
    if tag != "pre" and os.path.isfile(pre_static):
        head = st.get("head") or {}
        body_top = int(head.get("bottom", 0)) + 2 if head else int(card.get("y", 0))
        body_box = [card.get("x", 0), min(body_top, int(card.get("bottom", 0))),
                    card.get("right", inner_w), card.get("bottom", 0)]
        d = pix.diff(pre_static, static_path, body_box)
        R.chk("静止帧与修复前静止帧逐像素一致（无裁剪损失；只比较 .tthead 以下课表主体）", d == 0,
              "diff=%d box=%s" % (d, json.dumps([round(float(v), 1) for v in body_box])))

    # 第二个「超出框」来源排查：7 天周表 min-width:428px，在 .tscroll 里横向滚动时
    # 内容必须被 .tscroll 自身裁剪（滚动中不得漏到白卡外）。
    cdp.eval("(function(){var g=document.getElementById('tGrid');g.scrollLeft=g.scrollWidth;return true;})()")
    time.sleep(0.18)
    scroll_end = shot(cdp, tag, W, "tscroll_end")
    d_scroll = pix.outside_diff(static_path, scroll_end, card)
    cdp.eval("(function(){var g=document.getElementById('tGrid');g.scrollLeft=0;return true;})()")
    time.sleep(0.18)
    R.chk("静止：.tscroll 横向滚到末尾时内容不超出卡片（第二来源排查）",
          d_scroll <= 8, "框外差异像素=%d" % d_scroll)

    # ---------------- 结构断言（修复实现存在） ----------------
    R.chk("结构：.ttmain 外层存在裁剪容器 .ttframe 且在 .ttbody 内",
          bool(st.get("frame")) and "ttbody" in (st.get("frameParentCls") or "")
          and st.get("frameHasGrid") and "ttframe" in (st.get("mainParentCls") or ""),
          "frameOverflow=%s frameParent=%s" % (st.get("frameOverflow"), st.get("frameParentCls")))
    R.chk("结构：裁剪容器 overflow 为 hidden", (st.get("frameOverflow") or "").startswith("hidden"),
          "overflow=%s" % st.get("frameOverflow"))
    if W >= 1024:
        side = st.get("side") or {}
        R.chk("桌面：课表主区+右侧栏为两栏 grid（侧栏存在）",
              (st.get("bodyDisplay") == "grid") and side.get("w", 0) > 100,
              "display=%s side.w=%s" % (st.get("bodyDisplay"), round(side.get("w", 0), 1)))
        R.chk("桌面：主列与侧栏不重叠（裁剪区止于右侧栏之前）",
              bool(st.get("frame")) and (st.get("frame") or {}).get("right", 1e9) <= side.get("x", -1) + 1,
              "frame.right=%s side.x=%s" % (round((st.get("frame") or {}).get("right", 0), 1),
                                            round(side.get("x", 0), 1)))
        side_box = [side.get("x", 0), side.get("y", 0), side.get("right", 0), side.get("bottom", 0)]
    else:
        side_box = None

    # 拖动锚点：课表头部周导航中间的「第 N 周」标签（不在 .tscroll 内 → 触发换周手势）
    anchor = cdp.eval("""(function(){var el=document.querySelector('.ttwk .wlab');
      if(!el)return null;var r=el.getBoundingClientRect();
      return {x:r.x+r.width/2,y:r.y+r.height/2};})()""")
    if not anchor:
        R.chk("拖动锚点：课表头部周标签存在", False)
        return R, stats
    ax, ay = anchor["x"], anchor["y"]
    card_box = [card.get("x", 0), card.get("y", 0), card.get("right", 0), card.get("bottom", 0)]

    def leak_check(name, path, allow_internal=None, internal_min=0):
        d_out = pix.outside_diff(static_path, path, card)
        ok = d_out <= 8
        note = "框外差异像素=%d" % d_out
        if side_box is not None:
            d_side = pix.diff(static_path, path, side_box)
            ok = ok and d_side <= 0
            note += " 侧栏差异=%d" % d_side
        d_in = pix.diff(static_path, path, card_box)
        note += " 卡内变化=%d" % d_in
        if internal_min:
            ok = ok and d_in >= internal_min
        R.chk(name, ok, note)
        return d_out, d_in

    # ---------------- 场景 1：小拖后松手回弹（跟手 + 回弹两帧） ----------------
    touch(cdp, [(ax, ay)], "touchStart")
    for i in range(1, 5):                        # +10 / +20 / +30 / +40
        touch(cdp, [(ax + 10 * i, ay)], "touchMove")
        time.sleep(0.02)
    time.sleep(0.06)
    snapA = shot(cdp, tag, W, "snap_1")          # 按住不放（位移 +40）
    leak_check("回弹：松手前拖动帧（框外无泄漏 + 卡内可见变化）", snapA, internal_min=400)
    touch(cdp, [], "touchEnd")                   # 松手 → snap() 弹性回位
    time.sleep(0.09)
    snapB = shot(cdp, tag, W, "snap_2")          # 回弹动画中间帧
    leak_check("回弹：松手后回弹动画帧（框外无泄漏）", snapB, internal_min=100)
    time.sleep(0.42)
    snapSettle = shot(cdp, tag, W, "snap_settled")
    st2 = cdp.eval("__ttfProbe()")
    R.chk("回弹：松手后位移归零（transform 已清理、周次不变）",
          abs(float(st2.get("tx") or 0)) < 0.5 and _label_week(st2.get("week")) == base_week,
          "tx=%s week=%s" % (st2.get("tx"), st2.get("week")))
    d = pix.diff(static_path, snapSettle)
    R.chk("回弹：回落后整帧与静止帧一致（无残留）", d <= 8, "diff=%d" % d)

    # ---------------- 场景 2：右拖 140px 按住 + 松手切上一周 ----------------
    tx = 140
    touch(cdp, [(ax, ay)], "touchStart")
    for i in range(1, 8):
        touch(cdp, [(ax + 20 * i, ay)], "touchMove")
        time.sleep(0.018)
    time.sleep(0.09)
    dragRight = shot(cdp, tag, W, "drag_right")
    stD = cdp.eval("__ttfProbe()")
    R.chk("拖动：按住不放时 .ttmain 发生跟手位移（|tx|≈140）",
          abs(abs(float(stD.get("tx") or 0)) - tx) <= 20,
          "tx=%s" % stD.get("tx"))
    leak_check("拖动：按住 140px 帧（框外无泄漏 + 卡内可见变化）", dragRight, internal_min=1500)
    R.chk("拖动中：页面无横向溢出（位移被裁剪容器吃掉）",
          int(stD.get("scrollW") or 0) <= int(stD.get("innerW") or W) + 2,
          "innerW=%s scrollW=%s" % (stD.get("innerW"), stD.get("scrollW")))
    touch(cdp, [], "touchEnd")
    time.sleep(0.75)
    stW = cdp.eval("__ttfProbe()")
    R.chk("横滑切周：右滑 → 上一周（第 %d 周 → 第 %d 周）" % (base_week, base_week - 1),
          _label_week(stW.get("week")) == base_week - 1, stW.get("week"))

    # ---------------- 场景 3：左拖 240px 松手 → 飞入/飞出换回下一周 ----------------
    touch(cdp, [(ax, ay)], "touchStart")
    for i in range(1, 13):
        touch(cdp, [(ax - 20 * i, ay)], "touchMove")
        time.sleep(0.016)
    time.sleep(0.08)
    dragLeft = shot(cdp, tag, W, "drag_left")
    stL = cdp.eval("__ttfProbe()")
    leak_check("拖动：按住 -240px 帧（框外无泄漏）", dragLeft, internal_min=1500)
    R.chk("拖动中（-240px）：页面无横向溢出",
          int(stL.get("scrollW") or 0) <= int(stL.get("innerW") or W) + 2,
          "innerW=%s scrollW=%s" % (stL.get("innerW"), stL.get("scrollW")))
    touch(cdp, [], "touchEnd")
    # 飞出/飞入各帧（fly: 230ms 后换内容，随后 260ms 飞入）
    fly_paths = []
    targets = [0.02, 0.10, 0.20, 0.30, 0.42]
    t0 = time.time()
    for i, tt in enumerate(targets):
        wait = tt - (time.time() - t0)
        if wait > 0:
            time.sleep(wait)
        fly_paths.append(shot(cdp, tag, W, "fly_%d" % (i + 1)))
    fly_in_diffs = [pix.diff(static_path, p, card_box) for p in fly_paths]
    stats["fly_in_diffs"] = fly_in_diffs
    # 飞出/飞入帧：框外必须干净（逐帧断言，超过阈值的帧先看内部是否有变化）
    bad_frames = []
    for p in fly_paths:
        d_out = pix.outside_diff(static_path, p, card)
        extra = ""
        if side_box is not None:
            d_side = pix.diff(static_path, p, side_box)
            if d_side > 0:
                bad_frames.append((os.path.basename(p), d_out, d_side))
                continue
        if d_out > 8:
            bad_frames.append((os.path.basename(p), d_out, -1))
    R.chk("换周飞出/飞入各帧：框外无泄漏" + ("（含桌面侧栏）" if side_box is not None else ""),
          not bad_frames, str(bad_frames[:3]))
    R.chk("换周飞出/飞入：卡内检测到动画变化（不是把动画关掉）",
          max(fly_in_diffs) >= 1000, "card diffs=%s" % fly_in_diffs)
    time.sleep(0.6)
    settled_path = shot(cdp, tag, W, "settled")
    stS = cdp.eval("__ttfProbe()")
    d = pix.diff(static_path, settled_path)
    R.chk("飞入结束后回到静止帧（整帧一致、无残留、周次复原）",
          d <= 8 and _label_week(stS.get("week")) == base_week,
          "diff=%d week=%s" % (d, stS.get("week")))

    # ---------------- 上一周 / 下一周按钮 ----------------
    def click_sel(sel):
        rect = cdp.eval("""(function(){var e=document.querySelector(%s);if(!e)return null;
          var r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()""" % json.dumps(sel))
        if not rect:
            return False
        mouse_click(cdp, rect["x"], rect["y"])
        return True
    click_sel("#tPrevW")
    time.sleep(0.35)
    stP = cdp.eval("__ttfProbe()")
    R.chk("按钮：上一周按钮仍工作", _label_week(stP.get("week")) == base_week - 1, stP.get("week"))
    click_sel("#tNextW")
    time.sleep(0.35)
    stN = cdp.eval("__ttfProbe()")
    R.chk("按钮：下一周按钮仍工作", _label_week(stN.get("week")) == base_week, stN.get("week"))

    # ---------------- 点击课程 → 详情弹层 ----------------
    cell = cdp.eval("""(function(){var e=document.querySelector('#tGrid .crs');if(!e)return null;
      var r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,name:e.getAttribute('data-cname')};})()""")
    if cell:
        mouse_click(cdp, cell["x"], cell["y"])
        time.sleep(0.35)
        stC = cdp.eval("__ttfProbe()")
        opened = (stC.get("panelDisplay") != "none") and (cell["name"] in (stC.get("panelText") or ""))
        R.chk("交互：点击课程打开详情弹层且内容正确", opened,
              "display=%s name=%s text=%s" % (stC.get("panelDisplay"), cell["name"],
                                              (stC.get("panelText") or "")[:40]))
        click_sel("#ttCClose")
        time.sleep(0.3)
        stC2 = cdp.eval("__ttfProbe()")
        R.chk("交互：详情弹层可关闭", stC2.get("panelDisplay") == "none", stC2.get("panelDisplay"))
    else:
        R.chk("交互：点击课程打开详情弹层且内容正确", False, "未找到课程格")

    # ---------------- 周/日视图按钮 ----------------
    click_sel("#tViewSeg button[data-ttview=\"day\"]")
    time.sleep(0.4)
    stDay = cdp.eval("__ttfProbe()")
    R.chk("按钮：切到「日」视图（网格隐藏/日视图显示）",
          stDay.get("gridDisplay") == "none" and stDay.get("dayBarDisplay") != "none",
          "grid=%s daybar=%s" % (stDay.get("gridDisplay"), stDay.get("dayBarDisplay")))
    if W == 390:
        # 日视图同样不能泄漏（手机上默认视图就是日视图）；日视图卡片高度与周视图不同，需各自静止参照
        time.sleep(0.3)
        day_static = shot(cdp, tag, W, "static_day")
        day_info = cdp.eval("__ttfProbe()")
        day_card = day_info.get("card") or card
        day_box = [day_card.get("x", 0), day_card.get("y", 0),
                   day_card.get("right", 0), day_card.get("bottom", 0)]
        touch(cdp, [(ax, ay)], "touchStart")
        for i in range(1, 8):
            touch(cdp, [(ax + 20 * i, ay)], "touchMove")
            time.sleep(0.016)
        time.sleep(0.08)
        dayDrag = shot(cdp, tag, W, "drag_day")
        day_out = 0
        for box in pix.outside_boxes(day_card, pix.img(day_static).size):
            day_out += pix.diff(day_static, dayDrag, box)
        day_in = pix.diff(day_static, dayDrag, day_box)
        R.chk("日视图：按住拖动帧（框外无泄漏 + 卡内可见变化）",
              day_out <= 8 and day_in >= 1500,
              "框外差异像素=%d 卡内变化=%d" % (day_out, day_in))
        touch(cdp, [], "touchEnd")
        time.sleep(0.7)
        click_sel("#tViewSeg button[data-ttview=\"week\"]")
        time.sleep(0.35)
        stWk = cdp.eval("__ttfProbe()")
        R.chk("按钮：切回「周」视图", stWk.get("gridDisplay") != "none", stWk.get("gridDisplay"))

    # ---------------- 收尾：横向溢出 / JS 错误 ----------------
    fin = cdp.eval("__ttfProbe()")
    R.chk("收尾：无页面横向溢出",
          int(fin.get("scrollW") or 0) <= int(fin.get("innerW") or W) + 1 and
          int(fin.get("bodyScrollW") or 0) <= int(fin.get("innerW") or W) + 1,
          "innerW=%s scrollW=%s bodyScrollW=%s" % (fin.get("innerW"), fin.get("scrollW"),
                                                   fin.get("bodyScrollW")))
    R.chk("收尾：0 JS 错误", int(fin.get("errs") or 0) == 0,
          "errs=%s" % (cdp.eval("JSON.stringify(__ttf.errs())") or "[]")[:300])
    R.chk("收尾：0 console.error", int(fin.get("cerrs") or 0) == 0,
          "cerrs=%s" % (cdp.eval("JSON.stringify(__ttf.cerrs())") or "[]")[:300])
    stats["final"] = {k: fin.get(k) for k in ("week", "innerW", "scrollW", "errs", "cerrs")}
    return R, stats


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    src = os.environ.get("TT_FRAME_SRC")
    tag = os.environ.get("TT_FRAME_TAG", "post")
    if "--src" in args:
        src = args[args.index("--src") + 1]
    if "--tag" in args:
        tag = args[args.index("--tag") + 1]
    src = os.path.abspath(src or os.path.join(ROOT, "index.html"))
    if not os.path.isfile(src):
        print("[v2_tt_frame_check] 源文件不存在: %s" % src)
        sys.exit(2)
    os.makedirs(SHOTS, exist_ok=True)
    raw = open(src, "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    print("=" * 96)
    print("[v2_tt_frame_check] source = %s" % src)
    print("[v2_tt_frame_check] size=%d sha256=%s tag=%s" % (len(raw), sha, tag))
    print("[v2_tt_frame_check] shots  = %s" % SHOTS)
    print("[v2_tt_frame_check] http=%d cdp=%d edge=%s" % (HTTP_PORT, CDP_PORT, os.path.basename(EDGE)))
    print("=" * 96)

    tmp = tempfile.mkdtemp(prefix="ttframe_")
    prof = tempfile.mkdtemp(prefix="edgeprof_")
    srv = None
    proc = None
    cdp = None
    pix = Pixels()
    checks = []
    stats_all = {}
    try:
        build_preview(src, os.path.join(tmp, PREVIEW))
        handler = functools.partial(Handler, directory=tmp)
        srv = Q(("127.0.0.1", HTTP_PORT), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        devnull = open(os.devnull, "wb")
        proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                                 "--no-default-browser-check", "--disable-extensions",
                                 "--remote-debugging-port=%d" % CDP_PORT,
                                 "--user-data-dir=" + prof, "about:blank"],
                                stdout=devnull, stderr=devnull)
        cdp = CDP(get_ws(CDP_PORT))
        cdp.send("Page.enable")
        try:
            cdp.send("Emulation.setTimezoneOverride", {"timezoneId": "Asia/Shanghai"})
        except Exception:
            pass
        for (W, H, mobile) in VIEWPORTS:
            print("-" * 96)
            print("[viewport] %dx%d mobile=%s" % (W, H, mobile))
            R, stats = run_viewport(cdp, W, H, mobile, tag, True, pix)
            checks += R.items
            stats_all["%d" % W] = stats
    finally:
        if cdp:
            cdp.close()
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(prof, ignore_errors=True)

    passed = sum(1 for c in checks if c["ok"])
    failed = [c for c in checks if not c["ok"]]
    summary = {"tag": tag, "src": src, "size": len(raw), "sha256": sha,
               "pass": passed, "fail": len(failed), "checks": checks, "stats": stats_all,
               "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        with open(os.path.join(SHOTS, "%s_summary.json" % tag), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    print("=" * 96)
    if failed:
        print("[FAIL] %d 项：" % len(failed))
        for c in failed:
            print("  - %s  | %s" % (c["name"], c["note"]))
    print("v2_tt_frame_check[%s]: %d PASS / %d FAIL  (source sha256=%s)"
          % (tag, passed, len(failed), sha[:16]))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
