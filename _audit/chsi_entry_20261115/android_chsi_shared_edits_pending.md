# Android「学信网卡片页」待补共享文件改动（task-9 · CHSI_ENTRY_SPEC §3）

> **状态（2026-11-15 14:12）：已全部套用并验证通过** —— 并行会话静默 ≥1.5h（最后写盘 12:27:36）后按「读当前文件→精确 edit」补回，保留并行未提交 WIP（OPPO 推送/地图/点名/通知等）；`:app:testDebugUnitTest` **1276/0**（100 suites），`:app:assembleRelease --no-build-cache --no-daemon` **BUILD SUCCESSFUL 4m32s**，APK `artifacts/classtools-4.53.0-release-signed.apk`（3,284,845 B / SHA-256 `DA22AC202FFC77B0C54803E94CADACC43BDD80FFA17314217C27DE6F6F9E14BC` / vc71）。
> 生成：2026-11-15 14:0x（android-dev / Lead 口径：新增文件先写，共享文件等并行会话静默后精确 edit）。
> 仓库：`C:\Users\Ko_Li\.openclaw\workspace\android-class-tools`；HEAD `040473e`（v4.50.0）；**工作树有并行会话未提交 WIP**（版本 4.52.0/vc70，OPPO 推送/地图/点名等）。
> 套用方式：**并行会话静默 ≥3 分钟 + `:app:compileDebugKotlin` 通过后，读当前文件 → 精确 edit**（禁止整文件覆盖，保留并行 WIP）。

## 0. 已完成（新增文件，独占路径无冲突）

| 文件 | 内容 |
|---|---|
| `app/src/main/kotlin/com/furina/classtools/features/chsi/ChsiModels.kt` | `ChsiPagePayload`/`ChsiLink`、`ChsiOfficialTool`（10 项）、`ChsiDataCardKind`（4 卡）、`ChsiCardStatus`/`ChsiDataCardUi`、`ChsiCatalog`（URL/10 工具/UA 常量/数据卡 URL）、`ChsiTexts`（逐字文案） |
| `app/src/main/kotlin/com/furina/classtools/features/chsi/ChsiExtractLogic.kt` | 注入 JS 生成（body.innerText ≤6000 + links）、WebView 回调双层 JSON 解码、宽容 JSON 解析、标签就近取 1–3 行、空态降级、18 位身份证/11 位手机号掩码、URL/登录态判定、更新时间文案 |
| `app/src/main/kotlin/com/furina/classtools/ui/screens/chsi/ChsiEntryScreen.kt` | LOGIN（官方登录页，用户手动）/ CARDS（卡片页）/ WEB（官方页面全屏）三模式；进入加载档案 wap 页；登录后注入提取；刷新/去登录/退出登录（清 Cookie+WebStorage+缓存）；「桌面版/手机版」UA 切换；仅 http(s) 导航、禁 file/content access、JS/DOM storage/Cookies 开 |
| `app/src/main/kotlin/com/furina/classtools/ui/screens/chsi/ChsiCardsSection.kt` | 卡片页：状态条 + 『数据』4 卡 + 『官方工具』10 卡 + 底部两按钮；**LazyColumn + 窄屏 2 列/≥600dp 3 列**；点按 ≥48dp；文字最多 3 行省略；深浅色 token |
| `app/src/test/kotlin/com/furina/classtools/features/chsi/ChsiExtractLogicTest.kt` | 纯 JVM 单测（10 工具常量/UA/JS 只读/双层解析/宽容解析/标签映射/空态/掩码/URL 登录态/时间文案），全合成夹具 |

## 1. `app/build.gradle.kts`（约 42–43 行）

old（当前工作树 WIP 值）:
```kotlin
        versionCode = 70
        versionName = "4.52.0"
```
new:
```kotlin
        versionCode = 71
        versionName = "4.53.0"
```
> 套用时以**当前实际值**为准；若并行会话已推进到 71/4.53.0 或更高 → 顺延（如 72/4.53.1）并记录。

