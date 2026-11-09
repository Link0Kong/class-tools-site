# CLOUDBASE.md — 云端作业板（给 ZCode 的配置结果）

> 交接人：芙宁娜 ｜ 目的：把「作业」从**纯本机 localStorage** 升级为**云端共享**，
> 实现 **登录后可发布 · 发布后所有设备同步**。
> 上手顺序：`AGENTS.md` → `HANDOFF.md` → 本文件。
> **本文件是 2026-10-10 的真实配置结果，已经端到端实测通过。**

---

## 0. 2026-11-04 身份系统重构（当前有效）

> ⚠️ 本文后续「账号/密码登录」「X-Device-Id: 账号|hash」「identity_verify」等旧说明已废弃，仅作历史参考。

### 0.1 入口与身份

- 网页与微信小程序启动后都先进入**身份界面**：输入「学号 + 姓名」。
- 前端只调用 `class_verify`，不再有注册、密码、旧管理员账号、`users` 表。
- 验证通过后云端签发 30 天 token；**所有班级数据请求都必须带 token**：
  - 网页：`X-Device-Id: <token>`（CloudBase 网关 CORS 白名单只允许这个自定义头）
  - 小程序：`X-Class-Token: <token>`（`wx.request` 无浏览器 CORS）
  - 服务端 `public.auth_hdr()` 同时接受这两个头。
- token 失效后页面会重新回到身份门禁；客户端不保存密码。

### 0.2 RPC

```http
POST {REST}/rpc/class_verify
Authorization: Bearer <PUBLISH_KEY>
Content-Type: application/json

{"p_sid":"3260707024","p_name":"陈子麒"}
```

成功：

```json
{"ok":true,"token":"…","sid":"3260707024","name":"陈子麒","role":"副团支部书记","badge":"班委","is_admin":true}
```

失败：`{"ok":false,"reason":"姓名或学号不在班级名单中"}`。

登录后拉名单：

```http
POST {REST}/rpc/class_members
X-Device-Id: <token>     # 或小程序 X-Class-Token
Content-Type: application/json

{}
```

返回 70 人：`[{seat,sid,name,role,badge,is_admin}]`。名单只来自云端，**不进公开 HTML**。

管理员改班委职务：

```http
POST {REST}/rpc/class_set_role
X-Device-Id: <token>
{"p_sid":"…","p_role":"副团支书","p_badge":"班委"}
```

### 0.3 数据与权限

| 资源 | 说明 |
|---|---|
| `private.class_ids` | 班级名单：`seat,name,sid,role,badge,is_admin`；70 人，来自官方花名册；其中 18 名班委按 2026 级班委会拟定结果导入 |
| `private.class_sessions` | token 会话（sid/name/expires_at），不对外暴露 |
| `public.homework` / `notices` | 共享作业/通知；RLS 要求有效 token |
| `public.marks` / `fitrecs` / `userdata` | 按 sid 读写的个人状态；RLS 只允许本人 |
| `public.roster` | 旧名单表（保留兼容；前端已改用 `class_members`） |
| `public.visits` | 访问统计，新增 `sid,name`；按账号聚合，仅管理员可读 |
| `public.feedback` | 反馈；登录用户可写，管理员可读 |

- 管理员：**陈子麒 / 3260707024**（`is_admin=true`）。
- 旧账号映射：`admin → 3260707024`，`xsx/xzx → 谢梓萱 3260707026`（数据行已迁移）。
- 旧 `public.users`、`public.identity_verify` 已删除；`public.roster` 保留但不再作为身份来源。
- 网页课表仍从同源静态 `tools/tt.json` 读取（2026-11-03 设计）；页面只在身份通过后请求它。

### 0.4 前端契约

```js
// 网页
const ID = JSON.parse(localStorage.getItem('zq_class_identity') || 'null');
// 请求头：{ 'X-Device-Id': ID.token }
// 小程序
// { 'X-Class-Token': token }
```

身份页成功后才调用 `homework/notices/marks/fitrecs/class_members/tt.json`；身份页之前不发送班级数据请求。

---

## 1. 结论（一句话）

云端后端**已经配好了**，前端只需要**原生 `fetch()`**：

```
POST https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/homework
Authorization: Bearer <PUBLISH_KEY>
```

**不引入任何 SDK、不加 `<script src>`、不加 npm、不改 `<head>`。**
界面层（HTML/CSS/交互）**一行都不用改**，只把「作业」的数据层换成云端读写。

---

## 2. 云端配置结果

| 项目 | 值 |
|------|-----|
| 云厂商 | 腾讯云 CloudBase（云开发）· 个人版 |
| 环境 envId | `tool-d4gosudok46e0e081` |
| 地域 | `ap-shanghai` |
| 数据库 | **PostgreSQL**（⚠️ 该环境**没有**文档型数据库，别写 `db.collection()`） |
| 表 | `public.homework` |
| 接口根（REST） | `https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/homework` |
| 鉴权 | `Authorization: Bearer <PUBLISH_KEY>` |
| 角色 | `anon`（行级安全 RLS 控制权限） |
| 安全来源 / CORS | `tool.furina.fun`（已放通，预检 204 实测通过） |
| 云函数 | 已删除（没用上，方案更简单了） |

