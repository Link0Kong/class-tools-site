# 切流 Runbook：CloudBase → ECS 自建后端（P4）

> 前置：P0 导出、P1 ECS PG/PostgREST、P2 staging 验证、P3 客户端/管线就绪。
> **本文件由 Lead 执行；任何一步失败按 §7 回滚。**
> 关键约束：迁移窗口内 CloudBase 保持在线（回滚依赖它）；测试只用测试账号；数据文件走私有 OSS + 短签名 URL。

## 0. 前置检查（切流前一天）

- [ ] staging `/v1/rdb/rest-next/` 合同回归全绿（RPC/RLS/读写/性能），且用测试账号在网页 `?api=next` 真实登录成功。
- [ ] 小程序/安卓新版已构建并（备案后）可在真机/开发工具连 `https://tool.furina.fun/v1/rdb/rest/` 或 staging。
- [ ] `tool.furina.fun` 备案已通过、DNS 已恢复、ECS HTTPS 已启用（`deploy/ecs_site.py apply --https`），证书有效。
- [ ] 本机管线环境变量已就绪（`CLASS_CB_BASE` 切换脚本/说明），ECS 云函数替代 timer 已部署但**未启用**。
- [ ] 最新全量导出产物 + `verify_export` 全绿；ECS 备份任务在跑；CloudBase 仍在线。

## 1. 切流窗口（建议 5–10 分钟，低峰；提前在群里通知）

> **推荐用编排命令**（2026-11-18 已演练）：
> `python deploy\migration\cutover_run.py rehearsal --artifact <快照目录> --skip-snapshot`（安全演练）
> `python deploy\migration\cutover_run.py execute --artifact <快照目录> --skip-snapshot --confirm-cutover`（真正切流）
> `python deploy\migration\cutover_run.py rollback --confirm`（回滚）。
> 下面 §1 是等价的手工步骤（编排失败时按手工回退）。

1. **宣布冻结**：请在班群/任意入口通知「接下来 5 分钟别提交作业/投票/抽签」。
2. **最终快照**（CloudBase 只读）：
   ```
   cd C:\Users\Ko_Li\.openclaw\workspace\web
   python deploy\migration\export_schema.py --out C:\briefdesk\data\cloudbase_migration\cutover
   python deploy\migration\export_data.py  --out C:\briefdesk\data\cloudbase_migration\cutover
   python deploy\migration\verify_export.py --dir C:\briefdesk\data\cloudbase_migration\cutover
   ```
3. **导入到 `class_tools_cut`（全新库，不影响 staging）**：
   ```
   python deploy\ecs_pg.py import --db class_tools_cut --artifact C:\briefdesk\data\cloudbase_migration\cutover --reset
   python deploy\ecs_pg.py verify --db class_tools_cut --expect C:\briefdesk\data\cloudbase_migration\cutover\manifest.json
   python deploy\ecs_pg.py apply-sql --db class_tools_cut --file deploy\migration\2026-11-18_notice_meta_lite.sql
   python deploy\ecs_pg.py apply-sql --db class_tools_cut --file deploy\migration\2026-11-18_notice_meta_cache.sql
   ```
   校验：34 表行数/哈希一致；函数/策略/触发器/索引计数一致；序列值正确；
   应用本地优化 SQL 后 `class_notices_meta` 输出与 CloudBase 现有实现逐字节一致（staging 已验证 sha 相同），
   且延迟从 221–250ms 降到 75–95ms（ECS 环回，125 行 / 313KB）。
4. **切换 PostgREST 指向 cut DB**（1 秒重启）：
   ```
   python deploy\ecs_pg.py switch-db --db class_tools_cut
   ```
   健康：`curl http://127.0.0.1/v1/rdb/rest-next/`（staging 先验）。
5. **切换生产路由**（改 Caddy：`/v1/rdb/rest/*` → 127.0.0.1:3000，保留 header_up -Authorization；同时删/保留 rest-next）：
   ```
   python deploy\ecs_cutover.py switch --to local
   python deploy\ecs_cutover.py status
   ```
   备份：脚本先把当前 `/etc/caddy/Caddyfile` 复制到 `/opt/class-tools/backup/caddy-<ts>.Caddyfile`。
6. **三端验证（测试账号）**：
   - 网页：`http://121.196.47.2/?api=next` 或域名 → 登录/通知/作业/投票/抽签/电费 → 写一条测试 marks 再清理。
   - 小程序/安卓（若已发布新域名版）：登录 + 读通知 + 提交一次测试投票/撤销。
   - 本机管线：`CLASS_CB_BASE=http://121.196.47.2/v1/rdb/rest/ python sync_notices_cloud.py --dry-run` 类只读检查。
7. **启用 ECS 定时任务**（power/xgj/health）：`python deploy\ecs_cron.py enable`；确认首轮成功（journal）。
8. **观察 30–60 分钟**：API 5xx、PostgREST 日志、PG 连接数、磁盘、附件/PPT 下载、健康行 `cloudbase` 变成 ok。

## 2. 切换后

- **附件外置启用（用户已授权的迁移第②步）**：确认三端新版已发布（网页已兼容 URL 形态）后，在本机 `C:\briefdesk\secrets\cloud.env`
  设 `NOTICE_ATTACH_EXTERNALIZE=1` + `ATT_BASE_URL=https://tool.furina.fun`，跑一次 `python scripts\sync_notices_cloud.py` 回填存量附件
  （data URI → ECS 签名 `/att/` URL；失败 fail-open 保留 data URI）。回滚：去掉 env 后重跑一次（已外置的 URL 仍可读，回滚不清存量）。
  演练证据：`deploy/migration/e2e_attach_staging.py` 8/8 PASS（staging）。


