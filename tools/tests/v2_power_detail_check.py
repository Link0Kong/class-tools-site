# -*- coding: utf-8 -*-
"""task-27 A：电费趋势详细查看（去横滑 + 游标/信息/拖动/空态/宽度）回归

- 无横向 scroll：overflow-x hidden、scrollWidth<=clientWidth、无「横滑」提示；
- 24h/7d/30d：点击绘图区命中最近真实采样点，显示竖线+圆点+「时间 · 电量 xx.xx 度」；
- 拖动实时更新并 snap 到真实点；松手保留；点空白/标题取消；不切工具/不滚页面；
- 空态（<2 采样）不显示游标；360/430/1280 无溢出；0 JS 报错；截图。
用法：cd C:\\...\\web\\tools && python tests\\v2_power_detail_check.py
"""
import functools
import http.server
import importlib.util
import json
import os
import re
import shutil
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
    print("[v2_power_detail_check] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("power_check", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

EDGE = pc.EDGE
HTTP_PORT = 8968
CDP_PORT = 9468
BASE = "http://127.0.0.1:%d/" % HTTP_PORT
SID = pc.SID_A
SHOTS = os.path.join(HERE, "_shots_power_detail")
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


def mouse(cdp, typ, x, y):
    cdp.send("Input.dispatchMouseEvent", {"type": typ, "x": x, "y": y, "button": "left", "clickCount": 1})


def open_power(cdp):
    cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();return true;})()")
    time.sleep(0.4)
    cdp.eval("(function(){var b=document.querySelector('#allCards [data-open=\"power\"]');if(b)b.click();return !!b;})()")
    return wait_until(cdp, "!!document.getElementById('pwSelect')", 10)


def pick(cdp, rv):
    cdp.eval("(function(){var s=document.getElementById('pwSelect');if(!s)return false;"
             "s.value='%s';s.dispatchEvent(new Event('change',{bubbles:true}));return true;})()" % rv)
    return wait_until(cdp, "(function(){var e=document.getElementById('pwNum');return !!e&&e.textContent.trim()!==''&&e.textContent.trim()!=='—';})()", 15)


def plot_rect(cdp):
    return cdp.eval("(function(){var e=document.getElementById('pwTrendScroll');if(!e)return null;var r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})()")


def detail(cdp):
    return cdp.eval("""(function(){
      var d=document.getElementById('pwDetail'),tip=document.getElementById('pwDetailTip'),
          line=document.getElementById('pwDetailLine'),dot=document.getElementById('pwDetailDot'),
          info=document.getElementById('pwDetailInfo');
      return {on:!!(d&&d.classList.contains('on')),text:tip?String(tip.textContent||''):'',
        line:line?String(line.style.left||''):'',dot:dot?String(dot.style.top||''):'',
        infoHidden:info?!!info.hidden:true,infoText:info?String(info.textContent||''):''};
    })()""")


def tip_rects(cdp):
    return cdp.eval("""(function(){
      function R(sel){var e=document.querySelector(sel);if(!e)return null;var r=e.getBoundingClientRect();
        return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height};}
      return {tip:R('#pwDetailTip'),plot:R('#pwTrendScroll'),card:R('#pwTrendCard'),detail:R('#pwDetail')};
    })()""")


def set_range(cdp, rng):
    cdp.eval("(function(){var b=document.querySelector('#pwRanges [data-range=\"%s\"]');if(b)b.click();return true;})()" % rng)
    time.sleep(0.7)


def click_x(cdp, frac):
    r = plot_rect(cdp)
    x = r["x"] + max(4, min(r["w"] - 4, r["w"] * frac))
    y = r["y"] + r["h"] / 2
    mouse(cdp, "mousePressed", x, y)
    mouse(cdp, "mouseReleased", x, y)
    time.sleep(0.12)
    return detail(cdp)


def drag_xs(cdp, fracs):
    r = plot_rect(cdp)
    def px(f):
        return r["x"] + max(4, min(r["w"] - 4, r["w"] * f))
    y = r["y"] + r["h"] / 2
    mouse(cdp, "mousePressed", px(fracs[0]), y)
    out = []
    for f in fracs:
        mouse(cdp, "mouseMoved", px(f), y)
        time.sleep(0.05)
        out.append(detail(cdp))
    mouse(cdp, "mouseReleased", px(fracs[-1]), y)
    time.sleep(0.15)
    return out


