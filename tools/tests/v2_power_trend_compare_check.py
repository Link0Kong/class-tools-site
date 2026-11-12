# -*- coding: utf-8 -*-
r"""自检：电费「13/16 号楼隐藏 24h 趋势」+「电费比较改为自然周期同期」（2026-11-11，网页）。

覆盖：
A. 静态：比较文案常量/自然周期函数/慢楼栋隐藏逻辑/并发取数去重/无「较上窗口」残留/使用说明；
B. 13/16 号楼：24h 按钮隐藏、默认/自动切 7 天、7 天/30 天仍可用；
C. 电费比较（mock 70 天历史）：
   C1 23B-423 近24h → 「较昨日同期」，百分比与 mock 口径一致；
   C2 近7天 → 「较上周同期」，且补拉 14 天窗口；
   C3 近30天 → 「较上月同期」，且补拉 70 天窗口；
   C4 16-305（慢楼栋）近7天 → 「较上周同期」；24h 按钮隐藏；
   C5 历史数据不足（仅 5 天）→ 上周/上月比较不显示（不硬凑），昨日比较仍显示；
   C6 同一窗口不重复请求（并发去重）；
   C7 切回实时房 423 后 24h 按钮恢复；
D. 360/430/1280 无横向溢出、0 JS 报错。

用法：python tools\tests\v2_power_trend_compare_check.py
      set SPEC_CHECK=<副本.html>   # 复盘任意副本
退出码 0 = 全绿。
"""
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import time
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
WEB = os.path.dirname(TOOLS)
SRC = os.path.abspath(os.environ.get("SPEC_CHECK") or os.path.join(TOOLS, "index.html"))
SRC_TEXT = open(SRC, encoding="utf-8").read()
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

SID = "9999000001"
NAME = "测试同学"
SHOTS = os.path.join(HERE, "_shots_power_trend")
REAL_ROOM = "4-23B---423"
SLOW_ROOM = "1-16---305"
SLOW13 = "1-13---324"
DAY = 86400000
PASS = 0
FAIL = 0
FAILS = []


def T(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + name)
    else:
        FAIL += 1
        FAILS.append(name + (" | " + str(detail) if detail != "" else ""))
        print("  [FAIL] " + name + (("  <" + str(detail) + ">") if detail != "" else ""))


def delta_pct(text):
    m = re.search(r'([+-]?\d+)%', text or "")
    return int(m.group(1)) if m else None


def wait_delta(page, timeout=8.0):
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        try:
            last = page.evaluate("(function(){var d=document.querySelector('#pwUseTile .opt-pw-delta');return d?d.textContent:null;})()") or ""
        except Exception:
            last = ""
        if last:
            return last
        time.sleep(0.15)
    return last


# ---------------------------------------------------------------- mock 数据
def build_history(rv, now_ms, days=70):
    """返回升序点（电量随时间下降）。423 每小时，305/324 每天。
    423 各自然周期速率不同，用于断言比较百分比。"""
    today = datetime.fromtimestamp(now_ms / 1000).replace(hour=0, minute=0, second=0, microsecond=0)
    today_ms = int(today.timestamp() * 1000)
    week_ms = today_ms - today.weekday() * DAY
    month_ms = int(today.replace(day=1).timestamp() * 1000)
    prev_month_first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    prev_month_ms = int(prev_month_first.timestamp() * 1000)

    if days <= 5:
        start = today_ms - days * DAY
    else:
        start = now_ms - days * DAY
    out = []

    if rv == REAL_ROOM:
        def rate_at(t):
            if t >= today_ms:
                return 0.20
            if t >= today_ms - DAY:
                return 0.10
            if t >= week_ms:
                return 0.15
            if t >= week_ms - 7 * DAY:
                return 0.10
            if t >= month_ms:
                return 0.12
            if t >= prev_month_ms:
                return 0.08
            return 0.10
        t = start
        q = 1000.0
        while t <= now_ms:
            out.append({"ts": datetime.fromtimestamp(t / 1000).astimezone().isoformat(), "quantity": round(q, 4)})
            q -= rate_at(t)
            t += 3600 * 1000
        return out
    t = today_ms - (days - 1) * DAY
    q = 900.0
    for _ in range(days):
        if t <= now_ms:
            out.append({"ts": datetime.fromtimestamp(t / 1000).astimezone().isoformat(), "quantity": round(q, 3)})
        q -= 5.0
        t += DAY
    return out


