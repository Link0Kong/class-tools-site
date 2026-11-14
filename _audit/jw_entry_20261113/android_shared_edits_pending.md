# Android「教务 WebView 直进 + 自动登录」待补共享文件改动（task-6 · 增量 55）

> **状态（2026-11-13 22:12）：已全部套用并验证通过** —— 并行会话静默窗口（21:57–22:12 无写盘、HEAD 仍 e7553a3）后按「读当前文件→精确 edit」补回；`:app:compileDebugKotlin` 通过，`testDebugUnitTest` **1135/0**，`assembleRelease --no-build-cache --no-daemon` 成功，APK 见 `artifacts/classtools-4.46.1-release-signed.apk`（3,141,833 B / SHA-256 `9074038E…7ACCF` / vc63）。
> 生成：2026-11-13 21:5x（android-dev / Lead 指示：先落 patch 说明，避免并行会话整体写回丢失）。
> 仓库：`C:\Users\Ko_Li\.openclaw\workspace\android-class-tools`；HEAD 当前 `e7553a3`（v4.46.0 / vc62）。
> 套用方式：**等对方写盘稳定 / HEAD 前进后，读当前文件 → 精确 edit 片段**（禁止整文件覆盖）。
> 每处改动后 `git diff --stat` 只应出现下列 hunk；新文件已就位、无需再动。

## 0. 已完成（新文件，均未与并行会话冲突）

| 文件 | 说明 |
|---|---|
| `app/src/main/kotlin/com/furina/classtools/features/jw/JwLoginLogic.kt` | 纯 Kotlin：URL/跳转 allowlist、注入 JS 生成与转义、密码校验/掩码、sid 匹配、Base64、状态文案常量 |
| `app/src/main/kotlin/com/furina/classtools/data/jw/JwCredentialStore.kt` | Android Keystore AES-256/GCM + SharedPreferences（sid+密文+IV），无日志/无私网、sid 不匹配即失效 |
| `app/src/main/kotlin/com/furina/classtools/ui/screens/jw/JwEntryScreen.kt` | 已**整体重写**为 WebView 直进页（一次性密码输入 / 自动填充提交 / 800ms 复核回退 / 顶栏「清除登录」清密码+Cookie+缓存） |
| `app/src/main/res/xml/network_security_config.xml` | base 禁明文 + 仅 `210.34.74.77` 放行 cleartext |
| `app/src/test/kotlin/com/furina/classtools/features/jw/JwLoginLogicTest.kt` | 纯 JVM 单测 18 项（JS 转义/allowlist/密码/掩码/解析/文案/Base64） |
| ~~`app/src/test/kotlin/com/furina/classtools/ui/screens/jw/JwEntryTest.kt`~~ | 已删除（旧「入口页 + ACTION_VIEW」实现的测试，常量已不存在） |

## 1. `app/build.gradle.kts`（约 26–27 行）

old:
```kotlin
        versionCode = 62
        versionName = "4.46.0"
```
new:
```kotlin
        versionCode = 63
        versionName = "4.46.1"
```

## 2. `app/src/main/kotlin/com/furina/classtools/data/tool/ToolCatalog.kt`

### 2a. import（`Notifications` 之后、保持字母序）
old:
```kotlin
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material.icons.rounded.Slideshow
```
new:
```kotlin
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material.icons.rounded.School
import androidx.compose.material.icons.rounded.Slideshow
```
（若当前版本 import 顺序不同，插到 `Notifications` 与下一个 `rounded.*` 之间即可；`BrandSlateBlue` 已在 HEAD import 中。）

### 2b. `val tools: List<AppTool> = listOf(...)` **末尾追加**（当前最后一项是 `diag`，其后紧接 `    )`）
new:
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
> 注意：并行会话当前删除了 `settings` 条目、游离于 HEAD 之外；本任务**不恢复** `settings`（那是对方 WIP），只追加 jw。

## 3. `app/src/main/kotlin/com/furina/classtools/ui/navigation/MainNavHost.kt`

### 3a. import（`HomeScreen` 之后）
new line:
```kotlin
import com.furina.classtools.ui.screens.jw.JwEntryScreen
```

### 3b. `when (toolId)` 内，`"ppt" -> ...` 之后、`else -> {` 之前
new:
```kotlin
                "jw" -> JwEntryScreen(
                    sid = session.sid,
                    onBack = { popTool(toolId) },
                )
```
> 若套用时当前文件没有 `popTool(...)`（并行会话回退），则用与相邻分支一致的
> `onBack = { navController.popBackStack() }`。`session` 在该 composable 作用域可用。

## 4. `app/src/main/AndroidManifest.xml`（`<application>` 属性，21:49 已由本会话写入，若被覆盖则重加）

old:
```xml
        android:label="@string/app_name"
        android:roundIcon="@mipmap/ic_launcher_round"
```
new:
```xml
        android:label="@string/app_name"
        android:networkSecurityConfig="@xml/network_security_config"
        android:roundIcon="@mipmap/ic_launcher_round"
```
> 红线：**不要**加 `android:usesCleartextTraffic="true"`；只挂 networkSecurityConfig。
> 兼容性：targetSdk≥28 默认本就禁明文，本配置不改变既有网络行为，仅额外放行 210.34.74.77（教务 HTTP）。

