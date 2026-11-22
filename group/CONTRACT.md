# 分组独立 + 抽签/分组拆分 · 跨端契约（唯一真源）

> 2026-11-22 · 用户需求：「将分组功能与抽签功能独立，优化两者的使用逻辑和界面，对所有端生效」。
> 用户确认的口径：**直接删除结果单**（原 STEP 3 合并图）；**保留一个「沿用最近一次抽签结果」的快捷入口，但只在分组页**（抽签页不再有「下一步」）。
> 范围：网页 `web/tools/index.html`、小程序 `mp-class-tools`、安卓 `android-class-tools`、鸿蒙 `harmony-class-tools`、Windows `windows-class-tools`。
> 与本文冲突的旧实现以本文为准；改契约先改本文。

---

## 0. 红线（继承各仓 AGENTS.md）

1. 导出图片/页面**不出现学号、手机号、宿舍号**；姓名只能来自本班名单或用户自填名称映射。
2. 不引入构建链 / 外部依赖 / CDN / 统计；网页保持单文件零依赖、原生 fetch。
3. 不新增 UD（userdata v6）顶层 section、不改合并算法；小程序/网页互通字段保持旧值域（见 §4）。
4. 测试只用测试身份（`3260799999 / 测试账号` 或 9999 段临时 QA 身份）。
5. 各端改完走各自仓的 `sync-repos.cmd "feat: …"` 双远端推送；网页部署 `deploy/sync_tools.py`；安卓按发版规则发 beta。

---

## 1. 产品定义（五端一致）

### 1.1 抽签（draw）
- **单页工具**：配置 + 结果同页；**不再有 STEP 1/2/3 切换条**，**不再有「下一步：分组」**。
- 参数：范围（起始/结束）、抽取个数、排除序号、参与名单（可选，来自班级名单）、名称映射（序号→名称）、允许重复、剔除后自动重抽。
- 结果：结果序号/名称、剔除（×）与自动补抽、排序（从大到小/从小到大/随机打乱）、存证行（已存证·今日第 N 次/存证中/未存证）、导出图片、抽签记录、重置。
- 重置**只清空抽签结果与剔除记录**（不再连带清空分组结果——分组已是独立工具）。
- 抽签成功后把「最近一次抽签结果」**本机持久化**（序号数组 + 参数快照 + 时间），供分组工具读取；换端不跟随（不进 UD）。

### 1.2 分组（group）
- **独立工具**：有独立入口（网页工具栏/全部页、小程序全部页与首页快捷勾选、各端原生工具目录），**不依赖先抽签**，也不需要从抽签页跳转。
- 成员来源（三选一，顺序固定）：
  1. **全班**：一键取班级名单全部成员（内部仍等价于「班级名单」来源 + 全选，见 §4 兼容）；
  2. **最近抽签**：读取本机持久化的最近一次抽签序号（无则置灰并提示）；
  3. **手动选择**：从班级名单勾选。
- 分组方式：按组数 / 按每组人数（数字 + 加减步进，点按 ≥40px）。
- 打乱成员再分组（默认关）。
- 结果：组卡（第 N 组 + 人数 + 成员「序号 姓名」），摘要「共 N 人 · M 组 · 每组 x–y 人」；操作：重新分组 / 复制 / 导出图片。
- 分组**不再有**「上一步：抽签」「下一步：结果单」。

### 1.3 结果单
- **删除**：网页 `#s-draw` 的 STEP 3、小程序 `pages/sum`、各端相关入口与导出入口全部移除。
- 导出能力不丢：抽签、分组各自导出图片（版式仍走导出卡 v2）。

### 1.4 导航与入口
- 网页 `TOOLS` 新增 `{k:"group", n:"分组"}`，`ALL_TONE.group` 用蓝色系；`draw` 描述改为「抽签与结果导出」。
- 小程序 `utils/tools.js` 新增 `key:"group"` 工具（name「分组」），`draw` 名称改「抽签」；`app.json` 删除 `pages/sum/sum`。
- 安卓/鸿蒙/Windows 工具目录里 `group` 原本已存在，**保持**；只改文案与入口顺序相关描述（见 §5）。

---

## 2. 界面规格（网页/小程序）

### 2.1 抽签页
- 布局：手机单列；`≥960px` 左右分栏（左「抽签参数」卡、右「抽签结果」面板），与既有设计规范一致。
- 抽签按钮文案：无结果「开始抽签」；有结果「重新抽签」。
- 结果区：大号序号（有名称时序号小字 + 名称大字），每项右上 × 剔除；底部小字「共 N 个 · 排序：xxx · 已剔除 K」。
- 空态：`—` 占位（保持各端现有空态风格）。
- 存证行、抽签记录、名称映射、名单选择弹层交互不变（契约 `web/draw/CONTRACT.md` §3 继续有效）。

