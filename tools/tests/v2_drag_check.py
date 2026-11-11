# -*- coding: utf-8 -*-
"""task-22：卡片拖拽（工具栏入位/替换 + 全部页排序）回归（CDP，鼠标+触摸）

2026-11-11 增量：定位基准 v2.1 = 卡片本体（幽灵矩形）而不是鼠标指针
  · 工具栏命中 / 工具栏插入位置 / 卡片排序插入位置 全部按「拖动中的卡片本体」计算；
    指针只驱动幽灵（保留抓取偏移，H4 锁定）。
  · 全部页所有卡片（含电费/反馈/使用说明三个特殊页）都能拖进顶部工具栏。

场景：
  A. 全部页卡片 handle 存在（三条横线），无「设为首页/替换为/点击取消」按钮；
  B. 鼠标拖「点名 roll」到工具栏第 2 位 → homeTools 顺序、tabs 顺序、thumb 对齐；点击可切页；刷新后保持；
  C. 工具栏满员（竖屏 3 槽）时拖「体测 ft」到第 3 槽 → 替换；刷新后保持；
  D. 全部页网格拖动卡片（第 1 张 → 第 3 张后）→ zq_all_order_v1 持久化、DOM 顺序、刷新后保持；
  E. 触摸拖动（CDP touch）卡片到工具栏 → 生效；
  F. reduced-motion 下拖动功能正常；
  G. 横竖屏切换后 tabs/thumb 正常、拖动与点击仍可用；
  H. 拖动幽灵跟手（卡片本体锚定：ghost = 卡片左上 + (指针 - 按下点)）；
  I. 触摸拖动幽灵跟手 + 清理；
  K. 工具栏命中区/高亮/移出清除；
  L. 卡片排序稳定（不抽动）+ 目标卡让位；
  M. 边缘自动滚动（长列表可拖到顶/底）；
  N. homeTools 只存用户选择（不写回自动补齐项；兼容小程序勾选）；
  O. 拖动收尾清理；
  P. 桌面多列网格拖动；
  Q. 自动滚动到顶后工具栏命中区仍正确（.tabs sticky 位置随滚动换位）；
  R. 命中基准 = 卡片本体：卡片上沿压进工具栏即进入投放态（此时指针仍在旧「指针命中区」外），
     本体矩形与幽灵实际位置一致，离开工具栏后回到卡片排序态；
  S. 排序落点 = 卡片本体中心（桌面多列：本体中心压到目标卡中心 → 落位一致）；
  T. 特殊卡片（宿舍电费 / 反馈建议 / 使用说明）可拖入工具栏：homeTools、短标签、点击切页、刷新保持；
  U. 工具栏插入位置 = 卡片本体中心（不是指针）：本体中心压住第 2 格 → homeTools[1]；
  J. 0 JS 报错。
用法：cd C:\\...\\web\\tools && python tests\\v2_drag_check.py
"""
import functools
import http.server
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import websocket
except Exception:
    print("[v2_drag_check] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("power_check", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

EDGE = pc.EDGE


def _free_port():
    """动态端口：并行会话可能同时跑回归（曾撞 8965/9465 导致 Edge 连接被重置）。"""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


HTTP_PORT = _free_port()
CDP_PORT = _free_port()
BASE = "http://127.0.0.1:%d/" % HTTP_PORT
SID = pc.SID_A
# 预览副本用 PID 唯一命名，避免并行会话的 v2_drag_check 同时写 _power_preview.html 互相覆盖
PV = "_drag_preview_%d.html" % os.getpid()
RESULTS = []


def T(key, ok, note=""):
    RESULTS.append({"k": key, "ok": bool(ok)})
    print(("[PASS] " if ok else "[FAIL] ") + key + ((" | " + str(note)) if note != "" else ""))


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=60)
        self._id = 0

    def send(self, method, params=None, timeout=60):
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

    def eval(self, expr, timeout=60):
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


def wait_until(cdp, expr, timeout=30, interval=0.1):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cdp.eval(expr):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


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
    raise RuntimeError("no CDP page")


BOOT_READY = ("(function(){var b=document.querySelector('#tabsBar button.on');"
              "return !!(b&&!document.body.classList.contains('id-locked'));})()")


def set_metrics(cdp, w, h):
    cdp.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h,
                                                    "deviceScaleFactor": 2, "mobile": True})


def wait_boot(cdp):
    ok = wait_until(cdp, BOOT_READY, 30)
    time.sleep(1.6)
    return ok


def home_tools(cdp):
    v = cdp.eval("(function(){try{var d=JSON.parse(localStorage.getItem('zq_tools_v2_%s')||'{}');return d.homeTools||[];}catch(e){return [];}})()" % SID)
    return v or []


def tab_order(cdp):
    return cdp.eval("[].slice.call(document.querySelectorAll('#tabsBar button[data-tab]')).map(function(b){return b.dataset.tab;})") or []


def cur_tab(cdp):
    return cdp.eval("(function(){var b=document.querySelector('#tabsBar button.on');return b?b.dataset.tab:'';})()")


def all_order(cdp):
    v = cdp.eval("(function(){try{return JSON.parse(localStorage.getItem('zq_all_order_v1')||'[]');}catch(e){return [];}})()")
    return v or []


def dom_cards(cdp):
    return cdp.eval("[].slice.call(document.querySelectorAll('#allCards [data-card]')).map(function(c){return c.getAttribute('data-card');})") or []


def open_all(cdp):
    cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();return !!b;})()")
    time.sleep(0.7)


def scroll_card_into_view(cdp, key):
    cdp.eval("(function(){var c=document.querySelector('#allCards [data-card=\"%s\"]');if(c&&c.scrollIntoView)c.scrollIntoView({block:'center'});return true;})()" % key)
    time.sleep(0.35)


def handle_center(cdp, key):
    scroll_card_into_view(cdp, key)
    return cdp.eval("(function(){var h=document.querySelector('#allCards [data-card=\"%s\"] [data-handle]');if(!h)return null;var r=h.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()" % key)


def card_center(cdp, key):
    scroll_card_into_view(cdp, key)
    return cdp.eval("(function(){var c=document.querySelector('#allCards [data-card=\"%s\"]');if(!c)return null;var r=c.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()" % key)


def tab_rect(cdp, tab):
    return cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"%s\"]');if(!b)return null;var r=b.getBoundingClientRect();return {x:r.left,y:r.top,w:r.width,h:r.height};})()" % tab)


