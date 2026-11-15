# 学信网入口（三端中的安卓 App + 网页）实现规格 · 2026-11-15

> 用户需求（2026-11-15 13:50）：「以相同方式引入学信网入口，同样将内部常用工具做成卡片，整体页面要适配手机」。
> 已确认口径（本次点选）：
> 1. **范围 = 安卓 App（卡片页 + 数据卡）+ 网页（站内「学信网」卡片页，仅官方工具入口、不抓数据）**；小程序不动。
> 2. **卡片 = 数据卡**：安卓端在你**手动登录学信网**后，从官方页面取学籍/学历/学位等摘要数据展示（学信网有短信/验证码/实人核验，**无法自动登录**；不保存学信网账号密码）。
> 3. **整体页面适配手机**：网页卡片页 360/390/430 无横向溢出、2/3 列自适应、点按 ≥40px；安卓卡片页窄屏 2 列/宽屏 3 列、适配状态栏/导航栏安全区。

## 0. 事实与红线

- 学信网官方站点对手机 UA **自带 wap 自适应**（实测 2026-11-15）：
  `https://www.chsi.com.cn/` → `/wap/index.jsp`；`https://my.chsi.com.cn/archive/index.jsp` → `/archive/wap/index.jsp`；
  `https://yz.chsi.com.cn/` → `/wap/`；`https://www.chsi.com.cn/xlcx/lscx.jsp` → mobile 学历查询；`https://www.chsi.com.cn/xlcx/bgcx.jsp` → mobile 在线验证报告查询。
- **学信网登录不可自动化/不可代填**：登录页 `https://account.chsi.com.cn/passport/login`（`#fm1` POST，账号+密码，通常附加验证码/短信/实人核验）。
  → 安卓端只做「打开官方登录页由本人手动登录」，**不保存、不预填、不上传学信网账号密码**；不调用任何学信网写接口。
- 数据只在本机展示：安卓端从已登录的官方页面提取文本摘要，**不得上传/同步/写日志/导出**；展示前对身份证号/手机号做掩码，卡片不显示完整证件号。
- 网页端受浏览器跨域限制，**不抓取、不内嵌**学信网，只做官方工具入口卡（`<a target="_blank" rel="noopener noreferrer">`）。
- 测试红线（AGENTS §0-7）：自动化测试只用合成夹具/假数据，**不得使用真实学信网账号**；真机验证由用户本人完成。

## 1. 官方工具与 URL（2026-11-15 实测，全部可访问/跳转合理）

| # | 卡片名 | 说明 | URL | 需登录 |
|---|---|---|---|---|
| 1 | 学信档案 | 学籍·学历·学位 | `https://my.chsi.com.cn/archive/index.jsp` | 是 |
| 2 | 学籍/学历查询 | 公开查询 | `https://www.chsi.com.cn/xlcx/lscx.jsp` | 否 |
| 3 | 学位查询 | 公开查询 | `https://www.chsi.com.cn/xwcx/index.jsp` | 否 |
| 4 | 在线验证报告 | 申请/查看报告 | `https://my.chsi.com.cn/archive/bab/index.jsp` | 是 |
| 5 | 报告在线验证 | 用人单位核验 | `https://www.chsi.com.cn/xlcx/bgcx.jsp` | 否 |
| 6 | 学历认证报告 | 认证服务 | `https://www.chsi.com.cn/xlrz/index.jsp` | 否 |
| 7 | 照片校对 | 校对学历照片 | `https://my.chsi.com.cn/archive/xlzp/index.jsp` | 是 |
| 8 | 研招网 | 考研报名/成绩 | `https://yz.chsi.com.cn/` | 部分 |
| 9 | 学职平台 | 就业/职业发展 | `https://xz.chsi.com.cn/` | 部分 |
| 10 | 帮助中心 | 常见问题 | `https://www.chsi.com.cn/help/` | 否 |
| — | 登录/注册 | 学信网账号 | `https://account.chsi.com.cn/passport/login` | — |

