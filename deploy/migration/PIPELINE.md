# 本机管线 + 云端定时任务切自建后端 · Runbook（P3）

> 阶段：**CloudBase → ECS 自建 PostgREST** 迁移 P3（总计划见 [`PLAN.md`](PLAN.md) §3）。
> 目标：切流前让**本机数据管线**与**CloudBase 云端定时任务**都支持「ECS 自建后端」，但
> **默认行为与迁移前完全一致（仍 CloudBase）**；切流时可只改配置/开关，随时可回滚。
> 记录日期：2026-11-18（P3 本机管线工程师 pipeline-dev）。

## 0. 一句话结论

| 层 | 默认（今天） | 切换后 | 回滚 |
|---|---|---|---|
| 本机管线（17 脚本） | 解析 `web/tools/index.html` 的 `var CB` → CloudBase | `secrets\cloud.env` 里加 `CLASS_CB_BASE=`（+可选 `CLASS_CB_KEY=`） | 删除/注释该行 |
| ECS 定时任务（替代 3 个云函数） | 不安装/已安装但 **systemd timer 全部 disabled** | `deploy\ecs_cron.py enable --confirm` | `disable`（保留文件）或 `uninstall` |
| 健康/诊断 18 行 | 本机写 local 10 行 + CloudBase `health_probe` 写 cloud 8 行 | ECS `health_probe` job 写 cloud 8 行（`meta.runner=ecs-timer`），本机仍写 local 10 行 | 停 ECS timer、恢复 CloudBase 定时器 |
| CloudBase | 只读、不动 | P4 切流后才停用 | 定时器/云函数恢复 |

**红线**：本机生产任务默认行为不变；不写 CloudBase；测试只用测试账号；凭据不打印、不入库。

## 1. 开关契约（唯一入口 `C:\briefdesk\scripts\cloud_backend.py`）

```
优先级（高 → 低）：
  1. 进程环境变量  CLASS_CB_BASE / CLASS_CB_KEY（非空才生效）
  2. 文件          C:\briefdesk\secrets\cloud.env 中的同名键（KEY=VALUE）
  3. 默认          web/tools/index.html 的 `var CB="..."` / `var CBK="..."`（CloudBase）
```

- 只覆盖 `base` 时，key 仍用 index.html 的 publishable key（自建路由由 Caddy 剥离 `Authorization`，不影响行为）。
- `CLASS_CB_KEY` 仅当需要给「自建后端但要求非空 Authorization」时用；一般不用设。
- 不设任何覆盖时，`resolve()` 返回的 base/key 与旧实现 `re.search(r'var CB="([^"]+)"')` 完全一致（见 §6 A01 断言）。
- 排障/辅助变量（一般不设）：
  - `CLASS_CB_CONFIG`：替换 `secrets\cloud.env` 路径（测试/演练用）；
  - `CLASS_CB_INDEX`：替换 `tools/index.html` 路径。
- 只读诊断命令（**不打印 key**）：
  ```powershell
  C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\cloud_backend.py --status
  C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\cloud_backend.py --check     # 只读 GET <base>service_health
  C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\cloud_backend.py --env-example
  ```

### 1.1 注入方式（推荐 A；写清楚「为什么不是用户环境变量」）

| 方式 | 做法 | 适用 |
|---|---|---|
| **A（推荐）** | 在 `C:\briefdesk\secrets\cloud.env` 追加 `CLASS_CB_BASE=...`（不打印） | watchdog 每 5 分钟新起进程、watcher 拉起的子进程**每次都重新读文件** → 改文件立即生效、回滚删行即可 |
| B | `setx CLASS_CB_BASE ...` 用户环境变量 | 只对之后新启动的进程生效；常驻 `detect_docs` watcher 及其子进程**不会**看到（父进程环境不变）→ 需重启 watcher/相关计划任务 |

> 之所以不只用 B：`detect_docs.py --watch` 是常驻 pythonw，它 spawn 的
> `sync_notices_cloud.py` / `sync_class_roster.py` / `oppo_push.py` 继承它的旧环境，
> 用户环境变量改了也不生效，容易「以为切了其实没切」。A 的 `cloud.env` 由每个子进程重新读取，最稳。

