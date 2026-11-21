# DNS 暂停前改造规格：课表去域名化 + 诊断条目完善（2026-11-07）

> 背景：用户即将「挑选时间把 furina.fun 的解析**全部暂停**，网页暂时暂停使用」。
> 目标：① 修复小程序课表对 `https://tool.furina.fun/tt.json` 的硬依赖；② 诊断页新增/完善服务条目，并在网页暂停期间正确显示「已暂停」而不是误报异常。
> 本文件是三方（cloud-tt / mp-tt / Lead）**唯一契约**，实现与验收均以此为准。

---

## 0. 关键约束

- **不改手机端/网页的视觉设计**；只做数据源、诊断条目与状态语义。
- **密钥零泄漏**：token/key 只通过现有文件读取，不打印、不写报告/日志、不进对话。
- 网页 `index.html` 由 **Lead** 修改；`mp-class-tools/` 由 **mp-tt** 修改；`C:\briefdesk\scripts\health_beat.py`、`C:\briefdesk\cloudbase\**`、`web\jwxt\**` 由 **cloud-tt** 修改。互不越界。
- 手机端与网页端诊断条目、分组、名称、状态语义必须**完全一致**。
- 每次改完必须跑各自既有测试；不得回退既有功能。

---

## 1. 新表 `public.site_assets`（课表快照内迁）

```sql
create table if not exists public.site_assets (
  id text primary key,
  body jsonb not null,
  meta jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
alter table public.site_assets enable row level security;
grant select, insert, update on public.site_assets to anon;
create policy sa_read   on public.site_assets for select to anon using (public.auth_ok());
create policy sa_insert on public.site_assets for insert to anon with check (public.auth_admin());
create policy sa_update on public.site_assets for update to anon using (public.auth_admin()) with check (public.auth_admin());
```

- `id='tt'` 行：
  - `body` = `tools/tt.json` 的原始 JSON 对象（`{c:[...],t:"...",meta:{...}}`）；
  - `meta` = `{source:"jwxt", fetchedAt:<ms>, count:<n>, termStart:"YYYY-MM-DD", syncedAt:"<ISO>"}`；
  - `updated_at` = 发布时刻（now）。
- 读：`GET {CB}site_assets?id=eq.tt&select=body,meta,updated_at`，头 `Authorization: Bearer <CBK>` + `X-Class-Token`（mp）/`X-Device-Id`（web）。
- 写：管理员 token（jwxt 本地同步脚本用 `C:\briefdesk\secrets\class-token.json`，过期自动 class_verify 刷新）。
- 迁移 SQL 文件：`web/deploy/cloudbase/2026-11-07_site_assets.sql`（幂等，含回滚注释）。

## 2. 新表 `public.site_config`（网页暂停开关）

```sql
create table if not exists public.site_config (
  id text primary key,
  value jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
alter table public.site_config enable row level security;
grant select, insert, update on public.site_config to anon;
create policy sc_read   on public.site_config for select to anon using (public.auth_admin());
create policy sc_insert on public.site_config for insert to anon with check (public.auth_admin());
create policy sc_update on public.site_config for update to anon using (public.auth_admin()) with check (public.auth_admin());
```

- 行 `id='web'`，`value = {"paused": true|false, "note": "备案暂停", "paused_at": <ms>}`。
- 由本机脚本 `C:\briefdesk\scripts\web_pause.py --on/--off/--status` 维护（cloud-tt 新建）。
- 云函数 `health_probe` 读取该行决定 `site_static/site_tls/dns_domain` 状态语义；读不到按 `paused=false`。

## 3. 课表发布链路（cloud-tt）

- 新建 `web/jwxt/tt_cloud.py`：
  - 读取 `web/tools/index.html` 的 `var CB` / `var CBK`；
  - 管理员 token：`C:\briefdesk\secrets\class-token.json`（过期则 `rpc/class_verify` 刷新，姓名用 `sync_power_cloud.py` 的 ADMIN_SID/ADMIN_NAME 同源常量）；
  - `publish(tt_path)`：PATCH `site_assets?id=eq.tt`，404 时 POST；失败抛异常由调用方处理；
  - CLI：`python tt_cloud.py --tt ..\tools\tt.json [--dry-run]`（用于立即回填）；日志不打印 token。
- `web/jwxt/sync.py`：成功写入 `--out` 文件后、`--deploy` 前后**总是尝试**调用 `tt_cloud.publish(out)`；失败只记日志，**不得改变 sync.py 退出码**、不影响 OSS 上传。
- 立即回填一次：用现有 `tools/tt.json` 发布（云端须看到 `site_assets.tt` 行）。

## 4. 健康行（cloud-tt 实现）

原有 13 行保留；`kind` 规则：cloud 行由云函数写，local 行由本机写。**新增 5 行（均 kind=cloud）**，总计 **18 行**：

