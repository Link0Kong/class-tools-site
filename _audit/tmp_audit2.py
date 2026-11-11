# -*- coding: utf-8 -*-
"""CloudBase 数据审计（第 2 步：数据质量/垃圾数据；只读）。"""
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


show("剩余表列定义", """
select table_name, column_name, data_type from information_schema.columns
where table_schema='public' and table_name in
 ('polls','poll_votes','ppt_decks','ppt_upload_chunks','power','power_history','userdata',
  'notices','marks','visits','service_health','site_assets','site_config','login_jobs','homework','roster')
order by 1, ordinal_position
""", widths=[22, 24, 22])

show("private 数据量 / 过期会话 / 测试表", """
select 'class_ids' as t, count(*) as n, count(*) filter (where is_test) as extra from private.class_ids
union all select 'class_sessions_all', count(*), count(*) filter (where expires_at < now()) from private.class_sessions
union all select 'class_league', count(*), 0 from private.class_league
union all select 'class_audience', count(*), 0 from private.class_audience
union all select 'test_zz', count(*), 0 from private.test_zz
union all select 'test_zz2', count(*), 0 from private.test_zz2
""")

show("notices 概况", """
select count(*) as total,
       count(*) filter (where coalesce(archived,false)) as archived,
       count(*) filter (where coalesce(hidden,false)) as hidden,
       count(*) filter (where edited_at is not null) as edited,
       count(*) filter (where length(coalesce(body,'')) > 300000) as big_body_300k,
       round(avg(length(coalesce(body,''))))::int as avg_body,
       max(length(coalesce(body,''))) as max_body,
       min(ts) as min_ts, max(ts) as max_ts
from public.notices
""", widths=[8, 9, 8, 8, 12, 10, 10, 16, 16])

show("notices 最老/最新与超期", """
select id, ts, length(coalesce(body,'')) as body_len, coalesce(archived,false) as archived,
       coalesce(hidden,false) as hidden, audience
from public.notices order by ts asc limit 5
""", widths=[40, 16, 9, 8, 7, 10])

show("homework 概况", """
select count(*) as total, count(*) filter (where coalesce(archived,false)) as archived,
       count(*) filter (where coalesce(done,false)) as done,
       count(*) filter (where length(coalesce(attachments,''))>500000) as big_att,
       min(ts) as min_ts, max(ts) as max_ts
from public.homework
""", widths=[8, 9, 8, 8, 16, 16])

show("marks 概况（kind 分布/孤儿/重复）", """
select kind, count(*) as n, count(*) filter (where val) as true_n
from public.marks group by kind order by kind
""", widths=[20, 8, 8])

show("marks 孤儿 seat（不在 class_ids）", """
select count(*) as orphan from public.marks m
where not exists (select 1 from private.class_ids c where c.seat = m.seat)
""")

show("userdata 概况", """
select count(*) as rows, count(*) filter (where blob is null or length(blob) < 10) as empty_blob,
       round(avg(length(blob)))::int as avg_len, max(length(blob)) as max_len,
       min(ts) as min_ts, max(ts) as max_ts
from public.userdata
""", widths=[8, 8, 8, 8, 16, 16])

show("userdata 孤儿 id（不在 class_ids.sid）", """
select count(*) as orphan from public.userdata u
where not exists (select 1 from private.class_ids c where c.sid = u.id)
""")

show("fitrecs 概况", """
select count(*) as total, count(*) filter (where coalesce(arch,false)) as archived,
       count(*) filter (where length(coalesce(data,''))>100000) as big,
       count(*) filter (where acc not in (select sid from private.class_ids)) as orphan_acc,
       max(ts) as max_ts
from public.fitrecs
""", widths=[8, 9, 6, 10, 16])

show("visits 概况", """
select count(*) as total, count(distinct sid) as users,
       count(*) filter (where ts > (extract(epoch from now())*1000)::bigint) as future_ts,
       max(ts) as max_ts, min(ts) as min_ts
from public.visits
""", widths=[8, 8, 9, 16, 16])

