# 班级工具站 Windows 桌面版 · 设计方案

> 版本：v0.1（设计稿） · 日期：2026-11-16 · 状态：**已被取代，仅存档**
> **2026-11-16 18:0x 变更**：用户明确「目前只在我的电脑上使用，要原生应用」→ 本「WebView2 壳 + 本机通道」方案不再采用；新方案见 [Windows 原生版设计方案](WINDOWS_NATIVE_DESIGN_20261116.md)。本文保留作对比与历史记录。
> 目标平台：Windows 10 1809+ / Windows 11（x64）；教室大屏与个人电脑
> 关联契约：`AGENTS.md` §0/§1/§4b、`HANDOFF.md` §5、`deploy/LOCAL_CHANNEL.md`、`deploy/local_channel.py`、`ppt/CONTRACT.md`、`drop/CONTRACT.md`
> 本文只做设计，不改网页、不改云端表/RLS/UD v6、不部署。

---

## 0. 结论（先看这里）

**推荐方案：WebView2 桌面壳 + 本机通道（把现有 `deploy/local_channel.py` 产品化）。**

- **不重写第四端**：Windows 壳只做「宿主 + 本机代理 + 系统集成」，业务仍是同一个 `tools/index.html`。
- **不改网页、不改云端**：壳在本机 `127.0.0.1` 起一个静态资源服务 + API 代理，并在返回 `index.html` 时做 5 条固定字符串重写；班级数据由本机代理转发到 CloudBase，附带白名单 `Origin`。
- **不依赖域名**：登录/数据走 `https://…api.tcloudbasegateway.com`（TLS），备案暂停期也能用；PPT/文件传输暂走 ECS IP，域名恢复后自动可切 HTTPS。
- **离线优先**：网页资源包（约 1.7 MB）随壳安装，断网也能打开身份页/已缓存数据；登录与未缓存数据仍需网络。
- **系统集成**：全屏课堂模式、投影屏、常亮、托盘、下载落盘、PowerPoint/WPS 打开、单实例、开机自启、签名更新。

**关键验证已做**：2026-11-16 实跑 `python deploy/local_channel_selftest.py` → **RESULT: PASS**（官方测试身份 `3260799999/测试账号`；9 个 `/__cb` 请求；身份门禁 → 登录 → 全部页 → 演示模块；0 console/network 错误）。说明「本机通道 + 当前 1.32 MB 页面」这条路是通的，不是纸面推演。

**明确不做**：原生 WinUI/WPF 重写全部业务、安卓独有的今日校园/教务 WebVPN/第二课堂/学信网提取、后台推送服务、管理员门禁绕过、新增云端表或 UD v6 顶层键。

**预计工作量**：20–28 人日（4–6 周，兼职）；原生重写约 60–100 人日，且会多出第三套业务实现，不建议。

---

## 1. 需求理解（我理解的 7 件事）

| # | 场景 | 要解决的问题 | 本方案的回应 |
|---|---|---|---|
| 1 | **教室电脑/投影** | 浏览器地址栏、误触、自动休眠、投影切屏、PPT 打不开/媒体不可用、老电脑卡 | 无边框全屏 + 指定投影屏 + 常亮 + 下载到本地 + PowerPoint/WPS 打开 + 单实例防重复 |
| 2 | **个人电脑** | 每次开浏览器找网址、通知看不到、下载散落、版本旧 | 桌面图标/开机自启 + 托盘 + 系统通知（尽力）+ 统一下载目录 + 自动更新 |
| 3 | **断网/校园网不稳** | 网页打不开、缓存丢、抽签/点名不能用 | 本机资源包 + 固定 origin 保留 localStorage/IndexedDB；断网仍可开身份页与已缓存工具 |
| 4 | **身份门禁** | 不能绕开 RLS，不能存班级公用账号 | 仍用学号+姓名 → `class_verify`；壳不接触密码；管理员仍是云端 role |
| 5 | **隐私/公用电脑** | 教室电脑多人用，残留 token/名单/通知 | 「公用电脑模式」：独立 profile，退出即删；个人模式才记住 29 天 |
| 6 | **分发/更新** | 70 人班，不能人人装开发环境；无管理员权限 | 每用户安装（无需管理员）+ 便携 ZIP；壳与网页包分开更新，RSA 签名清单 |
| 7 | **不添乱** | 网页是唯一真源，三端已很多 | 不改 `index.html`、不改云端；所有业务语义仍由网页决定；壳只做标准 Web 平台事件 |

> 一句话：**不是「再写一个班级工具站」，而是「给现有单文件站点做一个能进教室、能离线、能管下载和 Office 的 Windows 宿主」。**

---

## 2. 现状与硬约束

### 2.1 现有四端

| 端 | 形态 | 版本/规模 | 与 Windows 版的关系 |
|---|---|---|---|
| 网页 | `tools/index.html` 单文件、零构建、零依赖 | **1,322,990 B；APP_VER 2.0.0** | Windows 版直接复用，唯一业务真源 |
| 小程序 | 微信原生 | 源码待用户上传发布 | 不相关；共享 UD v6/契约 |
| 安卓 | Kotlin/Compose 真原生 | 工作区 4.57.x；单测 1,534/0；APK 3.27 MiB | 功能对照；**不把安卓的学校系统 WebView 能力带进 v1** |
| 云端 | CloudBase PG + PostgREST + RLS；ECS（Caddy + `/drop` `/pptfiles` `/att` `/v1/rdb/rest`） | 单班、单环境 | 不改；Windows 只做客户端 |

### 2.2 与 Windows 版直接相关的既有能力

| 能力 | 现状（证据） | Windows 版怎么用 |
|---|---|---|
| 身份 | `#idgate`；`classVerify`；token 存 `zq_class_identity`，29 天免登录（`index.html:12994`） | 原样；壳不另做登录 |
| 数据 | CloudBase PostgREST；`X-Device-Id`；`var CB` 字面量（`:4322`） | 本机代理转发，附带固定 `Origin` |
| 同源反代 | 站点在 `tool.furina.fun`/`tool.furina.fun` 时 `CB` 改同源 `/v1/rdb/rest/`（`:4327-4328`） | 本机 origin 不是这两个，不触发；由壳重写为 `/__cb/` |
| 同步 | UD v6（14 顶层键、逐 section LWW）+ `marks` | **完全不变**；壳不新增同步类别 |
| PPT | 下载详情的 `<a download="标题_兼容版.pptx">`（`:13642`）；ECS 缓存基址 `https://tool.furina.fun/pptfiles`（`:13562`）；大屏「打开文件」是 `target=_blank`（`:17481`，**不是** `ms-powerpoint:`） | 重写为同源 `/__ecs/pptfiles`；下载属性保留正确文件名；壳拦截并调 Office |
| 文件传输/互联 | 同账号临时云空间；`https://tool.furina.fun/drop`（`:18203/19400`）；8 MiB 分片 | 重写为 `/__ecs/drop`，走本机代理（顺带消除 CORS） |
| 大屏 | 仅管理员可开（`:18790`，页脚「仅管理员 · 团日活动」）；V5 布局/投票/抽签/PPT/互联 | 原样；壳只做全屏/投影/常亮，**不提权** |
| 通知 | 页面打开时 45s 轻量签名轮询（`:19809`），`new Notification`（`:19757`） | 托盘保活 + WebView2 通知（M0 验证）；不另建推送 |
| 诊断 | `#s-diag` 全员可见；`client_diag` 白名单 | 壳另做本机诊断日志；不新增上报字段 |
| 本地通道 | `local_channel.py` 在内存把 CB 改 `/__cb/`，服务端带 `Origin: https://tool.furina.fun` 转发；自检 PASS | **本方案的直接原型**，用 C# 重写为产品能力 |

### 2.3 红线（逐条对照）

| 红线 | 本方案是否触碰 | 说明 |
|---|---|---|
| 密钥零泄漏 | 否 | 壳不读 `deploy/creds.env`/`tools/cert/`；不记录 token；更新私钥只在发布机 |
| 不引入网页构建链 | 否 | 网页仍是单文件；壳的 .NET 构建是**客户端**构建，类似安卓 Gradle，不参与网页产物 |
| 不碰 `me.furina.fun` | 否 | 只访问本站云端/ECS |
| 身份门禁/RLS | 否 | 壳不提供绕过；所有数据仍带班级 token |
| 隐私 | 是（需设计） | 公用电脑模式、日志脱敏、下载目录、导出仍由网页控制 |
| 双远端同步 | 适用 | 若新增文档/脚本，仍走 `sync-repos.cmd` |
| 测试账号唯一化 | 是 | 壳 E2E 只用官方测试身份/9999 段/纯 mock；**不登录真实同学/管理员** |

