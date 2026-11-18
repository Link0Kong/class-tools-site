#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_schema.py — CloudBase PostgreSQL 全量结构只读导出（P0）

从 CloudBase（env ``tool-d4gosudok46e0e081``，PG 17.11）通过只读 SQL 通道读取
``pg_catalog``，生成可导入到 ECS PostgreSQL 18 的结构产物：

    roles.sql           anon / authenticated / service_role（NOLOGIN，按线上属性）；
                        authenticator 由部署方创建（本文件只留说明，不含密码）
    schema.sql          CREATE SCHEMA private → 扩展(pgcrypto in public) → 序列
                        → 表(列/类型/NOT NULL) → 函数(52 个自有函数，先
                        set check_function_bodies=false) → 列默认值 → 约束
                        (PK/UNIQUE/FK/CHECK) → 非约束索引 → RLS ENABLE → 触发器
                        → 策略(73) → 授权(表/序列/函数/schema) → 序列 setval
    schema_manifest.json  结构计数 + 每表列定义 + 与 catalog 的交叉校验结果

约束
====
- **只读**：所有远端操作都是 ``select``（经 ``tcb_sql.TcbSqlClient`` 白名单校验）。
- 结构计数与 catalog 不一致时**直接报错**，绝不产出半可信 schema.sql。
- 产物目录私有（默认 ``C:\\briefdesk\\data\\cloudbase_migration\\<YYYYMMDD-HHMM>\\``），
  **不进仓库、不打印数据**；本脚本只打印对象计数。

用法::

    python deploy/migration/export_schema.py            # 复用最新产物目录（无则新建）
    python deploy/migration/export_schema.py --new-run  # 强制新建时间戳目录
    python deploy/migration/export_schema.py --out D:\\path\\run1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tcb_sql import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT,
    TcbSqlClient,
    TcbSqlError,
    human_bytes,
    new_output_dir,
    qualified_name,
    quote_ident,
    resolve_output_dir,
    sha256_file,
    utc_now_iso,
    write_json,
)

SCHEMAS = ("public", "private")
SCHEMA_IN = "n.nspname in ($$public$$, $$private$$)"
DEPLOY_ROLES = ("anon", "authenticated", "service_role")
PUBLIC = "PUBLIC"
# 生成 DDL 时只复刻这些被授权者；CloudBase 平台内部角色（cloudbase_*）不迁移
GRANT_ROLES = ("PUBLIC",) + DEPLOY_ROLES


class ExportSchemaError(RuntimeError):
    """结构导出失败（计数不一致 / catalog 异常）。"""


# ---------------------------------------------------------------------------
# catalog 查询
# ---------------------------------------------------------------------------

def _q_meta(cli: TcbSqlClient) -> dict:
    return cli.fetch_json(
        """
        select json_build_object(
          'captured_at', now()::text,
          'pg_version', version(),
          'server_version_num', current_setting('server_version_num'),
          'database', current_database(),
          'current_user', current_user,
          'search_path', current_setting('search_path'),
          'timezone', current_setting('TimeZone'),
          'datestyle', current_setting('DateStyle'),
          'server_encoding', current_setting('server_encoding'),
          'standard_conforming_strings', current_setting('standard_conforming_strings'),
          'database_locale', (
            select json_build_object('encoding', pg_encoding_to_char(encoding),
                                     'collate', datcollate, 'ctype', datctype,
                                     'provider', datlocprovider::text,
                                     'icu_locale', datlocale)
            from pg_database where datname = current_database()),
          'roles', (
            select coalesce(json_agg(json_build_object(
              'name', r.rolname, 'super', r.rolsuper, 'login', r.rolcanlogin,
              'inherit', r.rolinherit, 'createrole', r.rolcreaterole,
              'createdb', r.rolcreatedb, 'bypassrls', r.rolbypassrls,
              'connlimit', r.rolconnlimit) order by r.rolname), '[]')
            from pg_roles r
            where r.rolname in ($$anon$$, $$authenticated$$, $$service_role$$, $$authenticator$$)),
          'schemas', (
            select coalesce(json_agg(json_build_object(
              'name', n.nspname, 'owner', pg_get_userbyid(n.nspowner),
              'acl', n.nspacl::text) order by n.nspname), '[]')
            from pg_namespace n where n.nspname in ($$public$$, $$private$$)),
          'extensions', (
            select coalesce(json_agg(json_build_object(
              'name', e.extname, 'schema', n.nspname, 'version', e.extversion)
              order by e.extname), '[]')
            from pg_extension e join pg_namespace n on n.oid = e.extnamespace),
          'event_triggers', (
            select coalesce(json_agg(json_build_object(
              'name', e.evtname, 'event', e.evtevent,
              'fn_schema', (select n.nspname from pg_namespace n join pg_proc p
                            on p.pronamespace = n.oid where p.oid = e.evtfoid),
              'fn_name', (select p.proname from pg_proc p where p.oid = e.evtfoid),
              'enabled', e.evtenabled::text) order by e.evtname), '[]')
            from pg_event_trigger e),
          'publications', (select count(*) from pg_publication),
          'subscriptions', (select count(*) from pg_subscription),
          'db_role_settings', (
            select coalesce(json_agg(json_build_object(
              'role', case when s.setrole = 0 then 'ALL' else pg_get_userbyid(s.setrole) end,
              'database', (select datname from pg_database d where d.oid = s.setdatabase),
              'config', s.setconfig)), '[]')
            from pg_db_role_setting s),
          'default_acls', (
            select coalesce(json_agg(json_build_object(
              'role', pg_get_userbyid(d.defaclrole),
              'schema', case when d.defaclnamespace = 0 then null
                             else (select nspname from pg_namespace where oid = d.defaclnamespace) end,
              'objtype', d.defaclobjtype::text,
              'acl', d.defaclacl::text) order by 1, 2, 3), '[]')
            from pg_default_acl d)
        )::text
        """
    )


