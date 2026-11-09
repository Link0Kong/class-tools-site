# 腾讯云 CloudBase 后端服务现状盘点（task-2）

- **审计时间**：2026-11-09 22:08–22:14（Asia/Shanghai）
- **审计员**：cloudbase-auditor（Team 子任务 task-2）
- **方法**：本地只读文件/文档/SQL 阅读；`tcb` CLI 只读尝试（未登录即停）；CloudBase 网关 **只读 GET** 探测（公开 publishable key，见 §3）；DNS/TLS 只读探测；`cloudbaserc.json`/部署记录交叉核对。
- **红线遵守**：未 deploy / 未 invoke 云函数 / 未增删触发器 / 未写 DB / 未调用任何 RPC（含只读 RPC，因为 RPC 一律 POST）/ 未 `tcb login` / **未记录或打印任何 token、密钥值**（publishable key 仅记录长度与 JWT 元数据）。
- **来源标注**：每条结论标 `[实测]`（本轮命令+时间戳）、`[文档]`（文件:行号记载）、`[未验证]`（拿不到，已注明原因）。
- **配套**：阿里云侧见 task-1 `_audit/aliyun.md`；本机侧见 task-3 `_audit/local.md`；本文件只覆盖腾讯云 CloudBase 后端。

---

## 0. 结论速览（最关键 5 条）

1. **环境仍存活、网关与 PG REST 正常** `[实测 22:10:00]`：`GET /v1/rdb/rest/` 返回 200（OpenAPI，79,759 字符），18 张 `public` 表对匿名 key 全部 200 + `[]`（RLS 过滤），TLS 1.3 证书有效至 2027-05-02。
2. **后端形态 = PostgreSQL + PostgREST 网关，无业务 HTTP API**：前端只 `fetch` 一个基址 `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/`；云函数只做定时同步/巡检，不承担业务读写 `[文档] CLOUDBASE.md:98-120、BACKEND_CONTRACT.md:20`。
3. **云函数 4 个（power_sync / xgj_sync / health_probe / hello）+ 3 个定时触发器**，本地代码与 2026-11-06/07 部署记录齐全；**但本轮无法实测当前部署态**（`tcb` 未登录，`tcb env list` 22:09:59 报 `No valid identity found`）。间接证据：2026-11-08 17:37–18:0x 只读诊断记录「18/18 健康行 106s 内上报」`[文档] memory/2026-11-08.md:51`。
4. **数据库：18 张 anon 可见表（实测 OpenAPI 清单）+ 4 张 private schema 表**（`class_ids` / `class_sessions` / `class_league` / `class_audience`，无 API 暴露）；`public.users`、`public.identity_verify` 已删除（匿名 GET 404，实测 22:12:25）。
5. **⛔ 最紧急运营风险：环境 2026-12-10 23:59:59 到期**（距今 **约 31 天**），到期后 DB/网关/云函数/定时器/存储一并失效 → 网页、小程序、安卓三端全部不可用。**续费状态：`IsAutoRenew=true` 已开启（2026-11-08 记录），但“支付方式待确认”，无续费完成证据、无迁移/备份计划** `[文档] 云端服务迁移_20261106.md:3-8、memory/2026-11-08.md:54,57,92`。

---

## 1. 环境信息

| 项 | 值 | 来源/状态 |
|---|---|---|
| 云厂商/产品 | 腾讯云 CloudBase（云开发）· **个人版** | `[文档]` CLOUDBASE.md:111、README.md:22；`[文档]` 迁移文档:8 |
| envId | `tool-d4gosudok46e0e081` | `[文档]` web/deploy/cloudbase/cloudbaserc.json:3；`[文档]` briefdesk/cloudbase/cloudbaserc.json:3 |
| 地域 | `ap-shanghai`（上海） | `[文档]` 同上 cloudbaserc.json:4；实测网关 DNS 解析到腾讯云上海可用区 |
| 数据库 | **PostgreSQL（PostgREST），无文档型数据库** | `[文档]` CLOUDBASE.md:114、README.md:75-77；`[实测]` OpenAPI 根路径存在 |
| 创建时间 | 2026-10-10 | `[文档]` 迁移文档:35（`tcb env list` 输出摘录）；`[文档]` publishable key `iat=2026-10-10 08:54:40`（本轮解码元数据，不抄值） |
| **到期时间** | **2026-12-10 23:59:59** | `[文档]` 迁移文档:3-8、35；CLOUDBASE.md:690；web/AGENTS.md:101；HANDOFF.md:2073；memory/2026-11-08.md:54 |
| 当前资源状态 | 存活：网关 200、PG REST 正常、TLS 有效 | `[实测]` §3（22:10:00–22:12:25） |
| 静态托管 | 默认域名可达但根路径 **404**（`tool-d4gosudok46e0e081-1419350518.tcloudbaseapp.com`→404；`tool-d4gosudok46e0e081.tcloudbaseapp.com`→`INVALID_HOST`），当前**不是**站点入口 | `[实测 22:12:4x]` |
| 旧环境 | `class-tools-d9gewpget3f15db3f`（个人版）**Unavailable（到期未续）** | `[文档]` 迁移文档:36 — 到期不续的直接先例 |
| 交付渠道 | 无自定义域名绑定到网关（网关即 `*.tcloudbasegateway.com` 腾讯域名）；CORS 白名单放通 `tool.furina.fun` | `[文档]` CLOUDBASE.md:116-119；`[实测]` CORS 探测 §3.6 |

---

## 2. 云函数 + 定时触发器

