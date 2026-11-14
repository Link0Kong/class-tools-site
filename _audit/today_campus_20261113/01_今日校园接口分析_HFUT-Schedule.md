# 今日校园（学工系统）接口与 CAS 认证链路分析 —— 基于 HFUT-Schedule 公开源码

- 分析对象：`https://github.com/Chiu-xaH/HFUT-Schedule`，默认分支 **`dev`**（本文所有行号均指该分支 2026-11-13 抓取副本）。
- 分析方式：**仅静态源码 + 公开文档**。未登录任何真实系统、未使用任何真实凭据、未向 hfut/fjtcm 域名发起任何探测请求（抓取仅走 `raw.githubusercontent.com`）。
- 代码缓存：`_audit/today_campus_20261113/_scratch_repo/`（文件名把 `/` 换成 `_`；本次共抓 899 个文件≈4.5MB，覆盖 app 模块全部 586 个 `.kt`、network-api/network-core/common-logic 全部、docs 全部、tools/sql 相关）。Lead 预抓的 27 个关键文件亦复用。
- 标注约定：**推断** = 源码/文档未直接写死、由旁证归纳；**未能证实** = 本仓库静态代码无法证明，需对目标系统实测（本次按约束不做）。
- 与任务无关但需注意：仓库 `Constant.kt:11` 内含硬编码 Gitee token（本文不复述其值），属仓库密钥卫生问题，不影响今日校园链路。

---

## 0. 一句话结论

HFUT-Schedule 能「用今日校园的功能」，靠的是**自己走完 CAS 登录拿 TGC → 用 TGC 换学工系统 ticket → 跟随 302 拿到学工系统自己的 `_WEU` 会话 Cookie → 把 `_WEU` 注入 WebView 打开 `xsfw/sys/<模块>/*default/index.do`**；它**没有**逆向今日校园 H5 的业务接口，应用目录是**内置静态快照 `assets/stu.json`（11 类 50 个应用）+ 智慧社区 `listApplication` 动态补充**两层。因此可迁移的是「CAS→ticket→cookie→WebView 壳」这套骨架，不可直接搬的是 HFUT 域名、CAS/OAuth 客户端参数、应用编码与快照数据。

---

## 1. 仓库模块地图（与今日校园 / 学工 / CAS 相关）

| 层/文件（dev 分支路径） | 职责 | 证据 |
|---|---|---|
| `network-api/src/main/java/com/hfut/schedule/network/api/inf/StuService.kt` | 学工系统（今日校园）3 个 Retrofit 接口定义 | 全文 12–27 行 |
| `network-api/.../impl/StuServiceCreator.kt` | 学工 Retrofit 工厂：baseUrl=`Constant.STU_URL`，禁用自动 302 | 8–12 行 |
| `network-api/.../model/Constant.kt` | 全部 HFUT 域名/常量（`CAS_LOGIN_URL` 60 行、`STU_URL` 83 行、`PC_UA` 154 行） | 全文 |
| `network-api/.../model/response/json/stu/TodayCampusAppResponse.kt` | 今日校园应用目录 JSON 模型（`datas[].apps[]`） | 5–19 行 |
| `app/.../logic/model/enumeration/CasLoginType.kt` | 走 CAS 的各平台 service URL 枚举（`STU` = 学工系统） | 6–23 行（STU 在 10 行） |
| `app/.../logic/network/repo/CasLoginRepository.kt` | CAS 六步的编排：取 execution/cookie、取 AES key、TGC 换 ticket、OAuth2 跳转 | 22–98 行 |
| `app/.../logic/network/interceptor/AesKeyInterceptor.kt` | 从 `cas/checkInitParams` 的 `Set-Cookie` 抓 `LOGIN_FLAVORING`（AES key） | 8–31 行 |
| `app/.../logic/network/interceptor/RedirectTicketInterceptor.kt` | 拦截 302，按目标平台解析 ticket/cookie（学工 `_WEU` 在 171–185 行） | 17–239 行 |
| `app/.../logic/network/interceptor/GotoInterceptor.kt` | OAuth2 `code=` / 慧新易校 `synjones-auth=` 截获 | 9–35 行 |
| `app/.../logic/network/interceptor/GoToInterceptorState.kt` | 拦截器与 VM 之间的 flow 状态 | 5–8 行 |
| `app/.../logic/network/impl/LoginServiceCreator.kt` | CAS OkHttp：关闭自动 302 + 注册 `RedirectTicketInterceptor` | 9–15 行 |
| `app/.../logic/network/impl/AesKeyServiceCreator.kt` | CAS OkHttp：baseUrl=CAS + 注册 `AesKeyInterceptor` | 8–13 行 |
| `app/.../logic/network/impl/OneGotoServiceCreator.kt` | CAS OkHttp：注册 `GotoInterceptor`（OAuth2 用） | 8–13 行 |
| `network-api/.../inf/LoginService.kt` | CAS 全部 HTTP 接口：checkInitParams/login/loginGoTo/loginGoToOauth/vercode… | 14–77 行 |
| `app/.../viewmodel/network/LoginViewModel.kt` | CAS 登录流程 VM（拼 Cookie、POST、存 TGC/ticket） | 37–109、111–164 行 |
| `app/.../viewmodel/network/NetWorkViewModel.kt` | 聚合入口：`goToStu` 331、`checkStuLogin` 334–335、`getStuApps` 551–552 | 同上 |
| `app/.../logic/network/repo/OthersRepository.kt` | 学工「是否仍登录」探测 `checkStuLogin` | 161–172 行 |
| `app/.../logic/network/repo/CommunityRepository.kt` | 智慧社区登录（ticket→token）与动态应用目录 `getStuApps` | 67–86、342–357 行 |
| `network-api/.../inf/CommunityService.kt` | 智慧社区接口，其中「学工系统列表」`listApplication` | 106–108 行 |
| `network-api/.../model/response/json/community/CommunityStuAppResponse.kt` | 动态应用目录模型（`result[].subList[]{name,logo,url}`） | 3–16 行 |
| `app/.../ui/screen/home/search/function/school/student/TodayCampus.kt` | 今日校园 UI：应用网格 + 打开 WebView + Cookie 注入 | 全 410 行 |
| `app/.../ui/nav/destination/StuTodayCampusDestination.kt` | 导航目的地（key=`"stu"`） | 12–22 行 |
| `app/.../activity/screen/SuccessActivity.kt`、`ui/nav/destination/HomeDestination.kt`、`ui/screen/home/MainUI.kt` | 登录成功后 `isSuccessActivity/isLogin=true` 的传递链（触发学工等平台自动刷新） | `SuccessActivity.kt:22-30`、`HomeDestination.kt:39-45`、`MainUI.kt:1144-1150` |
| `app/.../ui/nav/destination/WebViewDestination.kt` | WebView 路由（携带 url+cookies） | 8–41 行 |
| `app/.../activity/util/WebViewActivity.kt` | 独立 Activity 承载 WebView（Intent 传 url/title/cookies/icon） | 14–30 行 |
| `app/.../ui/component/webview/WebViewForNavigation.kt` / `WebViewForActivity.kt` | WebView 初始化与 Cookie 注入调用点 | 前者 140–204，后者 127–199 |
| `app/.../ui/util/WebViewFactory.kt` | `setInitial()` 设 Cookie、`sharedInterceptRequest()` 补 Cookie | 661–741 行 |
| `app/.../logic/util/sys/Starter.kt` | 启动今日校园 App（`com.wisedu.cpdaily`）与 WebView | 43–58、62–79、217–289 行 |
| `app/src/main/assets/stu.json` | 今日校园应用目录**离线快照**：11 类 50 个应用 | 全文 1031 行 |
| `docs/HfutApi.md` | 仓库自带 API 文档：CAS 全流程（6–133 行）；学工只写「参数多需 JS 逆向」（1720–1722 行） | 同上 |
| `docs/update/4.9.md` 72 行、`4.16.md` 36 行、`4.17.md` 40 行、`4.18.md` 92 行、`4.21.md` 27 行 | 学工/今日校园功能演进记录 | 同上 |
| `tools/Captcha-Ocr/*` | CAS 验证码 OCR（Tesseract 训练 + 样本爬取 `cas/vercode`） | README 1–12 行；爬取脚本 11 行 |
| `sql/supabase.sql`、`tools/Login-Web-Python/`、`tools/webvpn/` | 与本链路无直接关系（Supabase/校园网/WebVPN），仅背景 | — |