### 2.4 外部风险（比技术选型更优先）

| 风险 | 事实 | 对 Windows 版的影响 | 处理 |
|---|---|---|---|
| **CloudBase 2026-12-10 到期** | `AGENTS.md` §13 | 到期未续费/迁移 → 所有端登录与数据全停，Windows 版也救不了 | **发布前置条件**：先续费或迁移；本文不替代该决策 |
| **`tool.furina.fun` DNS 暂停（备案期）** | `AGENTS.md` §0-8 | 不能依赖域名；ECS IP 只有 HTTP | 本机通道登录走 HTTPS 网关；PPT/drop 走 ECS HTTP；域名恢复后可切 HTTPS |
| **教室电脑可能是 Win7** | 未知 | .NET 10 + 现代 WebView2 不支持 Win7 | **M0 必须先确认**；若只有 Win7，建议用自带笔记本/升级，不做 Win7 版（见 §13-Q1） |

---

## 3. 方案对比与选择

### 3.1 五种形态

| 方案 | 形态 | 复用网页 | 离线 | 系统集成 | 工作量 | 主要风险 | 结论 |
|---|---|---|---|---|---|---|---|
| **A. WebView2 壳 + 本机通道** | WPF 宿主 + 127.0.0.1 静态/反代 | **100%** | 好（资源包） | 强（全屏/Office/下载/托盘/更新） | 20–28 人日 | WebView2 运行时、字符串重写漂移 | **推荐** |
| B. WebView2 壳 + 虚拟主机 + 原生请求代理 | 本地 HTML 映射 `tool.furina.fun` | 100% | 好 | 强 | 30–40 人日 | 同源路径多（CB/tt/ppt/drop/att/map 全要代理），实现复杂 | 备选，不如 A |
| C. Electron / Tauri | 打包 Chromium/WebView2 | 100% | 好 | 中 | 25–35 人日 | 体积/内存（Electron）；Rust+COM 难（Tauri） | 不推荐 |
| D. 原生 WinUI/WPF 重写 | 重写 20+ 工具 | 0% | 中 | 最强 | 60–100 人日 | 三套业务实现、测试翻倍、长期维护 | 不推荐 |
| E. Edge `--app` / PWA 快捷方式 | 0 代码 | 100% | 差 | 几乎没有 | 0 | 无托盘/无下载管理/无更新/无离线包 | 只做临时体验 |

### 3.2 为什么推荐 A（而不是 B）

B 的「虚拟主机」看似更优雅：页面 origin 仍是 `https://tool.furina.fun`，CORS 直接过。但**代码审计**发现页面在该 origin 下会触发同源假设（尚未做虚拟主机实测，结论来自源码路径）：

1. `CB` 自动改 `/v1/rdb/rest/` → 虚拟主机没有该反代 → 登录/全部 API 404；
2. `tt.json`、`/pptfiles`、`/drop`、`/att` 也按同源解析 → 404；
3. 要补齐就得在 WebView2 里做「全路径原生反代」，请求体/响应流/206/上传进度都要自己实现，复杂度远高于 A；
4. 固定虚拟主机名和 userDataFolder 一旦改，身份/IDB 全丢。

A 的本机 origin `http://127.0.0.1:47821` 不触发这些同源分支；只需 5 条重写 + 3 条代理路由，已在 Python 原型上跑通。**A 的复杂度更低、失败面更小、可验证性更好。**

### 3.3 为什么不是原生重写

- 网页 20,412 行、1.32 MB，覆盖 20+ 工具、大屏、PPT、投票、抽签存证、通知模板；重写等于把安卓 66 轮/1,534 个单测的工程再来一遍，且三端从此三套业务逻辑。
- 桌面端真正的缺口是**系统集成**（全屏/投影/Office/下载/更新/托盘），不是页面本身；这些用壳补最划算。
- 原生重写不会让页面更快：老电脑的瓶颈是 Chromium 渲染与网络，WebView2 与 Edge 同核；壳可以把资源放本地，反而更快。

### 3.4 0 代码临时方案（只用于对比/体验）

`msedge.exe --app=https://tool.furina.fun/ --start-fullscreen` 可以立刻得到一个无地址栏窗口，适合课前临时用；但没有离线包、托盘、下载管理、Office 联动、更新、公用电脑清理，**不作为交付形态**。

---

## 4. 总体架构

### 4.1 架构图

```
┌───────────────────────────── Windows 桌面（每用户） ─────────────────────────────┐
│  ClassTools.exe (WPF / .NET 10)                                                 │
│  ├─ 窗口/托盘/单实例/全屏/投影/常亮/快捷键/深链                                  │
│  ├─ 下载器（Range/进度/断点/打开 Office）                                        │
│  ├─ 更新器（壳 + 网页资源包，RSA 验签，回滚）                                    │
│  ├─ 诊断日志（脱敏、滚动）                                                       │
│  └─ 本机通道 Kestrel  127.0.0.1:47821                                           │
│       ├─ 静态：web pack（index.html 服务时重写、tt.json、assets、map）            │
│       ├─ /__cb/*      ──HTTPS──> CloudBase 网关（Origin: https://tool.furina.fun）│
│       ├─ /__ecs/pptfiles/* ──HTTP/HTTPS──> ECS 缓存                              │
│       ├─ /__ecs/drop/*     ──HTTP/HTTPS──> ECS 文件传输                          │
│       └─ /__ecs/att/*      ──HTTP/HTTPS──> ECS 附件（预留）                      │
│                                                                                 │
│  WebView2（独立 userDataFolder）── 只加载 http://127.0.0.1:47821                │
└─────────────────────────────────────────────────────────────────────────────────┘
        │ 页面内仍只有原有请求：CloudBase（经本机代理）、OSS 图片/视频、ECS 文件
        ▼
   更新源：ECS /dl/win/*  + 阿里云 OSS win/*（manifest 用 RSA-PSS 签名）
```

### 4.2 启动链路（时序）

1. 单实例互斥；第二个实例把参数发给第一个并退出。
2. 读取 `%LOCALAPPDATA%\ClassTools\settings.json`；处理上次未删完的 guest profile。
3. 检查 WebView2 Runtime；缺失 → 安装引导（在线引导器/离线固定版）。
4. 校验当前 web pack（`pack.json` 内每个文件 SHA-256；失败 → 修复/回退上一包）。
5. 启动 Kestrel（固定端口 47821）；失败 → 明确弹窗（端口占用/权限）。
6. 创建 WebView2 环境（独立 profile；禁用开发者工具/默认右键；设置浏览器参数）。
7. 导航 `http://127.0.0.1:47821/`。
8. 页面加载后自检：`CB` 是否以 `/__cb/` 开头；不是 → 显示「壳与网页版本不匹配，请更新」。
9. 延迟 30s 检查更新（壳/pack）；启动托盘。
10. 退出时：关 WebView2 → 停 Kestrel →（公用模式）删 profile → 跑更新 helper。

### 4.3 数据与目录

