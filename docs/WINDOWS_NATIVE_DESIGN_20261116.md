# 班级工具站 Windows 原生版 · 全功能 + Win11 Fluent 设计方案

> 版本：v0.3（设计稿） · 日期：2026-11-16 · 状态：**范围已确认；M0 通过，M1 骨架已落地，按里程碑推进**
> 适用：**只在旅行者自己的 Windows 电脑上使用**；**功能全做**；**Win11 现代化 UI + 高质量交互**；不要 WebView/网页壳
> **2026-11-16 已确认**：全功能（含地图、PPT 播放器、大屏 V5）；安卓独有功能（今日校园/第二课堂/快递/学信网提取）不做；WinUI 3 工具链已通过。
> 代码：`C:\Users\Ko_Li\.openclaw\workspace\windows-class-tools`（`ClassTools.WinUI.sln`；M1 骨架：NavigationView + 标题栏 + 工作台 + 24 页导航占位）。
> 说明：本文 v0.3 直接取代 v0.2 的单机原生方案（同一文件已更新为全量范围）；v0.1 WebView2 壳方案见 [WINDOWS_DESKTOP_DESIGN_20261116.md](WINDOWS_DESKTOP_DESIGN_20261116.md)（已存档）。
> 关联契约：`AGENTS.md` §0/§1、`CLOUDBASE.md`、`HANDOFF.md` §5、`ppt/CONTRACT.md`、`vote/CONTRACT.md`、`draw/CONTRACT.md`、`drop/CONTRACT.md`、`tools/tests/_water_contract.md`
> 本文只做设计：不改网页、不改云端表/RLS/UD v6、不部署。

---

## 0. 结论（先看这里）

**推荐：WinUI 3（Windows App SDK）+ Fluent 2 + Mica 的原生 Windows 11 应用；直连 CloudBase；不引 WebView。**

- **全功能**：网页现有工具/页面/管理员能力/大屏/互联全部原生重做（清单见 §1）。
- **Win11 UI**：`NavigationView` + 自定义标题栏 + Mica 背景 + Fluent 2 令牌 + `ContentDialog`/`InfoBar`/`TeachingTip`/`CommandBar`/`SettingsCard` + 连接动画/隐式动画。
- **高质量交互**：键盘全可达、全局搜索、命令栏、上下文菜单、拖放、加载骨架、空态、错误态、离线态、乐观更新、撤销、减少动效适配、无障碍。
- **直连云端**：`HttpClient` + `Authorization` + `X-Class-Token`；不需要 CORS、不需要本机代理/HTML 重写、不依赖域名。
- **单机形态**：`dotnet publish` 自包含目录 + 双击 exe；不做安装器/自动更新/公用电脑模式/多用户。

**必须提前说清的成本**：这不是壳，是完整的第四端原生应用。全量 + 高质量 UI 约 **180–210 人日**；全职约 **5–6 个月**，每天 5 小时约 **8–10 个月**。如果希望更快，只能减少范围或对少数复杂页面接受浏览器/WebView 兜底（见 §1.3 的杠杆）。

**M0 技术验证（2026-11-16 已通过主项）**：本机没有 Visual Studio/独立 Windows SDK，但用 `dotnet` + NuGet 的 `Microsoft.WindowsAppSDK 2.6.4` + `Microsoft.Windows.SDK.BuildTools 10.0.28000.2957` **成功构建并启动**了 WinUI 3 工程（.NET 10，自包含未打包）；`NavigationView`、Mica、中文字体、`InfoBar`、品牌 Accent、自定义标题栏、**Office COM（PowerPoint 16.0）** 均验证通过。剩余 M0 项：`AppNotificationManager`、托盘、文件选择器。工程与骨架见 `C:\Users\Ko_Li\.openclaw\workspace\windows-class-tools`。

---

## 1. “功能全做”的边界

### 1.1 纳入（以网页现有功能为准）

| 组 | 功能 |
|---|---|
| 入口 | 身份门禁、工作台、全部工具/常用、设置、外观、关于 |
| 学习 | 课表（周/日、下一节、课程详情、个人教务课表登录）、作业（发布/完成/附件/导出）、通知（分类/筛选/已处理/置顶/长期/附件/提醒/管理员编辑隐藏） |
| 班级 | 抽签（STEP1–3、存证、名称映射、剔除补抽、历史/复算、导出/二维码）、分组、名单（班委/团员/全班/管理）、点名（到/假/历史/汇总）、体测（国标评分/历史/导出） |
| 互动 | 投票（列表/详情/投票/发起/管理/可见范围/匿名/配图）、大屏 V5（布局/模块/聚焦/灵动岛/PPT/投票/抽签名单/互联/预设/撤销/锁定）、文件传输（drop） |
| 数据 | 电费（房间/趋势/同期比较/13/16 隐藏 24h）、水量（4/6 人间/月份/抄表/共享表） |
| 演示 | PPT 列表/上传/转换状态/详情/兼容版/PDF/原件/视频单独下载/内置分步与视频播放/Office 打开 |
| 其他 | 地图（2.5D 楼栋/教室/下一节）、教务入口、学信网入口、使用说明、反馈、统计（管理员）、诊断（服务健康/本机检查/AI 结论只读）、数据备份/恢复、提醒设置 |

### 1.2 不纳入（除非另行确认）

- **安卓独有**：今日校园、第二课堂、快递、学信网数据提取、OPPO 推送、沉浸式状态栏/壁纸取色（网页没有，不属于“班级工具站网页版”）。
- **WebView 壳/内嵌学校系统**：教务/学信网用默认浏览器打开（与网页行为一致：网页也只是入口/直跳，不代填密码）。
- **多用户/公用电脑/安装器/自动更新/代码签名**：单机使用，`dotnet publish` 目录即可。
- **新增云端表/RLS/UD v6 顶层键/同步类别**：全部复用现有契约。
- **网页构建链**：网页仍是单文件零依赖；原生客户端可以 .NET/NuGet。

