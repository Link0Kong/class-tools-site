# -*- coding: utf-8 -*-
"""v2 通知时间显示与识别 · 线上页面验证（阶段3 ②，真·线上 tool.furina.fun + 测试身份）

做法（只读，不部署、不改产品）：
  1) urllib 下载线上 index.html，核对 sha256=Lead 部署报告值，并存档；
  2) 启动 headless Edge（--remote-debugging-port=0），用 CDP(websocket-client) 打开 https://tool.furina.fun/；
  3) 首次加载后向 localStorage 注入测试身份（**仅测试身份 token**，不打印/不落盘；2026-11-11 用户红线后不再读取真实管理员 token），
     reload → 真实云端拉取 notices → 切到通知 tab（gotoTab('nt')）→ 读取 iframe 内 GROUPS/DOM；
  4) 断言：申报材料合并卡/药膳报名优先/花名册 兰佳杰/献血合并卡/无旧文案与今天混排/0 JS 报错；
     并截图（首屏、申报卡、献血卡）存 C:\\briefdesk\\data\\_qa_nottime\\phase3\\online_ui\\。
env：NTP_UI_OUT（截图/日志目录）、NTP_EDGE。
退出码 0 = 线上页面验证全绿。

用法：cd C:\\Users\\Ko_Li\\.openclaw\\workspace\\web\\tools && python tests\\v2_notice_time_online_ui_check.py
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

EDGE = os.environ.get("NTP_EDGE") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
URL = os.environ.get("NTP_UI_URL") or "https://tool.furina.fun/"
OUT = os.environ.get("NTP_UI_OUT") or r"C:\briefdesk\data\_qa_nottime\phase3\online_ui"
TOKEN_FILE = None   # 政策：不再读取真实管理员 token；改用下方测试身份 token

# 政策（2026-11-11 用户红线）：测试只用测试账号，不再读取真实管理员 token（class-token.json）。
TEST_SID, TEST_NAME = "3260799999", "测试账号"
REST_BASE = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"


def test_identity_token():
    """读取公开 publishable key 后仅用测试身份换取 class token（不打印/不落盘）。"""
    key_path = os.path.join(ROOT, "deploy", "cloudbase", "publish_key.txt")
    key = open(key_path, encoding="utf-8").read().strip()
    body = json.dumps({"p_sid": TEST_SID, "p_name": TEST_NAME}).encode("utf-8")
    req = urllib.request.Request(
        REST_BASE + "rpc/class_verify", data=body, method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        obj = json.loads(r.read().decode("utf-8"))
    tok = str((obj or {}).get("token") or "")
    if not tok:
        raise SystemExit("测试身份 class_verify 失败（未返回 token）")
    return tok

EXPECT_SHA = "b7819e39bc148b7654239bb83ec32d6b067c1e20445169ce4d3d40337359b47f"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

STEPS = []


def S(k, ok, note=""):
    STEPS.append({"k": k, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()


# ---------------------------------------------------------------- 极简 CDP 客户端
class CDP:
    def __init__(self, ws_url):
        import websocket  # websocket-client
        self.ws = websocket.create_connection(ws_url, timeout=60, enable_multithread=True)
        self.n = 0

    def cmd(self, method, params=None, timeout=90):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s: %s" % (method, msg["error"]))
                return msg.get("result") or {}
        raise TimeoutError(method)

    def eval(self, expr, by_value=True, timeout=90):
        r = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": by_value,
                                          "awaitPromise": False}, timeout=timeout)
        return r.get("result", {}).get("value")

    def wait_js(self, expr, timeout=60, interval=0.4):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                v = self.eval(expr, timeout=30)
                if v:
                    return v
            except Exception:
                pass
            time.sleep(interval)
        return None

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def launch_edge(profile):
    args = [EDGE, "--headless=new", "--remote-debugging-port=0", "--user-data-dir=" + profile,
            "--disable-gpu", "--no-first-run", "--hide-scrollbars", "--mute-audio",
            "--window-size=492,940", URL]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_devtools(profile, timeout=60):
    p = os.path.join(profile, "DevToolsActivePort")
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(p):
            lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
            if lines and lines[0].strip().isdigit():
                return int(lines[0].strip())
        time.sleep(0.2)
    return None


def page_ws(port):
    import urllib.request as ur
    t0 = time.time()
    while time.time() - t0 < 30:
        try:
            data = json.loads(ur.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5).read())
            for t in data:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.3)
    return None


# 在页面里取 iframe 内通知数据的 JS（返回 JSON 字符串，避免对象序列化问题）
IFRAME_JS = r"""
(function(){
  function q(s,r){try{return (r||document).querySelector(s)}catch(e){return null}}
  function norm(s){return String(s==null?"":s).replace(/\s+/g," ").trim();}
  var f=q('.notice-frame')||q('#noticeHost iframe');
  if(!f)return JSON.stringify({ok:false,err:'no-iframe'});
  var w=null;try{w=f.contentWindow;}catch(e){}
  var d=null;try{d=f.contentDocument||(w&&w.document);}catch(e){}
  if(!d||!w)return JSON.stringify({ok:false,err:'no-doc'});
  var gs=null;try{gs=w.GROUPS||null;}catch(e){}
  if(!gs)return JSON.stringify({ok:false,err:'no-groups'});
  var out={ok:true,count:gs.length,appVer:(typeof APP_VER!=='undefined'?APP_VER:'')};
  var byId={};gs.forEach(function(g){byId[g.id]=g;});
  function cardOf(id){return q('.gcard[data-gid="'+id+'"]',d);}
  function chipOf(id){var c=cardOf(id);var s=c?q('.st',c):null;return s?norm(s.textContent):null;}
  function cardText(id){var c=cardOf(id);return c?norm(c.textContent):'';}
  function statusOfSafe(g){try{return w.statusOf(g);}catch(e){return {label:'ERR:'+String(e),key:'ERR'};}}
  // 申报材料
  var sb=[];
  gs.forEach(function(g){
    var blob=norm(g.title)+' '+norm(g.aiSummary)+' '+(g.items||[]).map(function(it){return norm(it.text)+' '+norm(it.name);}).join(' ');
    if(blob.indexOf('申报材料')>=0)sb.push(g);
  });
  out.shenbao={count:sb.length,id:sb[0]&&sb[0].id,items:sb[0]?(sb[0].items||[]).length:0,
    chip:sb[0]?chipOf(sb[0].id):null,
    pubname:(function(){var c=sb[0]?cardOf(sb[0].id):null;var e=c?q('.pubname',c):null;return e?norm(e.textContent):null;})(),
    text:sb[0]?cardText(sb[0].id).slice(0,400):''};
  var sbText=sb[0]?cardText(sb[0].id):'';
  out.shenbao.has1106=/11-06/.test(sbText); out.shenbao.has1108=/11-08/.test(sbText);
  out.shenbao.noToday=!/今天 12:00/.test((sb[0]?chipOf(sb[0].id):'')+sbText);
  // 药膳
  var med=byId['g_qqm_7704134971497063025_c0'];
  out.med=med?{id:med.id,chip:chipOf(med.id),signupStart:med.signupStart||'',signupEnd:med.signupEnd||'',
    text:cardText(med.id).slice(0,240)}:null;
  // 手抄报
  var food=null;gs.forEach(function(g){var b=norm(g.title)+' '+(g.items||[]).map(function(it){return norm(it.text);}).join(' ');if(b.indexOf('手抄报')>=0)food=g;});
  out.food=food?{id:food.id,chip:chipOf(food.id),signupEnd:food.signupEnd||''}:null;
  // 药膳手记 c1（Lead 热修回归）
  var c1=byId['g_qqm_7704134971497063025_c1'];
  out.c1=c1?{id:c1.id,chip:chipOf(c1.id),signupStart:c1.signupStart||'',signupEnd:c1.signupEnd||'',
    deadline:c1.deadline||''}:null;
  // 花名册
  var fileg=byId['g_qqfile_1a81286a3a'];
  var fc=fileg?cardOf(fileg.id):null;
  out.file=fileg?{id:fileg.id,senderName:fileg.senderName,senderRole:fileg.senderRole,senderBadge:fileg.senderBadge,
    pubname:fc?norm((fc.querySelector('.pubname')||{}).textContent||''):null,
    badge:fc?norm((fc.querySelector('.pubbadge')||{}).textContent||''):null,
    cardHasTiancheng:cardText(fileg.id).indexOf('天城企鹅')>=0}:null;
  // 献血
  var xx=[];gs.forEach(function(g){if(JSON.stringify(g).indexOf('献血')>=0)xx.push(g);});
  var x=xx[0]||null;
  out.xianxue={count:xx.length,id:x&&x.id,title:x&&x.title,chip:x?chipOf(x.id):null,
    eventAt:x&&x.eventAt,eventAction:x&&x.eventAction,
    items:x?(x.items||[]).map(function(it){return {label:it.label,time:it.time,from:it.from,kind:it.kind,
        text:norm(it.text||it.name||'').slice(0,80),hasUrl:!!it.url,note:norm(it.note||'')};}):[],
    text:x?cardText(x.id).slice(0,400):''};
  // 全部 chip 检查（旧文案/今天混排）
  var bad=[],labels=[];
  gs.forEach(function(g){
    var st=statusOfSafe(g);var lab=norm(st&&st.label);labels.push({id:g.id,label:lab,key:st&&st.key,cat:g.cat});
    if(/今天|明天|后天/.test(lab))bad.push({id:g.id,label:lab,type:'today'});
    ['已截止 · 自动完成','已结束 · 自动归档','已延长 ·'].forEach(function(old){if(lab.indexOf(old)>=0)bad.push({id:g.id,label:lab,type:'old:'+old});});
  });
  out.badChips=bad;
  out.chipTotal=labels.length;
  out.chips=labels;
  out.now=new Date().toString();
  // JS 报错（父页注入的 __qaErrs 会覆盖 iframe 新文档；保险再取 iframe 自带的 __errs）
  var errs=[];
  try{errs=errs.concat(window.__qaErrs||[]);}catch(e){}
  try{errs=errs.concat(w.__qaErrs||[]);}catch(e){}
  try{errs=errs.concat(w.__errs||[]);}catch(e){}
  out.errs=errs;
  return JSON.stringify(out);
})()
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    print("=" * 64)
    print("[online-ui] url=%s time=%s" % (URL, time.strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 64)
    # ---- 1. 下载并核对线上 index.html ----
    try:
        status, body = download(URL)
        idx = body.decode("utf-8", "replace")
        open(os.path.join(OUT, "index_online.html"), "w", encoding="utf-8", newline="").write(idx)
        sha = hashlib.sha256(body).hexdigest()
        S("U0.1 线上 index.html 可下载且 sha256 与部署报告一致（b7819e39…）", sha == EXPECT_SHA,
          "HTTP %s %d bytes sha256=%s（期望 %s）" % (status, len(body), sha[:16], EXPECT_SHA[:16]))
        if sha != EXPECT_SHA:
            S("U0.2 线上文件与部署报告不一致 → 按 Lead 要求先报告、不自行处理", False,
              "线上已变化（可能是另一会话部署），已停止后续页面验证")
            return finish()
    except Exception as e:  # noqa: BLE001
        S("U0.1 线上 index.html 可下载", False, type(e).__name__ + ": " + str(e)[:150])
        return finish()
    # 解码线上模板（顺带核对模板长度）
    m = re.search(r'var NOTICE_TPL_B64="([^"]*)"', idx)
    tpl_len = 0
    if m:
        try:
            tpl_len = len(base64.b64decode(m.group(1)).decode("utf-8", "replace"))
        except Exception:
            tpl_len = -1
    S("U0.3 线上 NOTICE_TPL_B64 解码", tpl_len > 10000, "template=%d bytes" % tpl_len)

    # ---- 2. 读测试身份 token（不打印） ----
    try:
        token = test_identity_token()   # 政策：仅测试账号
        S("U1.1 测试身份 token 可读（不打印）", bool(token) and len(token) > 20, "len=%d" % len(token))
    except Exception as e:  # noqa: BLE001
        S("U1.1 测试身份 token 可读（不打印）", False, type(e).__name__)
        return finish()

    profile = tempfile.mkdtemp(prefix="edgeonline_")
    proc = None
    cdp = None
    try:
        proc = launch_edge(profile)
        port = wait_devtools(profile)
        S("U1.2 Edge DevTools 端口就绪", bool(port), "port=%s" % port)
        if not port:
            return finish()
        ws = page_ws(port)
        if not ws:
            S("U1.3 页面 target 可连接", False)
            return finish()
        cdp = CDP(ws)
        S("U1.3 页面 target 可连接", True, "ws ok")
        cdp.cmd("Page.enable")
        cdp.cmd("Runtime.enable")
        try:
            cdp.cmd("Emulation.setDeviceMetricsOverride",
                    {"width": 492, "height": 940, "deviceScaleFactor": 2, "mobile": True})
        except Exception:
            pass
        # 错误收集（新文档注入，包含后续 reload 与 iframe）
        cdp.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": (
            "window.__qaErrs=[];"
            "window.addEventListener('error',function(e){try{window.__qaErrs.push(String(e.message||e));}catch(_){}});"
            "window.addEventListener('unhandledrejection',function(e){try{window.__qaErrs.push('rej:'+String(e.reason));}catch(_){}});"
            "(function(){var oe=console.error;console.error=function(){try{window.__qaErrs.push('console.error:'+Array.prototype.map.call(arguments,String).join(' '));}catch(_){} return oe.apply(console,arguments);};})();"
        )})
        # 等 gate 页加载
        cdp.wait_js("!!document.querySelector('#igSid')||!!document.querySelector('#s-nt')", timeout=40)
        # 注入测试身份
        ok = cdp.eval("(function(){try{localStorage.setItem('zq_class_identity',JSON.stringify({"
                      "token:%s,sid:'0000000000',name:'QA测试身份',role:'',badge:'',is_admin:false,ts:Date.now()}));"
                      "return true;}catch(e){return 'ERR:'+e;}})()" % json.dumps(token))
        S("U1.4 注入测试身份到 localStorage（token 不外显）", ok is True, str(ok)[:80])
        cdp.cmd("Page.reload", {"ignoreCache": True})
        time.sleep(1.5)
        # 等待 AUTH.ready 或通知数据
        rd = cdp.wait_js("(function(){try{var g=document.getElementById('idgate');"
                         "var hidden=!g||getComputedStyle(g).display==='none'||g.offsetParent===null;"
                         "var locked=document.body.classList.contains('id-locked');"
                         "return hidden&&!locked;}catch(e){return false;}})()", timeout=60)
        S("U1.5 测试身份进入班级（身份门禁已解除）", bool(rd), "")
        # 切到通知 tab（触发云端 notices 拉取 + iframe 渲染）
        switched = cdp.eval("(function(){try{gotoTab('nt');return true;}catch(e){"
                            "try{var b=document.querySelector('#tabsBar button[data-tab=\"nt\"]');if(b){b.click();return true;}}catch(e2){}"
                            "return 'ERR:'+e;}})()")
        S("U2.0 切到通知 tab", switched is True, str(switched)[:100])
        fr = cdp.wait_js("(function(){try{var f=document.querySelector('.notice-frame');"
                         "var d=f&&f.contentDocument;var gs=d&&d.defaultView&&d.defaultView.GROUPS;"
                         "return gs?gs.length:0;}catch(e){return 0;}})()", timeout=120)
        S("U2.1 线上通知 iframe 渲染（云端 notices 已拉到）", bool(fr), "iframe groups=%s" % fr)
        appver = re.search(r'var APP_VER="([^"]+)"', idx)
        S("U2.1b 线上 APP_VER=2.0.0（源码）", bool(appver) and appver.group(1) == "2.0.0",
          appver.group(1) if appver else "not found")

        # ---- 3. 读取 iframe 内断言数据 ----
        raw = cdp.eval(IFRAME_JS, timeout=120)
        data = json.loads(raw) if raw else None
        S("U2.2 iframe 内数据可读", bool(data and data.get("ok")), raw[:160] if raw else "no data")
        if not data or not data.get("ok"):
            return finish()
        S("U2.3 线上页面 now（真实时钟）", bool(data.get("now")), str(data.get("now"))[:40])

        sb = data.get("shenbao") or {}
        S("U3.1 申报材料在线上仅 1 卡（合并）", sb.get("count") == 1, "count=%s id=%s" % (sb.get("count"), sb.get("id")))
        S("U3.2 申报材料 items≥3", (sb.get("items") or 0) >= 3, "items=%s" % sb.get("items"))
        S("U3.3 申报材料 chip=时间+报送姓名截止（无「今天 12:00」）",
          bool(re.match(r"^(?:\d+ (?:分钟后|小时后|天后)|\d{2}-\d{2} \d{2}:\d{2}) 报送姓名截止$", str(sb.get("chip") or "")))
          and bool(sb.get("noToday")), "chip=%s" % sb.get("chip"))
        S("U3.4 申报材料显式 11-06 / 11-08 日期", bool(sb.get("has1106")) and bool(sb.get("has1108")),
          "11-06=%s 11-08=%s" % (sb.get("has1106"), sb.get("has1108")))
        med = data.get("med") or {}
        S("U4.1 药膳 chip 报名优先（报名类动作）",
          bool(re.search(r"(报名开始|报名截止|报名已截止)$", str(med.get("chip") or ""))),
          "chip=%s signup=%s~%s" % (med.get("chip"), med.get("signupStart"), med.get("signupEnd")))
        food = data.get("food") or {}
        S("U4.2 手抄报 chip=报名已截止", bool(re.search(r"报名已截止$", str(food.get("chip") or ""))),
          "chip=%s" % food.get("chip"))
        c1 = data.get("c1") or {}
        S("U4.3 线上药膳手记 c1 chip=11-05 18:00 报名已截止（热修后，非 11-14 报名截止）",
          str(c1.get("chip")) == "11-05 18:00 报名已截止"
          and "2026-11-05T18:00" in str(c1.get("signupEnd")),
          "chip=%s signupEnd=%s deadline=%s" % (c1.get("chip"), c1.get("signupEnd"), c1.get("deadline")))
        fl = data.get("file") or {}
        S("U5.1 花名册 senderName=兰佳杰 / 学习委员", fl.get("senderName") == "兰佳杰"
          and ("学习委员" in str(fl.get("senderRole")) or "班委" in str(fl.get("senderBadge"))),
          "name=%s role=%s badge=%s pubname=%s" % (fl.get("senderName"), fl.get("senderRole"),
                                                   fl.get("senderBadge"), fl.get("pubname")))
        S("U5.2 线上页面不显示「天城企鹅」", fl.get("cardHasTiancheng") is False, "")
        xx = data.get("xianxue") or {}
        items = xx.get("items") or []
        sup = [it for it in items if it.get("label") == "补充通知" and "陈子麒" in str(it.get("from"))]
        link = [it for it in items if it.get("hasUrl") and it.get("kind") == "link"
                and "陈子麒" in str(it.get("from"))]
        note_ok = any("本人转发" in str(it.get("note")) for it in items)
        S("U6.1 献血通知仅 1 卡（合并，无独立新卡）", xx.get("count") == 1,
          "count=%s id=%s title=%s" % (xx.get("count"), xx.get("id"), xx.get("title")))
        S("U6.2 献血卡含本人「补充通知」text item（10:18）+ 可点链接 + note 本人转发",
          len(sup) >= 1 and len(link) >= 1 and note_ok,
          "sup=%d link=%d note本人转发=%s" % (len(sup), len(link), note_ok))
        S("U6.3 献血卡 chip 活动开始（eventAt=11-14）",
          bool(re.search(r"活动开始$", str(xx.get("chip") or ""))) and "2026-11-14" in str(xx.get("eventAt")),
          "chip=%s eventAt=%s" % (xx.get("chip"), xx.get("eventAt")))
        bad = data.get("badChips") or []
        S("U7.1 全部 %s 组 chip 无「今天/明天/后天」混排、无旧文案" % data.get("chipTotal"), len(bad) == 0,
          json.dumps(bad[:6], ensure_ascii=False))
        errs = data.get("errs") or []
        S("U8.1 线上页面 0 JS 报错（父页+iframe）", len(errs) == 0, json.dumps(errs[:8], ensure_ascii=False))

        # ---- 4. 截图 ----
        shots = []

        def shot(name, tries=3):
            last = None
            for _i in range(tries):
                try:
                    r = cdp.cmd("Page.captureScreenshot", {"format": "png", "fromSurface": True},
                                timeout=45)
                    p = os.path.join(OUT, name + ".png")
                    open(p, "wb").write(base64.b64decode(r.get("data") or ""))
                    if os.path.getsize(p) > 5000:
                        shots.append((name, os.path.getsize(p)))
                        return True
                    last = "EMPTY"
                except Exception as e:  # noqa: BLE001
                    last = "ERR:" + type(e).__name__
                time.sleep(0.8)
            shots.append((name, last or "FAIL"))
            return False

        shot("view_top")
        cdp.eval("(function(){try{var f=document.querySelector('.notice-frame');var d=f.contentDocument;"
                 "var c=d.querySelector('.gcard[data-gid=\"g_ait_5396a55f24\"]');"
                 "if(c){var w=f.contentWindow;var y=c.getBoundingClientRect().top+ (w.pageYOffset||0);w.scrollTo(0,y-8);}return true;}catch(e){return 'ERR';}})()")
        time.sleep(0.5)
        shot("view_shenbao")
        cdp.eval("(function(){try{var f=document.querySelector('.notice-frame');var d=f.contentDocument;"
                 "var c=d.querySelector('.gcard[data-gid=\"g_ait_d3117057d2\"]');"
                 "if(c){var w=f.contentWindow;var y=c.getBoundingClientRect().top+(w.pageYOffset||0);w.scrollTo(0,y-8);}return true;}catch(e){return 'ERR';}})()")
        time.sleep(0.5)
        shot("view_xianxue")
        S("U9.1 截图落盘（首屏/申报卡/献血卡）", all(isinstance(s[1], int) and s[1] > 5000 for s in shots),
          json.dumps(shots))
    except Exception as e:  # noqa: BLE001
        S("U9.9 线上页面验证异常", False, type(e).__name__ + ": " + str(e)[:200])
    finally:
        if cdp:
            cdp.close()
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        shutil.rmtree(profile, ignore_errors=True)
    return finish()


def finish():
    total = len(STEPS)
    passed = sum(1 for s in STEPS if s["ok"])
    ts = time.strftime("%Y%m%d-%H%M%S")
    result = {"checkedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "url": URL,
              "passed": passed, "total": total, "steps": STEPS}
    json.dump(result, open(os.path.join(OUT, "online_ui_check_%s.json" % ts), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    lines = ["# 线上页面验证报告（通知时间显示与识别）", "",
             "- 时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
             "- 线上：`%s`（测试身份，token 不落盘）" % URL,
             "- 结果：**%d/%d PASS，%d FAIL**" % (passed, total, total - passed), ""]
    for s in STEPS:
        lines.append("- [%s] %s%s" % ("PASS" if s["ok"] else "FAIL", s["k"],
                                      (" — `" + s["note"] + "`") if s["note"] else ""))
    open(os.path.join(OUT, "online_ui_report.md"), "w", encoding="utf-8").write("\n".join(lines))
    print("=" * 64)
    print("v2_notice_time_online_ui_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("报告：%s" % os.path.join(OUT, "online_ui_report.md"))
    print("=" * 64)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
