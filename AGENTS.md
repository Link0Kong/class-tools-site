# AGENTS.md — 班级工具站（tool.furina.fun）

> 你正在开发的是一个 **单文件、零依赖** 的静态站点。动手前请**完整读一遍本文件**和同目录的 `HANDOFF.md`。
> 目标不是"写更多代码"，而是**在用户明确的设计红线内，把既有功能做对、做稳、可验证**。

---

## 0. 绝对红线（违反即返工，严重者禁止提交）

1. **密钥零泄漏**：`deploy/creds.env`、`tools/cert/`、`deploy/acme_account_key.pem` 是机密。
   **不得读取其内容、不得复制、不得粘贴进对话或任何外部请求（包括模型上下文）。**
   部署脚本只通过"读取文件"的方式使用它们。
2. **不得引入构建链**：禁止 npm / yarn / pnpm / vite / webpack / TypeScript 编译 / 任何前端框架。
   产物必须是**双击即可打开**的 HTML；JS 只用原生浏览器 API。
3. **不得触碰另一个站点**：`me.furina.fun`（竞选自我介绍页 + 微信域名校验文件）属于**另一个 OSS Bucket**，与本项目无关，禁止改动。
4. **班级身份门禁（2026-11-04 用户要求）**：网页/小程序启动后必须先输入「学号 + 姓名」，只有匹配班级官方名单（`private.class_ids`，70 人真实名单 + 1 个 `is_test` 测试身份，测试身份被 `class_members` 过滤、不在名单/统计显示）并拿到云端 token 后，才允许加载班级数据。
   - **所有班级数据**（作业、通知、名单、体测、marks、访问统计等）都走 CloudBase PostgreSQL + PostgREST，RLS 统一校验 token；**不能用前端隐藏代替权限**。
   - 网页用 `X-Device-Id: <token>`（网关 CORS 白名单），小程序用 `X-Class-Token: <token>`；服务端 `auth_hdr()` 两者都接受。
   - 旧账号密码/注册/`users` 表/旧管理员 `admin` 已全部下线；管理员 = 陈子麒（3260707024）。名单原文不进公开 HTML。
   - **课表**仍按 2026-11-03 决定以静态文件 `tools/tt.json` 同源发布；前端只在身份通过后请求它。教务系统账号密码只允许以 DPAPI 文件保存在本机，禁止外传。
   - **用户改动内容**（2026-11-05 用户要求扩大同步范围；2026-11-06 增量 18 补「水量抄表」）：作业完成、通知已处理 / 置顶、工具栏顺序、体测录入与历史、抽签 / 分组参数与名单选择、点名名单与到·假、隐藏项、课表与提醒偏好、昵称、**关注宿舍（电费）**、**水量抄表（4/6 人间 + 每间记录）**等，随账号同步——通知已处理 = `public.marks kind='ntdone'`；其余 = `public.userdata` blob v6（逐 section 时间戳合并，仅本人 token 可读写，可关闭/清除），网页与小程序互通（`water` section 见 `tools/tests/_water_contract.md` §2/§7；整段 LWW）。**再新增同步类别前先问用户**；身份 token、班级名单缓存、webhook 等配置仍只存本机。
   - 前端只允许原生 `fetch` 调 PostgREST 一个接口；`localStorage` 降级为缓存，请求失败仍可用。
   - **禁止在导出图片或页面上暴露手机号、学号、宿舍号等个人隐私。**
     唯一例外（用户 2026-11-05 明确要求）：电费页展示「本人关注宿舍」的规范楼栋+房间号+剩余电量（无姓名/学号），此数据**不导出、不对外分享**。
5. **部署授权（2026-10-10 用户原话：“以后都直接上线”，原 10-11 冻结期随之解除）**：四条自检全绿（见 `HANDOFF.md` §5.2）+ 先把线上 `index.html` 备份到 `tools/_backup/` 后，
   直接 `python deploy/sync_tools.py`，**无需再向用户确认**；回滚＝把备份重新上传。
6. **双远端同步（2026-11-10 用户要求）**：任何改动提交后**必须同时推送到 GitHub `origin` 与 Gitee `gitee` 两个远端**，并附能看懂「改了什么」的提交说明。
   - 唯一入口：`sync-repos.cmd "feat: 说明"`（实现见 `sync_repos.py`，流程见 `SYNC.md`）；它会安全检查、提交、推两端，并核对两端 SHA 与本地一致。
   - 只推一个远端 / 不写说明 / 写 `update`、`同步` 这类笼统说明 = **未完成交付**；失败按 `SYNC.md` 排障后重跑（不会产生空提交）。
   - 两个仓库均为私有（含个人信息 / 服务器配置），不要改为公开；凭据文件仍按第 1 条永不入库。

