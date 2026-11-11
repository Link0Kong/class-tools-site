# -*- coding: utf-8 -*-
"""真实云端验证：2026-11-11 共享表迁移（public.water / public.water_room / public.stage_prefs）

契约：`tools/tests/_water_shared_contract.md`、`tools/tests/_stage_sync_contract.md`
迁移：`deploy/cloudbase/2026-11-11_water_shared.sql`、`deploy/cloudbase/2026-11-11_stage_prefs.sql`

覆盖（真实 CloudBase PostgreSQL + PostgREST，**仅测试身份** + 同身份第二会话；2026-11-11 用户红线：
测试不得使用任何真实账号）：
1) schema 与迁移文件一致：列/类型/NOT NULL/默认值、主键（water=(roomverify,month)、
   water_room=roomverify、stage_prefs=sid）、persons CHECK(4,6)、RLS 开启、策略名称/命令/角色、
   stage_prefs.updated_at 触发器、anon 表级授权、auth_ok()/auth_sid() 存在；
2) 无 token → GET 返回 []、写被拒（401/403），不会产生行；
3) 有效 token：water upsert 幂等（同 (roomverify,month) 覆盖）、GET/DELETE、water_room upsert、
   测试身份的第二会话能看到/写入同一条宿舍记录（water 为班级 token 共享，与 session 无关）；
4) stage_prefs：写入 layout → 读回一致；再次写入 updated_at 递增（LWW 触发器的关键）；
   写入非本人 sid 被 with check 拒绝（仅本人行）；删除不存在（契约无 DELETE 策略，用超级用户清理）；
5) 清理：finally 用 ExecutePGSQL 超级用户删除本次测试行/第二会话，并复核 0 残留。

安全：token / 学号 / 姓名只存在进程内存，**不打印、不落盘**；测试行写入前带唯一标记，
finally 硬删除。本脚本不修改任何迁移/业务数据。

运行（web 目录）：
    python deploy/cloudbase/verify_2026_11_11_shared_tables.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
REST = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
KEY = open(os.path.join(HERE, "publish_key.txt"), encoding="utf-8").read().strip()
TEST_SID, TEST_NAME = "3260799999", "测试账号"      # 测试身份（is_test=true，公开凭据，不打印）
QA_TOKEN = "qatok_shared_verify_20261111"   # 测试身份的第二会话 token（不是任何真实账号）
MARK_RV = "4-TEST---999"                           # 测试专用 roomverify（唯一、可识别）
MARK_MONTH = "2099-12"                             # 测试专用月份（不影响真实数据）
LAYOUT_A = {"v": 1, "order": ["ppt", "vote", "timer", "draw"],
            "span": {"ppt": 8, "vote": 4, "timer": 6, "draw": 6},
            "hidden": [], "lastDeck": "", "pptDl": {}, "at": 1762860000000}
LAYOUT_B = {"v": 1, "order": ["vote", "ppt", "timer", "draw"],
            "span": {"ppt": 6, "vote": 6, "timer": 6, "draw": 6},
            "hidden": ["timer"], "lastDeck": "verifytestdeck", "pptDl": {}, "at": 1762860123456}

RESULTS = []
MEM = {"test_token": "", "test_sid": "", "qa_token": "", "qa_sid": "",
       "created": {"water": False, "water_room": False, "stage_prefs": False,
                   "qa_stage": False, "qa_session": False}}

_spec = importlib.util.spec_from_file_location("apply_sql", os.path.join(HERE, "apply_sql.py"))
_apply_sql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_apply_sql)


# ------------------------------------------------------------------ 基础工具
def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


def _tcb(sql, timeout=120):
    body = json.dumps({"EnvId": _apply_sql.ENV_ID, "Sql": sql}, ensure_ascii=False)
    return subprocess.run([_apply_sql.NODE, _apply_sql.TCB_BIN, "api", "tcb",
                           "ExecutePGSql", "--api-version", _apply_sql.API_VERSION,
                           "--body", body, "--json"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def sql_rows(stmt):
    """只读 SQL → 行 dict 列表（不打印行内容）。"""
    r = _tcb(stmt)
    out = (r.stdout or "") + (r.stderr or "")
    a, b = out.find("{"), out.rfind("}")
    if a < 0 or b <= a:
        raise RuntimeError("SQL 输出无法解析（tcb ExecutePGSql）")
    data = (json.loads(out[a:b + 1]) or {}).get("data") or {}
    cols = data.get("Columns") or []
    rows = []
    for raw in data.get("Rows") or []:
        try:
            arr = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(arr, list):
            rows.append(dict(zip(cols, arr)))
    return rows


def sql_exec(stmt, label="sql"):
    """执行写/DDL SQL；**不打印语句内容**（可能含 sid/姓名），只打印结果标签。"""
    try:
        r = _tcb(stmt)
        out = (r.stdout or "") + (r.stderr or "")
        ok = r.returncode == 0 and "error" not in out.lower()
        print(("[ok]   " if ok else "[FAIL] ") + label)
        return ok
    except Exception as exc:  # noqa: BLE001
        print("[FAIL] %s (%s)" % (label, exc.__class__.__name__))
        return False


def _q(s):
    return str(s or "").replace("'", "''")


def hdr(token=None):
    h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
         "Origin": "https://tool.furina.fun"}
    if token:
        h["X-Device-Id"] = token
    return h


def rest(method, path, token=None, body=None, prefer=None, timeout=40):
    headers = hdr(token)
    if prefer:
        headers["Prefer"] = prefer
    try:
        r = requests.request(method, REST + path, headers=headers, json=body,
                             timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {"status": 0, "json": None, "text": exc.__class__.__name__, "hd": {}}
    parsed = None
    if r.content:
        try:
            parsed = r.json()
        except Exception:  # noqa: BLE001
            parsed = None
    return {"status": r.status_code, "json": parsed, "text": (r.text or "")[:300],
            "hd": {k.lower(): v for k, v in r.headers.items()}}


def rpc(name, body, token=None):
    try:
        r = requests.post(REST + "rpc/" + name, headers=hdr(token), json=body, timeout=40)
        return r.status_code, (r.json() if r.content else {})
    except Exception as exc:  # noqa: BLE001
        return 0, {"ok": False, "reason": exc.__class__.__name__}


def ts_ms(value):
    try:
        txt = str(value).strip().replace("Z", "+00:00")
        return int(datetime.fromisoformat(txt).timestamp() * 1000)
    except Exception:  # noqa: BLE001
        return 0


def upsert_headers():
    return "resolution=merge-duplicates,return=minimal"


# ------------------------------------------------------------------ §0 登录/QA 会话
def login_test_identity():
    st, r = rpc("class_verify", {"p_sid": TEST_SID, "p_name": TEST_NAME})
    tok = str((r or {}).get("token") or "")
    sid = str((r or {}).get("sid") or "")
    if st != 200 or not tok or not sid:
        raise SystemExit("测试身份登录失败（status=%s，网关/名单需可用）" % st)
    MEM["test_token"], MEM["test_sid"] = tok, sid
    return tok, sid


def create_qa_session():
    """测试身份的**第二会话**（同 sid、不同 token；仅用于验证「水量共享/会话无关」与 with check 拒绝），
    2026-11-11 用户红线后不再绑定任何真实班级成员；finally 删除该会话行。"""
    sid = str(MEM["test_sid"])
    name = str(TEST_NAME)
    ok = sql_exec(
        "insert into private.class_sessions(token,sid,name,expires_at) values "
        "('%s','%s','%s',now()+interval '2 hours') "
        "on conflict (token) do update set sid=excluded.sid, name=excluded.name, "
        "expires_at=excluded.expires_at"
        % (_q(QA_TOKEN), _q(sid), _q(name)), label="create second test session")
    if not ok:
        raise SystemExit("第二测试会话创建失败")
    MEM["qa_token"], MEM["qa_sid"] = QA_TOKEN, sid
    MEM["created"]["qa_session"] = True
    return QA_TOKEN, sid


def preclean():
    sql_exec("delete from public.water where roomverify = '%s'" % _q(MARK_RV),
             label="preclean water test rows")
    sql_exec("delete from public.water_room where roomverify = '%s'" % _q(MARK_RV),
             label="preclean water_room test rows")
    sql_exec("delete from public.stage_prefs where sid in ('%s')" % _q(MEM["test_sid"]),
             label="preclean stage_prefs test row")


def cleanup():
    if MEM.get("cleaned"):
        return
    MEM["cleaned"] = True
    if MEM["created"]["stage_prefs"] or MEM["created"]["qa_stage"]:
        sql_exec("delete from public.stage_prefs where sid in ('%s','%s')"
                 % (_q(MEM["test_sid"]), _q(MEM["qa_sid"])),
                 label="cleanup stage_prefs test rows")
    if MEM["created"]["water"]:
        sql_exec("delete from public.water where roomverify = '%s'" % _q(MARK_RV),
                 label="cleanup water test rows")
    if MEM["created"]["water_room"]:
        sql_exec("delete from public.water_room where roomverify = '%s'" % _q(MARK_RV),
                 label="cleanup water_room test rows")
    if MEM["created"]["qa_session"]:
        sql_exec("delete from private.class_sessions where token = '%s'" % _q(QA_TOKEN),
                 label="cleanup one-time QA session")


def _count(sql):
    rows = sql_rows(sql)
    return int((rows[0] if rows else {}).get("n") or 0)


def verify_cleanup():
    left = [
        _count("select count(*) as n from public.water where roomverify = '%s'"
               % _q(MARK_RV)),
        _count("select count(*) as n from public.water_room where roomverify = '%s'"
               % _q(MARK_RV)),
        _count("select count(*) as n from public.stage_prefs "
               "where sid in ('%s','%s')" % (_q(MEM["test_sid"]), _q(MEM["qa_sid"]))),
        _count("select count(*) as n from private.class_sessions "
               "where token = '%s'" % _q(QA_TOKEN)),
    ]
    T("清理后 0 残留（water/water_room/stage_prefs/QA 会话）", left == [0, 0, 0, 0],
      "counts=%s" % left)


# ------------------------------------------------------------------ §1 schema 核对
def check_schema():
    cols = sql_rows(
        "select table_name, column_name, data_type, is_nullable, column_default "
        "from information_schema.columns where table_schema='public' "
        "and table_name in ('water','water_room','stage_prefs') "
        "order by table_name, ordinal_position")
    by_table = {}
    for row in cols:
        by_table.setdefault(str(row["table_name"]), []).append(row)
    names = {t: [str(r["column_name"]) for r in rows] for t, rows in by_table.items()}
    T("water 列 = roomverify,month,reading,persons,updated_at",
      names.get("water") == ["roomverify", "month", "reading", "persons", "updated_at"],
      str(names.get("water")))
    T("water_room 列 = roomverify,persons,updated_at",
      names.get("water_room") == ["roomverify", "persons", "updated_at"],
      str(names.get("water_room")))
    T("stage_prefs 列 = sid,layout,updated_at",
      names.get("stage_prefs") == ["sid", "layout", "updated_at"],
      str(names.get("stage_prefs")))

    def col_of(table, name):
        for row in by_table.get(table) or []:
            if str(row["column_name"]) == name:
                return row
        return {}

    reading = col_of("water", "reading")
    persons = col_of("water", "persons")
    layout = col_of("stage_prefs", "layout")
    T("water.reading = numeric NOT NULL", "numeric" == str(reading.get("data_type"))
      and str(reading.get("is_nullable")) == "NO",
      "%s/%s" % (reading.get("data_type"), reading.get("is_nullable")))
    T("water.persons = integer NOT NULL default 4",
      str(persons.get("data_type")) == "integer"
      and str(persons.get("is_nullable")) == "NO"
      and "4" in str(persons.get("column_default") or ""),
      "%s default=%s" % (persons.get("data_type"), persons.get("column_default")))
    T("stage_prefs.layout = jsonb NOT NULL default '{}'",
      str(layout.get("data_type")) == "jsonb"
      and str(layout.get("is_nullable")) == "NO"
      and "{}" in str(layout.get("column_default") or ""),
      "%s default=%s" % (layout.get("data_type"), layout.get("column_default")))

    pks = sql_rows(
        "select tc.table_name, kcu.column_name, tc.constraint_type "
        "from information_schema.table_constraints tc "
        "join information_schema.key_column_usage kcu on tc.constraint_name = kcu.constraint_name "
        "and tc.table_schema = kcu.table_schema "
        "where tc.table_schema='public' and tc.table_name in ('water','water_room','stage_prefs') "
        "and tc.constraint_type='PRIMARY KEY' order by tc.table_name, kcu.ordinal_position")
    pk = {}
    for row in pks:
        pk.setdefault(str(row["table_name"]), []).append(str(row["column_name"]))
    T("water PK = (roomverify, month)",
      pk.get("water") == ["roomverify", "month"], str(pk.get("water")))
    T("water_room PK = roomverify", pk.get("water_room") == ["roomverify"],
      str(pk.get("water_room")))
    T("stage_prefs PK = sid", pk.get("stage_prefs") == ["sid"],
      str(pk.get("stage_prefs")))

    checks = sql_rows(
        "select conrelid::regclass::text as tbl, conname, pg_get_constraintdef(oid) as def "
        "from pg_constraint where contype='c' "
        "and conrelid in ('public.water'::regclass, 'public.water_room'::regclass)")
    defs = {str(r["tbl"]).replace("public.", ""): str(r["def"] or "") for r in checks}
    chk_ok = (len(checks) == 2
              and all("4" in defs.get(t, "") and "6" in defs.get(t, "")
                      for t in ("water", "water_room")))
    T("persons CHECK (persons IN (4,6)) 存在（water + water_room）", chk_ok,
      "constraints=%s" % list(defs.keys()))

    rls = sql_rows(
        "select c.relname, c.relrowsecurity from pg_class c "
        "join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname='public' and c.relname in ('water','water_room','stage_prefs')")
    rls_map = {str(r["relname"]): bool(r["relrowsecurity"]) for r in rls}
    T("三表均开启 RLS", all(rls_map.get(t) is True for t in
                            ("water", "water_room", "stage_prefs")), str(rls_map))

    pols = sql_rows(
        "select tablename, policyname, cmd, roles::text as roles from pg_policies "
        "where schemaname='public' and tablename in ('water','water_room','stage_prefs') "
        "order by tablename, policyname")
    want = {
        "water": {"water_read": "SELECT", "water_insert": "INSERT",
                  "water_update": "UPDATE", "water_delete": "DELETE"},
        "water_room": {"water_room_read": "SELECT", "water_room_insert": "INSERT",
                       "water_room_update": "UPDATE", "water_room_delete": "DELETE"},
        "stage_prefs": {"stage_prefs_sel": "SELECT", "stage_prefs_ins": "INSERT",
                        "stage_prefs_upd": "UPDATE"},
    }
    got = {}
    for row in pols:
        got.setdefault(str(row["tablename"]), {})[str(row["policyname"])] = str(row["cmd"]).upper()
    T("RLS 策略与契约一致（water 4 / water_room 4 / stage_prefs 3，仅 anon）",
      got == want and all("{anon}" == str(r["roles"]) for r in pols),
      "tables=%s" % (({k: len(v) for k, v in got.items()}),))

    trig = sql_rows(
        "select t.tgname from pg_trigger t where t.tgrelid='public.stage_prefs'::regclass "
        "and not t.tgisinternal")
    T("stage_prefs.updated_at 触发器存在（updated_at 每次写入刷新）",
      any(str(r["tgname"]) == "stage_prefs_touch_trg" for r in trig),
      str([r["tgname"] for r in trig]))

    fns = sql_rows(
        "select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname='public' and p.proname in ('auth_ok','auth_sid')")
    fn_names = sorted(str(r["proname"]) for r in fns)
    T("public.auth_ok()/auth_sid() 存在", fn_names == ["auth_ok", "auth_sid"], str(fn_names))

    grants = sql_rows(
        "select table_name, privilege_type from information_schema.role_table_grants "
        "where table_schema='public' and grantee='anon' "
        "and table_name in ('water','water_room','stage_prefs') "
        "order by table_name, privilege_type")
    gmap = {}
    for row in grants:
        gmap.setdefault(str(row["table_name"]), set()).add(str(row["privilege_type"]).upper())
    T("water/water_room anon 授权 SELECT/INSERT/UPDATE/DELETE",
      gmap.get("water") == {"SELECT", "INSERT", "UPDATE", "DELETE"}
      and gmap.get("water_room") == {"SELECT", "INSERT", "UPDATE", "DELETE"},
      str({k: sorted(v) for k, v in gmap.items()}))
    T("stage_prefs anon 仅 SELECT/INSERT/UPDATE（无 DELETE，契约设计）",
      gmap.get("stage_prefs") == {"SELECT", "INSERT", "UPDATE"},
      str(sorted(gmap.get("stage_prefs") or [])))

    def has_private(table, words):
        return [c for c in (names.get(table) or [])
                if any(w in c.lower() for w in words)]
    T("water/water_room 无姓名/学号/手机号列",
      not has_private("water", ("name", "sid", "phone", "mobile", "seat"))
      and not has_private("water_room", ("name", "sid", "phone", "mobile", "seat")),
      "water=%s water_room=%s" % (names.get("water"), names.get("water_room")))
    T("stage_prefs 仅 sid 账号主键（无姓名/手机号列）",
      (names.get("stage_prefs") or []) == ["sid", "layout", "updated_at"],
      "columns=%s" % (names.get("stage_prefs"),))


# ------------------------------------------------------------------ §2 无 token
def check_no_token():
    for table, sel in (("water", "select=roomverify,month,reading,persons&roomverify=eq." + MARK_RV),
                       ("water_room", "select=roomverify,persons&roomverify=eq." + MARK_RV),
                       ("stage_prefs", "select=layout,updated_at&sid=eq." + MEM["test_sid"])):
        r = rest("GET", table + "?" + sel)
        rows = r["json"] if isinstance(r["json"], list) else None
        ok = (r["status"] == 200 and rows == []) or r["status"] in (401, 403)
        T("无 token GET %s → 401/[]（RLS 拒绝）" % table, ok,
          "HTTP %s rows=%s" % (r["status"], (len(rows) if isinstance(rows, list) else r["text"][:60])))

    r = rest("POST", "water?on_conflict=roomverify,month",
             body={"roomverify": MARK_RV, "month": MARK_MONTH,
                   "reading": 1.11, "persons": 4}, prefer=upsert_headers())
    T("无 token POST water 被拒（401/403）", r["status"] in (401, 403),
      "HTTP %s" % r["status"])
    rows = sql_rows("select count(*) as n from public.water where roomverify='%s'"
                    % _q(MARK_RV))
    T("无 token 写入未产生行", int((rows[0] or {}).get("n") or 0) == 0,
      "count=%s" % ((rows[0] or {}).get("n")))


# ------------------------------------------------------------------ §3 water 共享
def check_water_shared():
    tok = MEM["test_token"]
    path = "water?on_conflict=roomverify,month"
    r = rest("POST", path, token=tok, body={"roomverify": MARK_RV, "month": MARK_MONTH,
                                            "reading": 111.25, "persons": 4},
             prefer=upsert_headers())
    MEM["created"]["water"] = r["status"] in (200, 201, 204)
    T("测试身份 POST water upsert 成功", MEM["created"]["water"], "HTTP %s" % r["status"])

    sel = ("water?select=roomverify,month,reading,persons,updated_at"
           "&roomverify=eq.%s&month=eq.%s" % (MARK_RV, MARK_MONTH))
    r = rest("GET", sel, token=tok)
    rows = r["json"] if isinstance(r["json"], list) else []
    T("GET water 读回 1 行且字段一致",
      r["status"] == 200 and len(rows) == 1
      and rows[0].get("roomverify") == MARK_RV and rows[0].get("month") == MARK_MONTH
      and float(rows[0].get("reading")) == 111.25 and int(rows[0].get("persons")) == 4,
      "HTTP %s rows=%d" % (r["status"], len(rows)))

    # 幂等 upsert：同 (roomverify,month) 覆盖，不新增行
    r = rest("POST", path, token=tok, body={"roomverify": MARK_RV, "month": MARK_MONTH,
                                            "reading": 222.5, "persons": 6},
             prefer=upsert_headers())
    ok_post = r["status"] in (200, 201, 204)
    r = rest("GET", sel, token=tok)
    rows = r["json"] if isinstance(r["json"], list) else []
    T("water upsert 幂等（同 PK 覆盖：1 行 / reading 222.5 / persons 6）",
      ok_post and r["status"] == 200 and len(rows) == 1
      and float(rows[0].get("reading")) == 222.5 and int(rows[0].get("persons")) == 6,
      "rows=%d reading=%s persons=%s"
      % (len(rows), rows[0].get("reading") if rows else "?",
         rows[0].get("persons") if rows else "?"))

    # 同一测试身份的第二会话可见并可写同一条宿舍记录 → 水量按班级 token 共享（与 session 无关）
    qa = MEM["qa_token"]
    r = rest("GET", ("water?select=roomverify,month,reading,persons&roomverify=eq.%s"
                     "&month=eq.%s" % (MARK_RV, MARK_MONTH)), token=qa)
    qa_rows = r["json"] if isinstance(r["json"], list) else []
    T("测试身份第二会话能看到同一条 water 记录（宿舍共享）",
      r["status"] == 200 and len(qa_rows) == 1
      and float(qa_rows[0].get("reading")) == 222.5,
      "HTTP %s rows=%d" % (r["status"], len(qa_rows)))
    r = rest("POST", path, token=qa, body={"roomverify": MARK_RV, "month": MARK_MONTH,
                                           "reading": 333.75, "persons": 4},
             prefer=upsert_headers())
    T("测试身份第二会话可写同一条 water（班级共享语义）", r["status"] in (200, 201, 204),
      "HTTP %s" % r["status"])
    r = rest("GET", sel, token=tok)
    rows = r["json"] if isinstance(r["json"], list) else []
    T("测试身份主会话立即看到第二会话写入（333.75）",
      len(rows) == 1 and float(rows[0].get("reading")) == 333.75,
      "reading=%s" % (rows[0].get("reading") if rows else "?"))

    # water_room upsert
    rp = "water_room?on_conflict=roomverify"
    r = rest("POST", rp, token=tok, body={"roomverify": MARK_RV, "persons": 6},
             prefer=upsert_headers())
    MEM["created"]["water_room"] = r["status"] in (200, 201, 204)
    r = rest("GET", "water_room?select=roomverify,persons&roomverify=eq." + MARK_RV,
             token=tok)
    rows = r["json"] if isinstance(r["json"], list) else []
    T("water_room upsert persons=6 读回一致",
      MEM["created"]["water_room"] and r["status"] == 200 and len(rows) == 1
      and int(rows[0].get("persons")) == 6,
      "HTTP %s rows=%d" % (r["status"], len(rows)))
    r = rest("POST", rp, token=tok, body={"roomverify": MARK_RV, "persons": 4},
             prefer=upsert_headers())
    r = rest("GET", "water_room?select=roomverify,persons&roomverify=eq." + MARK_RV,
             token=tok)
    rows = r["json"] if isinstance(r["json"], list) else []
    T("water_room upsert 幂等（同 PK 覆盖 persons=4，仍 1 行）",
      r["status"] == 200 and len(rows) == 1 and int(rows[0].get("persons")) == 4,
      "rows=%d persons=%s" % (len(rows), rows[0].get("persons") if rows else "?"))

    # DELETE water / water_room（契约允许 delete，auth_ok）
    r = rest("DELETE", "water?roomverify=eq.%s&month=eq.%s" % (MARK_RV, MARK_MONTH),
             token=tok)
    ok_del = r["status"] in (200, 204)
    r = rest("GET", sel, token=tok)
    rows = r["json"] if isinstance(r["json"], list) else []
    T("DELETE water 后 GET 返回 []", ok_del and rows == [],
      "HTTP %s rows=%s" % (r["status"], len(rows)))
    r = rest("DELETE", "water_room?roomverify=eq." + MARK_RV, token=tok)
    ok_del = r["status"] in (200, 204)
    r = rest("GET", "water_room?select=roomverify,persons&roomverify=eq." + MARK_RV,
             token=tok)
    rows = r["json"] if isinstance(r["json"], list) else []
    T("DELETE water_room 后 GET 返回 []", ok_del and rows == [],
      "HTTP %s rows=%s" % (r["status"], len(rows)))
    MEM["created"]["water"] = False
    MEM["created"]["water_room"] = False


# ------------------------------------------------------------------ §4 stage_prefs
def check_stage_prefs():
    tok, sid, qa, qa_sid = MEM["test_token"], MEM["test_sid"], MEM["qa_token"], MEM["qa_sid"]
    own_get = "stage_prefs?select=layout,updated_at&sid=eq." + urllib.parse.quote(sid)

    # 无 token 已在 §2 覆盖；测试身份初始为 []
    r = rest("GET", own_get, token=tok)
    rows = r["json"] if isinstance(r["json"], list) else []
    T("测试身份初始 stage_prefs = []（干净）", r["status"] == 200 and rows == [],
      "HTTP %s rows=%d" % (r["status"], len(rows)))

    body = {"sid": sid, "layout": dict(LAYOUT_A)}
    r = rest("POST", "stage_prefs?on_conflict=sid", token=tok, body=body,
             prefer=upsert_headers())
    MEM["created"]["stage_prefs"] = r["status"] in (200, 201, 204)
    T("测试身份写入 layout 成功", MEM["created"]["stage_prefs"],
      "HTTP %s" % r["status"])

    r = rest("GET", own_get, token=tok)
    rows = r["json"] if isinstance(r["json"], list) else []
    remote = (rows[0] or {}).get("layout") if rows else None
    updated1 = ts_ms((rows[0] or {}).get("updated_at")) if rows else 0
    same = isinstance(remote, dict) and remote.get("v") == 1 \
        and remote.get("order") == LAYOUT_A["order"] \
        and remote.get("span") == LAYOUT_A["span"] \
        and remote.get("hidden") == [] and remote.get("lastDeck") == "" \
        and int(remote.get("at") or 0) == LAYOUT_A["at"]
    T("读回 layout 与写入完全一致", r["status"] == 200 and len(rows) == 1 and same,
      "HTTP %s rows=%d" % (r["status"], len(rows)))

    # 再次写入 → updated_at 必须递增（LWW 依赖 UPDATE 触发器）
    time.sleep(1.2)
    body = {"sid": sid, "layout": dict(LAYOUT_B)}
    r = rest("POST", "stage_prefs?on_conflict=sid", token=tok, body=body,
             prefer=upsert_headers())
    r2 = rest("GET", own_get, token=tok)
    rows2 = r2["json"] if isinstance(r2["json"], list) else []
    updated2 = ts_ms((rows2[0] or {}).get("updated_at")) if rows2 else 0
    remote2 = (rows2[0] or {}).get("layout") if rows2 else None
    T("upsert 更新 layout 生效（order/hidden/lastDeck 更新）",
      r["status"] in (200, 201, 204) and len(rows2) == 1
      and isinstance(remote2, dict) and remote2.get("hidden") == ["timer"]
      and remote2.get("lastDeck") == "verifytestdeck",
      "HTTP %s rows=%d" % (r["status"], len(rows2)))
    T("updated_at 随写入递增（LWW 关键，触发器生效）",
      updated1 > 0 and updated2 > updated1,
      "delta_ms=%d" % (updated2 - updated1))

    # 仅本人：写入非本人 sid 会被 with check 拒绝（不涉及任何真实账号）
    other_sid = "9999000000"   # 合成 sid（不属于任何人；仅用于 RLS 负向断言）
    r = rest("POST", "stage_prefs?on_conflict=sid", token=tok,
             body={"sid": other_sid, "layout": {"v": 1, "at": 1}}, prefer=upsert_headers())
    T("写入非本人 sid 的 stage_prefs 被拒（401/403，with check auth_sid()=sid）",
      r["status"] in (401, 403), "HTTP %s" % r["status"])
    # 第二会话（同 sid）看到同一行（同账号多设备语义）；非本人行仍不可见
    r = rest("GET", own_get, token=qa)
    rows = r["json"] if isinstance(r["json"], list) else []
    T("测试身份第二会话看到本账号 stage_prefs（同 sid 多设备）",
      r["status"] == 200 and len(rows) == 1, "HTTP %s rows=%d" % (r["status"], len(rows)))
    r = rest("GET", "stage_prefs?select=layout,updated_at&sid=eq." + urllib.parse.quote(other_sid), token=tok)
    rows = r["json"] if isinstance(r["json"], list) else []
    T("查询非本人 sid 的 stage_prefs → []（RLS 仅本人）",
      (r["status"] == 200 and rows == []) or r["status"] in (401, 403),
      "HTTP %s rows=%s" % (r["status"], len(rows) if isinstance(rows, list) else "?"))
    # 未授权 DELETE：契约无 DELETE 策略 → 删除应被拒/不生效（数据仍可由超级用户清理）
    r = rest("DELETE", "stage_prefs?sid=eq." + urllib.parse.quote(sid), token=tok)
    r2 = rest("GET", own_get, token=tok)
    rows2 = r2["json"] if isinstance(r2["json"], list) else []
    T("stage_prefs 无 DELETE 策略：删除不生效（行仍在）",
      (r["status"] in (401, 403, 204, 200)) and len(rows2) == 1,
      "delete HTTP %s rows_after=%d" % (r["status"], len(rows2)))


# ------------------------------------------------------------------ main
def main():
    print("=== 0. 准备：测试身份登录 + 第二测试会话 + 预清理 ===")
    login_test_identity()
    T("测试身份 class_verify 登录成功（token 不打印）", bool(MEM["test_token"]))
    create_qa_session()
    T("测试身份第二会话创建成功（不涉及真实账号；finally 删除该会话行）",
      bool(MEM["qa_token"]))
    preclean()
    T("预清理完成（测试标记行/测试身份 stage_prefs）", True)

    print("\n=== 1. schema 与迁移文件一致性（information_schema / pg_catalog） ===")
    check_schema()

    print("\n=== 2. 无 token（anon 无身份）行为 ===")
    check_no_token()

    print("\n=== 3. water / water_room：upsert 幂等 / 读删 / 班级共享 ===")
    check_water_shared()

    print("\n=== 4. stage_prefs：仅本人读写 / layout 读回 / updated_at LWW ===")
    check_stage_prefs()

    print("\n=== 5. 清理与残留复核 ===")
    cleanup()
    verify_cleanup()

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["ok"])
    print("\n%s（%d/%d）" % ("VERIFY PASS" if passed == total else "VERIFY FAIL",
                            passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # 任何异常/提前退出都保证清理测试行（重复删除幂等）
        try:
            cleanup()
        except Exception:  # noqa: BLE001
            pass
