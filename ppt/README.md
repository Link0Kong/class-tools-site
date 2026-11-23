# PPT 演示 · 本机转换机运维手册（web/ppt）

> 唯一契约真源：`web/ppt/CONTRACT.md`（v1/v1.2 + **§12 v2.0 重定义**，2026-11-10）。
> 本目录实现契约 §3/§4/§6/§7/§11.2/§12：Windows + Microsoft PowerPoint COM 把班级上传的
> `.ppt/.pptx` 转换成 **v2.0 兼容性处理包**（默认）或**旧版分步图片+原样播放视频**（`--legacy`），
> 上传阿里云 OSS，并更新 CloudBase 队列状态。
>
> **v2.0（2026-11-10 22:05，用户重定义）**：本工具 = **PPT 兼容性处理与多端下载中心**。
> 上传 PPT → 转换机自动做**不降质**的兼容性处理 → 网页/小程序/安卓都能**下载处理后的文件**
> （`compat.pptx` 兼容版 / `preview.pdf` / `original.<ext>` 原件），在教室电脑/自己电脑/手机上用
> PowerPoint/WPS/PDF 查看器打开，动画、媒体、版式与清晰度保持原样。在线播放降级为旧 deck 的可选「预览」。
>
> **禁止**把 PPT 渲染成图片/视频冒充兼容版；**禁止**对图片/视频重编码或降分辨率（质量红线，见 §6.2）。
>
> **v2.0.1（2026-11-11，用户反馈「嵌入视频的 PPT 下载后视频依旧不可用」）**：compat 流水线新增
> **断链视频修复**——当视频关系是 `TargetMode=External` 且 Target 为 `NULL`/空/本机不存在（断链），
> 但同一形状的 `p14:media` 指向包内有效内嵌副本时，在 SaveAs 之后用 zip 级 OOXML 修复把 video 关系
> 内部化（Target 指向内嵌 media、去掉 TargetMode），下载后 PowerPoint 用包内视频播放；
> 修复记录写入 `manifest.compat.repairs`，媒体字节绝不改动（详见 §6.3）。

```
[web/mp/android] --分片上传--> CloudBase ppt_decks(status=queued)
                                       │
        web/ppt/agent.py --once 每分钟轮询 ┤
        ├ 心跳 site_assets(id=ppt_agent)
        ├ 认领 → 拉分片拼源文件 → 上传原件 ppt/src/<id>/source.<ext> → 删分片
        ├ convert.py：PowerPoint 临时副本 → compat.pptx(字体嵌入/规范化) + preview.pdf
        │              + cover.webp + original.<ext>（绝不重编码媒体/不动源文件）
        │              → 断链视频修复（zip 级 OOXML，v2.0.1）→ manifest v2
        ├ 上传资产 ppt/a/<id>/<buildId>/ → PATCH ready + manifest（进度 10/30/55/75/85/95）
        └ 任何异常 → PATCH failed + 中文 error（≤300 字）

存量 ready deck 补兼容文件（保留旧 slides/video 预览字段）：
        python agent.py --deck <id> --compat-only [--dry-run]
旧版流程（分步图片 + 原样播放视频，仅运维调试）：
        python agent.py --once --legacy / python agent.py --deck <id> --legacy
```

---

## 1. 文件清单

| 文件 | 作用 |
|---|---|
| `agent.py` | 入口：轮询/认领/分片拼装/OSS 上传/心跳/token 刷新/单实例锁/进度 PATCH/日志；v2.0 默认 `--once` 走 **compat**（`--legacy` 保留旧流程）、`--compat-only --deck <id>` 为存量 ready deck 补兼容文件并合并 manifest（保留旧 slides/video）；**上传后 best-effort 预热 ECS 文件缓存**（build 根目录 4 文件 + `media/` 子目录独立媒体；`PPT_WARM_BASE`，见 §7.1） |
| `convert.py` | 转换核心：v2.0 `convert_compat()`（compat.pptx 字体嵌入/规范化 + preview.pdf + cover.webp + original.<ext> + manifest v2 + sha256；不重编码媒体）；v1.2 `convert_deck()`/`export_video_only()`（分步图+原样播放视频）保留给 `--legacy` |
| `pptx_xml.py` | 纯函数：尺寸/页序/媒体/切换/step 规划/buildId；v1.2 视频章节/限流/ffprobe/`manifest.video` 校验；**v2.0** 文件名清洗/路径尾/外链媒体告警/包内媒体 sha256/`manifest.files` 校验（v1/v2 兼容）；**v2.0.1** `repair_broken_video_links` 断链视频修复（rels 重写） |
| `oss_upload.py` | OSS 封装（`oss2`，凭据复用 `web/deploy/sync_tools.py::load_creds()`，不打印）；`download_to()` 供补转取回原件 |
| `install_agent.ps1` | 注册计划任务 `PptConvertAgent`（每分钟 + 登录后 30s、InteractiveToken、pythonw、StartWhenAvailable、单实例、`ExecutionTimeLimit=PT45M`；compat 转换预算 ≥20min） |
| `tests/make_fixture_pptx.py` | 用 COM 生成测试 fixture（16:9 五页、4:3 三页、**.ppt 旧格式三页**；含动画/退场/嵌入视频+音轨/外链/备注/切换） |
| `tests/test_pure_logic.py` | **171 项**纯逻辑单测（无 COM/网络；v1.2 视频 46 项 + v2.0 compat 26 项 + v2.0.1 断链视频修复 8 项 + v2.2 媒体编码兼容 20 项 + **v2.3 单独下载 9 项**：文件名/页号引用/manifest 校验/上传 key/预热 URL；另含预热/强制刷新 8 项） |
| `tests/test_convert_integration.py` | **22 项**真实 COM 旧链路断言（图片尺寸/step 去重/视频 hot区/4:3/外链跳过/笔记/耗时 + v1.2 video/帧级/降级/tuanri；`--legacy` 路径回归） |
| `tests/test_compat_integration.py` | **36 项** v2.0 compat 真实 COM 断言（manifest v2/files 存在+sha/size、页数=源、PowerPoint 可打开、**keep 媒体 sha256 逐字节一致**、PDF 页数、cover、字体、外链告警且不删除、`.ppt→pptx`、失败路径 + 断链视频修复 6 项 + 媒体编码兼容 6 项 + **单独下载 5 项**：注入被引用 HEVC/WMA 媒体 → media_files 3 个、页号/时长/大小/sha、单独文件与 compat 字节一致、上传 key、PowerPoint 可打开） |
| `tests/test_cloud_contract.py` | 云端 RLS/分片/失败路径/token 刷新/心跳冒烟 + 真实 OSS E2E（E2E 显式走 `legacy=True` 保持旧断言） |
| `logs/` | `agent-YYYYMMDD.log`（按天，保留 14 天）；`agent.lock` 单实例锁 |
| `work/` | 每个 deck 的临时工作目录（转换结束删除；陈旧目录 >24h 自动清） |
| `ppt-agent.pause` | 暂停开关（存在即本轮跳过） |

