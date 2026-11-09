# PPT 演示 · 三端契约（v1，2026-11-09）

> **本文件是唯一真源**。网页 / 小程序 / 安卓 / 本机转换机四端都按本文件实现；
> 任何接口、字段、状态、行为改动必须先改本文件并在交付说明里注明版本。
> 上线目标：`tool.furina.fun`（网页）、微信小程序、Android APK 三端同步上线。

---

## 1. 需求与产品结论（用户 2026-11-09 原话场景）

- 教室电脑老旧：PPT 动画多就卡死/无响应；在自己电脑能播的嵌入视频换到班级电脑就「媒体不可用」。
- 目标：**任意设备都能完整、流畅地播放 PPT**；**任何人可上传**（班级成员）。
- 结论（本方案）：
  1. **上传端只上传源文件**，本机「转换机」（Windows + Microsoft PowerPoint COM）一次性把 PPT
     渲染成**分步图片**（每页 + 每个「点击动画步」一张图），并把**嵌入视频/音频抽出来转成 H.264 MP4 / AAC**；
  2. 三端播放器只做「加载图片 + 切图 + 播 MP4」→ 老电脑也秒开、不卡；视频不再依赖 PowerPoint 解码器；
  3. 图片/视频放阿里云 OSS（公共读、内容哈希路径、长缓存），清单和状态走 CloudBase PostgreSQL（现有班级 token RLS）；
  4. 转换机离线时任务排队，页面显示状态；转换完成后全班可见。
- **已知取舍（必须如实写进交付说明，不许掩饰）**：
  - 「分步图片」优先保证**内容完整 + 播放流畅**；同一文本框内**逐段文字出现**的动画会合并为整段出现；
    **强调动画/运动路径**只取该步的最终视觉状态（快照），不是逐帧动画；
  - 转换机需在开机状态（带 PowerPoint 的本机）；离线时只排队不转换；
  - 转换后资产在 OSS 公共读（URL 含 128bit 随机 deckId，不可枚举）；班级 PPT 视为班内公开材料；
  - 源文件保留 `ppt/src/` 供「下载原件」，原文件同样公共读（同上，随机路径）。

## 2. 总体数据流

```
[web/mp/android] --(1)POST ppt_decks 建行-->  CloudBase PG public.ppt_decks
                --(2)POST ppt_upload_chunks 分片（512KB/片，base64）--> public.ppt_upload_chunks
                --(3)PATCH ppt_decks status=queued---------------------> (转换机轮询)
[本机转换机 web/ppt/agent.py，管理员 token]
  GET queued → PATCH processing → GET chunks 拼源文件 → DELETE chunks
  → PowerPoint COM 逐页/逐步导出 JPG → Pillow 转 WebP(1600/400)
  → SaveCopyAs 解包 ppt/media → ffmpeg 转码 → 上传 OSS ppt/a/<id>/<build>/
  → PATCH ppt_decks status=ready + manifest + cover_url
[三端] GET ppt_decks 列表 / 单行 manifest → 播放器按 manifest 加载 OSS 图片与视频
```

- 云端写死的常量（三端 + 转换机一致）：
  - REST 基址：`https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/`
  - 发布键（PUBLISHABLE KEY，公开凭据，已在网页内）：见 `web/deploy/cloudbase/publish_key.txt`；
    网页已内嵌 `CBK`，小程序在 `utils/cloud-config.js`，安卓在 `data/network`，**不要新增任何服务端密钥**。
  - 身份头：网页 `X-Device-Id: <token>`；小程序 `X-Class-Token: <token>`；安卓 `X-Device-Id: <token>`。
  - 请求统一带 `Authorization: Bearer <PUBLISHABLE_KEY>`。
- OSS：bucket `tool-furina-fun`（`oss-cn-hongkong`），公共读，直连域名（**不要用 tool.furina.fun 域名**）：
  - 资产基址：`https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/`
  - 转换产物：`ppt/a/<deckId>/<buildId>/...`
  - 原件：`ppt/src/<deckId>/source.<ext>`

## 3. 云端表（已应用：`web/deploy/cloudbase/2026-11-09_ppt_decks.sql`）

