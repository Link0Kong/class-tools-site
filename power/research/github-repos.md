# GitHub「完美校园」电费相关项目侦察报告

> 侦察员：gh-hunter ｜ 任务：task-1 ｜ 快照时间：2026-11-05 22:30（Asia/Shanghai）
> 方式：GitHub 免登录 REST 检索（14 组关键词、去重 468 个仓库）→ 下载 34 个仓库 tarball 本地精读源码 → 检查 Issue / 最近提交 → 公开网页（博客、Apifox、学校公文）交叉验证。
> 全程只做公开仓库只读检索，未向任何外部服务发送真实个人信息（学号/姓名/手机号/密码）。
> 目标学校：福建中医药大学（FJTCM），完美校园学校码 **769**。

> ⚠️ **方向更新（2026-11-05 22:50，Lead 实测后修订，优先级最高）**
> 用户本人确认：查宿舍电费的入口是「**完美校园 → 缴费 / 用电支出（预付费）**」，不是智能水电、也不是今日校园。
> Lead 实测：真实学号 + 学校码 **769** 调老引擎 `getbindroom` 返回 **8099「body格式错误」**（对照学校 759 正常），**基本坐实 FJTCM 不走完美校园智能水电老引擎**。
> 因此：§2.1 / §3.1~§3.11 的「老引擎 SWAEServlet」内容仅作**其他学校参考与协议背景**，**对本校大概率不可用**；本报告新增 **§3.0「云缴费专题」** 作为本校主线，最终落地请看 **§3.0.8 分级结论**、**§7.0**。

---

## 0. TL;DR

### 0.1 结论更新（2026-11-05 22:50，Lead 实测后；优先于下方初版）

1. **本校路线已锁定「云缴费」**：用户入口 = 完美校园「缴费 / 用电支出（预付费）」；Lead 用真实学号 + 769 实测老引擎返回 `8099「body格式错误」`（对照 759 正常）→ **老引擎（SWAEServlet）对本校排除**，不要再在它上面花时间。
2. **云缴费有两条子路线，优先测 B2**：
   - **B1 `h5cloud` CloudPayment**：`https://h5cloud.17wanxiao.com:18443/CloudPayment/`。必须完美校园登录（手机号+密码；新设备一次性短信验证，`deviceId` 绑定后免验证码）→ 握手 session 当 token → `pay.do` 换 `SESSION` → 五步链查 `quantity`。代表：`jialiangh/campus-electricity-monitor`（首选）、`Zuizhuban`、`DHKun`。
   - **B2 学校云支付网关（免登录）**：`https://cloudpaygateway.<学校域名>:<端口>/paygateway/smallpaygateway/trade`，调 `samllProgramGetRoomState`，只需 `schoolcode + payproid + businesstype + roomverify`，**无 token、无账号密码**。参数从**缴费页链接抓一次**即可。代表：`cyqmq/astrbot_plugin_wanmei_dorm_power`（一键解析）、`lswlc33`、`stmtc233`。
3. **「必须抓一次包」清单**：B2 必须抓一次「缴费/用电支出」页面链接（拿网关 host:port、`customerId`、`payproid`、`flag`）；B1 不需要抓包，但需要用户本人完成首次账密登录 + 短信验证（一次性，`deviceId` 可复用）；goPay 充值需要抓一次收银台域名/商户号（各校不同）。
4. **直接可抄**：B2 → `cyqmq` 的 `pay_url_parser.py` + `tools/detect_config.py` + `_get_room_state`（改链接即用）；B1 → `jialiangh` 的 `CloudPay` 类 + `wanxiao_login.py`；推送/定时 → Qmsg / Server酱 / PushPlus / 钉钉 + cron（`chanlun3377`、`fanxingstarry` 的骨架）。
5. **云缴费线的风险重点**：登录风控（新设备/异地/验证码、`deviceId` 失效）、`SESSION` 过期、WAF（405 / `code_:9004` 熔断）、海外 IP 受限、查询过频（网关会「频繁请求，请稍后」）。**没有检索到公开的"因查电费被封号"实锤案例**，但账号安全要按密码对待。
6. 老引擎那批项目（27★ 的 zuwei522 等）文档价值高、**但对 FJTCM 用不上**——保留在报告里只为协议背景与其他学校复用。

> —— 以下为初版 TL;DR（22:30 版），保留备查；其中「2026 年仍活跃的是老引擎路线」「本校需要实测走哪条」等判断已被 §0.1 更新，**以 §0.1 为准**。——

## 0.2 初版 TL;DR（先看这 8 条，保留备查）

1. **生态分两条产品线，不能混用**：
   - **老引擎「智能水电」**：`POST https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet`，只凭 `customercode`（学校码）+ `account`（学号，部分学校是 outid/身份证号）即可查，**不需要登录、没有 token**。代表：`zuwei522/perfect-campus_electricity-alert`（27★）、`Jursin/wanxiao-electric-apis`、`suiren0219/astrbot_plugin_dorm_power`、`DragonYH/astrbot_plugin_wanxiao_electricity`。
   - **云缴费「CloudPayment」**：`https://h5cloud.17wanxiao.com:18443/CloudPayment/`，需要**完美校园账密登录**（RSA + 3DES 协议）换 token → SSO → `SESSION`，再走五步取数；另有一条「学校云支付网关」变体 `https://cloudpaygateway.<学校域名>:<端口>/paygateway/smallpaygateway/trade`（`samllProgramGetRoomState`），**可免登录**，但需抓一次缴费链接。代表：`jialiangh/campus-electricity-monitor`、`JustaSage/ZCST_FEE_Bot`、`DHKun/xzmu-electricity-monitor`、`cyqmq/astrbot_plugin_wanmei_dorm_power`、`stmtc233/WanXiao-Elec-TgBot`。
2. **2026 年仍在更新的是「老引擎」路线**（2026-10 有多个新项目：chanlun3377、fanxingstarry、suiren0219、Jursin、sctop、DragonYH），说明 SWAEServlet 对相当一部分学校仍然可用；但部分学校已被迁到**加密版 `SWAEEncryptServlet`**（AES-128-ECB，chuzong886 2026-10 实现）或云缴费。**只能用一条 `getbindroom` 实测判断本校属于哪条线。**
3. **本校（FJTCM）没有现成项目可抄**。学校码 769 只出现在三份「学校码表」里。FJTCM 官方口径（2021 新闻、2022 信息化 FAQ）是「今日校园 → 公共服务 → 购电查询（填楼栋号+房间号）」，完美校园在本校主要用于一卡通充值；隔壁**福建医科大学**的完美校园则走「线上缴费 → 预付费 → 用电支出」。**769 走哪条线必须实测**（见 §7 验证步骤）。
4. **最值得抄的是 `jialiangh/campus-electricity-monitor`**（MIT，2026-10，Python）：一份完整的「先分流判断 + 完美校园登录协议 + CloudPayment 五步取数 + 坑清单」逆向笔记，还带可复用的登录 CLI。其次是 `Jursin/wanxiao-electric-apis`（老引擎最干净的接口文档 + CLI）。
5. **最大风险不是接口挂了，而是 IP 被封**：完美校园曾对海外 IP / 云厂商 IP 返回超时或 405（阿里云 WAF），GitHub Actions / 云服务器部署有概率翻车（有 2025-07 恢复的记录）。建议**家宽 / 树莓派 / Windows 任务计划** + 每天 ≤8 次低频。
6. 老引擎所谓「免登录」其实是一个**越权读取面**（知道学校码+学号就能查该账户绑定的房间）。只用于本人宿舍、低频；**不要批量探测别人房间**，既违反平台协议也有风控/封号风险。
7. 推送渠道没有标准答案：Qmsg 酱 / Server 酱 / PushPlus / 钉钉 / 飞书 / Telegram / SMTP 邮件都有人实现，选自己每天会看的那个即可（Qmsg/Server 酱最省事）。
8. 本仓库（千级 star 的打卡项目如 `ReaJason/17wanxiaoCheckin` 397★）不适合抄功能，但**登录协议 / 加密实现**（RSA-1024 + 3DES-CBC + `campusSign`）是全网最权威的中文开源参考，做云缴费路线时必读。

---

## 1. 侦察方法与覆盖范围

| 步骤 | 做法 | 结果 |
|---|---|---|
| 仓库检索 | GitHub Search API，关键词：`完美校园`、`17wanxiao`、`100campus`、`完美校园 电费`、`完美校园 打卡`、`新开普`、`智能水电`、`SWAEServlet`、`smartWaterAndElectricityService`、`perfect campus`、`校园卡 电费`、`wanxiao`、`xqh5`、`电费 提醒` | `100campus`/`SWAEServlet`/`xqh5` 仓库搜索均为 0；合并去重后 **468** 个仓库（每词最多取 100 条） |
| 精读 | 下载 34 个最相关仓库 tarball，逐个读 README + 核心脚本 + 学校码表 | 34 个仓库、约 60 个核心文件 |
| 活跃度 | `pushed_at`（2026-11-05 快照）+ Issue 状态 + README 失效声明 | 见 §5、§6 |
| 协议交叉验证 | Apifox 共享接口文档、doupoa 博客（2024-09/2026-04）、CSDN、飞书推送教程、Gitee/GitHub Issue | 见 §4、§9 |
| 本校线索 | 搜索「福建中医药大学 电费 / 完美校园 / 购电查询」，抓学校官方 docx（福建医科大学，注意是另一所学校）与公众号文章 | 见 §7 |

> 说明：未登录的 GitHub Search 只覆盖 name/description/README 命中；**代码搜索需要登录**，所以「README 里提到但仓库名不含关键词」的项目可能漏检。本报告对 2026-09 之后新出现的项目覆盖较好。
>
> **第二轮（2026-11-05 22:55，Lead 指定云缴费方向后补检）**：针对 `CloudPayment`、`cloudpaygateway`、`smallpaygateway`、`samllProgramGetRoomState`、`goPay 完美校园`、`完美校园 缴费/预付费`、`云缴费 newcapec`、`h5cloud.17wanxiao.com` 等 10 组仓库关键词 + 4 组 Issue 关键词复查。结果：**仓库搜索几乎全部 0 命中**（仅「完美校园 缴费」命中 1 个 cyqmq），Issue 搜索仅 3 条（其中 zuwei522 Issue #8 为福建高校云缴费案例）。这说明 **CloudPayment/云支付网关相关实现只存在于源码里，未登录无法代码检索**——本节结论来自对 34 个已知仓库源码的交叉引用，代表性可接受但非穷尽。

---

## 2. 项目对比表

### 2.1 核心：完美校园电费直连（老引擎 SWAEServlet，免登录）

> ⚠️ **FJTCM 适用性：已实测排除**。用户入口是「缴费/用电支出」；Lead 用 769 实测 `getbindroom` 返回 `8099「body格式错误」`（759 正常）→ 本表项目对本校**大概率不可用**，仅作其他学校参考与协议背景。目标路线请看 §2.2 + §3.0。

