# -*- coding: utf-8 -*-
"""OPTIM V2 特性冒烟（无头 Edge，自建 harness，不改仓库测试）。

用法：cd web/tools && python tests/optim_v2_check.py [index.html]
两轮：
  main  : 非管理员、普通 UA —— 预设 / hash / 汇总按钮 / 备份存储用量 / toast 错误样式 / 0 报错
  admin : 管理员、微信 UA   —— 大屏演示 / 微信导出图弹层 + inert / 0 报错
退出码 0 = 全绿。
"""
import os
import sys
import json
import time
import threading
import http.server
import socketserver
import subprocess
import functools

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "..", "index.html")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8997
SID = "3260709999"
NAME = "测试同学"
WX_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49(0x1800312f) NetType/WIFI Language/zh_CN")

DATA = {
    "members": [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
                 "role": "", "badge": "", "is_admin": False} for i in range(1, 71)],
    "homework": [], "marks": [], "fitrecs": [], "notices": [],
    "tt": {"c": [], "t": "2026-08-31"},
}


def mock_head(admin):
    js = json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")
    return r"""
<script>
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
(function(){var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};})();
var DATA=__DATA__;
function ok(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
window.fetch=function(u,o){
  var s=String((u&&u.url!==undefined)?u.url:u);
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("rpc/class_members")>=0)return ok(DATA.members);
    if(s.indexOf("/notices")>=0)return ok(s.indexOf("select=id,ts")>=0?[]:DATA.notices);
    if(s.indexOf("/homework")>=0)return ok(DATA.homework);
    if(s.indexOf("/marks")>=0)return ok(DATA.marks);
    if(s.indexOf("/fitrecs")>=0)return ok(DATA.fitrecs);
    if(s.indexOf("/userdata")>=0)return ok([]);
    return ok([]);
  }
  if(s.indexOf("tt.json")>=0)return ok(DATA.tt);
  return ok([]);
};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:__ADMIN__,ts:Date.now()}));}catch(e){}
</script>
""".replace("__DATA__", js).replace("__SID__", SID).replace("__NAME__", NAME) \
   .replace("__ADMIN__", "true" if admin else "false")