---

## 1. 设计规范（用户明确逐条要求过，违反即返工）

- **没有底部导航栏**。顶部切换条随屏幕比例变化：竖屏 4 格（3 工具 + 全部）、横屏 5 格（4 工具 + 全部），横竖屏切换带液体重排动画；用户自定义的工具顺序保存在 `homeTools`（最多 4 个）。**课表在身份通过后开放**，不再需要管理员身份。
- **不要多余的说明文字**：界面上不写解释性段落。能用标签、占位符、`<b>` 表达的信息，就不要写成句子。
- **身份后即点即用**：启动先进入学号+姓名身份页（唯一入口，无欢迎弹窗）；通过后直接进入「抽签工作流」第一步。
- 视觉基调：暖白 `#F7F8F8` / 雾青 `#4E9082` / 灰蓝 `#6E8CA8` / 暖沙 `#B98F63`；卡片圆角 16px；手机优先，桌面居中并随屏宽自适应（≥960px 逐步放宽：最宽约 1120 / 1320 / 1520px；手机/平板保持 880 以内）。**桌面靠“排布”利用空间**：课表用主区+侧栏（无下一节时自动单栏全宽），抽签/体测用左右分栏，作业/通知宽屏双栏；不要只靠放大字号或拉宽容器。
- **零外部请求**：不引 Google Fonts、CDN、统计脚本、埋点。
- 交互：移动端可点区域 ≥ 40px；表格类允许横向滚动并给出可滑提示。**滑动交互**：带跟手动画；顶部工具条按实际左右顺序切工具（自定义顺序同样适用），抽签内容切 STEP（STEP1 右滑/STEP3 左滑到边界才切工具），课表内容切**上一周/下一周**（周/日视图只点击切换，不滑动切换），非工具栏上的工具内容滑动不切工具；输入框/文本域上也可滑动（点击仍正常聚焦）；工具栏滑块为**液体动效**（拖动拉伸、松手弹性吸附）；表格横向可滚动区不触发。

---

## 2. 导出图片规范（全部走 `exportCard()`）

- **命名**：`<类型>_<YYYYMMDD-HHMM>_<关键参数>.png`
  例：`抽签结果_20261009-2024_范围1-50_抽10个_不重复_按抽取顺序.png`
- **必须包含**：图内「参数配置」区 + 斜向平铺水印 `tool.furina.fun`（低透明度，不碍阅读）+ 页脚生成时间 + 唯一编号（`recId()`）。
- **版式**：导出卡 v2（2026-11-05 起），规格与小程序共用：`tools/tests/export_card_v2_spec.md`。
  `blocks` 支持三种：`{label,lines[,mono]}`（文本）、`{label,chips:[{n,nm}]}`（抽签结果胶囊）、
  `{label,groups:[[{n,nm}],...]}`（分组两列组卡）；`opt.qr/qrNote` 仅抽签剔除重抽时使用。
  **不要**在页面里自己写 canvas；新导出先按三种块类型组装数据。
- **工作流每一步都能独立导出**（STEP 1 / 2 / 3 各有导出按钮）。

---

## 3. 改动流程（建议）

1. 先读 `HANDOFF.md` §4 定位代码位置，**只改需要改的地方**（这是单文件应用，改动要收敛）。
2. 小步改 → 本地预览 → 跑自检（`HANDOFF.md` §5.2）→ 通过后再部署。
3. 部署：自检全绿 + 备份线上后直接 `python deploy/sync_tools.py`（无需再确认，详见 HANDOFF §5）。
4. **每次改动都必须保持 `index.html` 能被旧版数据平滑读取**（不得破坏 `zq_tools_v2` 的向后兼容；迁移逻辑见 HANDOFF §4）。

---

## 4. 沟通与交付期望

- 复述你理解的需求，再动手；不确定的设计取舍，**列 2–3 个方案 + 推荐**，不要默默改设计。
- 改动后给出：**改了什么 / 怎么验证的 / 有什么副作用**，以及双远端提交 SHA（`git log -1 --oneline` 或 `sync-repos.cmd --check` 输出）。
- 每次改完必须走 `sync-repos.cmd "说明"` 同时推 GitHub + Gitee（见 §0 第 6 条）。
- 不要顺手"优化"用户没要求的东西（重命名、重构、换配色、加动效）。

---

## 4b. v2.0.0 架构补充（2026-11-05，改通知/同步/版本前必读）

1. **版本号**：全站 2.0.0，唯一来源——网页 `tools/index.html` `var APP_VER="2.0.0"`；小程序 `mp-class-tools/utils/version.js` 的 `VERSION`。
   用户要求「直到下一次成功上传发布」不得改版本号。
