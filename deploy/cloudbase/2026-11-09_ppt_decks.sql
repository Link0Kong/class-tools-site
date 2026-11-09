-- 2026-11-09 · PPT 演示（班级演示 / PPT-to-web 播放器）云端表
--
-- 目标：任何班级成员在三端（网页 / 微信小程序 / 安卓）上传 .ppt/.pptx → 本机转换机
--       （PowerPoint COM）一次性渲染成分步图片 + 内嵌视频/音频 → 任意设备流畅播放。
--
-- 契约（唯一真源）：web/ppt/CONTRACT.md
--
-- 表：
--   public.ppt_decks          演示文件（一行 = 一个 PPT）
--   public.ppt_upload_chunks  分片上传暂存（转换机取走后立即删除，不长期保留）
--
-- 权限模型（沿用现有班级 token RLS）：
--   · 读 ppt_decks：所有有效班级 token（auth_ok()）——班级内共享演示库
--   · 写 ppt_decks：本人 owner_sid = auth_sid()（上传/提交）；转换机用管理员 token 更新任意行
--   · 分片 chunks：本人可读写删；转换机（管理员 token）可读删
--   · 无 DELETE 策略给 decks（删除 = PATCH deleted=true 软删除，与站内其它表一致）
--
-- 应用（幂等，可重复执行）：
--   cd web/deploy/cloudbase
--   python apply_sql.py 2026-11-09_ppt_decks.sql
--
-- 回滚：
--   DROP TABLE IF EXISTS public.ppt_upload_chunks;
--   DROP TABLE IF EXISTS public.ppt_decks;

-- ---------------------------------------------------------------------------
-- §1 public.ppt_decks
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.ppt_decks (
  id            text PRIMARY KEY,
  title         text NOT NULL DEFAULT '',
  owner_sid     text NOT NULL DEFAULT '',
  owner_name    text NOT NULL DEFAULT '',
  client        text NOT NULL DEFAULT '',
  status        text NOT NULL DEFAULT 'uploading',
  progress      integer NOT NULL DEFAULT 0,
  error         text NOT NULL DEFAULT '',
  source_name   text NOT NULL DEFAULT '',
  source_size   bigint NOT NULL DEFAULT 0,
  chunk_count   integer NOT NULL DEFAULT 0,
  source_key    text NOT NULL DEFAULT '',
  slide_count   integer NOT NULL DEFAULT 0,
  step_count    integer NOT NULL DEFAULT 0,
  aspect        text NOT NULL DEFAULT '16:9',
  cover_url     text NOT NULL DEFAULT '',
  manifest      jsonb NOT NULL DEFAULT '{}'::jsonb,
  converter     text NOT NULL DEFAULT '',
  deleted       boolean NOT NULL DEFAULT false,
  created_at    bigint NOT NULL DEFAULT 0,
  updated_at    bigint NOT NULL DEFAULT 0,
  converted_at  bigint NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ppt_decks_status_idx ON public.ppt_decks (status, created_at);
CREATE INDEX IF NOT EXISTS ppt_decks_owner_idx ON public.ppt_decks (owner_sid);

ALTER TABLE public.ppt_decks ENABLE ROW LEVEL SECURITY;

GRANT USAGE ON SCHEMA public TO anon;

GRANT SELECT, INSERT, UPDATE ON public.ppt_decks TO anon;

DROP POLICY IF EXISTS pd_read ON public.ppt_decks;

CREATE POLICY pd_read ON public.ppt_decks FOR SELECT TO anon USING (public.auth_ok());

DROP POLICY IF EXISTS pd_insert ON public.ppt_decks;

CREATE POLICY pd_insert ON public.ppt_decks FOR INSERT TO anon WITH CHECK (public.auth_ok() AND owner_sid = COALESCE(public.auth_sid(), ''::text));

DROP POLICY IF EXISTS pd_update ON public.ppt_decks;

CREATE POLICY pd_update ON public.ppt_decks FOR UPDATE TO anon USING (public.auth_admin() OR owner_sid = COALESCE(public.auth_sid(), ''::text)) WITH CHECK (public.auth_admin() OR owner_sid = COALESCE(public.auth_sid(), ''::text));

-- ---------------------------------------------------------------------------
-- §2 public.ppt_upload_chunks（分片暂存，转换机消费后删除）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.ppt_upload_chunks (
  deck_id   text NOT NULL,
  owner_sid text NOT NULL DEFAULT '',
  idx       integer NOT NULL,
  data      text NOT NULL,
  ts        bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (deck_id, idx)
);

CREATE INDEX IF NOT EXISTS ppt_chunks_owner_idx ON public.ppt_upload_chunks (deck_id, owner_sid);

ALTER TABLE public.ppt_upload_chunks ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.ppt_upload_chunks TO anon;

DROP POLICY IF EXISTS pc_read ON public.ppt_upload_chunks;

CREATE POLICY pc_read ON public.ppt_upload_chunks FOR SELECT TO anon USING (public.auth_admin() OR owner_sid = COALESCE(public.auth_sid(), ''::text));

DROP POLICY IF EXISTS pc_insert ON public.ppt_upload_chunks;

CREATE POLICY pc_insert ON public.ppt_upload_chunks FOR INSERT TO anon WITH CHECK (public.auth_ok() AND owner_sid = COALESCE(public.auth_sid(), ''::text));

-- UPDATE 仅用于分片断点重传的 upsert（INSERT ... ON CONFLICT DO UPDATE 需要 UPDATE 权限 + 策略）
DROP POLICY IF EXISTS pc_update ON public.ppt_upload_chunks;

CREATE POLICY pc_update ON public.ppt_upload_chunks FOR UPDATE TO anon USING (public.auth_admin() OR owner_sid = COALESCE(public.auth_sid(), ''::text)) WITH CHECK (public.auth_admin() OR owner_sid = COALESCE(public.auth_sid(), ''::text));

DROP POLICY IF EXISTS pc_delete ON public.ppt_upload_chunks;

CREATE POLICY pc_delete ON public.ppt_upload_chunks FOR DELETE TO anon USING (public.auth_admin() OR owner_sid = COALESCE(public.auth_sid(), ''::text));
