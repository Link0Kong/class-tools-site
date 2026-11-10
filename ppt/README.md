# PPT 演示 · 本机转换机运维手册（web/ppt）

> 唯一契约真源：`web/ppt/CONTRACT.md`（v1 + §11 v1.2，2026-11-10）。本目录实现契约 §3/§4/§6/§7/§11.2：
> Windows + Microsoft PowerPoint COM 把班级上传的 `.ppt/.pptx` 一次性转换成
> **分步图片（WebP）+ H.264 视频/AAC 音频 + 原样播放视频（deck.mp4）**，上传阿里云 OSS，并更新 CloudBase 队列状态。
> 三端播放器只加载图片/视频 → 老电脑也能流畅播放；视频不再依赖 PowerPoint 解码器。
> **v1.2（2026-11-10）**：新增「原样播放」——本机 PowerPoint `CreateVideo` 导出一份含
> 入场/强调/路径动画、页切换、内嵌视频与声音的 720p 视频，网络良好时三端默认播放它；
> 失败/超限只跳过视频，分步模式照常 ready。

```
[web/mp/android] --分片上传--> CloudBase ppt_decks(status=queued)
                                       │
        web/ppt/agent.py --once 每分钟轮询 ┤
        ├ 心跳 site_assets(id=ppt_agent)
        ├ 认领 → 拉分片拼源文件 → 上传原件 ppt/src/<id>/source.pptx → 删分片
        ├ convert.py：PowerPoint COM 分步渲染 → WebP + 抽取视频 → ffmpeg H.264
        │              + CreateVideo 原样播放视频（advance/章节/PlayOnEntry）→ deck.mp4
        ├ 上传资产 ppt/a/<id>/<buildId>/ → PATCH ready + manifest
        └ 任何异常 → PATCH failed + 中文 error（≤300 字）

存量 ready deck 补视频（不重传图片/媒体）：
        python agent.py --deck <id> --video-only [--dry-run]
```

---

## 1. 文件清单

| 文件 | 作用 |
|---|---|
| `agent.py` | 入口：轮询/认领/分片拼装/OSS 上传/心跳/token 刷新/单实例锁/进度 PATCH/日志；`--video-only` 为存量 ready deck 只补原样播放视频（从 OSS 下载 `source_key` 原件，只新增 `manifest.video`） |
| `convert.py` | 转换核心：PowerPoint 忙检测、可见性快照、去重、导出、媒体抽取、ffmpeg、WebP、manifest、buildId；**v1.2 视频阶段**（advance/章节/PlayOnEntry/CreateVideo/remux 或重编码/ffprobe）+ `export_video_only()` |
| `pptx_xml.py` | 纯函数：`presentation.xml` 尺寸、页序、媒体/热区解析、页面切换映射、step 规划/降级、manifest/video 校验、buildId；**v1.2** `compute_anim_end` / `compute_advance` / `compute_chapters` / `video_skip_reason` / `parse_ffprobe_json` |
| `oss_upload.py` | OSS 封装（`oss2`，凭据复用 `web/deploy/sync_tools.py::load_creds()`，不打印）；`download_to()` 供 `--video-only` 取回原件 |
| `install_agent.ps1` | 注册计划任务 `PptConvertAgent`（每分钟 + 登录后 30s、InteractiveToken、pythonw、StartWhenAvailable、单实例、`ExecutionTimeLimit=PT45M`） |
| `tests/make_fixture_pptx.py` | 用 COM 生成测试 fixture（16:9 五页 + 4:3 三页，含动画/退场/嵌入视频+音轨/外链/备注/切换） |
| `tests/test_pure_logic.py` | **97 项**纯逻辑单测（无 COM/网络；原 51 项 + v1.2 视频章节/限流/ffprobe/video 校验/`--video-only` 合并 46 项） |
| `tests/test_convert_integration.py` | **22 项**真实 COM 转换断言（图片尺寸/step 去重/视频/热区/4:3/外链跳过/笔记/耗时 + `manifest.video`、h264+aac、章节=页数、帧级验证、降级路径、真实 tuanri 16 页视频） |
| `tests/test_cloud_contract.py` | 云端 RLS/分片/失败路径/token 刷新/心跳冒烟 + 真实 OSS 视频链路 E2E |
| `logs/` | `agent-YYYYMMDD.log`（按天，保留 14 天）；`agent.lock` 单实例锁 |
| `work/` | 每个 deck 的临时工作目录（转换结束删除；陈旧目录 >24h 自动清） |
| `ppt-agent.pause` | 暂停开关（存在即本轮跳过） |

