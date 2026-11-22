# -*- coding: utf-8 -*-
"""通知管理 · 云端可见性检查（2026-11-22，契约 nt_admin_spec.md §5）

只使用**临时 QA 测试身份**（9999 段、is_test=true，finally 硬删除）：
  * 创建身份 → class_verify 拿真实班级 token；
  * 直接调 rpc/notice_audience_visible 验证 seats:/all/admin/committee/league/sid: 判定；
  * 不创建/修改任何通知或业务数据；
  * 结束时删除该身份及其会话（无论成败）。

运行：
    cd G:/ClassTools/web/tools
    python tests/nt_admin_cloud_check.py

凭据：index.html 里的公开 Publishable Key（前端凭据）+ 本机已登录的 tcb CLI（仅建/删临时身份）。
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(os.path.dirname(HERE), "index.html")
NODE = os.environ.get("NODE_EXE") or r"C:\nvm4w\nodejs\node.exe"
TCB_BIN = os.environ.get("TCB_BIN") or r"C:\Users\Ko_Li\AppData\Roaming\npm\node_modules\@cloudbase\cli\bin\tcb"
ENV_ID = "tool-d4gosudok46e0e081"
API_VERSION = "2018-06-08"

QA_SID = "9999000221"
QA_NAME = "测试临时通知管理"
QA_SEAT = 998  # 999 是官方测试身份（3260799999）；998 为空闲号段
QA_ADMIN_SID = "9999000222"
QA_ADMIN_NAME = "测试临时通知管理员"
QA_ADMIN_SEAT = 997
QA_ROW_ID = "qa_notice_admin_test"

RESULTS = []


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


def tcb_sql(sql):
    body = json.dumps({"EnvId": ENV_ID, "Sql": sql}, ensure_ascii=False)
    proc = subprocess.run(
        [NODE, TCB_BIN, "api", "tcb", "ExecutePGSql", "--api-version", API_VERSION,
         "--body", body, "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 or '"error"' in out:
        raise RuntimeError("tcb sql failed: %s" % out[-500:])
    return out


def load_cloud():
    s = open(INDEX, encoding="utf-8").read()
    base = re.search(r'var CB="([^"]+)"', s).group(1)
    key = re.search(r'var CBK="([^"]+)"', s).group(1)
    return base, key


def request(base, key, path, method="GET", body=None, token=None, prefer="return=representation",
            timeout=30):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    if token:
        headers["X-Device-Id"] = token
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, (json.loads(raw) if raw else None)
            except ValueError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, (json.loads(raw) if raw else None)
        except ValueError:
            return e.code, raw


def post(base, key, path, body, token=None, timeout=30):
    return request(base, key, path, "POST", body, token, timeout=timeout)


def visible(base, key, token, audience):
    st, out = post(base, key, "rpc/notice_audience_visible", {"p_audience": audience}, token)
    if st != 200:
        return None, "http%s %s" % (st, str(out)[:120])
    return out, ""


def main():
    base, key = load_cloud()
    T("读取站点云端基址与公开 Publishable Key", bool(base and key), base[:46] + "…")
    token = ""
    admin_token = ""
    created = False
    try:
        # 1) 两个临时 QA 身份：普通成员 + 管理员（只存在于本次检查；先清理上次异常退出的残留）
        for sid, seat, name in ((QA_SID, QA_SEAT, QA_NAME), (QA_ADMIN_SID, QA_ADMIN_SEAT, QA_ADMIN_NAME)):
            tcb_sql("DELETE FROM private.class_sessions WHERE sid = '%s'" % sid)
            tcb_sql("DELETE FROM private.class_ids WHERE sid = '%s' OR (seat = %d AND is_test = true)"
                    % (sid, seat))
            tcb_sql("INSERT INTO private.class_ids (seat, name, sid, role, badge, is_admin, is_test) "
                    "VALUES (%d, '%s', '%s', '', '', %s, true)"
                    % (seat, name, sid, "true" if sid == QA_ADMIN_SID else "false"))
        created = True
        T("创建临时 QA 身份（普通 + 管理员，is_test=true，finally 删除）", True,
          "%s / %s" % (QA_SID, QA_ADMIN_SID))

        st, out = post(base, key, "rpc/class_verify", {"p_sid": QA_SID, "p_name": QA_NAME})
        ok = st == 200 and isinstance(out, dict) and out.get("ok") and out.get("token")
        T("普通 QA 身份 class_verify 拿到班级 token", ok, "http%s" % st)
        if not ok:
            raise RuntimeError("class_verify failed: %s %s" % (st, str(out)[:200]))
        token = out["token"]

        st, out = post(base, key, "rpc/class_verify", {"p_sid": QA_ADMIN_SID, "p_name": QA_ADMIN_NAME})
        ok = st == 200 and isinstance(out, dict) and out.get("ok") and out.get("token")
        T("管理员 QA 身份 class_verify 拿到班级 token", ok, "http%s" % st)
        if not ok:
            raise RuntimeError("admin class_verify failed: %s %s" % (st, str(out)[:200]))
        admin_token = out["token"]

        # 2) seats: 判定（核心新增）
        v, why = visible(base, key, token, "seats:%d" % QA_SEAT)
        T("seats:<座号> 命中 → true", v is True, why or repr(v))
        v, why = visible(base, key, token, "seats:1")
        T("seats:<其它座号> 不命中 → false", v is False, why or repr(v))
        v, why = visible(base, key, token, "seats:1,%d,70" % QA_SEAT)
        T("seats:多人列表中命中 → true", v is True, why or repr(v))
        v, why = visible(base, key, token, "seats:abc,%d" % QA_SEAT)
        T("seats 含非法项仍不抛错且能命中 → true", v is True, why or repr(v))
        v, why = visible(base, key, token, "seats:")
        T("seats: 空值 fail-closed → false", v is False, why or repr(v))

        # 3) 既有取值不回归
        v, why = visible(base, key, token, "all")
        T("all → true", v is True, why or repr(v))
        v, why = visible(base, key, token, "admin")
        T("admin（测试身份非管理员）→ false", v is False, why or repr(v))
        v, why = visible(base, key, token, "committee")
        T("committee（测试身份非班委）→ false", v is False, why or repr(v))
        v, why = visible(base, key, token, "league")
        T("league（测试身份非团员）→ false", v is False, why or repr(v))
        v, why = visible(base, key, token, "sid:" + QA_SID)
        T("sid:<本人> → true", v is True, why or repr(v))
        v, why = visible(base, key, token, "sid:3260707024")
        T("sid:<他人> → false", v is False, why or repr(v))
        v, why = visible(base, key, token, "set:volunteer")
        T("set:<不含本人的名单> → false", v is False, why or repr(v))

        # 4) 策略确实改用集中函数
        sql = tcb_sql("select qual from pg_policies where schemaname='public' "
                      "and tablename='notices' and policyname='nt_read'")
        T("nt_read 策略 = auth_ok() AND notice_audience_visible(audience)",
          "notice_audience_visible" in sql and "auth_ok" in sql, sql[-300:])

        # 5) site_config（网页通知管理配置/状态）服务端仅管理员可读写
        st, rows = request(base, key, "site_config?select=id,value&id=eq.notice_groups", token=admin_token)
        groups = ((rows or [{}])[0].get("value") or {}).get("groups") if isinstance(rows, list) and rows else None
        T("管理员可读 notice_groups（网页配置来源）", st == 200 and isinstance(groups, list) and len(groups) > 0,
          "http%s groups=%s" % (st, len(groups or [])))
        st, rows = request(base, key, "site_config?select=id&id=eq.notice_groups", token=token)
        T("普通成员读 site_config → 空（仅管理员可见）", st == 200 and rows == [],
          "http%s %s" % (st, str(rows)[:120]))

        st, out = request(base, key, "site_config", "POST",
                          [{"id": QA_ROW_ID, "value": {"v": 1, "by": "qa"}}], token=admin_token)
        T("管理员可写 site_config（临时行）", st in (200, 201), "http%s %s" % (st, str(out)[:120]))
        st, out = request(base, key, "site_config?id=eq." + QA_ROW_ID, "PATCH",
                          {"value": {"v": 2, "by": "qa"}}, token=admin_token)
        T("管理员可改 site_config（临时行）", st in (200, 204), "http%s" % st)

        st, out = request(base, key, "site_config?id=eq." + QA_ROW_ID, "PATCH",
                          {"value": {"v": 99, "by": "member"}}, token=token)
        st2, rows = request(base, key, "site_config?select=value&id=eq." + QA_ROW_ID, token=admin_token)
        val = ((rows or [{}])[0].get("value") or {}) if isinstance(rows, list) and rows else {}
        T("普通成员改 site_config 不生效（RLS 拒绝）", val.get("v") == 2,
          "http%s %s" % (st, str(val)[:120]))

        st, out = request(base, key, "site_config", "POST",
                          [{"id": QA_ROW_ID + "_member", "value": {"v": 1}}], token=token)
        st2, rows = request(base, key, "site_config?select=id&id=eq." + QA_ROW_ID + "_member",
                            token=admin_token)
        T("普通成员新增 site_config 行被拒绝", (st not in (200, 201)) or not rows,
          "http%s rows=%s" % (st, str(rows)[:80]))
    finally:
        if created:
            try:
                tcb_sql("DELETE FROM public.site_config WHERE id IN ('%s','%s_member')"
                        % (QA_ROW_ID, QA_ROW_ID))
                tcb_sql("DELETE FROM private.class_sessions WHERE sid IN ('%s','%s')"
                        % (QA_SID, QA_ADMIN_SID))
                tcb_sql("DELETE FROM private.class_ids WHERE sid IN ('%s','%s')"
                        % (QA_SID, QA_ADMIN_SID))
                print("[cleanup] 临时 QA 身份与测试行已删除")
            except Exception as exc:  # noqa: BLE001
                print("[cleanup] FAILED: %r" % (exc,))
                RESULTS.append({"name": "临时 QA 身份清理", "ok": False, "note": str(exc)})

    passed = sum(1 for r in RESULTS if r["ok"])
    print("\nRESULT: %d/%d PASS" % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
