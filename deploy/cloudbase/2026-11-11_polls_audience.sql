-- 2026-11-11 · 投票功能增量：可见人范围（audience）
--
-- 需求（用户 2026-11-11 18:08）：「投票功能新增可见人范围选项」。
-- 已确认口径：
--   * 范围选项：全班 all / 班委 committee / 团员 league / 指定成员 custom（指定成员用**座号**存储，
--     不存学号、页面不显示学号；范围外同学在列表里完全看不到且不能投票/看结果）；
--   * 发起人与管理员始终可见、可管理（管理可越权可见；管理员不在范围内时**不能投票**，发起人始终可投票）。
--
-- 本文件 = 对 `2026-11-11_polls.sql` 的增量迁移（幂等，可重复应用）：
--   1) polls 增加 audience / audience_seats 两列 + 约束；
--   2) 新增 poll_audience_visible() / poll_norm_audience() 两个内部函数；
--   3) DROP 旧签名的 poll_create / poll_manage 后重建（新增 p_audience / p_audience_seats 参数，默认 all/NULL，
--      旧版缓存页面不传新参数时等价于「全班」/不修改范围，向后兼容）；
--   4) poll_list / poll_detail / poll_submit 增加服务端可见性过滤与返回字段。
--
-- 应用：cd web/deploy/cloudbase && python apply_sql.py 2026-11-11_polls_audience.sql
-- 契约：web/vote/CONTRACT.md §1.6 / §2
--
-- 回滚（会丢失 audience 配置，投票其余数据保留）：
--   DROP FUNCTION IF EXISTS public.poll_manage(text,text,text,text,jsonb,jsonb,bigint,text,jsonb);
--   DROP FUNCTION IF EXISTS public.poll_create(text,text,text,text,jsonb,jsonb,bigint,text,jsonb);
--   DROP FUNCTION IF EXISTS public.poll_audience_visible(text,jsonb);
--   DROP FUNCTION IF EXISTS public.poll_norm_audience(text,jsonb);
--   然后重新执行 2026-11-11_polls.sql（旧签名 7 参数版会恢复；audience 两列保留但不参与判定）
--   ALTER TABLE public.polls DROP CONSTRAINT IF EXISTS polls_audience_chk;
--   ALTER TABLE public.polls DROP COLUMN IF EXISTS audience_seats;
--   ALTER TABLE public.polls DROP COLUMN IF EXISTS audience;

-- ---------------------------------------------------------------------------
-- §1 表结构增量
-- ---------------------------------------------------------------------------
ALTER TABLE public.polls ADD COLUMN IF NOT EXISTS audience text NOT NULL DEFAULT 'all';
ALTER TABLE public.polls ADD COLUMN IF NOT EXISTS audience_seats jsonb NOT NULL DEFAULT '[]'::jsonb;

DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'polls_audience_chk') THEN
    ALTER TABLE public.polls
      ADD CONSTRAINT polls_audience_chk CHECK (audience IN ('all', 'committee', 'league', 'custom'));
  END IF;
END;
$do$;

-- ---------------------------------------------------------------------------
-- §2 内部归一/判定函数（不给 anon 直接调用）
-- ---------------------------------------------------------------------------

-- 可见范围判定：调用方已校验 auth_ok；返回当前 token 是否在 p_audience 范围内
CREATE OR REPLACE FUNCTION public.poll_audience_visible(p_audience text, p_seats jsonb)
RETURNS boolean
LANGUAGE plpgsql
STABLE SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_aud text;
  v_sid text;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN false;
  END IF;
  v_aud := coalesce(nullif(btrim(coalesce(p_audience, '')), ''), 'all');
  IF v_aud = 'all' THEN
    RETURN true;
  END IF;
  IF v_aud = 'committee' THEN
    RETURN public.auth_is_committee();
  END IF;
  IF v_aud = 'league' THEN
    RETURN public.auth_is_league();
  END IF;
  IF v_aud <> 'custom' THEN
    RETURN false;
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  IF v_sid = '' THEN
    RETURN false;
  END IF;
  RETURN EXISTS (
    SELECT 1
    FROM private.class_ids c
    WHERE c.sid = v_sid
      AND c.seat IN (
        SELECT (e.value)::int
        FROM jsonb_array_elements_text(
          CASE WHEN jsonb_typeof(p_seats) = 'array' THEN p_seats ELSE '[]'::jsonb END
        ) AS e(value)
        WHERE e.value ~ '^[0-9]{1,3}$'
      )
  );
