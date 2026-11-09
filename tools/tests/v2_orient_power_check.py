# -*- coding: utf-8 -*-
"""task-22：横竖屏工具栏回归 + 电费关注宿舍刷新恢复审计（CDP top-level，真 resize 事件）

A. 横竖屏（CDP Emulation.setDeviceMetricsOverride 360x740 ↔ 740x360，多轮）：
   - tabs 数随比例变化（竖屏 4 格=3 工具+全部 / 横屏 5 格=4 工具+全部）；
   - `.tabs-thumb` 与当前按钮矩形对齐（±2px，含宽度）、无 `.tabs.morph` 残留、无按钮内联样式残留；
   - 点击 tab 可切页；fly 动画中切方向后无残留、可继续点；
   - 快速连续切换方向后状态一致；
   - 0 JS 报错。
B. 电费关注宿舍（web 侧）：
   B1. 选择后「立即刷新（<1200ms 防抖推送窗口内）」→ 从本机兜底恢复；
   B2. 选择并等待 UD 推送完成后刷新 → 从 UD 缓存恢复；
   B3. UD POST blob.power 正确 + 14 键契约（含 water）；
   B4. 删除本机 zq_power_sel 后仍从 UD 缓存恢复。
用法：cd C:\\...\\web\\tools && python tests\\v2_orient_power_check.py
"""
import functools
import http.server
import importlib.util
import json
import os
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
    print("[v2_orient_power_check] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

spec = importlib.util.spec_from_file_location("power_check", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

EDGE = pc.EDGE
HTTP_PORT = 8964
CDP_PORT = 9464
BASE = "http://127.0.0.1:%d/" % HTTP_PORT
SID = pc.SID_A
PV = "_power_preview.html"
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


SNAP = r"""
(function(){
  var bar=document.getElementById("tabsBar"); if(!bar) return null;
  var bs=[].slice.call(document.querySelectorAll("#tabsBar button[data-tab]"));
  var on=document.querySelector("#tabsBar button.on");
  var th=document.querySelector(".tabs-thumb");
  var tr=th?th.getBoundingClientRect():null, br=on?on.getBoundingClientRect():null;
  var styles=[];bs.forEach(function(b){var s=b.getAttribute("style")||"";if(s)styles.push(s);});
  return {vw:innerWidth,vh:innerHeight,n:bs.length,
    on:on?on.dataset.tab:"",
    morph:bar.classList.contains("morph"),
    thumb:tr?{x:Math.round(tr.left*10)/10,y:Math.round(tr.top*10)/10,w:Math.round(tr.width*10)/10,h:Math.round(tr.height*10)/10,op:th.style.opacity}:null,
    btn:br?{x:Math.round(br.left*10)/10,y:Math.round(br.top*10)/10,w:Math.round(br.width*10)/10,h:Math.round(br.height*10)/10}:null,
    styles:styles,
    thumbStyle:th?String(th.style.cssText):""};
})()
"""

BOOT_READY = ("(function(){var b=document.querySelector('#tabsBar button.on');"
              "return !!(b&&!document.body.classList.contains('id-locked'));})()")


def snap(cdp):
    return cdp.eval(SNAP)


def aligned(s):
    if not s or not s.get("thumb") or not s.get("btn"):
        return False
    t, b = s["thumb"], s["btn"]
    return abs(t["x"] - b["x"]) <= 2 and abs(t["w"] - b["w"]) <= 2


def set_metrics(cdp, w, h):
    cdp.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h,
                                                    "deviceScaleFactor": 2, "mobile": True})


def click_tab(cdp, tab):
    return cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"%s\"]');if(b)b.click();return !!b;})()" % tab)


def open_power(cdp):
    cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();return !!b;})()")
    time.sleep(0.35)
    ok = cdp.eval("(function(){var b=document.querySelector('#allCards [data-open=\"power\"]');if(b)b.click();return !!b;})()")
    time.sleep(0.9)
    return ok


def install_touch(cdp):
    cdp.eval(r"""
window.__swipeToolbar=function(dir){
  try{
    var d=document, b=document.querySelector("#tabsBar button.on"); if(!b)return false;
    var r=b.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
    function mk(px,py){return new Touch({identifier:1,target:d.body,clientX:px,clientY:py});}
    function fire(type,list){var ev=new TouchEvent(type,{bubbles:true,cancelable:true,touches:list,changedTouches:list,targetTouches:list});d.dispatchEvent(ev);}
    var t0=mk(x,y);fire("touchstart",[t0]);
    for(var i=1;i<=10;i++){var t=mk(x+dir*(80*i/10),y);fire("touchmove",[t]);}
    var te=mk(x+dir*80,y);
    d.dispatchEvent(new TouchEvent("touchend",{bubbles:true,cancelable:true,touches:[],changedTouches:[te],targetTouches:[]}));
    return true;
  }catch(e){return String(e);}
};""")
    return True


