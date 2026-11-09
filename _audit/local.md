# 本机（Windows）侧服务与自动化调度现状审计 — task-3

- 审计员：local-auditor（Team Lead: lead）
- 审计时间：2026-11-09 22:08 – 22:15（Asia/Shanghai, UTC+8）
- 主机：旅行者 Windows 电脑，`KO_LINK` / 用户 `Ko_Li`；`LastBootUpTime=2026-11-09 21:35:39`（本次开机约 38 分钟）
- 范围：`C:\briefdesk\`（scripts/logs/data/secrets）、计划任务、本机监听服务、本机→阿里云 ECS 推送通道、交付端（网页/小程序/安卓）
- 只读声明：全程只用只读命令与只读 GET；**未启停服务、未运行/修改计划任务、未运行 push/sync/health_beat/watchdog 等写操作脚本、未发消息、未读 secrets 内容**（`secrets\` 仅看文件名/大小/mtime）。`web_pause.py --status` 按其文档「只读打印当前值，不写库」执行（见 §9 证据 E11）。

> ⚠️ 方法学限制：本会话的 `Get-NetTCPConnection` / `netstat` 视图不完整（多个监听端口 `OwningProcess=0`，且只列出 13 条 LISTENING，与 HTTP 实测（18789/3000/11434 均可达）矛盾，疑为沙箱网络视图受限）。端口归属统一用 **`netstat -ano` + `Win32_Process.CommandLine` + HTTP 实测**三方交叉确认；无法确认处标「未验证」。

---

## 0. 结论速览（8 条）

1. **本机采集链路整体在线**：qqflow `:5032` / weflow `:5033` / briefdesk `:3000` / detect_docs watcher 全部 healthy（`watchdog.log` 22:10:03 `round done: qqflow=OK weflow=OK briefdesk=OK detect_docs=OK coverage=OK`）；各采集日志 22:09–22:13 持续写入。
2. **21:35 开机自愈有效**：本次开机后 watchdog 在 21:36:58–21:37:09 检测到 3 个服务 DOWN 并全部自动拉起（qqflow→18864、weflow→33036、briefdesk→20636），后续 `coverage=OK`。
3. **本机→ECS 简报推送通道活跃**：`detect_docs.py --watch --rebuild` 重建后调 `push_to_cloud.py`；最后推送 **21:41:01（page 6,166,576B）/ 21:41:06（data 6,093,899B）**。ECS `http://121.196.47.2/api/status` 返回 `updatedAt=2026-11-09T21:41:02+0800`、`sha256=d2d9221c…`，**与本地 `notice-board-live-demo.html`（6,166,576B）逐字节一致**；`C:\briefdesk\secrets\cloud.env` 存在（103B，mtime 2026-11-03 21:26:12，未读内容）。
4. **本机→CloudBase 写入通道活跃**（每小时/每轮都有成功日志）：notices `67/67`（21:41:15）、power `17/17` + power_history `17` 条（21:46:28）、homework auto `2/2`（21:39:23）、service_health 本机 10 行 `patch=10`（22:10:04）、diag_analysis 2 条（22:13:00）。
5. **17 个计划任务中与项目相关的 8 个全部 Ready、LastResult=0**；关键调度：Watchdog 每 5 分钟、DiagAgent 每 1 分钟（+登录后 30s）、Homework Auto 每 2 小时、ClassPowerSync 每小时 :46、JwxtTimetableSync 每日 07:00（+登录后 2 分钟）、Clients/OpenClaw 仅登录触发。
6. **网页暂停开关与 DNS 现状不一致（风险）**：`web_pause.py --status` = `paused=false`（updated_at `2026-11-07T07:47:14+08:00`，历史日志显示 07:47:10 开、07:47:15 又关），但 `tool.furina.fun` 已 `NXDOMAIN`（`furina.fun` 仅 SOA）。按设计，paused=false 时云端 health_probe 会按「真实探测失败」上报 site_static/site_tls/dns_domain，而不是「已按备案暂停」的豁免提示。
7. **交付端「本机可见状态」**：网页 `index.html` **732,621B / APP_VER 2.0.0 / sha256 65610511…**（HANDOFF 记载 19:59 已上传 OSS 且 MATCH，DNS 暂停期 URL 不可访问）；小程序代码 **2.0.0**，最新 2026-11-08/09 改动**均待上传**（本机无法验证微信后台）；安卓 versionName **3.2.0**/versionCode 8，最新 `app-release.apk` **2,593,869B / 18:52** 未复制进 `artifacts/`（交付副本仍为 00:16 的 3.2.0 / 2,577,485B），桌面当前无 APK。
8. **纯本机依赖多、关机即停**：QQ/微信客户端→qqflow/weflow、briefdesk、detect_docs+AI 管线、附件/OCR/压缩包、教务抓取、hw_auto 浏览器收集、diag_agent、watchdog/health_beat、ECS 简报推送都依赖本机；已上云但仍保留本机兜底的是 `power_sync`（云函数每小时:01 + 本机 :46）与 `xgj_sync`（云函数每 2h:20 + 本机 hw_auto 每 2h）。**CloudBase 环境 2026-12-10 到期**（文档明示）是最大外部到期风险（task-2 详查）。

---

## 1. 计划任务表（`Get-ScheduledTask` / `Get-ScheduledTaskInfo`，查询时间 2026-11-09 22:09:08）

