# -*- coding: utf-8 -*-
"""只读审计：阿里云 OSS（tool-furina-fun / furina-site-logs）。

- 凭据：复用 deploy/sync_tools.py 的 load_creds()，绝不打印 AK/SK（全部输出过 scrub）。
- 只做 List/Get 类只读操作：不 put/delete/copy/get 到磁盘。
- 同时比对本地 web/tools 文件 sha256（index.html / tt.json / assets/*）。
"""
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


def scrub(s):
    s = str(s)
    for x in _SECRETS:
        s = s.replace(x, "***REDACTED***")
    return s


def p(*parts):
    print(scrub(" ".join(str(x) for x in parts)))


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def sha(b):
    return hashlib.sha256(b).hexdigest()


import oss2  # noqa: E402

REGION = sync_tools.REGION
EP = "https://%s.aliyuncs.com" % REGION
BUCKET = sync_tools.BUCKET
LOGBUCKET = "furina-site-logs"

print("=" * 70)
print("阿里云 OSS 只读审计  @", now(), " region=", REGION)
print("=" * 70)

auth = oss2.Auth(AK, SK)
svc = oss2.Service(auth, EP)

# 0) 全部 bucket 列表（确认 me-furina-fun 是否已删、日志桶是否存在）
p("\n### 0. Bucket 列表（oss-cn-hongkong）")
try:
    for b in oss2.BucketIterator(svc):
        attrs = {}
        for k in ("name", "location", "creation_date", "storage_class", "extranet_endpoint"):
            v = getattr(b, k, None)
            if v is not None:
                attrs[k] = v
        p("  BUCKET", attrs)
except Exception as e:
    p("  [ERROR] list buckets:", type(e).__name__, e)

bucket = oss2.Bucket(auth, EP, BUCKET)

# 1) Bucket 基础属性
p("\n### 1. Bucket 属性:", BUCKET)
try:
    info = bucket.get_bucket_info()
    p("  get_bucket_info:", {k: getattr(info, k, None) for k in (
        "name", "owner", "creation_date", "location", "storage_class",
        "redundancy_type", "versioning", "intranet_endpoint", "extranet_endpoint")})
except Exception as e:
    p("  [ERROR] get_bucket_info:", type(e).__name__, e)
try:
    p("  ACL:", bucket.get_bucket_acl())
except Exception as e:
    p("  [ERROR] get_bucket_acl:", type(e).__name__, e)
try:
    w = bucket.get_bucket_website()
    p("  静态网站托管 (get_bucket_website): index=", getattr(w, "index_file", None),
      " error=", getattr(w, "error_file", None))
except Exception as e:
    p("  [ERROR] get_bucket_website:", type(e).__name__, e, "（可能未开启静态网站托管）")
try:
    lg = bucket.get_bucket_logging()
    p("  访问日志配置 (get_bucket_logging): target_bucket=", getattr(lg, "target_bucket", None),
      " target_prefix=", getattr(lg, "target_prefix", None))
except Exception as e:
    p("  [ERROR] get_bucket_logging:", type(e).__name__, e)

# 2) 自定义域名 + 证书
p("\n### 2. 自定义域名绑定 / 证书")
try:
    cn = bucket.list_bucket_cname()
    p("  bucket=", getattr(cn, "bucket", None), " owner=", getattr(cn, "owner", None))
    if not getattr(cn, "cname", None):
        p("  (无自定义域名绑定)")
    for c in getattr(cn, "cname", []) or []:
        p("  CNAME domain=", c.domain, " status=", c.status, " last_modified=", c.last_modified,
          " is_purge_cdn_cache=", c.is_purge_cdn_cache)
        cert = getattr(c, "certificate", None)
        if cert is None:
            p("    certificate = None（未绑定证书）")
        else:
            p("    cert type=", cert.type, " cert_id=", cert.cert_id, " status=", cert.status)
            p("    creation_date=", cert.creation_date, " valid_start=", cert.valid_start_date,
              " valid_end=", cert.valid_end_date)
            p("    fingerprint=", cert.fingerprint)
            try:
                if cert.valid_end_date:
                    end = datetime.datetime.fromisoformat(cert.valid_end_date.replace("Z", "+00:00"))
                    days = (end - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 86400.0
                    p("    剩余天数 = %.1f 天 (距 %s)" % (days, cert.valid_end_date))
            except Exception as e:
                p("    [warn] 剩余天数解析失败:", type(e).__name__, e)
except Exception as e:
    p("  [ERROR] list_bucket_cname:", type(e).__name__, e)

# 3) 对象清单 + sha256 + 本地比对
p("\n### 3. 对象清单:", BUCKET)
remote = {}
try:
    token = ""
    while True:
        res = bucket.list_objects_v2(prefix="", continuation_token=token, max_keys=1000)
        for o in res.object_list:
            remote[o.key] = {"size": o.size, "last_modified": o.last_modified, "etag": o.etag,
                             "storage_class": getattr(o, "storage_class", None), "type": o.type}
        if not res.is_truncated:
            break
        token = res.next_continuation_token
    p("  对象总数 =", len(remote))
except Exception as e:
    p("  [ERROR] list_objects_v2:", type(e).__name__, e)

for key in sorted(remote):
    r = remote[key]
    p("  OBJ %-28s %10d bytes  last_modified=%s  etag=%s  storage=%s" % (
        key, r["size"], r["last_modified"], r["etag"], r["storage_class"]))
    try:
        head = bucket.head_object(key)
        p("      head: Content-Type=%s  Cache-Control=%s  Content-Length=%s  Last-Modified=%s" % (
            head.headers.get("Content-Type"), head.headers.get("Cache-Control"),
            head.headers.get("Content-Length"), head.headers.get("Last-Modified")))
    except Exception as e:
        p("      [warn] head_object:", type(e).__name__, e)
    if key.endswith((".html", ".json", ".png", ".css", ".js", ".txt", ".ico", ".svg")):
        try:
            data = bucket.get_object(key).read()
            rs = sha(data)
            local_path = os.path.join(WEB, "tools", key.replace("/", os.sep))
            if os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    ld = f.read()
                ls = sha(ld)
                state = "MATCH" if ls == rs else "MISMATCH"
                p("      sha256 远端=%s (%d B) | 本地=%s (%d B) | %s" % (
                    rs, len(data), ls, len(ld), state))
            else:
                p("      sha256 远端=%s (%d B) | 本地文件不存在: %s" % (rs, len(data), local_path))
        except Exception as e:
            p("      [ERROR] get_object:", type(e).__name__, e)

# 本地 tools 目录文件（看是否有未上传的文件）
p("\n### 3b. 本地 web/tools 目录文件（与远端对比用）")
try:
    for root, dirs, files in os.walk(os.path.join(WEB, "tools")):
        dirs[:] = [d for d in dirs if d not in ("cert", "tests", "_backup", "__pycache__")]
        for f in sorted(files):
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, os.path.join(WEB, "tools")).replace("\\", "/")
            with open(fp, "rb") as fh:
                d = fh.read()
            p("  LOCAL %-30s %9d B sha256=%s | 远端%s" % (
                rel, len(d), sha(d), "有" if rel in remote else "无"))
