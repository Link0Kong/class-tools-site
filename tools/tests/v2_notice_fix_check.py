# -*- coding: utf-8 -*-
"""2026-11-19 通知修复专项：毛毛雨无关图片 / 假班委气泡 / 军训方案时间 / 心得重复合并。

只读真实 board demo（tools/notice-board-live-demo.html），不连云端。
用法：cd web/tools && python tests\\v2_notice_fix_check.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
import _cdp  # noqa: E402

DEMO = os.path.join(ROOT, "notice-board-live-demo.html")
PORT = 8977
RESULTS = []


def T(name, ok, note=""):
    RESULTS.append(bool(ok))
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    h = lambda *a, **kw: Q(*a, directory=ROOT, **kw)
    s = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), h)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def js(p, expr):
    return p.evaluate(expr)


def main():
    s = serve()
    b = _cdp.Browser(edge=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    p = b.new_page()
    try:
        p.set_device(430, 900, dpr=2.0, mobile=True, touch=True)
        p.add_init_script("window.__errs=[];window.addEventListener('error',function(e){window.__errs.push(String(e.message||e.error||''));});"
                          "window.addEventListener('unhandledrejection',function(e){window.__errs.push('rejection:'+String(e.reason&&e.reason.message||e.reason));});")
        p.navigate("http://127.0.0.1:%d/notice-board-live-demo.html" % PORT)
        p.wait_load(60)
        T("A0 board demo 启动", p.wait_for("typeof GROUPS!=='undefined' && GROUPS.length>50", 30), "")
        # 1) 军训方案时间：应为 11-09，而不是 11-19 09:00
        plan = js(p, """(function(){var c=[].slice.call(document.querySelectorAll('.gcard')).filter(function(x){return x.textContent.indexOf('2026年学生军训工作实施方案')>=0;});return c.length?{n:c.length,text:c[0].textContent}:null;})()""")
        T("A1 军训方案只有一张卡", plan and plan["n"] == 1, json.dumps({"n": plan and plan["n"]}, ensure_ascii=False))
        T("A2 军训方案时间=11-09（不是 11-19 09:00）", plan and ("11-09" in plan["text"] or "11月9日" in plan["text"]) and "11-19 09:00" not in plan["text"], (plan or {}).get("text", "")[:260])
        # 2) 心得 11-22 与心得+鉴定表合并：只剩一张，含 11-22 和 11-19
        merge = js(p, """(function(){var cs=[].slice.call(document.querySelectorAll('.gcard')).filter(function(x){return x.textContent.indexOf('军训心得')>=0;});return {n:cs.length,texts:cs.map(function(x){return x.textContent.slice(0,380);})};})()""")
        T("A3 军训心得只剩一张卡（重复组已合并）", merge and merge["n"] == 1, json.dumps(merge, ensure_ascii=False)[:600])
        mt = (merge or {}).get("texts", [""])[0] if merge and merge["n"] else ""
        T("A4 合并卡同时含班级 11-19 与学校 11-22", ("11-19" in mt or "11月19日" in mt) and ("11-22" in mt or "11月22日" in mt), mt[:300])
        T("A5 不再单独出现「军训心得11-22前提交」卡", plan is not None and js(p, "!document.body.textContent.includes('军训心得11-22前提交')"), "")
        # 3) 毛毛雨：图片已移除，文字仍在
        rain = js(p, """(function(){var c=[].slice.call(document.querySelectorAll('.gcard')).filter(function(x){return x.textContent.indexOf('毛毛雨照常训练')>=0;});return c.length?{n:c.length,img:c[0].querySelectorAll('.imgrow').length,text:c[0].textContent}:null;})()""")
        T("A6 毛毛雨卡仍存在", rain and rain["n"] >= 1, json.dumps({"n": rain and rain["n"]}, ensure_ascii=False))
        T("A7 毛毛雨卡不再显示无关图片", rain and rain["img"] == 0, json.dumps({"img": rain and rain["img"]}, ensure_ascii=False))
        T("A8 毛毛雨通知内容保留", rain and "毛毛雨" in rain["text"] and "35分钟" in rain["text"], (rain or {}).get("text", "")[:200])
        # 4) 假班委气泡：数据层 badge 只出现在有 role 的发送者
        board = json.load(open(r"C:\briefdesk\data\board-data.json", encoding="utf-8"))
        bad, names = [], {"张誉权", "范进平", "杨培琪"}
        for g in board.get("groups", []):
            for it in g.get("items") or []:
                if not isinstance(it, dict):
                    continue
                nm = str(it.get("fromName") or "")
                if it.get("fromBadge") == "班委" and not it.get("fromRole"):
                    bad.append((g.get("id"), nm))
                if nm in names and it.get("fromBadge") == "班委":
                    bad.append((g.get("id"), nm, "非班委误标"))
        T("A9 非班委同学不再带班委气泡（数据层）", not bad, json.dumps(bad[:8], ensure_ascii=False))
        T("A10 0 JS 报错", js(p, "(window.__errs||[]).length") == 0, str(js(p, "(window.__errs||[]).slice(0,3)")))
    finally:
        try: p.close()
        finally: b.close(); s.shutdown()
    bad = RESULTS.count(False)
    print("=" * 60)
    print("v2_notice_fix_check: %d 项，PASS %d，FAIL %d" % (len(RESULTS), len(RESULTS) - bad, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
