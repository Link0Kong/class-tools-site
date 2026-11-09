# -*- coding: utf-8 -*-
"""电费「13/16 号楼网关日更」特异性统计验收（规格 tools/tests/power_cadence_spec.md §5/§6）

网页侧实现验收：
  - S1-S5 / L1 / L2 fixture 期望值（按规格 §1 公式：11.25→11.3、5.481→5.5 等 JS toFixed 语义）；
  - 取数契约：慢频房 pull 恰好 3 个 power_history（24h/7d/30d，gte 递增 / order=ts.asc / limit=2000），
    实时房 2 个（切 30d 时 3 个）；
  - 区间切换：慢频 7d/30d 图仍按真实时间压缩铺满、x 轴 3–5 刻度、无横滑、30d 已缓存不重复请求；
  - 数据覆盖（防未来网关提速）：13 号楼某房 24h changes≥6 → 不显示「日更」，走实时口径、只拉 2 窗口；
  - 无更新提示（近 24h/7 天/30 天）、「近 30 天无变化」、平线垂直居中；
  - 360/430/1280 无横向溢出 / 0 JS 报错 / 0 console.error / 0 外部请求；
  - 截图 tests/_shots_power_cadence/。
用法：cd C:\\...\\web\\tools && python tests\\v2_power_cadence_check.py
"""
import base64
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
    print("[v2_power_cadence_check] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("power_check", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

EDGE = pc.EDGE
HTTP_PORT = 8970
CDP_PORT = 9470
BASE = "http://127.0.0.1:%d/" % HTTP_PORT
PV = pc.PREVIEW
SHOTS = os.path.join(HERE, "_shots_power_cadence")
RESULTS = []
BASE_ROWS = dict(pc.ROWS)
BASE_HIST = dict(pc.HIST)


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
    cdp.eval("(function(){var s=document.getElementById('pwSelect');if(!s)return false;"
             "s.value='%s';s.dispatchEvent(new Event('change',{bubbles:true}));return true;})()" % rv)
    return wait_until(cdp, "(function(){var e=document.getElementById('pwNum');return !!e&&e.textContent.trim()!==''&&e.textContent.trim()!=='—';})()", 15)


def set_range(cdp, rng, label):
    cdp.eval("(function(){var b=document.querySelector('#pwRanges [data-range=\"%s\"]');if(b)b.click();return !!b;})()" % rng)
    return wait_until(cdp, "(function(){var t=document.getElementById('pwTrendTitle');return !!t&&t.textContent.indexOf('%s')>=0;})()" % label, 12)


def hist_reqs(cdp):
    return cdp.eval(r"""(function(){
      return (window.__reqs||[]).filter(function(r){return r.url.indexOf('/power_history?')>=0;}).map(function(r){
        var g=r.url.match(/ts=gte\.([^&]+)/);
        return {url:r.url, gte:g?Date.parse(decodeURIComponent(g[1])):0};
      });
    })()""") or []


def hist_for(cdp, rv):
    """当前选中房的历史请求数（按 roomverify 过滤，避免累计值干扰）。"""
    return cdp.eval("(window.__reqs||[]).filter(function(r){return r.url.indexOf('/power_history?')>=0&&"
                    "r.url.indexOf('roomverify=eq.%s')>=0;}).length" % rv) or 0


def state(cdp):
    return cdp.eval(r"""(function(){
      function txt(s){var e=document.querySelector(s);return e?String(e.textContent||'').replace(/\s+/g,' ').trim():'';}
      function tl(i){var a=document.querySelectorAll('#pwTiles .pw-tile');return a[i]?String(a[i].textContent||'').replace(/\s+/g,' ').trim():'';}
      var chip=document.getElementById('pwSlow'),ref=document.querySelector('#pwTiles .pw-ref'),
          note=document.getElementById('pwTrendNote'),tdot=document.querySelector('#pwTrend .pw-tdot'),
          path=document.querySelector('#pwTrend path.pw-trend-line'),
          sec=document.getElementById('s-power'),lab=document.querySelectorAll('#pwXAxis .pw-xlab');
      var xl=[].slice.call(lab).map(function(e){return String(e.textContent||'');});
      return {num:txt('#pwNum'),days:txt('#pwDays'),upd:txt('#pwUpd'),
        chipHidden:chip?!!chip.hidden:true,chipText:chip?String(chip.textContent||'').trim():'',
        chipTitle:chip?String(chip.title||''):'',
        cadence:sec?String(sec.getAttribute('data-cadence')||''):'',
        tile1:tl(0),tile2:tl(1),tile4:tl(3),
        refText:ref?String(ref.textContent||'').trim():'',
        ring:(document.getElementById('pwRingFg')||{}).getAttribute?document.getElementById('pwRingFg').getAttribute('stroke-dasharray'):'',
        noteHidden:note?!!note.hidden:true,noteText:note?String(note.textContent||'').trim():'',
        notePE:note?getComputedStyle(note).pointerEvents:'',
        tdotTop:tdot?String(tdot.style.top||''):'',cdotN:document.querySelectorAll('#pwTrend .pw-cdot').length,
        pathD:path?String(path.getAttribute('d')||''):'',
        legend:txt('#pwLegend'),
        xl:xl,
        scrollSW:(function(){var s=document.getElementById('pwTrendScroll');return s?s.scrollWidth:0;})(),
        scrollCW:(function(){var s=document.getElementById('pwTrendScroll');return s?s.clientWidth:0;})(),
        scrollOX:(function(){var s=document.getElementById('pwTrendScroll');return s?getComputedStyle(s).overflowX:'';})(),
        active:(function(){var s=document.querySelector('section.on');return s?s.id:'';})(),
        hist:((window.__reqs||[]).filter(function(r){return r.url.indexOf('/power_history?')>=0;})).length,
        extern:((function(){var out=[];try{(performance.getEntriesByType('resource')||[]).forEach(function(e){
          var u=String(e.name||'');if(!/^https?:\/\/127\.0\.0\.1[:/]/.test(u)&&!/^data:/.test(u)&&!/^blob:/.test(u))out.push(u);});}catch(e){}return out;})())};
    })()""")


def fmt_ts(ms):
    d = time.localtime(ms / 1000.0)
    return "%02d-%02d %02d:%02d" % (d.tm_mon, d.tm_mday, d.tm_hour, d.tm_min)


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


def shot(cdp, name):
    try:
        os.makedirs(SHOTS, exist_ok=True)
        data = cdp.send("Page.captureScreenshot", {"format": "png"})
        p = os.path.join(SHOTS, name)
        open(p, "wb").write(base64.b64decode(data["data"]))
        return os.path.getsize(p) > 8000
    except Exception as e:
        print("[shot fail]", name, str(e)[:160])
        return False


def apply_fixtures(rows, hist, phase):
    pc.ROWS = dict(BASE_ROWS)
    pc.HIST = dict(BASE_HIST)
    pc.ROWS.update(rows)
    pc.HIST.update(hist)
    pc.build_previews()
    if phase:
        # 让静态服务器返回新内容（避免 Edge 用上一阶段缓存）
        src = open(os.path.join(HERE, PV), encoding="utf-8").read()
        src = src.replace("</head>", "<!--phase %s--></head>" % phase, 1) if False else src
    return phase


def boot(cdp, phase):
    # 清 localStorage + sessionStorage：避免上一阶段「刷新恢复 tab」(zq_pos_v1) 让页面直接落在
    # 电费页（此时工具栏里可能没有对应 tab，`#tabsBar button.on` 为空）导致启动判定误判。
    cdp.eval("(function(){try{localStorage.clear();}catch(e){}try{sessionStorage.clear();}catch(e){}})()")
    cdp.send("Page.navigate", {"url": BASE + "tests/" + PV + "?ph=" + str(phase)})
    # 注意：Page.navigate 立即返回时旧页面仍可求值 → 必须等 URL 已切到新页面再做 BOOT_READY
    # 允许「刷新恢复 tab」把页面直接落在电费页（此时工具栏可能没有对应 tab）
    ok = wait_until(cdp, "(function(){var b=document.querySelector('#tabsBar button.on');"
                    "var s=document.querySelector('section.on');var pw=!!s&&s.id==='s-power';"
                    "return String(location.search||'').indexOf('ph=%d')>=0&&"
                    "!document.body.classList.contains('id-locked')&&(!!b||pw);})()"
                    % phase, 30)
    if not ok:
        try:
            print("[boot diag]", cdp.eval("(function(){return {url:String(location.href),rs:document.readyState,"
                                          "cls:String(document.body&&document.body.className),"
                                          "tabs:document.querySelectorAll('#tabsBar button').length};})()"))
        except Exception as e:
            print("[boot diag err]", str(e)[:160])
        return False
    time.sleep(1.2)
    for _ in range(3):
        try:
            if cdp.eval("(function(){var s=document.querySelector('section.on');return !!s&&s.id==='s-power';})()"):
                return True
            open_power(cdp)
        except Exception:
            pass
        time.sleep(0.7)
    try:
        print("[boot diag] power not opened:", cdp.eval("(function(){var s=document.querySelector('section.on');"
                                                       "return s?s.id:'none';})()"))
    except Exception:
        pass
    return False


def run_phase_a(cdp):
    T("A0 启动完成 + 电费页打开", boot(cdp, 1), "")
    s0 = state(cdp)
    T("A1 未选择：日更徽标隐藏、无 history 请求", s0["chipHidden"] and s0["hist"] == 0, json.dumps({"chip": s0["chipText"], "hist": s0["hist"]}, ensure_ascii=False))

    # ===== S1：13-324 单段观测 =====
    ok = pick(cdp, "1-13---324")
    time.sleep(0.9)
    a = state(cdp)
    T("S1.0 13-324 加载（88.8）", ok and a["num"] == "88.8", a["num"])
    T("S1.1 日更 chip + title", (not a["chipHidden"]) and a["chipText"] == "日更"
      and a["chipTitle"] == "13/16 号楼网关日更，按真实更新点统计", json.dumps({"t": a["chipText"], "title": a["chipTitle"]}, ensure_ascii=False))
    T("S1.2 data-cadence=slow", a["cadence"] == "slow", a["cadence"])
    last_ok = bool(re.match(r"^更新 \d{2}-\d{2} \d{2}:\d{2}$", a["upd"])) and abs(
        (parse_upd(a["upd"]) or 0) - (time.time() * 1000 - 0.2 * 3600e3)) < 15 * 60e3
    T("S1.3 更新时间=最后真实变化点（约 12 分钟前；不是 updated_at 同步时间）",
      last_ok and a["upd"] != "更新 11-06 06:42",
      json.dumps({"upd": a["upd"], "expect": fmt_ts(time.time() * 1000 - 0.2 * 3600e3)}, ensure_ascii=False))
    T("S1.4 估算 7.9 天 / 11.3 度/天 / 参考",
      ("7.9" in a["tile1"]) and ("11.3" in a["tile1"]) and a["refText"] == "参考" and ("数据积累中" not in a["days"]),
      json.dumps({"tile1": a["tile1"], "days": a["days"]}, ensure_ascii=False))
    T("S1.5 环刻度 26.3 / 环内小字 7.9 天", a["ring"].startswith("26.3") and "7.9" in a["days"],
      json.dumps({"ring": a["ring"], "days": a["days"]}, ensure_ascii=False))
    T("S1.6 近 24h 用电 11.3 度 + 电费副标（非「该区间无更新」）",
      "11.3" in a["tile2"] and "该区间无更新" not in a["tile2"] and "¥" in a["tile2"], a["tile2"])
    T("S1.7 慢频阶梯线（H/V）+ 1 个变化点圆点", ("H" in a["pathD"] and "V" in a["pathD"]) and a["cdotN"] == 1,
      json.dumps({"path": a["pathD"][:90], "cdots": a["cdotN"]}, ensure_ascii=False))
    T("S1.8 24h 内有更新：无「近 24h 无更新」提示", a["noteHidden"], a["noteText"])
    T("S1.9 图例保真（起点/当前/近 24h 下降）", "起点" in a["legend"] and "当前" in a["legend"] and "近 24h 下降" in a["legend"], a["legend"])
    hrs = hist_reqs(cdp)
    wins = sorted([r["gte"] for r in hrs])
    diffs = [round((wins[i + 1] - wins[i]) / 3600e3) for i in range(len(wins) - 1)] if len(wins) > 1 else []
    contract = len(hrs) == 3 and all(("select=ts,quantity" in r["url"]) and ("order=ts.asc" in r["url"])
                                    and ("limit=2000" in r["url"]) and ("roomverify=eq.1-13---324" in r["url"]) for r in hrs)
    T("S1.10 取数契约：慢频房恰 3 个 history（24h/7d/30d）",
      contract and len(diffs) == 2 and 550 <= diffs[0] <= 554 and 143 <= diffs[1] <= 145,
      json.dumps({"n": len(hrs), "diffsH": diffs}, ensure_ascii=False))
    T("S1.11 截图 S1 390 宽", shot(cdp, "cadence_s1_390.png"), "")

    # ===== S2：16-305 24h 无更新 =====
    ok = pick(cdp, "1-16---305")
    time.sleep(0.9)
    b = state(cdp)
    T("S2.0 16-305 加载（38.0）", ok and b["num"] == "38.0", b["num"])
    T("S2.1 日更 chip", (not b["chipHidden"]) and b["chipText"] == "日更", b["chipText"])
    T("S2.2 估算 3.2 天 / 12.0 度/天 / 参考", "3.2" in b["tile1"] and "12.0" in b["tile1"] and b["refText"] == "参考", b["tile1"])
    T("S2.3 环刻度 10.6", b["ring"].startswith("10.5") or b["ring"].startswith("10.6"), b["ring"])
    T("S2.4 tile2 该区间无更新", "—" in b["tile2"] and "该区间无更新" in b["tile2"], b["tile2"])
    T("S2.5 「近 24h 无更新」提示可见", (not b["noteHidden"]) and b["noteText"] == "近 24h 无更新", b["noteText"])
    try:
        top = float(str(b["tdotTop"]).replace("%", ""))
    except Exception:
        top = -1
    T("S2.6 平线垂直居中（末点 top≈50%）", 49 <= top <= 51, b["tdotTop"])
    T("S2.7 无提示遮挡：#pwTrendNote pointer-events=none", b["notePE"] == "none", b["notePE"])
    T("S2.8 24h 无变化 → 0 个变化点圆点", b["cdotN"] == 0, b["cdotN"])
    T("S2.9 截图 S2 390 宽", shot(cdp, "cadence_s2_390.png"), "")

    # ===== S3：13-308 多段 =====
    ok = pick(cdp, "1-13---308")
    time.sleep(0.9)
    c = state(cdp)
    T("S3.0 13-308 加载（83.0）", ok and c["num"] == "83.0", c["num"])
    T("S3.1 估算 15.1 天 / 5.5 度/天 / 多段不标参考",
      ("15.1" in c["tile1"]) and ("5.5" in c["tile1"]) and c["refText"] == "" and ("15.1" in c["days"]),
      json.dumps({"tile1": c["tile1"], "days": c["days"], "ref": c["refText"]}, ensure_ascii=False))
    T("S3.2 环刻度 50.5", c["ring"].startswith("50.4") or c["ring"].startswith("50.5"), c["ring"])
    T("S3.3 24h 区间用电 6.0 度（非无更新）", "6.0" in c["tile2"] and "该区间无更新" not in c["tile2"], c["tile2"])
    T("S3.4 24h 变化 1 次 → 1 个变化点圆点", c["cdotN"] == 1, c["cdotN"])
    T("S3.5 有更新：无「近 24h 无更新」提示", c["noteHidden"], c["noteText"])
    T("S3.6 截图 S3 390 宽", shot(cdp, "cadence_s3_390.png"), "")
    # 7 天档：仍按真实时间压缩铺满、阶梯线、x 轴 3–5 刻度、无横滑；区间用电 37.0 度
    set_range(cdp, "7d", "7 天")
    time.sleep(0.7)
    c7 = state(cdp)
    T("S3.7 切 7 天：阶梯线 + x 轴 3–5 刻度 + 无横向滚动",
      ("H" in c7["pathD"] and "V" in c7["pathD"]) and (3 <= len(c7["xl"]) <= 5)
      and c7["scrollOX"] == "hidden" and c7["scrollSW"] <= c7["scrollCW"] + 1,
      json.dumps({"xl": len(c7["xl"]), "ox": c7["scrollOX"]}, ensure_ascii=False))
    T("S3.8 切 7 天：区间用电 37.0 度（真实下降累计）", "37.0" in c7["tile2"], c7["tile2"])
    T("S3.9 截图 S3 7 天 390 宽", shot(cdp, "cadence_s3_7d_390.png"), "")
    set_range(cdp, "24h", "24h")
    time.sleep(0.5)

    # ===== S4：16-306 只有充值 =====
    ok = pick(cdp, "1-16---306")
    time.sleep(0.9)
    d = state(cdp)
    T("S4.0 16-306 加载（120）", ok and d["num"] == "120", d["num"])
    T("S4.1 只有充值无用电段 → 数据积累中 / tile1 — / ring 4",
      "数据积累中" in d["days"] and "—" in d["tile1"] and d["ring"].startswith("4"),
      json.dumps({"days": d["days"], "tile1": d["tile1"], "ring": d["ring"]}, ensure_ascii=False))
    T("S4.2 无参考徽标", d["refText"] == "", d["refText"])
    T("S4.3 上次充值 120.00（30d 变化点，约 6h 前）", "120.00" in d["tile4"] and bool(re.search(r"\d{2}-\d{2} \d{2}:\d{2}", d["tile4"])), d["tile4"])
    T("S4.4 日更 chip 仍显示", (not d["chipHidden"]) and d["chipText"] == "日更", d["chipText"])

    # ===== L1：23A-321 完全保持现状 =====
    n_l0 = state(cdp)["hist"]
    ok = pick(cdp, "4-23A---321")
    time.sleep(0.9)
    l1 = state(cdp)
    T("L1.0 23A-321 加载（382）", ok and l1["num"] == "382", l1["num"])
    T("L1.1 无日更 chip / data-cadence=live", l1["chipHidden"] and l1["cadence"] == "live",
      json.dumps({"hidden": l1["chipHidden"], "cad": l1["cadence"]}, ensure_ascii=False))
    T("L1.2 估算 ≥30 天、无参考、近 24h 用电 6.3 度",
      "≥30" in l1["days"] and l1["refText"] == "" and "6.3" in l1["tile2"],
      json.dumps({"days": l1["days"], "tile2": l1["tile2"]}, ensure_ascii=False))
    T("L1.3 更新时间仍用 updated_at（现状：11-06 06:42）", l1["upd"] == "更新 11-06 06:42", l1["upd"])
    T("L1.4 实时房折线（无阶梯 H/V）、无变化点圆点", "L" in l1["pathD"] and "H" not in l1["pathD"] and l1["cdotN"] == 0,
      json.dumps({"path": l1["pathD"][:90], "cdots": l1["cdotN"]}, ensure_ascii=False))
    T("L1.5 实时房选择 → 恰好 2 个 history 窗口（现状）", l1["hist"] - n_l0 == 2, "%s->%s" % (n_l0, l1["hist"]))
    T("L1.6 截图实时房 390 宽", shot(cdp, "cadence_live_390.png"), "")

    # ===== L2：23B-422 新守卫 =====
    n_l2_0 = state(cdp)["hist"]
    ok = pick(cdp, "4-23B---422")
    time.sleep(0.9)
    l2 = state(cdp)
    T("L2.0 23B-422 加载（100）", ok and l2["num"] == "100", l2["num"])
    T("L2.1 24h/7d 均无真实下降 → 数据积累中（不再伪造 ≥30 天）",
      "数据积累中" in l2["days"] and "—" in l2["tile1"] and l2["ring"].startswith("4"),
      json.dumps({"days": l2["days"], "tile1": l2["tile1"], "ring": l2["ring"]}, ensure_ascii=False))
    T("L2.2 实时房 2 个 history 窗口（24h+7d）", l2["hist"] - n_l2_0 == 2, "%s->%s" % (n_l2_0, l2["hist"]))

    # ===== 宽度 / 溢出（慢频有更新状态 S1）=====
    pick(cdp, "1-13---324")
    time.sleep(0.8)
    for w, h in ((360, 800), (430, 900), (1280, 900)):
        set_metrics(cdp, w, h)
        time.sleep(0.7)
        cdp.eval("window.scrollTo(0,0)")
        time.sleep(0.2)
        ov = cdp.eval(r"""(function(){
          var de=document.documentElement,bad=[];
          Array.prototype.slice.call(document.querySelectorAll('#s-power *')).forEach(function(e){
            var r=e.getBoundingClientRect();
            if(r.width>0&&r.right>de.clientWidth+1&&getComputedStyle(e).position!=='fixed')bad.push(e.tagName+'.'+String(e.className).split(' ')[0]);
          });
          return {vw:de.clientWidth,sw:de.scrollWidth,bad:bad.slice(0,6)};})()""")
        T("W1 %d 宽：无横向溢出" % w, ov["sw"] <= ov["vw"] + 1 and len(ov["bad"]) == 0, json.dumps(ov, ensure_ascii=False))
        if w == 1280:
            st = state(cdp)
            T("W2 1280 宽：日更 chip + 阶梯线 + 参考徽标正常", (not st["chipHidden"]) and st["chipText"] == "日更"
              and ("H" in st["pathD"]) and st["refText"] == "参考",
              json.dumps({"chip": st["chipText"], "ref": st["refText"]}, ensure_ascii=False))
            T("W3 1280 宽截图", shot(cdp, "cadence_1280.png"), "")
            T("W4 1280 宽：tile 数仍为 4、估算不溢出", st["tile1"] != "" and "7.9" in st["tile1"], st["tile1"])
    set_metrics(cdp, 390, 844)
    time.sleep(0.5)

    errs = cdp.eval("JSON.stringify(window.__errs||[])")
    cerrs = cdp.eval("JSON.stringify(window.__cerrs||[])")
    T("A2 阶段 A 0 JS 报错", errs == "[]", errs[:300])
    T("A3 阶段 A 0 console.error", cerrs == "[]", cerrs[:300])


def run_phase_b(cdp):
    # S5 / 平线无变化 / 数据覆盖 三个 fixture（规格 §5 补充 + 数据覆盖用例）
    T("B0 阶段 B 启动完成 + 电费页打开", boot(cdp, 2), "")

    # ===== S5：16-306 异常大扣减剔除 + 30d 区间用电 =====
    ok = pick(cdp, "1-16---306")
    time.sleep(0.9)
    s5 = state(cdp)
    T("S5.0 16-306（S5 fixture）加载 122", ok and s5["num"] == "122", s5["num"])
    T("S5.1 异常段剔除 → 3.0 度/天、≥30 天、多段不标参考",
      ("≥30" in s5["days"]) and ("3.0" in s5["tile1"]) and s5["refText"] == "",
      json.dumps({"days": s5["days"], "tile1": s5["tile1"]}, ensure_ascii=False))
    T("S5.2 环刻度满环 100", s5["ring"].startswith("100"), s5["ring"])
    T("S5.3 日更 chip", (not s5["chipHidden"]) and s5["chipText"] == "日更", s5["chipText"])
    set_range(cdp, "30d", "30 天")
    time.sleep(0.8)
    s5b = state(cdp)
    T("S5.4 切 30 天：区间用电 18.0 度（异常 60 度段被 deductOf 剔除）",
      "18.0" in s5b["tile2"], s5b["tile2"])
    T("S5.5 切 30 天：图例区间下降 18.00、异常段 60.00 标为扣减",
      "18.00" in s5b["legend"] and "扣减 60.00" in s5b["legend"], s5b["legend"])
    T("S5.6 切 30 天：x 轴 3–5 刻度、无横向滚动",
      3 <= len(s5b["xl"]) <= 5 and s5b["scrollOX"] == "hidden" and s5b["scrollSW"] <= s5b["scrollCW"] + 1,
      json.dumps({"xl": len(s5b["xl"]), "ox": s5b["scrollOX"], "sw": s5b["scrollSW"], "cw": s5b["scrollCW"]}, ensure_ascii=False))
    T("S5.7 切 30 天：命中缓存不重复请求（pull 已拉 30d）", hist_for(cdp, "1-16---306") == 3,
      "%s (all=%s)" % (hist_for(cdp, "1-16---306"), state(cdp)["hist"]))
    T("S5.8 截图 S5 30 天 390 宽", shot(cdp, "cadence_s5_30d_390.png"), "")

    # ===== 平线 + 近 30 天无变化（13-324 30 天恒定）=====
    set_range(cdp, "24h", "24h")
    time.sleep(0.4)
    ok = pick(cdp, "1-13---324")
    time.sleep(0.9)
    fl = state(cdp)
    T("F1.0 恒定 30 天房：加载 100、日更 chip", ok and fl["num"] == "100" and (not fl["chipHidden"]) and fl["chipText"] == "日更",
      json.dumps({"num": fl["num"], "chip": fl["chipText"]}, ensure_ascii=False))
    T("F1.1 30 天无变化 → hero「近 30 天无变化」", fl["upd"] == "近 30 天无变化", fl["upd"])
    T("F1.2 无有效用电段 → 数据积累中 + tile2 该区间无更新",
      "数据积累中" in fl["days"] and "—" in fl["tile2"] and "该区间无更新" in fl["tile2"],
      json.dumps({"days": fl["days"], "tile2": fl["tile2"]}, ensure_ascii=False))
    T("F1.3 24h 无更新提示「近 24h 无更新」", (not fl["noteHidden"]) and fl["noteText"] == "近 24h 无更新", fl["noteText"])
    T("F1.4 平线阶梯线 + 无变化点圆点 + 垂直居中",
      ("H" in fl["pathD"] and "V" in fl["pathD"]) and fl["cdotN"] == 0 and fl["tdotTop"] == "50%",
      json.dumps({"path": fl["pathD"][:80], "cdots": fl["cdotN"], "top": fl["tdotTop"]}, ensure_ascii=False))
    set_range(cdp, "7d", "7 天")
    time.sleep(0.5)
    f7 = state(cdp)
    T("F1.5 切 7 天：提示「近 7 天无更新」", (not f7["noteHidden"]) and f7["noteText"] == "近 7 天无更新", f7["noteText"])
    set_range(cdp, "30d", "30 天")
    time.sleep(0.5)
    f30 = state(cdp)
    T("F1.6 切 30 天：提示「近 30 天无更新」、x 轴 3–5 刻度",
      (not f30["noteHidden"]) and f30["noteText"] == "近 30 天无更新" and 3 <= len(f30["xl"]) <= 5,
      json.dumps({"note": f30["noteText"], "xl": len(f30["xl"])}, ensure_ascii=False))
    T("F1.7 切档不重复请求（慢频 30d 已随 pull 缓存）", hist_for(cdp, "1-13---324") == 3,
      "%s (all=%s)" % (hist_for(cdp, "1-13---324"), state(cdp)["hist"]))
    T("F1.8 截图平线无更新 30 天 390 宽", shot(cdp, "cadence_flat_30d_390.png"), "")
    # 趋势区横滑不切工具（片段事件）
    act0 = state(cdp)["active"]
    try:
        cdp.eval(r"""(function(){
          var sc=document.getElementById('pwTrendScroll');
          function send(type,x){
            var t=new Touch({identifier:9,target:sc,clientX:x,clientY:600,pageX:x,pageY:600});
            var e=new TouchEvent(type,{bubbles:true,cancelable:true,touches:(type==='touchend'?[]:[t]),
              targetTouches:(type==='touchend'?[]:[t]),changedTouches:[t]});
            sc.dispatchEvent(e);
          }
          send('touchstart',330);send('touchmove',150);send('touchend',150);return true;})()""")
    except Exception:
        pass
    time.sleep(0.5)
    T("F1.9 趋势横滑不触发切工具（仍在电费页）", state(cdp)["active"] == "s-power" and act0 == "s-power",
      json.dumps({"before": act0, "after": state(cdp)["active"]}, ensure_ascii=False))

    # ===== 数据覆盖：13 号楼某房 24h changes≥6 → 走实时口径 =====
    ok = pick(cdp, "1-13---308")
    time.sleep(1.0)
    cov = state(cdp)
    T("C1.0 覆盖 fixture 加载（92.0）", ok and cov["num"] == "92.0", cov["num"])
    T("C1.1 24h changes≥6 → 不显示日更 chip、data-cadence=live",
      cov["chipHidden"] and cov["cadence"] == "live",
      json.dumps({"hidden": cov["chipHidden"], "cad": cov["cadence"]}, ensure_ascii=False))
    T("C1.2 走实时口径：估算有效（非数据积累中）、无参考",
      ("数据积累中" not in cov["days"]) and cov["refText"] == "",
      json.dumps({"days": cov["days"], "tile1": cov["tile1"]}, ensure_ascii=False))
    T("C1.3 实时房更新时间用 updated_at（11-06 06:42）", cov["upd"] == "更新 11-06 06:42", cov["upd"])

    errs = cdp.eval("JSON.stringify(window.__errs||[])")
    cerrs = cdp.eval("JSON.stringify(window.__cerrs||[])")
    ext = state(cdp)["extern"]
    T("B1 阶段 B 0 JS 报错", errs == "[]", errs[:300])
    T("B2 阶段 B 0 console.error", cerrs == "[]", cerrs[:300])
    T("B3 0 外部请求", len(ext) == 0, json.dumps(ext[:4], ensure_ascii=False))


PHASE_A_ROWS = {
    "1-13---324": {"quantity": 88.75, "low": False},
    "1-16---305": {"quantity": 38.00, "low": False},
    "1-13---308": {"quantity": 83.00, "low": False},
    "1-16---306": {"quantity": 120.00, "low": False},
}
PHASE_A_HIST = {
    "1-13---324": [(11.2, 100.00), (0.2, 88.75)],                                           # S1
    "1-16---305": [(30.1, 50.00), (6.1, 38.00), (0.2, 38.00)],                              # S2
    "1-13---308": [(168, 120.00), (96, 101.00), (72, 101.00), (48, 89.00), (24, 89.00), (6, 83.00), (0.2, 83.00)],  # S3
    "1-16---306": [(48, 90.00), (24, 90.00), (6, 120.00), (0.2, 120.00)],                   # S4
}
PHASE_B_ROWS = {
    "1-16---306": {"quantity": 122.00, "low": False},
    "1-13---324": {"quantity": 100.00, "low": False},
    "1-13---308": {"quantity": 92.00, "low": False},
}
PHASE_B_HIST = {
    # S5：异常 60 度大跌应被中位数阈值剔除
    "1-16---306": [(168, 200.00), (120, 194.00), (96, 194.00), (72, 188.00), (48, 188.00),
                   (24, 182.00), (12, 122.00), (0.2, 122.00)],
    # 30 天恒定 → events 只有起点、lastChange=null、各窗口 changes=0
    "1-13---324": [(160, 100.00), (140, 100.00), (120, 100.00), (100, 100.00), (80, 100.00),
                   (60, 100.00), (40, 100.00), (20, 100.00), (0.2, 100.00)],
    # 数据覆盖：24h 内 8 次真实变化 → isSlowRoom 降级为实时口径
    "1-13---308": [(24, 100.00), (21, 99.00), (18, 98.00), (15, 97.00), (12, 96.00),
                   (9, 95.00), (6, 94.00), (3, 93.00), (0.2, 92.00)],
}


def main():
    os.makedirs(SHOTS, exist_ok=True)
    devnull = open(os.devnull, "wb")
    prof = tempfile.mkdtemp(prefix="edgeprof_cad_")
    proc = cdp = httpd = None
    try:
        apply_fixtures(PHASE_A_ROWS, PHASE_A_HIST, 1)
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
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844,
                                                        "deviceScaleFactor": 2, "mobile": True})
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        run_phase_a(cdp)
        apply_fixtures(PHASE_B_ROWS, PHASE_B_HIST, 2)
        run_phase_b(cdp)
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
    print("v2_power_cadence_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("截图目录:", SHOTS)
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
