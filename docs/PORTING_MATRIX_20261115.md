# 网页端（web）对安卓 App 的移植性审计矩阵 · 2026-11-15

> 任务：task-64「网页端移植性审计 + 可完整移植项（不部署）」
> 审计对象：工作区网页源码 `web/tools/index.html`（单文件零依赖；审计开始时 **1,246,165 B**、服务器版本 2.0.0，工作树含并行地图会话 1 行 WIP，未部署；本次实施后 1,322,983 B，见 §5）与安卓 App 源码 `C:\Users\Ko_Li\.openclaw\workspace\android-class-tools`（`app/src/main/kotlin/com/furina/classtools/ui/screens/*`、`features/*`、`data/*`）。
> 结论口径：**可完整移植** = 网页端能力与安卓基本等价或已具备；**部分缺失** = 网页平台限制导致只能做子集/替代形态；**不移植** = 网页无法可靠实现，或无收益/与用户既定决定冲突。
> 本次红线：只改 `web` 源码与测试；**不部署线上**；`APP_VER` 保持 **2.0.0**；不引入构建链/外部依赖/外部请求；不改 UD v6 契约与云端表。
> 相关规范：`AGENTS.md` §0（红线）§1（设计规范）§4b（架构补充）、`HANDOFF.md` §5.2（自检）、`web/vote/CONTRACT.md`、`web/ppt/CONTRACT.md`。
> **2026-11-16 附注（21:4x 更正）**：网页「学信网」入口按用户更正已恢复（仅网页保留；`活动` 已于 2026-11-15 撤回、`今日校园` 从未在网页提供，二者仍不出现）；本文件 §1 / §2.1 #15 / §5 中相关描述为 2026-11-15 历史审计快照，当前状态见文末 §7。

## 0. 审计方法与证据来源

| 项 | 说明 |
|---|---|
| 安卓侧枚举 | `ui/screens/`（activity/all/chsi/cloudspace/data/diag/draw/express/feedback/fit/group/guide/home/homework/identity/jw/map/me/notices/power/ppt/privacy/profile/roster/settings/timetable/todaycampus/tools/vote/water）+ `features/`（chsi/draw/export/feedback/fit/group/home/jw/power/ppt/roster/water）；通知「自动全部加载」见 `data/notices/NoticesAutoLoader.kt`；外观三态见 `ui/theme/AppearanceMode.kt` |
| 网页侧枚举 | `tools/index.html`：`TOOLS`（draw/tt/committee/hw/nt/ft/roll/stats/diag/water/vote/ppt/map/jw/chsi + 运行时追加 file）、`SPECIAL_TAB`（power/fb/ug）、独立页 `#s-file`/`#s-nt`/`#s-ug`/`#s-fb`/大屏（`STAGE`/`OPT2`）与 `B2` 提醒 |
| 数据/同步契约 | 网页：CloudBase PG + PostgREST（`X-Device-Id` token + RLS）、`userdata` v6、`marks`、`public.notices` override 四列；本地 localStorage 仅缓存。安卓：同云端契约（UD v6 互通） |
| 证据定位 | 下文表格「网页证据」列为 `tools/index.html` 内的锚点/选择器/函数名；「安卓证据」列为 `app/src/main/kotlin/com/furina/classtools/...` 路径缩写 |
| 限制说明 | 本审计为**源码级**静态比对 + 现有专项测试/契约文档交叉核对；未使用真实账号登录任何一端（AGENTS §0-7 测试账号红线） |

## 1. 总结论（先看这里）

