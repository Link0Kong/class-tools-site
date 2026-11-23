# 通知附件外置 · 签名 URL 契约（v1，2026-11-10）

> 迁移第 2 步：把 `public.notices.body` 里的 base64 `data:` URI 附件搬到 ECS 私有存储，
> 云端只保留**签名 HTTPS URL**。目标：通知接口体积 8.05 MB → ~0.17 MB，且不牺牲班级隐私。
> 三端（网页 / 微信小程序 / 安卓）必须同时兼容「data URI」与「URL」两种形态；旧数据永远可读。

## 1. URL 形态

```
https://tool.furina.fun/att/<id>?exp=<unix秒>&sig=<hex64>
```

- `<id>` = 文件字节 sha256 的前 32 位小写十六进制（内容寻址、不可枚举、同内容天然去重）。
- `sig` = `HMAC-SHA256(key, "<id>\n<exp>")` 的 hex；`key = sha256(CLOUD_SYNC_TOKEN + "|att-v1")`（服务端/客户端同源推导，无新增密钥分发）。
- `exp` = Unix 秒；默认 **180 天**，每次通知同步（`sync_notices_cloud.py` 重建）重新签名。
- 正式基址 `https://tool.furina.fun/att/...`（2026-11-23 备案 + HTTPS 已启用，调试仍可用 `ATT_BASE_URL` 覆盖）；三端代码只判断 `^https?://`，**不写死域名**。
- GET 不需要任何请求头/cookie；`<img>` / `<a download>` / `wx.downloadFile` / OkHttp 均可直接取。

## 2. 云端字段（只动三处）

| 场景 | 字段 | 外置后 |
|---|---|---|
| 通知图片 | `items[].src` | 签名 URL |
| 通知文件 | `items[].url` | 签名 URL |
| 压缩包内文件 | `items[].archive.files[].url` | 签名 URL（包内小文件逐个签名） |
| 外链/收集表/公众号/小程序 | `realUrl` / `url`（link/article/mini） | **不动**（本来就是外链） |
| 文件大小 | `items[].size` | 已有人类可读字符串（如 `82 KB`）；三端在 URL 形态下优先用它，禁止显示 `0 B` |

服务端返回头：`Content-Type` 按上传时登记；`Content-Disposition: inline`（图片/PDF/音视频）或 `attachment`；
`Cache-Control: public, max-age=31536000, immutable`（内容寻址不可变）；支持 `Range`（PDF/大文件分段）。

## 3. 服务端（ECS）

| 项 | 值 |
|---|---|
| 代码 | `web/attachments/common.py` + `server.py`（纯标准库）→ ECS `/opt/class-tools/att-code/` |
| 数据 | `/opt/class-tools/attachments/<id>` + `<id>.json`（name/mime/size/ts） |
| 进程 | systemd `class-tools-att.service`，`User=www-data`，`127.0.0.1:8091`，`Restart=always` |
| 环境 | `EnvironmentFile=/etc/briefdesk-board.env`（复用 `SYNC_TOKEN`；**不新增密钥**） |
| 路由 | Caddy `handle /att/* { reverse_proxy 127.0.0.1:8091 }`（HTTP 与 HTTPS 配置都含） |
| 上传 | `POST /att/upload`，头 `X-Sync-Token`（= SYNC_TOKEN）、`X-Att-Name`、`X-Att-Mime`，body 原始字节；单文件上限 25 MB |
| 下载 | `GET /att/<id>?exp=&sig=`；签名错/过期 → 403；文件不存在 → 404 |
| 健康 | `GET /att/healthz` → `{"ok":true,"attachments":N,"auth":true}` |
| 备份 | 目录内是普通文件；建议随 ECS 快照/`tar` 定期备份（附件为可再生+内容寻址，风险低） |

## 4. 本机管线

`C:\briefdesk\scripts\sync_notices_cloud.py`（本机数据管线）在把 board-data 推到 CloudBase 前：

```
NOTICE_ATTACH_EXTERNALIZE=1   # 开启（默认关闭；2026-11-23 备案已通过，等四端新版发布后打开）
ATT_BASE_URL=https://tool.furina.fun   # 可选；默认即正式域名（备案 2026-11-23 已通过）
```

