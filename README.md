# 班级工具站 · class-tools-site

为班级服务的工具站完整归档（生产：**https://tool.furina.fun/**）。站点是 **单文件、零依赖、零外部请求** 的静态页 `tools/index.html`；班级数据走 CloudBase PostgreSQL + PostgREST（身份 token + RLS 鉴权），本机 localStorage 仅作缓存。

> 当前版本 **2.0.0**。版本号唯一来源：`tools/index.html` 的 `APP_VER`（小程序在 `mp-class-tools/utils/version.js`，源码不在本仓库）。

- 仓库（**均为私有**，含个人信息、服务器 IP 与云端配置说明，请勿公开/转存）：
  - GitHub（主，remote `origin`）：https://github.com/Link0Kong/class-tools-site
  - Gitee（镜像，remote `gitee`）：https://gitee.com/ko_Link/class-tools-site
  - 全部项目仓库地图（小程序 / Android / HarmonyOS / Windows / 管线）：[REPOS.md](REPOS.md)
- 分支：`master`（两端同名）

## 先读什么

| 文档 | 内容 |
|---|---|
| [AGENTS.md](AGENTS.md) | **绝对红线 + 设计规范 + 架构补充**：动手前必读 |
| [HANDOFF.md](HANDOFF.md) | 完整交接：现状 / 架构 / 数据模型 / 部署 / 自检 / 历史坑 |
| [CLOUDBASE.md](CLOUDBASE.md) | 云端环境：CloudBase PG / PostgREST 接口、RLS、部署 |
| [SYNC.md](SYNC.md) | **双远端同步流程**（GitHub + Gitee，每次改完必跑） |
| [CHANGELOG.md](CHANGELOG.md) | 每次上线的记录：时间 / 内容 / 回滚点 |
| [tools/README.md](tools/README.md) | 站点功能、导出规范、实现细节 |

## 目录

```
tools/          站点本体：index.html（单文件主程序）、tt.json（课表快照）、tests/（自检套件）、build_notice_embed.py
legal/          五端隐私政策 / 用户协议（10 个独立静态页 + 文档中心 + manifest，见 legal/README.md）
deploy/         部署：OSS 上传（sync_tools.py）、五端法律页同步（sync_legal.py）、ECS 备案落点部署（ecs_site.py，见 deploy/ECS_DEPLOY.md）、CloudBase SQL、证书、对象校验（creds.env 等凭据已排除）
jwxt/           教务课表同步（本机 DPAPI 凭据；产物 tools/tt.json）
ppt/            PPT 演示：本机转换机 agent + 云端契约 / 运维文档
ziqi/           竞选自我介绍页静态源归档（独立 OSS，勿与本站混改）
attachments/    通知附件外置：签名 URL 契约 + ECS 私有存储服务端 + 本机客户端 + 单测
deploy/ECS_DEPLOY.md  ECS 备案落点部署（云助手通道，无需 SSH）
_audit/ _compliance/ _water_rules/ 验收报告/   审计、合规、水电规则研究、验收报告存档
AGENTS.md HANDOFF.md CLOUDBASE.md CHANGELOG.md SYNC.md README.md   项目文档
```

## 改完怎么交付（硬性）

1. **自检**：按改动范围跑 `tools/tests/` 下对应脚本（红线与基线见 [AGENTS.md](AGENTS.md) §0、[HANDOFF.md](HANDOFF.md) §5.2）。
2. **上线**（站点改动）：备份线上 `index.html` 到 `tools/_backup/` 后 `python deploy/sync_tools.py`；并在 `CHANGELOG.md` 记一条（时间 / 内容 / 回滚点）。
   - 备案落点 ECS（`121.196.47.2`）同步：先上传 OSS，再 `python deploy/ecs_site.py apply`（云助手通道，无需 SSH；详见 [deploy/ECS_DEPLOY.md](deploy/ECS_DEPLOY.md)）。
3. **提交并同时推送两个远端**（缺一不可）：
   ```cmd
   sync-repos.cmd "feat: 一句话说明本次改了什么"
   ```
   - 说明必须能看出改了什么（前缀 `feat:` / `fix:` / `docs:` / `test:` / `chore:` …；中文可以，不要 emoji）。
   - 脚本会：敏感路径 / 凭据特征检查 → `git add -A` → commit → 推 GitHub → 推 Gitee → **核对两端 HEAD 与本地一致**；网络失败自动重试。
   - **只推一个远端 = 未完成交付**；详细流程与排障见 [SYNC.md](SYNC.md)。
   - 只核对两端是否与本地一致：`sync-repos.cmd --check`（或 `python sync_repos.py --check`）。

## 安全红线（摘要；完整见 AGENTS.md §0）

- `deploy/creds.env`、`deploy/acme_account_key.pem`、`tools/cert/` 等凭据 **永不入库、不读取、不复制、不外发**。
- 不引入 npm / 构建链 / 前端框架 / CDN / 统计脚本；产物必须双击可开，JS 只用原生浏览器 API。
- 班级身份（学号 + 姓名）门禁、云端 RLS、导出图不泄露手机号 / 学号 / 宿舍号等约束见 AGENTS.md。
- 本仓库必须保持 **私有**；若需公开，先做完整脱敏（联系人、服务器 IP、云端配置、测试凭据等）。

## 当前状态

- 站点上线记录以 [CHANGELOG.md](CHANGELOG.md) / [HANDOFF.md](HANDOFF.md) 为准；DNS 备案暂停期以 `python deploy/oss_object.py check index.html` 的 OSS 对象字节校验为准。
- 仓库同步状态：`python sync_repos.py --check` 应输出 GitHub / Gitee / 本地 三方 SHA 一致。