2. **通知页（网页，2026-11-05 21:25 最终形态）**：`#s-nt` 通知页 = **固定视口高度 iframe + iframe 内部原生滚动**（手机 `calc(100vh-140px)` / 桌面 `calc(100vh-150px)`，`scrolling="yes"`）：
   - 模板由 `C:\Users\Ko_Li\.openclaw\workspace\briefdesk-plan\build_notice_board.py` 生成 → `web/tools/build_notice_embed.py` 嵌入 `NOTICE_TPL_B64`；
   - **纵向滚动必须由 iframe 原生滚动承担**（不要用 `parent.scrollBy` 在 JS 里驱动父页滚动：父页滚一个 20,000px iframe 层在微信 WebView 会掉帧/无惯性）；父页不随通知内容滚动，`class-notice-height` 父页忽略（模板内保留空实现）；
   - iframe 触摸适配层只处理**横向**（切工具/切页，死区 4px，锁定后同步跟手）；纵向手势不 `preventDefault`；仅当「纵向拖 2 帧后 iframe `scrollY` 仍无变化且内容可滚」才启用 JS `scrollBy` + 衰减惯性兜底；
   - 通知页刷新保位：父页只恢复 tab；iframe 内滚动由注入脚本 `zq_nt_scroll_v1` 自存自恢（260ms 落盘 + 加载后重试）；
   - 模板固定定位的弹层/编辑表单在父页渲染（保持）；
   - **不要**改回「父页滚动 + iframe 自适应 20,000px 高度」方案（2026-11-05 晚已因微信内滚动抽搐回退）。
3. **云端通知管理员覆盖**：`public.notices.override_json / hidden / edited_at / edited_by`（迁移 `deploy/cloudbase/2026-11-05_notice_admin_override.sql`）。
   采集端 `sync_notices_cloud.py` 不得写这 4 列；前端通知签名查询需 `select=id,ts,hidden,edited_at`。
4. **通知识别（briefdesk）**：`#接龙` 不进入通知；补充通知（supplements）可合并进已有通知（追加 item + 修正时间 + updatedAt）；
   人工补丁 `C:\briefdesk\data\notice-manual-patches.json` 最后应用、重建不丢；长期安排用 `recurrence`；
   QQ 文件缺失时前端显示「待获取」，本机 `fetch_qq_files.py --import-only` + `data/qq-files` 目录签名触发自动上线。
5. **同步契约**：userdata v6 `fit` section 必须含 `sex/grade`；`marks` 仍是通知已处理/作业完成唯一真源；
   本机待补发 overlay + 回前台/切页/刷新强拉 marks 的加固不得删除（否则跨端状态看起来「未同步」）。
   **电费关注宿舍**（2026-11-05 晚新增 section）：`power = {sel:"<roomverify>", at:<ms>}`，随 v6 同一套 LWW 合并/缓存/防抖/云端拉取；
   顶层键顺序 `v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,homeToolsAt`（13 键）；
   本机 `zq_power_sel_<sid>` 只作离线兜底，真源是 `UD.power`；小程序已拥有该 section（2026-11-06 v5 起）：`power={sel,at,low}`，低电阈值随账号同步；旧数据无 low 按 30。
   改 v6 契约必须同步更新两端 merge 期望 + `tools/tests/sync_check.py`。
