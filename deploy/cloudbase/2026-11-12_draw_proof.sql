-- 2026-11-12 · 抽签存证（draw_records / draw_events + 6 个 SECURITY DEFINER RPC）
--
-- 契约唯一真源：web/draw/CONTRACT.md（§1 数据与云端 / §1.2 哈希规范 / §1.3 RPC / §1.4 params 归一）
--
-- 需求背景（用户 2026-11-12）：「抽签导出图片还是会被质疑有作弊」→ 云端存证 + 扫码核验 + 当天抽签次数统计。
--
-- 设计取舍（重要，逐条对应契约）：
--   * draw_records / draw_events 两张表 **不对 anon 暴露任何直连权限**（RLS 开启 + 无策略 + REVOKE），
--     所有读写只经本文件的 SECURITY DEFINER RPC —— 防止绕过参数/结果校验、篡改已存证记录、直连删记录；
--   * 记录不可改：没有任何 UPDATE 已存证记录的 RPC（唯一 DELETE = is_test 测试身份清理自己的测试数据）；
--   * 哈希：canon = concat_ws(E'\n','v1',id,created_ms,day,seq_day,algo,seed,prev_hash,params,pool,result,labels)，
--     hash = encode(digest(canon,'sha256'),'hex')（pgcrypto，UTF8 下与网页 crypto.subtle / Python hashlib 逐字节一致）；
--     事件哈希 ev_canon = concat_ws(E'\n','e1',record_id,seq,kind,n,added,note,created_ms,prev_hash)；
--   * params / pool / result / labels 全部由服务端**从入参重建**（白名单归一，未知键丢弃），保证 canon 确定；
--   * pg_advisory_xact_lock(hashtext('public.draw_records')) 串行化当天 seq_day 取号与 prev_hash 链；
--   * is_test 口径隔离：is_test := (sid='3260799999' OR sid ~ '^9999[0-9]{6}$')；seq_day/today_count/prev 链/
--     list/get 可见性全部按 is_test 口径隔离，真实用户永远看不到测试记录、也不计入真实今日次数；
--   * **任何 RPC 响应都不返回 sid**（只返回 op_name/op_seat、is_mine 布尔）。
--
-- 应用（幂等，可重复执行，fails=0）：
--   cd web/deploy/cloudbase
--   python apply_sql.py 2026-11-12_draw_proof.sql --dry-run
--   python apply_sql.py 2026-11-12_draw_proof.sql
--
-- 测试：
--   cd web/tools
--   python tests\draw_cloud_check.py
--
-- 回滚（仅删除本文件新增对象，不影响其它功能）：
--   DROP FUNCTION IF EXISTS public.draw_test_clear();
--   DROP FUNCTION IF EXISTS public.draw_test_purge(text);
--   DROP FUNCTION IF EXISTS public.draw_record_list(text, integer);
--   DROP FUNCTION IF EXISTS public.draw_record_get(text);
--   DROP FUNCTION IF EXISTS public.draw_event_append(text, text, integer, integer, text);
--   DROP FUNCTION IF EXISTS public.draw_record_create(text, jsonb, jsonb, jsonb, jsonb, text, text);
--   DROP FUNCTION IF EXISTS public.draw_norm_labels(jsonb, jsonb);
--   DROP FUNCTION IF EXISTS public.draw_norm_result(jsonb, jsonb, integer, boolean);
--   DROP FUNCTION IF EXISTS public.draw_norm_pool(jsonb);
--   DROP FUNCTION IF EXISTS public.draw_norm_params(jsonb);
--   DROP TABLE IF EXISTS public.draw_events;
--   DROP TABLE IF EXISTS public.draw_records;
--   （pgcrypto 为既有扩展，不删）

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- §1 表（契约 §1.1）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.draw_records (
  id          text PRIMARY KEY,                -- 'd' + 8..31 位 [0-9a-z]（客户端生成，幂等键）
  sid         text NOT NULL,                   -- 操作用户学号（内部；任何 RPC 响应都不返回）
  is_test     boolean NOT NULL DEFAULT false,  -- 由 sid 判定：'3260799999' 或 9999 段 10 位
  at          timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_ms  bigint NOT NULL,                 -- (extract(epoch from at)*1000)::bigint（哈希/展示用）
  day         date NOT NULL,                   -- (at AT TIME ZONE 'Asia/Shanghai')::date
  seq_day     integer NOT NULL,                -- 当天第几次（同 is_test 口径，全表递增）
  params      jsonb NOT NULL,                  -- 归一化参数（见 §1.4）
  pool        jsonb NOT NULL,                  -- 抽签池号码数组（复算用）
  result      jsonb NOT NULL,                  -- 抽取顺序结果号码数组
  labels      jsonb NOT NULL DEFAULT '[]',     -- 自定义名称命中结果 [{n,nm}]（≤300）
  seed        text NOT NULL,                   -- 16 位小写 hex
  algo        text NOT NULL DEFAULT 'draw-v1',
  prev_hash   text NOT NULL DEFAULT '',        -- 链上前一条 hash（同 is_test 口径，按 (at,id) 前一条）
  hash        text NOT NULL,                   -- sha256(canon) 64 位 hex
  CONSTRAINT draw_records_id_chk    CHECK (id ~ '^d[0-9a-z]{8,31}$'),
  CONSTRAINT draw_records_day_chk   CHECK (seq_day >= 1),
  CONSTRAINT draw_records_seed_chk  CHECK (seed ~ '^[0-9a-f]{16}$'),
  CONSTRAINT draw_records_algo_chk  CHECK (algo = 'draw-v1')
);
CREATE INDEX IF NOT EXISTS draw_records_day_idx  ON public.draw_records (day DESC, seq_day DESC);
CREATE INDEX IF NOT EXISTS draw_records_at_idx   ON public.draw_records (at DESC, id);