def windows(range_, now_ms):
    def day_start(ts):
        d = datetime.fromtimestamp(ts / 1000)
        return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

    def week_start(ts):
        d = datetime.fromtimestamp(ts / 1000)
        ws = d.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=d.weekday())
        return int(ws.timestamp() * 1000)

    def month_start(ts):
        d = datetime.fromtimestamp(ts / 1000)
        return int(d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

    def shift_month(ts, delta):
        d = datetime.fromtimestamp(ts / 1000)
        day = d.day
        first = d.replace(day=1)
        m = first.month - 1 + delta
        y = first.year + m // 12
        m = m % 12 + 1
        import calendar
        last = calendar.monthrange(y, m)[1]
        return int(first.replace(year=y, month=m, day=min(day, last)).timestamp() * 1000)

    if range_ == "24h":
        return (day_start(now_ms), now_ms), (day_start(now_ms - DAY), now_ms - DAY)
    if range_ == "7d":
        return (week_start(now_ms), now_ms), (week_start(now_ms - 7 * DAY), now_ms - 7 * DAY)
    return (month_start(now_ms), now_ms), (shift_month(month_start(now_ms), -1), shift_month(now_ms, -1))


def usage_between(pts, start, end):
    sub = [p for p in pts if start <= p["t"] <= end]
    if len(sub) < 2:
        return None
    drop = 0.0
    for i in range(1, len(sub)):
        dq = sub[i - 1]["q"] - sub[i]["q"]
        if dq > 0.005:
            drop += dq
    return drop


def expected_pct(pts, range_, now_ms):
    cur, prev = windows(range_, now_ms)
    cu = usage_between(pts, cur[0], cur[1])
    pu = usage_between(pts, prev[0], prev[1])
    if not cu or not pu or pu <= 0.01:
        return None
    return (cu - pu) / pu * 100


def to_points(rows):
    out = []
    for r in rows:
        out.append({"t": int(datetime.fromisoformat(r["ts"]).timestamp() * 1000), "q": float(r["quantity"])})
    out.sort(key=lambda p: p["t"])
    return out


# ---------------------------------------------------------------- 页面 mock
SHIM = r"""
(function(){
  try{
    var REMOTE=__REMOTE__;
    window.__gw={remote:REMOTE,writes:[],hist:[]};
    var _f=window.fetch&&window.fetch.bind(window);
    function J(o,s){return Promise.resolve(new Response(JSON.stringify(o),{status:s||200,headers:{'Content-Type':'application/json'}}));}
    function S(){try{sessionStorage.setItem('__gwremote',JSON.stringify(window.__gw.remote));}catch(e){}}
    window.fetch=function(u,o){
      var url=String((u&&u.url)||u),m=String((o&&o.method)||'GET').toUpperCase();
      if(url.indexOf('tcloudbasegateway.com')<0)return _f.apply(this,arguments);
      if(m==='OPTIONS')return J('',204);
      if(url.indexOf('/userdata')>=0){
        if(m==='GET')return J([{id:'__SID__',blob:JSON.stringify(window.__gw.remote),ts:Date.now()}]);
        try{var arr=JSON.parse((o&&o.body)||'[]');if(arr[0]&&arr[0].blob){window.__gw.remote=JSON.parse(arr[0].blob);S();}}catch(e){}
        return J([]);
      }
      if(url.indexOf('/rpc/class_members')>=0)return J([{seat:24,name:'__NAME__',role:'',badge:'',sid:'__SID__'}]);
      if(url.indexOf('/rpc/')>=0)return J({ok:true});
      if(url.indexOf('/power_history')>=0){
        var mm=url.match(/roomverify=eq\.([^&]+)/);
        var rv=mm?decodeURIComponent(mm[1]):'';
        var mts=url.match(/ts=gte\.([^&]+)/);
        var cut=mts?Date.parse(decodeURIComponent(mts[1])):0;
        window.__gw.hist.push({rv:rv,cut:cut,url:url});
        var arr=(__HIST__[rv]||[]).filter(function(p){return Date.parse(p.ts)>=cut;});
        return J(arr);
      }
      if(url.indexOf('/power?')>=0){
        var mm=url.match(/id=eq\.([^&]+)/);var rv=mm?decodeURIComponent(mm[1]):'';
        return J([__ROWS__[rv]||__ROWS__['4-23B---423']]);
      }
      return J([]);
    };
  }catch(e){}
})();
"""

IDENT = ("try{localStorage.clear();sessionStorage.clear();"
         "localStorage.setItem('zq_class_identity',JSON.stringify({token:'qa-token',sid:'__SID__',name:'__NAME__',"
         "role:'',badge:'',is_admin:true,ts:Date.now()}));}catch(e){}")


def ud_blob(sel=REAL_ROOM):
    now = int(time.time() * 1000)
    return {"v": 6, "at": {"homeTools": now, "fit": now, "draw": now, "group": now, "roster": now, "hide": now,
                           "tt": now, "prefs": now, "nick": now, "power": now, "water": now},
            "homeTools": ["draw", "hw", "nt", "tt"], "fit": {}, "draw": {}, "group": {}, "roster": {},
            "hide": {}, "tt": {}, "prefs": {}, "nick": "",
            "power": {"sel": sel, "at": now, "low": 30}, "water": {"rooms": {}}, "homeToolsAt": now}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(port):
    root = os.path.dirname(SRC)
    h = lambda *a, **kw: Quiet(*a, directory=root, **kw)
    s = socketserver.ThreadingTCPServer(("127.0.0.1", port), h)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def snapshot(page):
    return page.evaluate("""(function(){
      var q=function(s){return document.querySelector(s);};
      var ranges=[].map.call(document.querySelectorAll('#pwRanges .pw-range'),function(b){
        return {k:b.getAttribute('data-range'),hidden:!!b.hidden,display:getComputedStyle(b).display,on:b.classList.contains('on')};});
      var tile=q('#pwUseTile'), delta=tile?tile.querySelector('.opt-pw-delta'):null,
          line=tile?tile.querySelector('.pw-cmp'):null, ts=tile?tile.querySelector('.pw-ts'):null, tr=q('#pwTrend');
      function box(el){if(!el)return null;var b=el.getBoundingClientRect();
        return {x:Math.round(b.x),y:Math.round(b.y),w:Math.round(b.width),h:Math.round(b.height),
                right:Math.round(b.right),bottom:Math.round(b.bottom)};}
      var cmpClipped=false;
      if(line&&tile){
        var lb=line.getBoundingClientRect(),tb=tile.getBoundingClientRect();
        cmpClipped=(lb.right>tb.right-1||lb.left<tb.left-1||lb.bottom>tb.bottom+1);
      }
      return {ranges:ranges, title:(q('#pwTrendTitle')||{}).textContent,
              tile2:tile?tile.textContent:null, delta:delta?delta.textContent:null,
              deltaTitle:delta?delta.getAttribute('title'):null,
              cmpLine:!!line, cmpBox:box(line), cmpDeltaBox:box(delta), tileBox:box(tile),
              cmpClipped:cmpClipped, tsClipped:!!(ts&&ts.scrollWidth>ts.clientWidth+1),
              hasSvg:!!(tr&&tr.querySelector('svg')), sel:(q('#pwSelect')||{}).value,
              trect:tr?tr.getBoundingClientRect().width:0,
              overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
              hist:(window.__gw&&window.__gw.hist||[]).map(function(x){return {rv:x.rv,cut:x.cut};}),
              errs:(window.__errs||[]).slice(-3)};
    })()""")


def open_power(page):
    page.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();'x'")
    time.sleep(0.4)
    page.evaluate("var b=document.querySelector('#allCards [data-open=\"power\"]');if(b)b.click();'x'")
    page.wait_for("!!document.querySelector('#s-power')&&document.querySelector('#s-power').classList.contains('on')", 15)
    time.sleep(0.6)


def pick_range(page, k):
    page.evaluate("(function(){var b=document.querySelector('#pwRanges [data-range=\"%s\"]');if(b)b.click();return true;})()" % k)
    time.sleep(1.4)


def pick_room(page, rv):
    page.evaluate("(function(){var s=document.querySelector('#pwSelect');s.value=%s;s.dispatchEvent(new Event('change',{bubbles:true}));return true;})()" % json.dumps(rv))
    time.sleep(2.2)


def scroll_tile(page):
    """把「区间用电」tile 滚到视口中间，供手机比例肉眼/截图核查。"""
    page.evaluate("(function(){var t=document.getElementById('pwUseTile');if(t)t.scrollIntoView({block:'center'});return true;})()")
    time.sleep(0.4)


def wait_ready(page, timeout=25):
    page.wait_load(30)
    return page.wait_for("!document.body.classList.contains('auth-pending')", timeout)


def make_rows():
    now = int(time.time() * 1000)
    return {
        REAL_ROOM: {"id": REAL_ROOM, "label": "23号楼B座423", "building": "23号楼B座", "room": "423",
                    "quantity": 77.8, "unit": "度", "low": False, "updated_at": "2026-11-11T19:00:00+08:00"},
        SLOW_ROOM: {"id": SLOW_ROOM, "label": "16号楼305", "building": "16号楼", "room": "305",
                    "quantity": 38.0, "unit": "度", "low": False, "updated_at": "2026-11-11T19:00:00+08:00"},
        SLOW13: {"id": SLOW13, "label": "13号楼324", "building": "13号楼", "room": "324",
                 "quantity": 78.0, "unit": "度", "low": False, "updated_at": "2026-11-11T19:00:00+08:00"},
    }


def page_script(hist, rows, cache):
    shim = SHIM.replace("__REMOTE__", json.dumps(ud_blob())).replace("__SID__", SID).replace("__NAME__", NAME)
    shim = shim.replace("__HIST__", json.dumps(hist, ensure_ascii=False)).replace("__ROWS__", json.dumps(rows, ensure_ascii=False))
    init = IDENT.replace("__SID__", SID).replace("__NAME__", NAME)
    if cache is not None:
        init += "try{localStorage.setItem('zq_udcache_%s',%s);}catch(e){}" % (SID, json.dumps(json.dumps(cache)))
    return shim + init


def new_page(b, port, hist, rows, cache=None, w=1280, h=900, mobile=False):
    p = b.new_page("about:blank")
    p.set_device(w, h, dpr=2.0 if mobile else 1.0, mobile=mobile, touch=mobile)
    p.add_init_script(page_script(hist, rows, cache))
    p.navigate("http://127.0.0.1:%d/index.html" % port)
    assert wait_ready(p), "identity ready timeout"
    time.sleep(0.5)
    return p


def main():
    os.makedirs(SHOTS, exist_ok=True)
    port = 8993
    srv = serve(port)
    now = int(time.time() * 1000)
    rows = make_rows()
    hist_rich = {REAL_ROOM: build_history(REAL_ROOM, now), SLOW_ROOM: build_history(SLOW_ROOM, now),
                 SLOW13: build_history(SLOW13, now)}
    hist_short = {REAL_ROOM: build_history(REAL_ROOM, now, days=5),
                  SLOW_ROOM: build_history(SLOW_ROOM, now, days=5),
                  SLOW13: build_history(SLOW13, now, days=5)}
    b = _cdp.Browser(window=(1280, 900))
    try:
        # ================= A. 静态 =================
        print("\n== A 静态检查 ==")
        for name, cond in [
            ("A1 自然周期比较常量（较昨日/上周/上月同期）",
             all(k in SRC_TEXT for k in ('"24h":"较昨日同期"', '"7d":"较上周同期"', '"30d":"较上月同期"'))),
            ("A2 自然周期窗口/覆盖/比较函数",
             all(k in SRC_TEXT for k in ("naturalWindows:function", "naturalCompare:function", "cmpCoverage:function", "cmpSource:function"))),
            ("A3 慢楼栋隐藏 24h（slowBldOf/normRangeForSel/renderChips）",
             all(k in SRC_TEXT for k in ("slowBldOf:function", "normRangeForSel:function", "POWER.slowBldOf(POWER.sel)"))),
            ("A4 比较窗口按需补拉（ensureCompare）", "ensureCompare:function" in SRC_TEXT),
            ("A5 history 并发去重（_hf）", "POWER._hf" in SRC_TEXT),
            ("A6 不再出现「较上窗口」文案", "较上窗口" not in SRC_TEXT),
            ("A7 使用说明注明 13/16 不提供 24h", "不提供 24h" in SRC_TEXT),
            ("A8 APP_VER 仍为 2.0.0", 'var APP_VER="2.0.0"' in SRC_TEXT),
            ("A9 手机比例比较行独立（.pw-cmp 样式 + opt2PowerDelta 建独立行，不再追加进 .pw-ts）",
             ".pw-tile .pw-cmp" in SRC_TEXT and 'line.className="pw-cmp ' in SRC_TEXT
             and 'ts.insertAdjacentElement("afterend",line)' in SRC_TEXT),
        ]:
            T(name, cond)

        # ================= B/C 运行时 =================
        print("\n== B 13/16 隐藏 24h ==")
        p = new_page(b, port, hist_rich, rows, cache=ud_blob(), w=1280, h=900)
        open_power(p)
        wait_delta(p)
        s = snapshot(p)
        r24 = [r for r in s["ranges"] if r["k"] == "24h"][0]
        T("B1 实时房（23B-423）24h 按钮可见", (not r24["hidden"]) and r24["display"] != "none" and r24["on"], r24)
        exp24 = expected_pct(to_points(hist_rich[REAL_ROOM]), "24h", now)
        got24 = delta_pct(s["delta"])
        T("B2 实时房默认近24h且比较=较昨日同期（百分比符合自然周期口径）",
          "较昨日同期" in (s["delta"] or "") and got24 is not None and abs(got24 - round(exp24 or 0)) <= 1,
          (s["delta"], exp24, got24))
        T("B3 比较徽标 title 说明统计时段", "今日 00:00" in (s["deltaTitle"] or ""), s["deltaTitle"])
        p.screenshot(os.path.join(SHOTS, "1280_24h.png"))
        pick_range(p, "7d")
        wait_delta(p)
        s7 = snapshot(p)
        exp7 = expected_pct(to_points(hist_rich[REAL_ROOM]), "7d", now)
        got7 = delta_pct(s7["delta"])
        T("B4 近7天比较=较上周同期且百分比符合自然周期口径",
          "较上周同期" in (s7["delta"] or "") and got7 is not None and abs(got7 - round(exp7 or 0)) <= 1,
          (s7["delta"], exp7, got7))
        T("B5 近7天已补拉 14 天比较窗口", any(abs(h["cut"] - (now - 14 * DAY)) < 5 * 60000 for h in s7["hist"]), s7["hist"][-3:])
        pick_range(p, "30d")
        wait_delta(p)
        s30 = snapshot(p)
        exp30 = expected_pct(to_points(hist_rich[REAL_ROOM]), "30d", now)
        got30 = delta_pct(s30["delta"])
        T("B6 近30天比较=较上月同期且百分比符合自然周期口径",
          "较上月同期" in (s30["delta"] or "") and got30 is not None and abs(got30 - round(exp30 or 0)) <= 1,
          (s30["delta"], exp30, got30))
        T("B7 近30天已补拉 70 天比较窗口", any(abs(h["cut"] - (now - 70 * DAY)) < 5 * 60000 for h in s30["hist"]), s30["hist"][-3:])
        # 切慢楼栋 16-305：24h 隐藏，从 30d 保持 30d 或切 7d 都允许；先切回 24h 再选慢房验证默认 7d
        pick_range(p, "24h")
        pick_room(p, SLOW_ROOM)
        wait_delta(p)
        slow1 = snapshot(p)
        r24s = [r for r in slow1["ranges"] if r["k"] == "24h"][0]
        T("B8 慢楼栋（16-305）24h 按钮隐藏", r24s["hidden"] and r24s["display"] == "none", r24s)
        on_ranges = [r for r in slow1["ranges"] if r["on"]]
        T("B9 从 24h 切到慢楼栋 → 自动落到 7 天档",
          bool(on_ranges) and on_ranges[0]["k"] == "7d" and "近 7 天趋势" in (slow1["title"] or ""),
          (slow1["ranges"], slow1["title"]))
        T("B10 慢楼栋近7天也有「较上周同期」", "较上周同期" in (slow1["delta"] or ""), slow1["delta"])
        p.screenshot(os.path.join(SHOTS, "1280_slow_7d.png"))
        # 13号楼同样隐藏
        pick_room(p, SLOW13)
        slow13 = snapshot(p)
        T("B11 13号楼 24h 按钮同样隐藏", [r for r in slow13["ranges"] if r["k"] == "24h"][0]["hidden"], slow13["ranges"])
        # 切回实时房 → 24h 恢复
        pick_room(p, REAL_ROOM)
        back = snapshot(p)
        T("B12 切回实时房 24h 按钮恢复", not [r for r in back["ranges"] if r["k"] == "24h"][0]["hidden"], back["ranges"])
        T("B13 全程 0 JS 报错", (p.evaluate("JSON.stringify(window.__errs||[])") or "[]") in ("[]", ""),
          p.evaluate("JSON.stringify(window.__errs||[])"))
        p.close()

        print("\n== C 历史不足时降级 ==")
        ps = new_page(b, port, hist_short, rows, cache=ud_blob(), w=390, h=844, mobile=True)
        open_power(ps)
        wait_delta(ps)
        ss = snapshot(ps)
        T("C1 历史仅 5 天：近24h 比较仍显示（昨日在数据内）", "较昨日同期" in (ss["delta"] or ""), ss["delta"])
        pick_range(ps, "7d")
        time.sleep(1.0)
        ss7 = snapshot(ps)
        T("C2 历史仅 5 天：近7天「较上周同期」不显示（不硬凑残缺周期）", "较上周同期" not in (ss7["delta"] or ""), ss7["delta"])
        ps.screenshot(os.path.join(SHOTS, "390_short_7d.png"))
        ps.close()

        print("\n== D 请求去重 / 多宽度 ==")
        pd = new_page(b, port, hist_rich, rows, cache=ud_blob(), w=430, h=900, mobile=True)
        open_power(pd)
        pick_range(pd, "7d")
        hh = snapshot(pd)["hist"]
        # 同一 (房间, 窗口起点按分钟归桶) 只应出现一次（并发去重）
        keys = [(x["rv"], round(x["cut"] / 60000)) for x in hh]
        dup = [k for k in set(keys) if keys.count(k) > 1]
        T("D1 同一房间同一窗口不重复请求", not dup, dup)
        T("D2 430 无横向溢出", snapshot(pd)["overflow"] == 0, snapshot(pd)["overflow"])
        scroll_tile(pd)
        sd = snapshot(pd)
        T("D2b 430 手机比例：同期比较独立成行、完整显示（不被单行 .pw-ts 裁掉）",
          sd["cmpLine"] and (not sd["cmpClipped"]) and (not sd["tsClipped"]) and "较上周同期" in (sd["delta"] or ""),
          (sd["cmpBox"], sd["tileBox"], sd["tsClipped"], sd["delta"]))
        pd.screenshot(os.path.join(SHOTS, "430_tile_compare.png"))
        pd.close()
        p2 = new_page(b, port, hist_rich, rows, cache=ud_blob(), w=360, h=780, mobile=True)
        open_power(p2)
        wait_delta(p2)
        scroll_tile(p2)
        s360 = snapshot(p2)
        T("D3b 360 手机比例：比较行完整可见（tile 内无裁切）",
          s360["cmpLine"] and (not s360["cmpClipped"]),
          (s360["cmpBox"], s360["tileBox"], s360["delta"]))
        p2.screenshot(os.path.join(SHOTS, "360_tile_compare.png"))
        pick_range(p2, "30d")
        T("D3 360 无横向溢出（24h 隐藏时按钮行不撑破）", snapshot(p2)["overflow"] == 0, snapshot(p2)["overflow"])
        p2.screenshot(os.path.join(SHOTS, "360_30d.png"))
        p2.close()
        p4 = new_page(b, port, hist_rich, rows, cache=ud_blob(), w=390, h=844, mobile=True)
        open_power(p4)
        wait_delta(p4)
        scroll_tile(p4)
        s390 = snapshot(p4)
        T("D4 390 手机比例：「较昨日同期」比较行完整显示（在 tile 矩形内、无 ts 裁切）",
          s390["cmpLine"] and (not s390["cmpClipped"]) and (not s390["tsClipped"]),
          (s390["cmpBox"], s390["tileBox"], s390["tsClipped"]))
        T("D5 390 比较文案与百分比完整（较昨日同期 + N%）",
          "较昨日同期" in (s390["delta"] or "") and delta_pct(s390["delta"]) is not None
          and s390["cmpBox"] is not None and s390["cmpBox"]["h"] > 8,
          (s390["delta"], s390["cmpBox"]))
        T("D6 390 比较行不破坏布局（无横向溢出）", s390["overflow"] == 0, s390["overflow"])
        p4.screenshot(os.path.join(SHOTS, "390_tile_compare.png"))
        p4.close()
        p3 = new_page(b, port, hist_rich, rows, cache=ud_blob(), w=1280, h=900, mobile=False)
        open_power(p3)
        pick_range(p3, "7d")
        p3.screenshot(os.path.join(SHOTS, "1280_7d.png"))
        p3.close()

        # ================= E. 充值折算趋势（2026-11-12 用户反馈） =================
        print("\n== E 充值后趋势可读（已折算充值跳变） ==")
        hist_rech = {}
        for k, v in hist_rich.items():
            hist_rech[k] = [dict(x) for x in v]
        cut = now - 3 * 3600 * 1000
        for pt in hist_rech[REAL_ROOM]:
            ts = int(datetime.fromisoformat(pt["ts"]).timestamp() * 1000)
            if ts >= cut:
                pt["quantity"] = round(float(pt["quantity"]) + 30.0, 4)   # 模拟充值 +30 度
        pr = new_page(b, port, hist_rech, rows, cache=ud_blob(), w=1280, h=900)
        open_power(pr)
        time.sleep(1.2)
        extra = pr.evaluate("""(function(){
          var q=function(s){return document.querySelector(s);};
          var yl=[].map.call(document.querySelectorAll('#pwYAxis .pw-ylab'),function(x){return parseFloat(x.textContent);});
          return {title:(q('#pwTrendTitle')||{}).textContent||'',
            chipVisible:!!(q('#pwRecharge')&&!q('#pwRecharge').hidden),
            chipText:(q('#pwRecharge')||{}).textContent||'',
            legend:(q('#pwLegend')||{}).textContent||'',
            rline:document.querySelectorAll('#pwTrend .pw-rline').length,
            yl:yl, errs:(window.__errs||[]).slice(-3)};
        })()""")
        pr.screenshot(os.path.join(SHOTS, "1280_recharge_adjusted.png"))
        T("E1 充值区间：标题标注「已折算充值」", "已折算充值" in (extra["title"] or ""), extra["title"])
        T("E2 充值徽标可见且说明折算", extra["chipVisible"] and "充值" in (extra["chipText"] or ""), extra["chipText"])
        T("E3 图例显示充值金额（约 +30 度，已折算）",
          bool(re.search(r"充值 \+2[89]\.\d+ 度（已折算）", extra["legend"] or "")), extra["legend"][:120])
        T("E4 图上标出充值位置竖线", int(extra["rline"]) >= 1, extra["rline"])
        ys = [x for x in (extra["yl"] or []) if x == x]
        T("E5 y 轴按折算后用电范围显示（不再被 +30 度撑满）", bool(ys) and (max(ys) - min(ys)) <= 10, extra["yl"])
        T("E6 充值折算页 0 JS 报错", not extra["errs"], extra["errs"])
        pr.close()
    finally:
        b.close()
        srv.shutdown()

    print("\n== 截图 ==")
    for f in sorted(os.listdir(SHOTS)):
        print("  " + os.path.join(SHOTS, f))
    print("\n============================================================")
    print("v2_power_trend_compare_check: PASS %d / FAIL %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：")
        for x in FAILS:
            print("  - " + x)
    print("============================================================")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
