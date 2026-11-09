# 水量统计 + 电费计费 · 实现契约（Lead 定稿 2026-11-06）

> 由 Lead 维护。实现方 = Lead（只改 `tools/index.html`）；测试方 = water-tester（只写 `tools/tests/water_check.py`、`_water_shots/`）；
> 小程序方 = mp-water（只改 `mp-class-tools/`）。计费规则来源见 `web/_water_rules/research.md` 与 `rules.json`。
> 若上下文冲突，以本文件为准；Lead 改契约会同步通知。

## 0. 计费规则常量（页面唯一来源 `var RULES`，web/mp 同值）

```js
var RULES={
  elec:0.58,                 // 元/度（福建中医药大学后勤基建处 2025-09-05 说明）
  water:3.03,                // 元/吨（同上；无阶梯、无额外加价）
  waterFreePP:2,             // 吨/人/月
  elecFreePP:5,              // 度/人/月（官方 2021 公寓管理规定；与旧网文「4 度」冲突，页面注明「以学校最新通知为准」）
  personsDef:4,              // 宿舍人数默认 4
  personsOpts:[4,6],         // 页面可选
  waterDate:"2025-09-05", elecDate:"2025-09-05", quotaDate:"2021-07"
};
```

公式（页面展示与测试同口径）：
- 本期水费(元) = `max(0, 用量吨 - 2×人数) × 3.03`（保留 2 位）
- 折合扣电(度) = `水费 / 0.58`（保留 1 位）
- 区间电费(元) = `区间用电(度) × 0.58`（保留 1 位）
- 用量吨 = 本次读数 − 上次读数（同一宿舍按月份升序的前一条）
- `1 吨水 ≈ 3.03/0.58 = 5.2241 度`（规则卡展示）
- **不得使用福州市居民阶梯价/福建阶梯电价**（仅研究文档备选，页面不接）。

## 1. 数据结构与本机存储

```jsonc
// D.d.water（localStorage zq_tools_v2_<sid> 内，随 DEF 初始化）
water = {
  "rooms": {
    "<roomverify>": {
      "p": 4,                    // 宿舍人数：4|6（默认 4）
      "recs": [                  // 按月唯一、按 m 升序；最多 120 条
        {"m":"2026-10","r":123.45,"ts":1699000000000},  // r=水表读数(吨)，2 位小数
        {"m":"2026-11","r":130.10,"ts":1699100000000}
      ]
    }
  }
}
```
- `DEF.water={rooms:{}}`；`mkD` 对 water 做 object 校验（坏数据 → `{rooms:{}}`）。
- 本机键仍走 `storeKey()`（已有按 sid 隔离）。

## 2. UD v6 同步契约（新增第 11 个 section）

- `UD_KEYS` 末尾追加 `"water"` → 顺序 `homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,water`。
- `UD_DEF.water={rooms:{}}`。
- `UD.sections()` → `out.water={rooms: clone(D.d.water.rooms || {})}`。
- `UD.apply` 增加 `if(take("water")) WATER.applyRemote(merged.water);`。
- **顶层 blob 键 14 个（顺序）**：`v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,water,homeToolsAt`。
- `at.water` 由既有 LWW 机制自动维护；water 值内**不镜像 at**（只有 power 值内含 `at`）。
- 旧数据无 water → 默认 `{rooms:{}}`，不报错、不覆盖其他 section。
- 小程序未拥有 water section 时按既有「原样保留」规则携带，不写坏。
- 保存一条抄表记录后 `D.save()` → 触发 UD 脏检测 → ≥1200ms 防抖后 POST userdata（blob 含 water）。

## 3. web DOM（`tools/index.html`）

### 3.1 工具/路由
- `TOOLS` 末尾新增：`{k:"water",n:"水量",d:"每月手动抄表，自动对比上次，按校方规则算水费"}`（追加在 `diag` 之后）。
- `ALL_TONE` 增加 `water:"blue"`。
- `#s-water` 段插入位置：`#s-power` 之后、`#s-all` 之前。
- `gotoTab`：`if(k==="water")WATER.enter();`（`renderTabs` 的 `ok` 判定 / `POS.begin` 的 valid 由 `toolOf` 自动覆盖）。
- 全部页卡片自动生成（`data-card="water"`、`data-open="water"`、可拖动）。

