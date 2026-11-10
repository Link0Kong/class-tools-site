# HANDOFF.md — 班级工具站 · 开发交接说明

> 交接对象：接手的开发 Agent（ZCode）
> 交接人：芙宁娜（原开发方）
> 更新时间：2026-10-09
> **先读 `AGENTS.md`（红线与设计规范），再读本文件。**

---

## 1. 一句话概览

一个**为班级服务的轻量工具站**：抽签工作流（抽签 → 分组 → 结果单）+ 课表 + 作业板 + 通知板 + 体测计算器（大学组国标）。
单文件静态页，零依赖、零后端、数据存在使用者本机；**每步都能导出带水印与参数的规范图片**。

- **线上地址**：<https://tool.furina.fun/>（等价 `https://tool.furina.fun/index.html`）
- **仓库目录**：`C:\Users\Ko_Li\.openclaw\workspace\web\`
- **当前版本**：v3.14 之前的自研单文件（无版本号，以文件为准；`index.html` 约 68 KB）

> ⚠️ **建议 ZCode 的工作区只设为 `web\` 这层目录**（不要打开 `.openclaw\workspace` 根目录），
> 因为上层含个人记忆、会话记录与云端密钥文件。

---

## 2. 资产清单

```
web/
├─ AGENTS.md                  ← 红线与设计规范（必读）
├─ HANDOFF.md                 ← 本文件
├─ CLOUDBASE.md               ← 【必读】云端作业板：envId / 密钥 / 接口契约 / 前端接法
├─ tools/                     ← 站点源码（唯一真源）
│  ├─ index.html              ← 应用本体（单文件，所有 HTML/CSS/JS 都在里面）
│  ├─ tt.json                 ← 教务课表快照（同源 fetch；jwxt/sync.py 生成）
│  ├─ assets/qr_tools.png     ← 站点二维码（指向 https://tool.furina.fun）
│  ├─ cert/                   ← ⚠️ 机密：Let's Encrypt 证书与私钥，禁止读取/外传
│  ├─ tests/                  ← 自检脚本（见 §5）
│  └─ README.md               ← 面向人的说明
├─ jwxt/                      ← 教务课表同步工具链（本机 Python，见 §5.1 / §10）
│  ├─ sync.py                 ← 登录→抓取→解析→写 tools/tt.json（--deploy 自动上传）
│  ├─ jwxt.py                 ← 登录协议 / 课表抓取 / HTML 解析
│  ├─ bookmarklet.html        ← 教务课表页一键同步码（人工辅助）
│  ├─ install_task.ps1        ← Windows 计划任务（pythonw，每天 07:00）
│  ├─ creds.dpapi             ← ⚠️ 机密：DPAPI 加密的教务账号密码，禁止外传/进 Git
│  └─ tests/                  ← 解析器 fixture 单测
└─ deploy/                    ← 部署与云资源脚本
   ├─ sync_tools.py           ← 【日常】把 tools/ 同步到线上
   ├─ setup_tool_site.py      ← 【一次性/续证书】建 Bucket + 传文件 + 签证书 + 绑域名
   ├─ creds.env               ← ⚠️ 机密：阿里云 AK/SK，禁止读取/外传
   ├─ deploy_cert.py          ← me.furina.fun 的证书脚本（历史遗留，与本项目无关）
   ├─ deploy_oss.py / sync.py / check_ak.py ← me.furina.fun 的历史脚本，勿改
   └─ acme_account_key.pem    ← ⚠️ 机密：Let's Encrypt 账号密钥
```

**云资源现状**

| 项目 | 值 |
|------|-----|
| Bucket | `tool-furina-fun` @ `oss-cn-hongkong`（公共读 + 静态网站托管 `index.html`） |
| 自定义域名 | `tool.furina.fun` → CNAME `tool-furina-fun.oss-cn-hongkong.aliyuncs.com` |
| 域名归属校验 | DNS TXT `_dnsauth.tool`（阿里云 DNS，`furina.fun` 在 `dns21/dns22.hichina.com`） |
| 证书 | Let's Encrypt（DNS-01），签发给 `tool.furina.fun`，90 天有效期；续期＝重跑 `setup_tool_site.py` |
| 无关资源 | `me-furina-fun` Bucket（竞选页），**不要动** |

---

## 3. 用户与使用场景

- **用户**：一名大一学生（信管专业），班级事务的执行者（竞选副团支书）。技术能力强，喜欢清爽、克制、可验证的东西。
- **使用者**：他本人 + 班里同学（**通过微信/QQ 扫码在手机浏览器打开**）。
  → 因此：**必须手机优先**；**必须能塞进微信/QQ 内置浏览器**（所以零外部请求、不用重型库）。
- **典型场景**：班会上抽签定顺序 / 随机分组、发作业清单图、发通知卡片图、查课表。
- **隐私立场**：全班名单是敏感数据。**现阶段坚决不上传**，只在本机算、在本机出图。

---

## 4. 代码结构（`tools/index.html` 内）

整站是一个 IIFE，按下面顺序组织。**改动时请先定位到对应区块，不要重排结构。**

| 区块 | 作用 | 关键标识 |
|------|------|----------|
| 工具函数 | `$` `$$` `esc()` `toast()` `copy()` | 文件顶部 |
| **数据层 `D()`** | **唯一存储入口**：`D.d`（内存数据）+ `D.save()` | 常量 `KEY="zq_tools_v2"`、`OLDKEY="ziqi.tools.v1"` |
| **通知层 `push()`** | 统一推送出口（webhook / QQ / 企微 / Server酱） | 读 `D.d.settings.{kind,url}` |
| 外壳 | 顶部 tab 切换 + 工作流步骤条 | `.tabs button[data-tab]`、`.steps button[data-step]`、`stepGo(n)` |
| **导出层 `exportCard(o)`** | **所有图片导出唯一出口**（v2 版式，规格见 `tools/tests/export_card_v2_spec.md`） | 入参 `{title,sub,file,rec,config,blocks,foot,qr?,qrNote?}`；`blocks` 支持 `lines` / `chips` / `groups` |
| STEP 1 抽签 | `parseExcl()` `doDraw()` `renderA()` | `A.result` / `A.cfg` |
| STEP 2 分组 | `gMembers()` `doGroup()` `renderG()` | `G.result` / `G.cfg` |
| STEP 3 结果单 | `sumData()` `renderSum()` | 汇总 `A` + `G` |
| 课表 | `ttData()` `renderTT()` `ttRenderWeek()` `ttRenderDay()` `ttRenderNext()` `ttOpenCourse()` `ttSyncPull()` `ttParseInput()` | `TT.pub` / `D.d.course` / `D.d.ttLocal` / `#tt=` 链接 |
| 教务同步 | `jwxt/sync.py`（本机 Python） | `tools/tt.json` + `jwxt/creds.dpapi` |
| 作业 | `renderHW()` `dueInfo()` `hwArr()` `hwBlocks()` | `D.d.homework[]` |
| 通知 | `renderNT()` | `D.d.notices[]` |
| 体测 | `ftCalc()` `renderFT()` `ftRead()` `ftLabels()` | `D.d.fit` |

### 扩展指南

- **加一个新工具**：在 `.tabs` 里加一个 `<button data-tab="x">`，加一个 `<section id="s-x">`，再写 `renderX()` 并在文件末尾初始化区调用。**不要动底部导航（已按用户要求删除）**。
- **加工作流新步骤**：在 `.steps` 加按钮 + `<div class="stpane" id="pN">`，在 `stepGo()` 的渲染分支里加钩子，在 `sumData()` 里把新步骤的 `config/blocks` 合并进结果单。
- **任何新的导出**：**必须**走 `exportCard()`，不要自己写 canvas——否则命名/水印/编号规范就断了。

### 数据结构（`localStorage` 键 `zq_tools_v2`）

```jsonc
{
  "course": [ {"name","teacher","room","day":0-6,"start":1-12,"end":1-12,"weeks":"1-16","parity":"all|odd|even"} ],
  "ttView": "week|day（空=按屏宽自动）", "ttUseMine": false, "ttLocal": {"c":[],"t":""}|null,
  "ttAdopt": "上次采纳教务课表时的 course JSON 串", "ttSyncAt": 0,
  "homework": [ {"subject","content","due","date":"YYYY-MM-DD","done":false} ],
  "notices": [ {"title","body","pin":false,"imp":false,"ts":1699000000000} ],
  "termStart": "2026-09-07",
  "draw":  {"start":1,"end":50,"count":10,"dup":false,"excl":"","sort":"draw|desc|asc"},
  "group": {"source":"prev|names","names":"","mode":"groups|pergroup","n":4,"shuffle":false},
  "settings": {"kind":"webhook|qq|wecom|serverchan","url":""},
  "fit": {"sex":"m|f","grade":"12|34","h":"","w":"","vc":"","r50":"","sit":"","jump":"","pull":"","durM":"","durS":""}
}
```

⚠️ **向后兼容**：启动时会尝试读旧键 `ziqi.tools.v1`（字段名 `courses` → `course`）并自动迁移。
**改数据结构时必须保留这条迁移路径**，否则老用户的数据会丢。

---

## 5. 部署与验收（改完必跑）

### 5.1 部署

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web\deploy
python sync_tools.py                 # 同步 tools/index.html + tools/assets/**
```

- **常设授权（2026-10-10 用户原话：“以后都直接上线”）**：四条自检全绿 + 线上 `index.html`
  已备份到 `tools/_backup/` 后，直接跑 `sync_tools.py`，**不必再问**；回滚＝重传备份文件。

- 上传后**立即生效**（对象设了 `Cache-Control: no-cache`，无需清缓存/等 CDN）。
- **课表数据**：`jwxt/sync.py` 生成 `tools/tt.json` 后，`python deploy/sync_tools.py tt.json` 单独上传（或 `sync.py --deploy` 自动上传；`sync_tools.py` 已把 tt.json 纳入默认列表）。
- 首次开站 / 证书续期（幂等，可重跑）：`python setup_tool_site.py`
- 凭据来自 `creds.env`（脚本自动读取；**不要打印、不要外传**）。

**域名暂停期本机临时通道（2026-11-10 新增，工具 `deploy/local_channel.py`）**

> 背景：`furina.fun` DNS 全部暂停期间 `tool.furina.fun` 不可解析；直接用 OSS 默认域名打开页面会因
> Origin 不在 CloudBase 网关 CORS 白名单而登录失败。临时通道只在本机起作用：
> 内存里把页面 CloudBase 基址改成同源 `/__cb/`，服务端带 `Origin: https://tool.furina.fun` 转发到 CloudBase
> （不改线上页面、不改网关配置、不需要证书/DNS）。默认仅监听 `127.0.0.1`。

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web
python deploy\local_channel.py --open        # 或双击 deploy\local_channel.cmd / 桌面「班级工具站_本地临时通道」
python deploy\local_channel_selftest.py      # 自检：headless Edge + 测试身份真实登录 → RESULT: PASS
```

详见 `deploy/LOCAL_CHANNEL.md`（原理/安全边界/常见问题）。域名恢复解析后不再需要。

### 5.2 四条自检（**全绿才算完成**）

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\web\tools
python tests\selfcheck.py            # ① 交互冒烟：模拟点击全部按钮，断言 0 JS 报错 + 旧数据迁移 + 无底部栏
python tests\overflow_check.py 430   # ② 横向溢出审计：overflowCount=0
python tests\shots.py                # ③ 各档宽度截图到 tests\_shots\（HUD 会打印 viewport/scrollW/overflow）
python tests\export_check.py draw    # ④ 抓取导出图片存盘（draw|group|flow|tt|hw）供肉眼核查
```

**判据**：
- ① 输出必须含 `PASS`、`ERR=(none)`、`navCount=0`；
- ② 输出 `overflowCount=0`；
- ③ 每张图的 HUD 必须 `scrollW == viewport` 且 `overflow=0`；
- ④ 能落盘 PNG，且图中「参数配置 / 水印 / 时间 / 编号」齐全、无溢出乱码。

需要 Python 包：`oss2`、`Pillow`、`opencv-python`（已有）。浏览器用本机 Edge：
`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`。

> ⚠️ 2026-11-04 身份门禁重构后现状：① `selfcheck.py` 与 ③ `shots.py` 仍按无门禁旧页面写
> （截图会停在身份页），暂时不能直接当门禁；小改动用「专项审计（真宽度溢出 / 交互 / 截图）」
> 替代 ①③，② 与 ④ 照跑，部署仍按 5.1 的授权流程。修测试的待办见 §11 / §19。

### 5.3 线上验收

```powershell
# 逐字节比对（最可靠）
python -c "import hashlib,urllib.request;l=open(r'C:\Users\Ko_Li\.openclaw\workspace\web\tools\index.html','rb').read();r=urllib.request.urlopen('https://tool.furina.fun/').read();print(hashlib.sha256(l).hexdigest()==hashlib.sha256(r).hexdigest())"
```

---

## 6. 已知坑（血泪，务必绕开）

1. **OSS 静态网站托管不对子目录应用首页文件**：`/tools/` 会被根目录 404 回退吞掉。
   → 所以本站必须**独占 Bucket 根目录**（独立域名才是正解）。已试过 RoutingRule，**无效**，不要重试。
2. **headless 浏览器 `--window-size` 不决定视口宽度**（实测恒为 ~492px）。直接截图会右侧被裁，视觉模型会**误报"溢出"**。
   → 必须用 **iframe 固定宽度**（`tests/shots.py` 已这么做），并在页面上打印 HUD 读数。
3. **`localStorage.setItem(key, 对象)` 必须 `JSON.stringify`**：否则存成 `"[object Object]"`（15 字节），页面全空、极难发现。
4. **阿里云 AK 在上下文中可能被"脱敏显示"**（`LTAI5t…17Fp` 里那个 `…` 是显示脱敏）。**直接把带省略号的串当参数会炸（latin-1 编码错误）**。真值只从 `creds.env` 读，永远不要手打。
5. **Let's Encrypt 续签**：账号已存在时 `new_account` 抛 `ConflictError` → 必须 `query_registration(RegistrationResource(NewRegistration.from_data(...), uri=None))` 并设 `ac.net.account`，否则报 `No Key ID in JWS header`。
6. **`canvas.toBlob` 是异步的**：写自检脚本时要拦截 `HTMLCanvasElement.prototype.toBlob` 转同步，否则抓不到产物。
7. **数据迁移**：改 `zq_tools_v2` 结构时，务必保留对 `ziqi.tools.v1` 的兜底读取。
8. **教务系统只能在"本机脚本"里抓**：教务站是 HTTP，而站点是 HTTPS —— 浏览器直连会被混合内容（mixed content）+ CORS + 无登录态三重拦截。正确链路是：本机 `jwxt/sync.py` 登录抓取 → 写 `tools/tt.json` → 上传静态文件 → 网页同源 `fetch('tt.json')`。
9. **教务凭据只许 DPAPI 本机保存**（`jwxt/creds.dpapi`）：不得进网页/仓库/日志/云端；`--save-creds` 用 getpass 交互输入，绝不把明文密码写进任何文件。
10. **教务系统登录必须走统一认证（SSO，2026-11-03 实测）**：用户密码是 `authserver.fjtcm.edu.cn` 的统一身份认证密码，jsxsd 直登会报密码错误。链路：authserver 登录（无验证码）→ 门户 `e.fjtcm.edu.cn`（内容在 iframe `CUS_TEMPLATE_DGUT`）→ 点「新教务系统」→ `210.34.74.77` 会话 → `xskb_list.do?viweType=0` 抓周表。**同一账号并发登录会互踢**，计划任务与手动 `--check` 不要同时跑。
11. **新版权课表页结构**：`table.qz-weeklyTable` 表头文本是 `周次,星期日,星期一,…,星期六`（服务器模板 bug），但 tbody 数据列实际是**周一起始**；解析一律按「数据列位置」映射 day，`--day-order header` 仅调试用。

---

## 7. 路线图（用户已确认的方向）

> 用户原话（2026-10-09）："我有计划让他成为一个真正的网站，租一个服务器，并为他进行 ICP 备案，
> 他要具备以后再可以同时在微信服务号/小程序、QQ 小程序、浏览器运行并同步的能力。"

### P1 — 轻后端：共享数据 + 定时通知（**零备案，可立即开工**）

> ⚠️ **2026-10-10 更新：作业共享已落地（P1 开工）。**
> 后端配置结果与前端接法 → **见 `CLOUDBASE.md`**（这是本节的实际执行版，以下保留为原始方案讨论）。
> 已定：腾讯云 CloudBase 个人版 · PostgreSQL + PostgREST HTTP 接口 · 前端零依赖 `fetch()`；
> 云函数方案已放弃（该环境无文档型数据库）。


现状痛点：数据在本机 → 作业/通知**不互通**；推送需页面打开。

建议接口草案（保持前端改动最小）：

```
GET  /api/v1/board?class=<id>          → { notices:[], homework:[], updatedAt, rev }
POST /api/v1/board                     → 覆盖写（需「班委口令」）
GET  /api/v1/pull?since=<rev>          → 增量拉取
POST /api/v1/notify/subscribe          → { channel, target, tags }  绑定推送
定时任务（每天 20:00）                  → 扫「明天到期」的作业 + 置顶通知 → 调通知适配器
```

- **鉴权**：写入用**班委口令**（前端只存 hash，服务端校验）；读取**只读公开**。
- **限流**：按 IP/口令限流 + 字段长度上限 + 简单敏感词过滤（防刷屏）。
- **存储**：复用现成云（阿里云函数计算 FC + OSS 存 JSON，或 Cloudflare Worker + KV），成本≈0。
- **前端改动**：把 `D()` 从"localStorage 直读"改成"远程为主 + 本地缓存"，把 `push()` 改成"服务端统一推"。
  **界面层不允许改**（这是本项目的硬约束：数据/通知两层是可替换的"插头"）。
- **隐私**：共享数据里**只放作业/通知这类公共信息**，**永不上传名单类个人数据**。

### P2 — 备案 + 大陆服务器

硬条件：**大陆服务器** + 域名实名 + 主体一致 + 内容合规；周期 5–20 个工作日；备案期该域名**不得对外提供访问**。

⚠️ **两大前置风险（务必先核实，别先买服务器）**：
1. **`.fun` 是否在工信部可备案后缀名单内** —— **极可能不在**。若不在，备案会被拒，**需另备 `.cn`/`.com` 兜底**。
2. **微信「服务号」个人注册不了**（需企业/组织主体 + 300 元/年认证）。
   个人可走的现实路线：**QQ 官方机器人**（用户已有现成基础设施）> 企业微信群机器人 > Server 酱 > 微信**小程序**（个人主体 **`web-view` 组件受限**）。

### P3 — 多端

- H5 一套代码 → 微信/QQ 小程序用 **web-view 套壳**（需**已备案域名 + 主体**）；或原生重写。
- 小程序要求：业务域名校验（站根放一个随机 txt 文件——这正是用户在 10-09 做过的那件事）、HTTPS、无违法内容。

---

## 8. 明确"不要做"的清单

- ❌ 不要引入 npm/框架/构建步骤；不要拆分文件导致无法直接用浏览器打开。
- ❌ 不要改 `tool.furina.fun` 的域名结构与 Bucket（除非用户明确要求）。
- ❌ 不要把任何密钥写进前端代码或仓库（`index.html` 里**一个 secret 都不能有**）。
- ❌ 不要上传用户名单/手机号等个人数据。
- ❌ 不要为了让界面"更好看"而违背 §1 的设计规范（无底部栏、无冗说明文字）。
- ❌ 不要删除 `tests/` 自检脚本，也不要让改动跳过 §5 的验收。

---

## 9. 交接待办（按优先级）

- [ ] 通读 `AGENTS.md` + 本文件，跑一遍 §5.2 四条自检，确认**当前基线全绿**。
- [x] ~~10-11 冻结期~~ 已于 2026-10-10 由用户解除（“以后都直接上线”）；体测工具已于 2026-10-10 08:20 上线（备份 `tools/_backup/index_online_20261010-0820.html`）。
- [ ] 与用户确认 P1 的三件事：① 服务器预算与云商 ② 主体（个人/社团/其他）③ 是否先注册 `.cn` 域名兜底。
- [ ] P1 落地：后端 + 前端"插头"替换，**界面零改动**为验收标准。
- [x] 补一份 `CHANGELOG.md`，记录每次上线时间与内容（已建，见仓库根 `CHANGELOG.md`）。

---

## 10. 附：常用命令速查

```powershell
# 同步上线
cd C:\Users\Ko_Li\.openclaw\workspace\web\deploy ; python sync_tools.py
# 开站/续证书
python setup_tool_site.py
# 自检
cd ..\tools
python tests\selfcheck.py
python tests\overflow_check.py 430
python tests\shots.py
python tests\export_check.py draw
# 线上比对
python -c "import hashlib,urllib.request;l=open('index.html','rb').read();r=urllib.request.urlopen('https://tool.furina.fun/').read();print('MATCH' if hashlib.sha256(l).hexdigest()==hashlib.sha256(r).hexdigest() else 'DIFF')"
# 教务课表同步（本机；密码＝学校**统一身份认证**密码，不是教务系统直登密码）
cd ..\jwxt
python sync.py --save-creds --account 3260707024   # 首次，getpass 输入（DPAPI 保存，仅本机）
python sync.py --check                             # 验证统一认证→门户→教务 SSO 全链路
python sync.py --out ..\tools\tt.json --deploy     # 抓取+写快照+上传（约 10-60 秒）
python sync.py --refresh-sso                       # 忽略 cookie 缓存，强制重新 SSO
python sync.py --manual                            # 自动流程失败时，可见 Edge 手动登录后抓取
powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -Run   # 装/跑每日 07:00 任务
```

---

## 11. 班级通知并入工具站（2026-11-04）

- 工具站「通知」tab 顶部新增「班级通知」云端板：`NT.pull()` 解析 `public.notices` 中
  `body` 以 `[[CLASS_NOTICE_V1]]` 开头的行；手动发布的通知仍在下方。
- 自动通知由 `C:\briefdesk\scripts\sync_notices_cloud.py` 写入：
  - `id = auto_<group.id>`
  - `body = [[CLASS_NOTICE_V1]] + <group JSON>`
  - 过时的 auto 行置 `archived=true`
  - 本地 `detect_docs.rebuild_board()` 构建后自动调用同步。
- 前端只在身份 token 通过后拉取；匿名请求返回空数组（已实测）。
- 自动通知板含 AI 标题/摘要/字段、附件预览下载、二维码直显、原始消息按钮。
- 注意：现有 `tests/selfcheck.py` 等仍按旧版无门禁页面写，需先更新测试再作为上线门禁。

### 通知板：班级简报 + 桌面双栏（2026-11-04 14:30）

- 通知 tab 顶部新增「班级简报」卡：待处理 / 24h 截止 / 7 天内 / 已过期 + 最近 3 个截止。
- 通知列表支持：待处理 / 已过期 / 已处理 / 全部、分类筛选、标记已处理（localStorage `zq_auto_nt_done`）。
- 桌面 ≥960px 自动两列；手机单列；分类/状态 chips 换行。
- 已部署并实测：登录后 7 待处理 / 12 过期 / 19 总；缴费分类 1 条；标记已处理生效；430px 无横向溢出。

---

## 12. 通知页整页搬入（2026-11-04 18:15）

- 工具站 `通知` tab 已改为承载完整通知页，而不是简化版卡片：
  - `#s-nt` 只保留 `#noticeHost`
  - `renderNoticeFrame()` 用 CloudBase 的 `AUTO_NOTICES` 生成 iframe 页面
  - iframe 内是 `notice-board-live-demo.html` 的完整 HTML/CSS/JS（简报、筛选、原始消息、附件、二维码、过期折叠、桌面双栏）
  - 页面头部品牌/页脚被移除；仅使用工具站配色（`#F7F8F8` / 白卡 / `--cy`）
- 模板生成：`tools\build_notice_embed.py`
  - 从 `tools\notice-board-live-demo.html` 提取 body/CSS/JS，注入 `__DATA__` 占位，base64 后写回 `index.html` 的 `NOTICE_TPL_B64`
  - 通知页 UI/逻辑更新后需重跑该脚本再部署
- 旧的发布通知/手动通知卡片、`#ntPanel`、`#nList` 已从 DOM 移除；云端 `auto_*` 通知仍由 watcher 同步。
- 已部署并实测：简报 6/2/2/13、19 张通知卡、页面内筛选/原始消息、桌面双栏、430px 无横向溢出。

> 注意：旧 `tools/tests/selfcheck.py` 仍包含已删除的手动通知组件断言，不能直接作为本次通知页上线门禁。

---

## 13. Monet 配色统一 + 小程序通知适配（2026-11-04 18:35）

- 网页工具站改用莫奈色 token：`#F4F0E6` 奶油底、`#FFFCF6` 卡片、`#5E8F87` 睡莲青、`#7D9EBB` 雾蓝、`#C6A475` 暖沙、`#B87870` 灰粉。
- 通知 iframe 模板 `build_notice_embed.py` 的 `TOOLS_VARS/OVERRIDE` 同步为同一套 Monet 色。
- 小程序 `mp-class-tools/app.wxss` 的 M3 token、`theme.json`、页面/组件里的旧品牌色统一替换为 Monet 色。
- 小程序通知页 `pages/nt/*` 重写为云端自动通知：
  - 读取 `public.notices` 的 `auto_*` 行
  - 简报统计、待处理/已过期/全部、分类筛选
  - AI 摘要/要点/字段拆分、附件（图片/PDF 打开）、原始消息弹层
  - 移除旧发布通知/置顶/手动通知逻辑
- 验证：小程序 `unit.js` 49/49、`staticcheck.py` handlers missing 0、`cli preview` 编译成功；网页端生产 iframe 19 卡、移动端无横向溢出。

## 14. 通知按人群可见（2026-11-04 18:55）

- `public.notices` 新增 `audience` 列；RLS 按 token 身份过滤。
- 自动映射：红会群 → `sid:3260707024`（仅陈子麒）；班委群 → `committee`；其余 → `all`。
- `nt_insert/nt_update` 收紧为管理员，防篡改 audience。
- 已验证管理员 19、班委 18、普通 18、匿名 0；班委临时测试通过后恢复。

## 15. 通知截止时间按消息发送日期解析（2026-11-04 19:10）

- `build_notice_board.py` 的 `extract_deadline(text, ref)` 重写：
  - 只从「截止/截至/前/报名时间/提交时间」语境取时间，不再把活动时间、集合时间当截止；
  - `今天/明天/后天/今晚/明晚` 以消息 `time` 为锚，而不是脚本运行时间；
  - 支持 `11月3日24:00前`（跨到次日 00:00）、`今晚八点`、`今天六点半`、`截止今天18:30` 等；
  - 合并转发补回每条消息的发送时间；最后一条带明确截止的消息优先。
- `ai_brief.py` 把系统解析出的当前截止写进 AI 提示并参与缓存键；AI 输出里的相对日期会替换成绝对 `MM-DD HH:MM`。
- 已重建 19 组并同步 CloudBase：例如培训班“今天下午三点”→ 11-03 15:00；校运动会观众“今天六点半”→ 11-03 18:30；挑战杯“2027年6月1日以前”→ 2027-06-01；无明确截止的思政/太极拳/选课通知改为“无截止”。

## 16. 通知 iframe 内弹层点击修复（2026-11-04 19:25）

- 现象：通知页嵌入 iframe 后，点击「原始消息 / 图片 / 文件预览」看不到弹层。
- 根因：iframe 高度等于整页内容高度（约 4600px），通知页里的 `position:fixed` 弹层按 iframe 视口居中，中心点落在页面可视区之外。
- 修复：iframe 改为固定视口高度并独立滚动：
  - `height: calc(100vh - 150px)`，手机 `calc(100vh - 140px)`
  - `scrolling="yes"`
  - 父页不再用子页 postMessage 设置整页高度
- 已验证：原始消息、二维码、PDF 预览弹层都在 iframe 可视区居中显示。

## 17. 时间模型扩展 + 手机弹层全屏（2026-11-04 19:55）

- 时间不再只看 `deadline`：
  - `eventAt`：活动/测试/集合时间；无明确截止时用于判断时效
  - `expireAt`：实际失效时间；优先于 deadline
  - `timeLabel`：卡片顶部展示文字（如「报名 11-05 12:00」）
- 规则：
  - 体育课补测：`eventAt=10-31 10:40`，超过后自动「已结束 · 自动归档」
  - 挑战杯：`2027-06-01` 是「符合报名条件」时间，不再当截止；该通知显示「无时间」
  - 两个药膳打卡：`eventAt=11-05 12:00`（报名开放），`expireAt=11-06 12:00`（开放一天后过期）
  - 无明确截止但能解析活动时间的通知，按活动结束后自动结束；不能解析则「无时间」
- 通知弹层：iframe 内 modal 打开时通过 postMessage 让父页面把 iframe 全屏，关闭后恢复；手机/桌面暗层全屏，卡片在视口内滚动。
- 小程序 `nt.js` 同步支持 `expireAt` / `eventAt` / `timeLabel`。
- 已重新生成 19 组、重生成 AI 摘要、同步 CloudBase 并部署。

## 18. 小程序通知完整化（2026-11-04 20:10）

- 小程序 `pages/nt` 增加：
  - 卡片「展开 / 收起」：摘要常显，详情（字段拆分、附件、图片）按需展开
  - 展开时才加载该通知的图片 data URI，避免 setData 一次塞入全部图片
  - 图片横向缩略图，点击走 `wx.previewImage`，支持多图
  - 文件在展开区打开；原始消息继续走底部弹层
  - `expireAt / eventAt / timeLabel` 状态：无截止但有活动时间的通知会显示「已结束」
- 已通过小程序 `unit.js` 49 项、`staticcheck.py` handlers 0、`cli preview` 编译（409 KB）。

## 19. 全部栏卡片配色 + 按钮底部对齐（2026-11-04 20:40）

- 「全部」页卡片（`renderAllCards()` 生成）从旧白/灰绿改为莫奈系：卡片底 `--card`、描边 `--line`；
  页眉按工具族着色，色调映射在 `ALL_TONE`（`draw/tt/committee/hw/nt/ft/roll/stats` + `fb=mint`、`ug=plain`），
  通过 `data-tone` 属性驱动 CSS 变量 `--tl-bg / --tl-ink / --tl-bd`。
- 「打开」按钮跟随卡片色，「设为首页」保持描边幽灵样式；`.tdesc` 文字色改为 `#6E7A72`。
- **按钮底部对齐**：`.gcard.tool{display:flex;flex-direction:column}` + `.bd{flex:1;display:flex}` +
  `.bd .row{margin-top:auto}`，同一网格行卡片等高时按钮贴底；不涉及分组结果卡（`.gcard` 无 `.tool`）。
- 验证脚本（临时，已删）：真宽度 360/430/720/1280、普通/管理员两种身份，审计 overflow / 同行按钮底差 /
  色调生效 / 逐卡点击 / JS 报错，全部为 0；部署后线上逐字节 MATCH。
- 顺带发现：`tests/selfcheck.py`、`tests/shots.py` 仍是身份门禁改造前的旧脚本（会被身份页挡住），
  待更新后才能重新作为上线门禁（见 §5.2 现状说明）。

## 20. 手机标题栏减负 + 卡片/框浮起（2026-11-04 20:58）

- **手机顶部栏**：`@media (max-width:600px)` 下 `.brand` 隐藏 `.dots` / `.idrole`，标题 17px/800，
  域名 10px，`.idchip` 限宽 7.4em；`.brand` 顶部 padding 走 `env(safe-area-inset-top)`，`.tabs` 的
  `top` 也让出安全区并加柔和投影。宽屏（>600px）布局不变。
- **层次 token**（`Monet palette` 的 `:root` 内新增）：`--surface:#FFFFFF`、`--line-strong:#E0D2BC`、
  `--tint-panel:#FBF6EC`、`--elev-card`。`.card/.gcard/.gcard.tool` 用白卡 + `--elev-card`；
  `.result/.item` 用 `--tint-panel`；输入框 `#FDFAF2` + 内阴影；`.ck/.steps` 同步。
- **通知 iframe**：`build_notice_embed.py` 的 `OVERRIDE` 同步为白卡/同投影/浅沙内框，重建
  `NOTICE_TPL_B64`（重建后模板与 old 仅 OVERRIDE 区不同；demo 源文件与旧模板内容逐字节一致）。
- 验证（临时脚本，已删）：320/360/390/430/601/720/844/1280 八档审计 overflow=0、JS 错误 0、
  全部栏按钮底差 0；320–430 身份胶囊不截断；通知页 mock 数据下 390/1280 渲染正常；draw 导出正常。

## 21. 打开网页默认停在工具栏第一格（2026-11-04 21:07）

- 新增全局 `LANDING=true`；`renderTabs()` 在 `AUTH.ready` 为真时首次消费：
  `CURTAB=home[0]||"draw"`，即工具栏第一个（自定义 `homeTools` 顺序 / 当前竖横屏可见槽位均生效）。
- 只消费一次：切 tab、拖拽换栏、旋转屏导致 `renderTabs()` 重排时保持当前页；身份门禁未通过前的
  resize 不消费标记（避免落地错误）。
- 验证（临时脚本，已删）：默认/自定义三组顺序 × 360/390/1280 落地页正确、第一格高亮、点 tab 与 resize
  后不重置、全部栏正常、0 JS 报错；线上 sha256 MATCH（317,216 B）。

## 22. 通知弹层背景 + 截止时间误判修复（2026-11-04 21:53）

- **弹层拉宽背景**：父页在 `class-notice-modal-open` 时仍把 iframe 拉成全屏（否则暗层只盖半屏），
  但模板新增 `body.modal-on .wrap{visibility:hidden}`（由 `build_notice_board.py` 里 120ms 轮询同步
  `modal-on` 类），弹层打开时不再露出被拉宽的列表；关闭后恢复。
- **截止时间误判**：`classify_qq_text.py` 旧逻辑对所有 QQ 文本通知兜底写
  `expireAt = created+7d 23:59`，模板 `statusOf()` 又用 `expireAt` 当截止显示，导致
  「运动会期间晚自习正常」（原文无时间、AI 返回 deadline=null）显示 `11-11 23:59 截止`。
  - 数据：`classify_qq_text.make_group` 只在有截止/活动时间时写 `expireAt`（只事件 → `eventAt+2h`；
    都没有 → 全空）；`build_notice_board.load_qq_text` 清理旧数据（`eventAt == _createdAt` 视为占位丢弃、
    无时间不写 `expireAt/timeLabel`），`main()` 统一兜底。
  - 模板：`statusOf()` 只按真实 `deadline`（含延期）判断/显示截止；只有 `eventAt` 时按活动结束判断；
    两者都无 → 「无时间」；`expireAt` 仅用于归档不再当截止。`stats()` / `briefNext()` 同步改真实截止。
- 数据链路：重建 `board-data.json` + `notice-board-live-demo.html`，`sync_notices_cloud.py` 同步
  CloudBase **20/20**；`auto_g_qqtext_77a2abbbf7` 的 `deadline/eventAt/expireAt/timeLabel` 均为 null。
- 验证（临时脚本，已删）：全量 20 组卡片状态审计（无时间 5 组 / 真截止显示具体时间 / 事件结束显示
  「已结束 · 自动归档」）；390/1280 弹层为干净暗层、关闭恢复静态 iframe；0 JS 报错；overflow=0；
  线上 `index.html` sha256 MATCH（318,512 B）。
- 注意：本次线上只替换内嵌通知模板（线上旧版 + 新模板上传）；工作区 `index.html` 另含并行会话的
  「名单选择」改动，未随本次上线。

## 23. 名单改为班级名单选择器 + 液态气泡（web 端，2026-11-04 22:13，已上线）

### 交互
- 三处名单**不再支持自定义输入**：
  - 抽签 STEP1：删掉 `#aRoster` textarea、`#aRosterHint`、`#aDefRoster/#aUpRoster/#aPaste/#aClear` 与相关监听；改为「参与名单」行 = 已选名单气泡摘要 +「选择名单」+「清空」+ 抽签池提示。
  - 分组 STEP2：「粘贴名单」单选改名「选择名单」（内部 `value="names"` 便于旧数据）；删掉 `#gNames` textarea，改为摘要 +「选择名单」。
  - 点名：删掉 `#rNames` textarea 与 `#rImportClass`；保留「沿用抽签名单」（从抽签页已选名单），新增「选择名单」。
- **单例弹层 `#rosterModal`**（draw / group / roll 共用）：移动端（≤600px）底部弹层（max-height 88vh、内部滚动），桌面（≥601px）居中卡片（520px）。标题「选择抽签名单 / 选择分组名单 / 选择点名名单」；点气泡切换、全选 / 清空 / 取消 / 确定、计数「已选 N / 70」；Esc / 遮罩 = 取消；取消不写回；气泡是 `<button>`，回车/空格可切换，focus-visible 可见。
- 页面摘要气泡只显示名字（不显示座号、不可输入、无 ×）；超过 12 个显示「+N」，点摘要气泡打开弹层。

### 代码位置（`tools/index.html`）
- 弹层 DOM：`<div class="modal roster-modal" id="rosterModal">`（正文末尾、`#toast` 之前；无 goo 层 / 无 SVG 滤镜）。
- CSS：`/* ===== 班级名单选择 ... ===== */` 段（`</style>` 前）：`.rsum/.rchip/.roster-modal/.rst-*`（气泡、玻璃高光、浮动/果冻/pop、reduced-motion）。
- JS：
  - 弹层 + 迁移 + 摘要：`/* 班级名单（只允许从班级名单里选人，不能自定义） */` 段（`membersPull()` 之后）。
  - 入口：`openPicker(mode)`、`RST`；摘要渲染 `renderRosterSums()`；抽签池提示 `updateDrawHint()/drawPoolCount()`；写回 `applyDrawSel()/applyGroupSel()/applyRollSel()`、`writeRollFromSel()`；迁移 `migrateRoster()`。
  - 触发位置：`bucketInit()`（缓存 members 时启动迁移）、`membersPull()`（云端名单到达后迁移）、`doDraw()`（抽签池语义）、`gMembers()`（分组名单来源）、`renderRoll()`、`startClassData()`。
  - 事件：`#aRosterPick/#aRosterClear`（draw）、`#gRosterPick`（group）、`#rPickSel/#rImportDraw`（roll）；弹层底部 `#rstAllBtn/#rstNoneBtn/#rstCancel/#rstOk`。

