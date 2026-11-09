# PPT 演示 · 本机转换机运维手册（web/ppt）

> 唯一契约真源：`web/ppt/CONTRACT.md`（v1，2026-11-09）。本目录实现契约 §3/§4/§6/§7：
> Windows + Microsoft PowerPoint COM 把班级上传的 `.ppt/.pptx` 一次性转换成
> **分步图片（WebP）+ H.264 视频/AAC 音频**，上传阿里云 OSS，并更新 CloudBase 队列状态。
> 三端播放器只加载图片/视频 → 老电脑也能流畅播放；视频不再依赖 PowerPoint 解码器。

```
[web/mp/android] --分片上传--> CloudBase ppt_decks(status=queued)
                                       │
        web/ppt/agent.py --once 每分钟轮询 ┤
        ├ 心跳 site_assets(id=ppt_agent)
        ├ 认领 → 拉分片拼源文件 → 上传原件 ppt/src/<id>/source.pptx → 删分片
        ├ convert.py：PowerPoint COM 分步渲染 → WebP + 抽取视频 → ffmpeg H.264
        ├ 上传资产 ppt/a/<id>/<buildId>/ → PATCH ready + manifest
        └ 任何异常 → PATCH failed + 中文 error（≤300 字）
```

---

## 1. 文件清单

| 文件 | 作用 |
|---|---|
| `agent.py` | 入口：轮询/认领/分片拼装/OSS 上传/心跳/token 刷新/单实例锁/进度 PATCH/日志 |
| `convert.py` | 转换核心：PowerPoint 忙检测、可见性快照、去重、导出、媒体抽取、ffmpeg、WebP、manifest、buildId |
| `pptx_xml.py` | 纯函数：`presentation.xml` 尺寸、页序、媒体/热区解析、页面切换映射、step 规划/降级、manifest 校验、buildId |
| `oss_upload.py` | OSS 封装（`oss2`，凭据复用 `web/deploy/sync_tools.py::load_creds()`，不打印） |
| `install_agent.ps1` | 注册计划任务 `PptConvertAgent`（每分钟 + 登录后 30s、InteractiveToken、pythonw、StartWhenAvailable、单实例） |
| `tests/make_fixture_pptx.py` | 用 COM 生成测试 fixture（16:9 五页 + 4:3 三页，含动画/退场/嵌入视频/外链/备注/切换） |
| `tests/test_pure_logic.py` | 51 项纯逻辑单测（无 COM/网络） |
| `tests/test_convert_integration.py` | 17 项真实 COM 转换断言（图片尺寸/step 去重/视频/热区/4:3/外链跳过/笔记/耗时） |
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

# 调试指定 deck（真实链路：认领→原件→转换→资产→ready）
python agent.py --deck <deckId>