| 内容 | 个人模式 | 公用电脑模式 | 便携模式 |
|---|---|---|---|
| 程序 | `%LOCALAPPDATA%\Programs\ClassTools\` | 同左 | `X:\ClassTools\` |
| WebView2 profile | `%LOCALAPPDATA%\ClassTools\profiles\default` | `…\profiles\guest`（退出即删） | `.\data\profiles\default` |
| Web pack | `%LOCALAPPDATA%\ClassTools\web\packs\<ver>` | 同左 | `.\data\web\packs\` |
| 设置 | `%LOCALAPPDATA%\ClassTools\settings.json` | 同左（模式=guest） | `.\data\settings.json` |
| 下载 | `%USERPROFILE%\Documents\ClassTools\`（可改） | 同左（可选退出清理） | `.\downloads\` |
| 日志 | `%LOCALAPPDATA%\ClassTools\logs\` | 同左（脱敏） | `.\data\logs\` |
| 更新缓存 | `%LOCALAPPDATA%\ClassTools\updates\` | 同左 | `.\data\updates\` |

**端口固定 47821**：origin 稳定，`localStorage`/IndexedDB 才能跨启动保留。端口被占用时**不自动换端口**（换端口=换 origin=掉登录），弹窗让用户处理；测试可用 `--port`（会提示需重新登录）。

**已知限制**：同一台电脑如果有两个 Windows 用户同时登录并各开一个桌面版，固定端口会冲突。教室/个人都是单会话场景，可接受；若后续要支持，可按用户 SID 派生稳定端口（P2，代价是跨用户数据天然隔离）。

---

## 5. 关键设计

### 5.1 本机通道（核心）

#### 5.1.1 服务时重写（5 条，缺一不可，失败即关闭）

本机服务器返回 `index.html` 前，在内存做**精确字符串替换**；pack 文件本身保持与线上逐字节一致（便于校验/更新）。

| # | 原文（精确） | 替换为 | 期望次数 | 作用 |
|---|---|---|---|---|
| R1 | `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/` | `/__cb/` | 1 | 登录/全部数据走本机代理，消除 CORS |
| R2 | `PPT_ECS_BASE="https://tool.furina.fun/pptfiles"` | `PPT_ECS_BASE="/__ecs/pptfiles"` | 1 | PPT 下载同源，`download` 文件名生效 |
| R3 | `"https://tool.furina.fun/drop"` | `"/__ecs/drop"` | 4 | 文件传输/大屏互联同源，不依赖 drop 的 CORS |
| R4 | `location.origin+location.pathname+"#drop"` | `"<ShareBase>/#drop"` | 1 | 「复制互联链接」不再复制出 `127.0.0.1` 的无效链接 |
| R5 | `var base="https://tool.furina.fun";` | `var base="<ShareBase>";` | 1 | 抽签核验二维码/链接在备案期也能扫开（当前用 ECS IP，域名恢复后自动用域名） |

**`<ShareBase>` 的取值**：启动时先用上次缓存（首次默认 `https://tool.furina.fun`），后台用 2s HEAD 探测 `https://tool.furina.fun/`；可用则切 `https://tool.furina.fun`，否则若 `https://tool.furina.fun/` 可用则保持 IP，两者都不可用则仍用域名（此时分享出去也打不开，等联网）。探测结果缓存 10 分钟并后台刷新；页面重新加载即用新值。**不要把 ShareBase 写死成 IP 或域名**：备案期/恢复期两种状态都要能用。

规则实现要求：

- 每条**必须匹配到期望次数**；任一不符 → 不返回页面，显示本机错误页「Windows 壳与网页版本不匹配，请更新壳」。**不允许半替换后带病运行**（否则表现为登录 404/文件下载失败，极难排查）。
- 重写后在 HTML 顶部加一行注释：`<!-- CT-DESKTOP-REWRITE v1 cb=1 ppt=1 drop=4 share=1 verify=1 -->`，供自检/日志。
- 规则表随壳版本号管理（`RewriteProfile = "2026-11-16.1"`）；网页升级若改动这些字符串，发布前用 `tools/tests` 跑壳的兼容测试，或同步发壳。
- **不改** `h==="tool.furina.fun"` 这类 hostname 判断（本机 hostname 是 `127.0.0.1`，不会命中，留着无害）；不做全局 IP 替换，避免误伤判断逻辑。

#### 5.1.2 路由表

| 路由 | 上游 | 说明 |
|---|---|---|
| `/`、`/index.html` | 本地 pack | 读取 + 重写 + 内存缓存 |
| `/tt.json` | **ECS 在线优先**（`/tt.json`，2s 超时、缓存 5 分钟）→ 本地 pack 兜底 | 避免 pack 里的课表快照长期陈旧；断网仍可用 |
| `/assets/*`、`/map/*`、`/favicon.ico` | 本地 pack | `map` 是页面 iframe 的 `/map/campus_final_25d.html`，必须随包 |
| `/__cb/*` | `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/*` | 固定 `Origin: https://tool.furina.fun`、`Referer` 同值；TLS 校验开启 |
| `/__ecs/pptfiles/*` | `https://tool.furina.fun/pptfiles/*`（域名恢复后优先 `https://tool.furina.fun/pptfiles/*`） | 保留 Range/206/HEAD/Content-Length；大文件流式 |
| `/__ecs/drop/*` | `https://tool.furina.fun/drop/*`（同上可切 HTTPS） | 8 MiB 分片上传；流式，不整包缓冲 |
| `/__ecs/att/*` | `https://tool.furina.fun/att/*`（预留） | 目前页面附件走绝对 URL，暂不强制 |
| `/__chan/health` | 本机 | 返回 `{ok, shell, pack, rewrite}`；不返回 token/路径 |
| 其它 | 404 | **不是开放代理**：上游 host 由路由固定，绝不根据请求 URL 拼接 |

上游选择：

- `/__cb` 永远走 CloudBase HTTPS（与域名无关，备案期也可用）。
- ECS 上游默认 HTTP IP；启动后异步探测 `https://tool.furina.fun/pptfiles/__health`（2s 超时），可用则新请求切 HTTPS，失败保持 HTTP；每 10 分钟复探一次。只影响媒体/文件，不影响登录。

#### 5.1.3 安全控制（产品化时必须补上，原型没有）

| 控制 | 做法 | 原因 |
|---|---|---|
| 只监听回环 | `Listen(IPAddress.Loopback, 47821)` | 不暴露给局域网 |
| Host 校验 | 只接受 `127.0.0.1:47821` / `localhost:47821` | 防 DNS rebinding |
| 每次启动随机 cookie | `Set-Cookie: ct_ch=<32B>; Path=/; HttpOnly; SameSite=Strict`；`/__cb`、`/__ecs` 必须带 | 跨站请求带不上 SameSite=Strict cookie；无需改网页 |
| Origin 校验 | 有 `Origin` 且不等于 `http://127.0.0.1:47821` → 403 | 防浏览器跨站调用本机代理 |
| Sec-Fetch-Site | 只允许 `same-origin`/`none`（缺失按同源处理）；`cross-site`/`same-site` → 403 | 同上 |
| 方法白名单 | GET/HEAD/POST/PATCH/DELETE/OPTIONS | 与 PostgREST/ECS 实际使用一致 |
| 请求体上限 | 16 MiB（> 8 MiB drop 分片 + 余量） | 防内存攻击；PPT 分片 512 KiB |
| 路径校验 | 拒绝 `..`、编码斜杠、绝对 URL、`//`；静态文件必须落在 pack 根内 | 防目录穿越/开放代理 |
| 响应头白名单 | 只回 `Content-Type/Length/Range/Disposition/ETag/Cache-Control/Last-Modified/Location`；剥离 `Set-Cookie`/`Access-Control-*` | 不把上游 cookie/CORS 带进本机 |
| 不记录敏感信息 | 日志只记方法/路径（去 query）/状态/耗时；不记 header/body/token | 防日志泄露 |
| 超时 | 连接 10s、响应头 30s、空闲 60s；大文件流式不设总时长 | 防挂死 |
| TLS | 使用系统根证书与系统代理；**不关闭校验** | 校园网代理/证书问题要显式报错 |

> 注：原型 `local_channel.py` 的 `OPTIONS` 返回 `Access-Control-Allow-Origin: *`，产品版**必须去掉**（同源不需要 CORS，通配符反而扩大攻击面）。

#### 5.1.4 为什么不用「原生 fetch 代理」或「虚拟主机」

- 原生 fetch/XHR shim：网页有 fetch + 1 处 XHR + `<a download>` + `<video>` + iframe，shim 覆盖不全，且会改变上传进度/流式语义。
- 虚拟主机：见 §3.2，同源路径全要补，复杂度更高。
- 本机通道：浏览器看到的是普通同源 HTTP，所有标准能力（下载属性、Range、iframe、clipboard、fullscreen）都按原样工作，已在原型验证。

### 5.2 身份、存储与公用电脑模式

- **身份**：页面原有 `#idgate`；壳不提供登录 UI、不接触密码、不另存 token。token 仍由页面按原逻辑存在 WebView2 profile 的 localStorage（29 天）。
- **个人模式**：固定 origin + 固定 profile，登录一次可用 29 天；换机/清 profile 需重新登录。
- **公用电脑模式**：
  - 独立 profile `profiles\guest`；退出时关 WebView2 → 删除该目录 → 若文件被锁，写 `delete-on-next-start`，下次启动先删。
  - 每次启动都是身份页；不残留 token、名单、通知缓存、抽签记录。
  - 下载目录可选「退出时清空」；默认保留（PPT 是班级材料，不是个人数据）。
  - 设置里可随时切换；切换会提示「需要重新登录」。