6. **小程序审核相关**（2026-11-05 20:25 用户要求）：**不实现演示/审核模式，除“添加账号”外不加任何审核相关功能**；审核只靠云端测试身份（`private.class_ids.is_test=true`，`class_members` 过滤、不在班级名单显示，凭据不入仓库）；**AI 开发模式发版默认关闭**（`ai_toggle.py --off`，源码保留，`--on` 恢复）。
7. **全部页卡片拖动 v2（2026-11-06，增量 20）**：全部页卡片右上角三条横线 handle 可拖动，规则：①拖到顶部 `.tabs` = 加入/替换/调整工具栏顺序（写 `homeTools`，仍 ≤4，走既有 UD 同步契约）；②在全部页内拖动 = 调整卡片顺序，持久化 `localStorage zq_all_order_v1`（**仅本机偏好，不进 UD 同步**，换设备不跟随；`renderAllCards` 按此排序，未知新工具排末尾）。实现要点（勿回退）：插入位置按「指针所在网格行 + 行内 x 中线」算 + 候选连续 2 帧一致才落位（防 A→B→A 抽动）；重排后一次性批量读几何、WAAPI FLIP 让位（不要逐卡 `void offsetWidth` 强制重排）；rAF 只做落点/自动滚动，ghost 跟手在 move 事件里同步写 transform；工具栏命中区 = sticky `.tabs` + 下方 26px（离开迟滞 72px），命中时 `.tabs.drag-over` / 目标 tab `.drophl` / 插入线高亮，滚动时 `refreshBarRect()` 刷新 sticky 换位后的实时位置；指针进入视口上/下 90/110px 自动滚动；**`will-change` 只允许拖动瞬间的幽灵内联使用**（`v2_x5_anim_check` S8 口径）。**homeTools 只存用户选择（≤4）**：`renderTabs` 显示时仍按屏幕比例补齐 3/4 格但**不把补齐项写回**，`dropToTabs` 只在用户拖入时写真实选择（避免小程序只勾选 1–3 个时被网页补回 4 个）。测试：`tools/tests/v2_drag_check.py` **56 项**（含 K/L/M/N/O/P/Q 组）。
8. **电费慢更新提示（2026-11-06，13/16 号楼网关日更）**：趋势卡统计 24h history 相邻采样 `|Δq|>0.005` 的变化次数，≤2 次显示「数据更新较慢 · 上次变化 MM-DD HH:MM」（0 次「数据未更新」），估算可用 tile 加「参考」；不插值、不改真实阶梯；正常房间不显示。小程序同口径（`utils/power.js slowUpdate`）。
9. **通知合并与附件（2026-11-06，数据管线）**：`notice_merge.py` 跨源（微信/QQ 同 URL/同原文/高相似+冲突守卫）合并，保留 `mergedSources/crossSource`；`wechat_media.py` 微信附件采集（文件走本地明文、图片 V2 加密标「待获取」）；`archive_scan.py` 压缩包安全解压+内容识别+AI 摘要。模板产物由 `briefdesk-plan/build_notice_board.py` → `tools/build_notice_embed.py` 嵌入；改模板后必须重跑 embed。

