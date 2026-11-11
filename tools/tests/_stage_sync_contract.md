# 大屏自定义项目云同步 · 契约 v1

> Lead 定稿 2026-11-11。用户需求（第 3 条）：「所有自定义项目保持云同步」。
> 不新增/不修改 UD v6 跨端契约（避免旧版小程序合并时丢字段），改用独立小表，按账号本人可读写。

## 1. 云端表（`public` schema，PostgREST 直连）

```sql
create table if not exists public.stage_prefs (
  sid        text primary key,                     -- 班级账号学号（auth_sid()）
  layout     jsonb not null default '{}'::jsonb,   -- 大屏自定义（见 §2）
  updated_at timestamptz not null default now()
);
alter table public.stage_prefs enable row level security;
-- 仅本人可读写（auth_sid() = sid）；不返回/不存储姓名
create policy stage_prefs_sel on public.stage_prefs for select to anon using (auth_sid() = sid);
create policy stage_prefs_ins on public.stage_prefs for insert to anon with check (auth_sid() = sid);
create policy stage_prefs_upd on public.stage_prefs for update to anon using (auth_sid() = sid) with check (auth_sid() = sid);
```

## 2. `layout` JSON（版本化，未知字段忽略、缺字段用默认）

```jsonc
{
  "v": 1,
  "order": ["ppt","vote","timer","draw"],       // 可见模块顺序（只允许内置模块 key）
  "span": {"ppt":8,"vote":4,"timer":6,"draw":6}, // 12 列网格宽度（4/6/8/12）
  "hidden": [],                                  // 已移除（隐藏）的模块
  "lastDeck": "",                                // 上次使用的演示 deck id
  "pptDl": {},                                   // 已下载标记 {deckId:{at,kind}}（可选，最大裁剪 50 条）
  "at": 1762860000000                            // 本机最后修改时间（LWW：仅当本机 at > 云端 updated_at 才覆盖）
}
```

## 3. 客户端读写（web `STAGE`）

- 启动/打开大屏：先读 `localStorage zq_stage_layout_v1`（旧键保留为离线缓存）立即渲染 → 再
  `GET stage_prefs?select=layout,updated_at&sid=eq.<AUTH.sid>`；拿到后 **LWW 合并**：
  `layout.at > updated_at(ms)` → 本机更新（推）；否则应用云端。
- 用户改布局（拖动排序/改宽/增删模块/预设/上次演示/已下载标记）：写 localStorage → 防抖 800ms →
  `POST stage_prefs?on_conflict=sid`（`Prefer: resolution=merge-duplicates,return=minimal`）body `{"sid":"<sid>","layout":{...}}`。
- 离线/失败：不阻塞，保持本机，联网/下次打开时补推（单飞、去重）。
- 读不到/空表：用旧 localStorage 初始化并推一次；`layout` 非法 JSON → 视为无云端数据。
- 未登录/无 sid：不请求。

## 4. 验收

- 设备 A 拖动/改宽/增删模块 → 设备 B 刷新后同布局（真实云端 QA：测试身份写、finally 清理）。
- 离线改布局 → 联网后自动补推，不覆盖 B 端更新的旧值（LWW）。
- 无 token → 401/空；token 只见本人行（另一账号查询返回 []）。
- 不改 UD v6 契约、不改小程序 userdata 合并（mp 端无需改动）。