---

## 2. 快速开始（手动）

系统 Python：`%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe`
（已装 python-pptx 1.0.2 / Pillow 11.3 / oss2 / requests / pywin32；`pythonw.exe` 同目录）。
ffmpeg/ffprobe 在 PATH（`%USERPROFILE%\bin\ffmpeg.exe`）。

```powershell
cd %USERPROFILE%\.openclaw\workspace\web\ppt

# ---- v2.0 默认：兼容性处理（不降质 + 多端下载）----
# 只转换、不碰云端（调试单文件；输出 compat.pptx/preview.pdf/cover.webp/original.<ext>）
python convert.py "C:\path\deck.pptx" --compat --work-dir work\debug-compat

# 跑一轮队列（计划任务等价命令；新 deck 默认走 compat）
python agent.py --once

# 调试指定 deck（真实链路：认领→原件→compat→上传→ready；默认 compat）
python agent.py --deck <deckId>

# 只读演练：不认领、不写云端、不上传 OSS（本地实际转换并打印摘要）
python agent.py --deck <deckId> --dry-run

# v2.0 存量 ready deck 补兼容文件（不重传旧预览资产，只新增 files/compat）
python agent.py --deck <deckId> --compat-only
# 先本地演练（从 OSS 下载原件 → 实际 compat 导出 → 打印，不上传/不写云端）
python agent.py --deck <deckId> --compat-only --dry-run

# ---- 旧链路（v1.2 分步图片 + 原样播放视频，运维调试用）----
python agent.py --once --legacy                    # 旧链路跑一轮
python agent.py --deck <deckId> --video-only       # 存量 deck 补 deck.mp4
python convert.py "C:\path\deck.pptx" --work-dir work\debug          # 旧分步图+视频
python convert.py "C:\path\deck.pptx" --video-only --work-dir work\debug-video
```

> `--deck` 只对 `queued`（或调试用 `failed/processing`）有意义；已经是 `ready` 的 deck 会被
> 跳过，提示「如需重转先把 status PATCH 回 queued」。**只有 `--compat-only` / `--video-only`
> 接受 `ready` deck**。

---

## 3. 安装计划任务（生产）

