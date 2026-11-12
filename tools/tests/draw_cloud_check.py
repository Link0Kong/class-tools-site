# -*- coding: utf-8 -*-
"""抽签存证 · 云端 API 黑盒专项测试（真实 CloudBase PostgreSQL / PostgREST）

契约唯一真源：web/draw/CONTRACT.md §1（表 / 哈希规范 / RPC / params 归一 / 测试数据卫生）。
迁移：deploy/cloudbase/2026-11-12_draw_proof.sql（已应用；幂等）。

覆盖（契约 §5.1 全部点）：
  * 迁移结构：6 个 RPC 存在 + SECURITY DEFINER + search_path=public,private,pg_temp + anon 可执行；
    draw_records / draw_events RLS 开启、无策略、匿名无任何直连表权限；
  * 鉴权：无 token / 错误 token → {ok:false,reason:'身份已失效，请重新进入班级'}（HTTP 200）；
  * create 校验：id / seed / algo / params / pool / result / labels 全部非法输入的明确中文 reason，
    且非法请求一律不落库；
  * create 归一与哈希：params 未知键丢弃 + excl 去重升序、pool 去重升序、labels 按 n 升序去重（后值覆盖）、
    canon 逐字节格式（v1 行）与 Python hashlib.sha256 重算 == hash；today_count/today_mine、seq_day 递增；
  * 幂等：同 id 同 sid 重复 create 返回已存记录（不覆盖）；同 id 不同 sid → 记录编号冲突；
  * get：canon+hash 格式、hash 自检、events 时间线、is_mine/op_name/op_seat、**响应无 sid**；
  * list：today/all/YYYY-MM-DD/非法 scope、limit 1..100 夹取、摘要字段集（无 seed/pool/canon/events）、排序；
  * event append：kind 白名单、seq 递增、prev_hash 链（首条=record.hash）、note 120 字截断、
    event hash 用 Python 复算一致、非本人/不存在记录 → 记录不存在；
  * is_test 隔离：测试身份记录 is_test=true（3260799999 与 9999 段两条分支均验证），
    「真实口径（is_test=false）查询这些记录恒为 0」；get/list 服务端按 is_test 口径过滤（源码 + 行为双重断言）；
  * 直连表：GET rest/draw_records、rest/draw_events 带班级 token 仍 401/403；
  * 清理：draw_test_purge（本人/他人/不存在）+ draw_test_clear（级联删 events、可重复调用），
    finally 里 clear 并 SQL 复核云端无残留测试记录。

身份与纪律（AGENTS.md §0 第 7 条 / 契约 §0-5）：
  * **只用测试身份**：官方测试身份 `3260799999 / 测试账号`（private.class_ids.is_test=true，公开凭据）
    + 本脚本临时创建、finally 删除的 **9999 段 is_test QA 身份**（随机 sid + 空闲座号）；
    **绝不**登录任何真实同学/管理员账号、不读真实 token、不打印/落盘任何 token / publishable key / 学号；
  * CB（REST base）/ CBK（publishable key）只在运行时从 `tools/index.html` 解析进内存，**不打印**；
  * 测试记录全部 is_test=true，finally 里 `draw_test_clear` 清空；临时会话与 class_ids 行 finally 删除。

运行：
  cd web/tools
  python tests\\draw_cloud_check.py
退出码 0 = 全 PASS。
"""
import hashlib
import importlib.util
import json
import os
import re
import secrets
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))          # web/
INDEX = os.path.join(WEB, "tools", "index.html")
sys.path.insert(0, HERE)

# 政策（AGENTS §0-7 / 契约 §0-5）：只用测试身份。守卫在真实调用前调用。
from _test_account import TEST_NAME, TEST_SID, assert_test_identity, test_identity_token  # noqa: E402

CN = timezone(timedelta(hours=8))
TAG = str(int(time.time() * 1000))
RESULTS = []
INVALID_IDS = []       # 非法参数尝试的 id（断言一律不落库）
TEMP_IDS = []          # 临时 QA 测试身份创建的记录 id
OFFICIAL_IDS = []      # 官方测试身份创建的记录 id（finally 用 purge 精确清理）
CLEAN = {"temp_sid": "", "temp_token": "", "official_token": "", "seat": None}
SAMPLE = {"canon": ""}

# CB / CBK 仅运行时内存；绝不打印
CB = ""
KEY = ""


# ------------------------------------------------------------------ 基础工具
_spec = importlib.util.spec_from_file_location(
    "apply_sql", os.path.join(WEB, "deploy", "cloudbase", "apply_sql.py"))
_apply_sql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_apply_sql)

import subprocess  # noqa: E402


