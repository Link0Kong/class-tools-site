# -*- coding: utf-8 -*-
"""OPTIM V1 特性的无头浏览器冒烟测试（自建 harness，不改仓库测试）。

用法：cd web/tools && python tests/optim_v1_check.py [index.html]
断言：
  1) 抽签：出结果后出现「池/已抽」状态行，且 zq_draw_last_v1 已写入本机
  2) 重置后出现「上次结果 · 恢复」行，点恢复能还原结果
  3) 全部页：作业卡出现「未完成 N」摘要；存在「数据备份」入口
  4) 备份弹层能打开/关闭，含导出/导入按钮
  5) 0 JS 报错 / 0 console.error
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
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
SRC = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "..", "index.html")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8994
REPORT_DIR = os.path.join(HERE, "_optim_v1_reports")
os.makedirs(REPORT_DIR, exist_ok=True)
REPORT = os.path.join(REPORT_DIR, "optim_report.json")
PREVIEW = os.path.join(REPORT_DIR, "optim_preview.html")

SID = "3260709999"
NAME = "测试同学"

DATA = {
    "members": [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
                 "role": "", "badge": "", "is_admin": False} for i in range(1, 71)],
    "homework": [{"id": "hw_opt_1", "subject": "测试作业", "content": "完成练习",
                  "due": "", "date": "2099-01-01", "time": "", "done": False}],
    "marks": [], "fitrecs": [], "notices": [],
    "tt": {"c": [], "t": "2026-08-31"},
}

MOCK_HEAD = r"""
<script>
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
(function(){var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};})();
window.confirm=function(){return true;};
var DATA=__DATA__;
function ok(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
var _f=window.fetch;
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
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
</script>
"""

RUNNER = r"""
<script>
(function(){
  window.__opt={steps:[],phase:0};
  function T(k,ok,note){window.__opt.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
  function q(s){return document.querySelector(s);}
  function qa(s){return Array.prototype.slice.call(document.querySelectorAll(s));}
  function click(s){var e=q(s);if(e){e.click();return true;}return false;}
  function report(){
    try{var x=new XMLHttpRequest();x.open("POST","/_report",false);
        x.setRequestHeader("Content-Type","application/json");
        x.send(JSON.stringify({steps:window.__opt.steps,errs:window.__errs||[],cerrs:window.__cerrs||[]}));}catch(e){}
  }
  window.addEventListener("load",function(){
    setTimeout(async function(){
      try{
        T("页面启动（身份门禁通过）", !!q("#aOut") && !!q("#aRun"), "");
        /* 1) 抽签出结果 + 状态行 + 本机记忆 */
        click('[data-tab="draw"]');
        await sleep(150);
        T("抽签入口存在", click("#aRun"), "");
        await sleep(450);
        var cells=qa("#aOut .rcell").length;
        T("抽签出结果", cells===10, "rcell="+cells);
        var st=q("#optDrawStat"), stTxt=st?String(st.textContent):"";
        T("状态行含「池/已抽」", !!st && stTxt.indexOf("池")>=0 && stTxt.indexOf("已抽")>=0, stTxt);
        T("上次结果写入本机 zq_draw_last_v1", !!localStorage.getItem("zq_draw_last_v1"), "");
        /* 2) 重置 -> 出现「上次结果 · 恢复」 */
        click("#aReset");
        await sleep(250);
        var st2=q("#optDrawStat"), st2Txt=st2?String(st2.textContent):"";
        T("重置后出现「上次结果」行", !!st2 && st2Txt.indexOf("上次结果")>=0, st2Txt);
        var rb=st2?st2.querySelector("button"):null;
        if(rb)rb.click();
        await sleep(250);
        var back=qa("#aOut .rcell").length;
        T("点「恢复」能还原结果", back>0, "rcell="+back);
        /* 3) 全部页卡片摘要 + 数据备份入口（先进入作业页触发整表拉取） */
        click('[data-tab="hw"]');
        await sleep(700);
        click('[data-tab="all"]');
        await sleep(300);
        var hwMeta=q('#allCards [data-card="hw"] .cardmeta');
        T("作业卡出现「未完成」摘要", !!hwMeta && String(hwMeta.textContent).indexOf("未完成")>=0, hwMeta?String(hwMeta.textContent):"");
        T("数据备份入口存在", !!q("#optBkBtn"), "");
        click("#optBkBtn");
        await sleep(120);
        var ov=q("#optBkOv");
        T("备份弹层可打开", !!ov && ov.style.display!=="none", ov?ov.style.display:"none");
        T("备份弹层含导出/导入按钮", !!q("#optBkOut") && !!q("#optBkIn"), "");
        click("#optBkClose");
        await sleep(80);
        T("备份弹层可关闭", !!ov && ov.style.display==="none", ov?ov.style.display:"none");
        /* 4) 0 报错 */
        T("0 JS 报错", (window.__errs||[]).length===0, JSON.stringify(window.__errs||[]).slice(0,400));
        T("0 console.error", (window.__cerrs||[]).length===0, JSON.stringify(window.__cerrs||[]).slice(0,400));
      }catch(e){
        window.__opt.steps.push({k:"脚本异常",ok:false,note:String(e&&e.stack||e)});
      }
      report();
    }, 900);
  });
})();
</script>
"""


def build_preview():
    html = open(SRC, encoding="utf-8", newline="").read()
    mock = MOCK_HEAD.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")) \
                    .replace("__SID__", SID).replace("__NAME__", NAME)
    if '<meta charset="utf-8">' in html:
        html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + mock, 1)
    else:
        html = html.replace("<head>", "<head>" + mock, 1)
    html = html.replace("</body>", RUNNER + "\n</body>", 1)
    open(PREVIEW, "w", encoding="utf-8", newline="").write(html)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        open(REPORT, "wb").write(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def main():
    build_preview()
    Handler2 = functools.partial(Handler, directory=HERE)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler2)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    if os.path.exists(REPORT):
        os.remove(REPORT)
    try:
        shot = os.environ.get("OPTIM_SHOT", "")
        args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                "--force-device-scale-factor=1", "--window-size=430,940",
                "--virtual-time-budget=12000"]
        if shot:
            args.append("--screenshot=" + shot)
        rel = os.path.relpath(PREVIEW, HERE).replace("\\", "/")
        args.append("http://127.0.0.1:%d/%s" % (PORT, rel))
        subprocess.run(args, capture_output=True, timeout=120)
        data = None
        for _ in range(30):
            if os.path.exists(REPORT):
                time.sleep(0.2)
                data = json.loads(open(REPORT, encoding="utf-8", errors="replace").read())
                break
            time.sleep(0.4)
        if not data:
            print("FAIL: 未收到报告（页面可能未启动/提前崩溃）")
            return 1
        bad = 0
        for s in data.get("steps", []):
            tag = "PASS" if s["ok"] else "FAIL"
            if not s["ok"]:
                bad += 1
            print("%s  %s%s" % (tag, s["k"], ("  [" + s["note"] + "]") if s["note"] else ""))
        if data.get("errs"):
            print("JS-ERR ", data["errs"][:5])
        if data.get("cerrs"):
            print("CONSOLE-ERR ", data["cerrs"][:5])
        print("RESULT %s (%d fails)" % ("GREEN" if bad == 0 else "RED", bad))
        return 0 if bad == 0 else 1
    finally:
        httpd.shutdown()
        try:
            os.remove(PREVIEW)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