END;
$fn$;

REVOKE ALL ON FUNCTION public.poll_audience_visible(text, jsonb) FROM PUBLIC;

-- 范围归一 + 校验：{ok:true,audience,seats} 或 {ok:false,reason}
-- custom 时 seats 只保留班级名单中真实存在的座号（去重升序，排除 is_test 测试身份）
CREATE OR REPLACE FUNCTION public.poll_norm_audience(p_audience text, p_seats jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_aud text;
  v_seats jsonb := '[]'::jsonb;
BEGIN
  v_aud := coalesce(nullif(btrim(coalesce(p_audience, '')), ''), 'all');
  IF v_aud NOT IN ('all', 'committee', 'league', 'custom') THEN
    RETURN jsonb_build_object('ok', false, 'reason', '可见范围不合法');
  END IF;
  IF v_aud <> 'custom' THEN
    RETURN jsonb_build_object('ok', true, 'audience', v_aud, 'seats', '[]'::jsonb);
  END IF;
  IF coalesce(jsonb_typeof(p_seats), '') <> 'array' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '请选择可见成员');
  END IF;
  SELECT coalesce(jsonb_agg(x.seat ORDER BY x.seat), '[]'::jsonb) INTO v_seats
  FROM (
    SELECT DISTINCT (e.value)::int AS seat
    FROM jsonb_array_elements_text(p_seats) AS e(value)
    WHERE e.value ~ '^[0-9]{1,3}$'
  ) x
  WHERE EXISTS (
    SELECT 1 FROM private.class_ids c
    WHERE c.seat = x.seat AND NOT coalesce(c.is_test, false)
  );
  IF jsonb_array_length(v_seats) < 1 THEN
    RETURN jsonb_build_object('ok', false, 'reason', '请选择可见成员');
  END IF;
  RETURN jsonb_build_object('ok', true, 'audience', 'custom', 'seats', v_seats);
END;
$fn$;

REVOKE ALL ON FUNCTION public.poll_norm_audience(text, jsonb) FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- §3 读 RPC（重建：可见性过滤 + 返回 audience 字段）
-- ---------------------------------------------------------------------------

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
  v_mine := (v_p.owner_sid = v_sid);
  v_manage := v_mine OR public.auth_admin();
  -- 可见范围：范围外的人完全看不到（不暴露存在性）；发起人/管理员始终可见
  IF NOT (v_manage OR public.poll_audience_visible(v_p.audience, v_p.audience_seats)) THEN
    RETURN jsonb_build_object('ok', false, 'reason', '投票不存在');
  END IF;
  v_closed := (v_p.status = 'closed') OR (v_p.deadline > 0 AND v_now >= v_p.deadline);
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
      'created_at', v_p.created_at, 'updated_at', v_p.updated_at,
      'audience', v_p.audience,
      'audience_count', jsonb_array_length(coalesce(v_p.audience_seats, '[]'::jsonb)),
      -- 指定成员座号仅发起人/管理员可见（编辑回填用；不返回学号）
      'audience_seats', CASE WHEN v_manage THEN coalesce(v_p.audience_seats, '[]'::jsonb) ELSE '[]'::jsonb END
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
      'audience', p.audience,
      'audience_count', jsonb_array_length(coalesce(p.audience_seats, '[]'::jsonb)),
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
      AND (
        p.owner_sid = v_sid
        OR public.auth_admin()
        OR public.poll_audience_visible(p.audience, p.audience_seats)
      )
    ORDER BY p.created_at DESC
    LIMIT 100
  ) t;
  RETURN jsonb_build_object('ok', true, 'now', v_now, 'polls', v_polls);
END;
$fn$;

GRANT EXECUTE ON FUNCTION public.poll_list() TO anon;