### 数据字段（`localStorage` 键 `zq_tools_v2_<sid>`）
- 新增：`rosterSel` / `groupSel` / `rollSel`（座号数组，1–70、去重、升序）、`rosterMigrated`（一次性迁移标记）。
- 派生兼容文本（每次选择变化写入，旧算法继续可用）：`roster = "座号 名字\n…"`、`group.names = "名字\n…"`、`rollNames = "座号 名字\n…"`；`rollSt` 以新名单下标为键。
- `classRoster` 不再使用（字段保留兼容，迁移时清空）；`DEFAULT` 里三个 sel 默认 `[]`。

### 迁移规则（幂等，members 可用后执行一次）
1. 旧 `roster` 文本逐行：`序号 名字` / 纯名字；行内序号若与该座号成员姓名一致直接采用，否则按姓名与班级成员精确匹配 → 座号；匹配不到丢弃。
2. 旧 `group.names` 同上（按姓名匹配）→ `groupSel`，派生文本只写名字、按座号升序。
3. 旧 `rollNames` + `rollSt`：按旧列表顺序取姓名与状态，匹配成员 → 座号；新列表按座号升序重建 `rollNames`，`rollSt` 按姓名保留「到/假」状态并重排索引；匹配不到丢弃。
4. `classRoster` 清空，`rosterMigrated=true`，`D.save()`。

### 抽签 / 分组 / 点名语义
- 抽签：`rosterSel` 为空 → 旧行为只抽序号；非空 → `pool = 所选座号 ∩ 范围 − 排除`，结果必带姓名；池为空 / 人数不够有明确 toast；UI 提示「已选 N 人 · 抽签池 M」，导出参数「参与名单（N 人）」。
- 分组：`g.source==="names"` 时成员取 `groupSel` 对应成员（`{n:座号,nm:名字}`，升序）；未选择 toast「请先选择名单」；导出成员来源显示「选择名单」。
- 点名：名单由 `rollSel` 派生 `rollNames` 呈现；「沿用抽签名单」= `applyRollSel(D.d.rosterSel)`；状态按姓名保留。

### 视觉（2026-11-04 22:34 简化为整站克制风格，已上线）
- **用户反馈**：名单气泡「液态糖果风」太花，要求更简约、贴合整站风格 → 与 `.ck/.btn/.steps button.on` 同一套 option chip 语言。
- **选择器气泡 `.rst-b`**：未选 `#FFFCF6` 底 + 1px `var(--line)` 暖沙边 + `var(--ink2)` 字（13.5px/600，min-height 40px，padding 8px 13px）；已选 `#F1F7F5` 底 + `var(--cy)` 边/字（font-weight 700，对齐 `.steps button.on`）；hover `#F2F5F4` / 已选 hover `#E9F3F0`；press 仅 `transform:scale(.985)`；transition 130ms；focus-visible 2px teal outline；座号 10.5px、opacity .45（已选 .65）、与名字间隔 4px。
- **页面摘要 `.rchip`**：小号已选标签 `.rchip`：`#F1F7F5` 底 + `#CFE3DD` 边 + teal 字（12px/600，padding 3px 9px）；`+N` 虚线透明幽灵；空态灰字保留；无任何 animation。
- **已删除**：`rstFloat`/`rstPop`/`rsumFloat` keyframes、`.rst-b::before` 玻璃高光、渐变/内阴影/box-shadow 光泽、`--i` 错峰延迟、JS `rstPress/rstPop`/pointerdown 逻辑；`prefers-reduced-motion` 段精简为仅关闭弹层入场动画与过渡。
- 历史：此前曾评估 goo 融合（SVG `feGaussianBlur`+`feColorMatrix`），因气泡缝隙出现白色透底空洞而放弃；随后方案 C 液态气泡（渐变/高光/浮动）也已按本次反馈移除。性能：70 个纯色 chip，无滤镜无持续动画。
- **上线（22:34）**：线上 `index.html` **336,035 B** · sha256 `c626698f…7e1e1b3`；与线上最新通知磨砂弹层/模板（TPL `37a51a1a`）共存，名单简化样式已生效；已对线上字节复跑 `roster_check.py` 199/199 PASS。回滚：旧视觉版 `tools/_backup/index_online_20261104-223112_preTemplateUpdate.html`（342,576 B）；新基线备份 `tools/_backup/index_online_20261104-2233_simpleRoster.html`。

### 验证命令
```powershell
cd tools
python tests\roster_check.py          # 专项自检：199/199 PASS（注入假身份 + 合成 70 人名单 + 旧名单迁移）
python tests\overflow_check.py 430    # overflowCount=0（旧脚本仍会被身份页挡住，仅作宽度参考）
python tests\export_check.py draw     # 落盘 tests\_shots\export_draw.png（已注入假身份）
```
- 截图：`tools/tests/_shots_roster/roster_{all,mixed,none}_{390,1280}.png` + `roster_page_summary_390.png`（全部合成姓名「同学01–70」）。
- `roster_check.py` 覆盖：旧名单迁移（非法姓名丢弃、点名状态按姓名保留）、弹层 70 气泡、0/70→70/70→确定、页面摘要、抽签结果全带姓名、只选 3 人抽签池=3 与超池提示、分组 5 人、360/390/430/720/1280 无横向溢出、reduced-motion、0 JS 报错。
- 已知：`selfcheck.py` / `shots.py` 仍是身份门禁前旧脚本，不作为本次门禁。

### 上线记录（2026-11-04 22:13，并行合并后 22:20）
- 本次名单上线（22:13）：`index.html` **333,218 B** · sha256 `cd4a7c4034e4a9bf6eabf97328ec83d00ad229205cf1bbaee053ac6336b53baa`（与自检版本逐字节一致）。
- 当前线上（22:20 另一会话把新通知模板基于实时线上版合并上线后）：**339,237 B** · sha256 `b88c9be1c2da524476a19f05ddd65e54a02a8724b0fceae94bfc3e7ec390bea0`；名单功能完整保留，已对**线上字节**复跑 `roster_check.py` **199/199 PASS**。
- 部署方式：**混合上传** —— 以部署前线上版（318,512 B）+ 本次名单改动合成，保留当时线上旧通知模板（`NOTICE_TPL_B64` sha 前缀 `cfa4ca2c`），不把并行会话尚未上线的通知模板带上线；并行会话随后基于实时线上版合并新模板（`3d4ac9a0`），双向改动共存。
- 线上冒烟：身份门禁正常显示；线上字节含 `#rosterModal / #aRosterPick / rosterSel / 选择名单`，不含旧 `#aRoster/#gNames/#rNames/#aPaste`。
- 验证：实现者 `roster_check.py` 199/199 PASS；验收者 `roster_check_verify.py` 157/157 PASS；`export_check.py draw` 落盘 204,844 B PNG。

### 回滚
- 部署前线上备份：`tools/_backup/index_online_20261104-2203_preRoster.html`（318,512 B，直接重传即回到改动前线上）。
- 本地改动前版：`tools/_backup/index_local_20261104-2132_preRoster.html`（317,216 B）；用它覆盖 `tools/index.html` 后重新部署。
- 无需清数据（新字段对旧版是未知字段，旧版读取不受影响；旧字段 `roster/group.names/rollNames/classRoster` 仍在，旧版可继续用）。


## 23. 通知弹层背景改为「原页面磨砂变暗」（2026-11-04 22:33）

- 旅行者：弹层背景不要纯色填充，要原页面的磨砂变暗。
- **结构**：弹层内容仍由通知 iframe 生成（openOriginal/openImg/openFile），但改为 presentModal()：
  - window.parent !== window（嵌入网页）→ postMessage({type:'class-notice-modal-open',html}) 交给父页面；
  - 单独打开 demo → 仍用内置 #modal（closeModal() 关闭）。
- **父页**（web/tools/index.html）：新增 #ntModal（.nt-modal：position:fixed;inset:0;backdrop-filter:blur(7px) +
  
gba(40,50,42,.34)；卡片 .nt-modal-card 白卡、max-height:88vh 滚动）；message 监听改为渲染卡片，
  × / 点暗层 / Esc 关闭并还焦点。**iframe 不再 fixed 拉伸**（删掉 .notice-host.modal-open iframe{position:fixed…}）。
- **模板**（riefdesk-plan/build_notice_board.py）：新增 presentModal/closeModal；移除 120ms 全屏轮询与
  ody.modal-on .wrap{visibility:hidden}。
- 验证（临时脚本，已删）：390/1280 弹层打开后 iframe 保持 static 362×1060 / 1188×750，overlay 计算值
  lur(7px)；关闭后 #ntModal class/内容清空；主页面冒烟 0 JS 报错、overflow=0；线上 sha256 MATCH
  （338,372 B，sha a6f39ee…）。
- 注意：本次部署用工作区 index.html（已含并行会话的名单选择改动 + 新通知模板）；部署前线上
  （339,237 B，名单功能 + 旧通知模板）已备份。回滚点：	ools/_backup/index_online_20261104-2226_preFrostModal.html。

## 24. 统计页显示优化 + 全站去除学号（2026-11-04 22:50，已上线）

- 旅行者：网页也去掉所有学号（不显示，而非打码）；优化统计功能显示。
- **学号**：班委名单去掉打码学号（`.cmsid` + `maskSid()` 删除）；反馈列表（管理员）改用 `memberNameBySid()` 按姓名显示（未知→「（未知成员）」）；统计不再输出学号/尾号；`D.d.verify` 去 `sidMask`；工具描述/使用说明同步为「按姓名」「按账号同步」。
- **统计**：`#s-stats` 重新排版 —— 标题 +「仅管理员 · 按姓名聚合，不显示学号」+ 今天/近 7 天 + 三格摘要（访问账号/访问次数/今日活跃）+ 排行（名次、姓名、最近访问、近 7 天「活跃 N/7 天」、占比条、次数）+ 口径说明；`renderStats()` 重写（按 sid 内部去重、显示姓名；旧匿名行不参与）；CSS 新增 `.stsum/.strow .rk/.stnote`，≥720px 宽屏名称列 120–240px。
- **验证**：`roster_check.py` 199/199；`overflow_check.py 430` overflowCount=0；`export_check.py draw` 206,970 B；假数据预览 390/430/1280，统计页 `rows=10 errs=0 sw==iw noSID`（今天/近 7 天）；线上 sha256 与本地 MATCH；线上 `cmsid`/`maskSid` 0、`stSum`/`memberNameBySid` 在。
- **上线**：`tools/index.html` 339,436 B · sha256 `d5f96b9e46bd29a6…`；回滚 `tools/_backup/index_online_20261104-2250_preNoSidStats.html`（336,035 B，重传即回滚）。
- 说明：与并行会话名单/通知改动共存，未改其逻辑；统计只展示已完成身份验证的访问。

## 25. 抽签页补回「重置」按钮（2026-11-04 22:50 随统计页一起上线）

- 旅行者：抽签页的「重置」按钮不见了。核查：网页版历史线上备份（`tools/_backup/` 50 份，10-11 → 11-04 22:34）里抽签页**从未有过**「重置」；该按钮只在小程序抽签页底部操作条（`mp-class-tools/pages/draw/draw.wxml` `bindtap="reset"`）。本次按小程序语义在网页补回，两端对齐。
- **代码位置**（`tools/index.html`）：
  - DOM：`#p1` 参数卡片 `.row` 内 `#aRun` 之后 `#aReset`（`btn ghost`，文字「重置」）。
  - JS：`$("#aRun").addEventListener(...)` 之后新增 `#aReset` 监听（在 `var G` 声明之前，闭包内引用，运行期已初始化）。
  - 使用说明：`#ugBody` 抽签段新增一条「点「重置」清空本轮抽签与分组结果，参数和参与名单保留。」
- **语义**：无结果 → toast「本轮还没有抽签结果」不弹确认；有结果 → `confirm("重置本轮抽签？将清空抽签结果与分组结果（参数与名单保留）")`；确定后清 `A.result/A.cfg/A.log/A.removed/A.pool` + `G.result/G.cfg`，`renderA();renderG();renderSum();`，toast「已重置抽签与分组」；**参数（`D.d.draw`）与参与名单（`rosterSel`/`groupSel`）不动**（与小程序 reset 一致：清结果不清设置）。
- **验证**：`tools/tests/reset_check.py`（新增，109 项；假身份 + iframe 固定宽度 + headless Edge；`RESET_SRC` 可复盘任意副本）**109/109 PASS**——DOM/位置/40px 可点区、无结果提示、取消保留、确定清空 4 处（抽签/剔除记录/分组/结果单）、参数与名单保留、仅分组可重置、0 JS 报错/0 console.error/无外部请求、360–1280 无横向溢出；截图 `tools/tests/_shots_reset/`。回归 `roster_check.py` 199/199、`overflow_check.py 430` overflowCount=0、`export_check.py draw` 正常。对**线上字节**复跑 109/109 PASS。
- **上线**：线上 `index.html` 339,436 B · sha256 `d5f96b9e46bd29a6…`（随并行会话 22:50 统计页部署一起上线，两份改动共存）。回滚：`tools/_backup/index_online_20261104-2250_preNoSidStats.html`（336,035 B，重传即回到两改动前的线上）。
- **独立验收**（另一 agent fresh context，脚本 `tools/tests/_reset_verify/verify_reset.py`）：**验收项 151/151 PASS、过程项 2/2 PASS、0 FAIL**；起止 sha256 均 `d5f96b9e…`（验收期间未被并发改动）；人工 read_image 复核 390/1280 截图；报告 `tools/tests/_reset_verify/report.json`。唯一无害观察：`#aOut` 的 `data-log` 属性重置后未 remove（只写不读、不可见、无行为影响）。
- 小提示：本地提交前如遇并发会话写同一文件，先重读再最小增量合入（本次两次被并发修改后重新 rebase 过）。

---

## 26. 网页性能与缓存优化（2026-11-04 23:30，已上线）

> 需求（旅行者）：对网页/小程序容易因手机性能或网络卡顿处做性能和视觉优化；大部分内容首次打开后缓存，
> 减少后续加载。本文档只记网页端；小程序见 `mp-class-tools/README.md`（v18 / 1.4.5）。

### 26.1 问题定位（实测数字）

- `notices?select=*&order=ts.asc&archived=eq.false` 单次 **2,001,996 B**（43 行：24 auto + 19 manual；
  9 张图片 data URI 1,310,983 字符 + 5 个文件 data URI 605,116 字符），服务端**无 gzip**；
  只取 `select=id,ts` 时仅 **2,106 B**（约 1/950）。
- `homework` 仅 1,179 B、`fitrecs` 3,854 B、`marks` 361 B——不是瓶颈。
- 旧实现：`cloudPull()`（boot + `setInterval` 30s + `visibilitychange`）里 `NT.pull()`/`HW.pull()`
  每次都整表 `cache:"no-store"` 重拉；`gotoTab('nt')` 也 `NT.pull()`；`NT.pull` 成功后无条件
  `renderNoticeFrame()` 用 `doc.write()` 重建 2MB iframe（boot 即创建，哪怕没进通知 tab）。

### 26.2 实现（`tools/index.html` 内新增/改动，ES5、单文件）

| 区块 | 关键符号 | 说明 |
| --- | --- | --- |
| 缓存层 | `CACHE_VER=2` `IDBQ` `cacheNoticesGet/Set` `cacheKill` | IDB `zq_cache_v1/kv` 只存 AUTO_NOTICES；sid+代际隔离；失败静默 |
| TTL 元数据 | `TTL` `needPull()` `syncedMark()` `visitedMark()` `migratedMark()` | localStorage `zq_synced_at_*` / `zq_visited_*` / `zq_migrated_*`（按 sid） |
| 签名重校验 | `cbSig()` `sigOfNotices()` `cbGetNotices()` | `notices?select=id,ts&order=ts.asc,id.asc` ≈2KB，一致只更新时间 |
| 通知 | `NT.pull/refresh/fetchFull/applyCache` | TTL 门控 + id,ts 签名 + 迁移标记持久化 + 骨架 |
| 作业 | `HW.pull` | TTL 门控 + 迁移标记持久化（homework 本身很小） |
| 其他表 | `marksPull/membersPull/fitPull/ttSyncPull` | 各自 TTL；marks 快照进 localStorage |
| 启动 | `startClassData` `bootCache()` `bootRefresh()` | 本机先渲染→IDB hydrate→小表 TTL→大表 idle≥2s 后台 |
| 通知 iframe | `renderNoticeFrame()` `noticePerfPatch()` | 未进通知 tab 不建；数据不变不重建；图片 lazy/async；弹层 blur 降级 |
| 骨架 | `skelHTML()` + `.skel*` CSS | 同色系 shimmer，`prefers-reduced-motion` 关闭 |

TTL：`notices/homework 10min`、`marks 2min`、`fit 5min`、`members/tt 6h`、`visits 10min`。
`force` 只用于显式刷新（当前网页无按钮，保留给测试/后续）；30s 轮询调用 `cloudPull()`（无 force），
大表 TTL 内 0 请求。

### 26.3 验收与门禁

- 新增 `tools/tests/perf_check.py`（headless Edge + 假身份 + fetch mock，合成 24 卡 / 3.2MB payload；
  `PERF_SRC=<副本>` 复盘任意字节）：**123/123 PASS**（对线上字节复跑）。
- 回归：`roster_check.py` **199/199**、`reset_check.py` **109/109**（对线上字节）、
  `overflow_check.py 430` **overflowCount=0**、`export_check.py draw` 正常落盘 PNG。
- 验收脚本自身产物在 `tools/tests/_perf_shots` / `_perf_reports`（过程文件，勿入库）。

### 26.4 上线与回滚

- 线上最终字节：**353,460 B · sha256 `7a7628b1ffb16f32febf69f4f822993831f6a84dbb71d64c4d12a6cdfdf7b9c5`**
  （与并行会话的 visits/feedback `cbPostNoRep` 修复共存；对方部署后覆盖了本会话首次部署的 353,042 B 版本，
  最终字节已包含双方改动，本会话已对最终字节复跑 perf_check/reset_check 全绿）。
- 回滚点：`tools/_backup/index_online_20261104-2321_perf.html`（339,436 B，本次优化前的线上字节；
  重传即回滚到优化前，会同时回滚并行会话的后续改动，需谨慎）。
- **并发提醒**：本次期间另一会话在同一 `index.html`/本地文件上改 stats/feedback 并部署，出现过
  「本地 ≠ 线上」的短暂状态；以后改完部署前先取线上 raw bytes 比对，避免覆盖。

### 26.5 后续建议（本次未做）

- 根治 2MB：通知的图片/附件别再以 data URI 内嵌进 `notices.body`，改成 OSS/CloudBase 存储外链
  （预计整表降到 ~50KB，首开也几乎瞬时）。属 briefdesk/云端改造，需另开任务。
- 网页暂无「手动刷新通知」按钮：如需要可加一个 force 入口（一行 `NT.pull(true)`）。

---

## 27. 访问统计修复：非管理员访问/反馈写入被 401（2026-11-04 23:30，已上线）

> 用户反馈：统计列表始终只有自己一个人，即使换别人的账号登录后再看也一样。

### 27.1 根因（已实测，不是显示问题）

- `public.visits` / `public.feedback` 的 SELECT RLS 原来只有 `auth_admin()`；
- 网页 `cbPost()`（`cbH(true)`）与小程序 `headers(true)` 对写入统一带 PostgREST
  `Prefer: return=representation`；
- PostgREST 的 INSERT + returning 要求新插入行**同时能被 SELECT**，于是非管理员写这两张表返回
  `401 DATABASE_42501 new row violates row-level security policy for table "visits"`，
  网页 `.catch(function(){})` / 小程序 `.catch(return false)` 静默吞掉；
- 结论：除管理员外的访问**压根没入库**（管理员自己能被 SELECT，所以正常）；反馈提交同样坏掉。
- 复现证据：headless Edge 以普通成员身份打开线上站 → `POST /rest/visits` **401**；Python 直连同一
  token，不带 Prefer → 201，带 `Prefer: return=representation` → 401。DB 里当时只有管理员 36 行 + 旧匿名 81 行。

### 27.2 修复（三层，缺一不可）

1. **云端 RLS**（`deploy/cloudbase/2026-11-04_visits_feedback_own_read.sql`，已应用）：
   ```sql
   vs_read: auth_admin() OR (auth_ok() AND sid = auth_acc())
   fb_read: auth_admin() OR (auth_ok() AND acc = auth_acc())
   ```
   写入策略不变（visits 仍只能写自己 sid；feedback 仍 `auth_ok()`）；管理员照旧读全部，
   普通成员只能读自己那几行，**不暴露他人数据**。这一步让**已部署的旧页面/小程序**立即恢复写入。
2. **网页**（`tools/index.html`）：新增 `cbPostNoRep()`（POST 不带 returning 头，仅判 `r.ok`），
   `visitLog()` 访问埋点与反馈提交改用它；其余表（homework/notices/fitrecs/marks）不动。
3. **小程序**（`mp-class-tools/utils/cloud.js`，仅源码，尚未发布）：`visitLog()` / `fbSend()`
   的 `headers(true)` → `headers(false)`（+2 字节，其余 0 改动）。小程序下次发版带上即不再依赖第 1 步的放宽。

### 27.3 验证

- 新增网页回归 `tools/tests/stats_check.py`（假身份 + fetch mock，不碰真实云、不写库）：**30/30 PASS**——
  埋点/反馈 POST 无 `return=representation`、带 `X-Device-Id`、body 身份正确；管理员统计页今天/近 7 天
  聚合、按姓名、不含学号；0 JS 报错、无外部请求；截图 `tools/tests/_shots_stats/stats_admin_430.png`。
- 线上 E2E（headless Edge + CDP，普通成员身份）：`POST /rest/visits` **201**（修复前 401），
  DB 出现该 sid 当前小时行；管理员统计页出现 2 个账号（陈子麒 / 李学盈）、无学号；
  截图 `tools/tests/_shots_stats/live_stats_admin_430.png`。
- 云端策略直连探测（临时脚本，已删）：8/8——非管理员 INSERT+representation 201、只读本人行、
  不能伪造他人 sid（仍 401）、管理员可见多人、feedback 同样通过。
- 回归：`export_check.py draw` 正常落盘；`roster_check.py 199/199`、`overflow_check.py 430=0`
  见 §27.6 独立验收。
- 数据清理：探测/E2E 产生的测试行（did=`probedid0001`/`probe_prefer`/`rlsverify`/`f05b…`）与测试反馈已删。
- **历史数据补不回**：修复前其他同学的访问从未入库；统计从本次修复后开始有数据。

### 27.4 上线与回滚

- 线上 `index.html` **353,460 B · sha256 `7a7628b1ffb16f32febf69f4f822993831f6a84dbb71d64c4d12a6cdfdf7b9c5`**
  （与本地逐字节一致；与 §26 性能优化共存——本修复落在 353,460 最终字节里，§26 已对该字节复跑
  perf_check/reset_check 全绿）。
- 回滚：`tools/_backup/index_online_20261104-2326_preStatsFix.html`（353,042 B，修复前线上字节；
  重传会同时回滚 §26 性能优化，需谨慎）；云端回滚 SQL 见迁移文件末尾注释。

### 27.5 遗留 / 建议

- `fb_insert` 仍为 `auth_ok()`：任何已认证成员可写任意 `acc` 的反馈行（历史行为，非本次引入）。
  如需收紧可改 `auth_ok() AND acc = auth_acc()`，本次未改（网页/小程序两端口径都已是本人 sid）。
- 部署验证小工具 `tools/tests/verify_live.py`（线上 vs 本地逐字节 + 修复标记计数）可长期复用。
- 并发教训（与 §26 一致）：同一 `index.html` 另一个会话也在改时，部署前先取线上 raw bytes 比对；
  本次最终线上字节 = 双方改动并集，已确认本地=线上。

### 27.6 独立验收（另一 agent，fresh context，只读）

- **结论：产品侧全 PASS、0 FAIL、无需返工**；验收期间线上字节首尾两次一致（`7a7628b1…`），本地未变。
- A 线上字节：200 / 353,460 B / sha256 与本地逐字节一致；`cbPostNoRep` 恰 3 处（function @86144、
  feedback @224843、visits @320306），`cbPost("visits"` / `cbPost("feedback"` 0 处。
- B 云端 RLS：`vs_read` / `fb_read` 与迁移文件一致；写策略未放宽；`relrowsecurity=true`；无越权读策略。
- C 真实浏览器 E2E 26/26（自写 headless Edge + CDP，选 DB 内普通成员 3260707005 陈婉珺）：
  `POST /rest/visits` **201**（无 Prefer、DB 有当前 slot 行、`zq_visit_slot` 回填）；反馈 **201** +
  toast「已提交，谢谢」+ DB 行；管理员统计页渲染 2 个账号（陈子麒/陈婉珺）、全文不含学号；
  截图 `%TEMP%\verify_stats_shots\live_admin_stats_430.png`（430×932）。
- D 回归：`stats_check.py` **30/30**、`overflow_check.py 430` **0**、`roster_check.py` **199/199**（首跑全绿）。
- E 边界：非管理员读他人 visits/feedback → `[]`；伪造他人 sid 写入 → **401 DATABASE_42501**、DB 无伪造行。
- 测试数据已由验收者自清（visits 5 行 / feedback 2 行 / session 6 行，复查 0）。
- 剩余风险（已记录）：生产 `visits` 中管理员今日 38 行含历史自动化测试痕迹（10 个不同小时；
  本次测试产生的行已按 did 删除，其余无法安全区分，未动）；小程序源码修复未发版；
  统计按 slot 小时去重依赖前端 localStorage（换浏览器/无痕会重复计数，既有设计）。

---

## 28. 修复「班委名单一直加载不出来」（2026-11-04 23:57，已上线）

- **现象**（旅行者）：手机网页班委名单一直停在「加载中…」。
- **触发条件**：本机已有班级名单缓存（`D.d.members` 持久化在 `zq_tools_v2_<sid>`）且
  `zq_synced_at_<sid>.members` 在 6h 内 → `membersPull()` TTL 命中直接返回，不发请求。
  **冷启动 / 无缓存**（TTL 未命中 → 网络拉取 → `membersApply()`）不会触发，所以 QA 的
  冷启动/缓存回放用例都没暴露，只有「日常回访」路径必现。
- **根因**：§26 给 `membersPull()` 加 TTL 门控时，`renderCommittee()` 的唯一调用点原本在
  `membersApply()`（拉取成功后）里；TTL 短路后不再有调用点，而 `refreshAll()` / `gotoTab()`
  都没有渲染班委页 → 每次加载都是新 DOM，`#cmOut` 停在初始「加载中…」。
- **修复**（`tools/index.html`）：
  - `refreshAll()` 末尾加 `renderCommittee()`（首屏从本机 `D.d.members` 渲染）；
  - `gotoTab()` 加 `if(k==="committee") renderCommittee();`；
  - `membersPull()` 的 TTL 命中分支补 `renderCommittee()`（防御性，避免未来再出现同类短路）；
  - 启动流程解耦 IndexedDB：`startClassData()` 里 `bootRefresh()` **立即执行**，`bootCache()`
    改为异步补水（`then` 里清 `NT.loading` + `renderNoticeFrame`），不再用
    `bootCache().then(bootRefresh)` 串行——手机 WebView 的 IDB 回调不返回/被策略拦截时，
    名单、课表、统计、访问记录等初始化不再被卡住。
- **回归测试**：新增 `tools/tests/committee_check.py`（headless Edge + `--virtual-time-budget 9000` +
  `--dump-dom`，**不需要 CDP**；`CM_SRC` 可复盘任意副本）：
  - A. 缓存命中 + 全断网：班委页必须渲染 3 个角色行、不出现「加载中」；
  - B. 冷启动 + mock `class_members`：同样必须渲染；
  - 每场景 7 项（身份进入 / 切页 / 行数 / 文案 / 姓名 / 0 JS 错 / 0 console.error），**14/14 PASS**。
  - 修复前后对比：修复前 A 场景 3 项 FAIL（`rows=0 text=加载中…`），B 场景 PASS——精准复现用户症状。
- **回归**：`perf_check.py` 123/123、`reset_check.py` 109/109、`roster_check.py` 199/199、
  `overflow_check.py 430` overflow=0、`export_check.py draw` 正常。
- **上线**：线上 `index.html` **353,799 B · sha256 `ecaabee7a4a9cbf6…`**；对线上字节复跑
  committee 14/14 + reset 109/109 + perf 123/123。回滚：
  `tools/_backup/index_online_20261104-2357_preCommitteeFix.html`（353,460 B，修复前线上字节）。
- **以后改 TTL/缓存短路的检查清单**：① 该函数是否还有「渲染/副作用」？短路分支要自己触发；
  ② 渲染不能只挂在网络成功回调里，`refreshAll()`（首屏）与 `gotoTab()`（切页）要有兜底；
  ③ 新加 tab/数据时，测试至少覆盖「缓存命中 + 网络不可用」这条路径。

---

## 29. 用户数据跨端同步 v6 + 通知已处理（2026-11-05 08:2x，已上线）

> 需求（旅行者）：「一次微信小程序的数据和隐私模块，同时将同步范围扩大为所有用户更改的内容，
> 包括通知标记完成等，并确保网页端和微信端同步数据能互通。」
> 小程序侧见 `mp-class-tools/README.md`「三·补二、数据与隐私与同步 v6（1.4.6）」。
> 云端契约见 `CLOUDBASE.md`「用户数据同步 v6 与通知已处理」。

### 29.1 契约（两端逐字节一致，改动前先改契约）

- **marks**：新增 `kind='ntdone'`（ref=自动通知组 id），行 `id=<sid>|kind|ref`、`seat=sid`、`val=true/false`；
  upsert 写入（`Prefer: return=representation,resolution=merge-duplicates`），取消写 `val=false`（RLS 无 DELETE）；
  读取 `GET marks?select=*&seat=eq.<sid>`。网页头 `X-Device-Id`、小程序头 `X-Class-Token`，服务端 `auth_hdr()` 都认。
- **userdata blob v6**：单行 `{id:sid, blob:JSON, ts}`；blob = `{v:6, at:{homeTools,fit,draw,group,roster,hide,tt,prefs,nick}, homeTools, fit, draw, group, roster, hide, tt, prefs, nick, homeToolsAt}`。
  合并：逐 section 比较 `at`，`remote.at >= local.at` 云端赢（同 at 幂等收敛）；缺字段用默认值；v5 迁移为
  `{homeTools, fit, at:{homeTools:homeToolsAt, fit:0}}`；**未拥有的 section 原样保留**（web 不写 `prefs`；
  mp 不写 `nick` 与 `tt` 除 `termStart` 外字段）。
- 拉取 TTL 60s；推送脏 section 防抖 1200ms（显式操作可 force）；离线 pending；应用远端不重置进行中的抽签/分组结果。
- 清除：RLS 无 DELETE → userdata 覆盖空 v6 + marks 置 false + fitrecs `arch`；`visits/feedback` 无法删（小程序隐私页如实说明）。

### 29.2 网页实现位置（`tools/index.html`）

| 功能 | 位置（终稿行号） |
| --- | --- |
| UD v6 模块（merge/pull/push/touch/apply/off、缓存键、v5 迁移） | ~L1655-1933 |
| `D.save()` 脏检测钩子（防抖 1200ms） | L1130 |
| boot idle 拉取 / `cloudPull` TTL 60s / 退出身份 `cacheKill` | L4761 / L2421 / L2030 |
| marks `ntdone` 应用 + 旧 localStorage 迁移 | L1615 / L1342、L1380、L4731 |
| `NT.done` + iframe `__zqApplyDone` + capture 点击 + 父页 message | L1548 / L1436-1467 / L1531 |
| 旧卡片入口（避免遗漏） | L3985 |
| 用户可见文案 | L1003、L1007-1009、L1024、L3703 |

### 29.3 验收与上线

- 新增 `tools/tests/sync_check.py`（headless Edge + fetch mock，**夹具内嵌**，不依赖 `_sync_task`）**117/117 PASS**。
- 回归：`perf_check` 123/123、`reset_check` 109/109、`roster_check` 199/199、`overflow_check 430` 0、
  `export_check draw`、`committee_check` 14/14；以上本地 + 对**线上字节**各跑一遍。
- 线上最终字节：**374,183 B · sha256 `b0bbd71023b53327…`**（含 `UD.rebaseline('tt')` 与**远端 v5→v6 自动写回**
  两处加固）；回滚：
  `tools/_backup/index_online_20261105-0752_preSync.html`（353,799 B · `ecaabee7…`，本次全部改动前基线），
  中间版 `..._0810_preTtRebaseline.html`（372,607 B · `ba07b435…`）、`..._0823_preV5Writeback.html`（373,691 B · `eeb5e348…`）。
- 真实生产互通由独立验收（QA）用小号/管理员身份 + automator + headless Edge 交叉验证（见 `_sync_task/qa/REPORT.md`，
  临时过程目录，结论已并入本文件与 CHANGELOG）。

### 29.4 已知风险 / 后续

1. 管理员「教务课表自动同步」会改 `ttUseMine`：自动采用路径已排除出 UD 脏检测（`UD.rebaseline('tt')`），
   用户手动切换视图/导入自定义课表仍正常同步。
2. `sync_check.py` 依赖真实 DOM 选择器（`#ugBody`、工具 tab 等），后续改版注意同步维护；
3. userdata 合并只有「按 section 的 last-write-wins」，同一 section 两设备同时改会以时间戳大者为准（记录为已知限制）。
4. 新增同步类别时：先改契约 → 两端同时加 section/字段 → 更新 `_sync_task/fixtures` 的 3 份期望（或直接内嵌到
   两端测试）→ 两端 merge 必须逐字节一致 → 再改 UI/测试。



---

## 30. 导出图片 v2「清爽分享卡」（2026-11-05，网页已上线 / 小程序待发版）

### 30.1 用户要求

2026-11-05 旅行者：「优化网站和微信所有导出图片的显示效果」。
目标：网页 6 类导出（抽签 / 分组 / 结果单 / 课表 / 作业 / 体测）与小程序 6 类导出（draw / group / sum / hw / tt / ft）
统一升级为更清爽、可分享的图片，同时**不破坏**既有硬约束（参数配置区、斜向水印、生成时间、唯一编号、文件名规则、隐私）。

### 30.2 设计（规格文档 `tools/tests/export_card_v2_spec.md`）

- 画布 760 逻辑宽 / DPR2（成图 1520 宽，高度自适应）；底色垂直渐变，主卡内缩 22 / 圆角 22 / 1px 描边 / 柔和投影。
- 头部：左上 4×40 渐变装饰条 + 三色圆点（primary / primary2 / sand）+ 品牌；标题 30px/800（超宽降号再截断）；
  副标题 13px/500；分隔线。
- 参数配置：tinted 面板；按实测宽度自动两列（306×2）或单列（单列标签列宽自适应 110–186，长标签不硬折行）。
- 内容块三种：`{label,lines[,mono]}`（旧文本块全兼容，含 dim/strong/glue run）、
  `{label,chips:[{n,nm}]}`（抽签结果胶囊）、`{label,groups:[[{n,nm}],...]}`（分组两列组卡，组头「第 N 组 / N 人」）。
- 二维码（仅网页抽签剔除重抽）：所有内容块之后通栏面板：标题「剔除重抽记录」+ `qrNote` 前 3 条文字明细 +
  底部扫码说明 + 右侧白底板二维码。
- 页脚：分隔线 + 生成时间 + 编号（左）+ 三色点品牌（右对齐）。
- 水印：`clip()` 到主卡圆角路径后斜向平铺（alpha 0.03、700 15px、-20°、300×140），卡片外不再出现半截字。
- 文字换行：`wrap()` 增加行首标点禁则（，。、；：！？）】」 等不单独起行；配置值 / 长文本共用。

两端仅允许三处差异：平台色板、品牌文字（`tool.furina.fun` / `班级工具站`）、小程序无二维码块。

### 30.3 网页改动（`tools/index.html`）

| 位置 | 改动 |
|------|------|
| L2630 `wrap()` | 加行首标点禁则 |
| L2738 `var EXPC` / L2750 `exportCard(o)` | v2 版式实现（调色板、头部、参数面板、chips/groups/text、二维码、页脚、水印） |
| L3321 `#aImg` | 抽签导出改 chips + `qrNote`（剔除明细文字） |
| L3402 `#gImg` | 分组导出改 `{label:"分组结果", groups:[...]}` |
| L3420 `sumData()` | 新增 `xblocks`（chips + groups），页面展示用的旧 `blocks` 保留 |
| L3456 `#sImg` | 结果单改用 `s.xblocks` |
| `tools/tests/export_check.py` | 新增 `drawqr` 变体、`EXPORT_SRC`/`EXPORT_OUT` 环境变量（复盘任意副本/回滚版） |

课表 / 作业 / 体测导出入口未改（文本块由新 renderer 自动适配）。

### 30.4 小程序改动（`mp-class-tools`，v22 / 1.5.1，详见其 README / CHANGELOG）

- `utils/canvas.js`：`drawCard()` 逐像素同版式（暖色板 + 「班级工具站」品牌、无二维码块）；对外 API / 导出常量不变。
- `pages/draw/draw.js`（rows→chips）、`pages/group/group.js`（groups→groups）、`pages/sum/sum.js`（items→chips/groups）；
  `pages/hw|tt|ft` 未改。
- `mp-class-tools-tests/unit.js`：假 canvas 补 `createLinearGradient/arc/clip/shadow*`，水印断言改 v2，
  新增两列/单列、chips、groups、高度自适应断言；`render_export.py` 用 Edge 无头渲染 `drawCard` 落盘供肉眼核查。

### 30.5 验收

- 网页：`export_check` 全部 6 类 + `drawqr` + 三个 roster 变体落盘；`sync_check 117/117`、`perf_check 123/123`、
  `reset_check 109/109`、`roster_check 199/199`、`committee_check 14/14`、`overflow_check.py 430` overflowCount=0。
  独立 QA（fresh context）**20/20 PASS、0 FAIL**：`tools/tests/_qa_export/QA_web_export_v2.md`
  （逐张肉眼 + canvas 调用级 + 像素级；回归 #sOut / 复制 / 导出按钮 / 5 tab；隐私正则零命中）。
- 小程序：`node unit.js` **108 passed / 0 failed**、`python staticcheck.py` exit 0；独立 QA **24/24 PASS、0 FAIL**：
  `mp-class-tools-tests/_qa_export/QA_mp_export_v2.md`（6 类官方渲染 + 5 边界；与网页参考图 H/锚点逐项一致）。
