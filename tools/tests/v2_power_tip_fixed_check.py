# -*- coding: utf-8 -*-
"""电费趋势信息气泡「固定右上角」专项检查（2026-11-07 23:20，用户要求：气泡不放在图内，固定显示在趋势图右上角上部）

要求：气泡不浮在绘图区/曲线内，固定显示在趋势图右上角上部（区间行右侧、绘图区外），随选中点只更新文字。
覆盖：
  - 静态：DOM 在 .pw-trend-top（不在 #pwDetail 内）、CSS 非 absolute/无 transform、区间行 flex 布局、touch-action 恢复 pan-y；
  - 初始/取消/空态：未选中/取消后气泡 hidden；空态不出现；
  - 点击选中：气泡可见、文案格式正确、竖线/圆点有位置；
  - 固定位置：气泡在绘图区上方（tip.b <= plot.t）、与区间按钮不重叠、右对齐卡片内容右缘；
  - 不随拖动移动：同一 x 上下拖 / 左右拖，气泡 rect 不变（只文字变化）；
  - 360/390/1280：气泡在卡片内、不溢出、窄屏折行不遮挡区间按钮；
  - 0 JS 报错。
用法：cd web/tools && python tests\\v2_power_tip_fixed_check.py
"""
import importlib.util
import json
import os
import re
import sys
import threading
import http.server
import socketserver
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

