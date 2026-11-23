# -*- coding: utf-8 -*-
"""把 tool.furina.fun 的解析从香港 OSS 切到内地 ECS（ICP 备案落点），或回滚。

背景（2026-11-23）：网站 ICP 备案已通过（备案号 闽ICP备2026042939号-2）。
备案通过前域名 CNAME 到 `tool-furina-fun.oss-cn-hongkong.aliyuncs.com`（香港 OSS），
而 ICP 备案要求解析到备案接入商的内地服务器（本项目为阿里云杭州 ECS `121.196.47.2`）。

用法（在 web 目录下执行，凭据同 deploy/creds.env）：
    python deploy\\domain_switch.py status          # 只读：列出 furina.fun 下 tool 相关记录
    python deploy\\domain_switch.py to-ecs          # 备份 → 删除 tool 的 CNAME/A → 新增 A 记录到 ECS
    python deploy\\domain_switch.py to-ecs --dry-run
    python deploy\\domain_switch.py wait            # 轮询公共 DNS（阿里 DoH）直到 A 记录生效
    python deploy\\domain_switch.py restore --file deploy\\_dns_backup\\xxx.json

安全：
- 只动 `tool` 这一条 RR 的 A/CNAME 记录，不动 TXT（证书校验）、MX、其它子域；
- 每次写操作前把当前记录备份成 JSON（`deploy/_dns_backup/`，已在 .gitignore）；
- 不打印任何凭据。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ZONE = "furina.fun"
RR = "tool"
ECS_IP = "121.196.47.2"
ECS_IP_OLD = "121.196.47.2"  # 备案落点固定；保留常量便于将来换 ECS
TTL = "600"
BACKUP_DIR = os.path.join(HERE, "_dns_backup")
DOH = "https://dns.alidns.com/resolve"


def load_creds() -> tuple[str, str]:
    """与 sync_tools.load_creds 同口径；只返回，不打印。"""
    if os.environ.get("ALIYUN_AK_ID") and os.environ.get("ALIYUN_AK_SECRET"):
        return os.environ["ALIYUN_AK_ID"], os.environ["ALIYUN_AK_SECRET"]
    p = os.path.join(HERE, "creds.env")
    if os.path.exists(p):
        d = {}
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
        if d.get("ALIYUN_AK_ID") and d.get("ALIYUN_AK_SECRET"):
            return d["ALIYUN_AK_ID"], d["ALIYUN_AK_SECRET"]
    raise SystemExit("缺少凭据：环境变量 ALIYUN_AK_ID / ALIYUN_AK_SECRET，或 web/deploy/creds.env")


def client():
    from aliyunsdkcore.client import AcsClient

    ak, sk = load_creds()
    return AcsClient(ak, sk, "cn-hangzhou")


def dns(cli, action: str, params: dict) -> dict:
    from aliyunsdkcore.request import CommonRequest

    r = CommonRequest()
    r.set_domain("alidns.aliyuncs.com")
    r.set_version("2015-01-09")
    r.set_action_name(action)
    r.set_method("POST")
    for k, v in params.items():
        r.add_query_param(k, v)
    return json.loads(cli.do_action_with_exception(r).decode("utf-8"))


def records(cli) -> list[dict]:
    """取本 zone 下 RR 精确等于 tool 的记录（A/AAAA/CNAME 全取，TXT 不含）。"""
    out: list[dict] = []
    page = 1
    while True:
        res = dns(cli, "DescribeDomainRecords", {
            "DomainName": ZONE, "PageNumber": str(page), "PageSize": "100",
            "RRKeyWord": RR,
        })
        recs = (res.get("DomainRecords") or {}).get("Record") or []
        for x in recs:
            if str(x.get("RR", "")).strip() != RR:
                continue
            out.append(x)
        total = int(res.get("TotalCount") or 0)
        if page * 100 >= total or not recs:
            break
        page += 1
    return out


def show(recs: list[dict]) -> None:
    if not recs:
        print("  (无记录)")
        return
    for x in recs:
        print("  %-8s %-6s %-6s %s  ttl=%s  status=%s  id=%s" % (
            x.get("RR"), x.get("Type"), x.get("Line", ""), x.get("Value"),
            x.get("TTL"), x.get("Status"), x.get("RecordId")))


def backup(recs: list[dict]) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(BACKUP_DIR, "%s-%s-%s.json" % (ZONE, RR, ts))
    keep = [{k: x.get(k) for k in ("RR", "Type", "Value", "TTL", "Line", "Priority", "RecordId")}
            for x in recs]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"zone": ZONE, "rr": RR, "saved_at": ts, "records": keep}, fh,
                  ensure_ascii=False, indent=2)
    print("[backup] %s（%d 条）" % (path, len(keep)))
    return path


def delete_record(cli, record_id: str, label: str, dry: bool) -> None:
    print("  - 删除 %s（%s）" % (label, record_id))
    if dry:
        return
    dns(cli, "DeleteDomainRecord", {"RecordId": record_id})


def add_a(cli, dry: bool) -> None:
    print("  + 新增 A tool -> %s（TTL %s，默认线路）" % (ECS_IP, TTL))
    if dry:
        return
    dns(cli, "AddDomainRecord", {
        "DomainName": ZONE, "RR": RR, "Type": "A", "Value": ECS_IP, "TTL": TTL,
    })


def cmd_status(cli) -> int:
    print("zone=%s rr=%s" % (ZONE, RR))
    recs = records(cli)
    show(recs)
    a = [x for x in recs if x.get("Type") == "A" and x.get("Value") == ECS_IP]
    if a:
        print("=> 已指向 ECS %s" % ECS_IP)
    else:
        print("=> 尚未指向 ECS %s（当前仍是 OSS CNAME 或空）" % ECS_IP)
    return 0


def cmd_to_ecs(cli, dry: bool) -> int:
    recs = records(cli)
    print("切换前记录：")
    show(recs)
    if any(x.get("Type") == "A" and x.get("Value") == ECS_IP for x in recs):
        print("=> 已经是 A → %s，无需切换" % ECS_IP)
        return 0
    backup(recs)
    print("执行：")
    for x in recs:
        if x.get("Type") in ("A", "AAAA", "CNAME"):
            delete_record(cli, x["RecordId"], "%s %s %s" % (
                x.get("Type"), x.get("RR"), x.get("Value")), dry)
    add_a(cli, dry)
    print("完成。解析生效后运行 `python deploy\\ecs_site.py apply` 让 Caddy 自动签发证书。")
    return 0


def cmd_restore(cli, path: str, dry: bool) -> int:
    data = json.load(open(path, encoding="utf-8"))
    if data.get("zone") != ZONE or data.get("rr") != RR:
        raise SystemExit("备份文件的 zone/rr 不匹配：%s" % path)
    print("回滚到 %s（%d 条）" % (data.get("saved_at"), len(data["records"])))
    cur = records(cli)
    for x in cur:
        if x.get("Type") in ("A", "AAAA", "CNAME"):
            delete_record(cli, x["RecordId"], "%s %s %s" % (
                x.get("Type"), x.get("RR"), x.get("Value")), dry)
    for x in data["records"]:
        if x.get("Type") not in ("A", "AAAA", "CNAME"):
            continue
        print("  + 恢复 %s %s -> %s" % (x.get("Type"), x.get("RR"), x.get("Value")))
        if dry:
            continue
        params = {
            "DomainName": ZONE, "RR": x["RR"], "Type": x["Type"],
            "Value": x["Value"], "TTL": x.get("TTL") or TTL,
        }
        if x.get("Line"):
            params["Line"] = x["Line"]
        dns(cli, "AddDomainRecord", params)
    return 0


def public_a() -> list[str]:
    q = urllib.parse.urlencode({"name": "%s.%s" % (RR, ZONE), "type": "A"})
    req = urllib.request.Request(DOH + "?" + q, headers={"Accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [a.get("data", "") for a in (data.get("Answer") or []) if a.get("type") == 1]


def cmd_wait(timeout: int) -> int:
    start = time.time()
    last = None
    while time.time() - start < timeout:
        try:
            ips = public_a()
        except Exception as e:  # noqa: BLE001 - 只看结果
            ips = ["ERR:%s" % type(e).__name__]
        if ips != last:
            print("  [%s] A=%s" % (time.strftime("%H:%M:%S"), ips))
            last = ips
        if ECS_IP in ips:
            print("=> 公共 DNS 已生效：%s" % ", ".join(ips))
            return 0
        time.sleep(10)
    print("=> 超时：%ss 内公共 DNS 仍未返回 A %s（可能 TTL/缓存尚未过期）" % (timeout, ECS_IP))
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="tool.furina.fun 解析切换/回滚（阿里云 DNS）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="只读列出记录")
    p_ecs = sub.add_parser("to-ecs", help="切到 ECS A 记录")
    p_ecs.add_argument("--dry-run", action="store_true")
    p_wait = sub.add_parser("wait", help="轮询公共 DNS")
    p_wait.add_argument("--timeout", type=int, default=300)
    p_restore = sub.add_parser("restore", help="按备份回滚")
    p_restore.add_argument("--file", required=True)
    p_restore.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args(argv)

    if ns.cmd == "wait":
        return cmd_wait(ns.timeout)
    cli = client()
    if ns.cmd == "status":
        return cmd_status(cli)
    if ns.cmd == "to-ecs":
        return cmd_to_ecs(cli, ns.dry_run)
    if ns.cmd == "restore":
        return cmd_restore(cli, ns.file, ns.dry_run)
    return 2


if __name__ == "__main__":
    sys.exit(main())