### PUBLISH_KEY（放进前端代码，这是**设计上就公开**的凭据）

```
eyJhbGciOiJSUzI1NiIsImtpZCI6IjkwMTNkMzBkLWY3NTEtNGE4Yi05OGNlLTlmNTFiMzk3ZDdjNyJ9.eyJpc3MiOiJodHRwczovL3Rvb2wtZDRnb3N1ZG9rNDZlMGUwODEuYXAtc2hhbmdoYWkudGNiLWFwaS50ZW5jZW50Y2xvdWRhcGkuY29tIiwic3ViIjoiYW5vbiIsImF1ZCI6InRvb2wtZDRnb3N1ZG9rNDZlMGUwODEiLCJleHAiOjQwOTUyNzY4ODAsImlhdCI6MTc5MTU5MzY4MCwibm9uY2UiOiItdGJncVVhcVNZS25jNUx0VmZ2QWZRIiwiYXRfaGFzaCI6Ii10YmdxVWFxU1lLbmM1THRWZnZBZlEiLCJuYW1lIjoiQW5vbnltb3VzIiwic2NvcGUiOiJhbm9ueW1vdXMiLCJwcm9qZWN0X2lkIjoidG9vbC1kNGdvc3Vkb2s0NmUwZTA4MSIsIm1ldGEiOnsicGxhdGZvcm0iOiJQdWJsaXNoYWJsZUtleSJ9LCJyb2xlIjoiYW5vbiIsImlzX2Fub255bW91cyI6dHJ1ZSwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiYW5vbnltb3VzIiwicHJvdmlkZXJzIjpbImFub255bW91cyJdfSwidXNlcl9tZXRhZGF0YSI6eyJuYW1lIjoiQW5vbnltb3VzIn0sInVzZXJfdHlwZSI6IiIsImNsaWVudF90eXBlIjoiY2xpZW50X3VzZXIiLCJpc19zeXN0ZW1fYWRtaW4iOmZhbHNlfQ.Iyf827jPzSxTtY6l9tjeRSWG0DVkU8a-sqOcg43b0sP-4CuykUQ_2DpIm3vQSd6t9gDjQRsODpuQzZt4X2iabRr7eahQnB5UFjNuHWBJYtg9O1IZSdx1qfiyQ9NHLHLMOGQKw95E5qhqEs-tQXu-FbASsAl4Y-O_ssL3_OrwFP6qUWfLRb53D0X5gqkumEaKvf-hHhSlyFCzOImKdTKnoI-Qr_N-xa3_WE1AWjGXC_5lo8BhsxZFrGXrkp90eB1kT4303lPA_bzuzP1RXHdrNRmJRbobZmOUUa3k8SoqoeSrizQxCSaL-1oyhZZBFn_zBMpN7wGw0H2uC8I-NTE5Vg
```

> 这是 **Publishable Key**（JWT 里 `role: anon`、`platform: PublishableKey`），
> 官方定义就是给前端用的公开凭据；能做什么完全由 RLS 决定。
> 真正不能进前端的是 `--type api_key` 那种服务端密钥（本项目没有创建）。
> 原始文件也在 `deploy/cloudbase/publish_key.txt`。

---

## 3. 表结构 `public.homework`

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | text PK | 由前端生成，建议 `Date.now().toString(36) + Math.random().toString(36).slice(2,8)` |
| `subject` | text 非空 | 科目 |
| `content` | text 非空 | 作业内容 |
| `due` | text | 截止（展示用，如 `10-12`） |
| `date` | text | 截止日期 `YYYY-MM-DD`；不设 `time` 时按当天 `00:00` 截止（2026-10-22 调整） |
| `time` | text | 截止时间 `HH:MM`，可选（2026-10-22 新增） |
| `author` | text | 发布者昵称（自由填） |
| `owner` | text | 发布者账号（2026-10-20 新增；用于“只有管理员/发布者可全局删除”） |
| `attachments` | text | 图片/文件附件 JSON 字符串（2026-10-20 新增；图片原图 ≤5MB（自动压缩）、文件 ≤2MB，最多 2 个） |
| `done` | boolean | 完成标记 |
| `archived` | boolean | 软删除标记（预留） |
| `ts` | bigint | 毫秒时间戳（排序/增量用，由前端给） |

**权限边界（RLS，已实测）**
- ✅ anon 可 **SELECT / INSERT / UPDATE**
- ❌ anon **不能 DELETE**（`401 DATABASE_42501 permission denied for table homework`）
- 「删除」只能：把 `archived` 置 `true` 做软删除，或走 CLI/控制台由管理员真删。

---

## 4. 接口契约（照抄即可）

统一 header：

```js
const BASE = 'https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/homework';
const KEY  = '<上面那把 PUBLISH_KEY>';
const H = { 'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json' };
```

### 4.1 拉列表

```js
const r = await fetch(BASE + '?select=*&order=ts.asc&archived=eq.false', { headers: H });
const list = await r.json();   // [{id,subject,content,due,date,author,done,archived,ts}, ...]
```
- 返回就是**数组**（不是 `{ok,list}` 那种包一层）。
- 空表返回 `[]`。
- 失败时返回 `{code,message,requestId}` 且 HTTP 非 2xx —— 判断 `r.ok`。

