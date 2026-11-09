# 阿里云侧资源现状审计（只读）

> 任务：`task-1` — 审计阿里云侧资源现状（OSS / DNS / ECS / FC / 证书 / ICP）
> 审计员：`aliyun-auditor`（Team Lead：`lead`）
> 实测窗口：**2026-11-09 22:10:46 – 22:19 （Asia/Shanghai）**，均为单次快照，之后可能变化。
> 工作目录：`C:\Users\Ko_Li\.openclaw\workspace\web`
> 红线遵守：全程**只读**（OSS List/Get 类、DNS Describe 类、ECS Describe 类、HTTP GET / TCP connect / TLS 握手 / MC status ping）；**未**上传、删除、改 DNS、SSH 登录、部署。凭据仅由脚本内部 `deploy/sync_tools.py::load_creds()` 加载，全部输出经 `scrub()` 脱敏；**本报告不含任何 AK/SK/token/私钥**，未读取 `deploy/creds.env`、`deploy/acme_account_key.pem`、`tools/cert/**`、`C:\briefdesk\secrets\**` 的内容（仅检查个别文件存在性）。
> 复现脚本（保留在 `_audit/`）：`tmp_dns_probe.py`、`tmp_dns_logs.py`、`tmp_oss_probe.py`、`tmp_oss_probe2.py`、`tmp_ecs_probe.py`、`tmp_ecs_probe2.py`、`tmp_net_probe.py`（同名 `.log` 为运行输出）。

---

## 0. 结论摘要（最关键的 5 条）

| # | 结论 | 关键证据 |
|---|------|----------|
| 1 | **OSS 线上站点健康、与本地源码逐字节一致**：`tool-furina-fun`（oss-cn-hongkong）公共读 + 静态托管 `index.html`，6 个对象；`index.html` 732,621 B / `sha256 65610511…`、`tt.json` 7,463 B / `ccf5153f…`、`assets/qr_tools.png` 3,661 B / `fb36932a…` 均与本地 `web/tools/` **MATCH**（22:11–22:19 实测，`deploy/oss_object.py sha/check` 复核）。 | §1.3、§1.4 |
| 2 | **furina.fun 是「暂停解析」不是「删除记录」**：解析记录仍保留 6 条（含 `tool`/`start`/`mc`/`_dnsauth.tool`/`_acme-challenge.tool`/`_dnsauth.me`），但**全部 `Status=DISABLE`**；`me` CNAME 是唯一被删的记录。公网 223.5.5.5、本机解析器、权威 NS `dns21.hichina.com` 对 `tool/mc/start` 均返回 **NXDOMAIN**；NS 委派（dns21/22.hichina.com）正常。 | §2.2–§2.4 |
| 3 | **ECS 121.196.47.2 仍在运行，跑的是「旧版静态站镜像 + 班级简报 board + 同步 API」**：`class_tool`（i-bp1ibr9hs7ewepmm1ugw）Running；80 开放，`/` 返回 **166,952 B / sha `1fefeac…`**（= 本地 `tools/_backup/index_local_20261103_2215_preTT.html`，即 **2026-11-03 镜像**，落后线上 OSS 732,621 B 约 565 KB）；`/board` 返回 6,166,576 B / `d2d9221c…`（= 本地 `notice-board-live-demo.html`，**今日 21:41 刚更新**）；`/api/status` 显示 `updatedAt=2026-11-09T21:41:02+0800` → 本机推送管道仍在跑。443 **连接拒绝**（Caddy 只监听 :80，未启用 HTTPS），22 超时（安全组仅放行 110.88.108.89/32）。 | §3.1–§3.6 |
| 4 | **MC 服务器（mc.furina.fun）不可达且本账号已无对应 ECS 实例**：`mc` A 记录现指向 **115.29.166.27**（非任务描述的 120.27.217.236；后者是旧文档地址），记录 DISABLE；两个 IP 的 22/25565/80 **全部 TCP 超时**，MC status ping 失败；全地域 ECS 盘点（33 区域）仅 1 台 `class_tool`、轻量应用服务器 SWAS 0 台 → MC ECS **高度可能已被释放**（见 §4 未验证说明）。 | §4.1–§4.4 |
| 5 | **FC 一键启动函数仍在线，但域名入口不可用**：`https://mc-start-mc-serv-control-alwwvseret.cn-hangzhou.fcapp.run/` 返回 **403 + 691 B 的「MC 服务器状态 / 无权限 token 错误」页**（函数在服务）；但 `start.furina.fun` 因 DNS DISABLE 无法解析。证书方面：OSS 自定义域名 `tool.furina.fun` 绑定状态 Enabled，证书 **2027-01-07T11:13:09Z 到期（剩余 ≈58.9 天）**，未见续期记录。 | §5、§1.5 |

---

## 1. 阿里云 OSS（oss-cn-hongkong）

### 1.1 Bucket 清单

| 资源 | 当前配置 | 实测状态（含时间戳） | 证据命令 / 输出摘要 | 结论 |
|------|----------|----------------------|----------------------|------|
| `tool-furina-fun` | 香港、Standard、创建于 2026-10-09T12:10:53Z | **存在** @22:11 | `tmp_oss_probe.py` → `get_bucket_info`: location=oss-cn-hongkong, storage_class=Standard | 线上站点主 Bucket |
| `furina-site-logs` | 香港、Standard、创建于 2026-10-11T13:50:05Z | **存在** @22:11 | 同上 | 访问日志桶 |
| `me-furina-fun` | 已按下线清单删除 | **不存在** @22:11 | `oss2.BucketIterator` 仅返回上述 2 个 bucket | `ME-FURINA-SHUTDOWN.md` 删桶步骤已执行 ✅ |