### 1.3 范围调节阀（想缩短工期时按顺序砍）

| 杠杆 | 省 | 代价 |
|---|---|---|
| 地图改成「在浏览器打开」 | −10–12 人日 | 原生内没有 2.5D 地图；课表联动跳浏览器 |
| PPT 不做内置播放器，只下载后用 Office | −8–10 人日 | 失去“任意设备流畅播放”的原生体验；本机有 Office 时可接受 |
| 通知管理员编辑/隐藏先留在网页 | −4–5 人日 | 原生只读+已处理 |
| 大屏只做 v1 固定模块，不做 V5 拖拽/灵动岛/遥控 | −8–10 人日 | 大屏交互降级 |
| 个人教务课表登录留在网页 | −3–4 人日 | 原生只用公共课表 |
| 少数复杂页面用只读 WebView（如地图/通知 HTML） | −15–20 人日 | **违背“纯原生”**，不推荐；仅作最后手段 |

> 全量按 §1.1 做，默认**不用 WebView**；上述杠杆只在时间不够时用。

---

## 2. 技术路线

| 方案 | 形态 | Win11 观感 | Windows 集成 | 工作量（全量） | 风险 | 结论 |
|---|---|---|---|---|---|---|
| **A. WinUI 3 + Windows App SDK** | 原生 Fluent 2/Mica | **最正宗** | 强（Office COM/托盘/通知需少量 Win32 互操作） | 180–210 人日 | 工具链/运行时/打包；本机缺 SDK | **推荐（先 M0 验证）** |
| B. WPF + WPF-UI | 原生 WPF + Fluent 2 主题 | 接近，细节非 100% | 最强（Office/托盘/热键直接） | 170–200 人日 | 观感/动画需自建；不是 WinUI | **M0 失败时的回退** |
| C. Compose Desktop | Kotlin/JVM，Material | 不是 Fluent | 中（Office 需 JNA/helper） | 140–170 人日 | 观感不符 Win11；打包带 JRE | 只在想复用安卓逻辑时考虑 |
| D. WPF 自绘 Fluent | 原生 WPF | 可做但成本高 | 最强 | 190–220 人日 | 控件/动效/无障碍全靠自建 | 不推荐 |
| E. Electron/WebView 壳 | Web 技术 | 可仿 | 中 | 100–130 人日 | 非原生；用户已否决 | 不做 |

### 2.1 为什么是 WinUI 3

- Win11 的 **Fluent 2 / Mica / NavigationView / ContentDialog / InfoBar / TeachingTip / CommandBar / AnimatedIcon / ConnectedAnimation** 都是内置能力；WPF 需要大量仿制。
- 原生窗口、标题栏、Snap 布局、主题、无障碍（UIA）与 Win11 一致。
- `Microsoft.WindowsAppSDK` 自包含 + 未打包（`WindowsPackageType=None`）可生成文件夹 + exe，不需要 MSIX/商店/管理员。
- Office COM、托盘、全局热键、文件选择器都可以在 .NET 里做；只是托盘/热键要少量 Win32 互操作。

### 2.2 WinUI 3 的代价（必须接受）

- 工具链：需要 Windows App SDK + Windows SDK BuildTools；本机当前没有 Windows SDK/VS，M0 先验证 `dotnet` + NuGet 能否构建。
- 托盘：WinUI 3 没有 `NotifyIcon`；用 `H.NotifyIcon.WinUI` 或 Win32 `Shell_NotifyIcon`。
- 通知：未打包应用的 `AppNotificationManager` 需要注册/AUMID；M0 验证。
- 文件选择器：需要 `InitializeWithWindow`；`ApplicationData.Current` 在未打包应用不可用，缓存用 `%LOCALAPPDATA%`。
- 包体：自包含 Windows App SDK 实测 **约 242 MB 文件夹**（WindowsAppSDK 2.6 含 AI/ML 组件；压缩后约 100–140 MB）；单机可接受。若嫌大，可改框架依赖（需装 Windows App Runtime）或裁剪语言资源，后续评估。
- 生态：第三方控件比 WPF 少；复杂表格/图表要自绘或少量 NuGet。

### 2.3 M0 决策门（已部分通过）

**2026-11-16 实测**：`dotnet build` + 运行成功，未安装 Visual Studio/独立 Windows SDK；NuGet 的 WindowsAppSDK 2.6.4 + SDK BuildTools 10.0.28000.2957 足够构建自包含未打包 WinUI 3。窗口标题栏/Mica/NavigationView/InfoBar/中文字体/品牌 Accent/Office COM 均正常。剩余验证：

1. `AppNotificationManager`（未打包注册/AUMID）。
2. 托盘（`H.NotifyIcon.WinUI` 或 Win32）。
3. `FileOpenPicker`/`FileSavePicker` + `InitializeWithWindow`。
4. 通过 → WinUI 3 继续；任一关键项失败 → **WPF + WPF-UI**（Fluent 2 主题、Mica、NavigationView、Snackbar、ContentDialog、SettingsCard），数据/领域层不改。

> 本机 OS 为 Windows build 26300（具备 Win11 级别 Fluent/Mica 能力，但需以实际 API 验证）。

---

## 3. Win11 Fluent 设计系统

### 3.1 基础