- 上线：线上 `index.html` **385,138 B · sha256 `b30fbf91eba714cb…1fedbc`**，与本地逐字节 MATCH；
  回滚：`tools/_backup/index_online_20261105-1405_preExportV2.html`（374,183 B · `b0bbd710…`）。
- 回滚版可复盘：`set EXPORT_SRC=...\index_online_20261105-1405_preExportV2.html` + `EXPORT_OUT=...` 跑 `export_check`。

### 30.6 已知风险 / 后续

1. 小程序只做了 Edge 无头 + 假 canvas 验证，**真机 Canvas 2D**（shadow / clip / linearGradient / 字重 600–800）
   需在发版前用微信开发者工具真机复核一次 draw/group 导出。
2. 低端 Android 对数字字重 600/800 可能回退默认粗细（不破版，仅观感差异）。
3. 结果单文件名仍无 `_关键参数` 段（历史行为）；超长单行文本折行按字符贪心，断点可能不完美（已加标点禁则）。
4. 二维码块左侧在明细条数很少时留白偏多（抽签无剔除时不出现该块）；如需更紧凑可把明细改为两列。

---

## 31. **v2.0.0 全班体验升级**（2026-11-05 19:45 网页已上线 / 小程序源码待上传）

> 用户 16 条需求整体交付。完整逐项说明见 `CHANGELOG.md` 顶部 v2.0.0 段（本文件只记交接要点与坑）。
> 规划/契约过程文件 `_v2_plan.md` 已按交付规则删除；可复现证据在 `tools/tests/v2_*.py`、`tools/tests/_qa_v2/`、`mp-class-tools-tests/`。

### 31.1 关键设计（改动前先读，避免回退）

1. **版本号**：全站 2.0.0，唯一来源——网页 `index.html` 的 `var APP_VER="2.0.0"`；小程序 `utils/version.js` 的 `VERSION`。
   用户要求「直到下一次成功上传发布」都不改版本号。
2. **通知页架构（需求 4，重要）**：网页通知 tab 不再是「固定视口 iframe 内部滚动」，而是
   **父页滚动 + iframe 自适应内容高度**：
   - 模板由 `briefdesk-plan/build_notice_board.py` 生成，`web/tools/build_notice_embed.py` 注入
     `__noticeHeight()`（按 `.wrap` 实际高度 + body 留白测量，**不要用 `documentElement.scrollHeight`**，
     否则 iframe 视口高会反噬成只增不减的棘轮）并经 `class-notice-height` 发父页；
   - 父页 `noticeSetHeight()` 设 iframe 高度；`noticePerfPatch()` 注入 iframe 触摸适配：
     纵向位移转父页滚动、横向位移转父页跟手/飞出切工具；模板内 `position:fixed` 的编辑/弹层在自适应高度下
     不可见，因此**管理员编辑表单在父页磨砂弹层渲染**；模板 toast 走 `class-notice-toast` 桥接父页。
   - 模板 `#modal` 仅独立打开 demo 时使用。
3. **刷新保位**：`sessionStorage zq_pos_v1`（按 sid/工具/滚动位置，退出身份清空）；首次访问仍落工具栏第一格；
   恢复最多等 6s（等通知 iframe 撑高）、用户 wheel/touch/按键立即取消。小程序 `utils/scrollmem.js` 同理。
4. **管理员编辑/删除（需求 12）**：云端 `public.notices` 4 列 `override_json text / hidden bool / edited_at bigint / edited_by text`
   （迁移 `deploy/cloudbase/2026-11-05_notice_admin_override.sql` 已应用；幂等）。
   - 采集端 `sync_notices_cloud.py` 只 PATCH id/title/body/audience/archived/ts，**不得写这 4 列**；
   - 前端套用 override、过滤 hidden（管理员可「已隐藏」恢复）；rowid = `auto_` + 通知组 id；
   - 通知轻量签名必须 `select=id,ts,hidden,edited_at`（只 id,ts 会永远命中旧缓存）；
   - PATCH 用 `Prefer: return=representation` 在管理员 token 下实测 200（nt_read 有 admin 旁路）。
5. **用户状态同步（需求 14/16）**：`public.marks` 仍是唯一真源（`ntdone` / `hw`），userdata v6 `fit` section 含 `sex/grade`；
   本机「待补发 overlay」防止云端旧状态冲掉刚点的勾选；回前台/切页/刷新强制拉一次 marks（5s 防抖）。
   小程序 `pages/fttable` 的男女/年级选择必须写回 `store.fit` + `store.save()` 才参与同步（本次补的缺口）。
6. **长期安排（需求 9）**：通知 JSON 新增 `recurrence`（freq/weekday(JS getDay 0=周日)/weeks/time/startAt/label）；
   两端本地计算「下次」；`actionable=false` 不计待处理、不按 deadline 判过期。样例 `g_dorm`（每月前三周周三 17:30）。
7. **QQ 文件（需求 7）**：file item 无 `url` = 待获取；两端点击提示「前往 QQ 群『群名』查看，下载后自动上线」；
   本机 `fetch_qq_files.py --import-only` 扫 Downloads/QQ/微信目录 + watcher `data/qq-files` 目录签名触发重建；
   `qq_file_uri` 单文件上限 1.5MB（内嵌 base64 进 notices.body）。
8. **小程序审核相关（需求 10，2026-11-05 20:25 已收敛）**：**不实现演示/审核模式**（demo 代码/入口/文案已全部删除）；
   审核只靠云端测试身份（`private.class_ids.is_test=true`，`class_members` 过滤、不在班级名单显示），凭据只在交付说明；
   除“添加账号”外不加入任何审核相关功能。详见 §32。
   **AI 开发模式发版默认关闭**（`ai_toggle.py --off`，app.json 无 agent/subPackages；`ai/` 源码保留，`--on` 恢复）。

### 31.2 验收（最终字节复跑）

- 网页既有门禁 7/7：roster 199、reset 109、perf 123、sync 117、committee 14、overflow 430=0、export ok。
- 网页 v2 专项 7/7：v2_scroll 35、v2_admin 39、v2_sync 35、v2_ui 27、v2_notice_data 27、v2_notice_live 16、
  v2_pos_restore 10（真实 40 卡 20,000px 通知页冷启动弱网恢复）。
- 小程序：unit 152/152、sync_contract 29/29、staticcheck exit 0、v2_preview 18/18、tt_swipe automator 16/16、
  AI 三件套（off 前）全绿；`cli auto-preview` TOTAL 682,809 B（AI off 单主包）。
- 独立 QA 报告：`tools/tests/_qa_v2/REPORT.md`、`mp-class-tools-tests/_qa_v2/REPORT.md`。

### 31.3 上线与回滚

- 线上 `index.html`：**448,812 B · sha256 `2253e5e4dcdd38b7a9254bacf44d6ead6b80120cdf6dbe84588ac38be4eac3ff`**（本地=线上 MATCH）。
- 部署前线上备份：`tools/_backup/index_online_20261105-1925_preV2.html`（385,138 B · `b30fbf91…`）。
- 中间回滚点（父页改动、旧模板）：`tools/_backup/index_local_20261105_v2_preEmbed.html`（412,546 B）。
- 云数据无需回滚（4 新列对旧前端无影响；旧签名 `select=id,ts` 兼容）；云端回滚 SQL 见迁移文件末尾。
- briefdesk watcher 已恢复（`watchdog.pause` 已删、detect_docs 运行）；数据备份 `C:\briefdesk\data\_backup_v2_20261105\`。

### 31.4 已知风险 / 后续

1. 微信/QQ WebView 真机未自动验证「父页滚动」；上线后建议人工在微信内置浏览器滑一次通知页（QA 已用 headless 等价标准 + 真机 automator 部分覆盖）。
2. 通知页 40 卡 ~20,000px，DOM 全量渲染（与旧版 iframe 全量渲染等价）；低端机首屏仍建议靠缓存/签名优化，不要盲目加动画。
3. 小程序通知超长卡片展开/收起用 max-height(4000rpx) 过渡，收起首帧可能略跳；真机 Canvas 2D 导出/订阅消息模板发版前复核。
4. `build_groups()` 的示例 xlsx 附件每次重建字节不同（openpyxl 时间戳），board-data 里 3 个示例附件 src 每次重建会变（不影响语义/AI 缓存）。
5. 演示模式已于 2026-11-05 20:25 按用户要求整体移除；审核只保留云端测试身份（`is_test`，不在班级名单显示），详见 §32。

---

## 32. v2.0.0 增量：网页滑动手感修复 + 审核相关功能收敛（2026-11-05 20:25，网页已上线）

> 用户 20:07 反馈：「网页滑动现在有阻滞感，不够跟手且出现了一些抽动」；
> 「除添加账号外不要再有其他审核相关功能加入」。本节覆盖 §31 中已过时的演示模式描述。

### 32.1 网页滑动手感（已部署）

- **根因**：§31 引入的三处热路径改动叠加——①`touchmove` 改为「记录位移 + rAF 合并写 transform」，
  rAF 在移动 WebView/主线程忙时延迟一帧以上 → 不跟手/抽动；②`touchstart` 无条件 `geoInit()` 强制布局；
  ③刷新保位的 `POS.saveSoon` 在滚动中 rAF + 每 160ms 同步写 `sessionStorage` → 周期性微顿。
- **实测指标**（`tools/tests/v2_swipe_perf.py`，CDP 合成 12 次 touchmove；baseline=pre-v2 备份）：
  | 指标 | baseline | v2 修复前 | 修复后 |
  |---|---|---|---|
  | reactionRate（transform 与手势位移同步命中率） | 1 | **0** | 1 |
  | syncErrP50/P95（transform 落后 px） | 0/0 | **20/20** | 0/0 |
  | 滚动期间 sessionStorage 写入 | 0 | **10** | 0（停止后 1 次） |
- **修法**：①touchmove 同步直写 `transform`（恢复 v2 前手感），`transition:none` 只在手势首次锁定时设；
  ②`geoEnsure()` 复用工具栏几何缓存（isConnected/宽度校验）；③`POS.saveSoon` 改为滚动停止 480ms 后单次落盘，
  滚动中不写同步存储，切 tab/退出身份/pagehide/visibilitychange 仍立即写；④通知 iframe 手势预览同步跟手。
- **约束（以后不要回退）**：全局滑动跟手路径不要再用 rAF 合并写 transform；滚动事件里不要同步写 `sessionStorage`；
  `touchstart` 不要无条件读布局。
- **上线**：`index.html` **449,446 B · sha256 `701fd0f8cd31af4be5b6a86f909e09c24f01e8ee74904dc073e06fef8fba3668`**（本地=线上 MATCH）。
  回滚：`tools/_backup/index_online_20261105-2016_v2final.html`（448,812 B · `2253e5e4…`，修复前 v2.0.0）；
  更早 `tools/_backup/index_online_20261105-1925_preV2.html`（385,138 B · `b30fbf91…`）。
- 新增回归：`v2_swipe_perf.py`（PASS，三档指标）；全量既有 7 门禁 + v2 7 专项 + pos 10 全绿；QA 独立复跑一致。

### 32.2 小程序审核相关收敛（源码待上传）

- **不实现演示/审核模式**（用户要求）：已删除 `utils/demo.js`、`utils/demo-data.js`、身份页「演示模式（审核用）」入口、
  「我的」页演示提示/退出、`cloud.js` demo 拦截、`notify.js` demo 守卫、store demo 桶、demo 单测/截图；
  README/CHANGELOG 已清理并写明不实现审核模式。源码 grep「demo/演示/审核用/审核员」= 0 真实命中。
- **唯一审核能力 = 云端测试身份**（`web/deploy/cloudbase/2026-11-05_test_account.sql` 已应用）：
  - `private.class_ids` 新增 `is_test boolean default false`；测试行：seat 999 / 姓名「测试账号」/ 学号 `3260799999` / 非管理员；
  - `public.class_members()` 已过滤 `is_test` → 班级名单仍 70 人、名单选择器/统计不出现测试身份；
  - 审核员用正常身份页「学号+姓名」登录；凭据只在交付说明（不入仓库/文档）；
  - 审核结束回收：`delete from private.class_sessions where sid='3260799999'; delete from private.class_ids where sid='3260799999' and is_test=true;`
    （SQL 文件末尾有完整回滚注释）。
- 回归：unit **147/147**、sync_contract **29/29**、staticcheck exit 0、cache_perf 16/16、`cli auto-preview` 通过；
  最终包体 **667,382 B 单主包**（移除 demo 前 682,809 B）；版本仍 **2.0.0**；AI 开发模式仍 off（`ai/` 源码保留）。
- QA 增量验收：源码 demo/审核模式 0 处；测试身份 7/7 PASS；页面/入口均无审核相关 UI。

### 32.3 以后改动的检查清单

1. 任何跟手动画：touchmove 内同步写，别用 rAF 攒帧；不要每帧改 `transition`。
2. 滚动/滑动期间禁止同步 `sessionStorage.setItem`；用停止防抖 + pagehide。
3. 审核相关：不要再加演示模式/审核入口/试用开关；需要账号就在云端名单加 `is_test` 测试身份（凭据不入仓库）。

---

## 33. v2.0.0 增量 2：微信内滑动二次修复（2026-11-05 21:27，网页已上线）

> 用户二次反馈（手机微信内置浏览器，已清缓存）：左右切换工具/页面仍抽搐、**慢速更明显**；通知页里上下滚动抽搐。
> 本节是**滑动/通知页架构的最终定稿**，覆盖 §32.1 中关于通知页的旧约束。

### 33.1 量测结论（CDP 合成 touch，修复前线上 449,446）

| 现象 | 实测 |
|---|---|
| 慢速横滑 4px/步 | 首个跟手位移 **12px**（前 1–2 步空走，过阈值后突跳） |
| 通知 iframe 内慢速横滑 | **12px**（适配层 10px + 全局 12px 双死区） |
| 通知页纵向拖动 | iframe scrollY **恒 0**；`parent.scrollBy` 调 **19 次**、父页滚 90px → 每帧滚一个 20,000px iframe 层 |

### 33.2 最终架构（不要回退）

1. **通知页 = 固定视口 iframe + iframe 内部原生滚动**：手机 `calc(100vh-140px)` / 桌面 `calc(100vh-150px)`，`scrolling="yes"`；
   父页不随通知内容滚动；`class-notice-height` 父页忽略（模板内保留空实现）。
   - 纵向手势**交还原生**：iframe 适配层不 `preventDefault`、不用 `parent.scrollBy`；
   - 仅当「纵向拖 2 帧后 iframe `scrollY` 仍无变化且内容可滚」才启用 JS `scrollBy` + 衰减惯性兜底；
   - 横向手势仍由适配层转父页滑动引擎（切工具/切页）。
2. **横向跟手**：全局锁定阈值 **4px**、比例 **1.2**；通知 iframe 适配死区 **4px**（不要恢复 10/12px 双阈值）；
   锁定后 `touchmove` **同步直写** transform；`transition:none` 只在手势首次锁定设一次；
   thumb 液体宽度脉动仅 ≥16px 位移启用。
3. **通知页刷新保位**：父页只恢复 tab；iframe 内滚动由注入脚本 `zq_nt_scroll_v1` 自存自恢
   （滚动停止 260ms 落盘；加载后 24×150ms 重试恢复，最多 ~3.6s）。
4. 模板 fixed 弹层/管理员编辑表单仍在**父页**渲染（不变）。
5. `.tabs{overflow:hidden}` + thumb 位置 clamp 必须保留（否则滑块回弹过冲会瞬时撑宽页面 6–10px）。

### 33.3 指标（`tools/tests/v2_swipe_perf.py`，pre-v2 / 修复前 / 本次）

| 指标 | pre-v2 | 修复前 | 本次 |
|---|---|---|---|
| 慢速 4px 首个跟手位移 | 12px | 12px | **4px** |
| 慢速锁定后跟手率 | 1.00 | 0 | **1.00** |
| 通知 iframe 内 4px 首个跟手 | — | 12px | **4px** |
| 通知页纵向 iframe scrollY | 161 | 0 | **161（原生）** |
| 通知页纵向 parent scrollY | 0 | 90 | **0** |
| 通知页纵向 JS scrollBy | 0 | 19 | **0** |
| step reaction / syncErr | 1 / 0px | 0 / 20px | **1 / 0px** |
| 滚动中 POS 写入 | 0 | 10 | **0**（停止后 1） |

### 33.4 测试与上线

- 既有 7 门禁全绿；v2 8 条全绿（scroll 40/40 已按新架构重写、pos_restore 12/12、notice_live 16/16、admin 39、sync 35、ui 27、notice_data 27、swipe_perf PASS）。
- 线上 `index.html`：**452,250 B · sha256 `5b5bb6c333a56edfa9d0a237ba1d0f5a914dc7bd1949ec09c7d659b8747bffd0`**（本地=线上 MATCH）。
- 回滚：`tools/_backup/index_online_20261105-2127_preWeChatFix.html`（449,446 B · `701fd0f8…`）；
  更早 `index_online_20261105-2016_v2final.html`（448,812 B · `2253e5e4…`）。

### 33.5 真机风险 / 后续

- headless 已验证 iframe 原生滚动路径；微信 WebView 若个别机型仍滚不动，会自动走「2 帧后 JS scrollBy + 衰减惯性」兜底
  （如用户仍反馈纵向卡，可把兜底判定从 2 帧提前到 1 帧/提高灵敏度，但**不要**改回父页滚动 20k iframe）。
- 横向 4px 较敏感（用 1.2 比例防纵向误判）；若用户反馈误切工具可回调到 5px。
- 通知 iframe 高度 `100vh` 随微信地址栏收起/展开变化，属 pre-v2 既有行为。
- 通知页 iframe 内滚动恢复最多重试 ~3.6s；内容极慢加载时可能恢复不到位（可再增大重试次数）。

---

## 34. v2.0.0 增量 3：通知页横向“重影”修复（2026-11-05 22:00，网页已上线）

> 用户（手机微信）反馈：上下滚动已正常，但**左右滑动仍有重影等动画异常**；确认**只在通知页**、且**手指拖动跟手时就出现**。
> 本节是 X5 合成残影的最终处理，滑动/通知页架构以 §33 + 本节为准。

### 34.1 根因

微信 X5/WebView 对「含 iframe 的整块 section 做 transform」会出现合成残影（iframe 是独立 surface，位移时旧帧残留）；
`fly()` 对大面积子树同时动画 `opacity + transform` 会放大 alpha 合层残影。

### 34.2 最终做法（不要回退）

1. **通知页左右滑不做任何 section/iframe 位移**：拖动只驱动 toolbar thumb；`snap()` 对通知页直接清零不写 transform；
   松手走 `directSwitch()` 直接切 tab（thumb 弹性过去 → `gotoTab` → 清理），**不走 `fly()`**；保留 320ms 点击抑制；
   **进入通知页同样直接切**（避免 incoming iframe 被位移）。
2. **其它工具页**保留跟手 + fly，但 `fly()`：
   - 只动 `transform: translate3d(...)`，**不写 opacity**；
   - 动画期间 `<body>` 加 `zq-flying` 临时禁用 `section.on/.stpane.on` 的 `fade`；
   - 结束清理内联 transform / will-change / 类。
3. toolbar thumb 统一 `translate3d`。
4. **不要**对含 iframe 的通知 section 做 transform；**不要**给大面积子树同时动画 opacity+transform（X5 残影风险）。
5. 若真机仍有极轻微残影，下一档可选：拖动/切换通知页时临时隐藏 iframe 或给容器 `contain: paint`（本轮未做，避免影响滚动与弹层）。

### 34.3 测试与上线

- 新增 `tools/tests/v2_x5_anim_check.py` **24/24 PASS**（静态 8 + 行为 16）：
  通知页拖动 13 采样点 section 无 transform、iframe rect 全程不变、thumb 跟手、preventDefault=12；
  松手 nt→all、切后无 transform、320ms 点击抑制后恢复；非通知页 fly 20 次 translate3d、0 次 opacity 内联、`zq-flying` 临时存在、结束清理干净。
- 手感指标不退化：4px 慢速首个跟手=4px、step reaction=1/syncErr=0、通知纵向 iframe 原生 161px（父页 0、JS scrollBy 0）、滚动中 POS 写入 0。
- 回归：既有 7 门禁 + v2 9 条（scroll40/admin39/sync35/ui27/notice_data27/notice_live16/pos_restore12/swipe_perf PASS/x5_anim 24）全绿。
- 线上 `index.html`：**453,951 B · sha256 `186651f292afe28292f9ae91d522e0c2657cb033ed044d7903ba21aa70219f82`**（本地=线上 MATCH）。
- 回滚：`tools/_backup/index_online_20261105-2200_preX5Anim.html`（452,250 B · `5b5bb6c3…`）；
  更早：`index_online_20261105-2127_preWeChatFix.html`（449,446 B · `701fd0f8…`）。

### 34.4 观感变化（按用户范围约定）

通知页左右滑时**内容不再位移**（只 thumb 跟手、松手直接切）；其它工具页保持原跟手 + fly；fly 不再淡入淡出（纯位移）。
若用户仍觉得通知页左右滑“没动画”，可考虑加一个非合成的轻提示（不要用 iframe transform/opacity）。

---

## 35. 管理员「诊断」页 + 关机重启韧性（2026-11-05，网页已上线）

> 用户需求：「确保班级工具站的信息获取等功能即使关机重启后也能正常使用，同时为我在班级工具站内部新增一个仅管理员可见工具，显示各个依赖服务是否正常」。
> 契约唯一真源：`tools/tests/health_monitor_spec.md`；云端表与运维：`CLOUDBASE.md` 的「依赖服务健康表」节。

### 35.1 依赖服务清单（13 项，全部展示在诊断页）

| id | 显示名 | kind | 判定来源 |
|---|---|---|---|
| `cloudbase` | 云端数据库 | cloud | 浏览器实时探测（读 service_health 的延迟）+ 采集主机上报 |
| `site_static` | 站点资源 | static | 浏览器同源 fetch `tt.json` 的延迟 + 采集主机上报 |
| `site_tls` | 站点证书 | static | 采集主机 TLS 握手 + 证书剩余天数（>21 天 ok / 8–21 warn / ≤7 down） |
| `collector_host` | 采集主机 | local | 心跳新鲜度（>15 分钟未更新 → 所有 local 行降级「离线」）+ 开机时长 |
| `qqflow` | QQ 消息采集 | local | `:5032/health` + `/api/v1/accounts` 有 `state=ready` 账号 |
| `weflow` | 微信消息采集 | local | `:5033/health` + ready 账号 |
| `briefdesk` | 本地通知服务 | local | `:3000/api/status` HTTP 200 |
| `watcher` | 文档/通知监听 | local | `detect_docs.py --watch` 进程 + `docs-detect.log` 新鲜度（≤300s ok） |
| `ai` | AI 识别 | local | `logs/ai-cloud.log` 最近 error 是否晚于最近 `cloud ok` |
| `jwxt` | 教务课表同步 | local | `tools/tt.json` 的 `meta.fetchedAt` 年龄（≤30h ok / 30–54h warn / >54h down） |
| `hwauto` | 作业自动整理 | local | `logs/hw-auto.log` 新鲜度（≤3h ok / 3–8h warn / >8h down） |
| `qq_client` | QQ 客户端 | local | `QQ.exe` 进程存在（消息源） |
| `wechat_client` | 微信客户端 | local | `Weixin.exe` 进程存在（消息源） |

状态：`ok` 正常 / `warn` 注意 / `down` 异常 / `unknown` 未知；前端另派生 `offline`（心跳过期）显示「离线」灰态。

### 35.2 采集主机心跳（新）

- **`C:\briefdesk\scripts\health_beat.py`**（新建，纯标准库，1087 行）：检测 13 项 → 写云端
  `public.service_health`（逐行 PATCH，行不存在时 POST）；`--once` / `--dry-run`；管理员 token 从
  `C:\briefdesk\secrets\class-token.json` 读取（过期自动 `rpc/class_verify` 刷新），**不打印 token**；
  日志 `C:\briefdesk\logs\health-beat.log`；任何异常只记日志、不抛出。
- **`C:\briefdesk\scripts\watchdog.py`**（只新增 3 处）：每轮结束调用 `publish_from_watchdog()`；
  `watchdog.pause` 存在时上报 `collector_host=warn`（「采集已暂停」）；均 try/except，不影响退出码与
  现有守护/重试/账号自愈逻辑。心跳每 5 分钟自动跑（计划任务 Briefdesk Watchdog），**重启后随登录自动恢复**。
- 云端表 `public.service_health`：8 列（id/name/kind/status/detail/meta/checked_at/updated_at），
  RLS 三条策略均 `TO anon` + `auth_admin()` → **仅管理员可读写**，匿名/普通成员 SELECT 返回 `[]`，无 DELETE 策略。
  迁移：`deploy/cloudbase/2026-11-05_service_health.sql`（已应用）。

### 35.3 前端实现位置（`tools/index.html`，单文件内）

| 区块 | 位置（2026-11-05 并集版行号） |
|---|---|
| CSS `.diag-*`（摘要/分组/行/状态点/胶囊/960px 两列） | 684–716 |
| DOM `<section id="s-diag">`（`#diagSum` + `#diagGrid`） | 1016–1020（`#s-stats` 之后、`#s-all` 之前） |
| `TOOLS` 追加 `{k:"diag",n:"诊断",d:…,admin:true}` | 2944 |
| `gotoTab` 管理员门禁通用化 + 诊断定时器 enter/leave + diag 分支 | 2951–2956、2976 |
| `DIAG` 模块（拉取/探测/合并/渲染/刷新/自动刷新/探针 `window.__diag`） | 5320–5535 |

- **门禁（三层）**：① `TOOLS` 的 `admin:true` + `toolShown()`（工具栏/全部页不出现）；
  ② `gotoTab` 对 `toolOf(k)` 统一判定（`all/fb/ug` 例外放行）；③ `DIAG.pull()` 内再判 `canManage()`，
  非管理员**不会发起任何 `service_health` 请求**。
- **数据合并**：`cloudbase`/`site_static` 以浏览器实时探测覆盖；`collector_host.checked_at` 距今 >15 分钟
  或无该行时，所有 `kind=local` 行显示「离线」灰态（detail 保留上次上报、行尾「上报于 HH:MM」）；
  云端请求失败时本会话无缓存 → local 行「未知」而不是误报离线；`jwxt` 在云端无行时用同源 tt.json 兜底。
- **交互**：摘要卡（状态点+概要+最后检测时间+刷新按钮，按钮 41px）；四组卡片；60s 自动刷新
  （页面隐藏/切走即暂停，恢复可见重启）；刷新防重复；无解释性长文，遵循 Monet 配色与 ≥960px 两列。

### 35.4 关机重启韧性（计划任务，2026-11-05 改）

| 任务 | 触发器 | 关键设置 | 动作 |
|---|---|---|---|
| `Briefdesk Watchdog`（原有，未改） | 每 5 分钟 + 登录后 1 分钟 | StartWhenAvailable、Hidden、IgnoreNew | `pythonw watchdog.py` → 拉起 qqflow/weflow/briefdesk/detect_docs + 账号自愈 + 心跳 |
| `Class Homework Auto`（改） | 每 2 小时 **+ 登录后 3 分钟**（新增） | StartWhenAvailable=true、电池不禁用、RestartOnFailure(PT10M×3) | `pythonw hw_auto/run_hw_auto.py` |
| `JwxtTimetableSync`（改） | 每日 07:00 **+ 登录后 2 分钟**（新增） | StartWhenAvailable=true、RestartOnFailure(PT10M×3) | `pythonw jwxt/sync.py --out tools/tt.json --term-start 2026-08-31 --deploy` |
| `Class Tools Clients`（新建） | 登录后 90 秒 | StartWhenAvailable、Hidden、IgnoreNew、无电池限制 | `pythonw C:\briefdesk\scripts\ensure_clients.py`（幂等：QQ/Weixin 未运行才静默拉起，消息源在线） |

- 全部任务改动前 XML 备份：`C:\briefdesk\data\_backup_taskxml_20261105\`。
- `C:\briefdesk\scripts\ensure_clients.py`（新建）：tasklist 检测 `QQ.exe`/`Weixin.exe`，缺失才经
  `run_hidden.start_hidden()` 无窗口启动；日志 `C:\briefdesk\logs\ensure-clients.log`；退出码恒 0。
- **限制（如实）**：任务用 `InteractiveToken`，**需要用户登录 Windows 后才运行**（关机重启后登录即恢复；
  未登录不跑）。QQ/微信若需重新扫码登录，诊断页会把 `qq_client`/`wechat_client` 显示为异常。

### 35.5 验收（2026-11-05）

- 后端：`service_health` 13 行全 ok、`checked_at` 新鲜；匿名/非管理员读 = `[]`，写入仅管理员；
  `health_beat --once` 幂等、`--dry-run` 不写库、日志无 token；kill qqflow → watchdog 隐藏重启 20.9s 恢复 ok；
  挂起等价故障 → 云端正确 down → resume 恢复；pause 文件 → `collector_host=warn`（「采集已暂停」）。
- 前端：本地 Edge headless —— 管理员「全部」页见「诊断」卡（管理角标）、打开渲染 13 行/4 组/摘要/刷新；
  非管理员无入口、`gotoTab("diag")` 无效、0 个 `service_health` 请求；360/390/430/1280 无横向溢出、0 JS 报错；
  断网/空表降级正常；60s 自动刷新与隐藏暂停正常。
- **独立 QA（qa-health）总计 227 项：201 PASS / 0 FAIL / 26 INFO（PASS）**，报告
  `tools/tests/_health_qa/REPORT.md` + `report.json`（RLS 21、心跳 20、故障注入 17、暂停 11、任务 42、
  本地 UI 57、**线上 20/20**、门禁 6/6）。
- 回归：`sync_check` 117/117、`perf_check` 123/123、`v2_ui_check` 27/27、`v2_admin_check` 39/39、
  `overflow_check` 430=0、`export_check draw` 正常（部署前 + 部署后对线上字节冻结副本各跑一遍，均全绿）。
- 任务：4 个计划任务 XML 触发器/设置/动作静态核验 + `Class Tools Clients` 实测 `/run` LastResult=0。

### 35.6 上线与回滚

- 2026-11-05 22:45 上线：`index.html` **468,856 B · sha256 `7a2704e0fc3df225a113f9e1e2a85709945eeed6211d6d7d508c58d11acfe1ad`**
  （本地=线上逐字节 MATCH；v2.0.0 版本号未改；部署后线上独立复验 20/20 PASS）。
- 回滚：把 `tools/_backup/index_online_20261105-2242_preDiag.html`（453,951 B · `186651f2…`）复制回
  `tools/index.html` 后 `python deploy/sync_tools.py index.html`。
- 注：上线期间另一并发会话正在改同一 `index.html`（先 flicker fix、后「电费」工具）。本次上线版是
  **flicker fix + 诊断页的并集**（相对 flicker 版仅 264 行 diag 新增 + 2 行预期替换，flicker 代码零删除，
  diff 证据 `C:\briefdesk\data\health_dev_evidence\`）。之后该会话在本地继续叠加「电费」工具
  （其版本仍含 `#s-diag`/`DIAG`/`TOOLS diag`，我们的安全副本 `C:\briefdesk\data\index_with_diag.html` = 7A2704）。
  **若其后续部署，线上字节会更新为「诊断 + 电费」并集**；诊断页验收记录以本次 7A2704 为准，
  上线后如需复核，直接看线上诊断页是否可打开即可（RLS/心跳与前端字节无关）。

### 35.7 已知限制 / 后续

1. `site_tls` 只按采集主机上报渲染（浏览器不探证书）；心跳过期时显示上次结果（spec 只要求 local 行降级）。
2. 采集主机关机/未登录时，诊断页会显示「采集主机离线」，local 行灰态 —— 属预期（云端数据仍可读）。
3. 管理员可把「诊断」拖到顶部工具栏（`renderTabs` 自动补位，与 stats 一致）；非管理员不会出现。
4. 心跳写入依赖采集主机的管理员 token（有效期 30 天，`health_beat` 会自动 `class_verify` 刷新；token 文件被删则
   `cloudbase`/local 行会显示心跳缺失，需重新生成 `C:\briefdesk\secrets\class-token.json`）。
5. `service_health` 无 DELETE 策略；如需清空由 tcb/管理员直接在库内 `delete`。

---

## 36. 宿舍电费（2026-11-05，网页已上线）

> 用户需求：「『全部』页加一张宿舍电费卡片，点开能选任一班级宿舍看剩余电量，低电标红」（方案 A：不改顶部 4 格布局）。
> 数据走 CloudBase（身份 token 才能读），不放公开静态文件。
>
> ⚠️ **2026-11-05 深夜 v2 已改版**（统一命名 + 单选关注下拉框 + 选择进同步）——本节 36.1/36.2/36.4 部分描述
> 已被 §37 覆盖（尤其「全部宿舍列表」「id=label」「楼栋 chips」）；数据链路/网关/计划任务部分仍有效。

### 36.1 数据链路（完美校园 · 免登录）

- 网关：`POST https://cloudpaygateway.59wanmei.com:8087/paygateway/smallpaygateway/trade`
  body `{"method":"samllProgramGetRoomState","bizcontent":"<json>","timestamp":"yyyy-MM-dd HH:mm:ss","sourceId":2}`；
  bizcontent `{"payproid":"2122","schoolcode":"769","roomverify":"<id>","businesstype":"2"}`；
  头 `Content-Type: application/json` + `Origin`/`Referer`（`https://cloudpaygateway.59wanmei.com:8087`、`.../pay/index.html`）。
- 响应：`businessData.quantity`（**字符串**，如 `"382.02"`）/ `businessData.quantityunit`（`度`）；
  `returncode=="SUCCESS"` 才算成功。查询房间**不需要学号/登录**；学号/姓名仅用于 CloudBase 写 token（`rpc/class_verify`）。
- 班级 17 间房 roomverify 固化在 `C:\briefdesk\scripts\sync_power_cloud.py`：
  13号楼324=`1-13---324`、13号楼308=`1-13---308`、16号楼305=`1-16---305`、16号楼306=`1-16---306`、
  23A-321=`4-23A---321` … 23A-330=`4-23A---330`、23B-422=`4-23B---422` … 23B-425=`4-23B---425`。
- **areaid / 虚拟楼层坑**：roomverify = `<areaid>-<楼栋>---<房间号>`。首段 `areaid` 是完美校园后台的「片区/虚拟楼栋」
  编号，**不等于现实楼栋序号**：13/16 号楼 `areaid=1`（`1-13`/`1-16`），23A/23B `areaid=4`（`4-23A`/`4-23B`）；
  楼层不参与查询（没有真实楼层字段，房间号直接拼在 `---` 后）。**逐间实测照抄，禁止按楼栋号/楼层自行推导**。
- **`samll` 是官方接口拼写错误**（`samllProgramGetRoomState`），必须原样照抄，改成 `small...` 会失败。

### 36.2 云端表 `public.power`（RLS）

- 列：`id(text PK = label) / label / building / room / roomverify / quantity numeric / unit / low bool / updated_at timestamptz`；
  `low = quantity < 30` 由同步脚本写入（前端也兜底按 <30 度标红）。
- RLS：`pw_read = public.auth_ok()`（有效班级 token；匿名/过期 token 读回 `[]`）；
  `pw_insert / pw_update = public.auth_admin()`（仅管理员 token）；anon 授 SELECT/INSERT/UPDATE，无 DELETE。
- 迁移：`deploy/cloudbase/2026-11-05_power.sql`（建表 + RLS + 回滚，幂等，已应用）。实测匿名 0 行 / 管理员 17 行。

### 36.3 本机同步 + 计划任务

- `C:\briefdesk\scripts\sync_power_cloud.py`：串行 17 间、请求间隔 ≥1.1s、失败 3 次退避（2s/4s）；已存在行 PATCH、
  新行 POST；失败房间**保留旧值**并记日志；日志 `C:\briefdesk\logs\power-sync.log`（>1MB 轮转 `.1`）；
  `--dry-run` / `--limit N` / `--interval` 可用；pythonw 兼容（不依赖 stdout）；**输出/日志不含姓名学号**。
- token：`C:\briefdesk\secrets\class-token.json`（与 `sync_notices_cloud.py` / `health_beat.py` 共用；过期自动
  `class_verify` 刷新）。⚠️ class_verify 的姓名必须与云端 `private.class_ids` **逐字一致**（含生僻字）；脚本里姓名用
  unicode 转义常量，曾因 `麒(U+9E92)` 误写 `驐(U+9A90)` 导致刷新失败（缓存 token 有效时不报错，易漏）——改动后请跑一次
  `get_token(..., force=True)` 或删缓存验证。
- 计划任务 `ClassPowerSync`：`pythonw.exe` 隐藏窗口，**每 60 分钟**（网关软限流；原定 30 分钟已调整为 60）。
  - 安装：`schtasks /Create /TN "ClassPowerSync" /TR "\"C:\briefdesk\venv\Scripts\pythonw.exe\" \"C:\briefdesk\scripts\sync_power_cloud.py\"" /SC MINUTE /MO 60 /F`
  - 查看：`schtasks /Query /TN "ClassPowerSync" /V /FO LIST`；立即跑：`schtasks /Run /TN "ClassPowerSync"`
  - 删除：`schtasks /Delete /TN "ClassPowerSync" /F`
  - 限制：`InteractiveToken`（需登录 Windows 才跑，与 jwxt / health 任务同模式）。

### 36.4 前端实现位置（`tools/index.html`）

| 区块 | 关键标识 |
|---|---|
| CSS | `/* ===== 宿舍电费 ... ===== */` 段（`</style>` 前）`.pw-*`；≥960px `#s-power.on` 左右分栏 |
| DOM | `<section id="s-power">`（`#s-diag` 之后、`#s-all` 之前）：`#pwMeta / #pwRefresh / #pwHero / #pwBuildings / #pwRooms / #pwList / #pwFoot` |
| 全部页卡片 | `renderAllCards()` 里 `data-open="power"` 的 `.gcard.tool[data-tone=blue]`（**无「设为首页」、不进 homeTools**） |
| 路由 | `gotoTab()`：`all/fb/ug` 例外列表加 `power`；`if(k==="power")POWER.enter()`；`renderTabs()` 的 `ok` 判定加 `power` |
| 刷新保位 | `POS.begin()` 的 `valid` 加 `power`（刷新后可回到电费页） |
| 数据模块 | `POWER`（`PW_LOW=30` / `PW_BLDS`）：`pull()` 走 `cbRaw("power?select=id,label,building,room,quantity,unit,low,updated_at&order=id.asc")`；`TTL.power=2*60*1000`；`cloudPull()` 仅在电费页按 TTL 拉取 |
| 本机缓存 | `zq_power_cache_<sid>`（最近数据）、`zq_power_sel_<sid>`（选中房间） |

