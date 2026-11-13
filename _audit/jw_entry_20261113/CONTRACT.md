# 教务入口（三端）实现契约 · 2026-11-13

> 需求（用户原话）：「帮我在班级工具站三端加个教务网站的入口」。
> 已确认的口径（2026-11-13 18:38 用户点选）：
> 1. 指向 **新版教务管理系统** `http://210.34.74.77/sso.jsp`（学校统一身份认证 SSO，登录后回到教务系统；站内课表数据也来自该系统）；
> 2. 形态 = **新增「教务」工具卡**（全部页可拖入顶部工具栏），三端一致。

---

## 0. 已实测事实（不要在实现里改动这些前提）

- `http://210.34.74.77/sso.jsp` 返回 JS 跳转：
  `https://authserver.fjtcm.edu.cn/authserver/login?service=http%3A%2F%2F210.34.74.77%2Fsso.jsp`；
  2026-11-13 从非校园网实测 HTTP 200 可达（本机 `web/jwxt/sync.py` 每日同步也用它，链路已长期验证）。
- 教务系统只有 HTTP、没有 HTTPS。**只能做顶层导航**（`<a target="_blank">` / Android `ACTION_VIEW`），
  不得 iframe 内嵌、不得作为子资源（避免混合内容与 CORS）。
- 校方口径：校外访问教务建议先连学校 VPN（页面上保留一句提示即可，不做探测）。
- 禁止在页面加载时对教务站发任何请求；禁止采集/保存账号密码。

## 1. 统一标识与文案（三端必须逐字一致）

| 项 | 值 |
|---|---|
| key / id | `jw` |
| 工具名 | `教务` |
| 短描述（web `d` / mp `meta` / android `subtitle`） | `成绩 · 选课 · 考试` |
| 长描述（mp `desc` / 卡片说明） | `学校新版教务管理系统：成绩、选课、考试安排；统一身份认证登录` |
| 页面标题 | `教务管理系统` |
| 主按钮 | `打开教务系统` |
| 次按钮 | `复制链接` |
| 链接 | `http://210.34.74.77/sso.jsp` |
| 提示行 | `统一身份认证登录 · 打不开时先连学校 VPN` |
| 复制成功 toast | 网页 `链接已复制`；小程序/安卓 `链接已复制，请在手机浏览器打开` |
| 色调 | 网页 `ALL_TONE.jw="blue"`；小程序 `tone:"primary"`；安卓 `BrandSlateBlue` |
| 图标 | 网页 🏫；小程序 🏫 + `images/tool-jw.png`（96×96 透明底白色 glyph）；安卓 `Icons.Rounded.School` |

## 2. 三端要求

### 2.1 网页（仓库 `web/`，唯一改动 `tools/index.html` + 测试/文档）

- `TOOLS` 数组 **末尾**追加 `{k:"jw",n:"教务",d:"成绩 · 选课 · 考试；统一身份认证直达教务系统"}`；
  `ALL_TONE.jw="blue"`。**不要插在数组中间**（避免改变现有工具栏补齐/滑动顺序）。
- 新增 `<section id="s-jw">`，位置：`#s-vote` 之后、`<!-- __WEB_B2_FILE_BEGIN__ -->` 之前，用
  `<!-- __JW_ENTRY_V1_BEGIN__ -->` / `<!-- __JW_ENTRY_V1_END__ -->` 包住：
  - 卡片含：标题「教务管理系统」+ 短描述；主按钮必须是真实 `<a class="btn pri" href="http://210.34.74.77/sso.jsp" target="_blank" rel="noopener noreferrer">打开教务系统</a>`；
    `<button class="btn ghost" id="jwCopy" type="button">复制链接</button>`；URL 小字（`http://210.34.74.77/sso.jsp`）；提示行。
  - 点按区域 ≥40px；手机 360/390/430 无横向溢出；不改其它页面。
- CSS：`</style>` 前新增 `/* __JW_ENTRY_V1_CSS__ */` 块（少量 `.jw-*` 规则，不引外部资源）。
- JS：`</body>` 前（UG 块之后）新增 `/* __JW_ENTRY_V1_JS__ */` IIFE：绑定 `#jwCopy` 复制（复用现有 `copyText()`/`toast()`，见 index.html 约 3508–3513 行），
  暴露只读探针 `window.JW={url:"http://210.34.74.77/sso.jsp"}`；不新增定时器/轮询/网络请求。
- 使用说明 `__UG_CARDS_V1__` 的 `CARDS` 增加一张 `jw` 卡（`cat:"study"`，标题「教务入口」，复用现有 scene，不新增配图）。
- 文档：`CHANGELOG.md` 顶部加本次条目；`HANDOFF.md` 末尾按现有「增量」格式追加一节；`AGENTS.md` §4b 末尾追加一条精简条目（编号顺延）。
  `APP_VER` 保持 `2.0.0`。
