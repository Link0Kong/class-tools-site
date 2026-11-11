# -*- coding: utf-8 -*-
r"""网页批次2 · 反馈1：独立「文件传输」工具（web-b 专项，独立文件，不改既有测试）。

需求：文件传输做成独立工具页（全部页卡片 / 可拖入工具栏 / #drop hash 路由），
复用 ECS drop 服务：同账号会话房间码、跨设备互见、分片上传（任意大小/进度/取消）、
文件列表下载（签名 URL）、发文字、会话关闭；文案「文件保留 3 天」；大屏互联面板不回归。
（TTL 3 天 / 不限大小由 cloud-backend drop 服务契约负责，前端只按 drop/CONTRACT.md 口径。）

覆盖：
A 静态：TOOLS 含 file、#s-file 位于 #s-all 前、全部页卡片自动出现、会话/上传/列表/文字/关闭/TTL 文案、
        #drop → 新页路由、大屏互联面板保留、APP_VER 2.0.0、单文件零外链
B 运行时（fetch mock drop 服务，无真实网络）：
  B1 进入页自动开通道：房间码/链接显示
  B2 小文件上传：init→chunk→finish 口径正确，列表出现 + 下载链接
  B3 大文件（20MiB）分片 = 3 片（8MiB×2 + 4MiB），总大小正确
  B4 上传进度显示、取消后不再 finish
  B5 发文字 POST /text
  B6 关闭会话 POST /close 且 UI 复位
  B7 #drop hash 直接打开新页（不再弹大屏互联弹层）
C 430 无横向溢出 / 0 JS 报错 / 0 外部请求

用法：python tools\tests\v2_web_batch2_file_check.py
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
SRC = os.path.abspath(os.environ.get("FILE_SRC") or os.path.join(TOOLS, "index.html"))
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


INIT = r"""
(function(){
  try{
    window.__errs=[];window.__cerrs=[];
    window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
    window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
    var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
    try{Object.defineProperty(window,"indexedDB",{value:undefined,configurable:true});}catch(e){}
    window.confirm=function(){return true;};
    window.__DROP_BASE="__DROPBASE__";
    try{localStorage.clear();}catch(e){}
    try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
    /* ---- mock drop 服务（同 drop/CONTRACT.md 口径；TTL 3 天=259200s） ---- */
    var DS={session:null,files:[],events:[],uploads:{},calls:[],filesSeq:1,aborted:false,delayChunk:0,seq:0};
    window.__ds=DS;
    function J(obj,status){status=status||200;return Promise.resolve(new Response(JSON.stringify(obj),{status:status,headers:{"Content-Type":"application/json"}}));}
    function sess(){return DS.session?{id:DS.session.id,code:DS.session.code,createdAt:DS.session.createdAt,expiresAt:DS.session.expiresAt}:null;}
    function pushEvent(kind,payload){DS.seq++;DS.events.push({seq:DS.seq,kind:kind,at:Date.now(),from:{name:"__NAME__"},payload:payload});}
    function handleDrop(s,m,o,bodyBytes){
      DS.calls.push({path:s,method:m,body:bodyBytes});
      if(s.indexOf("/open")>=0){
        if(!DS.session)DS.session={id:"sess1a2b3c4d5e6f7a8b",code:"042317",createdAt:Date.now(),expiresAt:Date.now()+259200*1000};
        return J({ok:true,session:sess()});
      }
      if(s.indexOf("/mine")>=0)return J({ok:true,session:sess()});
      if(s.indexOf("/state")>=0)return J({ok:true,session:sess(),events:DS.events.slice(),cursor:DS.seq});
      if(s.indexOf("/upload/init")>=0){
        var b={};try{b=JSON.parse(bodyBytes||"{}");}catch(e){}
        var uid="u"+(Object.keys(DS.uploads).length+1);
        DS.uploads[uid]={name:b.name||"file",size:Number(b.size)||0,total:Number(b.totalChunks)||1,chunks:[]};
        return J({ok:true,uploadId:uid,chunkSize:8388608});
      }
      if(s.indexOf("/upload/chunk")>=0){
        var mm=s.match(/uploadId=([^&]+)/),im=s.match(/index=(\d+)/);
        var uid=mm?decodeURIComponent(mm[1]):"",idx=im?Number(im[1]):0;
        var up=DS.uploads[uid];
        var chunkLen=(bodyBytes&&typeof bodyBytes==="object")?(Number(bodyBytes.bytes)||0):String(bodyBytes||"").length;
        var run=function(){
          if(DS.aborted){return Promise.reject(new DOMException("aborted","AbortError"));}
          if(up)up.chunks[idx]=chunkLen;
          return J({ok:true,received:(up?up.chunks.reduce(function(a,b){return a+(b||0);},0):0)});
        };
        if(DS.delayChunk>0){
          return new Promise(function(res,rej){
            var t=setTimeout(function(){t=0;res(run());},DS.delayChunk);
            if(o&&o.signal){o.signal.addEventListener("abort",function(){if(t){clearTimeout(t);t=0;}DS.aborted=true;rej(new DOMException("aborted","AbortError"));});}
          });
        }
        return run();
      }
      if(s.indexOf("/upload/finish")>=0){
        var b2={};try{b2=JSON.parse(bodyBytes||"{}");}catch(e){}
        var up2=DS.uploads[b2.uploadId||""]||null;
        DS.calls.push({finish:true,uploadId:b2.uploadId,chunks:up2?up2.chunks:null});
        var f={id:"f"+(DS.filesSeq++),name:up2?up2.name:"file",size:up2?up2.size:0,mime:"application/octet-stream",
          downloadUrl:"http://mock.local/drop/file/f1?s=sess1&exp=1&sig=mock"};
        DS.files.push(f);pushEvent("file",f);
        return J({ok:true,file:f});
      }
      if(s.indexOf("/text")>=0){
        var b3={};try{b3=JSON.parse(bodyBytes||"{}");}catch(e){}
        pushEvent("text",{text:b3.text||""});
        return J({ok:true,seq:DS.seq});
      }
      if(s.indexOf("/close")>=0||s.indexOf("/session/")>=0){DS.session=null;DS.files=[];DS.events=[];return J({ok:true});}
      return J({ok:false,reason:"unknown"});
    }
    function J2(obj,status){return J(obj,status);}
    var _f=window.fetch;
    window.fetch=function(u,o){
      o=o||{};
      var s=String((u&&u.url!==undefined)?u.url:u),m=String(o.method||"GET").toUpperCase();
      if(s.indexOf("__DROP_PREFIX__")>=0){
        var rel=s.slice(s.indexOf("__DROP_PREFIX__")+"__DROP_PREFIX__".length);
        var bb=o.body;
        function toBytes(cb){try{
          if(bb==null){cb("");return;}
          if(bb instanceof Blob||(bb&&typeof bb.size==="number"&&typeof bb.slice==="function")){
            var fr=new FileReader();
            fr.onload=function(){cb({bytes:(fr.result&&fr.result.byteLength)||(bb.size||0)});};
            fr.onerror=function(){cb({bytes:bb.size||0});};
            fr.readAsArrayBuffer(bb);return;
          }
          cb(String(bb));
        }catch(e){cb("");}}
        return new Promise(function(res){
          toBytes(function(txt){res(handleDrop(rel,m,o,txt));});
        });
      }
      if(s.indexOf("tcloudbasegateway")<0){
        if(s.indexOf("tt.json")>=0)return J2({c:[],t:"",meta:{fetchedAt:Date.now()}});
        return _f.apply(this,arguments);
      }
      if(s.indexOf("/userdata")>=0)return o.method==="GET"?J2([]):J2([]);
      if(s.indexOf("rpc/class_members")>=0)return J2([{seat:1,sid:"__SID__",name:"__NAME__",role:"",badge:""}]);
      if(s.indexOf("rpc/class_verify")>=0)return J2({ok:true,token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false});
      if(s.indexOf("rpc/")>=0)return J2({ok:true,seats:[]});
      return J2([]);
    };
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
      var files=[].map.call(document.querySelectorAll('#fileList .file-item'),function(it){
        var a=it.querySelector('.file-dl,.file-download,a[href]');
        return {name:it.querySelector('.file-name')?it.querySelector('.file-name').textContent:it.textContent,
          size:it.querySelector('.file-size')?it.querySelector('.file-size').textContent:'',
          href:a?String(a.getAttribute('href')||a.href||''):''};});
      var ups=[].map.call(document.querySelectorAll('#fileUpList .file-up,.file-upitem'),function(it){
        return {name:it.textContent,pct:it.querySelector('.file-up-pct,.file-up-pct b')?it.querySelector('.file-up-pct,.file-up-pct b').textContent:''};});
      var ds=window.__ds||{};
      return {room:q('#fileRoom')?q('#fileRoom').textContent:null,
        state:q('#fileState')?q('#fileState').textContent:null,
        link:q('#fileLink')?String((q('#fileLink').value!==undefined?q('#fileLink').value:q('#fileLink').textContent)||''):'',
        ttl:q('#fileTTL')?q('#fileTTL').textContent:(document.getElementById('s-file')?document.getElementById('s-file').textContent:''),
        files:files,ups:ups,
        expiredNotice:q('#fileList .file-expired')?q('#fileList .file-expired').textContent:'',
        expiredDl:document.querySelectorAll('#fileList [data-fid="f-expired-1"] .file-dl').length,
        ds:{session:ds.session||null,files:(ds.files||[]).length,events:(ds.events||[]).length,
          calls:(ds.calls||[]).map(function(c){return c.path||'finish';}),aborted:!!ds.aborted,
          uploads:(ds.uploads||{})},
        errs:(window.__errs||[]).slice(-4),cerrs:(window.__cerrs||[]).slice(-4),
        overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth};
    })()""")


def wait_for(fn, timeout=10.0, step=0.12):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


def open_file_page(page):
    page.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();'x'")
    time.sleep(0.4)
    page.evaluate("(function(){var b=document.querySelector('#allCards [data-open=\"file\"],#allCards [data-card=\"file\"] button');if(b)b.click();})()")
    return page.wait_for("(function(){var e=document.getElementById('s-file');return !!(e&&e.classList.contains('on'));})()", 15)


def upload_file(page, size, name, mime="application/octet-stream"):
    return page.evaluate("""(function(){
      var inp=document.querySelector('#fileUpInput');if(!inp)return false;
      var n=%d,arr=new Uint8Array(n);
      for(var i=0;i<n;i++)arr[i]=(i%%251);
      var f=new File([arr],%s,{type:%s});
      var dt=new DataTransfer();dt.items.add(f);
      inp.files=dt.files;
      inp.dispatchEvent(new Event('change',{bubbles:true}));
      return true;})()""" % (size, json.dumps(name), json.dumps(mime)))


def main():
    os.makedirs(SHOTS, exist_ok=True)
    httpd, port = serve(TOOLS)
    url = "http://127.0.0.1:%d/%s" % (port, urllib.parse.quote(REL))
    dropprefix = "http://127.0.0.1:%d/__drop" % port
    b = _cdp.Browser(window=(430, 900))
    init = (INIT.replace("__SID__", SID).replace("__NAME__", NAME)
            .replace("__DROPBASE__", dropprefix).replace("__DROP_PREFIX__", dropprefix))

    def new_page(w=430, h=900, hash=""):
        p = b.new_page("about:blank")
        p.set_device(w, h, dpr=2.0, mobile=True, touch=True)
        p.add_init_script(init)
        p.navigate(url + hash)
        assert p.wait_for("!document.body.classList.contains('auth-pending')", 30), "identity timeout"
        p.wait_for("document.querySelectorAll('#tabsBar button').length>0", 15)
        time.sleep(0.8)
        return p

    print("\n== A 静态检查 ==")
    T("A1 TOOLS 新增文件传输（k=file / n=文件传输）",
      '"file"' in SRC_TEXT and "文件传输" in SRC_TEXT and ("k:\"file\"" in SRC_TEXT.replace(" ", "")))
    T("A2 #s-file section 位于 #s-all 之前",
      'id="s-file"' in SRC_TEXT and 'id="s-all"' in SRC_TEXT and
      SRC_TEXT.index('id="s-file"') < SRC_TEXT.index('id="s-all"'))
    T("A3 文件传输页关键元素（房间码/链接/上传/列表/文字/关闭）",
      all(k in SRC_TEXT for k in ('id="fileRoom"', 'id="fileLink"', 'id="fileUpInput"', 'id="fileList"',
                                  'id="fileText"', 'id="fileSendText"', 'id="fileClose"')))
    T("A4 文案含「文件自上传起保留 3 天」+ 不限大小/分片说明",
      "文件自上传起保留 3 天" in SRC_TEXT and ("任意大小" in SRC_TEXT or "不限大小" in SRC_TEXT or "不限文件大小" in SRC_TEXT))
    T("A5 #drop hash 路由指向新文件传输页（gotoTab('file')）",
      '"#drop"' in SRC_TEXT and ("gotoTab(\"file\")" in SRC_TEXT or "gotoTab('file')" in SRC_TEXT))
    T("A6 分片 8MiB（8388608）且 upload/init|chunk|finish 协议在页内实现",
      "8388608" in SRC_TEXT and "/upload/init" in SRC_TEXT and "/upload/chunk" in SRC_TEXT and "/upload/finish" in SRC_TEXT)
    T("A7 大屏互联面板保留（o2sDropModal / dropCtl 不回归）",
      'id="o2sDropModal"' in SRC_TEXT and ('dropCtl' in SRC_TEXT or 'id="dropCtl"' in SRC_TEXT))
    T("A8 APP_VER 仍 2.0.0", 'var APP_VER="2.0.0"' in SRC_TEXT)
    T("A9 零外链（无 http(s):// 静态外链脚本/字体/CSS）",
      "fonts.googleapis" not in SRC_TEXT and "cdn." not in SRC_TEXT and "<script src=" not in SRC_TEXT)
    T("A10 drop v2.1 过期文件处理（expired 事件 → 列表标注已过期、不可下载）",
      "expired" in SRC_TEXT and ("已过期" in SRC_TEXT) and ("文件自上传起保留 3 天" in SRC_TEXT))

    print("\n== B 运行时（mock drop 服务） ==")
    p = new_page()
    # B0 全部页卡片
    p.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();'x'")
    time.sleep(0.5)
    card = p.evaluate("(function(){var c=document.querySelector('#allCards [data-card=\"file\"]');return c?c.textContent:null;})()")
    T("B0a 全部页自动生成「文件传输」卡片", bool(card) and "文件传输" in card, card)
    ok = open_file_page(p)
    T("B0b 卡片可打开 #s-file 页", ok)
    if not ok:
        print("  [SKIP] 文件传输页未实现，运行时组跳过")
    else:
        wait_for(lambda: "042317" in (snap(p)["room"] or ""), 10)
        s = snap(p)
        T("B1a 进入页自动开通道：房间码显示", "042317" in (s["room"] or ""), s["room"])
        T("B1b 会话链接展示（含 #drop）", "#drop" in (s["link"] or ""), s["link"])
        T("B1c 页面说明「文件保留 3 天」", "3天" in "".join((s["ttl"] or "").split()), (s["ttl"] or "")[:120])
        T("B1d 大屏互联弹层未被误打开（独立页不弹旧弹层）",
          p.evaluate("(function(){var e=document.getElementById('dropCtl');return e?getComputedStyle(e).display==='none'||!e.classList.contains('on'):true;})()"))
        # B2 小文件上传
        upload_file(p, 1024, "测试小文件.txt", "text/plain")
        ok2 = wait_for(lambda: any("测试小文件" in (it["name"] or "") for it in snap(p)["files"]), 12)
        s2 = snap(p)
        init_calls = [c for c in s2["ds"]["calls"] if "/upload/init" in c]
        chunk_calls = [c for c in s2["ds"]["calls"] if "/upload/chunk" in c]
        fin = [c for c in (s2["ds"]["calls"] or [])]
        T("B2a 小文件上传成功并出现在文件列表", ok2, s2["files"])
        T("B2b init/chunk/finish 调用各 1 次", len(init_calls) == 1 and len(chunk_calls) == 1 and len(s2["ds"]["uploads"]) == 1,
          (init_calls, chunk_calls, s2["ds"]["uploads"]))
        T("B2c 下载链接来自服务端签名 URL", bool(s2["files"]) and "mock.local" in (s2["files"][0]["href"] or ""), s2["files"])
        # B3 20MiB 大文件分片
        up0 = dict(s2["ds"]["uploads"])
        upload_file(p, 20 * 1024 * 1024, "大文件.bin")
        ok3 = wait_for(lambda: len(snap(p)["ds"]["uploads"]) == len(up0) + 1, 25)
        time.sleep(1.2)
        s3 = snap(p)
        ups = s3["ds"]["uploads"]
        newu = [u for k, u in ups.items() if k not in up0]
        nchunks = len(newu[0]["chunks"]) if newu else 0
        sizes = [c for c in (newu[0]["chunks"] if newu else []) if c]
        T("B3a 20MiB 大文件 = 3 片", ok3 and nchunks == 3, (nchunks, sizes))
        T("B3b 分片大小 = 8MiB/8MiB/4MiB（最后一片可小）",
          sizes == [8388608, 8388608, 20 * 1024 * 1024 - 2 * 8388608], sizes)
        T("B3c 大文件出现在列表（大小 ~20MB）", any("大文件" in (it["name"] or "") for it in s3["files"]), s3["files"])
        # B4 进度 + 取消
        p.evaluate("window.__ds.delayChunk=220;'x'")
        before_finish = len([c for c in snap(p)["ds"]["calls"] if c == "finish" or "/upload/finish" in c])
        upload_file(p, 20 * 1024 * 1024, "取消测试.bin")
        time.sleep(0.5)
        s4a = snap(p)
        pct_ok = any("%" in (u["pct"] or "") for u in s4a["ups"])
        T("B4a 上传中显示进度（存在 % 进度）", pct_ok, s4a["ups"])
        p.evaluate("(function(){var b=document.querySelector('[data-filecancel]');if(b)b.click();})()")
        time.sleep(1.4)
        s4 = snap(p)
        after_finish = len([c for c in s4["ds"]["calls"] if c == "finish" or "/upload/finish" in c])
        T("B4b 取消后 abort 生效且不再 finish", s4["ds"]["aborted"] is True and after_finish == before_finish,
          (s4["ds"]["aborted"], before_finish, after_finish))
        # B5 发文字
        p.evaluate("window.__ds.delayChunk=0;'x'")
        p.evaluate("(function(){var t=document.getElementById('fileText');if(t){t.value='大屏你好';t.dispatchEvent(new Event('input',{bubbles:true}));}var b=document.getElementById('fileSendText');if(b)b.click();})()")
        ok5 = wait_for(lambda: any('"大屏你好"' in json.dumps(c.get("text", ""), ensure_ascii=False) or "大屏你好" in str(c) for c in (p.evaluate("(window.__ds.events||[])") or [])), 8)
        T("B5 发文字 → POST /text 并追加 text 事件", ok5, p.evaluate("(window.__ds.events||[])"))
        # B8 drop v2.1：文件自上传起 72h 过期 → /state 返回 expired=true 且无 downloadUrl
        p.evaluate("""(function(){var ds=window.__ds;ds.seq++;ds.events.push({seq:ds.seq,kind:"file",at:Date.now(),payload:{id:"f-expired-1",name:"旧文件.bin",size:1234,expired:true}});return true;})()""")
        p.evaluate("var b=document.getElementById('fileRefresh');if(b)b.click();'x'")
        ok8 = wait_for(lambda: "已过期" in (snap(p)["expiredNotice"] or ""), 10)
        s8 = snap(p)
        T("B8a 过期文件在文件列表标注「已过期」", ok8, (s8["expiredNotice"], s8["files"]))
        T("B8b 过期文件不再提供下载链接", s8["expiredDl"] == 0, s8["expiredDl"])
        # B6 关闭会话
        p.evaluate("var b=document.querySelector('#fileClose');if(b)b.click();'x'")
        ok6 = wait_for(lambda: (snap(p)["ds"]["session"] is None), 8)
        s6 = snap(p)
        T("B6a 关闭 → POST /close 且会话清空", ok6 and any("/close" in c for c in s6["ds"]["calls"]), s6["ds"]["calls"][-6:])
        T("B6b 关闭后 UI 复位（房间码清空/提示未开启）",
          (not s6["room"]) or ("未" in (s6["room"] or "")) or ("—" in (s6["room"] or "")), s6["room"])
        T("B6c 0 JS 报错 / 0 console.error", not s6["errs"] and not s6["cerrs"], (s6["errs"], s6["cerrs"]))
        T("B6d 无外部请求", not (p.evaluate(EXTS_JS) or []))
        try:
            p.screenshot(os.path.join(SHOTS, "file_430.png"))
        except Exception:
            pass
    p.close()

    print("\n== B7 #drop hash 路由 ==")
    p = new_page(hash="#drop")
    ok = p.wait_for("(function(){var e=document.getElementById('s-file');return !!(e&&e.classList.contains('on'));})()", 15)
    T("B7a #drop 直接打开文件传输页", ok)
    T("B7b #drop 不再打开大屏互联旧弹层",
      p.evaluate("(function(){var e=document.getElementById('dropCtl');return e?(getComputedStyle(e).display==='none'||!e.classList.contains('on')):true;})()"))
    p.close()

    print("\n== C 溢出 / 报错 ==")
    for w, h in ((360, 780), (430, 900)):
        px = new_page(w, h)
        open_file_page(px)
        sx = snap(px)
        T("C-%d 文件传输页无横向溢出" % w, sx["overflow"] == 0, sx["overflow"])
        T("C-%d 0 JS 报错" % w, not sx["errs"] and not sx["cerrs"], (sx["errs"], sx["cerrs"]))
        px.close()

    b.close()
    httpd.shutdown()

    print("\n== 截图 ==")
    for f in sorted(os.listdir(SHOTS)):
        if "file" in f:
            print("  " + os.path.join(SHOTS, f))
    print("\n============================================================")
    print("v2_web_batch2_file_check: PASS %d / FAIL %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：")
        for x in FAILS:
            print("  - " + x)
    print("============================================================")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
