# -*- coding: utf-8 -*-
"""task-27 B/C/E：返回键、登录闪烁（auth-pending）、首屏性能对比、安全静态审计

B. tab 切换写 history；history.back() 回上一 tab（不离开页面）；
   根层返回提示「再按一次返回退出」；名单弹层打开时返回先关弹层。
C. 无缓存（未登录）：首帧 body.auth-pending、主内容隐藏、门禁第一帧就在；
   已登录：不出现 id-locked/门禁闪烁，主内容在身份完成后显示。
E. 首屏性能：与改动前备份（_backup/...preTask27）对比 DCL / load / 首屏可交互 / 首屏请求数；
   安全静态审计：eval/new Function、内联事件、postMessage source 校验、iframe sandbox、
   外部链接 rel、token 出现在 URL/console 等。
用法：cd C:\\...\\web\\tools && python tests\\v2_back_auth_perf_security_check.py
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
    print("[v2_back_auth_perf_security_check] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("power_check", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

EDGE = pc.EDGE
HTTP_PORT = 8969
CDP_PORT = 9469
BASE = "http://127.0.0.1:%d/" % HTTP_PORT
SID = pc.SID_A
RESULTS = []
PERF = {}


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


BOOT = "(function(){var b=document.querySelector('#tabsBar button');return !!b&&!document.body.classList.contains('id-locked');})()"
RECORDER = r"""
(function(){
  window.__cls=[];window.__readyAt=null;window.__readyReqs=null;window.__firstBody=null;
  function pushBody(){
    var c=document.body?String(document.body.className||""):null;
    if(c!=null&&window.__cls[window.__cls.length-1]!==c)window.__cls.push(c);
    if(c!=null&&window.__firstBody==null)window.__firstBody=c;
  }
  try{
    new MutationObserver(pushBody).observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:["class"]});
  }catch(e){}
  var iv=setInterval(function(){
    try{
      if(document.body)pushBody();
      var b=document.querySelector("#tabsBar button");
      if(b&&window.__readyAt==null){
        window.__readyAt=performance.now();
        window.__readyReqs=(window.__reqs||[]).length;
        clearInterval(iv);
      }
    }catch(e){}
  },8);
})();
"""


def build_variants():
    pc.build_previews()  # 生成 _power_preview.html（注入身份 + mock）
    cur = open(os.path.join(ROOT, "index.html"), encoding="utf-8", newline="").read()
    # 已登录预览：直接复制 pc 产物（identity 在 INJECT 中按 query 注入）
    # 未登录预览：当前 index + 只 mock fetch、不注入身份
    mock_out = r"""
