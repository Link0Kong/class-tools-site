# PPT 演示 v1.2「原样播放」· 独立验收报告（Lead，2026-11-10）

> 用户反馈：网络良好时希望达到电脑本地文件播放效果；此前动画全部消失、视频无法播放、操作不便。
> 本报告只记录**真实命令/真实数据**；mock 单测由各端实现者报告，Lead 负责真实云端/真实浏览器/真实 devtools 端到端。

## 结论：**PASS**（真实链路 4/4 端通过；三端单测全绿；唯一需用户操作项：微信发布 + 域名白名单）

| 项 | 实测 |
|---|---|
| 转换机 | 真实用户 deck 补转：`deck.mp4` 13,668,151 B / 303.60s / 1280×720 / h264+aac / chapters=16；OSS HEAD 200；manifest.video 已写入、slides 16 未动；外链媒体已静态化（消除 +87s） |
| 转换机测试 | `test_pure_logic.py` **97/97**；`test_convert_integration.py` **22/22**（含 16:9 视频+aac、帧级验证 1s 抽帧最大差 5.15、4:3、降级无 video、tuanri 16 页）；`test_cloud_contract.py` **7/7** |
| 网页 | `v2_ppt_check.py` 86/86、`v2_ppt_video_check.py` 99/99、overflow 430=0；**真实 E2E 15/15**：默认原样播放 deck.mp4（303.6s/16 章）、下一章 seek 4.86s→第 2/16 页、刻度跳第 12 页 53.39s、续播到 55s、切分步、第 12 页热点必现、热点打开 m0.mp4、0 JS error |
| 网页部署 | 线上 OSS 对象 847,026 B / sha256 `411354e1997db1cc77bf272f873d38bd409f0668181b2d1ea7a39431906feebc`，`deploy/oss_object.py check index.html` = MATCH |
| 小程序 | `unit.js` 337/0、`ppt_unit_tests.js` 40/0、`ppt_video_unit_tests.js` 30/0、`sync 33/0`、`staticcheck/code_quality` 0、automator 38/0；**真实 deck automator**：默认原样播放、`deck.mp4` 直连起播（vt>2s、vdur 303.601315）、章节下一章、倍速 1.25×、切分步热点=1 |
| 安卓 | `testDebugUnitTest` 954 tests / 0 failures；`assembleRelease` BUILD SUCCESSFUL；APK 2,724,998 B / sha256 `542943B43EE1857EABFE275B6D1C37AF1DFD3FE9DBFF3F06AA7C7947737DCC0D`；预览 7 张（含视频模式控制条/64dp 热点/列表继续徽标） |
| 三端同步 | web 提交 `f3211bb`（本地=GitHub=Gitee）；小程序源码与安卓 APK 走各自交付路径（源码不在 web 仓库） |

## 证据文件

- 网页真实 E2E 证据：Lead CDP 脚本断言 15/15 PASS（脚本：`web/deploy/_e2e_ppt_v12_web.py`，本机过程脚本不入库；截图采集受 headless 多目标影响未作为证据，以断言 + DOM 输出为准）
- 网页专项截图：`web/tools/tests/_shots_ppt_video/`（A1~G1 9 张，模块内 mock 基座，已人工核对）
- 小程序真实截图：`mp-class-tools-tests/_shots_ppt_v12_mp_real.png`；专项 12 张 `_shots_ppt_video/`
- 安卓预览：`android-class-tools/artifacts/ppt-player-video-mode.png`、`ppt-player-steps-hotspot.png`、`ppt-list-states.png` 等 7 张
- 桌面交付：`C:\Users\Ko_Li\OneDrive\桌面\班级工具站_PPT演示_20261109\`（3.4.0 APK、截图_v1.2、更新说明_PPT_v1.2_20261110.md）

## 已知限制/需用户操作

1. **小程序需用户**：微信公众平台 → 开发设置 → 服务器域名，把 `https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com` 加入 **request + downloadFile** 合法域名；再上传发布新版本。发布前 devtools 已验证直连可播、失败链自动回退分步。
2. OSS 默认域名仍带 `x-oss-force-download`/`Content-Disposition: attachment`（阿里云策略，非本项目配置）；网页可播、小程序以 downloadFile 兜底；恢复自定义域名（备案/DNS 恢复后）更稳。
3. 原样播放把单击动画合并为自动节奏；外链媒体（未嵌入源文件的链接视频）无法播放，视频中以海报静态帧代替；章节时间允许 ±1s；>120 页或 >30min 不生成视频。
4. 旧 deck（无 manifest.video）自动走分步，不需要迁移；存量用户 deck 已单独补转。
5. 若回滚网页，注意 `index_online_20261110-2055_prePPTv12.html` 会连同并行会话的大屏入口改动一起回退。