-- ---------------------------------------------------------------------------
-- §4 写 RPC（重建：创建/投票增加范围；管理支持改范围）
-- ---------------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.poll_create(text, text, text, text, jsonb, jsonb, bigint);
DROP FUNCTION IF EXISTS public.poll_manage(text, text, text, text, jsonb, jsonb, bigint);

CREATE OR REPLACE FUNCTION public.poll_create(
  p_id text, p_title text, p_description text, p_mode text,
  p_options jsonb, p_settings jsonb, p_deadline bigint,
  p_audience text DEFAULT 'all', p_audience_seats jsonb DEFAULT NULL
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
  v_audience text;
  v_aud_seats jsonb;
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
  v_chk := public.poll_norm_audience(p_audience, p_audience_seats);
  IF NOT coalesce((v_chk->>'ok')::boolean, false) THEN
    RETURN v_chk;
  END IF;
  v_audience := v_chk->>'audience';
  v_aud_seats := coalesce(v_chk->'seats', '[]'::jsonb);
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
    deadline, status, closed_at, deleted, created_at, updated_at,
    audience, audience_seats
  ) VALUES (
    p_id, v_title, v_desc, v_mode, v_sid, v_name, v_opts, v_settings,
    v_deadline, 'open', 0, false, v_now, v_now,
    v_audience, v_aud_seats
  );
  RETURN public.poll_detail(p_id);
EXCEPTION WHEN others THEN
  RETURN jsonb_build_object('ok', false, 'reason', '发起投票失败，请重试');
END;
$fn$;

GRANT EXECUTE ON FUNCTION public.poll_create(text, text, text, text, jsonb, jsonb, bigint, text, jsonb) TO anon;

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
  -- 可见范围：范围外不可见（对普通成员隐藏存在性；管理员可见但不在范围时不能投票）；发起人始终可投
  IF NOT public.poll_audience_visible(v_p.audience, v_p.audience_seats) THEN
    IF v_p.owner_sid <> v_sid THEN
      IF public.auth_admin() THEN
        RETURN jsonb_build_object('ok', false, 'reason', '不在可见范围内');
      END IF;
      RETURN jsonb_build_object('ok', false, 'reason', '投票不存在');
    END IF;
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

CREATE OR REPLACE FUNCTION public.poll_manage(
  p_id text, p_action text,
  p_title text DEFAULT NULL, p_description text DEFAULT NULL,
  p_options jsonb DEFAULT NULL, p_settings jsonb DEFAULT NULL,
  p_deadline bigint DEFAULT NULL,
  p_audience text DEFAULT NULL, p_audience_seats jsonb DEFAULT NULL
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
  v_audience text;
  v_aud_seats jsonb;
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
    IF p_audience IS NOT NULL THEN
      v_chk := public.poll_norm_audience(p_audience, p_audience_seats);
      IF NOT coalesce((v_chk->>'ok')::boolean, false) THEN
        RETURN v_chk;
      END IF;
      v_audience := v_chk->>'audience';
      v_aud_seats := coalesce(v_chk->'seats', '[]'::jsonb);
      UPDATE public.polls
      SET title = v_title, description = v_desc, options = v_opts, settings = v_settings,
          deadline = v_deadline, audience = v_audience, audience_seats = v_aud_seats,
          updated_at = v_now
      WHERE id = p_id;
    ELSE
      -- 旧版缓存页面不传 audience：保持原可见范围不变（向后兼容）
      UPDATE public.polls
      SET title = v_title, description = v_desc, options = v_opts, settings = v_settings,
          deadline = v_deadline, updated_at = v_now
      WHERE id = p_id;
    END IF;
  ELSE
    RETURN jsonb_build_object('ok', false, 'reason', '不支持的操作');
  END IF;
  RETURN public.poll_detail(p_id);
EXCEPTION WHEN others THEN
  RETURN jsonb_build_object('ok', false, 'reason', '操作失败，请重试');
END;
$fn$;

GRANT EXECUTE ON FUNCTION public.poll_manage(text, text, text, text, jsonb, jsonb, bigint, text, jsonb) TO anon;