- 测试：新增 `tools/tests/v2_jw_check.py`（参照 `v2_ug_check.py`：本地 HTTP + Edge CDP + mock fetch + 测试身份 `SID="9999000005"`）：
  - 静态：section/TOOLS/ALL_TONE/UG 卡/锚点 href+target+rel；`APP_VER` 不变；零外部资源；加载阶段不请求 210.34.74.77。
  - 运行时 430/360/390/1280：`gotoTab("jw")` 与「全部」卡片点击两条路径都能进页；主按钮可见且 href 正确；
    复制按钮点击不报错且出现 toast；0 JS 报错、0 console.error、0 外部请求、无横向溢出。
  - 截图落盘 `tools/tests/_shots_jw/`。
  - 回归（按现有命令实跑）：`overflow_check`、`v2_ui_check`、`v2_drag_check`、`v2_ug_check`、`optim_v1_check`/`optim_v2_check` 全绿。

### 2.2 小程序（仓库 `mp-class-tools/`，工作区同级目录）

- `utils/tools.js` 的 `TOOLS` **末尾**追加：
  `{ key:'jw', name:'教务', ico:'🏫', icoImg:'/images/tool-jw.png', meta:'成绩 · 选课 · 考试', desc:'学校新版教务管理系统：成绩、选课、考试安排；统一身份认证登录', url:'/pages/jw/jw', tab:false, tone:'primary' }`
- 新增 `pages/jw/jw.{js,json,wxml,wxss}`；`app.json` 注册页面。页面内容：卡片标题/描述、主按钮「复制链接」
  （`wx.setClipboardData` → `wx.showToast`）、URL 文本（`user-select`/可长按复制）、提示行。
  **禁止 web-view / 打开外部网页**（个人主体能力受限，只能复制链接引导）。
- 图标：新增 `images/tool-jw.png`（96×96 透明底白色 glyph，参照 `mp-class-tools-tests/_make_vote_icon.py` 生成），
  生成脚本保留 `mp-class-tools-tests/_make_jw_icon.py`。
- 使用说明 `pages/ug/ug.js` 的 `CARDS` 增加 jw 卡（`cat:'study'`，icon:'🏫'，按现有字段 title/sub/tone/steps/tip 写）。
- `utils/version.js` 的 `VERSION` 保持 `2.0.0`；不改云端/同步契约（homeTools 只是多一个合法 key）。
- 测试（在 `mp-class-tools-tests/` 跑）：`node unit.js`、`node tool_sort_unit.js`、`node ug_cards_check.js`、
  `node sync_contract_test.js` 全绿；`python staticcheck.py`、`node code_quality_check.js` 退出 0；
  追加断言（`tools.toolOf('jw')` 字段/url、toolOrder 含 jw、默认首页不含 jw）。

### 2.3 安卓（仓库 `android-class-tools/`，工作区同级目录）

- `data/tool/ToolCatalog.kt` 追加 `AppTool(id="jw", name="教务", subtitle="成绩 · 选课 · 考试",
  icon=Icons.Rounded.School, accent=BrandSlateBlue, category=ToolCategory.STUDY, features=[...3 条...])`。
- 新增 `ui/screens/jw/JwEntryScreen.kt`：`CtTopBar` + 卡片；主按钮「打开教务系统」=
  `Intent(Intent.ACTION_VIEW, Uri.parse(URL))`（`runCatching`，失败 toast「没有可打开浏览器的应用」）；
  次按钮「复制链接」=`ClipboardManager` + toast「链接已复制」；URL 小字 + 提示行。
- `ui/navigation/MainNavHost.kt` 的 `when (toolId)` 增加 `"jw" -> JwEntryScreen(onBack = { navController.popBackStack() })`。
- 使用说明 `ui/screens/guide/GuideContent.kt` 增加 jw 卡（按现有 20 卡结构；tip 文案同契约）。
- 测试：新增 `app/src/test/.../JwEntryTest.kt`（纯 JVM：URL 常量、intent action/data、复制文本辅助函数）；
  `gradlew.bat :app:testDebugUnitTest` 全绿（现有 1104+）。
- 版本：`versionName 4.45.0` / `versionCode 61`；`gradlew.bat :app:assembleRelease --no-build-cache`，
  产物复制到 `artifacts/classtools-4.45.0-release-signed.apk`，记录大小与 SHA-256；`docs/CHANGELOG.md` 加 v4.45.0 条目。
- 注意：仓库有**并行会话未提交 WIP（26 个文件）**，不得回退/格式化他人改动；只改/记录本次相关文件
  （仓库无远端，无需推送）。

## 3. 红线（三端通用）

- 不引入构建链 / 外部依赖 / 页面加载外部请求；网页保持单文件零依赖；`APP_VER`/`VERSION` 不变（安卓按版本规则 +1）。
- 不采集、不传输、不存储任何学号/密码/token；不嵌 iframe/web-view。
- 不碰 `deploy/creds.env`、`tools/cert/`、`jwxt/creds.dpapi` 等机密；测试只用官方测试身份 / mock。
- 只改各自 scope 内文件；**开发同学不部署、不 git push**（网页部署与双远端提交由 Lead 执行）。

## 4. 验收清单（Lead 复核）

- [ ] 三端 key/文案/URL 与契约一致（grep 校验）
- [ ] 网页新测试 + 回归全绿；部署后 OSS 字节 MATCH，线上 HTML 含入口链接
- [ ] 小程序 unit/staticcheck 全绿，改动文件清单可直接用于微信上传
- [ ] 安卓单测全绿 + APK 产出（大小/SHA-256）
- [ ] 无新增外部请求；无隐私字段；无对既有功能的行为改动
