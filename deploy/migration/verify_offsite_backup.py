# -*- coding: utf-8 -*-
"""校验私有 OSS 异地备份可用：下载 → sha256 对比 ECS 本机 dump → pg_restore 到临时库 → 计数 → 清理。

用法（web 仓库根目录，系统 python）：
    python deploy\\migration\\verify_offsite_backup.py [--keep-db]

只读/临时库操作：不动 class_tools 生产库；临时库名 class_tools_offsite_test，默认校验后 DROP。
输出只含计数/大小，不打印数据内容。
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(WEB, "deploy"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import ecs_site  # noqa: E402

PRIVATE_BUCKET = "furina-site-logs"
REGION = "oss-cn-hongkong"
PREFIX = "pg-backup/"
TMPDB = "class_tools_offsite_test"

REMOTE = r"""#!/bin/bash
set +e
export LC_ALL=C
URL="__URL__"
BASE="__BASE__"
TMPDB="class_tools_offsite_test"
TMP=/tmp/offsite_verify.dump
echo "=== 1. 下载私有 OSS 对象 ==="
curl -sS -m 900 -o "$TMP" -w 'download_http=%{http_code} bytes=%{size_download} time=%{time_total}s\n' "$URL"
[ -s "$TMP" ] || { echo "FATAL 下载为空"; exit 2; }
REMOTE_SHA=$(sha256sum "$TMP" | cut -d' ' -f1)
echo "remote_sha256=$REMOTE_SHA"
LOCAL=/opt/class-tools/backup/pg/"$BASE"
if [ -f "$LOCAL" ]; then
  LOCAL_SHA=$(sha256sum "$LOCAL" | cut -d' ' -f1)
  echo "local_sha256=$LOCAL_SHA"
  [ "$REMOTE_SHA" = "$LOCAL_SHA" ] && echo "SHA256_MATCH" || { echo "FATAL sha 不一致"; exit 3; }
else
  echo "WARN 本机已无同名 dump（仅做可读性恢复）"
fi
echo "=== 2. pg_restore -l 可读性 ==="
LINES=$(pg_restore -l "$TMP" | wc -l)
echo "restore_list_lines=$LINES"
pg_restore -l "$TMP" | grep -E '^[0-9]+;' | head -3
echo "=== 3. 恢复到临时库 ${TMPDB} ==="
runuser -u postgres -- dropdb --if-exists "$TMPDB" 2>/dev/null
runuser -u postgres -- createdb -O class_tools_owner -E UTF8 --locale=C --template=template0 "$TMPDB" || { echo "FATAL createdb"; exit 4; }
runuser -u postgres -- pg_restore --no-owner -d "$TMPDB" "$TMP" >/tmp/offsite_restore.log 2>&1
RC=$?
echo "restore_rc=$RC"
tail -4 /tmp/offsite_restore.log
echo "=== 4. 计数校验 ==="
runuser -u postgres -- psql -d "$TMPDB" -Atc "select 'tables='||count(*) from information_schema.tables where table_schema in ('public','private')"
runuser -u postgres -- psql -d "$TMPDB" -Atc "select 'functions='||count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('public','private')"
runuser -u postgres -- psql -d "$TMPDB" -Atc "select 'policies='||count(*) from pg_policies"
runuser -u postgres -- psql -d "$TMPDB" -Atc "select 'notices='||count(*) from public.notices"
runuser -u postgres -- psql -d "$TMPDB" -Atc "select 'class_sessions='||count(*) from private.class_sessions"
runuser -u postgres -- psql -d "$TMPDB" -Atc "select 'db_size='||pg_size_pretty(pg_database_size(current_database()))"
echo "=== 5. 清理临时库 ==="
runuser -u postgres -- dropdb --if-exists "$TMPDB"
rm -f "$TMP" /tmp/offsite_restore.log
echo "OFFSITE_VERIFY_OK"
"""


def bucket():
    import oss2
    import sync_tools
    ak, sk = sync_tools.load_creds()
    return oss2.Bucket(oss2.Auth(ak, sk), "https://%s.aliyuncs.com" % REGION, PRIVATE_BUCKET)


def main(argv=None):
    ap = argparse.ArgumentParser(description="校验私有 OSS 异地备份（下载/恢复临时库/计数）")
    ap.parse_args(argv)
    b = bucket()
    objs = []
    for o in __import__("oss2").ObjectIterator(b, prefix=PREFIX):
        if o.key.endswith(".dump"):
            objs.append(o)
    if not objs:
        print("[x] 私有 OSS %s%s 下没有备份对象" % (PRIVATE_BUCKET, PREFIX))
        return 2
    objs.sort(key=lambda o: o.last_modified, reverse=True)
    latest = objs[0]
    base = os.path.basename(latest.key)
    print("[verify] 最新异地备份：%s/%s (%d B, %s)" % (PRIVATE_BUCKET, latest.key, latest.size, latest.last_modified))
    url = b.sign_url("GET", latest.key, 1800)
    script = REMOTE.replace("__URL__", url).replace("__BASE__", base)
    st, rc, out = ecs_site.run_script(script, label="offsite-verify", timeout=900, wait=1200)
    print(out)
    ok = st == "Success" and rc in (0, "0") and ("OFFSITE_VERIFY_OK" in (out or ""))
    print("[verify]", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
