# -*- coding: utf-8 -*-
"""电费关注宿舍同步加固回归（无基线/首开/推送未完成/离开页面 flush/同步状态）

覆盖：
  A. 无 UD 基线（新 WebView/清缓存）：选宿舍 → 触发 userdata POST，blob.power.sel 正确；重开恢复。
  B. boot pull 失败（userdata GET 500）：选宿舍 → 重开（新页面）从本机兜底恢复，并自动补推上云。
  C. 选完立即 pagehide：flush 尽力推送（不依赖 1200ms 防抖）。
  D. 同步状态：失败时「未同步 · 点重试」，点后恢复「已同步」。
  E. 正常路径不回归 + 0 JS 报错。
云端 mock 用 localStorage `__cloud_ud` 跨页面持久；失败开关 `__udFailGet/__udFailPost` 计数。
用法：cd C:\\...\\web\\tools && python tests\\v2_power_sync_hardening_check.py
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
    print("[v2_power_sync_hardening_check] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("power_check", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

EDGE = pc.EDGE
HTTP_PORT = 8967
CDP_PORT = 9467
BASE = "http://127.0.0.1:%d/" % HTTP_PORT
SID = "9999000004"  # 用户反馈中 power 为 NULL 的账号之一
PV = "_psync_preview.html"
RESULTS = []


def T(key, ok, note=""):
    RESULTS.append({"k": key, "ok": bool(ok)})
    print(("[PASS] " if ok else "[FAIL] ") + key + ((" | " + str(note)) if note != "" else ""))


MOCK = r"""
(function(){
  window.__reqs=[];window.__udPosts=[];window.__errs=[];
  window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||e));});
  var SID="__SID__",NM="测试同学";
  function qv(k,d){try{var m=String(location.search||"").match(new RegExp("[?&]"+k+"=([^&]*)"));return m?decodeURIComponent(m[1]):d;}catch(e){return d;}}
  SID=qv("sid",SID);
  try{
    localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token-"+SID,sid:SID,name:NM,role:"",badge:"",is_admin:false,ts:Date.now()}));
    if(!localStorage.getItem("zq_tools_v2_"+SID))localStorage.setItem("zq_tools_v2_"+SID,JSON.stringify({homeTools:["draw","hw","nt","tt"]}));
  }catch(e){}
  function resp(obj,status){
    status=status||200;
    return Promise.resolve({ok:status>=200&&status<300,status:status,
      json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve(JSON.stringify(obj));}});
  }
  function flag(k){try{return Number(localStorage.getItem(k)||0)||0;}catch(e){return 0;}}
  function consume(k){var n=flag(k);if(n>0){try{localStorage.setItem(k,String(n-1));}catch(e){}return true;}return false;}
  function cloudRead(){try{return JSON.parse(localStorage.getItem("__cloud_ud")||"null");}catch(e){return null;}}
  function cloudWrite(row){try{localStorage.setItem("__cloud_ud",JSON.stringify(row));}catch(e){}}
  var _f=window.fetch;
  window.fetch=function(u,o){
    var s=String((u&&u.url!==undefined)?u.url:u);
    var m=String((o&&o.method)||"GET").toUpperCase();
    if(s.indexOf("tcloudbasegateway")<0){
      if(s.indexOf("tt.json")>=0)return resp({c:[],t:"",meta:{}});
      return _f.apply(this,arguments);
    }
    window.__reqs.push({url:s,method:m,body:(o&&o.body)?String(o.body):""});
    if(s.indexOf("/userdata")>=0){
      if(m==="GET"){
        if(consume("__udFailGet"))return resp("err",500);
        var row=cloudRead();
        var dly=flag("__udDelayGetMs");
        if(dly>0){
          try{localStorage.setItem("__udDelayGetMs","0");}catch(e){}
          return new Promise(function(res){setTimeout(function(){res(resp(row?[row]:[]));},dly);});
        }
        return resp(row?[row]:[]);
      }
      if(consume("__udFailPost"))return resp("err",500);
      var arr=[];try{arr=JSON.parse(String((o&&o.body)||"[]"));}catch(e){}
      var r=(arr&&arr[0])||{};
      if(r&&r.id!=null&&r.blob!=null){
        var rec={id:String(r.id),blob:String(r.blob),ts:Number(r.ts)||Date.now()};
        cloudWrite(rec);
        try{window.__udPosts.push(JSON.parse(String(r.blob)));}catch(e){window.__udPosts.push(null);}
        return resp([rec]);
      }
      return resp([]);
    }
    if(s.indexOf("/power_history")>=0){
      var now=Date.now();
      return resp([
        {ts:new Date(now-8*3600e3).toISOString(),quantity:100.5},
        {ts:new Date(now-6*3600e3).toISOString(),quantity:99.2},
        {ts:new Date(now-4*3600e3).toISOString(),quantity:98.4},
        {ts:new Date(now-2*3600e3).toISOString(),quantity:97.1},
        {ts:new Date(now-0.2*3600e3).toISOString(),quantity:96.0}
      ]);
    }
    if(s.indexOf("/power")>=0){
      var pv="4-23A---321";
      try{var pm=s.match(/[?&]id=eq\.([^&]+)/);if(pm)pv=decodeURIComponent(pm[1]);}catch(e){}
      return resp([{id:pv,label:"测试宿舍",building:"23号楼A座",room:"321",quantity:96.0,unit:"度",low:false,
        updated_at:"2026-11-06T12:00:00+08:00"}]);
    }
    if(s.indexOf("rpc/class_members")>=0)return resp([{seat:1,sid:SID,name:NM,role:"",badge:"",is_admin:false}]);
    if(s.indexOf("rpc/class_verify")>=0)return resp({ok:true,token:"mock-token-"+SID,sid:SID,name:NM,role:"",badge:"",is_admin:false});
    if(s.indexOf("/marks")>=0)return resp([]);
    if(s.indexOf("/notices")>=0)return resp([]);
    if(s.indexOf("/homework")>=0)return resp([]);
    if(s.indexOf("/fitrecs")>=0)return resp([]);
    if(s.indexOf("/visits")>=0)return resp([]);
    if(s.indexOf("/feedback")>=0)return resp([]);
    return resp([]);
  };
})();
"""


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


BOOT_READY = ("(function(){var b=document.querySelector('#tabsBar button');"
              "return !!(b&&document.querySelector('section.on')&&!document.body.classList.contains('id-locked'));})()")


def build_preview():
    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8", newline="").read()
    mock = MOCK.replace("__SID__", SID)
    html = html.replace("<head>", "<head><script>" + mock + "</script>", 1)
    open(os.path.join(HERE, PV), "w", encoding="utf-8", newline="").write(html)


def set_flag(cdp, key, v):
    cdp.eval("(function(){try{localStorage.setItem('%s','%s');return true;}catch(e){return false;}})()" % (key, str(v)))


def clear_cloud(cdp):
    cdp.eval("(function(){try{localStorage.removeItem('__cloud_ud');localStorage.removeItem('__udFailGet');localStorage.removeItem('__udFailPost');return true;}catch(e){return false;}})()")


def cloud(cdp):
    return cdp.eval("(function(){try{return JSON.parse(localStorage.getItem('__cloud_ud')||'null');}catch(e){return null;}})()")


def posts(cdp):
    return cdp.eval("Array.isArray(window.__udPosts)?window.__udPosts.slice():[]") or []


def last_power_sel(cdp):
    ps = posts(cdp)
    for b in reversed(ps):
        if isinstance(b, dict) and isinstance(b.get("power"), dict):
            return str(b["power"].get("sel") or "")
    return ""


def wait_power_post(cdp, sel, timeout=12):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if last_power_sel(cdp) == sel:
            return True
        time.sleep(0.2)
    return False


def open_power(cdp):
    cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();return !!b;})()")
    time.sleep(0.4)
    cdp.eval("(function(){var b=document.querySelector('#allCards [data-open=\"power\"]');if(b)b.click();return !!b;})()")
    time.sleep(0.9)


def pick(cdp, rv):
    return cdp.eval("(function(){var s=document.getElementById('pwSelect');if(!s)return false;"
                    "s.value='%s';s.dispatchEvent(new Event('change',{bubbles:true}));return true;})()" % rv)


def sel_value(cdp):
    return cdp.eval("(function(){var s=document.getElementById('pwSelect');return s?s.value:'';})()")


def badge(cdp):
    return cdp.eval("""(function(){var e=document.getElementById('pwSync');if(!e)return null;
      return {hidden:!!e.hidden,text:String(e.textContent||'').trim(),cls:String(e.className||''),
              ds:String(e.getAttribute('data-sync')||'')};})()""")


def boot(cdp, wait=1.4):
    ok = wait_until(cdp, BOOT_READY, 30)
    if not ok:
        try:
            print("[boot diag]", cdp.eval("(function(){return {url:location.href,ready:document.readyState,cls:(document.body?String(document.body.className):''),tabs:document.querySelectorAll('#tabsBar button').length,locked:(document.body?document.body.classList.contains('id-locked'):null)};})()"))
        except Exception as e:
            print("[boot diag err]", str(e)[:200])
        return False
    time.sleep(wait)
    return True


def reload(cdp, wait=1.4):
    cdp.send("Page.reload", {"ignoreCache": False})
    return boot(cdp, wait)


def run(cdp):
    # 干净环境
    cdp.send("Storage.clearDataForOrigin", {"origin": BASE.rstrip("/"), "storageTypes": "all"})
    # 首次加载让 boot UD.pull 失败 1 次：保证进入电费页时确实「无 UD 基线」
    sid0 = cdp.send("Page.addScriptToEvaluateOnNewDocument", {
        "source": "try{localStorage.setItem('__udFailGet','99');}catch(e){}"})["identifier"]
    cdp.send("Page.navigate", {"url": BASE + "tests/" + PV + "?sid=" + SID})
    T("A0 启动完成", boot(cdp, 1.0), "")

    # ===== A. 无 UD 基线 → 选宿舍 → 立即上云 =====
    T("A1 初始无 UD 基线缓存", not bool(cdp.eval("(function(){try{return localStorage.getItem('zq_udcache_%s');}catch(e){return null;}})()" % SID)), "")
    cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": sid0})
    set_flag(cdp, "__udFailGet", 0)
    open_power(cdp)
    pick(cdp, "4-23A---321")
    okA = wait_power_post(cdp, "4-23A---321", 12)
    T("A2 无基线选宿舍 → 触发 userdata POST", okA, json.dumps([p.get("power") if isinstance(p, dict) else None for p in posts(cdp)][-3:], ensure_ascii=False))
    blob = None
    for b in posts(cdp):
        if isinstance(b, dict) and isinstance(b.get("power"), dict):
            blob = b
    T("A3 blob.power.sel 正确 + 14 键契约（含 water）", bool(blob) and blob["power"].get("sel") == "4-23A---321" and len(blob.keys()) == 14 and "water" in blob,
      json.dumps(blob.get("power") if blob else None, ensure_ascii=False))
    cdp.eval("(function(){try{return localStorage.getItem('zq_udcache_%s');}catch(e){return null;}})()" % SID)
    cdp.send("Page.reload", {"ignoreCache": False})
    T("A4 重开完成", boot(cdp), "")
    open_power(cdp)
    T("A5 重开后从云端恢复关注宿舍", sel_value(cdp) == "4-23A---321", sel_value(cdp))
    T("A6 云端 blob.power.sel=321", bool(cloud(cdp)) and json.loads(cloud(cdp).get("blob") or "{}").get("power", {}).get("sel") == "4-23A---321",
      str(cloud(cdp))[:160])

    # ===== B. boot pull 失败 → 选宿舍 → 重开恢复并补推 =====
    clear_cloud(cdp)
    set_flag(cdp, "__udFailGet", 99)
    if not reload(cdp):
        T("B1 重开（pull 失败）", False, "boot timeout")
        return
    T("B1 boot pull 失败场景启动", True, "")
    open_power(cdp)
    pick(cdp, "4-23A---324")
    time.sleep(2.2)
    T("B2 pull 失败时选宿舍：本机兜底已写入", cdp.eval("(function(){try{return localStorage.getItem('zq_power_sel_%s')||'';}catch(e){return '';}})()" % SID) == "4-23A---324",
      cdp.eval("(function(){try{return localStorage.getItem('zq_power_sel_%s')||'';}catch(e){return '';}})()" % SID))
    set_flag(cdp, "__udFailGet", 0)
    if not reload(cdp):
        T("B3 重开恢复", False, "boot timeout")
        return
    open_power(cdp)
    T("B3 重开后从本机兜底恢复关注宿舍", sel_value(cdp) == "4-23A---324", sel_value(cdp))
    okB = wait_power_post(cdp, "4-23A---324", 12)
    T("B4 恢复后自动补推上云（blob.power.sel=324）", okB, json.dumps([p.get("power") if isinstance(p, dict) else None for p in posts(cdp)][-2:], ensure_ascii=False))

    # ===== C. 选完立即 pagehide → flush =====
    clear_cloud(cdp)
    if not reload(cdp):
        T("C0 重开", False, "boot timeout")
        return
    open_power(cdp)
    time.sleep(2.2)  # 等 boot pull 建立基线
    set_flag(cdp, "__udFailGet", 1)  # 让 pick 的即时 push 失败一次（GET 失败），仅剩 pagehide flush 可成功
    pick(cdp, "4-23A---324")
    time.sleep(0.05)
    cdp.eval("(function(){try{window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:false}));return true;}catch(e){return String(e);}})()")
    okC = wait_power_post(cdp, "4-23A---324", 5)
    T("C1 选完立即 pagehide：flush 推送成功", okC, json.dumps([p.get("power") if isinstance(p, dict) else None for p in posts(cdp)][-2:], ensure_ascii=False))

    # ===== D. 同步状态：失败→未同步，点重试→已同步 =====
    clear_cloud(cdp)
    set_flag(cdp, "__udFailGet", 99)
    set_flag(cdp, "__udFailPost", 99)
    if not reload(cdp):
        T("D0 重开", False, "boot timeout")
        return
    open_power(cdp)
    pick(cdp, "4-23A---321")
    time.sleep(2.0)
    b1 = badge(cdp)
    T("D1 同步失败时显示「未同步 · 点重试」", bool(b1) and not b1["hidden"] and "未同步" in b1["text"] and b1["ds"] == "0",
      json.dumps(b1, ensure_ascii=False))
    set_flag(cdp, "__udFailGet", 0)
    set_flag(cdp, "__udFailPost", 0)
    cdp.eval("(function(){var e=document.getElementById('pwSync');if(e)e.click();return !!e;})()")
    okD = wait_power_post(cdp, "4-23A---321", 12)
    T("D2 点重试后推送成功", okD, json.dumps([p.get("power") if isinstance(p, dict) else None for p in posts(cdp)][-2:], ensure_ascii=False))
    t0 = time.time()
    b2 = None
    while time.time() - t0 < 6:
        b2 = badge(cdp)
        if b2 and "已同步" in b2["text"]:
            break
        time.sleep(0.2)
    T("D3 同步成功后状态「已同步」", bool(b2) and "已同步" in b2["text"] and b2["ds"] == "1", json.dumps(b2, ensure_ascii=False))

    # ===== E. 正常路径不回归 =====
    clear_cloud(cdp)
    if not reload(cdp):
        T("E0 重开", False, "boot timeout")
        return
    open_power(cdp)
    pick(cdp, "4-23A---321")
    T("E1 正常选择后刷新按钮可用", cdp.eval("(function(){var r=document.getElementById('pwRefresh');return !!(r&&!r.disabled);})()"), "")
    T("E2 正常路径选择写兜底键", cdp.eval("(function(){try{return localStorage.getItem('zq_power_sel_%s')||'';}catch(e){return '';}})()" % SID) == "4-23A---321", "")
    # ===== F. boot pull 延迟竞态：响应到达前选宿舍，本地/云端/ POST 都必须是新选择 =====
    cdp.send("Storage.clearDataForOrigin", {"origin": BASE.rstrip("/"), "storageTypes": "all"})
    old_blob = {"v": 6,
                "at": {"homeTools": 0, "fit": 0, "draw": 0, "group": 0, "roster": 0, "hide": 0, "tt": 0,
                       "prefs": 0, "nick": 0, "power": 1700000000000},
                "homeTools": ["draw", "hw", "nt", "tt"], "fit": {}, "draw": {}, "group": {},
                "roster": {"rosterSel": [], "rollSel": [], "rollSt": {}, "rollNames": ""},
                "hide": {"hwHide": {}, "ntHide": {}},
                "tt": {"ttView": "", "ttUseMine": False, "ttLocal": None, "termStart": ""},
                "prefs": {"hwRemind": {}, "ntSub": False, "ntSubAt": 0},
                "nick": "", "power": {"sel": "1-16---305", "at": 1700000000000, "low": 30},
                "homeToolsAt": 0}
    cloud_row = {"id": SID, "blob": json.dumps(old_blob, ensure_ascii=False), "ts": 1700000000000}
    src_script = ("try{localStorage.setItem('__cloud_ud',JSON.stringify(%s));"
                  "localStorage.setItem('__udDelayGetMs','2500');}catch(e){}"
                  % json.dumps(cloud_row, ensure_ascii=False))
    sidF = cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": src_script})["identifier"]
    cdp.send("Page.navigate", {"url": BASE + "tests/" + PV + "?sid=" + SID})
    T("F0 延迟 boot pull 场景启动", boot(cdp, 0.5), "")
    open_power(cdp)
    pick(cdp, "4-23A---324")  # boot GET 仍延迟中
    time.sleep(0.3)
    T("F1 竞态中立即选宿舍：本机选择已是新宿舍", sel_value(cdp) == "4-23A---324", sel_value(cdp))
    time.sleep(4.5)  # 等延迟响应到达 + pull/merge/push
    T("F2 boot pull 回来未覆盖本机新选择", sel_value(cdp) == "4-23A---324", sel_value(cdp))
    T("F3 POST body 为新选宿舍（云端旧值不赢）", last_power_sel(cdp) == "4-23A---324",
      json.dumps([p.get("power") if isinstance(p, dict) else None for p in posts(cdp)][-3:], ensure_ascii=False))
    cl = cloud(cdp)
    cl_sel = ""
    try:
        cl_sel = json.loads(cl.get("blob") or "{}").get("power", {}).get("sel", "")
    except Exception:
        pass
    T("F4 云端 blob.power.sel 已更新为新选宿舍", cl_sel == "4-23A---324", str(cl)[:160])
    bF = badge(cdp)
    T("F5 竞态后同步状态「已同步」", bool(bF) and "已同步" in bF["text"], json.dumps(bF, ensure_ascii=False))
    cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": sidF})

    # ===== G. 无基线 + 选完立即 pagehide（flush 尽力；重开后恢复并补推） =====
    cdp.send("Storage.clearDataForOrigin", {"origin": BASE.rstrip("/"), "storageTypes": "all"})
    sidG = cdp.send("Page.addScriptToEvaluateOnNewDocument", {
        "source": "try{localStorage.setItem('__udFailGet','99');}catch(e){}"})["identifier"]
    cdp.send("Page.navigate", {"url": BASE + "tests/" + PV + "?sid=" + SID})
    T("G0 无基线+失败场景启动", boot(cdp, 1.0), "")
    open_power(cdp)
    pick(cdp, "4-23A---321")
    time.sleep(0.05)
    cdp.eval("(function(){try{window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:false}));return true;}catch(e){return String(e);}})()")
    time.sleep(1.0)
    T("G1 无基线+pagehide 时本机兜底已写入", cdp.eval("(function(){try{return localStorage.getItem('zq_power_sel_%s')||'';}catch(e){return '';}})()" % SID) == "4-23A---321", "")
    cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": sidG})
    set_flag(cdp, "__udFailGet", 0)
    cdp.send("Page.reload", {"ignoreCache": False})
    T("G2 重开（网络恢复）完成", boot(cdp), "")
    open_power(cdp)
    T("G3 重开后从本机兜底恢复", sel_value(cdp) == "4-23A---321", sel_value(cdp))
    T("G4 恢复后补推上云（POST power.sel=321）", wait_power_post(cdp, "4-23A---321", 12),
      json.dumps([p.get("power") if isinstance(p, dict) else None for p in posts(cdp)][-2:], ensure_ascii=False))

    errs = cdp.eval("JSON.stringify(window.__errs||[])")
    T("E3 0 JS 报错", errs == "[]", errs[:300])


def main():
    build_preview()
    devnull = open(os.devnull, "wb")
    prof = tempfile.mkdtemp(prefix="edgeprof_psync_")
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
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844,
                                                        "deviceScaleFactor": 2, "mobile": True})
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
        for fn in (PV,):
            try:
                os.remove(os.path.join(HERE, fn))
            except Exception:
                pass
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 60)
    print("v2_power_sync_hardening_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
