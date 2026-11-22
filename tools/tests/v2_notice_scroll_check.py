# -*- coding: utf-8 -*-
"""通知页「下滑时不停刷新」专项（2026-11-22 用户反馈）。

用户原话：「修复网页端通知下滑时会不停刷新，没有连贯的体验」。

根因（修复前）：
  · lite 列表里的图片/附件占位由 IntersectionObserver 进入视口时自动请求单行完整 body；
  · 回填函数 __zqHydrate 收到 body 后调 **整表 render()** 再 scrollTo 恢复位置 —— 每回填一张图
    就重绘整张通知列表（69 组 DOM 全换掉、data URI 重新解码），滚动过程中连续触发 → 看起来「不停刷新」；
  · 期次卡（长期安排 `<base>@occ:YYYYMMDD`）更严重：render() 每次都从基础组重新克隆，
    回填只改克隆 → 下次重绘又变回「预览加载中」→ 再请求 → 反复重绘（上限 AUTO_PREVIEW.max=18）。

修复口径：
  · 回填只替换该条 `.gitem`（不整表重绘），并把完整 items 回填到 **基础组**，期次卡重绘后不再退化；
  · 视口自动回填按「gid|idx」去重，失败 15s 后允许重试；
  · 下滑过程中 0 次整表重绘 / 0 次 #list 重建，图片仍自动出现，滚动位置不回跳。

本脚本用 power_check 的测试身份预览页 + mock 云端（10 条普通通知 + 1 条长期安排，各带 1 张懒加载图片），
真实 wheel 输入下滑，统计 iframe 内 render()/#list 重建次数。只读，不连云端。

运行：
  G:\\ClassTools\\briefdesk\\venv\\Scripts\\python.exe G:\\ClassTools\\web\\tools\\tests\\v2_notice_scroll_check.py
"""
import http.server
import importlib.util
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
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
import _cdp  # noqa: E402

spec = importlib.util.spec_from_file_location("pc", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

AN = "[[CLASS_NOTICE_V1]]"
IMG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
       "z8BQDwAFgwJ/lK3Q6wAAAABJRU5ErkJggg==")
NOW_FIX = "2026-11-22T21:40:00+08:00"   # 周日 21:40；长期安排设周日 22:00 → 期次窗口内
N_NORMAL = 10
RECUR_ID = "g_scroll_recur"
RECUR_ROW = "auto_scroll_%02d" % N_NORMAL   # 长期安排在行序里是第 N_NORMAL 条
RESULTS = []


def T(name, ok, note=""):
    RESULTS.append(bool(ok))
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


def free_port():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def mk_group(i):
    gid = "g_scroll_%02d" % i
    return {
        "id": gid, "cat": "通知",
        "title": "滚动测试通知 %02d" % i,
        "summary": "下滑时不应重绘整张列表。",
        "aiSummary": "下滑时不应重绘整张列表。",
        "aiPoints": ["图片进入视口自动回填", "滚动位置保持不动"],
        "group": "测试群", "source": "微信群 · 测试群",
        "publishedAt": "2026-11-22T%02d:00:00+08:00" % (i % 12 + 1),
        "items": [
            {"kind": "text", "label": "原始消息", "time": "11-22 %02d:00" % (i % 12 + 1),
             "from": "测试",
             "text": ("这一段是用于撑高卡片的测试正文，覆盖通知原文与补充说明。"
                      "下滑经过多张卡片时，列表 DOM 不应被整体替换，否则会出现闪烁与滚动跳位。\n"
                      "第二段继续占位，保证每张卡片有足够高度，滚动能覆盖多张懒加载图片。")},
            {"kind": "img", "caption": "测试图片 %02d" % i, "lazy": True,
             "time": "11-22 %02d:00" % (i % 12 + 1),
             "note": "通知图片 · 预览加载中…"},
        ],
    }


