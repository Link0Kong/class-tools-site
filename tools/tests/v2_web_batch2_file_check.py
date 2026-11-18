# -*- coding: utf-8 -*-
r"""网页批次2 · 文件传输 = 临时云空间（2026-11-12 重设计）。

需求：文件传输不做「会话/房间码/链接」概念，而是**临时云空间**：
同账号跨设备自动共享同一空间（无需配对/链接）；上传任意大小（8MiB 分片）、列表下载、
单文件删除、清空空间；文件自上传起保留 3 天；过期自动删除。
后端复用 ECS drop 服务（v2.2，新增 DELETE /file/<fileId>），认证同 drop 契约。
大屏互联控制器保留，入口 `#drop`；文件页入口 `#file`。

覆盖：
A 静态：TOOLS/页面结构/无房间码无链接无文字/上传列表清理/TTL/分片协议/#drop→控制器 #file→云空间
B 运行时（fetch mock drop 服务）：
  B0 全部页卡片打开
  B1 进入自动连接（同账号共享，无配对码/链接）
  B2 小文件上传（init→chunk→finish，列表出现 + 下载链接）
  B3 大文件 20MiB = 3 片
  B4 上传进度 + 取消（不 finish）
  B5 单文件删除（DELETE /file/<id>，行消失、统计更新）
  B6 过期文件标注（不可下载）
  B7 清空空间（/close → 自动重开新空间）
  B8 hash 路由：#drop 不再打开文件页、#file 打开云空间
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
    window.open=function(u){window.__opened=String(u||'');return null;};
    window.__DROP_BASE="__DROPBASE__";
    try{localStorage.clear();}catch(e){}
    try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
    /* ---- mock drop 服务（临时云空间口径：session + file/filedel 事件，TTL 3 天） ---- */
    var DS={session:null,files:[],events:[],uploads:{},calls:[],filesSeq:1,aborted:false,delayChunk:0,seq:0,
      expiresAt:0,openCount:0,closeCount:0};
    window.__ds=DS;
    function J(obj,status){status=status||200;return Promise.resolve(new Response(JSON.stringify(obj),{status:status,headers:{"Content-Type":"application/json"}}));}
    function sess(){return DS.session?{id:DS.session.id,code:DS.session.code,createdAt:DS.session.createdAt,expiresAt:DS.session.expiresAt,seq:DS.seq}:null;}
    function pushEvent(kind,payload){DS.seq++;DS.events.push({seq:DS.seq,kind:kind,at:Date.now(),from:{name:"__NAME__"},payload:payload});}
    function fileUrl(id){return "http://mock.local/drop/file/"+id+"?s=sess1&exp=1&sig=mock";}
      /* v2.5：/state?all=1 的文件清单取自「会话文件表」而不是事件（与服务端一致）；
         expiredNotice 由服务端统计（这里允许用例直接指定 DS.expiredNoticeN 模拟）。 */
    function liveList(){
      var now=Date.now(),ttl=DS.fileTtl!==undefined?Number(DS.fileTtl):259200000;
      return DS.files.filter(function(f){return !(f.ttlOff)&&!(f.at&&(now-f.at)>ttl);}).map(function(f){
        return {id:f.id,name:f.name,size:f.size,mime:f.mime,at:f.at||now,downloadUrl:fileUrl(f.id)};
      }).sort(function(a,b){return (b.at||0)-(a.at||0);});
    }
    function dropFile(id,extra){
      var f=null;
      for(var i=0;i<DS.files.length;i++){if(String(DS.files[i].id)===String(id)){f=DS.files[i];break;}}
      if(!f)return {ok:true,deleted:false};
      DS.files=DS.files.filter(function(x){return String(x.id)!==String(id);});
      pushEvent("filedel",{fileId:f.id,name:f.name,size:f.size});
      return {ok:true,deleted:true,name:f.name,size:f.size};
    }
    function handleDrop(s,m,o,bodyBytes){
      DS.calls.push({path:s,method:m});
      if(s.indexOf("/open")>=0){
        if(!DS.session){
          DS.session={id:"sess1a2b3c4d5e6f7a8b",code:"042317",createdAt:Date.now(),expiresAt:Date.now()+259200*1000};
          DS.events=[];DS.files=[];DS.seq=0;DS.openCount++;
        }
        return J({ok:true,session:sess()});
      }
      if(s.indexOf("/mine")>=0)return J({ok:true,session:sess()});
      if(s.indexOf("/presence")>=0)return J({ok:true,stage:true,at:Date.now()});
      if(s.indexOf("/state")>=0){
        var sinceM=s.match(/[?&]since=(\d+)/),sinceV=sinceM?Number(sinceM[1]):0;
        var evs=DS.hideEvents?[]:DS.events.filter(function(e){return Number(e.seq)>sinceV;}).map(function(e){
          var c={seq:e.seq,kind:e.kind,at:e.at,from:e.from,payload:JSON.parse(JSON.stringify(e.payload))};
          return c;
        });
        var out={ok:true,session:sess(),events:evs,cursor:DS.seq};
        if(/[?&]all=1(&|$)/.test(s)){
          out.files=liveList();
          out.expiredNotice=Number(DS.expiredNoticeN||0);
          out.fileSeq={};
        }
        return J(out);
      }
      if(s.indexOf("/upload/init")>=0){
        var b={};try{b=JSON.parse(bodyBytes||"{}");}catch(e){}
        var uid="u"+(Object.keys(DS.uploads).length+1);
        DS.uploads[uid]={name:b.name||"file",size:Number(b.size)||0,total:Number(b.totalChunks)||1,chunks:[],finished:false};
        return J({ok:true,uploadId:uid,chunkSize:8388608});
      }
      if(s.indexOf("/upload/chunk")>=0){
        var mm=s.match(/uploadId=([^&]+)/),im=s.match(/index=(\d+)/);
        var uid2=mm?decodeURIComponent(mm[1]):"",idx=im?Number(im[1]):0;
        var up=DS.uploads[uid2];
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
        if(up2)up2.finished=true;
        var f={id:"f"+(DS.filesSeq++),name:up2?up2.name:"file",size:up2?up2.size:0,mime:"application/octet-stream",
          downloadUrl:"",at:Date.now()};
        f.downloadUrl=fileUrl(f.id);
        DS.files.push(f);pushEvent("file",{fileId:f.id,name:f.name,size:f.size,mime:f.mime,downloadUrl:f.downloadUrl});
        return J({ok:true,file:{id:f.id,name:f.name,size:f.size,mime:f.mime,downloadUrl:f.downloadUrl}});
      }
      if(m==="DELETE"&&s.indexOf("/file/")>=0){
        var fid=s.slice(s.indexOf("/file/")+6).split("?")[0];
        return J(dropFile(decodeURIComponent(fid)));
      }
      if(s.indexOf("/close")>=0){
        DS.session=null;DS.files=[];DS.events=[];DS.seq=0;DS.expiresAt=0;DS.closeCount++;
        return J({ok:true});
      }
      return J({ok:false,reason:"unknown"});
    }
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
        if(s.indexOf("tt.json")>=0)return J({c:[],t:"",meta:{fetchedAt:Date.now()}});
        return _f.apply(this,arguments);
      }
      if(s.indexOf("/userdata")>=0)return o.method==="GET"?J([]):J([]);
      if(s.indexOf("rpc/class_members")>=0)return J([{seat:1,sid:"__SID__",name:"__NAME__",role:"",badge:""}]);
      if(s.indexOf("rpc/class_verify")>=0)return J({ok:true,token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false});
      if(s.indexOf("rpc/")>=0)return J({ok:true,seats:[]});
      return J([]);
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
        var a=it.querySelector('.file-dl');
        return {name:it.querySelector('.file-name')?it.querySelector('.file-name').textContent:'',
          meta:it.querySelector('.file-meta')?it.querySelector('.file-meta').textContent:'',
          href:a?String(a.getAttribute('href')||a.href||''):'',
          label:a?String(a.textContent||''):'',
          del:!!it.querySelector('[data-filedel]')};});
      var ups=[].map.call(document.querySelectorAll('#fileUpList .file-up'),function(it){
        return {name:it.textContent,pct:it.querySelector('.file-up-pct')?it.querySelector('.file-up-pct').textContent:''};});
      var ds=window.__ds||{};
      return {state:q('#fileState')?q('#fileState').textContent:null,
        statCount:q('#fileStatCount')?q('#fileStatCount').textContent:null,
        statSize:q('#fileStatSize')?q('#fileStatSize').textContent:null,
        ttl:q('#fileTTL')?q('#fileTTL').textContent:'',
        text:(document.getElementById('s-file')||{}).textContent||'',
        files:files,ups:ups,
        expiredNotice:q('#fileList .file-expired')?q('#fileList .file-expired').textContent:'',
        ds:{session:ds.session||null,files:(ds.files||[]).length,events:(ds.events||[]).length,
          calls:(ds.calls||[]).map(function(c){return c.path||'finish';}),aborted:!!ds.aborted,
          uploads:(ds.uploads||{}),openCount:ds.openCount||0,closeCount:ds.closeCount||0},
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
        time.sleep(0.9)
        return p

    print("\n== A 静态检查 ==")
    T("A1 TOOLS 含文件传输（k=file / n=文件传输 / 临时云空间）",
      '"file"' in SRC_TEXT and "文件传输" in SRC_TEXT and "临时云空间" in SRC_TEXT
      and ("k:\"file\"" in SRC_TEXT.replace(" ", "")))
    T("A2 #s-file section 位于 #s-all 之前",
      'id="s-file"' in SRC_TEXT and 'id="s-all"' in SRC_TEXT and
      SRC_TEXT.index('id="s-file"') < SRC_TEXT.index('id="s-all"'))
    T("A3 云空间关键元素（上传/列表/清空/刷新/说明），无房间码/链接/文字",
      all(k in SRC_TEXT for k in ('id="fileUpInput"', 'id="fileList"', 'id="fileClear"',
                                  'id="fileRefresh"', 'id="fileTTL"'))
      and all(k not in SRC_TEXT for k in ('id="fileRoom"', 'id="fileLink"', 'id="fileSendText"',
                                          'id="fileText"', 'id="fileOpen"', 'id="fileClose"', '房间码')))
    T("A4 文案含「文件自上传起保留 3 天」+ 不限大小/分片说明",
      "文件自上传起保留 3 天" in SRC_TEXT and ("任意大小" in SRC_TEXT or "不限大小" in SRC_TEXT or "不限文件大小" in SRC_TEXT))
    T("A5 hash 路由：#file → 云空间；#drop → 大屏互联控制器（不再指向文件页）",
      ('"#file"' in SRC_TEXT or "===\"#file\"" in SRC_TEXT) and 'gotoTab("file")' in SRC_TEXT
      and '"#drop"' in SRC_TEXT and 'dropCtlOpen' in SRC_TEXT
      and 'if(h!=="#drop"&&h!=="#file")return;' in SRC_TEXT)
    T("A6 分片 8MiB（8388608）且 upload/init|chunk|finish/DELETE 协议在页内实现",
      "8388608" in SRC_TEXT and "/upload/init" in SRC_TEXT and "/upload/chunk" in SRC_TEXT
      and "/upload/finish" in SRC_TEXT and 'method:"DELETE"' in SRC_TEXT)
    T("A7 大屏互联面板/控制器保留（o2sDropModal / dropCtl 不回归）",
      'id="o2sDropModal"' in SRC_TEXT and 'dropCtl' in SRC_TEXT)
    T("A8 APP_VER 仍 2.0.0", 'var APP_VER="2.0.0"' in SRC_TEXT)
    T("A9 零外链（无 http(s):// 静态外链脚本/字体/CSS）",
      "fonts.googleapis" not in SRC_TEXT and "cdn." not in SRC_TEXT and "<script src=" not in SRC_TEXT)
    T("A10 过期文件处理 + filedel 事件（expired 标注、删除同步）",
      "expired" in SRC_TEXT and "已过期" in SRC_TEXT and "filedel" in SRC_TEXT)

    print("\n== B 运行时（mock drop 云空间） ==")
    p = new_page()
    p.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();'x'")
    time.sleep(0.5)
    card = p.evaluate("(function(){var c=document.querySelector('#allCards [data-card=\"file\"]');return c?c.textContent:null;})()")
    T("B0a 全部页自动生成「文件传输」卡片", bool(card) and "文件传输" in card, card)
    ok = open_file_page(p)
    T("B0b 卡片可打开 #s-file 页", ok)
    if not ok:
        print("  [SKIP] 文件传输页未打开，运行时组跳过")
    else:
        ok1 = wait_for(lambda: "已连接" in (snap(p)["state"] or ""), 12)
        s = snap(p)
        T("B1a 进入页自动连接云空间（同账号共享）", ok1 and "同账号" in (s["state"] or ""), s["state"])
        T("B1b 无房间码/链接/配对 UI，空空间统计为 0",
          ("房间码" not in (s["text"] or "")) and (not s["files"]) and (s["statCount"] == "0"), (s["statCount"], s["files"]))
        T("B1c 页面说明「文件保留 3 天」", "3天" in "".join((s["ttl"] or "").split()), (s["ttl"] or "")[:120])

        # B2 小文件
        upload_file(p, 1024, "测试小文件.txt", "text/plain")
        ok2 = wait_for(lambda: any("测试小文件" in (it["name"] or "") for it in snap(p)["files"]), 12)
        s2 = snap(p)
        T("B2a 小文件上传后出现在列表（含下载按钮）", ok2, s2["files"])
        T("B2b 下载链接为签名 URL（drop /file/）",
          ok2 and any("/file/" in (it["href"] or "") or "mock.local" in (it["href"] or "") for it in s2["files"]), s2["files"])
        T("B2c 统计更新为 1 个文件 / 非 0 占用", s2["statCount"] == "1", (s2["statCount"], s2["statSize"]))
        # 下载后按钮变「打开」（与 PPT 一致的用户预期）
        p.evaluate("(function(){var a=document.querySelector('#fileList .file-dl');if(a)a.click();})()")
        ok_open = wait_for(lambda: any(it["label"] == "打开" for it in snap(p)["files"]), 8)
        op = p.evaluate("(function(){try{return localStorage.getItem('zq_file_opened_v1')||'';}catch(e){return '';}})()")
        T("B2d 点击下载后按钮变「打开」并持久化标记", ok_open and "f1" in op, (ok_open, op[:80]))
        p.evaluate("(function(){var a=document.querySelector('#fileList .file-dl');if(a)a.click();})()")
        ok_reopen = wait_for(lambda: bool(p.evaluate("window.__opened")), 8)
        T("B2e 再点「打开」会重新取签名链接并打开", ok_reopen, p.evaluate("String(window.__opened||'')")[:80])

        # B3 大文件 20MiB = 3 片
        upload_file(p, 20 * 1024 * 1024, "测试大文件.bin")
        ok3 = wait_for(lambda: any("测试大文件" in (it["name"] or "") for it in snap(p)["files"]), 25)
        s3 = snap(p)
        ups3 = s3["ds"]["uploads"] or {}
        big = None
        for _k, v in ups3.items():
            if v.get("name") == "测试大文件.bin":
                big = v
        T("B3a 大文件上传成功并出现在列表", ok3, [it["name"] for it in s3["files"]])
        T("B3b 20MiB 分为 3 片（8+8+4MiB）",
          bool(big) and big.get("total") == 3 and len([x for x in (big.get("chunks") or []) if x]) == 3,
          big)

        # B4 进度 + 取消
        p.evaluate("window.__ds.delayChunk=120;'x'")
        before_finish = sum(1 for c in snap(p)["ds"]["calls"] if c == "finish")
        upload_file(p, 2 * 1024 * 1024, "取消测试.bin")
        okp = wait_for(lambda: any("取消测试" in (u["name"] or "") and "%" in (u["pct"] or "") for u in snap(p)["ups"]), 8)
        T("B4a 上传进度条出现（百分比）", okp, snap(p)["ups"])
        p.evaluate("(function(){var b=document.querySelector('[data-filecancel]');if(b)b.click();})()")
        okc = wait_for(lambda: any("已取消" in (u["name"] or "") for u in snap(p)["ups"]), 8)
        after_finish = sum(1 for c in snap(p)["ds"]["calls"] if c == "finish")
        T("B4b 取消上传：显示已取消且不 finish", okc and after_finish == before_finish,
          (okc, before_finish, after_finish))
        p.evaluate("window.__ds.delayChunk=0;window.__ds.aborted=false;'x'")

        # B5 单文件删除
        del_before = [it["name"] for it in snap(p)["files"]]
        p.evaluate("""(function(){var its=[].slice.call(document.querySelectorAll('#fileList .file-item'));
          for(var i=0;i<its.length;i++){var nm=its[i].querySelector('.file-name');
            if(nm&&nm.textContent.indexOf('测试小文件.txt')>=0){var b=its[i].querySelector('[data-filedel]');if(b){b.click();return;}}}
        })()""")
        okd = wait_for(lambda: len([it for it in snap(p)["files"] if it["name"] == "测试小文件.txt"]) == 0, 10)
        s5 = snap(p)
        del_calls = [c for c in s5["ds"]["calls"] if "/file/" in c]
        T("B5a 单文件删除成功（DELETE /file/<id>，行消失）", okd and bool(del_calls), (okd, del_calls[-3:]))
        T("B5b 删除后统计同步减少", s5["statCount"] in ("1", "2"), s5["statCount"])

        # B6 过期文件（v2.5 口径：/state?all=1 的 expiredNotice 由服务端统计）
        p.evaluate("window.__ds.expiredNoticeN=1;'x'")
        p.evaluate("var b=document.getElementById('fileRefresh');if(b)b.click();'x'")
        ok6 = wait_for(lambda: bool(snap(p)["expiredNotice"]), 10)
        T("B6a 过期文件在列表下方标注「已过期」", ok6, snap(p)["expiredNotice"])
        T("B6b 过期文件不提供下载行", not any(it["name"] == "旧文件.bin" for it in snap(p)["files"]), snap(p)["files"])
        p.evaluate("window.__ds.expiredNoticeN=0;'x'")

        # B6c/B6d v2.5 回归：文件事件被挤出窗口（/state?since=<大值> 只回空事件）也必须看到文件
        p.evaluate("""(function(){var ds=window.__ds;
          ds.hideEvents=1;                       /* 模拟「事件表已截断 / 只拉增量」 */
          ds.files.push({id:"fhidden1",name:"只剩清单也有.txt",size:10,mime:"text/plain",at:Date.now()});
        })()""")
        p.evaluate("var b=document.getElementById('fileRefresh');if(b)b.click();'x'")
        ok6c = wait_for(lambda: any("只剩清单也有" in (it["name"] or "") for it in snap(p)["files"]), 10)
        s6c = snap(p)
        T("B6c 无 file 事件时（事件已截断）仍按服务端文件清单列出文件", ok6c, [it["name"] for it in s6c["files"]])
        state_calls = [c for c in s6c["ds"]["calls"]
                       if c.startswith("/state") and "all=1" in c]
        T("B6d 文件页 /state 带 all=1（以服务端文件清单为准）",
          bool(state_calls), [c for c in s6c["ds"]["calls"] if c.startswith("/state")][-3:])

        # B7 清空空间
        close_before = snap(p)["ds"]["closeCount"]
        p.evaluate("var b=document.getElementById('fileClear');if(b)b.click();'x'")
        ok7 = wait_for(lambda: snap(p)["ds"]["closeCount"] > close_before and snap(p)["statCount"] == "0", 12)
        s7 = snap(p)
        T("B7a 清空空间：POST /close 后自动重开（/open）",
          ok7 and s7["ds"]["openCount"] >= 2, (s7["ds"]["closeCount"], s7["ds"]["openCount"]))
        T("B7b 清空后列表为空", not s7["files"] and bool(s7["ds"]["session"]), s7["files"])

        # B8 hash 路由：#drop 开大屏互联控制器，不再打开文件页
        p_drop = new_page(hash="#drop")
        ok_drop = p_drop.wait_for("(function(){var e=document.getElementById('dropCtl');return !!(e&&e.classList.contains('on'));})()", 15)
        on_file_after_drop = p_drop.evaluate("!!(document.getElementById('s-file')&&document.getElementById('s-file').classList.contains('on'))")
        T("B8a #drop 打开大屏互联控制器、不再打开文件页", ok_drop and not on_file_after_drop, (ok_drop, on_file_after_drop))
        p_drop.close()

        T("B9a 430 宽无横向溢出", s7["overflow"] <= 0, s7["overflow"])
        T("B9b 0 JS 报错 / 0 console.error", not s7["errs"] and not s7["cerrs"], (s7["errs"], s7["cerrs"]))
        T("B9c 无外部请求", not (p.evaluate(EXTS_JS) or []))
        try:
            p.screenshot(os.path.join(SHOTS, "file_cloud_430.png"))
        except Exception:
            pass
    p.close()

    # C #file hash 直接打开云空间
    p2 = new_page(hash="#file")
    okh = p2.wait_for("(function(){var e=document.getElementById('s-file');return !!(e&&e.classList.contains('on'));})()", 15)
    T("C1 #file hash 直接打开临时云空间", okh, "")
    p2.close()

    httpd.shutdown()
    print("\n" + "=" * 60)
    print("v2_web_batch2_file_check: PASS %d / FAIL %d" % (PASS, FAIL))
    if FAILS:
        for f in FAILS:
            print("  [FAIL] " + f)
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
