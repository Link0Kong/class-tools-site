# -*- coding: utf-8 -*-
"""只读：阿里云 DNS 操作日志 DescribeDomainLogs（确认暂停解析的时间与操作类型）。"""
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


from aliyunsdkcore.client import AcsClient  # noqa: E402
from aliyunsdkcore.request import CommonRequest  # noqa: E402

cli = AcsClient(AK, SK, "cn-hangzhou")


def call(action, params):
    r = CommonRequest()
    r.set_domain("alidns.aliyuncs.com")
    r.set_version("2015-01-09")
    r.set_action_name(action)
    r.set_method("POST")
    for k, v in params.items():
        r.add_query_param(k, v)
    return json.loads(cli.do_action_with_exception(r).decode("utf-8"))


print("=" * 70)
print("阿里云 DNS 操作日志只读查询 @", datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
print("=" * 70)

attempts = [
    ("DescribeDomainLogs", {"DomainName": "furina.fun", "PageSize": "100", "PageNumber": "1"}),
    ("DescribeDomainLogs", {"PageSize": "100", "PageNumber": "1"}),
    ("DescribeChangeLogs", {"PageSize": "100", "PageNumber": "1"}),
]
for action, params in attempts:
    try:
        res = call(action, params)
        p("[%s %s] ->" % (action, params), json.dumps(res, ensure_ascii=False)[:6000])
    except Exception as e:
        p("[%s %s] 失败: %s: %s" % (action, params, type(e).__name__, e))
print("\n[DONE]")
