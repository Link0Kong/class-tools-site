-- 2026-11-17 · OPPO 账号绑定学号 + OPPO 快捷登录（账号服务）
--
-- 用户 2026-11-17 要求：允许 OPPO 账号绑定学号（一个学号最多绑定 3 个不同 OPPO 账号），
-- 允许 OPPO 账号快捷登录。安全模型：客户端只拿 OPPO authCode，由 ECS 账号服务
-- （deploy/account_app.py）用账号服务 AppSecret 调 OPPO /oauth2/token/token-code 换
-- openId，再由该服务写本表/发班级 token；客户端无法伪造 openid。
--
-- 本表只允许管理员 token（ECS 服务持有）读写，匿名/普通班级 token 无直连权限；
-- 不暴露 openid/姓名给其他用户。一个学号最多 3 行（DB 触发器强制，ECS 也做友好提示）。
--
-- 应用（幂等）：cd web/deploy/cloudbase && python apply_sql.py 2026-11-17_account_bindings.sql
-- 回滚：DROP TRIGGER IF EXISTS account_bindings_limit_trg ON public.account_bindings;
--       DROP FUNCTION IF EXISTS public.account_bindings_limit();
--       DROP TABLE IF EXISTS public.account_bindings;

CREATE TABLE IF NOT EXISTS public.account_bindings (
  id          bigserial PRIMARY KEY,
  sid         text NOT NULL,
  name        text NOT NULL DEFAULT '',
  provider    text NOT NULL DEFAULT 'oppo' CHECK (provider IN ('oppo')),
  openid      text NOT NULL,
  nickname    text NOT NULL DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, openid),
  UNIQUE (provider, sid, openid)
);

CREATE INDEX IF NOT EXISTS account_bindings_sid_idx ON public.account_bindings (sid);

ALTER TABLE public.account_bindings ENABLE ROW LEVEL SECURITY;

-- 不给 anon 任何直接策略；只有管理员 token（ECS 账号服务）可读写
GRANT SELECT, INSERT, UPDATE, DELETE ON public.account_bindings TO anon;
GRANT USAGE, SELECT ON SEQUENCE public.account_bindings_id_seq TO anon;

DROP POLICY IF EXISTS account_bindings_admin ON public.account_bindings;
CREATE POLICY account_bindings_admin ON public.account_bindings FOR ALL TO anon
  USING (public.auth_admin()) WITH CHECK (public.auth_admin());

-- 一个学号最多绑定 3 个 OPPO 账号（DB 级兜底；ECS 另做友好提示）
CREATE OR REPLACE FUNCTION public.account_bindings_limit()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
  v_count int;
BEGIN
  SELECT count(*) INTO v_count
  FROM public.account_bindings
  WHERE provider = NEW.provider AND sid = NEW.sid;
  IF v_count >= 3 THEN
    RAISE EXCEPTION 'binding_limit_reached' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS account_bindings_limit_trg ON public.account_bindings;
CREATE TRIGGER account_bindings_limit_trg
BEFORE INSERT ON public.account_bindings
FOR EACH ROW EXECUTE FUNCTION public.account_bindings_limit();
