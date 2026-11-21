# P0 产物导入 Runbook（CloudBase → ECS PostgreSQL 18）

> 适用阶段：**P1/P2**（staging 库 `class_tools`）与 **P4**（切流库 `class_tools_cut`）。
> 前置：P0 导出产物就绪（`schema.sql` / `roles.sql` / `data/*.json.gz` / `manifest.json`），
> ECS 已完成 `python deploy\ecs_pg.py provision`（PG18 + PostgREST 13 + 角色 + 备份）。
> 总计划：`deploy/migration/PLAN.md`；切流：`deploy/migration/CUTOVER.md`；
> 部署/运维：`deploy/ecs_pg.py`、`deploy/ECS_DEPLOY.md`。

---

## 1. 红线（导入期间）

1. **CloudBase 只读**：P0 导出完成后不再从 CloudBase 读业务写入；导入目标只能是 ECS 自建库。
2. **数据文件不公开**：P0 产物含班级名单/通知正文等隐私数据，只允许走
   **私有 OSS 桶 `furina-site-logs`（ACL=private）+ 短时效签名 URL** 暂存，导入后**立即删除**；
   不得上传到 `tool-furina-fun`（公共读）、不得进仓库、不得贴到聊天。
3. **密码/密钥**：`pgrest.conf` 的数据库密码由 ECS 本地生成、0600、永不打印；本 runbook 不含任何凭据。
4. **不切生产路由**：导入与验收只走 staging `/v1/rdb/rest-next/`；生产 `/v1/rdb/rest/*` 保持 CloudBase 网关，直到 P4。
5. **测试只用测试账号**：`3260799999 / 测试账号`（见 `tools/tests/_test_account.py`），不得用真实账号/真实 token。

## 2. 产物要求（P0 交付格式）

```text
<产物目录>/
  roles.sql                  # anon / authenticated / service_role（NOLOGIN，幂等）
  schema.sql                 # CREATE SCHEMA private / 扩展 / 序列 / 表 / 函数 / 约束 / 索引
                             #   / RLS ENABLE / 触发器 / 策略 / 授权 / 序列 setval
  schema_manifest.json       # 结构计数 / structure_checks（P0 export_schema）
  data_manifest.json         # 数据清单（P0 export_data）：kind/complete/tables/files/totals
  manifest.json              # （可选）合并后的总 manifest；没有时自动用 data_manifest.json
  data/<schema>.<table>.jsonl.gz   # 每表一个 JSONL（每行 = row_to_json(t)::text 原文）
  SUMMARY.md                 # 可选（导入时跳过）
```

`data_manifest.json` 关键字段（已实测 `_test` 产物）：

| 字段 | 含义 |
|---|---|
| `complete` | `true` 才允许导入（`false` 直接拒绝） |
| `tables` | 字典，键 = `"schema.table"`；值含 `rows` / `sha256`（行哈希）/ `server_sha256`（源库重算）/ `columns[]` / `file` |
| `files` | 列表：`{path, bytes, sha256, rows}`；`sha256` = **gz 文件字节**哈希 |
| `settings.hash_spec` | `sha256( 逐行文本 chr(10) 拼接 )`（**无末尾换行**；= `sha256("\n".join(lines))`） |
| `settings.row_encoding` | JSONL，每行 `row_to_json` 原文（UTF-8） |

- 导入器会**逐表先校验**：gz 文件 sha256 == `files[].sha256`、行哈希 == `tables.*.sha256`、
  行数 == `rows`，三项全过后才 INSERT；任一不一致即整体非零退出（不写不可信数据）。
- 列类型（P0 schema 实测）：`text/integer/bigint/boolean/numeric(p,s)/jsonb/date/timestamptz`，
  无 `bytea`/数组列；`jsonb` 自动包装，时间/数值按文本参数由 PG 转换。
- 数据文件与 `schema.sql` 的 sha256/字节数会在上传/拉取两端校验（`fetch.json` 记录）。
- **数据库 locale**：源库 CloudBase 为 `LC_COLLATE=C / LC_CTYPE=C / UTF8`（见 `schema.sql` 注释）。
  `provision` 与 `import` 建库时均使用 `createdb -E UTF8 --locale=C --template=template0`，
  避免换 locale 改变 text 排序/大小写比较语义（unique 约束 / ORDER BY 行为）。
