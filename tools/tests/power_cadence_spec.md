# 电费「13/16 号楼日更」特异性统计优化 · 规格（v1，2026-11-07）

> 目标（用户原话）：「对 16 号楼和 13 号楼的电量统计做特异性功能优化，避免因统计频次的不同导致观感不佳和功能失效」。
> 本规格是网页（`web/tools/index.html` 的 `POWER` 模块）与小程序（`mp-class-tools/utils/power.js` + `pages/power/*`）**共同实现口径**；
> 验收测试（`tools/tests/v2_power_cadence_check.py`、`tools/tests/_power_cadence_qa/`）与 mp 单测均按本规格断言。

---

## 0. 真实数据依据（2026-11-07 22:01 探测，只读）

数据源：CloudBase `public.power_history`（30 天保留），`tools/tests/_power_freq/probe.py` / `eval_current.py` 产出 `freq_probe.json` / `eval.json`。

| 楼栋 | 47h 内真实数值变化次数 | 变化间隔 | 结论 |
|---|---|---|---|
| 13号楼（324/308）、16号楼（305/306） | 各 **1 次**（均为 2026-11-06 09:46 同批） | — | 网关**日更/批量更**（周末 11-07 全天无变化） |
| 23号楼A座 / B座（抽样 4 间） | 各 **45–46 次** | 中位 1.0h | 网关**准实时（每小时）** |

现状症状（真实数据复算，`eval_current.py`）：

1. **功能失效**：13号楼324 剩余 67.72 度、上次真实下降 11.25 度（≈1 天用量），页面「估算可用」却显示 **≥30 天**（24h 窗口无变化 → rate=0 被下限 0.05 兜底 / 7d 窗口把 47h 摊平）；16号楼305/306、13号楼308 同样显示 ≥30 天。
2. **观感不佳**：近 24h 趋势是一条水平直线；「近 24h 用电」tile 显示「—」；页面「更新 22:01」其实是同步时间，数值自 11-06 09:46 起未变（误导）；旧「数据更新较慢 · 上次变化…」长徽标只提示不修复。
3. 对照：23A/B 每小时都有真实变化，现有 24h/7d 双窗口估算工作正常，**不应改变**其口径与观感。

**产品判断**：13/16 号楼属于「按更新点统计」的慢频数据；页面应**按真实更新点**（change points）计算可用天数/日用量，更新与无更新状态要如实展示；23A/B 保持现状。
另加一条**通用有效性守卫**：窗口内真实用电量为 0 时不再用 0.05 度/天的下限伪造「≥30 天」，改为「数据积累中」（慢更新房与正常房同规则，避免同类失效）。

---

## 1. 常量与纯函数口径（web / mp 必须一致）

```
CH          = 0.005      // 数值变化阈值（与现有 slowInfo 一致）
MIN_SEG_H   = 6          // 有效用电段最短 6 小时（过滤同批抖动/短时修正）
EXPECT_H    = 24         // 13/16 号楼预期更新周期（小时）；仅用于「只有 1 段观测」时折算
SLOW_BLD    = ["13号楼","16号楼"]   // 楼栋级慢频配置（产品知识；23A/23B 不在内）
```

### 1.1 `events(pts30)`
- `pts30`：该房近 30 天真实采样（`normalizeHistory` 后按 t 升序）。
- 从 `pts30[0]` 开始，保留「与上一个保留点的 |Δq| > CH」的点。→ 得到真实**变化点**序列 `events`（首点为起点，不要求变化）。
- `lastChange = events[last].t`（任何方向变化，含充值；30 天内无变化 → null）。
- `lastRecharge = 最后一个「q 上升（prev.q - cur.q < -0.05）」事件`，记 `{t, reset: events[i].q}`（30 天内无 → null）。
- `changesIn(pts)`：窗口内 |相邻 Δq| > CH 的次数（用于 24h 覆盖判定与无更新提示）。