---

## 2. 快速开始（手动）

系统 Python：`C:\Users\Ko_Li\AppData\Local\Programs\Python\Python312\python.exe`
（已装 python-pptx 1.0.2 / Pillow 11.3 / oss2 / requests / pywin32；`pythonw.exe` 同目录）。
ffmpeg/ffprobe 在 PATH（`C:\Users\Ko_Li\bin\ffmpeg.exe`）。

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web\ppt

# 只转换、不碰云端（调试单文件）
python convert.py "C:\path\deck.pptx" --deck-id dtestfix --work-dir work\debug

# 跑一轮队列（计划任务等价命令）
python agent.py --once

# 调试指定 deck（真实链路：认领→原件→转换→资产→ready，含原样播放视频）
python agent.py --deck <deckId>

# 只读演练：不认领、不写云端、不上传 OSS（本地转换并打印 manifest 摘要）
python agent.py --deck <deckId> --dry-run

# v1.2 存量 ready deck 补原样播放视频（不重传图片/媒体，只新增 manifest.video）
python agent.py --deck <deckId> --video-only
# 先本地演练（从 OSS 下载原件 → 导出视频 → 打印，不上传/不写云端）
python agent.py --deck <deckId> --video-only --dry-run

# 只导出视频、不渲染图片（调试单文件；等价 convert.export_video_only）
python convert.py "C:\path\deck.pptx" --video-only --work-dir work\debug-video
# 跳过视频（只跑分步图片/媒体）
python convert.py "C:\path\deck.pptx" --no-video
```

> `--deck` 只对 `queued`（或调试用 `failed/processing`）有意义；已经是 `ready` 的 deck 会被
> 跳过，提示「如需重转先把 status PATCH 回 queued」。**只有 `--video-only` 接受 `ready` deck**。

---

## 3. 安装计划任务（生产）

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web\ppt

# 注册（不立即运行、注册后禁用；等你/Lead 统一 E2E 后自行启用）
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1 -NoRun -Disabled

# 查看（Logon Mode 必须是 "Interactive only"）
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1 -Show

# 启用 / 立即跑一轮 / 删除
schtasks /Change /TN PptConvertAgent /ENABLE
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1 -Run
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1 -Remove
```

任务定义（`schtasks /Query /TN PptConvertAgent /V /FO LIST` 可核对）：

- 动作：`C:\Users\Ko_Li\AppData\Local\Programs\Python\Python312\pythonw.exe "…\web\ppt\agent.py" --once`
  - **pythonw.exe（GUI 子系统）**：每分钟触发不会闪黑框；不要用 `powershell.exe/cmd.exe` 承载。
- 触发器：每 1 分钟 + **登录后 30s**（关机/睡眠错过的任务由 StartWhenAvailable 补跑）；
- 主体：当前用户、**InteractiveToken**（PowerPoint COM 自动化必须交互桌面，不能"不管用户是否登录"）；
- 设置：`StartWhenAvailable`、`IgnoreNew`（多实例等待）、`Hidden`、`StopIfGoingOnBatteries=false`、
  `ExecutionTimeLimit=PT45M`（v1.2：单任务转换预算 **30min** 含原样播放视频 + 收尾/排队余量；
  旧版本为 PT20M）；
- 单实例：`agent.py` 自己还有 `logs/agent.lock`（MSVCRT 文件锁），并发轮次直接跳过。

创建/启用后可以用 `-Show` 或 `schtasks /Query /TN PptConvertAgent` 核对；`Last Result: 267011`
是「任务尚未运行」的正常值（0x41303）。

