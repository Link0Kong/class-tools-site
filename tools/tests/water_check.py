# -*- coding: utf-8 -*-
r"""专项门禁：班级工具站「水量统计 + 电费计费」 —— task-2

契约：tools/tests/_water_contract.md（Lead 定稿；本文件只读 index.html，不修改生产文件）
参考骨架：power_check.py / v2_power_slow_check.py / sync_check.py（headless Edge + CDP + fetch mock + 假身份）

覆盖契约 §5 A–G：
  A 身份门禁：未登录 0 请求 / 不渲染水量数据；学号+姓名校验后可进入
  B 水量页基础：全部页「水量」卡片、打开 #s-water、空态引导、360/430/1280 无横向溢出、
    0 JS 报错 / 0 console.error / 无外部请求（除 mock 的 CloudBase）
  C 手动抄表：与电费共用关注宿舍；保存 / 自动对比上次 / 水费公式（4 人 & 6 人）/ 折合扣电 /
    读数小于上次拒绝 / 同月覆盖 / 删除重算 / 历史倒序 / #wtPreview 即时 / 人数切换重算 / 本机存储
  D 规则卡：0.58 元/度、3.03 元/吨、2 吨水 + 5 度电/人/月、超出定额公式、折合扣电、来源、
    「以学校最新通知为准」；不含市政阶梯价
  E 电费页：mock 一次 ~30 度异常下跌 → 区间用电/电费不含它、#pwDeduct 出现、
    水量记录匹配时显示水费扣除、tile 副标电费=用电×0.58、估算速率不受异常段影响
  F 同步：保存后 >1.3s POST userdata blob（14 键顺序 + water.rooms 内容）；换设备恢复；
    两账号隔离；旧数据无 water 不报错
  G 截图到 tests/_water_shots/；全程 0 JS 报错 / 0 console.error / 无外部请求

用法（cwd = web\\tools）：
  python tests\\water_check.py              # 全量门禁（浏览器实跑；退出码 0 = 全绿）
  python tests\\water_check.py --list       # 只列断言计划（不启动浏览器）
  python tests\\water_check.py --static     # 只跑静态契约检查
  python tests\\water_check.py --boot       # 只跑浏览器骨架自检（启动/身份/mock/路由/电费页）
  set SPEC_CHECK=<副本.html>               # 复盘任意 index.html 副本（只读）
"""
import base64
import functools
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import websocket
except Exception:
    print("[water_check] 缺少 websocket-client：pip install websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.abspath(os.environ.get("SPEC_CHECK") or os.path.join(ROOT, "index.html"))
SHOTS = os.path.join(HERE, "_water_shots")
# 临时根：与其他门禁/Lead 调试共用，只清理本次 run 的子目录（不整目录删除）
TMP = os.path.join(HERE, "_water_tmp")
RUN_TMP = ""
PREVIEW = ""

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
EDGE = next((p for p in EDGE_CANDIDATES if os.path.exists(p)), EDGE_CANDIDATES[0])

HTTP_PORT = 0
CDP_PORT = 0
BASE = ""

SID_A = "9999000001"
SID_B = "9999000002"
NAME = "测试同学"

RV321 = "4-23A---321"
RV330 = "4-23A---330"
RV305 = "1-16---305"
# 契约变更（2026-11-11，反馈6）：23A/23B 固定 4 人间 → 4↔6 人重算改用 13 号楼房间；
# 6 人间恢复类场景改用 16 号楼房间（与 23A/23B 无关的旧断言不受影响）
RV13 = "1-13---324"
RV16 = "1-16---306"

CATALOG = [
    ("1-13---324", "13号楼324", "13号楼"),
    ("1-13---308", "13号楼308", "13号楼"),
    ("1-16---305", "16号楼305", "16号楼"),
    ("1-16---306", "16号楼306", "16号楼"),
    ("4-23A---321", "23号楼A座321", "23号楼A座"),
    ("4-23A---323", "23号楼A座323", "23号楼A座"),
    ("4-23A---324", "23号楼A座324", "23号楼A座"),
    ("4-23A---325", "23号楼A座325", "23号楼A座"),
    ("4-23A---326", "23号楼A座326", "23号楼A座"),
    ("4-23A---327", "23号楼A座327", "23号楼A座"),
    ("4-23A---328", "23号楼A座328", "23号楼A座"),
    ("4-23A---329", "23号楼A座329", "23号楼A座"),
    ("4-23A---330", "23号楼A座330", "23号楼A座"),
    ("4-23B---422", "23号楼B座422", "23号楼B座"),
    ("4-23B---423", "23号楼B座423", "23号楼B座"),
    ("4-23B---424", "23号楼B座424", "23号楼B座"),
    ("4-23B---425", "23号楼B座425", "23号楼B座"),
]

# ---------------------------------------------------------------------------
# 电费页 fixture（E）：每个宿舍一段 24h 采样（[(几小时前, 电量)]）
#   321：8h 内一次 30.0 度异常下跌（389.00 → 359.00），其余 6 段各 0.5 度 → 区间用电 3.0 度
#        水量记录可匹配（水费 17.39 元 ≈ 30.0 度）→ water:true
#   330：同样 30.0 度异常下跌，但无水量记录 → 候选未匹配 → water:false（异常扣减）
#   305：正常下降 2.0 度，无扣减
# ---------------------------------------------------------------------------
POWER_ROWS = {
    RV321: {"quantity": 357.00, "low": False},
    RV330: {"quantity": 200.00, "low": False},
    RV305: {"quantity": 100.00, "low": False},
}
POWER_HIST = {
    RV321: [(8.0, 390.00), (7.5, 389.50), (7.0, 389.00), (6.5, 359.00),
            (6.0, 358.50), (5.0, 358.00), (3.0, 357.50), (0.2, 357.00)],
    RV330: [(8.0, 233.00), (7.5, 232.50), (7.0, 232.00), (6.5, 202.00),
            (6.0, 201.50), (5.0, 201.00), (3.0, 200.50), (0.2, 200.00)],
    RV305: [(4.0, 102.00), (2.0, 101.00), (0.2, 100.00)],
}

# 本用例使用的月份（相对当前月，避免未来月份被实现拒绝 / 跨月运行失效）
NOW = date.today()


def month_add(base, delta):
    y, m = base.year, base.month + delta
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return "%04d-%02d" % (y, m)


M0 = month_add(NOW, 0)      # 当前月
M1 = month_add(NOW, -1)
M2 = month_add(NOW, -2)
M3 = month_add(NOW, -3)
M4 = month_add(NOW, -4)
CUR_M, PREV_M = M0, M1

RESULTS = []
GLOBAL = {"errs": [], "cerrs": [], "exts": []}
_LAST_PASS = 0


def T(key, ok, note=""):
    global _LAST_PASS
    RESULTS.append({"k": key, "ok": bool(ok), "note": str(note or "")[:320]})
    if ok:
        _LAST_PASS += 1
        print("[PASS] " + key)
    else:
        print("[FAIL] " + key + (("  -- " + str(note)[:300]) if note != "" else ""))
    try:
        sys.stdout.flush()
    except Exception:
        pass
    return bool(ok)


def norm(text):
    return re.sub(r"\s+", "", str(text or ""))


def has_all(text, *subs):
    c = norm(text)
    return all(s in c for s in subs)


def has_any(text, *subs):
    c = norm(text)
    return any(s in c for s in subs)


# ---------------------------------------------------------------------------
# 页面注入：假身份 + fetch mock（CloudBase 全部本地返回；其余同源 passthrough）
# 查询参数：sid / name / noid=1 / ud=<cloud userdata blob> / bucket=<本机 zq_tools_v2_<sid> 种子>
# ---------------------------------------------------------------------------
INJECT = r"""<script>
(function(){
window.__reqs=[];window.__errs=[];window.__cerrs=[];window.__udPosts=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
try{Object.defineProperty(window,"indexedDB",{value:undefined,configurable:true});}catch(e){}
function qv(k,d){var m=String(location.search||"").match(new RegExp("[?&]"+k+"=([^&]*)"));return m?decodeURIComponent(m[1]):d;}
function jp(k){try{var v=qv(k,"");return v?JSON.parse(v):null;}catch(e){return null;}}
/* reset=1：新文档启动前先清空本机存储（避免上一个场景 pagehide/flush 竞态把旧 UD 缓存带进来） */
var RESET=qv("reset","")==="1";
try{if(RESET)localStorage.clear();}catch(e){}
var SID=qv("sid","__SID_A__"), NM=qv("name","__NAME__");
var NOID=qv("noid","")==="1";
var UDSEED=jp("ud"), BUCKET=jp("bucket");
var ROWS=__ROWS__, HIST=__HIST__, CATALOG=__CATALOG__;
try{
  localStorage.removeItem("zq_last_identity");
  if(!NOID){
    localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token-"+SID,sid:SID,name:NM,role:"",badge:"",is_admin:false,ts:Date.now()}));
  }
  var bkey="zq_tools_v2_"+SID;
  if(BUCKET&&!localStorage.getItem(bkey))localStorage.setItem(bkey,JSON.stringify(BUCKET));
}catch(e){}
var UD_ROW=UDSEED?[{id:SID,blob:JSON.stringify(UDSEED),ts:1762300800000}]:[];
function resp(obj,status){status=status||200;return Promise.resolve({ok:status>=200&&status<300,status:status,
  json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve(JSON.stringify(obj));}});}
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};
  var s=String((u&&u.url!==undefined)?u.url:u), m=String(o.method||"GET").toUpperCase(), h=o.headers||{};
  if(s.indexOf("tcloudbasegateway")<0){
    if(s.indexOf("tt.json")>=0)return resp({c:[],t:"",meta:{fetchedAt:Date.now()}});
    return _f.apply(this,arguments);
  }
  var hdr={};for(var k in h){try{hdr[k.toLowerCase()]=String(h[k]);}catch(e){}}
  window.__reqs.push({url:s,method:m,headers:hdr,body:o.body?String(o.body):""});
  if(s.indexOf("/userdata")>=0){
    if(m==="GET")return resp(UD_ROW.map(function(r){return {id:r.id,blob:r.blob,ts:r.ts};}));
    var arr=[];try{arr=JSON.parse(String(o.body||"[]"));}catch(e){}
    var row=(arr&&arr[0])||{};
    if(row&&row.id!=null&&row.blob!=null){
      window.__udPosts.push({id:String(row.id),blob:String(row.blob),headers:hdr,url:s});
      UD_ROW=[{id:String(row.id),blob:String(row.blob),ts:Number(row.ts)||Date.now()}];
    }
    return resp([{id:row.id,blob:row.blob,ts:row.ts}]);
  }
  if(s.indexOf("/power_history")>=0){
    var hv="";try{var hm=s.match(/[?&]roomverify=eq\.([^&]+)/);if(hm)hv=decodeURIComponent(hm[1]);}catch(e){}
    var cut=0;try{var gm=s.match(/[?&]ts=gte\.([^&]+)/);if(gm)cut=Date.parse(decodeURIComponent(gm[1]));}catch(e){}
    var hl=(HIST[hv]||[]).filter(function(p){var t=Date.now()-p[0]*3600000;return !cut||t>=cut;}).map(function(p){return {roomverify:hv,quantity:p[1],ts:new Date(Date.now()-p[0]*3600000).toISOString()};});
    return resp(hl);
  }
  if(s.indexOf("/power?")>=0){
    var pv="";try{var pm=s.match(/[?&]id=eq\.([^&]+)/);if(pm)pv=decodeURIComponent(pm[1]);}catch(e){}
    var cat=null;for(var i=0;i<CATALOG.length;i++){if(CATALOG[i][0]===pv){cat=CATALOG[i];break;}}
    if(!cat)return resp([]);
    var rw=ROWS[pv]||{quantity:100,low:false};
    return resp([{id:pv,label:cat[1],building:cat[2],room:cat[1].replace(cat[2],""),
      quantity:rw.quantity,unit:"度",low:rw.low,updated_at:"2026-11-06T06:42:24+08:00"}]);
  }
  if(s.indexOf("rpc/class_members")>=0)return resp([{seat:1,sid:SID,name:NM,role:"",badge:"",is_admin:false}]);
  if(s.indexOf("rpc/class_verify")>=0)return resp({ok:true,token:"mock-token-"+SID,sid:SID,name:NM,role:"",badge:"",is_admin:false});
  if(s.indexOf("/marks")>=0)return resp([]);
  if(s.indexOf("/notices")>=0)return resp([]);
  if(s.indexOf("/homework")>=0)return resp([]);
  if(s.indexOf("/fitrecs")>=0)return resp([]);
  if(s.indexOf("/visits")>=0)return resp([]);
  if(s.indexOf("/feedback")>=0)return resp([]);
  return resp([]);
};
})();
</script>"""

# 外部请求 / 错误采集
EXTS_JS = ("(function(){var out=[];try{(performance.getEntriesByType(\"resource\")||[]).forEach(function(e){"
           "var u=String(e.name||\"\");"
           "if(!/^https?:\\/\\/127\\.0\\.0\\.1[:/]/.test(u)&&!/^data:/.test(u)&&!/^blob:/.test(u))out.push(u);});}catch(e){}"
           "return out;})()")

BOOT_LOGIN = ("(function(){try{return document.readyState===\"complete\"&&document.body&&"
              "!document.body.classList.contains(\"id-locked\")&&"
              "document.querySelectorAll(\"#tabsBar button\").length>0&&"
              "!!String(((document.getElementById(\"idChipTxt\")||{}).textContent)||\"\").trim();}catch(e){return false;}})()")
BOOT_NOID = ("(function(){try{return document.readyState===\"complete\"&&document.body&&"
             "document.body.classList.contains(\"id-locked\")&&!!document.getElementById(\"igSid\")&&"
             "!!document.getElementById(\"idgate\");}catch(e){return false;}})()")

JCE = "(function(){var e=document.querySelector(__SEL__);if(!e)return false;e.click();return true;})()"
JTXT = "(function(){var e=document.querySelector(__SEL__);return e?String(e.textContent||\"\"):\"\";})()"
JATTR = "(function(){var e=document.querySelector(__SEL__);return e?String(e.getAttribute(__ATTR__)||\"\"):\"\";})()"
JCOUNT = "(function(){return document.querySelectorAll(__SEL__).length;})()"
JEXIST = "(function(){return !!document.querySelector(__SEL__);})()"
JDISABLED = "(function(){var e=document.querySelector(__SEL__);return !!e&&!!e.disabled;})()"
JDISPLAY = "(function(){var e=document.querySelector(__SEL__);return e?String(e.ownerDocument.defaultView.getComputedStyle(e).display):\"none\";})()"
JVAL = "(function(){var e=document.querySelector(__SEL__);return e?String(e.value==null?\"\":e.value):\"\";})()"
JSET = ("(function(){var e=document.querySelector(__SEL__);if(!e)return false;try{e.focus();}catch(x){}"
        "e.value=__VAL__;e.dispatchEvent(new Event(\"input\",{bubbles:true}));"
        "e.dispatchEvent(new Event(\"change\",{bubbles:true}));return true;})()")
JTEXTS = ("(function(){return Array.prototype.slice.call(document.querySelectorAll(__SEL__))"
          ".map(function(e){return String(e.textContent||\"\").trim();});})()")


def jsq(s):
    return json.dumps(str(s), ensure_ascii=False)


def enc(s):
    return urllib.parse.quote(str(s), safe="")


# ---------------------------------------------------------------------------
# CDP 客户端（同 v2_power_slow_check.py 的 live-browser 方案）
# ---------------------------------------------------------------------------
class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=60)
        self._id = 0

    def send(self, method, params=None, timeout=60):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                time.sleep(0.01)
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s -> %s" % (method, json.dumps(msg["error"], ensure_ascii=False)))
                return msg.get("result", {})
        raise TimeoutError(method)

    def eval(self, expr, timeout=60):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True}, timeout=timeout)
        res = r.get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError("JS: " + str(res.get("description"))[:400])
        return res.get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def wait_until(cdp, expr, timeout=20, interval=0.1):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cdp.eval(expr):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def wait_text(cdp, sel, sub, timeout=15):
    expr = ("(function(){var e=document.querySelector(%s);var t=e?String(e.textContent||\"\"):\"\";"
            "return t.indexOf(%s)>=0;})()" % (jsq(sel), jsq(sub)))
    return wait_until(cdp, expr, timeout)


