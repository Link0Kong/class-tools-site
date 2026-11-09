-- 2026-11-04 · 访问统计 / 反馈：本人行 SELECT 策略（修复非管理员写入 401）
--
-- 背景（实测根因）：
--   前端写 visits / feedback 时带 PostgREST 的 `Prefer: return=representation`
--   （网页 cbPost → cbH(true)；小程序 headers(true)）。
--   PostgREST 对 INSERT + returning 要求新插入行同时能被 SELECT 策略看到，
--   而原来这两张表的 SELECT 策略只有 auth_admin()：
--     visits:   vs_read  using (auth_admin())
--     feedback: fb_read  using (auth_admin())
--   → 非管理员 INSERT 被拒：401 DATABASE_42501 "new row violates row-level security policy"，
--     前端 catch 后静默失败 → 统计只有管理员自己、普通同学反馈提交失败。
--
-- 修法：SELECT 策略放行「管理员 OR 本人行」；写入策略不变（visits 仍只能写自己 sid，
--   feedback 仍 auth_ok）。这样 returning 能拿到自己刚插入的行，且不暴露他人数据。
--
-- 应用：cd web\deploy\cloudbase && tcb db execute -e tool-d4gosudok46e0e081 --sql "<本文件内容>"
-- 回滚：见文件末尾。

drop policy if exists vs_read on public.visits;
create policy vs_read on public.visits for select to anon
  using (public.auth_admin() OR (public.auth_ok() AND sid = public.auth_acc()));

drop policy if exists fb_read on public.feedback;
create policy fb_read on public.feedback for select to anon
  using (public.auth_admin() OR (public.auth_ok() AND acc = public.auth_acc()));

-- 回滚（恢复 2026-10-18 收紧后的行为）：
--   drop policy if exists vs_read on public.visits;
--   create policy vs_read on public.visits for select to anon using (public.auth_admin());
--   drop policy if exists fb_read on public.feedback;
--   create policy fb_read on public.feedback for select to anon using (public.auth_admin());
