# CHANGELOG — 班级工具站（tool.furina.fun）

> 每次上线记一条：时间 / 内容 / 回滚点。部署命令：`python deploy/sync_tools.py`。

## 2026-11-22 17:0x–17:2x · 通知附件「待获取」误报修复（网页 + 数据管线）

> 用户反馈：「有的我已经下载获取了还是显示待获取」。

- **根因（4 类）**：① 文件条目可能把 data URI 放在 `src` 而非 `url`（示例附件），模板只看 `url` → 误标；
  ② 压缩包已解压识别（`archiveOk`）后原包仍无 `url`，管理页把原包和 3 个包内文件都当成待获取；
  ③ 本机 `data/qq-files` 已有字节但超过 1.5MB 内嵌上限（榕疾控 PDF 1.9MB / 6.0MB），builder 返回空 `url` 且无标记；
  ④ 微信群 36MB pptx 已在微信 `msg/file`，但超过 30MB 导入上限 / 1.5MB 内嵌上限，前端无从得知已下载。
- **数据管线**：builder 新增 `apply_file_presence()`——按 `data/qq-files` → 微信媒体落地目录 → 本机下载目录
  依次确认字节，写入 `present/localSize`（不再带 `pending`）；`sync_notices_cloud.compact_group` 对 `present`
  的附件剥离 `pending`。通知模板：文件 `furl=it.url||it.src`，`present` 分支显示 **已获取**（未内嵌），
  `openFile` 同样兼容 `src`；压缩包保持 **已识别**。
- **管理页**：`pending_files()` 只列真正需要去群里拿的文件——跳过 `url/src/present`、压缩包已识别、
  微信媒体已落地、`data/qq-files` 已有、下载目录已有（尚未导入也算用户已下载）；不再单独列包内文件。
  管理页待获取 **12 → 1**（只剩确实未下载的 `民族器乐大赛招募志愿者名单.xlsx`）。
- **测试**：真实 board 轻量渲染（7 张卡）只剩 1 个「待获取」徽标，6 个「已获取/已识别」；`v2_notice_fix_check`
  **11/11**、`v2_notice_data_check` **27/27**、`v2_nt_admin_check` **65/65**；云端通知 body 已确认
  `present=true` 且 `pending` 已移除。
- **上线**：网页 **1,605,566 B / sha256 `7753daeeb2f1dacf4948925f158d12776b0135bd0ffe3f49a9d503d16ebbb7a5`**
  （OSS 与 ECS 均为该字节；用 **HEAD + 新模板** 合成，避免把并行会话未提交的任务 UI 改动带上线）。
  部署前线上备份 `tools/_backup/index_online_20261122-1723_prePresentFix.html`（1,604,750 B / `b0508020…`）。
- **回滚**：重传上述备份 + `ecs_site.py apply`；数据侧回退 builder 的 `apply_file_presence` 与模板分支
  （`sync_notices_cloud.py` 下次同步即恢复原样）。
- **已知取舍**：36MB 微信群文件只标「已获取」，网页仍不提供下载（超过内嵌/导入上限，原件在微信
  `msg/file`）；要在线提供需接 ECS 附件外置服务（`NOTICE_ATTACH_EXTERNALIZE=1`，尚未开启）。

## 2026-11-22 16:0x–16:5x · 通知管理（仅管理员：QQ/微信群采集 + 逐群可见人群 + 待获取文件）

> 用户需求：「在网页端的通知工具内添加仅管理员可见的页面，方便我对 qq/微信截取群聊，以及各个群聊的通知可见人群的管控，同时支持直接列出还需要获取的文件」。

- **页面**：新增 `#s-ntadmin`「通知管理」（TOOLS `admin:true`，通知页右下「管理」浮钮；非管理员不显示、`gotoTab` 拦截）。
  群列表（全部/QQ/微信筛选 + 搜索，采集中优先）；行内「采集」总开关 + 识别/文件/图片/文档分项；可见人群
  弹层（全体/班委/团员/仅管理员/指定座号/既有群成员名单）；添加/移除群聊；待获取文件（平台筛选、单项复制、
  复制清单、重新扫描）；采集端状态卡（上次应用、配置 rev、待获取数、应用时间）。桌面 ≥960px 双栏。
- **云端**：配置/状态/请求复用 `public.site_config` 三行 `notice_groups / notice_status / notice_request`
  （既有 RLS：仅 `auth_admin()` 可读写；普通成员读空、写被拒）。迁移
  `deploy/cloudbase/2026-11-22_notice_groups.sql`（已应用）：新增 `auth_seat()` + 集中函数
  `notice_audience_visible()`，重建 `notices.nt_read`，新增 `seats:1,8,12` 可见范围（只存座号）。
- **本机采集端**：新增 `notice_groups.py`（配置只读视图，未命中回落原关键词规则）与 `notice_admin.py`
  （拉配置 → `data/notice-group-config.json`；看门狗每轮隐藏启动；配置变化后立即重跑通知同步；发布状态；
  「重新扫描」只执行固定的 `fetch_qq_files.py --import-only`）。播种只含班级相关/确有采集项的 **24 群**
  （14 QQ + 10 微信），保持改造前采集范围；红会群可见人群为 `admin`（当前唯一管理员，等价原 `sid:`）。
  管线接入：`ai_triage` / `wechat_media` / `qq_context` / `fetch_qq_images` / `ocr_qq_images` / `detect_docs`
  逐群按配置采集；`sync_notices_cloud` 先应用配置再写 `notices.audience`。
- **修复**：`compact_group` 会丢掉 `group` 字段，导致逐群可见人群未生效 → 同步时用原始 group 计算 audience，
  并支持从 `source`「QQ 群 · X / 微信群 · X」反推群名（4 条红会通知实测纠正，117/117 与配置一致）。
- **测试**：网页 `v2_nt_admin_check.py` **65/65**（门禁/筛选/开关/人群/添加移除/待获取/空态/360·390·430 无溢出/
  桌面双栏/0 JS/0 外部请求）；云端 `nt_admin_cloud_check.py` **23/23**（临时 QA 普通+管理员身份：seats 命中/不命中、
  all/committee/league/sid 不回归、site_config 管理员可读写且普通成员读空/写被拒，finally 清理）；真实云端只读 E2E
  `nt_admin_live_check.py` **11/11**（本地通道 + QA 管理员，页面 24 群/12 待获取与云端一致，写请求全部拦截）；
  本机管线 `test_notice_admin.py` **16/16**（播种/归一/回落/audience/待获取/云拉取）。回归 `v2_ui` 27/27、
  `v2_drag` 69/69、`overflow 430`=0、`optim_v2` GREEN。
- **上线**：网页 **1,604,750 B / sha256 `b050802051d0d11c40b078cc0a2705d269d1937a81752b83983812f7237cbda7`**
  （OSS check MATCH / ECS verify MATCH）。部署前线上备份
  `tools/_backup/index_online_20261122-1653_preNoticeAdmin.html`（1,565,408 B / `9de65e9f…`，该备份不含本功能）。
- **回滚**：重传上述备份 + `ecs_site.py apply`；DB 回滚按迁移头部（重建旧 `nt_read`、删两个函数）；
  本机停用 `notice_admin`（看门狗调用）即回到原关键词采集。
- **已知取舍**：管理列表只播种 24 个班级相关群（其它全关群按需「添加群聊」）；「群成员（自动匹配）」只对
  现有 volunteer/viewer/blood/review/dorm/redcross 名单可用；指定成员按座号 1–70（存座号不存学号）；
  配置应用最长约 5 分钟（看门狗周期），配置变化后会立即触发一次通知同步；待获取清单来自 board-data，
  页面最多展示 200 条（云端状态最多 500 条）。

## 2026-11-22 20:0x–20:2x · 左侧栏自定义顺序同步（网页端）

> 用户反馈：「左侧栏的自定义没有同步」。

- **视图顺序上云**：左侧「视图」拖动顺序从仅 `localStorage zq_task_ui_v1` 扩展为任务数据
  `prefs.sidebarOrder` + `prefs.sidebarOrderAt`；`tkReorderSmart` 写本机偏好后同步写任务并 `tkSave()`，
  随现有 `taskdata` 任务快照上云；另一台网页设备拉到后应用到侧栏。
- **旧本机顺序迁移**：升级后首次打开若本机已有自定义视图顺序、任务数据尚无该字段，自动补写并推送；
  若云端已有顺序，则按 `sidebarOrderAt` 时间戳较新者生效，避免旧缓存覆盖。
- **分组顺序**：任务分组本身已在 `lists[].order` 随 taskdata 同步；本轮未改分组同步路径，仅补视图顺序。
- **云同步合并**：`taskNormData` 保留 `sidebarOrder/sidebarOrderAt`；`hasData` 把只有视图顺序的数据也视为有数据；
  `union` 按时间戳单独合并视图顺序；`applySnapshot` 后 `tkRefresh` 应用并回写本机 UI。
- **数据/接口**：无新表/字段迁移；taskdata blob 内新增 `prefs.sidebarOrder`（字符串数组）与 `sidebarOrderAt`（ms）；
  userdata v6 不变；其他本机 UI 偏好（排序/快速添加/完成区展开等）仍只本机。
- **测试**：`task_check.py` **161/161**（新增视图顺序写入任务数据）；`task_cloud_check.py` **10/10**
  （云端顺序下拉应用、推送 blob 携带顺序）；`task_cloud_live_check.py` 5/5；`v2_ui` 27/27、`optim_v2` GREEN、
  overflow 390/430=0、0 JS/console/外部请求。
- **上线**：**1,669,280 B / sha256 `637cb8ec4cba259ee046996e841d971a995f5805768a0643c1ef3b5fbda41753`**
  （OSS/IP 同字节；gzip **502,927 B**）；部署前备份
  `tools/_backup/index_online_20261122-2000_preSidebarSync.html`（1,667,196 B / `fb3bfee5…`）。
- **回滚**：重传上述备份；无 DB 变更。
- **取舍**：视图顺序随任务快照 LWW（并发改顺序以较新的 `sidebarOrderAt`/task 时间戳为准）；小程序/安卓任务端
  当前不消费该字段；分组顺序仍按 `lists[].order`。

## 2026-11-22 19:2x–19:4x · 任务详情、步骤展开与步骤备注（网页端）

> 用户需求：「在任务有步骤时允许展开步骤，同时点击已创建的任务应该是清晰明了的详情，单独设置编辑图标，同时每个步骤允许额外添加备注」。

- **点击任务 = 只读详情**：任务行点击不再直接进编辑器，打开 `#tkDetailPanel`；展示标题、分组/完成/重要、
  截止/提醒/重复/我的一天/标签、备注、步骤（含进度与备注）、附件（可预览）、来源（班级作业/通知可定位）、
  创建/更新时间；底部可标记完成/未完成。
- **编辑图标独立**：详情右上角铅笔按钮 `#tkDtEdit`，任务行右侧也有独立铅笔 `[data-tkedit]`；点击直接进原编辑器，
  不再与查看混在一起。详情右上角同时保留重要星标/关闭。
- **步骤展开**：有步骤的任务行出现展开箭头 `[data-tkexpand]`，展开为 `.tk-substeps`，显示每个步骤的完成状态、
  文字和备注；可在展开区直接勾选/取消步骤（不影响任务本身完成状态），再次点击收起。展开状态为页面会话内。
- **步骤备注**：步骤数据结构增加 `note`（≤500 字，缺省空），编辑器每个步骤下方多行备注输入；详情和列表展开
  区都显示备注；任务 JSON 备份、本机存储、`taskdata` 云同步自然携带（无新表/字段迁移）。
- **验证**：`task_check.py` **160/160**（详情打开/独立编辑图标/行编辑图标/步骤展开/备注/详情步骤勾选/
  移动端详情；原 147 项保留并调整点击语义）；cloud 8/8、live 5/5；`v2_ui` 27/27、`optim_v2` GREEN、
  overflow 390/430=0、0 JS/console/外部请求。
- **上线**：**1,667,196 B / sha256 `fb3bfee5ad1c84cc4ad16e32992648af5671cd03adb6409c3d714f2e66ae14d8`**
  （OSS/IP 同字节；gzip **502,352 B**）；部署前备份
  `tools/_backup/index_online_20261122-1935_preTaskDetail.html`（1,650,927 B / `1fa1cd7b…`）。
- **回滚**：重传上述备份；无 DB 变更。
- **取舍**：详情本身不再直接编辑（走铅笔）；步骤备注与展开不改变任务完成判定；步骤上限仍 50、备注 500 字；
  详情不提供删除，删除仍在编辑器内。

## 2026-11-22 18:5x–19:1x · 任务日期选择器优化（网页端）

> 用户需求：「对日期的选择也要做优化」。

- **任务截止日期改为专用日历面板**：快速添加 `#tkQuickDate`、详细编辑 `#tkFDate` 仍是隐藏原生 date（值源），
  可见的是日历按钮 + 当前日期/「选择日期」；不再直接弹浏览器原生日期框。
- **面板能力**：今天/明天/后天/下周一/一周后快捷；上月/下月/上一年/下一年；周一开始的 6 行日历；
  今日描边、选中实心、跨月日期可点；底部清除/取消/确定；已选日期回显。
- **联动**：选中日期写回隐藏值并派发 `input`/`change`，原有日期快捷/校验/提醒/导出/云同步不变；
  日期面板「清除」同时清除对应时间（避免只有时间没有日期）；时间按钮同步为「全天」。
- **交互**：移动端底部抽屉、桌面居中卡片；点按 ≥40px；Esc/遮罩关闭、焦点回归、Tab 收束、body 滚动锁恢复。
- **范围**：本轮仅任务截止日期；提醒「指定时间」仍原生 datetime-local，班级作业/通知管理/投票截止不动。
- **测试**：`task_check.py` **147/147**（日期入口/默认今天/日历直接选日/快捷明天/隐藏值+按钮/翻月/清除/
  快速添加 dueTime/编辑器回填/日期快捷同步）；cloud 8/8、live 5/5；`v2_ui` 27/27、`optim_v2` GREEN、
  overflow 390/430=0、0 JS/console/外部请求。
- **上线**：**1,650,927 B / sha256 `1fa1cd7b3b9175d6cb1c598914ce25c3c1ffe50ee4fa0f8b4b8d5d807b095bf9`**
  （OSS/IP 同字节；gzip **498,678 B**）；部署前备份
  `tools/_backup/index_online_20261122-1900_preDatePicker.html`（1,635,198 B / `ddc205a3…`）。
- **回滚**：重传上述备份；无 DB 变更。

## 2026-11-22 18:1x–18:4x · 任务时间选择器优化（网页端）

> 用户需求：「优化时间选择功能」。

- **任务截止时间改为专用选择面板**：快速添加截止时间和详细编辑截止时间都不再直接弹原生 `time`；
  隐藏的原生 `time` 输入保留为值源（兼容旧代码/测试），可见的是时钟按钮 + 当前时间/「全天」。
- **面板能力**：常用时间 chips（08:00 / 12:00 / 14:00 / 18:00 / 20:00 / 22:00 / 23:59）、00–23 小时网格、
  05 分钟步进网格、直接输入 `HH:MM`/`2030`（自动归一）、实时预览、全天（清空时间）、取消/确定；
  移动端底部抽屉，桌面居中卡片；点按 ≥40px；Esc/遮罩关闭、焦点回归、Tab 收束、body 滚动锁恢复。
- **联动**：快速添加带日期+时间保存后 `dueTime` 正确；编辑已有时间回填；清除日期/快速添加重置同步按钮；
  `taskTimeOk`/提醒计算/ICS/导出数据格式不变，无数据结构变更。
- **范围**：本轮优化任务截止时间；提醒「指定时间」仍用原生 `datetime-local`，班级作业发布时间/通知管理/
  投票截止等仍为原生日期时间控件，未改动（避免扩大改动面）。
- **测试**：`task_check.py` **138/138**（时间面板打开/小时分钟/预览/隐藏值/按钮回显/直接输入/全天清空/
  快速添加 dueTime/编辑器回填）；`task_cloud_check.py` 8/8、`task_cloud_live_check.py` 5/5；
  回归 `v2_ui` 27/27、`optim_v2` GREEN、overflow 390/430=0、0 JS/console/外部请求。
- **上线**：**1,635,198 B / sha256 `ddc205a3b78236f8cda0a82c3a265f3d1970efcdfc663fd0bb48dc2c475396eb`**
  （OSS/IP 同字节；gzip **495,364 B**）；部署前备份
  `tools/_backup/index_online_20261122-1820_preTimePicker.html`（1,619,514 B / `25b878ec…`）。
- **回滚**：重传上述备份；无 DB 变更。



> 用户需求：「把默认分组『任务』移除，允许任务不归属任何分组，同时不限制附件大小，同样做好预览等功能，同时也允许将通知添加到任务中」。

- **默认分组移除**：任务默认 `lists:[]`；`inbox` 分组从数据中删除，旧任务 `list:"inbox"` 迁移为 `""`（未分组）；
  侧栏不再出现默认「任务」分组，任务行不再显示空的未分组 chip；编辑器/快速添加分组下拉首项为「未分组」。
  分组删除后任务移入未分组；新建分组仍立即有删除/拖动入口。
- **任务附件取消人为大小限制**：小文件（≤480KB）继续内嵌 base64，**大文件原始 Blob 存 IndexedDB**
  （`zq_task_files_v1`，任务 JSON 只存 id/名称/类型/大小），不压缩、不设 MB/KB 上限；受浏览器配额限制，
  失败提示不静默。任务附件仍最多 2 个、仍只本机（不随 taskdata 上云）。
- **预览**：图片/PDF/文本/视频/音频内联预览，其他类型下载；文本仅预览前 200KB，完整下载；任务卡片缩略图支持
  IndexedDB Blob；附件删除在保存时清理，取消编辑不误删原附件。
- **通知加入任务**：通知 iframe 每张卡片注入「加入任务」按钮（MutationObserver 跟随模板重绘）；
  标题/摘要/正文/分类/截止时间带入任务，写入 `sourceNoticeId`/`sourceTitle`；任务详情显示「来自班级通知」+「查看」，
  点「查看」回通知页定位卡片；同一通知防重复，按钮变「已在任务」。
- **数据**：任务新增 `sourceNoticeId`；`taskdata` 云端同步仍只同步任务元数据（附件不上云）；无新 DB/表变更，
  userdata v6 不变；APP_VER 仍 2.0.0。
- **测试**：`task_check.py` **128/128**（新增未分组默认/迁移、快速添加未分组、编辑器未分组、班级作业转入未分组、
  通知按钮/加入/来源/防重复、附件大文件不限制/预览）；`task_cloud_check.py` **8/8**；`task_cloud_live_check.py`
  **5/5**；另用真实 headless Edge（CDP、非虚拟时间）验证 2MB 文件写入 IndexedDB 并出卡片/预览；回归
  `v2_ui` 27/27、`overflow 390/430`=0、`optim_v2` GREEN、0 JS/console/外部请求。
- **上线**：网页 **1,619,514 B / sha256 `25b878ecdbba070fe16f38cd3f15bfb5503fec37dd0ca367f14c58eb7e740029`**
  （OSS 同字节；ECS/IP HTTP 200 同字节；gzip 492,200 B）；部署前 HEAD 备份
  `tools/_backup/index_online_20261122-1735_preTaskUngrouped.html`（1,605,566 B / `7753dae…`）。
- **回滚**：重传上述 HEAD 备份 → 两条部署命令（会回到含通知管理的上一版）；无 DB 回滚。
- **已知取舍**：任务附件仍限 2 个且仅本机（IndexedDB 清站点数据会丢失大文件）；班级作业附件仍走云端 base64
  上限（不适用于本轮任务附件）；通知附件不复制，只带文字/截止；任务同步仍整快照 LWW。

## 2026-11-22 16:3x–16:5x · 拖动让位动画 + 新分组删除按钮 + 任务云端同步（网页端）

> 用户需求：「调整顺序要有对应的让位动画，同时我发现分组新建后无删除按钮，且无法调整顺序，同时把任务模块同步至云端」。

- **让位动画**：`tkFlipMove` 用 FLIP + WAAPI（190ms）让非拖动条目让位；左侧视图/分组与任务行共用，
  `prefers-reduced-motion` 时直接移动；重复拖动先 finish 旧动画。
- **分组删除**：非收件箱分组行新增删除按钮（`data-tkgdel`），点击确认后任务移回「任务」并删除分组；
  弹层删除复用同一逻辑。**新建分组后立即有删除按钮和拖动把手**。
- **任务云端同步（新表 public.taskdata）**：迁移 `deploy/cloudbase/2026-11-22_taskdata.sql` 已应用；
  RLS 仅本人行、anon SELECT/INSERT/UPDATE；**不增加 userdata v6 section**，不影响其它端/现有同步契约。
  `TASKSYNC`：`task.updatedAt` 版本、首次合并、之后整快照 LWW、先 GET 再 POST、删除最后任务/分组可推空快照；
  `#tkCloud` 状态（已同步/同步中…/仅本机/待保存）；任务附件不上云（本机保留，按 task id 回填）。
- **数据**：任务新增 `updatedAt`；仅新表，无其它 DB/接口/账号变更；APP_VER 仍 2.0.0。
- **测试**：`task_check.py` **116/116**（新增 FLIP 动画断言、新分组删除/把手）；`task_cloud_check.py` **8/8**
  （mock 首次合并/附件保留/推送不含附件/新任务自动推送）；`task_cloud_live_check.py` **5/5**
  （真实 CloudBase 本人 GET/RLS/POST/回读/清理，仅测试身份）；回归 `v2_ui` 27/27、`overflow 390/430`=0、
  `optim_v2` GREEN、0 JS/console/外部请求。
- **上线**：网页 **1,565,408 B / sha256 `9de65e9fe7746175abc4061988c2a1834d392247c8971a83bfc4316eab7427d1`**
  （OSS check MATCH；ECS 文件与 IP 同字节；gzip 477,581 B；`http://121.196.47.2/` HTTP 200 同字节同 sha）；
  部署前备份 `tools/_backup/index_online_20261122-1642_preTaskSync.html`（1,555,246 B / `63aa2874…`）。
- **回滚**：重传备份 → 两条部署命令；DB 回滚 `DROP TABLE IF EXISTS public.taskdata;`（本地任务不受影响）。
- **已知取舍**：任务同步仅网页端；整快照 LWW（同时改不同任务可能后写覆盖，无逐条 tombstone）；任务附件不上云；
  首次无基线为合并，删除可能被另一端旧副本短暂恢复；同步失败降级「仅本机」。

## 2026-11-22 16:1x–16:3x · 左侧栏目 + 任务拖动排序（网页端）

> 用户需求：「允许对右侧栏目的拖动调整顺序，同时对任务也进行处理」；随后明确「我指的是左侧栏目要支持拖动改变顺序」。

- **左侧「视图」拖动排序**：5 个智能列表加六点把手，Pointer Events 拖动；顺序写 `zq_task_ui_v1.smartOrder`
  （本机 UI 偏好，不跨端、不进 UD），未知/缺失 key 自动过滤/补齐。
- **左侧「分组」拖动排序**：用户分组加把手（收件箱「任务」固定第一）；拖完写回 `task.lists[].order` 并
  `D.save()`；`taskNormData` 加载时按 order 排、收件箱强制第一。
- **任务行拖动排序**：未完成行左侧加把手；默认排序、无搜索、非计划中/已完成时可拖；其他排序下把手变淡并提示。
  松手把当前可见未完成任务的旧 `order` 槽位升序重分配（隐藏任务保留原 order），保存并重绘。
- **交互**：click 拦截把手避免拖后误开任务/切视图；拖动中行 `pointer-events:none`；视口上下 60px 自动滚动；
  `body.tk-sorting` 禁选中；移动端 chip inline-flex，390px 无横向溢出。
- **数据**：智能列表顺序只在 `zq_task_ui_v1`；分组/任务顺序在既有本机任务数据；**UD v6 未改**、无 DB/表/接口变更；
  APP_VER 仍 2.0.0。
- **测试**：`tools/tests/task_check.py` **114/114**（新增任务/视图/分组拖动改序与保存断言；原 108 项保留）；
  回归 `v2_ui_check` 27/27、`overflow 390/430` overflow=0、`optim_v2_check` GREEN；`perf 45/63`、`sync 91/99`
  与 HEAD 基线一致。
- **上线**：网页 **1,555,246 B / sha256 `63aa2874a912089edd93bb42f8e27cb7f98f861d0b39b1823aca012343be776f`**
  （OSS check MATCH / ECS verify MATCH；gzip 474,441 B；`http://121.196.47.2/` HTTP 200 同字节同 sha）；
  部署前线上备份 `tools/_backup/index_online_20261122-1628_preDrag.html`（1,544,842 B / `34e72d10…`）。
- **回滚**：重传备份 → `python deploy/sync_tools.py index.html` + `python deploy/ecs_site.py apply`。
- **已知取舍**：拖动顺序仅本机；完成区任务不能拖；计划中/截止/创建/重要排序下不能拖；无撤销；收件箱固定第一；
  移动端横向 chip 跨行拖动以指针所在行为准。

## 2026-11-22 15:0x–16:0x · 任务第二轮：班级作业直接加入任务 + 附件系统 v2 + 详细编辑/提示（网页端）

> 用户原话：「允许将班级作业直接直接添加至任务，同时优化附件上传系统，优化详细编辑的方式和提示」。

- **班级作业 → 任务**：班级列表每项新增「加入任务」，班级头新增「加入任务」批量（只取未完成、已关联跳过）；
  生成任务带 `sourceHwId/sourceTitle` + 标题/备注/截止/标签。**不复制班级附件**，任务详情显示「来自班级作业」
  来源块（内容、原附件按钮、定位回班级并高亮）；已关联的班级项显示「已在任务」，删除任务后恢复可添加。
- **附件系统 v2（核心修复）**：修正 `attRenderEditor` 的 DOM id 映射（旧代码找 `hwFilesList`，实际是
  `hFilesList`，导致上传只计数不显示卡片、点击拖拽区也不弹文件选择）；作业/任务统一为拖拽区 + 缩略图/文件卡 +
  移除 + `n/2` 计数 + 状态提示；支持点击/键盘/拖入/粘贴图片；图片优先 `URL.createObjectURL` + canvas 压缩
  （白底，避免透明 PNG 变黑），非图片优先 `file.arrayBuffer()`；`ATT_ACTIVE` 持有解码对象、12s 超时回退
  FileReader，失败回收 busy；`ATT_SESSION` 防止关闭弹层后迟到的上传写回新会话。
- **额度**：作业沿用 2 个/图片原图 5MB/文件 2MB；任务 2 个/图片压缩到约 300K base64/文件 320KB/单任务总
  base64 ≤700K + 本机 `JSON.stringify(D.d)+新增 ≤4.1M` 预算，防 localStorage 爆掉。任务附件只存本机。
- **详细编辑**：快速添加旁新增「详细编辑」（`#tkQuickMore`），预填标题/截止/分组/重要；详情分
  步骤/备注/时间/组织/附件/来源；日期快捷 今天/明天/下周一/清除；提醒/重复实时提示（预计提醒时间、完成后
  创建下一次）、备注字数、步骤进度；空标题/日期/提醒/分组行内错误并聚焦字段；底部「未保存」指示 + 关闭
  `confirm` 拦截；保留 `Ctrl/⌘+Enter` 保存。
- **数据**：任务条目新增 `attachments`（JSON 字符串，≤2）、`sourceHwId`、`sourceTitle`；`taskNormItem()`
  归一/限幅；**未改 userdata v6**（任务/附件仍不跨端）；**无 DB/表/接口/账号变更**；APP_VER 仍 2.0.0。
- **测试**：`tools/tests/task_check.py` 扩到 **108/108**（新增逐项/批量加入、来源附件预览/定位高亮、拖拽/文件选择/
  图片压缩、超限/大文件/类型拦截、任务附件持久化/重开/移除、详细编辑预填/日期快捷/提醒提示/空标题行内错误/
  未保存拦截/取消不新增）；回归 `optim_v1_check` GREEN、`optim_v2_check` GREEN、`v2_drag_check` 69/69、
  `v2_ui_check` 27/27、`v2_web_reminder_check` 37/37、`v2_pos_restore_check` 12/12、`overflow_check 430`
  overflow=0、`export_check hw` 出图正常；`perf_check` 45/63、`sync_check` 91/99 与 HEAD 基线一致。
- **上线**：网页 **1,544,842 B / sha256 `34e72d108a24d271c8d174195ef486195873a7f61a50ed8ff7fecc04edd8c84c`**
  （OSS check MATCH / ECS verify MATCH；gzip 471,864 B；`http://121.196.47.2/` HTTP 200 同字节同 sha）；
  部署前线上备份 `tools/_backup/index_online_20261122-1534_preTaskV2.html`（1,508,419 B / `47522baf…`）。
- **回滚**：重传上述备份 → `python deploy/sync_tools.py index.html` + `python deploy/ecs_site.py apply`。
- **已知取舍**：任务附件仅本机；来源附件在班级作业被删除后不可预览；批量加入不复制附件；粘贴只在任务/作业
  弹层打开时生效；移动端以点击选择为主（拖拽桌面优先）；附件上限见上。

## 2026-11-22 08:3x–09:2x · 作业工具升级「任务」：个人任务 + 分组 + 提醒 + 班级作业自动同步（网页端）

> 用户原话：「升级作业工具为任务功能，在保留自动更新班级作业的基础上仿照市面上类似 Microsoft To Do
> 以及 GitHub 上类似项目，做到完全的个人任务创建、分组分类、提醒等等类似项目所具有功能的系统，先从网页端做起」。

- **网页**（`tools/index.html` 新增任务块，APP_VER 仍 2.0.0、单文件零依赖、零外部请求）：
  - `TOOLS` 的 `hw` 显示名改为「任务」（key 不变，保住 homeTools/拖动/历史/旧测试选择器）；
  - `#s-hw` = 「我的任务 / 班级作业」两段；个人任务区左侧智能列表（我的一天/重要/计划中/全部/已完成）+
    分组（新建/重命名/删除/颜色），右侧快速添加 + 任务列表 + 已完成折叠；手机端左栏换行 chip；
  - 任务终态编辑（标题/备注/截止日期时间/提醒/重复/分组/标签/步骤/我的一天/重要）、完成/撤销、
    重复任务下一次、搜索/排序/计数/空态；桌面 1280 与 390px 真视口无横向溢出、深色主题适配；
  - 提醒：20s 页内调度 + 可见时补查；横幅（完成/稍后 10 分钟/关闭）+ 浏览器 Notification（需授权）；
    提醒设置（状态/授权/测试/提示音/默认提醒）；关闭页面后不提醒，提供 ICS 导出写入系统日历；
  - 导出：`exportCard()` 任务图片、JSON 备份/恢复（合并）、ICS（VEVENT/VALARM/CRLF/75 字节折行）；
  - 班级作业保留 `#hPub/#hImg/#hClean/#hSyncSt/#hList` 原 ID/原行为；`renderHW` 钩子只加任务角标与
    自动分段；`hwMeta` 合并班级未完成 + 个人任务摘要。
- **数据**：`D.d.task={v:1,lists,items,prefs}` 随 `zq_tools_v2_<sid>` 本机保存；`taskNormData()` 归一/限幅；
  **未改 userdata v6**（个人任务暂不跨端；跨端需先改 UD 契约并征得用户同意）；无 DB/表/接口变更。
- **测试**：新增 `tools/tests/task_check.py`（mock 云端 + 测试身份 3260799999）**72/72**，覆盖快速添加/终态编辑/
  重复完成撤销/分组增删改/搜索标签/提醒稍后完成/ICS/图片/JSON 恢复/班级 marks/无个人任务时自动落班级段/
  390px iframe 无溢出/390px 编辑器首屏保存键/0 报错/0 外部请求；回归 `optim_v1_check` GREEN、`optim_v2_check` GREEN、
  `v2_drag_check` 69/69、`v2_ui_check` 27/27、`v2_web_reminder_check` 37/37、`v2_pos_restore_check` 12/12、
  `overflow_check 430` overflow=0、`export_check hw` 出图正常；`perf_check` 45/63、`sync_check` 91/99 与 HEAD 基线一致；
  `v2_sync_check` 的 11/12 在 HEAD 副本同样复现（通知 iframe frameDoc 为空，非本次引入）。
- **上线**：网页 **1,508,419 B / sha256 `47522baf9c9cab4ff6d890f2b11d50589dd63f8c49ae8641c4677fcc10616249`**
  （OSS check MATCH / ECS verify MATCH；gzip 462,207 B；`http://121.196.47.2/` HTTP 200 1,508,419 B）；
  部署前线上备份 `tools/_backup/index_online_20261122-0904_preTask.html`（1,396,936 B / `e7ef5bb8…`，= 部署前 HEAD 字节）。
  **无 DB / 表 / 接口 / 账号变更**。
- **回滚**：重传上述备份 → `python deploy/sync_tools.py index.html` + `python deploy/ecs_site.py apply`。
- **已知取舍**：个人任务默认本机不跨端；提醒只在网页打开时生效（另有 ICS）；分组/任务无拖拽排序；
  班级作业与个人任务分栏不混排；老 `#h*` ID 保留不可删。

## 2026-11-22 08:0x–08:4x · 修复「11-22 12:00 前进打卡群」上下文断裂：进群补充并回龙狮活动卡 + 报名截止后不再整卡提前过期（数据已同步云端，网页模板未变无需重发）

> 用户反馈：「我发现11月22日（今天） 12:00 前进打卡群的上下文联系有问题」。
> 现象：主列表里只有一张标题为「11月22日（今天） 12:00 前进打卡群」的卡（分类班级事务、动作写成「报名截止」），不知道属于哪个活动、也没有它说的二维码；真正的活动卡「龙狮系列主题活动」已在「已截止」里。

- **根因（三处叠加）**：① 同一条 QQ 合并转发（「翰墨腾龙韵，巧手叙狮欢」系列 + 策划书 PDF + 一条补充说明 + 3 张群二维码图片）被 AI 聚类拆成两张卡：活动正文+附件+三张二维码一类，「成功报名的同学加入对应的二维码，在11月22日12点之前进群，到点即锁群」单独一类；② `redistribute_images` 把图片都挂到了有附件的活动卡，补充卡只剩一句没有上下文的文字；③ 活动卡报名 11-21 22:00 截止，状态机「报名截止优先」→ 整卡判成已截止移出主列表（可活动 11-22 才开始、11-25 还要交作品）。
- **合并（`build_notice_board.expand_merged` 新增 `_merge_supplement_clusters`）**：同记录里恰好只有一条「活动主体」聚类时，把「成功报名/报名成功/扫码/二维码/进群/入群/锁群」这类单条短文本、自身无附件图片、且不含活动主体信息（活动时间/对象/内容/报名方式/子活动…）的补充片段并进活动卡，条目标「补充通知」（卡片标「已更新」）；有多个活动主体聚类时保守跳过。`ai_merged.py` prompt 同步增补「报名成功后扫码/加群/锁群 + 群二维码必须与所属活动同组，不能单独成卡」。
- **报名截止后不整卡提前过期（新增 `_drop_passed_signup_end`）**：`signupEnd` 已过、但还有更晚的 `deadline` 时，去掉已过的 `signupEnd`（三端契约「只有 signupStart 且已开始 → 退回截止/活动时间」），并让 `expireAt` 不早于该截止；报名窗口仍留在摘要/要点/分段里。没有更晚截止的卡（讲座/比赛/名单）仍按契约进已截止区；多报名窗口（`signupWindows`）不动。**同类的「11-20 手绘器械征集报名」也随之从已截止回到主列表（作品提交 11-22 23:00 前）**。
- **人工补丁（`C:\briefdesk\data\notice-manual-patches.json`）**：该记录加两条——`g_qqm_7709544715184408061_c1` `mergeInto` 主活动卡 + 目标卡 `set`（摘要/要点/分段写明 11-22 12:00 前扫码进群、到点锁群、11-25 23:00 前交作品；主截止=作品提交 11-25 23:00 提交截止、`signupEnd=null`、`expireAt=11-25 23:00`、保留 11-21 18:00-22:00 报名窗口在分段）。
- **数据结果（本地 + 云端）**：合并后 112 组；该活动 1 张卡 `g_qqm_7709544715184408061_c0`（cat=活动，items=策划书 PDF + 活动正文 + 补充通知 + 3 张群二维码），摘要「11-22至11-25线上龙狮书法打卡；成功报名者11-22 12:00前扫码进群，11-25 23:00前交作品。」；主列表 chip「4 天后 提交截止」、正文含 11-22 12:00 扫码进群与三张二维码；旧卡 `auto_…_c1` 已归档。`sync_notices_cloud` 112/112，测试身份只读核验通过。`index.html` 未改字节，无需 OSS/ECS 重发；小程序/安卓读同一字段，无需改客户端。
- **测试**：新增 `tools/tests/v2_notice_qrgroup_check.py` **17/17**（数据 10 项含「无『时间+进群/锁群』孤立卡」通用守卫 + 真实模板 430px 渲染：主列表/「扫码进群」可见/3 张二维码/0 JS 报错/截图 `_v2_notice_reports/qrgroup_card.png`）；`briefdesk/tests/test_build_normalize.py` 增补 §3.11 补充片段合并、§3.12 报名截止后跟踪更晚截止 → **88 PASS / 12 FAIL**（12 项为既有 §5 身份夹具缺失）；回归 `v2_notice_slowrun_check 16/16`、`v2_notice_longterm_check 27/27`、`v2_notice_period_check 53/53`、`v2_notice_publish_check 20/20`、`v2_notice_data_check 27/27`、`v2_notice_dynamic_cat_check 18/18`、`v2_notice_live_check 20/20`、`v2_notice_fix_check 11/11`（`v2_notice_time_check` 为 11-05 固定时间线的历史验收脚本，本次仍 34/69：花名册/药膳 c1/献血组等夹具已过期、`g_qqimg_152d0abee7` 的「班级收取」动作来自更早的人工补丁，均与本次无关）。
- **回滚**：还原 `build_notice_board.py` 的 `_merge_supplement_clusters` / `_drop_passed_signup_end` / `expand_merged` supplement 标记与 `ai_merged.py` prompt；删除人工补丁里 `g_qqm_7709544715184408061` 两条；重建 board + `sync_notices_cloud.py`。网页无字节变更。

## 2026-11-22 07:2x–07:3x · 网页端「OPPO / 鸿蒙」扫码登录（账号服务 v1.2 + 手机确认页；方案 D 第一阶段）

> 用户要求：「尝试在网页端增加 oppo 和鸿蒙扫码一键登录」。已与用户确认方案 D：先把网页扫码链路做完并可测，
> 二维码预留原生 App 接管位；App 侧后续接入即可升级为真 OPPO/华为账号一键登录。

- **网页**（`tools/index.html`，`__QR_LOGIN_V1__`，APP_VER 仍 2.0.0）：身份页「进入班级」下方新增「或 · 扫码登录」；
  扫码弹层（OPPO/鸿蒙分段、内置 `qrGen` 生成二维码、等待/已确认/已取消/已过期/服务不可用状态、刷新、Esc/遮罩关闭、
  成功自动进入班级、过期自动换票、关闭即停轮询）；手机确认页（`#qr=<t>&p=oppo|harmony`，读后立即清 hash；
  已登录一键确认，未登录学号+姓名，401 回退表单，无效二维码错误页）；暗色主题与 360/430px 无溢出。
- **ECS 账号服务 v1.2**（`deploy/account_app.py`）：新增 `POST /qr/create`、`GET /qr/poll`、
  `POST /qr/authorize`、`POST /qr/deny`；票据 128-bit、TTL 180s、纯内存（上限 2000）、一次性轮询密钥；
  授权时 `class_whoami` + `class_verify` 另签 30 天 token（含 role/badge/is_admin），**不向手机返回 token/openid**；
  `/qr/*` 带 CORS（无 Cookie）与 OPTIONS；建票 12/分、轮询 240/分、授权 30/分/IP；日志不打印 t/k/token。
- **契约/文档**：`docs/QR_LOGIN_CONTRACT.md`（URL/API/安全/App 接管位/已知限制/回滚）。
- **测试**：`tools/tests/v2_qr_login_check.py` **34/34**（headless Edge + CDP，mock 云端，0 外部请求：入口/二维码像素/
  OPPO↔鸿蒙切换/轮询成功入班/停止轮询/关层停轮询/过期换票/服务不可用/手机已登录一键确认/学号+姓名/401 回退/无效二维码/
  无溢出/0 JS 报错）；`deploy/tests/test_account_qr.py` **12 passed**（票据格式/错误 k/过期/幂等/CORS/限频/内存上限）。
  线上实测（测试身份 3260799999）：真实 ECS 服务 + 真实浏览器，桌面扫码→手机确认→桌面拿到 64 位 token。
- **上线**：账号服务 v1.2 已部署（`/account/__health` = `{version:"1.2",qr:true,qrTtl:180}`）；
  网页 **1,396,970 B / sha256 `0325a8a4cd1e31f547e9b60b91947defc494a03bbd8e34444cf79137dd8e96cb`**
  （OSS check MATCH / ECS MATCH；gzip 433,152B）。备份 `tools/_backup/index_online_20261122-0735_preQR.html`
  （1,374,596 B / `f224dce7…`）。
- **如实限制**：本轮手机端「OPPO/鸿蒙」只是生态标签，确认仍用班级身份；OPPO 账号服务实测仍 `invalid_client`；
  OPPO 无官方网页扫码，华为 Account Kit 官方扫码授权需 AGC `client_secret` 与能力申请，均未接入（App 接管位见契约 §7）。
- **回滚**：重传上述备份并 `ecs_site.py apply`；账号服务回退到 v1.1 后 `ecs_account.py deploy`；无 SQL 变更。

## 2026-11-21 21:3x–21:4x · 修复冬季傍晚慢跑打卡活动被判长期通知：限期活动合并成一张卡并展示报名开始/报满即止（数据已同步云端，网页模板未变无需重发）

> 用户反馈：「修复将冬季傍晚慢跑打卡活动识别成长期通知的问题，实际该内容也为活动之一，需要报名，通知内应该展示的是活动报名开始和截止时间」。
> 已确认口径：原文只写「报名时间：2026年11月16日17:00」+「报名时间结束即止/报满即止」，没有明确报名截止 → 只展示报名开始 11-16 17:00 并写明「报满即止」，不虚构截止时间；两张重复卡合并为一张。

- **根因（三处叠加）**：① AI 聚类把同一活动的「活动介绍全文」与「补报名 + 策划书附件」拆成两张卡，介绍卡没有报名信息；② 介绍卡里「11-16 至 11-27 每日 17:00-20:00」被 AI 质检判成 `recurrence(daily, until 11-27)`，`recurrence` 在状态机里优先 → 卡片进「长期通知」且 `actionable=false`；③ 上一轮的人工补丁按旧组 id/标题「屏山慢跑打卡」写的，重组后匹配不到 → 旧修正静默失效。
- **合并（`build_notice_board.expand_merged` + `ai_merged.merge_same_activity`，同口径）**：同一条合并转发记录里标题同主题的聚类合并成一张卡（标题归一化公共前缀 ≥6 字且占较长标题 ≥70%，如「冬季慢跑打卡活动报名」/「…介绍」），indexes/points 取并集；「子活动一/二/三」这类短公共前缀不合并。合并后该活动只剩 1 张卡（补报名原文 + 活动全文 + 策划书附件）。
- **限期活动不是长期安排（`build_notice_board.resolve_recurrence_conflicts` 新增确定性规则）**：`recurrence` + 正文显式起止日期 + 活动语义 → 限期活动：`eventAt`=活动期首日+每日时段起点、`expireAt`=末日+时段终点，移除 `recurrence` 并恢复 `actionable`。反向保护：只有周期表述、没有活动起止日期的真长期安排（军训请假每日 7:30、每月前三周卫生检查）保持不变；「请假/报备/检查/值班/考勤」类不因正文顺带提到日期区间而降级。
- **AI 提示词（`ai_quality.py` / `ai_brief.py`）**：「报名时间：<日期 时间>」没有「前/截止」字样是**报名开始**；只有「报满即止」时 `signupEnd`/`deadline` 必须留 null、不得编造；限期活动必须 eventAt/expireAt 表达并给出慢跑打卡的例子。本次不改 `CACHE_VER`（只有内容变化的组重算，分类另由 builder 确定性规则兜底，避免在活跃板上整体重算抖动）。
- **人工补丁（`C:\briefdesk\data\notice-manual-patches.json`）**：替换旧「屏山慢跑打卡」条目——合并重复组的 `mergeInto` + 目标卡 `set`（`signupStart=2026-11-16T17:00`、`signupEnd/deadline/deadlineAction=null`、`eventAt=11-16T17:00`+`eventAction=报名开始`、`expireAt=2026-11-27T20:00`、`actionable=true`、摘要/要点/分段含「报名 11-16 17:00 起、报满即止、11-17 屏山补报名」）。补丁 `set` 新增 `null=删除字段`（时间字段同样适用），避免 AI 再写回推断的报名截止。
- **数据结果（本地 + 云端）**：该组 1 张卡；`recurrence=null`、`signupStart=11-16T17:00`、`signupEnd/deadline=null`、`eventAt=11-16T17:00 报名开始`、`expireAt=11-27T20:00`、`actionable=true`；卡片在主列表 chip「11月16日（本周一） 17:00 报名开始」，正文含报名/报满即止；长期通知计数不再含该组（仅军训请假与宿舍卫生检查两条真周期安排）。`sync_notices_cloud` 已推云端（`auto_g_qqm_7708988868871074939_c0` 未归档；旧的 `…_c1`、`auto_g_qqm_7707958493357894546_c0` 已归档；测试身份只读核验通过）。`index.html` 模板未改，**无需 OSS/ECS 重发**；小程序/安卓读同一字段，无需改客户端。
- **测试**：新增 `tools/tests/v2_notice_slowrun_check.py` 重写为当前回归 **16/16**（数据 9 项含「无『限期活动+长期安排』并存组」通用守卫 + 真实模板 430px 渲染 chip/主列表/长期计数/0 JS 报错）；`briefdesk/tests/test_build_normalize.py` 新增 §3.8 限期活动、§3.9 补丁 null=删除、§3.10 聚类合并共 14 项 → **76 PASS / 12 FAIL**（12 项为改动前既有的 §5 身份夹具缺失，非本次引入）；回归 `v2_notice_longterm_check 27/27`、`v2_notice_period_check 53/53`、`v2_notice_publish_check 20/20`、`v2_notice_data_check 27/27`、`v2_notice_dynamic_cat_check 18/18`、`v2_notice_live_check 20/20`、`v2_notice_fix_check 11/11`；`v2_notice_quality_check 12/20`（8 项为改动前既有：河洛夜市/小儿体质夹具组已过期下线，原 builder 同样 12/20）。
- **回滚**：还原 `build_notice_board.py` 的 `_merge_similar_clusters`/`_recurrence_to_period_activity`/补丁 null 语义与 `ai_merged.py` 合并规则；删掉人工补丁里的慢跑条目（旧的 `g_qqm_7707958493357894546_c0` 补丁如需恢复从本机历史取）；重建 board + `sync_notices_cloud.py` 即可回滚云端数据。网页无字节变更。

## 2026-11-21 13:0x · 电费「上次充值」改为跨区间查找并显示充值量（已上线 OSS+ECS）

> 用户要求：「修复电费上次充值只会在选择区间内查找的问题，同时优化安卓端的电费曲线，上次充值应该改为显示上次的充值量」；随后要求全部端同步修复。

- **网页 `tools/index.html`**：新增 `POWER.lastRecharge(pts)`（按 t 升序取最后一次 `Δq>0.05`，返回 `{t,reset,delta}`）；tile4「上次充值」优先取 **30d 全量历史**（云端 `power_history` 仅保留 30 天）的最后一次上升，慢频房取 `slowStats.lastRecharge`，30d 缺失才回退所选区间 `lastUp`；显示值改为 `+delta` 度（充值量），不再显示充值后余额 `reset`；切 24h/7d/30d 值不变。
- **取数**：`pull` 恒定拉 24h+7d+30d（实时房由 2 个历史请求变 3 个，5 分钟缓存/在途去重不变）；`loadHist` 同样补 30d。
- **验证**：`power_check.py` **155/155**、`v2_power_cadence_check.py` **84/84**、`v2_power_detail_check.py` 30、`v2_power_trend_compare_check.py` 38、`v2_orient_power_check.py` 33、`v2_power_pick_mem_check.py` 48、`v2_power_sync_hardening_check.py` 29、`v2_power_tip_fixed_check.py` 25；`v2_power_slow_check.py` 44/45（C5 为改动前既有失败，HEAD 同样失败）。
- **上线**：`index.html` **1,374,596 B / sha256 `f224dce7458c6a12b1db7693e350af381858439aab9da661394f68f7f248dacf`**；OSS `check` MATCH、ECS `/` 同字节（gzip 427,473 B）。部署前备份 `tools/_backup/index_online_20261121-1307_prePowerRecharge.html`（1,372,939 B / `effa33de…`）。
- **回滚**：`python deploy/oss_object.py get tools/_backup/index_online_20261121-1307_prePowerRecharge.html index.html` 后重跑 `sync_tools.py` + `ecs_site.py apply`。

## 2026-11-20 22:1x · 账号服务 v1.1（荣耀）+ vivo 推送发送器 + provider 约束放开 + OPPO 推送调度补挂

> 用户要求：按 `honorid-opensdk` 接入荣耀账号 OAuth；按 AppID/AppKey/AppSecret 接入 vivo 推送；再次检查 OPPO 账号服务与推送。

- **ECS 账号服务** `deploy/account_app.py` v1.1：新增 `POST /honor/{login,bind,unbind}`、`GET /honor/bindings`；
  荣耀 authCode → `https://hnoauth-login.cloud.honor.com/oauth2/v3/token`（form：grant_type/code/client_id/client_secret/redirect_uri）
  → `https://account-drcn.platform.hihonorcloud.com/rest.php?nsp_svc=GOpen.User.getInfo` 取 `openID/displayName`；
  `/__health` 增加 `providers:{oppo,honor}`。已用云助手部署（`ecs_account.py`，含 `honor-account.json`），
  公网 `https://tool.furina.fun/account/__health` = `{ok:true,providers:{oppo:true,honor:true},version:"1.1"}`；
  无效 code 实测返回 `honor_exchange_failed / 1101/20152 invalid code`（说明凭证被接受）。
- **DB 迁移** `deploy/cloudbase/2026-11-20_push_vivo_account_honor.sql`（已应用）：
  `push_tokens.provider` 放开 `('oppo','harmony','vivo')`；`account_bindings.provider` 放开 `('oppo','honor')`（触发器仍按 provider 分别限 3）。
- **vivo 推送发送器** `briefdesk/scripts/vivo_push.py`：`/message/auth`（md5(appId+appKey+ts+appSecret)）+ `/message/send`；
  `skipType=4` intent URI 点击直达 MainActivity；水位/首轮基线/`--test/--notice/--dry-run/--auth`；真实凭证 `--auth` 成功。
- **OPPO 推送复核**：`oppo_push.py --auth` 成功；发现 `ClasstoolsPushWatch` 之前只跑鸿蒙 `push_tick.py`，OPPO/vivo 发送器**从未被调度** →
  新增 `briefdesk/scripts/push_tick_all.py`（harmony→oppo→vivo）并已把该任务指过去，实跑三脚本 exit=0。云端当前 0 台 OPPO token（无 ColorOS 真机登录）。
- **OPPO 账号复核（23:0x 按官方文档）**：官方《OPPO 账号OAuth授权SDK服务端API》(id=10155) 确认固定域 `https://api.uc.oppomobile.com/oauth2/token/token-code`、`{appKey,appSecret,code}`；用户提供的 `appServerSecret` 等于推送 MasterSecret（推送鉴权已通过），不是账号服务参数；用给定 appKey/appSecret + 无效 code 仍返回 `2020003 invalid_client` → **应用未在账号服务激活/未申请 openid 权限**（或 appSecret 非账号服务应用）。服务端已收敛为官方单域名，并给出明确提示；详见 android 仓 `docs/PUSH_ACCOUNT_RECHECK_20261120.md`。
- **OPPO 账号复核**：ECS 服务 configured=true，但账号服务 token 端点用现 appKey/appSecret（与推送同一套）+ 无效 code 返回
  `{"code":"2020003","message":"invalid_client"}`；同一套密钥在推送侧鉴权成功 → 账号服务 AppKey/AppSecret 是另一套或服务未开通。
  需在 OPPO 开放平台补账号服务凭证并在 `oppo-account.json` 更新；客户端已把 `invalid_client` 显示为可诊断文案。
- **回滚**：账号服务恢复上一版 `account_app.py` 重新 `ecs_account.py deploy`；DB 先删 `provider in ('vivo','honor')` 行再收紧 CHECK；
  vivo 发送器改名/删除 `vivo-push.json` 即安全跳过；推送任务可指回 `harmony-class-tools/scripts/push_tick.py`。

## 2026-11-18 22:3x–22:4x · 统计排序改为「访问次数优先，次数相同按最近访问」（网页已上线；小程序/安卓/Windows 源码同步）

> 用户原话：「把排序设成访问次数排序优先，访问次数相同时按访问时间排序」。唯一契约 `《统计多端·最新登录》契约（内部归档）`（§2 排序口径已更新）。

- **网页** `renderStats`：排序改为 `(b.n-a.n)||(b.last-a.last)`；标题/说明工具卡统一为「按访问次数排序（次数相同按最近访问）」；`stats_check.py` 断言改为 张三（2 次）→ 王五（1 次 12:00）→ 李四（1 次 10:42），**44/44**。
- **小程序**：`pages/stats` 排序 `count` → `lastTs`；WXML/工具描述/AI `getVisitStats` 同步；`unit.js` 统计页新增次数优先/同次数按最近访问用例。
- **Windows**：`VisitStats.Build` 改为 `Count` 降序 → `LastTs` 降序；新增同次数按最近访问单测，`dotnet test 66/0`。
- **安卓**：`VisitStats.build` 改为 `count` → `lastTs`；`beta6/vc89`，`testDebugUnitTest 1629/0`（新增两组排序用例）。
- **回归**：网页 `v2_ui_check 27/27`、`v2_port_ui_check 80/80`、`v2_ug_check 56/56`、overflow 430=0；小程序 `ai_unit_account.js 41/0`，`unit.js 588 passed / 7 failed`（7 项为并行会话既有失败：合规域名/ko-link/draw/期次/发布，与本改动无关）。
- **上线**：`tools/index.html` **1,338,726 B / sha256 `d6a20cf9c2e6537bc65c0f7a574e1d6a7568910908fca081008a8aba1e4afc91`**；OSS `check` MATCH、ECS verify MATCH（gzip 414,999B）。部署前备份 `tools/_backup/index_online_20261118-2240_preCountSort.html`（1,338,669 B / `f6f85eb5…`）。
- **回滚**：重传备份 index；小程序/Windows/安卓回退上一版源码/安装包。

## 2026-11-18 22:0x · 仓库整理：五端一仓 + 一键双远端提交（无站点字节变更，不需部署）

> 用户要求：「gitee 和 github 仓库只要每个端口留一个即可，而不是按功能做仓库，并且每个端口都应该做好自动提交」。
> 同日补充：「不要设计划任务，删除相关脚本」。

- **五个端仓库**：`class-tools-site`（本仓）、`class-tools-android`、`class-tools-mp`、`class-tools-harmony`、`class-tools-windows`；不再按功能拆仓库。
- **并入**（保留完整历史）：`class-tools-briefdesk` → `web/briefdesk/`、`class-tools-power` → `web/power/`、`class-tools-mp-tests` → `mp-class-tools/tests/`；旧本地路径保留 junction（`briefdesk-plan` / `perfect-campus-power` / `mp-class-tools-tests`），旧仓库 GitHub 已归档。
- **同步工具**：五个端仓库根统一 `sync_repos.py` + `sync-repos.cmd`（自动识别双远端、敏感路径/令牌/大文件检查、远端领先自动 rebase、推两端并核对 SHA）。
- **不设后台任务**：**未添加计划任务、不跑守护脚本**（`ClassToolsRepoAutoSync` 已删除，`tools/repo_ops/` 已移除）；规则写进各仓 `AGENTS.md` 与工作区 `AGENTS.md`——改完由 agent 主动跑 `sync-repos.cmd`。
- **验证**：五仓 `sync-repos.cmd --check` 两端 SHA 一致；`node unit.js` 588/7（tests/ 误扫与相对路径问题已随本次修正；剩余 7 项为 11-14 撤销域名、今日 staging 路由与通知期次/发布逻辑的既有过期断言，需另行跟进）；`code_quality_check.js` 退出 0、`cloudfunctions/notify.test.js` 35/0。
- **回滚**：`git revert` 对应合并提交、旧仓库 `gh repo unarchive`；本机目录 junction 可用 `cmd /c rmdir <旧路径>` 删除。

## 2026-11-18 21:2x–21:4x · 统计多端：按最新登录排序 / 默认今天 / 分钟时间 / 记录登录端 / 忽略测试账号（网页已上线；小程序/安卓/Windows/鸿蒙源码同步）

> 用户原话：「将所有端的统计工具统一更新为按最新登录顺序排序，默认打开为今天，时间精确到分钟，记录具体登录端，忽略测试账号」。唯一契约 `《统计多端·最新登录》契约（内部归档）`。

- **数据**：`public.visits` 新增 `client text not null default ''`（web/mp/android/win/harmony；旧行为空显示「未记录」）+ `ts/slot` 索引；迁移 `deploy/cloudbase/2026-11-18_visits_client.sql` 已应用（CloudBase + ECS `class_tools`/`class_tools_cut` 三库同步）。旧客户端不传 client 仍可写。
- **网页 `tools/index.html`**：`visitLog` 写 `client:"web"`；统计查询改 `select=slot,sid,name,ts,client&order=ts.desc&limit=5000`；`renderStats` 按 `max(ts)` 倒序、时间显示 `MM/DD HH:mm`（旧行 ts=0 回退 slot 整点）、账号行显示端标签、过滤官方测试账号 `3260799999` 与 9999 段 10 位 QA 身份；每次进入统计页重置「今天」。
- **小程序**：`utils/cloud.js` 写 `client:"mp"`、`id=sid|slot|mp`、去重键按 `sid+端` 分开；`statsPull` 取 ts/client、limit 5000；`pages/stats` 默认今天/最近登录排序/分钟/端标签/忽略测试；AI `getVisitStats` 同口径。
- **Windows**：`VisitItem` 增 ts/client；`VisitsRepository` 按 ts 拉取并新增 `ReportAsync`（client=win，小时幂等）；`SessionService` 恢复/登录后 best-effort 上报；统计页默认今天、最近登录排序、分钟/端标签/忽略测试。
- **安卓**：新增 `VisitReporter`（client=android，小时幂等、失败静默），`AppContainer.updateActiveSession` 后 best-effort 上报；**同日追加**管理员统计页 `StatsScreen`（`beta5/vc88`，按最近登录/今天/分钟/端/过滤测试，入口仅管理员可见），`testDebugUnitTest 1627/0`，APK **5,804,121B / `6EE6E7AB078FB27A0E96A2B017153C3150057A1DF8294CB83AE794047E57EFB1…`**。
- **鸿蒙**：`VisitsReporter` 行增 `client:"harmony"`。
- **测试**：网页 `stats_check.py` **44/44**（默认今天/排序/分钟/端/旧行回退/测试过滤/client=web）、`v2_ui_check 27/27`、`v2_port_ui_check 80/80`、`v2_ug_check 56/56`、overflow 430=0；小程序 `unit.js 597/0`、`ai_unit_account.js 41/0`、staticcheck/code_quality 0；Windows/安卓/鸿蒙见各自仓库记录。
- **上线**：`tools/index.html` **1,338,669 B / sha256 `f6f85eb5fcfc8d67db099283808b040d6c8daa2f5b6c02a7c36433976f357f0b`**；OSS `check` MATCH、ECS verify MATCH（gzip 414,969B）。部署前备份 `tools/_backup/index_online_20261118-2135_preStatsLogin.html`（1,337,057 B / `139136c4…`）。
- **回滚**：重传备份 index；`visits.client` 可保留（旧客户端忽略），如需彻底回滚 `alter table public.visits drop column if exists client;`；小程序/安卓/Windows/鸿蒙回退源码/安装包。
- **迁移备注**：本次为切流前唯一一次 CloudBase schema 增量（仅加列+索引、不改数据），最终 P4 快照会包含；ECS `class_tools`/`class_tools_cut` 已同步应用，之后 CloudBase 恢复只读。

## 2026-11-18 13:2x–13:4x · 修复屏山慢跑「11-17 补报名」识别：固定日期活动不再判长期安排（网页数据已同步云端）

> 用户反馈：「屏山慢跑打卡11月17日（本周二）补报名的消息识别出现了分组异常和时间识别异常以及通知分类异常等问题，请修复」。
> 根因：11-17 补充通知（重发活动全文 + 屏山校区 17:00 补报名）被并入 11-14 活动组后，AI 质检把「每日 17:00-20:00」判成 `recurrence`，并重写标题为「屏山慢跑打卡11-17补报名」；`recurrence` 在状态机中优先于 `signupStart`，导致卡片显示「本次 11-18 17:00」、被归入长期通知且 `actionable=False`（不进待处理）。

- **数据修正（人工补丁 `C:\briefdesk\data\notice-manual-patches.json`）**：该组标题回到活动主体「冬季傍晚慢跑打卡（11-16至11-27）」；摘要补「屏山11-17 17:00补报名」；`eventAt=2026-11-17T17:00` + `eventAction=补报名`、`expireAt=2026-11-27T20:00`、`actionable=true`。
- **通用规则（builder `resolve_recurrence_conflicts`）**：凡 `recurrence` 与 `signupStart/signupEnd/deadline/eventAt/signupWindows` 并存 → 以一次性时间为准、移除 recurrence（活动时段保留在摘要/原文），并恢复 actionable；日志 `recurrence->oneoff`。
- **分组去重（`notice_merge.merge_groups`）**：同一活动补充通知重发全文时，同原文（≥14 字）即使消息时间不同也只保留一份；补报名原文/附件保留。修复后该组 items 4→3（重复全文消失）。
- **AI 提示词**：`ai_quality.py` / `ai_brief.py` 增补「固定日期范围内的活动/打卡不是长期安排；有 signup/deadline/eventAt 时 recurrence 必须 null；标题不得用补充通知的局部动作（补报名）替换活动主体」。
- **测试**：新增 `tools/tests/v2_notice_slowrun_check.py` **19/19**（数据字段/DOM chip「11月17日（本周二） 17:00 补报名」/主列表/档位 3/长期通知 1=进行中/无 recurrence 冲突/0 JS 报错/截图）；`test_notice_merge.py` 增加重发全文去重用例，全部 PASS；回归 `v2_notice_period_check` 53/53、`v2_notice_longterm_check` 27/27、`v2_notice_live_check` 20/20、`v2_notice_publish_check` 20/20、`v2_notice_data_check` 27/27、`v2_notice_dynamic_cat_check` 18/18、`v2_ui_check` 27/27。
- **云端**：`sync_notices_cloud` 104/104；测试身份只读核验该组 title/eventAt/eventAction/expireAt/recurrence=null/actionable=true；board 页 14,624,368 B（sha256 `3419bc2e…`）、data 14,537,493 B。网页 `index.html` 未变（仍 1,335,115 B / `610a39dc…`，数据驱动无需重发）。
- **影响**：长期通知数由「recurrence 组数」口径恢复为进行中安排数（屏山慢跑不再算长期）；该卡进入主列表档 3，chip 显示 11-17 17:00 补报名。小程序/安卓读同一字段，下个版本/已发布版本均按 `eventAt` 显示（无需改客户端代码）。

## 2026-11-18 12:45–13:0x · 通知「发布时间统一」：无时间通知以发布时间入主列表、动作「发布」并统一排序/统计（网页已上线 OSS+ECS；小程序/安卓源码待发）

> 用户原话（2026-11-18 12:45）：「将通知中不含时间的时间设定为发布时间，动作设为发布，并参与排序等等统一计算」。2026-11-14 契约曾把「无任何时间锚点」的通知单独放入「资料 / 无时间」栏、不进主列表/不参与待处理统计；本次改为统一计算。

- **唯一契约**：`《通知三端·发布时间统一》契约（内部归档）`（`publishedAt` / `publishAction` 数据字段、状态/分类/排序/统计口径、兼容与回滚）。
- **数据管线**（`briefdesk-plan/build_notice_board.py` + `C:\briefdesk\scripts\sync_notices_cloud.py`）：所有组写 `publishedAt`（组内最新消息时间/updatedAt 的较晚者，ISO +08:00，与「最新发布」同口径）；无任何时间锚点且非长期安排的组写 `publishAction="发布"`；`compact_group` 白名单新增两字段（云端 body 下发三端）。
- **网页模板**（`build_notice_board.py` → demo → `build_notice_embed.py`）：新增 `publishedTsOf`（优先字段、旧数据回退推算）；`statusOf` 在「无时间」前新增 `published` 分支（chip `<时间> 发布`）；`isInfoGroup` 排除有发布时间者、`isTimeGroup` 纳入发布卡 → 发布卡进主列表；`orderRank` 档 4 + 档内按发布时间倒序；「资料 / 无时间」栏只保留既无锚点又无发布时间的兜底卡（正常 0 条自动隐藏）；待处理/24h/7 天/最新发布按契约统一计算（发布卡 actionable!==false 计入待处理；主显示时间过去→不进未来窗口）。
- **测试**：新增 `tools/tests/v2_notice_publish_check.py` **20/20**（状态/chip/主列表/资料栏兜底/排序倒序/待处理统计/最新发布字段优先/真实数据/无溢出）；更新 `v2_notice_period_check.py` **53/53**、`v2_notice_longterm_check.py` **27/27**、`v2_notice_live_check.py` **20/20**（资料栏语义改为发布卡进主列表）；`v2_notice_data_check` 27/27、`v2_notice_dynamic_cat_check` 18/18、`v2_ui_check` 27/27；`overflow_check 430` overflowCount=0、`export_check draw` 正常落盘。
- **上线**：`tools/index.html` **1,335,115 B / sha256 `610a39dcfc2aad1f8a3d7727a87396a0a6c8a949c15d39e0b76e9dbdb497b46b`**；OSS `sync_tools.py` + ECS `ecs_site.py apply`，`oss_object check`/ECS verify 均 MATCH（gzip 413,620B）；board 页 **14,626,157 B / sha256 e603f657…**、data **14,539,363 B**；notices cloud **104/104**（测试身份只读核验：104 组全部带 publishedAt、9 组带 publishAction）。
- **部署前备份**：`tools/_backup/index_online_20261118-1258_prePublishTime.html`（1,333,307 B / `b33d0251296ecc25c26e23dd56137d578874f72b57768c6d589ba4b3dd7ceac0`）。
- **回滚**：重传备份 index（模板恢复旧语义）；`publishedAt`/`publishAction` 为新增字段，旧模板会忽略，可直接保留；board/notices 数据如需彻底回退可重建+重新 sync。
- **待用户操作**：小程序（`mp-class-tools`）与安卓（`android-class-tools`）源码同步改造完成、单测全绿；小程序需用户上传发布、安卓需重新打包安装后生效。

## 2026-11-18 10:2x–10:3x · 修复网页通知页「一直加载 / 加载失败」：整表 15MB → lite 0.3MB + 附件按需拉取（网页已上线 OSS+ECS）

> 用户反馈网页/小程序通知页打不开、一直加载或提示「通知加载失败」，同时手机收不到提醒。只读排查：本地通知服务 HTTP 200、云端 `public.notices` 可读，但整表已达 **15,024,643 B / 124 行**（自动通知 body 内嵌图片/文件 data URI）；网页仍用 `notices?select=*` 一次拉全表，手机弱网/微信 WebView 下等同于卡死。小程序 11-17 已有 `class_notices_meta` lite 链路，网页此前未接。

- **网页 `tools/index.html`**：`fetchFull()` 改为优先 `POST rpc/class_notices_meta`（服务端把 `items[].url/src` 的 data URI 置空并写 `lazy=true`，**实测 306,056 B / 0.57s**；失败/接口不存在才回退旧整表）；新增 `NT.loadBody(gid)` 按 `notices?select=*&id=eq.<rowId>` 拉单条完整 body；`class-notice-need-body` 消息由父页处理并回注 iframe。
- **通知模板**（`briefdesk-plan/build_notice_board.py` → `notice-board-live-demo.html` → `build_notice_embed.py`）：文件/图片/压缩包内文件空 URL 且 `lazy=true` 时显示「点击加载」占位；新增 `lazyBody` / `__zqHydrate`，点击后才拉单条 body，文件弹层显示真实大小与下载按钮、图片弹层直接渲染；长期安排期次卡按 `__baseId` 回填，不破坏期次字段。
- **缓存/兼容**：lite 缓存从 15MB 降到 ~0.3MB（IDB 不再超限）；旧缓存（整表）仍可读；无 lite RPC 的旧云端自动回退，功能不丢。
- **真实浏览器验证**（测试身份，只读 + 本地同源代理）：通知页 **1.3s 内 96 卡**、`nt.fail=false`、0 JS 报错；首次加载仅 `class_notices_meta` 306KB，无 `notices?select=*` 整表请求；点击附件按需拉 170,004B 单行并弹出 121KB 下载；点击图片按需拉 480,325B 并渲染 1237×2199。
- **回归**：`v2_notice_live_check` **20/20**、`v2_notice_period_check` **53/53**（新增 S5 lite RPC / S6 模板水合静态断言）、`v2_notice_longterm_check` **27/27**、`overflow_check 430` overflow=0、`v2_ui_check` **27/27**；三个通知测试的 fetch mock 增加 `rpc/class_notices_meta` 分支。
- **上线**：`tools/index.html` **1,333,307 B / sha256 `b33d0251296ecc25c26e23dd56137d578874f72b57768c6d589ba4b3dd7ceac0`**；OSS `sync_tools.py` + ECS `ecs_site.py apply`，`oss_object check`/ECS verify 均 MATCH（gzip 412,824B）。部署前线上备份 `tools/_backup/index_online_20261118-1035_preNoticeLite.html`（1,326,819 B / `8cc6f447…`）。
- **仍待人工的一步（小程序提醒）**：云函数 `notify` 代码已是 11-15 修复版（本地/云端 index.js、scan.js hash 一致），但 `config.json` 的 `hwReminder` timer 触发器仍未上传——`diag` 实测 `hb.source=flush`、`lastScanAt=0`、等待 75s 心跳不前进（`FAIL_TIMER_STALE_OR_NOT_ADVANCING`）。微信机制限制：CLI/「上传并部署」只传代码，**触发器必须在开发者工具右键 `cloudfunctions/notify/config.json` →「上传触发器」**（或云开发控制台 → 云函数 → notify → 触发器 → 新建 `hwReminder` / timer / `0 */1 * * * * *`）。上传后 `diag.hb.source` 应为 `timer`。
- **OPPO 推送**：本机 `oppo-push.log` 今天每轮均「注册设备 token 数: 0」；`push_tokens` 表 RLS/写入已用测试身份验证可用（插入→读取→删除通过）。当前没有任何手机上传 RegistrationID，需在 ColorOS 真机打开 beta4 并登录后确认设置页推送状态；若仍为 0，再查 OPPO 开放平台包名/签名与 `oppo.properties` 推送密钥是否匹配。
- **回滚**：重传备份即可（会同时回退本次模板/脚本；lite RPC 与 DB 不变，旧页面仍可用）。小程序侧无代码回滚（未改）。

## 2026-11-17 22:4x–23:0x · 安卓 vc87/beta4：补齐 OPPO 账号 OAuth Manifest APPID（修复 2020003 的客户端配置缺失）并发布

> 用户反馈 OPPO 授权仍提示 2020003；仔细核对 OPPO 账号 OAuth SDK 文档后，发现「Manifest 配置 MSP 开放平台 APPID」一步此前缺失。

- `AndroidManifest.xml` 新增 `com.heytap.msp.client.appid=${oppoAccountAppId}`（Gradle 从 `oppo.properties` 注入）+ 系统账号服务 provider `<queries>`；合并 manifest 已核对 APPID=38092999。
- 版本 vc87 / 1.0.0-beta4（测试版本 4）；全量单测 **1566/0**；APK **5,787,765 B / SHA-256 `CFB5418E…2981E1AC`**。
- 桌面规范包 `班级工具站_v1.0.0-beta4_安卓.apk`；更新通道 latest.json vc87 + ECS APK 已发布并实取 sha 一致（OSS `.apk.bin` 同步）。
- 待 ColorOS 真机验证 2020003 是否消除；若仍失败，下一步查 OPPO 账号服务应用激活/上架/包名签名。
- 回滚：更新通道 latest.json 回 vc86、桌面回 beta3；网页无需部署。## 2026-11-17 21:2x–21:4x · 安卓 vc86/beta3：ColorOS-only 账号入口、快捷登录免填学号姓名、OPPO 授权错误可诊断、更新改弹窗手动选择

> 用户反馈：OPPO 授权失败；账号相关应只在 ColorOS 显示；未输入学号姓名无法快捷登录；检测到更新不应立即自动更新，应在弹窗给选择。

- **ColorOS-only**：`OppoAccountDeviceSupport` 严格按 ColorOS ROM 属性判断；非 ColorOS 隐藏快捷登录/账号入口（含补单测）。
- **快捷登录独立性**：入口移到身份表单前，按钮只依赖协议勾选/授权状态，不依赖学号姓名；未勾选协议点击给提示。
- **授权错误诊断**：SDK 错误码显示「中文（code=xxx）」；ECS `oppo_exchange_failed`/`invalid_client` 显示「账号服务未开通或凭证不匹配」；登录/绑定/非 2xx 映射 + 单测。ECS 日志确认用户操作时无 authCode 到 `/oppo/login`（失败在 SDK 授权阶段）。
- **更新交互**：自动/手动检查发现新版只弹窗，不自动下载；下载完成不自动安装，等「立即安装」；弹窗显示当前→新版、说明、包大小(sizeBytes)、渠道，按钮立即更新/稍后/取消下载/立即安装/重试，force 无稍后；新增 UpdateManagerTest 13 项。
- **产物**：vc86 / 1.0.0-beta3，**5,787,701 B / SHA-256 `11C121C8…52BBD93`**，全量单测 **1566/0**；桌面规范包 `班级工具站_v1.0.0-beta3_安卓.apk`；更新通道 `latest.json` vc86 + ECS APK 已发布并实取 sha 校验一致。
- 未验证：ColorOS 真机真实 OPPO 授权（服务端 invalid_client 待账号服务修好）；更新手动选择路径未真机跑。
- 回滚：更新通道 latest.json 回 vc85（或删 beta3 APK）；桌面回旧包；网页无需部署。
## 2026-11-17 21:1x · 修复安卓检查更新：发布 vc85/beta2 到更新通道（latest.json + APK）

> 用户反馈「app 的检查更新检查不到」。排查：更新服务器 `https://tool.furina.fun/android/latest.json` 仍是 **vc84/1.0.0-beta1**（`versionCode=84`），而桌面新包已是 **vc85/1.0.0-beta2**；App 更新判定只看 `versionCode > 当前 versionCode`，所以装 vc84→服务器同为 84 不会提示，装 vc85→服务器 84 更低也不会提示；同时 vc85 APK 之前未发布到更新通道（ECS `/var/www/tool/android/` 无 beta2 文件）。

- 已发布：`android/latest.json` → `versionCode=85 / versionName=1.0.0-beta2 / apkUrl=https://tool.furina.fun/android/classtools-1.0.0-beta2.apk / sha256=7580c6e7…5708c6 / channel=beta / force=false`；
- APK 已上传 OSS（因 OSS 限制 `.apk` 后缀，沿用 `.apk.bin` 方式）并由 ECS 落成 `/var/www/tool/android/classtools-1.0.0-beta2.apk`（5,787,701 B，sha256 与 manifest 一致）；ECS `latest.json`/APK 均 HTTP 200 实取校验通过。
- 影响：手机上当前为 **vc84 或更低** 的 App 现在检查更新可发现 vc85/beta2；已经是 **vc85/beta2** 的手机显示「已是最新」是正常的（服务器没有更高 versionCode）。注意本轮两次 vc85 构建（先无账号密钥、后有账号密钥）versionCode 都是 85，若装的是前一个 vc85，系统不会提示同版本更新，需手动安装桌面最新 `班级工具站_v1.0.0-beta2_安卓.apk` 或后续升 vc86。
- 回滚：把 `latest.json` 改回上一版 vc84/beta1 并从 ECS 删除 beta2 APK（OSS beta2.apk.bin 可保留）。
## 2026-11-17 20:0x–20:5x · 增量 62：OPPO 账号绑定学号（≤3 个）+ OPPO 快捷登录（安卓 + ECS 账号验证服务）；安装包改规范命名

> 用户要求：允许 OPPO 账号绑定学号（一学号最多 3 个）、允许 OPPO 快捷登录；安装包替换桌面规范命名包、不要功能命名包。已确认：可自助解绑；允许 ECS 新增账号验证接口（服务端 authCode→openid）。

- **安装包**：桌面只保留 `班级工具站_v1.0.0-beta2_安卓.apk`（vc85 / 1.0.0-beta2 / **5,787,701 B / SHA-256 `CE861934…055C78`**，v2 签名；功能命名包已删）；`artifacts/classtools-1.0.0-beta2-vc85-release-signed.apk` 同字节。
- **云端**：迁移 `deploy/cloudbase/2026-11-17_account_bindings.sql` 已应用（绑定表 + 仅管理员 RLS + 3 条上限触发器）；测试身份实测第 4 条绑定被拒、普通 token 直连不可见、管理员可清理。
- **ECS**：新增 `deploy/account_app.py` + `deploy/ecs_account.py`（`class-tools-account.service` 127.0.0.1:8094），`deploy/ecs_site.py` 三套 Caddy 配置加 `/account/*` 反代并 apply；公网 `/account/__health` 200。接口：`/oppo/login`、`/oppo/bind`、`/oppo/bindings`、`/oppo/unbind`；authCode 服务端换 openid、openid 不出服务端、绑定表仅管理员 token、限频 30/分/IP。
- **本地 mock E2E 通过**：绑定 4 个 mock 账号→前 3 成功/第 4 limit；快捷登录返回班级 token（class_whoami 校验）；解绑后登录 unbound。绑定行已清理。
- **安卓**：OPPO 账号 OAuth SDK 1.1.3 + 身份页快捷登录 + 我的→账号绑定/解绑/列表（N/3）；全量单测 **1545/1545（116 suites，新增账号 72）**；APK vc85/1.0.0-beta2。当前账号服务凭证未填 → 快捷登录/账号入口隐藏；真实 OAuth 未联调（需账号服务专用凭证 + ColorOS 真机）。
- **待用户操作**：账号服务专用 AppID/AppKey/AppSecret 填 `C:\briefdesk\secrets\oppo-account.json` + `app/oppo.properties` 的 `oppo.accountAppId/accountAppKey` → Lead 重跑 `deploy\ecs_account.py deploy`（health configured:true）+ 重打 APK。
- 文档：`《通知 OPPO 账号绑定与快捷登录》说明（内部归档）`、`android-class-tools/docs/OPPO_ACCOUNT.md`。回滚：停 ECS 服务/去 Caddy 路由；DROP 表；客户端回退上一版 APK。
## 2026-11-16 21:4x · 更正：网页恢复「学信网」工具（用户更正：仅网页保留；Android/小程序/鸿蒙仍删除；未部署、未 commit）

> 用户更正：网页版学信网可以留下，其它端仍删除。当前 HEAD `9092feb` 已删除 chsi（线上 1,321,954B/`5fc54899`），本次只把学信网相关代码合并回网页，activity/today 仍不在网页。注意 `9092feb^` 因并行提交 `78765f4` 已含删除结果，实际以备份 `tools/_backup/index_online_20261116-2129_preRemoveTools.html`（1,322,990 B / `621f6a7b`，含 chsi）为片段来源；插入位置按当前 HEAD 锚点，并做了「再跑一次删除脚本 == HEAD 字节级一致」的往返校验。

- **恢复清单（`tools/index.html`，7 处）**：`TOOLS` 末尾 `{k:"chsi",n:"学信网",d:"学籍 · 学历 · 学位；官方入口卡"}`（jw 后加逗号）；`ALL_TONE.chsi="blue"`；`#s-chsi` 整段 HTML（含 `__CHSI_ENTRY_V1_BEGIN__/_END__` 标记与注释）；`__CHSI_ENTRY_V1_CSS__` 样式块；深色主题 `.vote-opt-edit .vnum + #s-chsi .chsi-card em` 合并规则；深色 `#s-chsi .chsi-card:hover/:active` 两条；使用说明第 19 张 `chsi` 卡。
- **测试恢复**：`tools/tests/v2_chsi_check.py`（54 项，从 `9092feb^` 取回）；`v2_ug_check` 回 19 卡/57 步计数；`v2_jw_check` 回「jw 后为 chsi」+ UG 19 卡断言；`v2_port_ui_check` 全部页描述卡下限回 18；`tools/tests/_power_preview.html` 由 `power_check.build_previews()` 按恢复后 `index.html` 重生成（含 chsi 64 处、keepalive 5 处）。
- **实跑结果**：`overflow_check 430` overflowCount=0；`v2_ui_check 27/27`；`v2_port_ui_check 80/80`；`export_check draw` 退出码 0（`_shots/export_draw.png` 221,094 B）；`v2_chsi_check 54/54`（430/360/390/1280 两路径）；`v2_ug_check 56/56`（19 卡/57 步）；`v2_jw_check 52/55`——S3/S12/S14 三条既有静态断言在改动前工作树副本上同样 FAIL（与学信网无关的陈旧切片假设），S2/S9 已随 chsi 恢复通过。
- **确认**：`tools/index.html` 中 `activity`/`todaycampus`/`今日校园` = 0，网页仍只有「学信网」恢复、其它两个工具保持不出现；`APP_VER` 仍 `2.0.0`。最终 **1,326,819 B / sha256 `8cc6f447443575904945c818dc79001aa76cded9f6ff5b0e964df9bc3cbf965c`**（LF；= HEAD 1,321,954 B + 原 chsi 删除字节 4,865 B）。**未部署 OSS/ECS、未 commit**（由 Lead 部署）；回滚=还原上述 7 处恢复（回到 `9092feb` 字节）。

## 2026-11-16 21:2x · 修复：大屏退出后「大屏互联」一直显示开启 + 上一次大屏数据回放（网页已上线 OSS+ECS；drop 服务 v2.4）

> 用户反馈（2026-11-16 21:17）：「大屏互联功能一直显示开启，即使我已经把大屏退出了，而且上一次大屏的数据还一直留存着」。
> 根因（两处叠加）：① **presence 竞态**——`opt2StageOpen` 里 `stgDropEnsure().then(... stgPresenceStart())` 没有生命周期守卫，用户在大屏打开后立即退出（/open 尚未返回）时，迟到的回调会在关闭后重新启动 10s 心跳，于是「全部页→大屏互联」入口/其他设备控制器永久显示在线；② **本次会话未隔离**——大屏复用 72h 云空间会话，重开时 `/state?since=0` 会把上一次大屏/文件传输的历史事件全部回放成「本次收到」；接收模块（recv）也因此残留旧文件/文字。
> 范围：`tools/index.html`（§11 大屏块，presence/会话游标/控制器；APP_VER 仍 2.0.0）、`deploy/drop_app.py`（v2.4：`session.seq` + `/presence` 的 `sinceSeq`）、`drop/CONTRACT.md`、`drop/tests/test_drop_app.py`、`tools/tests/v2_stage_drop_session_check.py`（新增）、`tools/tests/optim_v2_check.py`。

- **presence 生命周期加守卫**：`STAGE.lifeGen` 每次打开/关闭递增；`stgDropEnsure(true)` 的异步回调发现「大屏已关闭 / 世代变化」时直接上报 `presence=false` 并返回，绝不再启动心跳；`stgPresenceStart()` 要求 `STAGE.open`，心跳 interval 每秒检查，关闭即停；`stgPresenceStop()` 立即 POST false（keepalive），并新增 `pagehide`/`beforeunload` keepalive 兜底（关标签页/刷新也下线）。
- **会话游标隔离「本次大屏」**：`POST /open`、`GET /mine` 的 `session` 新增 `seq`（当前最大事件 seq）；大屏每次打开用 `stgDropBeginStage()` 把游标对齐到该 seq 并清空本次接收列表，`/state` 只拉之后的新事件；退出大屏时清空 recv/互联列表（云空间文件仍保留 3 天，可在「文件传输」页查/删）。
- **其他设备控制器只按 presence 判定在线**：不再「只要 72h 云空间会话存在就显示已连接」；`/presence` 新增 `sinceSeq`（大屏打开时刻上报），控制器用 `sinceSeq` 作为 `/state` 起点，只显示本次大屏期间的文件/文字；大屏退出（或心跳 30s 过期）后控制器显示「大屏已退出」并隐藏上传/遥控区。
- **大屏互联面板**不再提供「关闭通道」误删 72h 云空间文件：× / 「收起」只收起面板；面板文案区分「本次互联已开启 / 云空间已连接 · 大屏未在线」。
- **测试（真实输出）**：新增 `tools/tests/v2_stage_drop_session_check.py` **24/24 PASS**（预置 4 条历史事件后打开大屏不显示旧内容；本次事件出现；退出 presence 立即 false/入口隐藏/无心跳残留；`/open` 延迟 900ms 时快速退出也不会把 presence 拉回；重开不显示上一次消息；控制器在线/退出/本次事件隔离；0 JS 报错）；drop 单测 **93/93 OK**（新增 `session.seq`、`/presence` `sinceSeq` 往返/钳制/下线归零/旧客户端兼容用例）；`optim_v2_check` **GREEN 0 fails**（mock 升级为 v2.4 presence/seq 语义）；真实 ECS 黑盒（测试身份）：`session.seq` 0→3、`/presence {sinceSeq:2}` 读取一致、下线 sinceSeq=0 且会话保留、越界 sinceSeq 钳制到 3、旧页面不传 sinceSeq 取当前 seq；`deploy/ecs_drop.py verify` PASS。
- **上线**：drop 服务 ECS **v2.4**（`/drop/__health` = `{"ok":true,"version":"2.4"...}`）；网页 OSS+ECS **1,321,954 B / sha256 `5fc54899…`**（本次部署时线上已是并行会话合并后的同一份文件，`oss_object check`/ECS 均 MATCH）。回滚：网页重传 `tools/_backup/index_online_20261116-2120_preDropSessionFix.html`（1,322,990B/`621f6a7b…`，修复前）；drop 服务按 `drop/CONTRACT.md §7` 回退 v2.3（去掉 `/presence` 的 sinceSeq/`session.seq` 消费方即可；服务端旧字段向后兼容）。
- **已知限制（如实）**：旧版本缓存页面（修复前打开、未刷新的标签）仍可能每 10s 上报旧心跳，直到关闭/刷新；presence 心跳 30s 内视为在线（页面崩溃后最迟 30s 自动离线）；云空间文件仍按设计保留 3 天，本次只隔离「大屏互联/接收」的会话视图，不改变「文件传输」工具的保留策略。本文件同时含并行会话「学信网入口下线」改动（其 CHANGELOG 记未部署，实际随本次合并文件一并上线；以文件内容与线上 sha 为准）。

## 2026-11-16 21:1x · 网页删除「活动 / 今日校园 / 学信网」三工具（web task-75；未部署、未 commit）

> **2026-11-16 21:4x 用户更正：网页保留学信网，已恢复（见上一条）；Android/小程序/鸿蒙仍删除。本条目以下内容为当时记录，仅 activity/今日校园保持删除。**

> 用户要求全端删除「活动 / 今日校园 / 学信网」三个工具。网页侧现状：`活动` 已于 2026-11-15 按用户决定撤回（commit `6c0ae49`，改由安卓 App 原生提供）；`今日校园` 从未进入网页 `TOOLS`（仅安卓 App 有；网页通知正文里的「今日校园」是上游 App 专名，不是工具入口）；本次删除唯一存在的 `学信网`（增量 61 新增）。

- **`tools/index.html` 死代码删除（APP_VER 仍 2.0.0）**：`TOOLS` 的 `chsi` 条目、`ALL_TONE.chsi`、`#s-chsi` 整段 HTML（含 `__CHSI_ENTRY_V1_BEGIN__/_END__` 标记与上方注释）、`__CHSI_ENTRY_V1_CSS__` 样式块、深色主题下 3 条 `#s-chsi` 规则（1 条合并选择器内、2 条独立 hover/active）、使用说明第 19 张 `chsi` 卡；无隐藏/灰显/降级逻辑保留。
- **入口不可达验证口径**：顶部快捷工具栏与「全部」页卡片均由 `TOOLS` + `tabInfoOf` 驱动（`renderTabs` 对 `homeTools` 按 `tabInfoOf` 过滤、未知 key 自动丢弃；`allCardDefs` 遍历 `TOOLS`），`#tab=` 直达经 `gotoTab` → `toolOf` 校验，`chsi` 均不再命中；网页无工具搜索 UI（唯一搜索框是投票「指定成员」搜索）。全部页卡片 18→17（管理员视图；普通成员 17→16）、使用说明卡 19→18。
- **测试同步**：删除 `tools/tests/v2_chsi_check.py`（54 项，目标已不存在）；`v2_ug_check` 固定计数 19→18 张、57→54 步（S9/R1/R2/R5/R6/R7/R8/R10/R13/R14/R15/R16/R27，未放宽断言）；`v2_jw_check` 恢复「jw 为 TOOLS 末尾」断言并 UG 卡数 19→18；`v2_port_ui_check` 全部页描述卡下限 18→17；`tools/tests/_power_preview.html` 由 `power_check.build_previews()` 按新 `index.html` 重生成（0 处 chsi）。
- **实跑结果（最终合并文件复跑）**：`overflow_check 430` overflowCount=0；`v2_ui_check 27/27`；`v2_port_ui_check 80/80`；`export_check draw` 退出码 0（`_shots/export_draw.png` 219,094 B）；`v2_ug_check 56/56`（含 430/360/390/1280 运行时、0 JS 报错/0 外部请求）；`v2_jw_check 52/55`——S3/S12/S14 三条静态断言在**改动前的 HEAD 工作树副本**上同样 FAIL（`__JW_ENTRY_V1_JS__` 尾部切片被 11-16 新增 JS 块污染、`tail` 起算点失效），属既存测试陈旧假设，非本次改动引入；S2/S9 两条与旧工具相关的断言已更新并通过。补充运行时验收（临时脚本，未入库；在纯删除中间态实跑）：老 `homeTools=["chsi",...]` 启动后工具栏自动过滤为 `draw,tt,hw,all`、DOM 无 `#s-chsi`/`#s-activity`/`#s-todaycampus`、`#tab=chsi` 不切页、页面 0 JS 报错（5/5 PASS）；最终合并文件上同一入口逻辑未改动（删除仅由 `TOOLS`/`tabInfoOf` 数据驱动）。
- **源码**：`tools/index.html` 最终合并文件 **1,321,954 B / sha256 `5fc54899fc3aee282ef2c05b453cd4a268226715446c3cf343d0eacadedc0624`**（本任务纯删除中间态 1,318,125 B / `5fadfd84…`；两者均 LF、单文件零依赖、`APP_VER` 仍 2.0.0）。**注意**：合并前后的工作树同时含并行会话「大屏互联 drop 会话/keepalive」整文件写入（约 +3.8 KB，`2026-11-16` 同日；该会话曾把本删除覆盖回旧版，本轮已把其改动与删除合并为同一文件并复跑全部测试）；工作树原有的地图缓存版本号 1 行 WIP 原样保留。**未部署 OSS/ECS、未 commit**（由 Lead 统一集成部署；回滚=在最终文件上还原本任务 7 处删除）。

## 2026-11-15 19:3x–20:0x · 小程序提醒链路修复（云函数源码；网页无改动、无需部署）

> 用户反馈「微信小程序提醒功能异常」。线上实测（automator 调 `notify` 云函数）：部署的仍是 2026-11-10 旧版（`ntStatus`/`bootstrap`/`scan` 均 `unknown-action`），且 `diag.hb.source` 一直为 `flush`、等待 80s 无 `timer` 心跳 → 定时触发器未注册。源码另有一处会让新通知提醒永远 `no-token` 的缺陷。

- **源码修复**（`mp-class-tools/cloudfunctions/notify/index.js` + `scan.js`）：`patchCfg()` 原先用 `doc.set({data:patch})` 写 `notify_cfg/__notify_cfg`，而云开发 `set` 是整文档替换 → bootstrap 写入的班级 token 在第一次 scan 写 `lastSig` 时被清掉；每次 bootstrap 又清掉基线。改为「已有文档 `doc.update` 字段合并；文档不存在时 `getCfg` + `scan.mergeCfg` 合并后 `set` 完整文档」，新增纯函数 `scan.mergeCfg`。
- **测试**：`notify_flush_ui_test.js` 11/11（C7 防回退）、`task7_unit_tests.js` 24/24（B2b bootstrap→scan→bootstrap 字段不丢）、`cloudfunctions/notify.test.js` 35/35、`notify_fix_20261110.test.js` 18/18；`node --check` / `staticcheck.py` / `code_quality_check.js` 通过。另用临时 mock 集成跑通 bootstrap→baseline→新通知 send=1，token 全程保留。
- **部署状态**：仅改源码；**未自动上传云函数/触发器、未改小程序前端、未动 VERSION 2.0.0/UD v6、网页零改动**。需用户按 `mp-class-tools/README.md §九·补`：① 上传 `notify` 云函数（带 `scan.js`/`rest-config.js`）；② 右键 `config.json`「上传触发器」（`0 */1 * * * * *`）；③ 上传后 `notify {action:'diag'}` 验证 `hb.source=timer`、`notify.hasToken=true`。
- 回滚：还原两个云函数文件与测试；云端未部署，无回滚动作。

## 2026-11-15 13:50–15:0x · 增量 61：三端中的网页 + 安卓新增「学信网」入口——网页官方工具卡片页（手机优先 2/3/4 列，**已上线 OSS+ECS**）+ 安卓卡片页/数据卡（4.53.0 APK 已交付）；小程序不动

> 用户原话（2026-11-15 13:50）：「以相同方式引入学信网入口，同样将内部常用工具做成卡片，整体页面要适配手机」。规格唯一来源 `_audit/chsi_entry_20261115/CHSI_ENTRY_SPEC.md`；口径：网页 = 站内「学信网」卡片页（仅官方工具入口，不抓数据、不内嵌、不保存账号）；安卓 = 数据卡 + 手动登录（另一任务）；小程序不动。任务单原写「增量 57」，因 57–60 已被 2026-11-14 其他增量占用，按编号顺延为本增量 61。

### ① 网页实现（`tools/index.html`，APP_VER 仍 2.0.0）
- `TOOLS` **末尾**追加 `{k:"chsi",n:"学信网",d:"学籍 · 学历 · 学位；官方入口卡"}`（jw 之后，不改既有工具顺序）；`ALL_TONE.chsi="blue"`。
- 新增 `#s-chsi`（`__CHSI_ENTRY_V1_BEGIN__`/`_END__` 包住；位于 `#s-vote` 之后、`__WEB_B2_FILE_BEGIN__` 之前）：头部卡片「学信网 + 中国高等教育学生信息网 · 官方入口 + 学信档案/照片校对需登录学信网账号」；10 张官方工具卡（严格规格 §1 实测 URL、顺序一致）：学信档案 / 学籍/学历查询 / 学位查询 / 在线验证报告 / 报告在线验证 / 学历认证报告 / 照片校对 / 研招网 / 学职平台 / 帮助中心；每卡 `<a class="chsi-card" href target="_blank" rel="noopener noreferrer">`，含短名 + 说明 + 徽标（规格表「是」3 张=「需登录」；「部分」2 张=「部分需登录」，其余 5 张无徽标）。
- CSS `/* __CHSI_ENTRY_V1_CSS__ */`（`</style>` 前）：`grid-template-columns:repeat(auto-fill,minmax(140px,1fr))`；`@media (min-width:640px)`→3 列、`(min-width:960px)`→4 列；卡片 `min-height:88px`（点按 ≥44px）、`overflow-wrap:anywhere`，无固定宽度/横向滚动；360/390/430 实测 2 列且无横向溢出，1280 为 4 列。
- 红线：加载/切页阶段对学信网**零请求**（全 HTML 仅 10 处 `chsi.com.cn`，全部是卡片 href，点击才跳转）；不 iframe 内嵌、不采集/不保存账号密码（浏览器跨域限制，网页端只做入口）；单文件零依赖；APP_VER 仍 2.0.0。
- 使用说明 `__UG_CARDS_V1__` 追加第 19 张 `chsi` 卡（cat study、scene grid、3 步 + tip）。AGENTS §4b 按 Lead 要求本增量不动。

### ② 测试（实跑）
- 新增 `tools/tests/v2_chsi_check.py` **54/54**（静态 15 + 运行时 39）：430/360/390/1280 四档 × 两条进入路径（`gotoTab("chsi")`、「全部」页点 `#allCards [data-card="chsi"]`）→ `#s-chsi` 可见；10 卡 href 顺序严格等于规格 §1 + target/rel；头部文案逐字；徽标 3+2；网格列数 430/360/390=2、1280=4；10 卡点按高度 88px（≥44）；无横向溢出；0 JS 报错 / 0 console.error / 0 外部请求（performance resource 不含 chsi.com.cn，加载+切页两阶段）；截图 5 张落盘 `tools/tests/_shots_chsi/`。
- 测试基础设施修正（本测试内）：headless Edge 的 `--window-size` 有最小窗宽（外页视口恒 ~492），旧截图 harness 用 `margin:0 auto` 会让 iframe 左偏 31–66px、PNG 被裁右侧；本测试改为 iframe 左对齐，手机截图完整不裁切（其它旧测试的截图 harness 未改，不影响其断言）。
- 回归：`overflow_check` 430/360/390 overflowCount=0、`v2_ui_check 27/27`、`v2_drag_check 69/69`、`v2_ug_check 56/56`（UG 卡 18→19 计数期望更新：S9/R1/R2/R5/R6/R7/R8/R10/R13/R14/R15/R16/R27，未放宽断言）、`optim_v1_check GREEN`、`optim_v2_check main 16 + admin 70 + hash 4 GREEN`；额外相邻面 `v2_jw_check 55/55`。
- `v2_drag_check` 适配（如实）：新增 1 张全部页工具卡使全部页高度 +130px，M 边缘自动滚动用例固定 `scrollTo(scrollHeight*0.35)` 后 handle 落进 sticky 工具栏（y≈18px，按下落空）→ 增加「handle 若贴近顶栏/视口外则先滚到卡片居中再取安全落点」兜底（M1/M3/M4 断言不变）；HEAD 基线实跑 69/69、修改后实跑 69/69。
- `v2_jw_check` 过期断言修正（如实）：S2 原要求 jw 是 TOOLS 最后一项（本增量 chsi 追加在 jw 之后 → 改为「jw 逐字存在且其后为 chsi」）；S9 UG 卡数 18→19；J5 卡片说明在 2026-11-14 增量 57 已精简为「成绩、选课与考试」（**S2/J5 在改前 HEAD 基线就已红，非本任务引入**，已一并修正）。实跑 55/55。
- 测试身份 `SID=9999000005 / 测试同学`（9999 段 mock，符合 AGENTS §0-7）；未使用真实学号/真实学信网账号；页面加载不触发任何外部请求。

### ③ 状态 / 回滚

- 本次网页**已上线 OSS+ECS**：线上 **1,245,831 B / sha256 `9f93306be176892ce5aff187e19979336fb5462e36f2e3c5766ab0327d56ba72`**（`deploy/oss_object.py check index.html` = MATCH；`python deploy/ecs_site.py verify` = MATCH（ECS_IP 直连字节校验），gzip 391,472 B；ECS 直连实取同字节且含 `#s-chsi`、10 张官方工具卡、`chsi-grid`、`APP_VER 2.0.0`）。部署前线上备份 `tools/_backup/index_online_20261115-1414_preChsi.html`（1,241,167 B / `000f0787…`）。Lead 独立复跑 `v2_chsi_check 54/54`、`overflow 430/360/390=0`、`v2_ui 27/27`、`v2_drag 69/69`、`v2_ug 56/56`、`v2_jw 55/55`。APP_VER 仍 2.0.0；无 DB / `userdata` v6 / 云函数变更。
- 源码 `tools/index.html` **1,245,831 B / sha256 `9f93306be176892ce5aff187e19979336fb5462e36f2e3c5766ab0327d56ba72`**；本次改动 hunk：CSS `+2558`、`#s-chsi` `+3108`、TOOLS `+5614`、ALL_TONE `+5750`、UG `+19281`；`git diff` 另含并行地图会话 1 行 WIP（`...&v=202611152305`，未触碰，随本文件一并提交/部署；路径不变仅缓存版本号）。
- 安卓端（同批另一任务）：v4.53.0 / vc71 APK `artifacts/classtools-4.53.0-release-signed.apk` **3,284,845 B / SHA-256 `DA22AC202FFC77B0C54803E94CADACC43BDD80FFA17314217C27DE6F6F9E14BC`**（点「学信网」→ 手动登录官方页 → 学籍/学历/学位/在线验证报告数据卡 + 10 官方工具入口卡 + 桌面版/手机版 UA 切换；窄屏 2 列/≥600dp 3 列；单测 **1276/0**（100 suites，新增 ChsiExtractLogicTest 26）；未真机/真实账号验证——红线）。
- 回滚：网页重传部署前备份后 OSS+ECS apply；安卓删除 features/chsi、ui/screens/chsi 与测试文件、共享文件按 pending 文档反向 edit、版本号回退；无 DB 变更。
## 2026-11-14 21:1x–21:4x · 增量 60：OPPO 官方推送 SDK 接入（安卓客户端 + 云端 push_tokens + 本机服务端推送；网页无需部署；待用户开通 OPPO 推送/密钥后真机验证）

> 用户 2026-11-14 晚要求「尝试将通知接入 oppo 官方 sdk」；已确认目标=App 未运行也能收系统通知栏推送，允许新增设备 token 表，先用测试权限验证。官方 SDK V4.0.0。

- 安卓：OPPO PUSH SDK V4.0.0 AAR（`app/libs/com.heytap.msp_V4.0.0.aar`，sha256 `8A542A78…1C41`）+ `app/oppo.properties`(不入库)/`.example` + Manifest 回调 Service + Channel `class_notice` + 注册状态机/设置页状态 + token 上传云端 + 点击（冷启动/onNewIntent）打开对应通知；全量单测 **1246/1246**（新增 OPPO 33 项）；Release **v4.51.0/vc69**，APK **3,252,045 B / SHA-256 `5BD44F09…EDA1A5`**（aapt2/apksigner 复核）。**未真机验证（无密钥）**。
- 云端：迁移 `deploy/cloudbase/2026-11-14_push_tokens.sql` 已应用（本人读写自己行、管理员读全量）；测试身份实测插入/upsert 去重/权限/清理通过。
- 本机：新增 `C:\briefdesk\scripts\oppo_push.py`（OPPO auth/单推/批量/水位去重/`--test/--notice/--dry-run/--tokens`）+ 14/14 单测；`detect_docs.py` 在云端通知同步后自动调用（`secrets/oppo-push.json` 存在才跑，失败不阻断）。
- 文档：`web/《通知 OPPO 推送接入》说明（内部归档）`、`android-class-tools/docs/OPPO_PUSH.md`。
- 用户下一步：OPPO 开放平台开通推送（测试权限）拿三密钥 → 安卓填 `oppo.properties` 重打包真机安装 → 本机填 `C:\briefdesk\secrets\oppo-push.json` → `oppo_push.py --tokens/--test <regId>` 验证。
- 回滚：清空/删除 `oppo-push.json` 即停推；`DROP TABLE public.push_tokens`；安卓回退上一版 APK；已知限制：仅 ColorOS 系、正式通知栏权限需上架 OPPO 商店/特殊申请。


## 2026-11-14 21:1x–21:3x · 撤销 ko-link.cn 临时域名（三端源码 + ECS Caddy + DNS 全部回退；等 furina.fun 备案）

> 用户 2026-11-14 决定：老老实实等 `tool.furina.fun` 备案完成，撤销三端中所有用到 ko-link.cn 的改动。

- **网页**：`tools/index.html` 同源反代判断（`var CB` 运行时覆盖）与抽签核验链接 host 判断去掉 `ko-link.cn`，恢复为 `tool.furina.fun` 子域 / `tool.furina.fun`；测试预览副本 `tools/tests/_power_preview.html` 同步；`deploy/ecs_site.py` Caddy HTTPS 站点块恢复为仅 `tool.furina.fun`。**保留** `/v1/rdb/rest/*` 反代 `header_up -Origin`（IP/非白名单来源登录必需，2026-11-12 修复）。
- **小程序**（源码，待用户重新上传）：`utils/cloud-config.js` `webBase` → `https://tool.furina.fun`、`dropBase` → `''`；`utils/drawproof.js`/README/CHANGELOG 注释同步。**安卓**：全仓库无 ko-link.cn 引用，无需改动。
- **服务器/DNS**：`python deploy\ecs_site.py apply` 部署（Caddy 仅 `tool.furina.fun`、80/443 正常、`grep -c ko-link /etc/caddy/Caddyfile` = 0）；删除 ko-link.cn 的 LE 证书缓存；阿里云 DNS 删除 `@`/`www` A 记录（恢复 0 记录，`dns.alidns.com` DoH 实测无 A）。
- **上线**：网页 OSS/ECS **1,257,937 B / sha256 `b84b3d57d8acace943a693c13645c84f14ab9f048cf51fcf04d7e87a45204e48`**（`oss_object.py check` MATCH、ECS verify MATCH、`https://tool.furina.fun/` 实取同字节、页面内 `ko-link.cn` 出现次数 0）；headless Edge 测试身份在 `https://tool.furina.fun/` 登录成功（class_verify/class_members/class_league/fitrecs/marks/userdata 全 200、0 console error）。
- **回滚**：重传备份 `tools/_backup/index_online_20261114-2122_preKoLinkRevert.html`（1,257,999B/`fe5ca3da…`）+ `apply`；小程序回退源码；如需恢复临时域名 = Caddy 加回域名 + DNS 加回 `@`/`www` A → `tool.furina.fun` + 三端源码反向修改。

## 2026-11-14 13:3x–14:4x · 增量 58：三端通知改造（长期安排按期次 + 5 张可点数据卡 + 资料·无时间栏 + 时间显示归一）+ AI 活动周期记忆/更新合并（网页已上线 OSS+ECS；小程序/安卓待用户上传/安装）

> 用户 2026-11-14 要求：通知数据栏新增长期通知、全部数据卡可点展示、已过期卡换最新发布；长期通知不隐藏、按期次每次提前一天展示并可单独已处理；无时间不得进长期；请假只在军训期间；射击 11-14 通知应按已过期且要有时间；时间显示统一 `11月13日（本周五）`；11-13 晚自习/军训应合并为更新通知、摘要只留军训。契约 `《通知三端·长期通知与时间显示》契约（内部归档）`。

### 网页（`tools/index.html` 内嵌模板，APP_VER 仍 2.0.0）
- 顶部 5 张可点数据卡：待处理 / 24h 截止 / 7 天内 / **长期通知** / **最新发布**（点=筛选、再点取消、与 chips 互斥）；已过期数量只在下方过期区标题，不再占卡。
- 分区：「全部」= 主列表（含**期次卡**）→「资料 / 无时间」栏（默认展开）→ 已过期区；「长期通知」=长期安排清单（周期/下次/进行中）；「最新发布」=发布倒序；分类 chips 全视图生效。
- 期次：窗口 `[next-24h,next)`、key `<gid>@occ:<YYYYMMDD>`、「本次已处理」走既有 `marks ntdone`（ref=期次 key，跨端同步）；`recurrence.until` 到期归「长期安排已结束」；长期定义卡不再出现在主列表/不可 done。
- 时间显示统一 `M月D日（相对周）`（渲染时计算，跨年带年份、已带括号不重复）。
- 数据侧 builder：`apply_quality` 时间保护、`apply_threads`（更新/取消合并）、`sanitize_recurrence`（until 校验）。

### AI 管线（本机 briefdesk，不入 git）
- 新增 `ai_memory.py`（活动周期/用户反馈记忆 → `notice-memory.json`，prompt 注入；`memory_version` 只含 activities+rules 防全量抖动）、`notice_threads.py`（更新/取消线程 → `notice-threads.json`，相似度守卫 + 空结果保留上一版）。
- `ai_brief.py` CACHE_VER 9（原文相对日期预换算/记忆注入/recurrence until/取消内容不进摘要）；`ai_quality.py` CACHE_VER 2（系统时间保护/记忆 until/无时间不得 recurrence）；`detect_docs.py` 接入两阶段 + `NOTICE_SKIP_THREADS` 中间构建跳过线程；`notice-feedback.json` 用户反馈持久化（当前 9 条）。
- 最终数据：95 组、长期 2（g_dorm / 每日请假 until=2026-11-15）、资料·无时间 9、11-13 链合并为「11-14至11-15军训安排」摘要只含军训、射击 eventAt=2026-11-14T08:00 已过期独立卡。

### 小程序 / 安卓（源码交付）
- 小程序：`utils/notice.js` + `pages/nt/*` + `pages/index/index.js` 同构实现（VERSION 2.0.0、UD v6 不变）；unit 545/0、notice_time 20/0、longterm 13/0、occ 9/0、sync 34/0、v3 65/0、staticcheck/code_quality 0、automator 28/0（真实云端数据）。**待用户上传发布**。
- 安卓：v4.50.0/vc68，APK **3,174,605 B / SHA-256 `0F6F5141…B2FF1`**；全量单测 1213/1213、通知范围 260/260；仓库未 commit（HEAD 仍是并行会话的 c17142a，含并行 WIP）。**待用户安装**。

### 验证 / 上线 / 回滚
- 数据验收 20/20；网页 5 套 145/145；独立验收报告 `验收报告/通知长期期次与时间显示_独立验收_20261114.md`（无 P0；P1 已修；P2 如 AI 摘要少量重写/内存压力/最新发布时间来源）。
- 上线：备份 `tools/_backup/index_online_20261114-141130_preNoticeV2.html`（1,232,339B/`6da2b338…`）→ OSS/ECS **1,257,999 B / sha256 `fe5ca3da…`**（HTTPS 443 与 ko-link.cn/www/tool.furina.fun 同字节）；云端通知 95/95。
- 回滚：网页重传备份 + `deploy/ecs_site.py apply`；数据/AI 脚本备份在 `C:\briefdesk\data\_backup_notice_redesign_20261114\`；小程序/安卓回退用户上一版。

## 2026-11-14 13:0x–13:2x · 增量 56：安卓「教务」工具页改「卡片速览 + 官方接口数据 + 官方工具入口」（仅安卓 4.48.0 APK；网页/小程序无改动、无需部署）

> 用户原话（2026-11-14）：「把教务系统点开后也展示和班级工具站的卡片一样展开，只调用官方各个工具的网页接口」。
> 已确认（本次点选）：**只做安卓 App**；**卡片直接展示官方接口数据**（用户授权真实账号一次性接口勘察；Lead 复用本机 DPAPI + 既有 `jwxt.sso_login_http` 生产链路完成，只记录 URL/参数/字段名，原始页面只落盘 `%TEMP%\jw_probe\` 不入仓）。规格 `_audit/jw_entry_20261113/JW_CARDS_V1_SPEC.md`、契约 §6。

### ① 官方接口勘察结论（2026-11-14）
- **数据接口（只读 GET，layui `pageNum`/`pageSize` 分页）**：成绩 `/jsxsd/kscj/cjcx_list`、考试 `/jsxsd/xsks/xsksap_list`、选课轮次 `/jsxsd/xsxk/xklc_list_data`、公告 `/jsxsd/ggly/ysgg_query?type=list`；响应 `{msg,code,data,count}`，行字段名见规格 §2。
- **官方快捷菜单 8 项**（实测自 `xsMainV_new` 的 `kjcdShow`）：学期理论课表 `/jsxsd/xskb/xskb_list.do`、课程成绩查询 `/jsxsd/kscj/cjcx_frm`、学生选课中心 `/jsxsd/xsxk/xklc_list`、考试安排查询 `/jsxsd/xsks/xsksap_query`、培养方案明细 `/jsxsd/pyfa/topyfamx`、已收公告 `/jsxsd/ggly/ysgg_query`、缓考申请 `/jsxsd/kscj/hksq_query`、社会考试报名 `/jsxsd/xsdjks/xsdjks_list`。
- **实测态（如实）**：本账号大一第一学期，4 接口 `count` 全 0（成绩未公布/无考试/无选课轮次/无公告），空态是正常路径；**有数据行渲染未用真实有数据账号验证**（合成夹具覆盖）。

### ② App 实现（android-class-tools v4.48.0 / vc66）
- 点「教务」卡 → App 内**卡片页**：4 张数据卡（成绩/考试/选课/公告，官方 JSON 接口）+ 8 张官方工具入口卡 + 「打开完整教务官网」；点任意卡 → 内置 WebView 全屏打开官方页面，返回回卡片页；返回键 WEB→卡片页→退出。
- 新增 `data/jw/JwApiModels.kt`（宽松信封 + 4 类行模型）、`JwApiClient.kt`（URL/参数/Cookie/UA/Referer/X-Requested-With/Accept；HTML→会话失效闸门；宽松 JSON 解析；复用既有 HttpTransport）、`JwCardsRepository.kt`（coroutine 并行 4 接口、单卡失败隔离、cookie 缺失短路）；`ui/screens/jw/JwCardModels.kt`（卡片视图模型/文案/映射）、`JwCardsSection.kt`（卡片页 UI：状态条/数据 2 列/官方工具 2 列/完整官网）。
- 改造 `ui/screens/jw/JwEntryScreen.kt`（27734B）：LOGIN/CARDS/WEB 三模式；复用 v4.46.1 自动登录（sso.jsp→authserver 注入→回 210 成功）/验证码回退/本机 Keystore 凭据/一次性密码弹层/清除登录；登录成功取 `CookieManager` 同域 cookie 拉数据；会话失效自动重登 1 次；刷新/单卡重试。
- 安全：写操作只在官方页面内；密码仍只本机 Keystore 加密保存；cookie 只在请求瞬间使用、不落盘/不打日志/不上传；卡片数据只内存；「清除登录」清密码+Cookie+WebStorage+缓存。
- 共享文件：`build.gradle.kts` 4.48.0/vc66、`ToolCatalog` jw subtitle/features、`GuideContent` VERSION 2026-11-14.1 + jw 卡文案、`UserGuideContentTest`、`docs/CHANGELOG` v4.48.0 条目（android 仓库内）。
- 并行冲突处置：新增文件先写；共享文件先落 `_audit/jw_entry_20261113/android_jw_cards_shared_edits_pending.md` patch，监控并行会话静默 ≥5 分钟后按当前内容精确补回（保留并行 13:09 的「点名 roll」条目），构建/测试期间无并行写盘。

### ③ 测试 / 产物 / 状态
- 单测 **1177/0**（93 suites；新增 JwApiClientTest 20 / JwCardsRepositoryTest 8 / JwCardModelsTest 14，全合成 JSON，无真实账号/数据）；Lead 独立复跑 `:app:testDebugUnitTest` BUILD SUCCESSFUL + 聚合 1177/0/0/0。
- Release `artifacts/classtools-4.48.0-release-signed.apk` **3,141,837 B / SHA-256 `7543DAE44153ABF42525F2D62446058607E26B5FA0B7F8ED0B4BCE5D22E649B9`**（vc66，v2 签名 Verifies；dex 已核验含 4 个官方接口路径与「学期理论课表/打开完整教务官网/官方工具/卡片速览」文案）；`assembleRelease --no-build-cache --no-daemon` 2m14s。
- Android 仓库 HEAD 仍为并行会话的 `47d8f56 v4.47.1`（本次改动未提交，仓库无远端；APK 含并行未提交 WIP，无法仅由 HEAD 复现）。

### ④ 已知限制 / 回滚
- 未真机/真实有数据账号验证；官方接口/页面改版 → 卡片降级空态/失败态（不崩溃）并保留「打开官网」；验证码→手动回退；WebView 依赖系统内核。
- 回滚：删除新增 8 个 jw 卡片文件 + `JwEntryScreen.kt` 回 HEAD（v4.46.1）+ 共享文件按 pending 文档反向 edit + 版本号回退 4.47.1；APK 回退上一版 `classtools-4.47.1-*`（3,141,833 B）。

## 2026-11-13 21:38–22:1x · 增量 55：网页端教务入口改「点卡片直接进入 + 浏览器自动填充」（取代增量 54 的中间入口页；**网页已上线 OSS+ECS**；小程序入口已按用户要求撤销；安卓 WebView 直进+自动填充另行交付）

> 用户原话（2026-11-13 21:38）：「把网页端和app的教务系统入口改直接进入同时附带自动填充账号密码功能，取消微信小程序端的教务系统入口」。已确认口径（契约 §5.0）：网页端 = **直跳 + 浏览器自带密码保存/自动填充**（本站不接触、不保存教务密码）；安卓 = 本机 Keystore 加密保存 + 自动登录；小程序 = 取消入口。本增量只做网页端；安卓/小程序由并行会话按契约 §5.3/§5.4 负责。

### ① 关键事实（契约 §5.1，实现不得假设相反）
- 学校统一认证登录页**不支持 URL 预填账号**（`?username=` 不生效）；浏览器安全模型**禁止本站跨域读写 authserver 登录表单** → 网页端无法真正代填。
- 因此网页端唯一可行形态 = **点「教务」卡片直接顶层打开教务系统 + 交给浏览器密码管理器**（首次登录手动输入并勾选「保存密码」，之后由浏览器自动填充）。

### ② 网页实现（`tools/index.html`，APP_VER 仍 2.0.0）
- **删除中间入口页**：`#s-jw` section（`__JW_ENTRY_V1_BEGIN__`/`_END__`）、其 CSS（`__JW_ENTRY_V1_CSS__`）、旧「复制链接」JS 全部移除；`TOOLS` 的 jw 条目改为链接型工具：加 `url:"http://210.34.74.77/sso.jsp"`。
- 新 JS 块 `/* __JW_ENTRY_V1_JS__ */`（主 IIFE 内、UG 块之后）：`JW_URL`、`isLinkTool(k)`、`openJwDirect()`（创建真实 `<a target="_blank" rel="noopener noreferrer">` 并 `click`，兜底 `location.href`）、`firstPageTab(home)`、只读探针 `window.JW={url,open}`（`Object.freeze` + `writable:false`）；**无定时器 / 无轮询 / 无网络请求**。
- **包装 `gotoTab`**：`isLinkTool(k)` → `openJwDirect()` 后 `return`（不切页、不改 `CURTAB` / history / POS）；「全部」页卡片点击与顶部工具栏 tab 点击都走这条路径；卡片按钮文案改为「进入」（`label:(t.url?"进入":"打开")`）。
- **滑动引擎**：`targetFor("tool")` 与抽签 STEP 边界切工具统一走 `nextPageTabIdx()`，**跳过链接型工具**（jw），避免滑动/边界切页误开新窗口。
- **恢复路径防护**（新增，防无手势自动打开外站）：`POS.begin` 中 `tool.url` 的位置恢复视为无效；`popstate` 遇到旧 history 里的 `jw` 直接跳过；`renderTabs` 默认落地页与非法 tab 归一都用 `firstPageTab(home)`（工具栏第一个非链接工具）。因此：刷新、返回键、旧 sessionStorage/history 数据都不会自动弹出教务站。
- **卡片点击双触发修复**：`renderAllCards` 原先对「卡片容器」与「卡片内按钮」各绑一次 `gotoTab` 点击处理；普通工具页两次调用幂等无感，但链接型工具会**一次点击打开两个窗口**。改为只绑定卡片容器（按钮点击自然冒泡），jw 卡「进入」按钮现只打开 1 次。
- 使用说明 `__UG_CARDS_V1__` jw 卡文案改为「点卡片直接打开教务系统 / 首次登录时勾选浏览器『保存密码』/ 之后打开即自动填充账号密码」+ tip「自动填充由浏览器完成；校外打不开时先连学校 VPN」。
- 红线核对：页面加载/切页/点击阶段对 `210.34.74.77`、`authserver.fjtcm.edu.cn` **零请求**（全 HTML 仅 2 处教务 URL：`TOOLS.url` + `JW_URL`）；不嵌 iframe、不采集/不保存账号密码、单文件零依赖、APP_VER 仍 2.0.0。

### ③ 测试（实跑）
- 重写 `tools/tests/v2_jw_check.py` **55/55**（静态 14 + 运行时 41）：430/360/390/1280 四档 × **两条用户路径**（「全部」页点 jw 卡、顶部工具栏「教务」tab）→ mock anchor click 断言 `href/target/rel` 正确且**不切页**（`CURTAB` / `section.on` / history.length / history.state 不变）；程序化 `gotoTab("jw")` 与 `window.JW.open()` 同路径；`isLinkTool('jw')===true`；旧 `zq_pos_v1 tab=jw` 恢复不自动打开；**卡片内「进入」按钮只打开 1 次（防双开）**、**点拖动手柄不打开**；0 JS 报错 / 0 console.error / 0 外部请求（含 210.34.74.77 与 authserver，加载+全流程两阶段）/ 无横向溢出；截图 5 张 `tools/tests/_shots_jw/`（全部页 430/360/390/1280 + 430 工具栏含教务 tab）。
- 回归：`overflow_check` 430/360/390 overflowCount=0、`v2_ui_check 27/27`、`v2_drag_check 69/69`、`v2_ug_check 56/56`、`optim_v1_check GREEN`、`optim_v2_check main 16 + admin 70 + hash 4 全 GREEN`；额外受影响面 `v2_pos_restore_check 12/12`。
- 测试身份 `SID=9999000005 / 测试同学`（9999 段 mock，符合 AGENTS §0-7）；未使用真实账号/未读密钥/未真实写云端。

### ④ 状态 / 回滚
- 本次网页**已上线 OSS+ECS**：线上 **1,232,963 B / sha256 `b47c6bb7ec0934d7be2793cf921b80d3a1340c0ad34ed9aedf289e2aa521c236`**（`deploy/oss_object.py check index.html` = MATCH；`python deploy/ecs_site.py verify` = MATCH（ECS_IP 直连字节校验），gzip 382,777 B；ECS 直连实取同字节且含 `url:"http://210.34.74.77/sso.jsp"` / `isLinkTool`、**无**旧 `#s-jw` 页）。部署前线上备份 `tools/_backup/index_online_20261113-2205_preJwDirect.html`（1,233,447 B / `de932bfa…`）。
- Lead 独立复跑（非仅 web-dev 自报）：`v2_jw_check 55/55`、`overflow_check 430`=0、`v2_ug_check 56/56`、`v2_drag_check 69/69`、`v2_ui_check 27/27`、`optim_v1_check` GREEN。
- 回滚：重传上述部署前备份后 OSS+ECS apply；或 revert 本次 `tools/index.html` / `tools/tests/v2_jw_check.py` hunk（恢复增量 54 的中间入口页）。APP_VER 仍 2.0.0；无 DB / `userdata` v6 / 云函数变更。
- 小程序：按用户 21:38 要求**取消教务入口**（删除 `utils/tools.js` 的 jw、`pages/jw/`、`images/tool-jw.png`、`app.json` 注册、`pages/ug/ug.js` 使用说明卡；`VERSION` 仍 2.0.0，unit 536/0、tool_sort 21/0、ug_cards 59/0、sync 34/0、staticcheck/code_quality exit 0），需用户重新上传发布。
- 已知取舍（如实）：自动填充完全由浏览器密码管理器决定（首次需手动登录并勾选保存；不同浏览器策略/隐私模式可能不填充；本站无法检测、无法代填、不保存任何教务凭据）；教务系统为 HTTP，只能顶层导航；若用户曾在增量 54 把「教务」拖入工具栏，55 版工具栏仍可含「教务」tab（点击直接打开），但默认落地页/恢复路径会跳过它。

## 2026-11-13 18:4x–19:1x · 增量 54：三端新增「教务」入口——网页「教务」工具卡 + 统一身份认证直达页（网页已上线 OSS+ECS；小程序源码待用户上传发布；安卓 4.45.0 APK 已交付）

> 需求（用户原话）：「帮我在班级工具站三端加个教务网站的入口」；已确认口径见唯一契约 `_audit/jw_entry_20261113/CONTRACT.md`：指向新版教务管理系统 `http://210.34.74.77/sso.jsp`（学校统一身份认证 SSO；教务系统只有 HTTP，**只能顶层导航**，不得 iframe 内嵌/子资源），形态 = 新增「教务」工具卡（全部页可拖入顶部工具栏）。

### ① 网页实现（`tools/index.html`，APP_VER 仍 2.0.0）
- `TOOLS` **末尾**追加 `{k:"jw",n:"教务",d:"成绩 · 选课 · 考试；统一身份认证直达教务系统"}`（不插中间，工具栏补齐/滑动顺序不变）；`ALL_TONE.jw="blue"`。
- 新增 `#s-jw` 页面（`<!-- __JW_ENTRY_V1_BEGIN__ -->`/`_END__` 包住；位于 `#s-vote` 之后、`<!-- __WEB_B2_FILE_BEGIN__ -->` 之前）：标题「教务管理系统」、短描述「成绩 · 选课 · 考试」、主按钮 `<a class="btn pri" id="jwOpen" href="http://210.34.74.77/sso.jsp" target="_blank" rel="noopener noreferrer">打开教务系统</a>`、`<button class="btn ghost" id="jwCopy" type="button">复制链接</button>`、URL 小字、提示行「统一身份认证登录 · 打不开时先连学校 VPN」。
- CSS `/* __JW_ENTRY_V1_CSS__ */`（`</style>` 前）：少量 `.jw-*`；锚点按钮 inline-flex 居中、`text-decoration:none`；点按高度 44px；≤380px 按钮整行；360/390/430 实测无横向溢出。
- JS `/* __JW_ENTRY_V1_JS__ */`（**主 IIFE 内部**、UG 块之后、脚本收尾 `})();` 之前）：`#jwCopy` → 优先 `navigator.clipboard.writeText`，回退隐藏 textarea + `execCommand`（与站内 `fb()` 同法）→ 复用闭包 `toast("链接已复制")`；暴露只读探针 `window.JW={url}`（`Object.freeze` + `writable:false`）；无定时器/轮询/网络请求。
- 使用说明 `__UG_CARDS_V1__` 的 `CARDS` 追加第 18 张 `jw` 卡（`cat:"study"`、标题「教务入口」、scene 复用 `list`、tone blue、3 步 + tip），不新增配图；轮播/总览/页码随之 17→18。
- 红线核对：页面加载与切页阶段对 `210.34.74.77` **零请求**（全 HTML 仅 3 处 URL：锚点 href、URL 文本、`JW_URL` 常量）；不嵌 iframe、不采集账号密码、单文件零依赖、APP_VER 仍 2.0.0。

### ② 测试（实跑）
- 新增 `tools/tests/v2_jw_check.py` **64/64**（静态 16 + 运行时 48）：430/360/390/1280 四档 × **两条进入路径**（`gotoTab("jw")` 与「全部」页点 `#allCards [data-card="jw"]`）→ `#s-jw` 可见；`#jwOpen` href/target/rel 逐字校验；`#jwCopy` 点击 → mock 剪贴板收到教务 URL 且 toast「链接已复制」；0 JS 报错、0 console.error、0 外部请求（含 210.34.74.77，页面加载+切页两阶段）、无横向溢出、点按 ≥40px、锚点无下划线；**J34 作用域锁定**（闭包 toast/copy 为函数、`window.toast` 只是 id=toast 的 DOM 元素，防 JS 块被移出主 IIFE）；截图 5 张落盘 `tools/tests/_shots_jw/`。
- 回归：`overflow_check` 430/360/390 overflowCount=0、`v2_ui_check 27/27`、`v2_drag_check 69/69`、`v2_ug_check **56/56**`（卡片数按新事实 17→18：S9/R1/R2/R5/R6/R7/R8/R10/R13/R14/R15/R16/R27 期望更新，未放宽断言）、`optim_v1_check GREEN`、`optim_v2_check main 16 + admin 70 + hash 4 全 GREEN`。
- 测试身份：`SID=9999000005 / 测试同学`（9999 段 mock 身份，符合 AGENTS §0-7）；未使用真实账号、未读密钥、未真实写云端。

### ③ 三端同步落地（Lead 汇总）
- **网页已上线 OSS+ECS**：线上 **1,233,447 B / sha256 `de932bfab059a908d2b8b0f49adf963730e970d7ee5e7519ab58f2e5c38af266`**（`deploy/oss_object.py check index.html` = MATCH；`python deploy/ecs_site.py verify` = MATCH（脚本按 ECS_IP 直连字节校验）；直连 `https://tool.furina.fun/` 实取 1,233,447 B / 同一 sha 且含教务入口；gzip 382,493 B）；部署前线上备份 `tools/_backup/index_online_20261113-1902_preJw.html`（1,228,439 B / `89685d55…`）。
- Lead 独立复跑：`v2_jw_check 64/64`、`run/overflow_check 430 overflowCount=0`、`v2_ug_check 56/56`、`v2_drag_check 69/69`、`v2_ui_check 27/27`、`export_check draw` PASS；`selfcheck.py` 为身份门禁前旧脚本（引用已删除 `#aRoster`），HEAD 基线同样 FAIL，按既有文档口径不作门禁。
- **小程序源码已改、待用户微信上传发布**（`mp-class-tools`，VERSION 仍 2.0.0）：`utils/tools.js` TOOLS 末尾追加 `jw`、新增 `pages/jw/jw.{js,json,wxml,wxss}` + `app.json` 注册、`images/tool-jw.png`（96×96 透明底白色校舍 glyph，1,643 B）、`pages/ug/ug.js` 使用说明新增「教务入口」卡（19→20 卡）；页面只做「复制链接 → 手机浏览器打开」（个人主体无 web-view/外链能力），`wx.setClipboardData` + toast「链接已复制，请在手机浏览器打开」；实跑 `unit.js 537/0、tool_sort_unit 21/0、ug_cards_check 60/0、sync_contract_test 34/0、staticcheck/code_quality exit 0`（含 test-only 修复 5 个既有红用例：作业夹具日期腐烂 + tool_sort 缺 file 期望）。
- **安卓 4.45.0 / vc61 APK 已交付**：`data/tool/ToolCatalog.kt` 追加 `jw`（School 图标 / BrandSlateBlue / 学习分类）、新增 `ui/screens/jw/JwEntryScreen.kt`（ACTION_VIEW 打开 + 剪贴板复制 + URL / 提示行）、`MainNavHost` 路由分支、使用说明第 21 卡；`testDebugUnitTest` **1112/0**（89 suites，+JwEntryTest 8），Release **3,108,633 B / SHA-256 `39458E83C0EEBF64187F29DA48051B2F832E7B204E061E95F972D5F3805CFA41`**（`android-class-tools/artifacts/classtools-4.45.0-release-signed.apk`，v2 签名验签通过、dex 内已核验含教务 URL/文案；APK 以当前工作树构建，含并行会话未提交 WIP）。
- 回滚：网页重传上述部署前备份后 OSS+ECS apply；小程序回退源码；安卓回退上一版源码/APK 4.44.0（`0F37DA73…`）。本功能无 DB / `userdata` v6 / 云函数变更。

## 2026-11-12 22:2x–22:4x · 增量 53：手机比例修复（电费同期比较被裁切 / 团员人数首次不显示）+ 全站手机比例审计（网页已上线 OSS+ECS）

> 用户反馈：「网页修复手机比例下电费对比无法正常显示的问题，同时检查各处是否有未适配手机比例的场景，修复团员人数初次点击不显示的问题」。

### ① 电费「自然周期同期比较」手机比例下不显示（P0 修复）
- **根因**：比较徽标由 OPTIM V2 `opt2PowerDelta()` 追加进「区间用电」tile 的 `.pw-ts` 子行；该行 `white-space:nowrap;overflow:hidden;text-overflow:ellipsis`。手机 2 列 tile 宽仅 176–196px，`≈ ¥2.61 电费 · 较昨日同期 +100%` 需要 177px+，实测 390 宽被裁 13px、430 宽被裁 11px、360 更宽；1280 桌面 tile 311px 可完整显示 → 只在手机比例暴露。
- **修复**：`opt2PowerDelta()` 改为在 tile 内 `.pw-ts` **之后另起一行** `.pw-cmp`（新增 `.pw-tile .pw-cmp{font-size:11px;line-height:1.35;margin-top:2px;white-space:normal;overflow-wrap:anywhere}`），比较文案不再参与单行 ellipsis；保留 `.opt-pw-delta` 类、title 与涨跌配色，24h/7d/30d 及慢楼栋逻辑不变。实测 360/390/430 均为独立一行完整显示「较昨日同期 +N%」。

### ② 团员人数「初次点击不显示」（P1 修复）
- **根因**：`团员` tab 人数徽标 `#cmCntL` 只在 `renderCommittee()` 里由 `CM_LEAGUE` 计算，而团员名单只在**点击团员 tab 之后**才懒加载；首次进入名单页时徽标为空；点击时 `renderCommittee()` 与 tab 点击处理器各发一次 `class_league`（真实云端实测 2 个并发请求 160/202ms），慢网下首次点击瞬间人数仍空白。
- **修复**：`cmLeagueFetch()` 增加 `CM_LEAGUE_P` **并发去重**；`renderCommittee()` 在 `CM_LEAGUE===null` 时**进入名单页即预取**并自动重渲染；tab 点击不再二次请求；加载失败显示「—」（不再误显示 0）。真实本地通道（官方测试身份）实测：进入名单页 0.15s 内自动显示团员 50 人、全程仅 **1 次** `class_league` 请求；点击团员 tab 即时 50 行。
- 影响面：名单工具（网页）；`optim_v2_check` 名单三 tab 用例同步复跑 GREEN。

### ③ 全站手机比例适配审计（本次范围）
- **自动化审计**：网页 16 个工具页（抽签/课表/作业/通知/体测/点名/名单/诊断/电费/水量/演示/投票/文件/反馈/使用说明/全部）× 360/390/430 竖屏 + 844×390、932×430 手机横屏 → 页面级横向溢出全部 **0**；弹层实测 rosterModal / 电费关注宿舍选择器 / 投票发起 / 通知提醒 / 抽签名称映射（390、320、375、844×390）均在视口内且可滚动；大屏 V4 手机竖屏自动单列堆叠、可滚动操作；320 小屏无溢出。
- **结论**：本次审计范围内唯一未适配场景即 ①（已修）；②为加载时序问题（已修）。其余页面无需新增样式改动（未为适配而改桌面布局）。
- 审计脚本为临时本地脚本（未入库）；防回归落在：`v2_power_trend_compare_check.py` 新增 A9/D2b/D3b/D4/D5/D6（手机比例比较行完整显示且不撑破），新增 `tools/tests/v2_committee_league_check.py`（静态 + 运行 30 项）。

### 测试（实跑）
- `v2_power_trend_compare_check.py` **38/38**（原 32 + 手机比例 6：430/360/390 比较行不裁切、独立成行、不撑破）
- 新增 `v2_committee_league_check.py` **30/30**（进入即预取 / 只发 1 次请求 / 首次点击列表与人数 / 切走切回不重复 / 390 与 844×390 无溢出 / 0 报错 / 0 外部请求〔既有大屏 presence 基线除外〕）
- 回归：`power_check 155/155`、`v2_ui_check 27/27`、`overflow_check 430/360 = 0`、`v2_ug_check 56/56`、`v2_drag_check 69/69`、`optim_v2_check GREEN`（含名单三 tab 计数/列表）
- 真实链路：本机临时通道 + 官方测试身份（3260799999/测试账号）→ 名单页自动 50 人、单请求、0 JS 报错；未使用任何真实账号、未读密钥。

### 上线 / 回滚
- 部署：`python deploy/sync_tools.py index.html` + `python deploy/ecs_site.py apply` → OSS/ECS **1,228,439 B / sha256 `89685d55858eac107ca284f8307e2127e396f1ba4eab3e14035fc22f05b08265`**（`oss_object.py check` MATCH、ECS verify MATCH、gzip 380,687 B）。
- 部署前线上备份：`tools/_backup/index_online_20261112_2238_prePowerCmpMobile.html`（1,227,464 B/`891a6389…`）。
- 回滚：重传该备份（OSS+ECS apply）；**无 DB / userdata v6 同步契约变更**。

---

## 2026-11-12 21:0x–21:5x · 增量 51：三端「使用说明」卡片化重构（网页已上线 OSS+ECS；小程序源码待用户上传发布；安卓 APK 已交付）

> 用户需求原话：「对三端使用说明进行重构，从文字堆叠改为卡片展示，左右滑动切换卡片，且加入一键总览等按钮的形式，可加入一定配图对功能说明，重写使用说明，使其更清晰易懂」。

### 共享契约
- 新增 `《使用说明·卡片化重构》契约（内部归档）`（三端唯一契约）：一屏一张卡 + 左右滑动切换 + 一键总览 + 分类快捷标签 + 上一张/下一张 + 11 种配图 scene + 文案硬规则（标题≤8 / 作用≤20 / 步骤≤24 / 提示≤30）；三端按本端真实功能实现，不写别端入口。

### 网页（`tools/index.html` `__UG_CARDS_V1__`；已上线）
- `#s-ug` 重写：**17 张卡片横向 scroll-snap 轮播**（一屏一张、首尾 clamp、触摸/触控板/鼠标拖动跟手）+ **5 个分类 chips**（点跳该分类首卡、分类高亮、点按高度 40px）+ **一键总览弹层**（按分类分组、桌面 ≥960px 两列、点条目关闭并跳卡、遮罩/×/返回键/Esc 关闭，关闭不误弹「再按一次返回退出」）+ 上一张/下一张/页码/进度条 + 键盘 ←/→。
- 配图：11 个内联 SVG symbol（picks/steps/grid/list/chart/people/transfer/ballot/droplet/shield/slides），**零外部请求、零图片请求**；修复 `<use>` 百分比尺寸导致的非等比拉伸/裁切。
- 文案全部重写去重（删除原使用说明里重复的「文件传输」「水量」「通知提醒」条目）；保留既有测试断言短语（重置 / 名单不支持自定义输入 / 关注宿舍按楼栋 / 不提供 24h）。
- 手势：全局滑动引擎 `resolveStart()` 排除 `#ugPager` / `#ugOv`（卡片横滑与总览内滑动不切工具）。
- 测试：新增 `tools/tests/v2_ug_check.py` **56/56**（静态 20 + 运行时 36：430/360/390/1280 四档、翻页、分类跳转、总览开关/点跳/返回键/Esc、键盘、无横向溢出、0 JS 报错、0 console.error、0 外部请求、所有按钮点按 ≥40px；截图 `tools/tests/_shots_ug/`）。
- 回归：`v2_ui_check 27/27`、`overflow 430=0`、`v2_drag_check 69/69`、`v2_pos_restore 12/12`、`v2_swipe_perf PASS`、`v2_power_pick_mem 48/48`、`v2_power_trend_compare 32/32`；`vote_check 82/83`、`reset_check 108/109`、`roster_check_verify 154/157` 的唯一失败均为并行会话大屏 presence 外部请求（已知基线噪音），`v2_scroll_check 36/40`（C7/C8/C9/G3）与改造前副本逐项一致。
- 兼容性适配：使用说明不再长滚动，`v2_pos_restore_check` / `v2_scroll_check` / `v2_swipe_perf` 中把「使用说明」当长滚动代表页的几处改用「全部」页（断言不变，理由写在测试注释）。
- 部署：`python deploy/sync_tools.py index.html` + `python deploy/ecs_site.py apply` → OSS/ECS **1,227,464 B / sha256 `891a6389edf18143d4e75bac168fde9f113001cc323e3159f880b0defeb77b19`**（`oss_object.py check` MATCH、ECS verify MATCH、gzip 380,265 B）；部署前线上备份 `tools/_backup/index_online_20261112_2124_preUGdeploy.html`（1,163,168 B/`c4676d57…`）。
- 回滚：重传上述备份（会同时回退并行会话在本功能之后的改动；若只回退使用说明，可 revert 本提交中 index.html 的 `__UG_CARDS_V1__` 相关 hunk）；无 DB / 同步契约变更。

### 小程序（`pages/ug`；源码待用户上传发布）
- 重写为 **swiper 19 卡**（id/顺序按契约 §4.2）+ 分类 chips + 总览遮罩清单 + 上一张/下一张/页码 + **11 类 WXSS 形状配图（0 新增图片资源）** + 全量重写文案；top-app-bar 标题置空避免与原生导航栏重复；保留 share / agent handoff / scrollmem / 身份校验，版本仍 2.0.0。
- swiper 高度用 `createSelectorQuery` 实测卡片最大高度后 clamp 屏幕可用高度；内容装不下回退「内容高度 + 卡内 scroll-view」，不截断。
- 测试：Lead 复跑 `unit.js 535/0`、`staticcheck.py exit 0`、`code_quality_check.js` 全规则通过、新增 `ug_cards_check.js 59/59`；automator（390 宽）`ui_scroll_test 10/0`、`perf_ug_preview 10/0`、`ug_cards_shot 7/0`（19 卡逐张截图 `_shots_ug_cards/`，0 console error）。
- 已知：仅开发者工具 390 宽验证，未真机；发布前仍需按既有流程处理微信后台合法域名（与本功能无关）。

### Android（`ui/screens/guide/`；APK 已交付）
- `UserGuideScreen.kt` 重写 + 新增 `GuideContent.kt` / `GuideScenes.kt`：CtTopBar（右侧「总览」）+ 5 分类 chips + **`HorizontalPager` 20 卡** + 11 种 scene Compose 自绘（无图片依赖）+ 底部上一张/页码/下一张（≥48dp、首尾禁用、clamp 不循环）+ `ModalBottomSheet` 分组总览（点条目关 sheet 并跳卡、BackHandler 关 sheet）+ 卡内 verticalScroll；`UserGuideContent.VERSION="2026-11-12.1"`；全局版本号未改。
- 测试：新增 `UserGuideContentTest` **13/13**（20 卡/id 唯一/分类合法/文案长度/事实/VERSION/Android 独有 reminder·calendar·permissions）；`:app:testDebugUnitTest` **1098/0**、`assembleDebug` 通过、`assembleRelease` 成功。
- APK：`%USERPROFILE%\Desktop\classtools-4.42.0-ug-cards-release-signed.apk`（3,075,869 B / sha256 `352E0C9F78ADBD045C35A84BFE79BF8637DC5F75C235DA322F4E8C343D3283C7`，v4.42.0 / vc58，apksigner 验证通过）。注意：该 APK 构建自当前工作区，**同时包含并行会话未提交改动**（版本号 4.42.0/vc58 由并行会话维护，本功能未改全局版本号）。

### 独立验收
- `验收报告/使用说明_重构_独立验收_20261112.md`：QA 独立复核三端 **PASS（P0=0 / P1=0 / P2=1 记录豁免）**——web 自研 CDP 真实触摸驱动 122/122、`v2_ug_check 56/56`、上线对象三方字节一致；mp 535/0 + staticcheck/ug_cards_check；android 单测复跑 1098/0。初验 P1（chips 34px<40px）已修复重新上线，P2 已修 4 项（桌面两列总览 / power 提示长度 / fb 文案 / nt「右下提醒」位置），SVG 阴影色按记录豁免。

---

## 2026-11-12 21:00–21:35 · v2.0.0 增量 52：抽签升级 v1——云端存证防作弊 + 今日抽签次数 + 自定义序号名称映射（网页已上线 OSS+ECS / 小程序源码待用户上传发布）

> 用户需求：「抽签导出图片还是会被质疑有作弊」+「重新将可自定义序号对应的名称功能添加回来（可将序号对应组名等）」。唯一契约 `web/draw/CONTRACT.md`；范围=网页+小程序源码（安卓本轮不做）。

- **云端**（迁移 `deploy/cloudbase/2026-11-12_draw_proof.sql`，已应用 **38 statements / fails=0**）：新增 `public.draw_records` + `public.draw_events`（RLS 开启 + 0 策略 + REVOKE ALL → 直连 401；仅 SECURITY DEFINER RPC 访问）与 6 个 RPC（`draw_record_create` / `draw_event_append` / `draw_record_get` / `draw_record_list` / `draw_test_purge` / `draw_test_clear`）+ 4 个内部归一函数；服务器时间 + Asia/Shanghai 当日 `seq_day`/`today_count`/`today_mine`（is_test 口径隔离：测试身份记录真实用户不可见、不计真实次数），哈希链 `prev_hash`，`canon`（12 行固定规范）+ sha256，params/pool/result/labels 服务端白名单归一，`pg_advisory_xact_lock` 并发取号，响应不含学号；测试记录已清零。
- **网页** `tools/index.html` 新块 `__DRAW_PROOF_V1__`：STEP1 新增「名称映射」面板（`D.d.draw.names`，格式 `序号 名称`，优先级 映射 > 班级名单派生名 > 空；`UD_DRAW_KEYS` 增 `names`、旧数据按空，不新增顶层键）；每次点「开始抽签」= 一条云端存证（draw-v1 种子算法：seed+pool 可复算，替换原 Math.random 洗牌），结果区显示「已存证 · 今日第 N 次（全班今日共 M 次）」；「抽签记录」弹层（今日/全部、详情、算法复算 ✓、哈希自检 ✓、`#verify=<id>` 深链（登录后打开；初始化时先收 id + replaceState 清 hash，关闭不重开））；剔除/补抽/重置追加事件；导出图 `rec`=存证编号、参数区存证编号/时间(秒)/今日次数/记录哈希、QR=核验链接（`qrTitle/qrCap`，`export_card_v2_spec.md` 已同步）、未存证降级标注；跨端同步 `draw.names` 走既有 draw section。
- **小程序源码**（待用户上传发布）：新增 `utils/drawproof.js`（draw-v1 算法/名称映射/RPC 封装/记录视图模型）+ `pages/draw` 名称映射弹层/存证状态/事件/导出核验二维码 + 新增 `pages/drawrec`（今日/全部/详情/深链，app.json 注册）+ `utils/canvas.js` 可选 qrTitle/qrCap + `utils/cloud-config.js webBase`（临时 ko-link.cn，恢复后改回）；VERSION 仍 2.0.0、零新依赖。
- **测试（真实跑过）**：云端 `draw_cloud_check.py` **179/179**（连续两次）+ QA 独立 probe **78/78**；网页 QA mock **166/166** + 真实云端 E2E `draw_live_check.py` **45/45**（本地临时通道+测试身份+CDP 写白名单+finally 清理）；回归 export_check draw PASS、v2_ui 27/27、overflow 430=0、v2_drag 69/69；roster 197/199 与 sync 142/144 的 4 项均为并行会话/既有 drop presence 的已知非本功能失败。小程序 `drawproof_unit_tests 35/0`、`unit.js 535/0`、`sync_contract_test 34/0`、staticcheck/code_quality exit 0。独立验收报告 `web/验收报告/抽签存证与名称映射_独立验收_20261112.md`（P0/P1=0）。
- **上线**：网页 **1,227,297 B / sha256 `4a6a49ba…`**（OSS `check index.html` MATCH、ECS verify MATCH；本轮与并行会话合并部署）。回滚 `tools/_backup/index_online_20261112-2132_preDrawProof.html`（1,163,168B/`c4676d57…`）；SQL 回滚见迁移文件头；小程序回退源码。
- **已知取舍**：存证只覆盖主抽签工作流（大屏快捷抽签/分组不存证）；名称映射只影响显示/导出（不限制抽签池；抽签后改映射不改已存证 labels）；真实用户今日次数=全班共用（同一 is_test=false 桶）；测试身份记录不显示/不计数。

## 2026-11-12 21:20–21:25 · 修复 IP/临时域名访问登录「网络错误」（Caddy 同源反代去 Origin）

- 用户反馈 `https://tool.furina.fun/` 登录提示「网络错误」。根因：CloudBase 网关 Origin 白名单只含 `https://tool.furina.fun` / `http://127.0.0.1:*`，而浏览器对同源 POST/PATCH/DELETE 也会带 `Origin: <当前访问域名>`，经 Caddy `/v1/rdb/rest/*` 反代原样透传 → 网关 **403**（`ko-link.cn`、IP、OSS 域名、`null` 实测均 403；`tool.furina.fun`/`127.0.0.1` 200）。
- 修复：`deploy/ecs_site.py` 三处 `/v1/rdb/rest/*` 反代块加 `header_up -Origin`（同源请求不需要 CORS；鉴权仍是 Bearer anon key + `X-Device-Id` 班级 token，不变）。
- 部署：`python deploy\ecs_site.py apply --https`（ECS Caddy 生效，`grep -c 'header_up -Origin' /etc/caddy/Caddyfile` = 2）；带 Origin 的请求返回 401（需鉴权）而不是 403。
- 验证：headless Edge 打开 `https://tool.furina.fun/` 用测试身份 `3260799999/测试账号` 登录成功（auth-pending 移除；`class_verify`/`class_members`/`fitrecs`/`marks`/`userdata` 全 200；0 console error）。
- 副作用：只影响本机反代对网关请求头的处理；直连 CloudBase 网关的页面仍受网关白名单约束。ko-link.cn 备案通过后同样走这个反代，无需再改 CloudBase 配置。
- 回滚：还原 `deploy/ecs_site.py` 三处 `header_up -Origin` 后重新 `apply --https`。

## 2026-11-12 20:58–21:50 · 长期通知优化显示（网页已上线 OSS+ECS；小程序源码已改，待上传发布）

> 用户需求：「对长期通知进行优化显示，防止长期霸占通知前排」。确认口径：网页+小程序；长期通知 = 长期安排（recurrence）+ 无时间/长期有效通知；展示 = 主列表下方独立折叠区（默认收起），主列表只留时间明确、可处理的通知。规格 `tools/tests/notice_longterm_display_spec.md`。

- **网页模板**（源 `briefdesk-plan/build_notice_board.py`）：新增长期通知判据 `isLongtermGroup`（recurrence 或 无 deadline/eventAt/报名窗口且未过期）、`renderLongterm` 折叠区（主列表下方、已过期区上方；仅「全部」筛选；默认收起；折叠头「长期通知 · N 条」）、长期区排序（长期安排按下次发生升序 → info 按消息时间倒序）、待处理统计/简报/待处理筛选排除长期通知；长期区内标记已处理不回流主列表。`tools/build_notice_embed.py` OVERRIDE 补 `.lt-wrap` 底纹。
- **网页测试**：新增 `tools/tests/v2_notice_longterm_check.py` **26/26**（对最终线上字节实跑）；`v2_notice_live_check.py` 与 HEAD 基线一致（既有 L16 drop/presence 外部请求 FAIL 非本次引入）；`v2_ui_check.py` 27/27；briefdesk-plan 模板/嵌入三检查 PASS（TEMPLATE MATCH）。
- **网页上线（多次并行覆盖后的最终状态）**：最终线上 = **1,227,464 B / sha256 `891a6389edf18143d4e75bac168fde9f113001cc323e3159f880b0defeb77b19`**（并行已验收的抽签/使用说明内容 + 本增量通知模板 v2；OSS/HTTP IP/ECS 文件/http·https 域名均一致）；通知模板 112,609B / sha256 `f8284f9521fda39b446a410b394389323cc338a6eed25ba31e4f2778648b95af`；drop v2.3、pptfiles 健康。
- **HTTPS 两次被并行会话的 `ecs_site.py apply`（旧默认 HTTP-only）写没（21:23、21:40），21:46 已恢复**；根治：`ecs_site.py apply` **默认改为 HTTPS**（兼容 `--https`，新增 `--http-only` 显式降级），`deploy/ECS_DEPLOY.md` §3 同步说明。
- **小程序源码**（待用户上传发布）：`utils/notice.js` 新增 `isLongterm`/主列表排序/长期区排序并让 `statOf`/`mostUrgent` 排除长期通知；`pages/nt/nt.js` 三桶拆分 + 主列表改网页同口径紧急度排序（原 ts.asc 旧到新）+ `longtermCards/showLongterm/toggleLongterm` + `_cardById/patchCard/toggleDone/jumpPendingGid` 覆盖；`nt.wxml|wxss` 新增「长期通知 · N 条」折叠区（默认收起、42px 点按）；`pages/index/index.js` 工作台待办排除长期通知。测试：`unit.js` **536/0**（新增 `notice_longterm_unit.js` **13/13**）、`notice_time_test.js` 20/0、`sync_contract_test.js` 34/0、`staticcheck.py` exit 0、`code_quality_check.js` PASS；未跑 automator（9420 被其他会话占用）。`VERSION` 仍 2.0.0、UD v6 未动、零新增请求/依赖/外链。
- **独立验收**：`验收报告/长期通知优化_独立验收_20261112.md` —— **PASS，P0=0 / P1=0 / P2=0**（网页独立测试 43/43、线上 App 内嵌 12/12、小程序复跑 536/0 + 独立用例 49/49；原 3 项 P2 已修复复验，HTTPS 运维 P1 已消除）。
- **回滚**：网页重传线上备份（OSS+ECS apply）；小程序回退本次 5 个源码文件；模板源回退 `briefdesk-plan/build_notice_board.py` 本次改动（长期区相关函数与 CSS/HTML/JS 片段）；ECS apply 默认改动可保留（不回退更安全）。

## 2026-11-12 20:4x–21:0x · 临时切换公网域名到 ko-link.cn（HTTPS 已启用；网页已上线；小程序源码已改，待上传）

> 背景：`tool.furina.fun` 因备案/DNS 暂停不可解析，微信小程序体验版必须有 HTTPS + 已备案域名。用户提供阿里云同账号域名 `ko-link.cn`（注意实际是**连字符**，不是下划线）。

- **DNS**：阿里云 DNS 新增 `@` / `www` A → `tool.furina.fun`（TTL 600），公网已生效。
- **ECS/Caddy**：HTTPS 站点块改为同时服务 `tool.furina.fun, ko-link.cn, www.ko-link.cn`（`deploy/ecs_site.py`）；`ecs_site.py apply --https` 已启用 Caddy HTTPS，证书已签发。
- **实测**：`https://ko-link.cn/` 200（1,158,556B / `9fac5b58…`）、`https://www.ko-link.cn/` 200、`https://ko-link.cn/drop/__health` 200 version=2.3、`https://ko-link.cn/v1/rdb/rest/*` 同源反代 200、drop 签名下载 URL 为 `https://ko-link.cn/drop/file/...` 且真实下载 200（测试身份 probe，已清理）。
- **网页**：`tools/index.html` 运行时同源判断增加 `ko-link.cn` 及其子域（走同源 `/v1/rdb/rest` / `/drop` / `/pptfiles`）；线上 index **1,158,556 B / sha256 `9fac5b58…`**（OSS+ECS MATCH）。备份 `tools/_backup/index_online_20261112_preKoLink.html`（1,158,525B/`41dcfefc…`）。
- **小程序**：`utils/cloud-config.js` 临时 `dropBase: 'https://ko-link.cn/drop'`；体验版/正式版需在微信后台把 `https://ko-link.cn` 同时加入 **request 合法域名** 与 **downloadFile 合法域名**（域名需完成 ICP 备案），重新上传体验版。
- **后续切回**：`tool.furina.fun` DNS/备案恢复后，把小程序 `dropBase` 改回 `''`、重新上传即可；Caddy 已同时保留该域名，DNS 恢复后自动续/签证书。
- **待办**：小程序备案号展示（用户提供号码后加到「我的」页）。
## 2026-11-12 17:5x–18:3x · v2.0.0 增量 49：用户 10 项反馈（网页已上线 OSS+ECS / drop v2.3 已上线 / 小程序源码待上传）

> 用户 10 项：①上传后列表看不到；②充值后趋势不明显；③域名停用期间小程序正常使用方案；④大屏拖动效果；⑤大屏增加「接收」模块；⑥保留预设布局按钮；⑦无大屏时隐藏大屏互联；⑧小程序可在大屏开启时使用大屏互联；⑨PPT 统一「打开文件」；⑩文件云空间下载后变「打开」。

### ① 上传后列表看不到（P0 根因修复）
- drop `/state` 的 `file` 事件 payload 字段是 **`fileId`**（不是 `id`），而网页 `addFile()` 只读 `p.id` → 真实上传成功但列表永远不渲染；单测 mock 同时给了 `id` 所以漏测。
- 修复 `addFile` 兼容 `p.id || p.fileId`；测试 mock 改为**只给 `fileId`**（贴真实后端），防回归。

### ② 电费充值后趋势可读（web）
- 区间内检测到充值跳变（`Δq>0.5`）时，绘图值改为**扣除累计充值后的折算剩余**（曲线连续下降），并标出充值竖虚线；标题「已折算充值」、徽标/图例「充值 +N 度（已折算）」；y 轴按折算范围，真实剩余仍在图例/详情。
- 新增 `v2_power_trend_compare_check.py` E1–E6（32/32）；回归 power_check 155、cadence 84、slow 45、detail 30、tip 21。

### ③ 域名停用期间小程序使用方案
- 说明：课表/作业/通知/投票/名单/水量等**不依赖 tool.furina.fun**（走 CloudBase HTTPS 网关）；仅文件云空间/大屏互联/部分静态加速依赖 ECS 域名。
- 小程序默认：开发/体验版直连 ECS `https://tool.furina.fun/drop`（DevTools 勾「不校验合法域名」）；正式版用 `https://tool.furina.fun/drop`，需 DNS 恢复 + HTTPS + 微信后台 request/downloadFile 合法域名。
- 根治：恢复 DNS/备案并 `web_pause.py --off` + `ecs_site.py apply --https`；临时期可用已备案域名 CNAME 到 ECS；正式版不能走 http/IP。

### ④ 大屏拖动重做（占位块）
- 拖动改为**占位块 `.opt2-ph` + 拖动开始时固定几何命中**：源卡隐藏、占位块在网格里让位（FLIP），松手才提交 order（不再边拖边重排）；中心 ±8px 容差防整数坐标抖动；自动边缘滚动；表头 ⠿ + `title`。
- `v2_stage_v5_check` 135/135（B2/C2 通过；移动端长按拖动通过）。

### ⑤ 大屏「接收」模块
- `STG_PANELS` 新增 `recv`（📥 接收，默认整行）：展示本次大屏期间收到的文件（下载）/文字（复制）+ 互联状态 +「打开互联」；由 `STG.drop.events` 合并渲染，轮询/开关即时刷新。

### ⑥ 预设布局按钮
- 顶栏恢复「▦ 预设布局」：默认 / 演示优先 / 投票优先 / 四等分 4 套；应用前入撤销栈；模块弹层「恢复默认」复用同一逻辑。

### ⑦ 无大屏时隐藏大屏互联（drop v2.3）
- drop 新增 `GET/POST /presence`（30s TTL）。网页大屏打开后每 10s 上报、关闭时下线；全部页「大屏互联」按钮默认隐藏，presence 在线才显示（只在「全部」页可见时轮询）；`#drop` 链接也先查 presence，无大屏提示「当前没有设备开启大屏」。
- drop 单测 91/91、真实 ECS `selftest` **38/38 PASS**（v2.3）。

### ⑧ 小程序「大屏互联」工具
- 新增 `utils/screencast.js` + `pages/screencast`（4 文件）：presence 在线才可用；发文字、传文件（8MiB 分片）、遥控 11 项（聚焦 4/退出聚焦/计时 3/抽签/恢复全屏/关闭大屏）。
- `pages/all` 只在 `presence.stage=true` 时动态显示「大屏互联」入口；不在线不显示。`app.json` 注册（28 页）。
- `screencast_unit_tests.js`（16 项）挂入 `unit.js`：**478/0**；`staticcheck.py` 通过、`code_quality_check.js` 全规则通过。

### ⑨ PPT 统一「打开文件」
- 大屏 PPT 面板去掉 `ms-powerpoint` 直接放映与「开始放映」：主按钮统一「📂 打开文件」（浏览器下载/预览，手动用 PowerPoint 打开后 F5）；详情页「PowerPoint 打开」→「打开文件」；列表行「打开文件/详情」。遥控 `ppt action=open` → openfile。

### ⑩ 文件云空间下载后变「打开」
- 点击下载后记录 `zq_file_opened_v1`（本机偏好），按钮变「打开」；再点会重新取签名链接后打开；小程序 `pages/cloudspace` 同步（`zq_mp_file_opened_v1`，按钮「下载/打开」）。

### 测试/上线/回滚
- 网页：`v2_stage_v5 135/135`、`optim_v2 GREEN`、`v2_web_batch2_file_check 35/35`、`v2_power_trend_compare 32/32`、`v2_ui 27/27`、overflow 430=0、0 JS 报错。
- 上线：备份 `tools/_backup/index_online_20261112_preBatch2.html`（1,146,207B/`9f680c0c…`）→ OSS+ECS **1,158,525 B / sha256 `41dcfefc…`**（OSS check MATCH / ECS verify MATCH）；drop v2.3（health version=2.3）。
- 回滚：网页重传备份；drop 重装上一版；小程序回退源码。

## 2026-11-12 13:0x–13:1x · v2.0.0 增量 48：文件传输改「临时云空间」+ 大屏自定义体验优化 + drop v2.2（网页已上线 OSS+ECS；小程序源码待上传发布）

> 用户要求：①删除开场指令文件；②文件传输「做成类似临时云空间的工具」；③大屏自定义体验继续优化；④「把微信小程序的功能也同步更新一下」。

### ① 文件传输 = 临时云空间（网页 `#s-file` 重写）
- 去掉通道/房间码/链接/文字记录等会话概念：进入页面自动连接，同账号（同 token）的电脑/手机/大屏自动共享同一空间，无需配对。
- 页面：文件数 / 已占用 / 3 天保留统计；上传（任意大小、8MiB 分片、进度/取消）；文件列表（大小/上传时间/剩余保留时间、下载、删除）；清空空间（二次确认）；过期文件标注且不可下载；5s 静默刷新。
- 路由：`#file` → 文件传输（云空间）；`#drop` 恢复为大屏互联控制器（不再指向文件页）。
### ② drop 服务 v2.2（ECS 已上线）
- 新增 `DELETE /file/<fileId>?sessionId=…`：仅本账号会话 owner、幂等、删实体 + 追加 `filedel` 事件（其它同账号设备同步移除）；原 file 事件标记 expired 不再重签。
- 413 拒收超大请求体前有界读取（消除客户端 ConnectionAborted 竞态）；`ecs_drop.py selftest` 扩到 **32/32 PASS**（真实 ECS：删除/幂等/旧链接失效/关闭清理）。
### ③ 大屏自定义体验（`tools/index.html` §11）
- 表头加 ⠿ 拖动把手（可发现性，仍可按住卡片拖动）；顶栏新增撤销 ↶；模块弹层新增「撤销 / 锁定布局 / 恢复默认」；布局历史 `layoutHist`≤12（拖动/拖宽/增删模块/恢复默认都可撤销）；锁定后禁止拖动/拖宽（按钮/聚焦不受影响），`locked` 随 `stage_prefs` 云同步；首次进入提示「按住卡片可拖动排序 · 右上角 ⤢ 放大模块」。
### ④ 小程序同步（源码就绪，待用户上传发布；VERSION 仍 2.0.0、UD v6 不变）
- 新增 `utils/cloudspace.js` + `pages/cloudspace`（临时云空间：同账号共享、上传/下载/删除/清空、72h、5s 轮询、分享）；`utils/tools.js` 新增「文件传输」入口；`app.json` 注册；`utils/cloud-config.js` 新增 `dropBase`（开发/体验版直连 ECS、正式版 https://tool.furina.fun/drop）。
- 正式版发布前需在微信后台配置 request + downloadFile 合法域名（DNS/HTTPS 就绪后）。
- 按测试账号红线，`mp-class-tools-tests/**` 55 个文件的真实学号/姓名夹具替换为测试身份；`node unit.js` **461/0**、`staticcheck.py` 通过、`code_quality_check.js` 全规则通过。
### ⑤ 测试/上线/回滚
- 网页：`v2_web_batch2_file_check` **33/33**（云空间语义）、`v2_stage_v5_check` **126/126**（新增撤销/锁定/把手/提示断言）、`optim_v2_check` GREEN、`v2_ui 27/27`、`v2_pos_restore 12/12`、overflow 430=0、0 JS 报错。
- 上线：备份 `tools/_backup/index_online_20261112_preCloudSpace.html`（1,143,924B/`8ddf817f…`）→ OSS+ECS **1,146,207 B / sha256 `9f680c0c…`**（OSS check MATCH、ECS verify MATCH）；drop v2.2 `/drop/__health` version=2.2。
- 回滚：网页重传备份；drop 回滚=重装上一版 `drop_app.py`（`ecs_drop.py deploy`）；小程序回退源码。
- 删除 `给ZCode的开场指令.txt`（用户要求）。

## 2026-11-12 12:4x · v2.0.0 增量 47：文件传输 / 大屏互联移除「房间码」（网页已上线 OSS+ECS）

> 用户问「为什么要做房间码」。房间码来自大屏 V4 的会话模型，但实际**同账号设备自动复用同一会话**，`code` 只是 6 位展示字段，
> 不参与鉴权/加入/配对（`drop/CONTRACT.md` 原口径即「展示用，不参与鉴权」）；放进独立文件传输页后容易误导为需要输码配对 → 移除 UI。

- **网页**：文件传输页删掉大号「房间码」块与 `.file-code` 样式，状态文案改「已开启 · 同账号设备互见」；大屏互联面板/手机控制器去掉房间码标签；
  提示改为「同账号的电脑 / 手机 / 大屏打开同一链接即可互见」；`#drop` 路由/链接复制/上传/文件列表/文字/关闭会话均不变。
- **契约**：`drop/CONTRACT.md` 注明 `code` 为历史兼容字段（前端已不展示，不参与鉴权/配对）；后端 `code` 字段未改，无需重新部署 ECS。
- **测试**：`v2_web_batch2_file_check` **37/37**、`optim_v2_check` **GREEN**、`v2_ui_check` **27/27**、overflow 430=0；0 JS 报错。
- **上线/回滚**：备份 `tools/_backup/index_online_20261112_preRoomCode.html`（1,144,714B/`1c2b77b3…`）→ OSS+ECS **1,143,924 B / sha256 `8ddf817f…`**
  （OSS `check` MATCH、ECS verify MATCH）；回滚=重传备份。

## 2026-11-11 23:0x–23:5x · 政策/测试整改：测试账号唯一化（用户要求，**无网页/云端功能改动、无需部署**）

> 用户原话（2026-11-11）：「以后测试统一用测试账号，不要再用任何真实账号了」。
> 已写入 `AGENTS.md §0-7` / `HANDOFF.md §46`；审计与整改明细 `_audit/real_account_test_audit_20261111.md`。

- **政策**：测试/验收/自动化只允许 ① 官方测试身份 3260799999/测试账号；② 脚本临时创建、finally 删除的 `is_test=true` 9999 段 QA 测试身份。严禁登录真实同学/管理员账号、读取/注入真实 token、用真实身份冒名构造 `class_sessions`、测试中真实写业务数据；mock 夹具也不再使用真实学号。生产运维（部署/PPT 转换机/课表同步）凭据不属测试且不得注入自动化。守卫 `tools/tests/_test_account.py`。
- **整改**：`ppt/tests/test_cloud_contract.py` 管理员客户端→测试身份（心跳改纯 mock、token 刷新用测试身份临时 token、`agent.run_once(...,heartbeat=False)` 新参数默认不变）；`cleanup_test_decks.py` 管理员 token→测试身份（owner 软删测试 deck）；`deploy/cloudbase/verify_2026_11_11_shared_tables.py` 真实成员 QA 会话→测试身份第二会话+负向 RLS 断言；`dns_pause_web_check.py` 不再读真实管理员 token；`vote_cloud_check.py` 真实身份会话→9999 段临时 QA 测试身份（班委/团员/普通/管理员，finally 清理）；30 个测试文件真实学号→测试身份/9999 段；jwxt SSO 示例改假号；历史审计脚本加运维闸门。
- **验证（真实复跑）**：sync 144、power 155、hardening 29、v2_ui 27、water 171、water_sync 118、stage_v5 116、batch2 30/36/37/37、power_pick 48、dns_pause 19、v2_ppt 92、test_pure_logic 171、test_cloud_contract 子集 5、cleanup dry-run exit 0；真实云端 verify 46/46 + vote 80/80，finally 0 残留；云端复核 class_ids=71（9999 段 0）/class_league=50/QA 会话 0/polls/water/stage_prefs=0。
- **覆盖变化（如实）**：管理员专属心跳写/管理员 token 刷新改 mock/运维步骤；可见范围「名单内真实成员可看可投」正向用例需非 `is_test` 身份，已移除并注释说明。
- **回滚**：按文件回退测试/夹具改动即可；无 DB/部署回滚（本轮未改站点、未部署）。

## 2026-11-11 21:45–22:5x · v2.0.0 增量 45：用户 13 项反馈批次（网页已上线 OSS+ECS / 小程序源码待用户上传发布 / 安卓 3.7.0 APK 已交付 / drop 服务 v2.1 已上线 / 云端两张新表已应用）

> 用户一次提出 13 条（原文）：①文件传输直接做成单独的工具，上传的文件三天后删除，不限制上传文件大小；②名单不必做单独的班委气泡；③大屏不要单独布局按钮，按住模块卡片即可拖动并有让位效果；模块全屏应有独特 UI 适配；不要在顶部添加退出聚焦按钮，直接复用卡片右上角全屏按钮（全屏后按钮转为缩小图标）；卡片增减单独设按钮；所有自定义项目保持云同步；④大屏灵动岛参考 iOS 设计并加动效；⑤退出大屏时自动清除此次临时数据结果（如抽签结果等）；⑥水量：23 号楼两座自动四人间、去除每月免费*吨水字样、统计与同步以宿舍为单位；⑦测试 PPT 还是没有删除；⑧抽签/投票可见/点名等用到名单处应可一键快捷选择班委/团员等，但又可在此基础上添加删除；⑨优化微信小程序加载与缓存（有缓存时网络只做核对/增减）；⑩网站也尝试调用服务达到提醒功能；⑪优化小程序提醒（开关反馈、收不到通知、多余订阅可加）；⑫调整 app 端通知端口，应用未在后台运行时也能收到通知；⑬检查 CloudBase 数据是否存在问题。

- **① 文件传输独立工具 + drop 服务 v2.1**：后端 `deploy/drop_app.py` 重写（`DROP_TTL` 逐文件 72h——每个文件自上传完成起 72h 自动删除、会话空闲滑动 72h；`max_file_bytes=0`/`max_session_bytes=0` 不限制大小（磁盘唯一限制，不足 507）；8MiB 分片；`/state` 对未过期文件每次重签 30min 下载链接、过期文件 `payload.expired=true` 无链接、下载 404「文件已过期」）；`drop/CONTRACT.md` v2.1、单测 85、ECS verify/selftest 28/28、公网 health `version=2.1/ttl=259200/max=0`。网页新增独立工具「文件传输」`#s-file`（TOOLS/file + 全部页卡片 + 可拖入工具栏；房间码/同账号跨设备、分片上传任意大小、进度/取消、507 提示、文件列表下载前重拉 /state、已过期标注、发文字、关闭会话；文案「文件自上传起保留 3 天」；`#drop` hash 改开新页；大屏互联面板保留）。
- **② 名单徽章去重**：名单工具行内不再重复渲染「班委」badge 气泡（保留职务文字）；全部页卡片描述去掉「；班级身份气泡」；小程序 `showBadge` 同口径（role 已展示则不再重复 badge，管理员等保留）。
- **③④⑤ 大屏 V5（`tools/index.html` 大屏块整段重写）**：去「布局/编辑模式」按钮与 ↑↓/宽度/隐藏工具条；按住模块卡片拖动（鼠标表头按住/触屏长按 180ms；跟手幽灵 + WAAPI FLIP 让位，落位写 localStorage + 800ms 防抖推云端）；模块增删独立「＋ 模块」弹层 + 表头 ×；聚焦只由卡片右上角按钮切换且图标 ⤢→缩小，顶部/灵动岛无「退出聚焦」，4 模块聚焦态各自专属 UI（计时超大数字+大按钮+快捷时长、抽签超大结果+最近结果、投票大号结果条+倒计时、演示大标题+大按钮）；**iOS 风格灵动岛**（黑色 34px 胶囊 ⇄ 卡片 spring 形变、内容淡入滑动、多活动堆叠、reduced-motion 尊重）；退出大屏 `stgCleanupSession()` 清空临时态（计时归零、抽签结果、投票详情与**发起草稿 DOM+内存**、聚焦/岛/上传队列；布局与文件传输会话保留）；布局自定义（order/span/hidden/lastDeck/pptDl）**云同步**：新表 `public.stage_prefs`（仅本人 RLS + updated_at 触发器），LWW/单飞/404 静默降级/旧 localStorage 首次 seed。
- **⑥ 水量宿舍共享**：新表 `public.water`(PK roomverify,month)/`public.water_room`（班级 token RLS 四策略）；web/mp 进入先本机缓存再云端合并（云端同月覆盖本地、本地独有补传）、保存/删除/改人数先本机后云端、失败 pending 重试；**23A/23B 固定四人间**（选择器禁用、云端 water_room=4）；去掉「每月免费 8/12 吨水」字样（option 只留 4/6 人间），「免费额度/免费定额/免费 N 吨」措辞改「定额」（3.03/0.58/2 吨·5 度数值不变）；UD v6 `water` 契约不变（仅离线缓存）。
- **⑦ 测试 PPT 清理**：软删 2 个 `deleted=false` 测试 deck（owner=测试身份，写前断言；复核仅真实 deck `dmwalrdlgevz90l`）；根因是 `ppt/tests/test_cloud_contract.py::TestE2EFixtures` 每次跑都会重建并“保留”fixture → 已改 `tearDownClass` 自动软删+清分片（临时脚本真实验证生效）；`ppt/README` 更新；OSS 测试资产仅统计未删（9.60MiB）。
- **⑧ 名单快捷预设**：抽签/分组/点名共享 `#rosterModal` + 投票「指定成员」+ 大屏发起投票成员区加「全班/班委/团员」一键套用基础集合，之后仍可逐个增删（真实点击既有按钮，不复制状态机）；数据格式不变（seat 数组 / p_audience_seats）；小程序 roster-picker 同口径（团员走 `class_league` 缓存）。
- **⑨ 小程序加载/缓存**：有本机缓存时 onShow 同步渲染（去掉首屏骨架）、工作台 diffPatch 只 setData 变化字段、marks 5s 单飞/去重、TTL 内不重复拉。真实基准（改造前源码快照 vs 改造后，同一冷启动剧本）：首次启动请求 13→12、二次冷启动请求 2→1 且首屏计算 11.4ms→0.3ms、页面重入 setData 6 次/3111B→5 次/522B（-83%）；devtools automator 首屏可交互 217–284ms、0 console error。
- **⑩ 网页提醒**：通知页右下角「提醒」胶囊 + 设置弹层（授权状态/开关/测试提醒/可选提示音）；45s 仅 `cbSig()` 轻量签名轮询、签名变化才拉整表、隐藏→可见补检；授权且 HTTPS 时发系统 Notification，否则页内 toast + 标题【新通知】闪烁；设置本机 `zq_remind_v1`；零新增外部请求。
- **⑪ 小程序提醒**：根因=`kind='nt'` 订阅只由无调用方的 `publishNotice` 消费→永不发送；现在 notify 云函数 timer 用 PostgREST 轮询新通知签名（首跑基线、仅新 id 发送）并发送 kind='nt'；班级 token 由任一小程序客户端 bootstrap 上报（云函数校验后存 `notify_cfg/__notify_cfg`）；按钮反馈「已开启 · 收到后自动关闭」/云端 N 人已订阅/失败原因区分/可再次开启；支持第二模板 ID（`SECOND_TEMPLATE_ID` + env `NOTIFY_TMPL2`，不配=单模板）；诊断页新增提醒通道诊断（心跳/active/lastScanAt/lastError）；工作台新通知角标。部署步骤见 `mp-class-tools/README.md §九·补`（云函数上传含新 scan.js/rest-config.js + 上传触发器 + 建 notify_cfg 集合）。
- **⑫ 安卓后台通知（3.7.0 / vc13）**：根因：ReminderWorker 只读进程内缓存且不联网、Worker 冷启动 token=null、单条仅 WorkManager OneTime（Doze 延迟）、渠道懒创建/重要性不足。修复：WorkManager 周期任务加网络约束并恢复会话 token 后台拉签名→新通知本地通知+去重（首跑基线）+ deep link；单条提醒优先 `AlarmManager.setExactAndAllowWhileIdle`（Android12+ 检查 canScheduleExactAlarms，不可用回退 WorkManager）+ 开机/更新重排；启动即建 HIGH 渠道（声音/震动/锁屏）；权限四态引导 + 「后台提醒（诊断）」卡（上次轮询/渠道重要性/电池优化/精确闹钟）+ 省电自启动说明。APK 2,774,274B / sha256 `FA3DEB4C…7FF353`；副本分支 `feat/background-notify` commit 172831a，单测 1056/0（基线 994/0），主仓库因并行会话未合入（patch `artifacts/background-notify.patch` 可 `git apply`）。
- **⑬ CloudBase 数据审计**：42MB/28 张 relation 全表盘点；软删测试 deck、DROP `private.test_zz/test_zz2`、清过期 `login_jobs`、回收 `debug_headers` anon 执行权、`site_config.web.paused` 与 DNS 暂停对齐（--on）；报告 `_audit/cloudbase_data_audit_20261111.md`（含 P0 到期 2026-12-10、notices 36MB/可见 13.3MB 首拉性能、class_sessions 无保留策略、diag_analysis 旧 new 等建议）。
- **测试（真实输出）**：网页新增 `v2_stage_v5_check` 116/116、`v2_web_batch2_roster_check` 30/30、`v2_web_batch2_water_cloud_check` 36/36、`v2_web_batch2_file_check` 37/37、`v2_web_reminder_check` 37/37、真实云端 `water_cloud_api 15/15` + `water_live 13/13`；回归 `optim_v2` GREEN、`v2_ui` 27/27、`v2_drag` 69/69、overflow 360/390/430=0、`v2_pos_restore` 12/12、`v2_x5_anim` 28/28、`optim_v1` GREEN、`sync` 144/144、`vote` 83/83、`water` 171/171、`v2_water_sync` 118/118、`water_layout` 29/29、`water_month` 41/41、`power` 155/155、`export draw` 落盘、0 JS 报错/0 外部请求。小程序：`unit 437/0`、`sync_contract 33/0`、`staticcheck` exit 0、`code_quality` exit 0、`task7_unit 23/0`、notify 云函数测试 35/0 + 18/0、automator `task7_preview 34/0`（9 图）、`cache_speed_bench 3/3`。安卓：`testDebugUnitTest 1056/0`、`assembleRelease` 成功、apksigner verify PASS。云端：water/stage_prefs 迁移 22 语句 0 失败 + 幂等；真实身份验证 47/47（water 共享读写、stage_prefs 仅本人、updated_at 触发器）。
- **上线/回滚**：部署前线上备份 `tools/_backup/index_online_20261111-2210_preBatch13.html`（1,054,704B / `834d39cc…`）；网页 OSS+ECS 上线 **1,144,714 B / sha256 `1C2B77B3…`**（独立验收对象为 1,144,965B/`86B9F114…`；验收后仅做 P2 收尾——使用说明重复行去重 + notice demo 恢复，再部署为当前字节）（`oss_object check` MATCH、ECS verify MATCH）。回滚=重传备份；小程序=源码回退并重新上传（云函数/触发器同步回退）；安卓=回退 v3.6.0 APK；DB=迁移文件头 DROP TABLE/策略回滚；drop=停 unit 或改回旧 env 重新 deploy。
- **用户需执行（不代做）**：① 微信开发者工具上传发布小程序 + 上传 `notify` 云函数（含 scan.js/rest-config.js）+ 上传触发器 + 建 `notify_cfg` 集合（可选第二模板）；② 安卓安装新 APK（或并行会话合并后用 patch 重编）；③ CloudBase 2026-12-10 到期前续费/备份；④ DNS 恢复解析后 `web_pause.py --off`。
- **已知限制（如实）**：网页提醒只在页面打开时（含后台标签页）工作、不支持/非 HTTPS 仅页内提醒（关闭标签页的推送需 Web Push 基础设施，当前 DNS/HTTPS 未恢复无法做）；小程序真实订阅消息到达需用户按步骤部署云函数/触发器后真机自测；安卓无 FCM/厂商推送无法秒达（周期下限约 15 分钟，Doze/厂商限制会延迟），未做真机安装验证（构建机无 adb 设备）；文件传输「3 天」按逐文件 72h（会话空闲滑动）；水量权限为班级内共享（任一有效 token 可读写整表，契约如此）；大屏布局云同步按账号（stage_prefs 仅本人）；测试 PPT 的 OSS 资产仅统计未删除。

## 2026-11-11 20:2x–20:4x · v2.0.0 增量 44：通知附件「压缩包已下载仍待获取」修复 + 云端确认后清理下载目录原件（数据管线；无网页改动、无需部署）

> 用户反馈：`关于全国大学生创新创业实践联盟学术年会（2026）优秀论文、优秀案例、优秀事迹和优秀项目征集的通知（20261111）.rar` 已下载，但通知卡仍显示「待获取」；并要求「云端成功获取后及时删除本机的文件，避免存储占用」。
> 用户确认清理范围 **A**：只删「下载目录里的原件」（Downloads / QQ NT / 微信 msg/file 里的重复原件），**data/qq-files 等管线缓存保留**（通知板每分钟重建、云端附件都靠它，删了会退回「待获取」）；历史重复件要一次性回填清理。

- **根因（已独立复现）**：`C:\briefdesk\scripts\qq_file_names.py` 的 `SUPPORTED_EXTS` 只含 Office 类，不含 `.rar/.7z/.tar/.gz/.tgz` → `scan_dirs()` 扫不到 Downloads 里的压缩包 → `fetch_qq_files.import_downloads()` 永不导入 → `data/qq-files` 无该文件 → `build_notice_board` 的 archive 分支不触发 → 模板走 `linkrow missing` 显示「待获取」。实测旧口径 `scan_dirs` 不含目标、`find_external=None`；补 `.rar` 后命中 score=1.0。
- **修复（本机管线 7 个文件，均 `py_compile` + 单测 26/26）**：① `qq_file_names.py`：`SUPPORTED_EXTS` 追加 `.rar/.7z/.tar/.gz/.tgz`，`_EXT_RE` 补 tar/tgz/gz；② `archive_scan.py`：`CACHE_VER 1→2` + `_persist_inner()`，rar/7z 包内 ≤1.2MB 的 doc/pdf 也落盘 `data/archive-files/<sha8>/`（与 zip 同口径 → 卡片内文件可直接下载；>1.2MB 内部文件仅列清单）；③ `fetch_qq_files.py`：导入成功/目标已存在但外部有同大小重复件时登记 `data/qq-imports-pending.json`（原子写；仅 `external_dirs()` 内的外部原件；管线缓存永不登记）；④ 新增 `cleanup_qq_downloads.py`：在云端通知同步成功后只读 GET `notices?id=eq.auto_<gid>` 确认 body 里同 norm_key 的 file item 有 `url` 或 `archive.count>0` 才删原件（护栏：普通文件/在 external_dirs 内/不在 `C:\briefdesk`/target 存在同名同大小/管线有同 norm 副本/board 能定位 gid；云端查询失败一律保留；`--dry-run`/`--backfill`）；⑤ `detect_docs.py`：`rebuild_board()` 里 `sync_notices_cloud` 成功后调用 cleanup 并记录尾部计数（失败不打断重建）；⑥ `wechat_media.py` 注释同步；⑦ 新增 `tests/test_qq_import_cleanup.py`。
- **实测效果（真实数据）**：watcher 自动 `qq files imported: 2`（目标 rar 3.7MB + 成绩认定 rar 1.8MB）→ archive scan → board item `压缩包 · 已识别 8 个文件` / `archiveOk=true` / `count=8` / **7 行可下载**（内部 3.7MB PDF 仅列清单）；云端 `auto_g_qqfile_24adb7ddbc` bodyLen≈273KB、archiveCount=8、filesWithUrl=7、archived=false；cleanup 首轮删除下载原件 **25 个 / 约 16.4MiB**（含目标 rar），`data/qq-files` 的 rar **保留 3,723,180B**；pending 仅剩 2 个微信 msg/file 被微信占用文件（`PermissionError 13` → `keep` 重试，fail-safe）。
- **测试/验收**：管线单测 **26/26**（含真实 7-Zip .7z 集成）；独立 QA **34/34**（new watcher PID 52920 于 20:37:24 真实执行 hook、幂等 `deleted=0 kept=2`）+ 独立清理安全测试 **28/28** + headless Edge 前端 **13/13**（冻结 demo：已识别 + 8 行包内清单 + 7 下载按钮 + 无待获取 + 0 JS 报错；截图 `qa_qq_cleanup_20261111/shots/{before,after}_card.png`）+ before 基线 7/7；回归：board groups=83、fileWithUrl 与基线一致、qq-files/wechat-media 无删、既有 archive 记录未丢。
- **回填清理**：`cleanup_qq_downloads.py --backfill --dry-run` → `wouldDelete=0`（历史重复件已由首轮默认 cleanup 全部 drain，无额外删除）；真实 `--backfill` 为 no-op。
- **回滚**：briefdesk 管线无版本库，回滚=还原上述 6 个脚本改动（移除 cleanup 脚本与 detect_docs hook、去掉 pending 登记、还原 `SUPPORTED_EXTS`/`_EXT_RE`、`CACHE_VER` 回 1、archive `_persist_inner` 移除）；网页/云端 schema/三端均无改动，无需部署与数据回滚。
- **已知限制（如实）**：>1.5MB 原包不内嵌（既有口径）→ 3.8MB 内部 PDF 仍不可从通知卡下载；微信占用中的 msg/file 原件删不掉（保留重试）；首轮清理会批量删除历史云端已确认的下载重复件（本次 25 个）；`Briefdesk Watchdog` 双实例问题（两个 detect_docs watch 进程）仍存在、非本次引入，待后续收口。

## 2026-11-11 20:3x · v2.0.0 增量 43：小程序端同步「13/16 隐藏 24h + 电费比较自然周期同期」（源码已改，待用户上传发布）

> 用户「小程序也要」→ 与增量 42 网页同口径落到小程序。

- **隐藏 24h**：`utils/power.js` 新增 `showRange/rangesOfBuilding/normRangeForBuilding`（13/16 号楼主楼不提供 24h 档）；`pages/power/power.js` 过滤 `data.ranges`（24h 按钮不渲染）、选中慢楼栋自动落 7 天、切回实时房恢复进入前档位；24h 数据仍拉取，仅用于 `isSlowRoom`（日更/降级）与估算，不展示 24h 趋势。
- **电费比较**：`utils/power.js` 新增 `cmpSourceKey/naturalWindows/ptsBetween/cmpCoverage/naturalCompare`（自然周期同期；覆盖 <35% 不显示）；`tilesOf(..., cmp)` 在「区间用电」tile 副标追加「较昨日/上周/上月同期 ±x%」；`utils/cloud.js` 增 14d/70d 隐藏取数窗口；`pages/power/power.js` `load()` 按需补拉（实时房 7d→14d、30d→70d；慢楼栋 7d 用已预取 30d）。
- **与网页差异（如实）**：小程序 7d 比较取数按楼栋选窗口（13/16 用 30d；其他楼栋 14d），网页按 isSlowRoom 数据口径（慢楼栋提速时网页用 14d）；现网历史约 6 天 → 上周/上月同期暂不显示，数据积累后自动出现。
- **测试**：`v3_power_diag_tests.js` **64/64**、`unit.js` **414/0**、`sync_contract_test.js` **33/0**、`staticcheck.py` exit 0、`code_quality_check.js` exit 0；automator `power_natural_cmp_preview.js` **9/9 PASS**（截图 `_shots_power_natural_cmp/`，0 console error）。
- **发布状态**：小程序源码不在 web 仓库，需用户在微信开发者工具上传发布后生效；VERSION 仍 2.0.0、UD v6 不变。回滚=源码回退上一版重新上传。

## 2026-11-11 20:0x–20:2x · v2.0.0 增量 42：电费 13/16 号楼隐藏 24h 趋势 + 电费比较改「自然周期同期」（网页已上线 OSS+ECS）

> 用户需求（2026-11-11 19:48）：「对 13 号楼，16 号楼隐藏 24 小时趋势图；对于电费比较，24h 改为与前一天比较，七天改为与上一周比较，以此类推」。
> 用户确认：比较口径=自然周期同期；13/16 隐藏 24h 档位并默认 7 天。范围仅网页电费页；UD v6 契约/云端表/小程序/安卓未改；APP_VER 仍 2.0.0。

- **13/16 隐藏 24h**：楼栋级判定（`PW_SLOW_BLD`）→ `renderChips` 隐藏 24h 按钮（`hidden`+`display:none`）；选中时若当前 24h 自动落 7 天（`normRangeForSel`，只在切宿舍时归位）；切回实时房恢复进入前档位；24h 数据仍拉取，仅用于「日更」检测/估算，不再展示 24h 趋势；`setRange` 保留程序化入口（测试/深链），鼠标无入口。
- **电费比较改为自然周期同期**：tile 徽标由「较上窗口」改为——24h「较昨日同期」（今日 00:00–现在 vs 昨日同一时段）、7d「较上周同期」（本周一–现在 vs 上周同一时段）、30d「较上月同期」（本月 1 日–现在 vs 上月同期）；窗口内真实采样累计下降、不插值；两周期采样覆盖均 ≥35% 窗口才显示（现网历史约 6 天，7d/30d 比较待数据积累后自动出现）；徽标 title 写明时段。
- **取数/性能**：比较按需补拉 14 天/70 天隐藏窗口（`ensureCompare` 异步补拉后刷新）；`fetchHist` 增加 in-flight 去重（force 也复用进行中请求），切档/刷新不重复打同一窗口；缓存仍 5 分钟。
- **测试**：新增 `tools/tests/v2_power_trend_compare_check.py` **26/26**（静态 8 + 隐藏/默认/恢复 12 + 自然周期百分比逐档核对 + 历史不足降级 + 并发去重 + 360/430/1280 无溢出，截图 `_shots_power_trend/`）；回归 `power_check` **155/155**、`v2_power_cadence_check` **84/84**、`v2_power_slow_check` **45/45**、`v2_power_detail_check` 30、`v2_power_tip_fixed_check` 21、`v2_orient_power_check` 33、`v2_pos_restore_check` 12、`v2_ui_check` 27、`sync_check` 144、`v2_drag_check` 69、`water_check` **169/169**、`v2_water_sync_check` 116、`v2_water_layout_check` 29、`v2_water_month_check` 41、overflow 430=0；0 JS 报错。
- **上线（OSS+ECS）**：备份线上 `tools/_backup/index_online_20261111-2020_prePowerTrendCmp.html`（1,048,404B/`c6034271…`）→ 部署 **1,054,704 B / sha256 `834d39cc…`**，OSS `check` MATCH、ECS `verify` MATCH。回滚=重传备份。
- **取舍（如实）**：tile 主数值仍是近 N 天窗口用电，比较百分比为自然周期同期（UI 文案已区分）；现网历史约 6 天 → 上周/上月同期比较暂不显示；仅网页端，小程序端未改；13/16 隐藏 24h 为楼栋级固定策略，网关提速不恢复 24h。
- **文档**：`HANDOFF.md` 增量 42、`web/AGENTS.md §4b-34`、本文件、验收报告 `验收报告/v2.0.0_增量42_电费13-16隐藏24h与自然周期比较_网页.md`、`tools/tests/power_cadence_spec.md` 注记。

## 2026-11-11 20:0x · 大屏 V4：模块聚焦/灵动岛/布局易用化 + 投票完整发起 + 抽签名单 + 名单工具 + PPT「打开」联动 + 跨端互联通道（网页+ECS 服务已上线）

> 用户需求（2026-11-11 19:3x）原话 8 项：「把各个模块都做成点击可放大的模式，其他如果有正在进行的模块则以灵动岛的思路展示；PPT模块应设计成下载后按钮变为打开并在点击后自动调用本地PPT软件全屏放映，同时保证PPT退出或临时切出后还在大屏模式；当前各个模块的自定义化还是非常难操作；投票模块应保持可上传图片等功能；增强与其他模块的交互，在当前用户的电脑正处于大屏放映模式时，添加临时的文件传输通道，同时也可在其他端进行一些大屏上的操作；优化抽签可便捷修改或使用名单；班委名单工具修改为名单工具，内含班委名单，团员名单和全班名单」。用户确认口径：PPT 采用「调起本机 PowerPoint（Office URI）+ 提示按 F5，大屏保持/一键回全屏」（浏览器无法强制 PowerPoint 全屏）；跨端 = **同一账号在所有登录端**互传文件（分片直传 ECS，实测 6MB/s 级）+ 纯文字，并遥控大屏；投票大屏发起保留「除指定截止日期、选项说明外」的全部表单（含选项配图）。
> 范围：`tools/index.html`（大屏块 V4 重写 + 名单工具 + PPT 联动 + 互联双端 UI）、`drop/`（契约+服务+测试）、`deploy/drop_app.py`、`deploy/ecs_drop.py`、`deploy/ecs_site.py`（Caddy /drop 三处）、`deploy/cloudbase/2026-11-11_stage_rpc.sql`（class_whoami/class_league）、`tools/tests/stage_rpc_check.py`、`tools/tests/optim_v2_check.py`、`CLOUDBASE.md`、`deploy/ECS_DEPLOY.md`；APP_VER 仍 2.0.0、单文件零依赖、网页无新增外部来源（互联走同源/ECS 直连）。

- **模块点击可放大**：点面板表头或右上 ⤢ → 该面板聚焦铺满 12 列（其余隐藏），顶栏 ⤡ / 灵动岛「退出聚焦」还原；聚焦态 Esc 逐层退出。
- **灵动岛**：顶栏下方 pill 汇总「计时运行 / 投票进行中 / 互联已开启 / 切出后恢复全屏」，点击展开下拉可切聚焦任意面板/退出聚焦；手机端为流式 pill + 底部弹出。
- **布局自定义易用化**：编辑模式新增 12 列网格参考线；**整条面板表头可直接拖拽换位**（`data-dragpanel`）；点面板选中后出现底部**大按钮条**（前移/后移/宽窄切换/隐藏/完成，触摸 ≥40px）；右下角拖拽改宽；预设（主持台/双栏/聚焦）/恢复默认保留；`zq_stage_layout_v1` 本机持久化；窄屏单列堆叠、无横向溢出。
- **PPT「下载→打开」联动**：下载详情点击下载后记录 `zq_stage_ppt_dl_v1`，大屏主按钮自动变「▶ 打开放映」→ 通过 `ms-powerpoint:ofv|u|<ECS /pptfiles 绝对 URL>` 调起本机 PowerPoint，并提示「按 F5 全屏放映」；`window.PPT.hrefOf(id,kind)` 新导出（ECS 加速链）；切出 PPT/窗口失焦回来大屏仍在，灵动岛提示「点击恢复全屏」；WPS 无远程打开协议 → 下载后打开（界面有说明）。
- **投票大屏完整发起**：标题、2–20 选项、**每选项配图上传（canvas 压缩长边 640/≤150KB，单投票 ≤1.6MB）**、单选/多选+最多可选、匿名/实名、允许改票、结果可见性（始终/投后/截止后）、可见范围（全班/班委/团员/指定成员）、限时 5/10/30/60/120 分钟或不限时；切换规则/范围/限时不丢输入；创建后自动切到新投票投屏。
- **抽签便捷名单**：抽签面板「名单」→ 弹层含 全班/班委/团员/清空 快捷 + 成员勾选网格 + 已选计数，应用后与抽签页共享 `D.d.rosterSel`；面板显示「抽签池 N 人」。
- **「班委名单」→「名单」工具**：班委 / 团员 / 全班 三 tab（计数徽标）；班委来自 `class_members.role/badge`（管理仍仅班委 tab 可设职务）、团员来自新 RPC `class_league`（50 人、只返回座号+姓名、无 sid）、全班 70 人；空态/错误态兜底。
- **跨端互联（服务端）**：`drop/CONTRACT.md` v1 + ECS `class-tools-drop.service`（127.0.0.1:8093，Python 标准库，Caddy `/drop/*`）：`class_whoami` 鉴权（120s 缓存、fail closed 503）、**同账号（同 sid）自动同房**、`/open` 房间码、`/state` 增量事件、8MiB 分片上传、HMAC 签名下载 30 分钟（Range/HEAD/inline）、`/text`、`/cmd` 9 类白名单、单文件 2GiB/会话 8GiB/300 文件/TTL 2h/60s 清理；单实例锁、文件名 sanitize、CORS 全配。
- **跨端互联（前端）**：大屏打开即自动开通道，顶栏 🛰（绿点）打开面板显示房间码/链接（复制）、收到的文件（下载/图片预览）与文字（复制）；同账号其他设备从「全部页 → 大屏互联」或链接 `#drop` 打开控制器：选择文件多选（分片进度）、发文字到大屏、遥控（聚焦 4 面板/退出聚焦/计时开始暂停重置/抽签 1 人/打开当前 PPT/恢复全屏/发提示/关闭大屏），2s 轮询。
- **测试**：`optim_v2_check.py` admin 大屏断言扩到 **52 项**（聚焦/灵动岛/大按钮条/整表头拖拽/PPT 打开/投票完整表单/抽签名单/互联面板+控制器/名单三 tab 等），全套 main 16 + admin 52 + hash 3 = **GREEN 0 fails**；drop 单测 **68/68**、`ecs_drop.py selftest` **23/23**（20MiB 3 片 6.37MB/s 上传、5.49MB/s 下载、sha 一致、双 token 同 sid 互见、close 后 404）；我独立真实 ECS 黑盒（test identity：open/text/9MB 分片/下载 sha 一致 6.0MB/s/cmd/close）通过；回归 overflow 430=0、v2_ui 27/27、v2_ppt 92/92、v2_ppt_download 65/65；手机 430 单列堆叠/0 横向溢出；合成 PointerEvent 表头拖拽与拖宽通过。
- **独立验收**：`验收报告/大屏V4_独立验收_20261111.md` —— **PASS，无 P0/P1**：前端独立断言 **91/91 PASS**（8 项逐条 + 0 JS error；首轮两处 P1 已修复复验：底部大按钮条动作/整条表头拖拽）；真实 ECS drop 黑盒 **25/25 PASS**（测试身份现取 token、双 token 同 sid 互见、9MiB 2 片上传、签名下载 sha 一致 **7.16MB/s**、Range/HEAD/篡改 403/越权 403/close 后 404）；回归 optim_v2 GREEN、v2_ui 27/27、overflow 430=0；被验 sha=834d39cc（与 c6034271 的大屏 V4 块字节级一致）。P2：验收夹具首轮 toast/Esc 观测问题（已改夹具）、投票指定成员摘要仅重渲染刷新、灵动岛 `.open` 样式类未加（功能正常）、浏览器不能强制 PPT 全屏/WPS 无远程协议等设计限制。
- **上线**：网页 **1,048,404 B / sha256 `c6034271…`**（OSS `check` MATCH；ECS `/` MATCH，gzip 328KB；`/drop/__health`、`/pptfiles/__health` 200）；ECS 互联服务 active/enabled，真实 selftest 23/23；备份 `tools/_backup/index_online_20261111-2002_preStageV4.html`（975,287B/`56667b04…`）。
- **回滚**：网页重传备份；`systemctl disable --now class-tools-drop` + 撤销 ecs_site.py 的 `/drop/*` 三处后 `apply`（旧 Caddyfile 备份 `/var/www/tool_backup/20261111-195725/`），数据 `rm -rf /opt/class-tools/drop/{sessions,files,uploads}`；RPC `drop function public.class_whoami(); drop function public.class_league();`。
- **已知限制（如实）**：浏览器不能强制 PowerPoint 全屏（需 F5；WPS 走下载）；布局/「已下载」标记为本机偏好（不跨设备）；互联需同账号且会话关闭/2h 过期即删文件，签名下载 URL 30 分钟过期；ECS 单实例、单文件 2GiB/会话 8GiB；大屏仍仅管理员可见；本文件同时含并行会话 PPT v2.3 网页增量（已随本次统一部署上线）。

## 2026-11-11 19:4x · PPT v2.3（网页端）：下载详情新增「视频单独下载」分组（**本地完成，待 Lead 统一部署；真实 deck media_files 待转换机重转**）

> 契约：`web/ppt/CONTRACT.md` **§12.8**（转换机从最终 compat 包抽取音视频 → `manifest.media_files`；客户端下载详情新增分组）。本条只记**网页端**（`tools/index.html` + 专项测试）；转换机 media_files 由后端实现（`PptConvertAgent` 当前暂停，等其完成）。`APP_VER` 仍 `2.0.0`、单文件零依赖、无新增外部请求。
> 写作用域：`tools/index.html`（PPT 下载详情块内增量）+ `tools/tests/` + 本 CHANGELOG；未改其它文件、未部署、未 git。

- **数据**：读 `manifest.media_files`（数组，元素 `{s,name,size,sha256,kind:"video"|"audio",dur,w,h,slides:[7],src}`）；无该字段/空数组的旧 deck **不渲染分组**（向后兼容）。
- **UI（下载详情，位于「兼容版/PDF/原始文件」三行之后）**：分组头「视频单独下载」+ 数量胶囊；每行主标签 `视频N · 第 X 页`（音频 `音频N · 第 X 页`；同一媒体多页用「、」并列），副行 `时长 · 分辨率 · 大小`（如 `2:30 · 1024×576 · 19MB`；音频无分辨率）；下载按钮主 href 复用 `pptDlHref`（http→ECS `/pptfiles`+pathname；https→同源 `/pptfiles`；非 `/ppt/` 回退 OSS），`download` 用 manifest `name`；行内小字「备用」= 原 OSS 直链（`title="备用下载（较慢）"`），回退场景不重复。
- **CSS**：收在 PPT 块 `__PPT_DL_V1__` 段内（`.ppt-mgroup/.ppt-mg-hd/.ppt-mg-n/.ppt-mfile`），暖白/雾青、横向分隔虚线；430px 底部弹层与文件行不横向溢出（实测 `rowMaxRight ≤ vw`）。
- **探针**：`window.PPT.mediaRows()` 返回当前下载详情 media 行数（无分组/未打开=0，供测试与后续 E2E）。
- **测试（真实输出，最终文件 978,482 B / sha256 `d48d858bf92a06a5d8806894a814c2802aac342ff3b7fef5d25dd641fb8451d8`）**：
  - [`v2_ppt_download_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_download_check.py) **65/65 PASS**（12.6s；新增：media_files 2 视频 → 分组/数量 2/标签「视频1 · 第 7 页」「视频2 · 第 12 页」/时长 2:30、3:45/分辨率 1024×576、1280×720/大小 19MB、30MB/主 href ECS（pathname 百分号编码）+ `download=manifest name`/备用 OSS+title/`PPT.mediaRows()==2`；音频 fixture → 「音频1 · 第 3 页」+ 1:35 + 1.2MB 且无分辨率、ECS/备用规则一致；无 media_files 的 deck → 分组不显示、探针 0；430px 文件行不溢出；0 JS 报错/0 console.error/0 真实云端写）
  - 既有 [`v2_ppt_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_check.py) **92/92**、[`v2_ppt_video_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_video_check.py) **100/100**；回归 `overflow_check 430`=**0**、`v2_ui_check` **27/27**
  - 真实 deck `dmwalrdlgevz90l`（当前 manifest **无** media_files）：下载详情仍 3 行 + 兼容提示 + 在线预览，**不显示视频分组**、`PPT.mediaRows()==0`、0 JS error（向后兼容）；真实 2 视频的 media_files 待转换机重转后由 Lead 复测（契约预期第 7 页 150.92s、第 12 页 225.582s 两行）
- **已知限制/注意**：① 真实 deck 当前尚无 media_files（转换机暂停中，后端实现后需重转/补转，网页无需再改）；② ECS href 的 pathname 由 `URL` 规范化为百分号编码（与 OSS/ECS key 一致，浏览器可直接下载）；③ 分组按转换机上限最多 20 个文件，详情弹层内部滚动；④ 音频行也放在「视频单独下载」分组内（契约统一分组名）。
- **并行改动/回滚**：改前工作区备份 `tools/_backup/index_online_20261111-1940_preMediaDl.html`（**975,287 B / sha256 `56667b04…`**，不含本次 media 分组；本次 diff 仅 **+55 / -1 行**，全部在 PPT 下载详情块内）；并行大屏/投票/电费改动未动；未部署/未 git。最终工作区 `tools/index.html` **978,482 B / sha256 `d48d858b…`**（部署前请 Lead 以最终文件重新备份/部署）。

## 2026-11-11 19:0x · v2.0.0 增量 38：电费「关注宿舍」记忆修复 + 选择器优化（网页已上线 OSS+ECS）

> 用户需求（2026-11-11 18:33）：「把网页端的电费宿舍选择框优化一下，然后修复网页端还是无法记住我的宿舍的问题」。
> 范围：`tools/index.html` 电费页交互/同步兜底 + 专项测试；未改 UD v6 契约 / 云端表 / 小程序 / 安卓；APP_VER 仍 2.0.0、单文件零依赖、无新增外部请求。

- **根因（记不住宿舍）**：`UD.sections().power` 直接读内存 `POWER.sel`，而 `POWER` 只在打开电费页 `enter()` 时才从 UD 缓存恢复。用户打开网页停在别的 tab 时，启动同步读到空 `power.sel`，与缓存里非空选择不同 → 被判为本机改成空 → 把 `power={sel:"",at:now}` 推回云端覆盖真实选择；每次打开循环清空。用真实页面代码 + 合成 userdata 复现到空值 POST。
- **修复**：① 新增 `POWER.bootRestore()`：启动即从 UD 缓存 / 本机兜底恢复选择（`UD.sections()` 读 power 前兜底、幂等；`POWER.enter` / `WATER.restoreSel` 复用）；② `UD.localView` power 防丢：隐式空（未初始化/非法旧值/无基线）不得覆盖非空基线/云端，只有 `POWER._clearedAt`（用户显式清空）允许推空；③ `UD.pull` 自愈：云端为空、本机非空且非显式清空 → 保留本机选择并补推一次；④ 显式清空标记贯通网页与水量页。
- **选择器优化**：原生 `<select>`（17 项长列表）→ 自定义选择器：触发按钮 + 浮层面板（楼栋分段 13/16/23A/23B + 房间网格：23B 4 列 / 13、16 2 列 / 23A 3 列；选中 ✓）；点击开合、Esc/点面板外关闭、打开后焦点落选中房间、空间不足自动向上翻转、aria-expanded/aria-label、点按 ≥40px；`.pw-pickwrap` 加入两处滑动手势豁免。隐藏原生 `#pwSelect`（1px/opacity 0）保留为值源与自动化兼容；水量页 `#wtSel` 不变。使用说明补「点『关注宿舍』按楼栋选房间；选择随账号同步，换设备自动恢复。」
- **测试（本机实跑）**：新增 `tools/tests/v2_power_pick_mem_check.py` **48/48 PASS**（静态 12 + 选择器/布局交互 27 + 记忆链路 9；mock fetch 无真实云端写；截图 `_shots_power_pick/`；对修复前冻结副本实跑 FAIL，证明能抓回归）。回归：`power_check` **155/155**、`sync_check` **144/144**、`v2_power_detail_check` 30、`v2_power_tip_fixed_check` 21、`v2_power_cadence_check` 84、`v2_power_slow_check` 45、`v2_orient_power_check` 33、`v2_power_sync_hardening_check` 29、`water_check` 169、`v2_water_sync_check` 116、`v2_water_layout_check` 29、`v2_water_month_check`、`v2_pos_restore_check` 12、`v2_ui_check` 27、`v2_drag_check` 69、overflow 430 = 0；0 JS 报错 / 无外部请求。测试适配：`power_check` 下拉框高度改为「自定义触发器 ≥40px + 原生 select opacity 0」；`sync_check` static 改为 sections power IIFE/`bootRestore`；`v2_water_sync_check` G09/G16 改为显式强拉一次再断言 sid 过滤（原断言依赖旧 bug 产生的 GET）。
- **上线（OSS+ECS，DNS 暂停期以对象字节为准）**：备份线上 `tools/_backup/index_online_20261111-1915_prePowerPick.html`（963,583 B / `c2f8ce71…`）→ `python deploy/sync_tools.py index.html` + `python deploy/ecs_site.py apply`；线上 **975,287 B / sha256 `56667b04…`**，OSS `check` = MATCH、ECS `verify` = MATCH。部署后 ECS 真实环境冒烟（真实身份 + CDP 拦截全部云端写，blocked=2，未污染云端）：电费页恢复云端 `4-23B---423`、面板 4 楼栋/4 房间/1 选中、390 无溢出、0 JS 报错（截图 `_shots_power_pick/live_ecs_390.png`）。回滚 = 重传备份（会连同同批大屏/投票等一起回退到 963,583 版本）。
- **副作用/已知取舍（如实）**：① 未改电费数据/统计口径；② 非空优先：一端显式取消关注后，其他仍持有非空选择的端可能把它补推恢复（首要保证永不丢失；严格联动取消需新增显式标记字段并改 UD 契约）；③ 17 间静态目录不变（增删宿舍仍要 `PW_ROOMS` 与同步脚本两处同改）；④ 隐藏原生 select 仅供值源/自动化，键盘与读屏走自定义按钮（aria 标注）。
- **文档**：`HANDOFF.md §38`、`web/AGENTS.md §4b-30`、本文件、验收报告 `验收报告/v2.0.0_增量38_电费宿舍记忆修复与选择器优化_网页.md`。


## 2026-11-11 18:1x–18:4x · 大屏 V3：面板化 + 高度自定义布局 + 投票投屏/快速发起 + PPT 播放/下载联动（网页已随合并部署上线）

> 用户需求（2026-11-11 18:10）：「添加投票功能至大屏，同时对于目前重新改动的ppt功能重新设计大屏ppt板块，优化大屏功能和布局高度自定义」。用户拍板：大屏投票＝**投屏 + 大屏快速发起**；布局自定义＝**按钮式 + 拖拽排序/拖拽改宽**；PPT 板块＝**做下载按钮 + 本机 Office 联动**。
> 范围：仅 `tools/index.html` 大屏块（CSS/JS 重写约 1400 行）+ PPT 下载详情小增（PowerPoint 打开）+ `tools/tests/optim_v2_check.py`；未改 UD v6 / 云端表 / 小程序 / 安卓；APP_VER 仍 2.0.0、单文件零依赖、无新增外部来源。

- **大屏改为 12 列自适应面板网格（非固定四格）**：演示 / 投票 / 计时 / 抽签四面板，时钟固定顶栏；每行自动补满 12 列；≤900px 单列纵向堆叠（自然高度、整体滚动）；短面板自动紧凑（PPT 主位隐藏 eyebrow/标签、标题 1 行，避免裁切）。
- **布局高度自定义**：`#o2sLay`（或 L 键）进编辑模式 → 布局条（预设 **主持台** 8/4+6/6、**双栏** 6/6+6/6、**聚焦** 12+4/4/4、恢复默认、完成、隐藏面板恢复 chips）；每面板工具 ↑↓ 排序 / ⤢ 大小循环（4/6/8/12）/ × 隐藏；⋮⋮ 手柄拖拽换位、右下角拖拽改宽；持久化 `localStorage zq_stage_layout_v1`（本机偏好，不进 UD 同步）；隐藏后自动补满行；编辑态不触发面板内容操作。
- **投票面板（新增）**：`cbRpc("poll_list"/"poll_detail"/"poll_create")`；进行中投票 chips 切换；大号标题 + 已投人数 + 倒计时（1s 走）+ 单选/匿名/结果可见性标签 + 选项票数/百分比条；**不渲染投票人姓名**（即使 detail 返回 voters）；结果隐藏时只显示「投后可见/截止后可见」不显示票数；空态「还没有进行中的投票 + 发起投票」。
- **大屏快速发起**：弹层内标题 + 2–8 选项 + 限时 5/10/30/60 分钟 + 匿名开关 → `poll_create`（mode=quick、单选、允许改票、结果始终可见）→ 创建后自动投屏；失败显示原因不阻塞大屏。
- **PPT 板块适配 v2.0 下载中心**：`window.PPT` 新增 `openDetail(id)/filesOf(id)` 导出；主位 deck 显示 页数/大小/上传者 + 兼容版/PDF/可放映标签；兼容版主按钮「⤓ 下载资料」（打开 `#pptDl` 下载详情）、旧 deck 主按钮「▶ 开始放映」；主/次按钮可互切；列表行含下载/放映小按钮；头部「演示库/刷新」；空库「去上传」跳 #s-ppt。
- **PPT 下载详情 · 本机 Office 联动**：兼容版行新增「PowerPoint 打开」= `ms-powerpoint:ofv|u|<绝对URL>`（仅兼容版且 http(s)，走 ECS 缓存 URL；Windows 已装 Office 时直接调起 PowerPoint 打开远程文件）+ 一行说明「兼容版可 PowerPoint 打开（需本机 Office）；WPS 请下载后用本机 WPS 打开」（WPS 无公开远程打开协议，故走下载）。
- **其它优化**：计时面板 5/10/15/30 分钟快捷（点选即设置并停止旧计时）；Esc 分层（先关弹层 → 退出编辑 → 关大屏；`#pptPlayer`/`#pptDl` 打开时不抢 Esc）；F 全屏、L 布局；窗口 resize 重新补满行并自适应紧凑；移动端触控目标 ≥40px；移除旧 hero+rail 结构及选择器。
- **测试（本机真实输出）**：`optim_v2_check.py` admin 大屏断言更新为 **29 项**（面板/编辑模式/预设/大小/隐藏恢复/PPT 放映+下载详情+PowerPoint 打开/投票投屏+快速发起/计时快捷/0 JS 报错），全套 main 16 + admin 29 + hash 3 = **GREEN 0 fails**；回归 `v2_ppt_check` 92/92、`v2_ppt_download_check` 51/51、`v2_ui_check` 27/27、`overflow_check 430` = 0；本机 CDP 截图 1366/1920/430/编辑态/投票/PPT 下载详情均 0 横向溢出、0 报错。
- **独立验收（第三轮，fresh-context teammate）**：**94/94 PASS、0 FAIL、0 JS error**（12 列网格/布局编辑/合成 PointerEvent 拖拽换位与改宽/重载恢复/投票投屏+快速发起/PPT 下载详情+Office URI/Esc 分层/空态错误态/三档布局/非管理员），报告 `验收报告/团日大屏_改造验收_20261110.md`（第三轮；前两轮标注作废保留历史），证据 `tools/tests/_stageqa/`。
- **上线**：随并行会话合并部署，线上 `index.html` **963,583 B / sha256 `c2f8ce71…`**（OSS `check` MATCH / ECS `verify` MATCH，含同批投票可见人范围与拖拽 v2.1）；APP_VER 2.0.0 未改。
- **回滚**：重传 `tools/_backup/index_online_20261111-1829_preVoteAudience.html`（962,121 B / `0254a4b8…`，不含投票 audience 与大屏 V3）；仅回退大屏不建议（会连带回退 PPT v2/投票等）。
- **副作用/已知限制**：大屏打开时额外读取投票列表/详情（5s 详情、20s 列表刷新）与一次 PPT 列表+轻量文件元数据（均为现有 PostgREST 只读，无新增外部来源）；布局偏好只本机；WPS 无法从浏览器直接调起打开远程文件（需下载后打开）；大屏仍仅管理员可见。

## 2026-11-11 18:0x–18:3x · 增量 36：网页卡片拖动定位基准 v2.1（卡片本体）+ 全部卡片可拖入顶部工具栏 + 删除云端测试 PPT（网页已上线 OSS+ECS）

> 用户需求（2026-11-11 18:08）：「1、删除测试ppt，2、将网页版卡片拖动的定位基准设成卡片本体而不是鼠标位置，3、修复部分卡片无法拖动至上方工具栏的问题」。
> 范围：`tools/index.html`（全部页卡片拖动块 + tabs 元数据）、`tools/tests/v2_drag_check.py`（56→69 项）、`ppt/tests/cleanup_test_decks.py` + `ppt/README.md`；云端仅 `ppt_decks` 软删 2 行测试数据。APP_VER 仍 2.0.0、单文件零依赖、无新增外部请求。

- **拖动定位基准（#2）**：幽灵视觉本来就是卡片本体锚定（`ghost = 指针 - 抓取偏移`，`v2_drag_check` H4 锁定）；本次把**落点/命中/插入位置**从鼠标坐标改为**卡片本体矩形**：`beginGhost` 缓存卡片宽高（`DRAG.cardW/cardH`）→ `dragCardBox()` 用幽灵实时位置推导本体矩形（不逐帧读布局）；`updateDropTarget` 工具栏命中 = 本体矩形与 sticky `.tabs` 重叠（上沿压进栏 ≥2px 进入、离开迟滞 18px）；`calcTabsDrop(cx)` 用本体中心 x 选插入位；`calcCardsDrop(cx,cy)` 按本体中心**阅读顺序（先行后列）**算插入位置，与目标中心几乎重合时按拖动方向决定前/后，保留「候选连续 2 帧一致才落位」迟滞；松手收尾/自动滚动/FLIP 不回归。
- **全部卡片可拖入工具栏（#3）**：新增 `SPECIAL_TAB={power:"电费",fb:"反馈",ug:"说明"}` + `tabInfoOf/isTabKey`（TOOLS 用原名、特殊页用短标签），贯通 `renderTabs` 显示/安全过滤、`dropToTabs` 校验、命中放行；`gotoTab` 既有支持不改；homeTools 仍 ≤4、仍走 UD v6 同步。14 张卡片逐张验证均可入栏。
- **测试（真实输出）**：`tools/tests/v2_drag_check.py` **56→69 项全 PASS**——新增 R 本体命中（抓取偏移大、指针在旧命中区外、本体上沿压进栏仍进入投放态；本体矩形=幽灵位置 ≤2px）；S 桌面多列本体中心压到目标卡中心 → 落位到该 index；T 电费/反馈/使用说明入栏 + 短标签 + 点击切页 + 刷新保持；U 工具栏插入位=本体中心（对照指针口径证明不是指针）。测试基座改**动态端口 + 预览副本 PID 唯一名**，避免并行会话撞 8965/9465/`_power_preview.html`（本轮曾致浏览器连接重置假失败）。
- **回归（本机实跑）**：overflow 360/390/430 = **overflowCount 0**；`v2_ui_check` 27/27；`v2_pos_restore_check` 12/12；`v2_x5_anim_check` 28/28；`optim_v1_check` GREEN；`v2_orient_power_check` 33/33；`sync_check` 144/144；`export_check draw` 正常落盘。
- **删除测试 PPT（#1）**：云端 `public.ppt_decks` 原有 3 行 `deleted=false`，其中 2 个测试 deck（`dtestvidnu3wy4gfvefa`「测试·嵌入视频演示」、`dtest437clgn2cbiopo`「测试·4:3 演示」）已按用户要求软删（PATCH `id=in.(…)&deleted=eq.false` HTTP 200、affected 2；写前断言 owner_sid=测试身份 3260799999）；清理后仅剩真实 deck `dmwalrdlgevz90l`（16 页 38MB）。新增 `ppt/tests/cleanup_test_decks.py`（默认 dry-run；`--apply` 幂等、写前断言 owner；`--report-oss` 只读统计）+ `ppt/README.md` §9 交付前清理说明；测试身份全部 deck 的 OSS 资产 78 obj / 7.20MiB **只统计未删**（用户未要求清存储）。
- **上线（已随并行合并部署）**：本改动随并行会话 18:36 合并部署上线 —— OSS/ECS **963,583 B / sha256 `c2f8ce718a2baf6e0e1a4eb1c655c1c5e3222e37967f2eccca1182ced2ba82cb`**（`deploy/oss_object.py check index.html` = **MATCH**；冻结副本 `tools/tests/frozen/index_drag_body_c2f8ce71.html`）。部署前线上备份 `tools/_backup/index_online_20261111-1829_preVoteAudience.html`（962,121 B/`0254a4b8…`）。线上字节级复核：`dragCardBox / SPECIAL_TAB / DRAG_TABS_OVER / calcCardsDrop(cx,cy)` 标记均在。
- **回滚**：重传上述备份（会连同并行投票可见范围/大屏 CSS 一起回退）；仅回退拖动手感需局部还原 `updateDropTarget/calcTabsDrop/calcCardsDrop` 与 `isToolKey` 拦截，并把测试回退到 56 项版本。
- **已知取舍/副作用（如实）**：① 鼠标不再参与命中/插入位置——拖动时落点以卡片本体为准（工具栏插入位置随本体中心，比旧「指针位置」左移约半个卡片宽，测试按新口径锁定）；② 只从卡片右上 handle 起手（未改起手方式）；③ 跨端：小程序 `utils/tools.js normalizeHome` 会过滤 power/fb/ug（noHome/未知 key），网页工具栏中的特殊 key 在小程序首页不显示、且小程序编辑首页后可能回写覆盖。

## 2026-11-11 18:0x–18:3x · 投票功能：可见人范围（网页已上线 OSS+ECS；小程序源码待用户上传发布）

> 用户需求（2026-11-11 18:08）：「投票功能新增可见人范围选项」。已确认：**全班 / 班委 / 团员 / 指定成员（座号多选，不存/不显示学号）**；**范围内的人才能看到并投票**（范围外列表完全不可见，detail/submit「投票不存在」）；发起人始终可见可管理可投；管理员始终可见可管理、不在范围时不能投。
> 契约：`web/vote/CONTRACT.md` §1.6；增量迁移：`deploy/cloudbase/2026-11-11_polls_audience.sql`（已应用，幂等）。

- **云端**：`polls` 增 `audience`（all/committee/league/custom）+ `audience_seats`（座号 jsonb，去重升序，排除测试身份）；新增 `poll_audience_visible()`/`poll_norm_audience()`；DROP 旧 7 参 `poll_create`/`poll_manage` 重建 9 参（新参数默认 all/NULL → 旧版页面创建=全班、编辑不改范围，**向后兼容**）；`poll_list`/`poll_detail`/`poll_submit` 服务端按范围过滤；`audience_seats` 仅 `can_manage` 返回；任何 RPC 不返回学号。
- **网页**：发起/编辑弹层「可见范围」4 段 + 指定成员（姓名搜索 + 成员 chips，只显示姓名/内部座号，至少 1 人）；卡片/详情范围标签（班委可见/团员可见/指定 N 人，all 不显示）；编辑回填；纯增量 APP_VER 2.0.0。
- **小程序（源码）**：`utils/vote.js` 范围纯逻辑、`utils/cloud.js` 透传、`pages/vote` 范围 4 段 + roster 成员多选（页面 data 剥离 sid）、`pages/votedetail` 标签；版本仍 2.0.0，**待用户上传发布**。
- **测试**：`vote_check.py` **83/83**、`vote_cloud_check.py` **82/82**（真实云端班委/团员/普通/管理员身份，finally 清理）、`vote_live_check.py` **34/34**（真实身份：班委投票普通成员不可见、指定成员真实名单可见性）；小程序 `unit 402/0`、staticcheck/code_quality 通过；回归 overflow=0、v2_ui 27/27、v2_drag 69/69。
- **上线**：部署前备份 `tools/_backup/index_online_20261111-1829_preVoteAudience.html`（962,121 B/`0254a4b8…`）；OSS+ECS 对象 **963,583 B / sha256 `c2f8ce718a2baf6e0e1a4eb1c655c1c5e3222e37967f2eccca1182ced2ba82cb`**（OSS/ECS 校验 MATCH；同文件含并行会话大屏 CSS 改动）。回滚：网页重传备份；DB 先按增量迁移头部回滚、再按基础迁移头部回滚整功能；小程序回退源码。

## 2026-11-11 13:0x · 投票功能（网页已上线 OSS+ECS；小程序源码待用户上传发布）

> 用户需求（2026-11-11）：「新增投票功能，该功能需同时可用于临时的限时投票和可设立截止日期的长时投票，投票选项和投票标题需可高度自定义化」。
> 已确认取舍：先做**网页 + 小程序**（安卓后续）；**完整版自定义**；**全班成员可发起**，发起人+管理员可管理。
> 契约唯一真源：`web/vote/CONTRACT.md`；云端迁移：`deploy/cloudbase/2026-11-11_polls.sql`（已应用）；APP_VER 仍 2.0.0、单文件零依赖、无新增外部请求。

- **云端**：`public.polls` + `public.poll_votes`；两表 **RLS 开启、无策略、REVOKE ALL**（anon 完全无直连权限，直连 401），全部读写只经 5 个 `SECURITY DEFINER` RPC：`poll_create`（幂等；标题 1–80/说明 ≤500/选项 2–20/选项文字 1–80/说明 ≤200/配图 `data:image` 单张 ≤150000 字符且合计 ≤1.6MB/规则归一/截止必须晚于服务端当前时间）、`poll_list`、`poll_detail`、`poll_submit`（服务端 `clock_timestamp()` 判截止、单选/多选上限、`UNIQUE(poll_id,sid)` 一人一票、allowChange）、`poll_manage`（编辑仅限无票/提前结束/延长重开/软删；owner 或管理员）。**任何 RPC 响应不返回学号**；匿名投票不返回投票人（服务端仍按 sid 去重）。
- **网页**：`__VOTE_V1__` 块（CSS/HTML/JS 纯增量）——列表（进行中/已结束、15s 刷新、倒计时、规则标签、已投人数/我已投）、详情弹层（单选/多选提交·改票、结果百分比条 `.vd-pct`、实名投票人、结果隐藏提示、管理按钮）、发起/编辑弹层（限时快捷 5/10/30/60/120 分钟【默认 30】、指定截止 `datetime-local`、不限时；2–20 选项含说明与配图【canvas 压缩成长边 ≤640 JPEG data URL】；单选/多选+最多可选；匿名/实名；允许改票；结果始终/投票后/截止后可见）；桌面 ≥960px 列表双栏；小控件点按 ≥40px。
- **小程序（源码）**：`pages/vote` + `pages/votedetail` + `utils/vote.js` + `utils/cloud.js` 5 个 poll RPC 封装 + `utils/tools.js` 入口 + `images/tool-vote.png` + `app.json` 注册；`node unit.js` **397/0**（vote 34）、`staticcheck.py` exit 0、`code_quality_check.js` exit 0；**待用户上传发布**。
- **测试**：`tools/tests/vote_check.py` **66/66**（mock UI）、`vote_cloud_check.py` **54/54**（真实云端 API，测试数据 finally 硬删）、`vote_live_check.py` **20/20**（本地临时通道+测试身份真实 E2E，写白名单只放行 poll_*）；独立 QA `vote_qa_cloud/ui/live.py` **116/78/19 全 PASS**，报告 `web/验收报告/投票功能_独立验收_20261111.md`；回归 overflow=0、v2_ui 27/27、v2_drag 56/56。
- **上线（2026-11-11 13:0x）**：部署前线上备份 `tools/_backup/index_online_20261111-1257_preVote.html`（870,349 B/`ea799a28…`）；首版部署 920,140 B/`489c87ea…`，按独立验收修复 P1（默认限时 30 分钟）与 P2（`.vd-pct`、点按 ≥40px）后最终 **920,368 B / sha256 `db91fe6c0d850376fa8ceccb54069b6c5fe7c56d653813d8eb6ecbb27849973d`**；OSS `oss_object check` = MATCH，ECS `ecs_site.py apply/verify` = MATCH（QA 独立公网拉取两处字节一致）。
- **回滚**：网页重传上述备份；DB 回滚用迁移文件头部 `DROP FUNCTION` ×5 + `DROP TABLE poll_votes/polls`；小程序回退源码。已知限制：投票页不导出图片；配图 data URL 单投票 ≤1.6MB；匿名只对外不返回投票人；投票数据不进 userdata v6。

## 2026-11-11 12:4x · PPT 下载加速（网页端）：下载详情优先走 ECS 缓存 `/pptfiles` + 备用 OSS 直链（**本地完成，待 Lead 部署网页；ECS 已上线**）

> 背景（Lead 任务）：实测本机→OSS 香港单连接 74KB/s、用户→ECS 杭州 4.7MB/s；ECS 提供 `/pptfiles/ppt/a/...` 缓存下载（服务由另一 agent 部署，地址 `https://tool.furina.fun/pptfiles/`，https 备案后同源 `/pptfiles/`）。本次把网页下载详情的三行下载链接改为优先走 ECS 缓存，OSS 保留为「备用」。
> 写作用域：`tools/index.html`（PPT 块内增量）+ `tools/tests/` + 本 CHANGELOG；未改其它文件、未部署、未 git。

- **链接选择 `pptDlHref(man,f)`**：先用 `resolveUrl(manifest.base, files.s)` 得 OSS 绝对 URL 并解析 pathname；`/ppt/...` 路径时——http 页面 → `https://tool.furina.fun/pptfiles` + pathname；https 页面 → `location.origin + "/pptfiles"` + pathname（为 tool.furina.fun 备案后同源反代预留）；非 `/ppt/` 路径、`data:`/`blob:`、解析失败 → 回退原 OSS 直链。
- **fileRow**：主「下载」按钮改用 ECS href（`<a href=… download=name>`，下载文件名/人类可读大小不变）；按钮下方新增**小字「备用」**链接指向原 OSS 直链（`title="备用下载（较慢）"`、同一 download 名），ECS 未就绪/失败时可自选；回退场景（主链接即 OSS）不重复显示「备用」；「未生成 · —」行不变。按钮组竖排 `.ppt-file-a`，暖白卡片/雾青主按钮风格不变。
- **顺带修正**：存量 deck 补转 compat 后（既有 `files` 又保留旧 `slides/video`），详情现在按契约 §12.4.1 显示**次要「在线预览」**按钮（此前仅无 files 的旧 deck 才有），下载为主、预览为次。
- **测试（真实输出，最终稳定合并文件 920,140 B / sha256 `489c87eaf55ab19dc26b443152929baa6de1c7c8fe25425b4c32cf82304c5298`；mtime 12:51:39，并行投票/大屏改动均在内）**：
  - [`v2_ppt_download_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_download_check.py) **51/51 PASS**（新增/更新：http 页面三行主 href 均以 `https://tool.furina.fun/pptfiles/ppt/a/` 开头、download 文件名/大小不变、备用=原 OSS 且 title 正确、非 /ppt/ 路径回退 OSS 且不显示备用、存量补转 deck 三行 ECS +「在线预览」可进旧播放器、430px 文件行不溢出、0 JS 报错/0 console.error/0 真实云端写）
  - 既有 [`v2_ppt_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_check.py) **92/92**、[`v2_ppt_video_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_video_check.py) **100/100** 全过（详情/下载/播放器交互不回归）
  - 回归（真实输出）：`overflow_check 430`=**0**、`v2_ui_check` **27/27**、`v2_pos_restore_check` **12/12**、`v2_x5_anim_check` **28/28**、`v2_drag_check` **56/56**
  - 真实 deck `dmwalrdlgevz90l`（本地 http 页面）：详情三行主 href 实测为 `https://tool.furina.fun/pptfiles/ppt/a/dmwalrdlgevz90l/c0e5834805/{compat.pptx,preview.pdf,original.pptx}`，备用均为 `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/...`（title=备用下载（较慢）），下载名=原中文名；详情同时保留「在线预览」；0 JS error。
  - **ECS `/pptfiles` 已上线（Lead 反馈缓存命中 7.2MB/s、用户 deck 4 文件已预热）**；本机只读复核：HEAD `compat.pptx` 200/39,063,744B、`preview.pdf` 200/1,105,861B、`original.pptx` 200/38,016,533B、`ppt/src/.../source.pptx` 200/38,016,533B；`Range: bytes=0-4095` 四者均 206 且返回 `bytes 0-4095/总长`（即 `/ppt/a/` 与 `/ppt/src/` 都在 ECS 缓存覆盖范围，无需收窄 `pptDlHref` 前缀）；真实速度/sha256 由 Lead 部署网页后 E2E。
- **已知限制**：① https 页面走同源 `/pptfiles`，需 Caddy 反代就绪（备案后）；② ECS 已实测覆盖 `/ppt/a/` 与 `/ppt/src/`，旧 deck 原始文件同样走缓存；若未来 ECS 范围收窄，需把 `pptDlHref` 生效前缀同步收窄（一行）；③ 浏览器大文件下载无进度（原生下载，仅显示大小）；④ 移动端/微信内仍可能被改写为预览或拦截 `<a download>`。
- **并行改动提醒**：本次期间并行 agent 合入了「投票」功能（+~700 行 CSS/JS/HTML 与 TOOLS 入口），最终稳定工作区 `tools/index.html` **920,140 B / sha256 `489c87eaf55ab19dc26b443152929baa6de1c7c8fe25425b4c32cf82304c5298`**（我的下载加速 + 投票 + 此前大屏/v2.0 均在内），全部 PPT 测试在该合并文件上实跑通过；部署前请 Lead 以最终文件重新备份。
- **回滚**：本次未部署；改前线上对象备份 `tools/_backup/index_online_20261111-1241_preDlAccel.html`（**870,349 B / sha256 `ea799a28…`**，不含本次加速与并行投票改动）；回滚该文件会一并回退并行改动，建议以 Lead 部署前备份为准；本次改动只在 PPT 下载详情函数/CSS 行内，回退到旧 `fileRow` 即恢复 OSS 直链。

## 2026-11-10 22:4x · PPT v2.0（网页端）：功能重定义为「兼容性处理 + 多端下载中心」（**已上线：2026-11-10 22:53 由 Lead 统一部署**）

> 用户原话（2026-11-10 22:05）：「重新定义该功能，不再已在线播放为主要功能，而是以上传ppt，自动对内容进行兼容性处理，并提供多端下载的方式，不改变ppt本身质量」。
> 契约唯一真源：`web/ppt/CONTRACT.md` **§12**（§12.2 manifest v2 `files.compat/pdf/source` + `compat.warnings` + `slides:[]`；§12.4.1 列表/详情 UI；§12.6 红线）。本条只记**网页端**（`tools/index.html` + 专项测试）；转换机 compat 兼容包/PDF 与小程序/安卓下载中心由其它实现者交付。`APP_VER` 仍 `2.0.0`；单文件零依赖、无新增外部请求（仅复用 PostgREST 读接口）。

- **列表：点击卡片 = 打开「下载」详情（不再默认进播放器）**。卡片保留封面/标题/`页数 · 大小 · 步数 · 上传者`/状态胶囊；有 `files.compat` 的 deck 显示小标签「兼容版」「PDF」（不写长句），大小优先取 `manifest.files.compat.size`（旧 deck 用 `source_size`）；整卡点击打开详情，失败卡保留「重试」、本人卡保留「删除」；上传/轮询/离线提示/软删除/重试逻辑全不变。
- **下载详情（懒拉单 deck manifest：`GET ppt_decks?select=manifest&id=eq.<id>`）**：
  - 三行下载：**兼容版 PPTX / PDF / 原始文件**，每行 `<a href=base+files.s download=files.name>` 直连 OSS（含 `size` 人类可读大小；PDF 额外显示 `pages 页`；缺项显示「未生成 · —」）；
  - `manifest.compat.warnings` → 橙色「兼容提示」区逐条显示（外链媒体、字体未嵌入等，仅告警不删内容）；
  - `slides: []` 的 manifest v2 正常渲染（无在线预览按钮，不报错）；`cover_url` 仍按原逻辑显示；
  - 状态非 ready：只显示状态/进度（上传 N%/排队转换/转换中 p%），不显示下载；`failed` 显示 error 原文 + 「重试」（PATCH `status=queued`）；
  - 旧 deck（无 files）：显示「兼容版未生成」+ **原始文件下载**（旧 `manifest.src`）+「在线预览」（仅当有旧 `slides`）+「重新处理」（复用 `retryDeck`）；
  - 弹层底部安全区适配、Esc / × / 点遮罩关闭、打开时锁页面滚动、弹层内滑动不切工具（`resolveStart` 排除 `#pptDl`）。
- **旧播放器保留为「在线预览」入口**：点击详情「在线预览」进入原 v1.2 播放器（分步/原样播放、续播、热点等全部逻辑原样保留）；`PPT.open(id)` 仍直接开播放器（大屏演示等既有调用不变）；若对**新兼容版 deck**（无 slides）调用 `PPT.open`，自动转为打开下载详情（不报错、不进空播放器）。列表不再有列表级「播放」按钮/封面 ▶。
- **列表标签数据**：§4.4 仍禁止列表主查询带 manifest；为显示「兼容版/PDF」与大小，新增**一次轻量子查询** `GET ppt_decks?select=id,files:manifest->files&deleted=eq.false&limit=100`（PostgREST JSON 子字段选择，只含文件元数据、不含 slides；**生产网关已实测 200**）。失败（旧网关/不支持）静默忽略不报错；详情/预览时也会把 files 缓存到本机 `zq_ppt_files_<deckId>` 兜底。
- **代码位置（保持单文件）**：CSS 追加在 `</style>` 前、以 `/* __PPT_DL_V1__ */` 分隔（下载弹层/文件行/兼容提示/列表标签）；JS 全部在 `var PPT=(function(){…})()` 块内新增下载详情段（`filesMeta/filesOf/cacheFiles/openDetail/renderDetail/openPreview/...`）；`__PPT_FEATURE_V1__` 标记仍 CSS+JS 各一；无新增外部请求/字体/CDN。
- **测试（真实输出，最终文件 870,349 B / sha256 `ea799a2892809b4e08b6dffe59f7aaddff99066f11b50147381534ee28771dc3`）**：
  - 新增 [`v2_ppt_download_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_download_check.py) **41 项全过 / 0 FAIL**（6.9–11.0s，多次实跑；含：新 v2 deck 列表标签+大小→点卡片进详情（不进播放器）→三行下载 href=base+s/download=name/size/PDF 页数→兼容提示橙色逐条→无预览→Esc/×关闭→430px 无溢出；旧 deck「兼容版未生成+原始文件+在线预览+重新处理」→在线预览进旧播放器；无 slides 旧 deck 无预览；queued 详情只状态无下载；failed 详情 error+重试→真实 PATCH status=queued；外部 `PPT.open`（大屏调用）对兼容版 deck 转打开下载详情；0 JS 报错/0 console.error/0 真实云端写）
  - 改造 [`v2_ppt_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_check.py) **92/92 PASS**（原 86 项语义保留，播放器用例改经「卡片→详情→在线预览」入口；+4 静态 v2.0 断言 +2 详情入口断言；mock 支持 `manifest->files` 轻量子查询）
  - 改造 [`v2_ppt_video_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_video_check.py) **100/100 PASS**（原 99 项保留；打开路径改为详情→在线预览；新增详情三态断言）
  - 回归（真实输出）：`overflow_check 430`=**0**；`v2_ui_check` **27/27**；`v2_pos_restore_check` **12/12**；`v2_x5_anim_check` **28/28**；`v2_drag_check` **56/56**
  - 真实 deck `dmwalrdlgevz90l`（旧 v1 manifest，无 files，16 页/36MB）：headless Edge 实跑——列表卡片「16 页 · 36MB · 16 步 · 管理员」、无标签无列表播放按钮；点击卡片 0.08s 内打开详情：「兼容版未生成 + 原始文件 36MB（OSS `ppt/src/.../source.pptx`，download=source.pptx）+ 在线预览 + 重新处理」；点在线预览进原播放器（`ppt-vmode`、真实 deck.mp4 `readyState=4、paused=false、err=0`），0 JS error；生产轻量标签查询实际 URL `ppt_decks?select=id%2Cfiles%3Amanifest-%3Efiles&deleted=eq.false&limit=100` 返回 200。
- **已知限制（如实）**：① 列表标签/大小依赖上面的 JSON 子字段轻查询（已实测线上 200）；若未来网关/表结构不支持会静默无标签（功能仍可用），彻底稳的方案是后端加 `has_compat/video_dur` 等轻字段（需契约 §4.4 与三端同改，本次未做）；② 旧 deck「在线预览」仅当旧 manifest 有 `slides`（v1 实际都有；video-only 旧 manifest 无独立播放器入口）；③ 网页下载为 `<a download>` 直连 OSS，移动浏览器/微信内可能改为预览或拦截（契约 12.4.2 已注），大文件不显示下载进度（只显示大小）；④ 详情打开期间列表 10s 轮询刷新不会实时重绘详情，状态变化需关闭重开；⑤ 「长按/右上 ⋯」菜单未做，保留原内联「重试/删除」按钮；⑥ 兼容版 deck 调用 `PPT.open` 会转为下载详情（大屏演示暂无直接放映兼容版能力，需转分步/视频旧模式才行）。
- **回滚**：本次未部署；回滚 = 用改前线上对象覆盖 `tools/index.html` 后重传（本机参考备份 `tools/_backup/index_online_20261110-2215_preStageV2.html`，**847,026 B / sha256 `411354e1…`**；注意该备份不含并行「大屏演示 V2」改动，回退会一并回退）；本次改动只在 PPT 块内（列表/详情 + 播放器保留），不影响其它工具逻辑。交付时工作区 `tools/index.html` **870,349 B / sha256 `ea799a2892809b4e08b6dffe59f7aaddff99066f11b50147381534ee28771dc3`**（含并行大屏改动，部署前请 Lead 以最终文件重算哈希）。
> **上线（2026-11-10 22:53，Lead 统一部署）**：`index.html` **870,349 B / sha256 `ea799a2892809b4e08b6dffe59f7aaddff99066f11b50147381534ee28771dc3`**（含同批「大屏 V2」）；`sync_tools.py index.html` 后 `oss_object.py check` = **MATCH**，`ecs_site.py apply` 后 ECS `/` 同字节（**MATCH**）。回滚点：`tools/_backup/index_online_20261110-2253_prePPTv2.html`（853,685 B / `9a158498…`，含大屏 V2、不含本 v2.0）；或再往前 `…2215_preStageV2.html`（847,026 B / `411354e1…`，两项改动之前）。

## 2026-11-10 22:2x · 大屏第二轮：重做布局（非四宫格）+ 换「墨夜雾青」配色

> 用户需求（2026-11-10 22:06）：「重新优化布局，不要局限于四格的布局，同时调整配色」。配色用户拍板 **A · 墨夜雾青**（深墨黑底 + 雾青 + 暖沙，延续站点品牌色）。
> 范围：仅网页 `tools/index.html` 大屏块 + `tools/tests/optim_v2_check.py`；行为/数据/契约不变（仍仅管理员、只读、UD v6 未动、APP_VER 2.0.0、零外部来源）。

- **布局（非四宫格）**：`.opt2-stage` = 顶栏（左「大屏」+ 日期，右大时钟 + 全屏/退出图标）→ 主体 `grid`：左侧 **大「演示」放映台**（主位 deck 大标题 + 状态行 + 「开始放映/继续放映」主按钮；其余 deck 为底部紧凑列表，可滚）+ 右侧**竖排「计时 / 抽签」双 tile**（1.06fr/.94fr）；底部单行页脚。手机 ≤900px 时纵向堆叠（演示台在上、计时/抽签并排在下），≤560px 再收字号/间距。
- **配色「墨夜雾青」**：深墨黑渐变底 + 顶部雾青辉光 + 左下暖沙微光；面板半透明渐变 + 1px 细边 + 顶部霓虹渐变高光；主色 `#5FA895`、点缀 `#C9A87C`；数字 `tabular-nums`；按钮雾青渐变（深色字）与 ghost 两种；装饰性大圆环（hero 右上）增加层次；入场 340ms 上浮淡入（`prefers-reduced-motion` 关闭）。
- **交互保持**：点主位/列表任一 deck → `PPT.open(id)` 全屏播放器（z110 叠 z95），退出自动回大屏；上次放映置顶并显示「继续放映」；空库居中「还没有演示 + 去上传」；加载失败「重试」；计时 05:00 开始/重置（到 0 复位按钮）；抽签 1 人；关闭恢复滚动/inert；关闭时暂停计时并把按钮复位。
- **选择器变更（测试/脚本注意）**：新增 `.opt2-top/.opt2-brand/.opt2-mark/.opt2-clock/.opt2-ibtn/.opt2-main/.opt2-hero/.opt2-hero-hd/.opt2-hero-deck/#o2sHero/.opt2-play/.opt2-rail/.opt2-tile/.opt2-num/.opt2-btn/.opt2-foot`；删除 `.opt2-stage-grid/.opt2-scard/.opt2-sbtn/.opt2-stage-top/.opt2-stage-foot/.opt2-time/.opt2-clockcard` 等；ID 保留 `o2sTime/o2sDate/o2sTimer/o2sPick/o2sDecks/o2sDeckEmpty/o2sDeckRefresh/o2sClose/o2sFs` 并新增 `o2sHero`。
- **测试**：`optim_v2_check.py` 更新（mock 3 个 deck；断言「非四宫格布局（hero+rail）」「主位+列表」「时钟在顶栏」等）→ **main 16 + admin 29 + hash 3 全绿，0 JS 报错**；回归 `v2_ui_check` 27/27、`optim_v1_check` GREEN、`overflow_check 430` = **overflowCount=0**；本机 CDP 截图 1366×768 / 1920×1080 / 430×900 / 空库态，无横向溢出、0 报错（视觉：主标题 48–64px、计时数字 96–112px、右侧两 tile 纵向排布）。
- **上线说明（含并行会话隔离）**：工作区 `tools/index.html` 当时含**并行会话未提交的 PPT 下载/标签 WIP**，为避免把未验收 WIP 上线，本次上线对象 = **HEAD + 仅本改造**的干净构建；线上 `index.html` **853,685 B / sha256 `9a158498806eb04ad2d75f437e112420afdb77ee5943b5b8122297edfc3aad83`**（OSS `oss_object.py sha` = 同值；ECS 从 OSS 同步后 `/` 返回同字节）。后续并行会话提交/部署其 WIP 时会覆盖为合并版；实际已于 2026-11-10 22:53 与 PPT v2.0 合并统一部署（线上 870,349 B / `ea799a28…`，见上一条）。
- **回滚**：重传 `tools/_backup/index_online_20261110-2215_preStageV2.html`（**847,026 B / `411354e1…`**，第一轮四宫格版）后 `sync_tools.py` + `ecs_site.py apply`。

## 2026-11-10 21:47 · 大屏改为团日主持台（去掉作业/下一节 · PPT 联动放映台 · 右上角实时时间）+ 合并 PPT v1.2 统一上线

> 用户需求（2026-11-10 20:52）：「去除大屏功能的作业，下一节课功能，因为该功能最大的可能使用场景只有团日活动的时候用，所以加强与PPT播放功能的联动，右上角可替换为实时时间，接着请你搜集网上案例给出可做功能案例」。
> 用户拍板：布局 B（原「作业」卡位换大时钟，2×2 = 演示 / 实时时间 / 计时 / 抽签）、PPT 联动 A（大屏内放映台）、可见范围保持仅管理员。
> 范围：仅网页 `tools/index.html` 的 OPTIM V2 §11 大屏块 + `tools/tests/optim_v2_check.py`；未改 UD v6 / 云端表 / 小程序 / 安卓；`APP_VER` 仍 2.0.0。本快照同时合并并行会话的「PPT v1.2 网页端」（其条目见下一条），**统一部署**。

- **去掉「下一节」「作业」两卡**：连同 `opt2StageNext/opt2StageHw` 数据函数一起删除（站点其它地方的课表/作业功能未动），大屏只留团日活动用得到的信息。
- **PPT 联动（左上「演示」放映台）**：`window.PPT` 新增只读访问器 `list()/loaded()/err()`；大屏列出共享演示库 `status=ready` 的 deck（上次放映置顶并标「上次」，本机键 `zq_stage_deck_v1`，不进 UD 同步）；点行 → `PPT.open(id)` 全屏播放器（z110 叠在大屏 z95 上），退出放映自动回到大屏、不跳页；空库显示「还没有演示 · 去上传」（关闭大屏并切到演示页）；加载失败有「刷新/重试」；打开大屏时同轮拉一次演示列表（只读 GET `ppt_decks`/`site_assets`，无新增外部来源）。
- **右上角实时时间**：大号 `HH:MM:SS` + `2026年11月10日 · 周二`，每秒走；顶部栏不再放小钟，「全屏/退出」移到右侧；计时到 00:00 后按钮复位「开始」。
- **文案/入口**：全部页入口「大屏演示」→「大屏」；标题「大屏」，页脚「仅管理员 · 团日活动」；`body.opt2-lock` / `.wrap inert` 关闭恢复不变。
- **测试**：`optim_v2_check.py` 大屏断言同步更新（实时时间每秒变、无「下一节/作业」、演示列表渲染、点演示打开播放器、退出回大屏、计时器、抽签、关闭后解锁）——**main 16 + admin 27 + hash 3 = 46/46 PASS，0 JS 报错 / 0 console.error**；回归 `v2_ppt_check` **86/86**、`v2_ppt_video_check` **99/99**、`v2_ui_check` 27/27、`optim_v1_check` GREEN、`overflow_check 430` = **overflowCount=0**；本机 CDP 截图（1366×768 / 430×900 / 空库态）无横向溢出、0 报错。
- **独立验收**（fresh context teammate，未复用本实现断言）：**67/67 PASS、0 FAIL、0 JS error**，覆盖管理员全流程/空库/500 失败/非管理员/1366×768+430×900 布局/代码事实/回归，报告 `验收报告/团日大屏_改造验收_20261110.md`（证据 `tools/tests/_stageqa/`）；遗留 P2：计时到底文案（已在本版修）、`overflow_check` headless 实际视口 492px（另用 CDP 真 430 复核）。
- **调研**：`验收报告/团日大屏_案例与可做功能_20261110.md`（19 个网上案例 + 16 条交互模式 + 12 项可做功能 P0/P1/P2 + 11 条不建议做），供后续排期（推荐下一批：F2 团日议程 rundown、F5 抽签大屏版、F10 播放器团日 HUD）。
- **并行合并说明**：同批包含并行会话的 PPT v1.2 网页端改动（`ppt/` 契约/转换机/测试 + `tools/index.html` PPT 块）与 `v2_ppt_video_check.py`；已在其自测 99/99 基础上由 Lead 复跑本机 99/99 后统一部署。
- **上线（2026-11-10 21:47，Lead 统一部署）**：`index.html` **847,026 B / sha256 `411354e1997db1cc77bf272f873d38bd409f0668181b2d1ea7a39431906feebc`**；`sync_tools.py index.html` 后 `oss_object.py check` = **MATCH**；`ecs_site.py apply` 后 ECS `/` 同字节（本地=ECS **MATCH**），`/board`、`/api/status`、`/tt.json` 200。DNS 暂停期以 OSS/ECS 字节为准，恢复解析后生效。
- **回滚**：整批改前线上对象 `tools/_backup/index_online_20261110-2121_preBigScreen.html`（802,355 B / `e40571d3…`，今日两增量之前，最干净）；仅回退 PPT v1.2 = `tools/_backup/index_online_20261110-2146_prePPTv12.html`（845,241 B / `10167956…`，含大屏不含 v1.2 定稿）。回滚＝用对应备份覆盖 `tools/index.html` 后重传 OSS + `ecs_site.py apply`。

## 2026-11-10 21:3x · PPT 演示 v1.2（网页端）：原样播放（高保真视频）+ 续播 + 列表便捷 + 热点时序修复（**已上线：2026-11-10 21:47 由 Lead 统一部署**）

> 用户反馈（2026-11-10 20:39）：「继续优化在各设备上的演示效果，我希望的是在网络良好时达到电脑本地文件的播放效果，目前 PPT 内动画全部消失，视频也依然无法播放，且各端操作都不够便捷」。
> 契约唯一真源：`web/ppt/CONTRACT.md` §11（v1.2，§11.1 manifest.video / §11.3 播放器 / §11.5 网页约束）；设计参考：`web/ppt/DESIGN.md` §4.3–4.9。
> 本条只记**网页端**（`tools/index.html` + 专项测试）；转换机 `manifest.video` 导出、小程序/安卓由其它实现者交付。`APP_VER` 仍 `2.0.0`；单文件零依赖、无新增外部请求/字体/CDN。

- **原样播放模式（`manifest.video`）**：新增视频层（全屏黑底 letterbox `<video playsinline>` + 自定义控制条），**仅当 manifest.video 有效（s + dur>0）时创建该层 DOM**，旧 deck 完全不受影响；视频 URL 仍按 §5 相对 `manifest.base` 解析（http/https/data 直连）。`chapters` 缺失/不全/乱序都不报错：无章节时隐藏页码/禁用上下页，进度条仍可 seek。
- **视频控制条（3s 自动隐藏，鼠标/触摸唤出）**：播放/暂停、`mm:ss / mm:ss`、**上一页/下一页按 chapters seek 到 `t+0.05` 且保持播放/暂停状态**、章节进度条（刻度点可点 seek、条上点击也可 seek）、倍速 1×/1.25×/1.5×/2× 循环、全屏、**下载原样视频（`<a download>`）**、退出、顶栏「原样 / 分步」模式胶囊（分步模式下也显示胶囊，便于随时切回）；页面顶部显示「第 3/16 页」（当前页 = 最大的 `chapters[i].t ≤ currentTime`）。缓冲/加载态：`loadedmetadata/canplay` 前显示轻量 spinner，`waiting/stalled` 时显示，恢复即撤，不白屏。
- **默认模式/偏好**：`manifest.video` 存在且网络良好（`navigator.connection`：非 `saveData` 且 `effectiveType` 非 `slow-2g/2g/3g`；无 API 时看 `onLine`）→ 原样播放 + 自动播放（列表进入属用户手势；被拒时显示大播放按钮、不报错不弹错）；无 video / 弱网 → 分步浏览。用户手动切换写入本机偏好 `zq_ppt_mode_v1`，下次优先（仍可切换；弱网也尊重手动选择）。
- **键盘/手势**：Space 播放暂停、`←/→` 上一页/下一页（章节）、F 全屏、Esc 退出（未看完为站内「退出演示？/继续/退出」）、M 切模式；左右滑 = 章节翻页；点击舞台 = 显示/隐藏控制条（**视频模式不做左右 1/3 点击翻页**，1/3 点击仅保留分步）；点按舞台与鼠标移动都会先唤出控制条，点击切换以 pointerdown 前状态为准，避免「鼠标动一下就点不出去」。
- **失败/卡顿降级**：`error` 或 `waiting` 连续 2 次超过 4s → 重试 1 次（保留已看位置）→ 仍失败自动切分步 + toast「网络不佳，已切换分步浏览」，播放器不关闭、分步主图随后渲染，不白屏；失败回退后再手动切回原样允许重新尝试一次。
- **续播（§11.3.4）**：按 deckId 保存 `zq_ppt_pos_<deckId> = {mode,slide,step,t,at}`（仅 localStorage，7 天有效）；打开时自动续播（视频 seek 到 t / 分步到 slide+step），并 toast「续播 mm:ss / 第 N 页」；视频模式每 1.5s 节流落盘、暂停/切换模式/关闭时立即落盘；**看完到末尾（`ended` / t≥95%）或手动「从头播放」清除记录**；分步模式续播时控制条动态插入「从头播放 ↺」（手机自动压缩控件保证单行不溢出）。列表卡片显示「继续」小徽标（7 天内且未到末尾；过期/已看完不显示）。
- **列表便捷**：整卡点击 = 按默认模式直接播放（原有封面大「▶」保留）；本机缓存过 `manifest.video` 的 deck 在封面右下显示「原样 m:ss」短胶囊（列表查询仍按 §4.4 **不带 manifest**，不新增请求）；删除/重试/空态/状态胶囊等既有行为与文案不变（网页 v1 无重命名入口，未新增）。
- **分步模式增强 · 热点时序 bug 修复**：根因是切页时 `syncHot()` 可能在图片解码/布局完成前读到 0×0 矩形，且旧代码在「6s 兜底 start」之后 `onload` 不再重算 → 图片晚到时热点永久为 0。修复：新增 `paintHot/syncHot/hotBurst/hotWatch`，在 **图片 `load`（onload + 捕获阶段）/ CSS `transitionend` / resize+orientationchange / 过渡刚开始（图片解码后 rAF 提前绘制）/ 60-240-700-1500ms 定时补算** 全部重算，图片晚到（含 >6s 兜底路径）热点也必现；热点直径 ≥56px（手机 64px，音频热点仍 32px）、保留「视频 m:ss」角标、新增轻微脉冲环（`prefers-reduced-motion` 关闭）；点击播放逻辑/媒体层生命周期不变。页码/步点/缩略图/备注/黑屏/全屏/下载原件/退出确认全部保持原行为。
- **代码位置（保持单文件）**：CSS 追加在 `</style>` 前、以 `/* __PPT_VIDEO_V1__ */` 分隔；JS 全部在 `var PPT=(function(){…})()` 块内（视频/续播函数新增约 600 行，既有函数内增量）；未新增任何全局 API 名（仅 `PPT` 现有导出）；`__PPT_FEATURE_V1__` 标记仍 CSS+JS 各一。
- **验收（本机真跑，真实输出；最终文件 847,026 B）**：新增 [`v2_ppt_video_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_video_check.py) **99 项全过 / 0 FAIL**（88.0s；CDP mock 复用 `v2_ppt_check` 基座 + 自建慢图服务器；假 token，非 mock 写请求全部拦截 → 0 真实云端写；覆盖默认模式网络判断/控制条与章节 seek/倍速/下载/模式切换与偏好/键盘/滑动/点舞台显隐/弱网默认分步/error→重试→分步回退+toast/自动播放被拒→大播放钮/续播恢复+「继续」徽标+原样时长胶囊+从头/看完重置/**热点 700ms 慢图**与**6.5s 超兜底慢图历史 bug 复现**/resize+orientation+快速连切/430px 无横向溢出/0 JS error/0 console.error）。既有 [`v2_ppt_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_check.py) **86/86**（连续 3 次全过）；合并统计 **86+99=185 项 ≥110**。回归（真实输出）：`overflow_check 430` = overflowCount 0、`v2_ui_check` 27/27、`v2_pos_restore_check` 12/12、`v2_x5_anim_check` 28/28、`v2_drag_check` 56/56。真实 deck `dmwalrdlgevz90l`（16 页、第 12 页内嵌 225.6s 视频，当前 manifest 尚无 video）：headless Edge 实跑，第 12 页主图 `s12-1.webp` 网络 2.7–6.6s 才到时热点**自动出现**（n=1、「视频 3:46」、页码 12/16，无需重试/resize），点击热点打开媒体层读到真实视频 `dur=225.58s · 1024×576 · err=0`，全程 0 JS error/0 console.error。
- **已知限制（如实）**：① 列表「原样 m:ss」胶囊首见需该 deck 在本机被打开过一次（列表轻字段禁带 manifest，遵守 §4.4；若需首次即显示，应改契约加 `has_video`/`video_dur` 轻字段，三端同步）；② `waiting` 超 4s×2 的自动回退路径按契约实现，自动化只覆盖 `error` 路径（实时等 8s 不划算；代码路径已按同一 `vTrouble` 分支）；③ 真实用户 deck 当前 `manifest.video` 尚未生成（转换机 v1.2 补转后自动生效，网页端无需再改）；④ 自动播放被系统策略拒绝时显示大播放按钮（不静默、不报错），iOS/微信内可能需再点一次；⑤ 视频下载用 `<a download>`，移动浏览器/微信可能改为预览或拦截（能力允许的端提供）；⑥ 分步图/视频转场沿用原有限制（分步=每步最终态；视频±1s 章节误差由转换机公式决定）。
- **回滚**：改前线上对象备份 `tools/_backup/index_online_20261110-2055_prePPTv12.html`（**802,355 B / sha256 `e40571d395f32af735243673f7e93c6d008788143b046a7b15df2ec0c4142c50`**，与 ECS 当前 `index.html` 一致）；回滚 = 用该文件覆盖 `tools/index.html` 后重传。本次**未部署**；交付时工作区 `tools/index.html` **847,026 B / sha256 `411354e1997db1cc77bf272f873d38bd409f0668181b2d1ea7a39431906feebc`**（含另一路并发改动 `opt2StageLastDeck` 等「大屏演示入口」代码，非本条目；部署前由 Lead 确认合并状态、以最终文件重算哈希）。
- **测试稳定性补丁（仅测试文件、语义不变）**：[`v2_ppt_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_check.py) 里 2 处键盘「←/PageUp 后退」断言原为 `sleep(0.5)` 后立即比对（本 fixture 转场 `trd=450` + 40ms → 只有 10ms 余量，负载高时偶发读数早于 idx 更新），改为等 idx 到达目标值（≤2s）再断言；断言内容/覆盖不变。改后本机连续 3 次运行 `v2_ppt_check` 均 **86/86**（改前同样代码在本机 3 连 85/86 抖动，实测与功能无关）。
- **上线（2026-11-10 21:47，Lead 统一部署）**：合并后 `tools/index.html` **847,026 B / sha256 `411354e1997db1cc77bf272f873d38bd409f0668181b2d1ea7a39431906feebc`**（含同批「大屏团日改造」）；OSS `oss_object.py check` = **MATCH**、ECS `ecs_site.py verify` = **MATCH**。本条目原「本次未部署」状态已由该次统一部署解除；整批回滚点 = `tools/_backup/index_online_20261110-2121_preBigScreen.html`（802,355 B / `e40571d3…`）。

## 2026-11-10 18:5x · 迁移 ①ECS 备案落点 + ②通知附件外置（签名 URL）+ ③同源/缓存（网页已上线；三端附件兼容改造中）

> 背景：ICP 备案尚未通过（`furina.fun` 6 条 DNS 记录仍 DISABLE），本步先把内地落点与三端兼容能力做好，备案后一键切换。
> 用户决策：② 采用「ECS 私有存储 + 签名 URL」方案（A），且**要求三端一起发布**。

- **① ECS 备案落点（已完成）**：新增 `deploy/ecs_site.py`（云助手 RunCommand，无需 SSH）把 OSS 最新站同步到 `/var/www/tool`；Caddy 增加 `encode zstd gzip`、缓存头（index/tt/board no-cache、assets 7 天）、`/att/*` 与 `/v1/rdb/rest/*` 路由；HTTPS 就绪配置写入 `/etc/caddy/Caddyfile.https.ready`（等备案 + DNS 恢复后 `apply --https` 自动签发）。实测 ECS `index.html` 802,355 B / sha256 `e40571d3…`、gzip 传输 260,997 B、`/board`/`/api/status` 不受影响；文档 `deploy/ECS_DEPLOY.md`。
- **② 通知附件外置（服务与网页端已完成，默认关闭）**：新增 `attachments/`（契约 + 纯标准库服务端 + 本机客户端 + 单测）与 `deploy/ecs_attachments.py`；ECS `class-tools-att.service`（127.0.0.1:8091，数据 `/opt/class-tools/attachments`，签名 URL `HMAC-SHA256(sha256(SYNC_TOKEN|att-v1), id+exp)`，180 天、内容寻址、不可枚举）；本机 `sync_notices_cloud.py` 以 `NOTICE_ATTACH_EXTERNALIZE=1` 开关接入（失败保留 data URI，fail-open）；实测 40 个去重附件 6.1 MB 上传后，board 通知体 **8.05 MB → 0.17 MB**，签名 GET 200/篡改 403。网页模板（`briefdesk-plan/build_notice_board.py` + `build_notice_embed.py`）已兼容 URL 与 data URI 双形态（`v2_attach_url_check.py` 9/9、`v2_notice_data_check` 27/27 全绿）。**不默认开启**：旧版小程序/安卓未见新版前遇到 http/IP URL 会坏，按「三端一起」等备案通过后统一开。
- **③ 同源/缓存（已完成）**：网页 `CB` 在 `tool.furina.fun`/`tool.furina.fun` 下运行时改走同源 `/v1/rdb/rest/*`（ECS 反代 CloudBase 网关，消除 CORS 与跨云一跳；`var CB` 字面量保留给本机脚本解析）；静态站 gzip 32.5%。
- **上线**：`index.html` **802,355 B / sha256 `e40571d395f32af735243673f7e93c6d008788143b046a7b15df2ec0c4142c50`**（OSS `check` MATCH + ECS 同步 MATCH）；改前线上对象备份 `tools/_backup/index_online_20261110-1900_preAttUrl.html`（800,243 B / `4412f5fc…`）。
- **三端改造已完成（2026-11-10 晚）**：小程序 `nt.js`（`unit.js` **305/0**，新增 8 条 URL 用例）、安卓（`testDebugUnitTest` **934/0**，新增 30 条）；均保持 data URI 兼容、版本号未 bump、未发布/未构建 APK。
- **未完成（等备案）**：开启 `NOTICE_ATTACH_EXTERNALIZE` 与存量回填；`apply --https` 切域名；小程序后台加 downloadFile 域名；安卓正式版只能走 https。
- **回滚**：网页重传上述备份；ECS 回滚 `/var/www/tool_backup/<时间戳>/` + `/opt/class-tools/backup/<时间戳>/`；附件服务可 `systemctl stop class-tools-att`（旧 data URI 数据仍可读）。

## 2026-11-09 22:5x · PPT 演示（网页端）：上传自动转换 + 分步全屏播放器（**本地完成，待 Lead 统一部署**）

> 需求（2026-11-09，用户场景）：教室老电脑播 PPT 卡死、嵌入视频「媒体不可用」→ 上传端只传源文件，本机转换机转成「分步图片 + H.264 小视频」，任意设备流畅播放。
> 契约唯一真源 `web/ppt/CONTRACT.md`（§3 表 / §4 接口 / §5 manifest+播放语义 / §7 转场 / §8.2 网页）；设计参考 `web/ppt/DESIGN.md`。
> 本条只记**网页端**（`tools/index.html` + 专项测试）；小程序 / 安卓 / 转换机由其它 agent 交付。`APP_VER` 仍 `2.0.0`。
> **已上线（Lead 统一部署，2026-11-09 23:04）**：线上对象 **800,243 B / sha256 `4412f5fc16200a8787d496a2845555332d350b5d42525fd04721c2f572efafb1`**，
> `deploy/oss_object.py check index.html` = **MATCH**；回滚 = 重传 `tools/_backup/index_online_20261109-2220_prePPT.html`（732,621 B / `65610511…`）。
> 真实端到端（真实云端 deck + 真实 OSS 图片/视频，Lead CDP 脚本）已 PASS：桌面 16 页、430px 触摸滑、含视频 deck `video paused=false dur=3`、0 JS error。

- **新工具「演示」（纯增量）**：`TOOLS` 追加 `{k:"ppt",n:"演示",d:"PPT 上传自动转换 · 分步 + 视频 · 任意设备流畅播放"}` → 顶部工具栏 / 全部页卡片 / 首页槽位补齐 / 刷新保位（POS）/ 全部页拖动均自动收录；现有工具顺序与既有行为零改动。站点其它逻辑只动 4 处挂钩：TOOLS 一项、`gotoTab` 两行（`PPT.leave()` / `enter()`）、站点滑动引擎 `resolveStart` 排除 `#pptPlayer` 一行。
- **列表页**：暖白卡片（手机 96 高横向「封面 128×72 + 信息」/ ≥960 桌面 3 列 16:9）、封面 `loading=lazy`、标题、`页数 · 步数 · 上传者`、状态胶囊（`上传 34%` / `排队转换` / `转换中 61%` / `转换失败`+error 行+`重试` / `上传中断`；**ready 不显示胶囊**只给播放）；本人进行中置顶；别人的 `uploading` 行不显示；本人卡片可删除、失败可重试；空态「还没有演示文件」+ 上传按钮（无插画/无解释句）；首次进入骨架 3 张。
- **上传**：`File.slice(512KiB)` → base64 → 分片；先 `POST ppt_decks` 建行（`d`+base36(ts)+6 位随机）→ `POST ppt_upload_chunks`（并行 ≤4、失败 400/1200ms 退避重试 2 次）→ `PATCH status=queued`；标题默认=文件名去扩展名（≤80 字可改后再传）；进度=`上传 N%`（片数比、只增不减），切后台提示「上传中 · 勿退出」；取消=软删；`>60MiB` 与非法扩展名直接拒绝。
- **轮询**：列表页可见时 10s（`visibilitychange` 停/启，切到本页立即拉一次），每轮**同轮**拉 `site_assets?id=eq.ppt_agent`；`seen_at>180s` 显示「转换机离线 · 排队中」（不报错、不白屏）。
- **全屏播放器**（`position:fixed;z-index:110` 独立 DOM，打开时记录并锁定原 tab+滚动位置，退出恢复；不写 POS）：纯黑舞台 + 图片 `contain` letterbox；`tr` 转场 none/fade320/push360/wipe380/zoom300/cover340，页内 step 130ms 淡入；**页码按「页」、顶部 2px 进度按 step、页内步点仅 step≥2**；点击右 2/3 前进 / 左 1/3 后退（**后退粒度=step，step=0 退到上页末步**）；鼠标拖 + 触摸横滑（阈值 40px 或屏宽 12%，指针捕获只在确认横向拖动后设置）；键盘 → ← ↑ ↓ Space PageDown/PageUp Esc F N/S T B/.（**翻页不唤出控制条**）；控制条单行（桌面 52 / 手机 48）3s 自动隐藏、移动/触摸唤出、隐藏时桌面 `cursor:none`；缩略图抽屉（桌面左侧 288 全高 2 列 / 手机底部 62vh 3 列，当前页描边 + 多步页短线，内部横向滚动到当前页）；备注抽屉（桌面右侧 320 / 手机底部 50vh，**不透明底**，空→「本页无备注」，`H` 长按 1.5s 瞬显）；媒体热点按 `x/y/w/h` 叠在**图片实际渲染区域**（56/48px 圆钮 + `视频 0:12` 时长角标），**点击才加载/播放**、不自动播，失败灰化 +「视频不可用」且不阻塞翻页，媒体层**只在换页/退出销毁**（不随 step 卸载）；首帧 `cover_url` 铺底→step 图 120ms 淡入（无「加载中」文字）；预加载后 2 张、切完释放旧图解码（常驻 ≤5）、低端机（`hardwareConcurrency≤2` / `deviceMemory≤2`）强制 `fade 200ms` + 步内 0ms；图片失败保留上一张 + 「图片加载失败 · 重试」；有进度退出给站内「退出演示？/继续/退出」（不用原生 confirm）；全屏按钮走 Fullscreen API，不支持/被拒时降级隐藏控制条的沉浸模式；B 黑屏任意键恢复且恢复不显示 UI。
- **隔离/合规**：CSS/JS 全部收在 `/* __PPT_FEATURE_V1__ */` 两块内（CSS 187 行、HTML 26 行、JS 1255 行 / 96 个函数）；无外部脚本字体 CDN、不引构建链、无新增密钥（前端只用现有 PUBLISHABLE KEY + token 机制）；`APP_VER` 仍 `2.0.0`。
- **验收（本机真跑，真实输出）**：新增 [`v2_ppt_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_check.py) **86 项全过 / 0 FAIL**（0 JS 报错、0 console.error；CDP `Fetch.fulfillRequest` **只 mock `ppt_decks` / `ppt_upload_chunks` / `site_assets` 三路径**，注入**假 token**，非 mock 写请求全部 fail 并计数 → **0 真实云端写**；430px 列表+播放器无横向溢出；播放器内鼠标拖与合成触摸滑动后 `section.on` 仍为 `#s-ppt`；截图 `tools/tests/_shots_ppt/` 12 张）。回归（真实输出）：`overflow_check 430` = **overflowCount=0**（改前基线同为 0）、`v2_ui_check` **27/27**（改前 27/27）、`v2_pos_restore_check` 12/12、`v2_drag_check` 56/56、`optim_v1_check` GREEN 14/14、`v2_x5_anim_check` 28/28（首轮 27/28 为新增 `.ppt-layer` 的 `will-change` 触发 S8，已移除该 CSS 后复跑全绿）。
- **已知限制（如实）**：分步图只取每步最终视觉态（同段逐字出现合并、强调/运动路径只取快照）；转换机离线时只排队；专项测试用 `data:` fixture 清单，未做真实上传→真实转换→真实 manifest 的端到端（按契约 §9.3 由 Lead 用测试身份执行）；客户端不解析 pptx 页数，DESIGN 的「>60 页」预提示未做；图片失败为手动单次重试，未做「连续 3 张失败降级 thumb」；iOS Safari 无元素全屏 → 走沉浸降级。
- **回滚**：改前线上对象 `index.html` **732,621 B / sha256 `656105117464c6d67106faa4011d5dd806d11d2c0d44760df961488d92e3b420`**（`tools/_backup/` 形态）；回滚 = 用该对象覆盖 `tools/index.html` 后重传。本次**未部署**。

## 2026-11-09 19:55 · 过期判定补强：无具体时间的失效通知 / 已处理过期也进过期栏 / 招聘等分类消失

> 用户反馈（2026-11-09 19:53）：「再次检查是否有虽然未具体提时间但实际已过时效的通知，同时注意已处理的过期通知也要放入过期栏里，同时我这边看像招聘等分类还是没消失」。

- **无具体时间但已过时效**：`ai_quality.py` 质检规则补强——没有明确日期时结合每条消息时间判断；一次性事件（招聘会/宣讲/比赛/会议/培训/报名）消息距今 >2 天且无未来截止/活动 → 判过期，expireAt 取消息当天 23:59；结果/名单/录取公布、已招满、活动已举办等同样判过期；培养方案/发票下载/选课方式等长期资料不算过期。重跑 66 组后过期从 34→**40 组**，新增识别：「运动会期间晚自习正常」「军训动员大会场地划分」「招聘会志愿者录取名单/结果」「综合管理服务类专场招聘会」等。
- **已处理 + 已过期 → 进过期栏**：模板 `statusOf()` 改为**先判过期、再判已处理**（报名截止/截止/活动结束任一已过即返回 expired），已处理的过期通知不再留在「已处理/待处理」，统一进「已过期」区（统计也计入过期）。
- **招聘等分类消失**：分类 chips 规则（至少一条未过期通知才展示）+ 上面补强后，当前 66 组只剩 **5 个分类**：教务、活动、班级事务、志愿、军训；「运动会」「招聘」因全部项目已过期而不再单独展示（过期卡片仍在已过期区、保留历史分类徽标）。选中中的分类消失会自动回「全部分类」。
- **上线**：`index.html` **732,621 B · sha256 `656105117464c6d67106faa4011d5dd806d11d2c0d44760df961488d92e3b420`**（模板重新嵌入并部署，OSS check **MATCH**）；改前备份 `tools/_backup/index_online_20261109-1959_preDoneExpired.html`（732,317B / `26684487…`）。云端 notices 66/66 已同步新的过期字段；小程序分类过滤改动仍待上传。
- **验证**：`v2_notice_quality_check` **20/20**（新增 Q17 已处理+过期仍过期、Q18 无时间已过时效、Q19 招聘分类消失）；`v2_notice_dynamic_cat_check` 18/18、`v2_notice_data_check` 27/27、`v2_notice_live_check` 16/16、`v2_admin_check` 39/39、`v2_ui_check` 27/27、`v2_notice_time_check` 64/72（8 项存量）、overflow 430=0、模板嵌入 YES。
- **刷新提示**：网页版需下拉刷新/重开通知页（浏览器/微信 WebView 可能缓存旧 index），新版分类行应与上述 5 类一致。

## 2026-11-09 19:32 · 分类再优化：全部项目都已过期的分类不再单独展示

> 用户反馈（2026-11-09 19:29）：「如全部项目已过期则不单独分类」。

- **规则**：分类 chips 只展示「至少还有一条未过期通知」的分类；某分类下的通知全部过期后，该分类自动从 chips 消失（对应过期卡片仍保留历史分类徽标、仍在「已过期」区可查）。若某一刻所有通知都已过期，分类行整体隐藏（只留已过期列表）。当前效果：7 类中「运动会」8 组全部过期 → 不再单独展示；军训/招聘等仍有未过期通知的分类保留。选中中的分类消失时自动回「全部分类」。
- **实现**：模板 `catList()` 按 `statusOf(g)` 过滤（expired/extended_past/alert 不计入活跃），`renderCatChips()` 无分类时隐藏整行；小程序 `pages/nt/nt.js` 同步口径（`g.expired` 的分类不进入 chips，刷新后选中消失回全部）。纯前端计算，云端 body 无需改。
- **上线**：`index.html` **732,317 B · sha256 `266844873bbdd4ea12dabc1e8db415dab8dd816d025e8b98dce0a63ebf4486ad`**（OSS check MATCH）；改前备份 `tools/_backup/index_online_20261109-1932_preExpiredCatHide.html`（731,777B / `c21787b9…`）。小程序需用户上传发布；安卓无分类筛选，无需改。
- **验证**：`v2_notice_quality_check` 新增 Q16（每个展示分类仍有未过期通知）→ **17/17**；`v2_notice_dynamic_cat_check` 18/18（E12 动态新增分类改用未过期通知）；`v2_notice_data_check` 27/27、`v2_notice_live_check` 16/16、`v2_admin_check` 39/39、`v2_ui_check` 27/27、`v2_notice_time_check` 64/72（8 项存量）、overflow 430=0、模板嵌入 YES；mp `node --check` + `unit.js` 259/0。
- **回滚**：重传 `tools/_backup/index_online_20261109-1932_preExpiredCatHide.html`；小程序改动随下次上传覆盖。

## 2026-11-09 18:40–19:00 · 通知质量优化第二轮：AI 质检 / 自动过期 / 多报名窗口 / 附件补链 / 分类阈值 / 去噪

> 用户反馈（2026-11-09 18:34）：「① 只有出现大量同一类别通知时才新建分类；② 11月4日至6日观赛人员安排、11-06运动会赛程及名单这类通知明显在6号过后就应设为过期状态；③ 河洛夜市摊位招募11-20的报名截止时间识别成了开始时间；④ 成绩认定与免修申请11-11截止附件未识别；⑤ 小儿体质养护科普活动11-10启动分别有三个报名时间，需做特殊优化；⑥ 还有部分无内容通知和明显不属于通知的内容，请做完整优化，ai识别应做到质量最优化，无需考虑成本」。
> 范围：briefdesk 数据管线（新增 AI 质检层、微信附件补链、rar 内容识别）+ 网页通知模板/部署；小程序/安卓无需改（signupWindows 被忽略、过期用 eventAt/expireAt 表达，旧客户端同样显示过期）。本条目叠在当日 18:3x「体验优化 V2」之上，未改动该增量的任何网页功能。

- **① 分类阈值**：`ai_categories.py` 新增 `MIN_NEW_CAT=3`——只有同一主题 **≥3 条**才允许新建分类；`repair_small_new_cats()` 会把数量 <3 的分类交给 AI 并入已有大分类（失败归「其他」），缓存里遗留的碎片分类会自动整理一次。当前 66 组 **7 类**：活动 18、志愿 14、教务 12、运动会 8、班级事务 7、军训 4、招聘 3（每类 ≥3；「宣传」「团务」已并入）。
- **② 自动过期**：新增 [`ai_quality.py`](C:/briefdesk/scripts/ai_quality.py) 逐条 AI 质检层（原文全文 + 附件/链接识别正文 → 是否通知、时间语义、是否已过期、多报名窗口、要点/摘要修正；按组内容 hash 缓存，只重算变化的通知）。已过期通知统一写 `eventAt` + `expireAt`（三类客户端天然展示「已过期」）：11-04/11-05/11-06 运动会项目名单、**11月4日至6日观赛人员安排**、**11-06 运动会赛程及名单**等 **33 组可见历史通知**已按期过期，不再挂在待处理（AI 共判 34 组过期，其中 1 组同时被判「非通知」已剔除）。
- **③ 河洛夜市**：AI 质检纠正为 `deadline=2026-11-09 22:00 · 报名截止`、无 `signupStart`（不再显示「报名开始」）；「11-11 22:00 公布审核结果」不再被误当报名截止。
- **④ 成绩认定附件**：微信 rawContent 文件 appmsg 补链（`wechat_media.py` / `ai_triage.py`）把群文件 `关于开展…成绩认定与免修申请工作的通知11.9.rar`（1,804,210B）挂到通知；`archive_scan.py` 用 `-sccUTF-8` 修中文名乱码并解压识别包内 2 个 docx；`attachment_digest.py` 把压缩包 AI 要点并入识别正文 → AI 以**附件正式通知为准**把截止从消息里的 11-11 修正为 **11-13**（并保留「审核截止 11-15」要点）。
- **⑤ 小儿体质三报名窗口**：AI 质检产出 `signupWindows`（子活动一/二/三：11-10、11-11、11-12 各 12:00—18:00），三个时间写入要点；网页模板按当前时间**动态显示当前/下一个报名窗口**（状态 chip 保持「时间+短动作」契约，如「17 小时后 报名开始」；三窗口以要点/窗口数据体现）；云端 body 同步下发 `signupWindows`（`sync_notices_cloud.compact_group`），小程序/安卓用 signupStart（最早开始）/signupEnd（最晚结束）兜底。
- **⑥ 去噪 + 质量最优化**：AI 质检逐条判断，剔除 5 条非通知/无内容（红会卫生碎片对话、采访招募已结束过程消息、急救点闲聊、纯图片无文字、APK 文件无说明）；全量扫描 66 组已无「未识别/无内容」残留；公众号链接 URL 做 `html.unescape`（`&amp;`）后补识别（综合管理服务类招聘会标题/发布信息不再显示「原文未能完整读取」）。判「不是通知」的旧结论会保留在 `ai-quality.json`，避免 triage 每轮重新产出又出现「删了又回来」。
- **上线**：`index.html` **731,777 B · sha256 `c21787b9cc1323cc00e5c24b769d3c5ab640d79113e7b227b696def5e9b4bdb9`**（APP_VER 仍 2.0.0；模板增加 `g.expired` 与 `signupWindows` 动态逻辑，已重嵌并部署）。改前线上对象备份：`tools/_backup/index_online_20261109-1910_preWindowFix.html`（731,593B / `4407ae6f…`，本增量第二次补丁）；更早 `tools/_backup/index_online_20261109-1907_preLabelFix.html`（731,729B / `c0a38b8a…`）、`...1854_preQualityExpire.html`（730,113B / `a7b26001…`，当日 V2）；`oss_object.py check index.html` = **MATCH**。云端 `public.notices` 66/66 同步，分类分布与本地一致。桌面 demo 副本已刷新。
- **验证**：新增 [`v2_notice_quality_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_notice_quality_check.py) **16/16**（过期/河洛/多窗口/附件/去噪/分类阈值/0 JS 错）；`v2_notice_dynamic_cat_check` **19/19**、`v2_notice_data_check` **27/27**（此前存量 D22 因质检重新生成要点后也转绿）、`v2_notice_live_check` **16/16**、`v2_admin_check` **39/39**、`v2_ui_check` **27/27**、`v2_notice_time_check` **64/72**（较改前基线 62/72 提升，剩余 8 项为存量花名册/献血断言）、`overflow_check 430`=0、`_check_template_embed_match`=YES；`detect_docs.py --rebuild` 端到端 exit 0 且完全幂等（quality called=0、categories cached、66 组稳定）；本轮未改小程序/安卓。顺带修掉 `detect_docs.py` 控制台 cp936 遇 emoji 标题崩溃的隐患（stdout 强制 UTF-8 replace，--watch 长期稳定）。
- **已知限制**：公众号文章部分需微信环境验证（只能取标题/极短正文）；无 OCR（纯图片通知仍会丢弃或仅标题）；多报名窗口的「动态当前窗口」是网页端能力，小程序/安卓显示构建时的首个窗口/跨度；分类阈值会随通知自然增删（<3 条的旧分类会被合并）；Android/小程序需各自发布/升级后才看到最新数据。
- **回滚**：线上重传 `tools/_backup/index_online_20261109-1910_preWindowFix.html`（本增量第二版；要回到本增量初版用 `...1907_preLabelFix.html`；要回到无本增量用 `...1854_preQualityExpire.html`）；代码/数据回滚详见 `C:\briefdesk\data\_backup_quality_20261109\ROLLBACK_NOTES_quality.md`（含 ai_quality.py 删除、各文件逆改、数据快照、云同步恢复）。

## 2026-11-09 18:3x · v2.0.0 体验优化 V2（微信导出图 / 公平随机 / 汇总导出 / 大屏演示等 11 项）

> 用户决定（2026-11-09）：除「汇总作业、通知/作业未处理人数、变更留痕、WakeLock」不做外，其余全做；「课堂/班会大屏模式」暂时只做**管理员可见 demo**。
> 基线/回滚：改前线上对象 `tools/_backup/index_online_20261109_1835_preOptimV2.html`（703,054 B / `6cef5da1…`，含另一路 agent 18:24 的更新）。

- **微信内导出图（修复）**：微信内置浏览器拦截 `<a download>`，导出后改为**显示图片 + 「长按图片保存（或截屏）」**弹层；非微信保持原下载。图片用 blob URL，弹层期间背景 `inert`。7 个导出入口共用 `exportCard()`，一处生效。
- **公平随机源**：抽签/分组/剔除补抽的 `Math.random` 全部换成 `crypto.getRandomValues` + 拒绝采样（`rndInt(n)`，crypto 不可用时回退），消除模偏；行为与结果格式不变。
- **toast 无障碍 + 错误区分**：`#toast` 加 `role="status" aria-live="polite" aria-atomic="true"`；错误提示（失败/无效/不能/请先…）自动 2600ms + 暖沙色条，成功保持 1900ms。
- **汇总导出图**：点名页新增「导出汇总」（应到/已到/请假/未点），水量页新增「导出汇总」（房间数/人数合计/本期用水/水费/超定额房间数）；图内**不含姓名/学号/房间号**，复用 exportCard 规范。作业汇总按用户要求不做。
- **电费 tile「较上窗口 Δ%」**：区间用电对比上一同长窗口（24h 用 7d 数据、7d 用 30d 数据，缓存可用时才显示），下降=雾青、上升=暖沙；不新增请求。
- **URL `#tab=` 直达**：切工具写入 `#tab=xxx`（不覆盖既有 `#tt=`/`#edit` 分享 hash），带 hash 打开/分享可直达对应工具；hashchange 也能切换。
- **备份弹层显示本机存储用量**：`navigator.storage.estimate()` → 「已用 x MB · 可用约 y MB」。
- **打印 / 存 PDF**：作业清单与抽签结果单旁新增「打印」（桌面浏览器 `window.print()` + `@media print` 只留当前页）；微信内不触发。
- **背景 `inert`**：导出图/大屏/备份弹层打开时对 `.wrap` 加 inert（不支持的内核自动跳过），关闭复原。
- **抽签参数预设（本机）**：抽签页新增 3 套预设（范围/个数/重复/排除 + 分组参数），存 `zq_presets_v1` 本机、不进 UD v6。
- **管理员「大屏演示」**：全部页底部（仅管理员）「大屏演示」→ 全屏深色班会大屏 demo：下一节/作业未完成数/5 分钟计时/抽签演示（只读演示，不改动任何数据/云端）；含全屏按钮与 Esc/退出；**不做 WakeLock**（按用户决定）。
- **测试（全部本机实跑，合并后真实文件）**：`_v2/v2_check.py` 新增 **40 项全过**（含微信 UA 导出弹层、inert、大屏、预设、hash、错误 toast、存储用量）；`optim_v1_check` 14/14、`v2_ui_check` 27/27、`v2_drag_check` 56/56、`overflow 430`=0、`reset_check` 109/109、`sync_check` 144/144、`v2_sync_check` 35/35、`perf_check` 123/123、`v2_admin_check` 39/39、`v2_diag_v2_check` 140/140、`v2_tt_login_check` 85/85、`v2_tt_frame_check` 140/0、`v2_x5_anim_check` 28/28、`v2_pos_restore_check` 12/12、`stats_check` 30/30、`v2_power_detail_check` 30/30、`v2_water_month_check` 41/41、`export_check draw` 落盘正常、`shots` 截图正常；视觉抽查 `_v2/shots/`（全部页/抽签预设/大屏/微信导出）。
- **上线**：`index.html` **730,113 B · sha256 `a7b2600174ec943dbd35dfdb606df20a9135c8c2d32ebffd5181362de8e6d7bf`**（APP_VER 仍 2.0.0）；`sync_tools.py index.html` 后 `oss_object.py check index.html` = MATCH；回滚 = 重传 `index_online_20261109_1835_preOptimV2.html`。
- **未做（按用户决定）**：作业完成率汇总导出、通知/作业「未处理人数」聚合、作业/点名变更留痕、Wake Lock。

## 2026-11-09 14:3x · 通知优化：文件/链接内容识别 + AI 动态分类（取消固定分类）

> 用户需求（2026-11-09 14:1x）：「① 对于文件类通知或通知中包含文件或链接的，要打开文件或链接识别具体内容再做整理；② 取消固定分类设置，由 ai 根据近期通知做灵活增添和删除分类，例如近期军训类通知较多便可在此期间自动添加军训分类」。
> 范围：briefdesk 数据管线 + web 通知模板/父页编辑弹层（**本次模板有改动，已重嵌并部署**）+ 小程序 nt 页小幅加固（需用户上传发布）；安卓无需改（cat 任意文本、筛选与分类无关）。

- **文件/链接内容识别（A）**：新增 [`content_extract.py`](C:/briefdesk/scripts/content_extract.py)（PDF 用 pypdf、docx/xlsx/pptx 标准库、旧 doc/xls/ppt 走 Office COM、zip 复用 archive_scan；公众号文章抓正文、腾讯文档/SPA 尽力取标题；SSRF 防护/12s 超时/2MB 截断/7d 缓存）；新增 [`attachment_digest.py`](C:/briefdesk/scripts/attachment_digest.py) 把 board-data 里 file/link/archive 的识别正文汇总到本机 `content-digests.json`；[`ai_brief.py`](C:/briefdesk/scripts/ai_brief.py) 把识别内容拼进 AI prompt 并计入缓存 hash；`detect_docs.py` 在 fetch_qq_files 后跑 digest、ai_brief 后跑分类。**识别正文只落本机，不进 board-data/云端**（隐私不扩散）。
- **AI 动态分类（B）**：新增 [`ai_categories.py`](C:/briefdesk/scripts/ai_categories.py)——按近 7 天全部通知的标题/摘要让 AI 归类；优先沿用上次分类/逐条归类（防抖动），近期同主题新增分类（如军训）、没有通知的分类自动删除；AI 失败保留旧缓存 + 旧规则兜底；缓存 hash 只看通知内容。`build_notice_board.py` 新增 `apply_categories()`；模板改为**数据驱动分类 chips**（`catClass`/`catList`/`renderCatChips`、`#catRow` 空容器 + 换行、未知分类稳定 hash 取色、选中分类消失自动回「全部」、编辑下拉动态）；`index.html` 父页管理员编辑弹层 cats 也改为 `AUTO_NOTICES` 去重（修掉会把「军训」覆盖成「教务」的隐患）；`ai_triage.py` 分类校验放开为 2~6 字任意名。
- **结果（14:29 重建/14:46 稳定）**：69 组通知 **9 个动态分类**：活动 17、志愿 15、教务 11、运动会 8、班级事务 7、**军训 6**、招聘 3、宣传 1、团务 1（军训类来自近期军训实施方案/动员大会/点名/急救点等，军训期结束无通知后会自动消失）；**24 组通知获得附件/链接识别正文（28 个来源：PDF/docx/xlsx/公众号/压缩包/收集表）**，如药膳活动从策划书 PDF 识别出「报名 11-07 12:00—18:00、11-07—11-14 线上打卡」并修正摘要/要点；军训场地划分 xls 识别出「主席台/跑道/各营人数」；管院运动会 6 个腾讯收集表链接也读到表名。云端 `public.notices` 同步 69/69，cat 分布与本地一致、无 `[聊天记录]` 占位。
- **独立复核（teammate `dyncat-reviewer`，task-2）**：FAIL 0，可保持上线。逐项独立验证：生产数据/云端 cat 逐组一致、识别正文 0 泄漏、模板嵌入 MATCH、动态分类测试 18/18、content_extract `--selftest` 49/0、幂等（ai_categories cached / ai_brief 缓存全命中 / digest 重算 diff=0）、web/mp 分类取色同口径一致；8 条 P3 观察项中已顺手修 3 条：收集表 `realUrl` 纳入识别、分类名源头剔除 `<>&\"'`（纵深防御，渲染本已 esc）、digest 新抓取 240s 总时间预算（防拖垮看门狗）；其余（AI 失败缓存不重试/父页旧 auto 通知筛选死代码/无 OCR/腾讯文档仅标题/mp 新逻辑无单测等）记录为已知限制或后续项。
- **上线**：`index.html` **693,068 B · sha256 `e1f0fccc0d78039744d9e7146c96d0528f7b2e2f6d1df21dc2e2f1aa7942b7f1`**（APP_VER 仍 2.0.0；模板改变，按 AGENTS §5 先备份线上对象 `tools/_backup/index_online_20261109-1431_preDynCat.html`（691,488B/`46184aeb…`）再 `sync_tools.py index.html`；`oss_object.py check index.html` = **MATCH**。DNS 暂停期以 OSS 对象字节为准，恢复解析后生效。桌面 demo 副本已刷新。
- **测试（本机实跑）**：新增 `tools/tests/v2_notice_dynamic_cat_check.py` **18/18 PASS**（动态 chips/筛选/增删分类/选中消失回落/编辑下拉/0 JS 错）；`v2_notice_data_check` 27 项 26 PASS（仅存量 D22 AI 要点≤6）；`v2_notice_live_check` **16/16**；`v2_admin_check` **39/39**（父页编辑弹层动态分类后仍过）；`v2_ui_check` **27/27**；`overflow_check 430` overflow=0；`_check_template_embed_match.py` = **YES**（index 内嵌模板 = 当前 demo 产物）；小程序 `unit.js` **257/0**、`node --check nt.js` 通过。`r3_notice_online_check`/`v2_notice_time_live_check` 因 DNS 暂停无法访问线上 URL（预期），以 OSS 字节校验替代；`r3_notice_online_check.py:213` 的 `==44` 断言已改为 `>=44`（数据自然增长到 69 组，与本次功能无关）。
- **已知限制**：① 无 OCR——图片型 PDF/纯图片公众号只能取标题或空；② 腾讯文档/forms/sheets 仅标题（JS 渲染，无登录态）；SPA 页面为空；③ 识别正文只在本机 `content-digests.json`（不进云端/前端展示，仅用于 AI 整理）；④ 分类可按 AI 判断保留单条主题分类（如「宣传」1 条），分类名/数量由 AI 按近期内容调整；⑤ 小程序需用户上传发布后才看到动态分类；安卓重装/升级后才刷新数据。
- **回滚**：线上 index 用 `tools/_backup/index_online_20261109-1431_preDynCat.html` 重传；代码/数据回滚见 `C:\briefdesk\data\_backup_nestedfix_20261109\ROLLBACK_NOTES_dyncat.md`（含各文件改回片段/新文件删除清单）；云端跑 `sync_notices_cloud.py` 恢复数据。

## 2026-11-09 14:0x · 通知优化：聊天记录里还有聊天记录（QQ 嵌套合并转发）→ 展开为真实通知

> 用户需求（2026-11-09 13:33）：「优化通知功能，对聊天记录中还存在聊天记录的情况做处理」。
> 现象：QQ 群转发的「聊天记录」里又套着「聊天记录」时，外层预览只有 `违规昵称#12138: [聊天记录]`，旧管线生成一张摘要「收到一条聊天记录，原文未提供具体通知内容」的空白卡（样本 rowid=7706038317343250643，13:24 入库）。
> 范围：briefdesk 采集/构建管线（未改 `index.html` 模板；网页通知数据走云端 `public.notices`，同步即生效，无需 OSS 部署）。

- **数据链路（主要改动）**：`briefdesk-plan/build_notice_board.py::load_qq_merged` 新增嵌套展开——解析 dbscan 输出 `40900 full` blob 里的内层 `<msg action="viewMultiMsg">` 卡片（标题/tSum/预览行），再按消息元素 marker（`u_B-xbHgFtPzMTjvfvZNVuqw` 单/对）切分内层消息，清洗头像 token/二进制噪声/本地 `NTOSFull::` 路径后，按顺序替换外层 `[聊天记录]` 占位；无 full 或无内层卡片时丢弃占位符（不再把 `[聊天记录]` 当通知原文），打印 `qq merged skipped` 便于排查。
- **AI 聚类缓存一致性**：`expand_merged` 增加 ai_merged 缓存 hash 过期检测——聊天记录展开后消息集合与旧缓存不一致时先不按旧索引硬拆（否则旧 index [0,1] 只取前两条，展开的 12 条丢 10 条），留给 `ai_merged.py` 重新聚类后再拆。
- **时间归一修复（展开后的富文本才暴露的存量 bug）**：`ai_brief.py` 的 `_MMDD_RE` 曾把 `9:00-12:00` 里的 `00-12` 误当 MM-DD（产出 `9:11-09:00` 这类脏时间）、`_abs_clock_text` 会在时间区间后半段/第二个时段重复插锚点日期；`notice_time.py` `_DASH_DATE_RE` 同类边界。另 `resolve_times` 对含「活动时间/签到时间/签退时段」的卡跳过 legacy 事件时间推断，交 `notice_time` 单一真源（否则样本卡 eventAt 被算成消息发送日 11-09 17:00，19:00 即被判过期）。
- **结果（2026-11-09 14:00 重建）**：该记录从 1 张空白卡 → **5 张真实通知**（均含原文长文与策划书 PDF 附件）：`g_qqm_7706038317343250643_c0` 校园主持人大赛报名通知 · `c1` 气排球垫球挑战11-22举行（eventAt 11-22 09:00）· `c2` 11-15校园拼贴诗活动 · `c3` 11-15三爱游园会报名 · `c4` 秋暮拾光校园随手拍征集。board 65 → **69 组**，其它 64 组 id 不变，时间字段仅 c1/c2 修正（11-09 17:00→11-22 09:00、11-13 12:00→11-15 09:00，清掉错误 expireAt/timeLabel）。云端 `public.notices` 同步 **69/69**，5 行均无 `[聊天记录]` 占位；桌面 `班级通知整合_近7天模拟上线_20261103.html` 已刷新。
- **验证**：`tools/tests/v2_notice_data_check.py` 27 项 26 PASS（唯一 FAIL 为 **D22 AI 要点 ≤6 条**，`g_qqm_7706037840253967598_c0`=8 条 / `g_ait_30fbc46e20`=7 条）；`v2_notice_time_check.py` 62/72 PASS。**关键证据：用改前 13:40 基线 board/demo 复跑两套测试，失败项与数量完全一致**（D22、A5.x 花名册、A6.x 献血、D5.1/D6.1、A9.1/A9.6）——均为存量断言/存量数据问题，非本次引入；日志 `C:\briefdesk\logs\_nestedfix_baseline_tests.log`、`_nestedfix_webtests.log`、`_nestedfix_webtests_final.log`。
- **独立复核（teammate `notice-reviewer`，只读，task-1）**：核心 PASS——生产 board 69 组、新增 id 恰为 c1..c4、0 处 `[聊天记录]`；其它 11 条合并记录语义不变；`_merged_msg_hash` 与 ai_merged 算法一致；端到端重建与线上 69 组逐组一致。**复核发现并已修**：① 深层嵌套回退预览未过滤占位符（F1，`_qq_merge_preview_messages`/`_qq_merge_expand_nested` 增加过滤，展开后仍无正文则整卡跳过）；② `QQ_EMOJI_RE` 会把「JPG/JPEG格式」「https://…」里的 `/英文` 当表情删掉（真实内容误删，已改专用 CJK 表情正则 `QQ_MERGE_EMOJI_RE`）；③ 文件名后文被过度截断（已去掉整行截断）。修后重跑 AI 聚类/摘要并复验：无重复日期、无占位、c4 原文「JPG/JPEG格式」完整；`ai_brief` 二次运行 changed=0（幂等）。
- **回滚**：代码/数据回滚点 `C:\briefdesk\data\_backup_nestedfix_20261109\`（含改前 `build_notice_board.py`、`qq-merged/board-data/ai-merged/ai-briefs/notice-board-live-demo` 与 `ROLLBACK_NOTES.md` 里 ai_brief.py / notice_time.py 两处小改动的原文件片段）。数据产物重建即可；云端跑 `sync_notices_cloud.py` 恢复。本次**无需 OSS / index.html 回滚**（模板未动，index.html 仍为 2026-11-08 22:27 / 691,488B / `46184aeb…`）。
- **已知限制**：① 嵌套展开依赖 QQ 消息表 40900 列里带有内层卡片（QQ 未落盘/裁剪时只能丢弃占位卡，不会伪造内容）；② 微信合并转发（appmsg type 19）的嵌套展开未做（`fetch_wechat_notices` 旧采集器当前 `LEGACY_KEYWORD_SOURCES=False` 未启用，无现状影响）；③ 新卡的时间语义仍受 `notice_time` 多报名窗口/签退时段解析限制（c0 eventAt=选手报名开始 11-18、c2 deadline=签退 11-15 23:00、c4 deadline=报名开始——为存量语义问题，复核列为后续观察项）；④ `ai_brief._MMDD_RE`/`notice_time._DASH_DATE_RE` 已加 `:`/`：` 边界（`10：10-12：00`、点分区间为残余边界，当前数据无命中）。

## 2026-11-08 22:3x · v2.0.0 夜间体验优化（OPTIM V1：全部页摘要 / 抽签状态与记忆 / 导出重试 / 数据备份）

> 依据 2026-11-08 两份 GitHub 参考分析报告，只落地「零契约改动、纯前端增量、零新请求」的四项；报告中需用户拍板的交互项未动。
> 基线/回滚：改前线上对象 `tools/_backup/index_online_20261108_2227_preOptimV1.html`（678,732 B / `e7b32ba4…`，即增量 26 diag v2 产物）。

- **全部页卡片摘要**：`renderAllCards` 后给 课表/作业/抽签/电费 卡各加一行 `.cardmeta`「下一件事」——课表 `正在上/下一节 · 课程 · 教室`（ttNowInfo）、作业 `未完成 N · 最近 MM-DD`、抽签 `已抽 N · 余 M`、电费 `剩 xx 度 · 低电`；数据全部本地已有，不新增请求、不动 UD v6。
- **抽签状态行 + 上次结果本机记忆**：出结果后 `#optDrawStat` 显示「池 N · 已抽 M · 剩余 K」；结果写入本机 `zq_draw_last_v1`（仅本机、不进 UD、不上云）；重置后显示「上次结果 N 个 · 时间 [恢复]」，可一键还原。
- **导出图片异常自动重试**：`exportCard` 包装，绘制抛错时自动重试一次再提示，降低微信 iOS 偶发中断/空白概率（不改版式/命名/水印）。
- **数据备份（全部页底部入口）**：「数据备份」弹层可导出本机 `zq_*` 数据为 JSON（**自动排除身份 token**），换设备/清缓存后可导入恢复（覆盖同键后刷新）；不改同步契约。
- **测试（全部本机实跑，均在合入后的真实文件上）**：`tools/tests/optim_v1_check.py`（新增，14/14）、`v2_ui_check` 27/27、`v2_drag_check` 56/56、`overflow_check 430` overflowCount=0、`reset_check` 109/109、`export_check draw` 落盘正常、`v2_sync_check` 35/35、`sync_check` 144/144、`perf_check` 123/123、`committee_check` 14/14、`v2_pos_restore_check` 12/12、`v2_x5_anim_check` 28/28、`v2_tt_frame_check` 140/0、`v2_admin_check` 39/39、`v2_diag_v2_check` 130/130、`v2_tt_login_check` 85/85、`stats_check` 30/30、`v2_power_detail_check` 30/30、`v2_water_month_check` 41/41、`shots` 截图正常。`selfcheck.py` 仍为身份门禁改造后的已知失效项（HANDOFF §5.2 已注明，非本次引入）。
- **上线**：`index.html` **691,488 B · sha256 `46184aebc9390b40467470c086ead0785e85d4a02987f023cef2db4c3864714d`**（APP_VER 仍 2.0.0）；`sync_tools.py index.html` 后 `oss_object.py check index.html` = **MATCH**；回滚 = 重传 `index_online_20261108_2227_preOptimV1.html`。
- **并发说明**：合入时另一路 agent 的「诊断 v2 + 课表登录（增量 26）」已上线（678,732 B），本优化以其产物为基线叠加，未改动 diag / tt 登录逻辑。

## 2026-11-09 18:3x · v2.0.0 增量 27：诊断 v2.1（AI 结论下挂异常项/简化折叠展开/10s 进展/设备信息最小化）+ 本机 agent 开机补跑与无人工自动修复

> 用户需求（2026-11-09）：「ai诊断项目应放置在对应异常项目的下面且简化显示，详情可预留展开按钮查看，同时各个问题进展要及时更新，你要预留通道来在电脑开机期间及时自动修复，尽量去除人工部分，即使关机状态也应该对期间用户端报上的错误留存并在开机后尝试修复，设备信息应只保留可能出现错误导致无法使用的信息」。
> 契约 `_diag_task/CONTRACT_V2_1.md`；基线=增量 26（诊断 v2 三端）。本条目记网页侧与云端/本机侧；小程序/安卓另记。

- **诊断页 UI 重构（网页 `#s-diag`）**：删除独立「AI 分析」大卡与独立「修复流程」卡；`diag_analysis` 按 `related.health_ids` 下挂到服务健康**异常行**、按 `related.checks` 下挂到设备检查行；无关联/旧数据进「其它诊断」（默认收起只显示条数）。折叠态一行 ≈34px（severity 点 + 标题≤22 字 + `⚙ 可自动修复` + 状态胶囊 待处理/修复中/已修复/修复失败 + `›`），点击整行展开 cause/建议/flow 时间线（flow 含 agent 写的 `run` 因故「进行中」步）/关联修复（action·状态·结果·创建-开始-结束时间，按 `related.repair_id` 关联 repair_tasks）；异常行无 AI：本机在线→「AI 分析排队中…」、离线→「本机离线，已留存待开机修复」；顶部摘要追加 `可自动修复 N · 已修复 M`。
- **进展**：AI/agent/repair 轮询 **15s→10s**（页面可见时；隐藏/切走停止；进入页面立即拉），状态胶囊与 flow 实时更新；保留服务健康 60s 刷新。
- **设备信息最小化**：`client_diag.device` 只上报 §B 白名单（platform/os/webview/screen{w,h,dpr}/memoryGB/storagePct/network/clockSkewMs）；`detail` 只允许 check/latency_ms/storage_pct/clock_skew_ms/err_count/code（`detail.check` 必带设备检查 id 逗号串供 agent 归因）；设备检查 9 项展示不再含 UA/语言/品牌/IndexedDB。
- **本机 agent v1.1.0**（`C:\briefdesk\scripts\diag_agent.py`，+569/−138，计划任务 `BriefdeskDiagAgent`）：① catch-up —— `state.last_round_at` 缺失/缺口 >180s（关机/睡眠回来）→ 忽略分析冷却强制分析、client_diag 上限 50、分析上限 20、修复上限 5，summary 带 `catchup/backlog_diag/backlog_repair`；② 自动修复扫描不依赖当轮 AI —— 每轮扫 `diag_analysis status=new+fixable+cloud/mixed+error/warn`，白名单直接执行，analysis 级 + **action 级去重**（同 action 30 分钟内 done 跳过、failed 6h 冷却）；③ 修复进展先写 —— 执行前 PATCH `repair_tasks.status='running'` + `diag_analysis.status='running'` + flow `本机开始执行 <action>`（st=run），执行后写 done/failed + 结果步 + 终态；④ `related.checks` 从 `client_diag.detail.check` 推导；⑤ 分析输入 device/detail 按 §B 白名单清洗；⑥ 计划任务 XML 新增 **LogonTrigger（登录后 30s）**，保留 TimeTrigger 1min/StartWhenAvailable/IgnoreNew/Hidden/InteractiveToken；⑦ 附加 `recover_stale_running`（running >10min 标 failed）与 `--force-catchup` 调试开关。
- **测试（本机实跑）**：网页 `v2_diag_v2_check.py`（v2.1 扩展）**140/140 PASS**；回归 `v2_tt_login_check` 85/85、`overflow_check 430`=0、`v2_ui_check` 27/27、`optim_v1_check` GREEN。本机 agent `test_diag_agent.py` **36/36 PASS**（新增 catchup/积压/冷却/去重/running 先写/related.checks/白名单/stale running 等 12 项）；真实 `--once`（合成 3 条关机积压 + 1 条修复候选）→ `catchup=true gap=600.2s, backlog_diag=3, repair ok=1, elapsed 8.6s`；生产任务自动执行 `refresh_timetable` 成功（running→done、analysis running→fixed、同轮 action 去重挡掉第二条）。Lead 独立验证「关机留存→开机补跑」：暂停 agent 75s 期间新上报保持 `status=new`，恢复后 `--force-catchup` 一轮 `backlog_diag=2`、两行均 analyzed、生成分析 `related.checks=['gateway']`。
- **上线（OSS 对象字节校验；DNS 暂停期）**：`index.html` **703,054 B · sha256 `6cef5da1…`（18:34 部署并校验 MATCH；18:35 并行会话在含本增量的文件上继续追加并部署 **730,113 B / a7b26001…**，已核验远端仍含本增量 v2.1 标记——线上现为 730,113 B）**（APP_VER 2.0.0）；部署前线上对象 693,068 B/e1f0fccc（含并行会话 OPTIM V1，已随本次一并上线，其 `optim_v1_check.py` GREEN），备份 `tools/_backup/index_online_20261109_1835_preDiagV21.html`；`oss_object.py check` = **MATCH**。回滚=重传备份。
- **安全**：仍只走既有 CloudBase 网关；设备/诊断上报字段严格白名单；无新增外部请求；未改身份门禁/同步契约（UD v6 不变）。

## 2026-11-08 22:2x · v2.0.0 增量 26：诊断 v2（设备诊断 + 本机 AI 分析 + 白名单自动修复 + 全班可见）+ 课表登录（个人教务课表）

> 用户需求（2026-11-08）：② 诊断页加入使用设备诊断，异常自动上传云端，由 AI 扫描服务给出可能原因；云端易修复问题在本机在线时尝试调用本机直接修复并在诊断页展示流程；设备端问题给修复建议；诊断设为人人可见。③ 体育课每人课表不同 → 给出登录入口，用自己账号获取自己的课表。
> ③ 实测云端无法访问校园内网教务 210.34.74.77 → 经用户确认采用 **A'：云收单（密码仅 PGP 密文）+ 本机代理（校园网 SSO/抓取）**。三端同做，本文件记网页侧；云契约 `_diag_task/CONTRACT.md`、迁移 `deploy/cloudbase/2026-11-08_diag_login.sql`。
> 基线/回滚：改前线上对象 `tools/_backup/index_online_20261108_2228_preDiagV2.html`（644,988 B / `603c4e5d…`）。

- **云端（已应用）**：新表 `client_diag`/`diag_analysis`/`repair_tasks`/`agent_keys`/`login_jobs` + RPC `tt_login_enqueue`/`tt_login_status`/`diag_agent_info`；`service_health` 读放宽 auth_ok；`client_diag.sid` 默认 `auth_sid()`（客户端不传 sid 也归属；真实云 201 实测）。密码仅 `pgp_pub_encrypt` 密文入 `login_jobs`，本机用后立即清空；诊断上报/展示全脱敏。
- **本机 agent**（`C:\briefdesk\scripts\diag_agent.py`，`BriefdeskDiagAgent` 每 1 分钟）：心跳+PGP、登录任务解密→纯 requests SSO（`web/jwxt/jwxt.py` 新增 `sso_login_http()`，`sync.py --check` exit 0）→回写课表；`client_diag`+`service_health`→本机 `cloud_ai` AI 分析→`diag_analysis`；白名单自动修复（recheck_health/…，每轮≤3、单动作≤120s、不重复），flow 回写。真实 `recheck_health` 修复成功并回写。
- **网页诊断页**：所有已登录成员可见（去 admin 门禁；门禁前 0 请求）；本机 agent 在线卡；设备诊断 10 项（环境/屏幕/内存/存储/IndexedDB/网络/网关延迟/时钟/课表快照/JS 错误）+ 重新检测/上报；异常自动+手动上报 client_diag（限频脱敏）；AI 分析+修复流程 15s 可见轮询；全局 onerror/unhandledrejection 自动上报；`sensMask()` 显示脱敏。
- **网页课表登录**：`#tLogin` 登录教务 → 弹层（学号默认、密码不入 storage）→ `rpc/tt_login_enqueue` → 1.5s 轮询 ≤120s → done 写 `D.d.ttLocal` 走 UD v6 同步 → 立即渲染；错误码提示；清除我的课表回退；**课表优先级改为 个人 ttLocal > 公共**（标签「个人课表」）。
- **测试**：`v2_diag_v2_check.py` **130/130**、`v2_tt_login_check.py` **85/85**；回归 `overflow_check 430`=0、`v2_ui_check` 27/27、`power_check` 155/155、`v2_tt_frame_check` **140/0**（静止帧对照改为只比课表主体，因 `.ttacts` 新增登录按钮；裁剪/泄漏/手感断言未改）。截图 `_shots_diag_v2/`、`_shots_tt_login/`（8 张）。
- **上线**：`index.html` **678,732 B · sha256 `e7b32ba4e7ba7e0be65c7a0ec34b1efe2b13d7ba9ac3ad66a04d64a23253b575`**（APP_VER 2.0.0）；`sync_tools.py index.html` 后 `oss_object.py check index.html` = **MATCH**（DNS 暂停期以 OSS 对象字节为准；DNS 恢复后生效）。
- **小程序/安卓**：同口径实现（mp 待用户上传发布；Android 新增诊断页+登录弹窗，`app-release.apk` 2,577,485 B / sha256 `59BEE20F…`）。

## 2026-11-07 23:05 · v2.0.0 增量 25：电费 13/16 号楼日更特异性统计（已上传 OSS；DNS 暂停期以 OSS 对象字节校验为准）

> 用户需求（2026-11-07）：「对 16 号楼和 13 号楼的电量统计做特异性功能优化，避免因统计频次的不同导致观感不佳和功能失效」。
> 范围：网页 + 小程序同口径（规格 `tools/tests/power_cadence_spec.md` v1）；只改电费统计口径与电费页展示，不改数据表/同步契约/其它工具。

- **真实数据依据（2026-11-07 22:01 只读探测，`tools/tests/_power_freq/`）**：`public.power_history` 47h（11-05 22:45→11-07 22:01）——13/16 号楼 4 间房各只有 **1 次**数值变化（均在 2026-11-06 09:46 同批，11-07 全天无变化）＝网关日更/批量更；对照 23A/23B 抽样 4 间 **45–46 次**、中位间隔 **1.0h**＝准实时。现状 bug 复算：13号楼324 剩 67.72 度、上次真实下降 11.25 度（≈1 天用量），页面「估算可用」却显示 **≥30 天**；24h 趋势平线、「近 24h 用电」显示「—」、hero「更新 22:01」其实是同步时间（数值自 11-06 09:46 未变）；13-308/16-305/16-306 同样 ≥30 天假估算。
- **修复（口径）**：新增慢频真实变化点统计 `POWER.slowStats`（30d 真实变化点分段：`dq>0.05 && dtH>=6h` 为有效用电段；中位阈值 `max(5, 4×中位数)` 剔异常大跌；1 段按预期 24h 折算并标「参考」，≥2 段按时间加权不标参考）；`isSlowRoom` 慢频判定 = 楼栋 ∈ 13/16 号楼（`PW_SLOW_BLD`）且当前 24h 真实变化 <6 次（`>=6` 自动降级实时口径，防网关提速）；取数慢频房选择即拉 **24h+7d+30d 三窗口**（实时房仍 2 窗口；切档补 30d，缓存 5 分钟不重复请求）；新增通用有效性守卫 `estimate`（24h/7d 真实用电均 ≤0.05 度 → `valid=false`「数据积累中」，不再用 0.05 度/天下限伪造 ≥30 天）。
- **修复（UI）**：趋势头固定「日更」短徽标（title=13/16 号楼网关日更）；hero 更新时间改用最后一个真实变化点（30 天无变化 →「近 30 天无变化」）；tile1「参考」仅慢频+有效+ref 时显示；tile2 该区间无下降时副标「该区间无更新」；tile4 上次充值改用 30d `lastRecharge`（切档不变）；慢频趋势改**阶梯线**（H/V）+ 真实变化点圆点 `.pw-cdot`（≤60）；所选区间无变化叠加提示 `#pwTrendNote`「近 24h/7 天/30 天无更新」（`pointer-events:none` 不挡点选）；平线时线段**垂直居中**且 y 轴只标中心一个刻度（避免三个相同数字像渲染异常）。使用说明 `#s-ug` 电费条补一句。
- **网页测试（全部本机实跑）**：新增 `tools/tests/v2_power_cadence_check.py` **84/84 PASS**；`v2_power_slow_check` **45/45**、`power_check` **155/155**（仅 C 组 16-305 fixture/断言与 Q 组 23B-422 期望按新口径更新并注释）、`v2_power_detail_check` **30/30**、`v2_power_sync_hardening_check` **29/29**、`v2_orient_power_check` **33/33**、`water_check` **169/169**、`sync_check` **144/144**、`v2_ui_check` **27/27**、overflow 430=0；日志 `tools/tests/_power_cadence_work/logs/`，截图 `tools/tests/_shots_power_cadence/`（8 张）。
- **独立验收（PASS）**：`tools/tests/_power_cadence_qa/REPORT.md` —— 独立行为/视觉 **454/454**、真实数据 live **83/83**（云端写拦截 6 个写请求全拦、无 PUT/PATCH/DELETE、token 不落盘）、静态契约 **27/27**、网页回归 **12/12**（含并集新增 `v2_water_month_check` 41/41、`v2_power_tip_follow_check` 18/18）、小程序 6/6 + 独立复算 **90/90**；证据 `…/_power_cadence_qa/{logs,shots}`（`after_S1_324_430.png`、`after_S2_305_430.png`、`live_after_real_13-324_430.png`）。
- **真实数据 live 验收（修复后）**：13号楼324 **≈6.0 天 / ≈11.3 度/天 / 参考 / 日更 / 更新 11-06 09:46 / 近 24h 无更新 / 平线居中 / 阶梯线 / ring 20.07**；13-308、16-305、16-306 均「数据积累中」（30d 无有效用电段）；23A-321 保持 ≥30 天 / ≈2.5 度/天 / 折线 / 无日更（现状不变）。
- **上线**：`index.html` **646,956 B · sha256 `02bcc76f33cf6e762a8297238a725d8c059c55de84972c0c2a1ece895aadfd73`**；部署 `python deploy/sync_tools.py index.html`；`python deploy/oss_object.py check index.html` = **MATCH**（remote = local 646,956 B / 同 sha），独立 `get` 取回字节存 `tools/_backup/_verify_online_02BCC76F.html` 与本地逐字节相等；冻结副本 `tools/tests/frozen/index_cadence_02BCC76F.html`。**furina.fun DNS 当前无 A 记录（备案暂停），线上 URL 不可访问 → 以 OSS 对象字节校验为准，DNS 恢复后生效**。
- **回滚**：`tools/_backup/index_online_20261107-2300_prePowerCadenceFinal.html`（646,736 B · `a5e3e151…` = 增量 23/24 线上对象，重传即回滚）；更早基线 `tools/_backup/index_online_20261107-2228_prePowerCadence.html`（621,560 B · `e4b16188…`）；部署前本地备份 `tools/_backup/index_local_20261107_2305_final.html`（646,956 B）。
- **小程序**：`utils/power.js`（新增 `slowStats/estimateSlow/isSlowRoom/noUpdateText/stepSegments/changeDots` 等，`estimate` 加 §1.4 守卫，`tilesOf`/`slowUpdate` 补慢频字段）+ `pages/power/*`（拉 30d、日更徽标、更新时间、tile2/4、阶梯线+变化点+无更新提示）；`v3_power_diag_tests.js` **53/0（较基线 45 增 8）**、`unit.js` **254/0**、`sync_contract_test.js` **31/0**、`tool_sort_unit.js` **21/0**、`staticcheck.py` exit 0、`code_quality_check.js` 通过；automator `power_preview.js` **31/0**，截图 `mp-class-tools-tests/_shots_power_sync/09_daily_badge.png`、`09b_no_update.png`。**小程序需用户在微信开发者工具上传发布后才生效**；`VERSION` 2.0.0 / UD v6 未动。
- **并发归属（如实）**：本快照 = **增量 23**（水量页月份选择 UI，22:45 部署 646,736 B/`a5e3e151…`）+ **增量 24**（电费趋势气泡，最终定稿为「固定右上角」：网页已单独部署 644,988 B/`603c4e5d…`；小程序源码已改待上传）+ **增量 25**（本次电费 13/16 日更特异性）；**本增量只对电费统计口径负责**；并行小程序气泡跟手与本次小程序改动共存，mp 门禁全绿。附注：QA 时并集新增的网页 `v2_power_tip_follow_check.py` 18/18 属增量 24 的第一版（跟手），同日 23:30 定稿改为「固定右上角」后该文件归档为 `archive/web_power_tip_work_20261107/…superseded`，新脚本 `v2_power_tip_fixed_check.py` 21/21；增量 24 已单独部署 644,988 B / `603c4e5d…`（覆盖增量 25 的 646,956 B / `02bcc76f…`，两增量内容均在当前线上文件中）。
- **已知限制**：13/16 网关实际更新时刻/是否仅工作日无法从 47h 完全确定（单段按预期 24h 折算并标「参考」，≥2 段后按真实间隔加权）；30d 窗口当前采样密度 960–1440 条 <2000 上限（未来加密需重评）；慢频房 24h 平线属如实展示；实时房仅「窗口真实用电=0」时显示「数据积累中」；DNS 暂停期线上校验走 OSS；CloudBase 环境 2026-12-10 到期（旧话题，非本次）。
- **文档**：`tools/tests/power_cadence_spec.md`、`HANDOFF.md §52`、`web/AGENTS.md §4b-17`、验收报告 `验收报告/v2.0.0_增量25_电费13-16日更特异性_网页+小程序.md`。

## 2026-11-07 23:30 · v2.0.0 增量 24：电费趋势信息气泡改为「固定右上角」（已上线 / 小程序待上传）

> 用户需求：「把气泡直接不放在图内，而是在趋势图的右上角上部（不要放在图内）固定显示」。
> 本增量替换同日 22:50 的第一版「气泡跟手」方案：气泡固定在趋势图右上角上部（区间按钮行右侧、绘图区外），
> 不随指针移动；竖线 + 圆点仍对准最近真实采样点，拖动只更新文字与游标位置。

- **网页**（`tools/index.html` POWER 模块）：新增 `.pw-trend-top` 包裹区间按钮 + 气泡（气泡移出 `#pwDetail`）；
  `.pw-detail-tip` 改静态布局（`margin-left:auto` 右对齐、`max-width:calc(100% - 186px)`、窄屏折行、`[hidden]` 隐藏）；
  删除 `POWER._ptr/placeTip/detailFromPoint/PW_TIP_GAP`；`detailSelect` 只写竖线/圆点 + 气泡文字；`renderTrend` 不再生成
  重复的「查看 …」行；`.pw-trend-scroll` 恢复 `touch-action:pan-y`；使用说明同步。
- **小程序**（`mp-class-tools`）：WXML 新增 `.pw-trend-top`（气泡移到绘图区外）、WXSS 静态布局、页面 `cursor` 简化为
  `{on,left,top,text}` 并删除 `_placeCursorTip/_cursorSeq/_cursorPos/_plotTop`；`utils/power.js` 移除 `cursorFollowLayout`。
- **测试**：网页新增 `tools/tests/v2_power_tip_fixed_check.py` **21/21 PASS**；回归 `v2_power_detail_check` **30/30**、
  `power_check` **155/155**、`v2_power_cadence_check` **84/84**、`v2_power_slow_check` **45/45**、`v2_orient_power_check` **33/33**、
  `delta_cursor_resize` ALL_OK、overflow 430 = 0。小程序新增 `tip_fixed_unit.js` **5/5**（已挂 `unit.js`）；回归 `v3_power_diag_tests` **53/53**、
  `unit.js` **247/247**、`sync_contract_test` **31/31**、`staticcheck`/`code_quality` 通过。
- **上线**：`index.html` **644,988 B · sha256 `603c4e5dd51a1cb3ede8d7f4b2c070c429013a533ae1281e0618b13f9948c69e`**（23:21 部署；
  OSS `get_object` 校验本地=线上逐字节 MATCH；回滚 `tools/_backup/index_online_20261107-2321_preTipFixed.html` 646,956 B · `02bcc76f…`）。
- **说明**：本版快照同时包含增量 25（13/16 日更统计）等并行会话成果；本增量只对「电费趋势气泡固定显示」负责。
- **文档**：`HANDOFF.md` §51、`tools/tests/_shots_power_tip/`、`验收报告/v2.0.0_增量24_电费气泡固定右上角_网页+小程序.md`。


## 2026-11-07 22:45 · v2.0.0 增量 23：水量页月份选择 UI 重做（自定义月步进 + 月网格弹层，已上线）

> 用户需求：「优化月份选择 ui，使页面更美观」。
> 背景：水量页「月份」原为未套站内样式的原生 `<input type="month">`，桌面/手机观感与整站不一致；本次改为站内自绘月份选择器（零依赖 / 原生 JS / 无构建链）。

- **控件**：`.wt-mctl` 三段式（‹ 上一个月 / 中间触发 / › 下一个月，高 42px）；中间「YYYY 年 MM 月」（年小·月大层级）+ 日历图标 + 展开箭头；未选关注宿舍时三键禁用；触发按钮 `aria-haspopup=dialog` / `aria-expanded`。
- **弹层**：点中间弹出月份面板（fixed 锚定控件下方，空间不足自动向上、左右自动收边；296px 宽）：‹ 上一年 / 年份 / › 下一年 + 「本月」+ 关闭 ×；12 个月 4×3 网格（42px），选中月浅青底+青边、当前月描边、**已有抄表记录的月份带小圆点**；选月即回写并关闭、焦点回触发按钮。
- **交互/无障碍**：Esc 关闭并回焦、点空白关闭、方向键在月份间移动焦点、`aria-current`；切页 / 窗口缩放 / 页面滚动自动收起弹层（fixed 元素防残留/错位）。
- **兼容**：真实值仍是隐藏 `#wtMonth`（type=month，1px / opacity 0 / tabindex -1）；保存、自动对比、`set_input` 测试路径全部沿用，`WATER.onMonthInput` 反向同步标签与预览。
- **响应式**：401–480px 与 960–1439px 窄列隐藏日历图标并收窄标签（触发按钮内容零溢出）；≤480px 两侧步进按钮 40px 可点区；≤400px 表单单列（控件全宽）；≥1440 恢复日历图标。
- **测试**：新增 `v2_water_month_check.py` **41/41 PASS**（静态 6 + 禁用 4 + 控件/弹层 18 + 桌面/手机弹层 4 + 多宽度零溢出 1 + 切页收起 1 + 错误汇总 3 + 其余）；回归 `water_check` **169/169**、`v2_water_layout_check` **29/29**、`v2_water_sync_check` **116/116**、`sync_check` **144/144** 全绿；部署后批次 `power_check` **155/155**、`v2_ui` **27/27**、overflow 430 = 0、export draw PNG 正常落盘。
- **上线**：`index.html` **646,736 B · sha256 `a5e3e15148c40ed627f6776cc553ce955f7d35b6d95cbd3fdd641f1b6456ac9f`**；因 furina.fun DNS 暂停无法按域名取回，改用 OSS `get_object` 校验「本地 = 冻结副本 = 线上」逐字节 MATCH；回滚 `tools/_backup/index_online_20261107-2243_preMonthUi.html`（621,560 B · `e4b16188…`，增量 22 版）；本地补丁前备份 `tools/_backup/index_local_20261107_2243_preMonthUi.html`（= 当前版本逐字节副本）。
- **已知限制**：月份只做「年 + 月」选择（年份 2000–2100 钳制，不提供年份直接输入）；弹层打开时页面滚动/缩放会自动收起（fixed 定位防错位）。
- **说明**：本版快照同时包含并行会话当日未部署的 WIP（电费趋势节奏/气泡等，非本增量内容）；本增量只对水量页月份选择负责，水量相关门禁全绿。
- **文档**：`tools/tests/_water_contract.md` §3.2/§3.2b、`HANDOFF.md` §50、验收报告 `验收报告/v2.0.0_增量验收报告6_水量月份选择UI_网页.md`。

## 2026-11-07 07:5x · v2.0.0 增量 22：DNS 暂停前改造（课表去域名化 + 诊断 18 行 + 网页暂停开关，已上线）

> 用户将暂停 furina.fun 全部解析、网页暂时停用；本次让小程序课表不再依赖站点域名，并完善诊断条目/暂停语义。

- **课表去域名化**：新增 CloudBase `public.site_assets`（`id='tt'`，RLS 有效班级 token 可读/管理员可写）；
  `web/jwxt/tt_cloud.py` 发布快照（sync.py 写盘后自动 publish，失败不影响退出码/OSS 上传）；
  小程序 `ttFetch` 改为 CloudBase `site_assets` 优先、失败回退旧 `ttUrl`；网页 `ttSyncPull` 同源 `tt.json` 优先、失败回退 CloudBase。
- **诊断 18 行 / 5 组**（web+小程序同口径）：新增 `dns_domain` 域名解析 / `tt_cloud` 课表云端数据 / `cloud_power_sync` 电费云同步 /
  `cloud_xgj_sync` 学工记云同步 / `cloud_health_probe` 云端巡检；云端巡检超 15 分钟 → 其它 cloud 行「注意 · 巡检未更新」。
  本机 `health_beat` 只写 local 10 行（不再探测域名/TLS，watchdog 单轮耗时降约 60%）。
- **网页暂停开关**：`public.site_config` 行 `web={paused,note,paused_at}`（仅管理员）；`C:\briefdesk\scripts\web_pause.py --on/--off/--status`；
  暂停时 `site_static/site_tls` 显示「注意 · 网页已按备案安排暂停」、`dns_domain` 按「已暂停/仍在解析」判定，避免误报。
- **验收**：云函数 invoke ok rows=8、service_health 18 行；小程序 unit 232/0、v3_power_diag 43/0、cache_unit 18/0、sync_contract 31/0、staticcheck 0；
  网页 `dns_pause_web_check` 19/19、sync 144、v2_ui 27、v2_admin 39、v2_sync 35、v2_scroll 40、x5 28、power 155、committee 14、
  notice_live 16、overflow 430/390=0、export OK、roster 199、pos_restore 12、notice_data 27、stats 30、swipe_perf PASS；QA 报告 `tools/tests/_dns_pause_qa/REPORT.md`。
- **上线**：`index.html` **621,560 B · sha256 `e4b16188d631f564138121e5441c2733e9c8ebc04166bf12837be93b0ac3092f`**（本地=线上 MATCH；APP_VER 仍 2.0.0）；
  回滚 `index_online_20261107-0750_preTTDiag.html（619,447 B / `e697df0e…`）`。**注意：新版小程序需用户在微信开发者工具上传发布后才生效**。
- **用户侧操作**：暂停 DNS 前跑 `web_pause.py --on`；恢复解析后 `--off`；**2026-12-10 前续费 CloudBase**。

## 2026-11-06 22:05 · v2.0.0 增量 21：电费趋势详细查看（去横滑）/返回键/登录闪烁/使用说明/性能安全（已上线）

> 用户 2026-11-06 21:41 批次中的网页部分（其余：云端迁移/小程序同口径/QA 见对应记录）。

- **电费趋势**：删除 7天/30天横向滚动与滚动代理、「横滑查看」提示；24h/7d/30d 全部采样按真实时间比例压缩铺满绘图区（不插值）。新增**曲线详细查看**：点击/左右拖动按 x 命中最近真实采样点，显示竖线+圆点+信息 `HH:MM / MM-DD HH:MM · 电量 xx.xx 度`，拖动实时 snap 更新、松手保留、点空白/标题取消；趋势区手势豁免（不切工具/不滚页）；空态/<2 点不显示；慢更新/充值徽标保留。
- **返回键**：tab/工具切换写 `history.pushState`，`popstate` 回上一 tab（不刷新不退出）；根层第一次返回 toast「再按一次返回退出」+ 1.6s 内双击退出；通知/名单弹层打开时返回先关弹层；内部渲染用 `_silent` 防脏 history。
- **无缓存登录闪烁**：`<body class="auth-pending">` 首帧隐藏 `.wrap`，身份完成才移除；未登录门禁从第一帧就在、已登录不出现 `id-locked` 闪烁。
- **使用说明**：`#s-ug` 新增「电费」小节（关注宿舍/低电阈值/趋势点看/不横滑/慢更新参考）、全部页拖动/工具栏拖动、通知附件（QQ/微信文件、压缩包识别、跨源合并）。
- **性能/安全**：首屏指标对比（DCL 49.2→58.8ms、load 50.8→61.1ms、可交互 51.3→61.6ms、首屏云请求 1→1；headless mock，波动内）；通知 iframe 已懒加载、非当前页请求 idle 延后。安全：postMessage 增加 `e.source` 校验；通知 iframe 加 `sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"`；确认无 eval/new Function/内联事件、外链 rel=noopener、esc 133 处、token 未进 URL/console。
- **测试**：新增 `v2_power_detail_check.py` 24/24、`v2_back_auth_perf_security_check.py` 27/27；全量 28 门禁全绿（含 power155、sync144、drag56、water/tt 等）。
- **上线**：`index.html` **619,447 B · sha256 `e697df0eedf29f71c28282a4d6aed841ef861f7d1a56b343e0ef8f7f5ff3eaf7`**（本地=线上 MATCH；模板未变、未重 embed；尾部补 tip 边界 clamp + resize 重排，`power_detail 30/30`）。
- **回滚**：`tools/_backup/index_online_20261106-2255_preDetailClamp.html`（617,440 B · `c7bbff40…`）；更早 `index_online_20261106-2215_preTask27.html`（608,498 B · `e01af2d6…`）。
- 残余：单文件内联脚本无法上严格 CSP；通知弹层 HTML 来自同源可信模板（如要更强隔离需另加白名单净化）。
## 2026-11-06 20:36 · v2.0.0 增量 20：全部页卡片拖动 v2（去抽动 / 跟手 / 工具栏命中 / 边缘自动滚动）+ 首页工具只存用户选择

> 用户反馈：「我发现网页的拖动效果依旧不足」；追问补充：「拖动卡片时有时会出现在几个位置间抽动的问题，有时想拖到的地方目标卡片反而不会自动移走」，
> 多选：拖到顶部工具栏很难命中/容易误判、拖动不够跟手/有卡顿掉帧。
> **2026-11-06 20:22 已上线**：线上 `index.html` **608,498 B · sha256 `e01af2d6b1ec8007faee0366542b451732bd42840fe7f48ad60bb7997ab10cea`**
> （本地 = 线上逐字节 MATCH；部署前线上 stable 600,414 B / `4db9953b…` 已备份）。
> 基线 = 增量 19 部署的 stable（600,414 B）；本改动只动拖动相关 CSS/JS + `renderTabs` homeTools 写回语义 + 拖动专项测试，**未改课表/水量/通知/电费/同步合并算法**。

- **根因（实测复现）**：
  1. 旧插入算法 = 「最近的卡片中心 + `y < cy` 决定前/后」：单列布局下同一行只有一张卡、网格行/列切换时最近中心与前后判定互相矛盾；每次重排后又立刻 `refreshCardRects()` 刷新几何 → 同一指针位置在 1~2 帧内算出不同插槽，**A→B→A 抽动**；且同一行内 x 方向完全不参与判定 → 指针已到目标卡上，**目标卡却不让位**。
  2. 每次 `move` 在 FLIP 循环里 `void c.offsetWidth` 强制重排 + 逐卡 `getBoundingClientRect()` → 掉帧。
  3. 工具栏命中区只有 tab 条 ±6px / 下方 ~50px，且拖动中**没有任何投放区高亮** → 难命中/误判；长列表也无法把卡片拖到屏幕外位置（无边缘自动滚动）。
  4. `.tabs` 是 sticky：页面滚到顶部前后它在「贴顶 0…47px」与「brand 下方 ~42…89px」之间换位，滚动后旧的工具栏几何缓存会让投放区停在旧坐标（自动滚到顶后再拖到栏上也会不认）。
- **实现**（替换「全部页卡片拖拽」整块 + 拖动 CSS；`renderTabs`/`dropToTabs` 语义调整）：
  - **稳定插入**：改为「指针所在网格行 + 行内 x 中线」算插入位置（`calcCardsDrop`），不再用最近中心；候选位置需**连续 2 帧一致**才落位（迟滞，消除抽动）；指针所在行只有源卡时保持原位；重排后**一次性批量**读新布局，FLIP 用 WAAPI `element.animate` 批量位移（无逐卡强制重排；不支持时回退 `transform` 过渡）。
  - **跟手**：`pointermove/touchmove` 只记录坐标并立即写 ghost `translate3d`（越过 6px 阈值同步起拖，不依赖 rAF 时序）；rAF 只负责落点/自动滚动，每帧单次写 transform；幽灵 `will-change` 只在拖动瞬间内联存在（X5 层切换闪烁源不常驻）。
  - **工具栏投放**：命中区 = sticky `.tabs` 整条 + 下方 26px（离开迟滞 72px）；命中时 `.tabs.drag-over` 高亮 + 目标 tab `.drophl` + 插入线 + tabs 让位；移出自动清除。滚动时刷新 `.tabs` 实时位置（`refreshBarRect`），自动滚到顶后仍能正确命中。
  - **边缘自动滚动**：指针进入视口上/下 90/110px 边缘按距离 3–16px/帧滚动；几何缓存按滚动量平移，松手即停。
  - **收尾反馈**：ghost 收拢到源卡位置（150ms）后移除；`navigator.vibrate` 轻震（有则用）；拖动后抑制一次卡片点击 360ms；`reduced-motion` 下时长 0。
  - **homeTools 只存用户选择**：`renderTabs` 仍按屏幕比例补齐工具栏到 3/4 格（视觉不变），但**补齐项不再写回 homeTools**；`dropToTabs` 只在用户拖入时写 ≤4 个真实选择（竖屏满 4 个时替换当前可见槽位）。目的：小程序端「首页工具主动勾选」只勾 1–3 个时，打开一次网页不会被补回 4 个（跨端勾选不被污染）。
- **测试**：`tools/tests/v2_drag_check.py` **36 → 56 项**（新增 K 命中区扩大/高亮/移出清除；L 12 采样点源卡索引无 A→B→A + 目标卡让位；M 边缘自动滚动/离开停止/松手停止；N 远端 homeTools=2 时本机仍 2 个且工具栏补齐显示；O 收尾无幽灵/残留内联位移；P 1280 多列网格拖动；Q 自动滚到顶、sticky 工具栏换位后仍能命中）→ **56/56 PASS**（本地 608,498 B 与线上字节复跑均 56/56）。
- **回归（本机实跑）**：`sync_check` 144/144、`water_check` 169/169、`power_check` 155/155、`v2_water_layout_check` 29/29、`v2_water_sync_check` 116/116、`v2_tt_frame_check` 140/140、`v2_ui_check` 27/27、`v2_orient_power_check` 33/33、`overflow_check` 430=0（per 全 0）、`v2_x5_anim_check` 28/28（S8 按「will-change 仅拖动幽灵临时使用」口径）、`v2_pos_restore_check` 12/12、`v2_power_slow_check` 25/25、`v2_power_sync_hardening_check` 29/29、`export_check draw` 正常落盘、`v2_swipe_perf` PASS。
- **备份 / 回滚**：部署前线上（= 增量 19 stable）`tools/_backup/index_online_20261106_2020_preDragV2Deploy.html`（600,414 B / `4db9953b…`），重传即回滚；本地打补丁前另存 `tools/_backup/index_local_20261106_2010_preDragV2.html`（同字节）。
- **已知限制**：拖动仍只从卡片右上三条横线 handle 起手（本轮未改起手方式，未做「长按卡片任意位置拖」）；特殊卡片（电费/反馈/使用说明）不能进工具栏（维持原语义）；仅桌面/手机模拟器自动化验证，未做微信真机手测（建议上线后手机上拖一次确认手感）；小程序端勾选顺序与网页端仍按 homeTools 原样应用（不按两端各自本机顺序回写，避免来回改写）。

## 2026-11-06 20:05 · v2.0.0 增量 19：网页课表横滑裁剪（滑动时内容不再超出白卡框 / 不盖右侧栏）

> 用户反馈：「对于网页课表功能，请优化滑动时会超出课表框的情况」。
> **2026-11-06 20:08 已上线**：线上 `index.html` **600,414 B · sha256 `4db9953b2572ae8149d59c90508dd9dfb02efa1577162aabd6103ab05408feab`**
> （与本地逐字节 MATCH；部署前线上 stable 600,198 B / `e48bd963…` 已备份）。基线 = 增量 18 部署的 stable；并行会话已在 `HANDOFF.md` §46.4 记录本 WIP。

- **根因**：全局横滑引擎在课表页把 `transform:translate3d(±W px)` 直接写在 `.ttmain` 上（`curEl("view")` / `nextEl("week")`），而 `.ttcard`/`.ttbody`/`.ttmain` 都没有 `overflow` 裁剪 → 拖动跟手、松手回弹、换周飞出/飞入期间，7 天周表（或日视图列表）会画到白色圆角卡片之外：手机左右页边 14px 条带外露（390 档拖动帧框外差异 5.2k–5.7k px），桌面 ≥1024 直接盖住右侧 `.ttside` 的「下一节 / 全部课程」（1280 档侧栏差异 9.6k px）；且拖动时 transformed 内容把 `document.scrollWidth` 撑宽（360/390/430 实测 471/501/541px > 视口）。小程序 `pages/tt/tt.wxss` 早有 `.ttcard{overflow:hidden}` 并注明「左右滑动飞出/飞入时裁剪在卡片内」，网页端缺这一步。
- **修复**（`tools/index.html`，4 处 / 7 行，纯 CSS + DOM 包裹，**JS 零改动**）：
  - `<div class="ttbody">` 内加一层 `<div class="ttframe">`（L1219/L1226），现有 `.ttmain` 原样留在里面 —— `transform` 仍落在 `.ttmain`，`curEl/nextEl/cleanAllSections` 等选择器全部不用改；
  - 手机/平板（L386-387）：`.ttframe{order:2;min-width:0;overflow:hidden}`，flex 列 order 从 `.ttmain` 移到 `.ttframe`（下一节 → 周表 → 全部课程 顺序不变）；
  - 桌面 ≥1024（L410）：`.ttframe{display:block;order:0;grid-column:1;min-width:0}` —— 裁剪区 = 主列，止于 260px 右侧栏之前，动画不会盖到 `.ttside`。
  - 取舍：`.ttcard{overflow:hidden}` 只在卡片边界裁剪，桌面仍会盖住 `.ttside`，故采用 `.ttframe`；两者都不改滑动阈值/跟手算法/换周逻辑。
- **专项测试**（新增 `tools/tests/v2_tt_frame_check.py`：headless Edge + CDP `Input.dispatchTouchEvent` 合成真实触摸 + 假身份 + 合成 7 天含周六/周日 14 门课 + 拦截 `tcloudbasegateway`/`tt.json` + 固定时间；PIL 逐像素对比）：
  - 修复前（`--src` 基线副本，`--tag pre`）：**107 PASS / 29 FAIL** —— 拖动按住帧框外泄漏 4.9k–7.4k px、1280 侧栏被盖 9.6k px、换周飞出/飞入帧泄漏 4.7k–34k px、日视图拖动泄漏 3.6k px、拖动中页宽被撑宽；
  - 修复后：**140 PASS / 0 FAIL** —— 360/390/430/1280 的拖动按住 / 回弹 / 飞出 / 飞入各帧「卡片框外差异 = 0」（1280 侧栏差异 = 0），卡内动画变化 12k–345k px（证明动画仍在动），回落后整帧 diff=0、静止帧与修复前逐像素 diff=0（无裁剪损失）；7 天 14 课程格 / 星期列完整、`.tscroll` 横滚到末尾不漏、横滑切周、课程详情弹层、上一周/下一周按钮、周·日视图切换均正常；四档静止与拖动中均无页面横向溢出、0 JS 错误、0 console.error。
- **回归**（全部本机实跑）：`overflow_check.py 430` overflowCount=0（per 全 0）；`v2_swipe_perf.py --only fixed` PASS（reactionRate=1、syncErrP50=0px、applyLatencyP50=0ms、slow4px firstFollowDx=-4、followRate=1.00、通知页纵滚/残影指标不变）；`v2_ui_check.py` 27/27；`v2_x5_anim_check.py` 28/28。
- **截图**：`tools/tests/_shots_tt_frame/`（`pre_390_drag_right.png` / `pre_1280_drag_right.png` = 修复前泄漏帧；`post_390_drag_right.png` / `post_1280_drag_right.png` = 修复后；另有 snap/fly/settled/static_day 各帧与 `pre_summary.json`、`post_summary.json`）。
- **备份 / 回滚**：改前基线 `tools/_backup/index_local_20261106_1958_preTTFrame.html`（600,198 B · `e48bd963…`，= 增量 18 stable 逐字节副本）；修复后本地 **600,414 B · sha256 `4db9953b2572ae8149d59c90508dd9dfb02efa1577162aabd6103ab05408feab`**。回滚 = 把备份复制回 `tools/index.html`（已部署则重传上一版本）；无数据层改动。
- **上线（Lead，20:08）**：部署命令 `cd deploy && python sync_tools.py index.html`（只传 index.html）；部署后线上 sha256 与本地逐字节 MATCH。部署前线上 stable 备份 `tools/_backup/index_online_20261106_2010_preTTFrameDeploy.html`（600,198 B / `e48bd963…`，重传即回滚）。Lead 独立复验（独立实现的像素带脚本，非本专项测试）：修复前复现框外泄漏（390 左/右 4,893/5,317 px、1280 左 7,557 px、侧栏被压 11,876 px）→ 修复后框外差异 **0/0**（含线上字节）、静止帧课表网格区与修复前**逐像素 diff=0**；线上/本地字节复跑 `v2_tt_frame_check.py` **140 PASS / 0 FAIL**、`overflow_check.py 430`=0、`v2_swipe_perf.py --only fixed` PASS、`v2_ui_check.py` 27/27、`v2_x5_anim_check.py` 28/28。
- **已知限制**：微信/X5 真机未做（本改动不动 `transform`/`will-change`，x5_anim 门禁 28/28 通过）；横竖屏旋转走既有 `resize` 路径（未新增监听）；`.ttframe` 裁剪与 `.tscroll` 横向滚动互不影响（已断言周末列可滚动到完整可见）。

## 2026-11-06 19:52 · v2.0.0 增量 18：水量页云同步「所有内容」显性化/加固 + 桌面三栏比例优化（已上线）

> 用户需求：「对水费统计的用户所有内容加入云同步，包括抄表记录等，优化网页端水费工具比例」。
> 说明：抄表记录 / 每间人数 / 关注宿舍的云同步在增量 16 已随 UD v6 `water` section 落地；本轮先做独立审计
> （`tools/tests/_water_work/sync_audit.md`，20 项「用户内容→同步字段→证据」覆盖矩阵）确认**无漏同步项**，
> 再完成「显性化 + 加固 + 桌面比例」，**未改 v6 契约 / 合并算法**（water 仍整段 LWW）。

- **云同步显性化**：水量页 hero 底部新增 `#wtSync`（复用 `.pw-sync`）：`已同步` / `未同步 · 点重试`；未选关注宿舍时隐藏。点击重试 = `WATER.requestSync()`（有基线立即 `UD.push(true,["water"])`；无基线先 `UD.pull(true)` 建基线再补推）。
- **云同步加固**：
  - 新增 `WATER.normWater()`：远端 `water.rooms` 逐间归一（`p` 夹 4/6、`recs` 走 `normRecs` 排序/月校验/≤120 条、坏房间丢弃），`WATER.applyRemote` 与 `UD.sections()` 推流共用 → 远端不可信数据不再原样进本机 raw / 回写云端；
  - `WATER.enter()` 本机缓存还没有 water（旧缓存/首装）时强制补拉一次；其余走 `UD.pull()` 60s TTL；
  - `save/del/setPersons` 后 `UD.pendWrite(["water"])`（无基线/推送失败时下次 pull 保本机赢，同电费加固套路）；
  - `WATER.syncState()` pending = `pendRead || dirty`（去掉 `_push`，push 成功不闪回「未同步」）；新增 `udSyncUi()` 统一刷新电费/水量同步状态。
- **桌面比例（≥1280 三栏 / 960–1279 两栏；<960 零改动）**：
  - ≥1280：`repeat(3,minmax(0,1fr))` + `areas:"hero form hist"/"hero rules hist"` 三栏等高（hero 自然高不拉伸、中栏 form+规则合计=hero、无结构性空洞）；规则卡压成**横向 chips 条**（`#wtRuleBody` flex，文案零改动）；dash 宽度 `≥1280 max-width:1320`（生效 1188）、`≥1600 max-width:1520`（生效 1492）；`#s-water .wt-dash>.card{margin-bottom:0}`；
  - 960–1279：两栏 `"hero hist"/"form rules"`，规则卡保持纵向（不 chips）；
  - 抄表历史 `contain:size` + `.wt-list` 内部滚动 → 12 条/更多记录页高不变；空态 `#wtLastNum.no-data` 灰小占位（不再 62px 大黑横线）。
- **实测高度**：1280×800 `scrollH=800`（旧 1115，−315；≤810 门禁）；960/1024×800 `scrollH=955`（旧 1126，−171）；1440/1600 不滚动、用满 1292/1492；12 条/空态 @1280×800 仍 800；430 手机单列不变、无横向溢出。
- **测试**：`water_check` **169/169 PASS**（原 153 + 静态 3 + H 组 13：`#wtSync` 隐藏/已同步/未同步/点重试补推、推送 blob 含新记录、远端归一 p=9→4/130→120/非法月/坏房间丢弃）；新增 `v2_water_layout_check.py` **29/29**（三栏等高/中栏合计=hero/1280×800 无滚动/dash 1188/chips/1440·1600 宽 1292·1492/12 条内部滚动/空态/430 单列）；独立 `v2_water_sync_check.py` **116/116**（稳定版冻结副本复跑）；`sync_check` **144/144**（适配 `UD.sections().water` 归一静态断言）；`power_check` **155/155**；overflow 430=0；export draw 正常落盘（213,888 B）；v2 批次 `drag 36/36`、`ui 27/27`、`power_slow 25/25`、`power_sync_hardening 29/29`、`pos_restore 12/12`、`roster 199/199`、`reset 109/109`；`v2_orient` 并发首跑 B0 启动 timeout（环境 flake）→ 单跑复测 **33/33**。
- **上线**：`index.html` **600,198 B · sha256 `e48bd9635638a8da607feeeb9c7f9044b22d92a5b4cf6f9490846cced5630aba`**（部署后本地=线上逐字节 MATCH）；回滚 `tools/_backup/index_online_20261106-1950_preWaterSyncLayout.html`（594,410 B · `f7731e77…`），本地补丁前备份 `tools/_backup/index_local_20261106_1948_postWaterSyncLayout.html`（= 当前 stable）。
- **已知限制**：`water` 为**整段 LWW**（双端并发修改不同宿舍时后写整段覆盖；要做按房间/按记录合并需 web+小程序+契约 fixtures 同改，本轮不做，建议先问用户）；水费折算（÷0.58）为多源推断，以学校账单为准；小程序 water 页源码已就绪、待用户上传发布（旧版小程序按「未拥有 section 原样保留」不覆盖云端 water）。
- **文档**：`tools/tests/_water_contract.md` §7（增量 18 补丁）、`HANDOFF.md` §46、独立审计 `_water_work/sync_audit.md`、布局审计 `_water_work/layout_audit.md`、验收报告 `验收报告/v2.0.0_增量验收报告5_水量云同步与桌面比例_网页.md`。

## 2026-11-06 19:25 · v2.0.0 增量 17：计费规则归位（电费规则进「电量统计」，水量页只留水费规则）

> 用户反馈：「电费的计费规则应放入电量统计里」。

- **电费页**：计费规则从趋势卡下方独立行改为**指标 tiles 网格内满宽规则条**（`#pwTiles #pwBill`）：电价 0.58 元/度、区间电费 ≈ ¥X.XX、免费 5 度电/人/月（4 人间=20 度）、水费 3.03 元/吨从电费账户扣 · 1 吨≈5.2 度、已忽略扣减摘要；与「估算可用/区间用电/低电阈值/上次充值」同属电量统计区。
- **水量页**：规则卡只留水费规则（3.03 元/吨、每人 2 吨水/月免费定额、超出定额×3.03、折合扣电÷0.58、计费说明），不再重复电费单价/电免费定额；人数下拉改为「4/6 人间（每月免费 8/12 吨水）」。
- **桌面高度**：`.pw-side` 两行 + tile 80px + 规则条紧凑 → 1280×800 scrollH=800（≤810）、1280×1000 仪表盘贴底。
- **测试**：`water_check` 153/153（D01–D05 水费口径 + E11 断言 #pwBill 在 #pwTiles 内）；`power_check` 155/155（1280×800 scrollH=800）；`v2_power_slow_check` 25/25、`v2_orient_power_check` 33/33、`v2_ui_check` 27/27、`v2_drag_check` 36/36、overflow 430=0；线上字节复跑 water/power 全绿。
- **上线**：`index.html` **594,410 B · sha256 `f7731e77891dacb60b557206f38bd1fbce9ecd0058d6b4be03f82e86fd03c167`**（本地=线上 MATCH）；回滚 `tools/_backup/index_local_20261106_1918_preRulesMove.html`（594,167 B · `e41866c0…`）。

## 2026-11-06 19:15 · v2.0.0 增量 16：宿舍水量统计 + 水电计费规则 + 电费异常扣减忽略（已上线）

> 用户需求：「为班级工具站添加水量统计功能；目前水费无自动计费、为每月学生手动抄表模式，设计为可手动记录并自动与上次记录对比；由于水费自动从电费扣除，电费计算中如短时间内下跌幅度过大要予以忽略；搜索并为水量和电量统计添加计费规则」。
> 计费依据：`web/_water_rules/research.md` + `rules.json`（14 条来源；校方原文已核实）。

- **计费规则（页面 `var RULES` 唯一来源）**：电 **0.58 元/度**、水 **3.03 元/吨**（后勤基建处 2025-09-05《关于学生公寓水电费计取的情况说明》原文，明确「不存在额外加价」）；免费定额 **每人每月 2 吨水 + 5 度电**（2021《学生公寓（宿舍）管理规定》；当月有效、每学年 10 个月、寒暑假无；4 人间=8 吨/20 度，6 人间=12/30）；无阶梯、无额外加价。公式：`水费 = max(0, 用量 − 2×人数) × 3.03`、`折合扣电 = 水费 ÷ 0.58`（1 吨≈5.2241 度）、`区间电费 = 区间用电 × 0.58`。页面注明「以学校最新通知为准」（官方 5 度与第三方旧文 4 度冲突已标注）。
- **水量页（新增工具）**：`TOOLS` 加「水量」+ `<section id="s-water">` + `.wt-*` CSS + `WATER` 模块；与电费共用「关注宿舍」（17 间，可切换）、宿舍人数 4/6；选月份 + 水表读数保存 → 自动与上一条对比（用量/水费/折合扣电/超定额）、同月覆盖、读数低于上次（或高于下条）拒绝、删除后自动重算、历史按月倒序、计费规则卡；全部页卡片可拖动进工具栏；无网络请求（本机 + UD 同步），只显示关注的一间宿舍，不含姓名/学号。
- **同步（UD v6 第 11 个 section）**：`water={rooms:{<roomverify>:{p:4|6,recs:[{m:"YYYY-MM",r:吨,ts}]}}}`；顶层 blob **14 键** `v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,water,homeToolsAt`；`at.water` LWW、值内不镜像 at；旧数据默认 `{rooms:{}}`；小程序未拥有端原样保留（不会丢云端 water）。
- **电费计费 + 异常扣减**：`POWER.deductOf()` 识别短时大幅下跌（`dq > max(5, 4×窗口正常单段中位数)`；与当月/上月水量记录折合扣电误差 ≤max(2 度,10%) 时标为「水费扣除」，即使未达候选阈值也忽略）；异常段不计入区间用电/电费/估算速率；趋势卡头 `#pwDeduct`（水费扣除 N 次 / 已忽略 N 次扣减）、图例「扣减 X 度」、区间用电 tile 副标「≈ ¥X.XX 电费」、`#pwBill` 电价/水费/1 吨≈5.2 度/免费定额/忽略摘要；充值（上升）逻辑不变。桌面 1280×800 仍无纵向滚动（`.pw-side` 三行 + tiles 104 + bill 紧凑）。
- **测试**：新增 `water_check.py` **153/153 PASS**（静态 19 / A 12 / B 14 / C 30 / D 7 / E 21 / F 27 / W 5 / G 3；连跑 3 次稳定；含 30 度异常不计用电、水量匹配「水费扣除」、14 键 blob、换设备/两账号隔离/旧数据）；`sync_check` 适配后 **144/144**（新增 water C5 9 项 + K 旧数据 4 项）；`power_check` **155/155**（13→14 键、fixture 补 water、新扣减算法 rate 6.1→5.8、1280×800 scrollH=806≤810）、`v2_orient_power_check` 33/33、`v2_power_sync_hardening_check` 29/29、`v2_power_slow_check` 25/25、`v2_drag_check` 36/36（全部页卡片 11/11）、`v2_ui_check` 27/27、`v2_pos_restore_check` 12/12、`v2_swipe_perf` PASS、`roster_check` 199/199、`reset_check` 109/109、`overflow_check 430`=0、`export_check draw` 正常落盘；独立验收 `tests/_water_verify/VERIFY_REPORT.md`。
- **小程序（源码完成，待用户上传发布）**：`pages/water/*` + `utils/water.js` + cloud/privacy/store 接入 water section；`unit.js` **212/212**（新增 12 项）、`sync_contract_test.js` **31/31**（14 键双向合并）、`staticcheck.py` 0 missing、`cli auto-preview` 编译通过；版本仍 2.0.0、AI off。
- **上线**：`index.html` **594167 B · sha256 `e41866c03bed6000e35e53ae731de7dd5cd9cc5b20cffcc7d2cfe9e670296e89`**（本地=线上逐字节 MATCH；部署前线上 565,417 B · `8520e547…`）。
- **回滚**：`tools/_backup/index_online_20261106-1848_prePowerSync.html`（565,417 B · `8520e547…`）复制回 `tools/index.html` 后 `python deploy/sync_tools.py index.html`；本地补丁前备份 `tools/_backup/index_local_20261106_1854_preWater.html`。无数据库迁移（water 走既有 userdata blob）。
- **已知限制**：水费折算公式（÷0.58）为「同一账户余额按元」+ 校方 2017 学生媒体口径的多源推断（校方未给算例），页面按估算展示、以学校账单为准；免费电额度仅规则展示、未从区间电费扣除（充值口径）；异常扣减阈值固定 `max(5 度, 4×中位数)`（1h 采样下正常用电不会误判）。

## 2026-11-06 18:50 · v2.0.0 增量 15：电费关注宿舍同步加固（无基线/竞态/离开 flush，已上线）

> 用户反馈（18:21）：「网页端电费关注宿舍依旧做不到记录和同步，每次重新打开都要重新选择」；用户确认自动登录（本地存储正常）、多环境复现、跨设备也看不到。

- **根因（竞态）**：boot `UD.pull()` 未完成时选宿舍 → 无基线 → `UD.touch()` 直接 return 不推送 → pull 返回后 `wasDirty=[]`、`localView` 不标脏、`power.at=0` → 云端旧 `sel`/空值在 merge 中赢 → 覆盖用户刚选的宿舍；于是本地显示丢失、跨设备也一直旧值。
- **修复**：
  1. `POWER.pick()` 与 `POWER.enter()` 兜底恢复后 `UD.pendWrite(["power"])`；
  2. `UD.pull()`：`pendRead()` 时取 pend keys 作为 forceKeys，`localView` 强制本机这些 section `at=now`（即使无基线），保证本机新选择在 merge 中赢，随后 `push(true,forceKeys)`；
  3. `UD.touch()` 无基线不再 return：真实用户手势后 `pendWrite(改动 keys)` + `pull(true)`（用 capture 手势标记规避首屏默认值噪声）；
  4. 进入电费页无 sel → `UD.pull(true)` 后重试恢复；页面首次进电费页 `requestPowerSync(true)` 确认云端；
  5. `pagehide/beforeunload/visibilitychange(hidden)` → `UD.flush()` 立即推送 pend/dirty（选完马上关页面也不丢）；
  6. 电费 hero 脚注新增极简同步状态：「已同步 / 未同步 · 点重试」（按 power sel/low 判定，at 不参与；点击重试）。
  7. 无基线且无 forceKeys 时拒绝盲推，避免默认值覆盖云端。
- **测试**：新增 `v2_power_sync_hardening_check.py` **29/29**（无基线推送、boot pull 500、立即 pagehide、同步失败点重试、**boot GET 延迟 2.5s 竞态**、无基线+pagehide、0 JS 报错）；全量 23 门禁全绿（power155、sync124、drag36、orient33 等）。
- **上线**：`index.html` **565,417 B · sha256 `8520e547741bae2006f98faf25b2205a264e161fd29c257a7c02280435b4e8de`**（本地=线上 MATCH；模板未变、未重新 embed）。
- **回滚**：`tools/_backup/index_online_20261106-1848_prePowerSync.html`（557,076 B · `6d7b0aa8…`）。
- **真机/云端验证**：用测试账号在部署后复现「登录后立即进电费页→选宿舍→立即 pagehide→重开/换全新 profile」：云端 userdata.power 更新为所选房间、新 profile 登录自动恢复；同步徽标显示「已同步」。
## 2026-11-06 13:30 · v2.0.0 增量 14：卡片拖动跟手优化（ghost 跟手 + 几何缓存，已上线）

> 用户反馈（2026-11-06 13:14）：「优化拖动工具卡片时的跟手效果」。

- **问题**：原实现拖动时只给源卡片加 `.drag-src`，没有跟随指针的视觉元素；每次 move 都 `getBoundingClientRect()` 遍历全部卡片并立即重排，移动端掉帧/感觉延迟。
- **修复**：
  1) 越过 6px 阈值后克隆源卡片为 **ghost**（`position:fixed; pointer-events:none; z-index:90`，偏移取按下点相对卡片左上角），每次 pointermove/touchmove **同步写 `translate3d`**（无 rAF、无 transition），手指/鼠标到哪卡片到哪；源卡片保持原位 opacity .35 作占位。
  2) 开始拖动时一次性缓存 tabs/bar/卡片矩形；move 只读缓存 + 写 ghost transform；插入点/重排按 8px 位移节流，tabs 让位仅在 idx 变化时更新，卡片仅在插入位置变化时重排+FLIP，并刷新缓存。
  3) 松手前按最终指针位置补算一次落点（防节流漏算）；结束/取消移除 ghost、恢复源卡、清理状态；resize cancel、reduced-motion 兼容；ghost 的 `will-change` 仅拖动瞬间存在。
- **测试**：`v2_drag_check.py` 22→**36 项**（鼠标/触摸各 6 采样点 ghost transform 与指针误差 **0.0px**、fixed/pe:none/z90、无 handle、源卡 .35、拖动不滚动页面、GBCR 计数 ≤120、松手 ghost 移除/源卡恢复/落点正确、既有用例不回归）；`v2_x5_anim_check.py` S8 调整为「will-change 仅拖动幽灵临时使用」，28/28。
- **回归**：22 条门禁全绿（roster199/reset109/perf123/sync124/committee14/overflow0/export/power155/power_slow25/scroll40/admin39/sync35/ui27/notice_data27/notice_live16/notice_time79/notice_time_live33/pos12/swipe_perf/x5_anim28/orient_power33/drag36）。
- **上线**：`index.html` **557,076 B · sha256 `6d7b0aa864f7911d6f5a7a584f2710ba6ce6357774758752540f54f0f14ff7f5`**（本地=线上逐字节 MATCH；模板未变、未重新 embed）。
- **回滚**：`tools/_backup/index_online_20261106-1328_preDragGhost.html`（553,962 B · `187eaa8d…`）。
## 2026-11-06 13:00 · v2.0.0 增量 13：用户 9 条反馈批次（网页 UX + 通知附件/压缩包/跨源合并，已上线）

> 用户 2026-11-06 12:02 九条反馈中的网站/数据管线部分（小程序部分另见 mp 仓库）；本次不含版本号变更（仍 2.0.0）。

- **横竖屏切换工具栏卡住**：根因是 `resize` 时先跑旧几何 thumb 重算 + `renderTabs` 在 `.tabs.morph`(scaleX .975) 动画瞬间用 `getBoundingClientRect` 量到 97.5% 宽度；改为工具栏几何用 `offset*`（不受 transform 影响），resize 顺序 = 清 geoCache → 取消 fly/手势/拖动 → 重排 tabs → rAF 重算 thumb + 重渲染全部页卡片；新增 `v2_orient_power_check.py` 33/33。
- **电费关注宿舍未记录（网页真 bug）**：`POWER.enter()` 仅在 UD 缓存「完全没有 power 字段」时才读本机兜底；正常情况缓存 power 存在但 `sel=""`，导致 1200ms 防抖推送窗口内刷新/离线推送失败即丢选择。改为 sel 为空/非法时始终回退 `zq_power_sel_<sid>` 并补 `D.save()` 重推。
- **全部页卡片拖动**：删除全部「设为首页/替换为X/点击取消」及 `homePending/toggleHome`；全部页卡片右上角三横线 handle：①拖到顶部 `.tabs` = 加入/替换/调整工具栏顺序（写 `homeTools`，≤4，走既有 UD 同步）；②全部页内拖动 = 卡片排序（FLIP 让位 180ms，本机 `localStorage zq_all_order_v1`，不进 UD）；Pointer Events + 触摸/mouse，reduced-motion 关闭动画；新增 `v2_drag_check.py` 22/22。
- **电费慢更新提示（13/16 网关日更）**：趋势卡统计 24h history 相邻采样 `|Δq|>0.005` 变化次数，≤2 次显示「数据更新较慢 · 上次变化 MM-DD HH:MM」（0 次「数据未更新」），估算可用 tile 加「参考」；不插值、不改真实阶梯；新增 `v2_power_slow_check.py` 25/25。
- **通知模板 embed 更新**（来自数据管线）：微信附件（文件 data URI / 图片「待获取」）、压缩包卡（包内文件清单 + AI 摘要 + 小文件下载、「待识别」态）、跨源合并卡（`mergedSources/crossSource` + 「＋微信／QQ」标签）、通知时间新契约；`notice-board-live-demo.html` 2,632,307 B（13:02 重建，模板 99,108 B 不变）。
- **数据管线（briefdesk）同步上线**：`wechat_media.py`（微信附件采集；图片 V2 加密待密钥）、`archive_scan.py`（zip 安全解压+内容识别+AI 摘要，真实 5.18MB 样本验证）、`notice_merge.py`（微信/QQ 跨源重复通知合并，真实数据 47→44 组、3 张合并卡（1 张跨源；12 条旧重复 id 自动 archived））、weflow 班级群 md5 别名兜底（微信消息 0→36 条/30h）、小管家英语作业 `xjg_homework.py` 接入 `run_hw_auto.py`（真实 15 条英语作业、无未完成、token 至 2027-01-05）。
- **旧契约测试修正**：`v2_notice_time_check.py` 79/79、`v2_notice_time_live_check.py` 33/33（按 `briefdesk-plan` 最新契约：`_short_action`、无「报名已截止」渲染、`eventAction` 短动作；L3.13 剔除 ACTION_SHORT 历史归一映射键）。
- **门禁**：既有 7/7（roster199、reset109、perf123、sync124、committee14、overflow0、export ok）；power_check 155/155；v2：scroll40/admin39/sync35/ui27/notice_data27/notice_live16/pos_restore12/swipe_perf PASS/x5_anim28/orient_power33/drag22/power_slow25/notice_time79；线上严格 live 33/33。
- **上线**：`index.html` **553,962 B · sha256 `187eaa8d4d2956c9de84b3548c8d4c877892462711740c543370541d896ca082`**（本地=线上逐字节 MATCH；线上模板 sha `14fb3e2aeaf85e95…`）。
- **回滚**：`tools/_backup/index_online_20261106-1300_preUXBatch.html`（532,533 B · `e38bddcf…`）复制回 `tools/index.html` 后 `python deploy/sync_tools.py`；数据层本次无表结构变更。
- **备注**：mp-class-tools 同功能批次（电费持久化修复/工作台电费卡/慢更新提示/13 键契约）已完成源码与测试，**待用户上传发布**（版本仍 2.0.0、AI off）。
## 2026-11-06 07:56 · v2.0.0 增量 12：宿舍电费 v5（估算可用算法优化 + 可调低电阈值）

> 用户新需求（2026-11-06 07:46）：优化「估算可用」算法；允许用户调整低电阈值（默认 30 度，随账号同步）；
> 同步至小程序由另一任务处理（本任务只改 web，未动 mp-class-tools）。

- **估算算法重构**：7 天窗口分段统计（`dq = q[i-1]-q[i]`：`>0.05` 计用电+时长；`<-0.05` 视为充值跳变整段跳过；
  `|dq|≤0.05` 计时长 0 用电），分别算 24h / 7d 速率（跨度 ≥6h 且 ≥2 采样有效），`rate = 0.65*rate24 + 0.35*rate7`
  （只有一个有效用其自身），`rate = max(rate, 0.05)` 下限，`days = q/rate`；`days≥30` 显示「≥30 天」并满环，
  无估算显示「数据积累中」；环、aria、alert 全部用该估算。
- **「估算可用」tile**：主值天数（≥30 显示「≥30」）+ 标签级副标 `≈ {rate 1位} 度/天`（无估算则空）。
- **可调低电阈值**：默认 30，范围 10–100 步进 10；点「低电阈值」tile 弹 8 档小选择层，选中立即生效并保存；
  判定改为 `q<low` 低电 / `low≤q<low*2` 偏低 / 其余充足（pill、环色、alert、tile 全用）；
  存入 `userdata.power = {sel,at,low}`（顶层 13 键不变、旧数据无 low 按 30、LWW 用 at）。
- 测试：`power_check` **155/155 PASS**（算法 4 组 fixture：混合/充值跳变跳过/持平日下限/24h+7d 混合；阈值：默认、
  弹层 8 档、50/10 切换判定、UD 写入 low、13 键、本机兜底、刷新保持、旧数据默认、换设备恢复、低电/偏低判定）；
  `sync_check` **124/124**（power 契约随 low 更新）；`overflow_check 430`=0；`export_check draw` 正常。
- 上线：`index.html` **532533 B · sha256 `e38bddcf27c389a4a472648c0fa9406cc90df5b66fc3b471924007a17732f09a`**（本地=线上逐字节 MATCH）。
- 回滚：`tools/_backup/index_online_20261106-0755_prePowerV5.html` 复制回 `tools/index.html` 后 `python deploy/sync_tools.py index.html`；本次无数据库结构变更。
- 截图：`tools/tests/_shots_power/power_v5_390.png`（默认阈值）、`power_v5_threshold_390.png`（阈值改 50 的低电态）、
  `power_v5_lowsel_390.png`（阈值弹层）、`power_v5_1280.png`。

## 2026-11-06 07:38 · v2.0.0 增量 11：宿舍电费 v4（24h/7天/30天切换 + 固定 y 轴横滑 + 上次充值）

> 用户新需求（2026-11-06 07:20）：「趋势支持 7 天/30 天切换；『更新』改为上次充值时间+重置度数；趋势加竖坐标轴并支持左右滑动」。

- **三档趋势**：`24h / 7天 / 30天` 分段 chips（40px、默认 24h、选中白底雾青、`localStorage(zq_power_range_v1)` 记忆）；
  按档位请求 `power_history?select=ts,quantity&roomverify=eq.<rv>&ts=gte.<窗口>&order=ts.asc&limit=2000`；
  内存缓存 5 分钟（同宿舍切档不重复拉）；刷新按钮力拉当前档（并确保 24h 数据用于估算天数）。
- **tiles 调整**：估算可用（24h 速率）/ **区间用电**（随档位：近 24h / 近 7 天 / 近 30 天）/ 低电阈值 30 度 /
  **上次充值**（历史跳变 `q[i]-q[i-1]>0.05` 的最后一次：重置后度数 1 位小数 + 时间；无记录「— / 暂无记录」）。
- **竖坐标轴 + 横滑**：右侧固定 y 轴（竖线 + 3 刻度，--ink2 10.5px tabular，不随横滑）；绘图区 `overflow-x` 横滑
  （24h 铺满、7d/30d 点密时加宽；隐藏滚动条；桌面鼠标拖拽）；横轴为固定覆盖层，按可见窗口给 3–5 个日期刻度并随横滑刷新；
  x 坐标按真实时间比例；稀疏/断档不造数；**手势豁免**：`excluded()` 对 `.pw-trend-scroll` 恒返回 true，趋势图横滑不触发站点切工具。
- 视觉沿用 v3 token/字号/间距；空态 y 轴只留竖线、不显示刻度值；充值 chip 按所选档位检测。
- 测试：`power_check.py` 扩展至 **135 项 PASS**（三档/请求 gte 单调/充值 tile 有&无/固定 y 轴/横滑后 y 轴不动+x 轴刷新/
  30d 可横滑/横滑不切 CURTAB/30d 刷新 +1/切回 24h 命中缓存/五档无溢出/0 JS/无外部请求）；`sync_check` 124/124、
  `overflow_check 430`=0、`export_check draw` 正常；通知门禁 `v2_notice_data_check` 27/27、`v2_notice_live_check` 16/16。
- 线上真实冒烟 **25/25 PASS**：空态 0 请求 → 24h → 7 天/30 天切档（更早窗口请求、tiles/图例随档）→ 趋势横滑不切工具 +
  y 轴不动 + x 轴刻度在 → 30 天档刷新 → userdata.power 云端确认 → 换全新 profile 恢复关注宿舍（档位设备级默认 24h）。
- **上线**：`index.html` **527,152 B · sha256 `2cf7ed06aac81dea30e882bbb6454a2edd09269b49141ff8ba342459d462427b`**（本地=线上逐字节 MATCH）。
  本次上线 = 电费 v4 + **通知板模板刷新**（`NOTICE_TPL_B64`，非本会话产生，已跑通知门禁；部署前线上 518,416 B · `5d923415…`）。
- 回滚：`tools/_backup/index_online_20261106-0737_prePowerV4.html`（518,416 B · `5d923415…`）复制回 `tools/index.html` 后
  `python deploy/sync_tools.py index.html`；数据层无需回滚（本次无表结构变更）。
- 截图（`tools/tests/_shots_power/`）：`power_v4_390.png`、`power_v4_7d_390.png`、`power_v4_30d_390.png`、
  `power_v4_recharge_390.png`、`power_v4_1280.png`；线上：`power_live_v4_empty_390.png`、`power_live_v4_390.png`、
  `power_live_v4_7d_390.png`、`power_live_v4_restored_390.png`。

## 2026-11-06 07:33 · v2.0.0 增量 10：通知时间全量日期化 + 动作精简 + 正文版式（已上线）

> 旅行者反馈：「下午招聘会请准时到场还是没有修复日期问题，请再次检查所有通知是否符合，同时时间动作应该尽量精简，
> 药膳答题打卡活动报名下方请放置经ai精简后的内容，而原始消息应该都被放入按钮中」。
> 契约：`C:\briefdesk\scripts\通知时间显示与识别_契约_20261105.md` §0（第三轮补充）；说明：同目录 `通知时间显示与识别_修复说明_20261105.md` §五。

### 一、通知模板（iframe 模板）

- **全量日期化**：absRelDates 增强——裸日号 `5号/4日`→11-05/11-04（语境限定，排除「42号同学」）、裸时段（上午/下午/晚上/中午）→ 前缀 `MM-DD`、
  裸周「本周/下周」→ 周一、`本周（11.4）` 用括号日期、绝对日期+括号相对词去重、**「今日校园」专名保护/还原**；作用到**标题**、
  aiSummary/aiPoints/aiSegments、原文、合并转发、原始消息弹层、链接/附件名、来源群名。
- **chip 动作精简（≤6 字）**：报送姓名截止→报送截止、集合点名→点名、活动开始→开始、签到开始/签到签退→签到、比赛开始→比赛、考试开始→考试；
  `报名已截止`→`报名截止`（无「已」）；长期安排例外不变。
- **正文版式**：所有有 aiSummary 的卡（含合并/补充通知卡）正文只保留 AI 摘要/要点/segments/附件/图片/链接/收集表；
  **原始消息（含补充通知原文）全部收进「原始消息」按钮**，弹层按每条发送时间日期化。药膳 c0、申报合并卡均内联=0、按钮 3 条。

### 二、数据链路（C:\briefdesk）

- `ai_brief.py`：`CACHE_VER=8`；prompt v8 给每条消息附发送时间 + 「系统已解析关键时间（必须原样使用）」块；
  `repair_brief_entry` 确定性修复（同 HH:MM 绑定、节次绑定、recurrence startAt、points 残句、冗余时段、今日校园还原）+ 最终统一限长
  （title≤20/summary≤60/points≤12/seg≤40）；缓存 hash 纳入 eventAt/signup/动作/recurrence。
- `notice_time.py`：裸日号/裸时段/裸周/括号去重/专名保护；报名窗口收紧（cue 与端点同分句、裸窗口需显式钟点、时间抽取只用 item.text）；
  recurrence 清一次性 eventAt；事件语义闸门（课程表等不补假 eventAt）；R5 5号/4号 eventAt 09:00 非 00:00；动作短词。
- 回归修复：`g_games_viewer` signupEnd 误算 11-06 14:00 → 恢复 11-03 18:30（chip=`11-03 18:30 报名截止`）。

### 三、验证与上线

- QA 本地最终验收 **68/68 PASS**（R1–R9 + 回归 5 项 + 逐卡 44 组表）；Lead 线上自验 **29/29 PASS**；云端 44/44 同步。
- 上线：`index.html` **518,416 B · sha256 `5D923415A584…95C0`**（以线上版为基底只替换 NOTICE_TPL_B64，diff-only-template 校验通过）；
  回滚：`tools/_backup/index_online_20261106-0731_preR3Deploy.html`（511,604 B）重传即可。
- 小程序同口径已改（unit 182/182、notice 20/20、auto-preview 编译通过），**未上传、版本仍 2.0.0**。

## 2026-11-06 07:05 · v2.0.0 增量 9：宿舍电费「数据仪表盘」v3（已上线）

> 用户新需求：「请充分利用空间，提高视觉效果和 ui」——针对 `#s-power` 做数据仪表盘升级。

### 一、数据层（新增历史采样）
- CloudBase 新表 `public.power_history(id bigserial / roomverify / quantity / unit / ts)`：索引 `(roomverify, ts desc)`；
  RLS 读=`auth_ok()`、写删=`auth_admin()`；迁移 `deploy/cloudbase/2026-11-06_power_history.sql`（含回滚）。
- `sync_power_cloud.py`：每次成功写 power 后追加同 ts 历史；新增 `--backfill-log`（解析 power-sync.log，兼容旧格式，
  按 `(roomverify, ts)` 去重，可重复跑）+ 30 天前历史自动清理；回填 **169 行 / 17 间房**，增量同步 `history_ok=17`。

### 二、前端 `#s-power`：hero 电量环 + 近 24h 趋势 + 指标
- **环语义**：`arc = clamp(估算可用天数/30)`（数据不足 → 「数据积累中」+ 小弧兜底）；环内大字=剩余电量
  （≥100 取整、<100 一位小数），下方「≈N 天」；`role="img"` + `aria-label` 完整描述；颜色按状态（充足雾青/偏低暖沙/低电红）。
- **布局**：≥960 两栏 5fr/7fr + `min-height:max(560px,calc(100vh-200px))`（1280×1000 仪表盘底距视口底 27px；
  1280×800 无纵向滚动），左栏环垂直居中、右栏趋势吃满 + tiles 固定底部；720–959 hero 横排 + 趋势全宽 + tiles 一行 4 格；
  390 纵向三段；空态不折叠右栏（稳定占位）。
- **信息**：近 24h 趋势（内联 SVG 折线 + 面积 + DOM 端点 + 起点/当前/下降图例，含「期间有充值」chip、只累计下降）；
  4 个指标 tiles：估算可用 / 近 24h 用电 / 低电阈值 30 度 / 更新约 1 小时/次；低电 alert（移动端 hero 后、桌面通栏置顶）。
- **可达性**：状态 pill 与 alert 换 AA 配色（充足 #2F6555/#EAF2EC、偏低 #8A6A3E/#FAF3E6、低电 #8F5550/#F7EDEB、
  alert #8A5049）；小字 ink3→ink2 且 ≥11.5px；全部沿用 Monet token，无新增外部请求/字体/库。
- 删解释性文案与重复：房间名只在「下拉选中值」出现 1 次，更新时间只在 hero 状态行 1 次；tile 不出现内部任务名。

### 三、测试与上线
- `tools/tests/power_check.py` 重写为 **110 项**：环刻度/趋势/指标/空态/低电/期间充值/UD 同步（选择 / 同设备恢复 /
  换设备恢复 / 两账号隔离）/ 空间基准（1280×1000、1280×800）/ 360·430·1280 无溢出 / 0 JS 报错 / 无外部请求。
- 回归：`sync_check` 124/124、`overflow_check 430`=0、`export_check draw` 正常。
- 截图：`tools/tests/_shots_power/power_v3_{390,768,1280,1440}.png`、`power_v3_empty_390.png`、`power_v3_low_390.png`。
- 上线：`index.html` **511,604 B · sha256 `9b6143cb7d89fa11fb1ae16df59f1b833c81a25fe26e84b4b0473eaffeaccc6c`***（本地=线上 MATCH）；APP_VER 仍 2.0.0；只传 `index.html`。
- 回滚：`tools/_backup/index_online_20261106-0701_prePowerV3.html`（496,283 B · `c929bd83…`） 复制回 `tools/index.html` 后
  `python deploy/sync_tools.py index.html`；云端回滚 `DROP TABLE IF EXISTS public.power_history`。

## 2026-11-05 23:52 · v2.0.0 增量 8：电脑端「比例」UI 优化（全站，已上线）

> 用户需求：「优化电脑比例的 ui」→ 确认范围 = **全站电脑端统一优化**。

- **审计先行**：`tools/tests/_desktop_audit/REPORT.md`（1024/1280/1366/1440/1920 × 13 页 + 抽签 3 STEP，75 截图 + metrics）。
  主因：`.wrap` 放宽到 1520，但内容排布没跟上 → 宽屏空白多、卡片过窄/过宽、断点跳变。
- **实现**：`index.html` 的 `<style>` 末尾新增一段 ≥960px 的 CSS 覆盖块（标记 `DESKTOP-OPT-V1`），
  **不改手机端、不改 JS/HTML 结构、不加功能**。
- **主要改动**：全部页卡片 250–272px 起 + 内容限宽（7 列窄卡 → 4 列宽卡）；诊断页两栏瀑布流（消除 194px 行间空白）；
  电费下拉限宽 + 大字面板；班委 2/3 栏；统计改两栏（摘要 520→300 + 排行榜右侧）；点名多列断点 1200→960；
  作业/通知双栏断点 1200→1024；反馈表单限宽 + 列表两栏；抽签 STEP1 右栏结果面板撑满（88→396px）+ 排序/动作固定右栏底部；
  STEP2 分组卡加大；使用说明三栏；课表 ≥1600 解除 1180 固定宽；长文本 70ch。
- **验收**：16 项门禁全绿（sync 124、v2_sync 35、v2_ui 27、v2_admin 39、v2_scroll 40、x5 28、power 75、
  committee 14、notice_live 16、roster 199、pos_restore 12、notice_data 27、stats 30、swipe_perf PASS、
  overflow 430/390=0、export OK）；线上真实冒烟 1920/1440/390 **0 JS 报错、0 横向溢出**，效果生效、手机端不变。
- **上线**：`index.html` **496,283 B · sha256 `c929bd83561dd2312153493051230fbd037f2020a4de36dd4ba07c3fbd6b09e8`**
  （本地=线上 MATCH；APP_VER 仍 2.0.0）；回滚 `tools/_backup/index_online_20261105-2350_preDesktop.html`（491,461 B）。
- **未做/限制**：通知 iframe 内部两栏（模板生成侧）；<960px 保持原样；>1920 未专项审计。

## 2026-11-05 23:23 · v2.0.0 增量 7：通知 AI 识别与时间显示修复（已上线）

> 用户反馈 6 条：申报材料截止时间错误/相对日期、时间显示不统一、活动报名优先报名时间、申报材料两条未合并、网名B未映射班委、本人发布通知未识别。
> 契约：`C:\briefdesk\scripts\通知时间显示与识别_契约_20261105.md`；说明：`C:\briefdesk\scripts\通知时间显示与识别_修复说明_20261105.md`。

### 一、通知模板（iframe 模板，build_notice_board.py → build_notice_embed.py）

- 时间区域统一 **「<时间> <动作>」**：`fmtWhen`（<1h 分钟后 / <24h 小时后 / <7d 天后 / 其他与已过绝对 MM-DD HH:MM）；
  报名优先（`signupStart/signupEnd` → 报名开始/报名截止/报名已截止）；`deadlineAction`/`eventAction`（缺省 截止/开始）；
  长期安排 `长期安排 · label`；修掉「明天 12:00 显示成今天 12:00 截止」旧 bug；简报「最近截止」同口径。
- 消息文本相对日期替换 `absRelDates`：今天/明天/今晚/明早/本周X/下周X/裸周X → MM-DD（锚点=首条 item.time；
  作用于 AI 摘要/要点/segments/原文/补充通知/合并转发/原始消息弹层）。
- 合并/多消息卡渲染全部原文 item（不再被 aiSummary 隐藏）；透传 `aiMerged/supplement/updatedAt`（「已更新」徽标）。
- 发送者身份映射：class-members + class-identities + class-aliases，网名「网名B」→ 同学B/学习委员/班委。

### 二、数据链路（C:\briefdesk，非 web 仓库）

- 新模块 `scripts/notice_time.py`（时间解析/报名窗口/动作推断/归一/相对日期替换，pipeline 与 builder 共用）。
- `ai_triage.py`：不再跳过 `isSend=1`（本人消息）；AI schema 新增 `deadlineAction/eventAction/signupStart/signupEnd`
  与 `supplements.sameEvent`；合并保留更早 deadline；确定性同事件合并兜底；本人转发链接 rescue（并入同主题卡）。
- `ai_brief.py`：摘要/要点/segments 相对日期按 item 发送时间替换（CACHE_VER=5）。
- `sync_notices_cloud.py`：compact_group 带新时间字段（不碰管理员列）。

### 三、验证与上线

- QA 独立验收 **76/76 PASS**（A1–A9，含 5 项回归：v2_notice_data_check 27/27、v2_ui_check 27/27、v2_admin_check 39/39、
  overflow 430=0、export_check 正常、0 JS 报错）；证据 `tools/tests/_v2_notice_time_reports/`、`C:\briefdesk\data\_qa_nottime\`。
- 云端 public.notices 44/44 同步：申报材料合并 1 行、献血合并行、27 行带新时间字段；Lead 线上自验 **20/20 PASS**。
- 上线：`index.html` **491,461 B · sha256 `B7819E39BC14…B47F`**（线上逐字节一致）。
- 回滚：`tools/_backup/index_online_20261105-2323_preNoticeTime.html`（483,097 B · `16087845…`）重传即回滚。
- 小程序同口径已改（utils/notice.js + pages/nt/*，unit 162/162、auto-preview 编译通过），**未上传/未改版本号 2.0.0**。

## 2026-11-05 23:15 · v2.0.0 增量 6：宿舍电费 v2（统一命名 + 单选关注 + 选择进同步，已上线）

> 用户新需求：「统一宿舍的名称；不需要所有宿舍统一展示，每个账号选择一个宿舍关注就好（不是一次性选择，做下拉框）；宿舍选择也要放到同步里」。

### 一、统一命名（全链路）

- 规则 `{楼号}号楼{座}{房间号}`，23 号楼用「23号楼A座 / 23号楼B座」：`13号楼324/308`、`16号楼305/306`、
  `23号楼A座321…330`、`23号楼B座422…425`（roomverify 不变：`1-13---3xx` / `1-16---3xx` / `4-23A---3xx` / `4-23B---4xx`）。
- CloudBase `public.power`：**`id` 改为 `roomverify`（稳定主键）**，17 行逐条 UPDATE 迁移 label/building；
  新增 anon DELETE 授权 + 仅管理员 `pw_delete` 策略（同步脚本清理过期行用）。
  迁移：`deploy/cloudbase/2026-11-05_power_v2_names.sql`（含回滚）；建表脚本已同步为 v2 最终形态。
- `C:\briefdesk\scripts\sync_power_cloud.py`：`ROOMS` 改规范名、按 `id=roomverify` PATCH/POST、全量后清理不在 ROOMS 的旧行；
  真跑 `ok=17/17 stale_deleted=0 cloud_rows=17`。计划任务 `ClassPowerSync` 仍每 60 分钟。

### 二、前端：单选关注（下拉框）

- `#s-power` 去掉「全部宿舍」列表/楼栋 chips/房间 chips → **「关注宿舍」原生下拉框**（`<optgroup>` 按规范楼栋分组，
  选项=规范 label、value=roomverify，高 44px）+ 当前宿舍大字剩余电量/状态/更新时间 + 刷新。
- **未选择时不发任何电量请求**（选项来自静态 `PW_ROOMS` 17 间）；选择后只请求 `power?id=eq.<roomverify>`；
  低电（<30 度或云端 low）标红；≥960px 左右两栏；「全部」页卡片副标题同步改。
- 页面仍只有规范楼栋+房间号+电量+时间，**无姓名/学号**；不接入导出。

### 三、选择进同步（userdata v6 新增 `power` section）

- `power = {sel:"<roomverify>", at:<ms>}`，复用 v6 LWW 合并/本机缓存/1200ms 防抖/云端拉取；blob 顶层键变 13 个
  （`v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,homeToolsAt`）。
- 两账号互不影响；换设备/换浏览器同一账号登录后从云端恢复；本机 `zq_power_sel_<sid>` 仅离线兜底（真源 `UD.power`）。
- 小程序端未拥有该 section：原样保留、暂不展示电费（契约已写入 `AGENTS.md` §4b / HANDOFF §37.5）。

### 四、测试与上线

- `tools/tests/sync_check.py` **124/124 PASS**（power 契约/13 键/合并期望值全部更新）。
- `tools/tests/power_check.py` 重写 **75/75 PASS**（下拉框、未选择 0 请求、单选显示、低电、同设备恢复、换设备恢复、
  **两账号隔离**、非法值降级、360/430/1280 无溢出、0 JS 报错、无外部请求、3 张截图）。
- 回归：`overflow_check.py 430`=0、`export_check.py draw` 正常落盘。
- **线上真实冒烟 24/24 PASS**：真实登录 → 选 23号楼A座321 → 真实电量/刷新 → userdata 推送 →
  **全新 profile 重新登录自动恢复关注宿舍并拉到真实电量**。
- 上线：`index.html` **483,097 B · sha256 `16087845e4c938e3f4d5f18ff53d91ea489c4c6bd7410aac207cda2cebc3a306`**
  （本地=线上 MATCH；APP_VER 仍 2.0.0）。
- 回滚：`tools/_backup/index_online_20261105-2311_prePowerV2.html`（482,591 B · `1422438f…`）复制回 `tools/index.html` 后
  `python deploy/sync_tools.py index.html`；云端命名回滚 SQL 见 `2026-11-05_power_v2_names.sql`。

## 2026-11-05 23:05 · v2.0.0 增量 5：宿舍电费（已上线）

> 用户需求：「在『全部』页加一张宿舍电费卡片，点开能选任一班级宿舍看剩余电量，低电标红」；已确认方案 A（「全部」页卡片，**不改顶部 4 格布局**）。
> 数据走 CloudBase（身份 token 才能读，不放公开静态文件）。

### 一、数据链路（免登录）

- 完美校园 CloudPay 网关：`POST https://cloudpaygateway.59wanmei.com:8087/paygateway/smallpaygateway/trade`，
  `{"method":"samllProgramGetRoomState","bizcontent":"{...}","timestamp":"yyyy-MM-dd HH:mm:ss","sourceId":2}`；
  bizcontent = `{"payproid":"2122","schoolcode":"769","roomverify":"<id>","businesstype":"2"}`；
  头 `Content-Type: application/json` + Origin/Referer `https://cloudpaygateway.59wanmei.com:8087(/pay/index.html)`。
- 返回 `businessData.quantity`（字符串）/ `quantityunit`（“度”），`returncode=SUCCESS`。**查询房间不需要学号**；
  学号/姓名只用于 CloudBase 写 token（`rpc/class_verify`）。
- 班级 **17 间房**的 roomverify 已逐间实测并固化在 `sync_power_cloud.py`（13号楼324=`1-13---324` … 23B-425=`4-23B---425`）。

### 二、云端表 `public.power`

- 列：`id(text PK=label) / label / building / room / roomverify / quantity numeric / unit / low bool / updated_at timestamptz`。
- RLS：`pw_read = auth_ok()`（有效班级 token）；`pw_insert / pw_update = auth_admin()`（仅管理员）；
  anon 授 SELECT/INSERT/UPDATE、无 DELETE（同步脚本只 upsert 不删行）。
- 迁移：`deploy/cloudbase/2026-11-05_power.sql`（幂等 DDL + RLS + 回滚语句，已应用）；实测匿名读 `[]`、管理员读 17 行。

### 三、本机同步 + 计划任务

- `C:\briefdesk\scripts\sync_power_cloud.py`：串行 17 间、请求间隔 1.1s、失败 3 次退避；PATCH 已存在行 / POST 新行；
  失败的房间**保留旧值**并记日志；日志 `C:\briefdesk\logs\power-sync.log`；**输出与日志不含姓名/学号**；
  token 缓存 `C:\briefdesk\secrets\class-token.json`（与 `sync_notices_cloud.py` / `health_beat.py` 共用，过期自动刷新）。
- 计划任务 `ClassPowerSync`：`pythonw.exe` 隐藏窗口，**每 60 分钟**（按网关软限流，由原定 30 分钟调整为 60）。
  首次手动同步：`ok=17/17 gateway_fail=0 cloud_fail=0 low=1 elapsed=27.6s cloud_rows=17`。

### 四、前端（`tools/index.html`）

- 「全部」页新增「宿舍电费」卡片（`data-open="power"`，无「设为首页」；**顶部工具栏 4 格布局未改**）。
- `section#s-power`：摘要（共 N 间 · 低电 M 间 · 更新时间）+ 刷新按钮；楼栋 chips（全部/13号楼/16号楼/23A/23B）→ 房间 chips；
  大字剩余电量（44/54px，low 标红）+「低电/充足」+ 单房更新时间；全部宿舍按电量升序（低电在前、带占比条）；
  ≥960px 左右分栏，≤400px 缩字号；全部可点区域 ≥40px。
- JS：`POWER` 模块 + `PW_LOW=30` / `PW_BLDS`；`TTL.power=2*60*1000`；`gotoTab` 放行 power 页；`renderAllCards` 卡片；
  `POS.begin` 允许刷新恢复电费页；`cloudPull` 仅在电费页按 TTL 拉取；数据走现有 `cbH()`（Bearer CBK + `X-Device-Id: token`），
  **身份门禁通过后才请求**；本机缓存 `zq_power_cache_<sid>`、选中房间 `zq_power_sel_<sid>`。
- 隐私：页面/JS 只有楼栋 + 房间号 + 电量，无姓名/学号；未接入导出图片（`exportCard` 未动）。

### 五、测试与上线

- 新增 `tools/tests/power_check.py` **59/59 PASS**（未登录 0 请求、卡片/打开 s-power、请求契约、升序/低电标红、楼栋筛选、
  大字/状态、刷新、40px、空数据、360/430/1280 无横向溢出、0 JS 报错、无外部请求、2 张截图）。
- 线上真实冒烟 **22/22 PASS**（headless Edge + CDP，真实 `class_verify` 登录 + 真实 `public.power` 17 行、power 请求 200、
  0 JS/console 报错、无外部请求）；截图 `tools/tests/_shots_power/power_live_390.png`、`power_live_1280.png`。
- 回归：`overflow_check.py 430`=0、`export_check.py draw` 正常落盘、`stats_check.py` 30/30、`committee_check.py` 14/14。
- 上线：`index.html` **482,591 B · sha256 `1422438fa341a57162d1b7e86f99428ef728f9df0de4c5d744b32124e1600692`**
  （本地=线上 MATCH；部署前线上 468,856 B · `7a2704e0…` = 含并发会话「诊断页」的基线）。
  本次上线 = **线上基线（service_health/诊断页，另一会话，未由本会话验证）+ 本会话电费功能**；APP_VER 仍 **2.0.0**。
- 回滚：`tools/_backup/index_online_20261105-2252_prePower.html`（468,856 B · `7a2704e0…`）复制回 `tools/index.html` 后
  `python deploy/sync_tools.py index.html`；云端 `DROP TABLE IF EXISTS public.power`；
  任务 `schtasks /Delete /TN "ClassPowerSync" /F`。

## 2026-11-05 23:0x · v2.0.0 增量 4：管理员「诊断」页 + 关机重启韧性（已上线）

> 用户需求：「确保班级工具站的信息获取等功能即使关机重启后也能正常使用，同时为我在班级工具站内部新增一个仅管理员可见工具，显示各个依赖服务是否正常」。

### 一、管理员「诊断」页（仅管理员可见）

- **13 个依赖服务**（契约 `tools/tests/health_monitor_spec.md`）：云端数据库 / 站点资源 / 站点证书 /
  采集主机 / QQ 消息采集 / 微信消息采集 / 本地通知服务 / 文档与通知监听 / AI 识别 / 教务课表同步 /
  作业自动整理 / QQ 客户端 / 微信客户端。
- **数据来源**：采集主机心跳 `public.service_health`（新增云端表，仅管理员可读写；每 5 分钟上报 13 行）
  + 浏览器实时探测（CloudBase 延迟、同源 `tt.json` 延迟）。心跳 >15 分钟未更新 → local 行降级「离线」灰态；
  云端请求失败 → 顶部「云端连接失败」、local 行「未知」，不误报。
- **界面**：摘要卡（全部正常 / n 项注意 / n 项异常 / 采集主机离线 + 最后检测时间 + 刷新按钮）；
  四组卡片（站点与云端 / 信息采集 / 定时任务 / 采集主机）；行内状态点 + 状态胶囊 + detail + 上报时间/延迟；
  手机单列、≥960px 两列；停留本页 60s 自动刷新（页面隐藏/切走暂停）。
- **门禁**：`TOOLS` 的 `admin:true` + `toolShown()` + `gotoTab` 通用判定 + `DIAG.pull()` 内 `canManage()`
  三层，非管理员**不出现入口、不发起任何 `service_health` 请求**；RLS 同时保证非管理员读 = `[]`。

### 二、关机重启韧性

- 新增计划任务 `Class Tools Clients`（登录后 90s）：`ensure_clients.py` 幂等检测并静默拉起
  QQ（QQNT）/ 微信（Weixin）客户端 —— 消息源在线才有新消息可采集。
- `Class Homework Auto`：新增登录触发（+3 分钟）、StartWhenAvailable、电池限制解除、失败重试（PT10M×3）。
- `JwxtTimetableSync`：新增登录触发（+2 分钟）、失败重试（PT10M×3）；每日 07:00 + StartWhenAvailable 保留。
- `Briefdesk Watchdog` 原有「每 5 分钟 + 登录 + StartWhenAvailable」保持；心跳已并入其每轮结束。
- 任务 XML 备份：`C:\briefdesk\data\_backup_taskxml_20261105\`。

### 三、验收与上线

- 后端：13 行全 ok、心跳幂等、匿名/非管理员读 `[]`、写入仅管理员、杀 qqflow 后 watchdog 隐藏重启 20.9s 恢复、
  挂起故障正确显示 down、pause 语义正确；QA 独立报告 `tools/tests/_health_qa/REPORT.md`（227 项：201 PASS / 0 FAIL / 26 INFO）。
- 前端：admin 渲染 13 行/4 组/摘要/刷新、非管理员 0 入口 0 请求、360/390/430/1280 无溢出 0 JS 报错、
  断网/空表降级、60s 自动刷新与隐藏暂停；回归 sync 117/117、perf 123/123、v2_ui 27/27、v2_admin 39/39、overflow 430=0、export 正常
  （部署前 + 部署后对线上字节冻结副本各跑一遍）。部署后线上独立复验 20/20 PASS。
- 上线：`index.html` **468,856 B · sha256 `7a2704e0fc3df225a113f9e1e2a85709945eeed6211d6d7d508c58d11acfe1ad`**
  （本地=线上 MATCH）；同时含另一并发会话的 flicker fix（并集，相对 flicker 版仅 264 行 diag 新增 + 2 行预期替换）。
- 回滚：`tools/_backup/index_online_<部署前>_preDiag.html` 复制回 `tools/index.html` 后
  `python deploy/sync_tools.py index.html`。
- 云端回滚：`DROP TABLE IF EXISTS public.service_health`（见 `deploy/cloudbase/2026-11-05_service_health.sql`）。
- 说明：心跳与计划任务都运行在**本机**（采集主机）；Windows 需登录后触发（InteractiveToken 限制）。

## 2026-11-05 22:00 · v2.0.0 增量 3：通知页横向「重影」修复（微信 X5 合成残影，已上线）

> 用户（手机微信）反馈：上下滑动已解决，**但左右滑动仍有重影等动画异常**；用户确认**只在通知页**、且**手指拖动跟手时就出现**。

- **根因**：微信 X5/WebView 对「含 iframe 的整块 section 做 transform」会出现合成残影（iframe 是独立 surface，位移时旧帧残留）；且 `fly()` 对大面积子树同时动画 opacity+transform 会放大 alpha 合层残影。
- **修法（仅通知页横向 + 允许的 fly 优化）**：
  1) 通知页左右滑**不再 transform `section.on`/iframe**：只驱动 toolbar thumb 跟手；松手**直接切 tab**（`directSwitch()`，不走 `fly()`），保留 320ms 点击抑制；进入通知页同样直接切，避免 incoming iframe 被位移。
  2) `fly()`（其它工具页）：去掉 opacity 动画，只动 `transform: translate3d`；动画期间给 `<body>` 加 `zq-flying` 临时禁用 `section.on/.stpane.on` 的 fade；结束清理内联样式/`will-change`/类。
  3) toolbar thumb 统一 `translate3d`。
- **验证**：新增 `tools/tests/v2_x5_anim_check.py` **24/24 PASS**——通知页拖动 13 个采样点 section 全程无 transform、iframe rect 全程不变、thumb 跟手、preventDefault=12；松手 nt→all、切后无 transform、320ms 内点击被抑制后恢复；非通知页 fly 20 次 translate3d、**0 次 opacity 内联**、`zq-flying` 临时存在、结束清理干净。其它手感指标不退化（4px 慢速首跟手、step reaction=1/syncErr=0、通知纵向原生 161px/父页 0/JS scrollBy 0、滚动中 POS 写入 0）。
- **回归**：既有 7 门禁 + v2 9 条（scroll40/admin39/sync35/ui27/notice_data27/notice_live16/pos_restore12/swipe_perf PASS/x5_anim 24）全绿。
- **上线**：`index.html` **453,951 B · sha256 `186651f292afe28292f9ae91d522e0c2657cb033ed044d7903ba21aa70219f82`**（本地=线上 MATCH）；
  回滚：`tools/_backup/index_online_20261105-2200_preX5Anim.html`（452,250 B · `5b5bb6c3…`）。
- **观感变化（按范围约定）**：通知页左右滑内容不再位移（只 thumb 跟手、松手直切）；其它工具页保持原跟手+fly；fly 不再淡入淡出（纯位移）。若真机仍有极轻微残影，下一档可拖动时临时隐藏 iframe / `contain:paint`（本轮未做，避免影响滚动与弹层）。
- **约束（以后不要回退）**：**含 iframe 的通知页不要做整块 section transform**；大面积子树不要同时动画 opacity+transform（X5 残影风险）。
## 2026-11-05 21:27 · v2.0.0 增量 2：微信内滑动手感二次修复（横向死区 + 通知页原生纵向滚动，已上线）

> 用户（**手机微信内置浏览器**，已清缓存）二次反馈：「网页还是抽搐不跟手，在滑动速度慢时更加明显」；
> 具体为 ①左右滑动切换工具/页面 ②通知页里上下滚动。

### 根因（CDP 合成 touch 实测，修复前线上 449,446 版）

| 现象 | 实测 |
|---|---|
| 慢速横滑（4px/步） | 首个跟手位移 **12px**（前 1–2 步空走，过阈值后突跳）→ 慢速最明显 |
| 通知 iframe 内慢速横滑 | **12px**（适配层 10px 死区 + 全局 12px 叠加） |
| 通知页纵向拖动 | iframe 自身 scrollY **恒 0**，`parent.scrollBy` 被调 **19 次**、父页滚 90px → 每帧滚动一个 20,000px iframe 层，微信 WebView 必掉帧且无惯性 |

### 修法

1. **横向跟手**：全局锁定阈值 12→**4px**、比例 1.35→**1.2**；通知 iframe 横向适配死区 10→**4px**（去双阈值叠加）；
   工具栏 thumb 液体宽度脉动仅 ≥16px 位移启用（小位移不再抖晃）。锁定后每步同步直写 transform（不再 rAF/batch）。
2. **通知页纵向**：回退为**固定视口 iframe + iframe 内部原生滚动**（手机 `calc(100vh-140px)` / 桌面 `calc(100vh-150px)`，`scrolling="yes"`）；
   父页不再随通知内容滚动，`class-notice-height` 父页忽略；iframe 触摸适配层**纵向完全放行**（不 preventDefault/不 scrollBy），
   只处理横向切工具；仅当「纵向拖 2 帧后 iframe scrollY 仍无变化且内容可滚」才启用 JS `scrollBy`+衰减惯性兜底。
3. **刷新保位**：通知页父页只恢复 tab；iframe 内滚动由注入脚本 `zq_nt_scroll_v1` 自存自恢（260ms 落盘 + 加载后重试 ~3.6s）。
4. 回归修复：`.tabs{overflow:hidden}` + thumb 位置 clamp，消除滑块回弹过冲导致 720/1280 瞬时页面加宽 6–10px。

### 修复后指标（`tools/tests/v2_swipe_perf.py`）

| 指标 | pre-v2 | 修复前（449,446） | 修复后（452,250） |
|---|---|---|---|
| 慢速 4px 首个跟手位移 | 12px | 12px | **4px** |
| 慢速锁定后跟手率 | 1.00 | 0 | **1.00** |
| 通知 iframe 内 4px 首个跟手 | — | 12px | **4px** |
| 通知页纵向 iframe scrollY | 161 | **0** | **161（原生）** |
| 通知页纵向 parent scrollY | 0 | **90** | **0** |
| 通知页纵向 JS scrollBy 次数 | 0 | **19** | **0** |
| step 手势 reaction / syncErr | 1 / 0px | 0 / 20px | **1 / 0px** |
| 滚动中 `zq_pos_v1` 写入 | 0 | 10 | **0**（停止后 1 次） |

### 验收与上线

- 测试：既有 7 门禁全绿（roster 199/reset 109/perf 123/sync 117/committee 14/overflow 0/export）；
  v2 8 条全绿（**scroll 40/40**、**pos_restore 12/12**、notice_live 16/16、admin 39/39、sync 35/35、ui 27/27、notice_data 27/27、**swipe_perf PASS**）。
- 上线：`index.html` **452,250 B · sha256 `5b5bb6c333a56edfa9d0a237ba1d0f5a914dc7bd1949ec09c7d659b8747bffd0`**（本地=线上 MATCH）。
- 回滚：`tools/_backup/index_online_20261105-2127_preWeChatFix.html`（449,446 B · `701fd0f8…`）；
  更早 `index_online_20261105-2016_v2final.html`（448,812 B · `2253e5e4…`）。
- 注意（架构定稿）：**通知页纵向滚动必须由 iframe 原生滚动承担**，不要再改回「父页滚动 + iframe 自适应高度」（见 AGENTS §4b.2 / HANDOFF §33）。

## 2026-11-05 20:25 · v2.0.0 增量：网页滑动手感修复 + 审核相关功能收敛（网页已上线 / 小程序待上传）

> 用户 20:07 反馈：「网页滑动现在有阻滞感，不够跟手且出现了一些抽动」；「除添加账号外不要再有其他审核相关功能加入」。

### A. 网页滑动手感（已上线）

- **根因（v2 引入的性能回退）**：v2 把全局滑动的 `touchmove` 改为「只记录位移 + rAF 合并写 transform」，
  并且 `POS.saveSoon` 在滚动中 rAF + 每 160ms 同步 `sessionStorage.setItem`；同时 `touchstart` 无条件
  `geoInit()` 触发 getBoundingClientRect 强制布局。实测（`tools/tests/v2_swipe_perf.py`，12 次 touchmove）：
  | 指标 | pre-v2 baseline | v2 线上（修复前） | 修复后 |
  |---|---|---|---|
  | reactionRate（手势位移与 transform 同步命中率） | 1 | **0** | 1 |
  | syncErrP50 / P95（transform 落后位移 px） | 0 / 0 | **20 / 20** | 0 / 0 |
  | 滚动期间 sessionStorage 写入次数 | 0 | **10** | 0（停止后 1 次） |
  | frameP95 / longFrames | ~28.7ms / 1 | ~28.5ms / 1 | ~28.3ms / 1 |
- **修法**：①`touchmove` 内**同步直写** `transform`（与 v2 前一致；单元素开销小），`transition:none` 只在本次手势首次锁定时设一次；
  ②`geoEnsure()` 复用工具栏几何缓存（校验 isConnected/宽度），`touchstart` 不再无条件读布局；
  ③`POS.saveSoon` 改为滚动停止 480ms 后单次落盘，滚动中不写同步存储；切 tab/退出身份/pagehide/visibilitychange 仍立即写；
  ④通知 iframe 手势预览同样改为同步跟手（`__zqSwipePreview`）。
- **验证**：新增 `tools/tests/v2_swipe_perf.py`（baseline/prefix/fixed 三档，PASS）；全量回归（既有 7 门禁 + v2 7 专项 + pos 10）全绿；
  QA 独立复跑三档指标一致。
- **上线**：`index.html` **449,446 B · sha256 `701fd0f8cd31af4be5b6a86f909e09c24f01e8ee74904dc073e06fef8fba3668`**（本地=线上 MATCH）；
  回滚：`tools/_backup/index_online_20261105-2016_v2final.html`（448,812 B · `2253e5e4…`，即修复前 v2.0.0）。

### B. 小程序：移除演示/审核模式，仅保留“添加账号”的测试身份（待上传）

- 按用户要求删除全部「演示/审核模式」：`utils/demo.js`、`utils/demo-data.js`、身份页「演示模式（审核用）」入口、
  「我的」页演示提示/退出、`cloud.js` 的 demo 拦截、`notify.js` demo 守卫、store demo 桶、相关测试与截图；
  README/CHANGELOG 改为「不实现审核模式」。
- **唯一的审核相关能力 = 测试账号**：云端 `private.class_ids` 新增 `is_test=true` 的测试身份
  （学号 `3260799999` / 姓名 `测试账号`，非管理员；凭据只写在交付说明，不入仓库）；`class_members` 已过滤该身份，
  班级名单仍 70 人、名单选择器/统计不出现它；审核员用正常「学号+姓名」身份页登录即可。
  迁移/回滚：`web/deploy/cloudbase/2026-11-05_test_account.sql`（审核结束删行即收回登录，SQL 见文件末尾注释）。
- 回归：unit **147/147**、sync_contract **29/29**、staticcheck exit 0、cache_perf 16/16、`cli auto-preview` 通过；
  最终包体 **667,382 B 单主包**（移除 demo 前 682,809 B）；版本仍 **2.0.0**；AI 开发模式仍 off（`ai/` 源码保留）。
- QA 增量验收：源码扫描 demo/演示/审核用 **0 处**；测试身份 7/7 PASS（可登录、名单 70 且不含、可只读班级数据）。

## 2026-11-05 19:45 · **v2.0.0** 全班体验升级（网页已上线 / 小程序源码 2.0.0 待上传发布）

> 用户 16 条需求整体交付。版本号 **全站 2.0.0**（网页 `APP_VER`、小程序 `utils/version.js`），
> 在用户下一次成功上传发布前不再改版本号。规格与逐项验收见 `_v2_plan.md`（过程文件，已删）、
> `tools/tests/v2_*.py`、`tools/tests/_qa_v2/REPORT.md`、`mp-class-tools/CHANGELOG.md`。

### 需求逐项（1–16）

1. **版本 2.0.0**：网页 `APP_VER="2.0.0"`（身份页页脚 + 使用说明页底部）；小程序 `utils/version.js` 唯一来源 → `app.js globalData.version` → 「我的」页页脚 `班级工具 · v2.0.0`。
2. **刷新保位**：网页 `sessionStorage zq_pos_v1` 恢复「当前 tab + 滚动位置」（按 sid 隔离、退出清空、首次访问仍落工具栏第一格；通知 20,000px 大页面冷启动/弱网等待上限 6s，`class-notice-height` 变化即重试；用户滚动/触摸/按键即取消恢复）。小程序 `utils/scrollmem.js` 接入 17 页（纵向 + tt/fttable 内部横向 scroll-view）。
3. **小程序课表滑动修复**：第 9 周周末有课时 `days=6 → _gridOverflow=true` 导致周视图整周禁滑。改为 `bindscroll` 跟踪横向位置 + `_gridAtEdge`：仅在横滑方向已到边缘时切周，否则让表格滚动；首/尾周阻尼、多指/动画保护保留。unit 7b 重写 + automator 真触摸 16/16。
4. **网页通知页滑动**：根因是「固定视口 iframe 内部滚动」在微信/QQ WebView 不可靠。改为**父页滚动 + iframe 自适应内容高度**（消费模板 `class-notice-height`，测量 `.wrap` 实际高度避免 scrollHeight 棘轮）；iframe 上纵向手势转父页滚动、横向手势转父页跟手/飞出切工具；磨砂弹层保留在父页；模板 fixed toast 桥接父页 toast。
5. **页面滑动卡住/异常**：`bodyLockAudit()` 覆盖切页/重建 iframe/关弹层/回前台，`nt-modal-open`/`rst-lock`/`id-locked` 不再残留；`fly()` try/catch + 620ms 兜底解锁（回调抛错不再永久吞手势）；touchmove rAF 化、工具栏几何起手缓存；斜向手势不劫持纵向滚动；`suppressClick` 只在真正换页/换周后抑制。
6. **通知识别**：①`#接龙`/接龙消息采集端确定性过滤（41→9 条 triage notices，旧接龙卡 archived/兜底剔除）；②新增**补充通知**识别与合并能力（ai_triage 输出 supplements → builder 合并：追加 `补充通知` item + 修正 deadline/eventAt/expireAt/timeLabel/summary + `updatedAt`）；③人工补丁 `data/notice-manual-patches.json`（builder 最后应用、重建不丢）落地药膳：报名时间 11-05 → **11-07 12:00—18:00**（deadline 11-07 18:00、eventAt 11-07 12:00、timeLabel 报名 11-07 12:00、补入 12:37 补充通知原文、updatedAt 11-05 12:37）。
7. **QQ 文件缺失/补抓**：file item 无 url → 前端「待获取」徽标 + 点击提示「前往 QQ 群『<群名>』查看，下载后自动上线」（网页/小程序一致，可复制群名）；`fetch_qq_files.import_downloads()` 扩展扫描 `~/Downloads`（含 Docs/）＋ QQ/微信下载目录、支持 pdf/xlsx/xls/docx/doc/pptx/ppt/zip/csv、文件名宽容匹配；watcher 每轮轻量导入 + `data/qq-files` 目录签名触发重建；已手动下载的 3 个文件（培养方案 docx / 军训场地 xls / 花名册 xls）自动内嵌上线，其余 5 个保持待获取。
8. **AI 摘要**：取消 3 条分点限制（1–6 条，由 AI 判断）；要点改为**关键词/短句、每条 ≤12 字**；`attach_ai` 不再 `points[:3]`；40 组全部重生成（178 条要点，单条 ≤12 字）。
9. **长期重复安排**：通知 JSON 新增 `recurrence`（freq/weekday/weeks/time/startAt/label），模板/小程序本地计算「下次」；`g_dorm` 宿舍卫生检查 = `每月前三周 周三 17:30`（下次 11-11 周三 17:30），`actionable=false` 不计入待处理、不按 deadline 判过期。
10. **小程序审核**（**已被 20:25 增量移除/替代，见顶部增量条目**）：原交付为「演示模式（审核用）」；用户 20:07 要求删除，改为云端测试身份（`is_test`，见增量条目 B），除“添加账号”外不保留任何审核相关功能；**AI 开发模式仍 `--off`**（app.json 无 agent/subPackages，`ai/` 源码保留，发版后可 `ai_toggle.py --on` 恢复）；提审注意项见 HANDOFF §31 / mp README。
11. **小程序工作台浮动轮换**：作业/通知两卡同时展示；卡内「最新一条」每 5s 轮换（上浮淡出→下浮淡入）+ 卡片轻微常驻浮动；页面隐藏暂停、≤1 条不轮换、reduced-motion 降级；局部 setData 不整页刷新。
12. **管理员通知编辑/删除**：云端 `notices` 新增 `override_json/hidden/edited_at/edited_by`（迁移 `deploy/cloudbase/2026-11-05_notice_admin_override.sql` 已应用）；前端解析套用 override、过滤 hidden（管理员可「已隐藏」恢复）；网页父页磨砂弹层编辑表单 + iframe postMessage 契约 `class-notice-edit/hide/restore` → `PATCH notices?id=eq.auto_<gid>`（成功才更新本地/IDB/iframe）；小程序卡片「编辑/删除」+ 已隐藏筛选恢复；签名扩展 `select=id,ts,hidden,edited_at`（旧协议自动回退）；采集重建只 PATCH body/audience 等，**不覆盖**这 4 列。
13. **全局动效**：CSS token `--ui-dur .26s` / `--ui-ease cubic-bezier(.2,.8,.3,1)` 统一切页/步骤/弹层/卡片/工具栏；通知卡展开/收起高度过渡（不再整页重渲染）；列表入场；`prefers-reduced-motion` 全量降级。
14. **体测男女/年级同步**：userdata v6 `fit` section 双端确认含 `sex/grade`；网页远端应用即刷新 radio/select；小程序补 `pages/fttable` 缺口——国标表页选择写回 `store.fit` + `store.save()`（触发同步）、主 ft 页 onShow 重新读取；两端往返测试。
15. **性能**：touchmove 计算 rAF 化、工具栏几何缓存避免强制 reflow、滚动位置 rAF+节流保存、通知 iframe 重建去重、marks 无变化不重复渲染、IDB 未 hydrate 不白拉 ~2MB；小程序 setData 局部更新、轮换计时器节流、图片懒加载。
16. **通知/作业状态同步修复**：`marks` 真源不变（`ntdone`/`hw`）；`markPend` 去重 + 待补发 overlay（云端旧状态不冲掉本地刚点勾选）；回前台（visibilitychange）/切页（hw/nt/roll）/刷新强制拉一次 marks（5s 防抖）；拉取成功自动补发 pending；通知列表/作业列表/简报计数随 marks 刷新；小程序 app.onShow + hw/nt/index 强拉 marksPull(true) + notifyPages 重绘。

### 数据侧（briefdesk）

- `ai_triage.py`：接龙过滤 + supplements 识别 + AI 年份自动修正；`ai_brief.py`：points 1–6/≤12 字 + `recurrence` + 缓存 v4/稳定 hash；`sync_notices_cloud.py`：白名单加 `recurrence/updatedAt`、不碰管理员 4 列；`detect_docs.py`：qq-files 签名 + 每轮轻量导入；`fetch_qq_files.py` 重写 + `qq_file_names.py`（新）；`fetch_qq_file_notices.py` 窗口 7→10 天；`build_notice_board.py`：supplements/人工补丁/接龙兜底/qq_file_uri 1.5MB/长期安排/文件待获取/管理员 UI/动画；新增 `test_supplements.py`（16 项）。
- 产物：`board-data.json` 40 组 / 2.33MB、`ai-briefs.json` 40 组、`ai-triage-notices.json` 9 条、`qq-file-notices.json` 7 条、`notice-manual-patches.json`、`web/tools/notice-board-live-demo.html`（2.51MB）。备份 `C:\briefdesk\data\_backup_v2_20261105\`。
- 云端 `public.notices`：40 组生效（旧接龙/寝室汇报 5 行 archived），总 body ~2.39MB。

### 验收与上线（网页）

- **网页门禁全绿（最终字节 448,812 B 上复跑）**：既有 7 条 roster 199/199、reset 109/109、perf 123/123、sync 117/117、committee 14/14、overflow 430=0、export ok；新增 7 条 **v2_scroll 35/35、v2_admin 39/39、v2_sync 35/35、v2_ui 27/27、v2_notice_data 27/27、v2_notice_live 16/16、v2_pos_restore 10/10**（含真实 40 卡 20,000px 通知页 scrollY=8000 冷启动弱网恢复 4.13s → 8000、wheel 取消）。
- 独立 QA（fresh context）：`tools/tests/_qa_v2/` 脚手架 + 基线审计 + 终验报告 REPORT.md（另见本文件末尾「v2.0.0 终验」）。
- **线上**：`index.html` **448,812 B · sha256 `2253e5e4dcdd38b7a9254bacf44d6ead6b80120cdf6dbe84588ac38be4eac3ff`**（本地=线上逐字节 MATCH）。
- **回滚**：重传 `tools/_backup/index_online_20261105-1925_preV2.html`（385,138 B · `b30fbf91…`）；无需回滚云数据（新增 4 列对旧前端无影响、旧签名 `select=id,ts` 仍可用）；云端如需回滚按迁移文件末尾注释。
- **briefdesk watcher 已恢复**（watchdog 暂停文件已删、detect_docs 运行中；恢复后 2 轮无异常重建）。

### 小程序发布（待用户上传）

- 源码已冻结：unit 152/152、sync_contract 29/29、staticcheck exit 0、v2_preview 18/18、tt_swipe automator 16/16、AI 三件套（off 前）全绿；`cli auto-preview` 编译通过 **TOTAL 682,809 B（单主包，AI off）**。
- 提审前：`python mp-class-tools-tests\ai_toggle.py --off`（已执行，app.json 当前即发版状态）；后台「用户隐私保护指引」声明「姓名+学号仅用于班级身份校验」；确认 appid `wx3df9869d229b96c4`、urlCheck 与后台域名；发版后如需 AI 适配：`ai_toggle.py --on` 后重新上传。
- 已知风险：通知超长卡片展开/收起用 max-height(4000rpx) 过渡，收起首帧可能略跳；真机 Canvas 2D 导出/订阅消息模板需发布前复核；tt.json 随教务同步变化，滑动回归已改为动态定位 6/7 天的周。

## 2026-11-05 · 导出图片 v2「清爽分享卡」（网页 + 小程序，同版式，网页已上线）

- 用户要求：**优化网站和微信所有导出图片的显示效果**。
- **设计方案**：导出卡 v2（规格 `tools/tests/export_card_v2_spec.md`，网页/小程序共用版式）——
  760 逻辑宽 / DPR2；暖白渐变底 + 圆角主卡 + 柔和投影；左上渐变装饰条 + 三色圆点品牌行；
  标题 30px 自适应降号截断；参数配置 tinted 面板（自动两列 / 单列，单列长标签列宽按实测自适应 110–186）；
  区块标题方块；内容块三种（`text` 兼容 string / rich runs / mono、`chips` 抽签结果胶囊、`groups` 分组两列组卡）；
  页脚生成时间 + 唯一编号 + 品牌三色点；斜向水印**裁剪在卡内**（alpha 0.03，不再出现卡片外的半截字）；
  抽签剔除记录改为「通栏面板：标题 + 文字明细 + 二维码」；`wrap()` 增加行首标点禁则。
- **网页实现**（`tools/index.html`）：重写 `exportCard()`（`EXPC` 调色板/版式，约 2724 行起）；新增 `chips/groups`
  块与 `qrNote`；抽签 / 分组 / 结果单入口改新 blocks API（结果单新增 `xblocks`，页面展示与复制逻辑不动）；
  课表 / 作业 / 体测沿用文本块自动适配；`tools/tests/export_check.py` 增加 `drawqr` 变体与 `EXPORT_SRC/EXPORT_OUT`
  环境变量（可用任意副本/回滚版复盘）。
- **小程序实现**（`mp-class-tools`，v22 / 1.5.1，详见其 CHANGELOG）：`utils/canvas.js` 逐像素同版式（暖色板 +
  「班级工具站」品牌、无二维码块）；`pages/draw|group|sum` 改 chips/groups；`hw|tt|ft` 不动；`unit.js` 108/108、
  `staticcheck.py` exit 0；6 类成图 `mp-class-tools-tests/_shots/export/mp_*.png`。
- **验证（网页）**：`export_check` 6 类 + `drawqr` + 三个 roster 变体全部落盘（1520 宽）；`sync_check 117/117`、
  `perf_check 123/123`、`reset_check 109/109`、`roster_check 199/199`、`committee_check 14/14`、
  `overflow_check.py 430` overflowCount=0；独立 QA（fresh context）**20/20 PASS，0 FAIL**，报告
  `tools/tests/_qa_export/QA_web_export_v2.md`（含逐张肉眼 + canvas 调用级 + 像素级检查、回归与隐私扫描）。
- **验证（小程序）**：独立 QA **24/24 PASS，0 FAIL**，报告 `mp-class-tools-tests/_qa_export/QA_mp_export_v2.md`；
  与网页参考图同内容下 H（474/588/710）与头部/参数/区块/页脚锚点逐项一致，仅色板/品牌/无二维码三处允许差异。
- **上线（14:1x）**：线上 `index.html` **385,138 B · sha256 `b30fbf91eba714cb…1fedbc`**（与本地逐字节 MATCH）；
  回滚：`tools/_backup/index_online_20261105-1405_preExportV2.html`（374,183 B · `b0bbd710…`，重传即回到改动前）。
- 备注：小程序需在微信开发者工具上传 + 审核发布；真机 Canvas 2D（shadow / clip / linearGradient）发版前再复核。
  已知低优先级：结果单文件名仍无 `_关键参数` 段（历史行为）；超长单行文本的折行断点按字符贪心（仅观感）。

## 2026-11-04 · 抽签页补回「重置」按钮（网页，已上线）

- 用户反馈：抽签功能的重置按钮不见了。
- **核查结论**：网页版抽签页**从未有过**「重置」按钮 —— 逐份核对 `tools/_backup/` 全部 50 份线上备份（2026-10-11 08:20 → 2026-11-04 22:34），抽签页只有「开始抽签 / 排序 / 导出 / 下一步」，全站唯一的「重置」是点名页「重置本轮」。该按钮实际存在于**微信小程序**抽签页底部操作条（`pages/draw/draw.wxml` 的 `bindtap="reset"`）。本次按小程序语义在网页版补回，两端行为对齐。
- **实现**（`tools/index.html`）：
  - STEP1 参数卡片操作行：「开始抽签」右侧新增 `<button class="btn ghost" id="aReset" type="button">重置</button>`（与 `#aRun` 同一 `.row`，可点高度 40px+）。
  - 点击逻辑：无抽签/分组结果 → toast「本轮还没有抽签结果」且不弹确认；有结果 → `confirm("重置本轮抽签？将清空抽签结果与分组结果（参数与名单保留）")`；确定后清空 `A.result/A.cfg/A.log/A.removed/A.pool` 与 `G.result/G.cfg`，`renderA();renderG();renderSum();` → `#aOut`（—）/`#aSortRow`·`#aNextRow` 隐藏/`#gOut`（—）/`#sOut`（—），toast「已重置抽签与分组」；抽签参数（`D.d.draw`）与参与名单（`rosterSel`/`groupSel`）保留。
  - 使用说明「抽签」新增：「点「重置」清空本轮抽签与分组结果，参数和参与名单保留。」
- **验证**：新增专项 `tools/tests/reset_check.py`（假身份 + iframe 固定宽度 + headless Edge，支持 `RESET_SRC` 指定任意副本复盘）**109/109 PASS**：按钮 DOM/位置/可点高度、无结果提示、取消保留、确定清空（抽签/剔除记录/分组/结果单）、参数与名单保留、仅分组状态也能重置、0 JS 报错 / 0 console.error / 无外部请求、360/390/430/720/1280 无横向溢出；截图 `tools/tests/_shots_reset/`（390/1280 × 抽签后·重置后）。回归：`roster_check.py` **199/199 PASS**、`overflow_check.py 430` overflowCount=0、`export_check.py draw` 落盘正常。**对线上字节（339,436 B）复跑 `reset_check.py`：109/109 PASS**。
- **独立验收**（另一 agent，fresh context，`tools/tests/_reset_verify/`）：**验收项 151/151 PASS、过程项 2/2 PASS、0 FAIL**（静态 10 + 功能语义 42 + 仅分组 14 + 5 档宽度 65 + 截图 16 + 人工读图 2；起止 sha256 一致证明验收期间未被并发改动）。报告 `tools/tests/_reset_verify/report.json`。唯一无害观察：`#aOut` 的 `data-log` 属性重置后未 remove（全文件只写不读、不可见）。
- **上线（22:50，随并行会话的统计页部署一起上线）**：线上 `index.html` **339,436 B** · sha256 `d5f96b9e46bd29a63dbdee3e2b116101637373dd8e02dd26202ac0e869fbd4de`，含 `#aReset` / 「本轮还没有抽签结果」；与并行会话的「统计页显示优化 + 全站去除学号」共存。回滚：`tools/_backup/index_online_20261104-2250_preNoSidStats.html`（336,035 B，重传即回到本次改动前的线上）。

## 2026-11-04 · 统计页显示优化 + 全站去除学号（已上线）

- 用户要求：网页同样去掉所有学号（不打码、直接不显示）；优化统计功能显示。
- **学号清理**：
  - 班委名单：去掉姓名后的打码学号（删 `.cmsid` 展示 + `maskSid()` 函数）；
  - 反馈列表（管理员）：由显示学号改为按姓名（新增 `memberNameBySid()`，匹配不到显示「（未知成员）」）；
  - 统计页：不再显示学号/尾号；`D.d.verify` 不再写 `sidMask`；工具描述改「按姓名统计访问（不显示学号）」；
  - 使用说明：「按学号同步」改为「按账号同步」，并注明页面只显示姓名与角色、不显示学号。
- **统计显示优化**：
  - 卡片结构：标题 + 「仅管理员 · 按姓名聚合，不显示学号」+ 今天 / 近 7 天切换 + 三格摘要（访问账号 / 访问次数 / 今日活跃）+ 排行列表 + 底部口径说明；
  - 列表：名次徽章 + 姓名（前三名高亮）+ 最近访问时间（近 7 天另显示「活跃 N/7 天」）+ 次数占比条 + 次数；
  - 桌面 ≥720px 名称列 120–240px、条形自适应，宽屏一屏可读；空态/加载态保留。
- **验证**：`roster_check.py` **199/199 PASS**、`overflow_check.py 430` overflowCount=0、`export_check.py draw` 落盘 206,970 B；自建假数据（不碰真实云）390/430/1280 截图，统计页 `rows=10 / errs=0 / scrollWidth==innerWidth / noSID`（今天 + 近 7 天）；线上 sha256 与本地一致；线上含 `stSum` / `memberNameBySid`，`cmsid` / `maskSid` 均为 0。
- **线上**：339,436 B · sha256 `d5f96b9e46bd29a6…`；回滚 `tools/_backup/index_online_20261104-2250_preNoSidStats.html`（336,035 B，直接重传）。
- 备注：与并行会话的名单/通知改动共存（线上仍含 `选择名单`/`rosterModal`/`idgate`，未受影响）。

## 2026-11-04 · 名单气泡视觉简化（更贴合整站风格，已上线）

- 用户反馈：名单的「液态糖果风」太花，要求「优化名字的 UI 效果，使其更简约并符合整个网页的风格」。
- **选择器气泡**（`#rosterModal` 内 `.rst-b`）改回整站 option chip 语言：
  - 未选：`#FFFCF6` 底 + 1px `var(--line)` 暖沙边 + `var(--ink2)` 字，13.5px/600、min-height 40px、padding 8px 13px。
  - 已选：`#F1F7F5` 浅青底 + `var(--cy)` teal 边/字（font-weight 700，对齐 `.steps button.on`）。
  - hover `#F2F5F4` / 已选 hover `#E9F3F0`；press 仅 `scale(.985)`；transition 130ms；focus-visible 2px teal outline；座号 10.5px、opacity .45（已选 .65）、间隔 4px。
- **页面摘要** `.rchip` 改为小号已选标签：`#F1F7F5` 底 + `#CFE3DD` 边 + teal 字（12px/600、padding 3px 9px），`+N` 虚线透明幽灵，空态灰字保留；去掉全部 animation。
- **清理**：删除 `rstFloat`/`rstPop`/`rsumFloat` keyframes、`.rst-b::before` 玻璃高光、渐变/内阴影/box-shadow 光泽、`--i` 错峰延迟、JS 按压/弹跳逻辑；`prefers-reduced-motion` 段精简为仅关闭弹层入场动画与过渡。
- 验证：`tools/tests/roster_check.py` 视觉断言改为新规格（平铺实底、无渐变、无伪元素高光、`animation-name:none`、已选=浅青底+teal 边/字、座号 10.5px/opacity .45/间隔 4px），**199/199 PASS**；截图更新 `tools/tests/_shots_roster/`（390/1280 × all·mixed·none + 390 摘要，合成姓名「同学01–70」）。
- **上线（22:34）**：线上 `index.html` **336,035 B** · sha256 `c626698f…7e1e1b3`；与线上最新的通知磨砂弹层 / 通知模板（`NOTICE_TPL_B64` = `37a51a1a`）共存，名单简化样式已生效。已对**线上字节**复跑 `roster_check.py`：**199/199 PASS**（0 JS 报错）。回滚：旧视觉版可重传 `tools/_backup/index_online_20261104-223112_preTemplateUpdate.html`（342,576 B）；本次上线后基线备份 `tools/_backup/index_online_20261104-2233_simpleRoster.html`。

## 2026-11-04 · 通知弹层背景改为「原页面磨砂变暗」

- 用户反馈：点开通知弹层后背景是纯色页面填充，希望是原页面的磨砂变暗。
- **实现**：通知 iframe 的 `openImg / openFile / openOriginal` 改走 `presentModal()`——嵌入网页时把弹层内容 HTML 通过 `postMessage` 交给父页面；父页新增 `#ntModal` 全屏蒙层（`backdrop-filter:blur(7px)` + `rgba(40,50,42,.34)`）盖在原页面之上，卡片在父页渲染（支持原始消息 / 图片 / 文件预览）。
- **iframe 不再被拉全屏**：去掉旧的 `.notice-host.modal-open iframe{position:fixed;…}` 与模板里的全屏轮询；弹层打开时原页面（工具栏 + 通知列表）保持原位，只做模糊 + 压暗。
- **交互**：点 × / 点暗层 / Esc 关闭，焦点回到触发处；单独打开 `notice-board-live-demo.html` 时仍用内置弹层。
- 相关文件：`web/tools/index.html`（父页弹层 DOM/CSS/JS）、`briefdesk-plan/build_notice_board.py`（模板 `presentModal/closeModal`，移除旧轮询与 `.modal-on` 隐藏逻辑）。
- 验证：390/1280 弹层打开后 iframe 保持 `static`（362×1060 / 1188×750），overlay 计算值 `blur(7px)`、关闭后 class/内容清空；主页面冒烟 0 JS 报错、overflow=0；线上 `index.html` sha256 MATCH（338,372 B，sha `aa6f39ee…`）。
- 回滚点：`tools/_backup/index_online_20261104-2226_preFrostModal.html`。

## 2026-11-04 · 名单改为班级名单选择器 + 液态气泡（web 端，已上线）

- **名单不再支持自定义**：抽签 STEP1 的「名单对应」textarea / 粘贴 / 清空 / 导入班级名单 / 更新云端名单，分组 STEP2 的「粘贴名单」textarea，点名的「名单」textarea 与「导入班级名单」按钮全部移除。三处统一改为「已选名单气泡摘要 + 选择名单按钮」（抽签额外保留「清空」）；摘要为空显示灰字「未选择」，点摘要气泡可重新打开弹层。
- **全局单例名单弹层**：draw / group / roll 复用同一个 DOM（`#rosterModal`），标题分别「选择抽签名单 / 选择分组名单 / 选择点名名单」；成员来自 `D.d.members`（`rpc/class_members`，座号 1–70）。移动端（≤600px）底部弹层、桌面居中卡片（520px）；点气泡切换、全选 / 清空 / 取消 / 确定、计数「已选 N / 70」；Esc / 遮罩 = 取消，取消不写回；键盘可达（`<button>` + 回车/空格 + focus-visible）。
- **液态气泡（方案 C，干净无瑕疵）**：不透明奶白 / 睡莲青渐变气泡 + `::before` 玻璃高光 + 暖沙描边 + 内阴影；错峰浮动、按压果冻（scale .93）、选中 pop、页面摘要气泡轻浮动；文字永不被滤镜影响；`prefers-reduced-motion: reduce` 全部关闭动画。手机优先、各级宽度无横向溢出。
- **数据模型**：新增 `D.d.rosterSel / groupSel / rollSel`（座号数组，1–70 去重升序）与 `rosterMigrated` 迁移标记；选择变化写派生文本兼容旧算法：draw → `D.d.roster = "座号 名字\n…"`，group → `D.d.group.names = "名字\n…"`，roll → `D.d.rollNames = "座号 名字\n…"`。
- **旧数据迁移（一次性、幂等，members 可用后执行）**：旧文本名单逐行取姓名与班级成员精确匹配 → 座号；行内序号与该座号成员姓名一致也接受；匹配不到的姓名丢弃。`group.names` 同理；点名旧 `rollNames` + `rollSt` 按姓名保留「到/假」状态、按座号升序重建并重排索引；`classRoster` 不再使用（字段保留、迁移时清空）。
- **抽签语义**：未选名单 = 只抽序号（旧行为）；选了名单 = 抽签池 = 所选座号 ∩ 范围 − 排除，结果必带姓名；池为空 / 人数不够有明确 toast；名单行提示「已选 N 人 · 抽签池 M」，导出参数为「参与名单（N 人）」。分组来源文案改「选择名单」、未选择时 toast「请先选择名单」；点名保留「沿用抽签名单」。
- 使用说明（名单 / 分组 / 点名）文案同步更新。
- 验证：`tests/roster_check.py` **199/199 PASS**（注入假身份 + 合成 70 人「同学01–70」+ 旧自定义名单；弹层 70 气泡、0/70→70/70、确定写回、页面摘要、抽签 10 个全带姓名、只选 3 人抽签池=3 与超池提示、分组 5 人、点名状态迁移、360/390/430/720/1280 无横向溢出、`prefers-reduced-motion`、0 JS 报错）；截图见 `tools/tests/_shots_roster/`；`tests/overflow_check.py 430` → `overflowCount=0`；`tests/export_check.py draw` 落盘 PNG 正常（已给该脚本注入假身份）。
- 注意：`tests/selfcheck.py` / `shots.py` / `overflow_check.py` 仍是身份门禁前脚本，本次专项以 `roster_check.py` 为准。
- **独立验收**（另一 agent）：`tests/roster_check_verify.py` 157/157 PASS；交叉复跑 `roster_check.py` 199/199 PASS；360–1280 无横向溢出、0 JS 报错、身份门禁未通过时 0 次班级数据请求。
- **线上部署（22:13）**：<https://tool.furina.fun/> 已上线；本次混合上传 `index.html` **333,218 B**，sha256 `cd4a7c40…53baa`（与自检所用版本逐字节一致）。采用「部署前线上版 + 本次名单改动」合成（保留当时线上旧通知模板 `cfa4ca2c`），不把并行会话尚未上线的通知模板带上线。
- **并行合并后现状（22:20）**：另一会话随后把新通知模板（`3d4ac9a0`，发布人 / OCR 等）基于实时线上版合并上线，名单功能被完整保留；线上现为 **339,237 B**，sha256 `b88c9be1…90bea0`。已对**线上字节**复跑 `roster_check.py`：**199/199 PASS**（0 JS 报错，弹层 / 抽签 / 分组 / 点名 / 迁移全绿）。
- 回滚点：`tools/_backup/index_online_20261104-2203_preRoster.html`（部署前线上原样，318,512 B）；本地改动前版 `tools/_backup/index_local_20261104-2132_preRoster.html`。

## 2026-11-04 · 通知弹层背景修复 + 截止时间误判修复

- **弹层不再拉宽整页**：通知 iframe 内弹层打开时父页仍会把 iframe 拉成全屏以铺满暗层，但模板新增 `body.modal-on .wrap{visibility:hidden}`，被拉宽的通知列表不再露出（之前能看到被拉伸的整页卡片）；关闭后恢复。`build_notice_board.py` 模板里 `modal-on` 类与 `open/close` 同步。
- **「运动会期间晚自习正常」不再显示截止时间**：
  - 根因：`classify_qq_text.py` 给所有 QQ 文本通知兜底写 `expireAt = 创建时间+7天(23:59)`，而通知模板 `statusOf()` 用 `expireAt` 当截止时间显示 → 该消息被显示成 `11-11 23:59 截止`；AI 侧其实已正确返回 `deadline=null`。
  - 修复①（数据口径）：`classify_qq_text.make_group` 只有存在截止/活动时间才写 `expireAt`（无时间 → 不写）；`build_notice_board.load_qq_text` 兼容清理旧数据（`eventAt` 等于发送时间视为占位、丢弃；无时间通知不带 `expireAt/timeLabel`），并在 `main()` 里统一兜底。
  - 修复②（模板口径）：`statusOf()` 重写——有截止按真实截止（含延期）判断/显示；只有活动时间按活动结束判断；两者都没有显示「无时间」，**不再拿 `expireAt` 当截止**；`stats()` / `briefNext()` 的 24h/7天统计与文案同步改用真实截止。
  - 数据侧已重建 `board-data.json` / `notice-board-live-demo.html` 并同步 CloudBase（20/20 行，`auto_g_qqtext_77a2abbbf7` 的 `deadline/eventAt/expireAt/timeLabel` 均为 null）。
- 验证：mock 全量 20 组通知审计——运动会通知显示「无时间」、药膳显示「报名 11-05 12:00」、事件已结束显示「已结束 · 自动归档」、真截止显示具体时间；390/1280 弹层打开为干净暗层、关闭后恢复静态 iframe；0 JS 报错；overflow=0；线上 `index.html` sha256 MATCH（318,512 B，仅替换内嵌通知模板）。
- 备注：本次线上只带通知模板改动（以当时线上版 + 新模板上传）；工作区 `index.html` 同时含并行会话的「名单选择」改动，未由本次上线。
- 回滚点：`tools/_backup/index_online_20261104-2151_preNoticeModalTime.html`。

## 2026-11-04 · 打开网页默认停在工具栏第一格

- 用户自定义工具栏顺序后，打开/刷新网页仍停在固定的「抽签」，与工具栏第一个不一致。
- 新增 `LANDING` 标记：身份通过后首次 `renderTabs()` 把 `CURTAB` 设为 `home[0]`（工具栏第一个，含自定义顺序；横屏 4 工具 / 竖屏 3 工具按当前可见槽位取），消费一次；之后切 tab、拖拽换栏、旋转屏 `renderTabs()` 都不会重置。
- 未通过身份门禁前的 resize 不消费该标记，避免门禁期间改窗口导致落地错误。
- 验证：默认顺序 → 抽签（不变）；自定义 `[课表,通知,抽签,作业]` 竖屏落在课表且第一格高亮；1280 横屏自定义落在通知；360 自定义落在作业；点 tab / resize 后保持当前页；全部栏正常；0 JS 报错；线上 `index.html` **sha256 MATCH**（317,216 B）。
- 回滚点：`tools/_backup/index_online_20261104-2107_preLandingFirstTab.html`。

## 2026-11-04 · 手机标题栏减负 + 卡片/框浮起

- **手机比例顶部栏（≤600px）**：隐藏装饰三色点与身份角标（副团支书等角标只在宽屏显示），身份胶囊限宽 7.4em、不换行、字号 11.5；域名降到 10px；标题加大 17px/800。顶部内边距接入 `env(safe-area-inset-top)`，吸顶 tabs 也留出安全区。>600px 的桌面/横屏布局保持原样。
- **卡片与框浮起**：卡片底改暖白 `#FFFFFF`、描边 `#E0D2BC`、柔和投影（`0 1px 2px` + `0 12px 26px -14px`）；内层的「结果框 / 作业·反馈条目」改浅沙 `#FBF6EC` 做出「外浮内陷」层次；输入框/多行框改 `#FDFAF2` + 深一档描边并加内阴影；`.ck`、`.steps` 按钮同步；吸顶 tabs 加柔和投影。
- **通知 iframe 同步**：`build_notice_embed.py` 的 `OVERRIDE` 改为白卡 + 同等投影 + 浅沙内框，重新嵌入 `NOTICE_TPL_B64`（模板与旧版逐行 diff 仅 OVERRIDE 区 15 行；demo 与旧模板逐字节一致）。
- 验证：真宽度 320/360/390/430/601/720/844/1280 全部 `overflow=0`、0 JS 报错、全部栏按钮底差 0px；手机 320–430 身份名不截断（管理员）且角标/点隐藏，601+ 恢复完整；通知页 390/1280 内嵌模板卡片渲染正常；draw 导出正常；线上 `index.html` **sha256 MATCH**（316,967 B）。
- 回滚点：`tools/_backup/index_online_20261104-2058_preMobileTopCard.html`。

## 2026-11-04 · 全部栏卡片莫奈配色 + 按钮底部对齐

- **卡片配色统一到莫奈系**：「全部」页卡片底色改 `#FFFCF6`、描边 `#E7DED0`；页眉按工具族着色（课表雾蓝 `#EDF2F7`、作业/反馈睡莲青 `#EAF2EC`、抽签/体测暖沙 `#FAF3E6`、班委/点名/统计紫 `#F1EEF7`、通知灰粉 `#F7EDEB`、使用说明中性 `#F3F1E9`）；「打开」按钮跟随卡片色，「设为首页」保持描边幽灵样式；描述文字 `#6E7A72` 提高可读性。
- **按钮底部对齐**：卡片改纵向 flex，`.bd` 撑满、按钮行 `margin-top:auto`，同一行卡片高度一致时按钮贴底对齐（修复点名/反馈等卡片按钮高低不齐）。
- 「全部」卡片色调映射在 `renderAllCards()` 的 `ALL_TONE`；分组结果卡（`.gcard` 非 `.tool`）不受影响。
- 验证：真宽度 360/430/720/1280（管理员 10 卡 / 普通 9 卡）全部页 `overflow=0`、同行按钮底差 0px、逐卡点击打开对应页、0 JS 报错；draw 导出图参数/水印/时间/编号正常；线上 `index.html` **sha256 MATCH**。
- 已知：`tests/selfcheck.py` 仍是身份门禁重构前的旧脚本（HANDOFF §11 已注明），本次以「全部栏专项审计」替代 ①，②③④ 照跑。
- 回滚点：`tools/_backup/index_online_20261104-2040_preAllCardColor.html`。

## 2026-11-04 · 身份门禁重构：学号+姓名进入 + 班委/账号统计

- **旧登录全部移除**：网页不再有账号/密码/注册/旧管理员入口，`users`/`identity_verify` 旧登录表已从 CloudBase 删除；管理员身份改由班级名单中的 `is_admin` 决定（管理员 / 2024000001）。
- **启动身份页**：网页打开先显示身份门禁，输入「学号 + 姓名」→ `rpc/class_verify`；通过后才拉取班级名单（70 人）、作业、通知、marks、体测与课表，未通过前不发任何班级数据请求。
- **新名单权威**：`private.class_ids` 重建为官方 XLS 花名册的 70 人；旧 `admin` 数据迁到 2024000001，旧 `xzx/xsx` 数据迁到同学M 2024000002。旧管理员 `admin` 不再可用。
- **班委名单**：新增「班委」工具页，展示 `role/badge` 身份气泡；已按《关于公布2026级班委会拟定结果的通知》导入 **18 名班委**（班长同学A、团支书同学M、副团支书管理员、学习/生活/纪律/文娱/劳动/体育/心理/组织/宣传/廉政监督员），按官方职务顺序展示；管理员仍可在班委页点「管理」调整。
- **统计改为按账号**：`visits` 新增 `sid/name`，前端埋点写当前身份；统计页只管理员可见，按账号聚合访问次数/最近时间/近 7 天，旧匿名行忽略。
- **CORS**：网页 token 走网关已放行的 `X-Device-Id` 头（服务端同时接受小程序的 `X-Class-Token`），修复 `X-Class-Token` 被浏览器预检拒绝的问题。
- 验证：线上输入管理员/2024000001 成功进入、名单 70 人、班委页 **18 条**、统计按账号、console errors 0；本地 identity/committee/stats 截图通过；未登录时数据接口返回空/拒绝。
- 已知限制：课表仍为同源静态 `tools/tt.json`（前端身份后请求）。
- 回滚点：`tools/_backup/index_online_20261104_1335.html`（身份改造前线上版本）。

## 2026-11-04 · 课表全员开放 + 横竖屏动态工具栏（横屏 5 格 / 竖屏 4 格）

- **课表正式上线**：移除 `tt` 的管理员限制，所有访客都能在「全部」看到课表，并可直接打开；横屏工具栏默认第 4 个工具即为「课表」。
- **工具栏随比例变化**：竖屏 = 3 工具 + 全部（4 格）；横屏（宽 > 高） = 4 工具 + 全部（5 格）；桌面浏览器拖动窗口比例、手机横竖屏切换都会自动重排。
- **自定义保存**：`homeTools` 保存最多 4 个工具槽位，横竖屏共享同一套自定义顺序；竖屏显示前 3 个、横屏显示全部 4 个，来回切换不丢设置。
- **液体重排动画**：比例切换时按钮用 FLIP 滑到新位置、新增按钮缩放淡入，工具栏整体做 `scaleX` 液态过渡，滑块弹性吸附；容器宽度也做了过渡。
- 验证：线上 1280×800 → 5 格（抽签/作业/通知/课表/全部）、700×1000 → 4 格（出现 `morph` 动画类）、再回横屏恢复 5 格；自定义 `homeTools` 始终保存 4 项；匿名（未登录非管理员）在全部页可见并打开课表；selfcheck PASS、430px overflow=0；线上 `index.html` **sha256 MATCH**（211,443 B）。
- 回滚点：`tools/_backup/index_online_20261104_1210.html`。

## 2026-11-04 · 课程详情按“本次点击的这一节”显示

- 周表 / 日视图 / 全部课程点击后，只显示**被点击这一节**的信息：授课教师、日期 + 周几 + 第几节 + 起止时间、教室；
- 新增「下次」：以本次点击的课为基准，显示这门课**下一节**的上课时间（日期 / 周几 / 节次 / 起止时间）；没有后续则显示「暂无后续课程」；
- 全部课程列表点击时没有具体节次，按“现在之后最近的一节”展示；
- 课程格与日视图卡片加了 `data-cid`，详情不再合并列出所有时段；
- 验证：线上点击 `C语言程序设计 · 11/3 周二 第1-2节`，详情为「张翠萍副教授 / 11/3 周二 第1-2节（08:10–09:40）/ 自强楼(教室01105) / 下次 11/24 周二 第1-2节」；selfcheck PASS、430px overflow=0；线上 `index.html` **sha256 MATCH**（209,152 B）。
- 回滚点：`tools/_backup/index_online_20261104_1150.html`。

## 2026-11-04 · 体测输入框滑动 / 课表按周滑动 / 手机教室信息

- **体测输入框区域可滑动**：不再把 `input / textarea` 排除在滑动手势外；横向滑动才拦截，点击输入框照常聚焦；滑动后自动收起焦点并抑制一次合成点击，不影响后续点击。仍只在体测位于工具栏时用于切工具（未在工具栏的工具按既有规则不切）。
- **课表滑动改为一周一周切换**：左右滑动切上一周 / 下一周（含日视图），到第 1 周/最大周回弹；周视图/日视图的切换只保留点击「周 / 日」。
- **手机周表教室可读**：窄列下教室显示短标识（如 `01105`、`02111`、`1-3`），完整教室名保留在 `title` 与课程详情；同时缩小课程块内边距，避免教室被裁掉。
- 验证：输入框点击聚焦 `fH`、在输入框上左滑 体测→抽签、滑动后焦点回 BODY、再点击 `fW` 正常聚焦；课表第 10 周左滑 → 第 11 周且视图保持周、点击「日」正常切日；线上手机周表教室显示 `01105/02111/01202/1-3/01203`；selfcheck PASS、430px overflow=0；线上 `index.html` **sha256 MATCH**（207,496 B）。
- 回滚点：`tools/_backup/index_online_20261104_1135.html`。

## 2026-11-04 · 工具栏滑块改为液体动效

- 顶部 tabs 滑块改为液体式：拖动时向右（目标 tab 方向）渐进移动并**横向拉伸**、轻微压扁，接近目标时收窄，松手用弹性曲线**吸附**到新 tab；取消则回弹原位。
- 滑块目标位置仍取工具栏实际 DOM 顺序（自定义排序同样有效）。
- 验证：线上 Headless 触摸实测——初始 94px/5px；拖 40px 时 124px/75px（拉伸+右移）；拖 140px 时 97px/99px（收窄接近目标）；松手后 94px/105px 且 active=hw；selfcheck PASS、430px overflow=0。
- 线上 `index.html` **sha256 MATCH**（206,445 B）；回滚点 `tools/_backup/index_online_20261104_1115.html`。

## 2026-11-04 · 滑动交互改版（跟手动画 + 按上下文切换）

- **跟手动画**：拖动时当前页面/步骤面板/课表内容跟着手指位移，松手后滑出、新内容从另一侧滑入并淡入；未过阈值则回弹。
- **切换规则按上下文**：
  - 顶部工具条：按**实际左右顺序**切工具（含用户自定义顺序），已不在工具栏上的工具不做工具切换；
  - 抽签内容：切 STEP 1/2/3；STEP1 右滑 / STEP3 左滑到边界才切到上/下一个工具；
  - 课表内容：切 **周 / 日**，不切工具；
  - 反馈 / 使用说明等非工具栏工具：内容滑动不切工具。
- **工具栏动画**：顶部 tabs 增加跟随滑块的白色药丸，拖动时随手指移动，切页时平滑滑到新位置。
- 防误触：输入框/文本域、可横向滚动的表格内不触发；滑动结束抑制一次合成点击，避免误开课程详情。
- 验证：selfcheck PASS、430px overflow=0；本地+线上触摸模拟：抽签拖动位移 -58.5px、STEP1→2、STEP3→作业、工具栏 作业→通知（滑块 5→204px）、课表 周→日（仍停留课表）、课表工具栏滑动不切页；线上 `index.html` **sha256 MATCH**（205,383 B）。
- 回滚点：`tools/_backup/index_online_20261104_1100.html`。

## 2026-11-04 · 左右滑动切换 + 日视图色条莫奈化

- **滑动切换**：顶部工具 tabs、抽签 STEP 1/2/3、课表周/日开关支持左右滑动；页面内容区滑动也可切换工具（从课表/反馈等「全部」进入的页面右滑回「全部」）。
- 横向可滚动区（周表 7 天、国标表）和输入框/文本域内不触发滑动，避免与滚动、输入冲突；5/6 天周表本身不滚动，可直接滑动切页。
- **日视图色条**：课程卡片左侧颜色条由深色强调色改为**莫奈浅色**（取课程色板浅色），宽度 6px，与周表色块观感一致。
- 验证：selfcheck PASS、430px overflow=0；线上 Headless 触摸模拟：hw→nt、STEP1→2、周→日、日视图色条 `#F1DDD9` / `#F0E5CD`（6px）；线上 `index.html` **sha256 MATCH**（198,857 B）。
- 回滚点：`tools/_backup/index_online_20261104_1025.html`。

## 2026-11-04 · 桌面端内容排布（多栏/侧栏，不只是拉宽）

- **课表**：桌面改为「周表主区 + 右侧信息栏」——下一节卡与「全部课程」放到侧栏，周表不再一味拉宽；当天课已上完/无下一节时自动切回单栏全宽（侧栏内容落到下方），避免右侧空白。
- **课表比例收紧**：桌面课表卡片最大宽度 1180px，天列宽上限 200px，课程名 14.5px / 教室 11.5px / 行高 72px（原为 16.5 / 12.5 / 84）；侧栏 260px。多栏排布不变，只是不再显得过大。
- **抽签**：STEP 1 配置在左、抽签结果在右；STEP 2 配置在左、分组结果在右；手机/平板仍为原来的上下单列。
- **体测**：录入表单在左、成绩与明细在右。
- **作业 / 通知**：宽屏列表改双栏；点名格子列数随宽度增加。
- 容器仍保留分级宽度，但页面结构随比例改变（侧栏/分栏/双栏），而不是单纯放大字号。
- 验证：selfcheck PASS、430px overflow=0、1280/1440 截图；线上实测：1280/1440/1920 课表卡片均为 1180px、课名 14.5px、行高 72px；抽签 617+559 双栏、体测 612+564 双栏；线上 `index.html` **sha256 MATCH**（196,505 B）。
- 回滚点：`tools/_backup/index_online_20261104_1005.html`。

## 2026-11-04 · 桌面端加宽（充分利用横向空间）

- 页面容器 `.wrap` 在 ≥960px 起逐步放宽：960→最多 1120、1280→最多 1320、1600→最多 1520px；手机/平板保持原 880 以内。桌面左右留白从 ~200px 降到 28–60px。
- 课表随列宽同步放大：天列宽最大 260px，课名 16.5px、教室 12.5px、行高 84px、间距 8px，教师行在宽列继续显示。
- 抽签 / 作业 / 通知 / 体测等其它工具同样使用更宽容器，桌面信息密度更高。
- 验证：selfcheck PASS、430px overflow=0、1280/1440 截图正常；线上 Headless 实测容器宽度 1000/1280/1920 = 952/1216/1520px，课表无横向溢出；线上 `index.html` **sha256 MATCH**（193,922 B）。
- 回滚点：`tools/_backup/index_online_20261104_0930.html`。

## 2026-11-04 · 课表响应式字号与排版（按设备比例自适应）

- 周表由实际“天列宽” `--dayw` 驱动：课名字号 clamp(10.5→15.5px)、教室 9→12px、行高 48→76px、单元格间距 3→7px；手机约 11px 课名，桌面/平板放大到 15.5px。
- 宽列（≥104px，平板/桌面）自动在教室下多显示**教师行**，手机隐藏；表头星期/日期/今日徽标、节次列、圆角与内边距同步缩放。
- 日视图、全部课程、课程详情、下一节卡均用 `clamp()+vw` 自适应；≥720px 加大卡片留白。
- 验证：selfcheck PASS、430px overflow=0、截图正常；线上 Headless 三档实测：430px（列宽 60.6 / 课名 11.2 / 行高 53）、768px（120.2 / 14.5 / 72，显示教师）、1280px（139.8 / 15.5 / 76，显示教师）；线上 `index.html` **sha256 MATCH**（193,592 B）。
- 回滚点：`tools/_backup/index_online_20261104_0920.html`。

## 2026-11-04 · 课表改为只读同步（当天课完隐藏下一节 / 全部课程合并收起）

- **下一节课**：当天课程全部上完后不再显示「下一节」（也不再把次日/下周课程当作下一节）；正在上课时仍显示剩余时间。
- **全部课程**：默认收起；同名课程合并为一条（线上 32 条 → 9 门），条目内用标签列出各时段，点开显示该课全部时间/地点/教师/周次。
- **去掉编辑入口**：删除顶部「添加课程 / 导入默认课表 / 发布课表 / 清空本机」整栏；课程详情去掉「编辑 / 删除」；课表数据只来自教务同步 `tt.json`（「导入」保留为本地备份用途）。
- 同步更新自检脚本：`export_check tt` 改为直接种一门课；`selfcheck` / `overflow_check` 去掉 `#tFormCard` / `pubOK` 断言。
- 验证：selfcheck PASS、430px overflow=0、tt 导出正常；线上 Headless Edge：第 10 周、下一节隐藏、全部课程默认收起（9 门、无重名）、详情无编辑按钮、`#tAddOpen/#tDefCourse/#tPub/#tWipe` 数量 0；线上 `index.html` **sha256 MATCH**（190,077 B）。
- 回滚点：`tools/_backup/index_online_20261104-0910.html`。

## 2026-11-04 · 课表细节修正（今日标记 / 第 10 周 / 倒计时）

- **今日只在日期处标记**：周三表头日期后加「今天」小徽标；取消整列高亮与今日列呼吸背景（课程块保留「正在上课」描边）。
- **学期周次校准**：教务系统 **11/2–11/8 = 第 10 周** → 第 1 周周一改为 `2026-08-31`（原来 `2026-09-07` 会误显示第 9 周）。同步更新 `tools/tt.json` 的 `t`、前端 `DEF_TERM`、jwxt 文档/示例；计划任务实参补 `--term-start 2026-08-31`，前后周次自动顺延。
- **倒计时人性化**：剩余时间 ≥ 60 分钟显示「X 小时 Y 分钟」，不再显示几百分钟（如「还有 2 小时 34 分钟」）。
- 验证：selfcheck PASS、430px overflow=0、截图正常；线上 Headless Edge 实测「第 10 周 / 11/2–11/8」、今日仅表头「今天」徽标、`td.cell.today` 数为 0；线上 `index.html` 与 `tt.json` 均 **sha256 MATCH**。
- 回滚点：`tools/_backup/index_online_20261104-0855.html`。

## 2026-11-04 · 课表视觉改版（莫奈配色 / 等宽列 / 周末自动隐藏）

- **等宽列**：周表改为 `table-layout:fixed`，节次标签列固定 50px，其余每天列完全均分；7 天全满时保留横向滚动，5/6 天在手机上可整表无滚动显示。
- **莫奈色**：16 色低饱和调色板（雾蓝 / 紫丁香 / 鼠尾草 / 藕粉 / 奶油黄 / 灰紫…），课程名最多 2 行、教室单行省略，点开详情看全文；日视图卡片与左侧色条同步换色。
- **圆润与视觉**：课表卡片 20px 圆角、课程块 / 日期块 12px 圆角、柔和投影与渐变（「下一节」卡、今日列呼吸），悬停微抬升、按压回弹；日视图卡片 16px 圆角。
- **周末自动隐藏**：按当前查看的周判断——周六/周日无课则隐藏对应列（周视图与日视图日期条同步）；该周有周末课（如第 9 周周六体育 1）会自动出现；周日无课时永远不占位。
- 验证：selfcheck PASS（ERR=none）、430px overflow=0、截图 tt/tt_day/tt_prev/tt_detail/tt_admin/tt_desktop/tt_360、导出 tt 正常；线上 Headless Edge 实测第 9 周 6 列（无滚动）、第 8 周 5 列、页面无横向溢出；线上 sha256 MATCH。
- 回滚点：`tools/_backup/index_online_20261104-0830.html`（本次上线前的线上版，195,382 bytes）。

## 2026-11-03 · 课表改版 + 教务系统自动同步

- **课表 UI**：周次切换（‹ 第 N 周 › + 本周，显示 `11/2 – 11/8` 日期区间）；周 / 日双视图（窄屏默认日视图，选择会记住）；点课程看详情弹层（时间/地点/教师/周次/本周是否上课，管理员可编辑删除）；「下一节」卡显示正在上课 / 还有 X 分钟 / 明天；全部课程改可折叠列表（手机默认收起）；管理员编辑表单收进「添加课程」弹层；导出图片带上周次与日期区间。
- **数据源优先级**：发布链接 `#tt=` > 教务同步 `tt.json` > 个人导入 > 本机编辑；有课表数据时普通访客在「全部」能看到课表工具（不再仅管理员/链接可见）；管理员首次自动采纳教务课表，手动改过则保留本机版本并可在导入面板一键覆盖。
- **导入 / 同步**：新增「导入」弹层——粘贴同步码 / JSON / 发布链接 / 选择 .json 文件；「刷新教务课表」按钮同源拉取 `tt.json`。
- **同步工具链**：新增 `jwxt/`（`jwxt.py` 登录+抓取+解析、`sync.py` CLI、`bookmarklet.html`、`install_task.ps1` 计划任务、`tests/` fixture 单测）；凭据用 Windows DPAPI 加密存本机，不进网页/仓库/云端；同步产物写 `tools/tt.json`，`--deploy` 走现有 `deploy/sync_tools.py`（已支持 tt.json 上传）。
- **自检**：selfcheck PASS（ERR=none、navCount=0）；430px overflow=0；截图新增 tt / tt_day / tt_prev / tt_detail / tt_import / tt_admin / tt_desktop / tt_360；导出 tt 正常；`tt.json` 三种模式（访客 / 管理员自动采纳 / `#tt=` 链接）浏览器实测通过。
- **教务真实同步打通（SSO）**：用户密码实为学校统一身份认证密码；新增 authserver（AES 加密表单，无验证码）→ 门户 → headless Edge 点「新教务系统」→ 取教务 cookie → `xskb_list.do?viweType=0` 抓周表 → 新版 `qz-weeklyTable` 解析（32 门课，周一起始按数据列位置映射）→ 写 `tools/tt.json`。已上线真实快照（线上 sha256 MATCH）。
- **定时任务**：注册 Windows 计划任务 `JwxtTimetableSync`（pythonw + schtasks XML，每天 07:00；`StartWhenAvailable`，失败/超时写 `jwxt/logs/sync-YYYYMMDD.log`）。实测 `-Run`：Last Result=0，cookie 快路径 ~9 秒、SSO 全链路 ~20 秒，自动上传成功。
- 真实数据与旧 bootstrap（10-13 人工）对比：29→32 门；星期无位移（与「有课表课程」列表逐条核对）；修正 14 处节次（如高数周一 1-2→1-3）、若干周次/教室；发布链接功能保留。
- 部署：2026-11-03 22:42 上线 `index.html` + 初始 `tt.json`；23:16–23:17 定时任务两次实跑，线上 `tt.json` 已更新为真实 32 门（sha256 MATCH）。
- 回滚点：`tools/_backup/index_online_20261103-2240.html`（本次上线前的线上版，166,952 bytes）；`tt.json` 回滚＝删线上对象或重传旧快照。

## 2026-10-22 · 作业截止时间

- 作业截止日期支持可选的具体时间；不设置时间时按截止日期当天 **00:00** 计算。
- 微信小程序：截止提醒按新截止时间计算，支持「下一节该课程上课时间」一键设为截止；自定义提醒改为日期 + 时间选择器，并校验不能早于现在、不能晚于截止。
- 微信小程序：作业前图标改为书本图标；抽签重置时同步清空分组结果。
- 云端：`homework` 新增 `time text default ''`；网页端同步支持截止时间。
- 验证：网页自检 / 430px 溢出通过；线上逐字节 sha256 MATCH。
- 回滚点：`tools/_backup/index_online_20261022-2000.html`。

## 2026-10-21 · 体测输入框清理

- 体测输入框移除占位提示，保持空白；小程序端增加数字清洗（身高/体重/50 米/坐位允许小数，坐位允许负数；肺活量/跳远/引体与长跑只允许整数）。
- 小程序抽签、分组、课表、学号等数字输入同样增加清洗，字母/符号不再进入数据。
- 验证：网页自检、430px 溢出通过；线上逐字节 sha256 MATCH。
- 回滚点：`tools/_backup/index_online_20261021-1322.html`。

## 2026-10-20 · 登录边界 / 同步补全 / 附件

- **登录边界**：未登录不能发布作业/通知；仍可查看列表、勾选完成作业、置顶通知。发布入口会引导登录。
- **同步补全**：小程序工具排序写入 `userdata`（`homeTools/homeToolsAt`），按时间自动合并；网页通知置顶改走 `marks`，登录后跨设备同步。
- **附件**：作业 / 通知支持最多 2 个图片或文件（图片原图 ≤5MB 自动压缩、文件 ≤2MB），随行上云。网页可图片/PDF/文本内预览并下载；小程序用 `chooseMedia` / `chooseMessageFile`，点击图片预览、文件用系统应用打开/保存。
- **UI**：工作台问候语右侧显示账号并右对齐、移除卡片日期；体测去掉示例值与自动算分提示；点名名单改为「编辑名单」按钮 + 底部弹层，长名单不再撑高页面；登录页只保留一个图标；「我的」登录后只保留右上角账号小按钮（长账号自动省略）。
- 云端：`homework` / `notices` 已加 `attachments text default ''`。
- 验证：网页自检/430px 溢出/导出全绿；Web 附件上传→渲染→预览→下载实测；小程序单元 41/41、静态审计、附件与排序定点测试。
- 回滚点：`tools/_backup/index_online_20261020-2233.html`。

## 2026-10-20 · 名单自定义 / 删除权限 / 体测与小程序修复

- **名单**：抽签、分组、点名里的名单都改为“用户自定义”；班级名单只缓存在 `classRoster`，只有点「导入班级名单」才会填入，不再随登录自动覆盖自定义名单。未登录也可以编辑自己的名单。
- **删除权限**：作业 / 通知新发布的行写入 `owner`（账号）。管理员或发布者可删除且所有人不可见；其他人只能「隐藏」自己的视图，不会影响别人。云端已给两张表补 `owner` 列。
- **说明文案**：使用说明按实际功能重写，移除开发者口吻与过期描述。
- 验证：四条自检全绿；430px 溢出 0；导出 draw/ft/hw/nt 正常；线上逐字节 sha256 MATCH。
- 回滚点：`tools/_backup/index_online_20261020-2015.html`。

## 2026-10-19 · 认证改为按需 + 作业截止可选/三天后清理

- 去掉常驻认证提示条/认证按钮；未认证时隐藏名单输入和名单按钮，只在抽签/点名的“班级名单”入口点击时弹出认证。
- 作业截止日期/截止说明改为可选；有截止日期的作业在截止日 23:59 后再过 3 天，打开/同步时本机移除并云端 `archived=true`；无截止日期保留。
- 验证：网页自检、430px 溢出、截图、导出全绿；线上逐字节 MATCH。
- 回滚点：`tools/_backup/index_online_20261019-2236.html`。

## 2026-10-19 · 班级身份认证（姓名 + 学号）

- 登录后新增班级身份认证：真实姓名 + 10 位学号→ `identity_verify`。
- 官方名单放在私有 schema `private.class_ids`（无 API），由 security definer 校验；`roster` SELECT 要求认证行存在，只登录不认证读不到名单（服务端 RLS，不只是隐藏）。
- 客户端：小程序「我的」认证卡 + 工作台锁定提示；网页顶部提示条/认证弹窗；认证后自动拉取名单。
- 名单更新为官方 69 人（原表 49 号重复、48 号缺失，按唯一座号去重），行格式“01 姓名”。
- 验证：真实 RLS 测试（未认证 roster 空、错误身份 401、正确身份 201 后 roster 可读）；网页线上真实登录→认证→名单解锁。
- 回滚点：`tools/_backup/index_online_20261019-2136.html`。

## 2026-10-19 · 体测历史：首开修复 / 补填合并 / 最多两条 / 自定义名称

- 小程序首次打开体测页时历史卡片改用渲染后的字段（不再显示裸记录空白）。
- 同一份数据只是多填项目 → 更新原记录，不新增；本地与云端最多保留最近两条，超出软删。
- 历史记录支持自定义名称（小程序「改名」/网页改名提示），名称随 `fitrecs.data.n` 跨端同步。
- 验证：小程序端到端 78/78；网页自检、430px 溢出、截图、导出全绿；线上逐字节 MATCH。
- 回滚点：`tools/_backup/index_online_20261019-1836.html`。

## 2026-10-19 · 工作台/点名/登录/体测 UI 优化

- 工作台顶栏：双阈值收缩 + 去掉过渡，修复滑动到 40px 附近来回抽搐。
- 点名：三色统计（已到/请假/未点）+ 状态药丸 + 整行到/假按钮，和原有配色统一。
- 登录弹窗：图标/标题/副标题、主次按钮、昵称独立提示；未设置昵称时不再默认用账号名。
- 体测历史：每条直接展示身高/体重/肺活量/50 米/坐位/跳远/引体/长跑明细，按等级色条区分。
- 体测新增“国标表”按钮/弹窗（男/女 × 大一大二/大三大四，7 项 × 20 档）。
- 使用说明：移除管理员功能描述，置顶改为按账号同步。
- 验证：四条自检全绿；线上逐字节 MATCH。
- 回滚点：`tools/_backup/index_online_20261019-0846.html`。

## 2026-10-18 · 云权限收紧 + 多端同步契约

- 登录/注册改为服务端 RLS 鉴权：所有请求带 `X-Device-Id: 账号|口令哈希`；`users` 只能按自己的 id+h 读取，注册只允许非 admin；名单/勾选/体测/反馈/统计按行收紧（SQL 见 `deploy/cloudbase/security_hardening.sql`）。
- 网页版与小程序统一使用 `roster` / `fitrecs` / `marks` / `homework` / `notices` 表；`userdata` 仅保留旧版兼容。
- 验证：本地四条自检全绿；线上逐字节 MATCH；真实云登录/名单拉取通过（测试账号已清理）。
- 回滚点：`tools/_backup/index_online_20261018-2337.html`；RLS 回滚 `deploy/cloudbase/security_rollback.sql`。

## 2026-10-15 · 作业长内容/多行显示与导出修复

- 作业发布「内容」由单行输入改为多行 textarea：Enter 直接发布、Shift+Enter 换行（原单行输入根本无法录入多行内容）。
- 作业列表重排：科目作为独立标题行，内容作为正文多行显示——保留换行、超长无空格串强制折行、无科目时内容直接顶格；其余交互（勾完成/删除/待补发）不变。
- 作业清单导出图：内容按换行逐行绘制；`wrap()` 支持 `\n` 硬换行与超宽 token 字符级折行（长英文/中外文混排不再越界）。
- 根因修复（旧版线上已有此 bug，本次定位）：`exportCard` 预测量阶段字符串分支从未设置画布字体（绘制上下文一直停留在默认 `10px sans-serif`），换行宽度按 10px 计算、绘制却按 16.5px，导致「长作业内容导出图片右侧被切」；已用 10-15 上线前备份版复现确认，现预测量与绘制统一字体。
- 验证：四条自检全绿；专项用例（约 130 字中文长串 + 4 行多行内容 + 长英文句）在 430/760 宽列表无溢出（overflow=0），导出图内容右界 1432px < 卡片右缘 1492px；线上逐字节 sha256 MATCH。
- 回滚点：`tools/_backup/index_online_20261015-1340.html`（本次上线前的线上版）。

## 2026-10-13 晚 · 课表核对修正与动效

- 课表数据按教务系统官方课表（2026-2027-1，学生个人课表 xls，打印于 2026-10-13）逐条核对重写：
  29 条课程，周次/节次/教室/教师全部对齐官方（体育1 按教师分周次、军事理论为单节 09:50~10:30、
  中医学晚间 10-12 节、高数/英语1/思修/C语言/计算机导论等周次全部修正）。
- 节次时间对齐学校作息：第一节 08:10 起，午休 12:10–14:30，晚间 19:00–21:20。
- 配色改为按课程名首次出现顺序分配（16 色调色板）：同名全局同色、不同课必不撞色、颜色不随周次漂移。
- 微动效：课程块错峰入场渐显、今日列呼吸高亮、悬停/按压反馈、下一节课呼吸指示灯；
  `prefers-reduced-motion` 时全部关闭。
- 验证：无头 Edge 几何校验（周 6 共 11 块全部渲染、7 门课 7 色无撞色、rowspan 连续覆盖无断缝、
  无泳道重叠）；四条自检全绿后上线，线上逐字节 sha256 MATCH。
- 回滚点：`tools/_backup/index_online_20261013-1849.html`（本次上线前的线上版）。

## 2026-10-13

- 课表配色：今日节次高亮描边，课程块颜色统一、对比度优化。
- 使用说明去管理员化：说明文案不再出现「管理员 / admin 账号」字眼，改为发布链接语义。
- 体测记录：新增「保存记录」与历史列表（回填 / 删除，上限 50 条）；登录后按账号同步到云端
  `public.fitrecs`（无 DELETE 权限，删除走 `arch` 软删），未登录仅存本机、登录后自动补传。
- 名单登录门禁：班级名单从公开 HTML 移除并上云（`public.roster`，登录后下发）；未登录隐藏名单入口
  （抽签页名单域、点名页导入按钮），渲染层按空名单处理；「从云端加载班级名单 / 更新云端名单（管理员）」按钮。
- 一次性登录引导：未登录首次发布作业 / 通知 / 勾完成置顶 / 保存体测记录后弹一次「登录后更多功能」，
  关闭后不再显示。
- 回滚点：`tools/_backup/index_online_20261013.html`（上线前的线上版）。

## 2026-10-10 08:20

- 新增第 5 个工具「体测」：大学体测成绩计算（《国家学生体质健康标准（2014 年修订）》大学组，
  大一大二 / 大三大四两档）；7 项按权重算标准分 + 附加分 = 学年总分(120) 与等级；可导出/复制/清空。
- 数据结构新增 `zq_tools_v2.fit`（旧数据无此字段时走默认值，向后兼容）。
- 自检扩展：`shots.py` 新增 ft/ft_360/ft_desktop 三档截图并关掉装饰性动画保证确定性；
  `export_check.py` 支持 `ft`；`overflow_check.py` 改为逐 tab 溢出审计。
- 四条自检全绿后上线；线上逐字节 sha256 与本地 MATCH。
- 回滚点：`tools/_backup/index_online_20261010-0820.html`（上线前的线上版）。
- 流程变更：用户授权“以后都直接上线”，原 10-11 冻结期解除；部署前置＝自检全绿 + 备份线上。



## 2026-11-04 班级通知并入工具站
- `tools/index.html` 通知 tab 顶部新增云端「班级通知」板：AI 标题/摘要/字段、附件预览下载、二维码直显、原始消息。
- 自动通知经 `public.notices` 的 `auto_*` 行 + `[[CLASS_NOTICE_V1]]` payload 下发；本地 watcher 构建后自动同步。
- 仍走 `class_verify` 身份门禁；匿名读取返回空。
- 测试脚本仍按旧版无门禁页面写，需更新后再作为上线门禁。

## 2026-11-04 14:15 通知板配色/登录
- 工具站通知板统一 #F7F8F8 背景与白卡；身份 token 29 天内自动进入；已部署并实测 login-once、19条、匿名空、无横向溢出。旧 selfcheck 仍待更新。

## 2026-11-04 14:30 班级简报
- 工具站通知 tab 增加班级简报、状态/分类/已处理筛选、桌面双栏；已部署并完成生产验证。

## 2026-11-04 18:15 通知页整页搬入
- 通知 tab 改成完整 notice-board iframe：简报/筛选/原始消息/附件/二维码/过期折叠/桌面双栏；颜色统一；旧手动发布组件移除；CloudBase 数据注入；已部署测试。

## 2026-11-04 18:35 Monet 统一 + 小程序通知
- 网页/小程序统一莫奈色；网页通知 iframe 模板更新；小程序通知页改为云端 auto notices，移除旧发布/置顶/手动逻辑；unit 49/49、staticcheck 0、preview 编译通过。

## 2026-11-04 18:45 小程序 UI 修复
- 工具页「打开」按钮：移除固定 283rpx 卡片高度和 16px 内联间距，改为 flex 卡片、描述自适应、按钮固定在卡片底部，避免位置偏移。
- 首页工具图标：课表/班委补 `tool-tt.png` / `tool-bz.png`，全部工具统一白线图标；首页图标底色改为实色莫奈色（睡莲青/雾蓝/暖沙），白图标不再落在浅色容器上。
- 网页国标体测评分表：首列 sticky 加 `z-index:3`，表头 `z-index:4`，左上角 `z-index:5`；用不透明卡片底色 + 右侧分隔线，横向滑动时分数据不再覆盖项目名；表格改 `border-collapse:separate`。
- 验证：小程序 unit 49/49、staticcheck handlers missing 0、cli preview 编译成功（405.1KB）；网页生产环境打开国标表横向滚动，首列保持覆盖。

## 2026-11-04 18:55 通知人群可见
- notices.audience + RLS 服务端过滤；红会群仅 2024000001，班委群仅班委，其余 all；写权限收紧管理员；已验证 19/18/18/0。

## 2026-11-04 19:10 截止时间按消息日期解析
- 截止只取截止语境，相对日期按消息发送时间锚定；AI 摘要截止同步重算；已重建并同步 19 组。

## 2026-11-04 19:25 通知弹层修复
- iframe 固定视口高度/内部滚动，修复原始消息/图片/PDF 弹层居中到长页面中部不可见的问题。

## 2026-11-04 19:55 时间模型/手机弹层
- notices 增加 eventAt/expireAt/timeLabel；体育补测按活动结束、挑战杯取消错误截止、药膳按报名开放+1天；通知 iframe 弹层全屏化。

## 2026-11-04 20:10 小程序通知完整化
- 小程序通知卡片支持展开/收起、图片缩略图与全屏预览、附件展开、原始消息弹层；图片按需加载。

## 2026-11-04 20:35 登录图标 + 团员可见
- 网页登录门禁（身份页）左上角「班」字方块换成班级工具站图标（内联 SVG，与 favicon 同款：暖白圆角方块 +
  睡莲青主圆 + 雾蓝/暖沙点缀）；无外部请求、无新增资源，已部署，线上 sha256 MATCH。
- 服务端：`public.notices.audience` 新增 `league`（团员可见）；`private.class_league` 50 名团员名单 +
  `auth_is_league()` + `nt_read` 新分支；自动通知映射「团员」群 → `league`。详见 `CLOUDBASE.md`
  （其中「长言木」「🗿」两个网名群成员已按用户确认映射为同学D、孙博文）。
- 小程序：身份页图标同步换成站点图标（`images/logo.png`）；小程序头像用 `images/app-icon-1024.png` 上传。
- 回滚点：`tools/_backup/index_online_20261104-2032_preLogo.html`（本次上线前的线上版）。

## 2026-11-04 23:30 网页性能与缓存优化（持久缓存 + 通知懒渲染，已上线）

- **背景（实测）**：通知表 `notices` 整表响应 **2,001,996 B**（43 行：24 auto + 19 manual；9 张图片
  data URI 1,310,983 字符 + 5 个文件 data URI 605,116 字符，元数据仅 53KB），服务端**无 gzip**。
  原实现 boot、每 30s 轮询、进通知 tab、可见性回前台都整表重拉（≈240MB/h），数据一到就
  `doc.write` 2MB 重建通知 iframe（未进通知 tab 也会建）。
- **持久缓存**：IndexedDB `zq_cache_v1/kv` 存 AUTO_NOTICES（按学号 sid + `zq_cache_gen_*` 代际隔离，
  记录 `{sid,ver,g,at,sig,val}`）；localStorage 存 marks 勾选快照与
  `zq_synced_at_*` / `zq_visited_*` / `zq_migrated_*` / `zq_cache_gen_*` 元数据（按 sid）。
  IDB 不可用 / 配额失败 / 数据损坏一律静默降级为原行为；退出身份 `cacheKill()` 换代并清理，
  防止同学共用手机串数据。
- **刷新策略**：TTL 门控（notices/homework 10min、marks 2min、fit 5min、members/tt 6h、visits 10min）。
  TTL 过期先发轻量签名 `notices?select=id,ts&order=ts.asc,id.asc`（≈2KB，实测同表整表查询为 2,106B），
  与缓存签名一致仅更新 lastSync（0 大表请求），不一致才整表重拉；`force` 保留给显式刷新。
  30s 轮询保留，但大表 TTL 内 0 请求。
- **首屏**：本机数据先渲染 → IDB hydrate → 小表 TTL 拉取 → 大表 `requestIdleCallback` 后 ≥2s 低优先级
  后台刷新（仅访问过的 tab + TTL 过期 + 非慢网）；**首次无缓存用户不预取通知/作业**，进 tab 才拉。
  新增同色系骨架屏（shimmer，`prefers-reduced-motion` 下关闭动画），不写说明文字。
- **通知 iframe 懒渲染**：未激活通知 tab 不创建；数据未变不重建；有缓存时进 tab 立即出内容；
  运行时向 iframe 注入 `loading=lazy` / `decoding=async` 与弹层 `backdrop-filter` 降级（不修改模板源）。
- **效果（CDP 实测 @390 / 4x CPU throttle）**：boot 大表 0 请求；TTL 内 0 请求；TTL 过期 ≈2KB/10min
  （≈12KB/h）；内容变化才重拉 2MB；有缓存二次加载全程 0 网络请求、通知 tab 秒开；
  30s 轮询 4.1MB/min → 0；未进通知 tab 时 iframe 创建数 0。
- **验证**：新增 `tools/tests/perf_check.py`（123 项，`PERF_SRC` 可复盘任意副本；对线上字节复跑
  **123/123 PASS**）；回归 `roster_check.py` 199/199、`reset_check.py` 109/109（对线上字节）、
  `overflow_check.py 430` overflowCount=0、`export_check.py draw` 正常；无外部请求、0 console.error。
- **上线**：线上 `index.html` **353,460 B · sha256 `7a7628b1ffb16f32…`**（与并行会话的
  visits/feedback `cbPostNoRep` 修复共存；期间出现过「本地 ≠ 线上」的短暂状态，最终线上字节已包含双方
  改动，并对最终字节复跑 perf_check / reset_check 全绿）。回滚：把
  `tools/_backup/index_online_20261104-2321_perf.html`（339,436 B，本次优化前的线上字节）重传即可。
- **遗留建议**：通知 2MB 的根因是附件/图片以 data URI 内嵌 `notices.body`；服务端改为外链 URL 后可降到
  ~50KB，属 briefdesk/云端改造，本次未做（前端已用缓存 + 10 分钟签名把重复流量压掉）。

## 2026-11-04 23:35 修复「访问统计只有管理员自己」：visits/feedback 非管理员写入 401（已上线）

- **用户反馈**：统计列表始终只有自己一个人，即使换别人的账号登录后再看也一样。
- **根因（实测，不是统计页显示问题）**：`public.visits` / `public.feedback` 的 SELECT RLS 只有
  `auth_admin()`；而网页 `cbPost()` / 小程序 `headers(true)` 的写请求统一带 PostgREST
  `Prefer: return=representation`。PostgREST 的 INSERT + returning 要求新行同时能被 SELECT →
  非管理员写这两张表返回 `401 DATABASE_42501`，前端 catch 后静默失败。**除管理员外的访问根本没入库**
  （DB 当时只有管理员 36 行 + 旧匿名 81 行）；反馈提交同样坏掉。
- **修复**：
  1) 云端 RLS（`deploy/cloudbase/2026-11-04_visits_feedback_own_read.sql`，已应用）：
     `vs_read` = `auth_admin() OR (auth_ok() AND sid = auth_acc())`；
     `fb_read` = `auth_admin() OR (auth_ok() AND acc = auth_acc())`。写入策略不变，管理员读全部、
     普通成员只读本人行（不暴露他人）。这一步让**已部署的旧页面/小程序立即恢复写入**。
  2) 网页 `tools/index.html`：新增 `cbPostNoRep()`（POST 不带 returning，仅判 `r.ok`），
     `visitLog()` 与反馈提交改用它；其余表不动。
  3) 小程序 `mp-class-tools/utils/cloud.js`（仅源码，未发版）：`visitLog()`/`fbSend()` 的
     `headers(true)` → `headers(false)`；小程序未发版前靠第 1 步已恢复。
- **验证**：新增 `tools/tests/stats_check.py`（假身份 + fetch mock，不碰真实云）**30/30 PASS**；
  线上 E2E（headless Edge + CDP，普通成员）`POST /rest/visits` **201**（修复前 401）、DB 入库、
  管理员统计页出现 2 个账号（管理员/同学N）、无学号（截图 `tools/tests/_shots_stats/live_stats_admin_430.png`）；
  云端策略直连探测 8/8（临时脚本已删）；回归 `export_check.py draw` 正常，
  `roster_check.py` / `overflow_check.py` 见独立验收。测试产生的 visits/feedback 行已清理。
- **独立验收**（另一 agent，fresh context，只读）：线上字节首尾两次比对一致（353,460 B / 同上 sha256）；
  真实浏览器 E2E **26/26**（普通成员 visits 201 入库、反馈 201 + toast、管理员统计页 2 账号且不含学号）；
  `stats_check.py` **30/30**、`overflow_check.py 430` **0**、`roster_check.py` **199/199**；
  边界通过（非管理员读他人数据 → `[]`，伪造他人 sid 写入 → 401）。测试数据已自清。
- **上线**：线上 `index.html` **353,460 B · sha256 `7a7628b1ffb16f32…`**（= 本地；与并行会话的
  性能优化共存，最终字节已由双方互验）。回滚：`tools/_backup/index_online_20261104-2326_preStatsFix.html`
  （353,042 B，修复前线上字节；重传会同时回滚性能优化，需谨慎）。
- **备注**：修复前其他同学的访问无法补回，统计从修复后开始有数据；`fb_insert` 仍为历史行为
  `auth_ok()`（未收紧，见 HANDOFF §27.5）。

## 2026-11-04 23:57 修复：手机网页「班委名单」一直加载不出来（性能优化回归，已上线）

- **现象**（旅行者反馈）：手机网页打开班委名单，一直停在「加载中…」。
- **根因**：性能优化给 `membersPull()` 加了 6h TTL 门控；旧实现是「拉取成功 → `membersApply()` →
  `renderCommittee()`」，TTL 命中后不再发请求，而 `refreshAll()` / `gotoTab()` 都没有调用
  `renderCommittee()`——整页应用每次加载 DOM 重建后，`#cmOut` 就永远停在初始的「加载中…」。
  冷启动/无缓存时能拉到名单所以正常，**只有「本机已有名单缓存且 6h 内」的常规回访路径必现**。
- **修复**（`tools/index.html`，3 处 + 启动流程）：
  1) `refreshAll()` 增加 `renderCommittee()`（首屏即从本机 `D.d.members` 渲染）；
  2) `gotoTab('committee')` 增加 `renderCommittee()`（从「全部」工具卡进入时也必渲染）；
  3) `membersPull()` 的 TTL 命中分支补一次 `renderCommittee()`（防御性）。
  另：启动流程改为 **不等 IndexedDB**——`bootRefresh()` 立即执行、`bootCache()` 异步补水
  （IDB 回调不返回 / 被手机 WebView 策略拦截时，名单、课表、统计等初始化不再被卡住）。
- **验证**：新增 `tools/tests/committee_check.py`（headless Edge + `--virtual-time-budget` +
  `--dump-dom`，不需要 CDP）：缓存命中·网络不可用 / 冷启动·云端返回名单 两种场景各 7 项
  **14/14 PASS**（修复前缓存场景 3 项 FAIL，可稳定复现「加载中…」）。回归：`perf_check.py` 123/123、
  `reset_check.py` 109/109、`roster_check.py` 199/199、`overflow_check.py 430` overflow=0、
  `export_check.py draw` 正常；0 JS 报错 / 0 console.error。
- **上线**：线上 `index.html` **353,799 B · sha256 `ecaabee7a4a9cbf6…`**（对线上字节复跑
  committee_check 14/14、reset 109/109、perf 123/123）。回滚：
  `tools/_backup/index_online_20261104-2357_preCommitteeFix.html`（353,460 B，修复前线上字节）。
- **教训**：给函数加 TTL/缓存短路时，要检查它是否还承担「渲染副作用」；整页应用每次加载 DOM 都是新的，
  短路分支必须自己触发渲染（现约定：tabs 渲染在 `refreshAll()` / `gotoTab()` 兜底）。

## 2026-11-05 08:2x 用户数据跨端同步 v6 + 通知已处理（已上线）

- **范围**：作业完成 / 通知置顶 / **通知已处理**（`marks`）、工具栏顺序、体测录入、抽签参数、分组参数与名单、
  抽签参与名单 / 点名名单与到·假、隐藏项、课表偏好、昵称（`userdata` blob **v6**）——与小程序同一账号
  **双向互通**；表结构 / RLS / 域名 / 接口地址均不变（`marks` 新增 `kind='ntdone'`，`userdata.blob` JSON 内扩展）。
- **通知已处理**：通知 iframe 模板（briefdesk 生成，勿改源）运行时注入 `w.__zqApplyDone(map)` 写模板全局
  `state.done` 后 `render()`；iframe 内 capture 监听 `[data-act="done"]` → `postMessage({type:'class-notice-done'})`
  → 父页更新 `NT.done/AN_DONE` 并 `cbMark('ntdone', gid, done)`（失败进 `markPend` 补发）；父页**不重复 render**，
  应用云端 done 时保持 iframe 滚动位置；旧 localStorage `zq_auto_nt_done` 按 sid 一次性迁移后清除。
- **UD v6 模块**（约 L1655-1933）：`merge` 与契约 fixture 逐字节一致（逐 section 比较 `at`，`remote.at >= local.at`
  云端赢、同 at 幂等收敛；未拥有 section 原样保留，网页不写 `prefs`）；v5 自动迁移；`D.save()` 脏检测防抖
  1200ms；拉取 = boot idle + `cloudPull` TTL 60s；推送 = GET 合并后 POST upsert（`Prefer` merge-duplicates），
  离线进 `zq_udpend_<sid>` 待补发；应用远端数据**不重置**进行中的抽签/分组结果（定向更新，不用 `refreshAll`）；
  体测输入框聚焦时只存值不写 DOM。退出身份 `cacheKill` 同时清 UD 缓存键。
- **文案**：使用说明改为新口径（完成/置顶/已处理/工具顺序/体测/抽签分组/点名/隐藏/课表偏好按账号同步、
  网页与小程序互通；身份 token 与班级名单缓存仅本机、退出清除）；不再出现「抽签、分组、点名只存本机」。
- **验证**：新增 `tools/tests/sync_check.py`（headless Edge + fetch mock，夹具内嵌，可独立跑）
  **117/117 PASS**（远端 v6→UI 应用、本地改动 POST blob 契约与 11 键顺序 / `homeToolsAt` 镜像 / `prefs` 保留、
  merge 三组逐字节、iframe `state.done`、迁移、坏 JSON、断网重试、管理员教务课表自动采用不产生同步推送、
  **远端 v5 → 自动写回 v6 且保留 fit/homeTools、再 pull 不重复写**、0 JS 错 / 0 console.error / 无外部请求）；
  回归 `perf_check` 123/123、`reset_check` 109/109、`roster_check` 199/199、`overflow_check 430` overflow=0、
  `export_check draw` 正常、`committee_check` 14/14（本地与**线上字节**各跑一遍）。
- **上线**：线上 `index.html` **374,183 B · sha256 `b0bbd71023b53327…`**（含 tt 自动采用 rebaseline、
  v5→v6 自动写回两处加固；与小程序 v1.4.6 同一契约；真实生产互通验证见独立验收报告）。回滚：
  `tools/_backup/index_online_20261105-0752_preSync.html`（353,799 B · sha256 `ecaabee7…`，本次全部改动前
  线上字节）；中间版留档 `..._0810_preTtRebaseline.html`（372,607 B · `ba07b435…`）、
  `..._0823_preV5Writeback.html`（373,691 B · `eeb5e348…`）。
- **已知风险**：① 管理员「教务课表自动同步」会改 `ttUseMine`：已用 `UD.rebaseline('tt')` 把自动采用排除出
  同步脏检测（后台逻辑不跨端推送/不改用户偏好；用户手动切换视图、导入自定义课表仍正常同步）；
  ② UD 模块含 apply/DOM 辅助约 280 行（契约估 ~150 行）；③ 网页无隐私开关（隐私/数据管理页在小程序），
  网页不承诺开关。











