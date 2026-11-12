# -*- coding: utf-8 -*-
r"""大屏 V5 专项自检（2026-11-11，用户反馈第 2/3/4/5 条）。

覆盖：
A. 静态：无布局/编辑模式按钮与工具栏、无顶部/灵动岛「退出聚焦」、聚焦图标 ⤢/⤡、
   stage_prefs 云同步（LWW/800ms 防抖/merge-duplicates/404 静默降级）、cleanupSession、
   4 模块专属全屏 UI 标记、iOS 灵动岛 spring 曲线与 reduced-motion、名单无重复「班委」badge、
   全部页卡片描述、APP_VER 不变；
B. 桌面 1366×768（mock 云端+drop）：
   B1 顶部按钮（无布局/无退出聚焦；＋模块/全屏/关闭/互联）
   B2 鼠标按住表头直拖：跟手幽灵 + 其他模块 WAAPI FLIP 让位 + 落位持久化
   B3 右下角拖宽（非编辑模式）
   B4 模块管理弹层增删 + 卡片表头 ×
   B5 聚焦按钮图标切换 + 4 模块专属全屏 UI（计时超大数字/抽签超大结果+最近/投票大号结果条+倒计时/演示大标题+大按钮）
   B6 灵动岛：34px 黑胶囊、展开卡片、spring 动画、无「退出聚焦」、多活动图标+数量、点按可聚焦
   B7 退出大屏清理：计时归零/抽签清空/投票详情与发起草稿清空/聚焦与灵动岛清空/上传队列清空；
      布局偏好与文件传输会话保留（不调用 /close）
C. 触屏 390×844：长按 180ms 才能拖、短按不拖；长按拖动重排
D. stage_prefs：GET LWW（云端更新→应用；本机更新→推）、POST 防抖 800ms、merge-duplicates、
   404 静默降级 localStorage、空表 seed 推送
E. 360/430/1280 无横向溢出 + 截图
F. prefers-reduced-motion：灵动岛/FLIP 不产生动画
G. 0 JS 报错 / 0 console.error / 无外部网络请求

用法：python tools\tests\v2_stage_v5_check.py
退出码 0 = 全绿。
"""
import http.server
import json
import os
import socketserver
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SRC = os.path.abspath(os.environ.get("SPEC_CHECK") or os.path.join(TOOLS, "index.html"))
SRC_TEXT = open(SRC, encoding="utf-8").read()
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

SID = "9999000001"
NAME = "测试同学"
SHOTS = os.path.join(HERE, "_shots_stage_v5")
PASS = 0
FAIL = 0
FAILS = []


def T(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + name)
    else:
        FAIL += 1
        FAILS.append(name + (" | " + str(detail) if detail != "" else ""))
        print("  [FAIL] " + name + (("  <" + str(detail) + ">") if detail != "" else ""))


# ---------------------------------------------------------------- mock 数据
MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": ("班长" if i == 1 else ""), "badge": ("班委" if i <= 3 else ""), "is_admin": False}
           for i in range(1, 71)]
POLLSET = {"multi": False, "maxChoices": 1, "anonymous": True, "allowChange": True, "resultVisibility": "always"}
DECKS = [
    {"id": "d1", "title": "团日活动演示", "status": "ready", "progress": 100, "slide_count": 2, "step_count": 2,
     "aspect": "16:9", "cover_url": "", "owner_name": "测试同学", "source_name": "团日活动演示.pptx",
     "created_at": 3, "converted_at": 4},
    {"id": "d2", "title": "团支部年度工作总结", "status": "ready", "progress": 100, "slide_count": 8,
     "step_count": 12, "aspect": "16:9", "cover_url": "", "owner_name": "李同学", "source_name": "总结.pptx",
     "created_at": 2, "converted_at": 3},
]
FILES_ROWS = [
    {"id": "d2", "files": {"compat": {"s": "ppt/a/d2/build/compat.pptx", "size": 39000000, "name": "总结_兼容版.pptx"},
                           "pdf": {"s": "ppt/a/d2/build/preview.pdf", "size": 1200000, "name": "总结.pdf", "pages": 16}}},
    {"id": "d1", "files": None},
]
MANIFESTS = [
    {"id": "d2", "title": "团支部年度工作总结", "slide_count": 8, "step_count": 12, "aspect": "16:9", "cover_url": "",
     "manifest": {"base": "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/", "slides": [],
                  "files": {"compat": {"s": "ppt/a/d2/build/compat.pptx", "size": 39000000, "name": "总结_兼容版.pptx"},
                            "pdf": {"s": "ppt/a/d2/build/preview.pdf", "size": 1200000, "name": "总结.pdf", "pages": 16}}}},
    {"id": "d1", "title": "团日活动演示", "slide_count": 2, "step_count": 2, "aspect": "16:9", "cover_url": "",
     "manifest": {"slides": [{"steps": [{"img": "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="}], "tr": "fade"}]}},
]
GIF = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
DATA = {"members": MEMBERS}

