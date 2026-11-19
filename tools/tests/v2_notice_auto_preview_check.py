# -*- coding: utf-8 -*-
"""通知图片「直接预览」专项（2026-11-19 用户需求 7）。

用 power_check 的测试身份预览页 + 注入 lite meta / 单行 body mock：
  - 列表只返回 lazy 图片（无 data URI）；
  - 进入通知页后，模板应在图片进入视口时自动请求单行完整 body；
  - 回填后 <img> 直接出现，不再需要点「点击加载」。
只读，不连云端。
"""
import http.server
import json
import os
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
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("pc", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

PORT = 8979
RESULTS = []
AN = "[[CLASS_NOTICE_V1]]"
ROW_ID = "auto_g_lazy_preview"
GID = "g_lazy_preview"
IMG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lK3Q6wAAAABJRU5ErkJggg=="

GROUP = {
    "id": GID, "cat": "通知", "title": "图片预览测试",
    "summary": "图片应在进入视口时自动显示。", "aiSummary": "图片应在进入视口时自动显示。",
    "aiPoints": [], "group": "测试群", "source": "微信群 · 测试群",
    "items": [{"kind": "img", "label": "图片", "time": "11-19 12:00", "from": "测试",
               "caption": "测试图片", "note": "通知图片 · 预览加载中…", "lazy": True}],
    "publishedAt": "2026-11-19T12:00:00+08:00"
}
GROUP_FULL = json.loads(json.dumps(GROUP, ensure_ascii=False))
GROUP_FULL["items"][0].pop("lazy", None)
GROUP_FULL["items"][0]["src"] = IMG

META_ROW = {"id": ROW_ID, "title": "图片预览测试", "body": AN + json.dumps(GROUP, ensure_ascii=False),
            "archived": False, "hidden": False, "edited_at": 0, "ts": 1763000000000}
FULL_ROW = dict(META_ROW, body=AN + json.dumps(GROUP_FULL, ensure_ascii=False))


def T(name, ok, note=""):
    RESULTS.append(bool(ok))
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


WRAP = r"""
<script>
(function(){
  window.__noticeMetaCalls=0;window.__noticeFullCalls=0;window.__noticeSigCalls=0;
  var prev=window.fetch;
  function resp(obj){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve(JSON.stringify(obj));}});}
  window.fetch=function(u,o){
    o=o||{};var s=String((u&&u.url!==undefined)?u.url:u);
    if(s.indexOf("rpc/class_notices_meta")>=0){window.__noticeMetaCalls++;return resp(META);}
    if(s.indexOf("/notices?select=*&id=eq.")>=0){window.__noticeFullCalls++;return resp([FULL]);}
    if(s.indexOf("/notices")>=0&&s.indexOf("select=id,ts")>=0){window.__noticeSigCalls++;return resp([{id:FULL.id,ts:FULL.ts,hidden:false,edited_at:0}]);}
    if(s.indexOf("/notices")>=0){return resp([META]);}
    return prev.apply(this,arguments);
  };
  window.__lazyProbe=function(){return {meta:window.__noticeMetaCalls,full:window.__noticeFullCalls,sig:window.__noticeSigCalls};};
})();
</script>
"""


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    h = lambda *a, **kw: Q(*a, directory=HERE, **kw)
    s = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), h)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def main():
    s = serve()
    b = None
    p = None
    try:
        pc.build_previews()
        src = open(os.path.join(HERE, pc.PREVIEW), encoding="utf-8").read()
        inject = WRAP.replace("META", json.dumps(META_ROW, ensure_ascii=False)).replace("FULL", json.dumps(FULL_ROW, ensure_ascii=False))
        src = src.replace("</head>", inject + "</head>", 1)
        open(os.path.join(HERE, "_notice_lazy_preview.html"), "w", encoding="utf-8").write(src)
        b = _cdp.Browser(edge=pc.EDGE)
        p = b.new_page()
        p.set_device(390, 900, dpr=2.0, mobile=True, touch=True)
        ud = pc.ud_blob("4-23A---321")
        q = "sid=%s&name=%s&ud=%s" % (pc.SID_A, urllib.parse.quote(pc.NAME),
                                      urllib.parse.quote(json.dumps(ud, ensure_ascii=False), safe=""))
        p.navigate("http://127.0.0.1:%d/_notice_lazy_preview.html?%s" % (PORT, q))
        p.wait_load(30)
        T("A0 预览页启动", p.wait_for("!!document.querySelector('#idChipTxt')", 20), "")
        p.evaluate("var b=document.querySelector('#tabsBar button[data-tab=\"nt\"]');if(b)b.click();'x'")
        T("A1 通知页打开", p.wait_for("document.querySelector('#s-nt') && document.querySelector('#s-nt').classList.contains('on')", 10), "")
        T("A2 通知 iframe 出现", p.wait_for("!!document.querySelector('#noticeHost iframe')", 15), "")
        T("A3 模板渲染", p.wait_for("(function(){var f=document.querySelector('#noticeHost iframe');if(!f||!f.contentWindow)return false;try{return typeof f.contentWindow.GROUPS!=='undefined'&&f.contentWindow.GROUPS.length>0;}catch(e){return false;}})()", 20), "")
        # 进入视口后自动请求单行 full body；最多等 8 秒
        ok = p.wait_for("window.__noticeFullCalls>0", 12)
        T("A4 已自动请求图片所在单行 body（无需点击）", ok, json.dumps(p.evaluate("window.__lazyProbe()"), ensure_ascii=False))
        ok_img = p.wait_for("(function(){var f=document.querySelector('#noticeHost iframe');if(!f)return false;try{return !!f.contentDocument.querySelector('.imgrow img');}catch(e){return false;}})()", 12)
        T("A5 图片已直接回填为 <img>", ok_img, "")
        left = p.evaluate("(function(){var f=document.querySelector('#noticeHost iframe');if(!f)return -1;try{return f.contentDocument.querySelectorAll('.imgrow.lazyimg').length;}catch(e){return -1;}})()")
        T("A6 不再残留「预览加载中」占位", left == 0, str(left))
        T("A7 0 JS 报错", p.evaluate("(window.__errs||[]).length") == 0, str(p.evaluate("(window.__errs||[]).slice(0,3)")))
        print("probe:", p.evaluate("window.__lazyProbe()"))
    finally:
        try:
            if p: p.close()
        finally:
            if b: b.close()
            s.shutdown()
            for f in [pc.PREVIEW, "_notice_lazy_preview.html", pc.HARNESS, pc.COMMON]:
                try: os.remove(os.path.join(HERE, f))
                except OSError: pass
    bad = RESULTS.count(False)
    print("=" * 60)
    print("v2_notice_auto_preview_check: %d 项，PASS %d，FAIL %d" % (len(RESULTS), len(RESULTS) - bad, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
