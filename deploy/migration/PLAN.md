# CloudBase → ECS 自建后端迁移 · 总计划（2026-11-18）

> 目标：把班级工具站后端从腾讯云 CloudBase（2026-12-10 到期）迁到阿里云 ECS 自建
> **PostgreSQL 18 + PostgREST**，API 路径继续用 `/v1/rdb/rest/`，三端尽量零改代码即可切流；
> 同时利用本地后端把各端体验做一轮优化。
> 本文件是唯一计划入口；执行记录追加到 §7「执行日志」。

## 1. 现状（2026-11-18 13:1x 实测）

| 项 | 值 |
|---|---|
| ECS | `class_tool` / `121.196.47.2`，2 vCPU / **3.6 GiB 可用内存** / 40 GB ESSD / 出峰值 **100 Mbps**，Ubuntu 26.04，Caddy 2.6.2 |
| ECS 现有服务 | board 8090、附件 8091、PPT 文件缓存 8092、drop 8093、账号 8094、地图 8095（全部 127.0.0.1 + Caddy 路由） |
| CloudBase | env `tool-d4gosudok46e0e081`，**2026-12-10 23:59:59 到期**；PG **17.11**；`tcb` CLI 已登录，`tcb db execute --json` 可执行只读 SQL |
| CloudBase 数据 | 库 42 MB；public **29 表**、private **5 表**；**88 个函数**（36 SECURITY DEFINER）、**71 条策略（全部 TO anon）**；`notices` 184 行/25.4 MB（单行最大 2.0 MB）、`class_sessions` 8,326 行 |
| 客户端 | 网页：ECS `http://121.196.47.2/`（备案前仅 IP 调试），`var CB` 运行时同源 `/v1/rdb/rest/`（当前 Caddy 反代 CloudBase）；小程序/安卓：仍直连 CloudBase 网关（`https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/`） |
| 备案 | `tool.furina.fun` 仍 NXDOMAIN，**ICP 未通过** → 小程序/安卓正式版无法切到自建域名（它们不接受 http/IP） |

## 2. 目标架构

```
浏览器/小程序/安卓
   │  https://tool.furina.fun/v1/rdb/rest/…   （备案后；现在网页走 http://121.196.47.2/ 同源）
   ▼
Caddy (:80/:443, gzip/zstd, 静态站, /att /pptfiles /drop /account /map)
   │  handle_path /v1/rdb/rest/*  → 127.0.0.1:3000   （切换时只改这一条）
   ▼
PostgREST 13（本地，db-anon-role=anon，去掉 Authorization）
   ▼
PostgreSQL 18（class_tools 库：public 29 表 + private 5 表，88 函数、71 策略、序列/触发器/索引全部按线上导出）
```

- **角色**：`anon` / `authenticated` / `service_role`（NOLOGIN，按线上 ACL 授权）+ `authenticator`（PostgREST 登录用）。
- **RLS/鉴权**：函数与策略原样迁移；`auth_hdr()` 读 PostgREST 的 `request.headers`，与 CloudBase 行为一致。
- **Authorization**：三端仍会带 CloudBase publishable JWT；PostgREST 无法验签 → Caddy 在自建路由上 `header_up -Authorization` 剥掉（RLS 靠 `X-Device-Id`/`X-Class-Token` 头，本来就是设计口径）。
- **CloudBase 只读**：迁移期间所有导出只读；切换前不写、不删。
- **数据搬运**：本地导出 → 私有 OSS 暂存（短时效签名 URL）→ ECS 拉取导入 → 立即删对象；数据文件不进仓库、不放公开桶。

## 3. 阶段与门禁

| 阶段 | 内容 | 门禁 |
|---|---|---|
| P0 导出 | 全量 schema（DDL/函数/策略/触发器/索引/授权/序列）+ 数据（34 表）导出与自校验 | 只读 CloudBase；计数/哈希一致 |
| P1 搭建 | ECS 安装 PostgreSQL 18 + PostgREST 13 + systemd + 备份；导入 P0 产物 | 不触碰生产 Caddy 路由 |
| P2 影子验证 | 新路由 **`/v1/rdb/rest-next/*`**（仅 staging）→ 本地 PostgREST；用**测试账号**跑 RPC/RLS/契约回归 + 性能测量 | 生产 `/v1/rdb/rest/*` 仍走 CloudBase |
| P3 客户端就绪 | 网页（零改动）、小程序/安卓 base URL 化 + 优化；备案前只能 devtools/调试构建连 staging | 三端测试全绿 |
| P4 切流 | 备案通过 + 域名恢复后：最终增量导出 → 一次性切 `/v1/rdb/rest/*` 到本地；三端发布；CloudBase 停用 | 用户确认窗口；有回滚脚本 |
| P5 收尾 | 关 CloudBase 云函数/定时器、退订；ECS 监控/备份巡检 | — |

