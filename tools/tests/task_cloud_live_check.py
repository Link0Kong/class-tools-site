# -*- coding: utf-8 -*-
"""真实云端 taskdata 冒烟（仅测试身份 3260799999）。

验证：public.taskdata 表存在、RLS 只允许本人行、PostgREST GET/POST upsert 可用。
测试行写入后清空 blob；不读写任何真实账号。
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _test_account import TEST_SID, test_identity_token  # noqa: E402

HTML = os.path.join(TOOLS, "index.html")
h = open(HTML, encoding="utf-8").read()
CB = re.search(r'var CB="([^"]+)"', h).group(1)
CBK = re.search(r'var CBK="([^"]+)"', h).group(1)
REST = CB.rstrip("/") + "/"
TOKEN = test_identity_token(REST, CBK)


def call(method, path, body=None, prefer=None):
    headers = {"Authorization": "Bearer " + CBK, "Content-Type": "application/json",
               "X-Device-Id": TOKEN}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(REST + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


ok = 0
fail = 0
def check(name, cond, note=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name, note)
    else:
        fail += 1
        print("FAIL", name, note)

st, rows = call("GET", "taskdata?select=*&id=eq." + TEST_SID)
check("taskdata GET 本人行", st == 200 and isinstance(rows, list), "%s %s" % (st, str(rows)[:80]))
st, rows = call("GET", "taskdata?select=*&id=eq.9999000001")
check("taskdata RLS 拒绝他人行", st == 200 and rows == [], "%s %s" % (st, str(rows)[:80]))

blob = json.dumps({"v": 1, "lists": [{"id": "inbox", "name": "任务", "color": "cy", "order": 0}],
                   "items": [{"id": "t_probe", "title": "taskdata 冒烟", "notes": "", "list": "inbox",
                              "done": False, "attachments": ""}],
                   "prefs": {"sound": True, "defaultRemind": "none"},
                   "updatedAt": 1700000000000}, ensure_ascii=False)
st, out = call("POST", "taskdata", [{"id": TEST_SID, "blob": blob, "ts": 1700000000000}],
               "return=representation,resolution=merge-duplicates")
check("taskdata POST upsert", st in (200, 201), "%s %s" % (st, str(out)[:120]))
st, rows = call("GET", "taskdata?select=*&id=eq." + TEST_SID)
row = rows[0] if isinstance(rows, list) and rows else {}
try:
    parsed = json.loads(row.get("blob") or "{}")
except Exception:
    parsed = {}
check("taskdata 回读 blob/ts", st == 200 and parsed.get("items", [{}])[0].get("title") == "taskdata 冒烟"
      and int(row.get("ts") or 0) == 1700000000000, "%s %s" % (st, str(row)[:120]))

# 清理测试行内容（保留空行，避免影响测试身份）
st, out = call("POST", "taskdata", [{"id": TEST_SID, "blob": "", "ts": 0}],
               "return=representation,resolution=merge-duplicates")
check("taskdata 清理", st in (200, 201), "%s" % st)

print("RESULT", "GREEN" if fail == 0 else "RED", "PASS", ok, "FAIL", fail)
sys.exit(0 if fail == 0 else 1)
