# -*- coding: utf-8 -*-
"""测试账号唯一化（2026-11-11 用户要求）。

**红线**：所有测试 / 验收 / 自动化脚本只允许使用：
  1) 官方测试身份 `3260799999 / 测试账号`（`private.class_ids.is_test=true`，公开凭据）；
  2) 测试脚本自行创建、并在 finally 删除的**临时 QA 测试身份**（`is_test=true`，学号 9999 段，
     仅存在于本次测试进程，绝不使用任何真实同学/管理员账号）。
禁止：登录真实账号、把真实账号 token 注入浏览器/自动化、用真实身份冒名构造 class_sessions。
生产运维服务（部署/PPT 转换机/迁移）不属于测试，其服务凭据另按 AGENTS §0-1 管理。
"""
TEST_SID = "3260799999"
TEST_NAME = "测试账号"
# 临时 QA 测试身份统一使用 9999 段（class_ids.is_test=true，脚本 finally 删除）
QA_SID_PREFIX = "9999"


def is_test_identity(sid, name=None):
    sid = str(sid or "")
    if sid == TEST_SID:
        return True
    if sid.startswith(QA_SID_PREFIX) and len(sid) == 10:
        return True
    return False


def assert_test_identity(sid, name=None, where=""):
    """测试身份守卫：非测试身份直接抛错，防止真实账号进入自动化。"""
    if is_test_identity(sid, name):
        return True
    raise SystemExit(
        "政策禁止：%s 使用了非测试身份 sid=%s（只允许 3260799999/测试账号或 9999 段临时 QA 测试身份）；"
        "详见 AGENTS.md §0 第 7 条 / tools/tests/_test_account.py" % (where or "测试脚本", sid))


def test_identity_snapshot(token="test-token", is_admin=False, role="", badge="", ts=None):
    """给前端 mock/自动化注入的测试身份快照（无真实账号字段）。"""
    import time
    return {
        "token": token,
        "sid": TEST_SID,
        "name": TEST_NAME,
        "role": role or "",
        "badge": badge or "",
        "is_admin": bool(is_admin),
        "ts": int(ts if ts is not None else time.time() * 1000),
    }


def test_identity_token(rest_base, publish_key, session=None):
    """用测试身份换取真实 class token（不打印 token；仅测试身份）。"""
    import json
    import urllib.request

    headers = {"Authorization": "Bearer " + publish_key,
               "Content-Type": "application/json"}
    data = json.dumps({"p_sid": TEST_SID, "p_name": TEST_NAME}).encode("utf-8")
    req = urllib.request.Request(rest_base.rstrip("/") + "/rpc/class_verify",
                                 data=data, headers=headers, method="POST")
    try:
        if session is not None:
            with session.post(rest_base.rstrip("/") + "/rpc/class_verify",
                              headers=headers, json={"p_sid": TEST_SID, "p_name": TEST_NAME},
                              timeout=30) as resp:
                obj = resp.json()
        else:
            with urllib.request.urlopen(req, timeout=30) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
    except Exception:
        raise SystemExit("测试身份登录失败（网络/网关不可用）")
    tok = str((obj or {}).get("token") or "")
    if not tok:
        raise SystemExit("测试身份登录失败（class_verify 未返回 token）")
    return tok