| 任务名 | 触发器 | 动作 | 状态 | 上次运行 | 上次结果 | 下次运行 | 备注 |
|---|---|---|---|---|---|---|---|
| `Briefdesk Watchdog` | TimeTrigger start 2026-11-04T21:45 每 **PT5M**；LogonTrigger 延迟 1 分钟 | `C:\briefdesk\venv\Scripts\pythonw.exe "C:\briefdesk\scripts\watchdog.py"` | Ready | 2026-11-09 22:05:01 | 0 | 22:10:00 | StartWhenAvailable=True；ETL PT5M；Hidden=True；跑 4 服务自愈+health_beat |
| `BriefdeskDiagAgent` | TimeTrigger start 2026-11-09T18:26:56 每 **PT1M**；LogonTrigger 延迟 30s | `…\venv\Scripts\pythonw.exe "C:\briefdesk\scripts\diag_agent.py" --once`（cwd `C:\briefdesk`） | Ready | 22:08:57 | 0 | 22:09:56 | 2026-11-09 新增登录触发器；v1.1.0（catch-up+自动修复扫描） |
| `Class Homework Auto` | TimeTrigger start 2026-11-04T23:02 每 **PT2H**；LogonTrigger 延迟 3 分钟 | `C:\Users\Ko_Li\AppData\Local\Programs\Python\Python312\pythonw.exe "C:\briefdesk\scripts\hw_auto\run_hw_auto.py"` | Ready | 21:38:54 | 0 | 23:02:00 | ETL PT72H；Hidden=False |
| `Class Tools Clients` | LogonTrigger 延迟 **1 分 30 秒** | `…\venv\Scripts\pythonw.exe "C:\briefdesk\scripts\ensure_clients.py"`（cwd scripts） | Ready | 21:37:24 | 0 | — | 登录后拉起 QQ/WeChat 客户端（幂等） |
| `ClassPowerSync` | TimeTrigger start 2026-11-05T22:46 每 **PT1H** | `"…\venv\Scripts\pythonw.exe" "C:\briefdesk\scripts\sync_power_cloud.py"` | Ready | 21:46:01 | 0 | 22:46:00 | **DisallowStartIfOnBatteries=True、StartWhenAvailable=False**（本机无电池，实测空电池列表，影响存疑）；ETL PT72H |
| `JwxtTimetableSync` | DailyTrigger start **07:00**；LogonTrigger 延迟 2 分钟 | `…Python312\pythonw.exe "…\web\jwxt\sync.py" --out "…\web\tools\tt.json" --term-start 2026-08-31 --deploy`（cwd `web\jwxt`） | Ready | 21:37:54 | 0 | 2026-11-10 07:00 | ETL PT30M；`tt.json` mtime 21:37:58 佐证成功 |
| `OpenClaw Gateway` | LogonTrigger | `C:\Users\Ko_Li\.openclaw\gateway.cmd` | Ready | 21:35:53 | 0 | — | node gateway :18789，进程 24272 起于 21:35:59 |
| `OpenClaw Gateway Watchdog` | TimeTrigger start 2026-09-15T12:16 每 **PT5M**；LogonTrigger 延迟 1 分钟 | `…Python312\pythonw.exe "C:\Users\Ko_Li\.openclaw\gateway-watchdog.py"` | Ready | 22:06:02（22:13 复核 22:11:02） | 0 | 22:11:00 | Hidden=False |
| `OpenClaw Update Once` | 一次性 start 2026-10-10T23:58 | `C:\Users\Ko_Li\.openclaw\update-now.cmd` | Ready | 2026-10-10 23:58:00 | 0 | — | 陈旧一次性任务，与班级工具站无关 |

- 全机共 **221** 个计划任务；按动作路径（briefdesk/workspace/openclaw/qqflow/weflow/qqdocs/jwxt）全量过滤后，与项目相关的就是上表 9 条，**无遗漏任务**。
- 未运行、未修改、未导出/导入任何任务；无任务处于 Running 状态（均为 Ready）。

---

## 2. 本机常驻服务 / 端口表（`netstat -ano` + `Win32_Process` + HTTP 只读 GET，2026-11-09 22:09–22:10）

| 端口 | 服务 | PID / 启动时间 | 绑定/命令 | 健康实测（只读 GET） | 判定 |
|---|---|---|---|---|---|
| **5032** | qqflow-server **0.10.0**（QQ 消息采集） | 18864，2026-11-09 21:36:58 | `…\bin\qqflow-server\qqflow-server-0.10.0-x86_64-pc-windows-msvc\qqflow-server.exe --port 5032 --log info`；netstat 显示 127.0.0.1 | `GET /health` → **200** `{"account":"ready","status":"ok","version":"0.10.0"}`（65ms） | ✅ 在线 |
| **5033** | weflow-server **0.10.0**（微信消息采集） | 33036，21:37:04 | `…\bin\weflow-server\weflow-server-0.10.0…\weflow-server.exe serve --host 127.0.0.1 --port 5033 --log info` | `GET /health` → **200** 同上 payload（2ms） | ✅ 在线 |
| **3000** | briefdesk（本地通知/简报聚合，FastAPI+UI） | venv 父进程 20636 起 21:37:09；子进程 9124 `-m briefdesk` | 代码写死 `host="localhost"`（`app\briefdesk\main.py` L292）；`server_port` 默认 3000（`config.py` L180） | `GET /api/status` → **200**：sources.qqflow=online、`lastSync=2026-11-09T13:47:53Z`（21:47:53+08）、syncing=false、syncProgress done=true、lastError=null；`GET /` → 200，31,161B，title「简报台」 | ✅ 在线 |
| 8090 | briefdesk-board 云同步 API（**仅云端**运行） | — | `C:\briefdesk\cloud\server.py` 默认 `PORT=8090`；ECS systemd `uvicorn server:app --host 127.0.0.1 --port 8090` | `http://127.0.0.1:8090/api/status` → 连接被拒绝 | ⚪ 本机未运行（合理：该服务部署在 ECS，见 §4） |
| 11434 | Ollama（AI 本地兜底，`cloud_ai.py` → qwen3:14b） | 33948 + ollama app 14588，21:37:09 | `cloud_ai.py` L28 `http://127.0.0.1:11434/api/chat` | `GET /api/tags` → **200**，920B | ✅ 在线（主用 DeepSeek，兜底就绪） |
| 18789 | OpenClaw Gateway（本机 AI/自动化代理） | node 24272，21:35:59 | `node …openclaw\dist\index.js gateway --port 18789` | `GET /` → **200**，20,524B | ✅ 在线（非班级工具站直接依赖，但 diag/自动化生态依赖） |
| 9343 | Edge 远程调试端口（hw_auto `collect.js` 用） | 按需 | `collect.js` L14 `PORT=9343`，Edge profile `C:\briefdesk\secrets\qq-login-profile` | 采集运行时临时监听；当前未实测 | ⚪ 按需启动，未验证 |
| 18080/18081 | Cyberheart 系统代理 `core.exe`（与本项目无关） | 38100 | — | — | ℹ️ 忽略（非本项目） |

