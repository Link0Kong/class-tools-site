# Android「教务卡片页」待补共享文件改动（task-7 · JW_CARDS_V1_SPEC）

> **状态（2026-11-14 13:24）：已全部套用并验证通过** —— 并行会话静默 ≥5 分钟（最后写盘 13:15:12）后按「读当前文件→精确 edit」补回；`:app:testDebugUnitTest` **1177/0**（93 suites），`:app:assembleRelease --no-build-cache --no-daemon` **BUILD SUCCESSFUL 2m14s**，APK `artifacts/classtools-4.48.0-release-signed.apk`（3,141,837 B / SHA-256 `7543DAE44153ABF42525F2D62446058607E26B5FA0B7F8ED0B4BCE5D22E649B9` / vc66）。
> 生成：2026-11-14 13:2x（android-dev / Lead 指示：新增文件先写，共享文件等并行会话静默后精确 edit）。
> 仓库：`C:\Users\Ko_Li\.openclaw\workspace\android-class-tools`；HEAD `47d8f56`（v4.47.1 / vc65）。
> 套用方式：**等并行会话静默 ≥3 分钟 + `:app:compileDebugKotlin` 通过后，读当前文件 → 精确 edit**（禁止整文件覆盖）。
> 若版本号已被并行会话占用 → 顺延并报告（如 vc66 被占则用 vc67 / 4.48.1，并在交付说明注明）。

## 0. 已完成（新增文件，独占无冲突）

| 文件 | 内容 |
|---|---|
| `app/src/main/kotlin/com/furina/classtools/data/jw/JwApiModels.kt` | `JwApiPage`/`JwApiResult`（Success/ApiError/SessionExpired/Malformed）+ 成绩/考试/选课/公告 4 类行模型（官方字段 → camelCase，全部默认空串） |
| `app/src/main/kotlin/com/furina/classtools/data/jw/JwApiClient.kt` | `JwApiSpec`：4 个官方端点 + URL/参数/请求头构造 + HTTP 闸门（HTML→会话失效）+ 宽松 JSON 解析；`JwApiClient`（复用仓库既有 `HttpTransport`/`OkHttpTransport`，10s 超时） |
| `app/src/main/kotlin/com/furina/classtools/data/jw/JwCardsRepository.kt` | 并行拉 4 接口（coroutineScope/async）、单卡失败隔离、`sessionExpired` 汇总、cookie 缺失短路 |
| `app/src/main/kotlin/com/furina/classtools/ui/screens/jw/JwCardModels.kt` | `JwDataCardKind`/`JwOfficialTool`/`JwCardCatalog`（8 个官方工具入口）/`JwCardMapper`（结果→卡片文案，纯 Kotlin）/`JwCardTexts`/`JwCardConfig` |
| `app/src/main/kotlin/com/furina/classtools/ui/screens/jw/JwCardsSection.kt` | Compose 卡片页：状态条 + 4 数据卡（2 列）+ 8 官方工具入口卡（2 列）+「打开完整教务官网」；单卡失败态内嵌「重试」 |
| `app/src/test/.../data/jw/JwApiClientTest.kt` | URL/参数/请求头/HTTP 闸门/4 类 JSON 解析/失败态/客户端接线（假 HttpTransport，合成夹具） |
| `app/src/test/.../data/jw/JwCardsRepositoryTest.kt` | 并行拉取/单卡失败隔离/会话失效/cookie 缺失/空态 |
| `app/src/test/.../ui/screens/jw/JwCardModelsTest.kt` | 官方工具清单/4 卡 READY/EMPTY/ERROR 映射/目标 URL/更新时间文案 |
| `app/src/main/kotlin/.../ui/screens/jw/JwEntryScreen.kt` | **改造完成**：LOGIN/CARDS/WEB 三模式（卡片页 + 全屏 WebView 切换）；保留 v4.46.1 自动登录/验证码回退/清除登录/凭据存储；登录成功取 CookieManager cookie → 拉 4 接口；会话失效自动重登 1 次；刷新/单卡重试共用 refreshSeq |

## 1. `app/build.gradle.kts`（约 26–27 行）

old（当前 HEAD）:
```kotlin
        versionCode = 65
        versionName = "4.47.1"
```
new:
```kotlin
        versionCode = 66
        versionName = "4.48.0"
```
> 套用时先确认当前值：若并行会话已改到 66/4.48.0 或更高，顺延（67/4.48.1…）并记录。

## 2. `app/src/main/kotlin/com/furina/classtools/data/tool/ToolCatalog.kt`（jw 条目）

old:
```kotlin
        AppTool(
            id = "jw",
            name = "教务",
            subtitle = "直达教务 · 自动登录",
            icon = Icons.Rounded.School,
            accent = BrandSlateBlue,
            category = ToolCategory.STUDY,
            features = listOf(
                "点卡片直接进入内置教务网页",
                "本机加密保存密码，自动登录",
                "验证码或失败时手动完成；可一键清除",
            ),
        ),
```
new:
```kotlin
        AppTool(
            id = "jw",
            name = "教务",
            subtitle = "卡片速览 · 自动登录",
            icon = Icons.Rounded.School,
            accent = BrandSlateBlue,
            category = ToolCategory.STUDY,
            features = listOf(
                "成绩 · 考试 · 选课 · 公告速览",
                "8 个官方工具入口，App 内打开",
                "自动登录；数据只在本机内存展示",
            ),
        ),
```
> 注意：并行会话 13:09 在该文件另加了「点名 roll」工具（未提交），只改 jw 段，勿动其它条目。

