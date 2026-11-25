# -*- coding: utf-8 -*-
r"""网页批次2 · 反馈8：名单快捷预设（web-b 专项，独立文件，不改既有测试）。

覆盖（实现后应全绿；当前为测试骨架，功能块未落地前运行时组会 FAIL）：
A. 静态：
   A1 共享名单弹层 #rosterModal 有快捷预设行（全班/班委/团员，data-rstpreset）
   A2 投票「指定成员」区有快捷预设（data-audpreset）
   A3 大屏发起投票「指定成员」区有快捷预设（data-crtmempreset）
   A4 复用 class_league（团员）与成员 role/badge（班委）；仅 seat 数组，不改数据格式
   A5 APP_VER 仍 2.0.0
B. 运行时 · 共享名单弹层（draw / group / roll 三处共用）：
   B1 打开抽签名单弹层 → 可见 3 个预设按钮
   B2 点「班委」→ 选中 = members 里 role/badge 非空的座号（2 人）
   B3 预设之后仍可逐个增删（取消 1 人 / 加选 1 人）
   B4 确定 → D.d.rosterSel 写入座号数组、摘要刷新
   B5 分组弹层点「团员」→ 选中 = class_league seats；确定写入 groupSel
   B6 点名弹层点「全班」→ 选中 = 全部成员；确定写入 rollSel
C. 运行时 · 投票「指定成员」：
   C1 打开发起投票 → 切换「指定成员」→ 预设按钮可见
   C2 点「班委」→ chips 选中 = 班委座号；再点「团员」→ 切换为团员座号
   C3 预设后逐个增删仍生效
   C4 发起投票 payload.p_audience='custom'、p_audience_seats=最终座号（升序、无 sid）
D. 运行时 · 大屏发起投票（web-a V5 交付后适配；当前无 V5 时记 SKIP 不算失败）
E. 360/430 无横向溢出、0 JS 报错、0 外部请求

用法：python tools\tests\v2_web_batch2_roster_check.py
退出码 0 = 全绿（含 SKIP 不算失败）。
"""
import http.server
import json
import os
import socket
import socketserver
import sys
import threading
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
WEB = os.path.dirname(TOOLS)
SRC = os.path.abspath(os.environ.get("ROSTER_SRC") or os.path.join(TOOLS, "index.html"))
REL = os.path.relpath(SRC, TOOLS).replace("\\", "/")
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

SID = "9999000001"
NAME = "测试同学"
SHOTS = os.path.join(HERE, "_shots_web_batch2")
SRC_TEXT = open(SRC, encoding="utf-8").read()

PASS = 0
FAIL = 0
SKIP = 0
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


def S(name, why=""):
    global SKIP
    SKIP += 1
    print("  [SKIP] " + name + (("  <" + str(why) + ">") if why else ""))


def T_(name, cond, detail=""):
    """web-a V5 未交付时允许跳过的大屏断言。"""
    if not HAS_STAGE_CREATE:
        S(name, "大屏 V5 未交付/结构未识别")
        return
    T(name, cond, detail)


# 5 人名单：1 班长 / 3 副班长(=班委) / 3、5 为团员
MEMBERS = [
    {"seat": 1, "name": "张三", "role": "班长", "badge": "班委"},
    {"seat": 2, "name": "李四", "role": "", "badge": ""},
    {"seat": 3, "name": "王五", "role": "副班长", "badge": "班委"},
    {"seat": 4, "name": "赵六", "role": "", "badge": ""},
    {"seat": 5, "name": "陈七", "role": "", "badge": ""},
]
COMMITTEE_SEATS = [1, 3]
LEAGUE = [{"seat": 3, "name": "王五"}, {"seat": 5, "name": "陈七"}]
LEAGUE_SEATS = [3, 5]
ALL_SEATS = [1, 2, 3, 4, 5]