> **重要边界**：`tcb` CLI 3.8.7 已装但**未登录**（`tcb env list` 22:09:59 → `× No valid identity found, please log in with tcb login`，exit 2），`%USERPROFILE%\.config\cloudbase` 不存在、各项目 `.cloudbase/` 目录不存在。因此 **`fn list / fn detail / trigger list` 均无法实测**；`tcb fn invoke` 会写库，按红线**禁止调用**。以下「部署验证」列均为历史证据/间接证据，已明确标注。

### 2.1 函数清单

| 函数 | 用途 | 运行时/入口 | timeout / 内存 | 触发 cron（7 段：秒 分 时 日 月 周 年） | 部署与验证证据 |
|---|---|---|---|---|---|
| `power_sync` | 完美校园电费网关 → `public.power`（17 行）+ `power_history` 增量 + 30 天清理 | `Python3.9` / `index.main_handler` | 120s / 256MB | `0 1 * * * * *`（每小时 :01） | `[文档]` 迁移文档:99,257；本地代码 `functions/power_sync/index.py`（2026-11-06 21:58）；`[文档]` 手动验证 ok 8.0–8.4s、定时器 22:01 Invocation=1（迁移文档:115-141） |
| `xgj_sync` | 班级小管家英语作业 → `public.homework` 仅 `auto_hw_xgj_en_*` 行（幂等） | `Python3.9` / `index.main_handler` | 180s / 256MB | `0 20 */2 * * * *`（偶数小时 :20） | `[文档]` 迁移文档:100,258；代码 2026-11-06 21:58；`[文档]` 连续两次调用幂等（迁移文档:143-155） |
| `health_probe` | 云端探测 8 行 → `public.service_health`（cloudbase/site_static/site_tls/dns_domain/tt_cloud/cloud_power_sync/cloud_xgj_sync/cloud_health_probe） | `Python3.9` / `index.main_handler` | 60s / 256MB | `0 */5 * * * * *`（每 5 分钟） | `[文档]` 迁移文档:101,259；代码 `functions/health_probe/index.py` 2026-11-07 07:37（18 行版）；`[文档]` 11-06 22:15 首触发、22:14/22:19 Invocation=1,1,1（`C:\briefdesk\data\_monitor_health_probe2.json`） |
| `hello` | 冒烟：部署/环境变量/公网出口自检 | `Python3.9` / `index.main_handler` | 10s / 256MB | **无触发器**（冒烟后已删） | `[文档]` 迁移文档:102,178-182；代码 2026-11-06 21:54 |

- 函数定义（不含密钥）：`[文档]` `C:\briefdesk\cloudbase\cloudbaserc.json:5-10`；部署脚本：`[文档]` `C:\briefdesk\cloudbase\deploy.py:36-46,64-99`（从 `scripts/` 复制同源代码 → `functions/`，只生成含密钥的 `secrets/cloudbaserc.local.json`，不打印值）。
- **仓库里只有函数定义，没有触发器声明**（`cloudbaserc.json` 无 triggers 段）→ cron 只存在于文档与 CLI 操作记录中，重建环境需手工重建触发器。
- 云函数环境变量（**只列名称**，值不读不抄）：`CB_BASE`、`CB_KEY`、`CLASS_ADMIN_SID`、`CLASS_ADMIN_NAME`、`CLASS_TOKEN`（可选）、`XGJ_TOKEN`/`XGJ_MEMBER_ID`/`XGJ_EXP`/`XGJ_EXP_TEXT`/`XGJ_CID` `[文档]` deploy.py:76-91、迁移文档:226-237；本机含密钥文件 `C:\briefdesk\secrets\cloudbaserc.local.json`（存在，1,753 B，mtime 2026-11-07 07:37，**内容未读**）。
- **当前部署态**：`[未验证]`（tcb 未登录）。可核验的间接证据：2026-11-08 17:37–18:0x 只读诊断「18/18 健康行 106s 内上报、网关 REST 108–172ms、class_verify 90–123ms」`[文档] memory/2026-11-08.md:50-51`；文档记载 `cloud_xgj_sync` warn=「暂无学工记作业」属预期空态（同文件:54）。
- 已知待修（文档记载，2026-11-08 提出，未见后续修复记录）：`cloud_power_sync` 年龄解析在 Python3.9 下间歇假新鲜 `[文档] memory/2026-11-08.md:54,57③`；`site_assets.tt` 课表快照因教务登录链故障停在 2026-11-07 07:00 `[文档] memory/2026-11-08.md:53`。

---

## 3. HTTP 网关（PostgREST）实测

基址：`https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/`（网页 `var CB` 同值，实测字符串相等）。
凭据：`web/deploy/cloudbase/publish_key.txt` 的 **publishable key**（本文件未抄值；长度 1150 字符；JWT 元数据：`role=anon`、`is_anonymous=true`、`aud=envId`、`iat=2026-10-10 08:54:40`、`exp=2099-10-10 08:54:40`、`platform=PublishableKey`——由本轮本地解码得出）。

### 3.1 根路径 / OpenAPI（22:10:12、22:10:27）

| 请求 | 结果 |
|---|---|
| `GET /v1/rdb/rest/` + `Accept: application/openapi+json` | **200**，`Content-Type: application/openapi+json`，79,759 字符；`swagger` 2.0 风格，`info.title="standard public schema"`、`version="15 (pre-release)"` |
| OpenAPI `definitions` | **18 张表**：`agent_keys, client_diag, diag_analysis, feedback, fitrecs, homework, login_jobs, marks, notices, power, power_history, repair_tasks, roster, service_health, site_assets, site_config, userdata, visits` |
| OpenAPI `paths` | 42 条 = 18 表 + **23 个 `/rpc/*`** + `/`：`armor, auth_acc, auth_admin, auth_hash, auth_hdr, auth_in_audience, auth_is_admin, auth_is_committee, auth_is_league, auth_ok, auth_sid, class_members, class_set_role, class_verify, dearmor, debug_headers, diag_agent_info, gen_random_uuid, gen_salt, pgp_armor_headers, pgp_key_id, tt_login_enqueue, tt_login_status` |

