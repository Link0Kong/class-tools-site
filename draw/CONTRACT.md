# 抽签升级 v1 · 存证防作弊 + 自定义序号名称（唯一契约）

> 2026-11-12 · 用户需求：①「抽签导出图片还是会被质疑有作弊」→ 云端存证 + 扫码核验 + **当天抽签次数统计**
> （防止看到不理想结果就重新开一轮）；②「重新将可自定义序号对应的名称功能添加回来（可将序号对应组名等）」。
> 范围：**网页（tools/index.html）+ 小程序源码（mp-class-tools）；安卓本轮不做**。
> 本文件是云端 / 网页 / 小程序 / 测试的唯一真源；实现与本文冲突时以本文为准，需改契约先改本文。

---

## 0. 红线（继承 AGENTS.md，违反即返工）

1. 导出图片/页面**不得出现学号、手机号、宿舍号**；班级名单姓名只能来自本班名单（页面已有逻辑）。
   云端 `draw_records` 只存**序号（号码）+ 自定义名称（组名等）**；不存班级名单姓名。
2. 核验页与记录列表**必须登录（班级身份 token）**才可读；不做公开匿名接口。
3. 网页保持**单文件、零依赖、原生 fetch**；小程序零新依赖；不引 CDN/字体/统计。
4. 记录**不可改**：任何 RPC 都不 UPDATE 已存证记录；唯一例外 = `is_test` 测试记录可由创建它的测试身份清除（测试数据卫生）。
5. 测试/验收**只用测试身份**（`3260799999 / 测试账号` 或 9999 段临时 QA 身份）；真实账号零接触。
6. 所有新增/改动文件最终走 `sync-repos.cmd` 双远端推送；网页部署走 `deploy/sync_tools.py`。
7. APP_VER 仍 `2.0.0`；UD 契约版本仍 v6（只**在既有 `draw` section 内加字段**，不新增顶层 section）。

---

## 1. 数据与云端（唯一实现：`deploy/cloudbase/2026-11-12_draw_proof.sql`）

### 1.1 表（两表对 anon 完全无直连权限：RLS 开启 + 无策略 + REVOKE，仅 SECURITY DEFINER RPC 访问）

```sql
CREATE TABLE public.draw_records (
  id          text PRIMARY KEY,                -- 'd' + 8..31 位 [0-9a-z]（客户端生成，幂等键）
  sid         text NOT NULL,                   -- 操作用户学号（内部；任何 RPC 响应都不返回）
  is_test     boolean NOT NULL DEFAULT false,  -- 由 sid 判定：'3260799999' 或 9999 段 10 位
  at          timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_ms  bigint NOT NULL,                 -- (extract(epoch from at)*1000)::bigint（哈希/展示用）
  day         date NOT NULL,                   -- (at AT TIME ZONE 'Asia/Shanghai')::date
  seq_day     integer NOT NULL,                -- 当天第几次（同 is_test 口径，全表递增）
  params      jsonb NOT NULL,                  -- 归一化参数（见 §1.4）
  pool        jsonb NOT NULL,                  -- 抽签池号码数组（复算用）
  result      jsonb NOT NULL,                  -- 抽取顺序结果号码数组
  labels      jsonb NOT NULL DEFAULT '[]',     -- 自定义名称命中结果 [{n,nm}]（≤300）
  seed        text NOT NULL,                   -- 16 位小写 hex
  algo        text NOT NULL DEFAULT 'draw-v1',
  prev_hash   text NOT NULL DEFAULT '',        -- 链上前一条 hash（全表，按 (at,id) 前一条）
  hash        text NOT NULL,                   -- sha256(canon) 64 位 hex
  CONSTRAINT draw_records_id_chk    CHECK (id ~ '^d[0-9a-z]{8,31}$'),
  CONSTRAINT draw_records_day_chk   CHECK (seq_day >= 1),
  CONSTRAINT draw_records_seed_chk  CHECK (seed ~ '^[0-9a-f]{16}$'),
  CONSTRAINT draw_records_algo_chk  CHECK (algo = 'draw-v1')
);
CREATE INDEX draw_records_day_idx  ON public.draw_records (day DESC, seq_day DESC);
CREATE INDEX draw_records_at_idx   ON public.draw_records (at DESC, id);

CREATE TABLE public.draw_events (
  record_id text NOT NULL REFERENCES public.draw_records(id) ON DELETE CASCADE,
  seq       integer NOT NULL,                  -- 从 1 起
  kind      text NOT NULL,                     -- remove | refill | sort | reset
  n         integer,                           -- 被剔除号码
  added     integer,                           -- 补抽号码
  note      text NOT NULL DEFAULT '',
  at        timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_ms bigint NOT NULL,
  prev_hash text NOT NULL DEFAULT '',
  hash      text NOT NULL,
  PRIMARY KEY (record_id, seq),
  CONSTRAINT draw_events_kind_chk CHECK (kind IN ('remove','refill','sort','reset'))
);
```

