-- 2026-11-11 · 投票功能（临时限时 + 长时截止 + 高度自定义标题/选项）云端表与 RPC
--
-- 契约唯一真源：web/vote/CONTRACT.md
--
-- 设计取舍（重要）：
--   * polls / poll_votes 两张表 **不对 anon 暴露任何直连权限**（RLS 开启、无策略、REVOKE），
--     所有读写只经下面的 SECURITY DEFINER RPC —— 防止绕过规则（改他人投票、读他人投票明细、超选、截止后投票）；
--   * 任何 RPC 响应都不返回学号（sid）：投票人只返回姓名（匿名投票连姓名也不返回）；
--   * 每人每投票一行 poll_votes（UNIQUE(poll_id,sid)），单选/多选上限、截止时间都由服务端 clock_timestamp() 判定；
--   * 提前结束/延长/重开/删除/编辑也全部走 RPC（poll_manage），owner 或管理员才允许；
--   * 删除 = 软删 deleted=true；anon 永远没有 DELETE。
--
-- 应用（幂等，可重复执行）：
--   cd web/deploy/cloudbase
--   python apply_sql.py 2026-11-11_polls.sql
--
-- 回滚：
--   DROP FUNCTION IF EXISTS public.poll_manage(text,text,text,text,jsonb,jsonb,bigint);
--   DROP FUNCTION IF EXISTS public.poll_submit(text,jsonb);
--   DROP FUNCTION IF EXISTS public.poll_detail(text);
--   DROP FUNCTION IF EXISTS public.poll_list();
--   DROP FUNCTION IF EXISTS public.poll_create(text,text,text,text,jsonb,jsonb,bigint);
--   DROP FUNCTION IF EXISTS public.poll_norm_settings(jsonb,integer);
--   DROP FUNCTION IF EXISTS public.poll_norm_options(jsonb);
--   DROP FUNCTION IF EXISTS public.poll_results_visible(jsonb,boolean,boolean);
--   DROP TABLE IF EXISTS public.poll_votes;
--   DROP TABLE IF EXISTS public.polls;

-- ---------------------------------------------------------------------------
-- §1 表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.polls (
  id          text PRIMARY KEY,
  title       text NOT NULL,
  description text NOT NULL DEFAULT '',
  mode        text NOT NULL DEFAULT 'long',
  owner_sid   text NOT NULL DEFAULT '',
  owner_name  text NOT NULL DEFAULT '',
  options     jsonb NOT NULL,
  settings    jsonb NOT NULL,
  deadline    bigint NOT NULL DEFAULT 0,
  status      text NOT NULL DEFAULT 'open',
  closed_at   bigint NOT NULL DEFAULT 0,
  deleted     boolean NOT NULL DEFAULT false,
  created_at  bigint NOT NULL DEFAULT 0,
  updated_at  bigint NOT NULL DEFAULT 0,
  CONSTRAINT polls_title_len   CHECK (char_length(title) BETWEEN 1 AND 80),
  CONSTRAINT polls_desc_len    CHECK (char_length(description) <= 500),
  CONSTRAINT polls_options_len CHECK (jsonb_array_length(options) BETWEEN 2 AND 20),
  CONSTRAINT polls_mode_chk    CHECK (mode IN ('quick', 'long')),
  CONSTRAINT polls_status_chk  CHECK (status IN ('open', 'closed')),
  CONSTRAINT polls_deadline_chk CHECK (deadline >= 0)
);

CREATE INDEX IF NOT EXISTS polls_created_idx ON public.polls (created_at DESC);
CREATE INDEX IF NOT EXISTS polls_owner_idx   ON public.polls (owner_sid);

CREATE TABLE IF NOT EXISTS public.poll_votes (
  id      text PRIMARY KEY,
  poll_id text NOT NULL REFERENCES public.polls(id) ON DELETE CASCADE,
  sid     text NOT NULL,
  choices jsonb NOT NULL,
  ts      bigint NOT NULL DEFAULT 0,
  CONSTRAINT poll_votes_uniq UNIQUE (poll_id, sid)
);