| 项 | 规则 |
|---|---|
| 背景 | `MicaBackdrop`（Win11）；Win10/远程桌面退 `DesktopAcrylicBackdrop`/纯色 |
| 内容层 | `CardBackgroundFillColorDefaultBrush` + `CardStrokeColorDefaultBrush`；半透明层叠，不堆纯白 |
| 强调色 | 品牌雾青 `#4E9082` 作为 Accent；深色模式提亮一档保证对比度 |
| 次强调 | 暖沙 `#B98F63` 仅用于标签/图表系列；灰蓝 `#6E8CA8` 用于信息类 |
| 语义色 | 成功/警告/错误用 Fluent `SystemFillColorSuccess/Caution/Critical`，不自定义大红大绿 |
| 字体 | `Segoe UI Variable`（拉丁）+ `Microsoft YaHei UI`（中文）；Fluent 字阶 |
| 字阶 | Caption 12 / Body 14 / BodyStrong 14 semibold / Subtitle 20 / Title 28 / TitleLarge 40 |
| 圆角 | 卡片/对话框 8；输入/按钮 4；胶囊 999；遵循 Fluent，不照搬网页 16 |
| 间距 | 4/8/12/16/24/32；页面边距 32（宽屏 40） |
| 图标 | `SymbolIcon`/`FontIcon`（Segoe Fluent Icons）；20/24；不引外部图标包 |
| 阴影 | 卡片用 1px 描边 + 轻投影；浮层用 `ThemeShadow`；避免网页式重阴影 |
| 深浅 | 浅/深/跟随系统三态；首帧不闪白；Mica 随主题 |
| 密度 | 标准；列表行高 40/48；触摸目标 ≥40（关键按钮 48） |

### 3.2 结构

- **NavigationView**：左侧；`PaneDisplayMode=Left`，展开 240 / 紧凑 48；分组：
  - 工作台
  - 学习：课表 / 作业 / 通知
  - 班级：抽签 / 分组 / 名单·点名 / 体测 / 投票
  - 生活：电费 / 水量
  - 课堂：演示 / 大屏 / 文件
  - 工具：地图 / 教务 / 学信网 / 使用说明 / 反馈
  - 管理：统计 / 诊断（管理员或全员按网页口径）
  - Footer：设置
- **自定义标题栏**：品牌三点 + 应用名；全局搜索（Ctrl+K）；同步状态胶囊；身份头像/姓名；窗口按钮；`ExtendsContentIntoTitleBar` + `SetTitleBar`。
- **页面头**：标题（Title 28）+ 一句副标（可选）+ 主操作（CommandBar/按钮）；滚动时标题栏可吸顶。
- **CommandBar**：每页主操作（如「开始抽签」「发布作业」「上传 PPT」），次要进溢出；带键盘加速器。
- **内容卡片**：`Border` + Fluent 卡片刷；圆角 8；标题 BodyStrong；正文 Body；操作在右上或底部。
- **空态**：图标 + 标题 + 一句动作；不写长说明。
- **加载**：骨架（Shimmer）+ `ProgressRing`；避免整页空白。
- **错误**：`InfoBar`（页内）+ `ContentDialog`（阻断）；文案短，给重试。
- **确认**：破坏性操作用 `ContentDialog`（红色主按钮），支持 Esc 取消。
- **通知**：`AppNotification`（系统 Toast）+ 应用内 `InfoBar`/`TeachingTip`；不重复轰炸。

### 3.3 动效

- 页面切换：`SlideNavigationTransitionInfo`（左右）/ `DrillIn`（详情）；200–300ms。
- 列表：`RepositionThemeTransition` + `ImplicitAnimations`（透明度/位移）；新增/删除 150–200ms。
- 卡片→详情：`ConnectedAnimationService`（共享元素）；失败静默降级。
- 按钮/导航：Fluent 自带 `PointerOver`/`Pressed` 视觉；不额外加弹簧。
- 对话框/浮层：Fluent 默认；`ThemeShadow`。
- 减少动效：读 `UISettings.AnimationsEnabled`，关闭非必要动画。
- 性能：动画只动 `Opacity/Translation/Scale`（Composition），不动布局；60fps。

### 3.4 品牌与 Win11 的平衡

- 不把网页的暖白 `#F7F8F8` 大面积铺在 Mica 上；用 Fluent 中性层 + 品牌 Accent/标签/图表。
- 品牌三点、抽签结果胶囊、导出卡仍保留站点识别度。
- 工作台可用一张低饱和品牌渐变 Hero（雾青→暖沙，透明度低），不抢内容。

---

## 4. 高质量交互规范

### 4.1 导航与状态

- `NavigationView` 选中态与 `Frame` 同步；返回栈保留滚动位置/筛选/表单草稿。
- 页面切换不重建全局服务；取消上一页在途请求（`CancellationToken`）。
- 记住窗口大小/位置/最大化/导航最后页；多显示器恢复。
- 首次使用 `TeachingTip` 指北（2–3 条，可关闭）；不重复弹。
- 全局离线/同步状态：标题栏胶囊（已同步/同步中/离线），失败可点开详情。

### 4.2 键盘与焦点

- `Ctrl+1..9` 切页；`Ctrl+K` 全局搜索；`Ctrl+R` 刷新；`F11` 全屏（大屏/演示）；`Esc` 关弹层/取消；`Enter` 提交；`Tab/Shift+Tab` 完整焦点链。
- 所有图标按钮有 `AutomationProperties.Name` 与 `ToolTip`；`KeyboardAcceleratorTextOverride` 显示快捷键。
- 焦点视觉使用 Fluent 默认双环；不自绘低对比描边。
- 对话框焦点陷阱；关闭后焦点回到触发元素。
- 名单/表格支持方向键、Home/End、PageUp/PageDown、Shift 多选。

### 4.3 搜索与命令

- 标题栏全局搜索：工具、页面、通知标题、名单姓名/座号；分组结果；Enter 打开；Esc 关闭。
- 页面内搜索：通知列表、名单、作业、PPT；`AutoSuggestBox` + 过滤。
- 右键/长按上下文菜单：复制、打开、在文件夹中显示、删除缓存、刷新。
- 命令栏主操作不超过 3 个；其余进溢出，避免拥挤。

### 4.4 反馈与容错

