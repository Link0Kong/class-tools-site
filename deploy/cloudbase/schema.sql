-- 班级工具站 · 云端作业表（CloudBase PostgreSQL / PostgREST）
-- 幂等：可重复执行。执行方式：
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "<整段>"
-- 或分条执行（CLI 一次只吃一条语句）。

create table if not exists public.homework (
  id        text primary key,
  subject   text not null,
  content   text not null,
  due       text        default '',
  date      text        default '',
  time      text        default '',
  author    text        default '',
  owner     text        default '',
  attachments text      default '',
  done      boolean not null default false,
  archived  boolean not null default false,
  ts        bigint  not null default 0
);

-- 2026-10-20：发布者归属（只有管理员或发布者能“为所有人删除”）
alter table public.homework add column if not exists owner text default '';
-- 2026-10-20：图片 / 文件附件（JSON 字符串数组，单条 ≤ 600KB）
alter table public.homework add column if not exists attachments text default '';
-- 2026-10-22：作业截止时间（可选 HH:MM；为空按截止日期当天 00:00）
alter table public.homework add column if not exists time text default '';

-- 行级安全：所有访问都走 RLS
alter table public.homework enable row level security;

-- anon（前端 Publishable Key 的身份）权限边界：读 / 写 / 改，但**不能删**
grant usage on schema public to anon;
grant select, insert, update on public.homework to anon;

drop policy if exists hw_read   on public.homework;
drop policy if exists hw_insert on public.homework;
drop policy if exists hw_update on public.homework;

create policy hw_read   on public.homework for select to anon using (true);
create policy hw_insert on public.homework for insert to anon with check (true);
create policy hw_update on public.homework for update to anon using (true) with check (true);
-- 没有 delete policy ⇒ anon 删除必然 401（实测 DATABASE_42501）

-- ------------------------------------------------------------
-- 通知表（2026-10-10 用户确认上云；结构与 RLS 同作业）
-- ------------------------------------------------------------
create table if not exists public.notices (
  id        text primary key,
  title     text not null,
  body      text not null default '',
  pin       boolean not null default false,
  imp       boolean not null default false,
  author    text        default '',
  owner     text        default '',
  attachments text      default '',
  archived  boolean not null default false,
  ts        bigint  not null default 0
);

alter table public.notices add column if not exists owner text default '';
alter table public.notices add column if not exists attachments text default '';

alter table public.notices enable row level security;
grant select, insert, update on public.notices to anon;

drop policy if exists nt_read   on public.notices;
drop policy if exists nt_insert on public.notices;
drop policy if exists nt_update on public.notices;

create policy nt_read   on public.notices for select to anon using (true);
create policy nt_insert on public.notices for insert to anon with check (true);
create policy nt_update on public.notices for update to anon using (true) with check (true);

-- ------------------------------------------------------------
-- 按座号的个人状态表（作业完成 / 通知置顶；2026-10-10）
-- id = "<seat>|<kind>|<ref>"，upsert 用 Prefer: resolution=merge-duplicates
-- 注意：列名不能用 on（SQL 保留字），用 val
-- ------------------------------------------------------------
create table if not exists public.marks (
  id    text primary key,
  seat  text not null,
  kind  text not null,          -- 'hw' | 'nt'
  ref   text not null,          -- homework / notices 的行 id
  val   boolean not null default true,
  ts    bigint  not null default 0
);

alter table public.marks enable row level security;
grant select, insert, update on public.marks to anon;

drop policy if exists mk_read   on public.marks;
drop policy if exists mk_insert on public.marks;
drop policy if exists mk_update on public.marks;

create policy mk_read   on public.marks for select to anon using (true);
create policy mk_insert on public.marks for insert to anon with check (true);
create policy mk_update on public.marks for update to anon using (true) with check (true);

