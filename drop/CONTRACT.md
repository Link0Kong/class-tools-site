# 大屏临时互联通道 · 服务契约 v1（ECS `drop` 服务）

> 2026-11-11 建立（task-5）。用途：团日活动大屏与手机/其它设备**同账号临时互联**——
> 跨端传文件、发文字、遥控指令中转，会话 2 小时后自动销毁，文件不长期保存。
>
> - 服务：`deploy/drop_app.py`（Python 标准库，**127.0.0.1:8093**），systemd `class-tools-drop.service`
> - 数据根：`/opt/class-tools/drop`（`app.py` + `sessions/` + `files/` + `uploads/` + `.secret`）
> - 公网入口：Caddy `handle /drop/*` → `uri strip_prefix /drop` → `reverse_proxy 127.0.0.1:8093`
> - 部署/探测：`deploy/ecs_drop.py`（阿里云云助手，无需 SSH）；部署记录见 `deploy/ECS_DEPLOY.md` §9
>
> 前端约定：HTTPS 同源页面用 `location.origin + "/drop"`；HTTP 调试期直连 `http://121.196.47.2/drop`。
> 本文件是**前后端唯一契约**；改动必须同步更新本文件 + `drop/tests/test_drop_app.py`。

---

## 0. 拓扑

```
浏览器(大屏/手机)  --https(same-origin /drop)-->  Caddy  --strip_prefix-->  127.0.0.1:8093  drop_app
浏览器(HTTP 调试)  --http://121.196.47.2/drop-->  Caddy                           |
                                                                                 +--> CloudBase 网关 rpc/class_whoami（鉴权）
```

- 服务只监听 127.0.0.1，公网只能经 Caddy `/drop/*` 访问；**直接裸 IP:8093 不可达**。
- 鉴权走 CloudBase RPC `class_whoami`（task-6 交付，见 `deploy/cloudbase/2026-11-11_stage_rpc.sql`）：
  服务端带 `Authorization: Bearer <publish_key>` + `X-Device-Id: <班级 token>` POST `{}`，
  返回 `{ok:true,sid,seat,name}` / `{ok:false,reason}`。
- **publish_key 只以文件形式落在 ECS**（`/opt/class-tools/drop/publish_key`，root:www-data 0640），
  由 `deploy/ecs_drop.py` 从 `deploy/cloudbase/publish_key.txt` 读取后上传，**不打印、不进代码/日志**。

---

## 1. 通用约定

### 1.1 鉴权

- 除 `OPTIONS`、`GET /__health`、签名文件下载外，**所有 API 都必须带** `X-Device-Id: <班级 token>`。
- 服务端把 token 换成 `sid/seat/name` 后**只用于本会话**；token→身份缓存 **120s**（`DROP_AUTH_CACHE_SEC` 可覆盖）。
- 失效/缺失 token → **401** `{ok:false,reason:"身份无效"}`（沿用 RPC 的中文 reason）。
- 网关不可达 / RPC 5xx / 响应不可解析 / 未配置 publish_key → **503** `{ok:false,reason:"鉴权服务暂不可用"}`（**fail closed**，不放行）。
- 访问日志只打印 `方法 路径 状态 耗时`，**绝不打印 token / query / 请求头**。

### 1.2 CORS

所有响应（含错误、文件下载）都带：

```
Access-Control-Allow-Origin: <回显请求 Origin；无 Origin 时 *>
Vary: Origin
Access-Control-Allow-Headers: Content-Type,X-Device-Id,X-Upload-Id
Access-Control-Allow-Methods: GET,POST,DELETE,OPTIONS
Access-Control-Expose-Headers: Content-Length,Content-Range
```

`OPTIONS *` → **204**（空 body），不要求鉴权。

### 1.3 响应 / 错误

