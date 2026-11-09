# -*- coding: utf-8 -*-
"""自检：网页端「班委名单」在缓存命中（TTL 内、网络不可用）时仍必须渲染。

背景（2026-11-04 23:50 用户反馈）：「手机网页班委名单一直加载不出来」。
根因：性能优化给 membersPull() 加了 TTL 门控（6h 内不重拉）；旧实现靠 membersPull 成功后的
membersApply() 顺带调 renderCommittee()，门控命中后 renderCommittee() 没有任何调用点，
页面每次都新建 DOM，#cmOut 一直停在初始的「加载中…」。

本测试用 headless Edge + `--virtual-time-budget` + `--dump-dom`（不需要 CDP）：
  A. 缓存命中场景：本机已有 70 人名unit桶 + 最近同步时间；拦截全部云端请求（模拟弱网/离线）
     → 班委 tab 必须渲染出班委行（不允许停在「加载中…」）。
  B. 冷启动场景：本机无名单缓存；mock class_members 返回 70 人 → 班委 tab 渲染班委行。
  C. 两种场景都 0 JS 报错、0 console.error。

用法：
    cd web\tools
    python tests\committee_check.py
    set CM_SRC=<某副本.html>   # 复盘任意版本（如线上字节）
退出码 0 = 全绿。
"""
import os
import re
import sys
import json
import time
import shutil
import socket
import tempfile
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
ROOT = os.path.dirname(HERE)
SRC = os.path.abspath(os.environ.get("CM_SRC") or os.path.join(ROOT, "index.html"))
TMP = os.path.dirname(os.path.abspath(__file__))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8933
BASE = "http://127.0.0.1:%d/" % PORT

SID = "3260709999"
NAME = "测试同学"
MEMBERS = [
    {"seat": 1, "sid": "9000000001", "name": "班委甲", "role": "班长", "badge": "", "is_admin": True},
    {"seat": 2, "sid": "9000000002", "name": "普通乙", "role": "", "badge": "", "is_admin": False},
    {"seat": 3, "sid": "9000000003", "name": "班委丙", "role": "学习委员", "badge": "", "is_admin": False},
    {"seat": 4, "sid": "9000000004", "name": "班委丁", "role": "生活委员", "badge": "", "is_admin": False},
    {"seat": 5, "sid": "9000000005", "name": "普通戊", "role": "", "badge": "", "is_admin": False},
]
# 渲染期望：role/badge 非空 = 3 人
EXPECT_ROWS = 3

SEED_CACHE = (
    'try{'
    'localStorage.setItem("zq_class_identity",JSON.stringify({token:"test-token-cm",sid:"%s",name:"%s",'
    'role:"",badge:"",is_admin:false,ts:Date.now()}));'
    'var st={members:%s,rosterSel:[],groupSel:[],rollSel:[],draw:{start:1,end:70,count:10,dup:false,excl:"",sort:"draw"},'
    'group:{source:"prev",names:"",mode:"groups",n:4,shuffle:false}};'
    'localStorage.setItem("zq_tools_v2_%s",JSON.stringify(st));'
    'localStorage.setItem("zq_synced_at_%s",JSON.stringify({members:Date.now()}));'
    '}catch(e){}' % (SID, NAME, json.dumps(MEMBERS, ensure_ascii=False), SID, SID)
)
SEED_COLD = (
    'try{'
    'localStorage.setItem("zq_class_identity",JSON.stringify({token:"test-token-cm",sid:"%s",name:"%s",'
    'role:"",badge:"",is_admin:false,ts:Date.now()}));'
    'localStorage.removeItem("zq_tools_v2_%s");'
    'localStorage.removeItem("zq_synced_at_%s");'
    '}catch(e){}' % (SID, NAME, SID, SID)
)

INJECT = r"""<script>
(function(){
  window.__errs=[]; window.__cerrs=[];
  window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
  window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
  var _ce=console.error; console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));_ce.apply(console,arguments);};
  __SEED__
  window.__MEMBERS=__MEMBERS_JSON__;
  __MOCK__
  window.addEventListener("load",function(){
    setTimeout(function(){
      try{
        var all=document.querySelector('#tabsBar button[data-tab="all"]');
        if(all)all.click();
      }catch(e){}
      setTimeout(function(){
        try{
          var card=document.querySelector('#allCards [data-open="committee"]');
          if(card)card.click();
        }catch(e){}
        setTimeout(function(){
          var out=document.getElementById("cmOut");
          var r=document.createElement("div");
          r.id="cmtest-result";
          r.setAttribute("data-text",(out?out.textContent:"").replace(/\s+/g," ").trim());
          r.setAttribute("data-rows",out?out.querySelectorAll(".cmrow").length:-1);
          r.setAttribute("data-errs",(window.__errs||[]).join("|"));
          r.setAttribute("data-cerrs",(window.__cerrs||[]).join("|"));
          r.setAttribute("data-locked",document.body.classList.contains("id-locked")?"1":"0");
          r.setAttribute("data-sec-on",document.getElementById("s-committee")&&document.getElementById("s-committee").classList.contains("on")?"1":"0");
          var chip=document.getElementById("idChipTxt");
          r.setAttribute("data-user",chip?chip.textContent:"");
          document.body.appendChild(r);
        },300);
      },400);
    },700);
  });
})();
</script>"""