### 4.2 发布（**任何人可发**）

```js
await fetch(BASE, {
  method: 'POST',
  headers: { ...H, 'Prefer': 'return=representation' },
  body: JSON.stringify([{ id, subject, content, due, date, author, done: false, archived: false, ts: Date.now() }])
});
// 201，body 带回插入后的整行
```
> body **必须是数组**（PostgREST 批量语义），即使只插一条。

### 4.3 标记完成 / 取消

```js
await fetch(BASE + '?id=eq.' + encodeURIComponent(id), {
  method: 'PATCH',
  headers: { ...H, 'Prefer': 'return=representation' },
  body: JSON.stringify({ done: true })
});
// 200 + 该行
```

### 4.4 软删除（可选）

```js
await fetch(BASE + '?id=eq.' + encodeURIComponent(id), {
  method: 'PATCH', headers: { ...H, 'Prefer': 'return=representation' },
  body: JSON.stringify({ archived: true })
});
```
> 注意：anon 的 update 策略是 `using(true) with check(true)`，也就是**任何人能改任何行**。
> 这是「任何人可发布」的必然代价；如果你觉得风险大，就别在前端放删除/编辑入口，
> 只保留「发布 + 勾选完成」。
>
> 2026-10-20 起前端按 `owner`（发布者账号）控制入口：只有管理员或发布者显示「删除」
> （软删 `archived=true`，所有人不可见）；其他人只显示「隐藏」，只写本机 `hwHide/ntHide`。
> `owner` 列已通过 `alter table ... add column if not exists owner text default ''` 添加；
> 旧行 `owner` 为空时回退比较 `author` 与当前账号，仍不匹配的只有管理员能删。
>
> 2026-10-20 附件：`homework.attachments` / `notices.attachments` 为 JSON 字符串，
> 数组元素 `{n:文件名, t:MIME, s:字节数, d:base64}`。前端限制最多 2 个；图片原图 ≤5MB 自动压缩、文件 ≤2MB；
> 图片在网页内预览、其他文件可下载/用系统应用打开。小程序端用 `chooseMedia/chooseMessageFile`
> 读取后同样以 base64 上云，附件随行同步。

### 4.5 登录（座号）与个人状态 marks（2026-10-10）

- 前端「登录」＝输入座号（无密码），存本地 `D.d.seat`；左上角图标进入/退出；
- 登录后作业「完成」、通知「置顶」按**座号**云端同步：表 `public.marks`，
  `id = "<seat>|<kind>|<ref>"`（kind=`hw`/`nt`，ref=行 id），
  写入用 upsert：`POST /v1/rdb/rest/marks` + `Prefer: return=representation,resolution=merge-duplicates`；
  拉取 `GET /v1/rdb/rest/marks?select=*&seat=eq.<座号>`；
- 未登录时完成/置顶仍只存本机（`D.d.hwDone` / `D.d.ntPin`）；
- 登录且发布昵称为空时，作者自动填座号；
- 列名用 `val` 而非 `on`（`on` 是 SQL 保留字，建表会失败）。

---

## 5. 前端改造建议（**界面零改动**）

现在 `tools/index.html` 里：「作业」由 `D.d.homework[]` 驱动，渲染在 `renderHW()` / `hwArr()` / `hwBlocks()` / `dueInfo()`。

**加一个 `HW` 小模块**（同文件内、纯原生 fetch，样式/结构都不动）：

```js
const HW = {
  online: false,
  async pull() {
    try {
      const r = await fetch(BASE + '?select=*&order=ts.asc&archived=eq.false', { headers: H, cache: 'no-store' });
      if (!r.ok) throw new Error('http ' + r.status);
      const list = await r.json();
      D.d.homework = list.map(x => ({
        id: x.id, subject: x.subject, content: x.content, due: x.due,
        date: x.date, author: x.author, done: !!x.done, ts: Number(x.ts) || 0
      }));
      D.save(); HW.online = true; renderHW();
    } catch (e) { HW.online = false; }        // 失败静默退回本地缓存
  },
  async publish(item) { /* POST 数组，成功后用返回行 append + renderHW() */ },
  async done(id, v)   { /* PATCH {done:v} */ }
};
```

**同步策略（够用就行，别上实时推送）**
1. 打开页面 / 切到「作业」tab → `HW.pull()`
2. `document.visibilitychange`（回到前台）→ `HW.pull()`
3. 定时 **30s** 一次 `HW.pull()`（页面 `hidden` 时暂停，省流量省电）
4. 本地发布/勾选成功后 → 用响应里的行更新本地数组 + 重渲染（不用等下一次轮询）

**个人状态（2026-10-18 更新）**
- 作业「完成」、通知「置顶」对**未登录**是按设备本地状态（`D.d.hwDone` / `D.d.ntPin`，以行 id 为键）；
  登录后改为按账号写 `marks`，同账号多端同步，不同账号互不影响。
- 云端 `homework.done` / `notices.pin` 列保留但恒为 false、读取时忽略；置顶/完成只认 `marks`。
- 「清除已完成」＝本机隐藏（`D.d.hwHide`），不软删云端行（否则会把别人的也删掉）；
  通知/作业删除走 `archived=true` 软删 + 本机 `ntHide` 兜底。