- 所有网络请求有加载态/失败态/重试；写操作乐观更新 + 失败回滚 + `InfoBar`。
- 破坏性操作二次确认；可撤销的操作给 `Snackbar`「撤销」（如隐藏通知、删除投票、清缓存）。
- 删除本机缓存/退出登录明确说明影响；不静默清数据。
- 离线：读缓存 + 顶部 `InfoBar`「离线 · 显示本机缓存」；写操作入队并标注「待同步」。
- 错误不显示原始异常/URL/token；给用户短文案 + 诊断入口。
- 无数据：空态 + 主操作；不显示空白表格。

### 4.5 拖放与多选

- PPT 上传：拖文件到上传区；多文件；进度/取消。
- 大屏模块：拖动/缩放/聚焦；占位/吸附/撤销；与网页 V5 语义一致。
- 工具库：拖动排序/固定到导航（写 `homeTools`）；拖到「常用」区。
- 名单/投票可见范围：多选/全选/反选；键盘 Shift/Ctrl。
- 文件传输：拖放上传、下载到文件夹。

### 4.6 响应式与窗口

- 断点：≥1600 三栏/宽内容；1280–1600 两栏；1024–1280 紧凑；<1024 最小窗口提示（不强行手机布局）。
- `NavigationView` 自动紧凑；卡片网格 2/3/4 列；详情抽屉/分栏随宽度切换。
- 窗口最小 1024×700；默认 1440×900；支持 Snap 布局、最大化、多显示器。
- 大屏是独立 `Window`，全屏到指定显示器；关闭需确认。

### 4.7 无障碍

- UIA 名称/帮助文本；列表项可朗读；图表提供文字摘要/数据表切换。
- 对比度 ≥4.5:1（正文）；高对比主题跟随系统。
- 全键盘可达；触摸目标 ≥40；不依赖颜色单独传达状态（配图标/文字）。
- 减少动效、文本缩放 100–200% 不裁切。

### 4.8 性能即体验

- 首屏只拉必要数据；通知/作业分页/增量；列表虚拟化。
- 图片解码限尺寸；大文件流式下载；不把 2 MB 通知 JSON 全量绑到 UI。
- 页面切换 <150ms；启动 <2s（WinUI 3 自包含首次可能略慢）；内存 200–350 MB。
- 任何 >200ms 的操作有进度/骨架；不冻结 UI 线程。

---

## 5. 架构与数据契约

### 5.1 分层

```
ClassTools.WinUI (App)
├─ Shell：Window/TitleBar/NavigationView/Tray/Notifications/Theme
├─ Views：Page + UserControl + ContentDialog + Flyout
├─ ViewModels：CommunityToolkit.Mvvm
├─ Services：ApiClient/Session(DPAPI)/Sync(UD v6)/Marks/Cache/
│            Downloads/Office/Notifications/Clipboard/Share/Logging
├─ Domain：Draw/Group/Fit/Notices/Homework/Timetable/Power/Water/Vote/Ppt/Stage/Roster
└─ Storage：%LOCALAPPDATA%\ClassTools\（session.bin/cache/downloads/logs/settings.json）
        │ HTTPS 直连
        ├─ CloudBase PostgREST（auth/表/RPC）
        ├─ ECS /drop /pptfiles /att
        └─ OSS（PPT 媒体）
```

- **MVVM**：`CommunityToolkit.Mvvm`（`ObservableProperty`/`RelayCommand`），减少样板；不引重型框架。
- **DI**：`Microsoft.Extensions.DependencyInjection` 或手写组合根；服务单例，ViewModel 瞬时。
- **导航**：`Frame` + `NavigationView`；参数用强类型 `NavigationParameter`；返回栈。
- **配置**：`settings.json`（窗口/主题/下载目录/通知/更新检查关闭）；不放 token。
- **日志**：文件滚动 7 天；脱敏；不记 token/header/body。

### 5.2 请求

| 项 | 值 |
|---|---|
| Base | `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/` |
| 公开 key | `Authorization: Bearer <CBK>` |
| 班级身份 | `X-Class-Token: <token>`（`auth_hdr()` 同时接受 `X-Device-Id`） |
| 内容 | `application/json`；写回行 `Prefer: return=representation` |
| CORS | 不需要；原生无 Origin |
| 超时 | 连接 10s；普通 30s；通知整表 60s |
| 重试 | GET 1 次（~350ms）；写不重试 |
| 401/403 | 401 清会话；403 提示权限不足，不一律清 |

### 5.3 关键接口

| 功能 | 接口 | 备注 |
|---|---|---|
| 登录 | `POST rpc/class_verify {p_sid,p_name}` | 返回 `token/sid/name/role/badge/is_admin`；**marks 用 `sid`** |
| 名单 | `POST rpc/class_members` / `rpc/class_league` | 只显示姓名/座号；不显示学号 |
| UD v6 | `GET userdata?select=*&id=eq.<sid>`；`POST userdata` | 单行 `blob`；14 顶层键；逐 section LWW |
| 勾选 | `GET marks?select=*&seat=eq.<sid>`；`POST marks` | `id` = sid、kind、ref 三段拼接；`kind=hw/nt/ntdone`；列名 `seat` 存学号 |
| 作业 | `GET/POST/PATCH homework` | `archived=false`；完成走 marks |
| 通知 | `GET notices?select=*&order=ts.asc&archived=eq.false`；签名查 `id,ts,hidden,edited_at` | 2 MB；签名变化才整表拉 |
| 课表 | `GET site_assets?id=eq.tt` | 公共快照；个人课表走 UD `tt` |
| 体测 | `GET/POST/PATCH fitrecs` | `fit` 当前输入，`fitrecs` 历史 |
| 电费/水量 | `power`/`power_history`；`water`/`water_room` | 口径照网页 |
| 投票 | `rpc/poll_create/list/detail/submit/manage` | 一人一票；可见范围；响应无学号 |
| 抽签 | `rpc/draw_record_create/...` | 存证/哈希链；测试记录 `draw_test_*` 清理 |
| 演示 | `ppt_decks`；`ppt_upload_chunks` | 512 KiB 分片；manifest |
| 大屏 | `stage_prefs` | 仅本人；布局 JSON |
| 文件 | ECS `/drop/*` | 8 MiB 分片；72h |
| 附件 | ECS `/att/*` / data URL | 签名 URL |