CREATE TABLE IF NOT EXISTS public.draw_events (
  record_id text NOT NULL REFERENCES public.draw_records(id) ON DELETE CASCADE,
  seq       integer NOT NULL,                  -- 从 1 起
  kind      text NOT NULL,                     -- remove | refill | sort | reset
  n         integer,                           -- 被剔除号码
  added     integer,                           -- 补抽号码
  note      text NOT NULL DEFAULT '',
  at        timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_ms bigint NOT NULL,
  prev_hash text NOT NULL DEFAULT '',
  hash      text NOT NULL,
  PRIMARY KEY (record_id, seq),
  CONSTRAINT draw_events_kind_chk CHECK (kind IN ('remove','refill','sort','reset'))
);

-- RLS 开启且不建任何策略 → 直连表一律拒绝；只允许 SECURITY DEFINER RPC（函数 owner）访问。
ALTER TABLE public.draw_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.draw_events  ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.draw_records FROM PUBLIC;
REVOKE ALL ON TABLE public.draw_records FROM anon;
REVOKE ALL ON TABLE public.draw_events  FROM PUBLIC;
REVOKE ALL ON TABLE public.draw_events  FROM anon;

-- ---------------------------------------------------------------------------
-- §2 内部归一函数（不给 anon 直接调用；供 RPC 服务端重建参数）
-- ---------------------------------------------------------------------------