> 说明：PostgREST 只把 **anon 角色有权限**的表/函数列进 OpenAPI；因此这 18 表 = 对匿名 key 存在表级授权的表（行级仍被 RLS 过滤）。

### 3.2 匿名只读探测（22:10:00–22:10:03，带 publishable key）

| 表 | HTTP | body |
|---|---|---|
| `service_health`、`site_assets`、`site_config`、`power`、`power_history`、`homework`、`notices`、`marks`、`fitrecs`、`userdata`、`visits`、`feedback`、`client_diag`、`diag_analysis`、`repair_tasks`、`agent_keys`（均带 `select=...&limit=...`） | 全部 **200** | 全部 **`[]`**（0 行，RLS 生效） |
| `power?select=count`（22:12:25） | 200 | `[{"count":0}]` → 匿名聚合也被 RLS 过滤，**不能当行数探针** |
| `class_ids` / `private.class_ids` / `no_such_table` | **404** `DATABASE_PGRST205`（Could not find the table ... in the schema cache） | private schema 不暴露、public 无该表 |
| `users` / `identity_verify`（22:12:25） | **404** 同上 | **旧账号表/旧认证表已删除**（与 CLOUDBASE.md:76 一致） |
| `class_sessions` / `class_league` / `class_audience`（22:12:25） | **404** | 属 `private` schema，无 API |

### 3.3 鉴权边界

| 请求 | 结果（时间） |
|---|---|
| 无 `Authorization` 头 `GET service_health?select=id` | **401** `MISSING_CREDENTIALS`（22:10:03） |
| publishable key + `X-Device-Id: bogus-test-token` | **200 `[]`**（22:11:09）→ 无效 token 不报错，仅 RLS 过滤 |
| publishable key + `X-Class-Token: bogus-test-token` | **200 `[]`**（22:11:10）→ 两套头都被 `auth_hdr()` 读取（见 §5） |

### 3.4 CORS（22:10:03）

| `Origin` | 结果 |
|---|---|
| `https://tool.furina.fun` | **200**，`Access-Control-Allow-Origin: https://tool.furina.fun` |
| `https://example.com` | **403**（空 ACAO）→ 网关按白名单拒绝 |

> 文档记载白名单另含 CloudBase 静态托管默认域名（memory/2026-11-06.md:146）；本轮只抽样 2 个 origin，**完整白名单 `[未验证]`**（需控制台/`tcb cors list`）。网页依赖的自定义头 `X-Device-Id` 是否在预检白名单内 **未实测**（本轮禁止非 GET 请求），`[文档]` CLOUDBASE.md:19-21、README.md:86 记载已放通。

### 3.5 DNS / TLS（22:11:10 左右）

- DNS：`tool-d4gosudok46e0e081.api.tcloudbasegateway.com` → CNAME `prod.paasgw.tencentcloudbase.com` → A `81.69.138.235` / `81.69.216.233`（腾讯云）。
- TLS：TCP 443 通，`Tls13`；证书 `CN=*.tcloudbasegateway.com, O=Tencent Technology (Shenzhen) Company Limited`；签发 `DigiCert Secure Site OV G2 TLS CN RSA4096 SHA256 2022 CA1`；**notAfter 2027-05-02 07:59:59（剩余 173.4 天）**——与 CloudBase 环境到期（2026-12-10）无关，证书由腾讯维护。

### 3.6 网关域名与备案

- 网关使用腾讯云自有的 `*.tcloudbasegateway.com` 域名（本轮 DNS/TLS 实测 + `[文档]` mp-class-tools/README.md:503 作为小程序 request 合法域名），**域名备案主体是腾讯云，不是本项目域名**；本项目未把自定义域名绑定到该网关（无任何文档/实测证据），故「网关本身是否需要用户备案」= 不需要；真正受限的是**小程序后台 request 合法域名配置**（文档记载已配该网关；后端配置无法从本机只读核实）。
- 项目自有域名 `tool.furina.fun` 在本后端里只作为 **CORS origin**（实测放通），当前 DNS 已暂停解析，不影响网关可用性 `[文档]` HANDOFF.md:2067-2074、memory/2026-11-06.md:147。
- 小程序已发布并有备案号 `闽ICP备2026042939号` `[文档]` memory/2026-11-06.md:135,139,147、HANDOFF.md:2029（本任务不做备案核查，仅记录）。

---

## 4. 数据库表清单 + RLS 要点

> 表名/列名以下均为 **2026-11-09 22:10 OpenAPI 实测**；RLS 细节来自 `web/deploy/cloudbase/*.sql` 与 CLOUDBASE.md（其中**现行线上策略有一部分不在仓库内**，见 §4.4 漂移警告）。行数为 `[文档]` 记载、**本轮未实测**（匿名被 RLS 挡住，且本轮禁止使用管理员 token / 写接口）。

### 4.1 `public` schema（18 张，实测 OpenAPI）