10. **小程序工具页拖动排序 + 首页快捷编辑模式（2026-11-06，与网页拖动 v2 对齐；待用户上传发布）**：`pages/all` 删除「调整」按钮/排序弹层**与顶部「首页快捷」工具行**（页面只剩「全部工具」）。普通模式**无勾选框**：点工具打开、长按 350ms 拖动排序（跟手幽灵、2 列网格迟滞重排、边缘自动滚动、`page-meta` 锁滚动、拖后抑制 tap；说明文字「长按工具可拖动排序」）。首页快捷改为**按钮进入编辑模式**：标题行右侧固定按钮 `#home-edit-btn`（「编辑首页」⇄「完成」）；编辑态说明「点工具加入或移出首页快捷（最多 4 个）」，点 tile 切换（不打开工具；选中 = 主色描边 + 对勾徽标，未选 = 空心圆），勾满 4 个第 5 个 toast「最多选 4 个」，编辑态禁长按拖动，「完成」退出，`onShow` 强制退出；勾选结果只在工作台「常用工具」展示（无勾选空态引导）。数据：`homeTools`（UD v6，≤4）= 勾选集合（不再自动补齐；旧「全量顺序」首次读取迁移为前 4 勾选 + toolOrder，迁移仅在 `homeToolsAt===0` 时触发）；`toolOrder` = 「全部工具」顺序，**随账号云同步**：走 userdata v6 已有 `prefs.toolOrder`（不新增顶层键；`toolOrderSetAt>0` 才写，默认自然顺序不写；无基线抢 `at.prefs`，远端无该字段不清空本机；导出 JSON 含 `prefs.toolOrder`）。网页端不拥有 `prefs`、合并时原样保留；网页自己的「全部页卡片顺序」仍是本机偏好 `zq_all_order_v1`（不进 UD）。测试（**只用 miniprogram-automator + mp.screenshot，禁止 pyautogui/屏幕操作与 preview/auto-preview 手机推送**）：`unit.js` 226/0、`sync_contract_test.js` 31/0、`tool_sort_unit.js` 21/0（含工具顺序云同步/换设备用例）、`tool_sort_preview.js` 31/0（0 console error）、`staticcheck.py` exit 0；截图 `_shots_tool_sort2/`。
11. **电费趋势交互（2026-11-06，增量 21）**：网页/小程序趋势**禁止横滑**（无 scroll/代理/「横滑查看」）；24h/7d/30d 全采样按真实时间比例压缩铺满；点击/左右拖动按 x 命中最近**真实采样点**显示竖线+圆点+`HH:MM / MM-DD HH:MM · 电量 xx.xx 度`，同步 snap、松手保留、点空白取消；手势豁免（不切工具/不滚页）；空态不显示。网页/小程序气泡**固定显示在趋势图右上角上部（绘图区外，见 §4b-16）**；竖线+圆点仍按采样点定位，resize/orientation 只重算竖线/圆点与文字（无图内气泡 clamp/跟手）。
12. **网页返回键/登录首帧（2026-11-06，增量 21）**：tab/工具切换 `history.pushState`，`popstate` 回上一 tab 不退出；根层第一次返回 toast 并需双击退出；弹层打开时返回先关弹层；内部渲染用 `_silent` 防脏 history。HTML 初始 `<body class="auth-pending">` 首帧隐藏 `.wrap`，身份完成才移除（未登录门禁第一帧可见、已登录不闪）。
13. **云端迁移（2026-11-06）**：CloudBase 云函数+定时器已承载 `power_sync`（每小时:01）、`xgj_sync`（每2h:20）、`health_probe`（每5分钟）；本机任务保留 fallback；`health_beat` 默认只写 local 10 行（不再探测域名/TLS，避免网页暂停后每轮白等超时），云端 8 行（cloudbase/site_static/site_tls/dns_domain/tt_cloud/cloud_power_sync/cloud_xgj_sync/cloud_health_probe）归云函数；⚠️ **CloudBase 环境 2026-12-10 到期**需续费/迁移；详见 `C:\briefdesk\docs\云端服务迁移_20261106.md`、`CLOUDBASE.md`。
14. **课表去域名化 + 诊断 v2（2026-11-07，DNS 暂停改造）**：课表快照已内迁 CloudBase `public.site_assets`（`id='tt'`，RLS 有效班级 token 可读/管理员可写）；本机 `web/jwxt/tt_cloud.py` 在 `sync.py` 写盘后自动发布（失败不影响退出码/OSS 上传）；**小程序 `ttFetch` 改为 site_assets 优先、失败回退旧 ttUrl；网页 `ttSyncPull` 同源 `tt.json` 优先、失败回退 site_assets**。诊断 18 行 / 5 组（新增 dns_domain/tt_cloud/cloud_power_sync/cloud_xgj_sync/cloud_health_probe；云端巡检 15 分钟过期降级；网页暂停时 site_static/site_tls 显示「注意·已按备案暂停」不误报异常）。网页暂停/恢复开关：`C:\briefdesk\scripts\web_pause.py --on/--off/--status`（`public.site_config` 行 `web`）。**用户暂停 furina.fun DNS 前先 `--on`，恢复解析后 `--off`**。契约 `tools/tests/dns_pause_tt_health_spec.md`、`health_monitor_spec.md §9`；改造记录 `HANDOFF.md §39`。小程序改动需用户上传发布后才生效（版本仍 2.0.0）。
15. **自动化/截图/冒烟使用真实管理员 token 时必须阻断云端写（2026-11-07 教训）**：浏览器脚本若注入真实管理员 token 并允许页面云同步，会把无痕环境的默认状态（尤其 `UD.power={sel:"",at}`、visits 等）写回云端，覆盖旅行者真实的「关注宿舍」等选择（2026-11-05 桌面优化冒烟曾发生，见 `HANDOFF.md §37.7`）。统一入口：`tools/tests/_qa_v2/_cloud_guard.py` 的 `install_write_block(page)`（CDP Fetch：只放行 GET/HEAD/OPTIONS 与只读 `POST /rpc/`，其余 fail）——所有注入真实 token 的浏览器脚本在导航前调用；小程序自动化优先用测试身份。2026-11-07 起 `desktop_opt.py`、`live_smoke.py` 已加该拦截（实测 blocked=2: visits+userdata）。
16. **电费趋势信息气泡固定右上角（2026-11-07，增量 24）**：气泡**不放在图内**，固定在趋势图右上角上部（区间按钮行右侧、绘图区外）：网页 `.pw-trend-top` 包裹 `#pwRanges` + `#pwDetailTip`（静态布局 `margin-left:auto`、`max-width:calc(100% - 186px)`、窄屏折行、`[hidden]` 隐藏；删除跟手 `placeTip/_ptr/PW_TIP_GAP`），`.pw-trend-scroll` 保持 `touch-action:pan-y`；小程序同口径（`.pw-trend-top` + `.pw-cursor-tip{position:static;margin-left:auto}`，页面 `cursor={on,left,top,text}`，已删除 `_placeCursorTip/_cursorSeq/_cursorPos/_plotTop`）。竖线+圆点仍对准最近真实采样点；拖动只更新文字/游标。测试：`tools/tests/v2_power_tip_fixed_check.py` **21**、`mp-class-tools-tests/tip_fixed_unit.js` **5**（已挂 `unit.js`）。上线 644,988B/`603c4e5d…`；小程序需用户上传发布。
17. **电费 13/16 号楼「日更」特异性统计（2026-11-07，增量 25）**：慢频口径契约（规格 `tools/tests/power_cadence_spec.md` §1，**web `POWER` 与 mp `utils/power.js` 必须同口径**）——常量 `PW_CH=0.005 / PW_MIN_SEG_H=6 / PW_EXPECT_H=24 / PW_SLOW_BLD=["13号楼","16号楼"]`（mp `SLOW_BUILDINGS` + `SLOW_COVER_CHANGES=6`）；`slowStats(pts30,rowQ)` 用 **30d 真实变化点**（`eventsOf`：从首点起保留 |Δq|>CH 的点）分段：`dq>0.05 && dtH>=6h` 为有效用电段，中位阈值 `max(5, 4×中位数)` 剔异常大跌；**1 段**按预期 24h 折算 `drop/24*24` 且 `ref=true`（UI 标「参考」），**≥2 段**按 `Σdrop/ΣdtH*24` 时间加权且 `ref=false`；`isSlowRoom` = 楼栋 ∈ SLOW_BLD **且** 当前 24h 真实变化 <6 次（`>=6` 自动降级实时口径，防网关提速）；慢频房 `pull` **3 窗口 24h+7d+30d**（实时房 2 个；30d URL `limit=2000`、缓存 5 分钟、不插值）；`estimate` 通用守卫：24h/7d 窗口真实用电均 ≤0.05 度 → `valid=false`「数据积累中」，**不得再用 0.05 度/天下限伪造 ≥30 天**；UI：趋势头固定「日更」+ hero 更新时间=最后一个真实变化点（30 天无变化→「近 30 天无变化」）+ tile2 无下降副标「该区间无更新」+ tile4 用 30d `lastRecharge`（切档不变）+ 慢频阶梯线/真实变化点 `.pw-cdot`（≤60）+ `#pwTrendNote` 无更新提示（`pointer-events:none`）+ 平线垂直居中且 y 轴只标中心单刻度。**改口径必须 web + mp + spec + `v2_power_cadence_check.py`/`v2_power_slow_check.py`/`power_check.py`/`v3_power_diag_tests.js` 同改**（mp 端需用户上传发布；`VERSION` 仍 2.0.0、UD v6 不变）。

