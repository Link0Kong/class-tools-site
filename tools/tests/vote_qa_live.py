# -*- coding: utf-8 -*-
"""投票功能独立验收 · 真实云端登录冒烟（本地临时通道 + 真实测试身份 + 真实 CloudBase）。

流程：deploy/local_channel.py 同源代理 CloudBase → headless Edge 打开 → 测试身份
（3260799999 / 测试账号）真实登录 → 进入投票页 → 界面发起（限时 5 分钟/匿名/投后可见）→
界面投票 → 真实 RPC 校验 → 界面删除 → 真实 RPC 校验软删 → SQL 硬删除测试数据与本次会话 token。

云端写保护：CDP Fetch 只放行 GET/HEAD/OPTIONS 与 POST `__cb/rpc/poll_*`、`class_verify`、`class_members`；
其余云写（visits / userdata / marks…）fail —— 与 AGENTS §15 口径一致。
不打印 token / 不读取任何凭据文件。

运行：cd web/tools && python tests\\vote_qa_live.py
截图：tools/tests/_shots_vote_qa/live_*.png
"""
import importlib.util
import json
import os
import socket
import sys
import threading
import time

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
import _cdp  # noqa: E402

REST = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
KEY = open(os.path.join(WEB, "deploy", "cloudbase", "publish_key.txt"), encoding="utf-8").read().strip()
TEST_SID, TEST_NAME = "3260799999", "测试账号"
SHOTS = os.path.join(HERE, "_shots_vote_qa")
os.makedirs(SHOTS, exist_ok=True)
RESULTS = []
STATE = {"pid": "", "token": ""}

_spec = importlib.util.spec_from_file_location("apply_sql", os.path.join(WEB, "deploy", "cloudbase", "apply_sql.py"))
_apply_sql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_apply_sql)


def sql(stmt):
    return _apply_sql.run_stmt(1, stmt, False)


def sql_quiet(stmt):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return _apply_sql.run_stmt(1, stmt, False)


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


def hdr(tok):
    return {"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
            "X-Device-Id": tok, "Origin": "https://tool.furina.fun"}


def rpc(name, body, tok):
    try:
        r = requests.post(REST + "rpc/" + name, headers=hdr(tok), json=body or {}, timeout=60)
        return r.status_code, r.json()
    except Exception as e:  # noqa: BLE001
        return 0, {"reason": "request-error:%s" % e}


def ev(pg, expr, ap=False):
    return pg.evaluate(expr, await_promise=ap)


def jsq(s):
    return json.dumps(s, ensure_ascii=False)


def click(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.click();return true;})()" % jsq(sel))


def set_val(pg, sel, v):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;"
                 "var d=Object.getOwnPropertyDescriptor(e.tagName==='TEXTAREA'?window.HTMLTextAreaElement.prototype:window.HTMLInputElement.prototype,'value');"
                 "d.set.call(e,%s);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));"
                 "return true;})()" % (jsq(sel), jsq(v)))


def text_of(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);return e?String(e.textContent||''):'';})()" % jsq(sel))


