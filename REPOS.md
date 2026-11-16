# 班级工具站 · 仓库地图

> 2026-11-16 全量核对：站点与各客户端源码均为**私有仓库**，GitHub + Gitee 双远端。仓库含个人信息、服务器配置，**不要改为公开**。
> 分支统一 `master`（Android 另有 `feat/background-notify` 分支保存后台通知改动）。

| 项目 | 本地目录 | GitHub（origin） | Gitee（gitee） | 说明 |
|---|---|---|---|---|
| 站点 + 部署 + 测试 | `web/` | https://github.com/Link0Kong/class-tools-site | https://gitee.com/ko_Link/class-tools-site | 单文件站点 `tools/index.html`、`deploy/`、`tools/tests/`、文档 |
| 微信小程序 | `mp-class-tools/` | https://github.com/Link0Kong/class-tools-mp | https://gitee.com/ko_Link/class-tools-mp | 原生小程序 v25 / 2.0.0，30 页 |
| 小程序测试 | `mp-class-tools-tests/` | https://github.com/Link0Kong/class-tools-mp-tests | https://gitee.com/ko_Link/class-tools-mp-tests | unit / staticcheck / code_quality / automator |
| Android | `android-class-tools/` | https://github.com/Link0Kong/class-tools-android | https://gitee.com/ko_Link/class-tools-android | Kotlin + Compose；`master` + `feat/background-notify` |
| HarmonyOS | `harmony-class-tools/` | https://github.com/Link0Kong/class-tools-harmony | https://gitee.com/ko_Link/class-tools-harmony | ArkTS + ArkUI，1.0.6 / M79 |
| Windows | `windows-class-tools/` | https://github.com/Link0Kong/class-tools-windows | https://gitee.com/ko_Link/class-tools-windows | WinUI 3 / .NET 10，里程碑开发中 |
| 通知管线 | `briefdesk-plan/` | https://github.com/Link0Kong/class-tools-briefdesk | https://gitee.com/ko_Link/class-tools-briefdesk | 通知页模板生成 / 校验 / 方案 |
| 电费工具包 | `perfect-campus-power/` | https://github.com/Link0Kong/class-tools-power | https://gitee.com/ko_Link/class-tools-power | 完美校园电费研究与本机采集工具包 |

## 同步命令

站点（含本文件）：

```cmd
cd /d C:\Users\Ko_Li\.openclaw\workspace\web
sync-repos.cmd "docs: 说明本次改了什么"
```

其他仓库（已配置 `origin` / `gitee` 两个远端）：

```powershell
cd C:\Users\Ko_Li\.openclaw\workspace\<项目目录>
git add -A
git commit -m "feat: 说明本次改了什么"
git push origin master
git push gitee master
```

## 核对

```powershell
# 任一仓库：本地与两端 HEAD 应一致
git rev-parse HEAD
git ls-remote origin refs/heads/master
git ls-remote gitee refs/heads/master
```

## 不入库

- 站点：`deploy/creds.env`、`tools/cert/`、`*.pem` / `*.key` / `*.env`、线上备份 `tools/_backup/`。
- 小程序：`1.keystore`、`project.private.config.json`。
- 鸿蒙：签名材料（`*.p12` / `*.cer` / `*.p7b`）、`build/`、`oh_modules/`、`.hvigor/`。
- 安卓：`key/`、`keystore.properties`、`app/oppo.properties`、`build/`。
- Windows：`bin/`、`obj/`、`artifacts/`。
- 电费：`src/config.json`、电量快照、SQLite 台账、日志。
