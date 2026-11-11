# 水量共享云端（以宿舍为单位）· 跨端契约 v1

> Lead 定稿 2026-11-11。用户需求：「水量统计与同步以宿舍为单位」「23 号楼的两座自动设为四人间」「去除每月免费*吨水字样」。
> 本文件是 web / 小程序 / 云端迁移（`deploy/cloudbase/2026-11-11_water_shared.sql`）的唯一接口口径。
> 现有 UD v6 `water` section **契约不变**，仅降级为「本机离线缓存」（mp 端可继续原样保留/读写，不新增 UD section）。

## 1. 云端表（`public` schema，PostgREST 直连）

```sql
create table if not exists public.water (
  roomverify text not null,              -- 与 PW_ROOMS 一致，如 4-23B---423
  month      text not null,              -- YYYY-MM（如 2026-11）
  reading    numeric(10,2) not null,     -- 水表读数（吨，两位小数）
  persons    int  not null default 4 check (persons in (4,6)),
  updated_at timestamptz not null default now(),
  primary key (roomverify, month)
);
create table if not exists public.water_room (
  roomverify text primary key,
  persons    int not null default 4 check (persons in (4,6)),
  updated_at timestamptz not null default now()
);
```
- RLS 全部开启；策略：select / insert / update / delete 均 `to anon using (auth_ok()) / with check (auth_ok())`
  （沿用 `public.homework` / `public.notices` 的班级 token 口径；`auth_ok()` 已接受网页 `X-Device-Id` 与小程序 `X-Class-Token`）。
- 不存姓名/学号/手机号；`updated_at` 仅时间。
- 建议给 `water_room` 预置 17 间房（persons 默认 4），可选；客户端无行时按 4 处理。

## 2. HTTP 口径（网页 `fetch` / 小程序 `wx.request`，均带班级 token）

- 列水表记录：`GET water?select=roomverify,month,reading,persons&roomverify=eq.<rv>&order=month.asc` → `[{...}]`
- 写一条（幂等 upsert）：`POST water?on_conflict=roomverify,month`，头 `Prefer: resolution=merge-duplicates,return=minimal`，
  body `{"roomverify":"<rv>","month":"YYYY-MM","reading":123.45,"persons":4}`
- 删一条：`DELETE water?roomverify=eq.<rv>&month=eq.<YYYY-MM>`
- 房间人数：`GET water_room?select=roomverify,persons&roomverify=eq.<rv>`；
  写：`POST water_room?on_conflict=roomverify`，body `{"roomverify":"<rv>","persons":4}`
- 响应/错误同现有 PostgREST；失败不得阻塞页面（离线缓存继续可用）。

## 3. 合并与离线规则（web `WATER` / mp `utils/water.js`）

1. **进入水量页 / 切换宿舍**：先渲染本机缓存（UD `water.rooms[rv]` 或 mp store）→ 再 GET 云端；
   云端成功：`recs` 以云端为准（同 month 云端覆盖本地；本地有而云端无的月份**补传**，补传失败静默保留本地 pending）。
   云端失败：保留本机缓存 + 同步状态显示「离线」。
2. **保存/删除/改人数**：先写本机 + `D.save()`（/ mp store.save）→ 再尽力写云端；失败设 `pending` 标记，
   下次进入、刷新、联网/页面可见时重试（web 可在 `WATER.enter` + `online` 事件重试；mp `onShow` 重试）。
3. 云端数据为宿舍共享：同宿舍任一同学写入后，其他同学进入即可看到（这就是「以宿舍为单位」）。
4. UD v6 `water` 仍可照旧读写（兼容旧版页面），但**统计/展示以云端为准**；不得删除/改写 UD 契约。

## 4. 23 号楼 A/B 座固定四人间

- 判定：`roomverify` 以 `4-23A---` 或 `4-23B---` 开头（等价 `building` 为「23号楼A座」/「23号楼B座」）。
- 行为：选中这些房间时 `persons` 强制 = 4；人数选择器 `disabled`（web `#wtPersons`，mp 同）或显示「4 人间（固定）」；
  云端 `water_room.persons` 首次进入自动 upsert 4；不得让用户改成 6。
- 其他楼栋（13/16）保持 4/6 可选，默认 4。

## 5. 文案

- 去掉 UI 里「每月免费 8 吨水 / 12 吨水」字样（`#wtPersons` option 文案只留「4 人间」「6 人间」）。
- 水量页/使用说明里「免费额度/免费定额/免费 N 吨」措辞改为「定额」（如「用水定额 每人 2 吨/月」），**计费公式与数值不变**（超额部分 × 3.03 元/吨）。
- 其余规则卡来源与单价不变。

## 6. 验收（web/mp 各自实现，Lead 统一回归）

- web：选 23A/23B 房间 → 人数=4 且不可改；13/16 房间可 4/6；云 mock：GET/POST/DELETE 口径正确、离线缓存可用、
  保存后另一账号（同宿舍）能看到同一记录（mock 或真实云端 QA，真实写用测试身份 + finally 清理）。
- mp：同上（`unit.js` + 页面预览，真实云端只读/测试身份写）。
- 云端：迁移应用后 RLS 拒绝无 token（401/[]）、有效 token 可读写；`water` 主键幂等；不产生姓名/学号字段。
