# 扫码登录契约（网页端 · 手机确认 / App 扫码）

> 版本 v2 · 2026-11-23 · 适用范围：`web/tools/index.html` 身份页 + ECS 账号服务 `deploy/account_app.py` v1.2
> + 安卓 App「扫一扫」（`data/scan` / `features/scan` / `ui/screens/scan`）。
>
> 需求演进：
> 1. 2026-11-22（v1）：网页端扫码登录，手机网页确认（方案 D 第一阶段）。
> 2. 2026-11-23（v2）：用户要求「扫码登录为所有手机共有能力，鸿蒙登录做独立选项；其他安卓品牌统一扫码后登录；
>    安卓 App 新增扫码按键，用于抽签结果核验和扫码登录」——网页去掉 OPPO 品牌分段（改为「通用 / 鸿蒙」），
>    安卓 App 直接扫网页二维码完成登录或抽签存证核验。

## 1. 目标与边界

- **通用扫码（所有手机）**：电脑网页点「扫码登录」→ 任何手机相机/浏览器扫码 → 手机网页用**班级身份**确认
  （已登录一键确认，否则学号 + 姓名）→ 电脑自动进入班级。**不再区分 OPPO/其他安卓品牌**。
- **鸿蒙独立选项**：弹层保留「鸿蒙」分段，二维码带 `&p=harmony`；手机确认页显示「鸿蒙手机」。
  真正的华为 Account Kit 官方扫码授权（AGC `client_secret` + 能力申请）仍未接入，接入后可在该分段直连（见 §8）。
- **安卓 App 扫一扫**：同一个扫码入口支持两类二维码：
  1. 网页登录二维码 `#qr=<ticket>[&p=harmony]` → App 用本机班级 token 调 `/qr/authorize`（`via:"app"`），
     电脑端无需手机网页即可自动登录；App 不接收 token。
  2. 抽签存证二维码 `#verify=<recordId>` → App 调 `rpc/draw_record_get`，在本机做 SHA-256(canon) 与
     draw-v1 复算，展示「哈希 ✓/✗」「复算 ✓/✗」。
- 不在本契约内：OPPO 官方没有公开的网页/PC 扫码能力；华为官方扫码授权需要 AGC 服务端凭证（未接入，见 §8）。

## 2. 角色与流程

```
电脑网页                       ECS /account                     手机
   │ POST /qr/create {p} ────────▶ 生成 t(128bit) + k(128bit)
   │ ◀──── {t,k,ttl,exp}          票据存内存（180s）
   │ 画二维码（只含 t / p）
   │                               │ ◀── 手机网页 #qr=<t>[&p=harmony]
   │                               │     已登录 → 一键确认；未登录 → 学号+姓名
   │                               │     或：安卓 App「扫一扫」直接确认
   │                               │ ◀── POST /qr/authorize {t,p,via} + X-Class-Token
   │                               │     whoami → class_verify 另签 30 天 token → 写票据 state=ok
   │ GET /qr/poll?t&k ────────────▶│
   │ ◀──── {status:ok, token,...}  │
   │ enterClass(token,sid,name,role,badge,is_admin)
```

抽签核验：

```
网页抽签记录/导出图二维码 → https://tool.furina.fun/#verify=<recordId>
安卓 App 扫一扫 → POST rpc/draw_record_get {p_id} → 本地 SHA-256 + draw-v1 → 核验结果页
```

状态机：`wait`（默认）→ `ok`（手机确认）｜`deny`（手机取消）｜`expired`（超过 TTL）。
`wait` 期间桌面每 1.2s 轮询；`expired` 自动建新票并重画；`ok` 后停止轮询。

## 3. URL 与二维码

- 通用登录二维码：`<当前页面 origin+pathname>#qr=<32 位小写 hex>`（**不带 `p`**）。
- 鸿蒙登录二维码：`<当前页面 origin+pathname>#qr=<32 位小写 hex>&p=harmony`。
  - 只包含票据 `t`；**不包含** token、轮询密钥 `k`、学号、姓名。
  - 历史 `p=oppo` / `p=honor` 一律按通用处理（兼容旧二维码）。
  - 链接超过 128 字符时省略 `&p=`（`qrGen` 上限 134 字节，防止二维码被截断）。
- 抽签存证二维码：`https://tool.furina.fun/#verify=<recordId>`（`d` + 8..31 位 `[0-9a-z]`）。
- 手机页面读取 hash 后立即 `history.replaceState` 去掉 hash（不把票据留在地址栏/历史里）。
- 票据 `t`、轮询密钥 `k` 都是 `secrets.token_hex(16)`（128-bit）；`k` 只在创建响应里返回一次。

## 4. ECS 接口（`/account/*` → 127.0.0.1:8094）

所有响应 `Content-Type: application/json; charset=utf-8`、`Cache-Control: no-store`；
`/qr/*` 额外返回 `Access-Control-Allow-Origin: *`（无 Cookie，凭据只在 header/body），
并支持 `OPTIONS` 预检（`X-Class-Token, X-Device-Id, Content-Type`，Max-Age 600）。

### 4.1 `POST /qr/create`