| 结论 | 数量 | 工具/能力 |
|---|---|---|
| **可完整移植（网页已具备）** | 21 | 身份门禁、工作台/工具栏（顶部切换条）、全部工具页、抽签、分组、课表、作业、通知（含长期/附件/提醒）、体测、名单、点名、诊断、学信网（入口）、演示、投票、地图、使用说明、反馈、文件传输（=安卓云空间）、大屏与互联（网页独有，反方向）、提醒设置（能力子集：浏览器 Notification + 页内提醒） |
| **可完整移植（本次实施）** | 6 | ① 通知「自动全部加载（进度/失败重试）」② 外观浅/深/跟随系统 ③ 工具卡片描述两行 ④ 浅色底部操作区无黑影 ⑤ 顶部留白 ⑥ 平板/桌面 ≥960/1320 响应式审计修复 |
| **部分缺失（网页平台限制）** | 8 | 我的数据 2×2、清除本机缓存、用户协议/隐私政策独立页、权限管理、系统级后台推送（网页＝浏览器 Notification，后台不可靠）、教务表单自动填充（浏览器安全模型禁止跨域代填）、PPT 原样播放弱网/后台保活（浏览器限制）、沉浸式/深色状态栏（仅 `theme-color` 近似） |
| **不移植（明确决定/无收益）** | 6 | 快递、活动（第二课堂）、今日校园、OPPO 推送、安卓底部导航 dock、隐藏状态栏/壁纸取色（浏览器无 API） |

> 一句话：**网页端工具面已基本追平安卓（21 项具备）；本次补齐 6 项可完整移植的体验短板；8 项平台受限项与 6 项不移植项均有明确理由。**

## 2. 逐工具矩阵

图例：✅ 可完整移植（已具备）｜🛠 可完整移植（本次实施）｜🟡 部分缺失｜⛔ 不移植

### 2.1 学习与班级工具