INIT_TMPL = r"""
(function(){
  window.__errs=[];window.__cerrs=[];
  window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
  window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
  (function(){var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};})();
  window.__stageMock={mode:"__MODE__",remote:__REMOTE__,local:__LOCAL__,getCount:0,postCount:0,gets:[],posts:[],
    dropOpen:0,dropClose:0};
  var _f=window.fetch&&window.fetch.bind(window);
  function J(obj,status){return Promise.resolve(new Response(JSON.stringify(obj),{status:status||200,headers:{"Content-Type":"application/json"}}));}
  function ET(status){return Promise.resolve(new Response("",{status:status||200}));}
  try{
    if(!sessionStorage.getItem("__sv5_init")){localStorage.clear();sessionStorage.setItem("__sv5_init","1");}
  }catch(e){}
  try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:true,ts:Date.now()}));}catch(e){}
  try{window.__DROP_BASE=location.origin+"/dropmock";}catch(e){}
  if(window.__stageMock.local){try{localStorage.setItem("zq_stage_layout_v1",JSON.stringify(window.__stageMock.local));}catch(e){}}
  var DATA=__DATA__;
  var PNOW=Date.now()+1800000;
  var POLLSET=__POLLSET__;
  var POLL={id:"p1",title:"团日活动形式投票",description:"",mode:"quick",owner_name:"测试同学",settings:POLLSET,
    deadline:PNOW,status:"open",closed_at:0,created_at:Date.now(),updated_at:Date.now(),closed:false,
    total:12,counts:{o1:7,o2:5},has_voted:false,my_choices:[],results_hidden:false,mine:true,can_manage:true};
  var PDETAIL={ok:true,now:Date.now(),poll:{id:"p1",title:"团日活动形式投票",description:"",mode:"quick",owner_name:"测试同学",
    settings:POLLSET,options:[{id:"o1",text:"参观红色基地"},{id:"o2",text:"主题团课"}],deadline:PNOW,status:"open",closed_at:0,
    created_at:Date.now(),updated_at:Date.now()},closed:false,total:12,counts:{o1:7,o2:5},has_voted:false,my_choices:[],
    results_hidden:false,mine:true,can_manage:true,voters:[]};
  window.fetch=function(u,o){
    var url=String((u&&u.url!==undefined)?u.url:u);
    var m=String((o&&o.method)||"GET").toUpperCase();
    var H=(o&&o.headers)||{};
    if(url.indexOf("stage_prefs")>=0){
      if(m==="POST"){
        window.__stageMock.postCount++;
        var body={};try{body=JSON.parse(o.body||"{}");}catch(e){}
        window.__stageMock.posts.push({body:body,prefer:String((H.Prefer||H.prefer||""))});
        return window.__stageMock.mode==="post404"?ET(404):ET(201);
      }
      window.__stageMock.getCount++;window.__stageMock.gets.push(url);
      if(window.__stageMock.mode==="404")return ET(404);
      if(window.__stageMock.mode==="error")return Promise.reject(new Error("mock offline"));
      if(window.__stageMock.mode==="empty")return J([]);
      return J(window.__stageMock.remote||[]);
    }
    if(url.indexOf("/dropmock")>=0){
      var ds={id:"sess-qa",code:"2468",expiresAt:Date.now()+3600000,createdAt:Date.now()};
      if(url.indexOf("/open")>=0){window.__stageMock.dropOpen++;return J({ok:true,session:ds});}
      if(url.indexOf("/close")>=0){window.__stageMock.dropClose++;return J({ok:true});}
      if(url.indexOf("/state")>=0)return J({ok:true,session:ds,events:[],cursor:0});
      if(url.indexOf("/mine")>=0)return J({ok:true,session:ds});
      return J({ok:true});
    }
    if(url.indexOf("tcloudbasegateway")<0){
      return _f.apply(this,arguments);
    }
    if(url.indexOf("rpc/class_members")>=0)return J(DATA.members);
    if(url.indexOf("rpc/poll_list")>=0)return J({ok:true,now:Date.now(),polls:[POLL]});
    if(url.indexOf("rpc/poll_detail")>=0)return J(PDETAIL);
    if(url.indexOf("rpc/class_league")>=0)return J({ok:true,count:3,seats:[{seat:1,name:"同学甲"},{seat:2,name:"同学乙"},{seat:3,name:"同学丙"}]});
    if(url.indexOf("ppt_decks")>=0){
      if(url.indexOf("files%3A")>=0||url.indexOf("files:")>=0)return J(__FILES__);
      if(url.indexOf("manifest")>=0)return J(__MANIFESTS__);
      return J(__DECKS__);
    }
    if(url.indexOf("/site_assets")>=0)return J([{body:{seen_at:Date.now()},updated_at:Date.now()}]);
    if(url.indexOf("/notices")>=0)return J(url.indexOf("select=id,ts")>=0?[]:[]);
    if(url.indexOf("/userdata")>=0)return J([]);
    return J([]);
  };
})()
"""

REMOTE_DEFAULT = {"v": 1, "order": ["ppt", "vote", "timer", "draw"], "span": {"ppt": 8, "vote": 4, "timer": 6, "draw": 6},
                  "hidden": [], "lastDeck": "", "pptDl": {}, "at": 1000}


def iso_ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def init_script(mode="remote", remote=None, local=None):
    s = INIT_TMPL
    s = s.replace("__MODE__", mode)
    s = s.replace("__REMOTE__", json.dumps(remote if remote is not None else [], ensure_ascii=False))
    s = s.replace("__LOCAL__", json.dumps(local, ensure_ascii=False) if local is not None else "null")
    s = s.replace("__DATA__", json.dumps(DATA, ensure_ascii=False))
    s = s.replace("__POLLSET__", json.dumps(POLLSET, ensure_ascii=False))
    s = s.replace("__DECKS__", json.dumps(DECKS, ensure_ascii=False))
    s = s.replace("__FILES__", json.dumps(FILES_ROWS, ensure_ascii=False))
    s = s.replace("__MANIFESTS__", json.dumps(MANIFESTS, ensure_ascii=False))
    s = s.replace("__SID__", SID).replace("__NAME__", NAME)
    return s


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(port):
    root = TOOLS
    h = lambda *a, **kw: Quiet(*a, directory=root, **kw)
    s = socketserver.ThreadingTCPServer(("127.0.0.1", port), h)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


URL = ""


def new_page(b, w=1366, h=768, mobile=False, **cfg):
    p = b.new_page("about:blank")
    p.set_device(w, h, dpr=2.0 if mobile else 1.0, mobile=mobile, touch=mobile)
    p.add_init_script(init_script(**cfg))
    p.navigate(URL)
    p.wait_load(30)
    p.wait_for("!document.body.classList.contains('auth-pending')", 25)
    time.sleep(0.6)
    return p


def open_stage(p, timeout=12):
    p.evaluate("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();return 'x';})()")
    if not p.wait_for("!!document.querySelector('#opt2StageBtn')", timeout):
        return False
    p.evaluate("document.querySelector('#opt2StageBtn').click();'x'")
    ok = p.wait_for("(function(){var s=document.querySelector('#opt2Stage');return !!s&&s.style.display!=='none'&&document.querySelectorAll('#o2sBody .opt2-panel').length===4;})()", timeout)
    time.sleep(0.7)
    return ok


def snap(p):
    return p.evaluate(r"""(function(){
      var q=function(s){return document.querySelector(s);};
      var rect=function(e){if(!e)return null;var r=e.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height};};
      var panels=[].map.call(document.querySelectorAll('#o2sBody .opt2-panel'),function(x){
        return {k:x.getAttribute('data-panel'),hidden:x.hidden,span:x.style.gridColumn,
          cls:String(x.className),rect:rect(x),zbtn:(x.querySelector('.opt2-zbtn')||{}).textContent||''};});
      var island=q('#o2sIsland'),core=q('#o2sIsCore'),drop=q('#o2sIslandDrop');
      var gw=window.__stageMock||{};
      return {
        panels:panels,
        bodyFocus:q('#o2sBody')?q('#o2sBody').classList.contains('opt2-focusmode'):null,
        order:panels.map(function(x){return x.k;}),
        island:{hidden:island?island.hidden:null,cls:island?String(island.className):'',
          rect:rect(core),bg:island?getComputedStyle(island).backgroundColor:null,
          radius:island?getComputedStyle(island).borderRadius:null,
          open:island?island.classList.contains('open'):null,
          aria:core?core.getAttribute('aria-expanded'):null,
          txt:core?String(core.textContent||''):'',
          dropHidden:drop?drop.hidden:null,dropTxt:drop?String(drop.textContent||''):''},
        overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
        stageDisplay:q('#opt2Stage')?q('#opt2Stage').style.display:null,
        layout:(function(){try{return JSON.parse(localStorage.getItem('zq_stage_layout_v1')||'null');}catch(e){return null;}})(),
        mock:{getCount:gw.getCount,postCount:gw.postCount,gets:gw.gets||[],posts:gw.posts||[],dropOpen:gw.dropOpen,dropClose:gw.dropClose},
        errs:(window.__errs||[]).slice(-4),cerrs:(window.__cerrs||[]).slice(-4)
      };
    })()""")