| id | 名称 | 判定 | 状态/细节 |
|---|---|---|---|
| `dns_domain` | 域名解析 | `socket.getaddrinfo("tool.furina.fun", 443)` | paused=true 且无法解析→ok「已暂停（符合预期）」；paused=true 且解析成功→warn「仍在解析（请检查暂停操作）」；paused=false 且解析成功→ok「解析正常」；paused=false 且失败→down「无法解析」；meta 带 `{host, addrs, paused}` |
| `tt_cloud` | 课表云端数据 | GET `site_assets?id=eq.tt&select=meta,updated_at` | 取 `meta.fetchedAt`（无则 `updated_at`）年龄：≤30h ok / 30–54h warn / >54h down / 行缺失 down「云端未发布课表快照」；detail「云端快照 X 小时前同步」 |
| `cloud_power_sync` | 电费云同步 | GET `power?select=updated_at&order=updated_at.desc&limit=1` | 最新行年龄 ≤2h ok / 2–3h warn / >3h down / 无行 warn「电费无数据」；detail「最近同步 X 分钟/小时前」 |
| `cloud_xgj_sync` | 学工记云同步 | GET `homework?select=ts&id=like.auto_hw_xgj_en_*&order=ts.desc&limit=1` | 最新行年龄 ≤3h ok / 3–5h warn / >5h down / 无行 warn「暂无学工记作业」 |
| `cloud_health_probe` | 云端巡检 | 云函数每轮写自身行 | 每轮 status=ok，detail「本轮完成 · N 行 · Xms」，meta `{rows,patched,posted,ms}`；若该行 checked_at 超过 15 分钟未更新，前端把其它 cloud 行降级「注意 · 巡检未更新」 |

**暂停语义**：`site_config.web.paused=true` 时，`site_static/site_tls` 不再真正探测，直接 status=warn、detail「网页已按备案安排暂停（<note>）」、meta `{paused:true, note}`；`dns_domain` 按上表 paused 规则。paused=false 时 `site_static/site_tls` 行为与现在一致。

**归属常量**：`CLOUD_OWNED_IDS` 更新为
`("cloudbase","site_static","site_tls","dns_domain","tt_cloud","cloud_power_sync","cloud_xgj_sync","cloud_health_probe")`。

**本机脚本**：`health_beat.collect()` 默认只探测/返回 local 10 行（不再探测 cloud 行，避免暂停后每 5 分钟白等 DNS/TLS 超时）；新增 `collect_cloud(base,key,token)` 供云函数使用；`publish(include_cloud=False)` 过滤常量同步更新。

**云函数**：`health_probe/index.py` 改为调用 `hb.collect_cloud(...)` 并写 8 行云端行；部署用 `C:\briefdesk\cloudbase\deploy.py --only health_probe`。

**前端诊断（web + mp 完全一致）**：新增/调整分组与名称：

```
站点与网页：site_static, site_tls, dns_domain
云端后台：  cloudbase, tt_cloud, cloud_power_sync, cloud_xgj_sync, cloud_health_probe
信息采集：  qqflow, weflow, watcher, briefdesk, qq_client, wechat_client
定时任务：  jwxt, hwauto, ai
采集主机：  collector_host
```
NAMES：site_static=站点资源、site_tls=站点证书、dns_domain=域名解析、cloudbase=云端数据库、tt_cloud=课表云端数据、cloud_power_sync=电费云同步、cloud_xgj_sync=学工记云同步、cloud_health_probe=云端巡检；其余沿用。
KINDS：上述 5 个新 id 均 `cloud`。

**cloud 行新鲜度**（web/mp 同一逻辑）：取 `cloud_health_probe` 行 checked_at 作为巡检心跳；缺失或 >15 分钟 → 对所有 `kind==='cloud'` 行（`cloudbase` 的浏览器延迟覆盖除外）在状态为 ok 时改为 `warn`，detail 追加「· 巡检未更新」。`kind==='static'` 的行不参与该降级（它们由暂停语义控制）。

**web 特有**：
- 浏览器实时探测 `cloudbase` 延迟（已有）；浏览器 `site_static`（同源 `tt.json` 探测）在云端行 `meta.paused=true` 时**不覆盖**（保留暂停语义）。否则沿用原逻辑。
- `site_static` 浏览器探测成功=ok、失败=down；但当线上暂停、网页本来也打不开，这段主要供恢复后使用。
- `tt` 数据：`ttSyncPull` 先同源 `tt.json`；失败时回退 CloudBase `site_assets?id=eq.tt`（带 `cbH(false)` token，`cache:no-store`），成功则按 tt.json 同构处理；两者都失败才提示失败。不得影响既有 `#tt=` 发布链接/本机缓存优先级。

**mp 特有**：
- `utils/cloud-config.js`：新增 `tables.siteAssets: 'site_assets'`；`ttUrl` 保留（legacy 兜底）。
- `utils/cloud.js → ttFetch(force)`：统一改为 **CloudBase `site_assets` 优先**（`GET ...?select=body,meta&id=eq.tt`，走统一 `request` 通道，带 publishableKey + X-Class-Token），body 可字符串/对象；成功 `touchSync('tt')` 并返回 body；失败再回退旧 `ttUrl`（无身份头）；TTL/缓存语义不变（命中 TTL 直接返回缓存，不发请求）。
- `utils/diag.js`：按上述分组/名称/kind/cloud 新鲜度/站点暂停语义更新，保持纯函数与现有调用接口 `build(ctx)` 不变（web 与 mp 诊断口径一致）。
- 诊断页（`pages/diag`）通常无需改结构；若有固定行数断言需同步测试。
- 更新 mp README / CHANGELOG；版本号仍 2.0.0（用户要求直到成功上传发布不改）。