-- params 归一（契约 §1.4）：{ok:true,params:{range,count,dup,excl,sort,rosterN,namesN}} 或 {ok:false,reason:'参数不合法'}
CREATE OR REPLACE FUNCTION public.draw_norm_params(p_params jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $fn$
DECLARE
  v_arr    jsonb;
  v_lo_txt text;
  v_hi_txt text;
  v_count  text;
  v_dup    boolean := false;
  v_sort   text;
  v_excl_n int;
  v_i      int;
  v_e      text;
  v_seen   int[] := '{}';
  v_excl   jsonb;
  v_roster text;
  v_names  text;
BEGIN
  IF coalesce(jsonb_typeof(p_params), '') <> 'object' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
  END IF;
  -- range：[lo,hi] 两个整数 0..99999，lo<=hi
  IF NOT (p_params ? 'range') THEN
    RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
  END IF;
  v_arr := p_params->'range';
  IF coalesce(jsonb_typeof(v_arr), '') <> 'array' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
  END IF;
  IF jsonb_array_length(v_arr) <> 2 THEN
    RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
  END IF;
  v_lo_txt := (v_arr->0)::text;
  v_hi_txt := (v_arr->1)::text;
  IF v_lo_txt !~ '^[0-9]{1,5}$' OR v_hi_txt !~ '^[0-9]{1,5}$' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
  END IF;
  IF (v_lo_txt)::int > 99999 OR (v_hi_txt)::int > 99999 OR (v_lo_txt)::int > (v_hi_txt)::int THEN
    RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
  END IF;
  -- count：1..1000
  IF NOT (p_params ? 'count') THEN
    RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
  END IF;
  v_count := (p_params->'count')::text;
  IF v_count !~ '^[0-9]{1,4}$' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
  END IF;
  IF (v_count)::int < 1 OR (v_count)::int > 1000 THEN
    RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
  END IF;
  -- dup：boolean（缺省 false）
  IF p_params ? 'dup' THEN
    IF coalesce(jsonb_typeof(p_params->'dup'), '') <> 'boolean' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
    END IF;
    v_dup := (p_params->>'dup')::boolean;
  END IF;
  -- sort：draw|num|desc|rand（缺省 draw）
  IF p_params ? 'sort' THEN
    IF coalesce(jsonb_typeof(p_params->'sort'), '') <> 'string' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
    END IF;
    v_sort := p_params->>'sort';
    IF v_sort NOT IN ('draw', 'num', 'desc', 'rand') THEN
      RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
    END IF;
  END IF;
  -- excl：整数数组 ≤200（去重升序；缺省 []）
  IF p_params ? 'excl' THEN
    IF coalesce(jsonb_typeof(p_params->'excl'), '') <> 'array' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
    END IF;
    v_excl_n := jsonb_array_length(p_params->'excl');
    IF v_excl_n > 200 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
    END IF;
    FOR v_i IN 0..v_excl_n - 1 LOOP
      v_e := (p_params->'excl'->v_i)::text;
      IF v_e !~ '^[0-9]{1,5}$' THEN
        RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
      END IF;
      IF (v_e)::int > 99999 THEN
        RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
      END IF;
      IF NOT ((v_e)::int = ANY(v_seen)) THEN
        v_seen := v_seen || (v_e)::int;
      END IF;
    END LOOP;
  END IF;
  SELECT coalesce(jsonb_agg(x ORDER BY x), '[]'::jsonb) INTO v_excl FROM unnest(v_seen) AS x;
  -- rosterN 0..70（缺省 0）；namesN 0..300（缺省 0）
  IF p_params ? 'rosterN' THEN
    v_roster := (p_params->'rosterN')::text;
    IF v_roster !~ '^[0-9]{1,3}$' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
    END IF;
    IF (v_roster)::int > 70 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
    END IF;
  END IF;
  IF p_params ? 'namesN' THEN
    v_names := (p_params->'namesN')::text;
    IF v_names !~ '^[0-9]{1,3}$' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
    END IF;
    IF (v_names)::int > 300 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '参数不合法');
    END IF;
  END IF;
  RETURN jsonb_build_object('ok', true, 'params', jsonb_build_object(
    'range',   jsonb_build_array((v_lo_txt)::int, (v_hi_txt)::int),
    'count',   (v_count)::int,
    'dup',     v_dup,
    'excl',    v_excl,
    'sort',    coalesce(v_sort, 'draw'),
    'rosterN', coalesce((v_roster)::int, 0),
    'namesN',  coalesce((v_names)::int, 0)
  ));
END;
$fn$;

REVOKE ALL ON FUNCTION public.draw_norm_params(jsonb) FROM PUBLIC;

-- pool 归一（契约 §1.4）：{ok:true,pool:[去重升序 0..99999],n:长度} 或 {ok:false,reason:'抽签池不合法'}
CREATE OR REPLACE FUNCTION public.draw_norm_pool(p_pool jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $fn$
DECLARE
  v_n    int;
  v_i    int;
  v_e    text;
  v_seen int[] := '{}';
  v_out  jsonb;
BEGIN
  IF coalesce(jsonb_typeof(p_pool), '') <> 'array' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '抽签池不合法');
  END IF;
  v_n := jsonb_array_length(p_pool);
  IF v_n < 1 OR v_n > 1000 THEN
    RETURN jsonb_build_object('ok', false, 'reason', '抽签池不合法');
  END IF;
  FOR v_i IN 0..v_n - 1 LOOP
    v_e := (p_pool->v_i)::text;
    IF v_e !~ '^[0-9]{1,5}$' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '抽签池不合法');
    END IF;
    IF (v_e)::int > 99999 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '抽签池不合法');
    END IF;
    -- 同一号码不得重复
    IF (v_e)::int = ANY(v_seen) THEN
      RETURN jsonb_build_object('ok', false, 'reason', '抽签池不合法');
    END IF;
    v_seen := v_seen || (v_e)::int;
  END LOOP;
  SELECT coalesce(jsonb_agg(x ORDER BY x), '[]'::jsonb) INTO v_out FROM unnest(v_seen) AS x;
  RETURN jsonb_build_object('ok', true, 'pool', v_out, 'n', v_n);
END;
$fn$;

REVOKE ALL ON FUNCTION public.draw_norm_pool(jsonb) FROM PUBLIC;

-- result 校验（契约 §1.4）：元素必须 ∈ pool；长度 = count；dup=false 时互不重复。
-- 返回 {ok:true,result:[...抽取顺序...]} 或 {ok:false,reason:'结果不合法'}
CREATE OR REPLACE FUNCTION public.draw_norm_result(p_result jsonb, p_pool jsonb, p_count integer, p_dup boolean)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $fn$
DECLARE
  v_n        int;
  v_i        int;
  v_e        text;
  v_int      int;
  v_pool_arr int[];
  v_seen     int[] := '{}';
  v_out      jsonb := '[]'::jsonb;
