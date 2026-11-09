# -*- coding: utf-8 -*-
"""只读 ECS 规格补充：磁盘、带宽、云监控指标。不打印任何凭据。"""
import io, os, sys, json, datetime
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, r"C:\Users\Ko_Li\.openclaw\workspace\ecs_handoff")
from ecs_ctl import client, call

c = client()
iid = "i-bp1ibr9hs7ewepmm1ugw"
reg = "cn-hangzhou"

print("### DescribeDisks")
try:
    d = call(c, "DescribeDisks", {"RegionId": reg, "InstanceId": iid})
    for disk in (d.get("Disks") or {}).get("Disk") or []:
        print(json.dumps({k: disk.get(k) for k in ("DiskId", "Size", "Category", "Type", "Status", "Device", "DeleteWithInstance")}, ensure_ascii=False))
except Exception as e:
    print("ERR", type(e).__name__, e)

print("### DescribeInstanceAttribute (bandwidth)")
try:
    d = call(c, "DescribeInstanceAttribute", {"InstanceId": iid})
    print(json.dumps({k: d.get(k) for k in ("InstanceId", "InstanceName", "InternetMaxBandwidthIn", "InternetMaxBandwidthOut", "InternetChargeType", "InstanceNetworkType", "CreditSpecification")}, ensure_ascii=False))
except Exception as e:
    print("ERR", type(e).__name__, e)

print("### CloudMonitor 最近 7 天（实例级，1h 粒度）")
try:
    from aliyunsdkcore.request import CommonRequest
    now = datetime.datetime.utcnow()
    start = now - datetime.timedelta(days=7)
    fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
    for metric in ("CPUUtilization", "InternetOutRate", "InternetInRate", "DiskReadBPS", "DiskWriteBPS", "MemoryUtilization"):
        req = CommonRequest(); req.set_domain("cms.aliyuncs.com"); req.set_version("2019-01-01")
        req.set_action_name("DescribeMetricList"); req.set_method("POST")
        for k, v in {"Namespace": "acs_ecs_dashboard", "MetricName": metric, "Period": "3600",
                     "StartTime": fmt(start), "EndTime": fmt(now),
                     "Dimensions": json.dumps([{"instanceId": iid}])}.items():
            req.add_query_param(k, v)
        try:
            raw = c.do_action_with_exception(req).decode("utf-8")
            data = json.loads(raw)
            pts = json.loads(data.get("Datapoints") or "[]")
            vals = []
            for p in pts:
                v = p.get("Average", p.get("Value"))
                if isinstance(v, (int, float)):
                    vals.append(float(v))
            if vals:
                vals2 = sorted(vals)
                print("%-20s n=%d avg=%.3f p95=%.3f max=%.3f" % (metric, len(vals2), sum(vals2) / len(vals2), vals2[int(len(vals2) * 0.95) - 1], vals2[-1]))
            else:
                print("%-20s no datapoints (%s)" % (metric, (data.get("Message") or data.get("Code") or "")[:80]))
        except Exception as e:
            print("%-20s ERR %s %s" % (metric, type(e).__name__, str(e)[:120]))
except Exception as e:
    print("CMS ERR", type(e).__name__, e)
