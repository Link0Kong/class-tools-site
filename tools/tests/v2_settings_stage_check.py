# -*- coding: utf-8 -*-
"""设置工具卡片 + 大屏工具卡片专项检查（2026-11-19 用户需求 4/5/6）。

覆盖：
  - 静态：TOOLS 含 settings / stage(admin)；#s-settings；设置页协议链接；
          旧「大屏 / 大屏互联」按钮行不再创建；stage 由 gotoTab 打开覆盖层。
  - 运行时（测试身份 mock，is_admin=true 以便看到大屏卡片）：
          全部页有「设置」「大屏」两张卡片；设置页可打开，外观/备份弹层可用；
          协议链接指向 legal/web/*.html；大屏卡片点击打开 #opt2Stage；
          页面无 JS 错误；未开启大屏时不存在可见的「大屏互联」按钮。
用法：cd web/tools && python tests\\v2_settings_stage_check.py
"""
import http.server
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
ROOT = os.path.dirname(HERE)
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("pc", os.path.join(HERE, "power_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

PORT = 8973
RESULTS = []


def T(name, ok, note=""):
    RESULTS.append(bool(ok))
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    h = lambda *a, **kw: Q(*a, directory=HERE, **kw)
    s = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), h)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def static_checks():
    src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    T("S1 TOOLS 含设置工具卡片", '{k:"settings",n:"设置"' in src)
    T("S2 TOOLS 含大屏工具卡片（仅管理员）", '{k:"stage",n:"大屏",d:"团日主持与演示放映",admin:true}' in src)
    T("S3 设置页 #s-settings 存在", '<section id="s-settings">' in src)
    T("S4 设置页协议链接指向 legal/web", 'href="legal/web/privacy.html"' in src and 'href="legal/web/terms.html"' in src)
    T("S5 大屏改由 gotoTab 打开覆盖层", 'k==="stage"' in src and 'window.__openStage' in src)
    T("S6 旧大屏/互联按钮行仅保留隐藏兼容节点", 'row.id="opt2StageRow"' in src and 'row.hidden=true' in src and '#opt2StageRow[hidden]' in src)
    T("S7 未开启大屏无可见互联按钮（CSS 兜底）", '#opt2DropBtn[hidden]' in src and 'display:none!important' in src)


def click(p, sel):
    return p.evaluate("(function(){var e=document.querySelector(%r);if(!e)return false;e.click();return true;})()" % sel)


def visible(p, sel):
    return p.evaluate("(function(){var e=document.querySelector(%r);if(!e)return false;var r=e.getBoundingClientRect();"
                      "var s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';})()" % sel)


def run(p):
    url = "http://127.0.0.1:%d/" % PORT
    ud = pc.ud_blob("4-23A---321")
    import urllib.parse
    q = "sid=%s&name=%s&ud=%s" % (pc.SID_A, urllib.parse.quote(pc.NAME), urllib.parse.quote(__import__("json").dumps(ud, ensure_ascii=False), safe=""))
    p.set_device(390, 900, dpr=2.0, mobile=True, touch=True)
    p.navigate(url + "_settings_preview.html?" + q)
    p.wait_load(30)
    T("A0 页面启动", p.wait_for("!!document.querySelector('#idChipTxt')", 20), "")
    click(p, '#tabsBar button[data-tab="all"]')
    T("A1 全部页打开", p.wait_for("document.querySelector('#s-all') && document.querySelector('#s-all').classList.contains('on')", 10), "")
    T("A2 全部页有设置卡片", p.wait_for("!!document.querySelector('#allCards [data-card=\"settings\"]')", 10), "")
    T("A3 全部页有大屏卡片（管理员）", p.wait_for("!!document.querySelector('#allCards [data-card=\"stage\"]')", 10), "")
    T("A4 未开启大屏时无可见的大屏互联按钮", not visible(p, "#opt2DropBtn"), "")

    click(p, '#allCards [data-card="settings"]')
    T("B1 设置页打开", p.wait_for("document.querySelector('#s-settings').classList.contains('on')", 10), "")
    T("B2 设置页三行（外观/备份/协议）", p.evaluate("document.querySelectorAll('#s-settings .set-line').length") >= 3, "")
    T("B3 协议链接 href 正确", p.evaluate("(function(){var a=document.querySelector('#s-settings a[href=\"legal/web/privacy.html\"]');return !!a&&a.getAttribute('target')==='_blank';})()"), "")
    click(p, "#setAppearanceBtn")
    T("B4 外观弹层可打开", p.wait_for("(function(){var e=document.querySelector('#apOv');return !!e&&!e.hidden&&getComputedStyle(e).display!=='none';})()", 5), "")
    click(p, "#apClose")
    click(p, "#setBackupBtn")
    T("B5 数据备份弹层可打开", p.wait_for("(function(){var e=document.querySelector('#optBkOv');return !!e&&getComputedStyle(e).display!=='none';})()", 5), "")
    click(p, "#optBkClose")
    click(p, '#tabsBar button[data-tab="all"]')
    click(p, '#allCards [data-card="stage"]')
    T("B6 大屏卡片打开覆盖层", p.wait_for("(function(){var e=document.querySelector('#opt2Stage');return !!e&&!e.hidden&&getComputedStyle(e).display!=='none';})()", 10), "")
    T("B7 大屏内才有互联按钮", visible(p, "#o2sDropBtn"), "")
    T("B8 0 JS 错误", p.evaluate("(window.__errs||[]).length") == 0, str(p.evaluate("(window.__errs||[]).slice(0,3)")))


def main():
    serve()
    try:
        pc.build_previews()
        src = open(os.path.join(HERE, pc.PREVIEW), encoding="utf-8").read()
        src = src.replace("is_admin:false", "is_admin:true")
        open(os.path.join(HERE, "_settings_preview.html"), "w", encoding="utf-8").write(src)
        static_checks()
        b = _cdp.Browser(edge=pc.EDGE)
        p = b.new_page()
        try:
            run(p)
        finally:
            try: p.close()
            finally: b.close()
    finally:
        for f in [pc.PREVIEW, "_settings_preview.html", pc.HARNESS, pc.COMMON]:
            try:
                os.remove(os.path.join(HERE, f))
            except OSError:
                pass
    bad = RESULTS.count(False)
    print("=" * 60)
    print("v2_settings_stage_check: %d 项，PASS %d，FAIL %d" % (len(RESULTS), len(RESULTS) - bad, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
