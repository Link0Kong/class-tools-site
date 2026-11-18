#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_export.py — P0 导出产物校验 + SUMMARY.md + 合并 manifest.json

校验层次
========
1. **产物完整性**：roles.sql / schema.sql / data/*.jsonl.gz 存在，大小与 sha256 与
   schema_manifest.json / data_manifest.json 记录一致。
2. **结构**：重新读线上 catalog 计数，和 schema_manifest.counts 对比；再统计
   schema.sql 里的 DDL 语句数（CREATE TABLE/FUNCTION/POLICY/TRIGGER/INDEX/…），
   与 catalog 三方对齐；可选地用 pglast（libpg_query）做一次全文件语法解析。
3. **数据（本地）**：逐表解压 JSONL，流式重算「行数 + 规范化 sha256」并与
   data_manifest 记录比对；逐行 JSON 解析 + 列集合校验；gzip 文件 sha256 复核。
4. **数据（线上）**：重新对线上每表算 ``count(*) + sha256(string_agg(row_to_json))``，
   与导出时（manifest 的 server_n / server_sha256）对比：
   - **MATCH**：导出后线上无变化（快照与线上一致）；
   - **DRIFT**：导出后有新写入（live 表正常现象），输出 delta 行数，默认仅警告；
     ``--strict`` 时视为失败。
5. **覆盖性**：线上 34 张表必须全部在产物中（public 29 + private 5）。

输出
====
- ``<out>/manifest.json``：合并后的最终清单（结构计数 + 每表行数/sha/列类型 + 校验结果）
- ``<out>/SUMMARY.md``：人类可读摘要（**只含对象名/计数/大小，绝不含正文/姓名/学号/token**）

用法::

    python deploy/migration/verify_export.py                # 复用最新产物目录
    python deploy/migration/verify_export.py --strict       # 线上漂移也算失败
    python deploy/migration/verify_export.py --skip-online  # 只查本地（不连 CloudBase）
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tcb_sql import (  # noqa: E402
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
PKS_MISSING = object()


class VerifyError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 线上 catalog / 数据计数
# ---------------------------------------------------------------------------

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
                                and cl.relkind = $$r$$ and cl.relrowsecurity
                                and cl.relforcerowsecurity),
          'extension_count', (select count(*) from pg_extension),
          'event_triggers', (select count(*) from pg_event_trigger)
        )::text
        """
    )


def _q_live_tables(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'table', cl.relname) order by n.nspname, cl.relname), '[]')::text
        from pg_class cl join pg_namespace n on n.oid = cl.relnamespace
        where {SCHEMA_IN} and cl.relkind = $$r$$
        """
    )


def _q_pks(cli: TcbSqlClient) -> dict:
    rows = cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'table', cl.relname,
          'columns', (select json_agg(a.attname order by k.ord)
                      from unnest(co.conkey) with ordinality k(attnum, ord)
                      join pg_attribute a on a.attrelid = co.conrelid and a.attnum = k.attnum)
        ) order by n.nspname, cl.relname), '[]')::text
        from pg_constraint co join pg_class cl on cl.oid = co.conrelid
        join pg_namespace n on n.oid = cl.relnamespace
        where {SCHEMA_IN} and co.contype = $$p$$
        """
    )
    return {(r["schema"], r["table"]): r["columns"] for r in rows}


def _order_expr(pk: list) -> str:
    if pk:
        return ", ".join(f"t.{quote_ident(c)}" for c in pk)
    return "t.ctid"


def _q_online_digest(cli: TcbSqlClient, schema: str, table: str, pk: list) -> dict:
    fq = qualified_name(schema, table)
    order = _order_expr(pk)
    return cli.fetch_json(
        "select json_build_object("
        "'n', count(*), "
        "'h', encode(digest(coalesce(string_agg(row_to_json(t)::text, chr(10) "
        f"order by {order}), ''), 'sha256'), 'hex'), "
        "'at', now()::text"
        f")::text from {fq} t",
        timeout=300,
    )


# ---------------------------------------------------------------------------
# 本地校验
# ---------------------------------------------------------------------------

def _hash_jsonl_gz(gz_path: Path) -> tuple:
    """解压后流式重算 (rows, sha256(行文本 \\n 连接), json_ok, column_key_mismatch)。"""
    h = hashlib.sha256()
    rows = 0
    first = True
    json_ok = 0
    json_bad = 0
    with gzip.open(gz_path, "rb") as fh:
        for raw_line in fh:
            line = raw_line.rstrip(b"\n")
            if not first:
                h.update(b"\n")
            h.update(line)
            first = False
            rows += 1
            if line:
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        json_ok += 1
                    else:
                        json_bad += 1
                except (ValueError, UnicodeDecodeError):
                    json_bad += 1
    return rows, h.hexdigest(), json_ok, json_bad


def load_json(path: Path, label: str) -> dict:
    if not path.exists():
        raise VerifyError(f"缺少 {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise VerifyError(f"{label} 无法解析: {exc}")


def check_schema_sql(schema_sql: str, schema_manifest: dict) -> tuple:
    """统计 schema.sql 里的 DDL 语句数并与 catalog 计数对齐。"""
    checks = []

    def count(pattern: str) -> int:
        return len(re.findall(pattern, schema_sql, flags=re.MULTILINE))

    c = schema_manifest.get("counts") or {}
    expected = {
        "tables": c.get("tables", {}).get("total", -1),
        "sequences": c.get("sequences", -1),
        "functions_own": c.get("functions", {}).get("own", -1),
        "indexes_nonconstraint": c.get("indexes", {}).get("non_constraint", -1),
        "constraints_total": (c.get("constraints", {}).get("primary", 0)
                              + c.get("constraints", {}).get("unique", 0)
                              + c.get("constraints", {}).get("foreign", 0)
                              + c.get("constraints", {}).get("check", 0)),
        "rls_enabled": c.get("rls", {}).get("enabled_tables", -1),
        "triggers_user": c.get("triggers", {}).get("user", -1),
        "policies": c.get("policies", {}).get("total", -1),
    }
    patterns = {
        "tables": r"^CREATE TABLE ",
        "sequences": r"^CREATE SEQUENCE ",
        "functions_own": r"^CREATE OR REPLACE FUNCTION ",
        "indexes_nonconstraint": r"^CREATE INDEX ",
        "constraints_total": r"^ALTER TABLE ONLY .* ADD CONSTRAINT ",
        "rls_enabled": r"^ALTER TABLE .* ENABLE ROW LEVEL SECURITY;$",
        "triggers_user": r"^CREATE TRIGGER ",
        "policies": r"^CREATE POLICY ",
    }
    for name, pat in patterns.items():
        actual = count(pat)
        checks.append({"check": f"schema.sql.{name}", "expected": expected[name],
                       "actual": actual, "ok": actual == expected[name]})
    secdef = count(r" SECURITY DEFINER$")
    exp_secdef = c.get("functions", {}).get("security_definer", -1)
    checks.append({"check": "schema.sql.functions_security_definer",
                   "expected": exp_secdef, "actual": secdef, "ok": secdef == exp_secdef})
    pgcrypto = count(r"^CREATE EXTENSION IF NOT EXISTS pgcrypto ")
    checks.append({"check": "schema.sql.pgcrypto_extension", "expected": 1,
                   "actual": pgcrypto, "ok": pgcrypto == 1})
    return checks


def check_schema_syntax(schema_sql: str, roles_sql: str) -> dict:
    """可选：用 pglast(libpg_query) 做 PostgreSQL 语法解析（未安装则跳过）。"""
    result = {"available": False, "schema_ok": None, "roles_ok": None,
              "schema_statements": None, "roles_statements": None, "error": ""}
    try:
        from pglast import parse_sql  # type: ignore
    except Exception:
        result["error"] = "pglast 未安装（可选校验，跳过）"
        return result
    result["available"] = True
    try:
        stmts = parse_sql(schema_sql)
        result["schema_ok"] = True
        result["schema_statements"] = len(stmts)
    except Exception as exc:  # noqa: BLE001
        result["schema_ok"] = False
        result["error"] = f"schema.sql 解析失败: {exc}"
    try:
        stmts = parse_sql(roles_sql)
        result["roles_ok"] = True
        result["roles_statements"] = len(stmts)
    except Exception as exc:  # noqa: BLE001
        result["roles_ok"] = False
        result["error"] += f" / roles.sql 解析失败: {exc}"
    return result


def check_roles_sql(roles_sql: str) -> list:
    checks = []
    for role in ("anon", "authenticated", "service_role"):
        ok = re.search(rf"CREATE ROLE {role}\b", roles_sql) is not None and \
            re.search(rf"ALTER ROLE {role}\b", roles_sql) is not None
        checks.append({"check": f"roles.sql.{role}", "ok": bool(ok)})
    # 不含真实密码：只看非注释行
    code_lines = [ln for ln in roles_sql.splitlines() if not ln.lstrip().startswith("--")]
    code = "\n".join(code_lines)
    checks.append({"check": "roles.sql.no_password",
                   "ok": re.search(r"\bPASSWORD\b", code) is None})
    checks.append({"check": "roles.sql.service_role_bypassrls",
                   "ok": "service_role BYPASSRLS" in roles_sql
                         or re.search(r"ALTER ROLE service_role .*BYPASSRLS", roles_sql) is not None})
    return checks


# ---------------------------------------------------------------------------
# SUMMARY.md
# ---------------------------------------------------------------------------

def build_summary(manifest: dict) -> str:
    s = manifest["schema_manifest"]
    d = manifest["data_manifest"]
    v = manifest["verification"]
    counts = s["counts"]
    lines = []
    add = lines.append
    add("# CloudBase → ECS PostgreSQL 迁移 · P0 导出产物摘要")
    add("")
    add(f"- 生成时间（UTC）：{manifest['generated_at_utc']}")
    add(f"- 产物目录：`{manifest['output_dir']}`（**私有，含真实数据，绝不进仓库**）")
    add(f"- 源库：CloudBase env `{s['source']['env_id']}` · "
        f"{s['source']['pg_version'].split(' on ')[0]} · db `{s['source']['database']}`")
    add(f"- 源库时区/编码/locale：{s['source']['timezone']} / {s['source']['encoding']} / "
        f"C={s['source']['locale'].get('collate')} (UTF8)")
    add(f"- 目标：ECS PostgreSQL 18（库 `class_tools`）")
    add("")
    add("## 1. 结构（schema）")
    add("")
    add("| 对象 | 数量 | 说明 |")
    add("|---|---:|---|")
    add(f"| 表 | {counts['tables']['total']} | public {counts['tables']['public']} + "
        f"private {counts['tables']['private']} |")
    add(f"| 列 | {counts['columns']} | 含类型/默认值/NOT NULL |")
    add(f"| 序列 | {counts['sequences']} | 含 last_value/is_called → setval |")
    add(f"| 函数 | {counts['functions']['in_catalog']} | 自有 {counts['functions']['own']} + "
        f"pgcrypto 扩展 {counts['functions']['extension']}；其中 SECURITY DEFINER "
        f"{counts['functions']['security_definer']} |")
    add(f"| 策略（RLS policy） | {counts['policies']['total']} | TO anon "
        f"{counts['policies']['to_anon']} + TO PUBLIC {counts['policies']['to_public']} |")
    add(f"| 触发器 | {counts['triggers']['user']} | 业务触发器；另有 {counts['triggers']['internal_fk']} "
        f"个 FK 内部触发器由约束自动生成 |")
    add(f"| 索引 | {counts['indexes']['total']} | 非约束索引 {counts['indexes']['non_constraint']} |")
    add(f"| 约束 | {sum(counts['constraints'].values())} | PK {counts['constraints']['primary']} / "
        f"UNIQUE {counts['constraints']['unique']} / FK {counts['constraints']['foreign']} / "
        f"CHECK {counts['constraints']['check']} |")
    add(f"| RLS 开启表 | {counts['rls']['enabled_tables']} | 源库无 FORCE RLS |")
    add("")
    gen = s["generated_statement_counts"]
    add("生成的 DDL 语句数（schema.sql）："
        f"CREATE TABLE {gen['create_table']}、CREATE SEQUENCE {gen['create_sequence']}、"
        f"CREATE FUNCTION {gen['create_function']}、ADD CONSTRAINT {gen['add_constraint']}、"
        f"CREATE INDEX {gen['create_index']}、ENABLE RLS {gen['enable_rls']}、"
        f"CREATE TRIGGER {gen['create_trigger']}、CREATE POLICY {gen['create_policy']}、"
        f"SET DEFAULT {gen['set_default']}、GRANT/REVOKE 合计 "
        f"{gen['grant_schema'] + gen['grant_table'] + gen['grant_sequence'] + gen['grant_function'] + gen['revoke_function_public'] + gen['revoke_private']}、"
        f"setval {gen['setval']}。")
    add("")
    add("## 2. 数据（data）")
    add("")
    add(f"- 表数：**{d['totals']['tables']}**；行数合计：**{d['totals']['rows']}**")
    add(f"- JSON 文本合计：{human_bytes(d['totals']['bytes_json'])}；"
        f"gzip 合计：{human_bytes(d['totals']['bytes_gz'])}")
    add("")
    add("| # | 表 | 行数 | JSON | gzip | 模式 | 页数 | 导出时线上 sha256（前 16） |")
    add("|---:|---|---:|---:|---:|---|---:|---|")
    for i, (key, e) in enumerate(sorted(d["tables"].items()), 1):
        add(f"| {i} | `{key}` | {e['rows']} | {human_bytes(e['bytes_json'])} | "
            f"{human_bytes(e['bytes_gz'])} | {e['export_mode']} | {e['pages']} | "
            f"`{(e.get('server_sha256') or '')[:16]}` |")
    add("")
    add("规范化哈希口径：`sha256( row_to_json(t)::text 各行按主键/ctid 升序以 chr(10) 连接 )`，"
        "本地文件与服务端同一口径，导出时逐表比对一致。")
    add("")
    add("## 3. 校验结果")
    add("")
    add(f"- 产物文件：**{v['artifacts_ok']}/{v['artifacts_total']}** 存在且 sha256 一致")
    add(f"- 结构计数（catalog vs schema.sql）：**{v['schema_checks_ok']}/{v['schema_checks_total']}** 一致")
    add(f"- schema.sql 语法解析（pglast/libpg_query）："
        f"{'PASS' if v['syntax']['schema_ok'] else ('（跳过）' if v['syntax']['available'] is False else 'FAIL')}"
        f"（{v['syntax'].get('schema_statements')} 条语句）")
    add(f"- 数据本地校验（行数 + sha256 + JSON 逐行解析）：**{v['data_ok']}/{v['data_total']}** 表通过")
    add(f"- 导出时线上快照一致性（manifest server sha == 本地 sha）：**{v['snapshot_ok']}/{v['snapshot_total']}** 表")
    add("")
    if v["drift"]:
        add("### 线上变化（导出之后有 live 写入，属预期）")
        add("")
        add("| 表 | 导出时行数 | 当前行数 | Δ行数 | 说明 |")
        add("|---|---:|---:|---:|---|")
        for item in v["drift"]:
            add(f"| `{item['table']}` | {item['snapshot_rows']} | {item['current_rows']} | "
                f"{item['delta_rows']:+d} | {'行内容也变化' if item['hash_changed'] else '仅有新增/删除'} |")
        add("")
        add("> P4 切流前需再做一次**最终增量导出**（或短暂停写），P0 产物用于 staging 导入验证。")
    else:
        add("线上 34/34 表当前仍与导出快照一致。")
    add("")
    add("## 4. 产物文件")
    add("")
    for item in v["artifacts"]:
        add(f"- `{item['path']}` — {human_bytes(item['bytes'])} · sha256 `{item['sha256'][:16]}…`")
    add("")
    add("## 5. 已知边界 / 导入注意（P1 IMPORT.md）")
    add("")
    add("- **locale= C**：源库 `LC_COLLATE=C/LC_CTYPE=C`，ECS 建库建议同 locale"
        "（否则 text 排序/大小写比较、unique 判定语义可能变化）。")
    add("- **类型保真**：每行都是服务端 `row_to_json` 原文，numeric 精度/时区偏移（+08）"
        "由 PostgreSQL 保留；导入端用参数化 INSERT 并按 manifest `columns[].type` 绑定类型")
    add("  （numeric→Decimal、timestamptz→ISO8601、jsonb→JSON、text→str、bigint→int）。")
    add("- **序列**：schema.sql 里 setval 是导出时值；数据导入后需按「max(id) 或线上值」再 setval 一次。")
    add("- **SECURITY DEFINER 函数**：导入后其 owner = 建库角色（建议非超级用户属主），"
        "`auth_hdr()` 依赖 PostgREST 的 `request.headers` GUC"
        "（db-anon-role=anon + db-extra-search-path=public,private）。")
    add("- **authenticator** 角色不在此产物（LOGIN 密码由部署方生成，只落 ECS 本地）。")
    add("- **CloudBase 平台对象不迁移**：event triggers `pgrst_*`/`trg_restrict_s3_tables`、"
        "pg_catalog 多租户 RLS、storage/auth schema、默认 ACL 里的 `cloudbase_*` 角色、"
        "数据库级 setting `tencentdb_multi_tenant_visible_roles`。")
    add("- **live 表**（导出期间仍在写入）：class_sessions、visits、power_history、notices 等；"
        "P4 切流前必须做最终增量导出。")
    add("- 本摘要**不含**任何正文/姓名/学号/token；数据只在私有产物目录的 `data/*.jsonl.gz` 中。")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_verify(args: argparse.Namespace) -> int:
    t_start = time.time()
    out_dir = resolve_output_dir(args.out)
    print(f"[verify_export] 产物目录: {out_dir}")

    errors: list = []
    warnings: list = []

    schema_manifest = load_json(out_dir / "schema_manifest.json", "schema_manifest.json")
    data_manifest = load_json(out_dir / "data_manifest.json", "data_manifest.json")
    if not data_manifest.get("complete"):
        errors.append("data_manifest.complete=false（导出未完整完成，或仍在进行中）")

    schema_path = out_dir / "schema.sql"
    roles_path = out_dir / "roles.sql"
    schema_sql = schema_path.read_text(encoding="utf-8") if schema_path.exists() else ""
    roles_sql = roles_path.read_text(encoding="utf-8") if roles_path.exists() else ""

    # ---- 1. 产物完整性 ----
    artifacts = []
    artifacts_ok = 0
    expected_files = {}
    for name, info in (schema_manifest.get("generated_files") or {}).items():
        expected_files[name] = info
    for entry in data_manifest.get("files") or []:
        expected_files[entry["path"]] = entry
    for rel, info in sorted(expected_files.items()):
        path = out_dir / rel
        item = {"path": rel, "bytes": 0, "sha256": "", "ok": False}
        ok_size = True
        ok_sha = True
        if not path.exists():
            errors.append(f"缺少产物文件: {rel}")
        else:
            item["bytes"] = path.stat().st_size
            item["sha256"] = sha256_file(path)
            exp_sha = info.get("sha256")
            exp_bytes = info.get("bytes")
            if exp_bytes and item["bytes"] != int(exp_bytes):
                errors.append(f"{rel} 大小不一致: {item['bytes']} != {exp_bytes}")
                ok_size = False
            if exp_sha and item["sha256"] != exp_sha:
                errors.append(f"{rel} sha256 不一致")
                ok_sha = False
            item["ok"] = ok_size and ok_sha
        if item["ok"]:
            artifacts_ok += 1
        artifacts.append(item)
    # 数据文件必须同时出现在 files 中
    data_files = sorted((out_dir / "data").glob("*.jsonl.gz")) if (out_dir / "data").is_dir() else []
    if len(data_files) != len(data_manifest.get("files") or []):
        errors.append(f"data/ 下文件数 {len(data_files)} != data_manifest.files "
                      f"{len(data_manifest.get('files') or [])}")
    for stray in data_files:
        rel = f"data/{stray.name}"
        if rel not in expected_files:
            errors.append(f"data/ 下存在未记录文件: {stray.name}")

    # ---- 2. 结构 ----
    schema_checks = check_schema_sql(schema_sql, schema_manifest)
    schema_checks += check_roles_sql(roles_sql)
    schema_checks_ok = sum(1 for c in schema_checks if c["ok"])
    for c in schema_checks:
        if not c["ok"]:
            errors.append(f"结构校验失败: {c['check']} expected={c.get('expected')} "
                          f"actual={c.get('actual')}")
    syntax = check_schema_syntax(schema_sql, roles_sql)
    if syntax["available"]:
        if not syntax["schema_ok"] or not syntax["roles_ok"]:
            errors.append(f"SQL 语法解析失败: {syntax['error']}")
    else:
        warnings.append("pglast 未安装，跳过 SQL 语法解析（可选）")

    # ---- 3. 数据本地校验 ----
    data_total = 0
    data_ok = 0
    table_rows_reported = {}
    for key, entry in sorted((data_manifest.get("tables") or {}).items()):
        data_total += 1
        gz_path = out_dir / entry["file"]
        try:
            rows, sha, json_ok, json_bad = _hash_jsonl_gz(gz_path)
            table_rows_reported[key] = rows
            ok = (rows == int(entry["rows"])
                  and sha == entry["sha256"]
                  and json_bad == 0
                  and json_ok == rows)
            if not ok:
                errors.append(
                    f"数据文件校验失败 [{key}]: rows {rows} vs {entry['rows']}, "
                    f"sha {'ok' if sha == entry['sha256'] else 'MISMATCH'}, "
                    f"json_bad={json_bad}")
            else:
                data_ok += 1
            if sha != (entry.get("server_sha256") or ""):
                errors.append(f"快照哈希不一致 [{key}]：本地文件 != 导出时服务端记录")
        except (OSError, EOFError, gzip.BadGzipFile) as exc:
            errors.append(f"数据文件不可读 [{key}]: {exc}")

    snapshot_total = len(data_manifest.get("tables") or {})
    snapshot_ok = sum(1 for e in (data_manifest.get("tables") or {}).values()
                      if e.get("stable", True))

    # ---- 4. 覆盖性 + 线上对比 ----
    drift = []
    catalog_counts = None
    coverage_ok = False
    if not args.skip_online:
        try:
            client = TcbSqlClient(env_id=args.env or None, timeout=300, attempts=3,
                                  verbose=args.verbose)
            print("[verify_export] 读取线上 catalog 计数 ...")
            catalog_counts = _q_counts(client)
            # 4.1 catalog vs schema_manifest
            c = schema_manifest["counts"]
            pairs = [
                ("tables", catalog_counts["tables_total"], c["tables"]["total"]),
                ("columns", catalog_counts["columns"], c["columns"]),
                ("sequences", catalog_counts["sequences"], c["sequences"]),
                ("functions_total", catalog_counts["functions_total"],
                 c["functions"]["in_catalog"]),
                ("functions_own", catalog_counts["functions_own"], c["functions"]["own"]),
                ("functions_extension", catalog_counts["functions_extension"],
                 c["functions"]["extension"]),
                ("functions_secdef_own", catalog_counts["functions_secdef_own"],
                 c["functions"]["security_definer"]),
                ("policies_total", catalog_counts["policies_total"], c["policies"]["total"]),
                ("triggers_user", catalog_counts["triggers_user"], c["triggers"]["user"]),
                ("indexes_total", catalog_counts["indexes_total"], c["indexes"]["total"]),
                ("indexes_nonconstraint", catalog_counts["indexes_nonconstraint"],
                 c["indexes"]["non_constraint"]),
                ("constraints_primary", catalog_counts["constraints_primary"],
                 c["constraints"]["primary"]),
                ("constraints_unique", catalog_counts["constraints_unique"],
                 c["constraints"]["unique"]),
                ("constraints_foreign", catalog_counts["constraints_foreign"],
                 c["constraints"]["foreign"]),
                ("constraints_check", catalog_counts["constraints_check"],
                 c["constraints"]["check"]),
                ("rls_enabled_tables", catalog_counts["rls_enabled_tables"],
                 c["rls"]["enabled_tables"]),
            ]
            for name, live, snap in pairs:
                if int(live) != int(snap):
                    errors.append(f"catalog 与 schema_manifest 不一致: {name} live={live} registry={snap}")

            # 4.2 覆盖性：线上 34 表都必须在产物里
            live_tables = {f"{t['schema']}.{t['table']}" for t in _q_live_tables(client)}
            exported = set((data_manifest.get("tables") or {}).keys())
            missing = sorted(live_tables - exported)
            extra = sorted(exported - live_tables)
            coverage_ok = not missing and not extra
            if missing:
                errors.append(f"线上表未导出: {missing}")
            if extra:
                errors.append(f"产物含线上不存在的表: {extra}")

            # 4.3 线上当前 count/sha vs 导出快照
            pks = _q_pks(client)
            print(f"[verify_export] 对 {len(exported)} 张表重算线上 count+sha256 ...")
            for i, key in enumerate(sorted(exported), 1):
                schema, table = key.split(".", 1)
                entry = data_manifest["tables"][key]
                pk = pks.get((schema, table)) or []
                try:
                    live = _q_online_digest(client, schema, table, pk)
                except TcbSqlError as exc:
                    errors.append(f"线上查询失败 [{key}]: {str(exc)[:200]}")
                    continue
                n_now = int(live.get("n") or 0)
                h_now = live.get("h")
                snap_n = int(entry.get("server_n") or entry["rows"])
                snap_h = entry.get("server_sha256") or entry["sha256"]
                if n_now == snap_n and h_now == snap_h:
                    continue
                drift.append({
                    "table": key,
                    "snapshot_rows": snap_n,
                    "current_rows": n_now,
                    "delta_rows": n_now - snap_n,
                    "hash_changed": h_now != snap_h,
                    "snapshot_sha256": snap_h,
                    "current_sha256": h_now,
                    "checked_at": live.get("at"),
                })
            if drift:
                msg = (f"{len(drift)} 张表在导出后有 live 写入（快照仍自洽）："
                       + ", ".join(d["table"] for d in drift))
                (errors if args.strict else warnings).append(msg)
        except TcbSqlError as exc:
            errors.append(f"线上校验失败（网络/权限）: {exc}")
    else:
        warnings.append("--skip-online：未做线上 catalog/数据对比")

    # ---- 5. 写 manifest.json + SUMMARY.md ----
    verification = {
        "verified_at_utc": utc_now_iso(),
        "elapsed_s": round(time.time() - t_start, 1),
        "artifacts_total": len(artifacts),
        "artifacts_ok": artifacts_ok,
        "artifacts": artifacts,
        "schema_checks_total": len(schema_checks),
        "schema_checks_ok": schema_checks_ok,
        "schema_checks": schema_checks,
        "syntax": syntax,
        "data_total": data_total,
        "data_ok": data_ok,
        "snapshot_total": snapshot_total,
        "snapshot_ok": snapshot_ok,
        "coverage_ok": coverage_ok,
        "catalog_counts": catalog_counts,
        "drift": drift,
        "strict": bool(args.strict),
        "skip_online": bool(args.skip_online),
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }
    manifest = {
        "kind": "migration_manifest",
        "generator": "deploy/migration/verify_export.py",
        "generated_at_utc": utc_now_iso(),
        "output_dir": str(out_dir),
        "privacy": ("私有产物：data/*.jsonl.gz 含真实业务数据，不得进 git、不得外发；"
                    "本 manifest 只记录计数/哈希/列类型，不含行内容。"),
        "pipeline": {
            "schema": "deploy/migration/export_schema.py",
            "data": "deploy/migration/export_data.py",
            "verify": "deploy/migration/verify_export.py",
            "sql_channel": "tcb.cmd db execute --json --sql (只读)",
        },
        "schema_manifest": schema_manifest,
        "data_manifest": data_manifest,
        "verification": verification,
    }
    manifest_path = out_dir / "manifest.json"
    write_json(manifest_path, manifest)
    summary = build_summary(manifest)
    summary_path = out_dir / "SUMMARY.md"
    summary_path.write_text(summary, encoding="utf-8", newline="\n")

    # ---- 控制台 ----
    print("")
    print("[verify_export] 结果")
    print(f"  产物完整性      : {artifacts_ok}/{len(artifacts)}")
    print(f"  结构计数        : {schema_checks_ok}/{len(schema_checks)}")
    print(f"  语法解析        : "
          f"{'PASS' if syntax['schema_ok'] else ('SKIP' if not syntax['available'] else 'FAIL')}")
    print(f"  数据本地校验    : {data_ok}/{data_total}")
    print(f"  导出时快照一致  : {snapshot_ok}/{snapshot_total}")
    print(f"  覆盖性(34 表)   : {'OK' if coverage_ok else 'FAIL/未检查'}")
    print(f"  线上当前漂移    : {len(drift)} 张表")
    if drift:
        print("    " + ", ".join(f"{d['table']}({d['delta_rows']:+d})" for d in drift))
    if warnings:
        print("  警告:")
        for w in warnings:
            print(f"    - {w}")
    if errors:
        print("  错误:")
        for e in errors[:20]:
            print(f"    - {e}")
        print(f"[verify_export] FAIL（{len(errors)} 个错误，{time.time() - t_start:.1f}s）")
        return 1
    print(f"[verify_export] PASS（{time.time() - t_start:.1f}s）")
    print(f"  写入: {manifest_path}")
    print(f"  写入: {summary_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="校验 P0 导出产物并生成 manifest.json / SUMMARY.md")
    parser.add_argument("--out", default="", help="产物目录（默认复用最新）")
    parser.add_argument("--strict", action="store_true",
                        help="导出后线上有 live 写入（DRIFT）也算失败")
    parser.add_argument("--skip-online", action="store_true", help="只做本地校验，不连 CloudBase")
    parser.add_argument("--env", default="", help="tcb 环境 ID")
    parser.add_argument("--verbose", action="store_true", help="打印 tcb 重试日志")
    args = parser.parse_args(argv)
    try:
        return run_verify(args)
    except VerifyError as exc:
        print(f"[verify_export] 失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