补充：`app/src/main/java/.../ui/screen/home/search/SearchUI.kt:251` 把今日校园注册为搜索入口（`SearchAppBean(35, "...学工系统 学工平台 请假 助学金 奖学金 贫困 寝室 心理 日常")`），`GlobalUiStateHolder.kt:137` 登记默认功能项 35，`AndroidManifest.xml:21-31` 声明 `<queries><package android:name="com.wisedu.cpdaily"/></queries>` 以便启动官方 App。

---

## 2. CAS 认证链路逐步拆解（HFUT 实现）

> HFUT 的 CAS 是**金智/正方系典型 CAS + 自定义 `LOGIN_FLAVORING` 前端 AES 加密**的变体：`cas/login` 表单提交前，密码要用服务端下发的 `LOGIN_FLAVORING` Cookie 值作 AES 密钥加密。以下按代码实际顺序。

### 步骤 1：`GET cas/checkInitParams` → 拿 `LOGIN_FLAVORING`(AES key) + `JSESSIONID` + 是否需验证码

- 接口定义：`LoginService.kt:16` `@GET("cas/checkInitParams")`（baseUrl=`https://cas.hfut.edu.cn/`，`Constant.kt:60`）。
- 执行者：`AesKeyServiceCreator`（baseUrl=CAS，注册 `AesKeyInterceptor`，`AesKeyServiceCreator.kt:8-13`）。
- 拦截器：遍历响应所有 `Set-Cookie`，命中含 `LOGIN_FLAVORING` 的那条，取 `cookie.substringBefore(";")` 再 `substringAfter("=")` 作为 key，写入 `SharedPrefs("LOGIN_FLAVORING")`（`AesKeyInterceptor.kt:11-27`）。
- 返回体 JSON 的 `vercode` 字段映射为 `needCaptcha`（`CasFlavorSessionResponse.kt:5-13`），同时把 `Set-Cookie` 原串作为 `jSession` 保存（`CasLoginRepository.kt:87-98`）。
- 文档佐证：`docs/HfutApi.md:26-31`（Step1 LOGIN_FLAVORING 获取）。

### 步骤 2：`GET cas/login?service=` → 拿 `execution` + 会话 Cookie

- 接口：`LoginService.kt:20-23` `@GET("cas/login")`，`service` 由调用方决定。
- 执行者：`CasLoginRepository.getCasCookie`（61–79 行）→ `LoginGetCookieServiceCreator`（CAS baseUrl，无拦截器）。
- 解析：Jsoup 取 `input[name=execution]` 的 `value`，**缺省回退 `"e1s1"`**（`CasLoginRepository.kt:75`）；`Set-Cookie` 取第一段 + `;` 作为 session（76 行）。
- service 取值：默认教务系统 `http://jxglstu.hfut.edu.cn/eams5-student/neusoft-sso/login`；开启「跳过教务系统」（`GlobalUiStateHolder.excludeJxglstu`）时为信息门户 `null`（`CasLoginRepository.kt:65-66`；枚举见 `CasLoginType.kt:8-9`）。
- 文档佐证：`docs/HfutApi.md:8-19`。

### 步骤 3：可选 `GET cas/vercode` → 图片验证码（仅 needCaptcha=true 时）

- UI：`LoginUI.kt:218-262`，图片 URL = `CAS_LOGIN_URL + "cas/vercode"`，请求带步骤 2 的 `jSession` Cookie，每次点击加时间戳刷新；启用 OCR 时自动填（`LoginUI.kt:778-819`）。
- 是否真的需要验证码由服务端 `vercode` 决定（`LoginUI.kt:778`）；OCR 工具：`tools/Captcha-Ocr/README.md`、样本爬取脚本 `tools/Captcha-Ocr/验证码样本爬取.py:11`。
- 文档佐证：`docs/HfutApi.md:21-24`。

### 步骤 4：`POST cas/login?service=` 表单登录 → 拿 302 `Location` 里的 ticket + `TGC`

- 接口：`LoginService.kt:26-37`
  - Form 字段：`username`、`password`（AES 密文）、`execution`、`_eventId`（默认 `"submit"`，34 行）、`capcha`（35 行；注意拼写就是 capcha）。
  - Header：`Cookie`（步骤 2 的 session + 步骤 1 的 jSession + `LOGIN_FLAVORING=...`）、`@Headers(Constant.PC_UA)`（27 行，**必须带 PC UA**，文档 `HfutApi.md:41/92` 明确「否则返回异常」）。
- 密码加密：`LoginUI.kt:151-153`
  ```kotlin
  val cookie = prefs.getString("LOGIN_FLAVORING", "")
  val outputAES = CryptoUtil.encryptAES(inputAES, cookie)   // AES-ECB/PKCS5 + Base64
  val loginFlavoring = "LOGIN_FLAVORING=$cookie"
  ```
  `CryptoUtil.encryptAES` 用 `Cipher.getInstance("AES")`（Android 默认 AES/ECB/PKCS5Padding）+ 密钥取 `LOGIN_FLAVORING` 原值字节，输出 Base64（`CryptoUtil.kt:26-37`）。
