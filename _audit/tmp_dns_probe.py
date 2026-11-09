# -*- coding: utf-8 -*-
"""只读探测：阿里云 DNS furina.fun 全量解析记录 + 域名元信息。

- 凭据：复用 deploy/sync_tools.py 的 load_creds()（环境变量或 deploy/creds.env），只读 Describe* API。
- 绝不打印 AK/SK：所有输出经 scrub() 过滤。
- 不做任何 Add/Delete/Update 操作。
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(WEB, "deploy"))
import sync_tools  # noqa: E402

try:
    AK, SK = sync_tools.load_creds()
except Exception as e:
    print("[FATAL] 无法加载凭据:", type(e).__name__, e)
    raise SystemExit(1)

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


def dns(action, params):
    r = CommonRequest()
    r.set_domain("alidns.aliyuncs.com")
    r.set_version("2015-01-09")
    r.set_action_name(action)
    r.set_method("POST")
    for k, v in params.items():
        r.add_query_param(k, v)
    return json.loads(cli.do_action_with_exception(r).decode("utf-8"))


print("=" * 70)
print("阿里云 DNS 只读探测  @", now())
print("=" * 70)

# 1) 全量解析记录
try:
    allrec = []
    page = 1
    while True:
        res = dns("DescribeDomainRecords", {
            "DomainName": "furina.fun", "PageSize": "500", "PageNumber": str(page)})
        recs = res.get("DomainRecords", {}).get("Record", [])
        allrec.extend(recs)
        total = int(res.get("TotalCount", len(allrec)))
        p("[INFO] DescribeDomainRecords page=%d 返回 %d 条 / TotalCount=%s" % (page, len(recs), total))
        if len(allrec) >= total or not recs:
            break
        page += 1
    p("[RESULT] furina.fun 解析记录总数 =", len(allrec))
    keys = ["RR", "Type", "Value", "TTL", "Status", "Locked", "Line", "RecordId", "Remark"]
    for r in sorted(allrec, key=lambda x: (x.get("RR", ""), x.get("Type", ""))):
        p("  REC " + " | ".join("%s=%s" % (k, r.get(k)) for k in keys if k in r))
    # 重点记录单独列出
    focus = ["tool", "_dnsauth.tool", "_acme-challenge.tool", "me", "start", "mc", "@", "www", "_dnsauth", "_dnsauth.me"]
    p("[FOCUS] 重点主机记录存在性:")
    for f in focus:
        hits = [r for r in allrec if r.get("RR") == f]
        if not hits:
            p("  -", f, "-> 不存在（DescribeDomainRecords 无此 RR）")
        for h in hits:
            p("  -", f, "->", h.get("Type"), h.get("Value"), "Status=", h.get("Status"), "TTL=", h.get("TTL"))
except Exception as e:
    p("[ERROR] DescribeDomainRecords:", type(e).__name__, e)

# 2) 域名元信息（只读；逐个尝试，失败只记录错误）
for action in ("DescribeDomainInfo", "DescribeDomainNs", "DescribeDomains"):
    try:
        params = {"DomainName": "furina.fun"} if action != "DescribeDomains" else {"PageSize": "100", "PageNumber": "1"}
        res = dns(action, params)
        p("[RESULT]", action, "->", json.dumps(res, ensure_ascii=False))
    except Exception as e:
        p("[INFO]", action, "不可用/报错:", type(e).__name__, e)

# 3) 解析量统计（只读，用于判断域名是否仍在被查询）
for action, params in (
    ("DescribeDomainStatistics", {"DomainName": "furina.fun", "StartDate": "2026-11-03", "EndDate": "2026-11-09"}),
):
    try:
        res = dns(action, params)
        p("[RESULT]", action, "->", json.dumps(res, ensure_ascii=False)[:3000])
    except Exception as e:
        p("[INFO]", action, "不可用/报错:", type(e).__name__, e)

print("\n[DONE]", now())
