# -*- coding: utf-8 -*-
"""v2 专项自检：微信 X5 残影风险（通知页横向手势不做 transform + fly 只动 transform）

背景：手机微信 X5 对「含 iframe 的整块 section 做 transform」会出现合成残影（手指拖动时最明显）。
本测试的静态/行为断言（Chrome headless 无法复现 X5 残影本身，只能消除高风险写法）：
  S. 静态：fly() 不再改 opacity、只动 transform 且用 translate3d；通知页横向手势路径不位移 section；
          commit 时通知页/directSwitch 直接切；CSS 在 fly 期间禁用 section fade；thumb 用 translate3d。
  B1. 通知页拖动：section 无 transform 样式、iframe 元素 rect 不变；toolbar thumb 跟手。
  B2. 通知页松手：直接切 tab（iframe 不做位移动画）、body.zq-flying 清理、320ms 点击抑制语义正确。
  B3. 其它页面：fly 仍正常（translate3d 位移、无 opacity、动画结束后内联样式/will-change/body 类清理）。

用法：cd C:\\...\\web\\tools && python tests\\v2_x5_anim_check.py
退出码 0 = 全绿。
"""
import http.server
import importlib.util
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import websocket
except Exception:
    print("[v2_x5_anim_check] 缺少 websocket-client")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.abspath(os.environ.get("V2X_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HTTP_PORT = 8962
CDP_PORT = 9462
W, H = 390, 844
RESULTS = []


def T(key, ok, note=""):
    RESULTS.append({"k": key, "ok": bool(ok)})
    print(("[PASS] " if ok else "[FAIL] ") + key + ((" | " + str(note)) if note != "" else ""))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


scrollmod = load("v2_scroll_check", os.path.join(HERE, "v2_scroll_check.py"))
Handler = scrollmod.Handler
Q = scrollmod.Q
CDP = scrollmod.CDP
get_ws = scrollmod.get_ws
wait_until = scrollmod.wait_until
touch = scrollmod.touch


def static_checks():
    html = open(SRC, encoding="utf-8").read()
    flat = re.sub(r"\s+", "", html)
    # 取 fly → snap 函数体、commit 函数体
    i = html.find("function fly(el,dir,type,fn)")
    j = html.find("function snap(el)", i)
    k = html.find("function commit(t,dir)", j)
    k2 = html.find("function gotoTab(k,noScroll)", 0)
    fly_src = html[i:j] if i >= 0 and j > i else ""
    commit_src = html[k:k + 4000] if k >= 0 else ""
    T("S1 fly() 不再修改 opacity（避免 X5 alpha 合层残影）", "opacity" not in fly_src, "")
    T("S2 fly() 使用 translate3d 位移", "translate3d(" in fly_src, "")
    T("S3 fly() 不写 will-change（层切换闪烁源）", "willChange" not in fly_src, "")
    T("S4 section.on 已无 fade 动画、无 @keyframes fade（STEP 面板已随 2026-11-22 拆分移除）",
      "animation:fade" not in flat and "@keyframesfade" not in flat and
      "section.on{display:block" in flat and ".stpane" not in flat, "")
    T("S5 通知页（含 iframe）横向手势不位移 section（isNoticeSection 判断）",
      html.count("isNoticeSection") >= 3, html.count("isNoticeSection"))
    T("S6 通知页/directSwitch 松手直接切 tab（不 fly iframe），且无 zq-flying 类逻辑",
      "directSwitch(" in commit_src and ('t.tab==="nt"' in commit_src) and "zq-flying" not in html, "")
    T("S7 通知页 snap() 不写 section transform", "isNoticeSection(el)" in html[j:j + 1400], "")
    gi = html.find("function beginGhost")
    ghost_src = html[gi:gi + 2600] if gi >= 0 else ""
    T("S8 will-change 仅拖动幽灵临时使用（fly/CSS 持久层切换禁用）",
      html.count("will-change") == 1 and "will-change:transform" in ghost_src and "willChange" not in html,
      "count=%d ghost=%s" % (html.count("will-change"), "will-change:transform" in ghost_src))
    T("S9 gotoTab 切页前幂等清理并取消未完成 fly",
      "__zqKillFly" in html[k2:k2 + 1800], "")
    T("S10 fly 单实例：新 fly 会先取消旧定时器", "flyClearTimers()" in fly_src, "")


NOTICE_DRAG_JS = r"""
(function(){
  try{
    var f=document.querySelector('#noticeHost iframe');
    if(!f)return JSON.stringify({err:'no-frame'});
    var D=f.contentDocument;
    function touch(x,y){return new Touch({identifier:1,target:D.body,clientX:x,clientY:y});}
    function fire(type,x,y,list){var ev=new TouchEvent(type,{bubbles:true,cancelable:true,touches:list,changedTouches:list,targetTouches:list});
      D.dispatchEvent(ev);return ev;}
    function snapState(){
      var sec=document.querySelector('#s-nt'), th=document.querySelector('.tabs-thumb'), ifr=f;
      var r=ifr.getBoundingClientRect(), tr=th?th.style.transform:"";
      return {tx:String(sec?sec.style.transform:""), thumb:tr,
        rect:[Math.round(r.x*10)/10,Math.round(r.y*10)/10,Math.round(r.width*10)/10,Math.round(r.height*10)/10],
        cls:document.body.className};
    }
    var samples=[], prevented=0;
    samples.push(snapState());
    var sx=200,sy=300,t0=touch(sx,sy);
    fire('touchstart',sx,sy,[t0]);
    for(var i=1;i<=12;i++){
      var x=sx-6*i;var t=touch(x,sy);var ev=fire('touchmove',x,sy,[t]);
      if(ev.defaultPrevented)prevented++;
      samples.push(snapState());
    }
    var beforeCommit=snapState();
    var endTouch=touch(sx-72,sy);
    D.dispatchEvent(new TouchEvent('touchend',{bubbles:true,cancelable:true,touches:[],changedTouches:[endTouch],targetTouches:[]}));
    var afterCommit=snapState();
    return JSON.stringify({samples:samples,prevented:prevented,beforeCommit:beforeCommit,afterCommit:afterCommit,
      tab:(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''});
  }catch(e){return JSON.stringify({err:String(e)});}
})()
"""

FLY_JS = r"""
(function(){
  try{
    window.__x5={styles:[],classes:[]};
    var mo=new MutationObserver(function(ms){
      for(var i=0;i<ms.length;i++){
        var t=ms[i].target;
        if(!t||t.nodeType!==1)continue;
        var st=t.getAttribute&&t.getAttribute("style")||"";
        if(st)window.__x5.styles.push({tag:t.tagName,id:t.id||"",cls:String(t.className||""),st:st});
      }
    });
    mo.observe(document.body,{attributes:true,attributeFilter:["style","class"],subtree:true});
    function touch(x,y){return new Touch({identifier:1,target:document.body,clientX:x,clientY:y});}
    function fire(type,x,y,list){var ev=new TouchEvent(type,{bubbles:true,cancelable:true,touches:list,changedTouches:list,targetTouches:list});
      document.dispatchEvent(ev);return ev;}
    var x=330,y=560,t0=touch(x,y);fire('touchstart',x,y,[t0]);
    for(var i=1;i<=8;i++){x-=10;var t=touch(x,y);fire('touchmove',x,y,[t]);}
    var endT=touch(x,y);
    document.dispatchEvent(new TouchEvent('touchend',{bubbles:true,cancelable:true,touches:[],changedTouches:[endT],targetTouches:[]}));
    return true;
  }catch(e){return String(e);}
})()
"""

CLEANUP_JS = r"""
(function(){
  var gone=true,secs=[];
  document.querySelectorAll("section,.ttmain").forEach(function(el){
    var st=el.getAttribute("style")||"";
    if(/transform|will-change|opacity/.test(st)){gone=false;secs.push({id:el.id,cls:String(el.className),st:st});}
  });
  var animFree=true;
  document.querySelectorAll("section,.ttmain").forEach(function(el){
    var st=el.getAttribute("style")||"";
    if(/animation|transition/.test(st))animFree=false;
  });
  return JSON.stringify({gone:gone,animFree:animFree,secs:secs,cls:document.body.className,
    flying:(" "+document.body.className+" ").indexOf(" zq-flying ")>0});
})()
"""


def run():
    devnull = open(os.devnull, "wb")
    tmp = tempfile.mkdtemp(prefix="x5_")
    prof = tempfile.mkdtemp(prefix="edgeprof_")
    srv = None
    proc = None
    cdp = None
    try:
        open(os.path.join(tmp, "preview.html"), "w", encoding="utf-8", newline="").write(scrollmod.build_preview())
        os.chdir(tmp)
        srv = Q(("127.0.0.1", HTTP_PORT), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                                 "--no-default-browser-check", "--disable-extensions",
                                 "--remote-debugging-port=%d" % CDP_PORT,
                                 "--user-data-dir=" + prof, "about:blank"],
                                stdout=devnull, stderr=devnull)
        cdp = CDP(get_ws(CDP_PORT))
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": W, "height": H,
                                                        "deviceScaleFactor": 2, "mobile": True})
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        cdp.send("Page.navigate", {"url": "http://127.0.0.1:%d/preview.html" % HTTP_PORT})
        wait_until(cdp, "!!(window.__v2&&__v2.bootDone&&__v2.bootDone())", 25)
        wait_until(cdp, "!!(document.querySelector('#tabsBar button.on'))", 10)

        # ---------- B1/B2 通知页拖动 + 松手 ----------
        cdp.eval("__v2.gotoTab('nt')")
        wait_until(cdp, "(function(){try{var f=__v2.frame();return !!(f&&f.contentDocument&&f.contentDocument.querySelectorAll('.gcard').length>=8);}catch(e){return false;}})()", 30)
        time.sleep(0.5)
        raw = cdp.eval(NOTICE_DRAG_JS)
        try:
            d = json.loads(raw)
        except Exception:
            d = {"err": str(raw)}
        T("B0 通知页拖动脚本执行", "err" not in d, str(d.get("err", ""))[:160])
        if "err" not in d:
            samples = d.get("samples") or []
            T("B1 通知页拖动：section 全程无 transform", all((s.get("tx") or "") == "" for s in samples),
              json.dumps([s.get("tx") for s in samples if s.get("tx")], ensure_ascii=False)[:180])
            rects = [tuple(s.get("rect") or []) for s in samples]
            T("B2 通知页拖动：iframe 元素 rect 不变（不被位移）", len(set(rects)) <= 1, json.dumps(list(set(rects))[:3]))
            thumbs = [s.get("thumb") or "" for s in samples]
            changed = len(set(thumbs)) > 1 and any("translate3d" in t for t in thumbs)
            T("B3 通知页拖动：toolbar thumb 跟手（translate3d 变化）", changed,
              json.dumps(thumbs[:4], ensure_ascii=False)[:160])
            T("B4 通知页拖动：横向手势 preventDefault（锁定后）", int(d.get("prevented") or 0) >= 8, d.get("prevented"))
            T("B5 通知页松手：tab 已切换（nt→all）", d.get("tab") == "all", d.get("tab"))
            T("B6 通知页松手：切后 section 仍无 transform",
              (d.get("afterCommit") or {}).get("tx") == "", (d.get("afterCommit") or {}).get("tx"))
            # 320ms 点击抑制：切后立刻点 draw 应被抑制（必须在 320ms 窗口内断言）
            time.sleep(0.02)
            cdp.eval("try{document.querySelector('#tabsBar button[data-tab=\"draw\"]').click();}catch(e){}")
            time.sleep(0.15)
            tab_suppressed = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
            T("B7 切 tab 后 320ms 内点击被抑制（不会误触回其他页）", tab_suppressed != "draw", tab_suppressed)
            time.sleep(0.45)
            cdp.eval("try{document.querySelector('#tabsBar button[data-tab=\"draw\"]').click();}catch(e){}")
            time.sleep(0.3)
            tab_after = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
            T("B8 320ms 后点击恢复正常", tab_after == "draw", tab_after)
            time.sleep(0.3)
            clean0 = json.loads(cdp.eval(CLEANUP_JS) or "{}")
            T("B9 通知页滑出后：无 zq-flying / 无内联 animation 残留",
              (not clean0.get("flying")) and clean0.get("animFree", True), json.dumps(clean0, ensure_ascii=False)[:180])
            T("B10 通知页滑出后：目标页无任何 section transform 残留",
              bool(clean0.get("gone")), json.dumps(clean0.get("secs"), ensure_ascii=False)[:180])

        # ---------- B3 其它页面 fly 动画 ----------
        cdp.eval("__v2.gotoTab('draw')")
        time.sleep(0.6)
        time.sleep(0.7)
        cdp.eval(FLY_JS)
        time.sleep(0.15)
        flying_mid = False
        time.sleep(0.9)
        rec = cdp.eval("JSON.stringify(window.__x5)")
        try:
            recs = json.loads(rec)
        except Exception:
            recs = {"styles": [], "classes": []}
        styles = recs.get("styles") or []
        tforms = [s for s in styles if "translate3d(" in (s.get("st") or "")]
        # 只关心 section 页面本体的 fly；工具栏滑块（tabs-thumb）的 opacity 是既有液体动效，不算页面淡入
        opac = [s for s in styles if "opacity" in (s.get("st") or "")
                and (String(s.get("tag")) == "SECTION" or String(s.get("id") or "").startswith("s-"))]
        T("B11 非通知页 fly：发生 translate3d 位移动画", len(tforms) > 0, len(tforms))
        T("B12 非通知页 fly：section 本体无 opacity 内联动画", len(opac) == 0, json.dumps(opac[:2], ensure_ascii=False)[:180])
        clean = json.loads(cdp.eval(CLEANUP_JS) or "{}")
        T("B13 fly 结束后内联 transform/transition 已清理", bool(clean.get("gone")), json.dumps(clean.get("secs"), ensure_ascii=False)[:200])
        T("B14 fly 后无 zq-flying/内联 animation 残留", (not clean.get("flying")) if clean.get("animFree", True) else False, "")

        # ---- B15/B16: fly 进行中点击 tab / 连续拖动 → 700ms 后无残留 ----
        cdp.eval("__v2.gotoTab('draw')")
        time.sleep(0.5)
        time.sleep(0.7)
        cdp.eval(FLY_JS)  # 触发一次工具页 fly（抽签/分组已无 STEP 手势）
        time.sleep(0.36)  # 等 320ms 点击抑制窗口过去，但 fly 仍在进行（约 530ms 结束）
        cdp.eval("try{document.querySelector('#tabsBar button[data-tab=\"hw\"]').click();}catch(e){}");
        time.sleep(0.8)
        clean1 = json.loads(cdp.eval(CLEANUP_JS) or "{}")
        tab1 = cdp.eval("(document.querySelector('#tabsBar button.on')||{}).dataset.tab||''")
        T("B15 fly 进行中点击 tab：700ms 后无残留 transform/transition、目标页正确",
          bool(clean1.get("gone")) and tab1 == "hw", json.dumps({"clean": clean1.get("gone"), "tab": tab1}))

        # 连续快速切页（含 fly 中断）
        cdp.eval("__v2.gotoTab('draw')")
        time.sleep(0.4)
        cdp.eval(FLY_JS)
        time.sleep(0.05)
        for tb in ("tt", "nt", "all", "draw"):
            cdp.eval("try{document.querySelector('#tabsBar button[data-tab=\"%s\"]').click();}catch(e){}" % tb)
            time.sleep(0.06)
        time.sleep(0.9)
        clean2 = json.loads(cdp.eval(CLEANUP_JS) or "{}")
        T("B16 连续快速切页（fly 中断）：最终无残留样式、未出现错位页",
          bool(clean2.get("gone")), json.dumps(clean2.get("secs"), ensure_ascii=False)[:200])

        errs = cdp.eval("JSON.stringify(__v2.errs())") or "[]"
        T("C1 全程 0 JS 报错", errs == "[]", errs[:300])
    finally:
        if cdp:
            cdp.close()
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        if srv:
            srv.shutdown()
            srv.server_close()
        try:
            devnull.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(prof, ignore_errors=True)


def main():
    static_checks()
    run()
    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print("=" * 60)
    print("v2_x5_anim_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 60)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