- Cookie 组装：`LoginViewModel.kt:51` `session + jId.jSession + ";" + keys`，再存入 `GlobalUiStateHolder.casCookies`（52 行）。
- 结果解析（`LoginViewModel.kt:90-100`）：响应头 `Location` 按 `substringAfter("=")` 取 ticket 存 `prefs("ticket")`；`Set-Cookie` 取第一段存 `prefs("TGC")`；`code` 记录 HTTP 状态。**成功判据**：302 且 `Location` 含 `"ticket"`（`LoginUI.kt:196-202`），401 → 「密码错误」（177–180 行）；200 且非 WebVPN 分支 → 提示「请输入正确的账号」（186–188 行）。
- 文档佐证：`docs/HfutApi.md:33-84`（含 `password` 由 LOGIN_FLAVORING 作 Key AES 加密、`execution=e1s1`、`capcha` 四位）。

### 步骤 5：用 TGC 换 ticket 的两种跳转（普通 service / OAuth2）

#### 5a. 普通 CAS service 跳转（教务、信息门户、**学工系统**、智慧社区、图书馆、二课、指间工大…）

- 接口：`LoginService.kt:40-45` `@GET("cas/login")`，参数 `service=<目标平台 URL>`，Header `Cookie=casCookies;TGC`，带 PC UA。
- 编排：`CasLoginRepository.gotoCommunity/gotoSecondClass/gotoZhiJian/gotoLibrary/goToStu/goToPe`（28–45 行）→ `login.loginGoTo(...)`；返回 HTTP code（`launchRequestNone`，`LaunchRequest.kt:133-150`）。
- **学工系统 service URL** = `https://stu.hfut.edu.cn/xsfw/sys/xgutilapp/userinfo/getConfigUserInfo.do`（`CasLoginType.kt:10`，即 `STU_URL + "xsfw/sys/xgutilapp/userinfo/getConfigUserInfo.do"`）。
- 触发时机：登录成功后 `LoginUI` 调 `Starter.loginSuccess()` 打开 `SuccessActivity`（`Starter.kt:306-315`），`SuccessActivity` 以 `isSuccessActivity=true` 渲染 `MainHost`（`SuccessActivity.kt:22-30`）→ `HomeDestination.Content` 在 `isSuccessActivity` 分支给 `MainScreen(isLogin=true)`（`HomeDestination.kt:39-45`）→ `MainScreen` 把 `isLogin` 作为 `refreshLogin` 传给课程表 `JxglstuCourseTableUI`（`MainUI.kt:1144-1150`）→ 并行刷新各平台登录态：`cookies = "$casCookies;$tgcCookie"`（234 行），学工分支在 297–317 行（无 `stu` 本地值 → `goToStu`；有值先 `checkStuLogin`，失败再 `goToStu`）。WebVPN 开启时**跳过学工**（299–301 行）。手动刷新入口同理走 `Starter.refreshLogin()`（`Starter.kt:180-190`，Intent extra `login=true`）。
- 302 的消费方：`RedirectTicketInterceptor`（见步骤 6）。

#### 5b. OAuth2 跳转（信息门户/慧新易校）

- 接口：`LoginService.kt:47-54` `@GET("cas/oauth2.0/authorize")`：`client_id`、`redirect_uri`、`response_type=code`（默认 `"code"`）、Cookie 带 TGC。
- 已用 client_id：信息门户 `BsHfutEduPortal`（`CasLoginRepository.kt:46-52`，redirect_uri=`https://one.hfut.edu.cn/home/index`）、慧新易校 `Hfut2023Ydfwpt`（53–59 行）。文档 `docs/HfutApi.md:94-104` 同。
- 响应 `Location` 含 `code=` 时由 `GotoInterceptor` 截获写入 `GoToInterceptorState.toOneCode`（`GotoInterceptor.kt:17-20`），VM 再换 token；`RedirectTicketInterceptor` 另有「跟两次才给 302」的注释（`JxglstuCourseTableUI.kt:111-126`）。
- **今日校园不走 OAuth2**，走 5a 的普通 service 跳转。

### 步骤 6：`RedirectTicketInterceptor` 截获 ticket / cookie 及其失效语义

核心：`LoginServiceCreator` 关闭自动重定向（`LoginServiceCreator.kt:12` `allowAutoRedirect(false)`，实现 `ClientBuilderHelper.kt:13-16`），改为拦截器手动 `chain.proceed` 并以 `hit(location, target)` 判定目标平台（`RedirectTicketInterceptor.kt:169`：URL 或 WebVPN 编码后的 URL 命中即算）。

学工系统分支（26–37 行）：
1. 302 的 `Location` 命中 `Constant.STU_URL` → 取 `ticket = location.substringAfter("ticket=")`（23 行，日志）。
2. 以 `location` 为 URL 再发一次 GET（29–34 行）→ 学工服务端校验 ticket 后种 `_WEU` Cookie。
3. `parseLoginStu(headers, body)`（171–185 行）：
   - `json == null` → 抛「无内容」；
   - 取本地学号 `getPersonInfo().getStudentIdFinally()`，**响应体必须包含学号**，否则抛「登陆失败」；
   - 从 `Set-Cookie` 提取 `_WEU=` 段（`prefix = "_WEU="`，178 行），保存 `prefs("stu") = "_WEU=<值>"`（180 行）；
   - 成功 toast「学工系统登陆成功」，失败只 `LogUtil.error`（**无失败 toast**，静默失败风险）。
- 其它平台对照（同文件）：智慧社区 38–42 只把 ticket 放 flow；指间工大 43–80 解析 `jsessionid`→`ecology_JSessionid`；教务 81–92 从 `Set-Cookie` 取 `SESSION=` 存 `prefs("redirect")`；图书馆 93–104 取 `Authorization=` 存 `Bearer`；体测 105–131 拼 `PHPSESSID=$ticket`；二课 132–162 取 `SESSION=`。
- **失效语义**（代码+文档归纳）：
  - CAS 侧：`Location` 末尾无 `ticket=XXX` ⇒ Cookie 过期/无效（`docs/HfutApi.md:51/84`）；登录 POST 返回 401 ⇒ 密码错误（`LoginUI.kt:177-180`）。
  - 学工侧：`_WEU` 失效时 `checkStuLogin` 的响应体不含学号 → 返回 false（`OthersRepository.kt:161-172`），上层随即重新 `goToStu` 刷新（`JxglstuCourseTableUI.kt:302-316`）。
  - 学工 `_WEU` 的具体有效期/签名结构：**未能证实**（代码只搬运 Cookie，不解析）。

### 认证链路时序（汇总）