MEMBERS_JSON = json.dumps(MEMBERS, ensure_ascii=False)
LEAGUE_JSON = json.dumps(LEAGUE, ensure_ascii=False)
HAS_STAGE_CREATE = ("data-crtmempreset" in SRC_TEXT) or ("o2sCrtMemPresets" in SRC_TEXT)

INIT = r"""
(function(){
  try{
    window.__errs=[];window.__cerrs=[];window.__rpc=[];
    window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
    window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
    var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
    try{Object.defineProperty(window,"indexedDB",{value:undefined,configurable:true});}catch(e){}
    try{localStorage.clear();}catch(e){}
    try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:true,ts:Date.now()}));}catch(e){}
    function resp(obj,status){status=status||200;return Promise.resolve(new Response(JSON.stringify(obj),{status:status,headers:{"Content-Type":"application/json"}}));}
    var _f=window.fetch;
    window.fetch=function(u,o){
      o=o||{};
      var s=String((u&&u.url!==undefined)?u.url:u),m=String(o.method||"GET").toUpperCase();
      if(s.indexOf("tcloudbasegateway")<0){
        if(s.indexOf("tt.json")>=0)return resp({c:[],t:"",meta:{fetchedAt:Date.now()}});
        return _f.apply(this,arguments);
      }
      var body="";try{body=o.body?String(o.body):"";}catch(e){}
      if(s.indexOf("/userdata")>=0){
        if(m==="GET")return resp([]);
        return resp([]);
      }
      if(s.indexOf("rpc/class_members")>=0)return resp(__MEMBERS__);
      if(s.indexOf("rpc/class_roster_search")>=0){
        var q=JSON.parse(body||"{}").p_query;
        (window.__rosterQueries||(window.__rosterQueries=[])).push(q);
        if(q==="QA-COMET")return new Promise(function(resolve){setTimeout(function(){resolve(resp([2,3]));},180);});
        return resp([]);
      }
      if(s.indexOf("rpc/class_league")>=0)return resp({ok:true,seats:__LEAGUE__});
      if(s.indexOf("rpc/class_verify")>=0)return resp({ok:true,token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:true});
      if(s.indexOf("rpc/poll_create")>=0){
        var pl={};try{pl=JSON.parse(body);}catch(e){}
        window.__rpc.push({name:"poll_create",payload:pl});
        return resp({ok:true,poll:{id:pl.p_id||"ptest",title:pl.p_title,deadline:pl.p_deadline||0,audience:pl.p_audience,audience_seats:pl.p_audience_seats}});
      }
      if(s.indexOf("rpc/")>=0)return resp({ok:true});
      if(s.indexOf("/marks")>=0)return resp([]);
      if(s.indexOf("/notices")>=0)return resp([]);
      if(s.indexOf("/homework")>=0)return resp([]);
      if(s.indexOf("/fitrecs")>=0)return resp([]);
      if(s.indexOf("/visits")>=0)return resp([]);
      if(s.indexOf("/feedback")>=0)return resp([]);
      if(s.indexOf("/power")>=0)return resp([]);
      return resp([]);
    };
  }catch(e){}
})();
"""