- 交互：楼栋 chips → 房间 chips → 大字剩余电量（low 标红 +「低电」胶囊）；全部宿舍按电量升序（低电在前、占比条、可点选）；
  刷新按钮力拉；空数据「暂无数据」、失败「加载失败，点刷新重试」。
- 隐私：页面/JS 只有楼栋 + 房间号 + 电量，**无姓名/学号**；未接入导出图片；数据请求在身份 token 通过后才发。
  宿舍号展示是用户明确要求的电费功能本身（AGENTS 红线「页面不暴露宿舍号」的例外），不用于导出/对外分享。

### 36.5 测试（2026-11-05）

- 新增 `tools/tests/power_check.py` **59/59 PASS**：未登录 0 请求 / 卡片 / 打开 `#s-power` / 请求契约（Bearer + X-Device-Id + 列白名单）/
  8 行升序 / 低电 2 行（含云端 low=false 但 <30 度仍标红）/ 楼栋筛选 / 大字与状态 / 刷新力拉 / 可点 ≥40px / 返回全部 /
  无姓名学号 / 空数据 / 360·430·1280 无横向溢出 / 0 JS 报错 / 无外部请求 / 2 张截图（`tests/_shots_power/`；`SPEC_CHECK=` 可复盘任意副本）。
- 线上真实冒烟 22/22 PASS（headless Edge + CDP，真实 `class_verify` 登录 + 真实 `public.power` 17 行、power 响应 200、
  0 JS/console 报错、无外部请求）；截图 `power_live_390.png` / `power_live_1280.png`。
- 回归：`overflow_check.py 430`=0、`export_check.py draw` 正常、`stats_check.py` 30/30、`committee_check.py` 14/14。
- ① `selfcheck.py` / ③ `shots.py` 仍为身份门禁前旧脚本（见 §5.2），未作为门禁；本次用上述专项审计替代。

### 36.6 上线与回滚

- 上线：`index.html` **482,591 B · sha256 `1422438fa341a57162d1b7e86f99428ef728f9df0de4c5d744b32124e1600692`**（本地=线上 MATCH）。
  本次上线 = 线上基线（468,856 B · `7a2704e0…`，另一会话的 service_health/诊断页，**未由本会话验证**）+ 本会话电费功能；
  APP_VER 仍 2.0.0；只传 `index.html`（assets / tt.json 无变化）。
- 回滚：`tools/_backup/index_online_20261105-2252_prePower.html`（468,856 B · `7a2704e0…`）复制回 `tools/index.html` 后
  `python deploy/sync_tools.py index.html`。
- 云端回滚：`tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP TABLE IF EXISTS public.power"`；
  任务回滚：`schtasks /Delete /TN "ClassPowerSync" /F`。

### 36.7 已知限制 / 后续

1. 计划任务 InteractiveToken：未登录 Windows 时不跑，页面显示上次同步数据（旧 `updated_at`）。
2. 网关为非官方接口、有软限流：已按 60 分钟/次；被限流时日志记 gateway_fail 且保留旧值，不会清空数据。
3. 低电阈值固定 30 度（脚本 `LOW_THRESHOLD` 与前端 `PW_LOW` 各一处，改时同步改）。
4. 新增/调整宿舍：只改 `sync_power_cloud.py` 的 `ROOMS`（label/building/room/roomverify 四元组）+ 跑一次同步；
   页面楼栋 chips 固定 4 个、数据里出现未知楼栋会自动追加。

---

## 37. 宿舍电费 v2：统一命名 + 单选关注（下拉框）+ 选择进同步（2026-11-05 深夜，网页已上线）

> 用户新需求（2026-11-05 23:10）：「统一宿舍的名称；我不是需要所有宿舍统一展示，每个账号选择一个宿舍关注就好了
> （不是一次性选择，做下拉框）；宿舍选择也要放到同步里」。
> **本节覆盖 §36 中已过时的部分**：36.1 数据链路/网关/任务仍有效；36.2 的 `id=label`、36.4 的「全部宿舍列表/楼栋 chips/
> 房间 chips」已被 v2 取代。

### 37.1 规范化命名（全链路统一，Lead 定，不要自己改）

| roomverify | label | building | room |
|---|---|---|---|
| `1-13---324` / `1-13---308` | `13号楼324` / `13号楼308` | `13号楼` | 324 / 308 |
| `1-16---305` / `1-16---306` | `16号楼305` / `16号楼306` | `16号楼` | 305 / 306 |
| `4-23A---321/323/324/325/326/327/328/329/330` | `23号楼A座321` … `23号楼A座330` | `23号楼A座` | 3xx |
| `4-23B---422/423/424/425` | `23号楼B座422` … `23号楼B座425` | `23号楼B座` | 4xx |

- 规则：`{楼号}号楼{座}{房间号}`；23 号楼用「23号楼A座 / 23号楼B座」。
- **`id` 改为 `roomverify`**（稳定主键，显示名变化不影响行身份）；`label/building` 只作展示。
- 三处必须一致：CloudBase `public.power` 行、`sync_power_cloud.py` 的 `ROOMS`、前端 `PW_ROOMS` 静态目录。

### 37.2 CloudBase 迁移（`deploy/cloudbase/2026-11-05_power_v2_names.sql`，已应用）

- 17 行逐条 `UPDATE public.power SET id='<roomverify>', label='<规范名>', building='<规范楼栋>' WHERE id='<旧 label>'`
  （旧 id=旧 label，新旧值不重叠，逐行不会主键冲突）。
- `GRANT DELETE ON public.power TO anon` + `pw_delete ... FOR DELETE TO anon USING (public.auth_admin())`
  → 同步脚本可清理「不在 ROOMS 里的过期行」，普通成员/匿名无 DELETE 能力。
- 应用/回滚语句见迁移文件头尾；`2026-11-05_power.sql`（建表脚本）已同步为 v2 最终形态（含 DELETE 策略）。
- 实测：17 行 / 17 个唯一 id / 13 行 23 号楼；同步后 `stale_deleted=0`。

### 37.3 同步脚本（`C:\briefdesk\scripts\sync_power_cloud.py`）

- `ROOMS` 改为规范四元组；`id=roomverify`；已存在行 `PATCH power?id=eq.<roomverify>`，新行 POST；
- 全量运行结束后清理过期行：`DELETE power?id=eq.<旧 id>`（仅管理员 token；`--limit`/`--dry-run` 时不清）；
- 真跑一次：`ok=17/17 gateway_fail=0 cloud_fail=0 low=1 stale_deleted=0 elapsed=27.8s cloud_rows=17`；
  日志新增 `DEL ...（不在 ROOMS，已清理）` 与 `stale_deleted=` 字段；
- 计划任务 `ClassPowerSync`（pythonw，每 60 分钟）不变；token/class_verify/日志/隐私规则见 §36.3。

### 37.4 前端 v2（`tools/index.html`，`#s-power`）

- **去掉**「全部宿舍」升序列表、楼栋 chips、房间 chips —— 页面只显示**当前账号关注的这一个宿舍**。
- 单卡结构：标题「宿舍电费」+ 摘要（规范名 · 更新时间）+ 刷新；
  `label 关注宿舍` + **原生 `<select>` 下拉框**（`<optgroup>` 按规范楼栋分组：13号楼 / 16号楼 / 23号楼A座 / 23号楼B座；
  选项文本=规范 label、value=roomverify；高度 44px）→ 大字剩余电量（44/54px）+ 状态「低电/充足」+ 单房更新时间；
  ≥960px 左选房右大字两栏；≤400px 缩字号；引导语「选择你要关注的宿舍」。
- 数据：`GET power?select=id,label,building,room,quantity,unit,low,updated_at&id=eq.<roomverify>`（单行），
  走现有 `cbH()`（Bearer CBK + `X-Device-Id` token）；`TTL.power=2*60*1000`；本机缓存 `zq_power_cache_<sid>`。
- **未选择时不发任何电量请求**（选项来自静态目录，17 间）；选择即渲染并保存；低电 = 云端 `low` 或 `<30` 度标红。
- 静态目录 `var PW_ROOMS=[{rv,label,building,room}…]`（17 间，与同步脚本 ROOMS 同步维护）。
- 「全部」页卡片副标题改为「关注你的宿舍，看剩余电量、低电标红」（不再有「共 17 间」语义）。
- 隐私：页面只有规范楼栋+房间号+电量+更新时间，无姓名/学号；不接入导出图片。

### 37.5 UD v6 新增 `power` section（跨端契约）

- `UD_KEYS` 追加 `"power"`；`UD_DEF.power = {sel:"", at:0}`；默认空选择不报错（旧数据无 power 平滑升级）。
- 值：`power = {sel:"<roomverify>", at:<ms>}`（值内 `at` 与顶层 `at.power` 镜像，便于跨端只读）；
  顶层 blob 键序变为 **13 键**：`v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,homeToolsAt`。
- 合并/缓存/防抖/云端拉取完全复用现有一套（LWW、`zq_udcache/zq_udpend/zq_udat`、`cloudPull 60s`、`D.save → UD.touch`）；
- 应用：`UD.apply` 的 `take("power")` → `POWER.applyRemote(sel,at)`：更新下拉框/大字；不在电费页时只存选择不拉电量；
  非法/已下架 roomverify 平滑降级为未选择；
- 本机 `zq_power_sel_<sid>` 保留为**离线兜底**（同时在首次进入时一次性并入 UD）；**真源是 `UD.power`**；
- 两个账号互不影响（按各自 sid 的 userdata 行）；换设备/换浏览器同一账号登录后由 UD 拉取恢复；
- 小程序未拥有 `power` section：按既有「未拥有 section 原样保留」规则不写坏、**暂不展示电费**（后续要展示再改
  `mp-class-tools/utils/cloud.js` 合并逻辑 + 两端契约测试）。

### 37.6 测试（2026-11-05 深夜）

- `tools/tests/sync_check.py` 适配 v6 新契约后 **124/124 PASS**：新增/更新 —— blob 13 键顺序、`at` 覆盖 10 section、
  `power` 默认值、选关注宿舍 → POST blob.power（sel/at 镜像）、merge(web,mp)/merge(mp,web)/v5 回写期望值同步更新。
- `tools/tests/power_check.py` 重写后 **75/75 PASS**：下拉框/optgroup/17 选项、未选择引导 + 0 power 请求、
  选择后按 `id=eq.<roomverify>` 请求（Bearer + X-Device-Id）、切换只显示新宿舍、低电标红（含云端 low=false 但 <30）、
  刷新力拉、`zq_power_sel` + UD.power 推送、**同设备刷新恢复**、**换设备从云端 UD.power 恢复**、
  **两账号隔离（A/B 各选不同宿舍互不覆盖、POST 只写本人 sid）**、非法 roomverify 降级、360/430/1280 无溢出、
  0 JS 报错/0 console.error/无外部请求、3 张截图（`tests/_shots_power/`）。
- 回归：`overflow_check.py 430`=0、`export_check.py draw` 正常落盘（212,899 B）。
- **线上真实冒烟 24/24 PASS**（headless Edge + CDP，真实 class_verify 登录）：未选择 0 请求 → 选 23号楼A座321 →
  真实电量/刷新 → userdata POST 含 `power.sel` → **全新 profile 重新登录自动恢复关注宿舍并拉到真实电量**。
  截图 `tests/_shots_power/power_live_v2_restored_390.png`。

### 37.7 上线与回滚

- 上线：`index.html` **483,097 B · sha256 `16087845e4c938e3f4d5f18ff53d91ea489c4c6bd7410aac207cda2cebc3a306`**
  （本地=线上逐字节 MATCH；APP_VER 仍 2.0.0；只传 `index.html`，assets/tt.json 未改）。
- 部署前线上：482,591 B · `1422438f…`；备份 `tools/_backup/index_online_20261105-2311_prePowerV2.html`。
- 回滚：把上述备份复制回 `tools/index.html` 后 `python deploy/sync_tools.py index.html`。
- 云端回滚：命名迁移回滚 SQL 见 `2026-11-05_power_v2_names.sql` 头部注释；
  整表删除 `DROP TABLE IF EXISTS public.power`；计划任务 `schtasks /Delete /TN "ClassPowerSync" /F`。
- 冒烟期间在管理员账号 UD 里写入的测试关注宿舍（23号楼A座321）已清空回 `{sel:"",at}`，未影响其它 section。

### 37.8 已知限制 / 后续

1. 前端选项来自静态 `PW_ROOMS`（17 间）：**增删宿舍要同时改 3 处**（DB 行 / `sync_power_cloud.py` ROOMS / 前端 PW_ROOMS）。
2. UD.power 只有「当前关注的一间」；未选择时页面不请求电量（属产品选择，不是缺陷）。
3. 小程序端暂不展示电费；若后续展示，需实现 `power` section 合并 + 页面（当前 mp 仅原样保留）。
4. 其余 §36.7（InteractiveToken、网关软限流、低电阈值两处、30 分钟→60 分钟）仍适用。

---

## 38. 电脑端「比例」UI 优化（2026-11-05 深夜，网页已上线）

> 用户需求原话：「优化电脑比例的 ui」→ 经确认范围＝**全站电脑端统一优化**。
> 做法：只加一段 `≥960px` 的 CSS 覆盖块（`<style>` 末尾，标记 `DESKTOP-OPT-V1`），**不改手机端、不改 JS/HTML 结构、不加功能**。

### 38.1 审计（先审计后改）

- 审计报告：`tools/tests/_desktop_audit/REPORT.md`（5 档宽度 1024/1280/1366/1440/1920 × 13 页 + 抽签 3 STEP，75 张截图 + `metrics.json`）。
- 结论：**0 横向溢出**，但「`.wrap` 放宽到 1520 而内容排布没跟上」——抽签右栏 340–390px 空白、全部页 7 列窄卡、
  统计摘要固定 520px（1920 只占 35%）、班委单列 1458px、点名 1024 档只要 2 列（5.3 屏）、诊断 2 栏 194px 行间空白等。

### 38.2 改动清单（全部是 CSS 媒体查询，`web/tools/index.html` 内 `DESKTOP-OPT-V1` 块）

| 范围 | 规则要点 | 效果（1920 实测） |
|---|---|---|
| 全部页 | `#allCards` 限宽 1280–1320 居中；`.groups` 卡片 `minmax(250–272px)` | 7 列×205px → **4 列×321px**，卡片描述不再挤成 3 行 |
| 诊断页 | `.diag-grid` 960+ 改 `columns:2` 瀑布流（卡片 `break-inside:avoid`） | 两列高度平衡：卡片顶 y=212/451，**行间 194px 空白消除** |
| 电费页 | `.pw-body` 左栏限宽 300–400；`.pw-hero` 变浅沙内容面板；`#s-power .card` ≥1200 限宽 1180 居中 | 下拉框不再拉满 700px；大字电量有面板承载 |
| 班委名单 | `#cmOut` 960+ 两栏、1600+ 三栏（CSS columns） | 单列 940px → **2/3 栏 373–516px**，姓名与标签不再相距 1100px |
| 访问统计 | ≥1024 卡片改两栏 grid：左筛选+三块摘要（竖排）+说明，右排行榜 | 摘要宽度 520 → **300**（左栏），排行榜占右侧，不再右侧 970px 空白 |
| 点名 | `.rollgrid` auto-fill 断点 1200 → **960**（minmax 176） | 1024 档从 2 列 3917px 高 → 多列，页高大幅下降 |
| 作业/通知 | 双栏断点 1200 → **1024**；≥1600 三栏（minmax 440） | 1024–1199 不再单栏 56 CJK 行长 |
| 反馈 | 列表 ≥1024 两栏；表单卡片限宽 820 居中、textarea 760 | 管理员查看反馈更紧凑；写反馈行长受控 |
| 抽签 STEP1 | `#p1.on` grid 三行 `minmax(0,1fr) auto auto`，结果面板 `align-self:stretch` 垂直居中，排序/动作固定在右栏底部 | 结果面板 88 → **396px**（左卡 522），右栏 340–390px 空白消除 |
| 抽签 STEP2 | 分组结果卡 `minmax(250px)`、卡片内边距/行高加大 | 结果卡从 87px 小卡变宽卡（3–4 列视宽度） |
| 使用说明 | ≥1024 三栏 | 页高 801 → 595，宽屏不拉成两列长文 |
| 课表 | ≥1600 `.ttcard` 解除 1180 固定宽 | 1920 用满 1520 内容宽，周表列更舒展 |
| 其他 | `.rollhint/.stnote` 限 70ch；≥1440 卡片内边距 18/20 | 长文本行宽受控，宽屏留白更舒展 |

- 所有规则都在 `@media (min-width:960px)` 及以上；**<960px（手机/平板）一行未改**。

### 38.3 验收

- 审计口径：修复前/后同宽同页对比（`C:\briefdesk\data\desktop_opt\compare\` 6 组前后对比图）。
- 既有门禁（**打补丁后的 index.html**）全绿：
  `sync_check 124/124`、`v2_sync_check 35/35`、`v2_ui_check 27/27`、`v2_admin_check 39/39`、`v2_scroll_check 40/40`、
  `v2_x5_anim_check 28/28`、`power_check 75/75`、`committee_check 14/14`、`v2_notice_live_check 16/16`、
  `roster_check 199/199`、`v2_pos_restore_check 12/12`、`v2_notice_data_check 27/27`、`stats_check 30/30`、
  `v2_swipe_perf PASS`、`overflow_check 430/390 = 0`、`export_check` 正常。
- 线上真实冒烟（headless Edge + 管理员身份，真实域名/云端）：1920/1440/390 三档 **0 JS/console 报错、0 横向溢出**；
  全部页 4 列 321px、班委 3 列、统计两栏、诊断瀑布流、抽签 STEP1 结果面板 396px 均生效；390 手机端布局不变（无 media 命中）。
- 截图：`C:\briefdesk\data\desktop_opt\live\live_*.png`。

### 38.4 上线与回滚

- 上线：2026-11-05 23:52，`index.html` **496,283 B · sha256 `c929bd83561dd2312153493051230fbd037f2020a4de36dd4ba07c3fbd6b09e8`**
  （本地=线上 MATCH；APP_VER 仍 2.0.0；只传 `index.html`，assets/tt.json 未动）。
- 部署前线上：`491,461 B · b7819e39…`（含诊断+电费+通知时间修复）；备份 `tools/_backup/index_online_20261105-2350_preDesktop.html`。
- 回滚：把上述备份复制回 `tools/index.html` 后 `python deploy/sync_tools.py index.html`。
- 复跑：`python C:\briefdesk\data\desktop_opt\desktop_opt.py shoot <目录> <输出> --widths 1280,1440,1920`；
  审计脚本 `web/tools/tests/_desktop_audit/audit.py`（`--widths/--pages`）。

### 38.5 已知限制 / 没做的

1. 通知页 iframe 内部的两栏（模板自身 `.two` 列高差）属 `build_notice_board.py` 生成侧，本次未动（改模板风险大、另行任务）。
2. 短内容页（统计/电费/作业等）底部空白属内容量本身，只做了排布优化，未做垂直居中。
3. 超宽屏 >1920（如 2560）未专项审计；`.wrap` 仍按 1520 上限。
4. 手机/平板（<960px）保持原样 —— 本次需求是「电脑比例」，改动全部在桌面媒体查询内。
5. 并发注意：上线时其他会话已静默约 20 分钟；若之后它们再部署，需确认新版本是否包含 `DESKTOP-OPT-V1` 块（不含则重新套用本补丁：`desktop_opt/patch.css`）。

---

## 39. 宿舍电费 v3「数据仪表盘」：历史采样 + 电量环 + 近 24h 趋势 + 指标（2026-11-06 早，网页已上线）

> 用户新需求（2026-11-06 06:40）：「请充分利用空间，提高视觉效果和 ui」——针对 `#s-power` 做数据仪表盘升级（不改其它工具）。
> 设计评审：`C:\Users\Ko_Li\.openclaw\workspace\perfect-campus-power\research\ui_review.md`（§F 预评审 + 收尾清单）；本版按 Lead 收敛口径实施。

### 39.1 数据层：public.power_history（新增）

- 表：`id bigserial PK / roomverify text / quantity numeric / unit text default '度' / ts timestamptz default now()`；
  索引 `(roomverify, ts DESC)`；RLS：读=`public.auth_ok()`、写/删=`public.auth_admin()`；
  `GRANT SELECT,INSERT,DELETE TO anon` + `GRANT USAGE,SELECT ON SEQUENCE power_history_id_seq`。
  迁移：`deploy/cloudbase/2026-11-06_power_history.sql`（含回滚；实测匿名读 `[]`、管理员可读）。
- `C:\briefdesk\scripts\sync_power_cloud.py`：
  - 每次成功写 `public.power` 后追加同 ts 的历史采样（本次 `history_ok=17`）；
  - 新增 `--backfill-log`：解析 `C:\briefdesk\logs\power-sync.log` 的 OK 行（兼容旧格式无 `[roomverify]`，按旧 label→roomverify 映射），
    按 `(roomverify, ts)` 去重后补录；**已回填 169 行 / 17 间房**，重复执行插入 0（幂等）；
  - 全量运行后清理 30 天前历史（`power_history?ts=lt.<cut>` DELETE，仅管理员 token）。
  - 日志摘要新增 `history_ok/history_fail`；计划任务 `ClassPowerSync`（每 60 分钟，pythonw）不变。

### 39.2 前端 #s-power：仪表盘结构（v3）

- 结构：顶部 `lghead`（标题+刷新）→ `#pwDash`：hero 卡（关注宿舍下拉 + 电量环 + 状态 pill + 更新时间）、
  低电 alert（仅 low；移动端 hero 后/趋势前，桌面通栏置顶）、右栏（近 24h 趋势卡 + 4 个指标 tiles）。
- **电量环语义**：`arc = clamp(估算可用天数/30, 0, 1)`；环内大字=剩余电量（≥100 取整、<100 一位小数），
  下方小字「≈N 天」；数据不足（<2 采样或窗口 <6h）→ 环内「数据积累中」+ 小弧兜底；
  `role="img"` + `aria-label="剩余 X 度，估算可用约 N 天"`；颜色按状态（充足 `--cy` / 偏低 `--warn` / 低电 `--danger`），不按 arc 变色。
- **估算与指标**：`rateDay = Σ(下降段)/窗口小时 × 24`，`days = 当前/rateDay`；检测到上升（充值）→ 趋势 chip「期间有充值」，
  只累计下降、不记负用电；tiles = 估算可用（天）/ 近 24h 用电（度，1 位小数）/ 低电阈值 30 度 / 更新约 1 小时/次。
- **断点**（`ui_review.md` §B4）：390–719 单列（环 160 / 数字 56 / 趋势 132 / tiles 2×2）；
  720–959 hero 横排 + 趋势全宽 + tiles 一行 4 格；960–1279 两栏 5fr:7fr（环 200 / 数字 64）；
  1280–1439 容器随 wrap（环 208 / 数字 68）；≥1440 环 224 / 数字 72，≥1600 容器上限 1320。
- **桌面铺满**：`#pwDash` grid 两栏 + `min-height:max(560px, calc(100vh - 207px))`；
  右栏 `grid-template-rows:minmax(320px,1.3fr) minmax(240px,1fr)`（趋势吃满 + tiles 固定底部）；
  实测 1280×1000 仪表盘底距视口底 27px、1280×800 无纵向滚动（scrollH≈800）。
- **视觉/可达性**：沿用 Monet token，无旧 hex；pill AA（充足 `#2F6555`/#EAF2EC、偏低 `#8A6A3E`/#FAF3E6、低电 `#8F5550`/#F7EDEB、
  alert `#8A5049`/#F7EDEB）；小字 `--ink2` 且 ≥11.5px；状态三档常量 `PW_LOW=30 / PW_WARN=60`；
  刷新 loading = disabled +「刷新中」+ `aria-busy=true`；趋势 y 轴 3 个数值标签（10.5px `--ink2`）；
  房间名只出现 1 次（下拉选中值）、更新时间只出现 1 次（hero 行）；空态不折叠右栏、环内只显示「—」。
- 保留 v2 契约：`PW_ROOMS` 静态目录（17 间）、`UD.power` section、`cbH()` 请求方式、身份门禁；
  未选择时 0 个 power/power_history 请求；切换宿舍只拉该房间 `power?id=eq.<roomverify>` 与 24h `power_history`。

### 39.3 测试与上线

- `tools/tests/power_check.py` 重写 **110 项 PASS**（环刻度/趋势/指标/空态/低电/期间充值/UD 同步（选择/同设备恢复/
  换设备恢复/两账号隔离）/空间基准（1280×1000、1280×800）/360·430·1280 无溢出/0 JS 报错/无外部请求）。
- 回归：`sync_check` **124/124**、`overflow_check 430`=0、`export_check draw` 正常。
- **线上真实冒烟 27/27 PASS**（headless Edge + CDP，真实 class_verify 登录）：空态（未选择 0 请求）→ 低电宿舍（真实 22.25 度、
  低电红 + alert + 真实 history 趋势）→ 刷新（power+history 各 +1）→ 正常宿舍 → userdata POST 推送 power.sel 且云端确认 →
  **全新 profile 重新登录从云端恢复关注宿舍并渲染真实趋势/指标**；0 JS 报错、无外部请求。
- 截图（`tools/tests/_shots_power/`）：`power_v3_390.png`、`power_v3_768.png`、`power_v3_1280.png`、`power_v3_1440.png`、
  `power_v3_empty_390.png`、`power_v3_low_390.png`、`power_live_v3_restored_390.png`。
- 上线：`index.html` **511,604 B · sha256 `9b6143cb7d89fa11fb1ae16df59f1b833c81a25fe26e84b4b0473eaffeaccc6c`**
  （本地=线上逐字节 MATCH；APP_VER 仍 2.0.0）。部署前线上 496,283 B · `c929bd83…`（含其它会话 desktop-opt 增量）。
- 回滚：`tools/_backup/index_online_20261106-0701_prePowerV3.html`（496,283 B · `c929bd83…`）复制回 `tools/index.html` 后
  `python deploy/sync_tools.py index.html`；云端 `DROP TABLE IF EXISTS public.power_history`。
- 注意（换行符）：仓库 `index.html` 为 **CRLF**；本版曾因脚本化编辑被转成 LF 导致 `sync_check` 锚点失败，
  已恢复 CRLF。以后用脚本改 `index.html` 请显式 `newline=""` 并按字节读写，避免全文换行符漂移。

### 39.4 已知限制 / 后续

1. 趋势 y 轴标签为 3 个（最大/中/最小），未做坐标轴线；采样断档暂按直线连接（真实数据每小时连续，影响小）。
2. 环刻度依赖 ≥6h 窗口数据；新宿舍/新部署初期显示「数据积累中」（已回填 169 行，当前每间房 24h 内约 10–12 个点）。
3. 桌面 tiles 固定 2×2（≥1200 不再 4 列）；平板 4 列；如后续觉得桌面 tile 过宽可再评估。
4. 历史采样保留 30 天；长期趋势/月报未做。
5. `--backfill-log` 只解析 `power-sync.log` 当前文件（轮转后的 `.1` 可手动合并后回填）。

---

## 40. 宿舍电费 v4：24h/7天/30天趋势切换 + 固定 y 轴横滑 + 上次充值（2026-11-06 早，网页已上线）

> 用户新需求（2026-11-06 07:20）：趋势支持 7 天/30 天切换；「更新」改为「上次充值时间 + 重置度数」；趋势加竖坐标轴并支持左右滑动。
> 设计沿用 v3（`ui_review.md` 口径），本版只改 `#s-power` 的趋势卡与 tiles。

### 40.1 数据与请求

- 新增档位常量：`PW_RANGES = [{24h,ms=24h},{7d},{30d}]`；设备级记忆 `localStorage["zq_power_range_v1"]`（默认 24h，不进 UD 同步）。
- history 请求：`power_history?select=ts,quantity&roomverify=eq.<rv>&ts=gte.<now-窗口>&order=ts.asc&limit=2000`
  （`select` 精简为 ts,quantity；窗口随档位）；内存缓存 `POWER.hcache[rv][range]`，TTL 5 分钟；
  切档命中缓存不重复请求；刷新按钮力拉当前档，并保证 24h 数据存在（估算可用天数固定用 24h 速率）。
- 充值检测：所选区间内按 ts 升序，`q[i]-q[i-1] > 0.05` 记为充值事件；取最后一次 `{t, reset=q[i], delta}`；
  tile 显示重置后度数（1 位小数）+ 时间；区间内无事件显示「— / 暂无记录」（当前线上真实数据 0 次充值 → 显示 —，不造数）。
- tiles：估算可用（24h 速率）/ 区间用电（随档位）/ 低电阈值 30 / 上次充值。

### 40.2 趋势图（#pwTrendCard）

- 结构：卡头（标题 + 期间有充值 chip）→ 3 个 `.pw-range` chips（40px 高、`role=tab`、aria-selected）→
  `.pw-trend-wrap`（横滑区 + 固定 y 轴）→ 图例。
- 横滑区 `.pw-trend-scroll`：`overflow-x:auto`、隐藏滚动条、`touch-action:pan-x`、桌面 pointer 拖拽（pointer capture + user-select none）；
  画布宽 = `max(容器宽, 点数×最小间距+16)`（24h 恒为容器宽；7d/30d 点密时加宽可滑）；x 坐标按**真实时间比例**。
- 固定 y 轴 `.pw-yaxis`：在滚动容器**之外**，竖线 + 3 刻度（hi/mid/lo，--ink2 10.5px tabular），横滑不移动。
- 固定横轴 `.pw-xaxis`：覆盖层（不在滚动内容内），按当前可见窗口给 3–5 个日期刻度（24h `HH:MM`，7d/30d `MM-DD`），
  监听 scroll 刷新；相邻重复标签自动推进去重。
- 手势豁免：`excluded()` 首行 `if(closest(t,".pw-trend-scroll"))return true;` → 趋势图上的横滑/拖动只平移图表，
  不触发站点全局横滑切工具（冒烟里合成 touch 手势验证 `section.on` 不变）。
- 空态/加载/数据不足：仅保留 y 轴竖线（不显示 3 个「—」刻度值），趋势区占位「未选择宿舍/加载中/数据积累中」。

### 40.3 测试与上线

- `power_check.py` **135/135 PASS**：三档 chips 与默认档、请求 `ts=gte` 随档位单调更早、7d 标题/图例/区间用电 tile、
  充值 tile 有（414.20 + 时间）/无（—/暂无记录）、固定 y 轴在滚动容器外且横滑后位置不变、x 轴 3–5 刻度且横滑后更新、
  30d `scrollWidth>clientW+40`、横滑合成手势不切 CURTAB、30d 刷新 power/history、切回 24h 命中缓存、
  360/430/1280 无横向溢出、0 JS 报错、无外部请求；截图 5 张由门禁生成。
- 回归：`sync_check` 124/124、`overflow_check 430`=0、`export_check draw` 正常；
  通知门禁 `v2_notice_data_check` 27/27、`v2_notice_live_check` 16/16（部署前线上含其它会话的 `NOTICE_TPL_B64` 通知模板刷新，已保留）。
- 线上真实冒烟 **25/25 PASS**（headless Edge + CDP 真实 class_verify）：空态 0 请求 → 24h → 7 天 → 30 天（标题/tiles/图例/更早窗口请求）
  → 趋势横滑（不切工具、y 轴不动、x 轴在）→ 30 天档刷新（history +1）→ 云端 userdata.power.sel 确认 →
  全新 profile 登录恢复关注宿舍（档位为设备级 localStorage，默认 24h）；0 JS 报错、无外部请求。
- 上线：`index.html` **527,152 B · sha256 `2cf7ed06aac81dea30e882bbb6454a2edd09269b49141ff8ba342459d462427b`**；
  部署前线上 518,416 B · `5d923415…`（= v3 + 通知模板刷新）；部署后 2 分钟复取 hash 仍为最终版。
- 回滚：`tools/_backup/index_online_20261106-0737_prePowerV4.html`（518,416 B · `5d923415…`）→ 复制回 `tools/index.html` →
  `python deploy/sync_tools.py index.html`。本次无数据库结构变更，无需数据层回滚。
- 截图：`tools/tests/_shots_power/` 的 `power_v4_390.png`、`power_v4_7d_390.png`、`power_v4_30d_390.png`、
  `power_v4_recharge_390.png`、`power_v4_1280.png`；线上冒烟 `power_live_v4_{empty_,,7d_,restored_}390.png`。

### 40.4 已知限制 / 后续

1. 生产 history 自 2026-11-05 22:46 起积累（当前每房 11–12 点、0 次充值）：7d/30d 目前与 24h 数据接近，画布暂时不横向溢出属真实情况；
   随每小时同步积累到数百点后 7d/30d 自动进入可横滑状态。
2. 「上次充值」在真实数据出现首次充值跳变前一直显示「—」，属真实。
3. 横轴刻度为固定层按可见窗口截取（随滑动刷新），不是整段固定 3–5 个；断档仍按直线连接（与 v3 一致）。
4. 充值检测阈值 0.05 度，与 v3 的上升检测一致；极端噪声（±0.05 内）不会误判。

---

## 41. 宿舍电费 v5：估算可用算法（24h/7d 分段混合）+ 可调低电阈值（web 上线；mp 待按此实现）

> 用户新需求（2026-11-06 07:46）：优化「估算可用」算法；允许用户调整低电阈值（默认 30 度，随账号同步）。
> 本任务只改 web（`tools/index.html`），**未动 mp-class-tools**；小程序端由另一任务按本文 §41.1/§41.2 同口径实现。

### 41.1 估算可用算法（web 与 mp 必须逐字同口径；可直接翻译成 JS）

```
// 输入：pts24 = 最近 24h 采样（ts >= now-24h）；pts7 = 最近 7 天采样（ts >= now-7d）；均按 ts 升序，元素 {t:ms, q:度}
function rateFor(pts){
  if(!pts || pts.length<2) return {rate:null, valid:false};
  var used=0, hours=0, n=pts.length;
  for(var i=1;i<n;i++){
    var dt=(pts[i].t-pts[i-1].t)/3600000;
    if(!(dt>0)) continue;
    var dq=pts[i-1].q-pts[i].q;            // 正=用电，负=充值跳变
    if(dq>0.05){ used+=dq; hours+=dt; }    // 正常用电
    else if(dq<-0.05){ /* 充值跳变：整段跳过，不计用电也不计时长 */ }
    else { hours+=dt; }                    // 持平：计时长、0 用电
  }
  var span=(pts[n-1].t-pts[0].t)/3600000;
  var rate=hours>0 ? used/hours*24 : null;
  var valid=(n>=2 && span>=6 && rate!=null && isFinite(rate));
  return {rate:rate, valid:valid};
}
var r24=rateFor(pts24), r7=rateFor(pts7), rate=null;
if(r24.valid && r7.valid) rate=0.65*r24.rate+0.35*r7.rate;
else if(r24.valid) rate=r24.rate; else if(r7.valid) rate=r7.rate;
if(rate!=null) rate=Math.max(rate,0.05);          // 下限保护（度/天）
var days = rate!=null ? q/rate : null;             // q = 当前剩余电量
// 显示：days==null → 「数据积累中」（环用小弧兜底）；days>=30 → 「≥30 天」（环满）；否则 ≈ days.toFixed(1) 天
// 「估算可用」tile 副标：rate!=null → 「≈ {rate.toFixed(1)} 度/天」；无估算则空
// 环：arc = clamp(days/30, 0, 1)；环色仍按状态色
```

要点：
1. 只用 **24h 与 7 天**两个窗口的 history，与趋势图档位（24h/7d/30d）解耦；网络层始终拉取 24h+7d（切 30d 档再补 30d）。
2. 分段判定以「时间升序相邻点」为准：`dq = 前一点电量 - 后一点电量`。`dq>0.05` 才计用电；`dq<-0.05` 是充值跳变，
   该段 **dt 也不计入 hours**（这是本次算法与旧版「used/窗口跨度」的关键差异，否则充值窗口会稀释速率）。
3. 有效条件：窗口内 ≥2 个采样 且 首末跨度 ≥6h 且 rate 有限；24h 与 7d 都有效才混合（0.65/0.35）。
4. `rate` 下限 0.05 度/天；`days=q/rate`；显示 `≥30 天`（环满）/ 1 位小数 / 无估算「数据积累中」。
5. 已知真实数据现状（2026-11-06 08:xx）：history 每房 ~13 点、跨度 ~9h、0 充值 → 7d 与 24h 同源、结果一致；
   随每小时同步积累后 7d 窗口才会出现差异，算法无需改动。

### 41.2 可调低电阈值

- 存储：`userdata` v6 的 `power = {sel:<roomverify>, at:<ms>, low:<10–100 步进10，默认30>}`；
  **顶层 13 键不变**（`v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,homeToolsAt`）；
  LWW 用 `at`，值内 `power.at` 与 `at.power` 镜像一致；旧数据无 `low` 按 30。
- 判定：`q < low` → 低电；`low ≤ q < low*2` → 偏低；否则充足；pill/环色/alert/tile 全用该阈值。
- 交互：点「低电阈值」tile（button，≥40px，aria-haspopup）弹轻量选择层，8 档 10/20/30/40/50/60/80/100（每档 ≥40px），
  选中立即生效并 `D.save()` 触发 UD 推送；本机 `zq_power_low_<sid>` 仅离线兜底，真源是 `UD.power.low`。

- 测试验收：默认 30；点 tile 弹 8 档；改 50 → 305（22.25 度）仍低电；改 10 → 充足且 alert 隐藏；
  UD POST `blob.power.low=50`；本机兜底键 `zq_power_low_<sid>`；刷新保持；旧数据无 low→30；换设备恢复 60 后
  78.97 度判「偏低」（low≤q<low*2）；顶层键序仍 13 键。

### 41.3 测试与上线

- `power_check.py` **155/155 PASS**（新增 Q 段：算法 4 组 fixture（321 混合 ≥30/≈6.1；330 充值跳变跳过→≈5.5 天/≈30.1；
  422 持平日 rate 下限→≥30/≈0.1；325 24h+7d 混合→≈5.3 天/≈19.0）；阈值全流程；五档无溢出/0 JS/无外部请求）。
