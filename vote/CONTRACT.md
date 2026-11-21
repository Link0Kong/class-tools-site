# 投票功能契约（web + 小程序）· 2026-11-11（含 18:08 增量：可见人范围）

> 唯一真源。服务端（PostgREST/PostgreSQL）、网页 `tools/index.html`、小程序 `mp-class-tools` 三处实现必须与本文一致。
> 迁移文件（按顺序应用，均幂等）：`deploy/cloudbase/2026-11-11_polls.sql`（基础：表 + 5 RPC）
> + `deploy/cloudbase/2026-11-11_polls_audience.sql`（增量：可见人范围 audience）。
> 回滚：先按 `2026-11-11_polls_audience.sql` 头部回滚 audience 增量，再按 `2026-11-11_polls.sql` 头部回滚整功能。

用户需求：
- 2026-11-11：「新增投票功能，该功能需同时可用于临时的限时投票和可设立截止日期的长时投票，投票选项和投票标题需可高度自定义化」。
- 2026-11-11 18:08：「投票功能新增可见人范围选项」→ 已确认口径：**全班 / 班委 / 团员 / 指定成员**；
  **范围内的人才能看到并投票**（范围外列表里完全看不到、不能投票/看结果）；**发起人与管理员始终可见可管理**
  （管理员不在范围内时只能看/管理、不能投票；发起人始终可投）。

全班成员都可发起；发起人与管理员可管理自己的投票。

---

## 1. 数据模型

### 1.1 `public.polls`（一行 = 一场投票；所有读写只经 RPC，前端不直连表）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | text PK | 客户端生成：`p` + `cbId()`（`[a-z0-9]{4,32}`，总长 5–33） |
| `title` | text | 标题 1–80 字 |
| `description` | text | 说明 0–500 字（可空） |
| `mode` | text | `quick` 临时限时 / `long` 长时；仅 UI 提示用（`deadline=0` 时显示「不限时」） |
| `owner_sid` | text | 发起人学号（仅服务端内部使用，**任何 RPC 都不返回学号**） |
| `owner_name` | text | 发起人姓名（服务端按 `private.class_ids.name` 写入） |
| `options` | jsonb | 选项数组，2–20 项，见 §1.3 |
| `settings` | jsonb | 规则，见 §1.4 |
| `deadline` | bigint | 截止时间（epoch ms）；`0` = 不限时 |
| `status` | text | `open` / `closed`（提前结束时置 `closed`；到期由 `deadline` 判定，不写库） |
| `closed_at` | bigint | 提前结束时刻 ms（到期结束保持 0） |
| `audience` | text | 可见人范围：`all` 全班（默认）/ `committee` 班委 / `league` 团员 / `custom` 指定成员，见 §1.6 |
| `audience_seats` | jsonb | `custom` 时的**座号**数组（去重升序，1–70；**不存、不返回学号**）；其它范围恒 `[]` |
| `deleted` | boolean | 软删除（无 DELETE 权限；删除 = `deleted=true`） |
| `created_at` / `updated_at` | bigint | epoch ms |

CHECK 约束：标题 1–80、说明 ≤500、选项数 2–20、`mode in (quick,long)`、`status in (open,closed)`、`deadline>=0`、`audience in (all,committee,league,custom)`。

### 1.2 `public.poll_votes`（一人一票，服务端去重）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | text PK | `<poll_id>|<sid>` |
| `poll_id` | text | FK → `polls.id` ON DELETE CASCADE |
| `sid` | text | 投票人学号（**任何 RPC 都不返回学号**） |
| `choices` | jsonb | 选项 id 数组（单选 1 项 / 多选 1..maxChoices 项） |
| `ts` | bigint | 最后一次投票/改票时刻 ms |

`UNIQUE(poll_id, sid)`。**表对 anon 完全无权限**（无 SELECT/INSERT/UPDATE/DELETE），只能经 `poll_*` RPC 访问；
RPC 内不泄露他人投票明细（匿名投票连发起人/管理员也不返回投票人）。