## 2. 网页端（web/tools/index.html）

- 新增工具 `{k:"chsi",n:"学信网",d:"学籍 · 学历 · 学位；官方入口卡"}`（**追加在 TOOLS 末尾**，jw 之后）；`ALL_TONE.chsi="blue"`。
- 新增 `<section id="s-chsi">`（放在 `#s-jw` 原位置附近/`__WEB_B2_FILE_BEGIN__` 之前，`__CHSI_ENTRY_V1_BEGIN__/END__` 包住）：
  - 头部卡片：标题「学信网」+ 副标「中国高等教育学生信息网 · 官方入口」+ 一行小提示「学信档案/照片校对需登录学信网账号」。
  - 卡片网格：上表 10 项，每卡 = `<a class="chsi-card" href="URL" target="_blank" rel="noopener noreferrer">`，含短名 + 说明 + 可选「需登录」小徽标；点按区 ≥44px。
  - **手机适配**：CSS grid `repeat(auto-fill,minmax(140px,1fr))`（360→2 列，430→2 列，≥640→3 列，≥960→4 列）；卡片文字 `overflow-wrap:anywhere`；页面 360/390/430 无横向溢出；不得用固定宽度/横向滚动。
  - 注意：加载页面时**不得请求学信网/任何外部资源**（仅链接，点击才跳转）；单文件零依赖；`APP_VER` 仍 2.0.0。
- 使用说明 `__UG_CARDS_V1__` 增加 `chsi` 卡（cat:"study"，标题「学信网入口」；18→19 张，需同步更新 `tools/tests/v2_ug_check.py` 计数期望）。
- 测试：新增 `tools/tests/v2_chsi_check.py`（参照 v2_ug_check/v2_jw_check：本地 HTTP + Edge CDP + 测试身份 `SID=9999000005`）：
  静态：section/TOOLS/ALL_TONE/10 链接 href+target+rel/UG 卡/APP_VER/无外部资源引用/单文件；
  运行时 430/360/390/1280：进入页面（`gotoTab("chsi")` 与全部页卡片点击）、10 卡渲染、网格列数（360/390/430 = 2 列；1280 ≥3 列）、无横向溢出、0 JS 报错/0 console.error、加载阶段 0 外部请求（performance resource 校验不含 chsi.com.cn）、点按高度 ≥40px；截图 `tools/tests/_shots_chsi/`。
  回归：overflow 360/390/430、v2_ui 27、v2_drag 69、v2_ug（19 卡）、optim_v1/v2 GREEN。
- 文档：CHANGELOG 增量 57、HANDOFF 增量 57、AGENTS §4b 追加精简条目（编号顺延；若动 AGENTS 先与 Lead 确认）。
- **不部署、不 commit**（Lead 统一部署 + 双远端提交）。

## 3. 安卓端（android-class-tools，版本 4.53.0 / vc71）

### 3.1 页面与交互
- 新增工具 `id="chsi"`、name「学信网」、subtitle「学籍 · 学历 · 学位 · 官方入口」、icon（建议 `Icons.Rounded.Verified`）、accent=BrandSlateBlue、category=STUDY；`MainNavHost` 加 `"chsi" -> ChsiEntryScreen(sid = session.sid, onBack = { popTool(...) })`。
- 点「学信网」卡 → `ChsiEntryScreen`：
  - **进入即加载** `https://my.chsi.com.cn/archive/wap/index.jsp`（隐藏 WebView）：若被重定向到 `account.chsi.com.cn` 登录页 → 全屏显示官方登录页（本人手动输入 + 验证码/短信/实人核验），App **不预填、不保存密码**；登录成功（URL 回到 `my.chsi.com.cn` 且非 account）→ 提取数据并显示卡片页。
  - **卡片页**（Compose，同 App 现有卡片风格）：
    - 状态条：「已登录学信网 · 数据更新 HH:mm」/「未登录或会话过期」+ 按钮「去登录」「刷新」。
    - 『数据』2 列卡片（从已登录官方页面文本摘要提取；提取不到显示空态 + 「打开官方页面查看」）：
      1. 学籍信息（学校/专业/学籍状态/入学时间等，能取到的行）
      2. 学历信息（院校/专业/学历/毕结业结论等）
      3. 学位信息（学位/专业/授予时间等）
      4. 在线验证报告（有无报告/状态，取不到则入口态）
    - 『官方工具』2 列（或宽屏 3 列）入口卡：§1 的 10 项（点卡 → 内置 WebView 全屏打开官方页面；返回回卡片页）。
    - 底部：「打开完整学信档案」+「退出学信网登录」（清 Cookie/WebStorage/缓存，回登录态）。
  - WebView 顶栏：标题 + 返回 + 「桌面版/手机版」切换（UA 切换 + reload，便于个别页面兼容）；WebView 仅允许 `http(s)` 导航、禁 file access、开 JS/DOM storage/Cookies。
