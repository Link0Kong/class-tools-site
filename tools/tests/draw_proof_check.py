# -*- coding: utf-8 -*-
"""抽签存证 + 自定义序号名称映射 · 网页 mock UI 专项验收
契约唯一真源：`web/draw/CONTRACT.md` §3 / §5.2（断言 ≥60）

方式：本地 HTTP + headless Edge + CDP（`tools/tests/_qa_v2/_cdp.py`）+ 注入官方测试身份
（3260799999/测试账号，见 `_test_account.py`）+ **Python mock 服务端**：
  * 页面里所有 `*.tcloudbasegateway.com/v1/rdb/rest/*` fetch 由 init script 改写为同源
    `/__mock/cb/*`，请求落到本脚本的 ThreadedHTTPServer；
  * mock 的 `draw_record_create / draw_record_get / draw_record_list / draw_event_append`
    按契约 §1.2 用 `_draw_qa/draw_canon.py` **生成 canon + sha256**（已在真实 CloudBase
    PostgreSQL 上逐字节验证：`_draw_qa/canon_pg_crosscheck.py`），并做 §1.4 服务端白名单归一；
  * 不访问真实云端、不写任何线上数据；本地 mock 状态独立于真实数据库。

覆盖：名称映射解析/保存/优先级/持久化/导出；抽签创建请求体（params/pool/result/seed/labels/algo）
+ 今日次数显示 + 哈希链；导出 rec=记录 id / config 行 / QR 内容 / qrTitle/qrCap / 渲染文本；
记录弹层今日/全部/详情/返回；`#verify=` 深链；哈希自检 ✓、复算 ✓、篡改后 ✗；失败降级
「未存证」；pending 超时降级；360/390/430 无横向溢出；0 JS 报错；0 外部请求。

运行：cd web/tools && python tests\\draw_proof_check.py
产物：tools/tests/_draw_qa/shots/*.png、tools/tests/_draw_qa/report_mock.json
"""
import copy
import hashlib
import http.server
import json
import os
import re
import socket
import socketserver
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # web/tools
QA = os.path.join(HERE, "_qa_v2")
DRAWQA = os.path.join(HERE, "_draw_qa")
sys.path.insert(0, QA)
sys.path.insert(0, DRAWQA)
import _cdp          # noqa: E402
import draw_canon    # noqa: E402

SHOTS = os.path.join(DRAWQA, "shots")
os.makedirs(SHOTS, exist_ok=True)
REPORT = os.path.join(DRAWQA, "report_mock.json")
# 并行会话可能同时编辑 tools/index.html：测试固定跑「当前 index.html 的快照」，报告记录 sha256
SNAPSHOT = os.path.join(DRAWQA, "index_drawsnapshot.html")
PAGE_PATH = "/tests/_draw_qa/index_drawsnapshot.html"
SNAPSHOT_SHA = [""]


TEST_SID = "3260799999"
TEST_NAME = "测试账号"
MOCK_TOKEN = "qa-draw-token"
RESULTS = []

# 参与名单 / 班级名单 mock（合成 9999 段测试身份，不是任何真实同学）
MEMBERS = [{"seat": i, "sid": "9999000%03d" % i, "name": "测试同学%02d" % i,
            "role": "", "badge": "", "is_admin": False} for i in range(1, 6)]
# 本机「名单」文本（nameOf 的班级名单派生名兜底）：9 号只在 roster 里，用于验证优先级
ROSTER_SEED = "1 张三座\n9 张九座"


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