MOCK_BLOCK = r"""
  var _f=window.fetch;
  window.fetch=function(u,o){var s=String(u||"");
    if(s.indexOf("tcloudbasegateway")>=0||s.indexOf("tt.json")>=0)return Promise.reject(new Error("test-block"));
    return _f.apply(this,arguments);};
"""

MOCK_COLD = r"""
  window.fetch=function(u,o){var s=String(u||"");
    if(s.indexOf("rpc/class_members")>=0)return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(window.__MEMBERS);}});
    if(s.indexOf("tcloudbasegateway")>=0||s.indexOf("tt.json")>=0)return Promise.reject(new Error("test-block"));
    return Promise.reject(new Error("test-block"));};
"""


def build(name, seed, mock, members_json):
    html = open(SRC, encoding="utf-8").read()
    inject = (INJECT.replace("__SEED__", seed)
                    .replace("__MEMBERS_JSON__", members_json)
                    .replace("__MOCK__", mock))
    out = html.replace("<head>", "<head>" + inject, 1)
    path = os.path.join(TMP, name)
    open(path, "w", encoding="utf-8").write(out)
    return path


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(directory):
    port = free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a, **k: None
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def dump(url, profile):
    cmd = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           "--hide-scrollbars", "--user-data-dir=" + profile,
           "--virtual-time-budget=9000", "--dump-dom", url]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    out = (r.stdout or b"").decode("utf-8", "replace")
    err = (r.stderr or b"").decode("utf-8", "replace")
    return out, err


def parse_result(dom):
    m = re.search(r'<div id="cmtest-result"([^>]*)>', dom)
    if not m:
        return None
    attrs = {}
    for k, v in re.findall(r'data-([a-z][a-z-]*)="([^"]*)"', m.group(1)):
        attrs[k] = v
    return attrs


def run():
    steps = []

    def T(k, ok, note=""):
        steps.append((k, bool(ok), str(note)))

    preps = {}
    try:
        # A. 缓存命中（网络全断）
        preps["cache"] = build("_cm_cache.html", SEED_CACHE, MOCK_BLOCK,
                               json.dumps(MEMBERS, ensure_ascii=False))
        # B. 冷启动（无名单缓存，class_members 返回 70 人）
        preps["cold"] = build("_cm_cold.html", SEED_COLD, MOCK_COLD,
                              json.dumps(MEMBERS, ensure_ascii=False))

        httpd, port = serve(TMP)
        profile = tempfile.mkdtemp(prefix="cmprofile_")
        try:
            for key, label in (("cache", "缓存命中·网络不可用"), ("cold", "冷启动·云端返回名单")):
                url = "http://127.0.0.1:%d/%s" % (port, os.path.basename(preps[key]))
                dom, err = dump(url, profile)
                res = parse_result(dom)
                if not res:
                    T("%s：测试标记未写入（页面可能未完成初始化）" % label, False, err[-300:])
                    continue
                rows = int(res.get("rows", "-1"))
                text = res.get("text", "")
                T("%s：身份已自动进入（不卡身份页）" % label, res.get("locked") == "0", "locked=" + str(res.get("locked")))
                T("%s：已切到班委页" % label, res.get("sec-on") == "1", "secOn=" + str(res.get("sec-on")))
                T("%s：班委行渲染数 = %d" % (label, EXPECT_ROWS), rows == EXPECT_ROWS, "rows=" + str(rows) + " text=" + text[:80])
                T("%s：不再停留在「加载中…」" % label, ("加载中" not in text), text[:80])
                T("%s：显示班委姓名" % label, ("班委甲" in text and "班委丙" in text), text[:120])
                T("%s：0 JS 报错" % label, not res.get("errs"), res.get("errs", "")[:200])
                T("%s：0 console.error" % label, not res.get("cerrs"), res.get("cerrs", "")[:200])
        finally:
            httpd.shutdown()
            shutil.rmtree(profile, ignore_errors=True)
    finally:
        for p in preps.values():
            try:
                os.remove(p)
            except OSError:
                pass

    print("=" * 60)
    for k, ok, note in steps:
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", k, (" :: " + note) if (note and not ok) else ""))
    npass = sum(1 for _, ok, _ in steps if ok)
    print("=" * 60)
    print("committee_check: %d 项，PASS %d，FAIL %d" % (len(steps), npass, len(steps) - npass))
    return 0 if npass == len(steps) else 1


if __name__ == "__main__":
    sys.exit(run())
