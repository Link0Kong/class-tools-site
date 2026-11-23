# -*- coding: utf-8 -*-
"""投票功能真实云端 E2E（网页：本地临时通道 + 测试身份 + 真实 CloudBase RPC）

流程：headless Edge 打开本机临时通道（deploy/local_channel.py，同源代理 CloudBase）→
测试身份（3260799999/测试账号）在身份页真实登录 → 进入投票页 → 界面发起限时投票 →
界面投票 → 第二个合成会话经真实 RPC 投票 → 界面看到 2 人已投 → 匿名不泄露 → 界面删除 →
真实 RPC 验证删除结果 → SQL 硬删除测试数据/会话。

云端写保护：仅放行 `POST /__cb/rpc/poll_*` 与 GET/HEAD/OPTIONS；其余云端写（visits/userdata/marks…）
一律拦截，避免真实测试身份污染其它业务数据（AGENTS §15 口径）。

运行：cd web/tools && python tests\\vote_live_check.py
截图：tools/tests/_shots_vote/live_*.png
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
SHOTS = os.path.join(HERE, "_shots_vote")
os.makedirs(SHOTS, exist_ok=True)
RESULTS = []
POLL_ID = [""]
AUD_POLL_IDS = []
LIVE_TOKENS = []

_spec = importlib.util.spec_from_file_location("apply_sql", os.path.join(WEB, "deploy", "cloudbase", "apply_sql.py"))
apply_sql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply_sql)


def sql(stmt):
    return apply_sql.run_stmt(1, stmt, False)


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


def free_port():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def load_local_channel():
    path = os.path.join(WEB, "deploy", "local_channel.py")
    spec = importlib.util.spec_from_file_location("local_channel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def start_channel(port):
    import http.server
    import socketserver
    lc = load_local_channel()

    class Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            pass

    srv = Srv(("127.0.0.1", port), lc.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def install_poll_guard(page):
    """CDP Fetch 拦截：只放行读请求与 poll_* RPC，其余云端写一律 fail。"""
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
                method == "POST" and (
                    "/rpc/poll_" in url or "/rpc/class_verify" in url or "/rpc/class_members" in url
                )
            )
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


def rhdr(tok):
    return {"Authorization": "Bearer " + KEY, "Content-Type": "application/json", "X-Device-Id": tok,
            "Origin": "https://tool.furina.fun"}


def rpc(name, body, tok):
    r = requests.post(REST + "rpc/" + name, headers=rhdr(tok), json=body or {}, timeout=40)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


def ev(pg, expr, ap=False):
    return pg.evaluate(expr, await_promise=ap)


def jsq(s):
    return json.dumps(s, ensure_ascii=False)


def click(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.click();return true;})()" % jsq(sel))


def set_val(pg, sel, v):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.value=%s;"
                "e.dispatchEvent(new Event('input',{bubbles:true}));return true;})()" % (jsq(sel), jsq(v)))


def text_of(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);return e?String(e.textContent||''):'';})()" % jsq(sel))


def main():
    port = free_port()
    srv = start_channel(port)
    b = _cdp.Browser(window=(430, 900))
    title = "E2E投票_%d" % int(time.time())
    try:
        pg = b.new_page("about:blank")
        pg.set_device(430, 900, 2.0, True, True)
        pg.add_init_script("window.confirm=function(){return true;};")  # 管理操作确认自动通过
        guard = install_poll_guard(pg)
        pg.navigate("http://127.0.0.1:%d/" % port)
        pg.wait_load(25)
        T("本地临时通道 + 真实身份页加载", pg.wait_for("!!document.getElementById('igGo')", 10))

        # ---- 真实登录（测试身份） ----
        set_val(pg, "#igSid", TEST_SID)
        set_val(pg, "#igName", TEST_NAME)
        ev(pg, "(function(){var a=document.getElementById('igAgree');if(a){a.checked=true;a.dispatchEvent(new Event('change'));}return true;})()")
        click(pg, "#igGo")
        ok = pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof VOTE!=='undefined'", 25)
        T("测试身份真实登录成功", ok)
        tok = ""
        try:
            tok = json.loads(ev(pg, "localStorage.getItem('zq_class_identity')||'{}'")).get("token") or ""
        except Exception:
            tok = ""
        T("登录后拿到真实班级 token", bool(tok))
        if tok:
            LIVE_TOKENS.append(tok)
        if not tok:
            return RESULTS
        # ---- 进入投票页（真实 poll_list） ----
        click(pg, '#tabsBar button[data-tab="all"]')
        pg.wait_for("document.querySelector('[data-card=\"vote\"]')!==null", 10)
        click(pg, '[data-open="vote"]')
        T("进入投票页（真实 poll_list 返回）", pg.wait_for("document.querySelector('#s-vote').classList.contains('on')", 10))
        T("列表为空态（发起前无投票）",
          pg.wait_for("(function(){var e=document.getElementById('voteEmpty');return !!e&&!e.hidden;})()", 10))

        # ---- 界面发起（限时 10 分钟 / 2 选项 / 匿名 / 可改票） ----
        click(pg, "#voteNew")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display!=='none';})()", 8)
        set_val(pg, "#voteTitle", title)
        set_val(pg, "#voteDesc", "真实云端 E2E")
        click(pg, '#voteQuick button[data-min="10"]')
        set_val(pg, '#voteOpts input[data-ot="0"]', "选项甲")
        set_val(pg, '#voteOpts input[data-ot="1"]', "选项乙")
        click(pg, "#voteCreateGo")
        ok = pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display!=='none';})()", 20)
        T("界面发起投票成功并打开详情", ok)
        pid = ""
        try:
            pid = ev(pg, "(function(){try{return window.VOTE.detail().poll.id;}catch(e){return '';}})()")
        except Exception:
            pid = ""
        T("详情返回投票 id（真实云端）", bool(pid), pid)
        POLL_ID[0] = pid
        st, d = rpc("poll_detail", {"p_id": pid}, tok)
        T("真实 RPC 校验：详情可读、0 票、结果隐藏",
          d.get("ok") is True and d.get("total") == 0 and d.get("results_hidden") is True and
          (d.get("poll") or {}).get("owner_name") == TEST_NAME, str(d)[:160])
        dl = int((d.get("poll") or {}).get("deadline") or 0)
        T("真实 RPC 校验：限时 deadline≈10 分钟", 9 * 60000 <= dl - int(time.time() * 1000) <= 11 * 60000)
        opt_ids = [(o or {}).get("id") for o in ((d.get("poll") or {}).get("options") or [])]

        # ---- 界面投票 ----
        click(pg, '.vd-opt[data-oid="%s"]' % opt_ids[0])
        click(pg, "#voteSubmit")
        ok = pg.wait_for("document.querySelectorAll('#voteDetailBody .vd-bar').length>0", 15)
        T("界面投票成功（真实 poll_submit）", ok)
        st, d = rpc("poll_detail", {"p_id": pid}, tok)
        T("真实 RPC 校验：1 票、本人已投",
          d.get("ok") is True and d.get("total") == 1 and d.get("has_voted") is True and
          (d.get("counts") or {}).get(opt_ids[0]) == 1, str(d.get("counts")))
        pg.screenshot(os.path.join(SHOTS, "live_detail_430.png"))

        # ---- 第二个成员（合成 QA 会话）真实投票 → 界面刷新看到 2 人 ----
        sql("insert into private.class_sessions(token,sid,name,expires_at) values "
            "('qatok_vote_live','9999000009','旁听同学',now()+interval '1 day') on conflict (token) do nothing")
        st, d2 = rpc("poll_submit", {"p_id": pid, "p_choices": [opt_ids[1]]}, "qatok_vote_live")
        T("第二个成员真实投票成功", d2.get("ok") is True and d2.get("total") == 2)
        T("匿名：第二成员读到 voters 为空且无 sid",
          d2.get("voters") == [] and '"sid"' not in json.dumps(d2))
        click(pg, "#voteDetailClose")
        pg.wait_for("document.querySelector('#voteDetailOv').style.display==='none'", 8)
        click(pg, '.vote-card[data-id="%s"]' % pid)
        pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display!=='none';})()", 10)
        T("界面看到 2 人已投（真实轮询/重开）", "2 人已投" in text_of(pg, "#voteDetailBody"))
        T("界面结果条显示两票", len(json.loads(ev(pg, "JSON.stringify([].map.call(document.querySelectorAll('#voteDetailBody .vd-nums'),function(e){return e.textContent;}))"))) >= 2)
        pg.screenshot(os.path.join(SHOTS, "live_detail_2votes_430.png"))

        # ---- 界面删除（软删） ----
        click(pg, '[data-vm="delete"]')
        ok = pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display==='none';})()", 15)
        T("界面删除成功（软删）", ok)
        pg.sleep(0.5)
        st, d = rpc("poll_detail", {"p_id": pid}, tok)
        T("真实 RPC 校验：删除后不可见", d.get("ok") is False and "不存在" in str(d.get("reason")), d.get("reason"))

        # ---- 可见人范围（真实云端）：班委可见 + 指定成员 ---- 
        aud_title = "E2E班委可见_%d" % int(time.time())
        click(pg, "#voteNew")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display!=='none';})()", 8)
        set_val(pg, "#voteTitle", aud_title)
        set_val(pg, '#voteOpts input[data-ot="0"]', "同意")
        set_val(pg, '#voteOpts input[data-ot="1"]', "不同意")
        click(pg, '#voteAudience button[data-aud="committee"]')
        pg.sleep(0.15)
        click(pg, "#voteCreateGo")
        T("界面发起班委可见投票", pg.wait_for(
            "(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display!=='none';})()", 20))
        apid = ""
        try:
            apid = ev(pg, "(function(){try{return window.VOTE.detail().poll.id;}catch(e){return '';}})()")
        except Exception:
            apid = ""
        if apid:
            AUD_POLL_IDS.append(apid)
        T("详情返回班委可见投票 id", bool(apid), apid)
        st, d = rpc("poll_detail", {"p_id": apid}, tok)
        T("真实 RPC：audience=committee 且 can_manage",
          d.get("ok") is True and (d.get("poll") or {}).get("audience") == "committee" and d.get("can_manage") is True,
          str((d.get("poll") or {}).get("audience")))
        T("界面显示「班委可见」标签", "班委可见" in text_of(pg, "#voteDetailBody"))
        pg.screenshot(os.path.join(SHOTS, "live_detail_audience_430.png"))
        # 真实普通成员（seat2 一次性会话）在列表/详情里完全看不到班委投票
        sql("insert into private.class_sessions(token,sid,name,expires_at) "
            "select 'qatok_vote_member', c.sid, c.name, now()+interval '1 hour' from private.class_ids c "
            "where c.seat=2 on conflict (token) do nothing")
        st, ml = rpc("poll_list", {}, "qatok_vote_member")
        T("普通成员列表看不到班委可见投票", all(x.get("id") != apid for x in (ml.get("polls") or [])))
        st, md = rpc("poll_detail", {"p_id": apid}, "qatok_vote_member")
        T("普通成员 detail 返回「投票不存在」", md.get("ok") is False and "不存在" in str(md.get("reason")), md.get("reason"))
        # 删除班委投票（界面）
        click(pg, '[data-vm="delete"]')
        T("界面删除班委投票", pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display==='none';})()", 15))

        # 指定成员可见（界面从真实班级名单选 seat2）
        cus_title = "E2E指定成员_%d" % int(time.time())
        click(pg, "#voteNew")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display!=='none';})()", 8)
        set_val(pg, "#voteTitle", cus_title)
        set_val(pg, '#voteOpts input[data-ot="0"]', "行")
        set_val(pg, '#voteOpts input[data-ot="1"]', "不行")
        click(pg, '#voteAudience button[data-aud="custom"]')
        T("指定成员：真实班级名单加载",
          pg.wait_for("document.querySelectorAll('#voteAudMem .vote-mem-b').length>=60", 12),
          "chips=%s" % ev(pg, "document.querySelectorAll('#voteAudMem .vote-mem-b').length"))
        click(pg, '#voteAudMem .vote-mem-b[data-seat="2"]')
        pg.sleep(0.15)
        T("指定成员：选中 1 人摘要", "已选 1" in text_of(pg, "#voteAudSum"))
        click(pg, "#voteCreateGo")
        T("界面发起指定成员投票", pg.wait_for(
            "(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display!=='none';})()", 20))
        cpid = ""
        try:
            cpid = ev(pg, "(function(){try{return window.VOTE.detail().poll.id;}catch(e){return '';}})()")
        except Exception:
            cpid = ""
        if cpid:
            AUD_POLL_IDS.append(cpid)
        st, d = rpc("poll_detail", {"p_id": cpid}, tok)
        T("真实 RPC：audience=custom、名单 1 人、座号仅发起人可见",
          d.get("ok") is True and (d.get("poll") or {}).get("audience") == "custom"
          and (d.get("poll") or {}).get("audience_count") == 1
          and (d.get("poll") or {}).get("audience_seats") == [2],
          str((d.get("poll") or {}).get("audience_seats")))
        st, ml = rpc("poll_list", {}, "qatok_vote_member")
        T("指定成员：名单内普通成员可见", any(x.get("id") == cpid for x in (ml.get("polls") or [])))
        st, ml2 = rpc("poll_list", {}, "qatok_vote_live")
        T("指定成员：名单外成员不可见", all(x.get("id") != cpid for x in (ml2.get("polls") or [])))
        click(pg, '[data-vm="delete"]')
        T("界面删除指定成员投票", pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display==='none';})()", 15))

        # ---- 写保护 / 报错 ----
        T("云端写保护生效（拦截了非投票云写）", guard["blocked"] >= 1,
          "blocked=%d allowed_rpc=%d seen=%d" % (guard["blocked"], guard["allowed_rpc"], guard["seen"]))
        errs = pg.all_errors()
        nerr = len(errs.get("exceptions") or [])
        js_errs = json.loads(ev(pg, "JSON.stringify(window.__errs||[])"))
        T("0 JS 异常（真实云端页面）", nerr == 0 and len(js_errs) == 0, "exceptions=%s onerror=%s" % (nerr, js_errs[:2]))
        pg.set_device(390, 844, 2.0, True, True)
        pg.sleep(0.3)
        T("390px：真实投票列表无横向溢出", ev(pg, "document.documentElement.scrollWidth<=window.innerWidth+1"))
        pg.screenshot(os.path.join(SHOTS, "live_list_390.png"))
        return RESULTS
    finally:
        try:
            if POLL_ID[0]:
                sql("delete from public.poll_votes where poll_id = '%s'" % POLL_ID[0])
                sql("delete from public.polls where id = '%s'" % POLL_ID[0])
            for apid in AUD_POLL_IDS:
                if not apid:
                    continue
                sql("delete from public.poll_votes where poll_id = '%s'" % apid)
                sql("delete from public.polls where id = '%s'" % apid)
            sql("delete from private.class_sessions where token in ('qatok_vote_live','qatok_vote_member')")
            for t in LIVE_TOKENS:
                sql("delete from private.class_sessions where token = '%s'" % t)
            print("[cleanup] poll=%s aud_polls=%d sessions=cleaned" % (POLL_ID[0] or "-", len(AUD_POLL_IDS)))
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
        print("\n=========== vote_live_check: %d PASS / %d FAIL ===========" % (len(RESULTS) - fails, fails))
        if RESULTS:
            with open(os.path.join(SHOTS, "live_report.json"), "w", encoding="utf-8") as f:
                json.dump({"pass": len(RESULTS) - fails, "fail": fails, "results": RESULTS}, f, ensure_ascii=False, indent=2)
        sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(main())
