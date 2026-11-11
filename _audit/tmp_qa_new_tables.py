# -*- coding: utf-8 -*-
"""独立真实云验证：water/water_room/stage_prefs（测试身份写 + finally 清理；不打印 token）。"""
import json
import os
import sys
import urllib.request
import urllib.error

WEB = r"C:\Users\Ko_Li\.openclaw\workspace\web"
sys.path.insert(0, os.path.join(WEB, "ppt"))
import agent  # noqa: E402

c = agent.Cloud(log=lambda *a, **k: None)
KEY = c.key
BASE = c.base
ADMIN = c.ensure_token()


def call(path, body=None, method="GET", token="", prefer=None):
    h = {"Authorization": "Bearer " + KEY, "Accept": "application/json",
         "User-Agent": "qa/1.0", "Content-Type": "application/json"}
    if token:
        h["X-Device-Id"] = token
    if prefer:
        h["Prefer"] = prefer
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(txt) if txt.strip() else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "replace")[:300]
        except Exception:
            return e.code, ""


# 测试身份 token（不打印）
st, out = call("rpc/class_verify", {"p_sid": "3260799999", "p_name": "测试账号"}, "POST")
assert st == 200 and out.get("token"), (st, out)
T = out["token"]
RV = "9-99Z---999"
YM = "2099-12"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("[PASS] " if ok else "[FAIL] ") + name + ("  " + str(detail)[:200] if detail else ""))


try:
    # 无 token 访问 → []（RLS）
    st, rows = call("water?select=roomverify&roomverify=eq." + RV)
    check("无 token 读 water 为空", st == 200 and rows == [], (st, rows))

    # 写 water（幂等 upsert）
    for reading in (1.23, 2.34):
        st, out = call("water?on_conflict=roomverify,month", [{
            "roomverify": RV, "month": YM, "reading": reading, "persons": 4}],
            "POST", T, "resolution=merge-duplicates,return=minimal")
        check("写 water reading=%s" % reading, st in (200, 201, 204), (st, out))
    st, rows = call("water?select=roomverify,month,reading,persons&roomverify=eq." + RV, token=T)
    check("读回 water 且 upsert 覆盖", st == 200 and len(rows) == 1 and float(rows[0]["reading"]) == 2.34,
          (st, rows))

    # 另一账号（管理员 sid 不同）能读同一宿舍（宿舍共享语义）——但云管理员 token 属于班级成员
    st, rows2 = call("water?select=roomverify&roomverify=eq." + RV, token=ADMIN)
    check("另一班级 token 可读同宿舍（共享语义）", st == 200 and len(rows2 or []) == 1, (st, rows2))

    # water_room
    st, out = call("water_room?on_conflict=roomverify", [{"roomverify": RV, "persons": 6}],
                   "POST", T, "resolution=merge-duplicates,return=minimal")
    check("water_room upsert", st in (200, 201, 204), (st, out))
    st, rows = call("water_room?select=roomverify,persons&roomverify=eq." + RV, token=T)
    check("water_room 读回 persons=6", st == 200 and rows and int(rows[0]["persons"]) == 6, (st, rows))

    # stage_prefs：本人写、本人读
    layout = {"v": 1, "order": ["ppt", "vote", "timer", "draw"],
              "span": {"ppt": 8, "vote": 4, "timer": 6, "draw": 6},
              "hidden": [], "lastDeck": "qa", "pptDl": {}, "at": 1794400000000}
    st, out = call("stage_prefs?on_conflict=sid", [{"sid": "3260799999", "layout": layout}],
                   "POST", T, "resolution=merge-duplicates,return=minimal")
    check("stage_prefs 写", st in (200, 201, 204), (st, out))
    st, rows = call("stage_prefs?select=layout,updated_at&sid=eq.3260799999", token=T)
    check("stage_prefs 本人读回 layout", st == 200 and rows and rows[0]["layout"].get("lastDeck") == "qa",
          (st, rows))
    st, rows = call("stage_prefs?select=layout&sid=eq.3260707024", token=ADMIN)
    check("stage_prefs 跨账号不可见", st == 200 and (rows == []), (st, rows))
    st, rows = call("stage_prefs?select=layout&sid=eq.3260799999", token=ADMIN)
    check("stage_prefs 他人行不可见（管理员 token 也只看本人）", st == 200 and rows == [], (st, rows))
finally:
    for path, method in [
        ("water?roomverify=eq." + RV, "DELETE"),
        ("water_room?roomverify=eq." + RV, "DELETE"),
        ("stage_prefs?sid=eq.3260799999", "DELETE"),
    ]:
        st, out = call(path, None, method, ADMIN)
        print("cleanup", method, path.split("?")[0], "->", st)
    st, rows = call("water?select=roomverify&roomverify=eq." + RV, token=ADMIN)
    print("最终残留 water 行:", len(rows or []))
    st, rows = call("stage_prefs?select=sid&sid=eq.3260799999", token=ADMIN)
    print("清理后 stage_prefs 行:", len(rows or []))

passed = sum(1 for _, ok, _ in results if ok)
print("\nQA RESULT: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
