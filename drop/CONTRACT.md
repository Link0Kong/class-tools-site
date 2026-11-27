# 文件传输服务（drop）· 服务契约 v2（ECS）

> 2026-11-11 建立 v1（大屏临时互联）；**v2（2026-11-11）** 按用户第 1 条改造：
> 「文件传输直接做成单独的工具，上传的文件三天后删除，不限制上传文件大小」。
> **v2.1（2026-11-11 晚）** 按用户原话收紧「三天后删除」语义：**逐文件**从上传完成起 72h 过期，
> 会话改为**空闲滑动**回收（见下）。
> **v2.2（2026-11-12）** 新增 `DELETE /file/<fileId>`（临时云空间单文件删除，仅本账号会话 owner、幂等）；
> 413 拒收前有界读取请求体，避免客户端连接 RST。
> **v2.3（2026-11-12）** 新增 `GET/POST /presence`：大屏在线心跳（30s TTL）；网页大屏每 10s 上报，
> 同账号其它设备据此判断「是否有大屏在开」——无大屏时隐藏「大屏互联」入口，小程序动态显示该工具。
> **v2.4（2026-11-16）** `/presence` 增加 **`sinceSeq`**（大屏打开时刻的会话最大 seq）：大屏首次心跳上报，
> 同账号控制器据此只显示「本次大屏期间」收到的文件/文字，不再翻出 72h 云空间里的旧记录；
> `POST /open`、`GET /mine` 的 `session` 新增 **`seq`** 字段（当前最大事件 seq），供前端拿到「从此刻起」的游标；
> 网页端同时修复：退出大屏立即 POST presence=false（含 `pagehide`/`beforeunload` keepalive），
> 快速开关时迟到的 `/open` 不会再把 presence 拉起；退出大屏会清空本次接收列表（云空间文件仍保留 3 天）。
> **v2.5（2026-11-19，修「文件上传后重新打开/换端就看不见」）**：
> ① **`GET /state` 新增 `all=1`** —— 随事件一并返回**当前有效文件清单** `files`（未过期全量、每次重签
> `downloadUrl`）、`fileSeq`、`expiredNotice`。**文件是会话状态而不是事件流**：事件表只保留最近
> `DROP_MAX_EVENTS`（500）条、且「`since` 之后没有新事件」≠「没有文件」；三端以前只按事件渲染列表，
> 因此事件被截断后会漏文件（表现为「重新打开软件/换端看不到已上传的文件」，删除/清空也会对
> 列表里已过期的 id 失败）。**前端列表一律以 `files` 为准，事件只做增量提示**；不传 `all` 时保持
> v2.4 形状（向后兼容旧客户端）。
> ② **鉴权失败分类**：失败的鉴权结果做短缓存（网关拒绝 30s / 鉴权服务不可用 10s），并回响应头
> **`X-Drop-Reason: token | unavailable`**——`token` = 身份令牌失效/过期（前端提示「重新登录」，停止空转轮询），
> `unavailable` = 鉴权服务暂不可用（提示「稍后自动重试」，放慢轮询）。以前两者都是 401/503 的裸 reason，
> 前端只能显示「连接异常」，用户不知道要重新登录。
>
> - 用途：**同账号（同 sid）跨设备传文件**、发文字、遥控指令中转；服务是独立「文件传输」工具的后端
>   （网页 `#s-file` 文件传输页 / 大屏互联面板共用同一服务），**不限于大屏**，手机 ↔ 电脑 ↔ 大屏均可。
> - **文件保留（v2.1）：每个文件自上传完成时刻起 72 小时（3 天，`DROP_TTL_SEC=259200`）后自动删除**
>   ——逐文件独立过期（后传的文件不会因为前一个文件旧而被一起删）。清理线程每 60s 扫描；
>   过期文件下载返回 404「文件已过期」，`/state` 保留事件 `seq` 但标记 `expired:true` 且不再给下载链接。
> - **会话保留（v2.1）：空闲滑动回收**——`open` / 上传（init·finish）/ 文字 / 指令算活动；
>   最后活动后 72h 无活动**且没有未过期文件**时删除会话（连同未完成分片）；有未过期文件时会话不会被空闲回收，
>   保证三天内随时可下载。`/state`、`/mine` 等纯读取不续期。`POST /close` 立即删除该会话全部文件。
> - 大小：**单文件、单会话总量都不设业务上限**（`DROP_MAX_FILE_BYTES=0`、`DROP_MAX_SESSION_BYTES=0`）；
>   唯一限制是 ECS 磁盘可用空间（保留 ≥1GiB 余量，不足返回 507），磁盘满时前端应提示「空间不足」。
> - 服务：`deploy/drop_app.py`（Python 标准库，**127.0.0.1:8093**，`VERSION=2.1`），systemd `class-tools-drop.service`
> - 数据根：`/opt/class-tools/drop`（`app.py` + `sessions/` + `files/` + `uploads/` + `.secret`）
> - 公网入口：Caddy `handle /drop/*` → `uri strip_prefix /drop` → `reverse_proxy 127.0.0.1:8093`
> - 部署/探测：`deploy/ecs_drop.py`（阿里云云助手，无需 SSH）；部署记录见 `deploy/ECS_DEPLOY.md` §9
>
> 前端约定：HTTPS 同源页面用 `location.origin + "/drop"`；HTTP 调试期直连 `https://tool.furina.fun/drop`。
> 本文件是**前后端唯一契约**；改动必须同步更新本文件 + `drop/tests/test_drop_app.py`。
> **v2.6（2026-11-26）** 支持按文件 ID 提交个人 PPT 转换，详见 §9。

