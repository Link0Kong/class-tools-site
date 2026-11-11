# CloudBase 数据审计报告（2026-11-11，反馈第 13 条）

> 审计人：Lead ｜ 时间：2026-11-11 21:45–22:10（Asia/Shanghai）
> 方法：**只读** SQL 盘点（CloudBase `ExecutePGSQL` API，管理员身份；PG 超级用户视角，不受 RLS 过滤）+
> PostgREST 匿名/班级 token 探测 + 既有文档/迁移交叉核对。清理仅限「测试垃圾 / 过期安全数据」，
> **未删除任何真实业务数据**。本报告已脱敏：不含 token、publish key、学号、姓名、手机号。
> 审计脚本：`web/_audit/tmp_audit1..7.py`、`tmp_audit_cleanup.py`、`tmp_cloud_probe_20261111.py`（只读/有界写）。

## 0. 结论速览

| 级别 | 问题 | 状态 |
|---|---|---|
| P0 | CloudBase 环境 **2026-12-10 23:59:59 到期**（IsAutoRenew=true，但无续费完成证据、无数据库备份/迁移演练） | 待用户处理 |
| P1 | 演示页测试 PPT 仍然可见：根因是 `ppt/tests/test_cloud_contract.py` 每次跑都会重建 2 个 `deleted=false` 测试 deck（此前设计“保留给网页验收”），非上次清理失败 | **已修复**（软删 2 个 + 测试夹具 tearDownClass 自清理 + 复核列表仅真实 deck） |
| P1 | 通知正文内嵌附件：`notices` 表 36MB，**可见 104 条正文合计 13.3MB**（单条最大 2.0MB，43 条含 data URI）；首次全量拉取（网页/小程序/安卓）在弱网下很慢。附件外置（ECS `/att`）能力已就绪但未启用 | 待用户决策（备案/HTTPS 后启用外置，或管线限制内嵌体积） |
| P2 | `private.class_sessions` 持续增长（2091 行、624kB；30 天 token 无清理策略） | 建议加保留清理（未执行） |
| P2 | `diag_analysis` 有 15 条 `status='new'` 分析（最早 11-08，最新今日；旧的可能已无价值） | 建议 agent 侧超时归档（未执行） |
| P2 | 遗留旧账号数据：`userdata` 2 行 / `fitrecs` 2 行 / `marks` 2 行使用非 10 位旧账号 id（历史 admin/xsx/xzx 迁移残留） | 如实报告，未删除（可能含真实偏好） |
| P2 | `visits` 69 行超过 25 天（页面统计只用今天/7 天） | 建议保留 90 天后清理（未执行） |
| P2 | `public.roster` 旧名单表仍有 1 行（legacy，前端已不用） | 保留兼容（未删除） |
| P2 | `site_assets.updated_at` 对 `ppt_agent` 心跳不更新（body.seen_at 是新鲜的；仅列时间戳误导） | 文案/查询注意即可 |
| P2 | anon 角色对部分表持有超出实际需要的 DELETE 权限（RLS 策略实际拦截，未发现可利用越权） | 建议后续最小权限收敛（未执行） |
| P2 | `debug_headers()` 调试函数可被 anon 执行（仅回显调用者自己的请求头，无越权；线上无调用方） | **已回收** anon/authenticated 执行权 |
| P2 | `private.test_zz`(0 行) / `private.test_zz2`(1 行) 测试遗留表 | **已 DROP** |
| P2 | `login_jobs` 有 1 条已完成的旧登录任务（含 PGP 密文字段，密文已空） | **已清理**（只删 >1h 的 done/failed/expired） |
| P2 | 备案暂停期 `site_config.web.paused=false` 与「DNS 实际暂停」不一致（诊断页会把 site_static/site_tls 报成 down 而非“已按备案暂停”） | **已修复**（`web_pause.py --on`，paused=true/note=备案暂停） |

## 1. 环境与容量

- 环境：`tool-d4gosudok46e0e081`（ap-shanghai，个人版）；`tcb env list`：Status NORMAL、IsAutoRenew=true、
  **ExpireTime 2026-12-10 23:59:59**。前端 gateway/PostgREST 正常；TLS 证书有效（既有记录）。
- 数据库总大小 **42 MB**；行数（PG 超级用户视角）：
  `notices 135（可见 104/归档 31）`、`homework 14`、`marks 37`、`fitrecs 28`、`userdata 8`、`visits 335`、
  `power 17`、`power_history 4215`、`ppt_decks 55（可见 1 / 软删 54）`、`ppt_upload_chunks 0`、
  `service_health 18`、`site_assets 2`、`site_config 1`、`client_diag 13`、`diag_analysis 17`、`repair_tasks 2`、
  `login_jobs 0（清理后）`、`agent_keys 1`、`polls 0`、`poll_votes 0`、`feedback 0`、`roster 1`；
  private：`class_ids 71（70+1 测试）`、`class_sessions 2091`、`class_league 50`、`class_audience 67`。
