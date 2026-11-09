# 班级工具站 · 合规现状审计（个人信息 / 隐私披露 / 权限 / 安全）

> **审计性质**：只读审计。未修改任何项目代码，未向云端写入任何数据，未读取 `deploy/creds.env`、`tools/cert/`、`deploy/acme_account_key.pem`、`jwxt/creds.dpapi`、`C:\briefdesk\secrets\` 等机密文件内容；文中不含 token / 密钥 / 完整手机号 / 完整体学号（均做掩码或只给数量）。
>
> **审计对象**：H5 站点 `web\tools\index.html`（线上 `https://tool.furina.fun`）+ 微信小程序 `mp-class-tools\`（个人主体，未发布）+ 腾讯云 CloudBase 后端 + 本机采集管道 `C:\briefdesk\`。
>
> **审计时间**：2026-11-05 22:30–22:55（Asia/Shanghai）。
>
> ⚠️ **快照说明（重要）**：审计期间 `tools\index.html` 被其他并行会话**多次改写**（22:23 → 22:33 → 22:38，字节数 468,856 → 454,498 → 468,856）。本报告行号以 **审计时工作副本 C（468,856 B，sha256 `7A2704E0FC3DF225A113F9E1E2A85709945EEED6211D6D7D508C58D11ACFE1AD`，mtime 22:38:51）** 为准；线上部署版本为 **O（453,951 B，sha256 `186651F292AFE28292F9AE91D522E0C2657CB033ED044D7903BA21AA70219F82`，与 `tools\_backup\index_online_20261105-2215_preFlickerFix.html` 逐字节一致，2026-11-05 22:03 部署）**。两版除「诊断页」等少量差异外，身份 / 隐私 / 通知 / 导出相关实现一致。**建议：转合规改造开工前先把 H5 冻结一个发布版本（git 或哈希锚定），否则审计与整改无法对齐。**

---

## 0. 执行摘要

**一句话结论**：功能侧已经具备「班级内可用」的完整形态，但**隐私合规链路是断裂的**——收集前没有隐私政策与同意、通知内容来自未经授权的群聊抓取并二次分发（含手机号与 OCR 名单）、云端数据「只进不出」（无删除权、无保留期限）、H5 无备案与强制 HTTPS；另有一个测试身份仍在线、H5 线上公开文件里还留着 2 个真实学号。按「转合规可备案 App」目标，**当前状态不具备提交审核/备案/上架条件**。

**差距数量（详见 §10）**：

| 级别 | 数量 | 代表性问题 |
|---|---|---|
| 🛑 阻断上线 | **5** | 无隐私政策/用户协议/同意；群聊抓取与二次分发无授权；无 ICP 备案与备案号；测试身份仍在线；小程序后台隐私指引与真实隐私接口不符 |
| 🔴 高风险 | **12** | 通知含 11 位手机号并对全班可见；H5 无数据管理页且退出不清主数据桶；云端无删除通道/无保留期限；数据最小化（全班学号下发等）；弱身份鉴权；H5 公开文件含真实学号；本机密钥与群聊原文明文集中；RLS/DDL 仓库漂移；非官方 QQ/微信客户端采集；HTTP 明文可访问；UGC 无内容审核；AI 处理链路未脱敏且无委托告知 |
| 🟠 中风险 | **11** | 敏感人群标签（团员/献血/评议/舍长/红会）无单独同意；未成年人条款缺失；附件/图片 base64 上云；披露表述不准确；数据权利两端不一致；导出图含健康数据；无 PIA/处理记录；数据地域与备份待确认；历史归档无清理；第三方链接无提示；多端框架配置待复核 |
| 🟡 低风险 | **9** | 课表公网可读（公开课程信息）；文档过期；服务健康表残留；命名/编号/水印规范良好（正面）；零外链/SDK（正面）；CORS 锁定（正面）等 |
| ❓ 待确认 | **12** | 云端 RLS 现行策略、class_verify 实现与 token TTL、限流、云函数 env 归属、后台隐私指引实际声明、上传包内容清单等（附只读核查方法） |

**线上只读探测（2026-11-05 22:40–22:41，未写数据）**：
- 匿名（仅公开 publishable key、无 token）GET `homework/notices/roster/visits/feedback/marks/fitrecs/userdata/service_health`，全部 `200` + **空数组 `[]`** → 匿名读确实被 RLS 挡住（与文档一致）。`users`、`identity_verify` 返回 **404（表已删除）**。
- CORS 预检：`Origin: https://tool.furina.fun` → `204`，`Access-Control-Allow-Origin` 精确回该站点、允许 `X-Device-Id`；`Origin: https://evil.example` → **403**（白名单有效）。
- 站点：`http://tool.furina.fun/` 与 `https://tool.furina.fun/` 均 **200**，**HTTP 未强制跳转 HTTPS**；线上 HTML 为上面 O 版本。

---

## 1. 系统与数据流总览

```
【使用端】
  H5（单文件 index.html，阿里云 OSS 香港，Let's Encrypt 证书）
    ├─ 身份门禁：学号+姓名 → POST {CloudBase}/rpc/class_verify → 30 天类 token
    ├─ 数据：homework / notices / marks / userdata / fitrecs / visits / feedback / service_health（管理员诊断）
    ├─ 缓存：localStorage（zq_tools_v2_<sid> 等） + IndexedDB（通知板约 2 MB）
    └─ 导出：canvas 图片（水印/编号，含姓名，无学号/手机号）

  微信小程序（原生 18 页，个人主体 AppID wx3df9869d229b96c4，未上传/未发布）
    ├─ 身份：同一 CloudBase rpc/class_verify → wx storage zq_class_identity
    ├─ 数据：同一批 CloudBase 表（X-Class-Token）
    ├─ 订阅消息：微信云开发云函数 notify（env fengdan-d6g7hnk4gf35685b3，集合 subscriptions 存 openid）
    ├─ 课表：GET https://tool.furina.fun/tt.json（跨域只读）
    └─ 数据与隐私页：导出我的数据 / 清除云端我的数据 / 清除本机数据

【云端】
  腾讯云 CloudBase 环境 tool-d4gosudok46e0e081（ap-shanghai，PostgreSQL + PostgREST）
    ├─ public.homework / notices / marks / userdata / fitrecs / visits / feedback / roster / service_health
    ├─ private.class_ids（70 人真实名单）/ class_sessions（token 会话）/ class_audience / class_league
    └─ RPC：class_verify / class_members / class_set_role

【本机采集管道 C:\briefdesk】
  QQ NT 本地库（qqflow，非官方只读） + 微信本地库（weflow，wcdb-key 提库密钥后只读）
    → 文本筛选 / 本地 OCR（RapidOCR，离线） / AI 批处理（DeepSeek 官方 API，境内）
    → 群消息＋发送人＋OCR 文本 → C:\briefdesk\data\board-data.json
    → sync_notices_cloud.py（管理员 token）→ 云端 public.notices（body = [[CLASS_NOTICE_V1]] + JSON）
  health_beat.py（每 5 分钟，watchdog 调用）→ public.service_health（13 项依赖状态，仅管理员可读）
```

**角色/主体**：运营者为个人（非企业），无网站/App 备案主体能力之外的资质；处理者身份在 H5 与小程序内均未披露。

---

## 2. 个人信息数据清单

### 2.1 汇总表

| # | 数据项 | 具体字段 / 内容 | 来源 | 用途 | 存储位置 | 上云？ | 保留 / 删除 | 可导出？ | 敏感度 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 学号 | `sid`（10 位） | 用户输入 + 官方花名册（`private.class_ids`） | 身份校验、数据归属（`marks.seat`、`userdata.id`、`fitrecs.acc`、`visits.sid`、`feedback.acc`、`homework.owner`） | 云端 `private.class_ids`（权威）→ 登录后 `class_members` 下发到每台设备 | 是 | 云端无期限；本机随缓存 | 小程序可（导出去学号）；H5 不可 | 高（身份识别） |
| 2 | 姓名 | `name` | 用户输入 + 官方花名册 | 身份校验、页面展示（抽签/名单/统计/反馈） | 同上 + 页面 | 是 | 同上 | 同上 | 高 |
| 3 | 班级角色 | `role`、`badge`、`is_admin` | 《班委会拟定结果》导入，管理员可改 | 班委页、权限判定 | 云端 `private.class_ids` | 是 | 无期限 | 导出去 token/名单 | 中 |
| 4 | 身份 token | `token`（30 天） | `class_verify` 签发 | 所有数据请求鉴权 | H5 `localStorage zq_class_identity`；小程序 `wx storage zq_class_identity`；本机采集 `C:\briefdesk\secrets\class-token.json`（管理员 token） | 否（仅请求头 `X-Device-Id` / `X-Class-Token`） | token 30 天；客户端 29 天自动登录；无撤销入口 | 否 | 高（等价口令） |
| 5 | 同学操作痕迹（本人） | 作业完成、通知已处理/置顶 | 用户操作 | 跨端同步 | 云端 `marks`（id=`sid|kind|ref`） | 是 | 无期限（取消写 false，不 DELETE） | 小程序导出 marks | 中 |
| 6 | 用户偏好/个人内容 | 工具顺序、抽签/分组参数与名单选择、点名名单与到·假、隐藏项、课表偏好、昵称、体测输入草稿 | 用户操作 | 跨端同步 | 云端 `userdata`（单行 `id=sid`, blob v6） | 是 | 无期限；可覆盖为空 | 小程序导出 | 中 |
| 7 | 体测健康数据 | 身高、体重、BMI、肺活量、50 米、坐位体前屈、立定跳远、引体/仰卧、长跑；性别、年级组、总分、等级、记录名 | 用户输入 | 体测算分与历史（最多 2 条） | 云端 `fitrecs.data`（JSON） | 是 | 无期限；删除 = `arch=true` 软删 | 小程序导出（含 total/grade，摘要） | **高（敏感：健康）** |
| 8 | 访问行为 | `slot`（小时级时间）、`sid`、`name`、`did`（随机设备码）、`ts` | 前端埋点（H5 每小时一次；小程序每小时一次） | 管理员统计访问 | 云端 `visits`；本机 `zq_visit_did` / `zq_visit_slot_*` | 是 | 无期限、**无法删除**；管理员可读全部 | 不可 | 中（行为画像） |
| 9 | 反馈 | 内容、联系方式（H5 收集 QQ/微信，可选）、`acc`(sid)、`done`、`ts` | 用户输入 | 管理员处理 | 云端 `feedback` | 是 | 无期限、**无法删除**；管理员可读 | 不可 | 中 |
| 10 | 作业内容与附件 | 科目/内容/截止/作者昵称/`owner`(sid)/图片与文件 base64（原图 ≤5 MB 压缩、文件 ≤2 MB，最多 2 个） | 用户输入 | 班级共享 | 云端 `homework.attachments`；本机缓存 | 是 | 无期限；`archived` 软删；anon 无 DELETE | 作业可导出图 | 中（附件可能含他人信息） |
| 11 | 通知内容 | 标题、正文 JSON：来源群、摘要、AI 摘要/要点、截止/事件/失效时间、**发送人姓名/职务/徽章**、OCR 文本、原始消息 `items`（`from`/`fromName`/`text`/图片 base64）、附件、管理员编辑字段 | **QQ/微信班级群消息**（含非本班群） | 班级通知板 | 云端 `notices.body`（单行最大约 40 万字节，整表约 2.4 MB payload）；本机 `board-data.json` 2.45 MB + H5 IndexedDB / 小程序分块缓存 | 是 | 无期限（归档=archived）；无硬删除通道 | H5 不导出通知；小程序可读 | **高（含第三方个人信息）** |
| 12 | 群成员身份映射 | QQ uin / 微信 wxid / 群名片 / 备注 / 昵称 / 群列表 / QQ 头像 dHash | 本机 QQ/微信库 + `q.qlogo.cn` 头像下载 | 把群名片匹配到班级成员（用于通知可见人群） | **仅本机** `C:\briefdesk\data\class-identities.json`、`avatars/qq/*.jpg`、`class-aliases.json` | 否 | 无限期（未设计清理） | 否 | 中 |
| 13 | 人群/敏感标签 | 团员名单（`private.class_league`，50 人）、运动会志愿者/观众、无偿献血、评议小组、舍长、红会（`private.class_audience`：audience/sid/seat/name） | QQ/微信群成员身份 | 通知可见人群控制 | 云端 `private.*`（无 API 暴露） | 是 | 每次同步覆盖 | 否 | **高（政治面貌/健康相关推断）** |
| 14 | openid / 订阅消息 | 微信 `openid`；提醒种类、ref、摘要 ≤20 字、时间文案、状态 | 微信授权 `requestSubscribeMessage` | 发送作业/通知提醒 | 微信云开发 `subscriptions` 集合 | 是（微信云开发） | 发送后 `active=false`，无清理策略 | 否 | 中 |
| 15 | 课表 | 32 条课程（课程名、教师姓名、教室、周次） | 教务系统同步（运营者本人账号，DPAPI 本机保存） | 全员课表 | **公网静态** `tools/tt.json`（OSS 香港，无需登录即可 GET） | 是（公开） | 无期限 | 本地导出 | 低（公开课程信息） |
| 16 | 附件图片/OCR 图片 | 通知中的图片、附件 data URI | 群消息 | 通知展示 | 云端 `notices.body` + 本机/端内缓存 | 是 | 无期限 | 否 | **高（图片可能含名单/照片/手机号）** |