- 进程父链：qqflow/weflow/briefdesk/detect_docs 四个常驻均由 **watchdog 经 `run_hidden.py` 以 pythonw 隐藏窗口拉起**（`watchdog.log` 21:36:58–21:37:09 记录 `DOWN -> started hidden pid=…`）。
- **日志活性**（`C:\briefdesk\logs` 最近写入，22:09:16 实测）：docs-detect 22:09:16、wechat-media 22:09:16、ai-triage 22:09:15、ai-cloud 22:13:00、qq-context 22:09:14、qq-file 22:09:14、ocr 22:09:13、diag-agent 22:13:00、health-beat 22:10:04、watchdog 22:10:03、power-sync 21:46:28、cloud-push 21:41:06、hw-auto 21:39:23、ensure-clients 21:37:24 → 采集/分析/心跳链路均活跃。

### 2.1 detect_docs watcher（纯本机进程，`pythonw`，非端口服务）

- 命令：`"C:\Users\Ko_Li\AppData\Local\Programs\Python\Python312\pythonw.exe" C:\briefdesk\scripts\detect_docs.py --watch --rebuild`（父为 watchdog 拉起），启动 21:37:09，PID 2508/33660。
- 循环：每 **60s** 扫描一次（`detect_docs.py` L562–706 `time.sleep(60)`），QQ 文档/微信/图片/文件/压缩包/AI-triage 变化 → `rebuild_board()`。
- 2026-11-09 22:10:20 最新一轮：`scan: 10 cards, 0 new, total 10, images changed=False`；22:10:24 `wechat media: candidates 0 … total 15`。

---

## 3. 数据管线：脚本 → 输入 → 写入目标

### 3.1 主链路（detect_docs 重建，事件驱动）

```
QQ 客户端(QQNT 本地库)          ┌ detect_docs.py --watch（每60s）
  └ dbscan.exe（只读 SQLCipher 拷贝）→ data/docs-detected.json / qq-merged.json
微信客户端(本地库) → weflow :5033 → ai_triage / wechat_media / ocr …
        │
        ├─ ai_triage.py        → data/ai-triage-notices.json / ai-triage-state.json（DeepSeek 分类判断）
        ├─ ai_merged / ai_brief / ai_quality / ai_categories → data/ai-*.json（摘要/质检/动态分类）
        ├─ attachment_digest / content_extract / archive_scan / qq_file_names → data/*.json（附件与内容摘要）
        ├─ build_notice_board.py（briefdesk-plan）→ board-data.json + web/tools/notice-board-live-demo.html（6.1MB）
        ├─ push_to_cloud.py    → 阿里云 ECS  http://121.196.47.2  POST /api/page + /api/data（X-Sync-Token）
        └─ sync_notices_cloud.py → 腾讯 CloudBase public.notices（auto_* 行，PATCH/POST，管理员班级 token）
```

### 3.2 脚本 → 写入目标表

| 脚本（`C:\briefdesk\scripts\`） | 角色 | 写入目标 | 调度/触发 | 最近证据（2026-11-09） |
|---|---|---|---|---|
| `watchdog.py` | 4 常驻服务健康检查/重启；每轮末尾上报健康 | 本地 `C:\briefdesk\watchdog.state.json`；调 `health_beat.py` → CloudBase `service_health`（本机 10 行） | `Briefdesk Watchdog` 每 5 分钟 | watchdog.log 22:10:03 全 OK；rounds=283 |
| `detect_docs.py` | QQ/微信通知总采集与重建编排（--watch 60s） | 本地 `data/docs-detected.json`、`qq-merged.json`；触发 builder / push / sync_notices | 常驻 pythonw（watchdog 拉起） | docs-detect.log 22:10:20 正常轮次 |
| `push_to_cloud.py` | 把 board HTML + board-data JSON 推到 **阿里云 ECS** | ECS `/opt/briefdesk/data/board.html`、`board.json`（HTTP POST） | detect_docs 重建成功后调用（不带 `--build`） | cloud-push.log 21:41:01/21:41:06 成功 |
| `sync_notices_cloud.py` | 富通知板 → **CloudBase** `public.notices` auto 行 | CloudBase PG（`notices`，REST：GET 列表后 PATCH/POST，`auto_*` 归档） | detect_docs 重建后 | docs-detect.log 21:41:15 `notices cloud: 67/67` |
| `sync_power_cloud.py` | 17 间宿舍电费采集→云；追加 history | 先 GET 电费网关 `cloudpaygateway.59wanmei.com:8087`（只读查询），再写 **CloudBase `public.power` + `public.power_history`** | `ClassPowerSync` 每小时 :46 | power-sync.log 21:46:28 `ok=17/17 cloud_rows=17 history_ok=17` |
| `hw_auto/run_hw_auto.py` | 作业编排：scan → node `collect.js`（本机 Edge 登录态）→ build → xgj → 云同步 | 本地 `data/auto-homework.json` 等；调 **CloudBase `public.homework`**（auto_hw_* 行） | `Class Homework Auto` 每 2 小时 | hw-auto.log 21:39:23 `homework cloud: 2/2` |
| `hw_auto/collect.js` | 用本机 Edge profile（`secrets\qq-login-profile`，9343 调试口）抓 QQ 作业详情/腾讯文档 | 本地 `data/qq-homework-details.json`、`tencent-doc-opendoc.json`、`hw-collect-status.json` | 被 run_hw_auto 调 | 21:39 轮次 ok |
| `xgj_homework.py`（`--collect --merge`） | 班级小管家英语作业采集并合并进 `auto-homework.json` | 本地 `data/auto-homework.json`（token：`secrets\xjg-token.json`） | run_hw_auto 内（build 之后、sync 之前） | xgj-homework.log 21:39:22 正常 |
| `health_beat.py` | 本机依赖 10 行健康 → 云端；默认只写 local 10 行（云端 8 行由云函数 `health_probe` 写） | **CloudBase `public.service_health`**（PATCH/POST） | watchdog 每轮末尾（5 分钟） | health-beat.log 22:10:04 `patch=10 failed=0` |
| `diag_agent.py`（v1.1.0） | 诊断代理：心跳/读 `client_diag`→AI 分析写 `diag_analysis`→白名单自动修复写 `repair_tasks`；PGP 解密教务登录请求 | **CloudBase `agent_keys`/`diag_analysis`/`repair_tasks`/`client_diag`(读+标 analyzed)**；本地 `diag-agent.state.json`；执行白名单动作（recheck_health/restart_gateway/web_pause_on|off/sync_power/sync_xgj/refresh_timetable/redeploy_web） | `BriefdeskDiagAgent` 每 1 分钟 | diag-agent.log 22:13:00 `analysis ran items=2 written=2 provider=cloud` |
| `jwxt/sync.py`（`web\jwxt`） | 教务 SSO 抓课表 | 本地 `web/tools/tt.json`；**CloudBase `public.site_assets` id='tt'**（`tt_cloud.py`）；`--deploy` 再调 `web/deploy/sync_tools.py` 上传 OSS | `JwxtTimetableSync` 每日 07:00 + 登录后 | tt.json mtime 21:37:58；任务 LastResult=0 |
| `ai_triage.py` / `ai_brief.py` / `ai_quality.py` / `ai_categories.py` / `ai_merged.py` | AI 识别/摘要/质检/动态分类（DeepSeek，失败落本地 Ollama） | 本地 `data/ai-*.json`、`ai-triage-state.json` | detect_docs 每轮循环 | ai-triage.log 22:09:15 `ai batch provider=cloud ok=True`；ai-cloud.log 22:13:00 `cloud ok model=deepseek-flash ms=2548` |
| `cloud_ai.py` | AI 适配器（OpenAI 兼容 + 本地兜底） | POST `secrets\cloud-ai.json` 中 base（部署记录为 `https://api.deepseek.com/v1`）；兜底 `http://127.0.0.1:11434` | 被各 AI 脚本调用 | 同上 |
| `fetch_qq_images.py` / `ocr_qq_images.py` / `classify_qq_images.py` / `fetch_qq_files.py` / `fetch_qq_file_notices.py` / `wechat_media.py` / `archive_scan.py` / `attachment_digest.py` / `content_extract.py` / `notice_merge.py` | 附件/图片/OCR/压缩包/内容摘要/合并 | 本地 `data/images/`、`qq-files/`、`wechat-media/`、`*.json` | detect_docs 每轮 | ocr.log 22:12:46、wechat-media 22:12:47 正常轮次 |
| `sync_class_roster.py` | CloudBase `rpc/class_members` → 本地名单缓存 | 本地 `data/class-members.json` | detect_docs 需要时 | 文件 mtime 19:06 |
| `sync_audience_rosters.py` / `sync_league_roster.py` | 人群名单/团员名单 | 本地 `data/audience-rosters.json`/`league-members.json`；`private.class_audience`（人群名单设计为同步到 CloudBase） | 人工/按需（未在计划任务中） | —（未验证） |
| `ensure_clients.py` | 登录后确保 QQ（QQNT）/微信（Weixin 4.x）在运行 | 无云写入（仅拉起本地客户端） | `Class Tools Clients` 登录后 90s | ensure-clients.log 21:37:24 |
| `web_pause.py` | 网页暂停开关（CloudBase `public.site_config` id='web'） | **CloudBase `site_config`**（仅 --on/--off 写；--status 只读） | 人工/diag agent 修复动作 | `--status` 22:11:55 见 §9-E11 |