> 具体字段/RPC 参数以 `CLOUDBASE.md` + 各 CONTRACT 为准；本文不复制 schema。

### 5.4 UD v6 / marks

- 14 顶层键：`v, at, homeTools, fit, draw, group, roster, hide, tt, prefs, nick, power, water, homeToolsAt`。
- 逐 section LWW：`remote.at[k] >= local.at[k]` 云端赢；本机改 `at[k]=now`。
- 只写自有 section；`prefs`（网页所有，安卓写 `prefs.toolOrder`）原样保留；不新增键。
- 推送防抖 1200ms；`POST userdata [{id:sid,blob,ts}]` + `Prefer: return=representation,resolution=merge-duplicates`。
- 拉取启动/60s TTL；无基线先拉再推；离线 pending 补发。
- `marks` 按 **`sid`**（列名 `seat`）合并；pending 优先于云端；写失败入队。
- 测试向量：以安卓 `UserdataV6.kt`、网页 `UD.merge`、`_sync_task/CONTRACT.md` 为准；逐 section 对齐，不能自创。

### 5.5 缓存/离线

| 数据 | TTL/策略 |
|---|---|
| 通知整表/签名 | 10 分钟 / 45s 轮询 |
| 作业 | 10 分钟 |
| 名单 | 6 小时 |
| 课表 | 6 小时 |
| 电费/水量 | 2/5 分钟 |
| marks | 2 分钟；回前台/切页强拉 |
| UD | 60s 拉；1200ms 推 |
| 离线 | 读缓存；marks/UD 入 outbox；恢复补发；页内 InfoBar |

存储：JSON + 原子写；图片/附件落盘；不引数据库。

### 5.6 单机形态

- 首次登录：学号+姓名 → token → DPAPI `session.bin`；29 天免登录；401 回登录。
- 不做公用电脑/多用户/profile 切换；DPAPI 绑当前 Windows 用户。
- 关闭窗口到托盘（可设置退出）；单实例；开机自启可选（HKCU Run）。
- 无安装器/自动更新；发布=自包含目录；快捷方式脚本可选。
- 手工使用真实账号是产品用途；自动化测试仍只用测试身份。

---

## 6. 功能矩阵与页面设计

### 6.1 工作量矩阵（全量）

| 模块 | 全量内容 | 人日（估） |
|---|---|---|
| 壳/设计系统 | 窗口/标题栏/NavigationView/主题/Mica/托盘/单实例/通知/日志 | 10–12 |
| 身份/会话 | 登录、DPAPI、29 天、401 | 3 |
| 数据层 | ApiClient、缓存、UD v6、marks、outbox、离线 | 12–14 |
| 工作台/工具库 | 今天、待办、快捷、搜索、固定到导航、homeTools | 5–6 |
| 课表 | 周/日、下一节、详情、个人登录、导出 | 8–10 |
| 作业 | 列表/详情/发布/附件/完成/轮询 | 4–5 |
| 通知 | 解析、分类、已处理、置顶、长期、附件、管理员编辑、提醒 | 12–14 |
| 抽签/分组 | 表单、引擎、存证、历史/复算、名称映射、导出/QR | 13–15 |
| 名单/点名 | 三 tab、座号网格、到/假、历史、汇总、管理 | 7–8 |
| 体测 | 输入、国标评分、历史、导出 | 4–5 |
| 投票 | 列表/详情/投票/发起/管理/可见范围/配图 | 8–10 |
| 电费/水量 | 选择器、tiles、趋势图、同期比较、月份/抄表 | 12–14 |
| 演示 PPT | 上传/分片/状态/详情/下载/视频/内置播放/Office | 13–15 |
| 大屏 + 互联 | V5 布局/拖拽/聚焦/灵动岛/模块/投票/名单/遥控/预设/撤销/锁定 | 18–20 |
| 文件传输 | 上传/下载/删除/进度 | 3–4 |
| 地图 | 2.5D 楼栋/教室/搜索/下一节/全屏 | 10–12 |
| 教务/学信网 | 入口卡、个人课表登录 | 4–5 |
| 使用说明/反馈/统计 | 卡片/表单/管理员列表 | 6–7 |
| 诊断 | 服务健康、本机检查、AI 结论只读 | 4–5 |
| 设置/外观/备份 | 账户/同步/通知/下载/主题/备份/关于 | 4–5 |
| QA/无障碍/性能/文档 | 测试、截图、兼容、发布 | 16–20 |

> 合计约 **180–210 人日**（含 QA）。按 §1.3 杠杆可压到 150–170。

### 6.2 页面设计要点

#### 工作台
- Hero：今天日期/周次、下一节课、当前时间；右侧同步状态。
- 卡片：未完成作业、未处理通知、今日抽签次数、最近演示；点击进详情。
- 快捷操作：抽签 / 点名 / 投票 / 大屏；`homeTools` 可配置（≤4），与网页同步。
- 离线时 Hero 下方 `InfoBar`；数据来自缓存。

#### 工具库（全部工具）
- 搜索/分类过滤；卡片网格 3/4 列；hover 抬升；右键「固定到导航/取消固定」。
- 拖动排序/固定写 `homeTools`；不覆盖网页的 `prefs`。
- 管理员工具：统计按 `is_admin` 显示；诊断按网页口径全员可达；都不绕过服务端。