```powershell
cd %USERPROFILE%\.openclaw\workspace\web\ppt

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

- 动作：`%USERPROFILE%\AppData\Local\Programs\Python\Python312\pythonw.exe "…\web\ppt\agent.py" --once`
  - **pythonw.exe（GUI 子系统）**：每分钟触发不会闪黑框；不要用 `powershell.exe/cmd.exe` 承载。
- 触发器：每 1 分钟 + **登录后 30s**（关机/睡眠错过的任务由 StartWhenAvailable 补跑）；
- 主体：当前用户、**InteractiveToken**（PowerPoint COM 自动化必须交互桌面，不能"不管用户是否登录"）；
- 设置：`StartWhenAvailable`、`IgnoreNew`（多实例等待）、`Hidden`、`StopIfGoingOnBatteries=false`、
  `ExecutionTimeLimit=PT45M`（单任务预算：**v2.0 compat ≥20min**；v1.2 legacy 视频 30min + 收尾余量）；
- 单实例：`agent.py` 自己还有 `logs/agent.lock`（MSVCRT 文件锁），并发轮次直接跳过。

创建/启用后可以用 `-Show` 或 `schtasks /Query /TN PptConvertAgent` 核对；`Last Result: 267011`
是「任务尚未运行」的正常值（0x41303）。

> **升级提示**：任务定义里的 `ExecutionTimeLimit` 只能在注册时写入（`schtasks /Change` 改不了），
> 升级 `install_agent.ps1` 后需**重新运行一次** `install_agent.ps1 -NoRun -Disabled` 更新定义
> （仍保持禁用），再由 Lead 统一启用。v2.0 沿用 PT45M，无需再改。

---

## 4. 暂停 / 恢复 / 看日志

- **暂停**：创建空文件 `web\ppt\ppt-agent.pause`（计划任务照常触发，但 agent 立即退出）；
- **恢复**：删除该文件；
- **日志**：`web\ppt\logs\agent-YYYYMMDD.log`（UTF-8，按天，14 天自动清理）。
  - 每轮：`round start` / `round done（action=...）`
  - 认领/进度/OSS 上传/失败堆栈（已脱敏，绝不含 token）
  - **compat（v2.0 默认）**：`compat: 源 …（N 页，页面 WxH pt）` → `compat: 兼容包已生成 …` →
    `compat: 内嵌媒体 sha256 与源包逐字节一致（M 个，未重编码）` →
    `compat: 字体部件 N 个（embedTrueTypeFonts=…, saveSubsetFonts=…）` →
    `compat: preview.pdf …MB / N 页；cover=cover.webp` →
    `compat 完成：N 页 / compat …MB sha=… / pdf N 页 … / 字体 N / 外链媒体 N / 耗时 … / build=…`；
    外链媒体逐条 `WARN compat: 外链视频 … 处未随文件携带（第 N 页，路径尾 …）`
  - 补兼容文件：`=== deck <id> 补兼容文件开始` → `下载源文件` → `上传兼容文件 N 个 → <原 build 前缀>`
    → `补兼容文件完成：… manifest 仅新增 files+compat（slides=N, video=True 原样保留）`
  - v1.2 legacy：`video: slide i/N animEnd=… → advance=…`、`video: 完成 dur=…` 等
  - `[skip] PowerPoint busy`：用户正开 PowerPoint，deck 保持 queued，下一轮自动再试
- **看心跳/队列**：云端 `public.site_assets` 行 `id='ppt_agent'`
  `body={online,seen_at,queued,version,host}`（`seen_at` 超过 180s 视为离线）；
- **日志里的进度**：compat 阶段 10（下载源文件）→30（PowerPoint 处理）→55（生成兼容包）→
  75（导出 PDF）→85（上传）→95（写入 ready）→100；legacy 旧流程按页 5→85 / 90→98。

---

## 5. 耗时与体积预算（本机实测，2026-11-10 v2.0 补充）

**v2.0 compat（默认流程，不降质）**

| 场景 | 实测 |
|---|---|
| fixture 5 页 / 1 内嵌视频+音轨 / 外链媒体 1 处（16:9） | 转换 **2.1–2.6s**（SaveAs 0.2s、PDF 0.2–0.5s）；compat.pptx **0.32MB** / PDF **69KB / 5 页** / 字体部件 **3** / 外链告警 1 条 / cover.webp 12KB |
| fixture 3 页（4:3） | 转换 **1.5–2s**；compat 0.18MB / PDF 28KB / 3 页 / 字体 3 / cover 1600x1200 |
| fixture `.ppt`（97-2003，3 页） | 转换 **1.8–2s**；→ compat ext=pptx、0.19MB / PDF 3 页 / `converted_from=ppt` |
| **真实 user deck `dmwalrdlgevz90l`**（16 页、源 38,016,533B、含 225.6s 内嵌视频 + 第 7 页**断链视频**） | **compat 转换 7.2s**（SaveAs 0.5s + PDF ~3s + 断链修复/校验/封面/收尾）；compat.pptx **39,063,743B** sha256 `f096f55e213f9e5267112690f3729c96e2fe44f7cc107f66be3183f752254c35`；PDF **1,105,861B / 16 页** sha256 `035e0baa45c0a6c49e13b92af8739b29abff88b7e36d85ca376576b56d6c7425`；字体部件 **6**；**断链视频修复 1 处（第 7 页 `视频一_播放` → 内嵌 media1.mp4 20,158,796B）**，warnings/external_media 均已清空；媒体 15 个 sha256 与源包集合完全一致（media1 `7c7cf971af68…`、media2 `1792662734c6…` 不变）；`--compat-only --dry-run` 总耗时含 OSS 下载 ≈250–550s（本机网络波动） |
| PowerPoint 冷启动 | 首次可能 60s+，之后 ~1s |
| Quit 收尾 | 自动化实例 Quit 后偶发滞留 60s+ → 3s 宽限后强制结束 `/AUTOMATION`；单次转换总耗时 **2–7s**（修复前 60–80s） |

**v1.2 legacy（`--legacy` / 旧 deck 预览，非默认）**

| 场景 | 实测 |
|---|---|
| fixture 5 页 / 8 步 / 1 内嵌视频（16:9，含原样播放视频） | 整份转换 **10–12.5s**（其中视频导出 **3.8–6.6s**）；deck.mp4 **23.22s / 1.83MB** / 1280x720 H.264+AAC |
| fixture 3 页（4:3，含视频） | 整份转换 **7.2–7.4s**；deck.mp4 **13.10s / 0.21MB** / 960x720（无内嵌媒体→无音轨） |
| 真实 tuanri deck 16 页动画+切换（无媒体）`--video-only` 等价导出 | **11–37s**（CreateVideo 7–33s，冷启动/首次 CreateVideo 偏慢）；deck.mp4 **64.28s / 7.46MB** / 1280x720；chapters=16 |
| 真实 user deck `dmwalrdlgevz90l` 16 页含 225.6s 内嵌视频（源 38MB）| `--video-only --dry-run` 总 **127s**（其中 OSS 下载 38MB ≈ 81s、视频导出 37s/CreateVideo 18s）；raw 52.7MB → **deck.mp4 13.66MB / 303.60s / 1280x720 H.264+AAC**；chapters=16、末章 t=299.11<303.60（偏差 +1.19s） |
| 真实 deck 逐页渲染（分步图） | 约 **0.3–0.5s/页**（1600×900 JPG 快照 + WebP 编码） |

> 计划任务每分钟一轮：`queued` 为空时一轮仅心跳 + 1 次查询（<2s）。
> 单 deck 上限：源文件 ≤64MiB、≤300 页；legacy 另有每页 step ≤12 / 图片 ≤260 降级。
> **compat 体积**：compat.pptx ≈ 源 + 字体子集（user deck 38MB→39MB）；
> PDF 另计（16 页 1.22MB）；原件 `original.<ext>` = 源大小。单 deck 总传输 ≈ 2×源文件 + PDF。
> legacy 视频：>120 页或预估 >1800s 不生成；`deck.mp4` 实测 1.8–13.7MB。

磁盘预算（建议 C 盘 ≥2GB 空闲；compat 转换时约 3–4 倍源文件）：

- compat 阶段 `work/<deck>-compat-<ts>/`：源副本 + `compat.pptx` + `original.<ext>` + `pdf_src.pptx` +
  `preview.pdf` + cover ≈ 源 × 3–4（user deck 38MB → 约 160MB），转换结束/失败都会清理；
  `--dry-run` 时**保留下载/产物**供核对 sha256/页数/媒体（成功 dry-run 不清理，见日志路径）；
- legacy 阶段另有每步 JPG（约 100–300KB/张）+ `tmp/deck_raw.mp4`（约为 deck.mp4 的 3–4 倍）；
- OSS：compat 每个 deck = compat.pptx（源+字体）+ original.<ext>（源）+ preview.pdf + cover；
  legacy 每 deck ≈ 图片 3–8MB + deck.mp4 1.8–13.7MB；
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

### 6.2 v2.0 compat 兼容性处理（**默认流程**，CONTRACT §12）

**定位**：上传 PPT → 自动做**不降质**兼容性处理 → 三端下载处理后的文件（不再以在线播放为主）。
`agent.py --once` 默认走本节；旧分步/视频链路保留为 `--legacy`（运维调试）。

输出（同一 build 目录 `ppt/a/<deckId>/<buildId>/`）：`compat.pptx` + `preview.pdf` +
`cover.webp` + `original.<ext>`；`manifest` v2：

```jsonc
{"v":2, "w":960, "h":540, "slides":[], "files":{
   "compat":{"s":"compat.pptx","size":…,"sha256":"…","ext":"pptx","name":"<安全标题>.pptx"},
   "pdf":{"s":"preview.pdf","size":…,"sha256":"…","pages":16,"name":"<安全标题>.pdf"},
   "source":{"s":"original.pptx","size":…,"sha256":"…","ext":"pptx","name":"<原文件名>"}},
 "compat":{"warnings":[…中文兼容提示…],"fonts_embedded":N,"converted_from":"ppt"|null,
           "external_media":[{"slide":7,"kind":"v","path_tail":"…v.mp4"}]}}