```
[UI] LoginUI.kt:141  loginClick
  ├─ AesKeyInterceptor  GET cas/checkInitParams ─→ LOGIN_FLAVORING(key), JSESSION, vercode→needCaptcha
  ├─ GET cas/login?service=<教务|空> ─→ execution + Set-Cookie(session)
  ├─ (可选) GET cas/vercode  ─→ 图片验证码；OCR 自动填充
  ├─ AES-ECB(password, LOGIN_FLAVORING) → Base64
  ├─ POST cas/login?service=…  Form{username,password,execution,_eventId=submit,capcha}
  │      Header Cookie: session;JSESSION;LOGIN_FLAVORING=… + PC UA
  └─ 302 Location(ticket=ST-…) + Set-Cookie(TGC)   → prefs("ticket"), prefs("TGC")
        │
        └─(登录成功，课程表页刷新各平台) JxglstuCourseTableUI.kt:213
             cookies = "$casCookies;$tgcCookie"
             GET cas/login?service=https://stu.hfut.edu.cn/xsfw/sys/xgutilapp/userinfo/getConfigUserInfo.do
                └─ 302 Location = https://stu.hfut.edu.cn/xsfw/sys/jbxxapp/*default/index.do?ticket=ST-…
                     └─ RedirectTicketInterceptor 命中 STU_URL → 再 GET 该 Location
                          └─ Set-Cookie: _WEU=… ; Body 含学号
                               └─ prefs("stu") = "_WEU=…"
                                    └─ TodayCampus UI: CookieManager.setCookie(openUrl, "_WEU=…") → WebView
```

---

## 3. 今日校园（学工系统）接口清单

### 3.1 `StuService`（`https://stu.hfut.edu.cn/`，`StuServiceCreator.kt:8-12`，**关闭自动 302**）

| # | 方法 | URL | 入参 | Header/Cookie | 返回 | 用途/错误判定 | 调用点 |
|---|---|---|---|---|---|---|---|
| 1 | GET | `xsfw/sys/jbxxapp/*default/index.do` | `?ticket=<CAS ticket>` | 无显式 Header | HTML（含学生信息） | 用 ticket 换学工会话（会 Set-Cookie `_WEU`）；定义于 `StuService.kt:15-16` | **仓库内未见调用**（仅定义；实际由拦截器手动 follow）|
| 2 | POST | `xsfw/sys/xgutilapp/userinfo/getConfigUserInfo.do` | 无 body（非 FormUrlEncoded） | `Cookie: _WEU=<…>`（必填） | JSON 文本，**含学号** | 「是否仍登录」探测；响应含学号=有效（`OthersRepository.kt:168-172`） | `OthersRepository.kt:161-172` |
| 3 | POST | `xsfw/sys/xggzptapp/modules/xszm/getFxYy.do` | Form `data={"FZDM":"SCYY","pageSize":"500","pageNum":1}` | `Cookie: _WEU=<…>` | JSON：`datas[].categoryName/apps[]{name,iconUrl,openUrl}` | 拉取今日校园「应用中心」目录（`StuService.kt:20-27`） | **仓库内未见调用**（见 3.3） |

注：`*default` 是 URL 字面量（星号并非通配符），来自 `stu.json` 与接口定义，今日校园侧对 `*default` 有特殊路由含义（**推断**：金智 uni-app 容器的默认页约定）。

### 3.2 应用目录 JSON 模型

**网络模型**（`TodayCampusAppResponse.kt:5-19`）：
```kotlin
TodayCampusAppResponse(datas: List<TodayCampusApp>)
TodayCampusApp(categoryName: String, apps: List<TodayCampusAppDetail>)
TodayCampusAppDetail(name: String, iconUrl: String, openUrl: String)
```
与 `datas[].apps[]` 结构一致；Gson 忽略多余字段。**内置快照 `assets/stu.json` 是同一模型的超集**（每个应用还含 `appId/appType/installUrl/version/viewAuth/accessAuth/fromPlatformType=OPEN/fromPlatform=open/serverDomain/appState=ONLINE/developerId/appSource/aliasName/nameLang`；每类含 `categoryId/categoryName/order/apps`，`stu.json:1-1031`）。

`stu.json` 实测统计：
- **11 个分类 / 50 个应用**（PowerShell 解析原文 JSON 得到）：
  | order | categoryName | apps |
  |---|---|---|
  | 0 | 学工服务 | 5 |
  | 4 | 研工服务 | 9 |
  | 5 | 迎新服务 | 1 |
  | 6 | 队伍建设 | 2 |
  | 7 | 就业工作 | 1 |
  | 8 | 国防教育 | 3 |
  | 9 | 健康管理 | 2 |
  | 10 | 心理服务 | 11 |
  | 11 | 学风建设 | 5 |
  | 12 | 资助工作 | 7 |
  | 13 | 日常管理 | 4 |
- 全部应用 `appType=1`、`fromPlatformType=OPEN`、`appState=ONLINE`、`accessAuth=0`。
- `openUrl` 31 个 `http://`、19 个 `https://`（http 混合内容风险，见 §7）；部分带 `#` 后缀（如 `swmskjcapphfut`、`swmwzxsslqapphfut`、`swmwzxjcapphfut`）。
- **50 条应用只有 47 个唯一 `appCode`**：`swmxshdapp`（学生活动/研究生活动）、`swmxsqjapp`（学生请假/研究生请假）、`swmknsapp`（困难生认定/研究生困难生库）各重复 1 次——即同一入口按「本科生/研究生」分类重复挂载。
- 应用编码规律：47 个唯一编码中 46 个为 `swm<拼音缩写>app`，HFUT 自建模块再追加 `hfut` 后缀（约 20 个，如 `swmxlzxapp` vs `swmxlfdapphfut`）；唯一例外 `swmzxj`（助学金，无 `app` 后缀且路径为 `/xsfw/sys/swmzxj/*default/index.do`）。
- 典型条目：`学生基本信息 swmjbxxapp`、`消息推送 swmxxtsapp`、`学生请假 swmxsqjapp`、`节假日离校 swmjjrlfxapp`、`签到助手 swmqdzsapp`、`健康信息收集 swmxsyqxxsjapp`、`学生健康档案 swmxsjkdaapphfut`、`综合测评 swmzhcptybbapp`、`奖学金 swmjxjapp`、`心理服务 11 项 swmxl*app/hfut` 等。
- 图标域：`res.campushoy.com`、`cpdaily-resource.oss-cn-hangzhou.aliyuncs.com`（金智今日校园 CDN，带 `?ut=` 时间戳），见 `stu.json` 各 `iconUrl`。50 个图标 `ut` 时间戳范围 **2021-01-18 ~ 2024-08-30**，说明快照素材不早于 2024-08；快照的生成时间/更新机制**未能证实**（仓库无生成脚本、运行时只读 assets）。