- 服务健康（22:00）：18 行均为 3 分钟内新写入；`cloudbase/tt_cloud/cloud_power_sync/cloud_health_probe=ok`；
  `cloud_xgj_sync=warn`（学工记无作业，既有预期空态）；`dns_domain/site_static/site_tls=down`（DNS 暂停期，
  已在 `web_pause --on` 后由巡检按“备案暂停”处理）。
- 课表快照 `site_assets.tt` 更新时间 2026-11-11 17:47（4 小时内，正常）；`ppt_agent` body.seen_at 新鲜、
  `queued=0`（转换机在线；`updated_at` 列不随 upsert 刷新属实现细节）。
- OSS 测试资产（只读统计，未删除）：50 个测试身份 deck 共 **104 对象 / 9.60 MiB**
  （`ppt/a/` 96 对象 9.25MB、`ppt/src/` 8 对象 0.82MB）。

## 2. 已整改（前后对比）

| 项 | 之前 | 之后 / 证据 |
|---|---|---|
| 演示页测试 deck | `deleted=false` 共 3 行：2 个测试 deck（「测试·嵌入视频演示」「测试·4:3 演示」，owner=测试身份）+ 真实 deck | 软删 2 行（PATCH HTTP 200，写前断言 owner_sid=3260799999）；`deleted=false` 仅 `dmwalrdlgevz90l`；网页 LIST_SELECT 复核同样 1 行 |
| 测试夹具复现 | `test_cloud_contract.py::TestE2EFixtures` 跑完保留 fixture → 用户每次看到测试 PPT | 已改 `tearDownClass`：软删本轮 fixture deck + 清分片 + 复核；用临时脚本真实创建 deck 后调用 tearDownClass 验证（deck→deleted=true、chunks 清零），验证行已彻底删除 |
| 测试遗留表 | `private.test_zz`(0)、`private.test_zz2`(1) | DROP 成功；private schema 只剩 4 张正式表 |
| 登录任务残留 | `login_jobs` 1 行 done（>1h，pwd_pgp 为空） | DELETE 1 行；现 0 行 |
| 调试函数暴露 | `debug_headers()` 可被 anon 执行（回显自身请求头） | `REVOKE EXECUTE FROM public, anon, authenticated`；现仅 owner/service_role |
| 暂停状态漂移 | `site_config.web.paused=false` 但 DNS 暂停 | `web_pause.py --on` → paused=true、note=备案暂停、paused_at=2026-11-11 22:02 |
| 通知附件“外置” | 0 条使用 `/att/` URL；43 条 body 含 data URI | 未改（见 §3 P1；需备案/HTTPS 后启用管线外置） |

## 3. 待处理 / 建议（按优先级）

1. **【P0，用户决策】CloudBase 到期 2026-12-10**：到期后 DB/网关/云函数/定时器/存储全部失效 →
   网页/小程序/安卓三端不可用。建议：尽快在控制台确认续费/自动续费扣款方式，并做一次**数据库导出备份**
   （42MB，`pg_dump` 或 CloudBase 备份）+ 迁移预案（`C:\briefdesk\docs\云端服务迁移_20261106.md`）。
2. **【P1，性能/成本】通知正文过大**：可见 104 条合计 13.3MB（最大单条 2.0MB，含 43 条 data URI 附件）。
   首次/换设备全量拉取会显著拖慢通知页；建议二选一：
   ① 备案/HTTPS 恢复后启用附件外置（`sync_notices_cloud.py` 的 `NOTICE_ATTACH_EXTERNALIZE=1` + `ATT_BASE_URL=https://tool.furina.fun`，存量自动回填，模板已兼容 URL 形态）；
   ② 仍内嵌时在管线限制单条内嵌附件总量（如 >1.5MB 的附件不内嵌，改为下载链接）。
   现状未被破坏：前端有轻量签名（`notices?select=id,ts,hidden,edited_at`），只有签名变化才整表重拉。
3. **【P2】会话表保留策略**：`private.class_sessions` 2091 行（30 天 token，无清理）。建议按
   `expires_at < now()-7d` 定期删除（不影响未过期登录）；本次未删（无过期行）。
4. **【P2】诊断分析归档**：`diag_analysis` 15 条 `new`，最早 11-08。建议 agent 对 >48h 未处理项标记
   `ignored`（避免诊断页长期挂待处理）；本次未改。
5. **【P2】遗留账号行**：旧账号 id（长度 2–3 的非学号账号）数据：userdata 2 行 / fitrecs 2 行 / marks 2 行。
   可能是早期 admin/xsx/xzx 迁移残留；**可能含真实偏好，未删除**，建议确认后迁移到新 sid 或忽略。
