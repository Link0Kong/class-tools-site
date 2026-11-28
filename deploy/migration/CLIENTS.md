# 客户端切流配置（小程序 / 安卓）— CloudBase → ECS 自建后端（P3）

> 阶段：P3 客户端就绪；**2026-11-28 P4 生产切流已完成**（`/v1/rdb/rest/*` → ECS 自建 PostgREST）。
> 小程序 `5c5053e`（2.1.3 已发布）、安卓 `23888f4`、鸿蒙 `aa84f24`、Windows `cc21a4d` 均默认 `selfhosted`；
> `cloudbase` 档仅作 2026-12-10 到期前的回滚路径。未升级旧版客户端仍直连 CloudBase，到期后失效。
> 目标后端：ECS 自建 PostgreSQL 18 + PostgREST 13，API 路径与 CloudBase 相同。
> 关联：`PLAN.md`（总计划）、`PIPELINE.md`（本机管线）、`IMPORT.md`（P1 导入）、`CUTOVER.md`（P4 切流/回滚）。
> 红线：不读/不打印密钥（publishableKey 可引用不整段粘贴）；测试只用测试账号 `3260799999/测试账号`；
> 测试/冒烟只连 **staging**；不提交 git（Lead 统一提交）。

## 0. 三档地址

| 档位 | REST base | 用途 | 允许明文 |
|---|---|---|---|
| `cloudbase` | `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/` | **回滚档**（旧版客户端仍直连）；CloudBase 2026-12-10 到期 | 否（https） |
| `staging` | `https://tool.furina.fun/v1/rdb/rest-next/` | ECS 影子验证（P2）；仅 devtools / debug 构建 | 是（仅 debug） |
| `selfhosted` | `https://tool.furina.fun/v1/rdb/rest/` | **生产**（2026-11-28 起，Caddy → 127.0.0.1:3000） | 否（https） |

- 三档使用同一份 publishableKey（公开 anon 令牌）；自建 Caddy 在 `/v1/rdb/rest*` 路由上 `header_up -Authorization` 剥掉该头，
  客户端鉴权头逻辑无需改动（RLS 仍按 `X-Class-Token` 校验）。
- staging 路径 `/v1/rdb/rest-next/*` 与正式 `/v1/rdb/rest/*` 语义相同，只有 Caddy 路由前缀不同。

## 1. 小程序（`mp-class-tools`）

### 1.1 配置位置与切档

唯一配置：`utils/cloud-config.js` 顶部：

```js
const REST_PROFILES = {
  cloudbase:  'https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/',
  staging:    'https://tool.furina.fun/v1/rdb/rest-next/',
  selfhosted: 'https://tool.furina.fun/v1/rdb/rest/'
};
const ACTIVE_REST_PROFILE = 'selfhosted';   // ← 2026-11-28 生产；回滚改 'cloudbase'（CloudBase 2026-12-10 到期）
```

- `restBase` 由 `resolveRestBase(ACTIVE_REST_PROFILE)` 计算（`module.exports.restBase` 仍与旧版同名字段兼容）；
  另有只读探针 `restProfile/restProfiles/resolveRestBase`。
- 切 staging（仅 devtools 冒烟）：`ACTIVE_REST_PROFILE = 'staging'`；
- 生产（2026-11-28 已切）：`ACTIVE_REST_PROFILE = 'selfhosted'`；
- 回滚：改回 `'cloudbase'` 重新上传发布。

### 1.2 开发期 http/IP 说明（devtools）

- 微信开发者工具：右上角「详情 → 本地设置」勾选 **「不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书」**
  后，devtools 可直接请求 `https://tool.furina.fun/v1/rdb/rest-next/`（体验版/正式版不允许 http + IP）。
- 运行时也可在 devtools console 临时切档（不改源码，结束即失效）：
  ```js
  require('./utils/cloud.js').configure({ restBase: 'https://tool.furina.fun/v1/rdb/rest-next/', restProfile: 'staging' });
  ```
- 真机调试（staging）不可用 http IP；正式域名 HTTPS 已于 2026-11-23 启用，`selfhosted` 档可用（P4 切流前 REST 仍 cloudbase）。

### 1.3 发布前微信后台配置（P4）

- 小程序后台 → 开发管理 → 开发设置 → 服务器域名：**request 合法域名** 增加 `https://tool.furina.fun`
  （通知附件/PPT 媒体如需 `downloadFile` 再增加 downloadFile 合法域名；drop 云空间同域）。
- 发布前确认 `ACTIVE_REST_PROFILE === 'selfhosted'`（2026-11-28 起生产档），然后由用户本人上传发布。
- 版本号不动（`utils/version.js` 仍 `2.0.0`）；本阶段不发布/不上传。

### 1.4 小程序网络层优化（2026-11-18，`utils/cloud.js` + `utils/cloud-config.js`）

实现（均在网络层，不改 UI/交互）：