RUNNER = r"""
<script>
(function(){
  window.__MODE="__MODE__";
  window.__opt={steps:[]};
  function T(k,ok,note){window.__opt.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
  function q(s){return document.querySelector(s);}
  function click(s){var e=q(s);if(e){e.click();return true;}return false;}
  function txt(s){var e=q(s);return e?String(e.textContent||"").trim():"";}
  function waitFor(fn,ms){return new Promise(function(res){var t0=Date.now();(function step(){try{if(fn())return res(true);}catch(e){}if(Date.now()-t0>=ms)return res(false);setTimeout(step,100);})();});}
  function toastInfo(){var t=q("#toast");return t?{text:String(t.textContent||""),err:t.classList.contains("err"),on:t.classList.contains("on"),role:t.getAttribute("role"),live:t.getAttribute("aria-live")}:null;}
  function report(slot){
    try{var x=new XMLHttpRequest();x.open("POST","/_report?slot="+slot,false);
        x.setRequestHeader("Content-Type","application/json");
        x.send(JSON.stringify({steps:window.__opt.steps,errs:window.__errs||[],cerrs:window.__cerrs||[]}));}catch(e){}
  }
  window.addEventListener("load",function(){
    setTimeout(async function(){
      try{
        for(var i=0;i<60;i++){ if(q("#aRun")&&q("#allCards"))break; await sleep(150); }
        T("页面启动（身份门禁通过）", !!q("#aRun")&&!!q("#allCards"), "");
        if(window.__MODE==="hash"){
          /* ===== 带 #tab= 直接打开 ===== */
          for(var hi=0;hi<40;hi++){ var hs=q("#s-hw"); if(hs&&hs.classList.contains("on"))break; await sleep(150); }
          var hsec=q("#s-hw");
          T("带 #tab= 打开可直达工具", !!hsec&&hsec.classList.contains("on"), String(location.hash||"")+" | "+(hsec?hsec.className:"none"));
        }else if(window.__MODE==="admin"){          /* ===== 管理员 + 微信 UA ===== */
          T("数据备份入口存在", !!q("#optBkBtn"), "");
          click('[data-tab="all"]'); await sleep(300);
          T("大屏演示入口（管理员）存在", !!q("#opt2StageBtn"), "");
          click("#opt2StageBtn"); await sleep(250);
          var st=q("#opt2Stage");
          T("大屏演示弹层可打开", !!st && st.style.display!=="none", st?st.style.display:"none");
          T("大屏时钟在走", /\d{2}:\d{2}:\d{2}/.test(txt("#o2sClock")), txt("#o2sClock"));
          T("大屏计时器存在", /05:00/.test(txt("#o2sTimer")), txt("#o2sTimer"));
          var pick=q('[data-o2pick="1"]'); if(pick)pick.click(); await sleep(120);
          T("抽签演示可点（无名单也不报错）", ["—","无名单"].indexOf(txt("#o2sPick"))>=0 || String(txt("#o2sPick")).length>0, txt("#o2sPick"));
          var w=q(".wrap");
          T("大屏打开时背景 inert", !(w&&("inert" in w)&&w.inert===false), (w&&("inert" in w))?String(w.inert):"no-inert");
          click("#o2sClose"); await sleep(150);
          T("大屏可关闭", q("#opt2Stage").style.display==="none", q("#opt2Stage").style.display);
          /* 微信内导出图：显示图 + 长按保存 */
          click('[data-tab="draw"]'); await sleep(200);
          click("#aRun"); await sleep(400);
          var cells=document.querySelectorAll("#aOut .rcell").length;
          T("抽签出结果", cells===10, "rcell="+cells);
          click("#aImg");
          await waitFor(function(){var o=q("#opt2ExpOv");return o&&o.style.display!=="none";},6000);
          await sleep(150);
          var ov=q("#opt2ExpOv"), img=q("#opt2ExpImg");
          T("微信内导出：出现图片弹层", !!ov && ov.style.display!=="none", ov?ov.style.display:"none");
          T("微信内导出：图片已生成", !!img && /^(blob:|data:)/.test(String(img.getAttribute("src")||"")), img?String(img.getAttribute("src")).slice(0,24):"");
          T("微信内导出：提示长按保存", txt("#opt2ExpOv").indexOf("长按")>=0, txt("#opt2ExpOv").slice(0,40));
          var w2=q(".wrap");
          T("导出弹层打开时背景 inert", w2&&("inert" in w2)&&w2.inert===true, w2&&("inert" in w2)?String(w2.inert):"no-inert");
          click("#opt2ExpClose");
          await waitFor(function(){var o=q("#opt2ExpOv");return !o||o.style.display==="none";},3000);
          T("导出弹层可关闭 + inert 复原", (!q("#opt2ExpOv")||q("#opt2ExpOv").style.display==="none") && (!("inert" in w2) || w2.inert===false), q("#opt2ExpOv")?q("#opt2ExpOv").style.display:"none");
        }else{
          /* ===== 非管理员、普通 UA ===== */
          T("toast 具备 ARIA live", !!q("#toast") && q("#toast").getAttribute("role")==="status" && q("#toast").getAttribute("aria-live")==="polite", q("#toast")?q("#toast").getAttribute("role"):"none");
          /* 抽签错误 → 错误样式 toast */
          q("#aStart").value="1"; q("#aEnd").value="1"; q("#aCount").value="5";
          click("#aRun"); await sleep(250);
          var ti=toastInfo();
          T("抽签校验错误 → toast.err", !!ti && ti.err===true, ti?ti.text:"none");
          /* 预设保存/载入 */
          T("预设控件存在", !!q("#opt2PresetRow")&&!!q("#opt2PreSave")&&!!q("#opt2PreLoad"), "");
          q("#aStart").value="3"; q("#aEnd").value="9"; q("#aCount").value="4";
          click("#opt2PreSave"); await sleep(150);
          q("#aStart").value="1"; q("#aEnd").value="2"; q("#aCount").value="1";
          click("#opt2PreLoad"); await sleep(150);
          T("预设保存后可载入", q("#aStart").value==="3" && q("#aEnd").value==="9" && q("#aCount").value==="4",
            [q("#aStart").value,q("#aEnd").value,q("#aCount").value].join("/"));
          /* 汇总入口 + 无数据错误 */
          T("点名汇总入口存在", !!q("#opt2RollSum"), "");
          T("水量汇总入口存在", !!q("#opt2WaterSum"), "");
          click("#opt2RollSum"); await sleep(200);
          T("点名无名单 → 错误提示", toastInfo() && toastInfo().err && String(toastInfo().text).indexOf("点名名单")>=0, toastInfo()?toastInfo().text:"");
          click("#opt2WaterSum"); await sleep(200);
          T("水量无记录 → 错误提示", toastInfo() && String(toastInfo().text).indexOf("抄表")>=0, toastInfo()?toastInfo().text:"");
          /* hash 直达 */
          click('[data-tab="hw"]'); await sleep(300);
          T("切工具写入 #tab= 直达", String(location.hash||"")==="#tab=hw", String(location.hash||""));
          var hset="";
          try{ history.replaceState(history.state||{},"","#tab=draw"); hset=String(location.hash||""); window.dispatchEvent(new Event("hashchange")); }catch(e){ hset="ERR:"+(e&&e.message||e); }
          await waitFor(function(){var s=q("#s-draw");return s&&s.classList.contains("on");},3000);
          var sec=q("#s-draw");
          T("hashchange 可切回工具", !!sec && sec.classList.contains("on"), "set="+hset+" now="+String(location.hash||"")+" cls="+(sec?sec.className:"none"));
          /* 打印按钮 + 备份存储用量 */
          T("打印入口存在（作业/结果单）", !!q("#opt2Print_hImg")&&!!q("#opt2Print_sImg"), "");
          T("非管理员无大屏入口", !q("#opt2StageBtn"), "");
          click('[data-tab="all"]'); await sleep(300);
          click("#optBkBtn"); await sleep(500);
          T("备份弹层显示本机存储用量", txt("#opt2BkUsage").indexOf("本机存储")>=0, txt("#opt2BkUsage"));
          click("#optBkClose"); await sleep(120);
        }
        T("0 JS 报错", (window.__errs||[]).length===0, JSON.stringify(window.__errs||[]).slice(0,400));
        T("0 console.error", (window.__cerrs||[]).length===0, JSON.stringify(window.__cerrs||[]).slice(0,400));
      }catch(e){
        window.__opt.steps.push({k:"脚本异常",ok:false,note:String(e&&e.stack||e)});
      }
      report(window.__MODE||"main");
    }, 900);
  });
})();
</script>
"""


