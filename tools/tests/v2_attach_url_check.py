# -*- coding: utf-8 -*-
"""通知附件 URL 兼容专项检查（迁移第 2 步，网页端）。

对象：`web/tools/notice-board-live-demo.html`（headless Edge，注入断言脚本，不改源文件）。
覆盖：文件行/图片行在「签名 https URL」与「data URI」两种形态下的渲染；URL 文件预览为下载提示；
      页面无 JS 报错。运行：cd web/tools && python tests\\v2_attach_url_check.py
"""
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEMO = os.path.abspath(os.environ.get("V2D_DEMO") or os.path.join(ROOT, "notice-board-live-demo.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8996
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_v2_notice_reports")

CHECK_JS = r"""
<script>
(function(){
var R={steps:[]};
function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
function post(){try{var x=new XMLHttpRequest();x.open("POST","/report?slot=attach_url",false);x.send(JSON.stringify(R));}catch(e){}}
try{
  var g1={id:"gtest1",items:[]};
  var f1={kind:"file",label:"附件",time:"11-10 10:00",name:"a.docx",size:"82 KB",url:"https://example.test/att/abcderf?exp=1&sig=x"};
  g1.items=[f1];
  var h1=itemHTML(g1,f1,0);
  T("E1 URL 文件行含 href URL", h1.indexOf("https://example.test/att/abcderf")>=0, "");
  T("E2 URL 文件行显示 size", h1.indexOf("82 KB")>=0, "");
  T("E3 URL 文件行不显示 0 B", h1.indexOf("0 B")<0, "");
  T("E4 URL DOCX 文件行不带 PDF 标记", h1.indexOf(" · PDF")<0, "");

  var f2={kind:"file",label:"附件",name:"b.docx",url:"data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,"+btoa("hello")};
  var g2={id:"gtest2",items:[f2]};
  var h2=itemHTML(g2,f2,0);
  T("E5 data URI 文件行仍正常", h2.indexOf("data:application/vnd")>=0 && h2.indexOf("附件 · ")>=0, "");

  var im={kind:"img",src:"https://example.test/att/imgabc?exp=1&sig=y",caption:"图"};
  var g3={id:"gtest3",items:[im]};
  var h3=itemHTML(g3,im,0);
  T("E6 URL 图片直接渲染", h3.indexOf("https://example.test/att/imgabc")>=0 && h3.indexOf("<img")>=0, "");

  GROUPS.push(g1);
  openFile("gtest1",0);
  var mh=(document.getElementById("modal")||{}).innerHTML||"";
  T("E7 URL DOCX 预览为下载提示（无 iframe）", mh.indexOf("下载原文件")>=0 && mh.indexOf("<iframe")<0 && mh.indexOf("missbox")>=0, "");
  closeModal();
  GROUPS.pop();

  var f3={kind:"file",label:"附件",name:"c.pdf",url:"data:application/pdf;base64,"+btoa("%PDF-1.4 test")};
  var g4={id:"gtest4",items:[f3]};
  GROUPS.push(g4);
  openFile("gtest4",0);
  var mh2=(document.getElementById("modal")||{}).innerHTML||"";
  T("E8 data URI PDF 仍用 iframe 预览", mh2.indexOf("<iframe")>=0, "");
  closeModal();
  GROUPS.pop();

  T("E9 无 JS 报错", (window.__errs||[]).length===0, JSON.stringify(window.__errs||[]));
}catch(e){T("E0 脚本异常", false, String(e));}
post();
})();
</script>
"""

ERR_JS = r"""
<script>window.__errs=[];window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||"error"));});</script>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        qs = urllib.parse.urlparse(self.path).query
        m = re.search(r"slot=([A-Za-z0-9_\-]+)", qs)
        slot = m.group(1) if m else "default"
        os.makedirs(REPORT_DIR, exist_ok=True)
        open(os.path.join(REPORT_DIR, slot + ".json"), "wb").write(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


class Q(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


def run_edge(url, budget=15000, timeout=150):
    prof = tempfile.mkdtemp(prefix="edgeprof_", dir=REPORT_DIR)
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=492,940",
            "--virtual-time-budget=%d" % budget, "--user-data-dir=" + prof, url]
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    p = os.path.join(REPORT_DIR, "attach_url.json")
    try:
        os.remove(p)
    except OSError:
        pass
    raw = open(DEMO, encoding="utf-8").read()
    raw = raw.replace("</head>", ERR_JS + "</head>", 1)
    raw = raw.replace("</body>", CHECK_JS + "</body>", 1)
    tmp = tempfile.mkdtemp(prefix="v2attach_")
    srv = None
    try:
        open(os.path.join(tmp, "demo.html"), "w", encoding="utf-8", newline="").write(raw)
        os.chdir(tmp)
        srv = Q(("127.0.0.1", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run_edge(BASE + "demo.html")
        data = None
        t0 = time.time()
        while time.time() - t0 < 20:
            if os.path.exists(p):
                time.sleep(0.2)
                try:
                    data = json.load(open(p, encoding="utf-8"))
                    break
                except Exception:
                    time.sleep(0.3)
            time.sleep(0.2)
        if not data:
            print("[v2_attach_url_check] 未拿到测试报告")
            return 2
        passed = 0
        for s in data.get("steps", []):
            if s["ok"]:
                passed += 1
            print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + str(s["note"])) if s["note"] else ""))
        total = len(data.get("steps", []))
        print("=" * 60)
        print("v2_attach_url_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
        print("=" * 60)
        return 0 if total and passed == total else 1
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())