(function(){
  window.__reqs=[];window.__errs=[];
  window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||e));});
  function resp(o,st){st=st||200;return Promise.resolve({ok:st>=200&&st<300,status:st,json:function(){return Promise.resolve(o);},text:function(){return Promise.resolve(JSON.stringify(o));}});}
  var _f=window.fetch;
  window.fetch=function(u,o){
    var s=String((u&&u.url!==undefined)?u.url:u),m=String((o&&o.method)||"GET").toUpperCase();
    if(s.indexOf("tcloudbasegateway")<0){
      if(s.indexOf("tt.json")>=0)return resp({c:[],t:"",meta:{}});
      return _f.apply(this,arguments);
    }
    window.__reqs.push({url:s,method:m,body:(o&&o.body)?String(o.body):""});
    if(s.indexOf("rpc/class_members")>=0)return resp([{seat:1,sid:"__SID__",name:"测试同学",role:"",badge:"",is_admin:false}]);
    if(s.indexOf("rpc/class_verify")>=0)return resp({ok:false,reason:"测试环境不验证"});
    if(s.indexOf("/visits")>=0)return resp([],201);
    return resp([]);
  };
})();
""".replace("__SID__", SID)
    out_html = cur.replace("<head>", "<head><script>" + mock_out + "</script>", 1)
    open(os.path.join(HERE, "_t27_preview_out.html"), "w", encoding="utf-8", newline="").write(out_html)
    # 基线（改动前备份）预览：同样注入 pc 的 INJECT（身份 + mock）
    base_src = os.path.join(ROOT, "_backup", "index_local_20261106_2146_preTask27.html")
    base = open(base_src, encoding="utf-8", newline="").read()
    inject = (pc.INJECT.replace("__SID_A__", pc.SID_A).replace("__NAME__", pc.NAME)
              .replace("__ROWS__", json.dumps(pc.ROWS, ensure_ascii=False))
              .replace("__HIST__", json.dumps(pc.HIST, ensure_ascii=False))
              .replace("__CATALOG__", json.dumps([[c[0], c[1], c[2]] for c in pc.CATALOG], ensure_ascii=False)))
    base_out = base.replace("<head>", "<head>" + inject, 1)
    open(os.path.join(HERE, "_t27_preview_base.html"), "w", encoding="utf-8", newline="").write(base_out)


def install_recorder(cdp):
    return cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": RECORDER})["identifier"]


def tab_click(cdp, k):
    return cdp.eval("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"%s\"]');if(b)b.click();return !!b;})()" % k)


def cur_section(cdp):
    return cdp.eval("(function(){var s=document.querySelector('section.on');return s?s.id:'';})()")


def hist_back(cdp, n=1):
    for _ in range(n):
        cdp.eval("history.back()")
        time.sleep(0.35)


def run_back(cdp):
    cdp.send("Page.navigate", {"url": BASE + "tests/" + "_power_preview.html?sid=" + SID + "&name=%E6%B5%8B%E8%AF%95%E5%90%8C%E5%AD%A6"})
    T("B0 已登录启动完成", wait_until(cdp, BOOT, 30), "")
    time.sleep(1.0)
    tab_click(cdp, "hw"); time.sleep(0.6)
    tab_click(cdp, "nt"); time.sleep(0.7)
    T("B1 切到通知 tab", cur_section(cdp) == "s-nt", cur_section(cdp))
    hist_back(cdp, 1)
    T("B2 返回键回到上一 tab（作业），不离开页面", cur_section(cdp) == "s-hw" and "tests/_power_preview" in str(cdp.eval("location.href")),
      cur_section(cdp) + " / " + str(cdp.eval("location.href"))[-40:])
    hist_back(cdp, 1)
    T("B3 再返回回到抽签 tab", cur_section(cdp) == "s-draw", cur_section(cdp))
    # 根层返回：首次提示，不离开页面
    url0 = str(cdp.eval("location.href"))
    hist_back(cdp, 1)
    toast_txt = cdp.eval("(function(){var t=document.getElementById('toast');return t?String(t.textContent||''):'';})()")
    T("B4 根层返回提示「再按一次返回退出」且不离开页面",
      ("再按一次返回退出" in toast_txt) and str(cdp.eval("location.href")) == url0,
      toast_txt + " / " + str(cdp.eval("location.href"))[-30:])
    # 弹层：名单弹层打开时返回先关弹层
    cdp.send("Page.navigate", {"url": BASE + "tests/" + "_power_preview.html?sid=" + SID + "&name=%E6%B5%8B%E8%AF%95%E5%90%8C%E5%AD%A6"})
    wait_until(cdp, BOOT, 30); time.sleep(1.0)
    cdp.eval("(function(){var b=document.getElementById('aRosterPick');if(b)b.click();return !!b;})()")
    opened = wait_until(cdp, "(function(){var m=document.getElementById('rosterModal');return !!m&&m.style.display!=='none';})()", 8)
    T("B5 打开名单弹层", opened, "")
    hist_back(cdp, 1)
    closed = cdp.eval("(function(){var m=document.getElementById('rosterModal');return !m||m.style.display==='none'||!m.classList.contains('on');})()")
    T("B6 弹层打开时返回先关弹层（不切 tab/不离开页面）", bool(opened) and closed and cur_section(cdp) == "s-draw",
      str(closed) + " / " + cur_section(cdp))


def run_auth_logged_out(cdp, rec_id):
    cdp.send("Storage.clearDataForOrigin", {"origin": BASE.rstrip("/"), "storageTypes": "all"})
    cdp.send("Page.navigate", {"url": BASE + "tests/_t27_preview_out.html"})
    gate = wait_until(cdp, "(function(){var g=document.getElementById('idgate');var b=document.body;return !!g&&b.classList.contains('id-locked')&&b.classList.contains('auth-pending');})()", 20)
    T("C1 未登录：门禁第一帧显示 + body.auth-pending", gate, "")
    wrap_hidden = cdp.eval("(function(){var w=document.querySelector('.wrap');return w?getComputedStyle(w).visibility:'none';})()")
    T("C2 未登录：主内容在身份完成前隐藏（visibility hidden）", wrap_hidden == "hidden", wrap_hidden)
    seq = str(cdp.eval("JSON.stringify(window.__cls||[])"))
    T("C3 未登录：首帧 body class 含 auth-pending", "auth-pending" in seq, seq[:200])


def run_auth_logged_in(cdp, rec_id):
    cdp.send("Storage.clearDataForOrigin", {"origin": BASE.rstrip("/"), "storageTypes": "all"})
    cdp.send("Page.navigate", {"url": BASE + "tests/" + "_power_preview.html?sid=" + SID + "&name=%E6%B5%8B%E8%AF%95%E5%90%8C%E5%AD%A6"})
    T("C4 已登录启动完成", wait_until(cdp, BOOT, 30), "")
    time.sleep(0.8)
    final_cls = str(cdp.eval("document.body.className||''"))
    vis = cdp.eval("(function(){var w=document.querySelector('.wrap');return w?getComputedStyle(w).visibility:'none';})()")
    seq2 = str(cdp.eval("JSON.stringify(window.__cls||[])"))
    T("C5 已登录：结束态无 auth-pending/id-locked、主内容可见",
      "auth-pending" not in final_cls and "id-locked" not in final_cls and vis == "visible", final_cls + " / " + vis)
    T("C6 已登录：加载过程从未出现 id-locked（无门禁闪烁）", "id-locked" not in seq2, seq2[:240])
    src_html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    T("C7 首帧隐藏规则存在：body 初始 auth-pending + CSS 隐藏 .wrap",
      '<body class="auth-pending">' in src_html and 'body.auth-pending .wrap{visibility:hidden}' in src_html, "")


def measure(cdp, file, tag):
    rec = install_recorder(cdp)
    cdp.send("Page.navigate", {"url": BASE + "tests/" + file})
    wait_until(cdp, "window.__readyAt!=null", 30)
    time.sleep(0.8)
    m = cdp.eval("""(function(){
      var n=performance.getEntriesByType('navigation')[0]||{};
      return {dcl:n.domContentLoadedEventEnd||0,load:n.loadEventEnd||0,
        ready:window.__readyAt||0,req:(window.__readyReqs==null?-1:window.__readyReqs),
        totalReq:(window.__reqs||[]).length};
    })()""")
    cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": rec})
    PERF[tag] = m
    return m


def run_perf(cdp):
    b = measure(cdp, "_t27_preview_base.html", "baseline")
    c = measure(cdp, "_power_preview.html?sid=" + SID, "current")
    print("  [perf] baseline:", json.dumps(b), "\n  [perf] current :", json.dumps(c))
    T("E1 首屏 DCL 不明显慢于改动前（≤+200ms）", c["dcl"] <= b["dcl"] + 200, "base=%d cur=%d" % (b["dcl"], c["dcl"]))
    T("E2 首屏可交互不明显慢于改动前（≤+250ms）", c["ready"] <= b["ready"] + 250, "base=%d cur=%d" % (b["ready"], c["ready"]))
    T("E3 首屏请求数不增加（≤+2）", c["req"] >= 0 and c["req"] <= b["req"] + 2, "base=%s cur=%s" % (b["req"], c["req"]))
    T("E4 load 事件不明显慢于改动前（≤+300ms）", c["load"] <= b["load"] + 300, "base=%d cur=%d" % (b["load"], c["load"]))


def run_security():
    src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    T("S1 无 eval( / new Function(（不动态执行字符串）",
      ("eval(" not in src) and ("new Function(" not in src), "")
    m = re.search(r'window\.addEventListener\("message",function\(e\)\{(.{0,1200})', src, re.S)
    handler = m.group(1) if m else ""
    T("S2 postMessage 处理器校验 e.source 为通知 iframe", "e.source" in handler and "NOTICE_FRAME" in handler, "")
    T("S3 postMessage 处理器做同源校验（origin）", "location.origin" in handler and "e.origin" in handler, "")
    T("S4 通知 iframe 带 sandbox", 'sandbox","allow-scripts allow-same-origin' in src, "")
    inline = re.findall(r'<[a-zA-Z][^>]*\son(?:click|error|load|mouseover)\s*=', src)
    T("S5 无内联事件处理器（onclick/onerror/onload 等）", len(inline) == 0, str(inline[:3]))
    has_blank = 'target="_blank"' in src
    T("S6 无 target=\"_blank\" 缺 rel=noopener", (not has_blank) or ('rel="noopener' in src), "target_blank=%s" % has_blank)
    T("S7 token 不出现在页面 URL 查询串/console 日志",
      not re.search(r'(?:location\.(?:search|hash)|console\.(?:log|info|warn|error))[^\n]{0,80}(?:token|X-Device-Id)', src), "")
    T("S8 动态展示用户/云端文本使用转义函数（esc 定义存在且调用≥20 处）", src.count("esc(") >= 20, str(src.count("esc(")))
    T("S9 无 javascript: 伪协议链接", "javascript:" not in src.lower(), "")


def run(cdp):
    r1 = install_recorder(cdp)
    run_auth_logged_out(cdp, r1)
    cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": r1})
    r2 = install_recorder(cdp)
    run_auth_logged_in(cdp, r2)
    cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": r2})
    run_back(cdp)
    run_perf(cdp)
    run_security()


def main():
    build_variants()
    devnull = open(os.devnull, "wb")
    prof = tempfile.mkdtemp(prefix="edgeprof_t27_")
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
        for fn in ("_power_preview.html", "_t27_preview_out.html", "_t27_preview_base.html", pc.COMMON):
            try:
                os.remove(os.path.join(HERE, fn))
            except Exception:
                pass
        shutil.rmtree(pc.REPORT_DIR, ignore_errors=True)
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 60)
    print("v2_back_auth_perf_security_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("perf:", json.dumps(PERF, ensure_ascii=False))
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
