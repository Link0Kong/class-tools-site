#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_data.py — CloudBase PostgreSQL 全量数据只读导出（P0）

把 34 张表（public 29 + private 5）逐表导出为「一行一个 JSON 对象的 JSONL（gzip）」：

    <out>/data/<schema>.<table>.jsonl.gz
    <out>/data_manifest.json

数据保真
========
- 每行 = 服务端 ``row_to_json(t)::text`` 的**原文**（不再本地重排/重序列化）：
  numeric 精度、timestamptz 时区、jsonb、bool/int/text 等都由 PostgreSQL 自己序列化，
  导入端按 manifest 里的列类型参数化插入即可。
- 每表记录：行数 + **规范化 sha256**，且与**服务端同口径**核算（见下）。

一致性策略（CloudBase 只读通道单次调用 = 单事务，无法跨页共享快照）
====================================================================
- **小表（整表 JSON 文本 ≤ oneshot 上限，默认 4 MB）**：单条 SQL 一次取回
  ``n + sha256(string_agg(row_to_json(t)::text, chr(10) order by 主键)) + body``，
  单快照、天然一致；本地重算 sha256 与服务端比对。
- **大表（notices 25.7 MB、ppt_upload_chunks 32.2 MB）**：先取
  ``[主键..., 行长]`` 计划，再按字节预算（默认 4 MB/页，CloudBase 响应硬上限 10 MB）
  用**主键 keyset 分页**（复合 PK 用 ROW 比较；无 PK 用 ctid）取回；
  导出完成后用同一条 ``count + sha256(string_agg(...))`` 查询与服务端比对，
  不一致（导出期间线上有写入）→ 整表重试（默认 3 次），仍不一致则标记 ``stable=false``。
- 分页失败（PGResultTooLarge / 超时）自动减半页大小重试；每次 CLI 调用带超时+重试。

断点续跑
========
- 默认：清空 ``<out>/data/`` 下本工具的旧产物后全量重导（幂等覆盖）。
- ``--resume``：读已有 data_manifest.json，对每张表用本地文件 sha256 复核后跳过已完成表，
  只重导缺失/损坏/中断的表（已完成表不再访问远端数据）。

隐私：本脚本只打印表名/行数/字节数/耗时，**绝不打印行内容**；产物目录私有、不进仓库。

用法::

    python deploy/migration/export_data.py                 # 全量（复用最新产物目录）
    python deploy/migration/export_data.py --resume        # 断点续跑
    python deploy/migration/export_data.py --out <dir>     # 指定产物目录
    python deploy/migration/export_data.py --only public.notices   # 调试单表
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tcb_sql import (  # noqa: E402
    TcbSqlClient,
    TcbSqlError,
    human_bytes,
    latest_output_dir,
    qualified_name,
    quote_ident,
    resolve_output_dir,
    sha256_file,
    utc_now_iso,
    write_json,
)

SCHEMAS = ("public", "private")
SCHEMA_IN = "n.nspname in ($$public$$, $$private$$)"

DEFAULT_PAGE_TARGET = 4 * 1024 * 1024        # 单页 JSON 文本预算（响应硬上限 10MB）
DEFAULT_ONESHOT_LIMIT = 4 * 1024 * 1024      # 小表一次性取回上限
MAX_PAGE_ROWS = 5000
DEFAULT_TABLE_RETRIES = 3

# CloudBase 单次响应硬上限 10MB，超限报 FailedOperation.PGResultTooLarge
_TOO_LARGE_HINTS = ("response limit", "PGResultTooLarge", "10 MB")


class ExportDataError(RuntimeError):
    """数据导出失败（不可恢复）。"""


class ResultTooLarge(ExportDataError):
    """单次响应超过 CloudBase 10MB 上限（可减少页大小重试）。"""


def _is_too_large(exc: Exception) -> bool:
    msg = str(exc)
    return any(h in msg for h in _TOO_LARGE_HINTS)


def _is_timeout(exc: Exception) -> bool:
    return "超时" in str(exc)


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------