| 能力 | 说明 |
|---|---|
| 超时分级 `timeouts` | `default=8000 / login=12000 / poll=8000 / upload=60000`（显式 `opts.timeout` 最优先）；登录 `class_verify` 用 login 档 |
| 重试 | 幂等只读请求（GET / 只读 RPC）**最多 2 次尝试**（1 次重试）：网络失败 + `502/503/504` 瞬时网关错误；退避 350ms 起、`×2^attempt + 随机抖动`；写请求永不重试 |
| 并发控制 | 全局并发上限 8（`net.maxConcurrent`）；连续失败 ≥2 次时降为 3（`net.weakMaxConcurrent`），避免把拥堵链路打爆 |
| 在途合并 | 相同 GET 并发只发 1 个请求（`net.coalesce`，`coalesce:false` 可关）；请求结束即移除，不返回旧缓存 |
| HTTP/2 | https 请求带 `wx.request.enableHttp2=true`（基础库 2.10.4+；旧基础库/自建 http staging 自动走 HTTP/1.1）；域名复用由微信网络栈保活 |
| 可观测 | `cloud.netStats()`（请求/重试/合并/排队/峰值并发）、`cloud.restInfo()`（当前档位/base；不含 token） |

**优化前后量化指标**（`mp-class-tools-tests/net_bench.js`，同机 mock 对比改动前快照 `_net_before/`，结果 `net_bench_result.json`）：

| 指标 | 前 | 后 |
|---|---|---|
| 登录（`class_verify`）1 次网络失败下的成功率 | 0% | **100%** |
| 读接口 502 瞬时网关错误成功率 | 0% | **100%** |
| 读接口「网络失败 + 502」混合抖动成功率 | 0% | **100%** |
| 登录在 80ms 高延迟下（默认档 50ms / 登录档 120ms）成功率 | 0% | **100%** |
| 10 个并发相同 GET 的请求数 | 10 | **1** |
| 定时器 + 回前台重叠触发两次 `cloudPull` 的请求数 | 11 | **8** |
| 8 个并发请求峰值并发（上限 2 时） | 8 | **2** |
| 登录后首屏 `cloudPull` 请求数（旧 base 不回退基线） | 9 | **9** |

复现：`cd %CLASS_TOOLS_ROOT%\mp-class-tools\tests; node net_bench.js`。
回归：`node unit.js` **597/0 全绿**（新增 `net_layer_tests.js` 12 项：三档配置/HTTP2/超时分级/重试/合并/并发/旧配置兼容）。

**首屏请求数评估**（登录/通知）：此前已完成的优化继续生效——通知列表走 `rpc/class_notices_meta`（~0.3MB，按需懒加载 body）、
`class_members` 单飞（登录后 warmSync + cloudPull 不再重复拉）、marks 5s 内不重复强拉、TTL/30s 轮询退避；
本次新增的在途合并让「定时器 + 回前台」重叠时同表请求再减少（11→8），首屏正常路径请求数不变（9→9，无回退）。

## 2. 安卓（`android-class-tools`）

### 2.1 配置位置与优先级

- 公开 publishableKey：`gradle.properties`（不变）。
- REST base 三档（`app/build.gradle.kts` 顶部有完整注释与默认值）：
  - 优先级（高 → 低）：`ct.restBaseUrl`（显式覆盖，**默认值 = CloudBase 不变**；只有改成非默认值时才覆盖两种 buildType）
    → `ct.restProfile`（`cloudbase|staging|selfhosted`，两种 buildType 同档）→ `ct.restBaseUrlDebug/ct.restBaseUrlRelease`
    → buildType 默认档（debug→staging / release→selfhosted）。
  - 三档地址可用 `ct.restBase.cloudbase / .staging / .selfhosted` 覆盖。
- ECS 其他服务（账号 `/account`、云空间 `/drop`、更新清单 `/android/latest.json`、地图 `/map/...`）同样按 buildType 注入：
  debug = `https://tool.furina.fun/...`；release = `https://tool.furina.fun/...`。
  显式覆盖：`ct.accountBaseUrl / ct.cloudspaceBaseUrl / ct.updateBaseUrl / ct.mapBaseUrl`。
- 构建产物字段（BuildConfig）：`REST_BASE_URL / REST_PROFILE / ACCOUNT_BASE_URL / CLOUDSPACE_BASE_URL / UPDATE_BASE_URL / MAP_BASE_URL`。

### 2.2 切档 / 回滚命令

```powershell
$env:JAVA_HOME = "C:\AndroidToolchain\jdk17"
cd %USERPROFILE%\.openclaw\workspace\android-class-tools

# debug（默认 staging：连 https://tool.furina.fun/v1/rdb/rest-next/，仅调试用）
.\gradlew.bat :app:assembleDebug

# 强制某档（两种 buildType 同档）：
.\gradlew.bat :app:assembleDebug   -Pct.restProfile=staging
.\gradlew.bat :app:assembleDebug   -Pct.restProfile=cloudbase     # 回滚 CloudBase
.\gradlew.bat :app:assembleRelease -Pct.restProfile=selfhosted    # 备案后正式切流

# 单 buildType 显式 URL：
.\gradlew.bat :app:assembleDebug   "-Pct.restBaseUrlDebug=https://tool.furina.fun/v1/rdb/rest-next/"
.\gradlew.bat :app:assembleRelease "-Pct.restBaseUrlRelease=https://tool.furina.fun/v1/rdb/rest/"

# release 安全闸门（发布前必跑；不构建 APK）：
.\gradlew.bat :app:verifyReleaseEndpoints
```