### 1.2 哈希规范（服务端计算；网页核验页可复算）

- `canon = concat_ws(E'\n', 'v1', id, created_ms::text, day::text, seq_day::text, algo, seed,
  prev_hash, params::text, pool::text, result::text, labels::text)`（`jsonb::text` 为 PostgreSQL 规范文本）
- `hash = encode(digest(canon,'sha256'),'hex')`（pgcrypto；幂等 `CREATE EXTENSION IF NOT EXISTS pgcrypto`）
- 事件：`ev_canon = concat_ws(E'\n','e1',record_id,seq::text,kind,coalesce(n::text,''),
  coalesce(added::text,''),note,created_ms::text,prev_hash)`；`ev_prev = 上一条事件 hash`（无则 record.hash）。
- `draw_record_get` 必须返回 `canon`（与存库时逐字节一致）供网页 `crypto.subtle.digest('SHA-256')` 自检。

### 1.3 RPC（全部 SECURITY DEFINER，`SET search_path = public, private, pg_temp`；`GRANT EXECUTE ... TO anon`）

统一：先 `IF NOT public.auth_ok() THEN RETURN {ok:false,reason:'身份已失效，请重新进入班级'}`；`sid=public.auth_sid()`；
`is_test := (sid='3260799999' OR (sid ~ '^9999[0-9]{6}$'))`。

1) `draw_record_create(p_id text, p_params jsonb, p_pool jsonb, p_result jsonb, p_labels jsonb, p_seed text, p_algo text DEFAULT 'draw-v1') → jsonb`
   - 幂等：同 id 已存在且 `sid` 相同 → 直接返回 `draw_record_get(id)`；sid 不同 → `{ok:false,reason:'记录编号冲突'}`。
   - 校验：id/seed/algo 见 CHECK；params/pool/result/labels 服务端**白名单归一**（见 §1.4）；
     pool 长度 1..1000、元素 0..99999 去重升序（同一号码不得重复）；result 元素必须 ∈ pool；
     dup=false 时 result 长度 = count 且互不重复；dup=true 时 result 长度 = count。
   - 事务内 `PERFORM pg_advisory_xact_lock(hashtext('public.draw_records'))` 取当天序号：
     `v_day := (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date`；
     `v_seq := count(*)+1 FROM draw_records WHERE day=v_day AND is_test=v_is_test`；
     `v_prev := coalesce((SELECT hash ... ORDER BY at DESC, id DESC LIMIT 1), '')`（同 is_test 口径链）。
   - 返回 `{ok:true, today_count:<int>, today_mine:<int>, record:{...公开视图...}}`（公开视图见 §1.3-3）。
   - 异常兜底 `{ok:false,reason:'存证失败，请重试'}`（不泄露 SQL 细节）。

2) `draw_event_append(p_id text, p_kind text, p_n integer DEFAULT NULL, p_added integer DEFAULT NULL,
   p_note text DEFAULT '') → jsonb`
   - 仅记录的 `sid`（本人）可追加；record 不存在/不可见 → `{ok:false,reason:'记录不存在'}`。
   - `kind` 白名单；`note` ≤120 字符（超出截断）；`seq=max(seq)+1`；算事件 hash/prev。
   - 返回 `{ok:true, event:{...}, event_count:<int>}`。

