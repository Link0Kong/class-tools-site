# -*- coding: utf-8 -*-
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tmp_sql_exec import exec_sql


def run(sql):
    c, o = exec_sql(sql)
    d = (o or {}).get("data") or {}
    out = []
    for r in d.get("Rows") or []:
        try:
            out.append(json.loads(r))
        except Exception:
            out.append(r)
    return c, d.get("Columns"), out


print("== ppt_agent 心跳 ==")
c, cols, rows = run("select id, body::text, meta::text, updated_at::text from public.site_assets where id='ppt_agent'")
print("rc", c)
for r in rows:
    print([str(x)[:1200] for x in r])

print("\n== notices 可见正文总字节 ==")
c, cols, rows = run("""
select count(*) as visible,
       sum(length(coalesce(body,''))) as body_bytes,
       sum(length(coalesce(title,''))) as title_bytes,
       sum(length(coalesce(attachments,''))) as att_bytes
from public.notices where archived = false
""")
print(cols, rows)

print("\n== notices 最大可见 5 条（不含正文）==")
c, cols, rows = run("""
select id, ts, length(coalesce(body,'')) as body_len, length(coalesce(attachments,'')) as att_len
from public.notices where archived=false order by body_len desc limit 5
""")
print(cols, rows)

print("\n== 附件外置 URL 统计（body 中 /att/）==")
c, cols, rows = run("select count(*) from public.notices where body like '%/att/%'")
print(rows)

print("\n== 可见通知时间跨度 ==")
c, cols, rows = run("select min(ts), max(ts) from public.notices where archived=false")
print(rows)