### 3.2 必须存在的 DOM id
```
#s-water
#wtMeta               副标文字（含关注宿舍名/更新时间）
#wtSel                关注宿舍下拉（选项同 #pwSelect：PW_ROOMS 17 间 optgroup；与电费共用选择）
#wtPersons            宿舍人数 select（4 人间/6 人间，默认 4）
#wtLastNum #wtLastSub 上次抄表读数与副标（月份/人数）
#wtCmp                自动对比区：本期用量 / 水费 / 折合扣电（无上一条时显示「首次记录」）
#wtMonth              隐藏的真实值 input[type=month]（1px/opacity 0，默认当前月；保存/预览/测试读它）
#wtMonthBtn #wtMonthPrev #wtMonthNext   自定义月份控件（触发 / 上一个月 / 下一个月）
#wtMonthLabel #wtMonthY #wtMonthM       触发按钮内的「YYYY 年 MM 月」文字
#wtMonthPop                            月份选择弹层（fixed；hidden 时隐藏）
#wtMonthPopY #wtMonthYPrev #wtMonthYNext #wtMonthNow #wtMonthClose  弹层年份导航 / 本月 / 关闭
#wtMonthGrid                          12 个月网格容器；每月按钮 [data-ym="YYYY-MM"]
#wtReading            读数 input[type=number] step=0.01（吨）
#wtSave               保存按钮（btn pri）
#wtPreview            输入即时预览（填读数即显示 用量/水费/折合扣电）
#wtList               历史列表容器；每行 [data-wm="YYYY-MM"]，删除按钮 [data-wdel="YYYY-MM"]
#wtRuleBody           计费规则卡内容（单价/免费定额/公式/来源，短句，无长段落）
```
历史行文本须含：月份、读数、用量、水费（SVG/表格均可，但 `textContent` 可断言）。
无数据态 `#wtCmp`/`#wtList` 有明确占位（如「还没有抄表记录」），不写解释段落。

### 3.2b 月份选择 UI（2026-11-07 增量 23）
- **真实值**：始终存 `#wtMonth`（type=month）。自定义控件只改它：`WATER.setMonth(ym, close)` 写值 →
  `syncMonthLabel()` 更新 `#wtMonthY/#wtMonthM` → `renderPreview()`；隐藏 input 的 `input/change` 事件
  反向同步标签（程序化 `set_input` 也生效）。
- **月步进**：`#wtMonthPrev/#wtMonthNext` = ±1 月（跨年自动进位/借位，年份钳制 2000–2100）。
- **弹层**：`#wtMonthBtn` 打开 `#wtMonthPop`；按年展示 12 个月（`[data-ym]`），选中月 `.on`（浅青底+青边）、
  当前月 `.now`、**已有抄表记录的月份 `.wt-mo-dot` 小圆点**；年份 ‹ › / 「本月」/ ×；选月回写并关闭、焦点回触发按钮。
- **关闭**：Esc（回焦触发按钮）、点弹层外、切页（`gotoTab`）、窗口缩放、页面滚动；`aria-expanded` 同步。
- **禁用**：未选关注宿舍时 `#wtMonthBtn/#wtMonthPrev/#wtMonthNext` 与隐藏 input 均 disabled，弹层不可打开。
- **响应式**：401–480px / 960–1439px 窄列隐藏日历图标并收窄标签（触发按钮内容零溢出）；≤480px 两侧步进 40px 可点区。
- 测试门禁：`tools/tests/v2_water_month_check.py`（40 项）。

