# -*- coding: utf-8 -*-
"""AI 质检/过期/多报名窗口自检（2026-11-09 用户第 2/3/4/5/6 条反馈）。

对象：`web/tools/notice-board-live-demo.html`（builder 生成，含 ai-quality 校正后的数据）。
覆盖：
  Q1  生产数据组数/关键组存在；
  Q2-5 已结束的运动会名单/赛程/观赛安排 → 状态机返回 expired（不再是进行中）；
  Q6-8 河洛夜市报名截止 11-09 22:00 被识别为「报名截止」而不是「报名开始」（deadline 正确、signupStart 为空）；
  Q9-11 小儿体质活动三个报名窗口：signupWindows=3、每个窗口写在要点、状态按当前时间显示「11-10 12:00 报名开始 · 子活动一」；
  Q12-13 成绩认定附件已识别（archiveOk/note），且以附件为准修正为 11-13 截止；
  Q14-15 非通知/无内容已被去除（5 个 id 不在 GROUPS，也不在列表）；分类没有少于 3 条的碎片类；
  Q16  0 JS 报错。

用法：cd C:\\...\\web\\tools && python tests\\v2_notice_quality_check.py
退出码 0 = 全绿。
"""
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEMO = os.path.abspath(os.environ.get("VQC_DEMO") or os.path.join(ROOT, "notice-board-live-demo.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8998
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_v2_quality_reports")

CHECK_JS = r"""
<script>
(function(){
var R={steps:[]};
function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
function gs(){try{return (typeof GROUPS!=="undefined"&&GROUPS)?GROUPS:[];}catch(e){return [];}}
function byId(id){var a=gs().filter(function(g){return g.id===id;});return a.length?a[0]:null;}
function st(g){try{return statusOf(g)||{};}catch(e){return {label:"ERR:"+e};}}
function when(iso){try{return fmtWhen(Date.parse(iso));}catch(e){return "";}}
try{
  var groups=gs();
  T("Q1 通知数据可读（含关键组）", groups.length>=55&&!!byId("g_qqimg_7c98c2f7e8")&&!!byId("g_qqm_7706037840253967598_c0")&&!!byId("g_qqm_7706038665232774784_c0")&&!!byId("g_ait_eb83112de5"), "groups="+groups.length);
  var a=st(byId("g_qqimg_7c98c2f7e8"));
  T("Q2 11月4日至6日观赛安排已过期", a.key==="expired"||a.cls==="expired"||String(a.label).indexOf("已过期")>=0, JSON.stringify(a));
  var b=st(byId("g_qqimg_23449ab035"));
  T("Q3 11-06运动会赛程及名单已过期", b.key==="expired"||b.cls==="expired"||String(b.label).indexOf("已过期")>=0, JSON.stringify(b));
  var c=st(byId("g_qqimg_6d052014c3")), d=st(byId("g_qqimg_def2524e9f"));
  T("Q4 11-05/11-04运动会项目名单已过期", (c.key==="expired"||c.cls==="expired")&&(d.key==="expired"||d.cls==="expired"), JSON.stringify(c)+" / "+JSON.stringify(d));
  var hl=byId("g_qqm_7706037840253967598_c0");
  T("Q5 河洛夜市 deadline=11-09 22:00 报名截止", hl&&hl.deadline==="2026-11-09T22:00:00+08:00"&&hl.deadlineAction==="报名截止", hl?hl.deadline+" "+hl.deadlineAction:"missing");
  T("Q6 河洛夜市未被误判成报名开始（无 signupStart）", hl&&!hl.signupStart, hl?String(hl.signupStart):"missing");
  var hs=st(hl);
  T("Q7 河洛夜市状态显示报名截止", String(hs.label).indexOf("报名截止")>=0&&String(hs.label).indexOf("报名开始")<0, JSON.stringify(hs));
  var xe=byId("g_qqm_7706038665232774784_c0");
  T("Q8 小儿体质活动有 3 个报名窗口", xe&&Array.isArray(xe.signupWindows)&&xe.signupWindows.length===3, xe?JSON.stringify(xe.signupWindows||null):"missing");
  var pts=(xe&&xe.aiPoints)||[];
  T("Q9 三个报名窗口都写在要点里", pts.some(function(p){return p.indexOf("11-10")>=0;})&&pts.some(function(p){return p.indexOf("11-11")>=0;})&&pts.some(function(p){return p.indexOf("11-12")>=0;}), pts.join(" | "));
  var xs=st(xe);
  T("Q10 小儿当前状态=下一个报名窗口报名开始", xs.key==="today"&&String(xs.label).indexOf("报名开始")>=0, JSON.stringify(xs));
  var cj=byId("g_ait_eb83112de5");
  T("Q11 成绩认定按附件修正为 11-13 截止", cj&&String(cj.deadline).indexOf("2026-11-13")===0&&String(cj.title).indexOf("11-13")>=0, cj?cj.deadline+" / "+cj.title:"missing");
  var fitems=(cj&&cj.items)||[];
  var attach=null;
  for(var i=0;i<fitems.length;i++){if(fitems[i].kind==="file"){attach=fitems[i];break;}}
  T("Q12 成绩认定附件已识别（压缩包/归档信息）", attach&&attach.archiveOk===true&&attach.archive&&(attach.archive.count||0)>=2, attach?JSON.stringify({name:attach.name,ok:attach.archiveOk,note:attach.note}):"missing");
  var drops=["g_qqm_7704959755845695040_c0","g_ait_d385e6d0bb","g_ait_self_325ad220cb","g_ait_self_3d6fb34de1","g_ait_wxfile_d7a089497a"];
  T("Q13 非通知/无内容已被去除", drops.every(function(id){return !byId(id);}), drops.filter(function(id){return !!byId(id);}).join(","));
  var droppedCards=Array.prototype.slice.call(document.querySelectorAll('#list .gcard')).filter(function(el){return drops.indexOf(el.getAttribute('data-gid'))>=0;});
  T("Q14 被去除通知不再渲染到列表", droppedCards.length===0, "n="+droppedCards.length);
  var cats=(typeof catList==="function")?catList():[];
  var bad=cats.filter(function(c){return groups.filter(function(g){return g.cat===c;}).length<3;});
  T("Q15 分类都≥3条（无碎片类）", cats.length>=3&&bad.length===0, "cats="+cats.join(",")+" bad="+bad.join(","));
  // 2026-11-09 用户要求：一个分类下全部项目都已过期 → 不单独展示该分类
  var expiredOnly=cats.filter(function(c){
    return !groups.some(function(g){return g.cat===c&&!isExpiredGroup(g);});
  });
  T("Q16 全部过期的分类不单独展示（每个展示分类仍有未过期通知）", expiredOnly.length===0, "cats="+cats.join(",")+" expiredOnly="+expiredOnly.join(","));
  // 已处理 + 已过期：仍应归入过期栏（状态机先判过期再判已处理）
  try{
    var expG=groups.filter(function(g){try{return isExpiredGroup(g);}catch(e){return false;}})[0];
    if(expG){
      var hadDone=!!state.done[expG.id];
      state.done[expG.id]=true;
      var sd=statusOf(expG);
      T("Q17 已处理的过期通知仍在过期栏", sd.key==="expired"||sd.key==="extended_past"||sd.key==="alert", JSON.stringify(sd));
      if(!hadDone) delete state.done[expG.id];
    }else{T("Q17 已处理的过期通知仍在过期栏",false,"无过期组");}
  }catch(e){T("Q17 已处理的过期通知仍在过期栏",false,String(e));}
  // 无具体时间但实际已过时效 → 质检应判过期（招聘会/名单/场地等）
  var nt=byId("g_qqtext_77a2abbbf7")||byId("g_qqfile_d08ac2b508")||byId("g_ait_db1c2a2585");
  T("Q18 无具体时间但已过时效的通知已过期", !!nt&&isExpiredGroup(nt), nt?nt.title:"missing");
  // 全部项目已过期的分类（当前如「招聘」）不再出现在 chips
  T("Q19 全部过期的分类已消失（当前含招聘）", cats.indexOf("招聘")<0, "cats="+cats.join(","));
  var errs=window.__errs||[];
  T("Q20 0 JS 报错", errs.length===0, JSON.stringify(errs).slice(0,300));
}catch(e){T("脚本异常",false,String(e&&e.stack||e));}
try{var x=new XMLHttpRequest();x.open("POST","/_report?slot=qc",false);x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(R));}catch(e){}
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
        os.makedirs(REPORT_DIR, exist_ok=True)
        open(os.path.join(REPORT_DIR, "qc.json"), "wb").write(body)
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
    prof = tempfile.mkdtemp(prefix="edgeqc_", dir=REPORT_DIR)
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
        os.remove(os.path.join(REPORT_DIR, "qc.json"))
    except Exception:
        pass
    raw = open(DEMO, encoding="utf-8").read()
    if "</head>" in raw:
        raw = raw.replace("</head>", ERR_JS + "</head>", 1)
    else:
        raw = ERR_JS + raw
    raw = raw.replace("</body>", CHECK_JS + "</body>", 1) if "</body>" in raw else raw + CHECK_JS
    tmp = tempfile.mkdtemp(prefix="v2qc_")
    srv = None
    try:
        open(os.path.join(tmp, "demo.html"), "w", encoding="utf-8", newline="").write(raw)
        os.chdir(tmp)
        srv = Q(("127.0.0.1", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run_edge(BASE + "demo.html")
        p = os.path.join(REPORT_DIR, "qc.json")
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
            print("[v2_notice_quality_check] 未拿到测试报告")
            sys.exit(2)
        passed = 0
        for s in data.get("steps", []):
            if s["ok"]:
                passed += 1
            print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + str(s["note"])) if s["note"] else ""))
        total = len(data.get("steps", []))
        print("=" * 60)
        print("v2_notice_quality_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
        print("=" * 60)
        sys.exit(0 if total and passed == total else 1)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