### 2.2 分组页
- 布局：手机单列；`≥960px` 左「分组参数」卡、右结果区（组卡网格 `minmax(250px,1fr)`）。
- 成员来源用分段按钮（`≥40px`）：`全班` / `最近抽签` / `手动选择`。
  - `全班` 文案带人数（如「全班 70 人」）；`最近抽签` 带人数与时间（「最近抽签 10 人 · 11-22 21:05」），无结果时按钮 `disabled` 且提示「还没有抽签结果」。
  - `手动选择` 展开名单气泡摘要 + 「选择名单」按钮 + 「全选 / 清空」快捷。
- 分组方式分段按钮：`按组数` / `每组人数`；数字行前有 − 后 +（步进 1，组数最小 2，每组人数最小 1）。
- 结果摘要一行：「共 N 人 · M 组 · 每组 x–y 人」；组卡标题「第 N 组」+ 人数徽标。
- 操作按钮：`开始分组`（无结果）/`重新分组`（有结果）、`复制`、`导出图片`。

---

## 3. 抽签结果本机持久化（跨端同结构）

- 键（各端本机）：网页 `localStorage["zq_draw_last_v1"]`（已有），小程序 `storage` 的 `zq_flow.draw`（已有），安卓/鸿蒙/Windows 各自新增「最近抽签」存储（SharedPreferences / Preferences / LocalSettings）。
- 结构（逻辑等价即可，字段名不必跨端一致）：
  `{at:<ms>, result:[<序号>…], pool:[…], cfg:{range,count,dup,sort}}`。
- 写入时机：每次抽签成功（含重新抽签）；重置时**保留**上一次成功结果（便于分组沿用），仅当用户显式「重置本轮」且确认后可保留。
- 读取时机：分组页进入、来源切到「最近抽签」、点「沿用」时。
- **去重**：沿用抽签结果时按序号去重（允许重复抽签时同一个人不应被分进两个组；分组人数以去重后为准）。
- 名称：分组沿用抽签结果时，名称优先级 = 名称映射 > 班级名单派生名 > 空（与抽签页 `nameOf` 一致）。

---

## 4. 兼容（UD v6 / 存量数据）

- `D.d.group`（网页）/ `store.group`（小程序）字段**不变**：`{source:"prev"|"pick", mode:"groups"|"per", n, shuffle}`（网页 mode 值为 `groups|pergroup`，保持）。
- 「全班」不新增 source 值：点「全班」= `source:"pick"` + `groupSel = 班级名单全部座号`；判断「全班」只需比较已选集合是否等于全班集合。
- `draw.names` 等既有字段不变；`homeTools` 里新增的 `group` 是普通 key，小程序旧版把它映射到 `draw`，新版**取消该映射**（`SYNC_KEY_IN` 删除 `group:'draw'`）。
- 抽签/分组的参数、名单选择仍随账号同步（既有契约）；抽签结果本身**不同步**（本机）。
- 旧版（未升级端）读到新版数据不得报错：多余字段忽略、未知 source 归一为 `prev`。

---

## 5. 各端落地清单

### 5.1 网页（`web/tools/index.html`）
1. 删除 `.steps` / `#p1`/`#p2`/`#p3` 三步结构与相关 JS（`stepGo`、`#aNext`、`sumData`/`renderSum`/`#sImg`/`#sCopy`）。
2. `#s-draw` 改单页双栏；新增 `#s-group` 分组页（参数 + 结果 + 导出/复制）。
3. `TOOLS` 增 `group`；`ALL_TONE` 增 `group`；全部页卡片、首页槽位、拖动排序自动生效（`group` 是普通工具 key）。
4. 滑动引擎：`CURTAB==="draw"` 的 STEP 手势取消（两个工具都按普通工具页切工具）。
5. `#aReset` 只重置抽签；分组的「重新分组」只重排分组。
6. OPTIM V2 预设（`opt2PreApply`）仍读写 `#aStart/#aEnd/#aCount/#aExcl/#aDup/#gMode/#gNum/#gShuffle`：**保留这些 id**（分组页 `#gMode` 改为 `select` 或保留原控件均可，但 id 必须存在）。
7. 使用说明（`#s-ug`）里抽签/分组条目文案同步更新。
8. `window.DRAWPROOF` / `window.GROUP` 探针：新增只读 `window.GROUP={state,config,members,result}` 供测试。