- **`db-extra-search-path` 时序**：PostgREST 启动时会校验该配置里的 schema 都存在；
  `private` 由 `schema.sql` 创建，因此 `provision` 先写 `public`，`import` 建好 `private` 后
  自动切到 `public,private` 并重启 PostgREST（任务要求的最终态）。手动排查时
  `python deploy\ecs_pg.py staging` 会自动完成该切换。
- **对象属主（重要）**：CloudBase 源库的 `SECURITY DEFINER` 函数 owner 是租户角色，函数内部**直接
  SELECT/写 RLS 表**（如 `class_notices_meta()` 读 `public.notices`），说明源 owner 具备 RLS 旁路。
  ECS 侧因此创建 **`class_tools_owner`（NOLOGIN / NOSUPERUSER / BYPASSRLS）**，让 `class_tools`
  库与全部 public/private 对象归它所有；`SECURITY DEFINER` 函数以该角色运行 —— 既不是超级用户，
  又与源库语义一致。**若属主错误地保留为 `postgres`（超级用户）或换成无 BYPASSRLS 角色**，
  前者权限过大、后者会让 `class_notices_meta` 等函数读不到 RLS 表（返回空），务必按本 runbook 执行。

## 2.1 已实测（2026-11-18，PG 18.6）

- `roles.sql` + `schema.sql` 已在临时库（C locale）完整导入通过：**34 表 / 89 函数 / 73 策略 /
  2 触发器 / 60 索引 / 4 序列 / private schema / pgcrypto**；`auth_hdr()`、`class_verify(text,text)`、
  `class_members()` 等关键函数存在。临时库导入后已删除（未污染 staging）。

## 3. 一次导入（staging）

```powershell
# 0) 前置（若还没做过）：ECS 安装 PG18 + PostgREST + 角色 + 备份 timer
python deploy\ecs_pg.py provision

# 1) 干跑：只列产物清单，不上传
python deploy\ecs_pg.py import --artifact C:\briefdesk\data\cloudbase_migration\<ts> --dry-run

# 2) 正式导入（默认目标库 class_tools；--reset 用于重导，会删库重建）
python deploy\ecs_pg.py import --artifact C:\briefdesk\data\cloudbase_migration\<ts> --reset

# 3) 行数校验（与 manifest 对比；优先 manifest.json，没有则用 data_manifest.json）
python deploy\ecs_pg.py verify --expect C:\briefdesk\data\cloudbase_migration\<ts>\manifest.json

# 4) staging 契约冒烟（测试账号：登录→名单→通知 meta→读表→RLS 负例→延迟）
python deploy\ecs_pg.py smoke

# 5) 公网 staging 路由验收（Caddy -> PostgREST，且生产路由仍是 CloudBase）
python deploy\ecs_pg.py staging
```

执行内容（`import` 子命令内部顺序）：

