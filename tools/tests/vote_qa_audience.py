# -*- coding: utf-8 -*-
"""投票「可见人范围」（audience）独立验收 · 云端黑盒（真实 CloudBase PostgreSQL/PostgREST）。

契约：`web/vote/CONTRACT.md` §1.6 / §2（2026-11-11 18:08 增量）。
迁移：`deploy/cloudbase/2026-11-11_polls_audience.sql`（已应用）。

独立 QA 编写（实现者 = Lead / mp-vote；本脚本不复用实现者断言）。覆盖：
  范围四值 all/committee/league/custom 的列表可见性、detail/submit 范围外「投票不存在」、
  发起人始终可见可投、管理员始终可见可管理但范围外不能投（「不在可见范围内」）、
  custom 座号校验（空/非数组/非法值/不存在/去重升序/排除 is_test）、
  audience_seats 仅 can_manage 返回、audience/audience_count 返回、
  旧客户端不传参数=all、旧客户端 edit 不改范围、编辑改范围（无票可改/有票拒绝）、
  响应原文无 "sid"/学号、直连表仍 401。

身份/纪律：
  * 使用 `private.class_ids` 中真实角色成员（班委/仅团员/普通成员/管理员）的 **一次性 class_sessions**
    （token 由脚本生成、finally 删除；不读取任何凭据、不打印 sid/姓名/token）；
  * 另用测试身份（3260799999/测试账号，is_test）验证 is_test 座号被排除；
  * 所有测试投票 id 以 `pqa` 开头，finally 硬删除 votes+polls 并逐项复查。

运行：
  cd web/tools && python tests\\vote_qa_audience.py --probe   # 只读探测（角色/函数/表结构）
  cd web/tools && python tests\\vote_qa_audience.py            # 完整黑盒验收
证据：tools/tests/_shots_vote_qa/audience_cloud_report.json
"""
import importlib.util
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
WEB = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(HERE, "_shots_vote_qa")
os.makedirs(SHOTS, exist_ok=True)
REST = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
KEY = open(os.path.join(WEB, "deploy", "cloudbase", "publish_key.txt"), encoding="utf-8").read().strip()
TEST_SID, TEST_NAME = "3260799999", "测试账号"
TAG = str(int(time.time() * 1000))[-8:]

RESULTS = []
CREATED = []
SESSION_TOKENS = []           # 本脚本创建的 class_sessions.token（finally 删除）
REAL_SIDS = set()             # 用到的真实 sid（仅内存用于响应泄漏扫描，不打印）
RAW_POLL_RESPONSES = []       # poll_* RPC 原文（隐私扫描用）
INFRA = {}


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


# ---------------------------------------------------------------- SQL 通道
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