**说明**：`sync_notices_cloud.py`、`sync_power_cloud.py`、`hw_auto/sync_homework_cloud.py` 的 CloudBase 地址/匿名 key 都从 `web/tools/index.html` 的 `var CB` / `var CBK` 解析（公开常量，非机密）；管理员班级 token 缓存在 `secrets\class-token.json`（本审计未读内容，仅确认存在 104B / mtime 2026-11-09 18:27:10）。

---

## 4. 本机 → 阿里云 ECS 简报推送通道（关键结论：通道活跃、内容逐字节一致）

| 项 | 结果 | 证据/时间 |
|---|---|---|
| ECS 探测 | `http://121.196.47.2/api/status` → **200** | `{"ok":true,"updatedAt":"2026-11-09T21:41:02+0800","pageBytes":6166576,"boardBytes":6088469,"sha256":"d2d9221c4af2454e22faf071e420aec242606e3acdb941b3a718a6f002ee8526","counts":{"groups":67,"homework":0,"docs":10}}`（22:10:47 采集） |
| 本地页面 | `web/tools/notice-board-live-demo.html` = **6,166,576B**，mtime 21:40:57，`sha256=d2d9221c…` | `Get-FileHash` 22:10:58 |
| 一致性 | **本地 sha256 == ECS meta sha256（MATCH）** → ECS 最近一次收到并保存的就是本地这一版简报 | 同上 |
| 本地推送日志 | `cloud-push.log`：`21:41:01 page pushed: 6166576 bytes sha256=d2d9221c4af2`；`21:41:06 data pushed: 6093899 bytes`；同日 19:17/19:58/20:41/20:43/21:39 也有成功推送（均成对出现） | 22:10:47 读取 |
| 重建链路日志 | docs-detect.log：`21:40:57 board rebuilt -> 桌面…html` → `21:41:06 cloud push ok` → `21:41:15 cloud notices ok: 67/67` | 22:14:56 读取 |
| 推送逻辑位置 | `detect_docs.py` L67 `PUSH_CLOUD=C:\briefdesk\scripts\push_to_cloud.py`；L321–327 在 `rebuild_board()` 末尾 `run_hidden([PY, str(PUSH_CLOUD)])`（**不带 `--build`，无递归风险**） | 代码阅读 |
| 推送实现 | `push_to_cloud.py`：读 `secrets\cloud.env` 的 `CLOUD_BASE_URL`/`CLOUD_SYNC_TOKEN` → `POST {base}/api/page`（HTML）+ `POST {base}/api/data`（JSON），头 `X-Sync-Token`；返回 `bytes/sha256` 写日志 | 代码阅读 |
| base URL 来源 | `deploy_ecs.py` L12 `HOST="121.196.47.2"`、L118 写 `CLOUD_BASE_URL=http://{HOST}` 到 `secrets\cloud.env` → 与 ECS 实测一致（**未读 cloud.env 内容**） | 代码阅读 |
| `cloud.env` | **存在**，103B，mtime `2026-11-03 21:26:12`（= deploy_ecs 部署日）；未读内容 | `Get-Item` 22:10:24 |
| watchdog 与 ECS | `watchdog.py` **不负责** ECS 推送（它只检查/重启 4 个本机服务并调 health_beat）；ECS 推送唯一入口是 detect_docs 重建后的 `push_to_cloud.py` | 代码 grep |
| 推送节奏 | **事件驱动**（仅有新通知/附件/媒体变化触发 rebuild 时才推），不是定时推送 → 21:41 后无新变化所以 updatedAt 停在 21:41 属正常 | docs-detect.log 22:10:20 `0 new` |
| ECS 服务形态 | 由本机 `C:\briefdesk\cloud\server.py`（FastAPI）+ systemd（`briefdesk-board.service`，uvicorn 127.0.0.1:8090）+ Caddy 80 组成；Caddy 路由见 `deploy_ecs.py` L91–105：`/api/*`→:8090，`/board*`→`/opt/briefdesk/data`，`/`→`/var/www/tool` | 本地副本+部署脚本阅读；**ECS 上实际配置未登录验证** |
| ECS 根站镜像 | `http://121.196.47.2/` → 200，**166,952B**，title「班级工具 · tool.furina.fun」，`sha256=1fefeacae5f205533cdc045ab1cfdad05bce2d0a37468b695540872c02ff5d95` = 本地备份 `web/tools/_backup/index_online_20261103-2240.html` 逐字节一致 → **ECS 根站是 2026-11-03 22:40 的旧版 index 快照**（当前本地 index.html 732,621B），而 `/board.html`（被推送的简报）是最新 | 22:11:07 / 22:14:34 |

