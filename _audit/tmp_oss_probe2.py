# -*- coding: utf-8 -*-
"""只读补充探测：OSS ACL 值、robots.txt、证书剩余天数、日志 bucket 按日统计。"""
import datetime
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(WEB, "deploy"))
import sync_tools  # noqa: E402

AK, SK = sync_tools.load_creds()
_SECRETS = [s for s in (AK, SK) if s]
import oss2  # noqa: E402


def scrub(s):
    s = str(s)
    for x in _SECRETS:
        s = s.replace(x, "***REDACTED***")
    return s


def p(*parts):
    print(scrub(" ".join(str(x) for x in parts)))


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def lts(epoch):
    try:
        return datetime.datetime.fromtimestamp(int(epoch)).astimezone().isoformat(timespec="seconds")
    except Exception:
        return str(epoch)


EP = "https://%s.aliyuncs.com" % sync_tools.REGION
auth = oss2.Auth(AK, SK)

print("=" * 70)
print("OSS 补充只读探测  @", now())
print("=" * 70)

b = oss2.Bucket(auth, EP, sync_tools.BUCKET)
try:
    acl = b.get_bucket_acl()
    p("tool-furina-fun ACL =", getattr(acl, "acl", None), "| status=", getattr(acl, "status", None))
except Exception as e:
    p("[ERROR] acl:", type(e).__name__, e)

try:
    cn = b.list_bucket_cname()
    for c in getattr(cn, "cname", []) or []:
        cert = getattr(c, "certificate", None)
        if cert and cert.valid_end_date:
            end = datetime.datetime.strptime(cert.valid_end_date, "%b %d %H:%M:%S %Y GMT").replace(
                tzinfo=datetime.timezone.utc)
            delta = end - datetime.datetime.now(datetime.timezone.utc)
            p("证书 valid_end=%s  →  剩余 %.2f 天（%.1f 小时）" % (
                end.isoformat(), delta.total_seconds() / 86400.0, delta.total_seconds() / 3600.0))
            p("证书是否已过期 =", delta.total_seconds() <= 0)
except Exception as e:
    p("[ERROR] cert:", type(e).__name__, e)

for key in ("robots.txt", "apple-touch-icon.png", "favicon.ico"):
    try:
        data = b.get_object(key).read()
        p("对象 %s 内容（%d B, sha256=%s）:" % (key, len(data), hashlib.sha256(data).hexdigest()))
        if key.endswith(".txt"):
            p("  >>>", data.decode("utf-8", "replace").replace("\n", "\\n"))
    except Exception as e:
        p("[ERROR] get", key, type(e).__name__, e)

print("\n--- 日志 bucket 按日统计 ---")
lb = oss2.Bucket(auth, EP, "furina-site-logs")
day = {}
objs = []
token = ""
while True:
    res = lb.list_objects_v2(prefix="", continuation_token=token, max_keys=1000)
    for o in res.object_list:
        d = {
            "key": o.key, "size": o.size, "lm": lts(o.last_modified),
            "lm_epoch": int(o.last_modified),
            "prefix": o.key.split("/")[0] + "/" if "/" in o.key else "(root)",
        }
        # 日志对象名里含 YYYY-MM-DD
        import re
        m = re.search(r"(\d{4}-\d{2}-\d{2})", o.key)
        o2 = dict(d)
        o2["day"] = m.group(1) if m else "?"
        objs.append(o2)
    if not res.is_truncated:
        break
    token = res.next_continuation_token

for o in objs:
    k = (o["prefix"], o["day"])
    s = day.setdefault(k, {"count": 0, "size": 0, "last_lm_epoch": 0, "last_key": ""})
    s["count"] += 1
    s["size"] += o["size"]
    if o["lm_epoch"] > s["last_lm_epoch"]:
        s["last_lm_epoch"] = o["lm_epoch"]
        s["last_key"] = o["key"]
for k in sorted(day):
    s = day[k]
    p("  %-6s %-10s count=%3d size=%8d 最后写入=%s (%s)" % (
        k[0], k[1], s["count"], s["size"],
        lts(s["last_lm_epoch"]), s["last_key"] if k[0] == "tool/" else ""))

print("\n--- tool/ 最新 10 个日志对象 ---")
for o in sorted([x for x in objs if x["prefix"] == "tool/"], key=lambda x: x["lm_epoch"])[-10:]:
    p("  %s  %-58s %6d B" % (o["lm"], o["key"], o["size"]))
print("\n--- me/ 最新 3 个日志对象 ---")
for o in sorted([x for x in objs if x["prefix"] == "me/"], key=lambda x: x["lm_epoch"])[-3:]:
    p("  %s  %-58s %6d B" % (o["lm"], o["key"], o["size"]))

print("\n[DONE]", now())