### 1.2 `slowStats(pts30, rowQ)`
对相邻变化点 `i-1 → i`：
- `dq = events[i-1].q - events[i].q`（>0 为用电）；`dtH = (events[i].t - events[i-1].t)/3600000`。
- `dq > 0.05 && dtH >= MIN_SEG_H` → 候选用电段 `{drop:dq, hours:dtH}`；`dq < -0.05` → 充值/修正，跳过（不进段）。
- **异常扣减剔除**：候选段 drop 中位数 `base`（仅 1 段时 base=该段）；`thr = max(5, 4*base)`；`drop > thr` 的段剔除（水费从电费账户扣/异常大跌），不计入 rate。
  - 与现有 `deductOf(pts)` 保持同一思路；web 端可复用 `POWER.deductOf` 的异常时间集合做二次排除（可选），mp 端用中位数阈值即可（mp 无水量匹配，允许该差异，测试按阈值口径）。
- **rate（度/天）**：
  - 有效段 0 段 → `valid=false`；
  - 1 段：`dtH < EXPECT_H*1.5` → `rate = drop/EXPECT_H*24`（视为「1 个预期更新周期」的用量，**ref=true**）；否则 `rate = drop/dtH*24`（按观测间隔，ref=true）；
  - ≥2 段：`rate = Σdrop / ΣdtH * 24`（按时间加权），**ref=false**。
- `days = rowQ / rate`；`valid = rate>0 && isFinite && rowQ!=null`。
- 返回（web 端字段名，mp 同名）：`{valid, rate, days, ref, nSeg, events, changes, lastChange, lastRecharge}`。
- 展示：`days` 仍按现有规则 `daysMain / daysText`（≥30 显示「≥30 天」，上限 999）；ring 弧 = `max(0.02, min(1, days/30))`；无效时沿用现有空态（「数据积累中」/小弧 0.04）。

### 1.3 慢频判定 `isSlowRoom(rv)`
1. `building = PW_ROOMS[rv].building`；不在 `SLOW_BLD` → false。
2. **数据覆盖**：当前 24h 缓存存在且 `changesIn(pts24) >= 6` → true 的屋也按实时口径（未来网关提速自动降级为实时，避免慢口径把高频变化误当噪声）。
3. 其余 → true。
（web 暴露 `POWER.isSlowRoom(rv)`；mp `power.isSlowBuilding(building)` + 页面用 24h 缓存判断覆盖。）

### 1.4 实时房 `estimate()` 通用守卫（所有非慢频房）
保留现有 24h/7d 双窗口分段统计与 0.65/0.35 混合，但有效性增加：
- `v24 = (n>=2 && span>=6 && rate 有限 && r24.used > 0.05)`；
- `v7` 同理（`r7.used > 0.05`）；
- 两档都无效 → `valid=false`（显示「数据积累中」），**不再**用 `rate=max(0,0.05)` 伪造天数；
- 有效时才应用 `rate = max(rate, 0.05)` 下限。
（影响：23B-422 这类「24h/7d 均无真实下降」的房从「≥30 天」变为「数据积累中」——这是修复，不是回归。）

### 1.5 估算选择
`estimate(rv)`：
- `isSlowRoom(rv)` → `slowStats(pts30, row.q)`（30d 缓存；未加载完 → valid=false）；
- 否则 → 实时口径（1.4）。
返回对象保持现有键（`valid/rate/days/q`），慢频额外带 `slow/ref/nSeg/changes/lastChange/lastRecharge`。

---

## 2. 取数契约（web / mp）

- 关注宿舍选择/同步/UD v6 契约**不变**；未选择时 0 请求不变。
- `pull()`（刷新/选择）历史窗口：
  - 慢频房：`["24h","7d","30d"]`（与当前选中区间去重）→ 选择后 **3 个 power_history 请求**；
  - 实时房：现有 `["24h","7d"]` + 选中区间（去重）→ **2 个**（切 30d 时 3 个）。
- `loadHist(range)`（切档位）：慢频房 = 选中区间 + `30d`（去重；24h 缓存 pull 已有则不重复）；实时房维持现有（非 24h 时补 24h）。
- 30d 请求：`power_history?select=ts,quantity&roomverify=eq.<rv>&ts=gte.<30天前ISO>&order=ts.asc&limit=2000`；缓存 TTL 5 分钟（与现有各档一致）；**不插值、不改采样、不改表结构**。
- 30 天保留量估算：当前双源采样 ~30–45min/条 → 960–1440 条 < 2000，安全；若未来采样加密需再评估。

---