def _q_counts(cli: TcbSqlClient) -> dict:
    return cli.fetch_json(
        f"""
        select json_build_object(
          'tables_total', (select count(*) from pg_class cl join pg_namespace n
                           on n.oid = cl.relnamespace where {SCHEMA_IN} and cl.relkind = $$r$$),
          'tables_public', (select count(*) from pg_class cl join pg_namespace n
                            on n.oid = cl.relnamespace where n.nspname = $$public$$ and cl.relkind = $$r$$),
          'tables_private', (select count(*) from pg_class cl join pg_namespace n
                             on n.oid = cl.relnamespace where n.nspname = $$private$$ and cl.relkind = $$r$$),
          'columns', (select count(*) from pg_attribute a join pg_class cl on cl.oid = a.attrelid
                      join pg_namespace n on n.oid = cl.relnamespace
                      where {SCHEMA_IN} and cl.relkind = $$r$$ and a.attnum > 0 and not a.attisdropped),
          'sequences', (select count(*) from pg_class cl join pg_namespace n
                        on n.oid = cl.relnamespace where {SCHEMA_IN} and cl.relkind = $$S$$),
          'views', (select count(*) from pg_class cl join pg_namespace n
                    on n.oid = cl.relnamespace where {SCHEMA_IN} and cl.relkind in ($$v$$, $$m$$)),
          'functions_total', (select count(*) from pg_proc p join pg_namespace n
                              on n.oid = p.pronamespace where {SCHEMA_IN}),
          'functions_own', (select count(*) from pg_proc p join pg_namespace n
                            on n.oid = p.pronamespace where {SCHEMA_IN}
                            and not exists (select 1 from pg_depend d
                                            where d.objid = p.oid and d.deptype = $$e$$)),
          'functions_extension', (select count(*) from pg_proc p join pg_namespace n
                                  on n.oid = p.pronamespace where {SCHEMA_IN}
                                  and exists (select 1 from pg_depend d
                                              where d.objid = p.oid and d.deptype = $$e$$)),
          'functions_secdef_own', (select count(*) from pg_proc p join pg_namespace n
                                   on n.oid = p.pronamespace where {SCHEMA_IN} and p.prosecdef
                                   and not exists (select 1 from pg_depend d
                                                   where d.objid = p.oid and d.deptype = $$e$$)),
          'policies_total', (select count(*) from pg_policy po join pg_class cl
                             on cl.oid = po.polrelid join pg_namespace n
                             on n.oid = cl.relnamespace where {SCHEMA_IN}),
          'policies_public', (select count(*) from pg_policy po join pg_class cl
                              on cl.oid = po.polrelid join pg_namespace n
                              on n.oid = cl.relnamespace where {SCHEMA_IN} and 0 = any(po.polroles)),
          'triggers_user', (select count(*) from pg_trigger tg join pg_class cl
                            on cl.oid = tg.tgrelid join pg_namespace n
                            on n.oid = cl.relnamespace where {SCHEMA_IN} and not tg.tgisinternal),
          'triggers_internal', (select count(*) from pg_trigger tg join pg_class cl
                                on cl.oid = tg.tgrelid join pg_namespace n
                                on n.oid = cl.relnamespace where {SCHEMA_IN} and tg.tgisinternal),
          'indexes_total', (select count(*) from pg_index i join pg_class cl
                            on cl.oid = i.indrelid join pg_namespace n
                            on n.oid = cl.relnamespace where {SCHEMA_IN}),
          'indexes_nonconstraint', (select count(*) from pg_index i join pg_class cl
                                    on cl.oid = i.indrelid join pg_namespace n
                                    on n.oid = cl.relnamespace where {SCHEMA_IN}
                                    and not exists (select 1 from pg_constraint c
                                                    where c.conindid = i.indexrelid)),
          'constraints_primary', (select count(*) from pg_constraint co join pg_class cl
                                  on cl.oid = co.conrelid join pg_namespace n
                                  on n.oid = cl.relnamespace where {SCHEMA_IN} and co.contype = $$p$$),
          'constraints_unique', (select count(*) from pg_constraint co join pg_class cl
                                 on cl.oid = co.conrelid join pg_namespace n
                                 on n.oid = cl.relnamespace where {SCHEMA_IN} and co.contype = $$u$$),
          'constraints_foreign', (select count(*) from pg_constraint co join pg_class cl
                                  on cl.oid = co.conrelid join pg_namespace n
                                  on n.oid = cl.relnamespace where {SCHEMA_IN} and co.contype = $$f$$),
          'constraints_check', (select count(*) from pg_constraint co join pg_class cl
                                on cl.oid = co.conrelid join pg_namespace n
                                on n.oid = cl.relnamespace where {SCHEMA_IN} and co.contype = $$c$$),
          'rls_enabled_tables', (select count(*) from pg_class cl join pg_namespace n
                                 on n.oid = cl.relnamespace where {SCHEMA_IN}
                                 and cl.relkind = $$r$$ and cl.relrowsecurity),
          'rls_forced_tables', (select count(*) from pg_class cl join pg_namespace n
                                on n.oid = cl.relnamespace where {SCHEMA_IN}
                                and cl.relkind = $$r$$ and cl.relforcerowsecurity),
          'extension_count', (select count(*) from pg_extension),
          'event_triggers', (select count(*) from pg_event_trigger)
        )::text
        """
    )


def _q_relations(cli: TcbSqlClient) -> list:
    """表 + 序列（relkind r/S），含 ACL 展开。"""
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'name', cl.relname, 'kind', cl.relkind::text,
          'owner', pg_get_userbyid(cl.relowner),
          'rls', cl.relrowsecurity, 'force_rls', cl.relforcerowsecurity,
          'persistence', cl.relpersistence::text,
          'acl', (
            select coalesce(json_agg(json_build_object(
              'grantee', case when a.grantee = 0 then 'PUBLIC' else pg_get_userbyid(a.grantee) end,
              'privileges', (
                select json_agg(a2.privilege_type order by a2.privilege_type)
                from aclexplode(cl.relacl) a2 where a2.grantee = a.grantee))
              order by a.grantee), '[]')
            from (select distinct grantee from aclexplode(cl.relacl)) a)
        ) order by n.nspname, cl.relname), '[]')::text
        from pg_class cl join pg_namespace n on n.oid = cl.relnamespace
        where {SCHEMA_IN} and cl.relkind in ($$r$$, $$S$$)
        """
    )


def _q_columns(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'table', cl.relname, 'attnum', a.attnum,
          'name', a.attname, 'type', pg_catalog.format_type(a.atttypid, a.atttypmod),
          'notnull', a.attnotnull,
          'identity', nullif(a.attidentity::text, ''),
          'generated', nullif(a.attgenerated::text, ''),
          'default', pg_get_expr(ad.adbin, ad.adrelid),
          'collation', (
            select co.collname from pg_collation co
            where co.oid = a.attcollation
              and a.attcollation <> (select ty.typcollation from pg_type ty
                                     where ty.oid = a.atttypid))
        ) order by n.nspname, cl.relname, a.attnum), '[]')::text
        from pg_attribute a
        join pg_class cl on cl.oid = a.attrelid
        join pg_namespace n on n.oid = cl.relnamespace
        left join pg_attrdef ad on ad.adrelid = a.attrelid and ad.adnum = a.attnum
        where {SCHEMA_IN} and cl.relkind = $$r$$ and a.attnum > 0 and not a.attisdropped
        """
    )


def _q_constraints(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'table', cl.relname, 'name', co.conname,
          'type', co.contype::text, 'def', pg_get_constraintdef(co.oid),
          'validated', co.convalidated,
          'columns', (
            select json_agg(a.attname order by k.ord)
            from unnest(co.conkey) with ordinality k(attnum, ord)
            join pg_attribute a on a.attrelid = co.conrelid and a.attnum = k.attnum)
        ) order by n.nspname, cl.relname,
          case co.contype when $$p$$ then 1 when $$u$$ then 2 when $$f$$ then 3 else 4 end,
          co.conname), '[]')::text
        from pg_constraint co
        join pg_class cl on cl.oid = co.conrelid
        join pg_namespace n on n.oid = cl.relnamespace
        where {SCHEMA_IN} and co.contype in ($$p$$, $$u$$, $$f$$, $$c$$)
        """
    )


def _q_indexes(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'table', cl.relname,
          'name', ic.relname, 'def', pg_get_indexdef(i.indexrelid),
          'unique', i.indisunique, 'valid', i.indisvalid
        ) order by n.nspname, cl.relname, ic.relname), '[]')::text
        from pg_index i
        join pg_class ic on ic.oid = i.indexrelid
        join pg_class cl on cl.oid = i.indrelid
        join pg_namespace n on n.oid = cl.relnamespace
        where {SCHEMA_IN}
          and not exists (select 1 from pg_constraint c where c.conindid = i.indexrelid)
        """
    )