- `sync_check.py` **124/124 PASS**（v6 power 契约加入 low；EXP_V5 默认 power 同步更新）。
- `overflow_check 430`=0；`export_check draw` 正常。
- 上线：`index.html` **532533 B · sha256 `e38bddcf27c389a4a472648c0fa9406cc90df5b66fc3b471924007a17732f09a`**（本地=线上逐字节 MATCH；部署前线上为 v4 `527,152 B · 2cf7ed06…`）。
- 回滚：`tools/_backup/index_online_20261106-0755_prePowerV5.html`（v4）复制回 `tools/index.html` → `python deploy/sync_tools.py index.html`；无数据层变更。
- 截图：`tools/tests/_shots_power/power_v5_390.png`、`power_v5_threshold_390.png`、`power_v5_lowsel_390.png`、`power_v5_1280.png`。

### 41.4 mp 同步清单（给小程序端同学照做；web 已上线，口径以此为准）

1. **`utils/power.js` 换新算法**：实现 §41.1 的 `rateFor`（24h/7d 分段、`dq>0.05` 计用电、`dq<-0.05` 充值跳变整段跳过、
   `|dq|≤0.05` 计时长 0 用电、跨度≥6h 且≥2 采样有效）、0.65/0.35 混合、`rate=max(rate,0.05)`、`days=q/rate`、
   `days≥30 → 「≥30 天」`（环满）、无估算「数据积累中」；「估算可用」tile 副标 `≈ {rate 1位} 度/天`。
   网络层始终拉取 24h+7d 两个 history 窗口（30d 趋势档再补 30d）；无需依赖趋势档位。
2. **`LOW/WARN` 改由 `power.low` 驱动**：`q<low` → 低电、`low≤q<low*2` → 偏低、否则充足；pill/环色/alert/tile 全用该阈值；
   默认 30，范围 10–100 步进 10；旧数据无 low 按 30。
3. **`utils/cloud.js` 的 power section 增加 `low` 字段**（默认 30）：`power={sel,at,low}`，LWW 用 `at`，值内 `power.at` 镜像 `at.power`；
   `privacy.js` 的 `SECTION_KEYS/DEFAULTS` 同步加入 `power.low`（DEFAULTS low=30），顶层 13 键不变。
4. **`pages/power` 阈值 tile 改成可点弹层**：button（≥40px、aria-haspopup）+ 8 档 10/20/30/40/50/60/80/100（每档 ≥40px），
   选中立即生效并触发同步；无记录/无估算的占位与 web 一致（「—」「暂无记录」「数据积累中」）。
5. 验收对齐 web `power_check`：混合/充值跳过/持平日下限/24h+7d 混合 4 组 fixture；改阈值 50/10 的低电/充足切换；
   UD POST `blob.power.low`；换设备恢复 low；旧数据无 low→30。

### 41.5 已知限制 / 后续

1. 真实 history 仅 9h/房、0 充值：7d 与 24h 当前同源，拟混合值≈单一窗口值；「上次充值」仍为「—」，均属真实数据现状。
2. 阈值选项固定 8 档（10–100 步进 10），未做自由输入；如需 5 度粒度再评估。
3. 阈值是账号级偏好（UD.power.low），未按宿舍区分；后续如需「每房阈值」另立任务。
4. 小程序端需按 §41.1 伪码实现同样算法，并按 §41.2 的 low 判定/展示；web 本机 local cache 仅兜底、不作为跨端真源。

---

## 42. 用户 9 条反馈批次（2026-11-06 午，网页/数据管线已上线；小程序待上传）

> 用户 2026-11-06 12:02 九条反馈。本节记录网站 + briefdesk 数据管线部分；小程序部分见 `mp-class-tools/README.md`（已源码完成、待上传，版本仍 2.0.0、AI off）。

### 42.1 网页修复（index.html，已上线 553,962B/`187eaa8d…`）

1. **横竖屏工具栏卡住**：`resize` 先跑旧几何 thumb 重算；`renderTabs` 在 `.tabs.morph`(scaleX .975) 瞬间用 `getBoundingClientRect` 量按钮 → thumb 宽被写死 97.5%。改为工具栏几何 `offset*`；resize 顺序 = `__zqGeoInvalidate`→`__zqKillFly`→`__zqSwipeReset`→`__cardDragCancel`→重排 tabs→rAF 重算 thumb+重渲染全部页卡片。测试 `v2_orient_power_check.py` 33。
2. **电费关注宿舍未记录**：`POWER.enter()` 改为 UD `power.sel` 空/非法时始终回退 `zq_power_sel_<sid>` 并补 `D.save()`；修 1200ms 防抖窗口内刷新丢选择。
3. **全部页卡片拖动**（替代设为首页）：卡片右上角三横线 handle；拖到 `.tabs` = 加入/替换/移序工具栏（`homeTools` 同步契约不变）；全部页内拖动 = FLIP 排序，`localStorage zq_all_order_v1` 本机偏好（**不进 UD**）；删除 `homePending/toggleHome`；Pointer Events + 触摸；reduced-motion 关闭动画。测试 `v2_drag_check.py` 22。
4. **电费慢更新提示**：24h history 相邻 `|Δq|>0.005` 计变化，≤2 次显示「数据更新较慢 · 上次变化 MM-DD HH:MM」（0 次「数据未更新」），估算 tile 加「参考」；不插值。测试 `v2_power_slow_check.py` 25。
5. 旧契约测试更新：`v2_notice_time_check.py` 79/79、`v2_notice_time_live_check.py` 33/33（按 briefdesk-plan 最新契约；L3.13 剔除 ACTION_SHORT 归一映射键；部署后 `NTL_STRICT_L2=1` 严格模式）。

### 42.2 数据管线（C:\briefdesk，已生效）

- **微信附件**：`wechat_media.py` 落盘/匹配；`ai_triage` 保留微信图片/文件消息 + 相邻挂载 + 后到附件回填；builder 注入 data URI / 「待获取」；图片 V2 加密需 `img_aes_key/img_xor_key`（未配置，显示待获取）。
- **微信班级群消息 0 修复**：weflow md5 别名兜底（`Msg_<md5>` 反查失败时以 md5 作会话 ID），原 talker+md5 双查合并；实测微信消息 0→36 条/30h，10 群命中；weflow v0.10.0 已最新，无需升级。
- **压缩包**：`archive_scan.py` 安全解压（zip-slip/大小/数量/炸弹/嵌套上限）、递归识别 docx/xlsx/pptx/pdf/文本、AI 摘要（sha256 缓存）、小文件持久化；真实 5.18MB 样本 5 文件识别。
- **跨源重复通知合并**：`notice_merge.py` 同 URL/同原文/标题+正文相似 + 冲突守卫；真实数据 47→44 组、3 张合并卡（1 张 QQ+微信跨源；12 条旧重复 id 自动 archived）；`mergedSources/crossSource` 同步云端/模板。
- **班级小管家英语作业**：`xjg_homework.py`（官方电脑网页版 XHR/签名，只读列表、不点详情、无已读回执；15 条英语作业、token 至 2027-01-05；`--refresh` 失效需扫码）已接入 `hw_auto/run_hw_auto.py`（build→xgj merge→sync，失败不阻塞）；下一轮 2h 定时生效。
- **13/16 电量阶梯**：非 bug——网关对 13/16 按日批量刷新（24h 仅 1 次变化 vs 23A/23B 每次变），映射/同步/展示均正确；前端加「数据更新较慢/参考」提示（见 42.1-4）。

### 42.3 发布与回滚

- 线上 `index.html` **553,962 B · sha256 `187eaa8d4d2956c9de84b3548c8d4c877892462711740c543370541d896ca082`**（本地=线上 MATCH；模板 sha `14fb3e2aeaf85e95…`）。
- 回滚：`tools/_backup/index_online_20261106-1300_preUXBatch.html`（532,533 B · `e38bddcf…`）。
- 数据管线：`watchdog.pause` 已删除、watchdog 恢复；云端 active auto 通知 44/44（含 3 mergedSources、1 crossSource、file items 11、img items 12、archive 卡 1；管理员 4 列未动）。
- 注意：`build_notice_embed.py` 嵌入的模板与 13:02 重建 demo 的模板一致（99,108 B），只换数据时无需重 embed；换模板必须重跑 embed 并重新部署。

### 42.4 未完成 / 限制

1. 微信图片 V2 加密：需图片密钥才能显示真图，现为「待获取」；如需处理需用户授权提取密钥。
2. 小程序端本轮改动（电费持久化修复/工作台电费卡/慢更新提示/13 键契约）已源码+测试完成，**待用户上传发布**（版本 2.0.0、AI off）。
3. 小管家 token 2 月后到期需扫码刷新；发版若改签名/APP_INFO 需更新脚本。
4. 跨源合并会移除重复卡 id；若管理员曾 override 被合并的重复卡，可能成孤立行（当前线上无此数据）。

---

## 43. 卡片拖动跟手优化（2026-11-06 13:30，网页已上线 557,076B/`6d7b0aa8…`）

> 用户反馈「优化拖动工具卡片时的跟手效果」。

- **原问题**：拖动时无跟随元素（只有 `.drag-src` 半透明），且每次 move 遍历 `getBoundingClientRect` + 立即重排 DOM，移动端掉帧。
- **修复**：ghost 克隆固定定位跟手（同步写 `translate3d`，无 rAF/transition；偏移取按下点相对卡片）；几何缓存 + 8px 位移节流 + 目标变化才重排/让位；松手前补算落点；结束清理 ghost/源卡。`v2_drag_check.py` 22→36（鼠标/触摸 6 采样点误差 0.0px、ghost 属性、不滚动页面、GBCR 计数、落点/清理）。
- **上线**：557,076 B / `6d7b0aa8…`；回滚 `index_online_20261106-1328_preDragGhost.html`（553,962B / `187eaa8d…`）。
- 注意：ghost 的 `will-change` 只在拖动瞬间存在；`v2_x5_anim_check` S8 已按「幽灵临时使用」口径调整，勿恢复为全文禁 will-change。


---

## 44. 电费关注宿舍同步加固（2026-11-06 18:50，网页已上线 565,417B/`8520e547…`）

> 用户反馈：网页端电费关注宿舍仍不记录/不同步，重开需重选（自动登录、多环境、跨设备都看不到）。

- **根因**：boot `UD.pull()` 与用户选宿舍竞态——无基线时 `UD.touch()` 不推送；pull 返回后无脏标记、`power.at=0`，云端旧值在 merge 中赢并覆盖本机新选择。
- **修复**：`POWER.pick/enter` 兜底后 `pendWrite(["power"])`；`UD.pull` 对 pend keys 强制本机 at=now（无基线也生效）并补 push；`touch` 无基线时在手势后 pend+pull；进入电费页无 sel 强制 pull 重试；`pagehide/visibilitychange` flush；hero 脚注「已同步/未同步·点重试」。
- **测试**：`v2_power_sync_hardening_check.py` 29/29（含 boot GET 延迟 2.5s 竞态、无基线、立即 pagehide、失败重试）；全量 23 门禁全绿。
- **上线/回滚**：565,417B / `8520e547…`；回滚 `index_online_20261106-1848_prePowerSync.html`（557,076B / `6d7b0aa8…`）。
- **真机验证**：测试账号在新 build 上「登录→立刻选宿舍→立即 pagehide→重开/换 profile」云端与本地均恢复；徽标已同步。

## 45. 宿舍水量统计 + 水电计费规则 + 电费异常扣减忽略（2026-11-06 19:1x，网页已上线）

> 用户需求：「为班级工具站添加水量统计功能；目前水费无自动计费，为每月学生手动抄表模式，设计为可手动记录并自动与上次记录对比；由于水费自动从电费扣除，电费计算中如短时间内下跌幅度过大要予以忽略；搜索并为水量和电量统计添加计费规则」。
> 计费规则核实：`web/_water_rules/research.md` + `rules.json`（14 条来源，官方原文已核实）。
> 基线：电费关注宿舍同步加固版 565,417B / `8520e547…`（§44，已在线）。

### 45.1 计费规则（页面唯一来源 `var RULES`）

- **电费 0.58 元/度、水费 3.03 元/吨**（福建中医药大学后勤基建处 2025-09-05《关于学生公寓水电费计取的情况说明》原文；「不存在额外加价」）。
- **免费定额：每人每月 2 吨水 + 5 度电**，按月拨给、当月有效、每学年 10 个月、寒暑假无补贴（2021《学生公寓（宿舍）管理规定》）。4 人间=8 吨水/20 度电·月，6 人间=12/30（按人数折算为推断）。
- 无阶梯、无额外加价；无独立热水价/公共分摊；水电绑定同一寝室账户（余额按元，页面按度显示）。
- 公式：`本期水费 = max(0, 用量吨 − 2×人数) × 3.03`；`折合扣电 = 水费 ÷ 0.58`（1 吨水 ≈ 5.2241 度）；`区间电费 = 区间用电 × 0.58`。
- 页面不接市政阶梯价（仅研究文档备选对照）。
- 冲突标注：官方 5 度电/人/月 vs 第三方旧文 4 度 → 页面按 5 度并注明「以学校最新通知为准」。

### 45.2 网页实现（`tools/index.html`）

| 区块 | 关键标识 |
|---|---|
| 工具/路由 | `TOOLS` 新增 `{k:"water",n:"水量"}`（追加在 diag 后）；`ALL_TONE.water="blue"`；`gotoTab` → `WATER.enter()`；全部页自动生成卡片（可拖动进工具栏） |
| DOM | `<section id="s-water">`（`#s-power` 之后）：`#wtSel/#wtPersons/#wtLastNum/#wtLastSub/#wtCmp/#wtMonth/#wtReading/#wtSave/#wtPreview/#wtList/#wtRuleBody` |
| CSS | `/* __WATER_FEATURE_V1__ ... */` 段（`.wt-*`，`</style>` 前）；≥960px 两栏；`#pwBill` 计费规则行、`.pw-deduct` 徽标 |
| JS | `var RULES` / `PW_DEDUCT`（POWER 常量区）；`var WATER` 模块（POWER 模块之后）；使用说明新增「水量」段 |
| 数据 | `D.d.water={rooms:{<roomverify>:{p:4|6,recs:[{m:"YYYY-MM",r:吨,ts}]}}}`（DEF/mkD 归一，月唯一升序，≤120 条） |
| 同步 | UD v6 新增第 11 个 section `water` → **顶层 blob 14 键** `v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,water,homeToolsAt`；`at.water` LWW；water 值内不镜像 at；旧数据默认 `{rooms:{}}`；小程序未拥有端原样保留 |
| 本机 | 沿用 `zq_tools_v2_<sid>`；关注宿舍与电费共用（`POWER.sel` / `UD.power.sel`），水量页选宿舍只写选择+同步、不拉电费接口 |

行为：选关注宿舍（17 间，与电费同值）→ 宿舍人数 4/6 → 选月份+读数保存；自动与上一条对比（用量/水费/折合扣电/超定额）；同月覆盖、读数小于上条（或大于下条）拒绝、删除后自动重算、历史按月倒序、规则卡显示 4/6 人间免费额度与来源。

### 45.3 电费异常扣减（水费从电费账户扣）

- `POWER.deductOf(pts)`：`dq = q[i-1]-q[i]`；`U` = 窗口内 `dq>0.05` 的中位数；`dq > max(5, 4×U)` 视为**候选异常扣减**；
- 若该宿舍水量记录（采样月/上月）算出的 `水费/0.58` 与 `dq` 相差 ≤ max(2 度, 10%) 且 `dq≥2` → 标为**水费扣除**（即使未达候选阈值也忽略）；
- 异常段不计入区间用电/区间电费/估算速率（`rateFrom` 中跳过用电但保留时长；充值 `dq<-0.05` 逻辑不变）；
- UI：趋势卡头 `#pwDeduct`（「水费扣除 N 次扣减」/「已忽略 N 次扣减」）、图例「扣减 X 度」、区间用电 tile 副标「≈ ¥X.XX 电费」、`#pwBill` 显示电价/水费/1 吨≈5.2 度/免费定额/已忽略摘要；
- 阈值依据 `research.md §四`（`max(5, 4U)`），生产 1 小时采样下日常用电（1–2 度/小时）不会误判。

### 45.4 测试与验收（全部本机实跑）

- 新增 `tools/tests/water_check.py`（153 项）：**153/153 PASS**（静态 19/A 12/B 14/C 30/D 7/E 21/F 27/W 5/G 3；连跑 3 次稳定；360/430/1280 无横向溢出、0 JS 报错、0 console.error、无外部请求）。
- `tools/tests/sync_check.py` 适配 14 键 + water 后 **144/144 PASS**（新增 C5 水量同步 9 项 + K 旧数据 4 项）；`v2_sync_check` 35/35、`v2_admin_check` 39/39。
- 既有门禁适配新契约后全绿：`power_check` **155/155**（13→14 键 + fixture 补 water + 新扣减算法 rate 6.1→5.8 期望 + 1280×800 无纵向滚动）、`v2_orient_power_check` 33/33、`v2_power_sync_hardening_check` 29/29、`v2_power_slow_check` 25/25、`v2_drag_check` 36/36、`v2_ui_check` 27/27、`v2_pos_restore_check` 12/12、`v2_swipe_perf` PASS、`roster_check` 199/199、`reset_check` 109/109、`overflow_check 430`=0、`export_check draw` 正常落盘。
- 线上冒烟：部署后对线上字节复跑 `water_check`（SPEC_CHECK=线上副本）应 153/153；同步契约以线上字节复跑 sync_check。
- 小程序（源码完成，**待用户上传发布**）：`unit.js` 212/212（新增 water 12 项）、`sync_contract_test.js` 31/31（14 键含 water 双向合并）、`staticcheck.py` 0 missing、`cli auto-preview` 编译通过；版本仍 2.0.0、AI off。

### 45.5 截图

`tools/tests/_water_shots/`：`water_empty_430.png`、`water_records_430.png`、`water_1280.png`、`power_deduct_430.png`（已逐张目检：无溢出、中文正常、数字对齐；桌面右栏留白属内容量，非功能问题）。

### 45.6 上线与回滚

- 上线：`index.html` **594167 B · sha256 `e41866c03bed6000e35e53ae731de7dd5cd9cc5b20cffcc7d2cfe9e670296e89`**（本地=线上逐字节 MATCH）。
- 部署前线上：565,417 B · `8520e547…`（§44）；备份 `tools/_backup/index_online_20261106-1848_prePowerSync.html`（= 本次改动前线上）。
- 本地改动前（含 water 补丁前）备份：`tools/_backup/index_local_20261106_1854_preWater.html`（565,417 B，= 本次部署前线上版本；重传即回到水量改动前）。
- 回滚：把上述线上备份复制回 `tools/index.html` 后 `python deploy/sync_tools.py index.html`。
- 数据层：无新表/无迁移（water 走既有 `public.userdata` blob；`at` 为 LWW 时间戳）。小程序旧版本（未上传 water）按「未拥有 section 原样保留」不会丢云端 water。

### 45.7 已知限制 / 后续

1. 水费折算公式（水费÷0.58）校方文件未给算例，为「同一账户余额按元」+ 2017 校方学生媒体口径的多源推断；页面按估算展示，实际以学校账单为准。
2. 免费电额度只作规则展示，未从「区间电费」扣除（电费是充值口径：用电量×0.58）。
3. 异常扣减阈值固定 `max(5 度, 4×中位数)`；13/16 号楼网关日更（多个 0 变化 + 单段日用量）时中位数取日用量，不会把日用电误判为扣减。
4. 小程序水量页需用户下次在微信开发者工具上传发布后生效；网页已先上线，旧版小程序不会覆盖云端 water 数据（未拥有 section 原样保留）。
5. 桌面水量页「抄表历史」内容少时下方留白（grid 内容量），未做强制拉伸。

---


### 45.8 计费规则归位（2026-11-06 19:2x，网页已上线）

> 用户反馈：「电费的计费规则应放入电量统计里」。

- **电费页**：计费规则从趋势卡下方的独立行改为**指标 tiles 网格内的一条满宽规则条**（`#pwTiles #pwBill`）：电价 0.58 元/度、区间电费 ≈ ¥X.XX、免费 5 度电/人/月（4 人间=20 度）、水费 3.03 元/吨从电费账户扣 · 1 吨≈5.2 度、已忽略扣减摘要；与「估算可用/区间用电/低电阈值/上次充值」四格同属电量统计区。
- **水量页**：规则卡只保留水费规则（水费 3.03 元/吨、每人 2 吨水/月免费定额、超出定额×3.03、折合扣电÷0.58、计费说明）；不再重复电费单价与电免费定额；人数下拉文案改为「4/6 人间（每月免费 8/12 吨水）」。
- **桌面高度**：`.pw-side` 恢复两行 + tile 80px + 规则条紧凑，1280×800 scrollH=800（≤810 门禁）、1280×1000 仪表盘贴底。
- **测试**：`water_check` D01–D05 改为水费口径 + E11 断言 `#pwTiles` 内存在 `#pwBill`（0.58/3.03/5.2 度）→ **153/153**；`power_check` **155/155**（含 1280×800 scrollH=800）；`v2_power_slow_check` 25/25；`v2_orient_power_check` 33/33；`v2_ui_check` 27/27；`v2_drag_check` 36/36；overflow 430=0。
- **上线**：`index.html` **594,410 B · sha256 `f7731e77891dacb60b557206f38bd1fbce9ecd0058d6b4be03f82e86fd03c167`**（本地=线上 MATCH；线上字节复跑 water_check/power_check 全绿）；回滚：`tools/_backup/index_local_20261106_1918_preRulesMove.html`（594,167 B · `e41866c0…`），或整体回退到 `index_online_20261106-1848_prePowerSync.html`（565,417 B）。

## 46. 水量页云同步「所有内容」显性化/加固 + 桌面三栏比例（2026-11-06 19:52，网页已上线）

> 用户需求：「对水费统计的用户所有内容加入云同步，包括抄表记录等，优化网页端水费工具比例」。
> 基线：§45.8 版 594,410 B / `f7731e77…`（已在线）。
> 结论先行：**云同步本身在增量 16 已覆盖「用户所有内容」**（独立审计 20 项矩阵全绿，未发现漏同步）；本轮做
> ①同步状态显性化 + 归一/竞态加固；②桌面比例优化（≥1280 三栏等高、960–1279 两栏、手机零改动）。**v6 契约与合并算法未变**。

### 46.1 云同步加固（`tools/index.html`）

| 改动 | 说明 |
|---|---|
| `WATER.normWater(w)`（新增） | `water.rooms` 逐间归一：`p` 只允许 4/6、`recs` 走 `normRecs`（月合法 2000–2100、读数有限 ≥0、2 位、按月升序、≤120）、丢弃 null/字符串/数组坏房间 |
| `WATER.applyRemote` | 改用 `normWater`（远端不可信数据不再原样进 `D.d.water` raw） |
| `UD.sections().water` | 推流前同归一（本机旧脏数据不回写云端，避免 blob 膨胀/脏值扩散） |
| `#wtSync`（新增） | hero 底部同步状态：`已同步`（`data-sync=1`）/ `未同步 · 点重试`（`data-sync=0`）；未选关注宿舍隐藏 |
| `WATER.requestSync()` | 点重试：有基线 `UD.push(true,["water"])`；无基线 `UD.pull(true)` 建基线后补推（不盲推默认值） |
| `WATER.enter()` | 本机缓存还没有 water（旧缓存/首装）时强制补拉一次；其余走 `UD.pull()` 60s TTL |
| `save/del/setPersons` | 写后 `UD.pendWrite(["water"])`（无基线/推送失败时下次 pull 保本机赢） |
| `WATER.syncState()` | pending = `UD.pendRead() || dirtySections 含 water`（**不含** `_push`，不闪回）；`udSyncUi()` 统一刷新电费/水量状态 |
| 使用说明 | 「按账号同步」清单补「关注宿舍、水量抄表记录」；水量页补「换设备自动恢复；右上『已同步』可点重试」 |

同步字段（未变）：关注宿舍 `power.sel`（与电费共用）、每间人数 `water.rooms[rv].p`、每间记录 `recs[{m,r,ts}]`；
顶层 blob 14 键、`at.water` LWW、water 值内不镜像 at、旧数据默认 `{rooms:{}}`、未拥有端原样保留。

### 46.2 桌面比例（`__WATER_FEATURE_V1__` CSS 段内；<960 零改动）

- **≥1280px 三栏等高**：`grid-template-columns:repeat(3,minmax(0,1fr))`；`grid-template-areas:"hero form hist" "hero rules hist"`；`align-items:stretch`。
  - hero 自然高（不拉伸）≈442；中栏 = 新增抄表（≈237）+ 计费规则 chips（≈178–189），合计 = hero（±6px，无结构性空洞）；抄表历史与 hero 同高、`contain:size` + `.wt-list` 内部滚动 → 12 条/更多记录页高不增长。
  - 规则卡 ≥1280 变横向 chips：`#wtRuleBody{display:flex;flex-wrap:wrap;gap:2px 12px}`、`.wt-rule-row` 去边框 inline；**文案零改动**（water_check D01–D07 仍过）。
  - dash 宽度：`≥1280 max-width:1320`（生效 1188）/ `≥1600 max-width:1520`（生效 1492）；`#s-water .wt-dash>.card{margin-bottom:0}`。
- **960–1279px 两栏**：`grid-template-areas:"hero hist" "form rules"`，规则卡保持纵向（不 chips，避免被 form 拉高留白）；`align-self:stretch` + 历史内部滚动。
- **空态**：`#wtLastNum` 加 `.wt-num.no-data`（灰、30px 小占位）；未选宿舍 `#wtSync` 隐藏。
- **实测（stable e48bd963）**：1280×800 `scrollH=800`（旧 1115，−315；power 同口径 ≤810）；960/1024×800 `scrollH=955`（旧 1126，−171）；1440/1600 不滚动、dash 宽 1292/1492；12 条/空态 @1280×800 仍 800；430×900 单列顺序 hero→form→hist→rules、无横向溢出。

### 46.3 测试 / 门禁

- `water_check.py` **169/169 PASS**（原 153 + 静态 3 + 新增 H 组 13）：H01 未选宿舍隐藏、H02 已同步、H03 保存后「未同步·点重试」、H04 防抖推送完成恢复已同步、H05 推送 blob 含新记录、H06 点重试立即补推、H07 重试 blob 含新记录、H08/H09 远端归一（p=9→4、130→120 首 2010-11、非法月/坏房间丢弃）、H10 收尾截图状态。
- `v2_water_layout_check.py`（新增 29 项）：≥1280 三栏/等高/中栏合计=hero/1280×800 无滚动/dash 1188/chips；1440/1600 宽 1292/1492；960/1024 scrollH≤1000 两栏；12 条内部滚动；空态；430 单列；0 JS 报错/无外部请求。
- 独立审计 `v2_water_sync_check.py` **116/116 PASS**（`_water_work/sync_audit.md`；冻结副本 `tests/frozen/index_water_e48bd963.html`，R2/R5 修复确认、R1 已知限制）。
- `sync_check.py` **144/144**（适配 `UD.sections().water` 归一静态断言）；`power_check.py` **155/155**；overflow 430=0；export draw PNG 213,888 B。
- `v2` 批次（并发跑）：`v2_drag` 36/36、`v2_ui` 27/27、`v2_power_slow` 25/25、`v2_power_sync_hardening` 29/29、`v2_pos_restore` 12/12、`roster` 199/199、`reset` 109/109。
- `v2_orient_power_check` 首跑 22/23（B0「电费环境启动完成」timeout：与 `v2_drag`、`power_check`、双 teammate 浏览器测试并发，4–5 个 headless Edge → 启动超时，环境 flake）；**无并发单跑复测 33/33 PASS**（该脚本历史也有 ConnectionReset flake，见 `_water_verify/VERIFY_REPORT.md` §B）。

### 46.4 上线 / 回滚

- **上线**：`index.html` **600,198 B · sha256 `e48bd9635638a8da607feeeb9c7f9044b22d92a5b4cf6f9490846cced5630aba`**（部署后本地=线上逐字节 MATCH；`python deploy/sync_tools.py`）。
- **回滚**：`tools/_backup/index_online_20261106-1950_preWaterSyncLayout.html`（594,410 B · `f7731e77…`）复制回 `tools/index.html` 后 `python deploy/sync_tools.py index.html`；本地补丁前备份 `tools/_backup/index_local_20261106_1948_postWaterSyncLayout.html`（= 当前 stable 逐字节副本）。
- 数据层：无新表 / 无迁移（water 仍走 `public.userdata` blob）；小程序契约未变。
- ⚠️ **并行会话注意**：本增量部署后（19:58），另一并行会话在本地 `tools/index.html` 又追加了「课表横滑 `.ttframe` 包裹」WIP（本地 600,414 B / `4db9953b…`，非本增量内容，本增量未部署它）；**本增量以冻结副本 `600,198 B / e48bd963…` 为准**，线上在另一会话部署前保持该版本。若后续要复盘/回滚水量改动，用冻结副本或上面的本地备份，不要直接以当时的本地文件为准。

### 46.5 已知限制 / 后续

1. `water` 仍为**整段 LWW**：双端并发修改不同宿舍时，后推送者整段覆盖（本地与云端都只剩赢家）；顺序/单端使用无影响。若要「按宿舍/按记录合并」需 `water.rooms[rv].at` + recs 按 m/ts 合并，并同改小程序 merge、`fixtures/merge_ref.js`、`sync_check`——**先问用户要不要**。
2. 水费折算公式（÷0.58）为多源推断；免费电额度仅规则展示；异常扣减阈值固定——见 §45.7。
3. 小程序 water 页源码已就绪（另一任务），**待用户微信开发者工具上传发布**；旧版小程序未拥有 water section，按「未拥有端原样保留」不会覆盖云端 water。
4. 960–1279 平板档仍会纵向滚动约 1 屏（955 > 800）：两栏结构下 hero 高度为硬下限，继续压收益有限（桌面比例主诉求在 ≥1280 已满足）；若后续要压，可考虑该档也改三栏（hero 下拉在 ~285px 宽会拥挤，需另行评估）。
5. 桌面 1280×1000 时内容底部留白（442 内容 + 视口 1000），属内容页正常留白，不做强制拉伸。

---

## 47. 网页课表横滑「超出白卡框」修复（2026-11-06 20:05，本地完成 / 待 Lead 部署）

> 用户反馈：「对于网页课表功能，请优化滑动时会超出课表框的情况」。
> 基线 = 增量 18 部署的 stable **600,198 B · `e48bd963…`**（= 本修复改前备份，见 §47.6）；修复后本地 **600,414 B · `4db9953b…`**（未部署）。
> 本改动与增量 18（水量云同步/桌面比例）互不重叠：本修复只动课表 CSS 3 行 + HTML 包裹 2 行，JS 零改动。

### 47.1 根因（headless Edge + CDP 合成触摸已复现）

全局「左右滑动」IIFE（`tools/index.html` 文件末尾）在课表页把 `transform:translate3d(±W px)` 直接写在 `.ttmain` 上
（`curEl("view")` / `nextEl("week")`，W=`min(340,max(120,innerWidth*0.5))`），但 `.ttcard`（L114 起）与
`.ttbody`/`.ttmain`（L385-390 / L408-410）都没有 `overflow` 裁剪 → 拖动跟手、松手回弹、换周飞出/飞入期间，
`.ttmain` 里的 7 天周表（或日视图列表）画到白色圆角卡片外：

- 手机 360/390/430：左右页边 14px 条带外露（实测拖动帧框外差异 **4.9k–7.4k px**），且 translated 内容把
  `document.scrollWidth` 撑宽（实测 471/501/541 > 360/390/430，页面可横向拖动）；
- 桌面 1280：主列变宽后周表直接盖住右侧 `.ttside`（「下一节 / 全部课程」区域差异 **9.6k px**），换周飞出/飞入帧同样盖住；
- 换周 fly 的飞出/飞入帧（transform 过渡）泄漏 4.7k–34k px；日视图拖动泄漏 3.6k px。

小程序 `pages/tt/tt.wxss` 的 `.ttcard` 早已 `overflow:hidden` 并注释「左右滑动飞出/飞入时裁剪在卡片内」，网页端缺这一步。

**第二个「超出框」来源排查**：7 天周表有 `min-width:428px`（`ttRenderWeek` 的 `minW`），在 `.tscroll`（`overflow-x:auto`）里横向滚动时
内容由 `.tscroll` 自身裁剪（专项测试「.tscroll 横向滚到末尾时框外差异」四档均为 0）→ **不是**独立泄漏源；卡片 padding 属于白卡内部，
修复后 `.ttframe` 在卡片 content box 裁剪，任何时刻内容都不出白卡。

### 47.2 实现（`tools/index.html`，4 处 / 7 行，纯 CSS + DOM 包裹）

| 位置 | 改动 |
|---|---|
| L386-387（手机/平板，`@media` 外） | 删除 `.ttmain{order:2;min-width:0}` → 新增注释 + `.ttframe{order:2;min-width:0;overflow:hidden}`（flex 列 order 移到外层容器） |
| L410（`@media(min-width:1024px)`） | `.ttmain{display:block;order:0;grid-column:1}` → `.ttframe{display:block;order:0;grid-column:1;min-width:0}`（桌面 grid 主列 = 裁剪区，280px 侧栏之前） |
| L1219 / L1226（`#s-tt` HTML） | `<div class="ttbody">` 内包 `<div class="ttframe">`，现有 `.ttmain` 原样留在里面（闭合 `</div>` 补在 `.ttmain` 之后、`<aside class="ttside">` 之前） |

- `transform` 仍落在 `.ttmain` 上 → 滑动引擎的 `curEl("view")` / `nextEl("week")` / `cleanAllSections()` 选择器**全部不用改**，
  滑动阈值（4px 死区 / 1.2 斜率 / 56px 换页）、跟手直写、`fly()`、换周逻辑、其它 tab 手势均零改动。
- 桌面布局（两栏 grid / `tt-nonext` 单栏分支）不受影响：`.ttframe` 顶替原 `.ttmain` 成为 flex/grid item；`.ttside{display:contents}` 的 order 1/3/4 仍直接作用于 `.ttbody`。
- 取舍：`.ttcard{overflow:hidden}` 只在卡片边界裁剪、桌面仍会盖 `.ttside`，故用 `.ttframe` 裁剪在「主列」；代价是裁剪边从卡片 content box
  生效（正常静止状态 `.ttframe` 边界 == 原 `.ttmain` 边界，静止帧与修复前逐像素 diff=0，无 UI 被裁）。

### 47.3 专项测试（新增 `tools/tests/v2_tt_frame_check.py`，140 项断言）

驱动方式复用既有门禁：headless Edge（CDP 8937/9537，可 env 覆盖）+ `Emulation.setDeviceMetricsOverride` 四档视口 +
`Input.dispatchTouchEvent` 合成真实触摸 + 注入假身份/合成 7 天课表（含周六/周日 14 门，`termStart=2026-09-07`）+
拦截 `tcloudbasegateway` 与 `tt.json`（不碰真实云端）+ 固定页面时间（2026-11-06 09:30，保证截图逐像素可复现）+
注入 `*{animation:none}` 冻结装饰动画；截图 `Page.captureScreenshot` + PIL 逐像素对比。

| 断言组 | 修复前（`--src tools/tests/_tt_frame_work/base_1950.html --tag pre`） | 修复后（默认测 `tools/index.html`） |
|---|---|---|
| 静止：7 天列 / 14 课程格 / 课程名 / 无横向溢出 / 白卡在视口内 / `.tscroll` 末尾不漏 | PASS | PASS |
| 静止帧与修复前逐像素一致（无裁剪损失，四档） | —（修复前没有 pre 参照） | **diff=0 × 4** |
| 结构：`.ttframe` 存在 / overflow=hidden / 在 `.ttbody` 内 / 桌面主列止于侧栏前 | FAIL ×8（2 项/档 × 4 档） | PASS |
| 拖动按住帧：框外差异=0（1280 另断言侧栏差异=0）+ 卡内变化≥1500 | FAIL（框外 4.9k–7.4k；1280 侧栏 9.6k） | **框外=0、侧栏=0、卡内 90k–345k** |
| 松手回弹帧：框外差异=0 + 回落后整帧一致 | snap 帧 FAIL；回落 PASS | PASS（回弹帧框外=0，回落 diff=0） |
| 换周 fly 飞出/飞入各帧：框外差异=0 + 卡内变化≥1000 | FAIL（泄漏 4.7k–34k） | PASS（框外=0，卡内 12k–290k） |
| 横滑切周（#tWeekLbl 9→8→9）、课程点击弹层、上一周/下一周按钮、周·日视图 | PASS | PASS |
| 拖动中页面无横向溢出 | FAIL（360/390/430 页宽 471/501/541） | PASS（四档均 = 视口） |
| 日视图按住拖动帧（390） | FAIL（框外 3.6k） | PASS（框外=0，卡内 34.6k） |
| 0 JS 错误 / 0 console.error | PASS ×4 | PASS ×4 |
| **合计** | **107 PASS / 29 FAIL** | **140 PASS / 0 FAIL** |

- 修复后输出：`v2_tt_frame_check[post]: 140 PASS / 0 FAIL  (source sha256=4db9953b2572ae81)`，退出码 0。
- 修复前复现命令（保留基线副本，可随时重跑）：`python tests\v2_tt_frame_check.py --src tests\_tt_frame_work\base_1950.html --tag pre`。

### 47.4 回归（全部本机实跑，真实输出）

- `python tests\overflow_check.py 430` → `overflowCount=0 | per=draw=0,tt=0,hw=0,nt=0,ft=0 | hint=0`。
- `python tests\v2_swipe_perf.py --only fixed` → **PASS**（reactionRate=1、syncErrP50=0px、applyLatencyP50=0ms、frameP95=28.60ms、
  slow4px firstFollowDx=-4 / followRate=1.00 / diagPrevented=0、通知页 thumbFollowDx=-4、sectionTransformed=False、
  iframeScrollY=163 / parentScrollY=0 / iframeScrollBy=0、toolbar reactionRate=1、posWrites 0→1）。
- `python tests\v2_ui_check.py` → **27/27 PASS**（含 APP_VER=2.0.0、0 JS 报错、0 console.error、无外部请求）。
- `python tests\v2_x5_anim_check.py` → **28/28 PASS**（fly/通知页无 transform 残影、S8 will-change 仅拖动幽灵、fly 结束后无残留）。