```

步骤（全部在**临时副本**上，绝不修改源文件 / `ppt/src` 原件）：

1. 复制源文件 → 临时 `.ppt/.pptx` 副本；PowerPoint 以**可写**方式打开；
2. **格式标准化 + 包规范化 + 字体嵌入**：一次
   `Presentation.SaveAs(compat.pptx, ppSaveAsOpenXMLPresentation=24, EmbedFonts=msoTrue=-1)`
   完成（`.ppt`→`.pptx` 也走这一步，PowerPoint 转换，不重采样媒体）；
3. **媒体不降质自检**：源 `.pptx` 与 compat.pptx 的 `ppt/media/*` 做 sha256 集合比对，
   出现「compat 媒体不是源包某媒体的原始字节」→ **直接失败**（判定疑似重编码）；
   页数以 zip 解析复验 = 源页数；
4. **外链媒体如实告警**（`TargetMode=External`，不能随包携带）：按 kind 聚合为中文提示，
   逐处记 `{slide, kind, path_tail}`；**不删除任何内容**，compat 包内仍保留原链接；
5. **PDF 兼容副本**：重开 compat 副本 → `SaveAs(preview.pdf, ppSaveAsPDF=32)`；校验 `%PDF` 头、
   用 pypdf 读实测页数（与幻灯片数不一致只 warn，以 PDF 实测为准）；
6. **封面**：第 1 页导出 JPG → WebP（最长边 1600，`cover.webp`）；失败只 warning；
7. sha256/size 写入 `files`；`buildId` 含 manifest；先传资产（单对象失败**重试 2 次**）再 PATCH ready；
8. `--compat-only --deck <id>`：对已 ready 的旧 deck，用 `source_key` 从 OSS 下载原件 → compat 处理 →
   上传到**原 build 目录** → 只新增 `files`/`compat`（旧 `slides`/`video`/`src`/`media` 原样保留，
   旧 deck 仍可在线预览）；失败不会把 ready deck 改成 failed。

**COM/API 适配（实测 2026-11-10，Windows PowerPoint 16）**：

- 本机 Presentation **没有**可写的 `EmbedTrueTypeFonts`/`SaveSubsetFonts` 属性 → 用官方等价参数
  `SaveAs(FileName, FileFormat, EmbedFonts)`（MS 文档）；实测生成 `ppt/fonts/*.fntdata` 且
  presentation.xml 带 `embedTrueTypeFonts="1" saveSubsetFonts="1"`（PowerPoint 自动做子集化）。
  字体因许可受限无法嵌入时只 warning（`compat.warnings` 含提示），不失败；
- `ExportAsFixedFormat` 在 pywin32 动态绑定下报 `TypeError: Python instance can not be converted to
  a COM object`（positional/kwargs 均试）→ 改用同一 PDF 引擎的 `SaveAs(FileName, ppSaveAsPDF=32)`，
  输出 `%PDF-1.7`、页数一致、compat.pptx 字节不变；
- **PowerPoint 收尾坑**：`Quit()` 后 POWERPNT.EXE 偶发滞留 **60s+**（Office RPC 清理卡顿），
  且「空实例」可能是半断开代理（复用后 `Presentations.Open` 报「接口未知」）。处理：
  ① 不复用空闲实例，先 Quit 再等旧进程退出后 `DispatchEx` 新建；
  ② Quit 后 3s 宽限仍不退出 → **强制结束 `/AUTOMATION` 实例**（无文档、文件已保存；用户手动打开的
     PowerPoint 不带 `/AUTOMATION` 不会被误杀）；③ COM 反初始化后再等待进程消失。
  实测单次 compat 转换 2–7s（修复前会被 60s 滞留拖到 60–80s）。

**质量红线（违反即返工）**：不得用图片/视频冒充兼容版；不得重编码媒体/降分辨率；
不得删除外链媒体/动画/备注等任何内容来「提高兼容性」；不得修改源文件、文件名、页数、版式。

### 6.3 断链视频修复（v2.0.1，SaveAs 之后 / PDF + 上传之前）

**问题**：用户上传的 PPT 里，视频形状可能是「`<a:videoFile r:link=rId1>` + `<p14:media r:embed=rId2>`」：
video 关系被保存成外链断链（`Type=relationships/video, Target="NULL", TargetMode=External`），
但同形状的 `p14:media` 指向包内**有效内嵌副本**（如 `../media/media1.mp4`，150.92s / h264+aac）。
PowerPoint SaveAs 可能原样保留断链 → 下载兼容包后 PowerPoint 判「视频不可用」。
（实测用户 deck `dmwalrdlgevz90l` slide7 即此结构；slide12 的 video 关系指向内部则正常。）

**修复**（`pptx_xml.repair_broken_video_links()`，在 compat SaveAs 关闭演示文稿之后、PDF/上传之前）：

1. 遍历 `ppt/slides/_rels/slideN.xml.rels`：找出 `Type` 以 `/relationships/video` 结尾且
   **断链**的关系（External 且 Target 空/`NULL`/本机 `file://` 路径不存在；或内部 Target 指向缺失部件）；
2. 在同一 slide XML 的 `<p:pic>` 里找 `p14:media r:embed=...` 指向的内嵌 media
   （同 rels 中 `Type=media/video`、Target=`../media/...` 且包内存在）；没有 `p14:media` 时，
   兜底使用该 slide 中**未被 a:blip 等引用的内嵌 media/video 关系**（仅唯一候选时）；
3. 把该 video 关系的 `Target` 改成内嵌 media 相对路径并去掉 `TargetMode`（Type 仍为 video，
   结构对齐正常包 slide12；`a:videoFile r:link` 仍指同一 rId，无需改 slide XML）；
4. **安全重写 zip**：只改 rels 部件，所有部件（含 media 字节）原样复制；重写后 `zipfile.testzip()`
   校验 + 部件名列表比对；无修复时不重写文件（幂等）；Windows 上先关闭源 zip 句柄再 `os.replace`；
5. 写入 `manifest.compat.repairs = [{slide, name, media, bytes}]`；已修复的外链提示**不再出现在**
   `compat.warnings` / `external_media`；找不到内嵌副本的保持 External 并照旧告警（如实）；
6. 对源包就断链的通用情况生效（`.pptx` 源、`.ppt→pptx` 后同样扫描）。

**已验证**（真实用户 deck 本地导出 + `--compat-only --dry-run`）：slide7 `rId1` 关系变为
`Type=relationships/video Target="../media/media1.mp4"`（无 TargetMode）；`p14:media`/slide XML 不动；
media1 sha256 `7c7cf971af68…`、media2 `1792662734c6…` 与源包逐字节一致（15/15 媒体集合相等）；
PowerPoint COM 打开修复后 compat：slide7 shape13 `Type=16`、`MediaFormat.Length=150919ms`、
`SampleWidth/SampleHeight=1024x576`（正常），slide12 对照 225582ms；PDF 16 页 / 字体 6 个部件不受影响。

**已知限制**：真·外链媒体（本机无内嵌副本/网络 URL）仍无法随包携带，只告警；
PowerPoint 若在 SaveAs 时已自动修复的包，本阶段无操作（幂等，`repairs` 为空）。

### 6.4 媒体编码兼容（v2.2，CONTRACT §12.7，2026-11-11 用户确认方案 A）

**问题**：compat 之前只做结构层（断链修复/字节保留/外链告警），不做**编码/容器兼容**。若 PPT 嵌入的
视频是 HEVC/VP9/AV1/VC-1/WMV/MPEG-2/Xvid 或音频 AC3/WMA/DTS/MP2/Vorbis/Opus，或容器是 mkv/mov/flv/avi，
在部分电脑/WPS/手机上仍可能「媒体不可用」。v2.2 在 **SaveAs + 断链修复之后、重新计算 size/sha 与上传之前**
对 `ppt/media/*` 内嵌音视频逐个处理（原始文件 `original.<ext>` 仍逐字节保留可下载）：

| 探测结果 | 动作 | 说明 |
|---|---|---|
| H.264 视频 + AAC/无音频，容器 mp4/m4v | **keep** | 原字节保留（沿用「媒体 sha 不变」红线） |
| H.264 + AAC，容器 mkv/mov/flv/avi 等 | **remux** | `ffmpeg -c copy -movflags +faststart` 换 MP4，音视频码流字节不变（lossless=true） |
| 视频编码不兼容（HEVC/VP9/AV1/VC-1/WMV/MPEG-2/Xvid…）或音频不兼容（AC3/WMA/DTS/MP2/Vorbis/Opus…） | **transcode** | `libx264 -profile:v high -crf 18 -preset medium -pix_fmt yuv420p` + `aac 192k`（无音轨不加），保持原分辨率/帧率，faststart；时长差 ≤0.3s（lossless=false） |
| 仅音频不兼容 | **transcode** | AAC m4a 192k；已兼容 mp3/m4a/aac 原样保留 |
| 单文件 >200MiB / 单段 >30min / 总时长 >60min | **keep + warning** | 不转换、保留原样并告警「媒体过大/过长，未做编码兼容」 |

- 跨扩展名时安全重写 zip：`[Content_Types].xml` 补/去重 `Default Extension`（mp4/m4a），
  所有 `ppt/slides/_rels/*.rels` 的 `Target="../media/旧名"` 改为新名；`p14:media`/`a:videoFile` 只引用 rId 不受影响；
  同扩展名直接替换字节；新名 = 原名去扩展名 + 新扩展名（防冲突加序号）；绝不删媒体、不改分辨率/画幅/时长。
- manifest：`compat.media_actions=[{file,kind,action,vcodec_from,acodec_from,vcodec_to,acodec_to,width,height,dur,bytes_before,bytes_after,lossless}]`
  + `compat.media_summary={total,kept,remux,transcode}`；**成功项不进 warnings**；compat 的 size/sha256 在媒体处理后重新计算。
- 质量红线：keep 媒体字节不变（强校验）；remux 码流不变；transcode 仅限编码不兼容且 CRF18/192k 高保真；`files.source` 永远保留原始文件。
- 关闭/降级：`convert_compat(..., {"compat_media_compat": False})` 可跳过（默认开）；ffmpeg/ffprobe 缺失时自动 keep+warning。
- 实测（fixture，5 个媒体：keep 1 / remux 1 / transcode 3）：媒体阶段约 **4.4s**；MKV h264+aac 81,832→83,053B（remux）、
  HEVC 81,370→168,001B、WMV2+AC3 365,663→202,930B、WMA 42,142→47,910B（AAC m4a），输出均 h264/aac 且时长差 ≤0.03s；
  真实 user deck 两段 h264/aac → `kept=2`、媒体字节不变，compat 39,063,742B sha256 `5dae5346…`（转换 7.4s）。
- 已知限制：转码会增加兼容包体积（HEVC/WMV 样本 1.5–2×）；`>200MiB/30min` 大媒体只告警不转；外链媒体仍只告警；
  PowerPoint 对极少数封装（如带字幕轨的 mkv）可能需先 remux，remux 只保留首视频轨+首音频轨（不保留字幕轨）。

### 6.5 视频/音频单独下载（v2.3，CONTRACT §12.8）

**问题**：教室电脑/旧 PowerPoint/WPS 打不开内嵌视频时，用户仍需要「单独下载视频到本机用任意播放器播放」。

**实现**（compat 流水线，媒体编码兼容 §12.7 之后、size/sha/上传之前）：
- 从**最终 compat 包**的 `ppt/media/*` 抽取音视频：ffprobe 识别 video/audio（非图片）；只抽被幻灯片
  `ppt/slides/_rels/*.rels` 的 video/media/audio 关系引用且**非外链**的媒体（Target 反查 `../media/<file>` → `slides:[页...]`，同媒体多页列出）；
- 独立文件：`assets/media/<safe>_视频1_第7页.mp4` / `<safe>_音频1_第X页.m4a`（扩展名按 compat 包内媒体）；
  **字节与 compat 包内媒体完全一致**（keep/remux/transcode 后的成品，不重新编码）；文件名清洗/长度限制/去重/防穿越；
- 上限：≤20 个文件、单文件 ≤200MiB（`compat_media_files_max` / `compat_media_file_max_bytes` 可调），
  超限/无法识别/纯外链 → 跳过 + warning（不影响 ready）；
- 上传：`ppt/a/<deck>/<build>/media/<name>`（同一 build 目录的 `media/` 子目录，`upload_assets`/`upload_compat_assets`
  复用现有重试）；**所有资产（含 media）上传成功后才 PATCH ready**；
- ECS 预热：先预热 build 根目录 4 文件，再预热 `media/` 子目录下所有 media 文件（同样 `?force=1`）；
- manifest：`media_files=[{s:"media/<name>",name,size,sha256,kind:"video"|"audio",dur,w,h,slides,src}]`；
  无媒体时省略该字段（向后兼容）；`validate_manifest` 校验 s 前缀/name/size/sha/kind/slides（去重升序）；
  旧 deck 无 `media_files` 客户端不显示分组。

**实测**：
- fixture（注入被引用的 HEVC 视频 + WMA 音频）：`media_files` **3 个** —— 视频1 第4页 3.0s 640x360 51,232B、
  视频2 第4页（HEVC→h264 转码后）3.0s 168,001B、音频1 第4页 2.996s 47,910B（AAC m4a）；单独文件与 compat
  包内同源媒体 sha256 逐字节一致；PDF 5 页/PowerPoint 打开正常；
- 真实 user deck `dmwalrdlgevz90l`（两段 h264/aac）：`media_files` **2 条** —— 第 7 页 150.92s 1024x576
  20,158,796B sha256 `7c7cf971…`（src media1.mp4）、第 12 页 225.582s 1024x576 15,870,426B sha256
  `1792662734c6…`（src media2.mp4）；与 compat 包内媒体字节一致、`s` 为 `media/...`。
- 已知限制：同媒体被多页引用只抽 1 个文件并在 `slides` 列出多页；媒体编码兼容阶段超限保留原样的媒体仍会抽（原格式）；
  超过 20 个/200MiB 的仅告警不抽；单独文件与 compat 包内媒体共用同一份磁盘字节（无额外转码开销）。

---

## 7. 云端行为（agent）

- **身份**：管理员 token 读 `C:\briefdesk\secrets\class-token.json`（`{token,exp}`）；
  距过期 <1h 时用 `POST rpc/class_verify`（PUBLISHABLE KEY + `cloudbaserc.local.json`
  `functions[].envVariables.CLASS_ADMIN_SID/NAME`）刷新并写回（保留原字段）。
  **日志/输出绝不打印 token、AK/SK**（`agent.sanitize()` 统一脱敏）。
- **一轮**：心跳 → `GET status=eq.queued&deleted=eq.false&order=created_at.asc&limit=1` →
  **先查 PowerPoint 忙**（忙则跳过、deck 保持 queued）→ 认领（`PATCH ...&status=eq.queued` 条件更新，
  被抢则本轮放弃）→ 拉分片（每页 8 片，避免大响应）→ 校验 `source_size`/扩展名 →
  上传原件 → **立即删分片** → **compat 兼容性处理**（v2.0 默认，进度 10/30/55/75；心跳线程每 30s）
  → 上传 compat/original/pdf/cover（85，单对象重试 2 次）→ **最后** PATCH ready（95→100；
  manifest v2 / slide_count / step_count=0 / aspect / cover_url / source_key / converter / converted_at）。
- **失败**：任何异常 PATCH `failed` + 中文 error（≤300 字，前端直接展示），并保证分片已删；
  用户在前端点「重试」→ `status=queued` 后下一轮再转。**失败不会自动重试**（避免坏文件死循环）。
- **PowerPoint 安全**：只读/可写临时副本；`DisplayAlerts=ppAlertsNone`；
  若已有 POWERPNT 进程且 `Presentations.Count>0`（用户可能正在编辑）→ 本轮跳过；
  空闲实例先 Quit（不复用）并等进程退出后新建；Quit 后 3s 仍滞留 → 强制结束 `/AUTOMATION` 实例；
  单任务 30min 预算。
- **重转换**：同一 deck 再次转换会生成新 buildId 路径（新目录），旧 build 目录不会自动删除
  （契约里写的是"可选删除"；需要清理由 Lead/运维手动删 `ppt/a/<deckId>/<旧buildId>/`）。
- **`--compat-only` 补兼容文件**（v2.0，CONTRACT §12.3）：`GET` 该 deck → 校验 `status=ready` 且
  `manifest.base` 非空 → 用 `source_key` 从 OSS 下载原件（缺失则中文报错并退出码 1）→
  `convert.convert_compat()`（不渲染旧预览资产）→ 上传 compat 资产到**原 build 目录**（重试 2 次）→
  `PATCH {manifest}`：`dict(manifest)` 浅拷贝后**只新增/覆盖 `files`+`compat`**，
  `slides/video/src/media/base` 原样保留；状态保持 `ready`（失败只报错/退出码，不把 deck 改 failed）。
  `--dry-run` 只下载+转换+合并校验+打印，不上传/不写云端。
- **`--video-only` 补视频**（v1.2 legacy）：同上，但只上传 `deck.mp4` 并只新增 `manifest.video`。

### 7.1 下载加速：ECS PPT 文件缓存（v2.1，2026-11-11）

兼容包 37MB 在 OSS 香港，跨境直连很慢（本机实测 ~74KB/s；用户换教室网络也一样）。现在：

```
转换机上传 compat.pptx / preview.pdf / original.<ext> / cover.webp 到 OSS
   └→ 立即对 ECS 缓存服务发预热：GET https://tool.furina.fun/pptfiles/__warm/ppt/a/<deckId>/<buildId>/<file>
       （best-effort：每文件 ≤3s 超时，失败只 WARN，不影响 PATCH ready）
用户下载 → https://tool.furina.fun/pptfiles/ppt/a/<deckId>/<buildId>/compat.pptx
       Caddy /pptfiles/* → strip_prefix → ECS 本地服务 127.0.0.1:8092
       命中本地磁盘：直接下发（Range/206、HEAD、Accept-Ranges、immutable 长缓存）
       未命中：从 OSS 回源（边下边发 + .part 原子落盘，同 path 加锁）
```

- 配置：`PPT_WARM_BASE` 环境变量（默认 `https://tool.furina.fun`）；预热函数 `agent.warm_ppt_files()`，
  URL 规则 `<base>/pptfiles/__warm/<manifest.base 相对 OSS 的路径前缀><文件名>?force=1`；
- **预热列表**：build 根目录 `compat.pptx/preview.pdf/original.*/cover.webp` + `media/` 子目录下全部
  `media_files`（两次 warm 调用，均 `?force=1`）；v2.3 起以 `warm_media_assets()` 实现；
- **同一 build 重转的缓存一致性（v2.1+）**：`--compat-only` 复用原 build 目录上传 compat（同 URL 内容会变），
  所以预热默认带 **`?force=1`**：服务先 HEAD OSS 比对本地 `.meta`（Content-Length/ETag/Last-Modified），
  不一致才 `.part` 回源原子替换并更新 meta；普通下载命中缓存直接下发（不 HEAD）。
  手动强制刷新：`curl 'https://tool.furina.fun/pptfiles/__warm/ppt/a/<deckId>/<buildId>/compat.pptx?force=1'`
  （202 刷新中 / 200 unchanged）；自测：`python deploy\ecs_pptfiles.py force-selftest`。
- 存量 deck 用 `--compat-only` 补文件后也会预热（写入原 build 目录）；
- **ECS 服务运维**（部署/健康/手动预热/清缓存）见 `deploy/ECS_DEPLOY.md §8`；脚本：
  `python deploy\ecs_pptfiles.py deploy|probe|verify`，健康 `https://tool.furina.fun/pptfiles/__health`；
