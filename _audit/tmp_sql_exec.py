# -*- coding: utf-8 -*-
"""临时只读 SQL 执行器（CloudBase ExecutePGSQL API；不打印 token/密钥）。"""
import json
import re
import subprocess
import sys

ENV_ID = "tool-d4gosudok46e0e081"
API_VERSION = "2018-06-08"
NODE = r"C:\nvm4w\nodejs\node.exe"
TCB_BIN = r"C:\Users\Ko_Li\AppData\Roaming\npm\node_modules\@cloudbase\cli\bin\tcb"


def exec_sql(sql, timeout=120):
    body = json.dumps({"EnvId": ENV_ID, "Sql": sql}, ensure_ascii=False)
    r = subprocess.run([NODE, TCB_BIN, "api", "tcb", "ExecutePGSql",
                        "--api-version", API_VERSION, "--body", body, "--json"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    # 找 JSON 块
    m = re.search(r'\{.*\}\s*$', out, re.S)
    if m:
        try:
            return 0, json.loads(m.group(0))
        except Exception:
            pass
    return r.returncode, out[-2000:]


if __name__ == "__main__":
    sql = sys.stdin.read()
    code, out = exec_sql(sql)
    print("rc=%s" % code)
    if isinstance(out, (dict, list)):
        print(json.dumps(out, ensure_ascii=False, indent=1)[:8000])
    else:
        print(str(out)[:4000])
