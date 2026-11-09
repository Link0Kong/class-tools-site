# me.furina.fun 下线清单（计划 2026-10-20 执行）

> 盘点时间：2026-10-13。盘点方式：Aliyun DNS API + OSS API 实测（非凭记忆）。
> **tool.furina.fun（班级工具站）与 mc.furina.fun（Minecraft 服务器）继续保留，不要动。**

## 一、现状

### DNS（furina.fun，共 7 条）
| 主机记录 | 类型 | 值 | 处理 |
|---|---|---|---|
| `me` | CNAME | me-furina-fun.oss-cn-hongkong.aliyuncs.com | **删除**（RecordId 2108479560433428480） |
| `_dnsauth.me` | TXT | a9b76d22dd4c801c343d07bb465c7b69 | **删除**（域名归属校验残留，RecordId 2108478852313201664） |
| `tool` | CNAME | tool-furina-fun.oss-cn-hongkong.aliyuncs.com | 保留 |
| `_dnsauth.tool` | TXT | 61783b3e3a87253f1a9121abd762ee8a | 保留 |
| `_acme-challenge.tool` | TXT | eeYxJiNAVAQscdikqPV7aluhPO2kNNHQiolul-YFpx4 | 保留（工具站续签用） |
| `start` | CNAME | mc-start-mc-serv-control-alwwvseret.cn-hangzhou.fcapp.run | 保留（MC 一键启动） |
| `mc` | A | 120.27.217.236 | 保留（MC 服务器） |

### OSS Bucket（oss-cn-hongkong）
| Bucket | 内容 | 处理 |
|---|---|---|
| `me-furina-fun` | 14 objects / 883 KB（全是本页：index.html、og.png、election.html、assets/、files/、favicon、校验 txt） | **整个删除** |
| `furina-site-logs` | 访问日志，含 `me/` 与 `tool/` 两个前缀 | **只删 `me/` 前缀**，tool/ 保留 |
| `tool-furina-fun` | 班级工具站 | 保留 |

## 二、执行步骤（按顺序）

1. **先备份**：把 `me-furina-fun` 全量下载到 `workspace/archive/me-furina-fun-<日期>/`
2. **删 DNS**：`me` CNAME + `_dnsauth.me` TXT（用 Aliyun `DeleteDomainRecord`）
3. **删 Bucket**：`me-furina-fun`
4. **清日志残余**：删除 `furina-site-logs` 里 `me/` 前缀的全部对象
5. **清本地残余**：
   - 删 `web/ziqi/cert/`（站点证书私钥，机密残留）
   - 归档 `web/deploy/deploy_oss.py`、`deploy_cert.py`、`sync.py`（me 专用）
   - **保留** `web/deploy/acme_account_key.pem`（工具站续签复用同一 LE 账号）
   - `web/ziqi/` 源码可保留或归档（建议留一份源码）
6. **复验**：
   - `me.furina.fun` → 解析失败 / 打不开
   - `tool.furina.fun` → 200，工具站正常
   - `mc.furina.fun` → MC 正常
7. **收尾**：本清单 ✅ 标记完成，写进当天 memory

## 三、注意

- 删对象/桶不可逆，**执行前先把备份做出来**。
- 销毁性操作（删 DNS 记录、删 Bucket）**先发方案给旅行者确认**再动手。
- 证书无需显式吊销：域名不再解析即可；只要不再续签，到期自然失效。
- GitHub 侧已无本页痕迹（代码搜索 `me.furina.fun` 命中 0），无需处理。

## 四、保留站点（复验用）
- https://tool.furina.fun/  → Bucket `tool-furina-fun`
- mc.furina.fun（游戏）/ start.furina.fun（一键启动）