- **实测速度**（2026-11-11）：预热后本机下载 37.25MB compat **4.41s / 8.44MB/s**
  （直连 OSS 香港同文件 ~74KB/s）；未缓存首次直下 38MB 14.88s / 2.56MB/s，缓存后 2.50s / 15.2MB/s；
  首次预热回源约 74s（ECS→OSS 当时 ~0.53MB/s），之后用户下载走 ECS 本地磁盘；
- **三端下载 URL 需切到 ECS**：manifest 里 `files.*.s` 仍存 OSS 相对路径（不改契约），客户端下载时
  把 `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/a/<deckId>/<buildId>/<file>`
  替换为 `https://tool.furina.fun/pptfiles/ppt/a/<deckId>/<buildId>/<file>`（**2026-11-23 备案通过、HTTPS 已启用，网页与三端都默认走同源 `/pptfiles`**）；未命中时服务会自动回源，所以客户端可**默认全走 ECS**，
  失败再回退 OSS 直链（缓存服务不可用时不要阻塞下载）；
- 缓存上限 5GiB 自动清最旧；清理：`rm -rf /opt/class-tools/pptfiles/ppt/<path>` 或见 ECS_DEPLOY §8.3；
- 回滚：`systemctl disable --now class-tools-pptfiles` + 客户端回退 OSS 直链（manifest 数据无需改动）。

