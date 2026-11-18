# 班级工具站 · 仓库地图（一端一仓）

> 2026-11-18 用户要求：**GitHub / Gitee 每个端只留一个仓库，不按功能拆仓库；每个端的改动都要能一键提交双远端。**
> 同日明确：**不设计划任务、不跑后台守护**，提交由 agent 改完后主动执行。
> 2026-11-16 全量核对：所有仓库均为**私有**，GitHub + Gitee 双远端，分支统一 `master`。
> 仓库含个人信息、服务器配置，**不要改为公开**。

## 一、五个端仓库

| 端 | 本地目录 | GitHub（origin） | Gitee（gitee） | 内容 |
|---|---|---|---|---|
| 网页 / 部署 | `web/` | https://github.com/Link0Kong/class-tools-site | https://gitee.com/ko_Link/class-tools-site | 单文件站点 `tools/index.html`、`deploy/`、`tools/tests/`、文档、**通知管线 `briefdesk/`**、**电费工具包 `power/`** |
| 小程序 | `mp-class-tools/` | https://github.com/Link0Kong/class-tools-mp | https://gitee.com/ko_Link/class-tools-mp | 原生小程序 v25 / 2.0.0，**`tests/`（原 mp-tests 仓库）** |
| Android | `android-class-tools/` | https://github.com/Link0Kong/class-tools-android | https://gitee.com/ko_Link/class-tools-android | Kotlin + Compose；另有 `feat/background-notify` 分支的第二个工作副本 `android-class-tools-notify/`（同一仓库） |
| HarmonyOS | `harmony-class-tools/` | https://github.com/Link0Kong/class-tools-harmony | https://gitee.com/ko_Link/class-tools-harmony | ArkTS + ArkUI，1.0.6 / M79 |
| Windows | `windows-class-tools/` | https://github.com/Link0Kong/class-tools-windows | https://gitee.com/ko_Link/class-tools-windows | WinUI 3 / .NET 10，里程碑开发中 |

- **不要再按功能新建仓库**：新功能落在所属端的仓库里；跨端功能在各端仓库分别提交。
- 原按功能拆的三个仓库已合并（保留完整历史）并归档：
  - `class-tools-briefdesk` → `web/briefdesk/`
  - `class-tools-power` → `web/power/`
  - `class-tools-mp-tests` → `mp-class-tools/tests/`
- 合并方式：`git merge -s ours` + `git read-tree --prefix=…`，旧提交历史在新仓库里可查（`git log -- briefdesk/`）。
- GitHub 已 `gh repo archive`；Gitee 需在网页「仓库设置 → 归档」手动归档同名仓库。

## 二、本地兼容层（junction）

历史脚本（如 `C:\briefdesk\scripts\detect_docs.py`、`fetch_qq_files.py`、测试与文档）写死了旧绝对路径，
旧路径保留 Windows 目录 junction，内容只有一份（都在仓库里），不存在副本漂移：

```text
~\workspace\briefdesk-plan          → ~\workspace\web\briefdesk
~\workspace\perfect-campus-power    → ~\workspace\web\power
~\workspace\mp-class-tools-tests    → ~\workspace\mp-class-tools\tests
```

- 旧 `.git` 已移到 `~\workspace\_repo_git_archive\`，确认无碍后可删。
- 从其他机器 clone 仓库时没有 junction；新脚本请直接用仓库内相对路径。
- 查看：`Get-Item <旧路径> | Select-Object LinkType,Target`。

## 三、同步命令（五个端都一样）

```cmd
cd /d C:\Users\Ko_Li\.openclaw\workspace\<仓库目录>
sync-repos.cmd "feat: 说明本次改了什么"
```

- 每个端仓库根都有一份同一内容的 `sync_repos.py` + `sync-repos.cmd`：安全检查 → 提交 → 推两端 → 核对 SHA。
- 核对：`sync-repos.cmd --check`（本地与两个远端 SHA 三行一致）。
- 手动 `git add -A` + 分两次 `git push` 的旧做法不再需要；**不要只推一个远端**。
- **不设计划任务、不跑后台守护**：agent 改完必须主动执行上面命令（用户 2026-11-18 要求）。

## 四、不入库

- 站点：`deploy/creds.env`、`tools/cert/`、`*.pem` / `*.key` / `*.env`、线上备份 `tools/_backup/`。
- 小程序：`1.keystore`、`project.private.config.json`、`node_modules/`、`tests/` 运行产物。
- 鸿蒙：签名材料（`*.p12` / `*.cer` / `*.p7b`）、`build/`、`oh_modules/`、`.hvigor/`。
- 安卓：`key/`、`keystore.properties`、`app/oppo.properties`、`build/`。
- Windows：`bin/`、`obj/`、`artifacts/`。
- 通知管线 / 电费：`src/config.json`、电量快照、SQLite 台账、日志（各自 `.gitignore` 已排除）。

## 五、回滚

- 合并提交：`web` 历史里的 `chore: 并入通知管线 …`、`chore: 并入电费工具包 …`，小程序仓的 `chore: 并入小程序测试仓库 …`；
  需要撤销时 `git revert -m 1 <sha>`，再把目录移回、恢复旧仓库即可。
- 旧仓库归档后仍可 `gh repo unarchive` 恢复。
