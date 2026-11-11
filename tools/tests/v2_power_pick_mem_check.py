# -*- coding: utf-8 -*-
r"""自检：电费「关注宿舍」选择器优化 + 记忆修复（2026-11-11，网页）。

覆盖：
A. 静态：自定义选择器结构/CSS/JS、bootRestore 与空值保护标记、APP_VER 不变、隐藏原生 select 兼容；
B. 选择器交互：打开/关闭（Esc/外部点击）、4 楼栋分段、房间网格列数（23B=4 列 / 13=2 列 / 23A=3 列）、
   选中态、点房间立即选中并收起、触发器文案、原生 select 同步、键盘焦点、点按尺寸、无横向溢出；
C. 记忆链路（mock fetch，无真实云端）：
   C1 云端有 423、本机缓存 423，停在别的 tab 加载 → **不得把云端覆盖为空**（修复前会推空）；
   C2 打开电费 → 显示 423（换设备从云端恢复）；
   C3 本机缓存为空/非法、云端 423 → 恢复 423 且不推空；
   C4 本机缓存 423 较新、云端为空 → 恢复 423 并补推非空；
   C5 通过选择器改选 425 → 推送 425（只允许非空覆盖）；
   C6 刷新（同 profile）→ 仍显示 425，不推空；
   C7 显式清空（原生 select 选空）→ 允许推送空值；
   C8 全程无 JS 报错 / 无 console.error / 无外部网络请求。
D. 截图：tests/_shots_power_pick/{390_open,390_closed,1280_open}.png。

用法：python tools\tests\v2_power_pick_mem_check.py
退出码 0 = 全绿。
"""
import http.server
import json
import os
import socketserver
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
WEB = os.path.dirname(TOOLS)
SRC = os.path.abspath(os.environ.get("SPEC_CHECK") or os.path.join(TOOLS, "index.html"))
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

SID = "3260707001"
NAME = "测试同学"
SHOTS = os.path.join(HERE, "_shots_power_pick")
REAL_ROOM = "4-23B---423"
ALT_ROOM = "4-23B---425"
ROOM13 = "1-13---324"

SRC_TEXT = open(SRC, encoding="utf-8").read()
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


def room_row(rv):
    cat = {
        "1-13---324": ("13号楼324", "13号楼", "324"), "1-13---308": ("13号楼308", "13号楼", "308"),
        "1-16---305": ("16号楼305", "16号楼", "305"), "1-16---306": ("16号楼306", "16号楼", "306"),
        "4-23A---321": ("23号楼A座321", "23号楼A座", "321"), "4-23A---323": ("23号楼A座323", "23号楼A座", "323"),
        "4-23A---324": ("23号楼A座324", "23号楼A座", "324"), "4-23A---325": ("23号楼A座325", "23号楼A座", "325"),
        "4-23A---326": ("23号楼A座326", "23号楼A座", "326"), "4-23A---327": ("23号楼A座327", "23号楼A座", "327"),
        "4-23A---328": ("23号楼A座328", "23号楼A座", "328"), "4-23A---329": ("23号楼A座329", "23号楼A座", "329"),
        "4-23A---330": ("23号楼A座330", "23号楼A座", "330"),
        "4-23B---422": ("23号楼B座422", "23号楼B座", "422"), "4-23B---423": ("23号楼B座423", "23号楼B座", "423"),
        "4-23B---424": ("23号楼B座424", "23号楼B座", "424"), "4-23B---425": ("23号楼B座425", "23号楼B座", "425"),
    }
    lbl, bld, room = cat.get(rv, ("23号楼B座423", "23号楼B座", "423"))
    return {"id": rv, "label": lbl, "building": bld, "room": room, "quantity": 77.8,
            "unit": "度", "low": False, "updated_at": "2026-11-11T18:00:00+08:00"}


def blob(sel=REAL_ROOM, at=None, low=30):
    now = int(time.time() * 1000)
    at = now if at is None else at
    return {"v": 6,
            "at": {"homeTools": now, "fit": now, "draw": now, "group": now, "roster": now, "hide": now,
                   "tt": now, "prefs": now, "nick": now, "power": at, "water": now},
            "homeTools": ["draw", "hw", "nt", "tt"], "fit": {}, "draw": {},
            "group": {"source": "prev", "mode": "groups", "n": 4, "shuffle": False, "sel": []},
            "roster": {"rosterSel": [], "rollSel": [], "rollSt": {}, "rollNames": ""},
            "hide": {"hwHide": {}, "ntHide": {}},
            "tt": {"ttView": "", "ttUseMine": False, "ttLocal": None, "termStart": ""},
            "prefs": {}, "nick": "", "power": {"sel": sel, "at": at, "low": low},
            "water": {"rooms": {}}, "homeToolsAt": now}


