# -*- coding: utf-8 -*-
"""大屏互联会话/在线状态回归（2026-11-16 修复：退出大屏后 presence 残留 + 上一次数据回放）。

场景：
  A. 打开大屏时只接收「本次」事件；退出后面板/接收模块不保留上一次内容；
  B. 退出大屏 → presence 立即 false（页面入口「大屏互联」隐藏），轮询/心跳停止；
  C. 快速开关大屏（/open 延迟返回）不会把 presence 在关闭后重新拉起（原来会永久显示开启）；
  D. 其它设备控制器：仅按 presence 判定「已连接」，退出后变「大屏已退出」，且不翻出旧事件；
  E. 全流程 0 JS 报错 / 0 console.error。
用法：python tools/tests/v2_stage_drop_session_check.py [index.html]
"""
import http.server
import json
import os
import socketserver
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(WEB, "index.html")
TMP = os.path.join(os.environ.get("TEMP", "/tmp"), "stage_drop_session_%d" % os.getpid())
sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
import _cdp  # noqa: E402

IMGD = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="

DATA = {
    "members": [{"seat": i, "sid": "9999%06d" % i, "name": "测试同学%02d" % (i % 5),
                 "role": ("班长" if i == 1 else ""), "badge": ("班委" if i <= 3 else ""), "is_admin": False}
                for i in range(1, 71)],
    "homework": [], "marks": [], "fitrecs": [], "notices": [],
    "tt": {"c": [], "t": "2026-08-31"},
}

