# -*- coding: utf-8 -*-
"""独立复核 cloud-backend 新迁移的表/RLS（只读）。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tmp_sql_exec import exec_sql  # noqa: E402


def run(label, sql):
    c, o = exec_sql(sql)
    d = (o or {}).get("data") or {}
    print("\n## " + label + "  rc=%s" % c)
    cols = d.get("Columns") or []
    print("cols:", cols)
    for r in d.get("Rows") or []:
        try:
            row = json.loads(r)
        except Exception:
            row = [r]
        print("  " + " | ".join("" if v is None else str(v)[:120] for v in row[:8]))


run("water/water_room/stage_prefs 约束", """
select c.relname, con.conname, pg_get_constraintdef(con.oid) as def
from pg_constraint con join pg_class c on c.oid=con.conrelid
join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relname in ('water','water_room','stage_prefs')
order by 1,2
""")

run("RLS 策略", """
select tablename, policyname, cmd, roles::text as roles,
       coalesce(qual,'') as using_expr, coalesce(with_check,'') as check_expr
from pg_policies where schemaname='public' and tablename in ('water','water_room','stage_prefs')
order by 1,2
""")

run("表级授权", """
select table_name, grantee, string_agg(privilege_type, ',' order by privilege_type)
from information_schema.role_table_grants
where table_schema='public' and table_name in ('water','water_room','stage_prefs') and grantee in ('anon','authenticated')
group by 1,2 order by 1,2
""")

run("stage_prefs 触发器", """
select event_object_table, trigger_name, action_timing, event_manipulation
from information_schema.triggers
where trigger_schema='public' and event_object_table in ('stage_prefs','water','water_room')
order by 1,2
""")

run("RLS 是否开启", """
select c.relname, c.relrowsecurity, c.relforcerowsecurity from pg_class c
join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relname in ('water','water_room','stage_prefs')
""")
print("\nDONE")