## 3. Web UI 变更（`tools/index.html`，`POWER` 模块 + 电费 CSS/DOM）

只改电费页；其它工具、导出、同步、返回键、拖动等一律不动；`APP_VER` 保持 `2.0.0`。

| 位置 | 实时房（23A/B，保持现状） | 慢频房（13/16） |
|---|---|---|
| 趋势头 `#pwSlow` | 现有数据驱动慢更新文案（24h 变化≤2 时） | 固定短徽标 **「日更」**（`title="13/16 号楼网关日更，按真实更新点统计"`），始终显示 |
| hero 更新时间 `#pwUpd` | `更新 <row.updated_at>` | `更新 <lastChange 本地 MM-DD HH:MM>`；30 天内无变化 → `近 30 天无变化` |
| tile1 估算可用 | 现状 | 慢统计 days/rate；`参考` 徽标仅在 `slow && valid && ref` 时显示（多段不再标参考）；无效仍「—/数据积累中」 |
| tile2 区间用电 | 现状（label=区间名，value=区间下降，sub=电费） | 同左；该区间无下降时 sub 显示 **「该区间无更新」** |
| tile3 低电阈值 | 现状 | 现状 |
| tile4 上次充值 | 现状（区间 lastUp） | 用 30d `lastRecharge`（值=reset，时间=变化点），24h/7d/30d 切档不变 |
| 趋势曲线 | 现状（折线） | **阶梯线**（先水平后垂直，H/V 路径）+ 真实变化点小圆点 `.pw-cdot`（≤60 个）；图例/充值/扣减徽标不变 |
| 趋势空/平态 | hi-lo<0.005 时线段**垂直居中**（全房通用，避免贴底） | 同左；另：所选区间内 `changesIn==0` 时叠加提示 **「近 24h 无更新 / 近 7 天无更新 / 近 30 天无更新」**（`#pwTrendNote`，`pointer-events:none`，不挡点选） |
| 环/低电条/aria/状态 | 由 estimate 驱动（现状） | 自动用慢统计（无需另改） |

实现要点：
- 新增 `#pwTrendNote` DOM（趋势容器内绝对居中；样式 `font-size:11.5px;color:var(--ink2)`，`hidden` 控制）。
- 新增 `.pw-cdot`（6–7px 圆点 #fff 底 + 主色描边，用 `style="left:%;top:%"` 定位；复用 `.pw-tdot` 之外的新 class，避免影响 detail 测试）。
- 阶梯路径只对慢频房；实时房仍 `M/L` 斜线（避免无谓视觉变化与测试回归）。
- `renderTiles` 的 `参考` 判断从「slowInfo 且 daysMain≠—」改为「慢频 est.ref」+ 保留实时房原有 slowInfo 规则。
- `pull/loadHist` 按 §2 增加 30d 窗口；`normHist` 不变。
- 使用说明 `#s-ug` 电费条目补一句：13/16 号楼网关日更，估算按真实更新点计算并可能标「参考」，无更新会提示（不写长说明段落，保持既有风格）。

`data-*` 便于测试：`#pwTrendCard` 已有 `data-state`；可加 `#s-power data-cadence="slow|live"`（非必需，但测试可断言）。

---

## 4. 小程序同口径（`mp-class-tools`）

- `utils/power.js`（纯函数）：
  - 新增常量 `SLOW_BUILDINGS`、`MIN_SEG_H`、`EXPECT_H`、`CH`；
  - `isSlowBuilding(b)`、`changesIn(pts)`、`slowStats(hist30, row)`（返回同 §1.2）、`estimateSlow(hist30,row)`；
  - `estimate()` 增加 §1.4 守卫；
  - `slowUpdate(hist24)` 保留现有字段并补 `lastChange/lastRecharge`（供页面更新行/充值 tile）；
  - `tilesOf(...)` 支持慢频：tile1 参考标记按 `est.ref`；tile2 无下降 sub「该区间无更新」；tile4 用 `lastRecharge`；
  - 导出新函数供 `v3_power_diag_tests.js` 单测。