CREATE INDEX IF NOT EXISTS poll_votes_poll_idx ON public.poll_votes (poll_id);

-- RLS 开启且不建任何策略 → 直连表一律拒绝；只允许 SECURITY DEFINER RPC（函数 owner）访问。
ALTER TABLE public.polls ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.poll_votes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.polls FROM PUBLIC;
REVOKE ALL ON TABLE public.polls FROM anon;
REVOKE ALL ON TABLE public.poll_votes FROM PUBLIC;
REVOKE ALL ON TABLE public.poll_votes FROM anon;

-- ---------------------------------------------------------------------------
-- §2 纯函数（内部使用，不给 anon 直接调用）
-- ---------------------------------------------------------------------------

-- 结果可见性：always 始终 / afterVote 投票后 / afterClose 截止后（未知值按 afterVote）
CREATE OR REPLACE FUNCTION public.poll_results_visible(p_settings jsonb, p_closed boolean, p_has_voted boolean)
RETURNS boolean
LANGUAGE sql IMMUTABLE
AS $fn$
  SELECT CASE coalesce(p_settings->>'resultVisibility', 'afterVote')
    WHEN 'always'     THEN true
    WHEN 'afterClose' THEN coalesce(p_closed, false)
    ELSE coalesce(p_has_voted, false)
  END;
$fn$;

REVOKE ALL ON FUNCTION public.poll_results_visible(jsonb, boolean, boolean) FROM PUBLIC;

-- 选项归一 + 校验：{ok:true, options:[{id,text,desc,img}]} 或 {ok:false, reason}
CREATE OR REPLACE FUNCTION public.poll_norm_options(p_options jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $fn$
DECLARE
  v_i int;
  v_n int;
  v_item jsonb;
  v_id text;
  v_text text;
  v_desc text;
  v_img text;
  v_ids text[] := ARRAY[]::text[];
  v_out jsonb := '[]'::jsonb;
  v_img_total bigint := 0;
BEGIN
  IF coalesce(jsonb_typeof(p_options), '') <> 'array' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '选项格式不合法');
  END IF;
  v_n := jsonb_array_length(p_options);
  IF v_n < 2 OR v_n > 20 THEN
    RETURN jsonb_build_object('ok', false, 'reason', '选项需 2–20 个');
  END IF;
  FOR v_i IN 0..v_n - 1 LOOP
    v_item := p_options->v_i;
    IF coalesce(jsonb_typeof(v_item), '') <> 'object' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '选项格式不合法');
    END IF;
    v_id := v_item->>'id';
    IF v_id IS NULL OR v_id !~ '^[A-Za-z0-9_-]{1,24}$' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '选项编号不合法');
    END IF;
    IF v_ids @> ARRAY[v_id] THEN
      RETURN jsonb_build_object('ok', false, 'reason', '选项编号重复');
    END IF;
    v_ids := v_ids || v_id;
    v_text := btrim(coalesce(v_item->>'text', ''));
    IF char_length(v_text) < 1 OR char_length(v_text) > 80 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '选项文字需 1–80 字');
    END IF;
    v_desc := btrim(coalesce(v_item->>'desc', ''));
    IF char_length(v_desc) > 200 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '选项说明不能超过 200 字');
    END IF;
    v_img := coalesce(v_item->>'img', '');
    IF v_img <> '' THEN
      IF left(v_img, 11) <> 'data:image/' THEN
        RETURN jsonb_build_object('ok', false, 'reason', '选项图片格式不合法');
      END IF;
      IF char_length(v_img) > 150000 THEN
        RETURN jsonb_build_object('ok', false, 'reason', '选项图片过大');
      END IF;
      v_img_total := v_img_total + char_length(v_img);
      IF v_img_total > 1600000 THEN
        RETURN jsonb_build_object('ok', false, 'reason', '选项图片总大小过大');
      END IF;
    END IF;
    v_out := v_out || jsonb_build_array(jsonb_build_object(
      'id', v_id, 'text', v_text, 'desc', v_desc, 'img', v_img
    ));
  END LOOP;
  RETURN jsonb_build_object('ok', true, 'options', v_out);
