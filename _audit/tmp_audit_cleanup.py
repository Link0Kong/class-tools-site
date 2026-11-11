# -*- coding: utf-8 -*-
"""CloudBase 审计整改（有界写操作）：删测试表/清理过期登录任务/回收 debug_headers 执行权。

只动明确是测试垃圾/过期安全数据的内容；真实业务表只读不删。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tmp_sql_exec import exec_sql  # noqa: E402


def run(label, sql):
    code, out = exec_sql(sql)
    ok = code == 0 and isinstance(out, dict) and not out.get("error")
    print(("[ok] " if ok else "[FAIL] ") + label + "  rc=%s" % code)
    if not ok:
        print("   ", str(out)[:600])
    else:
        d = out.get("data") or {}
        print("    affected=%s time_ms=%s" % (d.get("AffectedRows"), d.get("ExecutionTimeMs")))
    return ok


# 1) 测试遗留表（private schema，无任何代码引用；test_zz2 仅 1 行 id）
run("DROP private.test_zz", "drop table if exists private.test_zz;")
run("DROP private.test_zz2", "drop table if exists private.test_zz2;")

# 2) 过期/完成登录任务（含 PGP 密文字段；保留 1 小时内新任务）
run("清理过期 login_jobs", """
delete from public.login_jobs
where created_at < (extract(epoch from now())*1000 - 3600*1000)::bigint
  and status in ('done','failed','expired','cancelled');
""")

# 3) debug_headers：返回请求头的调试函数，线上无任何调用方 → 收回 anon/authenticated 执行权（保留 owner 可用）
run("REVOKE debug_headers", "revoke execute on function public.debug_headers() from public, anon, authenticated;")

# 4) 复核
for label, sql in [
    ("复核 login_jobs", "select count(*) from public.login_jobs;"),
    ("复核 debug_headers 权限", """
select p.proname, case when p.proacl is null then '(default)' else array_to_string(p.proacl,' ') end
from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname='debug_headers';
"""),
    ("复核 private 表", """
select n.nspname||'.'||c.relname as t from pg_class c join pg_namespace n on n.oid=c.relnamespace
where n.nspname='private' and c.relkind='r' order by 1;
"""),
]:
    code, out = exec_sql(sql)
    d = (out or {}).get("data") or {}
    print("\n## " + label)
    for r in d.get("Rows") or []:
        print("  " + str(r)[:400])
print("\nDONE")
