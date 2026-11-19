# -*- coding: utf-8 -*-
"""preflight_cutover.py — 切流日前置检查（只读，不切换任何服务）。

覆盖：CloudBase CLI 登录/到期、DNS/HTTPS 门槛、ECS 站点/附件/PPT 缓存、staging 路由、生产路由模式、
自建 PG/PostgREST 监控、备份/异地备份、最新快照、测试账号 staging 冒烟、仓库工作区状态；
可选 `--drift` 对比 CloudBase 当前行数与最新快照（只读 SQL）。

用法（web 仓库根目录，系统 python；需要 aliyunsdkcore + oss2）::

    python deploy\\migration\\preflight_cutover.py
    python deploy\\migration\\preflight_cutover.py --drift
    python deploy\\migration\\preflight_cutover.py --json
    python deploy\\migration\\preflight_cutover.py --check-remotes

退出码：有 FAIL → 1；仅 WARN/PASS → 0（DNS/ICP 未过是预期 WARN，但它是切流的硬门槛，见备注）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
DATA_ROOT = r"G:\ClassTools\briefdesk\data\cloudbase_migration"
ECS = "http://121.196.47.2"
STAGING = ECS + "/v1/rdb/rest-next/"
PROD = ECS + "/v1/rdb/rest/"
TEST_SID = "3260799999"
TEST_NAME = "测试账号"
PRIVATE_BUCKET = "furina-site-logs"
PRIVATE_REGION = "oss-cn-hongkong"
PRIVATE_PREFIX = "pg-backup/"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROWS = []  # (level, name, detail)


def add(level, name, detail=""):
    ROWS.append((level, name, str(detail)[:400]))
    return level == "FAIL"


def http(url, timeout=15, method="GET", data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(400)
        except Exception:  # noqa: BLE001
            body = b""
        return exc.code, dict(exc.headers or {}), body
    except Exception as exc:  # noqa: BLE001
        return 0, {}, str(exc).encode("utf-8", "replace")


def post_json(url, body, headers=None, timeout=30):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    st, hd, raw = http(url, timeout=timeout, method="POST", data=json.dumps(body).encode("utf-8"), headers=h)
    try:
        return st, json.loads(raw.decode("utf-8") or "null")
    except Exception:  # noqa: BLE001
        return st, None


def latest_snapshot():
    if not os.path.isdir(DATA_ROOT):
        return None
    cands = []
    for name in os.listdir(DATA_ROOT):
        d = os.path.join(DATA_ROOT, name)
        man = os.path.join(d, "manifest.json")
        dm = os.path.join(d, "data_manifest.json")
        if os.path.isfile(man) and os.path.isfile(dm):
            cands.append((os.path.getmtime(man), d))
    if not cands:
        return None
    return sorted(cands, reverse=True)[0][1]


def snapshot_info():
    d = latest_snapshot()
    if not d:
        add("FAIL", "快照", "找不到含 manifest.json/data_manifest.json 的产物目录（%s）" % DATA_ROOT)
        return None
    try:
        dm = json.load(open(os.path.join(d, "data_manifest.json"), encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        add("WARN", "快照", "data_manifest 解析失败：%s" % type(exc).__name__)
        return None
    totals = dm.get("totals") or {}
    gen = dm.get("generated_at_utc") or ""
    age_h = (time.time() - os.path.getmtime(os.path.join(d, "manifest.json"))) / 3600.0
    add("WARN" if age_h > 24 else "PASS", "快照",
        "%s | 表 %s / 行 %s / %.1f MiB | 生成 %s UTC | 距今 %.1f h"
        % (os.path.basename(d), totals.get("tables"), totals.get("rows"),
           (totals.get("bytes_gz") or 0) / 1048576.0, gen or "?", age_h))
    return d


def check_tcb():
    try:
        pr = subprocess.run(["tcb.cmd", "env", "list", "--json"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=120)
        doc = json.loads(pr.stdout or "{}")
        data = doc.get("data") or []
        if not data:
            add("FAIL", "CloudBase CLI", "`tcb env list` 无环境（未登录？）")
            return
        env = data[0]
        expire = env.get("ExpireTime") or ""
        try:
            dt = _dt.datetime.strptime(expire, "%Y-%m-%d %H:%M:%S")
            left = (dt - _dt.datetime.now()).total_seconds() / 86400.0
            level = "FAIL" if left < 0 else ("WARN" if left < 7 else "PASS")
            add(level, "CloudBase 环境",
                "%s | status=%s | 到期 %s（剩 %.1f 天）" % (env.get("EnvId"), env.get("Status"), expire, left))
        except Exception:  # noqa: BLE001
            add("WARN", "CloudBase 环境", "%s | 到期 %s（无法计算天数）" % (env.get("EnvId"), expire))
    except Exception as exc:  # noqa: BLE001
        add("FAIL", "CloudBase CLI", "tcb env list 失败：%s: %s" % (type(exc).__name__, str(exc)[:160]))


def check_dns():
    try:
        infos = socket.getaddrinfo("tool.furina.fun", 443)
        ips = sorted({i[4][0] for i in infos})
        add("PASS", "DNS/HTTPS 门槛", "tool.furina.fun 解析到 %s" % ",".join(ips[:4]))
    except Exception:  # noqa: BLE001
        add("WARN", "DNS/HTTPS 门槛",
            "tool.furina.fun 未解析（ICP 备案未完成；**切流硬门槛**：小程序/安卓正式版需要该域名 HTTPS）")


def check_ecs_services():
    st, hd, body = http(ECS + "/", timeout=15)
    add("PASS" if st == 200 else "FAIL", "ECS 首页", "HTTP %s" % st)
    st, hd, body = http(STAGING, timeout=20)
    add("PASS" if st == 200 else "FAIL", "staging 路由", "HTTP %s" % st)
    st, hd, body = http(PROD, timeout=20)
    if st == 401:
        add("PASS", "生产路由模式", "HTTP 401（仍 CloudBase，未切流）")
    elif st == 200:
        add("WARN", "生产路由模式", "HTTP 200（可能已切自建；确认是否预期）")
    else:
        add("WARN", "生产路由模式", "HTTP %s" % st)
    for path, name, key in (("/att/healthz", "附件服务", "ok"),
                            ("/pptfiles/__health", "PPT 缓存", "ok")):
        st, hd, body = http(ECS + path, timeout=15)
        ok = False
        try:
            doc = json.loads(body.decode("utf-8") or "{}")
            ok = st == 200 and bool(doc.get(key))
        except Exception:  # noqa: BLE001
            pass
        add("PASS" if ok else "FAIL", name, "HTTP %s %s" % (st, body[:100].decode("utf-8", "replace")))


def check_pg():
    try:
        pr = subprocess.run([sys.executable, os.path.join(WEB, "deploy", "ecs_pg.py"), "monitor", "--json"],
                            cwd=WEB, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=240, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        doc = None
        for line in (pr.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    doc = json.loads(line)
                except Exception:  # noqa: BLE001
                    pass
        if not doc:
            add("FAIL", "自建 PG/PostgREST", "monitor --json 无 JSON 输出")
            return
        m = doc.get("metrics") or {}
        ok = bool(doc.get("ok"))
        add("PASS" if ok else "FAIL", "自建 PG/PostgREST",
            "ok=%s | 备份 %sh(%s 份) | 磁盘 %s%% | 连接 %s | db=%s | prod_mode=%s"
            % (ok, m.get("backup_age_h"), m.get("backup_count"), m.get("disk_use_pct"),
               m.get("connections"), m.get("db_size"), m.get("prod_mode")))
        try:
            age = float(m.get("backup_age_h"))
            if age > 36:
                add("FAIL", "备份年龄", "%sh > 36h" % age)
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        add("FAIL", "自建 PG/PostgREST", "monitor 失败：%s" % type(exc).__name__)


def check_offsite():
    try:
        import oss2
        sys.path.insert(0, os.path.join(WEB, "deploy"))
        import sync_tools
        ak, sk = sync_tools.load_creds()
        b = oss2.Bucket(oss2.Auth(ak, sk), "https://%s.aliyuncs.com" % PRIVATE_REGION, PRIVATE_BUCKET)
        objs = [o for o in oss2.ObjectIterator(b, prefix=PRIVATE_PREFIX) if o.key.endswith(".dump")]
        if not objs:
            add("WARN", "异地备份", "私有 OSS 没有备份对象（建议先跑 `ecs_pg.py offsite`）")
            return
        objs.sort(key=lambda o: o.last_modified, reverse=True)
        newest = objs[0]
        age_d = (time.time() - newest.last_modified) / 86400.0
        level = "PASS" if age_d <= 14 else "WARN"
        add(level, "异地备份", "%d 份 | 最新 %s（%.1f 天前，%.1f MiB）"
            % (len(objs), os.path.basename(newest.key), age_d, newest.size / 1048576.0))
    except Exception as exc:  # noqa: BLE001
        add("WARN", "异地备份", "检查失败：%s: %s" % (type(exc).__name__, str(exc)[:160]))


def check_test_account():
    try:
        st, ver = post_json(STAGING + "rpc/class_verify", {"p_sid": TEST_SID, "p_name": TEST_NAME}, timeout=30)
        tok = (ver or {}).get("token") or ""
        if st != 200 or not tok:
            add("FAIL", "测试账号 staging", "class_verify HTTP %s" % st)
            return
        hdr = {"X-Class-Token": tok, "X-Device-Id": tok}
        st, members = post_json(STAGING + "rpc/class_members", {}, headers=hdr, timeout=30)
        st2, meta = post_json(STAGING + "rpc/class_notices_meta", {}, headers=hdr, timeout=60)
        ok = st == 200 and isinstance(members, list) and len(members) == 70 and st2 == 200 and isinstance(meta, list)
        add("PASS" if ok else "FAIL", "测试账号 staging",
            "members=%s meta=%s" % (len(members) if isinstance(members, list) else members,
                                    len(meta) if isinstance(meta, list) else meta))
    except Exception as exc:  # noqa: BLE001
        add("FAIL", "测试账号 staging", "%s: %s" % (type(exc).__name__, str(exc)[:160]))


def check_repo(check_remotes=False):
    try:
        pr = subprocess.run(["git", "status", "--porcelain"], cwd=WEB, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60)
        dirty = [l for l in (pr.stdout or "").splitlines() if l.strip()]
        add("PASS" if not dirty else "WARN", "仓库工作区",
            "clean" if not dirty else "%d 个未提交改动（切流前建议 clean）" % len(dirty))
        if check_remotes:
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WEB, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=30).stdout.strip()
            for remote in ("origin", "gitee"):
                try:
                    pr = subprocess.run(["git", "ls-remote", remote, "refs/heads/master"], cwd=WEB,
                                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                                        timeout=60)
                    sha = (pr.stdout or "").split()[0] if (pr.stdout or "").strip() else ""
                    add("PASS" if sha == head else "WARN", "远端 %s" % remote,
                        "一致" if sha == head else "本地 %s / 远端 %s" % (head[:8], sha[:8] or "?"))
                except Exception:  # noqa: BLE001
                    add("WARN", "远端 %s" % remote, "网络不可达（跳过）")
    except Exception as exc:  # noqa: BLE001
        add("WARN", "仓库工作区", "git 检查失败：%s" % type(exc).__name__)


def check_drift(snapdir):
    if not snapdir:
        add("WARN", "数据漂移", "无快照可对比")
        return
    try:
        dm = json.load(open(os.path.join(snapdir, "data_manifest.json"), encoding="utf-8"))
        tables = dm.get("tables") or {}
    except Exception as exc:  # noqa: BLE001
        add("WARN", "数据漂移", "读取 data_manifest 失败：%s" % type(exc).__name__)
        return
    if not tables:
        add("WARN", "数据漂移", "manifest 无 tables")
        return
    keys = sorted(tables.keys())
    parts = ["select '%s' as t, count(*) as n from %s" % (k.replace("'", "''"), k) for k in keys]
    sql = " union all ".join(parts)
    try:
        pr = subprocess.run(["tcb.cmd", "db", "execute", "--json", "--sql", sql], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=300)
        doc = json.loads(pr.stdout or "{}")
        rows = doc.get("data", {}).get("Rows") or []
        live = {}
        for r in rows:
            arr = json.loads(r)
            live[arr[0]] = int(arr[1])
    except Exception as exc:  # noqa: BLE001
        add("WARN", "数据漂移", "只读 SQL 失败：%s: %s" % (type(exc).__name__, str(exc)[:160]))
        return
    diffs = []
    for k in keys:
        sn = int((tables.get(k) or {}).get("rows") or 0)
        lv = live.get(k)
        if lv is not None and lv != sn:
            diffs.append("%s %+d" % (k, lv - sn))
    if diffs:
        add("WARN", "数据漂移", "%d 张表有变化（相对最新快照，切流时会重新导出）：%s"
            % (len(diffs), "；".join(diffs[:10])))
    else:
        add("PASS", "数据漂移", "全部 %d 表行数与最新快照一致" % len(keys))


def main(argv=None):
    ap = argparse.ArgumentParser(description="切流日前置检查（只读）")
    ap.add_argument("--drift", action="store_true", help="对比 CloudBase 当前行数与最新快照（只读 SQL）")
    ap.add_argument("--check-remotes", action="store_true", help="检查 GitHub/Gitee 与本地 HEAD 一致")
    ap.add_argument("--json", action="store_true", help="输出 JSON 汇总")
    ns = ap.parse_args(argv)
    t0 = time.time()
    snapdir = snapshot_info()
    check_tcb()
    check_dns()
    check_ecs_services()
    check_pg()
    check_offsite()
    check_test_account()
    check_repo(ns.check_remotes)
    if ns.drift:
        check_drift(snapdir)
    else:
        add("PASS", "数据漂移", "未检查（--drift 可对比最新快照行数）")
    fails = [r for r in ROWS if r[0] == "FAIL"]
    warns = [r for r in ROWS if r[0] == "WARN"]
    if ns.json:
        print(json.dumps({"ok": not fails, "fails": len(fails), "warns": len(warns),
                          "checks": [{"level": a, "name": b, "detail": c} for a, b, c in ROWS],
                          "elapsed_s": round(time.time() - t0, 1)}, ensure_ascii=False, indent=1))
    else:
        print("\n=== 切流日前置检查（%s） ===" % time.strftime("%Y-%m-%d %H:%M:%S"))
        for level, name, detail in ROWS:
            print("[%s] %-18s %s" % (level, name, detail))
        print("\n汇总：PASS %d / WARN %d / FAIL %d  （耗时 %.1fs）"
              % (len(ROWS) - len(fails) - len(warns), len(warns), len(fails), time.time() - t0))
        if fails:
            print("结论：存在 FAIL，**不要切流**；先处理上述问题。")
        elif warns:
            print("结论：无 FAIL；WARN 需人工判断（DNS/ICP 未过是已知切流硬门槛）。")
        else:
            print("结论：全部 PASS，可进入 cutover_run execute。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
