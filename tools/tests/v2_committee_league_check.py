# -*- coding: utf-8 -*-
"""v2.0.0 名单工具「团员人数」专项自检（2026-11-12）

覆盖（用户反馈：团员人数初次点击不显示）：
  A. 静态：进入名单页即预取团员名单（renderCommittee 内 cmLeagueFetch 预取）；并发去重
     （CM_LEAGUE_P）；错误时显示「—」而不是 0；tab 点击不再重复发请求；保留 class_league RPC。
  B. 运行时（mock class_league=3 人）：进入名单页**不点击**，团员人数自动显示 3 且只发 1 次请求；
     首次点击团员 tab → 列表 3 行、人数仍 3、无新增请求；切走再切回不重复请求；
     390 竖屏 / 844x390 手机横屏无横向溢出；0 JS 报错 / 0 console.error / 0 外部请求。
用法：cd web/tools && python tests\\v2_committee_league_check.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "index.html")
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _webqa  # noqa: E402

SHOTS = os.path.join(HERE, "_shots_committee_league")
RESULTS = []


def T(k, ok, note=""):
    RESULTS.append({"k": k, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note != "" else ""))


def static_checks():
    with open(SRC, encoding="utf-8", newline="") as f:
        src = f.read()
    T("S1 团员名单并发去重（CM_LEAGUE_P）", "CM_LEAGUE_P" in src and "if(CM_LEAGUE_P&&!force)return CM_LEAGUE_P;" in src)
    T("S2 进入名单页即预取团员名单（renderCommittee 内 cmLeagueFetch）",
      "if(CM_LEAGUE===null&&!CM_LEAGUE_ERR){cmLeagueFetch().then(function(){renderCommittee();});}" in src)
    T("S3 名单页切换不再重复拉取（tab 点击无二次 fetch）",
      'if(CM_TAB==="league"&&CM_LEAGUE===null)cmLeagueFetch().then(function(){renderCommittee();});' not in src)
    T("S4 团员人数加载失败显示「—」而非 0",
      '(CM_LEAGUE_ERR&&!(CM_LEAGUE||[]).length)?"—":CM_LEAGUE.length' in src)
    T("S5 仍通过 class_league RPC 读取团员名单", 'cbRpc("class_league",{})' in src)
    T("S6 名单工具三 tab 与计数位保留", 'id="cmCntL"' in src and 'data-cmtab="league"' in src)


def open_committee(s):
    s.open_all_card("committee")
    return s.wait("!!document.querySelector('#s-committee')&&document.querySelector('#s-committee').classList.contains('on')", 12)


def league_reqs(s):
    return [r for r in s.reqs("league") if "class_league" in (r.get("url") or "")]


def run_size(w, h, tag, mobile=True):
    srv = _webqa._Server()
    srv.start()
    s = None
    try:
        s = _webqa.Session(srv, width=w, height=h, mobile=mobile, dpr=2.0 if mobile else 1.0, name="cl" + tag)
        ok = s.wait_boot(25)
        T("B%s0 启动完成" % tag, ok, "")
        if not ok:
            return
        T("B%s1 进入名单页" % tag, open_committee(s), "")
        s.sleep(1.0)
        # 未点击团员 tab 前，人数应自动加载
        auto = s.wait("(function(){var e=document.getElementById('cmCntL');return !!e&&e.textContent==='3';})()", 8)
        T("B%s2 初次进入名单页（未点击）团员人数自动显示 3" % tag, auto,
          s.js("(function(){var e=document.getElementById('cmCntL');return e?e.textContent:'(none)';})()"))
        n1 = len(league_reqs(s))
        T("B%s3 预取只发 1 次 class_league 请求" % tag, n1 == 1, n1)
        # 首次点击团员 tab
        s.js("(function(){var b=document.querySelector('#cmTabs [data-cmtab=\"league\"]');if(b)b.click();return true;})()")
        s.sleep(0.8)
        st = s.js("""(function(){return JSON.stringify({
          cntL:(document.getElementById('cmCntL')||{}).textContent,
          rows:document.querySelectorAll('#cmOut .cmrow').length,
          tab:(document.querySelector('#cmTabs .cmtab.on')||{}).textContent||''});})()""")
        T("B%s4 首次点击团员 tab：列表 3 行、人数 3" % tag, '"rows":3' in st and '"cntL":"3"' in st, st)
        n2 = len(league_reqs(s))
        T("B%s5 点击 tab 不重复请求（仍 1 次）" % tag, n2 == 1, n2)
        # 切走再切回
        s.js("(function(){var b=document.querySelector('#cmTabs [data-cmtab=\"all\"]');if(b)b.click();})()")
        s.sleep(0.4)
        s.js("(function(){var b=document.querySelector('#cmTabs [data-cmtab=\"league\"]');if(b)b.click();})()")
        s.sleep(0.5)
        n3 = len(league_reqs(s))
        T("B%s6 切走再切回仍不重复请求" % tag, n3 == 1, n3)
        # 布局与错误
        over = s.js("document.documentElement.scrollWidth-document.documentElement.clientWidth")
        T("B%s7 无横向溢出" % tag, over == 0, over)
        errs = s.js_errors()
        T("B%s8 0 JS 报错" % tag, not errs, errs[:2])
        cerrs = s.console_errors()
        T("B%s9 0 console.error" % tag, not cerrs, cerrs[:2])
        # 大屏互联 presence 为 2026-11-12 起的既有基线请求（并行会话功能），不计入本功能外部请求
        ext = [u for u in (s.external_urls() or []) if "/drop/presence" not in str(u)]
        T("B%s10 0 外部请求（既有大屏 presence 基线除外）" % tag, not ext, ext[:2])
        os.makedirs(SHOTS, exist_ok=True)
        p = os.path.join(SHOTS, "league_%s.png" % tag)
        s.page.screenshot(p)
        T("B%s11 截图落盘" % tag, os.path.exists(p), p)
    finally:
        if s:
            s.close()
        srv.stop()


def main():
    static_checks()
    run_size(390, 844, "390", mobile=True)
    run_size(844, 390, "844x390", mobile=True)
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 64)
    print("v2_committee_league_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 64)
    return 0 if total and passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