| 表 | 用途 | 关键列（实测） | 读权限（RLS 口径） | 写/删（RLS 口径） | 行数（文档记载） |
|---|---|---|---|---|---|
| `homework` | 作业（含自动/手动） | id, subject, content, due, date, author, done, ts, archived, owner, attachments, time | 有效班级 token（匿名 `[]`）`[文档]` CLOUDBASE.md:68,329-336；早期 `using(true)` 已被身份系统收紧 | 写：登录用户；删：无 DELETE 策略（软删 archived）`[文档]` schema.sql:39-42 | 14 行（2026-11-06 `[文档]` 迁移文档:153） |
| `notices` | 通知（自动通知板 + 人工通知） | id, title, body, pin, imp, author, archived, ts, owner, attachments, **audience, override_json, hidden, edited_at, edited_by** | `auth_ok()` + audience 过滤（all/committee/league/set:*/admin/sid:）`[文档]` CLOUDBASE.md:367-410、2026-11-05_notice_admin_override.sql | 写：仅管理员（nt_insert/nt_update 收紧）；无 DELETE（archived/hidden 软删） | 69 行（2026-11-09 `[文档]` memory/2026-11-09.md:通知优化结果「云端 notices 69/69」） |
| `marks` | 作业完成 / 通知置顶 / 通知已处理 | id, seat, kind, ref, val, ts | 本人（`seat=auth_acc()`）`[文档]` security_hardening.sql:60-69 | 本人 upsert；**无 DELETE**（置 false） | 未统计 |
| `userdata` | 用户数据 blob v6（跨端同步） | id(=sid), blob, ts | 本人（`id=auth_acc()`）`[文档]` security_hardening.sql:84-93 | 本人 upsert；无 DELETE（覆盖） | 每用户 1 行，未统计 |
| `fitrecs` | 体测记录 | id, acc, data, arch, ts | 本人 `[文档]` security_hardening.sql:72-81 | 本人；无 DELETE（arch 软删） | 未统计 |
| `visits` | 访问统计 | id, slot, did, ts, **sid, name** | 管理员 OR 本人行 `[文档]` 2026-11-04_visits_feedback_own_read.sql:19-21 | insert=`auth_ok()`+本人；无 update/delete | 未统计 |
| `feedback` | 反馈 | id, content, contact, acc, done, ts | 管理员 OR 本人行 `[文档]` 同上:23-25 | insert=`auth_ok()`（遗留宽松，见 §4.4）；update 管理员 | 未统计 |
| `roster` | 旧名单单行（前端已改用 `class_members` RPC） | id, data, ts | 登录可读 `[文档]` security_hardening.sql:51-52 | 写仅管理员；无 DELETE | 单行 `id='main'` |
| `service_health` | 依赖服务健康心跳（18 行 / 5 组） | id, name, kind, status, detail, meta, checked_at, updated_at | **2026-11-08 起放宽为 `auth_ok()`**（原 `auth_admin()`）`[文档]` 2026-11-08_diag_login.sql:159-161 | 写仅管理员；无 DELETE | 18 行（2026-11-07 `[文档]` HANDOFF.md:2058-2060；11-08 诊断 18/18 行 106s 内上报 memory/2026-11-08.md:51） |
| `power` | 宿舍电费当前值（17 间） | id(=roomverify), label, building, room, roomverify, quantity, unit, low, updated_at | `auth_ok()` `[文档]` 2026-11-05_power.sql:60 | 写/删仅管理员 `[文档]` 同上:62-72 | **17 行** `[文档]` 迁移文档:99,135 |
| `power_history` | 电费历史采样（趋势数据源） | id(bigserial), roomverify, quantity, unit, ts | `auth_ok()` `[文档]` 2026-11-06_power_history.sql:47 | insert/delete 仅管理员 `[文档]` 同上:49-55；30 天清理 | 458→492 行（2026-11-06 `[文档]` 迁移文档:131-133） |
| `site_assets` | 课表快照（`id='tt'`） | id, body(jsonb), meta(jsonb), updated_at | `auth_ok()` `[文档]` 2026-11-07_site_assets.sql:48 | 写仅管理员 `[文档]` 同上:50-56；无 DELETE | 1 行（body/meta 与本地 tt.json 深度相等，2026-11-07 `[文档]` HANDOFF.md:2058） |
| `site_config` | 网页暂停开关（`id='web'`） | id, value, updated_at | 仅管理员 `[文档]` 2026-11-07_site_assets.sql:71-73 | 仅管理员 | 1 行（2026-11-08 读得 `paused=false` `[文档]` memory/2026-11-08.md:52） |
| `client_diag` | 设备诊断上报 | id, sid, platform, app_ver, kind, level, message, detail, device, fingerprint, ts, status, analysis_id, created_at | `auth_ok()` `[文档]` 2026-11-08_diag_login.sql:47 | insert：`auth_ok() AND sid=auth_sid()`（sid 默认 `auth_sid()`）；update 仅管理员；无 DELETE | 未统计 |
| `diag_analysis` | AI 诊断分析/修复流程 | id, ts, platform, scope, severity, title, cause, suggestion, fixable, action, status, confidence, flow, related, updated_at | `auth_ok()` `[文档]` 2026-11-08_diag_login.sql:82 | 仅管理员（ALL 策略）`[文档]` 同上:84-86 | 未统计 |
| `repair_tasks` | 本机自动修复任务 | id, created_at, action, params, reason, status, claimed_at, finished_at, result, analysis_id, node, updated_at | `auth_ok()` `[文档]` 同上:110 | 仅管理员 `[文档]` 同上:112-114 | 未统计 |
| `agent_keys` | 本机 agent PGP 公钥 + 心跳 | id, pubkey, host, seen_at, version, created_at | **仅管理员** `[文档]` 同上:129-131 | 仅管理员 | 单行 `id='tt_login'` |
| `login_jobs` | 课表登录任务（密码仅 PGP 密文） | id, sid, platform, pwd_pgp, created_at, expires_at, status, claimed_at, finished_at, result, error, node | **仅管理员**（客户端只能经 `tt_login_enqueue/status` RPC）`[文档]` 同上:152-157 | 仅管理员；RPC 内 15 分钟过期、每小时限 3 次 | 未统计 |

### 4.2 `private` schema（4 张，无 API，实测 public 路径 404）