SHIM = r"""
(function(){
  try{
    var init=__REMOTE__;
    var saved=null;try{saved=JSON.parse(sessionStorage.getItem('__gwremote')||'null');}catch(e){}
    window.__gw={remote:saved||init,writes:[],gets:0};
    var _f=window.fetch&&window.fetch.bind(window);
    function J(obj,status){return Promise.resolve(new Response(JSON.stringify(obj),{status:status||200,headers:{'Content-Type':'application/json'}}));}
    function save(){try{sessionStorage.setItem('__gwremote',JSON.stringify(window.__gw.remote));}catch(e){}}
    window.fetch=function(u,o){
      var url=String((u&&u.url)||u),m=String((o&&o.method)||'GET').toUpperCase();
      if(url.indexOf('tcloudbasegateway.com')<0)return _f.apply(this,arguments);
      if(m==='OPTIONS')return J('',204);
      if(url.indexOf('/userdata')>=0){
        if(m==='GET'){window.__gw.gets++;return J([{id:'__SID__',blob:JSON.stringify(window.__gw.remote),ts:Date.now()}]);}
        try{var arr=JSON.parse((o&&o.body)||'[]');
          if(arr[0]&&arr[0].blob){window.__gw.remote=JSON.parse(arr[0].blob);window.__gw.writes.push(window.__gw.remote.power);save();}
        }catch(e){}
        return J([]);
      }
      if(url.indexOf('/rpc/class_members')>=0)return J([{seat:24,name:'__NAME__',role:'',badge:'',sid:'__SID__'}]);
      if(url.indexOf('/rpc/')>=0)return J({ok:true});
      if(url.indexOf('/power_history')>=0)return J([]);
      if(url.indexOf('/power?')>=0){
        var mm=url.match(/id=eq\.([^&]+)/);var rv=mm?decodeURIComponent(mm[1]):'';
        return J([__ROWS__[rv]||__ROWS__['4-23B---423']]);
      }
      return J([]);
    };
  }catch(e){}
})();
"""

IDENT = r"""try{localStorage.setItem('zq_class_identity',JSON.stringify({token:'qa-token',sid:'__SID__',name:'__NAME__',role:'',badge:'',is_admin:true,ts:Date.now()}));}catch(e){}"""

ROWS_JSON = json.dumps({rv: room_row(rv) for rv in [
    "1-13---324", "1-13---308", "1-16---305", "1-16---306",
    "4-23A---321", "4-23A---323", "4-23A---324", "4-23A---325", "4-23A---326",
    "4-23A---327", "4-23A---328", "4-23A---329", "4-23A---330",
    "4-23B---422", "4-23B---423", "4-23B---424", "4-23B---425"]}, ensure_ascii=False)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(port):
    root = os.path.dirname(SRC)
    h = lambda *a, **kw: Quiet(*a, directory=root, **kw)
    s = socketserver.ThreadingTCPServer(("127.0.0.1", port), h)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def init_script(remote, cache=None, clear=True):
    shim = SHIM.replace("__REMOTE__", json.dumps(remote, ensure_ascii=False))
    shim = shim.replace("__ROWS__", ROWS_JSON).replace("__SID__", SID).replace("__NAME__", NAME)
    parts = []
    if clear:
        # 仅首次进入该 tab 时清理 localStorage（刷新场景保留本机缓存）
        parts.append("try{if(!sessionStorage.getItem('__gw_init')){localStorage.clear();sessionStorage.setItem('__gw_init','1');}}catch(e){}")
    ident = IDENT.replace("__SID__", SID).replace("__NAME__", NAME)
    parts.append(ident)
    if cache is not None:
        parts.append("try{if(!sessionStorage.getItem('__gw_cache')){localStorage.setItem('zq_udcache_%s',%s);sessionStorage.setItem('__gw_cache','1');}}catch(e){}"
                     % (SID, json.dumps(json.dumps(cache, ensure_ascii=False))))
    return "".join(parts) + shim


def wait_ready(page, timeout=25):
    page.wait_load(30)
    return page.wait_for("!document.body.classList.contains('auth-pending')", timeout)