def drag_mouse(p, from_sel, to_sel, steps=3, mid_cb=None):
    a = p.evaluate("(function(){var e=document.querySelector(%s);if(!e)return null;var r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+Math.min(20,r.height/2)};})()" % json.dumps(from_sel))
    b = p.evaluate("(function(){var e=document.querySelector(%s);if(!e)return null;var r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()" % json.dumps(to_sel))
    if not a or not b:
        return False
    p.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": int(a["x"]), "y": int(a["y"]), "button": "left", "clickCount": 1})
    time.sleep(0.05)
    for i in range(1, steps + 1):
        x = a["x"] + (b["x"] - a["x"]) * i / steps
        y = a["y"] + (b["y"] - a["y"]) * i / steps
        p.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": int(x), "y": int(y), "button": "left"})
        time.sleep(0.08)
        if mid_cb:
            mid_cb(i, steps)
    p.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": int(b["x"]), "y": int(b["y"]), "button": "left", "clickCount": 1})
    time.sleep(0.4)
    return True


def touch_longpress_drag(p, from_sel, to_sel, hold=0.24, steps=6):
    a = p.evaluate("(function(){var e=document.querySelector(%s);if(!e)return null;var r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()" % json.dumps(from_sel))
    b = p.evaluate("(function(){var e=document.querySelector(%s);if(!e)return null;var r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()" % json.dumps(to_sel))
    if not a or not b:
        return False
    p.touch_begin(a["x"], a["y"])
    time.sleep(hold)
    for i in range(1, steps + 1):
        x = a["x"] + (b["x"] - a["x"]) * i / steps
        y = a["y"] + (b["y"] - a["y"]) * i / steps
        p.touch_move(x, y)
        time.sleep(0.05)
    p.touch_end(b["x"], b["y"])
    time.sleep(0.45)
    return True


def focused_snap(p, k):
    return p.evaluate(r"""(function(){
      var q=function(s){return document.querySelector(s);};
      var panel=q('#opt2Stage [data-panel="%s"]');
      var fs=function(sel){var e=q(sel);return e?parseFloat(getComputedStyle(e).fontSize):0;};
      return {
        focused:!!panel&&panel.classList.contains('opt2-focused'),
        otherHidden:[].every.call(document.querySelectorAll('#o2sBody .opt2-panel'),function(x){return x===panel||x.hidden;}),
        zbtn:panel?String((panel.querySelector('.opt2-zbtn')||{}).textContent||''):'',
        bodyFocus:q('#o2sBody')?q('#o2sBody').classList.contains('opt2-focusmode'):false,
        fv:!!q('#opt2Stage [data-fv="%s"]'),
        timerNum:fs('#o2sTimer'), timerBig:!!q('#opt2Stage [data-fv="timer"] .opt2-fv-big'),
        timerChips:document.querySelectorAll('#opt2Stage [data-fv="timer"] .opt2-tchip').length,
        drawPick:fs('#opt2Stage [data-fv="draw"] .opt2-fv-pick'), drawBig:!!q('#opt2Stage [data-fv="draw"] .opt2-fv-big'),
        drawRecent:document.querySelectorAll('#opt2Stage .opt2-fv-rec').length,
        voteCd:q('#o2sVoteCd')?String(q('#o2sVoteCd').textContent||''):'',
        voteCdSize:fs('#o2sVoteCd'),
        voteBar:q('#opt2Stage [data-fv="vote"] .opt2-vbar')?parseFloat(getComputedStyle(q('#opt2Stage [data-fv="vote"] .opt2-vbar')).height):0,
        pptTtl:fs('#opt2Stage [data-fv="ppt"] .opt2-ppt-ttl'),
        pptPlay:!!q('#opt2Stage [data-fv="ppt"] .opt2-play')
      };
    })()""" % (k, k))