- **不做 DPAPI 存 token**（v1）：token 的信任边界就是 Windows 用户；公用模式用删除 profile 解决。若后续做原生后台通知，再评估 DPAPI（P2）。
- **数据备份/导出/清除**仍用网页的 `#optBkBtn`；壳只在公用模式做整 profile 清理，不另造一套数据管理。

### 5.3 课堂模式（教室场景的核心差异化）

| 能力 | 行为 | 实现要点 |
|---|---|---|
| 进入 | 托盘/标题栏「课堂模式」或 `Ctrl+Alt+K` | 记录当前窗口位置/状态/显示器 |
| 全屏 | 无边框覆盖所选显示器（含任务栏） | `WindowStyle=None` + `ResizeMode=NoResize`，按 `Screen.Bounds`（按 DPI 换算成 WPF 单位）设置窗口 bounds（不要只靠 `Maximized`，它可能只到工作区）；不置顶（避免盖住 PowerPoint） |
| 投影屏 | 设置里选「主屏/副屏/自动」；进入时移动到该屏 | `Screen.AllScreens`；`SystemEvents.DisplaySettingsChanged` 重新应用 |
| 常亮 | 进入即阻止息屏/睡眠；退出恢复 | `SetThreadExecutionState(ES_CONTINUOUS + ES_SYSTEM_REQUIRED + ES_DISPLAY_REQUIRED)`；显示设置变化后重设 |
| 页面全屏 | 页面自己 `requestFullscreen`（大屏）时，壳同步进全屏 | `ContainsFullScreenElementChanged` 事件 |
| 退出 | 悬浮「退出课堂模式」按钮 + `Ctrl+Alt+Shift+Q`；**不劫持 Esc** | Esc 仍归页面（关弹层/退全屏）；避免把用户困住 |
| 防误触 | 关闭按钮二次确认；保留 F5/刷新；不做全局键盘钩子 | 不劫持系统键，避免与输入法/其他软件冲突 |
| 缩放 | 设置 100/110/125%，记住 | `CoreWebView2.ZoomFactor`；投影 4:3 小字可调 |
| 触摸 | 一体机触摸原样可用 | 不启用任何禁用触摸的选项 |

**刻意不做**：双屏演讲者视图（页面是单屏语义）、强制屏蔽 Alt+Tab/Win 键（需要策略/驱动，且会困住老师）、投影自动识别「谁是投影」的魔法（让用户选一次更可靠）。

**管理员限制**：大屏按钮仍只对 `AUTH.is_admin` 显示；Windows 版**不提权**。如果希望班委也能开大屏，需要改网页门禁（产品决定，不在本期）。

### 5.4 PPT 与文件（桌面价值最高的部分）

#### 5.4.1 下载

- 页面 `<a download="<标题>_兼容版.pptx" href="/__ecs/pptfiles/...">` 在壳内是**同源**，WebView2 会尊重 `download` 文件名。
- 壳拦截 `DownloadStarting`：
  - 取消 WebView2 自带下载，交给原生下载器（进度、取消、Range 断点、重试、完成后「打开/打开文件夹」）。
  - 保存到下载目录；重名追加 ` (2)`；文件名清洗非法字符/保留名/超长（保留后缀）。
  - 下载中任务栏进度；完成托盘气泡。
- 大屏「打开文件」是 `target=_blank`（`:17481`）→ 壳拦截 `NewWindowRequested`：识别 `/__ecs/pptfiles/` 或 OSS `/ppt/` 路径 → 下载完成后**自动打开**（页面意图就是「打开文件」）。
- 外部链接（教务、学信网、地图全屏）→ `NewWindowRequested` 交给默认浏览器，不在应用内开第二个 WebView。
- 视频/音频单独下载（manifest `media_files`）走同一 `<a download>` → 原生下载器。
- 导出图片（blob `a[download]`）→ 保存到 `图片\ClassTools`，托盘提示。

#### 5.4.2 打开 Office

| 情况 | 行为 |
|---|---|
| 本机有 PowerPoint | COM：`PowerPoint.Application` → `AutomationSecurity=ForceDisable`（禁宏）→ `Presentations.Open(path, ReadOnly:=True, WithWindow:=True)` → `SlideShowSettings.Run()`；失败重试 2 次（500ms） |
| 只有 WPS / 无 Office | `ShellExecute` 默认关联打开；提示「按 F5 开始放映」；不假装能自动放映 |
| PDF | 默认阅读器打开 |
| 视频/音频 | 默认播放器打开 |
| 文件被占用/受保护视图 | 捕获异常，提示「关闭已打开的 PowerPoint 后重试 / 解除受保护视图」；不自动改注册表 |

- COM 使用**晚绑定**（`Type.GetTypeFromProgID`），不引 Office PIA；32/64 位 Office 均可（进程外 COM）。
- 下载的文件不写 Mark-of-the-Web（否则教室必进受保护视图）；这是有意的取舍，来源是班级云端，文档中注明。
- 打开后不监控 PowerPoint 进程；PowerPoint 是独立窗口，切回应用不影响（页面已有「窗口失焦回来提示恢复全屏」逻辑）。

#### 5.4.3 文件传输/大屏互联

- `/__ecs/drop` 同源代理，8 MiB 分片流式转发；上传进度由浏览器到本机的背压近似，不会先假 100%。
- 下载签名 URL 仍是绝对 ECS 地址；`window.open` → 壳拦截下载，文件名按 URL 兜底（P2 可让 drop 返回文件名/让页面加 `download`）。
- 大屏互联的 13 类遥控指令、presence 轮询原样；壳不做额外协议。

### 5.5 通知、托盘与后台

- **托盘常驻**：关闭窗口默认最小化到托盘（首次提示）；托盘菜单：打开、课堂模式、刷新、检查更新、打开下载文件夹、设置、退出。
- **页面保活**：最小化/托盘时 WebView2 不销毁；浏览器参数加 `--disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows`，让页面 45s 通知轮询继续跑。
- **系统通知**：
  - M0 验证 WebView2 `NotificationReceived`/权限事件；可用则把页面的 `new Notification` 转成 Windows 通知（点击激活窗口）。
  - 不可用则 v1 只保证「窗口可见时页内提醒」；P1 通过桥让页面调用原生 toast（需 1 行网页钩子，届时再评估）。
  - **不建独立推送服务**（无 WNS/WebSocket/后台轮询进程），避免多一套账号/token 存储。
- **开机自启**：HKCU `Run`，参数 `--autostart`（启动到托盘/身份页，不自动全屏）；公用模式默认关闭。
- **单实例**：`Local\Furina.ClassTools.Desktop` 互斥；命名管道传参；第二次启动激活已有窗口。
- **深链**：注册 `classtools://`（HKCU，无需管理员）：
  - `classtools://verify/<recordId>` → `#verify=<id>`（抽签存证深链，页面已支持）
  - `classtools://file`、`classtools://drop` → `#file`/`#drop`
  - 其它 → 打开首页
  - 页面加载后用 `ExecuteScriptAsync` 设置 hash；不注入业务逻辑。

**原生设置项（不复制网页的设置）**

| 分组 | 设置 |
|---|---|
| 启动 | 开机自启、启动到托盘、启动页（上次/工作台） |
| 课堂 | 默认进入课堂模式、投影屏（主/副/自动）、界面缩放、退出热键 |
| 窗口 | 关闭到托盘、记住窗口位置/大小 |
| 下载 | 下载目录、完成后打开、完成后打开文件夹、退出时清理（公用模式） |
| 隐私 | 公用电脑模式、立即清除本机数据（profile/pack/日志） |
| 更新 | 自动检查、通道（stable）、检查间隔、当前版本/资源包版本 |
| 诊断 | 打开日志目录、复制诊断信息、代理健康、安全模式重启 |

### 5.6 更新（壳 + 网页资源包）

#### 5.6.1 两个独立版本