### 1.2 `tool-furina-fun` 基础属性

| 项 | 当前配置 | 实测状态（2026-11-09 22:11） | 证据命令 / 输出摘要 | 结论 |
|----|----------|------------------------------|----------------------|------|
| Bucket ACL | 公共读 | `public-read` @22:18 复核 | `get_bucket_acl().acl == "public-read"` | 匿名可读（见风险 R-7） |
| 静态网站托管 | index=index.html / error=index.html | 已开启 | `get_bucket_website()` → index_file=index.html, error_file=index.html | 正常 |
| 访问日志 | 写入 `furina-site-logs` 前缀 `tool/` | 生效中（今日 21:37:55 仍有日志落盘，见 §1.6） | `get_bucket_logging()` → target_bucket=furina-site-logs, target_prefix=tool/ | 正常 |
| 自定义域名 | `tool.furina.fun`（CNAME `tool-furina-fun.oss-cn-hongkong.aliyuncs.com`） | 绑定状态 **Enabled**，last_modified=2026-10-09T17:15:35Z | `list_bucket_cname()` → domain=tool.furina.fun, status=Enabled, is_purge_cdn_cache=false | 绑定仍在（但域名解析被暂停，外部不可达） |
| 自定义域名证书 | 类型 CAS（OSS 侧标记；90 天有效期与首次 Let's Encrypt DNS-01 签发吻合） | `status=Enabled`，valid_start=**2026-10-09T11:13:10Z**，valid_end=**2027-01-07T11:13:09Z**，**剩余 ≈58.9 天**（22:18 计算） | `list_bucket_cname().cname[0].certificate`；剩余天数由 valid_end 与 UTC now 差值计算 | **未见续期**（valid_start=首次部署日）；DNS 暂停期无法走 DNS-01 续签（见风险 R-2） |

### 1.3 `tool-furina-fun` 对象清单（完整 6 个对象）

| 对象 key | 字节数 | sha256 | Last-Modified（本地时） | Content-Type / Cache-Control | 本地 `web/tools/` 比对 | 结论 |
|----------|--------|--------|--------------------------|------------------------------|------------------------|------|
| `index.html` | 732,621 | `656105117464c6d67106faa4011d5dd806d11d2c0d44760df961488d92e3b420` | 2026-11-09T19:58:59+08:00 | text/html; charset=utf-8 / no-cache | **MATCH**（732,621 B 同 sha） | 线上主站 = 本地最新（19:58 部署） |
| `tt.json` | 7,463 | `ccf5153f5a8950e06d127d6001f60829a190705ca39e0310ebfd2eac29d4d9cc` | 2026-11-09T21:38:03+08:00 | application/json; charset=utf-8 / no-cache | **MATCH**（本地 mtime 21:37:58） | 教务课表快照已上传 |
| `assets/qr_tools.png` | 3,661 | `fb36932a96323895216f0b7cae66b14db4ff5d8b0438980adafb9e17d3a7861a` | 2026-11-08T22:32:07+08:00 | image/png / no-cache | **MATCH** | 正常 |
| `apple-touch-icon.png` | 968 | `fbdbc3535a12f5c24c0a5379209152440e734ede4abd1c1a3e6f5f49f96ce1a5` | 2026-10-11T21:49:58+08:00 | image/png / no-cache | **本地不存在** | 线上存在、本地源码树无此文件（见风险 R-6） |
| `favicon.ico` | 2,568 | `9d68e34591b344ac0dcd75de0489a2359ab8a3d3f3a0013dcf02c87442541e8c` | 2026-10-11T21:49:58+08:00 | image/x-icon / no-cache | **本地不存在** | 同上 |
| `robots.txt` | 23 | `16ceb5ee3e0dc13aa9adf31a3ebbe45a1d965b8c2b9f72eaf84e5911e140ed95` | 2026-10-11T21:49:58+08:00 | text/plain; charset=utf-8 / no-cache | **本地不存在**；内容=`User-agent: *\nAllow: /` | 同上 |

> 证据命令：`python _audit/tmp_oss_probe.py`（22:11:24–22:11:46，ListObjectsV2 + HeadObject + GetObject 内存读取，未落盘）；`python deploy/oss_object.py sha/check index.html|tt.json|assets/qr_tools.png`（≈22:19，均为 **MATCH**）。
> 注：`deploy/oss_object.py get` 未被使用（红线）。

### 1.4 源站可达性（绕开自定义域名，确认 OSS 本身健康）

| 资源 | 实测状态（22:15） | 证据命令 / 输出摘要 | 结论 |
|------|-------------------|----------------------|------|
| `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/index.html` | HTTP **200**，732,621 B，sha256 **65610511…**，`Server: AliyunOSS`，Last-Modified 2026-11-09T11:58:59Z | `tmp_net_probe.py` → http_get（匿名、无 AK） | OSS 源站健康，线上内容可访问（匿名） |
| `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/tt.json` | HTTP **200**，7,463 B，sha256 **ccf5153f…** | 同上 | 正常 |
| `https://tool.furina.fun/`（自定义域名） | **DNS 解析失败 / 连接重置**（见 §2.5） | 同上 | 仅域名层不可达，非 OSS 故障 |