-- ------------------------------------------------------------
-- 访问统计表（分时段访问人数，仅管理员前端可见；2026-10-11 已用 tcb CLI 执行）
-- id = "<did>|<slot>"；slot = 本地时间 YYYY-MM-DD-HH；did = 前端随机设备码
-- 隐私：只存小时级 slot 与随机设备 id，不存 IP / 账号 / 名单等任何个人信息
-- anon 只能读 / 追加，**无 update / delete**（实测均 401 DATABASE_42501）
-- ------------------------------------------------------------
create table if not exists public.visits (
  id    text primary key,
  slot  text not null,
  did   text not null,
  ts    bigint not null default 0
);

alter table public.visits enable row level security;
grant select, insert on public.visits to anon;

drop policy if exists vs_read   on public.visits;
drop policy if exists vs_insert on public.visits;

create policy vs_read   on public.visits for select to anon using (true);
create policy vs_insert on public.visits for insert to anon with check (true);
-- 没有 update / delete policy ⇒ anon 改删必然 401

-- ------------------------------------------------------------
-- 体测记录表（登录后按账号同步；2026-10-13 已用 tcb CLI 执行）
-- id = 前端 cbId()；acc = 账号；data = 记录 JSON（fields/total/grade 等）
-- anon 无 delete，删除走 arch=true 软删；拉取过滤 arch=eq.false
-- ------------------------------------------------------------
create table if not exists public.fitrecs (
  id    text primary key,
  acc   text not null,
  data  text not null default '',
  arch  boolean not null default false,
  ts    bigint  not null default 0
);

alter table public.fitrecs enable row level security;
grant select, insert, update on public.fitrecs to anon;

drop policy if exists ftr_read   on public.fitrecs;
drop policy if exists ftr_insert on public.fitrecs;
drop policy if exists ftr_update on public.fitrecs;

create policy ftr_read   on public.fitrecs for select to anon using (true);
create policy ftr_insert on public.fitrecs for insert to anon with check (true);
create policy ftr_update on public.fitrecs for update to anon using (true) with check (true);
-- 没有 delete policy ⇒ anon 删除必然 401

-- ------------------------------------------------------------
-- 班级名单表（登录后下发；2026-10-13 已用 tcb CLI 执行）
-- 单行：id='main'；data = JSON {roster, ts}（名单文本用 \n 连接，70 行）
-- 软保护：前端仅登录后拉取；未登录渲染层按空名单处理
-- ------------------------------------------------------------
create table if not exists public.roster (
  id    text primary key,
  data  text not null default '',
  ts    bigint not null default 0
);

alter table public.roster enable row level security;
grant select, insert, update on public.roster to anon;

drop policy if exists rstr_read   on public.roster;
drop policy if exists rstr_insert on public.roster;
drop policy if exists rstr_update on public.roster;

create policy rstr_read   on public.roster for select to anon using (true);
create policy rstr_insert on public.roster for insert to anon with check (true);
create policy rstr_update on public.roster for update to anon using (true) with check (true);
-- 没有 delete policy ⇒ anon 删除必然 401

-- ------------------------------------------------------------
-- 账号 / 反馈 / 小程序个人数据（2026-10-18 补记；线上已存在）
-- 用途：网页版登录、反馈；小程序名单/体测录入同步。
-- 权限边界与作业一致：anon SELECT / INSERT / UPDATE，无 DELETE。
-- 此处补记表结构；重建环境时请按同样边界逐表补 RLS 策略。
-- ------------------------------------------------------------
create table if not exists public.users (
  id text primary key,
  h  text not null,
  ts bigint not null default 0
);

create table if not exists public.feedback (
  id      text primary key,
  content text not null,
  contact text default '',
  acc     text default '匿名',
  done    boolean not null default false,
  ts      bigint not null default 0
);

create table if not exists public.userdata (
  id   text primary key,
  blob text not null default '',
  ts   bigint not null default 0
);

grant select, insert, update on public.users to anon;
grant select, insert, update on public.feedback to anon;
grant select, insert, update on public.userdata to anon;