MOCK = r"""
<script>
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
(function(){var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};})();
var DATA=__DATA__;
var PNOW=Date.now()+600000;
var POLLSET={multi:false,maxChoices:1,anonymous:true,allowChange:true,resultVisibility:"always"};
var POLL={id:"p1",title:"团日活动形式投票",description:"",mode:"quick",owner_name:"测试同学",settings:POLLSET,
  deadline:PNOW,status:"open",closed_at:0,created_at:Date.now(),updated_at:Date.now(),closed:false,
  total:12,counts:{o1:7,o2:5},has_voted:false,my_choices:[],results_hidden:false,mine:true,can_manage:true};
var PDETAIL={ok:true,now:Date.now(),poll:{id:"p1",title:"团日活动形式投票",description:"",mode:"quick",owner_name:"测试同学",
  settings:POLLSET,options:[{id:"o1",text:"参观红色基地"},{id:"o2",text:"主题团课"}],deadline:PNOW,status:"open",closed_at:0,
  created_at:Date.now(),updated_at:Date.now()},closed:false,total:12,counts:{o1:7,o2:5},has_voted:false,my_choices:[],
  results_hidden:false,mine:true,can_manage:true,voters:[]};
var LEAGUE={ok:true,count:3,seats:[{seat:1,name:"测试同学01"},{seat:2,name:"测试同学02"},{seat:3,name:"测试同学03"}]};

/* ---- drop 云空间服务 mock（presence/seq/事件与真实 v2.4 对齐） ---- */
var SRV={session:null,events:[],presence:{stage:false,at:0,since:0},calls:[],openDelay:0};
function srMax(){var m=0;for(var i=0;i<SRV.events.length;i++)m=Math.max(m,Number(SRV.events[i].seq)||0);return m;}
function srSession(){if(!SRV.session)SRV.session={id:"sess-test01",code:"123456",createdAt:Date.now(),expiresAt:Date.now()+259200000};SRV.session.seq=srMax();return SRV.session;}
function srClone(o){return JSON.parse(JSON.stringify(o));}
function srAppend(kind,payload,from){var seq=srMax()+1;SRV.events.push({seq:seq,kind:kind,at:Date.now(),from:{name:from||"测试同学"},payload:payload});return seq;}
function srPresence(body){
  var want=!!body.stage,cur=srMax();
  if(want){
    SRV.presence.stage=true;SRV.presence.at=Date.now();
    var since=(body.sinceSeq==null)?cur:Math.max(0,Math.min(Number(body.sinceSeq)||0,cur));
    SRV.presence.since=since;
  }else{SRV.presence.stage=false;SRV.presence.at=0;SRV.presence.since=0;}
  return {ok:true,stage:want,at:SRV.presence.at,sinceSeq:SRV.presence.since,stageSince:SRV.presence.since};
}
function srPresenceLive(){
  var on=!!(SRV.presence.stage&&SRV.presence.at&&(Date.now()-SRV.presence.at)<=30000);
  return {stage:on,since:on?SRV.presence.since:0};
}
window.__SRV={
  preload:function(n,prefix){for(var i=0;i<n;i++){srAppend("file",{fileId:"old"+i,name:(prefix||"旧文件")+i,size:1024,mime:"image/jpeg",downloadUrl:"#old"});srAppend("text",{text:(prefix||"旧消息")+i});}return srMax();},
  pushText:function(t){return srAppend("text",{text:t},"另一台设备");},
  cs:function(){return srPresenceLive();},
  calls:function(){return SRV.calls.slice();},
  setOpenDelay:function(ms){SRV.openDelay=Number(ms)||0;},
  forcePresenceOff:function(){SRV.presence.stage=false;SRV.presence.at=0;SRV.presence.since=0;},
  state:function(){return {stage:SRV.presence.stage,maxSeq:srMax(),events:srMax()};}
};
function ok(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
window.fetch=function(u,o){
  var s=String((u&&u.url!==undefined)?u.url:u);
  o=o||{};var method=String(o.method||"GET").toUpperCase();
  var body={};try{body=o.body?JSON.parse(o.body):{};}catch(e){}
  if(s.indexOf("/drop")>=0&&s.indexOf("tcloudbasegateway")<0){
    var path=s.replace(/^.*\/drop/,"").split("#")[0];
    SRV.calls.push({t:Date.now(),m:method,path:path,body:body});
    if(path.indexOf("/open")===0){
      return new Promise(function(res){
        function go(){var sess=srClone(srSession());res(ok({ok:true,session:sess}));}
        if(SRV.openDelay)setTimeout(go,SRV.openDelay);else go();
      });
    }
    if(path.indexOf("/state")>=0){
      var q={};var qs=(path.split("?")[1]||"");
      qs.split("&").forEach(function(p){var kv=p.split("=");if(kv[0])q[decodeURIComponent(kv[0])]=decodeURIComponent(kv[1]||"");});
      var since=Number(q.since)||0,sess=srSession();
      var evs=SRV.events.filter(function(e){return Number(e.seq)>since;}).map(srClone);
      return ok({ok:true,session:{id:sess.id,code:sess.code,expiresAt:sess.expiresAt,seq:srMax()},events:evs,
        cursor:evs.length?evs[evs.length-1].seq:since});
    }
    if(path.indexOf("/presence")===0){
      if(method==="GET"){var p=srPresenceLive();return ok({ok:true,stage:p.stage,at:SRV.presence.at,sinceSeq:p.since,stageSince:p.since});}
      return ok(srPresence(body));
    }
    if(path.indexOf("/mine")===0)return ok({ok:true,session:srClone(srSession())});
    if(path.indexOf("/text")===0)return ok({ok:true,seq:srAppend("text",{text:String(body.text||"")})});
    if(path.indexOf("/cmd")===0)return ok({ok:true,seq:srAppend("cmd",{op:String(body.op||""),args:body.args||{}})});
    if(path.indexOf("/close")===0){SRV.session=null;SRV.events=[];SRV.presence={stage:false,at:0,since:0};return ok({ok:true});}
    if(path.indexOf("/upload/")===0)return ok({ok:true,uploadId:"u1",chunkSize:8388608,file:{id:"f1",name:"x.bin",size:1,mime:"application/octet-stream",downloadUrl:"#dl"}});
    return ok({ok:true});
  }
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0)return ok(DATA.members);
    if(s.indexOf("rpc/class_league")>=0)return ok(LEAGUE);
    if(s.indexOf("rpc/poll_list")>=0)return ok({ok:true,now:Date.now(),polls:[POLL]});
    if(s.indexOf("rpc/poll_detail")>=0)return ok(PDETAIL);
    if(s.indexOf("rpc/poll_create")>=0)return ok({ok:true,now:Date.now(),poll:PDETAIL.poll,closed:false,total:0,counts:{},has_voted:false,my_choices:[],results_hidden:false,mine:true,can_manage:true,voters:[]});
    if(s.indexOf("/notices")>=0)return ok(s.indexOf("select=id,ts")>=0?[]:DATA.notices);
    if(s.indexOf("/homework")>=0)return ok(DATA.homework);
    if(s.indexOf("/marks")>=0)return ok(DATA.marks);
    if(s.indexOf("/fitrecs")>=0)return ok(DATA.fitrecs);
    if(s.indexOf("/userdata")>=0)return ok([]);
    if(s.indexOf("/ppt_decks")>=0){
      if(s.indexOf("files%3A")>=0||s.indexOf("files:")>=0)return ok([{id:"d1",files:null}]);
      if(s.indexOf("manifest")>=0)return ok([{id:"d1",title:"示例演示",slide_count:2,step_count:2,aspect:"16:9",cover_url:"",manifest:{base:"https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/",slides:[{steps:[{img:"__IMG__"}],tr:"fade"},{steps:[{img:"__IMG__"}],tr:"fade"}]}}]);
      return ok([{id:"d1",title:"示例演示",status:"ready",progress:100,slide_count:2,step_count:2,aspect:"16:9",cover_url:"",owner_name:"测试同学",source_name:"a.pptx",created_at:1,converted_at:2}]);
    }
    if(s.indexOf("/site_assets")>=0)return ok([{body:{seen_at:Date.now()},updated_at:Date.now()}]);
    return ok([]);
  }
  if(s.indexOf("tt.json")>=0)return ok(DATA.tt);
  return ok([]);
};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"9999000005",name:"测试同学",role:"",badge:"",is_admin:true,ts:Date.now()}));}catch(e){}
try{localStorage.removeItem("zq_stage_layout_v1");localStorage.setItem("zq_stage_hint_v1","1");}catch(e){}
</script>
""".replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")).replace("__IMG__", IMGD)