- CloudBase **不要立刻退订**：保留 ≥2 周只读回滚窗口（旧版小程序/安卓仍可能在用旧网关）。
- 关闭 CloudBase 云函数定时器（`tcb fn trigger delete ...`），避免双写；保留 DB 备份。
- 关闭/回收 OSS 上不再需要的测试资产；确认私有 staging 桶已删。
- 更新 `AGENTS.md`/`HANDOFF.md`/`CLOUDBASE.md`：新后端为真源，记录 runbook 与版本。
- 备份/监控：每日 `pg_dump` 保留 14 天 + `ecs_pg.py offsite --keep 8` 私有 OSS 异地备份；`ecs_pg.py monitor` timer 每 10 分钟巡检（详见 `deploy/ECS_DEPLOY.md §9`）。
- 备份演练：从 `pg_dump` 恢复到临时库并校验。

## 3. 数据一致性策略

- 采用 **全新库 `class_tools_cut` + 切换 db-uri**，避免增量同步；切换瞬间之后的写只进新库。
- 时间线：T0 冻结通知 → T1 导出（约 2–5 分钟，25MB 正文）→ T2 导入（1–3 分钟）→ T3 切 PostgREST（秒级）→ T4 切 Caddy 路由 → T5 三端验证。
- 冻结窗口内的少量提交风险：如果 T1 之后 CloudBase 仍有写，需在 T3 前再跑一次导出/导入（或接受丢失并补偿）；建议 T1 前明确通知。
- `class_sessions` 会一起迁移 → 现有 token 继续有效（用户无需重新登录）；如会话表导出失败，则用户重新登录一次即可。

## 4. 回滚（任一验证失败）

```
python deploy\ecs_cutover.py rollback            # Caddy 路由回 CloudBase（自动备份恢复 + reload）
python deploy\ecs_pg.py switch-db --db class_tools   # 如需把 PostgREST 切回 staging DB
```
- 回滚后 CloudBase 仍旧是生产真源（本步切流前未停用）；验证网页/小程序/安卓旧版恢复。
- 若 CloudBase 已停用，则回滚需先恢复 CloudBase（未到期前都在）。

## 5. 验收清单（切流完成判定）

- [ ] Caddy `/v1/rdb/rest/*` → 127.0.0.1:3000；`header_up -Authorization` 生效。
- [ ] 匿名/坏 token → 空/401（RLS 生效）；测试账号可读写。
- [ ] 34 表行数/哈希 = manifest；`class_sessions` 旧 token 可用。
- [ ] 网页三端冒烟通过；延迟指标：本机→ECS API P50 < 30ms（对比 CloudBase 80–120ms）。
- [ ] ECS 定时任务首轮成功；健康行 `cloudbase` ok、`cloud_*` 行有 ECS timer 心跳。
- [ ] 备份：`pg_dump` 成功且可从备份恢复校验；`ecs_pg.py offsite` 已上传首份私有 OSS 备份。
- [ ] 监控：`ecs_pg.py monitor` = MONITOR_OK；`class-tools-pg-monitor.timer` active；日志无连续 WARN。
- [ ] 仓库提交并双远端推送（site/index/脚本/文档）。

## 5.1 P4 演练（不切流，2026-11-18 已跑通：40.7MiB 快照 / 导入 4.5min / VERIFY_OK 34 表 / meta sha 一致）

在真正切流前，用**生产只读快照**在 `class_tools_cut` 演练一遍完整 P4（不动生产 Caddy）：

```bat
set DIR=C:\briefdesk\data\cloudbase_migration\p4-rehearsal
python deploy\migration\export_schema.py --out %DIR%
python deploy\migration\export_data.py  --out %DIR%
python deploy\migration\verify_export.py --out %DIR%
python deploy\ecs_pg.py import --db class_tools_cut --artifact %DIR% --reset
python deploy\ecs_pg.py verify --db class_tools_cut --expect %DIR%\manifest.json
python deploy\ecs_pg.py apply-sql --db class_tools_cut --file deploy\migration\2026-11-18_notice_meta_lite.sql
python deploy\ecs_pg.py apply-sql --db class_tools_cut --file deploy\migration\2026-11-18_notice_meta_cache.sql
python deploy\ecs_pg.py switch-db --db class_tools_cut
python deploy\ecs_pg.py smoke                 :: 测试账号 staging 契约冒烟
python deploy\ecs_pg.py probe                 :: db-uri=class_tools_cut
python deploy\ecs_pg.py switch-db --db class_tools   :: 演练完切回 staging 库
```
- 期望：导入 HASH_OK 34/34、verify TABLES_OK 34/34、smoke 全 PASS、staging `/v1/rdb/rest-next/` 200；
  2026-11-18 实测：导入 4.5min、72MB、HASH_OK 34/34、VERIFY_OK 34、meta sha `20a0346a…` 一致；lite 优化后 87ms、缓存优化后 6–9ms；
- `switch-db` 只改 PostgREST 指向的库（秒级重启），不碰 Caddy；演练后切回 `class_tools` 即恢复原状；
- 生产切流窗口仍按 §1 执行（cut DB 演练通过后再加 Caddy 切换）。

## 6. 已知风险

| 风险 | 缓解 |
|---|---|
| 备案未通过 → 小程序/安卓无法切新域名 | 先完成 staging + 网页（IP 调试）；等备案后一次性发布并切流 |
| 冻结窗口内有写丢失 | 提前通知；T1 后再补一次导出/upsert；或延长观察 |
| PostgREST 与 CloudBase 行为差异（错误格式/Prefer/限流） | staging 用三端真实请求回归；保留 CloudBase 回滚 |
| 单机 PG 故障 | 每日 pg_dump + ECS 快照；必要时用备份库恢复 |
| CloudBase 到期 2026-12-10 | 切流必须在此之前完成；若延期先续费一个月 |