### 2.2 H5 本机存储（用户设备）

| 位置 | 键 / 库 | 内容 | 退出身份是否清除 |
|---|---|---|---|
| localStorage | `zq_class_identity` | `{token,sid,name,role,badge,is_admin,ts}`（[index.html:2422-2424](../tools/index.html#L2422-L2424)） | 是（`identityClear`） |
| localStorage | `zq_last_identity` | `{sid,name}`（[index.html:6093](../tools/index.html#L6093)） | 是（[index.html:6125](../tools/index.html#L6125)） |
| localStorage | `zq_tools_v2_<sid>` | 主数据桶：`members`（**70 人姓名+学号+角色**，[index.html:2573-2578](../tools/index.html#L2573-L2578)）、作业/通知缓存、点名到·假、体测记录、抽签参数等（`D.save`，[index.html:1194](../tools/index.html#L1194)；按 sid 分桶 [index.html:1166](../tools/index.html#L1166)） | **否（关键缺口）** |
| localStorage | `zq_udcache_<sid>` / `zq_udpend_<sid>` / `zq_udat_<sid>` | userdata 合并缓存/待补发/时间 | 是（[index.html:2515](../tools/index.html#L2515)） |
| localStorage | `zq_marks_cache_<sid>`、`zq_synced_at_<sid>`、`zq_visited_<sid>`、`zq_cache_gen_<sid>` | 勾选缓存/同步时间/访问标记/缓存代次（[index.html:2435](../tools/index.html#L2435)） | 是（[index.html:2512-2514](../tools/index.html#L2512-L2514)） |
| localStorage | `zq_visit_did`、`zq_visit_slot_<sid>` | 随机设备码 / 本小时已上报标记（[index.html:5230-5235](../tools/index.html#L5230-L5235)） | 否（did 残留，低风险） |
| localStorage | `zq_auto_nt_done`、`zq_tt_pub`、`zq_last_identity` 等 | 旧通知已处理缓存/课表发布快照 | 部分（旧键会迁移后清除） |
| sessionStorage | `zq_pos_v1`、`zq_nt_scroll_v1` | tab/滚动位置 | 是（`POS.clear`） |
| IndexedDB | `zq_cache_v1`（store `kv`） | 通知板整表缓存（约 2 MB，含发送人/OCR/图片 data URI），按 sid 分桶（[index.html:2433](../tools/index.html#L2433)、[2437-2506](../tools/index.html#L2437-L2506)） | 是（按 sid 删除，[index.html:2516-2523](../tools/index.html#L2516-L2523)） |

### 2.3 小程序本机存储（用户设备）

| 位置 | 键 | 内容 | 退出身份 |
|---|---|---|---|
| wx storage | `zq_class_identity` | `{token,sid,name,role,badge,is_admin,ts}`（[identity.js:10-13](../../mp-class-tools/utils/identity.js#L10-L13)） | 是（`identity.clear`，[identity.js:63-67](../../mp-class-tools/utils/identity.js#L63-L67)） |
| wx storage | `zq_tools_v2` | 主数据：`classMembers`（**70 人含学号**，[store.js:28](../../mp-class-tools/utils/store.js#L28)、[108](../../mp-class-tools/utils/store.js#L108)）、作业/通知/体测记录/名单选择/点名/隐藏/偏好/昵称/did 等 | 是（`cache.clearAll` 会全清） |
| wx storage | `zq_flow` | 抽签→分组→结果单状态 | 是 |
| wx storage | `zqc1_*` 分块缓存 | 通知整表约 2 MB（含发送人、OCR、图片/附件 data URI），单块 ≤600 KB、总预算 5 MB（[cache.js:1-27](../../mp-class-tools/utils/cache.js#L1-L27)） | 是 |
| wx storage | `zq_visit_slot`、主数据内 `did` | 访问去重标记、随机设备码（[cloud.js:1331-1356](../../mp-class-tools/utils/cloud.js#L1331-L1356)） | 部分 |
| wx storage | 主数据内 `ntRemind` | 通知提醒本地设置 | 是 |

### 2.4 云端存储表（CloudBase PostgreSQL，ap-shanghai）

| 表 | 关键列 | 主要写入方 | 读取限制（文档/实测口径） | 删除能力 |
|---|---|---|---|---|
| `public.homework` | id/subject/content/due/date/time/author/`owner`/attachments(base64)/done/archived/ts（[schema.sql:6-26](deploy/cloudbase/schema.sql#L6-L26)） | H5/小程序（登录用户） | 需有效 token（文档口径）；匿名 SELECT 实测 `[]` | 无 DELETE policy（软删 `archived`） |
| `public.notices` | title/body(自动通知 JSON)/audience/override_json/hidden/edited_at/edited_by/archived/ts（[schema.sql:47-61](deploy/cloudbase/schema.sql#L47-L61)、[2026-11-05_notice_admin_override.sql:23-26](deploy/cloudbase/2026-11-05_notice_admin_override.sql#L23-L26)） | 采集脚本（管理员 token）、管理员编辑 | `audience` 过滤（all/committee/league/set:sid，[CLOUDBASE.md:367-410](CLOUDBASE.md#L367-L410)）；匿名实测 `[]` | `archived`/`hidden` 软删 |
| `public.marks` | id/seat/kind/ref/val/ts | H5/小程序本人 | 仅本人（按 `seat = auth_acc()`，[security_hardening.sql:60-69](deploy/cloudbase/security_hardening.sql#L60-L69)） | 无 DELETE（置 false） |
| `public.userdata` | id(=sid)/blob v6/ts | H5/小程序本人 | 仅本人（[security_hardening.sql:84-93](deploy/cloudbase/security_hardening.sql#L84-L93)） | 无 DELETE（覆盖） |
| `public.fitrecs` | id/acc(=sid)/data(JSON)/arch/ts | 本人 | 仅本人（[security_hardening.sql:72-81](deploy/cloudbase/security_hardening.sql#L72-L81)） | 无 DELETE（`arch`） |
| `public.visits` | id/slot/sid/name/did/ts | H5/小程序本人 | 管理员 OR 本人行（[2026-11-04_visits_feedback_own_read.sql:19-21](deploy/cloudbase/2026-11-04_visits_feedback_own_read.sql#L19-L21)） | **无 DELETE** |
| `public.feedback` | id/content/contact/acc/done/ts | H5/小程序 | 管理员 OR 本人行（[2026-11-04_visits_feedback_own_read.sql:23-25](deploy/cloudbase/2026-11-04_visits_feedback_own_read.sql#L23-L25)） | **无 DELETE** |
| `public.roster` | id='main'/data(JSON 旧名单)/ts | 历史 | 登录可读（[security_hardening.sql:51-52](deploy/cloudbase/security_hardening.sql#L51-L52)）；**前端已改用 `class_members`，本表为遗留** | 无 DELETE |
| `public.service_health` | id/name/kind/status/detail/meta/checked_at（[2026-11-05_service_health.sql:25-34](deploy/cloudbase/2026-11-05_service_health.sql#L25-L34)） | 采集主机心跳 | 仅管理员（[2026-11-05_service_health.sql:42-51](deploy/cloudbase/2026-11-05_service_health.sql#L42-L51)） | 无 DELETE |
| `private.class_ids` | seat/name/sid/role/badge/is_admin/is_test | 一次性导入 + 管理员 | **无 API**（私有 schema，仅 SECURITY DEFINER 函数校验，[CLOUDBASE.md:66](CLOUDBASE.md#L66)、[343-344](CLOUDBASE.md#L343-L344)） | 无常规删除 |
| `private.class_sessions` | token/sid/name/expires_at | `class_verify` | 不对外暴露（[CLOUDBASE.md:67](CLOUDBASE.md#L67)） | 无清理任务可见（待确认） |
| `private.class_audience` | audience/sid/seat/name/updated_at（[audience_sets.sql:10-17](C:/briefdesk/scripts/sql/audience_sets.sql#L10-L17)） | 人群同步脚本 | 私有 schema | 每次同步先 DELETE 再写 |
| `private.class_league` | sid/seat/updated_at（[league_audience.sql:16-20](C:/briefdesk/scripts/sql/league_audience.sql#L16-L20)） | 团员名单脚本 | 私有 schema | 无 |
| 微信云开发 `subscriptions` | openid/kind/ref/fireAt/label/tip/timeText/summary/dateText/active/attempts/…（[cloudfunctions/notify/index.js:95-147](../../mp-class-tools/cloudfunctions/notify/index.js#L95-L147)） | 云函数 notify（微信云开发 env `fengdan-d6g7hnk4gf35685b3`） | 仅云函数（管理端） | 无清理策略，发送后仅 `active=false` |

> 已核实：`public.users`、`public.identity_verify` 已从云端删除（匿名 GET 均 404，2026-11-05 22:41 实测），与 [CLOUDBASE.md:76](CLOUDBASE.md#L76) 一致；但仓库里 [schema.sql:176-199](deploy/cloudbase/schema.sql#L176-L199)、[identity_schema.sql:16-25](../../mp-class-tools-tests/identity_schema.sql#L16-L25) 仍保留旧表定义（漂移，见 §9.3）。

### 2.5 本机采集管道（`C:\briefdesk`）

| 文件 / 目录 | 内容 | 规模（审计时） | 是否加密/清理 |
|---|---|---|---|
| `data\board-data.json` | 自动通知聚合：群消息原文、发送人、OCR 文本、AI 摘要、内嵌图片 data URI | **2,454,054 B**（sha256 `A18CC864…BACC5`，22:36） | 否；无清理 |
| `data\ai-triage-state.json` / `ai-triage-notices.json` | 已判消息缓存 / AI 识别结果 | 21 KB / 10 KB | 缓存保留 45 天（代码注释） |
| `data\ocr-cache.json` / `ocr-images.json` | 图片 OCR 缓存 / 最近 7 天 OCR 结果 | 16 KB / 11 KB | 缓存 30 天 / 输出 7 天（[ocr_qq_images.py:44-45](C:/briefdesk/scripts/ocr_qq_images.py#L44-L45)） |
| `data\qq-image-notices.json` | 图片通知（可能含图片/发送人） | 711 KB | 未设计清理 |
| `data\class-identities.json` / `class-aliases.json` | 每个班级成员的 QQ/微信身份、网名、备注、群名片、头像路径（[build_identity_map.py:2-13](C:/briefdesk/scripts/build_identity_map.py#L2-L13)） | 251 KB / 10 KB | 否 |
| `data\avatars\qq\*.jpg` | 下载的 QQ 头像缓存（[build_identity_map.py:172-186](C:/briefdesk/scripts/build_identity_map.py#L172-L186)） | 目录 | 否 |
| `data\images\`、`data\qq-files\` | 群图片/文件原件 | 目录 | 否 |
| `secrets\` | `cloud-ai.json`（DeepSeek key）、`class-token.json`（管理员班级 token，25 天）、`qqflow-token/key`、`weflow-token/keys`（22 个微信库密钥）、`ecs_*`、`ecs-root.txt` 等 | — | **明文文件**，README 称目录 ACL 已收紧（[README-下一步.md:39](C:/briefdesk/README-下一步.md#L39)） |

---

## 3. 身份与授权审计

### 3.1 现状

- **门禁实现**：启动即身份页，输入「学号 + 姓名」→ `POST /rpc/class_verify`（H5 [index.html:721-730](../tools/index.html#L721-L730)、[2569-2571](../tools/index.html#L2569-L2571)；小程序 [identity.wxml:27-42](../../mp-class-tools/pages/identity/identity.wxml#L27-L42)）。通过后云端签发 token（文档称 30 天，[CLOUDBASE.md:16-22](CLOUDBASE.md#L16-L22)）；H5 存 `localStorage.zq_class_identity`，请求头 `X-Device-Id`（[index.html:2426](../tools/index.html#L2426)）；小程序 `X-Class-Token`（[cloud.js:120-130](../../mp-class-tools/utils/cloud.js#L120-L130)）。
- **身份数据权威**：`private.class_ids`（70 人：seat/name/sid/role/badge/is_admin，[CLOUDBASE.md:66](CLOUDBASE.md#L66)）；登录后 `rpc/class_members` 下发 **70 人含学号**（[CLOUDBASE.md:42-52](CLOUDBASE.md#L42-L52)、H5 [index.html:2580-2584](../tools/index.html#L2580-L2584)）；小程序 `classMembers` 同样缓存（[store.js:28](../../mp-class-tools/utils/store.js#L28)）。
- **管理员**：`is_admin=true`（当前仅 1 人，学号 `32607070**`，[CLOUDBASE.md:74](CLOUDBASE.md#L74)）；H5 `canManage()=AUTH.is_admin`（[index.html:2527](../tools/index.html#L2527)），可改班委职务（`rpc/class_set_role`，[index.html:2850](../tools/index.html#L2850)）、读全部 `visits`/`feedback`、编辑/隐藏通知（[index.html:1612-1650 附近](../tools/index.html#L1612)）、读 `service_health` 诊断页（[index.html:5329-5472](../tools/index.html#L5329-L5472)）。
- **token 生命周期**：服务端 30 天（文档）；客户端本地 `ts` <29 天自动进入（[index.html:6130](../tools/index.html#L6130)）；**没有服务端过期/吊销后的回门禁逻辑**——`identityClear()` 只在手动退出时调用（[index.html:6124](../tools/index.html#L6124)），数据请求 401 时仅静默失败，与 [CLOUDBASE.md:22](CLOUDBASE.md#L22)「token 失效后页面会重新回到身份门禁」**不一致**。
- **匿名可读性**：实测匿名 SELECT 全部返回 `[]`（§0）；`class_members` 无 token 返回 `[]`（实测 POST 200 + `[]`）。
- **CORS**：仅 `tool.furina.fun`（实测 204/403，§0），并放行 `X-Device-Id` 自定义头（与 [CLOUDBASE.md:19](CLOUDBASE.md#L19) 一致）。

### 3.2 弱点与风险

| 问题 | 证据 | 影响 |
|---|---|---|
| **学号+姓名即凭证，无第二因子** | [index.html:2569-2571](../tools/index.html#L2569-L2571)、[identity.js:103-117](../../mp-class-tools/utils/identity.js#L103-L117) | 学号有固定规律（同班前 8 位相同）、姓名在群/文件中易得 → 同学间可冒用；对「仅本班同学可进入」的承诺不成立（[index.html:730](../tools/index.html#L730)） |
| **无失败限流/锁定/风控证据** | 仓库内 `class_verify` 实现/DDL 缺失（§9.3、§11） | 可被枚举/爆破；审计无法确认云端是否有限流（待确认） |
| **token 明文存储、30 天、无撤销入口** | [index.html:2422-2424](../tools/index.html#L2422-L2424)、[identity.js:52-61](../../mp-class-tools/utils/identity.js#L52-L61) | 设备共享/被查看/localStorage 被读即失守；管理员 token 还被明文放在 `C:\briefdesk\secrets\class-token.json` |
| **全班学号下发到每台设备** | `class_members` 返回 sid（[CLOUDBASE.md:52](CLOUDBASE.md#L52)）、H5 `D.d.members`（[index.html:2573-2578](../tools/index.html#L2573-L2578)）、小程序 `classMembers` | 违反最小必要：抽签/点名仅需座号+姓名；学号并非功能必需（仅用于内部归属） |
| **管理员权限过度集中** | 单管理员硬编码（`is_admin`）；可读全部 `visits/feedback`；无操作审计日志（仅通知有 `edited_by`，[2026-11-05_notice_admin_override.sql:9-13](deploy/cloudbase/2026-11-05_notice_admin_override.sql#L9-L13)） | 管理员可看全班访问行为/反馈联系方式；无追责/审计链 |
| **测试身份仍在线** | [2026-11-05_test_account.sql:41-46](deploy/cloudbase/2026-11-05_test_account.sql#L41-L46)（已应用）；凭据写在 `web\验收报告\v2.0.0_交付说明.md`（未读，据 [CLOUDBASE.md:583-584](CLOUDBASE.md#L583-L584)） | 拿到交付说明者可登录并查看 `audience=all` 全班数据；审核结束未回收 |
| **H5 公开文件含真实学号** | 线上 O 版 [_backup:2852-2853](../tools/_backup/index_online_20261105-2215_preFlickerFix.html#L2852-L2853)、工作副本 [index.html:2849-2850](../tools/index.html#L2849-L2850)：legacy 迁移硬编码两个真实学号（`32607070**`、`32607070**`） | 任何人下载公开 HTML 即可获得 2 个真实学号（且 OSS 香港公开可读）；管理员身份暴露 |

---

## 4. 隐私披露与同意审计

### 4.1 H5（线上站点）

- **身份页**只有 3 行文案：「2026级信息管理与信息系统 · 身份进入」「仅本班同学可进入；身份校验通过后才加载班级数据」（[index.html:721-730](../tools/index.html#L721-L730)；线上 O 版 [L691-700](../tools/_backup/index_online_20261105-2215_preFlickerFix.html#L691-L700)）。
- **无《隐私政策》**、**无《用户协议》**、无独立隐私入口、无「同意」勾选；全文检索「隐私/用户协议/个人信息/ICP」仅命中无关注释（H5 与线上 O 版均如此）。
- **无备案号**、无处理者名称/联系方式。
- **使用说明中的披露**（[index.html:1068-1070](../tools/index.html#L1068-L1070)）：「身份只用于名单校验」「班级名单与身份 token 只存本机；可退出身份清除本机数据」——两处均**不准确**：身份还用于数据归属/统计/反馈；退出身份**不会**清除主数据桶（§2.2）。
- **反馈页**仍收集「联系方式（QQ/微信，可选）」（[index.html:1031](../tools/index.html#L1031)、提交 [index.html:3054-3058](../tools/index.html#L3054-L3058)），而小程序已停止收集（[fb.js:3](../../mp-class-tools/pages/fb/fb.js#L3)）。
- **无数据管理页**：导出/更正/删除/注销在 H5 均无入口；唯一「退出身份」按钮（[index.html:6120-6127](../tools/index.html#L6120-L6127)）只清身份与部分缓存。
- **收集时机**：页面加载即要求输入学号+姓名并上传云端校验，**之前没有任何告知或同意**（无弹窗、无链接）。

### 4.2 微信小程序

- **身份页**：有「数据与隐私」说明卡片（[identity.wxml:45-54](../../mp-class-tools/pages/identity/identity.wxml#L45-L54)）：「姓名 / 学号 / 角色只用于班级名单校验」「云端同步：作业 / 通知 / 勾选 / 体测 / 访问统计按账号同步」等；**无同意勾选**、无隐私政策链接；按钮仅「验证并进入」（[identity.wxml:41](../../mp-class-tools/pages/identity/identity.wxml#L41)）。
- **「数据与隐私」页**（`pages/data`）相对完整：同步开关、同步范围、本机数据概览、云端数据（明确「访问统计/反馈无法删除」）、导出我的数据（剪贴板 JSON，不含 token/学号/名单原文）、清除云端我的数据、清除本机数据、隐私说明 8 条（[data.wxml:14-128](../../mp-class-tools/pages/data/data.wxml#L14-L128)；导出/清除逻辑 [privacy.js:100-161](../../mp-class-tools/utils/privacy.js#L100-L161)）。
- **披露缺口/不准确**：
  - 隐私说明「收集」清单未列**学号本身**、**班级名单缓存（他人姓名/学号）**、**通知内容（含群消息发送人姓名/手机号/OCR 文本）**；
  - 「不采集：证件信息、位置、通讯录、**相册**」（[data.wxml:116](../../mp-class-tools/pages/data/data.wxml#L116)）与实际使用 `wx.chooseMedia`（相册/相机，[hw.js:369](../../mp-class-tools/pages/hw/hw.js#L369)）、`wx.chooseMessageFile`（[hw.js:385](../../mp-class-tools/pages/hw/hw.js#L385)）、`wx.saveImageToPhotosAlbum`（保存相册，[canvas.js:519-531](../../mp-class-tools/utils/canvas.js#L519-L531)）**矛盾**；
  - 「云端数据只有本人 token 可读」（[data.wxml:51](../../mp-class-tools/pages/data/data.wxml#L51)）与「访问统计/反馈管理员可见」「作业/通知全班共享」矛盾；
  - 「不向任何第三方共享或出售」（[data.wxml:121](../../mp-class-tools/pages/data/data.wxml#L121)）未提及腾讯云/微信云开发作为**受托处理方**；
  - 缺：处理者身份与联系方式、保存期限（除 token 约 30 天外）、用户权利行使路径（撤回同意/更正/删除/投诉）、未成年人条款、个人信息保护影响评估说明。
- **后台「隐私保护指引」**：README/CHANGELOG 称仅声明「学号 + 姓名（仅用于班级名单校验）」（[README.md:135](../../mp-class-tools/README.md#L135)、[CHANGELOG.md:172](../../mp-class-tools/CHANGELOG.md#L172)）——但实际调用了相册/相机/文件选择/写入相册/微信设置等隐私接口却未申报；代码中**无** `wx.requirePrivacyAuthorize` / `onNeedPrivacyAuthorization` / 自定义隐私弹窗，`app.json` 也**无** `__usePrivacyCheck__`（全文检索无命中；[app.json:1-62](../../mp-class-tools/app.json#L1-L62)）。→ 真机上隐私接口可能报 `errno 112`/审核要求整改（**待确认**，需在真机与后台核对）。
- **同意时机**：验证身份（即开始处理学号+姓名）前无任何同意步骤；第一次录入体测健康数据前**无单独同意**（体测属敏感个人信息）。

### 4.3 必备条款对照表（《个人信息保护法》第 17/30 条口径）

| 必备要素 | H5 | 小程序 | 说明 |
|---|---|---|---|
| 处理者身份 + 联系方式 | ❌ | ❌ | 仅能通过「反馈」间接联系管理员 |
| 处理目的、方式 | ⚠️ 极简 | ⚠️ 部分 | 缺「同步/统计/提醒/群消息转通知」的完整说明 |
| 个人信息种类 | ❌ | ⚠️ 不全 | 缺学号、名单缓存、通知内容/群消息、openid、设备号 |
| 保存期限 | ❌ | ❌ | 仅 token 30 天，其余无期限 |
| 第三方共享/委托处理 | ❌ | ⚠️ 笼统 | 未列腾讯云、微信云开发、DeepSeek（采集侧） |
| 用户权利（查询/复制/更正/删除/撤回） | ❌ | ⚠️ 部分 | mp 可导出/清云端/清本机；无更正、无撤回同意、无删除访问统计/反馈 |
| 未成年人保护 | ❌ | ❌ | 班内可能有未满 18 岁同学（2008 年出生，2026 级） |
| 敏感个人信息单独同意 | ❌ | ❌ | 体测健康数据、人群标签（团员/献血等） |
| 同意取得（收集前） | ❌ | ❌ | 身份页即开始收集 |
| 隐私政策入口 | ❌ | ❌ | 仅有页面内说明卡片 |
| 用户协议/服务规则 | ❌ | ❌ | 无 |
| 备案号/主体信息展示 | ❌ | 小程序备案号未取得 | 见 §6 |

---

## 5. 第三方与网络审计

### 5.1 外部域名/服务清单

| 域名 / 服务 | 提供方 | 用途 | 传输的个人信息 | 地域 | 是否有数据处理协议/告知 |
|---|---|---|---|---|---|
| `tool-d4gosudok46e0e081.api.tcloudbasegateway.com` | 腾讯云 CloudBase（ap-shanghai） | 身份 RPC + 全部班级数据 | 学号/姓名/token/作业/通知/体测/访问/反馈/群消息 JSON | 境内（上海） | ❌ 仅平台协议，无用户告知 |
| `tool.furina.fun`（`oss-cn-hongkong`） | 阿里云 OSS 香港 | H5 静态托管 + `tt.json` | 公开 HTML（含 2 个真实学号）；课表（教师姓名/教室） | **香港（境外）** | ❌ |
| `tool.furina.fun`（小程序 request 域名） | 同上 | `tt.json` 课表只读 | 无身份 token（[cloud.js:1368-1376](../../mp-class-tools/utils/cloud.js#L1368-L1376)） | 香港 | 需 ICP 备案（见 §6.4） |
| `fengdan-d6g7hnk4gf35685b3`（微信云开发） | 腾讯（微信） | 订阅消息云函数 + `subscriptions` 集合 | openid/提醒摘要/时间 | 待确认 | ❌ |
| 微信订阅消息 `subscribeMessage.send` | 腾讯（微信） | 发提醒 | openid/摘要 | 境内 | 平台能力，需隐私指引声明 |
| `api.deepseek.com` | 深度求索 | 群消息/OCR 文本 → 通知识别/摘要 | 群消息原文（含发送人姓名、可能含手机号/名单） | 境内 | **无脱敏、无告知、无委托协议**（[ai_triage.py:315-341](C:/briefdesk/scripts/ai_triage.py#L315-L341)、[cloud_ai.py:74-112](C:/briefdesk/scripts/cloud_ai.py#L74-L112)、[CLOUD_AI.md:90-95](C:/briefdesk/scripts/CLOUD_AI.md#L90-L95)） |
| `q.qlogo.cn` / `q1.qlogo.cn` | 腾讯 QQ 头像 | 下载群成员头像用于身份匹配 | QQ 号/头像 | 境内 | 本机缓存，未告知成员（[build_identity_map.py:172-186](C:/briefdesk/scripts/build_identity_map.py#L172-L186)） |
| `me.furina.fun` | 阿里云 OSS（另一 Bucket） | 已弃用的另一站点 + 微信域名校验文件 | — | 香港 | 不属本项目；`tools/README` 中二维码仍指向它（历史遗留） |
| 通知内嵌外链：`docs.qq.com`、`mp.weixin.qq.com`、`fjtcm.benke.chaoxing.com`、`e.fjtcm.edu.cn`、`jwc.fjtcm.edu.cn`、`m.q.qq.com`、`icourse163.org` | 各内容方 | 通知中展示的报名表/课程链接 | 用户点击后才跳转，站点本身不自动请求 | 境内 | 建议加外链提示 |
| Let's Encrypt ACME | ISRG（境外） | 证书签发 | 域名/运营者邮箱 | 境外 | 非业务数据 |

**前端静态资源**：H5 除 CloudBase 网关外**零外部请求**（全文仅 1 个外部 URL，[index.html:1235](../tools/index.html#L1235)；`tt.json` 为同源请求），无 CDN/字体/统计 SDK，符合 AGENTS.md 红线；小程序除 CloudBase + `tool.furina.fun` 外也无其他网络域名（grep 仅 [cloud-config.js:23](../../mp-class-tools/utils/cloud-config.js#L23)、[37](../../mp-class-tools/utils/cloud-config.js#L37)）。

### 5.2 CORS / 传输 / 加密

- CORS 白名单精确到 `https://tool.furina.fun`，自定义头仅放行 `X-Device-Id`（实测 204/403，§0），**配置正确**。
- **未强制 HTTPS**：`http://tool.furina.fun/` 返回 200（无 301/HSTS），token 与班级数据可走明文 HTTP；OSS 香港未配置强制跳转（证据见 §0 实测）。
- 证书：Let's Encrypt（DNS-01，[setup_tool_site.py:121-172](deploy/setup_tool_site.py#L121-L172)），证书绑定 OSS 自定义域名（[setup_tool_site.py:190-199](deploy/setup_tool_site.py#L190-L199)）；90 天**手动续期**（`tools\README.md:78`：重跑脚本），但本机 `health_beat.py` 有 TLS 剩余天数监控（[health_beat.py:608-635](C:/briefdesk/scripts/health_beat.py#L608-L635)，>21 天 ok / ≤7 天 down），并写 `service_health` 供管理员查看。
- **数据出境判断**：业务数据在境内（上海）；`tt.json` 无个人信息；但 **H5 公开 HTML 含 2 个真实学号且托管在香港** → 构成「个人信息在境外可公开获取」的事实（虽仅 2 条，仍需删除）；微信云开发 env 地域待确认（§11）。除此外未发现业务数据出境。

---

## 6. 小程序侧审计

| 项 | 现状 | 证据 |
|---|---|---|
| AppID / 主体 | `wx3df9869d229b96c4`，个人主体（未认证企业） | [project.config.json:2](../../mp-class-tools/project.config.json#L2)、[60](../../mp-class-tools/project.config.json#L60)；[README.md:1](../../mp-class-tools/README.md#L1) |
| 发布状态 | **未上传/未发布**（v2.0.0 源码完成，交付说明称上传发布由 Lead 执行但未见记录） | [README.md:138](../../mp-class-tools/README.md#L138)；memory 2026-11-05「小程序需手动上传+审核发布」 |
| 页面 | 18 页原生（identity/index/draw/tt/me/data/group/sum/hw/nt/ft/fttable/fb/ug/all/roll/committee/stats） | [app.json:2-21](../../mp-class-tools/app.json#L2-L21) |
| 类目线索 | 仓库无类目记录；功能属「工具/效率 + 班级事务」；如选教育类类目个人主体大概率受限（待确认，见 task-1 研究） | — |
| `wx.requestSubscribeMessage` | 使用（作业截止/下一条通知/单条提醒），授权在用户点击链内，云函数发送 | [notify.js:7-45](../../mp-class-tools/utils/notify.js#L7-L45)；[cloudfunctions/notify/index.js:1-80](../../mp-class-tools/cloudfunctions/notify/index.js#L1-L80) |
| 隐私接口 | `wx.chooseMedia`（相册/相机）、`wx.chooseMessageFile`、`wx.saveImageToPhotosAlbum`、`wx.getSetting/openSetting`；**无** getUserProfile/getLocation/getUserInfo/getClipboard 读取 | [hw.js:365-392](../../mp-class-tools/pages/hw/hw.js#L365-L392)；[canvas.js:519-549](../../mp-class-tools/utils/canvas.js#L519-L549) |
| 隐私授权适配 | 无 `requirePrivacyAuthorize`/`onNeedPrivacyAuthorization`/`__usePrivacyCheck__`（全文检索 0 命中） | app.json / 源码 grep |
| 服务器域名 | 后台需配 `tool-d4gosudok46e0e081.api.tcloudbasegateway.com` + `tool.furina.fun`；README 明示「域名需 ICP 备案（国内主体）」 | [README.md:294-304](../../mp-class-tools/README.md#L294-L304) |
| `urlCheck` | 开发期 `false`，上传前需按后台域名确认 | [project.config.json:18](../../mp-class-tools/project.config.json#L18)；[README.md:137](../../mp-class-tools/README.md#L137) |
| 包体是否含真实名单 | **源码页面/组件未内嵌**（grep「3260707」0 命中、班级姓名 0 命中）；但仓库文档含真实学号/姓名：`README.md:528`（`32607070**`）、`README.md:578`（红会群仅某某）、`CHANGELOG.md:607`（班委实名列表）；`packOptions.ignore` 只排除 `ai`/`agent`，**未排除 `*.md`** | [project.config.json:4-16](../../mp-class-tools/project.config.json#L4-L16)；[README.md:528](../../mp-class-tools/README.md#L528)；[CHANGELOG.md:607](../../mp-class-tools/CHANGELOG.md#L607) |
| 包体大小 | 发版（AI 关闭）编译 TOTAL 532,652 B / 主包约 53 万 B；媒体 108 KB（<200 KB 规则） | [README.md:150-158](../../mp-class-tools/README.md#L150-L158)；[`_v2_compile_info.json`](../../mp-class-tools-tests/_v2_compile_info.json) |
| AI 开发模式 | 发版默认关闭（`ai/` 独立分包 + `packOptions.ignore`）；若开启，AI 原子接口可读身份与班级数据（需重新评估隐私） | [README.md:113](../../mp-class-tools/README.md#L113)、[127-132](../../mp-class-tools/README.md#L127-L132)；[AI README:735-743](../../mp-class-tools/README.md#L735-L743) |
| 多端框架配置 | `project.miniapp.json` 含 iOS/Android/鸿蒙多端配置（`privacy.enable=false`、vConsole open）；未见打包产物 | [project.miniapp.json:1-68](../../mp-class-tools/project.miniapp.json#L1-L68) |
| 缓存/退出 | 退出身份清空全部缓存（含通知分块）——**比 H5 做得好** | [identity.js:63-67](../../mp-class-tools/utils/identity.js#L63-L67)；[cache.js:1-27](../../mp-class-tools/utils/cache.js#L1-L27) |

**关于「真实名单/学号进包体」**：按编译包体积（532,652 B）与「代码+媒体」估算（代码 697,437 B 未压缩、媒体 108,978 B、文档 161,153 B），532 KB 与「代码压缩后 + 媒体」吻合，**文档很可能未进编译包**；但 `packOptions.ignore` 未排除 `*.md`，而生产上传模式默认不做无依赖文件过滤（`CODE_QUALITY_NOTES` E 条：上传用 `ignoreUploadUnusedFiles`，本项目未设置 → 默认不过滤），故**仍需上传后核对代码包文件清单**（待确认）。无论如何，仓库文档不应保留真实学号/姓名。

---

## 7. 内容与运营审计

### 7.1 群聊消息抓取与二次分发（最核心风险）

- **数据来源**：本机 QQ NT 本地库（qqflow，只读）与微信本地库（weflow，用 `wcdb-key-tool` 提取 22 个库密钥后只读解密），均为**非官方接口**（[README-下一步.md:155-170](C:/briefdesk/README-下一步.md#L155-L170)；[ai_triage.py:26-29](C:/briefdesk/scripts/ai_triage.py#L26-L29)）。
- **采集范围**：班级/课程/新生/专项群（含「2026级管院新生群」「26级周一89节太极拳」「红会」「运动会志愿者/观众」等），个人私聊仅「文件传输助手」；群接龙被过滤（[ai_triage.py:44-56](C:/briefdesk/scripts/ai_triage.py#L44-L56)、[197-202](C:/briefdesk/scripts/ai_triage.py#L197-L202)）。
- **写入云端**：`sync_notices_cloud.py` 把本地 `board-data.json` 的分组原样写入 `public.notices.body`（保留 `senderName/senderRole/senderBadge/ocr/items` 等字段，[sync_notices_cloud.py:86-96](C:/briefdesk/scripts/sync_notices_cloud.py#L86-L96)、[111-126](C:/briefdesk/scripts/sync_notices_cloud.py#L111-L126)），audience 由群名映射（all/committee/league/set:*，[sync_notices_cloud.py:57-83](C:/briefdesk/scripts/sync_notices_cloud.py#L57-L83)）。
- **前端展示**：H5 通知 iframe 模板显示 `senderName`（发送人姓名+职务）与每条 `items.from/fromName`（[模板解码证据：`pubLine`/`itemHTML`，内嵌于 index.html:1410](../tools/index.html#L1410)）；小程序通知页同样显示 `card.senderName`（[nt.wxml:19-23](../../mp-class-tools/pages/nt/nt.wxml#L19-L23)）。
- **审计时数据事实**（`C:\briefdesk\data\board-data.json` 22:39 快照，45 组自动通知）：
  - **39 组含发送人姓名**（`senderName`）；
  - **11 组原文含 11 位手机号**（来自 QQ 群名片，如「64姓名1**********」），这 11 组 **audience 全部为 `all`（全班可见）**；
  - **5 组含 OCR 识别文本**，内容为运动会参赛/观赛名单、班级课程表等（含**大量同学姓名与教职工姓名**），audience 均为 `all`；
  - **14 个条目内嵌 base64 图片**（合计约 **1.58 MB/次**），整包 payload 约 **2.43 MB/次**（每条通知单行最大约 40 万字节）。
  - 手机号/名单在「发送前」**没有脱敏/过滤**（`sync_notices_cloud.py` 无清洗逻辑；`classify/ocr` 仅本地 OCR 不改原文）。
- **同意链**：群成员（数据主体）从未被告知/同意其群名片、发言、图片被转成班级站通知；且部分内容来自**非本班群**（新生群、课程群、红会群），二次分发到本班站点，超出原群范围。
- **平台规则**：非官方客户端/本地库解密/自动抓取群聊，违反 QQ/微信用户协议与平台运营规范；同时可能触及《网络安全法》第 27 条（不得非法获取数据）与《个人信息保护法》告知同意规则 → 对「合规 App」是**阻断级**风险。
- **正面**：OCR 在本机离线完成（[ocr_qq_images.py:9-10](C:/briefdesk/scripts/ocr_qq_images.py#L9-L10)，RapidOCR，无外部网络）；AI 链路仅发送**文本**（不发送图片原始数据，[classify_qq_images.py:99-109](C:/briefdesk/scripts/classify_qq_images.py#L99-L109)）；AI 摘要在前端有「AI 摘要」标签（H5 模板、[nt.wxml:31-38](../../mp-class-tools/pages/nt/nt.wxml#L31-L38)），深度合成标识基本到位。

### 7.2 通知可见范围（audience）

- 值：`all` / `committee` / `league` / `admin` / `sid:<学号>` / `set:<人群>`（[CLOUDBASE.md:367-410](CLOUDBASE.md#L367-L410)、[audience_sets.sql:36-49](C:/briefdesk/scripts/sql/audience_sets.sql#L36-L49)、[league_audience.sql:41-52](C:/briefdesk/scripts/sql/league_audience.sql#L41-L52)）。
- 服务端 RLS 按 token 身份过滤（文档称已验证 19/18/18/0，[CLOUDBASE.md:403-409](CLOUDBASE.md#L403-L409)）；写权限收紧为仅管理员（[CLOUDBASE.md:401](CLOUDBASE.md#L401)）。
- 风险：`all` 比例高（审计时 37/45），且 `all` 内容含上述手机号/名单；`set:*`/`league` 名单来自群成员身份（**敏感标签**，见 §9.4）。

### 7.3 访问统计与反馈

- **visits**：H5 每小时一条 `{id:sid|slot|rand, slot, sid, name, did, ts}`（[index.html:5239-5247](../tools/index.html#L5239-L5247)）；小程序每小时一条（[cloud.js:1345-1356](../../mp-class-tools/utils/cloud.js#L1345-L1356)）。管理员可读全部（[index.html:5249-5257](../tools/index.html#L5249-L5257)），页面按姓名聚合、不显示学号（[index.html:5273+](../tools/index.html#L5273)）；但 DB 内保留 sid+name+did+小时级时间 = 可还原个人使用行为，且**无保留期限、无法删除**。
- **feedback**：H5 收集内容+**联系方式（QQ/微信）**+acc（[index.html:1031](../tools/index.html#L1031)、[3054-3058](../tools/index.html#L3054-L3058)）；管理员列表显示姓名映射与联系方式（[index.html:3060-3070](../tools/index.html#L3060-L3070)）。小程序 1.5.2 起已停止收集联系方式（[fb.js:3](../../mp-class-tools/pages/fb/fb.js#L3)）→ 两端不一致，H5 应同步下线该字段。

### 7.4 导出图片

- 统一 `exportCard()`：斜向平铺水印 `tool.furina.fun`、参数配置区、页脚生成时间、唯一编号（[index.html:3240-3249](../tools/index.html#L3240-L3249)、[3487-3500](../tools/index.html#L3487-L3500)、[3651](../tools/index.html#L3651)）；命名 `<类型>_<YYYYMMDD-HHMM>_<参数>.png`（[index.html:3131](../tools/index.html#L3131)）。
- **不含学号/手机号**（抽签 chips 用座号+姓名；体测图只有性别/年级/分数；作业图只有昵称）——符合 AGENTS.md 红线。
- 但会包含**同学姓名**（抽签/分组结果）与**体测健康数据**（身高/体重/BMI/肺活量等，[index.html:4990-5016](../tools/index.html#L4990-L5016)），图片被转发即扩散；导出前无提示「含他人姓名/健康信息」。

---

## 8. 安全与运维审计

### 8.1 前端密钥

- H5 仅含 **publishable key**（设计上公开，[CLOUDBASE.md:122-131](CLOUDBASE.md#L122-L131)、[index.html:1236](../tools/index.html#L1236)）+ CloudBase URL，无任何 `sk-`/secret/appsecret（grep 无命中）。
- 小程序 `cloud-config.js` 同样只含 publishable key（[cloud-config.js:1-26](../../mp-class-tools/utils/cloud-config.js#L1-L26)）；无 appsecret/service_role（grep 无命中）。
- 这是一个**正面项**：前端无高权限密钥，权限完全依赖 RLS + token。

### 8.2 本机密钥与敏感数据（高风险）

- `C:\briefdesk\secrets\` 明文存放：DeepSeek API key（`cloud-ai.json`）、管理员班级 token（`class-token.json`，25 天有效）、qqflow/weflow 的 API key 与 token、**微信 22 个数据库密钥（`weflow-keys.json`，可解密本机全部微信聊天记录）**、ECS 私钥与疑似 root 口令文本（`ecs-root.txt`）等；README 称目录 ACL 已收紧为仅当前用户（[README-下一步.md:39](C:/briefdesk/README-下一步.md#L39)），但仍为**明文**且高度集中。
- `web\deploy\creds.env`、`tools\cert\`、`deploy\acme_account_key.pem`、`jwxt\creds.dpapi` 属机密文件，本次未读取（遵守红线）；其中教务系统账号密码使用 DPAPI 本机保存（[HANDOFF.md:185](HANDOFF.md#L185)），相对规范。
- 风险：本机或备份泄露 → 微信/QQ 全量聊天记录 + 班级云数据（管理员 token）+ DeepSeek 账户全失守；且无轮换记录。

### 8.3 RLS / DDL 完整性与「仓库漂移」（高风险）

- 仓库内 SQL 与线上实际不一致，**无法离线复现/审计**：
  - [schema.sql:39-41](deploy/cloudbase/schema.sql#L39-L41) 仍是 `hw_read/hw_insert/hw_update … using(true)`；[66-72](deploy/cloudbase/schema.sql#L66-L72) `nt_read/insert/update using(true)`——若误执行会把已收紧的权限**打回公开**；
  - [security_hardening.sql:22-29](deploy/cloudbase/security_hardening.sql#L22-L29) 的 `auth_ok()` 仍查 `public.users`（该表已删除，实测 404）→ 该文件已过时，不能作为现行定义；
  - 线上现行的 `class_verify`、`private.class_sessions`、`auth_sid/auth_is_admin/auth_is_committee`、`homework` 现行 RLS 等**均未入库**（全仓库 grep 无 `create function public.class_verify` / `class_sessions` DDL）；
  - [identity_schema.sql:1-50](../../mp-class-tools-tests/identity_schema.sql#L1-L50) 是 2026-10-19 的旧身份设计（`identity_verify` + 账号密码），与现方案冲突，仍留在仓库。
- 后果：① 新环境无法重建；② 误跑旧 SQL 会破坏权限；③ 审计/备案/整改缺少可核验的权威 schema；④ 迁移无版本化记录（`deploy/cloudbase` 只有 4 个零散迁移）。
- 已确认的写策略遗留（文档自述，未实测）：`feedback` 的 INSERT 仍为 `auth_ok()`，任何已认证成员可写任意 `acc` 的行（[CLOUDBASE.md:518-521](CLOUDBASE.md#L518-L521)、[HANDOFF.md:668-669](HANDOFF.md#L668-L669)）；`homework` 的 UPDATE 旧策略为 `using(true) with check(true)`（[CLOUDBASE.md:210-217](CLOUDBASE.md#L210-L217)）——若未收紧，任何登录用户可改他人作业行（含 `owner` 冒充）；`visits`/`feedback` 的写策略在不同文档中口径冲突（[security_hardening.sql:103-106](deploy/cloudbase/security_hardening.sql#L103-L106) 说「保持 true」 vs [2026-11-04_visits_feedback_own_read.sql:13-14](deploy/cloudbase/2026-11-04_visits_feedback_own_read.sql#L13-L14) 说「写入策略不变（visits 仍只能写自己 sid）」）→ **待确认**。

### 8.4 日志与备份

- 采集侧日志：`health_beat.py` 明确「日志内容只有状态码/耗时/文案，无 token」（[health_beat.py:23](C:/briefdesk/scripts/health_beat.py#L23)）；`ai_triage` 日志只记数量/耗时；`watchdog` 日志只保留非敏感字段（[watchdog.py:250 附近](C:/briefdesk/scripts/watchdog.py#L250)）。**日志基本不含个人信息——正面。**
- 但本地 `C:\briefdesk\data\` 保存群聊原文/AI 结果/头像/图片，无加密、无访问日志、无保留期限（§2.5）。
- 云端备份/恢复：`CLOUDBASE.md`、`deploy/cloudbase/README.md` 未提及备份策略（CloudBase 个人版控制台可能有自动备份，**待确认**）；无数据恢复演练记录。
- 删除机制：云端 anon 无 DELETE；`visits/feedback/marks/userdata/fitrecs` 均无硬删除；管理员只能通过 `tcb db execute` CLI 手工删。**用户删除权实际不可行使**。

### 8.5 域名 / 备案 / HTTPS 现状

| 项 | 现状 | 证据 |
|---|---|---|
| 域名 | `furina.fun`（阿里云 DNS，`.fun` 后缀）；`tool` 子域 CNAME 到 OSS 香港 | [setup_tool_site.py:29-33](deploy/setup_tool_site.py#L29-L33)、[181-188](deploy/setup_tool_site.py#L181-L188) |
| ICP 备案 | **无**（页面无备案号；托管香港；HANDOFF 明确 `.fun` 极可能不可备案，[HANDOFF.md:223-230](HANDOFF.md#L223-L230)） | 线上 O 版 grep「ICP」0 命中 |
| HTTPS | 有 LE 证书，HTTPS 200；**未强制跳转**，HTTP 200 可访问 | §0 实测 |
| 小程序 request 域名 | `tool.furina.fun` 需 ICP 备案（[README.md:304](../../mp-class-tools/README.md#L304)）→ 未备案则正式版该请求被拦截（课表只能读本机缓存）；CloudBase 网关域名属腾讯备案，可用 | [README.md:294-304](../../mp-class-tools/README.md#L294-L304) |
| 公安联网备案 | 无 | — |
| 等保 | 未做（个人非经营性小站，是否适用待确认） | — |

---

## 9. 差距清单（分级）

> 工作量估算口径：0.1 人日 ≈ 1 小时；1 人日 ≈ 8 小时。法规名称为对应影响口径，具体适用性以 task-1 监管研究结论为准。

### 🛑 阻断上线（5）

| ID | 现状（证据） | 问题 | 影响 | 整改建议 | 工作量 |
|---|---|---|---|---|---|
| **B-1** | H5 无隐私政策/用户协议/同意勾选，身份页直接收集并上传学号+姓名（[index.html:721-730](../tools/index.html#L721-L730)）；小程序仅有页面内说明卡片、无同意（[identity.wxml:27-54](../../mp-class-tools/pages/identity/identity.wxml#L27-L54)） | 收集前未告知、未取得同意；处理者身份/联系方式/期限/权利/第三方共享均缺失 | 违反《个人信息保护法》第 13/14/17/30 条；小程序审核直接驳回；App 上架隐私合规必查项 | 编写《隐私政策》《用户协议》（H5 与小程序共用一份，列明处理者、目的、字段、期限、第三方受托方、用户权利、未成年人、联系方式）；H5 身份页加「我已阅读并同意」勾选 + 链接；小程序加隐私弹窗/`__usePrivacyCheck__` + 后台隐私指引；提供数据导出/删除入口 | 2–3 人日 |
| **B-2** | 通知内容来自 QQ/微信本地库自动抓取（非官方客户端）并写云端二次分发（§7.1；[sync_notices_cloud.py:86-96](C:/briefdesk/scripts/sync_notices_cloud.py#L86-L96)、[ai_triage.py:26-29](C:/briefdesk/scripts/ai_triage.py#L26-L29)）；含发送人姓名、11 位手机号、OCR 名单 | 数据主体（群成员）从未同意；跨群外传；平台协议与法律双重风险 | PIPL 违法处理；QQ/微信协议违规；若被举报/审核发现，站点/小程序/App 可被下架甚至追责 | ① 上线前**下线自动抓取管道**，改为「管理员人工转发 + 人工编辑」；② 若保留自动化，仅限本班群、去标识（去发送人/去手机号/去姓名）、不出本班、群内公告告知；③ 清理云端历史含手机号/OCR 名单的通知；④ 建立内容来源与授权台账 | 5–10 人日（重构）/ 1 人日（下线） |
| **B-3** | 无 ICP 备案；OSS 香港；小程序 request 域名 `tool.furina.fun` 无备案（§8.5） | 无网站备案号、无小程序备案号，域名不能作为小程序合法域名 | 无法满足「可备案 App」目标；小程序正式版课表请求被拦；App 上架需备案号 | 按 task-3 路线：小程序备案（先）+ 网站 ICP 备案（后）；`.fun` 视管局口径决定是否换 `.cn`/`.com`；小程序域名改为已备案域名或去掉 tt.json 跨域请求；首页/页脚悬挂备案号 | 1–2 人日准备 + 管局 3–6 周 |
| **B-4** | 云端仍有测试身份（学号 `326079****`，[2026-11-05_test_account.sql:41-46](deploy/cloudbase/2026-11-05_test_account.sql#L41-L46)），凭据写在交付说明（[CLOUDBASE.md:583-584](CLOUDBASE.md#L583-L584)） | 测试账号可进入 `audience=all` 全班数据；凭据随交付文档扩散 | 未授权访问；审核资料泄露即数据泄露 | 上线/提审前执行清理 SQL（删 class_sessions + class_ids 测试行）；删除交付说明中的凭据或改为人工重置的口令 | 0.1 人日 |
| **B-5** | 小程序后台隐私指引仅称「学号+姓名」（[README.md:135](../../mp-class-tools/README.md#L135)），但实际使用相册/相机/文件/写入相册（[hw.js:365-392](../../mp-class-tools/pages/hw/hw.js#L365-L392)、[canvas.js:519-531](../../mp-class-tools/utils/canvas.js#L519-L531)）；代码无隐私授权适配 | 隐私接口未声明，真机可能 `errno 112`；审核要求整改 | 小程序审核不通过/线上接口失败 | 后台「用户隐私保护指引」逐项勾选：相册（仅写入）、摄像头、选中的照片/视频、选中的文件；代码加 `wx.requirePrivacyAuthorize` 或启用微信默认隐私弹窗；真机回归 chooseMedia/chooseMessageFile/saveImageToPhotosAlbum | 0.5–1 人日 |

### 🔴 高风险（12）

| ID | 现状（证据） | 问题 | 影响 | 整改建议 | 工作量 |
|---|---|---|---|---|---|
| **H-1** | 45 组自动通知中 39 组含发送人姓名、11 组含 11 位手机号（audience 均 `all`）、5 组含 OCR 名单（含同学/教职工姓名）、14 个内嵌图片（约 1.58 MB）（§7.1） | 未脱敏的第三方个人信息对全班可见，且永久存云端 | PIPL 敏感信息/第三方信息违规；举报/审核风险 | 上传前加脱敏层：手机号/身份证/学号正则掩码、`from/fromName` 去人名或只留「班委」角色、图片 OCR 文本去名单；清理历史行；前端默认不展示 `from` 实名 | 1–2 人日（含重同步） |
| **H-2** | H5 无数据管理页；退出身份不清主数据桶（[cacheKill:2509-2525](../tools/index.html#L2509-L2525)，未删 `zq_tools_v2_<sid>`）；说明却称「可退出身份清除本机数据」（[index.html:1070](../tools/index.html#L1070)） | 共用手机残留 70 人名单（含学号）、点名到·假、体测记录、通知缓存；无导出/更正/删除 | 违反最小必要/存储期限/删除权；串号泄露 | 退出时删除 `zq_tools_v2_<sid>` 及全部 `zq_*_<sid>`/IndexedDB；新增「数据与隐私」页（对齐小程序：导出/清除云端/清除本机）；修正文案 | 1–1.5 人日 |
| **H-3** | 云端 `visits/feedback/marks/userdata/fitrecs` 均无 DELETE 策略；`notices/homework` 仅软删；无保留期限/清理任务（§2.4、§8.4） | 数据「只进不出」，用户删除权不可行使；永久保留 | 违反 PIPL 第 19/47 条；被举报/审计风险 | 增加本人/管理员删除 RPC（SECURITY DEFINER）：visits/feedback 可删、marks/userdata/fitrecs 可物理删；设定保留期（建议 visits 90 天、feedback 1 年、通知 6 个月后归档清理）并加定时清理；小程序/ H5 提供入口 | 2–3 人日 |
| **H-4** | `class_members` 向全体成员下发 70 人学号（[CLOUDBASE.md:42-52](CLOUDBASE.md#L42-L52)）；`visits` 存 sid+name+did+小时级时间；H5 反馈收集 QQ/微信（[index.html:1031](../tools/index.html#L1031)） | 超出功能必需（抽签/点名只需座号+姓名） | 最小必要原则违规；行为画像/联系方式泄露风险 | `class_members` 去掉 `sid`（管理员另开管理接口）；visits 改匿名/聚合（不存 name，sid 哈希或只存班内随机 ID）；H5 反馈去联系方式字段 | 1–2 人日 |
| **H-5** | 学号+姓名即凭证、无第二因子/限流/撤销；token 30 天明文；token 失效不回门禁（§3.2） | 冒用、枚举、长期泄露风险 | 未授权访问全班数据；PIPL 安全措施不足（第 51 条） | class_verify 加失败限流/延迟/告警；token 增加设备指纹或短 TTL+刷新；服务端 401 时前端回门禁；提供管理员「踢下线」；token 改存 sessionStorage 或加密 | 1.5–2 人日（含云端 RPC 改造） |
| **H-6** | H5 公开文件含 2 个真实学号（线上 O 版 [_backup:2852-2853](../tools/_backup/index_online_20261105-2215_preFlickerFix.html#L2852-L2853)；工作副本 [index.html:2849-2850](../tools/index.html#L2849-L2850)） | 学号随公开 HTML 全球可下载；且托管香港 | 个人信息公开泄露；管理员身份暴露 | 删除 legacy 迁移硬编码，改为「当前账号」通用逻辑；重新部署；保留旧数据的迁移改由服务端完成 | 0.2 人日 |
| **H-7** | 本机 `C:\briefdesk\secrets` 明文集中：DeepSeek key、管理员 token、qqflow/weflow key、22 个微信库密钥、ECS 私钥（§8.2） | 单点泄露即全量聊天记录+云数据+服务器 | 大规模个人信息泄露/入侵 | 全部迁 DPAPI/Windows 凭据管理器；目录 ACL + 磁盘加密；定期轮换（微信库密钥按需再取）；禁止 `ecs-root.txt` 明文；最小权限 | 1 人日 |
| **H-8** | RLS/DDL 仓库漂移，旧 SQL 可破坏现网权限（§8.3） | 无法审计/复现/重建；误操作风险 | 权限失控→数据泄露或功能全坏 | 从现网导出权威 schema（`pg_policies`/`pg_proc`/`pg_tables`）入库；清理/标注废弃 SQL；建立迁移目录与顺序说明；CI 校验 | 1–1.5 人日 |
| **H-9** | 非官方 QQ/微信客户端读取本地库（qqflow/weflow + wcdb-key 解密）（§7.1；[README-下一步.md:155-170](C:/briefdesk/README-下一步.md#L155-L170)） | 违反平台协议；技术手段游走法律边缘 | 平台封号/下架/举报风险；个人责任 | 与 B-2 同批整改：停用自动抓取，改用官方机器人/人工转发；删除本地库解密工具链；如保留仅作本机个人助理、不对外提供 | 3–5 人日（与 B-2 合并） |
| **H-10** | HTTP 明文可访问（§0 实测）；无 HSTS | token/数据可被中间人截获/篡改 | 违反《网络安全法》21 条安全保护义务；PIPL 安全措施 | OSS 自定义域名开启强制 HTTPS 跳转（301）+ HSTS；证书续期自动化（acme.sh/certbot 定时）；补充 CSP/安全头 | 0.5 人日 |
| **H-11** | 作业/通知/反馈/附件为用户自由输入，无内容安全审核（小程序无 `msgSecCheck`；H5 无） | UGC 违规内容风险；审核/上架不通过 | 微信平台内容安全要求；App 商店 UGC 条款；下架风险 | 小程序接入 `security.msgSecCheck`/`mediaCheckAsync`（云函数或云调用）；H5 加敏感词过滤；附件图片审核或限制 | 1–2 人日 |
| **H-12** | 群消息原文/OCR 文本发往 DeepSeek，无脱敏、无告知、无委托处理协议（[ai_triage.py:315-341](C:/briefdesk/scripts/ai_triage.py#L315-L341)、[cloud_ai.py:74-112](C:/briefdesk/scripts/cloud_ai.py#L74-L112)） | 委托处理未告知；含手机号/姓名外发 | PIPL 第 21 条（委托处理协议）、第 17 条（告知）；第三方泄露 | 发送前正则脱敏（手机号/学号/身份证）；与 DeepSeek 签订数据处理条款或用「不用于训练」的付费 API；在隐私政策披露；或仅用本地模型 | 0.5–1 人日 |

### 🟠 中风险（11）

| ID | 现状（证据） | 问题 | 影响 | 整改建议 | 工作量 |
|---|---|---|---|---|---|
| **M-1** | 云端 `private.class_league`（团员=政治面貌）50 人、`private.class_audience`（无偿献血/评议/舍长/红会）来自群成员身份（[CLOUDBASE.md:426-464](CLOUDBASE.md#L426-L464)、[sync_audience_rosters.py:1-13](C:/briefdesk/scripts/sync_audience_rosters.py#L1-L13)） | 敏感个人信息（特定身份/健康相关推断）无单独同意、无必要性论证 | PIPL 第 28-29 条（单独同意、告知必要性） | 评估必要性；去标识（只存 sid 或不可逆映射）；单独告知+同意；限制使用范围；不展示 | 1 人日 |
| **M-2** | 无未成年人识别/声明；同学出生年约 2008（部分未满 18） | 《未成年人网络保护条例》要求专门保护；<14 需监护人同意（本班基本不涉及，但需声明） | 合规瑕疵；投诉风险 | 隐私政策加未成年人条款；身份页声明「未满 18 岁需监护人同意」；敏感数据默认关闭 | 0.2 人日 |
| **M-3** | 作业附件/通知图片以 base64 存云（[schema.sql:24](deploy/cloudbase/schema.sql#L24)、[sync_notices_cloud.py:91-95](C:/briefdesk/scripts/sync_notices_cloud.py#L91-L95)） | 图片可能含证件/名单/照片；云 DB 单行数 10 万字节级 | 泄露面扩大；存储成本 | 附件改对象存储（私有桶+短签名 URL）+ 压缩；上传前提示「可能含他人信息」；保留期 | 1–2 人日 |
| **M-4** | 披露文案多处不准确（§4.1、§4.2） | 告知不实 = 未有效告知 | PIPL 告知义务 | 逐条修订文案，与实现一致（尤其是相册、云端可读范围、用途） | 0.3 人日 |
| **M-5** | 数据权利能力两端不一致：mp 有导出/清除，H5 无；mp 未发布 → 实际用户（H5 为主）无法行使权利 | 用户权利落空 | PIPL 第 45/47 条 | H5 增加同款「数据与隐私」页（连同一套 RPC） | 1 人日（与 H-2 合并） |
| **M-6** | 导出图含体测健康数据/同学姓名，无提示（[index.html:4990-5016](../tools/index.html#L4990-L5016)） | 用户分享即泄露（含敏感信息） | PIPL 敏感信息二次传播 | 导出前提示「图片包含健康数据/他人姓名，请谨慎分享」；体测图默认隐藏身高体重（可选） | 0.2 人日 |
| **M-7** | 无个人信息保护影响评估（PIA）记录、无数据处理台账、无数据安全事件应急预案 | PIPL 第 51/55/56 条要求（处理敏感信息应事前 PIA 并记录） | 监管检查/整改无依据 | 建立三份文档：个人信息清单+处理记录、PIA、安全事件应急预案；指定负责人 | 1 人日 |
| **M-8** | 数据地域/备份待确认：CloudBase ap-shanghai ✔；微信云开发 env `fengdan-d6g7hnk4gf35685b3` 归属/地域未知（[app.js:82](../../mp-class-tools/app.js#L82)）；OSS 香港静态含 2 学号（已在 H-6） | 出境/备份策略不明 | PIPL 跨境/等保口径 | 控制台确认 env 归属与地域；确认 CloudBase 备份策略与恢复演练；H-6 修复后消除境外个人信息 | 0.3 人日 |
| **M-9** | 通知归档/过期数据无清理：`archived=true` 行永久保留；无保留期限；本地 `board-data.json` 永久增长 | 存储期限不明确 | PIPL 第 19 条 | 建立保留策略 + 定时清理（管理员脚本 + 云端 SQL），在隐私政策写明 | 0.5 人日 |
| **M-10** | 通知含大量外部链接（docs.qq.com/学习通/慕课等）用户点击即离开站点 | 外链风险/钓鱼 | 建议加外链提示与域名白名单；外链不自动加载 | 0.2 人日 |
| **M-11** | 若启用多端框架原生打包（`project.miniapp.json` 含 iOS/Android/鸿蒙配置，iOS `privacy.enable=false`） | 原生打包另需隐私配置/权限声明 | 若未来走原生 App，需重新评估 | 发版前复核该配置；不启用则从包中排除 | 0.2 人日 |

### 🟡 低风险 / 正面项（9）

| ID | 现状 | 评价 |
|---|---|---|
| L-1 | 课表 `tt.json` 公网可读，含教师姓名/教室（[tt.json](tools/tt.json)、OSS 公开） | 低：公开课程信息；但建议确认教师姓名展示是否需模糊处理 |
| L-2 | 文档过期/不一致：`tools/README.md` 仍写旧尺寸/旧登录方式；`CLOUDBASE.md` 称「token 失效回门禁」与实现不符 | 低：维护风险；建议随整改更新 |
| L-3 | 云端 `service_health` 表与采集心跳仍在（诊断页当前工作副本有、线上 O 版无）；仅管理员可读，内容为主机 pid/uptime/消息数（[health_beat.py:646-735](C:/briefdesk/scripts/health_beat.py#L646-L735)） | 低：非个人信息；建议保留则纳入隐私政策「运维日志」说明 |
| L-4 | 安全正面：CORS 精确白名单（实测 403/204）；匿名 SELECT 均 `[]`；前端无密钥；零外链/SDK；小程序无 web-view/定位/通讯录接口 | ✅ 正面 |
| L-5 | 安全正面：导出图不含学号/手机号，带水印+编号（[index.html:3240-3249](../tools/index.html#L3240-L3249)） | ✅ 正面 |
| L-6 | 安全正面：本地 OCR 离线；AI 摘要前端有「AI 摘要」标识（H5 模板、[nt.wxml:31-38](../../mp-class-tools/pages/nt/nt.wxml#L31-L38)） | ✅ 正面（深度合成标识） |
| L-7 | 安全正面：小程序退出身份清全缓存（[identity.js:63-67](../../mp-class-tools/utils/identity.js#L63-L67)）；`sitemap.json` 全站 disallow（[sitemap.json:1-9](../../mp-class-tools/sitemap.json#L1-L9)） | ✅ 正面 |
| L-8 | 安全正面：TLS 证书剩余天数监控（[health_beat.py:608-635](C:/briefdesk/scripts/health_beat.py#L608-L635)） | ✅ 正面（续期仍手动） |
| L-9 | 通知 iframe 模板对文本做 `esc()` 转义、无外部脚本/外链资源（本报告已解码核验） | ✅ 正面（XSS 基础防护） |

---

## 10. 待确认清单（附只读核查方法）

| # | 待确认项 | 建议核查（只读） |
|---|---|---|
| Q-1 | 云端现行 RLS 策略（尤其 `hw_read/hw_insert/hw_update`、`nt_read/insert/update`、`vs_insert`、`fb_insert`、`mk_*`、`ud_*`） | `tcb db execute -e tool-d4gosudok46e0e081 --sql "select schemaname,tablename,policyname,cmd,qual,with_check from pg_policies where schemaname='public' order by 1,2"`（只读），与仓库 SQL 对比 |
| Q-2 | `class_verify` / `private.class_sessions` 实现：token 生成、TTL、限流、清理、能否吊销 | `select proname, pg_get_functiondef(oid) from pg_proc where proname like 'class_%' or proname in ('auth_ok','auth_sid','auth_admin')` |
| Q-3 | 云端 `notices` 实际是否含手机号/OCR 名单（及条数） | 管理员 token 只读统计：`select count(*) from public.notices where body ~ '[0-9]{11}'`、`select count(*) from public.notices where body ilike '%ocr%'`；**无需导出正文** |
| Q-4 | 微信云开发 env `fengdan-d6g7hnk4gf35685b3` 归属与地域、`subscriptions` 集合权限/保留 | 微信开发者工具 → 云开发控制台（只读查看） |
| Q-5 | 小程序后台「用户隐私保护指引」实际声明项、服务类目、request 合法域名是否已配置 | 微信公众平台 → 设置 → 服务内容声明/隐私保护指引/开发设置（截图存档） |
| Q-6 | 上传包是否包含 `README.md`/`CHANGELOG.md`（含真实学号/姓名） | 上传体验版/正式版后，在后台「代码包大小/文件列表」核对；或 `packOptions.ignore` 加 `*.md` 后对比包体积 |
| Q-7 | H5 线上/本地版本差异与后续发布节奏（审计期间被并发改写 3 次） | `sha256` 对比线上与本地；冻结发布版本 |
| Q-8 | 域名注册商/实名/`.fun` 可备案性；网站名称是否触发教育前置审批 | 阿里云控制台 + 福建省通信管理局备案系统（task-1 研究中） |
| Q-9 | 是否已提交小程序备案/网站 ICP 备案/公安备案（仓库无记录） | 微信后台「小程序备案」、阿里云/腾讯云备案控制台（只读） |
| Q-10 | CloudBase 备份策略与恢复能力 | 腾讯云控制台（备份/回档） |
| Q-11 | 数据出境判断（H5 静态含 2 学号在港；业务数据在沪；微信云开发地域） | 修复 H-6 后复核；以腾讯云/微信云开发地域为准 |
| Q-12 | `service_health`/诊断页是否随下一版上线（当前工作副本含、线上 O 版不含） | 发布前 diff 确认；若上线，纳入隐私政策「运维数据」说明 |

---

## 11. 正面发现（应保留）

1. **零外部依赖**：H5 无 CDN/字体/统计脚本/埋点，除 CloudBase 外零请求（[index.html:1235](../tools/index.html#L1235)）；小程序无第三方 UI/SDK、无 web-view、无定位/通讯录/用户信息接口。
2. **前端无高权限密钥**：仅 publishable key（设计公开）；无 `sk-`/appsecret/service_role。
3. **CORS 精确白名单**（实测 204/403），自定义头仅 `X-Device-Id`。
4. **匿名读取被 RLS 挡住**（实测所有表返回 `[]`；`users/identity_verify` 已删除 404）。
5. **身份门禁**在未验证前不请求班级数据（代码层面；已有多轮 QA），`class_members` 无 token 返回 `[]`。
6. **小程序数据与隐私页**提供了导出/关闭同步/清除云端/清除本机（尽管 H5 缺失），且退出身份清空全部缓存。
7. **导出图片规范**：水印/参数/编号/命名齐全，不含学号与手机号。
8. **AI 生成内容有「AI 摘要」标识**；OCR 本地离线；AI 只发文本不发图片。
9. **TSL 证书监控**（剩余天数告警）与 `health_beat` 13 项依赖心跳（仅管理员）。
10. **通知 iframe 模板**对外部文本 `esc()` 转义、无外部脚本。

---

## 附录 A · 审计证据索引（文件:行号）

### A.1 快照与线上

| 文件 | 快照信息 |
|---|---|
| H5 工作副本 `web\tools\index.html` | 468,856 B，mtime 2026-11-05 22:38:51，sha256 `7A2704E0…ACFE1AD`（审计期间被并发改写 3 次，见文首） |
| H5 线上 O 版 | 453,951 B，sha256 `186651F2…0219F82`，与 `web\tools\_backup\index_online_20261105-2215_preFlickerFix.html` 逐字节一致（2026-11-05 22:03 部署） |
| `C:\briefdesk\data\board-data.json` | 2,454,054 B，mtime 22:36，sha256 `A18CC864…BACC5`（45 组通知） |
| 小程序 | `mp-class-tools\`（app.json v2.0.0、18 页），源码 mtime 2026-11-05 7:46–21:32；未发布 |
| 云端 | `tool-d4gosudok46e0e081` / ap-shanghai；2026-11-05 22:40–22:41 只读探测（见 §0） |

### A.2 关键代码行（工作副本，除非另注）

| 主题 | 位置 |
|---|---|
| 身份门禁 UI | [index.html:721-730](../tools/index.html#L721-L730)；线上 [L691-700](../tools/_backup/index_online_20261105-2215_preFlickerFix.html#L691-L700) |
| 身份存储 / token | [index.html:2422-2426](../tools/index.html#L2422-L2426)、[6090-6130](../tools/index.html#L6090-L6130) |
| `class_verify` RPC | [index.html:2569-2571](../tools/index.html#L2569-L2571)；小程序 [cloud.js:207-219](../../mp-class-tools/utils/cloud.js#L207-L219) |
| `class_members`（含 sid） | [index.html:2580-2592](../tools/index.html#L2580-L2592)；文档 [CLOUDBASE.md:42-52](CLOUDBASE.md#L42-L52) |
| 管理员/班委 | [index.html:2527](../tools/index.html#L2527)、[2850-2878](../tools/index.html#L2850-L2878) |
| 主数据桶/缓存键 | [index.html:1159-1166](../tools/index.html#L1159-L1166)、[1194](../tools/index.html#L1194)、[2433-2435](../tools/index.html#L2433-L2435)、[2509-2525](../tools/index.html#L2509-L2525) |
| 退出身份 | [index.html:6120-6127](../tools/index.html#L6120-L6127) |
| 访问统计 | [index.html:5228-5263](../tools/index.html#L5228-L5263)、[5273+](../tools/index.html#L5273) |
| 反馈（含联系方式） | [index.html:1031](../tools/index.html#L1031)、[3054-3070](../tools/index.html#L3054-L3070) |
| 导出规范 | [index.html:3131](../tools/index.html#L3131)、[3240-3249](../tools/index.html#L3240-L3249)、[3487-3500](../tools/index.html#L3487-L3500)、[3651](../tools/index.html#L3651) |
| 诊断页（工作副本） | [index.html:684-716](../tools/index.html#L684-L716)、[1016-1019](../tools/index.html#L1016-L1019)、[5329-5500](../tools/index.html#L5329-L5500)；线上 O 版无 |
| 线上 O 版真实学号 | [_backup:2852-2853](../tools/_backup/index_online_20261105-2215_preFlickerFix.html#L2852-L2853) |
| 云端配置/公开 key | [index.html:1235-1236](../tools/index.html#L1235-L1236)、[CLOUDBASE.md:122-131](CLOUDBASE.md#L122-L131)、[cloud-config.js:18-32](../../mp-class-tools/utils/cloud-config.js#L18-L32) |
| 采集→云端写入 | [sync_notices_cloud.py:40-96](C:/briefdesk/scripts/sync_notices_cloud.py#L40-L96)、[111-143](C:/briefdesk/scripts/sync_notices_cloud.py#L111-L143) |
| AI 处理 | [ai_triage.py:315-343](C:/briefdesk/scripts/ai_triage.py#L315-L343)、[cloud_ai.py:74-112](C:/briefdesk/scripts/cloud_ai.py#L74-L112)、[CLOUD_AI.md:88-97](C:/briefdesk/scripts/CLOUD_AI.md#L88-L97) |
| 群成员身份/头像 | [build_identity_map.py:2-13](C:/briefdesk/scripts/build_identity_map.py#L2-L13)、[172-186](C:/briefdesk/scripts/build_identity_map.py#L172-L186)、[report_identity.py:1-13](C:/briefdesk/scripts/report_identity.py#L1-L13) |
| OCR | [ocr_qq_images.py:1-60](C:/briefdesk/scripts/ocr_qq_images.py#L1-L60) |
| 人群/团员名单 | [sync_audience_rosters.py:1-13](C:/briefdesk/scripts/sync_audience_rosters.py#L1-L13)、[sync_league_roster.py:100-170](C:/briefdesk/scripts/sync_league_roster.py#L100-L170)、[CLOUDBASE.md:426-464](CLOUDBASE.md#L426-L464) |
| 云端 DDL/RLS | [schema.sql](deploy/cloudbase/schema.sql)、[security_hardening.sql](deploy/cloudbase/security_hardening.sql)、[2026-11-04_visits_feedback_own_read.sql](deploy/cloudbase/2026-11-04_visits_feedback_own_read.sql)、[2026-11-05_notice_admin_override.sql](deploy/cloudbase/2026-11-05_notice_admin_override.sql)、[2026-11-05_test_account.sql](deploy/cloudbase/2026-11-05_test_account.sql)、[2026-11-05_service_health.sql](deploy/cloudbase/2026-11-05_service_health.sql) |
| 小程序隐私/同步 | [privacy.js:1-161](../../mp-class-tools/utils/privacy.js#L1-L161)、[data.wxml:1-130](../../mp-class-tools/pages/data/data.wxml#L1-L130)、[identity.wxml:1-56](../../mp-class-tools/pages/identity/identity.wxml#L1-L56)、[identity.js:1-134](../../mp-class-tools/utils/identity.js#L1-L134)、[cloud.js:120-170](../../mp-class-tools/utils/cloud.js#L120-L170) |
| 小程序订阅消息 | [cloudfunctions/notify/index.js:1-267](../../mp-class-tools/cloudfunctions/notify/index.js#L1-L267)、[app.js:80-87](../../mp-class-tools/app.js#L80-L87) |
| 部署/证书 | [sync_tools.py:14-65](deploy/sync_tools.py#L14-L65)、[setup_tool_site.py:29-33](deploy/setup_tool_site.py#L29-L33)、[121-172](deploy/setup_tool_site.py#L121-L172)、[181-199](deploy/setup_tool_site.py#L181-L199) |
| 健康心跳/证书监控 | [health_beat.py:1-23](C:/briefdesk/scripts/health_beat.py#L1-L23)、[608-635](C:/briefdesk/scripts/health_beat.py#L608-L635) |

### A.3 本次未读取的机密文件（遵守红线）

`web\deploy\creds.env`、`web\tools\cert\`、`web\deploy\acme_account_key.pem`、`web\jwxt\creds.dpapi`、`C:\briefdesk\secrets\*`（仅列文件名，未读内容）、任何 token/密钥明文。

---

## 附录 B · 方法与限制

1. **只读**：全部证据来自本地文件读取、`grep/Select-String`、只读命令、以及对自有站点/云端的**只读** GET/OPTIONS/HEAD 探测；未执行部署脚本，未写云端数据。
2. **快照漂移**：`tools/index.html` 在审计期间被并发改写至少 3 次（22:23 / 22:33 / 22:38），行号以 468,856 B 工作副本为准；线上 O 版为 453,951 B（不含诊断页）。若并发改造继续，请以本文所述「哈希锚定」方式复核。
3. **云端写策略未实测**：为避免写数据，`hw/nt` 的 INSERT/UPDATE 策略、`visits/feedback` 写策略、`class_verify` 限流/token TTL、数据清理任务等无法从外部只读确认，已列入 §10 待确认并给出只读核查方法。
4. **PII 最小化**：报告未打印任何 token、密钥、完整手机号；学号仅保留结构（`32607070xx` 等掩码）；手机号仅给数量与来源字段。
5. **法规适用性**：本文引用的法规条款为「影响口径」，具体适用与程序要求（备案、类目、PIA、等保、算法备案）以 task-1/ task-3 的研究结论为准；本报告聚焦**现状事实与差距**。