**硬性要求**
- `localStorage` 降级成**缓存**：断网/接口挂了，页面必须照常可用，**绝不能白屏**；
- 离线时发布可以先落本地队列、联网后再补发（可选，别做复杂）；
- 保留 `zq_tools_v2` 键和 `ziqi.tools.v1` 的迁移路径；
- **不引入任何外部脚本**。

---

## 6. 验收（改完必跑）

1. `python tests/selfcheck.py` → `PASS` / `ERR=(none)` / `navCount=0`
2. `python tests/overflow_check.py 430` → `overflowCount=0`
3. 端到端：手机 A 发一条 → 手机 B 在 30s 内看到同一条（**已在后端侧实测通过**）
4. 断网/接口 500：页面不报错、显示本地缓存
5. 导出图片 `export_check.py hw` 正常，水印/参数/编号齐全

后端侧已实测（用 Python 直连 REST）：`GET 200` / `POST 201` / `PATCH 200` /
`DELETE 401` / `OPTIONS 204` + 正确的 CORS 头。**ZCode 只需要验证前端接得好不好。**

---

## 7. 红线更新（原 `AGENTS.md` 第 4 条）

- **「作业」与「通知」允许上传云端**（2026-10-10 实测，`public.homework` / `public.notices`，
  anon 可 SELECT/INSERT/UPDATE、不可 DELETE）。
- **「班级名单」已上云（2026-10-13）**：存 `public.roster`（单行 `id='main'`，`data` 为 JSON）。
  **软保护**：前端**仅在登录成功后** GET 下发并写入账号数据桶；未登录时隐藏名单入口、渲染层一律按空名单处理；
  名单原文已从公开 HTML 移除。RLS 同作业（anon 可读写、不可 DELETE）；「更新云端名单」按钮仅管理员可见。
- **「体测记录」按账号同步（2026-10-19 更新）**：`public.fitrecs`，`acc` 为账号、`data` 为记录 JSON；
  `data` 内含 `id/ts/n(name)/sex/gr/fields/total/grade`；同一份数据只是补填项目时合并原记录；
  本地与云端都只保留最近两条，超出部分软删（`arch=true`）。
  anon 无 DELETE，删除走 `arch=true` 软删（拉取过滤 `arch=eq.false`）；未登录只存本机，登录后补传。
- **课表 / 点名 / 抽签配置等其余数据仍然只存本机**，不许上云。要动就先问用户。
- `deploy/creds.env`、`tools/cert/`、`deploy/acme_account_key.pem` 照旧**禁止读取/外传**。
- 本文件里的 PUBLISH_KEY **允许**进 `index.html`（它就是干这个的）；除此之外**任何密钥都不许进前端**。
- 不改 `tool.furina.fun` 的域名结构与 OSS Bucket；不动 `me.furina.fun`。

---

## 8. 小程序额外使用的表（2026-10-18 补记）

| 表 | 用途 | 字段 |
|----|------|------|
| `users` | 网页版/小程序共用账号 | `id`（账号）、`h`（sha256(账号+\x01+密码)）、`ts` |
| `feedback` | 反馈建议 | `id`、`content`、`contact`、`acc`、`done`、`ts` |
| `roster` | 班级名单（网页版/小程序共用） | `id='main'`、`data`（JSON：`{roster,ts}`）、`ts`；**仅登录且完成姓名+学号认证后可读** |
| `identity_verify` | 账号的班级身份认证 | `acc`（主键）、`name`、`sid`、`ok`、`ts`；只能读写自己 |
| `private.class_ids` | 官方姓名/学号对照（私有 schema，无 API） | `seat`、`name`、`sid`；只供 security definer 校验 |
| `fitrecs` | 体测历史（网页版/小程序共用） | `id`、`acc`、`data`（JSON）、`arch`、`ts` |
| `userdata` | 旧版兼容（当前体测录入备份） | `id`（账号）、`blob`、`ts` |

## 9. 2026-10-18 权限收紧（重要）

原匿名 RLS 是 `using(true)`，任何人拿到 publishable key 就能读 `users.h / roster.data /
userdata.blob / marks / fitrecs`。已改为**请求头鉴权 + RLS**：

- 客户端在每个请求加 `X-Device-Id: <账号>|<口令哈希>`（该头在 CloudBase 网关 CORS 白名单内）；
- `users` 只允许按自己的 `id + h` 读取；注册只允许非 admin、不含 `|`、64 位 hash；
- `roster` 登录后**还要完成姓名+学号认证**才可读、仅 admin 可写；`marks` 只能读写自己的 seat；`fitrecs` 只能读写自己的
  `acc`；`userdata` 只能读写自己的 id；`feedback` 读/标记仅 admin；`visits` 读仅 admin；
- 匿名 key 不再返回上述私有表的数据（200 + 空数组）；公开表 `homework/notices` 维持原样。

执行 SQL：`mp-class-tools-tests/security_hardening.sql`（回滚 `security_rollback.sql`）。
注意：所有旧缓存页面/旧小程序包如果没有发送该头，会被 RLS 拒绝；刷新网页或更新小程序即可。