### 1.2 `secrets\cloud.env` 追加示例（`--env-example` 同内容）

```ini
# staging（P2 影子验证；写 rest-next 影子库，可安全做集成测试）
CLASS_CB_BASE=http://121.196.47.2/v1/rdb/rest-next/
# 切流后（P4，Caddy /v1/rdb/rest/* 改指向自建 PostgREST）
#CLASS_CB_BASE=http://121.196.47.2/v1/rdb/rest/
# 备案 + HTTPS 恢复后等价写法
#CLASS_CB_BASE=https://tool.furina.fun/v1/rdb/rest/
# 可选：CLASS_CB_KEY=...（自建路由会剥 Authorization，一般不需要）
# 回滚：删除/注释掉 CLASS_CB_* 行即可
```

## 2. 覆盖清单（17 个脚本；直接 = 自己解析 base，间接 = 复用直接入口）

| # | 脚本 | 作用 | 入口 | 备注 |
|---|---|---|---|---|
| 1 | `scripts/sync_notices_cloud.py` | 通知板 → `public.notices` | 直接 `cb_config()` | 写 |
| 2 | `scripts/sync_power_cloud.py` | 完美校园电费 → `public.power/power_history` | 直接 `cb_config()` | 写 |
| 3 | `scripts/health_beat.py` | 本机 10 行 → `public.service_health`（并探测 cloud 8 行） | 直接 `_cb_config()` | 写 + 双后端适配 |
| 4 | `scripts/diag_agent.py` | 诊断/AI/修复任务/课表登录代理 | 直接 `cb_config()` | 读写 |
| 5 | `scripts/hw_auto/sync_homework_cloud.py` | 自动作业 → `public.homework` | 直接 `cb_config()` | 写 |
| 6 | `scripts/sync_class_roster.py` | `rpc/class_members` → 本机名单缓存 | 直接 `cb_config()` | 读 |
| 7 | `scripts/check_admin_notices.py` | 管理员通知可见性/人群统计 | 直接（import 时解析） | 只读 |
| 8 | `scripts/check_cloud_file_notices.py` | 云端通知/文件通知检查 | 直接（import 时解析） | 只读 |
| 9 | `scripts/test_league_visibility.py` | 遗留 RLS 人工核验脚本 | 直接 `cb_config()` | ⚠️ 用真实身份 + `tcb` 直写 CloudBase；**自建后端下主动拒绝运行**；不属于自动化测试 |
| 10 | `scripts/web_pause.py` | 网页暂停开关 → `public.site_config` | 间接（`health_beat._cb_config`） | 写 |
| 11 | `scripts/oppo_push.py` | OPPO 推送读 `public.push_tokens` + 推通知 | 间接（`sync_notices_cloud`） | 读 |
| 12 | `scripts/cleanup_qq_downloads.py` | QQ 下载清理时读云端通知 body | 间接（`sync_notices_cloud`） | 读 |
| 13 | `scripts/watchdog.py` | 每 5 分钟调度 + 每轮调 `health_beat.publish_from_watchdog()` | 间接（import `health_beat`） | 写 |
| 14 | `scripts/detect_docs.py` | 常驻 watcher，串起 1/5/6/11 等子进程 | 间接（子进程继承 + 自读 cloud.env） | — |
| 15 | `scripts/hw_auto/run_hw_auto.py` | 每 2h 调 5（`sync_homework_cloud.py`） | 间接 | — |
| 16 | `scripts/test_notice_merge.py` | 纯逻辑单测（monkeypatch 云端请求） | 间接（import 后替换 `cb_config`） | 不联网 |
| 17 | `cloudbase/deploy.py` | 部署 CloudBase 云函数 | **故意不跟随覆盖** | 云函数的 `CB_BASE` 必须指 CloudBase；见 §4.1 注释 |