### 1.5 日志 Bucket `furina-site-logs`

| 项 | 实测状态（2026-11-09 22:13） | 证据命令 / 输出摘要 | 结论 |
|----|------------------------------|----------------------|------|
| Bucket ACL | `private`（22:18 复核） | `get_bucket_acl().acl == "private"` | 正常 |
| 对象总数 / 总大小 | **551 个 / 5,022,699 B**（列举耗时 3.3s） | `tmp_oss_probe2.py`（ListObjectsV2 全量分页） | 正常 |
| `tool/` 前缀 | 428 个 / 3,970,657 B；**最近写入 2026-11-09T21:37:55+08:00**（对象 `tool/tool-furina-fun2026-11-09-18-00-00-000000000022`，14,322 B）；今日 11-09 共 10 个对象 / 20,697 B | 同上 | 访问日志仍在写入（日志为延迟落盘，18:00 时段对象 21:37 才写入） |
| `me/` 前缀 | **123 个 / 1,052,042 B，最近写入 2026-10-20T18:45:56+08:00** | 同上 | ⚠️ 下线清单第 4 步「清空 me/ 前缀」**未执行**（见风险 R-5） |

### 1.6 OSS 异常 / 风险

- **R-6（低）**：线上有 3 个本地源码树不存在的对象（`apple-touch-icon.png` / `favicon.ico` / `robots.txt`，均 2026-10-11 21:49 上传，来源未验证）。`sync_tools.py` 只上传固定列表，不会覆盖/删除它们；但本地无法重建这 3 件，若将来迁移/重建 Bucket 需另行补回。
- **R-4（中）**：Bucket 为 `public-read`，**OSS 默认端点（`*.oss-cn-hongkong.aliyuncs.com`）匿名 GET 仍 200**。备案期「停站」目前只停了自定义域名解析，内容仍可通过 OSS 默认域名访问 —— 与 `_compliance/research_delivery_paths.md` R11「备案抽查风险」一致，建议评估是否需要临时收紧（写操作，未做）。

---

## 2. 阿里云 DNS（furina.fun，云解析免费版）

### 2.1 域名元信息

| 项 | 实测状态（2026-11-09 22:10） | 证据命令 / 输出摘要 | 结论 |
|----|------------------------------|----------------------|------|
| DomainId | `30eef32ffec14853b160c420da9a12f5` | `DescribeDomainInfo(DomainName=furina.fun)` | 域名在阿里云云解析 |
| NS 委派 | `dns21.hichina.com`、`dns22.hichina.com`；`AllAliDns=true` | `DescribeDomainInfo` + `DescribeDomainNs` | NS 委派正常（未被删除/转移） |
| 版本 / 创建 | VersionCode=`mianfei`（免费版），CreateTime=2026-06-17T01:45Z | `DescribeDomainInfo` / `DescribeDomains` | 域名解析服务正常 |
| 记录总数 | **6 条**（`TotalCount=6`） | `DescribeDomainRecords` | 见 §2.2 |

> 账号下另有域名 `ko-link.cn`（0 条记录），与本项目无关，仅记录不展开。

### 2.2 当前全部解析记录（6 条，全部 DISABLE）

| RR | 类型 | 值 | TTL | Status | RecordId | 结论 |
|----|------|-----|-----|--------|----------|------|
| `tool` | CNAME | `tool-furina-fun.oss-cn-hongkong.aliyuncs.com` | 600 | **DISABLE** | 2108530859946394624 | **记录存在，被暂停**（非删除） |
| `_dnsauth.tool` | TXT | `61783b3e3a87253f1a9121abd762ee8a` | 600 | **DISABLE** | 2108530854917054464 | 保留，被暂停（OSS 域名归属校验用） |
| `_acme-challenge.tool` | TXT | `eeYxJiNAVAQscdikqPV7aluhPO2kNNHQiolul-YFpx4` | 600 | **DISABLE** | 2108530802237045760 | 保留，被暂停（证书 DNS-01 用） |
| `start` | CNAME | `mc-start-mc-serv-control-alwwvseret.cn-hangzhou.fcapp.run` | 600 | **DISABLE** | 2090434795511102464 | 保留，被暂停（MC 一键启动） |
| `mc` | A | **`115.29.166.27`** | 600 | **DISABLE** | 2085038289882749952 | 保留，被暂停；值为 **115.29.166.27**，非任务描述的 120.27.217.236 |
| `_dnsauth.me` | TXT | `a9b76d22dd4c801c343d07bb465c7b69` | 600 | **DISABLE** | 2108478852313201664 | ⚠️ 下线清单要求删除，**仍残留**（见 R-5） |

> 证据命令：`python _audit/tmp_dns_probe.py`（22:10:46，`aliyunsdkcore CommonRequest → alidns.aliyuncs.com / 2015-01-09 / DescribeDomainRecords`，PageSize=500 分页取全量）。
> **重点核对**：`tool` 存在（DISABLE，CNAME→香港 OSS）；`_dnsauth.tool` 存在（DISABLE）；`_acme-challenge.tool` 存在（DISABLE）；`me` **不存在（唯一被删记录）**；`start` 存在（DISABLE）；`mc` 存在（DISABLE，A=115.29.166.27）。
> **注意**：**整域 6 条记录全部 DISABLE**，并非 2026-11-06 降损方案建议的「只停 `tool` 一条」（memory 2026-11-06 L149），详见风险 R-1。

