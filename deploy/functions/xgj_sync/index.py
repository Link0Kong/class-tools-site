# -*- coding: utf-8 -*-
"""CloudBase 云函数：班级小管家 英语作业采集（XGJ 云端版）。

迁移目标（task-29）：本机 `run_hw_auto.py` 中的 xgj 步骤每 2h 跑
`xgj_homework.py --collect --merge`，随后 `sync_homework_cloud.py` 把
`data/auto-homework.json` 全量同步到 public.homework（含归档过期行）。
云端函数**只负责英语作业**：
    * 复用 xgj_homework.py 的 API/签名/token 逻辑（部署时复制到本目录）；
    * token 由环境变量 XGJ_TOKEN / XGJ_MEMBER_ID 等提供；
    * 只 upsert / 归档 `auto_hw_xgj_en_*` 前缀行，绝不碰其它来源（math/doc/sizheng…）；
    * 不依赖电脑开机（云函数 + 定时触发器），幂等：内容不变时 PATCH 同一行。

环境变量（云函数配置里设置，不写进代码/仓库）：
    CB_BASE          PostgREST 基地址
    CB_KEY           匿名 publishable key
    CLASS_ADMIN_SID / CLASS_ADMIN_NAME  管理员 token 换取（或 CLASS_TOKEN）
    XGJ_TOKEN / XGJ_MEMBER_ID / XGJ_EXP / XGJ_EXP_TEXT / XGJ_CID

返回：{"ok": bool, "english": n, "pending": n, "cloud_ok": n, "archived": n, "error": ...}
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
PREFIX = "auto_hw_"
OWN_PREFIX = PREFIX + "xgj_en_"
RECEIPT_ID = "xgj-sync-status"


def _env(name, default=""):
    v = os.environ.get(name)
    return v if v else default


def _http(base, key, path, body=None, method="GET", token=None, timeout=15, prefer=None):
    import urllib.error
    import urllib.request
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if token:
        headers["X-Device-Id"] = token
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8") \
        if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _token(base, key):
    tok = _env("CLASS_TOKEN")
    if tok:
        return tok
    st, out = _http(base, key, "rpc/class_verify",
                    {"p_sid": _env("CLASS_ADMIN_SID"), "p_name": _env("CLASS_ADMIN_NAME")}, "POST")
    if st != 200 or not isinstance(out, dict) or not out.get("token"):
        raise RuntimeError("class_verify failed: HTTP %s" % st)
    return out["token"]


def _setup_tmp(xgj, directory):
    tmp = Path(directory)
    for sub in ("data", "logs", "secrets"):
        (tmp / sub).mkdir(parents=True, exist_ok=True)
    xgj.DATA = tmp / "data"
    xgj.LOGS = tmp / "logs"
    xgj.SECRETS = tmp / "secrets"
    xgj.OUT = xgj.DATA / "xgj-homework.json"
    xgj.STATUS = xgj.DATA / "xgj-collect-status.json"
    xgj.AUTO = xgj.DATA / "auto-homework.json"
    xgj.SECRET = xgj.SECRETS / "xjg-token.json"
    xgj.LOG = xgj.LOGS / "xgj-homework.log"
    # 环境变量按字段拆开（整段 JSON 作为环境变量在 tcb CLI 传参时会报类型错误）
    token = _env("XGJ_TOKEN")
    member_id = _env("XGJ_MEMBER_ID")
    if not token or not member_id:
        raise RuntimeError("XGJ_TOKEN/XGJ_MEMBER_ID 未配置")
    exp = 0
    try:
        exp = int(_env("XGJ_EXP") or 0)
    except ValueError:
        exp = 0
    sec = {"token": token, "member_id": member_id, "exp": exp,
           "exp_text": _env("XGJ_EXP_TEXT"), "cid": _env("XGJ_CID"),
           "note": "cloud function env (来自本机 secrets/xjg-token.json；勿外传)"}
    xgj.SECRET.write_text(json.dumps(sec, ensure_ascii=False), encoding="utf-8")


def _sync_homework(base, key, token, payload):
    items = payload.get("items") or []
    pending = [r for r in items if r.get("status") == "未完成"]
    want = {}
    for r in pending:
        rid = PREFIX + str(r.get("key") or "")
        if not rid.startswith(OWN_PREFIX) or len(rid) == len(OWN_PREFIX):
            raise ValueError("unexpected homework source key")
        want[rid] = {
            "id": rid,
            "subject": (r.get("subject") or "")[:80],
            "content": r.get("content") or "",
            "due": (r.get("due") or "")[:80],
            "date": r.get("date") or "",
            "time": r.get("time") or "",
            "author": (r.get("author") or "自动识别")[:40],
            "owner": "auto",
            "attachments": "",
            "done": False,
            "archived": False,
            "ts": int(r.get("ts") or 0) or int(time.time() * 1000),
        }
    def list_rows():
        st, rows = _http(base, key, "homework?select=id,archived&id=like." + OWN_PREFIX + "*",
                         token=token)
        if st != 200 or not isinstance(rows, list):
            raise RuntimeError("list homework failed: HTTP %s" % st)
        return {r["id"]: r for r in rows}

    existing = list_rows()
    result = {"ok": False, "english": len(items), "pending": len(pending),
              "cloud_ok": 0, "cloud_total": len(want), "archived": 0}
    if want:
        status, _ = _http(base, key, "homework?on_conflict=id", list(want.values()), "POST", token,
                          prefer="resolution=merge-duplicates,return=minimal")
        if status not in (200, 201, 204):
            return dict(result, error_code="write_failed")

    stale = {rid for rid, old in existing.items() if rid not in want and not old.get("archived")}
    for rid in sorted(stale):
        _http(base, key, "homework?id=eq." + rid, {"archived": True}, "PATCH", token=token)

    confirmed = list_rows()
    result["cloud_ok"] = sum(rid in confirmed and confirmed[rid].get("archived") is False for rid in want)
    result["archived"] = sum(rid in confirmed and confirmed[rid].get("archived") is True for rid in stale)
    result["ok"] = result["cloud_ok"] == len(want) and result["archived"] == len(stale)
    if not result["ok"]:
        result["error_code"] = "verify_failed"
    return result


def _run(base, key, token, collect, runner):
    try:
        payload = collect()
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error_code": "collect_failed", "error_type": type(exc).__name__}
    else:
        try:
            result = _sync_homework(base, key, token, payload)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error_code": "write_failed", "error_type": type(exc).__name__}
    fields = ("ok", "pending", "cloud_ok", "cloud_total", "archived", "error_code")
    receipt = {field: result[field] for field in fields if field in result}
    receipt.update(at_ms=int(time.time() * 1000), runner=runner)
    row = {"id": RECEIPT_ID + ("-local" if runner == "local" else ""), "body": receipt}
    try:
        status, _ = _http(base, key, "site_assets?on_conflict=id", [row], "POST", token,
                          prefer="resolution=merge-duplicates,return=minimal")
        if status not in (200, 201, 204):
            return dict(result, ok=False, error_code="receipt_failed")
    except OSError:
        return dict(result, ok=False, error_code="receipt_failed")
    return result


def main_handler(event, context):
    import xgj_homework as xgj

    base = _env("CB_BASE")
    key = _env("CB_KEY")
    if not base or not key:
        return {"ok": False, "error_code": "missing_config"}
    try:
        token = _token(base, key)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error_code": "auth_failed", "error_type": type(exc).__name__}
    runner = "ecs-timer" if _env("CLASS_HEALTH_RUNNER") == "ecs-timer" else "cloudbase"
    with tempfile.TemporaryDirectory(prefix="xgj-") as directory:
        def collect():
            _setup_tmp(xgj, directory)
            return xgj.collect(dry_run=False)
        return _run(base, key, token, collect, runner)


if __name__ == "__main__":
    # 本机代理只补写学工记作业，不经过会同步其它来源的整批作业任务。
    if sys.argv[1:] != ["--local"]:
        raise SystemExit("usage: index.py --local")
    sys.path.insert(0, str(HERE.parents[3] / "briefdesk" / "scripts"))
    import diag_agent
    import xgj_homework as xgj

    cloud = diag_agent.Cloud()
    outcome = _run(cloud.base, cloud.key, cloud.ensure_token(), lambda: xgj.collect(dry_run=False), "local")
    print(json.dumps(outcome, ensure_ascii=False))
    raise SystemExit(0 if outcome["ok"] else 1)