---

## 0. 拓扑

```
浏览器(任意设备)  --https(same-origin /drop)-->  Caddy  --strip_prefix-->  127.0.0.1:8093  drop_app
浏览器(HTTP 调试)  --https://tool.furina.fun/drop-->  Caddy                           |
                                                                                  +--> CloudBase 网关 rpc/class_whoami（鉴权）
```

- 服务只监听 127.0.0.1，公网只能经 Caddy `/drop/*` 访问；**直接裸 IP:8093 不可达**。
- 鉴权走 CloudBase RPC `class_whoami`（见 `deploy/cloudbase/2026-11-11_stage_rpc.sql`）：
  服务端带 `Authorization: Bearer <publish_key>` + `X-Device-Id: <班级 token>` POST `{}`，
  返回 `{ok:true,sid,seat,name}` / `{ok:false,reason}`。
- **publish_key 只以文件形式落在 ECS**（`/opt/class-tools/drop/publish_key`，root:www-data 0640），
  由 `deploy/ecs_drop.py` 从 `deploy/cloudbase/publish_key.txt` 读取后上传，**不打印、不进代码/日志**。
- 「同账号」= 同 `sid`：同一个账号在两台设备（如手机 + 大屏）各拿一个 token，仍然互见同一会话/文件。
  不同 sid 之间**互相不可见**（跨账号访问 403/404）。

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
- 鉴权失败另有机器可读响应头（v2.5）：`X-Drop-Reason: token`（身份令牌失效，提示重新登录）或
  `unavailable`（鉴权服务故障，提示稍后重试）；同时已列入 CORS `Access-Control-Expose-Headers`。
- 状态码约定：400 参数错误 / 401 未登录或 token 无效 / 403 越权、签名错、已过期 /
  404 会话或文件不存在 / 405 方法不支持 / 411 缺少 Content-Length /
  413 数量/分片/请求体超限（**单文件/单会话大小默认不设上限，见 §6**）/ 500 服务内部错误 /
  503 鉴权服务不可用 / **507 服务器磁盘空间不足**（上传初始化、分片、拼接任一阶段都可能返回）。
- `GET /__health` → **免登录**（GET/HEAD），固定返回（v2.1 字段，前端「文件保留 3 天」文案/自动化可直接读）：