| # | 工具/能力 | 安卓 App 现状（证据） | 网页现状（证据） | 结论 | 说明 |
|---|---|---|---|---|---|
| 1 | 身份门禁（学号+姓名） | `ui/screens/identity/IdentityScreen.kt` | `#idgate` + `classVerify` + `zq_class_identity` token；RLS 服务端校验（`AGENTS.md` §0-4） | ✅ | 网页为唯一入口，无注册/密码；管理员=云端 role |
| 2 | 工作台 / 顶部切换条 | `ui/screens/home/HomeScreen.kt`（v5 工作台） | `.tabs` 顶部切换条（竖屏 3+全部、横屏 4+全部），`homeTools` ≤4，液体重排 | ✅ | 网页**无底部导航栏**（AGENTS §1 设计红线），形态与安卓不同但能力等价 |
| 3 | 全部工具页（卡片/排序） | `ui/screens/all/AllToolsScreen.kt`（长按拖动排序） | `#s-all` + `renderAllCards` + 卡片拖动 v2.1（`zq_all_order_v1` 仅本机）+ 拖入工具栏写 `homeTools` | ✅ | 网页多「拖入顶部工具栏」；顺序本机 vs 安卓 `toolOrder` 云同步（契约不同） |
| 4 | 抽签（STEP1） | `features/draw`、`ui/screens/draw` | `#s-draw`/`#p1`：范围/个数/重复/排除/名单/结果重排/存证 `#verify`/今日次数 | ✅ | 三端同规则：`crypto` 拒绝采样公平随机 |
| 5 | 分组（STEP2） | `features/group`、`ui/screens/group` | `#p2`：组数/每组人数/打乱/序号名单/导出 | ✅ | — |
| 6 | 课表 | `ui/screens/timetable/TimetableScreen.kt`、`features/…` | `#s-tt`：周/日视图、周次、下一节、课程详情、导入/导出、个人教务登录 `#tLogin`、云快照 `site_assets id='tt'` | ✅ | 网页课表为静态/云端快照 + 个人登录抓取；安卓另有本地缓存 |
| 7 | 作业 | `ui/screens/homework/HomeworkScreen.kt` | `#s-hw`：发布/截止倒计时/完成勾选/附件（图片压缩）/导出/30s 轮询/离线补发 | ✅ | 云端 `homework` + `marks` 跨端同步 |
| 8 | 通知 | `ui/screens/notices/+data/notices/*`（含 `NoticesAutoLoader`） | `#s-nt` 固定视口 iframe（模板 `NOTICE_TPL_B64`）：分类/筛选/已处理/附件/长期通知/管理员编辑/隐藏/恢复/提醒 | ✅（加载语义见 #23） | 通知模板由 briefdesk 生成 → `build_notice_embed.py` 嵌入；iOS/微信 iframe 滚动已加固（AGENTS §4b-2） |
| 9 | 体测 | `ui/screens/fit/`、`features/fit` | `#s-ft`：国标算分/等级/历史/导出/云同步（UD v6 `fit` 含 sex/grade） | ✅ | — |
| 10 | 名单（班委/团员/全班） | `ui/screens/roster/` | `#s-committee`（三 tab + 管理仅班委）、`class_members`/`class_league` RPC | ✅ | 网页名单只显示姓名+座号，不显示学号（隐私红线） |
| 11 | 点名 | `ui/screens/roster/`（点名相关） | `#s-roll`：到/假/历史/汇总导出、`zq_roll_*` 本机 + UD `roster` 同步 | ✅ | — |
| 12 | 统计 | `ui/screens/me/MeStatsSection.kt`（我的数据） | `#s-stats`：管理员访问统计（`visits` 表，≥960 左右分栏） | 🟡 | 网页统计=**管理员**访问统计；安卓「我的数据 2×2（本人作业/通知/抽签/访问）」网页无独立页 → 部分缺失 |
| 13 | 诊断 | `ui/screens/diag/` | `#s-diag` 诊断 v2.1：服务健康 18 行/5 组、设备检查 10 项、`client_diag` 脱敏上报、AI 结论/修复流程、`sensMask()` | ✅ | 全员可见、门禁前 0 请求（AGENTS §4b-18/19） |
| 14 | 教务 | `ui/screens/jw/`、`features/jw` | `#s-jw`：卡片直跳教务系统 + 浏览器密码管理器（`openJwDirect`）；个人课表登录 `#tLogin` | 🟡 | 网页不能跨域代填/内嵌（浏览器安全模型 + 学校 SPA），只能直跳+浏览器自动填充；个人登录走本机 PGP 排队链路 |
| 15 | 学信网 | `ui/screens/chsi/`、`features/chsi` | `#s-chsi`：10 张官方入口卡（2/3/4 列），零请求、不采集账号 | ✅（入口级） | 网页不抓数据（跨域+隐私），只做官方入口；安卓可登录后抽数据卡 |
| 16 | 演示（PPT） | `ui/screens/ppt/`、`features/ppt` | `#s-ppt`：上传→转换机→兼容版/PDF/原始/视频单独下载 + 旧 deck 在线预览；ECS `/pptfiles` 加速 + OSS 备用 | ✅ | 契约 `web/ppt/CONTRACT.md` §11/§12；浏览器无法强制 PowerPoint 全屏（需 F5，已标注） |
| 17 | 投票 | `ui/screens/vote/` | `#s-vote`：限时/指定截止/不限时、单选多选、匿名/实名、结果可见性、**可见范围（全班/班委/团员/指定成员）**、管理/改票/软删 | ✅ | 契约 `web/vote/CONTRACT.md`；一人一票按 sid、RPC 不返回学号 |
| 18 | 地图 | `ui/screens/map/` | `#s-map`：2.5D 校园地图 iframe（`/map/campus_final_25d.html`，embed/room 参数）+ 编辑/全屏入口 + 课表下节课联动 | ✅ | 网页地图为独立静态页（iframe），可外开全屏；零外部请求 |
| 19 | 使用说明 | `ui/screens/guide/` | `#s-ug`：分类卡片轮播 + 一键总览（19 张卡）、左右滑动/键盘 | ✅ | 网页版卡片化重构契约见 `使用说明_卡片化重构契约_20261112.md` |
| 20 | 反馈 | `ui/screens/feedback/`、`features/feedback` | `#s-fb`：提交（内容/联系方式）+ 管理员反馈列表（≥1024 两栏） | ✅ | 云端 `feedback` 表 |
| 21 | 文件传输 / 云空间 | `ui/screens/cloudspace/CloudSpaceScreen.kt` | `#s-file`（运行时 `TOOLS` 追加「文件传输」）：同账号设备共享、分片上传、3 天 TTL、`#file` 直达 | ✅ | = 安卓「云空间」，**无需重复移植**（任务口径） |
| 22 | 大屏 / 多端互联 | ——（安卓无对应） | `STAGE`/`OPT2` 大屏 V4/V5 + `#drop` 互联（ECS `class-tools-drop`，HMAC 下载、房间码） | ✅（网页独有） | 反方向能力；不要求安卓移植 |
| 23 | 通知「自动全部加载」 | `data/notices/NoticesAutoLoader.kt`：首屏后循环 `loadMore` 直到 `hasMore=false`，逐页回调、失败延时重试一次、保留已加载 + 重试行 | 旧版式无「加载更多」按钮：`NT.fetchFull()` 单次 `GET notices?select=*` 拉全表（现网约 103 组/2 MB 量级）后整表渲染；加载中骨架、失败无显式重试 | 🛠 | 网页无分页按钮（整表一次到位）。本次「移植语义到网页形态」：**明确的加载进度提示 + 失败保留缓存 + 重试入口**；保持单请求（避免 103 组表被拆页导致首屏变慢） |
| 24 | 外观浅/深/跟随系统 | `AppearanceMode.kt`（system/light/dark，默认跟随系统）+ `ProfileScreen` 颜色模式三选一（`ui/theme/Theme.kt` 双色板） | **无主题机制**：`:root` 固定浅色变量 + 大量硬编码浅色；无 `prefers-color-scheme`/`theme`/`dark` 相关代码 | 🛠 | 本次新增：本机 `zq_appearance_v1`、首帧应用（防闪白）、跟随系统监听、深色覆盖层（不改浅色默认视觉）、通知 iframe 同步深色 |
| 25 | 工具卡片描述两行 | 安卓全部工具卡描述行两行（`AllToolCard.kt`） | 网页 `.tdesc` 无行数限制、无省略号；窄屏 2 列时最长描述会换行，但无「两行完整显示」保障 | 🛠 | 本次：`.gcard.tool .tdesc` 统一两行盒模型 + 不截断断言（当前全部描述 ≤2 行） |
| 26 | 浅色底部操作区无黑影 | 安卓底部 dock 在浅色主题下的阴影/描边规范 | 网页无底部导航（设计红线）；等价物=底部弹层/操作区：`.dropctl-card` 用 `0 -20px 60px rgba(0,0,0,.4)` 黑色重影，浅色下观感突兀 | 🛠 | 本次：底部弹层阴影改暖色柔和投影（浅色主题），深色主题另给轻阴影 |
| 27 | 顶部留白 | 安卓沉浸式 + 状态栏留白 | 网页 `.brand` 顶部 18px（手机 15px+safe-area）；桌面换 sticky `tabs` 贴顶 | 🛠 | 本次：桌面适度增加顶部呼吸位（≥960 约 22–24px），手机保持 safe-area 不动 |
| 28 | 平板/桌面响应式（≥960/1320） | 安卓平板双栏（`ProfileScreen` ≥840dp 等） | 已有 DESKTOP-OPT-V1（≥960/1024/1200/1440/1600 多档）；本次审计复测 960/1320 档 | 🛠 | 本次：审计 960/1320 容器宽度、卡片网格列数、间距、底部行对齐等，修复明显问题（见 §4） |

