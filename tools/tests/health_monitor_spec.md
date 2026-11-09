# 运行状态（依赖服务健康监控）规格 — 2026-11-05

> 本文件是本次改动的**唯一契约**。后端心跳、前端面板、QA 都按此实现，不得各自发挥。
> 关联红线：`web/AGENTS.md` §0（单文件静态站、无构建链、身份门禁、密钥零泄漏）与 §1（设计规范）。

## 0. 需求（用户原话）

> 确保班级工具站的信息获取等功能即使关机重启后也能正常使用，同时为我在班级工具站内部新增一个仅管理员可见工具，显示各个依赖服务是否正常。

拆成两件事：
1. **重启韧性**：关机重启后，通知采集、课表同步、作业整理、本地服务、QQ/微信客户端都能自动恢复。
2. **管理员诊断工具**：站内新增仅管理员可见的「诊断」页，展示各依赖服务状态（正常/注意/异常/离线/未知）。

## 1. 依赖服务清单（必须全部覆盖）

| id | 显示名 | kind | 判定来源 |
|---|---|---|---|
| `cloudbase` | 云端数据库 | cloud | 浏览器实时探测（读 service_health）+ 采集主机上报 |
| `site_static` | 站点资源 | static | 浏览器实时探测（同源 fetch tt.json）+ 采集主机上报 |
| `site_tls` | 站点证书 | static | 采集主机 TLS 握手 + 证书剩余天数 |
| `collector_host` | 采集主机 | local | 心跳新鲜度（采集主机上报时间）+ 开机时间/运行时长 |
| `qqflow` | QQ 消息采集 | local | :5032/health + /api/v1/accounts 有 state=ready 账号 |
| `weflow` | 微信消息采集 | local | :5033/health + /api/v1/accounts 有 state=ready 账号 |
| `briefdesk` | 本地通知服务 | local | :3000/api/status HTTP 200 |
| `watcher` | 文档/通知监听 | local | detect_docs.py --watch 进程 + docs-detect.log 新鲜度 |
| `ai` | AI 识别 | local | logs/ai-cloud.log 最近一次 cloud ok / error 的时间先后 |
| `jwxt` | 教务课表同步 | local | tools/tt.json `meta.fetchedAt` 距今天数 |
| `hwauto` | 作业自动整理 | local | logs/hw-auto.log 或 data/auto-homework.json 新鲜度 |
| `qq_client` | QQ 客户端 | local | QQ.exe 进程存在 |
| `wechat_client` | 微信客户端 | local | Weixin.exe 进程存在 |

状态取值：`ok`（正常）/ `warn`（注意）/ `down`（异常）/ `unknown`（未知）。前端展示文案：正常 / 注意 / 异常 / 离线 / 未知。

## 2. 云端表 `public.service_health`

```sql
CREATE TABLE IF NOT EXISTS public.service_health (
  id          text PRIMARY KEY,
  name        text NOT NULL,
  kind        text NOT NULL DEFAULT 'local',   -- local | cloud | static
  status      text NOT NULL DEFAULT 'unknown', -- ok | warn | down | unknown
  detail      text NOT NULL DEFAULT '',
  meta        jsonb NOT NULL DEFAULT '{}'::jsonb,
  checked_at  bigint NOT NULL,                 -- 采集主机检测时刻（unix ms）
  updated_at  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.service_health ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE ON public.service_health TO anon;

-- 仅管理员可读、可写（RLS 统一校验 token；非管理员 select 返回 []）
DROP POLICY IF EXISTS sh_read   ON public.service_health;
CREATE POLICY sh_read   ON public.service_health FOR SELECT TO anon USING (public.auth_admin());
DROP POLICY IF EXISTS sh_insert ON public.service_health;
CREATE POLICY sh_insert ON public.service_health FOR INSERT TO anon WITH CHECK (public.auth_admin());
DROP POLICY IF EXISTS sh_update ON public.service_health;
CREATE POLICY sh_update ON public.service_health FOR UPDATE TO anon USING (public.auth_admin()) WITH CHECK (public.auth_admin());
```

