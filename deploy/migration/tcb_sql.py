#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tcb_sql.py — CloudBase PostgreSQL 只读 SQL 通道（P0 迁移导出专用）

背景
====
CloudBase 环境 ``tool-d4gosudok46e0e081``（PG 17.11）只提供 CLI 通道：

    tcb.cmd db execute --json --sql "<只读 SQL>"

- 默认角色（非 ``--role postgres``，实测该角色静默失败）可读 ``public`` / ``private`` /
  ``pg_catalog``；本模块只允许只读语句。
- stdout 是纯 JSON：``{"data": {"Columns": [...], "ColumnTypes": [...],
  "Rows": ["[\\"v1\\", \\"v2\\"]", ...], "RequestId": ..., "ExecutionTimeMs": ...}}``
  ——``Rows`` 的每一项是「一行」的 JSON 文本；单元格值会被 CLI 统一转成 JSON 字符串
  （``1.20`` / ``true`` / ``2026-11-18 13:23:19+08`` / ``\\x00ff`` 都是字符串），
  **复杂类型在 CLI 层会丢类型信息**。所以导出层统一用「服务端先拼成一段 JSON 文本，
  只取一个 text 列」的方式取数（见 ``fetch_json``），避免 CLI 的字符串化与 NULL 歧义。

安全边界（红线）
================
- 只允许单条 ``select`` / ``with`` / ``show`` 语句；拒绝 DML/DDL/TCL 关键字、多语句；
  所有导出动作对 CloudBase 都是只读的。
- 不在任何日志/异常里打印行内容（可能含隐私）；只打印列名/行数/耗时。
- 不读 ``C:\\briefdesk\\secrets\\**``。

用法
====
    from tcb_sql import TcbSqlClient
    cli = TcbSqlClient()                     # 默认 300s 超时、3 次重试
    q = cli.execute("select count(*)::text as n from public.notices")
    print(q.scalar())                        # '184'

    # 单行单列 JSON 文本（推荐所有结构化取数都用它）
    data = cli.fetch_json(
        "select coalesce(json_agg(json_build_object('name', c.relname) "
        "order by c.relname), '[]')::text from pg_class c where c.relkind = 'r'"
    )

命令行自检：

    python deploy/migration/tcb_sql.py --sql "select 1 as x"
    python deploy/migration/tcb_sql.py --file query.sql --show
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 300.0          # 单次 CLI 调用超时（秒）——大表 digest 需要
DEFAULT_RETRIES = 3              # 总尝试次数（含第一次）
DEFAULT_RETRY_DELAYS = (1.5, 4.0)  # 第 2/3 次尝试前的等待（秒）

# 只读语句允许的起始关键字（去注释、去空白后）
ALLOWED_STARTERS = ("select", "with", "show")