> **v1.2 升级提示**：旧注册任务的 `ExecutionTimeLimit` 是 `PT20M`，需**重新运行一次
> `install_agent.ps1`**（保持 `-NoRun -Disabled`，不会启用任务）把任务定义更新为 `PT45M`
> 后再由 Lead 统一启用；`schtasks /Change` 改不了时间上限。

---

## 4. 暂停 / 恢复 / 看日志

- **暂停**：创建空文件 `web\ppt\ppt-agent.pause`（计划任务照常触发，但 agent 立即退出）；
- **恢复**：删除该文件；
- **日志**：`web\ppt\logs\agent-YYYYMMDD.log`（UTF-8，按天，14 天自动清理）。
  - 每轮：`round start` / `round done（action=...）`
  - 认领/进度/转换逐页耗时/媒体转码/OSS 上传/失败堆栈（已脱敏，绝不含 token）
  - 视频：`video: slide i/N animEnd=… media=… trans=… → advance=…`（每页时序）、
    `video: PowerPoint 导出完成 …`、`video: remux/reencode …`、
    `video: 完成 dur=… w=… h=… audio=… size=… 耗时 …（预估 …，chapters=…，末章 t=…，重编码=…）`；
    跳过时 `video: <原因>，跳过原样播放视频`（**不影响 ready**）
  - 补视频：`=== deck <id> 补视频开始` → `下载源文件` → `上传 deck.mp4 → ppt/a/<id>/<build>/deck.mp4`
    → `补视频完成：… manifest 仅新增 video（slides=N 未改动）`
  - `[skip] PowerPoint busy`：用户正开 PowerPoint，deck 保持 queued，下一轮自动再试
- **看心跳/队列**：云端 `public.site_assets` 行 `id='ppt_agent'`
  `body={online,seen_at,queued,version,host}`（`seen_at` 超过 180s 视为离线）；
- **日志里的进度**：进度按「已渲染页数」推进 5→85，视频阶段 82/89，媒体/资产上传 88→98，ready=100。

---

## 5. 耗时与体积预算（本机实测 2026-11-09 / v1.2 补充 2026-11-10）

| 场景 | 实测 |
|---|---|
| fixture 5 页 / 8 步 / 1 内嵌视频（16:9，含原样播放视频） | 整份转换 **10–12.5s**（其中视频导出 **3.8–6.6s**）；deck.mp4 **23.22s / 1.83MB** / 1280x720 H.264+AAC |
| fixture 3 页（4:3，含视频） | 整份转换 **7.2–7.4s**；deck.mp4 **13.10s / 0.21MB** / 960x720（无内嵌媒体→无音轨） |
| 真实 tuanri deck 16 页动画+切换（无媒体）`--video-only` 等价导出 | **11–37s**（CreateVideo 7–33s，冷启动/首次 CreateVideo 偏慢）；deck.mp4 **64.28s / 7.46MB** / 1280x720；chapters=16 |
| 真实 user deck `dmwalrdlgevz90l` 16 页含 225.6s 内嵌视频（源 38MB）| `--video-only --dry-run` 总 **127s**（其中 OSS 下载 38MB ≈ 81s、视频导出 37s/CreateVideo 18s）；raw 52.7MB → **deck.mp4 13.66MB / 303.60s / 1280x720 H.264+AAC**；chapters=16、末章 t=299.11<303.60（偏差 +1.19s） |
| 真实 deck 逐页渲染（分步图） | 约 **0.3–0.5s/页**（1600×900 JPG 快照 + WebP 编码） |
| 缩略图 / OSS 单对象上传 | 每页 1 张 ~2–5KB；单对象 0.3–0.6s（资产先传完才 PATCH ready） |
| PowerPoint 冷启动 | **首次可能 60s+**（本机实测 COM 冷启动 62s），之后 ~1s；单任务 30min 预算足够 |

