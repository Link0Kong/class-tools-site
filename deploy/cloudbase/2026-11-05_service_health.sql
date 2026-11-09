-- 2026-11-05 · 依赖服务健康心跳表 public.service_health（班级工具站 v2.0.0「诊断」页）
--
-- 用途：采集主机（C:\briefdesk\scripts\health_beat.py，由 C:\briefdesk\scripts\watchdog.py
--   每 5 分钟调用）把 13 个依赖服务的运行状态上报到云端；管理员在网页「诊断」页读取展示。
--   契约：web/tools/tests/health_monitor_spec.md §1（13 行 id/name/kind）与 §2（本表）。
--   一次上报写 13 行（id 固定）；逐行 PATCH service_health?id=eq.<id>，行不存在时 POST。
--   checked_at = 采集主机检测时刻（unix ms）；updated_at = 云端行更新时间。
--
-- 权限：仅管理员可读写（RLS 统一校验班级 token；非管理员 / 匿名 SELECT 返回 []）。
--   依赖已有函数 public.auth_admin()（= public.auth_ok() + private.class_ids.is_admin）。
--   anon 需要 SELECT/INSERT/UPDATE 授权，但无 DELETE 策略 ⇒ anon 删除必然 401。
--
-- 应用（幂等，可重复执行；tcb CLI 一次只吃一条语句，需把每条语句压成一行）：
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE TABLE IF NOT EXISTS public.service_health (...)"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "ALTER TABLE public.service_health ENABLE ROW LEVEL SECURITY"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "GRANT SELECT, INSERT, UPDATE ON public.service_health TO anon"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP POLICY IF EXISTS sh_read ON public.service_health"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE POLICY sh_read ON public.service_health FOR SELECT TO anon USING (public.auth_admin())"
--   …… sh_insert / sh_update 同理（见下方语句）。
--   本文件也在 C:\briefdesk\scripts\sql\service_health.sql 保留一份副本（内容一致）。
--
-- 回滚：
--   DROP TABLE IF EXISTS public.service_health;

CREATE TABLE IF NOT EXISTS public.service_health (
  id          text PRIMARY KEY,
  name        text NOT NULL,
  kind        text NOT NULL DEFAULT 'local',
  status      text NOT NULL DEFAULT 'unknown',
  detail      text NOT NULL DEFAULT '',
  meta        jsonb NOT NULL DEFAULT '{}'::jsonb,
  checked_at  bigint NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.service_health ENABLE ROW LEVEL SECURITY;

GRANT USAGE ON SCHEMA public TO anon;

GRANT SELECT, INSERT, UPDATE ON public.service_health TO anon;

DROP POLICY IF EXISTS sh_read ON public.service_health;

CREATE POLICY sh_read ON public.service_health FOR SELECT TO anon USING (public.auth_admin());

DROP POLICY IF EXISTS sh_insert ON public.service_health;

CREATE POLICY sh_insert ON public.service_health FOR INSERT TO anon WITH CHECK (public.auth_admin());

DROP POLICY IF EXISTS sh_update ON public.service_health;

CREATE POLICY sh_update ON public.service_health FOR UPDATE TO anon USING (public.auth_admin()) WITH CHECK (public.auth_admin());