```json
{"ok":true,"version":"2.1","sessions":0,"files":0,"bytes":0,
 "ttl":259200,"ttl_hours":72,"file_ttl":259200,"session_idle_ttl":259200,
 "max_file_bytes":0,"max_session_bytes":0,
 "max_files":300,"upload_ttl":86400,
 "disk_free":32125018112,"disk_reserve":1073741824}
```

  - `ttl` / `file_ttl`＝**文件 TTL** 秒（259200 = 72h = 3 天，自上传完成起算）；`ttl_hours` 便于展示；
  - `session_idle_ttl`＝**会话空闲** TTL 秒（滑动续期，259200）；
  - `max_file_bytes` / `max_session_bytes`＝**0 表示不限**（磁盘为唯一限制）；
  - `upload_ttl`＝未完成分片回收秒数（默认 24h）；`disk_free`/`disk_reserve`＝实测磁盘可用/保留余量字节；
  - `sessions/files/bytes` 为**活动会话/未过期文件**的实测值（过期文件不计）。

---

## 2. 会话（一个 sid 同时只有一个活动会话）

- 会话在 `POST /open` 时惰性创建；同一 `sid` 再次 `POST /open`（另一台设备/另一个 token）**复用同一个会话**并算一次活动，
  因此手机与电脑天然「互见」。会话 ID 16 位 hex；`code` 为 6 位数字——**2026-11-12 起仅保留为 API 兼容字段，前端 UI 不再展示，也不参与鉴权/配对**（同账号设备自动互见，不需要房间码）。
- **文件 TTL（v2.1）：每个文件自上传完成（finish）时刻起 72h（3 天，`DROP_TTL_SEC`）后删除**，
  逐文件独立计算；清理线程每 60s 扫描删除文件实体并从会话文件表移除（事件保留 seq，标记 expired）。
- **会话 TTL（v2.1）：空闲滑动 72h**。活动 = `open` / `upload/init` / `upload/finish` / `text` / `cmd`；
  `/state`、`/mine`、下载等读取**不算**活动。最后活动后 72h 内会一直保留；**有未过期文件时不会因空闲被删**
  （保证文件三天内可下载）；文件全部过期后再按「空闲 72h」规则回收会话。
- 对外的 `expiresAt` = `max(最后活动 + 72h, 各未过期文件上传时刻 + 72h)`（毫秒），随活动/文件变化；
  会话被回收后 `/mine` 返回 `null`。
- `POST /close`（或 `DELETE /session/<id>`）立即删除：会话 JSON、**该会话全部文件与未完成分片**；之后 `/mine` 返回 `null`。
  不提供长期存储/回收站/手动续期（活动即自动续期会话，但**不延长已上传文件的 3 天期限**）。
- 同一 sid 的旧会话被回收后再 `/open`，服务端会建新会话。
- 会话记录在 `<数据根>/sessions/<sessionId>.json`（含事件与文件表），索引在 `sessions/index.json`；
  文件实体在 `<数据根>/files/<sessionId>/<fileId>.bin`；未完成分片在 `<数据根>/uploads/<uploadId>/`。

### 2.1 接口

#### `POST /open`（鉴权）

body `{}`（可为空 body）。返回：

```json
{"ok":true,"session":{"id":"1a2b3c4d5e6f7a8b","code":"042317",
 "createdAt":1762860000000,"expiresAt":1763119200000,"seq":42}}
```

（`expiresAt` 语义见 §2：创建时 = 创建时刻 + 72h，之后随活动/未过期文件滑动。
`seq` 为当前会话最大事件 seq（v2.4）：大屏打开时把它作为「本次起点」，再用 `/state?since=<seq>` 只取之后的新事件。）

#### `GET /mine`（鉴权）

```json
{"ok":true,"session":null}                    // 没有活动会话（或已被回收）
{"ok":true,"session":{...同 /open...}}          // 有
```

#### `GET /state?sessionId=<id>&since=<seq>`（鉴权，仅同 sid）

- `since`：已收到的最大 `seq`，缺省 0；只返回 `seq > since` 的事件（服务端最多保留 500 条，超出丢最旧）。
- 返回：

```json
{"ok":true,
 "session":{"id":"…","code":"042317","expiresAt":1763119200000,"closed":false},
 "events":[
   {"seq":3,"kind":"text","at":1762860001234,"from":{"name":"测试账号"},"payload":{"text":"你好"}},
   {"seq":4,"kind":"file","at":1762860002234,"from":{"name":"测试账号"},
    "payload":{"fileId":"…","name":"讲义.pdf","size":1048576,"mime":"application/pdf","downloadUrl":"https://tool.furina.fun/drop/file/…?s=…&exp=…&sig=…"}}
 ],
 "cursor":4}
```

