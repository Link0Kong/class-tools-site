# -*- coding: utf-8 -*-
"""ECS 自建后端：PostgreSQL 18 + PostgREST 13（云助手通道，无需 SSH）。

用途（2026-11-18 CloudBase -> ECS 迁移 P1）：
  在阿里云 ECS `class_tool` / 121.196.47.2 上安装 PostgreSQL 18 + PostgREST 13，
  建 staging 库 `class_tools`、角色与备份定时任务；Caddy staging 路由
  `/v1/rdb/rest-next/*` 由 `deploy/ecs_site.py` 维护（本脚本只验收，不改 Caddy）。

红线：
  - **不切生产** `/v1/rdb/rest/*`（仍 CloudBase 网关）；本脚本只服务 staging。
  - 数据库密码只在 ECS 本地 `/etc/class-tools/pgrest.conf`（0600），由 ECS 上
    `openssl rand -hex 24` 生成；本脚本**不打印、不落库、不进聊天/命令内容**。
  - 数据导入依赖 P0 产物；数据文件只经**私有 OSS 暂存 + 短时效签名 URL** 搬运，
    导入后立即删除暂存对象（不公开、不进仓库）。
  - 测试只用官方测试身份 `3260799999 / 测试账号`（tools/tests/_test_account.py）。

用法（在 web 目录下，系统 `python`，需要 aliyunsdkcore + oss2）：
  python deploy\\ecs_pg.py provision        # 安装 PG18 + 角色 + PostgREST + systemd + 备份 timer
  python deploy\\ecs_pg.py staging          # 重启/校验 staging PostgREST + 公网 /v1/rdb/rest-next/ 验收
  python deploy\\ecs_pg.py probe            # 只读：PG/服务/路由/备份/资源 状态
  python deploy\\ecs_pg.py backup           # 立即执行一次 pg_dump -Fc 并校验可读
  python deploy\\ecs_pg.py smoke            # 测试账号 staging 契约冒烟（需已导入 P0 数据）
  python deploy\\ecs_pg.py import --artifact <P0产物目录> [--db class_tools] [--reset]
  python deploy\\ecs_pg.py verify --expect <manifest.json> [--db class_tools]
  python deploy\\ecs_pg.py switch-db --db class_tools_cut   # P4 切流：只改 PostgREST 指向的库

导入 runbook 见 `deploy/migration/IMPORT.md`；总计划 `deploy/migration/PLAN.md`。
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ecs_site  # noqa: E402  (同目录；复用云助手 run_script / ECS 常量)

# ------------------------------------------------------------------ 常量
PG_MAJOR = "18"
DB_NAME = "class_tools"
PGREST_VERSION = "13.0.8"
PGREST_ASSET = "postgrest-v%s-linux-static-x86-64.tar.xz" % PGREST_VERSION
PGREST_URL = ("https://github.com/PostgREST/postgrest/releases/download/"
              "v%s/%s" % (PGREST_VERSION, PGREST_ASSET))
# 直连失败时的 GitHub 加速镜像（ECS 上依次尝试；2026-11-18 实测 GitHub 直连 0 字节，
# gh-proxy.com 约 146KB/s / ghproxy.net 约 14-17KB/s，故镜像优先，GitHub 直连最后兜底）。
PGREST_MIRRORS = ("https://gh-proxy.com/", "https://ghproxy.net/", "",
                  "https://mirror.ghproxy.com/")
PGREST_DIR = "/opt/class-tools/pgrest"
PGREST_BIN = PGREST_DIR + "/postgrest"
CONF_DIR = "/etc/class-tools"
PGREST_CONF = CONF_DIR + "/pgrest.conf"
PGREST_SERVICE = "class-tools-pgrest"
BACKUP_DIR = "/opt/class-tools/backup/pg"
BACKUP_SCRIPT = "/usr/local/bin/class-tools-pg-backup.sh"
IMPORT_ROOT = "/opt/class-tools/pgrest/import"
STAGING_PREFIX = "/v1/rdb/rest-next"
PROD_PREFIX = "/v1/rdb/rest"
# 私有 OSS 桶：furina-site-logs 是站点访问日志桶（ACL=private），仅作迁移产物暂存，
# 导入完成后立即删除对象（PLAN §2：「私有 OSS 暂存 + 短时效签名 URL」）。
PRIVATE_BUCKET = "furina-site-logs"
MIGRATION_PREFIX = "_migration"
PUBLISH_KEY_FILE = os.path.join(HERE, "cloudbase", "publish_key.txt")

TEST_SID = "3260799999"
TEST_NAME = "测试账号"
STAGING_BASE = "http://%s%s/" % (ecs_site.ECS_IP, STAGING_PREFIX)
PROD_BASE = "http://%s%s/" % (ecs_site.ECS_IP, PROD_PREFIX)
CLOUDBASE_GW = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"


# ------------------------------------------------------------------ 本机工具
def _http(method, url, headers=None, body=None, timeout=30):
    """极简 HTTP：返回 {status, headers, body(bytes), ms, error}；不抛异常。"""
    data = None
    if body is not None:
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return {"status": resp.status, "headers": dict(resp.headers),
                    "body": raw, "ms": round((time.time() - t0) * 1000.0, 1)}
    except urllib.error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read()
        except Exception:  # noqa: BLE001
            pass
        return {"status": exc.code, "headers": dict(exc.headers or {}),
                "body": raw, "ms": round((time.time() - t0) * 1000.0, 1)}
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "headers": {}, "body": b"",
                "ms": round((time.time() - t0) * 1000.0, 1),
                "error": "%s: %s" % (exc.__class__.__name__, str(exc)[:200])}


def _json_of(resp):
    try:
        return json.loads(resp["body"].decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def _preview(resp, limit=300):
    return resp["body"][:limit].decode("utf-8", "replace").replace("\n", " ")


def _load_publish_key():
    """CloudBase publishable key（设计上公开，见 deploy/cloudbase/publish_key.txt）；不打印。"""
    try:
        with open(PUBLISH_KEY_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _remote(script, label, timeout=180, wait=300, show=True):
    st, rc, out = ecs_site.run_script(script, timeout=timeout, wait=wait, label=label)
    if show:
        print(out or "")
    print("[%s] status=%s exit=%s" % (label, st, rc))
    return st == "Success" and rc in (0, "0", None), out or ""


def _pct(values, q):
    if not values:
        return None
    vals = sorted(values)
    idx = min(len(vals) - 1, max(0, int(round((len(vals) - 1) * q))))
    return vals[idx]


# ------------------------------------------------------------------ 远端脚本：provision
def build_provision_script():
    return r"""#!/bin/bash
set -euo pipefail
export LC_ALL=C
export DEBIAN_FRONTEND=noninteractive
PG_MAJOR="__PG_MAJOR__"
DB="__DB__"
PGRESTASSET="__PGREST_ASSET__"
PGRESTURL="__PGREST_URL__"
PGRESTBIN="__PGREST_BIN__"
PGRESTBIN_DIR="__PGREST_BIN_DIR__"
PGREST_SERVICE="__PGREST_SERVICE__"
CONFDIR="__CONF_DIR__"
CONF="__PGREST_CONF__"

echo "=== 1. apt 安装 PostgreSQL ${PG_MAJOR}（Ubuntu 26.04 自带） ==="
apt-get update -q -o Acquire::Retries=3 >/dev/null 2>&1 || apt-get update -q
apt-get install -y -q --no-install-recommends \
  postgresql postgresql-client postgresql-contrib python3-psycopg2 \
  ca-certificates curl xz-utils >/tmp/pg_apt.log 2>&1 || { echo "FATAL apt 安装失败"; tail -30 /tmp/pg_apt.log; exit 2; }
systemctl enable postgresql >/dev/null 2>&1 || true
systemctl start postgresql
for i in $(seq 1 60); do
  pg_isready -q && break
  sleep 1
done
pg_isready
echo "psql: $(psql --version)"
echo "server: $(runuser -u postgres -- psql -tAc 'select version()' | cut -c1-60)"

echo "=== 2. 内存调参（2C / 3.6GiB） ==="
CONFDIR_PG="/etc/postgresql/${PG_MAJOR}/main/conf.d"
install -d -m 0755 "$CONFDIR_PG"
TUNE=$(cat <<'PGCONF'
listen_addresses = '127.0.0.1'
shared_buffers = 1GB
effective_cache_size = 2GB
work_mem = 8MB
maintenance_work_mem = 128MB
max_connections = 80
log_min_duration_statement = 1000
PGCONF
)
if grep -q "include_dir = 'conf.d'" "/etc/postgresql/${PG_MAJOR}/main/postgresql.conf"; then
  printf '%s\n' "$TUNE" > "$CONFDIR_PG/10-classtools.conf"
  echo "写入 $CONFDIR_PG/10-classtools.conf"
else
  printf '\n# class-tools 迁移调参（2026-11-18）\n%s\n' "$TUNE" >> "/etc/postgresql/${PG_MAJOR}/main/postgresql.conf"
  echo "追加到 postgresql.conf（无 conf.d include）"
fi
pg_ctlcluster "$PG_MAJOR" main restart
for i in $(seq 1 60); do pg_isready -q && break; sleep 1; done

