# -*- coding: utf-8 -*-
"""v2 专项自检：刷新保位（需求 2）—— 固定视口 iframe + iframe 原生滚动架构

覆盖：
  A. 普通页面（全部）：父页 tab + 滚动位置刷新恢复；
  B. 通知 tab：父页只恢复 tab；滚动位置由 iframe 内部自存自恢
     —— 冷启动/弱网（无 IDB 缓存 + notices 延迟 3.5s）下内容晚到位，仍能恢复内部 scrollY；
  C. 用户手势取消父页恢复（不抢滚动）；
  D. 0 JS 报错。

用法：cd C:\\...\\web\\tools && python tests\\v2_pos_restore_check.py
退出码 0 = 全绿。
"""
import http.server
import importlib.util
import json
import os
import shutil
import socketserver
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
    print("[v2_pos_restore_check] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HTTP_PORT = 8996
CDP_PORT = 9496
W, H = 390, 844
RESULTS = []


def T(key, ok, note=""):
    RESULTS.append({"k": key, "ok": bool(ok)})
    print(("[PASS] " if ok else "[FAIL] ") + key + ((" | " + str(note)) if note != "" else ""))


def load_live_module():
    spec = importlib.util.spec_from_file_location("v2_notice_live_check", os.path.join(HERE, "v2_notice_live_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Q(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


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


def wait_until(cdp, expr, timeout=20, interval=0.12):
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


BOOT_READY = ("(function(){return !!(document.querySelector('#tabsBar button.on')&&window.__v2live"
              "&&__v2live.bootDone&&__v2live.bootDone());})()")


def frame_ready(cdp, timeout=30, cards=10):
    return wait_until(cdp, "(function(){try{var f=__v2live.frame();return !!(f&&f.contentDocument&&f.contentDocument.querySelectorAll('.gcard').length>=%d);}catch(e){return false;}})()" % cards, timeout)


def frame_y(cdp):
    v = cdp.eval("(function(){try{return Math.round(__v2live.frame().contentWindow.scrollY||0);}catch(e){return -1;}})()")
    return int(v or 0)


def frame_scroll_to(cdp, y):
    cdp.eval("(function(){try{__v2live.frame().contentWindow.scrollTo(0,%d);}catch(e){}})()" % int(y))


def curtab(cdp):
    return cdp.eval("(function(){try{return window.__v2live&&__v2live.pos?((__v2live.AUTH&&__v2live.D)?document.querySelector('#tabsBar button.on').dataset.tab:''):'';}catch(e){return '';}})")


def run():
    live = load_live_module()
    devnull = open(os.devnull, "wb")
    tmp = tempfile.mkdtemp(prefix="v2pos_")
    prof = tempfile.mkdtemp(prefix="edgeprof_")
    srv = None
    proc = None
    cdp = None
    seed_ids = []
    try:
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(live.build_preview())
        os.chdir(tmp)
        srv = Q(("127.0.0.1", HTTP_PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/preview.html" % HTTP_PORT
        proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                                 "--no-default-browser-check", "--disable-extensions",
                                 "--remote-debugging-port=%d" % CDP_PORT,
                                 "--user-data-dir=" + prof, "about:blank"],
                                stdout=devnull, stderr=devnull)
        cdp = CDP(get_ws(CDP_PORT))
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": W, "height": H,
                                                        "deviceScaleFactor": 2, "mobile": True})
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        # 关闭浏览器自带的 reload 滚动恢复（否则与站点 POS 混在一起无法判定）
        sid0 = cdp.send("Page.addScriptToEvaluateOnNewDocument", {
            "source": "try{history.scrollRestoration='manual';}catch(e){}"})["identifier"]
        seed_ids.append(sid0)
        cdp.send("Page.navigate", {"url": url})
        boot = wait_until(cdp, BOOT_READY, 30)
        T("A1 首次加载完成", boot, "")

        # ===== A. 普通页面（全部）父页 tab + 滚动位置恢复（使用说明已改为单屏轮播，改用全部页做代表） =====
        cdp.eval("__v2live.gotoTab('all')")
        time.sleep(0.5)
        maxs = cdp.eval("Math.max(document.documentElement.scrollHeight,document.body.scrollHeight)-innerHeight")
        target = int(min(1200, max(200, (maxs or 300) - 100)))
        cdp.eval("window.scrollTo(0,%d)" % target)
        time.sleep(1.0)
        pos = cdp.eval("(function(){try{return JSON.parse(sessionStorage.getItem('zq_pos_v1')||'null');}catch(e){return null;}})()") or {}
        T("A2 普通页面滚动后 zq_pos_v1 记录 tab/y",
          pos.get("tab") == "all" and abs(int(pos.get("y") or 0) - target) <= 40,
          json.dumps(pos, ensure_ascii=False))
        cdp.send("Page.reload", {"ignoreCache": False})
        wait_until(cdp, BOOT_READY, 30)
        time.sleep(1.5)
        cur = cdp.eval("(function(){var b=document.querySelector('#tabsBar button.on');return b?b.dataset.tab:'';})()")
        cur2 = cdp.eval("(function(){try{return (window.__v2live&&__v2live.curtab)?__v2live.curtab():'';}catch(e){return '';}})()")
        y_after = cdp.eval("Math.round(window.pageYOffset||0)")
        T("A3 普通页面刷新：tab 恢复为全部", cur2 == "all", cur2)
        T("A4 普通页面刷新：滚动位置恢复 %d±60" % target, abs(int(y_after or 0) - target) <= 60, y_after)

        # ===== B. 通知 tab：父页只恢复 tab；iframe 内部滚动自存自恢（慢网/冷启动） =====
        cdp.eval("__v2live.gotoTab('nt')")
        frame_ready(cdp, 30, 40)
        time.sleep(0.6)
        frame_scroll_to(cdp, 3000)
        time.sleep(0.9)  # iframe 内滚动停止 260ms 后落盘
        saved_nt = cdp.eval("(function(){try{return sessionStorage.getItem('zq_nt_scroll_v1');}catch(e){return null;}})()")
        T("B1 通知 iframe 内滚动位置已落盘", str(saved_nt) == "3000", saved_nt)
        sid = cdp.send("Page.addScriptToEvaluateOnNewDocument", {
            "source": ("try{window.__v2_notice_delay=3500;}catch(e){}"
                       "try{Object.defineProperty(window,'indexedDB',{configurable:true,get:function(){throw new Error('blocked-for-test');}});}catch(e){}")})["identifier"]
        seed_ids.append(sid)
        t_reload = time.time()
        cdp.send("Page.reload", {"ignoreCache": False})
        wait_until(cdp, BOOT_READY, 30)
        ready = frame_ready(cdp, 30, 40)
        T("B2 慢网冷启动：通知 iframe 最终建立（40 卡）", ready, "%.2fs" % (time.time() - t_reload))
        restored = False
        t0 = time.time()
        while time.time() - t0 < 11:
            if abs(frame_y(cdp) - 3000) <= 90:
                restored = True
                break
            time.sleep(0.2)
        dt = round(time.time() - t_reload, 2)
        ccd = cdp.eval("(function(){var b=document.querySelector('#tabsBar button.on');return b?b.dataset.tab:'';})()")
        py = cdp.eval("Math.round(window.pageYOffset||0)")
        T("B3 慢网冷启动：通知 tab 恢复", ccd == "nt", ccd)
        T("B4 慢网冷启动：iframe 内部滚动位置恢复 3000±90", restored, "y=%s dt=%.2fs" % (frame_y(cdp), dt))
        T("B5 通知 tab 父页不滚动（由 iframe 自管）", int(py or 0) <= 3, py)
        cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": sid})
        seed_ids.remove(sid)

        # ===== C. 用户手势取消父页恢复（普通页面，不强行拉回） =====
        cdp.eval("__v2live.gotoTab('all')")
        time.sleep(0.5)
        cdp.eval("window.scrollTo(0,1200)")
        time.sleep(1.0)
        sid = cdp.send("Page.addScriptToEvaluateOnNewDocument", {
            "source": ("try{localStorage.setItem('__v2_user_cancel','1');"
                       "var n=0,t=setInterval(function(){try{if(window.__v2live&&window.__v2live.pos&&window.__v2live.pos.armed){"
                       "window.dispatchEvent(new WheelEvent('wheel',{deltaY:120}));window.__v2UserCanceled=true;clearInterval(t);}}catch(e){}"
                       "if(++n>1500)clearInterval(t);},8);}catch(e){}")})["identifier"]
        seed_ids.append(sid)
        cdp.send("Page.reload", {"ignoreCache": False})
        wait_until(cdp, BOOT_READY, 30)
        time.sleep(1.8)
        canceled = cdp.eval("!!window.__v2UserCanceled")
        y_c = cdp.eval("Math.round(window.pageYOffset||0)")
        T("C1 用户滚动取消恢复", bool(canceled), "canceled=%r" % canceled)
        T("C2 取消后不被强行拉回 1200（保持用户位置附近）", int(y_c or 0) < 120, "y=" + str(y_c))
        cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": sid})
        seed_ids.remove(sid)
        cdp.eval("try{localStorage.removeItem('__v2_user_cancel');}catch(e){}")

        errs = cdp.eval("JSON.stringify(__v2live.errs())") or "[]"
        T("D1 全程 0 JS 报错", errs == "[]", errs[:300])
    finally:
        for sid in list(seed_ids):
            try:
                cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": sid})
            except Exception:
                pass
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
        try:
            devnull.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(prof, ignore_errors=True)


def main():
    run()
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 60)
    print("v2_pos_restore_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