END;
$fn$;

REVOKE ALL ON FUNCTION public.poll_norm_options(jsonb) FROM PUBLIC;

-- 规则归一 + 校验：{ok:true, settings:{multi,maxChoices,anonymous,allowChange,resultVisibility}} 或 {ok:false, reason}
CREATE OR REPLACE FUNCTION public.poll_norm_settings(p_settings jsonb, p_opt_count integer)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $fn$
DECLARE
  v_multi boolean;
  v_max int;
  v_anon boolean;
  v_change boolean;
  v_vis text;
BEGIN
  v_multi := CASE WHEN jsonb_typeof(p_settings->'multi') = 'boolean'
                  THEN (p_settings->>'multi')::boolean ELSE false END;
  v_anon := CASE WHEN jsonb_typeof(p_settings->'anonymous') = 'boolean'
                 THEN (p_settings->>'anonymous')::boolean ELSE true END;
  v_change := CASE WHEN jsonb_typeof(p_settings->'allowChange') = 'boolean'
                   THEN (p_settings->>'allowChange')::boolean ELSE true END;
  v_max := CASE WHEN jsonb_typeof(p_settings->'maxChoices') = 'number'
                THEN (p_settings->>'maxChoices')::int ELSE 1 END;
  v_vis := coalesce(p_settings->>'resultVisibility', 'afterVote');
  IF v_vis NOT IN ('always', 'afterVote', 'afterClose') THEN
    RETURN jsonb_build_object('ok', false, 'reason', '结果可见规则不合法');
  END IF;
  IF v_multi THEN
    IF v_max < 2 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '多选需允许至少选 2 项');
    END IF;
    IF v_max > coalesce(p_opt_count, 20) THEN
      v_max := coalesce(p_opt_count, 20);
    END IF;
    IF v_max < 2 THEN v_max := 2; END IF;
  ELSE
    v_max := 1;
  END IF;
  RETURN jsonb_build_object('ok', true, 'settings', jsonb_build_object(
    'multi', v_multi, 'maxChoices', v_max, 'anonymous', v_anon,
    'allowChange', v_change, 'resultVisibility', v_vis
  ));
END;
$fn$;

REVOKE ALL ON FUNCTION public.poll_norm_settings(jsonb, integer) FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- §3 读 RPC
-- ---------------------------------------------------------------------------