请求：`{"p":"any|harmony|"}`（可空；`any`/空 = 通用）
响应：`{"ok":true,"t":"<32hex>","k":"<32hex>","ttl":180,"exp":<epoch 秒>}`
服务端归一：`harmony` 保留，其余（any/空/历史 oppo/honor）一律记为通用 `""`。

### 4.2 `GET /qr/poll?t=<t>&k=<k>`

| 情况 | HTTP | 响应 |
|---|---|---|
| 正常等待 | 200 | `{"ok":true,"status":"wait"}` |
| 手机已确认 | 200 | `{"ok":true,"status":"ok","token","sid","name","role","badge","is_admin","provider","via"}` |
| 手机取消 | 200 | `{"ok":true,"status":"deny"}` |
| 票据过期/不存在 | 200 | `{"ok":true,"status":"expired"}` |
| 缺参 | 400 | `{"ok":false,"code":"bad_request"}` |
| `k` 不匹配 | 404 | `{"ok":false,"code":"not_found"}` |
| 限频 | 429 | `{"ok":false,"code":"rate_limited"}` |

`status=ok` 在票据过期前可重复读取（网络抖动重试安全）；同一份 token 不会因为重复轮询变化。
`provider` 为 `""`（通用）或 `"harmony"`；`via` 为 `"web"` 或 `"app"`。

### 4.3 `POST /qr/authorize`（需 `X-Class-Token` 或 `X-Device-Id`）

请求：`{"t":"<32hex>","p":"any|harmony|","via":"web|app"}`
成功：`{"ok":true,"name":"<姓名>"}`（**不返回 token**，避免手机端把新 token 暴露在任何地方）
失败：
- 401 `{"ok":false,"code":"unauthorized"}`（token 无效/过期）
- 200 `{"ok":false,"code":"ticket_expired"}`（票据过期，提示电脑刷新）
- 200 `{"ok":false,"code":"verify_failed"}`（`class_verify` 失败）
- 400 `{"ok":false,"code":"bad_request"}`（缺 `t`）
- 已确认过的票据：`{"ok":true,"name":...,"already":true}`（幂等）

服务端流程：`class_whoami(token)` 取 sid/name → `class_verify(sid,name)` 另签一份 30 天班级 token
→ 写入票据（`state=ok`，含 `role/badge/is_admin`）→ 发起端轮询取走。手机自己的 token 不写入票据。
安卓 App 与手机网页共用本接口，区别仅在 `via:"app"`（只作统计/排障，不改变鉴权）。

### 4.4 `POST /qr/deny`（需 `X-Class-Token`）

请求：`{"t":"<32hex>"}` → `{"ok":true}`；只把票据标记为 `deny`，不删除。

### 4.5 限频 / 容量 / 日志

- 建票 12 次/分/IP；轮询 240 次/分/IP；授权/取消 30 次/分/IP；另有账号服务全局 30 次/分/IP 的 POST 桶。
- 票据只在 ECS 内存（`_QR`），单实例上限 2000，过期 +120s 清理；服务重启丢票（用户重扫即可）。
- 服务日志只打印 `METHOD path`（`?` 之后不打印）；**不要**给 Caddy `/account/*` 开含 query 的访问日志
  （`k` 在 poll 的 query 里）。账号服务本身不打印 `t/k/token/code`。

## 5. 安全模型

- 二维码只含票据，拍照/转发二维码 = 把「授权这次电脑登录」的机会交给别人；TTL 180s + 手机确认页
  展示将登录的班级身份（姓名）来降低误点，风险与常见扫码登录一致（必要时以后加设备指纹/确认码）。
- 轮询密钥 `k` 与票据分离：只有发起端能取走 token；光有二维码无法轮询。
- 手机/App 确认必须持有有效班级 token；服务端不信任客户端提交的任何 sid/姓名。
- 新 token 由服务端 `class_verify` 签发，`role/badge/is_admin` 与学号+姓名登录完全一致（管理员扫码后仍有管理入口）。
- CORS `*` 只用于让 OSS 直连页（https）也能跨源访问；接口不使用 Cookie/凭据，跨站调用需要先有有效 token。
- 安卓「扫一扫」的相机画面只在本机由 ZXing 解码，不拍照、不保存、不上传；权限仅在进入扫码页时申请。

## 6. 网页实现

- 模块：`tools/index.html` 内 `__QR_LOGIN_V1__`（`var QRL=...`），位于身份页启动 IIFE 之前；
  暴露只读测试探针 `window.__qrLogin`（`state()/auth()/parse()/link()`）。
- 入口：身份页「进入班级」下方的「或 · 扫码登录」按钮（点按 ≥40px）；弹层 `#qrOv` 两个分段：
  **「通用」**（默认，所有手机）和 **「鸿蒙」**（独立选项）；220×220 二维码、状态行、刷新按钮、
  关闭/Esc/点遮罩关闭。
- 手机确认页：`#qrGate`（`body.qr-locked` 显示），通用显示「手机」、鸿蒙显示「鸿蒙手机」；
  已登录显示姓名 +「确认登录」；未登录显示学号/姓名 +「登录并确认」；成功后 `body.qr-done`
  显示「已确认登录」并自动进入班级；401 时回退到学号+姓名表单。