切流前需一起处理、已由 Lead 补上的两处（2026-11-18 确认，未在本任务写权限内）：
- `web/jwxt/tt_cloud.py`：已支持 `CLASS_CB_BASE` / `CLASS_CB_KEY`（默认仍 index.html）；**注意它要求
  两个变量都非空才走覆盖**（只设 `CLASS_CB_BASE` 会回退 index.html）——切流时在 cloud.env 里同时设置
  `CLASS_CB_KEY`（publishable key，公开）即可；或改成「base 优先、key 回退 index」。
- `ppt/agent.py`：已支持 `CLASS_CB_BASE`（`CFG_BASE`）与 `CLASS_CB_KEY`（`_read_publish_key`），
  二者独立，单设 base 即生效。
- `web/tools/tests/*`（如 `draw_cloud_check.py`、`v2_notice_time_live_check.py`）：测试脚本，
  切流后需指 staging/自建库；属测试资产，不影响生产。

## 3. 本机切换 / 回滚 runbook

### 3.1 切到 staging（演练 / P2 影子验证）
```powershell
# 1) 写入（不打印内容）：在 C:\briefdesk\secrets\cloud.env 末尾追加
#    CLASS_CB_BASE=http://121.196.47.2/v1/rdb/rest-next/
# 2) 只读确认（输出只含 base/来源，不含 key）
C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\cloud_backend.py --status
C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\cloud_backend.py --check
# 3) 逐脚本只读验证（不写）
C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\sync_power_cloud.py --dry-run --limit 1
C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\health_beat.py --once --dry-run
```
预期：`--status` 显示 `backend=staging base=http://121.196.47.2/v1/rdb/rest-next/ base_source=file`。

### 3.2 切回 CloudBase（任何异常立即执行）
```powershell
# 删除/注释 secrets\cloud.env 里的 CLASS_CB_BASE / CLASS_CB_KEY 两行
C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\cloud_backend.py --status
# 预期 backend=cloudbase base_source=index
```
无需改 `index.html`、无需重启 watchdog（它每轮新进程都会重读 cloud.env）。

### 3.3 切流后（P4，自建后端=生产库）
把 `CLASS_CB_BASE` 改成 `http://121.196.47.2/v1/rdb/rest/`（备案/HTTPS 后可用
`https://tool.furina.fun/v1/rdb/rest/`）。**顺序**：先切 Caddy `/v1/rdb/rest/*` → 验证
自建库 → 再改 cloud.env（否则本机管线会写到 Caddy 仍反代的 CloudBase）。

### 3.4 ⚠️ 双后端数据分叉
本机管线一旦切到 staging/自建库，**CloudBase 数据不再更新**。因此：
- staging 演练只做「读链路 + 单条测试写入（finally 清理）」；
- 演练完成后立即回滚到 CloudBase，不做长期双跑；
- 真正的全量切流在 P4 一次完成（见 `CUTOVER.md`）。

## 4. 云函数替代到 ECS（`deploy/ecs_cron.py` + `deploy/functions/`）

### 4.1 组件

| 云函数（CloudBase） | ECS 替代 | 时间表（systemd timer） | 写库 |
|---|---|---|---|
| `power_sync`（每小时:01） | `jobs_runner.py power_sync` | `*-*-* *:01:00` | `public.power` / `power_history` |
| `xgj_sync`（每2h:20） | `jobs_runner.py xgj_sync` | `*-*-* 00/2:20:00` | `public.homework`（`auto_hw_xgj_en_*`） |
| `health_probe`（每5分钟） | `jobs_runner.py health_probe` | `*-*-* *:00/5:00` | `public.service_health`（cloud 8 行） |

