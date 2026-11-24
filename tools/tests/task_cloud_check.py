# -*- coding: utf-8 -*-
"""任务云端同步 mock 集成检查（不连真实云端；真实表冒烟见 task_cloud_live_check.py）。"""
import os, sys, json, time, threading, http.server, socketserver, subprocess, functools
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import task_check as tc

OUT = os.path.join(HERE, "_task_cloud_check")
os.makedirs(OUT, exist_ok=True)
PORT = 9003
REPORT = os.path.join(OUT, "report.json")

RUNNER = r'''
<script>
(function(){
  function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
  function q(s){return document.querySelector(s);}
  function txt(s){var e=q(s);return e?String(e.textContent||""):"";}
  function T(k,ok,note){window.__p.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  window.__p={steps:[]};
  window.addEventListener("load",function(){
    setTimeout(async function(){
      try{
        T("云端状态出现", txt("#tkCloud").indexOf("同步")>=0, txt("#tkCloud"));
        var items=TASK.items();
        T("首次同步合并云端新任务", items.some(function(t){return t.title==="云端新增任务";}),
          items.map(function(t){return t.title;}).join("|"));
        var t2=items.filter(function(t){return t.id==="t2";})[0];
        T("同名任务采用较新云端标题", !!t2&&t2.title==="云端改过的任务", t2?t2.title:"missing");
        var sb=TASK.sidebar();
        T("云端左侧视图顺序已应用", !!sb&&sb.order&&sb.order[0]==="done"&&txt("#tkSmart [data-tkview]").indexOf("已完成")===0,
          JSON.stringify(sb)+" dom="+txt("#tkSmart [data-tkview]").slice(0,30));
        T("本机附件不被云端覆盖", !!t2&&String(t2.attachments||"").indexOf("bG9jYWw=")>=0, t2?String(t2.attachments).slice(0,60):"");
        var posts=window.__taskposts||[];
        var last=posts.length?posts[posts.length-1]:null;
        var blob=null;try{blob=JSON.parse(last[0].blob);}catch(e){}
        T("推送 blob 含任务/分组", !!blob&&blob.items.length>=2&&blob.lists.length>=2,
          blob?blob.items.length+" items / "+blob.lists.length+" lists":"no post");
        T("推送 blob 不含附件 data", !!blob&&blob.items.every(function(t){return !t.attachments;}),
          blob?blob.items.map(function(t){return t.attachments;}).join("|").slice(0,40):"");
        T("推送 blob 含左侧视图顺序", !!blob&&blob.prefs&&Array.isArray(blob.prefs.sidebarOrder)&&blob.prefs.sidebarOrder[0]==="done",
          blob&&blob.prefs?JSON.stringify(blob.prefs.sidebarOrder):"missing");
        var qel=q("#tkQuick");qel.value="云端同步新任务";
        qel.dispatchEvent(new Event("input",{bubbles:true}));
        q("#tkQuickAdd").click();
        var end=Date.now()+8000,found=false;
        while(Date.now()<end){
          posts=window.__taskposts||[];
          found=posts.some(function(p){try{return p[0].blob.indexOf("云端同步新任务")>=0;}catch(e){return false;}});
          if(found)break;
          await sleep(150);
        }
        T("本机新任务自动推送", found, "posts="+((window.__taskposts||[]).length));
        window.__holdTaskPost=true;
        qel.value="第一笔慢速保存";q("#tkQuickAdd").click();
        for(var wait=0;wait<40&&!window.__releaseTaskPost;wait++)await sleep(100);
        T("首笔写入已进入请求",!!window.__releaseTaskPost,"");
        qel.value="等待回包期间追加";q("#tkQuickAdd").click();
        await sleep(1600);
        window.__holdTaskPost=false;
        if(window.__releaseTaskPost)window.__releaseTaskPost();
        for(var n=0;n<50&&window.__taskdata[0].blob.indexOf("等待回包期间追加")<0;n++)await sleep(100);
        var final=JSON.parse(window.__taskdata[0].blob);
        T("请求期间的第二笔修改也补发",final.items.some(function(t){return t.title==="等待回包期间追加";}),"");
        T("同步后仍无 JS 报错", (window.__errs||[]).length===0, JSON.stringify(window.__errs||[]));
      }catch(e){window.__p.steps.push({k:"exception",ok:false,note:String(e&&e.stack||e)});}
      try{var x=new XMLHttpRequest();x.open("POST","/_report",false);x.setRequestHeader("Content-Type","application/json");
        x.send(JSON.stringify({steps:window.__p.steps}));}catch(e){}
    },2800);
  });
})();
</script>
'''

