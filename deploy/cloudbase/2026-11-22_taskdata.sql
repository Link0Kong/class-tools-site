-- 2026-11-22 · 任务模块云端同步 public.taskdata
--
-- 用途：网页端任务模块（个人任务/分组/排序/提醒/步骤/来源作业）跨设备同步。
--   - 一行 / 人：id = 学号（auth_acc()），blob = 任务数据 JSON 字符串，ts = 客户端数据版本（毫秒）。
--   - **任务附件不上云**：blob 中的 task.items[].attachments 由前端剥掉；附件仍只在本机。
--   - 与 userdata v6 分离：不影响现有 11 个 section / 小程序 / 安卓；任务同步失败不影响其它工具。
--
-- 权限：与 userdata 同一套班级 token 口径（X-Device-Id / X-Class-Token 由 auth_hdr() 接受）：
--   只能读写 id = auth_acc() 的本人行；匿名/过期 token 读写被拒。
--   upsert 用 POST + `Prefer: resolution=merge-duplicates`，不提供 DELETE（清空用空 blob）。
--
-- 幂等：IF NOT EXISTS / DROP POLICY IF EXISTS + CREATE POLICY，可重复应用。
--
-- 应用：cd web/deploy/cloudbase
--       python apply_sql.py 2026-11-22_taskdata.sql
-- 回滚（保留前端本地任务；仅失去跨设备同步）：
--   DROP TABLE IF EXISTS public.taskdata;

CREATE TABLE IF NOT EXISTS public.taskdata (
  id         text PRIMARY KEY,
  blob       text NOT NULL DEFAULT '',
  ts         bigint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.taskdata ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON public.taskdata TO anon;

DROP POLICY IF EXISTS taskdata_read ON public.taskdata;
CREATE POLICY taskdata_read ON public.taskdata FOR SELECT TO anon
  USING (public.auth_ok() AND id = public.auth_acc());

DROP POLICY IF EXISTS taskdata_insert ON public.taskdata;
CREATE POLICY taskdata_insert ON public.taskdata FOR INSERT TO anon
  WITH CHECK (public.auth_ok() AND id = public.auth_acc());

DROP POLICY IF EXISTS taskdata_update ON public.taskdata;
CREATE POLICY taskdata_update ON public.taskdata FOR UPDATE TO anon
  USING (public.auth_ok() AND id = public.auth_acc())
  WITH CHECK (public.auth_ok() AND id = public.auth_acc());