# ============================================================
# Python mock 服务端（契约 §1.1–§1.4；canon/hash 由 draw_canon 生成）
# ============================================================
class MockCloud(object):
    """draw_* RPC 的内存实现：校验/归一/幂等/seq_day/哈希链/事件链/测试清理。"""

    def __init__(self):
        self.lock = threading.RLock()
        self.records = {}        # id -> record(dict)
        self.events = {}         # id -> [event(dict)]
        self.requests = []       # [{kind,name,body,method,url}]
        self.caller_sid = TEST_SID
        # 注入开关（测试用）
        self.fail_create = False
        self.delay_create = 0    # 秒；一次生效
        self.hang_create = 0     # 秒；挂起 create 响应（模拟远端迟迟不返回，成功后仍返回 ok）
        self.tamper_hash = 0     # 次数；一次生效
        self.tamper_result = 0   # 次数；一次生效
        self.seeded = False

    # ---------------- 基础 ----------------
    @staticmethod
    def now_ms():
        return int(time.time() * 1000)

    def today(self):
        return draw_canon.local_day(self.now_ms())

    @staticmethod
    def is_test(sid):
        sid = str(sid or "")
        return sid == TEST_SID or (sid.startswith("9999") and len(sid) == 10)

    def _count(self, day, is_test):
        return len([r for r in self.records.values() if r["day"] == day and r["is_test"] == is_test])

    def _mine(self, day, is_test, sid):
        return len([r for r in self.records.values()
                    if r["day"] == day and r["is_test"] == is_test and r["sid"] == sid])

    def _prev(self, is_test):
        recs = [r for r in self.records.values() if r["is_test"] == is_test]
        if not recs:
            return ""
        recs.sort(key=lambda r: (r["created_ms"], r["id"]))
        return recs[-1]["hash"]

    def _new_record(self, rid, sid, created_ms, seq_day, params, pool, result, labels, seed, prev_hash,
                    algo="draw-v1", tamper_result=False, tamper_hash=False):
        rec = {
            "id": rid, "sid": sid, "is_test": self.is_test(sid), "created_ms": int(created_ms),
            "day": draw_canon.local_day(created_ms), "seq_day": int(seq_day),
            "params": params, "pool": pool, "result": result, "labels": labels,
            "seed": seed, "algo": algo, "prev_hash": prev_hash,
        }
        if tamper_result:
            # 破坏「复算」但不破坏「哈希自检」：改结果并按改后字段重算 canon/hash
            r = list(rec["result"])
            if len(r) >= 2:
                r[0], r[1] = r[1], r[0]
            rec["result"] = r
        rec["canon"] = draw_canon.canon_record(rec)
        rec["hash"] = draw_canon.hash_record(rec)
        if tamper_hash:
            # 破坏「哈希自检」但保留 canon（复算仍可一致）
            h = rec["hash"]
            rec["hash"] = ("0" if h[:1] != "0" else "1") + h[1:]
        return rec

    def seed(self):
        """预置：昨天 1 条 + 今天 6 条（同一 is_test 口径哈希链），否则新抽签是第 7 次。"""
        with self.lock:
            now = self.now_ms()
            base_params = {"range": [1, 70], "count": 10, "dup": False, "excl": [],
                           "sort": "draw", "rosterN": 0, "namesN": 0}
            pool = list(range(1, 71))
            # 昨天：seq_day=1（day 不同，不影响今天次数；用于「全部」筛选）
            y_seed = "11111111%08x" % 1
            y_ms = now - 86400000
            y_res = draw_canon.draw_v1(pool, 10, False, y_seed)
            y = self._new_record("dseed00000007", TEST_SID, y_ms, 1, base_params, pool, y_res, [],
                                 y_seed, "", tamper_result=False, tamper_hash=False)
            self.records[y["id"]] = y
            self.events[y["id"]] = []
            prev = y["hash"]
            for i in range(1, 7):
                seed = "%016x" % (0x2222222200000000 + i)
                ms = now - (7 - i) * 60000
                res = draw_canon.draw_v1(pool, 10, False, seed)
                rec = self._new_record("dseed0000000%d" % i, TEST_SID, ms, i, dict(base_params), pool,
                                       res, [], seed, prev)
                self.records[rec["id"]] = rec
                self.events[rec["id"]] = []
                prev = rec["hash"]
            self.seeded = True

    # ---------------- 公开视图（任何响应都不含 sid） ----------------
    def _event_pub(self, ev):
        return {"seq": ev["seq"], "kind": ev["kind"], "n": ev["n"], "added": ev["added"],
                "note": ev["note"], "at": ev["created_ms"],
                "hash": ev["hash"], "prev_hash": ev["prev_hash"]}

    def _record_pub(self, rec):
        day = self.today()
        is_t = rec["is_test"]
        return {
            "id": rec["id"], "at": rec["created_ms"], "day": rec["day"], "seq_day": rec["seq_day"],
            "today_count": self._count(rec["day"], is_t),
            "today_mine": self._mine(rec["day"], is_t, rec["sid"]),
            "is_mine": rec["sid"] == self.caller_sid,
            "op_name": TEST_NAME if rec["sid"] == TEST_SID else "",
            "op_seat": None,
            "params": rec["params"], "pool": rec["pool"], "result": rec["result"],
            "labels": rec["labels"], "seed": rec["seed"], "algo": rec["algo"],
            "hash": rec["hash"], "canon": rec["canon"], "prev_hash": rec["prev_hash"],
            "event_count": len(self.events.get(rec["id"]) or []),
            "events": [self._event_pub(e) for e in (self.events.get(rec["id"]) or [])],
        }

    def _summary(self, rec):
        return {"id": rec["id"], "at": rec["created_ms"], "day": rec["day"],
                "seq_day": rec["seq_day"], "params": rec["params"], "result": rec["result"],
                "labels": rec["labels"], "hash": rec["hash"],
                "event_count": len(self.events.get(rec["id"]) or []),
                "is_mine": rec["sid"] == self.caller_sid,
                "op_name": TEST_NAME if rec["sid"] == TEST_SID else "", "op_seat": None}

    # ---------------- RPC ----------------
    def handle_rpc(self, name, body):
        if name == "class_members":
            return MEMBERS
        if name == "class_verify":
            return {"ok": True, "token": MOCK_TOKEN, "sid": TEST_SID, "name": TEST_NAME,
                    "role": "", "badge": "", "is_admin": False}
        if name == "class_set_role":
            return {"ok": True}
        if name == "draw_record_create":
            return self.rpc_create(body)
        if name == "draw_record_get":
            return self.rpc_get(body)
        if name == "draw_record_list":
            return self.rpc_list(body)
        if name == "draw_event_append":
            return self.rpc_event(body)
        if name == "draw_test_purge":
            with self.lock:
                rid = str((body or {}).get("p_id") or "")
                if rid in self.records and self.records[rid]["is_test"]:
                    del self.records[rid]
                    self.events.pop(rid, None)
                    return {"ok": True, "deleted": 1}
            return {"ok": False, "reason": "仅测试身份可清理"}
        if name == "draw_test_clear":
            with self.lock:
                ids = [k for k, v in self.records.items() if v["is_test"]]
                for k in ids:
                    del self.records[k]
                    self.events.pop(k, None)
            return {"ok": True, "deleted": len(ids)}
        return {"ok": False, "reason": "mock-unknown-rpc:" + name}

    def rpc_create(self, body):
        body = body or {}
        if self.fail_create:
            return {"ok": False, "reason": "存证失败，请重试"}
        if self.hang_create:
            hang = self.hang_create
            self.hang_create = 0
            time.sleep(hang)
        if self.delay_create:
            delay = self.delay_create
            self.delay_create = 0
            time.sleep(delay)
        rid = str(body.get("p_id") or "")
        seed = str(body.get("p_seed") or "")
        algo = str(body.get("p_algo") or "draw-v1")
        if not re.match(r"^d[0-9a-z]{8,31}$", rid):
            return {"ok": False, "reason": "参数不合法"}
        if not re.match(r"^[0-9a-f]{16}$", seed):
            return {"ok": False, "reason": "参数不合法"}
        if algo != "draw-v1":
            return {"ok": False, "reason": "参数不合法"}
        try:
            params, pool, result, labels = draw_canon.normalize_create(
                body.get("p_params"), body.get("p_pool"), body.get("p_result"), body.get("p_labels"))
        except draw_canon.BadParam as exc:
            return {"ok": False, "reason": str(exc)}
        with self.lock:
            if rid in self.records:
                rec = self.records[rid]
                if rec["sid"] == self.caller_sid:
                    return {"ok": True, "today_count": self._count(rec["day"], rec["is_test"]),
                            "today_mine": self._mine(rec["day"], rec["is_test"], rec["sid"]),
                            "record": self._record_pub(rec)}
                return {"ok": False, "reason": "记录编号冲突"}
            now = self.now_ms()
            day = draw_canon.local_day(now)
            is_t = self.is_test(self.caller_sid)
            seq = self._count(day, is_t) + 1
            th = self.tamper_hash > 0
            tr = self.tamper_result > 0
            if th:
                self.tamper_hash -= 1
            if tr:
                self.tamper_result -= 1
            rec = self._new_record(rid, self.caller_sid, now, seq, params, pool, result, labels,
                                   seed, self._prev(is_t), algo=algo,
                                   tamper_result=tr, tamper_hash=th)
            self.records[rid] = rec
            self.events[rid] = []
            return {"ok": True, "today_count": self._count(day, is_t),
                    "today_mine": self._mine(day, is_t, self.caller_sid),
                    "record": self._record_pub(rec)}

    def rpc_get(self, body):
        rid = str((body or {}).get("p_id") or "")
        with self.lock:
            rec = self.records.get(rid)
            if not rec or rec["is_test"] != self.is_test(self.caller_sid):
                return {"ok": False, "reason": "记录不存在"}
            return {"ok": True, "record": self._record_pub(rec)}

    def rpc_list(self, body):
        body = body or {}
        scope = str(body.get("p_scope") or "today")
        try:
            limit = int(body.get("p_limit") or 30)
        except Exception:  # noqa: BLE001
            limit = 30
        limit = max(1, min(100, limit))
        with self.lock:
            is_t = self.is_test(self.caller_sid)
            day = self.today()
            recs = [r for r in self.records.values() if r["is_test"] == is_t]
            if scope == "today":
                recs = [r for r in recs if r["day"] == day]
                recs.sort(key=lambda r: (r["seq_day"], r["id"]), reverse=True)
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", scope):
                recs = [r for r in recs if r["day"] == scope]
                recs.sort(key=lambda r: (r["created_ms"], r["id"]), reverse=True)
            else:
                scope = "all"
                recs.sort(key=lambda r: (r["created_ms"], r["id"]), reverse=True)
            recs = recs[:limit]
            return {"ok": True, "scope": scope, "day": day,
                    "today_count": self._count(day, is_t),
                    "today_mine": self._mine(day, is_t, self.caller_sid),
                    "records": [self._summary(r) for r in recs]}

    def rpc_event(self, body):
        body = body or {}
        rid = str(body.get("p_id") or "")
        kind = str(body.get("p_kind") or "")
        n = body.get("p_n")
        added = body.get("p_added")
        note = str(body.get("p_note") or "")[:120]
        if kind not in ("remove", "refill", "sort", "reset"):
            return {"ok": False, "reason": "事件不合法"}
        with self.lock:
            rec = self.records.get(rid)
            if not rec or rec["sid"] != self.caller_sid:
                return {"ok": False, "reason": "记录不存在"}
            evs = self.events.setdefault(rid, [])
            seq = len(evs) + 1
            prev = evs[-1]["hash"] if evs else rec["hash"]
            now = self.now_ms()
            ev = {"seq": seq, "kind": kind,
                  "n": None if n is None else int(n),
                  "added": None if added is None else int(added),
                  "note": note, "created_ms": now, "prev_hash": prev}
            ev["hash"] = draw_canon.hash_event(rid, seq, kind, ev["n"], ev["added"], note, now, prev)
            evs.append(ev)
            return {"ok": True, "event": self._event_pub(ev), "event_count": len(evs)}

    # ---------------- 请求日志 / 快照 ----------------
    def log(self, kind, name, method, body, url=""):
        with self.lock:
            self.requests.append({"kind": kind, "name": name, "method": method,
                                  "body": body, "url": url, "at": self.now_ms()})

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({"records": self.records, "events": self.events,
                                  "requests": self.requests})

    def latest_record(self):
        with self.lock:
            recs = sorted(self.records.values(), key=lambda r: (r["created_ms"], r["id"]))
            return copy.deepcopy(recs[-1]) if recs else None

    def reqs(self, name):
        with self.lock:
            return [copy.deepcopy(r) for r in self.requests if r["name"] == name]


MOCK = MockCloud()


