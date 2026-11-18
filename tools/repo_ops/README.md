# repo_ops — 五端仓库的自动提交守护

2026-11-18 用户要求：五个端各一个仓库（不按功能拆），每个端都要能自动提交。

## 文件

| 文件 | 作用 |
|---|---|
| `auto_commit_all.py` | 扫描五个端仓库：有改动且空闲 ≥5 分钟 → 调该仓库根的 `sync_repos.py --auto`（提交 + 推 GitHub/Gitee + 核对 SHA） |
| `_logs/auto_commit.log` | 运行日志（本机，`.gitignore` 已排除） |

五个端仓库根目录各有一份同一内容的 `sync_repos.py` + `sync-repos.cmd`；
`web/sync_repos.py` 是维护用的母本，改动后复制到其余四个端（保持五份一致）。

## 手动使用

```cmd
python web\tools\repo_ops\auto_commit_all.py --dry-run        # 只看会提交什么
python web\tools\repo_ops\auto_commit_all.py                  # 跑一轮
python web\tools\repo_ops\auto_commit_all.py --repo 网页端    # 只跑一个端
```

## 计划任务

任务名：`ClassToolsRepoAutoSync`（每 10 分钟 + 登录后 1 分钟，`pythonw.exe` 无窗口）。

```cmd
schtasks /Query /TN ClassToolsRepoAutoSync /V /FO LIST
schtasks /Change /TN ClassToolsRepoAutoSync /DISABLE   & rem 暂停
schtasks /Change /TN ClassToolsRepoAutoSync /ENABLE    & rem 恢复
schtasks /Delete /TN ClassToolsRepoAutoSync /F         & rem 删除
```

重新注册（若任务被删）：

```powershell
schtasks /Create /TN ClassToolsRepoAutoSync /SC MINUTE /MO 10 /RL LIMITED /F ^
  /TR "\"C:\Users\Ko_Li\AppData\Local\Programs\Python\Python312\pythonw.exe\" \"C:\Users\Ko_Li\.openclaw\workspace\web\tools\repo_ops\auto_commit_all.py\""
```

（Windows 计划任务 `schtasks /SC MINUTE` 只支持“登录时运行”；如需开机补跑/多实例保护，
用 `Get-ScheduledTask` 导入 XML，当前机器上的任务已带 `StartWhenAvailable` 与 `IgnoreNew`。）

## 规则与安全

- 工作区干净 → 跳过（不产生空提交）。
- 最近 5 分钟仍有写入 → 等下一轮（避免提交写一半的文件）。
- 有 `MERGE_HEAD` / `rebase-merge` / `rebase-apply` / `CHERRY_PICK_HEAD` / `index.lock` → 跳过。
- 单实例锁：`_logs/auto_commit.lock`（30 分钟视为过期）。
- 提交前仍走 `sync_repos.py` 的安全检查：证书 / `creds.env` / 令牌 / 私钥 / 大文件一律中止。
- 超时：单仓库 15 分钟；网络失败只记录，不阻塞其他端。

## 关掉自动提交

```cmd
schtasks /Change /TN ClassToolsRepoAutoSync /DISABLE
```

agent 仍应在完成改动时主动执行 `sync-repos.cmd "feat: 说明"`。