| 步 | 动作 | 失败处理 |
|---|---|---|
| 1 | 本机收集产物（sha256/大小），跳过 `*.md`/隐藏文件 | 目录/必需文件缺失 → 退出码 2 |
| 2 | 上传到私有 OSS `furina-site-logs/_migration/<ts>/…`，生成 1h 签名 URL + `fetch.json` + 远端脚本 | OSS 失败 → 清理已上传对象后退出 |
| 3 | ECS 拉取到 `/opt/class-tools/pgrest/import/<ts>/artifact/`，逐文件校验 size+sha256 | 任何文件失败 → `FETCH_DONE fails>0`，退出 |
| 4 | `--reset` 时停止 PostgREST → 终止连接 → `dropdb`/`createdb`；否则缺库则创建；`GRANT CONNECT TO authenticator` | SQL 失败 → 输出 psql 日志 |
| 5 | `psql -f roles.sql`（`ON_ERROR_STOP=0`，只容忍 `already exists`；其余 ERROR 即失败） | 非预期错误 → 退出码 4 |
| 6 | `psql -v ON_ERROR_STOP=1 -f schema.sql`，打印表/函数/策略计数 | 任意错误 → 退出码 5 |
| 6.5 | **对象属主切换**：`ALTER SCHEMA private OWNER → class_tools_owner`、`ALTER DATABASE … OWNER → class_tools_owner`、`REASSIGN OWNED BY postgres TO class_tools_owner`（失败时按表/序列/函数/视图逐个 `ALTER … OWNER`） | 打印 `object_owners` / `db_owner` |
| 7 | `python3 _import_data.py`：逐表**先校验** gz 文件 sha256 + 行哈希 + 行数，全过后单表事务 INSERT（`session_replication_role=replica` 不触发业务触发器）；序列按 `max()` setval | 校验/插入失败 → 整表回滚并退出码 3/2/6 |
| 8 | `ANALYZE` + `NOTIFY pgrst, 'reload schema'` + 重启 PostgREST，健康检查 200 | 未就绪 → 打印 journal 退出码 8 |
| 9 | 成功：`IMPORT_OK`；行数与 manifest 不一致 → 退出码 7 | — |
| 10 | 默认删除 OSS 暂存对象 + ECS 临时目录（`--keep-staging` 保留排障） | — |

> 事务策略：**逐表提交**（表内单事务；某表失败不影响已提交表，重导建议 `--reset` 从零开始，避免半成品）。

## 4. 导入后验收（P2 门禁）

1. `python deploy\ecs_pg.py verify --expect …\manifest.json` → `VERIFY_OK tables=N`（行数 34/34 一致）。
2. `python deploy\ecs_pg.py smoke` → 全 PASS，含：
   - `rpc/class_verify` 测试账号登录（token 不打印）；
   - `rpc/class_members`、`rpc/class_notices_meta`、`notices/homework/power/power_history/marks` 读表；
   - RLS 负例：匿名/坏 token 读 `notices` 不下发数据；
   - 延迟：本机 → staging P50 对比 CloudBase 网关 P50。
3. `python deploy\ecs_pg.py staging` → staging root 200/OpenAPI、`rpc/not_exists` 404、带 JWT 请求 200（**Authorization 已被 Caddy 剥掉**）、生产 `/v1/rdb/rest/` 仍 401（CloudBase 未切流）。
4. `python deploy\ecs_pg.py probe` → PG 参数/角色/服务/备份/Caddy 路由计数（`staging_routes=3`、`prod_routes=3`）。
5. 网页 staging 真实验证（Lead/前端）：`https://tool.furina.fun/?api=next` 用测试账号登录（`tools/index.html` 内置 `?api=next` 切到 staging）。

### 4.1 接口/行为差异排查清单

| 症状 | 常见原因 | 处理 |
|---|---|---|
| `PGRST106` / `schema cache` 报错 | `db-schemas` 与库不一致 | 检查 `pgrest.conf` 的 `db-schemas="public"`、`db-extra-search-path="public,private"`；`NOTIFY pgrst, 'reload schema'` |
| 登录返回 401/空 | JWT 未被剥离（直连 3000 或旧 Caddy） | 只通过 `/v1/rdb/rest-next/` 访问；Caddy 需 `header_up -Authorization` |
| RPC 404 | schema.sql 未建函数 / 未 reload | `psql -c "NOTIFY pgrst, 'reload schema'"`，再 `probe` 看 functions 计数 |
| 写入 401 `new row violates…` 或 returning 失败 | `Prefer: return=representation` 新行不可读（与 CloudBase 同语义） | 前端已用 `cbPostNoRep`；不是迁移问题 |
| 行数不一致 | 导出分页漏行 / 导入序列中断 | 重跑 `verify`；必要时重新导出并 `--reset` 重导 |
| 中文乱码 | 数据库/客户端编码 | `class_tools` 默认 UTF8；`psql -v client_encoding=UTF8` |
| 慢查询 | 缺索引/未 ANALYZE | 导入已 `ANALYZE`；确认 schema.sql 含索引，必要时按 PLAN §6.7 补 |

## 5. 性能测量口径（P2 报告）

