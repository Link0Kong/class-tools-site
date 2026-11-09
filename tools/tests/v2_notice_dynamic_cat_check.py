# -*- coding: utf-8 -*-
"""动态分类自检（2026-11-09 用户需求：取消固定分类，AI 按近期通知增删分类）。

对象：`web/tools/notice-board-live-demo.html`（builder 生成的模板 + 内嵌 board 数据）
做法：复制到临时目录，在 </body> 前追加断言脚本（不改源文件），headless Edge 跑完同步 XHR 回传。
覆盖：
  - 分类 chips 由数据动态生成（不是硬编码的教务/活动/班级事务/缴费）；
  - 「全部分类」+ 每个实际分类都有 chip，data-cat 正确，无 JS 报错；
  - 点击分类 chip 过滤生效（列表卡片 badge 全为该分类、active 样式正确），点回全部恢复；
  - 动态增删：临时给某组换新分类 → 新 chip 自动出现；把所有该分类组换走后 → chip 消失
    （上次选中分类不存在时自动回「全部分类」）；
  - 管理员编辑弹层的分类下拉来自当前动态分类；
  - 分类 chips 换行、无横向/页面溢出。

用法：cd C:\\...\\web\\tools && python tests\\v2_notice_dynamic_cat_check.py
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
DEMO = os.path.abspath(os.environ.get("VDC_DEMO") or os.path.join(ROOT, "notice-board-live-demo.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8997
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_v2_dynamic_cat_reports")

CHECK_JS = r"""
<script>
(function(){
var R={steps:[]};
function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
function gs(){try{return (typeof GROUPS!=="undefined"&&GROUPS)?GROUPS:[];}catch(e){return [];}}
function chips(){return Array.prototype.slice.call(document.querySelectorAll('#catRow .chipf'));}
function chipLabels(){return chips().map(function(b){return b.textContent.trim();});}
function visibleCards(){return Array.prototype.slice.call(document.querySelectorAll('#list .gcard'));}
function cardCats(){return visibleCards().map(function(c){var b=c.querySelector('.ghd .badge');return b?b.textContent.trim():'';});}
try{
  T("E0 模板动态分类函数存在", typeof catList==="function"&&typeof renderCatChips==="function"&&typeof catClass==="function","");
  var groups=gs();
  T("E1 通知数据可读", groups.length>=39, "groups="+groups.length);
  var cats=catList();
  T("E2 分类由数据动态生成（≥3 类）", cats.length>=3, "cats="+cats.join(","));
  var labels=chipLabels();
  T("E3 含「全部分类」chip", labels.length>0&&labels[0]==="全部分类", labels.join(","));
  T("E4 每个实际分类都有 chip", cats.every(function(c){return labels.indexOf(c)>=0;}), "cats="+cats.join(",")+" labels="+labels.join(","));
  T("E5 分类 chip 数量 = 分类数+1", chips().length===cats.length+1, chips().length+" vs "+(cats.length+1));
  var noHardcode=(labels.join(",").indexOf("教务,活动,班级事务,缴费")<0);
  T("E6 不再是写死的四个固定分类", noHardcode, labels.join(","));
  T("E7 每张卡片分类都在 chip 列表里", visibleCards().every(function(c){return labels.indexOf((c.querySelector('.ghd .badge')||{}).textContent.trim())>=0;}), "");
  T("E8 分类 chips 无横向溢出/换行可用", (function(){
    var row=document.getElementById('catRow');
    return row && row.scrollWidth <= row.clientWidth+1 && document.documentElement.scrollWidth <= window.innerWidth+1;
  })(), "");

  // 点击一个非「全部」分类 → 只显示该分类
  var target=null;
  for(var i=1;i<chips().length;i++){var c=chips()[i].getAttribute('data-cat');var n=groups.filter(function(g){return g.cat===c;}).length;if(n>0){target=chips()[i];break;}}
  var totalBefore=visibleCards().length;
  if(target){
    var cname=target.getAttribute('data-cat');
    target.click();
    var after=cardCats();
    T("E9 点击分类 chip 过滤生效", after.length>0&&after.every(function(x){return x===cname;}), "cat="+cname+" n="+after.length+" first="+(after[0]||""));
    T("E10 选中 chip 有 on 样式", target.classList.contains('on')&&chips().filter(function(b){return b.classList.contains('on');}).length===1, target.className);
    chips()[0].click();
    T("E11 点回「全部分类」恢复", visibleCards().length===totalBefore, visibleCards().length+" vs "+totalBefore);
  }else{
    T("E9 点击分类 chip 过滤生效", false, "无可点击分类");
    T("E10 选中 chip 有 on 样式", false, "");
    T("E11 点回「全部分类」恢复", false, "");
  }

  // 动态增删：临时改一组分类 → 新 chip 出现；全部移走后 → chip 消失、选中态自动回全部
  try{
    // 需选一条未过期通知（全部项目已过期的分类不再展示，2026-11-09 新规则）
    var g0=groups.filter(function(x){try{return !isExpiredGroup(x);}catch(e){return true;}})[0]||groups[0];
    var gid0=g0.id;
    var oldCat=g0.cat;
    g0.cat="测试新类";
    render({animate:false});
    var hasNew=chipLabels().indexOf("测试新类")>=0;
    T("E12 新增分类自动出现在 chips（无需改模板/写死）", hasNew, chipLabels().join(","));
    // 选中新分类
    var nb=chips().filter(function(b){return b.getAttribute('data-cat')==='测试新类';})[0];
    if(nb)nb.click();
    T("E13 可筛选到动态新分类", visibleCards().every(function(c){return (c.querySelector('.ghd .badge')||{}).textContent.trim()==='测试新类';})&&visibleCards().length>=1, visibleCards().length);
    // 把所有属于该分类的组移走 → 分类消失，选中回全部
    groups.forEach(function(g){if(g.cat==="测试新类")g.cat=oldCat;});
    render({animate:false});
    T("E14 分类无通知后自动删除", chipLabels().indexOf("测试新类")<0, chipLabels().join(","));
    T("E15 选中分类消失后自动回全部", chips()[0].classList.contains('on')&&chips()[0].getAttribute('data-cat')==='全部', "");
  }catch(e){T("E12-15 动态增删脚本", false, String(e));}

  // 管理员编辑弹层分类下拉来自当前动态分类（只验证结构，不保存）
  try{
    if(typeof window.__zqSetAdmin==='function'){window.__zqSetAdmin(true);}
    var gid=visibleCards().length?visibleCards()[0].getAttribute('data-gid'):(groups[0]&&groups[0].id);
    if(typeof openEdit==='function'&&gid){openEdit(gid);var opts=Array.prototype.map.call(document.querySelectorAll('#edCat option'),function(o){return o.textContent.trim();});T("E16 编辑弹层分类选项也是动态分类", opts.length===catList().length||opts.every(function(x){return catList().indexOf(x)>=0;}), opts.join(","));if(typeof closeEdit==='function')closeEdit();}
    else T("E16 编辑弹层分类选项也是动态分类", false, "openEdit/gid missing");
    if(typeof window.__zqSetAdmin==='function'){window.__zqSetAdmin(false);}
  }catch(e){T("E16 编辑弹层分类选项也是动态分类", false, String(e));}

  var errs=window.__errs||[];
  T("E17 0 JS 报错", errs.length===0, JSON.stringify(errs).slice(0,300));
}catch(e){T("脚本异常",false,String(e&&e.stack||e));}
try{var x=new XMLHttpRequest();x.open("POST","/_report?slot=dcat",false);x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(R));}catch(e){}
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
        open(os.path.join(REPORT_DIR, "dcat.json"), "wb").write(body)
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
    prof = tempfile.mkdtemp(prefix="edgedcat_", dir=REPORT_DIR)
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
        os.remove(os.path.join(REPORT_DIR, "dcat.json"))
    except Exception:
        pass
    raw = open(DEMO, encoding="utf-8").read()
    if "</head>" in raw:
        raw = raw.replace("</head>", ERR_JS + "</head>", 1)
    else:
        raw = ERR_JS + raw
    raw = raw.replace("</body>", CHECK_JS + "</body>", 1) if "</body>" in raw else raw + CHECK_JS
    tmp = tempfile.mkdtemp(prefix="v2dcat_")
    srv = None
    try:
        open(os.path.join(tmp, "demo.html"), "w", encoding="utf-8", newline="").write(raw)
        os.chdir(tmp)
        srv = Q(("127.0.0.1", PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        run_edge(BASE + "demo.html")
        p = os.path.join(REPORT_DIR, "dcat.json")
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
            print("[v2_notice_dynamic_cat_check] 未拿到测试报告")
            sys.exit(2)
        passed = 0
        for s in data.get("steps", []):
            if s["ok"]:
                passed += 1
            print(("[PASS] " if s["ok"] else "[FAIL] ") + s["k"] + ((" | " + str(s["note"])) if s["note"] else ""))
        total = len(data.get("steps", []))
        print("=" * 60)
        print("v2_notice_dynamic_cat_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
        print("=" * 60)
        sys.exit(0 if total and passed == total else 1)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