### 1.3 选项对象 `options[i]`

```jsonc
{
  "id": "o1a2b3",             // [A-Za-z0-9_-]{1,24}，同一投票内唯一（客户端生成）
  "text": "选项文字",          // 1–80 字
  "desc": "补充说明",          // 0–200 字，可空/省略
  "img": "data:image/jpeg;base64,..."  // 可选配图；必须是 data:image/ 前缀；
                                        // 单张 data URL ≤ 150000 字符，全部选项 img 合计 ≤ 1.6MB
}
```
图片由客户端先压缩（长边 ≤ 640px、JPEG，控制在 150000 字符内）。服务端校验长度/前缀/总量，不合法返回中文 reason。

### 1.4 规则对象 `settings`

```jsonc
{
  "multi": false,                 // 单选 / 多选
  "maxChoices": 1,                // 单选恒为 1；多选 2–20，且不得超过选项数
  "anonymous": true,              // true=匿名（不返回投票人姓名）；false=实名（结果可见时返回投票人姓名）
  "allowChange": true,            // 截止前是否允许改票
  "resultVisibility": "afterVote" // always 始终可见 | afterVote 投票后可见 | afterClose 截止后可见
}
```
服务端 `poll_create` 负责归一（单选强制 `maxChoices=1`），并发回 canonical settings。

### 1.5 时间语义

- 截止 = `deadline > 0 && server_now >= deadline`，**一律以服务端 `clock_timestamp()` 判定**；
- `closed = status='closed' OR 已到截止时间`（RPC 返回 `closed:true` + `now:<server ms>`，客户端倒计时以本地时钟显示，提交时以服务端为准）；
- 提前结束：`poll_manage action='close'`；延长 / 重开：`action='extend'`（`p_deadline` 必须晚于当前时间）；
- 到期投票仍在列表「已结束」中保留（软删后不再返回）。

### 1.6 可见人范围 `audience`（2026-11-11 18:08 增量）

| 值 | 可见/可投人群 | 判定（服务端） |
|---|---|---|
| `all` | 已认证全班（默认） | `auth_ok()` |
| `committee` | 班委 | `auth_is_committee()`（`private.class_ids` 的 `role` 非空或 `badge` 含「班委」） |
| `league` | 团员 | `auth_is_league()`（`private.class_league` 名单内） |
| `custom` | 指定成员 | 当前 token 的 sid 对应 `private.class_ids.seat` ∈ `audience_seats`（座号数组） |

- **范围外**：`poll_list` 不返回、`poll_detail` 返回 `{ok:false,reason:"投票不存在"}`（不暴露存在性）、
  `poll_submit` 返回 `{ok:false,reason:"投票不存在"}`；
- **发起人（owner）**：始终可见、可管理、**可投票**（即使不在 custom 名单里）；
- **管理员（`auth_admin()`）**：始终可见、可管理；不在范围内时 `poll_submit` 返回 `{ok:false,reason:"不在可见范围内"}`；
- `custom` 名单只存/返回**座号**（用于编辑回填）；`poll_detail` 中 `poll.audience_seats` 仅对 `can_manage` 返回，其他人恒 `[]`；
  `poll_list`/`poll_detail` 只返回 `audience` 与 `audience_count`（座号数），**任何 RPC 不返回学号**；
- 服务端校验：`custom` 至少 1 个有效座号；座号必须真实存在于班级名单（排除 `is_test` 测试身份），去重升序；
- 编辑：仅「尚无票」时可通过 `poll_manage action='edit'` 修改可见范围；旧版客户端不传该参数时保持原范围不变。

---

## 2. 云端 RPC（全部 `POST {REST}/rpc/<name>`，带班级 token：网页 `X-Device-Id` / 小程序 `X-Class-Token`）

> 所有函数 `SECURITY DEFINER SET search_path = public, private, pg_temp`，`GRANT EXECUTE ... TO anon`。
> 返回均为 jsonb 对象；失败统一 `{ok:false, reason:"中文原因"}`（HTTP 200）。
> 任何返回都**不得包含 sid / 学号**（`owner_sid`、`voter.sid`、`audience.sid` 均不返回）。

