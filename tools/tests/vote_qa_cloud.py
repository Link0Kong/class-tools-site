# -*- coding: utf-8 -*-
"""投票功能独立验收 · 云端黑盒（真实 CloudBase PostgreSQL / PostgREST）。

验收对象：`web/vote/CONTRACT.md` §1/§2 与迁移 `deploy/cloudbase/2026-11-11_polls.sql` 已应用结果。
本脚本由独立 QA 编写，不复用实现者（tools/tests/vote_cloud_check.py）的断言与用例组织；
唯一复用：`deploy/cloudbase/apply_sql.py::run_stmt`（云端 SQL 通道）与公开 publishable key。

安全性：
  * 登录身份固定为测试身份（3260799999 / 测试账号），不读取任何真实成员凭据；
  * 多用户场景用 private.class_sessions 一次性 token（sid 99990100xx，脚本 finally 必删）；
  * 所有测试投票 id 以 `pqa` 开头并在 finally 中 `delete from poll_votes/polls` 硬删除；
  * 不打印 token / key / 任何真实同学信息。

运行：cd web/tools && python tests\\vote_qa_cloud.py
证据：tools/tests/_shots_vote_qa/cloud_report.json
"""
import importlib.util
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
SHOTS = os.path.join(HERE, "_shots_vote_qa")
os.makedirs(SHOTS, exist_ok=True)
REST = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
KEY = open(os.path.join(WEB, "deploy", "cloudbase", "publish_key.txt"), encoding="utf-8").read().strip()
TEST_SID, TEST_NAME = "3260799999", "测试账号"

TAG = str(int(time.time() * 1000))[-8:]
QA_A, QA_B, QA_C, QA_EXP = ("qatok_qavote_a_" + TAG, "qatok_qavote_b_" + TAG,
                            "qatok_qavote_c_" + TAG, "qatok_qavote_exp_" + TAG)
QA_SIDS = {"9999010001": "投票测试甲", "9999010002": "投票测试乙", "9999010003": "投票测试丙"}
NOW0 = int(time.time() * 1000)

RESULTS = []
CREATED = []        # 本脚本创建的 poll id（finally 硬删除）
SESSION_TOKENS = []  # 本脚本创建的 class_sessions.token（finally 删除）
REAL_TOKEN = [""]    # 测试身份登录 token（finally 删除，绝不打印）
RAW_POLL_RESPONSES = []  # poll_* RPC 原始响应文本（隐私扫描用；不含登录 token）


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


# ---------------------------------------------------------------- 云端通道
_spec = importlib.util.spec_from_file_location("apply_sql", os.path.join(WEB, "deploy", "cloudbase", "apply_sql.py"))
_apply_sql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_apply_sql)


def sql(stmt):
    return _apply_sql.run_stmt(1, stmt, False)


def sql_quiet(stmt):
    """执行 SQL 但不打印（含真实 token 的清理语句）。"""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = _apply_sql.run_stmt(1, stmt, False)
    return ok


def headers(token=None, style="device"):
    h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
         "Origin": "https://tool.furina.fun"}
    if token:
        h["X-Class-Token" if style == "class" else "X-Device-Id"] = token
    return h