| 表 | 用途 | 关键列 | 权限 | 来源 |
|---|---|---|---|---|
| `private.class_ids` | 班级官方名单（70 人 + 1 测试身份；`is_admin`/`is_test`/`role`/`badge`） | seat, name, sid, role, badge, is_admin, is_test | `revoke all ... from anon/authenticated`；仅 security definer 函数使用 | `[文档]` CLOUDBASE.md:66,322-324；identity_schema.sql:6-14；2026-11-05_test_account.sql:13,41-46 |
| `private.class_sessions` | 班级 token 会话（30 天） | token, sid, name, expires_at | 不对外暴露，仅 auth 函数 | `[文档]` CLOUDBASE.md:67；**DDL 不在仓库** |
| `private.class_league` | 团员名单（50 人，audience='league' 用） | sid, seat, updated_at | security definer（`auth_is_league()`） | `[文档]` league_audience.sql:16-20；CLOUDBASE.md:432-453 |
| `private.class_audience` | 自定义人群名单（audience='set:xxx' 用） | audience, sid, seat, name, updated_at | security definer（`auth_in_audience()`） | `[文档]` audience_sets.sql:10-17；memory/2026-11-06.md:53 |

### 4.3 已删除/遗留表（实测 404）

- `public.users`（旧账号密码表）、`public.identity_verify`（旧姓名学号认证表）→ 匿名 GET **404**（22:12:25），与文档「已删除」一致 `[文档]` CLOUDBASE.md:76。
- 但仓库 `schema.sql:176-199`、`mp-class-tools-tests/identity_schema.sql:16-25` 仍保留旧 DDL → **若按旧文件重建环境会把已删表建回来**（风险见 §4.4）。

### 4.4 RLS 机制小结与漂移警告

- 三层身份：**匿名（无效/无 token）→ 行全部过滤（200 + `[]`，实测）**；**班级 token（网页 `X-Device-Id` / 小程序·安卓 `X-Class-Token`）→ `auth_ok()`**；**管理员 token → `auth_admin()`**（=`auth_ok()` + `private.class_ids.is_admin`）。
- `auth_hdr()` = `request.headers->>'x-device-id'`（`[文档]` security_hardening.sql:7-10；`league_audience.sql:34` 显示 `private.class_sessions.token` 与该头直接比对，即**头值就是 token 本身**）。
- 多数表**无 DELETE 策略**（homework/notices/marks/fitrecs/userdata/roster/visits/feedback/service_health/site_assets/site_config/client_diag）→ 匿名/班级 token 删除必 401，删除靠软删或管理员；`power/power_history/diag_analysis/repair_tasks/login_jobs/agent_keys` 有管理员 DELETE/ALL 策略（`[文档]` 对应迁移文件）。
- ⚠️ **仓库内 DDL 与线上现行策略存在漂移（2026-11-05 隐私审计已记录）**：`class_verify`、`private.class_sessions`、`auth_sid/auth_is_admin/auth_is_committee/auth_is_league/auth_in_audience`、`homework/notices` 现行 RLS **均不在仓库**；`schema.sql` 的老 `using(true)` 策略与 `security_hardening.sql` 的 `auth_ok()`（仍查已删除的 `public.users`）**均已过时，不能当现行定义/不能重跑** `[文档]` web/_compliance/audit_current_state.md:327-332、android-class-tools/docs/BACKEND_CONTRACT.md:27,484。
- 本轮**未实测任何写策略**（红线：禁止写/RPC），§9 给出只读核查方法（需 tcb 登录后查 `pg_policies`/`pg_get_functiondef`）。

---

## 5. 身份 / 密钥体系（只写机制，不抄任何值）

| 组件 | 机制 | 来源 |
|---|---|---|
| **Publishable key** | JWT，`role=anon`、`platform=PublishableKey`，设计上就是给前端公开的凭据；能做什么完全由 RLS 决定。值出现在 `web/tools/index.html:2044`（`var CBK`）与 `deploy/cloudbase/publish_key.txt`，**实测两者完全一致**（本轮程序化字符串相等比较 True，未打印值）。有效期至 2099-10-10（解码元数据）。 | `[文档]` CLOUDBASE.md:122-131、README.md:88-89；`[实测]` 22:13 比较 |
| **班级 token** | 身份页「学号 + 姓名」→ `POST rpc/class_verify` → 云端签发 **30 天** token；会话存 `private.class_sessions(sid,name,expires_at)`；网页存 `localStorage.zq_class_identity` 并每次请求带 `X-Device-Id`；小程序/安卓带 `X-Class-Token`；服务端 `auth_hdr()` 两者均读（实际读 `x-device-id`，`X-Class-Token` 亦被接受——本轮无效值实测 200 `[]`，说明头被识别并进入 RLS 过滤）。 | `[文档]` CLOUDBASE.md:16-22,81-89,563-566；`[实测]` 3.3 |
| **管理员** | `private.class_ids.is_admin=true` 的账号即管理员；文档记载唯一管理员为**陈子麒 / 3260707024**；`auth_admin()` 依据 `class_ids.is_admin`（DDL 不在仓库）。 | `[文档]` CLOUDBASE.md:74,504；audit_current_state.md:78 |
| **云函数用的管理员 token** | 不在代码里硬编码：函数冷启动/调用时用环境变量 `CLASS_ADMIN_SID/NAME` 调 `rpc/class_verify` **动态换 token**（可选 `CLASS_TOKEN` 应急）；本机采集脚本用 `C:\briefdesk\secrets\class-token.json` 缓存（存在性/用法见文档，**本轮未读取**）。 | `[文档]` deploy.py:112、power_sync/index.py:9-14,33-43、xgj_sync/index.py:13-17、health_probe/index.py:14-17；CLOUDBASE.md:605-607 |
| **RPC 写入口** | 客户端唯一可写的 RPC：`tt_login_enqueue`（只写自己、密码仅 `pgp_pub_encrypt` 密文）、`tt_login_status`（只读自己）；其余数据走表 RLS。`class_verify/class_members/class_set_role/diag_agent_info` 为身份/诊断 RPC。 | `[文档]` 2026-11-08_diag_login.sql:164-269；`[实测]` OpenAPI rpc 清单 |
| **服务端实现缺口** | `class_verify`、`class_sessions` DDL、`auth_sid/auth_is_admin/auth_is_committee` 的 SQL **不在仓库**（无法核实 token 生成算法/TTL 常量/限流/清理/吊销）；TTL「30 天」仅为文档口径。 | `[文档]` audit_current_state.md:329,422(Q-2)；BACKEND_CONTRACT.md:27,484 |
| **机密边界** | 真正的服务端密钥（`--type api_key`）本项目**未创建**；`deploy/creds.env`、证书私钥等与本后端无关且禁止读取/外传。 | `[文档]` CLOUDBASE.md:130、README.md:88-89、web/AGENTS.md:6 |

