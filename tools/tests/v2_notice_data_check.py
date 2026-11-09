# -*- coding: utf-8 -*-
"""v2 集成自检：通知模板 + 真实 board 数据（需求 6/7/8/9/12 数据侧）

对象：`web/tools/notice-board-live-demo.html`（data-dev 生成的模板+内嵌 board 数据）
做法：复制到临时目录，在 </body> 前追加断言脚本（不改源文件），headless Edge 跑完用同步 XHR 回传报告。
覆盖：
  - 通知组数量（40 组生效）；
  - g_dorm「宿舍卫生检查安排」：recurrence=monthly_weeks / actionable=false / 卡片显示「长期安排」「下次…」；
  - 药膳答题活动 c0：deadline/eventAt/expireAt=11-07、timeLabel 含 11-07、含「补充通知」条、updatedAt；
  - 接龙类消息已排除（卡片标题无「接龙」）；
  - QQ 文件：≥3 个已内嵌 url、≥5 个「待获取」，页面出现「待获取」提示与复制群名；
  - AI 要点：每组 ≤6 条、单条 ≤12 字（需求 8 契约）；
  - 模板契约函数齐备（__zqSetAdmin/__zqSetHidden/__zqApplyOverride/__zqSetScroll）。

用法：cd C:\\...\\web\\tools && python tests\\v2_notice_data_check.py
退出码 0 = 全绿。
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
PORT = 8995
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_v2_notice_reports")

CHECK_JS = r"""
<script>
(function(){
var R={steps:[]};
function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
function bodyText(){return (document.body?document.body.textContent:"").replace(/\s+/g," ");}
try{
  var gs=(typeof GROUPS!=="undefined"&&GROUPS)?GROUPS:[];
  T("D1 通知组数量（40 组生效）", gs.length>=39, gs.length);
  var cats={};gs.forEach(function(g){cats[g.cat||"其他"]=1;});
  T("D2 分类覆盖", Object.keys(cats).length>=3, Object.keys(cats).join(","));

  var dorm=null;gs.forEach(function(g){if(String(g.id||"").indexOf("g_dorm")>=0)dorm=g;});
  T("D3 g_dorm 通知存在", !!dorm, dorm?dorm.title:"");
  var rec=dorm&&dorm.recurrence;
  T("D4 g_dorm recurrence=monthly_weeks / weekday=3 / weeks 1-3",
    !!(rec&&rec.freq==="monthly_weeks"&&Number(rec.weekday)===3&&(rec.weeks||[]).join(",")==="1,2,3"),
    JSON.stringify(rec||null).slice(0,200));
  T("D5 g_dorm 长期安排 label 合理", !!(rec&&/每月/.test(String(rec.label||""))&&/17:30/.test(String(rec.label||""))), rec?String(rec.label):"");
  T("D6 g_dorm actionable=false（不计入待处理）", !!(dorm&&dorm.actionable===false), dorm?String(dorm.actionable):"");
  var dormCard=dorm?document.querySelector('.gcard[data-gid="'+dorm.id+'"]'):null;
  T("D7 g_dorm 卡片显示「长期安排」", !!dormCard&&/长期安排/.test(dormCard.textContent), dormCard?dormCard.textContent.replace(/\s+/g," ").slice(0,160):"");
  T("D8 g_dorm 卡片显示「下次」时间", !!dormCard&&/下次/.test(dormCard.textContent), "");

  var med=null;gs.forEach(function(g){if(String(g.id||"").indexOf("g_qqm_7704134971497063025_c0")>=0)med=g;});
  T("D9 药膳答题活动 c0 存在", !!med, med?med.title:"");
  T("D10 药膳 deadline=2026-11-07 18:00", !!(med&&String(med.deadline||"").indexOf("2026-11-07T18:00")>=0), med?String(med.deadline):"");
  T("D11 药膳 eventAt=2026-11-07 12:00", !!(med&&String(med.eventAt||"").indexOf("2026-11-07T12:00")>=0), med?String(med.eventAt):"");
  T("D12 药膳 expireAt=2026-11-07 18:00", !!(med&&String(med.expireAt||"").indexOf("2026-11-07T18:00")>=0), med?String(med.expireAt):"");
  T("D13 药膳 timeLabel 含 11-07", !!(med&&/11-07/.test(String(med.timeLabel||""))), med?String(med.timeLabel):"");
  var hasSupp=!!(med&&(med.items||[]).some(function(it){return String(it.label||"")==="补充通知";}));
  T("D14 药膳含「补充通知」条目", hasSupp, med?JSON.stringify((med.items||[]).map(function(it){return it.label;})):"");
  T("D15 药膳 updatedAt 已写入", !!(med&&med.updatedAt), med?String(med.updatedAt):"");
  var medCard=med?document.querySelector('.gcard[data-gid="'+med.id+'"]'):null;
  T("D16 药膳卡片显示「已更新」标记", !!medCard&&/已更新/.test(medCard.textContent), "");

  var jl=[];gs.forEach(function(g){if(/接龙/.test(String(g.title||"")))jl.push(g.id);});
  T("D17 接龙类消息已排除", jl.length===0, jl.join(","));

  var fileTotal=0,fileUrl=0,fileMiss=0;
  gs.forEach(function(g){(g.items||[]).forEach(function(it){
    if(it.kind!=="file")return;
    fileTotal++;
    if(it.url)fileUrl++; else fileMiss++;
  });});
  T("D18 QQ 文件至少 3 个已内嵌下载链接", fileUrl>=3, fileUrl+"/"+fileTotal);
  T("D19 QQ 文件至少 5 个「待获取」", fileMiss>=5, fileMiss+"/"+fileTotal);
  var missTxt=(bodyText().match(/待获取/g)||[]).length;
  T("D20 页面渲染「待获取」提示", missTxt>=Math.min(5,fileMiss), missTxt);
  T("D21 有已内嵌文件的预览/下载入口", !!document.querySelector('[data-act="preview"]'), "");

  var maxPts=0,maxLen=0,ptsTotal=0;
  gs.forEach(function(g){
    var ps=g.aiPoints||[];
    if(ps.length>maxPts)maxPts=ps.length;
    ptsTotal+=ps.length;
    ps.forEach(function(p){var s=String(p||"");if(s.length>maxLen)maxLen=s.length;});
  });
  T("D22 AI 要点每组 ≤6 条（去掉 3 条硬限制）", maxPts<=6, maxPts);
  T("D23 AI 要点单条 ≤12 字（关键词/短句）", maxLen<=12, maxLen+" 字");
  T("D24 AI 要点总量合理（>80 条）", ptsTotal>80, ptsTotal);

  var contracts=["__zqSetAdmin","__zqSetHidden","__zqApplyOverride","__zqSetScroll"];
  var missing=contracts.filter(function(f){return typeof window[f]!=="function";});
  T("D25 模板契约函数齐备", missing.length===0, missing.join(","));
  T("D26 模板不再整页定时重渲染（RENDER_SIG 存在）", typeof RENDER_SIG!=="undefined", "");
  var errs=window.__errs||[];
  T("D27 0 JS 报错", errs.length===0, JSON.stringify(errs).slice(0,300));
}catch(e){T("脚本异常",false,String(e&&e.stack||e));}
try{
  var x=new XMLHttpRequest();x.open("POST","/_report?slot=data",false);
  x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(R));
}catch(e){}
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


def run_edge(url, budget=20000, timeout=180):
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
    try:
        os.remove(os.path.join(REPORT_DIR, "data.json"))
    except Exception:
        pass
    raw = open(DEMO, encoding="utf-8").read()
    # 只注入错误收集 + 断言脚本（不改源文件）
    if "</head>" in raw:
        raw = raw.replace("</head>", ERR_JS + "</head>", 1)
    else:
        raw = ERR_JS + raw
    raw = raw.replace("</body>", CHECK_JS + "</body>", 1) if "</body>" in raw else raw + CHECK_JS
    tmp = tempfile.mkdtemp(prefix="v2notice_")
    srv = None
    try:
        open(os.path.join(tmp, "demo.html"), "w", encoding="utf-8", newline="").write(raw)
        os.chdir(tmp)
        srv = Q(("127.0.0.1", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run_edge(BASE + "demo.html")
        p = os.path.join(REPORT_DIR, "data.json")
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
            print("[v2_notice_data_check] 未拿到测试报告")
            sys.exit(2)
        passed = 0
        for s in data.get("steps", []):
            if s["ok"]:
                passed += 1
            print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + str(s["note"])) if s["note"] else ""))
        total = len(data.get("steps", []))
        print("=" * 60)
        print("v2_notice_data_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
        print("=" * 60)
        sys.exit(0 if total and passed == total else 1)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