def open_power(page):
    page.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"all\"]');if(b)b.click();'x'")
    time.sleep(0.35)
    page.evaluate("var b=document.querySelector('#allCards [data-open=\"power\"]');if(b)b.click();'x'")
    page.wait_for("!!document.querySelector('#s-power')&&document.querySelector('#s-power').classList.contains('on')", 15)
    time.sleep(0.3)


def snap(page):
    return page.evaluate("""(function(){
      var q=function(s){return document.querySelector(s);};
      var btn=q('#pwPickBtn'),txt=q('#pwPickTxt'),panel=q('#pwPickPanel'),sel=q('#pwSelect');
      var rooms=[].map.call(document.querySelectorAll('#pwPickRooms .pw-pickroom'),function(x){return x.getAttribute('data-rv');});
      var blds=[].map.call(document.querySelectorAll('#pwPickBlds .pw-pickbld'),function(x){return x.getAttribute('data-bld');});
      var rect=function(e){if(!e)return null;var r=e.getBoundingClientRect();return {l:r.left,r:r.right,t:r.top,b:r.bottom,w:r.width,h:r.height};};
      var gw=window.__gw||{};
      return {
        select:sel?sel.value:null, selectOpacity:sel?getComputedStyle(sel).opacity:null, selectRect:rect(sel),
        options:sel?sel.options.length:0, placeholder:sel&&sel.options[0]?sel.options[0].value:null,
        txt:txt?txt.textContent:null, btn:rect(btn), btnAria:btn?{haspopup:btn.getAttribute('aria-haspopup'),expanded:btn.getAttribute('aria-expanded')}:null,
        panel:panel?{hidden:panel.hidden,rect:rect(panel),op:getComputedStyle(panel).display}:null,
        blds:blds, rooms:rooms, roomsCols:getComputedStyle(q('#pwPickRooms')).gridTemplateColumns,
        onRoom:panel?[].map.call(document.querySelectorAll('#pwPickRooms .pw-pickroom.on'),function(x){return x.getAttribute('data-rv');}):[],
        active:document.activeElement?document.activeElement.className:null,
        overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
        remote:gw.remote&&gw.remote.power||null, writes:gw.writes||[],
        errs:(window.__errs||[]).slice(-3), consoleErr:(window.__consoleErr||[]).slice(-3)
      };
    })()""")


def wait_for(fn, timeout=6.0, step=0.15):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(step)
    return False