3) `draw_record_get(p_id text) → jsonb`（登录 + `is_test` 匹配才可见；**不返回 sid**）
```json
{"ok":true,"record":{
  "id":"d...","at":1763000000000,"day":"2026-11-12","seq_day":3,
  "today_count":7,"today_mine":2,"is_mine":true,
  "op_name":"张三","op_seat":12,
  "params":{"range":[1,70],"count":10,"dup":false,"excl":[],"sort":"draw","rosterN":0,"namesN":0},
  "pool":[1,2,3],"result":[5,9,2],"labels":[{"n":5,"nm":"第一组"}],
  "seed":"0123456789abcdef","algo":"draw-v1",
  "hash":"...64","canon":"...","prev_hash":"",
  "event_count":2,
  "events":[{"seq":1,"kind":"remove","n":5,"added":12,"note":"","at":1763000001000,
             "hash":"...","prev_hash":"..."}]
}}
```
   - `op_name`/`op_seat` 来自 `private.class_ids`（left join sid；取不到给 ''/null）。
   - `today_count` = 当天同 `is_test` 口径全表条数；`today_mine` = 当天本人条数。
   - 记录不可见（含 is_test 不匹配）→ `{ok:false,reason:'记录不存在'}`。

4) `draw_record_list(p_scope text DEFAULT 'today', p_limit integer DEFAULT 30) → jsonb`
   - `p_scope`：`'today'` | `'all'` | `'YYYY-MM-DD'`（其它 → `'today'`）；`p_limit` 1..100。
   - 只返回与调用方 `is_test` 同口径的记录；`today` 按 `seq_day DESC`，其它 `at DESC, id DESC`。
   - 返回 `{ok:true, scope, day:<本地今天>, today_count, today_mine, records:[摘要]}`；
     摘要字段 = `id, at, day, seq_day, params, result, labels, hash, event_count, is_mine, op_name, op_seat`
     （**不含** seed/pool/canon/events）。

5) `draw_test_purge(p_id text) → jsonb` / `draw_test_clear() → jsonb`
   - 仅 `is_test=true` 记录、且 `sid=auth_sid()`；硬删（events 级联）；返回 `{ok:true,deleted:<int>}`。
   - 仅用于 QA/自动化测试数据清理；真实用户调用 → `{ok:false,reason:'仅测试身份可清理'}`。

### 1.4 params 归一（服务端从入参重建，未知键丢弃，保证 canon 确定）

```json
{"range":[lo,hi],"count":n,"dup":false,"excl":[...],"sort":"draw","rosterN":0,"namesN":0}
```
- `range`：两个整数 0..99999，lo≤hi；`count` 1..1000；`dup` boolean；`excl` 整数数组 ≤200（去重升序）；
  `sort` ∈ `draw|num|desc|rand`；`rosterN` 0..70；`namesN` 0..300。
- `labels`：`[{"n":<int>,"nm":"<1..40 字>"}]`，长度 ≤300，`n` 必须 ∈ result，按 n 升序去重（后值覆盖）。
- 超出/非法 → 明确中文 reason（如 `参数不合法` / `抽签池不合法` / `结果不合法` / `名称映射不合法`）。

### 1.5 测试数据卫生

- 测试身份创建的全部记录 `is_test=true`：真实用户 list/get 一律看不到，也不计入真实今日次数。
- 每个云端测试脚本 `finally` 里 `draw_test_clear()`（或逐条 purge），不允许把测试记录长期留在云端。

---

## 2. 抽签算法（网页/小程序/核验页三处逐字节一致）

- `algo = "draw-v1"`；`seed` = 8 字节随机数 → 16 位小写 hex（网页 `crypto.getRandomValues`，
  小程序 `wx.getRandomValues`/Math.random 兜底）。
- PRNG（mulberry32 的 uint32 显式版，**跨端必须逐字一致**）：

```js
function seededInts(seedHex){
  var s = parseInt(seedHex.slice(0,8),16) >>> 0;
  function next(){
    s = (s + 0x6D2B79F5) >>> 0;
    var t = s;
    t = Math.imul(t ^ (t >>> 15), (t | 1)) >>> 0;
    t = (t ^ ((t + Math.imul(t ^ (t >>> 7), (t | 61))) >>> 0)) >>> 0;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  return function(m){ return Math.floor(next() * m); };
}
```
- `dup=false`：`p = pool.slice()`；`for(j=p.length-1;j>0;j--){ r=int(j+1); swap(p[j],p[r]); }`；取 `p.slice(0,count)`。
- `dup=true`：`for(k=0;k<count;k++) res.push(pool[int(pool.length)])`。
- **固定测试向量**（两端口径必须一致，写进单测）：
  - seed `0123456789abcdef`, pool `[1..10]`, count 3, dup=false → `[9,10,4]`
  - seed `0123456789abcdef`, pool `[1,2,3,4,5]`, count 7, dup=true → `[1,3,1,2,2,2,3]`
  - seed `deadbeefcafebabe`, pool `[1..70]`, count 10, dup=false → `[28,36,11,34,38,1,14,70,65,46]`
  - seed `a1b2c3d4e5f60718`, pool `[1..8]`, count 8, dup=false → `[7,3,1,8,4,5,2,6]`