-- 详情 / 投票 / 管理 的统一返回结构（契约 §2.3）
CREATE OR REPLACE FUNCTION public.poll_detail(p_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid text;
  v_now bigint;
  v_p public.polls%ROWTYPE;
  v_closed boolean;
  v_mine boolean;
  v_manage boolean;
  v_total int;
  v_choices jsonb;
  v_has boolean := false;
  v_anon boolean;
  v_vis boolean;
  v_counts jsonb := '{}'::jsonb;
  v_voters jsonb := '[]'::jsonb;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  v_now := (extract(epoch FROM clock_timestamp()) * 1000)::bigint;
  SELECT * INTO v_p FROM public.polls WHERE id = p_id AND NOT deleted;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'reason', '投票不存在');
  END IF;
  v_closed := (v_p.status = 'closed') OR (v_p.deadline > 0 AND v_now >= v_p.deadline);
  v_mine := (v_p.owner_sid = v_sid);
  v_manage := v_mine OR public.auth_admin();
  SELECT count(*)::int INTO v_total FROM public.poll_votes WHERE poll_id = v_p.id;
  SELECT v.choices INTO v_choices FROM public.poll_votes v WHERE v.poll_id = v_p.id AND v.sid = v_sid;
  IF v_choices IS NULL THEN
    v_choices := '[]'::jsonb;
    v_has := false;
  ELSE
    v_has := true;
  END IF;
  v_anon := coalesce((v_p.settings->>'anonymous')::boolean, true);
  v_vis := public.poll_results_visible(v_p.settings, v_closed, v_has);
  IF v_vis THEN
    SELECT coalesce(jsonb_object_agg(x.cid, x.n), '{}'::jsonb) INTO v_counts
    FROM (
      SELECT c.value AS cid, count(*)::int AS n
      FROM public.poll_votes pv
      CROSS JOIN LATERAL jsonb_array_elements_text(pv.choices) AS c(value)
      WHERE pv.poll_id = v_p.id
      GROUP BY c.value
    ) x;
    IF NOT v_anon THEN
      SELECT coalesce(jsonb_agg(
               jsonb_build_object('name', coalesce(ci.name, ''), 'choices', pv.choices)
               ORDER BY pv.ts, pv.id
             ), '[]'::jsonb) INTO v_voters
      FROM public.poll_votes pv
      LEFT JOIN private.class_ids ci ON ci.sid = pv.sid
      WHERE pv.poll_id = v_p.id;
    END IF;
  END IF;
  RETURN jsonb_build_object(
    'ok', true,
    'now', v_now,
    'poll', jsonb_build_object(
      'id', v_p.id, 'title', v_p.title, 'description', v_p.description,
      'mode', v_p.mode, 'owner_name', v_p.owner_name,
      'settings', v_p.settings, 'options', v_p.options,
      'deadline', v_p.deadline, 'status', v_p.status, 'closed_at', v_p.closed_at,
      'created_at', v_p.created_at, 'updated_at', v_p.updated_at
    ),
    'closed', v_closed,
    'total', v_total,
    'counts', v_counts,
    'has_voted', v_has,
    'my_choices', v_choices,
    'results_hidden', NOT v_vis,
    'voters', v_voters,
    'mine', v_mine,
    'can_manage', v_manage
  );
END;
$fn$;

GRANT EXECUTE ON FUNCTION public.poll_detail(text) TO anon;

-- 列表（契约 §2.2）
CREATE OR REPLACE FUNCTION public.poll_list()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid text;
  v_now bigint;
  v_polls jsonb;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  v_now := (extract(epoch FROM clock_timestamp()) * 1000)::bigint;
  SELECT coalesce(jsonb_agg(t.row ORDER BY t.created_at DESC), '[]'::jsonb) INTO v_polls
  FROM (
    SELECT p.created_at, jsonb_build_object(
      'id', p.id,
      'title', p.title,
      'description', p.description,
      'mode', p.mode,
      'owner_name', p.owner_name,
      'settings', p.settings,
      'deadline', p.deadline,
      'status', p.status,
      'closed_at', p.closed_at,
      'created_at', p.created_at,
      'updated_at', p.updated_at,
      'closed', (p.status = 'closed' OR (p.deadline > 0 AND v_now >= p.deadline)),
      'total', coalesce(vv.total, 0),
      'has_voted', (mv.choices IS NOT NULL),
      'my_choices', coalesce(mv.choices, '[]'::jsonb),
      'results_hidden', NOT public.poll_results_visible(
        p.settings,
        (p.status = 'closed' OR (p.deadline > 0 AND v_now >= p.deadline)),
        (mv.choices IS NOT NULL)
      ),
      'counts', CASE WHEN public.poll_results_visible(
                       p.settings,
                       (p.status = 'closed' OR (p.deadline > 0 AND v_now >= p.deadline)),
                       (mv.choices IS NOT NULL)
                     )
                     THEN coalesce(vv.counts, '{}'::jsonb)
                     ELSE '{}'::jsonb END,
      'mine', (p.owner_sid = v_sid),
      'can_manage', (p.owner_sid = v_sid OR public.auth_admin())
    ) AS row
    FROM public.polls p
    LEFT JOIN public.poll_votes mv ON mv.poll_id = p.id AND mv.sid = v_sid
    LEFT JOIN (
      SELECT poll_id,
             count(*)::int AS total,
             coalesce(jsonb_object_agg(cid, n), '{}'::jsonb) AS counts
      FROM (
        SELECT pv.poll_id, c.value AS cid, count(*)::int AS n
        FROM public.poll_votes pv
        CROSS JOIN LATERAL jsonb_array_elements_text(pv.choices) AS c(value)
        GROUP BY pv.poll_id, c.value
      ) q GROUP BY poll_id
    ) vv ON vv.poll_id = p.id
    WHERE NOT p.deleted
    ORDER BY p.created_at DESC
    LIMIT 100
  ) t;
  RETURN jsonb_build_object('ok', true, 'now', v_now, 'polls', v_polls);