**智慧社区动态目录**（另一来源，UI 里标「智慧社区」）：
- `GET api//mobile/community/application/listApplication`，Header `X-Access-Token`（智慧社区 token），返回 `{result:[{category, subList:[{name,logo,url}]}]}`（`CommunityService.kt:106-108`、`CommunityStuAppResponse.kt:3-16`）。
- 客户端过滤只保留 `url` 以 `Constant.STU_URL` 开头的条目（`CommunityRepository.kt:349-357`）。
- 数据前提：智慧社区登录 `GET api/sys/cas/client/validateLogin?service=https:%2F%2Fcommunity.hfut.edu.cn%2F&ticket=<CAS ticket>` → `result.token` 存 `prefs("TOKEN")`（`CommunityService.kt:14-15`、`CommunityRepository.kt:67-86`）。

### 3.3 三个接口的实际使用情况（重要）

- **实际在跑的只有 3.1 的 #2**（`checkLogin`，`OthersRepository.kt:163`）；#1 `login(ticket)` 与 #3 `getStuApps()`（`xggzptapp/modules/xszm/getFxYy.do`）**在 899 个已抓文件中均无调用点**，仅有接口定义。结论：该仓库当前版本用「拦截器手动 follow 302 + 内置 `stu.json`」取代了 #1/#3；#3 是历史/备用接口（**推断**，基于 v4.17「新增学工平台登录」→ v4.18「今日校园 UI」的演进，见 `docs/update/4.17.md:40`、`4.18.md:92`；`docs/HfutApi.md:1720-1722` 也承认学工登录参数未整理）。
- `LoginUI.kt:593-604` 的「当前登录将刷新如下平台」把「学工系统」标为 `canWithoutJxglstu=true, canWithJxglstu=true, canWebVpn=false`，与 `JxglstuCourseTableUI.kt:299` 的 `if(useWebVpn) return@stu` 一致：**WebVPN 模式下不刷新学工**。

---

## 4. UI 承载：TodayCampus 屏如何列应用、开 WebView、注 Cookie、处理失效

入口与导航：
- 搜索中心注册入口：`SearchUI.kt:251`（「学工系统 学工平台 请假 助学金…」关键词）→ `TodayCampus.kt:86-98` 的 `ToadyCampus()` 列表项 → `navController.push(StuTodayCampusDestination)`（`StuTodayCampusDestination.kt:12-22`，key=`"stu"`）。
- 页面骨架：`StuTodayCampusScreen`（`TodayCampus.kt:102-163`）—— TopAppBar 两个动作：**启动官方「今日校园」App**（`StartAppIconButton(Starter.AppPackages.TODAY_CAMPUS)`，126 行，包名 `com.wisedu.cpdaily`，`Starter.kt:48`）与**浏览器打开学工首页**（`Starter.startWebUrlOuter(context, Constant.STU_URL)`，131 行）；下方是搜索框 + `StuAppsScreen`。

应用列表两层合并（`StuAppsScreen`，166–394 行）：
1. **本地快照**：`getTodayCampusApps(context)` 读 `assets/stu.json`（396–408 行），`remember` 缓存。
2. **网络补充**：`refreshNetwork = { prefs.getString("TOKEN","")?.let { vm.stuAppsResponse.clear(); vm.getStuApps(it) } }`（172–177 行）——注意用的是**智慧社区 token**（`TOKEN`），不是学工 `_WEU`；`LaunchedEffect` 里仅当非 Success 才拉（184–189 行）。
3. **去重**：把本地全部 `openUrl` 转成「`stu.hfut.edu.cn/` 之后、`?` 之前」的相对路径集合 `l`（190 行），网络条目按 `url` 同样处理后**排除已在本地列表中的**（191–194 行）→ 结果放进「智慧社区」分组（325–389 行）。
4. 展示：有搜索词时合并铺 2 列网格（197–258 行）；否则按本地分类逐个 `DividerTextExpandedWith(categoryName)` 两列排（260–324 行）。

打开一个应用（WebView + Cookie 注入）：
- 点击卡片 → `Starter.startWebUrlInner(context, openUrl, title=name, cookie=cookie, icon=...)`，其中 `cookie = remember { prefs.getString("stu","") }`（178 行；调用点 222、250、287、311、350、377 行）。
- `startWebUrlInner`：若全局 WebVPN 开启 → 用 WebVPN Cookie 并改写 URL；否则直连（`Starter.kt:217-234`）→ `goToWebView` 用 Intent 把 `url/title/cookies/icon` 传给 `WebViewActivity`（`Starter.kt:272-289`、`WebViewActivity.kt:14-30`）。
- WebView 初始化：`setInitial(cookieManager, cookies, url)`（`WebViewForActivity.kt:137`、`WebViewForNavigation.kt:150`）：
  - 先 `removeSessionCookies(null)` + `removeAllCookies(null)` + `flush()` **清空所有 Cookie**（`WebViewFactory.kt:684-686`）；
  - 再 `setCookie(finalUrl, cookies)` 并 `flush`，回调里才 `loadUrl`（689–695 行）；
  - 无 cookie 直接加载（696–698 行）。
- 请求级补注：`sharedInterceptRequest`（717–741 行）在每次请求判断——教务/体测等域名强制 `setCookie(req.url, cookies)`；其它情况若请求头 `Cookie` 不含目标 cookie 值则补设（734–738 行）。
- **注入的是学工 `_WEU` Cookie，不是 CAS TGC，也不把 ticket 放进 WebView URL**。ticket 只在 OkHttp 的 302 follow 中用一次（`RedirectTicketInterceptor.kt:28-35`）。
- 附加能力：命中 `Constant.UNI_APP_URL`（合工大教务 uni-app）时用 `Authorization` header 代理请求（`WebViewForActivity.kt:161-183`），与今日校园无关。

失效 / 退登处理：
- **无今日校园「退出登录」入口**：每次打开 WebView 都清空 Cookie 再按 `_WEU` 重设（`WebViewFactory.kt:684`），因此 WebView 会话不跨应用持久，`_WEU` 失效时用户会看到学工登录页（**推断**：代码未处理该场景）。
- 登录态自动修复在课程表页：`checkStuLogin`（POST getConfigUserInfo.do）返回 false → `goToStu` 重新刷新（`JxglstuCourseTableUI.kt:297-317`）。**TodayCampus 页本身不检测 `stu` Cookie 有效性**，只刷新应用目录。
- 历史记录：`docs/update/4.16.md:36`（学工系统/今日校园入口，登录暂跳浏览器）→ `4.17.md:40`（新增学工平台登录）→ `4.18.md:92`（刷新登录态后可用部分功能）→ `4.21.md:27`（修复今日校园页搜索删字崩溃）。

---

## 5. 仓库未覆盖的今日校园功能 + 可推断的 H5 微服务路径规律

### 5.1 未覆盖（只做到「入口壳 + WebView」）