### 2.2 系统 / 设置 / 平台独有

| # | 能力 | 安卓现状 | 网页现状 | 结论 | 说明 |
|---|---|---|---|---|---|
| 29 | 我的 / 设置页 | `ui/screens/profile/ProfileScreen.kt`（身份/数据与同步/通知与权限/外观/关于/退出 六段） | 无独立「我的」页：品牌区身份胶囊（点击退出）、`#optBkRow`（数据备份）、提醒设置弹层、外观弹层（本次新增） | 🟡 | 网页以轻量入口替代；「我的数据 2×2」「清除本机缓存」「用户协议/隐私政策」网页无独立页（见 #12/#30/#31） |
| 30 | 数据与隐私 / 清除本机缓存 | `DataPrivacyScreen.kt`、`PrivacyDialogs.kt` | 数据备份（导出/导入本机 zq_*，不含身份 token，`#optBkBtn`）；无「清除缓存」按钮 | 🟡 | 网页可用：退出身份（清 token/缓存桶）+ 浏览器清站点数据；拟后续补充「清除本机缓存」入口（本次不改，避免扩大范围） |
| 31 | 用户协议 / 隐私政策 | `ProfileScreen` 关于与帮助 + `PrivacyTexts.kt` | 无独立页 | 🟡 | 网页页脚仅身份门禁提示；隐私红线见 `AGENTS.md` §0-4/§2（导出不含隐私字段）。本次不新增法律文本页（需用户确认文案） |
| 32 | 权限管理 | `ui/screens/settings/PermissionSettingsScreen.kt` | 浏览器权限由站点设置/地址栏管理，网页无「权限管理」页 | 🟡 | 网页提醒设置内已展示 Notification 授权状态与降级说明（`#ntRemindBtn`） |
| 33 | 提醒设置 | `ReminderSettingsScreen.kt` | `#ntRemindBtn` 弹层：浏览器 Notification 授权/开关/测试提醒/降级为页内提醒（`zq_remind_v1`，本机） | ✅（能力子集） | 网页无法像安卓那样开机/后台常驻推送（浏览器限制）→ 归入 #32/#40 说明 |
| 34 | OPPO 推送 | `app/oppo.properties` + SDK V4.0.0 + `push_tokens` 表 | 无（网页） | ⛔ | 原生厂商推送 SDK 只存在于安卓；网页替代=浏览器 Notification + 页内提醒。本次不移植 |
| 35 | 快递 | `ui/screens/express/ExpressScreen.kt`：一键打开拼多多/淘宝/菜鸟/京东 App 或官方 H5 出示身份码/取件码 | 无 | ⛔ | 任务明确不建议移植：网页无法出示 App 内身份码/取件码、无原生深链；只做外链收益低。与用户既定决定一致 |
| 36 | 活动（第二课堂） | `ui/screens/activity/` + 本机 `activity` agent（签名/浏览器辅助登录） | 曾于 2026-11-15 上线，同日按用户决定撤回（commit `6c0ae49`：改由安卓 App 原生提供，其他端不显示） | ⛔ | 用户明确决定仅安卓；网页不恢复。且需 App 内学校登录态/本机签名服务 |
| 37 | 今日校园 | `ui/screens/todaycampus/`：WebView 打开学校融合门户 `e.fjtcm.edu.cn`（CAS 登录态） | 无 | ⛔ | 网页无法复用 WebView/CAS 登录态；iframe 会被 `X-Frame-Options`/跨域拦，密码红线禁止代填。不移植 |
| 38 | 安卓底部导航 dock | `ui/components/dock/` | **无底部导航**（AGENTS §1 用户明确设计红线：顶部切换条） | ⛔ | 不移植：与网页设计规范冲突 |
| 39 | 隐藏状态栏 / 壁纸取色 | `AppearanceSettings.hideStatusBar` / Material You 动态取色 | 无（浏览器无系统栏控制权） | ⛔ | 平台独占；网页用 `theme-color` 近似（本次随外观一起处理） |
| 40 | 系统级后台推送 | OPPO 推送 + 安卓前台服务 | 浏览器 Notification（页内轮询 + 隐藏时静默检查；页面关闭即失效） | 🟡 | 平台限制：网页无法保证后台/杀进程后送达；已有页内提醒降级文案 |
| 41 | 沉浸式/深色状态栏 | `ImmersiveStatusBar.kt` | 无系统栏；可通过 `meta theme-color` 让移动浏览器地址栏随主题变色（本次加入） | 🟡 | 近似方案，非等价 |