| 对象 | 版本 | 更新频率 | 载体 |
|---|---|---|---|
| 壳 | `1.0.0`（Assembly/FileVersion 同） | 低（月/季） | `ClassToolsSetup-x.y.z.exe` / 便携 ZIP |
| 网页资源包 | `2026-11-16.1`（内含 `APP_VER 2.0.0`） | 跟随网页发布（可周） | `pack-<ver>.zip`（约 1.7 MB） |
| 云端契约 | UD v6 / marks / 既有表 | 不变 | — |

#### 5.6.2 清单与验签

- 位置：ECS `/dl/win/shell-latest.json`、`pack-latest.json`；OSS `win/` 同路径兜底。
- 清单含 `version/url/sha256/size/min_shell/notes` 与 `sig`；`sig` 是对固定字符串的 RSA-PSS-SHA256 签名（见附录 B），公钥内嵌在壳里，**私钥只在发布机、永不入仓**。
- 验签失败/哈希不符/版本不升 → 静默放弃，保留当前版本，日志记录；不弹「更新失败」骚扰。
- ECS 目前可能是 HTTP：签名 + SHA-256 保证完整性；安装包另可加 Authenticode（有证书时）。

#### 5.6.3 应用与回滚

- 壳更新：后台下载 → 校验 → 提示「重启安装」→ 退出后 `ClassToolsUpdater.exe` 等待进程结束 → 静默运行安装器（`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`）→ 重启；保留上一版安装包。
- 网页包更新：下载 ZIP → 防 Zip Slip 解压 → 逐文件 SHA-256 → 写入 `packs\<ver>` → 切换 `active` 指针 → 下次启动生效；保留 `previous` 指针。
- **启动健康检查**：新包启动后 20s 内若未出现 `#idgate`/`.wrap` 或 `CB` 自检失败，记一次失败；连续 2 次自动回退 `previous` 并提示。
- 安全模式：`--safe-mode` = 不加载桥/不跑更新/使用安装包自带基线包 + 远程页面（可选），用于救砖。

### 5.7 诊断与日志

- 设置 →「诊断信息」：壳版本、pack 版本/哈希、WebView2 版本、.NET 版本、OS、屏幕/缩放、内存/磁盘、Office/WPS 检测、代理健康、最近 20 行日志；一键复制（脱敏）。
- 日志：`logs\shell-YYYYMMDD.log`，单文件 5 MB、保留 7 天；不记 token/header/body；URL 去 query；异常只记类型/栈（栈里若含路径，按需脱敏）。
- 崩溃：`ProcessFailed` → 记录 + 自动 reload；10 分钟内 3 次 → 弹「安全模式」；GPU 进程反复退出 → 下次以 `--disable-gpu` 启动。
- **不自动上传**任何诊断到云端；页面自带 `#s-diag`/`client_diag` 仍由网页决定，壳不新增字段。

### 5.8 安全与隐私清单（验收逐条打勾）

- [ ] 壳不读取 `deploy/creds.env`、`tools/cert/`、任何 token 文件；不调用真实管理员 token。
- [ ] 日志无 token、无 `X-Device-Id`、无 Cookie、无请求体。
- [ ] 本机代理只监听 `127.0.0.1`；Host/Origin/Sec-Fetch-Site/cookie 四道校验；无 CORS 通配符。
- [ ] 只代理固定上游；路径穿越/绝对 URL/`//` 全部拒绝。
- [ ] 导航只允许本机 origin；外部 http(s) 交给默认浏览器；`file:`/`javascript:`/`data:` 顶层导航拒绝。
- [ ] 下载扩展名白名单（pptx/ppt/pdf/mp4/m4a/zip/图片等）；`.exe/.bat/.cmd/.ps1/.js` 拒绝自动打开。
- [ ] Office 宏禁用；只读打开；不自动改注册表/受保护视图。
- [ ] 公用模式退出后 profile 目录不存在；再次启动无身份/名单/通知残留。
- [ ] 更新清单验签、包逐文件哈希、拒绝降级；失败不影响当前版本。
- [ ] 不新增云端表/RLS/UD v6 键；不把新数据写进 `userdata`。
- [ ] 网页原有「导出图不含手机号/学号/宿舍号」等红线不受壳影响。

### 5.9 与网页的兼容契约（必须写进交接）

壳依赖网页的 5 个字符串（R1–R5）与 3 个路径（`/__cb`、`/__ecs/pptfiles`、`/__ecs/drop`）。因此：

1. 网页改 `CB` 字面量、`PPT_ECS_BASE`、drop 基址、`stgDropLink`、`drawVerifyUrl` 的 base 时，必须同步壳的 `RewriteProfile` 并跑兼容测试；否则壳**失败关闭**（明确报错，不静默半残）。
2. 网页新增同源路径（如 `/att` 改为同源）时，壳要加路由；否则该功能 404。发布清单里加一条「Windows 兼容检查」。
3. `tt.json` 的语义是「同源快照」；壳在线时把它代理到 ECS 最新文件、离线回落本地 pack，避免 pack 内的课表陈旧。网页若改成别的时间戳/路径，需要同步壳。
4. 不要求网页为 Windows 加任何 `if (desktop)` 分支；v1 网页零改动。
5. UD v6 仍 14 顶层键、逐 section LWW；`marks` 仍是唯一真源；壳不碰。
6. 大屏仍仅管理员；壳不绕过。

---

## 6. 功能范围

### 6.1 MVP（第一个可交付版本，必须全有）

| 模块 | 内容 |
|---|---|
| 本机通道 | 静态 pack + R1–R5 重写 + `/__cb` `/__ecs/pptfiles` `/__ecs/drop` 代理 + 安全四校验 + health |
| 壳 | 单实例、窗口记忆、托盘、关闭到托盘、开机自启（可选）、设置、日志、崩溃恢复 |
| 身份/数据 | 现有网页全功能（21+ 工具、通知、PPT、大屏、投票、抽签、名单、电费、水量…） |
| 下载 | PPT/PDF/原件/视频/附件/导出图落盘、重名处理、打开文件夹 |
| Office | PPT 下载后打开；PowerPoint COM 放映；WPS/无 Office 回退 |
| 课堂 | 全屏、选投影屏、常亮、退出按钮/热键、缩放 |
| 公用模式 | 独立 profile、退出删除、切换提示 |
| 更新 | 壳 + pack 清单、验签、下载、静默安装、回滚、安全模式 |
| 安装 | 每用户安装器（无管理员）、便携 ZIP、卸载、快捷方式、WebView2 检测 |
| 诊断 | 本机诊断信息、日志、代理 health |

### 6.2 P1（第二版）

- 深链 `classtools://`（verify/file/drop）
- 系统通知（WebView2 可用则接；否则桥 + 1 行网页钩子）
- pack 自动更新（MVP 为「检查 + 提示后应用」，P1 改静默后台）
- 批量下载/下载队列 UI
- 界面缩放预设、投影 4:3 预设
- Office 打开后失败的可视化指引（受保护视图/Office 2007）
- 下载文件名透传（attachments/drop，若页面/服务端配合）

### 6.3 P2（按需，需单独设计）

- 安卓独有学校系统入口（今日校园 CAS、教务 WebVPN、第二课堂、学信网提取）——涉及学校账号/隐私，**不在 v1**
- ARM64 构建
- 多 profile/多账号并行
- Win7/8.1 固定 WebView2 109 兼容包（安全风险，不建议）
- 原生 toast/通知中心、任务栏未读徽标
- 课堂「预装包」：把 pack + 已缓存数据 + 已下载 PPT 复制到另一台电脑（涉及隐私，需确认）

### 6.4 明确不做

- 原生重写业务/第二套 UI
- 新云端表、新 RLS、UD v6 新顶层键、新同步类别
- 班级公用账号/代登录/密码代填
- 管理员提权/绕过身份门禁
- 后台常驻推送服务/WNS/WebSocket
- 修改 `me.furina.fun` 或任何其他站点

---

## 7. 技术选型与工程结构

### 7.1 选型

