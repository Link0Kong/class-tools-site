-- 2026-11-05 · 宿舍电费表 public.power（班级工具站「全部 → 宿舍电费」卡片）
--
-- 用途：本机同步脚本 C:\briefdesk\scripts\sync_power_cloud.py 串行查询完美校园
--   CloudPay 网关（学校码 769 / payproid 2122「旗山用电支出」/ businesstype 2，
--   method=samllProgramGetRoomState，免登录）的 17 间班级宿舍剩余电量，
--   逐行 upsert 到本表；网页在身份 token 通过后读取展示（低电 <30 度标红）。
--
-- 隐私：本表只有「楼栋 / 房间号 / 剩余电量 / 单位 / 更新时间」，不存姓名、学号、
--   手机号；同步脚本输出同样不含姓名。宿舍号展示是用户明确要求的电费功能本身，
--   不用于任何导出图片或对外分享。
--
-- 2026-11-05 v2（`2026-11-05_power_v2_names.sql`）：统一命名 + id 改 roomverify（稳定主键）+
--   DELETE 授权/策略（同步脚本清理不在 ROOMS 里的过期行）。新建库请直接用下方最终版语句。
--
-- 权限（与 public.notices / public.service_health 同一套 RLS 写法）：
--   读：public.auth_ok()（= 有效班级 token；匿名 / 过期 token 读回 []）
--   写/删：public.auth_admin()（= auth_ok() + private.class_ids.is_admin，仅管理员 token）
--   anon 授 SELECT/INSERT/UPDATE/DELETE；DELETE 仅用于同步脚本清理过期行。
--
-- 应用（tcb CLI 一次只吃一条语句，每条压成一行；语句与下方一致）：
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE TABLE IF NOT EXISTS public.power (...)"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "ALTER TABLE public.power ENABLE ROW LEVEL SECURITY"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "GRANT SELECT, INSERT, UPDATE, DELETE ON public.power TO anon"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP POLICY IF EXISTS pw_read ON public.power"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE POLICY pw_read ON public.power FOR SELECT TO anon USING (public.auth_ok())"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP POLICY IF EXISTS pw_insert ON public.power"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE POLICY pw_insert ON public.power FOR INSERT TO anon WITH CHECK (public.auth_admin())"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP POLICY IF EXISTS pw_update ON public.power"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE POLICY pw_update ON public.power FOR UPDATE TO anon USING (public.auth_admin()) WITH CHECK (public.auth_admin())"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP POLICY IF EXISTS pw_delete ON public.power"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE POLICY pw_delete ON public.power FOR DELETE TO anon USING (public.auth_admin())"
--
-- 回滚（整表删除；前端 power 拉取失败会显示「加载失败」，不影响其它工具）：
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP TABLE IF EXISTS public.power"
-- 仅回退 RLS（保留数据）：
--   DROP POLICY IF EXISTS pw_read ON public.power;
--   DROP POLICY IF EXISTS pw_insert ON public.power;
--   DROP POLICY IF EXISTS pw_update ON public.power;
--   DROP POLICY IF EXISTS pw_delete ON public.power;
--   REVOKE SELECT, INSERT, UPDATE, DELETE ON public.power FROM anon;

CREATE TABLE IF NOT EXISTS public.power (
  id          text PRIMARY KEY,              -- = roomverify（'4-23A---321'），稳定主键，同步脚本按此 upsert
  label       text NOT NULL,                 -- 规范展示名（'13号楼324' / '23号楼A座321'）
  building    text NOT NULL,                 -- 规范楼栋（'13号楼'/'16号楼'/'23号楼A座'/'23号楼B座'）
  room        text NOT NULL,                 -- 房间号（如 '321'）
  roomverify  text NOT NULL,                 -- 完美校园 roomverify（如 '4-23A---321'）
  quantity    numeric,                       -- 剩余电量
  unit        text NOT NULL DEFAULT '度',    -- 单位（网关 quantityunit）
  low         boolean NOT NULL DEFAULT false,-- quantity < 30 度 → true（同步脚本写入）
  updated_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.power ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.power TO anon;

DROP POLICY IF EXISTS pw_read ON public.power;

CREATE POLICY pw_read ON public.power FOR SELECT TO anon USING (public.auth_ok());

DROP POLICY IF EXISTS pw_insert ON public.power;

CREATE POLICY pw_insert ON public.power FOR INSERT TO anon WITH CHECK (public.auth_admin());

DROP POLICY IF EXISTS pw_update ON public.power;

CREATE POLICY pw_update ON public.power FOR UPDATE TO anon USING (public.auth_admin()) WITH CHECK (public.auth_admin());

DROP POLICY IF EXISTS pw_delete ON public.power;

CREATE POLICY pw_delete ON public.power FOR DELETE TO anon USING (public.auth_admin());