> 计划任务每分钟一轮：`queued` 为空时一轮仅心跳 + 1 次查询（<2s）。
> 单 deck 上限：源文件 ≤64MiB、≤300 页、每页动画 step ≤12、整份图片 ≤260（超出自动降级为每页 1–2 步但不丢内容）。
> **原样播放视频**：>120 页或预估 >1800s 不生成；CreateVideo 最长等 30min；`deck.mp4` 体积
> <40MB 只 remux、≥40MB（或非 h264）自动重编码控体积（实测 1.8–13.7MB）。

磁盘预算（建议 C 盘 ≥2GB 空闲；v1.2 视频导出时更大）：

- `work/<deck>-<ts>/` 临时：源文件 + 每步 JPG（约 100–300KB/张）+ 处理中的 WebP；
  60 页 × 1.4 步 ≈ 21MB，转换结束/失败都会清理；陈旧目录 >24h 开机首轮清掉；
  **视频阶段另有** `tmp/video_deck.pptx`（源文件副本）+ `tmp/deck_raw.mp4`（PowerPoint 原始导出，
  实测 user deck 52.6MB，约为 deck.mp4 的 3–4 倍）+ `deck.mp4`；转换结束一起清理；
- OSS：每页主图 30–80KB + 缩略图 2–5KB，60 页 deck ≈ 3–6MB（38 页典型 ≈ 8MB 量级含多步）；
  **每个 deck 另加一份 `deck.mp4`**（实测 1.8MB–13.7MB，上限 40MB 阈值内自动控体积）；
- 日志：约 50–300KB/天，保留 14 天。

---

## 6. 转换规则（与契约一致）

- **step 渲染**：每页第 0 步=默认画面（隐藏所有「首个效果为单击入场」的形状）；`trigger=1/4`
  （单击/点形状）开新 step，`trigger=2/3`（与上一动画同时/之后）并入当前 step；
  逐步设置 `Shape.Visible` 后 `Slide.Export`；连续两步字节相同去重；
- **自动动画合并**：真实教学 PPT 大量使用 `afterPrevious/withPrevious`，按契约并入当页最终态
  （**内容不丢**，只是没有逐条出现的中间帧）；强调/运动路径也只取该步最终视觉状态（已知取舍）；
- **切换**：读 `Slide.SlideShowTransition.EntryEffect` → manifest `tr/trd`。
  家族映射用真实 PowerPoint 实测（不是猜）：fade=3849/1793、push=3852–3855、wipe=2817–2820/2561、
  zoom=3073/3074、cover=1281–1288、cut=257/258/3844→none，其余→fade；
  `trd` 用客户端友好默认值（fade 450 / push 400 / wipe 420 / zoom 380 / cover 400 / none 0），
  不跟随 PPT 默认 2s（否则网页切页发肉）；
- **图片**：`Slide.Export` JPG → Pillow WebP；display 最长边 1600、q72，**单张 >200KB 降 q62 重试一次**；
  thumb 宽 400、q65，**>25KB 再降一次**；
- **媒体**：`SaveCopyAs` 临时 pptx → zip 解析 `<a:videoFile>/<a:audioFile>` + `<a:xfrm>` 归一化热区；
  ffmpeg `libx264 -preset veryfast -crf 26 -maxrate 2500k -bufsize 5000k -vf scale='min(1280,iw)':-2
  -c:a aac -b:a 96k -movflags +faststart`；音频 AAC 80k `.m4a`；失败重试一次 remux，仍失败跳过并记日志；
  外链媒体（`TargetMode="External"`）跳过不报错；
- **备注**：`NotesPage` 取正文占位（去页码占位），截断 2000 字；
- **buildId** = sha1(排序后的资产名+大小+manifest 摘要)[:10]，manifest `base` =
  `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/a/<deckId>/<buildId>/`。

### 6.1 v1.2 原样播放视频（CONTRACT §11.1/§11.2，`deck.mp4`）

在分步图片/媒体抽取之后、**同一 PowerPoint 会话**内完成：

