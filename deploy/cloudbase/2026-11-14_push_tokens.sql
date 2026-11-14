-- 2026-11-14 · OPPO 推送设备 token（班级通知服务端推送）
--
-- 背景（用户 2026-11-14 晚需求「尝试将通知接入 oppo 官方 sdk」）：
--   App 未运行/被系统清理时，服务端（本机 briefdesk 管线）通过 OPPO PUSH 单点推送
--   通知栏消息；客户端注册拿到 RegistrationID 后写入本表，服务端按设备逐条推送。
--
-- 权限模型（与现有迁移一致）：
--   读自己：public.auth_ok() 且 sid = auth_sid()（只返回本人行）
--   写/改/删自己：同上；客户端 upsert 用 on_conflict=provider,token
--   管理员读取全量：public.auth_admin()（本机管线用 admin 班级 token 读取所有设备）
--   管理员删除：public.auth_admin()（注销/清理失效设备）
--   本表不含姓名/学号/手机号；sid 为内部会话标识，不对外展示。
--
-- 应用（幂等）：cd web/deploy/cloudbase && python apply_sql.py 2026-11-14_push_tokens.sql
-- 回滚：DROP TABLE IF EXISTS public.push_tokens;

CREATE TABLE IF NOT EXISTS public.push_tokens (
  id           bigserial PRIMARY KEY,
  sid          text NOT NULL DEFAULT public.auth_sid(),
  provider     text NOT NULL DEFAULT 'oppo' CHECK (provider IN ('oppo')),
  token        text NOT NULL,                 -- OPPO RegistrationID（CN_...）
  device       text NOT NULL DEFAULT '',      -- 厂商+机型（无姓名/学号）
  app_version  text NOT NULL DEFAULT '',
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, token)
);

CREATE INDEX IF NOT EXISTS push_tokens_sid_idx ON public.push_tokens (sid);
CREATE INDEX IF NOT EXISTS push_tokens_provider_idx ON public.push_tokens (provider, updated_at DESC);

ALTER TABLE public.push_tokens ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.push_tokens TO anon;
GRANT USAGE, SELECT ON SEQUENCE public.push_tokens_id_seq TO anon;

DROP POLICY IF EXISTS pt_read_own ON public.push_tokens;
CREATE POLICY pt_read_own ON public.push_tokens FOR SELECT TO anon
  USING (public.auth_ok() AND sid = public.auth_sid());

DROP POLICY IF EXISTS pt_insert_own ON public.push_tokens;
CREATE POLICY pt_insert_own ON public.push_tokens FOR INSERT TO anon
  WITH CHECK (public.auth_ok() AND sid = coalesce(public.auth_sid(), ''));

DROP POLICY IF EXISTS pt_update_own ON public.push_tokens;
CREATE POLICY pt_update_own ON public.push_tokens FOR UPDATE TO anon
  USING (public.auth_ok() AND sid = public.auth_sid())
  WITH CHECK (public.auth_ok() AND sid = public.auth_sid());

DROP POLICY IF EXISTS pt_delete_own ON public.push_tokens;
CREATE POLICY pt_delete_own ON public.push_tokens FOR DELETE TO anon
  USING (public.auth_ok() AND sid = public.auth_sid());

DROP POLICY IF EXISTS pt_admin_read ON public.push_tokens;
CREATE POLICY pt_admin_read ON public.push_tokens FOR SELECT TO anon
  USING (public.auth_admin());

DROP POLICY IF EXISTS pt_admin_delete ON public.push_tokens;
CREATE POLICY pt_admin_delete ON public.push_tokens FOR DELETE TO anon
  USING (public.auth_admin());
