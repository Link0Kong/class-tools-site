# -*- coding: utf-8 -*-
"""网页端扫码登录专项自检（__QR_LOGIN_V1__ / ECS `/account/qr/*`）

覆盖：
  A. 身份页「扫码登录」入口 → 二维码弹层（票据/二维码像素/通用·鸿蒙切换）
  B. 桌面轮询 wait→ok 自动进入班级；成功后停止轮询
  C. 关闭弹层立即停止轮询；票据过期自动刷新
  D. 扫码服务不可用（建票失败）降级
  E. 手机确认页（已登录一键确认 / 学号+姓名 / 401 回退 / 无效二维码）
  F. 430/360 无横向溢出、0 JS 报错、0 外部请求

运行：cd web/tools && python tests\\v2_qr_login_check.py
截图：tools/tests/_shots_qr/
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
ROOT = os.path.dirname(HERE)
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

SHOTS = os.path.join(HERE, "_shots_qr")
os.makedirs(SHOTS, exist_ok=True)
PORT = 8981
BASE = "http://127.0.0.1:%d" % PORT
TID = "0123456789abcdef0123456789abcdef"
RESULTS = []


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)[:300]})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)[:200]) if note else ""))


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class _Srv(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


def serve(d, p):
    h = lambda *a, **kw: Q(*a, directory=d, **kw)  # noqa: E731
    s = _Srv(("127.0.0.1", p), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


MOCK_JS = r"""
(function(){
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var qs={};
String(location.search||"").replace(/^\?/,"").split("&").forEach(function(kv){
  if(!kv)return;var i=kv.indexOf("=");var k=decodeURIComponent(i<0?kv:kv.slice(0,i));var v=decodeURIComponent(i<0?"":kv.slice(i+1));qs[k]=v;
});
var CFG={};try{CFG=JSON.parse(localStorage.getItem("__qr_cfg")||"{}");}catch(e){CFG={};}
var M=window.__M={creates:0,polls:0,authorizes:[],denies:0,external:[],mode:CFG.mode||"ok",auth:CFG.auth||"",t:"",seq:0};
function newT(){M.seq++;var s=("0000000000000000"+M.seq.toString(16)).slice(-16);return s+s;}
try{
  if(CFG.id==="1"){
    localStorage.setItem("zq_class_identity",JSON.stringify({token:"qa-token",sid:"9999000001",name:"测试同学",role:"班长",badge:"班委",is_admin:false,ts:Date.now()}));
  }else{
    localStorage.removeItem("zq_class_identity");
  }
  localStorage.removeItem("zq_last_identity");
}catch(e){}
function resp(st,obj){return Promise.resolve({ok:st>=200&&st<300,status:st,
  json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve(JSON.stringify(obj));}});}
var MEMBERS=[{seat:1,sid:"9999000001",name:"测试同学",role:"班长",badge:"班委",is_admin:false}];
window.fetch=function(u,o){
  o=o||{};
  var s=String((u&&u.url!==undefined)?u.url:u);
  var headers={};try{Object.keys(o.headers||{}).forEach(function(k){headers[String(k).toLowerCase()]=String(o.headers[k]);});}catch(e){}
  if(s.indexOf("/account/qr/")>=0){
    var path=s.replace(/^.*\/account/,"").split("?")[0];
    if(path==="/qr/create"){
      M.creates++;
      if(M.mode==="createfail")return resp(503,{ok:false,code:"unavailable",message:"down"});
      M.t=newT();
      return resp(200,{ok:true,t:M.t,k:"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",ttl:180,exp:Math.floor(Date.now()/1000)+180});
    }
    if(path==="/qr/poll"){
      M.polls++;
      if(M.mode==="net")return Promise.reject(new Error("net"));
      if(M.mode==="slow")return resp(200,{ok:true,status:"wait"});
      if(M.mode==="expire"&&M.polls===1)return resp(200,{ok:true,status:"expired"});
      if(M.mode==="deny"&&M.polls===1)return resp(200,{ok:true,status:"deny"});
      if(M.polls<2)return resp(200,{ok:true,status:"wait"});
      return resp(200,{ok:true,status:"ok",token:"qr-token",sid:"9999000001",name:"测试同学",
        role:"班长",badge:"班委",is_admin:false,provider:"",via:"web"});
    }
    if(path==="/qr/authorize"){
      var tok=headers["x-class-token"]||"";
      var body=null;try{body=JSON.parse(o.body||"{}");}catch(e){}
      M.authorizes.push({t:body&&body.t,token:tok,body:body||{}});
      if(M.auth==="401"&&tok==="qa-token")return resp(401,{ok:false,code:"unauthorized",message:"身份已失效，请重新登录"});
      return resp(200,{ok:true,name:"测试同学"});
    }
    if(path==="/qr/deny"){M.denies++;return resp(200,{ok:true});}
  }
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_verify")>=0)return resp(200,{ok:true,token:"qa-new-token",sid:"9999000001",name:"测试同学",role:"班长",badge:"班委",is_admin:false});
    if(s.indexOf("rpc/class_whoami")>=0)return resp(200,{ok:true,sid:"9999000001",name:"测试同学"});
    if(s.indexOf("rpc/class_members")>=0)return resp(200,MEMBERS);
    if(s.indexOf("rpc/class_league")>=0)return resp(200,[]);
    if(s.indexOf("rpc/class_whoami")>=0)return resp(200,{ok:true,sid:"9999000001",name:"测试同学"});
    if(s.indexOf("class_notices_meta")>=0)return resp(200,{ok:true,items:[],ids:[],hidden:[],edited:[]});
    if(s.indexOf("/notices")>=0)return resp(200,[]);
    if(s.indexOf("/homework")>=0)return resp(200,[]);
    if(s.indexOf("/marks")>=0)return resp(200,[]);
    if(s.indexOf("/fitrecs")>=0)return resp(200,[]);
    if(s.indexOf("/userdata")>=0)return resp(200,[]);
    if(s.indexOf("/power")>=0)return resp(200,[]);
    return resp(200,[]);
  }
  if(s.indexOf("tt.json")>=0)return resp(200,{c:[],t:"",meta:{}});
  if(s.indexOf("/drop/presence")>=0)return resp(200,{ok:true,stage:false,at:0});
  if(s.indexOf("/map/api/")>=0)return resp(200,{ok:true});
  M.external.push(s.slice(0,160));
  return Promise.reject(new Error("external-blocked"));
};
})();
"""


def ev(pg, expr, ap=False):
    return pg.evaluate(expr, await_promise=ap)


def jsq(s):
    return json.dumps(s, ensure_ascii=False)


def click(pg, sel):
    # 2026-11-23 合规：确认登录前需勾选《用户协议》《隐私政策》（#qrCGo 默认 disabled）
    if sel == "#qrCGo":
        ev(pg, "(function(){var a=document.getElementById('qrAgree');if(a){a.checked=true;"
               "a.dispatchEvent(new Event('change'));}return true;})()")
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.click();return true;})()" % jsq(sel))


def set_val(pg, sel, v):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.value=%s;"
                 "e.dispatchEvent(new Event('input',{bubbles:true}));return true;})()" % (jsq(sel), jsq(v)))


def txt(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);return e?String(e.textContent||''):'';})()" % jsq(sel))


def visible(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;"
                  "var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;"
                  "var r=e.getBoundingClientRect();return r.width>0&&r.height>0;})()" % jsq(sel))


def qr_state(pg):
    return ev(pg, "(function(){return window.__qrLogin?window.__qrLogin.state():null;})()") or {}


def mock(pg):
    return ev(pg, "window.__M") or {}


def set_cfg(pg, cfg):
    ev(pg, "localStorage.setItem('__qr_cfg', %s)" % json.dumps(json.dumps(cfg, ensure_ascii=False)))


def goto(pg, cfg, path):
    set_cfg(pg, cfg)
    pg.navigate(BASE + path)
    pg.wait_load(25)


def fresh(b, cfg, path, w=430, h=900, mobile=True):
    pg = b.new_page("about:blank")
    pg.set_device(w, h, 2.0, mobile, mobile)
    pg.add_init_script(MOCK_JS)
    pg.navigate(BASE + "/index.html?prime=1")
    pg.wait_load(20)
    goto(pg, cfg, path)
    return pg


def no_overflow(pg):
    return bool(ev(pg, "document.documentElement.scrollWidth<=window.innerWidth+1 && "
                       "document.body.scrollWidth<=window.innerWidth+1"))


def canvas_has_code(pg):
    return bool(ev(pg, r"""(function(){
      var c=document.querySelector('#qrCanvas');if(!c)return false;
      var d=c.getContext('2d').getImageData(0,0,c.width,c.height).data,n=0;
      for(var i=0;i<d.length;i+=4){if(d[i]<90&&d[i+1]<90&&d[i+2]<90)n++;}
      return n>200;
    })()"""))


def canvas_sig(pg):
    return ev(pg, r"""(function(){
      var c=document.querySelector('#qrCanvas');if(!c)return '';
      var d=c.getContext('2d').getImageData(0,0,c.width,c.height).data,s=0;
      for(var i=0;i<d.length;i+=41){s=(s*131+d[i])>>>0;}
      return String(s);
    })()""")


def main():
    srv = serve(ROOT, PORT)
    b = _cdp.Browser(window=(1280, 900))
    try:
        # ================= A/B：桌面扫码 → 自动进入 =================
        pg = fresh(b, {"id": "0", "mode": "ok"}, "/index.html?n=1", 1280, 900, mobile=False)
        gate = pg.wait_for("document.body.classList.contains('id-locked') && !!document.querySelector('#igQr')", 20)
        T("A1 未登录身份页出现「扫码登录」入口", gate and visible(pg, "#igQr"))
        T("A2 初始二维码弹层隐藏", not visible(pg, "#qrOv"))
        T("A2b 扫码入口点按高度 ≥40px",
          ev(pg, "document.querySelector('#igQr').getBoundingClientRect().height>=39.5"))
        pg.screenshot(os.path.join(SHOTS, "qr_identity_entry_1280.png"))

        click(pg, "#igQr")
        ok_open = pg.wait_for("window.__qrLogin && window.__qrLogin.state().open && "
                              "window.__qrLogin.state().t.length===32", 8)
        st = qr_state(pg)
        T("A3 点扫码登录：建票并显示弹层", ok_open and visible(pg, "#qrOv") and mock(pg).get("creates") == 1,
          "t=%s" % str(st.get("t"))[:8])
        T("A4 二维码已绘制（画布深色模块 >200）", canvas_has_code(pg))
        T("A5 二维码链接只含票据与通用类型（无 token/k、无品牌参数）",
          ("#qr=" in str(st.get("link"))) and ("&p=" not in str(st.get("link")))
          and ("bbbbbbbb" not in str(st.get("link"))), st.get("link"))
        T("A6 默认「通用」分段选中", ev(pg, "document.querySelector('#qrSeg [data-qrp=\"any\"]').classList.contains('on')"))
        sig1 = canvas_sig(pg)

        click(pg, '#qrSeg [data-qrp="harmony"]')
        pg.sleep(0.15)
        st2 = qr_state(pg)
        T("A7 切到鸿蒙：链接 p=harmony、二维码重绘",
          st2.get("p") == "harmony" and "p=harmony" in str(st2.get("link")) and canvas_sig(pg) != sig1)
        T("A8 分段 aria-selected 同步",
          ev(pg, "document.querySelector('#qrSeg [data-qrp=\"harmony\"]').getAttribute('aria-selected')==='true'"))
        pg.screenshot(os.path.join(SHOTS, "qr_desktop_overlay_1280.png"))

        entered = pg.wait_for("window.__qrLogin && window.__qrLogin.auth() && window.__qrLogin.auth().ready===true", 12)
        T("B1 手机确认后桌面自动进入班级",
          entered and ev(pg, "(function(){var a=window.__qrLogin.auth();return !!a&&a.name==='测试同学'&&a.token==='qr-token';})()"),
          ev(pg, "(function(){var a=window.__qrLogin.auth()||{};return (a.name||'')+'/'+(a.role||'')+'/'+String(a.is_admin);})()"))
        T("B2 进入后弹层关闭、身份门禁移除",
          (not visible(pg, "#qrOv")) and (not ev(pg, "document.body.classList.contains('id-locked')"))
          and (not ev(pg, "document.body.classList.contains('auth-pending')")))
        p1 = mock(pg).get("polls") or 0
        pg.sleep(1.6)
        p2 = mock(pg).get("polls") or 0
        T("B3 登录成功后停止轮询", p1 == p2, "polls %s→%s" % (p1, p2))
        T("B4 建票只发生一次（未误刷新）", mock(pg).get("creates") == 1)
        pg.screenshot(os.path.join(SHOTS, "qr_desktop_after_login.png"))
        pg.close()

        # ================= C：关弹层停轮询 / 过期自动刷新 =================
        pg = fresh(b, {"id": "0", "mode": "slow"}, "/index.html?n=2", 1280, 900, mobile=False)
        pg.wait_for("document.body.classList.contains('id-locked')", 20)
        click(pg, "#igQr")
        pg.wait_for("window.__qrLogin && window.__qrLogin.state().t.length===32", 8)
        click(pg, "#qrClose")
        pg.sleep(0.2)
        c1 = mock(pg).get("polls") or 0
        pg.sleep(1.7)
        T("C1 关闭弹层立即停止轮询且弹层隐藏",
          (mock(pg).get("polls") or 0) == c1 and not visible(pg, "#qrOv"), "polls=%s" % c1)
        T("C2 关闭后清空票据（链接不再含 #qr）", not qr_state(pg).get("t"))

        goto(pg, {"id": "0", "mode": "expire"}, "/index.html?n=3")
        pg.wait_for("document.body.classList.contains('id-locked')", 20)
        click(pg, "#igQr")
        refreshed = pg.wait_for("window.__M.creates>=2", 10)
        T("C3 票据过期后自动刷新二维码", refreshed, "creates=%s" % (mock(pg).get("creates")))
        entered2 = pg.wait_for("window.__qrLogin && window.__qrLogin.auth() && window.__qrLogin.auth().ready===true", 12)
        T("C4 刷新后的票据仍可完成登录",
          entered2 and ev(pg, "(function(){var a=window.__qrLogin.auth();return !!a&&a.token==='qr-token';})()"))

        goto(pg, {"id": "0", "mode": "createfail"}, "/index.html?n=4")
        pg.wait_for("document.body.classList.contains('id-locked')", 20)
        click(pg, "#igQr")
        pg.sleep(0.8)
        st = qr_state(pg)
        T("D1 扫码服务不可用时给出错误态且可刷新",
          ("暂不可用" in txt(pg, "#qrState")) and visible(pg, "#qrRefresh") and st.get("busy") is False,
          txt(pg, "#qrState") + " creates=" + str(mock(pg).get("creates")))
        click(pg, "#qrClose")

        # 溢出：430 / 360
        for w in (430, 360):
            pg.set_device(w, 800, 2.0, True, True)
            pg.sleep(0.2)
            click(pg, "#igQr")
            pg.sleep(0.5)
            T("F1 %spx 扫码弹层无横向溢出" % w, no_overflow(pg))
            click(pg, "#qrClose")
        pg.close()

        # ================= E：手机确认页 =================
        pg = fresh(b, {"id": "1", "mode": "ok"}, "/index.html?n=5#qr=" + TID, 430, 860, mobile=True)
        ok_gate = pg.wait_for("document.body.classList.contains('qr-locked')", 20)
        T("E1 手机扫码打开：进入确认页并清掉地址栏票据",
          ok_gate and visible(pg, "#qrGate") and ev(pg, "location.hash===''"),
          "hash=%r" % ev(pg, "location.hash"))
        T("E2 已登录：展示姓名、隐藏学号表单、按钮文案「确认登录」",
          txt(pg, "#qrCWho") == "测试同学" and (not visible(pg, "#qrCForm"))
          and txt(pg, "#qrCGo") == "确认登录" and "手机" in txt(pg, "#qrCSub")
          and "鸿蒙" not in txt(pg, "#qrCSub"))
        pg.screenshot(os.path.join(SHOTS, "qr_phone_confirm_430.png"))

        click(pg, "#qrCGo")
        pg.wait_for("window.__M.authorizes.length===1", 8)
        a = (mock(pg).get("authorizes") or [{}])[0]
        T("E3 一键确认：带本机 token 授权票据（t/p/via 正确）",
          a.get("token") == "qa-token" and a.get("t") == TID and (a.get("body") or {}).get("p") == "any"
          and (a.get("body") or {}).get("via") == "web", json.dumps(a, ensure_ascii=False)[:160])
        done = pg.wait_for("document.body.classList.contains('qr-done')", 8)
        T("E4 授权成功显示完成态", done and visible(pg, "#qrCOk") and txt(pg, "#qrCOk b") == "已确认登录")
        pg.screenshot(os.path.join(SHOTS, "qr_phone_done_430.png"))
        entered3 = pg.wait_for("window.__qrLogin && window.__qrLogin.auth() && window.__qrLogin.auth().ready===true", 10)
        T("E5 手机端继续进入班级且确认层移除",
          entered3 and ev(pg, "(function(){var a=window.__qrLogin.auth();return !!a&&a.name==='测试同学'&&a.token==='qa-token';})()")
          and (not ev(pg, "document.body.classList.contains('qr-locked')")))
        pg.close()

        # 未登录：学号 + 姓名
        pg = fresh(b, {"id": "0", "mode": "ok"}, "/index.html?n=6#qr=" + TID + "&p=harmony", 430, 860, mobile=True)
        pg.wait_for("document.body.classList.contains('qr-locked')", 20)
        T("E6 未登录：显示学号/姓名表单与「登录并确认」",
          visible(pg, "#qrCForm") and (not visible(pg, "#qrCWho")) and txt(pg, "#qrCGo") == "登录并确认"
          and "鸿蒙" in txt(pg, "#qrCSub"))
        set_val(pg, "#qrSid", "9999000001")
        set_val(pg, "#qrName", "测试同学")
        click(pg, "#qrCGo")
        pg.wait_for("window.__M.authorizes.length===1", 10)
        a2 = (mock(pg).get("authorizes") or [{}])[0]
        T("E7 学号+姓名核验后授权（用新 token，不泄露到页面）",
          a2.get("token") == "qa-new-token" and a2.get("t") == TID, a2.get("token"))
        entered4 = pg.wait_for("window.__qrLogin && window.__qrLogin.auth() && window.__qrLogin.auth().ready===true", 10)
        T("E8 手机端进入班级",
          entered4 and ev(pg, "(function(){var a=window.__qrLogin.auth();return !!a&&a.name==='测试同学'&&a.token==='qa-new-token';})()"))
        pg.close()

        # 401：已登录 token 失效 → 回退表单
        pg = fresh(b, {"id": "1", "auth": "401", "mode": "ok"},
                   "/index.html?n=7#qr=" + TID, 430, 860, mobile=True)
        pg.wait_for("document.body.classList.contains('qr-locked')", 20)
        click(pg, "#qrCGo")
        fallback = pg.wait_for("document.querySelector('#qrCForm') && !document.querySelector('#qrCForm').hidden && "
                               "document.querySelector('#qrCErr').textContent.length>0", 8)
        T("E9 本机 token 失效：回到学号+姓名表单并提示", fallback and "身份已失效" in txt(pg, "#qrCErr"),
          txt(pg, "#qrCErr"))
        set_val(pg, "#qrSid", "9999000001")
        set_val(pg, "#qrName", "测试同学")
        click(pg, "#qrCGo")
        pg.wait_for("window.__M.authorizes.length>=2", 10)
        T("E10 回退后重新核验可完成确认",
          (mock(pg).get("authorizes") or [{}, {}])[-1].get("token") == "qa-new-token")

        goto(pg, {"id": "0", "mode": "ok"}, "/index.html?n=8#qr=zzz")
        bad = pg.wait_for("document.body.classList.contains('qr-locked')", 10)
        T("E11 无效二维码：错误页 + 返回首页",
          bad and txt(pg, "#qrCTitle") == "二维码无效" and (not visible(pg, "#qrCGo"))
          and txt(pg, "#qrCCancel") == "返回首页")

        # 360 溢出 + 报错/外部请求
        pg.set_device(360, 760, 2.0, True, True)
        pg.sleep(0.2)
        T("F2 360px 手机确认页无横向溢出", no_overflow(pg))
        errs = pg.all_errors()
        T("F3 0 JS 异常 / 0 console.error",
          not errs.get("exceptions") and not errs.get("console") and not (ev(pg, "window.__errs.length")),
          json.dumps(errs, ensure_ascii=False)[:200] + " win=" + str(ev(pg, "window.__errs")))
        ext = ev(pg, "window.__M.external") or []
        T("F4 0 外部请求（只允许 CloudBase / /account/qr）", not ext, json.dumps(ext, ensure_ascii=False)[:200])
        pg.screenshot(os.path.join(SHOTS, "qr_phone_bad_360.png"))
        pg.close()
    finally:
        try:
            b.close()
        except Exception:
            pass
        srv.shutdown()
        srv.server_close()

    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("\n=== 扫码登录自检 %d/%d ===" % (passed, total))
    bad = [r for r in RESULTS if not r["ok"]]
    for r in bad:
        print("FAIL:", r["name"], "|", r["note"])
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