1. 对演示文稿 `SaveCopyAs` **临时副本**并以**可写**方式打开（绝不保存用户源文件）；
2. **逐页时序**（`pptx_xml.compute_anim_end`）：
   - `MainSequence` 按顺序：`trigger` 1（单击）/4（点形状）/3（之后）= 串行
     `start=prevEnd+TriggerDelayTime`、`end=start+Duration`；`trigger` 2（与上一动画同时）
     与上一个串行效果并行，取 `max end`；
   - 媒体页 `mediaMaxDur` = 该页内嵌媒体（已抽取/或原始媒体 ffprobe）最长时长，同页取 max；
   - `advance_i = clamp(max(3.0, animEnd+1.5, mediaMaxDur+1.5), 3.0, 600)` 秒
     （`>= media+1.5` 是关键：否则 PowerPoint 自动延长媒体页，破坏章节公式）；
3. 设置 `SlideShowTransition.AdvanceOnClick=False / AdvanceOnTime=True / AdvanceTime=advance_i`
   （**保留原页切换效果**），并对每个内嵌媒体形状（`Shape.Type==16`）设置
   `AnimationSettings.PlaySettings.PlayOnEntry=True`（不设置时导出的视频只有海报帧且**没有音轨**）；
4. **外链媒体**（`TargetMode="External"`）：本机无源文件时 PowerPoint 导出会**在该页卡约 90s**
   （实测 user deck 第 7 页使总时长 +87s）。导出前在临时副本上把该形状导出为静态图后删除（画面保留），
   再重算时序；源文件不动；
5. `Presentation.CreateVideo(FileName, True, 5, 720, 30, 80)` → 轮询 `CreateVideoStatus`
   （兜底文件大小连续 3s 稳定，最长 30min）→ 失败/超时只跳过视频；
6. 后处理：`ffprobe` 取 dur/w/h/音轨；产物 `<40MB` 只
   `ffmpeg -c copy -movflags +faststart` 重封装为 `deck.mp4`；**`>=40MB`（或非 h264）重编码**
   `-c:v libx264 -preset veryfast -crf 24 -c:a aac -b:a 96k -movflags +faststart` 控体积；
7. **章节**：`chapters[0].t=0`，`i>0` 时
   `t_i = Σ_{j<i} advance_j + Σ_{j<=i} transDur_j`（`transDur` = `SlideShowTransition.Duration`，
   无切换记 0；PowerPoint 把切换时长插在页之间），再 clamp 到 `[0, dur-0.1]` 且单调不减；
   计算超出实测 dur 按比例压缩；实测 dur 与预估偏差 >max(3s, 2%) 记 warning（章节可能漂移）；
8. **降级**：页数 >120 或预估总时长 >1800s 或导出/后处理失败/超时 → **跳过视频只记 warning**，
   分步模式照常 `ready`，`manifest` 不含 `video`（三端回退分步）；`manifest.video` 缺失不是错误；
9. 上传 `deck.mp4` 到**同一 build 目录**，`manifest.video` 写好后（`PATCH ready` 前）才允许播放。

`--video-only` 补转：用 `source_key` 从 OSS 下载原件 → 只导出视频 → 传进**原 build 目录** →
`PATCH {manifest}` 时 `dict(manifest)` 拷贝后**只新增 `video`**（slides/img/media/notes/base 原样保留，
旧目录其它资产不动）；源文件缺失返回中文错误「源文件缺失：OSS 上找不到 …，请重新上传源文件后转换」。

---

## 7. 云端行为（agent）

- **身份**：管理员 token 读 `C:\briefdesk\secrets\class-token.json`（`{token,exp}`）；
  距过期 <1h 时用 `POST rpc/class_verify`（PUBLISHABLE KEY + `cloudbaserc.local.json`
  `functions[].envVariables.CLASS_ADMIN_SID/NAME`）刷新并写回（保留原字段）。
  **日志/输出绝不打印 token、AK/SK**（`agent.sanitize()` 统一脱敏）。
- **一轮**：心跳 → `GET status=eq.queued&deleted=eq.false&order=created_at.asc&limit=1` →
  **先查 PowerPoint 忙**（忙则跳过、deck 保持 queued）→ 认领（`PATCH ...&status=eq.queued` 条件更新，
  被抢则本轮放弃）→ 拉分片（每页 8 片，避免大响应）→ 校验 `source_size`/扩展名 →
  上传原件 → **立即删分片** → 转换（心跳线程每 30s）→ 上传资产 → **最后** PATCH ready
  （manifest/slide_count/step_count/aspect/cover_url/source_key/converter/converted_at）。