def free_port():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def start_channel(port):
    import http.server
    import socketserver
    spec = importlib.util.spec_from_file_location("local_channel", os.path.join(WEB, "deploy", "local_channel.py"))
    lc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lc)

    class Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            pass

    srv = Srv(("127.0.0.1", port), lc.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def install_poll_guard(page):
    """只放行读请求 + poll_* / 登录 / 名单 RPC；其余云端写 fail（防污染其它业务数据）。"""
    orig = page._dispatch
    state = {"blocked": 0, "seen": 0, "allowed_rpc": 0}

    def send_raw(method, params):
        page._id += 1
        page.ws.send(json.dumps({"id": page._id, "method": method, "params": params}))

    def patched(msg):
        if msg.get("method") == "Fetch.requestPaused":
            p = msg.get("params", {}) or {}
            req = p.get("request", {}) or {}
            method = (req.get("method") or "GET").upper()
            url = req.get("url") or ""
            state["seen"] += 1
            allow = method in ("GET", "HEAD", "OPTIONS") or (
                method == "POST" and ("/rpc/poll_" in url or "/rpc/class_verify" in url
                                      or "/rpc/class_members" in url))
            try:
                if allow:
                    if method == "POST":
                        state["allowed_rpc"] += 1
                    send_raw("Fetch.continueRequest", {"requestId": p.get("requestId")})
                else:
                    state["blocked"] += 1
                    send_raw("Fetch.failRequest", {"requestId": p.get("requestId"), "errorReason": "BlockedByClient"})
            except Exception:
                pass
            return
        orig(msg)

    page._dispatch = patched
    page.send("Fetch.enable", {"patterns": [{"urlPattern": "*__cb*", "requestStage": "Request"}]})
    return state


def main():
    port = free_port()
    srv = start_channel(port)
    b = _cdp.Browser(window=(430, 900))
    title = "QA独立验收投票_%d" % int(time.time())
    try:
        pg = b.new_page("about:blank")
        pg.set_device(430, 900, 2.0, True, True)
        pg.add_init_script(
            "window.confirm=function(){return true;};"
            "window.__errs=[];window.addEventListener('error',function(e){window.__errs.push(String(e&&e.message));});"
            "window.addEventListener('unhandledrejection',function(e){var r=e&&e.reason;"
            "window.__errs.push('rejection:'+String((r&&r.message)||r));});")
        guard = install_poll_guard(pg)
        pg.navigate("http://127.0.0.1:%d/" % port)
        pg.wait_load(25)
        T("L1 本地临时通道 + 真实页面加载（身份页出现）", pg.wait_for("!!document.getElementById('igGo')", 10))
        # ---- 真实登录 ----
        set_val(pg, "#igSid", TEST_SID)
        set_val(pg, "#igName", TEST_NAME)
        click(pg, "#igGo")
        ok = pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof VOTE!=='undefined'", 30)
        T("L2 测试身份真实登录成功（class_verify）+ VOTE 装载", ok)
        tok = ""
        try:
            tok = json.loads(ev(pg, "localStorage.getItem('zq_class_identity')||'{}'")).get("token") or ""
        except Exception:
            tok = ""
        STATE["token"] = tok
        T("L3 登录后取得真实班级 token（不打印）", bool(tok))
        if not tok:
            return RESULTS
        # ---- 进入投票页 ----
        click(pg, '#tabsBar button[data-tab="all"]')
        pg.wait_for("document.querySelector('#allCards [data-card=\"vote\"]')!==null", 12)
        click(pg, '[data-open="vote"]')
        T("L4 进入投票页（真实 poll_list 请求返回、无白屏）",
          pg.wait_for("document.querySelector('#s-vote').classList.contains('on')", 12)
          and pg.wait_for("window.VOTE.loaded()===true", 15))
        # ---- 界面发起（真实 poll_create） ----
        click(pg, "#voteNew")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display!=='none';})()", 8)
        set_val(pg, "#voteTitle", title)
        set_val(pg, "#voteDesc", "独立验收 · 真实云端冒烟")
        click(pg, '#voteQuick button[data-min="5"]')
        set_val(pg, '#voteOpts input[data-ot="0"]', "选项甲")
        set_val(pg, '#voteOpts input[data-ot="1"]', "选项乙")
        click(pg, "#voteCreateGo")
        ok = pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display!=='none';})()", 25)
        pid = ""
        try:
            pid = ev(pg, "(function(){try{return window.VOTE.detail().poll.id;}catch(e){return '';}})()")
        except Exception:
            pid = ""
        STATE["pid"] = pid
        T("L5 界面发起投票成功并打开详情（真实云端）", ok and bool(pid), pid)
        if not pid:
            return RESULTS
        # ---- 真实 RPC 校验创建结果 ----
        st, d = rpc("poll_detail", {"p_id": pid}, tok)
        T("L6 真实 RPC：详情可读、0 票、owner_name=测试账号、无 sid",
          d.get("ok") is True and d.get("total") == 0
          and (d.get("poll") or {}).get("owner_name") == TEST_NAME
          and '"sid"' not in json.dumps(d), str(d)[:150])
        dl = int((d.get("poll") or {}).get("deadline") or 0)
        T("L7 真实 RPC：限时 5 分钟（deadline-now≈5min）",
          4 * 60000 <= dl - int(time.time() * 1000) <= 6 * 60000,
          "delta=%s" % (dl - int(time.time() * 1000)))
        opt_ids = [(o or {}).get("id") for o in ((d.get("poll") or {}).get("options") or [])]
        T("L8 真实 RPC：匿名 + 投票后可见 + 允许改票 + 单选（服务端 canonical settings）",
          (d.get("poll") or {}).get("settings") == {"multi": False, "maxChoices": 1, "anonymous": True,
                                                    "allowChange": True, "resultVisibility": "afterVote"},
          str((d.get("poll") or {}).get("settings")))
        T("L9 未投票时详情无结果条（afterVote 隐藏）", "投票后可见" in text_of(pg, "#voteDetailBody")
          and ev(pg, "document.querySelectorAll('#voteDetailBody .vd-bar').length") == 0)
        # ---- 界面投票 ----
        click(pg, '.vd-opt[data-oid="%s"]' % opt_ids[0])
        click(pg, "#voteSubmit")
        T("L10 界面投票成功（真实 poll_submit，结果条出现）",
          pg.wait_for("document.querySelectorAll('#voteDetailBody .vd-bar').length>0", 20))
        st, d = rpc("poll_detail", {"p_id": pid}, tok)
        T("L11 真实 RPC：1 票、本人已投、counts 正确",
          d.get("ok") is True and d.get("total") == 1 and d.get("has_voted") is True
          and (d.get("counts") or {}).get(opt_ids[0]) == 1, str(d.get("counts")))
        pg.screenshot(os.path.join(SHOTS, "live_detail_430.png"))
        # ---- 列表回显 ----
        click(pg, "#voteDetailClose")
        pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display==='none';})()", 8)
        pg.wait_for("document.querySelector('.vote-card[data-id=\"%s\"]')!==null" % pid, 10)
        T("L12 列表卡片回显「1人已投 / 我已投」",
          "1人已投" in text_of(pg, '.vote-card[data-id="%s"]' % pid)
          and "我已投" in text_of(pg, '.vote-card[data-id="%s"]' % pid))
        # ---- 390 无横向溢出 ----
        pg.set_device(390, 844, 2.0, True, True)
        pg.sleep(0.35)
        T("L13 390px：真实投票列表无横向溢出",
          ev(pg, "document.documentElement.scrollWidth<=window.innerWidth+1"),
          "scrollW=%s vw=%s" % (ev(pg, "document.documentElement.scrollWidth"), ev(pg, "window.innerWidth")))
        pg.screenshot(os.path.join(SHOTS, "live_list_390.png"))
        # ---- 隐私：页面无学号/手机号 ----
        body = ev(pg, "document.body.innerText") or ""
        T("L14 真实页面文本无测试身份学号/手机号泄露", TEST_SID not in body and "3260799999" not in body)
        # ---- 界面删除（软删） ----
        pg.set_device(430, 900, 2.0, True, True)
        pg.sleep(0.3)
        click(pg, '.vote-card[data-id="%s"]' % pid)
        pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display!=='none';})()", 10)
        click(pg, '[data-vm="delete"]')
        T("L15 界面删除成功（软删，弹层关闭）",
          pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display==='none';})()", 20))
        st, d = rpc("poll_detail", {"p_id": pid}, tok)
        T("L16 真实 RPC：删除后详情不可查（投票不存在）",
          d.get("ok") is False and "不存在" in str(d.get("reason")), d.get("reason"))
        st, rl = rpc("poll_list", {}, tok)
        T("L17 真实 RPC：删除后列表不再返回该投票",
          rl.get("ok") is True and all(x.get("id") != pid for x in (rl.get("polls") or [])))
        # ---- 写保护 / 报错 ----
        T("L18 云端写保护生效（非投票云写被拦截，poll_* 放行）",
          guard["blocked"] >= 1 and guard["allowed_rpc"] >= 4,
          "blocked=%d allowed_rpc=%d seen=%d" % (guard["blocked"], guard["allowed_rpc"], guard["seen"]))
        errs = pg.all_errors()
        win_errs = json.loads(ev(pg, "JSON.stringify(window.__errs||[])"))
        T("L19 真实云端页面 0 未捕获 JS 异常",
          len(errs.get("exceptions") or []) == 0 and not win_errs,
          json.dumps({"exceptions": (errs.get("exceptions") or [])[:2], "win": win_errs[:2]})[:300])
        return RESULTS
    finally:
        try:
            if STATE["pid"]:
                sql("delete from public.poll_votes where poll_id = '%s'" % STATE["pid"])
                sql("delete from public.polls where id = '%s'" % STATE["pid"])
                print("[cleanup] 测试投票硬删除 pid=%s" % STATE["pid"])
            if STATE["token"]:
                sql_quiet("delete from private.class_sessions where token = '%s'" % STATE["token"])
                print("[cleanup] 本次测试身份会话已删除")
        except Exception as e:  # noqa: BLE001
            print("[cleanup] FAILED: %s" % e)
        try:
            b.close()
        except Exception:
            pass
        try:
            srv.shutdown()
        except Exception:
            pass
        fails = len([x for x in RESULTS if not x["ok"]])
        okn = len(RESULTS) - fails
        with open(os.path.join(SHOTS, "live_report.json"), "w", encoding="utf-8") as f:
            json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "pass": okn, "fail": fails,
                       "results": RESULTS}, f, ensure_ascii=False, indent=2)
        print("\n=========== vote_qa_live: %d PASS / %d FAIL ===========" % (okn, fails))
        sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(main())