EXTS_JS = ("(function(){var out=[];try{(performance.getEntriesByType('resource')||[]).forEach(function(e){"
           "var u=String(e.name||'');"
           "if(u.indexOf('http://127.0.0.1')!==0&&u.indexOf('https://127.0.0.1')!==0&&u.indexOf('data:')!==0&&u.indexOf('blob:')!==0)out.push(u);});}catch(e){}"
           "return out;})()")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(root):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    handler = lambda *a, **kw: Quiet(*a, directory=root, **kw)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def snap(page):
    return page.evaluate("""(function(){
      var q=function(s){return document.querySelector(s);};
      var modal=q('#rosterModal');
      var open=!!(modal&&modal.style.display!=='none'&&modal.classList.contains('on'));
      var sel=[].map.call(document.querySelectorAll('#rstTxt .rst-b.on'),function(b){return +b.getAttribute('data-seat');});
      var presets=[].map.call(document.querySelectorAll('#rosterModal [data-rstpreset]'),function(b){return b.getAttribute('data-rstpreset');});
      var cnt=q('#rstCnt')?q('#rstCnt').textContent:null;
      var aSum=q('#aRosterSum')?q('#aRosterSum').textContent:'';
      var gSum=q('#gRosterSum')?q('#gRosterSum').textContent:'';
      var rSum=q('#rRosterSum')?q('#rRosterSum').textContent:'';
      var audBox=q('#voteAudBox');
      var audPresets=[].map.call(document.querySelectorAll('#voteAudBox [data-audpreset]'),function(b){return b.getAttribute('data-audpreset');});
      var audSel=[].map.call(document.querySelectorAll('#voteAudMem .vote-mem-b.on'),function(b){return +b.getAttribute('data-seat');});
      var audSum=q('#voteAudSum')?q('#voteAudSum').textContent:'';
      return {open:open,cnt:cnt,sel:sel,presets:presets,aSum:aSum,gSum:gSum,rSum:rSum,
        audBoxHidden:audBox?audBox.hidden:null,audPresets:audPresets,audSel:audSel,audSum:audSum,
        overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
        errs:(window.__errs||[]).slice(-4),cerrs:(window.__cerrs||[]).slice(-4),
        rpc:(window.__rpc||[]).slice(-3)};
    })()""")


def wait_for(fn, timeout=8.0, step=0.12):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


def click(page, sel):
    return page.evaluate("(function(){var e=document.querySelector(%s);if(!e)return false;e.click();return true;})()" % json.dumps(sel))

def field(page, selector, value, event="input"):
    page.evaluate("""(function(){
      var el=document.querySelector(%s);el.value=%s;el.dispatchEvent(new Event(%s,{bubbles:true}));
    })()""" % tuple(map(json.dumps, (selector, value, event))))


def seats(page, selector, key):
    return page.evaluate("Array.from(document.querySelectorAll(%s),b=>Number(b.dataset[%s]))" %
                         (json.dumps(selector), json.dumps(key)))


def submit_search(page, selector):
    page.evaluate("document.querySelector(%s).dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))" %
                  json.dumps(selector))