- **手机适配**：卡片网格窄屏（<600dp）2 列、≥600dp 3 列；滚动容器 `LazyColumn`；适配状态栏/导航栏安全区；卡片文字最多 3 行省略；点按区 ≥48dp；深浅色主题 token。**本轮要作为验收硬指标**（用户在 OnePlus 上查看）。
- 数据提取（无法用真实账号验证，按官方 wap 页面通用结构做**宽容提取 + 降级**）：
  - 注入 JS 返回 JSON：`{url,title,text,links:[{t,h}]}`（`document.body.innerText` ≤6000 字符；`a[href]` 中 host 含 `chsi.com.cn` 且文本 ≤20 字）。
  - Kotlin 解析：`text` 按行分块；用标签（学籍信息/学历信息/学位信息/在线验证报告/学籍状态/院校/专业/学历/学位）就近取 1–3 行；**展示前掩码** 18 位身份证、11 位手机号（`****`），不显示完整证件号；提取不到 → 卡片显示「已登录 · 打开官方页面查看」。
  - 不保存提取结果（仅内存）；不上传/同步/日志。
- 安全：WebView Cookie 仅本机；不保存学信网账号密码；退出登录清理；`sensMask` 类似掩码；不调用官方写接口。
- 单测（纯 JVM，合成夹具，无真实数据）：提取 JSON 解析/字段映射/空态降级/掩码（身份证/手机号）/10 个官方工具常量与 URL/UA 切换常量；`testDebugUnitTest --no-daemon` 全绿。
- `assembleRelease --no-build-cache --no-daemon` → `artifacts/classtools-4.53.0-release-signed.apk`（记录大小/SHA-256）。
- **并行冲突口径**（同前）：仓库当前有并行会话未提交 WIP（HEAD 040473e v4.50.0，工作树 v4.52.0/vc70 + OPPO 推送/地图等新文件）→ 新增文件先写；共享文件（ToolCatalog/MainNavHost/GuideContent/UserGuideContentTest/build.gradle/docs/CHANGELOG）先落 pending patch，监控静默 ≥3 分钟且 `compileDebugKotlin` 通过后精确 edit；版本若被并行占用则顺延。
- **禁止用真实学信网账号跑自动化测试**；真机由用户本人验证，未验证要如实说明。

## 4. 验收（三端范围：网页 + 安卓；小程序不动）

- 网页：`v2_chsi_check` 全绿 + 回归全绿；Lead 部署 OSS+ECS 并校验字节；手机截图目检。
- 安卓：单测全绿、APK 产物核验；Lead 复核代码无凭据落盘/上传、卡片数据仅内存、掩码生效。
- 文档：CHANGELOG/HANDOFF/AGENTS 增量 57（网页仓库）；安卓 docs/CHANGELOG v4.53.0。
- 回滚：网页重传部署前备份；安卓删除 chsi 文件 + 回退 ToolCatalog/MainNavHost/版本号，APK 回退上一版。