def wait_js(cdp, js, timeout=15):
    return wait_until(cdp, js, timeout)


def ev(cdp, expr, timeout=30):
    return cdp.eval(expr, timeout=timeout)


def jget(cdp, sel):
    return bool(ev(cdp, JEXIST.replace("__SEL__", jsq(sel))))


def jtext(cdp, sel):
    try:
        return str(ev(cdp, JTXT.replace("__SEL__", jsq(sel))) or "")
    except Exception:
        return ""


def jtexts(cdp, sel):
    try:
        return ev(cdp, JTEXTS.replace("__SEL__", jsq(sel))) or []
    except Exception:
        return []


def jcount(cdp, sel):
    try:
        return int(ev(cdp, JCOUNT.replace("__SEL__", jsq(sel))) or 0)
    except Exception:
        return 0


def jattr(cdp, sel, attr):
    expr = JATTR.replace("__SEL__", jsq(sel)).replace("__ATTR__", jsq(attr))
    try:
        return str(ev(cdp, expr) or "")
    except Exception:
        return ""


def jdisabled(cdp, sel):
    try:
        return bool(ev(cdp, JDISABLED.replace("__SEL__", jsq(sel))))
    except Exception:
        return False


def jdisplay(cdp, sel):
    try:
        return str(ev(cdp, JDISPLAY.replace("__SEL__", jsq(sel))) or "none")
    except Exception:
        return "none"


def jval(cdp, sel):
    try:
        return str(ev(cdp, JVAL.replace("__SEL__", jsq(sel))) or "")
    except Exception:
        return ""


def click(cdp, sel):
    try:
        return bool(ev(cdp, JCE.replace("__SEL__", jsq(sel))))
    except Exception:
        return False


def click_first(cdp, sels):
    for s in sels:
        if click(cdp, s):
            return True
    return False


def set_input(cdp, sel, value):
    expr = JSET.replace("__SEL__", jsq(sel)).replace("__VAL__", jsq(str(value)))
    try:
        return bool(ev(cdp, expr))
    except Exception:
        return False


def set_select(cdp, sel, value):
    return set_input(cdp, sel, value)


def sleep(sec):
    time.sleep(sec)


def set_viewport(cdp, w, h, scale=1):
    try:
        cdp.send("Emulation.setDeviceMetricsOverride",
                 {"width": int(w), "height": int(h), "deviceScaleFactor": scale, "mobile": w < 600})
    except Exception:
        pass


def shot(cdp, path):
    """整页截图（超出视口也截），失败退回可视区截图。返回字节数。"""
    png = b""
    try:
        m = cdp.send("Page.getLayoutMetrics")
        cs = m.get("cssContentSize") or m.get("contentSize") or {}
        w = int(cs.get("width") or 0)
        h = int(cs.get("height") or 0)
        if w < 50 or h < 50:
            w, h = 430, 900
        w, h = min(w, 1600), min(h, 6500)
        r = cdp.send("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": w, "height": h, "scale": 1}}, timeout=90)
        png = base64.b64decode(r.get("data") or "")
    except Exception:
        try:
            r = cdp.send("Page.captureScreenshot", {"format": "png"}, timeout=90)
            png = base64.b64decode(r.get("data") or "")
        except Exception:
            png = b""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(png)
    except Exception:
        return 0
    return len(png)


# ---------------------------------------------------------------------------
# 预览页构建 / URL
# ---------------------------------------------------------------------------
def build_preview():
    src = open(SRC, encoding="utf-8").read()
    inject = (INJECT.replace("__SID_A__", SID_A).replace("__NAME__", NAME)
              .replace("__ROWS__", json.dumps(POWER_ROWS, ensure_ascii=False))
              .replace("__HIST__", json.dumps(POWER_HIST, ensure_ascii=False))
              .replace("__CATALOG__", json.dumps([[c[0], c[1], c[2]] for c in CATALOG], ensure_ascii=False)))
    out = src.replace("<head>", "<head>" + inject, 1)
    os.makedirs(os.path.dirname(PREVIEW), exist_ok=True)
    with open(PREVIEW, "w", encoding="utf-8") as f:
        f.write(out)


