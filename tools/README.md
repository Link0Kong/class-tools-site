# 班级小工具站（tool.furina.fun）· v2.0.0

为班级服务的工具站，单文件静态页（`index.html`），**零外部依赖、原生浏览器 API**；班级数据走 CloudBase PostgreSQL（身份 token + RLS），本机 localStorage 作为缓存。当前版本 **2.0.0**（2026-11-05）。

线上地址：**https://tool.furina.fun/**

> v2.0.0 更新摘要（详见 `../CHANGELOG.md`）：
> 版本号 2.0.0 · 刷新恢复 tab+滚动位置 · 通知页改为父页滚动（修复微信内 iframe 滑不动）+ iframe 左右滑切工具 ·
> 管理员通知编辑/软删除/恢复（云端 override_json/hidden 四列）· 通知长期安排（recurrence）·
> QQ 文件「待获取/下载后自动上线」· AI 摘要 1–6 条关键词（≤12 字）· 补充通知自动合并 · 体测男女/年级纳入同步 ·
> 通知已处理/作业完成跨端同步加固 · 全站克制动效 + reduced-motion · 性能优化。
> 小程序端同版 2.0.0（源码见仓库根目录「相关仓库」表），演示/审核模式、AI 开发模式发版默认关闭。

独立门牌：独立 OSS Bucket `tool-furina-fun` @ 香港（公共读 + 静态网站托管）+ 自定义域名 + Let's Encrypt 证书。
与竞选自我介绍页（`me.furina.fun`）完全解耦——自我介绍页弃用后，本站照样跑。

---

## 1. 五个工具（顶部切换，无底部栏、无多余说明文字）

| 工具 | 能力 | 数据 |
|------|------|------|
| 🎲 抽签工作流 | **STEP 1 抽签**：范围(起-止，默认 1-70)、抽取个数、允许重复、排除序号（如 `3,7,10-12`）、可选名单对应（输入或粘贴自动在行前加编号，序号 N ↔ 名字，可一键清空；有名单时结果突出名字）；结果随机出抽取顺序，出结果后可按钮重排（从大到小/从小到大/随机打乱），结果下有「导出图片」「下一步：分组」并列按钮｜**STEP 2 分组**：用上一步序号或粘贴名单，按组数/每组人数；勾选「打乱成员再分组」＝随机分配成员，不勾＝按原顺序轮流分配（可复现）；成员显示「序号 名字」｜**STEP 3 结果单**：抽签+分组全部参数与结果汇总成一张图。每步都可直接导出图片，STEP 2/3 可复制 | 配置 |
| 📅 课表 | **教务系统自动同步、只读、全员可看**（`jwxt/sync.py` 每日 07:00 抓取 → `tt.json` → 站点同源读取；发布链接 `#tt=` 仍可手动分享）：周次切换（‹ 第N周 › / 本周）、周/日双视图（窄屏默认日视图）、今日只在日期处标记、课程详情（按本次点击的单节显示教师/时间/教室/下次上课）、正在上课 / 下一节（当天课上完不再显示）、周末无课自动隐藏、全部课程默认收起、导入弹层（同步码/JSON/.json 文件本机备份）、导出图片 | 云 `tt.json`（公开静态快照，页面只读不可编辑） |
| 📌 作业板 | **云端同步**（登录后发布、全员 30s 轮询同步、离线降级本地并联网补发）：作业 + 截止日期倒计时（过期标红）、勾选完成、附件（图片 ≤5MB 自动压缩 / 文件 ≤2MB，最多 2 个）、导出清单图片；可显示发布者昵称；登录后「完成」按账号跨设备同步 | 云 homework / marks 表 |
| 📣 通知板 | **云端同步**（同上；推送入口已移除，将来由服务端统一推送）：发布通知（置顶/重要）、导出卡片 | 云 notices 表 |
| 🏃 体测 | 大学体测成绩计算（《国家学生体质健康标准（2014 年修订）》大学组，分大一大二 / 大三大四两档）：BMI、肺活量、50 米、坐位体前屈、立定跳远、引体向上/仰卧起坐、耐力跑七项按权重算标准分，另计附加分，得学年总分（满分 120）与等级；可导出成绩图 | 体测录入 |

### 导出图片的规范（统一走 `exportCard()`）

- **命名**：`<类型>_<YYYYMMDD-HHMM>_<关键参数>.png`
  例：`抽签结果_20261009-2024_范围1-50_抽10个_不重复_按抽取顺序.png`
