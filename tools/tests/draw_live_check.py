# -*- coding: utf-8 -*-
"""抽签存证 + 名称映射 · 真实云端 E2E（网页界面，测试身份）

流程：headless Edge 打开本机临时通道（`deploy/local_channel.py`，同源代理 CloudBase）→
官方测试身份 `3260799999 / 测试账号` 在身份页**真实登录** → 名称映射 70 项 → 界面抽签 →
真实 `draw_record_create` 存证 → 今日次数显示 → 导出图（rec=记录 id / 核验 QR）→
剔除重抽（真实 `draw_event_append`）→ 记录弹层今日列表 → 详情核验（复算 ✓ / 哈希 ✓）→
`#verify=` 深链 → 390/430 无溢出 → **finally：真实 `draw_test_clear` 清理测试记录 + 删除测试会话**。

云端写保护（AGENTS §0-7 / HANDOFF §15 口径）：CDP Fetch 只放行 GET/HEAD/OPTIONS 与
`POST /rpc/draw_*`、`/rpc/class_verify`、`/rpc/class_members`；其余云写（visits/userdata/marks 等）
一律 BlockedByClient，避免测试身份污染其它业务数据。

红线：只用测试身份；token 只存在进程内存，不打印、不落盘；测试记录 finally 清零。

运行：cd web/tools && python tests\\draw_live_check.py
产物：tools/tests/_draw_qa/shots/live_*.png、tools/tests/_draw_qa/report_live.json、
      快照 tools/tests/_draw_qa/index_livesnapshot.html（sha256 写入报告）
"""
import hashlib
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
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.dirname(HERE)
DRAWQA = os.path.join(HERE, "_draw_qa")
sys.path.insert(0, os.path.join(HERE, "_qa_v2"))
sys.path.insert(0, DRAWQA)
import _cdp           # noqa: E402
import draw_canon     # noqa: E402

REST = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
KEY = open(os.path.join(WEB, "deploy", "cloudbase", "publish_key.txt"), encoding="utf-8").read().strip()
TEST_SID, TEST_NAME = "3260799999", "测试账号"
SHOTS = os.path.join(DRAWQA, "shots")
os.makedirs(SHOTS, exist_ok=True)
REPORT = os.path.join(DRAWQA, "report_live.json")
SNAPSHOT = os.path.join(DRAWQA, "index_livesnapshot.html")
SNAPSHOT_SHA = [""]
RESULTS = []
TOKENS = []            # 测试身份 token（仅内存；finally 删除对应 class_sessions）
REC_IDS = []           # 本次创建的真实记录 id（finally 校验清理）

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


def make_snapshot():
    src = os.path.join(TOOLS, "index.html")
    with open(src, "rb") as fh:
        data = fh.read()
    tmp = SNAPSHOT + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, SNAPSHOT)
    sha = hashlib.sha256(data).hexdigest()
    SNAPSHOT_SHA[0] = sha
    return sha, len(data)