### 2.1 `poll_create(p_id text, p_title text, p_description text, p_mode text, p_options jsonb, p_settings jsonb, p_deadline bigint, p_audience text DEFAULT 'all', p_audience_seats jsonb DEFAULT NULL)`

- 需有效班级 token；发起人 = `auth_sid()`，`owner_name` = `private.class_ids.name`；
- 校验：id 规则、标题/说明/选项/规则/图片限制、`deadline=0 或 > now`、可见范围（§1.6）；
- 旧版缓存页面不传 `p_audience`/`p_audience_seats` → 等价「全班」，向后兼容；
- 幂等：同 `p_id` 已存在时直接返回 `poll_detail(p_id)`（网络重试不产生重复投票）；
- 成功：返回 §2.3 `poll_detail` 同结构。

### 2.2 `poll_list()`

```jsonc
{
  "ok": true,
  "now": 1760000000000,
  "polls": [{
    "id": "pabc123", "title": "…", "description": "…", "mode": "quick",
    "owner_name": "管理员", "settings": { … }, "deadline": 1760000000000,
    "status": "open", "closed_at": 0, "created_at": 1760000000000, "updated_at": 1760000000000,
    "audience": "committee", "audience_count": 0,
    "closed": false, "total": 12, "counts": {"o1": 7, "o2": 5},
    "has_voted": true, "my_choices": ["o1"],
    "results_hidden": false, "mine": true, "can_manage": true
  }]
}
```
- 只返回 `deleted=false` 且**当前身份可见**（§1.6：owner / admin / 在范围内）的投票，按 `created_at desc` 最多 100 条；
- `total` 恒为投票人数；`counts` / `results_hidden` 按 §1.4 可见性 + 本人是否已投计算（隐藏时 `counts={}`、`results_hidden=true`）；
- `my_choices` 永远返回本人选择（不受可见性影响，用于回显）。

### 2.3 `poll_detail(p_id text)` 与 `poll_submit(p_id text, p_choices jsonb)` 成功返回

```jsonc
{
  "ok": true, "now": 1760000000000,
  "poll": { "id": "...", "title": "...", "description": "...", "mode": "long",
            "owner_name": "...", "settings": { … }, "options": [ … ],
            "deadline": 0, "status": "open", "closed_at": 0,
            "created_at": 0, "updated_at": 0,
            "audience": "custom", "audience_count": 3,
            "audience_seats": [2, 5, 7] },  // 仅 can_manage 时返回；其他人恒 []
  "closed": false, "total": 12, "counts": {"o1": 7, "o2": 5},
  "has_voted": true, "my_choices": ["o1"], "results_hidden": false,
  "mine": false, "can_manage": false,
  "voters": [ {"name":"张三","choices":["o1"]} ]   // 仅 实名 && 结果可见；否则 []
}
```
`poll_submit` 校验顺序与 reason：
`投票不存在`（含范围外隐藏）/ `身份已失效…` → `不在可见范围内`（仅管理员越权可见时）→ `投票已结束`
→ `选项不合法` / `重复的选项` → `最多选 N 项` / `只能选 1 项` → `已投过票，不可改票`
→ 写入/更新后返回上述结构（含最新 counts，便于立即渲染）。
改票：允许时 upsert 同一行 `(poll_id,sid)`；不允许时已有记录 → `已投过票，不可改票`。

### 2.4 `poll_manage(p_id text, p_action text, p_title text DEFAULT NULL, p_description text DEFAULT NULL, p_options jsonb DEFAULT NULL, p_settings jsonb DEFAULT NULL, p_deadline bigint DEFAULT NULL, p_audience text DEFAULT NULL, p_audience_seats jsonb DEFAULT NULL)`

