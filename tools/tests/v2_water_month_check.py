# -*- coding: utf-8 -*-
r"""专项门禁：班级工具站「宿舍水量 · 月份选择 UI」 —— 2026-11-07

用户需求：「优化月份选择 ui，使页面更美观」。

覆盖：
  - 契约兼容：真实值仍是隐藏 `#wtMonth`（type=month），保存/预览/测试 set_input 逻辑不变；
  - 自定义控件：‹ 月步进 › + 点开月网格；默认当前月、标签「YYYY 年 MM 月」；
  - 弹层：12 个月网格 / 选中年份 / 「本月」/ 上·下一年 / 已有记录月份小圆点 / 选中态；
  - 交互：选择回写值并联动预览；Esc 关闭且焦点回触发按钮；点空白关闭；方向键移动；
  - 禁用：未选关注宿舍时控件与弹层不可用；
  - 响应式：1280 桌面与 390 手机弹层不出视口、无横向溢出、按钮可点高度 ≥40px；
  - 切页自动收起弹层；全程 0 JS 报错 / 0 console.error / 无外部请求。

骨架复用 `tools/tests/water_check.py`（headless Edge + CDP + 注入 mock 的预览页）。
用法（cwd = web\\tools）：
  python tests\\v2_water_month_check.py
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


def js(x):
    return json.dumps(x, ensure_ascii=False)


def shot_vp(cdp, path):
    """可视区截图（不用 captureBeyondViewport：它触发 resize 会收起弹层）。"""
    import base64
    try:
        r = cdp.send("Page.captureScreenshot", {"format": "png"}, timeout=60)
        data = base64.b64decode(r.get("data") or "")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(data)
        return len(data)
    except Exception:
        return 0


def rect(cdp, sel):
    return W.ev(cdp, "(function(){var e=document.querySelector(%s);if(!e)return null;var r=e.getBoundingClientRect();"
                     "return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),"
                     "r:Math.round(r.right),b:Math.round(r.bottom)};})()" % js(sel)) or {}


def month_info(cdp):
    return W.ev(cdp, r"""
