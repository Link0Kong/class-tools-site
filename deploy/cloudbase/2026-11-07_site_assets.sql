-- 2026-11-07 · 课表快照内迁 + 站点配置开关（班级工具站 v2.0.0）
--
-- 契约：web/tools/tests/dns_pause_tt_health_spec.md §1（site_assets）与 §2（site_config）。
--
-- 用途：
--   public.site_assets：站点静态资产快照。当前只有一行 id='tt'（= tools/tt.json 的原始对象，body/meta 见 §1）。
--     写者：本机 web/jwxt/tt_cloud.py（每次课表同步成功后 PATCH/POST，管理员 token）。
--     读：GET site_assets?id=eq.tt。RLS = public.auth_ok()（任意有效班级 token，网页 X-Device-Id / 小程序 X-Class-Token）。
--   public.site_config：站点开关配置。当前只有一行 id='web'（value = {paused,note,paused_at}）。
--     写者：本机 C:\briefdesk\scripts\web_pause.py --on/--off（管理员 token）。
--     读：管理员（云函数 health_probe 用管理员 token 读，决定 site_static/site_tls 的暂停语义）。
--
-- 权限：anon 需要 SELECT/INSERT/UPDATE 授权，但不给 DELETE 策略 ⇒ anon 删除必然被拒。
--   site_assets 读 = auth_ok()（全班可读课表）；site_config 读写 = auth_admin()（仅管理员）。
--
-- 应用（幂等，可重复执行；tcb CLI 一次只吃一条语句，需把每条语句压成一行）：
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE SCHEMA IF NOT EXISTS public"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE TABLE IF NOT EXISTS public.site_assets (id text PRIMARY KEY, body jsonb NOT NULL, meta jsonb NOT NULL DEFAULT '{}'::jsonb, updated_at timestamptz NOT NULL DEFAULT now())"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "ALTER TABLE public.site_assets ENABLE ROW LEVEL SECURITY"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "GRANT USAGE ON SCHEMA public TO anon"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "GRANT SELECT, INSERT, UPDATE ON public.site_assets TO anon"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP POLICY IF EXISTS sa_read ON public.site_assets"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE POLICY sa_read ON public.site_assets FOR SELECT TO anon USING (public.auth_ok())"
--   ……sa_insert / sa_update / sc_* 同理（见下方语句；每条 DROP POLICY 先跑再 CREATE）。
--
-- 回滚：
--   DROP TABLE IF EXISTS public.site_assets;
--   DROP TABLE IF EXISTS public.site_config;

-- ---------------------------------------------------------------------------
-- §1 public.site_assets（课表快照）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.site_assets (
  id          text PRIMARY KEY,
  body        jsonb NOT NULL,
  meta        jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.site_assets ENABLE ROW LEVEL SECURITY;

GRANT USAGE ON SCHEMA public TO anon;

GRANT SELECT, INSERT, UPDATE ON public.site_assets TO anon;

DROP POLICY IF EXISTS sa_read ON public.site_assets;

CREATE POLICY sa_read ON public.site_assets FOR SELECT TO anon USING (public.auth_ok());

DROP POLICY IF EXISTS sa_insert ON public.site_assets;

CREATE POLICY sa_insert ON public.site_assets FOR INSERT TO anon WITH CHECK (public.auth_admin());

DROP POLICY IF EXISTS sa_update ON public.site_assets;

CREATE POLICY sa_update ON public.site_assets FOR UPDATE TO anon USING (public.auth_admin()) WITH CHECK (public.auth_admin());

-- ---------------------------------------------------------------------------
-- §2 public.site_config（网页暂停开关）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.site_config (
  id          text PRIMARY KEY,
  value       jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.site_config ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON public.site_config TO anon;

DROP POLICY IF EXISTS sc_read ON public.site_config;

CREATE POLICY sc_read ON public.site_config FOR SELECT TO anon USING (public.auth_admin());

DROP POLICY IF EXISTS sc_insert ON public.site_config FOR INSERT TO anon WITH CHECK (public.auth_admin());

DROP POLICY IF EXISTS sc_update ON public.site_config FOR UPDATE TO anon USING (public.auth_admin()) WITH CHECK (public.auth_admin());
