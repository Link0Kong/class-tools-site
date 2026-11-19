# -*- coding: utf-8 -*-
"""水量共享 · 真实云端 E2E（网页：本地临时通道 + 测试身份 + 真实 water/water_room 表）

流程：
  headless Edge 打开本机临时通道（deploy/local_channel.py，同源代理 CloudBase）→
  测试身份（3260799999 / 测试账号）真实登录 → 全部页 → 水量页 →
  选 23B 423（1–6 自选，本次用 5 人）→ 填 2099-07 / 123.45 保存 → 真实 API 校验 water 行 →
  清本机缓存后重载 → 界面从云端恢复该记录 → 界面删除 → 真实 API 校验已删 →
  finally 清理 2099-xx 测试行。
云端写保护：仅放行 GET/HEAD/OPTIONS、POST /rpc/class_verify|class_members、以及
POST/DELETE 到 water / water_room 的写请求；其余云端写（userdata/visits/marks…）一律拦截。
不打印 token / 姓名 / 学号。

运行：cd web/tools && python tests\\v2_web_batch2_water_live_check.py
截图：tools/tests/_shots_web_batch2/live_water_*.png
退出码 0 = 全 PASS。
"""
import importlib.util
import json
import os
import re
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
RV = "4-23B---423"          # 23B（1–6 自选，本次用 5 人）
MONTH = "2099-07"
SHOTS = os.path.join(HERE, "_shots_web_batch2")
os.makedirs(SHOTS, exist_ok=True)
RESULTS = []


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


def install_water_guard(page):
    """只放行读请求 + water/water_room 写 + class_verify/class_members RPC。"""
    orig = page._dispatch
    state = {"blocked": 0, "seen": 0, "allowed_water": 0, "blocked_urls": [], "water_urls": []}

    def send_raw(method, params):
        page._id += 1
        page.ws.send(json.dumps({"id": page._id, "method": method, "params": params}))

    # 页面经本地通道把 CB 基址替换成同源 "/__cb/"，浏览器侧 URL 形如
    #   http://127.0.0.1:<port>/__cb/water?on_conflict=...  /  /__cb/water_room?...
    water_re = re.compile(r"/(water|water_room)(\?|$)")

    def patched(msg):
        if msg.get("method") == "Fetch.requestPaused":
            p = msg.get("params", {}) or {}
            req = p.get("request", {}) or {}
            method = (req.get("method") or "GET").upper()
            url = req.get("url") or ""
            state["seen"] += 1
            allow = method in ("GET", "HEAD", "OPTIONS")
            if not allow and method in ("POST", "DELETE") and water_re.search(url):
                allow = True
                state["allowed_water"] += 1
                state["water_urls"].append(method + " " + url[:180])
            if not allow and method == "POST" and ("/rpc/class_verify" in url or "/rpc/class_members" in url):
                allow = True
            try:
                if allow:
                    send_raw("Fetch.continueRequest", {"requestId": p.get("requestId")})
                else:
                    state["blocked"] += 1
                    state["blocked_urls"].append(method + " " + url[:180])
                    send_raw("Fetch.failRequest", {"requestId": p.get("requestId"), "errorReason": "BlockedByClient"})
            except Exception:
                pass
            return
        orig(msg)

    page._dispatch = patched
    page.send("Fetch.enable", {"patterns": [{"urlPattern": "*__cb*", "requestStage": "Request"}]})
    return state


def api(method, path, token, body=None):
    h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json", "Origin": "https://tool.furina.fun"}
    if token:
        h["X-Device-Id"] = token
        h["X-Class-Token"] = token
    try:
        r = requests.request(method, REST.rstrip("/") + "/" + path, headers=h,
                             data=(json.dumps(body, ensure_ascii=False) if body is not None else None), timeout=40)
        try:
            return r.status_code, r.json()
        except Exception:  # noqa: BLE001
            return r.status_code, None
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def cleanup(token):
    if not token:
        return
    api("DELETE", "water?roomverify=eq.%s&month=eq.%s" % (RV, MONTH), token)
    st, rows = api("GET", "water?select=month&roomverify=eq.%s&month=eq.%s" % (RV, MONTH), token)
    T("清理：测试月份行已删除", st == 200 and rows == [], "status=%s rows=%s" % (st, rows))


