-- 2026-11-20 · 访问统计：记录应用版本（ver）与访问设备（dev）
--
-- 用户需求：「重构各端统计模块，要求可以可视化和简洁直观的展示不同账号的
--   访问次数，访问设备，使用版本等信息，做到更加详细的内容」。
--
-- 说明：
--   * 旧行 ver/dev 为空串（升级前没有记录），统计页显示「未记录」；
--   * 新行由客户端写短标签（ver ≤32、dev ≤48，只含机型/系统/浏览器，不含个人信息）；
--   * 既有 client/slot/sid/name/did/ts 不变，小时去重与 RLS 不变；
--   * 表级 grant 是整表，新增列自动继承，不需要新增策略。
--
-- 应用（幂等）：cd web/deploy/cloudbase && python apply_sql.py 2026-11-20_visits_ver_dev.sql
-- 回滚：ALTER TABLE public.visits DROP COLUMN IF EXISTS ver, DROP COLUMN IF EXISTS dev;
--       （回滚会让新客户端写失败，必须同时回退客户端）

ALTER TABLE public.visits ADD COLUMN IF NOT EXISTS ver text NOT NULL DEFAULT '';

ALTER TABLE public.visits ADD COLUMN IF NOT EXISTS dev text NOT NULL DEFAULT '';

COMMENT ON COLUMN public.visits.ver IS '客户端应用版本短标签（≤32，空=未记录）';
COMMENT ON COLUMN public.visits.dev IS '访问设备短标签（≤48，机型/系统/浏览器，不含个人信息；空=未记录）';