- 事件类型只有三种：`file` / `text` / `cmd`；`from.name` 取当前 token 的 whoami 姓名。
- **`file` 事件（v2.1）**：`event.at` = 文件上传完成时刻；未过期文件事件带**每次读取重新签发**的
  `payload.downloadUrl`（30 分钟有效，见 §4）；文件已过期 → 该事件保留 `seq`，但 `payload.expired=true`
  且不再返回 `downloadUrl`（前端文件列表应过滤 `expired`，历史聊天记录可显示「文件已过期」）。
- **`all=1`（v2.5，文件传输页必须使用）**：额外返回当前有效文件清单：

```json
{"ok":true,
 "session":{"id":"…","code":"042317","expiresAt":1763119200000,"closed":false,"seq":42},
 "events":[ … 同上（只含 seq > since 的事件）… ],
 "cursor":42,
 "files":[
   {"id":"9f8e…","name":"讲义.pdf","size":1048576,"mime":"application/pdf",
    "at":1762860002234,"downloadUrl":"https://tool.furina.fun/drop/file/…?s=…&exp=…&sig=…"}
 ],
 "fileSeq":{"9f8e…":42},
 "expiredNotice":2}
```

  - `files` = **未过期且实体仍在**的文件全量（**与 `since` 无关**，每次重签 `downloadUrl`），按 `at` 倒序；
  - `fileSeq` = 本批事件涉及的 fileId → 当前最大 seq（增量提示用）；
  - `expiredNotice` = 会话里曾上传、现已过期的文件数（列表下方「N 个文件已过期」提示）；
  - 前端约定：`files` 是列表唯一真源；`events` 里 file/filedel 只用于弹「收到新文件」等提示。
    不传 `all` 时响应形状与 v2.4 相同。
- 跨账号访问别人的 sessionId → 403；sessionId 不存在/已回收 → 404。

#### `GET /presence`、`POST /presence`（鉴权）

- `POST /presence` body `{"stage":true,"sinceSeq":<int>?}`：标记当前账号大屏在线（`stageAt=now`，30s 内有效）；
  `sinceSeq` 由大屏在打开时上报（= 打开时刻 `session.seq`，服务端 clamp 到 `[0,当前seq]`；不传时取当前 seq，向后兼容旧页面）。
  `{"stage":false}` 立即下线并清零 `stageSince`。
  返回 `{"ok":true,"stage":true|false,"at":<ms>,"sinceSeq":<int>}`（下线时 sinceSeq=0）。
- `GET /presence`：同账号任意设备可查，返回 `{"ok":true,"stage":bool,"at":<ms>,"sinceSeq":<int>,"stageSince":<int>}`；
  无会话/过期时 stage=false、sinceSeq=0（不创建会话）。`sinceSeq` 只在大屏在线时给出，表示**本次大屏**的事件起点。
- 用途：网页「全部页 → 大屏互联」与小程序「全部工具 → 大屏互联」仅在大屏在线时显示；
  网页大屏打开后每 10s POST 心跳，关闭时（含 `pagehide` keepalive）POST false。
- 控制器读取 `sinceSeq` 后以 `/state?...&since=<sinceSeq>` 拉取，**只显示本次大屏期间**新增的文件/文字；
  72h 云空间里的历史记录不会回放成大屏消息（历史文件请到「文件传输」页查看）。
- 注意：区分于文件云空间会话——文件页自动开会话**不会**让 presence=true（未上报 stage）。

#### `DELETE /file/<fileId>?sessionId=<sid>`（鉴权，临时云空间单文件删除）

- 仅本账号会话 owner 可删；幂等：文件不存在/已过期 → `{ok:true,deleted:false}`。
- 成功：删除文件实体 + 从会话文件表移除，并追加 `filedel` 事件（`payload={fileId,name,size}`）；
  其它同账号设备通过 `/state` 收到 `filedel` 后从列表移除该文件。
- 原 `file` 事件保留 seq：`/state` 将其标记 `payload.expired=true` 且不再返回 `downloadUrl`；下载返回 403/404。
- 返回：`{"ok":true,"deleted":true,"name":"…","size":123}`。