| 层 | 选型 | 理由 |
|---|---|---|
| 运行时 | **.NET 10 LTS**（self-contained，win-x64） | 本机已装 10.0.115 SDK；LTS 到 2028；免装 .NET；WPF 成熟 |
| UI 壳 | **WPF**（少量 WinForms `NotifyIcon`） | 高 DPI/多屏/窗口状态成熟；不引第三方 UI 库 |
| 浏览器 | **WebView2 Evergreen**（固定版作离线兜底） | Win11 通常已带；Win10 可能需安装（每用户引导器）；与 Edge 同核；CDP 可测 |
| 本机服务 | **Kestrel**（ASP.NET Core 框架引用） | 无 HTTP.sys ACL/管理员问题；流式/超时/取消成熟 |
| JSON | `System.Text.Json` | 内置 |
| 加密 | `RSA`（PSS/SHA-256）+ `SHA256` | 内置，无第三方 |
| 测试 | xUnit + Python CDP（复用 `tools/tests/_qa_v2/_cdp.py`） | 单测 + 真实 WebView2 页面自动化 |
| 安装 | Inno Setup 6（`PrivilegesRequired=lowest`） | 每用户安装、无管理员、静默更新 |
| 依赖 | 仅 `Microsoft.Web.WebView2` NuGet + BCL | 不引 UI/日志/HTTP 第三方库；构建期 NuGet 可接受（与安卓 Gradle 同理） |

> 不使用 Electron（体积/内存/Node 攻击面）、Tauri（Rust + COM 成本）、WinUI 3（Windows App SDK 额外运行时/打包复杂度）、WinForms 主体（DPI/布局弱）。

### 7.2 仓库与目录（建议独立仓库）

与安卓一致，建议独立仓库 `windows-class-tools`（避免 .NET `bin/obj`、安装包进入网页仓库）；本设计文档留在 `web/docs/`，两仓互相链接。

```
windows-class-tools/
├─ ClassTools.sln
├─ Directory.Build.props            # 版本、Nullable、警告即错误
├─ src/ClassTools.Desktop/
│  ├─ App.xaml / MainWindow.xaml
│  ├─ Hosting/                      # 单实例、托盘、窗口、深链、启动参数
│  ├─ Web/                          # WebView2 环境、导航/下载/权限/全屏事件
│  ├─ LocalServer/                  # Kestrel、静态、重写、反代、安全校验
│  ├─ Features/
│  │  ├─ Classroom/                 # 全屏/投影/常亮
│  │  ├─ Office/                    # PowerPoint COM / ShellExecute
│  │  ├─ Downloads/                 # 下载器/文件名/进度
│  │  ├─ Updates/                   # 清单验签/下载/替换/回滚
│  │  └─ Diagnostics/               # 日志/诊断信息
│  ├─ Settings/                     # 设置模型/迁移
│  └─ Assets/                       # 图标、桥脚本（P1）
├─ tests/ClassTools.Desktop.Tests/  # xUnit（重写/代理/验签/文件名/路径）
├─ tests/e2e/                       # Python CDP 场景（复用 web 测试基座）
├─ installer/ClassTools.iss
├─ tools/                           # build.ps1 / pack.ps1 / sign_manifest.py / release.ps1
├─ docs/                            # TEST_PLAN / RELEASE / SECURITY / BRIDGE
└─ keys/                            # 仅公钥；私钥 gitignore
```

### 7.3 构建与发布流水线

```
build.ps1
  → dotnet publish src/ClassTools.Desktop -c Release -r win-x64 --self-contained true
  → 复制 web pack（从线上字节构建，见下）
  → Inno Setup 编译安装器；便携 ZIP
  → 生成 shell/pack manifest；sign_manifest.py 用发布机私钥签名
  → release.ps1 上传 ECS /var/www/tool-dl/win/ + OSS win/
  → 输出 SHA-256/大小/版本，写入发布记录
```

**网页资源包构建**（放网页仓库 `deploy/win_pack.py`，或壳仓库 `tools/pack.ps1` 调它）：

1. 从**线上对象**取 `index.html`（`deploy/oss_object.py`/OSS SDK），校验与部署记录一致；**不用工作区未部署的 WIP**。
2. 取 `tt.json`、`tools/assets/**`、`map/**`（`campus_final_25d.html` + data）。
3. 生成 `pack.json`（文件/大小/SHA-256、`web_ver`、`pack` 版本）。
4. 打 ZIP（仅存储/压缩），签名清单，上传。
5. 在壳的兼容测试里加载该 pack，跑 R1–R5 断言 + 测试身份登录。

---

## 8. 安装、分发与兼容性

### 8.1 三种包

| 包 | 大小（估） | 适用 | 说明 |
|---|---|---|---|
| 在线安装器 `ClassToolsSetup-x.y.z.exe` | ~60–80 MB | 大多数个人电脑 | 自包含 .NET；检测 WebView2，缺则运行 2 MB 在线引导器（需联网，每用户安装） |
| 离线完整包 `ClassToolsOffline-x.y.z.exe` | ~220–260 MB | 教室/无网/无管理员 | 含固定版 WebView2，插 U 盘即装；不依赖在线引导 |
| 便携 ZIP `ClassTools-Portable-x.y.z.zip` | ~80–100 MB | 教室 U 盘/临时用 | 解压即用；数据在 `.\data`；不写注册表（除可选深链/自启，默认关） |

### 8.2 安装流程（每用户，无需管理员）

1. 选择安装位置（默认 `%LOCALAPPDATA%\Programs\ClassTools`）。
2. 创建开始菜单快捷方式（含 AUMID，供通知）；桌面图标可选；开机自启可选。
3. 检测 WebView2：有 → 继续；无 → 在线引导/固定版。
4. 安装完成后启动；首次运行向导（2 屏）：
   - 用途：教室电脑 / 个人电脑（决定公用模式默认、自启、全屏默认、下载目录）
   - 下载目录 + 是否创建桌面图标
5. 进入网页身份页（学号+姓名）。

卸载：删除程序/快捷方式/自启/深链；询问是否保留 `settings/downloads`（默认保留下载，删除 profile 与 pack）。

### 8.3 兼容矩阵（必须实测）

| 维度 | 覆盖 |
|---|---|
| OS | Windows 10 1809 / 21H2 / 22H2；Windows 11 23H2 / 24H2（x64） |
| WebView2 | 当前 Evergreen（本机 157）；最低 109（不支持 Win7）；固定版离线 |
| 屏幕 | 1366×768、1920×1080、2560×1440、3840×2160；100/125/150% |
| 显示 | 单屏、双屏（复制/扩展）、投影 4:3 1024×768、16:9 |
| Office | Microsoft 365 / 2019 / 2016 / 2013 / 2010；WPS；无 Office |
| 网络 | 有线/校园 Wi-Fi/手机热点；断网→恢复；系统代理；慢网 |
| 安装 | 无管理员、Program Files 只读、U 盘便携、多用户切换 |
| 安全软件 | Defender、360、火绒（未签名 exe 的拦截/误报） |

**Windows 7/8.1**：不支持。WebView2 在 109 之后停止支持，.NET 10 也不支持；强行做固定 109 会把一个已知 EOL 的 Chromium 放进教室。若教室只有 Win7，建议用自带笔记本/升级（见 §13-Q1）。

### 8.4 SmartScreen / 杀软 / 签名

- 未签名的 exe 首次运行会弹「Windows 已保护你的电脑」；这是预期行为，不是 bug。
- 方案：
  - **默认**：不买证书；安装包旁附 SHA-256，班级群说明「更多信息 → 仍要运行」。
  - **可选**：OV/EV 代码签名证书（约 ¥1k–3k/年）；有证书则签 exe + 安装器，SmartScreen 逐步建立信誉。
  - 不推荐自签名（仍会警告，且要装根证书，反而更吓人）。
- 杀软误报：提交样本/加白说明；提供便携 ZIP 作为替代。

---

## 9. 性能预算

| 指标 | 目标 | 备注 |
|---|---|---|
| 冷启动到窗口 | ≤3 s（SSD）/ ≤6 s（HDD） | Kestrel + WebView2 初始化为主 |
| 到身份页可交互 | ≤4 s / ≤7 s | 本地 pack，无网络等待 |
| 登录后工作台 | ≤2 s（网络正常） | 与原网页一致 |
| 空闲内存 | ≤450 MB（壳+WebView2） | 4 GB 教室机可接受 |
| 空闲 CPU | <1% | 45s 轮询；隐藏时浏览器降频 |
| pack 更新下载 | 2 MB，≤5 s（ECS） | 后台 |
| 37 MB PPT 下载 | 5–9 MB/s（ECS 缓存） | 原生下载器；不经过页面内存 |
| 全屏切换 | <300 ms | 无动画或短动画 |

---

## 10. 测试与验收

### 10.1 分层