def mk_recur_group():
    return {
        "id": RECUR_ID, "cat": "通知",
        "title": "长期安排 · 周日卫生检查（滚动测试）",
        "summary": "每周日晚提交卫生照片。",
        "aiSummary": "每周日晚提交卫生照片。",
        "aiPoints": ["周日晚 22:00 前提交"],
        "group": "测试群", "source": "微信群 · 测试群",
        "publishedAt": "2026-11-20T10:00:00+08:00",
        "recurrence": {"freq": "weekly", "weekday": 0, "time": "22:00"},
        "items": [
            {"kind": "text", "label": "原始消息", "time": "11-20 10:00", "from": "测试",
             "text": "每周日晚 22:00 前把卫生照片发到群里。"},
            {"kind": "img", "caption": "卫生检查示例", "lazy": True,
             "time": "11-20 10:00", "note": "通知图片 · 预览加载中…"},
        ],
    }


def full_of(g):
    f = json.loads(json.dumps(g, ensure_ascii=False))
    for it in f["items"]:
        if it.get("kind") == "img":
            it.pop("lazy", None)
            it["src"] = IMG
    return f


GROUPS = [mk_group(i) for i in range(N_NORMAL)] + [mk_recur_group()]
FULL_ROWS = []
META_ROWS = []
for i, g in enumerate(GROUPS):
    rid = "auto_scroll_%02d" % i
    ts = 1763000000000 + i * 1000
    META_ROWS.append({"id": rid, "title": g["title"], "body": AN + json.dumps(g, ensure_ascii=False),
                      "archived": False, "hidden": False, "edited_at": 0, "ts": ts})
    FULL_ROWS.append({"id": rid, "title": g["title"],
                      "body": AN + json.dumps(full_of(g), ensure_ascii=False),
                      "archived": False, "hidden": False, "edited_at": 0, "ts": ts})
FULL_BY_ID = {r["id"]: r for r in FULL_ROWS}
SIG_ROWS = [{"id": r["id"], "ts": r["ts"], "hidden": False, "edited_at": 0} for r in META_ROWS]

WRAP = r"""
<script>
(function(){
  window.__bodyCalls={};window.__bodyTotal=0;
  var prev=window.fetch;
  function resp(obj){return Promise.resolve({ok:true,status:200,
    json:function(){return Promise.resolve(obj);},
    text:function(){return Promise.resolve(JSON.stringify(obj));}});}
  window.fetch=function(u,o){
    o=o||{};var s=String((u&&u.url!==undefined)?u.url:u);
    if(s.indexOf("rpc/class_notices_meta")>=0)return resp(__META__);
    if(s.indexOf("/notices?select=*&id=eq.")>=0){
      var id="";try{id=decodeURIComponent(s.split("id=eq.")[1].split("&")[0]);}catch(e){}
      window.__bodyCalls[id]=(window.__bodyCalls[id]||0)+1;window.__bodyTotal++;
      return resp(__FULL__[id]?[__FULL__[id]]:[]);
    }
    if(s.indexOf("/notices?select=id,ts")>=0)return resp(__SIG__);
    if(s.indexOf("/notices")>=0)return resp(__META__);
    return prev.apply(this,arguments);
  };
})();
</script>
"""

PROBE_JS = r"""
(function(){
  var f=document.querySelector('#noticeHost iframe');
  if(!f||!f.contentWindow)return 'noiframe';
  var W=f.contentWindow;
  if(W.__ntProbe)return 'already';
  var p={render:0,list:0};
  W.__ntProbe=p;
  if(typeof W.render==='function'){
    var orig=W.render;
    W.render=function(){p.render++;return orig.apply(W,arguments);};
  }
  var list=W.document.getElementById('list');
  if(list&&W.MutationObserver){
    p.mo=new W.MutationObserver(function(ms){
      for(var i=0;i<ms.length;i++){
        if(ms[i].type==='childList'&&ms[i].target===list)p.list++;
      }
    });
    p.mo.observe(list,{childList:true,subtree:false});
  }
  p.y0=W.scrollY||0;
  return 'ok';
})()
"""

PROBE_READ = r"""
(function(){
  var W=document.querySelector('#noticeHost iframe').contentWindow,p=W.__ntProbe||{};
  return {render:p.render||0,list:p.list||0,
          body:window.__bodyTotal||0,calls:window.__bodyCalls||{},
          y:Math.round(W.scrollY||0),
          imgs:W.document.querySelectorAll('.imgrow img').length,
          lazy:W.document.querySelectorAll('.imgrow.lazyimg').length,
          groups:W.GROUPS.length,
          occ:!!W.document.querySelector('#list article.gcard.occ')};
})()
"""


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        # 课表同源快照：预览页没有 tt.json，返回空对象避免无关 404 干扰「0 JS/console 报错」
        if self.path.startswith("/tt.json"):
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return http.server.SimpleHTTPRequestHandler.do_GET(self)


