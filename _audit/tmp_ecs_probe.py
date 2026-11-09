# -*- coding: utf-8 -*-
"""只读审计：阿里云 ECS 实例状态 + DNS 解析量统计（全部 Describe* 只读 API）。

- 凭据：deploy/sync_tools.py 的 load_creds()；绝不打印 AK/SK。
- 只读：不调用任何 Start/Stop/Run/Delete/Reboot/Reboot 类接口。
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(WEB, "deploy"))
import sync_tools  # noqa: E402

AK, SK = sync_tools.load_creds()
_SECRETS = [s for s in (AK, SK) if s]


def scrub(s):
    s = str(s)
    for x in _SECRETS:
        s = s.replace(x, "***REDACTED***")
    return s


def p(*parts):
    print(scrub(" ".join(str(x) for x in parts)))


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


from aliyunsdkcore.client import AcsClient  # noqa: E402
from aliyunsdkcore.request import CommonRequest  # noqa: E402

cli = AcsClient(AK, SK, "cn-hangzhou")


def call(domain, version, action, params, method="POST"):
    r = CommonRequest()
    r.set_domain(domain)
    r.set_version(version)
    r.set_action_name(action)
    r.set_method(method)
    for k, v in params.items():
        r.add_query_param(k, v)
    return json.loads(cli.do_action_with_exception(r).decode("utf-8"))


print("=" * 70)
print("阿里云 ECS / DNS 统计只读审计 @", now())
print("=" * 70)

# ---------- ECS 实例列表（cn-hangzhou） ----------
p("\n### ECS DescribeInstances (RegionId=cn-hangzhou)")
try:
    res = call("ecs.aliyuncs.com", "2014-05-26", "DescribeInstances",
               {"RegionId": "cn-hangzhou", "PageSize": "100", "PageNumber": "1"})
    insts = res.get("Instances", {}).get("Instance", [])
    p("TotalCount =", res.get("TotalCount"), " 本页实例数 =", len(insts))
    for it in insts:
        pub = (it.get("PublicIpAddress", {}) or {}).get("IpAddress", [])
        eip = (it.get("EipAddress", {}) or {}).get("IpAddress", "")
        inner = (it.get("VpcAttributes", {}) or {}).get("PrivateIpAddress", {}).get("IpAddress", [])
        p("  INSTANCE id=%s name=%s status=%s type=%s zone=%s" % (
            it.get("InstanceId"), it.get("InstanceName"), it.get("Status"),
            it.get("InstanceType"), it.get("ZoneId")))
        p("    publicIp=%s eip=%s privateIp=%s created=%s expired=%s charge=%s os=%s" % (
            pub, eip, inner, it.get("CreationTime"), it.get("ExpiredTime"),
            it.get("InstanceChargeType"), it.get("OSName")))
        p("    securityGroupIds=%s" % (it.get("SecurityGroupIds", {}) or {}).get("SecurityGroupId", []))
except Exception as e:
    p("  [ERROR] DescribeInstances:", type(e).__name__, e)

# ---------- 指定实例状态 ----------
p("\n### ECS DescribeInstanceStatus（已知实例 i-bp1ibr9hs7ewepmm1ugw）")
try:
    res = call("ecs.aliyuncs.com", "2014-05-26", "DescribeInstanceStatus",
               {"RegionId": "cn-hangzhou", "InstanceId.1": "i-bp1ibr9hs7ewepmm1ugw"})
    p("  ->", json.dumps(res, ensure_ascii=False)[:4000])
except Exception as e:
    p("  [ERROR] DescribeInstanceStatus:", type(e).__name__, e)

# ---------- 尝试按公网 IP 查实例（ipv4） ----------
p("\n### ECS DescribeInstances 按公网 IP 过滤（若 API 支持）")
for ip in ("121.196.47.2", "120.27.217.236", "115.29.166.27"):
    try:
        res = call("ecs.aliyuncs.com", "2014-05-26", "DescribeInstances",
                   {"RegionId": "cn-hangzhou", "PageSize": "100", "PageNumber": "1",
                    "PublicIpAddresses": ip})
        insts = res.get("Instances", {}).get("Instance", [])
        p("  %s -> %d 条: %s" % (ip, len(insts), [i.get("InstanceId") for i in insts]))
    except Exception as e:
        p("  %s -> [ERROR] %s: %s" % (ip, type(e).__name__, e))

# ---------- DNS 解析量统计（按天汇总） ----------
p("\n### DNS DescribeDomainStatistics furina.fun（2026-11-03 ~ 2026-11-09）")
try:
    res = call("alidns.aliyuncs.com", "2015-01-09", "DescribeDomainStatistics",
               {"DomainName": "furina.fun", "StartDate": "2026-11-03", "EndDate": "2026-11-09"})
    stats = res.get("Statistics", {}).get("Statistic", [])
    p("  数据点 =", len(stats))
    byday = {}
    for s in stats:
        ts = int(s.get("Timestamp", 0)) / 1000.0
        dt = datetime.datetime.fromtimestamp(ts).astimezone()
        day = dt.strftime("%Y-%m-%d")
        byday.setdefault(day, {"hours": 0, "count": 0, "max": 0})
        byday[day]["hours"] += 1
        byday[day]["count"] += int(s.get("Count", 0))
        byday[day]["max"] = max(byday[day]["max"], int(s.get("Count", 0)))
    for d in sorted(byday):
        p("  %s 点数=%2d 总查询=%4d 单点最大=%3d" % (
            d, byday[d]["hours"], byday[d]["count"], byday[d]["max"]))
except Exception as e:
    p("  [ERROR] DescribeDomainStatistics:", type(e).__name__, e)

# ---------- 域名解析统计汇总（尝试只读汇总接口） ----------
for action, params in (
    ("DescribeDomainStatisticsSummary", {"DomainName": "furina.fun", "StartDate": "2026-11-03", "EndDate": "2026-11-09"}),
    ("DescribeDomainResolveStatisticsSummary", {"DomainName": "furina.fun", "StartDate": "2026-11-03", "EndDate": "2026-11-09"}),
):
    try:
        res = call("alidns.aliyuncs.com", "2015-01-09", action, params)
        p("  [%s] ->" % action, json.dumps(res, ensure_ascii=False)[:1500])
    except Exception as e:
        p("  [%s] 不可用: %s: %s" % (action, type(e).__name__, e))

print("\n[DONE]", now())
