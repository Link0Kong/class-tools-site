-- 2026-11-08 · 诊断 v2（设备诊断 + AI 分析 + 自动修复）+ 课表登录（云收单 + 本机代理）
--
-- 背景（旅行者 2026-11-08 需求）：
--   ① 诊断页：加入使用设备诊断，异常自动上传云端；本机 AI 扫描服务后给出可能原因；若问题在云端且本机在线且易修复，
--      由本机守护进程（C:\briefdesk\scripts\diag_agent.py）直接修复，并在诊断页给出流程提示；诊断对“所有已登录班级成员”可见。
--   ② 课表登录：体育课等个人课表不同 → 学生输入自己的学号+教务密码，云端只做三件事：
--      （1）校验班级 token 与 sid（auth_ok / auth_sid）；
--      （2）用本机 agent 的 PGP 公钥把密码加密成密文（pgp_pub_encrypt）存 login_jobs；
--      （3）本机 agent（校园网）解密 → 登录教务抓课表 → 回写 result；密码用后即清（pwd_pgp=''，job 过期清理）。
--      * 云端无法直连校园内网教务（实测 210.34.74.77 超时），所以必须本机代理。
--
-- 权限模型（与现有迁移一致）：
--   读：public.auth_ok()（任意有效班级 token）；写诊断分析/修复任务/agent key/job：public.auth_admin()（仅管理员 token）。
--   客户端只有两条 RPC 可写 login_jobs：tt_login_enqueue（只写自己）、tt_login_status（只读自己）；无直接表权限。
--
-- 应用（幂等）：web/deploy/cloudbase/apply_sql.py 逐条执行（tcb db execute 一次一条）。
-- 回滚：DROP TABLE IF EXISTS public.client_diag, public.diag_analysis, public.repair_tasks, public.login_jobs, public.agent_keys;
--       DROP FUNCTION IF EXISTS public.tt_login_enqueue(text,text), public.tt_login_status(text), public.diag_agent_info();

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------- 1) client_diag 设备诊断上报
CREATE TABLE IF NOT EXISTS public.client_diag (
  id           text PRIMARY KEY,
  sid          text NOT NULL DEFAULT '',
  platform     text NOT NULL DEFAULT '',        -- web | mp | android
  app_ver      text NOT NULL DEFAULT '',
  kind         text NOT NULL DEFAULT 'error',   -- error | network | storage | crash | perf | manual
  level        text NOT NULL DEFAULT 'warn',    -- error | warn | info
  message      text NOT NULL DEFAULT '',
  detail       jsonb NOT NULL DEFAULT '{}'::jsonb,   -- 脱敏后的细节（不含姓名/学号/token/宿舍）
  device       jsonb NOT NULL DEFAULT '{}'::jsonb,   -- 脱敏后的设备信息
  fingerprint  text NOT NULL DEFAULT '',
  ts           bigint NOT NULL,
  status       text NOT NULL DEFAULT 'new',     -- new | analyzed | ignored
  analysis_id  text NOT NULL DEFAULT '',
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS client_diag_ts_idx ON public.client_diag (ts DESC);
CREATE INDEX IF NOT EXISTS client_diag_status_idx ON public.client_diag (status, ts DESC);

ALTER TABLE public.client_diag ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE ON public.client_diag TO anon;

DROP POLICY IF EXISTS cd_read ON public.client_diag;
CREATE POLICY cd_read ON public.client_diag FOR SELECT TO anon USING (public.auth_ok());

DROP POLICY IF EXISTS cd_insert ON public.client_diag;
CREATE POLICY cd_insert ON public.client_diag FOR INSERT TO anon
  WITH CHECK (public.auth_ok() AND sid = coalesce(public.auth_sid(), ''));

DROP POLICY IF EXISTS cd_update ON public.client_diag;
CREATE POLICY cd_update ON public.client_diag FOR UPDATE TO anon
  USING (public.auth_admin()) WITH CHECK (public.auth_admin());

-- ---------------------------------------------------------------- 2) diag_analysis AI 分析 + 修复流程
CREATE TABLE IF NOT EXISTS public.diag_analysis (
  id           text PRIMARY KEY,
  ts           bigint NOT NULL,
  platform     text NOT NULL DEFAULT 'all',     -- all | web | mp | android
  scope        text NOT NULL DEFAULT 'cloud',   -- cloud | device | mixed
  severity     text NOT NULL DEFAULT 'warn',    -- error | warn | info
  title        text NOT NULL DEFAULT '',
  cause        text NOT NULL DEFAULT '',        -- 可能原因（AI）
  suggestion   jsonb NOT NULL DEFAULT '[]'::jsonb,  -- 修复建议（字符串数组）
  fixable      boolean NOT NULL DEFAULT false,
  action       text NOT NULL DEFAULT '',        -- 白名单动作 id（空=不自动修）
  status       text NOT NULL DEFAULT 'new',     -- new | queued | running | fixed | failed | manual | ignored
  confidence   numeric(4,2) NOT NULL DEFAULT 0,
  flow         jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{t,text,st}] 流程提示（诊断页展示）
  related      jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {diag_ids, health_ids, repair_id}
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS diag_analysis_ts_idx ON public.diag_analysis (ts DESC);