> `p_deadline`：不传（NULL）= 不修改；`0` = 改为不限时；`>now` = 指定截止。`edit` 要求同时传 title/options/settings/deadline。
> `p_audience`：不传（NULL）= 不修改可见范围（旧版页面兼容）；传 `all|committee|league|custom` = 修改（custom 需 `p_audience_seats`）。

- 权限：发起人本人或管理员（`auth_admin()`）；否则 `{ok:false,reason:"无权管理该投票"}`；
- `action`：
  - `edit`：仅当该投票**尚无任何票**时允许；只更新传入的非 NULL 字段（重新走 §1.3/§1.4/§1.6 校验）；
  - `close`：`status='closed'`、`closed_at=server now`；
  - `extend`：`p_deadline>now` 必要，`status='open'`、`closed_at=0`（同时用于「截止后重开」）；
  - `delete`：`deleted=true`；成功返回 `{ok:true, deleted:true}`（软删后详情已不可查）；
- 其余动作成功返回 `poll_detail(p_id)`。

---

## 3. 网页端（`tools/index.html`，纯增量、零依赖、APP_VER 保持 2.0.0）

### 3.1 入口

- `TOOLS` 追加 `{k:"vote",n:"投票",d:"限时/长时投票 · 自定义标题选项 · 实时结果"}`（放 `water` 后、`ppt` 前）；
- 新增 `<section id="s-vote">`（在 `#s-all` 之前）；`gotoTab("vote")` 挂钩 `VOTE.enter()`，切走时 `VOTE.leave()`；
- 不加入默认 `homeTools`；用户可从「全部」页拖入工具栏（沿用既有拖动 v2，无新增逻辑）；
- 轮询/定时器仅在 `CURTAB==="vote"` 且 `document.visibilityState==="visible"` 时运行，切走/隐藏即停。

### 3.2 列表页

DOM 约定（测试依赖）：
```
#s-vote
  #voteNew / #voteNew2        发起投票按钮（有列表时用 #voteNew，空态用 #voteNew2）
  #voteFilter button[data-vf="open|closed"]   进行中 / 已结束（默认 open）
  #voteList                   卡片容器
  #voteEmpty                  空态（含 #voteEmptyText 文案标签）
  #voteSync                   刷新/状态标签（可选，文案「点击刷新」）
```
卡片 `.vote-card[data-id]`：标题、`发起人 · 状态/截止` 行、标签（单选/多选、匿名/实名、结果可见口径、**可见范围**：
`班委可见` / `团员可见` / `指定 N 人`（`all` 不显示范围标签））、`N 人已投`；点击卡片打开详情。
排序：进行中按截止时间升序（不限时在后）、已结束按 `created_at` 倒序。
空态文案：进行中「还没有进行中的投票」；已结束「没有已结束的投票」。

### 3.3 发起 / 编辑弹层

`#voteCreateOv`（复用 `.modal`），内容：
- `#voteTitle`（input，maxlength 80，placeholder「投票标题」）
- `#voteDesc`（textarea，maxlength 500，placeholder「说明（可选）」）
- 时限选择 `#voteDeadlineType button[data-vdt="quick|long|none"]`（限时 / 指定截止 / 不限时）
  - quick：`#voteQuick button[data-min="5|10|30|60|120"]` 快捷分钟
  - long：`#voteDeadlineInput`（`<input type="datetime-local">`，取本地时区 → epoch ms）
- 选项编辑 `#voteOpts`：每行 `.vote-opt-edit` 含文字 input（maxlength 80）、说明 input（maxlength 200）、
  配图按钮（`input[type=file] accept="image/*"`，压缩后缩略图 + × 移除）、上移/下移/删除；
  `#voteAddOpt` 追加（最多 20，最少 2）；
- 规则：单选/多选 `#voteMulti`（checkbox）；多选时 `#voteMax`（number 2–20）；
  匿名开关 `#voteAnon`；允许改票 `#voteChange`；结果可见 `#voteVis button[data-vis="always|afterVote|afterClose"]`；
