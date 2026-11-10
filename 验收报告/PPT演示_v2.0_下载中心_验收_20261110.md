# PPT 兼容处理与多端下载 v2.0 · 验收报告（Lead，2026-11-10）

> 用户 2026-11-10 22:05：「重新定义该功能，不再已在线播放为主要功能，而是以上传ppt，自动对内容进行兼容性处理，并提供多端下载的方式，不改变ppt本身质量」。
> 本报告记录**真实云端/真实 OSS/真实浏览器/真实转换机**证据；各端 mock 单测由实现者报告，Lead 做真实端到端。

## 结论：**PASS**（转换机真实补转 + 网页真实 E2E 16/16 + 质量强断言 24/24；三端单测全绿；需用户操作：小程序域名+发布、安装 3.5.0 APK）

| 项 | 实测结果 |
|---|---|
| 转换机默认流程 | `agent.py --once` 默认走 compat（`--legacy` 保留旧链路）；进度 10/30/55/75/85/95；失败中文 error |
| 转换机测试 | `test_pure_logic.py` **123/123**；`test_compat_integration.py` **19/19**；`test_convert_integration.py` **22/22**；`test_cloud_contract.py` **7/7** |
| 真实用户 deck 补转 | `dmwalrdlgevz90l`：compat.pptx 39,068,049B/sha256 `20de7b37…`/16 页；preview.pdf 1,105,861B/sha256 `bb2f1121…`/16 页；original.pptx 38,016,533B（=源）；cover 25,174B；字体 6；外链告警 1（第 7 页）；compat 4.5s |
| **不降质强断言** | 真实云端下载后校验：compat 内 `ppt/media/*` sha256 与源包 **15/15 逐字节一致（0 重编码，missing=[]）**；compat 可被 python-pptx 打开且页数=16；PDF `%PDF-1.7` 页数=16；三件套 size/sha256 与 manifest 一致 → `_qa_ppt_compat.py` **24/24 PASS** |
| 网页 | `v2_ppt_download_check.py` 41/41、`v2_ppt_check.py` 92/92、`v2_ppt_video_check.py` 100/100、overflow 430=0；**真实云端 E2E 16/16**：列表卡片「兼容版/PDF」标签无播放按钮、点击=下载详情、三行下载 href=OSS base+文件/文件名/大小、兼容提示、0 JS error |
| 网页部署 | 线上对象 **870,349 B / sha256 `ea799a2892809b4e08b6dffe59f7aaddff99066f11b50147381534ee28771dc3`**，`deploy/oss_object.py check index.html` = MATCH |
| 小程序 | `unit.js` 363/0、`ppt_dl_unit_tests.js` 26/0、`ppt_unit 40/0`、`ppt_video 30/0`、`sync 33/0`、staticcheck/code_quality 0；automator `ppt_dl_preview.js` **27/0**（真实旧 deck 详情/在线预览 + 注入 v2 三行下载/openDocument/shareFileMessage 链） |
| 安卓 | `testDebugUnitTest` **982 tests / 0 failures**（新增 28，原 954 无回退）；`assembleRelease` 成功；APK **2,741,438 B / sha256 `C45070ACB6C91745F27DD28D5C28075B64688999A50B1F4DFB5D92406B947647`**（3.5.0/vc11） |
| 提交 | web 提交（本地=GitHub=Gitee，见最终答复 SHA） |

## 质量与内容保护说明

- **兼容版不减质**：不做图片/视频重编码、不降分辨率、不删动画/切换/备注/母版；只做 PowerPoint 原生另存（包规范化+嵌入字体）与 `.ppt→.pptx`；媒体字节逐字节一致已实测。
- **外链媒体**：PPT 内「链接到文件」的视频源不在 PPT 包内，无法随文件携带；详情橙色提示页号，需用户改为「嵌入」后重新上传（不删除、不谎报）。
- **PDF**：Visual 版式保持不变（非动画），用于无 Office 设备的查看。
- **在线播放**：降为旧 deck 的「在线预览」次入口，不再是主流程。

## 证据文件

- 转换机测试：`web/ppt/tests/test_compat_integration.py`（19 项，真实 PowerPoint）
- 网页截图：`web/tools/tests/_shots_ppt_download/`（A0 列表标签/A1 详情/B1 旧 deck/C1 失败）
- 小程序截图：`mp-class-tools-tests/_shots_ppt_dl/`（7 张，含 v2 详情/旧 deck/下载进度）
- 安卓预览：`android-class-tools/artifacts/ppt-download-detail.png`、`ppt-download-warnings.png`、`ppt-download-legacy.png`、`ppt-list-states.png`
- 桌面交付：`C:\Users\Ko_Li\OneDrive\桌面\班级工具站_PPT演示_20261109\`（`班级工具站_3.5.0.apk`、`更新说明_PPT_v2.0_20261110.md`、`截图_v2.0\`）

## 已知限制 / 需用户操作

1. **小程序**：微信后台 → 服务器域名：把 `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com` 加入 **request + downloadFile** 合法域名；上传发布新版本后用真机下载一份兼容包并 `openDocument` 验证。
2. **安卓**：安装 3.5.0；下载保存于应用外部下载目录（系统通知可见，可直接打开/分享），因不申请存储权限，不写公共 Downloads。
3. 兼容包体积 ≈ 原文件 + 字体（本例 36.3MB→37.3MB）；建议 Wi-Fi 下载。小程序/安卓打开依赖设备已装 PowerPoint/WPS/PDF 查看器。
4. 旧 deck 需点「重新处理」补 compat；原有「在线预览」仍可用。当前用户 deck 已补好。
5. 兼容版与原始文件当前建议文件名相同（浏览器会自动重命名），后续可在转换机为兼容版加 `_兼容版` 后缀。