### 2.3 实测解析（公网 / 本机 / 权威）

| 查询目标 | 公共解析 223.5.5.5 | 本机系统解析器 | 权威 NS dns21.hichina.com | 结论 |
|----------|--------------------|----------------|---------------------------|------|
| `tool.furina.fun` (CNAME) | **NXDOMAIN**（DNS 名称不存在） | 失败（getaddrinfo 11001） | **NXDOMAIN** | 记录被禁用，无可解析答案 |
| `mc.furina.fun` (A) | **NXDOMAIN** | 失败 | **NXDOMAIN** | 同上 |
| `start.furina.fun` (CNAME) | **NXDOMAIN** | 失败 | **NXDOMAIN** | 同上 |
| `me.furina.fun` | **NXDOMAIN** | 失败 | **NXDOMAIN** | 记录已删除 |
| `_dnsauth.tool` / `_acme-challenge.tool` (TXT) | NXDOMAIN | — | **NXDOMAIN** | 记录被禁用 |
| `furina.fun` (NS) | 返回 SOA + NS `dns21/dns22.hichina.com` | — | — | **NS 委派仍生效**，域名未被 clientHold |

> 证据命令：`Resolve-DnsName ... -Server 223.5.5.5` / `-Server dns21.hichina.com`、`nslookup`、`python _audit/tmp_net_probe.py`（22:13:44–22:15:15）。
> 判定：**不是记录被删，而是记录 Status=DISABLE（暂停解析）**；域名 NS 仍正常委派 → 不是域名级 clientHold，也不是 registrar 停用。

### 2.4 DNS 解析量统计（只读，旁证暂停时间）

| 日期 | 总查询次数 | 单点（按小时）最大 |
|------|-----------|--------------------|
| 2026-11-03 | 0 | 0 |
| 2026-11-04 | 1,060 | 122 |
| 2026-11-05 | 1,226 | 160 |
| 2026-11-06 | **1,947** | 170 |
| 2026-11-07 | **899** | 113 |
| 2026-11-08 | 436 | 44 |
| 2026-11-09 | 400 | 58 |

> 证据命令：`tmp_ecs_probe.py` → `DescribeDomainStatistics(DomainName=furina.fun, StartDate=2026-11-03, EndDate=2026-11-09)`（168 个数据点，按小时）。
> 解读：11-06→11-07 查询量减半、之后逐日下降，与「2026-11-07 起暂停解析（AGENTS §4b-14 / HANDOFF §39）」以及缓存/客户端重试逐步衰减一致；**仍有查询量 ≠ 能解析**（权威 NS 均 NXDOMAIN）。停解析的**精确时刻/操作人**未验证（`DescribeDomainLogs` 仅返回域名级 add 日志，无记录级操作历史，最新仅 2026-06-17 的 add 事件）。

### 2.5 DNS 相关异常 / 风险

- **R-1（高）**：**整域暂停超出既定降损方案**——6 条记录全 DISABLE（含 `mc`、`start`、`_dnsauth.tool`、`_acme-challenge.tool`）。2026-11-06 的方案建议「只 Disable `tool` 一条，别停整域，否则 mc/start/_dnsauth/证书续签受牵连」（memory 2026-11-06 L149）。当前状态直接导致：MC 入口、一键启动入口、OSS 自定义域名归属复验（`_dnsauth.tool`）、证书 DNS-01 续签**全部停摆**。恢复时需逐条 `SetDomainRecordStatus(ENABLE)`（写操作，本次未做）。
- **R-2（高）**：证书 2027-01-07T11:13:09Z 到期（剩余 ≈58.9 天），续签依赖 `_acme-challenge.tool` TXT，而该记录当前 DISABLE → **暂停期间无法自动续签**；若恢复解析晚于 2027-01-07，HTTPS 会因证书过期失败（需恢复前先续证/重跑 `setup_tool_site.py`，属写操作）。
- **R-5（低-中）**：`me` 下线收尾不完整——`me` CNAME 已删、`me-furina-fun` Bucket 已删，但 `_dnsauth.me` TXT 记录仍在（DISABLE）、`furina-site-logs/me/` 仍有 **123 个日志对象 / 1.05 MB**（最后写入 2026-10-20T18:45:56+08:00），偏离 `ME-FURINA-SHUTDOWN.md` 第 4 步。

---

## 3. 阿里云 ECS 121.196.47.2（杭州 2C2G，`i-bp1ibr9hs7ewepmm1ugw`）

### 3.1 实例信息（只读 API，未登录）

| 项 | 实测状态（2026-11-09 22:16） | 证据命令 / 输出摘要 | 结论 |
|----|------------------------------|----------------------|------|
| 实例 | `i-bp1ibr9hs7ewepmm1ugw`，名称 **class_tool**，`cn-hangzhou-g`，`ecs.e-c1m1.large`（2C2G），Ubuntu 26.04 | `DescribeInstances(RegionId=cn-hangzhou)` + `DescribeInstanceStatus` → `Status=Running` | **仍在运行** |
| 公网 IP | `121.196.47.2`（私网 `172.16.139.251`，无 EIP） | 同上 | 与文档一致 |
| 计费/到期 | PrePaid（包年包月），创建 2026-11-03T12:55Z，**到期 2027-11-03T16:00Z** | 同上 | 在有效期内 |
| 安全组 | `sg-bp1cvttk00sb37dauyne` | `DescribeSecurityGroupAttribute`：ingress 5 条（见下） | 22 限家庭固定 IP，80/443 全网，另残留 25565/tcp 与 24454/udp 旧 MC 规则 |