(function(){
  var out={};
  function q(sel){return document.querySelector(sel);}
  var inp=q('#wtMonth'),btn=q('#wtMonthBtn'),pop=q('#wtMonthPop');
  out.value=inp?String(inp.value):null;
  out.type=inp?String(inp.getAttribute('type')):null;
  out.disabled=inp?!!inp.disabled:null;
  out.inpW=inp?Math.round(inp.getBoundingClientRect().width):null;
  out.inpOpacity=inp?String(getComputedStyle(inp).opacity):null;
  out.btnText=btn?String(btn.textContent||'').replace(/\s+/g,''):null;
  out.y=String((q('#wtMonthY')||{}).textContent||'');
  out.m=String((q('#wtMonthM')||{}).textContent||'');
  out.expanded=btn?String(btn.getAttribute('aria-expanded')):null;
  out.btnDisabled=btn?!!btn.disabled:null;
  out.prevDisabled=q('#wtMonthPrev')?!!q('#wtMonthPrev').disabled:null;
  out.nextDisabled=q('#wtMonthNext')?!!q('#wtMonthNext').disabled:null;
  out.popHidden=pop?!!pop.hidden:null;
  out.popYear=String((q('#wtMonthPopY')||{}).textContent||'');
  out.gridCount=document.querySelectorAll('#wtMonthGrid [data-ym]').length;
  var on=q('#wtMonthGrid .wt-mo.on');
  out.selYm=on?String(on.getAttribute('data-ym')):null;
  out.nowCount=document.querySelectorAll('#wtMonthGrid .wt-mo.now').length;
  out.dotCount=document.querySelectorAll('#wtMonthGrid .wt-mo-dot').length;
  out.focusId=document.activeElement?String(document.activeElement.id||document.activeElement.getAttribute('data-ym')||''):'';
  out.focusYm=(document.activeElement&&document.activeElement.getAttribute)?String(document.activeElement.getAttribute('data-ym')||''):'';
  out.preview=String((q('#wtPreview')||{}).textContent||'');
  out.mctlH=(function(){var e=q('.wt-mctl');return e?Math.round(e.getBoundingClientRect().height):0;})();
  out.btnH=(function(){var e=q('#wtMonthBtn');return e?Math.round(e.getBoundingClientRect().height):0;})();
  out.overflow=(function(){var de=document.documentElement;return {sw:de.scrollWidth,cw:de.clientWidth};})();
  return out;
})()
""") or {}


def pop_visible(cdp):
    return W.ev(cdp, "(function(){var p=document.querySelector('#wtMonthPop');return !!p&&!p.hidden;})()") is True


def open_pop(cdp):
    if not pop_visible(cdp):
        W.click(cdp, "#wtMonthBtn")
        W.sleep(0.25)
    return pop_visible(cdp)


def nav_fixture(cdp, rooms, power_sel=None):
    seed = W.ud_blob(power_sel=(W.RV321 if power_sel is None else power_sel), water_rooms=rooms)
    ok = W.nav(cdp, W.purl(ud=seed), clear=True)
    W.wait_ud_baseline(cdp, W.SID_A)
    W.open_water_page(cdp)
    W.sleep(0.5)
    return ok


def recs3():
    return [W.rec(W.M4, 100.0), W.rec(W.M3, 113.74), W.rec(W.M2, 130.0)]


def static_checks():
    src = open(W.SRC, encoding="utf-8").read()
    out = []
    ids = ["wtMonth", "wtMonthBtn", "wtMonthPrev", "wtMonthNext", "wtMonthPop",
           "wtMonthGrid", "wtMonthYPrev", "wtMonthYNext", "wtMonthNow", "wtMonthClose",
           "wtMonthY", "wtMonthM"]
    miss = [i for i in ids if ('id="%s"' % i) not in src]
    out.append(("S01 月份选择 DOM id 齐全（12 个）", not miss, "缺少 " + ",".join(miss)))
    out.append(("S02 真实值仍为 <input type=month id=wtMonth>（保存/预览/测试契约）",
                'type="month" id="wtMonth"' in src, ""))
    out.append(("S03 触发按钮 aria-haspopup=dialog / aria-expanded",
                'aria-haspopup="dialog" aria-expanded="false"' in src and 'id="wtMonthBtn"' in src, ""))
    out.append(("S04 自定义控件 CSS（.wt-mctl/.wt-mpop/.wt-mo.on/.wt-mo-dot）",
                all(k in src for k in (".wt-mctl{", ".wt-mpop{", ".wt-mo.on{", ".wt-mo-dot{")), ""))
    out.append(("S05 月网格/年导航/本月/关闭 逻辑接入 WATER",
                all(k in src for k in ("renderMonthGrid:function", "shiftMonthPopYear:function",
                                       "stepMonth:function", "openMonth:function", "closeMonth:function")), ""))
    out.append(("S06 未引入构建链 / 外部 CDN", ("<script src=" not in src) and ("cdn." not in src), ""))
    return out


def main():
    global RUN_TMP
    W.RUN_TMP = os.path.join(W.TMP, "run_month_%d" % os.getpid())
    RUN_TMP = W.RUN_TMP
    os.makedirs(RUN_TMP, exist_ok=True)
    W.PREVIEW = os.path.join(RUN_TMP, "_month_preview.html")
    W.build_preview()
    os.makedirs(SHOTS, exist_ok=True)

    for name, ok, note in static_checks():
        T(name, ok, note)

    W.HTTP_PORT = W.free_port()
    W.CDP_PORT = W.free_port()
    W.BASE = "http://127.0.0.1:%d/" % W.HTTP_PORT
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", W.HTTP_PORT),
                                           functools.partial(W.QuietHandler, directory=W.ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.35)
    prof = tempfile.mkdtemp(prefix="edgeprof_month_", dir=RUN_TMP)
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

        # ---------- 未选宿舍：禁用 ----------
        nav_fixture(cdp, {}, power_sel="")
        m0 = month_info(cdp)
        T("A01 未选宿舍：隐藏 input 默认当前月", m0.get("value") == W.M0, m0.get("value"))
        T("A02 未选宿舍：#wtMonthBtn / ‹ / › 均禁用",
          m0.get("btnDisabled") is True and m0.get("prevDisabled") is True and m0.get("nextDisabled") is True,
          json.dumps(m0, ensure_ascii=False)[:160])
        opened = open_pop(cdp)
        T("A03 未选宿舍：点击不打开月网格（禁用）", opened is False and m0.get("popHidden") is True,
          str(m0.get("popHidden")))
        W.collect_errors(cdp, "A 禁用")

        # ---------- 3 条记录：控件与弹层 ----------
        nav_fixture(cdp, {W.RV321: {"p": 4, "recs": recs3()}})
        m1 = month_info(cdp)
        T("B01 水量页可打开 / 0 JS 报错", W.jdisplay(cdp, "#s-water") != "none"
          and len(W.ev(cdp, "window.__errs||[]") or []) == 0, "")
        T("B02 默认当前月：标签 = M0 年 / 月",
          m1.get("value") == W.M0 and m1.get("y") == W.M0[:4] and m1.get("m") == W.M0[5:],
          "%s | %s年%s月" % (m1.get("value"), m1.get("y"), m1.get("m")))
        T("B03 隐藏 input 仍为 type=month 且视觉隐藏（opacity=0 / 宽 ≤2px）",
          m1.get("type") == "month" and m1.get("inpOpacity") == "0" and (m1.get("inpW") or 99) <= 2,
          "type=%s opacity=%s w=%s" % (m1.get("type"), m1.get("inpOpacity"), m1.get("inpW")))
        T("B04 控件可点高度 ≥40px（.wt-mctl / #wtMonthBtn）",
          (m1.get("mctlH") or 0) >= 40 and (m1.get("btnH") or 0) >= 40,
          "%s / %s" % (m1.get("mctlH"), m1.get("btnH")))
        T("B05 初始 aria-expanded=false / 弹层隐藏", m1.get("expanded") == "false" and m1.get("popHidden") is True,
          "%s / %s" % (m1.get("expanded"), m1.get("popHidden")))

        # 打开弹层
        ok_open = open_pop(cdp)
        m2 = month_info(cdp)
        T("C01 点按钮打开月网格：可见 + aria-expanded=true", ok_open and m2.get("expanded") == "true",
          "%s / %s" % (ok_open, m2.get("expanded")))
        T("C02 网格 12 个月；选中项 = 当前值；含 .now 当前月",
          m2.get("gridCount") == 12 and m2.get("selYm") == W.M0 and (m2.get("nowCount") or 0) == 1,
          "count=%s sel=%s now=%s" % (m2.get("gridCount"), m2.get("selYm"), m2.get("nowCount")))
        T("C03 面板年份 = 当前值年份", m2.get("popYear") == W.M0[:4] + " 年", m2.get("popYear"))
        T("C04 已有抄表记录的月份显示小圆点（2026 年 3 条）",
          m2.get("dotCount") == len([x for x in (W.M4, W.M3, W.M2) if x[:4] == W.M0[:4]]),
          m2.get("dotCount"))
        T("C05 打开后焦点在选中月按钮上", m2.get("focusYm") == W.M0, m2.get("focusYm"))
        # 截图（captureBeyondViewport 会触发 resize→弹层自动收起，属预期保护；截完重新打开）
        W.shot(cdp, os.path.join(SHOTS, "water_month_430.png"))
        open_pop(cdp)

        # 选择另一个月（M2，已有记录）→ 回写 + 联动 + 关闭
        W.click(cdp, '#wtMonthGrid [data-ym="%s"]' % W.M2)
        W.sleep(0.25)
        m3 = month_info(cdp)
        T("C06 点选月份：隐藏 input 回写 / 标签更新 / 弹层关闭",
          m3.get("value") == W.M2 and m3.get("y") == W.M2[:4] and m3.get("m") == W.M2[5:]
          and m3.get("popHidden") is True and m3.get("expanded") == "false",
          "%s | %s年%s月 | hidden=%s" % (m3.get("value"), m3.get("y"), m3.get("m"), m3.get("popHidden")))
        T("C07 选择后焦点回到触发按钮", m3.get("focusId") == "wtMonthBtn", m3.get("focusId"))

        # 月步进（跨年边界）
        W.set_input(cdp, "#wtMonth", W.M0[:4] + "-01")
        W.click(cdp, "#wtMonthPrev")
        W.sleep(0.2)
        mv = W.jval(cdp, "#wtMonth")
        T("C08 ‹ 上一个月：2026-01 → 2025-12（跨年）", mv == "2025-12", mv)
        W.click(cdp, "#wtMonthNext")
        W.sleep(0.2)
        T("C09 › 下一个月：2025-12 → 2026-01", W.jval(cdp, "#wtMonth") == W.M0[:4] + "-01",
          W.jval(cdp, "#wtMonth"))

        # 年导航 / 本月
        W.click(cdp, "#wtMonthNow")
        W.sleep(0.2)
        open_pop(cdp)
        W.click(cdp, "#wtMonthYPrev")
        W.sleep(0.2)
        m4 = month_info(cdp)
        T("C10 ‹ 上一年：面板年份 -1 且网格同步",
          m4.get("popYear") == str(int(W.M0[:4]) - 1) + " 年"
          and W.jval(cdp, "#wtMonth") == W.M0, "%s / %s" % (m4.get("popYear"), W.jval(cdp, "#wtMonth")))
        W.click(cdp, "#wtMonthYNext")
        W.sleep(0.2)
        T("C11 › 下一年：面板年份恢复", month_info(cdp).get("popYear") == W.M0[:4] + " 年",
          month_info(cdp).get("popYear"))
        W.click(cdp, "#wtMonthNow")
        W.sleep(0.2)
        T("C12 「本月」：回到当前月并关闭弹层",
          W.jval(cdp, "#wtMonth") == W.M0 and month_info(cdp).get("popHidden") is True,
          W.jval(cdp, "#wtMonth"))

        # 点空白 / Esc / 方向键
        open_pop(cdp)
        W.ev(cdp, "(function(){document.body.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));return true;})()")
        W.sleep(0.2)
        T("C13 点空白关闭弹层", month_info(cdp).get("popHidden") is True, "")
        open_pop(cdp)
        W.ev(cdp, "(function(){document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return true;})()")
        W.sleep(0.2)
        m5 = month_info(cdp)
        T("C14 Esc 关闭并回焦触发按钮", m5.get("popHidden") is True and m5.get("focusId") == "wtMonthBtn",
          "hidden=%s focus=%s" % (m5.get("popHidden"), m5.get("focusId")))
        open_pop(cdp)
        sel_m = int(W.M0[5:])
        if sel_m < 12:
            W.ev(cdp, "(function(){document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));return true;})()")
            exp_ym = W.M0[:4] + "-" + ("%02d" % (sel_m + 1))
        else:
            W.ev(cdp, "(function(){document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));return true;})()")
            exp_ym = W.M0[:4] + "-11"
        W.sleep(0.2)
        T("C15 方向键在月份间移动焦点", month_info(cdp).get("focusYm") == exp_ym,
          "%s vs %s" % (month_info(cdp).get("focusYm"), exp_ym))
        W.ev(cdp, "(function(){document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return true;})()")

        # 预览/保存联动
        W.set_input(cdp, "#wtReading", "145")
        W.sleep(0.2)
        open_pop(cdp)
        W.click(cdp, '#wtMonthGrid [data-ym="%s"]' % W.M1)
        W.sleep(0.3)
        T("C16 选择 M1 后预览联动（含「较 M2」）",
          W.M2 in W.jtext(cdp, "#wtPreview") and W.jval(cdp, "#wtMonth") == W.M1,
          W.jtext(cdp, "#wtPreview")[:120])
        W.click(cdp, "#wtSave")
        W.sleep(0.5)
        T("C17 保存使用所选月份：历史出现 M1 行",
          W.ev(cdp, "(function(){return !!document.querySelector('#wtList [data-wm=%s]');})()" % js(W.M1)) is True,
          "")

        # 程序化 set_input 兼容（脚本/测试路径）
        W.set_input(cdp, "#wtMonth", W.M0)
        W.sleep(0.2)
        m6 = month_info(cdp)
        T("C18 程序化 set_input 后标签同步（触发/隐藏值一致）",
          m6.get("y") == W.M0[:4] and m6.get("m") == W.M0[5:], "%s/%s" % (m6.get("y"), m6.get("m")))

        # ---------- 桌面 1280：弹层不出视口 + 截图 ----------
        W.set_viewport(cdp, 1280, 800)
        W.sleep(0.3)
        open_pop(cdp)
        W.sleep(0.2)
        pr = rect(cdp, "#wtMonthPop")
        in_vp = pr.get("x", -1) >= 0 and pr.get("y", -1) >= 0 and pr.get("r", 9999) <= 1280 and pr.get("b", 9999) <= 800
        T("D01 1280×800：弹层完整在视口内", in_vp, json.dumps(pr))
        shot_vp(cdp, os.path.join(SHOTS, "water_month_pop_1280.png"))
        W.ev(cdp, "(function(){document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return true;})()")

        # ---------- 手机 390：弹层不超宽、按钮 ≥40 ----------
        W.set_viewport(cdp, 390, 844)
        W.sleep(0.35)
        open_pop(cdp)
        W.sleep(0.25)
        pr2 = rect(cdp, "#wtMonthPop")
        mr = month_info(cdp)
        mobile_ok = pr2.get("x", -1) >= 0 and pr2.get("r", 9999) <= 390 and pr2.get("w", 0) <= 390 - 8
        T("D02 390×844：弹层不超出视口宽度", mobile_ok, json.dumps(pr2))
        T("D03 390×844：月份按钮可点高度 ≥40px",
          W.ev(cdp, "(function(){var a=document.querySelectorAll('#wtMonthGrid .wt-mo');if(!a.length)return 0;"
                    "var h=99;Array.prototype.forEach.call(a,function(e){h=Math.min(h,e.getBoundingClientRect().height);});return h;})()") >= 40,
          W.ev(cdp, "(function(){var a=document.querySelectorAll('#wtMonthGrid .wt-mo');if(!a.length)return 0;"
                    "var h=99;Array.prototype.forEach.call(a,function(e){h=Math.min(h,e.getBoundingClientRect().height);});return h;})()"))
        T("D04 390×844：无横向溢出",
          (mr.get("overflow") or {}).get("sw", 0) <= (mr.get("overflow") or {}).get("cw", 0) + 1,
          json.dumps(mr.get("overflow")))
        shot_vp(cdp, os.path.join(SHOTS, "water_month_pop_390.png"))

        # ---------- 多宽度：触发控件内容不溢出 ----------
        bad = []
        for vwx, vhx in ((360, 800), (390, 844), (430, 900), (960, 800),
                         (1024, 800), (1280, 800), (1440, 900)):
            W.set_viewport(cdp, vwx, vhx)
            W.sleep(0.3)
            r = W.ev(cdp, r"""