- 抽签池语义不变：`pool = [范围−排除]`；选了参与名单再 `∩ rosterSel`；映射不改变 pool。
- 「排序（从大到小/从小到大/随机打乱）」只改显示顺序，不改变结果集合，**不记事件**；
  `result` 存的是**抽取顺序**（初始算法输出），剔除/补抽走事件。
- 核验页复算：`draw-v1(seed, pool, count, dup)` 必须逐元素等于 `record.result`，否则显示「复算不一致」。

---

## 3. 网页（tools/index.html）

### 3.1 自定义序号名称映射（「名称映射」）

- 数据：`D.d.draw.names`（string，每行 `序号 名称`，如 `1 第一组`；空 = 未设置）。
  - 解析：按行；`/^(\d{1,4})\s*[.,、:：=\-]?\s*(.+)$/` 命中 → 该序号；未带序号 → 用「非空行序号」自增；
    名称 trim 后 1..40 字；同序号后值覆盖；最多 300 项；保存时归一为升序 `num name` 行。
  - `nameOf(n)` 优先级：`draw.names` 映射 > 班级名单派生名 > `''`（原来 `rosterMap` 逻辑保留兜底）。
- UI：STEP1 参与名单行加按钮「名称映射」（`#aNamesBtn`）+ 摘要 `#aNamesSum`（`N 项` / `未设置`）。
  点开弹层 `#nmModal`：标题「名称映射」、说明一行（`每行：序号 名称`）、textarea `#nmText`、
  `#nmCount`（`已映射 N 项`）、按钮 `清空 / 取消 / 保存`。Esc / 遮罩 = 取消；保存写回并重绘结果。
- 抽签结果 chips 显示名称；导出参数加 `["名称映射","N 项"]`（N>0 时）；`labels` 只传命中结果的 `{n,nm}`。
- 同步：`UD_DRAW_KEYS` 追加 `"names"`；`UD.sections().draw.names = String(draw.names||"")`；
  `UD.apply` 应用后刷新映射摘要；小程序同步同字段（§4）。旧数据无该字段按空。

### 3.2 存证与「今日抽签次数」

- 每次点「开始抽签」（`doDraw()` 成功）→ 生成 `recordId = 'd'+base36(now)+rand4`、`seed`、按算法出结果，
  立即 `rpc/draw_record_create`（异步，页面不阻塞）。每次点击 = 一条记录 = 今日次数 +1（**这是本需求核心**）。
- 状态 `A.proof`：`null`（未抽）| `{status:'pending'}` | `{status:'ok',record:{...}}` | `{status:'failed',reason}`。
- 结果区显示一行：`已存证 · 今日第 N 次（全班今日共 M 次）` 或 `存证中…` / `未存证（网络不可用）`。
- `draw_event_append` 时机（失败静默，仅影响时间线，不阻塞）：
  - `removeFlow()` 剔除 → `kind:'remove', n:<剔除号>, added:<补抽号或 null>`（自动重抽时补抽号码写入 events）；
  - 「重置本轮」在清空结果前 → `kind:'reset'`（若 A.proof 已存在）。
- 抽签记录入口：STEP1 `#aRecBtn`「抽签记录」→ 弹层 `#recModal`：
  - 顶部 `今日第 N 次 · 全班共 M 次`；`今日 / 全部` 两个筛选；列表项 = `HH:MM 第seq次 · 范围抽N个 · 结果摘要 · 操作人 · 查看核验`；
  - 点击项 → 记录详情/核验视图（同 §3.4，列表内切换返回）。
- 深链：`#verify=<id>`（登录后生效）→ 拉 `draw_record_get` 打开详情；记录弹层打开时 `history.pushState` 支持返回关闭。
- 跨端核心模块放新块 `/* ===== __DRAW_PROOF_V1__ ===== */`（CSS 在 `</style>` 前、HTML 弹层在 `#toast` 前、
  JS 在抽签块后），`window.DRAWPROOF` 只读探针（id/state/replay/labels 供测试）。

### 3.3 导出图片（走 `exportCard()`，规格 §6）