class Handler(http.server.SimpleHTTPRequestHandler):
    """静态站点（tools/）+ /__mock/cb/* mock 云端。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n > 0 else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else None
        except Exception:  # noqa: BLE001
            return None

    def do_GET(self):
        if self.path.startswith("/__mock/state"):
            return self._json(MOCK.snapshot())
        if self.path.startswith("/__mock/cb/"):
            MOCK.log("table", self.path, "GET", None, self.path)
            return self._json([])
        return super().do_GET()

    def do_HEAD(self):
        if self.path.startswith("/__mock/"):
            return self._json({})
        return super().do_HEAD()

    def do_POST(self):
        body = self._body()
        if self.path.startswith("/__mock/cb/rpc/"):
            name = self.path.rsplit("/", 1)[-1].split("?")[0]
            MOCK.log("rpc", name, "POST", body, self.path)
            return self._json(MOCK.handle_rpc(name, body))
        if self.path.startswith("/__mock/cb/"):
            MOCK.log("table", self.path.split("?")[0], "POST", body, self.path)
            return self._json([])
        self.send_error(404)

    def do_PATCH(self):
        body = self._body()
        if self.path.startswith("/__mock/cb/"):
            MOCK.log("table", self.path.split("?")[0], "PATCH", body, self.path)
            return self._json([])
        self.send_error(404)

    def do_DELETE(self):
        if self.path.startswith("/__mock/cb/"):
            MOCK.log("table", self.path.split("?")[0], "DELETE", None, self.path)
            return self._json([])
        self.send_error(404)


class _Srv(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


def free_port():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def start_server(port):
    handler = lambda *a, **kw: Handler(*a, directory=ROOT, **kw)  # noqa: E731
    srv = _Srv(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ============================================================
# 浏览器侧注入：测试身份 + fetch 改写到 mock 服务端 + 错误/请求捕获
# ============================================================
INIT_JS = r"""
(function(){
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
/* 官方测试身份（公开凭据，不涉及任何真实账号） */
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"__TOKEN__",sid:"__SID__",name:"__NAME__",role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
/* 本机「名单」文本：nameOf 的班级名单派生名兜底（只在这里出现的 9 号用于优先级验证）。
   登录后 D 使用分账号 key（zq_tools_v2_<sid>），两份都种；只在缺失时种，避免覆盖真实保存的数据。
   rosterMigrated=true：跳过旧数据「roster 文本 → 座号」迁移，保证本夹具稳定。 */
try{
  var _dv={roster:"__ROSTER__",rosterMigrated:true};
  if(!localStorage.getItem("zq_tools_v2"))localStorage.setItem("zq_tools_v2",JSON.stringify(_dv));
  if(!localStorage.getItem("zq_tools_v2___SID__"))localStorage.setItem("zq_tools_v2___SID__",JSON.stringify(_dv));
}catch(e){}
window.confirm=function(){window.__CONFIRMS=(window.__CONFIRMS||0)+1;return true;};
/* canvas 文本捕获：校验导出图确实渲染了存证信息 */
window.__TEXTS=[];
try{var _ft=CanvasRenderingContext2D.prototype.fillText;
CanvasRenderingContext2D.prototype.fillText=function(t){try{window.__TEXTS.push(String(t));}catch(e){}return _ft.apply(this,arguments);};}catch(e){}
/* 下载捕获（不真的落盘） */
window.__DL=[];
try{var _ac=HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click=function(){if(this.download){window.__DL.push(String(this.download));return;}return _ac.apply(this,arguments);};}catch(e){}
var CBRE=/^https:\/\/tool-d4gosudok46e0e081\.api\.tcloudbasegateway\.com\/v1\/rdb\/rest\//;
window.__MOCK={reqs:[],external:[]};
var _f=window.fetch;
window.fetch=function(u,o){
  o=o||{};
  var s=String((u&&u.url!==undefined)?u.url:u);
  var mt=String(o.method||(u&&u.method)||"GET").toUpperCase();
  if(s.indexOf("tcloudbasegateway")>=0){
    var rest=s.replace(CBRE,"");
    var local=location.origin+"/__mock/cb/"+rest;
    var body=null;try{body=o.body?JSON.parse(o.body):null;}catch(e){body=null;}
    var isRpc=rest.indexOf("rpc/")>=0;
    window.__MOCK.reqs.push({kind:isRpc?"rpc":"table",name:isRpc?rest.replace(/^.*rpc\//,"").split("?")[0]:rest.split("?")[0],method:mt,body:body,url:rest.slice(0,160)});
    var oo={method:mt,headers:o.headers||{},cache:"no-store"};
    if(o.body)oo.body=o.body;
    return _f.call(window,local,oo);
  }
  if(s.indexOf("tt.json")>=0){
    return Promise.resolve(new Response(JSON.stringify({c:[],t:"",meta:{}}),{status:200,headers:{"Content-Type":"application/json"}}));
  }
  if(s.indexOf("127.0.0.1")>=0||s.indexOf("localhost")>=0)return _f.apply(window,arguments);
  window.__MOCK.external.push(String(s).slice(0,160));
  return Promise.reject(new Error("external-blocked"));
};
})();
"""


def init_js():
    return (INIT_JS.replace("__TOKEN__", MOCK_TOKEN)
            .replace("__SID__", TEST_SID).replace("__NAME__", TEST_NAME)
            .replace("__ROSTER__", ROSTER_SEED.replace("\n", "\\n")))


def make_snapshot():
    """把当前 tools/index.html 复制成测试快照（并行会话仍在编辑，测试只针对快照）。"""
    src = os.path.join(ROOT, "index.html")
    with open(src, "rb") as fh:
        data = fh.read()
    tmp = SNAPSHOT + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, SNAPSHOT)
    sha = hashlib.sha256(data).hexdigest()
    SNAPSHOT_SHA[0] = sha
    return sha, len(data)


def page_url(port):
    return "http://127.0.0.1:%d%s" % (port, PAGE_PATH)


# ============================================================
# 页面操作辅助
# ============================================================
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


def count(pg, sel):
    return ev(pg, "document.querySelectorAll(%s).length" % jsq(sel))


def body_text(pg):
    return ev(pg, "document.body?String(document.body.innerText||''):''")


def modal_open(pg, mid):
    return ev(pg, "(function(){var e=document.getElementById(%s);return !!(e&&e.style.display!=='none');})()" % jsq(mid))


def state(pg):
    raw = ev(pg, "JSON.stringify(window.DRAWPROOF?window.DRAWPROOF.state():null)")
    return json.loads(raw or "null") or {}


def export_obj(pg):
    raw = ev(pg, "JSON.stringify(window.__lastDrawExport||null)")
    return json.loads(raw or "null")


def drawn_texts(pg):
    return json.loads(ev(pg, "JSON.stringify(window.__TEXTS||[])")) or []


def dl_names(pg):
    return json.loads(ev(pg, "JSON.stringify(window.__DL||[])")) or []


def clears_texts(pg):
    ev(pg, "(function(){window.__TEXTS=[];window.__DL=[];return true;})()")


def reqs_js(pg, name):
    raw = ev(pg, "JSON.stringify((window.__MOCK.reqs||[]).filter(function(r){return r.name===%s;}))" % jsq(name))
    return json.loads(raw or "[]")


def wait_proof(pg, status, timeout=15):
    return pg.wait_for("(function(){try{var s=DRAWPROOF.state();return !!(s.proof&&s.proof.status===%s);}catch(e){return false;}})()"
                       % jsq(status), timeout)


def wait_exports(pg, marker, timeout=20):
    """等导出完成：实现内置测试钩子 `window.__lastDrawExport` 每次导出都会被覆盖。"""
    return pg.wait_for("JSON.stringify(window.__lastDrawExport||null)!==%s" % jsq(marker), timeout)


def wait_dl(pg, n, timeout=10):
    """等导出落盘（optSaveCanvas → canvas.toBlob 异步回调里才创建 <a download>）。"""
    return pg.wait_for("(window.__DL||[]).length>%d" % n, timeout)


def export_marker(pg):
    return ev(pg, "JSON.stringify(window.__lastDrawExport||null)")


def rec_of(rid):
    return (MOCK.snapshot()["records"] or {}).get(rid) or {}


def wait_idle(pg, sec=0.25):
    pg.sleep(sec)


# ============================================================
# 主流程
# ============================================================
def run(pg, port):
    # ---------------- A. 启动 / 静态 ----------------
    ok = pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof DRAWPROOF!=='undefined'", 25)
    T("A1 启动：测试身份通过 + DRAWPROOF 探针装载", ok)
    T("A2 APP_VER 仍为 2.0.0",
      ev(pg, "(function(){var e=document.querySelector('.idver,.ugver');return !!e&&e.textContent.indexOf('2.0.0')>=0;})()"))
    T("A3 探针契约：algo=draw-v1 / state / nameOf / verifyUrl / openRecords / openVerify",
      ev(pg, "(function(){var p=window.DRAWPROOF;return !!p&&p.algo==='draw-v1'&&typeof p.state==='function'&&"
             "typeof p.nameOf==='function'&&typeof p.verifyUrl==='function'&&typeof p.openRecords==='function'&&"
             "typeof p.openVerify==='function'&&typeof p.drawV1==='function';})()"))
    T("A4 初始无存证记录（未点抽签不发 create）", len(MOCK.reqs("draw_record_create")) == 0)
    T("A5 名称映射初始摘要「未设置」", "未设置" in text_of(pg, "#aNamesSum"))
    T("A6 存证状态行初始隐藏", ev(pg, "(function(){var e=document.getElementById('aProof');return !!e&&e.style.display==='none';})()"))
    T("A7 初始无抽签结果（#aOut 空态）", "—" in body_text(pg) and ev(pg, "document.querySelectorAll('#aOut .rcell').length===0"))

    # ---------------- B. 名称映射（§3.1） ----------------
    click(pg, "#aNamesBtn")
    pg.wait_for("(function(){var e=document.getElementById('nmModal');return e&&e.style.display!=='none';})()", 8)
    T("B1 名称映射弹层可打开（#nmModal）", modal_open(pg, "nmModal"))
    T("B2 弹层标题/说明：名称映射 + 每行：序号 名称",
      ("名称映射" in text_of(pg, "#nmModal")) and ("每行：序号 名称" in text_of(pg, "#nmModal")))
    T("B3 初始 textarea 为空、计数「已映射 0 项」",
      ev(pg, "document.getElementById('nmText').value===''") and ("已映射 0 项" in text_of(pg, "#nmCount")))
    T("B4 打开弹层压入 history（HIST modal=drawnames）",
      ev(pg, "(function(){try{return !!(history.state&&history.state.modal==='drawnames');}catch(e){return false;}})()"))
    # 解析规则：带分隔符 / 无序号自增 / 重复后值覆盖
    parse_txt = "5 第五组\n3. 第三组\n10、第十组\n2: 第二组\n2 覆盖二\n无序号名称"
    set_val(pg, "#nmText", parse_txt)
    pg.sleep(0.15)
    T("B5 输入即时解析计数：已映射 5 项（重复序号后值覆盖）",
      "已映射 5 项" in text_of(pg, "#nmCount"), text_of(pg, "#nmCount"))
    click(pg, "#nmOk")
    pg.wait_for("(function(){var e=document.getElementById('nmModal');return e&&e.style.display==='none';})()", 6)
    st = state(pg)
    want_names = "2 覆盖二\n3 第三组\n5 第五组\n10 第十组\n11 无序号名称"
    T("B6 保存归一：升序「序号 名称」行（含无序号自增 11）", st.get("names") == want_names,
      repr(st.get("names")))
    T("B7 摘要显示「已映射 5 项」", "已映射 5 项" in text_of(pg, "#aNamesSum"))
    T("B8 名称优先级：映射 > 班级名单派生名 > ''",
      pg.wait_for("(function(){var p=window.DRAWPROOF;return p.nameOf(2)==='覆盖二'&&p.nameOf(9)==='张九座'&&p.nameOf(70)==='';})()", 6),
      "2=%r 9=%r 70=%r" % (ev(pg, "DRAWPROOF.nameOf(2)"), ev(pg, "DRAWPROOF.nameOf(9)"), ev(pg, "DRAWPROOF.nameOf(70)")))
    # 重开弹层回填已保存文本
    click(pg, "#aNamesBtn")
    pg.wait_for("(function(){var e=document.getElementById('nmModal');return e&&e.style.display!=='none';})()", 8)
    T("B9 重开弹层回填已保存映射文本",
      ev(pg, "document.getElementById('nmText').value") == want_names)
    # 清空按钮只改 textarea，取消不保存
    click(pg, "#nmClear")
    T("B10 清空按钮：textarea 清空且计数归零",
      ev(pg, "document.getElementById('nmText').value===''") and ("已映射 0 项" in text_of(pg, "#nmCount")))
    click(pg, "#nmCancel")
    pg.wait_for("(function(){var e=document.getElementById('nmModal');return e&&e.style.display==='none';})()", 6)
    T("B11 取消不保存（映射仍为 5 项）", state(pg).get("names") == want_names)
    # Esc 关闭
    click(pg, "#aNamesBtn")
    pg.wait_for("(function(){var e=document.getElementById('nmModal');return e&&e.style.display!=='none';})()", 8)
    ev(pg, "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));true")
    pg.sleep(0.2)
    T("B12 Esc 关闭名称映射弹层（且不保存）", not modal_open(pg, "nmModal"))
    # 全量 70 项映射：覆盖抽签结果所有号码，用于 chips / labels / 导出断言
    all70 = "\n".join("%d 第%d组" % (i, i) for i in range(1, 71))
    click(pg, "#aNamesBtn")
    pg.wait_for("(function(){var e=document.getElementById('nmModal');return e&&e.style.display!=='none';})()", 8)
    set_val(pg, "#nmText", all70)
    pg.sleep(0.15)
    T("B13 70 项映射计数正确（已映射 70 项）", "已映射 70 项" in text_of(pg, "#nmCount"))
    click(pg, "#nmOk")
    pg.wait_for("(function(){var e=document.getElementById('nmModal');return e&&e.style.display==='none';})()", 6)
    st = state(pg)
    T("B14 70 项映射保存/摘要", st.get("mapped") == 70 and ("已映射 70 项" in text_of(pg, "#aNamesSum")))
    T("B15 映射持久化到本机（zq_tools_v2_<sid>.draw.names）",
      ev(pg, "(function(){try{var d=JSON.parse(localStorage.getItem('zq_tools_v2___SID__')||'{}');"
             "return !!(d.draw&&d.draw.names&&d.draw.names.split('\\n').length===70);}catch(e){return false;}})()"
         .replace("__SID__", TEST_SID)))
    pg.screenshot(os.path.join(SHOTS, "names_modal_430.png"))

    # 刷新后映射仍在（本机缓存持久化；UD v6 draw.names 字段）
    pg.navigate(page_url(port))
    pg.wait_load(25)
    ok = pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof DRAWPROOF!=='undefined'", 25)
    T("B16 刷新后身份/探针恢复", ok)
    T("B17 刷新后名称映射仍为 70 项（draw.names 持久化）",
      pg.wait_for("(function(){try{return DRAWPROOF.state().mapped===70&&document.getElementById('aNamesSum').textContent.indexOf('70 项')>=0;}catch(e){return false;}})()", 12))

    # ---------------- C. 抽签创建存证（§3.2） ----------------
    n_before = len(MOCK.reqs("draw_record_create"))
    click(pg, "#aRun")
    ok = wait_proof(pg, "ok", 15)
    T("C1 点「开始抽签」创建存证成功（draw_record_create）", ok)
    T("C2 每次抽签 = 一条记录（create 只发 1 次）", len(MOCK.reqs("draw_record_create")) == n_before + 1)
    creates = MOCK.reqs("draw_record_create")
    cre = (creates[-1]["body"] or {}) if creates else {}
    rid1 = cre.get("p_id")
    seed1 = cre.get("p_seed")
    T("C3 create 请求 p_id 合法（d+8..31 位 [0-9a-z]）", bool(rid1 and re.match(r"^d[0-9a-z]{8,31}$", rid1)), rid1)
    T("C4 create 请求 p_seed 为 16 位小写 hex", bool(seed1 and re.match(r"^[0-9a-f]{16}$", seed1)), seed1)
    T("C5 create 请求 p_algo=draw-v1", cre.get("p_algo") == "draw-v1")
    params = cre.get("p_params") or {}
    T("C6 p_params 白名单键齐全（range/count/dup/excl/sort/rosterN/namesN）",
      set(params.keys()) == {"range", "count", "dup", "excl", "sort", "rosterN", "namesN"},
      str(sorted(params.keys())))
    T("C7 p_params 值：range[1,70] / count=10 / dup=false / sort=draw",
      params.get("range") == [1, 70] and params.get("count") == 10 and params.get("dup") is False
      and params.get("sort") == "draw")
    T("C8 p_params.excl 归一去重升序（空数组）", params.get("excl") == [])
    T("C9 p_params.rosterN=0（未选参与名单）", params.get("rosterN") == 0)
    T("C10 p_params.namesN=70（含名称映射项数）", params.get("namesN") == 70)
    pool = cre.get("p_pool") or []
    T("C11 p_pool = 1..70（范围−排除）", pool == list(range(1, 71)), "len=%d" % len(pool))
    result = cre.get("p_result") or []
    T("C12 p_result 长度=count 且互不重复且 ∈ pool",
      len(result) == 10 and len(set(result)) == 10 and all(x in pool for x in result), str(result))
    T("C13 p_result = drawV1(pool,10,false,seed)（seed 可复算）",
      result == draw_canon.draw_v1(pool, 10, False, seed1), str(result[:5]))
    st = state(pg)
    T("C14 探针 result 与请求 result 一致", st.get("result") == result)
    T("C15 探针 seed 与请求 seed 一致", st.get("seed") == seed1)
    labels = cre.get("p_labels") or []
    want_labels = [{"n": n, "nm": "第%d组" % n} for n in sorted(result)]
    T("C16a p_labels 只含命中结果的 {n,nm}，且覆盖全部 10 个结果",
      len(labels) == len(result) and [x.get("n") for x in labels] and
      set(x.get("n") for x in labels) == set(result) and
      all((x.get("nm") or "") == "第%d组" % x.get("n") for x in labels),
      str(labels[:3]))
    T("C16b 服务端把 p_labels 归一为 n 升序（契约 §1.4）",
      rec_of(rid1).get("labels") == want_labels, str(rec_of(rid1).get("labels"))[:120])
    T("C16c p_labels 每项 nm ≤40 字", all(1 <= len(x.get("nm") or "") <= 40 for x in labels))
    rec1 = MOCK.latest_record()
    T("C17 create 返回 record.id == 请求 p_id", bool(rec1 and rec1["id"] == rid1))
    T("C18 首次抽签 seq_day=7（mock 预置今日 6 条后）", bool(rec1 and rec1["seq_day"] == 7), str(rec1 and rec1.get("seq_day")))
    T("C19 today_count=7 / today_mine=7", bool(rec1 and MOCK._count(rec1["day"], True) == 7
                                              and MOCK._mine(rec1["day"], True, TEST_SID) == 7))
    T("C20 记录 prev_hash = 链上一条 hash（预置第 6 条的 hash）",
      bool(rec1 and rec1["prev_hash"] == MOCK.records["dseed00000006"]["hash"]))
    T("C21 状态行显示「已存证」", "已存证" in text_of(pg, "#aProof"))
    T("C22 状态行显示「已存证 · 今日第 7 次（全班今日共 7 次）」",
      ("已存证 · 今日第 7 次" in text_of(pg, "#aProof")) and ("全班今日共 7 次" in text_of(pg, "#aProof")),
      text_of(pg, "#aProof"))
    T("C23 #aRecSum 摘要「今日第 7 次 · 共 7 次」", "今日第 7 次" in text_of(pg, "#aRecSum"))
    T("C24 结果区 chips 全部带自定义名称（10/10 mapped）",
      count(pg, "#aOut .rcell.mapped") == 10, "mapped=%s" % count(pg, "#aOut .rcell.mapped"))
    chip_names = json.loads(ev(pg, "JSON.stringify([].map.call(document.querySelectorAll('#aOut .rname'),function(e){return e.textContent;}))"))
    T("C25 chips 名称 = 第N组（与映射一致）", chip_names == ["第%d组" % n for n in result], str(chip_names[:3]))

    # 第二次抽签：新记录、seq_day+1、哈希链前进
    click(pg, "#aRun")
    ok = pg.wait_for("(function(){try{var s=DRAWPROOF.state();return s.proof&&s.proof.status==='ok'&&s.proof.id!==%s;}catch(e){return false;}})()" % jsq(rid1), 15)
    T("C26 第二次抽签创建新记录", ok)
    creates = MOCK.reqs("draw_record_create")
    cre2 = (creates[-1]["body"] or {}) if creates else {}
    rid2 = cre2.get("p_id")
    rec2 = MOCK.latest_record()
    T("C27 第二次记录 seq_day=8 / today_count=8", bool(rec2 and rec2["seq_day"] == 8), str(rec2 and rec2.get("seq_day")))
    T("C28 第二次记录 prev_hash = 第一条记录 hash（哈希链）",
      bool(rec2 and rec1 and rec2["prev_hash"] == rec1["hash"]))
    T("C29 状态行「今日第 8 次」", "今日第 8 次" in text_of(pg, "#aProof"), text_of(pg, "#aProof"))

    # ---------------- D. 导出图片（§3.3，已存证） ----------------
    clears_texts(pg)
    marker = export_marker(pg)
    dl_before = len(dl_names(pg))
    click(pg, "#aImg")
    ok = wait_exports(pg, marker, 20)
    T("D1 点导出图片完成（已存证）", ok)
    eo = export_obj(pg)
    if not eo:
        T("D2 导出 hook 可用（window.__lastDrawExport）", False, "无导出捕获")
    else:
        T("D2 导出参数 rec = 存证记录 id", eo.get("rec") == rid2, str(eo.get("rec")))
        cfg = {str(k): v for k, v in (eo.get("config") or [])}
        T("D3 参数区含 存证编号", cfg.get("存证编号") == rid2)
        T("D4 参数区含 存证时间（服务器时间 YYYY-MM-DD HH:MM:SS）",
          bool(re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", str(cfg.get("存证时间") or ""))),
          str(cfg.get("存证时间")))
        T("D5 参数区 今日抽签=第 8 次（今日共 8 次）", cfg.get("今日抽签") == "第 8 次（今日共 8 次）",
          str(cfg.get("今日抽签")))
        T("D6 参数区 记录哈希=hash 前 16 位", cfg.get("记录哈希") == rec2["hash"][:16], str(cfg.get("记录哈希")))
        T("D7 参数区 名称映射=70 项", cfg.get("名称映射") == "70 项", str(cfg.get("名称映射")))
        T("D8 参数区其它项齐全（范围/个数/允许重复/排除/排序/可用池）",
          all(k in cfg for k in ("范围", "抽取个数", "允许重复", "排除序号", "结果排序", "可用池")))
        want_qr = "https://tool.furina.fun/#verify=" + rid2
        T("D9 QR=本站核验深链（非本站域名回退 tool.furina.fun）", eo.get("qr") == want_qr, str(eo.get("qr")))
        T("D10 qrTitle=抽签存证核验", eo.get("qrTitle") == "抽签存证核验")
        T("D11 qrCap=扫码核验本次抽签记录（需登录班级身份）",
          eo.get("qrCap") == "扫码核验本次抽签记录（需登录班级身份）")
        want_note = ["存证编号 " + rid2, "记录哈希 " + rec2["hash"][:12], "今日第 8 次 · 共 8 次"]
        T("D12 qrNote 3 行：编号/哈希/今日次数", eo.get("qrNote") == want_note, str(eo.get("qrNote")))
        blocks = eo.get("blocks") or []
        chips = (blocks[0] or {}).get("chips") if blocks else None
        T("D13 抽签结果 chips 10 个且带名称",
          bool(chips) and len(chips) == 10 and all(c.get("nm", "").startswith("第") for c in chips))
        T("D14 导出文件名规范（抽签结果_YYYYMMDD-HHMM_范围…png）",
          wait_dl(pg, dl_before) and any(
              re.match(r"^抽签结果_\d{8}-\d{4}_范围1-70_抽10个_不重复_按抽取顺序\.png$", n)
              for n in dl_names(pg)),
          str(dl_names(pg)[-1:]))
        texts = drawn_texts(pg)
        T("D15 导出图实际渲染「抽签存证核验」标题（canvas 文本）", "抽签存证核验" in texts)
        T("D16 导出图实际渲染 存证编号（canvas 文本）",
          any(t == "存证编号 " + rid2 for t in texts), str([t for t in texts if "存证编号" in t][:2]))
        T("D17 导出图实际渲染 记录哈希（canvas 文本）",
          any(t == "记录哈希 " + rec2["hash"][:12] for t in texts), str([t for t in texts if "记录哈希" in t][:2]))
    pg.screenshot(os.path.join(SHOTS, "draw_after_proof_430.png"))

    # ---------------- E. 剔除重抽事件（§3.2 事件链） ----------------
    n_ev = len(MOCK.reqs("draw_event_append"))
    removed_n = ev(pg, "(function(){var e=document.querySelector('#aOut .rcell');return e?Number(e.getAttribute('data-n')):null;})()")
    click(pg, "#aOut .rcell .rx")
    pg.sleep(0.6)
    evs = MOCK.reqs("draw_event_append")
    T("E1 剔除自动重抽：draw_event_append(kind=remove) 已发送", len(evs) == n_ev + 1)
    evb = (evs[-1]["body"] or {}) if evs else {}
    T("E2 事件 kind=remove / n=被剔除号", evb.get("p_kind") == "remove" and evb.get("p_n") == removed_n,
      "n=%s removed=%s" % (evb.get("p_n"), removed_n))
    T("E3 自动重抽：added=补抽号码且 ∈ 池", isinstance(evb.get("p_added"), int) and evb.get("p_added") in pool,
      str(evb.get("p_added")))
    evs_snap = MOCK.snapshot()["events"][rid2]
    T("E4 事件链：seq=1 / prev_hash=记录 hash", len(evs_snap) == 1 and evs_snap[0]["seq"] == 1
      and evs_snap[0]["prev_hash"] == rec2["hash"])
    T("E5 事件 hash 可复算（sha256(ev_canon)）",
      evs_snap[0]["hash"] == draw_canon.hash_event(rid2, 1, "remove", evb.get("p_n"), evb.get("p_added"),
                                                  "", evs_snap[0]["created_ms"], rec2["hash"]))
    st = state(pg)
    T("E6 记录 event_count 更新为 1", (st.get("proof") or {}).get("record", {}).get("event_count") == 1,
      str((st.get("proof") or {}).get("record", {}).get("event_count")))
    # 排序不改结果集合、不记事件
    res_before = state(pg).get("result")
    n_ev = len(MOCK.reqs("draw_event_append"))
    click(pg, '#aSortRow .btn[data-asort="desc"]')
    pg.sleep(0.25)
    T("E7 排序从大到小：结果集合不变、不追加事件",
      len(MOCK.reqs("draw_event_append")) == n_ev and sorted(state(pg).get("result") or []) == sorted(res_before))
    # 带剔除明细的导出：qrNote 不丢 + 纯文本块承接剔除明细（§3.3）
    clears_texts(pg)
    marker = export_marker(pg)
    click(pg, "#aImg")
    ok = wait_exports(pg, marker, 20)
    eo2 = export_obj(pg)
    T("E8 剔除后再次导出成功", ok and bool(eo2))
    blocks = (eo2 or {}).get("blocks") or []
    rm_block = [b for b in blocks if b.get("label") == "剔除重抽"]
    T("E9 剔除明细改放纯文本块「剔除重抽」", len(rm_block) == 1, str([b.get("label") for b in blocks]))
    rm_lines = (rm_block[0].get("lines") if rm_block else []) or []
    want_line = "#1 剔除 %s → 补抽 %s" % (evb.get("p_n"), evb.get("p_added"))
    T("E10 剔除块内容「#1 剔除 x → 补抽 y」", bool(rm_lines and rm_lines[0] == want_line), str(rm_lines))
    T("E11 带剔除时 QR 存证信息仍保留（qrNote 3 行）",
      (eo2 or {}).get("qr") == "https://tool.furina.fun/#verify=" + rid2,
      str((eo2 or {}).get("qr")))

    # ---------------- F. 重置本轮（reset 事件 + 清空） ----------------
    click(pg, "#aReset")
    pg.sleep(0.7)
    evs = MOCK.reqs("draw_event_append")
    T("F1 重置前追加 kind=reset 事件", bool(evs) and (evs[-1]["body"] or {}).get("p_kind") == "reset")
    st = state(pg)
    T("F2 重置清空结果与存证状态", st.get("result") in (None, []) and st.get("proof") is None,
      "result=%r" % (st.get("result"),))
    T("F3 重置后结果区回空态 / 存证行隐藏",
      count(pg, "#aOut .rcell") == 0 and ev(pg, "document.getElementById('aProof').style.display==='none'"))

    # ---------------- G. 抽签记录弹层（§3.2 记录入口 / 今日·全部·详情） ----------------
    click(pg, "#aRecBtn")
    pg.wait_for("(function(){var b=document.getElementById('recBody');return b&&b.textContent.indexOf('第')>=0&&b.textContent.indexOf('今日')>=0;})()", 10)
    T("G1 记录弹层打开且加载今日记录", modal_open(pg, "recModal") and "抽签记录" in text_of(pg, "#recBody"))
    T("G2 打开记录弹层压入 history（HIST modal=drawrec）",
      ev(pg, "(function(){try{return !!(history.state&&history.state.modal==='drawrec');}catch(e){return false;}})()"))
    req_list = MOCK.reqs("draw_record_list")
    T("G3 默认按今日拉取（p_scope=today）", bool(req_list) and (req_list[-1]["body"] or {}).get("p_scope") == "today",
      str((req_list[-1]["body"] if req_list else {})))
    n_today = count(pg, "#recBody .rec-item")
    T("G4 今日记录 8 条（预置 6 + 两次抽签）", n_today == 8, "items=%s" % n_today)
    T("G5 顶部次数「今日第 8 次 · 全班共 8 次」",
      ("今日第 8 次" in text_of(pg, "#recBody")) and ("全班共 8 次" in text_of(pg, "#recBody")))
    first = ev(pg, "(function(){var e=document.querySelector('#recBody .rec-item');return e?String(e.textContent||''):'';})()")
    T("G6 列表项含 第8次 / 时间 / 范围 1–70 / 抽 10 个 / 结果 / 操作人",
      ("第8次" in first) and ("范围 1–70" in first) and ("抽 10 个" in first) and ("结果" in first)
      and (TEST_NAME in first), first[:160])
    T("G7 列表项含哈希前 12 位（可核对）", rec2["hash"][:12] in first, first[:200])
    T("G8 列表项含剔除重抽次数", "剔除重抽" in first)
    T("G8b 列表项含「查看核验」入口文字", "查看核验" in first, first[-60:])
    T("G9 今日筛选按钮态 on", ev(pg, "(function(){var b=document.querySelector('#recBody [data-rectab=\"today\"]');return !!b&&b.classList.contains('on');})()"))
    # 全部筛选
    click(pg, '#recBody [data-rectab="all"]')
    pg.sleep(0.6)
    req_list = MOCK.reqs("draw_record_list")
    T("G10 切「全部」：p_scope=all", (req_list[-1]["body"] or {}).get("p_scope") == "all")
    n_all = count(pg, "#recBody .rec-item")
    T("G11 全部记录 9 条（含昨天 1 条）", n_all == 9, "items=%s" % n_all)
    T("G12 全部列表含昨天记录（第1次）",
      "第1次" in text_of(pg, "#recBody"), text_of(pg, "#recBody")[:80])
    # 打开详情
    click(pg, '#recBody [data-recid="%s"]' % rid2)
    ok = pg.wait_for("(function(){var b=document.getElementById('recBody');return b&&b.textContent.indexOf('存证编号')>=0;})()", 10)
    T("G13 点击记录打开存证核验详情", ok)
    detail = text_of(pg, "#recBody")
    T("G14 详情：存证编号 = 记录 id", rid2 in detail)
    T("G15 详情：存证时间（服务器 · 精确到秒）",
      "存证时间" in detail and bool(re.search(r"存证时间\s*\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", detail)))
    T("G16 详情：抽签人姓名（+座号可空）", "抽签人" in detail and TEST_NAME in detail)
    T("G17 详情：今日抽签 第 8 次（全班今日共 8 次）",
      ("第 8 次" in detail) and ("全班今日共 8 次" in detail))
    T("G18 详情：参数（范围 1–70 / 抽 10 个 / 不重复 / 名称映射 70 项）",
      "范围 1–70" in detail and "抽 10 个" in detail and "不重复" in detail and "名称映射 70 项" in detail)
    T("G19 详情：初始结果 chips 10 个（带名称）",
      count(pg, "#recBody .rec-chip") == 10 and ("第%d组" % rec2["result"][0]) in text_of(pg, "#recBody"))
    T("G20 详情：剔除重抽时间线 1 条", "剔除重抽" in detail and "剔除" in detail and "补抽" in detail)
    pg.wait_for("document.getElementById('recReplay').textContent.indexOf('✓')>=0", 8)
    T("G21 算法自检：复算 ✓ 一致（draw-v1 seed+pool）",
      "✓" in text_of(pg, "#recReplay") and "一致" in text_of(pg, "#recReplay"), text_of(pg, "#recReplay"))
    T("G22 哈希自检：哈希 ✓ 自检通过（crypto.subtle 复算 canon）",
      "✓" in text_of(pg, "#recHash") and "自检" in text_of(pg, "#recHash"), text_of(pg, "#recHash"))
    T("G23 详情：算法 draw-v1 + 种子明文", "draw-v1" in detail and rec2["seed"] in detail)
    T("G24 详情：完整记录哈希", rec2["hash"] in detail)
    T("G25 详情：核验链接 + 二维码 canvas",
      ("https://tool.furina.fun/#verify=" + rid2) in detail and count(pg, "#recQr") == 1)
    pg.screenshot(os.path.join(SHOTS, "rec_detail_430.png"))
    T("G26 返回列表按钮", click(pg, "#recBack"))
    T("G27 返回后重建列表（保持「全部」筛选 9 条）",
      pg.wait_for("document.querySelectorAll('#recBody .rec-item').length===9", 10),
      "items=%s" % count(pg, "#recBody .rec-item"))
    # 关闭弹层
    click(pg, "#recClose")
    pg.sleep(0.4)
    T("G28 关闭记录弹层且 history 回退（modal 状态清除）",
      (not modal_open(pg, "recModal")) and
      ev(pg, "(function(){try{return !(history.state&&history.state.modal);}catch(e){return false;}})()"))

    # 重新抽签两次（供深链/篡改用）
    click(pg, "#aRun")
    wait_proof(pg, "ok", 15)
    id_a = state(pg)["proof"]["id"]
    click(pg, "#aRun")
    pg.wait_for("(function(){try{var s=DRAWPROOF.state();return s.proof&&s.proof.status==='ok'&&s.proof.id!==%s;}catch(e){return false;}})()" % jsq(id_a), 15)
    id_b = state(pg)["proof"]["id"]
    rec_b = MOCK.records[id_b]
    T("G29 再次抽签两条记录写入（用于深链测试）", bool(id_a and id_b and id_a != id_b))

    # ---------------- H. #verify= 深链（§3.2 深链 / 登录后生效） ----------------
    pg.navigate("about:blank")
    pg.sleep(0.2)
    pg.navigate(page_url(port)+"#verify="+id_b)
    pg.wait_load(25)
    ok = pg.wait_for("(function(){var e=document.getElementById('recModal');return e&&e.style.display!=='none'&&"
                     "document.getElementById('recBody').textContent.indexOf(%s)>=0;})()" % jsq(id_b), 20)
    T("H1 #verify=<id> 深链登录后自动打开存证核验", ok)
    T("H2 深链详情含编号与哈希", id_b in text_of(pg, "#recBody") and rec_b["hash"] in text_of(pg, "#recBody"))
    pg.wait_for("document.getElementById('recReplay').textContent.indexOf('✓')>=0", 8)
    T("H3 深链详情复算/哈希自检双 ✓",
      "✓" in text_of(pg, "#recReplay") and "✓" in text_of(pg, "#recHash"))
    # 关闭：同一 evaluate 内点击并读状态（关闭同步生效；随后 history.back 不得重开）
    closed_now = ev(pg, "(function(){var e=document.getElementById('recClose2');if(!e)return false;"
                        "e.click();return document.getElementById('recModal').style.display==='none';})()")
    pg.sleep(0.8)
    h4_hash = ev(pg, "(function(){return String(location.hash||'');})()")
    h4_open = ev(pg, "(function(){var e=document.getElementById('recModal');return !!e&&getComputedStyle(e).display!=='none';})()")
    T("H4a ①点详情「关闭」：核验弹层关闭", closed_now)
    T("H4b ④关闭后 URL 无 #verify= hash", h4_hash == "", "hash=%r" % h4_hash)
    T("H4c ⑤关闭 800ms 后不自动重开", not h4_open)
    # ⑥ 再次手动设置 location.hash → hashchange 路径仍能打开
    ev(pg, "location.hash='#verify='+%s;true" % jsq(id_b))
    ok = pg.wait_for("(function(){var e=document.getElementById('recModal');return e&&e.style.display!=='none'&&"
                     "document.getElementById('recBody').textContent.indexOf(%s)>=0;})()" % jsq(id_b), 15)
    T("H4d ⑥手动设置 location.hash=#verify= 仍能打开（hashchange 路径）", ok)
    # ② Esc 关闭：不得重开
    esc_closed = ev(pg, "(function(){document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));"
                        "return document.getElementById('recModal').style.display==='none';})()")
    pg.sleep(0.8)
    esc_reopen = ev(pg, "(function(){var e=document.getElementById('recModal');return !!e&&getComputedStyle(e).display!=='none';})()")
    esc_hash = ev(pg, "(function(){return String(location.hash||'');})()")
    T("H4e ②Esc 关闭核验弹层", esc_closed)
    T("H4f Esc 关闭后 800ms 不重开且 URL 无 hash", (not esc_reopen) and esc_hash == "",
      "hash=%r 重开=%s" % (esc_hash, esc_reopen))
    # ③ 浏览器返回键：重新打开 → history.back()（popstate 路径）应关闭而不是重开
    ev(pg, "location.hash='#verify='+%s;true" % jsq(id_b))
    ok = pg.wait_for("document.getElementById('recBody')&&document.getElementById('recBody').textContent.indexOf(%s)>=0" % jsq(id_b), 15)
    T("H4g 浏览器返回键用例：先重新打开详情", ok)
    ev(pg, "history.back();true")
    pg.sleep(0.9)
    back_open = ev(pg, "(function(){var e=document.getElementById('recModal');return !!e&&getComputedStyle(e).display!=='none';})()")
    back_alive = ev(pg, "typeof DRAWPROOF!=='undefined'")
    T("H4h ③浏览器返回键关闭详情（不重开、仍在本页）", back_alive and not back_open,
      "重开=%s 页面存活=%s" % (back_open, back_alive))
    # 不存在的记录（整页新加载，避免上一次弹层/历史干扰）
    pg.navigate("about:blank")
    pg.sleep(0.2)
    pg.navigate(page_url(port)+"#verify=dnonexistent0001")
    pg.wait_load(25)
    ok = pg.wait_for("(function(){var b=document.getElementById('recBody');return b&&b.textContent.indexOf('记录不存在')>=0;})()", 20)
    T("H5 #verify=不存在的记录给出中文提示（记录不存在）", ok, text_of(pg, "#recBody")[:80])

    # ---------------- I. 哈希/复算篡改检测（负例） ----------------
    pg.navigate(page_url(port))
    pg.wait_load(25)
    pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof DRAWPROOF!=='undefined'", 25)
    MOCK.tamper_hash = 1
    click(pg, "#aRun")
    wait_proof(pg, "ok", 15)
    id_t1 = state(pg)["proof"]["id"]
    ev(pg, "window.DRAWPROOF.openVerify(%s);true" % jsq(id_t1))
    ok = pg.wait_for("(function(){var e=document.getElementById('recHash');return e&&e.textContent.indexOf('✗')>=0;})()", 10)
    T("I1 篡改 hash：哈希自检 ✗ 不一致", ok, text_of(pg, "#recHash"))
    T("I2 篡改 hash 但 canon 未变：复算仍 ✓", "✓" in text_of(pg, "#recReplay"), text_of(pg, "#recReplay"))
    click(pg, "#recClose2")
    pg.sleep(0.4)
    MOCK.tamper_result = 1
    click(pg, "#aRun")
    wait_proof(pg, "ok", 15)
    id_t2 = state(pg)["proof"]["id"]
    ev(pg, "window.DRAWPROOF.openVerify(%s);true" % jsq(id_t2))
    ok = pg.wait_for("(function(){var e=document.getElementById('recReplay');return e&&e.textContent.indexOf('✗')>=0;})()", 10)
    T("I3 篡改 result（canon/hash 自洽）：复算 ✗ 不一致", ok, text_of(pg, "#recReplay"))
    T("I4 篡改 result 但 hash 与 canon 自洽：哈希 ✓ 自检通过", "✓" in text_of(pg, "#recHash"), text_of(pg, "#recHash"))
    click(pg, "#recClose2")
    pg.sleep(0.4)

    # ---------------- J. 失败降级「未存证」（§3.3） ----------------
    MOCK.fail_create = True
    click(pg, "#aRun")
    ok = wait_proof(pg, "failed", 10)
    T("J1 存证失败：状态行显示「未存证」", ok and "未存证" in text_of(pg, "#aProof"), text_of(pg, "#aProof"))
    T("J1b 失败原因不含 JS 异常前缀（Error:）", "Error" not in text_of(pg, "#aProof"), text_of(pg, "#aProof"))
    T("J2 失败可重试（重试存证按钮）", count(pg, "#aProofRetry") == 1)
    clears_texts(pg)
    marker = export_marker(pg)
    click(pg, "#aImg")
    ok = wait_exports(pg, marker, 20)
    eo = export_obj(pg)
    T("J3 未存证仍可导出（降级不阻塞）", ok and bool(eo))
    cfg = {str(k): v for k, v in ((eo or {}).get("config") or [])}
    T("J4 参数区「存证=未存证（网络不可用）」", cfg.get("存证") == "未存证（网络不可用）", str(cfg.get("存证")))
    T("J5 未存证导出不带 QR", not (eo or {}).get("qr"))
    T("J6 未存证导出 rec 回退 DRAW- 编号", str((eo or {}).get("rec") or "").startswith("DRAW-"), str((eo or {}).get("rec")))
    T("J7 导出前 toast「本次未存证，图片无法核验」", "本次未存证，图片无法核验" in text_of(pg, "#toast"),
      text_of(pg, "#toast"))
    T("J8 未存证导出图不渲染核验标题", "抽签存证核验" not in drawn_texts(pg))
    MOCK.fail_create = False
    pg.screenshot(os.path.join(SHOTS, "proof_failed_430.png"))

    # ---------------- K. pending（存证中）与导出降级（§3.2/§3.3） ----------------
    MOCK.hang_create = 30     # mock 挂起 create 响应：模拟网络迟迟不返回
    click(pg, "#aRun")
    ok = pg.wait_for("(function(){var e=document.getElementById('aProof');return !!e&&e.className.indexOf('pending')>=0;})()", 5)
    T("K1 存证未返回时状态行「存证中…」", ok and ("存证中" in text_of(pg, "#aProof")), text_of(pg, "#aProof"))
    clears_texts(pg)
    marker = export_marker(pg)
    click(pg, "#aImg")
    ok = wait_exports(pg, marker, 14)
    eo = export_obj(pg)
    T("K2 pending 超约 6s 后导出：降级「未存证」（不阻塞导出）", ok and bool(eo))
    cfgk = {str(k): v for k, v in ((eo or {}).get("config") or [])}
    T("K3 pending 超时导出参数区「存证=未存证（网络不可用）」",
      cfgk.get("存证") == "未存证（网络不可用）", str(cfgk.get("存证")))
    T("K4 pending 超时导出不带 QR", not (eo or {}).get("qr"))
    T("K5 未返回前状态行不误报成功（仍为存证中）",
      "存证中" in text_of(pg, "#aProof"), text_of(pg, "#aProof"))
    MOCK.hang_create = 0

    # ---------------- L. draw-v1 固定测试向量（契约 §2） ----------------
    vec = json.loads(ev(pg, """JSON.stringify((function(){
      var f=window.DRAWPROOF.drawV1;if(typeof f!=='function')return {err:'no-drawV1'};
      function r(a,b){return JSON.stringify(a)===JSON.stringify(b);}
      var out={};
      out.v1=f([1,2,3,4,5,6,7,8,9,10],3,false,'0123456789abcdef');
      out.v2=f([1,2,3,4,5],7,true,'0123456789abcdef');
      var p70=[];for(var i=1;i<=70;i++)p70.push(i);
      out.v3=f(p70,10,false,'deadbeefcafebabe');
      var p8=[];for(var j=1;j<=8;j++)p8.push(j);
      out.v4=f(p8,8,false,'a1b2c3d4e5f60718');
      out.seeds=[];for(var k=0;k<60;k++)out.seeds.push(window.DRAWPROOF.newSeed());
      return out;
    })())""") or "{}")
    T("L1 固定向量1：seed 0123456789abcdef / pool 1..10 / 3 / 不重复 → [9,10,4]", vec.get("v1") == [9, 10, 4], str(vec.get("v1")))
    T("L2 固定向量2：dup=true → [1,3,1,2,2,2,3]", vec.get("v2") == [1, 3, 1, 2, 2, 2, 3], str(vec.get("v2")))
    T("L3 固定向量3：pool 1..70 / 10 → [28,36,11,34,38,1,14,70,65,46]",
      vec.get("v3") == [28, 36, 11, 34, 38, 1, 14, 70, 65, 46], str(vec.get("v3")))
    T("L4 固定向量4：pool 1..8 / 8 → [7,3,1,8,4,5,2,6]", vec.get("v4") == [7, 3, 1, 8, 4, 5, 2, 6], str(vec.get("v4")))
    seeds = vec.get("seeds") or []
    T("L5 newSeed 输出 16 位小写 hex（60 次全部合法）",
      len(seeds) == 60 and all(re.match(r"^[0-9a-f]{16}$", s or "") for s in seeds))
    T("L6 newSeed 随机性（60 个种子去重后 ≥55）", len(set(seeds)) >= 55, "unique=%d" % len(set(seeds)))
    T("L7 网页 drawV1 与 Python 独立实现逐元素一致（4 向量）",
      all(vec.get(k) == draw_canon.draw_v1(*args) for k, args in (
          ("v1", (list(range(1, 11)), 3, False, "0123456789abcdef")),
          ("v2", ([1, 2, 3, 4, 5], 7, True, "0123456789abcdef")),
          ("v3", (list(range(1, 71)), 10, False, "deadbeefcafebabe")),
          ("v4", (list(range(1, 9)), 8, False, "a1b2c3d4e5f60718")))))

    # ---------------- M. 360/390/430 无横向溢出 ----------------
    for w, h in ((430, 900), (390, 844), (360, 780)):
        pg.set_device(w, h, 2.0, True, True)
        pg.sleep(0.35)
        sw = ev(pg, "document.documentElement.scrollWidth")
        vw = ev(pg, "window.innerWidth")
        T("M%d %dpx：抽签页无横向溢出" % (w, w), sw <= vw + 1, "scrollW=%s vw=%s" % (sw, vw))
    # 名称映射弹层 / 记录弹层在窄屏不溢出
    click(pg, "#aNamesBtn")
    pg.wait_for("(function(){var e=document.getElementById('nmModal');return e&&e.style.display!=='none';})()", 8)
    pg.sleep(0.25)
    T("M361 360px：名称映射弹层无横向溢出",
      ev(pg, "document.documentElement.scrollWidth<=window.innerWidth+1"))
    click(pg, "#nmCancel")
    pg.sleep(0.25)
    click(pg, "#aRecBtn")
    pg.wait_for("document.querySelectorAll('#recBody .rec-item').length>=1", 10)
    pg.sleep(0.2)
    T("M362 360px：记录弹层无横向溢出",
      ev(pg, "document.documentElement.scrollWidth<=window.innerWidth+1"))
    click(pg, "#recClose")
    pg.sleep(0.3)
    pg.screenshot(os.path.join(SHOTS, "draw_360.png"))
    pg.set_device(430, 900, 2.0, True, True)
    pg.sleep(0.3)
    pg.screenshot(os.path.join(SHOTS, "draw_430_final.png"))

    # ---------------- N. 报错 / 外部请求 / 隐私红线 ----------------
    errs = pg.all_errors()
    nerr = len(errs.get("exceptions") or []) + len(errs.get("console") or []) + len(errs.get("log") or [])
    js_errs = json.loads(ev(pg, "JSON.stringify(window.__errs||[])"))
    js_cerrs = json.loads(ev(pg, "JSON.stringify(window.__cerrs||[])"))
    T("N1 0 JS 报错（CDP + window.onerror + console.error）",
      nerr == 0 and len(js_errs) == 0 and len(js_cerrs) == 0,
      "cdp=%s onerror=%s console=%s" % (nerr, js_errs[:2], js_cerrs[:2]))
    ext = json.loads(ev(pg, "JSON.stringify(window.__MOCK.external||[])"))
    # 已知既有行为（非抽签功能）：大屏互联的 drop presence 轮询打到 121.196.47.2（被 mock 拦截、无报错），
    # 与 sync_check「全程无外部请求」基线失败同源，按 Lead 口径不计入本功能。
    ext_unexpected = [x for x in ext if "drop/presence" not in x]
    T("N2 0 外部请求（除既有 drop presence 轮询外）", len(ext_unexpected) == 0,
      "unexpected=%s known_drop=%s" % (ext_unexpected[:3], len(ext) - len(ext_unexpected)))
    all_reqs = json.loads(ev(pg, "JSON.stringify(window.__MOCK.reqs||[])"))
    T("N3 云端请求全部经 RPC 通道，无直连 draw_records/draw_events 表",
      not any(r.get("kind") == "table" and "draw_" in str(r.get("url")) for r in all_reqs))
    bt = body_text(pg)
    sid_leak = ("3260799999" in bt) or ("qatok" in bt) or (MOCK_TOKEN in bt)
    T("N4 页面不出现学号/测试 token（隐私红线）", not sid_leak)
    # 导出参数中也不含学号
    eo = export_obj(pg) or {}
    T("N5 导出参数/文本不含学号", "3260799999" not in json.dumps(eo, ensure_ascii=False))
    pub = MOCK.handle_rpc("draw_record_get", {"p_id": rid2})
    T("N6 记录详情响应无 sid/owner_sid 字段（契约公开视图）",
      '"sid"' not in json.dumps(pub, ensure_ascii=False) and
      "owner_sid" not in json.dumps(pub, ensure_ascii=False))
    lst_pub = MOCK.handle_rpc("draw_record_list", {"p_scope": "all"})
    T("N7 记录列表响应无 sid 字段",
      '"sid"' not in json.dumps(lst_pub, ensure_ascii=False))
    return RESULTS


def main():
    sha, size = make_snapshot()
    print("[snapshot] tools/index.html -> %s (%d bytes, sha256 %s)" % (PAGE_PATH, size, sha))
    MOCK.seed()
    port = free_port()
    srv = start_server(port)
    b = _cdp.Browser(window=(430, 900))
    try:
        pg = b.new_page("about:blank")
        pg.set_device(430, 900, 2.0, True, True)
        pg.add_init_script(init_js())
        T("S0 测试针对 index.html 快照（并行会话编辑隔离，%d bytes / sha256 %s…）"
          % (size, sha[:12]), size > 1000000 and os.path.isfile(SNAPSHOT))
        pg.navigate(page_url(port))
        pg.wait_load(25)
        try:
            run(pg, port)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            T("X 测试执行异常（后续断言未执行）", False, "%s: %s" % (exc.__class__.__name__, exc))
    finally:
        ok_n = sum(1 for r in RESULTS if r["ok"])
        fails = len(RESULTS) - ok_n
        print("\n=========== draw_proof_check: %d PASS / %d FAIL（共 %d 断言）==========="
              % (ok_n, fails, len(RESULTS)))
        try:
            with open(REPORT, "w", encoding="utf-8") as fh:
                json.dump({"pass": ok_n, "fail": fails, "total": len(RESULTS),
                           "snapshot": {"path": PAGE_PATH, "sha256": SNAPSHOT_SHA[0],
                                        "bytes": os.path.getsize(SNAPSHOT) if os.path.isfile(SNAPSHOT) else 0},
                           "results": RESULTS, "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                          fh, ensure_ascii=False, indent=2)
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
        sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