---

## 8. 常见故障排查

| 现象 | 排查/处理 |
|---|---|
| 列表一直「排队转换」且心跳显示离线 | 计划任务被禁用/暂停文件存在。`schtasks /Query /TN PptConvertAgent`、`install_agent.ps1 -Show`；删除 `ppt-agent.pause`；`-Run` 试跑并看日志 |
| 日志 `[skip] PowerPoint busy` | 用户正开 PowerPoint（或有文档）；关掉 PowerPoint 后下一轮自动转换（deck 仍 queued） |
| 日志 `PowerPoint 进程存在但无法连接` | 可能是崩溃残留的 POWERPNT 僵尸进程。任务管理器结束 `POWERPNT.EXE` 后下一轮恢复；**先确认用户没在编辑/没未保存文档** |
| 日志 `退出时检测到 PowerPoint 有 N 个文档…保留实例` + 一直「排队转换」 | 上一轮转换被强制中断（计划任务超时/进程被杀）留下的残留实例，会让后续每轮判 busy。任务管理器结束 `POWERPNT.EXE`（先确认用户没在编辑）后下一轮自动恢复；本目录测试用 `python tests\test_convert_integration.py` 收尾会打印残留检查提示 |
| 日志 `PowerPoint 无法打开该文件（可能加密/损坏）` | 源文件加密/损坏/格式伪装 → 前端显示「转换失败」+ 中文原因；需用户重传 |
| 日志 `缺少 pywin32/oss2` | 用了错误解释器（venv 没装依赖）。计划任务必须用系统 pythonw（脚本默认 `%USERPROFILE%\AppData\Local\Programs\Python\Python312\pythonw.exe`） |
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
| **重转后下载到旧兼容包（旧视频/旧媒体）** | 同一 build 目录内容会变，缓存需强制刷新。v2.1+ 转换机上传后自动 `?force=1` 预热；若仍旧：手动 `curl '…/pptfiles/__warm/ppt/a/<id>/<build>/compat.pptx?force=1'` 等待 202 完成后重试；检查 `journalctl -u class-tools-pptfiles` 的 force 刷新日志 |
| **下载兼容版很慢（几十 KB/s）** | 现在应走 ECS 缓存 `…/pptfiles/ppt/a/...`（见 §7.1）。检查：`curl https://tool.furina.fun/pptfiles/__health` 是否 200；`deploy/ecs_pptfiles.py probe` 看服务/缓存；该文件是否已预热（`__warm` 返回 202 后约 1–2 分钟落盘）。缓存服务不可用时先用 OSS 直链（慢但可用） |
| **下载兼容版后视频仍显示不可用** | v2.0.1 起转换机自动修复「外链断链但包内有内嵌副本」的视频（日志 `修复断链视频（第 N 页…→ 内嵌 …）`，manifest `compat.repairs`）。检查该 deck manifest：`repairs` 是否含该页；若 `external_media` 仍列出说明是真外链（包内无副本）→ 只能告警，需用户重新在 PPT 里嵌入媒体后重传。修复需重转：`python agent.py --deck <id> --compat-only` |
| **旧 deck 没有兼容文件**（manifest 无 `files`） | 用 `python agent.py --deck <id> --compat-only` 补；dry-run 可先本地验证。补完 manifest 只新增 files/compat，旧预览字段保留 |
| `compat: 字体未嵌入（可能无 TrueType 字体或许可受限）` | 只是 warning，不失败；版式在其他设备可能变化。查看是否使用了许可禁止嵌入的字体 |
| `WARN compat: 外链视频 N 处未随文件携带（第 X 页，路径尾 …）` | **正常告警**：外链媒体文件不在上传包内、不能随 PPT 携带；转换机不删除内容，客户端展示兼容提示 |
| `保存兼容包失败` / `PDF 兼容副本导出失败` | deck PATCH `failed` + 中文 error；多为加密/损坏/PDF 引擎异常。用户重试或重传；OCR 无关 |
| `compat: 兼容包媒体字节与原文件不一致（疑似重编码）` → 失败 | 质量红线保护：拒绝产出「疑似被重编码」的兼容包。重试一次；仍失败请升级/检查 PowerPoint |
| `PowerPoint 自动化实例 Quit 后滞留 → 强制结束 N 个` | 正常兜底（Office RPC 清理卡顿，进程无文档、文件已保存）；不需要人工处理 |