## 2. `app/src/main/kotlin/com/furina/classtools/data/tool/ToolCatalog.kt`

### 2a. import（School/Slideshow 之后，字母序 Verified）
old:
```kotlin
import androidx.compose.material.icons.rounded.School
import androidx.compose.material.icons.rounded.Slideshow
import androidx.compose.material.icons.rounded.WaterDrop
```
new:
```kotlin
import androidx.compose.material.icons.rounded.School
import androidx.compose.material.icons.rounded.Slideshow
import androidx.compose.material.icons.rounded.Verified
import androidx.compose.material.icons.rounded.WaterDrop
```

### 2b. tools 列表末尾（jw 条目之后、闭合 `    )` 之前）追加
old（jw 条目结尾）:
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
    )
```
new（在 jw 后加 chsi）:
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
        AppTool(
            id = "chsi",
            name = "学信网",
            subtitle = "学籍 · 学历 · 学位 · 官方入口",
            icon = Icons.Rounded.Verified,
            accent = BrandSlateBlue,
            category = ToolCategory.STUDY,
            features = listOf(
                "学籍 · 学历 · 学位摘要",
                "10 个官方工具入口，App 内打开",
                "本人在官方页面手动登录；数据仅内存",
            ),
        ),
    )
```

## 3. `app/src/main/kotlin/com/furina/classtools/ui/navigation/MainNavHost.kt`

### 3a. import（`ui.screens.activity.ActivityScreen` 之后 / 字母序）
new line:
```kotlin
import com.furina.classtools.ui.screens.chsi.ChsiEntryScreen
```

### 3b. `when (toolId)` 内，`"jw" -> JwEntryScreen(...)` 之后
new:
```kotlin
                "chsi" -> ChsiEntryScreen(
                    sid = session.sid,
                    onBack = { popTool(toolId) },
                )
```

## 4. `app/src/main/kotlin/com/furina/classtools/ui/screens/guide/GuideContent.kt`

### 4a. doc 注释（约 7 行）
old: `* 5 个分类（入门 / 学习 / 生活 / 协作 / 更多）、21 张卡、一屏一张左右滑动。`
new: `* 5 个分类（入门 / 学习 / 生活 / 协作 / 更多）、22 张卡、一屏一张左右滑动。`

### 4b. VERSION（约 21 行）
old: `const val VERSION: String = "2026-11-14.1"`
new: `const val VERSION: String = "2026-11-15.1"`

### 4c. jw 卡之后（`id = "power"` 生活卡之前）插入学信网卡
new:
```kotlin
        GuideCard(
            id = "chsi",
            category = GuideCategory.STUDY,
            title = "学信网入口",
            subtitle = "学籍 · 学历 · 学位官方入口",
            steps = listOf(
                "点「学信网」卡片看官方数据速览",
                "学信网需本人手动登录，App 不保存密码",
                "10 个官方入口 App 内打开",
            ),
            tip = "数据仅本机内存展示；证件号已掩码",
            scene = GuideScene.SHIELD,
            tone = GuideTone.MINT,
        ),
```
> 文案硬规则（既有单测）：标题≤8（学信网入口=5）、subtitle≤20（16）、steps 每条≤24（15/20/14）、tip≤30（16）、不含实现细节关键词；STUDY 分类 tone 不连续重复（jw=BLUE → chsi=MINT ✓）。

## 5. `app/src/test/kotlin/com/furina/classtools/ui/screens/guide/UserGuideContentTest.kt`