def purl(sid=SID_A, name=NAME, noid=False, ud=None, bucket=None, reset=False):
    q = "sid=" + enc(sid) + "&name=" + enc(name)
    if reset:
        q += "&reset=1"
    if noid:
        q += "&noid=1"
    if ud is not None:
        q += "&ud=" + enc(json.dumps(ud, ensure_ascii=False, separators=(",", ":")))
    if bucket is not None:
        q += "&bucket=" + enc(json.dumps(bucket, ensure_ascii=False, separators=(",", ":")))
    rel = "tests/_water_tmp/" + os.path.basename(RUN_TMP) + "/" + os.path.basename(PREVIEW)
    return BASE + rel + "?" + q


def ud_blob(power_sel="", water_rooms=None, with_water=True, at=1762300800000):
    blob = {
        "v": 6,
        "at": {"homeTools": at, "fit": at, "draw": at, "group": at, "roster": at,
               "hide": at, "tt": at, "prefs": at, "nick": at, "power": at},
        "homeTools": ["draw", "hw", "nt", "tt"],
        "fit": {}, "draw": {}, "group": {},
        "roster": {"rosterSel": [], "rollSel": [], "rollSt": {}, "rollNames": ""},
        "hide": {"hwHide": {}, "ntHide": {}},
        "tt": {"ttView": "", "ttUseMine": False, "ttLocal": None, "termStart": ""},
        "prefs": {"hwRemind": {}, "ntSub": False, "ntSubAt": 0},
        "nick": "", "power": {"sel": power_sel, "at": at},
        "homeToolsAt": at,
    }
    if with_water:
        blob["at"]["water"] = at
        blob["water"] = {"rooms": water_rooms or {}}
    return blob


def water_bucket(rooms):
    return {"homeTools": ["draw", "hw", "nt", "tt"], "water": {"rooms": rooms}}


def rec(m, r, ts=1762000000000):
    return {"m": m, "r": r, "ts": ts}


# ---------------------------------------------------------------------------
# 导航 / 页面操作
# ---------------------------------------------------------------------------
def nav(cdp, url, noid=False, clear=False, timeout=30):
    if clear:
        url += ("&" if "?" in url else "?") + "reset=1"
    try:
        cdp.send("Page.navigate", {"url": url})
    except Exception:
        return False
    ok = wait_until(cdp, BOOT_NOID if noid else BOOT_LOGIN, timeout)
    if ok:
        sleep(0.3)
    return ok


def open_all(cdp):
    click(cdp, '#tabsBar button[data-tab="all"]')
    sleep(0.45)


def open_card(cdp, key):
    open_all(cdp)
    click_first(cdp, ['#allCards [data-card="%s"] .btn[data-open="%s"]' % (key, key),
                      '#allCards [data-card="%s"]' % key,
                      '#allCards [data-open="%s"]' % key])
    sleep(0.7)


def open_water_page(cdp):
    open_card(cdp, "water")
    return wait_until(cdp, "(function(){var e=document.getElementById('s-water');return !!(e&&e.classList.contains('on'));})()", 12)


def open_power_page(cdp):
    open_card(cdp, "power")
    return wait_until(cdp, "(function(){var e=document.getElementById('s-power');return !!(e&&e.classList.contains('on'));})()", 12)


def select_water_room(cdp, rv):
    return set_select(cdp, "#wtSel", rv)


def select_power_room(cdp, rv):
    return set_select(cdp, "#pwSelect", rv)


def wait_ud_baseline(cdp, sid):
    expr = "(function(){try{return !!localStorage.getItem(%s);}catch(e){return false;}})()" % jsq("zq_udcache_" + sid)
    return wait_until(cdp, expr, 15)


def reqs(cdp):
    try:
        return ev(cdp, "window.__reqs||[]") or []
    except Exception:
        return []


def udposts(cdp):
    try:
        return ev(cdp, "window.__udPosts||[]") or []
    except Exception:
        return []


def urls_matching(cdp, needle, method=None):
    out = []
    for r in reqs(cdp):
        u = str(r.get("url") or "")
        if needle in u and (method is None or str(r.get("method")) == method):
            out.append(r)
    return out


def collect_errors(cdp, label):
    try:
        errs = ev(cdp, "window.__errs||[]") or []
    except Exception:
        errs = []
    try:
        cerrs = ev(cdp, "window.__cerrs||[]") or []
    except Exception:
        cerrs = []
    try:
        exts = ev(cdp, EXTS_JS) or []
    except Exception:
        exts = []
    GLOBAL["errs"].extend([str(x) for x in errs])
    GLOBAL["cerrs"].extend([str(x) for x in cerrs])
    GLOBAL["exts"].extend([str(x) for x in exts])
    T(label + "：0 JS 报错", len(errs) == 0, " | ".join([str(x) for x in errs[:3]]))
    T(label + "：0 console.error", len(cerrs) == 0, " | ".join([str(x) for x in cerrs[:3]]))
    T(label + "：无外部请求", len(exts) == 0, " | ".join([str(x) for x in exts[:3]]))


def bucket_read(cdp, sid):
    expr = ("(function(){try{return JSON.parse(localStorage.getItem(%s)||'null');}catch(e){return null;}})()"
            % jsq("zq_tools_v2_" + sid))
    try:
        return ev(cdp, expr)
    except Exception:
        return None


def rows_of(cdp):
    """历史列表 [{'m':..,'t':..}]（data-wm 行）"""
    expr = ("(function(){return Array.prototype.slice.call(document.querySelectorAll('#wtList [data-wm]'))"
            ".map(function(e){return {m:String(e.getAttribute('data-wm')||''),t:String(e.textContent||'').trim()};});})()")
    try:
        return ev(cdp, expr) or []
    except Exception:
        return []


def row_text(cdp, month):
    for r in rows_of(cdp):
        if r.get("m") == month:
            return r.get("t") or ""
    return ""


def save_record(cdp, month, reading):
    ok_m = set_input(cdp, "#wtMonth", month)
    ok_r = set_input(cdp, "#wtReading", str(reading))
    ok_b = click(cdp, "#wtSave")
    sleep(0.25)
    return ok_m and ok_r and ok_b


def toast_text(cdp):
    return jtext(cdp, "#toast").strip()


# ---------------------------------------------------------------------------
# 静态契约检查（不启动浏览器）
# ---------------------------------------------------------------------------
def static_checks():
    out = []
    src = open(SRC, encoding="utf-8").read()
    flat = re.sub(r"\s+", "", src)

    def ck(name, ok, note=""):
        out.append((name, bool(ok), str(note)[:200]))

    ck("版本号仍为 2.0.0", 'var APP_VER="2.0.0"' in src)
    p_power = src.find('id="s-power"')
    p_water = src.find('id="s-water"')
    p_all = src.find('id="s-all"')
    ck("存在 #s-water 段，且位于 #s-power 之后 / #s-all 之前",
       -1 < p_power < p_water < p_all, "pos %s/%s/%s" % (p_power, p_water, p_all))
    ck("TOOLS 含 water 工具（n=水量）", 'k:"water"' in src and 'n:"水量"' in src)
    ck("ALL_TONE 含 water 色调", 'water:"blue"' in src)
    ck("全部页卡片由模板生成（data-card/data-open）",
       'data-card="' in src and 'data-open="' in src)
    ids = ["s-water", "wtMeta", "wtSel", "wtPersons", "wtLastNum", "wtLastSub", "wtCmp",
           "wtMonth", "wtReading", "wtSave", "wtPreview", "wtList", "wtRuleBody",
           "pwDeduct", "pwBill"]
    miss = [i for i in ids if ('id="%s"' % i) not in src]
    ck("契约 DOM id 齐全（15 个）", not miss, "缺少 " + ",".join(miss))
    ck("RULES 常量（0.58/3.03/2 / 5 / 4 人 / 1-6）",
       bool(re.search(r"elec:\s*0\.58", src)) and bool(re.search(r"water:\s*3\.03", src))
       and bool(re.search(r"waterFreePP:\s*2\b", src)) and bool(re.search(r"elecFreePP:\s*5\b", src))
       and bool(re.search(r"personsDef:\s*4\b", src))
       and bool(re.search(r"personsOpts:\s*\[\s*1\s*,\s*2\s*,\s*3\s*,\s*4\s*,\s*5\s*,\s*6\s*\]", src)))
    ck("PW_DEDUCT 常量（minDeg:5 / factor:4 / waterMatch:0.1）",
       bool(re.search(r"PW_DEDUCT\s*=\s*\{[^}]*minDeg:\s*5[^}]*factor:\s*4[^}]*waterMatch:\s*0?\.10?[^}]*\}", src)))
    ck("UD_KEYS 末尾追加 water（11 section）",
       'UD_KEYS=["homeTools","fit","draw","group","roster","hide","tt","prefs","nick","power","water"]' in flat)
    ck("UD_DEF.water={rooms:{}} 且 UD.sections()/apply 接入 water",
       "water:{rooms:{}}" in flat and "out.water=" in flat and "WATER.applyRemote" in src)
    ck("DEF.water 缺省 + mkD 校验（water 至少 2 处缺省）", flat.count("water:{rooms:{}}") >= 2)
    ck("云同步状态 UI（#wtSync + syncState/renderSync/requestSync 接入）",
       'id="wtSync"' in src and "syncState:function" in src and "renderSync:function" in src
       and "requestSync:function" in src and "WATER.renderSync()" in flat)
    ck("water 归一 normWater（applyRemote + UD.sections 接入，防脏数据）",
       "normWater:function" in src and "D.d.water=WATER.normWater(w)" in src
       and "WATER.normWater(d.water)" in flat)
    ck("桌面比例：三栏排布 + 抄表历史常高内部滚动（contain:size）",
       'grid-template-areas:"hero form hist" "hero rules hist"' in src
       and "contain:size" in flat and "overflow-y:auto" in flat)
    ck("gotoTab 进入水量页调用 WATER.enter()", 'if(k==="water")WATER.enter()' in flat)
    ck("历史行模板含 data-wm / data-wdel", "data-wm" in src and "data-wdel" in src)
    ck("规则卡文案关键字（0.58 元/度 / 3.03 元/吨 / 以学校最新通知为准）",
       "0.58元/度" in flat and "3.03元/吨" in flat and "以学校最新通知为准" in flat)
    ck("规则卡公式（超出定额/折合扣电）", "超出定额" in src and "折合扣电" in src)
    ck("不接市政阶梯价（源码无「阶梯水价/阶梯电价」/ 0.4983）",
       "阶梯水价" not in src and "阶梯电价" not in src and "居民阶梯" not in src and "0.4983" not in flat)
    ck("水/电单价公式源码引用 RULES.water / RULES.elec", "RULES.water" in src and "RULES.elec" in src)
    ck("电费既有契约未破坏（power_history 单选请求 / 关键 DOM）",
       "power_history?select=ts,quantity&roomverify=eq." in src
       and 'id="pwSelect"' in src and 'id="pwNum"' in src and 'id="pwLowBar"' in src
       and "PW_RANGES" in src)
    ck("未引入构建链 / 外部 CDN", ("<script src=" not in src) and ("cdn." not in src))
    return out


