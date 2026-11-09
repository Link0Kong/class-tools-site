-- 2026-11-06 · 宿舍电费历史采样表 public.power_history（电费页趋势/指标数据源）
--
-- 用途：同步脚本 C:\briefdesk\scripts\sync_power_cloud.py 每次成功写入 public.power 一行后，
--   追加一条同 ts 的历史采样（roomverify + quantity + unit）；`--backfill-log` 可从
--   C:\briefdesk\logs\power-sync.log 回填历史，页面用它画「近 24h 趋势 / 估算可用天数 / 近 24h 用电」。
--
-- 权限（与 public.power 同一套 RLS 写法）：
--   读：public.auth_ok()（有效班级 token）；匿名/过期 token 读回 []
--   写/删：public.auth_admin()（仅管理员 token；同步脚本用管理员 token 追加/清理）
--   anon 授 SELECT/INSERT/DELETE + 序列 USAGE（bigserial 自增）
--
-- 应用（tcb CLI 一次一条语句，每条压成一行；语句与下方一致）：
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE TABLE IF NOT EXISTS public.power_history (id bigserial PRIMARY KEY, roomverify text NOT NULL, quantity numeric, unit text NOT NULL DEFAULT '度', ts timestamptz NOT NULL DEFAULT now())"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE INDEX IF NOT EXISTS power_history_rv_ts_idx ON public.power_history (roomverify, ts DESC)"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "ALTER TABLE public.power_history ENABLE ROW LEVEL SECURITY"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "GRANT SELECT, INSERT, DELETE ON public.power_history TO anon"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "GRANT USAGE, SELECT ON SEQUENCE public.power_history_id_seq TO anon"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP POLICY IF EXISTS ph_read ON public.power_history"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE POLICY ph_read ON public.power_history FOR SELECT TO anon USING (public.auth_ok())"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP POLICY IF EXISTS ph_insert ON public.power_history"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE POLICY ph_insert ON public.power_history FOR INSERT TO anon WITH CHECK (public.auth_admin())"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP POLICY IF EXISTS ph_delete ON public.power_history"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE POLICY ph_delete ON public.power_history FOR DELETE TO anon USING (public.auth_admin())"
--
-- 回滚：
--   DROP TABLE IF EXISTS public.power_history;
-- 仅回退 RLS：DROP POLICY ph_read/ph_insert/ph_delete；REVOKE SELECT, INSERT, DELETE ON public.power_history FROM anon;

CREATE TABLE IF NOT EXISTS public.power_history (
  id          bigserial PRIMARY KEY,
  roomverify  text NOT NULL,
  quantity    numeric,
  unit        text NOT NULL DEFAULT '度',
  ts          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS power_history_rv_ts_idx ON public.power_history (roomverify, ts DESC);

ALTER TABLE public.power_history ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, DELETE ON public.power_history TO anon;

GRANT USAGE, SELECT ON SEQUENCE public.power_history_id_seq TO anon;

DROP POLICY IF EXISTS ph_read ON public.power_history;

CREATE POLICY ph_read ON public.power_history FOR SELECT TO anon USING (public.auth_ok());

DROP POLICY IF EXISTS ph_insert ON public.power_history;

CREATE POLICY ph_insert ON public.power_history FOR INSERT TO anon WITH CHECK (public.auth_admin());

DROP POLICY IF EXISTS ph_delete ON public.power_history;

CREATE POLICY ph_delete ON public.power_history FOR DELETE TO anon USING (public.auth_admin());
