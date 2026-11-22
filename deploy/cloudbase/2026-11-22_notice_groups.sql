-- 2026-11-22 · 通知管理（网页管理员页）配套：逐群可见人群支持「指定成员（座号）」
--
-- 背景：网页通知页新增仅管理员可见的「通知管理」页（web/tools/tests/nt_admin_spec.md），
--       可按群设置采集开关与通知可见人群。现有 audience 已支持
--       all / committee / league / admin / sid:<学号> / set:<名单>；
--       本迁移只补一种取值，让管理员可以按班级座号指定可见成员：
--           seats:1,8,12
--
-- 内容：
--   1) public.auth_seat()：当前班级 token 对应的座号（private.class_ids.seat）；
--   2) public.notice_audience_visible(text)：把原 nt_read 的判定集中到一个函数，并新增 seats: 分支；
--   3) 重建 public.notices 的 nt_read 策略为 auth_ok() AND notice_audience_visible(audience)。
--
-- 口径（与 2026-11-04/11-05 的 audience 完全一致，不改变既有取值行为）：
--   all                   已认证全班
--   admin                 仅管理员
--   committee             班委
--   league                团员
--   sid:<学号>            指定学号（原样保留）
--   set:<名单>            private.class_audience（志愿者/观众/献血/评议/舍长/红会干事）
--   seats:1,8,12          座号命中；只存座号，不存/不返回学号
--   管理员始终可见全部（原策略中的 OR auth_is_admin()）。
--
-- 应用（幂等）：
--   cd G:\ClassTools\web\deploy\cloudbase
--   python apply_sql.py 2026-11-22_notice_groups.sql
--
-- 回滚：
--   DROP POLICY IF EXISTS nt_read ON public.notices;
--   CREATE POLICY nt_read ON public.notices FOR SELECT TO anon USING (
--     public.auth_ok() AND (
--       coalesce(audience, 'all') = 'all' OR public.auth_is_admin()
--       OR (audience = 'admin' AND public.auth_is_admin())
--       OR (audience = 'committee' AND public.auth_is_committee())
--       OR (audience = 'league' AND public.auth_is_league())
--       OR (audience LIKE 'set:%' AND public.auth_in_audience(substring(audience from 5)))
--       OR (audience = 'sid:' || coalesce(public.auth_sid(), ''))
--     ));
--   DROP FUNCTION IF EXISTS public.notice_audience_visible(text);
--   DROP FUNCTION IF EXISTS public.auth_seat();

-- ---------------------------------------------------------------------------
-- §1 当前 token 的座号
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.auth_seat()
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
  select c.seat
    from private.class_sessions s
    join private.class_ids c on c.sid = s.sid
   where s.token = public.auth_hdr()
     and s.expires_at > now()
   limit 1
$fn$;

REVOKE ALL ON FUNCTION public.auth_seat() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.auth_seat() TO anon;

-- ---------------------------------------------------------------------------
-- §2 可见范围判定（集中原 nt_read 逻辑 + seats:）
--    注意：字符串匹配 seats 避免非法值导致 cast 异常（fail-closed）。
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.notice_audience_visible(p_audience text)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $fn$
  select case
    when coalesce(p_audience, 'all') = 'all' then true
    when public.auth_is_admin() then true
    when p_audience = 'admin' then public.auth_is_admin()
    when p_audience = 'committee' then public.auth_is_committee()
    when p_audience = 'league' then public.auth_is_league()
    when p_audience like 'set:%' then public.auth_in_audience(substring(p_audience from 5))
    when p_audience like 'seats:%' then
      (',' || substring(p_audience from 7) || ',')
        like '%,' || coalesce(public.auth_seat()::text, '-1') || ',%'
    else p_audience = 'sid:' || coalesce(public.auth_sid(), '')
  end
$fn$;

REVOKE ALL ON FUNCTION public.notice_audience_visible(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.notice_audience_visible(text) TO anon;

-- ---------------------------------------------------------------------------
-- §3 重建 notices 读策略（其余策略 nt_insert/nt_update 不动）
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS nt_read ON public.notices;

CREATE POLICY nt_read ON public.notices
  FOR SELECT TO anon
  USING (public.auth_ok() AND public.notice_audience_visible(audience));

NOTIFY pgrst, 'reload schema';
