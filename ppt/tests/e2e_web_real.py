# -*- coding: utf-8 -*-
"""Lead 独立验收：用真实云端 deck + 真实 OSS 资源，在 headless Edge 里跑网页播放器。

- 页面：本地 http 服务打开 web/tools/index.html（当前工作区版本）
- 身份：测试身份（3260799999/测试账号）真实 token 注入 localStorage
- 网络：--disable-web-security 绕过本地 origin 的 CORS（生产 origin tool.furina.fun 已在网关白名单；
  这里只验证功能链路）；_cloud_guard 拦截云端**写**请求（只放行读与只读 RPC，确保 0 云端写）
- 真实打 OSS 图片/视频，因此能验证 manifest/URL/图片解码/热点/键盘手势
用法：
  python web_e2e_real.py [--deck d...] [--width 1280] [--height 800] [--shots <dir>]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
QA = r"C:\Users\Ko_Li\.openclaw\workspace\web\tools\tests\_qa_v2"
sys.path.insert(0, QA)
import _cdp  # noqa: E402
import _webqa  # noqa: E402
import _cloud_guard  # noqa: E402

PUB = open(r"C:\Users\Ko_Li\.openclaw\workspace\web\deploy\cloudbase\publish_key.txt", encoding="utf-8").read().strip()
BASE = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
SHOTS = os.path.join(HERE, "shots_ppt")


def cloud(method, path, body=None, headers=None):
    h = {"Authorization": "Bearer " + PUB, "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_token():
    st, b = cloud("POST", "rpc/class_verify", {"p_sid": "3260799999", "p_name": "测试账号"})
    assert st == 200, (st, b[:300])
    return json.loads(b)["token"]


def key(page, key, code, vk):
    page.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "code": code,
                                         "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})
    page.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": code,
                                         "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})
    time.sleep(0.12)


def wait_idx(page, prev, timeout=8.0):
    """等 #pptIdx 文本变化（真实 OSS 图片加载/转场需要时间）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = page.evaluate("(document.getElementById('pptIdx')||{}).textContent||''")
        if v != prev:
            return v
        time.sleep(0.15)
    return prev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="dd3xpuazwls")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--mobile", action="store_true")
    ap.add_argument("--video", action="store_true", help="deck 含视频：打开热点并检查 <video>")
    ap.add_argument("--shots", default=SHOTS)
    args = ap.parse_args()
    os.makedirs(args.shots, exist_ok=True)

    # 先确认 deck 可播 + 拿 manifest 期望值（需要测试身份 token 才能读）
    tok = test_token()
    st, b = cloud("GET", "ppt_decks?select=id,title,status,slide_count,step_count,manifest&id=eq." + args.deck,
                  headers={"X-Device-Id": tok})
    assert st == 200 and b, (st, b[:200])
    row = json.loads(b)[0]
    assert row["status"] == "ready", row["status"]
    man = row["manifest"] or {}
    exp_slides = len(man.get("slides") or [])
    exp_steps = sum(len(s.get("steps") or []) for s in (man.get("slides") or []))
    print("[cloud] deck=%s title=%s slides=%d steps=%d media=%d" % (
        args.deck, row["title"], exp_slides, exp_steps, len(man.get("media") or [])))

    ident = {"token": tok, "sid": "3260799999", "name": "测试账号", "role": "", "badge": "",
             "is_admin": False, "ts": int(time.time() * 1000)}
    init_js = ("try{localStorage.setItem('zq_class_identity',%s);"
               "localStorage.setItem('zq_last_identity',%s);}catch(e){}"
               % (json.dumps(json.dumps(ident, ensure_ascii=False)),
                  json.dumps(json.dumps(ident, ensure_ascii=False))))
    # 页面会读取 UD 等；把无关的工具页轮询拉取照常（只读），写请求由 guard 拦截

    srv = _webqa._Server()
    srv.start()
    browser = _cdp.Browser(window=(args.width, args.height),
                           extra_flags=["--disable-web-security", "--allow-running-insecure-content"])
    page = None
    try:
        page = browser.new_page("about:blank")
        page.add_init_script(init_js)
        if args.mobile:
            page.set_device(args.width, args.height, dpr=2.0, mobile=True, touch=True)
            page.set_mobile_ua(args.width)
        guard = _cloud_guard.install_write_block(page)
        url = "http://127.0.0.1:%d/index.html" % srv.port
        page.navigate(url)
        page.wait_load(timeout=30)
        ok = page.wait_for("(function(){try{return !document.body.classList.contains('id-locked')"
                           "&&!!document.querySelector('#tabsBar button');}catch(e){return false;}})()", timeout=25)
        print("[page] boot:", ok, "| PPT api:", page.evaluate("window.PPT?'yes':'no'"))
        assert ok, "页面未通过身份/启动"
        assert page.evaluate("window.PPT?'yes':'no'") == "yes", "PPT 模块未加载"
        page.sleep(1.0)
        page.screenshot(os.path.join(args.shots, "01_home.png"))

        # 列表页：走真实 UI 路径（全部 → 演示卡片）
        page.evaluate("(function(){var b=document.querySelector('#tabsBar button[data-tab=all]');if(b)b.click();})()")
        card_ok = page.wait_for("(function(){var c=document.querySelector('#allCards [data-open=ppt]');"
                                "return !!c;})()", timeout=15)
        if card_ok:
            page.evaluate("(function(){var c=document.querySelector('#allCards [data-open=ppt]');if(c)c.click();})()")
        else:
            page.evaluate("window.PPT.enter()")
        got = page.wait_for("(function(){var l=document.getElementById('pptList');"
                            "return !!(l&&l.children.length);})()", timeout=25)
        page.sleep(1.2)
        list_txt = page.evaluate("(function(){var s=document.getElementById('pptStat');"
                                 "var l=document.getElementById('pptList');"
                                 "return (s&&!s.hidden?s.textContent:'')+' | cards='+(l?l.children.length:0);})()")
        print("[list]", bool(got), list_txt)
        page.screenshot(os.path.join(args.shots, "02_list.png"))

        # 播放器：真实 manifest + OSS 图片
        page.evaluate("window.PPT.open(%s)" % json.dumps(args.deck))
        okp = page.wait_for("(function(){var r=document.getElementById('pptPlayer');"
                            "if(!r)return false;"
                            "var a=document.querySelectorAll('#pptPlayer .ppt-layer img');"
                            "for(var k=0;k<a.length;k++){if(a[k].naturalWidth>0)return true;}"
                            "return false;})()", timeout=40)
        print("[player] open+first image:", okp)
        page.sleep(0.8)
        idx0 = page.evaluate("(document.getElementById('pptIdx')||{}).textContent||''")
        page.screenshot(os.path.join(args.shots, "03_player_s1.png"))
        print("[player] idx0:", idx0)

        # 点击右 2/3 前进（移动端用可信触摸点击）
        w, h = args.width, args.height
        if args.mobile:
            page.touch_tap(int(w * 0.82), int(h * 0.5))
        else:
            page.click(int(w * 0.82), int(h * 0.5))
        idx1 = wait_idx(page, idx0, 8.0)
        img_ok = page.evaluate("(function(){var a=document.querySelectorAll('#pptPlayer .ppt-layer img');"
                               "for(var k=0;k<a.length;k++){if(a[k].naturalWidth>0)return true;}"
                               "return false;})()")
        page.screenshot(os.path.join(args.shots, "04_player_s2.png"))
        print("[player] after click idx1:", idx1, "img:", img_ok)

        # 键盘前进/后退
        key(page, "ArrowRight", "ArrowRight", 39)
        idx2 = wait_idx(page, idx1, 8.0)
        key(page, "ArrowLeft", "ArrowLeft", 37)
        idx3 = wait_idx(page, idx2, 8.0)
        print("[player] key right:", idx2, "| key left(back):", idx3)

        # 点击左 1/3 后退
        if args.mobile:
            page.touch_tap(int(w * 0.12), int(h * 0.5))
        else:
            page.click(int(w * 0.12), int(h * 0.5))
        idx4 = wait_idx(page, idx3, 8.0)
        print("[player] click-left idx:", idx4)

        # 移动端：左右滑动翻步
        if args.mobile:
            page.touch_swipe(int(w * 0.82), int(h * 0.5), int(w * 0.18), int(h * 0.5), steps=8)
            idx5 = wait_idx(page, idx4, 8.0)
            page.touch_swipe(int(w * 0.18), int(h * 0.5), int(w * 0.82), int(h * 0.5), steps=8)
            idx6 = wait_idx(page, idx5, 8.0)
            page.screenshot(os.path.join(args.shots, "04b_mobile_swipe.png"))
            print("[player] swipe next:", idx5, "| swipe back:", idx6)

        # 缩略图抽屉
        page.evaluate("document.querySelector('#pptCtl [data-act=thumbs]').click()")
        page.sleep(0.6)
        th = page.evaluate("(function(){var d=document.getElementById('pptThumbs');"
                           "var n=document.querySelectorAll('#pptThumbsRow img').length;"
                           "return {open:!!(d&&d.classList.contains('on')),n:n};})()")
        page.screenshot(os.path.join(args.shots, "05_player_thumbs.png"))
        print("[player] thumbs:", th)
        idx_base = page.evaluate("(document.getElementById('pptIdx')||{}).textContent||''")
        clicked = page.evaluate("(function(){var a=document.querySelectorAll('#pptThumbsRow [data-thumb]');"
                                "if(!a.length)return false;var b=a[a.length-1];b.click();return true;})()")
        idx_end = wait_idx(page, idx_base, 10.0)
        page.screenshot(os.path.join(args.shots, "05b_player_last.png"))
        print("[player] thumb jump:", clicked, "->", idx_end)
        page.evaluate("document.querySelector('#pptCtl [data-act=thumbs]').click()")
        page.sleep(0.5)
        page.evaluate("(function(){var b=document.querySelector('#pptThumbsRow [data-thumb=\"0\"]');if(b)b.click();})()")
        page.sleep(1.0)
        page.evaluate("(function(){var m=document.getElementById('pptMask');if(m)m.click();})()")
        page.sleep(0.4)

        # 备注抽屉
        page.evaluate("document.querySelector('#pptCtl [data-act=notes]').click()")
        page.sleep(0.5)
        nt = page.evaluate("(function(){var d=document.getElementById('pptNotes');"
                           "return {open:!!(d&&d.classList.contains('on')),"
                           "text:(document.getElementById('pptNoteBody')||{}).textContent||''};})()")
        page.screenshot(os.path.join(args.shots, "06_player_notes.png"))
        print("[player] notes:", json.dumps(nt, ensure_ascii=False)[:160])
        page.evaluate("document.getElementById('pptMask').click()")
        page.sleep(0.3)

        # 黑屏
        page.evaluate("document.querySelector('#pptCtl [data-act=black]').click()")
        page.sleep(0.4)
        black = page.evaluate("(function(){var b=document.getElementById('pptBlack');"
                              "return !!(b&&!b.hidden);})()")
        page.screenshot(os.path.join(args.shots, "07_player_black.png"))
        page.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "b", "code": "KeyB",
                                             "windowsVirtualKeyCode": 66, "nativeVirtualKeyCode": 66})
        page.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "b", "code": "KeyB",
                                             "windowsVirtualKeyCode": 66, "nativeVirtualKeyCode": 66})
        page.sleep(0.4)
        black2 = page.evaluate("(function(){var b=document.getElementById('pptBlack');"
                               "return !!(b&&!b.hidden);})()")
        print("[player] black on:", black, "after B:", black2)

        # 视频 media（可选）
        if args.video:
            # 找带 media 的页：从 manifest 里定位
            hit = None
            for si, s in enumerate(man.get("slides") or []):
                for stp in s.get("steps") or []:
                    if stp.get("media"):
                        hit = (si, stp.get("media")[0])
                        break
                if hit:
                    break
            if hit:
                # 用缩略图跳到该页
                page.evaluate("(function(){var n=document.getElementById('pptCtl');"
                              "n.querySelector('[data-act=thumbs]').click();})()")
                page.sleep(0.5)
                page.evaluate("(function(){var r=document.getElementById('pptThumbsRow');"
                              "var i=r&&r.children[%d];if(i)i.click();})()" % hit[0])
                page.sleep(0.9)
                hot = page.evaluate("(function(){var h=document.getElementById('pptHot');"
                                    "return {n:h?h.children.length:0,"
                                    "html:(h?h.innerHTML:'').slice(0,120)};})()")
                page.screenshot(os.path.join(args.shots, "09_player_media_btn.png"))
                print("[player] media hotspots:", json.dumps(hot, ensure_ascii=False)[:220])
                # 点击热点播放
                page.evaluate("(function(){var b=document.querySelector('#pptHot button');if(b)b.click();})()")
                page.sleep(float(hit[1].get("dur") or 2) * 0.5 + 1.0)
                mv = page.evaluate("(function(){var v=document.querySelector('#pptMediaOv video');"
                                   "if(!v)return {has:false};return {has:true,paused:v.paused,"
                                   "t:v.currentTime,dur:v.duration,err:v.error?v.error.code:0,"
                                   "w:v.videoWidth,h:v.videoHeight};})()")
                page.screenshot(os.path.join(args.shots, "10_player_video.png"))
                print("[player] video:", json.dumps(mv, ensure_ascii=False))
                page.evaluate("(function(){var x=document.querySelector('#pptMediaOv .ppt-mclose');"
                              "if(x)x.click();})()")
                page.sleep(0.4)
            else:
                print("[player] WARN: deck 无 media 页")

        # 退出播放器（有进度会弹站内确认；最多重试 3 次）
        page.evaluate("(function(){var b=document.querySelector('#pptPlayer [data-act=close]');if(b)b.click();})()")
        for _i in range(4):
            page.sleep(0.8)
            stt = page.evaluate("(function(){var pl=document.getElementById('pptPlayer');"
                                "var cf=document.getElementById('pptConfirm');"
                                "return {player:!!pl,confirm:!!(cf&&!cf.hidden),"
                                "black:!!(document.getElementById('pptBlack')&&!document.getElementById('pptBlack').hidden),"
                                "media:!!(document.getElementById('pptMediaOv')&&!document.getElementById('pptMediaOv').hidden)};})()")
            print("[close] try", _i, stt)
            if not stt["player"]:
                break
            if stt["confirm"]:
                page.evaluate("(function(){var b=document.querySelector('#pptConfirm [data-act=leave]');if(b)b.click();})()")
            else:
                page.evaluate("(function(){var b=document.querySelector('#pptPlayer [data-act=close]');if(b)b.click();})()")
        page.sleep(0.5)
        closed = page.evaluate("(function(){return !document.getElementById('pptPlayer');})()")
        errs = page.all_errors()
        print("[player] closed:", closed)
        print("[net] gateway_requests=%d oss_images=%d" % (
            len([u for u in page.network_urls() if "tcloudbasegateway" in u]),
            len([u for u in page.network_urls() if "aliyuncs.com/ppt/" in u])))
        print("[guard] seen=%d blocked=%d released_rpc=%d" % (guard["seen"], guard["blocked"], guard["released_rpc"]))
        print("[errors] console=%s exceptions=%s log=%s" % (
            len(page.console_errors()), len(page.exceptions()), len(page.log_errors())))
        for e in (page.console_errors() + page.exceptions())[:5]:
            print("   !", str(e)[:300])
        print("RESULT:", "PASS" if (okp and closed and not page.exceptions() and black and not black2) else "CHECK")
        return 0
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass
        browser.close()
        srv.stop()


if __name__ == "__main__":
    sys.exit(main())
