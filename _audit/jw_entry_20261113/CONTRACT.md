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

---

## 5. 变更（2026-11-13 21:38 用户新要求，增量 55）

> 用户原话：「把网页端和app的教务系统入口改直接进入同时附带自动填充账号密码功能，取消微信小程序端的教务系统入口」

### 5.0 已确认口径（用户 21:39 点选）
- 网页端：**直接跳转 + 浏览器自动填充**（本站不接触、不保存教务密码；「直接进入」= 点「教务」卡片直接打开教务系统，删除中间入口页）。
- 安卓端：**允许本机加密保存密码，自动登录**（仅存手机本机、Android Keystore 加密、可一键清除、绝不上传；学校若开验证码则回退手动）。
- 小程序端：**取消入口**（删除卡片、页面、图标、使用说明卡；`VERSION` 仍 2.0.0）。

### 5.1 关键技术事实（2026-11-13 实测，实现不得假设相反）
- 学校统一认证登录页 `https://authserver.fjtcm.edu.cn/authserver/login?service=http%3A%2F%2F210.34.74.77%2Fsso.jsp`：
  - **不支持 URL 预填账号**（`?username=` 不生效，`username` 输入框 value 恒空）→ 网页端无法经 URL 预填。
  - 浏览器安全模型禁止 A 站（本站）跨域读写 B 站（authserver）表单 → **网页端无法真正代填**；只能「直跳 + 浏览器自带密码保存/自动填充」。本站不得保存教务密码（红线）。
  - 账号密码登录表单：form `#pwdFromId`、账号 `#username`、可见密码 `#password`（name=passwordText）、隐藏密文 `#saltPassword`、每会话盐 `#pwdEncryptSalt`、提交按钮 `<a id="login_submit">`；页面自身有全局 `encryptPassword(pwd, salt)`（AES-CBC/Pkcs7，CryptoJS）与 `#pwdLoginDiv` 展示逻辑；点击 `#login_submit` 会走 `startLogin→checkForm`（自动加密+提交）。
  - 登录页可能要求验证码（`#captchaDiv` / `#showErrorTip`），自动提交失败时必须回退人工。

### 5.2 网页（tools/index.html）
1. `TOOLS` 的 jw 条目增加 `url:"http://210.34.74.77/sso.jsp"`；**删除** `#s-jw` 页面（`<!-- __JW_ENTRY_V1_BEGIN__ -->` 区间）与其 CSS/复制页 JS；保留 UG 卡并改文案。
2. 新 JS 块（主 IIFE 内）：`JW_URL` 常量、`isLinkTool(k)`、`openJwDirect()`（创建 `<a href target="_blank" rel="noopener noreferrer">` 并 click，兜底 `location.href`）、只读探针 `window.JW={url,open}`；**无定时器/网络请求**。
3. 包装 `gotoTab`：`k==="jw"` → `openJwDirect()` 后 return（不切页、不改 CURTAB/history）；「全部」卡片点击与工具栏 tab 点击都走这条路径（卡片 label 用「进入」）。
4. 滑动引擎 `targetFor("tool")` 跳过 link tools（jw），避免滑动误开新窗口（抽签 STEP 边界切工具同函数，自动生效）。
5. UG jw 卡：sub「点卡片直接打开教务系统」；steps「点『教务』卡片直接打开教务系统 / 首次登录时勾选浏览器『保存密码』 / 之后打开即自动填充账号密码」；tip「自动填充由浏览器完成；校外打不开时先连学校 VPN」。
6. 测试 `tools/tests/v2_jw_check.py` 重写（mock anchor click / window.open）：卡片与工具栏两条路径都直接触发打开、不切页；0 JS 报错/0 console.error/0 外部请求（不请求 210.34.74.77 / authserver）；`isLinkTool('jw')===true`；4 档无溢出；截图更新 `_shots_jw/`。回归 overflow/v2_ui/v2_drag/v2_ug/optim_v1/v2。

### 5.3 安卓（android-class-tools）
1. 由「入口页 + 打开按钮」改为：点「教务」卡 → 直接进入内置 WebView（`http://210.34.74.77/sso.jsp`），**自动填充账号密码并提交**；无已存凭据时先弹一次性密码输入（账号默认当前身份 sid；可「仅打开不保存」）。
2. 密码仅本机保存：Android Keystore（AES/GCM）+ SharedPreferences 存 sid+密文+IV；**不写日志/不上报/不参与同步**；顶栏提供「清除登录（密码+Cookie）」；身份 sid 变化时不匹配旧凭据需重新输入。
3. WebView 配置：JS/DOM storage/Cookies 开启、禁 file access、仅允许 http(s)；新增 `res/xml/network_security_config.xml` 仅对 `210.34.74.77` 放行 cleartext（manifest 引用，不能全局开 cleartext）。
4. 注入时机：`onPageFinished` 且 URL 在 `authserver.fjtcm.edu.cn` 的 `/authserver/login` → 延迟 ~300ms：确保 `#pwdLoginDiv` 可见 → 填 `#username`/`#password`（派发 input 事件）→ 点 `#login_submit`（页面自身 encryptPassword+提交）；800ms 后复核：仍在 authserver 且 `#showErrorTip` 有文字或 `#captchaDiv` 可见 → 回退人工（提示「自动登录失败，可能需验证码，请手动完成」），成功后 URL 为非 authserver（210.34.74.77）即视为已进入。
5. 版本 `4.46.1 / vc63`；ToolCatalog subtitle/features、GuideContent jw 卡文案同步；docs/CHANGELOG 记 v4.46.1；单测 + Release APK（`artifacts/classtools-4.46.1-release-signed.apk`）。
6. 测试红线：**禁止用任何真实教务账号测试**（AGENTS §0-7）；模拟器冒烟只能用假账号/假密码验证「页面加载 + 注入触发 + 不崩溃」，或如实说明未做真机验证。