spec = importlib.util.spec_from_file_location("pc", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

SHOTS = os.path.join(HERE, "_shots_power_tip")
RESULTS = []
PORT = 8969


def T(name, ok, note=""):
    RESULTS.append({"k": name, "ok": bool(ok)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(d, p):
    h = lambda *a, **kw: Q(*a, directory=d, **kw)
    s = socketserver.ThreadingTCPServer(("127.0.0.1", p), h)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def mouse(p, typ, x, y):
    p.send("Input.dispatchMouseEvent", {"type": typ, "x": x, "y": y, "button": "left", "clickCount": 1})


def click(p, x, y):
    mouse(p, "mousePressed", x, y)
    mouse(p, "mouseReleased", x, y)
    time.sleep(0.12)


def probe(p):
    return p.evaluate("""(function(){
      function R(sel){var e=document.querySelector(sel);if(!e)return null;var r=e.getBoundingClientRect();return {l:+r.left.toFixed(1),t:+r.top.toFixed(1),r:+r.right.toFixed(1),b:+r.bottom.toFixed(1),w:+r.width.toFixed(1),h:+r.height.toFixed(1)};}
      var tip=document.querySelector('#pwDetailTip');
      return {on:document.querySelector('#pwDetail').classList.contains('on'),
              hidden:tip?!!tip.hidden:true,
              text:tip?String(tip.textContent||''):'',
              tip:R('#pwDetailTip'), plot:R('#pwTrendScroll'), card:R('#pwTrendCard'),
              ranges:R('#pwRanges'), top:R('.pw-trend-top'), dot:R('#pwDetailDot'), line:R('#pwDetailLine')};
    })()""")


def wait_chart_stable(p, timeout=20):
    t0 = time.time()
    last = None
    stable = 0
    while time.time() - t0 < timeout:
        d = p.evaluate("(function(){var p=document.querySelector('#pwTrend svg path.pw-trend-line');return p?p.getAttribute('d'):null;})()")
        if d and d == last:
            stable += 1
            if stable >= 3:
                return True
        else:
            stable = 0
        last = d
        time.sleep(0.2)
    return False


def static_checks():
    src = open(pc.SRC, encoding="utf-8").read()
    m = re.search(r'<div class="pw-detail" id="pwDetail"[\s\S]*?</div>', src)
    T("C1 气泡 DOM 已移出 #pwDetail（固定在 .pw-trend-top 内）",
      bool(m) and "pwDetailTip" not in m.group(0)
      and '<div class="pw-trend-top">' in src
      and re.search(r'<div class="pw-trend-top">[\s\S]*?id="pwDetailTip"[\s\S]*?</div>\s*<div class="pw-trend-wrap"', src) is not None,
      "")
    T("C2 气泡 CSS 不再绝对定位/不做位移，hidden 隐藏",
      ".pw-detail-tip{margin-left:auto" in src
      and ".pw-detail-tip[hidden]{display:none}" in src
      and ".pw-detail-tip{position:absolute" not in src
      and ".pw-detail-tip.below" not in src, "")
    T("C3 区间行 flex 布局 + 绘图区 touch-action 恢复 pan-y",
      ".pw-trend-top{display:flex" in src
      and re.search(r"\.pw-trend-scroll\{[^}]*touch-action:pan-y", src) is not None, "")
    T("C4 JS：无跟手定位残留（placeTip/_ptr/detailFromPoint），保留 detailFromClientX + tip.hidden 开关",
      "placeTip" not in src and "_ptr" not in src and "detailFromPoint" not in src
      and "detailFromClientX:function" in src and "tip.hidden=false" in src and "tip.hidden=true" in src, "")


def run(p, shots):
    url = "http://127.0.0.1:%d/" % PORT
    ud = urllib.parse.quote(json.dumps(pc.ud_blob("4-23A---321"), ensure_ascii=False), safe="")
    p.set_device(390, 900, dpr=2.0, mobile=True, touch=True)
    p.navigate(url + pc.PREVIEW + "?sid=" + pc.SID_A + "&name=%E6%B5%8B%E8%AF%95%E5%90%8C%E5%AD%A6&ud=" + ud)
    p.wait_load(30)
    T("A0 预览页启动", p.wait_for("!!document.querySelector('#idChipTxt')", 20), "")
    p.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();'x'")
    time.sleep(0.45)
    p.evaluate("var b=document.querySelector('#allCards [data-open=\"power\"]');if(b)b.click();'x'")
    T("A1 电费页打开", p.wait_for("!!document.querySelector('#s-power')&&document.querySelector('#s-power').classList.contains('on')", 15), "")
    T("A2 趋势图渲染", p.wait_for("!!document.querySelector('#pwTrend svg path.pw-trend-line')", 25), "")
    T("A3 趋势图数据稳定", wait_chart_stable(p), "")
    time.sleep(0.2)
    st0 = probe(p)
    T("A4 未选中：气泡隐藏", st0["hidden"] and not st0["on"], json.dumps({"hidden": st0["hidden"]}, ensure_ascii=False))

    sc = st0["plot"]
    def pt(fx, fy):
        return sc["l"] + sc["w"] * fx, sc["t"] + sc["h"] * fy

    # 点击中部选中
    x, y = pt(0.5, 0.5)
    click(p, x, y)
    st = probe(p)
    T("A5 点击后气泡可见、文案格式正确", st["on"] and not st["hidden"]
      and bool(re.match(r"^\d{2}:\d{2} · 电量 [\d.]+ 度$", st["text"])), json.dumps(st, ensure_ascii=False)[:280])
    T("A6 竖线/圆点在绘图区内（仍对准采样点）",
      bool(st["dot"]) and bool(st["line"]) and st["plot"]["l"] - 1 <= st["dot"]["l"] <= st["plot"]["r"] + 1,
      json.dumps({"dot": st["dot"]}, ensure_ascii=False))
    curve = p.evaluate("""(function(){
      var ch=window.__POWER_CHART&&window.__POWER_CHART(),svg=document.querySelector('#pwTrend svg'),path=svg&&svg.querySelector('path.pw-trend-line');
      if(!ch||!path)return null;
      var d=path.getAttribute('d')||'',nums=(d.match(/-?\d+(?:\.\d+)?/g)||[]).map(Number);
      var ends=[[nums[0],nums[1]]],i,maxd=0;
      for(i=2;i+5<nums.length;i+=6){ends.push([nums[i+4],nums[i+5]]);}
      for(i=0;i<Math.min(ends.length,ch.coords.length);i++){
        maxd=Math.max(maxd,Math.abs(ends[i][0]-ch.coords[i][0]),Math.abs(ends[i][1]-ch.coords[i][1]));
      }
      var dot=document.querySelector('#pwDetailDot'),dr=dot.getBoundingClientRect(),sr=svg.getBoundingClientRect();
      var c=ch.coords[ch.detail]||ch.coords[0];
      var ex=sr.left+c[0]/ch.W*sr.width,ey=sr.top+c[1]/ch.H*sr.height;
      var dx=Math.abs((dr.left+dr.right)/2-ex),dy=Math.abs((dr.top+dr.bottom)/2-ey);
      var pr=document.querySelector('#pwDetail').getBoundingClientRect(),tr=document.querySelector('#pwTrend').getBoundingClientRect();
      return {n:ch.coords.length,ends:ends.length,maxd:+maxd.toFixed(3),dx:+dx.toFixed(2),dy:+dy.toFixed(2),
              detailW:+pr.width.toFixed(1),plotW:+tr.width.toFixed(1)};
    })()""")
    T("A6b 平滑曲线穿过每个真实采样点（C 段终点=采样坐标）", curve and curve["ends"] == curve["n"] and curve["maxd"] <= 0.25, json.dumps(curve, ensure_ascii=False))
    T("A6c 游标圆点与曲线同坐标（百分比定位，缩放不漂移）", curve and curve["dx"] <= 1.2 and curve["dy"] <= 1.2, json.dumps(curve, ensure_ascii=False))
    T("A6d 详情层与绘图区同宽（圆点 x 与曲线同源）", curve and abs(curve["detailW"] - curve["plotW"]) <= 1.5, json.dumps(curve, ensure_ascii=False))
    T("A7 固定位置：气泡在绘图区上方（不放在图内）", st["tip"]["b"] <= st["plot"]["t"] + 0.5,
      "tip.b=%s plot.t=%s" % (st["tip"]["b"], st["plot"]["t"]))
    T("A8 右对齐卡片内容右缘（趋势图右上角）", abs(st["tip"]["r"] - (st["card"]["r"] - 16)) <= 2.5,
      "tip.r=%s card.r-16=%s" % (st["tip"]["r"], st["card"]["r"] - 16))
    T("A9 与区间按钮不重叠（同一行右侧）", st["tip"]["l"] >= st["ranges"]["r"] - 0.5,
      "tip.l=%s ranges.r=%s" % (st["tip"]["l"], st["ranges"]["r"]))
    p.screenshot(os.path.join(shots, "fixed_390.png"))

    # 上下拖（同一 x）：气泡位置不变、文案不变
    y2 = sc["t"] + sc["h"] * 0.85
    mouse(p, "mousePressed", x, y)
    mouse(p, "mouseMoved", x, y2)
    time.sleep(0.15)
    st_v = probe(p)
    same_rect = (abs(st_v["tip"]["l"] - st["tip"]["l"]) <= 0.6 and abs(st_v["tip"]["t"] - st["tip"]["t"]) <= 0.6
                 and abs(st_v["tip"]["w"] - st["tip"]["w"]) <= 0.6)
    T("A10 竖直拖动：气泡位置固定不动（只有竖线/圆点/文字随命中点）", same_rect and st_v["text"] == st["text"],
      json.dumps({"before": st["tip"], "after": st_v["tip"]}, ensure_ascii=False))
    mouse(p, "mouseReleased", x, y2)

    # 左右拖：气泡位置不变、文案变化
    mouse(p, "mousePressed", sc["l"] + sc["w"] * 0.15, sc["t"] + sc["h"] * 0.6)
    texts = []
    rects = []
    for f in (0.15, 0.45, 0.8):
        mouse(p, "mouseMoved", sc["l"] + sc["w"] * f, sc["t"] + sc["h"] * 0.6)
        time.sleep(0.12)
        s2 = probe(p)
        texts.append(s2["text"])
        rects.append((s2["tip"]["l"], s2["tip"]["t"], s2["tip"]["w"]))
    mouse(p, "mouseReleased", sc["l"] + sc["w"] * 0.8, sc["t"] + sc["h"] * 0.6)
    fixed_rects = all(abs(r[0] - rects[0][0]) <= 0.6 and abs(r[1] - rects[0][1]) <= 0.6 and abs(r[2] - rects[0][2]) <= 0.6 for r in rects)
    T("A11 左右拖动：气泡位置固定不动、只更新文案（≥2 个不同点）", fixed_rects and len(set(texts)) >= 2,
      json.dumps({"texts": texts, "rects": rects}, ensure_ascii=False))

    # 点标题取消 → 气泡隐藏
    p.evaluate("(function(){var t=document.getElementById('pwTrendTitle');if(t)t.click();return true;})()")
    time.sleep(0.1)
    st_c = probe(p)
    T("A12 点标题取消：气泡隐藏", st_c["hidden"] and not st_c["on"], json.dumps({"hidden": st_c["hidden"]}, ensure_ascii=False))

    # 多宽度：360（窄屏折行不遮挡按钮）/1280
    for w, h, shot in ((360, 780, "fixed_360.png"), (1280, 900, "fixed_1280.png")):
        p.set_device(w, h, dpr=2.0 if w < 700 else 1.0, mobile=w < 700, touch=True)
        time.sleep(0.9)
        sc2 = probe(p)["plot"]
        click(p, sc2["l"] + sc2["w"] * 0.55, sc2["t"] + sc2["h"] * 0.5)
        time.sleep(0.12)
        s3 = probe(p)
        inside = (s3["tip"] and s3["tip"]["l"] >= s3["card"]["l"] - 1 and s3["tip"]["r"] <= s3["card"]["r"] + 1
                  and s3["tip"]["t"] >= s3["card"]["t"] - 1 and s3["tip"]["b"] <= s3["card"]["b"] + 1)
        above = s3["tip"]["b"] <= s3["plot"]["t"] + 0.5
        no_overlap = s3["tip"]["l"] >= s3["ranges"]["r"] - 0.5
        no_overflow = p.evaluate("(function(){var d=document.documentElement;return d.scrollWidth<=d.clientWidth+1;})()")
        T("A13 %d 宽：气泡在卡片内、绘图区上方、不压按钮、无横向溢出" % w,
          s3["on"] and not s3["hidden"] and inside and above and no_overlap and no_overflow,
          json.dumps({"tip": s3["tip"], "ranges": s3["ranges"], "card": s3["card"], "above": above}, ensure_ascii=False)[:400])
        p.screenshot(os.path.join(shots, shot))

    # 空态（<2 采样）：不显示气泡
    p.set_device(390, 900, dpr=2.0, mobile=True, touch=True)
    time.sleep(0.6)
    p.evaluate("(function(){var s=document.getElementById('pwSelect');s.value='4-23B---424';s.dispatchEvent(new Event('change',{bubbles:true}));return true;})()")
    time.sleep(1.0)
    st_e = probe(p)
    T("A14 空态（数据不足）：气泡不显示", st_e["hidden"] and not st_e["on"], json.dumps({"hidden": st_e["hidden"]}, ensure_ascii=False))

    errs = p.evaluate("JSON.stringify(window.__errs||[])")
    T("A15 0 JS 报错", errs == "[]", errs[:300])


def main():
    os.makedirs(SHOTS, exist_ok=True)
    for f in os.listdir(SHOTS):
        try:
            os.remove(os.path.join(SHOTS, f))
        except Exception:
            pass
    static_checks()
    pc.build_previews()
    srv = serve(HERE, PORT)
    b = None
    try:
        b = _cdp.Browser(window=(430, 900))
        p = b.new_page("about:blank")
        try:
            run(p, SHOTS)
        finally:
            p.close()
    finally:
        if b:
            b.close()
        srv.shutdown()
        for fn in (pc.PREVIEW, pc.COMMON):
            try:
                os.remove(os.path.join(HERE, fn))
            except Exception:
                pass
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 60)
    print("v2_power_tip_fixed_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("截图目录:", SHOTS)
    print("=" * 60)
    return 0 if total and passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