> **为什么不能现在直接切小程序/安卓**：备案未通过，`tool.furina.fun` 无解析/无 HTTPS；小程序与安卓正式版都不允许 http/IP。
> 网页现在只通过 IP 调试入口使用，切到本地会与小程序/安卓（仍 CloudBase）产生**双后端数据分叉**，因此 P4 统一切换；
> P0–P3 只做「只读导出 + staging 验证 + 客户端代码就绪」。

## 4. 数据导出策略（P0）

- SQL 通道：`tcb.cmd db execute --json --sql "<只读 SQL>"`（返回 `data.Rows`，每行是 JSON 文本数组）；默认角色可读 public/private（只读）。
- 结构：从 `pg_catalog`/`information_schema` 生成：
  - `roles.sql`：anon/authenticated/service_role/authenticator（本地集群角色）+ schema USAGE
  - `schema.sql`：CREATE SCHEMA private → 扩展（pgcrypto in public）→ 序列 → 表（列/默认值/identity）→ 约束 → 索引 → RLS 开关 → 函数（`pg_get_functiondef`，`set check_function_bodies=false`）→ 触发器 → 策略（`pg_policy` + `pg_get_expr`）→ 授权（`information_schema.role_*_grants`）→ 序列 setval
- 数据：逐表按主键分页导出 JSON（bigserial/文本 PK；复合 PK 用 ROW 比较；无 PK 用 ctid），gzip；`data_manifest.json` 记录行数 + 规范化 sha256。
- 大表：`notices`（25.4 MB，行最大 2 MB）按 `id` 分页；`power_history`/`class_sessions`/`visits` 等也分页。
- 自校验：导出后重新统计每表 count + 哈希，与 manifest 对齐；结构对象计数与 catalog 对齐。

## 5. 运行时要点（P1/P2）

- PostgreSQL 18（Ubuntu 26.04 自带 18+290ubuntu1）；内存调参：`shared_buffers=1GB`、`effective_cache_size=2GB`、`work_mem=8MB`、`max_connections=80`、`maintenance_work_mem=128MB`。
- PostgREST 13 static binary（GitHub release；ECS 已实测可访问 github.com，失败时用镜像）→ systemd `class-tools-pgrest.service`（127.0.0.1:3000，`db-anon-role=anon`，`db-schemas=public`，`db-extra-search-path=public,private`）。
- Caddy staging 路由：`handle_path /v1/rdb/rest-next/* { reverse_proxy 127.0.0.1:3000 { header_up -Authorization } }`（临时生产不变；P4 时把 `/v1/rdb/rest/*` 指到同一 upstream 并删 next）。
- 备份：每日 `pg_dump -Fc` 到 `/opt/class-tools/backup/pg/`，保留 14 天 + 每周一份到私有 OSS（可选）；`/etc/cron.d` 或 systemd timer。
- 监控：`/opt/class-tools/pg_monitor.py` 或复用 health rows（`service_health.id='cloudbase'` 改为探本地）；磁盘/连接数/慢查询阈值。

## 6. 体验优化清单（P2–P4 落地）

