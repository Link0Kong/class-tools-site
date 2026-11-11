# -*- coding: utf-8 -*-
"""CloudBase 数据审计（第 4 步：函数权限/时效/修正查询；只读）。"""
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


def show(title, sql, maxrows=80, widths=None):
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


show("site_assets/site_config 列", """
select table_name, column_name, data_type from information_schema.columns
where table_schema='public' and table_name in ('site_assets','site_config')
order by 1, ordinal_position
""", widths=[20, 20, 24])

show("service_health 时效", """
select id, status,
       to_timestamp(checked_at/1000) as checked,
       round(extract(epoch from (now() - to_timestamp(checked_at/1000)))/60)::int as age_min
from public.service_health order by age_min desc
""", widths=[22, 8, 24, 8])

show("marks 孤儿（按 sid）", """
select count(*) as orphan from public.marks m
where m.seat not in (select c.sid from private.class_ids c)
""")

show("marks seat 样例（脱敏长度）", """
select kind, length(seat) as seat_len, count(*) n from public.marks group by 1,2 order by 1
""", widths=[10, 8, 6])

show("userdata ids 分类", """
select count(*) total,
  count(*) filter (where id in (select sid from private.class_ids)) known,
  count(*) filter (where id not in (select sid from private.class_ids)) unknown
from public.userdata
""", widths=[8, 8, 8])

show("函数 EXECUTE 授权（anon/public）", """
select p.proname as fn,
       pg_get_function_identity_arguments(p.oid) as args,
       coalesce(array_to_string(p.proacl, ' '), '(default)') as acl
from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public'
order by p.proname
""", maxrows=40, widths=[30, 40, 90])

show("函数是否有 SECURITY DEFINER", """
select p.proname as fn, p.prosecdef as secdef, p.proowner::regrole::text as owner
from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' order by 1
""", maxrows=40, widths=[34, 6, 18])

show("site_assets 数据行", """
select id, updated_at, octet_length(payload::text) as payload_len from public.site_assets
""", widths=[20, 24, 12])

show("notices 老数据/可见数据量", """
select count(*) filter (where not coalesce(archived,false)) as visible,
       count(*) filter (where coalesce(archived,false)) as archived,
       count(*) filter (where not coalesce(archived,false) and ts < 1794000000000) as visible_older_1d,
       count(*) filter (where not coalesce(archived,false) and length(coalesce(body,''))>300000) as visible_big
from public.notices
""", widths=[8, 8, 14, 8])

show("visits 老数据", """
select count(*) filter (where ts < 1793000000000) old_rows, count(*) n from public.visits
""", widths=[8, 6])

print("\nDONE")
