-- 2026-11-18 迁移优化：通知列表轻量化 RPC 的预计算（仅自建 PostgreSQL 后端使用）
--
-- 背景：`class_notices_meta()` 每次打开通知页都要把 184 行 notices.body（合计约 25MB）
-- 全量 JSON 解析 + 剥 data URI（notice_lite_body），staging 实测 221–250ms/次（125 行 / 313KB）。
-- 方案：触发器在写入时把 lite body 预计算进 private.notice_meta_lite；RPC 只做 JOIN + jsonb_set，
-- 输出与旧实现逐字节一致的 jsonb（契约不变，客户端零改动）。
--
-- 适用：自建 PostgreSQL 18（class_tools / class_tools_cut）。CloudBase 生产库不应用本文件。
-- 幂等：可重复执行。P4 切流时在「最终快照导入」之后、切 Caddy 之前执行（见 deploy/migration/CUTOVER.md）。

begin;

create table if not exists private.notice_meta_lite (
  id text primary key references public.notices(id) on delete cascade,
  body_lite text
);

revoke all on private.notice_meta_lite from public;
-- 属主对齐：SECURITY DEFINER 的 class_notices_meta 以 class_tools_owner 执行，需要能读该表
alter table private.notice_meta_lite owner to class_tools_owner;

-- 写入/更新 body 时预计算；DELETE 由 FK cascade 清理（触发器兜底显式删一次）
create or replace function private.notice_meta_lite_sync()
returns trigger
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $$
begin
  if tg_op = 'DELETE' then
    delete from private.notice_meta_lite where id = old.id;
    return old;
  end if;
  insert into private.notice_meta_lite(id, body_lite)
  values (new.id, public.notice_lite_body(new.body))
  on conflict (id) do update set body_lite = excluded.body_lite;
  return new;
end;
$$;

alter function private.notice_meta_lite_sync() owner to class_tools_owner;

drop trigger if exists trg_notice_meta_lite on public.notices;
create trigger trg_notice_meta_lite
after insert or update of body on public.notices
for each row execute function private.notice_meta_lite_sync();

-- 存量回填（184 行；解析一次约 0.2–0.5s）
insert into private.notice_meta_lite(id, body_lite)
select n.id, public.notice_lite_body(n.body)
from public.notices n
on conflict (id) do update set body_lite = excluded.body_lite;

-- RPC：输出结构与旧实现一致（notices 全列，body 换成 lite）
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
    select jsonb_agg(
             jsonb_set(to_jsonb(t), '{body}', to_jsonb(coalesce(m.body_lite, t.body)))
             order by t.ts asc, t.id asc
           )
    from public.notices t
    left join private.notice_meta_lite m on m.id = t.id
    where t.archived = false
  ), '[]'::jsonb);
end;
$$;

alter function public.class_notices_meta() owner to class_tools_owner;

analyze public.notices;
analyze private.notice_meta_lite;

commit;
