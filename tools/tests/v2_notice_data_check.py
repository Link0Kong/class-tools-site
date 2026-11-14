# -*- coding: utf-8 -*-
"""v2 集成自检：通知模板 + 真实 board 数据（需求 6/7/8/9/12 数据侧）

对象：`web/tools/notice-board-live-demo.html`（data-dev 生成的模板+内嵌 board 数据）
做法：复制到临时目录，在 </body> 前追加断言脚本（不改源文件），headless Edge 跑完用同步 XHR 回传报告。
覆盖：
  - 通知组数量（动态数据，≥55）；
  - g_dorm「宿舍卫生检查安排」：recurrence=monthly_weeks / actionable=false /
    2026-11-14 契约后不再在主列表、改在「长期通知」清单显示「周期 + 下次 M月D日（周X）HH:MM」；
  - 2026-11-14 契约 §1.4：从当前 GROUPS 动态取「补充通知」合并卡，断言 supplement/updatedAt|threadReason/
    原始消息+补充条目/已更新徽标/时间字段合法 +08:00 ISO/线程 reason ≤40 字/id 唯一且标题非空；
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
  T("D1 通知组数量（动态数据，≥55）", gs.length>=55, gs.length);
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
  /* 2026-11-14 契约 §2：长期安排定义卡移入「长期通知」筛选清单（主列表不再出现）。 */
  var dormMainCard=document.querySelector('#list .gcard[data-gid="'+dorm.id+'"]');
  T("D7 g_dorm 不再出现在「全部」主列表（长期定义移入长期通知筛选）", !dormMainCard,
    dormMainCard?dormMainCard.textContent.replace(/\s+/g," ").slice(0,160):"");
  var ltBtn=document.querySelector('#dataBar [data-card="longterm"]');
  var dormRow=null;
  if(ltBtn){
    ltBtn.click();
    Array.prototype.slice.call(document.querySelectorAll('#list .ltrow')).forEach(function(r){
      if(r.getAttribute('data-gid')===dorm.id)dormRow=r;
    });
    ltBtn.click();
  }
  T("D8 g_dorm 在「长期通知」清单显示周期 label + 下次时间",
    !!dormRow&&/每月/.test(dormRow.textContent)&&/下次/.test(dormRow.textContent)&&/\d{1,2}月\d{1,2}日（/.test(dormRow.textContent),
    dormRow?dormRow.textContent.replace(/\s+/g," ").slice(0,160):"");

  /* 2026-11-14 契约 §1.4：更新/更正线程合并（keep 覆盖最终状态 + merge 组 items 追加补充通知）。
     旧版固定药膳 c0 数据的断言改为从当前 GROUPS 动态取合并卡（数据每次重建会变化）。 */
  var supp=[];
  gs.forEach(function(g){
    if((g.items||[]).some(function(it){return String(it.label||"")==="补充通知";}))supp.push(g);
  });
  T("D9 存在「补充通知」合并卡（动态数据）", supp.length>0, "n="+supp.length);
  var mg=supp[0]||null;
  T("D10 合并卡标 supplement=true", !!(mg&&mg.supplement===true), mg?String(mg.supplement):"missing");
  T("D11 合并卡已写入 updatedAt 或 threadReason", !!(mg&&(mg.updatedAt||mg.threadReason)),
    mg?String(mg.updatedAt||mg.threadReason):"missing");
  var mgItems=(mg&&mg.items)||[];
  T("D12 合并卡保留原始消息并追加 ≥1 条补充通知", mgItems.length>=2
    && mgItems.some(function(it){return it.kind==="text"||it.kind==="follow";})
    && mgItems.some(function(it){return String(it.label||"")==="补充通知";}), "items="+mgItems.length);
  T("D13 页面渲染「已更新」徽标", document.querySelectorAll('.badge.upd').length>=1,
    document.querySelectorAll('.badge.upd').length);
  var isoRe=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$/;
  var badIso=[];
  gs.forEach(function(g){
    ["deadline","eventAt","signupStart","signupEnd","expireAt"].forEach(function(k){
      var v=g[k];
      if(v&&!isoRe.test(String(v)))badIso.push(g.id+"."+k+"="+v);
    });
  });
  T("D14 时间字段均为合法 +08:00 ISO（AI/线程/补丁写入）", badIso.length===0, badIso.slice(0,8).join(","));
  var badReason=[];gs.forEach(function(g){var r=String(g.threadReason||"");if(r.length>40)badReason.push(g.id);});
  T("D15 线程合并 reason ≤40 字（契约 §1.4，便于人工复核）", badReason.length===0, badReason.join(","));
  var idSet={},dup=[],emptyTitle=[];
  gs.forEach(function(g){if(idSet[g.id])dup.push(g.id);idSet[g.id]=1;if(!String(g.title||"").trim())emptyTitle.push(g.id);});
  T("D16 通知组 id 唯一且标题非空", dup.length===0&&emptyTitle.length===0, "dup="+dup.join(",")+" empty="+emptyTitle.join(","));

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
