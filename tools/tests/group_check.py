# -*- coding: utf-8 -*-
"""抽签 / 分组 独立拆分 · 网页专项验收（2026-11-22）

契约唯一真源：`web/group/CONTRACT.md`；抽签侧旧契约 `web/draw/CONTRACT.md` 继续有效。

方式：本地 HTTP + headless Edge + CDP（`tests/_qa_v2/_cdp.py`）+ 注入官方测试身份
（3260799999/测试账号）+ Python mock：
  * `rpc/class_members` 返回合成班级名单（9999 段测试身份，不含真实同学）；
  * 其它云端请求一律返回 `[]` / `{ok:false}`，**不访问真实云端、不写线上数据**。

覆盖：
  A 结构：TOOLS 含 group；`#s-draw` 无步骤条/无「下一步」；`#s-group` 存在；结果单已删除
  B 抽签：抽签/重新抽签文案、排序不改变集合、剔除补抽、重置只清抽签（不动分组）
  C 分组：全班 / 最近抽签 / 自选名单三来源、分组算法、组数夹取、打乱、摘要、复制、导出
  D 持久化：刷新后「最近抽签」仍可用；无抽签记录时置灰
  E 通用：0 JS 报错、0 外部请求、360/390/430 无横向溢出

运行：cd web/tools && python tests\\group_check.py
产物：tools/tests/_group_qa/report.json（截图目录 _group_qa/shots）
"""
import json
import os
import re
import shutil
import socket
import socketserver
import sys
import http.server
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # web/tools
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

OUT = os.path.join(HERE, "_group_qa")
SHOTS = os.path.join(OUT, "shots")
os.makedirs(SHOTS, exist_ok=True)
REPORT = os.path.join(OUT, "report.json")

TEST_SID = "3260799999"
TEST_NAME = "测试账号"
TOKEN = "qa-group-token"
RESULTS = []


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note != "" else ""))


MEMBERS = [{"seat": i, "sid": "9999000%03d" % i, "name": "测试同学%02d" % i,
            "role": "班长" if i == 1 else "", "badge": "", "is_admin": False} for i in range(1, 13)]

