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
   python deploy\ecs_pg.py import --db class_tools_cut --artifact C:\briefdesk\data\cloudbase_migration\cutover
   python deploy\ecs_pg.py verify --db class_tools_cut --expect <manifest.json>
   ```
   校验：34 表行数/哈希一致；函数/策略/触发器/索引计数一致；序列值正确。
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

- CloudBase **不要立刻退订**：保留 ≥2 周只读回滚窗口（旧版小程序/安卓仍可能在用旧网关）。
- 关闭 CloudBase 云函数定时器（`tcb fn trigger delete ...`），避免双写；保留 DB 备份。
- 关闭/回收 OSS 上不再需要的测试资产；确认私有 staging 桶已删。
- 更新 `AGENTS.md`/`HANDOFF.md`/`CLOUDBASE.md`：新后端为真源，记录 runbook 与版本。
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
- [ ] 备份：`pg_dump` 成功且可从备份恢复校验。
- [ ] 仓库提交并双远端推送（site/index/脚本/文档）。

## 6. 已知风险

| 风险 | 缓解 |
|---|---|
| 备案未通过 → 小程序/安卓无法切新域名 | 先完成 staging + 网页（IP 调试）；等备案后一次性发布并切流 |
| 冻结窗口内有写丢失 | 提前通知；T1 后再补一次导出/upsert；或延长观察 |
| PostgREST 与 CloudBase 行为差异（错误格式/Prefer/限流） | staging 用三端真实请求回归；保留 CloudBase 回滚 |
| 单机 PG 故障 | 每日 pg_dump + ECS 快照；必要时用备份库恢复 |
| CloudBase 到期 2026-12-10 | 切流必须在此之前完成；若延期先续费一个月 |