## 10. 2026-10-19 班级身份认证（姓名 + 学号）

- `private.class_ids` 保存官方名单（`seat/name/sid`），放在私有 schema，**无 PostgREST 权限**；
  学号规则由班级名单维护者掌握。
- `public.identity_verify` 每账号一行，只能读写自己（`acc = auth_acc()`）；写入时由
  `private.identity_match(name,sid)` 校验，姓名/学号不匹配直接 401/403。
- `roster` 的 SELECT 策略改为 `auth_admin() OR (auth_ok() AND private.identity_verified())`；
  因此**只登录不认证拿不到班级名单**，客户端隐藏只是第二层。
- 建表/策略：`mp-class-tools-tests/identity_schema.sql`；回滚：`identity_rollback.sql`。
- 官方表 70 行中 49 号重复、48 号缺失，按唯一座号去重后为 69 人；`roster` 同步为
  `01 姓名` 的 69 行。




---

## 通知板自动行（2026-11-04）

- `public.notices` 中 `id like 'auto_%'`、`body` 以 `[[CLASS_NOTICE_V1]]` 开头的行是自动采集通知。
- 写入脚本：`C:\briefdesk\scripts\sync_notices_cloud.py`；本地 watcher 构建后自动运行。
- 前端 `NT.pull()` 解析该前缀，交给自动通知板；手动通知不含该前缀。
- token 由本地 admin 身份 `class_verify` 获取并缓存于 `C:\briefdesk\secrets\class-token.json`（仅本机）。

---

## 通知人群可见性（2026-11-04 18:55）

### 字段

`public.notices.audience`：

| 值 | 可见人群 |
|---|---|
| `all` | 已认证全班（默认） |
| `committee` | 班委（`private.class_ids.role` 非空，或 `badge` 含「班委」） |
| `sid:3260707024` | 指定学号；红会群当前只给陈子麒 |
| `admin` | 管理员（保留值） |

### 自动通知映射

`C:\briefdesk\scripts\sync_notices_cloud.py`：

- 群名/来源含「红会」→ `sid:3260707024`
- 群名/来源含「班委」→ `committee`
- 其他 → `all`

### 服务端 RLS

新增 `auth_sid()` / `auth_is_admin()` / `auth_is_committee()`，并把 `nt_read` 改为：

```sql
auth_ok() AND (
  coalesce(audience,'all') = 'all'
  OR (audience='admin' AND auth_is_admin())
  OR (audience='committee' AND auth_is_committee())
  OR audience = 'sid:' || coalesce(auth_sid(),'')
)
```

同时把 `nt_insert` / `nt_update` 收紧为仅管理员，防止已认证用户修改 `audience` 绕过可见性。

### 已验证

- 陈子麒（管理员）：19 条，含红会
- 谢梓萱（班委）：18 条，不含红会
- 李学盈（普通成员）：18 条，不含红会
- 临时把一条通知设为 `committee`：班委可见、普通成员不可见；已恢复 `all`
- 匿名：0 条

回滚：删除 audience 列、恢复原 `nt_read/nt_insert/nt_update` 策略（原策略均 `auth_ok()`）。

## 通知时间字段（2026-11-04 19:55）

自动通知 body JSON 增加：

| 字段 | 含义 |
|---|---|
| `deadline` | 明确截止时间；没有时可为 null |
| `eventAt` | 活动/测试/集合时间；无明确截止时用于时效判断 |
| `expireAt` | 实际失效时间，优先于 deadline；药膳打卡 = eventAt + 1 天 |
| `timeLabel` | 卡片顶部展示文案，如「报名 11-05 12:00」 |

前端 `statusOf` 优先使用 `expireAt`；event-only 通知过期显示「已结束 · 自动归档」；没有可解析时间显示「无时间」。

## 团员可见（league）与团员名单（2026-11-04 20:30）

### audience 新值

| 值 | 可见人群 |
|---|---|
| `league` | 团员（`private.class_league` 名单内 + 有效班级 token） |

`nt_read` 增加分支 `OR (audience='league' AND public.auth_is_league())`；其余策略不变
（`nt_insert` / `nt_update` 仍仅管理员）。

### 团员名单来源

- QQ 群 **26信管团员群（群号 1027383483）** 成员（51 人）→ 按「群名片 seat+姓名」匹配
  `private.class_ids`，得到 **50 名班级团员**；群内 1 个非班级成员（「外」）不纳入。
  其中两个用网名/无名片的成员已按用户确认人工映射：**长言木 = 张誉权（座号 52）**、
  **🗿 = 孙博文（座号 10）**（脚本按 QQ 号固化该映射，群名片改回实名后也可自动匹配）。
- 生成脚本：`C:\briefdesk\scripts\sync_league_roster.py`
  - QQ 成员：`C:\briefdesk\scripts\qqmembers`（新 C# 工具，只读 `group_info.db.group_member3`；
    手机端点开群聊会补齐本地名册缓存）
  - 班级名单：`tcb db execute` 实时读 `private.class_ids`
  - 输出：`C:\briefdesk\data\league-members.json`（名单）+ `league-members.sql`（入库 SQL）