def mouse_drag(cdp, x0, y0, x1, y1, steps=10):
    cdp.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x0, "y": y0, "button": "left", "clickCount": 1})
    time.sleep(0.03)
    for i in range(1, steps + 1):
        x = x0 + (x1 - x0) * i / steps
        y = y0 + (y1 - y0) * i / steps
        cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left"})
        time.sleep(0.02)
    # CDP 连续合成 move 会被浏览器合并/滞后：补两次同坐标 move 等浏览器追上，再松手
    for _ in range(2):
        cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x1, "y": y1, "button": "left"})
        time.sleep(0.06)
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x1, "y": y1, "button": "left", "clickCount": 1})
    time.sleep(0.5)


def touch_drag(cdp, x0, y0, x1, y1, steps=10):
    def touch(points, kind):
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [
            {"x": p[0], "y": p[1], "id": i + 1} for i, p in enumerate(points)]})
    touch([(x0, y0)], "touchStart")
    time.sleep(0.03)
    for i in range(1, steps + 1):
        x = x0 + (x1 - x0) * i / steps
        y = y0 + (y1 - y0) * i / steps
        touch([(x, y)], "touchMove")
        time.sleep(0.024)
    for _ in range(2):
        touch([(x1, y1)], "touchMove")
        time.sleep(0.06)
    touch([], "touchEnd")
    time.sleep(0.5)


def drag_state(cdp):
    return cdp.eval("(function(){var s=window.__dragState?window.__dragState():null;return s||{};})()") or {}


def press_at(cdp, x, y):
    cdp.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    time.sleep(0.04)


def move_to(cdp, x, y, wait=0.03):
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left"})
    time.sleep(wait)


def release_at(cdp, x, y):
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
    time.sleep(0.5)


def src_index(cdp):
    return cdp.eval("(function(){var s=document.querySelector('#allCards .drag-src');if(!s)return -1;return [].slice.call(document.querySelectorAll('#allCards [data-card]')).indexOf(s);})()")


def handle_rect(cdp, key):
    return cdp.eval("(function(){var h=document.querySelector('#allCards [data-card=\"%s\"] [data-handle]');if(!h)return null;var r=h.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()" % key)


def card_rect(cdp, key):
    return cdp.eval("(function(){var c=document.querySelector('#allCards [data-card=\"%s\"]');if(!c)return null;var r=c.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2,top:r.top,bottom:r.bottom,left:r.left,right:r.right};})()" % key)


def scroll_handle_center(cdp, key):
    cdp.eval("(function(){var c=document.querySelector('#allCards [data-card=\"%s\"]');if(c&&c.scrollIntoView)c.scrollIntoView({block:'center'});return true;})()" % key)
    time.sleep(0.3)
    return cdp.eval("(function(){var c=document.querySelector('#allCards [data-card=\"%s\"]');var h=c?c.querySelector('[data-handle]'):null;if(!c||!h)return null;var cr=c.getBoundingClientRect(),hr=h.getBoundingClientRect();return {card:{left:cr.left,top:cr.top,w:cr.width,h:cr.height},hx:hr.left+hr.width/2,hy:hr.top+hr.height/2};})()" % key)


def install_rect_counter(cdp):
    cdp.eval("""(function(){
      if(!window.__rectOrig){
        window.__rectOrig=Element.prototype.getBoundingClientRect;
        Element.prototype.getBoundingClientRect=function(){window.__rectCount=(window.__rectCount||0)+1;return window.__rectOrig.apply(this,arguments);};
      }
      window.__rectCount=0;return true;
    })()""")


def rect_count(cdp):
    return int(cdp.eval("window.__rectCount||0") or 0)


def ghost_state(cdp):
    return cdp.eval(r"""(function(){
      var g=document.querySelector('.drag-ghost');
      var sy=Math.round(window.pageYOffset||0);
      var src=document.querySelector('.drag-src');
      var srcOp=src?String(getComputedStyle(src).opacity):"";
      if(!g)return {exists:false,scrollY:sy,srcOpacity:srcOp};
      var cs=getComputedStyle(g);
      var m=/translate3d\((-?[\d.]+)px,\s*(-?[\d.]+)px/.exec(String(g.style.transform||''));
      return {exists:true,x:m?parseFloat(m[1]):null,y:m?parseFloat(m[2]):null,
        position:cs.position,z:cs.zIndex,pe:cs.pointerEvents,scrollY:sy,
        hasHandle:!!g.querySelector('[data-handle]'),srcOpacity:srcOp,
        w:g.getBoundingClientRect().width};
    })()""")


def mouse_drag_sample(cdp, x0, y0, x1, y1, steps=6):
    samples=[]
    cdp.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x0, "y": y0, "button": "left", "clickCount": 1})
    time.sleep(0.03)
    for i in range(1, steps + 1):
        px = x0 + (x1 - x0) * i / steps
        py = y0 + (y1 - y0) * i / steps
        cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": px, "y": py, "button": "left"})
        time.sleep(0.03)
        g = ghost_state(cdp)
        samples.append({"px": px, "py": py, "g": g})
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x1, "y": y1, "button": "left", "clickCount": 1})
    time.sleep(0.5)
    return samples


def touch_drag_sample(cdp, x0, y0, x1, y1, steps=6):
    samples=[]
    def touch(points, kind):
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [
            {"x": p[0], "y": p[1], "id": i + 1} for i, p in enumerate(points)]})
    touch([(x0, y0)], "touchStart")
    time.sleep(0.03)
    for i in range(1, steps + 1):
        px = x0 + (x1 - x0) * i / steps
        py = y0 + (y1 - y0) * i / steps
        touch([(px, py)], "touchMove")
        time.sleep(0.03)
        samples.append({"px": px, "py": py, "g": ghost_state(cdp)})
    touch([], "touchEnd")
    time.sleep(0.5)
    return samples


def snap_thumb(cdp):
    return cdp.eval("""(function(){var bar=document.getElementById('tabsBar');
      var on=document.querySelector('#tabsBar button.on');var th=document.querySelector('.tabs-thumb');
      if(!on||!th||!bar)return null;var br=on.getBoundingClientRect(),tr=th.getBoundingClientRect(),bb=bar.getBoundingClientRect();
      return {bx:Math.round(br.left*10)/10,bw:Math.round(br.width*10)/10,
              tx:Math.round(tr.left*10)/10,tw:Math.round(tr.width*10)/10,
              morph:bar.classList.contains('morph')};})()""")


def bar_rect(cdp):
    return cdp.eval("(function(){var b=document.getElementById('tabsBar').getBoundingClientRect();return {top:b.top,bottom:b.bottom,left:b.left,right:b.right};})()")


def tab_centers(cdp):
    return cdp.eval("""[].slice.call(document.querySelectorAll('#tabsBar button[data-tab]')).map(function(b){
      var r=b.getBoundingClientRect();return {k:b.dataset.tab,cx:r.left+r.width/2,cy:r.top+r.height/2,left:r.left,width:r.width};})""") or []