1. **API 延迟**：CloudBase 网关（本地→腾讯上海约 80–120 ms）→ ECS 同源（约 5–20 ms），登录/通知/投票/抽签全链路提速。
2. **同源/无 CORS**：网页已同源；小程序/安卓切到 `tool.furina.fun` 后同域。
3. **HTTP/2 + 更优压缩**：备案后 Caddy 自动 HTTPS 即启用 HTTP/2；静态已 gzip/zstd（当前 index 1.34 MB → 414 KB）。
4. **PPT 媒体本地缓存**：`ppt/a/**`（WebP/MP4）目前仍走 OSS 香港（跨境 2–4 s 握手）；新增 `/pptmedia/*` ECS 反代+磁盘 LRU，三端把 manifest 媒体 URL 映射到本地缓存（网页同源；小程序/安卓用域名）。
5. **通知列表**：已做 lite meta + 按需 body（15 MB → ~0.3 MB）；本地后端后进一步保持。
6. **PPT 下载**：已有 `/pptfiles` ECS 缓存（实测 5–9 MB/s）。
7. **数据库索引**：对 notices(archived,ts)、power_history(roomverify,ts)、poll_votes(poll_id)、visits(ts)、marks(seat,kind) 等热查询补索引（以线上已有索引为准，缺的补）。
8. **小程序/安卓网络层**：HTTP/2 连接复用、超时/重试、图片缓存；去掉跨云端点。
9. **静态站**：备案后 HTTP/2 + 长缓存；必要时升级 Caddy 3 支持 brotli（评估稳定性后再做）。

## 7. 执行日志

- 2026-11-18 13:10–13:20：现状盘点与可行性验证（`tcb db execute --json` 只读 SQL 可用；ECS 升级为 2C4G/100Mbps；OpenAPI 25 表 53 RPC、catalog 34 表/88 函数/73 策略；压缩/健康检查基线）。本计划建立。
- 2026-11-18 13:20–14:30（P0）：`deploy/migration/{tcb_sql,export_schema,export_data,verify_export}.py` 完成；全量导出产物 `C:\briefdesk\data\cloudbase_migration\20261118-1337`：34 表/19,341 行/40.7MiB（gz），schema.sql 762 语句（34 表/270 列/52 自有函数+pgcrypto/73 策略/2 业务触发器/60 索引/4 序列），verify 36/36+15/15+34/34 全绿。
- 2026-11-18 13:30–14:20（P1）：ECS 装 PostgreSQL 18.6（C locale，`class_tools` 72MB）+ PostgREST 13.0.8（127.0.0.1:3000，anon/authenticator 角色，class_tools_owner BYPASSRLS 属主），每日 pg_dump 备份 timer；数据经私有 OSS 暂存导入，**HASH_OK 34/34、VERIFY_OK tables=34**，pg_restore 演练 0 warning；staging 路由 `/v1/rdb/rest-next/*`（生产 `/v1/rdb/rest/*` 未动）。
- 2026-11-18 14:00–14:30（P3）：本机管线 `cloud_backend.py` env 覆盖（17 路径；默认 CloudBase 行为不变）、ECS 云函数替代 timer（已安装、disabled）、`web/jwxt/tt_cloud.py`+`ppt/agent.py` env 覆盖；小程序/安卓三档 base 配置 + 网络层优化（mp unit 591/0、安卓 1594/0、`verifyReleaseEndpoints` 通过）；staging 冒烟：mp devtools 9/9、安卓 StagingSmokeTest、pipeline staging 26/26、ECS timer health_probe/power_sync smoke ok。
- 2026-11-18 14:20–14:45（P2 影子验证）：网页 `?api=next` 真实浏览器 E2E **10/10**（身份门禁/测试账号登录/9 个 staging 请求、0 生产 CloudBase 请求、members=70/meta=125、0 JS 报错，API P50 30ms）；网页已部署 OSS+ECS（1,335,602B/`36be5b2d…`，生产默认行为不变）。staging 后端数据/契约/RLS/性能由 ecs-pg 独立复核通过。
- 当前状态：**P0/P1/P2/P3 就绪，P4 切流待 ICP 备案 + 域名恢复**（mp/安卓正式版不能走 http/IP）。切流步骤见 `CUTOVER.md`。

## 8. 第二轮进展（2026-11-18 15:xx，P4 工具与优化）

- **P4 切换工具**：`deploy/ecs_cutover.py`（status / validate / switch --to selfhosted|cloudbase，`--confirm` 才执行；
  远端备份 Caddyfile → validate → reload → 公网复核）+ `ecs_site.py` 新增 `CLASS_API_MODE` 生成生产路由；
  `validate` 已用远端临时文件验证 selfhosted/cloudbase 两种 Caddy 配置均 `Valid configuration`（active 未动）。