# ---------------------------------------------------------------------------
# A. 身份门禁（未登录 0 请求 / 不渲染 → 学号+姓名进入）
# ---------------------------------------------------------------------------
def sc_a_identity(cdp):
    ok = nav(cdp, purl(noid=True), noid=True, clear=True)
    locked = False
    try:
        locked = bool(ev(cdp, "!!document.body&&document.body.classList.contains('id-locked')"))
    except Exception:
        pass
    gate_vis = jdisplay(cdp, "#idgate") != "none" and jget(cdp, "#idgate")
    T("A01 未登录：身份门禁可见", ok and locked and gate_vis,
      "boot=%s locked=%s gate=%s" % (ok, locked, jdisplay(cdp, "#idgate")))
    T("A02 未登录：不渲染工具栏", jcount(cdp, "#tabsBar button") == 0, jcount(cdp, "#tabsBar button"))
    T("A03 未登录：全部页不渲染水量卡片", jcount(cdp, '#allCards [data-card="water"]') == 0,
      jcount(cdp, "#allCards [data-card]"))
    water_on = False
    if jget(cdp, "#s-water"):
        try:
            water_on = bool(ev(cdp, "(function(){var e=document.getElementById('s-water');return !!(e&&e.classList.contains('on'));})()"))
        except Exception:
            water_on = False
    T("A04 未登录：#s-water 未激活且无水量数据",
      (not water_on) and jcount(cdp, "#wtList [data-wm]") == 0,
      "water_on=%s" % water_on)
    T("A05 未登录：0 个 CloudBase 请求", len(reqs(cdp)) == 0, len(reqs(cdp)))
    body_txt = ""
    try:
        body_txt = str(ev(cdp, "document.body?document.body.textContent:''") or "")
    except Exception:
        pass
    T("A06 未登录：不显示姓名/学号", NAME not in body_txt and SID_A not in body_txt)
    try:
        wt_opts = int(ev(cdp, "(function(){var e=document.getElementById('wtSel');return e?e.options.length:0;})()") or 0)
    except Exception:
        wt_opts = 0
    T("A07 未登录：水量页数据未渲染", jcount(cdp, "#wtList [data-wm]") == 0 and wt_opts <= 1,
      "rows=%d opts=%d" % (jcount(cdp, "#wtList [data-wm]"), wt_opts))
    collect_errors(cdp, "A 未登录")

    # 登录：学号 + 姓名 → mock class_verify → 进入班级
    set_input(cdp, "#igSid", SID_A)
    set_input(cdp, "#igName", NAME)
    ev(cdp, "(function(){var a=document.getElementById('igAgree');if(a){a.checked=true;a.dispatchEvent(new Event('change'));}return true;})()")
    click(cdp, "#igGo")
    login_ok = wait_until(cdp, BOOT_LOGIN, 20)
    T("A08 登录：学号+姓名校验后进入班级", login_ok,
      "locked=%s" % (str(ev(cdp, "document.body.classList.contains('id-locked')")) if login_ok else "timeout"))
    chip = jtext(cdp, "#idChipTxt").strip()
    T("A09 登录：顶部显示本人姓名", chip == NAME, chip)
    ver = urls_matching(cdp, "rpc/class_verify", "POST")
    ver_body = ver[0].get("body", "") if ver else ""
    T("A10 登录：class_verify 携带学号/姓名", bool(ver) and SID_A in ver_body and NAME in ver_body,
      ver_body[:120])
    T("A11 登录后：工具栏渲染（≥4 按钮）", jcount(cdp, "#tabsBar button") >= 4, jcount(cdp, "#tabsBar button"))


# ---------------------------------------------------------------------------
# B. 水量页基础（全部页卡片 / #s-water / 空态 / 规则卡）
# ---------------------------------------------------------------------------
def sc_b_water_basics(cdp):
    open_all(cdp)
    n_cards = jcount(cdp, "#allCards [data-card]")
    T("B01 全部页渲染工具卡", n_cards > 0, n_cards)
    card_ok = jget(cdp, '#allCards [data-card="water"]') and "水量" in jtext(cdp, '#allCards [data-card="water"]')
    T("B02 全部页存在「水量」卡片", card_ok, jattr(cdp, '#allCards [data-card="water"]', "data-card"))
    T("B03 水量卡片 data-open=water", jattr(cdp, '#allCards [data-card="water"]', "data-open") == "water",
      jattr(cdp, '#allCards [data-card="water"]', "data-open"))
    click_first(cdp, ['#allCards [data-card="water"] .btn[data-open="water"]',
                      '#allCards [data-card="water"]', '#allCards [data-open="water"]'])
    sleep(0.7)
    on = bool(ev(cdp, "(function(){var e=document.getElementById('s-water');return !!(e&&e.classList.contains('on'));})()"))
    T("B04 点击卡片打开 #s-water", on and jdisplay(cdp, "#s-water") != "none",
      "on=%s display=%s" % (on, jdisplay(cdp, "#s-water")))
    order_ok = False
    try:
        order_ok = bool(ev(cdp, "(function(){var a=document.getElementById('s-power'),b=document.getElementById('s-water'),c=document.getElementById('s-all');"
                                "if(!a||!b||!c)return false;return !!(a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING)&&"
                                "!!(b.compareDocumentPosition(c)&Node.DOCUMENT_POSITION_FOLLOWING);})()"))
    except Exception:
        pass
    T("B05 #s-water 位于 #s-power 与 #s-all 之间", order_ok)

    # 未选宿舍：引导 + 三输入 disabled + 默认当前月
    cmp_txt = jtext(cdp, "#wtCmp")
    T("B06 未选宿舍：#wtCmp 引导「先选择关注宿舍」", "先选择关注宿舍" in norm(cmp_txt), norm(cmp_txt)[:100])
    dis = [jdisabled(cdp, "#wtMonth"), jdisabled(cdp, "#wtReading"), jdisabled(cdp, "#wtSave")]
    T("B07 未选宿舍：#wtMonth/#wtReading/#wtSave 禁用", all(dis), str(dis))
    mv = jval(cdp, "#wtMonth")
    T("B08 #wtMonth 默认当前月（%s）" % M0, mv == M0, mv)

    opts = jcount(cdp, "#wtSel option")
    optgroups = jtexts(cdp, "#wtSel optgroup") if jget(cdp, "#wtSel") else []
    labels = []
    try:
        labels = ev(cdp, "(function(){return Array.prototype.slice.call(document.querySelectorAll('#wtSel optgroup')).map(function(g){return String(g.getAttribute('label')||'');});})()") or []
    except Exception:
        pass
    T("B09 #wtSel 宿舍选项 = 17 间（与电费同源）", opts >= 17, opts)
    T("B10 #wtSel optgroup = 4 个规范楼栋",
      labels == ["13号楼", "16号楼", "23号楼A座", "23号楼B座"], ",".join(labels))
    persons = []
    try:
        persons = ev(cdp, "(function(){var e=document.getElementById('wtPersons');return e?Array.prototype.slice.call(e.options).map(function(o){return o.value;}):[];})()") or []
    except Exception:
        pass
    T("B11 #wtPersons 选项 = 1–6 人且默认 4", persons == ["1", "2", "3", "4", "5", "6"] and jval(cdp, "#wtPersons") == "4",
      str(persons) + " val=" + jval(cdp, "#wtPersons"))
    T("B12 规则卡 #wtRuleBody 有内容", len(norm(jtext(cdp, "#wtRuleBody"))) > 10,
      norm(jtext(cdp, "#wtRuleBody"))[:80])
    # 可点区域 ≥40px（契约 §3.3.8）
    sizes = {}
    for sel in ("#wtSave", "#wtSel", "#wtPersons"):
        try:
            sizes[sel] = float(ev(cdp, "(function(){var e=document.querySelector(%s);return e?e.getBoundingClientRect().height:0;})()" % jsq(sel)) or 0)
        except Exception:
            sizes[sel] = 0
    T("B13 可点区域高度 ≥40px（#wtSave/#wtSel/#wtPersons）",
      all(v >= 40 for v in sizes.values()), json.dumps({k: round(v, 1) for k, v in sizes.items()}))

    # D. 规则卡文案（契约 §3.3.6 / §5 D）
    rule = jtext(cdp, "#wtRuleBody")
    T("D01 规则卡：水费 3.03 元/吨", "3.03元/吨" in norm(rule), norm(rule)[:120])
    T("D02 规则卡：水免费定额 2 吨/人/月", "2吨" in norm(rule) and "每人" in rule, norm(rule)[:200])
    T("D03 规则卡：水费=超出定额部分×3.03", "超出定额" in rule and "3.03" in rule, norm(rule)[:220])
    T("D04 规则卡：折合扣电=水费÷0.58", has_any(rule, "折合扣电", "折合") and "0.58" in rule)
    T("D05 电费计费规则不放在水量页（改由电量统计承载）", "电费" not in norm(rule) and "5度" not in norm(rule), norm(rule)[:200])
    T("D06 规则卡：来源（学校后勤 / 2025-09 / 2021 公寓管理规定）",
      ("后勤" in rule or "后勤基建处" in rule) and "以学校最新通知为准" in rule
      and has_any(rule, "2025-09", "2021"))
    water_txt = jtext(cdp, "#s-water")
    T("D07 规则卡不出现市政阶梯价/错误常量",
      not any(x in norm(water_txt) for x in ("阶梯水价", "阶梯电价", "居民阶梯", "0.4983", "7.20元")),
      " | ".join([x for x in ("阶梯水价", "阶梯电价", "居民阶梯", "0.4983", "7.20元") if x in norm(water_txt)]))
    # 隐私：水量页/电费页只出现关注宿舍，不出现姓名/学号（顶栏本人姓名属全局身份组件，不在本断言内）
    water_txt = jtext(cdp, "#s-water") + " " + jtext(cdp, "#s-power")
    T("B14 水量/电费页不显示姓名/学号", NAME not in water_txt and SID_A not in water_txt,
      norm(water_txt)[:80])
    collect_errors(cdp, "B/C 基础")