| 功能（应用目录中存在） | 应用编码 | 仓库覆盖度 |
|---|---|---|
| 学生请假 | `swmxsqjapp` | 仅入口打开（WebView），无提交请假接口 |
| 签到助手 | `swmqdzsapp` | 仅入口 |
| 健康信息收集 / 健康档案 | `swmxsyqxxsjapp` / `swmxsjkdaapphfut` | 仅入口 |
| 节假日离校 | `swmjjrlfxapp` | 仅入口 |
| 综合测评 / 奖学金 / 助学金 / 勤工助学 / 助学贷款 / 困难补助 / 困难生 | `swmzhcptybbapp` / `swmjxjapp` / `swmzxj` / `swmqgzxapp` / `swmzxdkapp` / `swmknbzapp` / `swmknsapp` | 仅入口 |
| 心理服务 11 项 | `swmxl*app` | 仅入口 |
| 一卡通 / 水电 / 成绩 | — | **在本仓库中不走今日校园**：一卡通走慧新易校（`HUI_XIN_URL`，`Constant.kt:48`、`CasLoginRepository.goToHuiXin`）；水电走慧新易校/呱呱物联（`SHOWER_URL` 等）；成绩走教务（jxglstu/jwglapp）与智慧社区。今日校园应用目录（`stu.json` 50 条）中无这三类应用——这是 HFUT 的站内分工，不代表金智今日校园产品能力边界（**推断**） |
| 签到/请假等的**数据读取与提交** | — | **未能证实**：仓库没有逆向这些 H5 内部的 `.do` 业务接口 |

### 5.2 H5 微服务路径规律（**推断**，基于 3 个已观察端点 + 50 个 openUrl）

- 学工系统根：`https://stu.hfut.edu.cn/`（`Constant.kt:83`；注意 31 个 openUrl 是 `http://`）。
- 应用入口统一形态：`{STU_URL}/xsfw/sys/{appCode}/*default/index.do`，个别带 `#` 尾巴；`appCode` 形如 `swm<拼音缩写>app[+机构后缀 hfut]`（如 `swmxsqjapp` = 学生申请请假？`swmjbxxapp` = 基本信息）。
- 后端 `.do` 接口与入口同前缀：`/xsfw/sys/{appCode}/...`，已见两种子结构：
  - `xgutilapp/userinfo/getConfigUserInfo.do`（公共用户信息）
  - `xggzptapp/modules/{module}/{action}.do`（学工工作平台：`modules/xszm/getFxYy.do`，参数 `data` 为 JSON 字符串，含 `FZDM` 分组码、`pageSize`、`pageNum`）
- **推断**：每个 `swm*app` 的 H5 内部同样以 `/xsfw/sys/{appCode}/modules/{module}/{action}.do` 或 `/{action}.do` 形式提供 JSON，`data={...}` 作为统一查询包（`FZDM` 类似「分组/菜单码」）；这类接口通常要求 `_WEU` Cookie + 金智前端 `Weu` 签名头。**未能证实**（仓库无代码）。
- 目录来源：线上真实目录应为 `xggzptapp/modules/xszm/getFxYy.do`（`StuService.kt:21-27`）或智慧社区 `listApplication`；本地 `stu.json` 是某次抓取的快照，**无自动更新机制**（`TodayCampus.kt:396-408` 只读 assets），因此会随学校调整而过期。

---

## 6. HFUT 专属常量 vs 金智通用规律（可迁移性判断）

| 项 | 归属 | 证据 | 迁移到 FJTCM 需替换? |
|---|---|---|---|
| `https://cas.hfut.edu.cn/`、`/cas/checkInitParams`、`/cas/login`、`/cas/vercode`、`/cas/oauth2.0/authorize` | HFUT 域名 + 金智/通用 CAS 路径 | `Constant.kt:60`、`LoginService.kt:16-54` | **域名必换**；路径需在目标 CAS 实测 |
| `LOGIN_FLAVORING` Cookie 作 AES key、`CryptoUtil.encryptAES`（AES-ECB+Base64） | 该 CAS 前端定制（金智系常见但非标准 CAS 规范） | `AesKeyInterceptor.kt:15-27`、`LoginUI.kt:151-153`、`CryptoUtil.kt:26-37` | **必须实测目标 CAS 是否同款**；否则改用目标自身的加密/明文方案 |
| 表单 `username/password/execution/_eventId=submit/capcha` | 通用 CAS 表单（`capcha` 拼写为实施方特征） | `LoginService.kt:29-36`、`docs/HfutApi.md:71-82` | 字段名需以目标登录页 HTML 为准 |
| `execution` 形如 `e1s1`，缺省回退 `"e1s1"` | 通用 CAS 执行令牌 | `CasLoginRepository.kt:75` | 可复用逻辑，值需现取 |
| 必须带 PC UA | 该 CAS 的反爬/适配要求 | `Constant.kt:154`、`LoginService.kt:27/41`、`HfutApi.md:41` | 通用建议保留 |
| TGC Cookie → `cas/login?service=` → `Location` 里 `ticket=ST-…` | 标准 CAS 协议 | `LoginViewModel.kt:93-99`、`RedirectTicketInterceptor.kt:21-37` | 协议级可复用，service 白名单需对方确认 |
| OAuth2 `client_id=BsHfutEduPortal`（信息门户）、`Hfut2023Ydfwpt`（慧新易校） | HFUT 专属客户端注册 | `CasLoginRepository.kt:46-59`、`HfutApi.md:100-102` | **不可迁移**，需目标方 client_id |
| 学工系统 `https://stu.hfut.edu.cn/`、`xsfw/sys/*` | 金智「今日校园」校园侧部署 | `Constant.kt:83`、`StuService.kt:15-21`、`stu.json` | **域名必换**；`xsfw/sys` 结构若同为金智今日校园则高度可复用 |
| `_WEU` 会话 Cookie | 金智今日校园会话语义（HFUT 实例） | `RedirectTicketInterceptor.kt:171-185` | 需实测目标今日校园 Cookie 名是否为 `_WEU` |
| `xggzptapp/modules/xszm/getFxYy.do` + `data={"FZDM":"SCYY","pageSize":"500","pageNum":1}` | 金智学工工作平台接口（`SCYY` 疑为「日常应用/收餐应用」分组码，**推断**） | `StuService.kt:21-27` | 结构可参考，**分组码/字段须实测** |
| 应用目录模型 `datas[].apps[]{name,iconUrl,openUrl}`；图标 `res.campushoy.com`/`cpdaily-resource.oss-*.aliyuncs.com` | 金智今日校园标准数据模型 | `TodayCampusAppResponse.kt:5-19`、`stu.json` | 模型可复用；**数据/图标 URL 不可复用** |
| 应用编码 `swm*app` / `swm*apphfut` | HFUT 侧按校情配置 | `stu.json`（50 条） | **不可复用**，需抓 FJTCM 自己的目录 |
| 官方 App 包名 `com.wisedu.cpdaily` | 金智「今日校园」统一包名 | `Starter.kt:48`、`AndroidManifest.xml:22` | **可直接复用**（若 FJTCM 也用今日校园 App） |
| `WebViewFactory.setInitial`/`sharedInterceptRequest` 的 Cookie 清空+注入模式 | 通用实现套路 | `WebViewFactory.kt:661-741` | 可复用（实现层面） |

