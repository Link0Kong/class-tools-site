-- 2026-11-05 · 通知管理员编辑 / 删除（班级工具站 v2.0.0 需求 12）
--
-- 背景：自动同步的通知行 id = auto_<通知组 id>，body = [[CLASS_NOTICE_V1]] + JSON。
--   需求 12 要求管理员可以在网页/小程序里编辑、删除（软删除=隐藏，可恢复）自动通知，
--   且采集端重建后不复活。做法是**不直接改 body**，而是新增 4 列存管理员覆盖：
--     override_json : 管理员编辑过的字段 JSON（白名单 title/cat/summary/aiSummary/
--                     deadline/eventAt/expireAt/timeLabel；值为 null 表示清空）
--     hidden        : 软删除标记（true = 前端列表隐藏；管理员可在「已隐藏」区恢复）
--     edited_at     : 最后编辑时间（毫秒时间戳）
--     edited_by     : 最后编辑人（学号或管理员标识，用于审计）
--   读：前端 `notices?select=*` 自动带上；解析 body 后套用 override_json、过滤 hidden。
--   写：管理员 PATCH notices?id=eq.<rowid>：
--         {override_json, edited_at, edited_by} / {hidden:true|false, edited_at, edited_by}
--   ⚠️ C:\briefdesk\scripts\sync_notices_cloud.py 只 PATCH id/title/body/audience/archived/ts，
--      不得写入/清空这 4 列（否则管理员编辑在采集重建后被覆盖）。
--   ⚠️ 现有 nt_update / nt_insert 策略已是「仅管理员」，无需新增 RLS。
--
-- 应用（Lead 执行；幂等，可重复跑）：
--   cd web\deploy\cloudbase && tcb db execute -e tool-d4gosudok46e0e081 --sql "<本文件内容>"
--   或逐条执行下面 4 条 alter（CLI 一次只吃一条语句）。
-- 回滚：见文件末尾注释。

alter table public.notices add column if not exists override_json text default '';
alter table public.notices add column if not exists hidden boolean not null default false;
alter table public.notices add column if not exists edited_at bigint default 0;
alter table public.notices add column if not exists edited_by text default '';

-- 回滚（会把管理员编辑/隐藏数据一起清掉；如需保留数据不要执行）：
--   alter table public.notices drop column if exists override_json;
--   alter table public.notices drop column if exists hidden;
--   alter table public.notices drop column if exists edited_at;
--   alter table public.notices drop column if exists edited_by;