- 开启后：解析 `items` 三处 data URI → 上传（同内容去重）→ 替换为签名 URL → 再写云端；**上传失败保留 data URI（fail-open）**，不会让通知丢失。
- 关闭时行为与现在完全一致。
- 存量 41 个附件无需单独迁移：开启后下一次 `sync_notices_cloud.py`（detect_docs 重建时自动跑）会把 95 条 `auto_*` 通知整体重写，自动回填。
- 手工通知（`owner` 为学号的行）的 `attachments` 字段当前为空；若以后手工上传附件，需要同样走外置（后续增量）。

## 5. 三端兼容要求（已实现/待发布）

| 端 | 现状 | 说明 |
|---|---|---|
| 网页 | ✅ 已实现（模板 v2.1，2026-11-10 部署 802,355 B / sha `e40571d3…`） | 图片/文件行/预览弹层均兼容 URL；`dataUriBytes` 仅对 data URI 生效 |
| 微信小程序 | ✅ 已完成（2026-11-10，task-4） | `nt.js` 增加 URL 分支：图片直连、`wx.downloadFile`→`openDocument`、大小用 `it.size`、`fileType` 兜底；`unit.js` **305/0**（新增 8 条 URL 用例）。**发布前需在微信后台把 `tool.furina.fun` 加入 downloadFile 合法域名** |
| 安卓 | ✅ 已完成（2026-11-10，task-5） | 网络图片加载（复用 pptImageLoader）+ OkHttp 下载到 cacheDir 后 FileProvider 打开；`testDebugUnitTest` **934/0**（新增 30 条）；**HTTP 明文默认被 Android 9+ 拦截，正式版必须 https** |

发布顺序（四端新版发布后，一起开）：
1. 确认 ECS 附件服务/route 正常（`/att/healthz`）。
2. `NOTICE_ATTACH_EXTERNALIZE=1` + `ATT_BASE_URL=https://tool.furina.fun`，手动跑一次 `sync_notices_cloud.py`，核对通知条数/无 403。
3. 网页重传 OSS + `ecs_site.py apply`；小程序上传发布；安卓打 `assembleRelease` 并交付 APK。
4. 观察 24h：附件 200 比例、通知接口体积、失败回退（data URI 仍可读）。

## 6. 安全与隐私

- 通知附件含班级个人信息（名单/手机号等），**不放公共 OSS**；默认存 ECS 私有目录，只经签名 URL 访问。
- 签名 URL 可被转发（180 天有效）；但 `<id>` 为内容哈希、无目录列举、无搜索入口。这是「与截图同级的可接受风险」，比 public-read 低一个量级。
- 服务端校验 `exp` + HMAC（常量时间比较）；上传必须持有 `SYNC_TOKEN`；不打印 token/内容。
- 如果未来要更严格（按 token 鉴权、防转发），可加「登录后换 cookie」层，不影响现有 URL 契约（增量）。
- 删除/清理：删除云端通知后附件不会自动删；如需回收，按 `<id>.json` 的 `ts` 做 180 天清理（后续增量）。

## 7. 测试

```powershell
# 算法/替换逻辑（无网络）
python attachments\tests\test_attachments.py          # 23 PASS / 0 FAIL
# 网页渲染（headless Edge，data URI 与 URL 双形态）
cd tools; python tests\v2_attach_url_check.py         # 9/9
# ECS 服务链路（部署脚本内含 上传→签名 GET→sha 校验；本机经 Caddy 再验一次）
python deploy\ecs_attachments.py deploy
python deploy\ecs_attachments.py probe
```

## 8. 已知边界

- 单文件上限 25 MB（通知附件实际最大 ~2 MB 级）；超大附件仍走「待获取」。
- 上传仅本机管线使用（HTTP 明文 + `X-Sync-Token` 与既有 board 推送同级；HTTPS 上线后自动走 TLS）。
- 签名 URL 过期后三端会 403；由下一次通知同步重新签名。若长期无同步，附件 URL 会在 180 天后失效（届时重跑一次同步即可）。
- 小程序 `<image>` 可直连 URL，但 `downloadFile`（保存/打开文件）需要在微信后台把 `tool.furina.fun` 加入 **downloadFile 合法域名**；`request` 域名本来就有。