#### `POST /close`（鉴权）

body 可带 `{"sessionId":"…"}`（缺省关闭本 sid 的活动会话）。关闭并**立即删除文件**，返回 `{ok:true}`。
`DELETE /session/<sessionId>` 是等价别名（CORS 允许 DELETE 方法）。

---

## 3. 分片上传（支持超大文件，单文件不限大小）

固定分片大小 **`chunkSize = 8388608`（8MiB）**，前端按此切片（最后一片可小于 8MiB）。

1. `POST /upload/init`（鉴权）body：
   `{"sessionId":"…","name":"讲义.pdf","size":20971520,"mime":"application/pdf","totalChunks":3}`
   → `{"ok":true,"uploadId":"9f8e…","chunkSize":8388608}`
   - `totalChunks` 必须与实际上传的片数一致（1..65536；8MiB×65536 ≈ 512GiB 声明上限，实际受磁盘限制）；
     `size` 为**字节数**，服务端以它为准校验；`totalChunks` 按 `ceil(size/chunkSize)` 计算。
   - **单文件大小默认不限**（`DROP_MAX_FILE_BYTES=0`）；主动配置上限时超限 → 413。
   - 会话文件数上限 300 → 413；磁盘余量不足 → **507**（中文 reason，前端提示空间不足/稍后重试）。
2. `POST /upload/chunk?uploadId=<id>&index=<0起>`（鉴权）body 为**原始字节**（不 base64），
   `Content-Length` 即分片长度（必须 ≤ `chunkSize`；也接受 `X-Upload-Id` 头代替 query）。
   → `{"ok":true,"received":<本 uploadId 累计已收字节>}`
   - 分片写入前检查磁盘余量，不足 → **507**（不会落半片；同 index 可重试覆盖）。
3. `POST /upload/finish`（鉴权）body `{"sessionId":"…","uploadId":"…"}`
   → `{"ok":true,"file":{"id":"…","name":"讲义.pdf","size":20971520,"mime":"application/pdf","downloadUrl":"…"}}`
   并追加一条 `file` 事件（`payload` 同上）。分片缺失/大小不符 → 400；拼接额外空间不足 → 507（不留半成品）。