6. **【P2】访问统计保留**：`visits` 335 行中 69 行 >25 天（统计页只用今天/7 天）。建议保留 90 天后清理。
7. **【P2】最小权限收敛**：anon 对 `power/power_history/diag_analysis/login_jobs/ppt_upload_chunks/repair_tasks`
   持有 DELETE 等表级权限（RLS 策略实际限制为管理员/owner；未发现可利用越权）。若后续要严格最小权限，
   需先确认云函数/转换机 admin-token 清理路径（power_history 30 天清理、ppt chunks 删除依赖这些权限）。
8. **【P2】`class_verify` 无限流**：身份验证仅校验学号+姓名，无频率限制（爆破成本高但存在）。建议
   后续网关/脚本侧加简单限流（本次未改）。
9. **【P2】`roster` 旧表** 1 行 legacy；前端已改用 `class_members`/`class_league`。可择机删除（未删）。
10. **【P2】`site_assets.updated_at` 语义**：`ppt_agent` 心跳只更新 body.seen_at；诊断/页面如需判断在线请读
    `body.seen_at`（毫秒），不要读 `updated_at`。

## 4. 权限/安全核查（实测）

- 无 token 访问 `power_history/notices/...` → 200 `[]`（RLS 生效）；`polls/poll_votes` 直连 → 401（设计：仅 RPC）。
- 有效班级 token：`userdata` 仅本人（`id=auth_acc()`）、`marks/fitrecs` 仅本人、`power/power_history/notices` 全班可读、
  `ppt_decks` 全班读/本人写/管理员更新、`ppt_upload_chunks` 仅 owner/admin，与迁移一致。
- `app.whoami`/`class_whoami`/`class_league`：SECURITY DEFINER + auth 校验；`tt_login_status/enqueue` 仅本人/管理员，
  不返回 `pwd_pgp`；`diag_agent_info` 需 auth。
- `pgcrypto` 扩展函数（crypt/gen_salt/pgp_*）对 anon 可执行，但都需要调用方自备密钥/明文，无服务端密钥泄露面。
- `debug_headers()` 已回收（见 §2）。
- 未在 DB 中发现明文密码/token 列；`login_jobs` 密文字段已空且旧行已清理。

## 5. 数据一致性核查

| 项 | 结果 |
|---|---|
| `power` 17 间房 | 与前端 `PW_ROOMS` 17 间一一对应（13×2、16×2、23A×9、23B×4），更新时间均在 22:00 内（小时级同步正常） |
| `power_history` 4215 行 | 17 房 × 247–248 点；无重复 (`roomverify,ts`)；无未来时间戳；无 >35 天旧行；最早 2026-11-05（与上线一致） |
| `polls/poll_votes` | 均 0 行（QA 清理干净），无孤儿投票 |
| `ppt_decks` | 可见 1（真实 deck）；54 软删（含历史测试/失败/卡死行，前端不可见）；`ppt_upload_chunks` 0（无残留分片） |
| `marks` | hw 8 / ntdone 28 / nt 1；35 行标准学号 + 2 行旧账号；无重复主键 |
| `notices` | 104 可见 / 31 归档 / 5 hidden / 135 条均有 edited_at（管线覆盖）；无 `/att/` 外置 URL |
| `service_health` | 18 行全部 3 分钟内新鲜；无过期行 |
| `site_assets` | tt 4 小时内更新、ppt_agent 心跳新鲜；site_config 1 行（web.paused 已按暂停状态修正） |
| `client_diag` | 13 行（analyzed 8 / ignored 5），最新今日 21:33；无长期未处理异常 |
| `agent_keys` | 1 行（tt_login，pubkey 2.1KB、seen_at 新鲜） |
| 表结构/RLS | 28 张 relation 全部有 RLS（private schema 不对外暴露）；public 无 `users`/`identity_verify` 旧表残留 |

## 6. 回滚

- 本次清理仅 6 项有界写操作（2 个 deck 软删、2 张测试表 DROP、1 行 login_jobs 删除、1 个函数权限回收、
  site_config paused 置 true）。
  - 测试 deck 软删可改回 `deleted=false`（但建议保持删除）。
  - `private.test_zz*` 为测试表，无需恢复。
  - `login_jobs` 旧行内容为已完成任务元数据，无需恢复。
  - `debug_headers` 权限可用 `GRANT EXECUTE ... TO anon` 恢复（不建议）。
  - 暂停状态恢复：DNS 恢复解析后执行 `python C:\briefdesk\scripts\web_pause.py --off`。
- 未对 `notices/power/power_history/userdata/marks/fitrecs/visits` 等真实业务表做任何删除。