### 3.1 `public.ppt_decks`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | text PK | 客户端生成：`d` + base36(ts) + 6 位随机小写字母数字，例 `dmg2k4x9ab12c` |
| `title` | text | 显示标题（默认=文件名去扩展名，可改，≤80 字） |
| `owner_sid` / `owner_name` | text | 上传者（客户端必须填 `owner_sid`=自己 sid，RLS 校验） |
| `client` | text | `web` / `mp` / `android` |
| `status` | text | `uploading` → `queued` → `processing` → `ready` / `failed`（见 §4.3） |
| `progress` | int | 0–100，转换进度（客户端上传进度用本地状态，不写云端） |
| `error` | text | 失败原因（中文，≤300 字，前端直接展示） |
| `source_name` / `source_size` / `chunk_count` | — | 源文件名 / 字节数 / 分片数（客户端上传时写） |
| `source_key` | text | 原件 OSS key（转换机写） |
| `slide_count` / `step_count` / `aspect` | — | 页数 / 总步数 / `16:9`·`4:3`·`其他宽高比文字` |
| `cover_url` | text | 封面图 URL（转换机写，第一页缩略图） |
| `manifest` | jsonb | **播放清单**，见 §5；上传中为 `{}` |
| `converter` | text | 转换机主机名（转换机写） |
| `deleted` | boolean | 软删除；客户端只查 `deleted=eq.false` |
| `created_at` / `updated_at` / `converted_at` | bigint | unix ms |

### 3.2 `public.ppt_upload_chunks`

| 列 | 说明 |
|---|---|
| `deck_id` | 所属 deck |
| `owner_sid` | 上传者（=deck.owner_sid，RLS 校验） |
| `idx` | 分片序号，从 0 连续递增 |
| `data` | 分片原始字节的 **base64 字符串** |
| `ts` | unix ms |

- 分片大小：**固定 512 KiB 原始字节/片**（最后一片可小）；base64 后约 683KB/行。
- 实测单请求 JSON body 2.7MB 可行；客户端**并行度 ≤4**，每请求 1 片最稳（也允许 2 片/请求）。
- 上传完成后 `PATCH ppt_decks` 写 `status=queued`、`chunk_count`、`source_size`、`updated_at`。
- 转换机拼装并**立即 DELETE 分片**；分片不长期保存。
- 重新上传/续传：同一 `(deck_id, idx)` 用 upsert（`Prefer: resolution=merge-duplicates`，PostgREST 对 POST 生效）。

### 3.3 权限（RLS，已实测）

- 读 `ppt_decks`：任意有效班级 token（`auth_ok()`）；匿名 `[]`。
- 写 `ppt_decks`：本人 `owner_sid = auth_sid()`；转换机用**管理员 token** 可更新任意行。
- 分片：本人可 `SELECT/INSERT/DELETE`；转换机（管理员 token）可读、可删。
- 无 DELETE 策略 → deck 删除=软删 `deleted=true`；分片 DELETE 有策略。

### 3.4 转换机心跳（复用 `public.site_assets`）

- 行 `id='ppt_agent'`：`body = {online:true, seen_at:<ms>, queued:0, version:"1.0", host:"..."}`，`updated_at` 由库自动。
- 转换机每轮（≤60s）upsert；客户端读 `GET site_assets?id=eq.ppt_agent&select=body,updated_at`，
  `now - seen_at > 180000` 视为**转换机离线**（页面提示「转换机离线 · 任务排队中」，不要报错）。

## 4. 接口契约（PostgREST；三端一致）

> 网页可直接复制现有 `cbH/cbPost` 风格；小程序走 `utils/cloud.js` 的 `request`；安卓走现有 OkHttp 通道。
> 所有失败处理：**不白屏、不丢本地状态、可重试**。

### 4.1 建 deck（上传第 0 步）

```http
POST /ppt_decks
Prefer: return=representation
[{ "id":"d...", "title":"班会PPT", "owner_sid":"<本人sid>", "owner_name":"<本人姓名>",
   "client":"web", "status":"uploading", "source_name":"班会.pptx", "source_size":12345678,
   "chunk_count":24, "aspect":"16:9", "created_at":<ms>, "updated_at":<ms>, "deleted":false }]
```
- 返回 201 + 行数组。失败（403/401）→ 提示「身份已过期，请重新进入」，回到身份页逻辑由各端现有机制处理。

