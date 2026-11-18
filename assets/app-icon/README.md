# 班级工具站 · 图标库

一套按同一矢量规格生成的全平台、全尺寸图标，供网页、小程序、Android、HarmonyOS、Windows 以及文档 / PPT / 第三方软件直接取用。

图形沿用线上既有标记：**暖白圆角方块 + 三圆点**。与网页 `tools/index.html` 的内联 favicon、Android `ic_launcher_foreground.xml`、小程序 `images/app-icon-1024.png` 的几何和颜色一致。

## 设计规格

| 项 | 值 |
|---|---|
| 视口 | `0 0 64 64` |
| 圆角 | `14 / 64 ≈ 21.9%` |
| 底色 | `#F7F8F8` 暖白 |
| 主圆点 | 圆心 `(32,32)`、半径 `9`、`#4E9082` 雾青 |
| 左上圆点 | 圆心 `(15,15)`、半径 `5`、`#6E8CA8` 灰蓝 |
| 右下圆点 | 圆心 `(49,49)`、半径 `5`、`#B98F63` 暖沙 |

> 改设计时请同时改本目录 `build_icons.py` 顶部常量与五端图标，不要只改某一个尺寸。

## 目录

```text
assets/app-icon/
├─ source/          4 个 SVG 源文件（圆角 / 方形 / 透明圆点 / 单色白）
├─ png/             通用 PNG，16–1024，含方形、maskable、透明、单色
├─ web/             favicon.ico / favicon.svg / apple-touch-icon / PWA 192·512·maskable
├─ android/         mipmap-* 传统图标、圆形图标、Play 商店 512、自适应前景/单色层
├─ harmony/         分层图标 background / foreground / 合成 app_icon + layered_image.json
├─ windows/         app-icon.ico（16–256）与 32/48/256 PNG
├─ preview.html     双击打开的可视检查页（无外部请求）
├─ preview.png      一张总览检查图
├─ manifest.json    文件清单：尺寸、用途、sha256
└─ build_icons.py   重新生成全部文件（Pillow，仅本地使用）
```

## 文件与尺寸

### 通用 PNG（`png/`）

| 文件 | 尺寸 | 说明 |
|---|---|---|
| `app-icon-{16,20,24,32,40,48,64,72,96,120,128,144,152,167,180,192,256,384,512,1024}.png` | 对应像素 | 圆角版，四角透明；文档、PPT、第三方软件、应用内 logo |
| `app-icon-square-{256,512,1024}.png` | 对应像素 | 满幅方形、不透明；系统遮罩 / 商店 / 头像上传 |
| `app-icon-maskable-512.png` | 512 | PWA maskable，内容缩至 40% 安全圆内 |
| `app-icon-glyph-1024.png` | 1024 | 透明底三圆点，叠加 / 水印 / 深色底 |
| `app-icon-mono-1024.png` | 1024 | 单色白，主题 / 单色图标 |

### 网页（`web/`）

| 文件 | 尺寸 | 说明 |
|---|---|---|
| `favicon.ico` | 16/32/48/64 | 浏览器标签页，4 帧（PNG 帧，体积小） |
| `favicon.svg` | 矢量 | 现代浏览器优先使用 |
| `favicon-{16,32,48}.png` | 对应像素 | 需要 PNG favicon 时 |
| `apple-touch-icon.png`、`apple-touch-icon-{120,152,167,180}.png` | 180 等 | iOS / iPadOS 主屏，方形不透明 |
| `icon-192.png`、`icon-512.png` | 192 / 512 | PWA `any` |
| `icon-maskable-512.png` | 512 | PWA `maskable` |

### Android（`android/`）

| 文件 | 尺寸 | 说明 |
|---|---|---|
| `mipmap-mdpi/ic_launcher.png` | 48 | 传统启动图标（minSdk 26 项目通常只需自适应 XML） |
| `mipmap-hdpi/ic_launcher.png` | 72 | 同上 |
| `mipmap-xhdpi/ic_launcher.png` | 96 | 同上 |
| `mipmap-xxhdpi/ic_launcher.png` | 144 | 同上 |
| `mipmap-xxxhdpi/ic_launcher.png` | 192 | 同上 |
| `mipmap-*/ic_launcher_round.png` | 48–192 | 圆形启动图标 |
| `ic_launcher-playstore-512.png` | 512 | Google Play 商店，不透明 |
| `ic_launcher_foreground-432.png` | 432 | 自适应前景（108dp × 4，内容在 72dp 安全区） |
| `ic_launcher_monochrome-432.png` | 432 | Android 13+ 单色层 |

### HarmonyOS（`harmony/`）