## 3. 「部分缺失」逐项说明（网页为何做不到等价）

1. **我的数据 2×2（#12）**：安卓本地/云端即时聚合本人作业完成、通知已处理、抽签、访问次数；网页对应数据分散在 `marks`/`NT.done`/`AN_DONE`/`zq_draw_last_v1`/`visits`，做聚合需新增只读 RPC 或大表查询 → 与「零新增接口」的收敛原则冲突；本次不做，记入后续建议。
2. **清除本机缓存（#30）**：网页本机缓存含 IndexedDB 通知缓存、`zq_tools_v2`、`zq_*` 偏好；正确清理需按 sid 分桶处理，误删会丢「通知已处理/抽签上次结果」等本机记忆。现有替代：退出身份（清身份+缓存桶）+ 数据备份/恢复。建议后续单独做「清理缓存（保留身份）」按钮并加确认。
3. **用户协议/隐私政策（#31）**：需用户确认正式文案；网页已有导出隐私红线与 `README.md` 安全红线，但无面向同学的独立法律页。不擅自编写法律文本。
4. **权限管理（#32）**：网页无系统权限概念；Notification 授权只能在浏览器站点设置里改，页面内已显示状态与降级说明。
5. **隐藏状态栏/壁纸取色（#39）**：浏览器沙箱无此 API，仅能以 `theme-color` 跟随明暗主题。
6. **通知后台推送（#40）**：浏览器不允许页面关闭后常驻轮询/推送（无 Service Worker 推送基础设施，且用户要求零外部请求/零后端）；网页保持「页内提醒 + 打开即同步」。
7. **教务自动填充（#14）**：浏览器安全模型禁止 A 站脚本读写 B 站登录表单；学校统一认证不支持 URL 预填（2026-11-13 结论，见 `CHANGELOG.md` 增量 55）。网页=直跳 + 交给浏览器密码管理器。
8. **PPT 原样播放弱网保活（#16）**：浏览器 `<video>` 后台/锁屏行为由系统策略决定；网页已有「弱网/无 video 自动回退分步」与 `waiting` 卡顿回退。

