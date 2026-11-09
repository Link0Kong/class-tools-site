# 仓库同步说明（GitHub + Gitee 双远端）

本仓库是「班级工具站」完整归档：单文件站点 `tools/index.html`、部署脚本 `deploy/`、测试 `tools/tests/`、文档与历史说明。

> **用户要求（2026-11-10）**：以后每次修改都必须**同时上传 GitHub + Gitee 两个远端**，并**附上说明**。只推一个远端 / 不写说明 = 未完成交付。

## 远端与凭据

| 名称 | 平台 | 地址 | 角色 |
|---|---|---|---|
| `origin` | GitHub | https://github.com/Link0Kong/class-tools-site | 主 |
| `gitee` | Gitee | https://gitee.com/ko_Link/class-tools-site | 镜像 |

- 分支：`master`（两端同名，不要用 main）。
- 凭据：GitHub 走 `gh auth`（Windows 凭据管理器 keyring）；Gitee 走 `credential.helper=store`（`C:\Users\Ko_Li\.git-credentials`，只在本机）。
- 两个远端都是**私有仓库**；仓库含个人信息、服务器 IP、云端配置说明，**不要改成公开**；若要公开先做脱敏审计。

## 每次改完，只跑这一条

```cmd
C:\Users\Ko_Li\.openclaw\workspace\web\sync-repos.cmd "本次改动一句话说明"
```

脚本 `sync_repos.py` 的流程（任一步失败都会停止并明确报错）：

1. 安全检查：若提交范围里出现 `tools/cert/`、`deploy/creds.env`、`*.pem` / `*.key` / `*.env` 等敏感路径，或发现疑似 GitHub 令牌 / 私钥 / AccessKey / 明文数据库密码，**直接中止**；
2. `git add -A`；
3. `git commit -m "<说明>"`（工作区无改动时跳过）；
4. 推 GitHub（失败自动重试 3 次）→ 推 Gitee（失败自动重试 3 次）；
5. `git ls-remote` 核对**两端 HEAD 与本地 HEAD 一致**，全部一致才输出 DONE。

网络偶发中断后，**重跑同一条命令即可**（不会产生空提交）。只想核对两端是否一致：

```cmd
sync-repos.cmd --check
```

## 说明怎么写

- 前缀：`feat:` 新功能 / `fix:` 修 bug / `docs:` 文档 / `test:` 测试 / `chore:` 杂务 / `refactor:` 重构 / `perf:` 性能 / `revert:` 回滚；没有前缀时脚本自动补 `chore: `。
- 必须写清「改了什么」；`update`、`fix`、`同步`、`修改` 这类笼统说明会被脚本拒绝。
- 中文可以；**不要 emoji**（Gitee 提交列表会乱码）。
- 站点上线类改动，另在 `CHANGELOG.md` 记一条（时间 / 内容 / 回滚点）；重要架构变动补 `HANDOFF.md`。

## 验证（任何时候都可查）

```cmd
git rev-parse HEAD
git ls-remote origin refs/heads/master
git ls-remote gitee refs/heads/master
```

三行 SHA 相同即两端同步完成；也可以 `sync-repos.cmd --check` 一键核对。

## .gitignore 约定（必看）

- **绝不入库**：`tools/cert/`、`deploy/creds.env`、`deploy/acme_account_key.pem`、任何 `*.pem` / `*.key` / `*.env`、`.git-credentials`、`tools/_backup/`（线上备份快照）、`ppt/work/`、截图 / 日志 / 临时产物、`.zcode/`（工具过程文件）。
- **入库**：站点与部署脚本、测试 `.py` / `.md`、文档、验收报告、`tools/tt.json` 课表快照；`tools/tests/frozen/` 仅保留既有基线冻结副本，新生成的不入库。
- 注：`tools/tt.json` 由本机计划任务 `JwxtTimetableSync`（每日 07:00）自动更新；出现改动时随下一次提交入库，若只有 `fetchedAt` 变化，并入下次提交即可，不必单独提交。
- 提交前脚本会自动检查敏感路径；不要用 `git add -f` 强行加入被忽略的凭据文件。

## 仓库结构（简）

```
web/
├── tools/                 # 站点本体（index.html 单文件主程序 / tt.json 课表快照 / tests/ 自检套件）
├── deploy/                # 部署脚本（凭据文件已排除）
├── jwxt/  ziqi/  ppt/     # 教务同步 / 竞选页归档 / PPT 演示
├── _audit/  _compliance/  _water_rules/  验收报告/   # 审计、合规、水电规则、验收存档
├── HANDOFF.md  CHANGELOG.md  CLOUDBASE.md  AGENTS.md  README.md
├── SYNC.md                # 本文件
├── sync-repos.cmd         # 双远端同步入口（Windows）
└── sync_repos.py          # 同步脚本实现（敏感检查 / 提交 / 双推 / 核对）
```

## 出问题怎么办

| 现象 | 处理 |
|---|---|
| `push` 被拒（non-fast-forward），或脚本提示「远端有本地没有的提交」 | `git pull --rebase origin master`，解决后重跑 `sync-repos.cmd` |
| GitHub 连接重置 / 超时（本机网络对 github.com 偶发阻断） | 脚本已自动重试 3 次；仍失败就隔 1–2 分钟重跑同一条命令 |
| Gitee 认证失败 | 令牌可能过期：gitee.com → 设置 → 私人令牌 重新生成，覆盖 `C:\Users\Ko_Li\.git-credentials` 里 gitee.com 那一行（`https://ko_Link:<新令牌>@gitee.com`，LF 换行、不能带 CR） |
| push 卡住不返回 / 弹登录窗 | `git config --local --set credential.helper store` 后重试；并确认网络：`Test-NetConnection gitee.com -Port 443` |
| 中文文件名显示成 `\346\226\207` | `git config core.quotepath false`（本仓库已设） |
| 提交里混进了大文件 / 敏感文件 | `git rm --cached <文件>`，补进 `.gitignore` 后再提交 |

## 版本约定

- 分支：`master`。
- 两端 `master` 必须始终指向同一提交，以 `sync-repos.cmd --check` 为准。