- 应用 SQL：`C:\briefdesk\scripts\apply_league.py`
  - 建表 `private.class_league(sid, seat, updated_at)`
  - 建函数 `public.auth_is_league()`（SECURITY DEFINER，按 `class_sessions.sid` 关联）
  - 重建 `notices.nt_read`
  - 导入 50 个 sid
  - 建表/策略脚本：`C:\briefdesk\scripts\sql\league_audience.sql`；回滚：`league_audience_rollback.sql`

### 自动通知映射

`C:\briefdesk\scripts\sync_notices_cloud.py` 现为：

- 群名/来源含「红会」→ `sid:3260707024`
- 群名/来源含「团员」→ `league`
- 群名/来源含「班委」→ `committee`
- 其余 → `all`

> 2026-11-04 当前 19 条自动通知里没有来自团员群的卡片；映射从下一次同步/新通知起生效。

### 已验证（自测行，验证后已删除）

| 身份 | audience=league | audience=all | 结论 |
|---|---|---|---|
| 陈子麒（管理员 + 团员） | 可见 | 可见 | PASS |
| 谢梓萱（班委 + 团员） | 可见 | 可见 | PASS |
| 李学盈（普通 + 团员） | 可见 | 可见 | PASS |
| 张誉权（普通 + 团员，群名片「长言木」） | 可见 | 可见 | PASS |
| 孙博文（普通 + 团员，群名片「🗿」） | 可见 | 可见 | PASS |
| 余文智（普通，非团员） | 不可见 | 可见 | PASS |
| 黄洁滢（班委，非团员） | 不可见 | 可见 | PASS |
| 匿名 | 不可见（0 行） | 不可见 | PASS |

测试脚本：`C:\briefdesk\scripts\test_league_visibility.py`（8/8 PASS）。

## 访问统计 / 反馈 RLS：本人行可读（2026-11-04 23:30 修复，已应用）

> 迁移文件：`deploy/cloudbase/2026-11-04_visits_feedback_own_read.sql`

### 问题

前端写 `visits`（访问统计埋点）与 `feedback`（反馈提交）时带 PostgREST 的
`Prefer: return=representation`（网页 `cbPost→cbH(true)`；小程序 `headers(true)`）。
PostgREST 对 INSERT + returning 要求新插入行**同时能被 SELECT**，而这两张表原来的读策略只有
`auth_admin()` → 非管理员写入返回 `401 DATABASE_42501 new row violates row-level security policy`，
前端 catch 后静默失败。现象：统计只有管理员自己一个人、普通同学反馈提交失败。

### 修复后的策略（写入策略未改）

```sql
-- visits
vs_read:  auth_admin() OR (auth_ok() AND sid = auth_acc())
vs_insert: auth_ok() AND sid = auth_acc()          -- 不变
-- feedback
fb_read:  auth_admin() OR (auth_ok() AND acc = auth_acc())
fb_insert: auth_ok()                                -- 不变
```

- 管理员：仍可读全部行；普通成员：只能读自己那几行（`auth_acc()` 来自 `private.class_sessions` token），**看不到他人**。
- 修复同时兜住尚未更新的旧页面/小程序（它们仍带 returning 头）。
- 客户端也已改为写这两张表不请求 representation（网页 `cbPostNoRep()`；小程序 `headers(false)`），
  下次发版后不再依赖本放宽；若未来要恢复「仅管理员可读」，先确认两端客户端都已更新。

### 回滚

```sql
drop policy if exists vs_read on public.visits;
create policy vs_read on public.visits for select to anon using (public.auth_admin());
drop policy if exists fb_read on public.feedback;
create policy fb_read on public.feedback for select to anon using (public.auth_admin());
```

### 遗留

`fb_insert` 仍为 `auth_ok()`（任何已认证成员可写任意 `acc` 的反馈行，历史行为）。如需收紧可改为
`auth_ok() AND acc = auth_acc()`；网页/小程序两端口径均已是本人 sid。

## 用户数据同步 v6 与「通知已处理」（2026-11-05，已上线网页 / 小程序待上传）

> 目标：网页与小程序同一账号下，用户自己改动的内容全部双向互通。**无新表、无 DDL、RLS 不变。**

### marks：新增 `kind='ntdone'`

| 字段 | 值 |
| --- | --- |
| `id` | `<sid>|<kind>|<ref>` |
| `seat` | 学号（RLS 按本人校验） |
| `kind` | `'hw'`（作业完成）/ `'nt'`（通知置顶）/ **`'ntdone'`（自动通知已处理）** |
| `ref` | 作业行 id / 通知行 id / 自动通知组 id |
| `val` | true/false（**取消写 false，不 DELETE**；无 DELETE 权限） |

- 写入：`POST marks` + `Prefer: return=representation,resolution=merge-duplicates`（upsert）；
- 读取：`GET marks?select=*&seat=eq.<sid>`（web 与 mp 完全一致，行 id 规则一致 → 天然互通）；
- web 旧 local `zq_auto_nt_done` 首次同步一次性迁移为 `ntdone` marks（按 sid 标记，迁后清本地）。

### userdata：blob 升级 v6（单行 `{id: sid, blob, ts}`，JSON 内扩展）