- 测试名：`21 张卡片且顺序与契约一致` → `22 张卡片且顺序与契约一致`
- `assertEquals(21, cards.size)` → `assertEquals(22, cards.size)`
- 顺序清单插入 `"chsi"`（在 `"jw"` 之后）：
```kotlin
                "identity", "home", "draw", "group", "roster", "hw", "nt", "tt", "fit", "jw", "chsi",
                "power", "water", "vote", "ppt", "reminder", "calendar", "permissions", "sort",
                "privacy", "feedback", "faq",
```
- `assertEquals(8, UserGuideContent.countOf(GuideCategory.STUDY))` → `9`
- 分类首下标：LIFE `10`→`11`、TEAM `12`→`13`、MORE `14`→`15`
- VERSION 断言：`assertEquals("2026-11-14.1", ...)` → `assertEquals("2026-11-15.1", ...)`
- 顶部注释「21 张卡」→「22 张卡」（如有）

## 6. `docs/CHANGELOG.md`（顶部插入，数字实跑后填）

```markdown
## v4.53.0 · 2026-11-15（新增「学信网」卡片页：数据卡 + 10 个官方工具入口）

- 新增「学信网」工具（`Icons.Rounded.Verified`、BrandSlateBlue、学习分类）：点卡片进入 App 内卡片页。
- 学信网有短信/验证码/实人核验，**无法自动登录**：进入即加载官方档案页，未登录时全屏显示官方登录页由**本人手动登录**，App 不预填/不保存/不上传学信网账号密码；登录成功后从官方页面**只读提取**学籍/学历/学位/在线验证报告文本摘要。
- 卡片页：状态条（已登录 · 数据更新 HH:mm / 未登录或会话过期，去登录/刷新）+『数据』4 卡（提取不到显示「已登录 · 打开官方页面查看」空态）+『官方工具』10 卡（规格 §1 实测 URL，内置 WebView 打开）+「打开完整学信档案」+「退出学信网登录」（清 Cookie/WebStorage/缓存）；WebView 顶栏「桌面版/手机版」UA 切换。
- 手机适配：LazyColumn；窄屏 2 列 / ≥600dp 3 列；状态栏/导航栏安全区；点按 ≥48dp；文字最多 3 行省略；深浅色 token。
- 安全：提取数据仅内存展示，不落盘/不上传/不打日志；展示前掩码 18 位身份证（保留前 6 后 4）与 11 位手机号（前 3 后 4）；WebView 禁 file/content access、仅 http(s)；不调用任何写接口。
- 单测 **N/0**（新增 ChsiExtractLogicTest X 项，全合成夹具）；Release X,XXX,XXX B / SHA-256 `…`（vc71，v2 签名）；**未用真实学信网账号验证、未做真机验证**（如实）。
```

## 7. 套用后验证顺序

```powershell
$env:JAVA_HOME='C:\AndroidToolchain\jdk17'; $env:ANDROID_HOME='C:\AndroidToolchain\sdk'
cd C:\Users\Ko_Li\.openclaw\workspace\android-class-tools
.\gradlew.bat :app:compileDebugKotlin --no-daemon --console=plain
.\gradlew.bat :app:testDebugUnitTest --no-daemon --console=plain
.\gradlew.bat :app:assembleRelease --no-build-cache --no-daemon --console=plain
Copy-Item app\build\outputs\apk\release\app-release.apk artifacts\classtools-4.53.0-release-signed.apk -Force
Get-FileHash artifacts\classtools-4.53.0-release-signed.apk -Algorithm SHA256
```

## 8. 已知限制（交付时如实说明）

1. **无法自动化/真机验证**：学信网登录需短信/验证码/实人核验，禁止用真实账号跑测试；提取逻辑按官方 wap 页面通用结构做**宽容提取 + 降级**，未用真实账号验证；官方改版时卡片降级为空态（「已登录 · 打开官方页面查看」），不崩溃。
2. 未在真机验证 WebView 登录页渲染/UA 切换/卡片 2→3 列断点（Compose 布局按 600dp 断点实现并单测常量）。
3. 不保存学信网账号密码；Cookie 由系统 CookieManager 管理，退出登录时清理；提取数据仅内存。
4. App 不调用学信网任何写接口；写操作只在官方页面内由用户完成。