---

## 9. 测试（本机可复跑）

```powershell
cd %USERPROFILE%\.openclaw\workspace\web\ppt

# 1) 生成 fixture（首次/需要重生成时；会启动 PowerPoint COM）
python tests\make_fixture_pptx.py

# 2) 纯逻辑单测（无 COM/网络，秒级；131 项）
python tests\test_pure_logic.py -v

# 3) v2.0 compat 真实 COM 集成（25 项；约 1–3min，视 PowerPoint 冷启动/残留进程）
python tests\test_compat_integration.py -v

# 4) v1.2 legacy 真实 COM 集成（22 项；约 30–75s）
python tests\test_convert_integration.py -v

# 5) 云端契约 + 真实 OSS 链路（7 项；需要网络；会产生 2 个保留的 ready fixture deck 供网页验收）
python tests\test_cloud_contract.py -v

# 6) 存量真实 deck 补兼容文件演练（需要网络；不下发云端写入，本地产物保留供核对）
python agent.py --deck dmwalrdlgevz90l --compat-only --dry-run
```

> **v2.0 compat 集成测试覆盖**（`test_compat_integration.py`）：`manifest.v2` + `files.compat/pdf/source`
> 存在且 size/sha256 正确；compat 页数 = 源页数；**PowerPoint 真打开 compat 校验页数**；
> **compat 包内媒体 sha256 与源包逐字节一致（不重编码强断言）**；PDF `%PDF` + pypdf 页数；
> cover.webp WebP/1600；字体部件 >0；外链媒体告警含页号/kind/路径尾且 compat 内**仍保留**外链；
> `.ppt` fixture → ext=pptx / `converted_from=ppt` / 原件 sha256；失败路径（SaveAs/PDF/疑似重编码）
> → 中文 `ConvertError`；**断链视频修复**（模拟 SaveAs 保留 External/NULL 断链 → repairs 记录、
> rels 内部化、媒体字节不变、PDF/字体不回退、PowerPoint 打开修复后媒体形状正常）。
> 真实 deck 的 `--compat-only` 走 dry-run 手动验（大文件下载不进自动化）。
>
> **v1.2 legacy 集成测试覆盖**：`manifest.video`（h264+aac、章节=页数、帧级真播放验证）、
> CreateVideo 失败降级仍 ready、tuanri 16 页真实视频导出。

- 测试账号：学号 `3260799999` / 姓名「测试账号」（RLS 冒烟用，token 不落日志）；
- 集成测试每个转换类开始前会**等待残留 PowerPoint 退出**（最多 180s；`Quit()` 返回后
  POWERPNT.EXE 可能还要数秒~数分钟才真正结束，连续转换/补转时尤其明显）；若等待超时
  （例如用户正在编辑 PowerPoint）则 `skip` 该类而不是报错，并打印原因。
- `test_cloud_contract.py` 会**保留** 2 个 ready deck（标题 `测试·嵌入视频演示`、`测试·4:3 演示`），
  供网页端播放器/视频热点验收；其余临时 deck/chunks/failed 数据在 `finally` 里清理；
- **交付前清理测试 deck**：运行 `python tests\cleanup_test_decks.py --apply` 软删测试 deck（脚本只对
  `owner_sid=3260799999` 且 `deleted=false` 的行 PATCH `deleted=true`，写前复核 owner 并断言全为测试身份，
  真实同学 deck 不参与；幂等，重跑 0 行；不带参数为 dry-run，只列出将被软删的 id/标题/状态/创建时间）；
  **2026-11-11 起 `tests/test_cloud_contract.py` 的 `TestE2EFixtures` 在 `tearDownClass` 自动软删本轮
  fixture deck + 清分片**，不再把「测试·…」deck 留在全班可见列表（此前设计为“保留给网页验收”，导致用户
  每次执行测试/验收后都在演示页看到测试 PPT；用户反馈后改为自清理，上面的 --apply 仅作历史兜底）；