END;
$fn$;

GRANT EXECUTE ON FUNCTION public.poll_list() TO anon;

-- ---------------------------------------------------------------------------
-- §4 写 RPC
-- ---------------------------------------------------------------------------

-- 发起（契约 §2.1；p_id 幂等）
CREATE OR REPLACE FUNCTION public.poll_create(
  p_id text, p_title text, p_description text, p_mode text,
  p_options jsonb, p_settings jsonb, p_deadline bigint
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid text;
  v_name text;
  v_now bigint;
  v_title text;
  v_desc text;
  v_mode text;
  v_deadline bigint;
  v_chk jsonb;
  v_opts jsonb;
  v_settings jsonb;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  v_now := (extract(epoch FROM clock_timestamp()) * 1000)::bigint;
  IF p_id IS NULL OR p_id !~ '^p[a-z0-9]{4,32}$' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '投票编号不合法');
  END IF;
  -- 幂等：重试同 id 直接返回已建投票
  IF EXISTS (SELECT 1 FROM public.polls WHERE id = p_id) THEN
    RETURN public.poll_detail(p_id);
  END IF;
  v_title := btrim(coalesce(p_title, ''));
  IF char_length(v_title) < 1 OR char_length(v_title) > 80 THEN
    RETURN jsonb_build_object('ok', false, 'reason', '标题需 1–80 字');
  END IF;
  v_desc := btrim(coalesce(p_description, ''));
  IF char_length(v_desc) > 500 THEN
    RETURN jsonb_build_object('ok', false, 'reason', '说明不能超过 500 字');
  END IF;
  v_mode := coalesce(p_mode, 'long');
  IF v_mode NOT IN ('quick', 'long') THEN
    v_mode := 'long';
  END IF;
  v_chk := public.poll_norm_options(p_options);
  IF NOT coalesce((v_chk->>'ok')::boolean, false) THEN
    RETURN v_chk;
  END IF;
  v_opts := v_chk->'options';
  v_chk := public.poll_norm_settings(p_settings, jsonb_array_length(v_opts));
  IF NOT coalesce((v_chk->>'ok')::boolean, false) THEN
    RETURN v_chk;
  END IF;
  v_settings := v_chk->'settings';
  v_deadline := coalesce(p_deadline, 0);
  IF v_deadline < 0 THEN
    RETURN jsonb_build_object('ok', false, 'reason', '截止时间不合法');
  END IF;
  IF v_deadline > 0 AND v_deadline <= v_now THEN
    RETURN jsonb_build_object('ok', false, 'reason', '截止时间需晚于当前时间');
  END IF;
  v_name := coalesce((SELECT c.name FROM private.class_ids c WHERE c.sid = v_sid), '');
  INSERT INTO public.polls (
    id, title, description, mode, owner_sid, owner_name, options, settings,
    deadline, status, closed_at, deleted, created_at, updated_at
  ) VALUES (
    p_id, v_title, v_desc, v_mode, v_sid, v_name, v_opts, v_settings,
    v_deadline, 'open', 0, false, v_now, v_now
  );
  RETURN public.poll_detail(p_id);
EXCEPTION WHEN others THEN
  RETURN jsonb_build_object('ok', false, 'reason', '发起投票失败，请重试');
END;
$fn$;

GRANT EXECUTE ON FUNCTION public.poll_create(text, text, text, text, jsonb, jsonb, bigint) TO anon;