```jsonc
{
  "v": 6,
  "at": { "homeTools":0, "fit":0, "draw":0, "group":0, "roster":0,
          "hide":0, "tt":0, "prefs":0, "nick":0 },
  "homeTools": [],                                  // 工具顺序（≤4）
  "fit": {},                                        // 体测录入（当前输入）
  "draw": {}, "group": {}, "roster": {},            // 抽签/分组参数与名单选择；点名名单与到·假
  "hide": { "hwHide":{}, "ntHide":{} },
  "tt": { "ttView":"", "ttUseMine":false, "ttLocal":null, "termStart":"" },
  "prefs": { "hwRemind":{}, "ntSub":false, "ntSubAt":0 },
  "nick": "",
  "homeToolsAt": 0                                  // 旧版兼容镜像（= at.homeTools）
}
```

- **合并规则**（两端逐字节一致，web `UD.merge` / mp `mergeUd`）：逐 section 比较 `at`，`remote.at>=local.at` 时云端赢
  （同时间戳云端赢，幂等收敛）；缺字段用默认值；v5 旧 blob 视为 `{homeTools, fit, at:{homeTools:homeToolsAt, fit:0}}` 后正常合并，**拉取到 v5 时自动写回 v6**（幂等，写回后不再重复）；
  未拥有的 section 按最近合并结果原样保留（web 不写 `prefs`，mp 不写 `nick` 与 `tt` 除 `termStart` 外字段）。
- 拉取：启动/回到前台/轮询 TTL 60s；推送：本地脏 section 防抖 1200ms，先 GET 合并再 POST upsert（`Prefer` 同上）。
- 清除：RLS 无 DELETE → 「清除云端我的数据」= userdata 覆盖为空 v6 + marks 置 false + fitrecs `arch=true`；
  `visits` 与 `feedback` 无法删除（保持原样，隐私页如实说明）。
- 已实测（2026-11-05，管理员本人身份 + 网页头 `X-Device-Id`）：`GET/POST userdata` 本人行均 200，
  即网页端与小程序端对同一行读写都通；当前线上 blob 为 v5（199 字符），v6 迁移路径真实存在。

### 两端实现位置

| 端 | 位置 |
| --- | --- |
| web | `tools/index.html`：`UD` 模块（约 1675 行起）、`noticeApplyDone/noticeSetDone/noticePushDone`（约 1345-1380）、`noticePerfPatch` 内 iframe 注入（约 1442-1465）、message handler `class-notice-done`（约 1531）；测试 `tools/tests/sync_check.py` |
| mp | `utils/cloud.js`：marks `ntdone` + UD v6 段（约 720-1127）；`utils/privacy.js`（导出/空 blob/置否标记纯逻辑）；`pages/data/*`（数据与隐私页）；`Store` 新增 `ntDone/udCache/udPend/cloudOff`；`pages/nt/nt.js` 已处理持久化；测试 `mp-class-tools-tests/sync_contract_test.js` |


## 依赖服务健康表 `public.service_health`（2026-11-05，管理员「诊断」页）

> 用途：采集主机每 5 分钟把 13 个依赖服务的状态上报云端；网页仅管理员可读并展示。
> 契约（唯一真源）：`tools/tests/health_monitor_spec.md` §1/§2。迁移：`deploy/cloudbase/2026-11-05_service_health.sql`（已应用）。

### 表结构

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | text PK | 服务 id（13 个固定值，见 spec §1） |
| `name` | text | 显示名（如「QQ 消息采集」） |
| `kind` | text | `local` / `cloud` / `static` |
| `status` | text | `ok` / `warn` / `down` / `unknown` |
| `detail` | text | 一句话中文（≤60 字） |
| `meta` | jsonb | 结构化细节（latency_ms / days_left / uptime / last_ok …） |
| `checked_at` | bigint | 采集主机检测时刻（unix ms） |
| `updated_at` | timestamptz | 云端行更新时间（默认 now()） |

RLS：`sh_read` / `sh_insert` / `sh_update` 三条策略全部 `TO anon` + `public.auth_admin()`；
匿名/普通成员 `SELECT` 返回 `[]`，写入（含 PATCH/POST）仅管理员 token。`anon` 无 DELETE 策略（不可删行）。

### 接口

```http
GET {REST}/service_health?select=id,name,kind,status,detail,meta,checked_at&order=id
Authorization: Bearer <PUBLISH_KEY>
X-Device-Id: <管理员 token>
```

采集主机写入（`C:\briefdesk\scripts\health_beat.py`）：GET 现有 id → 存在则
`PATCH /service_health?id=eq.<id>`，不存在则 `POST /service_health`；管理员 token 从
`C:\briefdesk\secrets\class-token.json` 读取（过期自动 `rpc/class_verify` 刷新），**不打印 token**。

### 心跳来源与判定

- 采集主机检测 13 项（QQ/微信消息采集、通知服务、文档监听、AI、教务同步、作业整理、
  QQ/微信客户端、云端库、站点资源、站点证书、采集主机），由 `watchdog.py` 每轮结束后调用；
  `C:\briefdesk\watchdog.pause` 存在时 `collector_host=warn`（「采集已暂停」）。
- 采集主机心跳 >15 分钟未更新 → 前端把所有 `kind=local` 行降级显示「离线」，不误报正常；
  云端/站点资源行以浏览器实时探测（CloudBase 延迟 / 同源 `tt.json`）覆盖。
