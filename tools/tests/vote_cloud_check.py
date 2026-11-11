# -*- coding: utf-8 -*-
"""投票功能云端 API 专项验收（真实 CloudBase PostgreSQL / PostgREST，契约 web/vote/CONTRACT.md §1/§2）

覆盖：鉴权、发起（标题/说明/选项/图片/规则/截止时间校验、幂等）、列表/详情、单选/多选/上限、
改票/不可改票、一人一票、匿名不泄露、实名投票人、结果三种可见性、截止/提前结束/延长、
编辑（无票/有票）、删除（软删）、权限（他人不可管理/不可直连表）、服务端截止时间（以 DB 时间判定）。

身份：使用**测试身份**（3260799999/测试账号，云端 is_test 行）与两个**合成 QA 会话**（private.class_sessions
内一次性 token，脚本结束时删除）。所有测试投票在 finally 中硬删除，不残留。

运行：cd web/tools && python tests\\vote_cloud_check.py
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
WEB = os.path.dirname(os.path.dirname(HERE))          # web/
REST = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
KEY = open(os.path.join(WEB, "deploy", "cloudbase", "publish_key.txt"), encoding="utf-8").read().strip()
TEST_SID, TEST_NAME = "3260799999", "测试账号"
QA_A, QA_B = "qatok_vote_a", "qatok_vote_b"
# 可见人范围测试用：真实班级身份的一次性会话（班委 seat16 / 仅团员 seat1 / 普通 seat2 / 管理员 sid）
AUD_COMMITTEE, AUD_LEAGUE, AUD_PLAIN, AUD_ADMIN = (
    "qatok_aud_committee", "qatok_aud_league", "qatok_aud_plain", "qatok_aud_admin")
NOW = int(time.time() * 1000)
RESULTS = []
CREATED = []          # 本脚本创建的 poll id（finally 硬删除）
EXTRA_TOKENS = []     # 需要清理的 class_sessions.token

# 复用 deploy/cloudbase/apply_sql.py 的 node+tcb 通道执行 SQL（建 QA 会话 / 清理数据）
_spec = importlib.util.spec_from_file_location("apply_sql", os.path.join(WEB, "deploy", "cloudbase", "apply_sql.py"))
apply_sql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply_sql)


def sql(stmt):
    return apply_sql.run_stmt(1, stmt, False)


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


def hdr(tok):
    h = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
    if tok:
        h["X-Device-Id"] = tok
    h["Origin"] = "https://tool.furina.fun"
    return h


def rpc(name, body, tok):
    try:
        r = requests.post(REST + "rpc/" + name, headers=hdr(tok), json=body if body is not None else {}, timeout=40)
        return r.status_code, r.json()
    except Exception as e:  # noqa: BLE001
        return 0, {"ok": False, "reason": "request-error:%s" % e}


def opt(i, text=None, desc="", img=""):
    return {"id": "o%d" % i, "text": text or ("选项%d" % i), "desc": desc, "img": img}


def settings(**kw):
    s = {"multi": False, "maxChoices": 1, "anonymous": True, "allowChange": True, "resultVisibility": "afterVote"}
    s.update(kw)
    return s


def mk(pid, title, *, options=None, st=None, deadline=0, mode="quick", desc="", tok=QA_A, audience=None, seats=None):
    body = {"p_id": pid, "p_title": title, "p_description": desc, "p_mode": mode,
            "p_options": options or [opt(1), opt(2), opt(3)], "p_settings": st or settings(),
            "p_deadline": deadline}
    if audience is not None:
        body["p_audience"] = audience
    if seats is not None:
        body["p_audience_seats"] = seats
    return rpc("poll_create", body, tok)


def token_of(tid):
    st, r = rpc("poll_detail", {"p_id": tid}, QA_A)
    return (r or {}).get("ok")


def main():
    fails0 = len([x for x in RESULTS if not x["ok"]])
    # ---- 0. 准备：合成 QA 会话（幂等） ----
    sql("insert into private.class_sessions(token,sid,name,expires_at) values "
        "('qatok_vote_a','9999000001','投票测试甲',now()+interval '2 days'),"
        "('qatok_vote_b','9999000002','投票测试乙',now()+interval '2 days') "
        "on conflict (token) do nothing")
    # 可见人范围：给真实班级身份造一次性 token（班委 / 仅团员 / 普通 / 管理员），仅测试用，finally 删除
    sql("insert into private.class_sessions(token,sid,name,expires_at) "
        "select 'qatok_aud_committee', c.sid, c.name, now()+interval '2 hours' from private.class_ids c where c.seat=16 "
        "union all select 'qatok_aud_league', c.sid, c.name, now()+interval '2 hours' from private.class_ids c where c.seat=1 "
        "union all select 'qatok_aud_plain', c.sid, c.name, now()+interval '2 hours' from private.class_ids c where c.seat=2 "
        "on conflict do nothing")
    sql("insert into private.class_sessions(token,sid,name,expires_at) "
        "select 'qatok_aud_admin', c.sid, c.name, now()+interval '2 hours' from private.class_ids c "
        "where c.sid='3260707024' on conflict do nothing")
    st, mem = rpc("poll_list", {}, QA_A)
    T("QA 会话可用（poll_list ok）", bool(mem.get("ok")), str(mem)[:120])
    st, r = rpc("poll_list", {}, None)
    T("无班级 token 拒绝（ok=false）", r.get("ok") is False, r.get("reason"))

    # ---- 1. 校验与幂等 ----
    pid = "pqa" + str(NOW)[-8:] + "a"
    st, r = mk(pid, "x", options=[opt(1)])
    T("选项少于 2 个被拒绝", r.get("ok") is False and "2" in str(r.get("reason")), r.get("reason"))
    st, r = mk(pid, "x" * 81)
    T("标题超过 80 字被拒绝", r.get("ok") is False, r.get("reason"))
    st, r = mk(pid, "x", desc="d" * 501)
    T("说明超过 500 字被拒绝", r.get("ok") is False, r.get("reason"))
    st, r = mk(pid, "x", deadline=NOW - 1000)
    T("截止时间早于当前被拒绝", r.get("ok") is False, r.get("reason"))
    st, r = mk(pid, "x", options=[opt(1), opt(2, img="http://evil/x.png")])
    T("选项图片非 data:image/ 被拒绝", r.get("ok") is False, r.get("reason"))
    st, r = mk(pid, "x", options=[opt(1), opt(2, img="data:image/jpeg;base64," + "A" * 150001)])
    T("选项图片超长被拒绝", r.get("ok") is False, r.get("reason"))
    st, r = mk(pid, "x", st=settings(resultVisibility="bad"))
    T("结果可见性非法被拒绝", r.get("ok") is False, r.get("reason"))
    st, r = mk(pid, "x", st=settings(multi=True, maxChoices=1))
    T("多选 maxChoices<2 被拒绝", r.get("ok") is False, r.get("reason"))
    st, r = mk(pid, "x", st=settings(multi=True, maxChoices=9), options=[opt(1), opt(2), opt(3)])
    T("多选 maxChoices>选项数时归一为选项数",
      r.get("ok") is True and (r.get("poll", {}).get("settings") or {}).get("maxChoices") == 3, r.get("reason"))
    if r.get("ok"):
        CREATED.append(pid)
    detail1 = r
    body = {"p_id": pid, "p_title": "幂等标题", "p_description": "", "p_mode": "quick",
            "p_options": [opt(1), opt(2)], "p_settings": settings(), "p_deadline": 0}
    st, r2 = rpc("poll_create", body, QA_A)
    T("同 p_id 重复发起幂等（返回同一投票、不覆盖内容）",
      r2.get("ok") is True and (r2.get("poll") or {}).get("id") == pid and
      (r2.get("poll") or {}).get("title") == (detail1.get("poll") or {}).get("title"),
      (r2.get("poll") or {}).get("title"))

    # ---- 2. 正常发起（临时限时 + 匿名 + 投票后可见 + 可改票） ----
    p1 = "pqa" + str(NOW)[-8:] + "b"
    st, r = mk(p1, "班会时间投票", desc="请选择合适时间", deadline=NOW + 3600 * 1000)
    T("发起限时投票成功", r.get("ok") is True and (r.get("poll") or {}).get("title") == "班会时间投票", r.get("reason"))
    if r.get("ok"):
        CREATED.append(p1)
    T("创建返回：can_manage / mine / 结果隐藏（afterVote 未投）",
      r.get("can_manage") is True and r.get("mine") is True and r.get("results_hidden") is True and r.get("total") == 0)
    T("创建返回不含学号 sid 字段", "'sid'" not in json.dumps(r) and "owner_sid" not in json.dumps(r))
    st, rl = rpc("poll_list", {}, QA_A)
    row = [x for x in (rl.get("polls") or []) if x.get("id") == p1]
    T("列表中可查到该投票且按创建倒序在前", len(row) == 1 and (rl.get("polls") or [{}])[0].get("id") == p1,
      (rl.get("polls") or [{}])[0].get("id"))
    T("列表同样不含学号 sid", "'sid'" not in json.dumps(rl))

    # ---- 3. 投票 / 改票 / 单选上限 ----
    st, r = rpc("poll_submit", {"p_id": p1, "p_choices": ["o1"]}, QA_A)
    T("单选投票成功且计数正确", r.get("ok") is True and r.get("counts") == {"o1": 1} and r.get("has_voted") is True, r.get("reason"))
    st, r = rpc("poll_submit", {"p_id": p1, "p_choices": ["o2"]}, QA_A)
    T("允许改票时改票成功", r.get("ok") is True and r.get("counts") == {"o2": 1} and r.get("total") == 1)
    st, r = rpc("poll_submit", {"p_id": p1, "p_choices": ["o1", "o2"]}, QA_A)
    T("单选提交 2 项被拒绝", r.get("ok") is False and r.get("reason") == "只能选 1 项", r.get("reason"))
    st, r = rpc("poll_submit", {"p_id": p1, "p_choices": ["ox"]}, QA_A)
    T("不存在的选项被拒绝", r.get("ok") is False and r.get("reason") == "选项不合法", r.get("reason"))
    st, r = rpc("poll_submit", {"p_id": p1, "p_choices": ["o2", "o2"]}, QA_A)
    T("重复选项被拒绝", r.get("ok") is False, r.get("reason"))
    st, r = rpc("poll_submit", {"p_id": p1, "p_choices": ["o1"]}, QA_B)
    T("第二人投票计数累加且匿名不返回投票人",
      r.get("ok") is True and r.get("total") == 2 and r.get("counts") == {"o1": 1, "o2": 1} and r.get("voters") == [],
      r.get("counts"))
    T("他人 can_manage=false", r.get("can_manage") is False and r.get("mine") is False)

    # ---- 4. 权限 / 编辑 ----
    st, r = rpc("poll_manage", {"p_id": p1, "p_action": "close"}, QA_B)
    T("非发起人不能提前结束", r.get("ok") is False and "无权" in str(r.get("reason")), r.get("reason"))
    st, r = rpc("poll_manage", {"p_id": p1, "p_action": "edit", "p_title": "改名", "p_description": "",
                                "p_options": [opt(1), opt(2)], "p_settings": settings(), "p_deadline": 0}, QA_A)
    T("已有票时编辑被拒绝", r.get("ok") is False and "已有投票" in str(r.get("reason")), r.get("reason"))

    # ---- 5. 提前结束 / 延长 ----
    st, r = rpc("poll_manage", {"p_id": p1, "p_action": "close"}, QA_A)
    T("提前结束成功且 closed=true", r.get("ok") is True and r.get("closed") is True and r.get("total") == 2)
    st, r = rpc("poll_submit", {"p_id": p1, "p_choices": ["o3"]}, QA_B)
    T("结束后再投票被拒绝", r.get("ok") is False and "已结束" in str(r.get("reason")), r.get("reason"))
    st, r = rpc("poll_manage", {"p_id": p1, "p_action": "extend", "p_deadline": NOW + 7200 * 1000}, QA_A)
    T("延长/重开成功（closed=false）", r.get("ok") is True and r.get("closed") is False)
    st, r = rpc("poll_submit", {"p_id": p1, "p_choices": ["o3"]}, QA_B)
    T("重开后第二人改票成功", r.get("ok") is True and r.get("counts") == {"o2": 1, "o3": 1}, r.get("counts"))

    # ---- 6. 不可改票 / 多选 / 实名 / afterClose ----
    p2 = "pqa" + str(NOW)[-8:] + "c"
    st, r = mk(p2, "不可改票测试", st=settings(allowChange=False))
    if r.get("ok"):
        CREATED.append(p2)
    st, r = rpc("poll_submit", {"p_id": p2, "p_choices": ["o1"]}, QA_A)
    T("不可改票：首次投票成功", r.get("ok") is True)
    st, r = rpc("poll_submit", {"p_id": p2, "p_choices": ["o2"]}, QA_A)
    T("不可改票：第二次被拒绝", r.get("ok") is False and r.get("reason") == "已投过票，不可改票", r.get("reason"))

    p3 = "pqa" + str(NOW)[-8:] + "d"
    st, r = mk(p3, "多选测试", st=settings(multi=True, maxChoices=2), deadline=NOW + 600 * 1000)
    if r.get("ok"):
        CREATED.append(p3)
    st, r = rpc("poll_submit", {"p_id": p3, "p_choices": ["o1", "o2", "o3"]}, QA_A)
    T("多选超过上限被拒绝", r.get("ok") is False and r.get("reason") == "最多选 2 项", r.get("reason"))
    st, r = rpc("poll_submit", {"p_id": p3, "p_choices": ["o1", "o2"]}, QA_A)
    T("多选 2 项提交成功", r.get("ok") is True and r.get("counts") == {"o1": 1, "o2": 1}, r.get("counts"))

    p4 = "pqa" + str(NOW)[-8:] + "e"
    st, r = mk(p4, "实名测试", st=settings(anonymous=False))
    if r.get("ok"):
        CREATED.append(p4)
    st, r = rpc("poll_submit", {"p_id": p4, "p_choices": ["o1"]}, QA_A)
    T("实名投票：返回投票人条目且无 sid（合成会话姓名可为空，真实姓名见 §9）",
      r.get("ok") is True and len(r.get("voters") or []) == 1
      and "name" in (r.get("voters") or [{}])[0] and "choices" in (r.get("voters") or [{}])[0]
      and '"sid"' not in json.dumps(r.get("voters")), r.get("voters"))

    p5 = "pqa" + str(NOW)[-8:] + "f"
    st, r = mk(p5, "截止后可见测试", st=settings(resultVisibility="afterClose"), deadline=NOW + 600 * 1000)
    if r.get("ok"):
        CREATED.append(p5)
    st, r = rpc("poll_submit", {"p_id": p5, "p_choices": ["o1"]}, QA_A)
    T("afterClose：投票后仍隐藏 counts", r.get("ok") is True and r.get("results_hidden") is True and r.get("counts") == {})
    st, r = rpc("poll_list", {}, QA_A)
    row = [x for x in (r.get("polls") or []) if x.get("id") == p5]
    T("afterClose：列表同样隐藏 counts 但 total 可见",
      len(row) == 1 and row[0].get("results_hidden") is True and row[0].get("counts") == {} and row[0].get("total") == 1)
    st, r = rpc("poll_manage", {"p_id": p5, "p_action": "close"}, QA_A)
    T("afterClose：提前结束后结果可见", r.get("ok") is True and r.get("results_hidden") is False and r.get("counts") == {"o1": 1})
    st, r = rpc("poll_detail", {"p_id": p5}, QA_B)
    T("afterClose：他人截止后可见结果", r.get("ok") is True and r.get("results_hidden") is False and r.get("counts") == {"o1": 1})

    # ---- 7. 服务端截止时间（DB 时间判定，不信任客户端） ----
    p6 = "pqa" + str(NOW)[-8:] + "g"
    st, r = mk(p6, "服务端截止测试", deadline=NOW + 3600 * 1000)
    if r.get("ok"):
        CREATED.append(p6)
    ok_sql = sql("update public.polls set deadline = %d where id = '%s'" % (NOW - 5000, p6))
    T("SQL 修改截止时间为过去", ok_sql)
    st, r = rpc("poll_submit", {"p_id": p6, "p_choices": ["o1"]}, QA_A)
    T("已过截止时间：服务端拒绝投票", r.get("ok") is False and "已结束" in str(r.get("reason")), r.get("reason"))
    st, r = rpc("poll_detail", {"p_id": p6}, QA_A)
    T("已过截止时间：详情 closed=true", r.get("ok") is True and r.get("closed") is True)

    # ---- 8. 编辑（无票时） ----
    p7 = "pqa" + str(NOW)[-8:] + "h"
    st, r = mk(p7, "编辑前标题", st=settings(), deadline=NOW + 3600 * 1000)
    if r.get("ok"):
        CREATED.append(p7)
    st, r = rpc("poll_manage", {"p_id": p7, "p_action": "edit", "p_title": "编辑后标题", "p_description": "新说明",
                                "p_options": [opt(1, "甲"), opt(2, "乙"), opt(3, "丙")],
                                "p_settings": settings(multi=True, maxChoices=2, anonymous=False),
                                "p_deadline": NOW + 7200 * 1000}, QA_A)
    T("无票时编辑成功", r.get("ok") is True and (r.get("poll") or {}).get("title") == "编辑后标题"
      and len((r.get("poll") or {}).get("options") or []) == 3, r.get("reason"))
    T("编辑后规则生效", ((r.get("poll") or {}).get("settings") or {}).get("multi") is True
      and ((r.get("poll") or {}).get("settings") or {}).get("anonymous") is False)
    st, r = rpc("poll_manage", {"p_id": p7, "p_action": "edit", "p_title": "x", "p_description": "",
                                "p_options": [opt(1)], "p_settings": settings(), "p_deadline": 0}, QA_A)
    T("编辑参数不合法被拒绝", r.get("ok") is False, r.get("reason"))

    # ---- 9. 测试身份 owner_name + 删除 ----
    st, r = rpc("class_verify", {"p_sid": TEST_SID, "p_name": TEST_NAME}, None)
    tok_t = (r or {}).get("token") if (r or {}).get("ok") else ""
    if tok_t:
        EXTRA_TOKENS.append(tok_t)
    T("测试身份登录（class_verify）", bool(tok_t) and (r or {}).get("is_admin") is False)
    p8 = "pqa" + str(NOW)[-8:] + "i"
    st, r = mk(p8, "测试身份发起的投票", options=[opt(1), opt(2)], tok=tok_t)
    if r.get("ok"):
        CREATED.append(p8)
    T("测试身份发起：owner_name 由服务端从班名单取",
      (r.get("poll") or {}).get("owner_name") == TEST_NAME, (r.get("poll") or {}).get("owner_name"))
    # 实名投票人姓名（测试身份投票 → 真实姓名来自 private.class_ids）
    p9 = "pqa" + str(NOW)[-8:] + "j"
    st, r = mk(p9, "实名姓名测试", options=[opt(1), opt(2)], st=settings(anonymous=False), tok=QA_A)
    if r.get("ok"):
        CREATED.append(p9)
    st, r = rpc("poll_submit", {"p_id": p9, "p_choices": ["o1"]}, tok_t)
    T("实名投票人返回真实姓名（测试账号）",
      r.get("ok") is True and [v.get("name") for v in (r.get("voters") or [])] == [TEST_NAME],
      r.get("voters"))
    st, r = rpc("poll_manage", {"p_id": p8, "p_action": "delete"}, tok_t)
    T("软删除返回 {ok:true,deleted:true}", r.get("ok") is True and r.get("deleted") is True)
    st, r = rpc("poll_detail", {"p_id": p8}, QA_A)
    T("删除后详情不可见（投票不存在）", r.get("ok") is False and "不存在" in str(r.get("reason")))
    st, rl = rpc("poll_list", {}, QA_A)
    T("删除后列表不再返回", all(x.get("id") != p8 for x in (rl.get("polls") or [])))

    # ---- 9b. 可见人范围 audience（2026-11-11 18:08 增量） ----
    audit_raw = []

    def lst(tok):
        return rpc("poll_list", {}, tok)[1]

    def has(lst_, pid_):
        return any(x.get("id") == pid_ for x in (lst_.get("polls") or []))

    # 旧客户端不传 p_audience → 默认 all（向后兼容）
    pdef = "pqa" + str(NOW)[-8:] + "k"
    st, r = mk(pdef, "默认范围测试")
    audit_raw.append(json.dumps(r, ensure_ascii=False))
    T("旧客户端不传范围：默认 audience=all",
      r.get("ok") is True and (r.get("poll") or {}).get("audience") == "all"
      and (r.get("poll") or {}).get("audience_count") == 0, r.get("reason"))
    if r.get("ok"):
        CREATED.append(pdef)

    # 班委可见
    pcom = "pqa" + str(NOW)[-8:] + "m"
    st, r = mk(pcom, "班委可见测试", audience="committee")
    audit_raw.append(json.dumps(r, ensure_ascii=False))
    T("创建班委可见投票", r.get("ok") is True and (r.get("poll") or {}).get("audience") == "committee", r.get("reason"))
    if r.get("ok"):
        CREATED.append(pcom)
    l_com, l_lea, l_pla, l_own = lst(AUD_COMMITTEE), lst(AUD_LEAGUE), lst(AUD_PLAIN), lst(QA_A)
    T("班委可见：班委列表可见 / 普通成员不可见", has(l_com, pcom) and not has(l_pla, pcom),
      "com=%s plain=%s" % (has(l_com, pcom), has(l_pla, pcom)))
    T("班委可见：仅团员（非班委）不可见", not has(l_lea, pcom))
    T("班委可见：发起人即使不在该范围仍可见", has(l_own, pcom))
    st, d = rpc("poll_detail", {"p_id": pcom}, AUD_PLAIN)
    audit_raw.append(json.dumps(d, ensure_ascii=False))
    T("班委可见：普通成员详情返回「投票不存在」", d.get("ok") is False and "不存在" in str(d.get("reason")), d.get("reason"))
    st, d = rpc("poll_submit", {"p_id": pcom, "p_choices": ["o1"]}, AUD_PLAIN)
    T("班委可见：普通成员不能投票", d.get("ok") is False and "不存在" in str(d.get("reason")), d.get("reason"))
    st, d = rpc("poll_detail", {"p_id": pcom}, AUD_ADMIN)
    T("班委可见：管理员越权可见且 can_manage=true", d.get("ok") is True and d.get("can_manage") is True)

    # 团员可见
    pleag = "pqa" + str(NOW)[-8:] + "n"
    st, r = mk(pleag, "团员可见测试", audience="league")
    T("创建团员可见投票", r.get("ok") is True and (r.get("poll") or {}).get("audience") == "league", r.get("reason"))
    if r.get("ok"):
        CREATED.append(pleag)
    l_com, l_lea, l_pla = lst(AUD_COMMITTEE), lst(AUD_LEAGUE), lst(AUD_PLAIN)
    T("团员可见：团员可见 / 普通不可见 / 非团员班委不可见",
      has(l_lea, pleag) and not has(l_pla, pleag) and not has(l_com, pleag),
      "lea=%s plain=%s com=%s" % (has(l_lea, pleag), has(l_pla, pleag), has(l_com, pleag)))

    # 指定成员（座号 1、2）
    pcus = "pqa" + str(NOW)[-8:] + "o"
    st, r = mk(pcus, "指定成员可见测试", audience="custom", seats=[1, 2])
    audit_raw.append(json.dumps(r, ensure_ascii=False))
    T("创建指定成员可见投票（audience_count=2）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience") == "custom"
      and (r.get("poll") or {}).get("audience_count") == 2, r.get("reason"))
    if r.get("ok"):
        CREATED.append(pcus)
    l_com, l_lea, l_pla, l_own = lst(AUD_COMMITTEE), lst(AUD_LEAGUE), lst(AUD_PLAIN), lst(QA_A)
    T("指定成员：名单内团员/普通可见", has(l_lea, pcus) and has(l_pla, pcus))
    T("指定成员：名单外班委不可见 / 发起人可见", not has(l_com, pcus) and has(l_own, pcus))
    st, d = rpc("poll_detail", {"p_id": pcus}, AUD_PLAIN)
    audit_raw.append(json.dumps(d, ensure_ascii=False))
    T("指定成员：名单内成员可看详情且无管理权、不回传座号名单",
      d.get("ok") is True and d.get("can_manage") is False
      and (d.get("poll") or {}).get("audience_seats") == []
      and (d.get("poll") or {}).get("audience_count") == 2, str((d.get("poll") or {}).get("audience_seats")))
    st, d = rpc("poll_detail", {"p_id": pcus}, QA_A)
    T("指定成员：发起人（编辑回填）可见座号数组", d.get("ok") is True and (d.get("poll") or {}).get("audience_seats") == [1, 2])
    st, d = rpc("poll_submit", {"p_id": pcus, "p_choices": ["o1"]}, AUD_ADMIN)
    T("指定成员：管理员不在名单内不能投票（reason=不在可见范围内）",
      d.get("ok") is False and d.get("reason") == "不在可见范围内", d.get("reason"))
    st, d = rpc("poll_submit", {"p_id": pcus, "p_choices": ["o1"]}, AUD_PLAIN)
    T("指定成员：名单内成员可投票", d.get("ok") is True and d.get("has_voted") is True)
    st, d = rpc("poll_submit", {"p_id": pcus, "p_choices": ["o2"]}, QA_A)
    T("指定成员：发起人不在名单也可投票（owner 例外）", d.get("ok") is True)

    # 范围校验
    pbad = "pqa" + str(NOW)[-8:] + "p"
    st, r = mk(pbad, "空名单范围", audience="custom", seats=[])
    T("custom 无可视成员被拒绝", r.get("ok") is False and "请选择可见成员" in str(r.get("reason")), r.get("reason"))
    st, r = mk(pbad, "不存在座号", audience="custom", seats=[9999])
    T("custom 座号不存在被拒绝", r.get("ok") is False and "请选择可见成员" in str(r.get("reason")), r.get("reason"))
    st, r = mk(pbad, "非法范围", audience="admin")
    T("非法可见范围被拒绝", r.get("ok") is False and "可见范围不合法" in str(r.get("reason")), r.get("reason"))
    pnorm = "pqa" + str(NOW)[-8:] + "q"
    st, r = mk(pnorm, "座号归一", audience="custom", seats=[5, 2, 2, "x"])
    audit_raw.append(json.dumps(r, ensure_ascii=False))
    T("custom 座号去重/过滤/升序（[2,5]）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience_count") == 2, r.get("reason"))
    if r.get("ok"):
        CREATED.append(pnorm)
    st, d = rpc("poll_detail", {"p_id": pnorm}, QA_A)
    T("custom 座号归一结果正确（owner 回读 [2,5]）", d.get("ok") is True and (d.get("poll") or {}).get("audience_seats") == [2, 5])

    # 编辑可见范围（无票）/ 旧客户端 edit 不改范围 / 有票后拒绝
    ped = "pqa" + str(NOW)[-8:] + "r"
    st, r = mk(ped, "编辑范围测试")
    if r.get("ok"):
        CREATED.append(ped)
    st, r = rpc("poll_manage", {"p_id": ped, "p_action": "edit", "p_title": "改范围", "p_description": "",
                                "p_options": [opt(1), opt(2)], "p_settings": settings(), "p_deadline": 0,
                                "p_audience": "committee"}, QA_A)
    T("编辑：all→committee 成功", r.get("ok") is True and (r.get("poll") or {}).get("audience") == "committee")
    st, r = rpc("poll_manage", {"p_id": ped, "p_action": "edit", "p_title": "改范围2", "p_description": "",
                                "p_options": [opt(1), opt(2)], "p_settings": settings(), "p_deadline": 0,
                                "p_audience": "custom", "p_audience_seats": [1, 2]}, QA_A)
    T("编辑：committee→custom 成功", r.get("ok") is True and (r.get("poll") or {}).get("audience") == "custom"
      and (r.get("poll") or {}).get("audience_count") == 2)
    st, r = rpc("poll_manage", {"p_id": ped, "p_action": "edit", "p_title": "改范围3", "p_description": "",
                                "p_options": [opt(1), opt(2)], "p_settings": settings(), "p_deadline": 0}, QA_A)
    T("旧客户端 edit 不传范围：保持原范围不变（custom）",
      r.get("ok") is True and (r.get("poll") or {}).get("audience") == "custom")
    rpc("poll_submit", {"p_id": ped, "p_choices": ["o1"]}, AUD_PLAIN)  # seat2 在 custom 名单内
    st, r = rpc("poll_manage", {"p_id": ped, "p_action": "edit", "p_title": "x", "p_description": "",
                                "p_options": [opt(1), opt(2)], "p_settings": settings(), "p_deadline": 0,
                                "p_audience": "all"}, QA_A)
    T("已有票后编辑范围被拒绝", r.get("ok") is False and "已有投票" in str(r.get("reason")), r.get("reason"))

    # audience 相关响应原文扫描：不得出现 "sid" 字段/学号
    raw_all = "".join(audit_raw)
    T("可见范围相关 RPC 响应不含 sid 字段", '"sid"' not in raw_all and "owner_sid" not in raw_all,
      raw_all[:120])

    # ---- 10. 直连表被拒（anon 无权限） ----
    for tbl in ("polls", "poll_votes"):
        try:
            rr = requests.get(REST + tbl + "?select=*", headers=hdr(QA_A), timeout=20)
            denied = rr.status_code in (401, 403, 404) or (rr.status_code == 200 and rr.json() == [])
        except Exception:
            denied = True
        T("直连 %s 表被拒绝" % tbl, denied, getattr(rr, "status_code", "?"))
    T("匿名（无 token）直连 RPC 返回 ok=false", rpc("poll_list", {}, None)[1].get("ok") is False)

    return RESULTS


if __name__ == "__main__":
    try:
        main()
    finally:
        # 硬删除测试投票（先删票再删投票；按 id 精确删除，绝不触碰真实班级投票）
        try:
            ids = [x for x in CREATED if x]
            if ids:
                lst = ",".join("'%s'" % i for i in ids)
                sql("delete from public.poll_votes where poll_id in (%s)" % lst)
                sql("delete from public.polls where id in (%s)" % lst)
            sql("delete from private.class_sessions where token in "
                "('qatok_vote_a','qatok_vote_b','qatok_aud_committee','qatok_aud_league','qatok_aud_plain','qatok_aud_admin')")
            for t in EXTRA_TOKENS:
                if t:
                    sql("delete from private.class_sessions where token = '%s'" % t)
            print("[cleanup] polls=%d sessions=cleaned" % len(CREATED))
        except Exception as e:  # noqa: BLE001
            print("[cleanup] FAILED: %s" % e)
        fails = len([x for x in RESULTS if not x["ok"]])
        print("\n=========== vote_cloud_check: %d PASS / %d FAIL ===========" % (len(RESULTS) - fails, fails))
        sys.exit(1 if fails else 0)