| 仓库 | Stars | 语言 | 最近提交 | License | 一句话定位 | 推送/定时 |
|---|---|---|---|---|---|---|
| [zuwei522/perfect-campus_electricity-alert](https://github.com/zuwei522/perfect-campus_electricity-alert) | 27 | Shell | 2025-06-06 | 未标注 | 元祖项目：GitHub Actions 定时查绑定房间电量，低阈值推 QQ（Qmsg 酱） | GitHub Actions cron（UTC 4/11 点）+ Qmsg |
| [Jursin/wanxiao-electric-apis](https://github.com/Jursin/wanxiao-electric-apis) | 0 | Python | 2026-10-07 | 未标注 | **最干净的接口封装 + 接口字段文档**（getbindroom/h5_getstuindexpage/getusedetail/gettimeusedetail） | 无定时，CLI |
| [chanlun3377/campus-electricity-alert](https://github.com/chanlun3377/campus-electricity-alert) | 0 | Python | 2026-10-01 | MIT | 从 zuwei522 重构：多房间、浮点精确比较、Windows 任务计划、记录 WAF 405 踩坑 | Windows 任务计划 12/19 点 + Qmsg |
| [fanxingstarry/perfect-campus-electricity-alert](https://github.com/fanxingstarry/perfect-campus-electricity-alert) | 0 | Python | 2026-10-16 | MIT | Docker 化，钉钉自定义机器人推送，含电量折算电费（0.62 元/度硬编码） | APScheduler 每日 12:00 + 钉钉 |
| [m555455445/Perfect-Campus_Electricity-Warning](https://github.com/m555455445/Perfect-Campus_Electricity-Warning) | 0 | JavaScript | 2023-11-30 | 未标注 | 早期 Actions 版 JS 脚本，双阈值（低电量/即将停电），支持微信/QQ/钉钉 | GitHub Actions + Server酱/Qmsg/钉钉 |
| [suiren0219/astrbot_plugin_dorm_power](https://github.com/suiren0219/astrbot_plugin_dorm_power) | 1 | Python | 2026-10-25 | MIT | **工程化最强**：多用户自助绑定、多房间、加密落盘、搜校限速防风控、接口字段/命令可配置、曲线图 | AstrBot 定时（默认 8/20 点）+ 会话播报 |
| [DragonYH/astrbot_plugin_wanxiao_electricity](https://github.com/DragonYH/astrbot_plugin_wanxiao_electricity) | 0 | Python | 2026-07-21 | AGPL-3.0 | 内置 358 条学校「名称→代码」表（带来源校验），多账号、水电同时查、并发限 2 | AstrBot 命令/定时 |
| [sctop/astrbot_plugin_perfect_campus_zqu_query](https://github.com/sctop/astrbot_plugin_perfect_campus_zqu_query) | 1 | Python | 2026-09-02 | AGPL-3.0 | 肇庆学院专用：pydantic 建模解析、轮询调度 | AstrBot 定时 |
| [Jursin/astrbot_plugin_wanxiao](https://github.com/Jursin/astrbot_plugin_wanxiao) | 1 | Python | 2026-10-07 | AGPL-3.0 | 上面 wanxiao-electric-apis 的 AstrBot 插件版，支持本周/近X周/本月/近X月用量 | AstrBot cron（默认每 2 小时检查预警） |
| [snowf14k3/electricity-alert](https://github.com/snowf14k3/electricity-alert) | 2 | TypeScript | 2025-07-29 | MIT | **Cloudflare Workers + D1 + SMTP** 的在线版，网页按 `学校码/学号` 查询、邮箱订阅预警 | Workers cron `0 4,11 * * *`（UTC） |
| [bingjuu/wxeleTool](https://github.com/bingjuu/wxeleTool) | 2 | Python | 2024-11-28 | 未标注 | 微信群插件（chatgpt-on-wechat）：查电费/监控/取消监控，附 schoolcode 测试脚本 | 插件循环检测 + 微信群 |
| [WeiZong668/ESP32-Electricity-TTS-MP3-Player](https://github.com/WeiZong668/ESP32-Electricity-TTS-MP3-Player) | 0 | Python | 2026-03-15 | 未标注 | 硬件玩法：服务器爬电费→TTS→ESP32 喇叭播报 | 常驻服务 |
| [Morii-torri/LowElecAlert](https://github.com/Morii-torri/LowElecAlert) | 0 | Python | 2024-06-10 | MIT | **不是完美校园标准接口**：上海工程技术大学自建 epay 页 `epay.sues.edu.cn/epay/wxpage/wanxiao/eleresult`，解析 `left-degree` | 外部定时（Actions）+ WxPusher |

### 2.2 核心：完美校园云缴费 / 账密登录路线（CloudPayment & 学校云支付网关）

> ✅ **FJTCM 目标路线**（用户入口=缴费/用电支出；老引擎已实测排除）。本节项目按「可抄性」再排序并展开见 **§3.0**。

| 仓库 | Stars | 语言 | 最近提交 | License | 一句话定位 | 推送/定时 |
|---|---|---|---|---|---|---|
| [jialiangh/campus-electricity-monitor](https://github.com/jialiangh/campus-electricity-monitor) | 2 | Python | 2026-10-15 | MIT | **技术文档最全**：纯账密无人值守，CloudPayment 五步取数；周一微信周报 + 低电量每 3 小时提醒 | 服务器 cron（每小时采样/周一 00:05 周报）+ PushPlus |
| [JustaSage/ZCST_FEE_Bot](https://github.com/JustaSage/ZCST_FEE_Bot) | 5 | Python | 2026-06-13 | AGPL-3.0 | 学校 SSO（CAS）自动换查询链接 → `loginCheck` AES 解密 → SWAEServlet；含**充值**（goPay→支付宝 WAP） | Telegram Bot + 到账监控 + 多用户定时 |
| [Zuizhuban/wanxiao-electricity-alert](https://github.com/Zuizhuban/wanxiao-electricity-alert) | 0 | JavaScript | 2026-10-12 | 未标注 | 单文件 Node 客户端：账密登录（RSA 换秘钥 + 3DES 信封）→ pay.do 换 SESSION → 云缴费查用量；带 `--selftest` | 外部调度（自带 Qmsg 推送函数） |
| [DHKun/xzmu-electricity-monitor](https://github.com/DHKun/xzmu-electricity-monitor) | 2 | Kotlin | 2026-10-31 | MIT | 西藏民大：安卓/鸿蒙 App + 桌面脚本；`h5cloud.17wanxiao.com:18443/CloudPayment/user/getRoomState.do` 需 **Cookie + Referer**；WebView 静默续登 | Android WorkManager / systemd timer + 系统通知 |
| [cyqmq/astrbot_plugin_wanmei_dorm_power](https://github.com/cyqmq/astrbot_plugin_wanmei_dorm_power) | 0 | Python | 2026-10-26 | 未标注 | **学校云支付网关版**：`samllProgramGetRoomState`，无需登录 token，只需抓一次缴费链接；附一键探测脚本 | AstrBot 定时（默认 8/20 点） |
| [stmtc233/WanXiao-Elec-TgBot](https://github.com/stmtc233/WanXiao-Elec-TgBot) | 0 | Go | 2026-11-05 | MIT | 最新（今天还在提交）：Go+SQLite+Telegram；老引擎查电 + **goPay 充值链接** + 小时统计图 + 2900 校表 | Cron v3 每 30 分钟采集/预警 |
| [lswlc33/jsit_wanmei_left_power_select](https://github.com/lswlc33/jsit_wanmei_left_power_select) | 1 | Python | 2024-03-06 | Apache-2.0 | 江苏信息职院：云支付网关 `cloudpaygateway.59wanmei.com:8087` 批量扫楼查房间电量（128 线程，已停更） | 手动/爬虫 |
| [lswlc33/wanxiao_power_monitor](https://github.com/lswlc33/wanxiao_power_monitor) | 0 | Python | 2024-12-14 | 未标注 | Flask + ECharts 电量面板，全校 TOP10；用同一云支付网关 | Flask/waitress，无预警（未完成） |
| [yifeiyixiang/wanmeixiaoyuan](https://github.com/yifeiyixiang/wanmeixiaoyuan) | 4 | —（仅 README） | 2023-10-24 | 未标注 | 早期云支付路线：`h5cloud.17wanxiao.com:8080/CloudPayment/user/getRoomState.do` + Cookie，虚拟 deviceId 登录 | 死循环 sleep 86400 + PushPlus |
| [Andtun02/school-charge-open](https://github.com/Andtun02/school-charge-open) | 3 | Python/HTML | 2024-05-24 | Apache-2.0 | 账密登录 + CloudPayment 爬虫 + Web 可视化；需先注册设备 ID（tool/） | 自建 Flask Web |
| [chuzong886/wanmeixiaoyuandianfeiyujin](https://github.com/chuzong886/wanmeixiaoyuandianfeiyujin) | 1 | PHP | 2026-10-16 | 未标注 | **「天枢」完整自部署系统**：加密版 `SWAEEncryptServlet`（AES-128-ECB）+ MySQL + 宝塔每分钟任务 + 用电预测/风险调度 + Spug/短信/邮件通知 | 宝塔 cron 每分钟 + Spug/Webhook/SMTP |

### 2.3 登录 / 协议 / 充值参考（这些项目不直接查电费，但协议最全）

| 仓库 | Stars | 语言 | 最近提交 | License | 用途 |
|---|---|---|---|---|---|
| [ReaJason/17wanxiaoCheckin](https://github.com/ReaJason/17wanxiaoCheckin) | 397 | Python | 2024-01-05 | MIT | 完美校园健康打卡；**账密/短信登录协议权威参考**（RSA 交换密钥、3DES-CBC、`campusSign`） |
| [sijiyo/new_wanxiao](https://github.com/sijiyo/new_wanxiao) | 5 | Python | 2026-01-04 | 未标注 | 「过风控版」登录参数（qudao/xiaomi、shebeixinghao 等换新版字段） |
| [fuqiuluo/wanxiao-campus](https://github.com/fuqiuluo/wanxiao-campus) | 5 | Rust | 2024-03-24 | 未标注 | Rust 版会话/加密实现：`exchangeSecretkey.action`、3DES、`keychain` API（`xqh5.17wanxiao.com/keychain/Api`） |
| [JarvisLeung/wanmei_campus](https://github.com/JarvisLeung/wanmei_campus) | 5 | Python | 2020-10-05 | MIT | 最早期模拟登录（旧域名 `server.17wanxiao.com`），一卡通流水/余额 |
| [KeJunMao/wan-xiao-ykt](https://github.com/KeJunMao/wan-xiao-ykt) | 3 | JavaScript | 2021-01-20 | 未标注 | 一卡通年度报告生成（Node，3DES/RSA 同源实现） |
| [imldy/17wanxiao2qq](https://github.com/imldy/17wanxiao2qq) | 0 | Python | 2022-12-20 | 未标注 | `reported.17wanxiao.com` 后台登录提醒（打卡场景，非电费） |
| [Dongxiaohaoo/17Wanxiao-Web](https://github.com/Dongxiaohaoo/17Wanxiao-Web) | 2 | Python | 2024-05-16 | 未标注 | Django Web 版打卡，几乎照搬 ReaJason 协议 + 一键 Web 部署 |

### 2.4 非完美校园（对比/思路参考，不要混用接口）

| 仓库 | 说明 |
|---|---|
| [iBUHub/TJUEcard](https://github.com/iBUHub/TJUEcard) 30★、[zhouii/Tongji_Helper](https://github.com/zhouii/Tongji_Helper) 226★、[Hjyheart/Spider-for-electricity-inquiries](https://github.com/Hjyheart/Spider-for-electricity-inquiries) 4★ | 天津大学/同济，各自学校的电费系统，与完美校园无关 |
| [Luke-Evan/nju_power_monitor](https://github.com/Luke-Evan/nju_power_monitor) 2★、[Begonia514/NJU-ElectricityReminder](https://github.com/Begonia514/NJU-ElectricityReminder) 3★ | 南京大学，GitHub Actions + 静态站方案，**定时/可视化思路可借鉴** |
| [w23x0/wattwatch-template](https://github.com/w23x0/wattwatch-template) 0★ | Cloudflare Workers 模板：作息感知停电预测 + 邮件提醒，**Serverless 思路可借鉴** |
| [Yukira252/GDUFS-Utility-Monitor](https://github.com/Yukira252/GDUFS-Utility-Monitor) 5★ | 广外「数智广外」，带托盘/向导/日报的成品形态，UI 思路可借鉴 |
| [IDeLoveYou/SGU-Water-and-Electricity-Bill-enquiry](https://github.com/IDeLoveYou/SGU-Water-and-Electricity-Bill-enquiry) 4★ | 韶关学院，**README 首行已写「本项目已不适用且不再维护」**，且非完美校园 |
| 其他：`saicem/OhMyWhut.FastFetcher`、`w1ndys/QFNUElectricityQuery`、`azazo1/ecnu-query-electric-bill`、`ChaceQC/Electricity-monitoring-system`、`Yancey597/HUBU-Electricity-bill-inquiry`、`Leon-Cjl/campus-dianfei`、`428581985-cyber/szu-electricity`、`ybyz2/dorm-electricity-bot`、`ZackWatts1145/nxist-power-monitor`、`campus-electricity-alert` 系 | 各校自建方案，若本校路线最终走不通，可参考其「低频 + 阈值 + 推送 + 历史曲线」的通用工程结构 |

---

## 3. 逐项目详解

> 本章结构：**§3.0 是本校（FJTCM）主线专题（云缴费 / 预付费 / 用电支出）**；§3.1~§3.22 是老引擎（SWAEServlet）项目，对本校大概率不适用，仅作协议参考与其他学校复用。

## 3.0 专题：完美校园「云缴费 / CloudPayment / 预付费 / 用电支出 / goPay」路线（本校目标路线，2026-11-05 补）

> 本节是 Lead 实测后新加的**主线**：FJTCM 用户入口 =「完美校园 → 缴费 / 用电支出（预付费）」，老引擎已被 8099 实测排除。本节回答四个问题：**有哪些项目实现了？登录鉴权到底是什么？有没有免登录入口？哪些要抓包？**

### 3.0.1 判定依据（为什么主线是云缴费）

| 线索 | 内容 | 来源 |
|---|---|---|
| 用户入口 | 完美校园 → 缴费 / 用电支出（预付费） | 用户本人确认（Lead 转述） |
| 老引擎实测 | 真实学号 + 769 调 `getbindroom` → `8099「body格式错误」`；对照 759 正常 | Lead 实测（2026-11-05） |
| 隔壁校形态 | 福建医科大学（完美校园）官方流程：「线上缴费 → 预付费 → 用电支出 → 缴费房间 → 剩余电量」 | [fjmu 官方 docx](https://www.fjmu.edu.cn/_upload/article/files/90/64/76601dcd4963bbc7885588ccc073/438e1229-2e96-456b-8192-5d661a7dee5e.docx) |
| 同类用户案例 | zuwei522 Issue #8：福建江夏学院「宿舍购电 → 电费支出 → 缴费房间」，学校码找不到/抓包失败 | https://github.com/zuwei522/perfect-campus_electricity-alert/issues/8 |
| 项目适用声明 | Zuizhuban 文件头：「你学校的电费在完美校园里是『首页 → 缴费 → 预付费 → 用电支出 → 选房间』看的，而不是『智能水电』里看的」 | 仓库原文 |

**结论：云缴费线有两种可能的产品形态，必须先抓一次缴费链接来分辨（见 3.0.2）。**

### 3.0.2 云缴费路线对比（B1 / B2 / 充值 R / 小程序 W；与 §4 全景表对照：B1≈§4-B/B'，B2＝§4-C，R＝§4-G）

| 代号 | 路线 | 端点 | 鉴权 | 是否可免登录 | 参数来源 | 查询响应 | 代表项目 |
|---|---|---|---|---|---|---|---|
| **B1** | h5cloud CloudPayment（完美校园官方云缴费 H5） | `https://h5cloud.17wanxiao.com:18443/CloudPayment/`（`user/pay.do` → `bill/type.do` → `bill/querySelfPayList.do` → `bill/selectPayProject.do` → `user/getRoomState.do`） | wanxiao 登录 token（手机号+密码或短信）→ SSO 换 `HttpOnly SESSION`；后续每个请求要 `Referer`（第 4 步完整 URL） | **否**（必须登录） | 登录后自动发现 `customerId`/`payProId`；或从缴费页 HTML 隐藏域 `hostCustomerCode` | `{"returncode":"100","quantity":"169.82","quantityunit":"度","description":"616"}` | jialiangh、Zuizhuban、DHKun、Andtun02、yifeiyixiang（旧端口） |
| **B2** | 学校云支付网关（完美校园「缴费」小程序的轻量网关，常见于 `cloudpaygateway.<学校域名>:<端口>`） | `POST https://cloudpaygateway.<域名>:<端口>/paygateway/smallpaygateway/trade` | **无**（部分网关校验 Origin/Referer，不校验登录） | **是** | 从缴费页链接解析：`customerId`→schoolcode、`#/billDetail?item={...}` 的 `id`→payproid、`flag`→businesstype、host:port→api_url | `{"returncode":"SUCCESS","businessData":{"quantity":"...","quantityunit":"度"}}` | cyqmq、lswlc33（两个仓库）、stmtc233（学生信息校验） |
| **R** | goPay 充值链（查余额之外，若要"低电自动充值/生成支付链接"） | `https://xqh5.17wanxiao.com/smartWaterAndElectricityService/goPay` → `cloudpaygateway.../paygateway/smallpaygateway/trade`（`getPayInfoByUuid`/`callWapCashDeskData`）→ 学校收银台 | 需登录 token + `loginCheck` 数据；部分学校白名单 | 否 | 需抓包确认学校收银台域名/商户号（如珠海 `dk.zcst.edu.cn`、学校 `merchantno`） | 返回支付宝 WAP 链接 | JustaSage、stmtc233 |
| **W** | 微信/支付宝小程序入口（如果用户从 WX 小程序进） | 同上，但先经 WX code → openid/token → 302 → 真 session | WX code + openid + token（2022 起加的身份验证） | 否 | 需在 WX 环境抓包 | 同上 | 无完整开源项目；doupoa 2022 博客有流程 |

> **优先级建议：先试 B2（最省事，免登录），B2 不通再走 B1（要账密+一次性短信）。** W 是最后手段（要 WX 环境，难度最高）。

### 3.0.3 云缴费相关项目清单（按"可抄性"排序）

| 项目 | 覆盖内容 | 登录方式 | 查询端点 | 充值 | License/最近提交 | 可抄性 |
|---|---|---|---|---|---|---|
| [jialiangh/campus-electricity-monitor](https://github.com/jialiangh/campus-electricity-monitor) | **B1 全链 + 登录协议 + 文档**（`docs/接口说明.md` 必读） | 手机号+密码；新设备短信；`deviceId` 落盘 | CloudPayment 五步 + `getRoomState.do` | 否 | MIT / 2026-10-15 | ★★★★★ 首选底稿 |
| [Zuizhuban/wanxiao-electricity-alert](https://github.com/Zuizhuban/wanxiao-electricity-alert) | B1 单文件 Node（RSA+3DES 登录、pay.do 换 SESSION、查房间/用量、`--selftest`） | 手机号+密码 / 短信；`deviceId` 缓存 | 同上 | 否 | 未标注 / 2026-10-12 | ★★★★★ 最快验证本校是否 B1 |
| [cyqmq/astrbot_plugin_wanmei_dorm_power](https://github.com/cyqmq/astrbot_plugin_wanmei_dorm_power) | **B2 全链**（缴费链接 → 参数解析 → 房间树 → `samllProgramGetRoomState`），附带一键探测脚本 | **无需登录** | `smallpaygateway/trade` | 否 | 未标注 / 2026-10-26 | ★★★★★ 若本校是 B2，改链接即用 |
| [DHKun/xzmu-electricity-monitor](https://github.com/DHKun/xzmu-electricity-monitor) | B1 的 `getRoomState.do`（Cookie+Referer）+ WebView 静默续登 | WebView 登录（可记住密码） | `CloudPayment/user/getRoomState.do` | 否 | MIT / 2026-10-31 | ★★★★ 学"登录态续期" |
| [stmtc233/WanXiao-Elec-TgBot](https://github.com/stmtc233/WanXiao-Elec-TgBot) | 老引擎查电 + **B2 学生信息校验**（`smallProgramUserAuth`）+ **R 充值链**（`getPayInfo`） | 无（查询）；充值需登录数据 | `goPay` + `cloudpaygateway` | 是（仅校码 1399 白名单） | MIT / 2026-11-05 | ★★★★ 学 goPay/多校表 |
| [JustaSage/ZCST_FEE_Bot](https://github.com/JustaSage/ZCST_FEE_Bot) | **E loginCheck**（学校公开链接→AES 解密得查电参数）+ **R 完整充值链**（goPay→uuid→getPayInfoByUuid→callWapCashDeskData→prepayOrder→支付宝） | 学校 CAS SSO / 公开查询链接 | 查询走老引擎 SWAEServlet（该校可用）；充值走网关 | 是 | AGPL-3.0 / 2026-06-13 | ★★★★ 学 loginCheck + 充值链；**查询部分对 FJTCM 不适用** |
| [Andtun02/school-charge-open](https://github.com/Andtun02/school-charge-open) | 早期 B1（账密 + `pay.do` + `selectPayProject` + `getRoomState`）+ Web 可视化 | 账密 + 注册设备 ID 工具 | CloudPayment | 否 | Apache-2.0 / 2024-05-24 | ★★★ 报文交叉参考（已停更） |
| [yifeiyixiang/wanmeixiaoyuan](https://github.com/yifeiyixiang/wanmeixiaoyuan) | 旧版 B1（`h5cloud:8080` + Cookie 直查 `getRoomState.do`） | 虚拟 deviceId 登录拿 Cookie | `getRoomState.do` | 否 | 未标注 / 2023-10-24 | ★★ 历史参考（端口已变 18443） |
| [lswlc33/jsit_wanmei_left_power_select](https://github.com/lswlc33/jsit_wanmei_left_power_select)、[wanxiao_power_monitor](https://github.com/lswlc33/wanxiao_power_monitor) | B2 参数拼法（`bizcontent` 示例、房间号编码规则） | **无需登录** | `smallpaygateway/trade` | 否 | Apache-2.0 / 未标注，2024 停更 | ★★ 只抄参数格式；**勿抄 128 线程批量扫** |
| [chuzong886/wanmeixiaoyuandianfeiyujin](https://github.com/chuzong886/wanmeixiaoyuandianfeiyujin) | 不是云缴费，是**加密版老引擎** `SWAEEncryptServlet`；若本校后续被迁到加密版时参考 | 无 | 加密 `SWAEServlet` | 否 | 未标注 / 2026-10-16 | ★★ 备用（第 4 顺位） |
| [ReaJason/17wanxiaoCheckin](https://github.com/ReaJason/17wanxiaoCheckin)（397★）、[fuqiuluo/wanxiao-campus](https://github.com/fuqiuluo/wanxiao-campus) | 登录协议（RSA→3DES→`campusSign`→session） | — | — | — | MIT / 未标注 | ★★★ 仅登录实现参考（B1 依赖它） |

> 其他「完美校园 电费」项目（zuwei522、chanlun3377、suiren0219、fanxingstarry 等）全部走老引擎，**对 FJTCM 不适用**，但它们的**推送/定时/阈值/工程骨架**可以照搬（见 §3.1~3.22）。

### 3.0.4 鉴权矩阵：到底要不要真密码 / 短信 / deviceId？有没有免登录入口？

| 能力 | 需要的鉴权 | 首次成本 | 之后是否可无人值守 | 免登录入口 |
|---|---|---|---|---|
| B2 `samllProgramGetRoomState` 查余额 | 无 | 抓一次缴费页链接（拿 4 个参数） | 是（参数固定） | **有** ✅ |
| B2 `samllProgramGetRoom` 找房间 | 无 | 同上 | 是 | **有** ✅ |
| B1 `CloudPayment/getRoomState.do` 查余额 | `SESSION` Cookie（来自登录后 `pay.do`）+ 正确 `Referer` | 账号密码（或短信），**新设备需一次短信验证**；`deviceId` 绑定 | 是（token 过期自动重登；`deviceId` 不丢） | 否（B1 无 login-free） |
| B1 登录本身 | 手机号+密码；新设备 `code_=5` 要短信 | 一次短信（`gainMatrixCaptcha543.action`，必须带 543 后缀） | 是（`deviceId` 存 `wanxiao_state.json`，换 IP 不再验证） | 否 |
| E `loginCheck`（如果有学校给的查询链接/落地页 params） | 无（用链接里的 `params`） | 复制一条学校给的链接 | 是（若链接长期有效） | **半免登录** |
| R goPay 充值 | B1 登录 token + 学校网关/收银台参数 | 账密+短信+抓包 | 是 | 否 |
| D WX 小程序 | WX code + openid + token → 302 → session | 需在微信环境抓包，且 code 难自动拿 | 很难 | 否 |

**关键结论：**
- **B2 完全没有登录概念**，只要缴费链接里的参数，理论上最稳定；担心的只是网关域名/项目 ID 变更。
- **B1 必须登录**，但 `deviceId` 是"受信设备"凭证：首次过后可长期免验证码（jialiangh 文档实测：绑定后换 IP 也不再要验证码）；代价是要保存手机号/密码或 token（加密存在本机）。
- **B1 没有免登录入口**：云缴费自身没有 login 接口（jialiangh 文档：「CloudPayment 自身没有任何 login 接口，必须持有有效 wanxiao token」），查余额必须先有登录态；唯一"半免登录"的是 E `loginCheck`（前提是你已有一条学校下发的查询链接）。

### 3.0.5 「学校网关 UUID / 参数」到底是什么、怎么拿

> 这里说的「学校网关 UUID」在这个生态里通常不是一个参数，而是下面几个标识的组合。**先把缴费页链接抓下来，一切就都有了。**

| 参数 | 含义 | 从哪拿 |
|---|---|---|
| `schoolcode` / `customerId` / `schoolno` | 学校在云缴费/云支付里的客户编码 | 缴费链接 `?customerId=XXXX`；**未必等于完美校园码 769**，以链接为准 |
| `payproid` | 「用电支出」缴费项目 ID（每年/每校可能不同） | 缴费链接 `#/billDetail?item={"id":<payproid>,"flag":2,...}` 的 `id` |
| `businesstype` / `flag` | 业务类型，用电一般 **2** | 同上 `flag` 字段 |
| `api_url` | 学校云支付网关地址 | 链接的 `https://<host>:<port>` + `/paygateway/smallpaygateway/trade` |
| `roomverify` | 房间 ID：`<校区ID>-<楼栋ID>--<楼层ID>-<房间号>` | B2 用 `samllProgramGetRoom` 逐级下钻（optype 1→2→3→4）；B1 用 `user/getRoom.do` 或历史缴费房间 |
| （B1）`customerId`/`payProId` | 登录后由项目列表/落地页 HTML 自动发现 | `bill/querySelfPayList.do` 的 `payprolist`；落地页隐藏域 `hostCustomerCode` |
| （充值）`uuid` | goPay 重定向里的交易单号（`T002...`），**不是学校标识** | goPay 302 Location 里 `"uuid":"T002..."` |
| （登录）`deviceId` | 完美校园"受信设备"ID（15 位 IMEI 形态） | 首次随机生成后保存；丢失要重新过短信 |

**标准获取流程（B2）**：
1. 完美校园 APP →「缴费」→「用电支出/预付费」→ 选房间页面 → 复制链接（或电脑端 F12/手机代理抓包）；
2. 链接形如：
   ```
   https://cloudpaygateway.<学校域名>:<端口>/pay/index.html?openId=...&token=...&customerId=<学校码>
   #/billDetail?item={"id":<项目ID>,"flag":2,"payproname":"用电支出",...}
   ```
3. 用 cyqmq 的 `tools/detect_config.py` 一键解析 + 交互式搜房 + 验证电量（纯标准库）：
   ```bash
   python tools/detect_config.py "粘贴你的缴费链接"
   ```
4. 输出 `schoolcode / payproid / businesstype / api_url / default_room`，填入脚本即可。

**标准获取流程（B1）**：不需要抓包，直接跑 `jialiangh/wanxiao_login.py login`（首次可能要 `sms-send`+`sms-code`），再 `electricity_monitor.py projects` 列出「用电支出」，用 `rooms --campus --building --room` 找 `roomverify`。

### 3.0.6 可直接复用的代码（原样）

#### (a) B2 免登录查询主链（来自 cyqmq，Python，可独立使用）

```python
# cyqmq/astrbot_plugin_wanmei_dorm_power/main.py L144-L188
async def _post(self, method: str, biz: dict) -> dict:
    """向云支付网关发起 POST，返回解析后的 JSON。"""
    payload = {
        "method": method,
        "bizcontent": json.dumps(biz, ensure_ascii=False),
        "timestamp": _now_ts(),          # time.strftime("%y-%m-%d %H:%M:%S")
        "sourceId": 2,
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(self._api_url, json=payload) as resp:
            if resp.status != 200:
                raise _ApiError(f"HTTP {resp.status}")
            data = await resp.json(content_type=None)
    if data.get("returncode") != "SUCCESS":
        raise _ApiError(data.get("returnmsg") or data.get("subMsg") or "接口返回失败")
    return data

async def _get_room_state(self, room_id: str) -> dict:
    """查询房间剩余电量。返回 businessData 字典。"""
    biz = {
        "payproid": self._payproid,
        "schoolcode": self._schoolcode,
        "roomverify": room_id,
        "businesstype": self._businesstype,   # 用电 = "2"
    }
    data = await self._post("samllProgramGetRoomState", biz)
    return data.get("businessData") or {}

async def _get_rooms(self, optype: int, areaid="0", buildid="0",
                     unitid="0", levelid="0") -> list:
    """获取房间级联列表：1校区/2楼栋/3楼层/4房间。"""
    biz = {
        "schoolno": self._schoolcode,
        "optype": optype,
        "payproid": self._payproid,
        "areaid": areaid, "buildid": buildid,
        "unitid": unitid, "levelid": levelid,
        "businesstype": self._businesstype,
        "idserial": "",
    }
    data = await self._post("samllProgramGetRoom", biz)
    return data.get("businessData") or []
```

等价的最小 curl（把 `<...>` 换掉即可，B2 调试用）：

```bash
curl -s 'https://cloudpaygateway.<学校域名>:<端口>/paygateway/smallpaygateway/trade' \
  -H 'Content-Type: application/json' \
  -H 'Origin: https://cloudpaygateway.<学校域名>:<端口>' \
  -H 'Referer: https://cloudpaygateway.<学校域名>:<端口>/pay/index.html' \
  --data '{"method":"samllProgramGetRoomState","bizcontent":"{\"payproid\":\"<项目ID>\",\"schoolcode\":\"769\",\"roomverify\":\"<房间ID>\",\"businesstype\":\"2\"}","timestamp":"26-11-05 22:50:00","sourceId":2}'
```
> 注意：`timestamp` 这个生态里 2 位年和 4 位年两种写法都有项目在用（cyqmq 用 `%y`，JustaSage 用 `%Y`），以实际返回为准；部分网关要用 `Origin`/`Referer`，失败先补。

#### (b) 缴费链接解析（来自 cyqmq `pay_url_parser.py`）

```python
GATEWAY_PATH = "/paygateway/smallpaygateway/trade"

def parse_pay_url(url: str) -> dict:
    base, _, frag = url.partition("#")
    parsed = urllib.parse.urlparse(base)
    query = urllib.parse.parse_qs(parsed.query)
    host = parsed.netloc
    schoolcode = ""
    for key in ("customerId", "customercode", "schoolcode", "schoolCode"):
        if query.get(key):
            schoolcode = query[key][0]; break
    api_url = f"https://{host}{GATEWAY_PATH}"
    payproid, businesstype, payproname = "", "", ""
    if "billDetail" in frag and "?" in frag:
        frag_query = urllib.parse.parse_qs(frag.split("?", 1)[1])
        item_str = frag_query.get("item", [""])[0]
        for raw in (urllib.parse.unquote(item_str), item_str):
            try:
                item = json.loads(raw); break
            except (ValueError, TypeError):
                continue
        if isinstance(item, dict):
            payproid = str(item.get("id") or "")
            businesstype = str(item.get("flag") or "")
            payproname = item.get("payproname") or ""
    return {"api_url": api_url, "schoolcode": schoolcode,
            "payproid": payproid, "businesstype": businesstype,
            "payproname": payproname}
```

#### (c) B1 CloudPayment 五步链（来自 jialiangh，Python；`wanxiao_login.py` 提供 token）

```python
# jialiangh/campus-electricity-monitor/electricity_monitor.py L44-L158（节选）
CP_BASE = "https://h5cloud.17wanxiao.com:18443/CloudPayment/"
WEB_UA = ("Mozilla/5.0 (Linux; Android 12; 24031PN0DC Build/V417IR; wv) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/110.0.5481.154 "
          "Safari/537.36 Wanxiao/5.8.9 Wmxy/5.8.27")
VERSIONCODE = "10589101"; VERSIONNUM = "1050827101"

class CloudPay:
    """必须用真正的 CookieJar：pay.do 是先 302 到 bill/type.do，
    并在这一跳下发 HttpOnly 的 SESSION，手工解析最终响应会丢。"""
    def __init__(self, schoolcode, timeout=25):
        self.schoolcode = str(schoolcode)
        self.jar = http.cookiejar.CookieJar()
        self.referer = CP_BASE + "bill/type.do"
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=CTX))

    def _get(self, path, referer=None, json_ok=False, **params):
        url = CP_BASE + path
        if params: url += "?" + urllib.parse.urlencode(params)
        h = {"User-Agent": WEB_UA,
             "Accept": ("application/json, text/javascript, */*; q=0.01"
                        if json_ok else "*/*"),
             "X-Requested-With": "XMLHttpRequest",
             "Referer": referer or self.referer}
        req = urllib.request.Request(url, headers=h)
        with self.opener.open(req, timeout=self.timeout) as r:
            return r.read().decode("utf-8", "replace")

    def sso(self, token):
        """token 有效才会下发 CloudPayment 的 SESSION cookie。"""
        self._get("user/pay.do", CP_BASE, versionnum=VERSIONNUM,
                  customerId=self.schoolcode, systemType="Android",
                  UAinfo="wanxiao", versioncode=VERSIONCODE, token=token)
        if not self.session_id():
            raise NoPowerData("token 未被 CloudPayment 接受（SSO 未下发 SESSION）")
        return self.session_id()

    def projects(self):
        return (json.loads(self._get("bill/querySelfPayList.do", json_ok=True))
                .get("payprolist") or [])

    def select_project(self, proj):
        params = dict(txcode=proj.get("txcode") or "",
                      interurl=proj.get("interurl") or "",
                      payProId=str(proj["id"]), amtflag=proj.get("amtflag") or "0",
                      payamt=proj.get("payamt") or "0",
                      payproname=proj.get("payproname") or "",
                      img=proj.get("img") or "", subPayProId="")
        # 服务端从 Referer 里的 payProId 反查 idserial，后续请求必须回传这条完整 URL
        self.referer = CP_BASE + "bill/selectPayProject.do?" + urllib.parse.urlencode(params)
        self._get("bill/selectPayProject.do", CP_BASE + "bill/type.do", **params)

    def room_state(self, proj, roomverify):
        raw = self._get("user/getRoomState.do", json_ok=True,
                        payProId=str(proj["id"]), schoolcode=self.schoolcode,
                        businesstype=proj.get("businesstype") or "2",
                        roomverify=roomverify)
        d = json.loads(raw)
        if str(d.get("returncode")) != "100":
            raise NoPowerData(f"getRoomState: {d.get('returnmsg') or raw[:120]}")
        return d
```

#### (d) 登录协议（B1 的前置；来自 ReaJason/jialiangh，多处一致）

```text
POST https://app.17wanxiao.com/campus/cam_iface46/exchangeSecretkey.action
  body {"key": "<RSA-1024 SPKI DER 的 base64，每 64 字符换行>"}
  → 用私钥 PKCS#1 v1.5 解密响应，得到 {session, key(32hex)}，appKey = key[:24]

之后所有业务请求：
  body = {"session": <session>, "data": <3DES-CBC(IV=66666666, PKCS#5) + base64>}
  header campusSign = sha256(请求体原文).hexdigest()
  header Content-Type: application/json
  password 字段：对密码**逐字符**分别 3DES 加密后 base64，组成数组
```

```text
# 新设备一次性短信（jialiangh docs 原文要点）
POST .../cam_iface46/gainMatrixCaptcha543.action     # 必须带 543 后缀！否则提交必失败 800114003
POST .../cam_iface46/registerUsersByTelAndLoginNew.action   # 提交验证码，同时把 deviceId 绑成受信设备
```

#### (e) 充值链（JustaSage `payment.py`，仅作参考；本校未验证）

```text
1  POST https://xqh5.17wanxiao.com/smartWaterAndElectricityService/goPay
       form: param={"cmd":"getPayInfo","thirdsource":"T002","token":...,"idserial":...,
                    "txcode":"51101","payamt":"<分>","schoolcode":...,"payaccnum":<roomverify>,...}
       → body.data.{url, jsonData, sign}
2  GET  {data.url}?jsonData=...&sign=...   (follow_redirects=False) → Location 里取 "uuid":"T002..."
3  POST https://cloudpaygateway.<学校域名>:<端口>/paygateway/smallpaygateway/trade
       {"method":"getPayInfoByUuid","bizcontent":"{\"uuid\":\"T002...\"}","sourceId":2,...}
4  POST 同上 /paygateway/paytrans/gateway  {"method":"callWapCashDeskData",...} → cashDeskData.orderInfo
5  POST https://<学校收银台域名>/WapCashDesk/prepayOrder  → paymsg.request_url（支付宝 WAP）
```

> `txcode`：电费 `51101`、冷水 `51201`、热水 `51301`（JustaSage 的映射，其他学校可能不同）；收银台域名/商户号是**学校自己的**，必须抓包确认（珠海为 `dk.zcst.edu.cn`、`merchantno=2020080539`，**不可照抄**）。

### 3.0.7 频率限制 / 封 IP / 封号 / 安全（云缴费线专项）

| 风险 | 证据/表现 | 应对 |
|---|---|---|
| 网关"频繁请求" | lswlc33 `wanxiao_api.py` 实测：响应含「频繁」，代码 `time.sleep(60)` 后重试 | 查询间隔 ≥1 小时；不要并发；每天 ≤8 次 |
| WAF 405 / `code_:9004` 熔断 | jialiangh 文档：「站点前面有 WAF，短时间请求过密会整个域名返回拦截页，几分钟内自愈」 | 低频；失败指数退避；不要秒级轮询 |
| 海外/云 IP 被封 | zuwei522 Issue #9（2025-07 海外服务器超时，国内正常；同月 Cloudflare worker 恢复）；snowf14k3 README「曾封杀国外 IP，现已恢复」；chanlun3377 README「阿里云 WAF 对 GitHub Actions/云厂商 IP 返 405」 | **家宽 / 树莓派 / 国内 VPS / 旧安卓挂机**；别用 GitHub Actions 当生产 |
| 登录风控 / 新设备 | `code_=5`「您正在新设备上使用完美校园，请使用验证码进行验证登录」；deviceId 未绑定则每次要短信 | 首次用 `gainMatrixCaptcha543` + 短信绑定；保存 `deviceId`（`wanxiao_state.json`） |
| 设备唯一性 | yifeiyixiang README：「完美校园就设备做了验证，只允许一个设备登录」；Andtun02 提醒「之后就不要再使用 APP 登录」 | 虚拟 deviceId 登录后，同一账号尽量不再用 APP 同时登录；或接受 App 被踢 |
| SESSION 过期 | DHKun：`RspBaseVO [code=ERROR, msg=系统繁忙...]`；Cookie 过期需重开缴费页 | 自动重登/WebView 静默续登；把"会话失效"与"系统繁忙"分开处理 |
| token 泄露 = 登录态 | jialiangh 文档：CloudPayment token 泄露能读姓名、证件号、手机号、绑定房间 | 本机加密存储；不提交 Git；不贴群 |
| 封号 | **未检索到公开"因查电费被封号"实锤**（GitHub Issue/博客均无）；只有 IP 限流、验证码、会话失效 | 仍按"违反用户协议/学校规定"风险对待：只查本人、不批量、不对外服务 |
| 充值白名单 | stmtc233 仅支持校码 1399；JustaSage 商户号/收银台为珠海专用 | 充值需要单独抓包/适配，不要默认能通用 |

### 3.0.8 分级结论：哪些直接抄、哪些必须抓一次包、哪些不要抄

| 等级 | 内容 | 说明 |
|---|---|---|
| ✅ **直接抄（零改造/小改参数）** | ① `cyqmq` 的 `pay_url_parser.py` + `tools/detect_config.py` + `_post/_get_room_state/_get_rooms`（B2 全套）② `jialiangh` 的 `wanxiao_login.py` + `CloudPay` 类（B1 全套，若走 B1）③ `Zuizhuban` 的 3DES/登录/pay.do/房间查询代码（B1 备选）④ Qmsg/Server酱/PushPlus/钉钉推送函数 ⑤ `chanlun3377`/`fanxingstarry` 的 cron/任务计划 + 阈值判断骨架 ⑥ 学校码表（`schools.csv`/`school_codes.json`） | 参数改成本校即可；B2 只需把缴费链接喂给 `detect_config.py` |
| 🔧 **必须由用户抓一次包/提供一次输入** | ① B2 的缴费页链接（网关 host:port、`customerId`、`payproid`、`flag`）② B1 的首次账密登录 + 新设备短信（`deviceId` 绑定）③ B1 的 `roomverify`（可用脚本下钻，无需抓包）④ 充值所需的学校收银台域名/商户号（如要做自动充值）⑤ 若只有微信小程序入口，则要在 WX 环境抓 code/openid | 这些是"外部世界才知道"的信息，无法从 GitHub 或学校代码表推出 |
| ❌ **不要抄 / 只作参考** | ① `lswlc33` 的 128 线程全校扫描（高频、易被封、也超出个人使用边界）② `chuzong886` 的预测引擎/自适应调度（几百行算法，第一期不需要）③ `Morii-torri`（非完美校园标准接口，只对上海工程技术大学）④ `ReaJason` 等打卡项目的业务功能（只借登录协议）⑤ 任何"批量查别人房间/公开别人数据/对外提供服务"的用法（违规 + 风控） | 合规与稳定性优先 |
| 🚫 **已确认不适用** | 老引擎 `SWAEServlet` 系全部项目（zuwei522/chanlun/fanxingstarry/Jursin/suiren/DragonYH/sctop/m5554/bingjuu/snowf14k3 等） | Lead 实测 769 → `8099 body格式错误`；保留作协议参考 |

**建议的落地顺序（给 task-3/Lead）**：
1. 用户抓一次缴费页链接 → 判断是 `cloudpaygateway.*`（B2）还是 `h5cloud:18443`（B1）；
2. 若是 B2：跑 `cyqmq` 的 `detect_config.py` → 拿到 4 参数 + 房间 ID → 写 `query.py`（B2 查询）+ 定时（cron/任务计划）+ 推送（PushPlus/Qmsg/钉钉）→ 完成；
3. 若是 B1：跑 `jialiangh` 的 `wanxiao_login.py login`（首次短信）→ `electricity_monitor.py projects/rooms/now` 验证 → 写查询/定时/推送；
4. 两条都失败：再考虑 chuzong886 加密版（若本校实际是加密智能水电）、或今日校园 WebView 逆向（成本高，不建议）；
5. 全程低频（≤8 次/天）、本机存凭据、日志脱敏。

---

> 以下 §3.1~§3.22 为**老引擎（SWAEServlet）项目**：对本校 FJTCM 大概率不可用（见 §7.0 实测 8099），仅作协议参考与其他学校复用。每个项目给：**接口调用方式（域名+路径+方法+关键参数/头）→ 鉴权 → 推送 → 定时 → 可复用代码（原样）→ 可用性结论**。

### 3.1 zuwei522/perfect-campus_electricity-alert（起点仓库，27★）

- 地址：https://github.com/zuwei522/perfect-campus_electricity-alert
- 形态：Shell + jq + GitHub Actions secrets；只查不充。
- **接口**：`POST https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet`
  - `Content-Type: application/x-www-form-urlencoded`（curl `-d` 默认）
  - 参数：`param={"cmd":"getbindroom","account":"<学号>"}`（URL 编码后）、`customercode=<学校码>`、`method=getbindroom`
  - 响应：`{"code_":0,"result_":"true","message_":"获取成功！","body":"{...}"}`，`body` 是被转义的 JSON 字符串，需二次解析。
- **鉴权**：无。只有学校码+学号。
- **推送**：Qmsg 酱 `POST https://qmsg.zendee.cn:443/send/<QMSG_KEY>`，`qq=&msg=`。
- **定时**：GitHub Actions `.github/workflows/main.yml`，`cron: "0 4,11 * * *"`（UTC，= 北京 12:00/19:00）。
- **可复用代码（原文）**：

```bash
# main.sh L9 —— 一条 curl 拿到绑定房间
body=$(curl -sd "param=%7B%22cmd%22%3A%22getbindroom%22%2C%22account%22%3A%22${STUDENT_ID}%22%7D&customercode=${SCHOOL_ID}&method=getbindroom" "https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet" | jq .body)
# 单房间没有 roomlist 键，用 detaillist[0].odd 兜底
roomOdd[$i]=$(echo $(echo $body | jq .detaillist[0].odd) | sed 's/"//g')
```

```yaml
# .github/workflows/main.yml L3-L4
on:
  schedule:
    - cron: "0 4,11 * * *"  # 世界协调时，相当于北京时间每天 12 点和 19 点各运行一次
```

- **学校码表**：`school-list.md`（1444 行，358 所学校），来源是完美校园官方 `open.17wanxiao.com/kdword_fl02.html`（**该官方页已下线**，DragonYH 仓库有带 sha256 校验的镜像）。**福建中医药大学 = 769（L849-850）**。
- **可用性/风险**：
  - 作者 2025-06 在 Issue #8 回复「我现在还是只用学校代码和学号两个参数就可以获取到数据，不需要 cookie」——老引擎至少对桂电北海等校仍可用。
  - **Issue #9（2025-07-04）**：「完美校园官方疑似封禁海外IP，致请求超时」——海外服务器请求一直卡住，国内服务器正常；2025-07-24 另一位用户（snowf14k3）留言「cloudflare worker 恢复」。说明**海外/云 IP 可能被临时封**。
  - Issue #3：单宿舍时无 `roomlist` 键导致解析为 0（已有 PR 修复，chanlun3377 等后续项目都兼容了）。
  - 无 LICENSE 文件（默认版权保留，只可学习参考，二次分发注意）。
  - 单房间假设、`printf` 四舍五入有边界误报（chanlun3377 README 已记录）。

### 3.2 Jursin/wanxiao-electric-apis（老引擎最佳接口文档）

- 地址：https://github.com/Jursin/wanxiao-electric-apis
- 形态：单文件 Python CLI（`wanxiao.py`）+ 解密脚本（`decrypt.py`）+ README 接口文档。
- **接口文档（原文提炼）**：
  - `POST https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet`
  - 请求头：`Content-Type: application/x-www-form-urlencoded`、`X-Requested-With: com.newcapec.mobile.ncp`、`Origin: https://xqh5.17wanxiao.com`、`Referer: https://xqh5.17wanxiao.com/userwaterelecmini/index.html`
  - 请求体：`param={"cmd":"接口","account":"学号",...}`、`customercode=学校编码`、`method=接口`、`command=OWNWaterElecService`（**注意：Jursin 用 `OWNWaterElecService`，zuwei522/chanlun 不传 command 或传 `JBSWaterElecService`，两种都能通，说明 command 与学校/业务有关**）
  - `method` 与 `param.cmd` 必须一致；`param` 内除 `cmd`、`account` 外是各接口自己的参数。
  - 响应：`{"code_":0,"result_":"true","message_":"获取成功！","body":"{...}"}`；`result_ != "true"` 抛错；`body` 二次 `json.loads`；`body.result`（`"0"` 成功）。
  - 接口清单：`getbindroom`（绑定房间；`existflag` 1 单房间 / 2 多房间，`roomverify`、`detaillist[].businesstype`、`use`/`odd`）；`h5_getstuindexpage`（首页：`devicename`、`todayuse`、`odd`、`price`、`weekuselist`、`monthuselist`、`sumbuy`、`linestatus`、`isshowpay`）；`gettimeusedetail`（区间用量，`YYYY-MM-DD`）；`getusedetail`（月度用量，`YYYY-MM`）。
  - **获取 `customercode` 的技巧**（README 原文）：从 APP 打开「智能水电」时 `AloneEntrance` 请求响应头的 `location` 里有 `customerid`；或用 `decrypt.py` 解 APP/微信小程序抓包的 `SWAEEncryptServlet` 请求体。
- **可复用代码（原文）**：

```python
# wanxiao.py L41-L62
def call(self, method, **kw):
    param = {"cmd": method, "account": self.account, **kw}
    data = {
        "param": json.dumps(param, ensure_ascii=False),
        "customercode": self.customercode,
        "method": method,
        "command": COMMAND,
    }
    resp = requests.post(BASE_URL, data=data, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    r = resp.json()
    if r.get("result_") != "true":
        raise RuntimeError(r.get("message_") or r)
    body = r.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            pass
    if not isinstance(body, dict):
        raise RuntimeError(f"返回数据格式异常: {body!r}")
    return body
```

```python
# decrypt.py 全文 —— 解 SWAEEncryptServlet 抓包请求体
import base64
from urllib.parse import parse_qsl
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

def decrypt(body):
    form = dict(parse_qsl(body.strip(), keep_blank_values=True))
    cipher = base64.b64decode(form["encryptData"])
    ts = str(form["timestamp"])
    key = ((ts[:6] if int(ts) % 2 else ts[-6:]) + form["randomStr"]).encode()
    return unpad(AES.new(key, AES.MODE_ECB).decrypt(cipher), AES.block_size)
```

> 注意：`decrypt.py` 的奇数/偶数判断是 `int(ts) % 2`，而 chuzong886 PHP 实现是 `((int)$stamp % 8) % 2`（等价于 `%2`），两者一致。**key 的取法：时间戳奇数取前 6 位、偶数取后 6 位，再拼 10 位 randomStr，得到 16 字节 AES-128 密钥。**

- **可用性**：2026-10-07 仍在更新，说明老引擎仍活；无 LICENSE；README 无失效声明。**最适合作为「老引擎 backend」的代码底稿。**

### 3.3 chanlun3377/campus-electricity-alert（本地化重构 + WAF 踩坑记录）

- 地址：https://github.com/chanlun3377/campus-electricity-alert （MIT，2026-10-01 更新，0★）
- 形态：Python + Windows 任务计划；多房间；Qmsg。
- **接口**：同 3.1（`getbindroom`），`alert.py` 里显式带 UA 和 `Referer: https://xqh5.17wanxiao.com/`。
- **可复用代码（原文）**：

```python
API_URL = "https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet"
data = {
    "param": json.dumps({"cmd": "getbindroom", "account": STUDENT_ID}),
    "customercode": SCHOOL_ID,
    "method": "getbindroom",
}
resp = requests.post(API_URL, headers=HEADERS, data=data, timeout=15)
raw = resp.json()
body = json.loads(raw["body"])
rooms = body.get("roomlist", [])
if not rooms and body.get("detaillist"):
    rooms = [body]          # 兼容单房间
```

- **最有价值的踩坑记录（README 原文，逐字）**：
  > 1. **WAF 拦截**：目标接口部署了阿里云 WAF，GitHub Actions 和云服务商 IP 全部返回 405。最终采用**本地住宅 IP + 任务计划**方案绕过，这也是本项目从 shell 脚本 + GitHub Actions 重构为 Python + Windows 任务计划的根本原因。
  > 2. **数据格式异构**：原作者用 `sed` / `printf` 处理嵌套 JSON，遇到不同学校的返回结构必然崩溃。重构为 Python `json.loads`，对 `roomlist` / `detaillist` 两种结构都做了兼容。
  > 3. 中文编码：Windows Git Bash 处理中文变量会出现 GBK/UTF-8 混乱。
  > 4. **边界误报**：`printf` 四舍五入导致 14.6 度被误判为 15 度不告警，改用 float 精确比较。
  > 5. 空值与异常数据：`odd` 为空/`"null"` 时跳过，不崩整个流程。
- **可用性**：2026-10 更新，作者本人已实测「住宅 IP 可用、云 IP 405」；**这是选择部署位置的第一手证据**。

### 3.4 fanxingstarry/perfect-campus-electricity-alert（Docker + 钉钉）

- 地址：https://github.com/fanxingstarry/perfect-campus-electricity-alert （MIT，2026-10-16，0★）
- 形态：Python + APScheduler + Docker/compose；钉钉自定义机器人（加签）。
- **接口**：同 `SWAEServlet`；与环境变量 `SCHOOL_ID / STUDENT_ID / ROOM_VERIFY / DINGTALK_ACCESS_TOKEN / DINGTALK_SECRET` 组合。
- **可复用代码（原文）**：

```python
url = "https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet"
payload = {
    "param": json.dumps({
        "cmd": "h5_getstuindexpage",
        "roomverify": room_verify,
        "account": student_id,
    }),
    "customercode": school_id,
    "method": "h5_getstuindexpage",
    "command": "JBSWaterElecService",
}
headers = {"User-Agent": "python-requests/3.x",
           "Content-Type": "application/x-www-form-urlencoded"}
resp = requests.post(url, data=payload, headers=headers, timeout=timeout)
j = resp.json(); body = j.get("body") or j
# body 可能是被转义的字符串，需 safe_json_loads_once 处理
odd_value = body['modlist'][1]['odd']          # ⚠️ 硬编码下标 1，多模块学校可能取错
has_money = round(0.62 * odd_value, 2)         # ⚠️ 电价硬编码 0.62 元/度
```

- **可用性**：代码新；但有两个隐含假设（`modlist[1]` 是电表、电价 0.62），**不同学校需改**。Docker 交付形态值得抄（`compose.yaml`+`Dockerfile`+`.env.example`）。

### 3.5 m555455445/Perfect-Campus_Electricity-Warning（早期 JS/Actions 版）

- 地址：https://github.com/m555455445/Perfect-Campus_Electricity-Warning （2023-11-30，未标注 License）
- **接口**：同 `SWAEServlet`；`param={"cmd":"getbindroom","account":"<学号>","timestamp":"00000000000000000"}`，`method=getbindroom&command=JBSWaterElecService`。
- 双阈值（`alert_threshold` 低电 / `alert_superthreshold` 即将停电），推送优先级 微信(Server酱)>QQ(Qmsg)>钉钉 webhook；Actions 每天 11/17 点。
- **可复用代码（原文）**：

```javascript
const postData = `param=${param}&customercode=${school_id}&method=getbindroom&command=JBSWaterElecService`;
axios.post('https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet', postData, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
}).then(response => {
    const data = response.data;
    if (data.message_ === '获取成功！') {
        const body = JSON.parse(data.body);
        electric = body.detaillist[0].odd;
        roomfullname = body.roomfullname;
    }
});
```

- **可用性**：停更 2 年，但接口层没变；仅支持单房间（`detaillist[0]`），多房间会错。适合当「最短可用脚本」参考。

### 3.6 suiren0219/astrbot_plugin_dorm_power（工程化最强，推荐抄结构）

- 地址：https://github.com/suiren0219/astrbot_plugin_dorm_power （MIT，2026-10-25，1★，main.py 76KB）
- 核心价值不在接口（也是 SWAEServlet），而在**工程细节**：
  - **账号是完美校园 outid（一般是身份证号）不是学号**；`/电量绑定 <学校代码> <账号>`。
  - 敏感信息加密落盘：优先 Fernet/AES，没 `cryptography` 用内置 PBKDF2；日志脱敏（首尾各隐 4 位）；历史里房间主键用 HMAC 摘要，不落明文 `roomverify`。
  - **搜校限速防风控**：默认 6 并发 + 6 QPS + 随机抖动、连续失败冷却、熔断、历史命中代码池（旧版 24 并发扫 1.3 万代码被封）。
  - 连接复用（aiohttp session）+ 网络错误/429/5xx 指数退避；业务失败（`result_ != true`）不重试也不计入熔断。
  - 接口地址/command/各 cmd 名/电量字段全部可配置（上游改字段不用改代码）。
  - 解析容错：`body` 是字符串或对象、字段改名、首个模块无电量都能处理，并给出干净错误原因。
- **可复用代码（原文）**：

```python
# main.py L942-L981
async def _post(self, customercode: int, param: dict, timeout_s: int = 10,
                retries: int = 1) -> dict:
    """发请求：复用全局 session；网络错误 / 429 / 5xx 按指数退避重试。"""
    url = self._cfg_get("api_url") or API_URL
    command = self._cfg_get("api_command") or "JBSWaterElecService"
    payload = {"param": json.dumps(param, ensure_ascii=False), "customercode": customercode,
               "method": param["cmd"], "command": command}
    for attempt in range(retries + 1):
        if attempt:
            await asyncio.sleep(0.6 * (2 ** (attempt - 1)) * (0.7 + random.random() * 0.6))
        try:
            async with _Http.session().post(
                    url, data=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout_s)) as resp:
                if resp.status in RETRY_STATUS:
                    raise _ApiStatusError(f"HTTP {resp.status}")
                outer = await resp.json(content_type=None)
            break
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError) as e:
            last = e
    ...
    if outer.get("result_") != "true":
        raise _ApiResultError(f"接口返回失败: {outer.get('message_')}")
```

```python
# secure_store.py L228-L232 —— 历史记录中房间不可逆主键
def room_key(secret: str | None, roomverify: str) -> str:
    if not secret:
        return roomverify
    return "rk_" + hmac.new(secret.encode(), f"room|{roomverify}".encode(), hashlib.sha256).hexdigest()
```

- **可用性**：2026-10 活跃，README 明确「接口无需登录态」「随时可能变更，已把地址/命令/字段做成配置」。**建议作为本项目的工程骨架参考（多房间、配置化、限速、加密存储）。**

### 3.7 DragonYH/astrbot_plugin_wanxiao_electricity（学校码表 + 水电同查）

- 地址：https://github.com/DragonYH/astrbot_plugin_wanxiao_electricity （AGPL-3.0，2026-07-21，0★）
- 亮点：
  - `school_codes.json`（21KB，358 条），来源是官方 `kdword_fl02.html` 的结构化快照 + `zuwei522/school-list.md` 固定 revision 镜像 + Apifox 转录，**带 record_count/sha256 校验**（README L40 说明「官方地址当前已不可用」）。**福建中医药大学 code=769 在 L227。**
  - 多账号、水电同查（`businesstype` 0=电、1=水），并发上限 2，单房间失败不阻断其他房间。
  - 用查询参数放 `params=`（aiohttp `session.post(API_URL, params=params)`），和大多数项目放 form body 不同但等价。
- **可用性**：2026-07 更新；AGPL 传染性注意（如果直接融入自己的项目并分发，需开源）。

### 3.8 sctop/astrbot_plugin_perfect_campus_zqu_query（肇庆学院）

- 地址：https://github.com/sctop/astrbot_plugin_perfect_campus_zqu_query （AGPL-3.0，2026-09-02，1★）
- 结构：`wmxy_client.py`（aiohttp + pydantic 模型）+ `cron_scheduler.py` + `main.py`。接口同老引擎。
- 价值：**pydantic 建模**（`RoomResult`/`RoomResultDetailListEntry` 字段注释含 `businesstype` 0电/1水、`odd` 剩余、`use` 已用、`sumbuy` 累计购买）适合照抄数据结构。

### 3.9 snowf14k3/electricity-alert（Cloudflare Workers 在线版）

- 地址：https://github.com/snowf14k3/electricity-alert （MIT，2025-07-29，2★）
- 形态：Workers + D1（订阅用户表）+ Worker-Mailer SMTP 发邮件；`wrangler.toml` 里 `[triggers] crons = ["0 4,11 * * *"]`。
- **接口（原文）**：

```typescript
// src/index.ts L267-L273：查绑定房间
const response = await fetch("https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet", {
  method: "POST",
  headers: { "Content-Type": "application/x-www-form-urlencoded" },
  body: `param=%7B%22cmd%22%3A%22getbindroom%22%2C%22account%22%3A%22${xh}%22%7D&customercode=${code}&method=getbindroom`
});
// L210-L216：查首页/周用量（注意这里用的是 getstuindexpage，不是 h5_ 前缀）
body: `param=%7B%22cmd%22%3A%22getstuindexpage%22%2C%22roomverify%22%3A%22${roomverify}%22%2C%22account%22%3A%22${xh}%22%2C%22timestamp%22%3A%22${timestamp}%22%7D&customercode=${code}&method=getstuindexpage`
```

- **README 关键信息**：
  - 「完美校园曾封杀过国外 ip，导致系统无法使用（现已恢复）」——与 zuwei522 Issue #9 互相印证。
  - Cloudflare Workers 禁 25 端口，发信要用 587/465；并发限制可能丢邮件。
- **可用性**：2025-07 之后没更新；Workers 方案**部署成本最低但 IP 风险最高**。

### 3.10 bingjuu/wxeleTool（微信群插件）

- 地址：https://github.com/bingjuu/wxeleTool （2024-11-28，2★，Python；依赖 chatgpt-on-wechat）
- 接口：老引擎 `h5_getstuindexpage`（account + customercode），解析 `body.modlist` 取 `odd`、`weekuselist[].dayuse`。
- 附带 `test_customercode.py`：填 customercode 后可单独测一个学号能否查（**学校码验证脚本**）。可复用代码：

```python
# test_customercode.py L30-L59（节选）
url = "https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet"
data = {"param": f'{{"cmd":"h5_getstuindexpage","account":"{account}"}}',
        "customercode": {customercode}}
response = requests.post(url, headers={}, data=data, proxies=None, verify=True)
if response.status_code == 200:
    response_data = response.json()
    if response_data.get("code_") == 0:
        body = json.loads(response_data["body"])
        room_number = body.get('roomfullname', [])
        for item in body.get("modlist", []):
            if 'odd' in item: current_power = item['odd']
            if 'weekuselist' in item: weekuselist = item['weekuselist']
```

> 注意：README 里写的官方学校码页 `https://open.17wanxiao.com/kdword_fl02.html` 已下线（见 3.7），现在只能靠仓库内的表。

### 3.11 chuzong886/wanmeixiaoyuandianfeiyujin（「天枢」，加密版 + 预测，2026-10）

- 地址：https://github.com/chuzong886/wanmeixiaoyuandianfeiyujin （PHP，2026-10-16，1★，PHP+MySQL，宝塔部署）
- 形态：完整系统（注册登录/多账户/多宿舍/通知通道/预测引擎），代码 3.0.2 脱敏开源；无 LICENSE 文件。
- **接口：加密版 `SWAEEncryptServlet`**（这是它与上面所有老引擎项目的最大区别）：
  - `POST https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEEncryptServlet`
  - form：`encryptData=<AES-128-ECB 密文 base64>`、`timestamp=<毫秒时间戳>`、`randomStr=<10 位 A-Z0-9>`、`method=<方法>`
  - 头：`Origin: https://xqh5.17wanxiao.com`、`Referer: https://xqh5.17wanxiao.com/userwaterelecmini/index.html`、`X-Requested-With: com.newcapec.mobile.ncp`
  - 明文 = 外层 JSON：`{"param":"{\"cmd\":\"getbindroom\",\"account\":\"...\",\"timestamp\":\"...\"}","customercode":"<学校码>","method":"getbindroom","command":"<JBSWaterElecService 或自定义>"}`
  - 若响应里也带 `encryptData`，用同一规则（响应里的 timestamp/randomStr）解密。
- **可复用代码（原文）**：

```php
// app/core.php L43 —— 密钥规则：时间戳 %8 的奇偶决定取前6位还是后6位
function campus_key(string $stamp,string $random): string {
    if(!preg_match('/^[0-9]{6,16}$/D',$stamp)||!preg_match('/^[A-Z0-9]{10}$/D',$random))
        throw new AppError('校园加密参数无效');
    return (((int)$stamp%8)%2?substr($stamp,0,6):substr($stamp,-6)).$random;
}

// app/core.php L49-L58 —— 查询主流程
function query_campus(array $m): array {
    $stamp=(string)(int)floor(microtime(true)*1000);            // 13 位毫秒时间戳
    $alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';$random='';
    for($i=0;$i<10;$i++)$random.=$alphabet[random_int(0,35)];
    $inner=['cmd'=>'getbindroom','account'=>unseal($m['account_secret']),'timestamp'=>$stamp];
    $outer=['param'=>json_value($inner),'customercode'=>$m['school_code'],
            'method'=>'getbindroom','command'=>$m['command']];
    $encrypt=openssl_encrypt(json_value($outer),'aes-128-ecb',campus_key($stamp,$random),0);
    [$code,$reply]=http_post('https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEEncryptServlet',
        ['encryptData'=>$encrypt,'timestamp'=>$stamp,'randomStr'=>$random,'method'=>'getbindroom'],
        true,
        ['Origin: https://xqh5.17wanxiao.com',
         'Referer: https://xqh5.17wanxiao.com/userwaterelecmini/index.html',
         'X-Requested-With: com.newcapec.mobile.ncp']);
    if($code!==200)throw new AppError('校园 HTTP 查询失败');
    if(!empty($reply['encryptData'])){
        $plain=openssl_decrypt((string)$reply['encryptData'],'aes-128-ecb',
            campus_key((string)($reply['timestamp']??''),(string)($reply['randomStr']??'')),0);
        $reply=$plain===false?null:json_decode($plain,true);
    }
    ...
}
```

- 其他可抄点：
  - **「从抓包解析配置」**：用户粘贴一条抓包（表单/HAR/curl/已解密 JSON），系统自动解出 `school_code/account/roomverify/command`，先预览再确认，不重放旧密文（`抓包解析使用说明.md`）。
  - 查询策略：默认窗口 08:00–22:00、每日最多 8 次、最短间隔 60 分钟，风险升高才提前；应急通知≥6h 冷却、每天最多 2 组。
  - 通知：Spug 五字段模板（标题/等级/对象/时间/内容）+ Webhook/SMTP；手机号注册 + 阿里云 ESA 验证码。
  - 预测引擎（6/24/48h 专家、首达时间、自适应调度）**属于锦上添花，不建议第一期抄**（复杂度极高）。
- **可用性**：2026-10 最新更新，代码自洽；但**它假设你学校已经切到加密终点**，普通学校用不上；且无 LICENSE。**如果实测发现 769 的老引擎返回「获取成功但 existflag=0」或明文调用被拒，就说明可能已加密化，这个仓库是解码参考。**

### 3.12 JustaSage/ZCST_FEE_Bot（SSO + loginCheck + 充值，珠海科技学院）

- 地址：https://github.com/JustaSage/ZCST_FEE_Bot （AGPL-3.0，2026-06-13，5★，Python）
- 路线：**学校 SSO/CAS 登录 → 拿到完美校园落地页 `https://xqh5.17wanxiao.com/userwaterelecmini/index.html#/?params=...` → `loginCheck` 换会话 → SWAEServlet 查余额**；带充值（goPay→支付宝 WAP）与到账轮询。
- **关键接口（README 原文 + fetcher.py）**：
  - `POST https://xqh5.17wanxiao.com/smartWaterAndElectricityService/loginCheck`，form `data=<params>`
  - 响应 `resultdata` 用 **AES-128-ECB / PKCS7，密钥硬编码 `1234567812345678`** 解密，得到 `body.data` → `{customerCode/customerid, command, outid/userid}`
  - 然后用这套 `customercode/command/account` 调 `SWAEServlet`（明文 `param`），拿 `modlist[].busnesstype` 区分电/冷水/热水（0/1/2）。
- **可复用代码（原文）**：

```python
# fetcher.py L77-L112
_AES_KEY = b"1234567812345678"

def _aes_decrypt(data_b64: str) -> str:
    """AES-ECB / PKCS7 解密，用于 loginCheck 返回的 resultdata。"""
    cipher = Cipher(algorithms.AES(_AES_KEY), modes.ECB(), backend=default_backend())
    decryptor = cipher.decryptor()
    raw = decryptor.update(base64.b64decode(data_b64)) + decryptor.finalize()
    pad_len = raw[-1]
    return raw[:-pad_len].decode("utf-8")

async def _login_check(client, params):
    r = await client.post(f"{_API_BASE}/loginCheck", data={"data": params})
    resp = r.json()
    decrypted = _aes_decrypt(resp["resultdata"])
    payload = json.loads(decrypted)
    body = json.loads(payload["body"])
    return body["data"]     # {customerCode, command, outid/userid}
```

```python
# fetcher.py L115-L140 —— 明文 SWAEServlet 调用（拿到 loginCheck 的 3 个字段后）
payload["account"] = account
payload["timestamp"] = _timestamp()          # "%Y%m%d%H%M%S"
body = {"param": json.dumps(payload), "customercode": customercode,
        "method": payload["cmd"], "command": command}
r = await client.post(f"{_API_BASE}/SWAEServlet", data=body)
resp = r.json()
return json.loads(resp["body"])
```

- **可用性**：2026-06 更新；AGPL。**价值：证明「学校给的公开查询链接」可以转成一条免抓包的登录链；且 loginCheck 的 AES 密钥是固定的，不需要模拟登录。** 若本校有类似「链接/二维码」入口（缴费页、公众号链接），优先考虑这条。

### 3.13 jialiangh/campus-electricity-monitor（云缴费路线最佳文档，2026-10，MIT）

- 地址：https://github.com/jialiangh/campus-electricity-monitor （MIT，2026-10-15，2★）
- 形态：`wanxiao_login.py`（纯账密登录）+ `electricity_monitor.py`（CloudPayment 五步取数 + SQLite + 周报/低电提醒）+ cron；推送 PushPlus。
- **必须先读的 `docs/接口说明.md`（本报告最重要的单一来源，以下为原文要点）**：

```
## 先分流：你的学校走哪条产品线
| | 老引擎 SWAEServlet | CloudPayment |
| 域名 | xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet | h5cloud.17wanxiao.com:18443/CloudPayment/ |
| 鉴权 | 不需要 token，只校验学校代码 + 学号 | 需要 wanxiao token 换 SESSION |
判断方法：直接问老引擎。返回 existflag:"0" / 未绑定房间，说明你们学校的宿舍电表
不挂这代系统，走 CloudPayment（也就是本项目走的路）。

## 登录协议
RSA-1024 自生成密钥对
  -> exchangeSecretkey.action  { "key": <SPKI DER 的 base64> }
  -> 用私钥 PKCS#1 v1.5 解密响应，得到 { session, key(32hex) }，appKey = key[:24]
  -> 之后所有业务体：3DES-CBC(IV=b"66666666", PKCS#5) + base64
  -> 外层信封恒为 { "session": sid, "data": <b64> }，Content-Type: application/text
  -> 请求头 campusSign = sha256(请求体原文).hexdigest()
  -> password 字段是逐字符分别 3DES 加密后 base64 的数组

## CloudPayment 取数链（基址 https://h5cloud.17wanxiao.com:18443/CloudPayment/，全部 GET）
1 user/pay.do?versionnum=…&customerId=<schoolcode>&systemType=Android
  &UAinfo=wanxiao&versioncode=…&token=<握手session>     → 302 并下发 HttpOnly SESSION
2 bill/type.do
3 bill/querySelfPayList.do            → payprolist（用电支出 / 购冷水支出）
4 bill/selectPayProject.do?txcode=…&payProId=…&…          → 建立会话上下文
5 user/getRoomState.do?payProId=…&schoolcode=…&businesstype=2&roomverify=<校区-楼栋--楼层-房间>
  → {"returncode":"100","quantity":"110.0","quantityunit":"度","description":"616"}
```

- **三个隐蔽要求（原文）**：
  1. **Referer 参与鉴权**：服务端从 `Referer` 的 `payProId` 反查 `idserial`；缺第 4 步或 Referer 不对，返回 `RspBaseVO [code=ERROR, msg=系统繁忙，请稍后重试]`（看起来像挂了，其实是少一步上下文）。
  2. **Cookie 必须用真正的 CookieJar**：`pay.do` 是先 302、在**那一跳**下发 SESSION 的；手解析最终响应的 `Set-Cookie` 会丢。
  3. **token 有效性只能靠项目列表判断**：token 无效时服务端不报错，照样发匿名 SESSION、返回 200 HTML、`payprolist` 为 `null`；唯一可靠探针是「项目列表非空」。
- **其他原文要点**：
  - token = 本次登录的**握手 session**，不是响应体里的 `user.token`（后者是账号级固定值，拿去 SSO 会被拒）。
  - 新设备风控：`code_=5`「您正在新设备上使用完美校园，请使用验证码进行验证登录」，**校验在密码校验之前**；绑定必须用 `gainMatrixCaptcha543.action`（**必须带 543 后缀**，不带也会回「发送成功」但提交必失败 `800114003`）；验证码绑在发起那次的 session 上（发短信与提交验证码必须复用同一 session + appKey）。绑定后**风控只看 deviceId，换 IP 也不再要验证码**（因此可服务器无人值守）。
  - 房间树：`user/getRoom.do?payProId=…&schoolcode=…&businesstype=2&optype=1|2|3|4&areaid=&buildid=&unitid=&levelid=`；`optype=4` 返回的 `id` **已经是拼好的 roomverify**（形如 `101-07--112-308`），不要再拼。
  - 「HTTP 405 / 熔断 `code_:9004`」是 WAF；每小时 1 次远低于阈值。
  - 账号是**手机号**（不是学号）；`deviceId` 存 `wanxiao_state.json`，拷到服务器可免二次验证码。
  - 隐私：token/deviceId 等同密码；CloudPayment 的 token 泄露 = 交出登录态（能读姓名、证件号、手机号、房间）。
- **可复用代码**：见仓库 `wanxiao_login.py`（完整 RSA/3DES/验证码实现）与 `electricity_monitor.py`（五步链 + SQLite 台账 + 时段分摊）。
- **可用性**：2026-10 更新、MIT、文档质量最高。**如果 FJTCM 走云缴费，这是首选底稿。**

### 3.14 Zuizhuban/wanxiao-electricity-alert（云缴费单文件 Node，2026-10）

- 地址：https://github.com/Zuizhuban/wanxiao-electricity-alert （2026-10-12，0★，JS，724 行单文件）
- 适用场景（文件头原文）：**「你学校的电费在完美校园里是『首页 → 缴费 → 预付费 → 用电支出 → 选房间』看的，而不是『智能水电』里看的」**——与 FJTCM 官方「线上缴费→预付费→用电支出」的说法高度吻合。
- 流程：`exchangeSecretkey.action`（RSA-1024）→ `loginnew.action`（3DES-CBC，IV=66666666，逐字符加密密码）→ `pay.do?token=<session>` 换 `SESSION`（**手动 redirect，抓 302 那一跳的 Set-Cookie**）→ `bill/querySelfPayList.do` 找「用电支出」`payProId` → `bill/selectPayProject.do`（Referer 来源）→ `getRoomState.do` 查 `quantity`。
- 设备 ID：随机 IMEI，验证过一次后存本地 `wanxiao-device.json`；新设备风控时走 `--send-sms-only` + `--sms-login`。
- 其他能力：从缴费页 HTML 自动发现 `hostCustomerCode`（云缴费学校码）与历史缴费房间 `roomverify`；`--selftest` 只做密钥交换，不碰账号；内置 Qmsg 推送。
- **可复用代码（原文）**：

```javascript
// 3DES-CBC / PKCS7，密钥 24 字节，IV 固定 66666666
function des3Encrypt(plain, appKey) {
  const key = Buffer.from(String(appKey).slice(0, 24), "utf8");
  const cipher = crypto.createCipheriv("des-ede3-cbc", key, Buffer.from(DES_IV, "utf8"));
  return Buffer.concat([cipher.update(String(plain), "utf8"), cipher.final()]).toString("base64");
}

// 统一加密上行
async function encryptedPost(url, secret, payload, debugName) {
  const data = des3Encrypt(JSON.stringify(payload), secret.appKey);
  const bodyText = '{"session": ' + JSON.stringify(secret.session) + ', "data": ' + JSON.stringify(data) + "}";
  const res = await fetch(url, { method: "POST",
    headers: { "User-Agent": DEFAULT_UA, "Content-Type": "application/json",
               campusSign: sha256Hex(bodyText) },
    body: bodyText });
  return res.json();
}

// 换取云缴费 SESSION（redirect: manual 才能在 302 这一跳拿到 Set-Cookie）
async function getCloudCookie(token) {
  const params = new URLSearchParams({ customerId: String(1000 + Math.floor(Math.random() * 999)),
    systemType: "android", UAinfo: "wanxiao", versioncode: cfg.appVersion, token });
  const res = await fetch(PAY_DO + "?" + params.toString(), { redirect: "manual", headers: {...} });
  const setCookie = res.headers.get("set-cookie") || "";
  const m = /SESSION=[^;]+/.exec(setCookie);
  if (!m) throw new Error("没能拿到 SESSION cookie（HTTP " + res.status + "），可能是 token 无效或接口变了");
  return { cookie: m[0], html: await (await fetch(new URL(res.headers.get("location"), PAY_DO), {headers:{Cookie:m[0]}})).text() };
}

// 查某房间剩余电量
async function roomState(cookie, payProId, schoolCode, roomVerify) {
  const q = new URLSearchParams({ payProId, schoolcode: schoolCode, businesstype: "2", roomverify: String(roomVerify) });
  return cloudGet(GET_ROOM_STATE + "?" + q.toString(), cookie, payProId); // GET_ROOM_STATE = CLOUD_BASE + "/CloudPayment/user/getRoomState.do"
}
```

- 响应解析：`{"returncode":"100","quantity":"169.82","quantityunit":"度","description":"616"}`；`quantity` 为空/`-1` 视为无效。
- **可用性**：2026-10 最新，单文件零依赖（Node 18+），自带 selftest，**适合快速验证本校是否走云缴费**。

### 3.15 DHKun/xzmu-electricity-monitor（云缴费 getRoomState + Cookie/Referer，Kotlin）

- 地址：https://github.com/DHKun/xzmu-electricity-monitor （MIT，2026-10-31，2★）
- README 明确写出接口形态（原文）：

```
GET https://h5cloud.17wanxiao.com:18443/CloudPayment/user/getRoomState.do
    ?payProId=<项目ID>&schoolcode=<学校编码>&businesstype=2&roomverify=<房间校验码>

→ {"returncode":"100","quantity":"250.0","quantityunit":"度","canbuy":"true","description":"XXX房间"}
```

- 要点（原文提炼）：
  - 服务器要求请求**同时**携带 `Cookie`（会话）和 `Referer`（缴费页地址），缺一个都返回「系统繁忙」。
  - `roomverify` 编码楼栋-楼层-房间（`101-1--9-XXX`），换房间需重新抓包。
  - Cookie 会过期，过期后重开一次缴费页面即可续期。
  - 安卓 App 用隐藏 WebView 打开 `open.17wanxiao.com/api/authorize?...` 做**静默续登**（会话还在时直接换新会话，否则自动填账密提交）——这是「长期稳定」的关键工程。
- **可复用代码（原文）**：

```kotlin
fun roomStateUrl(payProId: String, roomVerify: String) =
    "https://$HOST:$PORT/CloudPayment/user/getRoomState.do" +
            "?payProId=$payProId&schoolcode=$SCHOOL_CODE&businesstype=2&roomverify=" +
            URLEncoder.encode(roomVerify, "UTF-8")

// 失效会话的实测响应：HTTP 200 + "RspBaseVO [code=ERROR, msg=系统繁忙...]"
if (text.startsWith("RspBaseVO") && "code=ERROR" in text) {
    return failure(Kind.SESSION_SUSPECT, "会话可能已失效", setCookies)
}
```

- **可用性**：2026-10 更新；App 侧能稳定跑，说明**持有有效 SESSION 时云缴费接口很稳**；难的是维持登录态。

### 3.16 cyqmq/astrbot_plugin_wanmei_dorm_power（学校云支付网关，免 token）

- 地址：https://github.com/cyqmq/astrbot_plugin_wanmei_dorm_power （2026-10-26，0★，Python）
- 适用场景（README 原文）：**「宿舍电量不在『智能水电』页展示，而是显示在完美校园云支付缴费页（如 `cloudpaygateway.xxx.com/pay/index.html#/billDetail`）」；直接调用云支付网关 `samllProgramGetRoomState`，无需登录 token。**
- **接口（原文）**：
  - `POST https://<缴费链接域名>/paygateway/smallpaygateway/trade`
  - 请求体：`{"method": "...", "bizcontent": "{...}", "timestamp": "...", "sourceId": 2}`
  - 房间级联：`samllProgramGetRoom`（`optype`: 1校区→2楼栋→3楼层→4房间）
  - 电量查询：`samllProgramGetRoomState`，`bizcontent={"payproid":..., "schoolcode":..., "roomverify":..., "businesstype":2}`
  - 返回：`businessData.quantity`（剩余电量）+ `businessData.quantityunit`（如「度」）
- **配置从缴费链接解析（原文）**：

```python
# pay_url_parser.py
GATEWAY_PATH = "/paygateway/smallpaygateway/trade"
# 链接形如：
# https://cloudpaygateway.<学校域名>:<端口>/pay/index.html?openId=...&token=...&customerId=<学校代码>#/billDetail?item={"id":<项目ID>,"flag":2,...}
def parse_pay_url(url): ...
    api_url = f"https://{host}{GATEWAY_PATH}"
    payproid = item["id"]; businesstype = item["flag"]  # 用电一般 2
```

- **房间 ID 结构（原文）**：`roomverify = <校区ID>-<楼栋ID>--<楼层ID>-<房间号>`。
- **可用性**：2026-10 更新；**对本校最有吸引力**——如果 FJTCM 的完美校园缴费页是这种云支付网关，只需抓一次链接、无需账密/token/验证码。缺点：每个学校的网关域名/缴费项目 ID 都不同，需要自己抓一次。

### 3.17 stmtc233/WanXiao-Elec-TgBot（Go，2026-11-05 最新）

- 地址：https://github.com/stmtc233/WanXiao-Elec-TgBot （MIT，2026-11-05，0★，Go + SQLite + Telegram）
- 双路线：老引擎 `SWAEServlet` 查电 + 云支付网关 `cloudpaygateway.59wanmei.com:8087` + `goPay` 生成充值链接（仅学校码 1399 白名单）。
- **可复用代码（原文）**：

```go
// 老引擎：getbindroom
APIURL = "https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet"
// 学生信息校验（云支付网关，免登录）
body := {"method":"smallProgramUserAuth","timestamp":"...","sourceId":2,
         "bizcontent": `{"token":"","idserial":"<学号>","schoolcode":"<学校码>"}`}
POST https://cloudpaygateway.59wanmei.com:8087/paygateway/smallpaygateway/trade
// 充值：getPayInfo → data.URL/jsonData/sign → H5 收银台
```

- **注意**：`timestamp` 格式、`command`（`JBSWaterElecService`）、`schools/schools.csv`（约 2900 所学校）——**学校码表比 zuwei522 的 358 条更全**，可作为 769 的第三重佐证（`769,福建中医药大学`，`schools.csv` L142）。
- **可用性**：2026-11-05 仍在更新（今天）；MIT；Go 单二进制无依赖，适合长期跑。**如果要做 Telegram/多用户，可参考；普通个人用杀鸡用牛刀。**

### 3.18 lswlc33 两个仓库（云支付网关批量查，2024 停更）

- `jsit_wanmei_left_power_select`（Apache-2.0，2024-03）：`POST https://cloudpaygateway.59wanmei.com:8087/paygateway/smallpaygateway/trade`，`method=samllProgramGetRoomState`，`bizcontent={"payproid":273,"schoolcode":"609","roomverify":"<拼好的房间号>","businesstype":2}`；还有 `samllProgramGetRoom` 逐层取房间；128 线程批量扫全校。
- `wanxiao_power_monitor`（2024-12）：同网关 + Flask/ECharts 面板（全校 TOP10）；`timestamp` + `sourceId:1` + `idserial` 随机。
- **价值**：证明**云支付网关可以免登录批量查**；**风险**：128 线程属于高频扫接口，实测返回「频繁请求，等待60s」，不建议在生产复刻；两者都无「低电提醒」（后者的 TODO）。

### 3.19 yifeiyixiang/wanmeixiaoyuan（旧版云支付 + Cookie，README 示例）

- 地址：https://github.com/yifeiyixiang/wanmeixiaoyuan （2023-10-24，4★，只有 README）
- **老版云支付接口（原文）**：

```python
url = 'http://h5cloud.17wanxiao.com:8080/CloudPayment/user/getRoomState.do?payProId=2523&schoolcode=843&businesstype=2&roomverify=1-6--56-6415'
headers = {'User-Agent': '...MicroMessenger/8.0.28...', 'Referer': 'http://h5cloud.17wanxiao.com:8080/CloudPayment/bill/selectPayProject.do?...', 'cookie': '#你的完美校园cookie'}
req = requests.get(url, headers=headers)
power = float(req.json()['quantity'])
```

- 注意端口从 `:8080` 变为现在的 `:18443`；`code=ERROR` 表示 Cookie 失效（与 DHKun 的 `SESSION_SUSPECT` 一致）。
- **可用性**：思路有效但代码片段是 2023 年的，端口/流程需按 3.13/3.14 更新。

### 3.20 Andtun02/school-charge-open（早期账密 + Web 可视化）

- 地址：https://github.com/Andtun02/school-charge-open （Apache-2.0，2024-05-24，3★）
- 价值：`api.py` 把 CloudPayment 的 **账密登录 + pay.do + selectPayProject + getRoomState** 完整跑通，并给出「注册设备 ID」工具（`tool/`）。README 提醒：「此后不要再使用 APP 登录」。
- **可用性**：停更，但可作为 CloudPayment 报文的第二份交叉参考（与 3.13 对照）。

### 3.21 登录/协议参考（摘要）

- **ReaJason/17wanxiaoCheckin**（397★，MIT，最后提交 2024-01）：`login/campus.py` 是完美校园账密/短信登录最完整的开源实现：
  - `POST https://app.17wanxiao.com/campus/cam_iface46/exchangeSecretkey.action`，body `{"key": <RSA-1024 SPKI DER base64>}`，用私钥 PKCS#1 v1.5 解密响应 → `{session, key}`，`appKey = key[:24]`；
  - 业务请求体 = `{"session": sid, "data": <3DES-CBC/IV=66666666/base64>}`，头 `campusSign: sha256(body).hexdigest()`；
  - 密码 = **逐字符** 3DES 加密后 base64 的数组；
  - 短信登录：`gainMatrixCaptcha.action`（注意 jialiangh 说必须 `gainMatrixCaptcha543.action`）→ `registerUsersByTelAndLoginNew.action`。
- **fuqiuluo/wanxiao-campus**（Rust，2024-03）：同样的 exchangeSecretkey + 3DES，另有 `https://xqh5.17wanxiao.com/keychain/Api`（keychain 令牌）。
- **sijiyo/new_wanxiao**（2023，5★）：「过风控版」登录参数（`qudao: xiaomi`、`shebeixinghao: sailfish`、`telephonyInfo: 8.1.0`、`wanxiaoVersion: 10565101`、`yunyingshang: 07`），说明风控参数在持续演进。
- **JarvisLeung/wanmei_campus**（2020，MIT）、**KeJunMao/wan-xiao-ykt**（2021）：旧域名 `server.17wanxiao.com` 时代的实现，只作历史参考（域名已迁移到 `app.17wanxiao.com`）。

### 3.22 其他值得注意的项目（未逐一展开）

- **Andtun02/school-charge-open**、**snowf14k3/electricity-alert**：见上。
- **完美校园打卡族**（ReaJason 397★、WeiJiuguo/Wanmei_AutoCheck 108★、wdkang123/AutoFuckWM 20★、ShawnRZ/WanxiaoHealthyCheckOnTencentCloud 17★、Dongxiaohaoo/17Wanxiao-Web 2★ 等）：**与电费无关**，但都以「账密/短信登录 + 报平安」为核心，登录协议可复用。
- **`100campus.com` 关键词**：GitHub 仓库搜索 0 命中；本项目实战代码里没有出现该域名，仍以 `17wanxiao.com` 为准。
- **安全类**：`zh-byte/rce`（新开普智慧校园 `service.action` RCE）、`CrackerCat/xkp-zsxy-rce` —— 与本任务无关，**不要碰**。

---

## 4. 接口与鉴权全景（跨项目汇总）

### 4.1 端点总表

| 代号 | 端点 | 方法 | 关键参数 | 鉴权 | 典型响应 |
|---|---|---|---|---|---|
| A 老引擎 | `https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet` | POST form | `param={"cmd","account",...}`、`customercode`、`method`、`command` | **无**（学校码+账号） | `{code_:0,result_:"true",message_:"获取成功！",body:"<JSON 字符串>"}` |
| A' 加密版 | `.../SWAEEncryptServlet` | POST form | `encryptData`、`timestamp`（毫秒）、`randomStr`（10 位）、`method` | AES-128-ECB 请求加密（key 规则见 3.11） | 解密后同上 |
| B 云缴费登录 | `https://app.17wanxiao.com/campus/cam_iface46/exchangeSecretkey.action` → `loginnew.action` | POST JSON | RSA 公钥；`{session,data}`；`campusSign` | RSA-1024 + 3DES-CBC | `{session,key}` / `{result_:true,...}` |
| B' 云缴费 | `https://h5cloud.17wanxiao.com:18443/CloudPayment/` | GET | `token`（握手 session）→ SESSION；`payProId`、`schoolcode`、`businesstype=2`、`roomverify` | token → HttpOnly SESSION + **Referer 参与鉴权** | `{"returncode":"100","quantity":"...","quantityunit":"度"}` |
| C 学校云支付网关 | `https://cloudpaygateway.<学校域名>:<端口>/paygateway/smallpaygateway/trade` | POST JSON | `method=samllProgramGetRoomState`、`bizcontent="{payproid,schoolcode,roomverify,businesstype}"`、`timestamp`、`sourceId` | **无**（部分学校需 token，可空） | `{"businessData":{"quantity":...,"quantityunit":"度"}}` |
| D 学校自建 epay | 例 `http://epay.sues.edu.cn/epay/wxpage/wanxiao/eleresult` | GET | `sysid/roomid/areaid/buildid` | 无 | HTML 中 `left-degree="..."` |
| E loginCheck | `.../smartWaterAndElectricityService/loginCheck` | POST form | `data=<落地页 params>` | AES-128-ECB（key `1234567812345678`）解响应 | `body.data={customerCode,command,outid/userid}` |
| F 学生信息校验 | 云支付网关 `method=smallProgramUserAuth` | POST JSON | `bizcontent={"token":"","idserial","schoolcode"}` | 无 | `businessData.{username,orgname,orgcode}` |
| G 充值 | `.../smartWaterAndElectricityService/goPay` 或 `CloudPayment/user/pay.do` 系列 | POST/GET | `cmd=getPayInfo`、`payamt`、`txcode=51101`、`acctcode`… | 各校不同 | `data.{url,jsonData,sign}` → 支付宝 |

### 4.2 老引擎 cmd 一览（来自 Jursin README + 各项目实践）

| cmd / method | 用途 | 关键返回 |
|---|---|---|
| `getbindroom` | 查账号绑定的房间 | `existflag`（1 单/2 多/0 无）、`roomlist[]`、`roomfullname`、`roomverify`、`detaillist[{businesstype,use,odd,status,sumbuy,sumsub}]` |
| `h5_getstuindexpage` / `getstuindexpage` | 首页/电表详情 | `modlist[{devicename,todayuse,odd,price,weekuselist,monthuselist,sumbuy,linestatus,isshowpay}]` |
| `getusedetail` | 月度用量 | `monthuse`、`dayuselist[{daydate,dayuse}]` |
| `gettimeusedetail` | 区间用量 | `sumuse`、`dayuselist[{date,use,firstcolldate,lastcolldate}]` |
| `login`（搜校用） | 部分项目用于探测学校码是否可用 | 业务结果 |

### 4.3 `businesstype` 语义
- 老引擎 `detaillist[].businesstype`：**0=电，1=水**（DragonYH `_energy_label` 映射 0→「电」、1→「水」；suiren 同）。
- 云缴费/云支付：**`businesstype=2` 用电**，热水/冷水另有项目/类型（JustaSage 用 `0`=电、`1`=冷水、`2`=热水，注意这是它自己的映射，与老引擎不同——**字段语义在不同产品线不一致，以实际返回为准**）。
- `odd` = 剩余量（度/吨，字符串居多）；`use` = 已用量；`sumbuy` = 累计购买；`status` 1 一般送电 / 其他一般断电；`price` 电价（元/度）；`linestatus` 线路状态；`isshowpay` 是否显示缴费。

### 4.4 错误/失效形态（用于写兜底）
- 老引擎：HTTP 200 但 `result_ != "true"`；`body.result != "0"`；`existflag=0`（未绑定/学校不支持）；空/`"null"` 的 `odd`。
- 云缴费：`RspBaseVO [code=ERROR, msg=系统繁忙，请稍后重试]` = Cookie/Referer/会话问题；`quantity` 空或 `-1` = 无效读数；token 失效 = 返回 200 HTML 且 `payprolist` 为 null（不报错！）。
- 云支付网关：`returncode != "100"`；「频繁请求」→ 需 60s 退避。
- WAF：HTTP 405，或业务码 `code_:9004`（熔断）；短时间高频请求后整个域名返回拦截页，几分钟自愈。
- 登录：`code_=5` 可能是新设备验证**也可能**是密码错误（看 message）；`code_=800114003` 短信验证码错误（说明 captcha 接口没带 543 后缀）；`code_=4` 手机号未注册。

---

## 5. 学校编号 / 学校码表 / 房间参数

### 5.1 福建中医药大学 = 769（三源一致）

| 来源 | 位置 | 内容 |
|---|---|---|
| zuwei522/perfect-campus_electricity-alert | `school-list.md` L849-850 | `<td> 福建中医药大学</td><td>769</td>`（该表来自官方 `kdword_fl02.html` 的 2023 快照，commit f258c64） |
| DragonYH/astrbot_plugin_wanxiao_electricity | `school_codes.json` L227 | `{"name": "福建中医药大学", "code": "769"}`（358 条，带 sha256/record_count 校验） |
| stmtc233/WanXiao-Elec-TgBot | `schools/schools.csv` L142 | `769,福建中医药大学`（约 2900 条，最全） |

> Aapifox 转录文档（DragonYH README 引用）：https://apifox.com/apidoc/shared/38ff3833-9d57-42f3-9cd5-ffeaef43be3a
> 官方学校码页 `https://open.17wanxiao.com/kdword_fl02.html` **已下线**（DragonYH README 原文：「该官方地址当前已不可用」）。
> `100campus.com`：0 命中；代码里未出现该域名。

### 5.2 学校码 / 房间参数的三种拿法
1. **学校码**：查上面的表（769）；或抓 App「智能水电」入口响应头 `location` 里的 `customerid`（Jursin README）；或从缴费链接 `customerId=` 取（cyqmq）；或按学校名查 `schools.csv`。
2. **roomverify**：老引擎 `getbindroom` 返回 `roomfullname`（下划线分隔全路径）与 `roomverify`（后续接口必传）；云缴费从 `selectPayProject.do` 页面 HTML 的 `clickHistoryRoom(this)` 取（Zuizhuban），或 `user/getRoom.do?optype=4` 下钻（返回的 `id` 即 roomverify）。
3. **cloudpay 网关的 schoolcode/payproid/businesstype**：从缴费链接解析——`customerId`→schoolcode、`#/billDetail?item={...}` 的 `id`→payproid、`flag`→businesstype（用电一般 2）；`api_url = https://<链接域名>/paygateway/smallpaygateway/trade`（cyqmq docs）。

### 5.3 本校结构推测（谨慎）
- FJTCM 有旗山校区（主校区），宿舍楼编号如 10#、楼栋房间号形如 `10号楼101`（来自福建医科大学示例文档，**不是本校**，仅说明这类"楼栋+房间"结构在福建高校常见）。
- 云缴费 `roomverify` 形如 `<校区ID>-<楼栋ID>--<楼层ID>-<房间号>`（cyqmq/lswlc33），老引擎 `roomverify` 形如 `101-07--112-308`（jialiangh）——**同一编码风格**，说明两代系统底层数据模型相近。

---

## 6. 失效 / 风险标记

### 6.1 逐项目状态

| 项目 | 最近提交 | 接口是否还在 | 有没有人反馈不能用 | 结论 |
|---|---|---|---|---|
| zuwei522/perfect-campus_electricity-alert | 2025-06-06 | 老引擎，2025-06 作者确认可用 | Issue #9 海外 IP 超时（2025-07 恢复）；Issue #3 单房间解析 bug（有 PR） | **可用但老旧**；Actions+海外 IP 有风险 |
| Jursin/wanxiao-electric-apis | 2026-10-07 | 老引擎 | 无 Issue | **可用，最佳接口参考** |
| chanlun3377/campus-electricity-alert | 2026-10-01 | 老引擎，2026 实测可用 | 无 Issue；README 自述云 IP 405 | **可用；建议住宅 IP** |
| fanxingstarry/... | 2026-10-16 | 老引擎 | 无 | 可用；注意硬编码下标/电价 |
| m555455445/... | 2023-11-30 | 老引擎 | 无 | 停更但接口未变；单房间假设 |
| suiren0219/... | 2026-10-25 | 老引擎 | 无 | 可用；工程化最佳 |
| DragonYH/... | 2026-07-21 | 老引擎 | 无 | 可用；官方学校码页失效已由本地表兜底 |
| sctop/... | 2026-09-02 | 老引擎 | 无 | 可用（肇庆学院） |
| Jursin/astrbot_plugin_wanxiao | 2026-10-07 | 老引擎 | 无 | 可用 |
| snowf14k3/electricity-alert | 2025-07-29 | 老引擎 | README 记录「封杀国外 IP，现已恢复」 | 可用但 Cloudflare IP 风险最高 |
| bingjuu/wxeleTool | 2024-11-28 | 老引擎 | 无 | 停更；学校码测试脚本有用 |
| WeiZong668/ESP32... | 2026-03-15 | 老引擎 | 无 | 小玩具 |
| Morii-torri/LowElecAlert | 2024-06-10 | **非完美校园标准接口**（SUES 自建 epay） | 无 | 只对上海工程技术大学有效 |
| jialiangh/campus-electricity-monitor | 2026-10-15 | 云缴费 | 无 Issue；README 自述 405/9004 熔断 | **可用，文档最佳**；需账密+deviceId |
| JustaSage/ZCST_FEE_Bot | 2026-06-13 | SSO + loginCheck + 老引擎 | 无 Issue | 可用（珠海科技学院）；AGPL |
| Zuizhuban/wanxiao-electricity-alert | 2026-10-12 | 云缴费 | 无 | 可用；单文件验证工具 |
| DHKun/xzmu-electricity-monitor | 2026-10-31 | 云缴费 | 无 | 可用；Cookie 会过期需续 |
| cyqmq/... | 2026-10-26 | 学校云支付网关 | 无 | 可用；需抓一次缴费链接 |
| stmtc233/WanXiao-Elec-TgBot | 2026-11-05 | 老引擎 + 云支付 + goPay | Issue #1 转义 bug（已修） | **活跃，最新** |
| lswlc33/jsit... | 2024-03-06 | 云支付网关 | 无；README 无失效声明 | 停更；批量扫接口有风险 |
| lswlc33/wanxiao_power_monitor | 2024-12-14 | 云支付网关 | 无 | 停更；面板可参考 |
| yifeiyixiang/wanmeixiaoyuan | 2023-10-24 | 云支付（:8080 旧端口） | 无 | 思路有效，端口/流程已变 |
| Andtun02/school-charge-open | 2024-05-24 | 云缴费 | Issue：设备 ID 怎么填（说明门槛高） | 停更；报文参考 |
| chuzong886/... | 2026-10-16 | **加密版 SWAEEncryptServlet** | 无 | 可用（需加密化学校）；无 License |
| ReaJason/17wanxiaoCheckin | 2024-01-05 | 登录协议（打卡） | 无 | 仅登录参考；电费接口没用 |
| fuqiuluo/wanxiao-campus | 2024-03-24 | 登录协议（Rust） | 无 | 仅协议参考 |
| sijiyo/new_wanxiao | 2026-01-04 | 登录协议（过风控） | 无 | 仅登录参考 |
| JarvisLeung/wanmei_campus | 2020-10-05 | 旧域名 `server.17wanxiao.com` | 无 | 历史参考（域名已迁移） |
| KeJunMao/wan-xiao-ykt | 2021-01-20 | 旧协议 | 无 | 历史参考 |
| IDeLoveYou/SGU-... | 2024 | **README 首行：已不适用且不再维护** | 自述失效 | **不可用**（且非完美校园） |

### 6.2 系统性风险（比单个项目更重要）

1. **接口迁移/加密化**：老引擎已出现加密版 `SWAEEncryptServlet`（2026-10 的 chuzong886）；微信端 2024-09 也被曝「新接口增加身份验证」（doupoa 博客）。**任何学校都可能被升级**。
2. **IP 封锁 / WAF**：
   - 证据 1：zuwei522 Issue #9（2025-07）海外服务器请求超时、国内正常；同月 snowf14k3 称已恢复。
   - 证据 2：chanlun3377 README（2026-10）「阿里云 WAF，GitHub Actions 和云服务商 IP 全部返回 405」。
   - 证据 3：jialiangh（2026-10）「HTTP 405 / 熔断 code_:9004，短时间请求过密整个域名返回拦截页，几分钟自愈」。
   - 证据 4：snowf14k3 README「完美校园曾封杀过国外 ip」。
   - 结论：**免费云（GitHub Actions/Cloudflare/Vercel）能跑通是运气，不能当生产方案**；家宽/国内 VPS/树莓派/旧安卓手机最稳。
3. **频率限制**：云支付网关「频繁请求，等待60s」；老引擎高频会触发 WAF/熔断。建议 **1–8 次/天，最低 1 次/小时**（jialiangh 每小时 1 次未触发；chuzong886 默认每天最多 8 次）。
4. **新设备风控 / 验证码**：云缴费必须先用 `deviceId` 过一次性短信验证（绑定后换 IP 不再验证）；验证码接口必须带 `543` 后缀；验证码与 session 绑定。**自动化前必须先手动绑定一次设备**，否则永远卡在验证码。
5. **账号格式不一致**：老引擎 `account` 在部分学校是**学号**，在部分学校是 **outid（身份证号）**（suiren README 原文：「账号为完美校园 outid，一般是身份证号，不是学号」；Jursin 插件配置写「学号/身份证号」）。云缴费登录账号是**手机号**。**不要假设是学号**。
6. **越权/合规**：老引擎只校验「学校码+学号」，等于任何知道这两项的人都能查该账号绑定的房间（jialiangh 隐私提醒原文：「这套接口的设计存在明显的越权读取面」）。**只查本人账号；不要批量探测；不要公开别人数据；不要商用**。这类未公开接口的抓取可能违反完美校园用户协议与学校规定，存在账号风险；建议控制频率、只用于个人提醒、不对外提供服务。
7. **凭据安全**：账号/密码/token/deviceId 等于密码；不要提交到 Git、不要贴群（多个项目已完成加密落盘/脱敏，见 suiren、jialiangh、JustaSage）。
8. **项目许可**：AGPL（DragonYH、sctop、JustaSage）有传染性；大量项目**无 LICENSE**（默认版权保留）——抄代码前看清，自己用没问题，公开分发要谨慎。
9. **云缴费专项风险**（登录风控/验证码、SESSION 过期、WAF 405/9004、频率限制、token 泄露）见 **§3.0.7**。

---

## 7. 对本校（FJTCM）的适用性判断与验证步骤

### 7.0 结论更新（2026-11-05 22:50，已实测）

- **A 路线（老引擎 SWAEServlet）已排除**：Lead 用真实学号 + 学校码 769 调 `getbindroom` 返回 `8099「body格式错误」`（对照 759 正常）；加上用户入口是「完美校园 → 缴费 / 用电支出（预付费）」，可判定 FJTCM **不挂完美校园智能水电老引擎**。
- **主线切换为云缴费**：优先试 **B2 学校云支付网关（免登录，抓一次缴费链接）**，不行再走 **B1 h5cloud CloudPayment（账密+一次性短信）**；详见 **§3.0**。
- 下面 7.1~7.4 保留 22:30 初版分析（A 路线验证已作废可跳过；B1/B2 验证步骤仍然有效，并已在 §3.0.5 细化）。

**7.0.1 推荐落地顺序（更新版）**

1. 用户打开完美校园「缴费 → 用电支出/预付费 → 选房间」页面，抓/复制一条缴费链接（含 `customerId` 与 `item` 参数）。
2. 判断域名：`cloudpaygateway.*` → **B2**；`h5cloud.17wanxiao.com:18443` → **B1**。
3. **B2**：跑 `cyqmq/tools/detect_config.py "<链接>"` → 解析出 `schoolcode/payproid/businesstype/api_url`，交互式搜房并验证电量 → 改造成 `query.py` + 定时 + 推送即可（免登录，最稳）。
4. **B1**：跑 `jialiangh/wanxiao_login.py login`（首次可能需要 `sms-send`/`sms-code` 绑定设备）→ `electricity_monitor.py projects/rooms/now` 验证 → 再写定时/推送。
5. 两条都不通：检查是否加密版 `SWAEEncryptServlet`（chuzong886）或今日校园 WebView；都失败则退回人工查询。
6. 任何路线：查询 ≤8 次/天、间隔 ≥1 小时、家宽/本机 IP、凭据本机加密保存。

### 7.1 已检索到的本校证据（外部网页，仅作线索）

| 渠道 | 证据 | 时间 |
|---|---|---|
| 今日校园 | 福建中医药大学现代教育技术中心：「打开『今日校园』→ 公共服务 → 购电查询，填写楼栋号及房间号即可实时查询电费」；另有 2021 年《今日校园新增"购电查询"服务》 | 2021-07 / 2022-08 |
| 完美校园 | 本校后勤/一卡通通知：餐卡充值用「完美校园 APP」（绑定姓名、学号、消费密码） | 2017 / 2018 / 2023 |
| 完美校园（邻校对照，非本校） | **福建医科大学**（fjmu.edu.cn）官方 docx：「登入完美校园 → 线上缴费 → 预付费 → 用电支出 → 选择缴费房间 → 根据剩余电量缴费」；另有「全部应用 → 电量查询」 | 未标注（docx 现行） |
| 学校官网 | 福建中医药大学校园统一支付平台（`zfpt.fjtcm.edu.cn`，学费类） | 现在 |

> ⚠️ 重要：**不要把我上面"福建医科大学"的流程当成福建中医药大学**。两校同城不同校，福建医科大学走完美校园缴费，而福建中医药大学官方口径是今日校园购电查询。**完美校园学校码 769 只能说明"完美校园系统里有这个学校"（用于一卡通/可能有电费），不能证明电费走哪条线。**

### 7.2 候选路线（A 已排除；B1/B2 为主线，与 §3.0.2 编号对应）

| 路线 | 适用判断 | 需要的参数 | 复用项目 | 难度 |
|---|---|---|---|---|
| **A. 老引擎直查（已排除 ❌）** | ~~FJTCM 的完美校园里有「智能水电/电量查询」且后端挂老引擎~~ | 学校码 769 + account（学号或身份证号） | Jursin `wanxiao.py` / 3.1 / 3.3 | ★（已实测 8099，不可用） |
| **B1. h5cloud 云缴费（账密）** | FJTCM 的完美校园里有「缴费 → 预付费/用电支出」，且缴费页是 `h5cloud.17wanxiao.com:18443` | 手机号+密码、deviceId（一次性短信验证） | jialiangh（首选）/ Zuizhuban / DHKun | ★★★ |
| **B2. 学校云支付网关（免 token）** | FJTCM 缴费页是 `cloudpaygateway.*` 域名 | 抓一次缴费链接 → schoolcode/payproid/businesstype/api_url | cyqmq（自动解析）/ lswlc33 参数格式 | ★★ |
| W. 微信/支付宝小程序入口 | 只有小程序入口、拿不到 APP H5 链接 | WX code/openid/token（需 WX 环境抓包） | 无现成项目；doupoa 2022 博客 | ★★★★★（最后手段） |
| D. 今日校园购电查询 | 学校官方口径的入口 | 无公开 API，需逆向 WebView（未验证） | 无现成项目 | ★★★★★（不建议第一期） |

### 7.3 一次性验证清单（用**你自己的**账号，只在本机执行，不要外发）

> 以下请求只包含"学校码 + 学号/账号"，属于本人自查；仍建议低频、只跑 1 次。**不要**把真实学号贴到任何公开渠道；测试脚本请把学号放环境变量而非代码。

1. ~~**测老引擎**（A 路线）~~ **已完成，返回 8099，A 路线排除，可跳过**（见 §7.0）：
   ```bash
   curl -s "https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet" \
     --data-urlencode 'param={"cmd":"getbindroom","account":"<你的学号>"}' \
     --data-urlencode 'customercode=769' \
     --data-urlencode 'method=getbindroom' \
     -H 'Content-Type: application/x-www-form-urlencoded'
   ```
   - 返回 `"result_":"true"` 且 `body` 里 `existflag` 为 `"1"`/`"2"` → **A 路线可用**，直接上 §3.2/3.3 的脚本（改 school 769 + 学号）。
   - `existflag:"0"` 或「未绑定房间」或返回 8099 → 本校电表不挂老引擎，转 B1/B2（**已实测确认转 B1/B2**）。
   - HTTP 405/超时 → 可能是 IP 被 WAF 拦（换家宽/手机热点再试一次）。
2. **确认 App 入口**：打开完美校园 APP，看「缴费」里的「用电支出/预付费」入口（用户已确认存在）；A 路线（智能水电/电量查询）已排除，不用再试。
3. **测云支付链接**（B2 路线）：在完美校园 APP 打开缴费页面 → 复制链接（或 H5 页面地址栏）→ 看是否 `cloudpaygateway.<域名>:<端口>/pay/index.html?...customerId=...`。若是，用 cyqmq 的 `tools/detect_config.py` 一键解析并试查房间。
4. **测云缴费**（B1 路线）：用 jialiangh 的 `wanxiao_login.py status/login`（先看仓库 README 的登录/短信步骤），确认能否登录并列出缴费项目；能列出「用电支出」→ B1 可用。
5. **频率**：无论哪条路线，第一次验证后，定时任务建议 **每天 2–4 次（如 12:00/19:00）**，最多 8 次；间隔 ≥1 小时；失败不重试风暴。

### 7.4 如果 B1/B2 都不通
- 退而求其次：**手动查询 + 手动提醒**（每天自己打开 APP 看一眼），或写一个「点开缴费页截图→OCR 读数」的半自动方案（成本高、不稳）。
- 或联系学校后勤/信息化中心问是否有官方 API/订阅服务（合规、最稳，但学校不一定提供）。

---

## 8. 「最值得抄什么」结论（5 条）

> 注（2026-11-05 22:50 更新）：下面 5 条写于初版、偏"老引擎 + 通用"；**对 FJTCM 请以 §3.0.8 的分级结论为准**（B2 直接抄 cyqmq / B1 抄 jialiangh / 老引擎全部不适用）。第 1 条"先分流判断"仍然成立——只是本校的分流结果已经确定为云缴费。

1. **先抄"分流判断"，别急着抄代码**：任何方案第一步都是判断本校属于老引擎（A）还是云缴费（B1/B2）。`jialiangh/docs/接口说明.md` 的方法最直接——请求 `getbindroom` 看 `existflag`。**本校已实测：A 排除，走 B1/B2（§3.0）。**
2. **老引擎 backend 抄 `Jursin/wanxiao-electric-apis`**：接口字段、请求头、`getbindroom/h5_getstuindexpage/getusedetail/gettimeusedetail`、错误处理写得最干净（约 200 行 Python，零依赖思路清晰）；解析结构兼容单房间/多房间（参考 `chanlun3377` 的 `detaillist` 兜底）。
3. **云缴费 backend 抄 `jialiangh/campus-electricity-monitor`**：登录协议（RSA+3DES+campusSign）、deviceId 一次性绑定、CloudPayment 五步链、Referer/Cookie 坑、token 有效探针——一份文档覆盖 90% 的坑；`Zuizhuban` 的单文件 Node 版适合快速验证/自检。
4. **工程骨架抄 `suiren0219/astrbot_plugin_dorm_power`**：接口地址/command/字段名全部可配置、aiohttp 连接复用 + 指数退避、429/5xx 重试但业务失败不重试、搜校限速熔断、账号/房间加密落盘 + 日志脱敏、多用户多房间、字段容错。这些是「能长期跑」和「玩两天就坏」的分水岭。
5. **交付形态抄 `fanxingstarry` + `chanlun3377`**：单文件 Python + `config.example` + 环境变量 + 一条 cron/任务计划 + 一个推送渠道（Qmsg/钉钉/Server 酱/PushPlus 任选），Docker 可选；**提示信息里学号脱敏**（`STUDENT_ID[:4]******`）。另外把 `chuzong886` 的「抓包解析配置」思路抄过来（用户粘贴一条抓包→自动填 schoolcode/account/roomverify），能大幅降低换学校/换宿舍的维护成本。
6. （附加，不做第一版）`chuzong886` 的预测/自适应查询、`JustaSage`/`stmtc233` 的充值链接、`DHKun` 的静默续登，都是第二阶段再加的东西——**别一开始就上**。

---

## 9. 附录

### 9.1 关键来源链接

- 仓库（按重要性）：
  - https://github.com/jialiangh/campus-electricity-monitor
  - https://github.com/Jursin/wanxiao-electric-apis
  - https://github.com/suiren0219/astrbot_plugin_dorm_power
  - https://github.com/zuwei522/perfect-campus_electricity-alert
  - https://github.com/chanlun3377/campus-electricity-alert
  - https://github.com/cyqmq/astrbot_plugin_wanmei_dorm_power
  - https://github.com/Zuizhuban/wanxiao-electricity-alert
  - https://github.com/JustaSage/ZCST_FEE_Bot
  - https://github.com/DHKun/xzmu-electricity-monitor
  - https://github.com/chuzong886/wanmeixiaoyuandianfeiyujin
  - https://github.com/stmtc233/WanXiao-Elec-TgBot
  - https://github.com/DragonYH/astrbot_plugin_wanxiao_electricity
- 博客/文档：
  - doupoa《完美校园电费h5查询接口解析与应用》(2026-04 更新) — https://doupoa.site/archives/510/
  - doupoa《完美校园电费查询新接口请求原理解析》(2022-06，WX 端 code→openid→token→session) — https://blog.csdn.net/doupoa/article/details/125192380
  - 《Python对全校电费查询采集并可视化分析》(2023-08，完美校园缴费入口实践) — https://juejin.cn/post/7271103274064068665
  - 完美校园应用操作指引（微信/支付宝小程序绑定、含「云缴费 h5cloud.17wanxiao.com」示例）— https://mp.weixin.qq.com/s?__biz=MzkxNDQwMzM1NQ==&mid=2247494533&idx=1&sn=d322a7ea0c637e319ad58aad25d3a58d
  - Apifox 共享「完美校园智能水电API」— https://s.apifox.cn/ad1e6ba6-6cd2-4b6e-88b2-a1ca1577e14c/folder-41557094
  - Apifox 学校码转录 — https://apifox.com/apidoc/shared/38ff3833-9d57-42f3-9cd5-ffeaef43be3a
  - CSDN《完美校园微信/qq推送实现教程》— https://blog.csdn.net/qq_28821897/article/details/138329438
  - CSDN《湖南工业大学电费数据抓取（完美校园版）》(旧版 h5cloud:8080) — https://blog.csdn.net/weixin_43999566/article/details/101755168
- 失效/状态证据：
  - zuwei522 Issue #9（海外 IP 超时）— https://github.com/zuwei522/perfect-campus_electricity-alert/issues/9
  - zuwei522 Issue #3（单房间无 roomlist）— https://github.com/zuwei522/perfect-campus_electricity-alert/issues/3
  - snowf14k3 README（曾封海外 IP，已恢复）— https://github.com/snowf14k3/electricity-alert
- 本校/邻校线索（仅线索，需自行验证）：
  - 福建中医药大学信息化 FAQ（今日校园→购电查询）— https://metc.fjtcm.edu.cn/2022/0829/c1090a25617/page.htm
  - 福建中医药大学 2021 公众号《今日校园新增"购电查询"服务》— https://mp.weixin.qq.com/s/bnEa7CE5U5UFVLW6B2Szxg
  - 福建中医药大学后勤一卡通通知（完美校园 APP 充值）— https://hq.fjtcm.edu.cn/2018/0903/c1018a23505/page.htm
  - 福建医科大学（邻校对照）《学生宿舍在线缴费及电量查询流程操作说明》docx — https://www.fjmu.edu.cn/_upload/article/files/90/64/76601dcd4963bbc7885588ccc073/438e1229-2e96-456b-8192-5d661a7dee5e.docx

### 9.2 检索关键词清单（可复现）
`完美校园`、`17wanxiao`、`100campus`、`完美校园 电费`、`完美校园 打卡`、`新开普`、`智能水电`、`SWAEServlet`、`smartWaterAndElectricityService`、`perfect campus`、`校园卡 电费`、`wanxiao`、`xqh5`、`电费 提醒`；Issue 检索：`完美校园 电费`、`17wanxiao 电费`、`SWAEServlet`、`SWAEEncryptServlet`、`完美校园 接口 失效`、`完美校园 405`、`完美校园 风控`、`wanxiao 电量`。

### 9.3 原始数据位置（供 Lead/复核）
- 检索原始 JSON、合并表：`research/_raw/search_*.json`、`research/_raw/merged.tsv`
- 仓库完整快照（解压后）：`research/_raw/repos/<owner>__<repo>/`
- 元数据 / Issue 快照：`research/_raw/meta.json`、`research/_raw/issues.json`
- 本校 docx 与截图（辅助判断）：`research/_raw/fjtcm-docx.zip`、`research/_raw/fjtcm_docx_imgs/`

> 以上 `_raw` 目录为侦察过程产物（源码快照），保留供后续 task-2/task-3 复用；不属于最终交付物。

---

*报告完。若要继续，建议下一步：用 §7.3 的第 1 条命令（一次、本人账号）判定 A 路线是否可用，再决定抄 Jursin 还是 jialiangh。*