### 47.5 截图（`tools/tests/_shots_tt_frame/`，已逐张目检）

- 修复前泄漏帧：`pre_390_drag_right.png`（右页边条带外露）、`pre_1280_drag_right.png`（周表盖住右侧「下一节/全部课程」）。
- 修复后：`post_390_drag_right.png`（裁剪在卡片内、页边干净）、`post_1280_drag_right.png`（裁剪在主列、侧栏完好）；
  另有 `post_{360,390,430,1280}_static / snap_1 / snap_2 / fly_1..5 / settled / static_day / tscroll_end` 与
  `pre_summary.json`、`post_summary.json`（含每项断言与像素数）。

### 47.6 上线 / 回滚（2026-11-06 20:08 已上线，Lead 执行并复验）

- 改前备份（= 增量 18 stable 逐字节副本）：`tools/_backup/index_local_20261106_1958_preTTFrame.html`（600,198 B · `e48bd9635638a8da607feeeb9c7f9044b22d92a5b4cf6f9490846cced5630aba`）。
- 修复后本地 = 线上：`index.html` **600,414 B · sha256 `4db9953b2572ae8149d59c90508dd9dfb02efa1577162aabd6103ab05408feab`**
  （部署后 `https://tool.furina.fun/` 逐字节 MATCH；部署前线上 stable 备份 `tools/_backup/index_online_20261106_2010_preTTFrameDeploy.html` = 600,198 B / `e48bd963…`）。
- 部署命令：`cd deploy && python sync_tools.py index.html`（只传 index.html，不重复传 assets/tt.json）。
- Lead 独立复验（独立脚本 `tests/_lead_ttframe/lead_tt_clip_check.py`，与本专项测试不同实现）：
  修复前基线 `--expect leak` 复现（390 框外左/右差异 4,893/5,317 px、1280 左 7,557 px、1280 侧栏被压 11,876 px）→
  修复后 `--expect fixed` **框外差异 0/0（360 与 1280 全部为 0）**、1280 侧栏残余 34 px 仅为「下一节」脉冲点装饰动画；
  静止帧课表网格区与修复前**逐像素 diff=0**（390/1280，无裁剪损失）；对**线上字节**复跑同脚本同样 0 泄漏。
- 线上冒烟：部署后线上 sha256 与本地 MATCH；`v2_tt_frame_check.py` 对本地字节 **140 PASS / 0 FAIL**
  （`--tag leadcheck`，source sha256=4db9953b…），`overflow_check.py 430` overflowCount=0、
  `v2_swipe_perf.py --only fixed` PASS、`v2_ui_check.py` 27/27、`v2_x5_anim_check.py` 28/28、
  `v2_tt_frame_check` 修复前基线复现 107 PASS / 29 FAIL（基线副本可复盘）。
- 回滚：把上述备份复制回 `tools/index.html`；若已上线则 `python deploy/sync_tools.py index.html` 重传（或重传线上备份）。**无数据层/契约改动**。
- APP_VER 保持 `2.0.0` 未动；未改其它 tab / 其它工具 / 导出 / 同步逻辑。

### 47.7 已知限制 / 未覆盖边界

1. 微信/X5 **真机**未验证：本改动不改 `transform`/`will-change`/透明度，既有 x5_anim 门禁 28/28 通过；建议上线后真机滑一次课表确认观感。
2. 横竖屏旋转：走既有 `resize`（`__zqKillFly`→重排）路径，未新增监听；`.ttframe` 尺寸随布局重算，无持久内联样式。
3. 裁剪边界为卡片 content box（卡片 14/18px 内边距区域不再允许内容压入），静止状态无元素原本压在内边距上（静止帧 diff=0 已证）。
4. `.tscroll` 横向滚动（7 天表）与 `.ttframe` 裁剪互不影响，专项测试断言「周末列可滚到完整可见 + 滚动到末尾框外差异=0」。
5. 若后续在课表主区新增绝对定位弹层/浮层，需注意 `.ttframe{overflow:hidden}` 会裁剪（当前课表无此类元素；课程详情/导入弹层都在 body 级 `#ttCPanel/#ttImportPanel`）。

### 47.8 并发说明（与增量 18 的关系）

- 本轮写作时另一并行会话已完成「增量 18 水量云同步显性化 + 桌面三栏」并部署 **600,198 B / `e48bd963…`**（见 §46.4，其条目里也记了本 WIP 的 600,414 B / `4db9953b…`）。
- 本修复是在该 stable 之上**最小增量**（4 处 / 7 行），diff 不含任何 water/水量相关行；文件内仍同时存在增量 18 的
  `__WATER_FEATURE_V1__` 标记与 `wt-*` 样式（`__WATER_FEATURE_V1__` 1 处、`wt-` 108 处，与改前一致 → 未互相覆盖）。
- 部署时以「增量 18 + 本修复」的 600,414 B 版本为准；若线上已被其它会话更新，先取线上 raw bytes 比对再决定（§26.4）。

## 48. 全部页卡片拖动 v2 + homeTools 只存用户选择（2026-11-06，网页已上线 608,498 B / `e01af2d6…`）

> 用户反馈：「我发现网页的拖动效果依旧不足」；补充：「拖动卡片时有时会出现在几个位置间抽动的问题，有时想拖到的地方目标卡片反而不会自动移走」；
> 多选：拖到顶部工具栏很难命中/容易误判、拖动不够跟手/有卡顿掉帧。
> 本轮同时按用户要求把小程序「工具排序」改为长按拖动、首页工具改为主动勾选（小程序端见 §4b 第 10 条，源码已完成、待用户上传发布）。

### 48.1 根因（都是实测复现，不是猜测）

1. **抽动 / 目标卡不让位**：旧 `calcCardsDrop` = 「最近卡片中心」+ `before=(y<cy)` 决定插在目标前/后。单列布局（390 宽全部页是 1 列）时同一行只有一张卡，`y` 与中心的关系只是「上/下」，指针横移到目标卡上时 x 完全不参与 → 目标不让位；而每次重排后 `refreshCardRects()` 立即刷新几何，导致同一指针位置在相邻两帧算出不同插槽 → A→B→A 抽动。
2. **掉帧**：旧 FLIP 循环里对每张卡 `void c.offsetWidth` 强制同步重排 + 逐卡 `getBoundingClientRect()`，移动中每 8px 一次。
3. **工具栏难命中**：命中区只有 `.tabs` ±6px / 下方 ~50px，且拖动中无任何投放区高亮（`.drophl` CSS 存在但从未被加上）。
4. **滚动后投放区失效**：`.tabs` 是 `position:sticky`，页面滚到顶部前后位于「贴顶 0…47」与「brand 下方 ~42…89」；旧实现只在拖动开始时缓存一次 bar 矩形，自动滚动到顶后命中区停在旧坐标。
5. **长列表**：没有边缘自动滚动，屏幕外的位置拖不到。

### 48.2 实现（`web/tools/index.html`，拖动 CSS 块 + 「全部页卡片拖动 v2」JS 块 + `renderTabs`/`dropToTabs`）

- `calcCardsDrop`：按「指针所在网格行 + 行内 x 中线」算插入位置；候选位置需连续 2 帧一致才落位（`DRAG.candPos/candN` 迟滞）；指针所在行只有源卡时保持原位；`applyInsertPos` 重排后**一次批量**读新布局（`readCards()` 同时取消旧动画）。
- `animateFlip`：WAAPI `element.animate([{transform:translate(dx,dy)},{transform:none}],170ms)` 批量让位；不支持时回退 inline transform 过渡；`reduced-motion` 时 duration=0。
- `dragFrame`：rAF 只做落点计算与自动滚动；ghost 跟手在 `pointermove/touchmove` 里同步写 `translate3d`（越过 6px 阈值同步 `beginGhost`，不依赖 rAF 时序）；指针移动 ≥6px 或滚动过才重算落点。
- 工具栏：`updateDropTarget` 命中区 = `.tabs` 整条 + 下方 26px（离开迟滞 72px），命中加 `.drag-over`、目标 tab `.drophl`、插入线、tabs 让位 10px；`autoScrollStep` 滚动后调用 `refreshBarRect()` 刷新 sticky 换位后的实时位置。
- 自动滚动：`DRAG_EDGE_TOP=90 / DRAG_EDGE_BOT=110`，每帧 3–16px，`shiftGeom(-dy)` 平移卡片几何缓存，松手停。
- 收尾：ghost 150ms 收拢到源卡再移除；`navigator.vibrate` 轻震；`dragSuppress=+360ms` 抑制点击；`cancelCardDrag` 幂等清理（resize/切页安全）。
- **homeTools 语义**：`renderTabs` 里 `stored = 过滤后的 D.d.homeTools.slice(0,4)`，显示用 `home = stored + 按 TOOLS 顺序补齐到 slots`，但 `D.d.homeTools` 只写回 `stored`（补齐项不落盘）；`dropToTabs` 只在用户拖入时按「已有则移序 / 不足 4 个则插入 / 满 4 个替换当前屏幕比例可见槽位」写 ≤4 个真实选择。→ 小程序端只勾选 1–3 个首页工具时，打开网页不会被补回 4 个。

### 48.3 测试

- `tools/tests/v2_drag_check.py` 重写扩展 **36 → 56 项**：原有 A–J 全保留（B/C 先滚动再量 tab 坐标、D 先滚回顶部同时量两张卡，修掉旧用例的 sticky 坐标时序问题）；新增
  K 命中区扩大/高亮/移出清除、L 12 采样点源卡索引无 A→B→A + 目标卡让位、M 边缘自动滚动/离开停止/松手停止、
  N 远端 homeTools=2 时本机仍 2 个且工具栏补齐显示、O 收尾无幽灵/残留内联位移、P 1280 多列网格拖动、Q 自动滚到顶后 sticky 工具栏换位仍能命中。
- 本地字节 56/56、**线上字节（下载后 SPEC_CHECK 同测试）56/56**；门禁：sync 144/144、water 169/169、power 155/155、
  v2_water_layout 29/29、v2_water_sync 116/116、v2_tt_frame 140/140、v2_ui 27/27、orient 33/33、overflow 430=0、
  x5_anim 28/28、pos 12/12、power_slow 25/25、sync_hardening 29/29、export OK、swipe_perf PASS。
- `v2_x5_anim_check` S8 的口径：全文只能有 1 处 `will-change`，且必须属于 `beginGhost`（幽灵临时层提升）；本轮最终代码满足（CSS 里的常驻 `will-change` 已移除，改到 beginGhost 内联）。

### 48.4 上线 / 回滚 / 并发

- 本地 = 线上 `index.html` **608,498 B · sha256 `e01af2d6b1ec8007faee0366542b451732bd42840fe7f48ad60bb7997ab10cea`**（部署后两次复取 MATCH）。
- 部署前线上（= 增量 19 stable）备份 `tools/_backup/index_online_20261106_2020_preDragV2Deploy.html`（600,414 B / `4db9953b…`），重传即回滚；本地补丁前另存 `tools/_backup/index_local_20261106_2010_preDragV2.html`。
- 并发：基线为另一会话 20:08 部署的增量 19（课表横滑裁剪 600,414 / `4db9953b…`）。本轮 diff 不含课表/水量/通知/电费相关行；部署前取线上 raw bytes 确认与本地基线逐字节一致后才打补丁、部署。
- APP_VER 保持 `2.0.0`；未改同步合并算法、未改云端/数据表。

### 48.5 已知限制

1. 拖动仍只从卡片右上角三条横线 handle 起手（未做「长按卡片任意位置拖」，本轮用户未要求）。
2. 特殊卡片（宿舍电费 / 反馈建议 / 使用说明）不在 `TOOLS` 内，不能拖进工具栏（维持原语义）。
3. 仅 headless Edge（鼠标 + 触摸模拟）自动化验证，未做微信真机手测；`will-change` 只在幽灵上加，X5 门禁通过，建议真机再拖一次确认手感。
4. 跨端 homeTools：云端/另一端写入的顺序按原样应用，不做「按本端顺序重排」（避免两端来回改写；本端勾选/拖动产出的顺序一定按本端顺序）。


---

## 45. 电费趋势详细查看 + 返回键/登录闪烁/使用说明/性能安全（2026-11-06 22:05，网页已上线 619,447B/`e697df0e…`）

- **趋势**：去 7d/30d 横滑（无 scroll/代理/提示），全采样按真实时间比例压缩铺满；点击/拖动显示最近真实采样点（竖线+圆点+时间/电量，同步 snap，松手保留，点空白取消）；手势豁免；空态不显示；慢更新/充值保留。测试 `v2_power_detail_check.py` 24。
- **返回键**：tab/工具切换 pushState，popstate 回上一 tab；根层双击返回退出提示；弹层返回先关。`_silent` 防脏 history。
- **登录闪烁**：body.auth-pending 首帧隐藏 .wrap，身份完成移除；未登录门禁首帧即显示、已登录不闪。
- **使用说明**：`#s-ug` 补电费/拖动/通知附件/跨源合并等。
- **性能/安全**：首屏指标与旧版对比（mock 内 ±10ms，首屏云请求 1→1）；通知 iframe sandbox + postMessage e.source 校验；无 eval/内联事件、esc 133 处、token 未暴露。
- **上线/回滚**：最终 619,447B/`e697df0e…`（含 tip clamp/resize 重排）；回滚 `index_online_20261106-2255_preDetailClamp.html`（617,440B/`c7bbff40…`）。

---

## 39. DNS 暂停前改造：课表去域名化 + 诊断 18 行 + 网页暂停开关（2026-11-07）

> 用户需求：修复课表问题（网页暂停后小程序课表不能断）、添加和完善诊断条目；用户随后会自己挑时间暂停 **furina.fun 全部解析**，网页暂停使用。
> 契约：`tools/tests/dns_pause_tt_health_spec.md`（详细）；验收摘要：`tools/tests/health_monitor_spec.md` §9。

### 39.1 课表去域名化（核心）

- 新表 `public.site_assets`（`id='tt'`，`body`=原 tt.json 对象，`meta`={source,fetchedAt,count,termStart,syncedAt}）；
  RLS：有效班级 token 可读、仅管理员可写。迁移 `deploy/cloudbase/2026-11-07_site_assets.sql`。
- 写入：`web/jwxt/tt_cloud.py`（管理员 token 从 `C:\briefdesk\secrets\class-token.json`，过期自动 class_verify；
  PATCH/POST `site_assets?id=eq.tt`）；`web/jwxt/sync.py` 写盘成功后 always try publish（失败只记日志、不影响退出码/`--deploy`）；
  手动回填 `python web/jwxt/tt_cloud.py --tt tools/tt.json`。
- 读取：小程序 `utils/cloud.js → ttFetch` **CloudBase `site_assets` 优先**（统一 request 通道，带 `X-Class-Token`），
  失败回退旧 `ttUrl`（legacy，不带 token）；网页 `ttSyncPull` **同源 `tt.json` 优先**，失败回退 CloudBase `site_assets`。
  两者都失败时保留本机缓存/提示，不阻塞页面。原 6h TTL、cloudOff、云开关语义不变。
- 小程序已发布版本（备案号 闽ICP备2026042939号）需**用户重新上传发布**后才生效；未发布期间旧版本仍走 legacy `ttUrl`，
  DNS 暂停后会回退缓存（不更新）。版本号保持 2.0.0。

### 39.2 诊断 v2：18 行 / 5 组（web + 小程序同口径）

分组：站点与网页（site_static/site_tls/dns_domain）· 云端后台（cloudbase/tt_cloud/cloud_power_sync/cloud_xgj_sync/cloud_health_probe）·
信息采集 · 定时任务 · 采集主机。新增行判定/阈值见 `health_monitor_spec.md` §9.2：
- `dns_domain` 域名解析（网页暂停时：不可解析=正常「已暂停」；仍解析=注意）
- `tt_cloud` 课表云端快照 freshness（≤30h ok / 30–54h warn / >54h down）
- `cloud_power_sync`（power 表最新 updated_at ≤2h ok）、`cloud_xgj_sync`（homework 表 `auto_hw_xgj_en_*` 最新 ts，≤3h ok；当前无行=注意「暂无学工记作业」）
- `cloud_health_probe` 云端巡检心跳（每 5 分钟；超 15 分钟 → 其它 cloud 行「注意 · 巡检未更新」）
- 云端 8 行由云函数 `health_probe` 写；本机 `health_beat.py` 只写 local 10 行（不再探测域名/TLS，watchdog 单轮 4.5s→1.8s 级）。
- 网页暂停语义：`public.site_config` 行 `web={paused,note,paused_at}`（仅管理员可读写）；`web_pause.py --on/--off/--status` 维护；
  `paused=true` 时 `site_static/site_tls` 显示「注意 · 网页已按备案安排暂停」而不是误报异常。

### 39.3 文件位置

| 作用 | 路径 |
|---|---|
| 课表云端发布 | `web/jwxt/tt_cloud.py`；`web/jwxt/sync.py` 集成 |
| 迁移 SQL | `web/deploy/cloudbase/2026-11-07_site_assets.sql` |
| 云端心跳/暂停判定 | `C:\briefdesk\scripts\health_beat.py`（唯一真源）→ `deploy.py` 复制到 `cloudbase/functions/health_probe/` |
| 云函数入口 | `C:\briefdesk\cloudbase\functions\health_probe\index.py` |
| 暂停开关 | `C:\briefdesk\scripts\web_pause.py` |
| 小程序 | `mp-class-tools/utils/cloud.js`（ttFetch/ttCloudFetch/ttLegacyFetch）、`utils/diag.js`、`utils/cloud-config.js` |
| 网页诊断 | `tools/index.html` DIAG 模块（18 行/5 组 + 巡检过期降级 + 暂停覆盖保护）、`ttSyncPull` 回退 |

### 39.4 验证（2026-11-07）

- 云端：两表 RLS 6 策略；`site_assets.tt` body 与本地 tt.json 深度相等；管理员读 1 行、匿名=[]；`service_health` **18 行**，
  云函数 invoke 3 次 ok rows=8；暂停 --on/--off 链路实测通过（最终 paused=false）。
- 本机：`health_beat --once` 只写 local 10 行（1.99s），云端 8 行不被覆盖；watchdog 自动轮 1821ms。
- 小程序：unit 232/0、v3_power_diag 43/0、cache_unit 18/0、sync_contract 31/0、staticcheck exit 0。
- 网页：`tools/tests/dns_pause_web_check.py` **19/19**（18 行/5 组、暂停注意、巡检过期降级、tt 回退）；既有门禁
  sync 144、v2_ui 27、v2_admin 39、v2_sync 35、v2_scroll 40、x5 28、power 155、committee 14、notice_live 16、overflow 430/390=0、export OK、
  roster/pos_restore/notice_data/stats/swipe_perf 见 QA 报告 `tools/tests/_dns_pause_qa/REPORT.md`。
- 上线：`index.html` **621,560 B · sha256 `e4b16188d631f564138121e5441c2733e9c8ebc04166bf12837be93b0ac3092f`**（本地=线上 MATCH）；回滚 `index_online_20261107-0750_preTTDiag.html（619,447 B / `e697df0e…`）`。

### 39.5 用户侧后续动作（重要）

1. **先在微信开发者工具上传并发布新版小程序**（本次 mp 改动含课表去域名化 + 诊断 18 行），等审核通过。
2. 挑时间先运行 `C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\web_pause.py --on`
   （网页标记暂停 → 诊断显示「已暂停」而非异常），然后再暂停 furina.fun 全部解析。
3. 备案通过、恢复解析后运行 `web_pause.py --off`；恢复后诊断应回到 18 行真实状态。
4. **2026-12-10 前续费 CloudBase 环境**，否则小程序与云端数据一并中断。
5. 小程序发布后可评估从后台移除 `tool.furina.fun` request 域名（legacy 兜底不再必需）；删除前保留一次发版观察。

### 39.6 已知限制

- `cloud_xgj_sync` 当前 homework 表无 `auto_hw_xgj_en_*` 行（英语作业全部完成/xgj 只写未完成）→ 显示「注意 · 暂无学工记作业」，属预期。
- 小程序 legacy `ttUrl` 兜底仍指向 `tool.furina.fun/tt.json`；DNS 暂停后该兜底失效，主链路（CloudBase）不受影响。
- 旧 QA 脚本（`_health_qa/`、`mp-class-tools-tests/_qa_v2/mp_sync_features_check.js`）仍写死「13 行/4 组」，已过期，不作为门禁。
- 网页 `tt.json` 同源文件在恢复/换域名后仍可部署；CloudBase 回退只解决读取，不替代 OSS 上传。

---

## 40. 小程序电费趋势浮层对齐网页 + 「关注宿舍每次修改后要重选」原因（2026-11-07）

### 40.1 小程序趋势点击改网页版样式（task-9，待用户上传发布）

- 目标：小程序电费趋势的点击/拖动查看，视觉与交互对齐网页 `POWER.detail*`：
  **竖直游标线 + 真实采样点 y 位置圆点 + 深色浮层气泡**（`HH:MM` / `MM-DD HH:MM` + `电量 xx.xx 度`），
  气泡默认在点上方、越界自动翻到下方并水平 clamp；同点再点取消、拖动松手保留、换区间/清选择清除、无横滑。
- 改动：
  - `mp-class-tools/utils/power.js`：新增纯函数 `cursorTipLayout(x,y,cw,plotH,tipW,tipH,pad)`（网页 `POWER.placeTip` 同口径 + 窄屏限宽 + 非法入参安全值）。
  - `pages/power/power.js`：`_drawTrend` 记录 `_plotH`（实际测量高）并抽 `PLOT_PAD_X/T/B`；`_cursorFrac` 反解 canvas 坐标（含 padX）；`_showCursor` 用真实采样点像素坐标定位 → setData 回调用 `wx.createSelectorQuery` 实测 `.pw-plot`/`.pw-cursor-tip` → `cursorTipLayout` 修正气泡锚点（`_cursorSeq` 只应用最后一次，测量失败保留初值）；重置点统一 `cursorOff()`（left/top/tipLeft/tipTop/below/text）。
  - `pages/power/power.wxml/.wxss`：新增 `.pw-cursor-tip`（深色 #25332F、白字、圆角、阴影、nowrap/80% 限宽、`translate(-50%,-100%)`，below 变体 `translate(-50%,0)`）；圆点按 `cursor.top` 定位；删除可见 `.pw-cursor-info` 胶囊（`.pw-plot` 加 aria-label 保留读屏信息）；chips/图例/坐标轴不变。
  - 测试：`unit.js` 234/0、`v3_power_diag_tests.js` 45/0（+2：cursorTipLayout 7 组边界、气泡实测/防抖/失败保留）、`cache_unit_tests.js` 18/0、`sync_contract_test.js` 31/0、`staticcheck.py` exit 0、`code_quality_check.js` 通过。版本仍 2.0.0，**未上传/未发布**；automator 端口未开，`power_preview.js` 未跑（脚本不依赖旧 DOM，可在 automator 会话复跑）。
- 用户侧：微信开发者工具上传 → 提交审核 → 发布后生效。

### 40.2 为什么「关注宿舍」每次都要求重选（诊断结论）

- 真源：`public.userdata` v6 blob 的 `power={sel,at,low}`；网页/小程序本机 `zq_power_sel_<sid>` 只是离线兜底。
  同步采用**整包 blob 推送**（各 section 带时间戳、服务端不逐字段合并）——“谁最后整包写，谁的时间戳生效”。
- **已确认的历史机制**：我此前做桌面 UI 优化的线上截图/冒烟脚本（`C:\briefdesk\data\desktop_opt\desktop_opt.py`、
  `live_smoke.py`）注入的是**真实管理员 token** 打开线上站点，且当时**没有拦截云端写请求**；无痕浏览器没有本机选择，
  首轮同步/冒烟操作可能把测试用关注宿舍或空 `power={sel:"",at}` 推回云端。`HANDOFF §37.7` 有原文记录：
  「冒烟期间在管理员账号 UD 里写入的测试关注宿舍（23号楼A座321）已清空回 `{sel:"",at}`」——这次清空就抹掉了真实选择。
- 小程序对「云端显式空值」更严格：`_syncSel` 里 `allowFallback` 仅在云端没有 `power` 字段时用本机兜底，
  `sel=""` 被当成明确取消 → 云端一旦被空值覆盖，小程序下次打开就必须重选；网页端会用本机兜底 + 补推，通常能自愈，
  但多设备/旧标签页仍可能再把空值写回。
- 2026-11-07 09:47:45 云端 `power.sel` 再次变为空（09:39 时还是 `4-23B---423`）；09:51 我跑的冒烟已加写拦截（实测 blocked=2：
  visits+userdata，云端 UD 时间戳未变），因此那一次清空不是这轮冒烟造成的，可能来自其它旧设备/旧会话/其它自动化。
- **已做的修复**：新增 `web/tools/tests/_qa_v2/_cloud_guard.py`（`install_write_block(page)`：只放行 GET/HEAD/OPTIONS 与只读 `POST /rpc/`，
  其余云端写 fail），已在 `desktop_opt.py`、`live_smoke.py` 导航前接入；`web/AGENTS.md §4b-15` 固化为规则。
  后续所有用真实管理员 token 的截图/冒烟/验收必须先拦截写请求（或用测试身份）。
- 可选加固（未做，需用户拍板）：增加「空值不覆盖」保护——只有用户在 UI 里明确操作才允许推送 `power.sel=""`，
  否则空值不写云端；代价是「一端取消关注、另一端也不再同步清空」的语义失效。当前云端 `power.sel=""`，
  用户需重选一次（或授权我写回 `4-23B---423` / 23号楼B座423）。

### 40.3 修复：趋势拖动到边界气泡被裁切/遮挡（2026-11-07 10:5x，用户上传 2.0.1 后反馈）

- 现象：小程序电费趋势拖动靠近左/右/上/下边界时，气泡内容被覆盖/裁切。
- 根因：拖动每一帧先按未 clamp 的命中点 `x/y` 渲染气泡，`createSelectorQuery` 实测回调返回前（连续拖动时更明显）
  气泡越出 `.pw-plot` 边界，被 `.pw-plot { overflow:hidden }` 裁掉；且气泡与 y 轴覆盖层 z-index 同级（3）存在遮挡风险。
- 修复：
  1. `utils/power.js` 新增 `estimateCursorTipSize(text)`；页面 `_showCursor` 先用「文字估宽 + `cursorTipLayout`」
     **预 clamp** 再 setData（首帧即不越界），实测宽高回来后再精修。
  2. `_placeCursorTip` 对「节点/尺寸未就绪（width/height=0）」延迟 80ms 重试一次；重试仍失败保留预 clamp 安全值。
  3. 气泡 DOM 从 `.pw-plot` 内移到 `.pw-trend-body` 内（绘图区外层），避开 `.pw-plot overflow:hidden`。
  4. `.pw-cursor-tip`: `z-index:4`（高于 y 轴 3）、`max-width:calc(100% - 44rpx)`、20rpx 字号 / padding 3rpx 12rpx，
     边界不裁字、不被坐标轴遮。
- 测试：unit 234/0、v3 45/0（新增 estimate 单测 + 左边界测量失败仍不越界 + 测量失败安全值 + 静态断言气泡在绘图区外层）、
  cache 18/0、sync 31/0、staticcheck 0、code_quality 通过；automator 未运行（无 9420 端口），需用户上传后真机/模拟器复核。
- 代码 `VERSION` 仍 2.0.0（用户微信后台上传版本 2.0.1 是另一套编号）；若需同步请用户拍板改成 2.0.1 / 2.0.2。

## 50. 水量页月份选择 UI 重做（2026-11-07 22:45，网页已上线 646,736B/`a5e3e151…`）

> 用户需求：「优化月份选择 ui，使页面更美观」。
> 基线：增量 22 版 621,560B / `e4b16188…`（在线；furina.fun DNS 当日暂停，线上校验走 OSS get_object）。

### 50.1 现状与方案

- 原「月份」= 原生 `<input type="month" id="wtMonth">`，**没有套站内 input 样式**（全局样式列表只有 text/password/date/time/number），
  桌面显示浏览器默认月历控件，与旁边「读数」输入框/整站暖白卡片不一致。
- 方案：保留 `#wtMonth` 作为**隐藏真实值**（保存/预览/测试契约不变），外加站内自绘控件：
  「‹ 月步进 › + 点开月网格弹层」；零依赖、原生 JS、无构建链、不引外部资源。

### 50.2 实现（`tools/index.html`）

| 区块 | 关键点 |
|---|---|
| CSS | `/* 月份选择 */` 段在 `.wt-form-row` 之后：`.wt-mctl`（42px 三段式）、`.wt-mbtn/{.wt-mico/.wt-mlabel/.wt-mchev}`、`.wt-mnav`、`.wt-mpop`（fixed, 296px）、`.wt-mgrid`（4 列）、`.wt-mo`（`.on` 选中 / `.now` 当前 / `.wt-mo-dot` 已有记录圆点）、`.wt-mquick` / `.wt-mynav` / `.wt-mclose` |
| HTML | `#wtMonthBtn`（aria-haspopup=dialog / aria-expanded / aria-labelledby）、`#wtMonthPrev/#wtMonthNext`（‹ ›）、`#wtMonthLabel/#wtMonthY/#wtMonthM`；隐藏 `#wtMonth`（`.wt-mnative`，tabindex=-1）；`#wtMonthPop`（`#wtMonthPopY` 年份、`#wtMonthYPrev/YNext`、`#wtMonthNow`、`#wtMonthClose`、`#wtMonthGrid`） |
| JS（WATER 内） | `monthParts/monthShift/syncMonthLabel/monthAvail/renderMonthGrid/positionMonthPop/openMonth/closeMonth/renderMonthPopYear/shiftMonthPopYear/setMonth/stepMonth/onMonthInput`；`syncDom` 同步标签+禁用态；`bind` 挂按钮/键盘/点外/滚动/缩放；`gotoTab` 切页收起 |
| 交互 | 选中月 `setMonth(ym)` 回写隐藏 input → 标签 → 预览；Esc 关闭并回焦；点空白关闭；方向键在月份间移动焦点；Enter/Space 选月（原生 button）；`aria-expanded`/`aria-current` 同步 |
| 禁用 | 未选关注宿舍：`#wtMonthBtn/#wtMonthPrev/#wtMonthNext` 与 `#wtMonth` disabled，弹层不可打开（`syncDom` 同步） |
| 响应式 | 401–480px / 960–1439px 窄列隐藏日历图标、收窄标签（触发内容零溢出）；≤480px 步进按钮 40px 可点区；≤400px 表单 1 列；≥1440 恢复图标 |

数据/同步：**完全不变** —— 仍只读写 `#wtMonth` 的 `YYYY-MM` 与既有 `water.rooms[rv].recs`；`D.save()`/UD v6 water section/LWW 合并均未改。

### 50.3 测试

- 新增 `tools/tests/v2_water_month_check.py` **41/41 PASS**：
  - 静态 6（DOM id / type=month 保留 / aria / CSS / WATER 方法 / 无构建链）；
  - 未选宿舍 4（默认当前月 / 三键禁用 / 点击不打开 / 0 报错）；
  - 控件+弹层 18（默认值&标签 / 隐藏 input 视觉隐藏&宽 1px / ≥40px 可点 / 12 月网格 / 选中&当前月 / 圆点=已有记录数 / 焦点 / 选月回写&联动&关闭&回焦 / 跨年 ‹ › / 上·下一年 / 本月 / 点空白 / Esc / 方向键 / 预览联动 / 保存用所选月 / set_input 兼容）；
  - 弹层视口 4（1280 完整在视口 / 390 不超宽 / 手机月按钮 ≥40 / 无横向溢出）+ 多宽度零溢出 1（360→1440）；
  - 切页收起 1 + 0 JS 报错/0 console.error/无外部请求 3。
- 回归：`water_check` **169/169**、`v2_water_layout_check` **29/29**、`v2_water_sync_check` **116/116**、`sync_check` **144/144**；截图 `tests/_water_shots/water_month_*.png`（控件/弹层 1280、弹层 390）。

### 50.4 上线 / 回滚

- **上线**：`index.html` **646,736 B · sha256 `a5e3e15148c40ed627f6776cc553ce955f7d35b6d95cbd3fdd641f1b6456ac9f`**；
  DNS 暂停期用 OSS `get_object` 校验：本地 = `tests/frozen/index_month_A5E3E151.html` = 线上（逐字节 MATCH）。
- **回滚**：`tools/_backup/index_online_20261107-2243_preMonthUi.html`（621,560 B · `e4b16188…`）→ `python deploy/sync_tools.py index.html`；
  本地补丁前备份 `tools/_backup/index_local_20261107_2243_preMonthUi.html`（= 当前版本逐字节副本）。
- APP_VER 仍 2.0.0；无新表/无迁移；绑定/UD 契约未变。
- ⚠️ 本版快照同时包含并行会话当日未部署 WIP（电费趋势节奏/气泡等，非本增量内容）：本增量只对水量页月份选择负责；水量门禁全绿。

### 50.5 已知限制

1. 月份只选「年 + 月」（年 2000–2100 钳制），不提供年份数字输入；要做「跳到某年某月」可再加年份输入（当前上一年/下一年点击即可）。
2. 弹层打开时页面滚动/窗口缩放会自动收起（fixed 定位防错位）；若后续要「滚动跟随」，需改为逐帧重算坐标。
3. 原生日历控件在移动端有系统月历；自定义后统一走自绘弹层，牺牲了系统无障碍月历语义（用 aria-haspopup/dialog/label/current 兜底）。

---

## 51. 电费趋势信息气泡「固定右上角」（网页 + 小程序同口径，2026-11-07 23:30，网页已上线 644,988B/`603c4e5d…`）

### 51.1 需求与结论

- 第一版按「气泡跟手」实现（22:50）后，用户 23:03 进一步要求：**气泡不要放在图内，固定显示在趋势图的右上角上部**。
- 本版按此定稿：气泡固定在趋势图右上角上部（区间按钮行右侧、**绘图区外**），气泡位置固定、不随手指/鼠标移动；
  竖线 + 圆点仍对准最近真实采样点，拖动时只更新竖线/圆点位置与气泡文字。
- 动因：气泡浮在图内/跟手时会遮挡曲线，且平缓曲线时几乎只左右滑。

### 51.2 网页实现（`tools/index.html`）

- DOM：新增 `.pw-trend-top` 包裹「区间按钮 `#pwRanges` + 气泡 `#pwDetailTip`」（气泡从 `#pwDetail` 内移出，位于绘图区上方）；
  `#pwDetail` 只保留竖线/圆点。
- CSS：`.pw-trend-top{display:flex;align-items:flex-start;gap:8px;margin:0 0 10px}`；`.pw-ranges{margin:0}`；
  `.pw-detail-tip{margin-left:auto;align-self:center;flex:none;max-width:calc(100% - 186px);position:static;
  text-align:right;white-space:normal;word-break:break-word}` + `[hidden]{display:none}`；删除 absolute/translate/below 变体；
  `.pw-trend-scroll` 恢复 `touch-action:pan-y`（不需要纵向跟手）；趋势卡加 `position:relative`。
- JS：删除 `POWER._ptr` / `placeTip` / `detailFromPoint` / `PW_TIP_GAP`；`detailSelect(idx)` 只更新竖线/圆点位置与气泡文字
  （`tip.hidden=false/true`）；`detailFromClientX` 恢复按 x 命中（不需要指针 y）；事件层只传 `clientX`；
  `renderTrend` 图例不再生成 `#pwDetailInfo`「查看 …」行（气泡常显后重复，删除）。
- 使用说明 `#s-ug` 同步：「气泡固定显示在趋势图右上角（不遮挡曲线）」。
- 窄屏：360px 时气泡在按钮行右侧折两行（行高不变、不压按钮）；390/1280 单行右对齐卡片内容右缘。

### 51.3 小程序实现（`mp-class-tools`）

- WXML：新增 `.pw-trend-top` 包裹 `.pw-ranges` + 气泡 `.pw-cursor-tip`（移出 `.pw-trend-body`，绘图区外）；
  气泡只显示 `{{cursor.text}}`，无定位 style。
- WXSS：`.pw-trend-top{display:flex;…}`；`.pw-cursor-tip{position:static;margin-left:auto;align-self:center;flex:none;
  max-width:60%;text-align:right;white-space:normal;overflow-wrap:anywhere}`（删除 absolute/transform/下方变体）。
- 页面：`cursor` 数据简化为 `{on,left,top,text}`；`_showCursor(frac)` 只 setData 竖线/圆点位置 + 文字；
  删除 `_placeCursorTip` / `_cursorSeq` / `_cursorPos` / `_plotTop` / `CURSOR_TIP_*` 与指针 y 传递；触摸取消逻辑不变。
- utils：移除跟手定位 `cursorFollowLayout`（已无引用）；旧 `cursorTipLayout` / `estimateCursorTipSize` 纯函数保留
  （历史单测覆盖，页面不再使用）。

### 51.4 验证

- 网页新增 `tools/tests/v2_power_tip_fixed_check.py` **21/21 PASS**：静态 4（气泡在 `.pw-trend-top`/不在 `#pwDetail`、
  CSS 非 absolute、`touch-action:pan-y`、JS 无跟手残留）+ 初始隐藏 / 点击显示 / 在绘图区上方且右对齐 / 与区间按钮不重叠 /
  竖直拖与左右拖气泡位置固定只换文案 / 点标题隐藏 / 360 折行不压按钮 / 1280 右对齐 / 空态隐藏 / 0 JS 报错；
  截图 `tools/tests/_shots_power_tip/`。
- 网页回归：`v2_power_detail_check` **30/30**（A5/A19 断言按新定位更新）、`power_check` **155/155**、
  `v2_power_cadence_check` **84/84**、`v2_power_slow_check` **45/45**、`v2_orient_power_check` **33/33**、
  `_qa_v2/delta_cursor_resize.py` ALL_OK、overflow 430 = 0。
- 小程序：新增 `tip_fixed_unit.js` **5/5 PASS**（已挂 `unit.js`）；`v3_power_diag_tests` **53/53**（v6/v7/静态断言按新设计更新）、
  `unit.js` **247/247**、`sync_contract_test` **31/31**、`staticcheck.py` exit 0、`code_quality_check.js` 通过。

### 51.5 上线 / 回滚

- 网页：**644,988 B · sha256 `603c4e5dd51a1cb3ede8d7f4b2c070c429013a533ae1281e0618b13f9948c69e`**（2026-11-07 23:21 部署；
  DNS 暂停期用 `deploy/oss_object.py get/sha` 校验：本地 = 线上逐字节 MATCH，线上含 `pw-trend-top` 且无 `placeTip`）。