### 4.2 上传分片

```http
POST /ppt_upload_chunks
Prefer: resolution=merge-duplicates,return=minimal
[{ "deck_id":"d...", "owner_sid":"<sid>", "idx":0, "data":"<base64>", "ts":<ms> }]
```
- 201/204 都算成功；失败**重试 2 次**（指数退避 400/1200ms），仍失败→整体失败并 PATCH `status=failed,error="上传中断，请重试"`（允许用户重试：重新走 §4.2 全部片再 §4.3）。
- 客户端进度 = 已成功片数/总片数。

### 4.3 提交转换

```http
PATCH /ppt_decks?id=eq.<deckId>
Prefer: return=representation
{ "status":"queued", "chunk_count":<n>, "source_size":<bytes>, "updated_at":<ms> }
```

### 4.4 列表（列表页只查轻字段，禁止带 manifest）

```http
GET /ppt_decks?select=id,title,owner_sid,owner_name,status,progress,error,slide_count,step_count,aspect,cover_url,source_name,source_size,created_at,converted_at,client&deleted=eq.false&order=created_at.desc&limit=100
```
- 客户端展示规则：
  - `uploading` 且 `owner_sid==自己` → 显示「上传中」；`uploading` 且别人的 → **不显示**；
  - `queued` → 「排队转换」；`processing` → 「转换中 p%」；`failed` → 「转换失败」+ error；`ready` → 可播放；
  - 排序建议：本人在传/转换中的置顶，其余按 `created_at desc`。

### 4.5 播放前取清单

```http
GET /ppt_decks?select=manifest,title,slide_count,step_count,aspect,cover_url,source_name,source_key,converted_at&id=eq.<deckId>
```
- `manifest` 为空/`{}` → 「还没转换完成」。

### 4.6 软删除 / 重试（仅本人或管理员；前端只对本人入口展示）

```http
PATCH /ppt_decks?id=eq.<id>  { "deleted":true, "updated_at":<ms> }
PATCH /ppt_decks?id=eq.<id>  { "status":"queued", "progress":0, "error":"", "updated_at":<ms> }   # 失败重试
```

### 4.7 轮询

- 列表页可见时 **10s** 轮询（页面隐藏停止；回到前台立即拉一次）。播放页不轮询。
- 转换机心跳只在列表页轮询时随列表一起拉（同一轮）。

## 5. `manifest` 播放清单 v1（唯一契约）

```jsonc
{
  "v": 1,
  "base": "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/a/<deckId>/<buildId>/",
  "src":  "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/src/<deckId>/source.pptx",  // 可为 ""
  "w": 1600, "h": 900,          // 渲染图基准宽高（16:9=1600x900，4:3=1600x1200）
  "slides": [                   // 按页顺序
    {
      "tr": "fade",             // 页切换动效：none|fade|push|wipe|zoom|cover；未知按 fade
      "trd": 450,               // 毫秒
      "notes": "演讲者备注文本，可为空串",
      "thumb": "t1.webp",       // 本页缩略图（相对 base；也可写 http/data: 绝对地址）
      "steps": [                // 至少 1 个；每个「点击」推进一个 step
        {
          "img": "s1-1.webp",
          "media": [            // 可空数组；该步图上有视频/音频热点（与图片坐标系同一套 0..1 归一化）
            { "s": "m0.mp4", "k": "v", "x": 0.12, "y": 0.15, "w": 0.76, "h": 0.70 }
          ]
        }
      ]
    }
  ],
  "media": [                    // 全局媒体表（按 s 引用）
    { "s":"m0.mp4", "k":"v", "w":1280, "h":720, "dur":12.4 }   // k: v=视频 a=音频
  ]
}
```
- **URL 解析规则（三端一致）**：`img/thumb/s` 若以 `http://`、`https://`、`data:` 开头 → 直接使用；
  否则 `base + 文件名`。测试可用 `data:` URL 注入假图。