- REST 路径：`{CB}service_health?select=id,name,kind,status,detail,meta,checked_at&order=id`
  （`CB` 来自 index.html `var CB="..."`；鉴权 `Authorization: Bearer <CBK>`，身份头 `X-Device-Id: <token>`）
- 采集主机写入：同 token 头；逐行 `PATCH service_health?id=eq.<id>`，返回 404/无行时 `POST service_health`（参考 `sync_notices_cloud.py` 的写法）。
- **禁止**把 token / 密钥写进前端、日志、报告。CB/CBK 是设计上公开的 publishable key。

## 3. 采集主机心跳脚本 `C:\briefdesk\scripts\health_beat.py`

- 纯标准库；由 `watchdog.py` 每轮（5 分钟）结束后调用；**任何异常都不得让 watchdog 失败**（try/except 包裹）。
- 读取：
  - `C:\briefdesk\watchdog.state.json`（watchdog 已经算好的服务状态/失败次数）
  - `C:\briefdesk\secrets\class-token.json`（管理员 token，**只读不打印**）
  - index.html 里 `CB` / `CBK`
- 自行检测（不重复做 watchdog 已做且已落 state 的项）：
  - `collector_host`：开机时间（`Win32_OperatingSystem.LastBootUpTime` 或 psutil 不可用则读 `GetTickCount`？用 PowerShell CIM 隐藏执行即可）、运行时长、watchdog 轮次时间、pause 文件
  - `site_static`：GET `https://tool.furina.fun/tt.json`（urllib，8s 超时），延迟 ms
  - `site_tls`：TLS 握手 `tool.furina.fun:443`（默认校验上下文，失败即 down），剩余天数（`ssl.getpeercert()['notAfter']` 需在有验证的 context 下解析：用 `ssl.create_default_context()` + `sock.getpeercert()`，或 `ssl.cert_time_to_seconds`）
  - `cloudbase`：GET `{CB}service_health?select=id&limit=1`（带 token），延迟 ms
  - `qq_client` / `wechat_client`：进程枚举（可复用 PowerShell CIM，`CREATE_NO_WINDOW`）
  - `ai`：解析 `C:\briefdesk\logs\ai-cloud.log` 尾部 50 行，找最后一次 `cloud ok` 与 error 行
  - `jwxt`：读 `...\web\tools\tt.json` 的 `meta.fetchedAt`（ms）
  - `hwauto`：`C:\briefdesk\logs\hw-auto.log` mtime + 尾部最后时间戳
  - `watcher`：`C:\briefdesk\logs\docs-detect.log` mtime（<=300s ok，300–600 warn，>600 或进程缺失 down；进程存在性看 watchdog.state.json）
- 状态阈值：
  - qqflow/weflow：健康 + 账号 ready → ok；健康但账号不 ready → warn；HTTP 不通 → down
  - briefdesk：HTTP 200 → ok；否则 down
  - jwxt：tt.json 年龄 ≤30h ok；30–54h warn；>54h 或文件缺失 down
  - hwauto：日志/数据年龄 ≤3h ok；3–8h warn；>8h down
  - ai：最近一条 error 晚于最近一条 ok → warn，否则 ok（无调用不算异常，detail 写「最近成功 …」）
  - site_tls：剩余 >21 天 ok；8–21 warn；≤7 或握手失败 down
  - cloudbase/site_static：HTTP 成功且 <3000ms ok；成功但慢 → warn；失败 → down
  - collector_host：正常上报 → ok；`C:\briefdesk\watchdog.pause` 存在 → warn（detail「采集已暂停」）
- 每次上报写 13 行（见 §1），`checked_at` 用当前 ms，`detail` 一句话中文（≤60 字），`meta` 放结构化细节（uptime、latency_ms、days_left、last_ok 等）。
- 首次写表：不存在则 POST 整行（不要依赖 upsert 头）。失败只写日志 `C:\briefdesk\logs\health-beat.log`，**不得抛异常**。
- 提供 `--once` 手动入口便于测试；`--dry-run` 只打印将写入的行（**不得打印 token**）。

## 4. watchdog 集成