18. **诊断 v2 + 课表登录（2026-11-08，增量 26，网页已上传 OSS / 小程序待上传 / 安卓新增）**：① 诊断页 `#s-diag` **全员可见**（去 `admin` 门禁；门禁前 0 请求），`service_health` 读 RLS 已放宽 `auth_ok()`；设备诊断 10 项 + 异常自动/手动上报 `client_diag`（脱敏+指纹 10 分钟限频+单批≤3）；AI 分析/修复流程读 `diag_analysis`/`repair_tasks`（本机 agent 写入，15s 可见轮询，flow 时间线）；所有 detail/side/AI 文本必须过 `sensMask()`（IP / `C:\`路径 / URL / token=）。② 课表登录 `#tLogin`：密码 `type=password` 且提交后立即清空、不落 localStorage/日志/上报；`rpc/tt_login_enqueue`（仅 PGP 密文入云）→ 1.5s 轮询 `rpc/tt_login_status` ≤120s → 写 `tt.ttLocal` 走 UD v6 同步；**课表优先级 = 个人 ttLocal > 公共**。③ 本机代理：`C:\briefdesk\scripts\diag_agent.py`（`BriefdeskDiagAgent` 每分钟），负责 PGP 解密→纯 requests SSO（`web/jwxt/jwxt.py::sso_login_http`）→抓课表、AI 分析、白名单自动修复（recheck_health/restart_gateway/web_pause_on|off/sync_power/sync_xgj/refresh_timetable/redeploy_web；≤3/轮、单动作≤120s、不重复）。④ 云契约 `_diag_task/CONTRACT.md` + 迁移 `deploy/cloudbase/2026-11-08_diag_login.sql`（含 `client_diag.sid DEFAULT auth_sid()`；应用工具 `apply_sql.py` 逐条走 ExecutePGSQL 原始 API，**不要用 `tcb db execute` 跑含分号的函数体**）。⑤ 测试：`v2_diag_v2_check.py` 130/130、`v2_tt_login_check.py` 85/85、`v2_tt_frame_check` 140/0；小程序 `unit 257/0、v3 60/0、sync 33/0` + automator Lead 实跑 13/0；Android `test 779/0`、`assembleRelease` 2,577,485B。⑥ DNS 暂停期网页以 OSS 对象字节校验（`deploy/oss_object.py check index.html`）。