- **通知列表优化**：`deploy/migration/2026-11-18_notice_meta_lite.sql`（trigger 预计算 + RPC JOIN），
  staging 实测输出 sha 与旧实现**逐字节一致**（125 行 / 313819B / `20a0346a…`），延迟 **221–250ms → 75–95ms**；
  `ecs_pg.py apply-sql` 支持导入后应用（P4 切流步骤已写入 CUTOVER.md）。
- **P4 演练（2026-11-18 14:20–14:34，已完成）**：全新快照 `cutover-dryrun-20261118-1424`（schema 30s + 数据 139s + verify 70s，40.7MiB；drift 仅 class_sessions/agent_keys/diag_analysis 预期 live 写入）→
  `import --db class_tools_cut --reset`（4.5 分钟，72MB，HASH_OK 34/34）→ `verify` **tables=34 OK** →
  `apply-sql` notice_meta_lite → `switch-db class_tools_cut` → 测试账号 smoke：members 70（3.6ms）、notices meta **sha 20a0346a… 与旧实现逐字节一致 / 125 行**、延迟 **87ms**、RLS 负例 `[]`；
  生产公网 `/v1/rdb/rest/` 仍 401（CloudBase 未动）→ `switch-db class_tools` 切回 staging。
  结论：P4 切流全链路可在 5 分钟内完成；切流窗口按 CUTOVER.md §1 执行（最终快照重跑一次）。

## 9. 第二轮优化（2026-11-18 goal round 2）

- **通知 meta 二级缓存**：`deploy/migration/2026-11-18_notice_meta_cache.sql`（表 `private.notice_meta_cache` + 语句级触发器重建 + RPC 纯读）。
  staging 实测：**6–9ms**（此前预计算版 87ms；最初 221–250ms），输出 sha `20a0346a…` 不变；任何 notices 写语句触发一次重建（INSERT 约 +90ms），GET/POST 均可读（避免只读事务写表问题）。
- **PPT 在线媒体本地缓存**：复用现有 `/pptfiles` ECS 缓存（WebP/MP4 支持 Range/206、LRU 5GiB），网页 `resolveMediaUrl()` 把 OSS `/ppt/**` 媒体映射到 `/pptfiles`；
  真实浏览器 E2E `deploy/migration/e2e_ppt_media.py` **10/10**：播放器 16 个媒体请求全部走 `/pptfiles`、0 个 OSS 直连、视频 readyState=4、0 JS 报错。
  同时修复 `PPT.hrefOf` 因 files 缓存缺 base 导致大屏「打开放映」指向 `oss/.../compat.pptx` 的既有问题（`cacheFiles(..., base)` + `filesOf()._base`）。
- **测试修复**：`v2_ppt_check` 两处既有静态断言（TOOLS 文案变化、`js_static` 只取第一个 `<script>`）已修；PPT 套件 **92/92 + 100/100 + 65/65**、`v2_ui_check` 27/27。
- 网页已部署 OSS+ECS：`1,336,988B / sha256 0fee…`（以部署输出为准）；备份 `tools/_backup/index_online_*_prePptMediaCache.html`。
- 待办：小程序/安卓的在线预览媒体同样映射到 `https://tool.furina.fun/pptfiles`（备案发布时）；切流窗口执行时应用两个优化 SQL。

### 9.1 后端监控与异地备份（2026-11-18 round 3）

- `deploy/ecs_pg.py monitor`：只读检查 PG/PostgREST/备份年龄/磁盘/连接数/staging 路由/生产模式；
  已安装 systemd timer `class-tools-pg-monitor.timer`（每 10 分钟），日志 `/var/log/class-tools-pg-monitor.log`，失败时 service 状态 success/failed 可被 `systemctl`/巡检发现。当前实测 `MONITOR_OK`（备份 0h、磁盘 23%、连接 15）。
- `deploy/ecs_pg.py offsite --keep 8`：把最新 `pg_dump` 经短签名 PUT URL 上传到**私有 OSS** `furina-site-logs/pg-backup/`（ECS 不存 AK/SK；本机 head_object 校验大小；保留 8 份）。首次实测 42,831,353B 上传成功。
- 压缩验收：Caddy 对自建 API 响应启用 zstd/gzip（`notices meta` 313,819B → gzip 62,294B / zstd 61,854B，约 -80%），三端弱网收益明显。
- 备注：offsite 为手动/周度命令（不由 ECS 自行调度，避免在 ECS 存长期凭据）；建议每周跑一次并记录在巡检表。
