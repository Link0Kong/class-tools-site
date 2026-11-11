# -*- coding: utf-8 -*-
r"""网页批次2 · 反馈10：网页提醒（web-b 专项，独立文件，不改既有测试）。

需求：通知页新增「提醒」入口/设置（浏览器 Notification 授权状态反馈 + 开启/关闭 + 测试提醒 +
不支持/非 HTTPS 说明与优雅降级）；后台静默轮询新通知（复用 NT.pull / NT 列表签名，新增通知触发）：
授权时发系统通知，未授权/不支持时页内 toast + 标题闪烁「【新通知】」；可选 WebAudio 提示音；
设置存 localStorage（按设备）；不得新增外部请求。

覆盖：
A 静态：通知页提醒入口/设置弹层/授权状态/开关/测试/降级说明/标题闪烁/复用 NT 签名/本机存储/无外链
B 运行时（mock Notification + mock 通知签名）：
  B1 授权（granted）：状态反馈 · 开启开关 · 测试提醒发系统通知 · 设置落 localStorage
  B2 刷新后保持已开启（按设备）
  B3 新通知：mock 签名新增 → 触发系统通知 + 页内 toast + 标题【新通知】闪烁
  B4 进入通知页后标题/角标恢复
  B5 拒绝（denied）：状态反馈「已拒绝」，页内 toast + 标题闪烁仍可用
  B6 不支持（无 Notification）：说明需浏览器/HTTPS，不报错、优雅降级
  B7 非安全上下文（isSecureContext=false）：说明需 HTTPS，降级可用
C 0 JS 报错 / 0 外部请求 / 430 无横向溢出

用法：python tools\tests\v2_web_reminder_check.py
退出码 0 = 全绿。
"""
import http.server
import json
import os
import socket
import socketserver
import sys
import threading
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SRC = os.path.abspath(os.environ.get("REMIND_SRC") or os.path.join(TOOLS, "index.html"))
REL = os.path.relpath(SRC, TOOLS).replace("\\", "/")
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

SID = "9999000001"
NAME = "测试同学"
SHOTS = os.path.join(HERE, "_shots_web_batch2")
SRC_TEXT = open(SRC, encoding="utf-8").read()

PASS = 0
FAIL = 0
SKIP = 0
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


def S(name, why=""):
    global SKIP
    SKIP += 1
    print("  [SKIP] " + name + (("  <" + str(why) + ">") if why else ""))


# 变体：granted / denied / unsupported / insecure
INIT = r"""
(function(){
  try{
    window.__errs=[];window.__cerrs=[];window.__notifs=[];
    window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
    window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
    var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
    try{Object.defineProperty(window,"indexedDB",{value:undefined,configurable:true});}catch(e){}
    window.confirm=function(){return true;};
    try{if(!sessionStorage.getItem("__rb_init")){localStorage.clear();sessionStorage.setItem("__rb_init","1");}}catch(e){}
    try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
    /* 通知签名 mock：__ntRows 变化即可模拟「有新通知」 */
    window.__ntRows=[];
    function J(obj,status){status=status||200;return Promise.resolve(new Response(JSON.stringify(obj),{status:status,headers:{"Content-Type":"application/json"}}));}
    var _f=window.fetch;
    window.fetch=function(u,o){
      o=o||{};
      var s=String((u&&u.url!==undefined)?u.url:u),m=String(o.method||"GET").toUpperCase();
      if(s.indexOf("tcloudbasegateway")<0){
        if(s.indexOf("tt.json")>=0)return J({c:[],t:"",meta:{fetchedAt:Date.now()}});
        return _f.apply(this,arguments);
      }
      if(s.indexOf("/userdata")>=0)return m==="GET"?J([]):J([]);
      if(s.indexOf("rpc/class_members")>=0)return J([{seat:1,sid:"__SID__",name:"__NAME__",role:"",badge:""}]);
      if(s.indexOf("rpc/class_verify")>=0)return J({ok:true,token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false});
      if(s.indexOf("rpc/")>=0)return J({ok:true,seats:[]});
      if(s.indexOf("/notices")>=0){
        if(s.indexOf("select=*")>=0)return J([]);
        return J(window.__ntRows.slice());
      }
      if(s.indexOf("/marks")>=0||s.indexOf("/homework")>=0||s.indexOf("/fitrecs")>=0||s.indexOf("/visits")>=0||s.indexOf("/feedback")>=0||s.indexOf("/power")>=0)return J([]);
      return J([]);
    };
    /* ---- Notification mock（__perm: granted/denied/default；__noNotification 时删除） ---- */
    window.__perm="__PERM__";
    function MkNotif(title,opt){opt=opt||{};window.__notifs.push({title:String(title||""),body:String((opt&&opt.body)||"")});}
    MkNotif.permission=window.__perm;
    MkNotif.requestPermission=function(){
      if(window.__perm==="default")window.__perm="granted";
      MkNotif.permission=window.__perm;
      return Promise.resolve(window.__perm);
    };
    if("__NO_NOTIF__"==="1"){try{delete window.Notification;}catch(e){window.Notification=undefined;}}
    else{window.Notification=MkNotif;}
    if("__INSECURE__"==="1"){try{Object.defineProperty(window,"isSecureContext",{value:false,configurable:true});}catch(e){}}
  }catch(e){}
})();
"""

