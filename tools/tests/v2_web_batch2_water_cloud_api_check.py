# -*- coding: utf-8 -*-
"""水量共享云端 API 真实联调（tools/tests/_water_shared_contract.md §1/§2/§6）

目的：在网页实现之前，先用**真实 CloudBase PostgreSQL / PostgREST** 验证
`public.water` / `public.water_room` 的建表、RLS、幂等 upsert、DELETE、water_room upsert 口径，
确保网页端按契约写出的 URL/头/body 能被真实服务接受。

身份：测试身份（3260799999 / 测试账号）经 rpc/class_verify 换 token（不打印 token）。
写入只使用**临时 roomverify（9-QA-WATER-01）**与 2099-xx 月份，finally 全部删除，不碰真实宿舍行。
无 token 只读探测不应看到班级数据（RLS 生效）。

运行：python tools\\tests\\v2_web_batch2_water_cloud_api_check.py
退出码 0 = 全 PASS。
"""
import json
import os
import sys
import time

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
REST = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
KEY = open(os.path.join(WEB, "deploy", "cloudbase", "publish_key.txt"), encoding="utf-8").read().strip()
TEST_SID, TEST_NAME = "3260799999", "测试账号"
RV_TMP = "9-QA-WATER-01"          # 临时测试房号（不在 PW_ROOMS，不会与真实宿舍冲突）
M1, M2 = "2099-01", "2099-02"
REAL_RV = "4-23B---423"
RESULTS = []
TOKEN = ""


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)[:400]})
    print(("[PASS] " if ok else "[FAIL] ") + name + (("  | " + str(note)[:300]) if note else ""))


def hdr(tok="", extra=None):
    h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
         "Origin": "https://tool.furina.fun"}
    if tok:
        h["X-Device-Id"] = tok
        h["X-Class-Token"] = tok
    if extra:
        h.update(extra)
    return h


def req(method, path, tok="", body=None, extra=None, prefer=None):
    h = hdr(tok, extra)
    if prefer:
        h["Prefer"] = prefer
    url = REST.rstrip("/") + "/" + path
    try:
        r = requests.request(method, url, headers=h, data=(json.dumps(body, ensure_ascii=False) if body is not None else None), timeout=40)
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            j = None
        return r.status_code, j
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def login():
    global TOKEN
    st, j = req("POST", "rpc/class_verify", body={"p_sid": TEST_SID, "p_name": TEST_NAME})
    obj = j[0] if isinstance(j, list) and j else j
    ok = st == 200 and isinstance(obj, dict) and obj.get("ok") is True and bool(obj.get("token"))
    T("测试身份可登录（class_verify ok，token 不打印）", ok, "status=%s reason=%s" % (st, (obj or {}).get("reason")))
    if ok:
        TOKEN = str(obj.get("token"))
    return ok


def cleanup():
    if not TOKEN:
        return
    for m in (M1, M2):
        req("DELETE", "water?roomverify=eq.%s&month=eq.%s" % (RV_TMP, m), TOKEN)
    req("DELETE", "water_room?roomverify=eq.%s" % RV_TMP, TOKEN)
    st, rows = req("GET", "water?select=roomverify,month&roomverify=eq." + RV_TMP, TOKEN)
    T("清理：临时行已删除", st == 200 and isinstance(rows, list) and len(rows) == 0,
      "status=%s rows=%s" % (st, rows if not isinstance(rows, list) else len(rows)))