def sql_rows(stmt):
    """执行只读 SQL 返回行列表（不打印行内容，避免 sid/姓名进日志）。"""
    body = json.dumps({"EnvId": _apply_sql.ENV_ID, "Sql": stmt}, ensure_ascii=False)
    r = subprocess.run([_apply_sql.NODE, _apply_sql.TCB_BIN, "api", "tcb", "ExecutePGSql",
                        "--api-version", _apply_sql.API_VERSION, "--body", body, "--json"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    a, b = out.find("{"), out.rfind("}")
    if a < 0 or b <= a:
        raise RuntimeError("SQL 输出无法解析（tcb ExecutePGSql）")
    js = json.loads(out[a:b + 1])
    data = js.get("data") or {}
    cols = data.get("Columns") or []
    parsed = []
    for raw in (data.get("Rows") or []):
        try:
            arr = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(arr, list):
            parsed.append(dict(zip(cols, arr)))
    return parsed


def sql_run(stmt):
    """执行写 SQL（静默 stdout：语句里可能含临时 token，不打印）。"""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return _apply_sql.run_stmt(1, stmt, False)


def sql_count(stmt):
    rows = sql_rows(stmt)
    return int(rows[0]["n"]) if rows else -1


def truth(v):
    return str(v).strip().lower() in ("true", "t", "1")


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


def load_gateway():
    """从 tools/index.html 解析 CB / CBK 到内存（不打印、不落盘）。"""
    global CB, KEY
    try:
        html = open(INDEX, encoding="utf-8", errors="replace").read()
        cb = re.search(r'var CB="([^"]+)"', html)
        ck = re.search(r'var CBK="([^"]+)"', html)
        if not cb or not ck:
            return False
        CB = cb.group(1).rstrip("/") + "/"
        KEY = ck.group(1)
        return True
    except Exception:  # noqa: BLE001
        return False


def hdr(token=None):
    h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
         "Origin": "https://tool.furina.fun"}
    if token:
        h["X-Device-Id"] = token
    return h


def rpc(name, body=None, token=None, timeout=40):
    """调用 PostgREST RPC；返回 (http_status, json_dict, raw_text)。"""
    try:
        r = requests.post(CB + "rpc/" + name, headers=hdr(token),
                          json=body if body is not None else {}, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return 0, {"ok": False, "reason": "request-error:" + type(e).__name__}, ""
    raw = r.text or ""
    try:
        parsed = r.json()
    except Exception:  # noqa: BLE001
        parsed = {"ok": False, "reason": "non-json"}
    return r.status_code, parsed, raw


def rj(name, body=None, token=None):
    return rpc(name, body, token)[1]


def login_class(sid, name):
    st, r, _ = rpc("class_verify", {"p_sid": sid, "p_name": name})
    return (r or {}).get("token") or ""


def today_cn():
    return datetime.now(CN).strftime("%Y-%m-%d")


_rid_seq = 0


def new_rid():
    global _rid_seq
    _rid_seq += 1
    return "d" + format(int(time.time() * 1000), "x") + secrets.token_hex(2) + format(_rid_seq, "x")


def base_params(**kw):
    p = {"range": [1, 70], "count": 3, "dup": False, "excl": [], "sort": "draw", "rosterN": 0, "namesN": 0}
    p.update(kw)
    return p


def payload(rid=None, **kw):
    body = {
        "p_id": rid or new_rid(),
        "p_params": base_params(),
        "p_pool": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "p_result": [9, 10, 4],
        "p_labels": [],
        "p_seed": "0123456789abcdef",
        "p_algo": "draw-v1",
    }
    body.update(kw)
    return body


def create(**kw):
    body = payload(**kw)
    return rj("draw_record_create", body, CLEAN["temp_token"] or None), body


def ev_canon(rid, ev):
    """契约 §1.2 事件 canon（Python 复算用；与 SQL concat_ws 等价）。"""
    parts = [
        "e1", rid, str(ev.get("seq")), str(ev.get("kind") or ""),
        "" if ev.get("n") is None else str(ev.get("n")),
        "" if ev.get("added") is None else str(ev.get("added")),
        str(ev.get("note") or ""), str(ev.get("at")),
        str(ev.get("prev_hash") or ""),
    ]
    return "\n".join(parts)


def ev_hash(rid, ev):
    return hashlib.sha256(ev_canon(rid, ev).encode("utf-8")).hexdigest()


def canon_hash(canon):
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def is_reason(r, expected):
    return (r or {}).get("ok") is False and (r or {}).get("reason") == expected


def no_secret(raw, extra=()):
    """响应里不得出现 'sid' 键 / 10 位学号 / 本测试身份 sid 值。"""
    sids = [TEST_SID, CLEAN.get("temp_sid") or ""] + list(extra)
    return ('"sid"' not in (raw or "") and
            not re.search(r"\b\d{10}\b", raw or "") and
            all(s and s not in (raw or "") for s in sids))


# ------------------------------------------------------------------ §0 迁移结构 / 身份准备
def setup():
    # 0.1 网关配置（CB/CBK 仅内存，不打印）
    ok = load_gateway()
    T("0.1 tools/index.html 解析 CB/CBK 成功（仅内存，不打印密钥）", ok)
    T("0.2 CB 为 https REST 根、CBK 非空", CB.startswith("https://") and "/rdb/rest/" in CB and len(KEY) > 32)
    if not ok:
        return False
    # 0.3 官方测试身份守卫（真实调用前校验 sid）
    assert_test_identity(TEST_SID, TEST_NAME, where="draw_cloud_check 官方测试身份")
    T("0.3 官方测试身份通过 _test_account 守卫（3260799999 / 测试账号）", True)
    # 0.4 迁移结构：6 个 RPC
    fns = sql_rows(
        "select p.proname, p.prosecdef, "
        "array_to_string(coalesce(p.proconfig, '{}'), ',') as cfg, "
        "has_function_privilege('anon', p.oid, 'EXECUTE') as anon_exec "
        "from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname = 'public' and p.proname in "
        "('draw_record_create','draw_event_append','draw_record_get','draw_record_list',"
        "'draw_test_purge','draw_test_clear') order by p.proname")
    T("0.4 迁移已应用：6 个抽签存证 RPC 全部存在", len(fns) == 6,
      "n=%d" % len(fns))
    T("0.5 6 个 RPC 均为 SECURITY DEFINER", len(fns) == 6 and all(truth(f.get("prosecdef")) for f in fns))
    T("0.6 6 个 RPC search_path 固定为 public,private,pg_temp",
      len(fns) == 6 and all("public" in str(f.get("cfg")) and "private" in str(f.get("cfg")) for f in fns))
    T("0.7 6 个 RPC anon 均可执行（GRANT EXECUTE TO anon）",
      len(fns) == 6 and all(truth(f.get("anon_exec")) for f in fns))
    # 0.8 两表 RLS + 无策略 + anon 无直连权限
    tabs = sql_rows(
        "select c.relname, c.relrowsecurity, "
        "(select count(*) from pg_policies pp where pp.schemaname = 'public' and pp.tablename = c.relname) as npol, "
        "has_table_privilege('anon', 'public.'||c.relname, 'SELECT') as sel, "
        "has_table_privilege('anon', 'public.'||c.relname, 'INSERT') as ins, "
        "has_table_privilege('anon', 'public.'||c.relname, 'UPDATE') as upd, "
        "has_table_privilege('anon', 'public.'||c.relname, 'DELETE') as del "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relname in ('draw_records','draw_events') order by c.relname")
    T("0.8 迁移已建表：draw_records + draw_events", len(tabs) == 2,
      ",".join(str(t.get("relname")) for t in tabs))
    T("0.9 两表 RLS 已启用且无任何策略", len(tabs) == 2 and all(truth(t.get("relrowsecurity")) and int(t.get("npol")) == 0 for t in tabs))
    T("0.10 两表 anon 无 SELECT/INSERT/UPDATE/DELETE 直连权限",
      len(tabs) == 2 and all(not truth(t.get("sel")) and not truth(t.get("ins"))
                             and not truth(t.get("upd")) and not truth(t.get("del")) for t in tabs))
    cols = sql_rows(
        "select table_name, count(*) as n from information_schema.columns "
        "where table_schema = 'public' and table_name in ('draw_records','draw_events') "
        "group by table_name order by table_name")
    T("0.11 两表列结构与契约 §1.1 一致（15 + 10 列）",
      len(cols) == 2 and {r.get("table_name"): int(r.get("n")) for r in cols} ==
      {"draw_events": 10, "draw_records": 15}, cols)
    cons = sql_rows(
        "select conname from pg_constraint c join pg_class t on t.oid = c.conrelid "
        "join pg_namespace n on n.oid = t.relnamespace "
        "where n.nspname = 'public' and t.relname in ('draw_records','draw_events')")
    names = {r.get("conname") for r in cons}
    T("0.12 契约约束齐全（id/day/seed/algo/kind 四条命名 CHECK）",
      {"draw_records_id_chk", "draw_records_day_chk", "draw_records_seed_chk",
       "draw_records_algo_chk", "draw_events_kind_chk"} <= names)

    # 0.13 官方测试身份登录 → 校验返回 sid 仍是测试身份
    off_tok = ""
    try:
        off_tok = test_identity_token(CB, KEY)
    except SystemExit:
        off_tok = ""
    CLEAN["official_token"] = off_tok
    T("0.13 官方测试身份登录成功（class_verify 返回 64 位 token，不打印）",
      bool(off_tok) and len(off_tok) == 64, "token_len=%d" % len(off_tok))
    if not off_tok:
        return False
    who = rj("class_whoami", {}, off_tok)
    T("0.14 官方 token class_whoami sid 为测试身份（真实调用前二次校验）",
      (who or {}).get("ok") is True and (who or {}).get("sid") == TEST_SID
      and assert_test_identity((who or {}).get("sid"), where="draw_cloud_check whoami") is True)

    # 0.15 临时 9999 段 QA 测试身份（is_test=true；finally 删除）
    used_seats = {int(r["seat"]) for r in sql_rows("select seat from private.class_ids")}
    used_sids = {str(r["sid"]) for r in sql_rows("select sid from private.class_ids")}
    seat = next((s for s in range(990, 1001) if s not in used_seats), None)
    sid = ""
    for i in range(20):
        cand = "9999" + str((int(TAG) + i) % 1000000).zfill(6)
        if cand not in used_sids:
            sid = cand
            break
    T("0.15 选定临时 QA 测试身份（9999 段 is_test，座号空闲）", bool(sid) and seat is not None,
      "seat=%s" % seat)
    if not sid or seat is None:
        return False
    assert_test_identity(sid, where="draw_cloud_check 临时 QA 测试身份")
    ok_ins = sql_run(
        "insert into private.class_ids(seat,sid,name,role,badge,is_admin,is_test) values "
        "(%d,'%s','QA抽签测试','','',false,true)" % (seat, sid))
    T("0.16 临时 QA 测试身份写入 private.class_ids（is_test=true）", ok_ins)
    row = sql_rows("select is_test, seat, sid from private.class_ids where sid = '%s'" % sid)
    T("0.17 临时 QA 身份 DB 侧 is_test=true（真实名单/统计不显示）",
      bool(row) and truth(row[0].get("is_test")) and int(row[0].get("seat")) == seat)
    temp_tok = login_class(sid, "QA抽签测试")
    CLEAN["temp_sid"] = sid
    CLEAN["temp_token"] = temp_tok
    CLEAN["seat"] = seat
    T("0.18 临时 QA 测试身份登录成功（token 64 位，不打印）", len(temp_tok) == 64,
      "token_len=%d" % len(temp_tok))
    tw = rj("class_whoami", {}, temp_tok)
    T("0.19 临时 token class_whoami sid 为 9999 段测试身份（真实调用前二次校验）",
      (tw or {}).get("ok") is True and (tw or {}).get("sid") == sid
      and assert_test_identity((tw or {}).get("sid"), where="draw_cloud_check whoami") is True)
    return len(temp_tok) == 64


# ------------------------------------------------------------------ §1 鉴权
def test_auth():
    r = rj("draw_record_create", payload(), None)
    T("1.1 无 token 调用 draw_record_create → ok:false「身份已失效，请重新进入班级」",
      is_reason(r, "身份已失效，请重新进入班级"), r.get("reason"))
    r = rj("draw_record_list", {"p_scope": "today"}, "bad-token-" + TAG)
    T("1.2 错误 token 调用 draw_record_list → ok:false「身份已失效，请重新进入班级」",
      is_reason(r, "身份已失效，请重新进入班级"), r.get("reason"))
    r = rj("draw_record_get", {"p_id": "d000000000000000"}, None)
    T("1.3 无 token 调用 draw_record_get → ok:false 中文 reason", r.get("ok") is False and
      isinstance(r.get("reason"), str) and len(r.get("reason")) > 0, r.get("reason"))
    r = rj("draw_event_append", {"p_id": "d000000000000000", "p_kind": "remove"}, None)
    T("1.4 无 token 调用 draw_event_append → ok:false 中文 reason", r.get("ok") is False)
    r = rj("draw_test_clear", {}, None)
    T("1.5 无 token 调用 draw_test_clear → ok:false 中文 reason", r.get("ok") is False)


# ------------------------------------------------------------------ §2 create 校验（中文 reason，不落库）
def test_validation():
    cases = []

    def bad(label, expect, **kw):
        body = payload(**kw)
        INVALID_IDS.append(body["p_id"])
        r = rj("draw_record_create", body, CLEAN["temp_token"])
        cases.append((label, expect, r))

    bad("2.1 params 非对象被拒绝", "参数不合法", p_params=[])
    bad("2.2 range lo>hi 被拒绝", "参数不合法", p_params=base_params(range=[70, 1]))
    bad("2.3 range 元素非整数被拒绝", "参数不合法", p_params=base_params(range=["1", 2]))
    bad("2.4 count=0 被拒绝", "参数不合法", p_params=base_params(count=0))
    bad("2.5 count=1001 被拒绝", "参数不合法", p_params=base_params(count=1001))
    bad("2.6 dup 非布尔被拒绝", "参数不合法", p_params=base_params(dup="false"))
    bad("2.7 sort 非法值被拒绝", "参数不合法", p_params=base_params(sort="bogus"))
    bad("2.8 excl 超过 200 个被拒绝", "参数不合法", p_params=base_params(excl=list(range(201))))
    bad("2.9 excl 非整数被拒绝", "参数不合法", p_params=base_params(excl=["a"]))
    bad("2.10 rosterN=71 被拒绝", "参数不合法", p_params=base_params(rosterN=71))
    bad("2.11 namesN=-1 被拒绝", "参数不合法", p_params=base_params(namesN=-1))
    bad("2.12 空抽签池被拒绝", "抽签池不合法", p_pool=[])
    bad("2.13 抽签池超过 1000 个被拒绝", "抽签池不合法", p_pool=list(range(1, 1002)))
    bad("2.14 抽签池重复号码被拒绝", "抽签池不合法", p_pool=[1, 2, 2, 3])
    bad("2.15 抽签池元素 100000 越界被拒绝", "抽签池不合法", p_pool=[1, 100000])
    bad("2.16 抽签池元素为字符串被拒绝", "抽签池不合法", p_pool=["1", 2])
    bad("2.17 result 长度不等于 count 被拒绝", "结果不合法", p_result=[9, 10])
    bad("2.18 result 元素不在 pool 被拒绝", "结果不合法", p_result=[9, 10, 99])
    bad("2.19 dup=false 时 result 重复被拒绝", "结果不合法", p_result=[4, 4, 9])
    bad("2.20 dup=true 时 result 长度不等于 count 被拒绝", "结果不合法",
        p_params=base_params(dup=True, count=7), p_result=[1, 2, 3])
    bad("2.21 labels 非数组被拒绝", "名称映射不合法", p_labels={"n": 9})
    bad("2.22 labels 的 n 不在 result 被拒绝", "名称映射不合法", p_labels=[{"n": 1, "nm": "组一"}])
    bad("2.23 labels 的 nm 为空被拒绝", "名称映射不合法", p_labels=[{"n": 9, "nm": "   "}])
    bad("2.24 labels 的 nm 超过 40 字被拒绝", "名称映射不合法", p_labels=[{"n": 9, "nm": "名" * 41}])
    bad("2.25 labels 超过 300 项被拒绝", "名称映射不合法", p_labels=[{"n": 9, "nm": "组"}] * 301)
    bad("2.26 seed 长度不足 16 位被拒绝", "种子不合法", p_seed="0123456789abcde")
    bad("2.27 seed 含大写 hex 被拒绝", "种子不合法", p_seed="0123456789ABCDEF")
    bad("2.28 id 格式非法被拒绝", "记录编号不合法", p_id="x123")
    bad("2.29 id 为 null 被拒绝", "记录编号不合法", p_id=None)
    bad("2.30 algo 非 draw-v1 被拒绝", "算法不合法", p_algo="draw-v2")
    for label, expect, r in cases:
        T(label, is_reason(r, expect), (r or {}).get("reason"))
    # 非法请求全部不落库
    if INVALID_IDS:
        lst = ",".join("'%s'" % i for i in INVALID_IDS if i)
        n = sql_count("select count(*) as n from public.draw_records where id in (%s)" % lst) if lst else 0
    else:
        n = 0
    T("2.31 全部非法 create 请求均未落库（DB 计数为 0）", n == 0, "n=%s" % n)


# ------------------------------------------------------------------ §3 create 成功 / 归一 / 哈希
def test_create_success():
    rid1 = new_rid()
    params = base_params(range=[1, 70], count=3, dup=False, excl=[5, 3, 3], sort="num",
                         rosterN=12, namesN=3)
    params["hack"] = "drop table"          # 未知键必须丢弃
    body = payload(rid=rid1, p_params=params, p_pool=[10, 1, 7, 3, 5],
                   p_result=[7, 10, 1],
                   p_labels=[{"n": 7, "nm": " 第一组 "}, {"n": 1, "nm": "第三组", "x": 9},
                             {"n": 7, "nm": "甲组"}],
                   p_seed="a1b2c3d4e5f60718")
    st, r, raw = rpc("draw_record_create", body, CLEAN["temp_token"])
    TEMP_IDS.append(rid1)
    T("3.1 create 成功（HTTP 200 + ok:true）", st == 200 and r.get("ok") is True, r.get("reason"))
    rec = r.get("record") or {}
    T("3.2 顶层返回 today_count / today_mine 整数",
      isinstance(r.get("today_count"), int) and isinstance(r.get("today_mine"), int), r.get("today_count"))
    T("3.3 顶层 today_count/today_mine 与 record 内一致",
      r.get("today_count") == rec.get("today_count") and r.get("today_mine") == rec.get("today_mine"))
    T("3.4 record.id 与请求 id 一致", rec.get("id") == rid1)
    T("3.5 record.seed / algo 回显正确",
      rec.get("seed") == "a1b2c3d4e5f60718" and rec.get("algo") == "draw-v1")
    T("3.6 result 保留抽取顺序 [7,10,1]", rec.get("result") == [7, 10, 1], rec.get("result"))
    T("3.7 pool 服务端去重升序归一为 [1,3,5,7,10]", rec.get("pool") == [1, 3, 5, 7, 10], rec.get("pool"))
    p = rec.get("params") or {}
    T("3.8 params 未知键丢弃（恰好 7 个白名单键）",
      set(p.keys()) == {"range", "count", "dup", "excl", "sort", "rosterN", "namesN"},
      sorted(p.keys()))
    T("3.9 params excl 去重升序归一为 [3,5]", p.get("excl") == [3, 5], p.get("excl"))
    T("3.10 params 各字段归一正确（range/count/dup/sort/rosterN/namesN）",
      p.get("range") == [1, 70] and p.get("count") == 3 and p.get("dup") is False
      and p.get("sort") == "num" and p.get("rosterN") == 12 and p.get("namesN") == 3)
    labels = rec.get("labels") or []
    T("3.11 labels 按 n 升序去重（后值覆盖）且未知键丢弃",
      labels == [{"n": 1, "nm": "第三组"}, {"n": 7, "nm": "甲组"}], labels)
    T("3.12 record.at 为毫秒时间戳且接近当前时间",
      isinstance(rec.get("at"), int) and abs(rec["at"] / 1000.0 - time.time()) < 300)
    T("3.13 record.day 为 Asia/Shanghai 本地今天", rec.get("day") == today_cn(),
      "%s vs %s" % (rec.get("day"), today_cn()))
    T("3.14 seq_day 为 ≥1 的整数", isinstance(rec.get("seq_day"), int) and rec["seq_day"] >= 1)
    T("3.15 hash 为 64 位小写 hex", isinstance(rec.get("hash"), str)
      and re.fullmatch(r"[0-9a-f]{64}", rec["hash"]) is not None)
    canon = rec.get("canon") or ""
    SAMPLE["canon"] = canon
    T("3.16 canon 为字符串且行数 = 12（v1 规范）", isinstance(canon, str) and len(canon.split("\n")) == 12,
      "lines=%d" % len(canon.split("\n")))
    T("3.17 canon 用 Python hashlib.sha256 重算 == 返回 hash",
      canon_hash(canon) == rec.get("hash"), canon_hash(canon)[:16])
    cl = canon.split("\n")
    T("3.18 canon 逐行字段正确（v1/id/created_ms/day/seq_day/algo/seed/prev_hash）",
      len(cl) == 12 and cl[0] == "v1" and cl[1] == rid1 and cl[2] == str(rec.get("at"))
      and cl[3] == rec.get("day") and cl[4] == str(rec.get("seq_day"))
      and cl[5] == "draw-v1" and cl[6] == "a1b2c3d4e5f60718" and cl[7] == (rec.get("prev_hash") or ""))
    T("3.19 canon 的 params/pool/result/labels 段与返回 JSON 逐一致",
      json.loads(cl[8]) == rec.get("params") and json.loads(cl[9]) == rec.get("pool")
      and json.loads(cl[10]) == rec.get("result") and json.loads(cl[11]) == rec.get("labels"))
    T("3.20 event_count=0 且 events=[]（新记录）",
      rec.get("event_count") == 0 and rec.get("events") == [])
    T("3.21 is_mine=true，op_name/op_seat 来自 class_ids",
      rec.get("is_mine") is True and rec.get("op_name") == "QA抽签测试"
      and rec.get("op_seat") == CLEAN["seat"])
    T("3.22 create 响应不含 sid（键 + 10 位学号 + 本测试身份值）", no_secret(raw))
    # DB 侧核对（is_test 口径 + 哈希落库）
    row = sql_rows("select is_test, sid, created_ms, seq_day, hash, seed, params::text as p "
                   "from public.draw_records where id = '%s'" % rid1)
    T("3.23 DB 落库：is_test=true 且 sid 为临时测试身份",
      bool(row) and truth(row[0].get("is_test")) and row[0].get("sid") == CLEAN["temp_sid"])
    T("3.24 DB 落库 hash/created_ms/seq_day 与 RPC 返回一致",
      bool(row) and row[0].get("hash") == rec.get("hash")
      and int(row[0].get("created_ms")) == rec.get("at")
      and int(row[0].get("seq_day")) == rec.get("seq_day"))
    T("3.25 DB 落库 params 为服务端归一的 7 键对象（不含未知键 hack）",
      bool(row) and set(json.loads(row[0].get("p") or "{}").keys()) ==
      {"range", "count", "dup", "excl", "sort", "rosterN", "namesN"}
      and "hack" not in (row[0].get("p") or ""))
    # 幂等：同 id 同 sid 重复 create（参数全换）→ 返回原记录、不覆盖
    body2 = payload(rid=rid1, p_pool=[2, 4, 6], p_result=[6, 2, 4],
                    p_seed="ffffffffffffffff", p_params=base_params(count=3))
    r2 = rj("draw_record_create", body2, CLEAN["temp_token"])
    T("3.26 同 id 同 sid 重复 create 幂等：ok:true 且返回原记录",
      r2.get("ok") is True and (r2.get("record") or {}).get("hash") == rec.get("hash"))
    T("3.27 幂等重试不覆盖已存证内容（hash/seed/result 不变、今日次数不增）",
      (r2.get("record") or {}).get("seed") == "a1b2c3d4e5f60718"
      and (r2.get("record") or {}).get("result") == [7, 10, 1]
      and (r2.get("record") or {}).get("today_mine") == rec.get("today_mine"))
    T("3.27b 幂等分支仍带顶层 today_count/today_mine（契约 §1.3-1）",
      isinstance(r2.get("today_count"), int) and isinstance(r2.get("today_mine"), int)
      and r2.get("today_mine") == rec.get("today_mine"))
    # 不同 sid 同 id → 冲突（官方测试身份尝试占用临时身份的 id）
    r3 = rj("draw_record_create", payload(rid=rid1), CLEAN["official_token"])
    T("3.28 同 id 不同 sid → {ok:false,reason:'记录编号冲突'}",
      is_reason(r3, "记录编号冲突"), r3.get("reason"))
    return rid1, rec


# ------------------------------------------------------------------ §4 seq_day / today 次数 / 链
def test_seq_and_chain(rid1, rec1):
    rid2 = new_rid()
    r2 = rj("draw_record_create", payload(rid=rid2, p_result=[1, 2, 3]), CLEAN["temp_token"])
    TEMP_IDS.append(rid2)
    rec2 = r2.get("record") or {}
    T("4.1 第二条 create 成功", r2.get("ok") is True)
    T("4.2 seq_day 严格递增（第二条 > 第一条）",
      isinstance(rec2.get("seq_day"), int) and rec2["seq_day"] > rec1.get("seq_day"),
      "%s > %s" % (rec2.get("seq_day"), rec1.get("seq_day")))
    T("4.3 每次 create 返回 seq_day == today_count（同一事务取号，并发安全）",
      rec2.get("seq_day") == r2.get("today_count"),
      "%s vs %s" % (rec2.get("seq_day"), r2.get("today_count")))
    T("4.4 today_mine 精确 +1（临时身份唯一，无并发干扰）",
      r2.get("today_mine") == rec1.get("today_mine") + 1,
      "%s -> %s" % (rec1.get("today_mine"), r2.get("today_mine")))
    rid3 = new_rid()
    r3 = rj("draw_record_create", payload(rid=rid3, p_result=[10, 9, 8]), CLEAN["temp_token"])
    TEMP_IDS.append(rid3)
    rec3 = r3.get("record") or {}
    T("4.5 第三条 create 成功且 seq_day == today_count",
      r3.get("ok") is True and rec3.get("seq_day") == r3.get("today_count"))
    T("4.6 连续三次 seq_day 严格递增 / today_mine 递增",
      rec1.get("seq_day") < rec2.get("seq_day") < rec3.get("seq_day")
      and r3.get("today_mine") == r2.get("today_mine") + 1)
    # prev_hash 链：DB 口径确定性核对（(at,id) 前一条，同 is_test 口径）
    chain = sql_rows(
        "select r.prev_hash, "
        "coalesce((select p.hash from public.draw_records p "
        "          where p.is_test = r.is_test and (p.at, p.id) < (r.at, r.id) "
        "          order by p.at desc, p.id desc limit 1), '') as expected "
        "from public.draw_records r where r.id = '%s'" % rid2)
    T("4.7 第二条 prev_hash 等于同 is_test 口径 (at,id) 前一条 hash（链正确）",
      bool(chain) and chain[0].get("prev_hash") == chain[0].get("expected"),
      (chain[0].get("prev_hash") or "")[:12] if chain else "?")
    # prev_hash 必须指向同口径真实已存证记录（不伪造；有并发测试记录时也成立）
    prev = (chain[0].get("prev_hash") or "") if chain else ""
    n_prev = sql_count("select count(*) as n from public.draw_records "
                       "where is_test = true and hash = '%s'" % prev) if prev else 0
    T("4.8 第二条 prev_hash 指向同口径已存证记录的真实 hash（链上非伪造）", n_prev == 1,
      "matched=%s" % n_prev)
    # dup=true 记录（允许重复号码；长度 = count）
    rid4 = new_rid()
    r4 = rj("draw_record_create", payload(
        rid=rid4, p_params=base_params(count=7, dup=True), p_pool=[1, 2, 3, 4, 5],
        p_result=[1, 3, 1, 2, 2, 2, 3], p_seed="deadbeefcafebabe"), CLEAN["temp_token"])
    TEMP_IDS.append(rid4)
    rec4 = r4.get("record") or {}
    T("4.9 dup=true create 成功且 params.dup=true",
      r4.get("ok") is True and (rec4.get("params") or {}).get("dup") is True)
    T("4.10 dup=true result 保留重复且长度=count（7 个）",
      rec4.get("result") == [1, 3, 1, 2, 2, 2, 3], rec4.get("result"))
    T("4.11 dup=true 记录 canon 哈希自检一致",
      canon_hash(rec4.get("canon") or "") == rec4.get("hash"))
    T("4.12 四条记录 today_mine 精确 == 4（临时身份独立口径）",
      r4.get("today_mine") == 4, r4.get("today_mine"))
    return rid2, rec2, rid3, rec3, rid4, rec4


# ------------------------------------------------------------------ §5 get（canon/hash/events/无 sid）
def test_get(rid1, rec1, rid2):
    st, r, raw = rpc("draw_record_get", {"p_id": rid1}, CLEAN["temp_token"])
    rec = r.get("record") or {}
    T("5.1 get 成功（HTTP 200 + ok:true）", st == 200 and r.get("ok") is True)
    T("5.2 get 返回与 create 时逐字节一致的 canon/hash",
      rec.get("canon") == rec1.get("canon") and rec.get("hash") == rec1.get("hash"))
    T("5.3 get canon 用 Python hashlib.sha256 重算 == hash",
      canon_hash(rec.get("canon") or "") == rec.get("hash"))
    T("5.4 get record 含公开视图全部字段（id/at/day/seq_day/params/pool/result/labels/seed/"
      "algo/hash/canon/prev_hash/event_count/events/is_mine/op_name/op_seat/today_*）",
      {"id", "at", "day", "seq_day", "today_count", "today_mine", "is_mine", "op_name", "op_seat",
       "params", "pool", "result", "labels", "seed", "algo", "hash", "canon", "prev_hash",
       "event_count", "events"} <= set(rec.keys()))
    T("5.5 get 不含 sid 字段（键 + 10 位学号 + 本测试身份值）", no_secret(raw))
    T("5.6 get is_mine=true / op_name / op_seat 正确",
      rec.get("is_mine") is True and rec.get("op_name") == "QA抽签测试"
      and rec.get("op_seat") == CLEAN["seat"])
    T("5.7 get today_mine == 4 / today_count 为整数（同一身份当天次数）",
      rec.get("today_mine") == 4 and isinstance(rec.get("today_count"), int)
      and rec["today_count"] >= 4)
    r_nf = rj("draw_record_get", {"p_id": new_rid()}, CLEAN["temp_token"])
    T("5.8 get 不存在的合法 id → {ok:false,reason:'记录不存在'}",
      is_reason(r_nf, "记录不存在"), r_nf.get("reason"))
    r_bad = rj("draw_record_get", {"p_id": "not-a-record"}, CLEAN["temp_token"])
    T("5.9 get 非法格式 id → 记录不存在（不泄露 SQL 细节）",
      is_reason(r_bad, "记录不存在"))
    # 同一测试口径的另一测试身份可见（is_test 口径共享、按 sid 区分 is_mine）
    r_cross = rj("draw_record_get", {"p_id": rid1}, CLEAN["official_token"])
    T("5.10 同 is_test 口径的另一测试身份可见（get ok:true 且 is_mine=false）",
      r_cross.get("ok") is True and (r_cross.get("record") or {}).get("is_mine") is False)
    # prev_hash 与 DB 一致
    row = sql_rows("select hash, prev_hash from public.draw_records where id = '%s'" % rid2)
    g2 = rj("draw_record_get", {"p_id": rid2}, CLEAN["temp_token"])
    T("5.11 get prev_hash 与 DB 落库值一致",
      bool(row) and (g2.get("record") or {}).get("prev_hash") == row[0].get("prev_hash"))


# ------------------------------------------------------------------ §6 list（scope / limit / 摘要字段 / 无 sid）
def test_list(rid1, rid2, rid3, rid4):
    today = today_cn()
    st, r, raw = rpc("draw_record_list", {"p_scope": "today", "p_limit": 100}, CLEAN["temp_token"])
    recs = r.get("records") or []
    ids = [x.get("id") for x in recs]
    T("6.1 list today 成功（ok:true, scope='today', day=本地今天）",
      st == 200 and r.get("ok") is True and r.get("scope") == "today" and r.get("day") == today)
    T("6.2 list today 含本测试创建的全部 4 条记录",
      all(x in ids for x in (rid1, rid2, rid3, rid4)), "n=%d" % len(recs))
    seqs = [x.get("seq_day") for x in recs]
    T("6.3 list today 按 seq_day 倒序", seqs == sorted(seqs, reverse=True), seqs)
    T("6.4 list 返回 today_count / today_mine 整数且 today_mine=4",
      isinstance(r.get("today_count"), int) and r.get("today_mine") == 4)
    summ = next((x for x in recs if x.get("id") == rid1), {})
    expect_keys = {"id", "at", "day", "seq_day", "params", "result", "labels", "hash",
                   "event_count", "is_mine", "op_name", "op_seat"}
    T("6.5 list 摘要字段集与契约 §1.3-4 完全一致（12 键）", set(summ.keys()) == expect_keys,
      sorted(summ.keys()))
    T("6.6 list 摘要不含 seed/pool/canon/events",
      not ({"seed", "pool", "canon", "events"} & set(summ.keys())))
    T("6.7 list 摘要 is_mine/op_name/op_seat 正确",
      summ.get("is_mine") is True and summ.get("op_name") == "QA抽签测试"
      and summ.get("op_seat") == CLEAN["seat"])
    T("6.8 list 响应不含 sid（键 + 10 位学号 + 本测试身份值）", no_secret(raw))
    r_lim2 = rj("draw_record_list", {"p_scope": "today", "p_limit": 2}, CLEAN["temp_token"])
    lim2 = r_lim2.get("records") or []
    T("6.9 list limit=2 生效（返回 2 条、seq_day 倒序）",
      len(lim2) == 2 and [x.get("seq_day") for x in lim2] ==
      sorted([x.get("seq_day") for x in lim2], reverse=True))
    r_lim0 = rj("draw_record_list", {"p_scope": "today", "p_limit": 0}, CLEAN["temp_token"])
    T("6.10 list limit=0 夹取为 1", len(r_lim0.get("records") or []) == 1)
    r_limbig = rj("draw_record_list", {"p_scope": "today", "p_limit": 1000}, CLEAN["temp_token"])
    ids_big = [x.get("id") for x in (r_limbig.get("records") or [])]
    T("6.11 list limit=1000 夹取为 100（不报错且仍含本测试 4 条记录）",
      len(ids_big) <= 100 and all(x in ids_big for x in (rid1, rid2, rid3, rid4)),
      "n=%d" % len(ids_big))
    r_all = rj("draw_record_list", {"p_scope": "all", "p_limit": 100}, CLEAN["temp_token"])
    ids_all = [x.get("id") for x in (r_all.get("records") or [])]
    T("6.12 list all 成功（scope='all'）且包含本测试 4 条记录",
      r_all.get("ok") is True and r_all.get("scope") == "all"
      and all(x in ids_all for x in (rid1, rid2, rid3, rid4)))
    r_date = rj("draw_record_list", {"p_scope": today, "p_limit": 100}, CLEAN["temp_token"])
    ids_date = [x.get("id") for x in (r_date.get("records") or [])]
    T("6.13 list 指定日期（今天）成功且包含本测试记录",
      r_date.get("ok") is True and r_date.get("scope") == today
      and all(x in ids_date for x in (rid1, rid2, rid3, rid4)))
    r_bad = rj("draw_record_list", {"p_scope": "garbage-scope"}, CLEAN["temp_token"])
    T("6.14 list 非法 scope 归一为 today", r_bad.get("ok") is True and r_bad.get("scope") == "today")
    r_future = rj("draw_record_list", {"p_scope": "2099-01-01", "p_limit": 100}, CLEAN["temp_token"])
    T("6.15 list 无记录日期返回空数组（scope 保持日期）",
      r_future.get("ok") is True and r_future.get("scope") == "2099-01-01"
      and r_future.get("records") == [])
    r_default = rj("draw_record_list", {}, CLEAN["temp_token"])
    T("6.16 list 默认参数（无 body 字段）按 today 返回",
      r_default.get("ok") is True and r_default.get("scope") == "today")


# ------------------------------------------------------------------ §7 event append（seq / 链 / 截断 / 权限）
def test_events(rid1, rec1, rid2, rec2, rid3):
    e1 = rj("draw_event_append", {"p_id": rid1, "p_kind": "remove", "p_n": 7,
                                  "p_added": 55, "p_note": "剔除重抽"}, CLEAN["temp_token"])
    ev1 = e1.get("event") or {}
    T("7.1 追加 remove 事件成功（seq=1、event_count=1）",
      e1.get("ok") is True and ev1.get("seq") == 1 and e1.get("event_count") == 1)
    T("7.2 首条事件 prev_hash == record.hash（事件链接在存证根上）",
      ev1.get("prev_hash") == rec1.get("hash"))
    T("7.3 事件字段完整且 n/added/note/at 正确",
      ev1.get("kind") == "remove" and ev1.get("n") == 7 and ev1.get("added") == 55
      and ev1.get("note") == "剔除重抽" and isinstance(ev1.get("at"), int))
    T("7.4 事件 hash 为 64 位 hex 且 Python 按 e1 canon 复算一致",
      re.fullmatch(r"[0-9a-f]{64}", str(ev1.get("hash"))) is not None
      and ev_hash(rid1, ev1) == ev1.get("hash"))
    e2 = rj("draw_event_append", {"p_id": rid1, "p_kind": "refill", "p_added": 88,
                                  "p_note": ""}, CLEAN["temp_token"])
    ev2 = e2.get("event") or {}
    T("7.5 追加 refill 事件成功（seq=2、prev_hash=上一条事件 hash）",
      e2.get("ok") is True and ev2.get("seq") == 2 and ev2.get("prev_hash") == ev1.get("hash"))
    T("7.6 事件 n 为空时返回 null 且 hash 复算一致（n 段为空串）",
      ev2.get("n") is None and ev_hash(rid1, ev2) == ev2.get("hash"))
    long_note = "备" * 150
    e3 = rj("draw_event_append", {"p_id": rid1, "p_kind": "reset", "p_note": long_note},
            CLEAN["temp_token"])
    ev3 = e3.get("event") or {}
    T("7.7 note 超过 120 字被截断为 120 字",
      e3.get("ok") is True and len(ev3.get("note") or "") == 120
      and ev3.get("note") == long_note[:120], "len=%d" % len(ev3.get("note") or ""))
    T("7.8 截断后的 note 参与 hash 且 Python 复算一致",
      ev_hash(rid1, ev3) == ev3.get("hash"))
    e_bad = rj("draw_event_append", {"p_id": rid1, "p_kind": "hack"}, CLEAN["temp_token"])
    T("7.9 非法 kind 被拒绝（{ok:false,reason:'事件类型不合法'}）",
      is_reason(e_bad, "事件类型不合法"), e_bad.get("reason"))
    e_other = rj("draw_event_append", {"p_id": rid1, "p_kind": "remove"}, CLEAN["official_token"])
    T("7.10 非本人（另一测试身份）追加事件 → 记录不存在", is_reason(e_other, "记录不存在"))
    e_nf = rj("draw_event_append", {"p_id": new_rid(), "p_kind": "remove"}, CLEAN["temp_token"])
    T("7.11 不存在的记录追加事件 → 记录不存在", is_reason(e_nf, "记录不存在"))
    g = rj("draw_record_get", {"p_id": rid1}, CLEAN["temp_token"])
    grec = g.get("record") or {}
    evs = grec.get("events") or []
    T("7.12 get 返回 event_count=3 且事件按 seq 升序 [1,2,3]",
      grec.get("event_count") == 3 and [x.get("seq") for x in evs] == [1, 2, 3])
    T("7.13 事件链完整（e2.prev=e1.hash, e3.prev=e2.hash, 首条=record.hash）",
      len(evs) == 3 and evs[0].get("prev_hash") == rec1.get("hash")
      and evs[1].get("prev_hash") == evs[0].get("hash")
      and evs[2].get("prev_hash") == evs[1].get("hash"))
    T("7.14 全部事件 hash 用 Python 复算均一致",
      all(ev_hash(rid1, x) == x.get("hash") for x in evs))
    ev_rows = sql_rows("select seq, prev_hash, hash from public.draw_events "
                       "where record_id = '%s' order by seq" % rid1)
    T("7.15 DB draw_events 与 RPC 返回的 seq/prev_hash/hash 完全一致",
      [int(x["seq"]) for x in ev_rows] == [1, 2, 3]
      and [x["hash"] for x in ev_rows] == [x.get("hash") for x in evs]
      and [x["prev_hash"] for x in ev_rows] == [x.get("prev_hash") for x in evs])
    # 其它记录 event_count 仍为 0（事件不串记录）
    r2 = rj("draw_record_get", {"p_id": rid2}, CLEAN["temp_token"])
    r3 = rj("draw_record_get", {"p_id": rid3}, CLEAN["temp_token"])
    T("7.16 事件不串记录（其它记录 event_count 仍为 0）",
      (r2.get("record") or {}).get("event_count") == 0
      and (r3.get("record") or {}).get("event_count") == 0)
    lst = rj("draw_record_list", {"p_scope": "today", "p_limit": 100}, CLEAN["temp_token"])
    row1 = [x for x in (lst.get("records") or []) if x.get("id") == rid1]
    T("7.17 list 摘要 event_count 同步为 3",
      bool(row1) and row1[0].get("event_count") == 3)


# ------------------------------------------------------------------ §8 is_test 口径隔离
def test_isolation(rid1, rid2, rid3, rid4):
    ids = (rid1, rid2, rid3, rid4)
    lst = ",".join("'%s'" % i for i in ids)
    rows = sql_rows("select is_test, sid from public.draw_records where id in (%s)" % lst)
    T("8.1 测试身份创建的全部记录 DB 侧 is_test=true（%d 条）" % len(rows),
      len(rows) == 4 and all(truth(r.get("is_test")) for r in rows))
    T("8.2 记录 sid 均为临时测试身份（is_test 判定与 sid 一致）",
      len(rows) == 4 and all(r.get("sid") == CLEAN["temp_sid"] for r in rows))
    n_real = sql_count("select count(*) as n from public.draw_records "
                       "where id in (%s) and is_test = false" % lst)
    T("8.3 真实口径（is_test=false）查询这些记录恒为 0 → 真实用户不可见/不计入真实次数",
      n_real == 0, "real_rows=%s" % n_real)
    # 服务端过滤口径在 SQL 源码中固定（不依赖客户端参数字段）
    defs = sql_rows("select proname, pg_get_functiondef(p.oid) as def from pg_proc p "
                    "join pg_namespace n on n.oid = p.pronamespace "
                    "where n.nspname = 'public' and p.proname in ('draw_record_get','draw_record_list')")
    by = {r["proname"]: r.get("def") or "" for r in defs}
    T("8.4 draw_record_get / draw_record_list 源码均按 is_test 口径过滤（服务端固定）",
      len(defs) == 2 and "is_test = v_is_test" in by.get("draw_record_get", "")
      and "is_test = v_is_test" in by.get("draw_record_list", ""))
    # 行为：同 is_test 口径可见、跨 sid 仍可见（证明按口径而非 sid 隔离；真实口径由 8.3 证明为 0）
    cross = rj("draw_record_get", {"p_id": rid2}, CLEAN["official_token"])
    T("8.5 is_test 可见性 = 同口径（另一测试身份可读、is_mine=false）而非本人",
      cross.get("ok") is True and (cross.get("record") or {}).get("is_mine") is False)
    n_test = sql_count("select count(*) as n from public.draw_records where id in (%s) and is_test = true" % lst)
    T("8.6 测试口径（is_test=true）查询这些记录恒为 4（与 8.3 互补）", n_test == 4, n_test)


# ------------------------------------------------------------------ §9 purge / clear（权限 / 级联）
def test_purge(rid1, rid2):
    # 同一测试口径但不同 sid：不能删他人记录
    r = rj("draw_test_purge", {"p_id": rid1}, CLEAN["official_token"])
    T("9.1 另一测试身份 purge 非本人记录 → deleted=0（不删除他人记录）",
      r.get("ok") is True and r.get("deleted") == 0, r.get("deleted"))
    g = rj("draw_record_get", {"p_id": rid1}, CLEAN["temp_token"])
    T("9.2 他人 purge 后记录仍存在", g.get("ok") is True)
    r_nf = rj("draw_test_purge", {"p_id": new_rid()}, CLEAN["temp_token"])
    T("9.3 purge 不存在的 id → {ok:true,deleted:0}", r_nf.get("ok") is True and r_nf.get("deleted") == 0)
    # 级联：先建临时记录 + 事件，再 purge → 记录与事件均硬删
    rid_tmp = new_rid()
    c = rj("draw_record_create", payload(rid=rid_tmp), CLEAN["temp_token"])
    TEMP_IDS.append(rid_tmp)
    e = rj("draw_event_append", {"p_id": rid_tmp, "p_kind": "remove", "p_n": 2}, CLEAN["temp_token"])
    T("9.4 清理用临时记录创建成功（create+event）", c.get("ok") is True and e.get("ok") is True)
    r = rj("draw_test_purge", {"p_id": rid_tmp}, CLEAN["temp_token"])
    T("9.5 本人 purge 测试记录 → {ok:true,deleted:1}", r.get("ok") is True and r.get("deleted") == 1)
    T("9.6 purge 后记录硬删（get → 记录不存在）",
      is_reason(rj("draw_record_get", {"p_id": rid_tmp}, CLEAN["temp_token"]), "记录不存在"))
    n_rec = sql_count("select count(*) as n from public.draw_records where id = '%s'" % rid_tmp)
    n_ev = sql_count("select count(*) as n from public.draw_events where record_id = '%s'" % rid_tmp)
    T("9.7 purge 级联删除 draw_events（记录 0 行、事件 0 行）", n_rec == 0 and n_ev == 0,
      "rec=%s,ev=%s" % (n_rec, n_ev))
    # today 次数随 purge 回落（此前临时身份共 5 条，purge 1 条 → 4 条）
    lst = rj("draw_record_list", {"p_scope": "today", "p_limit": 100}, CLEAN["temp_token"])
    T("9.8 purge 一条后 today_mine 回落为 4", lst.get("today_mine") == 4, lst.get("today_mine"))


# ------------------------------------------------------------------ §10 官方测试身份分支（3260799999）+ 跨身份冲突
def test_official_identity(rid2):
    rid_off = new_rid()
    body = payload(rid=rid_off, p_result=[2, 4, 6])
    r = rj("draw_record_create", body, CLEAN["official_token"])
    OFFICIAL_IDS.append(rid_off)
    rec = r.get("record") or {}
    T("10.1 官方测试身份 3260799999 可创建存证（is_test 分支①）",
      r.get("ok") is True and rec.get("id") == rid_off, r.get("reason"))
    T("10.2 官方测试身份记录 op_name 由服务端从 class_ids 取（测试账号）",
      rec.get("op_name") == TEST_NAME and isinstance(rec.get("op_seat"), int),
      rec.get("op_name"))
    row = sql_rows("select is_test, sid from public.draw_records where id = '%s'" % rid_off)
    T("10.3 官方测试身份记录 DB 侧 is_test=true（3260799999 分支被识别）",
      bool(row) and truth(row[0].get("is_test")) and row[0].get("sid") == TEST_SID)
    g = rj("draw_record_get", {"p_id": rid_off}, CLEAN["official_token"])
    T("10.4 官方测试身份 get 成功且 canon hash 自检一致",
      g.get("ok") is True
      and canon_hash((g.get("record") or {}).get("canon") or "") == (g.get("record") or {}).get("hash"))
    # 跨 sid 冲突：官方测试身份不能占用临时身份的 id
    conflict = rj("draw_record_create", payload(rid=rid2), CLEAN["official_token"])
    T("10.5 官方测试身份复用临时身份记录 id → 记录编号冲突",
      is_reason(conflict, "记录编号冲突"), conflict.get("reason"))
    # purge 本人记录（官方身份清理自己的测试数据）
    rp = rj("draw_test_purge", {"p_id": rid_off}, CLEAN["official_token"])
    T("10.6 官方测试身份 purge 本人记录 → deleted=1", rp.get("ok") is True and rp.get("deleted") == 1)
    T("10.7 purge 后官方身份记录不可见（记录不存在）",
      is_reason(rj("draw_record_get", {"p_id": rid_off}, CLEAN["official_token"]), "记录不存在"))
    sg = rj("draw_record_get", {"p_id": rid_off}, CLEAN["temp_token"])
    T("10.8 官方身份记录被 purged 后同口径其它身份也不可见", is_reason(sg, "记录不存在"))


# ------------------------------------------------------------------ §11 直连表（401/403）
def table_status(tbl):
    last = None
    for _ in range(3):
        try:
            rr = requests.get(CB + tbl + "?select=*", headers=hdr(CLEAN["temp_token"]), timeout=20)
            last = rr.status_code
        except Exception:  # noqa: BLE001
            last = 0
        if last in (401, 403):
            return last
        time.sleep(1.5)
    return last


def test_direct_table():
    st1 = table_status("draw_records")
    T("11.1 直连 GET rest/draw_records（带班级 token）→ 401/403 无权限",
      st1 in (401, 403), "status=%s" % st1)
    st2 = table_status("draw_events")
    T("11.2 直连 GET rest/draw_events（带班级 token）→ 401/403 无权限",
      st2 in (401, 403), "status=%s" % st2)
    try:
        rr = requests.post(CB + "draw_records", headers=hdr(CLEAN["temp_token"]),
                           json={"id": new_rid(), "sid": CLEAN["temp_sid"]}, timeout=20)
        st3 = rr.status_code
    except Exception:  # noqa: BLE001
        st3 = 0
    T("11.3 直连 POST rest/draw_records（伪造写入）被拒绝（401/403）",
      st3 in (401, 403), "status=%s" % st3)


# ------------------------------------------------------------------ §12 clear 全量清理 + 残留复核
def test_clear(rid1, rid2, rid3, rid4):
    before = sql_count("select count(*) as n from public.draw_records "
                       "where sid = '%s'" % CLEAN["temp_sid"])
    T("12.1 clear 前临时身份记录数 == 4（全部测试记录）", before == 4, "n=%s" % before)
    r = rj("draw_test_clear", {}, CLEAN["temp_token"])
    T("12.2 draw_test_clear → {ok:true,deleted:4}", r.get("ok") is True and r.get("deleted") == 4,
      r.get("deleted"))
    after = sql_count("select count(*) as n from public.draw_records "
                      "where sid = '%s'" % CLEAN["temp_sid"])
    T("12.3 clear 后临时身份记录 0 行", after == 0, "n=%s" % after)
    T("12.4 clear 后 get 主记录 → 记录不存在",
      is_reason(rj("draw_record_get", {"p_id": rid1}, CLEAN["temp_token"]), "记录不存在"))
    lst = rj("draw_record_list", {"p_scope": "all", "p_limit": 100}, CLEAN["temp_token"])
    ids = [x.get("id") for x in (lst.get("records") or [])]
    T("12.5 clear 后 list all 不再返回本测试任何记录",
      not any(x in ids for x in (rid1, rid2, rid3, rid4)))
    T("12.6 clear 后 today_mine == 0", lst.get("today_mine") == 0, lst.get("today_mine"))
    r2 = rj("draw_test_clear", {}, CLEAN["temp_token"])
    T("12.7 clear 可重复调用（第二次 deleted=0）", r2.get("ok") is True and r2.get("deleted") == 0)
    n_ev = sql_count("select count(*) as n from public.draw_events e "
                     "join public.draw_records r on r.id = e.record_id "
                     "where r.sid = '%s'" % CLEAN["temp_sid"])
    T("12.8 clear 级联删除事件（残留事件 0 行）", n_ev == 0, "n=%s" % n_ev)


# ------------------------------------------------------------------ 收尾：finally 清理 + 复核
def cleanup_and_verify():
    extra = []
    # 1) 剩余测试记录：临时身份 clear，官方身份逐条 purge（只清本脚本创建的 id）
    try:
        if CLEAN.get("temp_token"):
            r = rj("draw_test_clear", {}, CLEAN["temp_token"])
            extra.append(("13.1 finally：draw_test_clear 清理临时身份测试记录（deleted=%s）"
                          % (r or {}).get("deleted"), (r or {}).get("ok") is True))
    except Exception as e:  # noqa: BLE001
        extra.append(("13.1 finally：draw_test_clear", False, type(e).__name__))
    try:
        if CLEAN.get("official_token"):
            for rid in OFFICIAL_IDS:
                rj("draw_test_purge", {"p_id": rid}, CLEAN["official_token"])
            extra.append(("13.2 finally：官方测试身份按 id 精确 purge 本脚本记录", True))
    except Exception as e:  # noqa: BLE001
        extra.append(("13.2 finally：官方身份 purge", False, type(e).__name__))
    # 2) SQL 复核：本脚本创建的 id 全部不存在
    try:
        all_ids = TEMP_IDS + OFFICIAL_IDS
        left = 0
        if all_ids:
            lst = ",".join("'%s'" % i for i in all_ids)
            left = sql_count("select count(*) as n from public.draw_records where id in (%s)" % lst)
        extra.append(("13.3 finally：云端无残留测试记录（本脚本 %d 个 id 复核为 0 行）" % len(all_ids),
                      left == 0, "left=%s" % left))
    except Exception as e:  # noqa: BLE001
        extra.append(("13.3 finally：残留记录复核", False, type(e).__name__))
    # 3) 删除临时 QA 身份 + 会话（不打印 token）
    try:
        toks = [CLEAN.get("temp_token") or "", CLEAN.get("official_token") or ""]
        toks = [t for t in toks if t]
        if toks:
            lst = ",".join("'%s'" % t for t in toks)
            ok_del = sql_run("delete from private.class_sessions where token in (%s)" % lst)
            left = 0
            try:
                left = sql_count("select count(*) as n from private.class_sessions where token in (%s)" % lst)
            except Exception:  # noqa: BLE001
                left = -1
            extra.append(("13.4 finally：一次性测试会话已删除（left=%s）" % left, ok_del and left == 0))
    except Exception as e:  # noqa: BLE001
        extra.append(("13.4 finally：测试会话删除", False, type(e).__name__))
    try:
        sid = CLEAN.get("temp_sid") or ""
        if sid:
            ok_del = sql_run("delete from private.class_ids where sid = '%s'" % sid)
            left = sql_count("select count(*) as n from private.class_ids where sid = '%s'" % sid)
            extra.append(("13.5 finally：临时 QA 测试身份已从 private.class_ids 删除（left=%s）" % left,
                          ok_del and left == 0))
    except Exception as e:  # noqa: BLE001
        extra.append(("13.5 finally：临时 QA 身份删除", False, type(e).__name__))
    try:
        sid = CLEAN.get("temp_sid") or ""
        if sid:
            n = sql_count("select count(*) as n from public.draw_records where sid = '%s'" % sid)
            extra.append(("13.6 finally：临时身份在云端 0 条抽签记录（n=%s）" % n, n == 0))
    except Exception as e:  # noqa: BLE001
        extra.append(("13.6 finally：临时身份记录复核", False, type(e).__name__))
    for item in extra:
        T(*item)


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()
    if not setup():
        RESULTS.append({"name": "X.0 前置失败（配置/登录/迁移不可用）", "ok": False})
        return
    test_auth()
    test_validation()
    rid1, rec1 = test_create_success()
    rid2, rec2, rid3, rec3, rid4, rec4 = test_seq_and_chain(rid1, rec1)
    test_get(rid1, rec1, rid2)
    test_list(rid1, rid2, rid3, rid4)
    test_events(rid1, rec1, rid2, rec2, rid3)
    test_isolation(rid1, rid2, rid3, rid4)
    test_purge(rid1, rid2)
    test_official_identity(rid2)
    test_direct_table()
    test_clear(rid1, rid2, rid3, rid4)
    print("\n[info] 耗时 %.1fs；记录 id 均以 d 开头、临时身份为 9999 段测试身份（不打印 token/sid）"
          % (time.time() - t0))
    if SAMPLE.get("canon"):
        print("[info] canon 示例（供实现比对；不含任何个人信息/学号）：")
        print("  " + SAMPLE["canon"].replace("\n", "\\n"))


if __name__ == "__main__":
    exc = False
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        exc = True
        traceback.print_exc()
        RESULTS.append({"name": "X.0 主流程未预期异常", "ok": False,
                        "note": traceback.format_exc()[-400:]})
    finally:
        try:
            cleanup_and_verify()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            RESULTS.append({"name": "X.0 finally 清理异常", "ok": False})
        fails = [x for x in RESULTS if not x["ok"]]
        print("\n=========== draw_cloud_check: %d PASS / %d FAIL ==========="
              % (len(RESULTS) - len(fails), len(fails)))
        for f in fails:
            print("  FAIL: " + f["name"] + ((" | " + f["note"]) if f["note"] else ""))
        sys.exit(1 if (fails or exc) else 0)
