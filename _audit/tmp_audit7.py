# -*- coding: utf-8 -*-
"""CloudBase 审计（第 7 步：遗留账号/体积汇总，脱敏）。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tmp_sql_exec import exec_sql  # noqa: E402


def run(sql):
    c, o = exec_sql(sql)
    d = (o or {}).get("data") or {}
    out = []
    for r in d.get("Rows") or []:
        try:
            out.append(json.loads(r))
        except Exception:
            out.append(r)
    return out


print("== 遗留非标准账号 id（脱敏：只给数量/长度分布） ==")
print(run("""
select 'userdata' as t,
  count(*) filter (where id ~ '^[0-9]{10}$') as std_10,
  count(*) filter (where id !~ '^[0-9]{10}$') as legacy,
  min(length(id)) as min_len, max(length(id)) as max_len
from public.userdata
union all
select 'fitrecs', count(*) filter (where acc ~ '^[0-9]{10}$'), count(*) filter (where acc !~ '^[0-9]{10}$'),
  min(length(acc)), max(length(acc)) from public.fitrecs
union all
select 'marks', count(*) filter (where seat ~ '^[0-9]{10}$'), count(*) filter (where seat !~ '^[0-9]{10}$'),
  min(length(seat)), max(length(seat)) from public.marks
union all
select 'visits', count(*) filter (where sid ~ '^[0-9]{10}$'), count(*) filter (where sid !~ '^[0-9]{10}$'),
  min(length(sid)), max(length(sid)) from public.visits
"""))

print("\n== 数据库总大小 / 各表大小 ==")
print(run("""
select pg_size_pretty(sum(pg_total_relation_size(c.oid))) as db_total from pg_class c
join pg_namespace n on n.oid=c.relnamespace where n.nspname in ('public','private') and c.relkind='r'
"""))

print("\n== class_ids 一致性（脱敏） ==")
print(run("""
select count(*) total,
       count(*) filter (where is_test) test_rows,
       count(*) filter (where is_admin) admins,
       count(*) filter (where sid ~ '^[0-9]{10}$') sid_std
from private.class_ids
"""))

print("\n== marker: 两个软删测试 deck 是否仍可见 ==")
print(run("""
select id, title, deleted, status from public.ppt_decks
where deleted = false order by created_at desc
"""))

print("\n== client_diag 未分析/旧行 ==")
print(run("""
select status, count(*), min(created_at)::text, max(created_at)::text
from public.client_diag group by status
"""))
