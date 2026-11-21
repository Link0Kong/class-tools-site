# 扫码登录契约（网页端 · 手机确认）

> 版本 v1 · 2026-11-22 · 适用范围：`web/tools/index.html` 身份页 + ECS 账号服务 `deploy/account_app.py` v1.2
> 需求来源：用户「尝试在网页端增加 oppo 和鸿蒙扫码一键登录」；已确认方案 D——先把网页扫码链路做完并可测，
> 二维码同时预留原生 App 接管位，App 侧后续接入即可升级为真 OPPO/华为账号一键登录。

## 1. 目标与边界

- **现在能用的链路**：电脑网页点「扫码登录」→ 手机扫码打开站内确认页 → 手机用**班级身份**确认
  （已登录则一键确认，否则学号 + 姓名）→ 电脑自动进入班级。
- **手机上的「OPPO / 鸿蒙」两个分段只是生态标签**：确定手机确认页的提示文案与后续 App 接管的目标端；
  **不调用** OPPO/华为账号 SDK，不读取 openid。
- **原生 App 接管位**：安卓/鸿蒙客户端以后认领二维码链接，用自己的班级 token 调同一个 `/qr/authorize`
  （`via:"app"`）即可；网页端不需要再改（见 §7）。
- 不在本契约内：OPPO 官方没有公开的网页/PC 扫码能力；华为 Account Kit 官方「扫码授权登录」需要
  AGC 服务端 `client_secret` 与能力申请，本轮未接入（如实记录，见 §8）。

## 2. 角色与流程

```
桌面网页                       ECS /account                    手机网页
   │ POST /qr/create {p} ────────▶ 生成 t(128bit) + k(128bit)
   │ ◀──── {t,k,ttl,exp}          票据存内存（180s）
   │ 画二维码（只含 t / p）
   │                               │ ◀── 扫码打开 #qr=<t>&p=…
   │                               │     （页面读 hash 后立即 replaceState 清掉）
   │                               │     手机：已登录 → 一键确认
   │                               │           未登录 → 学号+姓名
   │                               │ ◀── POST /qr/authorize {t,p,via} + X-Class-Token
   │                               │     whoami → class_verify 另签 30 天 token → 写票据 state=ok
   │ GET /qr/poll?t&k ────────────▶│
   │ ◀──── {status:ok, token,...}  │
   │ enterClass(token,sid,name,role,badge,is_admin)
```

状态机：`wait`（默认）→ `ok`（手机确认）｜`deny`（手机取消）｜`expired`（超过 TTL）。
`wait` 期间桌面每 1.2s 轮询；`expired` 自动建新票并重画；`ok` 后停止轮询。

## 3. URL 与二维码

- 二维码内容：`<当前页面 origin+pathname>#qr=<32 位小写 hex>[&p=oppo|harmony]`
  - 只包含票据 `t`；**不包含** token、轮询密钥 `k`、学号、姓名。
  - `p` 缺省或非法时按 `oppo` 处理；`honor` 仅作兼容保留。
  - 链接超过 128 字符时省略 `&p=`（`qrGen` 上限 134 字节，防止二维码被截断）。
- 手机页面读取 hash 后立即 `history.replaceState` 去掉 hash（不把票据留在地址栏/历史里）。
- 票据 `t`、轮询密钥 `k` 都是 `secrets.token_hex(16)`（128-bit）；`k` 只在创建响应里返回一次。

## 4. ECS 接口（`/account/*` → 127.0.0.1:8094）

所有响应 `Content-Type: application/json; charset=utf-8`、`Cache-Control: no-store`；
`/qr/*` 额外返回 `Access-Control-Allow-Origin: *`（无 Cookie，凭据只在 header/body），
并支持 `OPTIONS` 预检（`X-Class-Token, X-Device-Id, Content-Type`，Max-Age 600）。

### 4.1 `POST /qr/create`

请求：`{"p":"oppo|harmony|"}`（可空）
响应：`{"ok":true,"t":"<32hex>","k":"<32hex>","ttl":180,"exp":<epoch 秒>}`

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

### 4.3 `POST /qr/authorize`（需 `X-Class-Token` 或 `X-Device-Id`）

请求：`{"t":"<32hex>","p":"oppo|harmony|","via":"web|app"}`
成功：`{"ok":true,"name":"<姓名>"}`（**不返回 token**，避免手机端把新 token 暴露在任何地方）
失败：
- 401 `{"ok":false,"code":"unauthorized"}`（token 无效/过期）
- 200 `{"ok":false,"code":"ticket_expired"}`（票据过期，提示电脑刷新）
- 200 `{"ok":false,"code":"verify_failed"}`（`class_verify` 失败）
- 400 `{"ok":false,"code":"bad_request"}`（缺 `t`）
- 已确认过的票据：`{"ok":true,"name":...,"already":true}`（幂等）