# 1) add taskdata to mock data
remote = {
    "v": 1,
    "lists": [
        {"id": "inbox", "name": "任务", "color": "cy", "order": 0},
        {"id": "lstudy", "name": "学习", "color": "bl", "order": 1},
        {"id": "llife", "name": "生活", "color": "sd", "order": 2},
        {"id": "lcloud", "name": "云端组", "color": "violet", "order": 3},
    ],
    "items": [
        {"id": "t2", "title": "云端改过的任务", "notes": "", "list": "llife", "done": False,
         "attachments": "", "updatedAt": tc.NOW - 1000, "order": -1},
        {"id": "tcloud", "title": "云端新增任务", "notes": "", "list": "inbox", "done": False,
         "attachments": "", "updatedAt": tc.NOW - 1000, "order": -9},
    ],
    "prefs": {"sound": True, "defaultRemind": "none",
              "sidebarOrder": ["done", "planned", "myday", "important", "all"],
              "sidebarOrderAt": tc.NOW - 500},
    "updatedAt": tc.NOW - 1000,
}
data = json.loads(json.dumps(tc.DATA))
data["taskdata"] = [{"id": tc.SID, "blob": json.dumps(remote, ensure_ascii=False), "ts": tc.NOW - 1000}]
tc.DATA.clear(); tc.DATA.update(data)

# 2) mock taskdata GET/POST + capture
tc.MOCK = tc.MOCK.replace("var DATA=__DATA__;",
                          "var DATA=__DATA__;window.__taskdata=DATA.taskdata||[];window.__taskposts=[];", 1)
tc.MOCK = tc.MOCK.replace(
    'if(s.indexOf("/userdata")>=0)return ok([]);',
    'if(s.indexOf("/taskdata")>=0){if(m==="POST"){var tb=JSON.parse(o.body||"[]");window.__taskposts.push(tb);window.__taskdata=tb;if(window.__holdTaskPost)return new Promise(function(resolve){window.__releaseTaskPost=function(){resolve(ok(tb));};});return ok(tb);}return ok(window.__taskdata||[]);}\n'
    '    if(s.indexOf("/userdata")>=0)return ok([]);', 1)

tasks = json.loads(json.dumps(tc.TASKS))
for it in tasks["items"]:
    if it["id"] == "t2":
        it["attachments"] = json.dumps([{"n": "local.txt", "t": "text/plain", "s": 5, "d": "bG9jYWw="}], ensure_ascii=False)

class H(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        open(REPORT, "wb").write(self.rfile.read(n))
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass


def main():
    html = tc.build_preview(False, tasks=tasks)
    html = html.replace("</body>", RUNNER + "\n</body>", 1)
    page = os.path.join(OUT, "cloud.html")
    open(page, "w", encoding="utf-8", newline="").write(html)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), functools.partial(H, directory=OUT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start(); time.sleep(.4)
    if os.path.exists(REPORT): os.remove(REPORT)
    subprocess.run([tc.EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                    "--window-size=1280,900", "--virtual-time-budget=30000",
                    "--user-data-dir=" + os.path.join(OUT, "prof"),
                    "http://127.0.0.1:%d/cloud.html" % PORT], capture_output=True, timeout=180)
    for _ in range(50):
        if os.path.exists(REPORT): break
        time.sleep(.2)
    if not os.path.exists(REPORT):
        print("NO REPORT"); httpd.shutdown(); return 1
    d = json.loads(open(REPORT, encoding="utf-8").read())
    fail = 0
    for s in d.get("steps", []):
        print(("PASS" if s["ok"] else "FAIL"), s["k"], s["note"])
        if not s["ok"]: fail += 1
    print("RESULT", "GREEN" if fail == 0 else "RED", "PASS", len(d.get("steps", [])) - fail, "FAIL", fail)
    httpd.shutdown()
    return 0 if fail == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
