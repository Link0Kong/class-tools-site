# -*- coding: utf-8 -*-
"""把 SQL 迁移文件逐条应用到 CloudBase PostgreSQL。

背景（2026-11-08 实测）：
  * `tcb db execute` 会把 SQL 按分号切分 → 含 `;` 的 plpgsql 函数体无法执行；
  * `tcb` 在 Windows 是 .ps1 包装，PowerShell 5.1 会把 `--body` JSON 里的引号吞掉（INVALID_JSON）；
  * 整文件一次性 `--body` 会超 Windows 命令行长度。
  → 正确姿势：逐条语句，用 Python 直接调用 node + cloudbase CLI 入口（不经过 .ps1 包装）。

用法（PowerShell）：
    cd G:/ClassTools/web/deploy/cloudbase
    python apply_sql.py 2026-11-08_diag_login.sql            # 逐条应用（幂等）
    python apply_sql.py 2026-11-08_diag_login.sql --dry-run
"""
import argparse
import json
import os
import re
import subprocess
import sys

ENV_ID = "tool-d4gosudok46e0e081"
API_VERSION = "2018-06-08"
NODE = os.environ.get("NODE_EXE") or r"C:\nvm4w\nodejs\node.exe"
TCB_BIN = os.environ.get("TCB_BIN") or r"C:\Users\Ko_Li\AppData\Roaming\npm\node_modules\@cloudbase\cli\bin\tcb"


def split_sql(text):
    stmts, buf, i, n = [], [], 0, len(text)
    dollar = None
    while i < n:
        if dollar is None:
            m = re.match(r"\$[A-Za-z0-9_]*\$", text[i:])
            if m:
                dollar = m.group(0)
                buf.append(m.group(0))
                i += len(dollar)
                continue
            if text.startswith("--", i):
                j = text.find("\n", i)
                if j < 0:
                    break
                buf.append(text[i:j + 1])
                i = j + 1
                continue
            ch = text[i]
            if ch == ";":
                stmt = "".join(buf).strip()
                if stmt:
                    stmts.append(stmt)
                buf = []
                i += 1
                continue
            buf.append(ch)
            i += 1
        else:
            if text.startswith(dollar, i):
                buf.append(dollar)
                i += len(dollar)
                dollar = None
                continue
            buf.append(text[i])
            i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def run_stmt(idx, stmt, dry):
    body = json.dumps({"EnvId": ENV_ID, "Sql": stmt}, ensure_ascii=False)
    head = re.sub(r"\s+", " ", re.sub(r"^(--[^\n]*\n\s*)+", "", stmt))[:88]
    if dry:
        print("[dry] %02d bytes=%5d %s" % (idx, len(body.encode("utf-8")), head))
        return True
    r = subprocess.run([NODE, TCB_BIN, "api", "tcb", "ExecutePGSql",
                        "--api-version", API_VERSION, "--body", body, "--json"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    ok = r.returncode == 0 and '"error"' not in out
    print(("[ok]   " if ok else "[FAIL] ") + "%02d bytes=%5d %s" % (idx, len(body.encode("utf-8")), head))
    if not ok:
        print(out[-600:])
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    text = open(args.file, encoding="utf-8").read()
    stmts = split_sql(text)
    # 纯注释语句直接跳过
    stmts = [s for s in stmts if re.sub(r"--[^\n]*", "", s).strip()]
    print("[apply] %d statements" % len(stmts))
    fails = 0
    for idx, stmt in enumerate(stmts, 1):
        if not run_stmt(idx, stmt, args.dry_run):
            fails += 1
    print("[apply] done, fails=%d" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