注意：分片写盘为「临时文件 + 原子 rename」（断线重传同 index 覆盖即可）；`finish` 拼接完成后删除分片目录。
`name` 会做 sanitize：去路径（`/`、`\`）、去控制字符、限长 180 字符并**保留扩展名**；
`..`/反斜杠/NUL 不会造成路径穿越（最终落盘名恒为 `<fileId>.bin`，原名只用于展示与下载头）。

**未完成分片**：`/upload/init` 后 **24 小时无活动（`DROP_UPLOAD_TTL_SEC=86400`）** 或所在会话被关闭/过期时，
由后台清理线程删除整个 upload 目录；传输超大文件期间会持续刷新「最后活动时间」，不受影响。

---

## 4. 文件下载（签名 URL，无需请求头）

`GET|HEAD /file/<fileId>?s=<sessionId>&exp=<毫秒时间戳>&sig=<hmac>&inline=1`

- `sig = HMAC-SHA256(secret, "fileId|sessionId|exp")`（hex），`secret` 为 `<数据根>/.secret`（首次启动生成，0600，32 字节随机）。
- `exp` 为**毫秒**时间戳，有效期 **30 分钟**（`DROP_URL_TTL_SEC`）；过期为 403，篡改为 403。
- 支持 `Range: bytes=…`（单段；含 `bytes=N-` / `bytes=-N`）→ **206 + Content-Range**；非法/多段 → **416**；`HEAD` 返回 200 + 完整长度。
  **大文件下载请优先用 Range 续传**（链接 30 分钟内有效，过期需重新上传/刷新事件）。
- `Content-Disposition: attachment; filename*=UTF-8''<RFC5987 编码原名>`；
  带 `&inline=1` 时改为 `inline`（图片预览用）。
- **文件未过期（上传完成起 72h 内）且实体存在即可下载**；上传超过 72h 的文件即使清理线程还没轮到，
  也返回 **404 `文件已过期（上传超过 72 小时，已自动删除）`**；会话被关闭/回收后链接失效（404）。
  下载**不带 CORS 问题**（已带 CORS 头）。
- 下载链接由服务端在 `file` 事件与 `finish` 响应里给出，**不落库、不长期有效**。
- **v2.1 重签规则（文件保留 3 天的关键）**：文件实体保留到「各自上传完成 + 72h」，但下载签名只有 30 分钟；
  因此 `GET /state` 每次返回时会对**未过期且实体仍在**的文件重新签发 `payload.downloadUrl`
  （事件 `seq/kind/at/from` 与其它字段不变，仅刷新链接）。前端「文件列表」应以 `/state` 为准，
  **不要长期缓存 downloadUrl**：
  - 打开页面/刷新列表：`GET /state?sessionId=…&since=0` 拿最新可下载链接（过滤 `payload.expired`）；
  - 下载返回 403「下载链接已过期」时：重新拉一次 `/state` 再重试（大文件用 Range 续传同样先换新链接）；
  - 文件上传超过 72h：该文件事件变为 `expired:true` 且无 `downloadUrl`，列表不再显示可下载项。

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

## 6. 限制与清理（v2.1 默认值）

| 项 | 默认值 | 环境变量 |
|---|---|---|
| **单文件大小** | **不限（0）** | `DROP_MAX_FILE_BYTES`（>0 时启用上限） |
| **单会话总量** | **不限（0，仅受磁盘）** | `DROP_MAX_SESSION_BYTES`（>0 时启用上限） |
| 单会话文件数 | 300（仅计未过期文件） | `DROP_MAX_FILES` |
| 文字长度 | 10000 字 | `DROP_TEXT_MAX` |
| 每会话事件数 | 500（丢最旧） | `DROP_MAX_EVENTS` |
| **文件 TTL（保留）** | **259200s（72h = 3 天，自上传完成起算，逐文件）** | `DROP_TTL_SEC` |
| 会话空闲 TTL（滑动） | 259200s（有未过期文件期间不回收，文件全过期后按空闲 72h 回收） | `DROP_TTL_SEC` |
| 未完成分片保留 | 86400s（24h 无活动即回收） | `DROP_UPLOAD_TTL_SEC` |
| 下载签名有效期 | 1800s | `DROP_URL_TTL_SEC` |
| 鉴权缓存 | 120s | `DROP_AUTH_CACHE_SEC` |
| 数据根 | `/opt/class-tools/drop` | `DROP_ROOT` |
| 监听端口 | 8093 | `DROP_PORT` |
| 网关基址 | `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/` | `DROP_GATEWAY` |
| 下载 URL 基址 | 由 `X-Forwarded-Proto/Host` 推导 + `/drop` | `DROP_PUBLIC_BASE`（整体覆盖）、`DROP_PUBLIC_PREFIX` |
| 磁盘安全余量 | 保留 ≥1 GiB | `DROP_DISK_RESERVE_BYTES` |

- 后台线程每 **60s** 清理：① 逐文件 TTL（`now - 上传完成时刻 > 72h` → 删实体、移出会话文件表）；
  ② 无未过期文件且最后活动 > 72h 的会话（连同未完成分片）；③ 长时间无活动的孤儿分片；并统计磁盘。
- **单文件/单会话大小只受磁盘限制**：超磁盘可用空间（扣掉 1GiB 余量）时，init/分片/拼接分别返回 507；
  不会因大小本身返回 413（除非显式设置了 `DROP_MAX_*_BYTES`）。
- 健康接口 `sessions/files/bytes` 为**活动会话/未过期文件**的实测值；`ttl`/`file_ttl` 反映文件 TTL，
  `session_idle_ttl` 反映会话空闲 TTL。
- 单实例保护：① 端口绑定失败即启动失败退出（Linux `EADDRINUSE`，systemd 记录 journal）；
  ② 数据根 `.instance` 文件进程锁（`fcntl`/`msvcrt`，Windows 开发机同样生效）——
  两个实例绝不会同时操作同一数据根。

---

## 7. 部署 / 探测 / 回滚

```powershell
# web 目录下，系统 python（需要 aliyunsdkcore；AK/SK 由 deploy/creds.env 提供，脚本不打印）
python deploy\ecs_drop.py probe      # 只读：systemd / 健康 / 目录 / Caddy 路由 / journal
python deploy\ecs_drop.py deploy     # 分片上传 app.py + publish_key → 装 unit → 重启 → 本机健康检查
python deploy\ecs_drop.py verify     # 公网：/drop/__health（ttl/file_ttl/session_idle_ttl=259200）+ CORS + 无 token 401
python deploy\ecs_drop.py selftest   # 测试身份真实 E2E（登录/open/20MB 分片上传/下载 Range/测速/text/cmd/双 token）
```

- Caddy 路由由 `deploy/ecs_site.py` 的 `_caddy_http()/_caddy_https()` 统一维护：
  `handle /drop/* { uri strip_prefix /drop; reverse_proxy 127.0.0.1:8093 }`；
  改完执行 `python deploy\ecs_site.py apply`（自动备份旧 Caddyfile，`caddy validate` 通过才 reload），
  再 `python deploy\ecs_site.py verify` 确认站点字节与 `/drop/__health`。
- **回滚**：
  1) 停服务 + 拔路由：`systemctl disable --now class-tools-drop`，并去掉 `deploy/ecs_site.py` 里的 drop handle 后 `apply`；
  2) 数据清理：`rm -rf /opt/class-tools/drop/{sessions,files,uploads}`（保留 app.py/.secret/publish_key 无妨）；
  3) Caddy 配置回滚可用 `/var/www/tool_backup/<时间戳>/Caddyfile.old`（`apply` 自动备份）；
  4) 只回退到 v1 行为：`ecs_drop.py` 的 unit 里把 `DROP_TTL_SEC=7200`、
     `DROP_MAX_FILE_BYTES=2147483648`、`DROP_MAX_SESSION_BYTES=8589934592` 写入后重新 `deploy`。
- 服务本身无数据库/外部依赖（除鉴权 RPC），部署失败只影响 `/drop/*`，不影响站点、`/att/*`、`/pptfiles/*`。

---

## 8. 安全边界与已知限制（如实）

- 会话隔离靠 `sid`：**同班同学只要拿到同 sid 的 token 就能互相看见**——token 本身即该身份的全部权限，
  本服务不额外区分设备；跨 sid 不可见。
- `code` 为历史兼容字段（前端已不展示），**不是**鉴权凭据，也不用于配对；配对完全由「同一班级 token / 同账号」自动完成。
- 文件仅临时中转：**每个文件上传完成 3 天后自动删除 + 手动关闭会话即删**；不做持久化、不做缩略图、
  不做病毒扫描；同账号任一设备都可下载（3 天内），过期即失效。
- 单机单实例：所有会话共享 ECS 磁盘（当前 40GiB 盘，长期可用约 30GiB）与 2C2G 内存/带宽；
  单文件/会话不设业务上限，但**磁盘是硬限制**（保留 1GiB 余量），大文件并发上传/下载会争抢带宽与磁盘。
- 清理删除为后台线程同步操作：删除数十 GB 级文件可能耗时数秒~数十秒，但只发生在独立的清理线程，
  不阻塞其余 API（删除期间该文件已过期，下载/链接本就失效）。
- 分片暂存在数据根 `uploads/`，无活动超过 24h 由清理线程回收；**断点续传不跨会话/不跨重启**（刷新后需重传）。
- 网关鉴权不可用时服务 **fail closed**（全部 API 503），前端应提示「身份服务暂不可用」而不是降级放行。
- 下载签名为服务端 secret 的 HMAC；secret 丢失（`rm .secret`）会让**已发出的下载链接全部失效**（重新生成即可，不影响会话）。

## 9. 文件行的 PPT 转换（v2.6）

- `GET /state?sessionId=…&all=1&ppt=1` 增加 `pptConversion` 能力标志。已提交的文件有 `conversion: {status,progress,error,attempt}`。`status` 为 `queued`、`processing`、`ready` 或 `failed`。文件、会话归属和到期判断与 §2 一致。原文件的 `downloadUrl` 继续返回原件。旧查询与大屏事件保持原形状。
- `POST /ppt/<fileId>` 带原有 `X-Device-Id` 和 `{sessionId}`。文件表记录和落盘原件齐备后才可提交。服务端检查 `.ppt` 的复合文档流、`.pptx` 的演示包和页数，以及两种格式的 64 MiB 上限。PowerPoint 在转换时再次检查文件可打开且为 1–300 页。重复请求返回原任务。失败重试另带列表中实际看到的 `retryAttempt`，仅在对应尝试仍为 `failed` 时创建下一次尝试。`fileId` 一直相同。
- `GET /ppt/<fileId>?sessionId=…` 对同账号返回 `{ok,name,conversion}`，结果就绪时带 PPT v2 格式的 `manifest`。`files.compat`、`files.pdf` 和 `media_files` 只包含可下载的产物。`s` 为文件传输的结果下载地址。浏览器同源加入 `browser=1` 取得 `browserProof`，将其设为结果路由下的 `drop_ppt_download` Cookie。原始文件从原行下载。
- `GET|HEAD /ppt-result/<sessionId>/<fileId>/<key>?exp=…&sig=…` 支持原有附件响应与 Range。移动和桌面原生端在下载请求中带 `X-Device-Id`，由服务端检查归属。网页的原生下载由同站下载 Cookie 授权。服务端校验结果、所属会话、尝试序号及原件有效期。链接和凭证最长 30 分钟，且截至原件上传完成后 72 小时。删除或清空后即刻停止接受新的下载请求。
- 转换机通过 `/ppt-worker/` 读取个人任务，与班级队列按时间选择任务。转换机认领后直接读取已拼接原件，使用同一个 `convert_compat()`，再把成品流式写回 ECS。任务、结果和签名留在文件传输服务。队列等待超过 6 小时或认领后超过 50 分钟会转为可重试失败。删除和过期清理一并回收转换目录，旧认领无法把结果写回失效文件。启用方式见 [转换机运维](../ppt/README.md#12-文件传输的个人转换)。

网页、微信小程序、Android（M05，d1c5f80）、HarmonyOS（M06，78234fd）和 Windows（C04，efbf16b58581）的文件页均已接入 v2.6。三套原生下载器已用同一隔离服务校验原件、兼容 PPTX 和 PDF 字节，Windows 另覆盖过期结果链接续签。旧客户端继续使用 v2.5 的全量文件列表。

### 隔离验证个人转换

在 Web 仓根执行。脚本启动仅监听 loopback 的真实 Drop HTTP 服务，使用临时存储、两张同账号测试票和另一张合成账号票。所有原件为生成的两页 PPTX 与普通文本，服务、worker 工作目录和测试浏览器随进程结束关闭。输出目录保留本次样本。

    python -B drop/tests/conversion_fixture.py --output <新的结果目录>
    python -B drop/tests/conversion_fixture.py --web --office --output <新的结果目录>
    python -B drop/tests/conversion_fixture.py --port 17842 --keep-seconds 300 --output <新的结果目录>

第一条走模拟转换机，第二条用真实移动宽度的 Web 文件选择器上传、提交，第二个独立浏览器存储读取并逐字节校验原件和两项产物，PowerPoint COM 走部署使用的 run_drop_job/convert_compat。第三条在打印 READY 后保留服务，供原生端用同台主机的 loopback 访问；模拟器应使用对应平台的本机端口映射。服务没有向外网开放端口。假 worker 需 requests、python-pptx、pypdf，Web 回归需 Edge、websocket-client、Pillow；Office 路径另需仓内转换机的依赖与已安装的 PowerPoint。

fixture.json 提供本轮 base、sessionId、fileId、同账号的两张本地测试票、另一账号测试票和该次实际签发的响应。responses 包含 v2.5 文件列表、v2.6 文件列表及 queued、processing、failed、ready 四态详情。每次启动重新生成会话和下载链接。原件和产物分别与 sha256 内同名文件比对。预览 PDF 应有两页；兼容 PPTX 可重新打开且两页标题均保留。样例不含媒体，media_files 为空。下载产物需要带所属账号票，失效重新取详情再下载，原件从 files 行重签。下载原件的有效签名链接属于持有即能下载的能力，切号后服务禁止另一账号列出该会话或获取新的链接。释放夹具时删除原件验证已签产物与原件链接随即失效，并模拟 72 小时到期。