- 坐标 `x,y,w,h` = 相对**幻灯片整页**的 0..1 归一化；播放器把热点覆盖在图片实际渲染区域上（letterbox 内）。
- 媒体播放：`k:'v'` 用原生视频播放器（HTML `<video>` / mp `<video>` / Android VideoView），`k:'a'` 用音频播放器；
  播放器需支持「点热点→全屏/内嵌播放→播完/关闭后回到当前步」。
- 图片渲染：`steps[j].img` 是**该步完整画面**；同一页内切步用极短淡入（≤160ms），跨页用 `tr`。
- 缩略图：用 `slide.thumb`（无则用第一步 `img`）。
- 兼容：客户端必须忽略未知字段；manifest 缺失字段用默认值，不得报错白屏。
- **播放语义（2026-11-09 补充，DESIGN §4.12 确认）**：
  - 前进/后退单位 = **step**（动画步）；`step=0` 再后退 → 上一页的**最后一步**（否则永远退不回上一个动画）。
  - 媒体层（视频/音频）**不随 step 切换卸载**，只在换页 / 退出播放器时销毁；步骤切换不得重置正在播放的媒体。
  - 步图已包含视频海报帧（PowerPoint 渲染），**不需要额外 poster 字段**（`manifest` 不加 `ph`）。
  - 允许客户端按设备能力把页切换 `tr` 降级为 `fade`（低端机/保守实现），契约值仍保留；不得因此报错。
  - 页面页码按「页」、顶部总进度按「step」；页内步点仅在当前页 step≥2 时显示。

## 6. 转换机（`web/ppt/`，仅本机）

> 实现者：backend-agent。运行环境：Windows + Microsoft PowerPoint 16.0（无需 LibreOffice）+ ffmpeg（`ffmpeg.exe` 在 PATH）。

- **入口**：`web/ppt/agent.py`
  - `--once`：跑一轮（scheduled task 每 1 分钟调用一次；自带单实例锁）
  - `--deck <id>`：调试单个 deck
  - `--dry-run`：只打印不写云端/OSS
  - `--scheduled`（可选）：等价 `--once`
- **身份**：管理员 token 优先读 `C:\briefdesk\secrets\class-token.json`（`{"token","exp"}`）；
  过期提前 1h 用 `POST /rpc/class_verify`（PUBLISHABLE KEY，body `{p_sid:<admin_sid>,p_name:<admin_name>}`）刷新；
  管理员身份从 `C:\briefdesk\secrets\cloudbaserc.local.json` 的 `envVariables.CLASS_ADMIN_SID/NAME` 读取；
  刷新后的 token 写回 `C:\briefdesk\secrets\class-token.json`（保留原格式）。**日志/输出绝不打印 token。**
- **一轮流程**：心跳 → 取 `status=eq.queued&deleted=eq.false&order=created_at.asc&limit=1` →
  认领（PATCH `processing`,`progress:3`）→ 拉分片拼装（大小=source_size，≤64MiB，扩展名 .ppt/.pptx）→
  上传原件 OSS → 删分片（失败不阻塞）→ 转换（phase: 每页渲染 progress 递增）→ 上传资产 → PATCH `ready`。
  任何异常 → PATCH `failed`+`error`（中文，≤300 字），并保证分片已删；下一轮继续。
- **PowerPoint 安全**：
  - 若已存在 POWERPNT 进程且 `Presentations.Count>0`（用户可能正在编辑）→ 本轮**跳过转换**（deck 保持 queued，
    心跳写 `queued` 数量），日志 `[skip] PowerPoint busy`；为空实例则 Quit 后新建；
  - `DispatchEx("PowerPoint.Application")`，`DisplayAlerts=ppAlertsNone`，文件只读打开，用临时副本；
  - 单任务超时 15 分钟；超时只结束**自己创建的** PowerPoint 实例（保留用户文档），标记 failed「转换超时」。
- **渲染规格**：
  - 1600px 宽（16:9→1600x900；4:3→1600x1200；其它按比例，高=round(1600*h/w)）；
  - 每页 step = 1（默认画面）+ 每个「单击触发」�und动画步；`with previous/after previous` 并入当前 step；
    逐个 step 设置目标形状 `Shape.Visible` 后 `Slide.Export(...png/jpg)` 快照；
  - 连续两步图像**逐字节相同**则去重；每页 step 上限 12；整份资产上限 260 张（超出后每页只留 1–2 步，must 仍完整显示内容）；
  - 图片：导出 JPG → Pillow 转 **WebP**：display 最长边 1600、quality 72；thumb 宽 400、quality 65；
  - 页切换 `tr/trd` 由 `Slide.SlideShowTransition.EntryEffect` 映射（见 §7），未知→fade 450ms；
  - notes 取 `NotesPage` 文本（去掉页码占位），截断 2000 字。
