# -*- coding: utf-8 -*-
r"""专项门禁：班级工具站「宿舍水量 · 桌面端比例」 —— 2026-11-06 增量 18

目标（用户需求「优化网页端水费工具比例」）：
  - ≥1280px：三栏等高（hero / 新增抄表+规则 chips / 抄表历史），1280×800 一屏放下；1440/1600 用满 wrap 宽度（1292/1492）。
  - 960–1279px：两栏（hero+hist / form+rules），页高显著低于旧版（≤1000），无横向溢出。
  - 12 条记录/空态不改变页高（历史列表内部滚动），无横向溢出。
  - <960px 手机端保持原单列结构。

骨架复用 `tools/tests/water_check.py`（headless Edge + CDP + 注入 mock 的预览页）。
用法（cwd = web\\tools）：
  python tests\\v2_water_layout_check.py
  set SPEC_CHECK=<副本.html>  # 只读复盘任意 index.html 副本
退出码 0 = 全绿。
"""
import sys
import os
import json
import tempfile
import subprocess
import threading
import functools
import http.server
import time
import shutil
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import water_check as W

SHOTS = os.path.join(HERE, "_water_shots")
RESULTS = []
RUN_TMP = None


def T(key, ok, note=""):
    RESULTS.append({"k": key, "ok": bool(ok), "note": str(note or "")[:320]})
    print(("[PASS] " if ok else "[FAIL] ") + key + (("  -- " + str(note)[:300]) if note else ""))
    try:
        sys.stdout.flush()
    except Exception:
        pass
    return bool(ok)


def rv_rects(cdp):
    return W.ev(cdp, r"""
(function(){
  var de=document.documentElement,out={vw:de.clientWidth,vh:de.clientHeight,
    scrollH:de.scrollHeight,scrollW:de.scrollWidth};
  function r(sel){var e=document.querySelector(sel);if(!e)return null;var b=e.getBoundingClientRect();
    return {x:Math.round(b.x),y:Math.round(b.y),w:Math.round(b.width),h:Math.round(b.height),
            b:Math.round(b.bottom),r:Math.round(b.right)};}
  out.dash=r('#wtDash');out.hero=r('#wtHero');out.form=r('.wt-form');
  out.hist=r('.wt-hist');out.rules=r('.wt-rules');out.list=r('#wtList');out.chip=r('#wtSync');
  var d=document.querySelector('#wtDash');
  out.gridCols=d?getComputedStyle(d).gridTemplateColumns:null;
  out.gridAreas=d?getComputedStyle(d).gridTemplateAreas:null;
  out.ruleBodyDisplay=(function(){var e=document.querySelector('#wtRuleBody');return e?getComputedStyle(e).display:null;})();
  out.numClass=(function(){var e=document.querySelector('#wtLastNum');return e?String(e.className):null;})();
  out.chipHidden=(function(){var e=document.querySelector('#wtSync');return e?!!e.hidden:null;})();
  out.listScrollable=(function(){var e=document.querySelector('#wtList');return e?{sh:e.scrollHeight,ch:e.clientHeight}:null;})();
  out.rows=document.querySelectorAll('#wtList [data-wm]').length;
  return out;
})()
""") or {}


def overflow(cdp):
    return W.ev(cdp, r"""
(function(){var de=document.documentElement,bad=[];
Array.prototype.slice.call(document.querySelectorAll('#s-water *')).forEach(function(e){
  var r=e.getBoundingClientRect();
  if(r.width>0&&r.right>de.clientWidth+1&&getComputedStyle(e).position!=='fixed')bad.push(e.tagName+'.'+String(e.className).split(' ')[0]);
});
return {cw:de.clientWidth,sw:de.scrollWidth,bad:bad.slice(0,6)};})()
""") or {}


def nav_fixture(cdp, rooms, power_sel=None):
    seed = W.ud_blob(power_sel=(W.RV321 if power_sel is None else power_sel), water_rooms=rooms)
    ok = W.nav(cdp, W.purl(ud=seed), clear=True)
    W.wait_ud_baseline(cdp, W.SID_A)
    W.open_water_page(cdp)
    W.sleep(0.5)
    return ok


def recs3():
    return [W.rec(W.M4, 100.0), W.rec(W.M3, 113.74), W.rec(W.M2, 130.0)]


def recs12():
    return [W.rec(W.month_add(date(2026, 1, 1), i), 90.0 + i * 5.5) for i in range(12)]