### 5.2 小程序
1. `pages/draw`：删 `steps`/segmented、底部「下一步 · 分组」；重置只清抽签；保留存证/记录/名称映射/分享。
2. `pages/group`：删 segmented、「上一步 · 抽签」「下一步 · 结果单」；成员来源改「全班 / 最近抽签 / 手动选择」（全班 = 全选 class_members）；读 `flow.draw`；结果摘要；重新分组/复制/分享/导出。
3. `pages/sum` 删除（`app.json`、`utils/tools.js`、`utils/flow.js` 的步骤提示、分享卡片、AI skills 引用一并清理）。
4. `utils/tools.js`：拆 `draw` / `group` 两个 key；`SYNC_KEY_IN` 去掉 `group:'draw'`。
5. 图标：新增 `images/tool-group.png`（96×96，风格与 `tool-draw.png` 一致）。
6. 测试：`tests/unit.js` + 相关单测更新；`staticcheck.py`、`code_quality_check.js` 退出 0。

### 5.3 安卓（`android-class-tools`）
1. 抽签结果卡删除「去分组」按钮与 `onGroup` 回调链（`DrawScreen`/`MainNavHost`/预览）。
2. 新增「最近抽签」本机存储（序号 + 参数快照 + 时间），抽签成功即写；`GroupScreen` 的 `PREV` 来源改读该存储（不再依赖内存 `DrawSession`），文案改「最近抽签」。
3. 分组页：保存来源改「最近抽签 / 班级名单」+ 「全选」快捷；结果摘要与组卡文案对齐 §2.2。
4. 版本号 +1（`versionName` beta 递增），`testDebugUnitTest` 全绿，`assembleRelease` 发 beta 到更新渠道。

### 5.4 鸿蒙（`harmony-class-tools`）
1. 删除抽签结果页的「去分组」跳转与 `onGroup` 传递。
2. `DrawSession` 改持久化（preferences）：分组来源「最近抽签」可跨重启读取；文案改「最近抽签」。
3. 分组页加「全班」快捷（全选名单）；结果摘要对齐。
4. 单测 `hvigorw test`（或仓内既有命令）通过。

### 5.5 Windows（`windows-class-tools`）
1. 删除抽签→分组的快捷跳转（若存在）。
2. 最近抽签结果持久化（`ApplicationData.LocalSettings` 或既有 settings 设施）；分组来源改「最近抽签」并读取它。
3. 分组页加「全班」快捷；结果摘要对齐。
4. `dotnet test` 通过。

---

## 6. 测试与验收

| 端 | 必跑 |
|---|---|
| 网页 | `tools/tests/group_check.py`（新建，覆盖拆分与分组交互）、`draw_proof_check.py`、`export_check.py draw`、`roster_check.py`、`sync_check.py`、`v2_ui_check.py`、`optim_v1/v2`、`overflow_check.py 430`、`v2_drag_check.py`、`selfcheck.py`、`v2_ug_check.py` |
| 小程序 | `tests/unit.js`、`staticcheck.py`、`code_quality_check.js` |
| 安卓 | `gradlew testDebugUnitTest` + `assembleRelease --project-prop ct.updateChannel=beta` |
| 鸿蒙 | 仓内单测 + 构建 |
| Windows | `dotnet test` |

验收要点（全端一致）：
1. 抽签页没有分组步骤/下一步；分组页没有上一步/结果单。
2. 分组可以不抽签直接用（全班/手动选择）；抽签后关掉页面重进，分组仍能「最近抽签」沿用。
3. 两端互不干扰：重置抽签不清空分组结果；重新分组不改变抽签结果。
4. 旧数据（只有三步工作流时代的参数）升级后不报错、不丢参数。
5. 0 JS 报错、0 外部请求、360/390/430 无横向溢出、导出图片内容与旧版一致（分组/抽签各自）。

---

## 7. 文件所有权（并行写作用，本次单会话由 Lead 统一协调）

| 范围 | 允许改 |
|---|---|
| `web/tools/index.html`、`web/tools/tests/**`、`web/draw/CONTRACT.md`、`web/group/CONTRACT.md`、`web/AGENTS.md`、`web/HANDOFF.md`、`web/CHANGELOG.md` | Lead |
| `mp-class-tools/**` | mp 负责 |
| `android-class-tools/**` | android 负责 |
| `harmony-class-tools/**` | harmony 负责 |
| `windows-class-tools/**` | windows 负责 |

---

## 8. 回滚

- 网页：重传部署前备份 `tools/_backup/index_online_<时间>_preGroupSplit.html`（部署脚本自动备份）。
- 小程序：回退上一版源码后重新上传。
- 安卓/鸿蒙/Windows：回退到上一版 tag / 构建。
- 无数据库变更（本需求不涉及云端结构）。
