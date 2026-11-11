# -*- coding: utf-8 -*-
"""班级工具站 · 大屏临时互联服务鉴权 + 团员名单 RPC 云端黑盒校验（真实 CloudBase PostgREST）

被测（迁移：`deploy/cloudbase/2026-11-11_stage_rpc.sql`，已应用、幂等）：
  1) public.class_whoami() → jsonb（无参数，POST body `{}`）
       {ok:true,sid,seat,name}                    -- 当前 token 自身身份
       {ok:false,reason:"未登录"}                  -- 无 token / token 失效 / 过期
       {ok:false,reason:"身份无效"}                -- token 有效但 private.class_ids 查不到该 sid
       * 必须接受测试身份（is_test=true）；只返回本人；不返回 token。
  2) public.class_league() → jsonb
       {ok:true,count:N,seats:[{seat,name}...]}    -- seat 升序；排除 is_test；**不含 sid**
       {ok:false,reason:"未登录"}                  -- 未登录

覆盖：无 token、错误 token、过期 token、测试身份（含同账号双 token）、普通成员合成会话、
class_league 数量/字段/排序/与 DB 一致、无 sid 泄漏、ECS 服务端 X-Device-Id 调用、
CORS 预检头、只读/清理。

身份与纪律：
  * 测试身份 = `private.class_ids.is_test=true` 行（3260799999 / 测试账号，交付说明/CLOUDBASE.md 公开）；
  * 普通成员 = `private.class_sessions` 一次性合成 token（脚本 finally 删除），
    **不读取、不使用任何真实同学的 token**；
  * 不打印、不落盘任何 token / sid / 真实姓名；
  * 只读 + 两个 RPC；唯一写入是「一次性测试会话行」，finally 全部删除。

运行：
  cd web/tools
  python tests\\stage_rpc_check.py --probe    # 只读探测（列结构/函数签名/权限）
  python tests\\stage_rpc_check.py            # 云端黑盒（默认）
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import time

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))          # web/
REST = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
KEY = open(os.path.join(WEB, "deploy", "cloudbase", "publish_key.txt"), encoding="utf-8").read().strip()
TEST_SID, TEST_NAME = "3260799999", "测试账号"    # 测试身份（is_test=true，公开凭据）
TAG = str(int(time.time() * 1000))

RESULTS = []
SESSION_TOKENS = []          # 本脚本创建的一次性会话 token（只存内存，finally 删除，不打印）
DB = {
    "counts_before": {},     # class_ids / is_test / class_league 行数
    "test_row": None,        # 测试身份 DB 行（内存）
    "plain": None,           # 普通成员 DB 行（内存）
    "league": [],            # 团员名单预期（seat+name，内存）
    "all_sids": set(),       # 全部班级 sid（仅用于响应泄漏扫描，不打印）
}


# ------------------------------------------------------------------ 基础工具
_spec = importlib.util.spec_from_file_location(
    "apply_sql", os.path.join(WEB, "deploy", "cloudbase", "apply_sql.py"))
_apply_sql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_apply_sql)


def sql_rows(stmt):
    """执行只读 SQL 并返回行列表（不打印行内容，避免 sid/姓名进日志）。"""
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


def sql_quiet(stmt):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return _apply_sql.run_stmt(1, stmt, False)


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


def truth(v):
    return str(v).strip().lower() in ("true", "t", "1")


def hdr(token=None, style="device", origin="https://tool.furina.fun"):
    h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
    if origin:
        h["Origin"] = origin
    if token:
        h["X-Class-Token" if style == "class" else "X-Device-Id"] = token
    return h


def rpc(name, body=None, token=None, style="device", origin="https://tool.furina.fun", timeout=40):
    try:
        r = requests.post(REST + "rpc/" + name, headers=hdr(token, style, origin),
                          json=body if body is not None else {}, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return {"status": 0, "json": {"ok": False, "reason": "request-error:" + type(e).__name__}, "raw": ""}
    raw = r.text or ""
    try:
        parsed = r.json()
    except Exception:  # noqa: BLE001
        parsed = {"ok": False, "reason": "non-json"}
    return {"status": r.status_code, "json": parsed, "raw": raw}


def is_unauth(resp):
    body = resp.get("json") or {}
    return resp.get("status") == 200 and body.get("ok") is False and body.get("reason") == "未登录"


# ------------------------------------------------------------------ DB 只读核对
def load_db():
    fn = sql_rows("select count(*) as n from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
                  "where n.nspname = 'public' and p.proname in ('class_whoami', 'class_league')")
    nfun = int(fn[0]["n"]) if fn else 0
    fns = sql_rows(
        "select p.proname, p.prosecdef, "
        "array_to_string(coalesce(p.proconfig, '{}'), ',') as cfg, "
        "has_function_privilege('anon', p.oid, 'EXECUTE') as anon_exec "
        "from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname = 'public' and p.proname in ('class_whoami', 'class_league') "
        "order by p.proname")
    rows = []
    for r in fns:
        rows.append({"name": r.get("proname"), "secdef": truth(r.get("prosecdef")),
                     "anon_exec": truth(r.get("anon_exec")), "cfg": str(r.get("cfg") or "")})

    trows = sql_rows("select c.seat, c.name, c.sid, coalesce(c.is_test,false) as is_test "
                     "from private.class_ids c where c.sid = '%s'" % TEST_SID.replace("'", "''"))
    test_row = None
    if trows:
        test_row = {"seat": int(trows[0]["seat"]), "name": str(trows[0]["name"] or ""),
                    "sid": str(trows[0]["sid"] or ""), "is_test": truth(trows[0]["is_test"])}

    prows = sql_rows(
        "select c.seat, c.name, c.sid from private.class_ids c "
        "where not coalesce(c.is_test,false) and not coalesce(c.is_admin,false) "
        "and coalesce(nullif(btrim(c.role),''),'') = '' "
        "and coalesce(c.badge,'') not like '%班委%' "
        "and not exists (select 1 from private.class_league l where l.sid = c.sid) "
        "order by c.seat limit 1")
    plain = None
    if prows:
        plain = {"seat": int(prows[0]["seat"]), "name": str(prows[0]["name"] or ""),
                 "sid": str(prows[0]["sid"] or "")}

    league = []
    for r in sql_rows("select c.seat, c.name from private.class_league l "
                      "join private.class_ids c on c.sid = l.sid "
                      "where not coalesce(c.is_test,false) order by c.seat"):
        league.append({"seat": int(r["seat"]), "name": str(r["name"] or "")})

    all_sids = set()
    for r in sql_rows("select sid from private.class_ids"):
        s = str(r.get("sid") or "")
        if s:
            all_sids.add(s)

    cnt = sql_rows("select (select count(*) from private.class_ids) as c_ids, "
                   "(select count(*) from private.class_ids where coalesce(is_test,false)) as c_test, "
                   "(select count(*) from private.class_league) as c_league")
    counts = {}
    if cnt:
        counts = {"class_ids": int(cnt[0]["c_ids"]), "is_test": int(cnt[0]["c_test"]),
                  "class_league": int(cnt[0]["c_league"])}

    DB.update({"counts_before": counts, "test_row": test_row, "plain": plain,
               "league": league, "all_sids": all_sids})
    return {"nfun": nfun, "fns": rows, "counts": counts,
            "test_row": test_row, "plain": plain, "league": league}


# ------------------------------------------------------------------ 一次性测试会话
def setup_sessions(plain, fake_sid):
    """在 private.class_sessions 写入 3 行一次性会话：普通成员 / 假身份 / 已过期。"""
    tok_plain = "qatok_stage%s_plain" % TAG
    tok_exp = "qatok_stage%s_expired" % TAG
    tok_fake = "qatok_stage%s_fake" % TAG
    SESSION_TOKENS.extend([tok_plain, tok_exp, tok_fake])
    ok_plain = sql_quiet(
        "insert into private.class_sessions(token, sid, name, expires_at) "
        "select '%s', c.sid, c.name, now() + interval '2 hours' from private.class_ids c "
        "where c.sid = '%s' on conflict (token) do nothing"
        % (tok_plain, plain["sid"].replace("'", "''")))
    ok_exp = sql_quiet(
        "insert into private.class_sessions(token, sid, name, expires_at) "
        "select '%s', c.sid, c.name, now() - interval '1 hour' from private.class_ids c "
        "where c.sid = '%s' on conflict (token) do nothing"
        % (tok_exp, plain["sid"].replace("'", "''")))
    ok_fake = sql_quiet(
        "insert into private.class_sessions(token, sid, name, expires_at) "
        "values ('%s', '%s', '阶段RPC测试', now() + interval '2 hours') "
        "on conflict (token) do nothing" % (tok_fake, fake_sid.replace("'", "''")))
    rows = sql_rows("select count(*) as n from private.class_sessions where token in "
                    "('%s','%s','%s')" % (tok_plain, tok_exp, tok_fake))
    got = int(rows[0]["n"]) if rows else -1
    return ok_plain and ok_exp and ok_fake and got == 3, {"plain": tok_plain, "expired": tok_exp, "fake": tok_fake}


def pick_fake_sid():
    base = "9999" + str(int(TAG) % 1000000).zfill(6)
    for i in range(20):
        cand = str(int(base) + i).zfill(10)
        if cand not in DB["all_sids"]:
            rows = sql_rows("select count(*) as n from private.class_ids where sid = '%s'" % cand)
            if int(rows[0]["n"] or 0) == 0:
                return cand
    raise RuntimeError("无法构造 unused sid")


# ------------------------------------------------------------------ 主流程
def probe():
    """只读探测：列结构 / 函数签名与权限 / 行数（不打印 sid/姓名/token）。"""
    print("== private.class_ids / private.class_league 真实列 ==")
    for r in sql_rows("select table_name, column_name, data_type, is_nullable from information_schema.columns "
                      "where table_schema = 'private' and table_name in ('class_ids','class_league') "
                      "order by table_name, ordinal_position"):
        print("  %(table_name)s.%(column_name)s %(data_type)s nullable=%(is_nullable)s" % r)
    print("== public.class_whoami() / public.class_league() 签名与权限 ==")
    for r in sql_rows(
            "select p.proname, pg_get_function_identity_arguments(p.oid) as args, "
            "pg_get_function_result(p.oid) as ret, p.prosecdef, "
            "array_to_string(coalesce(p.proconfig, '{}'), ',') as cfg, "
            "has_function_privilege('anon', p.oid, 'EXECUTE') as anon_exec "
            "from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            "where n.nspname = 'public' and p.proname in ('class_whoami','class_league') order by p.proname"):
        print("  %(proname)s(%(args)s) → %(ret)s secdef=%(prosecdef)s anon_exec=%(anon_exec)s cfg=%(cfg)s" % r)
    print("== 行数（不含 sid/姓名） ==")
    for r in sql_rows("select (select count(*) from private.class_ids) as c_ids, "
                      "(select count(*) from private.class_ids where coalesce(is_test,false)) as c_test, "
                      "(select count(*) from private.class_league) as c_league"):
        print("  class_ids=%(c_ids)s (is_test=%(c_test)s) class_league=%(c_league)s" % r)


def main():
    info = load_db()
    league = info["league"]
    test_row, plain = info["test_row"], info["plain"]

    # ---------- 0. 前置 ----------
    T("0.1 迁移已应用：public.class_whoami() / public.class_league() 均存在（%d/2）" % info["nfun"],
      info["nfun"] == 2)
    T("0.2 两函数均为 SECURITY DEFINER 且 anon 有 EXECUTE 权限",
      len(info["fns"]) == 2 and all(f["secdef"] and f["anon_exec"] for f in info["fns"]),
      ",".join("%s secdef=%s anon=%s" % (f["name"], f["secdef"], f["anon_exec"]) for f in info["fns"]))
    T("0.3 两函数 search_path 固定为 public,private（SECURITY DEFINER 必需）",
      len(info["fns"]) == 2 and all("public" in f["cfg"] and "private" in f["cfg"] for f in info["fns"]))
    T("0.4 测试身份行存在且 is_test=true（private.class_ids）",
      bool(test_row) and test_row["is_test"],
      "seat=%s is_test=%s" % ((test_row or {}).get("seat"), (test_row or {}).get("is_test")))
    T("0.5 普通成员候选存在（非管理员/非班委/非团员/非测试）",
      bool(plain), "seat=%s" % ((plain or {}).get("seat")))
    T("0.6 团员名单预期非空（DB 直读 %d 人，已排除 is_test）" % len(league), len(league) > 0)
    if info["nfun"] != 2 or not test_row or not plain or not league:
        return

    fake_sid = pick_fake_sid()
    sess_ok, toks = setup_sessions(plain, fake_sid)
    T("0.7 一次性合成会话创建成功（普通成员/假身份/已过期，finally 删除）", sess_ok)

    # ---------- 1. 无 token ----------
    r = rpc("class_whoami", {})
    body = r["json"]
    T("1.1 class_whoami 无 token → HTTP 200 + {ok:false,reason:'未登录'}，顶层键恰为 {ok,reason}",
      is_unauth(r) and sorted(body.keys()) == ["ok", "reason"],
      "status=%s keys=%s" % (r["status"], sorted(body.keys())))
    r = rpc("class_league", {})
    T("1.2 class_league 无 token → HTTP 200 + {ok:false,reason:'未登录'}",
      is_unauth(r), "status=%s" % r["status"])
    try:
        ra = requests.post(REST + "rpc/class_whoami", json={}, timeout=30)
        st_noauth = ra.status_code
    except Exception as e:  # noqa: BLE001
        st_noauth = type(e).__name__
    T("1.3 缺少 Authorization: Bearer <publish_key> → 网关拒绝（401/403）",
      st_noauth in (401, 403), "status=%s" % st_noauth)

    # ---------- 2. 错误 / 过期 token ----------
    bad = "stage-rpc-check-bad-token-" + TAG
    T("2.1 class_whoami 随机错误 token → ok:false「未登录」", is_unauth(rpc("class_whoami", {}, bad)))
    T("2.2 class_league 随机错误 token → ok:false「未登录」", is_unauth(rpc("class_league", {}, bad)))
    T("2.3 class_whoami 过期会话 token → ok:false「未登录」",
      is_unauth(rpc("class_whoami", {}, toks["expired"])))
    T("2.4 class_league 过期会话 token → ok:false「未登录」",
      is_unauth(rpc("class_league", {}, toks["expired"])))

    # ---------- 3. 测试身份（is_test） ----------
    st1, login1 = None, {}
    try:
        ra = requests.post(REST + "rpc/class_verify", headers=hdr(None),
                           json={"p_sid": TEST_SID, "p_name": TEST_NAME}, timeout=40)
        st1, login1 = ra.status_code, ra.json()
    except Exception as e:  # noqa: BLE001
        login1 = {"ok": False, "reason": "request-error:" + type(e).__name__}
    tok1 = str((login1 or {}).get("token") or "")
    if tok1:
        SESSION_TOKENS.append(tok1)
    T("3.1 class_verify 测试身份登录成功（token 64 位，不打印）",
      (login1 or {}).get("ok") is True and len(tok1) == 64, "status=%s token_len=%d" % (st1, len(tok1)))

    tok2 = ""
    try:
        rb = requests.post(REST + "rpc/class_verify", headers=hdr(None),
                           json={"p_sid": TEST_SID, "p_name": TEST_NAME}, timeout=40)
        login2 = rb.json()
        tok2 = str((login2 or {}).get("token") or "")
        if tok2:
            SESSION_TOKENS.append(tok2)
    except Exception:  # noqa: BLE001
        login2 = {}
    T("3.2 同测试身份二次登录：token 不同、sid 相同（供 ECS 双 token 会话互见）",
      bool(tok1) and bool(tok2) and tok1 != tok2
      and (login1 or {}).get("sid") == (login2 or {}).get("sid"))

    w1 = rpc("class_whoami", {}, tok1)
    w2 = rpc("class_whoami", {}, tok2)
    T("3.3 两个 token 的 class_whoami 均 ok:true 且 sid/seat/name 完全一致",
      (w1["json"] or {}).get("ok") is True and (w2["json"] or {}).get("ok") is True
      and w1["json"] == w2["json"])
    T("3.4 class_whoami 顶层键恰好 {ok,sid,seat,name}（无 role/badge/is_admin/token）",
      sorted((w1["json"] or {}).keys()) == ["name", "ok", "seat", "sid"],
      "keys=%s" % sorted((w1["json"] or {}).keys()))
    T("3.5 class_whoami 的 seat/name 与 private.class_ids 一致（测试身份 is_test 被接受）",
      (w1["json"] or {}).get("seat") == test_row["seat"]
      and (w1["json"] or {}).get("name") == test_row["name"],
      "seat=%s" % (w1["json"] or {}).get("seat"))
    T("3.6 class_whoami 的 sid 为本测试身份 sid（字符串，仅本人）",
      isinstance((w1["json"] or {}).get("sid"), str) and (w1["json"] or {}).get("sid") == TEST_SID)
    lg_test = rpc("class_league", {}, tok1)
    T("3.7 class_league 测试身份 token 可调用（ok:true、count>0）",
      (lg_test["json"] or {}).get("ok") is True and int((lg_test["json"] or {}).get("count") or 0) > 0,
      "count=%s" % (lg_test["json"] or {}).get("count"))

    # ---------- 4. class_league 契约 ----------
    lj = lg_test["json"] or {}
    seats = lj.get("seats") or []
    T("4.1 class_league 顶层键恰好 {ok,count,seats}",
      sorted(lj.keys()) == ["count", "ok", "seats"], "keys=%s" % sorted(lj.keys()))
    T("4.2 count == seats 长度 == DB 预期人数（%d）" % len(league),
      isinstance(lj.get("count"), int) and lj.get("count") == len(seats) == len(league),
      "count=%s len=%d db=%d" % (lj.get("count"), len(seats), len(league)))
    T("4.3 seats 每项恰好 {seat,name} 两键（无 sid）",
      bool(seats) and all(sorted(x.keys()) == ["name", "seat"] for x in seats))
    T("4.4 seat 为 JSON 整数、name 为非空字符串",
      bool(seats) and all(isinstance(x.get("seat"), int) and isinstance(x.get("name"), str)
                          and x["name"].strip() != "" for x in seats))
    got_seats = [x.get("seat") for x in seats]
    T("4.5 seats 按 seat 严格升序",
      got_seats == sorted(got_seats) and len(set(got_seats)) == len(got_seats))
    expect_pairs = [(x["seat"], x["name"]) for x in league]
    got_pairs = [(x.get("seat"), x.get("name")) for x in seats]
    T("4.6 与 DB 直读团员名单逐项一致（seat+name、排除 is_test）", got_pairs == expect_pairs)
    raw_league = lg_test["raw"]
    T("4.7 class_league 原始响应无 'sid' 键", '"sid"' not in raw_league)
    T("4.8 class_league 原始响应无 10 位学号数字", not re.search(r"\b\d{10}\b", raw_league))
    leaked = [s for s in DB["all_sids"] if s and s in raw_league]
    T("4.9 class_league 原始响应不含任何班级真实 sid 值（%d 个 sid 内存比对）" % len(DB["all_sids"]),
      not leaked, "leaks=%d" % len(leaked))
    lg_again = rpc("class_league", {}, tok1)
    T("4.10 重复调用结果完全一致（确定性）", lg_again["json"] == lj)

    # ---------- 5. 普通成员（一次性合成会话，不使用真实同学 token） ----------
    w_n = rpc("class_whoami", {}, toks["plain"])
    wj = w_n["json"] or {}
    T("5.1 普通成员 class_whoami ok:true 且 sid/seat/name 与 DB 一致（只返回自己）",
      wj.get("ok") is True and wj.get("sid") == plain["sid"]
      and wj.get("seat") == plain["seat"] and wj.get("name") == plain["name"],
      "seat=%s" % wj.get("seat"))
    T("5.2 普通成员 class_whoami 顶层键恰好 4 个（无 role/badge/is_admin/token）",
      sorted(wj.keys()) == ["name", "ok", "seat", "sid"])
    others = [s for s in DB["all_sids"] if s and s != plain["sid"] and s in w_n["raw"]]
    T("5.3 普通成员 class_whoami 原始响应不含任何他人 sid 值", not others, "leaks=%d" % len(others))
    lg_n = rpc("class_league", {}, toks["plain"])
    T("5.4 普通成员 class_league 可调用且与测试身份结果完全一致（人数/座号/姓名）",
      lg_n["json"] == lj)
    raw_n = lg_n["raw"]
    T("5.5 普通成员 class_league 无 sid 泄漏（无 'sid' 键 / 无任何班级 sid 值 / 无 10 位学号）",
      '"sid"' not in raw_n and not re.search(r"\b\d{10}\b", raw_n)
      and not [s for s in DB["all_sids"] if s and s in raw_n])

    # ---------- 6. 身份无效（token 有效但班级名单查不到） ----------
    w_f = rpc("class_whoami", {}, toks["fake"])
    T("6.1 token 有效但不在 private.class_ids → class_whoami ok:false「身份无效」",
      w_f["status"] == 200 and (w_f["json"] or {}).get("ok") is False
      and (w_f["json"] or {}).get("reason") == "身份无效",
      "reason=%s" % (w_f["json"] or {}).get("reason"))
    lg_f = rpc("class_league", {}, toks["fake"])
    T("6.2 同 token class_league 仍可读（有效会话；名单本身不含 sid）",
      (lg_f["json"] or {}).get("ok") is True and (lg_f["json"] or {}).get("count") == len(league)
      and '"sid"' not in lg_f["raw"])

    # ---------- 7. ECS 服务端调用方式（X-Device-Id 头） ----------
    w_ecs = rpc("class_whoami", {}, tok1, origin=None)
    T("7.1 无 Origin + X-Device-Id + Bearer publish_key → ok:true（ECS 服务端 curl 风格）",
      (w_ecs["json"] or {}).get("ok") is True, "status=%s" % w_ecs["status"])
    try:
        ro = requests.options(
            REST + "rpc/class_whoami",
            headers={"Origin": "https://tool.furina.fun",
                     "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "authorization,content-type,x-device-id"},
            timeout=30)
        allow = (ro.headers.get("access-control-allow-headers") or "").lower()
        cors_ok = ro.status_code in (200, 204) and "x-device-id" in allow
    except Exception:  # noqa: BLE001
        cors_ok = False
    T("7.2 CORS 预检允许 X-Device-Id（OPTIONS 2xx、allow-headers 含 x-device-id）", cors_ok)
    w_cls = rpc("class_whoami", {}, tok1, style="class")
    T("7.3 X-Class-Token 头同样被接受（小程序头兼容）→ ok:true",
      (w_cls["json"] or {}).get("ok") is True)

    # ---------- 8. 清理 / 只读约束（由 cleanup_and_verify 在 finally 统一执行并断言） ----------

    # 示例响应（脱敏：sid/token 一律不打印）
    print("\n示例响应（已脱敏）：")
    print('  class_whoami → {"ok":true,"sid":"<redacted>","seat":%s,"name":"<redacted>"}' % test_row["seat"])
    sample = seats[0] if seats else {}
    print('  class_league → {"ok":true,"count":%d,"seats":[{"seat":%s,"name":"<redacted>"}, …]}'
          % (len(league), sample.get("seat")))


def cleanup_and_verify():
    extra = []
    toks = [t for t in SESSION_TOKENS if t]
    # 1) 一次性会话全部删除
    try:
        if toks:
            lst = ",".join("'%s'" % t.replace("'", "''") for t in toks)
            ok = sql_quiet("delete from private.class_sessions where token in (%s)" % lst)
            rows = sql_rows("select count(*) as n from private.class_sessions where token in (%s)" % lst)
            left = int(rows[0]["n"]) if rows else -1
            extra.append(("8.1 清理：一次性 class_sessions 全部删除（n=%d，left=%d）" % (len(toks), left),
                          ok and left == 0))
        else:
            extra.append(("8.1 清理：无需删除的测试会话（n=0）", True))
    except Exception as e:  # noqa: BLE001
        extra.append(("8.1 清理：一次性 class_sessions 删除", False, type(e).__name__))
    # 2) 清理后 token 立即失效
    try:
        probe_tok = toks[0] if toks else "qatok_stage_none"
        r = rpc("class_whoami", {}, probe_tok)
        extra.append(("8.2 清理后 token 立即失效（whoami → ok:false「未登录」）", is_unauth(r),
                      str((r.get("json") or {}).get("reason"))))
    except Exception as e:  # noqa: BLE001
        extra.append(("8.2 清理后 token 立即失效", False, type(e).__name__))
    # 3) 只读校验：class_ids / class_league 行数不变
    try:
        cnt = sql_rows("select (select count(*) from private.class_ids) as c_ids, "
                       "(select count(*) from private.class_ids where coalesce(is_test,false)) as c_test, "
                       "(select count(*) from private.class_league) as c_league")
        now = {"class_ids": int(cnt[0]["c_ids"]), "is_test": int(cnt[0]["c_test"]),
               "class_league": int(cnt[0]["c_league"])}
        extra.append(("8.3 只读：class_ids / is_test / class_league 行数调用前后不变",
                      now == DB.get("counts_before"), "before=%s after=%s" % (DB.get("counts_before"), now)))
    except Exception as e:  # noqa: BLE001
        extra.append(("8.3 只读：行数校验", False, type(e).__name__))
    for item in extra:
        T(*item)


def main_safe():
    exc = False
    try:
        main()
    except Exception:  # noqa: BLE001
        import traceback
        exc = True
        traceback.print_exc()
        RESULTS.append({"name": "X.0 主流程未抛未捕获异常", "ok": False,
                        "note": traceback.format_exc()[-400:]})
    finally:
        cleanup_and_verify()
        fails = [x for x in RESULTS if not x["ok"]]
        print("\n=========== stage_rpc_check: %d PASS / %d FAIL ==========="
              % (len(RESULTS) - len(fails), len(fails)))
        for f in fails:
            print("  FAIL: " + f["name"] + ((" | " + f["note"]) if f["note"] else ""))
        return 1 if (fails or exc) else 0


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
        sys.exit(0)
    sys.exit(main_safe())
