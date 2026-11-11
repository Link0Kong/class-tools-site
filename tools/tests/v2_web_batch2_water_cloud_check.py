# -*- coding: utf-8 -*-
r"""网页批次2 · 反馈6：水量按宿舍云端共享（web-b 专项，独立文件，不改既有测试）。

契约唯一真源：tools/tests/_water_shared_contract.md
- GET   water?select=roomverify,month,reading,persons&roomverify=eq.<rv>&order=month.asc
- POST  water?on_conflict=roomverify,month（Prefer: resolution=merge-duplicates,return=minimal）
- DELETE water?roomverify=eq.<rv>&month=eq.<YYYY-MM>
- GET/POST water_room（房间人数）
- 23A/23B（roomverify 以 4-23A--- / 4-23B--- 开头）固定 4 人、人数选择器禁用
- 去掉「每月免费 N 吨水」措辞（option 只留「4 人间」「6 人间」；「免费额度/定额」→「定额」，公式数值不变）

覆盖：
A 静态：契约请求口径常量/文案/23A 判定/RULES 数值不变/UD v6 water 仍保留
B 运行时（mock 云端，无真实写）：
  B1 进入水量页先渲染本机缓存（离线可用）
  B2 云端合并：云端 month 覆盖本地；本地有云端无 → 补传 POST
  B3 保存：先本地 + POST water（body/Prefer 头正确）
  B4 删除：DELETE 口径正确
  B5 失败 pending：离线保存进 pending，联网后重试并清空
  B6 23A/23B：人数=4 且选择器 disabled；13 号楼可 4/6
  B7 water_room：23A/23B 首次进入 upsert persons=4；切人数写 water_room
C 文案：option 无「免费 N 吨」；#s-water 无「每月免费」；出现「定额」；公式数值不变
D 360/430 无横向溢出、0 JS 报错、0 外部请求

用法：python tools\tests\v2_web_batch2_water_cloud_check.py
退出码 0 = 全绿。
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
SRC = os.path.abspath(os.environ.get("WATER_SRC") or os.path.join(TOOLS, "index.html"))
REL = os.path.relpath(SRC, TOOLS).replace("\\", "/")
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

SID = "3260707001"
NAME = "测试同学"
SHOTS = os.path.join(HERE, "_shots_web_batch2")
SRC_TEXT = open(SRC, encoding="utf-8").read()

RV23A = "4-23A---321"
RV23B = "4-23B---423"
RV13 = "1-13---324"

# 本机缓存：2026-09（云端也有，值不同）+ 2026-08（云端没有 → 需补传）
LOCAL_ROOMS = {RV23B: {"p": 4, "recs": [
    {"m": "2026-08", "r": 120.50, "ts": 1756000000000},
    {"m": "2026-09", "r": 130.00, "ts": 1758600000000},
]}}
# 云端：2026-09 覆盖为 131.00；2026-10 云端独有
CLOUD_ROWS = {RV23B: [
    {"roomverify": RV23B, "month": "2026-09", "reading": 131.00, "persons": 4},
    {"roomverify": RV23B, "month": "2026-10", "reading": 140.25, "persons": 4},
]}
CLOUD_ROOMS = {RV23B: {"roomverify": RV23B, "persons": 4}}

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


INIT = r"""
(function(){
  try{
    window.__errs=[];window.__cerrs=[];window.__wreq=[];window.__wfail=false;window.__wcloud=true;
    window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
    window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
    var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
    try{Object.defineProperty(window,"indexedDB",{value:undefined,configurable:true});}catch(e){}
    window.confirm=function(){return true;};
    try{localStorage.clear();}catch(e){}
    try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
    try{localStorage.setItem("zq_udcache___SID__",JSON.stringify(__UD__));}catch(e){}
    try{localStorage.setItem("zq_tools_v2___SID__",JSON.stringify(__BUCKET__));}catch(e){}
    /* 云端 mock 状态（water / water_room） */
    window.__WC={rows:__CLOUD_ROWS__,rooms:__CLOUD_ROOMS__};
    function J(obj,status){status=status||200;return Promise.resolve(new Response(JSON.stringify(obj),{status:status,headers:{"Content-Type":"application/json"}}));}
    var _f=window.fetch;
    window.fetch=function(u,o){
      o=o||{};
      var s=String((u&&u.url!==undefined)?u.url:u),m=String(o.method||"GET").toUpperCase();
      if(s.indexOf("tcloudbasegateway")<0){
        if(s.indexOf("tt.json")>=0)return J({c:[],t:"",meta:{fetchedAt:Date.now()}});
        return _f.apply(this,arguments);
      }
      var body="";try{body=o.body?String(o.body):"";}catch(e){}
      var hdr={};try{for(var k in (o.headers||{}))hdr[String(k).toLowerCase()]=String(o.headers[k]);}catch(e){}
      function rvOf(url){var m2=url.match(/roomverify=eq\.([^&]+)/);return m2?decodeURIComponent(m2[1]):"";}
      function monOf(url){var m2=url.match(/month=eq\.([^&]+)/);return m2?decodeURIComponent(m2[1]):"";}
      if(s.indexOf("/userdata")>=0){
        if(m==="GET")return J([]);
        return J([]);
      }
      if(s.indexOf("/water_room")>=0){
        var rv0=rvOf(s);
        window.__wreq.push({api:"water_room",method:m,url:s,body:body,headers:hdr,room:rv0});
        if(window.__wfail)return Promise.reject(new Error("offline"));
        if(m==="GET"){var rr=window.__WC.rooms[rv0];return J(rr?[rr]:[]);}
        if(m==="POST"){var b0={};try{b0=JSON.parse(body);}catch(e){}
          if(b0&&b0.roomverify)window.__WC.rooms[b0.roomverify]={roomverify:b0.roomverify,persons:Number(b0.persons)||4};
          return J([],201);}
        return J([]);
      }
      if(s.indexOf("/water")>=0){
        var rv=rvOf(s),mo=monOf(s);
        window.__wreq.push({api:"water",method:m,url:s,body:body,headers:hdr,room:rv,month:mo});
        if(window.__wfail)return Promise.reject(new Error("offline"));
        if(m==="GET"){
          var rows=(window.__WC.rows[rv]||[]).slice();
          if(o&&o.since===undefined){} /* noop */
          return J(rows);
        }
        if(m==="POST"){
          var b={};try{b=JSON.parse(body);}catch(e){}
          if(b&&b.roomverify&&b.month){
            var list=window.__WC.rows[b.roomverify]||(window.__WC.rows[b.roomverify]=[]);
            var replaced=false;
            for(var i=0;i<list.length;i++){if(list[i].month===b.month){list[i]={roomverify:b.roomverify,month:b.month,reading:Number(b.reading),persons:Number(b.persons)||4};replaced=true;}}
            if(!replaced)list.push({roomverify:b.roomverify,month:b.month,reading:Number(b.reading),persons:Number(b.persons)||4});
          }
          return J([],201);
        }
        if(m==="DELETE"){
          var l2=window.__WC.rows[rv]||[];
          window.__WC.rows[rv]=l2.filter(function(x){return x.month!==mo;});
          return J([],200);
        }
        return J([]);
      }
      if(s.indexOf("rpc/class_members")>=0)return J(__MEMBERS__);
      if(s.indexOf("rpc/class_verify")>=0)return J({ok:true,token:"mock-token",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false});
      if(s.indexOf("rpc/")>=0)return J({ok:true,seats:[]});
      if(s.indexOf("/marks")>=0||s.indexOf("/notices")>=0||s.indexOf("/homework")>=0||s.indexOf("/fitrecs")>=0||s.indexOf("/visits")>=0||s.indexOf("/feedback")>=0||s.indexOf("/power")>=0)return J([]);
      return J([]);
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


def ud_blob():
    now = int(time.time() * 1000)
    at = {k: now for k in ("homeTools", "fit", "draw", "group", "roster", "hide", "tt", "prefs", "nick", "power", "water")}
    return {
        "v": 6, "at": at,
        "homeTools": ["draw", "hw", "nt", "tt"], "fit": {}, "draw": {}, "group": {},
        "roster": {"rosterSel": [], "rollSel": [], "rollSt": {}, "rollNames": ""},
        "hide": {"hwHide": {}, "ntHide": {}},
        "tt": {"ttView": "", "ttUseMine": False, "ttLocal": None, "termStart": ""},
        "prefs": {}, "nick": "",
        "power": {"sel": RV23B, "at": now, "low": 30},
        "water": {"rooms": LOCAL_ROOMS}, "homeToolsAt": now,
    }


def bucket():
    return {"water": {"rooms": LOCAL_ROOMS}, "homeTools": ["draw", "hw", "nt", "tt"]}


def open_water(page):
    page.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();'x'")
    time.sleep(0.4)
    page.evaluate("var b=document.querySelector('#allCards [data-open=\"water\"]');if(b)b.click();'x'")
    return page.wait_for("(function(){var e=document.getElementById('s-water');return !!(e&&e.classList.contains('on'));})()", 15)


def snap(page):
    return page.evaluate(SNAP_JS.replace("__SID__", SID))


SNAP_JS = r"""(function(){
      var q=function(s){return document.querySelector(s);};
      var rows=[].map.call(document.querySelectorAll('#wtList .wt-row'),function(r){
        return {m:r.getAttribute('data-wm'),t:r.textContent};});
      var opts=q('#wtPersons')?[].map.call(q('#wtPersons').options,function(o){return o.textContent;}):[];
      var rule=q('#wtRuleBody')?q('#wtRuleBody').textContent:'';
      var sync=q('#wtSync')?{hidden:q('#wtSync').hidden,text:q('#wtSync').textContent,state:q('#wtSync').getAttribute('data-sync')}:null;
      return {sel:q('#wtSel')?q('#wtSel').value:null,persons:q('#wtPersons')?q('#wtPersons').value:null,
        personsDisabled:q('#wtPersons')?!!q('#wtPersons').disabled:null,opts:opts,rows:rows,rule:rule,
        list:q('#wtList')?q('#wtList').textContent:'',cmp:q('#wtCmp')?q('#wtCmp').textContent:'',
        sync:sync,waterText:q('#s-water')?q('#s-water').textContent:'',
        wreq:(window.__wreq||[]).slice(-40),remote:window.__WC||null,
        pending:(function(){try{return JSON.parse(localStorage.getItem('zq_water_pend___SID__')||'[]');}catch(e){return 'ERR';}})(),
        overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
        errs:(window.__errs||[]).slice(-4),cerrs:(window.__cerrs||[]).slice(-4)};
    })()"""


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


def set_select(page, sel, value):
    return page.evaluate("(function(){var e=document.querySelector(%s);if(!e)return false;e.value=%s;e.dispatchEvent(new Event('change',{bubbles:true}));return true;})()"
                         % (json.dumps(sel), json.dumps(value)))


def set_val(page, sel, value):
    return page.evaluate("(function(){var e=document.querySelector(%s);if(!e)return false;e.value=%s;"
                         "e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return true;})()"
                         % (json.dumps(sel), json.dumps(value)))


def save_rec(page, month, reading):
    set_val(page, "#wtMonth", month)
    set_val(page, "#wtReading", reading)
    time.sleep(0.15)
    page.evaluate("var b=document.querySelector('#wtSave');if(b)b.click();'x'")
    time.sleep(0.5)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    httpd, port = serve(TOOLS)
    url = "http://127.0.0.1:%d/%s" % (port, urllib.parse.quote(REL))
    b = _cdp.Browser(window=(430, 900))

    ud_json = json.dumps(ud_blob(), ensure_ascii=False)
    bucket_json = json.dumps(bucket(), ensure_ascii=False)
    init = (INIT.replace("__SID__", SID).replace("__NAME__", NAME)
            .replace("__UD__", ud_json.replace("<", "\\u003c"))
            .replace("__BUCKET__", bucket_json.replace("<", "\\u003c"))
            .replace("__CLOUD_ROWS__", json.dumps(CLOUD_ROWS, ensure_ascii=False))
            .replace("__CLOUD_ROOMS__", json.dumps(CLOUD_ROOMS, ensure_ascii=False))
            .replace("__MEMBERS__", json.dumps([{"seat": 1, "sid": SID, "name": NAME, "role": "", "badge": ""}], ensure_ascii=False)))

    def new_page(w=430, h=900):
        p = b.new_page("about:blank")
        p.set_device(w, h, dpr=2.0, mobile=True, touch=True)
        p.add_init_script(init)
        p.navigate(url)
        assert p.wait_for("!document.body.classList.contains('auth-pending')", 30), "identity timeout"
        p.wait_for("document.querySelectorAll('#tabsBar button').length>0", 15)
        time.sleep(0.8)
        return p

    print("\n== A 静态检查 ==")
    T("A1 GET 口径（select=roomverify,month,reading,persons&order=month.asc）",
      "water?select=roomverify,month,reading,persons" in SRC_TEXT and "order=month.asc" in SRC_TEXT)
    T("A2 POST 幂等口径（on_conflict=roomverify,month + merge-duplicates）",
      "water?on_conflict=roomverify,month" in SRC_TEXT and "merge-duplicates" in SRC_TEXT)
    T("A3 DELETE 口径（water?roomverify=eq. / month=eq.）",
      "water_room" in SRC_TEXT and 'water?roomverify=' in SRC_TEXT and "&month=eq." in SRC_TEXT)
    T("A4 23A/23B 固定四人间判定存在",
      ("4-23A---" in SRC_TEXT and "4-23B---" in SRC_TEXT and ("23A" in SRC_TEXT or "23B" in SRC_TEXT)))
    T("A5 option 文案移除「每月免费 N 吨水」",
      "每月免费" not in SRC_TEXT and "免费 8 吨" not in SRC_TEXT and "免费 12 吨" not in SRC_TEXT)
    T("A6 计费数值不变（水 3.03 / 电 0.58 / 定额 2 吨·5 度）",
      'var RULES={elec:0.58,water:3.03,waterFreePP:2,elecFreePP:5' in SRC_TEXT)
    T("A7 UD v6 water section 仍保留（离线缓存）",
      '"water"' in SRC_TEXT and "UD_KEYS" in SRC_TEXT and "zq_udcache_" in SRC_TEXT)
    T("A8 APP_VER 仍 2.0.0", 'var APP_VER="2.0.0"' in SRC_TEXT)

    print("\n== B 运行时 · 云端合并/保存/删除/离线 ==")
    p = new_page()
    ok = open_water(p)
    T("B0 打开水量页", ok)
    if not ok:
        S("B1-B7 水量页未打开")
    else:
        s = snap(p)
        # B1: 进入即渲染本机缓存（2026-08/09 均出现）
        T("B1 进入先渲染本机缓存（离线可用：08/09 月记录可见）",
          any(r["m"] == "2026-08" for r in s["rows"]) and any(r["m"] == "2026-09" for r in s["rows"]),
          [r["m"] for r in s["rows"]])
        # B2 等云端合并（云端独有 2026-10 出现）+ 补传 POST
        wait_for(lambda: any(r["m"] == "2026-10" for r in snap(p)["rows"]), 10)
        wait_for(lambda: any(r.get("api") == "water" and r.get("method") == "POST" and '"2026-08"' in (r.get("body") or "")
                            for r in (snap(p)["wreq"] or [])), 8)
        s = snap(p)
        T("B2a 云端独有月份合并进来（2026-10）", any(r["m"] == "2026-10" for r in s["rows"]), [r["m"] for r in s["rows"]])
        row09 = [r for r in s["rows"] if r["m"] == "2026-09"]
        T("B2b 同月云端覆盖本地（2026-09 显示 131.00 而非 130.00）",
          bool(row09) and "131.00" in row09[0]["t"], row09)
        gets = [r for r in s["wreq"] if r["api"] == "water" and r["method"] == "GET"]
        T("B2c GET 口径（roomverify=eq.<rv> + select 字段）",
          bool(gets) and ("roomverify=eq." + RV23B in gets[-1]["url"]) and "select=roomverify,month,reading,persons" in gets[-1]["url"],
          gets[-1]["url"] if gets else None)
        posts = [r for r in s["wreq"] if r["api"] == "water" and r["method"] == "POST"]
        up = [r for r in posts if '"2026-08"' in (r["body"] or "")]
        T("B2d 本地有云端无 → 补传 POST 2026-08",
          bool(up), [r["body"] for r in posts])
        if up:
            hd = {k.lower(): v for k, v in (up[-1]["headers"] or {}).items()}
            T("B2e POST 头 Prefer=resolution=merge-duplicates,return=minimal",
              "merge-duplicates" in hd.get("prefer", "") and "return=minimal" in hd.get("prefer", ""), hd.get("prefer"))
        # B3 保存
        save_rec(p, "2026-11", "150.00")
        s = snap(p)
        posts2 = [r for r in s["wreq"] if r["api"] == "water" and r["method"] == "POST" and '"2026-11"' in (r["body"] or "")]
        T("B3a 保存写本地（2026-11 行出现）", any(r["m"] == "2026-11" for r in s["rows"]), [r["m"] for r in s["rows"]])
        T("B3b 保存 POST water（body 带 roomverify/month/reading/persons）",
          bool(posts2) and all(k in posts2[-1]["body"] for k in ("roomverify", "month", "reading", "persons")),
          posts2[-1]["body"] if posts2 else None)
        # B4 删除
        p.evaluate("(function(){var b=document.querySelector('#wtList .wt-row[data-wm=\"2026-10\"] .wt-del');if(b)b.click();})()")
        wait_for(lambda: not any(r["m"] == "2026-10" for r in snap(p)["rows"]), 8)
        s = snap(p)
        dels = [r for r in s["wreq"] if r["api"] == "water" and r["method"] == "DELETE"]
        T("B4 删除行 → DELETE water?roomverify=eq.<rv>&month=eq.2026-10",
          bool(dels) and "roomverify=eq." + RV23B in dels[-1]["url"] and "month=eq.2026-10" in dels[-1]["url"],
          dels[-1]["url"] if dels else None)
        T("B4b 删除后本地行消失且云端状态更新",
          not any(r["m"] == "2026-10" for r in s["rows"]) and
          not any(x["month"] == "2026-10" for x in (s["remote"]["rows"].get(RV23B) or [])),
          s["remote"]["rows"].get(RV23B))
        # B5 失败 pending → 联网重试
        p.evaluate("window.__wfail=true;'x'")
        save_rec(p, "2026-12", "160.00")
        time.sleep(0.8)
        s = snap(p)
        pend = s["pending"] if isinstance(s["pending"], list) else []
        T("B5a 离线保存：本地写入 + pending 标记",
          any(r["m"] == "2026-12" for r in s["rows"]) and len(pend) > 0, pend)
        p.evaluate("window.__wfail=false;window.dispatchEvent(new Event('online'));'x'")
        ok5 = wait_for(lambda: (lambda sx: (not isinstance(sx["pending"], list) or len(sx["pending"]) == 0)
                               and any(x["month"] == "2026-12" for x in (sx["remote"]["rows"].get(RV23B) or [])))(snap(p)), 12)
        s = snap(p)
        T("B5b 联网后自动重试 pending：补传成功且 pending 清空", ok5, (s["pending"], s["remote"]["rows"].get(RV23B)))
        # B6 23A/23B 固定 4 人
        set_select(p, "#wtSel", RV23A)
        time.sleep(1.0)
        s = snap(p)
        T("B6a 23A 房间：人数强制 4", s["persons"] == "4", s["persons"])
        T("B6b 23A 房间：人数选择器 disabled", s["personsDisabled"] is True, s["personsDisabled"])
        wr = [r for r in s["wreq"] if r["api"] == "water_room" and r["method"] == "POST" and '"' + RV23A + '"' in (r["body"] or "")]
        T("B6c 23A 首次进入自动 upsert water_room persons=4", bool(wr), [r["body"] for r in s["wreq"] if r["api"] == "water_room"])
        set_select(p, "#wtSel", RV13)
        time.sleep(0.8)
        s = snap(p)
        T("B6d 13 号楼可 4/6（选择器可用）", s["personsDisabled"] is False, s["personsDisabled"])
        set_select(p, "#wtPersons", "6")
        wait_for(lambda: any(r.get("api") == "water_room" and r.get("method") == "POST" and '"' + RV13 + '"' in (r.get("body") or "")
                            for r in (snap(p)["wreq"] or [])), 8)
        time.sleep(0.3)
        s = snap(p)
        wr13 = [r for r in s["wreq"] if r["api"] == "water_room" and r["method"] == "POST" and '"' + RV13 + '"' in (r["body"] or "")]
        T("B6e 13 号楼切 6 人 → water_room upsert persons=6", s["persons"] == "6" and bool(wr13), (s["persons"], wr13[-1]["body"] if wr13 else None))
        T("B7 顺序：GET/POST/DELETE/water_room 全部走 PostgREST 同源（无外部请求）",
          not (p.evaluate(EXTS_JS) or []))
        T("B7b 0 JS 报错 / 0 console.error", not s["errs"] and not s["cerrs"], (s["errs"], s["cerrs"]))
        try:
            p.screenshot(os.path.join(SHOTS, "water_cloud_430.png"))
        except Exception:
            pass
    p.close()

    print("\n== C 文案 ==")
    p = new_page()
    open_water(p)
    s = snap(p)
    T("C1 #wtPersons 选项只有「4 人间」「6 人间」（无免费吨数）",
      s["opts"] == ["4 人间", "6 人间"], s["opts"])
    water_norm = "".join((s["waterText"] or "").split())
    T("C2 水量页无「每月免费」「免费 N 吨水」字样",
      "每月免费" not in water_norm and "免费8吨" not in water_norm and "免费12吨" not in water_norm,
      water_norm[:160])
    T("C3 水量页出现「定额」措辞", "定额" in water_norm)
    T("C4 公式数值不变：规则卡含 3.03 元/吨 与 每人 2 吨水", "3.03" in (s["rule"] or "") and "2" in (s["rule"] or ""))
    p.close()

    print("\n== D 溢出 / 报错 ==")
    for w, h in ((360, 780), (430, 900)):
        px = new_page(w, h)
        open_water(px)
        sx = snap(px)
        T("D-%d 水量页无横向溢出" % w, sx["overflow"] == 0, sx["overflow"])
        T("D-%d 0 JS 报错" % w, not sx["errs"] and not sx["cerrs"], (sx["errs"], sx["cerrs"]))
        px.close()

    b.close()
    httpd.shutdown()

    print("\n== 截图 ==")
    for f in sorted(os.listdir(SHOTS)):
        if "water" in f:
            print("  " + os.path.join(SHOTS, f))
    print("\n============================================================")
    print("v2_web_batch2_water_cloud_check: PASS %d / FAIL %d / SKIP %d" % (PASS, FAIL, SKIP))
    if FAILS:
        print("失败项：")
        for x in FAILS:
            print("  - " + x)
    print("============================================================")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