安全组 ingress 实测规则：`22` ← `110.88.108.89/32`（home fixed ip）；`80` ← `0.0.0.0/0`；`443` ← `0.0.0.0/0`；`25565/tcp` ← `0.0.0.0/0`；`24454/udp` ← `0.0.0.0/0`（后两条为「我的世界」遗留）。

### 3.2 端口实测

| 端口 | 实测状态（22:13） | 证据 / 说明 | 结论 |
|------|-------------------|-------------|------|
| 22 | **超时**（TimeoutError，5,014 ms） | `tmp_net_probe.py` → `socket.create_connection` | 安全组仅放行 `110.88.108.89/32`，本机当前出口 IP 不在白名单 → 探测被丢包；**未 SSH 登录** |
| 80 | **OPEN**（2,016 ms） | 同上；`Server: Caddy` | 服务在跑 |
| 443 | **连接拒绝**（ConnectionRefusedError 10061，2,143 ms） | 同上；安全组允许 443 但主机无监听 | Caddy 只监听 :80，**未启用 HTTPS**（与 `deploy_ecs.py` 生成的 Caddyfile `:80 {}` 一致） |

### 3.3 HTTP 实测（只读 GET）

| 路径 | 实测状态（2026-11-09 22:13–22:14） | 证据命令 / 输出摘要 | 结论 |
|------|------------------------------------|----------------------|------|
| `GET /` | **200**，**166,952 B**，sha256 `1fefeacae5f205533cdc045ab1cfdad05bce2d0a37468b695540872c02ff5d95`，`Server: Caddy`，`Content-Type: text/html; charset=utf-8`，`Last-Modified: Tue, 03 Nov 2026 13:25:42 GMT`；**无 Content-Encoding（未 gzip，字节直读）** | `tmp_net_probe.py` → `urllib` GET（`Accept-Encoding: identity`），标题=`班级工具 · tool.furina.fun` | 提供**静态站镜像（旧版）** |
| `GET /api/status` | **200**，**213 B**，`Server: uvicorn`，完整 JSON：`{"ok":true,"updatedAt":"2026-11-09T21:41:02+0800","pageBytes":6166576,"boardBytes":6088469,"sha256":"d2d9221c4af2454e22faf071e420aec242606e3acdb941b3a718a6f002ee8526","counts":{"groups":67,"homework":0,"docs":10}}` | 同上（完整输出，见 `_audit/tmp_net_probe.log`） | 提供**同步 API**，且数据**今日 21:41 仍在更新** |
| `GET /healthz` | **404**，0 B | 同上 | Caddy 只反代 `/api/*`，未暴露 FastAPI 的 `/healthz`（与部署脚本 Caddyfile 一致） |
| `GET /board`、`GET /board/` | **200**，**6,166,576 B**，sha256 `d2d9221c4af2454e22faf071e420aec242606e3acdb941b3a718a6f002ee8526`，`Last-Modified: Mon, 09 Nov 2026 13:41:02 GMT`，标题=`班级简报 · 待处理通知 · 班级工具` | 同上 | 提供**班级简报 board（当前版本）** |
| `GET https://121.196.47.2/` | 失败：连接被重置/443 拒绝；TLS 证书无法取得 | 同上（insecure TLS 握手） | **未启用 HTTPS** |

### 3.4 与本地源码 / OSS 线上对象的对比（镜像新旧判定）

| 对象 | 字节数 | sha256 | 对比结论 |
|------|--------|--------|----------|
| OSS 线上 `index.html`（§1.3） | 732,621 | `65610511…` | 当前线上最新（本地 MATCH） |
| 本地 `web/tools/index.html` | 732,621 | `65610511…` | 与 OSS 一致 |
| **ECS `GET /`（166,952 B）** | 166,952 | `1fefeacae5f205533cdc045ab1cfdad05bce2d0a37468b695540872c02ff5d95` | **= 本地 `tools/_backup/index_local_20261103_2215_preTT.html` 与 `_backup/index_online_20261103-2240.html`（均 166,952 B / 同 sha）→ 即 2026-11-03 21:25 部署的版本** |
| ECS `GET /board` | 6,166,576 | `d2d9221c…` | **= 本地 `web/tools/notice-board-live-demo.html`（6,166,576 B，mtime 2026-11-09 21:40:57）→ board 是当前版本** |

内容标记检查（ECS `/` 字节中检索）：`APP_VER`=0、`2.0.0`=0、`pw-trend-top`=0、`tLogin`=0、`诊断`=0；`抽签`=36、`tool.furina.fun`=7 → 确认是 **v2.0.0（2026-11-05）之前**的旧页面。ECS 镜像比线上 OSS **小 565,669 B**（约 6 天、多次发布落后）。

### 3.5 部署形态（推断依据：本机文件 + 响应头，未登录服务器）