- 已存证：`rec = record.id`（页脚编号 = 存证编号）；参数区加：
  `["存证编号", id]`、`["存证时间", "YYYY-MM-DD HH:MM:SS"]`、`["今日抽签", "第 N 次（今日共 M 次）"]`、
  `["记录哈希", hash.slice(0,16)]`；QR：
  `qr = verifyUrl(id)`（`location.origin` 属本站域名时用 origin，否则 `https://tool.furina.fun` + `/#verify=<id>`）；
  `qrTitle="抽签存证核验"`、`qrCap="扫码核验本次抽签记录（需登录班级身份）"`；
  `qrNote` 3 行：`["存证编号 "+id, "记录哈希 "+hash.slice(0,12), "今日第 "+seq_day+" 次 · 共 "+today_count+" 次"]`。
- 未存证（pending 超过约 6s / failed）：不加 QR；参数区加 `["存证","未存证（网络不可用）"]`；`rec` 回退 `recId("DRAW")`；
  导出前 toast 提示「本次未存证，图片无法核验」。
- 剔除重抽明细：`qrNote` 被存证信息占用后，原「剔除重抽」明细改放**纯文本块**（`blocks` 末尾，`label:"剔除重抽"`，
  只列 `#i 剔除 x → 补抽 y`，最多 8 行，超出省略），不得丢信息。

### 3.4 核验视图（登录后、记录详情）

依次展示（只读，无输入）：
1. `存证编号 / 存证时间（服务器）/ 抽签人（姓名 + 座号）/ 今日第 N 次（全班共 M 次）`
2. 参数（范围/个数/允许重复/排除/参与名单 N 人/名称映射 N 项）
3. 初始抽取结果 chips（有自定义名称则带名称；班级名单姓名在登录后本地解析，不进云端）
4. 剔除重抽时间线（events）
5. 算法自检：`算法 draw-v1 · 种子 <seed>` + `复算 <✓/✗>`；`哈希 <hash>` + `哈希自检 <✓/✗>`
   （网页用 `crypto.subtle.digest('SHA-256', TextEncoder(canon))` 与 record.hash 比对）
6. 二维码（同导出图 URL）+「复制核验链接」
全部数据来自 `draw_record_get`；**任何错误/不存在**给中文提示，不暴露存在性细节以外的信息。

---

## 4. 小程序（mp-class-tools 源码；需用户上传发布后生效）

- `utils/drawproof.js`（新增）：`drawV1(seed,pool,count,dup)`（§2 逐字一致）、`parseNames/nameMap`（§3.1 规则）、
  `labelsOf(names,result)`、`newRecordId/newSeed`、`verifyUrl(id)`、RPC 封装（`draw_record_create`/`draw_event_append`/
  `draw_record_get`/`draw_record_list`；用 `utils/cloud.js` 统一 header/token）。
- `pages/draw`：名称映射弹层 + 摘要；`nameOf` 优先级同网页；每次抽签创建存证并显示 `今日第 N 次` 状态；
  剔除/补抽/重置追加事件；导出图带二维码（`utils/canvas.js` 已支持 `qr/qrNote`，需支持可选 `qrTitle/qrCap`），
  `rec = record.id`；新增入口「抽签记录」。
- `pages/drawrec`（新增页，`app.json` 注册）：今日/全部列表 + 记录详情（参数/结果/时间线/哈希/二维码/复制链接）；
  `?id=<recordId>` 直接打开详情；不显示学号。
- 同步：`utils/store.js` 默认 `draw.names:''`；`utils/privacy.js` DEFAULTS draw 加 `names:''`；
  `utils/cloud.js` `udSections().draw.names` 与 `udApply` 应用；`sync_contract_test.js` 夹具同步更新。
- 小程序二维码 URL：优先 `utils/cloud-config.js` 新增 `webBase`（`https://tool.furina.fun`，
  `verifyUrl(id)=webBase+'/#verify='+id`；2026-11-14 起固定该值，不再使用临时域名）。
- 导出命名/版式/水印/编号规则不变；图片里 No 学号。

---

## 5. 测试与验收（必须真实跑过、贴输出）

### 5.1 云端（`tools/tests/draw_cloud_check.py`，新建；只允测试身份）

真实 CloudBase API：create（校验/幂等/中文 reason）、今天 seq_day 递增、today_count/today_mine、list（today/all/日期）、
get（canon+hash 格式、无 sid 字段）、event append（hash 链、seq 递增）、is_test 隔离（真实名单不可见=用测试身份模拟同一口径）、
直连表 401、`draw_test_clear` 清理（finally 必清）。全部断言数 ≥ 40。