def main():
    global URL
    os.makedirs(SHOTS, exist_ok=True)
    port = 8977
    srv = serve(port)
    URL = "http://127.0.0.1:%d/index.html" % port

    # ================================================================ A 静态
    print("\n== A 静态检查 ==")
    s = SRC_TEXT
    checks = [
        ("A1 APP_VER 仍为 2.0.0", 'var APP_VER="2.0.0"' in s),
        ("A2 无布局/编辑模式按钮 DOM（o2sLay/o2sLbar/o2sSelbar/o2sGrid）",
         all(x not in s for x in ('id="o2sLay"', 'id="o2sLbar"', 'id="o2sSelbar"', 'id="o2sGrid"'))),
        ("A3 无 ↑↓/宽度/隐藏 编辑工具栏（data-stg=layup/laydown/laysize/layhide/laytoggle）",
         all(x not in s for x in ('data-stg="layup"', 'data-stg="laydown"', 'data-stg="laysize"',
                                  'data-stg="layhide"', 'data-stg="laytoggle"', 'opt2-etools', 'opt2-editing'))),
        ("A4 无顶部退出聚焦按钮 #o2sFocusExit", 'id="o2sFocusExit"' not in s),
        ("A5 无灵动岛「退出聚焦」入口（全文仅遥控器保留 1 处）", s.count("退出聚焦") == 1),
        ("A6 聚焦按钮图标 ⤢/⤡ 切换与 dataset 标记", '"⤡" : "⤢"' in s or ('on?"⤡":"⤢"' in s) and 'data-fv' in s),
        ("A7 直拖：触屏长按 180ms + 鼠标表头 + 跟手幽灵 + FLIP", all(x in s for x in (
            "STG_LONG_PRESS=180", 'class="opt2-phd"', "opt2-ghost", "stgAnimateFlip", "pointerType===\"touch\""))),
        ("A8 模块管理：顶栏＋模块 + 卡片表头移除按钮", all(x in s for x in (
            'id="o2sModBtn"', 'data-stg="modopen"', 'data-stg="modremove"', "stgModToggle"))),
        ("A9 右下拖宽不再依赖编辑模式", "V5 起始终可用" in s and ".opt2-resize{display:block" in s),
        ("A10 stage_prefs 云同步：GET layout,updated_at + POST on_conflict=sid + merge-duplicates + 800ms 防抖",
         all(x in s for x in ("stage_prefs?select=layout,updated_at", "stage_prefs?on_conflict=sid",
                              "resolution=merge-duplicates", "STG_PUSH_DEBOUNCE=800", "LWW"))),
        ("A11 旧 localStorage 键保留为离线缓存 + 首次 seed", all(x in s for x in (
            'STG_DECK_KEY="zq_stage_deck_v1"', 'STG_LAYOUT_KEY="zq_stage_layout_v1"', 'STG_PPT_DL_KEY="zq_stage_ppt_dl_v1"'))),
        ("A11b 云同步 layout 含 order/span/hidden/lastDeck/pptDl",
         all(x in s for x in ("return {v:1,order:", "span:Object.assign", "hidden:", "lastDeck:String", "pptDl:dk"))),
        ("A12 退出清理 stgCleanupSession（close 调用）", "function stgCleanupSession()" in s and "stgCleanupSession();" in s),
        ("A13 4 模块专属全屏 UI 标记", all(x in s for x in (
            'data-fv="timer"', 'data-fv="draw"', 'data-fv="vote"', 'data-fv="ppt"', ".opt2-fv-timer .opt2-fv-num", ".opt2-fv-vote .opt2-vbar", ".opt2-fv-ppt .opt2-ppt-ttl"))),
        ("A14 iOS 灵动岛：黑胶囊 34px + spring 曲线 + reduced-motion",
         all(x in s for x in ("min-height:34px", "cubic-bezier(.34,1.56,.64,1)", "opt2-is-panel")) and
         "prefers-reduced-motion:reduce" in s),
        ("A15 名单工具无重复「班委」badge（cmbadge 源码清零）", "cmbadge" not in s),
        ("A16 全部页卡片描述去掉「班级身份气泡」", "班级身份气泡" not in s and 'd:"班委、团员与全班名单"' in s),
        ("A17 布局撤销：顶栏↶ + 模块弹层撤销 + 历史栈（layoutHist/stgUndoLayout）",
         all(x in s for x in ('id="o2sUndo"', 'data-stg="undolayout"', 'data-stg="modundo"',
                              "layoutHist", "stgUndoLayout", "stgPushHist"))),
        ("A18 布局锁定：模块弹层锁定按钮 + layout.locked 持久化 + opt2-locked",
         all(x in s for x in ('data-stg="modlock"', 'id="o2sModLock"', "locked:!!L.locked",
                              "L.locked=!!(o&&o.locked)", "opt2-locked"))),
        ("A19 拖动把手：表头 ⠿ + title（可发现性）",
         'class="opt2-grip"' in s and 'title="按住拖动排序"' in s and ".opt2-grip{" in s),
        ("A20 首次进入提示：按住卡片可拖动排序（每浏览器一次）",
         "zq_stage_hint_v1" in s and "按住卡片可拖动排序" in s),
    ]
    for name, cond in checks:
        T(name, cond)

    b = _cdp.Browser(window=(1366, 768))

    # ================================================================ B 桌面交互
    print("\n== B 桌面 1366×768 ==")
    remote_row = [{"layout": dict(REMOTE_DEFAULT), "updated_at": iso_ago(3600)}]
    p = new_page(b, 1366, 768, mobile=False, mode="remote", remote=remote_row)
    T("B0 大屏可打开（4 面板）", open_stage(p))
    st = snap(p)
    T("B1 顶栏无布局/退出聚焦按钮", p.evaluate("!document.querySelector('#o2sLay')&&!document.querySelector('#o2sFocusExit')&&!document.querySelector('#o2sLbar')"))
    T("B1 顶栏有「＋ 模块」/全屏/关闭/互联", p.evaluate("!!document.querySelector('#o2sModBtn')&&!!document.querySelector('#o2sFs')&&!!document.querySelector('#o2sClose')&&!!document.querySelector('#o2sDropBtn')"))
    T("B1 顶栏有撤销布局按钮（初始不可用）",
      p.evaluate("(function(){var b=document.querySelector('#o2sUndo');return !!b&&b.classList.contains('off');})()"))
    T("B1 4 个模块面板顺序=布局", st["order"] == ["ppt", "vote", "timer", "draw"], st["order"])
    T("B1 右下角拖宽手柄 4 个", p.evaluate("document.querySelectorAll('#opt2Stage [data-resize]').length===4"))
    p.screenshot(os.path.join(SHOTS, "desktop_default_1366.png"))

    # B2 鼠标直拖 + 幽灵 + FLIP
    mid = {"ghost": 0, "dragcls": 0, "anim": 0, "ghost_transform": ""}

    def mid_cb(i, n):
        if i != n // 2:
            return
        time.sleep(0.1)
        mid.update(p.evaluate(r"""(function(){
          var g=document.querySelector('#opt2Stage .opt2-ghost');
          var anims=document.getAnimations?document.getAnimations():[];
          var flip=0;anims.forEach(function(a){try{var t=a.effect&&a.effect.target;if(t&&t.classList&&t.classList.contains('opt2-panel'))flip++;}catch(e){}});
          return {ghost:g?1:0,dragcls:document.querySelectorAll('#opt2Stage .opt2-panel.opt2-dragging').length,anim:flip,
            ghost_transform:g?String(g.style.transform||''):''};
        })()"""))
        p.screenshot(os.path.join(SHOTS, "desktop_drag_ghost_1366.png"))

    T("B2 鼠标按住表头拖动（过程）", drag_mouse(p, '#opt2Stage [data-panel="ppt"] [data-panelhd]', '#opt2Stage [data-panel="vote"]', mid_cb=mid_cb))
    T("B2 拖动中出现跟手幽灵", mid["ghost"] == 1, mid)
    T("B2 拖动中源卡留位标记", mid["dragcls"] == 1, mid)
    T("B2 其他模块 FLIP 让位动画", mid["anim"] >= 1, mid)
    st = snap(p)
    T("B2 直拖后顺序变化", st["order"][:2] == ["vote", "ppt"], st["order"])
    try:
        lo = json.loads(p.evaluate("localStorage.getItem('zq_stage_layout_v1')||'null'"))
    except Exception:
        lo = None
    T("B2 直拖落位持久化到 zq_stage_layout_v1", bool(lo) and lo.get("order", [])[:2] == ["vote", "ppt"], lo and lo.get("order"))
    T("B2 拖后云端防抖推送（800ms 内 ≥1 次 POST）",
      (lambda: (time.sleep(1.2), snap(p)["mock"]["postCount"] >= 1)[1])(), "")
    posts = snap(p)["mock"]["posts"]
    T("B2 POST body={sid,layout} 且 Prefer=merge-duplicates",
      bool(posts) and posts[-1]["body"].get("sid") == SID and isinstance(posts[-1]["body"].get("layout"), dict) and
      "merge-duplicates" in posts[-1]["prefer"], posts[-1] if posts else None)
    # 撤销：点击顶栏 ↶ 恢复拖动前顺序
    p.evaluate("document.querySelector('#o2sUndo').click();'x'")
    time.sleep(0.5)
    st_u = snap(p)
    lo_u = json.loads(p.evaluate("localStorage.getItem('zq_stage_layout_v1')||'null'"))
    T("B2 撤销布局：恢复拖动前顺序并持久化",
      st_u["order"] == ["ppt", "vote", "timer", "draw"] and lo_u and lo_u.get("order")[:2] == ["ppt", "vote"],
      (st_u["order"], lo_u and lo_u.get("order")))
    T("B2 撤销后按钮回到不可用（栈空）",
      p.evaluate("document.querySelector('#o2sUndo').classList.contains('off')"))

    # B3 拖宽
    p.evaluate(r"""(function(){
      var panel=document.querySelector('#opt2Stage [data-panel="vote"]'),grip=panel.querySelector('[data-resize]');
      var r=grip.getBoundingClientRect(),colW=document.querySelector('#o2sBody').clientWidth/12;
      function pe(el,t,x,y){el.dispatchEvent(new PointerEvent(t,{bubbles:true,cancelable:true,clientX:x,clientY:y,pointerId:9,button:0,pointerType:"mouse"}));}
      pe(grip,'pointerdown',r.left+r.width/2,r.top+r.height/2);
      document.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,cancelable:true,clientX:r.left+r.width/2+colW*3,clientY:r.top+r.height/2,pointerId:9,button:0,pointerType:"mouse"}));
      document.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,cancelable:true,clientX:r.left+r.width/2+colW*3,clientY:r.top+r.height/2,pointerId:9,button:0,pointerType:"mouse"}));
      return 'x';
    })()""")
    time.sleep(0.35)
    lo = json.loads(p.evaluate("localStorage.getItem('zq_stage_layout_v1')||'null'"))
    T("B3 右下角拖宽改变宽度并持久化（非编辑模式）", lo and str(lo.get("span", {}).get("vote")) != "4", lo and lo.get("span"))
    time.sleep(0.9)
    posts3 = snap(p)["mock"]["posts"]
    T("B3 改宽进入云同步布局（POST layout.span）",
      bool(posts3) and isinstance(posts3[-1]["body"].get("layout", {}).get("span"), dict) and
      str(posts3[-1]["body"]["layout"]["span"].get("vote")) != "4", posts3[-1] if posts3 else None)

    # B4 模块管理
    p.evaluate("document.querySelector('#o2sModBtn').click();'x'")
    time.sleep(0.3)
    T("B4 模块管理弹层：4 模块 + 当前显示状态",
      p.evaluate("(function(){var m=document.querySelector('#o2sModModal');return !!m&&!m.hidden&&document.querySelectorAll('#o2sModBody .opt2-modrow').length===4;})()"))
    p.screenshot(os.path.join(SHOTS, "desktop_module_manager_1366.png"))
    p.evaluate("document.querySelector('#o2sModBody [data-stg=\"modtoggle\"][data-k=\"timer\"]').click();'x'")
    time.sleep(0.3)
    T("B4 移除模块生效", p.evaluate("document.querySelector('#opt2Stage [data-panel=\"timer\"]').hidden===true"))
    p.evaluate("document.querySelector('#o2sModBody [data-stg=\"modtoggle\"][data-k=\"timer\"]').click();'x'")
    time.sleep(0.3)
    T("B4 加回模块生效", p.evaluate("document.querySelector('#opt2Stage [data-panel=\"timer\"]').hidden===false"))
    T("B4 模块管理含撤销/锁定按钮",
      p.evaluate("!!document.querySelector('#o2sModUndo')&&!!document.querySelector('#o2sModLock')"))
    p.evaluate("document.querySelector('#o2sModLock').click();'x'")
    time.sleep(0.3)
    locked = p.evaluate("(function(){var lo=JSON.parse(localStorage.getItem('zq_stage_layout_v1')||'null');return !!(lo&&lo.locked)&&document.getElementById('opt2Stage').classList.contains('opt2-locked');})()")
    T("B4 锁定布局：写入 layout.locked + opt2-locked 生效", locked, locked)
    p.evaluate("document.querySelector('#o2sModLock').click();'x'")
    time.sleep(0.25)
    unlocked = p.evaluate("!document.getElementById('opt2Stage').classList.contains('opt2-locked')")
    T("B4 解锁布局生效", unlocked, unlocked)
    p.evaluate("document.querySelector('#o2sModModal [data-stg=\"modclose\"]').click();'x'")
    time.sleep(0.2)
    T("B4 卡片表头 × 移除按钮可移除模块",
      (p.evaluate("document.querySelector('#opt2Stage [data-panel=\"draw\"] [data-stg=\"modremove\"]').click();'x'"), time.sleep(0.3),
       p.evaluate("document.querySelector('#opt2Stage [data-panel=\"draw\"]').hidden===true"))[2])
    p.evaluate("(function(){var b=document.querySelector('#o2sModBtn');b.click();return 'x';})()")
    time.sleep(0.25)
    p.evaluate("document.querySelector('#o2sModBody [data-stg=\"modtoggle\"][data-k=\"draw\"]').click();'x'")
    time.sleep(0.25)
    p.evaluate("document.querySelector('#o2sModModal [data-stg=\"modclose\"]').click();'x'")
    time.sleep(0.2)

    # B5 聚焦按钮 + 4 模块专属 UI
    print("\n== B5 聚焦专属全屏 UI ==")
    for k, label, keys in (
            ("timer", "计时", ("timerNum", "timerBig", "timerChips")),
            ("draw", "抽签", ("drawPick", "drawBig")),
            ("vote", "投票", ("voteCd", "voteCdSize", "voteBar")),
            ("ppt", "演示", ("pptTtl", "pptPlay"))):
        s0 = snap(p)
        T("B5-%s 未聚焦时图标 ⤢" % label, [x for x in s0["panels"] if x["k"] == k][0]["zbtn"] == "⤢")
        p.evaluate("document.querySelector('#opt2Stage [data-panel=\"%s\"] .opt2-zbtn').click();'x'" % k)
        time.sleep(0.5)
        fs = focused_snap(p, k)
        T("B5-%s 聚焦：单面板铺满 + 图标变缩小 ⤡" % label, fs["focused"] and fs["otherHidden"] and fs["zbtn"] == "⤡" and fs["bodyFocus"], fs)
        T("B5-%s 聚焦：专属全屏 UI [data-fv]" % label, fs["fv"])
        if k == "timer":
            T("B5-计时：超大数字 + 大按钮 + 快捷时长", fs["timerNum"] >= 90 and fs["timerBig"] and fs["timerChips"] >= 5, fs["timerNum"])
            p.screenshot(os.path.join(SHOTS, "desktop_focus_timer_1366.png"))
        elif k == "draw":
            T("B5-抽签：超大结果 + 大按钮", fs["drawPick"] >= 80 and fs["drawBig"], fs["drawPick"])
            p.evaluate("document.querySelector('#opt2Stage [data-fv=\"draw\"] [data-o2pick=\"1\"]').click();'x'")
            time.sleep(0.35)
            fs2 = focused_snap(p, k)
            T("B5-抽签：最近结果列表", fs2["drawRecent"] >= 1, fs2["drawRecent"])
            p.screenshot(os.path.join(SHOTS, "desktop_focus_draw_1366.png"))
        elif k == "vote":
            T("B5-投票：大号结果条 + 倒计时", fs["voteCd"] and fs["voteCdSize"] >= 20 and fs["voteBar"] >= 14, (fs["voteCd"], fs["voteCdSize"], fs["voteBar"]))
            p.screenshot(os.path.join(SHOTS, "desktop_focus_vote_1366.png"))
        elif k == "ppt":
            T("B5-演示：大标题 + 大按钮", fs["pptTtl"] >= 34 and fs["pptPlay"], fs["pptTtl"])
            p.screenshot(os.path.join(SHOTS, "desktop_focus_ppt_1366.png"))
            p.evaluate("(function(){var r=document.querySelector('#opt2Stage [data-panel=\"ppt\"] [data-pptsel]');if(r)r.click();return 'x';})()")
            time.sleep(1.0)
            last_deck = None
            for x in snap(p)["mock"]["posts"]:
                if (x.get("body", {}).get("layout", {}) or {}).get("lastDeck"):
                    last_deck = x["body"]["layout"]["lastDeck"]
            T("B5-演示：上次使用 deck 写入布局并云同步（layout.lastDeck）", bool(last_deck), last_deck)
        p.evaluate("document.querySelector('#opt2Stage [data-panel=\"%s\"] .opt2-zbtn').click();'x'" % k)
        time.sleep(0.35)
        T("B5-%s 再点还原多面板" % label, snap(p)["bodyFocus"] is False)

    # B6 灵动岛
    print("\n== B6 iOS 灵动岛 ==")
    p.evaluate("(function(){var b=document.querySelector('#opt2Stage [data-panel=\"timer\"] [data-o2timer=\"1\"]');if(b)b.click();return 'x';})()")
    time.sleep(1.3)
    p.evaluate("(function(){var b=document.querySelector('#opt2Stage [data-panel=\"vote\"] [data-stg=\"voterefresh\"]');if(b)b.click();return 'x';})()")
    time.sleep(0.8)
    isl = snap(p)["island"]
    T("B6 灵动岛可见（进行中活动）", isl["hidden"] is False, isl)
    T("B6 紧凑态：黑色胶囊约 34px + 圆角胶囊", isl["bg"] in ("rgb(0, 0, 0)", "rgba(0, 0, 0, 1)") and abs(isl["rect"]["h"] - 34) <= 2 and float(str(isl["radius"]).split("px")[0]) >= 16, (isl["bg"], isl["rect"], isl["radius"]))
    T("B6 紧凑态显示活动图标 + 数量或文案", len(isl["txt"]) > 0 and "▾" in isl["txt"], isl["txt"])
    p.evaluate("document.querySelector('#o2sIsCore').click();'x'")
    time.sleep(0.5)
    isl = snap(p)["island"]
    T("B6 点按展开：.open + aria-expanded=true + 卡片面板", isl["open"] and isl["aria"] == "true" and isl["dropHidden"] is False, isl)
    T("B6 展开面板：进行中行 + 可聚焦模块 + 无「退出聚焦」",
      "进行中" in isl["dropTxt"] and "可聚焦模块" in isl["dropTxt"] and "退出聚焦" not in isl["dropTxt"], isl["dropTxt"][:120])
    T("B6 展开：spring 形变动画（WAAPI）",
      p.evaluate("(function(){var a=document.getAnimations?document.getAnimations():[];return a.some(function(x){try{var t=x.effect&&x.effect.target;return t&&(t.id==='o2sIsCore'||t.id==='o2sIslandDrop');}catch(e){return false;}})})()"))
    p.screenshot(os.path.join(SHOTS, "desktop_island_1366.png"))
    p.evaluate("document.querySelector('#o2sIslandDrop [data-stg=\"islandfocus\"][data-k=\"timer\"]').click();'x'")
    time.sleep(0.45)
    fs = focused_snap(p, "timer")
    T("B6 岛内点按进行中活动 → 聚焦对应模块", fs["focused"], fs)
    p.evaluate("document.querySelector('#opt2Stage [data-panel=\"timer\"] .opt2-zbtn').click();'x'")
    time.sleep(0.35)
    p.evaluate("document.querySelector('#o2sIsCore').click();'x'")
    time.sleep(0.4)
    T("B6 再次展开后点外部关闭", (p.evaluate("document.querySelector('#opt2Stage .opt2-top').click();'x'"), time.sleep(0.35), snap(p)["island"]["dropHidden"])[2])

    # B7 退出清理
    print("\n== B7 退出大屏清理 ==")
    # 准备：计时运行、抽签结果、投票发起草稿、聚焦、上传队列（控制器上传项）
    p.evaluate("document.querySelector('#opt2Stage [data-panel=\"timer\"] [data-o2timer=\"1\"]').click();'x'")
    time.sleep(1.2)
    p.evaluate("(function(){var b=document.querySelector('#opt2Stage [data-panel=\"draw\"] [data-o2pick=\"1\"]');if(b)b.click();return 'x';})()")
    time.sleep(0.3)
    drawn = p.evaluate("String((document.querySelector('#o2sPick')||{}).textContent||'')")
    p.evaluate("document.querySelector('#opt2Stage [data-panel=\"vote\"] [data-stg=\"votecreate\"]').click();'x'")
    time.sleep(0.4)
    p.evaluate("(function(){var i=document.querySelector('#o2sCrtTitle');if(i)i.value='草稿标题';return 'x';})()")
    p.evaluate("document.querySelector('#opt2Stage [data-panel=\"ppt\"] .opt2-zbtn').click();'x'")
    time.sleep(0.4)
    before = snap(p)
    draft_dom = p.evaluate("String((document.querySelector('#o2sCrtTitle')||{}).value||'')")
    T("B7 清理前：计时在走/有抽签结果/投票草稿已填/聚焦态",
      bool(drawn) and drawn != "?" and before["bodyFocus"] is True and draft_dom == "草稿标题",
      {"drawn": drawn, "draft": draft_dom})
    p.evaluate("document.querySelector('#o2sClose').click();'x'")
    time.sleep(0.5)
    T("B7 关闭大屏", snap(p)["stageDisplay"] == "none")
    m = snap(p)["mock"]
    T("B7 退出不关闭文件传输会话（不调用 /close）", m["dropClose"] == 0, m)
    T("B7 退出后弹层/岛状态清理（DOM 隐藏）",
      p.evaluate("(function(){var c=document.querySelector('#o2sModal'),r=document.querySelector('#o2sRoster'),mo=document.querySelector('#o2sModModal');return (!c||c.hidden)&&(!r||r.hidden)&&(!mo||mo.hidden);})()"))
    open_stage(p)
    st = snap(p)
    T("B7 重开：计时归零 05:00", p.evaluate("String((document.querySelector('#o2sTimer')||{}).textContent||'')") == "05:00",
      p.evaluate("String((document.querySelector('#o2sTimer')||{}).textContent||'')"))
    T("B7 重开：抽签结果清空", p.evaluate("String((document.querySelector('#o2sPick')||{}).textContent||'')") == "?")
    T("B7 重开：聚焦/灵动岛状态清空", st["bodyFocus"] is False and st["island"]["open"] is False, st["island"])
    _lo7 = json.loads(p.evaluate("localStorage.getItem('zq_stage_layout_v1')||'null'"))
    T("B7 重开：布局偏好保留（顺序与关闭前一致）",
      bool(_lo7) and st["order"] == _lo7.get("order"), (st["order"], _lo7 and _lo7.get("order")))
    T("B7 重开：文件传输会话保留（互联按钮高亮，未重新 /open）",
      p.evaluate("document.querySelector('#o2sDropBtn').classList.contains('on')") and snap(p)["mock"]["dropOpen"] == 1, snap(p)["mock"])
    # 退出→重开→发起投票：DOM 与 STAGE.crt 都必须为空（P1 回归：上次未提交草稿不得复活）
    p.evaluate("document.querySelector('#opt2Stage [data-panel=\"vote\"] [data-stg=\"votecreate\"]').click();'x'")
    p.wait_for("!!document.querySelector('#o2sCrtTitle')", 6)
    time.sleep(0.35)
    dom_draft = p.evaluate(r"""(function(){
      var ti=document.querySelector('#o2sCrtTitle');
      var o=document.querySelectorAll('#o2sCrtOpts [data-crtopt]');
      return {title:ti?String(ti.value||''):null,opts:[].map.call(o,function(x){return String(x.value||'');})};
    })()""")
    crt = p.evaluate("window.__stageCrt?window.__stageCrt():null")
    crt_blank = (isinstance(crt, dict) and str(crt.get("title", "")) == "" and isinstance(crt.get("opts"), list)
                 and len(crt["opts"]) >= 2 and all(str(o.get("text", "")) == "" and str(o.get("img", "")) == "" for o in crt["opts"]))
    T("B7 退出→重开→发起投票：DOM 与 STAGE.crt 均为空",
      dom_draft["title"] == "" and all(x == "" for x in dom_draft["opts"]) and crt_blank,
      {"dom": dom_draft, "crt": crt})
    p.evaluate("document.querySelector('#o2sModal [data-stg=\"votecreateclose\"]').click();'x'")
    time.sleep(0.2)
    T("B7 全程 0 JS 报错", not snap(p)["errs"] and not snap(p)["cerrs"], (snap(p)["errs"], snap(p)["cerrs"]))
    T("B7 无外部网络请求", not [u for u in p.network_urls() if u.startswith("http") and "127.0.0.1" not in u],
      [u for u in p.network_urls() if u.startswith("http") and "127.0.0.1" not in u][:5])
    p.screenshot(os.path.join(SHOTS, "desktop_cleanup_reopen_1366.png"))
    p.close()

    # ================================================================ C 触屏长按
    print("\n== C 触屏 390×844 长按拖拽 ==")
    p = new_page(b, 390, 844, mobile=True, mode="remote", remote=remote_row)
    T("C0 大屏可打开", open_stage(p))
    before = snap(p)["order"]
    # 短按（<180ms）不触发拖拽：先在可视面板上点一下
    p.evaluate("document.querySelector('#opt2Stage [data-panel=\"vote\"]').scrollIntoView({block:'center'});'x'")
    time.sleep(0.35)
    a = p.evaluate("(function(){var e=document.querySelector('#opt2Stage [data-panel=\"vote\"]');var r=e.getBoundingClientRect();return {x:r.left+r.width/2,y:Math.min(window.innerHeight-40,Math.max(60,r.top+r.height/2))};})()")
    p.touch_begin(a["x"], a["y"]); time.sleep(0.08); p.touch_end(a["x"], a["y"]); time.sleep(0.4)
    T("C1 触屏短按不触发拖拽", p.evaluate("!document.querySelector('#opt2Stage .opt2-ghost')") and snap(p)["order"] == before)
    # 长按 180ms 后拖动（计时面板表头 → 顶部，先滚动入视口；避免命中按钮）
    p.evaluate("document.querySelector('#opt2Stage [data-panel=\"timer\"]').scrollIntoView({block:'center'});'x'")
    time.sleep(0.35)
    a = p.evaluate("(function(){var h=document.querySelector('#opt2Stage [data-panel=\"timer\"] [data-panelhd]');var r=h.getBoundingClientRect();return {x:r.left+Math.min(40,r.width*0.3),y:Math.min(window.innerHeight-40,Math.max(60,r.top+r.height/2))};})()")
    p.touch_begin(a["x"], a["y"])
    time.sleep(0.26)
    p.touch_move(a["x"], a["y"] - 60); time.sleep(0.08)
    ghost_cnt = p.evaluate("document.querySelectorAll('#opt2Stage .opt2-ghost').length")
    for i in range(1, 6):
        y = a["y"] + (60 - a["y"]) * i / 5.0
        p.touch_move(a["x"], max(60, y))
        time.sleep(0.06)
    p.touch_end(a["x"], 60)
    time.sleep(0.5)
    after = snap(p)["order"]
    T("C2 触屏长按 180ms 后出现跟手幽灵", ghost_cnt == 1, ghost_cnt)
    T("C2 触屏长按拖动重排", after != before and after[0] == "timer", (before, after))
    T("C2 移动端无横向溢出（390）", snap(p)["overflow"] == 0, snap(p)["overflow"])
    p.screenshot(os.path.join(SHOTS, "mobile_390_longpress_drag.png"))
    T("C3 触屏 0 JS 报错", not snap(p)["errs"], snap(p)["errs"])
    p.close()

    # ================================================================ D stage_prefs 云同步
    print("\n== D stage_prefs 云同步（LWW / 防抖 / 404 降级） ==")
    # D1 云端更新 → 应用云端
    remote_newer = [{"layout": {"v": 1, "order": ["draw", "timer", "vote", "ppt"],
                                "span": {"ppt": 6, "vote": 6, "timer": 6, "draw": 6}, "hidden": [],
                                "lastDeck": "d2", "pptDl": {}, "at": 2000}, "updated_at": iso_ago(10)}]
    local_old = {"v": 1, "order": ["ppt", "vote", "timer", "draw"],
                 "span": {"ppt": 8, "vote": 4, "timer": 6, "draw": 6}, "hidden": [], "at": 1000}
    p = new_page(b, 1366, 768, mobile=False, mode="remote", remote=remote_newer, local=local_old)
    T("D0 大屏可打开", open_stage(p))
    time.sleep(0.8)
    st = snap(p)
    T("D1 LWW：云端更新 → 应用云端顺序", st["order"] == ["draw", "timer", "vote", "ppt"], st["order"])
    T("D1 GET 请求含 select=layout,updated_at&sid=eq.<sid>",
      any("select=layout,updated_at" in u and ("sid=eq." + SID) in u for u in st["mock"]["gets"]), st["mock"]["gets"][:2])
    T("D1 应用云端后不再重复推送", st["mock"]["postCount"] == 0, st["mock"]["postCount"])
    T("D1 云端布局写入本机离线缓存", (st["layout"] or {}).get("order") == ["draw", "timer", "vote", "ppt"], st["layout"] and st["layout"].get("order"))
    p.close()

    # D2 本机更新 → 推本机（LWW）
    local_newer = {"v": 1, "order": ["timer", "draw", "ppt", "vote"],
                   "span": {"ppt": 8, "vote": 4, "timer": 6, "draw": 6}, "hidden": [], "at": int(time.time() * 1000)}
    remote_old = [{"layout": {"v": 1, "order": ["draw", "timer", "vote", "ppt"],
                              "span": {"ppt": 6, "vote": 6, "timer": 6, "draw": 6}, "hidden": [], "at": 1000},
                   "updated_at": iso_ago(7200)}]
    p = new_page(b, 1366, 768, mobile=False, mode="remote", remote=remote_old, local=local_newer)
    T("D2 大屏可打开", open_stage(p))
    time.sleep(0.4)
    T("D2 LWW：本机更新 → 保留本机顺序", snap(p)["order"] == ["timer", "draw", "ppt", "vote"], snap(p)["order"])
    time.sleep(1.2)
    st = snap(p)
    T("D2 本机更新 → 推送本机布局（含 sid/layout）", st["mock"]["postCount"] >= 1 and
      st["mock"]["posts"][-1]["body"].get("sid") == SID and st["mock"]["posts"][-1]["body"]["layout"]["order"] == ["timer", "draw", "ppt", "vote"],
      st["mock"]["posts"][-1:] or None)
    T("D2 推送头 Prefer=resolution=merge-duplicates,return=minimal",
      "resolution=merge-duplicates" in st["mock"]["posts"][-1]["prefer"], st["mock"]["posts"][-1]["prefer"])
    p.close()

    # D3 404 → 静默降级 localStorage
    local404 = {"v": 1, "order": ["draw", "ppt", "timer", "vote"],
                "span": {"ppt": 8, "vote": 4, "timer": 6, "draw": 6}, "hidden": [], "at": int(time.time() * 1000)}
    p = new_page(b, 1366, 768, mobile=False, mode="404", local=local404)
    T("D3 表未就绪 404：大屏仍可打开", open_stage(p))
    time.sleep(1.2)
    st = snap(p)
    T("D3 404 静默降级：应用 localStorage 布局", st["order"] == ["draw", "ppt", "timer", "vote"], st["order"])
    T("D3 404 静默降级：0 JS 报错 / 0 console.error", not st["errs"] and not st["cerrs"], (st["errs"], st["cerrs"]))
    T("D3 404 已发起 GET 且不阻塞", st["mock"]["getCount"] >= 1, st["mock"]["getCount"])
    p.screenshot(os.path.join(SHOTS, "desktop_404_fallback_1366.png"))
    p.close()

    # D4 网络失败 → 静默降级
    p = new_page(b, 1366, 768, mobile=False, mode="error", local=local404)
    T("D4 网络失败：大屏仍可打开", open_stage(p))
    time.sleep(1.0)
    T("D4 网络失败：静默降级 localStorage、0 报错", snap(p)["order"] == ["draw", "ppt", "timer", "vote"] and not snap(p)["errs"])
    p.close()

    # D5 空表 → 首次 seed 推送
    p = new_page(b, 1366, 768, mobile=False, mode="empty", local=local404)
    T("D5 空表：大屏可打开", open_stage(p))
    time.sleep(1.3)
    st = snap(p)
    T("D5 空表：用旧 localStorage 初始化并推一次 seed", st["mock"]["postCount"] >= 1 and st["mock"]["posts"][-1]["body"]["layout"]["order"] == ["draw", "ppt", "timer", "vote"], st["mock"]["postCount"])
    p.close()

    # ================================================================ E 溢出 + 截图
    print("\n== E 360/430/1280 无横向溢出 ==")
    for w, h, mobile in ((360, 780, True), (430, 900, True), (1280, 800, False)):
        p = new_page(b, w, h, mobile=mobile, mode="remote", remote=remote_row)
        ok = open_stage(p)
        st = snap(p)
        T("E-%d 大屏可打开" % w, ok)
        T("E-%d 无横向溢出" % w, st["overflow"] == 0, st["overflow"])
        isl = st["island"]
        if isl["rect"]:
            T("E-%d 灵动岛在视口内" % w, isl["rect"]["l"] >= -1 and isl["rect"]["r"] <= w + 1 and isl["rect"]["t"] >= 0, isl["rect"])
        p.screenshot(os.path.join(SHOTS, "stage_%dx%s.png" % (w, h)))
        T("E-%d 0 JS 报错" % w, not st["errs"], st["errs"])
        p.close()

    # ================================================================ F reduced motion
    print("\n== F prefers-reduced-motion ==")
    p = new_page(b, 1366, 768, mobile=False, mode="remote", remote=remote_row)
    p.set_reduced_motion(True)
    T("F0 大屏可打开", open_stage(p))
    p.evaluate("(function(){var b=document.querySelector('#opt2Stage [data-panel=\"timer\"] [data-o2timer=\"1\"]');if(b)b.click();return 'x';})()")
    time.sleep(1.2)
    p.evaluate("document.querySelector('#o2sIsCore').click();'x'")
    time.sleep(0.4)
    anim = p.evaluate("(function(){var a=document.getAnimations?document.getAnimations():[];var n=0;a.forEach(function(x){try{var t=x.effect&&x.effect.target;if(t&&(t.id==='o2sIsCore'||t.id==='o2sIslandDrop'))n++;}catch(e){}});return n;})()")
    T("F1 reduced-motion：灵动岛形变动画关闭", anim == 0, anim)
    T("F1 reduced-motion：仍可展开（面板可见）", snap(p)["island"]["dropHidden"] is False)
    p.screenshot(os.path.join(SHOTS, "desktop_reduced_motion_1366.png"))
    p.close()

    b.close()
    srv.shutdown()

    print("\n== 截图 ==")
    for f in sorted(os.listdir(SHOTS)):
        print("  " + os.path.join(SHOTS, f))
    print("\n============================================================")
    print("v2_stage_v5_check: PASS %d / FAIL %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：")
        for x in FAILS:
            print("  - " + x)
    print("============================================================")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