def build_preview(name, admin, mode):
    html = open(SRC, encoding="utf-8", newline="").read()
    html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock_head(admin), 1)
    runner = RUNNER.replace("__MODE__", mode)
    html = html.replace("</body>", runner + "\n</body>", 1)
    path = os.path.join(HERE, name)
    open(path, "w", encoding="utf-8", newline="").write(html)
    return name


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        slot = "main"
        try:
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            slot = (q.get("slot") or ["main"])[0]
        except Exception:
            pass
        open(os.path.join(HERE, "report_%s.json" % slot), "wb").write(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def run_one(page, slot, wx, suffix="", timeout=100):
    report = os.path.join(HERE, "report_%s.json" % slot)
    if os.path.exists(report):
        os.remove(report)
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
            "--force-device-scale-factor=1", "--window-size=430,940",
            "--virtual-time-budget=16000"]
    if wx:
        args.append("--user-agent=" + WX_UA)
    args.append("http://127.0.0.1:%d/%s%s" % (PORT, page, suffix))
    subprocess.run(args, capture_output=True, timeout=timeout)
    data = None
    for _ in range(40):
        if os.path.exists(report):
            time.sleep(0.2)
            try:
                data = json.loads(open(report, encoding="utf-8", errors="replace").read())
                break
            except Exception:
                pass
        time.sleep(0.3)
    return data


def main():
    socketserver.TCPServer.allow_reuse_address = True
    Handler2 = functools.partial(Handler, directory=HERE)
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler2)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    bad = 0
    try:
        p1 = build_preview("v2_check_main.html", False, "main")
        p2 = build_preview("v2_check_admin.html", True, "admin")
        p3 = build_preview("v2_check_hash.html", False, "hash")
        for page, slot, wx, suf in ((p1, "main", False, ""), (p2, "admin", True, ""), (p3, "hash", False, "#tab=hw")):
            print("===== %s =====" % slot)
            data = run_one(page, slot, wx, suf)
            if not data:
                print("FAIL: 未收到 %s 报告" % slot)
                bad += 1
                continue
            for s in data.get("steps", []):
                ok = bool(s.get("ok"))
                if not ok:
                    bad += 1
                print("%s  %s%s" % ("PASS" if ok else "FAIL", s.get("k", ""),
                                    ("  [" + str(s.get("note", "")) + "]") if s.get("note") else ""))
            if data.get("errs"):
                print("JS-ERR ", data["errs"][:5])
            if data.get("cerrs"):
                print("CONSOLE-ERR ", data["cerrs"][:5])
        print("RESULT %s (%d fails)" % ("GREEN" if bad == 0 else "RED", bad))
        return 0 if bad == 0 else 1
    finally:
        httpd.shutdown()
        for n in ("v2_check_main.html", "v2_check_admin.html", "v2_check_hash.html"):
            try:
                os.remove(os.path.join(HERE, n))
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
