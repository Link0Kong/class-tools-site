# 同步说明（给 DSH / 任何接手的人）

本仓库是「班级工具站」的完整归档：单文件站点 `tools/index.html`、部署脚本 `deploy/`、测试 `tools/tests/`、文档与历史说明。

- GitHub（主）：https://github.com/Link0Kong/class-tools-site  —— remote 名 `origin`
- Gitee（镜像）：见下方 remote 名 `gitee`

## 每次改完，只跑这一条

```cmd
C:\Users\Ko_Li\.openclaw\workspace\web\sync-repos.cmd "本次改动一句话说明"
```

它会依次执行：`git add -A` → `git commit`（带说明）→ 推送 GitHub → 推送 Gitee。任何一步失败都会停下并报错。

## 等价的手工命令（想自己控制时）

```cmd
cd C:\Users\Ko_Li\.openclaw\workspace\web
git add -A
git commit -m "feat: 通知页新增已过期折叠"
git push origin master
git push gitee master
```

## 三条铁律

1. **不要提交证书与凭据**：`tools/cert/`、`deploy/creds.env`、`deploy/acme_account_key.pem`、任何 `*.key` / `*.pem` / `*.env` 都已在 `.gitignore` 里排除。想确认有没有漏：`git status --porcelain | findstr /i "pem key env creds"`，有输出就停下。
2. **不要提交过程产物**：`tools/_backup/`（57 MB 快照）、`tools/tests/frozen/`、`ppt/work/`、`*.pptx`、截图与日志都已排除。要留证据请放 `tools/tests/` 下的 `.py` 或 `.md`。
3. **每次提交都要写说明**，别用 `update`、`fix` 这种。中文可以，但别带 emoji（Gitee 的提交列表会乱码）。

## 仓库结构

```
web/
├── tools/                 # 站点本体
│   ├── index.html         # 单文件主程序（约 715 KB）
│   ├── notice-board-live-demo.html
│   ├── tests/             # 自建验收套件（.py / .md 入库，产物不入库）
│   └── README.md
├── deploy/                # 部署脚本（凭据文件已排除）
├── jwxt/  ziqi/  ppt/     # 辅助页面与素材
├── _compliance/  _audit/ 验收报告/
├── HANDOFF.md  CHANGELOG.md  CLOUDBASE.md  AGENTS.md
└── SYNC.md                # 本文件
```

## 出问题怎么办

| 现象 | 处理 |
|---|---|
| `push` 被拒（non-fast-forward） | `git pull --rebase origin master` 后再推；冲突就手工合并 |
| Gitee 提示认证失败 | 令牌过期。去 gitee.com → 设置 → 私人令牌 重新生成，然后 `git remote set-url gitee https://<用户名>:<新令牌>@gitee.com/<用户名>/class-tools-site.git` |
| 中文文件名显示成 `\346\226\207` | `git config core.quotepath false` |
| 提交里混进了大文件 | `git rm --cached <file>` 后补进 `.gitignore`，再提交 |

## 版本约定

- 分支：`master`（两边同名，别用 main，省得每次都要指定）
- 提交前缀：`feat:` 新功能 / `fix:` 修 bug / `docs:` 文档 / `chore:` 杂务 / `test:` 测试
- 每次推完两边，`git log --oneline -3` 看一眼，确认 HEAD 一致