结论（给 FJTCM 的可迁移性）：
1. **高可复用**：CAS 协议骨架（checkInitParams→login→execution/cookie→POST→TGC→service 换 ticket→302 ticket 换应用 Cookie）、WebView Cookie 注入、应用目录数据模型、官方 App 包名启动。
2. **必须替换/实测**：所有域名、CAS 前端加密方式（LOGIN_FLAVORING 是否同款）、`execution`/`_eventId`/`capcha` 字段、OAuth2 client_id、今日校园会话 Cookie 名（`_WEU`）、应用编码目录与 `FZDM` 分组码、service 白名单。
3. **完全不可复用**：`stu.json` 50 应用快照、HFUT 专属 `swm*apphfut` 编码、`Hfut2023Ydfwpt` 等客户端注册。
4. 若 FJTCM 的今日校园同为**金智教育**产品（**未能证实**，本仓库无 FJTCM 证据），则 `xsfw/sys/*`、`*default/index.do`、`datas[].apps[]` 模型层大概率同构，只需换域名与编码。

---

## 7. 风险点（实现/移植时必读）

| # | 风险 | 证据 | 影响/建议 |
|---|---|---|---|
| R1 | **图片验证码**：`needCaptcha` 由 `cas/checkInitParams` 的 `vercode` 决定 | `CasFlavorSessionResponse.kt:5-13`、`LoginUI.kt:778` | 可能随机触发；仓库靠 OCR（Tesseract 自训，`tools/Captcha-Ocr/README.md`）或人工 |
| R2 | **AES key 依赖 Cookie**：密钥来自 `LOGIN_FLAVORING`，且 `AesKeyInterceptor` **未命中时把空串写回**（27 行无条件 `saveString`） | `AesKeyInterceptor.kt:13-30` | 并发/首启失败会得到空 key → 密码加密错误；移植时应改为「保留旧值/失败抛错」 |
| R3 | **ticket 一次性 + 短时效**：`ST-` ticket 用一次即废 | `RedirectTicketInterceptor.kt:23-37`、`docs/HfutApi.md:51` | 每次平台刷新都要新的 `cas/login?service=`；不能缓存 ticket 复用 |
| R4 | **Cookie 生命周期未知**：TGC/`_WEU` 有效期无代码解析；学工只能靠「响应含学号」探测 | `OthersRepository.kt:161-172`、`LoginViewModel.kt:93-99` | 失效要靠 `checkStuLogin` 轮询式自愈；无 refresh token 机制 |
| R5 | **设备/UA 要求**：CAS 必须 PC UA，且各接口对 UA 敏感 | `Constant.kt:154`、`docs/HfutApi.md:41/92/136` | 移植时统一 UA，注明来源 |
| R6 | **HTTP 明文**：50 个应用中 31 个 `http://`，`_WEU` 注入 http URL；App 全局允许明文 | `stu.json`、`network_security_config.xml:2-4`、`AndroidManifest.xml:42` | 混合内容/中间人风险；WebView 需 `setAcceptThirdPartyCookies(true)`（`WebViewFactory.kt:681`） |
| R7 | **反爬/风控**：`docs/HfutApi.md:136`、`LoginUI.kt:447` 提到教务会封 IP / 拒绝响应；CAS 有验证码 | 同上 | 高频刷新（多平台并行登录）易触发；需节流、随机化 |
| R8 | **应用目录会过期**：`stu.json` 为内置快照，无前端更新 | `TodayCampus.kt:396-408` | FJTCM 若照搬，应改为从 `getFxYy.do`/智慧社区动态拉取并兜底缓存 |
| R9 | **静默失败**：学工登录失败只写日志、不提示 | `RedirectTicketInterceptor.kt:183-185` | 用户会以为已登录；移植应给明确失败态 |
| R10 | **凭据落盘**：CAS 账号密码以明文 SharedPreferences 保存（`Username`/`Password`）| `LoginUI.kt:130-137`、`SharedPrefs.kt:22-28` | 安全红线；移植不得复用该做法（应 DPAPI/系统钥匙串，且不落 Web） |
| R11 | **仓库自带密钥**：`Constant.kt:11` 硬编码 Gitee token | `Constant.kt:11` | 与本链路无关，但提示该仓库「常量池即配置」的风格不宜照搬 |
| R12 | **接口变更**：学工登录参数官方文档都写「需 JS 逆向」 | `docs/HfutApi.md:1720-1722` | `_WEU`/目录接口一旦改版，整条链路失效；需契约测试与降级（仅入口跳官方 App） |

---

## 8. 证据表（结论-证据-置信度）