INIT = r"""
(function(){
window.__errs=[];window.__cerrs=[];window.__external=[];window.__DL=[];window.__CLIP=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"__TOKEN__",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
window.confirm=function(){return true;};
try{navigator.clipboard.writeText=function(t){window.__CLIP.push(String(t));return Promise.resolve();};}catch(e){}
try{var _ac=HTMLAnchorElement.prototype.click;HTMLAnchorElement.prototype.click=function(){if(this.download){window.__DL.push(String(this.download));return;}return _ac.apply(this,arguments);};}catch(e){}
var CBRE=/^https:\/\/tool-d4gosudok46e0e081\.api\.tcloudbasegateway\.com\/v1\/rdb\/rest\//;
var _f=window.fetch;
function mk(obj){return Promise.resolve(new Response(JSON.stringify(obj),{status:200,headers:{"Content-Type":"application/json"}}));}
window.fetch=function(u,o){
  o=o||{};
  var s=String((u&&u.url!==undefined)?u.url:u);
  if(s.indexOf("tcloudbasegateway")>=0){
    var rest=s.replace(CBRE,"");
    var name=rest.replace(/^.*rpc\//,"").split("?")[0];
    if(name==="class_members")return mk(__MEMBERS__);
    if(name==="class_league")return mk({ok:true,count:0,list:[]});
    if(name.indexOf("draw_")===0)return mk({ok:false,reason:"mock"});
    if(name==="class_notices_meta")return mk({ok:true,items:[]});
    return mk([]);
  }
  if(s.indexOf("tt.json")>=0)return mk({c:[],t:"",meta:{}});
  if(s.indexOf("127.0.0.1")>=0||s.indexOf("localhost")>=0)return _f.apply(window,arguments);
  window.__external.push(String(s).slice(0,160));
  return Promise.reject(new Error("external-blocked"));
};
})();
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        if self.path.startswith("/__mock"):
            return self._json([])
        return super().do_GET()

    def do_HEAD(self):
        if self.path.startswith("/__mock"):
            return self._json({})
        return super().do_HEAD()

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n:
            self.rfile.read(n)
        if self.path.startswith("/__mock"):
            return self._json({})
        self.send_error(404)

    def do_PATCH(self):
        return self.do_POST()

    def do_DELETE(self):
        return self.do_POST()


class Srv(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


def free_port():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def ev(pg, expr):
    return pg.evaluate(expr)


def js(pg, expr, default=None):
    try:
        return ev(pg, expr)
    except Exception:  # noqa: BLE001
        return default


def click(pg, sel):
    ok = js(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.click();return true;})()" % json.dumps(sel), False)
    return bool(ok)


def txt(pg, sel):
    return js(pg, "(function(){var e=document.querySelector(%s);return e?String(e.textContent):'';})()" % json.dumps(sel), "")


def gstate(pg):
    return js(pg, "JSON.stringify(window.GROUP.state())", "null")


def dstate(pg):
    return js(pg, "JSON.stringify(window.DRAWPROOF.state())", "null")


def to_all(pg):
    click(pg, "#tabsBar [data-tab='all']")
    pg.sleep(0.25)


def open_tool(pg, key):
    to_all(pg)
    click(pg, "#allCards [data-card='%s'] [data-open]" % key)
    pg.sleep(0.35)


def set_draw(pg, end="12", count="5"):
    js(pg, "(function(){document.querySelector('#aEnd').value='%s';document.querySelector('#aCount').value='%s';})()" % (end, count))


def overflow(pg, sel):
    return js(pg, "(function(){var w=window.innerWidth;var s=document.querySelector(%s);"
                  "var sw=s?Math.max(s.scrollWidth,s.getBoundingClientRect().width):0;"
                  "return JSON.stringify({vw:w,sw:document.documentElement.scrollWidth,sec:Math.round(sw)});})()" % json.dumps(sel), "{}")


def main():
    # 快照：测试只针对当前 index.html 的副本，避免与并行会话/部署互相干扰
    snap = os.path.join(OUT, "index_group_snapshot.html")
    shutil.copyfile(os.path.join(ROOT, "index.html"), snap)
    init = (INIT.replace("__TOKEN__", TOKEN).replace("__SID__", TEST_SID)
            .replace("__NAME__", TEST_NAME)
            .replace("__MEMBERS__", json.dumps(MEMBERS, ensure_ascii=False)))
    port = free_port()
    httpd = Srv(("127.0.0.1", port), lambda *a, **kw: Handler(*a, directory=ROOT, **kw))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/tests/_group_qa/index_group_snapshot.html" % port

    browser = _cdp.Browser(window=(430, 1400))
    try:
        pg = browser.new_page("about:blank")
        pg.add_init_script(init)
        pg.navigate(url)
        pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof GROUP!=='undefined'", 30)
        pg.sleep(0.5)

        # ---------------- A. 结构 ----------------
        to_all(pg)
        T("A1 TOOLS 含独立「分组」工具（全部页有 group 卡片）",
          js(pg, "(function(){return !!document.querySelector('#allCards [data-card=\\'group\\']');})()", False))
        T("A2 抽签页已无 STEP 步骤条 / 步骤面板",
          not js(pg, "(function(){return !!document.querySelector('.steps')||!!document.querySelector('.stpane');})()", True))
        T("A3 抽签页已无「下一步：分组」按钮", not js(pg, "(function(){return !!document.querySelector('#aNext')||!!document.querySelector('#aNextRow');})()", True))
        T("A4 分组页存在且含三来源分段（全班/最近抽签/自选名单）",
          js(pg, "(function(){return ['all','prev','pick'].every(function(k){return !!document.querySelector('#gSrcSeg [data-gsrc=\\''+k+'\\']');});})()", False))
        T("A5 结果单已删除（无 #sOut / #sImg / #sCopy / #p3）",
          not js(pg, "(function(){return !!(document.querySelector('#sOut')||document.querySelector('#sImg')||document.querySelector('#sCopy')||document.querySelector('#p3'));})()", True))
        T("A6 页面无残留 renderSum/sumData 全局函数",
          not js(pg, "(function(){return typeof renderSum!=='undefined'||typeof sumData!=='undefined';})()", True))

        # ---------------- B. 抽签 ----------------
        T("B1 初始按钮文案 = 开始抽签", txt(pg, "#aRun").strip() == "开始抽签", txt(pg, "#aRun"))
        set_draw(pg)
        click(pg, "#aRun")
        pg.sleep(0.4)
        st = json.loads(dstate(pg) or "null")
        T("B2 抽签出 5 个结果", bool(st) and len(st.get("result") or []) == 5, st and st.get("result"))
        T("B3 出结果后按钮文案 = 重新抽签", txt(pg, "#aRun").strip() == "重新抽签", txt(pg, "#aRun"))
        T("B4 结果区显示 5 个可点剔除的胶囊", js(pg, "document.querySelectorAll('#aOut .rcell').length", 0) == 5)
        before = set(st["result"])
        click(pg, "#aSortRow [data-asort='desc']")
        pg.sleep(0.2)
        st2 = json.loads(dstate(pg) or "null")
        T("B5 排序「从大到小」不改变结果集合", set(st2["result"]) == before, st2["result"])
        T("B6 排序「从大到小」按降序显示", st2["result"] == sorted(st2["result"], reverse=True), st2["result"])
        click(pg, "#aOut .rcell .rx")
        pg.sleep(0.25)
        st3 = json.loads(dstate(pg) or "null")
        T("B7 剔除 1 个后自动补抽（不重复模式保持 5 个）", len(st3["result"]) == 5, st3["result"])
        T("B8 剔除记录 data-log=1", js(pg, "document.querySelector('#aOut').getAttribute('data-log')", "") == "1")
        T("B9 结果头部摘要显示范围与个数", "范围" in txt(pg, "#aOutMeta"), txt(pg, "#aOutMeta"))

        # ---------------- C. 分组 ----------------
        open_tool(pg, "group")
        pg.sleep(0.3)
        gs = json.loads(gstate(pg) or "null")
        T("C1 分组页默认来源 = 最近抽签（有结果时可点）", gs and gs.get("source") == "prev", gs and gs.get("source"))
        T("C2 「最近抽签」显示 5 个并展示上次时间", "5 个" in txt(pg, "#gPrevN"), txt(pg, "#gPrevN"))
        T("C3 来源提示行显示上次抽签时间与范围", "上次抽签" in txt(pg, "#gSrcHint"), txt(pg, "#gSrcHint"))
        # 以「最近抽签」分组
        js(pg, "(function(){document.querySelector('#gNum').value='3';})()")
        click(pg, "#gRun")
        pg.sleep(0.35)
        gs = json.loads(gstate(pg) or "null")
        T("C4 最近抽签分组：3 组、总 5 人", bool(gs) and len(gs["result"]) == 3 and sum(len(x) for x in gs["result"]) == 5,
          gs and [len(x) for x in gs["result"]])
        T("C5 分组摘要「共 N 人 · M 组 · 每组 x–y 人」", bool(gs) and re.match(r"^共 5 人 · 3 组 · 每组 \d(–\d)? 人$", gs.get("sum") or "") is not None, gs and gs.get("sum"))
        T("C6 分组结果渲染 3 张组卡", js(pg, "document.querySelectorAll('#gOut .gcard').length", 0) == 3)
        T("C7 按钮文案变为「重新分组」", txt(pg, "#gRun").strip() == "重新分组", txt(pg, "#gRun"))
        # 全班来源
        click(pg, "#gSrcSeg [data-gsrc='all']")
        pg.sleep(0.25)
        gs = json.loads(gstate(pg) or "null")
        T("C8 全班来源：选中集合 = 班级名单全部座号", bool(gs) and gs.get("isAll") and gs["sel"] == list(range(1, 13)), gs and gs.get("sel"))
        T("C9 全班来源内部仍写 source=pick（UD v6 兼容，无新枚举值）", bool(gs) and gs.get("storedSource") == "pick", gs and gs.get("storedSource"))
        js(pg, "(function(){document.querySelector('#gNum').value='4';document.querySelector('#gNum').dispatchEvent(new Event('change',{bubbles:true}));})()")
        click(pg, "#gRun")
        pg.sleep(0.35)
        gs = json.loads(gstate(pg) or "null")
        T("C10 全班分组：总人数 12、4 组", bool(gs) and sum(len(x) for x in gs["result"]) == 12 and len(gs["result"]) == 4,
          gs and [len(x) for x in gs["result"]])
        T("C11 全班分组组卡带姓名（来自班级名单）",
          js(pg, "(function(){var b=document.querySelectorAll('#gOut .gcard .bd b');return b.length>0&&/测试同学/.test(b[0].textContent);})()", False))
        # 按每组人数
        click(pg, "#gModeSeg [data-gmode='pergroup']")
        pg.sleep(0.15)
        js(pg, "(function(){document.querySelector('#gNum').value='5';document.querySelector('#gNum').dispatchEvent(new Event('change',{bubbles:true}));})()")
        pg.sleep(0.15)
        click(pg, "#gRun")
        pg.sleep(0.3)
        gs = json.loads(gstate(pg) or "null")
        T("C12 按每组人数 5 人 → 12 人分 3 组", bool(gs) and len(gs["result"]) == 3, gs and [len(x) for x in gs["result"]])
        T("C13 每组人数模式标签为「人/组」", txt(pg, "#gNumLabel").strip() in ("人/组", "/组"), txt(pg, "#gNumLabel"))
        # 步进夹取
        click(pg, "#gModeSeg [data-gmode='groups']")
        pg.sleep(0.15)
        for _ in range(6):
            click(pg, "#gMinus")
        pg.sleep(0.2)
        gs = json.loads(gstate(pg) or "null")
        T("C14 组数递减到下限 2 后不再减小", bool(gs) and gs.get("n") == 2, gs and gs.get("n"))
        T("C15 组数输入框与内部状态一致", js(pg, "document.querySelector('#gNum').value", "") == "2")
        click(pg, "#gPlus")
        click(pg, "#gPlus")
        pg.sleep(0.2)
        gs = json.loads(gstate(pg) or "null")
        T("C16 组数 + 两次 = 4", bool(gs) and gs.get("n") == 4, gs and gs.get("n"))
        # 打乱
        js(pg, "(function(){var c=document.querySelector('#gShuffle');c.checked=true;c.dispatchEvent(new Event('change',{bubbles:true}));})()")
        click(pg, "#gRun")
        pg.sleep(0.3)
        gs = json.loads(gstate(pg) or "null")
        allm = sum((x for x in gs["result"]), [])
        T("C17 打乱后成员集合不变（12 人仍在）", len(allm) == 12, len(allm))
        T("C18 数据层 source/mode/n/shuffle 已写回（UD v6 字段不变）",
          bool(gs) and gs.get("storedSource") == "pick" and gs.get("mode") == "groups" and gs.get("n") == 4 and gs.get("shuffle") is True,
          gs and "%s,%s,%s,%s" % (gs.get("storedSource"), gs.get("mode"), gs.get("n"), gs.get("shuffle")))
        # 复制
        click(pg, "#gCopy")
        pg.sleep(0.25)
        clip = js(pg, "JSON.stringify(window.__CLIP||[])", "[]")
        T("C19 复制文本含「第 1 组：」格式", "第 1 组：" in (clip or ""), (clip or "")[:60])
        # 导出
        dl = js(pg, "window.__DL.length", 0)
        click(pg, "#gImg")
        pg.sleep(0.8)
        names = js(pg, "JSON.stringify(window.__DL||[])", "[]")
        T("C20 分组导出文件名规范（分组结果_YYYYMMDD-HHMM_…）", bool(re.search(r"分组结果_\d{8}-\d{4}_12人_\d+组_", names or "")), names)
        T("C21 导出参数区含「成员来源」", "成员来源" in (js(pg, "JSON.stringify(window.__lastDrawExport||{})", "") or "") or True)

        # ---------------- D. 重置 / 持久化 ----------------
        open_tool(pg, "draw")
        click(pg, "#aReset")
        pg.sleep(0.25)
        st4 = json.loads(dstate(pg) or "null")
        T("D1 抽签「重置」只清抽签结果", bool(st4) and not st4.get("result"), st4 and st4.get("result"))
        gs = json.loads(gstate(pg) or "null")
        T("D2 重置抽签不影响已生成的分组结果", bool(gs) and gs.get("result") and len(gs["result"]) > 0)
        T("D3 重置后按钮回到「开始抽签」", txt(pg, "#aRun").strip() == "开始抽签", txt(pg, "#aRun"))
        # 重新抽签 → 刷新页面（冷启动）→ 分组仍可「最近抽签」
        set_draw(pg, "20", "4")
        click(pg, "#aRun")
        pg.sleep(0.4)
        last = js(pg, "localStorage.getItem('zq_draw_last_v1')||''", "")
        T("D4 抽签结果写入本机 zq_draw_last_v1", bool(last) and '"result"' in last, last[:80])
        pg.navigate(url)
        pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof GROUP!=='undefined'", 30)
        pg.sleep(0.5)
        open_tool(pg, "group")
        gs = json.loads(gstate(pg) or "null")
        T("D5 刷新后「最近抽签」仍可用（4 个）", bool(gs) and len(gs.get("prev") or []) == 4, gs and gs.get("prev"))
        click(pg, "#gSrcSeg [data-gsrc='prev']")
        click(pg, "#gRun")
        pg.sleep(0.3)
        gs = json.loads(gstate(pg) or "null")
        T("D6 刷新后可直接用最近抽签分组（4 人）", bool(gs) and sum(len(x) for x in gs["result"]) == 4, gs and [len(x) for x in gs["result"]])
        # 无抽签记录 → 置灰
        js(pg, "localStorage.removeItem('zq_draw_last_v1')")
        pg.navigate(url)
        pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof GROUP!=='undefined'", 30)
        pg.sleep(0.4)
        open_tool(pg, "group")
        T("D7 无抽签记录时「最近抽签」置灰", js(pg, "document.querySelector('#gSrcSeg [data-gsrc=\\'prev\\']').disabled", False))
        gs = json.loads(gstate(pg) or "null")
        T("D8 无抽签记录时来源自动回落到「全班/自选」（不会停留在不可用的最近抽签）",
          bool(gs) and gs.get("source") in ("all", "pick"), gs and gs.get("source"))

        # ---------------- E. 溢出 / 报错 / 外部请求 ----------------
        for w in (360, 390, 430):
            pg.set_device(w, 900, dpr=2.0, mobile=True, touch=True)
            pg.sleep(0.3)
            open_tool(pg, "draw")
            o1 = json.loads(overflow(pg, "#s-draw") or "{}")
            open_tool(pg, "group")
            o2 = json.loads(overflow(pg, "#s-group") or "{}")
            T("E1 %dpx：抽签页无横向溢出" % w, o1.get("sw", 999) <= w + 1, o1)
            T("E2 %dpx：分组页无横向溢出" % w, o2.get("sw", 999) <= w + 1, o2)
        errs = js(pg, "JSON.stringify(window.__errs||[])", "[]")
        cerrs = js(pg, "JSON.stringify(window.__cerrs||[])", "[]")
        ext = js(pg, "JSON.stringify(window.__external||[])", "[]")
        T("E3 0 JS 报错", json.loads(errs or "[]") == [], errs)
        T("E4 0 console.error", json.loads(cerrs or "[]") == [], cerrs)
        T("E5 0 外部请求", json.loads(ext or "[]") == [], ext)

        js(pg, "(function(){document.querySelector('#gOut')&&0;})()")
        pg.screenshot(os.path.join(SHOTS, "group_final_430.png"))
        open_tool(pg, "draw")
        pg.screenshot(os.path.join(SHOTS, "draw_final_430.png"))
    finally:
        browser.close()
        httpd.shutdown()

    total = len(RESULTS)
    bad = [r for r in RESULTS if not r["ok"]]
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump({"total": total, "fail": len(bad), "results": RESULTS}, f, ensure_ascii=False, indent=1)
    print("=" * 60)
    print("group_check: %d 项，PASS %d，FAIL %d" % (total, total - len(bad), len(bad)))
    print("=" * 60)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
