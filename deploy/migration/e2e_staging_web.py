# -*- coding: utf-8 -*-
"""网页端 staging 真实浏览器 E2E（2026-11-18 迁移 P2 验证）。

前置：ECS 已加 /v1/rdb/rest-next/ → 本地 PostgREST；网页已部署带 `?api=next` 开关的 index.html。
做法：headless Edge + CDP（复用 tools/tests/_qa_v2/_cdp.py）打开 `http://121.196.47.2/?api=next`，
用**测试账号** 3260799999/测试账号 在页面内真实 class_verify → 写 localStorage 身份 → 重新加载 →
确认：不再停在身份页、所有 API 走 staging 路径（0 个生产 CloudBase 请求）、名单 70、通知/作业等有数据、无 JS 报错。
只读/仅 staging 写（登录会写 class_sessions/visits，属预期）；不使用真实账号。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))          # deploy/migration -> web
sys.path.insert(0, os.path.join(WEB, "tools", "tests", "_qa_v2"))
sys.path.insert(0, os.path.join(WEB, "tools", "tests"))
import _cdp  # noqa: E402

BASE = os.environ.get("E2E_BASE") or "http://121.196.47.2"
URL = BASE + "/?api=next"
TEST_SID = "3260799999"
TEST_NAME = "测试账号"

results = []


def check(name, ok, note=""):
    results.append((name, bool(ok), str(note)[:300]))
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)[:200]) if note else ""))


def main():
    browser = _cdp.Browser(window=(430, 900), extra_flags=[
            "--no-proxy-server",
            # Edge 新版会把明文 HTTP 自动升级到 HTTPS；IP 调试入口没有 HTTPS，需显式关掉
            "--disable-features=HttpsUpgrades,HttpsFirstModeV2,HTTPS-FirstMode,HttpsFirstBalancedModeAutoEnable",
        ])
    try:
        page = browser.new_page("about:blank")
        page.add_init_script(
            "window.__e2e_errs=[];window.addEventListener('error',function(e){window.__e2e_errs.push(String((e&&e.message)||'error'));});"
            "window.addEventListener('unhandledrejection',function(e){window.__e2e_errs.push('reject:'+String(e&&e.reason&&e.reason.message||e.reason));});",
            run_immediately=True)
        page.navigate(URL)
        page.wait_load(30)
        page.sleep(0.5)

        # 1) 身份页存在（未登录门禁）且 api=next 生效
        st = page.evaluate("(function(){return {href:location.href, pending:document.body.classList.contains('auth-pending'), search:location.search};})()")
        check("V1 打开 ?api=next 页面", st.get("search", "").find("api=next") >= 0, st.get("href"))
        check("V2 未登录时身份门禁生效", st.get("pending") is True, "auth-pending=%s" % st.get("pending"))

        # 2) 页面内用测试账号调 staging class_verify（真实网络）
        ver = page.evaluate(
            """(async function(){
              var r=await fetch(location.origin+'/v1/rdb/rest-next/rpc/class_verify',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({p_sid:'%s',p_name:'%s'})});
              var j=await r.json();
              if(!j||!j.token)return {ok:false,err:'verify http '+r.status+' '+JSON.stringify(j).slice(0,120)};
              localStorage.setItem('zq_class_identity',JSON.stringify({token:j.token,sid:j.sid,name:j.name,role:j.role||'',badge:j.badge||'',is_admin:!!j.is_admin,ts:Date.now()}));
              return {ok:true,sid:j.sid,name:j.name,is_admin:!!j.is_admin};})()""" % (TEST_SID, TEST_NAME),
            await_promise=True, timeout=60)
        check("V3 测试账号 staging class_verify", ver.get("ok") is True and ver.get("sid") == TEST_SID, ver)
        if not ver.get("ok"):
            return finish()
        token = page.evaluate("(function(){try{return JSON.parse(localStorage.getItem('zq_class_identity')||'null').token}catch(e){return ''}})()")

        # 3) 重新加载：身份恢复 + 数据加载
        page.navigate(URL)
        page.wait_load(30)
        page.wait_for("!document.body.classList.contains('auth-pending')", timeout=25)
        page.sleep(3.0)

        state = page.evaluate(
            """(function(){
              var names=performance.getEntriesByType('resource').map(function(e){return e.name});
              var stage=names.filter(function(n){return n.indexOf('/v1/rdb/rest-next/')>=0});
              var prod=names.filter(function(n){return n.indexOf('/v1/rdb/rest/')>=0 && n.indexOf('rest-next')<0});
              var ids=[];try{ids=JSON.parse(localStorage.getItem('zq_class_identity')||'null')||{}}catch(e){}
              return {pending:document.body.classList.contains('auth-pending'), sid:ids.sid||'',
                      staging:stage.length, prod:prod.length,
                      bodyLen:(document.body.innerText||'').length,
                      text:(document.body.innerText||'').slice(0,600),
                      errs:(window.__e2e_errs||[]).slice(0,8)};
            })()""")
        check("V4 重新加载后身份恢复（不停在门禁页）", state.get("pending") is False and state.get("sid") == TEST_SID,
              "pending=%s sid=%s" % (state.get("pending"), state.get("sid")))
        check("V5 所有 API 走 staging（0 个生产 CloudBase 请求）",
              state.get("staging", 0) >= 5 and state.get("prod", 1) == 0,
              "staging=%s prod=%s" % (state.get("staging"), state.get("prod")))
        txt = state.get("text") or ""
        check("V6 页面渲染出内容（身份/工具/工作流可见）", ("测试账号" in txt) and ("抽签" in txt) and ("作业" in txt) and state.get("bodyLen", 0) > 80,
              "bodyLen=%s" % state.get("bodyLen"))
        check("V7 页面无 JS 报错", not state.get("errs"), state.get("errs"))

        # 4) 关键数据读链路（在页面上下文用身份 token 取 staging）
        data = page.evaluate(
            """(async function(){
              var id=JSON.parse(localStorage.getItem('zq_class_identity')||'null')||{};
              var h={ 'X-Class-Token': id.token||id.sid, 'X-Device-Id': id.token||'' };
              async function j(path){var r=await fetch(location.origin+path,{headers:h});return {s:r.status,b:await r.json().catch(function(){return null})};}
              var m=await j('/v1/rdb/rest-next/rpc/class_members');
              var meta=await j('/v1/rdb/rest-next/rpc/class_notices_meta');
              var hw=await j('/v1/rdb/rest-next/homework?select=id&limit=5');
              var pw=await j('/v1/rdb/rest-next/power?select=id&limit=2');
              return {members:(m.b&&m.b.length)||0, meta:(meta.b&&meta.b.length)||0,
                      hw:(hw.b&&hw.b.length)||0, power:(pw.b&&pw.b.length)||0,
                      statuses:[m.s,meta.s,hw.s,pw.s]};})()""",
            await_promise=True, timeout=90)
        check("V8 staging 读链路（members=70 / meta>0 / homework>=0 / power>0）",
              data.get("members") == 70 and data.get("meta", 0) > 10 and data.get("power", 0) > 0,
              data)
        check("V9 staging 读接口 HTTP 全 200", all(s == 200 for s in (data.get("statuses") or [])), data.get("statuses"))

        # 5) 性能：页面内 staging API 的 P50（本机→ECS 公网，真实浏览器）
        perf = page.evaluate(
            """(function(){var a=performance.getEntriesByType('resource').filter(function(e){return e.name.indexOf('/v1/rdb/rest-next/')>=0});
              var d=a.map(function(e){return e.duration}).sort(function(x,y){return x-y});
              return {n:d.length,p50:d.length?d[Math.floor(d.length*0.5)]:null,max:d.length?d[d.length-1]:null};})()""")
        check("V10 收集到 staging 请求耗时样本", (perf.get("n") or 0) >= 5,
              "n=%s p50=%sms max=%sms" % (perf.get("n"), round(perf.get("p50") or 0), round(perf.get("max") or 0)))
        return finish()
    finally:
        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass


def finish():
    passed = sum(1 for _n, ok, _ in results if ok)
    total = len(results)
    print("=" * 56)
    print("e2e_staging_web: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 56)
    return 0 if total and passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