show("power 17 间房与更新时效", """
select count(*) as rooms, min(updated_at) as oldest, max(updated_at) as newest,
       count(*) filter (where updated_at < now() - interval '2 hours') as stale_2h,
       count(*) filter (where updated_at < now() - interval '1 day') as stale_1d
from public.power
""", widths=[6, 24, 24, 10, 10])

show("power 房间名列表", """
select roomverify, updated_at from public.power order by roomverify
""", maxrows=25, widths=[24, 24])

show("power_history 概况", """
select count(*) as total, count(distinct roomverify) as rooms,
       count(*) filter (where ts > now()) as future_ts,
       count(*) filter (where ts < now() - interval '35 days') as older_35d,
       max(ts) as max_ts, min(ts) as min_ts
from public.power_history
""", widths=[8, 6, 10, 10, 24, 24])

show("power_history 重复采样/孤儿房号", """
select count(*) as dup_room_ts from (
  select roomverify, ts from public.power_history group by 1,2 having count(*)>1
) t
""")

show("power_history 每房采样数（尾部 5 行）", """
select roomverify, count(*) as n, min(ts) as first_ts, max(ts) as last_ts
from public.power_history group by roomverify order by n asc limit 20
""", widths=[22, 6, 24, 24])

show("ppt_decks 状态分布", """
select status, coalesce(deleted,false) as deleted, count(*) as n,
       min(created_at) as oldest, max(created_at) as newest
from public.ppt_decks group by 1,2 order by 1,2
""", widths=[10, 8, 5, 24, 24])

show("ppt_decks 卡死/可见异常", """
select id, title, status, coalesce(deleted,false) as deleted,
       to_timestamp(created_at/1000) as created
from public.ppt_decks
where (deleted = false and status <> 'ready')
   or (status in ('uploading','queued') and to_timestamp(created_at/1000) < now() - interval '1 day')
order by created_at desc limit 20
""", widths=[24, 26, 10, 8, 22])

show("ppt_upload_chunks 残留", """
select count(*) as rows, count(distinct deck_id) as decks,
       count(*) filter (where deck_id not in (select id from public.ppt_decks)) as orphan_deck,
       max(ts) as max_ts
from public.ppt_upload_chunks
""", widths=[6, 6, 10, 20])

show("ppt_upload_chunks 残留明细（不含 data）", """
select deck_id, idx, ts, length(data) as data_len from public.ppt_upload_chunks
order by ts desc limit 10
""", widths=[26, 4, 20, 10])

show("agent_keys", """
select id, host, version, seen_at, length(pubkey) as pubkey_len, created_at
from public.agent_keys order by created_at desc
""", widths=[20, 14, 10, 14, 10, 24])

show("login_jobs 列与状态", """
select count(*) as rows, max(created_at) as newest, min(created_at) as oldest
from public.login_jobs
""", widths=[6, 24, 24])

show("service_health 列数据（每服务最新行/时效）", """
select id, status, updated_at, latency_ms
from public.service_health order by id, updated_at desc limit 40
""", widths=[26, 8, 24, 8])

show("site_assets / site_config 时效", """
select 'asset:'||id as k, length(payload::text) as payload_len, updated_at::text as upd
from public.site_assets
union all
select 'config:'||id, length(value::text), updated_at::text from public.site_config
""", widths=[24, 10, 24])

show("client_diag 状态/时效", """
select coalesce(status,'(null)') as status, count(*) as n,
       max(created_at) as newest, min(created_at) as oldest
from public.client_diag group by 1 order by n desc
""", widths=[10, 6, 24, 24])

show("diag_analysis / repair_tasks 状态", """
select 'analysis' as t, coalesce(status,'(null)') as status, count(*) as n from public.diag_analysis group by 2
union all
select 'repair', coalesce(status,'(null)'), count(*) from public.repair_tasks group by 2
""", widths=[10, 12, 6])

show("roster 遗留行", """
select count(*) as rows, length(coalesce(roster,'')) as roster_len from public.roster group by 2
""")

print("\nDONE")