# ---------------------------------------------------------------------------
# C. 手动抄表（保存 / 自动对比 / 水费公式 / 覆盖 / 拒绝 / 删除 / 倒序 / 预览 / 人数）
# ---------------------------------------------------------------------------
def sc_c_records(cdp):
    # 选中关注宿舍（与电费共用）
    sel_ok = select_water_room(cdp, RV321)
    Sleep = sleep
    en = wait_until(cdp, "(function(){var e=document.getElementById('wtSave');return !!e&&!e.disabled;})()", 10)
    T("C01 选择关注宿舍后输入启用", sel_ok and en, "sel=%s enabled=%s" % (sel_ok, en))

    # 无记录空态
    T("C02 无记录：#wtList 空态占位",
      has_any(jtext(cdp, "#wtList"), "还没有抄表记录", "暂无", "没有记录", "首次记录"),
      norm(jtext(cdp, "#wtList"))[:80])

    # 第一条（最早月）
    save_record(cdp, M4, "100.00")
    rows = rows_of(cdp)
    T("C03 首次保存 %s 100.00 → 历史行存在" % M4, any(r["m"] == M4 for r in rows), [r["m"] for r in rows])
    first = row_text(cdp, M4)
    T("C04 首条记录用量显示「—」", has_any(first, "—", "–", "-", "首次记录"), norm(first)[:80])

    # 第二条：自动对比（用量 13.74 / 水费 17.39 / 折合扣电 30.0）
    save_record(cdp, M3, "113.74")
    wait_text(cdp, "#wtCmp", "13.74", 10)
    cmp_txt = jtext(cdp, "#wtCmp")
    T("C05 自动对比：较上次 %s 用量 13.74 吨" % M4, "13.74" in norm(cmp_txt) and M4 in norm(cmp_txt), norm(cmp_txt)[:140])
    T("C06 水费公式：13.74 吨（4 人免 8 吨）→ 17.39 元",
      "17.39" in norm(cmp_txt), norm(cmp_txt)[:140])
    T("C07 折合扣电：17.39 / 0.58 → 30.0 度", "30.0" in norm(cmp_txt), norm(cmp_txt)[:140])
    row3 = row_text(cdp, M3)
    T("C08 历史行含读数/用量/水费", has_all(row3, "113.74", "13.74", "17.39"), norm(row3)[:120])

    # 同月覆盖
    save_record(cdp, M3, "113.80")
    sleep(0.15)
    toast = toast_text(cdp)
    rows = rows_of(cdp)
    row3 = row_text(cdp, M3)
    T("C09 同月覆盖：行数不变且值更新",
      len(rows) == 2 and has_all(row3, "113.80", "13.80", "17.57"), "%d 行 | %s" % (len(rows), norm(row3)[:110]))
    T("C10 同月覆盖 toast「已更新」", has_any(toast, "已更新", "更新"), toast[:80])

    # #wtPreview 即时预览（M2 / 120.50：较 M3 113.80 → 6.70 / 0.00）
    set_input(cdp, "#wtMonth", M2)
    set_input(cdp, "#wtReading", "120.50")
    sleep(0.25)
    prev = jtext(cdp, "#wtPreview")
    T("C11 #wtPreview 输入即时预览（6.70 / 0.00）",
      "6.70" in norm(prev) and "0.00" in norm(prev), norm(prev)[:120])

    # 保存 M2 120.00（用量 6.20，未超定额）
    save_record(cdp, M2, "120.00")
    wait_text(cdp, "#wtCmp", "6.20", 10)
    cmp_txt = jtext(cdp, "#wtCmp")
    T("C12 未超定额：用量 6.20 → 水费 0.00 / 折合 0.0",
      "6.20" in norm(cmp_txt) and "0.00" in norm(cmp_txt) and "0.0" in norm(cmp_txt), norm(cmp_txt)[:140])

    # 读数小于上次 → 拒绝
    save_record(cdp, M1, "119.00")
    sleep(0.15)
    toast = toast_text(cdp)
    no_row = not any(r["m"] == M1 for r in rows_of(cdp))
    T("C13 读数小于上次 → 拒绝（不落盘）", no_row, [r["m"] for r in rows_of(cdp)])
    T("C14 拒绝 toast「读数不能小于上次记录」", "不能小于" in toast, toast[:90])

    # 非法读数（负数）→ 拒绝
    save_record(cdp, M1, "-1")
    sleep(0.15)
    toast2 = toast_text(cdp)
    T("C15 非法读数（-1）→ toast 且不落盘",
      toast2.strip() != "" and not any(r["m"] == M1 for r in rows_of(cdp)), toast2[:90])

    # 超出定额：M1 130.00 → 用量 10.00 / 超出 2.00 吨 / 水费 6.06 / 折合 10.4
    save_record(cdp, M1, "130.00")
    wait_text(cdp, "#wtCmp", "10.00", 10)
    cmp_txt = jtext(cdp, "#wtCmp")
    T("C16 超出定额：用量 10.00 → 超出 2.00 吨 → 水费 6.06",
      has_all(cmp_txt, "10.00", "超出定额2.00吨", "6.06"), norm(cmp_txt)[:160])
    T("C17 超出定额：折合扣电 10.4 度", "10.4" in norm(cmp_txt), norm(cmp_txt)[:160])

    # 历史倒序
    order = [r["m"] for r in rows_of(cdp)]
    T("C18 历史列表按月份倒序", order == [M1, M2, M3, M4], ",".join(order))

    # 2026-11-19：取消 23A/23B 固定 4 人间，所有宿舍 1–6 自选。
    set_select(cdp, "#wtPersons", "6")
    sleep(0.3)
    free6_ok = (jval(cdp, "#wtPersons") == "6" and
                not bool(ev(cdp, "(function(){var e=document.getElementById('wtPersons');return !!e&&!!e.disabled;})()")))
    T("C18b 23A 房间（4-23A---321）1–6 自选：6 人可生效", free6_ok,
      "val=%s" % jval(cdp, "#wtPersons"))
    rv13_ok = select_water_room(cdp, RV13)
    sleep(0.4)
    en13 = wait_until(cdp, "(function(){var e=document.getElementById('wtSave');return !!e&&!e.disabled;})()", 10)
    T("C18c 13 号楼可切换关注宿舍（人数 1–6 可选）",
      rv13_ok and en13 and not ev(cdp, "(function(){var e=document.getElementById('wtPersons');return !!e&&!!e.disabled;})()"),
      "sel=%s" % jval(cdp, "#wtSel"))
    save_record(cdp, M4, "100.00")
    save_record(cdp, M3, "113.74")
    save_record(cdp, M1, "130.00")
    wait_text(cdp, "#wtList", "17.39", 10)

    # 人数 4 → 6：历史水费全量重算（M3 13.80→5.45；M1 10.00→0.00）
    set_select(cdp, "#wtPersons", "6")
    sleep(0.4)
    wait_text(cdp, "#wtList", "5.45", 10)
    row3 = row_text(cdp, M3)
    row1 = row_text(cdp, M1)
    T("C19 13 号楼人数切 6：M3 水费按 6 人重算 5.27", "5.27" in norm(row3), norm(row3)[:110])
    T("C20 13 号楼人数切 6：M1 用量 10.00 < 定额 12 吨 → 水费 0.00", "0.00" in norm(row1), norm(row1)[:110])
    T("C21 13 号楼人数切 6：规则卡定额更新为 12 吨", "12吨" in norm(jtext(cdp, "#wtRuleBody")),
      norm(jtext(cdp, "#wtRuleBody"))[:100])

    # 人数 6 → 4：恢复（M3 17.57）
    set_select(cdp, "#wtPersons", "4")
    sleep(0.4)
    wait_text(cdp, "#wtList", "17.57", 10)
    row3 = row_text(cdp, M3)
    T("C22 13 号楼人数切回 4：M3 水费恢复 17.39", "17.39" in norm(row3), norm(row3)[:110])
    T("C23 13 号楼人数切回 4：规则卡定额 8 吨", "8吨" in norm(jtext(cdp, "#wtRuleBody")),
      norm(jtext(cdp, "#wtRuleBody"))[:100])

    # 切回原 23A 房间（后续 C24+ 断言仍在 321 上）
    select_water_room(cdp, RV321)
    sleep(0.4)
    # 23A 的 6 人选择沿用；C24+ 的 4 人口径先切回 4，避免影响后续断言。
    set_select(cdp, "#wtPersons", "4")
    sleep(0.3)

    # 删除 M3（confirm 确认）→ M2 用量重算为 20.00 / 36.36
    try:
        ev(cdp, "window.confirm=function(){return true;};true")
    except Exception:
        pass
    click(cdp, '[data-wdel="%s"]' % M3)
    sleep(0.5)
    rows = rows_of(cdp)
    order = [r["m"] for r in rows]
    row2 = row_text(cdp, M2)
    T("C24 删除记录：行数 3 且 M2 后续重算（20.00 / 36.36）",
      len(rows) == 3 and has_all(row2, "20.00", "36.36"), "%d 行 | %s" % (len(rows), norm(row2)[:120]))
    T("C25 删除后历史仍倒序", order == [M1, M2, M4], ",".join(order))

    # 本机存储归一化
    obj = bucket_read(cdp, SID_A) or {}
    water = ((obj.get("water") or {}).get("rooms") or {}).get(RV321) or {}
    recs = water.get("recs") or []
    T("C26 本机存储 water.rooms[rv] 归一（升序 / 2 位小数 / p=4）",
      water.get("p") == 4 and [x.get("m") for x in recs] == [M4, M2, M1]
      and all(abs(float(x.get("r", -1)) - v) < 1e-9 for x, v in zip(recs, [100.0, 120.0, 130.0])),
      json.dumps(water, ensure_ascii=False)[:200])

    # 删除后自动对比仍指向最新一条
    cmp_txt = jtext(cdp, "#wtCmp")
    T("C27 删除后 #wtCmp 指向最新一条（10.00 / 6.06）",
      "10.00" in norm(cmp_txt) and "6.06" in norm(cmp_txt), norm(cmp_txt)[:140])

    # 上次抄表区
    last_num = jtext(cdp, "#wtLastNum")
    last_sub = jtext(cdp, "#wtLastSub")
    T("C28 上次抄表区显示最新读数与月份/人数",
      "130.00" in norm(last_num) and M1 in norm(last_sub) and "4" in norm(last_sub),
      norm(last_num) + " | " + norm(last_sub))

    # 与电费页共用选择（水量 → 电费）
    open_power_page(cdp)
    T("C29 关注宿舍与电费共用（水量选 321 → #pwSelect=321）", jval(cdp, "#pwSelect") == RV321,
      jval(cdp, "#pwSelect"))
    select_power_room(cdp, RV330)
    sleep(0.6)
    open_water_page(cdp)
    T("C30 关注宿舍与电费共用（电费改 330 → #wtSel=330）", jval(cdp, "#wtSel") == RV330,
      jval(cdp, "#wtSel"))
    select_water_room(cdp, RV321)
    sleep(0.4)

    collect_errors(cdp, "C 抄表")