- 成功：HTTP 200 + `{ok:true,...}`；JSON 一律 `application/json; charset=utf-8`、`Cache-Control: no-store`。
- 失败：HTTP 4xx/5xx + **`{ok:false,reason:"中文"}`**（reason 可直接展示给用户）。
- 状态码约定：400 参数错误 / 401 未登录或 token 无效 / 403 越权、签名错、已过期 /
  404 会话或文件不存在 / 405 方法不支持 / 411 缺少 Content-Length /
  413 超限（文件/会话/分片/请求体）/ 500 服务内部错误 / 503 鉴权服务不可用。
- `GET /__health` → **免登录**，固定返回 `{ok:true,version,sessions,files,bytes}`。

---

## 2. 会话（一个 sid 同时只有一个活动会话）

- 会话在 `POST /open` 时惰性创建；同一 `sid` 再次 `POST /open`（另一台设备/另一个 token）**复用同一个会话**，
  因此手机与大屏天然「互见」。会话 ID 16 位 hex，房间码 `code` 为 6 位数字（展示用，不参与鉴权）。
- TTL：默认 **7200s**（`DROP_TTL_SEC`）。`expiresAt = createdAt + TTL*1000`，创建后不续期。
- 过期或 `POST /close` 后：会话 JSON 删除、**该会话全部文件与未完成分片删除**；之后 `/mine` 返回 `null`。
- 同一 sid 的旧会话过期后再 `/open`，服务端会先清理旧会话（含文件）再建新的。
- 会话记录在 `<数据根>/sessions/<sessionId>.json`（含事件与文件表），索引在 `sessions/index.json`；
  文件实体在 `<数据根>/files/<sessionId>/<fileId>.bin`；未完成分片在 `<数据根>/uploads/<uploadId>/`。

### 2.1 接口

#### `POST /open`（鉴权）

body `{}`（可为空 body）。返回：

```json
{"ok":true,"session":{"id":"1a2b3c4d5e6f7a8b","code":"042317",
 "createdAt":1762860000000,"expiresAt":1762867200000}}
```

#### `GET /mine`（鉴权）

```json
{"ok":true,"session":null}                    // 没有活动会话
{"ok":true,"session":{...同 /open...}}          // 有
```

#### `GET /state?sessionId=<id>&since=<seq>`（鉴权，仅同 sid）

- `since`：已收到的最大 `seq`，缺省 0；只返回 `seq > since` 的事件（服务端最多保留 500 条，超出丢最旧）。
- 返回：

```json
{"ok":true,
 "session":{"id":"…","code":"042317","expiresAt":1762867200000,"closed":false},
 "events":[
   {"seq":3,"kind":"text","at":1762860001234,"from":{"name":"测试账号"},"payload":{"text":"你好"}},
   {"seq":4,"kind":"file","at":1762860002234,"from":{"name":"测试账号"},
    "payload":{"fileId":"…","name":"讲义.pdf","size":1048576,"mime":"application/pdf","downloadUrl":"http://121.196.47.2/drop/file/…?s=…&exp=…&sig=…"}}
 ],
 "cursor":4}
```

- 事件类型只有三种：`file` / `text` / `cmd`；`from.name` 取当前 token 的 whoami 姓名。
- 跨账号访问别人的 sessionId → 403；sessionId 不存在/已过期 → 404。

#### `POST /close`（鉴权）

body 可带 `{"sessionId":"…"}`（缺省关闭本 sid 的活动会话）。关闭并**立即删除文件**，返回 `{ok:true}`。
`DELETE /session/<sessionId>` 是等价别名（CORS 允许 DELETE 方法）。

---

## 3. 分片上传（支持大文件）

固定分片大小 **`chunkSize = 8388608`（8MiB）**，前端按此切片（最后一片可小于 8MiB）。

1. `POST /upload/init`（鉴权）body：
   `{"sessionId":"…","name":"讲义.pdf","size":20971520,"mime":"application/pdf","totalChunks":3}`
   → `{"ok":true,"uploadId":"9f8e…","chunkSize":8388608}`
   - `totalChunks` 必须与实际上传的片数一致（1..65536）；`size` 为**字节数**，服务端以它为准校验。
   - 超单文件上限 → 413；超会话总量/文件数、磁盘不足 → 413/507（中文 reason）。