def run_power(cdp):
    # 冷启动干净状态
    cdp.send("Page.navigate", {"url": BASE + "tests/" + PV})
    if not wait_until(cdp, BOOT_READY, 30):
        T("B0 电费环境启动完成", False, "timeout")
        return
    T("B0 电费环境启动完成", True, "")
    time.sleep(2.8)  # 等 boot UD.pull 完成并写回 cache（power 为空）
    ok_open = open_power(cdp) and cdp.eval("!!document.getElementById('pwSelect')")
    T("B1 电费页已打开", ok_open, "")
    cache_power_before = cdp.eval("(function(){try{var b=JSON.parse(localStorage.getItem('zq_udcache_%s')||'null');return b&&b.power?JSON.stringify(b.power):null;}catch(e){return null;}})()" % SID)
    T("B2 刷新前 UD 缓存已存在且 power 为空", bool(cache_power_before) and '"sel":""' in str(cache_power_before).replace(" ", ""),
      cache_power_before)

    def pick(rv):
        return cdp.eval("(function(){var s=document.getElementById('pwSelect');if(!s)return false;"
                        "s.value='%s';s.dispatchEvent(new Event('change',{bubbles:true}));return true;})()" % rv)

    pick("4-23A---321")
    time.sleep(0.12)
    ls_sel = cdp.eval("(function(){try{return localStorage.getItem('zq_power_sel_%s')||'';}catch(e){return '';}})()" % SID)
    T("B3 选择立即写入本机兜底 zq_power_sel", ls_sel == "4-23A---321", ls_sel)
    cache_sel = cdp.eval("(function(){try{var b=JSON.parse(localStorage.getItem('zq_udcache_%s')||'null');return b&&b.power?String(b.power.sel||''):'<none>';}catch(e){return '<err>';}})()" % SID)

    # 立即刷新（1200ms 防抖窗口内）
    cdp.send("Page.reload", {"ignoreCache": False})
    wait_until(cdp, BOOT_READY, 30)
    time.sleep(1.0)
    open_power(cdp)
    time.sleep(1.2)
    sel_after = cdp.eval("(function(){var s=document.getElementById('pwSelect');return s?s.value:'';})()")
    T("B4 选择后立即刷新（防抖推送前）：关注宿舍应恢复", sel_after == "4-23A---321",
      json.dumps({"restored": sel_after, "udCachePowerBeforeReload": cache_sel, "localSelBeforeReload": ls_sel}, ensure_ascii=False))

    # 正常等待推送后刷新
    pick("4-23A---324")
    pushed = False
    t0 = time.time()
    while time.time() - t0 < 15:
        pushed = cdp.eval("(function(){var a=window.__udPosts||[];if(!a.length)return false;try{var b=JSON.parse(a[a.length-1].blob);return !!(b.power&&b.power.sel==='4-23A---324');}catch(e){return false;}})()") is True
        if pushed:
            break
        time.sleep(0.2)
    last = cdp.eval("(function(){var a=window.__udPosts||[];if(!a.length)return null;try{return a[a.length-1].blob;}catch(e){return null;}})()")
    T("B5 UD 推送成功（POST blob.power.sel=324）", pushed, str(last)[:160])
    keys = []
    blob_obj = None
    try:
        blob_obj = json.loads(last)
        keys = list(blob_obj.keys())
    except Exception:
        pass
    T("B6 UD blob 顶层 14 键契约（含 water）", len(keys) == 14 and "water" in keys and keys[keys.index("power") + 1] == "water", ",".join(keys)[:200])
    T("B7 blob.power 含 sel/at/low", bool(blob_obj and isinstance(blob_obj.get("power"), dict) and "sel" in blob_obj["power"] and "at" in blob_obj["power"]),
      json.dumps(blob_obj.get("power") if blob_obj else None, ensure_ascii=False))

    cdp.send("Page.reload", {"ignoreCache": False})
    wait_until(cdp, BOOT_READY, 30)
    time.sleep(1.0)
    open_power(cdp)
    time.sleep(1.2)
    T("B8 推送完成后刷新：关注宿舍恢复", cdp.eval("(function(){var s=document.getElementById('pwSelect');return s?s.value:'';})()") == "4-23A---324",
      cdp.eval("(function(){var s=document.getElementById('pwSelect');return s?s.value:'none';})()"))

    # 删除本机兜底键，仍从 UD 缓存恢复
    cdp.eval("try{localStorage.removeItem('zq_power_sel_%s');}catch(e){}" % SID)
    cdp.send("Page.reload", {"ignoreCache": False})
    wait_until(cdp, BOOT_READY, 30)
    time.sleep(1.0)
    open_power(cdp)
    time.sleep(1.2)
    T("B9 本机兜底键缺失：仍从 UD 缓存恢复", cdp.eval("(function(){var s=document.getElementById('pwSelect');return s?s.value:'';})()") == "4-23A---324",
      cdp.eval("(function(){var s=document.getElementById('pwSelect');return s?s.value:'none';})()"))

    errs = cdp.eval("JSON.stringify(window.__errs||[])")
    T("B10 电费场景 0 JS 报错", errs == "[]", errs[:200])