def serve(port):
    h = lambda *a, **kw: Q(*a, directory=HERE, **kw)
    s = socketserver.ThreadingTCPServer(("127.0.0.1", port), h)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def scroll_into_view(p, selector, extra_wait=1.1):
    """滚到目标卡片（真实 wheel 之后仍用 scrollIntoView 定位，保证稳定命中）。"""
    p.evaluate("(function(){var f=document.querySelector('#noticeHost iframe');"
               "var c=f.contentDocument.querySelector(%s);if(c)c.scrollIntoView({block:'center'});})()"
               % json.dumps(selector))
    p.sleep(extra_wait)


def main():
    port = free_port()
    s = serve(port)
    b = None
    page = None
    preview = "_notice_scroll_preview.html"
    try:
        pc.build_previews()
        src = open(os.path.join(HERE, pc.PREVIEW), encoding="utf-8").read()
        inject = (WRAP.replace("__META__", json.dumps(META_ROWS, ensure_ascii=False))
                  .replace("__SIG__", json.dumps(SIG_ROWS, ensure_ascii=False))
                  .replace("__FULL__", json.dumps(FULL_BY_ID, ensure_ascii=False)))
        src = src.replace("</head>", inject + "</head>", 1)
        open(os.path.join(HERE, preview), "w", encoding="utf-8").write(src)

        b = _cdp.Browser(edge=pc.EDGE)
        page = b.new_page()
        page.set_device(390, 880, dpr=2.0, mobile=True, touch=True)
        ud = pc.ud_blob("4-23A---321")
        q = ("sid=%s&name=%s&ud=%s" % (pc.SID_A, urllib.parse.quote(pc.NAME),
                                       urllib.parse.quote(json.dumps(ud, ensure_ascii=False), safe="")))
        page.navigate("http://127.0.0.1:%d/%s?%s" % (port, preview, q))
        page.wait_load(30)

        T("A0 预览页启动", page.wait_for("!!document.querySelector('#idChipTxt')", 20))
        page.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"nt\"]');if(b)b.click();'x'")
        T("A1 通知页打开",
          page.wait_for("document.querySelector('#s-nt') && document.querySelector('#s-nt').classList.contains('on')", 10))
        T("A2 通知 iframe 出现", page.wait_for("!!document.querySelector('#noticeHost iframe')", 15))
        T("A3 模板渲染 %d 组" % len(GROUPS),
          page.wait_for("(function(){var f=document.querySelector('#noticeHost iframe');if(!f||!f.contentWindow)return false;"
                        "try{return !!f.contentWindow.GROUPS&&f.contentWindow.GROUPS.length>=%d;}catch(e){return false;}})()"
                        % len(GROUPS), 25))
        # 固定时钟到期次窗口内（周日 21:40 → 周日 22:00 的期次）
        page.evaluate("(function(){var W=document.querySelector('#noticeHost iframe').contentWindow;"
                      "if(W&&W.__zqTest&&W.__zqTest.setNow)W.__zqTest.setNow(Date.parse('%s'));})()" % NOW_FIX)
        page.sleep(1.6)   # 等首屏自动回填结束，再装探针（只统计「之后」的重绘）

        T("A4 探针安装", page.evaluate(PROBE_JS) == "ok")
        base = page.evaluate(PROBE_READ)
        T("A5 首屏懒加载图片占位存在（回填待进入视口触发）", base.get("lazy", 0) >= 1, base)
        T("A6 iframe 根节点禁用滚动链接（overscroll-behavior-y: contain，防下拉刷新/整页回弹）",
          page.evaluate("(function(){var W=document.querySelector('#noticeHost iframe').contentWindow;"
                        "return W.getComputedStyle(W.document.documentElement).overscrollBehaviorY;})()") == "contain")

        # ---- 真实 wheel 下滑：多张图片依次进入视口 ----
        for _ in range(9):
            page.wheel(195, 470, 420)
            page.sleep(0.32)
        page.sleep(1.2)
        mid = page.evaluate(PROBE_READ)
        print("probe(mid):", json.dumps(mid, ensure_ascii=False))
        T("B1 下滑后图片继续自动回填（视觉不倒退）", mid.get("imgs", 0) > base.get("imgs", 0), 
          "imgs %s -> %s" % (base.get("imgs"), mid.get("imgs")))
        T("B2 下滑过程中 0 次整表 render()", mid.get("render") == 0, mid)
        T("B3 下滑过程中 0 次 #list 重建", mid.get("list") == 0, mid)
        T("B4 下滑后滚动位置没有回跳（>0 且未被重置）", mid.get("y", 0) > 200, mid.get("y"))

        # ---- 期次卡（长期安排）回填后必须写回基础组，重绘不退化 ----
        T("C0 存在期次卡（长期安排）", mid.get("occ") is True, mid)
        scroll_into_view(page, "#list article.gcard.occ", 1.4)
        for _ in range(3):
            page.wheel(195, 470, 300)
            page.sleep(0.3)
        page.sleep(0.8)
        occ = page.evaluate(r"""(function(){
          var W=document.querySelector('#noticeHost iframe').contentWindow;
          var card=W.document.querySelector('#list article.gcard.occ');
          var base=W.GROUPS.filter(function(g){return g.id===%s})[0]||null;
          return {card:!!card,
                  cardImg:!!(card&&card.querySelector('.imgrow img')),
                  cardLazy:!!(card&&card.querySelector('.imgrow.lazyimg')),
                  baseLazy:base?base.items.some(function(it){return !!it.lazy}):null,
                  calls:window.__bodyCalls||{}};
        })()""" % json.dumps(RECUR_ID))
        print("probe(occ):", json.dumps(occ, ensure_ascii=False))
        T("C1 期次卡图片已自动回填", occ.get("cardImg") is True, occ)
        T("C2 完整 items 已回填到基础组（下次重绘不退化）", occ.get("baseLazy") is False, occ)
        T("C3 期次卡 body 只请求一次（无重复拉取）", (occ.get("calls") or {}).get(RECUR_ROW, 0) <= 1,
          occ.get("calls"))

        # ---- 任意重绘（如标记已处理）后，已回填的图片不能退回占位 ----
        before = page.evaluate(PROBE_READ)
        page.evaluate("(function(){var W=document.querySelector('#noticeHost iframe').contentWindow;"
                      "if(W&&typeof W.render==='function')W.render();})()")
        page.sleep(1.0)
        after = page.evaluate(PROBE_READ)
        print("probe(re-render):", json.dumps(after, ensure_ascii=False))
        T("D1 期次卡重绘后图片仍在（不再反复请求）",
          page.evaluate("(function(){var W=document.querySelector('#noticeHost iframe').contentWindow;"
                        "var c=W.document.querySelector('#list article.gcard.occ');"
                        "return !!c&&!!c.querySelector('.imgrow img')&&!c.querySelector('.imgrow.lazyimg');})()"), after)
        T("D2 重绘后未新增重复 body 请求",
          sum((after.get("calls") or {}).values()) == sum((before.get("calls") or {}).values()),
          after.get("calls"))

        errs = page.all_errors()
        nerr = sum(len(v) for v in errs.values())
        T("E1 0 JS/console 报错", nerr == 0, {k: v[:3] for k, v in errs.items() if v})
        try:
            os.makedirs(os.path.join(HERE, "_v2_notice_reports"), exist_ok=True)
            page.screenshot(os.path.join(HERE, "_v2_notice_reports", "notice_scroll.png"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            if page:
                page.close()
        finally:
            if b:
                b.close()
            s.shutdown()
            for f in [pc.PREVIEW, preview, pc.HARNESS, pc.COMMON]:
                try:
                    os.remove(os.path.join(HERE, f))
                except OSError:
                    pass
    bad = RESULTS.count(False)
    print("=" * 60)
    print("v2_notice_scroll_check: %d 项，PASS %d，FAIL %d"
          % (len(RESULTS), len(RESULTS) - bad, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