- `watchdog.py` 主流程末尾调用 `health_beat.publish(round_info)`；`round_info` 至少含 `services` 状态字典、`scanner`、`updated`、本轮耗时。
- `PAUSE` 分支也要上报一次 `collector_host`（status=warn，detail=「采集已暂停」），让面板能区分「暂停」与「离线」。
- 失败绝不影响 watchdog 退出码与日志主流程。
- **不要改动** watchdog 现有守护逻辑（重试/账号自愈/预算）。

## 5. 前端诊断页（`web/tools/index.html`，单文件）

### 5.1 入口与门禁
- `TOOLS` 数组末尾新增：`{k:"diag",n:"诊断",d:"依赖服务运行状态，异常一眼可见",admin:true}`。
- `gotoTab(k)` 的 admin 拦截从「只拦 stats」改为通用：`var t=toolOf(k); if(!t || !toolShown(t)) return;`（保留 stats 行为）。
- 「全部」页沿用现有 `t.admin&&canManage()` 的「管理」角标与筛选逻辑，不得对非管理员出现。
- 非管理员**不得**发起 `service_health` 请求、不得渲染该 section。

### 5.2 数据获取
- 每次打开诊断页、点「刷新」、以及停留时每 60s（`document.hidden` 时暂停）：
  1. `GET {CB}service_health?select=id,name,kind,status,detail,meta,checked_at&order=id`，带 `X-Device-Id: AUTH.token`；计时记录 `cloud_latency_ms`。
  2. 同源 `fetch('tt.json',{cache:'no-store'})`，计时；解析 `meta.fetchedAt`。失败则 `site_static`=down。
  3. 合并规则：
     - `cloudbase` / `site_static` 行以浏览器实时探测为准覆盖（detail 写延迟）。
     - 其余行按云端返回渲染；若 `collector_host.checked_at` 距今 >15 分钟，则所有 `kind=local` 行显示为「离线」灰态，detail 保留原上报内容并在行尾显示「上报于 HH:MM」。
     - 无 `collector_host` 行时同样视为采集主机离线。
  4. 摘要：`全部正常` / `n 项注意` / `n 项异常` / `采集主机离线`（取最严重）。
- 请求失败（网络/HTTP 错误）：诊断页仍要可用 —— 顶部提示「云端连接失败」，`cloudbase` 行异常，其余按最近一次成功结果（内存缓存，仅本次会话）或「未知」展示。**不得** alert/阻塞。
- 无新增外部域名请求；CloudBase + 同源 tt.json 是既有依赖。

### 5.3 界面（遵循 AGENTS §1 设计规范）
- 单文件、原生 JS、无构建链；不新增底部导航。
- 结构：`<section id="s-diag">` + `.card`：
  - 顶部摘要卡：状态圆点 + 概要文案 + 「最后检测 HH:MM:SS」+ 右侧「刷新」按钮（≥40px 可点）。
  - 分组卡片：「站点与云端」（cloudbase/site_static/site_tls）/「信息采集」（qqflow/weflow/watcher/briefdesk/qq_client/wechat_client）/「定时任务」（jwxt/hwauto/ai）/「采集主机」（collector_host）。
  - 每行：状态点 + 名称 + 状态胶囊（正常/注意/异常/离线/未知）+ 一行 detail（省略号截断，title 全文）+ 右侧时间/延迟小字。
  - ≥960px 两列（复用 `.grid2`/媒体查询），手机单列；不横向溢出（360/390/430/1280 实测）。
- 配色用现有变量：正常 `--cy`（#4E9082）、注意 `--warn`（#C79A5A）、异常 `--danger`（#C0605A）、离线/未知 `--ink3`（#8C9A97）。
- 不写解释性段落；状态文案即信息。
- 保留现有 `POS` 刷新恢复逻辑（`tool.admin && !canManage()` 已处理）。

### 5.4 代码位置约束
- 只在 `web/tools/index.html` 内改动：CSS（`<style>` 末尾）、section DOM（`#s-stats` 之后）、JS（`TOOLS`/`gotoTab` 分支 + 新增 `renderDiag()` 模块，放在 `refreshAll()` 之前或附近）。
- 不重排现有结构、不改其他工具、不改导出逻辑、不改版本号 `APP_VER`（仍 2.0.0）。

