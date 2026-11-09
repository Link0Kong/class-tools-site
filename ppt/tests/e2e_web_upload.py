# -*- coding: utf-8 -*-
"""Lead E2E: real browser upload via web UI -> chunks -> queued -> converter -> ready.
# 维护说明: Lead 独立验收工具：真实浏览器 UI 上传 55KB PPT → 分片 → queued → 计划任务转换 ready → 播放（只允许 ppt 两表写，其它云端写阻断；结束自动软删测试 deck）。

Uses test identity token; cloud writes allowed ONLY for ppt_decks / ppt_upload_chunks
(everything else blocked by a custom CDP guard). Cleans up its deck afterwards.
"""
import json, os, sys, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
QA = r"C:\Users\Ko_Li\.openclaw\workspace\web\tools\tests\_qa_v2"
sys.path.insert(0, QA)
import _cdp, _webqa  # noqa: E402

PUB = open(r"C:\Users\Ko_Li\.openclaw\workspace\web\deploy\cloudbase\publish_key.txt", encoding="utf-8").read().strip()
BASE = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
SRC = r"C:\Users\Ko_Li\.openclaw\workspace\web\ziqi\files\slides.pptx"


def cloud(m, p, b=None, h=None):
    hh = {"Authorization": "Bearer " + PUB, "Content-Type": "application/json"}
    if h:
        hh.update(h)
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, headers=hh, method=m)
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            return x.status, x.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def allow_ppt_writes(page):
    st = {"seen": 0, "blocked": 0, "allowed": 0}
    orig = page._dispatch

    def send_raw(method, params):
        page._id += 1
        page.ws.send(json.dumps({"id": page._id, "method": method, "params": params}))

    def patched(msg):
        if msg.get("method") == "Fetch.requestPaused":
            pr = msg.get("params", {}) or {}
            rid = pr.get("requestId")
            req = pr.get("request", {}) or {}
            method = (req.get("method") or "GET").upper()
            url = req.get("url") or ""
            st["seen"] += 1
            ppt_write = ("/ppt_decks" in url or "/ppt_upload_chunks" in url)
            try:
                if method in ("GET", "HEAD", "OPTIONS") or (method == "POST" and "/rpc/" in url) or (ppt_write and method in ("POST", "PATCH", "DELETE")):
                    st["allowed"] += 1
                    send_raw("Fetch.continueRequest", {"requestId": rid})
                else:
                    st["blocked"] += 1
                    send_raw("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"})
            except Exception:
                pass
            return
        orig(msg)

    page._dispatch = patched
    page.send("Fetch.enable", {"patterns": [{"urlPattern": "*tcloudbasegateway.com*", "requestStage": "Request"}]})
    return st