- **失败**：任何异常 PATCH `failed` + 中文 error（≤300 字，前端直接展示），并保证分片已删；
  用户在前端点「重试」→ `status=queued` 后下一轮再转。**失败不会自动重试**（避免坏文件死循环）。
- **PowerPoint 安全**：只读打开临时副本；`DisplayAlerts=ppAlertsNone`；
  若已有 POWERPNT 进程且 `Presentations.Count>0`（用户可能正在编辑）→ 本轮跳过；
  空实例先 Quit 再新建；单任务 30min 截止（v1.2）；收尾只 Quit 无用户文档的实例。
- **重转换**：同一 deck 再次转换会生成新 buildId 路径（新目录），旧 build 目录不会自动删除
  （契约里写的是"可选删除"；需要清理由 Lead/运维手动删 `ppt/a/<deckId>/<旧buildId>/`）。
- **`--video-only` 补视频**（v1.2，CONTRACT §11.2.3）：`GET` 该 deck → 校验 `status=ready` 且
  `manifest.slides` 非空 → 用 `source_key` 从 OSS 下载原件（缺失则中文报错并退出码 1）→
  `convert.export_video_only()`（不渲染图片、不抽媒体）→ 上传 `deck.mp4` 到**原 build 目录** →
  `PATCH {manifest}`：`dict(manifest)` 浅拷贝后**只新增 `video`**，`slides/media/notes/base` 原样保留；
  状态保持 `ready`（视频失败只记 warning/退出码，不把 deck 改 failed）。`--dry-run` 只下载+导出+打印。

---

## 8. 常见故障排查

| 现象 | 排查/处理 |
|---|---|
| 列表一直「排队转换」且心跳显示离线 | 计划任务被禁用/暂停文件存在。`schtasks /Query /TN PptConvertAgent`、`install_agent.ps1 -Show`；删除 `ppt-agent.pause`；`-Run` 试跑并看日志 |
| 日志 `[skip] PowerPoint busy` | 用户正开 PowerPoint（或有文档）；关掉 PowerPoint 后下一轮自动转换（deck 仍 queued） |
| 日志 `PowerPoint 进程存在但无法连接` | 可能是崩溃残留的 POWERPNT 僵尸进程。任务管理器结束 `POWERPNT.EXE` 后下一轮恢复；**先确认用户没在编辑/没未保存文档** |
| 日志 `退出时检测到 PowerPoint 有 N 个文档…保留实例` + 一直「排队转换」 | 上一轮转换被强制中断（计划任务超时/进程被杀）留下的残留实例，会让后续每轮判 busy。任务管理器结束 `POWERPNT.EXE`（先确认用户没在编辑）后下一轮自动恢复；本目录测试用 `python tests\test_convert_integration.py` 收尾会打印残留检查提示 |
| 日志 `PowerPoint 无法打开该文件（可能加密/损坏）` | 源文件加密/损坏/格式伪装 → 前端显示「转换失败」+ 中文原因；需用户重传 |
| 日志 `缺少 pywin32/oss2` | 用了错误解释器（venv 没装依赖）。计划任务必须用系统 pythonw（脚本默认 `C:\Users\Ko_Li\AppData\Local\Programs\Python\Python312\pythonw.exe`） |
| 日志 `OSS 凭据缺失` / `401/403` | 检查 `web/deploy/creds.env`（不要打印内容）与 `class-token.json` 是否可读；token 会自动刷新 |
| 日志 `ffmpeg ... 失败` | 检查 PATH 中 ffmpeg（`ffmpeg -version`）；个别媒体失败会跳过该媒体（图片/其他内容仍可用） |
| 日志 `云端/配置错误` 且退出码 1 | `publish_key.txt`/token 文件/网络问题；修好后下一轮自动恢复（计划任务每分钟） |
| 转换很慢（>2min） | 看日志逐页耗时；页数多/母版/大图多会慢；首次冷启动 PPT 更慢。单任务 30min 截止后 PATCH failed「转换超时」 |
| 转换窗口出现在桌面 | PowerPoint 16 不允许 `Visible=False`（已实测），脚本会把窗口**最小化**；只在有任务时出现，转换完自动退出 |
| 磁盘增长 | `work/` 陈旧目录自动清（>24h）；OSS 旧 build 目录需手动清；`logs/` 14 天自动清 |
| **没有原样播放视频**（manifest 无 video，三端走分步） | 日志搜 `video:`：`页数超限`/`预估时长超限`(>120 页 / >30min) 是契约内跳过；`CreateVideoStatus=Failed`/`导出超时`/`ffmpeg 失败` 属导出失败，deck 仍 ready。重试：`python agent.py --deck <id> --video-only` |
| `video: 实测时长与预估偏差 …` warning | 多为媒体页自动延长或外链媒体；章节可能漂移。确认日志有 `清理外链媒体`（本机无外链文件时 PowerPoint 会卡 ~90s/页，已自动静态图替换）；必要时用 `--video-only` 重转 |
| 视频太大（>40MB） | 已自动重编码（crf24/aac96k）。日志 `video: reencode X MB → Y MB`；仍偏大属内容本身（长视频），弱网端会回退分步 |
| `--video-only` 报「源文件缺失」 | 该 deck 是早期数据（无 `source_key` 或 OSS 原件已清）。重新上传源文件后转换，或先 `PATCH status=queued` 让转换机重跑 |
| `--video-only` 报「只有 ready 的 deck 才能补视频」 | 只对已 ready 的存量 deck 补视频；queued/processing/failed 走正常转换流程 |