## 3. `app/src/main/kotlin/com/furina/classtools/ui/screens/guide/GuideContent.kt`

### 3a. VERSION
old: `const val VERSION: String = "2026-11-13.2"`（以套用时当前值为准；若被并行会话改过，在当前值上递增为 `2026-11-14.1`）
new: `const val VERSION: String = "2026-11-14.1"`

### 3b. jw 卡（`id = "fit"` 之后、`id = "power"` 之前）
old:
```kotlin
        GuideCard(
            id = "jw",
            category = GuideCategory.STUDY,
            title = "教务入口",
            subtitle = "点卡片直达，自动登录",
            steps = listOf(
                "点「教务」卡片直接进教务系统",
                "首次输入密码可加密存本机",
                "验证码或失败时手动完成",
            ),
            tip = "密码只存本机；校外打不开先连学校 VPN",
            scene = GuideScene.GRID,
            tone = GuideTone.BLUE,
        ),
```
new:
```kotlin
        GuideCard(
            id = "jw",
            category = GuideCategory.STUDY,
            title = "教务入口",
            subtitle = "卡片速览，官方数据",
            steps = listOf(
                "点「教务」卡片看成绩/考试/选课/公告",
                "8 个官方工具入口 App 内打开",
                "登录后自动拉取，数据只在内存",
            ),
            tip = "密码只存本机；校外打不开先连学校 VPN",
            scene = GuideScene.GRID,
            tone = GuideTone.BLUE,
        ),
```
> 文案硬规则（既有单测）：标题≤8、subtitle≤20、steps 3 条每条≤24、tip≤30、不含实现细节关键词。

## 4. `app/src/test/kotlin/com/furina/classtools/ui/screens/guide/UserGuideContentTest.kt`

old（约 145 行）: `assertEquals("2026-11-13.2", UserGuideContent.VERSION)`
new: `assertEquals("2026-11-14.1", UserGuideContent.VERSION)`
（若并行会话已改该断言，按当前值向 `2026-11-14.1` 对齐；`assertFalse(... "2026-11-12.1")` 保持不动。）

## 5. `docs/CHANGELOG.md`（顶部插入，数字实跑后填）

```markdown
## v4.48.0 · 2026-11-14（教务工具页改「卡片速览 + 官方接口数据 + 官方工具入口」）

- 点「教务」卡 = App 内卡片页：4 张官方接口数据卡（成绩/考试/选课/公告，官方 JSON 接口只读 GET）+ 8 张官方工具入口卡（学期理论课表/课程成绩查询/学生选课中心/考试安排查询/培养方案明细/已收公告/缓考申请/社会考试报名）+「打开完整教务官网」。
- 登录复用自动登录（sso.jsp → authserver 注入 → 回 210 视为成功）；登录后从 CookieManager 取同域 cookie，原生 HTTP GET 4 个官方接口（pageNum/pageSize + Cookie/UA/Referer/X-Requested-With/Accept），单卡失败隔离；返回 HTML/登录页判会话失效并自动重登 1 次。
- 点任意卡片 = App 内置 WebView 全屏打开对应官方页面，返回回卡片页；**App 不调用任何写接口**（选课/报名/缓考等写操作只在官方页面内由用户完成）。
- 安全：密码仍只本机 Keystore 加密保存；cookie 只在请求瞬间使用，不落盘/不打日志/不上传；卡片数据只内存展示；「清除登录」清密码 + Cookie + WebStorage + 缓存。
- 实测口径（2026-11-14 本人账号一次性勘察）：4 个接口均可用但当前无数据（count 全 0），**空态为正常路径**；有数据行渲染按官方字段 + 合成夹具实现，**未用真实有数据账号验证**。
- 单测 **N/0**（新增 JwApiClientTest/JwCardsRepositoryTest/JwCardModelsTest）；Release X,XXX,XXX B / SHA-256 `…`（vc66，v2 签名）；未做真机验证（如实）。
```

## 6. 套用后验证顺序（tree 可编译后）

```powershell
$env:JAVA_HOME='C:\AndroidToolchain\jdk17'; $env:ANDROID_HOME='C:\AndroidToolchain\sdk'
cd C:\Users\Ko_Li\.openclaw\workspace\android-class-tools
.\gradlew.bat :app:compileDebugKotlin --no-daemon --console=plain
.\gradlew.bat :app:testDebugUnitTest --no-daemon --console=plain
.\gradlew.bat :app:assembleRelease --no-build-cache --no-daemon --console=plain
Copy-Item app\build\outputs\apk\release\app-release.apk artifacts\classtools-4.48.0-release-signed.apk -Force
Get-FileHash artifacts\classtools-4.48.0-release-signed.apk -Algorithm SHA256
```

## 7. 已知限制（交付时如实说明）

1. **真机/真实数据未验证**：卡片数据只用 Lead 勘察记录的官方字段 + 合成夹具；本账号当前 4 接口 count 全 0（空态），有数据行渲染未用真实账号验证（官方改版/字段变化时降级为空态或失败态，不崩溃）。
2. 验证码/自动登录失败沿用 v4.46.1 回退人工提示。
3. WebView 与系统 WebView 版本相关；官方页面内写操作由用户完成，App 不代操作。
4. 会话失效自动重登最多 1 次（规格 §1）；仍失败显示「登录失效，请重试」。
5. cookie 不持久化到磁盘（仅在 CookieManager 内存/系统管理），App 不写入任何 cookie 到文件。