BEGIN
  IF coalesce(jsonb_typeof(p_result), '') <> 'array' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '结果不合法');
  END IF;
  v_n := jsonb_array_length(p_result);
  IF v_n <> coalesce(p_count, -1) THEN
    RETURN jsonb_build_object('ok', false, 'reason', '结果不合法');
  END IF;
  SELECT coalesce(array_agg((x)::int), '{}'::int[]) INTO v_pool_arr
  FROM jsonb_array_elements_text(p_pool) AS x;
  FOR v_i IN 0..v_n - 1 LOOP
    v_e := (p_result->v_i)::text;
    IF v_e !~ '^[0-9]{1,5}$' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '结果不合法');
    END IF;
    v_int := (v_e)::int;
    IF v_int > 99999 OR NOT (v_int = ANY(v_pool_arr)) THEN
      RETURN jsonb_build_object('ok', false, 'reason', '结果不合法');
    END IF;
    IF NOT coalesce(p_dup, false) THEN
      IF v_int = ANY(v_seen) THEN
        RETURN jsonb_build_object('ok', false, 'reason', '结果不合法');
      END IF;
      v_seen := v_seen || v_int;
    END IF;
    v_out := v_out || jsonb_build_array(v_int);
  END LOOP;
  RETURN jsonb_build_object('ok', true, 'result', v_out);
END;
$fn$;

REVOKE ALL ON FUNCTION public.draw_norm_result(jsonb, jsonb, integer, boolean) FROM PUBLIC;

-- labels 归一（契约 §1.4）：[{n:int,nm:1..40字}]，长度 ≤300，n 必须 ∈ result，
-- 按 n 升序去重（同 n 后值覆盖），未知键丢弃。
-- 返回 {ok:true,labels:[{n,nm}...]} 或 {ok:false,reason:'名称映射不合法'}
CREATE OR REPLACE FUNCTION public.draw_norm_labels(p_labels jsonb, p_result jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $fn$
DECLARE
  v_n       int;
  v_i       int;
  v_item    jsonb;
  v_n_txt   text;
  v_nm      text;
  v_res_arr int[];
  v_map     jsonb := '{}'::jsonb;
  v_out     jsonb;
BEGIN
  IF coalesce(jsonb_typeof(p_labels), '') <> 'array' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '名称映射不合法');
  END IF;
  v_n := jsonb_array_length(p_labels);
  IF v_n > 300 THEN
    RETURN jsonb_build_object('ok', false, 'reason', '名称映射不合法');
  END IF;
  SELECT coalesce(array_agg((x)::int), '{}'::int[]) INTO v_res_arr
  FROM jsonb_array_elements_text(p_result) AS x;
  FOR v_i IN 0..v_n - 1 LOOP
    v_item := p_labels->v_i;
    IF coalesce(jsonb_typeof(v_item), '') <> 'object' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '名称映射不合法');
    END IF;
    v_n_txt := (v_item->'n')::text;
    IF v_n_txt !~ '^[0-9]{1,5}$' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '名称映射不合法');
    END IF;
    IF coalesce(jsonb_typeof(v_item->'nm'), '') <> 'string' THEN
      RETURN jsonb_build_object('ok', false, 'reason', '名称映射不合法');
    END IF;
    v_nm := btrim(v_item->>'nm');
    IF char_length(v_nm) < 1 OR char_length(v_nm) > 40 THEN
      RETURN jsonb_build_object('ok', false, 'reason', '名称映射不合法');
    END IF;
    IF NOT ((v_n_txt)::int = ANY(v_res_arr)) THEN
      RETURN jsonb_build_object('ok', false, 'reason', '名称映射不合法');
    END IF;
    v_map := jsonb_set(v_map, ARRAY[(v_n_txt)::int::text], to_jsonb(v_nm), true);
  END LOOP;
  SELECT coalesce(jsonb_agg(jsonb_build_object('n', k::int, 'nm', v) ORDER BY k::int), '[]'::jsonb)
    INTO v_out
  FROM jsonb_each_text(v_map) AS t(k, v);
  RETURN jsonb_build_object('ok', true, 'labels', v_out);
END;
$fn$;

REVOKE ALL ON FUNCTION public.draw_norm_labels(jsonb, jsonb) FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- §3 读 RPC（契约 §1.3-3 / §1.3-4）
-- ---------------------------------------------------------------------------

