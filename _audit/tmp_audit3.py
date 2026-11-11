# -*- coding: utf-8 -*-
"""CloudBase 数据审计（第 3 步：时效/关键表/遗留问题复核；只读）。"""
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


show("service_health 列", """
select column_name, data_type from information_schema.columns
where table_schema='public' and table_name='service_health' order by ordinal_position
""", widths=[20, 30])

show("service_health 全部行", """
select * from public.service_health order by 1 limit 40
""", maxrows=30, widths=[28, 8, 40, 24])

show("site_assets 列/数据", """
select id, updated_at, length(payload::text) as payload_len from public.site_assets
union all select 'config:'||id, updated_at, length(value::text) from public.site_config
""", widths=[20, 24, 10])

show("marks 按 kind", """
select kind, count(*) n, count(*) filter (where val) t from public.marks group by kind
""")

show("marks 孤儿（修正写法）", """
select count(*) as orphan from public.marks m
where m.seat not in (select c.seat::text from private.class_ids c)
""")

show("userdata/fitrecs 非名单账号行数", """
select 'userdata' t, count(*) n,
  count(*) filter (where id = '3260799999') test_id,
  count(*) filter (where id = '3260707024') admin_id
from public.userdata
union all
select 'fitrecs', count(*),
  count(*) filter (where acc = '3260799999'),
  count(*) filter (where acc = '3260707024')
from public.fitrecs
union all
select 'marks', count(*),
  count(*) filter (where seat = '3260799999'),
  count(*) filter (where seat = '3260707024')
from public.marks
""", widths=[10, 6, 8, 8])

show("login_jobs 过期/旧", """
select id, status, created_at, expires_at, length(coalesce(pwd_pgp,'')) as pwd_len
from public.login_jobs order by created_at desc limit 5
""", widths=[24, 8, 16, 16, 8])

show("diag_analysis 旧 new 行", """
select status, count(*) n, min(to_timestamp(ts/1000)) as oldest, max(to_timestamp(ts/1000)) as newest
from public.diag_analysis group by status
""", widths=[8, 5, 24, 24])

show("client_diag 旧行", """
select min(created_at) as oldest, max(created_at) as newest, count(*) n from public.client_diag
""", widths=[24, 24, 5])

show("private.class_ids 统计（脱敏）", """
select count(*) total, count(*) filter (where is_test) test_rows,
       count(*) filter (where is_admin) admins,
       count(*) filter (where role is not null and role <> '') with_role,
       count(*) filter (where badge is not null and badge <> '') with_badge
from private.class_ids
""", widths=[8, 8, 8, 8, 8])

show("private.class_sessions 时效分布", """
select count(*) n,
  count(*) filter (where expires_at < now()) expired,
  count(*) filter (where expires_at >= now()) active,
  min(created_at) as oldest_created
from private.class_sessions
""", widths=[8, 8, 8, 24])

show("public 表总量/公开只读检查：无 token 访问 roster/notices", """
select 1 as x
""")

show("notices 附件内嵌 vs 外置统计", """
select count(*) n,
  count(*) filter (where body like '%data:application/%' or body like '%data:image/%' or body like '%data:audio/%' or body like '%data:video/%') as has_data_uri,
  count(*) filter (where body like '%/att/%') as external_att_url,
  count(*) filter (where length(coalesce(attachments,'')) > 0) as has_attachments_col
from public.notices
""", widths=[8, 12, 12, 12])

print("\nDONE")