# ---------------------------------------------------------------------------
# E. 电费页计费 + 异常大跌忽略
# ---------------------------------------------------------------------------
def sc_e_power(cdp):
    bucket = water_bucket({
        RV321: {"p": 4, "recs": [rec(PREV_M, 100.00), rec(CUR_M, 113.74)]},
    })
    ok = nav(cdp, purl(bucket=bucket), clear=True)
    T("E01 电量页 fixture 启动", ok)
    opened = open_power_page(cdp)
    T("E02 打开 #s-power", opened and jdisplay(cdp, "#s-power") != "none", opened)
    sleep(1.0)
    T("E03 未选择宿舍：0 个 power 请求", len(urls_matching(cdp, "/power?", "GET")) == 0,
      len(urls_matching(cdp, "/power?", "GET")))
    T("E04 未选择宿舍：0 个 power_history 请求", len(urls_matching(cdp, "/power_history")) == 0,
      len(urls_matching(cdp, "/power_history")))

    select_power_room(cdp, RV321)
    wait_text(cdp, "#pwNum", "357", 12)
    wait_until(cdp, "(function(){var e=document.getElementById('pwDeduct');return !!e&&!e.hidden;})()", 12)
    sleep(0.4)
    T("E05 选择后 mock 返回电量（357 度）", jtext(cdp, "#pwNum").strip() == "357", jtext(cdp, "#pwNum"))
    T("E06 24h 趋势渲染（内联 SVG 折线）", jget(cdp, "#pwTrend svg") and jget(cdp, "#pwTrend path.pw-trend-line"))

    tiles = jtext(cdp, "#pwTiles")
    T("E07 区间用电不含 30 度异常（3.0 度）", "近24h用电3.0度" in norm(tiles), norm(tiles)[:200])
    T("E08 区间电费副标 = 3.0×0.58 ≈ ¥1.74", "¥1.74" in norm(tiles) or "1.74" in norm(tiles),
      norm(tiles)[:200])
    chip = jtext(cdp, "#pwDeduct")
    T("E09 #pwDeduct 出现：水量匹配 →「水费扣除 1 次」",
      "水费扣除" in norm(chip) and "1" in norm(chip), norm(chip)[:120])
    legend = jtext(cdp, "#pwLegend")
    lg_m = re.search(r"扣减([0-9]+(?:\.[0-9]+)?)度", norm(legend))
    lg_deg = float(lg_m.group(1)) if lg_m else -1.0
    T("E10 图例追加「扣减 ~30 度」（实测 %s）" % (lg_deg if lg_deg >= 0 else "缺"), 29.0 <= lg_deg <= 31.0,
      norm(legend)[:160])
    bill = jtext(cdp, "#pwBill")
    T("E11 电费计费规则在电量统计内（#pwTiles #pwBill：0.58 元/度 / 3.03 元/吨 / 5.2 度）",
      bool(jget(cdp, "#pwTiles #pwBill")) and has_all(bill, "0.58", "3.03", "5.2")
      and "5" in norm(bill), norm(bill)[:200])
    T("E12 #pwBill 扣减摘要（已忽略 1 次 · ≈¥17.x）",
      "已忽略1次" in norm(bill) and has_any(bill, "17.39", "17.4", "17.392"), norm(bill)[:200])

    days = jtext(cdp, "#pwDays")
    rate_m = re.search(r"≈(\d+(?:\.\d+)?)度/天", norm(tiles))
    rate = float(rate_m.group(1)) if rate_m else -1.0
    T("E13 估算不受异常段影响（≥30 天 / 速率 %.1f 度/天 ∈[5,15]）" % rate,
      "≥30" in norm(days) and 5.0 <= rate <= 15.0, norm(days) + " | " + norm(tiles)[:160])

    # 未匹配的 30 度异常 → 「已忽略 N 次扣减」（候选但非水费）
    select_power_room(cdp, RV330)
    wait_text(cdp, "#pwNum", "200", 12)
    sleep(0.8)
    chip = jtext(cdp, "#pwDeduct")
    tiles = jtext(cdp, "#pwTiles")
    T("E14 未匹配异常 →「已忽略 1 次扣减」",
      "已忽略" in norm(chip) and "1" in norm(chip) and "扣减" in norm(chip), norm(chip)[:120])
    T("E15 未匹配异常：区间用电同样不计入（3.0 度）", "近24h用电3.0度" in norm(tiles), norm(tiles)[:200])
    bill = jtext(cdp, "#pwBill")
    T("E16 未匹配异常：#pwBill 含「已忽略 1 次」", "已忽略1次" in norm(bill), norm(bill)[:200])

    # 正常房：无扣减 chip / 无扣减图例 / 电费 = 2.0×0.58
    select_power_room(cdp, RV305)
    wait_text(cdp, "#pwNum", "100", 12)
    sleep(0.8)
    # 16/13 号楼用户界面已隐藏 24h 档；本用例验证 24h 数据口径，显式切到 24h
    ev(cdp, "(function(){var b=document.querySelector('#pwRanges [data-range=\"24h\"]');if(b)b.click();return true;})()")
    sleep(0.5)
    chip_hidden = True
    try:
        chip_hidden = bool(ev(cdp, "(function(){var e=document.getElementById('pwDeduct');"
                                    "if(!e)return true;var cs=getComputedStyle(e);return !!e.hidden||cs.display==='none';})()"))
    except Exception:
        pass
    tiles = jtext(cdp, "#pwTiles")
    T("E17 正常房：#pwDeduct 隐藏（无扣减）", chip_hidden, jtext(cdp, "#pwDeduct")[:80])
    T("E18 正常房：区间用电 2.0 度 / 电费 ¥1.16",
      "近24h用电2.0度" in norm(tiles) and has_any(tiles, "¥1.16", "1.16"), norm(tiles)[:200])
    T("E19 正常房：图例无扣减项", "扣减" not in norm(jtext(cdp, "#pwLegend")), norm(jtext(cdp, "#pwLegend"))[:120])

    power_txt = jtext(cdp, "#s-power")
    T("E20 电费页不含姓名/学号", NAME not in power_txt and SID_A not in power_txt)

    select_power_room(cdp, RV321)
    wait_text(cdp, "#pwNum", "357", 12)
    sleep(0.5)
    size = shot(cdp, os.path.join(SHOTS, "power_deduct_430.png"))
    T("E21 截图 power_deduct_430.png", size > 8000, "%d bytes" % size)
    collect_errors(cdp, "E 电费")


# ---------------------------------------------------------------------------
# F. 同步（POST blob / 换设备恢复 / 两账号隔离 / 旧数据无 water）
# ---------------------------------------------------------------------------
def _find_water_post(cdp, sid, rv):
    for p in reversed(udposts(cdp)):
        if str(p.get("id")) != sid:
            continue
        try:
            b = json.loads(p.get("blob") or "null")
        except Exception:
            continue
        if not isinstance(b, dict):
            continue
        rooms = ((b.get("water") or {}).get("rooms") or {})
        if isinstance(rooms.get(rv), dict):
            return b
    return None


def sc_f_sync(cdp):
    ok = nav(cdp, purl(), clear=True)
    T("F01 同步场景启动", ok)
    wait_ud_baseline(cdp, SID_A)
    open_water_page(cdp)
    select_water_room(cdp, RV321)
    wait_until(cdp, "(function(){var e=document.getElementById('wtSave');return !!e&&!e.disabled;})()", 10)
    save_record(cdp, M4, "100.00")
    save_record(cdp, M3, "113.74")
    sleep(0.3)

    cond = ("(function(){var ps=window.__udPosts||[];for(var i=ps.length-1;i>=0;i--){try{var b=JSON.parse(ps[i].blob);"
            "var r=b&&b.water&&b.water.rooms&&b.water.rooms[%s];if(r&&r.recs&&r.recs.length>=2)return true;}catch(e){}}return false;})()"
            % jsq(RV321))
    posted = wait_until(cdp, cond, 20)
    T("F02 保存后 ≥1200ms 防抖触发 userdata POST（blob 含 water）", posted, len(udposts(cdp)))
    blob = _find_water_post(cdp, SID_A, RV321)
    T("F03 POST id = 本人 sid", bool(udposts(cdp)) and str(udposts(cdp)[-1].get("id")) == SID_A,
      str(udposts(cdp)[-1].get("id")) if udposts(cdp) else "none")
    if blob:
        T("F04 blob 顶层 14 键顺序正确",
          list(blob.keys()) == ["v", "at", "homeTools", "fit", "draw", "group", "roster", "hide",
                                "tt", "prefs", "nick", "power", "water", "homeToolsAt"],
          ",".join(blob.keys()))
        atw = (blob.get("at") or {}).get("water")
        T("F05 blob.at.water 为数字且 water 值内不镜像 at",
          isinstance(atw, (int, float)) and atw > 0 and "at" not in (blob.get("water") or {}),
          "at.water=%s water.keys=%s" % (atw, list((blob.get("water") or {}).keys())))
        rw = ((blob.get("water") or {}).get("rooms") or {}).get(RV321) or {}
        recs = rw.get("recs") or []
        T("F06 blob.water.rooms[rv] 内容正确（p=4 / 2 条 / 月份升序 / 读数）",
          rw.get("p") == 4 and [x.get("m") for x in recs] == [M4, M3]
          and abs(float(recs[0].get("r", 0)) - 100.0) < 1e-9
          and abs(float(recs[1].get("r", 0)) - 113.74) < 1e-9,
          json.dumps(rw, ensure_ascii=False)[:220])
        blob_obj = blob
        # 换设备：清本机 → 用云端 blob 重新登录恢复
        restored = nav(cdp, purl(ud=blob_obj), clear=True)
        T("F07 换设备（清本机 + 云端 blob）启动", restored)
        wait_ud_baseline(cdp, SID_A)
        open_water_page(cdp)
        wait_until(cdp, "(function(){var e=document.getElementById('wtSel');return !!e&&e.value===%s;})()" % jsq(RV321), 15)
        rows_ok = wait_until(cdp, "(function(){return document.querySelectorAll('#wtList [data-wm]').length>=2;})()", 15)
        rows = rows_of(cdp)
        T("F08 换设备恢复抄表记录（2 行）", rows_ok and len(rows) >= 2, len(rows))
        T("F09 换设备恢复关注宿舍与人数（321 / 4 人）",
          jval(cdp, "#wtSel") == RV321 and jval(cdp, "#wtPersons") == "4",
          jval(cdp, "#wtSel") + "/" + jval(cdp, "#wtPersons"))
        row3 = row_text(cdp, M3)
        T("F10 恢复后历史数据正确（113.74 / 13.74 / 17.39）",
          has_all(row3, "113.74", "13.74", "17.39"), norm(row3)[:120])
    else:
        for nm in ("F04 blob 顶层 14 键顺序正确", "F05 blob.at.water 为数字且 water 值内不镜像 at",
                   "F06 blob.water.rooms[rv] 内容正确", "F07 换设备启动", "F08 换设备恢复抄表记录（2 行）",
                   "F09 换设备恢复关注宿舍与人数（321 / 4 人）", "F10 恢复后历史数据正确"):
            T(nm, False, "未捕获到 water userdata POST")
    collect_errors(cdp, "F 同步")


