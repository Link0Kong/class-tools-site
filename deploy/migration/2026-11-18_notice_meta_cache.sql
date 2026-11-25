-- 2026-11-18 迁移优化（第二级缓存）：通知列表 `class_notices_meta()` 结果缓存（写时重建，读时纯读）
--
-- 前置：先应用 `2026-11-18_notice_meta_lite.sql`（private.notice_meta_lite + 触发器）。
-- 设计：PostgREST 的 GET 请求在只读事务里执行，读路径不能写表；因此缓存改由**语句级触发器**
-- 在 notices 写入时重建（一次写语句约 75–90ms，写很少），RPC 只做纯 SELECT（STABLE）→ 2–5ms。
-- 输出与旧实现逐字节一致（staging 已验证 sha `20a0346a…`，125 行 / 313819B）。
--
-- 仅用于自建 PostgreSQL 18（class_tools / class_tools_cut）；CloudBase 生产库不应用。
-- 幂等：可重复执行。P4 切流在最终快照导入后、切 Caddy 前执行（见 deploy/migration/CUTOVER.md）。

begin;

create table if not exists private.notice_meta_cache (
  id smallint primary key,
  payload jsonb not null default '[]'::jsonb,
  built_rows int,
  built_at timestamptz not null default now()
);

alter table private.notice_meta_cache owner to class_tools_owner;
revoke all on private.notice_meta_cache from public;
-- 兼容旧版本（dirty 标记方案）残留
alter table private.notice_meta_cache drop column if exists dirty;
insert into private.notice_meta_cache(id) values (1)
on conflict (id) do nothing;

-- 普通函数：重建缓存（可从迁移 SQL 直接调用）
create or replace function private.notice_meta_cache_build()
returns void
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $$
declare
  v_payload jsonb;
  v_rows int;
begin
  select coalesce(jsonb_agg(
           jsonb_set(to_jsonb(t), '{body}', to_jsonb(coalesce(m.body_lite, t.body)))
           order by t.ts asc, t.id asc
         ), '[]'::jsonb),
         count(*)
    into v_payload, v_rows
  from public.notices t
  left join private.notice_meta_lite m on m.id = t.id
  where t.archived = false;

  insert into private.notice_meta_cache(id, payload, built_rows, built_at)
  values (1, v_payload, v_rows, now())
  on conflict (id) do update
    set payload = excluded.payload,
        built_rows = excluded.built_rows,
        built_at = excluded.built_at;
end;
$$;

alter function private.notice_meta_cache_build() owner to class_tools_owner;

-- 语句级触发器包装：一次写语句重建一次（批量 upsert 只付一次成本）
create or replace function private.notice_meta_cache_stmt()
returns trigger
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $$
begin
  perform private.notice_meta_cache_build();
  return null;
end;
$$;

alter function private.notice_meta_cache_stmt() owner to class_tools_owner;

-- 清掉旧 dirty 方案与旧函数（如曾应用过）
drop trigger if exists trg_notice_meta_cache_dirty on public.notices;
drop function if exists private.notice_meta_cache_dirty();
drop function if exists private.notice_meta_cache_rebuild();

drop trigger if exists trg_notice_meta_cache_stmt on public.notices;
create trigger trg_notice_meta_cache_stmt
after insert or update or delete on public.notices
for each statement execute function private.notice_meta_cache_stmt();

-- 初始构建（导入后执行一次）
select private.notice_meta_cache_build();

-- RPC：纯读缓存
create or replace function public.class_notices_meta()
returns jsonb
language plpgsql
stable
security definer
set search_path to 'public', 'pg_temp'
as $$
begin
  if not public.auth_ok() then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  return coalesce((
    select jsonb_agg(item order by n)
    from private.notice_meta_cache c
    cross join lateral jsonb_array_elements(c.payload) with ordinality as items(item, n)
    where c.id = 1 and public.notice_audience_visible(item->>'audience')
  ), '[]'::jsonb);
end;
$$;

alter function public.class_notices_meta() owner to class_tools_owner;

analyze private.notice_meta_cache;

commit;