#### 课表
- 自绘周表控件（5 天 × 12 节）；课程块按周次着色；今日列高亮；点击只显示本节详情。
- 右侧栏：下一节/课程详情；周/日切换；上/下周/本周；学期周次。
- 个人教务课表登录：弹窗输入账号密码（**不落盘**，提交后立即清空；RPC 排队/PGP），轮询状态，写 UD `tt.ttLocal`；失败给可读原因。
- 断网/无快照：空态 + 重试；不白屏。

#### 作业
- 左列表 + 右详情；筛选未完成/全部/已过期；截止倒计时；完成勾选乐观更新。
- 发布（管理员）：主题/内容/截止日期时间/附件；附件选择/压缩/上传；发布后列表刷新。
- 附件打开/另存；离线可读缓存，写操作排队。

#### 通知
- 三栏：分类/筛选、列表、详情；`InfoBadge` 未处理数。
- 签名 45s；变化才整表拉；解析 groups/items；长期/截止/报名窗口标签；附件图片/文件。
- 已处理 → marks；置顶；管理员编辑/隐藏/恢复（`override_json/hidden/edited_at`）。
- 提醒：系统 Toast（`AppNotification`）+ 应用内通知；点击跳到对应通知。
- 解析失败：纯文本兜底 + 「在浏览器打开」；不丢通知。

#### 抽签
- 左参数（范围/个数/重复/排除/名单来源/名称映射）+ 右结果；存证状态/今日次数。
- 算法 draw-v1；结果可复算；剔除/补抽/重置事件；历史/详情/哈希自检。
- 导出：原生 PNG（760 逻辑宽、2x、参数/水印/页脚/编号/QR）；隐私字段为零。
- 深链 `#verify=<id>`：复制链接/二维码；登录后打开。

#### 分组
- 来源/组数或每组人数/打乱；均衡分组；组卡两列；导出 PNG。

#### 名单/点名
- 三 tab：班委/团员/全班；搜索姓名/座号；座号网格 6 列；选中高亮。
- 点名：到/假切换；全部到/全部假；历史；汇总导出；状态写 UD `roster`。
- 管理（班委 tab）：仅管理员；不显示学号。

#### 体测
- 表单：性别/年级/身高/体重/肺活量/50m/坐位体前屈/立定跳远/引体或仰卧/耐力。
- 实时评分/等级/BMI；历史最多 2 条；导出 PNG。
- 口径与网页/安卓一致；用安卓单测向量。

#### 投票
- 列表：进行中/已结束；倒计时；单选/多选/匿名/可见范围标签；已投人数。
- 详情：勾选/改票/结果百分比/实名投票人/结果隐藏提示；管理（0 票编辑/提前结束/延长/删除）。
- 发起向导：标题/说明/选项 2–20/配图（压缩）/单选多选/最多可选/匿名/改票/结果可见性/可见范围（全班/班委/团员/指定成员）/限时或截止。
- 一人一票；服务端 RPC；响应不含学号；原生不缓存投票人隐私。

#### 电费
- 房间选择（楼栋+房间网格）；tiles：剩余/估算/低速/上次充值；趋势 24h/7d/30d。
- 13/16 隐藏 24h；慢频「日更」；自然周期同期比较；点击/拖动游标；空态。
- 自绘图表（Composition/Canvas）；hover/触摸；图例；无数据不伪造。

#### 水量
- 4/6 人间；选择房间；月份；每间记录/共享表；抄表；历史。
- 与网页 `_water_contract` 口径一致；离线可读缓存。

#### 演示 PPT
- 列表：状态/页数/大小/上传者/转换机离线；搜索；上传。
- 上传：拖放/选择；建行→512 KiB 分片→queued；进度/取消；≤64 MiB。
- 详情：兼容版/PDF/原件/视频单独下载；大小/页数/兼容提示；「用 Office 打开」；旧 deck 可「重新处理」（PATCH queued）。
- 下载：ECS 主链/OSS 备用；断点/进度；文件名 `<标题>_兼容版.pptx`；打开文件夹。
- 播放：分步图（每页/每步）+ 视频；章节/倍速/续播/全屏；弱网回退；与网页语义一致。
- Office：PowerPoint COM（禁宏、只读、放映）；WPS/无 Office 用 ShellExecute + F5 提示。

#### 大屏 V5 + 互联
- 独立 `Window`，全屏到指定显示器；12 栏布局；模块：计时/抽签/投票/演示/名单点到/互联/接收。
- 拖动/缩放/聚焦/灵动岛/预设/撤销/锁定；布局写 `stage_prefs`（仅本人）。
- PPT 面板：下载/打开文件；投票完整发起；抽签名单快捷（全班/班委/团员/清空）。
- 互联：drop 房间/同账号、presence、13 类遥控、文件/文字接收；与网页同协议。
- 退出确认；Esc 不直接退出大屏；键盘可用；投影对比度。

#### 文件传输
- 上传区（拖放/选择）+ 文件列表 + 进度；8 MiB 分片；72h；下载/删除/清空。
- 同账号设备互见；过期标注；错误 507 提示空间不足。

#### 地图
- 原生 2.5D：楼栋体块/道路/水面/点位；楼栋高亮；搜索楼名/教室号；下一节联动。
- 缩放/平移；全屏；图例；免责声明；不引在线地图/Three.js。
- 教室号解析（前 2 位楼栋/第 3 位楼层/后 2 位教室）；非教学楼值白名单。

#### 教务/学信网
- 与网页一致：入口卡 + 默认浏览器打开；不代填密码、不内嵌。
- 教务个人课表登录在课表页；学信网 10 个官方入口。

#### 使用说明/反馈/统计/诊断
- 使用说明：分类卡片/搜索/详情；内容从本地资源或网页同源 JSON；不写长段落。
- 反馈：内容/联系方式/提交；管理员列表/状态。
- 统计：管理员访问统计（`visits`）表格/图表；只读。
- 诊断：服务健康 18 行/5 组、本机检查（API/缓存/Office/网络/时钟）、AI 结论只读；不上传新字段。