except Exception as e:
    p("  [ERROR] walk tools:", type(e).__name__, e)

# 4) 日志 bucket 现状
p("\n### 4. 日志 Bucket:", LOGBUCKET)
try:
    lb = oss2.Bucket(auth, EP, LOGBUCKET)
    try:
        li = lb.get_bucket_info()
        p("  属性:", {k: getattr(li, k, None) for k in ("name", "owner", "creation_date", "location", "storage_class")})
    except Exception as e:
        p("  [warn] get_bucket_info:", type(e).__name__, e)
    try:
        p("  ACL:", lb.get_bucket_acl())
    except Exception as e:
        p("  [warn] get_bucket_acl:", type(e).__name__, e)
    stats = {}
    total = 0
    total_size = 0
    first = None
    last = None
    last_keys = []
    cap = 200000
    token = ""
    t0 = datetime.datetime.now()
    while True:
        res = lb.list_objects_v2(prefix="", continuation_token=token, max_keys=1000)
        for o in res.object_list:
            total += 1
            total_size += o.size
            prefix = o.key.split("/")[0] + "/" if "/" in o.key else "(root)"
            s = stats.setdefault(prefix, {"count": 0, "size": 0, "first": None, "last": None})
            s["count"] += 1
            s["size"] += o.size
            lm = str(o.last_modified)
            if s["first"] is None or lm < s["first"]:
                s["first"] = lm
            if s["last"] is None or lm > s["last"]:
                s["last"] = lm
            if first is None or lm < first:
                first = lm
            if last is None or lm > last:
                last = lm
            last_keys.append((lm, o.key, o.size))
            if len(last_keys) > 10:
                last_keys = last_keys[-10:]
        if not res.is_truncated:
            break
        token = res.next_continuation_token
        if total >= cap:
            p("  [warn] 对象数达到 cap", cap, "停止")
            break
    p("  对象总数 =", total, " 总大小 =", total_size, "bytes")
    p("  Last-Modified 范围:", first, "→", last)
    for k in sorted(stats):
        p("  前缀 %-10s count=%d size=%d first=%s last=%s" % (
            k, stats[k]["count"], stats[k]["size"], stats[k]["first"], stats[k]["last"]))
    p("  最近 5 个对象（按 Last-Modified）:")
    for lm, key, size in sorted(last_keys)[-5:]:
        p("    %s  %-50s %d bytes" % (lm, key, size))
    elapsed = (datetime.datetime.now() - t0).total_seconds()
    p("  (列举耗时 %.1fs)" % elapsed)
    # me/ 前缀
    try:
        cnt_me = 0
        token = ""
        while True:
            res = lb.list_objects_v2(prefix="me/", continuation_token=token, max_keys=1000)
            cnt_me += len(res.object_list)
            if not res.is_truncated:
                break
            token = res.next_continuation_token
        p("  me/ 前缀对象数 =", cnt_me, "（下线清单要求清空，应为 0）")
    except Exception as e:
        p("  [warn] me/ 前缀计数:", type(e).__name__, e)
except Exception as e:
    p("  [ERROR] logs bucket:", type(e).__name__, e)

print("\n[DONE]", now())