## 4. 本次实施清单（已完成，仅本机；不部署 / 不推版本）

| # | 实施项 | 实现落点 | 验收结果 |
|---|---|---|---|
| A | 通知「自动全部加载」网页语义 | `renderNoticeFrame()` 新增 `noticeLoadingHTML()`（进度条+「正在加载全部通知…」）与 `noticeFailHTML()`（失败+重试）；`NT` 增 `fail` 标记、失败保留已加载/缓存；retry 调 `NT.pull(true)`；IDB 补水最多等 1.2s 兜底（`NT._waitCache` 超时放行，迟到缓存用 `NT._fresh` 守卫不回灌）；`window.__NT_PROGRESS` 只读探针 | 无「加载更多/加载全部」按钮；8 条 mock 通知全部渲染；加载中显示进度、完成消失；失败显示失败态、点重试恢复；通过 `v2_port_ui_check` D1–D9 |
| B | 外观浅/深/跟随系统 | `<head>` 首帧 `__APPEARANCE_BOOT_V1__`（localStorage `zq_appearance_v1`，防深色闪白）+ `APPEARANCE` 模块（三态/跟随 `matchMedia`/多标签 `storage` 同步/弹层/焦点/ARIA）+ 全部页底部「外观」入口（与数据备份同排，`#apBtn`）+ `meta theme-color` 随主题；深色=纯追加覆盖层（`tools/build_dark_theme.py` 生成，`html[data-appearance=dark]` 前缀，浅色默认视觉零改动）；通知 iframe 深色由 `build_notice_embed.py` 内置覆盖，父页只切属性 | 三态即时生效/刷新保持/跟随系统实时切换；深色下 body/card/tabs 变暗且正文对比度≥4.5；通知 iframe 同步深浅；通过 `v2_port_ui_check` A1–A13/B1–B3/C1/D6–D7 |
| C | 工具卡片描述两行 | `.gcard.tool .tdesc`：`-webkit-line-clamp:2` + `min-height:1.6em` + `overflow-wrap:anywhere`（两行完整显示；现有全部工具描述均 ≤2 行不被省略） | 430/960/1320 全部卡片：无裁切（scrollHeight≤clientHeight）、行数≤2；通过 E11–E13/E21–E23/E31–E33 |
| D | 浅色底部操作区无黑影 | `.dropctl-card` 改 `0 -14px 36px rgba(35,48,46,.18)`、`.rst-sheet` 改 `0 -14px 40px rgba(35,48,46,.16)`（暖色柔和投影）；深色主题另给轻黑投影 | 浅色主题底部弹层 box-shadow 不含纯黑；通过 E18/E28/E38 |
| E | 顶部留白 | `@media(min-width:960px){.brand{padding:22px 0 14px}}`、`≥1280` 24px；手机 `15px+safe-area` 保持原样 | 960/1320 实测 brand padTop=22/24，手机 15；通过 E14/E25/E35 |
| F | 平板/桌面 ≥960/1320 响应式审计 | 审计 430/960/1320 三档（19 个页面截图 + 指标：容器/列数/底部行/溢出）；修复：`#optBkRow` 底部操作行限宽（1280/1320）+ 居中，与卡片网格右缘对齐；`≥1600` 时 `#allCards` 放宽到 1520（与 `.wrap` 超宽档一致） | 960 wrap=912/3 列、1320 wrap=1256/4 列、底部行与卡片右缘对齐 ±2px、三档横向溢出=0；通过 E25–E28/E36–E38 |

