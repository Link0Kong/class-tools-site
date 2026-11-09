# -*- coding: utf-8 -*-
"""ECS 历史负载只读查询（ECS API DescribeInstanceMonitorData）。不打印凭据。"""
import io, sys, json, datetime
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, r"C:\Users\Ko_Li\.openclaw\workspace\ecs_handoff")
from ecs_ctl import client, call

c = client()
iid = "i-bp1ibr9hs7ewepmm1ugw"
now = datetime.datetime.now(datetime.timezone.utc)
start = now - datetime.timedelta(days=7)
fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
try:
    d = call(c, "DescribeInstanceMonitorData", {
        "InstanceId": iid, "StartTime": fmt(start), "EndTime": fmt(now), "Period": "3600"})
    items = (d.get("MonitorData") or {}).get("InstanceMonitorData") or []
    print("datapoints:", len(items))
    if items:
        cpu = [float(x.get("CPU", 0)) for x in items]
        out = [float(x.get("InternetOutRate", 0)) for x in items]  # Kbps? docs say Kbps
        inn = [float(x.get("InternetInRate", 0)) for x in items]
        for name, vals in (("CPU%", cpu), ("InternetOutRate(Kbps?)", out), ("InternetInRate(Kbps?)", inn)):
            vals2 = sorted(vals)
            print("%-22s avg=%.3f p95=%.3f max=%.3f" % (name, sum(vals2)/len(vals2), vals2[int(len(vals2)*0.95)-1], vals2[-1]))
        print("sample last:", json.dumps(items[-1], ensure_ascii=False))
except Exception as e:
    print("ERR", type(e).__name__, str(e)[:300])