> 结论：**「本机仍在向阿里云 ECS 推送简报」成立**（最后实际推送 21:41:01/06，与 ECS updatedAt 21:41:02 吻合，内容 hash 一致）。注意区分：ECS 的**简报通道**是新的；ECS 的**根站页面**是 2026-11-03 旧镜像（是否要更新由 Lead/task-1 决策，本审计未做任何写操作）。

---

## 5. 交付端状态表

| 端 | 版本/标识 | 关键文件事实 | 「是否已上传/发布」判定 | 本机可验证性 |
|---|---|---|---|---|
| **网页** | `APP_VER="2.0.0"` | `web/tools/index.html`：**732,621B**，mtime **2026-11-09 19:58:46**，sha256 **656105117464c6d67106faa4011d5dd806d11d2c0d44760df961488d92e3b420** | HANDOFF.md §19:55 记载：2026-11-09 **19:59 已部署 OSS，`oss_object.py check` = MATCH**（732,621B/65610511…），部署前备份 `tools/_backup/index_online_20261109-1959_preDoneExpired.html`（732,317B，文件存在）→ 本地=线上新；**DNS 暂停期 URL 不可访问** | 本地文件事实 ✅；OSS 线上字节未独立复核（未验证，task-1 可用 `deploy/oss_object.py check`） |
| **微信小程序** | 代码 `VERSION='2.0.0'`（`utils/version.js`，RELEASED_AT 2026-11-05） | `project.config.json`：appid `wx3df9869d229b96c4`、libVersion 3.0.0、`urlCheck=false`；云地址：CloudBase 网关 `tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/` + legacy `https://tool.furina.fun/tt.json`（仅兜底） | **最新代码未上传发布**：README 顶部「2026-11-08（待上传…）」；CHANGELOG 顶部 2026-11-08 待上传 + 2026-11-09 诊断 v2.1「待上传；代码版本仍 2.0.0」；CHANGELOG L96 记录用户曾上传微信后台版本 **2.0.1**（与代码 VERSION 2.0.0 是两套编号）→ 线上正式版内容无法本地判定 | 代码/文档 ✅；微信后台发布状态 **未验证** |
| **安卓** | `versionName="3.2.0"` / `versionCode=8` / `applicationId com.furina.classtools` | ① 最新构建 `app/build/outputs/apk/release/app-release.apk` = **2,593,869B**，mtime **2026-11-09 18:52:17**，sha256 `b9a2922c…`（docs/DIAG_LOGIN_20261108.md §诊断 v2.1 记载 66 suites/817 tests、assembleRelease 2,593,869B）<br>② `artifacts/` 交付副本最新 = `classtools-3.2.0-release-signed.apk` **2,577,485B**，mtime **2026-11-09 00:16:50**，sha256 `1307a06d…`（与 18:52 构建**不一致 → 滞后**）；另有 3.1.0/3.0.0/2.1.1 旧副本 | **交付副本未跟上最新构建**；`docs/RELEASE_BUILD.md` 分发方式 = 自签名 release APK（`key/release.jks` 存在 2,752B）+ 交付副本放 `artifacts/` + adb 安装验证，历史惯例复制到桌面供侧载；**当前桌面无 `.apk`**（只有 2 个 md）→ 最新包是否已分发到手机 **未验证** | 本地文件 ✅；实际分发 **未验证** |
| **后端（供对照）** | CloudBase 环境 `tool-d4gosudok46e0e081` | 本机侧所有写云脚本均验证成功（见 §3.2）；Power/XGJ 云函数已上云（`C:\briefdesk\docs\云端服务迁移_20261106.md`），CloudBase 环境 **2026-12-10 到期** | 本机写出通道正常；云端资源现状属 task-2 范围 | 本机写入通道 ✅ |
| **furina.fun DNS** | 暂停解析 | `Resolve-DnsName tool.furina.fun` → **DNS 名称不存在（NXDOMAIN）**；`furina.fun` 仅返回 SOA（无 A/AAAA） | 2026-11-07 起暂停、等 ICP 备案（与 AGENTS/HANDOFF 一致） | ✅ 实测 |

---

## 6. 分类清单：必须本机 / 已云化兜底 / 纯本机且关机即停

### 6.1 必须本机（依赖本机客户端、本机登录态或校园网）
1. **QQ 消息采集**：QQ 客户端（QQNT）本地库 → `dbscan.exe` → qqflow `:5032`
2. **微信消息采集**：微信客户端本地库 → weflow `:5033`
3. **briefdesk 本地聚合**：`:3000`（看板/SSE/本地数据源）
4. **detect_docs watcher**：QQ 文档/群文件/图片/压缩包扫描与重建（每 60s）
5. **附件/OCR/压缩包处理**：`dbscan.exe`、`qqimages.exe`、RapidOCR、7-Zip（全部本机二进制）
6. **AI 通知识别管线**：ai_triage/ai_brief/ai_quality/ai_categories（调用 DeepSeek 云端 API，但编排/缓存/兜底在本机）
7. **教务课表抓取**：校园网 SSO（本机 IP/网络）+ DPAPI 保存的教务账号
8. **作业自动整理（hw_auto）**：QQ 群作业、腾讯文档、班级小管家全部依赖本机 Edge 登录态（`data\xgj_profile` 619.7MB）
9. **诊断 agent**：读云端 `client_diag`→AI 分析→本机执行白名单修复；PGP 解密个人教务登录请求
10. **本机健康行 + ECS 简报推送**：health_beat 本机 10 行；`push_to_cloud.py`→ECS 简报
11. **客户端守护**：`ensure_clients.py`（登录后拉起 QQ/微信）+ `watchdog.py`（5 分钟自愈）