安装位置：`/opt/class-tools/jobs/`（代码）+ `/etc/class-tools/jobs.env`（600，凭据）+
`/var/lib/class-tools/jobs/state/`（心跳）+ `/etc/systemd/system/class-tools-job-*.{service,timer}`。
源码来自仓库 `deploy/functions/`（= `C:\briefdesk\cloudbase\functions\` + `C:\briefdesk\scripts\` 同源副本，
**不含任何密钥**；`cloudbase/deploy.py` 部署 CloudBase 时也继续读 index.html 字面量，不受本机覆盖影响）。

### 4.2 部署（默认 staging；安装 ≠ 启用）
```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web
python deploy\ecs_cron.py install --dry-run     # 只打印计划（env 全部脱敏，不连 ECS）
python deploy\ecs_cron.py install               # 安装：staging 后端；三个 timer 全部 disabled
python deploy\ecs_cron.py status                # 只读：timer/心跳/env 键名/base
```
- `install` 结束会 `systemctl disable --now` 三个 timer（**默认禁用，不会产生任何写库**）。
- 环境变量：`CB_BASE/CB_KEY`（云函数包装层读）、`CLASS_CB_BASE/CLASS_CB_KEY`（同源脚本读）、
  `CLASS_ADMIN_SID/CLASS_ADMIN_NAME`（`rpc/class_verify`，生产服务凭据）、`XGJ_*`（学工记）、
  `CLASS_JOB_HEARTBEAT=1` / `CLASS_JOBS_STATE` / `CLASS_HEALTH_RUNNER=ecs-timer`。
  值由本机 `scripts/sync_power_cloud.py` 常量 + `secrets\xjg-token.json` 读取后写入 ECS 600 文件；
  **不打印、不入库、不进 git**。
- 切流后重装到生产路径（**仍不启用**）：
  ```powershell
  python deploy\ecs_cron.py install --backend live --allow-live
  ```
  `--backend live` 不带 `--allow-live` 会被拒绝（切流前 `/v1/rdb/rest/*` 仍反代 CloudBase，误用会写 CloudBase）。
  `--base` 指向 CloudBase 网关一律拒绝。

### 4.3 启用 / 停用 / 回滚
```powershell
python deploy\ecs_cron.py smoke --job health_probe   # 手动跑一轮（timer 仍禁用；只允许 staging 后端）
python deploy\ecs_cron.py enable --confirm           # 切流后启用
python deploy\ecs_cron.py disable                    # 停用（保留文件/心跳）
python deploy\ecs_cron.py uninstall [--purge --confirm]  # 删 unit；--purge 连 env/代码/心跳
```
**切流顺序（jobs 侧）**：
1. `install --backend live --allow-live`（仍禁用）；
2. 切 Caddy `/v1/rdb/rest/*` → 自建 PostgREST；
3. `enable --confirm` 启用 ECS timer；
4. **先停 CloudBase 端三个定时触发器**（控制台/`tcb`）——否则同一批 `service_health`/
   `power`/`homework` 行会双写跳变（CloudBase 写云库、ECS 写自建库；切流后云库不再被读，但
   若 CloudBase 仍跑会持续消耗额度/产生歧义数据）。
5. 观察 30 分钟：`status` 看三个 timer 的 NextElapse + 心跳 + `health_beat` 的 cloud 行。

**回滚（任一步失败）**：
1. `python deploy\ecs_cron.py disable`（ECS timer 全停）；
2. 恢复 CloudBase 端三个定时触发器；
3. 本机 `cloud.env` 删除 `CLASS_CB_*` 行（回 CloudBase）；
4. 需要彻底清理：`uninstall --purge --confirm`。

### 4.4 心跳契约（`health_beat.py` 读取，默认关闭）
每个 job 每轮写 `/var/lib/class-tools/jobs/state/<row_id>.json`（600，原子写）：
```json
{"row":"cloud_power_sync","job":"power_sync","runner":"ecs-timer","at_ms":1794980178216,
 "ok":true,"rc":0,"ms":1234,"host":"class_tool","version":"2026-11-18.p3","backend":"staging"}
```
`CLASS_JOB_HEARTBEAT=1` 时（ECS `jobs.env` 已固定写入）`health_beat.collect_cloud()` 会：
- `cloud_power_sync` / `cloud_xgj_sync`：数据年龄判定的原 detail **不变**，额外加 `meta.job`
  （runner/age_min/ok/stale/rc/ms）；心跳新鲜且 `ok=false` 而数据行仍 ok → 降级 `warn`，
  detail 追加「（ECS 定时任务上轮失败）」；
- `cloud_health_probe.meta.runner = ecs-timer`（CloudBase 云函数路径仍为 `cloudbase-function`）。

## 5. 健康/诊断双后端适配（不破坏诊断页契约）

- **18 行 id、名称、分组、状态语义、15 分钟巡检心跳降级全部不变**（诊断页只读
  `status/detail/checked_at/meta.paused`；新增 meta 字段不影响渲染）。
- 只新增 meta：
  | 行 | 新增 meta | 值 |
  |---|---|---|
  | `cloudbase` | `backend` | `cloudbase` / `staging` / `selfhosted`（探测的当前后端） |
  | `cloud_power_sync` | `job` | ECS timer 心跳（见 §4.4；开关关闭时无此字段） |
  | `cloud_xgj_sync` | `job` | 同上 |
  | `cloud_health_probe` | `runner` | `cloudbase-function` / `ecs-timer` |
- `cloudbase` 行探测的 base 就是当前 `CLASS_CB_BASE`（未设=CloudBase 网关）：本机 `health_beat`
  的 cloud 8 行（`--all-rows` 应急路径）与 ECS `health_probe` job 都自动跟随。
- 双写冲突：**同一时刻只能有一个 `health_probe` 在写 cloud 8 行**。切流时必须先停 CloudBase
  定时触发器再 `enable` ECS timer（见 §4.3）。
- 开关关闭（默认）→ 与迁移前完全一致：按 `public.power.updated_at` / `public.homework.ts` 数据年龄判定。

## 6. 测试与验收记录（2026-11-18 实测）

脚本：`C:\briefdesk\scripts\tests\test_cloud_backend.py`（全部离线、不读真实 token）。

| 组 | 断言 | 结果 |
|---|---|---|
| A 解析优先级 | 默认=index 字面量；env>file>index；文件格式（注释/export/引号）；无 scheme 拒绝；backend 归类；describe/CLI 不泄漏 key | PASS |
| B 脚本默认/覆盖 | 5 个直接入口 + `health_beat._cb_config`：不设覆盖=index；设置后=覆盖值 | PASS |
| C 心跳默认关闭 | 未开 `CLASS_JOB_HEARTBEAT` → 不读心跳；开启后读 3 行；坏 JSON 忽略 | PASS |
| D 心跳合并 | ok 心跳只加 meta（detail 不变）；失败降级 warn+追加文案；过期只标 stale；None 原样返回 | PASS |
| E 契约不变 | `cloud_health_probe` detail「本轮完成 · 8 行 · 321ms」不变，runner 进 meta；默认 runner=cloudbase-function | PASS |

合计 **23/23 PASS**。相关回归：

| 既有测试 | 结果 |
|---|---|
| `scripts/tests/test_diag_agent.py`（全 mock） | 36/36 PASS |
| `scripts/tests/test_oppo_push.py` | 14/14 PASS |
| `scripts/tests/test_hw_auto_xgj.py` | 46/46 PASS |
| `scripts/tests/test_notice_threads.py` | 24/24 PASS |
| `scripts/test_notice_merge.py`（含 sync_notices_cloud 字段/写入断言） | ALL PASS |
| `scripts/test_notice_filters.py` / `test_supplements.py` / `test_notice_summary_style.py` | 5/5 PASS / ALL PASS / ALL PASS |
| `scripts/sync_power_cloud.py --dry-run --limit 1`（默认 CloudBase 路径、不写云） | 网关出数 ok=1/1，exit 0 |
| `scripts/cloud_backend.py --check`（默认解析=CloudBase，只读） | `backend=cloudbase … http=200 110ms -> ok` |
| `scripts/tests/test_notice_time.py` | 275 PASS / 5 FAIL —— **已知历史漂移**（`ai_brief.py` CACHE_VER=10 vs 测试期望 8、supplement target 匹配），与本次改动无关（未改 ai_brief/notice_time；该文件 2026-11-18 13:28 由并行会话修改） |
| `health_beat.py --once --dry-run` | local 10 行 ok=10，exit 0，未写云端 |
| `collect_cloud(dead base)` 冒烟 | 8 行、无异常退出；`cloudbase.meta.backend=selfhosted`（按传入 base 正确归类） |
| 心跳链路模拟 | `cloud_power_sync.meta.job.ok=true`、`cloud_xgj_sync.meta.job.ok=false`；`cloud_health_probe.meta.runner=ecs-timer` |

`deploy/ecs_cron.py` 本地守卫测试：

| 用例 | 预期 | 结果 |
|---|---|---|
| `install --dry-run` | 打印计划，所有凭据 `***` | PASS |
| `install --backend live`（无 `--allow-live`） | 拒绝 | PASS |
| `install --base <CloudBase 网关>` | 拒绝 | PASS |
| `enable`（无 `--confirm`） | 拒绝 | PASS |
| `uninstall --purge`（无 `--confirm`） | 拒绝 | PASS |
| `smoke --dry-run` | 打印脚本（只允许 staging 的远端守卫） | PASS |

**staging 验证（P1 就绪后 2026-11-18 14:15–14:18 实测，全部通过）**：

| 用例 | 结果 |
|---|---|
| staging 可达性：`GET http://121.196.47.2/v1/rdb/rest-next/` | HTTP 200（OpenAPI 121,708 B） |
| `python deploy\ecs_cron.py smoke --job health_probe` | **ok:true / rc=0 / ms=575→1920，8 行 patched**；rows_detail：cloudbase ok(HTTP 200·3ms)、site_static/site_tls warn(备案暂停)、dns_domain ok(已暂停)、tt_cloud ok(7.2h)、cloud_power_sync ok、cloud_health_probe ok |
| `smoke --job power_sync` | **ok:true / rc=0 / ms=7073**；17/17 房间 PATCH 到 staging `power` + 17 条 `power_history`，cloud_fail=0 |
| `scripts\tests\staging_smoke.py`（测试账号，见下） | **26 PASS / 0 FAIL** |
| 本机 `health_beat --once --all-rows --dry-run` + 临时 `CLASS_CB_BASE`=staging | **18 行 ok=15 warn=3 down=0 unknown=0**，exit 0（dry-run 不写；cloudbase 行探测 staging HTTP 200 59ms） |
| `cloud_backend.py --status/--check` + 临时 `CLASS_CB_BASE`=staging | `backend=staging base_source=env`；`--check` HTTP 200 **69ms** → ok；移除临时 env 后回 `backend=cloudbase base_source=index`（生产默认未改） |

`staging_smoke.py`（测试账号 `3260799999/测试账号`，守卫复用 `web/tools/tests/_test_account.py`；
**默认只允许 base 含 `/rest-next/`，拒绝 CloudBase/生产地址**）实测明细：
- 读链路：`class_verify` 200/ok（token 64 位，不打印）→ `class_members` 200（**70 人**，含 seat/sid/name/role/badge/is_admin，测试身份被过滤）→ `class_notices_meta` 200（**125 行**，body lazy 无 data URI）→ `notices`/`homework`/`power`/`service_health`(18 行)/`userdata` 只读全部 200；
- RLS 负例：匿名读 `notices`/`service_health` 均为空数组（200）、无 token `class_members` 返回 `[]`（CloudBase 同契约）、匿名写 `water_room` 401；
- 单条写入 + finally 清理：`water_room` 插入 QA 行 **HTTP 201** → 读回一致（persons=4）→ finally **DELETE 204** → 读回 0 行（无残留）；
- 心跳双后端端到端：staging `service_health` 中 `cloudbase.meta.backend=staging`、`cloud_health_probe.meta.runner=ecs-timer`、`cloud_power_sync.meta.job={runner:ecs-timer, ok:true, age_min:0}`、状态 ok —— 证明「ECS timer 写心跳 → health_probe 读心跳并合并 meta → 测试账号 API 读回」全链路打通。
- 演练后残留检查（测试账号读回）：`water_room` QA 行 **0 条残留**；staging 表计数（测试账号可见范围）：
  `notices` 165 / `homework` 14 / `power` 17 / `service_health` 18 / `marks` 7 / `userdata` 1 / `water_room` 3。

（P1 staging 之前 13:31/13:36/13:41 三次探测均 404，故当时阻塞；现全部通过。）

**ECS 安装**（截至本节撰写）：见 §7。

## 7. ECS 安装状态（实测，2026-11-18 13:34–13:40）

> 执行：`python deploy\ecs_cron.py install`（系统 python 3.12 + aliyunsdkcore，经云助手 RunCommand；
> 13:34 首装 7 文件 → 13:35 补装 `cloud_backend.py`（8 文件）→ 13:39 第三次重装同步
> `health_beat.py` 的 sys.path 守卫（内容语义等价）；最终 `installed_at=2026-11-18T13:39:42+0800`）。

| 项 | 实测结果 |
|---|---|
| 上传/解码 | 8 个文件逐片上传 + `python3 -m py_compile` 全过（`decode-ok`） |
| 代码位置 | `/opt/class-tools/jobs/{jobs_runner.py,cloud_backend.py}` + `power_sync/`、`xgj_sync/`、`health_probe/` |
| `jobs.env` | 14 个键写入 `/etc/class-tools/jobs.env`，**600 root:root**，回显仅键名（`env installed: keys=CB_BASE,…`） |
| 后端 | `backend=staging base=http://121.196.47.2/v1/rdb/rest-next/`（install 时探活 404 → 已提示「P1 未就绪，timer 保持禁用」并继续安装） |
| systemd | 三组 `class-tools-job-*.{service,timer}` 安装 + `daemon-reload`；`enabled=disabled`、`active=inactive`（**默认全部禁用**） |
| self-check | `jobs_runner --self-check`（以 www-data 运行）：三个 job `import OK`；`target backend=staging`；`self-check OK` |
| marker | `/opt/class-tools/jobs/INSTALLED.json`（version=2026-11-18.p3、jobs/cron/service、8 文件 sha256、timers=disabled） |
| smoke（13:36，staging 未就绪时） | `smoke --job health_probe` → `status=Failed exit=1`，`{"ok":false,"rc":1,"result":{"error":"class_verify failed: HTTP 404 None"}}`；心跳落盘 `ok=false` —— runner/心跳链路正常，失败原因就是当时 P1 staging 404 |
| smoke（14:15 P1 就绪后） | `health_probe` → **ok:true rc=0 ms=575**（8 行 patched）；`power_sync` → **ok:true rc=0 ms=7073**（17/17 power + 17 history 写 staging）；`health_probe` 二跑 → ok:true ms=1920，`cloud_power_sync.detail=最近同步 12 秒前` |
| `status` 复核 | 三个 timer 仍 `enabled=disabled active=inactive`（smoke 是手动 runner，不启用 timer）；心跳：`cloud_health_probe` ok / `cloud_power_sync` ok；env 仅键名 |

结论：**ECS 侧已就绪但整体未启用**（timer 全禁用）；staging 冒烟已全部通过，P2 可随时用
`smoke`/`staging_smoke.py` 做影子验证；P4 切流后 `install --backend live --allow-live` +
`enable --confirm` 即可（仍保持“安装≠启用”）。

## 8. 待办 / 后续

- [x] ~~P1 staging 路由就绪后补跑 staging 读链路 + 单条测试写入（测试账号，finally 清理）~~ → 2026-11-18 14:15–14:18 完成，**26/26 PASS**（见 §6）；
- [x] ~~P1 就绪后重跑 `smoke --job health_probe` 与 `smoke --job power_sync`（staging 库）~~ → 均 ok:true / rc=0（见 §6/§7）；
- [ ] `smoke --job xgj_sync`（staging）：依赖外部「班级小管家」Token 有效性，未在本次执行（避免测试期外部账号风险）；P2 若需要再单独跑；
- [ ] **切流前**：`web/jwxt/tt_cloud.py` 支持自建 base —— Lead 已补 `CLASS_CB_BASE/CLASS_CB_KEY` 覆盖，
      但注意其条件是 `if base and key`（**两个都设才生效**，只设 base 会回退 index.html）；切流时 cloud.env 里
      `CLASS_CB_BASE` 与 `CLASS_CB_KEY` 一并设置即可，或把该处改为「base 优先、key 回退 index」；
      `ppt/agent.py` 已补（`CFG_BASE` 只认 base、`_read_publish_key` 只认 key，二者独立，单设 base 即可）；
- [ ] P2 影子验证：网页走 `/v1/rdb/rest-next/` 全量回归（Lead/网页会话主导）；
- [ ] P4 切流：按 `CUTOVER.md` 顺序（Caddy → 本机 cloud.env → ECS timer → 停 CloudBase 定时器）；
- [ ] CloudBase 到期前（2026-12-10）确认 3 个云函数/触发器已停用、ECS timer 稳定运行 ≥ 24h；
- [ ] 可选加固：`jobs.env` 里若长期不更换 XGJ token，到期前更新 `secrets\xjg-token.json` 后重跑 `install`（不启用不变）。

## 9. 本次改动文件

本机（`C:\briefdesk`，不在 git 仓库）：
```
scripts/cloud_backend.py            新增：唯一解析入口 + CLI（--status/--env-example/--check）
scripts/sync_notices_cloud.py       cb_config → cloud_backend.resolve
scripts/sync_power_cloud.py         cb_config → cloud_backend.resolve
scripts/health_beat.py              _cb_config → cloud_backend；新增后端归类 + ECS timer 心跳读取/合并（默认关闭）
scripts/diag_agent.py               cb_config → cloud_backend
scripts/sync_class_roster.py        cb_config → cloud_backend
scripts/hw_auto/sync_homework_cloud.py  cb_config → cloud_backend（含 sys.path 注入）
scripts/check_admin_notices.py      改走 cloud_backend（只读）
scripts/check_cloud_file_notices.py 改走 cloud_backend（只读）
scripts/test_league_visibility.py   cb_config → cloud_backend；自建后端下主动拒绝运行（遗留脚本）
scripts/web_pause.py                文档注明覆盖开关（实现经 health_beat）
scripts/tests/test_cloud_backend.py 新增单测 23 项
scripts/tests/staging_smoke.py      staging 冒烟（测试账号；只允许 /rest-next/；读链路+RLS负例+单条写/finally 清理+心跳 meta）
cloudbase/deploy.py                 注释：部署 CloudBase 云函数故意不跟随 CLASS_CB_* 覆盖
cloudbase/functions/power_sync/sync_power_cloud.py   = scripts 同源刷新
cloudbase/functions/health_probe/health_beat.py      = scripts 同源刷新
```
仓库（`C:\Users\Ko_Li\.openclaw\workspace\web`，未 commit，Lead 统一提交）：
```
deploy/functions/README.md
deploy/functions/jobs.env.example
deploy/functions/jobs_runner.py
deploy/functions/{power_sync,xgj_sync,health_probe}/*     ← CloudBase 云函数源码副本（脱敏）
deploy/ecs_cron.py
deploy/migration/PIPELINE.md         ← 本文件
```

## 10. 红线自查

- [x] 不设任何开关时，本机生产脚本行为与迁移前完全一致（测试 A01/B01；默认仍 CloudBase）；
- [x] **未写 CloudBase**：全部验证只读 CloudBase（`--check` 200）；所有写操作只发生在 **staging 自建库**
      （ECS `smoke` 的 health_probe 8 行 / power_sync 17 行 + 17 history、`staging_smoke.py` 的 water_room
      单条写+删）；ECS timer 全程 disabled；
- [x] 未改 `web/tools/index.html`、未改 P1 的 `ecs_pg.py`/`ecs_site.py`；`web/jwxt/tt_cloud.py`、
      `ppt/agent.py` 的 CLASS_CB_* 覆盖由 Lead 补（本任务仅确认，未改）；
- [x] 未打印/未复制任何 secret；`--dry-run` 对 env 值全部 `***`；jobs.env 只在 ECS 600 文件；
      测试输出不含 token（class_verify token 只报长度）；
- [x] 测试账号唯一化：`staging_smoke.py` 只用 `3260799999/测试账号`（复用 `_test_account.py` 守卫）；
      未使用真实同学/管理员账号做测试；ECS 定时任务冒烟属「生产服务」路径，其内部用服务凭据
      `CLASS_ADMIN_*` 换 token（不用于测试断言、不打印）；
- [x] 未 `git commit`（Lead 统一提交）。