def _q_tables(cli: TcbSqlClient) -> list:
    return cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'table', cl.relname,
          'rls', cl.relrowsecurity,
          'columns', (
            select json_agg(json_build_object(
              'name', a.attname, 'attnum', a.attnum,
              'type', pg_catalog.format_type(a.atttypid, a.atttypmod),
              'notnull', a.attnotnull, 'identity', nullif(a.attidentity::text, $$ $$)
            ) order by a.attnum)
            from pg_attribute a
            where a.attrelid = cl.oid and a.attnum > 0 and not a.attisdropped)
        ) order by n.nspname, cl.relname), '[]')::text
        from pg_class cl join pg_namespace n on n.oid = cl.relnamespace
        where {SCHEMA_IN} and cl.relkind = $$r$$
        """
    )


def _q_primary_keys(cli: TcbSqlClient) -> dict:
    rows = cli.fetch_json(
        f"""
        select coalesce(json_agg(json_build_object(
          'schema', n.nspname, 'table', cl.relname,
          'columns', (
            select json_agg(json_build_object(
              'name', a.attname,
              'type', pg_catalog.format_type(a.atttypid, a.atttypmod))
              order by k.ord)
            from unnest(co.conkey) with ordinality k(attnum, ord)
            join pg_attribute a on a.attrelid = co.conrelid and a.attnum = k.attnum)
        ) order by n.nspname, cl.relname), '[]')::text
        from pg_constraint co
        join pg_class cl on cl.oid = co.conrelid
        join pg_namespace n on n.oid = cl.relnamespace
        where {SCHEMA_IN} and co.contype = $$p$$
        """
    )
    return {(r["schema"], r["table"]): r["columns"] for r in rows}


# ---------------------------------------------------------------------------
# SQL 片段
# ---------------------------------------------------------------------------

def _order_expr(pk: list) -> str:
    if pk:
        return ", ".join(f't.{quote_ident(c["name"])}' for c in pk)
    return "t.ctid"


def _key_columns(pk: list) -> list:
    if pk:
        return [{"name": c["name"], "type": c["type"], "expr": f't.{quote_ident(c["name"])}::text'}
                for c in pk]
    return [{"name": "ctid", "type": "tid", "expr": "t.ctid::text"}]


def _start_condition(pk: list, key_values: list) -> str:
    """keyset 分页的 WHERE 条件（排他）。"""
    if pk:
        exprs = []
        for col, val in zip(pk, key_values):
            exprs.append(f"{_sql_lit(val)}::{col['type']}")
        if len(exprs) == 1:
            return f't.{quote_ident(pk[0]["name"])} > {exprs[0]}'
        left = "(" + ", ".join(f't.{quote_ident(c["name"])}' for c in pk) + ")"
        return f"{left} > ({', '.join(exprs)})"
    return f"t.ctid > {_sql_lit(key_values[0])}::tid"


def _sql_lit(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _fq(table: dict) -> str:
    return qualified_name(table["schema"], table["table"])


def _order_by_alias(pk: list) -> list:
    if pk:
        return [f't.{quote_ident(c["name"])}' for c in pk]
    return ["t.ctid"]


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------

def export_oneshot(cli: TcbSqlClient, table: dict, pk: list) -> tuple:
    """单快照取整表：返回 (body_text, n, server_sha, captured_at)。"""
    order = ", ".join(_order_by_alias(pk))
    sql = (
        "select json_build_object("
        "'n', count(*), "
        "'h', encode(digest(coalesce(string_agg(row_to_json(t)::text, chr(10) "
        f"order by {order}), ''), 'sha256'), 'hex'), "
        "'at', now()::text, "
        f"'body', coalesce(string_agg(row_to_json(t)::text, chr(10) order by {order}), '')"
        f")::text from {_fq(table)} t"
    )
    try:
        payload = cli.fetch_json(sql, timeout=300)
    except TcbSqlError as exc:
        if _is_too_large(exc):
            raise ResultTooLarge(str(exc))
        raise
    body = payload.get("body") or ""
    n = int(payload.get("n") or 0)
    sha = payload.get("h")
    rows = body.split("\n") if body else []
    if len(rows) != n:
        raise ExportDataError(
            f"单快照行数不一致: payload.n={n} body_rows={len(rows)}")
    if rows and hashlib.sha256(body.encode("utf-8")).hexdigest() != sha:
        raise ExportDataError("单快照本地 hash 与服务端不一致")
    if not rows and sha != hashlib.sha256(b"").hexdigest():
        raise ExportDataError("空表单快照 hash 异常")
    return body, n, sha, payload.get("at"), 1


def fetch_plan(cli: TcbSqlClient, table: dict, pk: list) -> list:
    """取 [主键..., 行 JSON 字节长度] 计划（一次查询，用于按字节预算分页）。"""
    key_exprs = ", ".join(k["expr"] for k in _key_columns(pk))
    order = ", ".join(_order_by_alias(pk))
    sql = (
        "select coalesce(json_agg(json_build_array("
        f"{key_exprs}, octet_length(row_to_json(t)::text)) order by {order}), '[]')::text "
        f"from {_fq(table)} t"
    )
    rows = cli.fetch_json(sql, timeout=300)
    if not rows:
        return []
    key_count = len(_key_columns(pk))
    plan = []
    for item in rows:
        if not isinstance(item, list) or len(item) != key_count + 1:
            raise ExportDataError(f"计划行格式异常: {type(item)}")
        plan.append({"key": item[:key_count], "len": int(item[key_count])})
    return plan


def fetch_page(cli: TcbSqlClient, table: dict, pk: list, start_key, count: int) -> list:
    """按 keyset 取一页，返回 [(row_json_text, key_values), ...]。"""
    key_exprs = ", ".join(k["expr"] for k in _key_columns(pk))
    order = ", ".join(_order_by_alias(pk))
    where = f" where {_start_condition(pk, start_key)}" if start_key is not None else ""
    sql = (
        f"select row_to_json(t)::text as __row, {key_exprs} as __k "
        f"from {_fq(table)} t{where} order by {order} limit {int(count)}"
    )
    try:
        res = cli.execute(sql, timeout=300)
    except TcbSqlError as exc:
        if _is_too_large(exc):
            raise ResultTooLarge(str(exc))
        raise
    out = []
    key_count = len(_key_columns(pk))
    for row in res.rows:
        if len(row) != key_count + 1 or not isinstance(row[0], str):
            raise ExportDataError("分页返回格式异常")
        keys = row[1:]
        if len(keys) == 1:
            keys = [keys[0]]
        out.append({"row": row[0], "key": keys})
    return out


def server_digest(cli: TcbSqlClient, table: dict, pk: list) -> tuple:
    """整表服务端 count + sha256（与本地文件同口径）。"""
    order = ", ".join(_order_by_alias(pk))
    sql = (
        "select json_build_object("
        "'n', count(*), "
        "'h', encode(digest(coalesce(string_agg(row_to_json(t)::text, chr(10) "
        f"order by {order}), ''), 'sha256'), 'hex'), "
        "'at', now()::text"
        f")::text from {_fq(table)} t"
    )
    payload = cli.fetch_json(sql, timeout=300)
    return int(payload.get("n") or 0), payload.get("h"), payload.get("at")


# ---------------------------------------------------------------------------
# 文件
# ---------------------------------------------------------------------------

def write_part(part_path: Path, body: str) -> None:
    with open(part_path, "w", encoding="utf-8", newline="\n") as fh:
        if body:
            fh.write(body)
            fh.write("\n")


def append_part(part_path: Path, rows: list) -> None:
    with open(part_path, "a", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(row)
            fh.write("\n")


def hash_part(part_path: Path) -> tuple:
    """流式重算 (rows, sha256(行文本以 \\n 连接))。"""
    h = hashlib.sha256()
    rows = 0
    with open(part_path, "rb") as fh:
        first = True
        for line in fh:
            if line.endswith(b"\n"):
                line = line[:-1]
            if not first:
                h.update(b"\n")
            h.update(line)
            first = False
            rows += 1
    return rows, h.hexdigest()


def gzip_part(part_path: Path, gz_path: Path) -> int:
    """把 .part 压成 .jsonl.gz（mtime=0，同内容 → 同字节，便于复跑比对）。"""
    size = 0
    with open(part_path, "rb") as src, open(gz_path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw,
                           compresslevel=6, mtime=0) as gz:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                gz.write(chunk)
                size += len(chunk)
    return size


# ---------------------------------------------------------------------------
# 单表导出
# ---------------------------------------------------------------------------

def export_table(cli: TcbSqlClient, table: dict, pk: list,
                 page_target: int,
                 data_dir: Path, table_retries: int) -> dict:
    key = f"{table['schema']}.{table['table']}"
    attempts = 0
    last_error = None
    while attempts < max(1, table_retries):
        attempts += 1
        t0 = time.time()
        part_path = data_dir / f"{key}.jsonl.part"
        gz_path = data_dir / f"{key}.jsonl.gz"
        for p in (part_path, gz_path):
            if p.exists():
                p.unlink()
        try:
            plan = None
            mode = "oneshot"
            pages = 1
            try:
                body, n, sha, captured_at, pages = export_oneshot(cli, table, pk)
                write_part(part_path, body)
            except ResultTooLarge:
                mode = "paged"
                plan = fetch_plan(cli, table, pk)
                cursor = None
                pos = 0
                page_count = 0
                while pos < len(plan):
                    remaining = plan[pos:]
                    take, acc = 0, 0
                    for item in remaining:
                        if take and (acc + item["len"] > page_target
                                     or take >= MAX_PAGE_ROWS):
                            break
                        acc += item["len"]
                        take += 1
                    count = max(1, take)
                    while True:
                        try:
                            rows = fetch_page(cli, table, pk, cursor, count)
                            break
                        except ResultTooLarge:
                            if count <= 1:
                                raise
                            count = max(1, count // 2)
                    if len(rows) != count:
                        raise ExportDataError(
                            f"分页行数不符（第 {page_count + 1} 页: 期望 {count}, "
                            f"实到 {len(rows)}；导出期间有写入）")
                    expected_lens = [p["len"] for p in remaining[:len(rows)]]
                    got_lens = [len(r["row"].encode("utf-8")) for r in rows]
                    if got_lens != expected_lens:
                        raise ExportDataError(
                            f"分页行内容变化（第 {page_count + 1} 页：长度与服务端计划不符，"
                            "导出期间有写入）")
                    append_part(part_path, [r["row"] for r in rows])
                    cursor = rows[-1]["key"]
                    pos += len(rows)
                    page_count += 1
                pages = page_count
                if not plan:
                    write_part(part_path, "")
                local_rows, local_sha = hash_part(part_path)
                n_after, sha_after, captured_at = server_digest(cli, table, pk)
                if local_rows != n_after or local_sha != sha_after:
                    raise ExportDataError(
                        f"整表 hash 不一致（本地 {local_rows} 行 / 线上 {n_after} 行，"
                        "导出期间线上有写入）")
                n = n_after
                sha = sha_after
            # 落盘 gzip
            rows_count, local_sha = hash_part(part_path) if part_path.exists() else (0, None)
            if part_path.exists():
                bytes_json = part_path.stat().st_size
            else:
                bytes_json = 0
            if rows_count != n or (rows_count and local_sha != sha):
                raise ExportDataError(
                    f"本地文件复算不一致（rows {rows_count} vs {n}）")
            if rows_count == 0:
                # 空表：写一个合法空 gzip 流（同内容 → 同字节）
                with open(gz_path, "wb") as raw:
                    with gzip.GzipFile(filename="", mode="wb", fileobj=raw,
                                       compresslevel=6, mtime=0):
                        pass
                bytes_json = 0
            else:
                gzip_part(part_path, gz_path)
            if part_path.exists():
                part_path.unlink()
            return {
                "schema": table["schema"], "table": table["table"],
                "file": f"data/{key}.jsonl.gz",
                "rows": n,
                "sha256": sha,
                "server_n": n,
                "server_sha256": sha,
                "server_captured_at": captured_at,
                "bytes_json": bytes_json,
                "bytes_gz": gz_path.stat().st_size,
                "export_mode": mode,
                "pages": pages if isinstance(pages, int) else len(pages),
                "columns": [{"name": c["name"], "type": c["type"],
                             "notnull": bool(c["notnull"])}
                            for c in table.get("columns") or []],
                "pk": pk,
                "order_by": _order_by_alias(pk),
                "order_kind": "pk" if pk else "ctid",
                "stable": True,
                "attempts": attempts,
                "duration_s": round(time.time() - t0, 1),
                "exported_at_utc": utc_now_iso(),
            }
        except (TcbSqlError, ExportDataError) as exc:
            last_error = exc
            for p in (part_path, gz_path):
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
            if attempts >= max(1, table_retries):
                break
            print(f"[export_data] {key} 第 {attempts} 次失败，重试: {str(exc)[:200]}")
            time.sleep(2.0)
    raise ExportDataError(f"{key} 导出失败（{attempts} 次）: {last_error}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_export(args: argparse.Namespace) -> int:
    t_start = time.time()
    out_dir = resolve_output_dir(args.out)
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "data_manifest.json"
    existing = {}
    if args.resume and manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing = prev.get("tables") or {}
            print(f"[export_data] --resume: 已有 {len(existing)} 张表记录")
        except (json.JSONDecodeError, OSError):
            existing = {}
    if not args.resume:
        for p in list(data_dir.glob("*.jsonl.gz")) + list(data_dir.glob("*.jsonl.part")):
            p.unlink()

    client = TcbSqlClient(env_id=args.env or None, timeout=300, attempts=3, verbose=True)
    ping = client.ping()
    print(f"[export_data] 已连接 {ping['database']} ({ping['version'][:50]}...)")

    print("[export_data] 读取表/列/主键 ...")
    tables = _q_tables(client)
    pks = _q_primary_keys(client)
    tables.sort(key=lambda t: (t["schema"], t["table"]))
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        tables = [t for t in tables if f"{t['schema']}.{t['table']}" in wanted]
        if not tables:
            raise ExportDataError(f"--only 没有匹配到表: {sorted(wanted)}")
    print(f"[export_data] 待导出 {len(tables)} 张表（每表单快照/大表分页）")

    manifest_tables = {}
    if existing and args.resume:
        manifest_tables.update(existing)
    total_rows = 0
    for idx, table in enumerate(tables, 1):
        key = f"{table['schema']}.{table['table']}"
        pk = pks.get((table["schema"], table["table"])) or []
        # --resume：已完成且本地文件 sha 复核通过的跳过
        if args.resume and key in manifest_tables:
            entry = manifest_tables[key]
            gz_path = out_dir / entry["file"]
            if gz_path.exists() and sha256_file(gz_path) == entry.get("artifact_sha256"):
                print(f"[export_data] ({idx}/{len(tables)}) {key:<32} 跳过（resume 已完成）")
                total_rows += int(entry.get("rows") or 0)
                continue
            manifest_tables.pop(key, None)
        print(f"[export_data] ({idx}/{len(tables)}) {key:<32} 导出中 ...", end=" ", flush=True)
        entry = export_table(
            client, table, pk,
            page_target=args.page_target,
            data_dir=data_dir,
            table_retries=args.table_retries,
        )
        entry["artifact_sha256"] = sha256_file(out_dir / entry["file"])
        manifest_tables[key] = entry
        total_rows += int(entry["rows"])
        print(f"{entry['rows']} 行 / JSON {human_bytes(entry['bytes_json'])} / "
              f"gz {human_bytes(entry['bytes_gz'])} / {entry['export_mode']} "
              f"/ {entry['duration_s']}s")
        # 每表落一次 manifest（崩溃后可 resume）
        partial = build_manifest(out_dir, manifest_tables, args, ping, t_start,
                                 complete=False)
        write_json(manifest_path, partial)
        (out_dir / "_checkpoint.json").write_text(json.dumps({
            "updated_at_utc": utc_now_iso(),
            "tables_done": sorted(manifest_tables),
            "last_table": key,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = build_manifest(out_dir, manifest_tables, args, ping, t_start, complete=True)
    write_json(manifest_path, manifest)
    if (out_dir / "_checkpoint.json").exists():
        (out_dir / "_checkpoint.json").unlink()

    print("")
    print("[export_data] 完成")
    print(f"  产物目录    : {out_dir}")
    print(f"  表数        : {len(manifest_tables)}")
    print(f"  行数合计    : {total_rows}")
    print(f"  JSON 合计   : {human_bytes(manifest['totals']['bytes_json'])}")
    print(f"  gzip 合计   : {human_bytes(manifest['totals']['bytes_gz'])}")
    unstable = [k for k, v in manifest_tables.items() if not v.get("stable", True)]
    if unstable:
        print(f"  ⚠ 导出期间数据变动（已标记 stable=false）: {unstable}")
    print(f"  耗时        : {time.time() - t_start:.1f}s")
    return 0


def build_manifest(out_dir: Path, tables: dict, args: argparse.Namespace,
                   ping: dict, t_start: float, *, complete: bool) -> dict:
    entries = {k: tables[k] for k in sorted(tables)}
    files = []
    for key, entry in entries.items():
        files.append({
            "path": entry["file"],
            "bytes": entry["bytes_gz"],
            "sha256": entry.get("artifact_sha256"),
            "rows": entry["rows"],
        })
    return {
        "kind": "data_manifest",
        "generator": "deploy/migration/export_data.py",
        "generated_at_utc": utc_now_iso(),
        "elapsed_s": round(time.time() - t_start, 1),
        "complete": complete,
        "source": {
            "env_id": args.env or "tool-d4gosudok46e0e081",
            "database": ping.get("database"),
            "pg_version": ping.get("version"),
            "timezone": ping.get("timezone"),
            "datestyle": ping.get("datestyle"),
            "search_path": ping.get("search_path"),
        },
        "settings": {
            "page_target_bytes": args.page_target,
            "oneshot_limit_bytes": args.oneshot_limit,
            "table_retries": args.table_retries,
            "max_page_rows": MAX_PAGE_ROWS,
            "row_encoding": "JSONL：每行 = 服务端 row_to_json(t)::text 原文（UTF-8）",
            "hash_spec": "sha256( 各行文本以 chr(10) 连接 )，顺序 = 主键 ASC / ctid ASC",
            "cloudbase_response_limit_bytes": 10 * 1024 * 1024,
            "import_hint": ("导入端按 columns[].type 参数化 INSERT；numeric 用 Decimal、"
                            "timestamptz 用 ISO8601、jsonb 直接 json；"
                            "每表 rows/sha256 与 manifest 对齐。"),
        },
        "totals": {
            "tables": len(entries),
            "rows": sum(int(e["rows"]) for e in entries.values()),
            "bytes_json": sum(int(e["bytes_json"]) for e in entries.values()),
            "bytes_gz": sum(int(e["bytes_gz"]) for e in entries.values()),
        },
        "files": files,
        "tables": entries,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="CloudBase → PG18 全量数据只读导出（JSONL gzip + data_manifest.json）")
    parser.add_argument("--out", default="", help="产物目录（默认复用最新）")
    parser.add_argument("--resume", action="store_true", help="断点续跑（跳过已完成表）")
    parser.add_argument("--only", default="", help="仅导出指定表（逗号分隔，调试用）")
    parser.add_argument("--page-target", type=int, default=DEFAULT_PAGE_TARGET,
                        help="大表单页 JSON 字节预算（默认 4MB；CloudBase 响应上限 10MB）")
    parser.add_argument("--oneshot-limit", type=int, default=DEFAULT_ONESHOT_LIMIT,
                        help="小表单快照取回上限（默认 4MB）")
    parser.add_argument("--table-retries", type=int, default=DEFAULT_TABLE_RETRIES,
                        help="每表失败/不一致重试次数（默认 3）")
    parser.add_argument("--env", default="", help="tcb 环境 ID")
    args = parser.parse_args(argv)
    try:
        return run_export(args)
    except (TcbSqlError, ExportDataError) as exc:
        print(f"[export_data] 失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