### 6.2 已云化、但本机仍保留兜底
| 服务 | 云端 | 本机兜底 |
|---|---|---|
| **电费同步 power_sync** | CloudBase 云函数每小时 `:01` | `ClassPowerSync` 每小时 `:46`（`sync_power_cloud.py`，写 `public.power`/`power_history`） |
| **学工记 xgj_sync** | CloudBase 云函数每 2 小时 `:20` | `Class Homework Auto` 每 2 小时（run_hw_auto → xgj_homework.py → `public.homework`） |
| **健康巡检 health_probe** | 云函数每 5 分钟写云端 8 行（cloudbase/site_static/site_tls/dns_domain/tt_cloud/cloud_power_sync/cloud_xgj_sync/cloud_health_probe） | `watchdog.py` 每轮调 `health_beat.py` 写本机 10 行（collector_host/qqflow/weflow/briefdesk/watcher/ai/jwxt/hwauto/qq_client/wechat_client）——互补而非严格兜底 |
| **通知/作业数据** | CloudBase `public.notices`/`public.homework` 承载前端读取 | 本机负责采集与写入（`sync_notices_cloud.py`/`sync_homework_cloud.py`） |
| **课表** | CloudBase `public.site_assets` id='tt' 承载读取（DNS 暂停后主链路） | 本机 `jwxt/sync.py` 抓取并发布；`tt.json` 本地同源文件保留 |

### 6.3 纯本机、关机即停
- qqflow / weflow / briefdesk / detect_docs watcher / 全部附件与 OCR 处理 / AI 通知识别 / 教务抓取 / hw_auto 浏览器收集 / diag_agent / watchdog / health_beat（本机行）/ ECS 简报推送（`push_to_cloud.py`）/ ensure_clients。
- 关机期间：新 QQ/微信消息不进本机库 → 通知/作业/AI 空转；ECS 简报与 CloudBase notices 停止更新（云端 power/xgj 云函数仍可更新部分数据，属 task-2）；本机 diag_agent 停止自动修复（设计为云端留存 `client_diag`、开机后 catch-up 消费）。
- 本次实测开机（21:35:39）后 21:36:58–21:37:09 完成全部服务拉起 → 自愈机制有效。

---

## 7. 状态/配置文件摘要（只读，未贴敏感内容）

| 文件 | 大小/mtime | 摘要 |
|---|---|---|
| `C:\briefdesk\watchdog.state.json` | 1,766B / 22:10:03 | qqflow/weflow/briefdesk/detect_docs 均 `healthy=true, failures=0`；rounds=283；qqflowCoverage：dbTotal=17937、monitored=13、staleGroups=0、status=ok、lastStaleAt 20:40:01（群「2026级信息管理与信息系统」+6256s）、lastRestartResult=ok（re-index 后 account ready，message_count=17702） |
| `C:\briefdesk\diag-agent.state.json` | 931B / 22:09:58 | last_round_at=22:09:58、last_heartbeat=22:09:57、last_analysis_at=22:07:57、last_analysis_items=2、health_sig 已记录；本轮：catchup=false、heartbeat=ok、pgp=ok、login 全 0、backlog_diag=0 |
| `C:\briefdesk\secrets\cloud.env` | **存在** 103B / 2026-11-03 21:26:12 | 仅确认存在性/大小/mtime，未读内容（生成来源：`deploy_ecs.py` 写 `CLOUD_BASE_URL=http://121.196.47.2` + `CLOUD_SYNC_TOKEN`） |
| `C:\briefdesk\secrets\cloud-ai.json` | 存在 178B / 2026-11-05 10:47:12 | DeepSeek AI 配置（未读内容）；运行日志显示 `model=deepseek-flash` |
| `C:\briefdesk\secrets\class-token.json` | 存在 104B / 2026-11-09 18:27:10 | 班级管理员 token 缓存（未读内容） |
| `web_pause --status` | 22:11:55 实测 | `site_config.web: paused=false note=- paused_at=- updated_at=2026-11-07T07:47:14+08:00`（exit 0）；`web-pause.log` 历史：11-07 07:47:10 `--on` → 07:47:15 `--off`（当前为关） |

---

## 8. 异常 / 风险清单