> 本次**不**实施：我的数据 2×2、清除本机缓存、用户协议/隐私政策页、权限管理页（均属「部分缺失」，见 §3）；不恢复活动/快递/今日校园；**不改 `APP_VER`（仍 2.0.0）、不部署、不推 Git 远端**（由 Lead 统一集成/部署）。

## 5. 验证方式与本次实测结果（本机、不部署）

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web\tools
python tests\v2_port_ui_check.py     # 新增：外观三态 / 通知自动全部加载 / 描述两行 / 底部阴影 / 顶部留白 / 桌面间距 / 0 JS 报错
python tests\v2_ui_check.py          # 回归
python tests\optim_v1_check.py       # 回归
python tests\optim_v2_check.py       # 回归（main/admin/hash）
python tests\overflow_check.py 430   # 横向溢出
python tests\overflow_check.py 960
python tests\overflow_check.py 1320
python tests\v2_drag_check.py        # 卡片拖动（全部页卡片不变更语义）
python tests\v2_ug_check.py          # 使用说明
```

| 测试 | 结果 |
|---|---|
| `tests/v2_port_ui_check.py`（新增） | **80/80 GREEN**（静态 21 + 运行时 59，退出码 0）：外观三态/首帧/存储/弹层/对比度/theme-color/通知 iframe 同步、跟随系统实时切换、深色持久化、通知加载进度/全部渲染/失败重试、描述两行、底部软影、顶部留白、960/1320 容器与列数、底部行对齐、横向溢出、0 JS 报错/0 console.error/0 外部请求 |
| `tests/v2_ui_check.py` | **27/27 PASS** |
| `tests/optim_v1_check.py` | **GREEN**（0 fails） |
| `tests/optim_v2_check.py` | **GREEN**（main + admin + hash 三段全绿，0 fails） |
| `tests/overflow_check.py 430 / 960 / 1320` | **overflowCount=0**（三档；per-tab draw/tt/hw/nt/ft 全 0） |
| `tests/v2_drag_check.py` | **69/69 PASS**（拖动/排序/拖入工具栏语义未变） |
| `tests/v2_ug_check.py` | **56/56 PASS** |
| `tests/v2_chsi_check.py` | **54/54 PASS**（并行改动回归；2026-11-16 曾随 task-75 删除，**同日按用户更正恢复并复跑 54/54，见 §7**） |
| `tests/v2_notice_data_check.py` | **27/27 PASS** |
| `tests/v2_notice_dynamic_cat_check.py` | **17/18**：`E13 可筛选到动态新分类` 失败；已用 `git show HEAD:tools/notice-board-live-demo.html` 副本复跑 **同样 17/18** → **改动前既有失败**（该测试对象是 `notice-board-live-demo.html`，本次未改动该文件；与本次改动无关） |
| 视觉审计 | `tests/_shots_port/`（过程截图，gitignore）：dark 19 页 @1280 + light 19 页 @960（另 1320 抽检），0 横向溢出、无 JS 报错；深色各页可读、无浅色大块残留（地图 iframe 为画面型浅色，保持其自身配色）；外观弹层浅/深两态截图核对 |

- 测试身份只用官方测试身份/9999 段 mock（`AGENTS.md` §0-7），不读写真实 token；预览页 fetch 全部 mock，0 外部请求。
- 深色主题再生成命令（新增组件/改浅色硬编码后）：
  `python build_dark_theme.py`（写 `index.html` 深色标记段）→ 如改了通知模板深色基线再 `python build_notice_embed.py`（重嵌 `NOTICE_TPL_B64`）。
- `tools/index.html` 改动前后：**1,246,165 B → 1,322,983 B**（深色覆盖 ~36 KB + 通知模板深色 ~16 KB（base64 后 ~22 KB）+ 外观/通知/布局增量）；`APP_VER` 仍 `2.0.0`。改后源码 **sha256 `42F5C5BB6F1A220EC84BCAC6D59C7BD138DAAB7CA40A8F68859447199A4BD1A8`**（供 Lead 集成/部署前核对）；行尾 LF（`build_notice_embed.py` 已固定 `newline="\n"`，避免 Windows 默认 CRLF 污染）。
- 深色生成的字节级幂等性已验证：连续两次 `python build_dark_theme.py`，`tools/index.html` 字节数与 sha256 完全一致。
- 身份门禁未改：本次未触碰 `class_verify`/RLS/`userdata` v6/云端表；未部署 OSS/ECS、未推 Git 远端（工作树改动，由 Lead 统一提交/部署）。

## 6. 遗留建议（不在本次范围）

1. 「我的数据 2×2」如需移植，建议新增只读 RPC（聚合本人 marks/visits/userdata 摘要，不返回学号）或在网页用已有本机数据 + `marks` 轻量查询近似。
2. 「清除本机缓存」入口建议放在 `#optBkRow`（与数据备份/外观同排），需按 sid 分桶清理并保留身份 token。
3. 用户协议/隐私政策页需用户提供/确认文案后再加，避免法律文本由工程侧臆造。
4. 通知表未来若超过网关单次返回上限，可将 `cbGetNotices` 改为 Range 分页 + 复用本次的进度/重试 UI（本次不预置分页，避免 103 组表被拆页拖慢首屏）。
5. 深色模式下若后续新增工具页/组件，需同步补深色覆盖（本次深色覆盖为「语义变量 + 浅色硬编码批量映射」，新增浅色硬编码可能漏网，建议新组件优先用 CSS 变量）。