| 层 | 工具 | 覆盖 |
|---|---|---|
| 单元 | xUnit | R1–R5 重写计数/失败关闭；代理头白名单/路径校验/cookie/Origin；文件名清洗；版本比较；清单验签（好/篡改/降级）；ZIP 解压防穿越；设置迁移；深链解析 |
| 集成 | xUnit + 本地 mock 上游 | 静态服务、`/__cb` GET/POST/PATCH/DELETE、206/Range、8 MiB 上传、超时/取消、并发 |
| 页面 E2E | Python CDP（复用 `_qa_v2/_cdp.py`） | 启动壳（`--remote-debugging-port`）→ 身份页 → 测试身份登录 → 工具冒烟 → PPT 下载/打开 → 全屏 → 托盘/单实例 |
| 视觉 | CDP 截图 | 1366×768、1920×1080、4K 150%、双屏；无横向溢出、无空白 |
| 手工 | 真实教室 | 投影 4:3/16:9、10 m 可读、45 分钟稳定、常亮、PPT/WPS、遥控器 |
| 安全 | 脚本 + 手工 | 跨站请求本机代理被拒；日志无 token；公用模式清理；更新篡改被拒 |

### 10.2 E2E 场景（编号，测试身份/mock）

| # | 场景 | 断言 |
|---|---|---|
| S1 | 断网冷启动 | 身份页可见；无外部请求；错误可读；恢复网络后可登录 |
| S2 | 测试身份登录 | `#idgate` → 工作台；`/__cb` 请求全部 200；0 console error |
| S3 | 21 工具冒烟 | 每个 tab 打开、0 报错、无横向溢出（1366/1920） |
| S4 | PPT 下载 | 文件名 = `标题_兼容版.pptx`；落盘大小与云端对象一致；目录正确；可被 Office 打开 |
| S5 | PPT 打开 | 有 Office → PowerPoint 进程/窗口出现；无 Office → 默认程序/提示 |
| S6 | 大屏（mock admin） | 全屏/退出/投影屏选择/常亮标志；Esc 不困住用户 |
| S7 | 公用模式 | 退出后 profile 目录不存在；重启回身份页；无 token/名单残留 |
| S8 | 壳更新 | mock 清单 → 下载/验签/静默安装/重启；版本变化 |
| S9 | 更新篡改 | 改 1 字节 → 验签失败；当前版本不变 |
| S10 | pack 回滚 | 注入坏包 → 2 次失败后回退上一包 |
| S11 | 单实例 | 第二次启动不新开窗口；激活已有窗口 |
| S12 | 代理安全 | 从 `http://evil.test` 页面 POST 本机 `/__cb` → 403；无 cookie/Origin 也 403 |
| S13 | 断网/恢复 | 断网时抽签可用且标「未存证」；恢复后可重试存证（页面逻辑） |
| S14 | 4K/150% | 字体/点击区正常；无模糊（WebView2 自带 DPI） |

### 10.3 测试账号红线

- 只用官方测试身份 `3260799999 / 测试账号`；需要第二成员时用 `finally` 删除的 9999 段临时 QA 身份。
- **不登录真实同学/管理员**；大屏/管理员场景用页面 mock（预写 `zq_class_identity` 的 `is_admin:true` + mock 数据），不注入真实管理员 token。
- 所有写云端操作限制在测试身份；测试结束清理临时数据；不在云端留测试 PPT（`cleanup_test_decks.py --apply` 兜底）。

### 10.4 验收清单（交付前逐条）

**教室**
- [ ] 1366×768 / 1920×1080 投影下，大屏文字 10 m 可读；4:3 不裁切
- [ ] 全屏进入/退出不黑屏、不抢焦点、不盖住 PowerPoint
- [ ] 45 分钟计时/投票/抽签无休眠、无掉帧、无内存持续上涨
- [ ] PPT 约 39 MB 兼容包下载→PowerPoint 打开→放映；WPS/无 Office 有清晰兜底
- [ ] 断网时抽签/点名/课表快照可用；联网后自动恢复

**个人**
- [ ] 登录一次 29 天内免登录；退出后清身份
- [ ] 托盘/页内提醒可用；WebView2 通知在 M0 验证通过时，系统通知可用
- [ ] 无管理员安装；卸载干净
**安全**
- [ ] §5.8 全部打勾；日志抽查无 token
- [ ] 更新篡改/降级被拒；公用模式无残留

---

## 11. 里程碑与工作量

| 阶段 | 内容 | 人日 | 出口条件 |
|---|---|---|---|
| M0 可行性 | WebView2 宿主原型；Kestrel 通道；R1–R5；Office COM；全屏/投影；目标机 OS/WebView2 确认 | 2–3 | 测试身份登录成功；PPT 能下载并打开；目标机可跑 |
| M1 壳 MVP | 窗口/单实例/托盘/设置/日志；静态+代理+安全校验；下载器；安装器骨架 | 5–6 | S1–S4/S11/S12 通过 |
| M2 课堂 | 全屏/投影/常亮/退出/缩放；通知/托盘保活 | 3–4 | S6 通过；教室手工验收 |
| M3 Office/文件 | PPT 拦截/下载/COM/WPS；附件/导出图；文件传输代理 | 3–4 | S4/S5 通过 |
| M4 更新/分发 | 壳+pack 清单/验签/更新/回滚/安全模式；在线/离线/便携包 | 4–5 | S8–S10 通过；无管理员安装 |
| M5 测试/交付 | 兼容矩阵、E2E、文档、发布记录、验收 | 4–5 | §10.4 全绿；发布 |
| **合计** | | **20–28 人日** | 4–6 周（兼职） |

> 估算不含：CloudBase 续费/迁移、域名备案、代码签名采购、学校网络/管理员策略沟通。

---

## 12. 风险与回滚

| 风险 | 概率/影响 | 缓解 | 回滚 |
|---|---|---|---|
| CloudBase 到期（2026-12-10） | 高/致命 | 发布前续费或迁移；本文不替代 | 无客户端可救；必须云端处理 |
| 教室只有 Win7 | 中/致命 | M0 先确认；不支持 Win7，改用笔记本/升级 | 不发布 Win7 版 |
| 未签名被 SmartScreen/杀软拦 | 高/中 | 说明 + SHA-256；可选 OV 证书；便携 ZIP | 用便携版/网页 |
| WebView2 缺失/被策略禁 | 中/中 | 在线引导/固定版离线包；检测失败给清晰指引 | 退回网页版 |
| 网页字符串漂移导致重写失败 | 中/高 | 期望次数校验、失败关闭、发布前兼容测试 | 更新壳；或 `--remote` 远程页面模式 |
| Office COM 被占用/版本差异 | 中/中 | 重试 + ShellExecute 兜底 + 提示 | 手动下载后用 Office 打开 |
| 公用模式删除 profile 失败 | 低/中 | 下次启动删除；提示 | 设置里「立即清除本机数据」 |
| 端口占用/多用户同时登录 | 低/中 | 固定端口 + 明确弹窗；文档说明 | 关闭占用程序；`--port`（需重登） |
| 维护第四端成本 | 中/中 | 业务零复制；壳只做宿主；测试复用 CDP | 停更壳，网页仍可用 |
| 大屏仅管理员，教室无人是管理员 | 中/产品 | 明确提示；需要时另做网页门禁变更 | 不做壳内提权 |

**回滚点**

- 壳：保留上一版安装包；回滚=发布一个**版本号更高、内容为旧版**的包（不做降级），或让用户手动装旧包。
- pack：`packs\previous` + 设置「使用上一版资源包」；删除 `active` 指针自动回退。
- 网页：**零改动**，无需回滚。
- 云端：**零改动**，无需回滚。
- 应急：`--safe-mode` 或 `--remote`（直接加载线上 `https://tool.furina.fun/`，功能等同浏览器，无离线/Office 增强）。

---

## 13. 待确认问题（请拍板；括号是推荐）