(function(){var b=document.querySelector('#wtMonthBtn');if(!b)return null;
  var br=b.getBoundingClientRect(),out={ok:b.scrollWidth<=b.clientWidth+1,bad:[]};
  Array.prototype.forEach.call(b.children,function(e){var r=e.getBoundingClientRect();
    if(r.width>0&&(r.left<br.left-1||r.right>br.right+1))out.bad.push(String(e.className));});
  return out;})()
""")
            if (not r) or (not r.get("ok")) or (r.get("bad") or []):
                bad.append((vwx, r))
        T("D06 多宽度（360→1440）触发按钮内容零溢出 / 子元素不越界", not bad, str(bad)[:220])

        # ---------- 切页收起弹层 ----------
        W.click(cdp, '#tabsBar button[data-tab="all"]')
        W.sleep(0.4)
        T("D05 切到其他页后弹层自动收起",
          W.ev(cdp, "(function(){var p=document.querySelector('#wtMonthPop');return !!p&&p.hidden;})()") is True,
          "")

        # ---------- 汇总 ----------
        errs = W.ev(cdp, "window.__errs||[]") or []
        cerrs = W.ev(cdp, "window.__cerrs||[]") or []
        exts = W.ev(cdp, W.EXTS_JS) or []
        T("E01 全程 0 JS 报错", len(errs) == 0, " | ".join([str(x) for x in errs[:4]]))
        T("E02 全程 0 console.error", len(cerrs) == 0, " | ".join([str(x) for x in cerrs[:4]]))
        T("E03 全程无外部请求", len(exts) == 0, " | ".join([str(x) for x in exts[:4]]))
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
    print("v2_water_month_check: %d/%d PASS" % (total - len(fails), total))
    return 0 if (total > 0 and not fails) else 1


if __name__ == "__main__":
    sys.exit(main())