def main():
    global RUN_TMP
    W.RUN_TMP = os.path.join(W.TMP, "run_layout_%d" % os.getpid())
    RUN_TMP = W.RUN_TMP
    os.makedirs(RUN_TMP, exist_ok=True)
    W.PREVIEW = os.path.join(RUN_TMP, "_layout_preview.html")
    W.build_preview()
    os.makedirs(SHOTS, exist_ok=True)
    W.HTTP_PORT = W.free_port()
    W.CDP_PORT = W.free_port()
    W.BASE = "http://127.0.0.1:%d/" % W.HTTP_PORT
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", W.HTTP_PORT),
                                           functools.partial(W.QuietHandler, directory=W.ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.35)
    prof = tempfile.mkdtemp(prefix="edgeprof_layout_", dir=RUN_TMP)
    devnull = open(os.devnull, "wb")
    proc = subprocess.Popen([W.EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--disable-extensions", "--force-device-scale-factor=1",
        "--hide-scrollbars", "--remote-debugging-port=%d" % W.CDP_PORT,
        "--user-data-dir=" + prof, "about:blank"], stdout=devnull, stderr=devnull)
    cdp = None
    try:
        cdp = W.CDP(W.get_ws(W.CDP_PORT))
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        W.set_viewport(cdp, 430, 900)

        # ---------- 3 条记录：六档比例 ----------
        nav_fixture(cdp, {W.RV321: {"p": 4, "recs": recs3()}})
        T("L01 3 条记录：水量页可打开且无 JS 报错",
          W.jdisplay(cdp, "#s-water") != "none" and len(W.ev(cdp, "window.__errs||[]") or []) == 0,
          len(W.ev(cdp, "window.__errs||[]") or []))
        W.set_viewport(cdp, 1280, 800)
        W.sleep(0.5)
        m = rv_rects(cdp)
        o = overflow(cdp)
        T("L02 1280×800：纵向不滚动（scrollH ≤ 810）", 0 < m.get("scrollH", 0) <= 810, m.get("scrollH"))
        T("L03 1280×800：三栏 grid（3 列 / areas=hero form hist）",
          len(str(m.get("gridCols") or "").split()) == 3 and "hero form hist" in str(m.get("gridAreas") or ""),
          str(m.get("gridCols")) + " | " + str(m.get("gridAreas")))
        hero, form, hist, rules = m.get("hero") or {}, m.get("form") or {}, m.get("hist") or {}, m.get("rules") or {}
        T("L04 1280×800：hero 与抄表历史等高（±3px）",
          abs((hero.get("h") or 0) - (hist.get("h") or 0)) <= 3,
          "hero=%s hist=%s" % (hero.get("h"), hist.get("h")))
        T("L05 1280×800：中栏 form+gap+规则条 = hero 高度（±6px，无结构性空洞）",
          abs(((form.get("h") or 0) + 16 + (rules.get("h") or 0)) - (hero.get("h") or 0)) <= 6,
          "form=%s rules=%s hero=%s" % (form.get("h"), rules.get("h"), hero.get("h")))
        T("L06 1280×800：dash 宽度 = 内容宽 1188（左右不留 56px 空）",
          abs((m.get("dash") or {}).get("w", 0) - 1188) <= 2, (m.get("dash") or {}).get("w"))
        T("L07 1280×800：规则卡为横向 chips（#wtRuleBody display=flex）",
          m.get("ruleBodyDisplay") == "flex", m.get("ruleBodyDisplay"))
        T("L08 1280×800：无横向溢出", (o.get("sw") or 0) <= (o.get("cw") or 0) + 1 and not o.get("bad"),
          "sw=%s cw=%s bad=%s" % (o.get("sw"), o.get("cw"), o.get("bad")))
        W.shot(cdp, os.path.join(SHOTS, "layout_1280x800.png"))

        for vw, vh, dw, name in ((1440, 900, 1292, "1440×900"), (1600, 900, 1492, "1600×900")):
            W.set_viewport(cdp, vw, vh)
            W.sleep(0.5)
            m2 = rv_rects(cdp)
            o2 = overflow(cdp)
            T("L09 %s：不滚动且用满内容宽 %d" % (name, dw),
              (m2.get("scrollH") or 0) <= vh and abs((m2.get("dash") or {}).get("w", 0) - dw) <= 2,
              "scrollH=%s dashW=%s" % (m2.get("scrollH"), (m2.get("dash") or {}).get("w")))
            T("L10 %s：无横向溢出" % name,
              (o2.get("sw") or 0) <= (o2.get("cw") or 0) + 1 and not o2.get("bad"), o2.get("bad"))
            W.shot(cdp, os.path.join(SHOTS, "layout_%dx%d.png" % (vw, vh)))

        # 960 / 1024：两栏、页高受控、无溢出
        for vw in (960, 1024):
            W.set_viewport(cdp, vw, 800)
            W.sleep(0.5)
            m3 = rv_rects(cdp)
            o3 = overflow(cdp)
            cols = str(m3.get("gridCols") or "").split()
            form3, rules3 = m3.get("form") or {}, m3.get("rules") or {}
            T("L11 %d×800：两栏布局（2 列 / rules 与 form 同排右侧）" % vw,
              len(cols) == 2 and (rules3.get("x") or 0) > (form3.get("x") or 0)
              and abs((rules3.get("y") or 0) - (form3.get("y") or 0)) <= 2,
              "cols=%s form.x=%s rules.x=%s" % (m3.get("gridCols"), form3.get("x"), rules3.get("x")))
            T("L12 %d×800：页高受控（scrollH ≤ 1000，旧版 1126）" % vw,
              0 < (m3.get("scrollH") or 0) <= 1000, m3.get("scrollH"))
            T("L13 %d×800：规则卡非 chips（#wtRuleBody display=block）" % vw,
              m3.get("ruleBodyDisplay") == "block", m3.get("ruleBodyDisplay"))
            T("L14 %d×800：无横向溢出" % vw,
              (o3.get("sw") or 0) <= (o3.get("cw") or 0) + 1 and not o3.get("bad"), o3.get("bad"))

        # ---------- 12 条记录：页高不变、历史内部滚动 ----------
        nav_fixture(cdp, {W.RV321: {"p": 4, "recs": recs12()}})
        W.set_viewport(cdp, 1280, 800)
        W.sleep(0.5)
        m4 = rv_rects(cdp)
        T("L15 12 条记录 @1280×800：页高不随记录数增长（scrollH ≤ 810）",
          0 < (m4.get("scrollH") or 0) <= 810, m4.get("scrollH"))
        sc = m4.get("listScrollable") or {}
        T("L16 12 条记录：抄表历史内部滚动（scrollHeight > clientHeight）",
          (sc.get("sh") or 0) > (sc.get("ch") or 0) + 4 and (m4.get("rows") or 0) == 12,
          "rows=%s sh/ch=%s/%s" % (m4.get("rows"), sc.get("sh"), sc.get("ch")))
        W.shot(cdp, os.path.join(SHOTS, "layout_1280x800_12rec.png"))

        # ---------- 空态：不滚动、无数据占位 ----------
        nav_fixture(cdp, {}, power_sel="")
        W.set_viewport(cdp, 1280, 800)
        W.sleep(0.5)
        m5 = rv_rects(cdp)
        T("L17 空态 @1280×800：不滚动（scrollH ≤ 810）", 0 < (m5.get("scrollH") or 0) <= 810, m5.get("scrollH"))
        T("L18 空态：上次抄表占位 no-data、同步状态隐藏",
          "no-data" in str(m5.get("numClass") or "") and m5.get("chipHidden") is True,
          "%s / %s" % (m5.get("numClass"), m5.get("chipHidden")))

        # ---------- 手机 430：单列结构不变、无横向溢出 ----------
        W.set_viewport(cdp, 430, 900)
        W.sleep(0.5)
        m6 = rv_rects(cdp)
        o6 = overflow(cdp)
        hero6, form6 = m6.get("hero") or {}, m6.get("form") or {}
        hist6, rules6 = m6.get("hist") or {}, m6.get("rules") or {}
        T("L19 430×900：单列纵向顺序 hero→form→hist→rules",
          (hero6.get("y") or 0) < (form6.get("y") or 0) < (hist6.get("y") or 0) < (rules6.get("y") or 0),
          "%s/%s/%s/%s" % (hero6.get("y"), form6.get("y"), hist6.get("y"), rules6.get("y")))
        T("L20 430×900：无横向溢出且规则卡回到纵向行",
          (o6.get("sw") or 0) <= (o6.get("cw") or 0) + 1 and not o6.get("bad") and m6.get("ruleBodyDisplay") == "block",
          "sw=%s cw=%s display=%s bad=%s" % (o6.get("sw"), o6.get("cw"), m6.get("ruleBodyDisplay"), o6.get("bad")))
        W.shot(cdp, os.path.join(SHOTS, "layout_430x900.png"))

        errs = W.ev(cdp, "window.__errs||[]") or []
        cerrs = W.ev(cdp, "window.__cerrs||[]") or []
        exts = W.ev(cdp, W.EXTS_JS) or []
        T("L21 全程 0 JS 报错", len(errs) == 0, " | ".join([str(x) for x in errs[:3]]))
        T("L22 全程 0 console.error", len(cerrs) == 0, " | ".join([str(x) for x in cerrs[:3]]))
        T("L23 全程无外部请求", len(exts) == 0, " | ".join([str(x) for x in exts[:3]]))
    finally:
        try:
            if cdp:
                cdp.close()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass
        try:
            devnull.close()
        except Exception:
            pass
        try:
            shutil.rmtree(RUN_TMP, ignore_errors=True)
        except Exception:
            pass

    fails = [r for r in RESULTS if not r["ok"]]
    print("")
    print("=" * 64)
    if fails:
        print("失败明细 (%d):" % len(fails))
        for r in fails:
            print("  - %s%s" % (r["k"], ("  -- " + r["note"]) if r["note"] else ""))
    print("截图目录:", SHOTS)
    total = len(RESULTS)
    print("v2_water_layout_check: %d/%d PASS" % (total - len(fails), total))
    return 0 if (total > 0 and not fails) else 1


if __name__ == "__main__":
    sys.exit(main())