### 5.1 安全观察（只读证据，非写测试）

- **匿名可执行的 RPC 面**（OpenAPI 实测列出 23 个 `/rpc/*`，含 `debug_headers` 与 pgcrypto 系列 `armor/dearmor/pgp_armor_headers/pgp_key_id/gen_salt/gen_random_uuid`）——这些函数对 anon 有 EXECUTE 权限；是否可被滥用（信息泄露/CPU）**未实测**（RPC 禁止调用），建议后续在控制台收紧 `grant execute`。
- 无效 token 不返回 401 而是 `200 []`：客户端无法区分「token 失效」与「无数据」，需靠业务层判定（文档已说明 token 失效回身份页）`[文档]` CLOUDBASE.md:22。
- 身份仅「学号+姓名」单因子、无撤销入口/失败限流证据（2026-11-05 审计已列 H-5）`[文档]` audit_current_state.md:169-176,376。
- 审核测试身份 `3260799999`（`is_test=true`）仍可能在线；**是否已回收 `[未验证]`** `[文档]` 2026-11-05_test_account.sql:41-50、audit_current_state.md:365(B-4)。

---

## 6. 调用方（谁在用这个后端）

| 端 | 配置位置 | 值/说明 | 状态 |
|---|---|---|---|
| **网页** | `web/tools/index.html` | `APP_VER="2.0.0"`；文件 732,621 B、sha256 `656105117464c6d67106faa4011d5dd806d11d2c0d44760df961488d92e3b420`、mtime 2026-11-09 19:58:46；`var CB=` 网关基址（L2043，实测等式成立）；`var CBK=` 公开 publishable key（L2044，实测与 `publish_key.txt` 相同，值不抄）；`authHdr()` 带 `X-Device-Id`（L3366）；RPC 调用：`class_verify`(L3510)、`class_members`(L3524)、`class_set_role`(L3793)、`tt_login_status`(L7415)、`tt_login_enqueue`(L7449)、`diag_agent_info`(L8687)；直引表：`homework`(L2194)、`notices`(L2055/2058/2063)、`marks`(L2916)、`userdata`(L3181)、`feedback`(L4466)、`power`(L4882)、`power_history`(L4593)、`fitrecs`(L7997)、`visits`(L8200)、`diag_analysis`(L8884)、`repair_tasks`(L8886)、`service_health`(L8915)、`site_assets`（`ttSyncPull` 回退，CLOUDBASE.md:687）；`client_diag`（诊断上报） | 本地文件即当前版本（**线上 OSS 版本本轮不在本任务范围**） |
| **微信小程序** | `mp-class-tools/`（appid `wx3df9869d229b96c4`，`project.config.json:60`） | `utils/cloud-config.js:23` `restBase`=同一网关；`utils/cloud.js:33` 端点表（verify/members/diagAgent/ttLoginEnqueue/ttLoginStatus）；请求头 `X-Class-Token`；`utils/version.js` `VERSION='2.0.0'`；README.md:466,503 记载 request 合法域名=`tool-d4gosudok46e0e081.api.tcloudbasegateway.com` | `[文档]` 已发布（备案号 `闽ICP备2026042939号`，memory/2026-11-06.md:135,147）；`cloud-config.js` mtime 2026-11-07 07:33 |
| **安卓 App** | `android-class-tools/` | `gradle.properties:11` `ct.restBaseUrl=`同一网关；`app/build.gradle.kts:31-33` 默认值同 URL 并写入 `BuildConfig.REST_BASE_URL`；`docs/BACKEND_CONTRACT.md:20` 明确「后端只有一种形态 = CloudBase PG + PostgREST」 | `[文档]` release v3.2.0 已构建（memory/2026-11-09.md:1-8）；`gradle.properties` mtime 2026-11-07 23:09 |
| **本机写方（服务端账号）** | `C:\briefdesk\scripts\` | 管理员 token 写库：`sync_power_cloud.py`（power/power_history）、`sync_homework_cloud.py`、`sync_notices_cloud.py`、`health_beat.py`（local 10 行）、`web/jwxt/tt_cloud.py`（site_assets）、`web_pause.py`（site_config）、`diag_agent.py`（agent_keys/login_jobs/diag_analysis/repair_tasks）、`sync_class_roster.py`、`sync_league_roster.py`、`sync_audience_rosters.py`（private 名单） | `[文档]` 迁移文档:211-220、CLOUDBASE.md:604-607；本地调度见 task-3 |

> 结论：**三端 + 本机采集共用同一 env**；没有任何第二后端/自建 API。小程序/安卓只依赖这个网关（安卓另无第三方域名）。

---

## 7. 到期风险与续费/迁移现状（最关键的运营风险）

### 7.1 事实

- **到期时刻：2026-12-10 23:59:59**（个人版套餐）。距本轮审计（2026-11-09 22:13）**约 31 天**。`[文档]` 迁移文档:3-8；CLOUDBASE.md:690；web/AGENTS.md:101；HANDOFF.md:2073；memory/2026-11-08.md:54。
- **续费现状**：2026-11-08 17:37–18:0x 只读诊断记录「**`IsAutoRenew=true` 已开，仍需确认支付方式**」`[文档]` memory/2026-11-08.md:54；同日待办列「⑤确认 CloudBase 12-10 续费」`[文档]` memory/2026-11-08.md:57，11-08 末「CloudBase 2026-12-10 到期需续费/迁移」`[文档]` memory/2026-11-08.md:92。**2026-11-09 memory 无 CloudBase/续费更新**（grep 0 命中）→ 截至审计时**无续费完成/已确认证据** `[未验证]`。
- **迁移/灾备计划：无**。迁移文档只解决「把定时任务搬上云、降低电脑关机影响」，明确「不改变这个到期约束」`[文档]` 迁移文档:5；`deploy/cloudbase` 只有零散迁移 SQL，无新环境/备份/恢复演练记录（2026-11-05 审计已列）`[文档]` audit_current_state.md:331,338。
- **先例**：旧环境 `class-tools-d9gewpget3f15db3f` 到期未续 → 现 `Unavailable` `[文档]` 迁移文档:36。

### 7.2 到期后影响面（按消费端）

| 对象 | 到期后 | 依据 |
|---|---|---|
| PostgreSQL + PostgREST 网关 | **全部 REST 读写失败**（身份 `class_verify` 先挂） | 迁移文档:3-4 |
| 4 个云函数 + 3 个定时触发器 | 停止：电费每小时同步、英语作业每 2h、健康巡检每 5 分钟全停（**本机 fallback 仍在，但本机 fallback 也要写云，同样失败**） | 迁移文档:3-4,211-220 |
| 网页工具站 | 身份门禁 → 全部班级数据功能不可用（作业/通知/名单/电费/体测/反馈/诊断/课表回退），只剩 localStorage 缓存与同源静态 tt.json | CLOUDBASE.md:676-690 等 |
| 微信小程序 | 同网页：身份 + 全部数据 + 课表（site_assets 主链路）不可用 | mp README:466,503 |
| 安卓 App | 同网页 | android docs/BACKEND_CONTRACT.md:20 |
| 存储 | 本环境当前无 bucket（0 个，文档 2026-11-06 盘点）| 迁移文档:23,326 |

### 7.3 建议（给 Lead 汇总用）

1. **P0**：让用户确认 `IsAutoRenew=true` 的扣款方式/余额并在 2026-11-30 前完成续费确认；续费凭证（订单/到期日新值）需留存。
2. **P1**：在 2026-12-10 前做一次**只读数据快照/备份**（power/power_history/notices/homework/userdata/marks/private 名单）——CloudBase 个人版备份策略**未验证**，避免续费失败时数据不可恢复。
3. **P2**：把「触发器 cron、class_verify/class_sessions/auth_* 的线上 SQL、RLS 策略」从控制台导出并入库（§4.4/§9），否则换环境无法重建。
4. 若续费失败：至少提前 `web_pause.py --on` 类降级与用户公告（另见 task-1/3）。

---

## 8. 未验证清单（及只读核查方法）

| # | 未验证项 | 原因 | 只读核查方法（需 tcb 登录后） |
|---|---|---|---|
| 1 | 云函数当前是否仍部署、运行时/超时/内存、触发器 cron | `tcb` 未登录；invoke 禁止 | `tcb fn list -e tool-d4gosudok46e0e081 --json`；`tcb fn detail <fn> -e ... --json`；`tcb fn trigger list` / `tcb api scf ListTriggers` |
| 2 | 各表真实行数/最新数据时间 | 匿名 RLS 全 `[]`；本轮不使用管理员 token | 管理员 token 只读 GET（如 `GET power?select=id`）或 `tcb db execute --sql "select count(*) ..."` |
| 3 | 线上现行 RLS 策略全文 | 不进仓库 | `select tablename,policyname,cmd,qual,with_check from pg_policies where schemaname in ('public')` |
| 4 | `class_verify` / `auth_*` / `class_members` 服务端实现（token 生成、TTL、限流、清理） | 不进仓库 | `select proname,pg_get_functiondef(oid) from pg_proc where proname like 'class_%' or proname like 'auth_%'` |
| 5 | 云函数日志（CLS 未开通） | `LOG_SERVICE_NOT_ENABLED` | 控制台开通 CLS 或云监控 `GetMonitorData`（Invocation/Error/Duration） |
| 6 | CORS 白名单完整列表 | 只抽样 2 origin | `tcb cors list -e tool-d4gosudok46e0e081` |
| 7 | 小程序后台 request 合法域名实际配置 | 后台不可从本机只读 | 微信公众平台后台截图/导出（非本任务范围） |
| 8 | 静态托管配置/是否有自定义域名绑定 | 只测到默认域 404 | 控制台「静态托管/域名」页 |
| 9 | 测试身份 3260799999 是否已回收 | 需管理员读 `private.class_ids` | `select * from private.class_ids where is_test` |
| 10 | CloudBase 备份策略/回档能力 | 控制台特性 | 控制台计费/备份页 |
| 11 | 环境到期时间的「当前实时值」 | 需登录控制台/`tcb env list` | `tcb env list`（文档值 2026-12-10 23:59:59） |

---

## 9. 证据来源清单

### 9.1 本地文件（文件:行号）

| 内容 | 位置 |
|---|---|
| envId/region（web 侧） | `web/deploy/cloudbase/cloudbaserc.json:1-5` |
| 函数定义（briefdesk 侧，无触发器） | `C:\briefdesk\cloudbase\cloudbaserc.json:1-11` |
| 部署脚本/同源复制/环境变量名 | `C:\briefdesk\cloudbase\deploy.py:36-46,64-99,112` |
| 4 个函数代码 | `C:\briefdesk\cloudbase\functions\{hello,power_sync,xgj_sync,health_probe}\index.py` |
| 表结构/RLS 设计 | `web/deploy/cloudbase/schema.sql`、`security_hardening.sql`、`2026-11-04_visits_feedback_own_read.sql`、`2026-11-05_service_health.sql`、`2026-11-05_power.sql`、`2026-11-05_power_v2_names.sql`、`2026-11-05_notice_admin_override.sql`、`2026-11-05_test_account.sql`、`2026-11-06_power_history.sql`、`2026-11-07_site_assets.sql`、`2026-11-08_diag_login.sql` |
| 身份/迁移/运维总说明 | `web/CLOUDBASE.md`（关键：:16-22 身份、:66-76 表、:111-120 环境、:367-410 audience、:523-573 v6、:576-632 健康表、:634-690 测试身份+site_assets+到期提醒） |
| 云端迁移与部署记录 | `C:\briefdesk\docs\云端服务迁移_20261106.md`（:3-8 到期、:35-36 env、:99-102 函数、:115-182 验证、:211-220 本机 fallback、:228-237 环境变量、:253-259 cron、:361-393 风险） |
| 到期/续费现状 | `web/AGENTS.md:101`、`web/HANDOFF.md:2073,2360`、`memory/2026-11-08.md:54,57,92`、`memory/2026-11-09.md`（无相关条目） |
| 历史只读诊断（网关/18 行健康数据） | `memory/2026-11-08.md:50-54` |
| 上轮隐私审计（漂移/风险/Q 清单） | `web/_compliance/audit_current_state.md:117-136,327-332,348,422` |
| 小程序/安卓配置 | `mp-class-tools/utils/cloud-config.js:23`、`utils/cloud.js:33`、`utils/version.js`、`project.config.json:60`、`README.md:466,503`；`android-class-tools/gradle.properties:11`、`app/build.gradle.kts:31-33`、`docs/BACKEND_CONTRACT.md:20,27` |
| 网页常量/调用 | `web/tools/index.html:2043-2070,2194,2916,3181,3366,3510,3524,3793,4466,4593,4882,7415,7449,7997,8200,8687,8884-8915` |

### 9.2 命令 + 关键输出 + 时间戳（本轮只读实测）

| 时间 | 命令/请求（摘要） | 关键输出 |
|---|---|---|
| 22:09:35 | `tcb --version`；`Get-Command tcb/tccli`；检查 `~/.config/cloudbase`、项目 `.cloudbase/` | `CloudBase CLI 3.8.7`；tccli 未安装；`~/.config/cloudbase` 不存在；各 `.cloudbase/` 目录 absent |
| 22:09:59 | `tcb env list`（只读，未登录） | `Using the global default environment: tool-d4gosudok46e0e081`；`× No valid identity found, please log in with tcb login`；exit=2 |
| 22:10:00–22:10:03 | 18 张 `public` 表 + 6 条边界 GET（publishable key） | 表 GET 全部 200 `[]`；`class_ids/private.class_ids/no_such_table` 404 `DATABASE_PGRST205` |
| 22:10:03 | 无 `Authorization` GET `service_health?select=id` | **401** `MISSING_CREDENTIALS` |
| 22:10:03 | `Origin` CORS 抽样 | `tool.furina.fun`→200 + ACAO echo；`example.com`→403 |
| 22:10:12 / 22:10:27 | `GET /v1/rdb/rest/`（Accept openapi+json） | 200，79,759 字符；swagger、`standard public schema`；**18 表 + 23 rpc + 42 paths**（清单见 §3.1） |
| 22:11:09 / 22:11:10 | publish key + 伪造 `X-Device-Id` / `X-Class-Token` | 200 `[]`（不报错） |
| 22:11:10 | 本地解码 publishable key JWT 元数据（不打印值） | `role=anon`、`is_anonymous=true`、`aud=envId`、`iat=2026-10-10 08:54:40`、`exp=2099-10-10 08:54:40`、长度 1150 |
| 22:11:10 | DNS/TLS 探测 `tool-d4gosudok46e0e081.api.tcloudbasegateway.com` | CNAME `prod.paasgw.tencentcloudbase.com` → 81.69.138.235/81.69.216.233；TLS1.3；`*.tcloudbasegateway.com` DigiCert；notAfter 2027-05-02，剩 173.4 天 |
| 22:12:25 | `users/identity_verify/class_sessions/class_league/class_audience` 匿名 GET；`power?select=count` | 全部 404（public 路径无表）；`power?select=count` → `[{"count":0}]` |
| 22:12:4x | 静态托管默认域 GET | `...-1419350518.tcloudbaseapp.com` → 404；`...tcloudbaseapp.com` → `INVALID_HOST` |
| 22:13:07 | 校验 `index.html` 的 `var CB`/`var CBK` 与部署文件 | CB 等于网关基址 True；CBK == `publish_key.txt` True（未打印值）；文件 732,621 B / sha256 `656105…e3b420` / mtime 2026-11-09 19:58:46 |

> 备注：**本轮所有请求均为 GET**；未发任何 POST/PUT/PATCH/DELETE（含 `/rpc/*`）；未 invoke 云函数；未调用 `tcb login`；未读/打印任何密钥值。publishable key 作为「设计上公开」的凭据仅用于上述只读探测。
