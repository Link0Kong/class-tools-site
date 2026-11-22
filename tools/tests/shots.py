# -*- coding: utf-8 -*-
"""自检 B：界面截图（iframe 固定宽度，得到真实窄屏渲染）+ 横向溢出审计。
用法：python tests\\shots.py
说明：headless Edge 的 --window-size 不直接决定视口宽度，故用 iframe 强制宽度。
"""
import os, json, subprocess, threading, http.server, socketserver, functools, time, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "index.html")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(OUT, exist_ok=True)

EDGE = None
for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
          r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
    if os.path.exists(p):
        EDGE = p
        break
if not EDGE:
    sys.exit("找不到 Edge")

SEED = {
    "termStart": "2026-08-31",
    "course": [
        {"name": "高等数学", "teacher": "王老师", "room": "A301", "day": 0, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"},
        {"name": "大学英语", "teacher": "李老师", "room": "B205", "day": 1, "start": 3, "end": 4, "weeks": "1-16", "parity": "all"},
        {"name": "程序设计基础", "teacher": "张老师", "room": "机房3", "day": 2, "start": 5, "end": 6, "weeks": "1-16", "parity": "all"},
        {"name": "管理学原理", "teacher": "刘老师", "room": "C102", "day": 3, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"},
        {"name": "体育", "teacher": "赵老师", "room": "操场", "day": 2, "start": 7, "end": 8, "weeks": "1-16", "parity": "all"},
    ],
    "homework": [
        {"subject": "英语", "content": "Unit 3 课后练习 P45-P48", "due": "10-12 上课前", "date": "2026-10-12", "done": False},
        {"subject": "高数", "content": "习题 2.3 第 1-15 题", "due": "10-13 晚自习前", "date": "2026-10-13", "done": False},
    ],
    "notices": [
        {"title": "关于本周五班会的通知", "body": "时间：10月11日 19:00\n地点：A301 教室\n内容：班委竞选演说，请全体同学准时参加。", "pin": True, "imp": True, "ts": 1759900000000},
    ],
    "draw": {"start": 1, "end": 50, "count": 10, "dup": False, "excl": "", "sort": "desc"},
    "group": {"source": "prev", "names": "", "mode": "groups", "n": 4, "shuffle": False},
    "roster": "\n".join("同学%d" % (i + 1) for i in range(50)),
    "settings": {"kind": "webhook", "url": ""},
}

AUTO = {
    "s1": 'c("#aRun");',
    "s2": 'c("#aRun");c("#gSrcSeg [data-gsrc=\'prev\']");c("#gRun");',
    "s3": 'c("#aRun");c("#gSrcSeg [data-gsrc=\'all\']");c("#gRun");',
    "s2_desktop": 'c("#aRun");c("#gSrcSeg [data-gsrc=\'prev\']");c("#gRun");',
    "tt": 'c("[data-tab=\'all\']");c("[data-open=\'tt\']");c("[data-ttview=\'week\']");',
    "tt_day": 'c("[data-tab=\'all\']");c("[data-open=\'tt\']");c("[data-ttview=\'day\']");',
    "tt_prev": 'c("[data-tab=\'all\']");c("[data-open=\'tt\']");c("[data-ttview=\'week\']");c("#tPrevW");',
    "tt_detail": 'c("[data-tab=\'all\']");c("[data-open=\'tt\']");c("[data-ttview=\'week\']");var _c1=d.querySelector("#tGrid td.crs");if(_c1)_c1.click();',
    "tt_import": 'c("[data-tab=\'all\']");c("[data-open=\'tt\']");c("#tImport");',
    "tt_admin": 'c("[data-tab=\'all\']");c("[data-open=\'tt\']");c("[data-ttview=\'week\']");',
    "tt_day_desktop": 'c("[data-tab=\'all\']");c("[data-open=\'tt\']");c("[data-ttview=\'day\']");',
    "hw": 'c("[data-tab=\'hw\']");',
    "nt": 'c("[data-tab=\'nt\']");',
    "ft": 'c("[data-tab=\'all\']");c("[data-open=\'ft\']");var ftv={fH:"175",fW:"65",fVc:"4300",fR50:"7.1",fSit:"17.7",fJump:"248",fPull:"15",fDurM:"3",fDurS:"42"};for(var fk in ftv){var fe=d.querySelector("#"+fk);fe.value=ftv[fk];fe.dispatchEvent(new Event("input",{bubbles:true}));}',
}

HASHED = {"tt_admin": "#edit"}

base = open(SRC, encoding="utf-8").read()
# 截图确定性：关掉装饰性淡入/切换过渡，避免抓到动画中途的半透明帧
base = base.replace("</head>",
    '<style>section.on{animation:none!important}.tabs button{transition:none!important}'
    'table.tt td.crs,table.tt .crs-multi .crs,table.tt td.cell.today{animation:none!important}</style></head>', 1)
base = base.replace('<div id="toast"></div>',
    '<div id="toast"></div>\n<script>var _f=window.fetch;window.fetch=function(u,o){if(String(u).indexOf("tcloudbasegateway")>=0||String(u).indexOf("tt.json")>=0)return Promise.reject(new Error("test-block"));return _f.apply(this,arguments);};try{localStorage.setItem("zq_tools_v2",JSON.stringify(%s));}catch(e){}</script>'
    % json.dumps(SEED, ensure_ascii=False))
open(os.path.join(ROOT, "_frame_app_%s.html" % time.strftime("%H%M%S")), "w", encoding="utf-8").write(base)
RUNID = time.strftime("%H%M%S")


def wrap(name, w, h):
    key = name.split("_")[0] if "_" in name else name
    auto = AUTO.get(name, AUTO.get(key, ""))
    src = "_frame_app_%s.html%s" % (RUNID, HASHED.get(name, ""))
    body = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#DDE3E1;font:12px monospace}
iframe{border:0;display:block;background:#fff}
#hud{padding:4px 8px;background:#23302E;color:#fff;font:11.5px monospace}</style></head><body>
<iframe id="f" src="%s" style="width:%dpx;height:%dpx"></iframe>
<div id="hud">测量中…</div>
<script>
document.getElementById("f").addEventListener("load",function(){
  var w=this.contentWindow,d=this.contentDocument;
  setTimeout(function(){
    function c(s){var e=d.querySelector(s);if(e)e.click();}
    %s
    setTimeout(function(){
      var de=d.documentElement,bad=[];
      d.querySelectorAll("*").forEach(function(e){
        var r=e.getBoundingClientRect();
        if(r.width>0&&r.right>de.clientWidth+1&&!e.closest("table.tt")&&getComputedStyle(e).position!=="fixed") bad.push(e.tagName+"."+String(e.className).split(" ")[0]);
      });
      document.getElementById("hud").textContent="viewport="+de.clientWidth+"  scrollW="+de.scrollWidth+"  overflow="+bad.length+(bad.length?"  ["+bad.slice(0,8).join(",")+"]":"");
    },350);
  },250);
});
</script></body></html>""" % (src, w, h, auto)
    p = os.path.join(ROOT, "_frame_%s_%s.html" % (name, RUNID))
    open(p, "w", encoding="utf-8").write(body)
    return p


shots = [("s1", 430, 1500), ("s2", 430, 1500), ("s3", 430, 1900),
         ("hw", 430, 1300), ("nt", 430, 1600), ("ft", 430, 1500),
         ("tt", 430, 1600), ("tt_day", 430, 1400), ("tt_prev", 430, 1600), ("tt_detail", 430, 1300), ("tt_import", 430, 1300),
         ("tt_admin", 430, 1700), ("tt_desktop", 1280, 1200), ("tt_wide", 1440, 1200),
         ("tt_day_desktop", 1280, 1100), ("s2_desktop", 1280, 1200),
         ("hw_desktop", 1280, 1100), ("nt_desktop", 1280, 1100),
         ("s1_desktop", 1280, 1100), ("s3_desktop", 1280, 1200), ("ft_desktop", 1280, 1250)]
shots += [("s1_360", 360, 1500), ("s2_360", 360, 1500), ("ft_360", 360, 1500), ("tt_360", 360, 1400), ("s1_wide", 1440, 1100)]

PORT = 8899
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)


class Q(socketserver.TCPServer):
    allow_reuse_address = True


httpd = Q(("127.0.0.1", PORT), Handler)
httpd.RequestHandlerClass.log_message = lambda *a, **k: None
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.6)

try:
    for name, w, h in shots:
        # 每个 shot 独立外框文件（避免 Edge HTTP 缓存串宽度）
        page = wrap(name, w, h)
        out = os.path.join(OUT, name + ".png")
        t0 = time.time()
        prof = os.path.join(tempfile.gettempdir(), "tt_shot_" + name)
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--user-data-dir=" + prof,
                        "--window-size=%d,%d" % (w, h + 120), "--screenshot=" + out,
                        "--virtual-time-budget=3500",
                        "http://127.0.0.1:%d/%s" % (PORT, os.path.basename(page))],
                       capture_output=True, timeout=90)
        # headless Edge 偶尔异步落盘：轮询等文件出现且不早于本次运行
        ok = False
        for _ in range(20):
            if os.path.exists(out) and os.path.getmtime(out) >= t0 - 1:
                ok = True
                break
            time.sleep(0.4)
        print("%-12s -> %s" % (name, os.path.getsize(out) if ok else "FAIL"))
finally:
    httpd.shutdown()
    for f in os.listdir(ROOT):
        if f.startswith("_frame_") and f.endswith(".html"):
            os.remove(os.path.join(ROOT, f))
print("shots ->", OUT)