- 二维码用页面自带 `qrGen`/`paintQr`（零依赖、零外部请求）；`APP_VER` 仍为 `2.0.0`。
- 暗色主题、360/430px 无横向溢出、`aria-live`/`aria-modal` 已在 CSS/HTML 中处理。

## 7. 安卓 App「扫一扫」（已实现）

- 入口：
  - 工作台顶部玻璃图标**扫码**（滚动后悬浮条同样有）；
  - 抽签页顶栏「扫码核验」图标；
  - 路由 `Routes.SCAN`（`ScanScreen`，NavHost push，返回即回原页）。
- 相机：CameraX 后置预览 + ZXing `MultiFormatReader(QR_CODE)` 本机解码；`CAMERA` 运行时权限，
  拒绝只影响扫码；支持手电筒开关；离页释放相机与线程。
- 分流（`QrPayloadParser`，纯 Kotlin 单测）：
  - `#qr=<32hex>[&p=harmony]` → `LoginConfirm` → 用户点「确认登录」→
    `QrLoginRepository.authorize(t, harmony, session.token)` → `POST https://tool.furina.fun/account/qr/authorize`
    `{t,p:"any|harmony",via:"app"}`；成功显示「已允许电脑登录」。
  - `#verify=<recordId>` → `DrawProofRepository.verify(id)` → `rpc/draw_record_get`；解析 params/pool/result/
    seed/canon/hash 后在本机 `DrawProofVerifier` 做 SHA-256(canon) 与 mulberry32 + Fisher–Yates 复算，
    页面展示存证编号/时间/抽签人/参数/结果/事件数与两个核验徽标。
  - 其它内容 → 「无法识别的二维码」，可重新扫描。
- 不接收、不保存任何来自电脑的 token；App 只用自己的班级 token 授权。
- 版本：源码已实现并通过编译/单测；安装包由并行会话统一发版（本次 Android 不单独提交/发布）。

## 8. 已知限制（如实）

- **OPPO 账号服务凭证仍不可用**：2026-11-22 实测 `POST /account/oppo/login` 仍返回
  `2020003 invalid_client`；本轮不再把 OPPO 作为网页登录品牌，App 的 OPPO 一键登录仍受此影响。
- **OPPO 无官方网页/PC 扫码能力**：官方只提供 Android OAuth SDK；网页端无法直接拿 OPPO authCode。
- **华为官方扫码授权登录未接入**：需要 AGC `client_secret` 与服务端「扫码授权登录」能力，
  当前 `harmony-signing/agconnect-services.json` 只有 client_id；接入后可作为 `p=harmony` 的免 App 直连通道。
- 本轮「鸿蒙」分段仍是班级身份确认，不调用华为账号 SDK；`p=harmony` 只影响文案/统计。
- 扫描登录与抽签核验都要求 App 已登录（持有有效班级 token）；未登录时先走 App 身份页。

## 9. 测试与部署

- 网页：`cd web/tools && python tests\v2_qr_login_check.py` → **34/34**（headless Edge + CDP，全 mock，0 外部请求）。
- 服务端：`cd web && python -m pytest deploy/tests/test_account_qr.py -q` → **13 passed**
  （内存票据/鉴权/CORS/过期/幂等/限频/App `via=app` 通用票据）。
- 安卓：`.\gradlew.bat :app:testDebugUnitTest --tests "com.furina.classtools.features.scan.*"
  --tests "com.furina.classtools.data.scan.*" --tests "com.furina.classtools.data.draw.DrawProofParserTest"`
  → **25 passed**（二维码解析 7 / draw-v1 复算 6 / 账号接口 8 / 存证解析 4）。
- 真实抽签存证核验（测试身份 3260799999）：`rpc/draw_record_list` → `draw_record_get` 返回
  `hash/canon/pool/result/seed`，Python 复算 `hash_ok=True / replay_ok=True`，字段与安卓解析假设一致。
- 部署：
  1. `python deploy\ecs_account.py deploy`（账号服务 v1.2；`publish_key` 本地缺失时保留 ECS 现值）
  2. `python deploy\sync_tools.py index.html`
  3. `python deploy\ecs_site.py apply`
  4. 法律页：`python deploy\sync_legal.py`
- 线上对象（2026-11-23 通用/鸿蒙版）：`index.html` **1,693,522 B / sha256
  `5e82b75ea7690ce3fe0783fac90599ad373f3b1df0bd8f1ac3d71740004cf9c4`**（OSS/ECS 同字节）。
- 部署前线上备份：`tools/_backup/index_online_20261123-2235_preScanAll.html`（同字节；含并行会话的备案/统计改动）。

## 10. 回滚

- 网页：重传上述备份并 apply（会同时回退备份之后的并行改动；本次部署前线上正是该备份）。
- 账号服务：把 `deploy/account_app.py` 回退到 v1.1 后 `python deploy\ecs_account.py deploy`；
  无数据库变更（票据纯内存）。
- 安卓：回退扫码相关源码/依赖并重新发版；CameraX/ZXing 只影响「扫一扫」入口，不改变既有功能。
