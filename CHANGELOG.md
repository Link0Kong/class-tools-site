# CHANGELOG — 班级工具站（tool.furina.fun）

> 每次上线记一条：时间 / 内容 / 回滚点。部署命令：`python deploy/sync_tools.py`。

## 2026-11-11 12:4x · PPT 下载加速（网页端）：下载详情优先走 ECS 缓存 `/pptfiles` + 备用 OSS 直链（**本地完成，待 Lead 部署网页；ECS 已上线**）

> 背景（Lead 任务）：实测本机→OSS 香港单连接 74KB/s、用户→ECS 杭州 4.7MB/s；ECS 提供 `/pptfiles/ppt/a/...` 缓存下载（服务由另一 agent 部署，地址 `http://121.196.47.2/pptfiles/`，https 备案后同源 `/pptfiles/`）。本次把网页下载详情的三行下载链接改为优先走 ECS 缓存，OSS 保留为「备用」。
> 写作用域：`tools/index.html`（PPT 块内增量）+ `tools/tests/` + 本 CHANGELOG；未改其它文件、未部署、未 git。

- **链接选择 `pptDlHref(man,f)`**：先用 `resolveUrl(manifest.base, files.s)` 得 OSS 绝对 URL 并解析 pathname；`/ppt/...` 路径时——http 页面 → `http://121.196.47.2/pptfiles` + pathname；https 页面 → `location.origin + "/pptfiles"` + pathname（为 tool.furina.fun 备案后同源反代预留）；非 `/ppt/` 路径、`data:`/`blob:`、解析失败 → 回退原 OSS 直链。
- **fileRow**：主「下载」按钮改用 ECS href（`<a href=… download=name>`，下载文件名/人类可读大小不变）；按钮下方新增**小字「备用」**链接指向原 OSS 直链（`title="备用下载（较慢）"`、同一 download 名），ECS 未就绪/失败时可自选；回退场景（主链接即 OSS）不重复显示「备用」；「未生成 · —」行不变。按钮组竖排 `.ppt-file-a`，暖白卡片/雾青主按钮风格不变。
- **顺带修正**：存量 deck 补转 compat 后（既有 `files` 又保留旧 `slides/video`），详情现在按契约 §12.4.1 显示**次要「在线预览」**按钮（此前仅无 files 的旧 deck 才有），下载为主、预览为次。
- **测试（真实输出，最终稳定合并文件 920,140 B / sha256 `489c87eaf55ab19dc26b443152929baa6de1c7c8fe25425b4c32cf82304c5298`；mtime 12:51:39，并行投票/大屏改动均在内）**：
  - [`v2_ppt_download_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_download_check.py) **51/51 PASS**（新增/更新：http 页面三行主 href 均以 `http://121.196.47.2/pptfiles/ppt/a/` 开头、download 文件名/大小不变、备用=原 OSS 且 title 正确、非 /ppt/ 路径回退 OSS 且不显示备用、存量补转 deck 三行 ECS +「在线预览」可进旧播放器、430px 文件行不溢出、0 JS 报错/0 console.error/0 真实云端写）
  - 既有 [`v2_ppt_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_check.py) **92/92**、[`v2_ppt_video_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_ppt_video_check.py) **100/100** 全过（详情/下载/播放器交互不回归）
  - 回归（真实输出）：`overflow_check 430`=**0**、`v2_ui_check` **27/27**、`v2_pos_restore_check` **12/12**、`v2_x5_anim_check` **28/28**、`v2_drag_check` **56/56**
  - 真实 deck `dmwalrdlgevz90l`（本地 http 页面）：详情三行主 href 实测为 `http://121.196.47.2/pptfiles/ppt/a/dmwalrdlgevz90l/c0e5834805/{compat.pptx,preview.pdf,original.pptx}`，备用均为 `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/...`（title=备用下载（较慢）），下载名=原中文名；详情同时保留「在线预览」；0 JS error。
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
  - 真实 deck `dmwalrdlgevz90l`（旧 v1 manifest，无 files，16 页/36MB）：headless Edge 实跑——列表卡片「16 页 · 36MB · 16 步 · 陈子麒」、无标签无列表播放按钮；点击卡片 0.08s 内打开详情：「兼容版未生成 + 原始文件 36MB（OSS `ppt/src/.../source.pptx`，download=source.pptx）+ 在线预览 + 重新处理」；点在线预览进原播放器（`ppt-vmode`、真实 deck.mp4 `readyState=4、paused=false、err=0`），0 JS error；生产轻量标签查询实际 URL `ppt_decks?select=id%2Cfiles%3Amanifest-%3Efiles&deleted=eq.false&limit=100` 返回 200。
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
- **③ 同源/缓存（已完成）**：网页 `CB` 在 `tool.furina.fun`/`121.196.47.2` 下运行时改走同源 `/v1/rdb/rest/*`（ECS 反代 CloudBase 网关，消除 CORS 与跨云一跳；`var CB` 字面量保留给本机脚本解析）；静态站 gzip 32.5%。
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
- **验证**：新增 [`v2_notice_quality_check.py`](C:/Users/Ko_Li/.openclaw/workspace/web/tools/tests/v2_notice_quality_check.py) **16/16**（过期/河洛/多窗口/附件/去噪/分类阈值/0 JS 错）；`v2_notice_dynamic_cat_check` **18/18**、`v2_notice_data_check` **27/27**（此前存量 D22 因质检重新生成要点后也转绿）、`v2_notice_live_check` **16/16**、`v2_admin_check` **39/39**、`v2_ui_check` **27/27**、`v2_notice_time_check` **64/72**（较改前基线 62/72 提升，剩余 8 项为存量花名册/献血断言）、`overflow_check 430`=0、`_check_template_embed_match`=YES；`detect_docs.py --rebuild` 端到端 exit 0 且完全幂等（quality called=0、categories cached、66 组稳定）；本轮未改小程序/安卓。顺带修掉 `detect_docs.py` 控制台 cp936 遇 emoji 标题崩溃的隐患（stdout 强制 UTF-8 replace，--watch 长期稳定）。
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

> 用户反馈 6 条：申报材料截止时间错误/相对日期、时间显示不统一、活动报名优先报名时间、申报材料两条未合并、天城企鹅未映射班委、本人发布通知未识别。
> 契约：`C:\briefdesk\scripts\通知时间显示与识别_契约_20261105.md`；说明：`C:\briefdesk\scripts\通知时间显示与识别_修复说明_20261105.md`。

### 一、通知模板（iframe 模板，build_notice_board.py → build_notice_embed.py）

- 时间区域统一 **「<时间> <动作>」**：`fmtWhen`（<1h 分钟后 / <24h 小时后 / <7d 天后 / 其他与已过绝对 MM-DD HH:MM）；
  报名优先（`signupStart/signupEnd` → 报名开始/报名截止/报名已截止）；`deadlineAction`/`eventAction`（缺省 截止/开始）；
  长期安排 `长期安排 · label`；修掉「明天 12:00 显示成今天 12:00 截止」旧 bug；简报「最近截止」同口径。
- 消息文本相对日期替换 `absRelDates`：今天/明天/今晚/明早/本周X/下周X/裸周X → MM-DD（锚点=首条 item.time；
  作用于 AI 摘要/要点/segments/原文/补充通知/合并转发/原始消息弹层）。
- 合并/多消息卡渲染全部原文 item（不再被 aiSummary 隐藏）；透传 `aiMerged/supplement/updatedAt`（「已更新」徽标）。
- 发送者身份映射：class-members + class-identities + class-aliases，网名「天城企鹅」→ 兰佳杰/学习委员/班委。

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
- 验证：真宽度 320/360/390/430/601/720/844/1280 全部 `overflow=0`、0 JS 报错、全部栏按钮底差 0px；手机 320–430 身份名不截断（陈子麒）且角标/点隐藏，601+ 恢复完整；通知页 390/1280 内嵌模板卡片渲染正常；draw 导出正常；线上 `index.html` **sha256 MATCH**（316,967 B）。
- 回滚点：`tools/_backup/index_online_20261104-2058_preMobileTopCard.html`。

## 2026-11-04 · 全部栏卡片莫奈配色 + 按钮底部对齐

- **卡片配色统一到莫奈系**：「全部」页卡片底色改 `#FFFCF6`、描边 `#E7DED0`；页眉按工具族着色（课表雾蓝 `#EDF2F7`、作业/反馈睡莲青 `#EAF2EC`、抽签/体测暖沙 `#FAF3E6`、班委/点名/统计紫 `#F1EEF7`、通知灰粉 `#F7EDEB`、使用说明中性 `#F3F1E9`）；「打开」按钮跟随卡片色，「设为首页」保持描边幽灵样式；描述文字 `#6E7A72` 提高可读性。
- **按钮底部对齐**：卡片改纵向 flex，`.bd` 撑满、按钮行 `margin-top:auto`，同一行卡片高度一致时按钮贴底对齐（修复点名/反馈等卡片按钮高低不齐）。
- 「全部」卡片色调映射在 `renderAllCards()` 的 `ALL_TONE`；分组结果卡（`.gcard` 非 `.tool`）不受影响。
- 验证：真宽度 360/430/720/1280（管理员 10 卡 / 普通 9 卡）全部页 `overflow=0`、同行按钮底差 0px、逐卡点击打开对应页、0 JS 报错；draw 导出图参数/水印/时间/编号正常；线上 `index.html` **sha256 MATCH**。
- 已知：`tests/selfcheck.py` 仍是身份门禁重构前的旧脚本（HANDOFF §11 已注明），本次以「全部栏专项审计」替代 ①，②③④ 照跑。
- 回滚点：`tools/_backup/index_online_20261104-2040_preAllCardColor.html`。

## 2026-11-04 · 身份门禁重构：学号+姓名进入 + 班委/账号统计

- **旧登录全部移除**：网页不再有账号/密码/注册/旧管理员入口，`users`/`identity_verify` 旧登录表已从 CloudBase 删除；管理员身份改由班级名单中的 `is_admin` 决定（陈子麒 / 3260707024）。
- **启动身份页**：网页打开先显示身份门禁，输入「学号 + 姓名」→ `rpc/class_verify`；通过后才拉取班级名单（70 人）、作业、通知、marks、体测与课表，未通过前不发任何班级数据请求。
- **新名单权威**：`private.class_ids` 重建为官方 XLS 花名册的 70 人；旧 `admin` 数据迁到 3260707024，旧 `xzx/xsx` 数据迁到谢梓萱 3260707026。旧管理员 `admin` 不再可用。
- **班委名单**：新增「班委」工具页，展示 `role/badge` 身份气泡；已按《关于公布2026级班委会拟定结果的通知》导入 **18 名班委**（班长陈玉霞、团支书谢梓萱、副团支书陈子麒、学习/生活/纪律/文娱/劳动/体育/心理/组织/宣传/廉政监督员），按官方职务顺序展示；管理员仍可在班委页点「管理」调整。
- **统计改为按账号**：`visits` 新增 `sid/name`，前端埋点写当前身份；统计页只管理员可见，按账号聚合访问次数/最近时间/近 7 天，旧匿名行忽略。
- **CORS**：网页 token 走网关已放行的 `X-Device-Id` 头（服务端同时接受小程序的 `X-Class-Token`），修复 `X-Class-Token` 被浏览器预检拒绝的问题。
- 验证：线上输入陈子麒/3260707024 成功进入、名单 70 人、班委页 **18 条**、统计按账号、console errors 0；本地 identity/committee/stats 截图通过；未登录时数据接口返回空/拒绝。
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
- notices.audience + RLS 服务端过滤；红会群仅 3260707024，班委群仅班委，其余 all；写权限收紧管理员；已验证 19/18/18/0。

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
  （其中「长言木」「🗿」两个网名群成员已按用户确认映射为张誉权、孙博文）。
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
  管理员统计页出现 2 个账号（陈子麒/李学盈）、无学号（截图 `tools/tests/_shots_stats/live_stats_admin_430.png`）；
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

