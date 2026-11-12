# 测试「真实账号」使用审计与整改（2026-11-11）

> 政策来源：用户 2026-11-11 要求「以后测试统一用测试账号，不要再用任何真实账号了」。
> 已写入 `AGENTS.md §0-7` 与 `HANDOFF.md §46`；守卫工具 `tools/tests/_test_account.py`。
> 本报告为一次性审计+整改记录（不写入任何 token / 真实姓名学号明文以外的内容；发现的真实学号仅以“真实学号”描述）。

## 0. 政策口径（已落地）

- 允许：① 官方测试身份 **3260799999 / 测试账号**（`private.class_ids.is_test=true`，公开凭据）；② 脚本临时创建、`finally` 删除的 **9999 段临时 QA 测试身份**（`is_test=true`，学号 `9999xxxxxx`，仅测试期存在）。
- 禁止：登录真实同学/管理员账号（含管理员 3260707024）、读取/注入真实账号 token（`C:\briefdesk\secrets\class-token.json`）、用真实身份冒名构造 `private.class_sessions`、测试期间真实写业务表。mock 身份/测试夹具也不再使用真实学号。
- 生产运维（部署 `deploy/`、PPT 转换机 `ppt/agent.py`、课表同步 `jwxt/`）**不属于测试**，其服务凭据仍按 AGENTS §0-1 管理；但不得把这些运维 token 注入测试/自动化。

## 1. 审计发现（整改前）

| # | 位置 | 问题 | 严重度 |
|---|---|---|---|
| 1 | `ppt/tests/test_cloud_contract.py` | `setUpClass` 用 `agent.Cloud`（自动读取/登录**真实管理员 token**）作为测试客户端：RLS/队列/心跳/管理员读断言、E2E fixture 清理、run_once 都跑在真实管理员身份下；`TestTokenRefreshReal` 还用真实管理员身份刷新 token；`TestHeartbeat` 真实写 `site_assets`（管理员专属） | 高（真实账号真实写云端） |
| 2 | `ppt/tests/cleanup_test_decks.py` | 用 `agent.Cloud`（真实管理员 token）读取并软删测试 deck | 高（真实账号真实写云端） |
| 3 | `deploy/cloudbase/verify_2026_11_11_shared_tables.py` | 「跨账号隔离」验证时往 `private.class_sessions` 插入**真实班级成员**（`is_test=false`，seat 1）的一次性会话，用真实身份读/写 water 与 stage_prefs | 高（冒用真实同学身份） |
| 4 | `tools/tests/vote_cloud_check.py` | 为可见范围测试插入 **4 个真实班级身份**（班委 seat16 / 团员 seat1 / 普通 seat2 / 管理员 sid）的 `class_sessions` 一次性 token，用真实身份列表/详情/投票 | 高（冒用真实同学+管理员身份） |
| 5 | `tools/tests/dns_pause_web_check.py` | 自动化浏览器注入**真实管理员 token**（读取 `C:\briefdesk\secrets\class-token.json`）——虽然云端请求全 mock，仍属真实账号进入自动化 | 中 |
| 6 | 30 个测试文件 | mock 身份/夹具使用真实学号（`3260707001/7002/7003`、`3260707026`、`3260707024`、`3260709999` 等）与真实姓名（陈子麒）作为占位——无网络登录，但不符合“只用测试账号”口径 | 中（夹具卫生） |
| 7 | `tools/tests/_qa_v2/qa_cloud.py` / `qa_live_ui.py`（本机未入库历史脚本） | 读取真实管理员 token 做云端/UI 验收 | 中（本地遗留；已在本报告标注停用，不入库） |
| 8 | `_audit/tmp_cloud_probe_20261111.py`（历史一次性审计脚本，已入库） | 用 `agent.Cloud` 读取真实管理员 token 做只读盘点 | 低（历史运维审计） |
| 9 | `jwxt/tests/test_sso_http.py` / `jwxt/sync.py` 示例 | 用真实管理员学号作为 SSO 单测示例账号/命令示例（mock，不联网；但字样为真实账号） | 低 |
| 10 | 生产代码 `ppt/agent.py`、`jwxt/tt_cloud.py` | 转换机/课表云同步需管理员服务凭据（运维，非测试） | 不整改（文档说明例外） |
| 11 | `tools/tests/v2_notice_time_live_check.py` / `v2_notice_time_online_ui_check.py` | 只读通知线上检查从 `C:\briefdesk\secrets\class-token.json` 读**真实管理员 token**（只读，但属真实账号进入测试） | 中 |
| 12 | `tools/tests/v2_notice_time*.py`、`_compliance/*`、`ziqi/make_qr.py` | 测试/报告断言里出现真实姓名，属**通知内容/报告内容数据**（非登录账号） | 保留（数据内容，非账号使用） |