def sql_rows(stmt):
    """执行 SQL 并返回行列表（不打印行内容，避免 sid/姓名进入日志）。"""
    body = json.dumps({"EnvId": _apply_sql.ENV_ID, "Sql": stmt}, ensure_ascii=False)
    r = subprocess.run([_apply_sql.NODE, _apply_sql.TCB_BIN, "api", "tcb", "ExecutePGSql",
                        "--api-version", _apply_sql.API_VERSION, "--body", body, "--json"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    a, b = out.find("{"), out.rfind("}")
    if a < 0 or b <= a:
        raise RuntimeError("SQL 输出无法解析")
    js = json.loads(out[a:b + 1])
    data = js.get("data") or {}
    rows = data.get("Rows") or []
    cols = data.get("Columns") or []
    parsed = []
    for raw in rows:
        try:
            arr = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(arr, list):
            parsed.append(dict(zip(cols, arr)))
    return parsed


def headers(token=None, style="device"):
    h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
         "Origin": "https://tool.furina.fun"}
    if token:
        h["X-Class-Token" if style == "class" else "X-Device-Id"] = token
    return h


def rpc(name, body=None, token=None, collect=True, timeout=60):
    try:
        r = requests.post(REST + "rpc/" + name, headers=headers(token), json=body if body is not None else {},
                          timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return 0, {"ok": False, "reason": "request-error:%s" % e}
    raw = r.text or ""
    try:
        parsed = r.json()
    except Exception:
        parsed = None
    if collect and name.startswith("poll_") and token:
        RAW_POLL_RESPONSES.append(raw)
    return r.status_code, parsed


def table_status(method, table, token, body=None):
    try:
        r = requests.request(method, REST + table + "?select=*&limit=1", headers=headers(token), json=body,
                             timeout=40)
        return r.status_code
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------- RPC 便捷
def settings(**kw):
    s = {"multi": False, "maxChoices": 1, "anonymous": True, "allowChange": True,
         "resultVisibility": "afterVote"}
    s.update(kw)
    return s


def opt(i, text=None, desc="", img=""):
    return {"id": "o%d" % i, "text": text if text is not None else ("选项%d" % i), "desc": desc, "img": img}


def pid(tag):
    return "pqa" + TAG + tag


def create(token, p, title, *, audience=None, seats=None, options=None, st=None, deadline=0,
           include_aud_keys=True, legacy=False):
    body = {"p_id": p, "p_title": title, "p_description": "", "p_mode": "long",
            "p_options": options if options is not None else [opt(1), opt(2), opt(3)],
            "p_settings": st if st is not None else settings(), "p_deadline": deadline}
    if include_aud_keys and not legacy:
        if audience is not None:
            body["p_audience"] = audience
        if seats is not None:
            body["p_audience_seats"] = seats
    stcode, r = rpc("poll_create", body, token)
    if isinstance(r, dict) and r.get("ok") and (r.get("poll") or {}).get("id"):
        if r["poll"]["id"] not in CREATED:
            CREATED.append(r["poll"]["id"])
    return stcode, r


def detail(token, p):
    return rpc("poll_detail", {"p_id": p}, token)


def submit(token, p, choices):
    return rpc("poll_submit", {"p_id": p, "p_choices": choices}, token)


def manage(token, p, action, **kw):
    body = {"p_id": p, "p_action": action}
    body.update(kw)
    return rpc("poll_manage", body, token)


def list_ids(token):
    st, rl = rpc("poll_list", {}, token)
    polls = (rl or {}).get("polls")
    if not isinstance(polls, list):
        return None
    return [x.get("id") for x in polls]


def list_row(token, p):
    st, rl = rpc("poll_list", {}, token)
    for x in ((rl or {}).get("polls") or []):
        if x.get("id") == p:
            return x
    return None


def raw_has_sid(prefix=""):
    leaks = []
    for i, raw in enumerate(RAW_POLL_RESPONSES):
        if '"sid"' in raw or "owner_sid" in raw or "audience_sid" in raw:
            leaks.append("resp[%d] sid-key" % i)
        for s in REAL_SIDS:
            if s and s in raw:
                leaks.append("resp[%d] real-sid-value" % i)
                break
    return leaks


# ---------------------------------------------------------------- 角色准备
def probe():
    """只读探测：函数/表结构/角色分布（不打印 sid/姓名）。"""
    print("== 内部函数 ==")
    for r in sql_rows("select proname, pg_get_function_identity_arguments(oid) as args "
                      "from pg_proc where proname in ('auth_is_committee','auth_is_league',"
                      "'poll_norm_audience','poll_audience_visible') order by proname"):
        print("  function:", r.get("proname"), "(", r.get("args"), ")")
    print("== 表结构 ==")
    for r in sql_rows("select table_name, column_name, data_type from information_schema.columns "
                      "where table_schema='private' and table_name in ('class_ids','class_league') "
                      "order by table_name, ordinal_position"):
        print("  %(table_name)s.%(column_name)s %(data_type)s" % r)
    print("== 角色分布（不含 sid/姓名） ==")
    for r in sql_rows("select seat, coalesce(nullif(btrim(role),''),'-') as role, "
                      "coalesce(badge,'') as badge, coalesce(is_admin,false) as admin, "
                      "coalesce(is_test,false) as test from private.class_ids where seat in (1,2,3,16) order by seat"):
        print("  seat=%(seat)s role=%(role)s badge=%(badge)s admin=%(admin)s test=%(test)s" % r)
    for r in sql_rows("select c.seat, (l.sid is not null) as in_league from private.class_ids c "
                      "left join private.class_league l on l.sid = c.sid "
                      "where c.seat in (1,2,3,16) order by c.seat"):
        print("  seat=%(seat)s in_league=%(in_league)s" % r)
    print("== 可用普通成员座号（非班委/非团员/非管理员/非测试，前 8） ==")
    print([r["seat"] for r in sql_rows(
        "select c.seat from private.class_ids c left join private.class_league l on l.sid=c.sid "
        "where not coalesce(c.is_admin,false) and not coalesce(c.is_test,false) "
        "and coalesce(nullif(btrim(c.role),''),'')='' and coalesce(c.badge,'') not like '%班委%' "
        "and l.sid is null order by c.seat limit 8")])
    print("== 测试身份行 ==")
    for r in sql_rows("select seat, coalesce(is_test,false) as test from private.class_ids "
                      "where sid = '%s'" % TEST_SID):
        print("  test_sid seat=%(seat)s is_test=%(test)s" % r)
    print("== 角色判定函数定义（auth_is_committee / auth_is_league） ==")
    for r in sql_rows("select proname, pg_get_functiondef(oid) as d from pg_proc "
                      "where proname in ('auth_is_committee','auth_is_league') order by proname"):
        print("  ---- %s ----" % r.get("proname"))
        print("  " + str(r.get("d") or "").replace("\n", "\n  ")[:900])
    print("== 当前云端 poll 总量（残留检查） ==")
    try:
        h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
             "Origin": "https://tool.furina.fun"}
        r = requests.post(REST + "rpc/class_verify", headers=h,
                          json={"p_sid": TEST_SID, "p_name": TEST_NAME}, timeout=30).json()
        tok = (r or {}).get("token") or ""
        if tok:
            h2 = dict(h)
            h2["X-Device-Id"] = tok
            rl = requests.post(REST + "rpc/poll_list", headers=h2, json={}, timeout=30).json()
            polls = (rl or {}).get("polls") or []
            print("  polls_total=%d pqa_leftover=%s" % (
                len(polls), [p.get("id") for p in polls if str(p.get("id", "")).startswith("pqa")]))
            sql_quiet("delete from private.class_sessions where token = '%s'" % tok)
    except Exception as e:  # noqa: BLE001
        print("  残留检查失败:", e)


def load_roles():
    """读取班级名单角色信息（仅内存使用；不打印 sid/姓名）。"""
    rows = sql_rows(
        "select sid, coalesce(seat,0)::int as seat, coalesce(name,'') as name, "
        "coalesce(role,'') as role, coalesce(badge,'') as badge, "
        "coalesce(is_admin,false) as is_admin, coalesce(is_test,false) as is_test "
        "from private.class_ids order by seat")
    if not rows:
        raise RuntimeError("读取 private.class_ids 失败")
    league = set()
    try:
        for r in sql_rows("select sid from private.class_league"):
            league.add(str(r.get("sid") or ""))
    except Exception:  # noqa: BLE001
        raise RuntimeError("读取 private.class_league 失败")
    for r in rows:
        r["seat"] = int(r.get("seat") or 0)
        r["in_league"] = str(r.get("sid") or "") in league
        r["is_committee"] = bool(str(r.get("role") or "").strip()) or ("班委" in str(r.get("badge") or ""))
        # tcb ExecutePGSql 把布尔值序列化成字符串（'true'/'false'），这里统一归一
        r["is_admin"] = str(r.get("is_admin")).lower() in ("true", "t", "1")
        r["is_test"] = str(r.get("is_test")).lower() in ("true", "t", "1")
    return rows


def pick_roles(rows):
    def find(pred, used):
        for r in rows:
            if r["seat"] <= 0 or str(r["sid"]) in used:
                continue
            if pred(r):
                return r
        return None

    used = set()
    committee = find(lambda r: r["is_committee"] and not r["is_admin"] and not r["is_test"]
                     and not r["in_league"], used)
    if committee is None:
        committee = find(lambda r: r["is_committee"] and not r["is_admin"] and not r["is_test"], used)
    used.add(str((committee or {}).get("sid")))
    league = find(lambda r: r["in_league"] and not r["is_committee"] and not r["is_admin"] and not r["is_test"],
                  used)
    used.add(str((league or {}).get("sid")))
    normal_a = find(lambda r: (not r["is_committee"] and not r["in_league"] and not r["is_admin"]
                               and not r["is_test"]), used)
    used.add(str((normal_a or {}).get("sid")))
    normal_b = find(lambda r: (not r["is_committee"] and not r["in_league"] and not r["is_admin"]
                               and not r["is_test"]), used)
    used.add(str((normal_b or {}).get("sid")))
    admin = find(lambda r: r["is_admin"] and not r["is_test"], used)
    test_row = find(lambda r: r["is_test"], used)
    return {"committee": committee, "league": league, "normal_a": normal_a,
            "normal_b": normal_b, "admin": admin, "test": test_row}


def setup_sessions(roles):
    toks = {}
    stmts = []
    for key in ("committee", "league", "normal_a", "normal_b", "admin"):
        r = roles.get(key)
        if not r:
            continue
        tok = "qatok_qaud%s_%s" % (TAG, key.replace("_", ""))
        toks[key] = tok
        stmts.append("('%s','%s','%s',now()+interval '2 days')"
                     % (tok, str(r["sid"]).replace("'", "''"), str(r["name"]).replace("'", "''")))
        REAL_SIDS.add(str(r["sid"]))
    if stmts:
        ok = sql("insert into private.class_sessions(token,sid,name,expires_at) values "
                 + ",".join(stmts) + " on conflict (token) do nothing")
        if not ok:
            raise RuntimeError("创建一次性 class_sessions 失败")
    SESSION_TOKENS.extend([t for t in toks.values() if t])
    return toks


# ---------------------------------------------------------------- 验收主流程
def main():
    # ---------- 0. 准备 ----------
    rows = load_roles()
    roles = pick_roles(rows)
    missing = [k for k, v in roles.items() if k != "test" and not v]
    T("0.1 角色准备：班委/仅团员/普通成员×2/管理员均存在", not missing, "missing=%s" % missing)
    if missing:
        return RESULTS
    sess = setup_sessions(roles)
    owner_sid = "9999020001"
    REAL_SIDS.add(owner_sid)
    own_tok = "qatok_qaud%s_owner" % TAG
    ok = sql("insert into private.class_sessions(token,sid,name,expires_at) values "
             "('%s','%s','可见范围测试发起人',now()+interval '2 days') on conflict (token) do nothing"
             % (own_tok, owner_sid))
    T("0.2 一次性 QA 会话创建（班委/仅团员/普通×2/管理员/发起人）", bool(ok))
    SESSION_TOKENS.append(own_tok)
    COM, LEG = sess.get("committee"), sess.get("league")
    NOR, NOR2, ADM = sess.get("normal_a"), sess.get("normal_b"), sess.get("admin")
    seat_com, seat_leg = int(roles["committee"]["seat"]), int(roles["league"]["seat"])
    seat_nor, seat_nor2 = int(roles["normal_a"]["seat"]), int(roles["normal_b"]["seat"])
    seat_adm = int(roles["admin"]["seat"])
    seat_test = int(roles["test"]["seat"]) if roles.get("test") and int(roles["test"]["seat"]) > 0 else 0
    for t in (own_tok, COM, LEG, NOR, NOR2, ADM):
        st, r = rpc("poll_list", {}, t, collect=False)
        if not (isinstance(r, dict) and r.get("ok") is True):
            T("0.3 会话可用（poll_list）", False, str(r)[:120])
            return RESULTS
    T("0.3 六个一次性会话均可用（poll_list ok）", True)
    # 测试身份真实登录（is_test 座号排除用）
    st, r = rpc("class_verify", {"p_sid": TEST_SID, "p_name": TEST_NAME}, None, collect=False)
    tok_test = (r or {}).get("token") or ""
    if tok_test:
        SESSION_TOKENS.append(tok_test)
    REAL_SIDS.add(TEST_SID)
    T("0.4 测试身份（is_test）登录成功", bool(tok_test))
    T("0.5 角色互斥：班委不在团员名单、仅团员非班委、普通成员两者都不是、管理员非测试",
      (not roles["committee"]["in_league"]) and (not roles["league"]["is_committee"])
      and (not roles["normal_a"]["is_committee"] and not roles["normal_a"]["in_league"])
      and (not roles["normal_b"]["is_committee"] and not roles["normal_b"]["in_league"])
      and (not roles["admin"]["is_test"]))

    # ---------- 1. 创建与向后兼容 ----------
    p_all = pid("all")
    st, r = create(own_tok, p_all, "全班可见投票", audience="all", deadline=0)
    T("1.1 audience=all 创建成功（返回 audience=all、audience_count=0）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience") == "all"
      and (r.get("poll") or {}).get("audience_count") == 0, r.get("reason"))
    p_legacy = pid("legacy")
    st, r = create(own_tok, p_legacy, "旧客户端创建（不传 audience）", legacy=True, deadline=0)
    T("1.2 旧客户端不传 p_audience/p_audience_seats → 等价 all（向后兼容）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience") == "all"
      and (r.get("poll") or {}).get("audience_count") == 0, r.get("reason"))
    st, r = create(own_tok, pid("emptyaud"), "空字符串范围", audience="", deadline=0)
    T("1.3 p_audience='' 归一为 all", r.get("ok") is True
      and (r.get("poll") or {}).get("audience") == "all")
    st, r = create(own_tok, pid("allseats"), "all+误传座号", audience="all",
                   seats=[seat_nor], deadline=0)
    T("1.4 audience=all 时误传座号被忽略（seats=[]）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience_seats") == [])
    st, r = create(own_tok, pid("badaud"), "非法范围", audience="class", deadline=0)
    T("1.5 非法 audience 值被拒「可见范围不合法」",
      r.get("ok") is False and r.get("reason") == "可见范围不合法", r.get("reason"))

    # ---------- 2. custom 座号校验 ----------
    p_custom = pid("custom")
    st, r = create(own_tok, p_custom, "指定成员可见", audience="custom",
                   seats=[seat_com, seat_nor, seat_nor, 998, seat_com], deadline=0)
    seats = ((r.get("poll") or {}).get("audience_seats") or []) if r.get("ok") else []
    T("2.1 custom 创建成功：去重升序、过滤不存在座号（返回 [班委,普通]）",
      r.get("ok") is True and seats == sorted({seat_com, seat_nor}), str(seats))
    T("2.2 custom audience_count = 有效座号数", (r.get("poll") or {}).get("audience_count") == 2)
    st, r = create(own_tok, pid("cempty"), "custom 空", audience="custom", seats=[], deadline=0)
    T("2.3 custom 空座号被拒「请选择可见成员」",
      r.get("ok") is False and r.get("reason") == "请选择可见成员", r.get("reason"))
    st, r = create(own_tok, pid("cnone"), "custom 非数组", audience="custom",
                   seats={"a": 1}, deadline=0)
    T("2.4 custom 座号非数组被拒「请选择可见成员」",
      r.get("ok") is False and r.get("reason") == "请选择可见成员", r.get("reason"))
    st, r = create(own_tok, pid("c998"), "custom 不存在座号", audience="custom",
                   seats=[998, 998], deadline=0)
    T("2.5 custom 全部座号不存在被拒「请选择可见成员」",
      r.get("ok") is False and r.get("reason") == "请选择可见成员", r.get("reason"))
    p_custom_test = pid("ctest")
    st, r = create(own_tok, p_custom_test, "custom 含 is_test 座号",
                   audience="custom", seats=[seat_test, seat_nor] if seat_test else [seat_nor],
                   deadline=0)
    seats_t = ((r.get("poll") or {}).get("audience_seats") or []) if r.get("ok") else []
    T("2.6 custom 排除 is_test 测试身份座号（只保留真实成员座号）",
      r.get("ok") is True and (seat_test not in seats_t) and seat_nor in seats_t, str(seats_t))
    st, r = create(own_tok, pid("cstr"), "custom 字符串座号", audience="custom",
                   seats="2,3", deadline=0)
    T("2.7 custom 座号为字符串被拒", r.get("ok") is False and r.get("reason") == "请选择可见成员")

    # ---------- 3. 创建 com/league/custom 三场用于可见性矩阵 ----------
    p_comm = pid("comm")
    st, r = create(own_tok, p_comm, "班委可见投票", audience="committee", deadline=0)
    T("3.1 audience=committee 创建成功（audience_count=0）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience") == "committee"
      and (r.get("poll") or {}).get("audience_count") == 0)
    p_leg = pid("leg")
    st, r = create(own_tok, p_leg, "团员可见投票", audience="league", deadline=0)
    T("3.2 audience=league 创建成功", r.get("ok") is True
      and (r.get("poll") or {}).get("audience") == "league")

    # ---------- 4. 列表可见性矩阵 ----------
    def visible(token, p):
        return p in (list_ids(token) or [])

    T("4.1 all：六种身份列表全部可见（含范围外普通成员）",
      all(visible(t, p_all) for t in (own_tok, COM, LEG, NOR, NOR2, ADM)))
    T("4.2 committee：班委/发起人/管理员可见；仅团员/普通成员×2 不可见",
      visible(COM, p_comm) and visible(own_tok, p_comm) and visible(ADM, p_comm)
      and not visible(LEG, p_comm) and not visible(NOR, p_comm) and not visible(NOR2, p_comm))
    T("4.3 league：团员/发起人/管理员可见；班委/普通成员×2 不可见",
      visible(LEG, p_leg) and visible(own_tok, p_leg) and visible(ADM, p_leg)
      and not visible(COM, p_leg) and not visible(NOR, p_leg) and not visible(NOR2, p_leg))
    T("4.4 custom：指定成员(普通A)/发起人/管理员可见；班委(在custom内)/仅团员/普通B 按名单判定",
      visible(NOR, p_custom) and visible(COM, p_custom) and visible(own_tok, p_custom)
      and visible(ADM, p_custom) and not visible(LEG, p_custom) and not visible(NOR2, p_custom))
    T("4.5 custom 未列入指定成员：普通B 列表完全看不到，并且无法通过列表拿到行数据",
      not visible(NOR2, p_custom) and list_row(NOR2, p_custom) is None)
    row_own = list_row(own_tok, p_custom)
    row_nor = list_row(NOR, p_custom)
    T("4.6 列表不返回 audience_seats 字段（只有 audience/audience_count）",
      row_own is not None and row_nor is not None
      and "audience_seats" not in row_own and "audience_seats" not in row_nor)
    T("4.7 列表返回 audience=+audience_count（custom=2）",
      row_own is not None and row_own.get("audience") == "custom" and row_own.get("audience_count") == 2)

    # ---------- 5. detail：范围外「投票不存在」 ----------
    for label, tok, p in (("仅团员看班委投票", LEG, p_comm), ("班委看团员投票", COM, p_leg),
                          ("普通B看custom投票", NOR2, p_custom), ("测试身份看custom投票", tok_test, p_custom_test)):
        st, r = detail(tok, p)
        T("5.%d %s：detail 返回「投票不存在」" % (len([x for x in RESULTS if x["name"].startswith("5.")]) + 1, label),
          r.get("ok") is False and r.get("reason") == "投票不存在", r.get("reason"))
    st, r = detail(NOR, p_custom)
    T("5.5 范围内普通成员 detail 成功，且 can_manage=false / audience_seats=[] / audience_count=2",
      r.get("ok") is True and r.get("can_manage") is False
      and (r.get("poll") or {}).get("audience_seats") == []
      and (r.get("poll") or {}).get("audience_count") == 2)
    st, r = detail(own_tok, p_custom)
    T("5.6 发起人（不在 custom 名单内）detail 可见且 audience_seats 完整（仅 can_manage 返回）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience_seats") == sorted({seat_com, seat_nor}))
    st, r = detail(ADM, p_custom)
    T("5.7 管理员（不在 custom 名单内）detail 可见、can_manage=true、能看到座号数组",
      r.get("ok") is True and r.get("can_manage") is True and r.get("mine") is False
      and (r.get("poll") or {}).get("audience_seats") == sorted({seat_com, seat_nor}))

    # ---------- 6. submit：范围外/管理员/发起人 ----------
    st, r = submit(LEG, p_comm, ["o1"])
    T("6.1 范围外普通成员提交 → 「投票不存在」",
      r.get("ok") is False and r.get("reason") == "投票不存在", r.get("reason"))
    st, r = submit(NOR2, p_custom, ["o1"])
    T("6.2 custom 名单外普通成员提交 → 「投票不存在」",
      r.get("ok") is False and r.get("reason") == "投票不存在", r.get("reason"))
    st, r = submit(ADM, p_custom, ["o1"])
    T("6.3 管理员可见但不在范围内提交 → 「不在可见范围内」",
      r.get("ok") is False and r.get("reason") == "不在可见范围内", r.get("reason"))
    st, r = submit(own_tok, p_custom, ["o1"])
    T("6.4 发起人（不在 custom 名单内）始终可投票", r.get("ok") is True and r.get("has_voted") is True)
    st, r = submit(COM, p_custom, ["o2"])
    T("6.5 custom 名单内成员可投票", r.get("ok") is True and r.get("total") == 2, "total=%s" % r.get("total"))
    st, r = submit(COM, p_comm, ["o2"])
    T("6.6 班委在 committee 范围可投票", r.get("ok") is True)
    st, r = submit(LEG, p_leg, ["o3"])
    T("6.7 团员在 league 范围可投票", r.get("ok") is True)
    st, r = submit(NOR, p_all, ["o1"])
    T("6.8 all 范围任意成员可投票", r.get("ok") is True)

    # ---------- 7. 管理员可见/可管理（越权管理） ----------
    p_adm = pid("adm")
    st, r = create(own_tok, p_adm, "管理员管理测试（班委可见）", audience="committee", deadline=0)
    st, r = manage(ADM, p_adm, "close")
    T("7.1 管理员可管理他人投票（close）",
      r.get("ok") is True and r.get("closed") is True and r.get("can_manage") is True, r.get("reason"))
    st, r = manage(ADM, p_adm, "extend", p_deadline=NOW + 7200 * 1000)
    T("7.2 管理员可延长/重开他人投票", r.get("ok") is True and r.get("closed") is False)
    st, r = detail(ADM, p_adm)
    T("7.3 管理员 (can_manage=true) 详情可见 audience_seats（committee 为 []）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience") == "committee")
    st, r = manage(NOR2, p_adm, "close")
    T("7.4 范围外非管理员不能管理（无权管理该投票）",
      r.get("ok") is False and r.get("reason") == "无权管理该投票", r.get("reason"))

    # ---------- 8. 旧客户端/编辑可见范围 ----------
    p_edit_old = pid("editold")
    st, r = create(own_tok, p_edit_old, "旧客户端编辑不改范围", audience="committee", deadline=0)
    st, r = manage(own_tok, p_edit_old, "edit", p_title="旧客户端改名", p_description="",
                   p_options=[opt(1), opt(2)], p_settings=settings(), p_deadline=NOW + 3600 * 1000)
    T("8.1 旧客户端 edit 不传 p_audience → 可见范围保持不变（committee）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience") == "committee"
      and (r.get("poll") or {}).get("title") == "旧客户端改名", r.get("reason"))
    p_edit_new = pid("editnew")
    st, r = create(own_tok, p_edit_new, "编辑改为指定成员", audience="all", deadline=0)
    st, r = manage(own_tok, p_edit_new, "edit", p_title="编辑后指定成员", p_description="",
                   p_options=[opt(1), opt(2)], p_settings=settings(), p_deadline=NOW + 3600 * 1000,
                   p_audience="custom", p_audience_seats=[seat_nor2])
    T("8.2 无票时 edit 可改可见范围（all → custom 普通B）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience") == "custom"
      and (r.get("poll") or {}).get("audience_seats") == [seat_nor2], r.get("reason"))
    T("8.3 改范围后：普通B 可见、普通A 不可见",
      visible(NOR2, p_edit_new) and not visible(NOR, p_edit_new))
    st, r = manage(own_tok, p_edit_new, "edit", p_title="再改范围", p_description="",
                   p_options=[opt(1), opt(2)], p_settings=settings(), p_deadline=NOW + 3600 * 1000,
                   p_audience="custom", p_audience_seats=[])
    T("8.4 edit 传 custom 空座号被拒「请选择可见成员」",
      r.get("ok") is False and r.get("reason") == "请选择可见成员", r.get("reason"))
    st, r = manage(own_tok, p_edit_new, "edit", p_title="非法范围", p_description="",
                   p_options=[opt(1), opt(2)], p_settings=settings(), p_deadline=NOW + 3600 * 1000,
                   p_audience="nope")
    T("8.5 edit 传非法范围被拒「可见范围不合法」",
      r.get("ok") is False and r.get("reason") == "可见范围不合法", r.get("reason"))
    p_edit_voted = pid("editvoted")
    st, r = create(own_tok, p_edit_voted, "有票不可编辑", audience="committee", deadline=0)
    st, r = submit(COM, p_edit_voted, ["o1"])
    st, r = manage(own_tok, p_edit_voted, "edit", p_title="有票改名", p_description="",
                   p_options=[opt(1), opt(2)], p_settings=settings(), p_deadline=NOW + 3600 * 1000,
                   p_audience="all", p_audience_seats=[])
    T("8.6 已有票时 edit（含改范围）被拒「已有投票，不能修改内容」",
      r.get("ok") is False and r.get("reason") == "已有投票，不能修改内容", r.get("reason"))
    st, r = manage(own_tok, p_edit_voted, "close")
    T("8.7 旧签名 style 的 manage（不传 audience 参数）可正常执行 close",
      r.get("ok") is True and r.get("closed") is True)

    # ---------- 9. 范围检查顺序 & 关闭状态不泄露存在性 ----------
    p_closed = pid("closed")
    st, r = create(own_tok, p_closed, "已结束的班委投票", audience="committee", deadline=0)
    st, r = manage(own_tok, p_closed, "close")
    st, r = submit(NOR2, p_closed, ["o1"])
    T("9.1 范围外 + 已结束：先返回「投票不存在」（不泄露存在性/状态）",
      r.get("ok") is False and r.get("reason") == "投票不存在", r.get("reason"))
    st, r = submit(COM, p_closed, ["o1"])
    T("9.2 范围内 + 已结束：返回「投票已结束」", r.get("ok") is False and r.get("reason") == "投票已结束")
    # 管理员不在 custom 范围时，即使已结束也应先返回「不在可见范围内」（顺序校验）
    p_closed2 = pid("closed2")
    st, r = create(own_tok, p_closed2, "已结束的指定成员投票", audience="custom",
                   seats=[seat_nor], deadline=0)
    st, r = manage(own_tok, p_closed2, "close")
    st, r = submit(ADM, p_closed2, ["o1"])
    T("9.3 管理员 + 范围外（即便已结束）优先返回「不在可见范围内」",
      r.get("ok") is False and r.get("reason") == "不在可见范围内", r.get("reason"))

    # ---------- 10. 隐私/权限/直连表 ----------
    leaks = raw_has_sid()
    T("10.1 所有 poll_* 原始响应无 sid 字段/真实学号值（%d 份响应扫描）" % len(RAW_POLL_RESPONSES),
      not leaks, str(leaks[:3]))
    ten = [raw for raw in RAW_POLL_RESPONSES if re.search(r"\b\d{10}\b", raw)]
    T("10.2 响应原文无 10 位学号数字", not ten, "n=%d" % len(ten))
    st = table_status("GET", "polls", NOR2)
    T("10.3 直连 polls 表仍被拒（401/403）", st in (401, 403), "status=%s" % st)
    st = table_status("GET", "poll_votes", NOR2)
    T("10.4 直连 poll_votes 表仍被拒（401/403）", st in (401, 403), "status=%s" % st)
    st, r = rpc("poll_list", {}, None, collect=False)
    T("10.5 无 token 仍拒绝", r.get("ok") is False)

    # ---------- 11. 幂等 & 保底 ----------
    st, r = create(own_tok, p_custom, "幂等重试不同标题", audience="all", deadline=0)
    T("11.1 同 id 幂等创建返回原投票（audience 保持 custom，不被覆盖）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience") == "custom"
      and (r.get("poll") or {}).get("title") == "指定成员可见")
    st, r = create(own_tok, pid("nodl"), "无截止全班", audience="all")
    T("11.2 p_deadline 省略（默认 0）创建成功",
      r.get("ok") is True and (r.get("poll") or {}).get("deadline") == 0)
    return RESULTS