## 7. 2026-11-16 变更附注：网页「学信网」入口先移除后更正恢复（历史审计内容保持原样）

- 用户先要求全端删除「活动 / 今日校园 / 学信网」三工具（web task-75），随后更正为**仅网页保留学信网**（Android/小程序/鸿蒙仍删除，web task-77）。网页侧：`活动` 已于 2026-11-15 按用户决定撤回（commit `6c0ae49`，改由安卓 App 原生提供）；`今日校园` 从未进入网页 `TOOLS`（仅安卓 App 有，本矩阵 #37 已记为「不移植」）；`学信网` 于 2026-11-16 先随 task-75 删除（HEAD `9092feb`），后按 task-77 恢复到当前 `index.html`（= HEAD + 原 chsi 7 处块；确认 `activity`/`todaycampus`/`今日校园` 仍为 0）。
- 恢复内容：`TOOLS.chsi`、`ALL_TONE.chsi`、`#s-chsi` 整段 HTML/`__CHSI_ENTRY_V1__` 标记、`__CHSI_ENTRY_V1_CSS__` 样式与深色主题 3 条规则、使用说明第 19 张 `chsi` 卡，以及 `tools/tests/v2_chsi_check.py`；`v2_ug_check`/`v2_jw_check`/`v2_port_ui_check` 计数与 `tools/tests/_power_preview.html` 一并恢复/重生成。
- 当前网页：`TOOLS` 15 项（draw/tt/committee/hw/nt/ft/roll/stats/diag/water/vote/ppt/map/jw/chsi），使用说明 19 张卡；`APP_VER` 仍 `2.0.0`；源码 1,326,819 B / sha256 `8cc6f447…`（详见 `CHANGELOG.md` 2026-11-16 21:4x 更正条目）。
- 因此本文件 §1「可完整移植（网页已具备）21 项」中的「学信网（入口）」与 §5 测试表中的 `tests/v2_chsi_check.py 54/54` 仍适用（该测试已恢复并通过）；`活动`/`今日校园` 仍维持「不移植/不在网页」。
