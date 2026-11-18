# -*- coding: utf-8 -*-
"""task-26：13/16 号楼电量「阶梯状」只读排查。

只读云端 power/power_history + 只读网关实时值；不写云端、不改前端。
输出：对照表（采样数/变化次数/最长相同段/网关 vs 云端/映射交叉验证）。

跑法：C:\\briefdesk\\venv\\Scripts\\python.exe -X utf8 "C:\\Users\\Ko_Li\\.openclaw\\workspace\\briefdesk-plan\\_check_power.py"
"""
import json
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, r"C:\briefdesk\scripts")
import sync_power_cloud as sp  # noqa: E402

CN = timezone(timedelta(hours=8))
TARGETS = ["1-13---324", "1-13---308", "1-16---305", "1-16---306"]
CONTROLS = ["4-23A---321", "4-23A---328", "4-23B---422"]
LABELS = {rv: label for label, building, room, rv in sp.ROOMS}


def iso(dt):
    return dt.astimezone(CN).isoformat()


def get_cloud():
    base, key = sp.cb_config()
    log = lambda m: None  # noqa: E731
    token = sp.get_token(base, key, log)
    return base, key, token


def fetch_history(base, key, token, rv, days):
    since = iso(datetime.now(CN) - timedelta(days=days))
    path = ("power_history?select=roomverify,quantity,unit,ts&roomverify=eq."
            + urllib.parse.quote(rv) + "&ts=gte." + urllib.parse.quote(since)
            + "&order=ts.asc&limit=5000")
    st, rows = sp.cb_request(base, key, path, token=token)
    if st != 200:
        return None, "HTTP %s %s" % (st, str(rows)[:160])
    return rows or [], None


def series_stats(rows):
    """采样序列统计：数量/变化次数/最长相同段/最大间隔。"""
    pts = []
    for r in rows or []:
        e = sp._epoch(r.get("ts"))
        try:
            q = round(float(r.get("quantity")), 2)
        except (TypeError, ValueError):
            continue
        if e is None:
            continue
        pts.append((e, q))
    pts.sort()
    out = {"n": len(pts), "changes": 0, "longest_same": 0, "longest_same_secs": 0,
           "max_gap_secs": 0, "first": None, "last": None, "values": sorted({q for _, q in pts})[:12],
           "range": None, "avg_gap_secs": None}
    if not pts:
        return out
    out["first"] = iso(datetime.fromtimestamp(pts[0][0], CN))
    out["last"] = iso(datetime.fromtimestamp(pts[-1][0], CN))
    out["range"] = [pts[0][1], pts[-1][1]]
    run_val, run_len, run_start = pts[0][1], 1, pts[0][0]
    gaps = []
    for i in range(1, len(pts)):
        gaps.append(pts[i][0] - pts[i - 1][0])
        if pts[i][1] == run_val:
            run_len += 1
            if run_len > out["longest_same"]:
                out["longest_same"] = run_len
                out["longest_same_secs"] = pts[i][0] - run_start
        else:
            out["changes"] += 1
            run_val, run_len, run_start = pts[i][1], 1, pts[i][0]
    out["longest_same"] = max(out["longest_same"], 1)
    if gaps:
        out["max_gap_secs"] = max(gaps)
        out["avg_gap_secs"] = round(sum(gaps) / len(gaps), 1)
    return out


def gateway_probe(rvs, interval=1.6):
    out = {}
    for i, rv in enumerate(rvs):
        if i:
            time.sleep(interval)
        try:
            q, unit = sp.gateway_room(rv)
            out[rv] = {"ok": True, "quantity": round(q, 2), "unit": unit}
        except Exception as e:  # noqa: BLE001
            out[rv] = {"ok": False, "error": str(e)[:120]}
    return out


def mapping_probe():
    """映射交叉验证：同楼不同房间/不同 area 前缀，看网关返回是否合理/可区分。"""
    probes = []
    # 13 号楼其它房间
    for rv in ["1-13---301", "1-13---302", "1-13---325"]:
        probes.append(rv)
    # 16 号楼其它房间
    for rv in ["1-16---301", "1-16---307"]:
        probes.append(rv)
    # 换 area 前缀探测：如果 13 号楼实际属于别的 area，用 2/3 前缀也能返回
    for prefix in ("2", "3", "5", "6"):
        probes.append("%s-13---324" % prefix)
    for prefix in ("2", "3"):
        probes.append("%s-16---305" % prefix)
    res = gateway_probe(probes, interval=1.6)
    return res


def main():
    base, key, token = get_cloud()
    print("== cloud init ok ==")
    st, power_rows = sp.cb_request(base, key, "power?select=*", token=token)
    print("power rows:", st, len(power_rows) if isinstance(power_rows, list) else str(power_rows)[:200])
    cloud = {r.get("roomverify"): r for r in (power_rows or []) if isinstance(r, dict)}

    out = {"generatedAt": iso(datetime.now(CN)), "cloud": {}, "history24": {}, "history30": {},
           "gateway": {}, "mapping": {}, "cloud_current_mismatch": []}
    for rv in TARGETS + CONTROLS:
        row = cloud.get(rv)
        out["cloud"][rv] = {"label": LABELS.get(rv), "quantity": (row or {}).get("quantity"),
                            "unit": (row or {}).get("unit"), "updated_at": (row or {}).get("updated_at")}
        rows24, err24 = fetch_history(base, key, token, rv, 1)
        rows30, err30 = fetch_history(base, key, token, rv, 30)
        out["history24"][rv] = {"error": err24, **series_stats(rows24)}
        out["history30"][rv] = {"error": err30, **series_stats(rows30)}

    gw = gateway_probe(TARGETS + CONTROLS, interval=1.6)
    out["gateway"] = gw
    for rv in TARGETS + CONTROLS:
        g = gw.get(rv) or {}
        c = cloud.get(rv) or {}
        cq = c.get("quantity")
        try:
            cq = round(float(cq), 2) if cq is not None else None
        except (TypeError, ValueError):
            cq = None
        if g.get("ok") and cq is not None and abs(float(g["quantity"]) - float(cq)) > 0.01:
            out["cloud_current_mismatch"].append({"roomverify": rv, "cloud": cq, "gateway": g["quantity"]})

    out["mapping"] = mapping_probe()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    # 保存到文件便于复盘（不含隐私）
    p = Path(r"C:\briefdesk\data\_power_diag.json")
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
