# -*- coding: utf-8 -*-
"""CloudBase 云函数：班级小管家 英语作业采集（XGJ 云端版）。

迁移目标（task-29）：本机 `run_hw_auto.py` 中的 xgj 步骤每 2h 跑
`xgj_homework.py --collect --merge`，随后 `sync_homework_cloud.py` 把
`data/auto-homework.json` 全量同步到 public.homework（含归档过期行）。
云端函数**只负责英语作业**：
    * 复用 xgj_homework.py 的 API/签名/token 逻辑（部署时复制到本目录）；
    * token 由环境变量 XGJ_TOKEN_JSON 提供（内容 = 本机 secrets/xjg-token.json 全文）；
    * 只 upsert / 归档 `auto_hw_xgj_en_*` 前缀行，绝不碰其它来源（math/doc/sizheng…）；
    * 不依赖电脑开机（云函数 + 定时触发器），幂等：内容不变时 PATCH 同一行。

环境变量（云函数配置里设置，不写进代码/仓库）：
    CB_BASE          PostgREST 基地址
    CB_KEY           匿名 publishable key
    CLASS_ADMIN_SID / CLASS_ADMIN_NAME  管理员 token 换取（或 CLASS_TOKEN）
    XGJ_TOKEN_JSON   小管家 token 文件 JSON 全文（含 token/member_id/exp…）

返回：{"ok": bool, "english": n, "pending": n, "cloud_ok": n, "archived": n, "error": ...}
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import xgj_homework as xgj  # noqa: E402  （部署时复制到本目录，保持与 scripts/ 同源）

PREFIX = "auto_hw_"
OWN_PREFIX = PREFIX + "xgj_en_"


def _env(name, default=""):
    v = os.environ.get(name)
    return v if v else default


def _http(base, key, path, body=None, method="GET", token=None, timeout=60):
    import urllib.error
    import urllib.request
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if token:
        headers["X-Device-Id"] = token
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


def _setup_tmp():
    tmp = Path("/tmp/xgj")
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


def main_handler(event, context):
    base = _env("CB_BASE")
    key = _env("CB_KEY")
    if not base or not key:
        return {"ok": False, "error": "CB_BASE/CB_KEY 未配置"}
    try:
        _setup_tmp()
        payload = xgj.collect(dry_run=False)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": ("xgj collect: %s" % str(e))[:300]}
    items = payload.get("items") or []
    pending = [r for r in items if r.get("status") == "未完成"]
    want = {}
    for r in items:
        if r.get("status") != "未完成":
            continue
        rid = PREFIX + str(r.get("key") or "")
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
            "ts": int(r.get("ts") or 0) or int(__import__("time").time() * 1000),
        }
    try:
        token = _token(base, key)
        st, rows = _http(base, key, "homework?select=id,archived&id=like." + OWN_PREFIX + "*",
                         token=token)
        if st != 200:
            raise RuntimeError("list homework failed: HTTP %s %s" % (st, str(rows)[:160]))
        existing = {r["id"]: r for r in (rows or [])}
        ok = 0
        for rid, row in want.items():
            if rid in existing:
                st, out = _http(base, key, "homework?id=eq." + rid, row, "PATCH", token=token)
            else:
                st, out = _http(base, key, "homework", [row], "POST", token=token)
            if st in (200, 201, 204):
                ok += 1
        archived = 0
        for rid, old in existing.items():
            if rid not in want and not old.get("archived"):
                st, _ = _http(base, key, "homework?id=eq." + rid, {"archived": True}, "PATCH", token=token)
                if st in (200, 204):
                    archived += 1
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "english": len(items), "pending": len(pending),
                "error": ("cloud write: %s" % str(e))[:300]}
    return {"ok": True, "english": len(items), "pending": len(pending),
            "cloud_ok": ok, "cloud_total": len(want), "archived": archived,
            "first": [str(r.get("content") or "")[:40] for r in list(want.values())[:3]]}