-- 记录详情 / 核验视图：登录 + is_test 同口径才可见；**不返回 sid**。
CREATE OR REPLACE FUNCTION public.draw_record_get(p_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid         text;
  v_is_test     boolean;
  v_r           public.draw_records%ROWTYPE;
  v_day         date;
  v_today_count int;
  v_today_mine  int;
  v_event_count int;
  v_events      jsonb;
  v_name        text;
  v_seat        int;
  v_canon       text;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  IF v_sid = '' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_is_test := (v_sid = '3260799999' OR v_sid ~ '^9999[0-9]{6}$');
  SELECT * INTO v_r
  FROM public.draw_records r
  WHERE r.id = p_id AND r.is_test = v_is_test;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'reason', '记录不存在');
  END IF;
  v_day := (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date;
  SELECT count(*)::int INTO v_today_count
  FROM public.draw_records r WHERE r.day = v_day AND r.is_test = v_is_test;
  SELECT count(*)::int INTO v_today_mine
  FROM public.draw_records r WHERE r.day = v_day AND r.sid = v_sid;
  SELECT count(*)::int INTO v_event_count
  FROM public.draw_events e WHERE e.record_id = v_r.id;
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'seq', e.seq, 'kind', e.kind, 'n', e.n, 'added', e.added,
           'note', e.note, 'at', e.created_ms,
           'hash', e.hash, 'prev_hash', e.prev_hash
         ) ORDER BY e.seq), '[]'::jsonb)
    INTO v_events
  FROM public.draw_events e WHERE e.record_id = v_r.id;
  SELECT c.name, c.seat INTO v_name, v_seat
  FROM private.class_ids c WHERE c.sid = v_r.sid LIMIT 1;
  -- canon 从库内字段逐字节重建（与 create 时写入的 canon 完全一致）
  v_canon := concat_ws(E'\n', 'v1', v_r.id, v_r.created_ms::text, v_r.day::text,
                       v_r.seq_day::text, v_r.algo, v_r.seed, v_r.prev_hash,
                       v_r.params::text, v_r.pool::text, v_r.result::text, v_r.labels::text);
  RETURN jsonb_build_object('ok', true, 'record', jsonb_build_object(
    'id', v_r.id,
    'at', v_r.created_ms,
    'day', v_r.day::text,
    'seq_day', v_r.seq_day,
    'today_count', v_today_count,
    'today_mine', v_today_mine,
    'is_mine', (v_r.sid = v_sid),
    'op_name', coalesce(v_name, ''),
    'op_seat', v_seat,
    'params', v_r.params,
    'pool', v_r.pool,
    'result', v_r.result,
    'labels', v_r.labels,
    'seed', v_r.seed,
    'algo', v_r.algo,
    'hash', v_r.hash,
    'canon', v_canon,
    'prev_hash', v_r.prev_hash,
    'event_count', v_event_count,
    'events', v_events
  ));
END;
$fn$;