- 本机 `C:\briefdesk\scripts\deploy_ecs.py`（mtime 2026-11-03 21:25:13，只读阅读）写入的 Caddyfile 为：
  `:80 { encode gzip; handle /api/* { reverse_proxy 127.0.0.1:8090 }; handle /board* { rewrite * /board.html; root * /opt/briefdesk/data; file_server }; handle { root * /var/www/tool; file_server } }`
  → 与实测「80 开放 / 443 拒绝 / `/api/*` 走 uvicorn / `/board` 返回 board.html / `/` 返回 /var/www/tool 旧 index.html」**完全吻合**。
- 本机 `C:\briefdesk\cloud\briefdesk-board.service`、`server.py`（FastAPI：`GET /healthz`、`GET /api/status`、`POST /api/page|/api/data`、`GET /`）→ 服务名 `briefdesk-board`，uvicorn 监听 127.0.0.1:8090。
- **未 SSH 登录**（密钥属机密；安全组也不放行本机）。systemd 实际状态未直接验证，但 80 端口响应 + `/api/status` 数据更新证明 Caddy 与 FastAPI 均在运行。

### 3.6 数据推送是否仍在进行

- `/api/status` 的 `updatedAt = 2026-11-09T21:41:02+0800`（今日）→ **推送管道活跃**；`pageBytes=6,166,576` 与 `/board` 实际字节一致；`sha256=d2d9221c…` 与本地 `notice-board-live-demo.html` 一致（该文件 mtime 21:40:57）。
- 本机 `C:\briefdesk\secrets\cloud.env` **存在**（103 B，mtime 2026-11-03 21:26，仅检查存在性，**未读内容**）；`C:\briefdesk\scripts\push_to_cloud.py`、`detect_docs.py` 存在（后者 mtime 今日 18:57）。
- 结论：**ECS 仍在承担「班级简报 board + 同步 API」角色**，但工具站静态镜像停留在 2026-11-03。

### 3.7 ECS 异常 / 风险

- **R-3（中）**：ECS 静态站镜像是 2026-11-03 旧版（166,952 B，无 APP_VER/诊断/个人课表/电费等 11-05 之后功能）；若备案通过后按原计划切到该 ECS 作为大陆落点，必须先重新部署静态站并启用 HTTPS，否则会回退到旧站。
- **R-4（低）**：443 已放行但无监听（Caddy 只有 `:80`）——目前裸 HTTP 提供 board 与 API（含 token 鉴权），后续切域名时需补 HTTPS。
- 安全组残留 25565/tcp、24454/udp（旧「我的世界」规则）；实例仍在预付费有效期（至 2027-11-03），当前属「闲置旧快照 + board 服务」状态，**去留需要 Lead/用户决策**（本任务不处置）。

---

## 4. MC 服务器（`mc.furina.fun`；任务给的 120.27.217.236 与 DNS 实际值 115.29.166.27）

### 4.1 端口实测（两个候选 IP）

| 目标 | 22 | 25565 | 80 | MC status ping | 结论 |
|------|----|-------|----|----------------|------|
| `120.27.217.236`（任务/旧文档地址） | 超时 5,015 ms | **超时** 5,012 ms | 超时 5,015 ms | 超时失败 | 不可达 |
| `115.29.166.27`（**DNS A 记录实际值**） | 超时 5,014 ms | **超时** 5,002 ms | 超时 5,006 ms | 超时失败 | 不可达 |

> 证据命令：`python _audit/tmp_net_probe.py`（22:13:44–22:15:15）；`nslookup/Resolve-DnsName` 确认 `mc.furina.fun` NXDOMAIN（§2.3）。全超时（而非拒绝）表示无路由/被过滤，无法据此区分「实例停机」与「安全组过滤」。

### 4.2 资源盘点（只读）

| 项 | 实测状态（22:17） | 证据命令 / 输出摘要 | 结论 |
|----|-------------------|----------------------|------|
| 全地域 ECS 实例 | 33 个区域盘点，**全账号仅 1 台**：`class_tool`（121.196.47.2） | `DescribeRegions` + 逐区域 `DescribeInstances`（`tmp_ecs_probe2.py`） | **未发现 MC 实例** |
| 轻量应用服务器 SWAS | `ListInstances(RegionId=cn-hangzhou)` → `{"Instances": [], "TotalCount": 0}` | 同上 | 也不是轻量服务器 |
| DNS 记录 | `mc` A `115.29.166.27`，Status=**DISABLE** | §2.2 | 记录残留、已暂停 |

### 4.3 文档/记忆交叉证据

- memory `2026-11-03.md` L3「**14:30 MC 服务器全量备份并下载（准备关停阿里云）**」；L6「服务器实际公网 IP 是 **115.29.166.27**（用 ECS DescribeInstances + AK 查到）。SSH/25565 在真实 IP 上都是通的」。
- memory `2026-11-06.md` L141：`mc A→115.29.166.27`。
- 结论：任务描述里的 `120.27.217.236` 是**旧地址**；当前 DNS A 指向 `115.29.166.27`，但该实例在当前账号已不可见。

### 4.4 未验证 / 结论

- **结论（高置信）**：MC 服务器 ECS **很可能已于 2026-11-04 前后按「全量备份后关停」计划释放**；两个历史 IP 均不可达；`mc` A 记录（115.29.166.27）属**残留记录**（恢复解析前应清理/更新，写操作未做）。
- **未验证**：① 无法证明实例「已释放」——DescribeInstances 只证明当前账号/当前可见区域无该实例，不排除资源在其它阿里云账号；② 无法区分长时间停机与释放（两 IP 全超时，无 TCP 拒绝证据）。