服务端流程：`class_whoami(token)` 取 sid/name → `class_verify(sid,name)` 另签一份 30 天班级 token
→ 写入票据（`state=ok`，含 `role/badge/is_admin`）→ 发起端轮询取走。手机自己的 token 不写入票据。

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
- 手机确认必须持有有效班级 token；服务端不信任客户端提交的任何 sid/姓名。
- 新 token 由服务端 `class_verify` 签发，`role/badge/is_admin` 与学号+姓名登录完全一致（管理员扫码后仍有管理入口）。
- CORS `*` 只用于让 OSS 直连页（https）也能跨源访问；接口不使用 Cookie/凭据，跨站调用需要先有有效 token。

## 6. 网页实现

- 模块：`tools/index.html` 内 `__QR_LOGIN_V1__`（`var QRL=...`），位于身份页启动 IIFE 之前；
  暴露只读测试探针 `window.__qrLogin`（`state()/auth()/parse()/link()`）。
- 入口：身份页「进入班级」下方的「或 · 扫码登录」按钮（点按 ≥40px）；弹层 `#qrOv`（OPPO/鸿蒙分段、
  220×220 二维码、状态行、刷新按钮、关闭/Esc/点遮罩关闭）。
- 手机确认页：`#qrGate`（`body.qr-locked` 显示），已登录显示姓名 + 「确认登录」；未登录显示学号/姓名 +
  「登录并确认」；成功后 `body.qr-done` 显示「已确认登录」并自动进入班级；401 时回退到学号+姓名表单。
- 二维码用页面自带 `qrGen`/`paintQr`（零依赖、零外部请求）；`APP_VER` 仍为 `2.0.0`。
- 暗色主题、360/430px 无横向溢出、`aria-live`/`aria-modal` 已在 CSS/HTML 中处理。

## 7. 原生 App 接管位（方案 D 的 B 部分，后续）

1. 安卓：已声明 `classtools://com.furina.classtools/...`，可识别 `.../qr?t=<t>&p=oppo`；
   鸿蒙：需在 `module.json5` 增加 uri scheme / App Linking 后识别同一路径。
2. App 内若已有班级 token：直接 `POST /account/qr/authorize {"t":t,"p":"oppo|harmony","via":"app"}`
   （头 `X-Class-Token`）；若未登录：先走现有 OPPO/华为账号一键登录拿到班级 token，再授权。
3. 成功后 App 提示「已允许电脑登录」，网页端无需改动。
4. 二维码链接保持不变；App 可注册 App Link 直接接管 https 链接，或在手机确认页增加「在 App 中确认」按钮
   （本轮未加，避免出现死按钮）。

## 8. 已知限制（如实）

- **OPPO 账号服务凭证仍不可用**：2026-11-22 实测 `POST /account/oppo/login` 仍返回
  `2020003 invalid_client`，所以即使 App 接管，OPPO 账号换 openid 也会失败；需先在 OPPO 开放平台
  开通「账号服务」并更新 `briefdesk/secrets/oppo-account.json` 后重新部署。
- **OPPO 无官方网页/PC 扫码能力**：官方只提供 Android OAuth SDK；网页端无法直接拿 OPPO authCode。
- **华为官方扫码授权登录未接入**：需要 AGC `client_secret` 与服务端「扫码授权登录」能力，
  当前 `harmony-signing/agconnect-services.json` 只有 client_id；接入后可作为独立 `p=harmony` 直连通道
  （无需装 App），届时再扩展 `/qr/*` 的 provider 分支。
- 本轮的 OPPO/鸿蒙标签不改变身份来源：仍是班级 token（服务端 `class_verify`）。

## 9. 测试与部署

- 网页：`cd web/tools && python tests\v2_qr_login_check.py` → **34/34**（headless Edge + CDP，全 mock，0 外部请求）。
- 服务端：`cd web && python -m pytest deploy/tests/test_account_qr.py -q` → **12 passed**（内存票据/鉴权/CORS/过期/幂等/限频）。
- 线上联调（2026-11-22，测试身份 3260799999）：真实 ECS 账号服务 + 真实浏览器（本地同源代理转发 `/account`），
  桌面扫码 → 手机确认 → 桌面拿到 64 位 token，`sid=3260799999`；0 console/异常。
- 部署：
  1. `python deploy\ecs_account.py deploy`（账号服务 v1.2；`publish_key` 本地缺失时保留 ECS 现值）
  2. `python deploy\sync_tools.py index.html`
  3. `python deploy\ecs_site.py apply`
- 线上对象：`index.html` **1,396,970 B / sha256 `0325a8a4cd1e31f547e9b60b91947defc494a03bbd8e34444cf79137dd8e96cb`**
  （OSS `check` MATCH / ECS `/` MATCH，gzip 433,152B）。
- 部署前线上备份：`tools/_backup/index_online_20261122-0735_preQR.html`（1,374,596 B / `f224dce7…`）。

## 10. 回滚

- 网页：重传备份并 apply（会同时回退备份之后的并行改动；本次部署前线上正是该备份）。
- 账号服务：把 `deploy/account_app.py` 回退到 v1.1 后 `python deploy\ecs_account.py deploy`；
  或只 `systemctl restart class-tools-account` 不部署（旧进程仍是新代码，不做代码回退不会恢复 v1.1）。
- 数据库无变更（票据纯内存），无需 SQL 回滚。