def _q_functions(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'name', p.proname, 'oid', p.oid,
          'identity', pg_get_function_identity_arguments(p.oid),
          'rettype', pg_catalog.format_type(p.prorettype, null),
          'language', l.lanname, 'secdef', p.prosecdef,
          'volatility', p.provolatile::text, 'proconfig', p.proconfig,
          'extension', exists(select 1 from pg_depend d
                              where d.objid = p.oid and d.deptype = $$e$$),
          'acl', (
            select coalesce(json_agg(json_build_object(
              'grantee', case when a.grantee = 0 then 'PUBLIC' else pg_get_userbyid(a.grantee) end,
              'privileges', (
                select json_agg(a2.privilege_type order by a2.privilege_type)
                from aclexplode(p.proacl) a2 where a2.grantee = a.grantee))
              order by a.grantee), '[]')
            from (select distinct grantee from aclexplode(p.proacl)) a)
        ) order by n.nspname, p.proname, p.oid), '[]')::text
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        join pg_language l on l.oid = p.prolang
        where {SCHEMA_IN}
        """
    )


def _q_function_defs(cli: TcbSqlClient, oids: list) -> dict:
    """pg_get_functiondef 单独取（一次查询，避免 meta 查询过大）。"""
    if not oids:
        return {}
    oid_list = ",".join(str(int(o)) for o in oids)
    rows = cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object('oid', p.oid, 'def', pg_get_functiondef(p.oid))
               order by p.oid), '[]')::text
        from pg_proc p where p.oid in ({oid_list})
        """
    )
    return {int(r["oid"]): r["def"] for r in rows}


def _q_triggers(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'table', cl.relname, 'name', tg.tgname,
          'internal', tg.tgisinternal, 'enabled', tg.tgenabled::text,
          'def', case when tg.tgisinternal then null else pg_get_triggerdef(tg.oid) end
        ) order by n.nspname, cl.relname, tg.tgname), '[]')::text
        from pg_trigger tg
        join pg_class cl on cl.oid = tg.tgrelid
        join pg_namespace n on n.oid = cl.relnamespace
        where {SCHEMA_IN}
        """
    )


def _q_policies(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'table', cl.relname, 'name', po.polname,
          'cmd', po.polcmd::text, 'permissive', po.polpermissive,
          'roles', (select json_agg(case when x = 0 then 'PUBLIC' else pg_get_userbyid(x) end
                                  order by x) from unnest(po.polroles) x),
          'qual', pg_get_expr(po.polqual, po.polrelid),
          'with_check', pg_get_expr(po.polwithcheck, po.polrelid)
        ) order by n.nspname, cl.relname, po.polname), '[]')::text
        from pg_policy po
        join pg_class cl on cl.oid = po.polrelid
        join pg_namespace n on n.oid = cl.relnamespace
        where {SCHEMA_IN}
        """
    )


def _q_schema_grants(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname,
          'grants', (
            select coalesce(json_agg(json_build_object(
              'grantee', case when a.grantee = 0 then 'PUBLIC' else pg_get_userbyid(a.grantee) end,
              'privileges', (select json_agg(a2.privilege_type order by a2.privilege_type)
                             from aclexplode(n.nspacl) a2 where a2.grantee = a.grantee))
              order by a.grantee), '[]')
            from (select distinct grantee from aclexplode(n.nspacl)) a)
        ) order by n.nspname), '[]')::text
        from pg_namespace n where n.nspname in ($$public$$, $$private$$)
        """
    )


def _q_sequence_owned_by(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', ns.nspname, 'sequence', s.relname,
          'table_schema', nt.nspname, 'table', t.relname, 'column', a.attname)
          order by ns.nspname, s.relname), '[]')::text
        from pg_class s
        join pg_namespace ns on ns.oid = s.relnamespace
        join pg_depend d on d.objid = s.oid
             and d.classid = $$pg_class$$::regclass
             and d.refclassid = $$pg_class$$::regclass
             and d.deptype in ($$a$$, $$i$$)
        join pg_class t on t.oid = d.refobjid
        join pg_namespace nt on nt.oid = t.relnamespace
        join pg_attribute a on a.attrelid = t.oid and a.attnum = d.refobjsubid
        where ns.nspname in ($$public$$, $$private$$) and s.relkind = $$S$$
        """
    )