- 测试 deck 的 OSS 前缀（`ppt/a/<id>/`、`ppt/src/<id>/`）对象数/字节数可用
  `python tests\cleanup_test_decks.py --report-oss` 只读统计（只 `list_objects_v2` 分页统计，**不删除**；
  加 `--all-test` 可统计全部测试身份 deck（含已软删）；是否清理存储由用户决定后另行处理）；
- 过程产物写 `tests/_out/`（`fixture_deck*.pptx`、`work_16x9/`、`work_4x3/`、`work_degraded/`、
  `work_tuanri/`、`media/clip.mp4`、`frame_media_*.jpg` 抽帧），交付前清理（fixture 可由脚本重新生成）。

---

## 10. 已知限制 / 取舍（务必如实转达）

### 10.1 v2.0 compat（默认流程）

1. **兼容包体积**：compat.pptx = 源 + 嵌入字体子集（user deck 38.0MB→39.1MB / +3%），
   PDF 另计（16 页 1.22MB），原件副本 = 源大小。单个 deck OSS 占用 ≈ 2×源 + PDF。
2. **字体**：只有 TrueType 字体可嵌入；字体许可禁止嵌入（如部分商业中文字体）时 PowerPoint 不写字体数据，
   只记 warning 并在 `compat.warnings` 提示「版式可能在其他设备变化」——**不失败、不改内容**。
3. **外链/断链媒体**：`TargetMode=External` 且无内嵌副本的真外链媒体**无法随 PPT 携带**，转换机只如实告警
   （每处 页号/kind/路径尾），不删除、不替换。**断链但有内嵌副本**的（外链 Target 为 `NULL`/空/不存在，
   同形状 `p14:media` 指向包内 media）会在 compat 包内自动修复为内嵌播放（v2.0.1，见 §6.3），
   修复记录在 `compat.repairs`；真外链下载到其他设备打开时仍可能「不可用」，客户端展示「兼容提示」。
4. **`.ppt`→`.pptx`**：由 PowerPoint 自身 `SaveAs(ppOpenXMLPresentation)` 完成，版式/动画/备注语义保持；
   97-2003 的个别特性（如某些 OLE 对象/旧版媒体）由 PowerPoint 决定，转换机不做额外有损处理。
5. **PDF 页数**：隐藏页是否进 PDF 由 PowerPoint 导出策略决定；manifest `files.pdf.pages` 写 **pypdf 实测页数**，
   与幻灯片数不一致时只 warning（不伪造页数）。
6. **旧 deck 预览**：v2.0 列表以下载为主；旧 deck（manifest v1 有 slides/video）仍保留「在线预览」入口；
   旧 deck 用 `--compat-only` 补文件后 manifest 只新增 `files`/`compat`，旧字段不动。
7. **质量红线**：不做任何图片/视频重编码、不降分辨率、不渲染成图/视频冒充兼容版；compat 媒体 sha256
   与源包不一致会**直接失败**（拒绝产出疑似有损包）。
8. **PowerPoint 自动化**：单实例；用户正在编辑时本轮跳过；Quit 后进程偶发滞留 60s 已用「3s 宽限 +
   强制结束 `/AUTOMATION` 实例」兜底（无文档、文件已保存）；机器需登录桌面会话（计划任务 InteractiveToken）。
9. **转换机需开机**：离线时任务只排队；页面显示「转换机离线 · 排队中」。
10. **旧 build 不自动删**：同 deck 重转换生成新 buildId 目录；`--compat-only` 写回原 build 目录
    （manifest.base 不变），旧 build 目录需运维手动清理。

### 10.2 v1.2 legacy（`--legacy` / 旧 deck 在线预览）

1. **自动动画合并**：`afterPrevious/withPrevious` 动画并入当页最终态（契约 §6）。
   真实中文教学 PPT 大量使用自动动画 → 分步浏览看到的是每页最终画面（**内容不丢**，但不是逐条出现）。
   已确认不做 auto-step 模式（Lead 决策 2026-11-09）。**原样播放视频可看到完整动画节奏**。
2. **强调/运动路径**只取该步最终视觉状态，不是逐帧动画（分步模式）；原样视频里是完整逐帧动画。
3. **隐藏幻灯片**仍会被转换（保证内容完整；不模拟"放映时跳过隐藏页"）。
4. **外链媒体**在分步模式跳过、原样视频里用**海报静态图**替代（避免 PowerPoint 导出等待外链文件 ~90s/页）。
5. **PowerPoint 窗口**：PowerPoint 16 不允许隐藏应用窗口，转换期间窗口会最小化出现；转换完 Quit。
6. **单任务超时**：legacy 预算 30min（含视频）；超时只影响视频时**跳过视频、分步照常 ready**；
   若 PowerPoint COM 调用本身卡死（极端情况），计划任务 `ExecutionTimeLimit=PT45M` 会强制结束；
   下一轮重新开始（deck 已 failed 需用户重试）。
7. **并发**：单实例锁 + PowerPoint 单实例 → 同一时刻只转一个 deck；队列按 `created_at asc` 串行。
8. **单 deck 上限**：源 ≤64MiB、≤300 页、每页 step ≤12、整份图片 ≤260（超出降级为每页 1–2 步不丢内容）；
   媒体单文件 ≤200MB、总时长 ≤30min、单段 >30min 只转前 30min。
   **原样播放视频另有限制：>120 页或预估 >1800s 不生成视频**；单页最长 600s（超长媒体页章节会截断）。
9. **token 写回**：刷新后的管理员 token 会写回 `C:\briefdesk\secrets\class-token.json`（保持 `{token,exp}` 格式）。
10. **视频章节 ±1s**：章节时间按探测公式计算（PowerPoint 把切换时长插在页之间），实测偏差
    （fixture +0.22s、tuanri +1.12s、user deck +1.19s）；播放器 seek 后内容误差在 ±1s 量级。
    若某 deck 出现明显漂移，日志会有 `实测时长与预估偏差` warning（可重转/降级分步）。
11. **视频体积**：720p q80 原始导出可能很大（user deck 16 页含 225s 视频：raw 52.6MB）；≥40MB 自动
    重编码（crf24/aac96k）后典型 **7–40MB**（user deck 13.7MB、tuanri 16 页 7.5MB、fixture 1.8MB）。
    弱网/节省流量时三端默认回退分步。
12. **视频为自动节奏**：单击动画被合并为自动连续播放；需要自主控制节奏时切「分步浏览」。
13. **降级不影响 ready**：`manifest.video` 是可选字段；缺失/加载失败三端回退分步，不是转换失败。

---

## 11. 安全红线

- 本目录代码/日志**不得**出现 token、AK/SK、手机号、学号等敏感信息（日志统一 `sanitize()`）；
- OSS 写凭据只在本机 `web/deploy/creds.env`（或环境变量），三端只读，前端不出现任何写入凭据；
- 测试用身份只用测试账号 `3260799999`；
- 不修改 `web/deploy/creds.env`、证书、`web/tools/index.html`、云函数/迁移 SQL。