def load_local_channel():
    path = os.path.join(WEB, "deploy", "local_channel.py")
    spec = importlib.util.spec_from_file_location("local_channel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def start_channel(port, snapshot_bytes):
    import http.server
    import socketserver
    lc = load_local_channel()
    orig_read = lc._read_file

    def patched_read(rel):
        if str(rel).replace("\\", "/").lower() in ("index.html", "index.htm"):
            return snapshot_bytes          # 用冻结快照（隔离并行会话编辑）
        return orig_read(rel)

    lc._read_file = patched_read

    class Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            pass

    srv = Srv(("127.0.0.1", port), lc.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def install_draw_guard(page):
    """CDP Fetch：只放行读请求与 draw_* / 登录 / 名单只读 RPC，其余云端写 fail。"""
    orig = page._dispatch
    state = {"blocked": 0, "seen": 0, "allowed_rpc": 0, "allowed_draw": 0}

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
            allowed_post = (
                method == "POST" and (
                    "/rpc/draw_" in url or "/rpc/class_verify" in url or "/rpc/class_members" in url
                )
            )
            allow = method in ("GET", "HEAD", "OPTIONS") or allowed_post
            try:
                if allow:
                    if method == "POST":
                        state["allowed_rpc"] += 1
                        if "/rpc/draw_" in url:
                            state["allowed_draw"] += 1
                    send_raw("Fetch.continueRequest", {"requestId": p.get("requestId")})
                else:
                    state["blocked"] += 1
                    send_raw("Fetch.failRequest", {"requestId": p.get("requestId"),
                                                   "errorReason": "BlockedByClient"})
            except Exception:  # noqa: BLE001
                pass
            return
        orig(msg)

    page._dispatch = patched
    page.send("Fetch.enable", {"patterns": [{"urlPattern": "*__cb*", "requestStage": "Request"}]})
    return state


def hdr(tok=None):
    h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
         "Origin": "https://tool.furina.fun"}
    if tok:
        h["X-Device-Id"] = tok
    return h


def rpc(name, body, tok=None):
    try:
        r = requests.post(REST + "rpc/" + name, headers=hdr(tok), json=body or {}, timeout=40)
        return r.status_code, r.json()
    except Exception as exc:  # noqa: BLE001
        return 0, {"ok": False, "reason": "request-error:%s" % exc}


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


def count_sel(pg, sel):
    return ev(pg, "document.querySelectorAll(%s).length" % jsq(sel))


def state(pg):
    return json.loads(ev(pg, "JSON.stringify(window.DRAWPROOF?window.DRAWPROOF.state():null)") or "null") or {}


def export_obj(pg):
    return json.loads(ev(pg, "JSON.stringify(window.__lastDrawExport||null)") or "null")


def wait_proof(pg, status, timeout=20):
    return pg.wait_for("(function(){try{var s=DRAWPROOF.state();return !!(s.proof&&s.proof.status===%s);}catch(e){return false;}})()"
                       % jsq(status), timeout)


def wait_export_new(pg, marker, timeout=25):
    return pg.wait_for("JSON.stringify(window.__lastDrawExport||null)!==%s" % jsq(marker), timeout)


def wait_dl(pg, n, timeout=15):
    return pg.wait_for("(window.__DL||[]).length>%d" % n, timeout)


# 页面注入：错误收集 + canvas 渲染文本捕获 + 下载文件名捕获（不真的落盘）
HOOK_JS = r"""
(function(){
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
window.confirm=function(){return true;};
window.__TEXTS=[];
try{var _ft=CanvasRenderingContext2D.prototype.fillText;
CanvasRenderingContext2D.prototype.fillText=function(t){try{window.__TEXTS.push(String(t));}catch(e){}return _ft.apply(this,arguments);};}catch(e){}
window.__DL=[];
try{var _ac=HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click=function(){if(this.download){window.__DL.push(String(this.download));return;}return _ac.apply(this,arguments);};}catch(e){}
})();
"""


def main():
    sha, size = make_snapshot()
    print("[snapshot] index_livesnapshot.html (%d bytes, sha256 %s)" % (size, sha))
    port = free_port()
    with open(SNAPSHOT, "rb") as fh:
        snap_bytes = fh.read()
    srv = start_channel(port, snap_bytes)
    b = _cdp.Browser(window=(430, 900))
    tok = [""]
    try:
        pg = b.new_page("about:blank")
        pg.set_device(430, 900, 2.0, True, True)
        pg.add_init_script(HOOK_JS)
        guard = install_draw_guard(pg)
        pg.navigate("http://127.0.0.1:%d/" % port)
        pg.wait_load(30)
        T("L0 本地临时通道 + 真实身份页加载", pg.wait_for("!!document.getElementById('igGo')", 15))
        T("L1 快照（并行编辑隔离）%d bytes / sha256 %s…" % (size, sha[:12]), size > 1000000)

        # ---- 真实登录（官方测试身份） ----
        set_val(pg, "#igSid", TEST_SID)
        set_val(pg, "#igName", TEST_NAME)
        click(pg, "#igGo")
        ok = pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof DRAWPROOF!=='undefined'", 30)
        T("L2 测试身份真实登录成功（class_verify 真实返回）", ok)
        raw_tok = ""
        try:
            raw_tok = json.loads(ev(pg, "localStorage.getItem('zq_class_identity')||'{}'")).get("token") or ""
        except Exception:  # noqa: BLE001
            raw_tok = ""
        if raw_tok:
            TOKENS.append(raw_tok)
            tok[0] = raw_tok
        T("L3 登录后持有真实班级 token（不打印）", bool(raw_tok and re.match(r"^[0-9a-f]{64}$", raw_tok)))
        st, mem = rpc("draw_record_list", {"p_scope": "today", "p_limit": 100}, tok[0])
        T("L4 测试身份云端可读（draw_record_list ok）", (mem or {}).get("ok") is True, str(mem)[:120])
        T("L5 现有记录基线（today_count=%s / today_mine=%s）" % (mem.get("today_count"), mem.get("today_mine")),
          isinstance(mem.get("today_count"), int) and isinstance(mem.get("today_mine"), int))
        base_count = int((mem or {}).get("today_count") or 0)

        # ---- 名称映射（70 项，真实 UD 本地保存；云同步被守卫拦截不影响） ----
        click(pg, "#aNamesBtn")
        pg.wait_for("(function(){var e=document.getElementById('nmModal');return e&&e.style.display!=='none';})()", 10)
        all70 = "\n".join("%d 第%d组" % (i, i) for i in range(1, 71))
        set_val(pg, "#nmText", all70)
        click(pg, "#nmOk")
        pg.wait_for("(function(){var e=document.getElementById('nmModal');return e&&e.style.display==='none';})()", 8)
        T("L6 名称映射 70 项保存成功（摘要）", "70 项" in text_of(pg, "#aNamesSum"), text_of(pg, "#aNamesSum"))

        # ---- 界面抽签 → 真实存证 ----
        n_create0 = 0
        click(pg, "#aRun")
        ok = wait_proof(pg, "ok", 25)
        st = state(pg)
        proof = st.get("proof") or {}
        rid = (proof.get("record") or {}).get("id") or ""
        if rid:
            REC_IDS.append(rid)
        T("L7 界面抽签 → 真实 draw_record_create 成功（已存证）", ok and bool(rid), str(proof.get("reason") or "")[:120])
        T("L8 记录 id 合法（d+8..31 位 [0-9a-z]）", bool(rid and re.match(r"^d[0-9a-z]{8,31}$", rid)), rid)
        T("L9 状态行显示 已存证 + 今日第 N 次", ("已存证" in text_of(pg, "#aProof")) and
          bool(re.search(r"今日第 \d+ 次", text_of(pg, "#aProof"))), text_of(pg, "#aProof"))

        # ---- 独立复核真实云端数据（自写 probe，不依赖 cloud-worker 结论） ----
        stc, det = rpc("draw_record_get", {"p_id": rid}, tok[0])
        rec = (det or {}).get("record") or {}
        T("L10 draw_record_get 返回记录（ok）", (det or {}).get("ok") is True and rec.get("id") == rid)
        T("L11 记录字段齐全（hash/canon/seed/algo/params/pool/result/labels/prev_hash）",
          all(k in rec for k in ("hash", "canon", "seed", "algo", "params", "pool", "result", "labels", "prev_hash")))
        T("L12 云端 seq_day / today_count 递增（today_count ≥ 基线+1）",
          int(rec.get("seq_day") or 0) >= 1 and int(rec.get("today_count") or 0) >= base_count + 1,
          "seq=%s today=%s base=%s" % (rec.get("seq_day"), rec.get("today_count"), base_count))
        T("L13 响应不含学号 sid / owner_sid", '"sid"' not in json.dumps(det, ensure_ascii=False)
          and "owner_sid" not in json.dumps(det, ensure_ascii=False))
        p = rec.get("params") or {}
        T("L14 params 归一：range/count/dup/excl/sort/rosterN/namesN 键齐全且合法",
          set(p.keys()) == {"range", "count", "dup", "excl", "sort", "rosterN", "namesN"}
          and p.get("range") == [1, 70] and p.get("count") == 10 and p.get("dup") is False
          and p.get("sort") == "draw" and p.get("excl") == [] and p.get("namesN") == 70,
          str(p)[:160])
        T("L15 pool 升序去重（1..70）", rec.get("pool") == list(range(1, 71)))
        T("L16 draw-v1 复算 == result（seed+pool+count+dup，网页端独立 Python 实现）",
          rec.get("result") == draw_canon.draw_v1(rec.get("pool") or [], p.get("count") or 0,
                                                  bool(p.get("dup")), rec.get("seed") or ""),
          str(rec.get("result"))[:100])
        py_rec = {"id": rec.get("id"), "created_ms": rec.get("at"), "day": rec.get("day"),
                  "seq_day": rec.get("seq_day"), "algo": rec.get("algo"), "seed": rec.get("seed"),
                  "prev_hash": rec.get("prev_hash"), "params": rec.get("params"),
                  "pool": rec.get("pool"), "result": rec.get("result"), "labels": rec.get("labels")}
        T("L17 canon 逐字节复算（Python vs 云端 jsonb::text）", draw_canon.canon_record(py_rec) == rec.get("canon"),
          "canon_len=%s" % len(rec.get("canon") or ""))
        T("L18 hash = sha256(canon)", draw_canon.hash_record(py_rec) == rec.get("hash"), str(rec.get("hash"))[:16])
        labels = rec.get("labels") or []
        T("L19 labels 只含命中结果且 n 升序（70 项映射下覆盖 10 个结果）",
          len(labels) == len(rec.get("result") or []) and
          [x["n"] for x in labels] == sorted(x["n"] for x in labels) and
          all(x["n"] in (rec.get("result") or []) for x in labels))

        # ---- 导出图片 ----
        ev(pg, "(function(){window.__TEXTS=[];window.__DL=[];return true;})()")
        marker = ev(pg, "JSON.stringify(window.__lastDrawExport||null)")
        click(pg, "#aImg")
        ok = wait_export_new(pg, marker, 25)
        eo = export_obj(pg) or {}
        T("L20 导出图生成（已存证）", ok and bool(eo))
        T("L21 导出 rec = 真实存证编号", eo.get("rec") == rid, str(eo.get("rec")))
        cfg = {str(k): v for k, v in (eo.get("config") or [])}
        T("L22 导出参数区含 存证编号/存证时间/今日抽签/记录哈希",
          cfg.get("存证编号") == rid and bool(cfg.get("存证时间")) and
          str(cfg.get("今日抽签") or "").startswith("第 ") and cfg.get("记录哈希") == rec.get("hash", "")[:16],
          str(cfg.get("今日抽签")))
        T("L23 导出 QR = canonical 核验深链（127.0.0.1 回退 tool.furina.fun，预期行为）",
          eo.get("qr") == "https://tool.furina.fun/#verify=" + rid, str(eo.get("qr")))
        T("L24 导出 qrTitle/qrCap/qrNote 符合契约",
          eo.get("qrTitle") == "抽签存证核验" and
          eo.get("qrCap") == "扫码核验本次抽签记录（需登录班级身份）" and
          (eo.get("qrNote") or [])[:1] == ["存证编号 " + rid])
        texts = json.loads(ev(pg, "JSON.stringify(window.__TEXTS||[])")) or []
        T("L25 导出图实际渲染「抽签存证核验」（canvas 文本）", "抽签存证核验" in texts)
        dl_ok = pg.wait_for("(window.__DL||[]).length>0", 10)
        dl = json.loads(ev(pg, "JSON.stringify(window.__DL||[])")) or []
        T("L26 导出文件名规范", dl_ok and bool(re.match(
            r"^抽签结果_\d{8}-\d{4}_范围1-70_抽10个_不重复_按抽取顺序\.png$", dl[-1] if dl else "")),
          dl[-1] if dl else "")

        # ---- 剔除重抽 → 真实事件 ----
        # 页面按契约对事件失败静默（仅影响时间线，不阻塞抽签）；云端网关偶发连接重置时事件可能丢失，
        # 因此这里允许重试 1 次剔除动作，并用真实 get 轮询事件链（不掩盖「完全不上报事件」的缺陷）。
        res_orig = state(pg).get("result") or []
        removed_list = []
        ev0 = {}
        rec2 = {}
        for attempt in range(2):
            removed_n = ev(pg, "(function(){var e=document.querySelector('#aOut .rcell');"
                               "return e?Number(e.getAttribute('data-n')):null;})()")
            removed_list.append(removed_n)
            click(pg, "#aOut .rcell .rx")
            found = False
            for _ in range(16):
                pg.sleep(0.4)
                stc, det2 = rpc("draw_record_get", {"p_id": rid}, tok[0])
                rec2 = (det2 or {}).get("record") or {}
                evs = rec2.get("events") or []
                if evs:
                    ev0 = evs[0]
                    found = True
                    break
            if found:
                break
        evs = rec2.get("events") or []
        T("L27 剔除重抽 → 真实 draw_event_append 成功（event_count≥1）",
          int(rec2.get("event_count") or 0) >= 1 and len(evs) >= 1,
          "event_count=%s" % rec2.get("event_count"))
        T("L28 事件字段：kind=remove / n=被剔除号 / added 补抽号",
          ev0.get("kind") == "remove" and ev0.get("n") in removed_list and ev0.get("n") in res_orig
          and (ev0.get("added") is None or ev0.get("added") in (rec.get("pool") or [])), str(ev0)[:160])
        T("L29 事件 hash 链：seq=1 / prev_hash=记录 hash / hash=sha256(ev_canon)",
          ev0.get("seq") == 1 and ev0.get("prev_hash") == rec.get("hash") and
          ev0.get("hash") == draw_canon.hash_event(rid, 1, ev0.get("kind"), ev0.get("n"), ev0.get("added"),
                                                   ev0.get("note") or "", ev0.get("at"),
                                                   ev0.get("prev_hash") or ""))

        # ---- 记录弹层：今日 / 详情核验 ----
        click(pg, "#aRecBtn")
        ok = pg.wait_for("document.querySelectorAll('#recBody .rec-item').length>=1", 20)
        T("L30 记录弹层今日列表加载（真实 draw_record_list）", ok and (rid in text_of(pg, "#recBody")) or
          ev(pg, "!!document.querySelector('#recBody [data-recid=\"%s\"]')" % rid), text_of(pg, "#recBody")[:100])
        T("L31 弹层顶部显示今日次数", bool(re.search(r"今日第 \d+ 次 · 全班共 \d+ 次", text_of(pg, "#recBody"))),
          text_of(pg, "#recBody")[:60])
        click(pg, '#recBody [data-recid="%s"]' % rid)
        ok = pg.wait_for("(function(){var b=document.getElementById('recBody');return b&&b.textContent.indexOf('存证编号')>=0;})()", 20)
        T("L32 打开记录详情（存证核验）", ok)
        pg.wait_for("(function(){var e=document.getElementById('recReplay');return e&&e.textContent.indexOf('✓')>=0;})()", 12)
        T("L33 真实数据：复算 ✓ 一致", "✓" in text_of(pg, "#recReplay"), text_of(pg, "#recReplay"))
        T("L34 真实数据：哈希 ✓ 自检通过", "✓" in text_of(pg, "#recHash"), text_of(pg, "#recHash"))
        detail = text_of(pg, "#recBody")
        T("L35 详情含编号/抽签人/参数/时间线/哈希",
          rid in detail and TEST_NAME in detail and "范围 1–70" in detail and
          "剔除重抽" in detail and rec.get("hash") in detail)
        pg.screenshot(os.path.join(SHOTS, "live_detail_430.png"))
        click(pg, "#recClose2")
        pg.sleep(0.5)

        # ---- #verify= 深链（真实 get） ----
        pg.navigate("about:blank")
        pg.sleep(0.2)
        pg.navigate("http://127.0.0.1:%d/#verify=%s" % (port, rid))
        pg.wait_load(30)
        ok = pg.wait_for("(function(){var e=document.getElementById('recModal');return e&&e.style.display!=='none'&&"
                         "document.getElementById('recBody').textContent.indexOf('存证编号')>=0;})()", 25)
        T("L36 #verify= 深链真实打开核验详情", ok)
        pg.wait_for("(function(){var e=document.getElementById('recReplay');return e&&e.textContent.indexOf('✓')>=0;})()", 12)
        T("L37 深链详情 复算 ✓ / 哈希 ✓",
          "✓" in text_of(pg, "#recReplay") and "✓" in text_of(pg, "#recHash"))
        pg.screenshot(os.path.join(SHOTS, "live_verify_deeplink_430.png"))

        # ---- 390 无溢出 ----
        pg.set_device(390, 844, 2.0, True, True)
        pg.sleep(0.4)
        T("L38 390px：真实核验详情无横向溢出",
          ev(pg, "document.documentElement.scrollWidth<=window.innerWidth+1"))
        pg.screenshot(os.path.join(SHOTS, "live_detail_390.png"))
        pg.set_device(430, 900, 2.0, True, True)

        # ---- 写白名单 ----
        T("L39 CDP 云写白名单生效（拦截 visits/userdata 等非抽签云写，放行 draw_*）",
          guard["blocked"] >= 1 and guard["allowed_draw"] >= 3,
          "blocked=%d allowed_rpc=%d allowed_draw=%d seen=%d" % (
              guard["blocked"], guard["allowed_rpc"], guard["allowed_draw"], guard["seen"]))
        errs = pg.all_errors()
        nerr = len(errs.get("exceptions") or [])
        js_errs = json.loads(ev(pg, "JSON.stringify(window.__errs||[])"))
        T("L40 真实云端页面 0 JS 异常", nerr == 0 and len(js_errs) == 0,
          "exceptions=%s onerror=%s" % (nerr, js_errs[:2]))
        pg.screenshot(os.path.join(SHOTS, "live_draw_430.png"))
    finally:
        try:
            b.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            srv.shutdown()
        except Exception:  # noqa: BLE001
            pass
        # ---- 清理：真实 draw_test_clear + 删除测试会话 + 断言 0 残留 ----
        try:
            t = tok[0]
            if t:
                st, r = rpc("draw_test_clear", {}, t)
                deleted = int((r or {}).get("deleted") or 0)
                T("C1 finally draw_test_clear 清理测试记录", (r or {}).get("ok") is True, "deleted=%s" % deleted)
                st2, g = rpc("draw_record_get", {"p_id": REC_IDS[0]}, t) if REC_IDS else (0, {})
                T("C2 清理后测试记录不可读（记录不存在）",
                  not REC_IDS or (g.get("ok") is False and "不存在" in str(g.get("reason"))), str(g)[:100])
                st3, lst = rpc("draw_record_list", {"p_scope": "all", "p_limit": 100}, t)
                remain = [x.get("id") for x in ((lst or {}).get("records") or []) if x.get("id") in REC_IDS]
                T("C3 清理后列表无本次测试记录残留", not remain, str(remain))
                if re.match(r"^[0-9a-f]{64}$", t):
                    sql("delete from private.class_sessions where token = '%s'" % t)
                st4, after = rpc("draw_record_list", {}, t)
                T("C4 测试会话已删除（旧 token 身份失效）",
                  (after or {}).get("ok") is False, str((after or {}).get("reason"))[:80])
            else:
                T("C1 finally draw_test_clear 清理测试记录", False, "无测试 token（登录失败）")
        except Exception as exc:  # noqa: BLE001
            T("C1 finally draw_test_clear 清理测试记录", False, "清理异常: %s" % exc)
        ok_n = sum(1 for r in RESULTS if r["ok"])
        fails = len(RESULTS) - ok_n
        print("\n=========== draw_live_check: %d PASS / %d FAIL（共 %d 断言）==========="
              % (ok_n, fails, len(RESULTS)))
        try:
            with open(REPORT, "w", encoding="utf-8") as fh:
                json.dump({"pass": ok_n, "fail": fails, "total": len(RESULTS),
                           "snapshot": {"path": "/tools/tests/_draw_qa/index_livesnapshot.html",
                                        "sha256": SNAPSHOT_SHA[0]},
                           "records": REC_IDS, "results": RESULTS,
                           "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                          fh, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
