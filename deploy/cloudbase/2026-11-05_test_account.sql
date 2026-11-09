-- 2026-11-05 · 审核测试账号（小程序提审用，唯一保留的审核相关能力）
--
-- 用户要求（2026-11-05 20:07）：「除添加账号外不要再有其他审核相关功能加入」。
-- 做法：在云端班级名单 private.class_ids 里新增一个测试身份，审核员用「学号 + 姓名」正常登录；
--   该账号 is_test=true，**不出现在班级成员列表**（class_members 过滤），不影响班级名单/统计展示；
--   仅当审核员主动用下列学号+姓名登录时生效。
--
-- 测试账号（交付说明中提供给审核员；审核结束可执行本文件末尾清理）：
--   学号 3260799999 / 姓名 测试账号
--
-- 应用：tcb db execute -e tool-d4gosudok46e0e081 --sql "<本文件内容>"（或用 python 分条执行）

alter table private.class_ids add column if not exists is_test boolean not null default false;

-- class_members 过滤测试身份（保证班级名单仍是 70 人、分类/名单选择器不出现测试账号）
create or replace function public.class_members()
 returns jsonb
 language plpgsql
 security definer
 set search_path to 'public', 'private', 'pg_temp'
as $function$
begin
  if not public.auth_ok() then
    return '[]'::jsonb;
  end if;
  return coalesce((
    select jsonb_agg(jsonb_build_object(
      'seat', c.seat, 'sid', c.sid, 'name', c.name,
      'role', coalesce(c.role, ''), 'badge', coalesce(c.badge, ''),
      'is_admin', coalesce(c.is_admin, false)
    ) order by c.seat)
    from private.class_ids c
    where not coalesce(c.is_test, false)
  ), '[]'::jsonb);
end
$function$;

grant execute on function public.class_members() to anon;

-- 测试身份（幂等）。seat 取 999，避开 1–70 的真实座号；sid 不与真实学号冲突。
insert into private.class_ids (seat, name, sid, role, badge, is_admin, is_test)
values (999, '测试账号', '3260799999', '', '', false, true)
on conflict (seat) do update set
  name = excluded.name,
  sid = excluded.sid,
  role = '', badge = '', is_admin = false, is_test = true;

-- 回滚/审核结束清理（会同时让该账号无法再次登录；已签发 token 需另删 class_sessions）：
--   delete from private.class_sessions where sid = '3260799999';
--   delete from private.class_ids where sid = '3260799999' and is_test = true;
--   -- 如需彻底移除字段与过滤逻辑（恢复原 class_members）：
--   -- alter table private.class_ids drop column if exists is_test;
--   -- create or replace function public.class_members() ...（见 2026-11-04 身份系统迁移前的定义；
--   --   即上方函数去掉 `where not coalesce(c.is_test,false)` 条件）
