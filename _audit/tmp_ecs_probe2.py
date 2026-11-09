# -*- coding: utf-8 -*-
"""只读审计补充：全地域 ECS 实例盘点 + 轻量应用服务器(SWAS)盘点 + 安全组规则。

只用 Describe*/List* 只读接口，不调用任何写接口。
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


def call(domain, version, action, params):
    r = CommonRequest()
    r.set_domain(domain)
    r.set_version(version)
    r.set_action_name(action)
    r.set_method("POST")
    for k, v in params.items():
        r.add_query_param(k, v)
    return json.loads(cli.do_action_with_exception(r).decode("utf-8"))


print("=" * 70)
print("阿里云资源补充只读盘点 @", now())
print("=" * 70)

# 1) 全地域 ECS 实例
p("\n### 1. 全地域 ECS 实例盘点")
try:
    regions = call("ecs.aliyuncs.com", "2014-05-26", "DescribeRegions", {}).get("Regions", {}).get("Region", [])
    ids = [r.get("RegionId") for r in regions]
    p("DescribeRegions 区域数 =", len(ids))
except Exception as e:
    ids = ["cn-hangzhou"]
    p("[warn] DescribeRegions:", type(e).__name__, e)
all_inst = []
for rid in ids:
    try:
        res = call("ecs.aliyuncs.com", "2014-05-26", "DescribeInstances",
                   {"RegionId": rid, "PageSize": "100", "PageNumber": "1"})
        insts = res.get("Instances", {}).get("Instance", [])
        if insts:
            p("  [%s] TotalCount=%s 实例:" % (rid, res.get("TotalCount")))
        for it in insts:
            pub = (it.get("PublicIpAddress", {}) or {}).get("IpAddress", [])
            eip = (it.get("EipAddress", {}) or {}).get("IpAddress", "")
            inner = (it.get("VpcAttributes", {}) or {}).get("PrivateIpAddress", {}).get("IpAddress", [])
            rec = {"region": rid, "id": it.get("InstanceId"), "name": it.get("InstanceName"),
                   "status": it.get("Status"), "type": it.get("InstanceType"),
                   "public": pub, "eip": eip, "private": inner,
                   "created": it.get("CreationTime"), "expired": it.get("ExpiredTime")}
            all_inst.append(rec)
            p("    ", json.dumps(rec, ensure_ascii=False))
    except Exception as e:
        p("  [%s] ERROR %s: %s" % (rid, type(e).__name__, e))
p("  >>> 全账号可见 ECS 实例总数 =", len(all_inst))
for rec in all_inst:
    p("      -", rec["region"], rec["id"], rec["name"], rec["status"], rec["public"], rec["private"])

# 2) 轻量应用服务器 SWAS
p("\n### 2. 轻量应用服务器 SWAS 盘点（若权限允许）")
for action, params in (
    ("ListInstances", {"RegionId": "cn-hangzhou"}),
    ("DescribeInstances", {"RegionId": "cn-hangzhou"}),
):
    for domain in ("swas.cn-hangzhou.aliyuncs.com", "swas.aliyuncs.com"):
        try:
            res = call(domain, "2020-06-01", action, params)
            p("  [%s @ %s] -> %s" % (action, domain, json.dumps(res, ensure_ascii=False)[:2500]))
            break
        except Exception as e:
            p("  [%s @ %s] 失败: %s: %s" % (action, domain, type(e).__name__, e))

# 3) 安全组规则（class_tool 实例）
p("\n### 3. 安全组 sg-bp1cvttk00sb37dauyne 规则 (DescribeSecurityGroupAttribute)")
try:
    res = call("ecs.aliyuncs.com", "2014-05-26", "DescribeSecurityGroupAttribute",
               {"RegionId": "cn-hangzhou", "SecurityGroupId": "sg-bp1cvttk00sb37dauyne",
                "Direction": "ingress"})
    perms = res.get("Permissions", {}).get("Permission", [])
    p("  ingress 规则数 =", len(perms))
    for x in perms:
        p("   ", json.dumps({k: x.get(k) for k in (
            "IpProtocol", "PortRange", "SourceCidrIp", "SourceGroupId", "Description",
            "Policy", "Priority", "Direction", "CreateTime")}, ensure_ascii=False))
except Exception as e:
    p("  [ERROR]", type(e).__name__, e)

print("\n[DONE]", now())
