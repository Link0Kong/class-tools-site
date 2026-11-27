# 个人设置 v6 · 共同向量 1

[六组虚构输入与逐字段期望](v1.json) 固定为 `userdata-v6-vectors-1`。基于 MP `e57e73f4a33f` 的 `tests/_sync_fixtures/merge_ref.js`、Web `08c5db083abe`、Android `82edee9a99a3`、HarmonyOS `30771a072031` 和 Windows `02efc2ab44f0` 的实际读取入口整理。样例只进入测试。

按 `merge(remote, local)` 调用。独立 section 采用各自时间戳，平手以远端为先。v5 缺省 draw 迁移出 `names: ""`，旧 v6 存量空对象按同一空映射读取。显式 names 应保留。homeTools 的旧时钟别名供旧读者使用。只对 expect 声明的路径做语义比较，absent 路径必须缺失。section 胜方携带自己的扩展字段；个人 marks 另表管理。未知顶层字段的保留不在这些期望中。

| 输入 | 读取结果 |
|---|---|
| v5-default | v6 读入缺省映射与旧工具顺序、时间和体测，旧读者仍能取 homeToolsAt |
| a-remote / b-remote | 同一对输入交换参数，平手按远端，有新时钟的 section 优先 |
| unstamped | 旧空 draw 可读、缺时间戳的 nick 取远端 |
| section-boundaries | 不拆分胜方 section 内未知内容，独立标记不会进入设置 |
| null-and-newer | 验证缺值与另一 section 的较新真实映射 |

测试语义忽略对象键序，数组顺序仍有意义。**摘要**比较规范字节。UTF-8、递归按对象键排序、无空格、无 BOM、无末尾换行；输入仅字符串、整数、布尔、null、数组、对象。包摘要 `6bbd74410d67d83ef41ab768530b8c2ddd7f12eecd580e472942523ee1b1552c`。每项的输入摘要取有序数组 `[remote,local]`。

`python contracts/userdata/freeze.py` 验包并列出每项摘要，`--out <文件>` 保存规范字节；端内已有夹具继续维护。Web 入口在 `tools/tests`，小程序在 `tests`，Android 执行 `gradlew.bat :app:testDebugUnitTest`，鸿蒙执行 `scripts/test.ps1`，Windows 执行 `dotnet test tests/ClassTools.Tests`。各端完整业务入口与发布路径见[维护索引](../../docs/maintenance/README.md)。回退测试可切回旧向量标签；线上缓存格式保持 v6。
