# -*- coding: utf-8 -*-
"""CloudBase 审计（第 5 步：敏感函数定义/剩下列表/site_assets；只读）。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tmp_sql_exec import exec_sql  # noqa: E402


def q(sql):
    code, out = exec_sql(sql)
    if code != 0 or not isinstance(out, dict):
        return None, out
    d = out.get("data") or {}
    rows = []
    for raw in d.get("Rows") or []:
        try:
            rows.append(json.loads(raw))
        except Exception:
            rows.append([raw])
    return {"cols": d.get("Columns") or [], "rows": rows}, None


def show(title, sql, maxrows=60, widths=None):
    print("\n### " + title)
    res, err = q(sql)
    if err is not None:
        print("  ERR:", str(err)[:400])
        return None
    print("  cols:", res["cols"], " rows:", len(res["rows"]))
    for r in res["rows"][:maxrows]:
        r = [("" if v is None else str(v)) for v in r]
        if widths:
            r = [x[:w] for x, w in zip(r, widths)]
        print("  " + " | ".join(r))
    if len(res["rows"]) > maxrows:
        print("  ... %d more" % (len(res["rows"]) - maxrows))
    return res


show("site_assets 数据", """
select id, updated_at, octet_length(body::text) as body_len,
       round(extract(epoch from (now()-updated_at))/3600)::int as age_hours
from public.site_assets order by id
""", widths=[20, 24, 10, 10])

show("剩余函数（名称/权限）", """
select p.proname, pg_get_function_identity_arguments(p.oid) as args,
       case when p.proacl is null then '(default)' else array_to_string(p.proacl,' ') end as acl
from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname in
 ('tt_login_enqueue','tt_login_status','class_verify','class_members','class_set_role',
  'class_whoami','class_league','diag_agent_info','debug_headers','health_rpc')
order by 1
""", widths=[24, 40, 100])

show("debug_headers 定义", """
select pg_get_functiondef(p.oid) as def from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname='debug_headers' limit 1
""", maxrows=1, widths=[600])

show("diag_agent_info 定义", """
select pg_get_functiondef(p.oid) as def from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname='diag_agent_info' limit 1
""", maxrows=1, widths=[600])

show("tt_login_status 定义（是否泄露密文/密码）", """
select pg_get_functiondef(p.oid) as def from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname='tt_login_status' limit 1
""", maxrows=1, widths=[900])

show("tt_login_enqueue 定义", """
select pg_get_functiondef(p.oid) as def from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname='tt_login_enqueue' limit 1
""", maxrows=1, widths=[900])

print("\nDONE")