| # | 结论 | 证据（文件:行 / URL） | 置信度 |
|---|---|---|---|
| E1 | CAS 用 `cas/checkInitParams` 下发 `LOGIN_FLAVORING` 作 AES key，密码 AES-ECB+Base64 后作为 `password` 表单提交 | `LoginService.kt:16/29-36`、`AesKeyInterceptor.kt:15-27`、`LoginUI.kt:151-153`、`CryptoUtil.kt:26-37`、`HfutApi.md:26-31/75` | 高（代码+文档一致） |
| E2 | CAS 登录 POST 需 `execution`（缺省 e1s1）+ `_eventId=submit` + `capcha` + PC UA | `CasLoginRepository.kt:75`、`LoginService.kt:26-37`、`Constant.kt:154`、`HfutApi.md:71-82` | 高 |
| E3 | 登录成功判据 = 302 且 `Location` 含 ticket；TGC 从 Set-Cookie 保存 | `LoginViewModel.kt:90-100`、`LoginUI.kt:196-202` | 高 |
| E4 | 学工系统登录 service = `STU_URL + xsfw/sys/xgutilapp/userinfo/getConfigUserInfo.do` | `CasLoginType.kt:10` | 高 |
| E5 | 学工入口 `xsfw/sys/jbxxapp/*default/index.do?ticket=` 换 `_WEU`，并校验响应体含学号 | `StuService.kt:15-18`、`RedirectTicketInterceptor.kt:21-37/171-185` | 高 |
| E6 | 学工登录态探测 POST `getConfigUserInfo.do`，响应含学号=有效 | `OthersRepository.kt:161-172`、`StuService.kt:17-18` | 高 |
| E7 | 今日校园应用目录接口 `xggzptapp/modules/xszm/getFxYy.do`，`data={"FZDM":"SCYY","pageSize":"500","pageNum":1}` | `StuService.kt:20-27` | 高（接口定义）/ 未调用（用法未能证实） |
| E8 | 应用目录 JSON 模型 = `datas[].apps[]{name,iconUrl,openUrl}`；内置快照 11 类 50 应用 | `TodayCampusAppResponse.kt:5-19`、`app/src/main/assets/stu.json`（PowerShell 解析） | 高 |
| E9 | UI 打开应用 = 取 `prefs("stu")` 的 `_WEU` → WebView；`setInitial` 清空全部 Cookie 后 setCookie 再 loadUrl | `TodayCampus.kt:178/217-222`、`WebViewFactory.kt:661-699`、`WebViewForActivity.kt:137` | 高 |
| E10 | 不注入 CAS TGC/ticket 到 WebView；ticket 只在 OkHttp 302 follow 用一次 | `RedirectTicketInterceptor.kt:23-37`、`WebViewFactory.kt:679-698` | 高 |
| E11 | 智慧社区 `listApplication` 提供动态目录（`X-Access-Token`），按 `STU_URL` 前缀过滤，供今日校园页「智慧社区」分组 | `CommunityService.kt:106-108`、`CommunityRepository.kt:342-357`、`TodayCampus.kt:172-177/190-194` | 高 |
| E12 | 登录成功后经 `SuccessActivity(isSuccessActivity=true)`→`MainScreen(isLogin=true)`→课程表页并行刷新各平台登录态（含学工），WebVPN 模式跳过学工 | `Starter.kt:306-315`、`SuccessActivity.kt:22-30`、`HomeDestination.kt:39-45`、`MainUI.kt:1144-1150`、`JxglstuCourseTableUI.kt:213-317` | 高 |
| E13 | OAuth2 用 `cas/oauth2.0/authorize`，client_id=`BsHfutEduPortal`（门户）/`Hfut2023Ydfwpt`（慧新易校） | `LoginService.kt:47-54`、`CasLoginRepository.kt:46-59`、`HfutApi.md:94-104` | 高 |
| E14 | `GotoInterceptor` 截获 `code=`/`synjones-auth=`，`RedirectTicketInterceptor` 用 `hit()` 判定目标平台（含 WebVPN 编码 URL） | `GotoInterceptor.kt:17-24`、`RedirectTicketInterceptor.kt:169` | 高 |
| E15 | 今日校园官方 App 包名 `com.wisedu.cpdaily`，可一键启动 | `Starter.kt:43-58/62-79`、`AndroidManifest.xml:21-31`、`TodayCampus.kt:126` | 高 |
| E16 | `_WEU` 的结构/有效期、H5 业务接口（签到/请假等）在仓库中均无解析 | 全仓 586 个 app `.kt` + network-api 全量 grep 无 `_WEU` 解析/`swm*app` 业务调用 | 高（「未覆盖」可证）/ 内容未知 |
| E17 | 仓库当前版本未调用 `StuService.login(ticket)` 与 `getStuApps()` | 899 个抓取文件 grep：仅 `OthersRepository.kt:163` 调 `stu.checkLogin` | 高 |
| E18 | FJTCM 今日校园是否同为金智体系、CAS 是否同款 LOGIN_FLAVORING | 本仓库无 FJTCM 相关文件 | **未能证实**（需另行查证） |
| E19 | 学工 `_WEU` 失效后的页面行为（登录页/错误页） | 代码无处理分支 | **未能证实**（推断为学工登录页） |
| E20 | `getFxYy.do` 的真实返回体与 `stu.json` 是否同构 | 模型字段与快照一致，但无实测 | **推断**（中） |

---

## 9. 未决问题（交给后续/实测）

1. FJTCM 的 CAS 是否为金智同款（`LOGIN_FLAVORING` + `execution=e1s1` + `capcha`）？——需在**授权范围内**用浏览器开发者工具观测目标登录页（本次约束禁止探测）。
2. FJTCM「今日校园/学工系统」域名与 `xsfw/sys` 前缀是否存在？会话 Cookie 是否叫 `_WEU`？
3. `getFxYy.do` 的 `FZDM` 取值表（`SCYY` 之外还有哪些）与 `data` 包结构。
4. `_WEU` 的有效期、是否刷新、服务端签名头（金智 `Weu` 系列）如何校验。
5. 目标校应用目录是否可从公开（未登录）页面获得，或必须登录后抓取。
6. 若目标校不用金智今日校园（而用别家学工 H5），则本报告 §2 的 CAS 骨架仍需重做适配，§3 的 `xsfw` 体系全部作废。

---

## 附录 A：本次抓取的源码清单（`_scratch_repo/`，文件名=`路径.replace('/','_')`）

- `network-api/src/main/java/**`（220 个 .kt 全量：StuService/LoginService/CommunityService/Constant/模型/CasFlavorSessionResponse…）
- `network-core/src/main/java/**`（BaseServiceCreator/ClientBuilderHelper/StatusCode）
- `common-logic/src/main/java/**`（NetworkUiState/UiStateHolder）
- `app/src/main/java/**`（**586 个 .kt 全量**）
- `docs/**`（HfutApi.md、教务系统登录思路.txt、update/4.9~4.21 等）
- `tools/`（Captcha-Ocr、Login-Web-Python、webvpn、All-Programs-Get-Python 的文本文件）
- `sql/supabase.sql`、`app/src/main/assets/stu.json`、`AndroidManifest.xml`、`network_security_config.xml`、`README.md`
- Lead 预抓的 27 个关键文件在 `C:\Users\Ko_Li\.openclaw\workspace\_research\hfut-src\`（同名规则），本文行号与其一致。

## 附录 B：关键 URL 速查

```
CAS:  https://cas.hfut.edu.cn/cas/checkInitParams            (GET, 取 LOGIN_FLAVORING/vercode)
      https://cas.hfut.edu.cn/cas/login?service=<svc>       (GET 取 execution / POST 登录)
      https://cas.hfut.edu.cn/cas/vercode?timestamp=…       (GET 图片验证码)
      https://cas.hfut.edu.cn/cas/oauth2.0/authorize?response_type=code&client_id=…&redirect_uri=…
学工: https://stu.hfut.edu.cn/xsfw/sys/jbxxapp/*default/index.do?ticket=<ST-…>
      https://stu.hfut.edu.cn/xsfw/sys/xgutilapp/userinfo/getConfigUserInfo.do   (POST)
      https://stu.hfut.edu.cn/xsfw/sys/xggzptapp/modules/xszm/getFxYy.do          (POST data={"FZDM":"SCYY","pageSize":"500","pageNum":1})
智慧社区: https://community.hfut.edu.cn/api/sys/cas/client/validateLogin?service=…&ticket=…
         https://community.hfut.edu.cn/api//mobile/community/application/listApplication  (X-Access-Token)
应用入口: https://stu.hfut.edu.cn/xsfw/sys/<appCode>/*default/index.do
```

---

*本文只做静态分析，未对 hfut/fjtcm 任何域名发起请求；未读取/使用任何真实凭据。分析时间 2026-11-13。*