REVOKE ALL ON FUNCTION public.draw_record_get(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.draw_record_get(text) TO anon;

-- 记录列表：只返回与调用方 is_test 同口径的记录；摘要**不含** seed/pool/canon/events。
CREATE OR REPLACE FUNCTION public.draw_record_list(p_scope text DEFAULT 'today', p_limit integer DEFAULT 30)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid         text;
  v_is_test     boolean;
  v_day         date;
  v_scope       text;
  v_scope_day   date;
  v_limit       int;
  v_today_count int;
  v_today_mine  int;
  v_records     jsonb;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  IF v_sid = '' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_is_test := (v_sid = '3260799999' OR v_sid ~ '^9999[0-9]{6}$');
  v_day := (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date;
  v_limit := least(greatest(coalesce(p_limit, 30), 1), 100);
  -- scope：today | all | YYYY-MM-DD（其它一律按 today）
  v_scope := lower(btrim(coalesce(p_scope, 'today')));
  IF v_scope NOT IN ('today', 'all') THEN
    IF v_scope ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
      BEGIN
        v_scope_day := v_scope::date;
      EXCEPTION WHEN others THEN
        v_scope := 'today';
      END;
      IF v_scope_day IS NOT NULL THEN
        v_scope := v_scope_day::text;   -- 规范化（去零填充差异 → 统一 YYYY-MM-DD）
      END IF;
    ELSE
      v_scope := 'today';
    END IF;
  END IF;
  SELECT count(*)::int INTO v_today_count
  FROM public.draw_records r WHERE r.day = v_day AND r.is_test = v_is_test;
  SELECT count(*)::int INTO v_today_mine
  FROM public.draw_records r WHERE r.day = v_day AND r.sid = v_sid;
  SELECT coalesce(jsonb_agg(t.row ORDER BY t.ord_seq DESC NULLS LAST, t.ord_at DESC, t.ord_id DESC), '[]'::jsonb)
    INTO v_records
  FROM (
    SELECT
      (CASE WHEN v_scope = 'today' THEN r.seq_day END) AS ord_seq,
      r.at AS ord_at,
      r.id  AS ord_id,
      jsonb_build_object(
        'id', r.id,
        'at', r.created_ms,
        'day', r.day::text,
        'seq_day', r.seq_day,
        'params', r.params,
        'result', r.result,
        'labels', r.labels,
        'hash', r.hash,
        'event_count', (SELECT count(*)::int FROM public.draw_events e WHERE e.record_id = r.id),
        'is_mine', (r.sid = v_sid),
        'op_name', coalesce(c.name, ''),
        'op_seat', c.seat
      ) AS row
    FROM public.draw_records r
    LEFT JOIN private.class_ids c ON c.sid = r.sid
    WHERE r.is_test = v_is_test
      AND (v_scope = 'all'
           OR (v_scope = 'today' AND r.day = v_day)
           OR (v_scope NOT IN ('all', 'today') AND r.day = v_scope_day))
    ORDER BY
      CASE WHEN v_scope = 'today' THEN r.seq_day END DESC NULLS LAST,
      r.at DESC,
      r.id DESC
    LIMIT v_limit
  ) t;
  RETURN jsonb_build_object(
    'ok', true,
    'scope', v_scope,
    'day', v_day::text,
    'today_count', v_today_count,
    'today_mine', v_today_mine,
    'records', v_records
  );
END;
$fn$;

REVOKE ALL ON FUNCTION public.draw_record_list(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.draw_record_list(text, integer) TO anon;

-- ---------------------------------------------------------------------------
-- §4 写 RPC（契约 §1.3-1 / §1.3-2）
-- ---------------------------------------------------------------------------

-- 存证创建（幂等 p_id）：服务端校验/归一 → 取当天 seq_day + 链 prev_hash → 算 canon/hash → 落库。
CREATE OR REPLACE FUNCTION public.draw_record_create(
  p_id text, p_params jsonb, p_pool jsonb, p_result jsonb, p_labels jsonb,
  p_seed text, p_algo text DEFAULT 'draw-v1'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid      text;
  v_is_test  boolean;
  v_chk      jsonb;
  v_params   jsonb;
  v_pool     jsonb;
  v_result   jsonb;
  v_labels   jsonb;
  v_algo     text;
  v_count    int;
  v_dup      boolean;
  v_at       timestamptz;
  v_ms       bigint;
  v_day      date;
  v_seq      int;
  v_prev     text;
  v_canon    text;
  v_hash     text;
  v_view     jsonb;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  IF v_sid = '' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_is_test := (v_sid = '3260799999' OR v_sid ~ '^9999[0-9]{6}$');
  -- id 格式（与 CHECK 一致；先校验避免把格式错误变成 SQL 异常）
  IF p_id IS NULL OR p_id !~ '^d[0-9a-z]{8,31}$' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '记录编号不合法');
  END IF;
  -- 幂等：同 id 已存在且 sid 相同 → 返回已存记录（契约 §1.3-1：仍带顶层 today_count/today_mine）
  IF EXISTS (SELECT 1 FROM public.draw_records r WHERE r.id = p_id) THEN
    IF EXISTS (SELECT 1 FROM public.draw_records r WHERE r.id = p_id AND r.sid = v_sid) THEN
      v_view := public.draw_record_get(p_id);
      IF NOT coalesce((v_view->>'ok')::boolean, false) THEN
        RETURN jsonb_build_object('ok', false, 'reason', '记录不存在');
      END IF;
      RETURN jsonb_build_object(
        'ok', true,
        'today_count', (v_view->'record'->>'today_count')::int,
        'today_mine', (v_view->'record'->>'today_mine')::int,
        'record', v_view->'record'
      );
    END IF;
    RETURN jsonb_build_object('ok', false, 'reason', '记录编号冲突');
  END IF;
  -- seed / algo
  IF p_seed IS NULL OR p_seed !~ '^[0-9a-f]{16}$' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '种子不合法');
  END IF;
  v_algo := coalesce(p_algo, 'draw-v1');
  IF v_algo <> 'draw-v1' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '算法不合法');
  END IF;
  -- params（白名单归一）/ pool / result / labels
  v_chk := public.draw_norm_params(p_params);
  IF NOT coalesce((v_chk->>'ok')::boolean, false) THEN
    RETURN v_chk;
  END IF;
  v_params := v_chk->'params';
  v_chk := public.draw_norm_pool(p_pool);
  IF NOT coalesce((v_chk->>'ok')::boolean, false) THEN
    RETURN v_chk;
  END IF;
  v_pool := v_chk->'pool';
  v_count := (v_params->>'count')::int;
  v_dup := (v_params->>'dup')::boolean;
  v_chk := public.draw_norm_result(p_result, v_pool, v_count, v_dup);
  IF NOT coalesce((v_chk->>'ok')::boolean, false) THEN
    RETURN v_chk;
  END IF;
  v_result := v_chk->'result';
  v_chk := public.draw_norm_labels(p_labels, v_result);
  IF NOT coalesce((v_chk->>'ok')::boolean, false) THEN
    RETURN v_chk;
  END IF;
  v_labels := v_chk->'labels';
  -- 事务串行化取号（当天 seq_day）+ 同 is_test 口径 prev_hash 链
  PERFORM pg_advisory_xact_lock(hashtext('public.draw_records'));
  v_at := clock_timestamp();
  v_ms := (extract(epoch FROM v_at) * 1000)::bigint;
  v_day := (v_at AT TIME ZONE 'Asia/Shanghai')::date;
  SELECT count(*)::int + 1 INTO v_seq
  FROM public.draw_records r WHERE r.day = v_day AND r.is_test = v_is_test;
  SELECT r.hash INTO v_prev
  FROM public.draw_records r
  WHERE r.is_test = v_is_test
  ORDER BY r.at DESC, r.id DESC
  LIMIT 1;
  v_prev := coalesce(v_prev, '');
  v_canon := concat_ws(E'\n', 'v1', p_id, v_ms::text, v_day::text, v_seq::text,
                       v_algo, p_seed, v_prev, v_params::text, v_pool::text,
                       v_result::text, v_labels::text);
  v_hash := encode(digest(v_canon, 'sha256'), 'hex');
  INSERT INTO public.draw_records (
    id, sid, is_test, at, created_ms, day, seq_day, params, pool, result,
    labels, seed, algo, prev_hash, hash
  ) VALUES (
    p_id, v_sid, v_is_test, v_at, v_ms, v_day, v_seq, v_params, v_pool, v_result,
    v_labels, p_seed, v_algo, v_prev, v_hash
  )
  ON CONFLICT (id) DO NOTHING;
  IF NOT FOUND THEN
    -- 并发下同 id 已被另一事务写入（极少见）：按幂等/冲突返回，不覆盖任何已存证记录
    IF EXISTS (SELECT 1 FROM public.draw_records r WHERE r.id = p_id AND r.sid = v_sid) THEN
      v_view := public.draw_record_get(p_id);
      IF NOT coalesce((v_view->>'ok')::boolean, false) THEN
        RETURN jsonb_build_object('ok', false, 'reason', '记录不存在');
      END IF;
      RETURN jsonb_build_object(
        'ok', true,
        'today_count', (v_view->'record'->>'today_count')::int,
        'today_mine', (v_view->'record'->>'today_mine')::int,
        'record', v_view->'record'
      );
    END IF;
    RETURN jsonb_build_object('ok', false, 'reason', '记录编号冲突');
  END IF;
  -- 公开视图（§1.3-3）作为 record 返回；today_count/today_mine 同时提到顶层
  v_view := public.draw_record_get(p_id);
  IF NOT coalesce((v_view->>'ok')::boolean, false) THEN
    RETURN jsonb_build_object('ok', false, 'reason', '存证失败，请重试');
  END IF;
  RETURN jsonb_build_object(
    'ok', true,
    'today_count', (v_view->'record'->>'today_count')::int,
    'today_mine', (v_view->'record'->>'today_mine')::int,
    'record', v_view->'record'
  );
EXCEPTION WHEN others THEN
  RETURN jsonb_build_object('ok', false, 'reason', '存证失败，请重试');
END;
$fn$;

REVOKE ALL ON FUNCTION public.draw_record_create(text, jsonb, jsonb, jsonb, jsonb, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.draw_record_create(text, jsonb, jsonb, jsonb, jsonb, text, text) TO anon;

-- 事件追加（剔除/补抽/排序/重置）：仅记录本人；seq 递增 + hash 链；note 超 120 字截断。
CREATE OR REPLACE FUNCTION public.draw_event_append(
  p_id text, p_kind text, p_n integer DEFAULT NULL,
  p_added integer DEFAULT NULL, p_note text DEFAULT ''
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid      text;
  v_rec      public.draw_records%ROWTYPE;
  v_kind     text;
  v_note     text;
  v_seq      int;
  v_prev     text;
  v_at       timestamptz;
  v_ms       bigint;
  v_canon    text;
  v_hash     text;
  v_count    int;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  IF v_sid = '' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  -- 行锁：同一记录的并发事件串行化（seq 与 hash 链安全）
  SELECT * INTO v_rec
  FROM public.draw_records r
  WHERE r.id = p_id AND r.sid = v_sid
  FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'reason', '记录不存在');
  END IF;
  v_kind := lower(btrim(coalesce(p_kind, '')));
  IF v_kind NOT IN ('remove', 'refill', 'sort', 'reset') THEN
    RETURN jsonb_build_object('ok', false, 'reason', '事件类型不合法');
  END IF;
  v_note := left(coalesce(p_note, ''), 120);
  v_at := clock_timestamp();
  v_ms := (extract(epoch FROM v_at) * 1000)::bigint;
  SELECT coalesce(max(e.seq), 0)::int + 1 INTO v_seq
  FROM public.draw_events e WHERE e.record_id = p_id;
  SELECT e.hash INTO v_prev
  FROM public.draw_events e WHERE e.record_id = p_id
  ORDER BY e.seq DESC LIMIT 1;
  v_prev := coalesce(v_prev, v_rec.hash);
  v_canon := concat_ws(E'\n', 'e1', p_id, v_seq::text, v_kind,
                       coalesce(p_n::text, ''), coalesce(p_added::text, ''),
                       v_note, v_ms::text, v_prev);
  v_hash := encode(digest(v_canon, 'sha256'), 'hex');
  INSERT INTO public.draw_events (record_id, seq, kind, n, added, note, at, created_ms, prev_hash, hash)
  VALUES (p_id, v_seq, v_kind, p_n, p_added, v_note, v_at, v_ms, v_prev, v_hash);
  v_count := v_seq;
  RETURN jsonb_build_object(
    'ok', true,
    'event', jsonb_build_object(
      'seq', v_seq, 'kind', v_kind, 'n', p_n, 'added', p_added,
      'note', v_note, 'at', v_ms, 'hash', v_hash, 'prev_hash', v_prev
    ),
    'event_count', v_count
  );
EXCEPTION WHEN others THEN
  RETURN jsonb_build_object('ok', false, 'reason', '事件写入失败，请重试');
END;
$fn$;

REVOKE ALL ON FUNCTION public.draw_event_append(text, text, integer, integer, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.draw_event_append(text, text, integer, integer, text) TO anon;

-- ---------------------------------------------------------------------------
-- §5 测试数据卫生 RPC（契约 §1.3-5 / §1.5）：仅 is_test 身份硬删自己的测试记录
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.draw_test_purge(p_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid     text;
  v_is_test boolean;
  v_deleted int := 0;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  IF v_sid = '' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_is_test := (v_sid = '3260799999' OR v_sid ~ '^9999[0-9]{6}$');
  IF NOT v_is_test THEN
    RETURN jsonb_build_object('ok', false, 'reason', '仅测试身份可清理');
  END IF;
  DELETE FROM public.draw_records r
  WHERE r.id = p_id AND r.is_test = true AND r.sid = v_sid;
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN jsonb_build_object('ok', true, 'deleted', v_deleted);
EXCEPTION WHEN others THEN
  RETURN jsonb_build_object('ok', false, 'reason', '清理失败，请重试');
END;
$fn$;

REVOKE ALL ON FUNCTION public.draw_test_purge(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.draw_test_purge(text) TO anon;

CREATE OR REPLACE FUNCTION public.draw_test_clear()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid     text;
  v_is_test boolean;
  v_deleted int := 0;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_sid := coalesce(public.auth_sid(), '');
  IF v_sid = '' THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份已失效，请重新进入班级');
  END IF;
  v_is_test := (v_sid = '3260799999' OR v_sid ~ '^9999[0-9]{6}$');
  IF NOT v_is_test THEN
    RETURN jsonb_build_object('ok', false, 'reason', '仅测试身份可清理');
  END IF;
  DELETE FROM public.draw_records r
  WHERE r.is_test = true AND r.sid = v_sid;
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN jsonb_build_object('ok', true, 'deleted', v_deleted);
EXCEPTION WHEN others THEN
  RETURN jsonb_build_object('ok', false, 'reason', '清理失败，请重试');
END;
$fn$;

REVOKE ALL ON FUNCTION public.draw_test_clear() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.draw_test_clear() TO anon;

-- 通知 PostgREST 重新加载 schema cache（新表/新函数立即可用；幂等且无副作用）
SELECT pg_notify('pgrst', 'reload schema');