## 2. 整改（已完成）

1. **`ppt/tests/test_cloud_contract.py`**：测试客户端改为 `TestAccountCloud`（官方测试身份）；匿名读用「无 token 的 transport」（`agent.Cloud` 只做 HTTP transport，`raw()` 不触发 `ensure_token`）；`TestHeartbeat` 改 **纯 mock 单测**（FakeCloud 捕获 payload，不再写 `site_assets`）；`TestTokenRefreshReal` 改为**测试身份**临时 TOKEN_FILE 刷新（`cloud.admin_sid/name=TEST_SID/TEST_NAME`，不读真实管理员身份）；E2E fixture 用测试身份（owner 可软删自己的测试 deck）；为测试身份新增 `agent.run_once(..., heartbeat=False)` 参数（生产默认 True，行为不变；测试身份无管理员写心跳权限）。
2. **`ppt/tests/cleanup_test_decks.py`**：新增 `TestIdentityCloud`（`class_verify` 测试身份取 token），读取/软删全部以测试身份执行（fixture 属测试身份，RLS owner 权限足够；真实 deck 不触碰的写前 owner 断言保留）。
3. **`deploy/cloudbase/verify_2026_11_11_shared_tables.py`**：删除真实班级成员一次性会话；改为「测试身份第二会话（同 sid 不同 token）」验证 water 共享与多设备语义；stage_prefs 的跨账号断言改为「写非本人 sid 被 with check 拒绝」「查非本人 sid 为空」等负向断言；清理逻辑删除对应会话行。文档头部如实写明覆盖变化。
4. **`tools/tests/vote_cloud_check.py`**：真实身份会话 → **9999 段临时 QA 测试身份**（`is_test=true`；seat 81–84：QA班委/QA团员/QA普通/QA管理员，class_league 行同步创建），finally 删除 sessions + class_league + class_ids + 测试投票；指定成员可见性保留 owner/范围外不可见/管理员越权等断言，需要真实非 is_test 身份才能观测的「名单内成员可看可投」正向用例**已如实剔除**（在脚本注释中写明原因）。
5. **`tools/tests/dns_pause_web_check.py`**：删除 `TOKEN_FILE`/真实管理员身份读取；改为 `IDENT = {token:"test-token-dns-pause", sid:"3260799999", name:"测试账号"}` 测试身份快照（脚本内云端请求全 mock）。
6. **夹具脱敏（30 个文件）**：真实学号 → 官方测试身份（3260799999）或 9999 段 mock（`9999000001…`）；`sync_check.py` 真实管理员学号→测试身份；`selfcheck.py`、`v2_ppt_check.py` 同步；`jwxt` SSO 单测示例账号改明显假号。
7. **守卫**：新增 `tools/tests/_test_account.py`（`TEST_SID/TEST_NAME`、`assert_test_identity`、`test_identity_snapshot`、`test_identity_token`）；AGENTS §0-7 要求新增测试/QA 脚本使用。
9. **通知线上检查**：`v2_notice_time_live_check.py` / `v2_notice_time_online_ui_check.py` 的 token 来源改为「公开 publishable key + 测试身份 `rpc/class_verify`」的 `test_identity_token()`，不再读取真实管理员 token（脚本目标为 DNS 暂停前的 https 线上地址，属历史线上检查；本轮只做身份合规改造，未联网复跑）。
8. **历史脚本**：`_audit/tmp_cloud_probe_20261111.py` 加 `OPS_RUN_ADMIN_AUDIT=1` 闸门（非测试、默认拒绝）；本机未入库的 `_qa_v2/qa_cloud.py`/`qa_live_ui.py` 标注停用（不再作为测试入口；其替代是 `_test_account.py` + 测试身份脚本）。

## 3. 验证（整改后真实复跑，全部真实执行）

