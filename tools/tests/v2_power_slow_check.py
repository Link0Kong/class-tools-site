# -*- coding: utf-8 -*-
"""电费「13/16 号楼网关日更」特异性统计（慢频口径）回归 —— 2026-11-07 规格 power_cadence_spec.md §3

背景：13/16 号楼电表网关日更，24h 数值几乎不变 → 旧口径把 24h 无变化当 0 用电，估算天数虚高（≥30 天）。
新口径（同一份规格 web/mp 共用）：
  - 趋势头固定「日更」短徽标；
  - hero 更新时间 = 最后一个真实变化点（不是同步时间），30 天无变化显示「近 30 天无变化」；
  - 估算可用按 30d 真实更新点统计（单段折算标「参考」）、多段不再标参考、无有效段显示「数据积累中」；
  - 区间无下降 → tile2 副标「该区间无更新」；趋势阶梯线 + 真实变化点小圆点 + 无更新提示；
  - 23A/B 实时房视觉与行为保持现状。
用例：
  A. 慢频房（S1 13-324，单段 11h 内一次下降）：日更 chip / 更新时间=最后变化点 / 7.9 天+参考 / ring 26.3 /
     近 24h 用电 11.3 度 / 阶梯线+1 个变化点圆点 / 无「近 24h 无更新」。
  B. 24h 无更新（S2 16-305）：3.2 天+参考 / tile2「—/该区间无更新」/「近 24h 无更新」/ 平线垂直居中。
  C. 正常房（23A-321）：无日更 chip、无参考、更新时间仍用 updated_at、折线（现状不变）。
  D. 数据不足（23B-424）：无日更 chip / 无参考 / 数据积累中。
  E. 切 7 天/30 天：日更 chip 与参考保持；慢频 30d 已随 pull 拉取，切档不重复请求。
  F. 360/430/1280 宽度下无横向溢出、日更徽标不被裁掉。
  G. 0 JS 报错 / 0 console.error。
用法：cd C:\\...\\web\\tools && python tests\\v2_power_slow_check.py
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
    print("[v2_power_slow_check] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("power_check", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

EDGE = pc.EDGE
HTTP_PORT = 8966
CDP_PORT = 9466
BASE = "http://127.0.0.1:%d/" % HTTP_PORT
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


BOOT_READY = ("(function(){var b=document.querySelector('#tabsBar button.on');"
              "return !!(b&&!document.body.classList.contains('id-locked'));})()")
UPD_RE = re.compile(r"^更新 \d{2}-\d{2} \d{2}:\d{2}$")


def set_metrics(cdp, w, h):
    cdp.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h,
                                                    "deviceScaleFactor": 2, "mobile": True})


def open_power(cdp):
    cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();return !!b;})()")
    time.sleep(0.35)
    ok = cdp.eval("(function(){var b=document.querySelector('#allCards [data-open=\"power\"]');if(b)b.click();return !!b;})()")
    time.sleep(0.8)
    return ok


def pick(cdp, rv):
    return cdp.eval("(function(){var s=document.getElementById('pwSelect');if(!s)return false;"
                    "s.value='%s';s.dispatchEvent(new Event('change',{bubbles:true}));return true;})()" % rv)


def wait_num(cdp, txt):
    return wait_until(cdp, "(function(){var e=document.getElementById('pwNum');return !!(e&&e.textContent.trim()==='%s');})()" % txt, 15)


def set_range(cdp, rng, label):
    cdp.eval("(function(){var b=document.querySelector('#pwRanges [data-range=\"%s\"]');if(b)b.click();return !!b;})()" % rng)
    return wait_until(cdp, "(function(){var t=document.getElementById('pwTrendTitle');return !!t&&t.textContent.indexOf('%s')>=0;})()" % label, 12)


def hist_count(cdp):
    return cdp.eval("(window.__reqs||[]).filter(function(r){return r.url.indexOf('/power_history?')>=0;}).length") or 0


def hist_for(cdp, rv):
    """当前选中房的历史请求数（按 roomverify 过滤，避免累计值干扰）。"""
    return cdp.eval("(window.__reqs||[]).filter(function(r){return r.url.indexOf('/power_history?')>=0&&"
                    "r.url.indexOf('roomverify=eq.%s')>=0;}).length" % rv) or 0


def state(cdp):
    return cdp.eval(r"""(function(){
      function txt(s){var e=document.querySelector(s);return e?String(e.textContent||'').replace(/\s+/g,' ').trim():'';}
      var chip=document.getElementById('pwSlow'),ref=document.querySelector('#pwTiles .pw-ref'),
          note=document.getElementById('pwTrendNote'),tdot=document.querySelector('#pwTrend .pw-tdot'),
          path=document.querySelector('#pwTrend path.pw-trend-line'),
          sec=document.getElementById('s-power');
      return {num:txt('#pwNum'),days:txt('#pwDays'),upd:txt('#pwUpd'),
        chipHidden:chip?!!chip.hidden:true,chipText:chip?String(chip.textContent||'').trim():'',
        chipTitle:chip?String(chip.title||''):'',
        cadence:sec?String(sec.getAttribute('data-cadence')||''):'',
        tile1:txt('#pwTiles .pw-tile.hl'),tile2:txt('#pwUseTile'),
        refText:ref?String(ref.textContent||'').trim():'',
        ring:(document.getElementById('pwRingFg')||{}).getAttribute?document.getElementById('pwRingFg').getAttribute('stroke-dasharray'):'',
        noteHidden:note?!!note.hidden:true,noteText:note?String(note.textContent||'').trim():'',
        tdotTop:tdot?String(tdot.style.top||''):'',cdotN:document.querySelectorAll('#pwTrend .pw-cdot').length,
        pathD:path?String(path.getAttribute('d')||''):'',
        hist:((window.__reqs||[]).filter(function(r){return r.url.indexOf('/power_history?')>=0;})).length};
    })()""")


def parse_upd(txt):
    """解析「更新 MM-DD HH:MM」→ epoch ms（按当前年份；跨年回退一年）。非法返回 None。"""
    m = re.match(r"^更新 (\d{2})-(\d{2}) (\d{2}):(\d{2})$", txt or "")
    if not m:
        return None
    now = time.localtime()
    try:
        ts = time.mktime((now.tm_year, int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), 0, 0, 0, -1)) * 1000.0
    except Exception:
        return None
    if ts - time.time() * 1000 > 180 * 86400e3:
        try:
            ts = time.mktime((now.tm_year - 1, int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), 0, 0, 0, -1)) * 1000.0
        except Exception:
            return None
    return ts


def fmt_change(ms):
    d = time.localtime(ms / 1000.0)
    return "%02d-%02d %02d:%02d" % (d.tm_mon, d.tm_mday, d.tm_hour, d.tm_min)


def set_fixtures():
    """S1/S2（规格 §5）覆盖 power_check 默认 13-324 / 16-305 采样；其余房保留原 fixture。"""
    pc.ROWS["1-13---324"] = {"quantity": 88.75, "low": False}
    pc.HIST["1-13---324"] = [(11.2, 100.00), (0.2, 88.75)]
    pc.ROWS["1-16---305"] = {"quantity": 38.00, "low": False}
    pc.HIST["1-16---305"] = [(30.1, 50.00), (6.1, 38.00), (0.2, 38.00)]


def run(cdp):
    set_metrics(cdp, 390, 844)
    cdp.send("Page.navigate", {"url": BASE + "tests/" + PV})
    if not wait_until(cdp, BOOT_READY, 30):
        T("A0 启动完成", False, "timeout")
        return
    time.sleep(1.2)
    T("A0 启动完成", True, "")
    if not open_power(cdp):
        T("A0b 电费页打开", False, "no power card")
        return
    T("A0b 电费页打开", True, "")

    # A. 慢频房 S1：13-324（11.2h 前 100.00 → 0.2h 前 88.75，单段 11h）
    pick(cdp, "1-13---324")
    okA = wait_num(cdp, "88.8")
    time.sleep(0.9)
    set_range(cdp, "24h", "24h")   # 13/16 用户界面已隐藏 24h；测试显式切 24h 验证内部口径
    time.sleep(0.4)
    a = state(cdp)
    T("A1 S1 慢频房显示「日更」徽标", okA and (not a["chipHidden"]) and a["chipText"] == "日更", json.dumps(a["chipText"], ensure_ascii=False))
    T("A2 日更徽标 title 说明按真实更新点统计", a["chipTitle"] == "13/16 号楼网关日更，按真实更新点统计", a["chipTitle"])
    T("A3 S1 标记 data-cadence=slow", a["cadence"] == "slow", a["cadence"])
    up_ok = bool(UPD_RE.match(a["upd"]))
    up_ts = parse_upd(a["upd"])
    last_ok = up_ts is not None and abs(up_ts - (time.time() * 1000 - 0.2 * 3600e3)) < 15 * 60e3
    T("A4 更新时间=最后真实变化点（约 12 分钟前），不是同步时间", up_ok and last_ok and a["upd"] != "更新 11-06 06:42",
      json.dumps({"upd": a["upd"], "expect": fmt_change(time.time() * 1000 - 0.2 * 3600e3)}, ensure_ascii=False))
    T("A5 估算修复：7.9 天 + 「参考」", ("7.9" in a["tile1"]) and a["refText"] == "参考" and ("数据积累中" not in a["days"]),
      json.dumps({"tile1": a["tile1"], "ref": a["refText"], "days": a["days"]}, ensure_ascii=False))
    T("A6 估算速率 ≈ 11.3 度/天（单段按 24h 预期周期折算）", "11.3" in a["tile1"], a["tile1"])
    T("A7 环刻度 = 可用天数/30（26.3）", a["ring"].startswith("26.3"), a["ring"])
    T("A8 环内小字 ≈ 7.9 天", "7.9" in a["days"], a["days"])
    T("A9 近 24h 用电 11.3 度", "11.3" in a["tile2"], a["tile2"])
    T("A10 慢频趋势为阶梯线（H/V）+ 1 个真实变化点圆点", ("H" in a["pathD"] and "V" in a["pathD"]) and a["cdotN"] == 1,
      json.dumps({"pathD": a["pathD"][:120], "cdots": a["cdotN"]}, ensure_ascii=False))
    T("A11 24h 内有更新：不显示「近 24h 无更新」", a["noteHidden"], a["noteText"])

    # B. 24h 无更新 S2：16-305（30.1h 前 50.00 → 6.1h 前 38.00，之后持平）
    pick(cdp, "1-16---305")
    okB = wait_num(cdp, "38.0")
    time.sleep(0.9)
    set_range(cdp, "24h", "24h")
    time.sleep(0.4)
    b = state(cdp)
    T("B1 S2 显示「日更」徽标", okB and (not b["chipHidden"]) and b["chipText"] == "日更", b["chipText"])
    T("B2 S2 估算 3.2 天 + 参考（12.0 度/天）", ("3.2" in b["tile1"]) and ("12.0" in b["tile1"]) and b["refText"] == "参考", b["tile1"])
    T("B3 S2 环刻度 10.6", b["ring"].startswith("10.5") or b["ring"].startswith("10.6"), b["ring"])
    T("B4 24h 无下降：tile2「—/该区间无更新」", "—" in b["tile2"] and "该区间无更新" in b["tile2"], b["tile2"])
    T("B5 24h 无更新提示「近 24h 无更新」", (not b["noteHidden"]) and b["noteText"] == "近 24h 无更新", b["noteText"])
    try:
        top = float(str(b["tdotTop"]).replace("%", ""))
    except Exception:
        top = -1
    T("B6 平线垂直居中（末点 top≈50%）", 49 <= top <= 51, b["tdotTop"])
    upB = parse_upd(b["upd"])
    T("B7 S2 更新时间=最后真实变化点（约 6.1h 前）",
      upB is not None and abs(upB - (time.time() * 1000 - 6.1 * 3600e3)) < 20 * 60e3,
      json.dumps({"upd": b["upd"], "expect": fmt_change(time.time() * 1000 - 6.1 * 3600e3)}, ensure_ascii=False))

    # C. 正常房：23A-321（现状不变）
    pick(cdp, "4-23A---321")
    okC = wait_num(cdp, "382")
    time.sleep(0.9)
    c = state(cdp)
    T("C1 23A 正常房不显示日更徽标", okC and c["chipHidden"], json.dumps({"hidden": c["chipHidden"], "text": c["chipText"]}, ensure_ascii=False))
    T("C2 23A 标记 data-cadence=live", c["cadence"] == "live", c["cadence"])
    T("C3 23A 估算仍 ≥30 天、不显示「参考」", "≥30" in c["days"] and c["refText"] == "", json.dumps({"days": c["days"], "ref": c["refText"]}, ensure_ascii=False))
    T("C4 23A 更新时间仍用 updated_at（现状）", c["upd"] == "更新 11-06 06:42", c["upd"])
    T("C5 23A 趋势仍为折线（无阶梯 H/V）、无变化点圆点", "L" in c["pathD"] and "H" not in c["pathD"] and c["cdotN"] == 0,
      json.dumps({"pathD": c["pathD"][:100], "cdots": c["cdotN"]}, ensure_ascii=False))

    # D. 数据不足：23B-424（仅 1 点）
    pick(cdp, "4-23B---424")
    okD = wait_num(cdp, "18.5")
    time.sleep(0.7)
    d = state(cdp)
    T("D1 数据不足房不显示日更徽标", okD and d["chipHidden"], d["chipText"])
    T("D2 数据不足房估算「数据积累中」、无参考", "数据积累中" in d["days"] and d["refText"] == "", json.dumps({"days": d["days"], "ref": d["refText"]}, ensure_ascii=False))

    # E. 区间切换：慢频日更徽标/参考保持；30d 已随 pull 拉取，切档不重复请求
    before_e = hist_for(cdp, "1-16---305")
    pick(cdp, "1-16---305")
    wait_num(cdp, "38.0")
    time.sleep(0.8)
    base_hist = hist_for(cdp, "1-16---305")
    T("E1 重新选择慢频房 → 3 个 history 窗口（24h/7d/30d）", base_hist - before_e == 3,
      "%s->%s (cum=%s)" % (before_e, base_hist, hist_count(cdp)))
    for rng, label in (("7d", "7 天"), ("30d", "30 天")):
        cdp.eval("(function(){var b=document.querySelector('#pwRanges [data-range=\"%s\"]');if(b)b.click();return !!b;})()" % rng)
        wait_until(cdp, "(function(){var t=document.getElementById('pwTrendTitle');return !!t&&t.textContent.indexOf('%s')>=0;})()" % label, 12)
        time.sleep(0.5)
        e = state(cdp)
        T("E2 切 %s：日更徽标仍显示" % label, (not e["chipHidden"]) and e["chipText"] == "日更", e["chipText"])
        T("E3 切 %s：估算参考仍为 3.2 天/参考" % label, "3.2" in e["tile1"] and e["refText"] == "参考", e["tile1"])
        T("E4 切 %s：7d/30d 命中缓存%s" % (label, "，仅补拉 70 天比较窗口" if rng == "30d" else ""),
          hist_for(cdp, "1-16---305") == base_hist + (1 if rng == "30d" else 0),
          "%s->%s" % (base_hist, hist_for(cdp, "1-16---305")))
    cdp.eval("(function(){var b=document.querySelector('#pwRanges [data-range=\"24h\"]');if(b)b.click();return !!b;})()")
    time.sleep(0.5)

    # F. 宽度不溢出（日更徽标显示状态）
    pick(cdp, "1-13---324")
    wait_num(cdp, "88.8")
    time.sleep(0.5)
    for w, h in ((360, 800), (430, 900), (1280, 900)):
        set_metrics(cdp, w, h)
        time.sleep(0.7)
        cdp.eval("window.scrollTo(0,0)")
        time.sleep(0.2)
        ov = cdp.eval("(function(){var d=document.documentElement;return {vw:innerWidth,sw:Math.max(d.scrollWidth,document.body.scrollWidth)};})()")
        T("F1 %d 宽：无横向溢出" % w, ov["sw"] <= ov["vw"] + 1, json.dumps(ov))
        s = state(cdp)
        T("F2 %d 宽：日更徽标可见且未被挤出" % w, (not s["chipHidden"]) and s["chipText"] == "日更", s["chipText"])
        T("F3 %d 宽：估算 tile 不溢出（参考徽标可见）" % w, s["refText"] == "参考", s["refText"])
    set_metrics(cdp, 390, 844)
    time.sleep(0.5)

    errs = cdp.eval("JSON.stringify(window.__errs||[])")
    cerrs = cdp.eval("JSON.stringify(window.__cerrs||[])")
    T("G1 0 JS 报错", errs == "[]", errs[:300])
    T("G2 0 console.error", cerrs == "[]", cerrs[:300])


def main():
    set_fixtures()
    pc.build_previews()
    devnull = open(os.devnull, "wb")
    prof = tempfile.mkdtemp(prefix="edgeprof_slow_")
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
        for fn in (PV, pc.COMMON):
            try:
                os.remove(os.path.join(HERE, fn))
            except Exception:
                pass
        shutil.rmtree(pc.REPORT_DIR, ignore_errors=True)
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 60)
    print("v2_power_slow_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
