# -*- coding: utf-8 -*-
"""只读盘点：哪些服务已迁到阿里云 ECS，哪些仍在外部（CloudBase / OSS 香港 / 本机）。

用法（web 目录）：
    python deploy\\ecs_audit.py            # 人类可读报告
    python deploy\\ecs_audit.py --json     # 机器可读（不含任何密钥）

口径（2026-11-28 P4 切流后）：
- 「已迁」= 进程/数据在 ECS 上，公网只能经 Caddy 同源访问（含生产 REST 与三个定时任务）；
- 「外部依赖」= 阿里云 OSS 香港（发布源与 PPT/APK 资产）、本机 Windows（通知采集/构建、PPT 转换、教务抓取、
  诊断 agent 等必须依赖本机环境的部分）、微信云开发（小程序订阅消息 openid/发送）、CloudBase 旧库（2026-12-10 到期）。
本脚本不读取、不打印任何密码/凭据。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ecs_site  # noqa: E402

SITE = "https://tool.furina.fun"

REMOTE = r"""set +e
echo "###UNITS"
for u in caddy briefdesk-board class-tools-att class-tools-pptfiles class-tools-drop class-tools-account class-tools-map class-tools-pgrest postgresql@18-main; do
  printf '%s|%s\n' "$u" "$(systemctl is-active $u 2>/dev/null)"