- **本机 → staging**（经公网 Caddy）：`staging root` / 读表 RTT（`ecs_pg.py smoke` 的 P50）。
- **ECS loopback → PostgREST**：`python deploy\ecs_pg.py staging` 输出的 `local :3000/`、`caddy /v1/rdb/rest-next/` 耗时。
- **对比 CloudBase 网关**：`smoke` 里对 `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/` 根路径的只读 GET P50（不写）。
- 目标（PLAN §6.1）：本机→ECS API P50 < 30ms（CloudBase 80–120ms）；同源后无 CORS。

## 6. manifest 兼容说明（P0 格式可能微调）

`import_data.py` / `verify` 的元数据提取器支持（已实测 P0 `data_manifest.json`）：

- `{"tables": {"schema.table": {"rows": N, "file": "...jsonl.gz", "sha256": "..."}}}`（P0 当前格式）；
- `{"data": [{"table": "notices", "schema": "public", "rows": N}]}` / 任意嵌套的
  `{"table/name/relname/table_name": "…", "rows": N}`；
- `import` 优先 `manifest.json`，缺失自动回退 `data_manifest.json`；`verify --expect` 两者都接受；
- 若传入的是只有结构计数的 `schema_manifest.json`：`verify` 输出 `VERIFY_DEGRADED`
  （仍打印实际表/函数/策略/触发器/索引计数），行数以导入日志 `IMPORT_SUMMARY` 为准。
- **哈希校验在 `import` 阶段完成**（gz 文件 sha + 行哈希 + 行数，见 §2）；`verify` 只做行数对比
  （逐表 count 与 manifest 计划保持一致）。

## 7. 回滚

### 7.1 staging（P1/P2）

```bash
# ECS 上（云助手执行或 deploy/ecs_pg.py 扩展）：停服务
systemctl disable --now class-tools-pgrest
# Caddy staging 路由回滚：从 deploy/ecs_site.py 去掉 handle_path /v1/rdb/rest-next/* 后
python deploy\ecs_site.py apply   # 生产 /v1/rdb/rest/* 不受影响
# 数据回滚：dropdb class_tools（新库，无生产数据）
```
> 备份目录 `/opt/class-tools/backup/pg/` 保留 14 天，可 `pg_restore -d class_tools <dump>` 恢复。

### 7.2 P4 切流后

- Caddy 路由回退：`python deploy\ecs_cutover.py rollback`（把 `/v1/rdb/rest/*` 指回 CloudBase 网关；CloudBase 保留 ≥2 周）。
- PostgREST 库回退：`python deploy\ecs_pg.py switch-db --db class_tools`。
- 数据不会自动合并回 CloudBase；切流窗口内新写入按 `CUTOVER.md §3` 人工补偿。

## 8. 导入状态（本文件维护）

| 时间 | 阶段 | 结果 |
|---|---|---|
| 2026-11-18 13:39 | P1 provision | PG **18.6** + PostgREST **13.0.8** 就绪（127.0.0.1:3000）；角色/库（C locale）/备份 timer 就绪；`provision` 幂等重跑通过 |
| 2026-11-18 13:41 | P1 staging 路由 | `deploy/ecs_site.py apply` 生效：`handle_path /v1/rdb/rest-next/*`（域名块 + IP `:80` 块）；公网 `https://tool.furina.fun/v1/rdb/rest-next/` = 200 OpenAPI；`rpc/not_exists` = 404；带 JWT 请求 = 200（Authorization 已剥离）；生产 `/v1/rdb/rest/` = 401（仍 CloudBase，未切流） |
| 2026-11-18 13:42 | P0 schema 导入自测 | `roles.sql`+`schema.sql` 在临时库（C locale）导入通过：34 表/89 函数/73 策略/2 触发器/60 索引/4 序列；临时库已删 |
| 2026-11-18 14:07 | **P0 数据导入（最终版）** | 产物 `20261118-1337`（41.05MB）经私有 OSS → ECS：**34/34 表、19,341 行导入成功**；`HASH_OK 34`（gz sha + 行哈希 34/34 一致）、`row_mismatch=[]`；序列 setval：hw_bindings=5 / power_history=9417 / push_tokens=17；`db-extra-search-path → public,private`；对象属主 `class_tools_owner` |
| 2026-11-18 14:08 | 行数校验 | `verify --expect manifest.json` → **VERIFY_OK tables=34**；库内计数 34 表/89 函数/73 策略/2 触发器/60 索引，db_size 72MB |
| 2026-11-18 14:09 | 测试账号契约冒烟 | **smoke 全 PASS**：class_verify 200、RLS 负例（匿名/坏 token notices = 0 行）、class_members 70、class_notices_meta 125 行/313KB、notices/homework/power/power_history/marks 读表全 200 |
| 2026-11-18 14:12 | 备份 + 恢复演练 | `pg_dump -Fc` 42.8MB（397 TOC）；`pg_restore` 到临时库：34 表/19,344 行/notices 184 行/89 函数/73 策略，0 warning；临时库已删 |
| 2026-11-18 14:14 | 生产路由复核 | 当前 Caddyfile vs 部署前备份：仅新增 16 行 staging 路由（0 删除）；`/v1/rdb/rest/*` 块内容 sha256 **相同**；ECS index.html sha 未变（610a39dc…） |