#### 设置
- 账户：身份/退出/清除会话。
- 同步：状态/手动同步/清除本机缓存。
- 通知：Toast 开关/提醒设置/权限状态。
- 下载：目录/完成后打开/打开文件夹。
- 外观：浅/深/系统；Mica；减少动效跟随系统。
- 关于：版本/契约/日志目录/第三方 notices。
- 数据：导出/导入本机设置与缓存（不含 token）；清除本机数据。

---

## 7. 工程、构建、测试

### 7.1 工程结构

```
ClassTools.WinUI.sln
├─ src/ClassTools.App/            # WinUI 3：App/Window/Pages/Controls/Themes
├─ src/ClassTools.Core/           # 纯领域：Draw/Group/Fit/Notices/.../UD merge
├─ src/ClassTools.Data/           # ApiClient/Session/Cache/Marks/Outbox
├─ tests/ClassTools.Tests/        # xUnit：领域向量/合并/解析/导出布局
├─ tests/ApiSmoke/                # 测试身份真实云端只读冒烟
├─ docs/                          # TEST_PLAN/CONTRACTS/BUILD
└─ tools/                         # build.ps1/publish.ps1/make-shortcut.ps1
```

### 7.2 依赖

- `Microsoft.WindowsAppSDK`（WinUI 3/Windows App SDK）
- `CommunityToolkit.Mvvm`（MVVM）
- `CommunityToolkit.WinUI.Controls.SettingsControls`（SettingsCard/Expander；可选）
- `System.Security.Cryptography.ProtectedData`（DPAPI）
- `QRCoder`（抽签二维码；可选）
- `H.NotifyIcon.WinUI`（托盘；或 Win32 自绘）
- 测试：xUnit；可选 FlaUI/Appium（WinUI 3 UIA）
- 不引 WebView2、Electron、第三方 UI 大框架、ORM、重型图表库（图表自绘）。

### 7.3 构建

```
dotnet publish src/ClassTools.App -c Release -r win-x64 --self-contained true `
  -p:WindowsPackageType=None -p:WindowsAppSDKSelfContained=true