def _q_sequence_params(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'name', cl.relname,
          'start', s.seqstart, 'increment', s.seqincrement,
          'min', s.seqmin, 'max', s.seqmax,
          'cache', s.seqcache, 'cycle', s.seqcycle,
          'type', pg_catalog.format_type(s.seqtypid, null)
        ) order by n.nspname, cl.relname), '[]')::text
        from pg_sequence s
        join pg_class cl on cl.oid = s.seqrelid
        join pg_namespace n on n.oid = cl.relnamespace
        where {SCHEMA_IN}
        """
    )


def _q_sequence_values(cli: TcbSqlClient, sequences: list) -> dict:
    """逐序列读 last_value / is_called（决定导入端 setval 参数）。"""
    if not sequences:
        return {}
    parts = []
    for seq in sequences:
        fq = qualified_name(seq["schema"], seq["name"])
        parts.append(
            "select "
            f"{_sql_lit(seq['schema'])}::text as schema, "
            f"{_sql_lit(seq['name'])}::text as name, "
            "last_value::text as last_value, is_called::text as is_called "
            f"from {fq}"
        )
    sql = (
        "select coalesce(json_agg(json_build_object("
        "'schema', schema, 'name', name, 'last_value', last_value, "
        "'is_called', is_called) order by schema, name), '[]')::text "
        "from (" + " union all ".join(parts) + ") x"
    )
    rows = cli.fetch_json(sql)
    return {(r["schema"], r["name"]): r for r in rows}


# ---------------------------------------------------------------------------
# SQL 生成工具
# ---------------------------------------------------------------------------

def _sql_lit(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return "'" + str(value).replace("'", "''") + "'"


def _q(schema: str, name: str) -> str:
    return qualified_name(schema, name)


def _group_grants(acl: list) -> dict:
    """{grantee: [privileges]}，只保留 GRANT_ROLES 中的被授权者。"""
    out: dict = {}
    for item in acl or []:
        grantee = item.get("grantee")
        if grantee not in GRANT_ROLES:
            continue
        out.setdefault(grantee, set()).update(item.get("privileges") or [])
    return {k: sorted(v) for k, v in out.items()}


# ---------------------------------------------------------------------------
# roles.sql
# ---------------------------------------------------------------------------

ROLE_ATTR_DEFAULTS = {
    "anon": dict(super=False, login=False, inherit=True, createrole=False,
                 createdb=False, bypassrls=False, connlimit=-1),
    "authenticated": dict(super=False, login=False, inherit=True, createrole=False,
                          createdb=False, bypassrls=False, connlimit=-1),
    "service_role": dict(super=False, login=False, inherit=True, createrole=False,
                         createdb=False, bypassrls=True, connlimit=-1),
}


def _role_attr_clause(attrs: dict) -> str:
    parts = ["NOLOGIN" if not attrs.get("login") else "LOGIN"]
    parts.append("NOSUPERUSER" if not attrs.get("super") else "SUPERUSER")
    parts.append("NOINHERIT" if not attrs.get("inherit", True) else "INHERIT")
    parts.append("NOCREATEROLE" if not attrs.get("createrole") else "CREATEROLE")
    parts.append("NOCREATEDB" if not attrs.get("createdb") else "CREATEDB")
    parts.append("NOBYPASSRLS" if not attrs.get("bypassrls") else "BYPASSRLS")
    connlimit = attrs.get("connlimit", -1)
    parts.append(f"CONNECTION LIMIT {int(connlimit)}" if connlimit is not None else
                 "CONNECTION LIMIT -1")
    return " ".join(parts)


def build_roles_sql(meta: dict) -> tuple:
    found = {r["name"]: r for r in meta.get("roles") or []}
    lines = [
        "-- =============================================================================",
        "-- roles.sql — CloudBase → ECS 自建 PostgreSQL：登录/接口角色（P0 导出产物）",
        "-- =============================================================================",
        "-- 源：CloudBase PostgreSQL (env tool-d4gosudok46e0e081, PG 17.11)",
        f"-- 抓取时间（源库 now()）：{meta.get('captured_at')}",
        "-- 目标：ECS PostgreSQL 18（库 class_tools）",
        "--",
        "-- 内容：anon / authenticated / service_role（NOLOGIN，属性按源库复刻；",
        "--       其中 service_role 为 BYPASSRLS，与源库一致）。",
        "--",
        "-- 不在此文件（由部署方创建）：",
        "--   authenticator —— PostgREST 的 LOGIN 角色，密码只存 /etc/class-tools/pgrest.conf（600）：",
        "--     CREATE ROLE authenticator LOGIN NOINHERIT PASSWORD '<随机强密码>';",
        "--     GRANT anon, authenticated, service_role TO authenticator;",
        "--   本文件不含任何密码/密钥，可进私有仓库。",
        "--",
        "-- 幂等：可重复执行（已存在则 ALTER 到目标属性）。",
        "-- =============================================================================",
        "",
    ]
    statements = []
    for role in DEPLOY_ROLES:
        attrs = dict(ROLE_ATTR_DEFAULTS[role])
        attrs.update({k: bool(v) for k, v in (found.get(role) or {}).items()
                      if k in ("super", "login", "inherit", "createrole", "createdb",
                               "bypassrls")})
        if found.get(role):
            attrs["connlimit"] = found[role].get("connlimit", -1)
        clause = _role_attr_clause(attrs)
        stmt = f"""DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {_sql_lit(role)}) THEN
    CREATE ROLE {quote_ident(role)} {clause};
  ELSE
    ALTER ROLE {quote_ident(role)} {clause};
  END IF;