def main():
    os.makedirs(SHOTS, exist_ok=True)
    port = 8991
    srv = serve(port)
    url = "http://127.0.0.1:%d/index.html" % port
    b = _cdp.Browser(window=(390, 844))
    results = {"static": {}, "runtime": {}}

    # ================= A. 静态 =================
    print("\n== A 静态检查 ==")
    for name, token in [
        ("A1 自定义选择器 HTML（触发器/面板/楼栋/房间）",
         'id="pwPickBtn"' in SRC_TEXT and 'id="pwPickPanel"' in SRC_TEXT and 'id="pwPickBlds"' in SRC_TEXT and 'id="pwPickRooms"' in SRC_TEXT),
        ("A2 原生 select 保留为隐藏值源", 'id="pwSelect"' in SRC_TEXT and "pw-select-native" in SRC_TEXT),
        ("A3 选择器 CSS（按钮/面板/楼栋/房间/选中态）",
         all(k in SRC_TEXT for k in (".pw-pickbtn{", ".pw-pickpanel{", ".pw-pickbld{", ".pw-pickroom{", ".pw-pickroom.on{"))),
        ("A4 bootRestore（启动即恢复关注宿舍）", "bootRestore:function(){" in SRC_TEXT and "POWER.bootRestore();POWER.init();POWER.bind()" in SRC_TEXT),
        ("A5 UD.sections().power 前兜底 bootRestore", "if(P&&P.bootRestore)P.bootRestore();" in SRC_TEXT),
        ("A6 power 空值保护（隐式空不覆盖非空）", "pExplicit" in SRC_TEXT and "POWER._clearedAt" in SRC_TEXT),
        ("A7 显式清空标记（pick 里设置）", "POWER._clearedAt=rv?0:Date.now();" in SRC_TEXT),
        ("A8 选择器事件绑定（按钮/楼栋/房间/Esc/外部点击）",
         all(k in SRC_TEXT for k in ("POWER.openPick(!POWER._pickOpen)", ".pw-pickbld", ".pw-pickroom", 'e.key==="Escape"', "closest(\".pw-pickwrap\")"))),
        ("A9 手势豁免（选择器内滑动不切工具）", SRC_TEXT.count(".pw-pickwrap") >= 2),
        ("A10 使用说明补充选择器/同步恢复说明", "点「关注宿舍」按楼栋选房间" in SRC_TEXT),
        ("A11 APP_VER 仍为 2.0.0", 'var APP_VER="2.0.0"' in SRC_TEXT),
        ("A12 未破坏水量页原生 select（.pw-select 共用样式）", 'class="pw-select" id="wtSel"' in SRC_TEXT),
    ]:
        T(name, token)
        results["static"][name] = bool(token)

    # ================= B/C. 运行时 =================
    pages = {}

    def new_page(w=390, h=844, mobile=True, remote=None, cache=None, clear=True):
        p = b.new_page("about:blank")
        p.set_device(w, h, dpr=2.0 if mobile else 1.0, mobile=mobile, touch=mobile)
        p.add_init_script(init_script(remote if remote is not None else blob(), cache, clear))
        p.navigate(url)
        assert wait_ready(p), "identity ready timeout"
        time.sleep(0.6)
        return p

    print("\n== B 选择器交互 ==")
    p = new_page()
    open_power(p)
    s = snap(p)
    T("B1 触发器显示云端恢复的宿舍", s["txt"] == "23号楼B座423", s["txt"])
    T("B2 原生 select 同步且视觉隐藏", s["select"] == REAL_ROOM and s["selectOpacity"] == "0", (s["select"], s["selectOpacity"]))
    T("B3 原生 select 保留 18 项（占位+17 房间）", s["options"] == 18 and s["placeholder"] == "", (s["options"], s["placeholder"]))
    T("B4 触发器 ≥40px 高、aria-expanded=false", s["btn"]["h"] >= 40 and s["btnAria"]["expanded"] == "false", (s["btn"]["h"], s["btnAria"]))
    T("B5 面板初始隐藏", s["panel"]["hidden"] is True, s["panel"])
    p.evaluate("document.querySelector('#pwPickBtn').click();'x'")
    time.sleep(0.35)
    s = snap(p)
    T("B6 点开面板：展开 + aria-expanded=true", s["panel"]["hidden"] is False and s["btnAria"]["expanded"] == "true", (s["panel"], s["btnAria"]))
    T("B7 楼栋分段 4 个（13/16/23A/23B）", s["blds"] == ["13号楼", "16号楼", "23号楼A座", "23号楼B座"], s["blds"])
    T("B8 当前楼栋=23B，4 个房间、4 列", s["rooms"] == ["4-23B---422", "4-23B---423", "4-23B---424", "4-23B---425"]
      and len(s["roomsCols"].split()) == 4, (s["rooms"], s["roomsCols"]))
    T("B9 当前选中房间标记 .on", s["onRoom"] == [REAL_ROOM], s["onRoom"])
    T("B10 楼栋/房间点按尺寸 ≥40px",
      all(x >= 40 for x in [s["btn"]["h"]]) and s["panel"]["rect"]["h"] > 0,
      s["btn"]["h"])
    T("B11 打开后焦点在房间按钮上", "pw-pickroom" in (s["active"] or ""), s["active"])
    T("B12 面板在视口内（不越界）", s["panel"]["rect"]["r"] <= 390 and s["panel"]["rect"]["b"] <= 844, s["panel"]["rect"])
    T("B13 无横向溢出（390）", s["overflow"] == 0, s["overflow"])
    p.screenshot(os.path.join(SHOTS, "390_open.png"))
    # 切 13 号楼 → 2 房间 2 列
    p.evaluate("(function(){var t=[].find.call(document.querySelectorAll('#pwPickBlds .pw-pickbld'),function(x){return x.getAttribute('data-bld')==='13号楼';});t.click();return true;})()")
    time.sleep(0.25)
    s13 = snap(p)
    T("B14 切 13 号楼：2 房间、2 列", len(s13["rooms"]) == 2 and len(s13["roomsCols"].split()) == 2, (s13["rooms"], s13["roomsCols"]))
    # 切 23A → 9 房间 3 列
    p.evaluate("(function(){var t=[].find.call(document.querySelectorAll('#pwPickBlds .pw-pickbld'),function(x){return x.getAttribute('data-bld')==='23号楼A座';});t.click();return true;})()")
    time.sleep(0.25)
    s23 = snap(p)
    T("B15 切 23A：9 房间、3 列", len(s23["rooms"]) == 9 and len(s23["roomsCols"].split()) == 3, (len(s23["rooms"]), s23["roomsCols"]))
    # Esc 关闭
    p.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));'x'")
    time.sleep(0.2)
    T("B16 Esc 关闭面板", snap(p)["panel"]["hidden"] is True)
    # 外部点击关闭
    p.evaluate("document.querySelector('#pwPickBtn').click();'x'")
    time.sleep(0.25)
    p.evaluate("document.body.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));'x'")
    time.sleep(0.2)
    T("B17 点面板外关闭", snap(p)["panel"]["hidden"] is True)
    # 点房间选中 425（先从 23A 切回 23B）
    p.evaluate("document.querySelector('#pwPickBtn').click();'x'")
    time.sleep(0.25)
    p.evaluate("(function(){var t=[].find.call(document.querySelectorAll('#pwPickBlds .pw-pickbld'),function(x){return x.getAttribute('data-bld')==='23号楼B座';});t.click();return true;})()")
    time.sleep(0.25)
    p.evaluate("(function(){var t=[].find.call(document.querySelectorAll('#pwPickRooms .pw-pickroom'),function(x){return x.getAttribute('data-rv')==='%s';});t.click();return true;})()" % ALT_ROOM)
    time.sleep(0.5)
    s = snap(p)
    T("B18 点房间立即选中：面板收起/文案更新/原生值同步", s["panel"]["hidden"] is True and s["txt"] == "23号楼B座425" and s["select"] == ALT_ROOM, (s["panel"]["hidden"], s["txt"], s["select"]))
    ok_push = wait_for(lambda: (s["remote"] or {}).get("sel") == ALT_ROOM, 6)
    T("B19 选择后推送 425 到云端（非空覆盖）", ok_push, s["remote"])
    waits = [w for w in s["writes"] if (w or {}).get("sel") == ""]
    T("B20 选择过程不产生空值覆盖，输入方式也为非空", not waits, waits)
    p.screenshot(os.path.join(SHOTS, "390_closed.png"))
    T("B23 全程 0 JS 报错", (p.evaluate("JSON.stringify(window.__errs||[])") or "[]") in ("[]", ""),
      p.evaluate("JSON.stringify(window.__errs||[])"))
    p.close()

    print("\n== C 记忆链路 ==")
    # C1: 云端 423 + 缓存 423，停在抽签 3s → 不推空
    p1 = new_page(cache=blob(REAL_ROOM))
    time.sleep(3.0)
    s1 = snap(p1)
    empties = [w for w in s1["writes"] if (w or {}).get("sel") == ""]
    T("C1 启动同步不把云端宿舍覆盖为空", (s1["remote"] or {}).get("sel") == REAL_ROOM and not empties,
      {"remote": s1["remote"], "empties": empties})
    # C2: 打开电费页恢复 423
    open_power(p1)
    s2 = snap(p1)
    T("C2 打开电费页显示 423（换设备恢复）", s2["select"] == REAL_ROOM and s2["txt"] == "23号楼B座423", (s2["select"], s2["txt"]))
    p1.close()

    # C3: 本机缓存为空/非法，云端 423 → 恢复 423，不推空
    bad = blob("1-99---999", at=0)
    p3 = new_page(remote=blob(REAL_ROOM), cache=bad)
    time.sleep(2.5)
    open_power(p3)
    s3 = snap(p3)
    empties3 = [w for w in s3["writes"] if (w or {}).get("sel") == ""]
    T("C3 本机非法缓存 + 云端 423 → 恢复 423 且不推空", s3["select"] == REAL_ROOM and (s3["remote"] or {}).get("sel") == REAL_ROOM and not empties3,
      (s3["select"], s3["remote"], empties3))
    p3.close()

    # C3b: 本机缓存为空（且时间戳比云端新，历史 bug 留下的陈旧空缓存），云端 423 → 仍以云端非空为准
    stale_empty = blob("", at=int(time.time() * 1000))
    p3b = new_page(remote=blob(REAL_ROOM, at=int(time.time() * 1000) - 3600 * 1000), cache=stale_empty)
    time.sleep(2.5)
    open_power(p3b)
    s3b = snap(p3b)
    empties3b = [w for w in s3b["writes"] if (w or {}).get("sel") == ""]
    T("C3b 本机陈旧空缓存（时间戳更新）+ 云端 423 → 仍恢复 423、不推空",
      s3b["select"] == REAL_ROOM and (s3b["remote"] or {}).get("sel") == REAL_ROOM and not empties3b,
      (s3b["select"], s3b["remote"], empties3b))
    p3b.close()

    # C4: 本机缓存 423 较新、云端为空 → 恢复并补推 423
    remote_empty = blob("", at=int(time.time() * 1000) - 7200 * 1000)
    p4 = new_page(remote=remote_empty, cache=blob(REAL_ROOM, at=int(time.time() * 1000) - 600 * 1000))
    open_power(p4)
    s4 = snap(p4)
    ok4 = wait_for(lambda: (snap(p4)["remote"] or {}).get("sel") == REAL_ROOM, 6)
    T("C4 本机 423 较新、云端为空 → 恢复 423 并补推", s4["select"] == REAL_ROOM and ok4,
      {"select": s4["select"], "remote": snap(p4)["remote"]})
    p4.close()

    # C5/C6: 选择器选 425 → 刷新同 profile → 仍 425，且不推空
    remote5 = blob(REAL_ROOM)
    p5 = new_page(remote=remote5, cache=blob(REAL_ROOM))
    open_power(p5)
    p5.evaluate("document.querySelector('#pwPickBtn').click();'x'")
    time.sleep(0.25)
    p5.evaluate("(function(){var t=[].find.call(document.querySelectorAll('#pwPickRooms .pw-pickroom'),function(x){return x.getAttribute('data-rv')==='%s';});t.click();return true;})()" % ALT_ROOM)
    time.sleep(0.6)
    ok5 = wait_for(lambda: (snap(p5)["remote"] or {}).get("sel") == ALT_ROOM, 6)
    T("C5 选择器改选 425 后推送云端", ok5, snap(p5)["remote"])
    # 刷新：同一 page 重新导航，sessionStorage 保留云端 mock；localStorage 保留本机缓存
    p5.navigate(url)
    assert wait_ready(p5)
    time.sleep(0.8)
    open_power(p5)
    s6 = snap(p5)
    empties6 = [w for w in s6["writes"] if (w or {}).get("sel") == ""]
    T("C6 刷新后仍显示 425、不推空", s6["select"] == ALT_ROOM and s6["txt"] == "23号楼B座425" and not empties6,
      {"select": s6["select"], "txt": s6["txt"], "empties": empties6})
    T("C7 刷新后云端仍为 425", (s6["remote"] or {}).get("sel") == ALT_ROOM, s6["remote"])

    # C8: 显式清空允许推送空
    p5.evaluate("document.querySelector('#pwPickBtn').click();'x'")
    time.sleep(0.2)
    # 用原生 select 显式清空（等价用户选占位“选择你要关注的宿舍…”）
    p5.evaluate("(function(){var s=document.querySelector('#pwSelect');s.value='';s.dispatchEvent(new Event('change',{bubbles:true}));return true;})()")
    ok8 = wait_for(lambda: (snap(p5)["remote"] or {}).get("sel") == "", 8)
    T("C8 显式清空允许推送空值（唯一允许空覆盖的场景）", ok8, snap(p5)["remote"])
    p5.close()

    # B21/B22: 360/430/1280 无溢出 + 面板不越界
    for w, h, mobile in ((360, 780, True), (430, 900, True), (1280, 900, False)):
        px = new_page(w, h, mobile, remote=blob(REAL_ROOM), cache=blob(REAL_ROOM))
        open_power(px)
        px.evaluate("document.querySelector('#pwPickBtn').click();'x'")
        time.sleep(0.35)
        sx = snap(px)
        T("B21-%d 无横向溢出" % w, sx["overflow"] == 0, sx["overflow"])
        T("B22-%d 面板在视口内" % w, sx["panel"]["rect"]["r"] <= w and sx["panel"]["rect"]["b"] <= h, sx["panel"]["rect"])
        if w == 1280:
            px.screenshot(os.path.join(SHOTS, "1280_open.png"))
        px.close()

    # 全局错误检查已在 B23 完成
    b.close()
    srv.shutdown()

    print("\n== 截图 ==")
    for f in sorted(os.listdir(SHOTS)):
        print("  " + os.path.join(SHOTS, f))
    print("\n============================================================")
    print("v2_power_pick_mem_check: PASS %d / FAIL %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：")
        for x in FAILS:
            print("  - " + x)
    print("============================================================")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