- `pages/power/power.js/.wxml/.wxss`：
  - 选中慢频房时 `load()` 额外拉 30d history（同 §2，缓存 5 分钟；失败不阻塞其它窗口）；页面 `_render` 选择慢/实时估算；
  - 趋势头徽标「日更」/hero 更新时间用 lastChange/无变化文案；tile2 sub、tile4 慢频数据；
  - canvas：慢频阶梯线 + 真实变化点圆点 + 无更新提示文字（画在绘图区内，不挡点击/游标）；平线垂直居中；
  - 不改 UD v6 契约、版本号（`utils/version.js` 保持 2.0.0）、AI toggle、分享/隐私。
- mp 测试：`mp-class-tools-tests/unit.js`（或 `v3_power_diag_tests.js`）新增 §1 纯函数/§3 决策断言；`sync_contract_test.js` 31 项不变；`staticcheck.py` exit 0。**能开 automator 则跑 `power_preview.js` 截图；开不了在报告中说明**。

---

## 5. 测试 fixture 与期望值（web mock 为「几小时前」格式）

`power_check.py` 的 mock：同一 `HIST[rv]` 对 24h/7d/30d 按 `ts=gte` 过滤，因此上表可覆盖三档。期望值按 §1 公式计算（JS `toFixed` 语义：11.25→「11.3」、5.481→「5.5」）。

| id | 房 | HIST（小时前, 电量） | 当前 q | 期望 |
|---|---|---|---|---|
| S1 | `1-13---324` | (11.2,100.00) (0.2,88.75) | 88.75 | events=2、1 段(11.25/11h)→rate=**11.25**、days=**7.9**、ref=true、ring=**26.3**；24h 变化 1 次→drop **11.3** 度；chip「日更」；更新时间=最后一个变化点（约 12 分钟前，MM-DD HH:MM）；无「近 24h 无更新」；慢频图 1 个变化点 |
| S2 | `1-16---305` | (30.1,50.00) (6.1,38.00) (0.2,38.00) | 38.00 | 1 段 12°/24h→rate=**12.0**、days=**3.2**、ref=true、ring=**10.6**；24h changes=0 → 提示「近 24h 无更新」、tile2「—/该区间无更新」、平线垂直居中（末点 top≈50%）；chip「日更」 |
| S3 | `1-13---308` | (168,120)(96,101)(72,101)(48,89)(24,89)(6,83)(0.2,83) | 83.00 | 3 段(19/72h,12/48h,6/42h)→rate=**5.5**、days=**15.1**、ref=false（无「参考」）；24h drop **6.0**；chip「日更」；变化点 1 个（24h） |
| S4 | `1-16---306` | (48,90)(24,90)(6,120)(0.2,120) | 120.00 | 只有 1 次上升 → 0 有效段：估算「数据积累中」/tile1「—」/ring 4；tile4 上次充值 **120.00**（6h 前）；chip「日更」 |
| S5 | `1-16---306`（or 另一慢房） | (168,200)(120,194)(96,194)(72,188)(48,188)(24,182)(12,122)(0.2,122) | 122.00 | 段 6/48h、6/48h、6/48h 保留，60°/12h 被判异常剔除 → rate=**3.0**、days=**40.7**（显示 ≥30）；切 30d：区间下降 = 6+6+6=**18.0** 度（异常段被现有 deductOf 剔除） |
| L1 | `4-23A---321` | 沿用 `power_check.py` 现有 fixture | 382.02 | **完全保持现状**：无日更 chip、估算 ≥30 天、tile2「近 24h 用电 6.3 度」等（现有 155 项断言不变） |
| L2 | `4-23B---422` | (8.0,100.02)(0.2,100.00) | 100.00 | 实时房、24h/7d 均无真实下降 → 新守卫：估算「数据积累中」、tile1「—」、ring 4（替换原「≥30 天/≈0.1 度/天」断言） |

补充用例：
- **请求契约**：选择慢频房 → 恰好 3 个 history 请求（24h/7d/30d，gte 递增、order=ts.asc、limit=2000）；实时房 → 2 个（现状）。
- **区间切换**：慢频 7d/30d 图仍按真实时间压缩铺满、x 轴 3–5 刻度、无横滑、不触发切工具；切档不重复请求已缓存窗口（30d 已随 pull 拉取）。
- **数据覆盖（防未来提速）**：13 号楼某房 24h changes≥6 的 fixture → 不显示「日更」chip，走实时口径。
- **视觉/回归**：360/430/1280 无横向溢出；0 JS 报错/0 console.error/0 外部请求；`water_check` 等既有门禁全绿。