def ev(pg, expr, ap=False):
    return pg.evaluate(expr, await_promise=ap)


def jsq(s):
    return json.dumps(s, ensure_ascii=False)


def click(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.click();return true;})()" % jsq(sel))


def set_val(pg, sel, v):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.value=%s;"
                 "e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return true;})()"
              % (jsq(sel), jsq(v)))


def text_of(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);return e?String(e.textContent||''):'';})()" % jsq(sel))


def wait_water_row(token, pred, timeout=12.0):
    """轮询真实云端 water 行直到满足断言（真实网关/代理有 ~0.5–2s 延迟，别用固定 sleep 判死）。"""
    end = time.time() + timeout
    row = None
    st = 0
    while time.time() < end:
        st, rows = api("GET", "water?select=roomverify,month,reading,persons&roomverify=eq.%s&month=eq.%s" % (RV, MONTH), token)
        row = (rows or [None])[0] if isinstance(rows, list) and rows else None
        try:
            if pred(row):
                return True, st, row
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    return False, st, row


def main():
    port = free_port()
    srv = start_channel(port)
    b = _cdp.Browser(window=(430, 900))
    token = ""
    try:
        pg = b.new_page("about:blank")
        pg.set_device(430, 900, 2.0, True, True)
        pg.add_init_script(
            "window.confirm=function(){return true;};"
            "window.__errs=[];window.addEventListener('error',function(e){window.__errs.push(String((e&&e.message)||''));});"
            "window.addEventListener('unhandledrejection',function(e){var r=e&&e.reason;window.__errs.push('rejection:'+String((r&&r.message)||r));});"
            "window.__wresp=[];"
            "(function(){var _f=window.fetch;window.fetch=function(u,o){var p=_f.apply(this,arguments);"
            "try{var s=String((u&&u.url!==undefined)?u.url:u);if(s.indexOf('/water')>=0){var m=String((o&&o.method)||'GET').toUpperCase();"
            "p.then(function(r){window.__wresp.push(m+' '+s+' -> '+r.status);},function(e){window.__wresp.push(m+' '+s+' -> ERR '+String((e&&e.message)||e));});}}catch(x){}"
            "return p;};})();")
        guard = install_water_guard(pg)
        pg.navigate("http://127.0.0.1:%d/" % port)
        pg.wait_load(25)
        T("本地临时通道 + 身份页加载", pg.wait_for("!!document.getElementById('igGo')", 15))

        # ---- 真实登录（测试身份） ----
        set_val(pg, "#igSid", TEST_SID)
        set_val(pg, "#igName", TEST_NAME)
        click(pg, "#igGo")
        ok = pg.wait_for("document.body.classList.contains('auth-pending')===false", 30)
        T("测试身份真实登录成功", ok)
        try:
            token = json.loads(ev(pg, "localStorage.getItem('zq_class_identity')||'{}'").replace("undefined", "null")).get("token") or ""
        except Exception:  # noqa: BLE001
            token = ""
        T("登录后拿到真实班级 token（不打印）", bool(token))
        if not token:
            return RESULTS

        # ---- 进入水量页 ----
        click(pg, '#tabsBar button[data-tab="all"]')
        pg.wait_for("document.querySelector('#allCards [data-card=\"water\"]')!==null", 15)
        click(pg, '#allCards [data-open="water"]')
        T("进入水量页", pg.wait_for("document.getElementById('s-water').classList.contains('on')", 15))

        # ---- 选择 23B 423（1–6 自选，本次用 5 人）----
        set_val(pg, "#wtSel", RV)
        pg.sleep(0.8)
        T("23B 房间人数默认 4 且选择器可用", ev(pg, "(function(){var e=document.getElementById('wtPersons');return e.value==='4'&&!e.disabled;})()"))
        set_val(pg, "#wtPersons", "5")
        pg.sleep(0.5)
        T("23B 房间可切换为 5 人间", ev(pg, "(function(){var e=document.getElementById('wtPersons');return e.value==='5'&&!e.disabled;})()"))
        # ---- 保存一条 2099-07 抄表（真实云端） ----
        set_val(pg, "#wtMonth", MONTH)
        set_val(pg, "#wtReading", "123.45")
        pg.sleep(0.2)
        click(pg, "#wtSave")
        pg.sleep(0.6)
        print("  DEBUG status=%s water_urls=%s blocked=%s" % (
            ev(pg, "(function(){try{return JSON.stringify(window.__B2.water.status());}catch(e){return 'na';}})()"),
            guard.get("water_urls"), guard.get("blocked_urls")))
        ok_w, st, row = wait_water_row(token, lambda r: isinstance(r, dict) and float(r.get("reading")) == 123.45
                                       and int(r.get("persons")) == 5)
        T("真实云端已写入 water 行（2099-07 / 123.45 / persons=5）", ok_w,
          "status=%s row=%s" % (st, row))
        T("界面水费预览/历史已更新", MONTH in text_of(pg, "#wtList") and "123.45" in text_of(pg, "#wtList"))
        # ---- 清本机缓存后重载：从云端恢复（换设备语义） ----
        ev(pg, "(function(){var id=localStorage.getItem('zq_class_identity');localStorage.clear();"
               "if(id)localStorage.setItem('zq_class_identity',id);return true;})()")
        pg.navigate("http://127.0.0.1:%d/" % port)
        pg.wait_load(25)
        pg.wait_for("document.body.classList.contains('auth-pending')===false", 30)
        click(pg, '#tabsBar button[data-tab="all"]')
        pg.wait_for("document.querySelector('#allCards [data-card=\"water\"]')!==null", 15)
        click(pg, '#allCards [data-open="water"]')
        pg.wait_for("document.getElementById('s-water').classList.contains('on')", 15)
        set_val(pg, "#wtSel", RV)
        ok_restore = pg.wait_for("(function(){var l=document.getElementById('wtList');return !!l&&l.textContent.indexOf(%s)>=0&&l.textContent.indexOf('123.45')>=0;})()" % jsq(MONTH), 20)
        T("清本机缓存重载后从真实云端恢复记录（换设备）", ok_restore, text_of(pg, "#wtList")[:160])
        # ---- 界面删除 ----
        click(pg, '#wtList .wt-row[data-wm="%s"] .wt-del' % MONTH)
        pg.sleep(1.2)
        print("  DEBUG after-delete status=%s wresp=%s" % (
            ev(pg, "(function(){try{return JSON.stringify(window.__B2.water.status());}catch(e){return 'na';}})()"),
            ev(pg, "(function(){try{return JSON.stringify((window.__wresp||[]).slice(-6));}catch(e){return 'na';}})()")))
        ok_del, st_del, row_del = wait_water_row(token, lambda r: r is None)
        T("界面删除 → 真实云端行已删除", ok_del, "status=%s row=%s" % (st_del, row_del))
        T("删除后界面不再显示该记录", MONTH not in text_of(pg, "#wtList"))
        try:
            pg.screenshot(os.path.join(SHOTS, "live_water_430.png"))
        except Exception:  # noqa: BLE001
            pass
        errs = ev(pg, "JSON.stringify(window.__errs||[])")
        T("全程 0 JS 报错", errs in ("[]", ""), errs)
        print("  云端写拦截：seen=%d blocked=%d allowed_water=%d" % (guard["seen"], guard["blocked"], guard["allowed_water"]))
        T("云端写保护生效（除 water 外无写请求放行）", guard["blocked"] > 0 and guard["allowed_water"] > 0,
          guard)
        return RESULTS
    finally:
        try:
            cleanup(token)
        except Exception:  # noqa: BLE001
            pass
        try:
            b.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            srv.shutdown()
        except Exception:  # noqa: BLE001
            pass
        fails = [x for x in RESULTS if not x["ok"]]
        print("\n============================================================")
        print("v2_web_batch2_water_live_check: PASS %d / FAIL %d" % (len(RESULTS) - len(fails), len(fails)))
        for x in fails:
            print("  - FAIL " + x["name"] + " | " + x["note"])
        print("============================================================")


if __name__ == "__main__":
    res = main() or []
    sys.exit(0 if all(x["ok"] for x in res) else 1)