ALTER TABLE public.diag_analysis ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.diag_analysis TO anon;

DROP POLICY IF EXISTS da_read ON public.diag_analysis;
CREATE POLICY da_read ON public.diag_analysis FOR SELECT TO anon USING (public.auth_ok());

DROP POLICY IF EXISTS da_write ON public.diag_analysis;
CREATE POLICY da_write ON public.diag_analysis FOR ALL TO anon
  USING (public.auth_admin()) WITH CHECK (public.auth_admin());

-- ---------------------------------------------------------------- 3) repair_tasks 本机修复任务/记录
CREATE TABLE IF NOT EXISTS public.repair_tasks (
  id           text PRIMARY KEY,
  created_at   bigint NOT NULL,
  action       text NOT NULL,
  params       jsonb NOT NULL DEFAULT '{}'::jsonb,
  reason       text NOT NULL DEFAULT '',
  status       text NOT NULL DEFAULT 'pending',  -- pending | running | done | failed | skipped
  claimed_at   bigint NOT NULL DEFAULT 0,
  finished_at  bigint NOT NULL DEFAULT 0,
  result       text NOT NULL DEFAULT '',
  analysis_id  text NOT NULL DEFAULT '',
  node         text NOT NULL DEFAULT 'local',
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS repair_tasks_ts_idx ON public.repair_tasks (created_at DESC);

ALTER TABLE public.repair_tasks ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.repair_tasks TO anon;

DROP POLICY IF EXISTS rt_read ON public.repair_tasks;
CREATE POLICY rt_read ON public.repair_tasks FOR SELECT TO anon USING (public.auth_ok());

DROP POLICY IF EXISTS rt_write ON public.repair_tasks;
CREATE POLICY rt_write ON public.repair_tasks FOR ALL TO anon
  USING (public.auth_admin()) WITH CHECK (public.auth_admin());

-- ---------------------------------------------------------------- 4) agent_keys 本机 agent 公钥 + 心跳
CREATE TABLE IF NOT EXISTS public.agent_keys (
  id           text PRIMARY KEY,               -- 'tt_login' 固定
  pubkey       text NOT NULL DEFAULT '',       -- ASCII armored PGP public key
  host         text NOT NULL DEFAULT '',       -- 脱敏主机标识（如 'local-windows'）
  seen_at      bigint NOT NULL DEFAULT 0,      -- 最近心跳（unix ms）
  version      text NOT NULL DEFAULT '',
  created_at   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.agent_keys ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE ON public.agent_keys TO anon;

DROP POLICY IF EXISTS ak_admin ON public.agent_keys;
CREATE POLICY ak_admin ON public.agent_keys FOR ALL TO anon
  USING (public.auth_admin()) WITH CHECK (public.auth_admin());

-- ---------------------------------------------------------------- 5) login_jobs 课表登录任务（密码仅密文）
CREATE TABLE IF NOT EXISTS public.login_jobs (
  id           text PRIMARY KEY,
  sid          text NOT NULL,
  platform     text NOT NULL DEFAULT '',
  pwd_pgp      text NOT NULL DEFAULT '',       -- base64( pgp_pub_encrypt(password) )；用后置空
  created_at   bigint NOT NULL,
  expires_at   bigint NOT NULL,
  status       text NOT NULL DEFAULT 'pending',-- pending | claimed | done | failed | expired
  claimed_at   bigint NOT NULL DEFAULT 0,
  finished_at  bigint NOT NULL DEFAULT 0,
  result       jsonb,                          -- {c:[{name,teacher,room,day,start,end,weeks,parity}],t:'YYYY-MM-DD',meta:{}}
  error        text NOT NULL DEFAULT '',
  node         text NOT NULL DEFAULT 'local'
);

CREATE INDEX IF NOT EXISTS login_jobs_status_idx ON public.login_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS login_jobs_sid_idx ON public.login_jobs (sid, created_at DESC);

ALTER TABLE public.login_jobs ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.login_jobs TO anon;

DROP POLICY IF EXISTS lj_admin ON public.login_jobs;
CREATE POLICY lj_admin ON public.login_jobs FOR ALL TO anon
  USING (public.auth_admin()) WITH CHECK (public.auth_admin());