---

## 6. 测试与门禁清单

网页（在 `web/tools` 下运行）：
- 新增 `tests/v2_power_cadence_check.py`：S1–S5、L1、L2、请求契约、区间切换、数据覆盖、三档宽度、静止截图（`tests/_shots_power_cadence/`）。
- 更新 `tests/v2_power_slow_check.py`：按 §3 新 UI 断言（13/16「日更」+ 估算修复 + 更新行 + 无更新提示；23A 正常）。
- 更新 `tests/power_check.py`：C（16-305 低电 fixture 改为 (30,24.6)(6,22.25)（约 9.5 天/ring 31.6；低电与提示条断言保留））、Q（L2 422 → 数据积累中）、静态断言若涉及旧文案同步调整；**155 项数量尽量保持**。
- 回归必跑：`power_check`、`v2_power_slow_check`、`v2_power_cadence_check`、`v2_power_detail_check`(24)、`v2_power_sync_hardening_check`(29)、`v2_orient_power_check`(33)、`water_check`(169)、`sync_check`(144)、`v2_ui_check`(27)、`overflow_check.py 430`。
- 报告：改动文件/行为、测试输出日志、截图路径、任何因新口径更新的既有断言及理由。

小程序（`mp-class-tools-tests` 下运行）：`node unit.js`、`node v3_power_diag_tests.js`、`node sync_contract_test.js`、`node tool_sort_unit.js`、`python staticcheck.py`、`node code_quality_check.js`；能开 automator 则 `node power_preview.js` + `mp.screenshot`，开不了在报告注明。

---

## 7. 部署与文档（Lead 负责，teammates 不要执行部署）

- 网页：备份 OSS 线上 `index.html` → `python deploy/sync_tools.py index.html` → 用 oss2 读回对象比对 sha256（**注意：furina.fun DNS 当前无 A 记录（备案暂停），无法用 URL 校验**；以 OSS 对象字节比对为准）。
- 文档：`CHANGELOG.md`（增量 23）、`HANDOFF.md` 新章节（含真实数据证据、回滚点）、`web/AGENTS.md §4b` 新增条目、`验收报告/` 网页+小程序报告、`mp-class-tools/CHANGELOG.md`、本 spec 保留。
- 小程序：只改源码+测试，需用户微信开发者工具上传发布；`VERSION` 保持 2.0.0（用户后台上传版本号另计）。

---

## 8. 边界与风险

1. 13/16 网关实际更新时刻/是否仅工作日无法从 47h 数据完全确定：单段观测按 `EXPECT_H=24` 折算并标「参考」；≥2 段后按真实间隔加权（含周末长间隔），不再依赖假设。
2. 30 天窗口在极端加密采样下可能超 2000 条上限（当前安全）；如出现再评估分页。
3. 慢频房切 24h 档且无变化时，图表为平线 + 提示，这是如实展示；默认档位仍按用户本机记忆（不自动改档）。
4. 实时房只在「窗口真实用电=0」时改显示「数据积累中」（1.4），其余算法/观感不变；既有无关联断言若受影响按本规格更新并记录。
5. 不改数据表/同步脚本/云函数；不改其它工具/导出/隐私边界（页面仍只有楼栋+房间号+电量+时间）。

## 7. 2026-11-11 增量 42 补充（网页端 UI/比较口径变更，不改本规格统计算法）

- **13/16 号楼隐藏 24h 档**：网页对 13/16 号楼主楼（`SLOW_BLD`）不再展示 24h 区间按钮，选中时默认 7 天；**24h 数据仍按本规格拉取**，仅用于 `isSlowRoom`（网关提速降级）/`changesIn`（日更检测）/估算，不进入 24h 趋势展示。测试如需验证 24h 内部口径，可程序化 `setRange("24h")`（用户界面无此入口）。
- **电费比较改自然周期同期**：tile 徽标不再是「上一同长窗口」，而是今日/本周/本月的同期对比（详见 `HANDOFF.md` 增量 42、`v2_power_trend_compare_check.py`）；本规格的统计/估算算法（`slowStats`/`estimate`/`changesIn` 等）不变。