19. **诊断 v2.1（2026-11-09，增量 27，网页已上传 OSS / 小程序待上传 / 安卓更新）**：① **AI 结论下挂对应异常项**——删除独立 AI/修复卡；`diag_analysis` 按 `related.health_ids` 挂服务健康异常行、按 `related.checks` 挂设备检查行（agent 从 `client_diag.detail.check` 推导）；无关联进「其它诊断」默认收起。折叠一行（severity 点 + 标题≤22 字 + `⚙可自动修复` + 状态胶囊 待处理/修复中/已修复/修复失败 + `›`），点击展开 cause/建议/flow/关联修复（按 `related.repair_id` 关联 `repair_tasks`）。② **进展 10s**：AI/agent/repair 轮询 15s→10s（可见时；隐藏停止；进入立即拉）；agent 修复时先写 `diag_analysis.status='running'` + flow `本机开始执行 <action>`（st=run）再执行，页面实时显示「修复中」。③ **本机 agent v1.1.0（无人工/开机补跑）**：`diag_agent.py` catch-up（state 缺口 >180s → 忽略冷却、client_diag 上限 50、分析上限 20、修复上限 5）+ 自动修复扫描（不依赖当轮 AI；`status=new`+`fixable`+`scope in (cloud,mixed)`+`severity in (error,warn)`；analysis 级 + action 级去重：同 action 30min 内 done 跳过、failed 6h 冷却）+ `recover_stale_running`（>10min 中断标 failed）；计划任务 `BriefdeskDiagAgent` 新增 **LogonTrigger（登录后 30s）**，保留 TimeTrigger/StartWhenAvailable。关机期间 `client_diag` 在云端保留，开机首轮 catch-up 消费（实测：暂停 75s 新上报保持 new，恢复后一轮 backlog_diag=2 全 analyzed + 生成 related.checks）。④ **设备信息最小化（§B）**：`client_diag.device` 只允许 platform/os/webview(或 baseLib)/screen{w,h,dpr}/memoryGB(或 memoryMB)/storagePct/network/clockSkewMs；`detail` 只允许 check/latency_ms/storage_pct/clock_skew_ms/err_count/code；**`detail.check` 必带设备检查 id**（agent 归因用）；页面设备检查不再展示 UA/语言/品牌/IndexedDB。⑤ 契约 `_diag_task/CONTRACT_V2_1.md`；本机测试 36/36、网页 140/140、小程序 259/0+62/0+33/0+automator 23/0。⑥ 网页上线对象 **703,054 B / sha256 6cef5da1…**（OSS object check MATCH；含并行会话已验收的 OPTIM V1）；小程序需用户上传发布；安卓 release APK 见 `android-class-tools/docs/DIAG_LOGIN_20261108.md` 更新。⑦ DNS 暂停期仍以 OSS 对象字节校验为准。

