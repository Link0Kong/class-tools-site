# -*- coding: utf-8 -*-
"""DNS 暂停改造 · 网页诊断 18 行 / 暂停语义 / 云端巡检过期降级 / tt 云端回退 验收。

用法（cwd 任意）：
    python web/tools/tests/dns_pause_web_check.py
运行：本地静态服务器 + headless Edge（CDP），管理员身份注入（token 只读 secrets，不打印）。
云端请求用 fetch 拦截 mock：service_health 返回 18 行；写请求阻断；tt.json 在回退用例中 404。
"""
import functools
import http.server
import json
import os
import socketserver
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QA2 = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA2)
from _cdp import Browser  # noqa: E402

TOKEN_FILE = r"C:\briefdesk\secrets\class-token.json"
ADMIN = {"sid": "3260707024", "name": "陈子麒"}
RESULTS = []


def T(name, ok, note=""):
    RESULTS.append((name, bool(ok), str(note)[:200]))
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)[:200]) if note else ""))


def token():
    return json.load(open(TOKEN_FILE, encoding="utf-8"))["token"]


def identity():
    return {"token": token(), "sid": ADMIN["sid"], "name": ADMIN["name"],
            "role": "", "badge": "", "is_admin": True, "ts": int(time.time() * 1000)}


def rows_mock(stale_probe=False, paused=True):
    now = int(time.time() * 1000)
    probe_at = now - (40 * 60 * 1000 if stale_probe else 5000)

    def r(rid, name, kind, status, detail, meta=None, chk=None):
        return {"id": rid, "name": name, "kind": kind, "status": status,
                "detail": detail, "meta": meta or {}, "checked_at": chk if chk is not None else now}

    site_detail = "网页已按备案安排暂停（备案暂停）" if paused else "HTTP 200 · 120ms"
    site_status = "warn" if paused else "ok"
    return [
        r("ai", "AI 识别", "local", "ok", "最近成功 07:10"),
        r("briefdesk", "本地通知服务", "local", "ok", "服务正常（HTTP 200）"),
        r("cloud_health_probe", "云端巡检", "cloud", "ok", "本轮完成 · 8 行 · 860ms", {"rows": 8}, probe_at),
        r("cloud_power_sync", "电费云同步", "cloud", "ok", "最近同步 20 分钟前"),
        r("cloud_xgj_sync", "学工记云同步", "cloud", "ok", "最近同步 1 小时前"),
        r("cloudbase", "云端数据库", "cloud", "ok", "HTTP 200 · 52ms"),
        r("collector_host", "采集主机", "local", "ok", "在线 1天2小时 · 上轮 2s"),
        r("dns_domain", "域名解析", "cloud", "ok", "已暂停（符合预期）" if paused else "解析正常",
          {"paused": paused, "addrs": []}),
        r("hwauto", "作业自动整理", "local", "ok", "作业整理 1.2 小时前运行"),
        r("jwxt", "教务课表同步", "local", "ok", "课表 12.0 小时前同步"),
        r("qq_client", "QQ 客户端", "local", "ok", "进程运行中（9 个实例）"),
        r("qqflow", "QQ 消息采集", "local", "ok", "健康 · 账号就绪"),
        r("site_static", "站点资源", "static", site_status, site_detail, {"paused": paused}),
        r("site_tls", "站点证书", "static", site_status, site_detail, {"paused": paused}),
        r("tt_cloud", "课表云端数据", "cloud", "ok", "云端快照 1 小时前同步"),
        r("watcher", "文档/通知监听", "local", "ok", "日志 30 秒前更新"),
        r("wechat_client", "微信客户端", "local", "ok", "进程运行中（5 个实例）"),
        r("weflow", "微信消息采集", "local", "ok", "健康 · 账号就绪"),
    ]