done
echo "###PORTS"
ss -ltn 2>/dev/null | awk 'NR>1{print $4}' | grep -E ':(80|443|3000|5432|8090|8091|8092|8093|8094|8095)$' | sort -u
echo "###DBS"
runuser -u postgres -- psql -Atc "select datname||'|'||pg_size_pretty(pg_database_size(datname)) from pg_database where datname like 'class_tools%' order by datname" 2>/dev/null
echo "###FRESH"
runuser -u postgres -- psql -Atd class_tools -c "select 'class_tools|'||coalesce(to_char(to_timestamp(max(ts)/1000) at time zone 'Asia/Shanghai','YYYY-MM-DD HH24:MI'),'-') from public.notices" 2>/dev/null
runuser -u postgres -- psql -Atd class_tools_cut -c "select 'class_tools_cut|'||coalesce(to_char(to_timestamp(max(ts)/1000) at time zone 'Asia/Shanghai','YYYY-MM-DD HH24:MI'),'-') from public.notices" 2>/dev/null
echo "###COUNTS"
runuser -u postgres -- psql -Atd class_tools -c "select 'tables|'||count(*) from information_schema.tables where table_schema in ('public','private')" 2>/dev/null
echo "###TIMERS"
systemctl list-timers --no-legend 2>/dev/null | grep -E 'class-tools' | awk '{print $4, $NF}'
echo "###UPSTREAM"
grep -E 'reverse_proxy' /etc/caddy/Caddyfile 2>/dev/null | sed -E 's/^[ \t]*//' | sort -u
echo "###SIZES"
du -sh /var/www/tool /opt/class-tools/pptfiles /opt/class-tools/attachments /opt/class-tools/drop /opt/class-tools/backup/pg 2>/dev/null
echo "###ATT"
find /opt/class-tools/attachments -type f 2>/dev/null | wc -l
echo "###DONE"
"""


def fetch(path: str, timeout: int = 20):
    try:
        req = urllib.request.Request(SITE + path, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def parse(out: str) -> dict:
    data: dict = {"units": {}, "ports": [], "dbs": [], "fresh": {}, "timers": [], "upstream": [],
                  "sizes": [], "attachments": None, "tables": None}
    section = ""
    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith("###"):
            section = line[3:]
            continue
        if not line:
            continue
        if section == "UNITS" and "|" in line:
            k, v = line.split("|", 1)
            data["units"][k] = v
        elif section == "PORTS":
            data["ports"].append(line)
        elif section == "DBS":
            data["dbs"].append(line)
        elif section == "FRESH" and "|" in line:
            k, v = line.split("|", 1)
            data["fresh"][k] = v
        elif section == "COUNTS" and "|" in line:
            k, v = line.split("|", 1)
            if k == "tables":
                data["tables"] = int(v) if v.isdigit() else None
        elif section == "TIMERS":
            data["timers"].append(line)
        elif section == "UPSTREAM":
            data["upstream"].append(line)
        elif section == "SIZES":
            data["sizes"].append(line)
        elif section == "ATT" and line.isdigit():
            data["attachments"] = int(line)
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ECS 服务迁移盘点（只读）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ns = ap.parse_args(argv)

    st, code, out = ecs_site.run_script(REMOTE, label="ecs-audit", timeout=180)
    if st != "Success" or str(code) not in ("0", "None"):
        raise SystemExit("云助手执行失败：status=%s exit=%s" % (st, code))
    data = parse(out)

    public = {p: fetch(p) for p in
              ("/", "/api/status", "/board", "/legal/web/privacy.html", "/tt.json",
               "/pptfiles/__health", "/drop/__health", "/v1/rdb/rest/", "/v1/rdb/rest-next/")}
    data["public"] = public

    # 生产 REST 的响应格式可用于判断上游：CloudBase 缺凭据返回 code=MISSING_CREDENTIALS；
    # ECS 自建 PostgREST 返回 200 OpenAPI（swagger/openapi 字段）。2026-11-28 P4 切流后应为后者。
    prod_mode = "unknown"
    try:
        with urllib.request.urlopen(urllib.request.Request(SITE + "/v1/rdb/rest/"), timeout=20) as r:
            body = r.read(300).decode("utf-8", "replace")
        if '"swagger"' in body or '"openapi"' in body:
            prod_mode = "selfhosted"
        elif "MISSING_CREDENTIALS" in body or "cloudbase.net" in body:
            prod_mode = "cloudbase"
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        body = e.read(300).decode("utf-8", "replace")
        if "MISSING_CREDENTIALS" in body or "cloudbase.net" in body:
            prod_mode = "cloudbase"
    except Exception:  # noqa: BLE001
        pass
    data["prod_rest_mode"] = prod_mode
    data["prod_rest_cloudbase"] = prod_mode == "cloudbase"
    data["oss_refs"] = [u for u in data["upstream"] if "tcloudbasegateway" in u]

    if ns.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    ok = lambda k: "[OK] active" if data["units"].get(k) == "active" else "[NOT-ACTIVE] " + data["units"].get(k, "missing")  # noqa: E731
    print("== 一、ECS 上的服务（实测） ==")
    rows = [
        ("Caddy（:80/:443，HTTPS + 同源反代）", "caddy"),
        ("站点静态文件 /var/www/tool", None),
        ("公告板 API /api/*（/board 页）", "briefdesk-board"),
        ("通知附件签名服务 /att/*", "class-tools-att"),
        ("PPT 文件缓存 /pptfiles/*", "class-tools-pptfiles"),
        ("文件传输 /drop/*", "class-tools-drop"),
        ("扫码登录/账号服务 /account/*", "class-tools-account"),
        ("校园地图共享状态 /map/api/*", "class-tools-map"),
        ("PostgreSQL 18（127.0.0.1:5432）", "postgresql@18-main"),
        ("PostgREST 13（127.0.0.1:3000，生产 + staging）", "class-tools-pgrest"),
    ]
    for label, unit in rows:
        print("  %-42s %s" % (label, ok(unit) if unit else "[OK] " + (data["sizes"][0] if data["sizes"] else "")))
    if data["timers"]:
        print("  定时任务：")
        for t in data["timers"]:
            print("    - " + t)
    if data["attachments"] is not None:
        print("  附件外置服务文件数：%d（管线仍默认关闭）" % data["attachments"])

    print("\n== 二、数据层 ==")
    for db in data["dbs"]:
        name, size = (db.split("|", 1) + [""])[:2]
        fresh = data["fresh"].get(name, "-")
        print("  %-16s %-8s notices.max(ts)=%s  %s" % (
            name, size, fresh, "（历史快照，非实时）" if fresh and fresh != "-" else ""))
    print("  public/private 表数：%s；PostgREST 版本：13.x" % data["tables"])
    if data.get("prod_rest_mode") == "selfhosted":
        print("  /v1/rdb/rest/*      → ECS 自建 PostgREST（127.0.0.1:3000，2026-11-28 起生产）")
    elif data["prod_rest_cloudbase"]:
        print("  /v1/rdb/rest/*      → **腾讯云 CloudBase 网关（未迁移）**，ECS Caddy 仅做同源反代")
    else:
        print("  /v1/rdb/rest/*      → 未识别上游（请人工确认）")
    print("  /v1/rdb/rest-next/* → 127.0.0.1:3000（ECS PostgREST，staging/影子验证，非生产）")

    print("\n== 三、公网入口（https://tool.furina.fun） ==")
    for p, code_ in data["public"].items():
        print("  %-28s HTTP %s" % (p, code_))

    print("\n== 四、外部依赖（CloudBase / OSS / 本机） ==")
    print("  1) 腾讯云 CloudBase：生产数据 API 与三个定时任务已于 2026-11-28 迁到 ECS；仅函数本体与旧库保留到 2026-12-10 到期")
    print("  2) 静态站发布源：OSS 香港（sync_tools 上传 → ECS apply 拉取）；PPT 媒体与 APK 亦在 OSS 香港")
    print("  3) 本机 Windows：通知采集/构建/AI 质检、PPT 转换（PowerPoint COM）、教务抓取、诊断 agent、看门狗")
    print("  4) 小程序订阅消息：微信云开发（独立 env，不随 CloudBase 到期）；openid 与发送仍依赖 wx.cloud")
    print("  5) 旧版客户端：未升级的小程序/安卓/鸿蒙/Windows 仍直连 CloudBase 网关，2026-12-10 后失效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