def card_offsets(cdp, key):
    """卡片 + handle 几何（不滚动；用于把「卡片本体中心」换算成指针位置）。"""
    return cdp.eval("""(function(){var c=document.querySelector('#allCards [data-card="%s"]');
      if(!c)return null;var h=c.querySelector('[data-handle]');if(!h)return null;
      var cr=c.getBoundingClientRect(),hr=h.getBoundingClientRect();
      return {hx:hr.left+hr.width/2,hy:hr.top+hr.height/2,
        offx:hr.left+hr.width/2-cr.left,offy:hr.top+hr.height/2-cr.top,
        left:cr.left,top:cr.top,w:cr.width,h:cr.height,cx:cr.left+cr.width/2,cy:cr.top+cr.height/2};})()""" % key)


def target_for_tab_insert(cdp, key, idx, dx=-10):
    """把卡片本体中心水平压到第 idx 个 tab 中心 + dx 处（下滑后卡片上沿仍在工具栏内）。

    返回 (起点 handle 坐标, 终点指针坐标, 期望本体中心)。基准是卡片本体而不是指针：
    指针 = 期望本体中心 + (抓取偏移 - 卡片中心到左上角距离)。
    """
    info = scroll_handle_center(cdp, key)
    bar = bar_rect(cdp)
    tabs = tab_centers(cdp)
    if not info or not bar or not tabs:
        return None
    i = max(0, min(idx, len(tabs) - 1))
    card_top = bar["bottom"] - 20                    # 卡片上沿压进工具栏 20px（保证命中）
    cx = tabs[i]["cx"] + dx
    cy = card_top + info["card"]["h"] / 2.0
    offx = info["hx"] - info["card"]["left"]
    offy = info["hy"] - info["card"]["top"]
    return {"x0": info["hx"], "y0": info["hy"],
            "x1": cx + offx - info["card"]["w"] / 2.0,
            "y1": cy + offy - info["card"]["h"] / 2.0,
            "cx": cx, "cy": cy}


def reset_home_all(cdp, home=None):
    """清全部页顺序 + 重置 homeTools 后刷新，回到「全部」页。"""
    home = home or ["draw", "hw", "nt", "tt"]
    cdp.eval("(function(){try{localStorage.removeItem('zq_all_order_v1');"
             "var k='zq_tools_v2_%s';var d=JSON.parse(localStorage.getItem(k)||'{}');"
             "d.homeTools=%s;localStorage.setItem(k,JSON.stringify(d));}catch(e){}return 1;})()"
             % (SID, json.dumps(home)))
    cdp.send("Page.reload", {"ignoreCache": False})
    ok = wait_boot(cdp)
    if ok:
        open_all(cdp)
    return ok