### 3.3 行为
1. **未选宿舍**：`#wtCmp` 显示「先选择关注宿舍」；`#wtMonth/#wtReading/#wtSave` disabled；选宿舍与电费共用：`#wtSel` change → `POWER.pick(rv)` → `WATER.render()`（电费选择变化后进入水量页也要同值）。
2. **人数切换**：`#wtPersons` change → 写 `water.rooms[POWER.sel].p` → `D.save()` → 全量重算（历史行水费按当前 p 重算）+ 规则卡免费额度更新。
3. **保存**：
   - 读数须为有限数且 ≥0（否则 toast，不落盘）；
   - 同月份已存在 → 覆盖该条（toast「已更新 X 月记录」）；
   - 排序后若读数 < 前一条读数 → 拒绝并 toast「读数不能小于上次记录」，不落盘；
   - 落盘归一化：recs 按月升序、`r` 四舍五入 2 位、`ts=Date.now()`、上限 120 条（丢最旧）；
   - 落盘后 `D.save()`、重渲染、清空 `#wtReading`、保留月份（自动 +1 月？可选：保持当前月不变）。
4. **自动对比**：`#wtCmp` 展示最新一条：`较上次（YYYY-MM）用量 X.XX 吨`、`水费 ¥X.XX`、`折合扣电 X.X 度`；若用量超过免费额度，展示「超出定额 X.XX 吨」；首条显示「首次记录（无上次对比）」。
5. **历史**：按月倒序；每行显示 月份 / 读数 / 用量 / 水费 / 删除；首条（最早）用量显示「—」。删除带 `confirm`，删后后续行用量自动重算。
6. **规则卡**：至少包含 `0.58 元/度`、`3.03 元/吨`、`2 吨水 + 5 度电/人/月`、`水费=超出定额用量×3.03`、`折合扣电=水费÷0.58`、来源（学校后勤基建处 2025-09-05 / 2021 公寓管理规定）、`以学校最新通知为准` 提示；**不出现**市政阶梯价。
7. 页面无网络请求（数据本机 + UD 同步）；不显示姓名/学号；只显示关注的这一间宿舍。
8. 360/430/1280 三档无横向溢出；0 JS 报错；可点区域 ≥40px（`#wtSave/#wtSel/#wtPersons`）。

## 4. 电费页（`#s-power`）计费 + 异常大跌忽略

### 4.1 常量
```js
var PW_DEDUCT={minDeg:5, factor:4, waterMatch:0.10, timeHint:true};
```

### 4.2 算法（必须与 web/mp 同口径；mp 只实现数据忽略，不画图）
输入 pts（ts 升序 `{t,q}`）。相邻段 `dq = q[i-1]-q[i]`（>0 = 用电；<0 = 充值）。
1. `U` = 窗口内所有 `dq>0.05` 的**中位数**（无则 0）。
2. 候选异常段：`dq > max(5, 4×U)`。
3. 水费对应段（可关联网水量记录）：取该宿舍水量记录中月份为「采样时间所在月」或「上一月」的记录，计算
   `fee = max(0,(r - prev_r) - 2×p)×3.03`，`deg=fee/0.58`；
   若 `dq≥2` 且 `|dq-deg| ≤ max(2, 10%×deg)` → 判为 `water:true`（即使未达候选阈值也忽略）。
4. 候选但未匹配 → `water:false`（界面「异常扣减」）。
5. 判定段：**不计入区间用电/区间电费**；`deriveRange` 输出 `deduct:[{t,deg,water}],deductDeg,deductYuan,deductN,deductWaterN`；
   `rateFrom` 同样跳过（`hours+=dt`、`used+=0`，充值段仍整段跳过）。`drop` 只累计非扣减段。
6. 保护：`dq` 段后连续 2 个采样为 0/相同值（断网/换表）时仍按扣减处理即可，不特殊造假；充值（`dq<-0.05`）逻辑不变。

### 4.3 UI
- 趋势卡头新增 `#pwDeduct` chip：有扣减时显示「水费扣除 N 次」（全部匹配 water）或「已忽略 N 次扣减」；`hidden` 无扣减。
- 图例追加一项「扣减 <b>X</b> 度」（X=deductDeg>0 时）。
- 区间用电 tile 增加副标：`≈ ¥X.XX 电费`（X=drop×0.58）；无选择/无数据时副标为空。
- `#pwSide` 内 tiles 之后新增 `#pwBill` 计费规则行（短句）：`电价 0.58 元/度 · 区间电费按用电计`、`水费 3.03 元/吨从电费账户扣（1 吨≈5.2 度）`；有扣减时追加 `已忽略 N 次·X 度≈¥Y`。
- 现有契约保持：未选择 0 power/power_history 请求；`#pwRefresh`、三档 chips、横滑固定轴、慢更新 chip、低电阈值弹层不变。