-- 投票 / 改票（契约 §2.3；一人一票，规则全部服务端校验）
CREATE OR REPLACE FUNCTION public.poll_submit(p_id text, p_choices jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid text;
  v_now bigint;
  v_p public.polls%ROWTYPE;
  v_closed boolean;
  v_has boolean := false;
  v_n int;
  v_max int;
  v_multi boolean;
  v_i int;
  v_cid text;
  v_seen text[] := ARRAY[]::text[];
  v_choices jsonb := '[]'::jsonb;
  v_old jsonb;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  v_now := (extract(epoch FROM clock_timestamp()) * 1000)::bigint;
  SELECT * INTO v_p FROM public.polls WHERE id = p_id AND NOT deleted;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'reason', '投票不存在');
  END IF;
  v_closed := (v_p.status = 'closed') OR (v_p.deadline > 0 AND v_now >= v_p.deadline);
  IF v_closed THEN
    RETURN jsonb_build_object('ok', false, 'reason', '投票已结束');
  END IF;
  IF coalesce(jsonb_typeof(p_choices), '') <> 'array' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '选项不合法');
  END IF;
  v_n := jsonb_array_length(p_choices);
  IF v_n < 1 THEN
    RETURN jsonb_build_object('ok', false, 'reason', '选项不合法');
  END IF;
  v_multi := CASE WHEN jsonb_typeof(v_p.settings->'multi') = 'boolean'
                  THEN (v_p.settings->>'multi')::boolean ELSE false END;
  v_max := CASE WHEN jsonb_typeof(v_p.settings->'maxChoices') = 'number'
                THEN (v_p.settings->>'maxChoices')::int ELSE 1 END;
  IF NOT v_multi THEN v_max := 1; END IF;
  IF v_n > v_max THEN
    IF v_multi THEN
      RETURN jsonb_build_object('ok', false, 'reason', '最多选 ' || v_max || ' 项');
    ELSE
      RETURN jsonb_build_object('ok', false, 'reason', '只能选 1 项');
    END IF;
  END IF;
  FOR v_i IN 0..v_n - 1 LOOP
    IF coalesce(jsonb_typeof(p_choices->v_i), '') <> 'string' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '选项不合法');
    END IF;
    v_cid := p_choices->>v_i;
    IF v_seen @> ARRAY[v_cid] THEN
      RETURN jsonb_build_object('ok', false, 'reason', '重复的选项');
    END IF;
    v_seen := v_seen || v_cid;
    IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_p.options) o WHERE o->>'id' = v_cid) THEN
      RETURN jsonb_build_object('ok', false, 'reason', '选项不合法');
    END IF;
    v_choices := v_choices || jsonb_build_array(v_cid);
  END LOOP;
  SELECT choices INTO v_old FROM public.poll_votes WHERE poll_id = v_p.id AND sid = v_sid;
  IF v_old IS NOT NULL THEN
    IF NOT coalesce((v_p.settings->>'allowChange')::boolean, true) THEN
      RETURN jsonb_build_object('ok', false, 'reason', '已投过票，不可改票');
    END IF;
    UPDATE public.poll_votes SET choices = v_choices, ts = v_now
    WHERE poll_id = v_p.id AND sid = v_sid;
  ELSE
    INSERT INTO public.poll_votes (id, poll_id, sid, choices, ts)
    VALUES (v_p.id || '|' || v_sid, v_p.id, v_sid, v_choices, v_now)
    ON CONFLICT (poll_id, sid) DO UPDATE SET choices = EXCLUDED.choices, ts = EXCLUDED.ts;
  END IF;
  RETURN public.poll_detail(v_p.id);
EXCEPTION WHEN others THEN
  RETURN jsonb_build_object('ok', false, 'reason', '投票失败，请重试');
END;
$fn$;

GRANT EXECUTE ON FUNCTION public.poll_submit(text, jsonb) TO anon;