# 禁止出现的 SQL 关键字（整词匹配；只读导出绝不需要）
# 注：select/with 里能「写」的只有 data-modifying CTE（insert/update/delete/merge）
# 和少数有副作用的函数（见 FORBIDDEN_FUNCS），这里做保守拦截。
FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "merge", "upsert",
    "create", "alter", "drop", "truncate",
    "grant", "revoke", "copy", "vacuum", "analyze", "cluster",
    "reindex", "refresh", "lock", "listen", "notify",
    "execute", "prepare", "deallocate",
    "begin", "commit", "rollback", "savepoint",
    "import",
)
# 有副作用/能改状态的内置函数（select 里也能调用）
FORBIDDEN_FUNCS = (
    "set_config", "nextval", "setval", "pg_terminate_backend",
    "pg_cancel_backend", "pg_reload_conf", "pg_rotate_logfile",
    "lo_import", "lo_export", "lo_unlink", "dblink", "pg_create_restore_point",
    "pg_switch_wal", "pg_promote", "pg_drop_replication_slot",
)
_FORBIDDEN_FUNC_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(f) for f in FORBIDDEN_FUNCS) + r")\s*\("
)
_FORBIDDEN_RE = re.compile(
    r"\b(" + "|".join(sorted(FORBIDDEN_KEYWORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_LEADING_COMMENT_RE = re.compile(
    r"\A(?:\s+|--[^\n]*(?:\n|\Z)|/\*.*?\*/)+", re.DOTALL
)
# 确定性 SQL 错误：重试无意义，直接失败
_NON_RETRYABLE_HINTS = (
    "SQLSTATE 42",           # syntax error / undefined object ...
    "SQLSTATE 42501",        # permission denied
    "does not exist",
    "permission denied",
    "unterminated",
    "syntax error",
    "response limit",        # PGResultTooLarge：10MB 响应上限，需减少单页行数
    "PGResultTooLarge",
)


class SqlValidationError(ValueError):
    """SQL 未通过只读白名单校验（本地拒绝，不发请求）。"""


class TcbSqlError(RuntimeError):
    """tcb CLI 调用失败（含重试耗尽）。"""

    def __init__(self, message: str, *, attempts: int = 1,
                 exit_code: Optional[int] = None, code: str = "",
                 request_id: str = "", sql: str = "") -> None:
        super().__init__(message)
        self.attempts = attempts
        self.exit_code = exit_code
        self.code = code
        self.request_id = request_id
        self.sql = sql


@dataclass
class QueryResult:
    """一次只读查询的结果。"""

    columns: List[str] = field(default_factory=list)
    column_types: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    request_id: str = ""
    execution_ms: int = 0
    raw_stdout_bytes: int = 0
    elapsed_s: float = 0.0

    # -- 便捷访问 -------------------------------------------------------
    def as_dicts(self) -> List[dict]:
        return [dict(zip(self.columns, row)) for row in self.rows]

    def one(self) -> dict:
        if len(self.rows) != 1:
            raise TcbSqlError(f"期望 1 行，实际 {len(self.rows)} 行")
        return self.as_dicts()[0]

    def scalar(self) -> Any:
        if len(self.rows) != 1 or len(self.rows[0]) != 1:
            raise TcbSqlError(f"期望 1 行 1 列，实际 {len(self.rows)} 行 "
                              f"{len(self.rows[0]) if self.rows else 0} 列")
        return self.rows[0][0]

    def first_cell(self) -> Any:
        if not self.rows:
            return None
        return self.rows[0][0] if self.rows[0] else None


# ---------------------------------------------------------------------------
# SQL 标识符 / 字面量工具
# ---------------------------------------------------------------------------

def quote_ident(name: str) -> str:
    """PostgreSQL 标识符引用（只在必要时加双引号）。"""
    if re.fullmatch(r"[a-z_][a-z0-9_$]*", name) and name not in _RESERVED:
        return name
    return '"' + name.replace('"', '""') + '"'


# 只需要覆盖可能出现在本库表名/列名里的保留字；多引号也无害，这里给常见集合。
_RESERVED = {
    "all", "and", "any", "as", "asc", "both", "case", "cast", "check", "collate",
    "column", "constraint", "create", "current_date", "current_time",
    "current_timestamp", "current_user", "default", "desc", "distinct", "do",
    "else", "end", "except", "false", "fetch", "for", "foreign", "from", "grant",
    "group", "having", "in", "initially", "intersect", "into", "is", "join",
    "lateral", "leading", "limit", "localtime", "localtimestamp", "not", "null",
    "offset", "on", "only", "or", "order", "primary", "references", "returning",
    "select", "session_user", "some", "symmetric", "table", "then", "to",
    "trailing", "true", "union", "unique", "user", "using", "variadic", "when",
    "where", "window", "with", "authorization", "binary", "collation",
    "concurrently", "cross", "current_role", "current_schema", "freeze",
    "full", "ilike", "inner", "isnull", "left", "like", "natural", "notnull",
    "outer", "over", "overlaps", "placing", "right", "similar", "tablesample",
    "verbose",
}


def qualified_name(schema: str, name: str) -> str:
    return f"{quote_ident(schema)}.{quote_ident(name)}"


def quote_literal(value: Any) -> str:
    """把 Python 值转成 SQL 字面量（字符串统一单引号 + 倍半转义）。

    仅用于我们自己的分页游标等受控值；不用于不可信输入拼接。
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    s = str(value).replace("\x00", "")
    return "'" + s.replace("'", "''") + "'"


def flatten_sql_for_transport(sql: str) -> str:
    """把多行 SQL 压成单行（只读通道的硬限制，实测）。

    Windows 上 ``tcb.cmd`` 是批处理文件，命令行里带换行会被 ``cmd.exe`` 截断，
    远端只会收到第一行（表现为 ``syntax error at end of input`` 或静默执行半截 SQL）。
    因此这里把「引号/注释之外」的空白折叠成单个空格；字符串字面量内保持原样
    （若字面量内部含换行则明确报错，而不是静默改数据）。
    """
    out: List[str] = []
    i, n = 0, len(sql)
    # 状态：normal / sq(') / dq(") / dollar(tag) / line_comment / block_comment
    state = "normal"
    tag = ""
    while i < n:
        ch = sql[i]
        if state == "normal":
            if ch in " \t\r\n\f\v":
                while i < n and sql[i] in " \t\r\n\f\v":
                    i += 1
                if out and out[-1] != " ":
                    out.append(" ")
                continue
            if ch == "-" and i + 1 < n and sql[i + 1] == "-":
                state = "line_comment"
                i += 2
                continue
            if ch == "/" and i + 1 < n and sql[i + 1] == "*":
                state = "block_comment"
                depth = 1
                i += 2
                while i < n and depth:
                    if sql.startswith("/*", i):
                        depth += 1
                        i += 2
                    elif sql.startswith("*/", i):
                        depth -= 1
                        i += 2
                    else:
                        i += 1
                state = "normal"
                if out and out[-1] != " ":
                    out.append(" ")
                continue
            if ch == "'":
                state = "sq"
                out.append(ch)
                i += 1
                continue
            if ch == '"':
                state = "dq"
                out.append(ch)
                i += 1
                continue
            if ch == "$":
                m = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
                if m:
                    tag = m.group(0)
                    state = "dollar"
                    out.append(tag)
                    i += len(tag)
                    continue
            out.append(ch)
            i += 1
            continue
        if state == "line_comment":
            if ch in "\r\n":
                state = "normal"
            i += 1
            continue
        if state == "sq":
            if ch in "\r\n":
                raise SqlValidationError("SQL 字符串字面量内含换行，只读 CLI 通道不支持")
            out.append(ch)
            i += 1
            if ch == "'":
                if i < n and sql[i] == "'":   # '' 转义
                    out.append("'")
                    i += 1
                else:
                    state = "normal"
            continue
        if state == "dq":
            if ch in "\r\n":
                raise SqlValidationError("SQL 标识符内含换行，只读 CLI 通道不支持")
            out.append(ch)
            i += 1
            if ch == '"':
                if i < n and sql[i] == '"':
                    out.append('"')
                    i += 1
                else:
                    state = "normal"
            continue
        if state == "dollar":
            if sql.startswith(tag, i):
                out.append(tag)
                i += len(tag)
                state = "normal"
                continue
            if ch in "\r\n":
                raise SqlValidationError("SQL dollar 字面量内含换行，只读 CLI 通道不支持")
            out.append(ch)
            i += 1
            continue
    if state in ("sq", "dq", "dollar"):
        raise SqlValidationError("SQL 字面量未闭合")
    return "".join(out).strip()


def validate_readonly_sql(sql: str) -> str:
    """校验并返回去掉首尾注释/空白/唯一结尾分号的只读 SQL。

    规则：
    1. 非空；2. 去掉开头注释后必须以 select/with/show 开头；
    3. 不允许内部出现分号（多语句）；4. 不允许任何 DML/DDL/TCL 关键字。
    失败抛 :class:`SqlValidationError`（不发请求）。
    """
    if not isinstance(sql, str) or not sql.strip():
        raise SqlValidationError("SQL 为空")
    body = sql.replace("\ufeff", "").strip()
    while True:
        m = _LEADING_COMMENT_RE.match(body)
        if not m or m.end() == 0:
            break
        body = body[m.end():]
        if not body:
            raise SqlValidationError("SQL 只有注释")
    # 允许唯一一个结尾分号
    if body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in body:
        raise SqlValidationError("只允许单条语句（检测到内部分号）")
    first = re.match(r"[A-Za-z]+", body)
    if not first or first.group(0).lower() not in ALLOWED_STARTERS:
        raise SqlValidationError(
            "只允许只读语句（select/with/show 开头），实际以 "
            f"{first.group(0) if first else '?'!r} 开头"
        )
    hits = sorted({m.group(0).lower() for m in _FORBIDDEN_RE.finditer(body)})
    if hits:
        raise SqlValidationError("SQL 含禁止的写/DDL 关键字: " + ", ".join(hits))
    fn_hits = sorted({m.group(1).lower() for m in _FORBIDDEN_FUNC_RE.finditer(body)})
    if fn_hits:
        raise SqlValidationError("SQL 调用了禁止的有副作用函数: " + ", ".join(fn_hits))
    return body


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------

def _find_tcb() -> str:
    """定位 tcb 可执行文件（Windows: tcb.cmd）。"""
    for candidate in (os.environ.get("TCB_BIN"), "tcb.cmd", "tcb"):
        if not candidate:
            continue
        found = shutil.which(candidate)
        if found:
            return found
    return os.environ.get("TCB_BIN") or "tcb.cmd"


def _decode_stdout(raw: bytes) -> str:
    # 实测 tcb CLI 的 JSON 输出是 UTF-8（Windows 控制台显示乱码是终端编码问题）
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("gbk")
        except UnicodeDecodeError:
            return raw.decode("utf-8", "replace")


def _extract_json(stdout: str) -> dict:
    text = stdout.strip()
    if not text:
        raise ValueError("stdout 为空")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("stdout 不是 JSON: " + text[:300])
        obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("stdout JSON 不是对象")
    return obj


class TcbSqlClient:
    """CloudBase PG 只读 SQL 客户端（subprocess 调 tcb.cmd）。"""

    def __init__(self, *, tcb_bin: Optional[str] = None, env_id: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT, attempts: int = DEFAULT_RETRIES,
                 retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
                 verbose: bool = False) -> None:
        self.tcb_bin = tcb_bin or _find_tcb()
        self.env_id = env_id or os.environ.get("TCB_ENV_ID") or ""
        self.timeout = float(timeout)
        self.attempts = max(1, int(attempts))
        self.retry_delays = list(retry_delays)
        self.verbose = verbose
        self.call_count = 0
        self._no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    # -- 内部 -----------------------------------------------------------
    def _build_cmd(self, sql: str) -> List[str]:
        cmd = [self.tcb_bin, "db", "execute"]
        if self.env_id:
            cmd += ["-e", self.env_id]
        cmd += ["--json", "--sql", sql]
        return cmd

    def _run_once(self, sql: str, timeout: float) -> QueryResult:
        cmd = self._build_cmd(sql)
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout,
                creationflags=self._no_window,
            )
        except subprocess.TimeoutExpired:
            raise TcbSqlError(f"tcb 调用超时（{timeout:.0f}s）", sql=sql)
        except FileNotFoundError:
            raise TcbSqlError(
                f"找不到 tcb 可执行文件: {self.tcb_bin}（CloudBase CLI 未安装或不在 PATH）",
                sql=sql,
            )
        elapsed = time.time() - t0
        stdout = _decode_stdout(proc.stdout or b"")
        stderr = _decode_stdout(proc.stderr or b"").strip()
        try:
            payload = _extract_json(stdout)
        except ValueError as exc:
            detail = stderr[-400:] or stdout.strip()[-400:]
            raise TcbSqlError(
                f"tcb 输出不是合法 JSON: {exc}; exit={proc.returncode}; "
                f"尾部={detail!r}", exit_code=proc.returncode, sql=sql,
            )
        err = payload.get("error")
        if err or proc.returncode != 0:
            if isinstance(err, dict):
                code = str(err.get("code") or "")
                msg = str(err.get("message") or "")
                rid = str(err.get("requestId") or "")
                exit_code = int(err.get("exit_code") or proc.returncode or -1)
            else:
                code, msg, rid, exit_code = "", str(err or ""), "", proc.returncode
            raise TcbSqlError(
                f"tcb SQL 失败: code={code} exit={exit_code} "
                f"requestId={rid} msg={msg[:500]}",
                exit_code=exit_code, code=code, request_id=rid, sql=sql,
            )
        data = payload.get("data") or {}
        if "Rows" not in data:
            raise TcbSqlError(
                "tcb 返回缺少 data.Rows（可能不是查询语句）: "
                + json.dumps(data, ensure_ascii=False)[:400], sql=sql,
            )
        columns = data.get("Columns") or []
        column_types = data.get("ColumnTypes") or []
        rows: List[List[Any]] = []
        for item in data["Rows"]:
            try:
                row = json.loads(item) if isinstance(item, str) else item
            except json.JSONDecodeError as exc:
                raise TcbSqlError(
                    f"Rows 项不是合法 JSON: {exc}: {str(item)[:200]!r}", sql=sql,
                )
            if not isinstance(row, list):
                row = [row]
            rows.append(row)
        return QueryResult(
            columns=list(columns), column_types=list(column_types), rows=rows,
            request_id=str(data.get("RequestId") or ""),
            execution_ms=int(data.get("ExecutionTimeMs") or 0),
            raw_stdout_bytes=len(proc.stdout or b""),
            elapsed_s=elapsed,
        )

    # -- 公开 -----------------------------------------------------------
    def execute(self, sql: str, *, timeout: Optional[float] = None,
                attempts: Optional[int] = None) -> QueryResult:
        """执行一条只读 SQL；失败按策略重试。"""
        body = flatten_sql_for_transport(validate_readonly_sql(sql))
        timeout = self.timeout if timeout is None else float(timeout)
        attempts = self.attempts if attempts is None else max(1, int(attempts))
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            self.call_count += 1
            try:
                return self._run_once(body, timeout)
            except TcbSqlError as exc:
                last_exc = exc
                msg = str(exc)
                non_retryable = any(h in msg for h in _NON_RETRYABLE_HINTS)
                if non_retryable or attempt >= attempts:
                    exc.attempts = attempt
                    raise
                delay = self.retry_delays[min(attempt - 1, len(self.retry_delays) - 1)]
                if self.verbose:
                    print(f"[tcb_sql] 第 {attempt} 次失败，{delay:.1f}s 后重试: "
                          f"{msg[:180]}", file=sys.stderr)
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc

    # -- 结构化取数（统一「单列 JSON 文本」口径）-------------------------
    def fetch_json(self, sql: str, *, timeout: Optional[float] = None) -> Any:
        """执行返回「单行单列 JSON 文本」的 SQL → Python 对象。"""
        res = self.execute(sql, timeout=timeout)
        if not res.rows:
            raise TcbSqlError("fetch_json 期望至少 1 行，实际 0 行", sql=sql)
        cell = res.first_cell()
        if cell is None:
            return None
        if not isinstance(cell, str):
            cell = json.dumps(cell)
        return json.loads(cell)

    def fetch_json_text(self, sql: str, *, timeout: Optional[float] = None) -> str:
        """执行返回「单行单列 JSON 文本」的 SQL，返回原始 JSON 文本。"""
        res = self.execute(sql, timeout=timeout)
        cell = res.first_cell()
        if not isinstance(cell, str):
            raise TcbSqlError(f"fetch_json_text 期望文本列，实际 {type(cell)}", sql=sql)
        return cell

    def fetch_scalar(self, sql: str, *, timeout: Optional[float] = None) -> Any:
        return self.execute(sql, timeout=timeout).scalar()

    def ping(self) -> dict:
        """连通性/身份自检（不发敏感信息）。"""
        return self.fetch_json(
            "select json_build_object("
            "'version', version(), "
            "'database', current_database(), "
            "'user', current_user, "
            "'search_path', current_setting('search_path'), "
            "'server_encoding', current_setting('server_encoding'), "
            "'timezone', current_setting('TimeZone'), "
            "'standard_conforming_strings', current_setting('standard_conforming_strings')"
            ")::text"
        )


# ---------------------------------------------------------------------------
# 产物目录 / 文件工具（P0 三个导出脚本共用）
# ---------------------------------------------------------------------------

# 私有产物根目录：含真实数据，**绝不进仓库**（AGENTS.md 红线：不进 git、不打印正文）
DEFAULT_OUTPUT_ROOT = Path(
    os.environ.get("CB_MIGRATION_ROOT")
    or r"C:\briefdesk\data\cloudbase_migration"
)
MANIFEST_FILES = ("schema_manifest.json", "data_manifest.json", "manifest.json")


def local_stamp() -> str:
    """产物目录时间戳 ``YYYYMMDD-HHMM``（本地时区）。"""
    return time.strftime("%Y%m%d-%H%M", time.localtime())


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def human_bytes(n: int) -> str:
    n = int(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n} B"


def sha256_file(path: "Path | str") -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: "Path | str", obj: Any) -> None:
    """原子写 JSON（UTF-8、缩进 2、保留非 ASCII）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def latest_output_dir(root: Optional["Path | str"] = None) -> Optional["Path"]:
    """返回根目录下最新的一个 P0 产物目录（按时间戳名倒序，需含 manifest 文件）。

    只认 ``YYYYMMDD-HHMM`` / ``YYYYMMDD-HHMM-N`` 形式的目录，避免把 `_test` 等
    调试目录误当作最新产物。
    """
    root = Path(root) if root else DEFAULT_OUTPUT_ROOT
    if not root.is_dir():
        return None
    stamp_re = re.compile(r"^\d{8}-\d{4}(?:-\d+)?$")
    candidates = []
    for sub in root.iterdir():
        if not sub.is_dir() or not stamp_re.match(sub.name):
            continue
        if any((sub / f).exists() for f in MANIFEST_FILES):
            candidates.append(sub)
    if candidates:
        return sorted(candidates, key=lambda p: p.name)[-1]
    # 兼容旧目录（没有时间戳名）
    for sub in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
        if sub.is_dir() and any((sub / f).exists() for f in MANIFEST_FILES):
            return sub
    return None


def new_output_dir(root: Optional["Path | str"] = None) -> "Path":
    """创建 ``<root>/<YYYYMMDD-HHMM>``（同分钟重复时追加 -2、-3…），不覆盖旧产物。"""
    root = Path(root) if root else DEFAULT_OUTPUT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    stamp = local_stamp()
    cand = root / stamp
    n = 2
    while cand.exists() and any(cand.iterdir()):
        cand = root / f"{stamp}-{n}"
        n += 1
    cand.mkdir(parents=True, exist_ok=True)
    return cand


def resolve_output_dir(explicit: Optional[str] = None) -> "Path":
    """``--out`` > ``$CB_MIGRATION_OUT`` > 最新产物目录；都没有则新建一个。"""
    if explicit:
        path = Path(explicit)
        path.mkdir(parents=True, exist_ok=True)
        return path
    env = os.environ.get("CB_MIGRATION_OUT")
    if env:
        path = Path(env)
        path.mkdir(parents=True, exist_ok=True)
        return path
    found = latest_output_dir()
    return found if found is not None else new_output_dir()


# ---------------------------------------------------------------------------
# CLI 自检
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="CloudBase 只读 SQL 通道自检（tcb db execute --json）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sql", help="直接给 SQL")
    group.add_argument("--file", help="从文件读 SQL（UTF-8）")
    group.add_argument("--ping", action="store_true", help="连通性/身份自检")
    parser.add_argument("--show", action="store_true", help="打印 rows（默认只打印计数）")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--attempts", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--env", default="", help="tcb 环境 ID（默认用 CLI 当前环境）")
    args = parser.parse_args(argv)

    client = TcbSqlClient(env_id=args.env or None, timeout=args.timeout,
                          attempts=args.attempts, verbose=True)
    try:
        if args.ping:
            info = client.ping()
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0
        sql = args.sql
        if args.file:
            with open(args.file, "r", encoding="utf-8") as fh:
                sql = fh.read()
        res = client.execute(sql)
        print(f"ok columns={res.columns} types={res.column_types} "
              f"rows={len(res.rows)} bytes={res.raw_stdout_bytes} "
              f"server_ms={res.execution_ms} elapsed={res.elapsed_s:.2f}s "
              f"requestId={res.request_id}")
        if args.show:
            for row in res.as_dicts():
                print(json.dumps(row, ensure_ascii=False))
        return 0
    except SqlValidationError as exc:
        print(f"SQL 校验失败（未发送）: {exc}", file=sys.stderr)
        return 2
    except TcbSqlError as exc:
        print(f"tcb SQL 失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