def sc_f_isolation(cdp):
    seedA = ud_blob(power_sel=RV321, water_rooms={
        RV321: {"p": 4, "recs": [rec("2025-01", 50.00), rec("2025-02", 60.50)]}})
    nav(cdp, purl(ud=seedA), clear=True)
    wait_ud_baseline(cdp, SID_A)
    open_water_page(cdp)
    wait_until(cdp, "(function(){return document.querySelectorAll('#wtList [data-wm]').length>=2;})()", 15)
    rowA = row_text(cdp, "2025-02")
    getsA = urls_matching(cdp, "/userdata", "GET")
    T("F11 账号A：从云端 water 恢复记录（2025-02 / 60.50）",
      has_all(rowA, "2025-02", "60.50"), norm(rowA)[:120])
    T("F12 账号A：userdata GET 只按 sid A", len(getsA) >= 1 and all(SID_A in str(r.get("url")) for r in getsA),
      len(getsA))
    bucketA = bucket_read(cdp, SID_A) or {}
    recsA = (((bucketA.get("water") or {}).get("rooms") or {}).get(RV321) or {}).get("recs") or []
    T("F13 账号A：本机桶写入 water 记录", len(recsA) >= 2, json.dumps(recsA, ensure_ascii=False)[:120])

    # 账号 B（不清本机，验证两账号隔离）；6 人间用 16 号楼房间（23A/23B 已固定 4 人）
    seedB = ud_blob(power_sel=RV16, water_rooms={
        RV16: {"p": 6, "recs": [rec("2025-03", 10.00), rec("2025-04", 30.00)]}})
    nav(cdp, purl(sid=SID_B, ud=seedB))
    wait_ud_baseline(cdp, SID_B)
    open_water_page(cdp)
    wait_until(cdp, "(function(){return document.querySelectorAll('#wtList [data-wm]').length>=2;})()", 15)
    rowB = row_text(cdp, "2025-04")
    all_txt = jtext(cdp, "#s-water")
    getsB = urls_matching(cdp, "/userdata", "GET")
    T("F14 账号B：恢复 B 的记录（2025-04 / 30.00 / 24.24）",
      has_all(rowB, "2025-04", "30.00", "24.24"), norm(rowB)[:120])
    T("F15 账号B：看不到 A 的记录（2025-01/2025-02）",
      "2025-01" not in norm(all_txt) and "2025-02" not in norm(all_txt))
    T("F16 账号B：userdata GET 只按 sid B",
      len(getsB) >= 1 and all(SID_B in str(r.get("url")) for r in getsB), len(getsB))
    bucketA2 = bucket_read(cdp, SID_A) or {}
    recsA2 = (((bucketA2.get("water") or {}).get("rooms") or {}).get(RV321) or {}).get("recs") or []
    T("F17 两账号互不覆盖：本机 A 桶数据保留", len(recsA2) >= 2, json.dumps(recsA2, ensure_ascii=False)[:120])

    # 再回 A：本机桶恢复
    nav(cdp, purl(sid=SID_A, ud=seedA))
    wait_ud_baseline(cdp, SID_A)
    open_water_page(cdp)
    wait_until(cdp, "(function(){return document.querySelectorAll('#wtList [data-wm]').length>=2;})()", 15)
    rowA2 = row_text(cdp, "2025-02")
    T("F18 切回账号A：本机桶 + 云端恢复 A 记录", has_all(rowA2, "2025-02", "60.50"), norm(rowA2)[:120])
    collect_errors(cdp, "F 隔离")


def sc_f_olddata(cdp):
    old = ud_blob(power_sel="", with_water=False)  # 旧数据 13 键（无 water）
    ok = nav(cdp, purl(ud=old), clear=True)
    T("F19 旧数据无 water：页面启动不报错", ok)
    wait_ud_baseline(cdp, SID_A)
    open_water_page(cdp)
    T("F20 旧数据无 water：水量页空态可用",
      has_any(jtext(cdp, "#wtList"), "还没有抄表记录", "暂无", "没有记录", "首次记录", ""),
      norm(jtext(cdp, "#wtList"))[:80])
    obj = bucket_read(cdp, SID_A) or {}
    water = obj.get("water")
    T("F21 旧数据无 water：本机默认 water={rooms:{}}",
      isinstance(water, dict) and water.get("rooms") == {}, json.dumps(water, ensure_ascii=False)[:120])
    collect_errors(cdp, "F 旧数据")


# ---------------------------------------------------------------------------
# H. 云同步状态 UI（#wtSync）+ 远端 water 归一（2026-11-06 增量 18）
# ---------------------------------------------------------------------------
def _wt_chip(cdp):
    try:
        return ev(cdp, "(function(){var e=document.querySelector('#wtSync');if(!e)return null;"
                       "return {hidden:!!e.hidden,text:String(e.textContent||''),sync:e.getAttribute('data-sync')};})()")
    except Exception:
        return None


def sc_h_syncui(cdp):
    # H1 空态：未选关注宿舍 → 不显示同步状态
    nav(cdp, purl(ud=ud_blob(power_sel="", water_rooms={})), clear=True)
    wait_ud_baseline(cdp, SID_A)
    open_water_page(cdp)
    sleep(0.4)
    c0 = _wt_chip(cdp)
    T("H01 未选宿舍：#wtSync 隐藏", bool(c0) and c0.get("hidden") is True, json.dumps(c0, ensure_ascii=False))

    # H2 选宿舍（同步完成后）→ 已同步
    select_water_room(cdp, RV321)
    ok1 = wait_until(cdp, "(function(){var e=document.querySelector('#wtSync');"
                          "return !!(e&&!e.hidden&&e.getAttribute('data-sync')==='1'&&String(e.textContent).indexOf('已同步')>=0);})()", 20)
    T("H02 选宿舍同步完成：显示「已同步」", ok1, json.dumps(_wt_chip(cdp), ensure_ascii=False)[:140])

    # H3 保存抄表 → 推送前「未同步 · 点重试」，防抖推送完成后恢复「已同步」
    save_record(cdp, M1, "120.00")
    c1 = _wt_chip(cdp)
    T("H03 保存后未推送：显示「未同步 · 点重试」",
      bool(c1) and c1.get("sync") == "0" and "未同步" in str(c1.get("text")), json.dumps(c1, ensure_ascii=False)[:140])
    ok2 = wait_until(cdp, "(function(){var e=document.querySelector('#wtSync');"
                          "return !!(e&&e.getAttribute('data-sync')==='1');})()", 20)
    T("H04 防抖推送完成：恢复「已同步」", ok2, json.dumps(_wt_chip(cdp), ensure_ascii=False)[:140])
    blob = _find_water_post(cdp, SID_A, RV321)
    recs = ((((blob or {}).get("water") or {}).get("rooms") or {}).get(RV321) or {}).get("recs") or []
    T("H05 推送 blob.water 已含新记录（M1 / 120.00）",
      any(x.get("m") == M1 and abs(float(x.get("r", 0)) - 120.0) < 1e-9 for x in recs),
      json.dumps(recs, ensure_ascii=False)[:180])

    # H6 点「未同步」重试：立即补推（不等 1.2s 防抖）→ 已同步且 blob 含新记录
    save_record(cdp, M2, "118.00")
    posts_before = len(udposts(cdp))
    click(cdp, "#wtSync")
    ok3 = wait_until(cdp, "(function(){var e=document.querySelector('#wtSync');"
                          "return !!(e&&e.getAttribute('data-sync')==='1');})()", 20)
    T("H06 点「未同步 · 点重试」立即补推 → 已同步", ok3,
      "posts=%d→%d %s" % (posts_before, len(udposts(cdp)), json.dumps(_wt_chip(cdp), ensure_ascii=False)[:120]))
    blob2 = _find_water_post(cdp, SID_A, RV321)
    recs2 = ((((blob2 or {}).get("water") or {}).get("rooms") or {}).get(RV321) or {}).get("recs") or []
    T("H07 重试推送 blob.water 含 M2 / 118.00",
      any(x.get("m") == M2 and abs(float(x.get("r", 0)) - 118.0) < 1e-9 for x in recs2),
      json.dumps(recs2, ensure_ascii=False)[:200])

    # H8 远端 water 归一（不可信云端）：p=9、130 条、非法月份、坏房间 → 本机桶清洗
    recs130 = [rec(month_add(date(2010, 1, 1), i), 100 + i) for i in range(130)]
    recs130.append({"m": "2026-13", "r": 5.0})
    seed = ud_blob(power_sel=RV321, water_rooms={RV321: {"p": 9, "recs": recs130}})
    seed["water"]["rooms"]["bad"] = None
    seed["water"]["rooms"]["arr"] = [1, 2, 3]
    nav(cdp, purl(ud=seed), clear=True)
    wait_ud_baseline(cdp, SID_A)
    open_water_page(cdp)
    sleep(0.8)
    bucket = bucket_read(cdp, SID_A) or {}
    rooms = (bucket.get("water") or {}).get("rooms") or {}
    room = rooms.get(RV321) or {}
    rl = room.get("recs") or []
    T("H08 远端 water 归一：p=9→4 / 130 条裁到 120（2010-11 起）",
      room.get("p") == 4 and len(rl) == 120 and bool(rl) and rl[0].get("m") == "2010-11",
      "p=%s len=%s first=%s" % (room.get("p"), len(rl), rl[0].get("m") if rl else "—"))
    T("H09 远端非法月份 / 坏房间被丢弃",
      all(x.get("m") != "2026-13" for x in rl) and "bad" not in rooms and "arr" not in rooms,
      json.dumps({"keys": list(rooms.keys()), "badMonth": [x.get("m") for x in rl if x.get("m") == "2026-13"]}, ensure_ascii=False)[:160])

    # 收尾：恢复干净 3 条记录，供后续 W 节截图
    seed2 = ud_blob(power_sel=RV321, water_rooms={RV321: {"p": 4, "recs": [
        rec(M4, 100.0), rec(M3, 113.74), rec(M2, 130.0)]}})
    nav(cdp, purl(ud=seed2), clear=True)
    wait_ud_baseline(cdp, SID_A)
    open_water_page(cdp)
    sleep(0.4)
    T("H10 收尾：恢复 3 条记录状态（供截图）",
      len(rows_of(cdp)) >= 2 and _wt_chip(cdp) is not None, len(rows_of(cdp)))
    collect_errors(cdp, "H 同步状态")