- **媒体抽取**：`SaveCopyAs` 临时 .pptx → unzip：
  - `ppt/presentation.xml` 的 `<p:sldSz cx cy>` 得页面 EMU 尺寸；
  - 每页 `slides/slideN.xml` 找含 `<a:videoFile r:link>` / `<a:audioFile r:link>` 的 `<p:pic>`，
    取 `<p:spPr><a:xfrm>` 的 off/ext 归一化（x,y,w,h），rId 经 `slides/_rels/slideN.xml.rels` 解析到 `../media/*`；
    `TargetMode="External"` 的外链视频：跳过并在 manifest 该步 `media` 留空（不报错）；
  - ffmpeg：视频 `-c:v libx264 -preset veryfast -crf 26 -vf scale='min(1280,iw)':-2 -c:a aac -b:a 96k -movflags +faststart`；
    音频 `-c:a aac -b:a 80k -movflags +faststart`（.m4a）；失败再试 remux；仍失败跳过该媒体（日志）；
  - 视频/音频单文件≤200MB、总时长≤30min，超出跳过并记日志。
- **OSS 上传**：`oss2`（凭据复用 `web/deploy/sync_tools.load_creds()`，禁止打印）；`cache_control=public,max-age=31536000,immutable`；
  buildId = sha1(排序后的 asset 名+大小+manifest 摘要)[:10]；先传资产再 PATCH ready（避免半成品可播）。
  重转换时如旧 manifest 的 buildId 不同，可选删除旧 prefix（失败忽略）。
- **心跳**：每轮 + 长任务期间后台线程每 30s：`POST site_assets` upsert `{id:'ppt_agent', body:{online:true,seen_at:ms,queued:n,version:'1.0',host}}`（管理员 token）。
- **安装**：`web/ppt/install_agent.ps1` 注册计划任务 `PptConvertAgent`：每分钟、登录后 30s、
  InteractiveToken、pythonw、StartWhenAvailable、单实例；日志 `web/ppt/logs/agent-YYYYMMDD.log`；
  暂停开关 `web/ppt/ppt-agent.pause`。
- **测试**：`web/ppt/tests/`：
  - `make_fixture_pptx.py`：用 PowerPoint COM 生成 `fixture_deck.pptx`（3–5 页：文字/多形状动画/嵌入视频/备注/切换/4:3 与 16:9 各一）；
  - 纯逻辑单测（XML 解析、step 规划、归一化坐标、chunk 拼装、URL 构造、状态机；不依赖 COM）；
  - `test_convert_integration.py`：真实 COM 转换 fixture → 断言图片尺寸/数量、video mp4 可被 ffprobe 读出 H.264、manifest 字段合法、
    hotspot 0..1、step 去重；输出到 `web/ppt/tests/_out/`（过程产物，交付前清理）；
  - `test_cloud_contract.py`：用**测试账号 token**（学号 3260799999 / 姓名 测试账号，`rpc/class_verify` 换取）跑
    建行→分片→读→删→软删的 RLS 冒烟，并清理测试数据。
- 详见实现者补充的 `web/ppt/README.md`（运维手册）。

## 7. 页切换动效映射（转换机写，客户端执行）

> 2026-11-09 由转换机用真实 PowerPoint COM 探测修正（`convert.py` / `pptx_xml.py`；客户端只消费 `tr` 字符串，
> 取值仍只有下列 6 个，接口不受影响）：

| PowerPoint EntryEffect | manifest.tr |
|---|---|
| 0 / 无 | `none` |
| fade 家族（1793、3849…） | `fade` |
| push 家族（3852–3855…） | `push` |
| wipe 家族（2817–2820、2561–2564…） | `wipe` |
| zoom 家族（3073、3074…） | `zoom` |
| cover 家族（1281–1288…） | `cover` |
| cut（257、258、3844）/ 1537 / 3954–3956 / 其它 | `none` 或 `fade`（按转换机实测表，见 `pptx_xml.py`） |

