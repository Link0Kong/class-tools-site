# 仓库同步说明（五个端各一个仓库 · GitHub + Gitee 双远端）

2026-11-18 用户要求：**按端建仓，不按功能建仓；每个端都要能自动提交。**

## 一、仓库地图

| 端 | GitHub | Gitee | 本地目录 |
|---|---|---|---|
| 网页 / 部署 / 通知管线 / 电费工具包 | `Link0Kong/class-tools-site` | `ko_Link/class-tools-site` | `~\workspace\web` |
| Android | `Link0Kong/class-tools-android` | `ko_Link/class-tools-android` | `~\workspace\android-class-tools` |
| 微信小程序（含测试） | `Link0Kong/class-tools-mp` | `ko_Link/class-tools-mp` | `~\workspace\mp-class-tools` |
| HarmonyOS | `Link0Kong/class-tools-harmony` | `ko_Link/class-tools-harmony` | `~\workspace\harmony-class-tools` |
| Windows | `Link0Kong/class-tools-windows` | `ko_Link/class-tools-windows` | `~\workspace\windows-class-tools` |

- 分支统一 `master`；两端仓库均为**私有**（含个人信息 / 服务器配置），不要改为公开。
- 原按功能拆的三个仓库已合并并归档：
  - `class-tools-briefdesk` → 本仓 `briefdesk/`（完整历史）
  - `class-tools-power` → 本仓 `power/`（完整历史）
  - `class-tools-mp-tests` → `mp-class-tools/tests/`（完整历史）
- 旧本地路径保留 junction，历史脚本里的绝对路径继续可用：
  `briefdesk-plan` → `web/briefdesk`、`perfect-campus-power` → `web/power`、`mp-class-tools-tests` → `mp-class-tools/tests`。
- 详细说明见 `REPOS.md`。

## 二、每次改完，只跑这一条

```cmd
sync-repos.cmd "feat: 本次改动一句话说明"
```

五个端仓库根目录都有同一份 `sync_repos.py` + `sync-repos.cmd`，按所在仓库自动识别 GitHub / Gitee 两个远端。
流程（任一步失败都会停止并明确报错）：

1. 安全检查：敏感路径（证书 / `creds.env` / `*.pem` / `*.key` / `*.jks` / `keystore.properties` 等）、
   疑似令牌 / 私钥 / AccessKey / 明文数据库密码、单文件 >50MB、单次 >200MB → 直接中止；
2. `git add -A`；
3. `git commit -m "<说明>"`（工作区无改动时跳过）；
4. 推 GitHub（失败自动重试 3 次）→ 推 Gitee（失败自动重试 3 次），远端领先时先 rebase；
5. `git ls-remote` 核对**两端 HEAD 与本地 HEAD 一致**，全部一致才输出完成。

网络偶发中断后，**重跑同一条命令即可**（不会产生空提交）。只想核对：

```cmd
sync-repos.cmd --check
```

## 三、自动提交（兜底）

- 计划任务 `ClassToolsRepoAutoSync`：每 **10 分钟**扫描五个端仓库；
  工作区有改动、且最近 **5 分钟**没有新写入（避免提交写一半的文件）时，
  自动执行该仓库的 `sync_repos.py --auto`（提交说明自动汇总改动目录）并推双端。
- 日志：`web/tools/repo_ops/_logs/auto_commit.log`（只在本机，不入库）。
- 实现：`web/tools/repo_ops/auto_commit_all.py`；手动跑一轮：

```cmd
python web\tools\repo_ops\auto_commit_all.py --dry-run   # 只看会提交什么
python web\tools\repo_ops\auto_commit_all.py             # 真正执行
```

- 暂停 / 恢复 / 删除：

```cmd
schtasks /Change /TN ClassToolsRepoAutoSync /DISABLE
schtasks /Change /TN ClassToolsRepoAutoSync /ENABLE
schtasks /Delete /TN ClassToolsRepoAutoSync /F
```

- **agent 仍应在完成改动时主动跑一次 `sync-repos.cmd`**，自动提交只是兜底，不替代说明。

## 四、说明怎么写

- 前缀：`feat:` 新功能 / `fix:` 修 bug / `docs:` 文档 / `test:` 测试 / `chore:` 杂务 / `refactor:` 重构 / `perf:` 性能 / `revert:` 回滚；没有前缀时脚本自动补 `chore: `。
- 必须写清「改了什么」；`update`、`fix`、`同步`、`修改` 这类笼统说明会被脚本拒绝。
- 中文可以；**不要 emoji**（Gitee 提交列表会乱码）。
- 站点上线类改动，另在 `CHANGELOG.md` 记一条（时间 / 内容 / 回滚点）；重要架构变动补 `HANDOFF.md`。

## 五、验证（任何时候都可查）

```cmd
git rev-parse HEAD
git ls-remote origin refs/heads/master
git ls-remote gitee refs/heads/master
```

三行 SHA 相同即两端同步完成；也可以 `sync-repos.cmd --check` 一键核对。

## 六、凭据与 .gitignore 约定

- GitHub 走 `gh auth`（Windows 凭据管理器 keyring）；Gitee 走 `credential.helper=store`（`C:\Users\Ko_Li\.git-credentials`，只在本机）。
  **不要读取、复制、粘贴这些凭据文件的内容。**
- **绝不入库**：`tools/cert/`、`deploy/creds.env`、`deploy/acme_account_key.pem`、任何 `*.pem` / `*.key` / `*.p12` / `*.jks` / `*.env`、
  `.git-credentials`、`tools/_backup/`（线上备份快照）、`ppt/work/`、截图 / 日志 / 临时产物、`.zcode/`。
- **入库**：站点与部署脚本、测试 `.py` / `.md`、文档、验收报告、`tools/tt.json` 课表快照；
  `tools/tests/frozen/` 仅保留既有基线冻结副本，新生成的不入库。
- 注：`tools/tt.json` 由本机计划任务 `JwxtTimetableSync`（每日 07:00）自动更新；出现改动时随下一次提交入库。

## 七、旧仓库归档

- GitHub：已用 `gh repo archive` 归档 `class-tools-briefdesk`、`class-tools-power`、`class-tools-mp-tests`。
- Gitee：无可用 API 凭据，需在网页「仓库设置 → 归档」手动归档同名的三个仓库；
  归档只读、保留历史，不影响新仓库。