## 6. 重启韧性（Lead 负责，backend 只做心跳）

- `Class Homework Auto`：补 LogonTrigger（延迟 3 分钟）、StartWhenAvailable=true、电池相关 false。
- `JwxtTimetableSync`：补 LogonTrigger（延迟 2 分钟）。
- `Briefdesk Watchdog`：已具备每 5 分钟 + 登录触发 + StartWhenAvailable，保持。
- 新增计划任务 `Class Tools Clients`：登录时（延迟 90s）无窗口启动 QQ（`C:\Program Files\Tencent\QQNT\QQ.exe`）与 Weixin（`C:\Program Files\Tencent\Weixin\Weixin.exe`，若进程不存在才启动），保证重启后消息源在线；脚本建议 `C:\briefdesk\scripts\ensure_clients.py`（pythonw 运行、CREATE_NO_WINDOW、幂等、绝不弹控制台）。
- 全部任务改动前导出 XML 备份到 `C:\briefdesk\data\_backup_taskxml_20261105\`。

## 7. 验收标准

后端：
1. `tcb db execute -e tool-d4gosudok46e0e081 --sql "select ... from pg_policies where tablename='service_health'"` 三条策略存在。
2. `health_beat.py --once` 后表内 13 行，字段完整，`checked_at` 新鲜；日志无 token。
3. 非管理员 token GET `service_health` 返回 `[]`；匿名（无 token）返回 `[]`；管理员返回 13 行。
4. 杀掉 qqflow-server → 下一次 watchdog 轮次后 `qqflow.status=down`（或先于重启），重启后恢复 `ok`；health-beat.log 无异常导致 watchdog 退出码非 0。
5. watchdog 暂停文件存在时 `collector_host.status=warn`。

前端：
1. 管理员登录后「诊断」出现在「全部」页并有「管理」角标；可打开；显示 13 项 + 摘要 + 刷新按钮。
2. 非管理员（含测试身份）工具栏/全部页均无「诊断」，直接 `gotoTab("diag")` 不生效、不发 service_health 请求。
3. 360/390/430/1280 无横向溢出、0 JS 报错、≥40px 可点；刷新按钮生效；60s 自动刷新（页面隐藏时暂停）。
4. 断网/云端失败时不崩溃，顶部提示 + 行降级。
5. 现有门禁不回退：`sync_check.py` / `perf_check.py` / `v2_ui_check.py` / `v2_admin_check.py` 等既有测试跑通（新增 1 个 admin 工具导致的计数断言若需更新，必须在测试里显式更新并说明）。

## 8. 文件归属（防并发写冲突）

| 路径 | 唯一写者 |
|---|---|
| `C:\briefdesk\scripts\health_beat.py`（新建）、`watchdog.py`、`C:\briefdesk\scripts\sql\service_health.sql`（新建）、`web\deploy\cloudbase\2026-11-05_service_health.sql`（新建） | backend-health |
| `web/tools/index.html` | frontend-health |
| 计划任务 XML / `C:\briefdesk\scripts\ensure_clients.py` / 部署 / 文档 | Lead |
| `web/tools/tests/_health_qa/**`（新建） | qa-health |

任何一方不得改对方文件；发现需要改对方文件 → 报告 Lead 协调。

---

## 9. 2026-11-07 增量 v2：18 行 + 网页暂停语义 + 课表云端化（当前有效）

> 背景：用户即将暂停 furina.fun 全部解析（网页暂停使用）；小程序已发布。本次让课表不再依赖 `tool.furina.fun`，并把诊断扩展到 18 行、支持「网页按备案暂停」状态。
> 契约详表见 `dns_pause_tt_health_spec.md`；本节为 v2 的权威摘要，与 §1-§8 冲突时以本节为准。

### 9.1 行清单（18 行 / 5 组）

| 分组 | 行 id |
|---|---|
| 站点与网页 | `site_static` 站点资源 / `site_tls` 站点证书 / `dns_domain` 域名解析 |
| 云端后台 | `cloudbase` 云端数据库 / `tt_cloud` 课表云端数据 / `cloud_power_sync` 电费云同步 / `cloud_xgj_sync` 学工记云同步 / `cloud_health_probe` 云端巡检 |
| 信息采集 | `qqflow` / `weflow` / `watcher` / `briefdesk` / `qq_client` / `wechat_client` |
| 定时任务 | `jwxt` / `hwauto` / `ai` |
| 采集主机 | `collector_host` |

- `kind`：`cloud`（云端函数写 8 行：cloudbase、site_static、site_tls、dns_domain、tt_cloud、cloud_power_sync、cloud_xgj_sync、cloud_health_probe）/ `static`（site_static、site_tls 前端展示用）/ `local`（本机 watchdog 写 10 行）。
- 本机 `health_beat.collect()` 默认只探测 local 10 行；云端 8 行由云函数 `health_probe` 写，互不覆盖。

### 9.2 新增判定

- `dns_domain`：解析 `tool.furina.fun`。网页暂停（`site_config.web.paused=true`）时：不可解析=ok「已暂停（符合预期）」；仍可解析=warn「仍在解析（请检查暂停操作）」。非暂停：可解析=ok；不可解析=down。
- `tt_cloud`：读 `public.site_assets?id=eq.tt` 的 `meta.fetchedAt` 年龄（≤30h ok / 30–54h warn / >54h down；行缺失 down）。
- `cloud_power_sync`：`public.power` 最新 `updated_at` 年龄（≤2h ok / 2–3h warn / >3h down）。
- `cloud_xgj_sync`：`public.homework` 中 `auto_hw_xgj_en_*` 最新 `ts` 年龄（≤3h ok / 3–5h warn / >5h down；无行 warn）。
- `cloud_health_probe`：云函数每轮写自身心跳行（detail「本轮完成 · N 行 · Xms」）；前端把它当**云端巡检心跳**：缺失或 checked_at >15 分钟 → 其余 `kind=cloud` 行（`cloudbase` 浏览器延迟覆盖行除外）`ok→warn`，detail 追加「· 巡检未更新」。
- 网页暂停：`site_config.web.paused=true` 时 `site_static/site_tls` 不实际探测，直接 status=warn、detail「网页已按备案安排暂停」、meta `{paused:true,note}`；`paused=false` 时恢复原探测。
- 网页端 `site_static` 的浏览器实时探测在云端行 `meta.paused=true` 时**不覆盖**暂停语义；`tt` 数据源：同源 `tt.json` 优先，失败回退 CloudBase `site_assets?id=eq.tt`；小程序 `ttFetch` 反向：CloudBase `site_assets` 优先，失败回退旧 `ttUrl`。

### 9.3 新增表

- `public.site_assets`：`id text pk / body jsonb / meta jsonb / updated_at`；RLS：读 `auth_ok()`（有效班级 token），写 `auth_admin()`。`id='tt'` 为课表快照。
- `public.site_config`：`id text pk / value jsonb / updated_at`；RLS：仅管理员读写。`id='web'` = `{paused:bool,note,paused_at}`；本机 `C:\briefdesk\scripts\web_pause.py --on/--off` 维护。
- 迁移：`web/deploy/cloudbase/2026-11-07_site_assets.sql`。

### 9.4 v2 验收

1. 云端 `service_health` 18 行；5 个新行 detail 合理；`cloud_health_probe` 每 5 分钟更新。
2. `site_assets.tt` body 与本地 `tt.json` 一致，管理员可读 1 行、匿名/普通 token 读 `[]`；小程序/网页诊断均渲染 18 行/5 组。
3. 暂停语义：`web_pause.py --on` → 巡检 → `site_static/site_tls` 注意「已暂停」、`dns_domain` 符合预期；`--off` 后恢复。
4. 云端巡检过期（mock checked_at >15min）→ 云端行「注意 · 巡检未更新」。
5. 课表回退：网页同源 `tt.json` 失败 → CloudBase `site_assets` 成功；小程序单测覆盖 CloudBase 优先 + legacy 回退。
6. 本机 watchdog 仍正常（local 10 行；单轮耗时回落到 ~2s 级），既有门禁（web/mp）不回退。