| 文件 | 尺寸 | 说明 |
|---|---|---|
| `background-1024.png` | 1024 | 分层图标背景（暖白） |
| `foreground-1024.png` | 1024 | 分层图标前景（透明，内容居中、宽约 50%） |
| `app_icon-1024.png` | 1024 | 背景 + 前景合成，可直接作为应用图标 |
| `layered_image.json` | — | `background` / `foreground` 引用配置 |

### Windows（`windows/`）

| 文件 | 尺寸 | 说明 |
|---|---|---|
| `app-icon.ico` | 16/20/24/32/40/48/64/128/256 | 可执行文件 / 窗口 / 任务栏，9 帧 32bpp |
| `app-icon-{32,48,256}.png` | 对应像素 | 需要 PNG 时（安装器、快捷方式、文档） |

## 各端怎么用

### 网页

```html
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
```

PWA manifest 片段：

```json
{
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

> 当前单文件站点用的是 `index.html` 内联 SVG favicon；要换成这些文件，需把 `web/` 下的文件放到站点根目录并改对应的 `<link>`。`deploy/sync_tools.py` 目前只上传 `index.html`、`tools/assets/` 平铺文件与 `tt.json`，**本目录不在上传列表里**。

### 小程序

- 微信公众平台「小程序头像」上传 144×144 PNG：`png/app-icon-144.png`。
- 页面内 logo 用 256 或 512：`png/app-icon-256.png`。
- 现有 `mp-class-tools/images/app-icon-1024.png` 与本库 `png/app-icon-square-1024.png` 同规格（满幅方形），可直接互换。

### Android

- minSdk 26 使用 `mipmap-anydpi-v26/ic_launcher.xml` 自适应图标；现有 `ic_launcher_foreground.xml` 已与本库几何一致，无需改。
- 需要位图启动图标时，把 `android/mipmap-*` 复制进 `app/src/main/res/`。
- 上架 Google Play 用 `android/ic_launcher-playstore-512.png`。

### HarmonyOS

把 `harmony/background-1024.png`、`foreground-1024.png`、`app_icon-1024.png` 复制到 `AppScope/resources/base/media/`，`layered_image.json` 放同目录。

> 注意：当前 `harmony-class-tools` 仓库里的 `foreground.png` 是**横排三圆点 + 纯白底**，与本库（网页/小程序/安卓同款斜排三圆点 + 暖白底）不一致。替换前请确认是否统一。

### Windows（WinUI 3 / .NET）

```xml
<ApplicationIcon>assets\app-icon.ico</ApplicationIcon>
```

资源管理器、任务栏、开始菜单都取这个 ico；需要 PNG 时用 `windows/app-icon-*.png`。以后若做 MSIX 打包，再按 `Assets/` 的 44 / 150 / 310 规格补充，避免现在绑定未定版式。

### 文档 / PPT / 第三方软件

- 直接插入 `png/app-icon-512.png` 或 `png/app-icon-1024.png`。
- 叠在深色底/照片上时用 `png/app-icon-glyph-1024.png`（透明底）。
- 需要单色白时用 `png/app-icon-mono-1024.png`。

## 重新生成

```bat
cd /d C:\Users\Ko_Li\.openclaw\workspace\web\assets\app-icon
python build_icons.py
```

- 依赖 Python + Pillow，**只在生成时使用**；站点和五端运行时都不依赖它，不引入 npm / 前端构建链。
- 重新生成会重写 `manifest.json` 的 `generated` 时间；文件 sha256 可用于核对。
- 生成后打开 `preview.html` 目视检查（双击即可，页面无外部请求）。

## 校验

`manifest.json` 列出了每个文件的尺寸/用途/sha256。核对示例：

```bat
python -c "import json,hashlib,pathlib; d=json.load(open('manifest.json',encoding='utf-8')); bad=[f['path'] for f in d['files'] if hashlib.sha256(pathlib.Path(f['path']).read_bytes()).hexdigest()!=f['sha256']]; print('OK' if not bad else bad)"
```

已核对：

- 全部 PNG 文件名与像素尺寸一致；圆角版四角透明、方形版不透明。
- `web/favicon.ico` 含 4 帧（16/32/48/64，PNG 帧）；`windows/app-icon.ico` 含 9 帧（16–256，32bpp），透明通道正常。
- `preview.html` 只引用本目录相对路径，无外部请求。

## 现状说明

线上站点根目录的 `/favicon.ico`、`/apple-touch-icon.png` 仍是 2026-10-11 上传的旧「F」图标（本地源码树里没有对应文件）；现代浏览器实际使用的是 `index.html` 里的内联 SVG 三圆点。本目录提供的是与内联 SVG 一致的新一套文件，**尚未替换线上旧文件**，需要时再按网页部署流程上线。
