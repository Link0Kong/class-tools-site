-- 2026-11-17 · 通知列表轻量化（微信小程序性能优化）
--
-- 背景：public.notices 的自动通知行 body 内嵌图片/文件 data URI，整表响应已增长到 ~14 MB
--       （实测 105 行 / 13.38 MB body，其中 items[].url 8.6 MB、items[].src 4.4 MB、
--        archive.files[].url 0.45 MB）。小程序每次冷启动/签名变化都拉整表，8s 超时 →
--        请求错误率高、启动卡顿、iOS 内存压力大；且 14 MB > 小程序 storage 上限，缓存永远失败。
--
-- 方案（不缩减任何功能）：
--   1) notice_lite_body(body)：把 [[CLASS_NOTICE_V1]] JSON 里的 data URI 字段
--      （items[].url / items[].src / items[].archive.files[].url|src）替换为空串，
--      并在对象上写 lazy=true；其余字段（标题/时间/摘要/文件名/大小/清单）原样保留。
--      单条响应从 ~14 MB 降到 ~0.3 MB。
--   2) class_notices_meta()：返回与 notices?select=* 同构的行数组（body 换成 lite），
--      仅有效班级 token 可调用（auth_ok）；小程序列表改用它。
--   3) 打开附件/图片时，小程序再按 id 拉单行完整 body（RLS 不变），功能不丢。
--
-- 应用（Lead 执行；幂等）：
--   cd web\deploy\cloudbase
--   python apply_sql.py 2026-11-17_notice_meta.sql
--
-- 回滚：
--   DROP FUNCTION IF EXISTS public.class_notices_meta();
--   DROP FUNCTION IF EXISTS public.notice_lite_body(text);
--   小程序端把 utils/cloud.js 的 noticesMeta 开关关掉即回退旧整表链路（代码保留 legacy）。

CREATE OR REPLACE FUNCTION public.notice_lite_body(p_body text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $fn$
DECLARE
  v_prefix constant text := '[[CLASS_NOTICE_V1]]';
  v_json jsonb;
  v_items jsonb;
  v_out jsonb := '[]'::jsonb;
  v_item jsonb;
  v_archive jsonb;
  v_files jsonb;
  v_out_files jsonb;
  v_file jsonb;
  v_lazy boolean;
  i int;
  j int;
BEGIN
  IF p_body IS NULL OR p_body = '' OR left(p_body, length(v_prefix)) <> v_prefix THEN
    RETURN p_body;
  END IF;
  BEGIN
    v_json := substr(p_body, length(v_prefix) + 1)::jsonb;
  EXCEPTION WHEN others THEN
    RETURN p_body;
  END;
  IF v_json IS NULL OR jsonb_typeof(v_json) <> 'object' THEN RETURN p_body; END IF;
  v_items := v_json -> 'items';
  IF v_items IS NULL OR jsonb_typeof(v_items) <> 'array' THEN RETURN p_body; END IF;
  FOR i IN 0 .. jsonb_array_length(v_items) - 1 LOOP
    v_item := v_items -> i;
    IF v_item IS NULL OR jsonb_typeof(v_item) <> 'object' THEN
      v_out := v_out || jsonb_build_array(v_item);
      CONTINUE;
    END IF;
    v_lazy := false;
    IF lower(coalesce(v_item ->> 'url', '')) LIKE 'data:%' THEN
      v_item := jsonb_set(v_item, '{url}', '""'::jsonb, true);
      v_lazy := true;
    END IF;
    IF lower(coalesce(v_item ->> 'src', '')) LIKE 'data:%' THEN
      v_item := jsonb_set(v_item, '{src}', '""'::jsonb, true);
      v_lazy := true;
    END IF;
    v_archive := v_item -> 'archive';
    IF v_archive IS NOT NULL AND jsonb_typeof(v_archive) = 'object' THEN
      v_files := v_archive -> 'files';
      IF v_files IS NOT NULL AND jsonb_typeof(v_files) = 'array' THEN
        v_out_files := '[]'::jsonb;
        FOR j IN 0 .. jsonb_array_length(v_files) - 1 LOOP
          v_file := v_files -> j;
          IF v_file IS NOT NULL AND jsonb_typeof(v_file) = 'object' THEN
            IF lower(coalesce(v_file ->> 'url', '')) LIKE 'data:%' THEN
              v_file := jsonb_set(v_file, '{url}', '""'::jsonb, true);
              v_file := jsonb_set(v_file, '{lazy}', 'true'::jsonb, true);
              v_lazy := true;
            END IF;
            IF lower(coalesce(v_file ->> 'src', '')) LIKE 'data:%' THEN
              v_file := jsonb_set(v_file, '{src}', '""'::jsonb, true);
              v_file := jsonb_set(v_file, '{lazy}', 'true'::jsonb, true);
              v_lazy := true;
            END IF;
          END IF;
          v_out_files := v_out_files || jsonb_build_array(v_file);
        END LOOP;
        v_item := jsonb_set(v_item, '{archive,files}', v_out_files, true);
      END IF;
    END IF;
    IF v_lazy THEN
      v_item := jsonb_set(v_item, '{lazy}', 'true'::jsonb, true);
    END IF;
    v_out := v_out || jsonb_build_array(v_item);
  END LOOP;
  RETURN v_prefix || jsonb_set(v_json, '{items}', v_out, true)::text;
END;
$fn$;

CREATE OR REPLACE FUNCTION public.class_notices_meta()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $fn$
BEGIN
  IF NOT public.auth_ok() THEN
    RAISE EXCEPTION 'unauthorized' USING ERRCODE = '42501';
  END IF;
  RETURN coalesce((
    SELECT jsonb_agg(
             to_jsonb(t) || jsonb_build_object('body', public.notice_lite_body(t.body))
             ORDER BY t.ts ASC, t.id ASC
           )
    FROM public.notices t
    WHERE t.archived = false
  ), '[]'::jsonb);
END;
$fn$;

GRANT EXECUTE ON FUNCTION public.notice_lite_body(text) TO anon;
GRANT EXECUTE ON FUNCTION public.class_notices_meta() TO anon;

NOTIFY pgrst, 'reload schema';