```

- 产物：文件夹 + `ClassTools.exe`；无 MSIX/安装器；`make-shortcut.ps1` 可选。
- 首次启动注册 AppNotification（未打包应用需要）；失败退托盘气泡。
- 版本 `1.0.0`；关于页显示；网页 `APP_VER` 仍 2.0.0。

### 7.4 测试

| 层 | 方式 | 覆盖 |
|---|---|---|
| 单元 | xUnit | UD v6 逐 section、marks、draw-v1 向量、分组、体测、通知解析、电费口径、文件名、导出布局、教室号解析 |
| API | 真实云端 + 测试身份 | 登录/名单/UD/marks/通知/课表/PPT/抽签测试记录（清理） |
| ViewModel | xUnit | 加载/离线/401/403/命令/状态 |
| UI | 手工截图 + 可选 FlaUI | 登录/导航/课表/通知/抽签/PPT/大屏/1366/1920；键盘/焦点 |
| 手工 | 你的电脑 | Office/托盘/Toast/断网/多显示器/主题/高对比 |
| 跨端 | 测试身份 | 原生写 UD/marks → 网页读；网页写 → 原生读 |
| 无障碍 | Accessibility Insights | UIA 名称/对比度/焦点/键盘 |

- 自动化只用测试身份 `3260799999/测试账号`；不登录真实同学/管理员；测试记录清理。
- 你本人手工使用真实账号是产品用途，不是自动化测试。

---

## 8. 里程碑与工作量

| 阶段 | 内容 | 人日 |
|---|---|---|
| M0 工具链/设计验证 | WinUI 3 最小工程、Mica/NavigationView/Dialog/Toast/托盘/Office/文件选择器；决定 WinUI 3 或 WPF-UI | 4–6 |
| M1 壳与数据层 | 设计系统/导航/标题栏/托盘/设置；ApiClient/DPAPI/缓存/UD v6/marks/离线 | 20–24 |
| M2 学习页 | 工作台/工具库/课表/作业/通知（解析/管理/提醒） | 30–34 |
| M3 班级工具 | 抽签/分组/存证/导出/QR；名单/点名/体测 | 30–34 |
| M4 互动与生活 | 投票；电费/水量图表；PPT 上传/下载/播放/Office | 32–36 |
| M5 大屏与长尾 | 大屏 V5/互联；文件；地图；教务/学信网；说明/反馈/统计/诊断；设置/备份 | 40–46 |
| M6 质量收尾 | 无障碍/性能/兼容/测试/文档/发布 | 24–30 |

> 合计约 **180–210 人日**；全职约 5–6 个月，每天 5 小时约 8–10 个月。可由多个 agent 并行（先定 UI 组件/数据契约），但集成与验收仍要时间。

---

## 9. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| WinUI 3 工具链不可用 | 无法开工 | M0 先验证；失败退 WPF-UI（数据/领域不变） |
| 范围 180–210 人日 | 周期长/疲劳 | 严格按 §1.3 杠杆；先 M1/M2 可用，再逐步补齐 |
| 地图/PPT 播放器/大屏 V5 | 复杂度高 | 地图可先浏览器；播放器可先 Office；大屏 v1→v2 |
| 通知解析/管理员编辑 | 显示不全 | 未知类型纯文本兜底；管理员编辑可先网页 |
| 托盘/Toast/Office COM | WinUI 3 互操作坑 | M0 各做最小验证；H.NotifyIcon/Win32；AppNotification 注册 |
| 业务规则漂移 | 与网页/安卓不一致 | 固定测试向量 + 跨端测试 + 以现有三端为准 |
| UI 质量/无障碍 | 不达 Win11 预期 | Fluent 控件优先；不自绘；Accessibility Insights 验收 |
| 性能 | 列表/图表卡顿 | 虚拟化/编译绑定/Composition 动画/分页 |
| CloudBase 到期 | 全端停 | 2026-12-10 前续费/迁移（与客户端无关） |
| 单人维护 | 新功能滞后 | 网页仍是全量入口；原生按你用的优先级跟进 |

**回滚**：原生是新增客户端，不影响网页/云端；删目录即可。数据以云端为准。

---

## 10. 待确认（已决）

> **2026-11-16 已确认**：Q1/Q2/Q6/Q7 全部按“全做”执行（地图原生、PPT 播放器原生、大屏 V5、通知管理员原生）；Q3 安卓独有不做；Q4 个人课表登录做；Q5 WinUI 3（M0 通过）；Q8 本机 build 26300；Q10 单机不做安装器/自动更新；Q9 接受多个月周期。下表保留为决策记录。

| # | 问题 | 影响 | 决定 |
|---|---|---|---|
| Q1 | 地图要**原生 2.5D**，还是「在浏览器打开」？ | ±10–12 人日 | **原生 2.5D** |
| Q2 | PPT 要**内置分步/视频播放器**，还是只下载后用 Office？ | ±8–10 人日 | **内置播放器**（Office 打开同时保留） |
| Q3 | 安卓独有（今日校园/第二课堂/快递/学信网提取）要不要？ | +15–25 人日，且涉及学校账号 | **不做**；网页版没有 |
| Q4 | 个人教务课表登录要不要原生？ | +3–4 人日 | **做**（网页有） |
| Q5 | WinUI 3 还是 WPF-UI？ | 观感/工具链 | **WinUI 3**（M0 已通过） |
| Q6 | 大屏要 V5 全交互（拖拽/灵动岛/遥控），还是 v1 固定模块？ | ±8–10 人日 | **V5 全交互** |
| Q7 | 通知管理员编辑/隐藏要原生吗？ | +4–5 人日 | **原生** |
| Q8 | 你的 Windows 是 Win11 哪个版本？ | Mica/Fluent API | **build 26300**，M0 已验证 |
| Q9 | 是否接受 5–6 个月（全职）/8–10 个月（兼职）？ | 是否调整范围 | **接受**；按里程碑推进 |
| Q10 | 是否要安装器/自动更新？ | +4–6 人日 | **不做**；目录 + 快捷方式 |

---

## 附录 A：Win11 控件映射

| 需求 | WinUI 3 |
|---|---|
| 左侧导航 | `NavigationView` |
| 标题栏/Mica | `ExtendsContentIntoTitleBar` + `AppWindowTitleBar` + `MicaBackdrop` |
| 命令栏 | `CommandBar` + `AppBarButton` + `KeyboardAccelerator` |
| 搜索 | `AutoSuggestBox` |
| 对话框 | `ContentDialog` |
| 页内提示 | `InfoBar` |
| 引导 | `TeachingTip` |
| 设置 | `SettingsCard`/`SettingsExpander`（CommunityToolkit） |
| 列表 | `ListView`/`ItemsRepeater` |
| 下拉刷新 | `RefreshContainer` |
| 标签页 | `TabView`（多详情时） |
| 进度 | `ProgressRing`/`ProgressBar` |
| 通知 | `AppNotificationManager` |
| 托盘 | `H.NotifyIcon.WinUI`/Win32 |
| 图表 | 自绘 `Canvas`/Composition |
| 导出 | `RenderTargetBitmap` + `BitmapEncoder` |
| 二维码 | `QRCoder`（可选） |

## 附录 B：数据契约来源

- 身份/UD/marks/通知/课表：`tools/index.html` + `CLOUDBASE.md`
- 抽签：`draw/CONTRACT.md`、`HANDOFF.md §38`
- 投票：`vote/CONTRACT.md`
- PPT：`ppt/CONTRACT.md`
- 大屏：`tools/tests/_stage_sync_contract.md`
- 文件：`drop/CONTRACT.md`
- 水量：`tools/tests/_water_contract.md`
- 导出：`tools/tests/export_card_v2_spec.md`
- 安卓参考：`android-class-tools/docs/ARCHITECTURE.md`、`features/*`、`data/sync`

## 附录 C：本机环境（设计时实测）

- .NET SDK 10.0.115（另有 8.0.428）；Windows build 26300（Win11 级别）；Office 16.0.20527。
- **未安装** Visual Studio/独立 Windows SDK；WinUI 3 已用 NuGet `Microsoft.WindowsAppSDK 2.6.4` + `Microsoft.Windows.SDK.BuildTools 10.0.28000.2957` 构建并启动成功；M1 骨架已落地。
- 设计假设：x64、Win11 22H2+；若 Win10，Mica 退 Acrylic/纯色，其余可用。

## 附录 D：证据

| 事实 | 证据 |
|---|---|
| 登录/29 天/token | `tools/index.html:12950-12997`、`5730-5734` |
| UD v6 推送 | `tools/index.html:5683-5709`、`5272-5286` |
| marks 结构（列名 seat 存学号） | `tools/index.html:5196-5219`、`5230-5263`、`12894` |
| 通知签名/轮询 | `tools/index.html:4335-4346`、`19809` |
| 课表快照 | `tools/index.html:10452-10484` |
| 抽签存证 | `HANDOFF.md §38`、`draw/CONTRACT.md` |
| 投票 RPC | `vote/CONTRACT.md` |
| PPT 下载/文件名 | `tools/index.html:13562-13643`、`ppt/CONTRACT.md` |
| 大屏仅管理员 | `tools/index.html:18790` |
| 安卓参考 | `android-class-tools/docs/ARCHITECTURE.md` |
| 云端风险 | `AGENTS.md` §13（2026-12-10 到期） |