## 5. 测试门禁（water-tester 写 `tools/tests/water_check.py`）

参考 `power_check.py`：headless Edge + 本地 http server + CDP（websocket-client）+ fetch mock + 注入假身份（`localStorage` 身份 token 键见 power_check）；`SPEC_CHECK=<副本路径>` 可复盘任意 index.html 副本。输出 `N/N PASS`、失败明细、截图到 `tests/_water_shots/`。

必须覆盖（详细断言）：
- A 身份门禁：未登录不渲染水量卡片 / 0 请求；登录后可进入。
- B 基础：全部页「水量」卡片存在、`data-open="water"`、打开 `#s-water`；空态引导；360/430/1280 `scrollW==innerW`；0 JS 报错/0 console.error；无外部请求（除 CloudBase mock）。
- C 抄表：选宿舍（与电费共用）→ 填 2026-09/2026-10/2026-11 三条读数 → 保存；用量=差值；水费按免费额度规则；折合扣电；读数小于上次被拒绝；同月覆盖；删除后重算；历史倒序；`#wtPreview` 即时；人数 4↔6 切换重算。
- D 规则卡：含 0.58/3.03/2吨/5度/来源；不含「阶梯」「7.20」「0.4983」。
- E 电费：mock power+history（含一次 30 度异常下跌）→ 区间用电不含 30 度；`#pwDeduct` 出现；tile 副标电费=用电×0.58；水量记录能匹配时 chip 文案为水费扣除；rateFrom 估算不受异常段影响（fixture 断言 DOM 天数/速率）。
- F 同步：保存记录后等待 >1.3s → `__udPosts` 出现 blob 且 `JSON.parse(blob).water.rooms[rv].recs` 正确、顶层键 14 个顺序正确（`v,at,...,water,homeToolsAt`）；换 profile（清 localStorage 保留 mock 云端）/重新登录 → 记录恢复；两账号隔离；旧数据无 water 不报错。
- G 回归：运行 `power_check.py` 仍全绿（由 Lead 统一回归；water_check 只断言自己页面）。

## 6. 小程序（mp-class-tools，mp-water 执行）

- `utils/cloud.js`：`SECTION_KEYS`/`DEFAULTS` 增加 `water`（默认 `{rooms:{}}`），合并逻辑按既有 section LWW，未拥有端原样保留；顶层 blob 14 键顺序与 web 一致。
- `app.json` 注册 `pages/water/water`；`pages/water/*` 与 web 同口径：
  - 关注宿舍沿用 `power.sel`（读 `store`/`cloud` 的 power section），可切换；
  - 宿舍人数 4/6；录入月份 + 读数；自动对比上一条；水费公式；历史列表可删除；
  - 规则卡同文；数据写入 `water.rooms[rv]` 并触发同步。
- 不改变 APP_VER/版本号（仍 2.0.0，随用户下次上传）；不实现演示/审核模式。
- 测试：跑仓库既有 `unit.js`、`staticcheck.py`（handlers missing 0）、`cli preview` 编译；新增 water 相关单测（水费公式/用量对比/合并保留）。

## 7. 增量 18（2026-11-06 晚）：云同步显性化/加固 + 网页桌面比例（**仅 web，不改变 v6 契约**）

> 用户需求：「对水费统计的用户所有内容加入云同步，包括抄表记录等，优化网页端水费工具比例」。
> 审计结论（`tools/tests/_water_work/sync_audit.md`）：v6 内「用户所有内容」已全部走同步；本增量只做加固/显性化与布局，water section 仍为**整段 LWW**（不按宿舍/记录合并，双端并发改不同宿舍时后写整段覆盖属已知限制）。

### 7.1 云同步加固（web `tools/index.html`）