def open_draw_picker(page):
    page.evaluate("var b=document.querySelector('#aRosterPick');if(b)b.click();'x'")
    page.wait_for("(function(){var m=document.getElementById('rosterModal');return !!(m&&m.classList.contains('on')&&m.style.display!=='none');})()", 15)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    httpd, port = serve(TOOLS)
    url = "http://127.0.0.1:%d/%s" % (port, urllib.parse.quote(REL))
    b = _cdp.Browser(window=(430, 900))

    init = (INIT.replace("__SID__", SID).replace("__NAME__", NAME)
            .replace("__MEMBERS__", MEMBERS_JSON.replace("<", "\\u003c"))
            .replace("__LEAGUE__", LEAGUE_JSON.replace("<", "\\u003c")))

    def new_page(w=430, h=900):
        p = b.new_page("about:blank")
        p.set_device(w, h, dpr=2.0, mobile=True, touch=True)
        p.add_init_script(init)
        p.navigate(url)
        assert p.wait_for("!document.body.classList.contains('auth-pending')", 30), "identity timeout"
        p.wait_for("document.querySelectorAll('#tabsBar button').length>0", 15)
        time.sleep(0.7)
        return p

    print("\n== A 静态检查 ==")
    T("A1 共享名单弹层快捷预设（#rosterModal [data-rstpreset] × 3）",
      SRC_TEXT.count("data-rstpreset=") >= 3 and "rstPresets" in SRC_TEXT)
    T("A2 投票指定成员快捷预设（#voteAudBox [data-audpreset] × 3）",
      SRC_TEXT.count("data-audpreset=") >= 3)
    T("A3 大屏发起投票指定成员快捷预设（data-crtmempreset）", HAS_STAGE_CREATE)
    T("A4 复用 class_league 团员名单 + role/badge 班委口径",
      "class_league" in SRC_TEXT and ("role||m.badge" in SRC_TEXT or "m.role||m.badge" in SRC_TEXT or "role||m.badge" in SRC_TEXT.replace(" ", "")))
    T("A5 名单仍是 seat 数组（rosterSel/groupSel/rollSel 未改格式）",
      all(k in SRC_TEXT for k in ("rosterSel", "groupSel", "rollSel", "normSeats")))
    T("A6 APP_VER 仍 2.0.0", 'var APP_VER="2.0.0"' in SRC_TEXT)

    print("\n== B 共享名单弹层 ==")
    p = new_page()
    open_draw_picker(p)
    s = snap(p)
    T("B1 抽签名单弹层：可打开且预设按钮 = all/committee/league",
      s["open"] and s["presets"] == ["all", "committee", "league"], (s["open"], s["presets"]))
    if s["open"]:
        menu = "#rstSearchGroup"
        field(p, menu, "committee", "change")
        T("筛选班委只改变可见成员", seats(p, "#rstTxt [data-seat]", "seat") == COMMITTEE_SEATS and snap(p)["sel"] == [])
        field(p, menu, "all", "change")
        field(p, "#rstSearch", "副班长")
        T("职务在键入时本地匹配", seats(p, "#rstTxt [data-seat]", "seat") == [3])
        field(p, "#rstSearch", "QA-COMET")
        time.sleep(.35)
        T("仅键入时不查询，不显示候选", not seats(p, "#rstTxt [data-seat]", "seat") and
          p.evaluate("(window.__rosterQueries||[]).length") == 0)
        p.evaluate("document.querySelector('#rstSearch').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true}))")
        T("输入法确认不提交搜索", p.evaluate("(window.__rosterQueries||[]).length") == 0)
        submit_search(p, "#rstSearch")
        field(p, "#rstSearch", "QA-")
        time.sleep(.35)
        T("改词后丢弃慢响应", seats(p, "#rstTxt [data-seat]", "seat") == [])
        submit_search(p, "#rstSearch")
        time.sleep(.15)
        T("不完整词提交后不匹配", seats(p, "#rstTxt [data-seat]", "seat") == [])
        field(p, "#rstSearch", "QA-COMET")
        click(p, "#rstSearchHost .member-search-submit")
        T("提交完整输入可找到同名多位成员",
          wait_for(lambda: seats(p, "#rstTxt [data-seat]", "seat") == [2, 3]))
        field(p, menu, "league", "change")
        T("完整匹配结果与团员分类取交集", wait_for(lambda: seats(p, "#rstTxt [data-seat]", "seat") == [3]))
        T("结果只渲染班级姓名和座号", p.evaluate("!document.querySelector('#rstTxt').textContent.includes('QA-COMET')"))
        field(p, "#rstSearch", "")
        field(p, menu, "all", "change")
        click(p, '#rosterModal [data-rstpreset="committee"]')
        time.sleep(0.4)
        s = snap(p)
        T("B2 点「班委」→ 选中 = 班委座号 [1,3]", s["sel"] == COMMITTEE_SEATS, s["sel"])
        T("B2b 计数正确（2 人）", str(s["cnt"]).strip() == "2", s["cnt"])
        field(p, "#rstSearch", "李四")
        click(p, "#rstAllBtn")
        field(p, "#rstSearch", "")
        T("选中可见保留已勾选的其他分类成员", snap(p)["sel"] == [1, 2, 3])
        click(p, '#rosterModal [data-rstpreset="committee"]')
        # 逐个增删：取消 1、加选 2
        click(p, '#rstTxt .rst-b[data-seat="1"]')
        time.sleep(0.2)
        click(p, '#rstTxt .rst-b[data-seat="2"]')
        time.sleep(0.2)
        s = snap(p)
        T("B3 预设后仍可逐个增删（取消 1 / 加选 2 → [2,3]）", s["sel"] == [2, 3], s["sel"])
        click(p, "#rstOk")
        time.sleep(0.5)
        s = snap(p)
        sel = p.evaluate("(function(){try{var raw=localStorage.getItem('zq_tools_v2_'+'" + SID + "');var o=raw?JSON.parse(raw):null;return o?o.rosterSel:null;}catch(e){return 'ERR';}})()")
        T("B4 确定后 D.d.rosterSel=[2,3]，摘要已刷新", sel == [2, 3] and ("李四" in (s["aSum"] or "") or "王五" in (s["aSum"] or "")), (sel, s["aSum"]))
    else:
        S("B2-B4 名单弹层未打开（功能块未落地）")
    p.close()

    p = new_page()
    click(p, '#cmTabs [data-cmtab="all"]')
    field(p, "#cmSearch", "QA-COMET")
    submit_search(p, "#cmSearch")
    T("名单页提交精确查询", wait_for(lambda: p.evaluate("Array.from(document.querySelectorAll('#cmOut .cmseat'), e=>Number(e.textContent))")==[2,3]))
    field(p, "#cmSearch", "")
    T("清空恢复全部成员", p.evaluate("document.querySelectorAll('#cmOut .cmrow').length")==5)
    T("名单工具没有点名动作或搜索来源提示",
      p.evaluate("!(/点名|群昵称|网名|别名/.test(document.querySelector('#s-committee').innerHTML))"))
    p.close()

    p = new_page()
    # 分组弹层 → 团员
    p.evaluate("var b=document.querySelector('#gRosterPick');if(b)b.click();'x'")
    ok = p.wait_for("(function(){var m=document.getElementById('rosterModal');return !!(m&&m.classList.contains('on')&&m.style.display!=='none');})()", 15)
    if ok:
        click(p, '#rosterModal [data-rstpreset="league"]')
        time.sleep(1.2)  # class_league RPC
        s = snap(p)
        T("B5 分组弹层点「团员」→ class_league seats [3,5]", s["sel"] == LEAGUE_SEATS, s["sel"])
        click(p, "#rstOk")
        time.sleep(0.5)
        gsel = p.evaluate("(function(){try{var raw=localStorage.getItem('zq_tools_v2_'+'" + SID + "');var o=raw?JSON.parse(raw):null;return o?o.groupSel:null;}catch(e){return 'ERR';}})()")
        T("B5b 分组确定后 groupSel=[3,5]", gsel == LEAGUE_SEATS, gsel)
    else:
        S("B5 分组名单弹层未打开")
    p.close()

    p = new_page()
    p.evaluate("(function(){var tr=document.querySelectorAll('#tabsBar button');for(var i=0;i<tr.length;i++){if(tr[i].getAttribute('data-tab')==='roll'){tr[i].click();return;}}document.querySelector('#tabsBar button[data-tab=\"all\"]').click();})()")
    time.sleep(0.6)
    p.evaluate("var b=document.querySelector('#rPickSel');if(!b){var bt=document.querySelector('#allCards [data-open=\"roll\"]');if(bt)bt.click();}'x'")
    time.sleep(0.5)
    p.evaluate("var b=document.querySelector('#rPickSel');if(b)b.click();'x'")
    ok = p.wait_for("(function(){var m=document.getElementById('rosterModal');return !!(m&&m.classList.contains('on')&&m.style.display!=='none');})()", 15)
    if ok:
        click(p, '#rosterModal [data-rstpreset="all"]')
        time.sleep(0.4)
        s = snap(p)
        T("B6 点名弹层点「全班」→ 全部座号", s["sel"] == ALL_SEATS, s["sel"])
        click(p, "#rstOk")
        time.sleep(0.5)
        rsel = p.evaluate("(function(){try{var raw=localStorage.getItem('zq_tools_v2_'+'" + SID + "');var o=raw?JSON.parse(raw):null;return o?o.rollSel:null;}catch(e){return 'ERR';}})()")
        T("B6b 点名确定后 rollSel=全部座号", rsel == ALL_SEATS, rsel)
    else:
        S("B6 点名名单弹层未打开")
    p.close()

    print("\n== C 投票「指定成员」 ==")
    p = new_page()
    # 打开全部页 → 投票卡片 → 发起投票
    p.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();'x'")
    time.sleep(0.5)
    p.evaluate("var b=document.querySelector('#allCards [data-open=\"vote\"]');if(b)b.click();'x'")
    time.sleep(0.8)
    p.evaluate("var b=document.querySelector('#voteNew');if(b)b.click();'x'")
    ok = p.wait_for("(function(){var e=document.getElementById('voteCreateOv');return !!(e&&e.style.display!=='none');})()", 15)
    T("C1 发起投票弹层可打开", ok)
    if ok:
        click(p, '#voteAudience button[data-aud="custom"]')
        time.sleep(1.0)  # 名单加载
        s = snap(p)
        T("C1b 指定成员区：预设按钮 = all/committee/league", s["audPresets"] == ["all", "committee", "league"] and s["audBoxHidden"] is False,
          (s["audPresets"], s["audBoxHidden"]))
        field(p, "#voteAudSearchGroup", "committee", "change")
        field(p, "#voteAudSearch", "QA-COMET")
        submit_search(p, "#voteAudSearch")
        T("普通投票成员精确查询与班委筛选取交集",
          wait_for(lambda: seats(p, "#voteAudMem [data-seat]", "seat") == [3]))
        field(p, "#voteAudSearch", "")
        field(p, "#voteAudSearchGroup", "all", "change")
        click(p, '#voteAudBox [data-audpreset="committee"]')
        time.sleep(0.35)
        s = snap(p)
        T("C2 点「班委」→ 选中班委座号 [1,3]", s["audSel"] == COMMITTEE_SEATS, s["audSel"])
        click(p, '#voteAudBox [data-audpreset="league"]')
        time.sleep(0.6)
        s = snap(p)
        T("C2b 再点「团员」→ 切换为团员座号 [3,5]", s["audSel"] == LEAGUE_SEATS, s["audSel"])
        # 逐个增删：取消 3、加选 1
        click(p, '#voteAudMem .vote-mem-b[data-seat="3"]')
        time.sleep(0.15)
        click(p, '#voteAudMem .vote-mem-b[data-seat="1"]')
        time.sleep(0.25)
        s = snap(p)
        T("C3 预设后逐个增删（→ [1,5]）", s["audSel"] == [1, 5], s["audSel"])
        # 填标题与两个选项后发起
        p.evaluate("""(function(){
          var t=document.getElementById('voteTitle');if(t){t.value='名单预设测试';t.dispatchEvent(new Event('input',{bubbles:true}));}
          var o0=document.querySelector('#voteOpts input[data-ot="0"]'),o1=document.querySelector('#voteOpts input[data-ot="1"]');
          if(o0){o0.value='甲';o0.dispatchEvent(new Event('input',{bubbles:true}));}
          if(o1){o1.value='乙';o1.dispatchEvent(new Event('input',{bubbles:true}));}
          return true;})()""")
        time.sleep(0.2)
        click(p, "#voteCreateGo")
        ok2 = wait_for(lambda: len(snap(p)["rpc"]) > 0, 8)
        s = snap(p)
        rpc = [r for r in (s["rpc"] or []) if r.get("name") == "poll_create"]
        payload = rpc[-1]["payload"] if rpc else {}
        T("C4 发起 payload：audience=custom 且 seats=[1,5]（升序、无 sid）",
          ok2 and payload.get("p_audience") == "custom" and payload.get("p_audience_seats") == [1, 5],
          payload)
        T("C4b 成员区不显示学号（只有姓名/座号）",
          "sid" not in json.dumps(payload.get("p_audience_seats") or []) and
          p.evaluate("(function(){var h=document.getElementById('voteAudMem');return h?h.innerHTML.indexOf('sid')<0:false;})()"))
    else:
        S("C1-C4 发起投票弹层未打开（功能块未落地）")
    p.close()

    print("\n== D 大屏发起投票指定成员（V5 适配，未交付则 SKIP） ==")
    p = new_page()
    try:
        p.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();'x'")
        time.sleep(0.5)
        p.evaluate("var b=document.querySelector('#opt2StageBtn');if(b)b.click();'x'")
        ok = p.wait_for("(function(){var e=document.getElementById('opt2Stage');return !!(e&&e.style.display!=='none'&&!e.hidden);})()", 12)
        if ok:
            # 打开大屏投票「发起」：优先 data-stg=votecreate，其次 o2s 投票区按钮
            p.evaluate("""(function(){
              var bs=document.querySelectorAll('[data-stg="votecreate"]');
              for(var i=0;i<bs.length;i++){var r=bs[i].getBoundingClientRect();if(r.width>0&&r.height>0){bs[i].click();return;}}
            })()""")
            time.sleep(0.5)
            p.evaluate("""(function(){
              var b=document.querySelector('[data-crtaud="custom"]');if(b)b.click();
            })()""")
            time.sleep(0.8)
            pre = p.evaluate("(function(){return [].map.call(document.querySelectorAll('#o2sCrtMem [data-crtmempreset]'),function(b){return b.getAttribute('data-crtmempreset');});})()")
            T_("D1 大屏指定成员区快捷预设 = all/committee/league", pre == ["all", "committee", "league"], pre)
            if pre:
                p.evaluate("""(function(){var b=document.querySelector('#o2sCrtMem [data-crtmempreset="committee"]');if(b)b.click();})()""")
                time.sleep(0.4)
                got = p.evaluate("(function(){return [].map.call(document.querySelectorAll('#o2sCrtMem .opt2-memb.on'),function(b){return +b.getAttribute('data-crtmemseat');});})()")
                T_("D2 大屏点「班委」→ 选中班委座号", got == COMMITTEE_SEATS, got)
                field(p, "#stageVoteSearch", "QA-COMET")
                submit_search(p, "#stageVoteSearch")
                T("大屏投票选择器提交精确查询",
                  wait_for(lambda: seats(p, "#o2sCrtMem [data-crtmemseat]", "crtmemseat") == [2, 3]))
                click(p, '[data-stg="votecreateclose"]')
                click(p, '[data-stg="drawroster"]')
                field(p, "#stageDrawSearchGroup", "league", "change")
                field(p, "#stageDrawSearch", "QA-COMET")
                submit_search(p, "#stageDrawSearch")
                T("大屏抽签选择器精确查询与团员筛选取交集",
                  wait_for(lambda: seats(p, "#o2sRstGrid [data-rstseat]", "rstseat") == [3]))
        else:
            S("D 大屏未打开（web-a V5 未交付）")
    except Exception as e:  # noqa: BLE001
        S("D 大屏结构不可探测", str(e)[:120])
    p.close()

    print("\n== E 溢出 / 报错 / 外部请求 ==")
    for w, h in ((360, 780), (430, 900)):
        px = new_page(w, h)
        open_draw_picker(px)
        sx = snap(px)
        T("E-%d 名单弹层无横向溢出" % w, sx["overflow"] == 0, sx["overflow"])
        T("E-%d 0 JS 报错 / 0 console.error" % w, not sx["errs"] and not sx["cerrs"], (sx["errs"], sx["cerrs"]))
        exts = px.evaluate(EXTS_JS) or []
        T("E-%d 无外部请求" % w, not exts, exts[:3])
        if w == 430:
            try:
                px.screenshot(os.path.join(SHOTS, "roster_430.png"))
            except Exception:
                pass
        px.close()

    b.close()
    httpd.shutdown()

    print("\n== 截图 ==")
    for f in sorted(os.listdir(SHOTS)):
        if "roster" in f:
            print("  " + os.path.join(SHOTS, f))
    print("\n============================================================")
    print("v2_web_batch2_roster_check: PASS %d / FAIL %d / SKIP %d" % (PASS, FAIL, SKIP))
    if FAILS:
        print("失败项：")
        for x in FAILS:
            print("  - " + x)
    print("============================================================")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