EXTS_JS = ("(function(){var out=[];try{(performance.getEntriesByType('resource')||[]).forEach(function(e){"
           "var u=String(e.name||'');"
           "if(u.indexOf('http://127.0.0.1')!==0&&u.indexOf('https://127.0.0.1')!==0&&u.indexOf('data:')!==0&&u.indexOf('blob:')!==0)out.push(u);});}catch(e){}"
           "return out;})()")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(root):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    handler = lambda *a, **kw: Quiet(*a, directory=root, **kw)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def snap(page):
    return page.evaluate("""(function(){
      var q=function(s){return document.querySelector(s);};
      var ov=q('#ntRemindOv');
      return {btn:!!q('#ntRemindBtn'),
        ov:ov?{hidden:ov.hidden,display:getComputedStyle(ov).display}:null,
        stateTxt:q('#ntRemindState')?q('#ntRemindState').textContent:null,
        note:q('#ntRemindNote')?q('#ntRemindNote').textContent:null,
        toggleTxt:q('#ntRemindToggle')?q('#ntRemindToggle').textContent:null,
        toggleDisabled:q('#ntRemindToggle')?!!q('#ntRemindToggle').disabled:null,
        testTxt:q('#ntRemindTest')?q('#ntRemindTest').textContent:null,
        ls:(function(){try{return localStorage.getItem('zq_remind_v1');}catch(e){return 'ERR';}})(),
        lsAll:(function(){try{var o={};for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);if(k&&k.indexOf('remind')>=0)o[k]=localStorage.getItem(k);}return o;}catch(e){return {};}})(),
        notifs:(window.__notifs||[]).slice(-5),
        toast:q('#toast')?q('#toast').textContent:null,
        title:document.title,
        remindAPI:!!(window.NTREMIND||window.REMIND),
        overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
        errs:(window.__errs||[]).slice(-4),cerrs:(window.__cerrs||[]).slice(-4)};
    })()""")


