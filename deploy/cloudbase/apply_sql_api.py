# -*- coding: utf-8 -*-
"""把整个 SQL 迁移文件一次性通过 CloudBase 原始 API (`tcb api tcb ExecutePGSql`, 2018-06-08) 应用。

为什么不用 `tcb db execute`：该命令会把 SQL 里的分号当语句分隔符，无法执行含 `;` 的函数体
（plpgsql 函数会报 syntax error / 只有最后一条生效）。原始 ExecutePGSql API 接受完整 SQL 字符串。

用法（PowerShell）：
    cd G:/ClassTools/web/deploy/cloudbase
    python apply_sql_api.py 2026-11-08_diag_login.sql
    python apply_sql_api.py 2026-11-08_diag_login.sql --dry-run
"""
import argparse
import json
import subprocess
import sys

ENV_ID = "tool-d4gosudok46e0e081"
API_VERSION = "2018-06-08"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sql = open(args.file, encoding="utf-8").read()
    if not sql.strip():
        print("[apply] empty sql")
        return 1
    body = json.dumps({"EnvId": ENV_ID, "Sql": sql}, ensure_ascii=False)
    if args.dry_run:
        print("[dry] sql bytes=%d, body bytes=%d" % (len(sql.encode("utf-8")), len(body.encode("utf-8"))))
        return 0
    cmd = ["tcb", "api", "tcb", "ExecutePGSql", "--api-version", API_VERSION,
           "--body", body, "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", shell=True)
    out = (r.stdout or "") + (r.stderr or "")
    print(out[-1200:])
    ok = r.returncode == 0 and '"error"' not in out
    print("[apply] %s" % ("OK" if ok else "FAIL rc=%s" % r.returncode))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
