# v2.0.0 增量验收报告（用户 2026-11-05 20:07 新指示）

> 独立 QA（fresh context）· 2026-11-05 20:15–20:30（Asia/Shanghai）
> 本轮只验增量 + 回归：**① 小程序移除全部「演示/审核模式」+ 云端测试身份；② 网页滑动手感修复（等待最终字节/部署后复跑）**。
> 结论：**小程序「移除审核模式 + 测试身份」PASS（源码可交付）；网页「滑动手感修复」PASS（已上线，可交付）**。
> 报告不写任何明文凭据；云端只读 + 可还原。

## 1. 小程序：移除「演示/审核模式」

### 1.1 源码清理核验（独立扫描，非开发者自述）

| 检查 | 结果 | 证据 |
|---|---|---|
| `utils/demo.js` / `utils/demo-data.js` | **不存在** ✅ | 文件存在性断言（`mp_v2_check`/`static_scan`） |
| 身份页 / 「我的」页「演示模式/审核用」入口与文案 | **0 处** ✅ | `identity.wxml/js`、`me.wxml/js` 扫描 0 命中 |
| cloud / store / notify 的 demo 拦截、演示桶（DEMO_KEY）、demo 数据引用 | **0 处** ✅ | `utils/cloud.js`、`utils/store.js`、`utils/notify.js` 扫描 0 命中 |
| 全源码（js/wxml/wxss/json）「演示同学/演示模式/审核用/demo-data」 | **0 处** ✅ | 递归扫描（排除 node_modules/cloudfunctions/images/_backup） |
| README / CHANGELOG | 已清理实现说明，并写明「不实现审核模式」/「移除审核模式」✅ | 文档扫描 |
| AI 开发模式 | **off**：`ai_toggle.py --status` → 「AI 分包: 未启用 / agent: 未启用」；`ai/` 源码保留（8 SKILL OK）✅ | 命令输出 |

### 1.2 QA 脚手架同步更新（原「演示模式」期望 → 「不存在」断言）

- `static_scan.py`：5 条 demo 期望改为 **7 条移除断言**（文件不存在 / 身份页无入口 / 网络层无拦截 / 我的页无文案 / README·CHANGELOG 已清理 / 源码无演示数据 / 隐私扫描无 demo 文案）。扫描项 47→**49 项**。
- `mp_v2_check.js`：5 条 demo 行为测试改为 **5 条「已移除」断言**（文件、身份页、网络层、我的页+文档、全源码无残留）。仍为 **47 项**。
- `README.md` / `FINAL_CHECKLIST.md`：需求 10 行改为「审核/演示模式已按用户指示移除 → 断言不存在」。

### 1.3 回归测试结果（全绿）

| 套件 | 命令 | 结果 |
|---|---|---|
| 既有单测 | `node unit.js` | **147 passed / 0 failed** ✅（152→147：删除 5 条 demo 用例，与 Lead 预期一致） |
| 同步契约 | `node sync_contract_test.js` | **29 passed / 0 failed** ✅ |
| 静态审计 | `python staticcheck.py` | exit 0（handlers missing []）✅ |
| 独立验收 | `node mp_v2_check.js --tag incremental` | **47 项：PASS 47 / FAIL 0 / PEND 1**（信息走查）✅ |
| 合规/隐私扫描 | `python static_scan.py --tag incremental` | **49 项：PASS 48 / FAIL 0 / PEND 1**（包体信息）✅ |
| 性能缓存 | `node cache_perf_test.js` | **16 passed / 0 failed** ✅ |
| 编译 | `cli.bat auto-preview --project mp-class-tools --auto-port 9420` | **exit 0**（QA 独立复跑）✅ |
| 包体 | `_compile_info_off.json` | **TOTAL 667,382 B 单主包**（与 Lead 提供一致）✅ |
| 版本 | `utils/version.js` | **2.0.0**（app.js/我的页/README/CHANGELOG 一致）✅ |
| automator 真触摸 | `MP_AUTO_ALLOW=1 node automator_optional.js` | **SKIP**：开发者工具会话在本次运行时 busy/关闭（上次终验已 4/4 PASS；本轮改动不涉及课表滑动逻辑） |

证据：`_reports/mp_v2_incremental.json`、`_reports/mp_static_incremental.json`、`_reports/existing_mp_incremental.json`、`/mp-class-tools-tests/_compile_info_off.json`。

## 2. 云端测试身份（只读核验，报告不写明文凭据）

> 表述：「测试身份已配置（is_test，服务端 class_members 过滤）」。学号在下方遮码显示。

| 检查 | 结果 | 证据 |
|---|---|---|
| `rpc/class_verify` 可登录 | **PASS** ✅ | status=200、ok=true、返回身份字段（token 未打印/未入报告） |
| 测试身份为普通身份（非管理员） | **PASS** ✅ | `is_admin=false` |
| 测试 token 拉 `class_members` | **PASS** ✅ | status=200、**70 人** |
| 测试身份**不在**班级名单中 | **PASS** ✅ | `sid_in_list=False / name_in_list=False`（遮码：`32607*****`） |
| 管理员账号名单不受影响 | **PASS** ✅ | status=200、**70 人**、不含测试身份 |
| 测试身份可只读访问班级数据 | **PASS** ✅ | `GET notices` status=200（可登录且可用） |

- 7/7 PASS；证据 `_reports/cloud_test_account_incremental.json`（web `_qa_v2/_reports/`）。
- 写操作：仅 `class_verify` 服务端会话记录（登录机制本身），**未写任何业务表**。

## 3. 网页：滑动手感修复（已完成，详见 `web/tools/tests/_qa_v2/REPORT_INCREMENTAL.md`）

- 最终线上字节：**449,446 B · sha256 `701fd0f8cd31af4be5b6a86f909e09c24f01e8ee74904dc073e06fef8fba3668`**，本地==线上逐字节 MATCH。
- `qa_web --tag final2`：**79 项 PASS 76 / FAIL 0 / PEND 3**（需求 1/2/4/5/6/7/8/9/12/13/14/15/16 全量回归）。
- 既有 7 门禁：**7/7 PASS**（roster/reset/perf/sync/committee/overflow/export）。
- `qa_online`：线上==本地 MATCH、版本 2.0.0、**0 console error / 0 外部请求**、通知区域父页滚动 4198px。
- **`v2_swipe_perf.py` 独立复跑 PASS**：reactionRate baseline/prefix/fixed = **1/0/1**；syncErrP50 = **0/20/0px**；
  posWritesDuringScroll = **0/10/0**、停止后 1 次；frameP95 28.10/28.60/28.30ms、longFrames 1/1/1
  → 手感与 pre-v2 baseline 对齐，需求 2 保位落盘行为保留。
- `v2_scroll_check.py`：**35/35 PASS**（需求 2/4/5 专项，含 iframe 自适应父页滚动、iframe 上滑切工具、刷新保位 2000px、弹层锁审计、桌面/reduced-motion、0 报错）。
- 需求 2/4/5/12/13/16 逐项无回归（见 web 增量报告 §5）。

## 4. 结论

- **小程序「移除审核模式 + 测试身份」：PASS**；源码可交付（上传发布前事项同原报告 §6：AI off 保持、域名/隐私指引/真机复核）。
- **网页「滑动手感修复」：PASS**（指标逐项对齐 pre-v2 baseline 且保留 v2 保位；全量回归 0 FAIL）；网页端仍可交付。
- 无阻塞缺陷需返工；本轮未改产品代码、未部署、云端未写业务数据。
