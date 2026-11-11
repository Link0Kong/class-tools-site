# -*- coding: utf-8 -*-
"""2026-11-11 临时只读探针：CloudBase 数据现状盘点（不打印 token / 学号 / 姓名）。

**历史运维审计脚本，不是测试**：2026-11-11 用户红线后，测试/QA 一律只用测试账号；
重跑本脚本需要显式设置 OPS_RUN_ADMIN_AUDIT=1（它用管理员 token 做跨表只读盘点）。"""
import json
import os

if os.environ.get("OPS_RUN_ADMIN_AUDIT") != "1":
    raise SystemExit("历史运维审计脚本：测试/QA 请只用测试账号（见 AGENTS.md §0-7）；如确需运维重跑，设置 OPS_RUN_ADMIN_AUDIT=1。")
import sys
import urllib.request
import urllib.error

WEB = r"C:\Users\Ko_Li\.openclaw\workspace\web"
PPT = os.path.join(WEB, "ppt")
sys.path.insert(0, PPT)
import agent  # noqa: E402

cloud = agent.Cloud(log=lambda *a, **k: None)
TOKEN = cloud.ensure_token()
KEY = cloud.key
BASE = cloud.base


def req(path, prefer=None, method="GET"):
    headers = {"Authorization": "Bearer " + KEY, "Accept": "application/json",
               "X-Device-Id": TOKEN, "User-Agent": "audit-probe/1.0"}
    if prefer:
        headers["Prefer"] = prefer
    r = urllib.request.Request(BASE + path, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, dict(resp.headers), (json.loads(body) if body.strip() else None)
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:
            text = ""
        return e.code, dict(e.headers), text


def count(table, where=""):
    path = "%s?select=id&limit=1" % table + (("&" + where) if where else "")
    st, hd, _ = req(path, prefer="count=exact")
    cr = hd.get("Content-Range") or hd.get("content-range") or "?"
    return st, cr


def rows(table, select="*", where="", limit=1000, order=None):
    path = "%s?select=%s&limit=%d" % (table, select, limit)
    if where:
        path += "&" + where
    if order:
        path += "&order=" + order
    st, hd, body = req(path)
    return st, body


print("== ppt_decks ==")
st, body = rows("ppt_decks", "id,title,status,deleted,owner_sid,created_at,updated_at", "", 200, "created_at.desc")
if st == 200 and isinstance(body, list):
    print("total rows fetched:", len(body))
    for r in body:
        owner = str(r.get("owner_sid") or "")
        print(" id=%-22s deleted=%-5s status=%-8s owner=%s title=%r created=%s" % (
            r.get("id"), r.get("deleted"), r.get("status"),
            "TEST" if owner == "3260799999" else ("ADMIN" if owner == "3260707024" else "other"),
            r.get("title"), r.get("created_at")))
else:
    print("ERR", st, body)

print("\n== ppt_upload_chunks ==")
print(count("ppt_upload_chunks"))
print(rows("ppt_upload_chunks", "deck_id,idx,updated_at", "", 20, "updated_at.desc")[1])

print("\n== tables counts ==")
for t in ["notices", "homework", "marks", "userdata", "fitrecs", "visits", "feedback",
          "power", "power_history", "service_health", "site_assets", "site_config",
          "client_diag", "diag_analysis", "repair_tasks", "login_jobs",
          "polls", "poll_votes", "agent_keys"]:
    try:
        st, cr = count(t)
        print(" %-18s HTTP=%s count=%s" % (t, st, cr))
    except Exception as e:
        print(" %-18s ERR=%s" % (t, e))

print("\n== notices sample ==")
st, body = rows("notices", "id,ts,archived,hidden,edited_at,length(body)", "", 5, "ts.desc")
print(st, body if st != 200 else [(x.get("id"), x.get("ts"), x.get("archived"), x.get("hidden")) for x in body])

print("\n== userdata ==")
st, body = rows("userdata", "sid,length(blob),at", "", 200)
if st == 200 and isinstance(body, list):
    print("rows:", len(body))
    sizes = [int(x.get("length") or 0) for x in body]
    print("blob size min/avg/max:", min(sizes) if sizes else "-", sum(sizes)//len(sizes) if sizes else "-", max(sizes) if sizes else "-")
    print("empty blob:", sum(1 for s in sizes if s == 0))
else:
    print("ERR", st, body)

print("\n== polls ==")
st, body = rows("polls", "id,title,deleted,status,created_at,audience", "", 50, "created_at.desc")
print(st, body if st != 200 else [(x.get("id"), x.get("deleted"), x.get("created_at")) for x in body])
print("poll_votes:", count("poll_votes"), rows("poll_votes", "id,poll_id,created_at", "", 5, "created_at.desc")[1])

print("\n== power ==")
st, body = rows("power", "roomverify,q,updated_at", "", 100)
print(st, len(body) if isinstance(body, list) else body)
print("power_history:", count("power_history"), rows("power_history", "roomverify,ts", "", 3, "ts.desc")[1])

print("\n== diag ==")
for t in ["client_diag", "repair_tasks", "diag_analysis"]:
    st, body = rows(t, "id,created_at", "", 3, "created_at.desc")
    print(t, st, body)

print("\n== service_health sample ==")
print(rows("service_health", "service,status,ts,detail", "", 30, "ts.desc")[1])

print("\n== site_assets/site_config ==")
print(rows("site_assets", "id,updated_at,length(payload)", "", 20)[1])
print(rows("site_config", "*", "", 20)[1])

print("\n== login_jobs ==")
print(count("login_jobs"), rows("login_jobs", "id,status,created_at", "", 5, "created_at.desc")[1])

print("\n== visits ==")
print(count("visits"))
print("\nDONE")