---

## 9. 测试（本机可复跑）

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web\ppt

# 1) 生成 fixture（首次/需要重生成时；会启动 PowerPoint COM）
python tests\make_fixture_pptx.py

# 2) 纯逻辑单测（无 COM/网络，秒级；97 项）
python tests\test_pure_logic.py -v

# 3) 真实 COM 转换集成（16:9 + 4:3 + 降级路径 + 真实 tuanri 16 页视频；约 30–75s）
python tests\test_convert_integration.py -v

# 4) 云端契约 + 真实 OSS 链路（需要网络；会产生 2 个保留的 ready fixture deck 供网页验收）
python tests\test_cloud_contract.py -v
```

> v1.2 集成测试覆盖：fixture 转换出 `manifest.video`（ffprobe 断言 **h264 + aac 音轨**、dur>0、
> chapters 数==页数且单调）、**帧级验证**（媒体页视频段内**间隔 1s** 抽 3 帧、最大平均差 >2.0，
> 证明真的播放而非海报）、CreateVideo 抛错的**降级路径**（仍 ready + manifest 无 video + warning）、
> 真实 tuanri deck（16 页动画+切换）`export_video_only` 导出 chapters=16 / dur>0 / 记录耗时。
> 真实用户 deck 的 `--video-only` 补转需网络 + 大文件下载，不放进自动化测试（运维手动跑）。

- 测试账号：学号 `3260799999` / 姓名「测试账号」（RLS 冒烟用，token 不落日志）；
- 集成测试每个转换类开始前会**等待残留 PowerPoint 退出**（最多 180s；`Quit()` 返回后
  POWERPNT.EXE 可能还要数秒~数分钟才真正结束，连续转换/补转时尤其明显）；若等待超时
  （例如用户正在编辑 PowerPoint）则 `skip` 该类而不是报错，并打印原因。
- `test_cloud_contract.py` 会**保留** 2 个 ready deck（标题 `测试·嵌入视频演示`、`测试·4:3 演示`），
  供网页端播放器/视频热点验收；其余临时 deck/chunks/failed 数据在 `finally` 里清理；
  交付前由 Lead 统一 soft-delete 这 2 个 deck 并清 OSS 测试 prefix；
- 过程产物写 `tests/_out/`（`fixture_deck*.pptx`、`work_16x9/`、`work_4x3/`、`work_degraded/`、
  `work_tuanri/`、`media/clip.mp4`、`frame_media_*.jpg` 抽帧），交付前清理（fixture 可由脚本重新生成）。

---

## 10. 已知限制 / 取舍（务必如实转达）

1. **自动动画合并**：`afterPrevious/withPrevious` 动画并入当页最终态（契约 §6）。
   真实中文教学 PPT 大量使用自动动画 → 网页上看到的是每页最终画面（**内容不丢**，但不是逐条出现）。
   已确认不做 auto-step 模式（Lead 决策 2026-11-09）。**v1.2 原样播放视频可看到完整动画节奏**。
2. **强调/运动路径**只取该步最终视觉状态，不是逐帧动画（分步模式）；原样视频里是完整逐帧动画。
3. **隐藏幻灯片**仍会被转换（保证内容完整；不模拟"放映时跳过隐藏页"）。
4. **外链媒体**跳过（PPT 里链接到本机/网络路径的视频无法在网页播放），manifest 该步媒体为空；
   原样播放视频里该形状用**海报静态图**替代（避免 PowerPoint 导出时等待外链文件 ~90s/页）。
5. **转换机需开机**：离线时任务只排队；页面显示「转换机离线 · 排队中」。
6. **PowerPoint 窗口**：PowerPoint 16 不允许隐藏应用窗口，转换期间窗口会最小化出现；转换完 Quit。
7. **单任务超时**：v1.2 转换预算 30min（含视频）；超时只影响视频时**跳过视频、分步照常 ready**；
   若 PowerPoint COM 调用本身卡死（极端情况），计划任务 `ExecutionTimeLimit=PT45M` 会强制结束；
   下一轮重新开始（deck 已 failed 需用户重试）。
8. **并发**：单实例锁 + PowerPoint 单实例 → 同一时刻只转一个 deck；队列按 `created_at asc` 串行。
9. **单 deck 上限**：源 ≤64MiB、≤300 页、每页 step ≤12、整份图片 ≤260（超出降级为每页 1–2 步不丢内容）；
   媒体单文件 ≤200MB、总时长 ≤30min、单段 >30min 只转前 30min。
   **原样播放视频另有限制：>120 页或预估 >1800s 不生成视频**；单页最长 600s（超长媒体页章节会截断）。
10. **旧 build 不自动删**：同 deck 重转换生成新 buildId 目录，旧目录需手动清理；`--video-only`
    写回原 build 目录的 `deck.mp4`（manifest.base 不变）。
11. **token 写回**：刷新后的管理员 token 会写回 `C:\briefdesk\secrets\class-token.json`（保持 `{token,exp}` 格式）。
12. **视频章节 ±1s**：章节时间按探测公式计算（PowerPoint 把切换时长插在页之间），实测偏差
   （fixture +0.22s、tuanri +1.12s、user deck +1.19s）；播放器 seek 后内容误差在 ±1s 量级。
    若某 deck 出现明显漂移，日志会有 `实测时长与预估偏差` warning（可重转/降级分步）。
13. **视频体积**：720p q80 原始导出可能很大（user deck 16 页含 225s 视频：raw 52.6MB）；≥40MB 自动
   重编码（crf24/aac96k）后典型 **7–40MB**（user deck 13.7MB、tuanri 16 页 7.5MB、fixture 1.8MB）。
    弱网/节省流量时三端默认回退分步。
14. **视频为自动节奏**：单击动画被合并为自动连续播放；需要自主控制节奏时切「分步浏览」。
15. **降级不影响 ready**：`manifest.video` 是可选字段；缺失/加载失败三端回退分步，不是转换失败。

---

## 11. 安全红线

- 本目录代码/日志**不得**出现 token、AK/SK、手机号、学号等敏感信息（日志统一 `sanitize()`）；
- OSS 写凭据只在本机 `web/deploy/creds.env`（或环境变量），三端只读，前端不出现任何写入凭据；
- 测试用身份只用测试账号 `3260799999`；
- 不修改 `web/deploy/creds.env`、证书、`web/tools/index.html`、云函数/迁移 SQL。