TT_BODY = {"c": [{"name": "测试课程", "teacher": "测试老师", "room": "101", "day": 0,
                  "start": 1, "end": 2, "weeks": "1-16", "parity": "all"}],
           "t": "2026-08-31", "meta": {"source": "jwxt", "fetchedAt": int(time.time() * 1000), "count": 1}}


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Srv(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_server():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    httpd = Srv(("127.0.0.1", port), functools.partial(Handler, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def init_script(rows, block_static_tt):
    return """(function(){
  var ROWS=%(rows)s, TT=%(tt)s, BLOCK=%(block)s;
  window.__fetchlog=[];
  try{localStorage.setItem('zq_class_identity',JSON.stringify(%(ident)s));}catch(e){}
  var _f=window.fetch;
  window.fetch=function(u,o){
    var url=String((u&&u.url)||u||'');
    var method=String((o&&o.method)||(u&&u.method)||'GET').toUpperCase();
    try{window.__fetchlog.push(method+' '+url);}catch(e){}
    if(url.indexOf('service_health?select=')>=0){
      return Promise.resolve(new Response(JSON.stringify(ROWS),{status:200,headers:{'Content-Type':'application/json'}}));
    }
    // 阻断云端写请求，避免污染班级数据
    if(url.indexOf('tcloudbasegateway')>=0 && method!=='GET' && method!=='HEAD'){
      return Promise.resolve(new Response('{"blocked":true}',{status:403,headers:{'Content-Type':'application/json'}}));
    }
    if(BLOCK && url.indexOf('tt.json?ts=')>=0){
      return Promise.resolve(new Response('not found',{status:404}));
    }
    if(url.indexOf('site_assets?id=eq.tt')>=0){
      return Promise.resolve(new Response(JSON.stringify([{body:JSON.stringify(TT),meta:{},updated_at:new Date().toISOString()}]),{status:200,headers:{'Content-Type':'application/json'}}));
    }
    return _f.apply(this,arguments);
  };
})();""" % {"rows": json.dumps(rows, ensure_ascii=False), "tt": json.dumps(TT_BODY, ensure_ascii=False),
             "block": "true" if block_static_tt else "false",
             "ident": json.dumps(identity(), ensure_ascii=False)}


def new_page(browser, port, rows, block_static_tt):
    page = browser.new_page("about:blank")
    page.add_init_script(init_script(rows, block_static_tt))
    page.set_device(1280, 900, 1.0, mobile=False, touch=False)
    page.navigate("http://127.0.0.1:%d/index.html" % port)
    page.wait_load(40)
    page.wait_for("!!(document.querySelector('#tabsBar button')) && !document.body.classList.contains('id-locked')", 40)
    time.sleep(0.8)
    return page


def open_diag(page):
    page.evaluate("(function(){try{window.__diag.gotoTab('diag');window.__diag.pull();}catch(e){return String(e)}})()")
    page.wait_for("document.querySelectorAll('#diagGrid .diag-row').length===18", 20)
    time.sleep(0.4)


def dump_diag(page):
    return page.evaluate("""(function(){
      var gs=[].map.call(document.querySelectorAll('#diagGrid .diag-group'),function(g){
        return {t:(g.querySelector('.diag-ghd')||{}).textContent||'',
          rows:[].map.call(g.querySelectorAll('.diag-row'),function(r){
            return {name:(r.querySelector('.diag-name')||{}).textContent||'',
                    pill:(r.querySelector('.diag-pill')||{}).textContent||'',
                    detail:(r.querySelector('.diag-detail')||{}).textContent||''};})};
      });
      return {groups:gs, summary:(document.querySelector('.diag-sumtext')||{}).textContent||'',
              rows:document.querySelectorAll('#diagGrid .diag-row').length};
    })()""")


def row_of(view, name):
    for g in view["groups"]:
        for r in g["rows"]:
            if r["name"] == name:
                return r
    return None


def run_case(browser, port, rows, block_static_tt, tag, stale=False):
    page = new_page(browser, port, rows, block_static_tt)
    open_diag(page)
    v = dump_diag(page)
    T(tag + " 分组 5 组", len(v["groups"]) == 5, [g["t"] for g in v["groups"]])
    T(tag + " 共 18 行", v["rows"] == 18, v["rows"])
    site = row_of(v, "站点资源")
    T(tag + " 暂停时站点资源显示「注意·暂停」", site and site["pill"] == "注意" and "暂停" in site["detail"],
      site and (site["pill"] + "|" + site["detail"]))
    tls = row_of(v, "站点证书")
    T(tag + " 暂停时站点证书显示「注意·暂停」", tls and tls["pill"] == "注意" and "暂停" in tls["detail"],
      tls and (tls["pill"] + "|" + tls["detail"]))
    dns = row_of(v, "域名解析")
    if not stale:
        T(tag + " 域名解析显示「正常·已暂停」", dns and dns["pill"] == "正常" and "暂停" in dns["detail"],
          dns and (dns["pill"] + "|" + dns["detail"]))
    else:
        T(tag + " 巡检过期时域名解析显示「注意·巡检未更新」", dns and dns["pill"] == "注意" and "巡检未更新" in dns["detail"],
          dns and (dns["pill"] + "|" + dns["detail"]))
    tt = row_of(v, "课表云端数据")
    if stale:
        T(tag + " 云端巡检过期 → 课表云端数据「注意·巡检未更新」",
          tt and tt["pill"] == "注意" and "巡检未更新" in tt["detail"], tt and (tt["pill"] + "|" + tt["detail"]))
        cp = row_of(v, "电费云同步")
        T(tag + " 云端巡检过期 → 电费云同步同样降级", cp and cp["pill"] == "注意" and "巡检未更新" in cp["detail"],
          cp and (cp["pill"] + "|" + cp["detail"]))
        T(tag + " 摘要「7 项注意」（2 站点暂停 + 5 云端行过期）", "7 项注意" in v["summary"], v["summary"])
    else:
        T(tag + " 正常时云端行显示正常", tt and tt["pill"] == "正常", tt and (tt["pill"] + "|" + tt["detail"]))
        T(tag + " 摘要「2 项注意」（仅网页暂停两项）", "2 项注意" in v["summary"], v["summary"])
    page.screenshot(os.path.join(HERE, "_shots_diag", "diag_%s.png" % tag), full=False)
    # tt 云端回退（仅在 block_static_tt 用例做）
    if block_static_tt:
        page.evaluate("(function(){var b=document.querySelector('#ttFromPub');if(b)b.click();return !!b;})()")
        time.sleep(1.2)
        pub = page.evaluate("(function(){try{return localStorage.getItem('zq_tt_pub')||''}catch(e){return ''}})()")
        try:
            obj = json.loads(pub)
        except Exception:
            obj = None
        T(tag + " tt.json 失败时回退 CloudBase site_assets 成功", bool(obj and isinstance(obj.get("c"), list) and obj["c"]),
          (obj.get("c") and len(obj["c"])) if isinstance(obj, dict) else pub[:80])
        logs = page.evaluate("(function(){return (window.__fetchlog||[]).filter(function(x){return x.indexOf('site_assets')>=0});})()")
        T(tag + " 回退请求命中 site_assets", len(logs) >= 1, logs[:2])
    errs = page.all_errors()
    T(tag + " 无 JS/console 报错", not (errs.get("console") or errs.get("exceptions") or errs.get("log")), errs)
    page.close()
    return v


def main():
    os.makedirs(os.path.join(HERE, "_shots_diag"), exist_ok=True)
    httpd, port = start_server()
    b = Browser()
    try:
        run_case(b, port, rows_mock(stale_probe=False, paused=True), False, "暂停+正常")
        run_case(b, port, rows_mock(stale_probe=True, paused=True), True, "暂停+巡检过期+回退", stale=True)
    finally:
        b.close()
        httpd.shutdown()
    npass = sum(1 for _, ok, _ in RESULTS if ok)
    print("=" * 60)
    print("dns_pause_web_check: %d 项，PASS %d，FAIL %d" % (len(RESULTS), npass, len(RESULTS) - npass))
    for name, ok, note in RESULTS:
        if not ok:
            print("  FAIL:", name, "|", note)
    sys.exit(0 if npass == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