- 回滚：部署前线上已备份 `tools/_backup/index_online_20261107-2321_preTipFixed.html`（646,956 B · `02bcc76f…`，含增量 25 与第一版跟手气泡）；
  回滚＝复制回 `tools/index.html` 后 `python deploy/sync_tools.py index.html`。
- 小程序：源码已改，**需用户在微信开发者工具上传发布后生效**；`VERSION` 仍 2.0.0。
- `APP_VER` / UD v6 / 导出 / 隐私边界均未改；无新表、无迁移。

### 51.6 副作用 / 已知限制

1. 气泡固定在趋势图右上角（绘图区外），不再跟随指针、也不再被曲线遮挡；拖动时只有竖线/圆点与文字变化。
2. 360px 窄屏气泡折两行（仍在区间按钮右侧、行高不变），390px+ 单行右对齐。
3. 图例行「查看 …」文字随本次删除（气泡常显后重复）。
4. 手机端趋势区纵向滑动恢复可滚动页面（`touch-action:pan-y`，与 2026-11-06 行为一致）。


## 52. 电费 13/16 号楼日更特异性统计（2026-11-07 23:05，网页已上线 646,956B/`02bcc76f…`；小程序待上传发布）

> 用户需求：「对 16 号楼和 13 号楼的电量统计做特异性功能优化，避免因统计频次的不同导致观感不佳和功能失效」。
> 规格（唯一口径来源）：`tools/tests/power_cadence_spec.md` v1（§1 公式 / §2 取数 / §3 UI / §5 fixture 期望 / §8 风险）。
> 独立验收：`tools/tests/_power_cadence_qa/REPORT.md`（PASS）。并发归属见 §52.7。

### 52.1 真实数据依据与根因

数据源 `public.power_history`（30 天保留）；只读探测脚本 `tools/tests/_power_freq/probe.py` / `eval_current.py`，产物 `freq_probe.json` / `eval.json`（2026-11-07 22:17–22:20 探测，窗口 11-05 22:45 → 11-07 22:01，共 47h）。

| 楼栋 | 47h 内真实数值变化 | 变化间隔 | 结论 |
|---|---|---|---|
| 13号楼（324/308）、16号楼（305/306） | 各 **1 次**（均 2026-11-06 09:46 同批；11-07 全天无变化） | — | 网关**日更/批量更** |
| 23号楼A座 / B座（抽样 4 间） | 各 **45–46 次** | 中位 **1.0h** | 网关**准实时（每小时）** |

现状 bug（真实数据复算，`eval_current.py`）：

1. **功能失效**：13号楼324 剩余 67.72 度、上次真实下降 11.25 度（≈1 天用量），「估算可用」却显示 **≥30 天**（24h 窗口无变化 → rate 被 0.05 下限兜底；7d 窗口把 47h 摊平）；13-308/16-305/16-306 同样显示 ≥30 天。
2. **观感不佳**：近 24h 趋势是一条水平直线；「近 24h 用电」tile 显示「—」；hero「更新 22:01」其实是同步时间，数值自 11-06 09:46 起未变（误导）；旧「数据更新较慢 · 上次变化…」长徽标只提示不修复。
3. 对照：23A/B 每小时都有真实变化，现有 24h/7d 双窗口估算工作正常，**口径与观感均不变**。

产品判断：13/16 号楼属于「按更新点统计」的慢频数据，应按真实更新点（change points）计算可用天数/日用量，更新/无更新状态如实展示；另加**通用有效性守卫**：窗口内真实用电为 0 时不再用 0.05 度/天下限伪造「≥30 天」，改为「数据积累中」（慢频房与正常房同规则）。

### 52.2 口径公式（规格 §1，web/mp 必须一致）

```
CH        = 0.005    // 数值变化阈值（与既有 slowInfo/slowUpdate 一致）
MIN_SEG_H = 6        // 有效用电段最短 6 小时（过滤同批抖动/短时修正）
EXPECT_H  = 24       // 13/16 号楼预期更新周期（小时）；仅「只有 1 段观测」时折算
SLOW_BLD  = ["13号楼","16号楼"]   // 楼栋级慢频配置（23A/23B 不在内）
```

- **`events(pts30)`**：按 t 升序，从首点起保留「与上一保留点 |Δq|>CH」的点 → 真实**变化点**序列；`lastChange` = 最后一个变化点（30 天无变化 → null）；`lastRecharge` = 最后一个 q 上升事件 `{t,reset}`。
- **`slowStats(pts30,rowQ)`**：相邻变化点 `dq=prev.q-cur.q`、`dtH`；`dq>0.05 && dtH>=6h` → 候选用电段；`dq<-0.05` → 充值/修正跳过；异常扣减剔除 `thr=max(5,4×中位数)`（水费从电费账户扣/异常大跌），`drop>thr` 段剔除。rate：0 段无效；**1 段** `dtH<36h` 按 `drop/EXPECT_H*24`（视为「1 个预期更新周期」的用量，ref=true）否则按观测间隔（ref=true）；**≥2 段** `Σdrop/ΣdtH*24` 时间加权（ref=false）。`days=rowQ/rate`；`valid = rate>0 && days 有限 && rowQ!=null`。
- **`isSlowRoom(rv)`**：楼栋 ∈ SLOW_BLD；当前 24h 缓存 `changesIn(pts24)>=6` → false（**数据覆盖降级**，网关提速后自动走实时口径）；其余 true。
- **`estimate()`（§1.4 通用守卫 / §1.5 选择）**：慢频 → `slowEst()`（30d 缓存未加载完 → valid=false）；实时房 → 24h/7d 分段 + 0.65/0.35 混合，两档都需 `used>0.05`，都无效 → `valid=false`（「数据积累中」），**有效时才应用 `rate=max(rate,0.05)` 下限**。
- 展示：days ≥30 → 「≥30 天」（上限 999）；ring 弧 = `max(0.02,min(1,days/30))`；无效沿用「数据积累中」/小弧 0.04。

### 52.3 网页实现（`tools/index.html`，行号以定稿 646,956 B 为准）

| 区块 | 位置 | 说明 |
|---|---|---|
| CSS | `.pw-cdot` L829-831 / `.pw-trend-note` L833-835 | 真实变化点圆点（白底+主色描边、`pointer-events:none`）；无更新提示（绝对居中、`pointer-events:none`、`z-index:7`，不挡点选） |
| DOM | `#pwTrendNote` L1533 | 趋势容器内提示层（`hidden` 控制） |
| 使用说明 | 电费句 L1687 | 「13/16 号楼网关日更，按真实更新点统计（趋势标『日更』），估算可能标『参考』，无更新会提示」 |
| 常量 | `PW_CH/PW_MIN_SEG_H/PW_EXPECT_H` L4326、`PW_SLOW_BLD` L4327 | 0.005 / 6 / 24；`["13号楼","16号楼"]` |
| 纯函数 | `eventsOf` L4474、`changesIn` L4483、`medianOf` L4492 | 变化点序列 / 窗口变化次数 / 中位数 |
| 慢统计 | `slowStats` L4497-4528 | 分段、异常剔除、1 段折算+参考、≥2 段时间加权 |
| 慢频判定 | `isSlowRoom` L4531-4537、`slowEst` L4539-4544 | 楼栋 + 24h 数据覆盖降级；30d 缓存未就绪 → 无效 |
| 估算 | `estimate` L4567-4595（函数 L4571） | 慢频分流 + 实时房 §1.4 守卫 |
| 取数 | `loadHist` L4601-4615、`pull` L4710-4743（30d L4721-4723） | 慢频房 3 窗口 / 实时房 2 窗口；切档补 30d；URL `limit=2000`、缓存 TTL 5 分钟、不插值 |
| 趋势 | `renderTrend` L4764-4873 | 「日更」chip L4776-4788；无更新提示 L4799-4805 + L4871-4873；平线居中 L4824-4829；阶梯线 L4831-4838；变化点 L4841-4849；y 轴单刻度 L4857-4865 |
| tile/hero | `renderTiles` L4915-4963；hero L4980-4988（赋值 L5012）；`data-cadence` L4991 | tile2「该区间无更新」L4926-4927、tile4 30d `lastRecharge` L4928-4929、参考 L4930；hero=lastChange /「近 30 天无变化」 |

- 行号以**部署对象 646,956 B** 为准（`tools/tests/frozen/index_cadence_02BCC76F.html` 同 sha）；若本地 `tools/index.html` 已被并行后续 WIP 改动导致行号漂移，按函数名/冻结副本核对。
- 慢频阶梯线只对慢频房（实时房仍 `M/L` 折线，避免无谓视觉变化与既有测试回归）；平线垂直居中 / y 轴单刻度为全房通用。
- 30d 采样量：当前 ~30–45min/条 → 960–1440 条 < `limit=2000`（规格 §2/§8）。
- 不改数据表/同步脚本/云函数/其它工具/导出/隐私；`APP_VER` 仍 2.0.0。

### 52.4 小程序实现（`mp-class-tools`，同规格同口径）

| 文件 | 位置 | 说明 |
|---|---|---|
| `utils/power.js` | 常量 L442-446 | `CH=0.005 / MIN_SEG_H=6 / EXPECT_H=24 / SLOW_BUILDINGS=['13号楼','16号楼'] / SLOW_COVER_CHANGES=6` |
| | `estimate` §1.4 守卫 L385-405（函数 L388） | 24h/7d `used>0.05` 才有效；两档无效 → valid=false |
| | `slowUpdate` L417 | 保留原字段，补 `lastChange/lastRecharge` |
| | `isSlowBuilding` L447 / `changesIn` L459 / `eventsOf` L466 | 楼栋判定 / 窗口变化次数 / 变化点序列 |
| | `slowStats` L481 / `estimateSlow` L523 / `isSlowRoom` L533 | 分段统计 / 慢频估算 / 楼栋+24h 覆盖降级 |
| | `noUpdateText` L539 / `stepSegments` L545 / `changeDots` L557 | 无更新文案 / 阶梯路径 / 变化点 |
| | `tilesOf` L569 / `trendLine` L622 | 慢频 tile（参考/该区间无更新/lastRecharge）/ 平线 |
| `pages/power/power.js` | `load` L333（30d 拉取 L330-344）、`pickRange` L203、`_renderData` L404（慢/实时分流 L417-419、hero 更新 L446）、`_drawTrend` L518 | 拉 30d（缓存 5 分钟、失败不阻塞其它窗口）；慢频估算分流；更新时间/日更徽标/阶梯线/变化点/无更新提示 |
| `pages/power/power.wxml` L66-67 / `power.wxss` L86 | 「日更」徽标与样式 |

- 不改 UD v6（`power={sel,at,low}`）、`VERSION` 2.0.0、分享/隐私；源码+测试完成，**需用户在微信开发者工具上传发布后生效**。

### 52.5 测试与证据

- **网页开发测试（本机实跑）**：`v2_power_cadence_check.py` **84/84**、`v2_power_slow_check.py` **45/45**、`power_check.py` **155/155**（仅 C 组 16-305 fixture/断言与 Q 组 23B-422 期望按新口径更新并注释）、`v2_power_detail_check.py` **30/30**、`v2_power_sync_hardening_check.py` **29/29**、`v2_orient_power_check.py` **33/33**、`water_check.py` **169/169**、`sync_check.py` **144/144**、`v2_ui_check.py` **27/27**、overflow 430=0。日志 `tools/tests/_power_cadence_work/logs/`；截图 `tools/tests/_shots_power_cadence/`（8 张：`cadence_s1_390.png`、`cadence_s2_390.png`、`cadence_s3_390.png`、`cadence_s3_7d_390.png`、`cadence_s5_30d_390.png`、`cadence_flat_30d_390.png`、`cadence_live_390.png`、`cadence_1280.png`）。
- **独立验收（`tools/tests/_power_cadence_qa/REPORT.md`，PASS）**：独立行为/视觉 **454/454**（`verify_cadence.py --tag after`，期望值 Python 侧按规格独立复算、不复用开发者断言）；真实数据 live **83/83**（真实 token 只读 CloudBase；导航前 `install_write_block`，6 个写请求全拦、无 PUT/PATCH/DELETE、token 仅内存不落盘）；静态契约 **27/27**；网页回归 **12/12**（含并集新增 `v2_water_month_check` 41/41、`v2_power_tip_follow_check` 18/18）；小程序 **6/6** + 独立复算 **90/90**。证据 `_power_cadence_qa/logs/`、`_power_cadence_qa/shots/`（`after_S1_324_430.png`、`after_S2_305_430.png`、`live_after_real_13-324_430.png` 等）。
- **修复前基线**（QA Phase A，621,560 B / `e4b16188…` 副本）：独立 suite 454 项 **PASS 275 / FAIL 179**（全部为规格要求修复点）；真实数据回放 13-324 ≥30 天 / ≈2.0 度/天 / 更新 11-07 22:01。
- **真实数据 live 验收（修复后）**：13号楼324 **≈6.0 天 / ≈11.3 度/天 / 参考 / 日更 / 更新 11-06 09:46 / 近 24h 无更新 / 平线居中 / 阶梯线 / ring 20.07**；13-308、16-305、16-306 均「数据积累中」（30d 无有效用电段；13-308 tile4 30d 充值 311.44、更新时间 11-06 09:46）；23A-321 保持 ≥30 天 / ≈2.5 度/天 / 折线 / 无日更。
- 说明：`v2_power_cadence_check`/规格 §5 的 S1 是 **mock fixture**（+11.25 度/11h → 折算 ≈7.9 天）；真实 live 数据是 30d 真实变化点 → **≈6.0 天**。两者口径同一、数据不同，均按规格验收通过。
- 证据路径说明：并集新增的网页气泡跟手专项脚本 `v2_power_tip_follow_check.py` 在 QA 时实跑 **18/18**（日志 `_power_cadence_qa/logs/regress_web_after_rerun.json`）；其后被并行会话后续新需求 WIP 取代，原文件归档为 `C:\Users\Ko_Li\.openclaw\workspace\archive\web_power_tip_work_20261107\v2_power_tip_follow_check.py.superseded`（属增量 24 文件，非本增量）。小程序侧该跟手版随后被增量 24 定稿替换：`tip_fixed_unit.js` 5 项（已挂 `unit.js`），页面/气泡改为固定右上角。
- **小程序测试**（`mp-class-tools-tests`）：`v3_power_diag_tests.js` **53/0（较基线 45 增 8）**、`unit.js` **254/0**、`sync_contract_test.js` **31/0**、`tool_sort_unit.js` **21/0**、`staticcheck.py` exit 0、`code_quality_check.js` 通过；automator `power_preview.js` **31/0**（0 console error），截图 `_shots_power_sync/09_daily_badge.png`、`09b_no_update.png`；日志 `mp-class-tools-tests/_power_cadence_work/FINAL_20261107-225104_*.log`。

### 52.6 上线 / 回滚

- **上线（2026-11-07 23:05）**：OSS `tool-furina-fun/index.html` = **646,956 B · sha256 `02bcc76f33cf6e762a8297238a725d8c059c55de84972c0c2a1ece895aadfd73`**；
  命令 `python deploy/sync_tools.py index.html`；`python deploy/oss_object.py check index.html` = **MATCH**（remote=local 646,956 B / 同 sha）；
  独立 `get` 取回对象字节存 `tools/_backup/_verify_online_02BCC76F.html`（同 sha）与本地逐字节相等；冻结副本 `tools/tests/frozen/index_cadence_02BCC76F.html`（同 sha）。
- 候选构成 = 部署前线上 646,736 B（增量 23/24）+ 本增量最后 **220B**「平线 y 轴单刻度」修复（646,956−646,736=220）。
- **DNS**：furina.fun 当前无 A 记录（备案暂停）→ 线上 URL 不可访问，**以 OSS 对象字节校验为准**；DNS 恢复后生效。
- **回滚**：`tools/_backup/index_online_20261107-2300_prePowerCadenceFinal.html`（646,736 B · `a5e3e151…` = 增量 23/24 线上对象，重传即回滚）；更早基线 `tools/_backup/index_online_20261107-2228_prePowerCadence.html`（621,560 B · `e4b16188…`，增量 22）；部署前本地备份 `tools/_backup/index_local_20261107_2305_final.html`（646,956 B）。
- `APP_VER` 2.0.0、UD v6、数据表/云函数均未改；无迁移。
- **本地工作副本提示**：部署时（23:05）本地 `tools/index.html` = 646,956 B / `02bcc76f…`；文档定稿时（23:1x）该工作副本已被**并行会话后续新需求 WIP** 继续修改（未部署、非增量 25 范围）。增量 25 的权威对象以 **OSS 对象 646,956 B / `02bcc76f…`** 及 `tools/tests/frozen/index_cadence_02BCC76F.html`、`tools/_backup/index_local_20261107_2305_final.html`（均同 sha）为准。

### 52.7 并发归属说明（重要）

- 同一台机器另一并行会话本轮已完成并记录：**增量 23** 水量页月份选择 UI（2026-11-07 22:45 部署，646,736 B / `a5e3e151…`）；**增量 24** 电费趋势气泡（最终定稿为「固定右上角」，2026-11-07 23:21 单独部署 **644,988 B / `603c4e5d…`**；小程序源码已改待上传；CHANGELOG / HANDOFF §51 / AGENTS §4b-16 / 验收报告均已写）。
- 本次增量 25 部署的是**并集快照（23 + 24 + 25）**；**本增量只对电费统计口径负责**，水量/气泡行为由对应增量负责。
- 并行会话的小程序气泡改动（增量 24：气泡固定右上角）与本次小程序慢频改动**共存**，mp 门禁全绿（`unit.js` 247/0 含两边用例）。

### 52.8 已知限制 / 后续

1. 13/16 网关实际更新时刻、是否仅工作日无法从 47h 完全确定 → 单段按预期 24h 折算并标「参考」；≥2 段后按真实间隔加权（含周末长间隔，不再依赖假设）。
2. 30d 窗口当前采样密度 960–1440 条 < 2000 上限，安全；若未来采样加密需再评估分页/上限。
3. 慢频房切 24h 档且无变化时图为平线 + 提示，这是如实展示；不自动改用户默认档位。
4. 实时房只在「窗口真实用电=0」时改显示「数据积累中」，其余算法/观感不变；23B-422 这类持平房从伪造 ≥30 天变为「数据积累中」（修复，非回归）。
5. DNS 暂停期线上校验走 OSS 字节比对；DNS 恢复后建议补一次 URL 可用性抽查。
6. 并行测试进程固定端口（8964/9464）残留曾导致 `v2_orient_power_check` 首轮 2 项假失败（QA §5.6 已定位非候选问题，复跑 33/33、整批 12/12 全绿）；建议后续测试统一 `free_port()`。
7. CloudBase 环境 2026-12-10 到期（旧话题，非本次；见 AGENTS §4b-13）。


## 2026-11-08 22:2x · v2.0.0 增量 26：诊断 v2（设备诊断 + 本机 AI 分析 + 白名单自动修复 + 全班可见）+ 课表登录（个人教务课表）

> 用户需求（2026-11-08 原话）：「1、电费趋势图的线会覆盖在宿舍选择框之上；2、优化诊断页面，加入对使用设备的诊断，检测到错误或异常后自动上传云端，由 ai 对服务进行扫描后给出可能错误原因，若问题出在云端且本机在线且为易修复的错误，则尝试调用本机进行直接修复，同时在诊断页给出对应流程提示，如为使用设备端问题则尝试扫描并同样给出修复建议，将诊断设为所有人可见；3、由于体育课每个人的课表可能不同，所以请给出登录入口，使课表与我不一样的人可通过登录自己的账号来获取自己的课表」。
> ③ 实测云端（上海）可访问学校统一认证/门户，但**访问不了校园内网教务 210.34.74.77** → 纯云函数代登录不可行；经用户确认改为 **A'：云收单（密码仅 PGP 密文）+ 本机代理（校园网执行 SSO/抓课表）**。
> 范围：网页 + 微信小程序 + 安卓 App 三端；本文件记网页侧。云契约见 `_diag_task/CONTRACT.md`、迁移 `deploy/cloudbase/2026-11-08_diag_login.sql`。

- **云端**（已应用；`apply_sql.py` 逐条走 ExecutePGSQL 原始 API，绕开 `tcb db execute` 的分号切分限制）：新表 `client_diag`（设备诊断上报，RLS：插入=本人 token sid、读=全班）、`diag_analysis`（AI 结论+flow，全班读/管理员写）、`repair_tasks`（本机修复记录）、`agent_keys`（本机 agent 公钥+心跳）、`login_jobs`（课表登录任务，密码仅 `pgp_pub_encrypt` 密文、用后清空）；RPC `tt_login_enqueue/tt_login_status/diag_agent_info`（SECURITY DEFINER）；`service_health` 读放宽为 `auth_ok()`（全员可见）。修正：`client_diag.sid` 默认 `auth_sid()`（客户端不传 sid 也能归属，真实云 201 实测 OK）。
- **本机 agent**（`C:\briefdesk\scripts\diag_agent.py`，计划任务 `BriefdeskDiagAgent` 每 1 分钟 `--once`）：心跳/PGP；`login_jobs` 认领→PGP 解密→纯 requests SSO（`web/jwxt/jwxt.py` 新增 `sso_login_http()`，`sync.py --check --refresh-sso` 实测 exit 0）→抓取解析→回写 `{c,t}` 并清空密码；`client_diag`+`service_health` → 本机 `cloud_ai.smart_json` 生成 `diag_analysis`（稳定 id 防堆行）；白名单自动修复（recheck_health/restart_gateway/web_pause_on|off/sync_power/sync_xgj/refresh_timetable/redeploy_web；≤3 条/轮、单动作超时 120s、同 analysis 不重复），flow 时间线写回。真实执行 `recheck_health` 成功并回写；诊断表中 0 明文密码/token/学号（已用真实班级 token 扫描校验）。
- **网页诊断页（#s-diag）**：去管理员门禁（所有已登录班级成员可见；门禁前 0 请求）；顶部本机 agent 在线状态；**设备诊断卡 10 项**（运行环境/屏幕+DPR/内存/本地存储/IndexedDB/网络/云端网关延迟/时钟偏差/课表快照/JS 错误数），异常自动+手动上报 `client_diag`（脱敏、fingerprint 10 分钟限频、单批≤3、门禁前不上报）；**AI 分析+修复流程**（`diag_analysis`+`repair_tasks`，15s 可见轮询，severity/cause/suggestion/fixable/action/status + flow 时间线 + 本机修完结果）；全局 `onerror/unhandledrejection` 自动上报；所有 detail/side/AI 文本经 `sensMask()` 脱敏（IP、C:\路径、URL、token=）。
- **网页课表登录**：`#tLogin`「登录教务」+弹层（学号默认身份 sid、密码 `type=password`、提交后立即清空、不入 localStorage/日志）→ `rpc/tt_login_enqueue`（X-Device-Id）→ 1.5s 轮询 `rpc/tt_login_status` ≤120s → done 写 `D.d.ttLocal={c,t}` 并走 UD v6 `tt.ttLocal` 同步 + 立即 `renderTT()`；错误码 agent_offline/rate/pwd/auth 分别提示；失败/超时保留公共课表；「清除我的课表」回退。`ttData()` 优先级改为 **个人 ttLocal > 公共（tt.json/site_assets）**（源标签「个人课表」）。
- **测试（全部本机实跑）**：新增 `tools/tests/v2_diag_v2_check.py` **165→130/130 PASS**（静态/未登录门禁/主流程/异常上报/全局错误/4 档布局；fetch 全 mock）、`v2_tt_login_check.py` **85/85 PASS**（成功/离线/失败/超时/清除/布局）；回归 `overflow_check 430`=0、`v2_ui_check` 27/27、`power_check` 155/155、`v2_tt_frame_check` **140/0 PASS**（其静止帧对照只比较 `.tthead` 以下课表主体，原因是本次 `.ttacts` 新增「登录教务」按钮；裁剪/泄漏/手感断言未改）。截图 `tools/tests/_shots_diag_v2/`、`_shots_tt_login/`（8 张，已逐张目检）。
- **上线（OSS 对象字节校验；furina.fun DNS 暂停期间 URL 不可访问）**：`index.html` **678,732 B · sha256 `e7b32ba4e7ba7e0be65c7a0ec34b1efe2b13d7ba9ac3ad66a04d64a23253b575`**（APP_VER 仍 2.0.0）；`python deploy/sync_tools.py index.html` 后 `python deploy/oss_object.py check index.html` = **MATCH**。部署前线上对象备份 `tools/_backup/index_online_20261108_2228_preDiagV2.html`（644,988 B / `603c4e5d…`）。回滚=重传该备份。**DNS 恢复后即生效**。
- **小程序/安卓**：同口径实现（详见 mp CHANGELOG / android `docs/DIAG_LOGIN_20261108.md`）；小程序源码完成待用户上传发布；Android 新增诊断页+登录弹窗。
- **安全/隐私**：教务密码只以 PGP 密文短暂存于 `login_jobs`，本机解密后仅内存使用并立即清空；诊断上报/展示均脱敏（无姓名/学号/宿舍/token/密码/URL/路径）；云表 RLS 仍以班级 token 为准（匿名不可读、匿名不可写）；未新增外部域名/构建链。

## 2026-11-09 14:0x · 通知优化：QQ 聊天记录里还有聊天记录（嵌套合并转发）展开

> 用户需求（2026-11-09 13:33）：「优化通知功能，对聊天记录中还存在聊天记录的情况做处理」。
> 现象：QQ 群转发的「聊天记录」里又套着「聊天记录」时，外层预览只有 `违规昵称#12138: [聊天记录]`，通知页出现一张摘要「收到一条聊天记录，原文未提供具体通知内容」的空白卡（样本 rowid=7706038317343250643，11-09 13:24 入库）。
> 范围：briefdesk 数据管线（**未改网页模板**；通知数据走云端 `public.notices`，sync 后即时生效，无需 OSS 部署）。

- **改动文件**：
  - `C:\Users\Ko_Li\.openclaw\workspace\briefdesk-plan\build_notice_board.py`：新增 `_qq_merge_*` 解析器与 `load_qq_merged` 嵌套展开；`expand_merged` 增加 ai_merged 缓存 hash 过期检测；`resolve_times` 对含「活动时间/签到时间/签退时段」的卡跳过 legacy 推断，交 `notice_time` 单一真源。
  - `C:\briefdesk\scripts\ai_brief.py`：`_MMDD_RE` 边界（防 `9:00-12:00` 的 `00-12` 被当日期）、`_abs_clock_text` 多时段/区间后半段不再乱插锚点日期。
  - `C:\briefdesk\scripts\notice_time.py`：`_DASH_DATE_RE` 加 `[:]` 边界（防时间区间被当日期）。
- **解析原理**：dbscan `--merged` 输出的 `40900 full` blob 里含内层 `<msg action="viewMultiMsg">` 卡片（title/tSum/preview）与其后内层消息元素（固定 marker `u_B-xbHgFtPzMTjvfvZNVuqw`：单出现=1 条，相邻两次=1 条）。按卡片顺序提取标题/预览/正文，清洗头像 token、二进制误码、`NTOSFull::` 本地路径、QQ emoji 后，替换外层 `[聊天记录]` 占位；抓不到内容时**丢弃占位卡**（不会把占位符当通知发出去）。
- **结果（14:00 重建）**：该记录 1 张空白卡 → **5 张真实通知**（c0 校园主持人大赛报名通知 / c1 气排球垫球挑战11-22举行 / c2 11-15校园拼贴诗活动 / c3 11-15三爱游园会报名 / c4 秋暮拾光校园随手拍征集），均含原文长文与 PDF 附件（`file` item，本地有文件时内嵌 data URI）；board 65 → **69 组**，其它 64 组 id 不变；时间仅 c1/c2 修正（c1 eventAt 11-09 17:00→11-22 09:00、c2 11-13→11-15 09:00，清掉错误 expireAt/timeLabel）。云端 `notices` 自动行 69/69 同步、无 `[聊天记录]`；桌面 demo 副本已刷新。
- **验证**：`v2_notice_data_check` 27 项 26 PASS（FAIL=D22 AI 要点≤6，存量：`g_qqm_7706037840253967598_c0`=8/`g_ait_30fbc46e20`=7）；`v2_notice_time_check` 62/72。**改前 13:40 基线 board/demo 复跑两套测试，失败项/数量完全一致** → 存量问题，非本次引入（日志 `C:\briefdesk\logs\_nestedfix_webtests.log`、`_nestedfix_baseline_tests.log`、`_nestedfix_webtests_final.log`）。独立复核（teammate `notice-reviewer`，task-1）确认：生产 69 组/新增 id 恰 c1..c4/0 处 `[聊天记录]`；其它 11 条记录语义不变；重建产物与线上逐组一致。复核发现的 3 个解析边界已修：深层嵌套回退预览过滤占位符、`QQ_EMOJI_RE` 误删 `/英文`（曾把「JPG/JPEG格式」删成「JPG」）、文件名行过度截断；修后重新聚类/摘要并复验（无重复日期、c4 原文完整、ai_brief 二次运行 changed=0 幂等）。
- **回滚**：`C:\briefdesk\data\_backup_nestedfix_20261109\`（改前 build_notice_board.py、qq-merged/board-data/ai-merged/ai-briefs/demo，以及 ai_brief.py/notice_time.py 的原片段，见 `ROLLBACK_NOTES.md`）。数据重建 + `sync_notices_cloud.py` 即恢复；无需 OSS/index.html 回滚（模板未动，index.html 仍 2026-11-08 22:27 / 691,488B / `46184aeb…`）。
- **已知限制**：① 嵌套展开依赖 40900 blob 内含内层卡片（QQ 未落盘时只能丢弃占位卡，不伪造内容）；② 微信合并转发嵌套未做（微信旧采集器当前未启用，无现状影响）；③ 新卡时间语义仍受 `notice_time` 多报名窗口/签退时段解析限制（c0 eventAt 取到选手报名 11-18、c2 deadline 取到签退 11-15 23:00、c4 deadline 取到报名开始——存量语义问题，复核列为后续观察项）。

## 2026-11-09 14:3x · 通知优化：文件/链接内容识别 + AI 动态分类（取消固定分类）

> 用户需求（2026-11-09 14:1x）：「对于文件类通知或通知中包含文件或链接的，要打开文件或链接识别具体内容再做整理；取消固定分类设置，由 ai 根据近期通知做灵活增添和删除分类，例如近期军训类通知较多便可在此期间自动添加军训分类」。
> 范围：briefdesk 数据管线 + web 通知模板（**模板改动，已重嵌/部署**）+ 父页编辑弹层 + 小程序 nt 页小幅加固（待用户上传发布）；安卓无需改。

- **新增/改动文件**：
  - 新增 `C:\briefdesk\scripts\content_extract.py`（文件/链接正文识别+缓存，pypdf 已装入 venv；PDF/docx/xlsx/pptx/旧 Office COM/zip/公众号/普通网页；SSRF 防护、12s 超时、2MB 截断、按内容/URL hash 缓存、7d TTL）。
  - 新增 `C:\briefdesk\scripts\attachment_digest.py`（汇总 board-data 的 file/link/archive 识别正文 → 本机 `data/content-digests.json`；每组≤3 来源/≤1600 字；本轮新抓取限额 8 URL/25 文件）。
  - `ai_brief.py`：make_prompt 增加「附件/链接已识别内容」块（≤1500 字），缓存 hash 纳入 digest（识别内容变化→重生成摘要）。
  - `detect_docs.py`：rebuild_board 在 fetch_qq_files 后跑 attachment_digest、ai_brief 后跑 ai_categories，最后统一 builder。
  - 新增 `C:\briefdesk\scripts\ai_categories.py`：AI 按近 7 天全部通知标题/摘要分类；上次分类+逐条归类进 prompt（防抖动）；新增/删除分类动态；缓存 hash 只看通知内容；AI 失败沿用旧缓存/旧规则兜底。
  - `build_notice_board.py`：`apply_categories()` + 模板动态分类（`catClass/catList/renderCatChips`、空 `#catRow` 换行、未知分类稳定 hash 取色、选中分类消失回「全部」、编辑下拉动态、`noticeSig` 含 cat）。
  - `index.html` 父页编辑弹层 cats 改为 `AUTO_NOTICES` 去重（修掉编辑「军训」通知会被覆盖成「教务」的问题）；重新 embed 并部署。
  - `ai_triage.py`：分类校验放开为 2~6 字任意名（不再限固定枚举）。
  - `mp-class-tools/pages/nt/nt.js`：分类色稳定 hash 兜底（与 web 同调色板）；刷新后当前选中分类消失时回「全部」（修复列表空白/无选中）。
- **结果（14:29 重建 / 14:46 稳定）**：69 组通知 **9 个动态分类**（活动 17/志愿 15/教务 11/运动会 8/班级事务 7/军训 6/招聘 3/宣传 1/团务 1）；**24 组通知、28 个来源获得识别正文**（PDF/docx/xlsx/公众号/压缩包/收集表），AI 摘要按真实内容补全（例：药膳策划书 PDF → 报名 11-07 12:00—18:00 精确写入；军训场地划分 xls → 主席台/跑道/各营人数；管院运动会 6 个收集表链接读到表名）；云端 notices 69/69 同步、无 `[聊天记录]`；识别正文只在本地 `content-digests.json`，不进 board-data/云端（独立复核 0 泄漏）。
- **上线**：`index.html` **693,068 B · sha256 `e1f0fccc0d78039744d9e7146c96d0528f7b2e2f6d1df21dc2e2f1aa7942b7f1`**（APP_VER 2.0.0）；改前线上对象备份 `tools/_backup/index_online_20261109-1431_preDynCat.html`（691,488B/`46184aeb…`）；`oss_object.py check index.html` = **MATCH**（DNS 暂停期以 OSS 字节为准）。小程序待用户上传发布。
- **验证**：新增 `tools/tests/v2_notice_dynamic_cat_check.py` **18/18**；`v2_notice_data_check` **26/27**（仅存量 D22，复核定位为 `notice_merge.py:302-307` 跨源合并后 aiPoints 并集>6，11-06 起既有）；`v2_notice_live_check` **16/16**；`v2_admin_check` **39/39**；`v2_ui_check` **27/27**；`overflow_check 430`=0；`_check_template_embed_match.py` = **YES**；`content_extract.py --selftest` **49/0**；mp `unit.js` 257/0、`node --check nt.js` 通过；`ai_categories`/`ai_brief` 二次运行 cached/changed 0（幂等），digest 重算 diff=0。线上 URL 因 DNS 暂停不可访问，`r3_notice_online_check`/`v2_notice_time_live_check` 无法跑（以 OSS 字节校验替代）；`r3_notice_online_check.py:213` 的 `==44` 已改 `>=44`（数据自然增长）。独立复核 `dyncat-reviewer`（task-2）**FAIL 0**，8 条 P3 中已修 3 条（收集表 realUrl 识别、分类名源头剔除 HTML 特殊字符、digest 新抓取 240s 总时间预算）。
- **已知限制**：无 OCR（图片型 PDF/纯图公众号仅标题）；腾讯文档/forms/sheets 仅标题（JS 渲染、无登录态）；SPA 页面空；识别正文仅本机使用；分类按 AI 判断可保留单条主题分类（「宣传」1 条）；AI 归类失败会被缓存到通知内容变化后才重试；小程序/安卓需各自发布/升级后看到新数据。
- **回滚**：线上重传 `tools/_backup/index_online_20261109-1431_preDynCat.html`；代码/数据回滚详见 `C:\briefdesk\data\_backup_nestedfix_20261109\ROLLBACK_NOTES_dyncat.md`。


## 2026-11-09 18:3x · 增量 27：诊断 v2.1（AI 下挂异常项/折叠展开/10s 进展/设备信息最小化）+ 本机 agent 开机补跑与无人工自动修复

> 用户需求（2026-11-09）：「ai诊断项目应放置在对应异常项目的下面且简化显示，详情可预留展开按钮查看，同时各个问题进展要及时更新，你要预留通道来在电脑开机期间及时自动修复，尽量去除人工部分，即使关机状态也应该对期间用户端报上的错误留存并在开机后尝试修复，设备信息应只保留可能出现错误导致无法使用的信息」。
> 契约 `_diag_task/CONTRACT_V2_1.md`（A UI / B 设备信息 / C agent / D 验收）。三端同做：本文件记网页与云端/本机；小程序 `mp-class-tools/CHANGELOG.md`、安卓 `android-class-tools/docs/DIAG_LOGIN_20261108.md`（待更新）另记。

- **网页**：`#s-diag` 删除独立 AI/修复大卡；`diag_analysis` 按 `related.health_ids` 挂服务健康异常行、按 `related.checks` 挂设备检查行；无关联进「其它诊断」默认收起。折叠一行 ≈34px（点 + 标题≤22 字 + ⚙可自动修复 + 状态胶囊 待处理/修复中/已修复/修复失败 + ›），展开 cause/建议/flow/关联修复。顶部摘要 `可自动修复 N · 已修复 M`。异常无 AI：在线→「AI 分析排队中…」、离线→「本机离线，已留存待开机修复」。轮询 15s→**10s**（可见时）。设备信息最小化：上报 device/detail 按 §B 白名单，`detail.check` 必带设备检查 id；展示 9 项且无 UA/语言/品牌/IndexedDB。
- **本机 agent v1.1.0**（`C:\briefdesk\scripts\diag_agent.py`，+569/−138）：catch-up（last_round 缺口>180s → 忽略冷却、积压 50、分析上限 20、修复上限 5，summary catchup/backlog）；自动修复扫描不依赖当轮 AI（new+fixable+cloud/mixed+error/warn；analysis 级 + action 级去重：同 action 30min 内 done 跳过、failed 6h 冷却）；修复前先写 running + flow run 步；`related.checks` 由 `client_diag.detail.check` 推导；分析输入设备白名单清洗；`recover_stale_running`（>10min 中断标 failed）；计划任务加 **LogonTrigger（登录后 30s）** 保留 TimeTrigger 1min/StartWhenAvailable；`--force-catchup` 调试。
- **验证**：网页 `v2_diag_v2_check.py` 140/140、`v2_tt_login_check` 85/85、overflow 430=0、`v2_ui_check` 27/27、`optim_v1_check` GREEN；本机 `test_diag_agent.py` 36/36、真实 `--once` catchup gap=600.2s backlog_diag=3 repair ok=1；生产任务自动 `refresh_timetable` 成功（running→done / analysis fixed / action 去重）；Lead 独立「暂停 75s → 恢复补跑」验证（new 留存 → backlog_diag=2、related.checks=['gateway']、analyzed）。小程序 `unit 259/0、v3 62/0、sync 33/0、automator 23/0`。
- **云端**：无 schema 变更；`client_diag` 旧测试行因 RLS 无 DELETE 只能置 ignored+清空（内容已空、ts=1，仅管理员本人自己的上报列表可见）。清理了 agent 自测 analysis/repair。
- **上线**：`index.html` **703,054 B · sha256 `6cef5da1…`（18:34 部署并校验 MATCH；18:35 并行会话在含本增量的文件上继续追加并部署 **730,113 B / a7b26001…**，已核验远端仍含本增量 v2.1 标记——线上现为 730,113 B）**；部署前线上对象 693,068 B/e1f0fccc（并行会话 OPTIM V1，已随本次上线，其测试 GREEN）；备份 `tools/_backup/index_online_20261109_1835_preDiagV21.html`；`oss_object.py check` MATCH。DNS 仍暂停，恢复后生效。
- **已知限制**：`client_diag` 无 DELETE RLS（历史测试行只能 ignored）；WXML 嵌套数组 `.length`/`wx:for` 在部分基础库不可靠 → mp AI 展开体的建议/flow 由 JS 预渲染字符串（`suggestionsText`/`flowText`，`white-space:pre-line`）；agent action 去重窗口 30 分钟（同 action 之后可能再执行一次，均幂等）；`catch-up` 依赖 state 缺口（真正关机/睡眠 >180s 才触发）。