def main():
    devnull = open(os.devnull, "wb")
    prof = tempfile.mkdtemp(prefix="edgeprof_op_")
    proc = None
    cdp = None
    httpd = None
    try:
        pc.build_previews()
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
        set_metrics(cdp, 360, 740)
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        cdp.send("Page.navigate", {"url": BASE + "tests/" + PV})
        if wait_until(cdp, BOOT_READY, 30):
            T("A0 应用启动完成", True, "")
            time.sleep(2.0)
            # orientation 场景继续在同一个页面上下文
            run_orientation_body(cdp)
            run_power(cdp)
        else:
            T("A0 应用启动完成", False, "boot timeout")
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
        for fn in (PV, pc.COMMON):
            try:
                os.remove(os.path.join(HERE, fn))
            except Exception:
                pass
        shutil.rmtree(pc.REPORT_DIR, ignore_errors=True)
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 60)
    print("v2_orient_power_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


def run_orientation_body(cdp):
    """orientation 断言（页面已启动、360x740、已等待 2s）。"""
    s = snap(cdp)
    T("A1 竖屏 360x740：tabs=4 格（3 工具+全部）", s and s["n"] == 4, json.dumps({"vw": s["vw"], "vh": s["vh"], "n": s["n"]} if s else None))
    T("A2 竖屏：thumb 与当前按钮对齐（±2px，含宽度）", aligned(s), json.dumps({"thumb": s["thumb"], "btn": s["btn"]} if s else None))
    T("A3 竖屏：无 .tabs.morph 残留", s and not s["morph"], s and str(s["morph"]))

    seq = [(740, 360, 5), (360, 740, 4), (740, 360, 5), (360, 740, 4), (740, 360, 5)]
    ok_all = True
    for i, (w, h, n) in enumerate(seq, 1):
        set_metrics(cdp, w, h)
        time.sleep(0.75)
        st = snap(cdp)
        ok_n = st and st["n"] == n
        ok_a = aligned(st)
        ok_m = st and not st["morph"]
        ok_s = st and len(st["styles"]) == 0
        ok_all = ok_all and ok_n and ok_a and ok_m and ok_s
        T("A4.%d 切到 %dx%d：tabs=%d 格" % (i, w, h, n), ok_n, json.dumps({"n": st["n"], "vw": st["vw"], "vh": st["vh"]} if st else None))
        T("A5.%d 切到 %dx%d：thumb 对齐/无 morph/无内联残留" % (i, w, h), ok_a and ok_m and ok_s,
          json.dumps({"thumb": st["thumb"], "btn": st["btn"], "morph": st["morph"], "styles": st["styles"]} if st else None)[:400])
    T("A6 多轮横竖屏后整体状态一致", ok_all, "")

    before = snap(cdp)["on"]
    click_tab(cdp, "hw")
    time.sleep(0.45)
    after = snap(cdp)["on"]
    T("A7 横竖屏切换后点击 tab 可切页", after == "hw" and after != before, before + "->" + after)
    click_tab(cdp, "draw")
    time.sleep(0.4)

    for k in range(6):
        set_metrics(cdp, 740 if k % 2 == 0 else 360, 360 if k % 2 == 0 else 740)
        time.sleep(0.04)
    time.sleep(1.1)
    s2 = snap(cdp)
    T("A8 快速连续切换后：tabs 数正确", s2 and s2["n"] in (4, 5), s2 and str(s2["n"]))
    T("A9 快速连续切换后：thumb 对齐、无 morph、无内联样式残留",
      aligned(s2) and not s2["morph"] and len(s2["styles"]) == 0,
      json.dumps({"thumb": s2["thumb"], "btn": s2["btn"], "morph": s2["morph"], "styles": s2["styles"]} if s2 else None)[:400])
    b9 = snap(cdp)["on"]
    click_tab(cdp, "nt")
    time.sleep(0.45)
    T("A10 快速切换后点击 tab 仍可切页", snap(cdp)["on"] == "nt" and snap(cdp)["on"] != b9, b9 + "->" + snap(cdp)["on"])
    click_tab(cdp, "draw")
    time.sleep(0.4)

    install_touch(cdp)
    cdp.eval("window.__swipeToolbar(-1)")
    time.sleep(0.09)
    set_metrics(cdp, 740, 360)
    time.sleep(0.9)
    s3 = snap(cdp)
    T("A11 fly 动画中横竖屏切换：无 morph/内联残留", s3 and not s3["morph"] and len(s3["styles"]) == 0,
      json.dumps({"morph": s3["morph"], "styles": s3["styles"]} if s3 else None))
    b11 = snap(cdp)["on"]
    click_tab(cdp, "all")
    time.sleep(0.45)
    T("A12 fly 中切换后点击 tab 仍可用（无卡死）", snap(cdp)["on"] == "all", "before:" + b11 + " after:" + snap(cdp)["on"])

    set_metrics(cdp, 360, 740)
    time.sleep(0.7)
    click_tab(cdp, "draw")
    time.sleep(0.4)
    s4 = snap(cdp)
    T("A13 恢复竖屏后 tabs=4 且可切页", s4 and s4["n"] == 4 and s4["on"] == "draw",
      json.dumps({"n": s4["n"], "on": s4["on"]}) if s4 else None)


if __name__ == "__main__":
    main()