- `site_tls`：TLS 握手 + 证书剩余天数（>21 天 ok，8–21 天 warn，≤7 天或握手失败 down）；
  `jwxt`：`tools/tt.json` 的 `meta.fetchedAt` 年龄（≤30h ok / 30–54h warn / >54h down）。

### 运维

```powershell
# 看当前 13 行（tcb）
tcb db execute -e tool-d4gosudok46e0e081 --sql "select id,status,detail,checked_at from public.service_health order by id"
# 手动跑一次心跳（隐藏窗口）
C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\health_beat.py --once
# 只打印不写库
C:\briefdesk\venv\Scripts\python.exe C:\briefdesk\scripts\health_beat.py --dry-run
# 日志
C:\briefdesk\logs\health-beat.log
# 回滚
tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP TABLE IF EXISTS public.service_health"
```

## 审核测试身份（2026-11-05 20:25 建立）

> 用户要求：审核相关只保留“添加账号”，不实现演示/审核模式。
> 迁移/回滚 SQL：`deploy/cloudbase/2026-11-05_test_account.sql`（已应用）。

- `private.class_ids` 新增列 `is_test boolean not null default false`；测试行：seat 999 / name「测试账号」/ sid `3260799999` / 非管理员。
- `public.class_members()` 已改为过滤 `is_test` → 班级名单仍 70 人、名单选择器/统计不出现测试身份。
- 审核员用**正常身份页**「学号 + 姓名」登录即可；凭据只写在交付说明（`web/验收报告/v2.0.0_交付说明.md`），不入代码/仓库。
- 审核结束回收：
  ```sql
  delete from private.class_sessions where sid = '3260799999';
  delete from private.class_ids where sid = '3260799999' and is_test = true;
  ```
- 不要再增加演示模式/试用开关/审核入口等其它审核相关功能（用户 2026-11-05 明确要求）。

## 课表快照 `public.site_assets` + 网页暂停开关 `public.site_config`（2026-11-07）

> 背景：用户将暂停 furina.fun 解析（网页暂停使用），小程序课表原先依赖 `https://tool.furina.fun/tt.json`；
> 本表把课表快照内迁 CloudBase，小程序改从网关读取，不再依赖站点域名。契约：`tools/tests/dns_pause_tt_health_spec.md`。

### 表结构

`public.site_assets`（幂等迁移 `deploy/cloudbase/2026-11-07_site_assets.sql`）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | text PK | `tt` = 课表快照 |
| `body` | jsonb | 原 `tools/tt.json` 对象 `{c:[...],t:"...",meta:{...}}` |
| `meta` | jsonb | `{source:"jwxt",fetchedAt:<ms>,count:<n>,termStart:"YYYY-MM-DD",syncedAt:"<ISO>"}` |
| `updated_at` | timestamptz | 发布时刻 |

RLS：`sa_read` = `auth_ok()`（有效班级 token 可读，网页 `X-Device-Id` / 小程序 `X-Class-Token`）；
`sa_insert/sa_update` = `auth_admin()`（仅管理员 token）。匿名/无效 token 读 `[]`。

`public.site_config`：`id text PK / value jsonb / updated_at`；RLS 仅管理员读写。行 `id='web'` =
`{paused:bool, note:str, paused_at:<ms>}`：暂停 DNS 前用 `C:\briefdesk\scripts\web_pause.py --on` 置 `paused=true`，
恢复解析后 `--off`。云函数 `health_probe` 读到 `paused=true` 时，`site_static/site_tls` 显示「注意 · 网页已按备案安排暂停」
（跳过实际探测），`dns_domain` 按「已暂停/仍在解析」判定；避免诊断页误报异常。

### 读写接口

```http
# 读课表快照（网页/小程序同一接口；需班级 token）
GET {REST}/site_assets?id=eq.tt&select=body,meta,updated_at
Authorization: Bearer <PUBLISH_KEY>
X-Class-Token: <token>        # 网页用 X-Device-Id

# 写课表快照（仅管理员 token；本机 jwxt 同步脚本自动执行）
PATCH {REST}/site_assets?id=eq.tt   body={body,meta,updated_at}
```

- 写入方：`web/jwxt/tt_cloud.py`（`sync.py` 写盘成功后 always try publish；失败只记日志、不影响 `sync.py` 退出码/OSS 上传）；
  手动回填 `python web/jwxt/tt_cloud.py --tt tools/tt.json`。
- 读取方：小程序 `utils/cloud.js → ttFetch`（site_assets 优先，失败回退旧 `ttUrl`）；网页 `ttSyncPull`（同源 `tt.json` 优先，失败回退 site_assets）。
- 本机 `C:\briefdesk\scripts\health_beat.py` 只剩 local 10 行；云端 8 行由 `health_probe` 云函数写
  （含 `tt_cloud` 检查本行 freshness、`cloud_power_sync`、`cloud_xgj_sync`、`cloud_health_probe` 心跳等，见 `health_monitor_spec.md` §9）。
- 暂停/恢复后无需改代码：`web_pause.py --on/--off` 即可；**2026-12-10 前必须续费 CloudBase**，否则小程序/云端一并中断。
