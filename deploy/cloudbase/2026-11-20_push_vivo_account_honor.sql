-- 2026-11-20 · 推送/账号绑定 provider 扩展（vivo 推送 + 荣耀账号）
--
-- 背景（用户 2026-11-20 要求）：
--   * 接入 vivo 推送服务（客户端 provider='vivo' 上传 regId，服务端 vivo_push.py 下发）；
--   * 接入荣耀账号服务（account_bindings provider='honor'，一个学号最多 3 个，与 OPPO 分开计数）。
--
-- 原约束（部署实测）：
--   push_tokens_provider_check     CHECK (provider = ANY (ARRAY['oppo','harmony']))
--   account_bindings_provider_check CHECK (provider = 'oppo')
-- 本迁移只放宽 CHECK，不动 RLS / 触发器 / 唯一键（upsert 冲突键仍为 provider,token）。
--
-- 应用（幂等）：cd web/deploy/cloudbase && python apply_sql.py 2026-11-20_push_vivo_account_honor.sql
-- 回滚：把两个 CHECK 还原为上面的原定义（先删除 provider='vivo'/'honor' 的行）。

ALTER TABLE public.push_tokens DROP CONSTRAINT IF EXISTS push_tokens_provider_check;
ALTER TABLE public.push_tokens ADD CONSTRAINT push_tokens_provider_check
  CHECK (provider IN ('oppo', 'harmony', 'vivo'));

ALTER TABLE public.account_bindings DROP CONSTRAINT IF EXISTS account_bindings_provider_check;
ALTER TABLE public.account_bindings ADD CONSTRAINT account_bindings_provider_check
  CHECK (provider IN ('oppo', 'honor'));