| 套件 | 结果 |
|---|---|
| `tools/tests/sync_check.py` | **144/144 PASS**（真实夹具含身份/看板同步全链路） |
| `tools/tests/power_check.py` | **155/155 PASS** |
| `tools/tests/v2_power_sync_hardening_check.py` | **29/29 PASS** |
| `tools/tests/v2_ui_check.py` | **27/27 PASS** |
| `tools/tests/water_check.py` | **171/171 PASS** |
| `tools/tests/v2_water_sync_check.py` | **118/118 PASS** |
| `tools/tests/v2_stage_v5_check.py` | **116/116 PASS** |
| `tools/tests/v2_web_batch2_roster_check.py` | **30/30 PASS** |
| `tools/tests/v2_web_batch2_water_cloud_check.py` | **36/36 PASS** |
| `tools/tests/v2_web_batch2_file_check.py` | **37/37 PASS** |
| `tools/tests/v2_web_reminder_check.py` | **37/37 PASS** |
| `tools/tests/v2_power_pick_mem_check.py` | **48/48 PASS** |
| `tools/tests/dns_pause_web_check.py` | **19/19 PASS**（不再读真实管理员 token） |
| `tools/tests/v2_ppt_check.py` | **92/92 PASS** |
| `ppt/tests/test_pure_logic.py` | **171/171 OK**（agent.py heartbeat 参数改动无回归） |
| `ppt/tests/test_cloud_contract.py`（测试身份子集：RLS/失败路径/删除态/token 刷新/心跳 mock） | **5/5 OK**（心跳为纯 mock，不再真实写 site_assets） |
| `ppt/tests/cleanup_test_decks.py --dry-run` | **exit 0**（测试身份读/预览；真实 deck 不触碰） |
| `deploy/cloudbase/verify_2026_11_11_shared_tables.py`（真实云端） | **VERIFY PASS 46/46**（仅测试身份 + 同身份第二会话；finally 0 残留） |
| `tools/tests/vote_cloud_check.py`（真实云端） | **80/80 PASS**（9999 段临时 QA 身份；finally 清理 sessions/class_ids/class_league/polls，云端复核 0 残留） |
| 云端复核 | `class_ids=71（9999 段 0）`、`class_league=50（9999 段 0）`、`class_sessions 中 QA token 0`、`polls/poll_votes=0/0`、`water=0`、`stage_prefs=0` |

覆盖变化（如实）：管理员专属能力（`site_assets` 心跳写、管理员 token 刷新）改为 mock/运维步骤；可见范围「名单内真实成员可看可投」正向用例需非 `is_test` 身份，已移除并在 `vote_cloud_check.py` 注释说明；其余角色（班委/团员/普通/管理员）由 9999 段临时 QA 身份覆盖。

## 4. 遗留与建议

- 本机未入库的 `tools/tests/_qa_v2/qa_cloud.py`、`qa_live_ui.py`、`desktop_opt.py`、`live_smoke.py` 等历史脚本仍可能引用管理员 token；**已停用**，新测试请勿使用；如确需管理员视角验收，应列入运维步骤并明确记录，而非自动化测试。
- `_audit/tmp_audit*.py` 为历史运维审计脚本（部分含真实学号作为分类常量）；它们是只读 SQL 证据，不是测试入口；已加说明/闸门（tmp_cloud_probe）。
- 通知内容数据/报告模板中的真实姓名属于业务数据展示，不是测试账号使用；如需进一步脱敏需单独评估（会影响通知内容真实性）。
- 生产服务（PPT 转换机、课表云同步）的管理员服务凭据属运维例外，已在 AGENTS §0-7 写明；不得导出到测试/自动化。

## 5. 补记：小程序测试目录（2026-11-12）

- 范围：`mp-class-tools-tests/**`（不在 web 仓库，但同样适用「测试只用测试账号」红线）。
- 发现：55 个 JS/Python 测试/预览脚本把真实管理员学号/姓名（3260707024/陈子麒）及真实同学学号作为身份 mock/期望值（纯 mock，不发真实请求）。
- 整改：统一替换为测试身份 `3260799999 / 测试账号`，同学座号类 mock 改 `9999` 段合成身份；`cloudspace_unit_tests.js` 保留「不出现真实账号」的静态断言。
- 验证：`node unit.js` 461 passed / 0 failed；`staticcheck.py` 通过；`code_quality_check.js` 全部规则通过。