- **可见范围**（§1.6）：`#voteAudience button[data-aud="all|committee|league|custom"]`（默认 `all`）；
  选 `custom` 时显示成员选择区 `#voteAudBox`：`#voteAudSearch`（姓名搜索）+ `#voteAudMem` 成员 chips
  （来自班级名单 `D.d.members`，座号 1–70，chips 点按切换选中、点按高度 ≥40px）+ `#voteAudSum` 已选摘要；
  至少选 1 人，否则客户端拦截 `toast("请选择可见成员")`；**界面不显示学号**（chips 只显示姓名，内部用座号）；
- `#voteCreateGo` 提交、`#voteCreateCancel` 取消；
- 默认值：单选、匿名开、允许改票开、结果「投票后可见」、可见范围「全班」；限时默认 30 分钟；
- 编辑复用同一弹层（`VOTE.edit` 预填；仅 `can_manage && total===0` 时列表/详情显示「编辑」入口；
  自定义范围按 `poll.audience_seats` 回填成员选中状态）。

### 3.4 详情弹层 `#voteDetailOv`

- `#voteDetailBody`：标题/说明/发起人/时限标签/规则标签/**可见范围标签**/投票选项/结果条/投票人；
- 未投票：选项可勾选（单选 radio / 多选 checkbox），`#voteSubmit`「提交投票」；
- 已投票且允许改票且未截止：可改选后 `#voteSubmit`「改票」；
- 已投票/截止：选项只读；结果可见时显示百分比条与人数（`.vd-bar` / `.vd-pct`）；实名且可见时显示投票人姓名；
- 结果隐藏时显示标签「投票后可见」/「截止后可见」；
- 管理按钮（`can_manage`）：`data-vm="edit|close|extend|delete"`；
- 截止倒计时每秒更新：`#voteCountdown` 文案 `剩 hh:mm:ss` / `剩 mm:ss` / `已截止`；
- 关闭按钮 `#voteDetailClose`；打开详情时列表轮询降频为 10s，详情内 5s（quick）或 10s（long/不限时）。

### 3.5 文案与视觉红线

- 不写解释性段落，只允许标签/占位符/`<b>`；移动端点按区域 ≥40px；暖白/雾青/灰蓝/暖沙既有 token；
- 投票页不得横向溢出（430 / 390 / 360 宽度）；所有用户输入（标题/说明/选项/姓名）一律 `esc()` 后渲染；
- 导出图片：本期不新增导出（投票结果不导出，避免学号/投票人隐私）；
- 离线/请求失败：列表保持上次数据（内存）+ toast「网络不可用，稍后重试」；不白屏、不抛未捕获异常。

### 3.6 `window.VOTE` 测试探针（仅暴露只读/动作方法）

`VOTE.enter() / leave() / pull(force) / open(id) / closeDetail() / list() / detail() / edit(id)`；
测试脚本通过 DOM 断言为主、探针只作诊断。

---

## 4. 小程序端（`mp-class-tools`，纯增量，版本仍 2.0.0，待用户上传发布）

### 4.1 新增文件与注册

- `pages/vote/vote.{js,json,wxml,wxss}`：列表 + 发起（页面内编辑区或弹层）+ 筛选（进行中/已结束）；
- `pages/votedetail/votedetail.{js,json,wxml,wxss}`：详情/投票/结果/管理；
- `utils/vote.js`：纯逻辑（时间/倒计时/百分比/规则归一/选项编辑/排序/**可见范围归一与标签**，便于 Node 单测）；
- `app.json` `pages` 注册两页；`utils/tools.js` 追加 `{key:'vote',name:'投票',ico:'🗳',icoImg:'/images/tool-vote.png',meta:'限时 · 长时 · 实时结果',desc:'…',url:'/pages/vote/vote'}`；
- 图标 `/images/tool-vote.png`（现有工具图标同风格，尺寸与其它 `tool-*.png` 一致）；
- `utils/cloud.js`：新增配置 `rpc.pollCreate/pollList/pollDetail/pollSubmit/pollManage` 与 5 个封装函数并导出
  （全部走既有 `rpcCall`/`request` 通道，带 `X-Class-Token`，不新增请求通道）。

### 4.2 交互

- 列表页：卡片标题/发起人/倒计时或截止/规则标签/**可见范围标签**/已投人数；进行中在前，支持下拉刷新；无投票空态 + 「发起投票」；
- 发起：标题、说明、时限（5/10/30/60/120 分钟快捷 / 指定日期时间（`picker` date+time）/ 不限时）、
  2–20 个选项（文字 + 可选补充说明 + 可选配图 `wx.chooseMedia` 压缩后 data URL）、单选/多选+最多选几项、
  匿名、允许改票、结果可见口径、**可见范围（全班/班委/团员/指定成员）**；选「指定成员」时展示班级名单多选
  （用 `utils/roster.js` 的 members/座位逻辑或页面内 scroll-view chips，**只显示姓名、内部用座号**，至少 1 人）；