| # | 问题 | 为什么重要 | 推荐 |
|---|---|---|---|
| Q1 | **教室电脑的实际 OS/内存/分辨率/是否管理员？** | 决定 Win10 基线、离线包、安装方式；若是 Win7 本方案不成立 | 先给我一台教室机的 `winver`/内存/分辨率；按 Win10 1809+ 设计 |
| Q2 | 主要用途优先级：教室大屏 vs 个人电脑完整客户端？ | 决定课堂模式/Office 的投入顺序 | 教室优先，个人同等功能 |
| Q3 | 接受「WebView2 壳」还是坚持原生界面？ | 原生重写 60–100 人日、长期三套逻辑 | 接受壳；这是桌面端性价比最高的形态 |
| Q4 | 安装包大小/形态：在线 ~70 MB / 离线 ~250 MB / 便携 ZIP？ | 教室无网/无管理员时离线包是刚需 | 首发在线 + 离线（教室兜底）；便携可随后补 |
| Q5 | 是否购买代码签名证书？ | 未签名会有 SmartScreen 警告/杀软误报 | 先不买；班里说明 + SHA-256；校级推广再买 OV |
| Q6 | 公用电脑模式默认开还是关？ | 教室多人用，隐私 vs 免登录便利 | 首次向导让用户选；教室默认开，个人默认关 |
| Q7 | 大屏仍仅管理员？ | 教室电脑若登录的是普通同学，开不了大屏 | 保持现状；若要班委可用，另做网页门禁变更（不在本期） |
| Q8 | 是否需要 Win7 / ARM64？ | Win7 需固定 WebView2 109（EOL） | 都不做；Win10 x64 起步，ARM64 P2 |
| Q9 | 是否要安卓独有学校系统入口（今日校园/教务 WebVPN/学信网）？ | 涉及学校账号与隐私，工作量大 | v1 不做；P2 单独立项 |
| Q10 | 仓库：独立 `windows-class-tools` 还是放 `web/windows/`？ | 影响构建产物/双远端流程 | 独立仓库（与安卓一致）；设计文档留在 `web/docs/` |
| Q11 | 更新源：ECS `/dl` + OSS 兜底？ | 需要改 `ecs_site.py` 加一条 Caddy handle | 是；ECS 快、OSS HTTPS 兜底；清单签名 |
| Q12 | 是否接受「PPT 下载后自动调起 PowerPoint 放映」？ | 教室最省步骤，但会抢焦点 | 是；提供设置「只下载不打开」 |

---

## 附录 A：重写与代理细节（实现对照）

### A.1 重写规则（服务时，内存）

```text
R1  count=1  https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/  ->  /__cb/
R2  count=1  PPT_ECS_BASE="https://tool.furina.fun/pptfiles"                              ->  PPT_ECS_BASE="/__ecs/pptfiles"
R3  count=4  "https://tool.furina.fun/drop"                                                ->  "/__ecs/drop"
R4  count=1  location.origin+location.pathname+"#drop"                                 ->  "<ShareBase>/#drop"
R5  count=1  var base="https://tool.furina.fun";                                       ->  var base="<ShareBase>";
```

- 任一条 count 不符：不返回页面，本机错误页 + 日志 `rewrite_mismatch rule=R? expected=? actual=?`。
- 成功：HTML 顶部插 `<!-- CT-DESKTOP-REWRITE v1 ... -->`；`/__chan/health` 暴露计数（不含内容）。
- `<ShareBase>` 由壳在启动/每 10 分钟探测 `https://tool.furina.fun/` 与 `https://tool.furina.fun/` 后决定（见 §5.1.1），不是固定值。
- 兼容性测试：`tests/test_rewrite.py` 读取线上 `index.html`，断言 5 条计数；发布前跑。

### A.2 代理请求头（白名单）

`Authorization`、`Content-Type`、`Accept`、`Prefer`、`X-Device-Id`、`X-Class-Token`、`Cache-Control`、`Range`、`If-Range`、`X-Upload-Id`（drop）、`Content-Range`（drop）、`Content-Length`（由 Kestrel 计算，不手工转发）。

固定注入（仅 `/__cb`）：`Origin: https://tool.furina.fun`、`Referer: https://tool.furina.fun/`、`Accept-Encoding: identity`。

### A.3 代理响应头（白名单）

`Content-Type`、`Content-Length`（Kestrel 设置）、`Content-Range`、`Accept-Ranges`、`Content-Disposition`、`ETag`、`Cache-Control`、`Last-Modified`、`Location`。

剥离：`Set-Cookie`、`Access-Control-*`、`Transfer-Encoding`、`Connection`、`Server`。

### A.4 与现有原型的差异（产品化必须改）

| 原型 `local_channel.py` | 产品版 |
|---|---|
| 端口自动顺延 | 固定 47821；占用即报错（保 origin） |
| `OPTIONS` 返回 `ACAO:*` | 去掉 CORS 头；同源不需要 |
| 无 cookie/Origin/Host 校验 | 四道校验（§5.1.3） |
| 响应整体读入内存 | 流式；大文件不缓冲 |
| 只代理 `/__cb` | 加 `/__ecs/pptfiles`、`/__ecs/drop`、`/__ecs/att` |
| 无重写自检 | 5 条计数校验 + health + 失败关闭 |
| Python `http.server` | Kestrel；超时/取消/连接池 |

---

## 附录 B：更新清单 schema 与签名

### B.1 壳清单 `shell-latest.json`

```json
{
  "schema": 1,
  "kind": "shell",
  "version": "1.0.0",
  "url": "https://tool.furina.fun/dl/win/ClassToolsSetup-1.0.0.exe",
  "sha256": "<hex>",
  "size": 73400320,
  "min_version": "1.0.0",
  "web_ver": "2.0.0",
  "notes": "首个 Windows 版",
  "sig": "<base64 RSA-PSS-SHA256>"
}
```

签名原文（固定、无 JSON 规范化）：

```text
shell\n1.0.0\n<url>\n<sha256>\n<size>\n<min_version>
```

### B.2 资源包清单 `pack-latest.json`

```json
{
  "schema": 1,
  "kind": "pack",
  "pack": "2026-11-16.1",
  "web_ver": "2.0.0",
  "url": "https://tool.furina.fun/dl/win/pack-2026-11-16.1.zip",
  "sha256": "<zip hex>",
  "size": 1780000,
  "min_shell": "1.0.0",
  "max_shell": "1.99.99",
  "files": [{"path": "index.html", "size": 1322990, "sha256": "<hex>"}],
  "notes": "跟随网页 2026-11-16 发布",
  "sig": "<base64>"
}
```

签名原文：

```text
pack\n2026-11-16.1\n<zip url>\n<zip sha256>\n<size>\n<min_shell>\n<max_shell>
```

- 公钥：`keys/manifest_pub.pem`，编译进壳；私钥只在发布机（如 `C:\briefdesk\secrets\win_manifest_key.pem`），**gitignore、不打印、不复制进对话**。
- 验签失败/哈希不符/版本不升/`min_shell` 不满足 → 放弃本次更新，保留当前。

---

## 附录 C：证据与参考

| 事实 | 证据 |
|---|---|
| 本机通道 + 当前页面可用 | 2026-11-16 实跑 `python deploy/local_channel_selftest.py` → `RESULT: PASS`；9 个 `/__cb` 请求；0 console/network error |
| 通道原理 | `deploy/LOCAL_CHANNEL.md` §原理；`deploy/local_channel.py:26-33,86-95,177-218` |
| CB 字面量/同源切换 | `tools/index.html:4322,4327-4328` |
| PPT 下载与文件名 | `tools/index.html:13562-13571,13642-13643`；`ppt/CONTRACT.md` §12 |
| 大屏「打开文件」是 `target=_blank` | `tools/index.html:17481`（与 `AGENTS.md` §33 的 `ms-powerpoint:` 描述不一致，以代码为准） |
| drop 基址 | `tools/index.html:18203,19400`；`drop/CONTRACT.md` |
| 互联复制链接用 `location.origin` | `tools/index.html:18231`（R4 修正） |
| 抽签核验链接 base | `tools/index.html:9565-9570`（R5 修正） |
| 大屏仅管理员 | `tools/index.html:18790` |
| 通知 45s 轮询 | `tools/index.html:19809` |
| token 29 天 | `tools/index.html:12994` |
| 页面版本/大小 | `var APP_VER="2.0.0"`；1,322,990 B（2026-11-16 工作区） |
| 本机环境 | .NET SDK 10.0.115；WebView2 157.0.4341.46；Office 16.0.20527；Edge 157 |
| 安卓对照 | `android-class-tools/docs/ARCHITECTURE.md`；1,534 单测；APK 3.27 MiB |
| 云端风险 | `AGENTS.md` §13（CloudBase 2026-12-10 到期）；§0-8（DNS 暂停） |
| 现有部署 | `deploy/ecs_site.py:111-160`（Caddy handles）；`deploy/sync_tools.py` |