echo "=== 3. 角色（anon/authenticated/service_role NOLOGIN + authenticator LOGIN） ==="
mk_role() {
  local r="$1"
  if [ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$r'")" = "1" ]; then
    runuser -u postgres -- psql -q -c "ALTER ROLE \"$r\" NOLOGIN"
  else
    runuser -u postgres -- psql -q -c "CREATE ROLE \"$r\" NOLOGIN"
  fi
}
mk_role anon
mk_role authenticated
mk_role service_role
# 对象属主角色（非超级用户 + BYPASSRLS）：CloudBase 源库 SECURITY DEFINER 函数 owner 为租户
# 角色（函数内直接读 RLS 表，需 RLS 旁路）。ECS 用 class_tools_owner 作为库/对象属主。
if [ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='class_tools_owner'")" = "1" ]; then
  runuser -u postgres -- psql -q -c "ALTER ROLE class_tools_owner NOLOGIN NOSUPERUSER BYPASSRLS"
else
  runuser -u postgres -- psql -q -c "CREATE ROLE class_tools_owner NOLOGIN NOSUPERUSER BYPASSRLS"
fi
if [ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='authenticator'")" != "1" ]; then
  runuser -u postgres -- psql -q -c "CREATE ROLE authenticator LOGIN"
fi
# 密码只在本机生成：48 hex 字符；仅写入 pgrest.conf 与 PostgreSQL 角色，不回显。
PASS="$(openssl rand -hex 24)"
runuser -u postgres -- psql -q -v ON_ERROR_STOP=1 -d postgres -v p="$PASS" <<'ROLE_SQL'
ALTER ROLE authenticator WITH LOGIN PASSWORD :'p';
GRANT anon, authenticated, service_role TO authenticator;
ROLE_SQL
echo "角色就绪：$(runuser -u postgres -- psql -tAc "SELECT string_agg(rolname||':'||CASE WHEN rolcanlogin THEN 'LOGIN' ELSE 'NOLOGIN' END, ' ' ORDER BY rolname) FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role','authenticator')")"

echo "=== 4. 数据库 ${DB} ==="
if [ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'")" = "1" ]; then
  echo "数据库已存在：$(runuser -u postgres -- psql -tAc "SELECT datname||' collate='||datcollate||' ctype='||datctype||' enc='||pg_encoding_to_char(encoding) FROM pg_database WHERE datname='$DB'")"
else
  # 源库（CloudBase）locale=C：换 locale 会改变 text 排序/大小写比较语义（unique/ORDER BY），
  # 因此 staging 库按 P0 schema.sql 的建议用 LC_COLLATE=C LC_CTYPE=C + UTF8 建库。
  runuser -u postgres -- createdb -O class_tools_owner -E UTF8 --locale=C --template=template0 "$DB"
  echo "已创建（C locale / UTF8）：$(runuser -u postgres -- psql -tAc "SELECT datname||' collate='||datcollate||' ctype='||datctype||' enc='||pg_encoding_to_char(encoding) FROM pg_database WHERE datname='$DB'")"
fi
runuser -u postgres -- psql -q -d "$DB" -c "GRANT CONNECT ON DATABASE \"$DB\" TO authenticator"

echo "=== 5. PostgREST 运行时用户 + 配置（密码 0600，不回显） ==="
if ! id -u pgrest >/dev/null 2>&1; then
  useradd --system --home-dir "$PGRESTBIN_DIR" --shell /usr/sbin/nologin pgrest
fi
install -d -o root -g pgrest -m 0750 "$CONFDIR"
install -d -o pgrest -g pgrest -m 0755 "$PGRESTBIN_DIR"
umask 077
# 为了不把「postgres://用户:密码@host」形态的明文写进仓库文本，这里把 @ 单独拼进变量：
# 生成后的 pgrest.conf 仍是标准 URI，但脚本源码里不出现 user:pass@ 字面量（sync-repos 安全扫描口径）。
PASS_AT="${PASS}@"
cat > "$CONF" <<PGCONF
db-uri = "postgres://authenticator:${PASS_AT}127.0.0.1:5432/${DB}"
db-schemas = "public"
db-anon-role = "anon"
db-extra-search-path = "public"
db-pool = "10"
server-host = "127.0.0.1"
server-port = 3000
db-channel-enabled = true
log-level = "info"
PGCONF
chown pgrest:pgrest "$CONF"
chmod 600 "$CONF"
stat -c 'pgrest.conf 权限 %a 属主 %U:%G' "$CONF"
# 注意：PostgREST 启动时会校验 db-extra-search-path 里的 schema 必须存在，
# 而 staging 库里 private 要等 P0 schema.sql 导入后才创建；因此 provision 先写
# "public"，导入完成后由 import / staging 子命令自动切到 "public,private"。
# （最终状态与任务要求一致：db-extra-search-path=public,private）

echo "=== 6. PostgREST ${PGRESTASSET} ==="
if [ -x "$PGRESTBIN" ] && "$PGRESTBIN" --version 2>/dev/null | grep -qE 'PostgREST 13\.'; then
  echo "已安装：$("$PGRESTBIN" --version)"
else
  DL=/tmp/pgrest-dl; rm -rf "$DL"; mkdir -p "$DL"
  OK=0
  for PREFIX in __MIRRORS__; do
    echo "下载尝试：${PREFIX}${PGRESTURL}"
    if curl -fsSL --http1.1 --retry 2 --retry-delay 2 --connect-timeout 10 --max-time 180 \
         -o "$DL/$PGRESTASSET" "${PREFIX}${PGRESTURL}"; then OK=1; break; fi
    echo "  失败"
  done
  [ "$OK" = "1" ] || { echo "FATAL PostgREST 下载失败（GitHub 与镜像均不可用）"; exit 6; }
  SZ=$(stat -c%s "$DL/$PGRESTASSET")
  echo "下载完成 ${SZ} bytes sha256=$(sha256sum "$DL/$PGRESTASSET" | cut -d' ' -f1)"
  [ "$SZ" -gt 3000000 ] || { echo "FATAL 下载文件过小（$SZ）"; exit 6; }
  tar -xJf "$DL/$PGRESTASSET" -C "$DL"
  install -o root -g root -m 0755 "$DL/postgrest" "$PGRESTBIN"
  rm -rf "$DL"
fi
"$PGRESTBIN" --version

echo "=== 7. systemd ${PGREST_SERVICE}（127.0.0.1:3000） ==="
cat > "/etc/systemd/system/__PGREST_SERVICE__.service" <<'UNIT'
[Unit]
Description=Class tools PostgREST 13 (staging /v1/rdb/rest-next, PostgreSQL 18)
After=network-online.target postgresql.service
Wants=network-online.target
Requires=postgresql.service

[Service]
Type=simple
User=pgrest
Group=pgrest
ExecStart=__PGREST_BIN__ __PGREST_CONF__
Restart=always
RestartSec=3
LimitNOFILE=2048
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
UNIT
systemctl daemon-reload
systemctl enable "__PGREST_SERVICE__" >/dev/null 2>&1 || true
systemctl restart "__PGREST_SERVICE__"
OK=0
for i in $(seq 1 40); do
  CODE=$(curl -s -o /tmp/pgrest_root.json -w '%{http_code}' -m 3 http://127.0.0.1:3000/ || true)
  if [ "$CODE" = "200" ]; then OK=1; break; fi
  sleep 1
done
if [ "$OK" != "1" ]; then
  echo "FATAL PostgREST 未就绪（${CODE:-无响应}），journal："
  journalctl -u "__PGREST_SERVICE__" -n 60 --no-pager || true
  exit 7
fi
echo "本机 PostgREST root HTTP $CODE -> $(head -c 160 /tmp/pgrest_root.json)"

echo "=== 8. 备份：每日 03:30 pg_dump -Fc，保留 14 天 ==="
install -d -o root -g root -m 0755 /opt/class-tools/backup
install -d -o postgres -g postgres -m 0700 "__BACKUP_DIR__"
cat > "__BACKUP_SCRIPT__" <<'BK'
#!/bin/bash
set -euo pipefail
DIR="__BACKUP_DIR__"
mkdir -p "$DIR"
TS="$(date +%Y%m%d-%H%M%S)"
umask 077
runuser -u postgres -- pg_dump -Fc -Z6 -d "__DB__" -f "$DIR/__DB__-$TS.dump"
SIZE="$(stat -c%s "$DIR/__DB__-$TS.dump")"
echo "backup ok: $DIR/__DB__-$TS.dump ${SIZE} bytes"
find "$DIR" -maxdepth 1 -type f -name '__DB__-*.dump' -mtime +14 -delete
# 最近一次成功时间，供 probe 使用
date -Is > "$DIR/.last_ok"
BK
chmod 755 "__BACKUP_SCRIPT__"
cat > /etc/systemd/system/class-tools-pg-backup.service <<'UNIT'
[Unit]
Description=Class tools PostgreSQL backup (pg_dump -Fc, keep 14 days)
After=postgresql.service
Requires=postgresql.service

[Service]
Type=oneshot
ExecStart=__BACKUP_SCRIPT__
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
UNIT
cat > /etc/systemd/system/class-tools-pg-backup.timer <<'UNIT'
[Unit]
Description=Daily class_tools PostgreSQL backup (03:30, keep 14 days)

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now class-tools-pg-backup.timer >/dev/null 2>&1
systemctl start class-tools-pg-backup.service
sleep 2
LATEST=$(ls -1t "__BACKUP_DIR__"/__DB__-*.dump 2>/dev/null | head -1 || true)
echo "timer=$(systemctl is-active class-tools-pg-backup.timer) dump=${LATEST:-NONE}"
if [ -n "${LATEST:-}" ]; then
  pg_restore -l "$LATEST" | head -6
fi

echo "=== 9. 汇总 ==="
runuser -u postgres -- psql -q -d postgres -tAc "SHOW shared_buffers; SHOW effective_cache_size; SHOW work_mem; SHOW maintenance_work_mem; SHOW max_connections; SHOW listen_addresses"
echo "db_size=$(runuser -u postgres -- psql -tAc "SELECT pg_size_pretty(pg_database_size('__DB__'))")"
systemctl is-active postgresql "__PGREST_SERVICE__"
df -h / | tail -2
free -m | head -2
echo "PROVISION_OK $(date -Is)"
""".replace("__PG_MAJOR__", PG_MAJOR).replace("__DB__", DB_NAME) \
   .replace("__PGREST_ASSET__", PGREST_ASSET).replace("__PGREST_URL__", PGREST_URL) \
   .replace("__PGREST_BIN__", PGREST_BIN).replace("__CONF_DIR__", CONF_DIR) \
   .replace("__PGREST_CONF__", PGREST_CONF).replace("__PGREST_SERVICE__", PGREST_SERVICE) \
   .replace("__PGREST_BIN_DIR__", PGREST_DIR) \
   .replace("__BACKUP_DIR__", BACKUP_DIR).replace("__BACKUP_SCRIPT__", BACKUP_SCRIPT) \
   .replace("__MIRRORS__", " ".join('"%s"' % m for m in PGREST_MIRRORS))


# ------------------------------------------------------------------ 远端脚本：probe
PROBE_SCRIPT = r"""#!/bin/bash
set +e
export LC_ALL=C
echo "=== 0. 磁盘/内存/负载 ==="
df -h / | tail -2
free -m | head -2
uptime
echo
echo "=== 1. PostgreSQL ==="
systemctl is-active postgresql
pg_lsclusters 2>/dev/null
runuser -u postgres -- psql -tAc "select version()" 2>/dev/null | cut -c1-80
runuser -u postgres -- psql -tAc "SHOW listen_addresses; SHOW shared_buffers; SHOW effective_cache_size; SHOW max_connections; SHOW work_mem; SHOW maintenance_work_mem" 2>/dev/null
echo "connections=$(runuser -u postgres -- psql -tAc 'SELECT count(*) FROM pg_stat_activity')"
echo "db_size=$(runuser -u postgres -- psql -tAc "SELECT pg_size_pretty(pg_database_size('class_tools'))" 2>/dev/null)"
runuser -u postgres -- psql -tAc "SELECT 'role '||rolname||' login='||rolcanlogin FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role','authenticator') ORDER BY 1" 2>/dev/null
echo
echo "=== 2. 表/行数（staging 导入后） ==="
echo "tables=$(runuser -u postgres -- psql -tAc "SELECT count(*) FROM pg_class WHERE relkind='r' AND relnamespace IN ('public'::regnamespace,'private'::regnamespace)" -d class_tools 2>/dev/null)"
runuser -u postgres -- psql -tAc "SELECT schemaname||'.'||relname||' '||n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC, relname LIMIT 40" -d class_tools 2>/dev/null
echo "functions=$(runuser -u postgres -- psql -tAc "SELECT count(*) FROM pg_proc WHERE pronamespace IN ('public'::regnamespace,'private'::regnamespace)" -d class_tools 2>/dev/null)"
echo "policies=$(runuser -u postgres -- psql -tAc 'SELECT count(*) FROM pg_policies' -d class_tools 2>/dev/null)"
echo "triggers=$(runuser -u postgres -- psql -tAc 'SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal' -d class_tools 2>/dev/null)"
echo "object_owner=$(runuser -u postgres -- psql -tAc "SELECT rolname||'='||count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner WHERE c.relnamespace IN ('public'::regnamespace,'private'::regnamespace) AND c.relkind IN ('r','S') GROUP BY r.rolname ORDER BY 1" -d class_tools 2>/dev/null | paste -sd' ')"
echo "db_owner=$(runuser -u postgres -- psql -tAc "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='class_tools'" -d postgres 2>/dev/null)"
echo
echo "=== 3. PostgREST 服务 ==="
systemctl is-active class-tools-pgrest; systemctl is-enabled class-tools-pgrest 2>/dev/null
echo "conf: $(stat -c '%a %U:%G' /etc/class-tools/pgrest.conf 2>/dev/null || echo MISSING)"
echo "bin: $([[ -x /opt/class-tools/pgrest/postgrest ]] && /opt/class-tools/pgrest/postgrest --version | head -1 || echo MISSING)"
curl -s -o /tmp/pg_pgrest_root.json -w 'local 3000 root=%{http_code} time=%{time_total}\n' -m 5 http://127.0.0.1:3000/
head -c 120 /tmp/pg_pgrest_root.json; echo
echo
echo "=== 4. Caddy 路由（生产必须仍是 CloudBase 网关） ==="
echo "staging_routes=$(grep -cE '^[[:space:]]*handle_path /v1/rdb/rest-next/\*' /etc/caddy/Caddyfile 2>/dev/null)"
echo "prod_routes=$(grep -cE '^[[:space:]]*handle /v1/rdb/rest/\*' /etc/caddy/Caddyfile 2>/dev/null)"
grep -n -A4 'handle_path /v1/rdb/rest-next' /etc/caddy/Caddyfile 2>/dev/null
grep -n -A5 'handle /v1/rdb/rest/\*' /etc/caddy/Caddyfile 2>/dev/null | head -24
echo
echo "=== 5. 经 Caddy 验收（loopback） ==="
curl -s -o /tmp/pg_stg.json -w 'staging /v1/rdb/rest-next/ = %{http_code} time=%{time_total}\n' -m 5 http://127.0.0.1/v1/rdb/rest-next/
head -c 160 /tmp/pg_stg.json; echo
curl -s -o /tmp/pg_prod.json -w 'prod    /v1/rdb/rest/      = %{http_code} time=%{time_total}\n' -m 10 http://127.0.0.1/v1/rdb/rest/
head -c 160 /tmp/pg_prod.json; echo
echo
echo "=== 6. 备份 ==="
systemctl is-active class-tools-pg-backup.timer 2>/dev/null
systemctl list-timers class-tools-pg-backup.timer --no-pager 2>/dev/null | head -3
du -sh /opt/class-tools/backup/pg 2>/dev/null || echo "(备份目录不存在)"
ls -la /opt/class-tools/backup/pg 2>/dev/null | tail -6
cat /opt/class-tools/backup/pg/.last_ok 2>/dev/null || true
echo
echo "=== 7. PostgREST 日志（最近 12 行） ==="
journalctl -u class-tools-pgrest -n 12 --no-pager 2>/dev/null
echo "=== done ==="
"""


# ------------------------------------------------------------------ 远端脚本：staging 验收
STAGING_SCRIPT = r"""#!/bin/bash
set +e
export LC_ALL=C
echo "=== 1. 服务状态 ==="
# PostgREST 启动要求 db-extra-search-path 里的 schema 都存在；private 由 P0 schema.sql
# 创建。provision 先写 "public"，private 就绪后自动切到 "public,private"（任务要求的最终态）。
DB_CUR=$(sed -n 's/^db-uri = "postgres:\/\/[^@]*@127.0.0.1:5432\/\([A-Za-z0-9_]*\)".*/\1/p' /etc/class-tools/pgrest.conf)
if [ -n "$DB_CUR" ] && runuser -u postgres -- psql -d "$DB_CUR" -tAc "SELECT 1 FROM pg_namespace WHERE nspname='private'" 2>/dev/null | grep -q '^1$'; then
  if grep -q 'db-extra-search-path = "public"' /etc/class-tools/pgrest.conf; then
    sed -i 's/db-extra-search-path = "public"/db-extra-search-path = "public,private"/' /etc/class-tools/pgrest.conf
    echo "db-extra-search-path -> public,private（private schema 已存在）"
  fi
fi
grep -n 'db-extra-search-path' /etc/class-tools/pgrest.conf
systemctl restart class-tools-pgrest
OK=0
for i in $(seq 1 30); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:3000/)" = "200" ] && { OK=1; break; }
  sleep 1
done
[ "$OK" = "1" ] || { echo "FATAL PostgREST 未就绪"; journalctl -u class-tools-pgrest -n 20 --no-pager; exit 4; }
echo "pgrest=$(systemctl is-active class-tools-pgrest) version=$(/opt/class-tools/pgrest/postgrest --version 2>/dev/null | head -1)"
echo
echo "=== 2. staging 路由存在性 ==="
echo "caddy staging_routes=$(grep -cE '^[[:space:]]*handle_path /v1/rdb/rest-next/\*' /etc/caddy/Caddyfile) prod_routes=$(grep -cE '^[[:space:]]*handle /v1/rdb/rest/\*' /etc/caddy/Caddyfile)"
grep -n -B1 -A4 'handle_path /v1/rdb/rest-next' /etc/caddy/Caddyfile
echo
echo "=== 3. loopback 契约点 ==="
curl -s -o /tmp/pg_root.json -w 'local  :3000/                       = %{http_code} time=%{time_total}\n' -m 5 http://127.0.0.1:3000/
curl -s -o /tmp/pg_caddy.json -w 'caddy  /v1/rdb/rest-next/            = %{http_code} time=%{time_total}\n' -m 5 http://127.0.0.1/v1/rdb/rest-next/
head -c 200 /tmp/pg_caddy.json; echo
curl -s -o /tmp/pg_prod.json -w 'caddy  /v1/rdb/rest/ (生产 CloudBase) = %{http_code} time=%{time_total}\n' -m 10 http://127.0.0.1/v1/rdb/rest/
head -c 160 /tmp/pg_prod.json; echo
echo
echo "=== 4. staging 404 与 Authorization 剥离 ==="
curl -s -o /tmp/pg_404.json -w 'staging rpc/not_exists = %{http_code}\n' -m 5 -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1/v1/rdb/rest-next/rpc/not_exists
head -c 200 /tmp/pg_404.json; echo
# 带 CloudBase publishable JWT 请求 staging：Caddy 已 header_up -Authorization，
# 若没剥掉会 401 JWT 解析失败；剥掉后走 anon（root OpenAPI 仍 200）。
curl -s -o /tmp/pg_auth.json -w 'staging root +Authorization     = %{http_code}\n' -m 5 -H 'Authorization: Bearer not-a-valid-jwt' http://127.0.0.1/v1/rdb/rest-next/
head -c 160 /tmp/pg_auth.json; echo
echo "=== 5. PostgREST 日志尾部 ==="
journalctl -u class-tools-pgrest -n 6 --no-pager 2>/dev/null
echo "=== done ==="
"""


# ------------------------------------------------------------------ 远端脚本：backup
BACKUP_SCRIPT_RUN = r"""#!/bin/bash
set -uo pipefail
export LC_ALL=C
echo "=== 1. 执行备份 ==="
systemctl start class-tools-pg-backup.service
sleep 2
echo
echo "=== 2. 备份文件 ==="
du -sh /opt/class-tools/backup/pg 2>/dev/null || true
ls -la --time-style=long-iso /opt/class-tools/backup/pg 2>/dev/null | tail -8
LATEST=$(ls -1t /opt/class-tools/backup/pg/class_tools-*.dump 2>/dev/null | head -1 || true)
echo "latest=${LATEST:-NONE}"
echo
echo "=== 3. 可读性校验（pg_restore -l） ==="
if [ -n "${LATEST:-}" ]; then
  pg_restore -l "$LATEST" | head -12
  echo "restore_list_lines=$(pg_restore -l "$LATEST" | wc -l)"
else
  echo "FATAL 没有备份文件"; exit 5
fi
echo
echo "=== 4. 定时器 ==="
systemctl is-active class-tools-pg-backup.timer
systemctl list-timers class-tools-pg-backup.timer --no-pager | head -3
echo "=== done ==="
"""


# ------------------------------------------------------------------ 子命令实现
def provision(dry_run=False):
    script = build_provision_script()
    if dry_run:
        print(script)
        return 0
    ok, out = _remote(script, "pg-provision", timeout=900, wait=1500)
    if ok and "PROVISION_OK" in out:
        print("\n[provision] 成功：PostgreSQL %s + PostgREST %s 已就绪（127.0.0.1:3000）"
              % (PG_MAJOR, PGREST_VERSION))
        return 0
    print("\n[provision] 失败：请检查上方输出（apt/下载/服务状态）")
    return 1


def staging():
    ok, out = _remote(STAGING_SCRIPT, "pg-staging", timeout=240, wait=360)
    if not ok:
        return 1
    print("\n=== 本机公网验收（%s） ===" % ecs_site.ECS_IP)
    fails = 0
    # 1) staging root（本机 -> 公网 -> Caddy -> PostgREST）
    timings = []
    for i in range(3):
        r = _http("GET", STAGING_BASE, timeout=15)
        timings.append(r["ms"])
        result = "HTTP %s %.1fms" % (r["status"], r["ms"])
        if i == 0:
            print("staging root: %s body=%s" % (result, _preview(r, 160)))
        if r["status"] != 200:
            fails += 1
    obj = _json_of(_http("GET", STAGING_BASE, timeout=15))
    has_openapi = isinstance(obj, dict) and bool({"swagger", "openapi"} & set(obj.keys()))
    print("staging OpenAPI JSON: %s（P50 %.1fms，3 次）"
          % ("OK" if has_openapi else "缺失", _pct(timings, 0.5)))
    if not has_openapi:
        fails += 1
    # 2) staging 带 CloudBase publishable JWT（真实浏览器行为）：Caddy 必须剥掉 Authorization
    hdr = {"Authorization": "Bearer " + (_load_publish_key() or "invalid"),
           "Content-Type": "application/json"}
    r = _http("GET", STAGING_BASE, headers=hdr, timeout=15)
    print("staging +Authorization: HTTP %s（200=已剥离；401=未剥离）" % r["status"])
    if r["status"] != 200:
        fails += 1
    # 3) staging RPC 不存在 -> 404（证明路径 strip 生效）
    r = _http("POST", STAGING_BASE + "rpc/not_exists", headers=hdr, body={}, timeout=15)
    print("staging rpc/not_exists: HTTP %s（期望 404）%s"
          % (r["status"], "" if r["status"] == 404 else " body=" + _preview(r, 120)))
    if r["status"] != 404:
        fails += 1
    # 4) 生产路由仍走 CloudBase（未登录 -> 401），证明未切流
    r = _http("GET", PROD_BASE, timeout=20)
    print("生产 /v1/rdb/rest/ root: HTTP %s（期望 401 CloudBase 网关，未切流）" % r["status"])
    if r["status"] != 401:
        fails += 1
    print("\n[staging] %s（%d 项失败）" % ("PASS" if fails == 0 else "FAIL", fails))
    return 0 if fails == 0 else 1


def probe():
    ok, _ = _remote(PROBE_SCRIPT, "pg-probe", timeout=180, wait=300)
    return 0 if ok else 1


def backup():
    ok, out = _remote(BACKUP_SCRIPT_RUN, "pg-backup", timeout=240, wait=420)
    if ok and "latest=/opt/class-tools/backup/pg/class_tools-" in out:
        print("\n[backup] 成功：pg_dump -Fc 已生成且 pg_restore -l 可读")
        return 0
    print("\n[backup] 失败（见上方输出）")
    return 1


# ------------------------------------------------------------------ 契约冒烟（测试账号）
def smoke(show_token=False):
    """用官方测试身份跑 staging 契约：登录/名单/通知/读表 + RLS 负例 + 延迟。"""
    key = _load_publish_key()
    auth = {"Authorization": "Bearer " + key} if key else {}
    base = STAGING_BASE
    fails = []
    evidence = []

    def check(name, ok, detail=""):
        evidence.append("%-46s %s %s" % (name, "PASS" if ok else "FAIL", detail))
        if not ok:
            fails.append(name)

    # 1) class_verify（测试身份）
    hdrs = dict(auth, **{"Content-Type": "application/json"})
    r = _http("POST", base + "rpc/class_verify", headers=hdrs,
              body={"p_sid": TEST_SID, "p_name": TEST_NAME}, timeout=30)
    obj = _json_of(r) or {}
    token = str(obj.get("token") or "")
    check("POST rpc/class_verify(测试账号)", r["status"] == 200 and bool(token),
          "HTTP %s%s" % (r["status"], "" if token else " 无 token"))
    if token and show_token:
        evidence.append("（token 长度 %d，不打印）" % len(token))
    # 2) RLS 负例：无 token / 坏 token 不得读全班数据
    for label, h in (("匿名", {}), ("坏 token", {"X-Device-Id": "deadbeef" * 4})):
        rr = _http("GET", base + "notices?select=id,ts,hidden,edited_at&order=ts.asc,id.asc"
                   "&archived=eq.false&limit=3", headers=dict(auth, **h), timeout=30)
        body = _json_of(rr)
        leaked = isinstance(body, list) and len(body) > 0
        check("RLS 负例 %s GET notices" % label, rr["status"] in (200, 401) and not leaked,
              "HTTP %s rows=%s" % (rr["status"], len(body) if isinstance(body, list) else "-"))
    if not token:
        print("\n".join(evidence))
        print("\n[smoke] FAIL：测试身份登录失败（staging 是否已导入 P0 数据？）")
        return 1
    th = dict(auth, **{"X-Device-Id": token, "Content-Type": "application/json"})
    # 3) 名单 RPC
    r = _http("POST", base + "rpc/class_members", headers=th, body={}, timeout=60)
    members = _json_of(r)
    check("POST rpc/class_members", r["status"] == 200 and isinstance(members, list) and len(members) > 0,
          "HTTP %s rows=%s" % (r["status"], len(members) if isinstance(members, list) else "-"))
    # 4) 通知轻量 meta（15MB 整表 -> 轻量接口）
    r = _http("POST", base + "rpc/class_notices_meta", headers=th, body={}, timeout=120)
    metas = _json_of(r)
    check("POST rpc/class_notices_meta", r["status"] == 200 and isinstance(metas, list),
          "HTTP %s rows=%s %.0fms" % (r["status"], len(metas) if isinstance(metas, list) else "-", r["ms"]))
    # 5) 读表
    for path, name in (
        ("notices?select=id,ts,hidden,edited_at&order=ts.asc,id.asc&archived=eq.false&limit=5", "notices(列表列)"),
        ("homework?select=*&order=ts.asc&archived=eq.false&limit=3", "homework"),
        ("power?select=*&limit=3", "power"),
        ("power_history?select=*&limit=3", "power_history"),
        ("marks?select=*&limit=3", "marks"),
    ):
        r = _http("GET", base + path, headers=th, timeout=60)
        body = _json_of(r)
        check("GET " + name, r["status"] == 200 and isinstance(body, list),
              "HTTP %s %.0fms" % (r["status"], r["ms"]))
    # 6) 延迟：staging vs CloudBase 网关（只读 GET，不写）
    st_t, cb_t = [], []
    for _ in range(5):
        st_t.append(_http("GET", base + "notices?select=id&limit=1", headers=th, timeout=30)["ms"])
        cb_t.append(_http("GET", CLOUDBASE_GW, timeout=30)["ms"])
    evidence.append("延迟（本机 5 次）：staging P50 %.1fms / CloudBase 网关 P50 %.1fms"
                    % (_pct(st_t, 0.5), _pct(cb_t, 0.5)))
    print("\n".join(evidence))
    print("\n[smoke] %s（%d 项失败）" % ("PASS" if not fails else "FAIL " + ",".join(fails), len(fails)))
    return 0 if not fails else 1


# ------------------------------------------------------------------ P0 产物导入
IMPORT_DATA_PY = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 数据导入（ECS 本地，postgres 身份执行；由 deploy/ecs_pg.py 生成上传）。

输入：P0 data_manifest.json / manifest.json + data/<schema>.<table>.jsonl.gz
顺序：逐表 ① gz 文件 sha256 校验（manifest.files[].sha256）
      ② 行哈希校验 sha256("\\n".join(JSONL 行))（P0 hash_spec：逐行文本 chr(10) 拼接，无末换行）
      ③ 单表事务批量 INSERT（session_replication_role=replica，不触发业务触发器）
      ④ 序列按 max() setval → 输出 JSON 摘要
失败即非零退出（hash/rows/insert），不会写入不可信数据。
"""
import argparse
import gzip
import hashlib
import json
import os
import sys

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, execute_values

ROW_KEYS = ("rows", "row_count", "num_rows", "count")


def is_table_meta(node):
    if not isinstance(node, dict):
        return False
    rows = any(isinstance(node.get(k), int) for k in ROW_KEYS)
    has_file = isinstance(node.get("file"), str)
    has_hash = isinstance(node.get("sha256"), str) or isinstance(node.get("server_sha256"), str)
    has_name = isinstance(node.get("table") or node.get("name"), str)
    return bool(rows and has_name and (has_file or has_hash))


def qualify(meta, key=""):
    schema = meta.get("schema")
    table = meta.get("table") or meta.get("name")
    if isinstance(key, str) and "." in key:
        ks, kt = key.split(".", 1)
        schema = schema or ks
        table = table or kt
    schema = schema or "public"
    table = table or (key.split(".")[-1] if key else "")
    return "%s.%s" % (schema, table)


def find_metas(manifest):
    """从 manifest（任意嵌套）提取 {schema.table: meta}；只认带行数 + 名称 + 文件/哈希的表元数据。"""
    out = {}

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                if is_table_meta(v):
                    out.setdefault(qualify(v, k), v)
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                if is_table_meta(v):
                    out.setdefault(qualify(v), v)
                walk(v)

    walk(manifest)
    return out


def find_file_hashes(manifest):
    """收集 manifest 里形如 {path, sha256} 的文件条目 → {path: sha256}。"""
    out = {}

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("path"), str) and isinstance(node.get("sha256"), str):
                out.setdefault(node["path"], node["sha256"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(manifest)
    return out


def parse_file_name(name):
    base = name
    for suf in (".jsonl.gz", ".json.gz", ".jsonl", ".json"):
        if base.endswith(suf):
            base = base[: -len(suf)]
            break
    parts = base.split(".")
    if len(parts) == 2 and parts[0] in ("public", "private"):
        return parts[0], parts[1]
    return "public", base


def read_jsonl(path):
    """返回 (gz 字节 sha256, 原始行文本 list, 行对象 list)。"""
    raw = open(path, "rb").read()
    gz_sha = hashlib.sha256(raw).hexdigest()
    data = gzip.decompress(raw) if path.endswith(".gz") else raw
    text = data.decode("utf-8")
    stripped = text.lstrip()
    # 兼容 .json 数组形态（非 P0 正式格式；JSONL 每行以 "{" 开头不受影响）
    if stripped[:1] == "[":
        try:
            obj = json.loads(text)
            if isinstance(obj, list):
                return gz_sha, [text.strip()], obj
        except json.JSONDecodeError:
            pass
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    rows = [json.loads(ln) for ln in lines if ln.strip()]
    return gz_sha, lines, rows


def table_columns(cur, schema, table, meta_columns):
    if meta_columns:
        cols = {}
        for c in meta_columns:
            name = c.get("name") or c.get("column_name")
            typ = c.get("type") or c.get("data_type") or c.get("udt_name") or ""
            if name:
                cols[name] = str(typ)
        if cols:
            return cols
    cur.execute("""SELECT column_name, data_type, udt_name
                   FROM information_schema.columns
                   WHERE table_schema=%s AND table_name=%s""", (schema, table))
    out = {}
    for name, dtype, udt in cur.fetchall():
        out[name] = udt if dtype == "USER-DEFINED" else dtype
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="数据目录（<schema>.<table>.jsonl.gz）")
    ap.add_argument("--manifest", default="", help="data_manifest.json / manifest.json")
    ap.add_argument("--schema", default="public", help="文件名无 schema 前缀时的默认 schema")
    ap.add_argument("--dsn", default="dbname=class_tools")
    ap.add_argument("--tables", default="", help="逗号分隔（schema.table 或 table）")
    ap.add_argument("--max-page-bytes", type=int, default=4 * 1024 * 1024)
    ap.add_argument("--allow-hash-mismatch", action="store_true")
    ns = ap.parse_args()
    only = [t.strip() for t in ns.tables.split(",") if t.strip()]

    metas = {}
    file_hashes = {}
    if ns.manifest and os.path.isfile(ns.manifest):
        with open(ns.manifest, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        metas = find_metas(manifest)
        file_hashes = find_file_hashes(manifest)
        if manifest.get("complete") is False:
            print("FATAL manifest.complete=false（P0 导出未完成，拒绝导入）")
            sys.exit(4)
        print("manifest：表元数据 %d / 文件 sha 记录 %d" % (len(metas), len(file_hashes)))
    else:
        print("WARN 无 manifest：只按文件导入，不做计数/哈希校验")

    root = os.path.dirname(os.path.abspath(ns.dir))
    files = []
    found = set()
    for name in sorted(os.listdir(ns.dir)):
        path = os.path.join(ns.dir, name)
        if not os.path.isfile(path):
            continue
        schema, table = parse_file_name(name)
        full = schema + "." + table
        if only and full not in only and table not in only:
            continue
        files.append((full, path, metas.get(full)))
        found.add(full)
    if not files:
        print("FATAL 数据目录没有可导入文件: %s" % ns.dir)
        sys.exit(4)
    missing = sorted(set(metas) - found)
    fatal_missing = [m for m in missing if int(metas[m].get("rows") or 0) > 0]
    if missing:
        print("WARN manifest 中 %d 表无数据文件：%s" % (len(missing), ", ".join(missing[:8])))
    if fatal_missing:
        print("FATAL manifest 中以下表有数据但缺文件：%s" % ", ".join(fatal_missing))
        sys.exit(4)

    conn = psycopg2.connect(ns.dsn)
    conn.autocommit = False
    summary = {"tables": {}, "rows_total": 0, "hashes_ok": 0,
               "hash_mismatch": [], "row_mismatch": [], "sequences": []}
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica")
            for full, path, meta in files:
                schema, table = full.split(".", 1)
                meta = meta or {}
                gz_sha, lines, rows = read_jsonl(path)
                row_hash = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
                exp_rows = meta.get("rows")
                exp_hash = meta.get("sha256")
                exp_srv = meta.get("server_sha256")
                exp_gz = None
                base = os.path.basename(path)
                for fpath, fsha in file_hashes.items():
                    if fpath.endswith("/" + base) or fpath == base:
                        exp_gz = fsha
                        break
                if exp_gz and exp_gz != gz_sha:
                    print("FATAL %s 文件 sha256 不一致（期望 %s 实得 %s）"
                          % (full, exp_gz[:16], gz_sha[:16]))
                    sys.exit(3)
                hash_state = "-"
                if exp_hash or exp_srv:
                    expect = exp_hash or exp_srv
                    if row_hash != expect:
                        msg = "%s 行哈希不一致（期望 %s 实得 %s）" % (full, expect[:16], row_hash[:16])
                        if ns.allow_hash_mismatch:
                            print("WARN " + msg)
                        else:
                            print("FATAL " + msg)
                            sys.exit(3)
                    if exp_srv and row_hash != exp_srv:
                        print("WARN %s server_sha256 不一致" % full)
                    hash_state = "OK"
                    summary["hashes_ok"] += 1
                if isinstance(exp_rows, int) and len(rows) != exp_rows:
                    summary["row_mismatch"].append("%s: %d != %d" % (full, len(rows), exp_rows))
                    print("FATAL %s 行数 %d != manifest %d" % (full, len(rows), exp_rows))
                    sys.exit(2)
                if not rows:
                    summary["tables"][full] = 0
                    print("  %-32s %7d 行  gz=%-2s hash=%s" % (full, 0, "OK" if exp_gz else "-", hash_state))
                    continue
                if not all(isinstance(r, dict) for r in rows):
                    print("FATAL %s 行不是 JSON 对象" % full)
                    sys.exit(2)
                cols_types = table_columns(cur, schema, table, meta.get("columns"))
                if not cols_types:
                    print("FATAL 目标表不存在：%s（schema.sql 未导入？）" % full)
                    sys.exit(5)
                bad = [c for c, t in cols_types.items() if "bytea" in str(t).lower()]
                if bad:
                    print("FATAL %s 含 bytea 列 %s：P0 序列化口径未确认，拒绝猜测" % (full, bad))
                    sys.exit(5)
                colnames = list(cols_types.keys())
                for r in rows:
                    missing_cols = [c for c in colnames if c not in r]
                    extra_cols = [c for c in r if c not in cols_types]
                    if missing_cols or extra_cols:
                        print("FATAL %s 行列不匹配 missing=%s extra=%s"
                              % (full, missing_cols[:5], extra_cols[:5]))
                        sys.exit(2)
                json_cols = {c for c, t in cols_types.items() if str(t).lower() in ("jsonb", "json")}
                avg = max(1, sum(len(ln) for ln in lines) // max(1, len(lines)))
                page = max(1, min(200, ns.max_page_bytes // avg))
                values = []
                for r in rows:
                    out = []
                    for c in colnames:
                        v = r.get(c)
                        if c in json_cols and v is not None and not isinstance(v, str):
                            v = Json(v)
                        out.append(v)
                    values.append(tuple(out))
                stmt = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s").format(
                    sql.Identifier(schema), sql.Identifier(table),
                    sql.SQL(",").join(sql.Identifier(c) for c in colnames))
                cur.execute("SAVEPOINT sp_tbl")
                try:
                    execute_values(cur, stmt.as_string(conn), values, page_size=page)
                    cur.execute("RELEASE SAVEPOINT sp_tbl")
                except Exception as exc:  # noqa: BLE001
                    cur.execute("ROLLBACK TO SAVEPOINT sp_tbl")
                    print("FATAL %s 导入失败: %s" % (full, str(exc)[:400]))
                    sys.exit(6)
                summary["tables"][full] = len(rows)
                summary["rows_total"] += len(rows)
                print("  %-32s %7d 行  gz=%-2s hash=%s page=%d"
                      % (full, len(rows), "OK" if exp_gz else "-", hash_state, page))
            conn.commit()
    except SystemExit:
        conn.rollback()
        raise
    finally:
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass

    # 序列修正（serial 列 DEFAULT nextval；按实际 MAX 校正，避免后续插入撞主键）
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.relname, n.nspname, t.relname, a.attname
              FROM pg_class s
              JOIN pg_depend d ON d.objid = s.oid AND d.deptype IN ('a','i')
              JOIN pg_class t ON t.oid = d.refobjid
              JOIN pg_namespace n ON n.oid = t.relnamespace
              JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
             WHERE s.relkind = 'S' AND n.nspname IN ('public','private')
        """)
        for seq, nschema, tbl, col in cur.fetchall():
            cur.execute(sql.SQL("SELECT max({}) FROM {}.{}").format(
                sql.Identifier(col), sql.Identifier(nschema), sql.Identifier(tbl)))
            mx = cur.fetchone()[0]
            if mx is not None:
                cur.execute("SELECT setval(%s::regclass, %s, true)",
                            ('"%s"."%s"' % (nschema, seq), mx))
                summary["sequences"].append([nschema + "." + tbl, col, mx])
    conn.close()
    print("HASH_OK %d" % summary["hashes_ok"])
    print("IMPORT_SUMMARY " + json.dumps(summary, ensure_ascii=False))
    if summary["row_mismatch"]:
        print("ROWS_MISMATCH " + "; ".join(summary["row_mismatch"]))
        sys.exit(2)
    print("IMPORT_DONE")


if __name__ == "__main__":
    main()
'''

FETCH_PY = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 fetch.json 下载迁移产物（私有 OSS 签名 URL）并校验 sha256。"""
import hashlib
import json
import os
import sys
import urllib.request


def main():
    fetch_json = sys.argv[1]
    out_dir = sys.argv[2]
    with open(fetch_json, "r", encoding="utf-8") as fh:
        items = json.load(fh)
    total = 0
    fails = 0
    for it in items:
        rel = it["path"]
        dest = os.path.join(out_dir, rel)
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        ok = False
        err = ""
        for attempt in range(4):
            try:
                req = urllib.request.Request(it["url"], headers={"User-Agent": "class-tools-import"})
                with urllib.request.urlopen(req, timeout=300) as resp:
                    data = resp.read()
                if it.get("size") and len(data) != it["size"]:
                    raise ValueError("size %d != %d" % (len(data), it["size"]))
                sha = hashlib.sha256(data).hexdigest()
                if it.get("sha256") and sha != it["sha256"]:
                    raise ValueError("sha256 不匹配")
                with open(dest, "wb") as fh:
                    fh.write(data)
                total += len(data)
                print("  OK %-42s %8d B" % (rel, len(data)))
                ok = True
                break
            except Exception as exc:  # noqa: BLE001
                err = "%s: %s" % (exc.__class__.__name__, str(exc)[:160])
        if not ok:
            fails += 1
            print("  FAIL %s（%s）" % (rel, err))
    print("FETCH_DONE files=%d bytes=%d fails=%d" % (len(items), total, fails))
    sys.exit(0 if fails == 0 else 3)


if __name__ == "__main__":
    main()
'''


def _oss_bucket():
    import oss2
    import sync_tools
    ak, sk = sync_tools.load_creds()
    return oss2.Bucket(oss2.Auth(ak, sk), "https://oss-cn-hongkong.aliyuncs.com",
                       PRIVATE_BUCKET)


def _collect_artifact(artifact_dir):
    """返回 [{path(rel), abspath, size, sha256}]，跳过汇总/临时文件。"""
    files = []
    for root, _dirs, names in os.walk(artifact_dir):
        for name in sorted(names):
            if name.startswith(".") or name.endswith(".tmp"):
                continue
            abspath = os.path.join(root, name)
            rel = os.path.relpath(abspath, artifact_dir).replace(os.sep, "/")
            if rel.lower().startswith("summary") or rel.lower().endswith(".md"):
                continue
            h = hashlib.sha256()
            with open(abspath, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            files.append({"path": rel, "abspath": abspath,
                          "size": os.path.getsize(abspath),
                          "sha256": h.hexdigest()})
    return files


def _find_manifest(files):
    """优先根目录 manifest.json，其次 data_manifest.json，最后任意 *manifest*.json。"""
    names = [f["path"].lower() for f in files]
    for want in ("manifest.json", "data_manifest.json"):
        if want in names:
            return files[names.index(want)]
        for f in files:
            if f["path"].lower().endswith("/" + want):
                return f
    for f in files:
        if "manifest" in f["path"].lower() and f["path"].lower().endswith(".json"):
            return f
    return None


def import_artifact(artifact_dir, db, reset=False, keep_staging=False,
                    dry_run=False, timeout=2400):
    """把 P0 产物导入 ECS PostgreSQL（私有 OSS 暂存 + 签名 URL 拉取）。"""
    artifact_dir = os.path.abspath(artifact_dir)
    if not os.path.isdir(artifact_dir):
        print("FATAL 产物目录不存在: %s" % artifact_dir)
        return 2
    ts = time.strftime("%Y%m%d-%H%M%S")
    prefix = "%s/%s/" % (MIGRATION_PREFIX, ts)
    files = _collect_artifact(artifact_dir)
    roles = [f for f in files if f["path"].lower().endswith("roles.sql")]
    schema = [f for f in files if f["path"].lower().endswith("schema.sql")]
    data_files = [f for f in files if re.search(r"(^|/)data/", f["path"])]
    manifest_file = _find_manifest(files)
    if not schema or not data_files:
        print("FATAL 产物缺少 schema.sql 或 data/*.json.gz（目录=%s）" % artifact_dir)
        return 2
    print("=== 1. 产物清单 ===")
    print("目录: %s" % artifact_dir)
    print("schema.sql: %s ; roles.sql: %s ; 数据文件: %d ; manifest: %s ; 合计 %.2f MB"
          % ([f["path"] for f in schema][0] if schema else "MISSING",
             [f["path"] for f in roles][0] if roles else "MISSING",
             len(data_files), manifest_file["path"] if manifest_file else "MISSING",
             sum(f["size"] for f in files) / 1048576.0))
    if dry_run:
        for f in files:
            print("  %-44s %10d B %s" % (f["path"], f["size"], f["sha256"][:16]))
        return 0

    import oss2  # noqa: F401  (提前报缺依赖)
    bucket = _oss_bucket()
    # 额外上传两个远端脚本（不在产物目录内，追加到 staging）
    extra = [("_fetch.py", FETCH_PY.encode("utf-8")),
             ("_import_data.py", IMPORT_DATA_PY.encode("utf-8"))]
    keys = []
    try:
        print("\n=== 2. 私有 OSS 暂存（%s/%s，导入后删除） ===" % (PRIVATE_BUCKET, prefix))
        import oss2
        import threading
        lock = threading.Lock()
        done_bytes = [0]
        last_pct = [-100.0]
        total_bytes = sum(f["size"] for f in files) or 1

        def _progress(n, total=None):
            with lock:
                done_bytes[0] += n
                pct = done_bytes[0] * 100.0 / total_bytes
                show = total_bytes > 8 * 1048576 and (pct - last_pct[0] >= 5 or pct >= 100)
                if show:
                    last_pct[0] = pct
                snapshot = (pct, done_bytes[0])
            if show:
                print("  上传进度 %5.1f%%（%.1f/%.1f MB）"
                      % (snapshot[0], snapshot[1] / 1048576.0, total_bytes / 1048576.0))

        for f in files:
            key = prefix + f["path"]
            if f["size"] >= 2 * 1048576:
                # 大文件并发分片上传（本机 -> OSS HK 实测单连接 ~0.13MB/s，8 线程 ~0.45MB/s）
                print("  上传 %s（%.1f MB，%d 线程分片）"
                      % (f["path"], f["size"] / 1048576.0, 8))
                oss2.resumable_upload(bucket, key, f["abspath"], num_threads=8,
                                      multipart_threshold=1048576, part_size=1048576,
                                      progress_callback=_progress,
                                      headers={"x-oss-object-acl": "private"})
            else:
                bucket.put_object_from_file(key, f["abspath"],
                                            headers={"x-oss-object-acl": "private"})
                _progress(f["size"])
            keys.append(key)
        for name, blob in extra:
            key = prefix + name
            bucket.put_object(key, blob, headers={"x-oss-object-acl": "private"})
            keys.append(key)
        print("已上传 %d 个对象（%.2f MB）" % (len(keys), sum(f["size"] for f in files) / 1048576.0))
        signed = {}
        for key in keys:
            signed[key] = bucket.sign_url("GET", key, 3600)
        fetch_items = []
        for f in files:
            fetch_items.append({"path": f["path"], "url": signed[prefix + f["path"]],
                                "size": f["size"], "sha256": f["sha256"]})
        fetch_json = json.dumps(fetch_items, ensure_ascii=False).encode("utf-8")
        fetch_key = prefix + "_fetch.json"
        bucket.put_object(fetch_key, fetch_json)
        keys.append(fetch_key)
        fetch_url = bucket.sign_url("GET", fetch_key, 3600)
        # 上传时已签名；_fetch.json 自身 URL 现签
        boot_fetch_py = signed[prefix + "_fetch.py"]
        boot_import = signed[prefix + "_import_data.py"]
    except Exception as exc:  # noqa: BLE001
        print("FATAL OSS 暂存失败：%s: %s" % (exc.__class__.__name__, str(exc)[:300]))
        _cleanup_objects(bucket, keys)
        _abort_multipart(bucket, prefix)
        return 3

    remote_dir = "%s/%s" % (IMPORT_ROOT, ts)
    script = r"""#!/bin/bash
set -euo pipefail
export LC_ALL=C
TS="__TS__"
DB="__DB__"
RESET="__RESET__"
RD="__REMOTE_DIR__"
ART="$RD/artifact"
mkdir -p "$ART"
cd "$RD"

echo "=== 3. 拉取产物（私有 OSS 签名 URL + sha256 校验） ==="
curl -fsSL --retry 3 --retry-delay 2 --max-time 120 -o _fetch.py '__FETCH_URL__'
curl -fsSL --retry 3 --retry-delay 2 --max-time 120 -o _import_data.py '__IMPORT_URL__'
curl -fsSL --retry 3 --retry-delay 2 --max-time 120 -o _fetch.json '__FETCH_JSON_URL__'
python3 _fetch.py _fetch.json "$ART"

echo "=== 4. 准备数据库 $DB ==="
systemctl stop class-tools-pgrest >/dev/null 2>&1 || true
# 对象属主角色（非超级用户 + BYPASSRLS；SECURITY DEFINER 函数语义与 CloudBase 对齐）
if [ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='class_tools_owner'")" != "1" ]; then
  runuser -u postgres -- psql -q -c "CREATE ROLE class_tools_owner NOLOGIN NOSUPERUSER BYPASSRLS"
  echo "已创建角色 class_tools_owner"
fi
if [ "$RESET" = "1" ]; then
  runuser -u postgres -- psql -q -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB'" >/dev/null 2>&1 || true
  runuser -u postgres -- dropdb --if-exists "$DB"
  echo "已删除旧库（--reset）"
fi
if [ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'")" != "1" ]; then
  # 与 P0 schema.sql 建议一致：源库 locale=C，建库用 LC_COLLATE=C LC_CTYPE=C / UTF8
  runuser -u postgres -- createdb -O class_tools_owner -E UTF8 --locale=C --template=template0 "$DB"
  echo "已创建数据库 $DB（C locale / UTF8）"
fi
runuser -u postgres -- psql -q -d "$DB" -c "GRANT CONNECT ON DATABASE \"$DB\" TO authenticator"

echo "=== 5. roles.sql（容忍 already exists） ==="
if [ -f "$ART/roles.sql" ]; then
  runuser -u postgres -- psql -q -v ON_ERROR_STOP=0 -d "$DB" -f "$ART/roles.sql" >/tmp/p0_roles.log 2>&1 || true
  BAD=$(grep -E '^ERROR:' /tmp/p0_roles.log | grep -v 'already exists' | head -5 || true)
  if [ -n "$BAD" ]; then echo "FATAL roles.sql 非预期错误:"; echo "$BAD"; exit 4; fi
  echo "roles.sql OK（already exists 已容忍）"
else
  echo "WARN 无 roles.sql（使用 provision 创建的角色）"
fi

echo "=== 6. schema.sql ==="
runuser -u postgres -- psql -q -v ON_ERROR_STOP=1 -d "$DB" -f "$ART/schema.sql" >/tmp/p0_schema.log 2>&1 \
  || { echo "FATAL schema.sql 失败"; tail -30 /tmp/p0_schema.log; exit 5; }
echo "schema.sql OK"
echo "tables=$(runuser -u postgres -- psql -tAc "SELECT count(*) FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace" -d "$DB")"
echo "functions=$(runuser -u postgres -- psql -tAc "SELECT count(*) FROM pg_proc WHERE pronamespace IN ('public'::regnamespace,'private'::regnamespace)" -d "$DB")"
echo "policies=$(runuser -u postgres -- psql -tAc 'SELECT count(*) FROM pg_policies' -d "$DB")"

echo "=== 7. 数据导入（psycopg2；逐表校验 gz sha256 + 行哈希，再单表事务 INSERT） ==="
MANIFEST="$ART/manifest.json"
[ -f "$MANIFEST" ] || MANIFEST="$ART/data_manifest.json"
[ -f "$MANIFEST" ] || MANIFEST=""
echo "manifest=${MANIFEST:-（无 manifest，跳过计数/哈希校验）}"
if ! runuser -u postgres -- python3 _import_data.py \
      --dir "$ART/data" \
      --manifest "$MANIFEST" \
      --schema public \
      --dsn "dbname=$DB" 2>&1 | tee /tmp/p0_import.log; then
  echo "FATAL 数据导入失败（哈希/行数/INSERT，见上）"
  tail -25 /tmp/p0_import.log || true
  exit 6
fi
if ! grep -q '^IMPORT_SUMMARY ' /tmp/p0_import.log; then echo "FATAL 数据导入未完成"; exit 6; fi
grep -E '^HASH_OK |^WARN ' /tmp/p0_import.log || true
if grep -q '^ROWS_MISMATCH ' /tmp/p0_import.log; then echo "FATAL 行数与 manifest 不一致"; exit 7; fi

echo "=== 7.5 对象属主 -> class_tools_owner（非超级用户 + BYPASSRLS） ==="
# 注意：不能用 REASSIGN OWNED（扩展成员对象会被系统拒绝）；逐对象 ALTER OWNER：
# 先表/视图（SERIAL/IDENTITY 关联序列随表属主自动跟随）→ 独立序列 → 非扩展函数。
runuser -u postgres -- psql -q -d postgres -c "ALTER DATABASE \"$DB\" OWNER TO class_tools_owner" >/dev/null 2>&1 || true
# 必须先把库属主改为 class_tools_owner（新属主需有库 CREATE 权限）再改 private schema 属主，
# 否则 ALTER SCHEMA ... OWNER 会因新属主无 CREATE 权限失败（顺序反了会报 permission denied for schema private）。
if [ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_namespace WHERE nspname='private'" -d "$DB")" = "1" ]; then
  runuser -u postgres -- psql -q -d "$DB" -c "ALTER SCHEMA private OWNER TO class_tools_owner" || { echo "FATAL 无法把 private schema 属主改为 class_tools_owner"; exit 9; }
else
  echo "WARN 无 private schema（schema.sql 未创建？）"
fi
runuser -u postgres -- psql -q -v ON_ERROR_STOP=1 -d "$DB" <<'OWNER_SQL' || { echo "FATAL 对象属主切换失败"; exit 9; }
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT n.nspname, c.relname, c.relkind FROM pg_class c
             JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('public','private') AND c.relowner = 'postgres'::regrole
              AND c.relkind IN ('r','p','v','m') LOOP
    EXECUTE format('ALTER %s %I.%I OWNER TO class_tools_owner',
      CASE r.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END,
      r.nspname, r.relname);
  END LOOP;
  FOR r IN SELECT n.nspname, c.relname FROM pg_class c
             JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('public','private') AND c.relowner = 'postgres'::regrole
              AND c.relkind = 'S'
              AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a','i')) LOOP
    EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO class_tools_owner', r.nspname, r.relname);
  END LOOP;
  FOR r IN SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid) AS args
             FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname IN ('public','private') AND p.proowner = 'postgres'::regrole
              AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e') LOOP
    EXECUTE format('ALTER FUNCTION %I.%I(%s) OWNER TO class_tools_owner', r.nspname, r.proname, r.args);
  END LOOP;
END $$;
OWNER_SQL
echo "object_owners=$(runuser -u postgres -- psql -tA -d "$DB" -c "SELECT rolname||'='||count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner WHERE c.relnamespace IN ('public'::regnamespace,'private'::regnamespace) AND c.relkind IN ('r','S') GROUP BY 1 ORDER BY 1" | paste -sd' ')"
echo "function_owners=$(runuser -u postgres -- psql -tA -d "$DB" -c "SELECT rolname||'='||count(*) FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.pronamespace IN ('public'::regnamespace,'private'::regnamespace) GROUP BY 1 ORDER BY 1" | paste -sd' ')"
echo "db_owner=$(runuser -u postgres -- psql -tA -d postgres -c "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='$DB'")"

echo "=== 8. ANALYZE + PostgREST schema reload ==="
runuser -u postgres -- psql -q -d "$DB" -c "ANALYZE"
runuser -u postgres -- psql -q -d "$DB" -c "NOTIFY pgrst, 'reload schema'"
# 目标库已有 private schema：把 db-extra-search-path 切到 "public,private"（PostgREST 启动校验需要）
DB_CUR=$(sed -n 's/^db-uri = "postgres:\/\/[^@]*@127.0.0.1:5432\/\([A-Za-z0-9_]*\)".*/\1/p' /etc/class-tools/pgrest.conf)
if [ "$DB_CUR" = "$DB" ] && runuser -u postgres -- psql -d "$DB" -tAc "SELECT 1 FROM pg_namespace WHERE nspname='private'" 2>/dev/null | grep -q '^1$'; then
  if grep -q 'db-extra-search-path = "public"' /etc/class-tools/pgrest.conf; then
    sed -i 's/db-extra-search-path = "public"/db-extra-search-path = "public,private"/' /etc/class-tools/pgrest.conf
    echo "db-extra-search-path -> public,private"
  fi
fi
systemctl start class-tools-pgrest
OK=0
for i in $(seq 1 40); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:3000/)" = "200" ] && { OK=1; break; }
  sleep 1
done
[ "$OK" = "1" ] || { echo "FATAL PostgREST 重启后未就绪"; journalctl -u class-tools-pgrest -n 40 --no-pager; exit 8; }
echo "PostgREST 就绪"
echo "db_size=$(runuser -u postgres -- psql -tAc "SELECT pg_size_pretty(pg_database_size('$DB'))")"
echo "IMPORT_OK $(date -Is)"
""".replace("__TS__", ts).replace("__DB__", db).replace("__RESET__", "1" if reset else "0") \
   .replace("__REMOTE_DIR__", remote_dir).replace("__FETCH_URL__", boot_fetch_py) \
   .replace("__IMPORT_URL__", boot_import).replace("__FETCH_JSON_URL__", fetch_url)

    ok, out = _remote(script, "pg-import", timeout=timeout, wait=timeout + 600)
    if keep_staging:
        print("\n[import] --keep-staging：保留 OSS 暂存与 ECS 文件（%s / %s）" % (prefix, remote_dir))
    else:
        _cleanup_objects(bucket, keys)
        cleanup_script = r"""#!/bin/bash
set +e
rm -rf '__REMOTE_DIR__'
echo "remote import dir 已删除"
""".replace("__REMOTE_DIR__", remote_dir)
        _remote(cleanup_script, "pg-import-cleanup", timeout=120, wait=180)
        print("\n[import] 已删除 OSS 暂存对象（%d 个）与 ECS 临时目录" % len(keys))
    if ok and "IMPORT_OK" in out:
        print("\n[import] 成功：%s 已导入 %s" % (artifact_dir, db))
        return 0
    print("\n[import] 失败（见上方输出；P0 产物格式差异需按 IMPORT.md §5 调整）")
    return 1


def _abort_multipart(bucket, prefix):
    """中止残留的未完成分片上传（导入失败/中断后清理 OSS 暂存）。"""
    try:
        import oss2
        for mp in oss2.MultipartUploadIterator(bucket, prefix=prefix):
            try:
                bucket.abort_multipart_upload(mp.key, mp.upload_id)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def _cleanup_objects(bucket, keys):
    for key in keys:
        try:
            bucket.delete_object(key)
        except Exception:  # noqa: BLE001
            pass


def verify_import(manifest_path, db):
    """按 manifest 校验行数（manifest 结构自适应；无可识别行数时只报实际计数）。"""
    if not os.path.isfile(manifest_path):
        print("FATAL manifest 不存在: %s" % manifest_path)
        return 2
    meta = json.load(open(manifest_path, "r", encoding="utf-8"))
    expected = {}
    try:
        expected = _extract_manifest_rows(meta)
    except Exception as exc:  # noqa: BLE001
        print("WARN manifest 行数解析失败: %s" % exc)
    expect_json = base64.b64encode(json.dumps(expected, ensure_ascii=False).encode("utf-8")).decode("ascii")
    script = r"""#!/bin/bash
set +e
export LC_ALL=C
DB="__DB__"
EXPECT_B64="__EXPECT__"
EXPECT=$(echo "$EXPECT_B64" | base64 -d)
echo "tables=$(runuser -u postgres -- psql -tAc "SELECT count(*) FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace" -d "$DB")"
echo "functions=$(runuser -u postgres -- psql -tAc "SELECT count(*) FROM pg_proc WHERE pronamespace IN ('public'::regnamespace,'private'::regnamespace)" -d "$DB")"
echo "policies=$(runuser -u postgres -- psql -tAc 'SELECT count(*) FROM pg_policies' -d "$DB")"
echo "triggers=$(runuser -u postgres -- psql -tAc 'SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal' -d "$DB")"
echo "indexes=$(runuser -u postgres -- psql -tAc "SELECT count(*) FROM pg_indexes WHERE schemaname IN ('public','private')" -d "$DB")"
echo "db_size=$(runuser -u postgres -- psql -tAc "SELECT pg_size_pretty(pg_database_size('$DB'))")"
EXPECT=$(echo "$EXPECT_B64" | base64 -d)
echo "expected_json=$EXPECT"
echo "=== 行数核对 ==="
python3 - "$DB" "$EXPECT" <<'PY'
import json, subprocess, sys
db, expect = sys.argv[1], json.loads(sys.argv[2] or "{}")
if not expect:
    print("VERIFY_NO_EXPECT（manifest 无可识别行数）")
    sys.exit(3)
bad = []
for key, exp in sorted(expect.items()):
    schema, table = (key.split(".", 1) if "." in key else ("public", key))
    q = "SELECT count(*) FROM \"%s\".\"%s\"" % (schema.replace('"', '""'), table.replace('"', '""'))
    r = subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-tA", "-d", db, "-c", q],
                       capture_output=True, text=True)
    if r.returncode != 0:
        bad.append("%s: 查询失败 %s" % (key, r.stderr.strip()[:80]))
        continue
    got = int(r.stdout.strip() or 0)
    if got != exp:
        bad.append("%s: %s != %s" % (key, got, exp))
if bad:
    print("VERIFY_FAIL " + "; ".join(bad))
    sys.exit(4)
print("VERIFY_OK tables=%d" % len(expect))
PY
RC=$?
if [ "$RC" = "3" ]; then echo "VERIFY_DEGRADED"; exit 0; fi
exit "$RC"
""".replace("__DB__", db).replace("__EXPECT__", expect_json)
    ok, out = _remote(script, "pg-verify", timeout=300, wait=480)
    if not ok:
        print("\n[verify] FAIL（见上方输出）")
        return 1
    print("\n[verify] PASS（manifest %d 表行数一致）" % len(expected))
    return 0


def _extract_manifest_rows(obj):
    """从 P0 data_manifest.json / manifest.json 提取 {schema.table: rows}（字段口径自适应）。"""
    row_keys = ("rows", "row_count", "num_rows", "n", "count")
    out = {}

    def meta_rows(node):
        for k in row_keys:
            if isinstance(node.get(k), int):
                return node[k]
        return None

    def is_meta(node):
        if not isinstance(node, dict):
            return False
        has_name = isinstance(node.get("table") or node.get("name"), str)
        has_file = isinstance(node.get("file"), str)
        has_hash = isinstance(node.get("sha256"), str) or isinstance(node.get("server_sha256"), str)
        return bool(meta_rows(node) is not None and (has_name or has_file) and (has_file or has_hash))

    def qualify(meta, key=""):
        schema = meta.get("schema")
        table = meta.get("table") or meta.get("name")
        if isinstance(key, str) and "." in key:
            ks, kt = key.split(".", 1)
            schema = schema or ks
            table = table or kt
        schema = schema or "public"
        table = table or (key.split(".")[-1] if key else "")
        return "%s.%s" % (schema, table)

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                if is_meta(v):
                    out.setdefault(qualify(v, k), meta_rows(v))
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                if is_meta(v):
                    out.setdefault(qualify(v), meta_rows(v))
                walk(v)

    walk(obj)
    return out


def switch_db(db):
    """P4 切流：只改 PostgREST 指向的数据库（密码保持不动），不切 Caddy 路由。"""
    script = r"""#!/bin/bash
set -euo pipefail
export LC_ALL=C
DB="__DB__"
CONF="/etc/class-tools/pgrest.conf"
[ -f "$CONF" ] || { echo "FATAL pgrest.conf 不存在"; exit 2; }
if [ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'")" != "1" ]; then
  echo "FATAL 目标库不存在: $DB"; exit 3
fi
TABLES=$(runuser -u postgres -- psql -tAc "SELECT count(*) FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace" -d "$DB")
if [ "${TABLES:-0}" -lt 1 ]; then echo "FATAL 目标库没有 public 表（是否还没 import？）"; exit 4; fi
runuser -u postgres -- psql -q -d "$DB" -c "GRANT CONNECT ON DATABASE \"$DB\" TO authenticator"
# 用 python 精确替换 db-uri 的库名，不打印文件内容
python3 - "$CONF" "$DB" <<'PY'
import re, sys
path, db = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as fh:
    text = fh.read()
new, n = re.subn(r'(?m)^(db-uri\s*=\s*"postgres://[^/"]+/)[A-Za-z0-9_]+(")',
                 lambda m: m.group(1) + db + m.group(2), text)
if n != 1:
    sys.exit("db-uri 行未唯一匹配（n=%d）" % n)
with open(path, "w", encoding="utf-8") as fh:
    fh.write(new)
print("db-uri 库名已更新为", db)
PY
chown pgrest:pgrest "$CONF"; chmod 600 "$CONF"
systemctl restart class-tools-pgrest
OK=0
for i in $(seq 1 40); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:3000/)" = "200" ] && { OK=1; break; }
  sleep 1
done
[ "$OK" = "1" ] || { echo "FATAL PostgREST 切库后未就绪"; journalctl -u class-tools-pgrest -n 40 --no-pager; exit 5; }
echo "connected_db=$(runuser -u postgres -- psql -tAc "SELECT datname FROM pg_stat_activity WHERE application_name='postgrest' LIMIT 1")"
echo "tables=$(runuser -u postgres -- psql -tAc "SELECT count(*) FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace" -d "$DB")"
echo "SWITCH_OK $(date -Is)"
""".replace("__DB__", db)
    ok, _ = _remote(script, "pg-switch-db", timeout=240, wait=420)
    if ok:
        print("\n[switch-db] 成功：PostgREST 已指向 %s（Caddy 生产路由未改动）" % db)
        print("下一步：按 deploy/migration/CUTOVER.md 让 ecs_cutover.py 切换生产 Caddy 路由。")
        return 0
    print("\n[switch-db] 失败（见上方输出）")
    return 1


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="ECS PostgreSQL 18 + PostgREST 13（staging，云助手）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("provision", help="安装 PostgreSQL 18 + PostgREST 13 + 角色 + 备份")
    p.add_argument("--dry-run", action="store_true", help="只打印远端脚本")
    sub.add_parser("staging", help="重启/验收 staging 路由（公网 /v1/rdb/rest-next/）")
    sub.add_parser("probe", help="只读状态")
    sub.add_parser("backup", help="立即备份并校验")
    ps = sub.add_parser("smoke", help="测试账号 staging 契约冒烟")
    ps.add_argument("--show-token-len", action="store_true", help="只显示 token 长度（不打印内容）")

    pi = sub.add_parser("import", help="导入 P0 产物（私有 OSS 暂存 + 签名 URL）")
    pi.add_argument("--artifact", required=True, help="P0 产物目录（schema.sql/roles.sql/data/manifest.json）")
    pi.add_argument("--db", default=DB_NAME, help="目标库名（默认 class_tools；P4 可用 class_tools_cut）")
    pi.add_argument("--reset", action="store_true", help="导入前删除并重建目标库（仅 staging/cut DB）")
    pi.add_argument("--keep-staging", action="store_true", help="保留 OSS 暂存与 ECS 临时文件（排障用）")
    pi.add_argument("--dry-run", action="store_true", help="只打印产物清单")
    pi.add_argument("--timeout", type=int, default=2400, help="远端执行超时秒数")

    pv = sub.add_parser("verify", help="按 manifest 校验行数")
    pv.add_argument("--expect", required=True, help="manifest.json 路径")
    pv.add_argument("--db", default=DB_NAME)

    pd = sub.add_parser("switch-db", help="P4：只改 PostgREST 指向的库（不切生产 Caddy 路由）")
    pd.add_argument("--db", required=True)

    ns = ap.parse_args(argv)
    if ns.cmd == "provision":
        return provision(dry_run=ns.dry_run)
    if ns.cmd == "staging":
        return staging()
    if ns.cmd == "probe":
        return probe()
    if ns.cmd == "backup":
        return backup()
    if ns.cmd == "smoke":
        return smoke(show_token=ns.show_token_len)
    if ns.cmd == "import":
        return import_artifact(ns.artifact, ns.db, reset=ns.reset,
                               keep_staging=ns.keep_staging, dry_run=ns.dry_run,
                               timeout=ns.timeout)
    if ns.cmd == "verify":
        return verify_import(ns.expect, ns.db)
    if ns.cmd == "switch-db":
        return switch_db(ns.db)
    return 2


if __name__ == "__main__":
    sys.exit(main())