## 5. `app/src/main/kotlin/com/furina/classtools/ui/screens/guide/GuideContent.kt`

### 5a. VERSION（约 21 行）
old: `const val VERSION: String = "2026-11-13.1"`
new: `const val VERSION: String = "2026-11-13.2"`

### 5b. jw 卡（`id = "fit"` 卡之后、`id = "power"` 卡之前；21:52 已由本会话写入，若被覆盖则重加）
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
> 21 卡结构/顺序（jw 在 fit 之后）与 `UserGuideContentTest` 的 21 卡断言配套。

## 6. `app/src/test/kotlin/com/furina/classtools/ui/screens/guide/UserGuideContentTest.kt`

old（约 145 行）:
```kotlin
        assertEquals("2026-11-13.1", UserGuideContent.VERSION)
```
new:
```kotlin
        assertEquals("2026-11-13.2", UserGuideContent.VERSION)
```
（`assertFalse(... VERSION == "2026-11-12.1")` 保持不动。若并行会话已提交自己的版本，按当前值调整。）

## 7. `docs/CHANGELOG.md`

在**顶部**（v4.45.0 段之前）插入（数字在实跑后填）：

```markdown
## v4.46.1 · 2026-11-13（教务入口改「内置 WebView 直进 + 本机加密自动登录」）

- 点「教务」卡 = 直接进入内置 WebView（`http://210.34.74.77/sso.jsp`）并在统一身份认证页自动填充账号（当前身份学号）+密码并提交；去掉原「入口页 + 打开按钮」一步。
- 密码仅本机保存：Android Keystore AES-256/GCM + SharedPreferences（sid+密文+IV），不打日志/不上报/不同步；顶栏「清除登录」清密码 + Cookie + 缓存；身份 sid 变化/解密失败要求重输。
- 新增 `features/jw`（URL/跳转 allowlist、JS 注入与转义、密码校验/掩码）+ `data/jw`（Keystore 凭据存储）+ WebView 页；`res/xml/network_security_config.xml` 仅对 210.34.74.77 放行 cleartext（不全局开）；非校内/非 http(s) 跳转交给系统浏览器或阻止。
- 验证码 / 表单变化 / 提交失败 → 800ms 复核后回退人工（提示「自动登录失败，可能需验证码，请手动完成」），不循环重试。
- ToolCatalog/GuideContent 文案同步；单测 **N/0**（新增 JwLoginLogicTest 18 项）；Release X,XXX,XXX B / SHA-256 `...`（vc63，v2 签名）；按任务口径未做真机/真实账号验证（红线）。
```

## 8. 套用后验证顺序（在 tree 可编译后）

```powershell
$env:JAVA_HOME='C:\AndroidToolchain\jdk17'; $env:ANDROID_HOME='C:\AndroidToolchain\sdk'
cd C:\Users\Ko_Li\.openclaw\workspace\android-class-tools
.\gradlew.bat :app:compileDebugKotlin --no-daemon --console=plain
.\gradlew.bat :app:testDebugUnitTest --no-daemon --console=plain
.\gradlew.bat :app:assembleRelease --no-build-cache --no-daemon --console=plain
Copy-Item app\build\outputs\apk\release\app-release.apk artifacts\classtools-4.46.1-release-signed.apk -Force
Get-FileHash artifacts\classtools-4.46.1-release-signed.apk -Algorithm SHA256
```

## 9. 契约逐条对照（§5.3）

1. 点卡直进 WebView + 自动填充提交：`JwEntryScreen`（无已存凭据先 `JwLoginPromptDialog`；账号默认 session.sid，掩码展示；可「仅打开不保存」）✅
2. Keystore AES/GCM + SharedPreferences(sid+密文+IV)、不日志/不上报/不同步、顶栏「清除登录」清密码+Cookie、sid 变化要求重输：`JwCredentialStore` + `JwEntryScreen.clearLogin` ✅
3. WebView：JS/DOM storage/Cookies 开、禁 file access、仅 http(s)（校外 http(s) 交系统浏览器、非 http(s) 阻止）；`network_security_config.xml` 仅 210.34.74.77 cleartext、manifest 引用 ✅
4. 注入时机：onPageFinished 且 authserver `/authserver/login` → 300ms 填 `#username`/`#password`（input+change）→ `#login_submit`；800ms 复核 `#showErrorTip`/`#captchaDiv` → 回退人工；210.34.74.77 = 成功 ✅
5. 版本 4.46.1/vc63、ToolCatalog subtitle/features、GuideContent 卡文案、CHANGELOG、单测 + Release APK ⏳（待共享文件补回 + 构建）
6. 测试红线：全部单测只用**假账号/假密码**（9999 段），未登录任何真实教务账号 ✅（真机/真实 SSO 未验证，如实报告）