# 只读演练：不认领、不写云端、不上传 OSS（本地转换并打印 manifest 摘要）
python agent.py --deck <deckId> --dry-run
```

> `--deck` 只对 `queued`（或调试用 `failed/processing`）有意义；已经是 `ready` 的 deck 会被
> 跳过，提示「如需重转先把 status PATCH 回 queued」。

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
  `ExecutionTimeLimit=PT20M`（单任务 15min + 收尾余量）；
- 单实例：`agent.py` 自己还有 `logs/agent.lock`（MSVCRT 文件锁），并发轮次直接跳过。

创建/启用后可以用 `-Show` 或 `schtasks /Query /TN PptConvertAgent` 核对；`Last Result: 267011`
是「任务尚未运行」的正常值（0x41303）。

---

## 4. 暂停 / 恢复 / 看日志

- **暂停**：创建空文件 `web\ppt\ppt-agent.pause`（计划任务照常触发，但 agent 立即退出）；
- **恢复**：删除该文件；
- **日志**：`web\ppt\logs\agent-YYYYMMDD.log`（UTF-8，按天，14 天自动清理）。
  - 每轮：`round start` / `round done（action=...）`
  - 认领/进度/转换逐页耗时/媒体转码/OSS 上传/失败堆栈（已脱敏，绝不含 token）
  - `[skip] PowerPoint busy`：用户正开 PowerPoint，deck 保持 queued，下一轮自动再试
- **看心跳/队列**：云端 `public.site_assets` 行 `id='ppt_agent'`
  `body={online,seen_at,queued,version,host}`（`seen_at` 超过 180s 视为离线）；
- **日志里的进度**：进度按「已渲染页数」推进 5→85，媒体/资产上传 88→98，ready=100。

---

## 5. 耗时与磁盘预算（本机实测 2026-11-09）

| 场景 | 实测 |
|---|---|
| fixture 5 页 / 8 步 / 1 内嵌视频（16:9） | 转换 **2.5–2.9s**（含 PowerPoint 启动 ~1s） |
| 真实 deck 16 页 / 16 步 / 32 图 / 0 媒体 | 转换 **8.56s**；整轮（4 分片拼装 + 原件 + 32 资产上传 + ready）**34.2s** |
| 真实 deck 逐页渲染 | 约 **0.3–0.5s/页**（1600×900 JPG 快照 + WebP 编码） |
| 缩略图 | 每页 1 张，~2–5KB |
| OSS 单对象上传 | 约 0.3–0.6s（32 张图 ≈ 15s；资产先传完才 PATCH ready） |
| PowerPoint 冷启动 | **首次可能 60s+**（本机实测 COM 冷启动 62s），之后 ~1s；单任务 15min 上限足够 |

> 计划任务每分钟一轮：`queued` 为空时一轮仅心跳 + 1 次查询（<2s）。
> 单 deck 上限：源文件 ≤64MiB、≤300 页、每页动画 step ≤12、整份图片 ≤260（超出自动降级为每页 1–2 步但不丢内容）。

磁盘预算（建议 C 盘 ≥2GB 空闲）：

- `work/<deck>-<ts>/` 临时：源文件 + 每步 JPG（约 100–300KB/张）+ 处理中的 WebP；
  60 页 × 1.4 步 ≈ 21MB，转换结束/失败都会清理；陈旧目录 >24h 开机首轮清掉；
- OSS：每页主图 30–80KB + 缩略图 2–5KB，60 页 deck ≈ 3–6MB（38 页典型 ≈ 8MB 量级含多步）；
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
  空实例先 Quit 再新建；单任务 15min 截止；收尾只 Quit 无用户文档的实例。
- **重转换**：同一 deck 再次转换会生成新 buildId 路径（新目录），旧 build 目录不会自动删除
  （契约里写的是"可选删除"；需要清理由 Lead/运维手动删 `ppt/a/<deckId>/<旧buildId>/`）。

---

## 8. 常见故障排查

| 现象 | 排查/处理 |
|---|---|
| 列表一直「排队转换」且心跳显示离线 | 计划任务被禁用/暂停文件存在。`schtasks /Query /TN PptConvertAgent`、`install_agent.ps1 -Show`；删除 `ppt-agent.pause`；`-Run` 试跑并看日志 |
| 日志 `[skip] PowerPoint busy` | 用户正开 PowerPoint（或有文档）；关掉 PowerPoint 后下一轮自动转换（deck 仍 queued） |
| 日志 `PowerPoint 进程存在但无法连接` | 可能是崩溃残留的 POWERPNT 僵尸进程。任务管理器结束 `POWERPNT.EXE` 后下一轮恢复；**先确认用户没在编辑/没未保存文档** |
| 日志 `PowerPoint 无法打开该文件（可能加密/损坏）` | 源文件加密/损坏/格式伪装 → 前端显示「转换失败」+ 中文原因；需用户重传 |
| 日志 `缺少 pywin32/oss2` | 用了错误解释器（venv 没装依赖）。计划任务必须用系统 pythonw（脚本默认 `C:\Users\Ko_Li\AppData\Local\Programs\Python\Python312\pythonw.exe`） |
| 日志 `OSS 凭据缺失` / `401/403` | 检查 `web/deploy/creds.env`（不要打印内容）与 `class-token.json` 是否可读；token 会自动刷新 |
| 日志 `ffmpeg ... 失败` | 检查 PATH 中 ffmpeg（`ffmpeg -version`）；个别媒体失败会跳过该媒体（图片/其他内容仍可用） |
| 日志 `云端/配置错误` 且退出码 1 | `publish_key.txt`/token 文件/网络问题；修好后下一轮自动恢复（计划任务每分钟） |
| 转换很慢（>2min） | 看日志逐页耗时；页数多/母版/大图多会慢；首次冷启动 PPT 更慢。单任务 15min 截止后 PATCH failed「转换超时」 |
| 转换窗口出现在桌面 | PowerPoint 16 不允许 `Visible=False`（已实测），脚本会把窗口**最小化**；只在有任务时出现，转换完自动退出 |
| 磁盘增长 | `work/` 陈旧目录自动清（>24h）；OSS 旧 build 目录需手动清；`logs/` 14 天自动清 |

---

## 9. 测试（本机可复跑）

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web\ppt

# 1) 生成 fixture（首次/需要重生成时；会启动 PowerPoint COM）
python tests\make_fixture_pptx.py

# 2) 纯逻辑单测（无 COM/网络，秒级）
python tests\test_pure_logic.py -v

# 3) 真实 COM 转换集成（16:9 + 4:3，约 10–20s）
python tests\test_convert_integration.py -v

# 4) 云端契约 + 真实 OSS 链路（需要网络；会产生 2 个保留的 ready fixture deck 供网页验收）
python tests\test_cloud_contract.py -v
```