def run(cdp):
    set_metrics(cdp, 390, 844)
    cdp.send("Page.navigate", {"url": BASE + "tests/" + PV})
    if not wait_boot(cdp):
        T("A0 启动完成", False, "timeout")
        return
    T("A0 启动完成", True, "")
    open_all(cdp)

    # A. 新 UI：handle 存在、旧按钮/文案已删除
    handles = cdp.eval("document.querySelectorAll('#allCards [data-handle]').length")
    cards = cdp.eval("document.querySelectorAll('#allCards [data-card]').length")
    oldbtn = cdp.eval("document.querySelectorAll('#allCards [data-home]').length")
    oldtxt = cdp.eval("(function(){var t=document.getElementById('allCards').textContent||'';"
                      "return ['设为首页','替换为','点击取消'].filter(function(x){return t.indexOf(x)>=0;}).join(',');})()")
    T("A1 全部页每张卡片都有拖动 handle", handles >= 7 and handles == cards, "%s/%s" % (handles, cards))
    T("A2 旧「设为首页/替换为/点击取消」按钮与文案已删除", oldbtn == 0 and oldtxt == "", "%s / %s" % (oldbtn, oldtxt))
    T("A3 handle aria-label=拖动调整", cdp.eval("(document.querySelector('#allCards [data-handle]').getAttribute('aria-label')||'')==='拖动调整'"), "")

    # B. 鼠标拖 roll 到工具栏第 2 位（hw 之前；按「卡片本体中心」定位，不是指针）
    tgB = target_for_tab_insert(cdp, "roll", 1)
    if not tgB:
        T("B0 起始 handle/tab 定位", False, "missing")
        return
    mouse_drag(cdp, tgB["x0"], tgB["y0"], tgB["x1"], tgB["y1"])
    order = tab_order(cdp)
    ht = home_tools(cdp)
    T("B1 鼠标拖 roll 到工具栏第 2 位：homeTools[1]=roll", len(ht) > 1 and ht[1] == "roll", json.dumps(ht, ensure_ascii=False))
    T("B2 工具栏 tabs 第 2 格为点名", len(order) > 1 and order[1] == "roll", json.dumps(order, ensure_ascii=False))
    sp = snap_thumb(cdp)
    T("B3 拖动后 thumb 与当前按钮对齐", bool(sp) and abs(sp["tx"] - sp["bx"]) <= 2 and abs(sp["tw"] - sp["bw"]) <= 2, json.dumps(sp))
    cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"roll\"]');if(b)b.click();return true;})()")
    time.sleep(0.6)
    T("B4 点击新工具栏位置可切页", cdp.eval("(function(){var s=document.getElementById('s-roll');return !!(s&&s.classList.contains('on'));})()"), "")
    cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"draw\"]');if(b)b.click();return true;})()")
    time.sleep(0.5)
    cdp.send("Page.reload", {"ignoreCache": False})
    wait_boot(cdp)
    T("B5 刷新后 homeTools 顺序保持", (home_tools(cdp) or [None, None])[1] == "roll", json.dumps(home_tools(cdp), ensure_ascii=False))
    open_all(cdp)

    # C. 工具栏满员替换：拖 ft 到第 3 槽（卡片本体中心压住第 3 格）
    tgC = target_for_tab_insert(cdp, "ft", 2)
    if tgC:
        mouse_drag(cdp, tgC["x0"], tgC["y0"], tgC["x1"], tgC["y1"])
    ht2 = home_tools(cdp)
    order2 = tab_order(cdp)
    T("C1 工具栏满员（4 个）时拖入替换第 3 槽：homeTools 含 ft 且仍 ≤4 项", "ft" in ht2 and len(ht2) <= 4, json.dumps(ht2, ensure_ascii=False))
    T("C2 工具栏第 3 格为体测", len(order2) > 2 and order2[2] == "ft", json.dumps(order2, ensure_ascii=False))
    cdp.send("Page.reload", {"ignoreCache": False})
    wait_boot(cdp)
    T("C3 刷新后替换结果保持", "ft" in home_tools(cdp), json.dumps(home_tools(cdp), ensure_ascii=False))
    open_all(cdp)

    # D. 全部页网格拖动排序（第 1 张 → 第 3 张之后）
    cards0 = dom_cards(cdp)
    if len(cards0) >= 3:
        cdp.eval("window.scrollTo(0,0)")
        time.sleep(0.3)
        first = cards0[0]
        third = cdp.eval("(function(){var c=document.querySelector('#allCards [data-card=\"%s\"]');if(!c)return null;var r=c.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()" % cards0[2])
        hd = cdp.eval("(function(){var h=document.querySelector('#allCards [data-card=\"%s\"] [data-handle]');if(!h)return null;var r=h.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()" % first)
        if third and hd:
            mouse_drag(cdp, hd["x"], hd["y"], third["x"], third["y"] + third["y"] * 0.0 + 20)
        cards1 = dom_cards(cdp)
        ord1 = all_order(cdp)
        T("D1 拖动后 DOM 卡片顺序改变", cards1 != cards0, "%s -> %s" % (cards0[:3], cards1[:3]))
        T("D2 zq_all_order_v1 已持久化且与 DOM 顺序一致", ord1 == cards1, json.dumps(ord1[:6], ensure_ascii=False))
        cdp.send("Page.reload", {"ignoreCache": False})
        wait_boot(cdp)
        open_all(cdp)
        T("D3 刷新后全部页卡片顺序保持", dom_cards(cdp) == cards1, json.dumps(dom_cards(cdp)[:6], ensure_ascii=False))
    else:
        T("D0 全部页卡片不足，无法排序测试", False, len(cards0))

    # E. 触摸拖动：拖 committee 到工具栏第 1 位（卡片本体中心）
    tgE = target_for_tab_insert(cdp, "committee", 0)
    if tgE:
        touch_drag(cdp, tgE["x0"], tgE["y0"], tgE["x1"], tgE["y1"])
    ht3 = home_tools(cdp)
    T("E1 触摸拖动卡片到工具栏生效", len(ht3) > 0 and ht3[0] == "committee", json.dumps(ht3, ensure_ascii=False))

    # F. reduced-motion 功能正常
    cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
    open_all(cdp)
    hd2 = handle_center(cdp, "draw")
    time.sleep(0.15)
    tgF = target_for_tab_insert(cdp, "draw", 0)
    if tgF:
        mouse_drag(cdp, tgF["x0"], tgF["y0"], tgF["x1"], tgF["y1"])
    T("F1 reduced-motion 下拖动仍生效", (home_tools(cdp) or [""])[0] == "draw", json.dumps(home_tools(cdp), ensure_ascii=False))
    cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "no-preference"}]})

    # G. 横竖屏切换后工具栏/拖动正常
    set_metrics(cdp, 740, 360)
    time.sleep(0.9)
    sp2 = snap_thumb(cdp)
    n_land = len(tab_order(cdp))
    T("G1 横屏后 tabs 数正确", n_land == 5, n_land)
    T("G2 横屏后 thumb 对齐", bool(sp2) and abs(sp2["tx"] - sp2["bx"]) <= 2 and abs(sp2["tw"] - sp2["bw"]) <= 2, json.dumps(sp2))
    set_metrics(cdp, 390, 844)
    time.sleep(0.9)
    sp3 = snap_thumb(cdp)
    T("G3 转回竖屏后 tabs=4、thumb 对齐", len(tab_order(cdp)) == 4 and bool(sp3) and abs(sp3["tx"] - sp3["bx"]) <= 2,
      json.dumps({"n": len(tab_order(cdp)), "sp": sp3}))
    open_all(cdp)
    T("G4 横竖屏后全部页卡片/拖动 handle 仍存在",
      cdp.eval("document.querySelectorAll('#allCards [data-card]').length") >= 7, "")

    # ===== H. 拖动幽灵跟手（鼠标） =====
    open_all(cdp)
    info = scroll_handle_center(cdp, "committee")
    if not info:
        T("H0 起始卡片/工具条定位", False, "missing committee card")
    else:
        first = tab_rect(cdp, tab_order(cdp)[0])
        install_rect_counter(cdp)
        sys_scroll0 = cdp.eval("Math.round(window.pageYOffset||0)")
        tx1 = first["x"] + 2
        ty1 = first["y"] + first["h"] / 2
        samples = mouse_drag_sample(cdp, info["hx"], info["hy"], tx1, ty1, steps=6)
        hit = [smp for smp in samples if smp["g"]["exists"]]
        T("H1 越过阈值后出现拖动幽灵", len(hit) >= 1, "samples=%d hit=%d" % (len(samples), len(hit)))
        T("H2 幽灵 position=fixed / pointer-events=none / z-index 高",
          all(smp["g"]["position"] == "fixed" and smp["g"]["pe"] == "none" and int(smp["g"]["z"] or 0) >= 50 for smp in hit),
          json.dumps(hit[0]["g"] if hit else None))
        T("H3 幽灵不含 handle（避免重复按钮）", all(not smp["g"]["hasHandle"] for smp in hit), "")
        # 期望位置 = 卡片左上 + (指针 - 按下点)；抓取点固定
        errs_xy = []
        for smp in hit:
            ex = info["card"]["left"] + (smp["px"] - info["hx"])
            ey = info["card"]["top"] + (smp["py"] - info["hy"])
            if smp["g"]["x"] is None:
                errs_xy.append(999)
            else:
                errs_xy.append(max(abs(smp["g"]["x"] - ex), abs(smp["g"]["y"] - ey)))
        T("H4 幽灵 transform 与指针位移一致（每点误差 ≤2px）",
          bool(errs_xy) and max(errs_xy) <= 2, json.dumps([round(e, 1) for e in errs_xy]))
        T("H5 拖动中源卡片变半透明（opacity≤.5）",
          all(0 < float(smp["g"]["srcOpacity"] or 1) <= 0.5 for smp in hit),
          json.dumps([smp["g"]["srcOpacity"] for smp in hit]))
        far = [smp for smp in hit if smp["py"] > 200]
        T("H6 拖动中指针远离视口边缘时不自动滚动", bool(far) and all(smp["g"]["scrollY"] == sys_scroll0 for smp in far),
          "start=%s far=%s" % (sys_scroll0, [smp["g"]["scrollY"] for smp in far]))
        rc = rect_count(cdp)
        T("H7 move 时布局读取受控（缓存几何，6 次 move 的 GBCR ≤120）", rc <= 120, "GBCR=%d moves=%d" % (rc, len(samples)))
        g_after = ghost_state(cdp)
        T("H8 松手后幽灵移除、源卡恢复透明", (not g_after["exists"]) and (g_after["srcOpacity"] in ("1", "")), json.dumps(g_after))
        T("H9 幽灵拖动落点仍正确（committee 进入工具栏首格）", (home_tools(cdp) or [""])[0] == "committee", json.dumps(home_tools(cdp), ensure_ascii=False))
        T("H10 页面无横向溢出", cdp.eval("(function(){var d=document.documentElement;return Math.max(d.scrollWidth,document.body.scrollWidth)<=innerWidth+1;})()"), "")

    # ===== I. 触摸拖动幽灵跟手 + 清理 =====
    open_all(cdp)
    info2 = scroll_handle_center(cdp, "tt")
    if not info2:
        T("I0 起始卡片/工具条定位（tt）", False, "missing tt card")
    else:
        torder = tab_order(cdp)
        t2 = tab_rect(cdp, torder[min(1, len(torder) - 1)])
        s2 = touch_drag_sample(cdp, info2["hx"], info2["hy"], t2["x"] + 2, t2["y"] + t2["h"] / 2, steps=6)
        hit2 = [smp for smp in s2 if smp["g"]["exists"]]
        T("I1 触摸拖动出现幽灵", len(hit2) >= 1, "hit=%d/%d" % (len(hit2), len(s2)))
        errs2 = []
        for smp in hit2:
            ex = info2["card"]["left"] + (smp["px"] - info2["hx"])
            ey = info2["card"]["top"] + (smp["py"] - info2["hy"])
            if smp["g"]["x"] is None:
                errs2.append(999)
            else:
                errs2.append(max(abs(smp["g"]["x"] - ex), abs(smp["g"]["y"] - ey)))
        T("I2 触摸幽灵 transform 跟手（每点误差 ≤2px）", bool(errs2) and max(errs2) <= 2, json.dumps([round(e, 1) for e in errs2]))
        T("I3 触摸拖动不滚动页面", all(smp["g"]["scrollY"] == s2[0]["g"]["scrollY"] for smp in hit2), "")
        ga = ghost_state(cdp)
        T("I4 触摸松手后幽灵移除", not ga["exists"], json.dumps(ga))

    # ===== K. 顶部工具栏命中区扩大 + 高亮（新） =====
    open_all(cdp)
    kinfo = scroll_handle_center(cdp, "water")
    if not kinfo:
        T("K0 起始卡片/工具条定位（water）", False, "missing water card")
    else:
        tabsK = cdp.eval("[].slice.call(document.querySelectorAll('#tabsBar button[data-tab]')).map(function(b){var r=b.getBoundingClientRect();return {t:b.dataset.tab,l:r.left,w:r.width};})") or []
        tooltabs = [t for t in tabsK if t["t"] != "all"]
        barK = cdp.eval("(function(){var b=document.getElementById('tabsBar').getBoundingClientRect();return {t:b.top,b:b.bottom,l:b.left,r:b.right};})()")
        if len(tooltabs) < 2:
            T("K0b 工具栏至少 2 个工具 tab", False, json.dumps(tabsK))
        else:
            tb = tooltabs[1]
            tx = tb["l"] + tb["w"] / 2
            ty = barK["b"] + 18          # 工具栏下方余量内（扩大后的命中区）
            press_at(cdp, kinfo["hx"], kinfo["hy"])
            for i in range(1, 7):
                move_to(cdp, kinfo["hx"] + (tx - kinfo["hx"]) * i / 6, kinfo["hy"] + (ty - kinfo["hy"]) * i / 6)
            st = drag_state(cdp)
            hl = cdp.eval("(function(){return {over:document.getElementById('tabsBar').classList.contains('drag-over'),hl:document.querySelectorAll('#tabsBar button.drophl').length,ins:(function(){var e=document.querySelector('.tab-ins');return !!(e&&e.classList.contains('on'));})()};})()")
            T("K1 拖到工具栏下方余量内即进入投放态（命中区扩大）", st.get("mode") == "tabs" and st.get("tabsZone") is True,
              "mode=%s zone=%s y=%s barBottom=%s" % (st.get("mode"), st.get("tabsZone"), st.get("y"), barK["b"]))
            T("K2 工具栏高亮 + 目标 tab 高亮 + 插入线", bool(hl.get("over")) and hl.get("hl", 0) >= 1 and bool(hl.get("ins")), json.dumps(hl))
            # 移出命中区 → 回到卡片排序态并清除工具栏高亮
            move_to(cdp, 60, 520, 0.05)
            move_to(cdp, 60, 540, 0.05)
            st2 = drag_state(cdp)
            over2 = cdp.eval("document.getElementById('tabsBar').classList.contains('drag-over')")
            T("K3 移出命中区后恢复卡片排序态且工具栏高亮清除", st2.get("mode") == "cards" and not over2,
              "mode=%s over=%s" % (st2.get("mode"), over2))
            release_at(cdp, 60, 540)

    # ===== L. 卡片排序稳定（不抽动）+ 目标卡让位（新） =====
    open_all(cdp)
    cdp.eval("window.scrollTo(0,0)")
    time.sleep(0.35)
    cardsL = dom_cards(cdp)
    if len(cardsL) < 5:
        T("L0 全部页卡片数量足够", False, len(cardsL))
    else:
        hL = handle_rect(cdp, cardsL[0])
        tgtL = card_rect(cdp, cardsL[3])
        if not hL or not tgtL:
            T("L0b 起始卡片定位", False, "missing")
        else:
            press_at(cdp, hL["x"], hL["y"])
            seq = []
            y_end = tgtL["y"] + 20
            for i in range(1, 13):
                move_to(cdp, hL["x"] + (tgtL["x"] - hL["x"]) * i / 12,
                        hL["y"] + (y_end - hL["y"]) * i / 12, 0.035)
                seq.append(int(src_index(cdp)))
            jitter = any(seq[i] == seq[i + 2] and seq[i] != seq[i + 1] for i in range(len(seq) - 2))
            T("L1 拖过 3 张卡片过程中源卡位置无 A→B→A 抽动", not jitter, json.dumps(seq))
            T("L2 拖动中实时让位（源卡索引发生变化）", any(v != seq[0] for v in seq) or (seq and seq[-1] != 0), json.dumps(seq))
            release_at(cdp, hL["x"] + (tgtL["x"] - hL["x"]), y_end)
            cardsL2 = dom_cards(cdp)
            T("L3 松手后 DOM 顺序已改变", cardsL2 != cardsL, "%s -> %s" % (cardsL[:3], cardsL2[:3]))
            T("L4 目标卡被让开（原第 4 张索引变化）", cardsL[3] in cardsL2 and cardsL2.index(cardsL[3]) != 3,
              "idx=%s" % (cardsL2.index(cardsL[3]) if cardsL[3] in cardsL2 else "?"))

    # ===== M. 边缘自动滚动（长列表可拖到顶/底） =====
    open_all(cdp)
    cdp.eval("window.scrollTo(0,0)")
    time.sleep(0.3)
    minfo = scroll_handle_center(cdp, "roll")
    if not minfo:
        T("M0 起始卡片定位（roll）", False, "missing")
    else:
        cdp.eval("window.scrollTo(0,%d)" % int(cdp.eval("Math.round(document.documentElement.scrollHeight*0.35)")))
        time.sleep(0.35)
        minfo = handle_rect(cdp, "roll")
        if not minfo:
            T("M0b 起始卡片定位（roll2）", False, "missing")
        else:
            y0 = cdp.eval("Math.round(window.pageYOffset)")
            press_at(cdp, minfo["x"], minfo["y"])
            move_to(cdp, minfo["x"], 300, 0.04)
            move_to(cdp, minfo["x"], int(cdp.eval("window.innerHeight")) - 16, 0.05)
            time.sleep(0.75)     # 指针停在下边缘：rAF 自动滚动
            y1 = cdp.eval("Math.round(window.pageYOffset)")
            T("M1 指针停在下边缘时页面自动向下滚动", y1 > y0, "%s -> %s" % (y0, y1))
            move_to(cdp, minfo["x"], 420, 0.05)
            time.sleep(0.4)
            y2 = cdp.eval("Math.round(window.pageYOffset)")
            T("M2 指针离开边缘后停止滚动", abs(y2 - y1) <= 2, "%s -> %s" % (y1, y2))
            move_to(cdp, minfo["x"], 8, 0.05)
            time.sleep(0.6)
            y3 = cdp.eval("Math.round(window.pageYOffset)")
            T("M3 指针停在上边缘时页面自动向上滚动", y3 < y2, "%s -> %s" % (y2, y3))
            release_at(cdp, minfo["x"], 8)
            ya = cdp.eval("Math.round(window.pageYOffset)")
            time.sleep(0.4)
            yb = cdp.eval("Math.round(window.pageYOffset)")
            T("M4 松手后停止自动滚动", abs(yb - ya) <= 1, "%s -> %s" % (ya, yb))

    # ===== N. homeTools 只存用户选择（不写回自动补齐项；兼容小程序勾选） =====
    # 用「远端 userdata 只有 2 个首页工具」模拟小程序勾选后同步到网页：显示按比例补齐，但 homeTools 不能被补回 4 个
    ub = pc.ud_blob("")
    ub["homeTools"] = ["hw", "nt"]
    # 远端时间戳抬到未来：保证这次合并远端赢（旧页面卸载时会把本机 cache/时间戳再刷一遍，清 localStorage 不可靠）
    _future = int(time.time() * 1000) + 3600 * 1000
    for _k in ub["at"]:
        ub["at"][_k] = _future
    ub["homeToolsAt"] = _future
    # 清掉本机同步时间戳，保证下一次启动真的按 ud= 重新拉 userdata（否则 60s TTL 内不拉）
    cdp.eval("(function(){try{Object.keys(localStorage).forEach(function(k){if(k.indexOf('zq_synced_at_')===0||k.indexOf('zq_udcache_')===0||k.indexOf('zq_udat_')===0)localStorage.removeItem(k);});}catch(e){}return 1;})()")
    cdp.send("Page.navigate", {"url": BASE + "tests/" + pc.preview_url(SID, ub)})
    if not wait_boot(cdp):
        T("N0 启动（模拟小程序勾选 2 个）", False, "timeout")
    else:
        applied = wait_until(cdp, "(function(){var b=[].slice.call(document.querySelectorAll('#tabsBar button[data-tab]'));return b.length===4&&b[0]&&b[0].dataset.tab==='hw'&&b[1]&&b[1].dataset.tab==='nt';})()", 12)
        time.sleep(0.4)
        htN = cdp.eval("(function(){try{return JSON.stringify(JSON.parse(localStorage.getItem('zq_tools_v2_%s')||'{}').homeTools||null);}catch(e){return 'ERR';}})()" % SID)
        toN = tab_order(cdp)
        T("N1 远端只有 2 个首页工具：本机 homeTools 保持 2 个，不被自动补齐写回", bool(applied) and htN == '["hw","nt"]', "applied=%s ht=%s" % (applied, htN))
        T("N2 工具栏仍按屏幕比例补齐显示（竖屏 3 工具 + 全部）", len(toN) == 4 and toN[:2] == ["hw", "nt"], json.dumps(toN, ensure_ascii=False))

    # ===== O. 拖动收尾清理 =====
    open_all(cdp)
    cdp.eval("window.scrollTo(0,0)")
    time.sleep(0.25)
    left = cdp.eval("""(function(){
      var o={ghost:document.querySelectorAll('.drag-ghost').length,
        src:document.querySelectorAll('.drag-src').length,
        over:document.getElementById('tabsBar').classList.contains('drag-over'),
        shift:document.querySelectorAll('#tabsBar button.tab-shift, #tabsBar button.drophl').length,
        inline:0,body:document.body.classList.contains('card-drag-on')};
      [].slice.call(document.querySelectorAll('#allCards [data-card]')).forEach(function(c){
        if(c.style.transform||c.style.transition||c.style.opacity)o.inline++;
      });
      return o;})()""")
    T("O1 拖动结束后无幽灵/源卡标记/工具栏高亮/残留内联位移",
      left.get("ghost") == 0 and left.get("src") == 0 and not left.get("over") and left.get("shift") == 0
      and left.get("inline") == 0 and not left.get("body"), json.dumps(left))

    # ===== P. 桌面多列网格拖动（≥960 多列） =====
    set_metrics(cdp, 1280, 900)
    time.sleep(0.9)
    open_all(cdp)
    cdp.eval("window.scrollTo(0,0)")
    time.sleep(0.35)
    cardsP = dom_cards(cdp)
    colsP = cdp.eval("(function(){var cs=[].slice.call(document.querySelectorAll('#allCards [data-card]'));var tops={};cs.forEach(function(c){var t=Math.round(c.getBoundingClientRect().top);tops[t]=(tops[t]||0)+1;});var m=0;Object.keys(tops).forEach(function(k){if(tops[k]>m)m=tops[k];});return m;})()")
    T("P1 桌面宽度下全部页为多列网格", int(colsP or 0) >= 2, "cols=%s" % colsP)
    if len(cardsP) >= 8 and int(colsP or 0) >= 2:
        hP = handle_rect(cdp, cardsP[0])
        tgtP = card_rect(cdp, cardsP[4])
        if hP and tgtP:
            press_at(cdp, hP["x"], hP["y"])
            for i in range(1, 9):
                move_to(cdp, hP["x"] + (tgtP["x"] - hP["x"]) * i / 8,
                        hP["y"] + (tgtP["y"] - hP["y"]) * i / 8, 0.03)
            release_at(cdp, tgtP["x"], tgtP["y"])
            cardsP2 = dom_cards(cdp)
            T("P2 桌面多列下卡片拖动排序生效", cardsP2 != cardsP, "%s -> %s" % (cardsP[:4], cardsP2[:4]))
            T("P3 桌面拖动后仍无残留（幽灵/源卡/内联位移）",
              cdp.eval("(function(){return document.querySelectorAll('.drag-ghost,.drag-src').length===0&&!document.body.classList.contains('card-drag-on');})()"), "")
        else:
            T("P2 桌面卡片定位", False, "missing")
    set_metrics(cdp, 390, 844)
    time.sleep(0.9)

    # ===== Q. 自动滚动到顶后工具栏命中区仍正确（.tabs sticky 位置随滚动换位） =====
    open_all(cdp)
    cdp.eval("window.scrollTo(0,0)")
    time.sleep(0.3)
    infoQ = scroll_handle_center(cdp, "water")
    if not infoQ:
        T("Q0 起始卡片定位（water）", False, "missing")
    else:
        ht_before = home_tools(cdp)
        press_at(cdp, infoQ["hx"], infoQ["hy"])
        move_to(cdp, infoQ["hx"], 300, 0.04)
        move_to(cdp, infoQ["hx"], 10, 0.05)
        time.sleep(1.2)      # 指针停在上边缘：自动滚动到顶（.tabs 由贴顶 0…47 换到 brand 下方）
        live = cdp.eval("(function(){var b=document.getElementById('tabsBar').getBoundingClientRect();var bs=[].slice.call(document.querySelectorAll('#tabsBar button[data-tab]')).filter(function(x){return x.dataset.tab!=='all';});var t=bs[Math.min(1,bs.length-1)].getBoundingClientRect();return {barTop:b.top,barBottom:b.bottom,barMid:(b.top+b.bottom)/2,tabx:t.left+t.width/2};})()")
        move_to(cdp, live["tabx"], live["barMid"], 0.08)
        time.sleep(0.35)
        stQ = drag_state(cdp)
        overQ = cdp.eval("document.getElementById('tabsBar').classList.contains('drag-over')")
        T("Q1 自动滚动到顶、sticky 工具栏换位后仍能命中投放区",
          stQ.get("mode") == "tabs" and stQ.get("tabsZone") is True,
          "mode=%s zone=%s y=%s barMid=%.1f" % (stQ.get("mode"), stQ.get("tabsZone"), stQ.get("y"), live["barMid"]))
        T("Q2 命中时工具栏高亮", bool(overQ), "over=%s" % overQ)
        release_at(cdp, live["tabx"], live["barMid"])
        ht_after = home_tools(cdp)
        T("Q3 滚动到顶后拖入工具栏仍生效", ht_after != ht_before and "water" in ht_after,
          "%s -> %s" % (json.dumps(ht_before, ensure_ascii=False), json.dumps(ht_after, ensure_ascii=False)))

    # ===== R. 命中基准 = 卡片本体（不是指针） =====
    reset_home_all(cdp, ["draw", "hw", "nt", "tt"])
    cdp.eval("window.scrollTo(0,0)")
    time.sleep(0.35)
    infoR = cdp.eval("""(function(){var c=document.querySelector('#allCards [data-card="draw"]');if(!c)return null;
      var h=c.querySelector('[data-handle]');var cr=c.getBoundingClientRect(),hr=h.getBoundingClientRect();
      var bar=document.getElementById('tabsBar').getBoundingClientRect();
      var bs=[].slice.call(document.querySelectorAll('#tabsBar button[data-tab]')).filter(function(x){return x.dataset.tab!=='all';});
      var t=bs.length>1?bs[1].getBoundingClientRect():null;
      return {hx:hr.left+hr.width/2,hy:hr.top+hr.height/2,ct:cr.top,barBottom:bar.bottom,
        tab1x:t?t.left+t.width/2:null};})()""")
    if not infoR or infoR.get("tab1x") is None:
        T("R0 起始卡片/工具栏定位", False, "missing")
    else:
        grab_y = infoR["hy"] + 18        # 抓 handle 偏下 → 抓取偏移大，指针可停在旧命中区外
        press_at(cdp, infoR["hx"], grab_y)
        tyR = infoR["barBottom"] + 31    # 旧口径命中区 = bar.bottom+26，指针已在其外
        for i in range(1, 7):
            move_to(cdp, infoR["hx"] + (infoR["tab1x"] - infoR["hx"]) * i / 6,
                    grab_y + (tyR - grab_y) * i / 6, 0.04)
        stR = drag_state(cdp)
        gR = ghost_state(cdp)
        cbR = stR.get("cardBox") or {}
        T("R1 卡片本体上沿压进工具栏即进入投放态（此时指针仍在旧「指针命中区」外）",
          stR.get("mode") == "tabs" and stR.get("tabsZone") is True and stR.get("y", 0) > infoR["barBottom"] + 26,
          "mode=%s zone=%s pointerY=%s barBottom=%.0f cardTop=%s" % (stR.get("mode"), stR.get("tabsZone"),
                                                                    stR.get("y"), infoR["barBottom"], cbR.get("top")))
        overR = cdp.eval("document.getElementById('tabsBar').classList.contains('drag-over')")
        T("R2 命中时工具栏高亮", bool(overR), "")
        T("R3 卡片本体矩形与幽灵实际位置一致（≤2px）",
          bool(gR.get("exists")) and abs((cbR.get("left") or 0) - (gR.get("x") or 0)) <= 2
          and abs((cbR.get("top") or 0) - (gR.get("y") or 0)) <= 2,
          json.dumps({"cardBox": {"left": cbR.get("left"), "top": cbR.get("top")},
                      "ghost": {"x": gR.get("x"), "y": gR.get("y")}}, ensure_ascii=False))
        move_to(cdp, infoR["tab1x"], infoR["barBottom"] + 70, 0.06)
        stR2 = drag_state(cdp)
        T("R4 本体离开工具栏（上沿离开 >18px）回到卡片排序态", stR2.get("mode") == "cards",
          "mode=%s cardTop=%s" % (stR2.get("mode"), (stR2.get("cardBox") or {}).get("top")))
        release_at(cdp, infoR["tab1x"], infoR["barBottom"] + 70)

    # ===== S. 排序落点 = 卡片本体中心（桌面多列） =====
    set_metrics(cdp, 1280, 900)
    time.sleep(0.9)
    reset_home_all(cdp, ["draw", "hw", "nt", "tt"])
    cardsS = dom_cards(cdp)
    if len(cardsS) < 6:
        T("S0 卡片数量足够（桌面多列）", False, len(cardsS))
    else:
        srcS, tgtKeyS = cardsS[0], cardsS[3]
        cdp.eval("window.scrollTo(0,0)")
        time.sleep(0.3)
        mgS = card_offsets(cdp, srcS)
        tgtS = card_rect(cdp, tgtKeyS)
        if not mgS or not tgtS:
            T("S0b 起始卡片定位", False, "missing")
        else:
            pxS = tgtS["x"] + mgS["offx"] - mgS["w"] / 2.0   # 指针 → 本体中心 = 目标卡中心
            pyS = tgtS["y"] + mgS["offy"] - mgS["h"] / 2.0
            press_at(cdp, mgS["hx"], mgS["hy"])
            for i in range(1, 9):
                move_to(cdp, mgS["hx"] + (pxS - mgS["hx"]) * i / 8,
                        mgS["hy"] + (pyS - mgS["hy"]) * i / 8, 0.035)
            stS = drag_state(cdp)
            cbS = stS.get("cardBox") or {}
            T("S1 拖动中本体中心与目标卡中心一致（≤3px）",
              abs((cbS.get("cx") or 0) - tgtS["x"]) <= 3 and abs((cbS.get("cy") or 0) - tgtS["y"]) <= 3,
              json.dumps({"cardBox": {"cx": cbS.get("cx"), "cy": cbS.get("cy")},
                          "target": {"cx": round(tgtS["x"], 1), "cy": round(tgtS["y"], 1)}}, ensure_ascii=False))
            release_at(cdp, pxS, pyS)
            cardsS2 = dom_cards(cdp)
            T("S2 松手后卡片落位到本体中心对应位置（原第 4 张处）",
              srcS in cardsS2 and cardsS2.index(srcS) == 3, json.dumps(cardsS2[:6], ensure_ascii=False))
    set_metrics(cdp, 390, 844)
    time.sleep(0.9)

    # ===== T. 特殊卡片（电费/反馈/使用说明）可拖入工具栏 =====
    reset_home_all(cdp, ["draw", "hw", "nt", "tt"])
    okT = {}
    for keyT, labelT, secT in (("power", "电费", "s-power"), ("fb", "反馈", "s-fb"), ("ug", "说明", "s-ug")):
        tgT = target_for_tab_insert(cdp, keyT, 2)
        if not tgT:
            okT[keyT] = {"missing": True}
            continue
        mouse_drag(cdp, tgT["x0"], tgT["y0"], tgT["x1"], tgT["y1"])
        htT = home_tools(cdp)
        txtT = cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"%s\"]');return b?b.textContent:'';})()" % keyT)
        cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"%s\"]');if(b)b.click();return 1;})()" % keyT)
        time.sleep(0.5)
        onT = cdp.eval("(function(){var s=document.getElementById('%s');return !!(s&&s.classList.contains('on'));})()" % secT)
        okT[keyT] = {"inHome": keyT in htT, "label": txtT, "page": onT}
        open_all(cdp)
    T("T1 电费/反馈/使用说明均可拖入工具栏并写入 homeTools",
      all(okT.get(k, {}).get("inHome") for k in ("power", "fb", "ug")), json.dumps(okT, ensure_ascii=False))
    T("T2 工具栏短标签正确（电费/反馈/说明）",
      okT.get("power", {}).get("label") == "电费" and okT.get("fb", {}).get("label") == "反馈"
      and okT.get("ug", {}).get("label") == "说明",
      json.dumps({k: okT.get(k, {}).get("label") for k in ("power", "fb", "ug")}, ensure_ascii=False))
    T("T3 点击特殊工具 tab 可切到对应页面",
      all(okT.get(k, {}).get("page") for k in ("power", "fb", "ug")),
      json.dumps({k: okT.get(k, {}).get("page") for k in ("power", "fb", "ug")}))
    cdp.send("Page.reload", {"ignoreCache": False})
    wait_boot(cdp)
    htT4 = home_tools(cdp)
    labelT4 = cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"ug\"]');return b?b.textContent:'';})()")
    T("T4 刷新后特殊工具仍保留在工具栏（标签 说明）", "ug" in htT4 and labelT4 == "说明",
      json.dumps({"home": htT4, "label": labelT4}, ensure_ascii=False))
    open_all(cdp)

    # ===== U. 工具栏插入位置 = 卡片本体中心（不是指针） =====
    reset_home_all(cdp, ["draw", "hw", "nt", "tt"])
    tgU = target_for_tab_insert(cdp, "water", 1)
    if not tgU:
        T("U0 起始定位", False, "missing")
    else:
        mouse_drag(cdp, tgU["x0"], tgU["y0"], tgU["x1"], tgU["y1"])
        htU = home_tools(cdp)
        orderU = tab_order(cdp)
        T("U1 本体中心压住第 2 格 → homeTools[1]=水量", len(htU) > 1 and htU[1] == "water",
          json.dumps(htU, ensure_ascii=False))
        T("U2 工具栏第 2 格显示水量", len(orderU) > 1 and orderU[1] == "water", json.dumps(orderU, ensure_ascii=False))
        tgU2 = target_for_tab_insert(cdp, "vote", 2)
        tcs = tab_centers(cdp)
        if tgU2 and len(tcs) > 2:
            mouse_drag(cdp, tgU2["x0"], tgU2["y0"], tcs[2]["cx"], tgU2["y1"])   # 旧口径：指针压住第 3 格中心
            htU2 = home_tools(cdp)
            T("U3 指针在第 3 格中心但本体中心偏左 → 插入位置按本体算（不是指针）",
              "vote" in htU2 and htU2.index("vote") < 2, json.dumps(htU2, ensure_ascii=False))
        else:
            T("U3 对照定位", False, "missing")

    errs = cdp.eval("JSON.stringify(window.__errs||[])")
    T("J1 0 JS 报错", errs == "[]", errs[:300])


def main():
    devnull = open(os.devnull, "wb")
    prof = tempfile.mkdtemp(prefix="edgeprof_drag_")
    proc = None
    cdp = None
    httpd = None
    try:
        pc.build_previews()
        shutil.copy(os.path.join(HERE, pc.PREVIEW), os.path.join(HERE, PV))
        os.chdir(ROOT)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                                 "--no-default-browser-check", "--disable-extensions",
                                 "--remote-debugging-port=%d" % CDP_PORT,
                                 "--user-data-dir=" + prof, "about:blank"],
                                stdout=devnull, stderr=devnull)
        cdp = CDP(get_ws(CDP_PORT))
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        set_metrics(cdp, 390, 844)
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        run(cdp)
    finally:
        if cdp:
            cdp.close()
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        try:
            devnull.close()
        except Exception:
            pass
        shutil.rmtree(prof, ignore_errors=True)
        try:
            os.remove(os.path.join(HERE, PV))
        except Exception:
            pass
        shutil.rmtree(pc.REPORT_DIR, ignore_errors=True)
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 60)
    print("v2_drag_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