def main():
    if not KEY:
        print("[FAIL] 未读到 publish_key")
        return 1
    if not login():
        return 1

    # 0. RLS：无 token
    st, j = req("GET", "water?select=roomverify,month,reading,persons&roomverify=eq." + RV_TMP + "&order=month.asc")
    T("无 token GET water 被拒绝（401/空）", st in (401, 403) or (st == 200 and j == []), "status=%s body=%s" % (st, str(j)[:120]))
    st, j = req("POST", "water?on_conflict=roomverify,month", body={"roomverify": RV_TMP, "month": M1, "reading": 1.0, "persons": 4},
                prefer="resolution=merge-duplicates,return=minimal")
    T("无 token POST water 被拒绝（401/403）", st in (401, 403), "status=%s body=%s" % (st, str(j)[:120]))

    # 1. 有效 token：空态
    st, j = req("GET", "water?select=roomverify,month,reading,persons&roomverify=eq." + RV_TMP + "&order=month.asc", TOKEN)
    T("有效 token GET water 空态（200 + []）", st == 200 and j == [], "status=%s body=%s" % (st, str(j)[:150]))

    # 2. 写入（幂等 upsert；Prefer 头按契约）
    st, j = req("POST", "water?on_conflict=roomverify,month",
                body={"roomverify": RV_TMP, "month": M1, "reading": 12.34, "persons": 4},
                tok=TOKEN, prefer="resolution=merge-duplicates,return=minimal")
    T("POST water upsert（merge-duplicates,return=minimal）返回 2xx", 200 <= st < 300, "status=%s body=%s" % (st, str(j)[:120]))
    st, j = req("GET", "water?select=roomverify,month,reading,persons&roomverify=eq." + RV_TMP + "&order=month.asc", TOKEN)
    row = (j or [None])[0] if isinstance(j, list) and j else None
    T("GET 读回 M1 记录（reading=12.34 / persons=4）",
      st == 200 and isinstance(row, dict) and float(row.get("reading")) == 12.34 and int(row.get("persons")) == 4,
      "status=%s row=%s" % (st, row))

    # 3. 同 PK 覆盖
    st, j = req("POST", "water?on_conflict=roomverify,month",
                body={"roomverify": RV_TMP, "month": M1, "reading": 13.00, "persons": 6},
                tok=TOKEN, prefer="resolution=merge-duplicates,return=minimal")
    st2, j2 = req("GET", "water?select=roomverify,month,reading,persons&roomverify=eq." + RV_TMP + "&order=month.asc", TOKEN)
    rows = j2 if isinstance(j2, list) else []
    T("同 (roomverify,month) 幂等覆盖（仍 1 行 / reading=13.00）",
      200 <= st < 300 and len(rows) == 1 and float(rows[0].get("reading")) == 13.0,
      "status=%s rows=%s" % (st, rows))
    T("persons=6 被接受（check persons in (4,6)）", bool(rows) and int(rows[0].get("persons")) == 6, rows)

    # 4. 第二条月份 + order=month.asc
    st, j = req("POST", "water?on_conflict=roomverify,month",
                body={"roomverify": RV_TMP, "month": M2, "reading": 20.00, "persons": 4},
                tok=TOKEN, prefer="resolution=merge-duplicates,return=minimal")
    st2, j2 = req("GET", "water?select=roomverify,month,reading,persons&roomverify=eq." + RV_TMP + "&order=month.asc", TOKEN)
    rows = j2 if isinstance(j2, list) else []
    T("两条月份按 order=month.asc 返回", st2 == 200 and len(rows) == 2 and rows[0].get("month") == M1 and rows[1].get("month") == M2,
      "status=%s months=%s" % (st2, [r.get("month") for r in rows]))

    # 5. water_room upsert
    st, j = req("POST", "water_room?on_conflict=roomverify", body={"roomverify": RV_TMP, "persons": 4},
                tok=TOKEN, prefer="resolution=merge-duplicates,return=minimal")
    st2, j2 = req("GET", "water_room?select=roomverify,persons&roomverify=eq." + RV_TMP, TOKEN)
    row = (j2 or [None])[0] if isinstance(j2, list) and j2 else None
    T("POST water_room upsert + GET 读回 persons=4",
      200 <= st < 300 and st2 == 200 and isinstance(row, dict) and int(row.get("persons")) == 4,
      "status=%s row=%s" % (st, row))
    st, j = req("POST", "water_room?on_conflict=roomverify", body={"roomverify": RV_TMP, "persons": 6},
                tok=TOKEN, prefer="resolution=merge-duplicates,return=minimal")
    st2, j2 = req("GET", "water_room?select=roomverify,persons&roomverify=eq." + RV_TMP, TOKEN)
    row = (j2 or [None])[0] if isinstance(j2, list) and j2 else None
    T("water_room 同 roomverify 覆盖 persons=6", 200 <= st < 300 and isinstance(row, dict) and int(row.get("persons")) == 6,
      "status=%s row=%s" % (st, row))

    # 6. 真实宿舍只读（不写）：23B 423 应可读（无行也合法）
    st, j = req("GET", "water?select=roomverify,month,reading,persons&roomverify=eq." + REAL_RV + "&order=month.asc", TOKEN)
    T("真实宿舍 %s 只读 GET 合法（200 数组）" % REAL_RV, st == 200 and isinstance(j, list), "status=%s n=%s" % (st, len(j) if isinstance(j, list) else j))

    # 7. DELETE water 单条
    st, j = req("DELETE", "water?roomverify=eq.%s&month=eq.%s" % (RV_TMP, M1), TOKEN)
    st2, j2 = req("GET", "water?select=roomverify,month&roomverify=eq." + RV_TMP + "&order=month.asc", TOKEN)
    rows = j2 if isinstance(j2, list) else []
    T("DELETE water?roomverify=eq.&month=eq. 生效（只剩 M2）",
      200 <= st < 300 and st2 == 200 and len(rows) == 1 and rows[0].get("month") == M2,
      "status=%s rows=%s" % (st, [r.get("month") for r in rows]))

    # 8. DELETE water_room
    st, j = req("DELETE", "water_room?roomverify=eq." + RV_TMP, TOKEN)
    st2, j2 = req("GET", "water_room?select=roomverify,persons&roomverify=eq." + RV_TMP, TOKEN)
    T("DELETE water_room 生效（GET 空）", 200 <= st < 300 and st2 == 200 and (j2 == [] or j2 is None),
      "status=%s body=%s" % (st, str(j2)[:120]))

    cleanup()
    fails = [x for x in RESULTS if not x["ok"]]
    print("\n============================================================")
    print("v2_web_batch2_water_cloud_api_check: PASS %d / FAIL %d" % (len(RESULTS) - len(fails), len(fails)))
    for x in fails:
        print("  - FAIL " + x["name"] + " | " + x["note"])
    print("============================================================")
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("[FAIL] 未捕获异常：%s" % e)
        try:
            cleanup()
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
