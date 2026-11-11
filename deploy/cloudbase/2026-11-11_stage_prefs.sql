-- 2026-11-11 · 大屏自定义布局云同步 public.stage_prefs（仅本人可读写）
--
-- 用途（契约：web/tools/tests/_stage_sync_contract.md）：
--   用户要求「大屏所有自定义项目保持云同步」：模块顺序 / 12 列宽度 / 隐藏模块 / 上次演示 deck /
--   已下载标记 → 存 layout jsonb，按账号本人一行；**不新增/不修改 UD v6 跨端契约**。
--   隐私：只有 sid（账号主键）+ 布局 JSON + 更新时间；不存姓名/手机号，RLS 保证仅本人可读写。
--
-- 权限（仅本人）：
--   select / insert / update 均 `to anon using/with check (public.auth_sid() = sid)`；
--   无 delete 策略（客户端无需删除；清空布局写 `{}` 即可），故 anon 不授 DELETE。
--   public.auth_sid() 校验 private.class_sessions(token, expires_at)，无 token/过期 → NULL → 全部拒绝。
--
-- updated_at（LWW 关键）：契约 §2 客户端按 `layout.at` 与 `updated_at` 比较决定覆盖方向，
--   而 upsert 的 POST body 只有 `{sid, layout}`。若 updated_at 只在插入时写入，
--   后续写入不会更新 → 换设备时会误判「云端更旧」而覆盖别人较新的布局。
--   故加 BEFORE INSERT OR UPDATE 触发器统一置 `now()`（客户端无需发送该字段）。
--   ⚠ 含 plpgsql 函数体（分号），用 apply_sql_api.py 整文件应用。
--
-- 幂等：IF NOT EXISTS / CREATE OR REPLACE / DROP POLICY IF EXISTS / DROP TRIGGER IF EXISTS。
--
-- 应用：cd web/deploy/cloudbase
--       python apply_sql_api.py 2026-11-11_stage_prefs.sql
-- 验证：cd web
--       python deploy/cloudbase/verify_2026_11_11_shared_tables.py
--
-- 回滚：
--   DROP TABLE IF EXISTS public.stage_prefs;
--   DROP FUNCTION IF EXISTS public.stage_prefs_touch();
-- 仅回退 RLS/触发器（保留数据）：
--   DROP TRIGGER IF EXISTS stage_prefs_touch_trg ON public.stage_prefs;
--   DROP POLICY IF EXISTS stage_prefs_sel ON public.stage_prefs;
--   DROP POLICY IF EXISTS stage_prefs_ins ON public.stage_prefs;
--   DROP POLICY IF EXISTS stage_prefs_upd ON public.stage_prefs;
--   REVOKE SELECT, INSERT, UPDATE ON public.stage_prefs FROM anon;

CREATE TABLE IF NOT EXISTS public.stage_prefs (
  sid        text PRIMARY KEY,                        -- 班级账号学号（auth_sid()），仅本人可读写
  layout     jsonb NOT NULL DEFAULT '{}'::jsonb,      -- 大屏自定义布局（契约 §2，版本化 JSON）
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.stage_prefs ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON public.stage_prefs TO anon;

DROP POLICY IF EXISTS stage_prefs_sel ON public.stage_prefs;

CREATE POLICY stage_prefs_sel ON public.stage_prefs FOR SELECT TO anon USING (public.auth_sid() = sid);

DROP POLICY IF EXISTS stage_prefs_ins ON public.stage_prefs;

CREATE POLICY stage_prefs_ins ON public.stage_prefs FOR INSERT TO anon WITH CHECK (public.auth_sid() = sid);

DROP POLICY IF EXISTS stage_prefs_upd ON public.stage_prefs;

CREATE POLICY stage_prefs_upd ON public.stage_prefs FOR UPDATE TO anon USING (public.auth_sid() = sid) WITH CHECK (public.auth_sid() = sid);

CREATE OR REPLACE FUNCTION public.stage_prefs_touch()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS stage_prefs_touch_trg ON public.stage_prefs;

CREATE TRIGGER stage_prefs_touch_trg
BEFORE INSERT OR UPDATE ON public.stage_prefs
FOR EACH ROW EXECUTE FUNCTION public.stage_prefs_touch();