- 详情页：倒计时、选项勾选、提交/改票、结果条、实名投票人、可见范围标签、管理（编辑/提前结束/延长/删除，带确认弹窗）；
- 轮询：页面显示且详情打开时 5s（限时）/10s（长时/不限时）；`onHide` 停止；`onShow` 恢复；
- 分享：每页保留 `onShareAppMessage` / `onShareTimeline` / `share.enable()`（staticcheck 硬要求）；
- 失败兜底：网络失败 toast「网络不可用，稍后重试」，不清空已渲染列表；不出现未捕获异常。

### 4.3 单测（`mp-class-tools-tests`）

- `vote_unit_tests.js`（`run(test)` 形式，挂入 `unit.js`）需新增覆盖：
  可见范围归一（`all/committee/league/custom`、非法值、custom 空座号）、范围标签文案、`buildPayload` 带
  `p_audience/p_audience_seats`、`editorFromPoll` 回填、cloud RPC 请求体包含新字段；
- `node unit.js` 全绿、`python staticcheck.py` 无 MISSING/COMPLAINT、`node code_quality_check.js` 通过。

---

## 5. 验收（交付必跑）

1. `python deploy/cloudbase/apply_sql.py 2026-11-11_polls.sql` + `python deploy/cloudbase/apply_sql.py 2026-11-11_polls_audience.sql` 幂等应用成功；
2. Python 直连 RPC 真实验收（测试身份 + 合成 QA 会话 + 班委/团员/普通成员真实 sid 的一次性会话）：
   创建/列表/详情/投票/改票/多选上限/截止拒绝/匿名不泄露姓名/权限拒绝/幂等创建/**可见范围四种及越权不可见/不可投**，清理测试数据；
3. 网页专项 `python tools/tests/vote_check.py`：mock 云端下列表/创建（含可见范围与成员选择）/详情/投票/改票/管理/倒计时/空态/无横向溢出/0 JS 报错；
4. 网页真实云端 E2E：测试身份登录 → 发起（含可见范围）→ 投票 → 结果 → 删除，清理残留；
5. 回归：`python tools/tests/overflow_check.py 430`、`python tools/tests/v2_ui_check.py` 等既有门禁不回归；
6. 小程序 `node unit.js`（含 vote 单测全绿）、`python staticcheck.py`；
7. 网页备份线上 → `python deploy/sync_tools.py` → OSS 对象字节校验 MATCH；
8. `sync-repos.cmd "feat(vote): …"` 双远端推送（GitHub + Gitee），两端 SHA 一致。

## 6. 红线

- 不引入构建链/外部依赖/外部请求；不改 `APP_VER`（2.0.0）；不动 `me.furina.fun`；
- 任何 RPC 响应、页面、导出物都不得出现学号/手机号/宿舍号；投票人只显示姓名（匿名票不显示姓名）；
  **指定成员范围只用座号存储/回填，页面与 RPC 都不出现学号**；
- `deploy/creds.env`、`tools/cert/`、`deploy/acme_account_key.pem` 照旧禁止读取/外传；
- 投票页不写入 `userdata`/`marks` 等既有同步契约（无新 section），不发多余请求。
