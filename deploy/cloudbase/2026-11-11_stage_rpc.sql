-- 2026-11-11 · 大屏临时互联服务鉴权 + 名单工具团员名单：两个只读 RPC
--
-- 用途（需求：班级工具站「大屏临时互联服务」鉴权 + 「名单工具」展示团员名单）：
--   1) public.class_whoami() → jsonb
--      服务端（ECS 互联服务）用 `X-Device-Id: <班级 token>` 头调用，返回**当前 token 自身**身份：
--        {ok:true,sid,seat,name}
--      无 token / token 失效 → {ok:false,reason:"未登录"}；
--      token 有效但班级名单里查不到该 sid → {ok:false,reason:"身份无效"}。
--      * 必须接受测试身份（private.class_ids.is_test=true，QA/审核需要），is_test 不作过滤；
--      * 只返回本人，不返回任何他人信息。
--   2) public.class_league() → jsonb
--      返回班级团员名单（private.class_league ⨝ private.class_ids）：
--        {ok:true,count:N,seats:[{seat,name}...]}   -- seat 升序
--      未登录 → {ok:false,reason:"未登录"}。
--      * 排除测试身份（is_test=true）；
--      * **不返回 sid / 学号**，每项只有 seat/name 两个字段。
--
-- 安全：两个函数均 SECURITY DEFINER + `set search_path=public,private,pg_temp`，
--       只读（无写操作），`revoke all ... from public` 后仅 `grant execute ... to anon`。
--       与既有 `public.class_members()` / `public.auth_is_league()` 同一套 token 鉴权
--       （`public.auth_hdr()` 同时接受 `X-Class-Token` 与 `X-Device-Id`，`public.auth_sid()` 校验
--       private.class_sessions + expires_at）。
--
-- 幂等：全部 CREATE OR REPLACE FUNCTION，可重复应用。
--
-- 应用：
--   cd web/deploy/cloudbase
--   python apply_sql.py 2026-11-11_stage_rpc.sql --dry-run
--   python apply_sql.py 2026-11-11_stage_rpc.sql
-- 测试：
--   cd web/tools
--   python tests\stage_rpc_check.py --probe     # 只读探测（列/函数签名）
--   python tests\stage_rpc_check.py             # 真实云端黑盒
--
-- 回滚（仅删除本文件新增的两个函数，不影响其它功能）：
--   DROP FUNCTION IF EXISTS public.class_whoami();
--   DROP FUNCTION IF EXISTS public.class_league();

-- ---------------------------------------------------------------------------
-- §1 class_whoami：当前 token 自身身份（服务端鉴权用）
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.class_whoami()
RETURNS jsonb
LANGUAGE plpgsql
STABLE SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_sid  text;
  v_seat int;
  v_name text;
BEGIN
  -- auth_sid() 只对「存在且未过期」的 private.class_sessions 返回 sid（无效/过期/无头 → NULL）
  v_sid := nullif(btrim(coalesce(public.auth_sid(), '')), '');
  IF v_sid IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'reason', '未登录');
  END IF;
  -- 不过滤 is_test：测试身份（private.class_ids.is_test=true）必须可鉴权
  SELECT c.seat, c.name INTO v_seat, v_name
  FROM private.class_ids c
  WHERE c.sid = v_sid
  LIMIT 1;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'reason', '身份无效');
  END IF;
  RETURN jsonb_build_object('ok', true, 'sid', v_sid, 'seat', v_seat, 'name', v_name);
END;
$fn$;

REVOKE ALL ON FUNCTION public.class_whoami() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.class_whoami() TO anon;

-- ---------------------------------------------------------------------------
-- §2 class_league：团员名单（座号 + 姓名，无学号）
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.class_league()
RETURNS jsonb
LANGUAGE plpgsql
STABLE SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
DECLARE
  v_seats jsonb;
BEGIN
  IF NOT public.auth_ok() THEN
    RETURN jsonb_build_object('ok', false, 'reason', '未登录');
  END IF;
  SELECT coalesce(
           jsonb_agg(jsonb_build_object('seat', x.seat, 'name', x.name) ORDER BY x.seat),
           '[]'::jsonb
         )
    INTO v_seats
  FROM (
    SELECT DISTINCT c.seat, c.name
    FROM private.class_league l
    JOIN private.class_ids c ON c.sid = l.sid
    WHERE NOT coalesce(c.is_test, false)
  ) x;
  -- count 与 seats 数组长度恒一致
  RETURN jsonb_build_object('ok', true, 'count', jsonb_array_length(v_seats), 'seats', v_seats);
END;
$fn$;

REVOKE ALL ON FUNCTION public.class_league() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.class_league() TO anon;