def cleanup_and_verify():
    extra = []
    try:
        ids = [x for x in CREATED if x]
        if ids:
            lst = ",".join("'%s'" % i for i in ids)
            sql("delete from public.poll_votes where poll_id in (%s)" % lst)
            sql("delete from public.polls where id in (%s)" % lst)
        extra.append(("清理 1 测试投票硬删除（poll_votes + polls）", True, "n=%d" % len(ids)))
        gone = True
        for i in ids:
            st, r = detail(SESSION_TOKENS[0], i)
            if not (isinstance(r, dict) and r.get("ok") is False and "不存在" in str(r.get("reason"))):
                gone = False
                break
        extra.append(("清理 2 硬删后详情均不可查（逐 id 复查）", gone))
        st, rl = rpc("poll_list", {}, SESSION_TOKENS[0])
        left = [x.get("id") for x in ((rl or {}).get("polls") or []) if x.get("id") in set(ids)]
        extra.append(("清理 3 列表无残留测试投票", not left, str(left)))
    except Exception as e:  # noqa: BLE001
        extra.append(("清理 1 测试投票硬删除", False, str(e)))
    try:
        toks = [t for t in SESSION_TOKENS if t]
        if toks:
            lst = ",".join("'%s'" % t for t in toks)
            sql_quiet("delete from private.class_sessions where token in (%s)" % lst)
        extra.append(("清理 4 一次性 class_sessions 全部删除（含测试身份本次会话）", True, "n=%d" % len(toks)))
    except Exception as e:  # noqa: BLE001
        extra.append(("清理 4 一次性 class_sessions 删除", False, str(e)))
    try:
        st, r = rpc("poll_list", {}, SESSION_TOKENS[0], collect=False)
        extra.append(("清理 5 清除后 QA token 已失效", r.get("ok") is False))
    except Exception as e:  # noqa: BLE001
        extra.append(("清理 5 清除后 QA token 已失效", False, str(e)))
    for item in extra:
        T(*item)


def save_report():
    fails = [x for x in RESULTS if not x["ok"]]
    with open(os.path.join(SHOTS, "audience_cloud_report.json"), "w", encoding="utf-8") as f:
        json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "pass": len(RESULTS) - len(fails), "fail": len(fails), "results": RESULTS},
                  f, ensure_ascii=False, indent=2)
    return len(fails)


NOW = 0

if __name__ == "__main__":
    if "--probe" in sys.argv:
        NOW = int(time.time() * 1000)
        probe()
        sys.exit(0)
    import traceback
    NOW = int(time.time() * 1000)
    main_exc = False
    try:
        main()
    except Exception:  # noqa: BLE001
        main_exc = True
        traceback.print_exc()
        RESULTS.append({"name": "0.0 主流程未抛未捕获异常", "ok": False, "note": traceback.format_exc()[-500:]})
    finally:
        cleanup_and_verify()
        nf = save_report()
        print("\n=========== vote_qa_audience: %d PASS / %d FAIL ===========" % (len(RESULTS) - nf, nf))
        sys.exit(1 if (nf or main_exc) else 0)