`verifyReleaseEndpoints` 断言 release 的 5 个地址全部 `https://` 且不含 `tool.furina.fun`；当前输出：
`REST_BASE_URL=https://tool.furina.fun/v1/rdb/rest/`、`ACCOUNT_BASE_URL=.../account`、`CLOUDSPACE_BASE_URL=.../drop`、
`UPDATE_BASE_URL=.../android/latest.json`、`MAP_BASE_URL=.../map/campus_final_25d.html`（REST_PROFILE=selfhosted）。

### 2.3 明文（cleartext）策略

- `app/src/main/res/xml/network_security_config.xml`（release 使用）：`cleartextTrafficPermitted=false`；
  仅保留教务 HTTP 主机 `210.34.74.77`。**不含 `tool.furina.fun`**。
- `app/src/debug/res/xml/network_security_config.xml`（仅 debug 合并）：额外放行 `tool.furina.fun`（staging REST +
  账号/云空间/更新/地图的备案前 IP 入口）。
- 因此 **release APK 不含 tool.furina.fun 明文放行**（`verifyReleaseEndpoints` + 源码资源双证据）；
  release 的 REST/ECS 地址全部 https，明文只可能在 debug 构建出现。
- 注意：release 构建的 ECS 服务地址自 2026-11-23 起一律 `https://tool.furina.fun/...`（备案已通过、证书已签发；`ct.ecsProfile` 只接受 `selfhosted`）。

### 2.4 安卓网络层优化（2026-11-18）

| 能力 | 说明 |
|---|---|
| 共享连接池/Dispatcher | 新增 `data/network/NetworkClients.kt`：**唯一** `ConnectionPool(8, 5min)` + `Dispatcher(64/16)`；REST/账号/云空间/附件下载/PPT 图片/更新检查下载全部复用（此前每个模块各自 `OkHttpClient`） |
| HTTP/2 | 所有 client 显式 `Protocol.HTTP_2, HTTP_1_1`（备案后 https 自动 h2 多路复用；staging http 走 HTTP/1.1 keep-alive） |
| 超时分级 | `ApiRequest.timeoutMs` 支持按调用设整体超时（OkHttp `Call.timeout`）；登录/身份验证档 **20s**（`ApiAuthRepository.AUTH_TIMEOUT_MS`），普通读写沿用 client 默认 60s，云空间分片 120s/10min，下载 10min |
| 重试 | GET 网络失败重试 1 次（既有契约）；**新增 502/503/504 瞬时网关错误重试 1 次**（幂等只读）；退避 350ms + 随机抖动；写请求永不重试 |
| 在途合并 | 同一会话相同 GET 并发只发 1 个 HTTP 请求（`ApiClient.get(..., coalesce=true)`；不缓存旧结果） |
| 302/重定向 | OkHttp 默认跟随（下载/更新沿用）；`retryOnConnectionFailure`：API 关闭（重试由 App 显式控制）、下载 client 开启 |
| 启动串行请求评估 | 首页各数据源已是独立 `LaunchedEffect`（课表/作业/通知/电费/标记/用户数据并行发起），无需串行化改造；PPT 列表本就用 `async` 并行；通知仓库已有 30s 超时 + 超时重试 1 次 |

**优化前后量化指标**（JVM 单测，同机本地 HTTP 服务/假传输层，无外网请求）：

| 指标 | 前 | 后 | 测试 |
|---|---|---|---|
| 3 个模块 client 顺序请求同一 host 的 TCP 连接数 | 3（每模块独立 OkHttpClient） | **1**（共享连接池） | `NetworkClientsConnectionTest` |
| GET 502 瞬时错误成功率 | 0% | **100%**（重试 1 次） | `ApiClientNetOptimizationTest` |
| 5 个并发相同 GET 的实际 HTTP 请求数 | 5 | **1**（在途合并） | `ApiClientNetOptimizationTest` |
| 登录请求整体超时档 | 60s（client 默认） | **20s**（失败更快、UI 可提示重试） | `AuthTimeoutTierTest` |
| 写请求 502 重试次数 | 0 | 0（保持不重试，避免重复写入） | `ApiClientNetOptimizationTest` |

回归：`.\gradlew.bat :app:testDebugUnitTest` **1605 项 / 0 失败 / 2 跳过**（跳过的 2 项 = 需 `CT_STAGING_SMOKE=1` 手动开启的 `StagingSmokeTest` + `PptStagingMediaSmokeTest`；新增 14 项：`AppNetConfigTest` 3、`ApiClientNetOptimizationTest` 8、
`NetworkClientsConnectionTest` 2、`AuthTimeoutTierTest` 1）。不改版本号（仍 `1.0.0-beta4` / vc87），不发布/不上传/不构建分发 APK。

