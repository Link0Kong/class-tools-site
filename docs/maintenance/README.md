# 五端维护入口

| 业务 | 先读契约与生产位置 | 消费端及验证入口 |
|---|---|---|
| 分组、抽签 | [分组协议](../../group/CONTRACT.md) · [普通抽签回执](../../draw/CONTRACT.md) | 五端。Web 执行 `python tools/tests/group_check.py`，Windows 查看 `tests/ClassTools.Tests/GroupTests.cs` |
| 文件、课件 | [同账号文件](../../drop/CONTRACT.md) · [班级 PPT](../../ppt/CONTRACT.md) | Web、Android、鸿蒙、Windows 的文件传输页；转换由 Windows Office 工作机执行，两种归属分别验收 |
| 个人设置与任务 | [设置共同夹具](../../contracts/userdata/README.md) · [任务数据与写入约定](../TASKDATA_SYNC_CONTRACT.md) | 各端自己的合并器。MP 从 `tests/sync_contract_test.js` 进入；Windows 见 `tests/ClassTools.Tests/UserDataMergeTests.cs` |
| 学期课表 | [课表同步源](../../jwxt/README.md) · [静态上传器](../../deploy/sync_tools.py) | `jwxt/sync.py` 产出 `tools/tt.json`，`jwxt/tt_cloud.py` 写云快照；五端校验公共课表、个人覆盖与显式清空 |
| 通知、作业 | [通知生产及消费说明](../../briefdesk/README.md) · [附件契约](../../attachments/CONTRACT.md) | 本机工作区 `briefdesk/scripts/detect_docs.py`、`sync_notices_cloud.py`、`hw_auto/run_hw_auto.py` 发布；Web 与客户端按角色回读正文，虚构输入运行 `briefdesk/scripts/tests/test_auto_publish.py` |
| 房间及共享读数 | [共享表维护](../../deploy/cloudbase/README.md) · [读数、电费源](../../power/README.md) | 区分班级共享 water/water_room、个人旧缓存和显式待提交操作；用同房间两个测试身份验证 |
| 客户端交付 | [Android 版本入口](https://github.com/Link0Kong/class-tools-android/blob/master/app/build.gradle.kts) · [鸿蒙测试脚本](https://github.com/Link0Kong/class-tools-harmony/blob/master/scripts/test.ps1) | Android 先单测，核 APK 元数据、签名并核对渠道；鸿蒙在本仓运行 `scripts/test.ps1` 和 `scripts/build.ps1 -Signed`，核对 HAP |

## 仓库与本机工作区

单仓检出可从 [Android](https://github.com/Link0Kong/class-tools-android)、[HarmonyOS](https://github.com/Link0Kong/class-tools-harmony)、[微信小程序](https://github.com/Link0Kong/class-tools-mp)、[Windows](https://github.com/Link0Kong/class-tools-windows) 按表中仓内路径定位。常用并列目录是 `android-class-tools/`、`harmony-class-tools/`、`mp-class-tools/`、`windows-class-tools/`。本机工作区另有 `docs/ARCHITECTURE.md`、`scripts/check-shared.cjs`、`briefdesk/scripts/`。维护者分别保管采集服务代码及离线备份、签名配置与发布包、远端部署前的首页副本。恢复点以当次可读回的文件与摘要为准。采集输入和数据库历史的逐项恢复需运行方核实。交付物位于工作区 `releases/`。

## 提交范围

仅在干净的目标检出或有意使用范围检查时运行 `python deploy/sync_scoped.py -m "fix: 描述具体改动" -- 路径1 "带空格的路径2"`。文件路径相对本仓，重命名列出两端。检查覆盖暂存、未暂存与未跟踪项；遇范围外文件或既有索引锁即非零退出。采用私有暂存区、精确路径与仓内正常的敏感检查、提交、双远端推送和核对。范围外的在途改动应留在原检出，改用独立干净检出交付。普通入口仍为 `sync-repos.cmd "fix: 描述具体改动"`。隔离回归 `python deploy/tests/test_sync_scoped.py` 使用本机两个临时 bare 仓。
