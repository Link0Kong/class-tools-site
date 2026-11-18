# -*- coding: utf-8 -*-
"""CloudBase 云函数：宿舍电量同步（ClassPowerSync 云端版）。

迁移目标（task-29）：本机 Windows 计划任务 `ClassPowerSync` 每小时跑
`scripts/sync_power_cloud.py`（完美校园网关 → public.power / power_history）。
本函数**复用同一脚本代码**（部署时由 cloudbase/deploy.py 从 scripts/ 复制到本目录），
仅把「取 CloudBase 地址/匿名 key、管理员 token、日志落盘位置」改为环境变量/临时目录。

环境变量（在 CloudBase 云函数配置里设置，不写进代码/仓库）：
    CB_BASE          PostgREST 基地址（网页 index.html 的 var CB）
    CB_KEY           匿名 publishable key（网页 index.html 的 var CBK）
    CLASS_ADMIN_SID  管理员学号（用于 rpc/class_verify 换 token；也可改用 CLASS_TOKEN 固定 token）
    CLASS_ADMIN_NAME 管理员姓名（同上）
    CLASS_TOKEN      （可选）直接给定管理员 token；设置后跳过 class_verify

返回：{"ok": bool, "rc": int, "tail": [日志尾部行]}
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sync_power_cloud as sp  # noqa: E402  （部署时复制到本目录，保持与 scripts/ 同源）


def _env(name, default=""):
    v = os.environ.get(name)
    return v if v else default


def _get_token(base, key, log, force=False):
    tok = _env("CLASS_TOKEN")
    if tok:
        return tok
    st, out = sp.cb_request(
        base, key, "rpc/class_verify",
        {"p_sid": _env("CLASS_ADMIN_SID"), "p_name": _env("CLASS_ADMIN_NAME")}, "POST")
    if st != 200 or not isinstance(out, dict) or not out.get("token"):
        raise RuntimeError("class_verify failed: HTTP %s %s" % (st, str(out)[:160]))
    log("cloud: token refreshed (class_verify)")
    return out["token"]


def main_handler(event, context):
    base = _env("CB_BASE")
    key = _env("CB_KEY")
    if not base or not key:
        return {"ok": False, "error": "CB_BASE/CB_KEY 未配置"}
    if not _env("CLASS_TOKEN") and not (_env("CLASS_ADMIN_SID") and _env("CLASS_ADMIN_NAME")):
        return {"ok": False, "error": "CLASS_TOKEN 或 CLASS_ADMIN_SID/CLASS_ADMIN_NAME 未配置"}
    sp.cb_config = lambda: (base, key)  # noqa: E731
    sp.get_token = _get_token
    sp.LOG_FILE = Path("/tmp/power-sync.log")
    try:
        rc = sp.main(["--no-sleep"])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}
    try:
        tail = sp.LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]
    except OSError:
        tail = []
    return {"ok": rc == 0, "rc": rc, "tail": tail}
