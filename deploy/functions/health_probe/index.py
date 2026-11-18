# -*- coding: utf-8 -*-
"""CloudBase 云函数：依赖服务健康探测（18 行版 / 2026-11-07 DNS 暂停改造）。

云端负责 8 行（CLOUD_OWNED_IDS）:
    cloudbase / site_static / site_tls / dns_domain / tt_cloud /
    cloud_power_sync / cloud_xgj_sync / cloud_health_probe
本机 `health_beat.py` 只写其余 local 10 行（避免双写冲突）。
实现复用 `health_beat.py` 的 collect_cloud()/detect_*（部署时复制同源脚本到本目录）。

暂停语义（site_config 行 id='web'）：collect_cloud 内部读 value.paused；
paused=true 时 site_static/site_tls 直接 warn「网页已按备案安排暂停」并跳过探测，
dns_domain 按「已暂停（符合预期）/仍在解析」规则判定。

环境变量（CloudBase 云函数配置，不写进代码/仓库）：
    CB_BASE / CB_KEY                    PostgREST 基地址 + publishable key
    CLASS_ADMIN_SID / CLASS_ADMIN_NAME  管理员 token（rpc/class_verify；或 CLASS_TOKEN）

返回：{"ok": bool, "rows": 8, "patched": n, "posted": n, "ms": n, "rows_detail": [...]}
"""
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import health_beat as hb  # noqa: E402  （部署时复制自 scripts/health_beat.py）


def _env(name, default=""):
    v = os.environ.get(name)
    return v if v else default


def _token(base, key):
    tok = _env("CLASS_TOKEN")
    if tok:
        return tok
    status, out, _ms = hb._cb_request(
        base, key, "rpc/class_verify",
        {"p_sid": _env("CLASS_ADMIN_SID"), "p_name": _env("CLASS_ADMIN_NAME")}, "POST")
    if status != 200 or not isinstance(out, dict) or not out.get("token"):
        raise RuntimeError("class_verify failed: HTTP %s %s" % (status, str(out)[:160]))
    return out["token"]


def _write(base, key, token, rows):
    """逐行写入 service_health（存在 PATCH/不存在 POST）。返回 (patched, posted)。"""
    status, existing, _ms = hb._cb_request(base, key, "service_health?select=id", token=token)
    if status != 200 or not isinstance(existing, list):
        raise RuntimeError("list service_health failed: HTTP %s" % status)
    have = {r.get("id") for r in existing if isinstance(r, dict)}
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    patched = posted = 0
    for row in rows:
        rid = str(row.get("id") or "")
        if not rid:
            continue
        body = dict(row)
        body["updated_at"] = updated_at
        if rid in have:
            st, _out, _ms = hb._cb_request(
                base, key, "service_health?id=eq." + urllib.parse.quote(rid),
                body, "PATCH", token)
            if st in (200, 204):
                patched += 1
        else:
            st, _out, _ms = hb._cb_request(
                base, key, "service_health", [body], "POST", token)
            if st in (200, 201, 204):
                posted += 1
    return patched, posted


def _status_list(rows):
    return [{"id": r.get("id"), "status": r.get("status"),
             "detail": str(r.get("detail") or "")[:60]} for r in rows]


def main_handler(event, context):
    base = _env("CB_BASE")
    key = _env("CB_KEY")
    if not base or not key:
        return {"ok": False, "error": "CB_BASE/CB_KEY 未配置"}
    if not _env("CLASS_TOKEN") and not (_env("CLASS_ADMIN_SID") and _env("CLASS_ADMIN_NAME")):
        return {"ok": False, "error": "CLASS_TOKEN 或 CLASS_ADMIN_SID/CLASS_ADMIN_NAME 未配置"}

    t0 = time.time()
    try:
        token = _token(base, key)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}

    # collect_cloud 返回 8 行：前 7 行是本轮探测结果，最后一行 cloud_health_probe 为占位。
    try:
        rows = hb.collect_cloud(base, key, token)
    except Exception as e:  # noqa: BLE001  （collect_cloud 内部已逐项兜底，这里只防意外）
        return {"ok": False, "error": ("collect_cloud: %s" % str(e))[:300]}

    head, self_row = rows[:-1], rows[-1]
    try:
        patched, posted = _write(base, key, token, head)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": ("write: %s" % str(e))[:300],
                "rows_detail": _status_list(rows)}

    # 云端巡检自身行：用本轮实际写入耗时/行数重建后写入（该行若写入失败，前端 15 分钟后
    # 会把其它 cloud 行降级「巡检未更新」，属预期降级语义）。
    ms = int((time.time() - t0) * 1000)
    final_self = hb.detect_cloud_health_probe(len(rows), patched, posted, ms)
    try:
        p2, s2 = _write(base, key, token, [final_self])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": ("write self: %s" % str(e))[:300],
                "patched": patched, "posted": posted, "ms": ms,
                "rows_detail": _status_list(head)}
    rows[-1] = final_self

    return {"ok": True, "rows": len(rows), "patched": patched + p2,
            "posted": posted + s2, "ms": ms,
            "rows_detail": _status_list(rows)}