- **`WATER.normWater(w)`（新增）**：water section 归一——`rooms` 逐间 `{p:4|6, recs:normRecs(r.recs)}`（月份合法、读数有限 ≥0、2 位、按月升序、≤120 条），丢弃 null/字符串/数组等坏房间。
  - `WATER.applyRemote` 改用 `normWater`（远端不可信数据不再原样进本机 raw）；
  - `UD.sections().water` 推流前也归一（本机旧脏数据不回写云端）。
- **同步状态 UI `#wtSync`**（hero 底部，样式复用 `.pw-sync`）：`已同步`（`data-sync=1`）/ `未同步 · 点重试`（`data-sync=0`）；未选关注宿舍时隐藏。状态 = 云端基线已有 + `UD.pendRead()` 无 + `UD.dirtySections()` 无 `water`（**不含** `UD._push`，避免闪回）。
  - 点击重试：`WATER.requestSync()`——有基线 `UD.push(true,["water"])`，无基线先 `UD.pull(true)` 建基线再补推（不盲推默认值覆盖云端）。
- **进页补拉**：`WATER.enter()` 在本机缓存里还没有 water（旧缓存/首装）时强制 `UD.pull(true)` 一次，其余走 `UD.pull()` 60s TTL。
- **写后标记待补发**：`save/del/setPersons` 后 `UD.pendWrite(["water"])`（无基线/推送失败时下次 pull 保本机赢，同电费加固套路）。
- **push/pull 完成统一刷新**：新增 `udSyncUi()` 同时刷新电费与水量同步状态。
- **使用说明**同步清单补「关注宿舍、水量抄表记录」；水量页补「换设备自动恢复；右上『已同步』可点重试」。

### 7.2 网页桌面比例（≥960px；<960px 零改动）

- **≥1280px 三栏等高**：`grid-template-columns:repeat(3,minmax(0,1fr))`，areas `"hero form hist"/"hero rules hist"`，`align-items:stretch`；hero 与抄表历史同高，中栏 = 新增抄表 + 计费规则（合计高度 = hero，无结构性空洞）。
- **规则卡 → 横向 chips 条**（仅 ≥1280）：`#wtRuleBody{display:flex;flex-wrap:wrap}`、`.wt-rule-row` 去边框 inline 排布；文案零改动（D01–D07 仍过）。
- **dash 宽度分档**：`≥1280 max-width:1320`（生效 1188）、`≥1600 max-width:1520`（生效 1492）；`#s-water .wt-dash>.card{margin-bottom:0}`。
- **960–1279px 两栏**：areas `"hero hist"/"form rules"`，`align-items:start`，规则卡保持纵向（不 chips，避免被拉高留白）。
- **抄表历史常高内部滚动**：`#s-water .wt-hist{display:flex;flex-direction:column;min-height:0;align-self:stretch;contain:size}` + `.wt-list{flex:1;min-height:0;overflow-y:auto}` → 12 条/更多记录页高不变。
- **空态**：`#wtLastNum.wt-num.no-data`（灰、30px 小占位），不再显示 62px 大黑横线。
- **实测高度**：1280×800 `scrollH=800`（旧 1115，−315；`power` 同口径门禁 ≤810）；960/1024×800 `scrollH=955`（旧 1126，−171）；1440/1600 不滚动且用满宽度；12 条/空态 @1280×800 仍 800。

### 7.3 门禁（本轮新增/适配）

- `tests/water_check.py`：静态 +3 项（`#wtSync` 接入、`normWater` 接入、桌面排布 CSS）；新增 **H 组**（10 项）：同步状态隐藏/已同步/未同步/点重试立即补推、推送 blob 含新记录、远端归一（p=9→4、130→120、非法月份/坏房间丢弃）、收尾恢复截图状态。
- `tests/v2_water_layout_check.py`（新增，29 项）：1280×800 三栏等高/中栏合计=hero/无滚动/dash 1188/chips；1440/1600 宽 1292/1492；960/1024 两栏 scrollH≤1000；12 条内部滚动；空态；430 单列无溢出；0 JS 报错。
- `tests/v2_water_sync_check.py`（独立审计新增，116 项）：见 `_water_work/sync_audit.md`。
- `tests/sync_check.py`：静态断言适配 `UD.sections().water` 归一实现。