END
$$;"""
        statements.append(stmt)
        lines.append(f"-- {role}: {clause}")
    lines.extend(["", "-- ---- 角色（幂等）----", ""])
    for stmt in statements:
        lines.append(stmt)
        lines.append("")
    lines.append("-- 说明：authenticator 的 LOGIN 密码不在产物中；P1 部署脚本生成并只落 ECS 本地。")
    lines.append("-- 说明：anon/authenticated 在源库即为 NOLOGIN，PostgREST 通过 SET ROLE 切换。")
    lines.append("")
    return "\n".join(lines), {"roles": len(statements)}


# ---------------------------------------------------------------------------
# schema.sql
# ---------------------------------------------------------------------------

POLCMD_MAP = {"r": "SELECT", "a": "INSERT", "w": "UPDATE", "d": "DELETE", "*": "ALL"}


def _policy_sql(policy: dict) -> str:
    ident = quote_ident(policy["name"])
    roles = [r for r in (policy.get("roles") or []) if r]
    if not roles:
        roles = [PUBLIC]
    role_clause = ", ".join(quote_ident(r) if r != PUBLIC else PUBLIC for r in roles)
    cmd = POLCMD_MAP.get(policy["cmd"], "ALL")
    perm = "PERMISSIVE" if policy.get("permissive", True) else "RESTRICTIVE"
    sql = (f"CREATE POLICY {ident} ON {_q(policy['schema'], policy['table'])}\n"
           f"  AS {perm}\n  FOR {cmd}\n  TO {role_clause}")
    if policy.get("qual"):
        sql += f"\n  USING ({policy['qual']})"
    if policy.get("with_check"):
        sql += f"\n  WITH CHECK ({policy['with_check']})"
    return sql + ";"


def build_schema_sql(meta: dict, relations: list, columns: list, constraints: list,
                     indexes: list, functions: list, function_defs: dict,
                     triggers: list, policies: list, schema_grants: list,
                     seq_owned: list, seq_values: dict,
                     seq_params: list) -> tuple:
    tables = [r for r in relations if r["kind"] == "r"]
    sequences = [r for r in relations if r["kind"] == "S"]
    tables.sort(key=lambda r: (r["schema"], r["name"]))
    sequences.sort(key=lambda r: (r["schema"], r["name"]))
    funcs = [f for f in functions if not f.get("extension")]
    funcs.sort(key=lambda f: (f["schema"], f["name"], f["oid"]))

    cols_by_table: dict = {}
    for col in columns:
        cols_by_table.setdefault((col["schema"], col["table"]), []).append(col)

    constraints_by_type: dict = {"p": [], "u": [], "f": [], "c": []}
    for con in constraints:
        constraints_by_type[con["type"]].append(con)

    stats = {k: 0 for k in (
        "create_schema", "create_extension", "create_sequence", "create_table",
        "create_function", "set_default", "add_constraint", "create_index",
        "enable_rls", "create_trigger", "create_policy", "grant_schema",
        "grant_table", "grant_sequence", "revoke_function_public", "grant_function",
        "revoke_private", "sequence_owned_by", "setval")}
    sec = {}

    def section(title: str, body: list) -> None:
        sec.setdefault(title, []).extend(body)

    # ---- 头部 ----
    locale = meta.get("database_locale") or {}
    header = [
        "-- =============================================================================",
        "-- schema.sql — CloudBase → ECS 自建 PostgreSQL：全量结构（P0 导出产物）",
        "-- =============================================================================",
        f"-- 源：CloudBase PostgreSQL (env tool-d4gosudok46e0e081) · {meta.get('pg_version')}",
        f"-- 抓取时间（源库 now()）：{meta.get('captured_at')}",
        f"-- 源库时区/编码/排序：{meta.get('timezone')} / {meta.get('server_encoding')} / "
        f"collate={locale.get('collate')} ctype={locale.get('ctype')} provider={locale.get('provider')}",
        "-- 目标：ECS PostgreSQL 18（库 class_tools）",
        "--",
        "-- 生成顺序：schema → 扩展 → 序列 → 表 → 函数 → 列默认值 → 约束 → 索引",
        "--           → RLS ENABLE → 触发器 → 策略 → 授权 → 序列 setval",
        "--",
        "-- 导入前提（P1 见 deploy/migration/IMPORT.md）：",
        "--   1) 先执行 roles.sql 建好 anon/authenticated/service_role；authenticator 由部署方创建。",
        "--   2) **建议用 `LC_COLLATE='C' LC_CTYPE='C' ENCODING='UTF8'` 建库**：源库 locale 为 C，",
        "--      换 locale 会改变 text 排序/大小写比较语义（unique 约束/ORDER BY 行为可能不同）。",
        "--   3) 以数据库属主（建议非超级用户 owner 角色）执行；SECURITY DEFINER 函数会以该属主身份运行。",
        "--   4) 先结构、后数据（export_data.py 产物）；数据导入后再 ANALYZE + 校验。",
        "--",
        "-- 不含：CloudBase 平台对象（event trigger pgrst_*/trg_restrict_s3_tables、pg_catalog 内的",
        "--       多租户 RLS、storage/auth schema、默认 ACL 中 cloudbase_* 角色、数据库级 setting）。",
        "--       详见 schema_manifest.json → excluded_platform_objects。",
        "-- =============================================================================",
        "",
        "SET client_encoding = 'UTF8';",
        "SET standard_conforming_strings = on;",
        "SET client_min_messages = warning;",
        "SET check_function_bodies = false;",
        "SET row_security = off;",
        "",
        "-- ---- schema ----",
        "CREATE SCHEMA IF NOT EXISTS private;",
        "",
        "-- 说明：public schema 由 PostgreSQL 默认提供（PG18 中 owner=pg_database_owner，",
        "--       PUBLIC 默认有 USAGE、无 CREATE；源库相同，授予见文件末尾 GRANT 段）。",
        "",
        "SET search_path = public, private, pg_temp;",
        "",
        "-- ---- extensions（源库只有 pgcrypto，位于 public；plpgsql 为内置）----",
        "CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;",
        "",
    ]
    stats["create_schema"] = 1
    stats["create_extension"] = 1
    # 注意：不把 CREATE SCHEMA/EXTENSION 放进 section 计数（表/函数等对象计数不含它）

    # ---- 序列 ----
    seq_param_by_key = {(s["schema"], s["name"]): s for s in seq_params}
    seq_meta = {}
    for seq in sequences:
        key = (seq["schema"], seq["name"])
        params = seq_param_by_key.get(key) or {}
        seq_meta[key] = params
        parts = [f"CREATE SEQUENCE {_q(seq['schema'], seq['name'])}",
                 f"  AS {params.get('type') or 'bigint'}",
                 f"  INCREMENT BY {int(params.get('increment') or 1)}",
                 f"  MINVALUE {int(params.get('min') or 1)}",
                 f"  MAXVALUE {int(params.get('max') or 9223372036854775807)}",
                 f"  START WITH {int(params.get('start') or 1)}",
                 f"  CACHE {int(params.get('cache') or 1)}"]
        parts.append("  CYCLE;" if params.get("cycle") else "  NO CYCLE;")
        section("sequences", ["\n".join(parts)])
        stats["create_sequence"] += 1

    # ---- 表 ----
    table_sqls = []
    default_sqls = []
    rls_sqls = []
    for table in tables:
        key = (table["schema"], table["name"])
        cols = cols_by_table.get(key) or []
        if not cols:
            raise ExportSchemaError(f"表 {key} 没有列信息")
        lines = [f"CREATE TABLE {_q(*key)} ("]
        for col in cols:
            col_type = col["type"]
            if col.get("collation"):
                col_type += f" COLLATE {quote_ident(col['collation'])}"
            if col.get("identity") == "a":
                col_type += " GENERATED ALWAYS AS IDENTITY"
            elif col.get("identity") == "d":
                col_type += " GENERATED BY DEFAULT AS IDENTITY"
            elif col.get("generated") == "s":
                if not col.get("default"):
                    raise ExportSchemaError(f"{key}.{col['name']} 生成列缺少表达式")
                col_type += f" GENERATED ALWAYS AS ({col['default']}) STORED"
            else:
                if col.get("default"):
                    default_sqls.append(
                        f"ALTER TABLE ONLY {_q(*key)} ALTER COLUMN "
                        f"{quote_ident(col['name'])} SET DEFAULT {col['default']};")
                    stats["set_default"] += 1
            if col.get("notnull"):
                col_type += " NOT NULL"
            lines.append(f"    {quote_ident(col['name'])} {col_type},")
        lines[-1] = lines[-1].rstrip(",")
        lines.append(");")
        table_sqls.append("\n".join(lines))
        stats["create_table"] += 1
        if table.get("rls"):
            rls_sqls.append(f"ALTER TABLE {_q(*key)} ENABLE ROW LEVEL SECURITY;")
            stats["enable_rls"] += 1
        if table.get("force_rls"):
            rls_sqls.append(f"ALTER TABLE {_q(*key)} FORCE ROW LEVEL SECURITY;")
    section("tables", table_sqls)

    # ---- 函数 ----
    missing_defs = [f"{f['schema']}.{f['name']}({f['identity']})"
                    for f in funcs if int(f["oid"]) not in function_defs]
    if missing_defs:
        raise ExportSchemaError("缺少函数定义: " + ", ".join(missing_defs[:5]))
    fn_sqls = []
    fn_grants = []          # (schema, name, identity, has_public, group_grants)
    for fn in funcs:
        definition = (function_defs[int(fn["oid"])] or "").rstrip()
        if not definition:
            raise ExportSchemaError(f"函数 {fn['name']} 定义为空")
        if not definition.endswith(";"):
            definition += ";"
        fn_sqls.append(f"-- {fn['schema']}.{fn['name']}({fn['identity']})"
                       f"{' [SECURITY DEFINER]' if fn['secdef'] else ''}\n{definition}")
        stats["create_function"] += 1
        grants = _group_grants(fn.get("acl"))
        fn_grants.append({
            "schema": fn["schema"], "name": fn["name"], "identity": fn["identity"],
            "acl_present": bool(fn.get("acl")),
            "has_public": "PUBLIC" in grants,
            "grants": grants,
        })
    section("functions", fn_sqls)

    # ---- 列默认值 ----
    section("defaults", default_sqls)

    # ---- 约束 ----
    con_sqls = []
    for typ in ("p", "u", "f", "c"):
        for con in constraints_by_type[typ]:
            con_sqls.append(
                f"ALTER TABLE ONLY {_q(con['schema'], con['table'])} "
                f"ADD CONSTRAINT {quote_ident(con['name'])} {con['def']};")
            stats["add_constraint"] += 1
    section("constraints", con_sqls)

    # ---- 索引 ----
    idx_sqls = []
    for idx in indexes:
        if not idx.get("valid"):
            raise ExportSchemaError(f"索引无效（不能导出为可用于导入的 DDL）: {idx['name']}")
        idx_sqls.append(idx["def"].rstrip(";") + ";")
        stats["create_index"] += 1
    section("indexes", idx_sqls)

    # ---- 序列 OWNED BY ----
    owned_sqls = []
    for item in seq_owned:
        owned_sqls.append(
            f"ALTER SEQUENCE {_q(item['schema'], item['sequence'])} "
            f"OWNED BY {_q(item['table_schema'], item['table'])}."
            f"{quote_ident(item['column'])};")
        stats["sequence_owned_by"] += 1
    section("sequence_owned_by", owned_sqls)

    # ---- RLS ----
    section("rls", rls_sqls)

    # ---- 触发器 ----
    trg_sqls = []
    for trg in triggers:
        if trg.get("internal"):
            continue
        trg_sqls.append(trg["def"].rstrip(";") + ";")
        stats["create_trigger"] += 1
    section("triggers", trg_sqls)

    # ---- 策略 ----
    pol_sqls = [_policy_sql(p) for p in sorted(
        policies, key=lambda p: (p["schema"], p["table"], p["name"]))]
    stats["create_policy"] = len(pol_sqls)
    section("policies", pol_sqls)

    # ---- 授权：schema ----
    grant_schema_sqls = []
    for item in schema_grants:
        schema_name = item["schema"]
        for grantee, privs in sorted(_group_grants_schema(item.get("grants")).items()):
            if not privs:
                continue
            grant_schema_sqls.append(
                f"GRANT {', '.join(privs)} ON SCHEMA {quote_ident(schema_name)} "
                f"TO {quote_ident(grantee) if grantee != PUBLIC else PUBLIC};")
            stats["grant_schema"] += 1
    section("grant_schema", grant_schema_sqls)

    # ---- 授权：表 / 序列 ----
    grant_rel_sqls = []
    # 私有 schema：显式撤销表/序列对 PUBLIC 与接口角色的权限。
    # 源库 private 下的表/序列本就没有 anon/authenticated/service_role 授权（只给 schema USAGE，
    # 供 SECURITY DEFINER 函数与策略表达式引用）；这里显式 REVOKE，防止导入库的默认 ACL 泄漏。
    for stmt in (
        "REVOKE ALL ON ALL TABLES IN SCHEMA private "
        "FROM PUBLIC, anon, authenticated, service_role;",
        "REVOKE ALL ON ALL SEQUENCES IN SCHEMA private "
        "FROM PUBLIC, anon, authenticated, service_role;",
    ):
        grant_rel_sqls.append(stmt)
        stats["revoke_private"] += 1
    for rel in relations:
        grants = _group_grants(rel.get("acl"))
        if not grants:
            continue
        keyword = "TABLE" if rel["kind"] == "r" else "SEQUENCE"
        for grantee, privs in sorted(grants.items()):
            if not privs:
                continue
            grant_rel_sqls.append(
                f"GRANT {', '.join(privs)} ON {keyword} {_q(rel['schema'], rel['name'])} "
                f"TO {quote_ident(grantee) if grantee != PUBLIC else PUBLIC};")
            if rel["kind"] == "r":
                stats["grant_table"] += 1
            else:
                stats["grant_sequence"] += 1
    section("grant_relations", grant_rel_sqls)

    # ---- 授权：函数（先按源库撤销 PUBLIC，再逐个 GRANT EXECUTE）----
    fn_grant_sqls = []
    for item in fn_grants:
        fq = f"{_q(item['schema'], item['name'])}({item['identity']})"
        if item["acl_present"] and not item["has_public"]:
            fn_grant_sqls.append(f"REVOKE ALL ON FUNCTION {fq} FROM PUBLIC;")
            stats["revoke_function_public"] += 1
        role_names = [g for g in item["grants"] if g != PUBLIC]
        if item["has_public"] and not item["acl_present"]:
            role_names = []   # 默认 ACL 已含 PUBLIC EXECUTE + owner
        for grantee in sorted(role_names):
            fn_grant_sqls.append(
                f"GRANT EXECUTE ON FUNCTION {fq} TO {quote_ident(grantee)};")
            stats["grant_function"] += 1
        if item["has_public"]:
            fn_grant_sqls.append(f"GRANT EXECUTE ON FUNCTION {fq} TO PUBLIC;")
            stats["grant_function"] += 1
    section("grant_functions", fn_grant_sqls)

    # ---- 序列 setval ----
    setval_sqls = []
    for seq in sequences:
        key = (seq["schema"], seq["name"])
        info = seq_values.get(key)
        if info is None:
            continue
        is_called = str(info.get("is_called")).lower() in ("true", "t", "1")
        seq_lit = "'" + _q(seq["schema"], seq["name"]).replace("'", "''") + "'"
        setval_sqls.append(
            f"SELECT pg_catalog.setval({seq_lit}, {int(info['last_value'])}, "
            f"{'true' if is_called else 'false'});")
        stats["setval"] += 1
    section("setval", setval_sqls)

    # ---- 组装 ----
    order = [
        ("schema", None),
        ("extensions", None),
        ("sequences", "---- 序列 ----"),
        ("tables", "---- 表（列类型/NOT NULL；默认值在函数之后设置）----"),
        ("functions", "---- 函数（52 个自有函数；36 个 SECURITY DEFINER；pgcrypto 由扩展提供）----"),
        ("defaults", "---- 列默认值（依赖函数/序列）----"),
        ("constraints", "---- 约束：PK / UNIQUE / FK / CHECK ----"),
        ("indexes", "---- 非约束索引 ----"),
        ("sequence_owned_by", "---- 序列归属 ----"),
        ("rls", "---- 行级安全（RLS）开关（策略见下）----"),
        ("triggers", "---- 触发器（2 个业务触发器；FK 内部触发器由约束自动生成，不导出）----"),
        ("policies", "---- RLS 策略（71 TO anon + 2 TO PUBLIC）----"),
        ("grant_schema", "---- 授权：schema USAGE ----"),
        ("grant_relations", "---- 授权：表/序列（按源库 ACL 复刻）----"),
        ("grant_functions", "---- 授权：函数 EXECUTE（按源库 ACL 复刻）----"),
        ("setval", "---- 序列当前值（数据导入前设置，导入后按新数据再校正）----"),
    ]
    body = list(header)
    for name, title in order:
        if title is None:
            continue
        statements = sec.get(name) or []
        body.append(f"-- ---- {title} ----")
        body.append("")
        if statements:
            body.extend(statements)
        else:
            body.append("-- （无）")
        body.append("")
    body.append("-- ---- 结构导入完成 ----")
    body.append("-- 后续（P1 IMPORT.md）：导入数据 → 逐表 setval 校正 → ANALYZE → 计数/哈希校验。")
    body.append("")
    return "\n".join(body), stats


def _group_grants_schema(grants: list) -> dict:
    """schema ACL 展开：{grantee: [privileges]}（只保留 GRANT_ROLES）。"""
    out: dict = {}
    for item in grants or []:
        grantee = item.get("grantee")
        if grantee not in GRANT_ROLES:
            continue
        out.setdefault(grantee, set()).update(item.get("privileges") or [])
    return {k: sorted(v) for k, v in out.items()}


# ---------------------------------------------------------------------------
# 交叉校验
# ---------------------------------------------------------------------------

def _count_regex(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text, flags=re.MULTILINE))


def check_generated_sql(schema_sql: str, catalog: dict) -> list:
    checks = []

    def add(name: str, expected: int, pattern: str):
        actual = _count_regex(schema_sql, pattern)
        checks.append({"check": name, "catalog": expected, "generated": actual,
                       "ok": actual == expected})

    add("tables", catalog["tables_total"], r"^CREATE TABLE ")
    add("sequences", catalog["sequences"], r"^CREATE SEQUENCE ")
    add("functions_own", catalog["functions_own"], r"^CREATE OR REPLACE FUNCTION ")
    add("indexes_nonconstraint", catalog["indexes_nonconstraint"], r"^CREATE INDEX ")
    add("constraints_total",
        catalog["constraints_primary"] + catalog["constraints_unique"]
        + catalog["constraints_foreign"] + catalog["constraints_check"],
        r"^ALTER TABLE ONLY .* ADD CONSTRAINT ")
    add("rls_enabled", catalog["rls_enabled_tables"],
        r"^ALTER TABLE .* ENABLE ROW LEVEL SECURITY;")
    add("triggers_user", catalog["triggers_user"], r"^CREATE TRIGGER ")
    add("policies", catalog["policies_total"], r"^CREATE POLICY ")
    add("pgcrypto_extension", 1, r"^CREATE EXTENSION IF NOT EXISTS pgcrypto ")
    # pg_get_functiondef 会把易变性写在同一行，如 " VOLATILE SECURITY DEFINER"
    secdef = _count_regex(schema_sql, r" SECURITY DEFINER$")
    checks.append({"check": "functions_security_definer", "catalog": catalog["functions_secdef_own"],
                   "generated": secdef, "ok": secdef == catalog["functions_secdef_own"]})
    failed = [c for c in checks if not c["ok"]]
    return checks, failed


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_export(args: argparse.Namespace) -> int:
    t_start = time.time()
    client = TcbSqlClient(env_id=args.env or None, timeout=args.timeout,
                          attempts=3, verbose=True)
    ping = client.ping()
    print(f"[export_schema] 已连接 {ping['database']} ({ping['version'][:60]}...)")

    print("[export_schema] 读取 catalog（元信息）...")
    meta = _q_meta(client)
    counts = _q_counts(client)

    print("[export_schema] 读取表/列/约束/索引/序列 ...")
    relations = _q_relations(client)
    columns = _q_columns(client)
    constraints = _q_constraints(client)
    indexes = _q_indexes(client)
    seq_owned = _q_sequence_owned_by(client)
    seq_params = _q_sequence_params(client)

    sequences = [r for r in relations if r["kind"] == "S"]
    print(f"[export_schema] 读取序列当前值（{len(sequences)}）...")
    seq_values = _q_sequence_values(client, sequences)

    print("[export_schema] 读取函数（88 = 52 自有 + 36 pgcrypto 扩展）...")
    functions = _q_functions(client)
    own_oids = [f["oid"] for f in functions if not f.get("extension")]
    function_defs = _q_function_defs(client, own_oids)

    print("[export_schema] 读取触发器/策略/授权 ...")
    triggers = _q_triggers(client)
    policies = _q_policies(client)
    schema_grants = _q_schema_grants(client)

    # -- 生成 roles.sql --
    roles_sql, role_stats = build_roles_sql(meta)

    # -- 生成 schema.sql --
    schema_sql, gen_stats = build_schema_sql(
        meta, relations, columns, constraints, indexes, functions, function_defs,
        triggers, policies, schema_grants, seq_owned, seq_values, seq_params)

    # -- 交叉校验（catalog vs 生成 DDL）--
    checks, failed = check_generated_sql(schema_sql, counts)
    if failed:
        detail = "; ".join(f"{c['check']}: catalog={c['catalog']} generated={c['generated']}"
                           for c in failed)
        raise ExportSchemaError("结构计数不一致，拒绝写入产物: " + detail)

    # -- 写产物 --
    out_dir = resolve_output_dir(args.out)
    roles_path = out_dir / "roles.sql"
    schema_path = out_dir / "schema.sql"
    roles_path.write_text(roles_sql, encoding="utf-8", newline="\n")
    schema_path.write_text(schema_sql, encoding="utf-8", newline="\n")

    # -- sha256 校验：源库函数/策略/触发器/索引/约束 内容指纹（用于导入端回归比对）--
    def _hash_list(items: list) -> str:
        import hashlib
        h = hashlib.sha256()
        for item in sorted(items, key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True)):
            h.update(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            h.update(b"\n")
        return h.hexdigest()

    table_columns = {}
    for col in columns:
        table_columns.setdefault(f"{col['schema']}.{col['table']}", []).append(
            {"name": col["name"], "type": col["type"],
             "notnull": bool(col["notnull"]), "attnum": col["attnum"]})
    tables = [r for r in relations if r["kind"] == "r"]
    pk_by_table = {}
    for con in constraints:
        if con["type"] == "p":
            pk_by_table[f"{con['schema']}.{con['table']}"] = con.get("columns") or []

    manifest = {
        "kind": "schema_manifest",
        "generator": "deploy/migration/export_schema.py",
        "generated_at_utc": utc_now_iso(),
        "elapsed_s": round(time.time() - t_start, 1),
        "source": {
            "env_id": args.env or "tool-d4gosudok46e0e081",
            "pg_version": meta.get("pg_version"),
            "server_version_num": meta.get("server_version_num"),
            "database": meta.get("database"),
            "current_user": meta.get("current_user"),
            "timezone": meta.get("timezone"),
            "datestyle": meta.get("datestyle"),
            "encoding": meta.get("server_encoding"),
            "locale": meta.get("database_locale"),
            "captured_at": meta.get("captured_at"),
        },
        "target": {
            "product": "PostgreSQL 18 (ECS 自建)",
            "recommended_db_locale": {
                "LC_COLLATE": "C", "LC_CTYPE": "C", "ENCODING": "UTF8",
                "reason": "源库 locale 为 C；换 locale 会改变 text 排序/比较语义",
            },
            "roles_required": list(DEPLOY_ROLES),
            "authenticator": "由部署方创建（LOGIN，密码仅 ECS 本地），产物不含密码",
        },
        "roles": meta.get("roles"),
        "schemas": meta.get("schemas"),
        "extensions": meta.get("extensions"),
        "counts": {
            "tables": {"total": counts["tables_total"],
                       "public": counts["tables_public"],
                       "private": counts["tables_private"]},
            "columns": counts["columns"],
            "sequences": counts["sequences"],
            "views": counts["views"],
            "functions": {"in_catalog": counts["functions_total"],
                          "own": counts["functions_own"],
                          "extension": counts["functions_extension"],
                          "security_definer": counts["functions_secdef_own"]},
            "policies": {"total": counts["policies_total"],
                         "to_public": counts["policies_public"],
                         "to_anon": counts["policies_total"] - counts["policies_public"]},
            "triggers": {"user": counts["triggers_user"],
                         "internal_fk": counts["triggers_internal"]},
            "indexes": {"total": counts["indexes_total"],
                        "non_constraint": counts["indexes_nonconstraint"]},
            "constraints": {"primary": counts["constraints_primary"],
                            "unique": counts["constraints_unique"],
                            "foreign": counts["constraints_foreign"],
                            "check": counts["constraints_check"]},
            "rls": {"enabled_tables": counts["rls_enabled_tables"],
                    "forced_tables": counts["rls_forced_tables"]},
        },
        "generated_statement_counts": gen_stats,
        "structure_checks": checks,
        "structure_hash": {
            "functions": _hash_list(own_oids and [
                {"oid": f["oid"], "schema": f["schema"], "name": f["name"],
                 "identity": f["identity"], "def": function_defs.get(int(f["oid"])),
                 "secdef": f["secdef"], "proconfig": f.get("proconfig")}
                for f in functions if not f.get("extension")]),
            "policies": _hash_list(policies),
            "triggers": _hash_list([t for t in triggers if not t["internal"]]),
            "indexes": _hash_list(indexes),
            "constraints": _hash_list(constraints),
            "columns": _hash_list(columns),
            "grants": _hash_list(schema_grants),
        },
        "tables": [
            {
                "schema": t["schema"], "name": t["name"],
                "rls": bool(t.get("rls")), "force_rls": bool(t.get("force_rls")),
                "owner": t.get("owner"),
                "pk": pk_by_table.get(f"{t['schema']}.{t['name']}", []),
                "columns": table_columns.get(f"{t['schema']}.{t['name']}", []),
            }
            for t in sorted(tables, key=lambda x: (x["schema"], x["name"]))
        ],
        "sequences": [
            {
                "schema": s["schema"], "name": s["name"],
                "last_value": seq_values.get((s["schema"], s["name"]), {}).get("last_value"),
                "is_called": str(seq_values.get((s["schema"], s["name"]), {}).get("is_called", "")),
                "params": {(q["schema"] + "." + q["name"]): q
                           for q in seq_params}.get(s["schema"] + "." + s["name"]),
                "acl": _group_grants(s.get("acl")),
            }
            for s in sorted(sequences, key=lambda x: (x["schema"], x["name"]))
        ],
        "excluded_platform_objects": {
            "event_triggers": meta.get("event_triggers"),
            "note_event_triggers": ("PostgREST/CloudBase 平台对象（extensions/storage schema），"
                                    "由部署方的 PostgREST/平台自行创建，不迁移。"),
            "pg_catalog_policies": "pg_catalog 下的多租户 RLS 属 CloudBase 平台，不迁移。",
            "default_acls": meta.get("default_acls"),
            "note_default_acls": ("默认 ACL 引用了 cloudbase_* 平台角色，不迁移；"
                                  "本库对象权限已由显式 GRANT 复刻（见 generated_statement_counts）。"),
            "db_role_settings": meta.get("db_role_settings"),
            "note_db_role_settings": ("tencentdb_multi_tenant_visible_roles 为 CloudBase 平台设置，不迁移。"),
            "internal_fk_triggers": counts["triggers_internal"],
            "note_internal_fk_triggers": "FK 内部触发器由 ADD CONSTRAINT 自动生成，不单独导出。",
            "platform_roles": meta.get("roles"),
            "publications": meta.get("publications"),
            "subscriptions": meta.get("subscriptions"),
        },
        "generated_files": {
            "roles.sql": {"bytes": roles_path.stat().st_size,
                          "sha256": sha256_file(roles_path)},
            "schema.sql": {"bytes": schema_path.stat().st_size,
                           "sha256": sha256_file(schema_path)},
        },
    }
    manifest_path = out_dir / "schema_manifest.json"
    write_json(manifest_path, manifest)

    # -- 控制台摘要（只打印计数，不打印对象/数据内容）--
    print("")
    print("[export_schema] 完成")
    print(f"  产物目录          : {out_dir}")
    print(f"  roles.sql         : {human_bytes(roles_path.stat().st_size)}"
          f"  (3 角色, authenticator 由部署方创建)")
    print(f"  schema.sql        : {human_bytes(schema_path.stat().st_size)}")
    print(f"  schema_manifest   : {human_bytes(manifest_path.stat().st_size)}")
    c = manifest["counts"]
    print(f"  表                : {c['tables']['total']} "
          f"(public={c['tables']['public']}, private={c['tables']['private']})")
    print(f"  列                : {c['columns']}")
    print(f"  序列              : {c['sequences']}")
    print(f"  函数              : catalog={c['functions']['in_catalog']} "
          f"= own {c['functions']['own']} + extension {c['functions']['extension']}; "
          f"SECURITY DEFINER={c['functions']['security_definer']}")
    print(f"  策略              : {c['policies']['total']} "
          f"(TO anon={c['policies']['to_anon']}, TO PUBLIC={c['policies']['to_public']})")
    print(f"  触发器            : user={c['triggers']['user']} (internal FK="
          f"{c['triggers']['internal_fk']})")
    print(f"  索引              : total={c['indexes']['total']} "
          f"(non-constraint={c['indexes']['non_constraint']})")
    print(f"  约束              : PK={c['constraints']['primary']} U={c['constraints']['unique']} "
          f"FK={c['constraints']['foreign']} CHECK={c['constraints']['check']}")
    print(f"  RLS 表            : {c['rls']['enabled_tables']}")
    print(f"  结构交叉校验      : {sum(1 for x in checks if x['ok'])}/{len(checks)} OK")
    print(f"  耗时              : {time.time() - t_start:.1f}s")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="CloudBase → PG18 结构只读导出（roles.sql + schema.sql + schema_manifest.json）")
    parser.add_argument("--out", default="", help="产物目录（默认复用最新，无则新建时间戳目录）")
    parser.add_argument("--new-run", action="store_true",
                        help="强制新建 <YYYYMMDD-HHMM> 产物目录（不覆盖旧产物）")
    parser.add_argument("--env", default="", help="tcb 环境 ID（默认用 CLI 当前环境）")
    parser.add_argument("--timeout", type=float, default=300.0, help="单次 SQL 超时秒数")
    args = parser.parse_args(argv)

    if args.new_run and not args.out:
        args.out = str(new_output_dir())
    try:
        return run_export(args)
    except (TcbSqlError, ExportSchemaError) as exc:
        print(f"[export_schema] 失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