### 5.4 小程序（mp-class-tools）
删除 jw 入口/页面/图标/使用说明卡，测试恢复 19 卡基线；`VERSION` 2.0.0；用户需重新上传发布。


---

## 6. 变更（2026-11-14 13:0x，增量 56，仅安卓）

> 用户原话：「把教务系统点开后也展示和班级工具站的卡片一样展开，只调用官方各个工具的网页接口」。
> 已确认（本次点选）：**只做安卓 App**；**卡片直接展示官方接口数据**（用户授权真实账号一次性接口勘察，仅用于发现官方 URL/参数/字段名）。

### 6.1 授权与安全口径
- 2026-11-14 用户选择「卡片直接展示官方接口数据（脆弱，需授权）」= 授权本次一次性接口勘察；Lead 复用本机 DPAPI 凭据 +
  既有 `jwxt.sso_login_http` 生产链路完成，**只记录 URL/参数/JSON 字段名/表头**，原始页面只落盘 `%TEMP%\jw_probe\`（不入仓、不进对话正文）。
  App 自动化测试仍**只用合成夹具/假账号**（AGENTS §0-7）。
- App 红线：卡片数据只读（4 个官方 GET 接口）；选课/报名/缓考/评教等写操作只在官方页面内由用户完成，App 不调用任何写接口；
  密码仍只本机 Keystore 加密保存；cookie 只在请求瞬间使用，不落盘/不打日志/不上传；数据只内存展示。

### 6.2 官方接口（2026-11-14 实测，详见 `_audit/jw_entry_20261113/JW_CARDS_V1_SPEC.md` §2）
- 成绩 `/jsxsd/kscj/cjcx_list`、考试 `/jsxsd/xsks/xsksap_list`、选课轮次 `/jsxsd/xsxk/xklc_list_data`、公告 `/jsxsd/ggly/ysgg_query?type=list`；
  GET + `pageNum`/`pageSize`（layui qzTable 口径）；必要请求头 Cookie/UA/Referer/X-Requested-With/Accept；响应 `{msg,code,data,count}`。
- 官方快捷菜单 8 项：学期理论课表/课程成绩查询/学生选课中心/考试安排查询/培养方案明细/已收公告/缓考申请/社会考试报名（路径见规格 §3）。
- 实测态：本账号（大一第一学期）4 接口均 `count=0`，**空态为正常路径**；有数据行渲染未用真实有数据账号验证（合成夹具覆盖）。

### 6.3 App 交付（android-class-tools v4.48.0 / vc66）
- `data/jw/JwApiModels.kt` + `JwApiClient.kt` + `JwCardsRepository.kt`（宽松解析/并行拉取/单卡失败隔离/HTML→会话失效）；
  `ui/screens/jw/JwCardModels.kt` + `JwCardsSection.kt`（4 数据卡 + 8 官方入口卡 + 完整官网）；`JwEntryScreen.kt` 改 LOGIN/CARDS/WEB 三模式
  （复用自动登录/验证码回退/本机 Keystore 凭据/清除登录；登录成功取 CookieManager cookie → 拉接口；会话失效自动重登 1 次）。
- 单测 **1177/0**（93 suites，新增 42：JwApiClientTest 20 / JwCardsRepositoryTest 8 / JwCardModelsTest 14）；Release
  `artifacts/classtools-4.48.0-release-signed.apk` **3,141,837 B / SHA-256 `7543DAE44153ABF42525F2D62446058607E26B5FA0B7F8ED0B4BCE5D22E649B9`**（vc66，v2 签名；dex 已核验含 4 个官方接口路径与卡片文案）。
- 已知限制：未真机/真实有数据账号验证；官方页面改版→卡片降级空态/失败态（不崩溃）；验证码沿用手动回退；APK 含并行会话未提交 WIP（无法仅由 HEAD 复现）。
- 回滚：删除新增 jw 卡片文件 + `JwEntryScreen.kt` 回 HEAD（v4.46.1）+ 版本号回退；APK 回退 4.47.1 产物。
