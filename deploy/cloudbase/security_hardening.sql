-- 班级工具站 · CloudBase PostgreSQL 权限收紧
-- 目标：不再允许匿名全表读取 users.h / roster.data / userdata.blob / marks / fitrecs。
-- 机制：客户端在 X-Device-Id 头里带 "账号|口令哈希"；RLS 用 security definer 函数校验。
-- 注意：网页版与小程序必须同步发送该头（已在 2026-10-18 客户端改造中完成）。
-- 回滚：security_rollback.sql。

create or replace function public.auth_hdr() returns text
language sql stable as $fn$
  select coalesce(nullif(current_setting('request.headers', true), ''), '{}')::json->>'x-device-id'
$fn$;

create or replace function public.auth_acc() returns text
language sql stable as $fn$
  select coalesce(split_part(public.auth_hdr(), '|', 1), '')
$fn$;

create or replace function public.auth_hash() returns text
language sql stable as $fn$
  select coalesce(split_part(public.auth_hdr(), '|', 2), '')
$fn$;

create or replace function public.auth_ok() returns boolean
language sql stable security definer set search_path = public, pg_temp as $fn$
  select position('|' in coalesce(public.auth_hdr(), '')) > 0
     and exists (
       select 1 from public.users u
       where u.id = public.auth_acc() and u.h = public.auth_hash()
     )
$fn$;

create or replace function public.auth_admin() returns boolean
language sql stable security definer set search_path = public, pg_temp as $fn$
  select public.auth_ok() and public.auth_acc() = 'admin'
$fn$;

grant execute on function public.auth_hdr() to anon;
grant execute on function public.auth_acc() to anon;
grant execute on function public.auth_hash() to anon;
grant execute on function public.auth_ok() to anon;
grant execute on function public.auth_admin() to anon;

-- users：只能按自己的 id + hash 读取；注册只能插入非 admin / 不含 | / 64 位 hash
drop policy if exists us_read on public.users;
create policy us_read on public.users for select to anon
  using (id = public.auth_acc() and h = public.auth_hash());
drop policy if exists us_insert on public.users;
create policy us_insert on public.users for insert to anon
  with check (lower(id) <> 'admin' and position('|' in id) = 0 and length(h) = 64);

-- roster：登录后可读；只有 admin 可写
drop policy if exists rstr_read on public.roster;
create policy rstr_read on public.roster for select to anon using (public.auth_ok());
drop policy if exists rstr_insert on public.roster;
create policy rstr_insert on public.roster for insert to anon with check (public.auth_admin());
drop policy if exists rstr_update on public.roster;
create policy rstr_update on public.roster for update to anon
  using (public.auth_admin()) with check (public.auth_admin());

-- marks：只能读写自己 seat 的标记
drop policy if exists mk_read on public.marks;
create policy mk_read on public.marks for select to anon
  using (public.auth_ok() and seat = public.auth_acc());
drop policy if exists mk_insert on public.marks;
create policy mk_insert on public.marks for insert to anon
  with check (public.auth_ok() and seat = public.auth_acc());
drop policy if exists mk_update on public.marks;
create policy mk_update on public.marks for update to anon
  using (public.auth_ok() and seat = public.auth_acc())
  with check (public.auth_ok() and seat = public.auth_acc());

-- fitrecs：只能读写自己账号的记录
drop policy if exists ftr_read on public.fitrecs;
create policy ftr_read on public.fitrecs for select to anon
  using (public.auth_ok() and acc = public.auth_acc());
drop policy if exists ftr_insert on public.fitrecs;
create policy ftr_insert on public.fitrecs for insert to anon
  with check (public.auth_ok() and acc = public.auth_acc());
drop policy if exists ftr_update on public.fitrecs;
create policy ftr_update on public.fitrecs for update to anon
  using (public.auth_ok() and acc = public.auth_acc())
  with check (public.auth_ok() and acc = public.auth_acc());

-- userdata：旧版兼容，只能读写自己的行
drop policy if exists ud_read on public.userdata;
create policy ud_read on public.userdata for select to anon
  using (public.auth_ok() and id = public.auth_acc());
drop policy if exists ud_insert on public.userdata;
create policy ud_insert on public.userdata for insert to anon
  with check (public.auth_ok() and id = public.auth_acc());
drop policy if exists ud_update on public.userdata;
create policy ud_update on public.userdata for update to anon
  using (public.auth_ok() and id = public.auth_acc())
  with check (public.auth_ok() and id = public.auth_acc());

-- feedback：提交仍公开；列表/标记仅管理员
drop policy if exists fb_read on public.feedback;
create policy fb_read on public.feedback for select to anon using (public.auth_admin());
drop policy if exists fb_update on public.feedback;
create policy fb_update on public.feedback for update to anon
  using (public.auth_admin()) with check (public.auth_admin());
-- fb_insert 保持 true

-- visits：埋点仍公开写入；统计仅管理员
drop policy if exists vs_read on public.visits;
create policy vs_read on public.visits for select to anon using (public.auth_admin());
-- vs_insert 保持 true