- **水印**：斜向平铺 `tool.furina.fun`（低透明度，不扰阅读）
- **图片内自带「参数配置」区** + 页脚生成时间 + 唯一编号，便于归档与复核
- **每步独立导出**：STEP 1 / 2 / 3 各有「导出图片」按钮

---

## 2. 架构（为「将来能通知」而设计）

```
浏览器（静态页）
   ├── 数据层 DB        → 现在：localStorage（本机）
   │                      将来：换成远程适配器即可多端共享
   └── 通知层 Notifier   → 现在：Webhook 直发（页面打开时有效）
                          将来：服务端定时任务 → 自动提醒
```

关键点：数据与通知都封装在**单一入口**（`DB` / `Notifier`），页面逻辑不直接碰 `localStorage` 或 `fetch`。
升级到服务端共享 + 自动推送时，**只改这两个对象，四个工具的界面一行都不用动**。

### 通知通道（已下线，待服务端接管）

前端**不再提供**推送通道配置与任何推送按钮（Webhook Key 存浏览器既不安全、也不互通）。
作业 / 通知现阶段仅本地管理 + 导出图片分享；统一推送与定时提醒由 P1 轻后端承接（见第 4 节）。

---

## 3. 部署 / 更新（重要：改了必须同步）

```powershell
cd %USERPROFILE%\.openclaw\workspace\web\deploy
python sync_tools.py            # 同步 web\tools → Bucket 根目录
```

- Bucket：`tool-furina-fun` @ `oss-cn-hongkong`（公共读 + 静态网站托管）
- 上传路径：根目录 `index.html`、`assets/qr_tools.png`、`tt.json`（教务课表快照，存在才传）
- 课表快照：由 `web\jwxt\sync.py` 生成并自动上传（Windows 计划任务 `JwxtTimetableSync`，每天 07:00；`python sync.py --out ..\tools\tt.json --deploy` 手动跑一次）
- 凭据：环境变量 `ALIYUN_AK_ID/ALIYUN_AK_SECRET`，否则读同目录 `creds.env`
- 验证：`https://tool.furina.fun/`，或逐字节 sha256 比对

首次开站 / 换证书（幂等，可重跑）：

```powershell
python setup_tool_site.py       # 建 Bucket + 传文件 + 签 LE 证书 + 绑域名
```

证书存于 `web\tools\cert\`（`fullchain.pem` / `domain.key`），Let's Encrypt 证书 90 天，续期重跑 `setup_tool_site.py`。

---

## 4. 下一阶段：共享数据 + 自动通知（路线图）

现状限制：数据存本机 → 同学之间的作业/通知**不共享**；推送需页面打开。

要做「真·班级服务」，需加一个轻后端（成本≈0，走香港节点免备案）：

1. **存储**：复用现有 OSS（`tools/data/*.json`）或 Cloudflare KV
2. **接口**：阿里云函数计算 FC / Cloudflare Worker 提供 `GET/POST /api/tools`
   - 访问口令（班委持有）→ 写；同学只读
3. **定时推送**：FC 定时触发器 / Worker Cron → 每天定点扫「明天到期」的作业与置顶通知 → 调通知适配器
4. **微信侧现实约束**（必须知道）：
   - **微信「服务号」个人无法注册**（需企业/组织主体 + 300 元/年认证）→ 走不通
   - 可行替代：① **QQ 官方机器人**（已有现成基础设施，群内推送最现实）② 企业微信群机器人 ③ Server 酱 / PushPlus 等第三方推微信
5. 前端改动：把 `DB` 换成远程读写、`Notifier` 换成服务端统一推 → 界面不动

---

## 5. 自检（改完必跑）

```powershell
cd %USERPROFILE%\.openclaw\workspace\web\tools
python tests\selfcheck.py       # 交互冒烟：模拟点击全部按钮，断言 0 JS 报错 + 旧数据迁移 + 无底部栏
python tests\overflow_check.py 430  # 横向溢出审计（逐 tab 收集，overflowCount=0）
python tests\shots.py           # 各档宽度截图（iframe 固定宽度，HUD 显示 viewport/scrollW/overflow）
python tests\export_check.py draw   # 抓出导出图片存盘核查（draw/group/flow/tt/hw/ft）
```

仓库内文件

- `index.html` —— 应用本体（单文件，约 68 KB）
- `assets/qr_tools.png` —— 站点二维码（内容 `https://me.furina.fun/tools/`）
- `tests/selfcheck.py`、`tests/shots.py`、`tests/export_check.py`、`tests/overflow_check.py` —— 自检脚本