2. `POST /upload/chunk?uploadId=<id>&index=<0起>`（鉴权）body 为**原始字节**（不 base64），
   `Content-Length` 即分片长度（必须 ≤ `chunkSize`；也接受 `X-Upload-Id` 头代替 query）。
   → `{"ok":true,"received":<本 uploadId 累计已收字节>}`
3. `POST /upload/finish`（鉴权）body `{"sessionId":"…","uploadId":"…"}`
   → `{"ok":true,"file":{"id":"…","name":"讲义.pdf","size":20971520,"mime":"application/pdf","downloadUrl":"…"}}`
   并追加一条 `file` 事件（`payload` 同上）。分片缺失/大小不符 → 400。

注意：分片写盘为「临时文件 + 原子 rename」（断线重传同 index 覆盖即可）；`finish` 拼接完成后删除分片目录。
`name` 会做 sanitize：去路径（`/`、`\`）、去控制字符、限长 180 字符并**保留扩展名**；
`..`/反斜杠/NUL 不会造成路径穿越（最终落盘名恒为 `<fileId>.bin`，原名只用于展示与下载头）。

---

## 4. 文件下载（签名 URL，无需请求头）

`GET|HEAD /file/<fileId>?s=<sessionId>&exp=<毫秒时间戳>&sig=<hmac>&inline=1`

- `sig = HMAC-SHA256(secret, "fileId|sessionId|exp")`（hex），`secret` 为 `<数据根>/.secret`（首次启动生成，0600，32 字节随机）。
- `exp` 为**毫秒**时间戳，有效期 **30 分钟**（`DROP_URL_TTL_SEC`）；过期为 403，篡改为 403。
- 支持 `Range: bytes=…`（单段；含 `bytes=N-` / `bytes=-N`）→ **206 + Content-Range**；非法/多段 → **416**；`HEAD` 返回 200 + 完整长度。
- `Content-Disposition: attachment; filename*=UTF-8''<RFC5987 编码原名>`；
  带 `&inline=1` 时改为 `inline`（图片预览用）。
- 会话关闭/过期/文件删除后链接失效（404）。下载**不带 CORS 问题**（已带 CORS 头）。
- 下载链接由服务端在 `file` 事件与 `finish` 响应里给出，**不落库、不长期有效**。

---

## 5. 文字与遥控指令

#### `POST /text`（鉴权）

`{"sessionId":"…","text":"…"}`，1..10000 字（含换行；按 Unicode 字符数）→ `{"ok":true,"seq":N}`，追加 `text` 事件。
空文字/超长 → 400。

#### `POST /cmd`（鉴权）

`{"sessionId":"…","op":"timer","args":{"min":5}}` → `{"ok":true,"seq":N}`，追加 `cmd` 事件。
**op 白名单（严格）**：`focus`、`focus_clear`、`timer`、`draw`、`vote_select`、`ppt`、`toast`、`restore_fs`、`stage_close`
（分别对应：聚焦模块、取消聚焦、计时、抽签、切投票、打开演示、提示气泡、恢复全屏、关闭大屏）。
未知 op → 400；`args` 缺省 `{}`，序列化后 ≤ 64KB。

---

## 6. 限制与清理

| 项 | 默认值 | 环境变量 |
|---|---|---|
| 单文件 | 2 GiB | `DROP_MAX_FILE_BYTES` |
| 单会话总量 | 8 GiB | `DROP_MAX_SESSION_BYTES` |
| 单会话文件数 | 300 | `DROP_MAX_FILES` |
| 文字长度 | 10000 字 | `DROP_TEXT_MAX` |
| 每会话事件数 | 500（丢最旧） | `DROP_MAX_EVENTS` |
| 会话 TTL | 7200s | `DROP_TTL_SEC` |
| 下载签名有效期 | 1800s | `DROP_URL_TTL_SEC` |
| 鉴权缓存 | 120s | `DROP_AUTH_CACHE_SEC` |
| 数据根 | `/opt/class-tools/drop` | `DROP_ROOT` |
| 监听端口 | 8093 | `DROP_PORT` |
| 网关基址 | `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/` | `DROP_GATEWAY` |
| 下载 URL 基址 | 由 `X-Forwarded-Proto/Host` 推导 + `/drop` | `DROP_PUBLIC_BASE`（整体覆盖）、`DROP_PUBLIC_PREFIX` |
| 磁盘安全余量 | 保留 ≥1 GiB | `DROP_DISK_RESERVE_BYTES` |

- 后台线程每 **60s** 清理：过期/已关闭会话（含文件）、超 TTL 的孤儿分片；并统计磁盘。
- 健康接口 `sessions/files/bytes` 为**活动会话**的实测值。
- 单实例保护：① 端口绑定失败即启动失败退出（Linux `EADDRINUSE`，systemd 记录 journal）；
  ② 数据根 `.instance` 文件进程锁（`fcntl`/`msvcrt`，Windows 开发机同样生效）——
  两个实例绝不会同时操作同一数据根。

---

## 7. 部署 / 探测 / 回滚

```powershell
# web 目录下，系统 python（需要 aliyunsdkcore；AK/SK 由 deploy/creds.env 提供，脚本不打印）
python deploy\ecs_drop.py probe      # 只读：systemd / 健康 / 目录 / Caddy 路由 / journal
python deploy\ecs_drop.py deploy     # 分片上传 app.py + publish_key → 装 unit → 重启 → 本机健康检查
python deploy\ecs_drop.py verify     # 本机公网：/drop/__health + OPTIONS + 无 token 401（whoami 未就绪时为 503）
python deploy\ecs_drop.py selftest   # 测试身份真实 E2E（登录/open/20MB 分片上传/下载 Range/测速/text/cmd/双 token）
```

- Caddy 路由由 `deploy/ecs_site.py` 的 `_caddy_http()/_caddy_https()` 统一维护：
  `handle /drop/* { uri strip_prefix /drop; reverse_proxy 127.0.0.1:8093 }`；
  改完执行 `python deploy\ecs_site.py apply`（自动备份旧 Caddyfile，`caddy validate` 通过才 reload），
  再 `python deploy\ecs_site.py verify` 确认站点字节与 `/drop/__health`。
- **回滚**：
  1) 停服务 + 拔路由：`systemctl disable --now class-tools-drop`，并去掉 `deploy/ecs_site.py` 里的 drop handle 后 `apply`；
  2) 数据清理：`rm -rf /opt/class-tools/drop/{sessions,files,uploads}`（保留 app.py/.secret/publish_key 无妨）；
  3) Caddy 配置回滚可用 `/var/www/tool_backup/<时间戳>/Caddyfile.old`（`apply` 自动备份）。
- 服务本身无数据库/外部依赖（除鉴权 RPC），部署失败只影响 `/drop/*`，不影响站点、`/att/*`、`/pptfiles/*`。

---

## 8. 安全边界与已知限制（如实）

- 会话隔离靠 `sid`：**同班同学只要拿到同 sid 的 token 就能互相看见**——token 本身即该身份的全部权限，
  本服务不额外区分「大屏/手机」设备。
- 房间码 `code` 只用于人工配对展示，**不是**鉴权凭据。
- 文件仅临时中转（会话 TTL 2 小时 + 手动关闭即删）；**不做持久化、不做缩略图、不做病毒扫描**。
- 单机单实例：所有会话共享 ECS 磁盘（当前 40GiB 盘，长期可用约 30GiB）与 2C2G 内存；
  大文件并发上传/下载会争抢带宽（ECS 出网带宽为实例规格上限）。
- 分片暂存在数据根 `uploads/`，`finish` 前中断会在 60s 清理线程按 TTL 回收；**断点续传不跨会话/不跨重启**（刷新后需重传）。
- 网关鉴权不可用时服务 **fail closed**（全部 API 503），前端应提示「身份服务暂不可用」而不是降级放行。
- 下载签名为服务端 secret 的 HMAC；secret 丢失（`rm .secret`）会让**已发出的下载链接全部失效**（重新生成即可，不影响会话）。
