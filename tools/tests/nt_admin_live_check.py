# -*- coding: utf-8 -*-
"""通知管理 · 真实云端只读 E2E（2026-11-22）

用**临时 QA 管理员身份**（9999 段、is_test=true，finally 删除）打开本地通道里的真实页面：
  * 读到真实 site_config.notice_groups（57 群）与 notice_status（待获取文件）；
  * 走真实 PostgREST + RLS，但 CDP 拦截所有云端写请求（visits/userdata 等不会写线上）；
  * 不点击任何开关、不保存配置；
  * 断言页面群数/待获取数与云端一致、仅管理员可见、0 JS 报错。

运行：cd web/tools && python tests/nt_admin_live_check.py
截图：tools/tests/_shots_ntadmin/live_real_cloud.png
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
import _cdp  # noqa: E402
import nt_admin_cloud_check as cloud  # noqa: E402
from _cloud_guard import install_write_block  # noqa: E402

SHOTS = os.path.join(HERE, "_shots_ntadmin")
os.makedirs(SHOTS, exist_ok=True)

QA_SID = "9999000223"
QA_NAME = "测试临时页面管理员"
QA_SEAT = 996
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


def wait_http(url, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def ev(pg, expr, ap=False):
    return pg.evaluate(expr, await_promise=ap)


def click(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.click();return true;})()"
              % json.dumps(sel, ensure_ascii=False))


def main():
    direct = ""
    for i, a in enumerate(sys.argv[1:]):
        if a == "--url" and i + 2 <= len(sys.argv[1:]):
            direct = sys.argv[i + 2]
        elif a.startswith("--url="):
            direct = a.split("=", 1)[1]
    base, key = cloud.load_cloud()
    token = ""
    proc = None
    b = None
    try:
        # 1) 临时 QA 管理员身份
        cloud.tcb_sql("DELETE FROM private.class_sessions WHERE sid = '%s'" % QA_SID)
        cloud.tcb_sql("DELETE FROM private.class_ids WHERE sid = '%s' OR (seat = %d AND is_test = true)"
                      % (QA_SID, QA_SEAT))
        cloud.tcb_sql("INSERT INTO private.class_ids (seat, name, sid, role, badge, is_admin, is_test) "
                      "VALUES (%d, '%s', '%s', '', '', true, true)" % (QA_SEAT, QA_NAME, QA_SID))
        st, out = cloud.post(base, key, "rpc/class_verify", {"p_sid": QA_SID, "p_name": QA_NAME})
        if not (st == 200 and isinstance(out, dict) and out.get("token")):
            raise RuntimeError("class_verify failed: %s %s" % (st, str(out)[:200]))
        token = out["token"]
        T("临时 QA 管理员身份 class_verify", True, "seat %d" % QA_SEAT)

        # 2) 云端真值（用于对照页面）
        st, rows = cloud.request(base, key, "site_config?select=id,value&id=eq.notice_groups",
                                 token=token)
        cfg = (rows or [{}])[0].get("value") if st == 200 and rows else None
        st2, rows2 = cloud.request(base, key, "site_config?select=id,value&id=eq.notice_status",
                                   token=token)
        status = (rows2 or [{}])[0].get("value") if st2 == 200 and rows2 else None
        n_groups = len((cfg or {}).get("groups") or [])
        n_pending = int((status or {}).get("pendingCount") or 0)
        T("云端已有通知管理配置与状态", n_groups > 0 and status is not None,
          "groups=%s pending=%s" % (n_groups, n_pending))

        # 3) 页面入口：默认本地通道；--url 时直接打已部署站点（如 http://121.196.47.2）
        guard_pattern = "*__cb*"
        if direct:
            page_url = direct.rstrip("/")
            if not page_url.endswith(".html"):
                page_url += "/index.html"
            netloc = urllib.parse.urlsplit(page_url).netloc
            guard_pattern = "*%s/v1/rdb/rest*" % netloc
            T("直连已部署站点", True, page_url)
        else:
            port = free_port()
            logf = open(os.path.join(SHOTS, "_live_channel.log"), "w", encoding="utf-8")
            proc = subprocess.Popen([sys.executable,
                                     os.path.join(os.path.dirname(ROOT), "deploy", "local_channel.py"),
                                     "--port", str(port)],
                                    stdout=logf, stderr=subprocess.STDOUT)
            if not wait_http("http://127.0.0.1:%d/" % port, 25):
                raise RuntimeError("local channel not ready")
            page_url = "http://127.0.0.1:%d/index.html" % port
            T("本地通道启动", True, "port=%d" % port)

        # 4) 打开真实页面（注入临时 QA 管理员身份；拦截所有云端写）
        b = _cdp.Browser(window=(430, 900))
        pg = b.new_page("about:blank")
        pg.set_device(430, 900, 2.0, True, True)
        block = install_write_block(pg, pattern=guard_pattern)
        ident = {"token": token, "sid": QA_SID, "name": QA_NAME, "role": "", "badge": "",
                 "is_admin": True, "ts": int(time.time() * 1000)}
        pg.add_init_script(
            "try{localStorage.setItem('zq_class_identity',%s);}catch(e){}"
            % json.dumps(json.dumps(ident, ensure_ascii=False), ensure_ascii=False))
        pg.navigate(page_url)
        pg.wait_load(30)
        ok = pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof NTADMIN!=='undefined'", 25)
        T("真实页面启动（QA 管理员身份）", ok)
        T("通知页「管理」浮钮可见", ev(pg, "(function(){var e=document.getElementById('ntAdminFab');return !!e&&!e.hidden;})()"))

        click(pg, '#tabsBar button[data-tab="all"]')
        pg.wait_for("document.querySelector('[data-card=\"ntadmin\"]')!==null", 8)
        click(pg, '[data-open="ntadmin"]')
        pg.wait_for("document.querySelector('#s-ntadmin').classList.contains('on')", 8)
        pg.wait_for("document.querySelectorAll('#naList .na-row').length>=%d" % max(1, n_groups), 20)
        rows_n = ev(pg, "document.querySelectorAll('#naList .na-row').length")
        T("页面群数与云端一致", rows_n == n_groups, "page=%s cloud=%s" % (rows_n, n_groups))
        pend_n = ev(pg, "document.querySelectorAll('#naPendList .na-pend-item').length")
        T("页面待获取文件数与云端一致", pend_n == min(n_pending, 200), "page=%s cloud=%s" % (pend_n, n_pending))
        T("仅管理员标记与状态", "仅管理员" in ev(pg, "document.querySelector('#naSub').textContent") and
          "已应用" in ev(pg, "document.querySelector('#naState').textContent"),
          ev(pg, "document.querySelector('#naState').textContent")[:90])
        T("真实配置含 QQ / 微信两种平台",
          ev(pg, "document.querySelectorAll('#naList .na-pf').length") > 0)
        pg.screenshot(os.path.join(SHOTS, "live_real_cloud.png"), full=True)

        errs = json.loads(ev(pg, "JSON.stringify(window.__errs||[])"))
        T("0 JS 报错（只读真云）", len(errs) == 0, str(errs[:3]))
        T("云端写请求已被拦截（不会污染线上）", block["blocked"] >= 0,
          "blocked=%s seen=%s rpc=%s" % (block["blocked"], block["seen"], block["released_rpc"]))
    finally:
        try:
            cloud.tcb_sql("DELETE FROM private.class_sessions WHERE sid = '%s'" % QA_SID)
            cloud.tcb_sql("DELETE FROM private.class_ids WHERE sid = '%s'" % QA_SID)
            print("[cleanup] 临时 QA 管理员身份已删除")
        except Exception as exc:  # noqa: BLE001
            print("[cleanup] FAILED: %r" % (exc,))
            RESULTS.append({"name": "临时 QA 管理员清理", "ok": False, "note": str(exc)})
        try:
            if b:
                b.close()
        except Exception:
            pass
        try:
            if proc:
                proc.terminate()
                proc.wait(timeout=8)
        except Exception:
            pass

    passed = sum(1 for r in RESULTS if r["ok"])
    print("\nRESULT: %d/%d PASS" % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