## 2026-11-09 18:40–19:00 · 通知质量优化第二轮（AI 质检 / 自动过期 / 多报名窗口 / 附件补链 / 分类阈值 / 去噪）

> 用户 18:34 六条反馈：① 只有大量同类通知才新建分类；② 11-04~06 观赛安排、11-06 赛程名单等应在 6 号后过期；③ 河洛夜市 11-20 报名截止被识别成开始；④ 成绩认定 11-11 截止附件未识别；⑤ 小儿体质活动 3 个报名时间需特殊优化；⑥ 无内容/非通知清理，AI 质量最优化（成本不计）。
> 本轮叠在当日 18:3x「体验优化 V2」之上，未改动其网页功能；小程序/安卓无需改。

- **新增 `C:\briefdesk\scripts\ai_quality.py`**：逐条 AI 质检/校正层（原文全文 ≤2600 字 + 附件识别正文 ≤1400 字），输出 `isNotice/dropReason/confidence`、`deadline/eventAt/signupStart/signupEnd/signupWindows`、`points`、可选 title/summary、`expired/expireAt`；`data/ai-quality.json` 按组内容 hash 增量缓存；AI 失败不覆盖旧结果；**判「不是通知」的旧结论会保留**（防 triage 每轮重新产出）。`detect_docs` 顺序：builder → digest → triage/media → ai_brief → **ai_quality → builder** → ai_categories → builder。
- **builder `apply_quality()`**：在第二次时间归一之后、人工补丁之前套用：丢弃置信度≥0.7 的非通知；写入时间/`signupWindows`/要点；过期统一写 `eventAt`+`expireAt`（旧客户端天然显示过期）；纠正时间时清 `timeLabel`。模板 `statusOf` 增加 `g.expired` 分支 + `signupWindows` 按当前时间动态取当前/下一报名窗口（展示子活动 label）；`sync_notices_cloud.compact_group` 增加 `signupWindows` 下发。
- **分类阈值**：`ai_categories.py` `MIN_NEW_CAT=3` + `repair_small_new_cats()`（<3 条分类让 AI 并入已有大分类，失败归「其他」；缓存碎片类也会整理）。现 66 组 7 类：活动18/志愿14/教务12/运动会8/班级事务7/军训4/招聘3（宣传/团务已并入）。
- **微信附件补链 + rar 内容识别**（teammate `wxattach-dev` 实现，Lead 复核）：`wechat_media.py`/`ai_triage.py` 从 rawContent appmsg 解析无 media 字段的文件消息；`qq_file_names._EXT_RE` 加 rar/7z 让 builder 识别压缩包；`archive_scan.py` 7z `-sccUTF-8` 修中文名、解压后识别内部 docx/xlsx 文本、修 `w14:paraId` 残渣；`attachment_digest.py` 压缩包 `aiPoints` 入 digest、URL `html.unescape`。→ 成绩认定 rar（1.8MB/2 docx）已挂到通知，AI 以附件为准把截止从 11-11 改为 **11-13**。
- **结果**：33 组可见历史通知按期过期（AI 判 34 组、其中 1 组同时被判非通知剔除；含 11-04/05/06 项目名单、11-04~06 观赛安排、11-06 赛程）；河洛夜市 `deadline=11-09 22:00 报名截止`、无 signupStart；小儿体质 `signupWindows` 3 窗口 + 要点三日期 + 状态按当前窗口动态显示「报名开始/报名截止」（chip 不带上限标签，符合 A7 契约）；剔除 5 条非通知/无内容；公众号链接补识别；`content-digests` 仍只在本机不进 board/云端；云端 notices 66/66、7 类分布一致。
- **上线**：`index.html` **731,777 B · sha256 `c21787b9…`**（模板 b64 100,044→101,036 字节；重嵌后部署，OSS check MATCH）。改前线上对象备份 `tools/_backup/index_online_20261109-1910_preWindowFix.html`（731,593B / `4407ae6f…`）；更早 `...1907_preLabelFix.html`（731,729B/c0a38b8a）、`...1854_preQualityExpire.html`（730,113B，当日 V2）；`APP_VER` 仍 2.0.0。
- **验证**：新增 `v2_notice_quality_check.py` 16/16；`v2_notice_dynamic_cat_check` 18/18、`v2_notice_data_check` 27/27（存量 D22 转绿）、`v2_notice_live_check` 16/16、`v2_admin_check` 39/39、`v2_ui_check` 27/27、overflow 430=0、template embed MATCH；`detect_docs.py --rebuild` 端到端 exit 0 且幂等（quality called=0 / categories cached / 66 组稳定）。顺带修 `detect_docs.py` 控制台 cp936 遇 emoji 标题崩溃（stdout UTF-8 replace）。
- **已知限制**：公众号文章部分需微信环境验证（仅标题/极短正文）；无 OCR（纯图片通知仍会丢弃或仅标题）；多报名窗口「动态当前窗口」为网页端能力，小程序/安卓用构建时首个窗口/跨度兜底；分类阈值会随通知自然增删；小程序/安卓需各自发布/升级。
- **回滚**：线上重传上述备份；代码/数据见 `C:\briefdesk\data\_backup_quality_20261109\ROLLBACK_NOTES_quality.md`。

### 19:32 · 分类再优化（全部过期的分类不单独展示，用户 19:29）
- 模板 `catList()` 只保留「至少一条未过期通知」的分类；`renderCatChips()` 未过期分类为空时隐藏整行；过期卡片徽标保留、仍在已过期区。小程序 `nt.js` 的 chips 同步过滤 `g.expired`（待用户上传）。
- 效果：当前「运动会」8 组全过期 → 不再单独展示；军训/招聘仍有未过期通知则保留。
- 上线：`index.html` **732,317 B / sha256 `26684487…`**（OSS MATCH）；备份 `tools/_backup/index_online_20261109-1932_preExpiredCatHide.html`（731,777B/c21787b9）。
- 验证：quality **17/17**（新增 Q16）、dynamic 18/18、data 27/27、live 16/16、admin 39/39、ui 27/27、time 64/72（存量 8）、overflow 0、模板嵌入 YES；mp 259/0。

### 19:55 · 过期判定补强（无具体时间 / 已处理过期 / 招聘分类）
- `ai_quality.py` 规则：无明确日期时按消息时间+上下文判断；一次性事件（招聘/宣讲/比赛/会议/培训/报名）消息 >2 天且无未来安排 → 过期；结果/名单/录取公布、活动已办等 → 过期；长期资料不算。重跑 66 组过期 34→40。
- 模板 `statusOf()`：**先判过期再判已处理**，done+expired 进「已过期」区；分类 chips 继续按「有未过期通知才展示」。
- 当前 5 类：教务/活动/班级事务/志愿/军训；「运动会」「招聘」全部过期已消失（过期卡片保留徽标+过期区）。
- 上线：index **732,621 B / sha256 `65610511…`**（OSS MATCH）；备份 `tools/_backup/index_online_20261109-1959_preDoneExpired.html`（732,317B/26684487）。
- 验证：quality **20/20**（Q17/Q18/Q19 新增）、dynamic 18/18、data 27/27、live 16/16、admin 39/39、ui 27/27、time 64/72（存量 8）、overflow 0、模板嵌入 YES。

> 19:10 补丁：signupWindows 在「窗口已开始但无结束时间/全部结束」时不再返回无时间的「报名中」，继续走 deadline/eventAt 逻辑（修 `v2_notice_time_check` A7 chip 契约）；三窗口仍由 `signupWindows` + 要点体现。最终线上 731,777B/`c21787b9…`；time 测试 64/72（基线 62/72，剩余为存量花名册/献血）。


## 2026-11-09 22:0x–23:0x · 增量 28：PPT 演示（三端同步上线；网页已部署 / 小程序待用户上传 / 安卓 APK 已交付）

> 用户需求（2026-11-09 原话场景）：教室电脑老旧，PPT 动画多时常常无反应；在自己电脑能播的嵌入视频移到班级电脑显示「媒体不可用」。
> 希望「可在任意设备上完整流畅播放 PPT」的、任何人可上传的播放工具。三端同步上线。
>
> **方案**：上传端只传源文件；家里电脑的「转换机」（Windows + Microsoft PowerPoint COM）一次性把 PPT 渲染成
> **分步图片**（每页 + 每个点击动画步）并把**嵌入视频/音频抽出来转成 H.264/AAC**；三端只加载图片/MP4 → 老电脑也秒开、
> 视频不再依赖 PowerPoint 解码器。清单与状态走 CloudBase PG（现有班级 token RLS），媒体资产走阿里云 OSS（公共读、内容哈希路径、长缓存）。
>
> **唯一契约**：`web/ppt/CONTRACT.md`（表/RLS/接口/manifest v1/播放语义/三端要求/红线）；**设计参考**：`web/ppt/DESIGN.md`
> （19 个竞品拆解 + 三端交互规格 + 微信域名/WebP 技术查证）；转换机运维：`web/ppt/README.md`。

### 云端（已应用）
- 迁移 `deploy/cloudbase/2026-11-09_ppt_decks.sql`（`apply_sql.py` 逐条 ExecutePGSQL）：`public.ppt_decks`（22 列：
  状态 `uploading→queued→processing→ready/failed`、`progress/error`、源文件信息、`manifest jsonb`、`deleted` 软删等）+
  `public.ppt_upload_chunks`（`(deck_id,idx)` PK、512KiB 原始字节/片 base64、转换完即删）。
- RLS：decks 读 `auth_ok()`（全班共享演示库）、写本人 `owner_sid=auth_sid()`、转换机管理员 token 可更新任意行；chunks 本人
  SELECT/INSERT/UPDATE(upsert)/DELETE、管理员可读删；匿名读 `[]`。**无 DELETE 给 decks**（删除=软删）。
- 转换机心跳复用 `public.site_assets` 行 `id='ppt_agent'`（`body={online,seen_at,queued,version,host}`；客户端 `seen_at>180s`
  显示「转换机离线 · 排队中」，不报错）。CLOUDBASE.md 已补章节。
- OSS 布局：`ppt/a/<deckId>/<buildId>/`（`s{页}-{步}.webp` 1600 宽主图 / `t{页}.webp` 400 缩略图 / `m{n}.mp4|.m4a`）+
  `ppt/src/<deckId>/source.<ext>`；`Cache-Control: public,max-age=31536000,immutable`；直连域名
  `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/`（不依赖暂停中的 furina.fun DNS）。

### 转换机（本机，已装好并启用）
- `web/ppt/`：`pptx_xml.py`（纯函数：sldSz/页序/媒体+xfrm 归一化/切换映射/step 规划降级/manifest 校验/buildId）、
  `convert.py`（PowerPoint COM：忙检测、可见性快照分步导出、字节去重、页 step≤12/整图≤260 降级、`SaveCopyAs` 媒体抽取、
  ffmpeg H.264/AAC `faststart`、Pillow WebP 主图≤200KB q72→q62 / thumb≤25KB、manifest+buildId）、
  `agent.py`（队列轮询/条件认领/分片拼装/OSS 上传/心跳线程/token 过期自动刷新/单实例锁/进度 PATCH/中文失败 error/日志脱敏）、
  `oss_upload.py`、`install_agent.ps1`、`README.md`（运维手册）、`tests/`（fixture 生成 + 纯逻辑 51 + COM 集成 13 + 云端契约 7）。
- **计划任务 `PptConvertAgent`**（系统 pythonw `C:\Users\Ko_Li\AppData\Local\Programs\Python\Python312\pythonw.exe`、
  Interactive only（COM 必须桌面会话）、每分钟 + 登录后 30s、StartWhenAvailable、IgnoreNew、单实例、ExecutionTimeLimit 20min）。
  已 `-NoRun` 注册 → Lead 已 `schtasks /Change /ENABLE` 并实测：22:59 计划任务真实消费 queued deck（6 页/7 步/13 资产）→ PATCH ready，
  `Last Result=0`。运维：`schtasks /Query /TN PptConvertAgent /V`；暂停=`schtasks /Change /DISABLE` 或建 `web/ppt/ppt-agent.pause`；
  日志 `web/ppt/logs/agent-YYYYMMDD.log`；单次 `python web/ppt/agent.py --once`；指定 deck `--deck <id>`。
- 安全/健壮性：用户 PowerPoint 有打开文档时本轮跳过（不打扰编辑）；失败 PATCH `failed`+中文≤300 字+清 chunks；token/密钥绝不落日志；
  修复了 PowerPoint Quit 后 COM 释放偶发 60s 卡顿（Close→释放引用→Quit→CoUninitialize，连续 6 次 4.4–4.9s、无残留进程）。
- **取舍（如实）**：分步图取「每步最终视觉态」→同段逐字出现会合并、强调/运动路径取快照、自动动画（afterPrevious/withPrevious）
  合并为当页最终态（内容不丢）；外链媒体跳过并 warning；隐藏页仍转换；单 deck ≤64MiB/≤300 页/图 ≤260/页 step ≤12；
  媒体 ≤200MB/总时长 ≤30min（超出截断/跳过）；重转换旧 buildId 目录不自动删。

### 网页（已部署）
- `tools/index.html` 732,621 → **800,243 B**（sha256 `4412f5fc…`）：CSS `/* __PPT_FEATURE_V1__ */` 187 行（`</style>` 前）+
  `<section id="s-ppt">` 26 行（`#s-all` 前）+ JS 1,255 行/96 函数（OPTIM V1 块前）；站点其它逻辑只 4 处挂钩
  （TOOLS 一项、gotoTab 两行、滑动引擎 resolveStart 排除 `#pptPlayer` 一行）；`APP_VER` 仍 2.0.0、无外部依赖/密钥。
- 列表（暖白卡片/状态胶囊/离线提示/空态/骨架）、上传（File.slice 512KiB→base64 并行≤4 重试2 退避 400/1200ms、PATCH queued、
  取消软删、>60MiB 拒绝）、10s 可见轮询+心跳同轮；全屏播放器（页码按页/顶部进度按 step/步点 step≥2；点击 2/3-1/3、鼠标拖、
  触摸滑、键盘全套；控制条单行 3s 自动隐藏、B 黑屏、缩略图/备注抽屉、视频热点点击才播且不随 step 卸载、站内退出确认、
  全屏 API+沉浸降级、预加载后 2 张/释放旧图/低端 fade 降级）。
- 专项测试 `tools/tests/v2_ppt_check.py` **86/86**（CDP Fetch 只 mock ppt 三路径 + 假 token，0 真实云端写；430px 无横向溢出；
  播放器手势不切工具）；回归 `overflow_check 430`=0、`v2_ui_check` 27/27、`v2_pos_restore_check` 12/12、`v2_drag_check` 56/56、
  `optim_v1_check` 14/14、`v2_x5_anim_check` 28/28。
- **上线**：2026-11-09 23:04 `deploy/sync_tools.py`；`deploy/oss_object.py check index.html` = **MATCH**
  （远程 800,243 B/`4412f5fc…`）；DNS 暂停期以 OSS 对象字节为准，恢复解析后生效。备份
  `tools/_backup/index_online_20261109-2220_prePPT.html`（732,621 B/`65610511…`，回滚用）。
- **真实端到端（Lead，独立于实现者的测试）**：headless Edge + 测试身份真实 token（`_cloud_guard` 阻断所有云端写）+
  真实云端 deck + 真实 OSS 资源：桌面 1280×800 与 430×900 触摸两套，16 页逐页/键盘/点按/滑动/缩略图/备注/黑屏/退出确认全 PASS，
  含视频 deck（`dtestvidspc2gii79oz4`）热点点击后 `<video>` 真实播放（`paused=false,dur=3,w=640,h=360`）、4:3 deck letterbox 正确，
  0 console/exception。截图证据 `tools/tests/_shots_ppt/`（实现者 15 张）与 Lead 临时 E2E 截图。
- **真实浏览器上传闭环（Lead，第二套独立 E2E）**：headless Edge 真实 UI 选文件（55KB PPT）→ 真实分片上传 → `queued` →
  计划任务转换 `ready`（6 页/7 步）→ 播放器真实打开播放 → 自动软删测试行；仅放行 ppt 两表写、其它云端写阻断，页面 0 错误。
  脚本留档 `web/ppt/tests/e2e_web_real.py`（真实 deck 播放：桌面/手机/视频/4:3）与 `web/ppt/tests/e2e_web_upload.py`（真实上传）。

### 小程序（源码完成，待用户上传发布）
- 新增 `utils/ppt.js`（§4 全部接口 + 512KiB 分片读取/base64/并发≤4/重试/进度/取消 + manifest 归一化/URL/step 导航纯函数）、
  `pages/ppt/{js,wxml,wxss,json}`（列表+上传，23KB）、`pages/pptplay/*`（全屏播放器 38KB）、`images/tool-ppt.png`；
  `app.json` 注册 2 页（23 页，未改 tabBar）；`utils/tools.js` 目录末尾加「演示」；`utils/cloud.js|cloud-config.js` +2 表名/+通用
  `cbDelete`；版本 `utils/version.js` 仍 **2.0.0**。
- 关键实现：聊天记录选 `.ppt/.pptx`（唯一入口）→ 占位卡片先行 → 分片上传 → queued；状态胶囊/离线横幅/取消/重试/删除/重命名/下载原件；
  10s 可见轮询/onShow 强拉；播放器（custom nav + `pageOrientation:auto` + disableScroll；点击 2/3-1/3、左右滑、后退=step、
  控制条自动隐藏、缩略图/备注抽屉、黑屏、`<image webp="{{true}}">`、媒体热点点击才播不随 step 卸载、退出释放）。
- 测试：`ppt_unit_tests.js` 38/0、`unit.js` 297/0、`sync_contract_test.js` 33/0、`tool_sort_unit.js` 21/0、
  `staticcheck.py` exit 0（23 页）、`code_quality_check.js` exit 0。
- **用户需做（发布前）**：微信公众平台把 `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com` 加入
  **request 合法域名 + downloadFile 合法域名**；OSS 防盗链放行空 Referer 与 `servicewechat.com`（当前 bucket 无防盗链、
  allow_empty_referer=true，已实测）；**真机正式版**验一张图 + 一段视频（香港 OSS 默认域名能否过微信校验未查证）；
  之后在开发者工具上传发布。代码版本仍 2.0.0。

### 安卓（已构建 APK，待用户安装）
- 新增 `data/ppt/`（容错模型/解析、§4 全部接口、分片上传器≤4 并行/重试/进度/取消、SAF Uri 分片源、自建 OkHttp+BitmapFactory
  WebP/LRU 图片加载）、`features/ppt/`（URL/step 导航/状态文案/分片计划/列表过滤/播放逻辑，纯 Kotlin 可单测）、
  `ui/screens/ppt/`（列表+沉浸式播放器，VideoView+MediaController 热点、音量键±翻页、缩略图/备注抽屉、黑屏、转场保守淡入）、
  `ui/preview/PptPreviews.kt`；注册 `ToolCatalog(id=ppt,「演示」)`、`Routes.PPT_PLAYER`、`MainNavHost`、`AppContainer`、`MainActivity` 音量键。
- 版本 **3.3.0 / versionCode 9**；无新增第三方依赖。验收：`:app:testDebugUnitTest` **904/0**（新增 PPT 87，原有 817 全绿，无回退）、
  `assembleRelease` BUILD SUCCESSFUL；APK **2,692,174 B**，sha256 `B4E88732…9459BF2B`，apksigner v2 通过；
  artifacts：`artifacts/classtools-3.3.0-release-signed.apk` + 5 张 Compose 预览 PNG（列表全状态/空态/16:9/4:3/深色）。
  交付由 Lead 统一复制到桌面。

### 独立验收（QA，另 agent）
- 报告 `web/验收报告/PPT演示_独立验收_20261109.md`（31.5 KB）：功能验收 **PASS**；脚本断言合计 **1,574 项 / 0 失败**
  （网页 86/86 + 真实 E2E 3/3、回归全绿；小程序 38/0+297/0+33/0+21/0+staticcheck/code_quality exit0；安卓 904/0；
  转换机 51/51+13/13+7/7+计划任务真实运行；DB 只读 RLS/列校验）。唯一 P0「网页未部署」已由 Lead 23:04 部署消除；
  剩余 P2：播放器封面阶段页码占位 1/1（瞬态）、云端测试数据交付前清理、`site_assets.ppt_agent.updated_at` 不随心跳刷新
  （客户端用 body.seen_at，不影响）、mp 顶部按钮文案「上传」vs 契约「上传 PPT」、安卓仅 fade 转场（契约允许）。
- 未验证（如实）：微信真机域名白名单/真机 WebP、安卓实机安装与预览渲染之外的交互、生产域名 CORS（DNS 暂停期）、
  真实用户账号上传→转换→播放（用测试身份完成，等价链路）。

### 回滚 / 清理
- 网页：重传 `tools/_backup/index_online_20261109-2220_prePPT.html`；转换机：`schtasks /Change /TN PptConvertAgent /DISABLE`；
  云端表可保留（无数据即无影响）或 DROP `public.ppt_upload_chunks`、`public.ppt_decks`；小程序/安卓回退到上一版源码/APK。
- 交付前已清理：测试身份产生的演示行全部软删、分片清零、OSS 测试前缀（`ppt/a/dtest*`、`ppt/a/dd3xpuazwls`、`ppt/src/*`、
  `ppt/probe/`）删除；`web/ppt/work`、`tests/_out`、`__pycache__` 等过程产物清理（fixture 可用 `tests/make_fixture_pptx.py` 重生成）。

## 2026-11-10 07:4x · 仓库规范化：GitHub + Gitee 双远端确认与同步流程（当前会话）

> 用户 2026-11-10 07:24 要求：确认已配置好的 Gitee / GitHub，把项目规范化，以后每次修改都要同时上传两个远端并附说明。

### 配置确认（实测）
- `origin` = GitHub `Link0Kong/class-tools-site`（**Private**，默认分支 `master`，推送凭据 = `gh auth` keyring token）；
  `gitee` = Gitee `ko_Link/class-tools-site`（**私有**，推送凭据 = `credential.helper=store` 的 `C:\Users\Ko_Li\.git-credentials`）。
- 实测：`git ls-remote origin/gitee refs/heads/master` 均成功、`git push --dry-run` 两端通过；本地 `master` 与两端已对齐。
- **已知环境问题（如实）**：本机到 `github.com:443` 偶发 `Recv failure: Connection was reset`（`api.github.com` / `gh` 正常、时好时坏），
  因此同步脚本内置 3 次自动重试；仍失败时隔 1–2 分钟重跑同一条命令即可（提交已在本地，不会产生空提交）。

### 本次规范化内容
1. 新增根 `README.md`：项目入口（远端 / 目录 / 交付流程 / 安全红线 / 当前状态）。
2. 新增 `sync_repos.py` + 重写 `sync-repos.cmd`：安全检查（敏感路径 / GitHub 令牌 / 私钥 / AccessKey / 明文 DB 密码）
   → `git add -A` → commit（无改动跳过）→ 推 GitHub → 推 Gitee → `ls-remote` 核对两端 HEAD 与本地一致；
   支持 `--check` 只核对；网络失败自动重试；UTF-8 输出。
3. `SYNC.md` 重写：双远端流程、说明规范、验证命令、排障、`.gitignore` 约定。
4. `AGENTS.md`：`§0` 增加第 6 条「双远端同步」红线；`§4` 增加交付时附两端 SHA 的期望；两处失效的 `§5` 自检引用改为 `HANDOFF.md §5.2`。
5. `.gitignore` 补 `.zcode/`；新增 `.gitattributes`（图片 / Office / APK 标记 binary）；`.zcode/plans/` 工具过程文件移出索引（本地保留）。
6. `tools/tt.json` 课表快照（2026-11-10 06:42 教务同步）入库。
7. 旧交接文件加「历史存档」提示：`给ZCode的开场指令.txt`、`使用说明.txt`（部分账号 / 登录描述已过时，现状以 `AGENTS.md` / `tools/README.md` 为准）。

### 以后每次改动的硬性流程
```cmd
sync-repos.cmd "feat: 说明本次改了什么"
```
只推一个远端 / 不写说明 = 未完成交付；两端 SHA 以 `sync-repos.cmd --check` 为准。仓库保持私有。

## 2026-11-10 补丁（运维/跨端）：本机临时通道启动器健壮化 + 转换机缺片报错含「上传中断」

- `deploy/local_channel.py`：端口被占自动顺延（最多 +10）；目标端口已有本通道在运行则直接打开浏览器；`--open` 打开实际端口。
- `deploy/local_channel.cmd` 与桌面启动器：不再依赖 `where python`（资源管理器双击环境 PATH 可能找不到 Python），
  改为按常见绝对路径探测 Python312/313/py.exe；批处理改为**纯 ASCII + CRLF**（cmd 按 OEM 代码页解析，避免中文注释/换行造成误判）。
  实测：双击启动后 `http://127.0.0.1:8787/__chan/health` = 200。
- `ppt/agent.py`：分片缺失错误改为「上传中断：云端分片不完整（缺 N 片…请重新上传）」→ 网页/小程序「重试」
  按 `上传中断` 判定为**重新上传文件**，而不是把空分片的 deck 再次排队。
- 小程序端同日修复（源码在 `mp-class-tools/`，非本仓库）：基础库 3.17 起 `openSync(path,'r')` 旧签名失效，
  导致分片读取全部失败（上传必然中断）；改为 `readFile({filePath,position,length})` 优先 + `pickChunkBuffer` 旧库切片 +
  对象/旧字符串签名 `openSync` 回退，分片请求超时 60s；`tool-ppt.png` 图标改为 96×96 白色实心「演示屏+播放」（与其它工具图标一致）。

## 2026-11-10 21:0x–21:5x · 增量 30：PPT 演示 v1.2 高保真「原样播放」视频（转换机 + 网页/小程序/安卓）

> 用户反馈（2026-11-10 20:39）：「网络良好时达到电脑本地文件的播放效果；目前 PPT 内动画全部消失、视频依然无法播放、各端操作都不够便捷」。
> 方案：保留分步图片（弱网/精细翻页/热点播媒体），新增**原样播放**模式——本机 PowerPoint 直接导出**高保真视频**（入场/强调/路径动画、页切换、
> 内嵌视频+AAC 声音），三端网络良好时默认播放该视频；契约见 `ppt/CONTRACT.md` §11。

- **转换机**（`ppt/convert.py`/`agent.py`/`pptx_xml.py`/`oss_upload.py`/`install_agent.ps1`）：
  - 同一 PowerPoint 会话内：逐页算动画结束时间/媒体时长 → 设 `AdvanceOnTime/AdvanceTime`（保留原页切换）→ 对媒体形状强制 `PlaySettings.PlayOnEntry=True`
    （实测不设则导出的视频只有海报帧且无音轨）→ `CreateVideo(True, 5, 720, 30, 80)` → `>40MB` 用 ffmpeg 重编码（crf24/aac96k）否则 `-c copy -movflags +faststart`；
  - `manifest` 增可选 `video {s,w,h,dur,chapters:[{i,t}],q}`；章节公式 = `Σ_{j<i}advance_j + Σ_{j<=i}transDur_j`（实测 3 色页/真实 deck ±1s）；
  - 外链媒体（TargetMode=External）在临时副本上替换静态图后删除，避免 PowerPoint 导出时等待超时（用户 deck 第 7 页曾致 +87s）；
  - 失败/超时/>120 页/预估 >1800s 仅跳过视频并 warning，不影响分步 ready；新增 `--video-only` 从 `source_key` 补转存量 deck（只新增 video）；
  - 计划任务 ExecutionTimeLimit 改 **PT45M**（已重注册并启用；旧注册 PT20M 不会自动更新，需重跑 `install_agent.ps1 -NoRun -Disabled` 再启用）。
- **网页**（`tools/index.html`，847,026 B / `411354e1…`，APP_VER 仍 2.0.0；已部署 OSS）：
  原样播放（默认网络良好 + 自动播放；控制条：播放/暂停、mm:ss、章节上/下页 seek、章节刻度进度条、倍速 1×/1.25×/1.5×/2×、全屏、下载视频、模式胶囊）；
  续播 localStorage（7 天）、列表「继续」徽标/整卡点播/「原样 m:ss」胶囊；分步热点时序 race 修复（img load/transitionend/resize/rAF 补算，64px+视频时长角标+脉冲）；
  视频 error/卡顿自动回退分步 + toast；键盘 Space/←→/F/Esc/M；左右滑=章节、点舞台显隐。专项 `v2_ppt_video_check.py` **99/99** + 原 86/86；回归全绿。
- **小程序**（源码在 `mp-class-tools/`，非本仓库；VERSION 仍 2.0.0）：原样播放 + 章节/倍速/续播/列表「继续」；降级链
  `<video src=OSS>` → `wx.downloadFile` 临时文件播放（进度、看门狗、可 abort）→ 自动分步；`unit 337/0`、`ppt 40/0`、`sync 33/0`、`staticcheck/code_quality` 0、automator **38/0**。
  **真机需用户在微信后台把 OSS 域名加入 request+downloadFile 合法域名，并上传发布后真机验图/视频**。
- **安卓**（3.4.0 / versionCode 10）：`PptVideoPlayer`（MediaPlayer+SurfaceView 自建控制条/章节 seek/倍速/下载/续播/网络降级）；`testDebugUnitTest` **954/0**、`assembleRelease` 成功，
  APK 2,724,998 B / sha256 `542943B4…7DCC0D`，预览 7 张见 `android-class-tools/artifacts/`。
- **存量用户 deck**：`dmwalrdlgevz90l`（16 页/第 12 页内嵌 225.6s）已 `--video-only` 补转：`deck.mp4` **13,668,151 B / 303.6s / 1280x720 / h264+aac / 16 章**，manifest 只新增 video、slides 未动。
- **真实 E2E**：网页（本地通道+headless Edge，真实云端 deck）**15/15 PASS**（默认原样、章节 seek、续播、切分步、热点、0 JS error）；小程序 automator 真机环境原样播放 `deck.mp4` 起播、章节/倍速/切分步通过。
- **回滚**：网页重传 `tools/_backup/index_online_20261110-2055_prePPTv12.html`（802,355 B/`e40571d3…`）；转换机 `schtasks /Change /TN PptConvertAgent /DISABLE` 或 `ppt-agent.pause`；
  manifest 可 PATCH 去掉 video（客户端自动回落分步）；已补转 deck 的 `deck.mp4` 删除即可。
- **已知取舍**：原样播放把单击动画合并为自动节奏；外链媒体无法播放（视频中以其海报静态帧代替）；章节允许 ±1s；>120 页/30min 不生成视频；
  小程序/安卓真机受 OSS 默认域名 force-download 头与微信域名白名单影响，失败会自动回退分步（详见 §11.4/§11.8）。

## 2026-11-10 22:0x–23:5x · 增量 31：PPT 功能重定义 v2.0——上传→自动兼容性处理→多端下载（不降质）

> 用户 22:05 原话：「重新定义该功能，不再已在线播放为主要功能，而是以上传ppt，自动对内容进行兼容性处理，并提供多端下载的方式，不改变ppt本身质量」。
> **新定位**：兼容性处理与多端下载中心；在线播放降为旧 deck 的「在线预览」次要入口。契约见 `ppt/CONTRACT.md` §12。

- **转换机**（`ppt/convert.py` 新增 `convert_compat()`、`agent.py` 默认 compat / `--legacy` / `--compat-only`）：
  - 临时副本（不改 `ppt/src` 原件）：`.ppt→.pptx`（PowerPoint SaveAs 24）、`SaveAs(24, EmbedFonts=-1)` 规范化+嵌入字体（实测 ppt/fonts 6 部件）、
    `SaveAs(32)` 导出 PDF（ExportAsFixedFormat 在 pywin32 动态绑定不可用，已记录等价适配）、第 1 页 cover.webp、上传 `compat.pptx` + `original.<ext>` + `preview.pdf` + `cover.webp`；
  - **质量强保证**：compat 包内 `ppt/media/*` sha256 与源包逐字节一致（用户 deck 15/15 一致，0 重编码）；PDF 页数= slide_count；
  - 外链媒体（TargetMode=External）**不删除**，manifest `compat.warnings` 按页告警（用户 deck 第 7 页外链视频 1 处）；
  - manifest v2 `files{compat,pdf,source}`+`compat{warnings,fonts_embedded,converted_from}`；slides 为空（compat 模式不生成分步图）；旧字段保留；
  - `--compat-only --deck <id>`：从 source_key 补 compat/PDF/源副本并合并 manifest（保留 slides/video/src/media/base）；进度 10/30/55/75/85/95；上传重试 2 次；
  - PowerPoint 自动化 Quit 偶发滞留 → 3s 宽限后强杀 `/AUTOMATION` 实例（不误杀用户手动实例），单次 compat 转换 2–7s；计划任务 ExecutionTimeLimit PT45M 保持不变并已重新启用。
  - 测试：`test_pure_logic.py` **123/123**、`test_compat_integration.py` **19/19**（媒体 sha 逐字节/页数/PDF 页数/字体/外链告警/.ppt/失败路径）、`test_convert_integration.py` **22/22**、`test_cloud_contract.py` **7/7**。
- **存量用户 deck** `dmwalrdlgevz90l`：真实 `--compat-only` 完成（manifest 保留旧 slides/video，仅新增 files+compat）：compat.pptx **39,068,049 B / sha256 20de7b37…**、preview.pdf **1,105,861 B / 16 页**、original.pptx **38,016,533 B**、cover.webp 25,174 B；字体 6；外链告警 1；compat 转换 4.5s（总耗时含 38MB 下载 189s）。
  独立质量验收 `_qa_ppt_compat.py`（真实云端/OSS 下载）**24/24 PASS**：三件套 size/sha256 与 manifest 一致、compat 页数=16、**源 15 个媒体全部逐字节保留（missing=[]）**、PDF 页数=16、warnings 可读、旧 slides/video 保留。
- **网页** `tools/index.html`（**870,349 B / sha256 `ea799a28…`**，APP_VER 仍 2.0.0；已部署 OSS MATCH）：
  点卡片=下载详情（懒拉 manifest）；三行下载 **兼容版 PPTX / PDF（页数）/ 原始文件**（OSS 直链 + download 文件名/大小）；橙色兼容提示；旧 deck「兼容版未生成+原始文件+在线预览+重新处理」；
  列表「兼容版」「PDF」小标签（轻量 `manifest->files` 子查询，失败静默）；旧播放器保留为「在线预览」；新 compat deck 外部 `PPT.open` 自动转详情。
  专项 `v2_ppt_download_check.py` **41/41**、`v2_ppt_check.py` **92/92**、`v2_ppt_video_check.py` **100/100**；真实云端 E2E **16/16**（真实 deck、三行 href/name/大小、warnings、0 JS error）。
- **小程序**（源码 `mp-class-tools/`，VERSION 2.0.0）：新页 `pages/pptdl`（三行下载、wx.downloadFile 进度/取消→wx.openDocument、wx.shareFileMessage 转发、复制链接、兼容提示、旧 deck 预览/重新处理）；列表点击=详情+「兼容版/PDF」标签；
  `unit 363/0`、`ppt_dl_unit 26/0`、`sync 33/0`、staticcheck/code_quality 0、automator `ppt_dl_preview` **27/0**（真实 old deck 详情 + 注入 v2 三行下载链）。
- **安卓** 3.5.0 / versionCode 11：下载详情页（三行下载/大小/DownloadManager/FileProvider 打开/分享/兼容提示/旧 deck/在线预览入口）；`testDebugUnitTest` **982/0**（新增 28 不可回退 954）；`assembleRelease` 成功，APK **2,741,438 B / sha256 `C45070AC…`**（保存在应用下载目录，系统通知可见，可直接打开/分享）。
- **交付**：桌面 `班级工具站_PPT演示_20261109\` 更新 **班级工具站_3.5.0.apk**、`更新说明_PPT_v2.0_20261110.md`、`截图_v2.0\`；独立验收报告 `web/验收报告/PPT演示_v2.0_下载中心_验收_20261110.md`。
- **回滚**：网页重传 `tools/_backup/index_online_20261110-2215_preStageV2.html`（847,026 B/`411354e1…`，注意会连同并行大屏改动回退）；禁用任务 `schtasks /Change /TN PptConvertAgent /DISABLE` 或 `ppt-agent.pause`；manifest 去掉 `files`/`compat` 即回落旧逻辑；`--legacy` 可临时跑旧链路；无 DB schema 变更。
- **已知限制**：外链媒体不能随包（只告警不删除）；字体许可受限时仅告警；兼容包体积 ≈ 源 + 字体（36.3MB→37.3MB）；小程序/安卓需设备装有 Office/WPS/PDF 查看器；小程序需微信后台配置 OSS request+downloadFile 合法域名并上传发布；安卓下载落私有下载目录（受不申请存储权限红线约束）；兼容版与原文件建议文件名区分（当前取同标题，浏览器会重命名）。