### 8.1 P1 实测性能（2026-11-18，staging）

| 场景 | 操作 | P50 |
|---|---|---:|
| ECS loopback（Caddy→PostgREST→PG） | class_members（7.3KB） | **2.9 ms** |
| 同上 | notices 列表列（9.2KB） | 6.4 ms |
| 同上 | homework / power / site_assets.tt | 2.5–2.8 ms |
| 同上 | marks（1KB） | 4.4 ms |
| 同上 | power_history `limit=2000`（222KB） | 40.2 ms |
| 同上 | class_notices_meta（313KB，25MB body 轻量化） | 235 ms |
| 本机 → staging（公网） | class_members | 39.8 ms |
| 本机 → staging（公网） | notices 列表列 / power / marks | 42–57 ms |
| 本机 → staging（公网） | class_notices_meta | 358 ms |
| 本机 → CloudBase 网关（同形 tiny POST） | 401 vs staging 404 | **76.4 ms vs 60.3 ms**（ECS 快 ~21%） |

- PostgreSQL：`shared_buffers=1GB / effective_cache_size=2GB / work_mem=8MB / maintenance_work_mem=128MB / max_connections=80 / listen_addresses=127.0.0.1`；连接数 11（db-pool=10 + 探活）。
- PostgREST 进程 RSS ≈ 38MB / CPU 0.7%；ECS 内存可用 ≈ 2.7GiB；磁盘 `/` 用 8.1G/40G。
- 首屏 `class_notices_meta` 的 235ms 主要来自 25MB 通知 body 的轻量化扫描；切流后如仍偏慢，可加派生列/物化缓存（P5 优化项）。

| 2026-11-18 14:20–14:34 | P4 演练 | 全新快照导入 `class_tools_cut`（4.5min/72MB/HASH_OK 34）→ VERIFY_OK 34 → apply-sql → switch-db → smoke（members 70/meta sha 一致/延迟 87ms）→ 切回 staging |

## 9. 已知限制（如实）

1. 导入按「逐表单事务」提交；中途失败不自动回滚已提交表，重导请用 `--reset` 从零开始。
2. `bytea` 列导入显式拒绝（P0 序列化口径未确认，不猜测；当前 schema 无 bytea/数组列）。
3. 哈希以 P0 `hash_spec`（逐行 chr(10) 拼接）实现并在 import 阶段强校验；未重算 `server_sha256` 之外的额外规范化。
4. 导入期间 PostgREST 会短暂停机（秒级~分钟级）；仅 staging。
5. 数据文件经私有 OSS 中转（本机→OSS 实测上行 0.13MB/s 单连接；8 线程分片约 0.45MB/s，41MB 约 2 分钟）；ECS→OSS 0.5–2.5MB/s。
6. 备份为单机 `pg_dump -Fc`（42.8MB/14 天保留），未做异地容灾；P5 再评估。
7. staging 内测试账号登录会新增 `private.class_sessions` 行（每次 +1），属预期；P4 切流用全新导出快照。