- 测试账号：学号 `3260799999` / 姓名「测试账号」（RLS 冒烟用，token 不落日志）；
- `test_cloud_contract.py` 会**保留** 2 个 ready deck（标题 `测试·嵌入视频演示`、`测试·4:3 演示`），
  供网页端播放器/视频热点验收；其余临时 deck/chunks/failed 数据在 `finally` 里清理；
  交付前由 Lead 统一 soft-delete 这 2 个 deck 并清 OSS 测试 prefix；
- 过程产物写 `tests/_out/`（`fixture_deck*.pptx`、`work_16x9/`、`work_4x3/`、`media/clip.mp4`），
  交付前清理（fixture 可由脚本重新生成）。

---

## 10. 已知限制 / 取舍（务必如实转达）

1. **自动动画合并**：`afterPrevious/withPrevious` 动画并入当页最终态（契约 §6）。
   真实中文教学 PPT 大量使用自动动画 → 网页上看到的是每页最终画面（**内容不丢**，但不是逐条出现）。
   已确认不做 auto-step 模式（Lead 决策 2026-11-09）。
2. **强调/运动路径**只取该步最终视觉状态，不是逐帧动画。
3. **隐藏幻灯片**仍会被转换（保证内容完整；不模拟"放映时跳过隐藏页"）。
4. **外链媒体**跳过（PPT 里链接到本机/网络路径的视频无法在网页播放），manifest 该步媒体为空。
5. **转换机需开机**：离线时任务只排队；页面显示「转换机离线 · 排队中」。
6. **PowerPoint 窗口**：PowerPoint 16 不允许隐藏应用窗口，转换期间窗口会最小化出现；转换完 Quit。
7. **单任务超时**：正常慢处理（页多）会在 15min 截止点中断并 PATCH failed「转换超时」；
   若 PowerPoint COM 调用本身卡死（极端情况），Windows RPC 超时前进程可能挂住，
   计划任务 `ExecutionTimeLimit=PT20M` 会强制结束；下一轮重新开始（deck 已 failed 需用户重试）。
8. **并发**：单实例锁 + PowerPoint 单实例 → 同一时刻只转一个 deck；队列按 `created_at asc` 串行。
9. **单 deck 上限**：源 ≤64MiB、≤300 页、每页 step ≤12、整份图片 ≤260（超出降级为每页 1–2 步不丢内容）；
   媒体单文件 ≤200MB、总时长 ≤30min、单段 >30min 只转前 30min。
10. **旧 build 不自动删**：同 deck 重转换生成新 buildId 目录，旧目录需手动清理。
11. **token 写回**：刷新后的管理员 token 会写回 `C:\briefdesk\secrets\class-token.json`（保持 `{token,exp}` 格式）。

---

## 11. 安全红线

- 本目录代码/日志**不得**出现 token、AK/SK、手机号、学号等敏感信息（日志统一 `sanitize()`）；
- OSS 写凭据只在本机 `web/deploy/creds.env`（或环境变量），三端只读，前端不出现任何写入凭据；
- 测试用身份只用测试账号 `3260799999`；
- 不修改 `web/deploy/creds.env`、证书、`web/tools/index.html`、云函数/迁移 SQL。