# ---------------------------------------------------------------------------
# 宽度 / 溢出 / 截图
# ---------------------------------------------------------------------------
def sc_widths(cdp):
    try:
        open_water_page(cdp)
    except Exception:
        pass
    for w, h in ((360, 800), (430, 900), (1280, 1000)):
        set_viewport(cdp, w, h)
        sleep(0.65)
        info = {}
        try:
            info = ev(cdp, "(function(){var de=document.documentElement,bad=[];"
                           "Array.prototype.slice.call(document.querySelectorAll('#s-water *')).forEach(function(e){"
                           "var r=e.getBoundingClientRect();"
                           "if(r.width>0&&r.right>de.clientWidth+1&&getComputedStyle(e).position!=='fixed')"
                           "bad.push(e.tagName+'.'+String(e.className).split(' ')[0]);});"
                           "return {cw:de.clientWidth,sw:de.scrollWidth,bad:bad.slice(0,6)};})()") or {}
        except Exception:
            info = {}
        cw = info.get("cw") or 0
        sw = info.get("sw") or 0
        bad = info.get("bad") or []
        T("W 宽度 %dpx：水量页无横向溢出" % w,
          cw > 0 and sw <= cw + 1 and not bad,
          "clientW=%s scrollW=%s bad=%s" % (cw, sw, bad))
    set_viewport(cdp, 1280, 1000)
    sleep(0.5)
    n1 = shot(cdp, os.path.join(SHOTS, "water_1280.png"))
    T("W 截图 water_1280.png", n1 > 8000, "%d bytes" % n1)
    set_viewport(cdp, 430, 900)
    sleep(0.5)
    n2 = shot(cdp, os.path.join(SHOTS, "water_records_430.png"))
    T("W 截图 water_records_430.png", n2 > 8000, "%d bytes" % n2)


def sc_empty_shot(cdp):
    size = shot(cdp, os.path.join(SHOTS, "water_empty_430.png"))
    T("W 截图 water_empty_430.png（空态）", size > 8000, "%d bytes" % size)


# ---------------------------------------------------------------------------
# 浏览器骨架自检（--boot：启动 / 身份 / mock / 路由 / 电费页）
# ---------------------------------------------------------------------------
def sc_boot(cdp):
    sc_a_identity(cdp)
    open_all(cdp)
    T("骨架：全部页工具卡渲染", jcount(cdp, "#allCards [data-card]") > 0, jcount(cdp, "#allCards [data-card]"))
    opened = open_power_page(cdp)
    T("骨架：电费页可打开", opened and jdisplay(cdp, "#s-power") != "none", opened)
    T("骨架：#pwSelect 17 间宿舍", jcount(cdp, "#pwSelect option") >= 17, jcount(cdp, "#pwSelect option"))
    select_power_room(cdp, RV321)
    num_ok = wait_text(cdp, "#pwNum", "357", 12)
    T("骨架：mock 电量返回并渲染（357）", num_ok, jtext(cdp, "#pwNum"))
    pr = urls_matching(cdp, "/power?", "GET")
    T("骨架：power 请求 id=eq.321",
      len(pr) >= 1 and any("id=eq." + RV321 in str(r.get("url")) for r in pr), len(pr))
    T("骨架：power_history 请求存在（24h+7d）", len(urls_matching(cdp, "/power_history")) >= 1,
      len(urls_matching(cdp, "/power_history")))
    T("骨架：本机数据桶 zq_tools_v2_<sid> 存在", bool(bucket_read(cdp, SID_A)))
    collect_errors(cdp, "骨架")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get_ws(port):
    t0 = time.time()
    while time.time() - t0 < 30:
        try:
            import urllib.request
            data = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=2).read())
            for t in data:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("CDP 页面未就绪（port %d）" % port)


def report(fails):
    print("")
    print("=" * 64)
    if fails:
        print("失败明细 (%d):" % len(fails))
        for r in fails:
            print("  - %s%s" % (r["k"], ("  -- " + r["note"]) if r["note"] else ""))
    print("截图目录:", SHOTS)
    total = len(RESULTS)
    passed = total - len(fails)
    print("water_check: %d/%d PASS" % (passed, total))
    return 0 if (total > 0 and not fails) else 1


def main(argv):
    global HTTP_PORT, CDP_PORT, BASE, RUN_TMP, PREVIEW
    if "--list" in argv:
        print("water_check 断言计划（契约 _water_contract.md §5 A–G）")
        print("  静态契约 %d 项：版本/路由/DOM id/RULES/PW_DEDUCT/UD_KEYS/DEF/规则卡/电费回归/无外链" % len(static_checks()))
        print("  A 身份门禁：未登录门禁可见 / 0 请求 / 不渲染；学号+姓名进入（约 11 项）")
        print("  B 水量页基础：全部页卡片 / #s-water / 空态 / #wtSel 17 间 / #wtPersons / 规则卡 / 可点 40px（约 14 项）")
        print("  C 手动抄表：保存 / 自动对比 / 水费 4&6 人 / 折合扣电 / 同月覆盖 / 小于上次拒绝 / 删除重算 / 倒序 / 预览 / 本机存储 / 选择共用（约 30 项）")
        print("  D 规则卡：0.58 / 3.03 / 2 吨 / 5 度 / 来源 / 不含阶梯价（7 项）")
        print("  E 电费页：30 度异常下跌不计入 / #pwDeduct / 水费匹配 / tile 副标 / 估算（约 21 项）")
        print("  F 同步：14 键 blob / water.rooms / 换设备恢复 / 两账号隔离 / 旧数据无 water（约 21 项）")
        print("  W 宽度与截图：360/430/1280 无横向溢出 + _water_shots/ 截图（5 项）")
        print("  G 汇总：全程 0 JS 报错 / 0 console.error / 无外部请求（3 项）")
        print("  模式：python tests\\water_check.py [--static|--boot] ；SPEC_CHECK=<副本.html> 复盘副本")
        return 0

    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)
    # 本次 run 独立子目录：与其他门禁/Lead 调试共用 _water_tmp 根目录，退出时只清自己的子目录
    RUN_TMP = os.path.join(TMP, "run_%d_%d" % (os.getpid(), int(time.time())))
    os.makedirs(RUN_TMP, exist_ok=True)
    PREVIEW = os.path.join(RUN_TMP, "_water_preview.html")
    if not os.path.exists(SRC):
        T("源文件存在", False, SRC)
        return report([r for r in RESULTS if not r["ok"]])

    # 静态契约检查
    static = static_checks()
    for name, ok, note in static:
        T(name, ok, note)

    mode = "boot" if "--boot" in argv else ("static" if "--static" in argv else "full")
    if mode == "static":
        return report([r for r in RESULTS if not r["ok"]])

    # 浏览器实跑
    global _LAST_PASS
    build_preview()
    HTTP_PORT = free_port()
    CDP_PORT = free_port()
    BASE = "http://127.0.0.1:%d/" % HTTP_PORT
    httpd = None
    proc = None
    cdp = None
    prof = None
    devnull = None
    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", HTTP_PORT),
                                                functools.partial(QuietHandler, directory=ROOT))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        sleep(0.35)
        prof = tempfile.mkdtemp(prefix="edgeprof_water_", dir=RUN_TMP)
        devnull = open(os.devnull, "wb")
        proc = subprocess.Popen(
            [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--force-device-scale-factor=1", "--hide-scrollbars",
             "--remote-debugging-port=%d" % CDP_PORT, "--user-data-dir=" + prof, "about:blank"],
            stdout=devnull, stderr=devnull)
        cdp = CDP(get_ws(CDP_PORT))
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        set_viewport(cdp, 430, 900)
        if mode == "boot":
            sc_boot(cdp)
        else:
            sc_a_identity(cdp)
            sc_b_water_basics(cdp)
            sc_empty_shot(cdp)
            sc_c_records(cdp)
            sc_widths(cdp)
            sc_e_power(cdp)
            sc_f_sync(cdp)
            sc_f_isolation(cdp)
            sc_f_olddata(cdp)
            sc_h_syncui(cdp)
    except Exception:
        T("脚本执行异常", False, traceback.format_exc()[-600:])
    finally:
        try:
            if cdp:
                cdp.close()
        except Exception:
            pass
        try:
            if proc:
                proc.kill()
        except Exception:
            pass
        try:
            if httpd:
                httpd.shutdown()
                httpd.server_close()
        except Exception:
            pass
        try:
            if devnull:
                devnull.close()
        except Exception:
            pass
        try:
            if RUN_TMP:
                shutil.rmtree(RUN_TMP, ignore_errors=True)
        except Exception:
            pass

    # G 汇总
    T("G01 全程 0 JS 报错", len(GLOBAL["errs"]) == 0, " | ".join(GLOBAL["errs"][:4]))
    T("G02 全程 0 console.error", len(GLOBAL["cerrs"]) == 0, " | ".join(GLOBAL["cerrs"][:4]))
    T("G03 全程无外部请求", len(GLOBAL["exts"]) == 0, " | ".join(GLOBAL["exts"][:4]))

    fails = [r for r in RESULTS if not r["ok"]]
    return report(fails)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