| # | 严重度 | 事项 | 证据 | 影响/建议 |
|---|---|---|---|---|
| A1 | **高（需决策）** | **网页暂停开关 `paused=false` 与 DNS 已暂停不一致** | `web_pause --status` = paused=false（updated 2026-11-07T07:47:14）；`tool.furina.fun` NXDOMAIN；health-beat.log 每轮 `pause=False` | 按设计 paused=true 时云端 health_probe 才把 site_static/site_tls 标「注意·已按备案暂停」；当前会按真实探测失败上报，诊断页可能显示站点异常。是否执行 `web_pause.py --on`（写云操作）需 Lead/用户确认，本审计未执行。 |
| A2 | 中 | **qqflow 覆盖巡检反复 STALE** | watchdog.log 17:25/19:00/20:40 三次 `ALERT qqflow: coverage STALE … -> full re-index` + 自动重启成功；20:40 群「2026级信息管理与信息系统」+6256s；当前 coverage=OK | 采集可能阶段性滞后；auto 自愈有效但根因未查（疑似 QQ 本地 DB 索引增量落后）。 |
| A3 | 中 | **ECS 根站镜像是 2026-11-03 旧版** | ECS `/` = 166,952B sha `1fefeacae…` = 本地 `_backup/index_online_20261103-2240.html`；当前本地 index.html 732,621B | ECS 简报通道（/api/*、/board.html）是最新，但若把 ECS 根地址当备用站点会看到 6 天前旧版；是否更新由 task-1/Lead 决定。 |
| A4 | 中 | **Android 交付副本滞后于最新构建** | build output 2,593,869B(18:52, sha b9a2922c…) vs artifacts 2,577,485B(00:16, sha 1307a06d…)；桌面无 APK | 最新 v2.1 改动未形成交付副本/可能未安装到手机；需复制并核对 sha。 |
| A5 | 低 | **小程序 2026-11-08/09 改动全部待上传** | README/CHANGELOG 顶部「待上传」；代码 VERSION 2.0.0；曾上传后台版本 2.0.1 | 用户上传发布前，线上小程序无诊断 v2/v2.1、课表登录；需提醒用户。 |
| A6 | 低 | wechat-media 每分钟 `fetch_messages filehelper … 404` | wechat-media.log 22:11:41/22:12:47 | 日志噪音（媒体采集对 filehelper 的固定失败），未见功能影响；可观察。 |
| A7 | 观察 | 本机 netstat/Get-NetTCPConnection 视图受限（PID=0、监听列表不全） | 见 §0 说明 | 结论不依赖单一线索，均已交叉验证；后续审计建议用 `netstat -ano` + 进程命令行。 |
| A8 | 风险（外部） | **CloudBase 环境 2026-12-10 到期** | `C:\briefdesk\docs\云端服务迁移_20261106.md` 首段明确 | 到期后云函数/定时器/DB/网关失效（含电费/作业/通知数据服务），需续费或迁移；详见 task-2。 |
| A9 | 低 | `ClassPowerSync` 计划任务 `DisallowStartIfOnBatteries=True` 且 `StartWhenAvailable=False` | 任务查询 | 本机实测无电池（Win32_Battery 为空），影响可能不存在；若将来用笔记本/错过计划点则不补跑，电费数据会缺 1 小时（云端 power_sync 可部分兜底）。 |
| A10 | 低 | 数据目录 893MB（`data\xgj_profile` 619.7MB 浏览器配置 + 备份目录）；日志 13.8MB | 22:13:58 统计 | 磁盘 C: 剩余 251.8GB，无空间风险；备份目录可后续按交付清理规则处理（本次未清理）。 |

---

## 9. 证据附录（命令 + 关键输出 + 时间戳，均为只读）

**E1 计划任务（22:09:03–22:09:08）**
```powershell
$OutputEncoding=[Console]::OutputEncoding=[System.Text.Encoding]::UTF8   # 防中文乱码
Get-ScheduledTask | Where-Object { $_.TaskName -match 'Briefdesk|Class|QQ|Jwxt|Power|Homework|Gateway|OpenClaw|Diag|Watchdog|Tool' }
Get-ScheduledTaskInfo -TaskName 'Briefdesk Watchdog'
```
输出摘要：9 条项目相关任务（见 §1），`State=Ready`、`LastTaskResult=0`；例：`Briefdesk Watchdog LastRun=11/09/2026 22:05:01 LastResult=0 NextRun=22:10:00`、`BriefdeskDiagAgent LastRun=22:08:57 Next=22:09:56`、`ClassPowerSync LastRun=21:46:01 Next=22:46:00`、`JwxtTimetableSync LastRun=21:37:54 Next=11/10 07:00`。

**E2 进程/命令行（22:09:39）**
```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|node|qqflow|weflow' } | Select ProcessId,ParentProcessId,Name,CommandLine
```
关键：`18864 qqflow-server.exe --port 5032`、`33036 weflow-server.exe serve --host 127.0.0.1 --port 5033`、`20636 pythonw -m briefdesk`、`2508/33660 pythonw detect_docs.py --watch --rebuild`、`24272 node …gateway --port 18789`。

**E3 端口/HTTP 健康检查（22:10:12）**
```powershell
Invoke-WebRequest http://127.0.0.1:5032/health   # 200 {"account":"ready","status":"ok","version":"0.10.0"} (65ms)
Invoke-WebRequest http://127.0.0.1:5033/health   # 200 同上 (2ms)
Invoke-WebRequest http://127.0.0.1:3000/api/status  # 200 lastSync=2026-11-09T13:47:53Z, syncing=false
Invoke-WebRequest http://127.0.0.1:8090/api/status  # 连接被拒绝（本机未运行，ECS 才跑 8090）
Invoke-WebRequest http://127.0.0.1:11434/api/tags   # 200 920B（Ollama 兜底在线）
Invoke-WebRequest http://127.0.0.1:18789/           # 200 20,524B
```
注：`Get-NetTCPConnection` 对 5032/5033 返回 `OwningProcess=0`、`netstat -ano` 对 5033 亦返回 0 → 端口归属以进程命令行 + HTTP 实测为准（见 §0 方法学限制）。

**E4 日志活性（22:09:16 / 22:11:21）**
```powershell
Get-ChildItem C:\briefdesk\logs | Sort LastWriteTime -Desc | Select -First 40 Name,Length,LastWriteTime
Get-Content C:\briefdesk\logs\watchdog.log -Tail 8
```
输出摘要：`22:10:02 round start (procs=9)` / `22:10:03 round done (1s): qqflow=OK weflow=OK briefdesk=OK detect_docs=OK coverage=OK`；docs-detect `22:10:20 scan: 10 cards, 0 new`；diag-agent `22:13:00 analysis ran items=2 written=2 provider=cloud`。

**E5 数据目录/磁盘（22:13:58）**
```powershell
Get-ChildItem C:\briefdesk\data -Directory | % { measure size }
Get-PSDrive C
```
输出摘要：data 合计 4,149 文件 / 893,284,260B（xgj_profile 619.7MB、_v2_template_check 75.6MB、qq-files 10.1MB、images 7.0MB、wechat-media 4.2MB）；logs 108 文件 / 13,845,860B；C: 已用 678.4GB、剩余 **251.8GB**。

**E6 状态文件（22:10:24 / 22:09:58 读取）**
- `watchdog.state.json`：4 服务 healthy、rounds=283、coverage ok（摘要见 §7）。
- `diag-agent.state.json`：last_round_at=1794233398371ms（=2026-11-09 22:09:58）、last_analysis_items=2（摘要见 §7）。

**E7 ECS /api/status（22:10:47）**
```powershell
Invoke-WebRequest http://121.196.47.2/api/status -UseBasicParsing
# 200 {"ok":true,"updatedAt":"2026-11-09T21:41:02+0800","pageBytes":6166576,
#      "boardBytes":6088469,"sha256":"d2d9221c4af2454e22faf071e420aec242606e3acdb941b3a718a6f002ee8526",
#      "counts":{"groups":67,"homework":0,"docs":10}}
Get-FileHash web\tools\notice-board-live-demo.html -Algorithm SHA256
# 6,166,576B, sha256=d2d9221c4af2454e22faf071e420aec242606e3acdb941b3a718a6f002ee8526 → MATCH
Get-Content C:\briefdesk\logs\cloud-push.log -Tail 12
# [2026-11-09 21:41:01] page pushed: 6166576 bytes sha256=d2d9221c4af2
# [2026-11-09 21:41:06] data pushed: 6093899 bytes
```

**E8 ECS 根页镜像（22:11:07 / 22:14:34）**
```powershell
Invoke-WebRequest http://121.196.47.2/ -OutFile %TEMP%\ecs_audit\root.html
Get-Item …\root.html   # size=166952 sha256=1fefeacae5f205533cdc045ab1cfdad05bce2d0a37468b695540872c02ff5d95
Get-FileHash web\tools\_backup\index_online_20261103-2240.html -Algorithm SHA256  # 同 hash → 逐字节一致
```

**E9 推送/同步成功记录（22:14:56 读取日志）**
```
docs-detect.log:  [2026-11-09 21:40:57] board rebuilt -> C:\Users\Ko_Li\OneDrive\桌面\班级通知整合_近7天模拟上线_20261103.html
                  [2026-11-09 21:41:06] cloud push ok
                  [2026-11-09 21:41:15] cloud notices ok: notices cloud: 67/67
power-sync.log:   [2026-11-09 21:46:28] power sync: ok=17/17 gateway_fail=0 cloud_fail=0 low=2 history_ok=17 history_fail=0 cloud_rows=17
hw-auto.log:      [2026-11-09 21:39:23] sync rc=0 homework cloud: 2/2 (archived stale: 2) / status {"scan":"ok:11",...}
health-beat.log:  [2026-11-09 22:10:04] publish: 10/10 rows (patch=10 post=0 failed=0 skipped_cloud=0 list_ms=103)
diag-agent.log:   [2026-11-09 22:13:00] round done … heartbeat=ok pgp=ok analysis={"ran":true,"items":2,"written":2,…,"provider":"cloud"}
ai-cloud.log:     [2026-11-09 22:13:00] cloud ok model=deepseek-flash ms=2548
```

**E10 cloud.env（22:10:24）**
```powershell
Get-Item C:\briefdesk\secrets\cloud.env -Force
# EXISTS size=103B mtime=2026-11-03 21:26:12   （未读内容）
```

**E11 web_pause --status（22:11:55，按其文档为只读）**
```powershell
& C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\web_pause.py --status
# site_config.web: paused=false note=- paused_at=- updated_at=2026-11-07T07:47:14+08:00   exit=0
Get-Content C:\briefdesk\logs\web-pause.log -Tail 4
# [2026-11-07 07:38:09] set paused=True … ; [07:38:22] set paused=False …
# [2026-11-07 07:47:10] set paused=True note='备案暂停' ; [07:47:15] set paused=False
Resolve-DnsName tool.furina.fun   # ERROR: DNS 名称不存在
Resolve-DnsName furina.fun        # 仅 SOA
```

**E12 交付端（22:12:05–22:12:58）**
```powershell
(Get-Item web\tools\index.html).Length            # 732621 ; mtime 2026-11-09 19:58:46
(Get-FileHash web\tools\index.html -Algorithm SHA256).Hash  # 656105117464c6d67106faa4011d5dd806d11d2c0d44760df961488d92e3b420
Select-String web\tools\index.html -Pattern 'var APP_VER'   # var APP_VER="2.0.0"
Get-Content mp-class-tools\utils\version.js            # VERSION='2.0.0' RELEASED_AT='2026-11-05'
Get-Content mp-class-tools\CHANGELOG.md -TotalCount 100 # 顶部 2026-11-08 待上传；L96 提到曾上传后台 2.0.1
Select-String android-class-tools\app\build.gradle.kts -Pattern 'versionName|versionCode'  # 3.2.0 / 8
Get-ChildItem android-class-tools -Recurse -Include *.apk | Sort LastWriteTime -Desc
# …\app\build\outputs\apk\release\app-release.apk  2,593,869B  2026-11-09 18:52:17
# …\artifacts\classtools-3.2.0-release-signed.apk  2,577,485B  2026-11-09 00:16:50
Get-FileHash （两者）  # b9a2922c… vs 1307a06d… → 不一致
Get-ChildItem C:\Users\Ko_Li\OneDrive\桌面 -File | ? Name -match '\.apk$'   # 无 APK
```

**E13 项目相关计划任务全量核对（22:13:41）**
```powershell
Get-ScheduledTask | foreach { actions 匹配 briefdesk|workspace|openclaw|qqflow|weflow|qqdocs|jwxt } 
# 仅 9 条（§1 表），无遗漏
```

---

## 10. 未验证项（明确不猜）

1. **OSS 线上 `index.html` 字节/sha256**：DNS 暂停期不可 URL 访问，本审计未运行 `deploy/oss_object.py check`（属 task-1 范围）；HANDOFF 记载 19:59 MATCH。
2. **微信小程序后台当前线上版本 / 最新代码是否已上传发布**：无本机权威记录；README/CHANGELOG 只证明「代码侧待上传」。服务器域名后台配置同样未验证（文档要求：CloudBase 网关必填、`tool.furina.fun` 仅 legacy 兜底）。
3. **Android 最新 APK 是否已分发/安装到手机**：桌面无 APK；`artifacts/` 交付副本滞后于 18:52 构建；实际分发渠道未验证。
4. **CloudBase `public.service_health` 中 site_static/site_tls/dns_domain 当前实际状态值**（以及 `site_config.web` 之外的云端行）：未查询（只读云端表查询可行但属 task-2；本审计只用 `web_pause --status` 读取了 `site_config.web`）。
5. **qqflow coverage STALE 根因**（QQ 本地 DB 增量索引/客户端状态）、**wechat-media filehelper 404 原因**。
6. **ECS 上实际 systemd/Caddy/数据目录状态**：仅依据本机 `C:\briefdesk\cloud\*` 副本与 `deploy_ecs.py` 推断（未 SSH/未云助手执行）。
7. **本机 8090 之外的其他潜在端口**：受 §0 网络视图限制，只列出已实测/进程命令行可确认的端口。

---

*本报告只写入 `_audit/local.md`；未修改任何其他文件、未做任何写操作。*
