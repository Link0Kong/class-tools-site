# 2026-11-27 网页首页发布回执

首页验收提交为 `46cb237f14a20f2142f4437e1d1fb49de4495571`。Git blob、验收机读入的 LF 文件、OSS 的 `index.html` 与正式域名首页逐字节相同，共 1,757,179 字节，SHA-256 为 `40e7702a4198588144a249d976a69f5e9256370b5c006d2dfa9745f5770c87a1`。

发布前复核了正式域名和 OSS 的旧文件，二者同为 `5204020a3806f5d95b215e07f9f8a10340684bcef4414e6b8d77dc85a94db775`。原首页备份在验收副本的 `tools/_backup/index-before-G03-5204020a3806.html`。上传参数为 `index.html`，ECS 的 `sync-index --expected-sha` 核对新文件后执行原子替换，再由独立 HTTP GET 回读两个地址。

| 验收入口 | 隔离测试结果 |
| --- | --- |
| `tools/tests/identity_sync_check.py`、`visibility_sync_check.py` | 同一登录、同学号换票、同源另一标签换号与登出重登录正常。旧响应不能覆盖新名单或送出已撤回通知的附件。真实页面操作覆盖完整及截断名单、个人标记的多页与断页、权限升降、通知元数据与按需正文、覆盖字段、隐藏和归档。 |
| `tools/tests/userdata_vectors_check.py` | 六个冻结向量全部通过。页面修改昵称后的实际设置请求保留 draw 扩展字段和 prefs，并保持 marks 独立。 |
| `tools/tests/draw_timeline_check.py` | 待存证时剔除、丢失回执后回读、未确认导图、重复导图、新一轮、排序与重置通过，种子复算和哈希一致。 |
| `tools/tests/timetable_refresh_check.py`、`task_cloud_check.py`、`v2_web_batch2_water_cloud_check.py` | 公共课表回退与个人课表互通、条件写冲突及离线恢复、宿舍人数和月读数的新增与删除通过。 |
| `tools/tests/cross_client_sync_check.py` | Web 与小程序在同一个回环服务上互读任务、水表。任务遇到两次条件写冲突后收敛，跨端删除及重开通过。 |
| `drop/tests/conversion_fixture.py --web --office` | 真实 PowerPoint 进程处理两页合成演示稿，另一台浏览器分别回读原件、兼容演示稿和 PDF 并逐字节核对。 |

按交接文档的身份门禁适配，在隔离页面中运行已登录交互和 390、430、1100 三档截图，保留了 16 张受测业务视图，专项检测到 0 个 JavaScript 异常。原有 `overflow_check.py 430` 输出 `overflowCount=0`。原有 `export_check.py draw` 生成 1520 × 996 PNG，共 218,597 字节，图内的参数配置、域名水印、生成时间与编号均已核验。PNG 的 SHA-256 为 `757978e6182c74c150eaf1f58ee2fcead9bff368a2f063df33d4011d0572bd78`。

隔离服务使用合成身份和数据。生产检查只回读静态首页。