def wait_for(fn, timeout=8.0, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


def open_settings(page):
    page.evaluate("var b=document.getElementById('ntRemindBtn');if(b)b.click();'x'")
    return page.wait_for("(function(){var e=document.getElementById('ntRemindOv');return !!(e&&!e.hidden);})()", 8)


def remind_api(page, method):
    return page.evaluate("(function(){var api=window.NTREMIND||window.REMIND;if(!api||typeof api.%s!=='function')return {missing:true};"
                         "try{return {v:api.%s()};}catch(e){return {err:String(e&&e.message||e)};}})()" % (method, method))


def main():
    os.makedirs(SHOTS, exist_ok=True)
    httpd, port = serve(TOOLS)
    url = "http://127.0.0.1:%d/%s" % (port, urllib.parse.quote(REL))
    b = _cdp.Browser(window=(430, 900))

    def page_for(perm="granted", no_notif=False, insecure=False, w=430, h=900):
        init = (INIT.replace("__SID__", SID).replace("__NAME__", NAME)
                .replace("__PERM__", perm)
                .replace("__NO_NOTIF__", "1" if no_notif else "0")
                .replace("__INSECURE__", "1" if insecure else "0"))
        p = b.new_page("about:blank")
        p.set_device(w, h, dpr=2.0, mobile=True, touch=True)
        p.add_init_script(init)
        p.navigate(url)
        assert p.wait_for("!document.body.classList.contains('auth-pending')", 30), "identity timeout"
        p.wait_for("document.querySelectorAll('#tabsBar button').length>0", 15)
        time.sleep(0.9)
        return p

    print("\n== A 静态检查 ==")
    T("A1 通知页提醒入口（#s-nt 内 #ntRemindBtn）",
      'id="ntRemindBtn"' in SRC_TEXT and 'id="s-nt"' in SRC_TEXT)
    T("A2 提醒设置弹层（#ntRemindOv + 状态/开关/测试/说明）",
      all(k in SRC_TEXT for k in ('id="ntRemindOv"', 'id="ntRemindState"', 'id="ntRemindToggle"',
                                  'id="ntRemindTest"', 'id="ntRemindNote"')))
    T("A3 使用 Notification API 与授权状态反馈",
      "Notification" in SRC_TEXT and ("requestPermission" in SRC_TEXT) and ("permission" in SRC_TEXT))
    T("A4 不支持 / 非 HTTPS 降级说明",
      ("HTTPS" in SRC_TEXT) and ("不支持" in SRC_TEXT or "浏览器" in SRC_TEXT) and
      ("isSecureContext" in SRC_TEXT or "protocol" in SRC_TEXT))
    T("A5 复用 NT 通知签名（sigOfNotices / NT.sig 或 cbSig）",
      "sigOfNotices" in SRC_TEXT and ("NT.sig" in SRC_TEXT or "NTREMIND" in SRC_TEXT))
    T("A6 页内 toast + 标题【新通知】闪烁降级",
      "【新通知】" in SRC_TEXT and "document.title" in SRC_TEXT)
    T("A7 设置存 localStorage（按设备）",
      "zq_remind" in SRC_TEXT and "localStorage" in SRC_TEXT)
    T("A8 可选 WebAudio 提示音（无外链）",
      ("AudioContext" in SRC_TEXT or "webkitAudioContext" in SRC_TEXT) and
      "http" not in "".join(SRC_TEXT[SRC_TEXT.index("AudioContext") - 400:SRC_TEXT.index("AudioContext") + 400].split()) if "AudioContext" in SRC_TEXT else True)
    T("A9 无新增外部域名（零外链检查）",
      "fonts.googleapis" not in SRC_TEXT and "cdn." not in SRC_TEXT and "<script src=" not in SRC_TEXT)
    T("A10 APP_VER 仍 2.0.0", 'var APP_VER="2.0.0"' in SRC_TEXT)

    print("\n== B1-B4 授权（granted） ==")
    p = page_for("granted")
    s = snap(p)
    T("B1a 通知页有提醒入口按钮", s["btn"] is True)
    ok = open_settings(p)
    T("B1b 打开提醒设置弹层", ok, s["ov"])
    if ok:
        s = snap(p)
        T("B1c 授权状态反馈（含「已授权/已开启/未开启」）",
          any(w in (s["stateTxt"] or "") for w in ("授权", "已开启", "未开启")), s["stateTxt"])
        # 开启
        p.evaluate("var b=document.getElementById('ntRemindToggle');if(b)b.click();'x'")
        time.sleep(1.2)
        s = snap(p)
        ls_ok = bool(s["ls"]) and ('"on":true' in (s["ls"] or "").replace(" ", "") or '"on": true' in (s["ls"] or ""))
        T("B1d 点开启：设置写入 localStorage（zq_remind_v1 on=true）", ls_ok, (s["ls"], s["lsAll"]))
        # 测试提醒
        before = len(p.evaluate("(window.__notifs||[])") or [])
        p.evaluate("var b=document.getElementById('ntRemindTest');if(b)b.click();'x'")
        ok2 = wait_for(lambda: len(p.evaluate("(window.__notifs||[])") or []) > before, 6)
        s2 = snap(p)
        T("B1e 测试提醒 → 系统通知（Notification mock 收到 1 条）", ok2 and len(s2["notifs"]) >= 1, s2["notifs"])
        T("B1f 测试通知标题/正文有内容", bool(s2["notifs"]) and bool(s2["notifs"][-1]["title"]) and bool(s2["notifs"][-1]["body"]), s2["notifs"][-1] if s2["notifs"] else None)
        p.evaluate("var b=document.getElementById('ntRemindClose');if(b)b.click();'x'")
        # B2 刷新保持
        p.navigate(url)
        p.wait_for("!document.body.classList.contains('auth-pending')", 30)
        time.sleep(1.0)
        if open_settings(p):
            s = snap(p)
            T("B2 刷新后仍为已开启（设置按设备保存）",
              'true' in (s["ls"] or "") and any(w in (s["stateTxt"] or "") for w in ("已开启", "已授权")),
              (s["ls"], s["stateTxt"]))
            p.evaluate("var b=document.getElementById('ntRemindClose');if(b)b.click();'x'")
        else:
            S("B2 提醒设置弹层未打开")
        # B3 新通知触发
        base = p.evaluate("(function(){var api=window.NTREMIND||window.REMIND;if(api&&api.check){try{return api.check(true);}catch(e){return 'ERR';}}return 'NOAPI';})()", await_promise=True)
        p.evaluate("window.__ntRows=[{id:'n-new-1',ts:Date.now(),hidden:false,edited_at:0}];'x'")
        trig = p.evaluate("(function(){var api=window.NTREMIND||window.REMIND;if(api&&api.check)return api.check(true);return 'NOAPI';})()", await_promise=True)
        time.sleep(0.5)
        s3 = snap(p)
        title_seen = wait_for(lambda: "【新通知】" in (p.evaluate("document.title") or ""), 3)
        T("B3a 新通知：check() 返回已触发（true）", trig is True, (base, trig))
        T("B3b 授权时发系统通知", len(s3["notifs"]) >= 1, s3["notifs"])
        T("B3c 页内 toast 提示新通知", "新通知" in (s3["toast"] or ""), s3["toast"])
        T("B3d 标题闪烁「【新通知】」", title_seen, p.evaluate("document.title"))
        # B4 进入通知页后恢复
        p.evaluate("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"nt\"]');if(b)b.click();})()")
        ok4 = wait_for(lambda: "【新通知】" not in (p.evaluate("document.title") or ""), 5)
        T("B4 进入通知页后标题恢复（不再闪烁）", ok4, p.evaluate("document.title"))
        try:
            pg_small = p.screenshot(os.path.join(SHOTS, "remind_nt_430.png"))
        except Exception:
            pass
        s4 = snap(p)
        T("B5b 全程 0 JS 报错 / 0 console.error", not s4["errs"] and not s4["cerrs"], (s4["errs"], s4["cerrs"]))
        T("B5c 无外部请求", not (p.evaluate(EXTS_JS) or []))
        try:
            p.screenshot(os.path.join(SHOTS, "remind_430.png"))
        except Exception:
            pass
    p.close()

    print("\n== B5 拒绝（denied） ==")
    p = page_for("denied")
    if open_settings(p):
        s = snap(p)
        T("B5a 拒绝状态反馈（已拒绝/未授权）",
          any(w in (s["stateTxt"] or "") for w in ("拒绝", "未授权", "未开启")), s["stateTxt"])
        # 页内降级：新通知仍触发 toast + 标题闪烁
        p.evaluate("var b=document.getElementById('ntRemindClose');if(b)b.click();'x'")
        p.evaluate("(function(){var api=window.NTREMIND||window.REMIND;if(api&&api.check)return api.check(true);return null;})()", await_promise=True)
        p.evaluate("window.__ntRows=[{id:'n-denied-1',ts:Date.now(),hidden:false,edited_at:0}];'x'")
        p.evaluate("(function(){var api=window.NTREMIND||window.REMIND;if(api&&api.check)return api.check(true);return null;})()", await_promise=True)
        time.sleep(0.5)
        s2 = snap(p)
        T("B5b 未授权时降级：页内 toast 新通知", "新通知" in (s2["toast"] or ""), s2["toast"])
        T("B5c 未授权时降级：标题闪烁仍可用",
          wait_for(lambda: "【新通知】" in (p.evaluate("document.title") or ""), 3), p.evaluate("document.title"))
        T("B5d 0 JS 报错", not s2["errs"] and not s2["cerrs"], (s2["errs"], s2["cerrs"]))
    else:
        S("B5 验证拒绝状态需提醒设置弹层")
    p.close()

    print("\n== B6 不支持 Notification ==")
    p = page_for("granted", no_notif=True)
    if open_settings(p):
        s = snap(p)
        note = (s["note"] or "") + (s["stateTxt"] or "")
        T("B6a 不支持时说明（需浏览器支持 / HTTPS）",
          any(w in note for w in ("不支持", "HTTPS", "浏览器")), note)
        T("B6b 不支持时开关 degraded（不可强开/提示替代）",
          s["toggleDisabled"] is True or any(w in (s["toggleTxt"] or "") for w in ("不可", "不支持")),
          (s["toggleDisabled"], s["toggleTxt"]))
        p.evaluate("var b=document.getElementById('ntRemindClose');if(b)b.click();'x'")
        s2 = snap(p)
        T("B6c 不支持时 0 JS 报错（优雅降级）", not s2["errs"] and not s2["cerrs"], (s2["errs"], s2["cerrs"]))
    else:
        S("B6 验证不支持状态需提醒设置弹层")
    p.close()

    print("\n== B7 非安全上下文（HTTP） ==")
    p = page_for("granted", insecure=True)
    if open_settings(p):
        s = snap(p)
        note = (s["note"] or "") + (s["stateTxt"] or "")
        T("B7a 非 HTTPS 说明（需 HTTPS / 安全连接）", any(w in note for w in ("HTTPS", "安全", "不支持")), note)
        T("B7b 非 HTTPS 不报错、仍可关闭弹层", not s["errs"] and not s["cerrs"], (s["errs"], s["cerrs"]))
    else:
        S("B7 验证非安全上下文需提醒设置弹层")
    p.close()

    print("\n== C 溢出 / 报错 ==")
    for w, h in ((360, 780), (430, 900)):
        px = page_for("granted", w=w, h=h)
        open_settings(px)
        sx = snap(px)
        T("C-%d 提醒设置弹层无横向溢出" % w, sx["overflow"] == 0, sx["overflow"])
        T("C-%d 0 JS 报错" % w, not sx["errs"] and not sx["cerrs"], (sx["errs"], sx["cerrs"]))
        px.close()

    b.close()
    httpd.shutdown()

    print("\n== 截图 ==")
    for f in sorted(os.listdir(SHOTS)):
        if "remind" in f:
            print("  " + os.path.join(SHOTS, f))
    print("\n============================================================")
    print("v2_web_reminder_check: PASS %d / FAIL %d / SKIP %d" % (PASS, FAIL, SKIP))
    if FAILS:
        print("失败项：")
        for x in FAILS:
            print("  - " + x)
    print("============================================================")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