PASS = 0
FAILS = []


def T(name, ok, note=""):
    global PASS
    if ok:
        PASS += 1
        print("PASS  %s  [%s]" % (name, str(note)[:160]))
    else:
        FAILS.append(name)
        print("FAIL  %s  [%s]" % (name, str(note)[:200]))


def build():
    if not os.path.isdir(TMP):
        os.makedirs(TMP)
    html = open(SRC, encoding="utf-8").read()
    html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + MOCK, 1)
    open(os.path.join(TMP, "index.html"), "w", encoding="utf-8").write(html)


def serve():
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=TMP, **k)

        def log_message(self, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def ev(p, js):
    return p.evaluate(js)


def main():
    build()
    httpd, port = serve()
    b = _cdp.Browser(window=(1366, 768))
    try:
        p = b.new_page("about:blank")
        p.set_device(1366, 768, dpr=1.0, mobile=False, touch=False)
        errs = []
        p.navigate("http://127.0.0.1:%d/index.html" % port)
        p.wait_load(25)
        T("测试页加载/身份就绪", p.wait_for("!document.body.classList.contains('auth-pending')", 15))
        ev(p, "(function(){var a=document.querySelector('[data-tab=\"all\"]');if(a)a.click();})()")
        T("全部页出现「大屏」入口", p.wait_for("!!document.getElementById('opt2StageBtn')", 8))
        # 预置 2 组历史（模拟上次大屏/文件传输留下的 72h 云空间事件）
        ev(p, "window.__SRV.preload(2,'旧')")
        T("预置历史事件 4 条", ev(p, "window.__SRV.state().maxSeq===4"), ev(p, "JSON.stringify(window.__SRV.state())"))

        # ---------- A. 打开大屏：只收本次事件 ----------
        ev(p, "document.getElementById('opt2StageBtn').click()")
        T("大屏打开", p.wait_for("(function(){var s=document.getElementById('opt2Stage');return s&&getComputedStyle(s).display!=='none';})()", 10))
        time.sleep(1.2)
        T("打开后 presence=在线且 sinceSeq=4", ev(p, "(function(){var c=window.__SRV.cs();return c.stage===true;})()") and
          ev(p, "window.__SRV.state().maxSeq===4"), ev(p, "JSON.stringify(window.__SRV.cs())"))
        recv = ev(p, "(function(){var b=document.querySelector('#opt2Stage [data-panel=\"recv\"]');return b?String(b.textContent||''):'';})()")
        T("接收模块不显示历史旧文件/旧消息", ("旧文件" not in recv) and ("旧消息" not in recv), recv[:160])
        # 另一设备推一条「本次」文字
        ev(p, "window.__SRV.pushText('本次消息A')")
        okA = p.wait_for("(function(){var b=document.querySelector('#opt2Stage [data-panel=\"recv\"]');return b&&String(b.textContent||'').indexOf('本次消息A')>=0;})()", 8)
        T("本次事件正常出现（本次消息A）", okA, "")
        recv2 = ev(p, "(function(){var b=document.querySelector('#opt2Stage [data-panel=\"recv\"]');return b?String(b.textContent||''):'';})()")
        T("本次仍不显示旧历史", ("旧文件" not in recv2) and ("旧消息" not in recv2), "")

        # ---------- B. 退出大屏：presence 立即 false，入口隐藏，轮询停止 ----------
        ev(p, "document.getElementById('o2sClose').click()")
        time.sleep(1.0)
        T("退出后 presence=离线", ev(p, "window.__SRV.cs().stage===false"), ev(p, "JSON.stringify(window.__SRV.cs())"))
        hidden = p.wait_for("(function(){var b=document.getElementById('opt2DropBtn');return !!b&&b.hidden===true;})()", 5)
        T("「大屏互联」入口隐藏", hidden, "")
        calls_now = ev(p, "window.__SRV.calls().filter(function(c){return c.path.indexOf('/presence')===0;}).length")
        time.sleep(3.2)
        calls_after = ev(p, "window.__SRV.calls().filter(function(c){return c.path.indexOf('/presence')===0;}).length")
        T("退出后无心跳/轮询继续产生", calls_after <= calls_now + 1, "%s -> %s" % (calls_now, calls_after))

        # ---------- C. 快速开关（/open 慢返回）不能把 presence 重新拉起来 ----------
        ev(p, "window.__SRV.setOpenDelay(900)")
        ev(p, "document.getElementById('opt2StageBtn').click()")
        time.sleep(0.15)
        ev(p, "document.getElementById('o2sClose').click()")
        close_t = ev(p, "Date.now()")
        time.sleep(2.6)
        T("快速退出后 presence 仍为离线（迟到的 /open 不会拉起）", ev(p, "window.__SRV.cs().stage===false"), ev(p, "JSON.stringify(window.__SRV.cs())"))
        # 再等一个心跳周期（10s），确认没有泄漏的 interval 在关闭后继续发 true
        time.sleep(10.5)
        late_true = ev(p, "(function(){var t=%d;return window.__SRV.calls().filter(function(c){return c.t>t+1200&&c.path.indexOf('/presence')===0&&c.body&&c.body.stage===true;}).length;})()" % close_t)
        T("关闭后无泄漏心跳（10s 内没有 stage:true POST）", late_true == 0, "late_true=%s" % late_true)
        ev(p, "window.__SRV.setOpenDelay(0)")

        # ---------- D. 重新打开：不显示上一次「本次消息A」 ----------
        ev(p, "document.getElementById('opt2StageBtn').click()")
        T("再次打开大屏", p.wait_for("(function(){var s=document.getElementById('opt2Stage');return s&&getComputedStyle(s).display!=='none';})()", 10))
        time.sleep(1.2)
        recv3 = ev(p, "(function(){var b=document.querySelector('#opt2Stage [data-panel=\"recv\"]');return b?String(b.textContent||''):'';})()")
        T("重开后不显示上一次数据（本次消息A）", "本次消息A" not in recv3, recv3[:160])
        T("重开后 presence 在线且 sinceSeq=当前最大 seq", ev(p, "window.__SRV.cs().stage===true") and
          ev(p, "Number(window.__SRV.cs().since)===window.__SRV.state().maxSeq"), ev(p, "JSON.stringify(window.__SRV.cs())"))

        # ---------- E. 控制器：在线时连接、退出后变「大屏已退出」 ----------
        ev(p, "window.__SRV.pushText('本次消息B')")
        ev(p, "location.hash='#drop'")
        T("控制器打开（在线）", p.wait_for("(function(){var c=document.getElementById('dropCtl');return c&&c.classList.contains('on');})()", 8))
        time.sleep(3.8)  # 等 presence+mine+/state 两轮轮询把「本次消息B」拉回
        ctl = ev(p, "(function(){var c=document.getElementById('dropCtl');return c?String(c.textContent||''):'';})()")
        T("控制器显示「已连接大屏」", "已连接大屏" in ctl, ctl[:120])
        T("控制器不显示旧历史（旧消息/旧文件）", ("旧消息" not in ctl) and ("旧文件" not in ctl), "")
        T("控制器显示本次消息B", "本次消息B" in ctl, ctl[-160:])
        # 模拟「另一台设备」视角：大屏 presence 掉线（不关闭本页大屏）→ 控制器应显示已退出并隐藏遥控区
        ev(p, "window.__SRV.forcePresenceOff()")
        off = p.wait_for("(function(){var c=document.getElementById('dropCtl');return c&&String(c.textContent||'').indexOf('大屏已退出')>=0;})()", 12)
        T("presence 掉线后控制器显示「大屏已退出」", off, "")
        ctl2 = ev(p, "(function(){var c=document.getElementById('dropCtl');return c?String(c.textContent||''):'';})()")
        T("掉线后控制器不再显示已连接/隐藏遥控区", ("已连接大屏" not in ctl2) and ("遥控大屏" not in ctl2), ctl2[:120])
        # 同设备关闭大屏 → 控制器随大屏一起收起
        ev(p, "document.getElementById('o2sClose').click()")
        closed = p.wait_for("(function(){var c=document.getElementById('dropCtl');return !c||!c.classList.contains('on');})()", 6)
        T("同设备关闭大屏 → 控制器收起", closed, "")
        # 清理 hash
        ev(p, "location.hash=''")

        errs = ev(p, "JSON.stringify({e:(window.__errs||[]),c:(window.__cerrs||[])})")
        ej = json.loads(errs)
        T("0 JS 报错 / 0 console.error", (len(ej["e"]) == 0) and (len(ej["c"]) == 0), str(ej)[:200])
    finally:
        try:
            p.close()
        except Exception:
            pass
        try:
            b.close()
        except Exception:
            pass
        httpd.shutdown()
        try:
            import shutil
            shutil.rmtree(TMP, ignore_errors=True)
        except Exception:
            pass

    print("\n==== RESULT: PASS=%d FAIL=%d ====" % (PASS, len(FAILS)))
    if FAILS:
        print("FAILED:", FAILS)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