### 5.2 网页 mock UI（`tools/tests/draw_proof_check.py`，新建）

本地 HTTP + headless Edge + mock 身份（测试身份）+ mock `/rpc/draw_*`（含正确 canon/hash，Python 用同规范算 SHA-256）：
名称映射弹层解析/保存/名称优先级/导出含映射；存证 create 请求体（params/pool/result/seed/labels/algo）+ 今日次数显示；
导出图 rec=记录 id / config 行 / QR 内容 / qrTitle/qrCap；记录弹层今日/全部 + 详情；`#verify=` 深链；
哈希自检 ✓、复算 ✓；失败降级「未存证」；360/390/430 无横向溢出；0 JS 报错；0 外部请求（仅 localhost）。
断言 ≥ 60。

### 5.3 小程序

`node unit.js`（新增 `drawproof_unit_tests.js`：算法 4 向量、映射解析、payload、记录视图）+ `sync_contract_test.js`
（draw.names 合并/换端）+ `staticcheck.py` exit 0 + `code_quality_check.js` exit 0；如可，automator 预览脚本覆盖
「名称映射→抽签→存证状态→记录页」mock 场景（截图存档）。

### 5.4 回归（网页）

`export_check.py draw`、`roster_check.py`（199）、`sync_check.py`（更新 draw.names 后期望全绿）、`v2_ui_check.py`、`overflow_check.py 430`、
`selfcheck.py`（按现状说明）、`v2_drag_check.py` 等与抽签无关的保持全绿；有改动期望值必须在测试内注释说明。

### 5.5 独立验收

QA（fresh context）另写报告 `验收报告/抽签存证与名称映射_独立验收_20261112.md`：功能项逐条 PASS/FAIL、断言数、
真实云端 E2E（测试身份：界面抽签→创建存证→记录列表→核验页哈希/复算 ✓→清理）、0 P0/P1，P2 如实列出。

---

## 6. 导出卡 v2 增量（spec 同步改 `tools/tests/export_card_v2_spec.md`）

- `exportCard(o)` / 小程序 `drawCard` 新增**可选**：`o.qrTitle`（默认「剔除重抽记录」）、`o.qrCap`（默认原说明文字）。
- 其余版式/尺寸/水印/页脚/编号规则**不变**；二维码仅在传入 `o.qr` 时绘制。
- 抽签导出改为「存证核验」二维码（§3.3），其它导出（分组/课表/作业/体测/结果单）不受影响。

---

## 7. 文件所有权（并行写作用）

| 范围 | 负责人 | 允许改 |
|---|---|---|
| `web/tools/index.html`、`web/tools/tests/export_card_v2_spec.md`、`web/draw/CONTRACT.md`、`web/AGENTS.md`/`CHANGELOG.md`/`HANDOFF.md`、部署/提交 | Lead | 全部 |
| `web/deploy/cloudbase/2026-11-12_draw_proof.sql`、`web/tools/tests/draw_cloud_check.py`、`web/CLOUDBASE.md` 抽签节 | cloud-worker | 仅这些文件 |
| `mp-class-tools/**`、`mp-class-tools-tests/**` | mp-worker | 仅这两个目录 |
| `web/tools/tests/draw_proof_check.py`、`web/tools/tests/draw_live_check.py`、`web/tools/tests/_draw_qa/**`、独立验收报告 | qa | 仅这些文件 |

**冲突规则**：同一文件只能一个 owner 写；需要别人文件时发消息请求，不直接改。

---

## 8. 部署 / 回滚

1. 云端：`cd web/deploy/cloudbase && python apply_sql.py 2026-11-12_draw_proof.sql`（幂等）。
2. 网页：`tools/_backup/index_online_<时间>_preDrawProof.html` 备份线上 → `python deploy/sync_tools.py` →
   `python deploy/oss_object.py check index.html` MATCH → `python deploy/ecs_site.py verify`（或等价）MATCH。
3. 小程序：源码交付，**用户上传发布后生效**；`webBase` 固定 `https://tool.furina.fun`（仅二维码链接用，不必加入微信 request 合法域名；**2026-11-23 备案通过 + HTTPS 启用后核验链接已可用**）。
4. 回滚：网页重传备份；SQL 见迁移文件头 `DROP FUNCTION ... / DROP TABLE draw_events / draw_records`；小程序回退源码。