-- ---------------------------------------------------------------- 6) 诊断对所有人可见：service_health 读放宽
DROP POLICY IF EXISTS sh_read ON public.service_health;
CREATE POLICY sh_read ON public.service_health FOR SELECT TO anon USING (public.auth_ok());

-- ---------------------------------------------------------------- 7) RPC：课表登录（客户端唯一写入口）
CREATE OR REPLACE FUNCTION public.tt_login_enqueue(p_pwd text, p_platform text DEFAULT '')
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
declare
  v_sid   text := public.auth_sid();
  v_key   text;
  v_seen  bigint;
  v_cnt   int;
  v_pend  text;
  v_job   text;
  v_now   bigint := (extract(epoch from clock_timestamp()) * 1000)::bigint;
  v_enc   text;
begin
  if not public.auth_ok() or v_sid is null or v_sid = '' then
    return jsonb_build_object('ok', false, 'reason', 'auth');
  end if;
  if p_pwd is null or length(btrim(p_pwd)) < 1 or length(p_pwd) > 128 then
    return jsonb_build_object('ok', false, 'reason', 'pwd');
  end if;
  -- 本机 agent 在线 + 公钥就绪
  select pubkey, seen_at into v_key, v_seen from public.agent_keys where id = 'tt_login';
  if v_key is null or v_key = '' or v_seen is null or v_now - v_seen > 180000 then
    return jsonb_build_object('ok', false, 'reason', 'agent_offline');
  end if;
  -- 已有未完成任务 → 复用，避免重复入队
  select id into v_pend from public.login_jobs
    where sid = v_sid and status in ('pending', 'claimed') and expires_at > v_now
    order by created_at desc limit 1;
  if v_pend is not null then
    return jsonb_build_object('ok', true, 'job_id', v_pend, 'reused', true);
  end if;
  -- 限流：每学号每小时最多 3 次
  select count(*) into v_cnt from public.login_jobs where sid = v_sid and created_at > v_now - 3600000;
  if v_cnt >= 3 then
    return jsonb_build_object('ok', false, 'reason', 'rate');
  end if;
  -- 密码用本机 agent 公钥加密（密文才落库；云端/数据库均无明文）
  begin
    v_enc := encode(pgp_pub_encrypt(p_pwd, dearmor(v_key)), 'base64');
  exception when others then
    return jsonb_build_object('ok', false, 'reason', 'encrypt');
  end;
  v_job := md5(random()::text || clock_timestamp()::text || v_sid);
  insert into public.login_jobs (id, sid, platform, pwd_pgp, created_at, expires_at, status)
  values (v_job, v_sid, coalesce(nullif(p_platform, ''), ''), v_enc, v_now, v_now + 900000, 'pending');
  return jsonb_build_object('ok', true, 'job_id', v_job);
end;
$fn$;

GRANT EXECUTE ON FUNCTION public.tt_login_enqueue(text, text) TO anon;

CREATE OR REPLACE FUNCTION public.tt_login_status(p_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
declare
  v_sid  text := public.auth_sid();
  v_row  public.login_jobs%rowtype;
begin
  if not public.auth_ok() then
    return jsonb_build_object('ok', false, 'reason', 'auth');
  end if;
  select * into v_row from public.login_jobs where id = p_id;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;
  if not public.auth_admin() and v_row.sid <> coalesce(v_sid, '') then
    return jsonb_build_object('ok', false, 'reason', 'forbidden');
  end if;
  return jsonb_build_object(
    'ok', true,
    'status', v_row.status,
    'finished', v_row.finished_at,
    'error', v_row.error,
    'result', v_row.result
  );
end;
$fn$;

GRANT EXECUTE ON FUNCTION public.tt_login_status(text) TO anon;

-- ---------------------------------------------------------------- 8) RPC：诊断页读取本机 agent 在线状态（所有人）
CREATE OR REPLACE FUNCTION public.diag_agent_info()
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, private, pg_temp
AS $fn$
  select jsonb_build_object(
    'ok', true,
    'online', coalesce((extract(epoch from clock_timestamp()) * 1000)::bigint - seen_at < 180000, false),
    'seen_at', coalesce(seen_at, 0),
    'host', coalesce(host, ''),
    'version', coalesce(version, '')
  ) from public.agent_keys where id = 'tt_login'
  union all
  select jsonb_build_object('ok', true, 'online', false, 'seen_at', 0, 'host', '', 'version', '')
  where not exists (select 1 from public.agent_keys where id = 'tt_login');
$fn$;

GRANT EXECUTE ON FUNCTION public.diag_agent_info() TO anon;

-- 2026-11-08 实测修正：客户端不传 sid 时由默认值从班级 token 归属（RLS cd_insert 依赖 sid=auth_sid()）
ALTER TABLE public.client_diag ALTER COLUMN sid SET DEFAULT public.auth_sid();
