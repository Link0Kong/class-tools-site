-- 2026-11-18 · 访问统计：记录具体登录端（client）
--
-- 用户需求：「将所有端的统计工具统一更新为按最新登录顺序排序，默认打开为今天，
--   时间精确到分钟，记录具体登录端，忽略测试账号」。
--
-- 说明：
--   * 旧行 client 为空串（升级前没有记录端），统计页显示「未记录」；
--   * 新行由客户端写 web / mp / android / win / harmony（见 《统计多端·最新登录》契约（内部归档））；
--   * slot 仍保持 YYYY-MM-DD-HH（既有小时去重键），ts 为毫秒时间，统计页显示到分钟；
--   * 表级 grant/RLS 不变，新增列自动继承；不新增策略，不改变写入权限。
--
-- 应用（幂等）：cd web/deploy/cloudbase && python apply_sql.py 2026-11-18_visits_client.sql
-- 回滚：ALTER TABLE public.visits DROP COLUMN IF EXISTS client;

ALTER TABLE public.visits ADD COLUMN IF NOT EXISTS client text NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS visits_ts_idx ON public.visits (ts DESC);
CREATE INDEX IF NOT EXISTS visits_slot_idx ON public.visits (slot DESC);