def main():
    st, b = cloud("POST", "rpc/class_verify", {"p_sid": "3260799999", "p_name": "测试账号"})
    tok = json.loads(b)["token"]
    ident = {"token": tok, "sid": "3260799999", "name": "测试账号", "role": "", "badge": "", "is_admin": False,
             "ts": int(time.time() * 1000)}
    init = "try{localStorage.setItem('zq_class_identity',%s);}catch(e){}" % json.dumps(json.dumps(ident, ensure_ascii=False))
    srv = _webqa._Server(); srv.start()
    br = _cdp.Browser(window=(1280, 800), extra_flags=["--disable-web-security"])
    pg = br.new_page("about:blank")
    pg.add_init_script(init)
    pg.set_device(1280, 800, dpr=1.0, mobile=False, touch=False)
    guard = allow_ppt_writes(pg)
    pg.navigate("http://127.0.0.1:%d/index.html" % srv.port)
    pg.wait_load(30)
    pg.wait_for("(function(){try{return !document.body.classList.contains('id-locked')&&!!document.querySelector('#tabsBar button');}catch(e){return false;}})()", 25)
    pg.sleep(1.0)
    # 进入演示页（真实 UI 路径）
    pg.evaluate("(function(){var b=document.querySelector('#tabsBar button[data-tab=all]');if(b)b.click();})()")
    pg.wait_for("document.querySelector('#allCards [data-open=ppt]')", 10)
    pg.evaluate("(function(){var c=document.querySelector('#allCards [data-open=ppt]');if(c)c.click();})()")
    pg.wait_for("document.querySelector('#pptFile')", 10)
    # 选择文件（CDP 设置 file input）
    root = pg.send("DOM.getDocument", {"depth": 1})["root"]["nodeId"]
    nid = pg.send("DOM.querySelector", {"nodeId": root, "selector": "#pptFile"})["nodeId"]
    pg.send("DOM.setFileInputFiles", {"files": [SRC], "nodeId": nid})
    ok_box = pg.wait_for("(function(){var b=document.getElementById('pptUpBox');return !!(b&&!b.hidden);})()", 15)
    print("[upload] file picked box:", ok_box, pg.evaluate("(function(){var f=document.getElementById('pptUpFile');return f?f.textContent:'';})()"))
    pg.evaluate("(function(){var n=document.getElementById('pptUpName');if(n)n.value='浏览器上传E2E';})()")
    pg.screenshot(os.path.join(HERE, "shots_ppt", "upload_01_pick.png"))
    pg.evaluate("document.getElementById('pptUpGo').click()")
    # 等上传完成（进度 → 排队/列表卡）
    done = False
    for i in range(40):
        time.sleep(1.0)
        s = pg.evaluate("(function(){var p=document.getElementById('pptUpProg');var l=document.getElementById('pptUpLabel');"
                        "return {prog:p?p.hidden:null,label:l?l.textContent:'',stat:(document.getElementById('pptStat')||{}).textContent||''};})()")
        if i % 3 == 0:
            print("[upload]", i, s)
        cards = pg.evaluate("document.querySelectorAll('#pptList .ppt-card').length")
        if cards and s.get("prog"):
            done = True
            break
    print("[upload] done:", done)
    pg.screenshot(os.path.join(HERE, "shots_ppt", "upload_02_done.png"))
    # 从云端确认这行的 id
    time.sleep(1.0)
    stt, b = cloud("GET", "ppt_decks?select=id,title,status,owner_name&deleted=eq.false&order=created_at.desc&limit=5",
                   h={"X-Device-Id": tok})
    rows = json.loads(b)
    print("[cloud] rows:", [(r["id"], r["title"], r["status"]) for r in rows])
    mine = [r for r in rows if r["title"] == "浏览器上传E2E"]
    if not mine:
        print("[cloud] deck row not found; abort")
        return 1
    deck = mine[0]
    print("[cloud] deck:", deck["id"], deck["status"])
    # 轮询转换状态（计划任务每分钟）
    t0 = time.time()
    final = None
    while time.time() - t0 < 180:
        stt, b = cloud("GET", "ppt_decks?select=id,status,progress,error,slide_count,step_count&id=eq." + deck["id"],
                       h={"X-Device-Id": tok})
        row = json.loads(b)[0]
        if row["status"] in ("ready", "failed"):
            final = row
            break
        time.sleep(4)
    print("[convert] final:", final)
    ok = bool(final and final["status"] == "ready")
    if ok:
        # 列表刷新 → 播放器打开该 deck
        pg.evaluate("window.PPT.pull()")
        pg.sleep(1.5)
        pg.evaluate("window.PPT.open(%s)" % json.dumps(deck["id"]))
        loaded = pg.wait_for("(function(){var a=document.querySelectorAll('#pptPlayer .ppt-layer img');"
                             "for(var k=0;k<a.length;k++){if(a[k].naturalWidth>0)return true;}return false;})()", 30)
        pg.sleep(0.8)
        pg.screenshot(os.path.join(HERE, "shots_ppt", "upload_03_play.png"))
        print("[play] real uploaded deck plays:", loaded)
        pg.evaluate("(function(){var b=document.querySelector('#pptPlayer [data-act=close]');if(b)b.click();})()")
        pg.sleep(1.2)
        pg.evaluate("(function(){var b=document.querySelector('#pptConfirm [data-act=leave]');if(b)b.click();})()")
        pg.sleep(0.6)
    errs = pg.all_errors()
    if isinstance(errs, dict):
        flat = [str(x) for v in errs.values() for x in (v if isinstance(v, list) else [v])]
    else:
        flat = [str(x) for x in errs]
    print("[errors]", len(flat), [e[:150] for e in flat[:3]])
    print("[guard] seen=%d allowed=%d blocked=%d" % (guard["seen"], guard["allowed"], guard["blocked"]))
    # 清理：软删 + 删分片
    stt, _ = cloud("DELETE", "ppt_upload_chunks?deck_id=eq." + deck["id"], h={"X-Device-Id": tok, "Prefer": "return=minimal"})
    stt, _ = cloud("PATCH", "ppt_decks?id=eq." + deck["id"], [{"deleted": True, "updated_at": int(time.time() * 1000)}],
                   h={"X-Device-Id": tok, "Prefer": "return=minimal"})
    print("[cleanup] deck soft-deleted:", stt)
    print("RESULT:", "PASS" if (done and ok) else "FAIL")
    pg.close(); br.close(); srv.stop()
    return 0 if (done and ok) else 1


if __name__ == "__main__":
    sys.exit(main())