20. **PPT 演示（2026-11-09，增量 28，网页已上传 OSS / 小程序源码待用户上传发布 / 安卓 3.3.0 APK 已交付 / 转换机计划任务已启用）**：① **需求**：教室电脑老旧，PPT 动画多会卡死、嵌入视频换机后「媒体不可用」→ 上传源文件，本机转换机一次性渲染**分步图片**（每页+每个点击动画步）并把**嵌入视频抽成 H.264**，三端只加载图片/MP4，任意设备流畅播放；任何班级成员可上传、全班共享演示库。② **唯一契约**：`web/ppt/CONTRACT.md`（表/RLS/接口/manifest v1/播放语义/三端要求/红线），设计参考 `web/ppt/DESIGN.md`（19 竞品拆解+三端交互规格+小程序域名查证）；转换机实现与运维见 `web/ppt/README.md`。③ **云端**：`public.ppt_decks` + `public.ppt_upload_chunks`（迁移 `deploy/cloudbase/2026-11-09_ppt_decks.sql`，RLS：全员读、本人写、转换机管理员 token 更新；删除=软删）；分片 512KiB/base64 经 PostgREST 上传（转完即删，**不要改成前端直传 OSS**——前端不能有 OSS 写凭据）。④ **媒体资产**：阿里云 OSS `tool-furina-fun` 公共读，直连域名 `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/`，`ppt/a/<deckId>/<buildId>/`（WebP 1600 主图/400 缩略图/MP4）+ `ppt/src/<deckId>/source.<ext>`；长缓存 immutable。⑤ **转换机**：`web/ppt/agent.py` + 计划任务 `PptConvertAgent`（系统 pythonw、Interactive only——PowerPoint COM 必须桌面会话、每分钟+登录后 30s、单实例、StartWhenAvailable）；PowerPoint 忙（用户有打开文档）时本轮跳过；失败路径 PATCH `failed`+中文 error+清分片；心跳写 `site_assets id='ppt_agent'`（客户端 180s 判离线）。⑥ **网页**：`index.html` 内 `__PPT_FEATURE_V1__` 块（列表/上传/播放器；CSS 在 `</style>` 前、HTML `#s-ppt` 在 `#s-all` 前、JS 在 OPTIM V1 块前；TOOLS 加 `ppt`，gotoTab/滑动引擎各 1 行挂钩），**保持单文件零依赖、APP_VER 2.0.0**；专项 `tools/tests/v2_ppt_check.py` **86/86**；真实端到端（真实云端 deck + 真实 OSS 图片/视频）Lead 用 CDP 脚本实跑 PASS（桌面+430px 触摸滑、视频热点 `paused=false`、0 JS error）。⑦ **小程序**：`utils/ppt.js` + `pages/ppt` + `pages/pptplay`（`<image webp="{{true}}">` 必须保留，否则真机 .webp 全白）；`unit 297/0、ppt 38/0、sync 33/0、staticcheck exit 0`；**发布前用户需在微信公众平台把 OSS 域名加入 request+downloadFile 合法域名并真机正式版验图/视频**（香港默认域名能否过微信校验未查证）。⑧ **安卓**：`data/ppt`+`features/ppt`+`ui/screens/ppt`，自建 OkHttp/BitmapFactory 图片加载与 VideoView，无新依赖；`testDebugUnitTest 904/0`（新增 87）、`assembleRelease` 2,692,174B（3.3.0/vc9）。⑨ **已知取舍（如实）**：分步图取「每步最终视觉态」→同段逐字出现会合并、强调/运动路径取快照、自动动画合并为当页最终态（内容不丢）；外链媒体跳过；转换机离线只排队；隐藏页仍转换；单 deck ≤64MiB/≤300 页/图 ≤260/页 step ≤12；重转换旧 buildId 不自动删。⑩ **回滚**：网页重传 `tools/_backup/index_online_20261109-2220_prePPT.html`（732,621B/`65610511…`）；禁用计划任务 `schtasks /Change /TN PptConvertAgent /DISABLE`；表可 DROP（不删无碍，仅冗余）；小程序/安卓回退到上一版源码。⑪ **上线与独立验收**：网页 2026-11-09 23:04 已部署，线上对象 **800,243 B / sha256 `4412f5fc…`**，`deploy/oss_object.py check index.html` = **MATCH**（DNS 暂停期以 OSS 字节为准，恢复解析后生效）；独立 QA 报告 `web/验收报告/PPT演示_独立验收_20261109.md`——功能验收 **PASS**（脚本断言 1,574 项 / 0 失败；网页 86/86 + 真实 E2E 3/3（含视频 deck 真实播放）+ 回归全绿；小程序/安卓/转换机/DB 全过），唯一 P0「网页未部署」已由 Lead 部署消除，剩余 P2 见报告（播放器封面阶段页码占位 1/1、云端测试数据交付前清理、mp 按钮文案「上传」等）。

21. **迁移第 1–3 步（2026-11-10，增量 29，网页已上线；附件外置三端源码均已改造，待备案通过后统一发布）**：① **ECS 备案落点**：`deploy/ecs_site.py` 通过阿里云**云助手 RunCommand**（无需 SSH，22 只放行家庭 IP）把 OSS 最新静态站同步到 `/var/www/tool`、写 Caddy（gzip/zstd + 缓存头 + `/api`/`/board`/`/att`/`/v1/rdb/rest` 路由）并验证；ECS `index.html` = 802,355 B / `e40571d3…`；HTTPS 就绪配置在 `/etc/caddy/Caddyfile.https.ready`，备案 + DNS 恢复后 `python deploy\ecs_site.py apply --https` 启用（Caddy 自动 Let's Encrypt）；详细运维见 `deploy/ECS_DEPLOY.md`。② **通知附件外置**（签名 URL）：ECS `class-tools-att.service`（127.0.0.1:8091，`/opt/class-tools/att-code`，数据 `/opt/class-tools/attachments`），Caddy `/att/*` 反代；契约 `attachments/CONTRACT.md`（URL/签名/字段/安全），本机管线 `sync_notices_cloud.py` 用 `NOTICE_ATTACH_EXTERNALIZE=1` + `ATT_BASE_URL=https://tool.furina.fun` 开启（**默认关闭**；等备案通过 + 三端新版发布后一起开，存量 41 个附件自动回填）；网页模板已兼容 URL/data URI 双形态（`v2_attach_url_check.py` 9/9）；小程序 `nt.js`（unit 305/0）与安卓（testDebugUnitTest 934/0）源码已支持 URL 双形态，等备案 + 微信 downloadFile 域名配置后随三端发布。③ **同源/缓存**：网页 `var CB` **字面量必须保留**（本机脚本用它解析网关），运行时在 `tool.furina.fun`/`121.196.47.2` 下改走同源 `/v1/rdb/rest/*`（ECS Caddy 反代 CloudBase 网关，`header_up Host` 已设）；静态资源 gzip 32.5% + 长缓存。**任何以上改动必须走 `sync-repos.cmd` 双远端推送。**