---

## 5. 阿里云函数计算 FC（`start.furina.fun` → `mc-start-mc-serv-control-alwwvseret.cn-hangzhou.fcapp.run`）

| 项 | 实测状态（2026-11-09 22:14–22:15） | 证据命令 / 输出摘要 | 结论 |
|----|------------------------------------|----------------------|------|
| FC 默认公网域名（HTTPS GET `/`） | **HTTP 403**，691 B，页面标题=**「MC 服务器状态」**，正文=`无权限 / token 错误，无法操作服务器` | `python _audit/tmp_net_probe.py` → `http_get` | **FC 仍在服务**（默认域名可达、函数有响应）；403 是其 token 校验页，属预期 |
| FC 默认域名 HTTP | 同样 403 / 691 B（同 sha） | 同上 | 正常 |
| `start.furina.fun` | **NXDOMAIN**（DNS `start` CNAME 记录 DISABLE） | §2.3 | 域名入口不可用 |
| 实际启动 MC 能力 | **未验证**（需 token，且目标 ECS 实例疑似已释放） | — | 不建议依赖 |

---

## 6. ICP 备案状态（只查文档，不做任何备案操作）

| 项 | 状态 | 证据（文件/行） | 结论 |
|----|------|------------------|------|
| 网站 ICP 备案（`furina.fun` / `tool.furina.fun`，阿里云接入） | **审核中 / 办理中（未通过）** | `web/_compliance/备案内容自查_20261106.md` L3「阿里云 ICP 备案（审核中）」；memory `2026-11-06.md` L135「furina.fun 网站 ICP 备案**正在办理中**」、L139 用户反馈「仍在备案审核中」；`2026-11-05.md` L215-218 备案方案 | 网站备案**尚未通过**；11-06 之后文档无「通过」记录 |
| 小程序备案 | **已通过并发布**，备案号 **闽ICP备2026042939号** | memory `2026-11-06.md` L135/L139；`HANDOFF.md` L2029「小程序已发布版本（备案号 闽ICP备2026042939号）」 | 与网站备案是两套（App 备案 vs 网站 ICP） |
| 公安联网备案 | **未办理**（要求网站开通后 30 日内） | `_compliance/implementation_plan.md` L40、L139；`备案内容自查` L64 | 待网站备案通过/上线后办理 |
| 停解析与备案的关系 | 为首次备案「审核期停站」而暂停解析（记录级 DISABLE） | `AGENTS.md` §4b-14（2026-11-07「furina.fun DNS 暂停」）、`HANDOFF.md` §39（用户将暂停全部解析，先 `web_pause.py --on`）；本次实测 6 条记录全 DISABLE 与之吻合 | 当前是「网站备案审核中 → 停解析」状态 |
| 备案号悬挂 | **未悬挂**（线上/本地 `index.html` 全文检索 `ICP`、`备案` = **0 命中**） | `grep` on `web/tools/index.html`（0 matches） | 符合「备案通过后再挂」的待办，非异常 |
| 实时管局状态 | **未验证**（无备案系统查询凭据/不登录，不做备案操作） | — | 文档状态截至 2026-11-06；实时以阿里云备案控制台为准 |

> ⚠️ 与停站相关的补充风险：见 R-4（OSS 默认端点仍匿名可读）——备案核查可能认为「站点仍可访问」，与 `_compliance/research_delivery_paths.md` R11 提示一致。

---

## 7. 风险 / 异常汇总（按严重度）

| 编号 | 级别 | 异常 | 影响 | 建议（本次只读，未执行） |
|------|------|------|------|--------------------------|
| R-1 | 高 | **整域 6 条 DNS 记录全部 DISABLE**（含 mc/start/_dnsauth/_acme），非方案预期的「仅停 tool」 | MC/一键启动/OSS 域名校验/证书续签全部停摆 | 确认是否为有意整域暂停；恢复时逐条 `SetDomainRecordStatus(ENABLE)` |
| R-2 | 高 | OSS 自定义域名证书 **2027-01-07T11:13:09Z 到期（≈58.9 天）**，且 DNS 暂停期无法 DNS-01 续签 | 恢复解析若晚于该日期 → HTTPS 失败 | 恢复前先续证（重跑 `setup_tool_site.py` 或换新证书）；记录到期提醒 |
| R-3 | 中 | ECS 静态站镜像停留 2026-11-03（166,952 B，无 v2.0.0 后功能）；443 无监听 | 若直接切 ECS 会回退旧站；无 HTTPS | 备案通过后先重新部署最新 `index.html` + 启用 HTTPS 再切解析 |
| R-4 | 中 | 备案期「停站」仅停域名解析；OSS 默认端点仍匿名可读（bucket public-read） | 备案抽查/驳回风险 | 评估是否临时收紧 OSS 访问（写操作） |
| R-5 | 低-中 | `me` 下线收尾不完整：`_dnsauth.me` TXT 仍存在（DISABLE）；`furina-site-logs/me/` 123 对象/1.05 MB 未清 | 残留/误导 | 按 `ME-FURINA-SHUTDOWN.md` 第 4 步清理（写操作） |
| R-6 | 低 | 线上 3 个对象（apple-touch-icon.png/favicon.ico/robots.txt）本地源码树无对应文件 | 本地无法重建，迁移/重建桶时需补 | 确认来源并纳入源码/部署清单 |
| R-7 | 低 | ECS 安全组残留 25565/tcp、24454/udp（旧 MC 规则）；22 仅放行 110.88.108.89/32（家庭固定 IP，IP 变化会失联） | 安全面收敛/运维便利 | 后续随 MC 废弃/家庭 IP 变化调整 |
| R-8 | 信息 | MC 服务器疑似已释放，DNS `mc` A 记录（115.29.166.27）残留；`start` 一键启动 FC 仍在线但目标疑似不存在 | 恢复解析后 mc/start 指向无效资源 | 恢复解析前先决定 MC 去留并清理 A 记录 |