- 客户端实现建议：`fade` 交叉淡入 320ms；`push` 上一层左移出+新层右移入 360ms；`wipe` 左→右裁切 380ms；
  `zoom` 1.04→1 透明度渐入 300ms；`cover` 新层从右覆盖 340ms；`none` 直切。步内切换一律 120–160ms 淡入。

## 8. 三端 UI / UX 要求（设计方向，实现时按各端既有风格落地）

> 详细设计参考（竞品拆解、取舍、组件规格）见 `web/ppt/DESIGN.md`（design-research 产出，客户端阅读后落地）。

### 8.1 通用交互（三端一致）

- **演示列表页**：卡片流（封面 + 标题 + 上传者 + 页数 + 状态）。顶部「上传 PPT」主按钮（不再写解释段落）。
- **上传流程**（最简 3 步）：选文件 → （可选改标题）→ 进度条 → 自动进入「排队转换」；失败可重试；取消即软删。
- **播放器**（核心，必须全是「课堂可用」级别）：
  - 黑色舞台，页面图片 `contain` 居中，按原始比例 letterbox；无任何站点导航/底栏；
  - 点击右 2/3 → 下一步；点击左 1/3 → 上一步；左右滑动切换；键盘 →/←/Space/PageDown/PageUp/Esc；
  - 底部自动隐藏控制条：上一页/下一页、`3/12 · 2/3`（页/步）、缩略图、备注、全屏、下载原件、关闭；
  - 顶部 2px 进度条（按 step 总进度）；左上角文件名（淡出）；
  - 视频热点：海报图上叠加圆形播放键；点击→内嵌播放（controls）；播放结束/关闭回当前步；
  - 缩略图抽屉：按页展示（`thumb`），点击跳页；当前页高亮；
  - 备注抽屉：显示当前页 `notes`（空则「本页无备注」）；
  - 预加载：当前步后 2 张图（最高优先级），再空闲加载相邻页缩略图；
  - 全屏：浏览器 Fullscreen API / 小程序 `pageOrientation:auto` + 横屏布局 / 安卓 immersive；
  - 手势/按键区不触发站点其它滑动逻辑（阻止冒泡）；
  - 双击舞台不缩放（避免误触）；长按不弹菜单。
- **状态文案（短）**：`上传中 34%`、`排队转换`、`转换中 61%`、`转换失败`（error 子行）、`转换机离线 · 排队中`、`还没有演示文件`。
- 空态：列表无内容时只给上传入口 + 一句「上传 PPT 后自动转换，任意设备可播放」。
- 删除：仅本人（或管理员）卡片上提供「删除」，二次确认后软删。

### 8.2 网页（`web/tools/index.html`，单文件、零依赖、无构建）

- 新工具 `TOOLS` 追加 `{k:"ppt", n:"演示", d:"PPT 上传自动转换 · 分步 + 视频 · 任意设备流畅播放"}`；
  不改变现有工具顺序/首页槽位逻辑；`renderAllCards` 自动收录；`gotoTab('ppt')` 分支加载列表。
- 风格：沿用暖白卡片 16px 圆角、雾青主色、克制的说明文字；手机优先、≥960px 桌面居中放宽。
- 播放器为 `position:fixed` 全屏覆盖层（`z-index` 高于通知弹层），独立 section 不存在滚动；退出恢复原 tab 与滚动位置。
- 不引入任何外部脚本/字体/CDN；OSS 仅 `<img>/<video>` 直连。
- 版本号 `APP_VER` 保持 `2.0.0`（用户要求下次成功上传发布前不改）。

### 8.3 微信小程序（`mp-class-tools`）

- 新页面：`pages/ppt/ppt`（列表+上传）、`pages/pptplay/pptplay`（播放器，`navigationStyle:custom` + `pageOrientation:auto`）；
  `app.json` 注册；`utils/tools.js` 目录加 `ppt` 工具（与网页同名「演示」）；
  `utils/cloud.js` 或新增 `utils/ppt.js` 实现 §4 全部接口 + 分片读取（`wx.chooseMessageFile` 读文件、
  文件系统分块读 base64、`wx.request` POST；注意内存与并发限制）；