def no_scroll(cdp):
    return cdp.eval("""(function(){
      var e=document.getElementById('pwTrendScroll');
      if(!e)return {ok:false};
      var cs=getComputedStyle(e);
      var txt=String((document.getElementById('s-power')||{}).textContent||'');
      return {ok:cs.overflowX!=='auto'&&cs.overflowX!=='scroll'&&e.scrollWidth<=e.clientWidth+1
                &&txt.indexOf('横滑')<0&&!e.classList.contains('tscroll'),
              ox:cs.overflowX,sw:e.scrollWidth,cw:e.clientWidth,hint:txt.indexOf('横滑')>=0};
    })()""")


def run(cdp):
    cdp.send("Page.navigate", {"url": BASE + "tests/" + "_power_preview.html?sid=" + SID + "&name=%E6%B5%8B%E8%AF%95%E5%90%8C%E5%AD%A6"})
    ok = wait_until(cdp, "(function(){var b=document.querySelector('#tabsBar button');return !!b&&!document.body.classList.contains('id-locked');})()", 30)
    T("A0 启动完成", ok, "")
    time.sleep(1.2)
    T("A1 电费页打开", open_power(cdp), "")
    T("A2 选择宿舍 321 并加载趋势", pick(cdp, "4-23A---321"), "")
    wait_until(cdp, "!!document.querySelector('#pwTrend svg')", 15)
    time.sleep(0.4)

    ns = no_scroll(cdp)
    T("A3 趋势区无横向滚动（overflow hidden / 无横滑提示）", bool(ns.get("ok")), json.dumps(ns))

    # 24h 详情
    d1 = click_x(cdp, 0.5)
    T("A4 24h 点击显示游标+信息行", d1["on"] and bool(re.match(r"^\d{2}:\d{2} · 电量 [\d.]+ 度$", d1["text"])),
      json.dumps(d1, ensure_ascii=False))
    rr1 = tip_rects(cdp)
    T("A5 游标线/圆点有位置，气泡固定显示在绘图区上方（区间行右侧，不在图内）",
      d1["line"].endswith("px") and d1["dot"].endswith("px") and d1["on"]
      and bool(rr1["tip"]) and rr1["tip"]["w"] > 0 and rr1["tip"]["b"] <= rr1["plot"]["t"] + 0.5,
      json.dumps({"line": d1["line"], "dot": d1["dot"], "tip": rr1["tip"], "plotT": rr1["plot"]["t"]}, ensure_ascii=False)[:360])
    d2 = click_x(cdp, 0.503)  # 相邻 3px 内应 snap 到同一点
    T("A6 相邻点击 snap 到最近真实采样点", d2["text"] == d1["text"], d1["text"] + " vs " + d2["text"])
    # 拖动 3 个位置
    rs = drag_xs(cdp, [0.15, 0.45, 0.8])
    texts = [x["text"] for x in rs]
    T("A7 左右拖动实时更新信息（≥2 个不同点）", all(x["on"] for x in rs) and len(set(texts)) >= 2, json.dumps(texts, ensure_ascii=False))
    held = detail(cdp)
    T("A8 松手保留最后选中点", held["on"] and held["text"] == texts[-1], json.dumps(held, ensure_ascii=False))
    T("A9 查看时不切换工具/不滚动页面", cdp.eval("(function(){var s=document.querySelector('section.on');return s?s.id:'';})()") == "s-power"
      and cdp.eval("Math.round(window.pageYOffset||0)") == 0, "")
    # 点标题取消
    cdp.eval("(function(){var t=document.getElementById('pwTrendTitle');if(t)t.click();return true;})()")
    time.sleep(0.1)
    T("A10 点标题取消游标", not detail(cdp)["on"], json.dumps(detail(cdp)))

    # 7d / 30d：压缩无横滑 + MM-DD HH:MM 格式
    for rng, label in (("7d", "7 天"), ("30d", "30 天")):
        set_range(cdp, rng)
        wait_until(cdp, "(function(){var t=document.getElementById('pwTrendTitle');return !!t&&t.textContent.indexOf('%s')>=0;})()" % label, 12)
        time.sleep(0.5)
        ns2 = no_scroll(cdp)
        d = click_x(cdp, 0.55)
        T("%s 区间：仍无横滑" % label, bool(ns2.get("ok")), json.dumps(ns2))
        T("%s 区间：点击显示 MM-DD HH:MM 信息" % label, d["on"] and bool(re.match(r"^\d{2}-\d{2} \d{2}:\d{2} · 电量 [\d.]+ 度$", d["text"])),
          json.dumps(d, ensure_ascii=False))
    set_range(cdp, "24h")

    # 空态
    pick(cdp, "4-23B---424")
    time.sleep(0.8)
    de = detail(cdp)
    T("A13 空态/数据不足不显示游标", (not de["on"]) and de["text"] == "", json.dumps(de, ensure_ascii=False))

    # 宽度
    pick(cdp, "4-23A---321")
    time.sleep(0.8)
    for w, h in ((360, 800), (430, 900), (1280, 900)):
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 2, "mobile": w < 700})
        time.sleep(0.7)
        ov = cdp.eval("(function(){var d=document.documentElement;return {vw:innerWidth,sw:Math.max(d.scrollWidth,document.body.scrollWidth)};})()")
        T("A14 %d 宽：无横向溢出" % w, ov["sw"] <= ov["vw"] + 1, json.dumps(ov))
        d = click_x(cdp, 0.5)
        T("A15 %d 宽：详细查看仍可用" % w, d["on"] and bool(d["text"]), json.dumps(d, ensure_ascii=False))
    cdp.send("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 900, "deviceScaleFactor": 2, "mobile": True})
    time.sleep(0.6)

    # ===== 选中点后连续 resize：气泡固定在绘图区上方（趋势图右上角），选中数据不变 =====
    pick(cdp, "4-23A---321")
    time.sleep(0.8)
    set_range(cdp, "30d")
    time.sleep(0.5)
    click_x(cdp, 0.62)
    before = detail(cdp)
    T("A18 预先选中一个点（用于 resize 跟随）", before["on"] and bool(before["text"]), json.dumps(before, ensure_ascii=False))
    for w, h in ((360, 800), (430, 900), (1280, 900), (390, 900), (360, 740)):
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 2, "mobile": w < 700})
        time.sleep(0.9)
        d = detail(cdp)
        rr = tip_rects(cdp)
        ok_keep = d["on"] and d["text"] == before["text"]
        ok_fit = bool(rr and rr["tip"] and rr["plot"] and rr["card"]) and \
            rr["tip"]["l"] >= rr["card"]["l"] - 1.5 and rr["tip"]["r"] <= rr["card"]["r"] + 1.5 and \
            rr["tip"]["t"] >= rr["card"]["t"] - 1.5 and rr["tip"]["b"] <= rr["plot"]["t"] + 0.5
        T("A19 %dx%d resize 后气泡仍固定在绘图区上方/卡片内、选中数据不变" % (w, h), ok_keep and ok_fit,
          json.dumps({"keep": ok_keep, "fit": ok_fit, "text": d["text"], "rr": rr}, ensure_ascii=False)[:420])
    cdp.send("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 900, "deviceScaleFactor": 2, "mobile": True})
    time.sleep(0.6)

    # 截图
    try:
        os.makedirs(SHOTS, exist_ok=True)
        set_range(cdp, "30d")
        time.sleep(0.6)
        click_x(cdp, 0.62)
        time.sleep(0.2)
        shot = cdp.send("Page.captureScreenshot", {"format": "png"})
        import base64
        open(os.path.join(SHOTS, "power_detail_30d_390.png"), "wb").write(base64.b64decode(shot["data"]))
        T("A16 截图已保存", os.path.getsize(os.path.join(SHOTS, "power_detail_30d_390.png")) > 8000, "")
    except Exception as e:
        T("A16 截图已保存", False, str(e)[:120])

    errs = cdp.eval("JSON.stringify(window.__errs||[])")
    T("A17 0 JS 报错", errs == "[]", errs[:300])


def main():
    pc.build_previews()
    devnull = open(os.devnull, "wb")
    prof = tempfile.mkdtemp(prefix="edgeprof_det_")
    proc = None
    cdp = None
    httpd = None
    try:
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
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 900, "deviceScaleFactor": 2, "mobile": True})
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
        for fn in ("_power_preview.html", pc.COMMON):
            try:
                os.remove(os.path.join(HERE, fn))
            except Exception:
                pass
        shutil.rmtree(pc.REPORT_DIR, ignore_errors=True)
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 60)
    print("v2_power_detail_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