def rpc(name, body=None, token=None, style="device", collect=True, timeout=60):
    """返回 (http_status, parsed_json_or_None, raw_text, content_type)。"""
    try:
        r = requests.post(REST + "rpc/" + name, headers=headers(token, style),
                          json=body if body is not None else {}, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return 0, None, "request-error:%s" % e, ""
    raw = r.text or ""
    try:
        parsed = r.json()
    except Exception:
        parsed = None
    if collect and name.startswith("poll_") and token is not None:
        RAW_POLL_RESPONSES.append(raw)
    return r.status_code, parsed, raw, r.headers.get("Content-Type", "")


def table_req(method, table, token=None, body=None, query="?select=*&limit=1"):
    try:
        r = requests.request(method, REST + table + query, headers=headers(token),
                             json=body, timeout=40)
        return r.status_code, (r.text or "")[:300]
    except Exception as e:  # noqa: BLE001
        return 0, "request-error:%s" % e


def pid(tag):
    return "pqa" + TAG + tag


def opt(i, text=None, desc="", img=""):
    return {"id": "o%d" % i, "text": text if text is not None else ("选项%d" % i), "desc": desc, "img": img}


def settings(**kw):
    s = {"multi": False, "maxChoices": 1, "anonymous": True, "allowChange": True,
         "resultVisibility": "afterVote"}
    s.update(kw)
    return s


def mk(p, title, *, options=None, st=None, deadline=0, mode="long", desc="", token=None):
    body = {"p_id": p, "p_title": title, "p_description": desc, "p_mode": mode,
            "p_options": options if options is not None else [opt(1), opt(2), opt(3)],
            "p_settings": st if st is not None else settings(), "p_deadline": deadline}
    stcode, r, raw, ct = rpc("poll_create", body, token or QA_A)
    if isinstance(r, dict) and r.get("ok") and (r.get("poll") or {}).get("id"):
        if r["poll"]["id"] not in CREATED:
            CREATED.append(r["poll"]["id"])
    return stcode, r, raw, ct


def submit(p, choices, token):
    return rpc("poll_submit", {"p_id": p, "p_choices": choices}, token)


def manage(p, action, token, **kw):
    body = {"p_id": p, "p_action": action}
    body.update(kw)
    return rpc("poll_manage", body, token)


def main():
    global RAW_POLL_RESPONSES
    fails0 = 0
    # ================= 0. 准备身份 =================
    sql("insert into private.class_sessions(token,sid,name,expires_at) values "
        "('%s','%s','%s',now()+interval '2 days'),"
        "('%s','%s','%s',now()+interval '2 days'),"
        "('%s','%s','%s',now()+interval '2 days'),"
        "('%s','%s','%s',now()-interval '2 hours') "
        "on conflict (token) do nothing"
        % (QA_A, list(QA_SIDS)[0], list(QA_SIDS.values())[0],
           QA_B, list(QA_SIDS)[1], list(QA_SIDS.values())[1],
           QA_C, list(QA_SIDS)[2], list(QA_SIDS.values())[2],
           QA_EXP, list(QA_SIDS)[0], list(QA_SIDS.values())[0]))
    SESSION_TOKENS.extend([QA_A, QA_B, QA_C, QA_EXP])
    st, r, raw, ct = rpc("class_verify", {"p_sid": TEST_SID, "p_name": TEST_NAME}, None)
    token_t = (r or {}).get("token") or ""
    REAL_TOKEN[0] = token_t
    if token_t:
        SESSION_TOKENS.append(token_t)
    T("0.1 测试身份登录（class_verify，非管理员）",
      st == 200 and bool(token_t) and (r or {}).get("is_admin") is False)
    st, rl, raw, ct = rpc("poll_list", {}, QA_A)
    T("0.2 一次性 QA 会话可用（poll_list ok=true）", rl is not None and rl.get("ok") is True, rl and rl.get("reason"))

    # ================= A. 鉴权 / 直连表 =================
    st, r, _, _ = rpc("poll_list", {}, None, collect=False)
    T("A1 无班级 token：poll_list 拒绝且无学号泄露",
      st == 200 and isinstance(r, dict) and r.get("ok") is False and "身份" in str(r.get("reason")),
      r and r.get("reason"))
    st, r, _, _ = rpc("poll_list", {}, "qatok_not_exists_" + TAG, collect=False)
    T("A2 伪造 token：拒绝", st == 200 and isinstance(r, dict) and r.get("ok") is False)
    st, r, _, _ = rpc("poll_list", {}, QA_EXP, collect=False)
    T("A3 过期 token（DB expires_at 已过）：拒绝",
      st == 200 and isinstance(r, dict) and r.get("ok") is False, r and r.get("reason"))
    st, r, _, _ = rpc("poll_list", {}, QA_A, style="class")
    T("A4 小程序头 X-Class-Token 同样有效（auth_hdr 双头）", r is not None and r.get("ok") is True)
    st, txt = table_req("GET", "polls", QA_A)
    T("A5 直连 GET /polls 被拒（401/403 或空）", st in (401, 403) or (st == 200 and txt.strip() in ("[]", "")), "status=%s" % st)
    st, txt = table_req("GET", "poll_votes", QA_A)
    T("A6 直连 GET /poll_votes 被拒", st in (401, 403) or (st == 200 and txt.strip() in ("[]", "")), "status=%s" % st)
    st, txt = table_req("POST", "polls", QA_A, {"id": "pqa_hack", "title": "hack"})
    T("A7 直连 POST /polls 被拒", st in (401, 403, 404), "status=%s" % st)
    st, txt = table_req("POST", "poll_votes", QA_A, {"id": "x|y"})
    T("A8 直连 POST /poll_votes 被拒", st in (401, 403, 404), "status=%s" % st)
    st, r, _, _ = rpc("poll_create", {"p_id": pid("noauth"), "p_title": "x", "p_description": "",
                                      "p_mode": "long", "p_options": [opt(1), opt(2)],
                                      "p_settings": settings(), "p_deadline": 0}, None, collect=False)
    T("A9 无 token 发起投票被拒", isinstance(r, dict) and r.get("ok") is False, r and r.get("reason"))

    # ================= B. poll_create 参数边界 =================
    cases = []
    st, r, _, _ = mk(pid("v1"), "   ")
    cases.append(("B1 标题全空白被拒", r is not None and r.get("ok") is False and "标题" in str(r.get("reason")), r and r.get("reason")))
    st, r, _, _ = mk(pid("v2"), "题" * 81)
    cases.append(("B2 标题 81 字被拒", r is not None and r.get("ok") is False, r and r.get("reason")))
    st, r, _, _ = mk(pid("v3"), "题" * 80)
    cases.append(("B3 标题 80 字接受", r is not None and r.get("ok") is True and len((r.get("poll") or {}).get("title", "")) == 80,
                  (r or {}).get("reason")))
    st, r, _, _ = mk(pid("v4"), "说明边界", desc="说" * 500)
    cases.append(("B4 说明 500 字接受", r is not None and r.get("ok") is True))
    st, r, _, _ = mk(pid("v5"), "说明边界", desc="说" * 501)
    cases.append(("B5 说明 501 字被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v6"), "选项下限", options=[opt(1)])
    cases.append(("B6 选项 1 个被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v7"), "选项上限", options=[opt(i) for i in range(1, 22)])
    cases.append(("B7 选项 21 个被拒", r is not None and r.get("ok") is False))
    opts20 = [opt(i) for i in range(1, 21)]
    opts20[0]["text"] = "项" * 80
    opts20[0]["desc"] = "补" * 200
    opts20[1] = opt(2, "选项2", desc="补" * 200)
    st, r, _, _ = mk(pid("v8"), "选项上限 20", options=opts20)
    cases.append(("B8 选项 20 个 + 选项文字 80 字 + 说明 200 字接受",
                  r is not None and r.get("ok") is True and len((r.get("poll") or {}).get("options") or []) == 20))
    st, r, _, _ = mk(pid("v9"), "选项文字超长", options=[opt(1, "项" * 81), opt(2)])
    cases.append(("B9 选项文字 81 字被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v10"), "选项文字空", options=[opt(1, "  "), opt(2)])
    cases.append(("B10 选项文字空白被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v11"), "选项说明超长", options=[opt(1, desc="补" * 201), opt(2)])
    cases.append(("B11 选项说明 201 字被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v12"), "选项编号非法", options=[{"id": "o 1", "text": "甲"}, opt(2)])
    cases.append(("B12 选项 id 非法字符被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v13"), "选项编号重复", options=[opt(1), opt(1, "重复")])
    cases.append(("B13 选项 id 重复被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v14"), "图片前缀", options=[opt(1, img="https://evil.example/x.png"), opt(2)])
    cases.append(("B14 选项 img 非 data:image/ 被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v15"), "图片超长", options=[opt(1, img="data:image/jpeg;base64," + "A" * 150001), opt(2)])
    cases.append(("B15 单张 img >150000 字符被拒", r is not None and r.get("ok") is False))
    big = [{"id": "o%d" % i, "text": "选项%d" % i,
            "img": "data:image/jpeg;base64," + "A" * 139900} for i in range(1, 13)]  # 12*139919 > 1.6M
    st, r, _, _ = mk(pid("v16"), "图片总量", options=big)
    cases.append(("B16 选项 img 合计 >1.6MB 被拒", r is not None and r.get("ok") is False, (r or {}).get("reason")))
    st, r, _, _ = mk(pid("v17"), "可见性非法", st=settings(resultVisibility="everyone"))
    cases.append(("B17 resultVisibility 非法被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v18"), "多选上限 1", st=settings(multi=True, maxChoices=1))
    cases.append(("B18 multi=true 且 maxChoices=1 被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v19"), "多选上限归一", options=[opt(1), opt(2), opt(3)],
                     st=settings(multi=True, maxChoices=25))
    smax = ((r or {}).get("poll") or {}).get("settings", {}).get("maxChoices")
    cases.append(("B19 maxChoices>选项数时归一为选项数", r is not None and r.get("ok") is True and smax == 3, "max=%s" % smax))
    st, r, _, _ = mk(pid("v20"), "单选归一", st=settings(multi=False, maxChoices=7))
    smax = ((r or {}).get("poll") or {}).get("settings", {}).get("maxChoices")
    cases.append(("B20 单选时 maxChoices 强制 1", r is not None and r.get("ok") is True and smax == 1, "max=%s" % smax))
    st, r, _, _ = mk(pid("v21"), "截止过去", deadline=NOW0 - 60000)
    cases.append(("B21 deadline 早于服务端当前时间被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v22"), "截止负数", deadline=-1)
    cases.append(("B22 deadline 负数被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk("x123", "id 非法")
    cases.append(("B23 p_id 不合法被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = rpc("poll_create", {"p_id": "p" + "a" * 33, "p_title": "id超长", "p_description": "",
                                      "p_mode": "long", "p_options": [opt(1), opt(2)],
                                      "p_settings": settings(), "p_deadline": 0}, QA_A)
    cases.append(("B24 p_id 超长（p+33）被拒", r is not None and r.get("ok") is False))
    st, r, _, _ = mk(pid("v25"), "模式非法", mode="forever")
    cases.append(("B25 mode 非法归一为 long（不写库非法值）",
                  r is not None and r.get("ok") is True and (r.get("poll") or {}).get("mode") == "long"))
    for name, ok, note in [c if len(c) == 3 else (c[0], c[1], "") for c in cases]:
        T(name, ok, note)
    # 幂等
    p_idem = pid("idem")
    st, r1, _, _ = mk(p_idem, "幂等原始标题", options=[opt(1), opt(2)])
    st, r2, _, _ = mk(p_idem, "幂等覆盖标题", options=[opt(1), opt(2), opt(3)], deadline=NOW0 + 100000)
    ids_same = (r1 or {}).get("poll", {}).get("id") == (r2 or {}).get("poll", {}).get("id") == p_idem
    title_keep = ((r2 or {}).get("poll") or {}).get("title") == "幂等原始标题"
    n_idem = 0
    st, rl, _, _ = rpc("poll_list", {}, QA_A)
    for x in (rl or {}).get("polls") or []:
        if x.get("id") == p_idem:
            n_idem += 1
    T("B26 同 p_id 重复发起幂等（不覆盖内容、列表仅 1 条）",
      ids_same and title_keep and n_idem == 1, "same=%s title_keep=%s n=%s" % (ids_same, title_keep, n_idem))

    # ================= C. 返回结构与隐私 =================
    p_base = pid("base")
    st, r0, raw0, ct0 = mk(p_base, "基础投票", options=[opt(1), opt(2), opt(3)],
                           deadline=NOW0 + 3600 * 1000, mode="quick", token=token_t)
    T("C1 正常发起成功且 HTTP/Content-Type 为 JSON",
      st == 200 and r0 is not None and r0.get("ok") is True and "json" in (ct0 or "").lower(),
      "status=%s ct=%s" % (st, ct0))
    T("C2 发起人姓名由服务端按名单写入（测试账号）",
      ((r0 or {}).get("poll") or {}).get("owner_name") == TEST_NAME,
      (r0 or {}).get("poll", {}).get("owner_name"))
    T("C3 发起人返回 mine/can_manage=true、未投结果隐藏、total=0",
      r0.get("mine") is True and r0.get("can_manage") is True and
      r0.get("results_hidden") is True and r0.get("total") == 0 and r0.get("counts") == {})
    st, r, _, _ = rpc("poll_detail", {"p_id": pid("nope")}, QA_A)
    T("C4 不存在的投票：详情返回 ok=false「投票不存在」",
      r is not None and r.get("ok") is False and "不存在" in str(r.get("reason")), r and r.get("reason"))
    st, rl, _, _ = rpc("poll_list", {}, QA_A)
    rows = [x for x in ((rl or {}).get("polls") or []) if x.get("id") == p_base]
    need = ["id", "title", "description", "mode", "owner_name", "settings", "deadline",
            "status", "closed_at", "created_at", "updated_at", "closed", "total",
            "has_voted", "my_choices", "results_hidden", "mine", "can_manage"]
    T("C5 列表返回契约 §2.2 全部字段", len(rows) == 1 and all(k in rows[0] for k in need),
      "missing=%s" % [k for k in need if not rows or k not in rows[0]])
    prev_created = None
    order_ok = True
    for row in (rl or {}).get("polls") or []:
        if row["id"] in (p_base, p_idem):
            if prev_created is not None and row["created_at"] > prev_created:
                order_ok = False
            prev_created = row["created_at"]
    T("C6 列表按 created_at 倒序（新投票出现在旧投票之前）", order_ok)
    st, rd, _, _ = rpc("poll_detail", {"p_id": p_base}, QA_A)
    dneed = ["ok", "now", "poll", "closed", "total", "counts", "has_voted", "my_choices",
             "results_hidden", "voters", "mine", "can_manage"]
    pneed = ["id", "title", "description", "mode", "owner_name", "settings", "options",
             "deadline", "status", "closed_at", "created_at", "updated_at"]
    T("C7 详情返回契约 §2.3 全部字段",
      all(k in (rd or {}) for k in dneed) and all(k in ((rd or {}).get("poll") or {}) for k in pneed))
    T("C8 任何 poll_* RPC 响应不含 sid 字段",
      all('"sid"' not in raw and "owner_sid" not in raw for raw in RAW_POLL_RESPONSES),
      "n_resp=%d" % len(RAW_POLL_RESPONSES))
    leak_sids = [s for s in list(QA_SIDS) + [TEST_SID] if any(s in raw for raw in RAW_POLL_RESPONSES)]
    T("C9 任何 poll_* RPC 响应不含学号值（测试身份/合成 sid）", not leak_sids, str(leak_sids))

    # ================= D. 投票规则：单选 / 一人一票 / 改票 =================
    st, r, _, _ = submit(p_base, ["o1"], QA_A)
    T("D1 单选投票成功（counts 正确、has_voted）",
      r is not None and r.get("ok") is True and r.get("counts") == {"o1": 1} and r.get("has_voted") is True,
      r and r.get("reason"))
    T("D2 投票后 total=1 且我的选项回显", r.get("total") == 1 and r.get("my_choices") == ["o1"])
    st, r, _, _ = submit(p_base, ["o1", "o2"], QA_A)
    T("D3 单选提交 2 项被拒「只能选 1 项」",
      r is not None and r.get("ok") is False and r.get("reason") == "只能选 1 项", r and r.get("reason"))
    st, r, _, _ = submit(p_base, [], QA_A)
    T("D4 空选项被拒「选项不合法」", r is not None and r.get("ok") is False and "选项不合法" in str(r.get("reason")))
    st, r, _, _ = submit(p_base, ["onope"], QA_A)
    T("D5 不存在的选项被拒「选项不合法」", r is not None and r.get("ok") is False and "选项不合法" in str(r.get("reason")))
    st, r, _, _ = submit(p_base, [123], QA_A)
    T("D6 非字符串选项被拒「选项不合法」", r is not None and r.get("ok") is False and "选项不合法" in str(r.get("reason")))
    st, r, _, _ = submit(p_base, ["o2"], QA_A)
    T("D7 allowChange=true 时改票成功（一人一票 upsert，total 仍 1、counts 替换）",
      r is not None and r.get("ok") is True and r.get("total") == 1 and r.get("counts") == {"o2": 1},
      r and r.get("counts"))
    st, r, _, _ = submit(p_base, ["o1"], QA_B)
    T("D8 第二人投票计数累加（total=2）",
      r is not None and r.get("ok") is True and r.get("total") == 2 and r.get("counts") == {"o1": 1, "o2": 1},
      r and r.get("counts"))
    T("D9 匿名投票 voters 恒为空数组", r.get("voters") == [])
    T("D10 非发起人 mine/can_manage=false", r.get("mine") is False and r.get("can_manage") is False)

    # 不可改票
    p_nochg = pid("nochg")
    st, r, _, _ = mk(p_nochg, "不可改票", st=settings(allowChange=False))
    T("D11 不可改票投票创建成功", r is not None and r.get("ok") is True)
    st, r, _, _ = submit(p_nochg, ["o1"], QA_A)
    T("D12 不可改票：首次投票成功", r is not None and r.get("ok") is True and r.get("total") == 1)
    st, r, _, _ = submit(p_nochg, ["o2"], QA_A)
    T("D13 不可改票：再次投票被拒「已投过票，不可改票」",
      r is not None and r.get("ok") is False and r.get("reason") == "已投过票，不可改票", r and r.get("reason"))
    st, r, _, _ = rpc("poll_detail", {"p_id": p_nochg}, QA_A)
    T("D14 不可改票：记录仍为首次选择", r is not None and r.get("counts") == {"o1": 1} and r.get("my_choices") == ["o1"])

    # 多选
    p_multi = pid("multi")
    st, r, _, _ = mk(p_multi, "多选投票", options=[opt(1), opt(2), opt(3)],
                     st=settings(multi=True, maxChoices=2), deadline=NOW0 + 3600 * 1000)
    T("D15 多选投票创建（maxChoices=2）",
      r is not None and r.get("ok") is True and ((r.get("poll") or {}).get("settings") or {}).get("maxChoices") == 2)
    st, r, _, _ = submit(p_multi, ["o1", "o2", "o3"], QA_A)
    T("D16 多选超上限被拒「最多选 2 项」",
      r is not None and r.get("ok") is False and r.get("reason") == "最多选 2 项", r and r.get("reason"))
    st, r, _, _ = submit(p_multi, ["o1", "o1"], QA_A)
    T("D17 多选重复选项被拒「重复的选项」",
      r is not None and r.get("ok") is False and r.get("reason") == "重复的选项", r and r.get("reason"))
    st, r, _, _ = submit(p_multi, ["o1", "o2"], QA_A)
    T("D18 多选 2 项提交成功", r is not None and r.get("ok") is True and r.get("counts") == {"o1": 1, "o2": 1})

    # ================= E. 结果可见性 =================
    # afterVote：D1 前已覆盖隐藏→可见（此处在 C3/D2 中体现），补显式断言
    T("E1 afterVote：未投时 results_hidden=true 且 counts={}（发起人视角）",
      r0.get("results_hidden") is True and r0.get("counts") == {})
    st, rv, _, _ = rpc("poll_detail", {"p_id": p_multi}, QA_C)
    T("E2 afterVote：第三方未投时看不到 counts，但 has_voted=false",
      rv is not None and rv.get("ok") is True and rv.get("results_hidden") is True and rv.get("counts") == {},
      rv and rv.get("counts"))
    # always
    p_always = pid("always")
    st, r, _, _ = mk(p_always, "始终可见", st=settings(resultVisibility="always"))
    T("E3 always：0 票时发起人也直接可见计数（counts={} + results_hidden=false）",
      r is not None and r.get("ok") is True and r.get("results_hidden") is False and r.get("counts") == {})
    st, r, _, _ = submit(p_always, ["o1"], QA_B)
    st, rv, _, _ = rpc("poll_detail", {"p_id": p_always}, QA_C)
    T("E4 always：未投票第三方也能看到 counts", rv is not None and rv.get("results_hidden") is False
      and rv.get("counts") == {"o1": 1})
    # afterClose
    p_after = pid("after")
    st, r, _, _ = mk(p_after, "截止后可见", st=settings(resultVisibility="afterClose"),
                     deadline=NOW0 + 3600 * 1000)
    T("E5 afterClose 创建成功（未投/未截止时隐藏）",
      r is not None and r.get("ok") is True and r.get("results_hidden") is True)
    st, r, _, _ = submit(p_after, ["o1"], QA_A)
    T("E6 afterClose：投票后仍隐藏 counts，但 my_choices 回显本人选择",
      r is not None and r.get("ok") is True and r.get("results_hidden") is True and
      r.get("counts") == {} and r.get("my_choices") == ["o1"])
    st, r, _, _ = manage(p_after, "close", QA_A)
    T("E7 afterClose：提前结束后结果可见（counts 出现）",
      r is not None and r.get("ok") is True and r.get("results_hidden") is False and r.get("counts") == {"o1": 1},
      r and r.get("counts"))
    st, r, _, _ = rpc("poll_detail", {"p_id": p_after}, QA_B)
    T("E8 afterClose：他人结束后同样可见", r is not None and r.get("ok") is True
      and r.get("results_hidden") is False and r.get("counts") == {"o1": 1})
    st, rl, _, _ = rpc("poll_list", {}, QA_A)
    lrow = [x for x in ((rl or {}).get("polls") or []) if x.get("id") == p_after]
    T("E9 列表可见性与详情一致（afterClose 结束后 results_hidden=false）",
      len(lrow) == 1 and lrow[0].get("results_hidden") is False and lrow[0].get("counts") == {"o1": 1})

    # ================= F. 实名投票人 =================
    p_real = pid("real")
    st, r, _, _ = mk(p_real, "实名投票", st=settings(anonymous=False), options=[opt(1), opt(2)])
    T("F1 实名投票创建", r is not None and r.get("ok") is True)
    st, r, _, _ = submit(p_real, ["o1"], QA_B)
    voters = r.get("voters") if r else None
    T("F2 实名：投票后返回投票人条目（name/choices，且不含 sid 键）",
      isinstance(voters, list) and len(voters) == 1 and "name" in voters[0] and "choices" in voters[0]
      and '"sid"' not in json.dumps(voters), voters)
    st, r, _, _ = submit(p_real, ["o2"], token_t)
    names = [v.get("name") for v in (r.get("voters") or [])]
    T("F3 实名：测试身份投票人姓名 = 测试账号（服务端按名单）", TEST_NAME in names, names)
    T("F4 实名：voters 不含 sid 键、name 均非数字学号（合成会话不在真实名单时 name 可为空，服务端未伪造学号）",
      all("sid" not in json.dumps(v) for v in (r.get("voters") or []))
      and all(not str(n or "").strip().isdigit() for n in names), names)
    # afterClose + 实名：未截止不可见投票人
    p_real2 = pid("real2")
    st, r, _, _ = mk(p_real2, "实名截止后可见", st=settings(anonymous=False, resultVisibility="afterClose"))
    st, r, _, _ = submit(p_real2, ["o1"], QA_B)
    T("F5 afterClose+实名：未截止时 voters 为空（即使结果可见性关闭）", r.get("voters") == [])

    # ================= G. 服务端截止时间（不信任客户端） =================
    p_ddl = pid("ddl")
    st, r, _, _ = mk(p_ddl, "服务端截止测试", deadline=NOW0 + 3600 * 1000)
    T("G1 限时投票创建成功", r is not None and r.get("ok") is True)
    dl_set = NOW0 - 5000
    ok_sql = sql("update public.polls set deadline = %d where id = '%s'" % (dl_set, p_ddl))
    T("G2 SQL 把 deadline 改为过去（模拟 DB 时间到达）", ok_sql)
    st, r, _, _ = submit(p_ddl, ["o1"], QA_A)
    T("G3 已到截止：服务端拒绝投票「投票已结束」",
      r is not None and r.get("ok") is False and "已结束" in str(r.get("reason")), r and r.get("reason"))
    st, r, _, _ = rpc("poll_detail", {"p_id": p_ddl}, QA_A)
    T("G4 已到截止：详情 closed=true 且 status 仍是 open（到期不写库）",
      r is not None and r.get("ok") is True and r.get("closed") is True
      and (r.get("poll") or {}).get("status") == "open")
    st, rl, _, _ = rpc("poll_list", {}, QA_A)
    lrow = [x for x in ((rl or {}).get("polls") or []) if x.get("id") == p_ddl]
    T("G5 列表 closed 标记与 DB deadline 一致", len(lrow) == 1 and lrow[0].get("closed") is True)

    # ================= H. 管理：结束 / 延长 / 权限 =================
    p_mg = pid("mg")
    st, r, _, _ = mk(p_mg, "管理测试", deadline=NOW0 + 3600 * 1000)
    st, r, _, _ = submit(p_mg, ["o1"], QA_A)
    T("H1 管理测试准备：1 票已投", r is not None and r.get("ok") is True)
    st, r, _, _ = manage(p_mg, "close", QA_B)
    T("H2 非发起人不能提前结束（无权管理该投票）",
      r is not None and r.get("ok") is False and "无权" in str(r.get("reason")), r and r.get("reason"))
    st, r, _, _ = manage(p_mg, "delete", QA_B)
    T("H3 非发起人不能删除", r is not None and r.get("ok") is False and "无权" in str(r.get("reason")))
    st, r, _, _ = manage(p_mg, "extend", QA_B, p_deadline=NOW0 + 7200 * 1000)
    T("H4 非发起人不能延长", r is not None and r.get("ok") is False and "无权" in str(r.get("reason")))
    st, r, _, _ = manage(p_mg, "close", QA_A)
    T("H5 发起人提前结束成功（closed=true, closed_at>0）",
      r is not None and r.get("ok") is True and r.get("closed") is True
      and int(((r.get("poll") or {}).get("closed_at") or 0)) > 0)
    T("H6 结束后 status=closed", ((r or {}).get("poll") or {}).get("status") == "closed")
    st, r, _, _ = submit(p_mg, ["o2"], QA_C)
    T("H7 提前结束后再投票被拒「投票已结束」",
      r is not None and r.get("ok") is False and "已结束" in str(r.get("reason")))
    st, r, _, _ = manage(p_mg, "extend", QA_A, p_deadline=NOW0 - 1000)
    T("H8 延长的截止时间不晚于当前被拒",
      r is not None and r.get("ok") is False and "晚于" in str(r.get("reason")), r and r.get("reason"))
    st, r, _, _ = manage(p_mg, "extend", QA_A, p_deadline=NOW0 + 7200 * 1000)
    T("H9 延长/重开成功（closed=false，status=open）",
      r is not None and r.get("ok") is True and r.get("closed") is False
      and (r.get("poll") or {}).get("status") == "open")
    st, r, _, _ = submit(p_mg, ["o2"], QA_C)
    T("H10 重开后他人可投票", r is not None and r.get("ok") is True and r.get("total") == 2)
    # 编辑
    p_edit = pid("edit")
    st, r, _, _ = mk(p_edit, "编辑前", st=settings(), options=[opt(1), opt(2)])
    st, r, _, _ = manage(p_edit, "edit", QA_A, p_title="编辑后标题", p_description="新说明",
                         p_options=[opt(1, "甲"), opt(2, "乙"), opt(3, "丙")],
                         p_settings=settings(multi=True, maxChoices=2, anonymous=False),
                         p_deadline=NOW0 + 7200 * 1000)
    T("H11 0 票时发起人编辑成功（标题/选项/规则/截止全部更新）",
      r is not None and r.get("ok") is True
      and (r.get("poll") or {}).get("title") == "编辑后标题"
      and len((r.get("poll") or {}).get("options") or []) == 3
      and ((r.get("poll") or {}).get("settings") or {}).get("anonymous") is False
      and ((r.get("poll") or {}).get("settings") or {}).get("multi") is True,
      r and r.get("reason"))
    st, r, _, _ = manage(p_edit, "edit", QA_A, p_title="x", p_options=[opt(1)], p_settings=settings(),
                         p_deadline=0)
    T("H12 编辑参数不合法（1 个选项）被拒", r is not None and r.get("ok") is False)
    st, r, _, _ = manage(p_edit, "edit", QA_A, p_title="缺参数")
    T("H13 编辑缺 options/settings/deadline 被拒「参数不完整」",
      r is not None and r.get("ok") is False and "不完整" in str(r.get("reason")), r and r.get("reason"))
    st, r, _, _ = manage(p_mg, "edit", QA_A, p_title="有票编辑", p_description="",
                         p_options=[opt(1), opt(2)], p_settings=settings(), p_deadline=0)
    T("H14 已有票时编辑被拒「已有投票，不能修改内容」",
      r is not None and r.get("ok") is False and "已有投票" in str(r.get("reason")), r and r.get("reason"))
    st, r, _, _ = manage(p_edit, "shutdown", QA_A)
    T("H15 未知管理动作被拒「不支持的操作」",
      r is not None and r.get("ok") is False and "不支持" in str(r.get("reason")), r and r.get("reason"))

    # ================= I. 软删除 =================
    p_del = pid("del")
    st, r, _, _ = mk(p_del, "待删除投票", options=[opt(1), opt(2)])
    st, r, _, _ = submit(p_del, ["o1"], QA_A)
    st, r, _, _ = manage(p_del, "delete", QA_A)
    T("I1 发起人软删除成功（{ok:true,deleted:true}）",
      r is not None and r.get("ok") is True and r.get("deleted") is True)
    st, r, _, _ = rpc("poll_detail", {"p_id": p_del}, QA_A)
    T("I2 软删后详情不可查「投票不存在」", r is not None and r.get("ok") is False and "不存在" in str(r.get("reason")))
    st, rl, _, _ = rpc("poll_list", {}, QA_A)
    T("I3 软删后列表不返回", all(x.get("id") != p_del for x in ((rl or {}).get("polls") or [])))
    st, r, _, _ = submit(p_del, ["o2"], QA_B)
    T("I4 软删后不可投票（投票不存在）", r is not None and r.get("ok") is False and "不存在" in str(r.get("reason")))
    st, r, _, _ = manage(p_del, "delete", QA_A)
    T("I5 已软删的投票再管理返回不存在", r is not None and r.get("ok") is False and "不存在" in str(r.get("reason")))

    # ================= J. 注入 / 类型对抗 =================
    evil = "'; drop table public.polls;--"
    p_inj = pid("inj")
    st, r, _, _ = mk(p_inj, evil, desc="<script>alert(1)</script>", options=[opt(1, evil), opt(2)])
    T("J1 标题/选项含 SQL 注入串被当作普通文本存储（无报错）",
      r is not None and r.get("ok") is True and (r.get("poll") or {}).get("title") == evil,
      (r or {}).get("reason"))
    st, rd, _, _ = rpc("poll_detail", {"p_id": p_inj}, QA_A)
    T("J2 详情原样返回注入文本（转义责任在前端 esc）",
      rd is not None and (rd.get("poll") or {}).get("title") == evil)
    st, rl, _, _ = rpc("poll_list", {}, QA_A)
    T("J3 注入串未破坏表（列表仍正常返回）", rl is not None and rl.get("ok") is True and len(rl.get("polls") or []) > 0)
    st, r, _, _ = rpc("poll_create", {"p_id": "pqa' or '1'='1", "p_title": "x", "p_description": "",
                                      "p_mode": "long", "p_options": [opt(1), opt(2)],
                                      "p_settings": settings(), "p_deadline": 0}, QA_A)
    T("J4 p_id 注入串被正则拒绝（投票编号不合法）",
      r is not None and r.get("ok") is False, r and r.get("reason"))
    st, r, _, _ = mk(pid("types"), "类型对抗", options="not-an-array")
    T("J5 p_options 非数组被拒（选项格式不合法）",
      r is not None and r.get("ok") is False and "选项" in str(r.get("reason")), r and r.get("reason"))
    st, r, _, _ = submit(p_multi, {"a": 1}, QA_A)
    T("J6 p_choices 非数组被拒（选项不合法）",
      r is not None and r.get("ok") is False and "选项不合法" in str(r.get("reason")), r and r.get("reason"))
    st, r, _, _ = rpc("poll_detail", {"p_id": None}, QA_A)
    T("J7 p_id=null 返回「投票不存在」（不抛 500）", r is not None and r.get("ok") is False)

    # ================= K. RPC 响应全 JSON =================
    bad_ct = [x for x in RAW_POLL_RESPONSES if not x.strip().startswith("{")]
    T("K1 全部 poll_* RPC 响应体均为 JSON 对象", not bad_ct, "n_resp=%d bad=%d" % (len(RAW_POLL_RESPONSES), len(bad_ct)))
    return RESULTS


def cleanup_and_verify():
    """先硬删投票数据并复查（还持有 token），再删所有一次性会话 token。"""
    extra = []
    try:
        ids = [x for x in CREATED if x]
        if ids:
            lst = ",".join("'%s'" % i for i in ids)
            sql("delete from public.poll_votes where poll_id in (%s)" % lst)
            sql("delete from public.polls where id in (%s)" % lst)
        extra.append(("清理 1 测试投票硬删除（poll_votes + polls）", True, "n=%d" % len(ids)))
        gone = True
        for i in ids[:100]:
            st, r, _, _ = rpc("poll_detail", {"p_id": i}, REAL_TOKEN[0] or QA_A, collect=False)
            if not (isinstance(r, dict) and r.get("ok") is False and "不存在" in str(r.get("reason"))):
                gone = False
        extra.append(("清理 2 硬删后详情均不可查（逐 id 复查）", gone))
        st, rl, _, _ = rpc("poll_list", {}, REAL_TOKEN[0] or QA_A, collect=False)
        left = [x.get("id") for x in ((rl or {}).get("polls") or []) if x.get("id") in set(ids)]
        extra.append(("清理 3 硬删后列表无残留测试投票", not left, str(left)))
    except Exception as e:  # noqa: BLE001
        extra.append(("清理 1 测试投票硬删除", False, str(e)))
    try:
        toks = [t for t in SESSION_TOKENS if t]
        if toks:
            # 含真实 token：不打印语句（sql_quiet）
            lst = ",".join("'%s'" % t for t in toks)
            sql_quiet("delete from private.class_sessions where token in (%s)" % lst)
        extra.append(("清理 4 一次性 class_sessions token 全部删除", True, "n=%d" % len(toks)))
    except Exception as e:  # noqa: BLE001
        extra.append(("清理 4 一次性 class_sessions token 删除", False, str(e)))
    try:
        st, r, _, _ = rpc("poll_list", {}, QA_A, collect=False)
        extra.append(("清理 5 清除后 QA token 已失效", isinstance(r, dict) and r.get("ok") is False))
    except Exception as e:  # noqa: BLE001
        extra.append(("清理 5 清除后 QA token 已失效", False, str(e)))
    for item in extra:
        T(*item)
    return extra


def save_report():
    fails = [x for x in RESULTS if not x["ok"]]
    out = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "pass": len(RESULTS) - len(fails),
           "fail": len(fails), "results": RESULTS}
    with open(os.path.join(SHOTS, "cloud_report.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return len(fails)


if __name__ == "__main__":
    import traceback
    main_exc = False
    try:
        main()
    except Exception:  # noqa: BLE001 —— 测试脚本自身异常必须显式暴露，不能被 finally 的 sys.exit 吞掉
        main_exc = True
        traceback.print_exc()
        RESULTS.append({"name": "0.0 主流程未抛未捕获异常", "ok": False,
                        "note": traceback.format_exc()[-500:]})
    finally:
        cleanup_and_verify()
        nf = save_report()
        print("\n=========== vote_qa_cloud: %d PASS / %d FAIL ===========" % (len(RESULTS) - nf, nf))
        sys.exit(1 if (nf or main_exc) else 0)
