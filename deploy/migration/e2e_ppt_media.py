# -*- coding: utf-8 -*-
"""网页 PPT 在线预览走 ECS `/pptfiles` 缓存的真实浏览器 E2E（2026-11-18 迁移优化）。

前置：网页已部署含媒体缓存映射的 index.html；staging 路由 `/v1/rdb/rest-next/` 可用；
真实 deck `dmwalrdlgevz90l` 在 staging 表里（与 CloudBase 快照一致）。
验证：用测试账号登录 staging → 打开 `PPT.open(deckId)` → 断言播放器出现、幻灯片/视频请求走
`/pptfiles/ppt/a/dmwalrdl...`、0 个 OSS 直连媒体请求、0 JS 报错、下载 href 也指向 ECS 缓存。
只读/仅 staging（登录会写 class_sessions/visits，属预期）；不使用真实账号。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(WEB, "tools", "tests", "_qa_v2"))
import _cdp  # noqa: E402

BASE = os.environ.get("E2E_BASE") or "http://121.196.47.2"
URL = BASE + "/?api=next"
DECK = os.environ.get("E2E_DECK") or "dmwalrdlgevz90l"
TEST_SID = "3260799999"
TEST_NAME = "测试账号"

RESULTS = []


def check(name, ok, note=""):
    RESULTS.append((name, bool(ok)))
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)[:260]) if note else ""))


def main():
    browser = _cdp.Browser(window=(430, 900), extra_flags=[
        "--no-proxy-server",
        "--disable-features=HttpsUpgrades,HttpsFirstModeV2,HTTPS-FirstMode,HttpsFirstBalancedModeAutoEnable",
        "--autoplay-policy=no-user-gesture-required",
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
        ver = page.evaluate(
            """(async function(){
              var r=await fetch(location.origin+'/v1/rdb/rest-next/rpc/class_verify',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({p_sid:'%s',p_name:'%s'})});
              var j=await r.json();
              if(!j||!j.token)return {ok:false,err:'verify '+r.status};
              localStorage.setItem('zq_class_identity',JSON.stringify({token:j.token,sid:j.sid,name:j.name,role:j.role||'',badge:j.badge||'',is_admin:!!j.is_admin,ts:Date.now()}));
              return {ok:true};})()""" % (TEST_SID, TEST_NAME), await_promise=True, timeout=60)
        if not ver.get("ok"):
            check("V0 测试账号 staging 登录", False, ver)
            return finish()
        page.navigate(URL)
        page.wait_load(30)
        page.wait_for("!document.body.classList.contains('auth-pending')", timeout=25)
        page.wait_for("(function(){return !!(window.PPT&&window.PPT.open);})()", timeout=25)
        check("V1 页面就绪且 PPT API 可用", True)

        # 先拉一次 PPT 列表（hrefOf/filesOf 依赖列表缓存），再检查下载 href
        try:
            page.evaluate("(async function(){try{await Promise.resolve(PPT.pull());}catch(e){} return PPT.loaded();})()",
                          await_promise=True, timeout=60)
        except Exception:  # noqa: BLE001
            pass
        # V2b：列表封面 cover_url 也应走 /pptfiles（列表在隐藏 tab 里，lazy 图不一定发请求，直接检查 DOM src）
        try:
            page.evaluate("(function(){try{PPT.enter();return 1;}catch(e){return 0;}})()")
            page.sleep(0.6)
        except Exception:  # noqa: BLE001
            pass
        covers = page.evaluate(
            "(function(){return Array.prototype.slice.call(document.querySelectorAll('#pptList img'))"
            ".map(function(i){return String(i.getAttribute('src')||'');})"
            ".filter(function(x){return x.indexOf('/pptfiles/ppt/a/%s/')>=0;}).slice(0,3);})()" % DECK)
        check("V2b 列表封面走 /pptfiles（DOM src）", bool(covers), covers)

        try:
            page.evaluate("(function(){try{PPT.openDetail('%s');return 1;}catch(e){return 0;}})()" % DECK)
            page.sleep(1.2)
        except Exception:  # noqa: BLE001
            pass
        href = page.evaluate("(function(){try{return String(PPT.hrefOf('%s','compat')||'');}catch(e){return 'ERR:'+e.message;}})()" % DECK)
        check("V2 下载 href 指向 ECS /pptfiles", ("/pptfiles/ppt/a/%s/" % DECK) in href, href[:160])

        op = page.evaluate("(function(){try{PPT.open('%s');return 'ok';}catch(e){return 'ERR:'+e.message;}})()" % DECK)
        check("V3 PPT.open 调用成功", op == "ok", op)
        page.sleep(6.0)

        st = page.evaluate(
            """(function(){
              var res=performance.getEntriesByType('resource').map(function(e){return e.name});
              var media=res.filter(function(n){return n.indexOf('/pptfiles/ppt/a/%s')>=0;});
              var oss=res.filter(function(n){return n.indexOf('tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/a/%s')>=0;});
              var prod=res.filter(function(n){return n.indexOf('/v1/rdb/rest/')>=0 && n.indexOf('rest-next')<0;});
              var imgs=Array.prototype.slice.call(document.querySelectorAll('#pptPlayer img')).map(function(i){
                return {src:(i.currentSrc||i.src||'').slice(0,180),ok:!!(i.complete&&i.naturalWidth>0)};});
              var v=document.querySelector('#pptPlayer video');
              return {player:!!document.querySelector('#pptPlayer'), media:media.length, oss:oss.length, prod:prod.length,
                      imgs:imgs.slice(0,4), imgOk:imgs.filter(function(x){return x.ok}).length,
                      video: v?{src:(v.currentSrc||v.src||'').slice(0,180),rs:v.readyState,err:v.error?v.error.code:0}:null,
                      errs:(window.__e2e_errs||[]).slice(0,6)};
            })()""" % (DECK, DECK))
        check("V4 播放器已打开", st.get("player") is True)
        check("V5 媒体请求走 /pptfiles 缓存（>=1）", (st.get("media") or 0) >= 1, "media=%s" % st.get("media"))
        check("V6 0 个 OSS 直连媒体请求", (st.get("oss") or 0) == 0, "oss=%s" % st.get("oss"))
        check("V7 0 个生产 CloudBase API 请求（staging 影子）", (st.get("prod") or 0) == 0, "prod=%s" % st.get("prod"))
        check("V8 幻灯片图片加载成功（>=1）", (st.get("imgOk") or 0) >= 1,
              "imgOk=%s imgs=%s" % (st.get("imgOk"), st.get("imgs")))
        v = st.get("video")
        check("V9 视频（如存在）来自 /pptfiles 且无解码错误",
              (not v) or (("/pptfiles/" in (v.get("src") or "")) and v.get("err") == 0),
              v)
        check("V10 无 JS 报错", not st.get("errs"), st.get("errs"))
        return finish()
    finally:
        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass


def finish():
    total = len(RESULTS)
    passed = sum(1 for _n, ok in RESULTS if ok)
    print("=" * 56)
    print("e2e_ppt_media: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 56)
    return 0 if total and passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
