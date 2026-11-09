-- 回滚 2026-10-18 的权限收紧：恢复匿名全表读写（仅供紧急回滚，平时不要执行）
drop policy if exists us_read on public.users;
create policy us_read on public.users for select to anon using (true);
drop policy if exists us_insert on public.users;
create policy us_insert on public.users for insert to anon with check (true);

drop policy if exists rstr_read on public.roster;
create policy rstr_read on public.roster for select to anon using (true);
drop policy if exists rstr_insert on public.roster;
create policy rstr_insert on public.roster for insert to anon with check (true);
drop policy if exists rstr_update on public.roster;
create policy rstr_update on public.roster for update to anon using (true) with check (true);

drop policy if exists mk_read on public.marks;
create policy mk_read on public.marks for select to anon using (true);
drop policy if exists mk_insert on public.marks;
create policy mk_insert on public.marks for insert to anon with check (true);
drop policy if exists mk_update on public.marks;
create policy mk_update on public.marks for update to anon using (true) with check (true);

drop policy if exists ftr_read on public.fitrecs;
create policy ftr_read on public.fitrecs for select to anon using (true);
drop policy if exists ftr_insert on public.fitrecs;
create policy ftr_insert on public.fitrecs for insert to anon with check (true);
drop policy if exists ftr_update on public.fitrecs;
create policy ftr_update on public.fitrecs for update to anon using (true) with check (true);

drop policy if exists ud_read on public.userdata;
create policy ud_read on public.userdata for select to anon using (true);
drop policy if exists ud_insert on public.userdata;
create policy ud_insert on public.userdata for insert to anon with check (true);
drop policy if exists ud_update on public.userdata;
create policy ud_update on public.userdata for update to anon using (true) with check (true);

drop policy if exists fb_read on public.feedback;
create policy fb_read on public.feedback for select to anon using (true);
drop policy if exists fb_update on public.feedback;
create policy fb_update on public.feedback for update to anon using (true) with check (true);

drop policy if exists vs_read on public.visits;
create policy vs_read on public.visits for select to anon using (true);

drop function if exists public.auth_admin();
drop function if exists public.auth_ok();
drop function if exists public.auth_hash();
drop function if exists public.auth_acc();
drop function if exists public.auth_hdr();