- 播放器用 `<image>` + `<video>` 组件；全屏/横屏用页面配置；退出返回列表；不新增 tabBar。
- **`<image>` 必须带 `webp="{{true}}"`**（否则真机 .webp 全白；设计 RESEARCH DESIGN.md §3.2）；
  图片/视频加载失败时降级（保留上一张图 / 热点灰化「视频不可用」），不得白屏阻塞翻页。
- 小程序上传唯一入口 = `wx.chooseMessageFile` 从聊天记录选文件；空态按钮「从聊天选择」+ 一行小字「先把 .pptx 发到聊天」。
- **发布前用户需在微信公众平台把 `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com` 加入
  request 与 downloadFile 合法域名**（香港 OSS 默认域名能否过微信校验未查证，真机正式版必须验一张图+一段视频；
  若 OSS 配了防盗链，须放行空 Referer 与 `servicewechat.com`）。此风险写入交付说明。
- 版本号 `VERSION` 保持 `2.0.0`；源码完成后用户自行上传发布（交付说明写清）。

### 8.4 安卓（`android-class-tools`，Kotlin + Compose）

- 数据层 `data/ppt/`：OkHttp/PostgREST 接口（复用现有 network/auth/identity token）、分片上传（协程、进度回调、≤4 并行）；
- UI：`ui/screens/ppt/` 列表页 + 播放器页（沉浸式全屏、横向手势/按键、视频用现有可用的 VideoView/MediaPlayer 方案，
  不引入高风险的重量级新依赖；若项目已有 ExoPlayer/Coil 依赖则复用）；
- 工具目录注册入口、导航路由；验收：`:app:testDebugUnitTest` 全绿（原有 779 项不许回退）、`assembleRelease` 成功、
  关键页面 Compose @Preview 渲图自检；版本信息与 CHANGELOG 由实现者更新；APK 交付到桌面（Lead 统一交付）。

## 9. 测试与验收（全绿才算完成）

1. **契约测试（转换机 `test_cloud_contract.py`）**：RLS/分片/软删/心跳全通，测试数据清理干净。
2. **转换集成测试**：fixture 真实转换通过（图片/视频/manifest 断言）。
3. **端到端（Lead 执行）**：用测试身份真实上传一个 PPT（真实分片）→ 转换机转 → manifest 可达 → 三端播放器加载
   真实图片/视频（网页用 Edge headless 截图验收；小程序 automator/静态检查；安卓单测+预览图）。
4. **网页门禁**：新增 `v2_ppt_check.py` 全过（0 JS error / 上传流程 / 播放器交互 / 430px 无横向溢出）+
   既有回归（`overflow_check.py 430`、`v2_ui_check.py`、`v2_x5_anim_check.py` 等按现状可跑的）。
5. **小程序**：`node unit.js`、`sync_contract_test.js`、`staticcheck.py` 不回归；新增 ppt 单测通过。
6. **安卓**：单测全绿 + release 构建成功。
7. **清理**：过程产物（测试图片/临时 pptx/pdf/日志/`__pycache__`）交付前清掉；成果进桌面（Lead 统一）。

## 10. 红线（违反即返工）

- 网页仍必须**单文件、零依赖、无构建**；不得引入 npm/框架/CDN/外部字体；不得把任何密钥写进前端。
- 不得改动现有工具的既有行为/数据结构/同步契约（`zq_tools_v2`、UD v6、marks 等）；新功能只做增量。
- 不得碰 `me.furina.fun`、`deploy/creds.env` 内容与证书；不得打印/外传任何密钥、token。
- OSS 只允许转换机写；三端只读。不得在前端出现 OSS 写凭据。
- 隐私：不上传班级名单/学号/手机号等个人数据；演示文件属班级内容，按 §1 已知取舍处理并在交付说明写明。
- 版本号：网页 `APP_VER`、小程序 `VERSION` 在用户下次成功上传发布前**保持 2.0.0**；安卓版本号按现有规则处理。
- 不要动 `web/tools/notice-board-live-demo.html`（6MB 演示文件）与 `_backup/`。