## 5. 网页暂停操作脚本（cloud-tt）

`C:\briefdesk\scripts\web_pause.py`：
- `--on`：PATCH/POST `site_config` 行 id='web' → `{paused:true, note:"备案暂停", paused_at:Date.now()}`；打印状态不含 token；
- `--off`：`paused:false`；`--status`：打印当前值；
- 读 token 与 CB/CBK 方式同 `health_beat.py`（secrets/class-token.json；过期自动刷新）；失败 exit 1。
- 用户暂停 DNS 前运行 `--on`，备案通过恢复后运行 `--off`。

## 6. 测试与验收

cloud-tt：
1. 应用 DDL；两表 RLS/策略存在。
2. `tt_cloud.py --tt ..\tools\tt.json` 回填成功，`site_assets.tt` body 与本地 tt.json 一致；**匿名/无效 token 读 → `[]`；有效班级 token（含普通学生）可读 1 行**（RLS `auth_ok()`，网页/小程序课表回退依赖此点）；管理员可写。
3. 跑一次 `sync.py` 流程不登录的方式验证：`Python -c import sync?` 至少验证 `tt_cloud` 模块可独立运行；不得实际触发教务登录（计划任务 07:00 已跑过）。
4. 部署 `health_probe` 后手动触发一次（`tcb fn invoke health_probe -e ...` 或控制台/命令行），云端 `service_health` 共 **18 行**，新 5 行存在且合理；`cloud_health_probe` 有本轮 detail。
5. 暂停模拟：`web_pause.py --on` → 再触发 health_probe → `site_static/site_tls`=warn「网页已按备案安排暂停」、`dns_domain` 由实际 DNS 决定；恢复 `--off` → 再触发 → site 行回到真实探测。**测试后必须恢复 paused=false**（用户尚未暂停）。
6. 本机 `health_beat --once` 仍只写 local 10 行，watchdog 轮次耗时回到正常（~2s 级，不再等 DNS/TLS）。

mp-tt：
1. `node unit.js`、`node v3_power_diag_tests.js`、`node cache_unit_tests.js`、`node sync_contract_test.js`、`python staticcheck.py` 全绿；更新其中因 13→18 行/分组变化、ttFetch 请求目标变化而失效的断言（不得削弱其它断言）。
2. 新增测试：ttFetch 优先 CloudBase（`site_assets` 请求带 X-Class-Token；返回 body 解析）＋ CloudBase 失败回退旧 ttUrl；diag 新分组/新名称/cloud 巡检过期降级/站点暂停语义。

Lead（web）：
1. `index.html` DIAG 分组/名称/kind/暂停+cloud 新鲜度逻辑；`ttSyncPull` 回退 CloudBase。
2. 跑既有门禁（sync 124、v2_ui、v2_admin、v2_sync、v2_scroll、x5、overflow 430/390、export、power、committee、notice_live、roster、pos_restore、notice_data、stats、swipe_perf）；新增：本地静态页 + mock `service_health` 18 行（含 paused 行/cloud_health_probe）时诊断渲染 18 行、分组 5 组、暂停行显示「注意」不误报异常、cloud 巡检过期降级；tt 同源失败时回退 CloudBase 成功。
3. 部署前备份线上 index.html；部署后线上字节核对。

QA（独立）：抽查云端表/RLS/18 行、mp 单测、web 诊断渲染与回退、暂停语义、既有门禁不回退。

## 7. 文件归属（防并发写冲突）

| 路径 | 唯一写者 |
|---|---|
| `C:\briefdesk\scripts\health_beat.py`、`C:\briefdesk\cloudbase\**`、`%USERPROFILE%\.openclaw\workspace\web\jwxt\**`、`C:\briefdesk\scripts\web_pause.py`、`web\deploy\cloudbase\2026-11-07_*.sql` | cloud-tt |
| `%USERPROFILE%\.openclaw\workspace\mp-class-tools\**`、`mp-class-tools-tests/**` | mp-tt |
| `%USERPROFILE%\.openclaw\workspace\web\tools\index.html`、`web\tools\tests\health_monitor_spec.md`、文档/部署/交付 | Lead |

## 8. 用户侧后续动作（不在本次自动化范围）

1. 在微信开发者工具**上传并发布**新版小程序（含 tt 云端读取），等待审核通过。
2. 挑时间运行 `web_pause.py --on`，再暂停 furina.fun 全部解析。
3. 备案通过后恢复解析 → `web_pause.py --off` → 检查诊断 18 行。
4. **2026-12-10 前续费 CloudBase**（否则小程序与云端全停）。
