# -*- coding: utf-8 -*-
"""CloudBase 数据审计（第 1 步：结构/容量/权限盘点；只读）。"""
import json
import sys
import os

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


def show(title, sql, maxrows=80, widths=None):
    print("\n### " + title)
    res, err = q(sql)
    if err is not None:
        print("  ERR:", str(err)[:500])
        return None
    print("  cols:", res["cols"], " rows:", len(res["rows"]))
    for r in res["rows"][:maxrows]:
        r = [("" if v is None else str(v)) for v in r]
        if widths:
            r = [x[:w] for x, w in zip(r, widths)]
        print("  " + " | ".join(r))
    if len(res["rows"]) > maxrows:
        print("  ... %d more rows" % (len(res["rows"]) - maxrows))
    return res


show("public/private 表容量", """
select n.nspname as schema, c.relname as tbl, t.n_live_tup as live_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) as total_size,
       c.relrowsecurity as rls, c.relforcerowsecurity as force_rls
from pg_class c
join pg_namespace n on n.oid=c.relnamespace
left join pg_stat_user_tables t on t.relid=c.oid
where c.relkind='r' and n.nspname in ('public','private')
order by pg_total_relation_size(c.oid) desc, 1,2
""", widths=[10, 24, 10, 12, 5, 5])

show("anon 表级授权（是否有越权写）", """
select table_name, grantee, string_agg(privilege_type, ',' order by privilege_type) as privs
from information_schema.role_table_grants
where table_schema='public' and grantee in ('anon','authenticated','public')
group by 1,2 order by 1,2
""", widths=[30, 16, 60])

show("public RLS 策略", """
select tablename, policyname, cmd, roles::text as roles,
       coalesce(qual,'') as using_expr, coalesce(with_check,'') as check_expr
from pg_policies where schemaname='public' order by 1,2
""", widths=[22, 30, 10, 20, 70, 50])

show("private 表列", """
select table_name, column_name, data_type, is_nullable
from information_schema.columns where table_schema='private'
order by 1, ordinal_position
""", widths=[20, 26, 22, 8])

show("public 关键表列", """
select table_name, column_name, data_type
from information_schema.columns
where table_schema='public' and table_name in
 ('login_jobs','class_sessions','agent_keys','site_assets','site_config','service_health',
  'client_diag','diag_analysis','repair_tasks','polls','poll_votes','ppt_decks','ppt_upload_chunks',
  'power','power_history','userdata','notices','marks','visits','fitrecs','homework','feedback')
order by 1, ordinal_position
""", widths=[20, 26, 24])

show("private 数据量", """
select 'class_ids' t, count(*) n, count(*) filter (where is_test) test_rows from private.class_ids
union all select 'class_sessions', count(*), count(*) filter (where expires_at < now()) from private.class_sessions
""")

print("\nDONE")