-- 管理：编辑（无票时）/ 提前结束 / 延长·重开 / 删除（契约 §2.4）
CREATE OR REPLACE FUNCTION public.poll_manage(
  p_id text, p_action text,
  p_title text DEFAULT NULL, p_description text DEFAULT NULL,
  p_options jsonb DEFAULT NULL, p_settings jsonb DEFAULT NULL,
  p_deadline bigint DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid text;
  v_now bigint;
  v_p public.polls%ROWTYPE;
  v_action text;
  v_title text;
  v_desc text;
  v_deadline bigint;
  v_chk jsonb;
  v_opts jsonb;
  v_settings jsonb;
  v_total int;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  v_now := (extract(epoch FROM clock_timestamp()) * 1000)::bigint;
  SELECT * INTO v_p FROM public.polls WHERE id = p_id AND NOT deleted;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'reason', '投票不存在');
  END IF;
  IF NOT (v_p.owner_sid = v_sid OR public.auth_admin()) THEN
    RETURN jsonb_build_object('ok', false, 'reason', '无权管理该投票');
  END IF;
  v_action := lower(coalesce(p_action, ''));
  IF v_action = 'delete' THEN
    UPDATE public.polls SET deleted = true, updated_at = v_now WHERE id = p_id;
    -- 软删后 poll_detail 已查不到该行，这里返回显式成功（契约 §2.4）
    RETURN jsonb_build_object('ok', true, 'deleted', true);
  ELSIF v_action = 'close' THEN
    UPDATE public.polls SET status = 'closed', closed_at = v_now, updated_at = v_now WHERE id = p_id;
  ELSIF v_action = 'extend' THEN
    v_deadline := coalesce(p_deadline, 0);
    IF v_deadline <= v_now THEN
      RETURN jsonb_build_object('ok', false, 'reason', '截止时间需晚于当前时间');
    END IF;
    UPDATE public.polls
    SET deadline = v_deadline, status = 'open', closed_at = 0, updated_at = v_now
    WHERE id = p_id;
  ELSIF v_action = 'edit' THEN
    SELECT count(*)::int INTO v_total FROM public.poll_votes WHERE poll_id = p_id;
    IF v_total > 0 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '已有投票，不能修改内容');
    END IF;
    IF p_title IS NULL OR p_options IS NULL OR p_settings IS NULL OR p_deadline IS NULL THEN
      RETURN jsonb_build_object('ok', false, 'reason', '参数不完整');
    END IF;
    v_title := btrim(coalesce(p_title, ''));
    IF char_length(v_title) < 1 OR char_length(v_title) > 80 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '标题需 1–80 字');
    END IF;
    v_desc := btrim(coalesce(p_description, ''));
    IF char_length(v_desc) > 500 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '说明不能超过 500 字');
    END IF;
    v_chk := public.poll_norm_options(p_options);
    IF NOT coalesce((v_chk->>'ok')::boolean, false) THEN
      RETURN v_chk;
    END IF;
    v_opts := v_chk->'options';
    v_chk := public.poll_norm_settings(p_settings, jsonb_array_length(v_opts));
    IF NOT coalesce((v_chk->>'ok')::boolean, false) THEN
      RETURN v_chk;
    END IF;
    v_settings := v_chk->'settings';
    v_deadline := coalesce(p_deadline, 0);
    IF v_deadline < 0 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '截止时间不合法');
    END IF;
    IF v_deadline > 0 AND v_deadline <= v_now THEN
      RETURN jsonb_build_object('ok', false, 'reason', '截止时间需晚于当前时间');
    END IF;
    UPDATE public.polls
    SET title = v_title, description = v_desc, options = v_opts, settings = v_settings,
        deadline = v_deadline, updated_at = v_now
    WHERE id = p_id;
  ELSE
    RETURN jsonb_build_object('ok', false, 'reason', '不支持的操作');
  END IF;
  RETURN public.poll_detail(p_id);
EXCEPTION WHEN others THEN
  RETURN jsonb_build_object('ok', false, 'reason', '操作失败，请重试');
END;
$fn$;

GRANT EXECUTE ON FUNCTION public.poll_manage(text, text, text, text, jsonb, jsonb, bigint) TO anon;