## 3. 网页（Lead 负责，本文件不涉及）

网页 `tools/index.html` 的 `var CB` 字面量保留；运行时在 `tool.furina.fun` / `tool.furina.fun` 下走同源 `/v1/rdb/rest/*`
（Caddy 反代当前 CloudBase，P4 切到本地 PostgREST）。staging 调试入口 `?api=next`（见 CUTOVER.md）。

## 3b. PPT 在线媒体走 ECS `/pptfiles` 缓存（小程序/安卓，2026-11-18）

背景：PPT 媒体（分步图 WebP、缩略图、原样播放 MP4、`media_files` 单独下载音视频、下载包）存放在
阿里云 OSS 香港 `tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/**`；跨境首访很慢（实测 13.6MB 视频 35s）。
ECS `/pptfiles`（127.0.0.1:8092 + Caddy `handle /pptfiles/...`，5GiB LRU）命中后 **6–11MB/s**，支持
GET/HEAD/**Range 206**（视频边下边播可用）。网页端已于 commit `f0a829e` 上线同口径映射（真实 E2E 10/10），
本小节记录小程序/安卓的等价实现。

### 映射规则（与网页 `pptEcsUrl()/resolveMediaUrl()` 一致）

| 输入 | 输出 |
|---|---|
| `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/<path>` | ECS 缓存基址 + `/ppt/<path>`（仅此 bucket、仅 `/ppt/` 前缀） |
| `data:` / `file:` / `content:` / 本地临时路径 / 相对路径 | 原样返回 |
| 其它域名（CDN/媒体外链）或本桶非 `/ppt/` 路径（如 `/android/...`） | 原样返回 |
| 已映射的 ECS 地址 | 原样（幂等） |

- 编码路径与 `?query` 原样保留（Caddy 解码后由缓存服务按 OSS pathname 命中；`#fragment` 丢弃，与网页一致）。
- ECS 缓存基址 = web 基址 + `/pptfiles`：staging/调试期 `https://tool.furina.fun/pptfiles`；备案后
  `https://tool.furina.fun/pptfiles`（Caddy 同源反代，无需新域名/新证书）。
- 覆盖范围（两端都是"manifest 归一化/解析后统一入口"，因此播放/预览/下载/预加载/缩略图自动复用）：
  `manifest.base`、`slides[].steps[].img`、`slides[].thumb`、`video.s`、`media_files[].s`、
  `files.{compat,pdf,source}.s`、`manifest.src`、步内热点 `media[].s`（全局媒体表合并后的 url）；
  **列表/详情/播放器首帧封面 `ppt_decks.cover_url`**（2026-11-18 P4 补入，同一 helper）。

### 小程序（`mp-class-tools`）

- 实现：`utils/ppt.js` 新增纯函数 `pptEcsUrl()/pptEcsBase()/mediaUrlOf()`；`normStep/normSlide/normManifest
  (含 src 与热点 url)/normVideo/normFileRow/normMediaFile` 统一走 `mediaUrlOf` → 派生数据
  （`flatSteps/thumbList/preloadPlan/mediaRows/fileRows/downloadDetailView`）与页面（`pages/pptplay` 图片/视频/
  预加载/`wx.downloadFile` 降级链、`pages/pptdl` 下载）自动使用映射后地址，无需逐处改。
  **封面 `cover_url`（2026-11-18 P4）**：列表 `deckView()/listView()` 的 `cover`、下载详情 `downloadDetailView()` 的
  `cover`、播放器首帧 `pages/pptplay` 的 `_deck.cover_url` 也统一经 `pptEcsUrl()` 映射（只映射本桶 `/ppt/`；空/data:/外域原样）。
- 开关：`utils/cloud-config.js` 的 `pptEcs: { enabled: true, base: '' }`
  - `base: ''`（默认）= `webBase + '/pptfiles'`（`webBase` 当前 `https://tool.furina.fun`，需备案 + HTTPS）；
  - devtools/备案前调试：临时设 `base: 'https://tool.furina.fun/pptfiles'`（配合「不校验合法域名」）；
  - 回滚：`enabled: false`（恢复 OSS 直链，旧行为）。
- 单测：`mp-class-tools-tests/ppt_ecs_unit_tests.js`（6 项，已挂 `unit.js`）：映射/不映射/data:/外域/
  编码路径+query/自定义 base/回滚开关/manifest 全字段集成/**cover_url（列表/详情/播放器首帧）映射**。
- 发布注意：正式版需在微信后台把 `https://tool.furina.fun` 加入 **request 合法域名** 与 **downloadFile
  合法域名**（图片 `<image>`/视频 `<video>` 网络请求同样受域名校验；devtools 勾「不校验」即可调试 staging）。

### 安卓（`android-class-tools`）

- BuildConfig：`app/build.gradle.kts` 新增 `WEB_BASE_URL`（debug = `https://tool.furina.fun`；release =
  `https://tool.furina.fun`；可用 `-Pct.webBaseUrl=<基址>` 显式覆盖两种 buildType），
  `verifyReleaseEndpoints` 同步校验 release 的 `WEB_BASE_URL` 不含 tool.furina.fun 且为 https。
- 实现：新增 `features/ppt/PptEcsUrl.kt`（纯函数 `map(url, ecsBase)`，默认基址 = `WEB_BASE_URL + /pptfiles`）；
  `PptManifest.resolveImage()` 统一入口改为 `PptEcsUrl.map(PptUrl.resolve(base, ref))`，因此
  `thumbOf/videoUrl/fileUrl/mediaUrl/sourceUrl` 与播放器（`PptPlayerScreen`/`PptVideoPlayer`/`PptImageLoader`）、
  下载（`PptDownloadLogic`/`PptMediaDownloadLogic` → DownloadManager/OkHttp）全部走 ECS 缓存；Range 由既有
  MediaPlayer/OkHttp 自动协商（ECS 支持 206）。
  **封面 `cover_url`（2026-11-18 P4）**：`PptDeck/PptDeckDetail` 新增 `coverDisplayUrl`（= `PptEcsUrl.map(coverUrl)`），
  列表 `PptListScreen`、下载详情 `PptDownloadDetailScreen`、播放器首帧 `PptPlayerScreen` 均改用该字段（图片加载器自然复用连接池）。
- 回滚：`PptEcsUrl.ENABLED = false` 重新构建（恢复 OSS 直链）；或 `-Pct.webBaseUrl=...` 换回退基址。
- 单测：`PptEcsUrlTest`（7 项）+ `PptEcsMappingTest`（3 项）：映射/不映射/编码路径/query/自定义基址/
  回滚开关/BuildConfig 基址/真实 manifest 全字段集成/**cover_url（列表+详情）映射**；既有 `PptUrlTest`（纯 URL 解析）不回退。

### 验证证据（2026-11-18）

- ECS 缓存实测（测试账号 + 真实 staging deck `dmwalrdlgevz90l`）：
  `HEAD /pptfiles/ppt/a/dmwalrdlgevz90l/c0e5834805/s1-1.webp` → 200 `image/webp` 25,174B；
  `t1.webp` → 200 3,236B；`deck.mp4` → 200 `video/mp4` 13,668,151B；
  `Range: bytes=0-1023` → **206** 1,024B；中文媒体 `media/本草孝心_…视频1_第7页.mp4` → 200 `video/mp4` 20,158,796B。
- 网页：Lead 已实跑真实 E2E 10/10（commit `f0a829e`）。
- **小程序 devtools 冒烟 PASS**（测试账号；临时 `ACTIVE_REST_PROFILE='staging'` + `pptEcs.base='https://tool.furina.fun/pptfiles'`
  → devtools 重开编译 → 真实登录 1132ms → 列表 + 播放器）：
  列表 `pages/ppt/ppt` 封面 `cover=https://tool.furina.fun/pptfiles/ppt/a/dmwalrdlgevz90l/c0e5834805/t1.webp`（`hasCover=true`）；
  播放器 `state=ready mode=video`，首帧 `vposter=…/pptfiles/…/t1.webp`、首图 `imgA=…/pptfiles/…/s1-1.webp`、
  缩略图 `t1/t2/t3.webp`、视频 `videoUrl=…/pptfiles/…/deck.mp4`，`imgErr=false`（图片真实加载成功）；
  **9/9 检查通过**、0 exception。存档 `mp-class-tools-tests/staging_smoke_ppt_result.json`。
- **安卓 debug 构建冒烟 PASS**（`CT_STAGING_SMOKE=1` 跑 `PptStagingMediaSmokeTest`，真实 staging deck）：
  manifest 16 页；`img=…/pptfiles/ppt/…`、`video=…/pptfiles/ppt/…`、`cover=…/pptfiles/ppt/…`；
  对 ECS 真实请求 **封面/图片 HEAD 200（image/webp）** 与 **Range GET 206**（`bytes=0-1023`，video/mp4），输出
  `PPT_STAGING_MEDIA_SMOKE_OK slides=16 img=https://tool.furina.fun/pptfiles/ppt/… video=… cover=… range=206 base=https://tool.furina.fun`。
- 工程回归：mp `node unit.js` **597/0 全绿**（`ppt_ecs_unit_tests.js` 6 项）；安卓 `:app:testDebugUnitTest`
  **1605 项 / 0 失败 / 2 跳过**（`PptEcsUrlTest` 7 + `PptEcsMappingTest` 3 + `PptStagingMediaSmokeTest` 1）；
  安卓 `:app:verifyReleaseEndpoints` OK。
- 小程序 devtools / 安卓 debug 构建的 PPT 预览冒烟见 §4.3。

### 已知边界

1. 封面 `cover_url`（DB 字段，2026-11-18 P4 已接入）：小程序的 `deckView/listView/downloadDetailView` 的 `cover` 与
   播放器首帧 `_deck.cover_url`、安卓的 `PptDeck/PptDeckDetail.coverDisplayUrl`（列表/下载详情/播放器）均走同一 helper；
   `cover_url` 为空/data:/外域时原样（列表显示占位图）。注意 `cover_url` 实际值可能是 `cover.webp` 或首图（如 t1.webp），
   规则按整条 URL 的桶/路径判断，两种都会命中 `/pptfiles/**`。
2. OSS 直链仍是回滚路径；ECS 缓存不可用时切 `pptEcs.enabled=false`/`PptEcsUrl.ENABLED=false` 重新发布。
3. 小程序正式版需域名白名单（request + downloadFile）；安卓 release 明文策略见 §2.3（ECS http 调试入口只在 debug）。
4. ECS `/pptfiles` 为 5GiB LRU 单实例缓存；大文件首访仍需回源 OSS（后台预热可提前命中）。

## 4. staging 冒烟（P1 就绪后；仅 staging、仅测试账号）

前置：`/v1/rdb/rest-next/` 已导入 schema+数据（`class_verify` 等 RPC 可用）。冒烟**只读**：登录 + 名单 + 通知/作业/课表快照，
不写任何业务数据。

### 4.1 小程序 devtools 冒烟（实测可行流程）

```powershell
$mp = "%USERPROFILE%\.openclaw\workspace\mp-class-tools"
$cli = "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat"

# 1) 关闭工程 → 把 ACTIVE_REST_PROFILE 临时改为 'staging' → 重开（保证 devtools 用 staging 编译）
& $cli close --project $mp
#    编辑 $mp\utils\cloud-config.js：const ACTIVE_REST_PROFILE = 'staging';
& $cli auto --project $mp --auto-port 9420 --trust-project

# 2) 运行冒烟（脚本先校验配置档位 + staging class_verify 200，否则拒绝运行；结束清空 devtools storage）
cd %CLASS_TOOLS_ROOT%\mp-class-tools\tests
node staging_smoke_mp.js

# 3) 收尾：把 ACTIVE_REST_PROFILE 改回 'cloudbase'，并关闭 devtools
& $cli quit
```

脚本断言：配置档位 = staging + staging `class_verify` 200 → 身份页真实登录（`class_verify` + `class_members`，测试账号）→
首屏 warm sync（marks/homework/notices/userdata）→ 通知页 / 课表快照 / 作业页真实读；输出 `loginMs`、名单人数、同步键、
页面状态（不含 token/姓名），并存档 `staging_smoke_result.json`。
**devtools 需勾选「不校验合法域名」**（staging 为 http + IP）。注意 devtools 的 `Page.callMethod` 在本环境不可用，
脚本统一用 `mp.evaluate(getCurrentPages()[last] / wx.*)` 调页面方法与读 storage。

### 4.2 安卓 debug 构建冒烟

```powershell
$env:JAVA_HOME = "C:\AndroidToolchain\jdk17"
$env:CT_STAGING_SMOKE = "1"
cd %USERPROFILE%\.openclaw\workspace\android-class-tools
.\gradlew.bat :app:testDebugUnitTest --tests "*StagingSmokeTest*" --info
```

`StagingSmokeTest` 用 debug 构建（`REST_BASE_URL` = staging）真实请求：`rpc/class_verify`（测试账号）→ `rpc/class_members` →
`notices/homework/site_assets` 只读；开头断言 `REST_PROFILE=staging` 且 base 是 `https://tool.furina.fun/v1/rdb/rest-next/`（防误连生产）。
默认跳过（不设 `CT_STAGING_SMOKE` 时 `Assume` 跳过），不影响常规 `testDebugUnitTest` 全绿。

### 4.3 冒烟结果（2026-11-18，P1 staging 导入完成后实跑 PASS）

| 项 | 结果 |
|---|---|
| 小程序 devtools（真实登录 + 读） | **PASS**：`ACTIVE_REST_PROFILE` 临时切 `staging` → devtools 重开编译 → 测试账号真实登录 **1300ms** → `pages/index/index`；名单 **70 人**；首屏同步键 `members/tt/marks/nt/ud/hw/fit`；通知页 `ready` **26 卡**（`云端已同步`、长期 1）；课表 `data` **32 门**（`教务 11/18 07:05`）；作业页 `data`；0 exception；9/9 检查通过。存档 `mp-class-tools-tests/staging_smoke_result.json`，脚本 `staging_smoke_mp.js` |
| 安卓 debug 构建（真实登录 + 读） | **PASS**：`CT_STAGING_SMOKE=1` 跑 `StagingSmokeTest`（debug BuildConfig = staging，真实网络）：`class_verify` 122ms、`class_members` 26ms（**70 人**）、notices 30ms、homework 23ms、site_assets 24ms；`STAGING_SMOKE_OK base=https://tool.furina.fun/v1/rdb/rest-next/ members=70` |
| 小程序 devtools（PPT 在线媒体 + 封面 → /pptfiles，2026-11-18） | **PASS**：`ACTIVE_REST_PROFILE='staging'` + `pptEcs.base='https://tool.furina.fun/pptfiles'` → devtools 重开 → 测试账号登录 1132ms → 列表封面 `…/pptfiles/ppt/a/dmwalrdlgevz90l/c0e5834805/t1.webp`（`hasCover=true`）→ 打开 staging deck `dmwalrdlgevz90l` 播放器：`state=ready mode=video`，首帧 `vposter`/首图/缩略图/原样播放视频 URL 均为 `https://tool.furina.fun/pptfiles/ppt/a/…`；`imgErr=false`；**9/9 检查通过**。存档 `mp-class-tools-tests/staging_smoke_ppt_result.json`，脚本 `staging_smoke_ppt_mp.js` |
| 安卓 debug 构建（PPT 媒体 + 封面 → /pptfiles，2026-11-18） | **PASS**：`PptStagingMediaSmokeTest`（CT_STAGING_SMOKE=1）真实读 staging deck manifest（16 页）→ 映射后对 ECS `/pptfiles` **封面/图片 HEAD 200（image/webp）**、**Range GET 206**（video/mp4）；输出 `PPT_STAGING_MEDIA_SMOKE_OK slides=16 img=…/pptfiles/ppt/… video=… cover=… range=206` |
| 冒烟前置校验（脚本内） | 配置档位必须为 `staging` + staging `class_verify` 200，否则脚本拒绝运行（不可能误连 CloudBase/生产）；PPT 冒烟额外校验 `pptEcs.base` 为 ECS IP |
| 清理 | 冒烟结束清空 devtools 本机 storage；`utils/cloud-config.js` 已改回 `'cloudbase'` + `pptEcs.base=''`；devtools 已退出 |

复跑命令见 §4.1/§4.2；结果文件：`staging_smoke_result.json`（小程序）、安卓测试 XML 的 `<system-out>`（`STAGING_SMOKE_OK ...`）。

## 5. P4 发布步骤（按顺序；备案 + HTTPS 已于 2026-11-23 就绪）

1. **服务端就绪**：DNS `tool` A → `121.196.47.2`（2026-11-23 已切）→ `python deploy\ecs_site.py apply`（Caddy HTTPS/HTTP2，
   Let's Encrypt）→ `curl -I https://tool.furina.fun/` 200、证书有效。
2. **服务端切流**：按 `CUTOVER.md` §1 把 `/v1/rdb/rest/*` 切到本地 PostgREST（保留 `header_up -Authorization`），
   staging `/v1/rdb/rest-next/*` 可保留观察或删除。
3. **P4 服务端配套（三端相关）**：
   - ECS `/android/latest.json` 的 `apkUrl` 改为 `https://tool.furina.fun/android/...`（release 不再放行明文 IP 下载）；
   - 通知附件外置 `NOTICE_ATTACH_EXTERNALIZE=1` + `ATT_BASE_URL=https://tool.furina.fun`（附件 URL 改为域名，三端已兼容双形态）；
   - PPT 媒体/下载链接域名化（`/pptfiles`、`/pptmedia/*`，三端按同域地址使用）；
   - 账号服务 `/account`、drop `/drop`、地图 `/map/*` 均由 Caddy 同域提供（客户端 release 默认已用域名）。
4. **小程序**：`utils/cloud-config.js` 的 `ACTIVE_REST_PROFILE` 改 `'selfhosted'` → `node unit.js` 全绿 → 微信后台
   request（必要时 downloadFile）合法域名加 `https://tool.furina.fun` → 用户本人上传发布 → 真机验证登录/通知/投票/PPT。
5. **安卓**：`.\gradlew.bat :app:verifyReleaseEndpoints` 必过 → `.\gradlew.bat :app:assembleRelease`（新增签名/版本号由 Lead 决定）
   → 分发 → 真机验证（登录/通知/更新检查/云空间/地图/PPT 下载）。
6. **网页**：Lead 按 CUTOVER.md 部署（OSS + ECS 同步）。
7. **观察 30–60 分钟**：三端错误率、PostgREST 5xx、PG 连接数；CloudBase 保留 ≥2 周回滚窗口。
8. **双远端提交**：所有源码/文档改动由 Lead 统一 `sync-repos.cmd` 提交推送（本文件与 mp/android 源码改动一起）。

## 6. 回滚

| 端 | 回滚动作 |
|---|---|
| 小程序 | `ACTIVE_REST_PROFILE = 'cloudbase'` → 重新上传发布（旧线上版本本身仍连 CloudBase，不受影响） |
| 安卓 | debug：`-Pct.restProfile=cloudbase` 或改回 `ct.restProfile=cloudbase`；release：上一版 APK 仍连 CloudBase（重装即可） |
| P4 服务端 | `python deploy\ecs_cutover.py rollback`（Caddy 路由回 CloudBase）+ `python deploy\ecs_pg.py switch-db --db class_tools`（如需） |
| 冒烟失败 | 不发布；记录错误，先修 staging/服务端；客户端源码无副作用（默认档不变或可一键回滚） |

## 7. 已知边界 / 风险

1. **staging 为 http + IP**：真机/体验版/正式版都不用它（只 devtools / debug 构建）。**正式域名 https 已于 2026-11-23 可用**。
2. **安卓 release ECS 服务**：自 2026-11-23 起一律 https 正式域名（`ct.ecsProfile=selfhosted` 为唯一档）；REST 仍 cloudbase 直到 P4 切流。
3. **网络优化边界**：重试只覆盖幂等只读请求，写请求不重试（防重复写入）；并发上限只影响异常突发，不改变正常首屏请求数（9→9）。
   安卓共享连接池只复用**同一主机**的连接（staging IP / 正式域名各自成池）。
4. **通知附件/PPT 媒体**：三端已支持 http(s) URL 与旧 data URI 双形态；P4 切域名后由服务端改 URL 形态，客户端无需再改（小程序需
   downloadFile 合法域名）。
5. **版本号**：本阶段不改版本号、不发布/不上传、不构建分发 APK；发布动作由用户在 P4 执行。

## 8. 改动清单（2026-11-18）

- 小程序：`utils/cloud-config.js`（三档 + 超时分级 + 网络参数）、`utils/cloud.js`（超时分级/重试增强/502-503-504 重试/并发闸门/
  在途合并/HTTP2/`restInfo`+`netStats` 探针）；测试：`mp-class-tools-tests/net_layer_tests.js`（12 项，已挂 `unit.js`）、
  `net_bench.js` + `net_bench_result.json`、`staging_smoke_mp.js`。
- 安卓：`gradle.properties`（档位注释/属性）、`app/build.gradle.kts`（buildType 注入 + `verifyReleaseEndpoints` 闸门）、
  `data/network/NetworkClients.kt`（新）、`HttpTransport.kt`、`ApiClient.kt`、`ApiAuthRepository.kt`、`CloudSpaceModels.kt`、
  `CloudSpaceTransport.kt`、`NoticeAttachmentFiles.kt`、`UpdateChecker.kt`、`UpdateDownloader.kt`、`UpdateLogic.kt`、
  `ui/screens/map/CampusMapScreen.kt`、`res/xml/network_security_config.xml`、`src/debug/res/xml/network_security_config.xml`（新）；
  测试：`AppNetConfigTest`、`ApiClientNetOptimizationTest`、`NetworkClientsConnectionTest`、`AuthTimeoutTierTest`、`StagingSmokeTest`。
- **2026-11-18 PPT 在线媒体 ECS `/pptfiles` 映射（task-10）**：
  - 小程序：`utils/ppt.js`（新增 `pptEcsUrl/pptEcsBase/mediaUrlOf` + `normStep/normSlide/normManifest/normVideo/
    normFileRow/normMediaFile` 全部映射）、`utils/cloud-config.js`（`pptEcs:{enabled,base}` 开关）、
    `pages/pptplay/pptplay.js`（注释）；测试：`mp-class-tools-tests/ppt_ecs_unit_tests.js`（5 项，已挂 `unit.js`）、
    `staging_smoke_ppt_mp.js` + `staging_smoke_ppt_result.json`。
  - 安卓：`app/build.gradle.kts`（新增 `WEB_BASE_URL` buildType 注入 + `verifyReleaseEndpoints` 校验）、
    `gradle.properties`（`ct.webBaseUrl` 覆盖说明）、`features/ppt/PptEcsUrl.kt`（新）、`data/ppt/PptModels.kt`
    （`resolveImage` 统一映射入口）；测试：`PptEcsUrlTest` 7、`PptEcsMappingTest` 3、`PptStagingMediaSmokeTest` 1。
- **2026-11-18 PPT 封面 `cover_url` 走 ECS `/pptfiles`（task-11，与网页本轮对齐）**：
  - 小程序：`utils/ppt.js`（`deckView`/`downloadDetailView` 的 `cover` 经 `pptEcsUrl`）、
    `pages/pptplay/pptplay.js`（首帧 `_deck.cover_url` 经 `ppt.pptEcsUrl`）；测试：`ppt_ecs_unit_tests.js`
    新增 C3 用例（列表/详情/播放器首帧 + data:/外域/空原样 + 静态接线；6 项）。
  - 安卓：`data/ppt/PptModels.kt`（`PptDeck/PptDeckDetail.coverDisplayUrl` = `PptEcsUrl.map(coverUrl)`）、
    `ui/screens/ppt/{PptListScreen,PptDownloadDetailScreen,PptPlayerScreen}.kt` 改用展示字段；
    测试：`PptEcsUrlTest`（cover 用例）、`PptEcsMappingTest`（列表/详情 cover 集成）、`PptStagingMediaSmokeTest`
    （真实 staging cover HEAD 200 image/webp）。
- 本文件由客户端工程师（client-dev）维护；P1/P4 执行状态变化时更新 §4/§5。