---

## 8. 未验证事项（明确标注，未猜测）

1. **网站 ICP 备案实时状态**：文档到 2026-11-06 为止为「审核中」；无备案系统查询凭据，未登录备案控制台 → 以阿里云备案控制台为准。
2. **证书是否曾续期**：仅能确认 OSS 当前绑定证书 valid_start=2026-10-09T11:13:10Z（= 首次部署日）；「未续期」为基于起始日期的推断，非续期历史直接证据。
3. **MC ECS 是否已释放**：当前账号全地域仅 class_tool、SWAS 0 台、两 IP 全超时；但无法排除资源在其他阿里云账号，无法直接证明「已释放」。
4. **ECS 上 systemd/Caddy 实际运行状态**：未 SSH 登录（密钥属机密、安全组不放行本机）；依据 = HTTP 响应头（Caddy/uvicorn）+ 本机 `deploy_ecs.py`/`server.py`/`briefdesk-board.service` 部署脚本与文档。
5. **ECS `/api/status` 中 `counts.homework=0` 是否符合预期**：属数据管线（briefdesk）范围，本任务未核实。
6. **OSS 自定义域名证书是否已被 OSS 周期性复验**：`_dnsauth.tool` 当前 DISABLE，若 OSS 复验可能影响绑定，未观测到实际影响（未验证）。
7. **DNS 记录被禁用的精确时间/操作人**：`DescribeDomainLogs` 只返回域名级日志（仅 2026-06-17 add），无记录级操作历史；文档记载「2026-11-07 起」。
8. **匿名 ListObjects**：仅验证匿名 `GET index.html` 可读；未验证匿名列举对象清单。
9. **FC 能否真正启动 MC**：需 token，且目标实例疑似已释放，未做任何调用（避免写/操作）。

---

## 9. 附录：探测命令与时间戳索引

| 时间（+08:00） | 命令 | 覆盖内容 | 输出文件 |
|----------------|------|----------|----------|
| 22:10:46–22:10:47 | `python _audit/tmp_dns_probe.py` | DNS 全量记录 / DomainInfo / Ns / Statistics | 终端输出（首次运行未重定向） |
| 22:11:24–22:11:46 | `python _audit/tmp_oss_probe.py` | Bucket 列表 / 属性 / ACL / 网站 / 日志 / CNAME 证书 / 6 对象头与 sha / 本地比对 / 日志桶统计 | `_audit/tmp_oss_probe.log` |
| 22:13:01–22:13:09 | `python _audit/tmp_oss_probe2.py` | ACL 值 / 证书剩余天数 / robots 内容 / 日志按日统计 / me/ 残留 | `_audit/tmp_oss_probe2.log` |
| 22:13:44–22:15:15 | `python _audit/tmp_net_probe.py` | ECS 端口 & HTTP；MC 端口 & status ping；FC；域名解析；OSS 默认端点；暂停域名 URL | `_audit/tmp_net_probe.log` |
| 22:16:00–22:16:01 | `python _audit/tmp_ecs_probe.py` | ECS 实例/状态；DNS 解析量统计 | `_audit/tmp_ecs_probe.log` |
| 22:17:09–22:17:14 | `python _audit/tmp_ecs_probe2.py` | 全地域 ECS 盘点 / SWAS / 安全组规则 | `_audit/tmp_ecs_probe2.log` |
| 22:17:39 | `python _audit/tmp_dns_logs.py` | `DescribeDomainLogs` / `DescribeChangeLogs` | `_audit/tmp_dns_logs.log` |
| ≈22:18–22:19 | ACL/证书复核；`python deploy/oss_object.py sha/check index.html|tt.json|assets/qr_tools.png` | 复核（均 MATCH） | 终端输出 |
| 22:13–22:14 | `Resolve-DnsName -Server 223.5.5.5 / dns21.hichina.com`、`nslookup` | 公网/权威解析实测 | 终端输出 |

> 只读 API 清单：OSS `ListBuckets/GetBucketInfo/GetBucketAcl/GetBucketWebsite/GetBucketLogging/ListBucketCname/ListObjectsV2/HeadObject/GetObject`；DNS `DescribeDomainRecords/DescribeDomainInfo/DescribeDomainNs/DescribeDomains/DescribeDomainStatistics/DescribeDomainLogs/DescribeChangeLogs`；ECS `DescribeRegions/DescribeInstances/DescribeInstanceStatus/DescribeSecurityGroupAttribute`；SWAS `ListInstances`；以及 HTTP GET / TCP connect / TLS 握手 / MC status ping。**未调用任何写接口**。
