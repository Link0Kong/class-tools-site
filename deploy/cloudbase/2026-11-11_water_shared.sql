-- 2026-11-11 · 水量统计共享表 public.water / public.water_room（以宿舍为单位）
--
-- 用途（契约：web/tools/tests/_water_shared_contract.md §1/§2）：
--   水量抄表从「本机 UD v6 缓存」升级为「以宿舍为单位的云端共享」：同宿舍任一同学写入后，
--   其他同学进入水量页即可看到同一记录（统计/展示以云端为准；UD v6 water 继续作为离线缓存）。
--   - public.water      ：每宿舍每月一条水表读数（roomverify + month 唯一）
--   - public.water_room ：每宿舍人数（4/6 人间；23 号楼 A/B 座固定 4，由客户端约束）
--   隐私：只有「宿舍标识 / 月份 / 读数 / 人数 / 更新时间」，**不存姓名、学号、手机号**。
--
-- 权限（与 public.homework / public.notices / public.power 同一套班级 token 口径）：
--   读 / 写 / 删：public.auth_ok()（有效班级 token；网页 X-Device-Id、小程序 X-Class-Token 均接受；
--   匿名/过期 token → GET 返回 []、写/删被拒）。anon 授 SELECT/INSERT/UPDATE/DELETE：
--   upsert 用 POST + `Prefer: resolution=merge-duplicates`，DELETE 用于撤销一条记录。
--
-- 说明：`updated_at` 由服务端默认 now() 在插入时写入；客户端 upsert 不发送该字段
--   （同 key 覆盖时 updated_at 保持首次写入值，仅作审计/可选展示，不参与合并判定）。
--
-- 幂等：全部 IF NOT EXISTS / DROP POLICY IF EXISTS + CREATE POLICY，可重复应用（0 错误）。
--
-- 应用：cd web/deploy/cloudbase
--       python apply_sql.py 2026-11-11_water_shared.sql
-- 验证：cd web
--       python deploy/cloudbase/verify_2026_11_11_shared_tables.py
--
-- 回滚（整表删除；前端水量页 GET 失败会保留本机离线缓存，不影响其它工具）：
--   DROP TABLE IF EXISTS public.water;
--   DROP TABLE IF EXISTS public.water_room;
-- 仅回退 RLS（保留数据）：
--   DROP POLICY IF EXISTS water_read   ON public.water;
--   DROP POLICY IF EXISTS water_insert ON public.water;
--   DROP POLICY IF EXISTS water_update ON public.water;
--   DROP POLICY IF EXISTS water_delete ON public.water;
--   DROP POLICY IF EXISTS water_room_read   ON public.water_room;
--   DROP POLICY IF EXISTS water_room_insert ON public.water_room;
--   DROP POLICY IF EXISTS water_room_update ON public.water_room;
--   DROP POLICY IF EXISTS water_room_delete ON public.water_room;
--   REVOKE SELECT, INSERT, UPDATE, DELETE ON public.water, public.water_room FROM anon;

CREATE TABLE IF NOT EXISTS public.water (
  roomverify text NOT NULL,              -- 与 PW_ROOMS 一致，如 4-23B---423
  month      text NOT NULL,              -- YYYY-MM（如 2026-11）
  reading    numeric(10,2) NOT NULL,     -- 水表读数（吨，两位小数）
  persons    int NOT NULL DEFAULT 4 CHECK (persons IN (4, 6)),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (roomverify, month)
);

CREATE TABLE IF NOT EXISTS public.water_room (
  roomverify text PRIMARY KEY,
  persons    int NOT NULL DEFAULT 4 CHECK (persons IN (4, 6)),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.water ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.water_room ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.water TO anon;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.water_room TO anon;

DROP POLICY IF EXISTS water_read ON public.water;

CREATE POLICY water_read ON public.water FOR SELECT TO anon USING (public.auth_ok());

DROP POLICY IF EXISTS water_insert ON public.water;

CREATE POLICY water_insert ON public.water FOR INSERT TO anon WITH CHECK (public.auth_ok());

DROP POLICY IF EXISTS water_update ON public.water;

CREATE POLICY water_update ON public.water FOR UPDATE TO anon USING (public.auth_ok()) WITH CHECK (public.auth_ok());

DROP POLICY IF EXISTS water_delete ON public.water;

CREATE POLICY water_delete ON public.water FOR DELETE TO anon USING (public.auth_ok());

DROP POLICY IF EXISTS water_room_read ON public.water_room;

CREATE POLICY water_room_read ON public.water_room FOR SELECT TO anon USING (public.auth_ok());

DROP POLICY IF EXISTS water_room_insert ON public.water_room;

CREATE POLICY water_room_insert ON public.water_room FOR INSERT TO anon WITH CHECK (public.auth_ok());

DROP POLICY IF EXISTS water_room_update ON public.water_room;

CREATE POLICY water_room_update ON public.water_room FOR UPDATE TO anon USING (public.auth_ok()) WITH CHECK (public.auth_ok());

DROP POLICY IF EXISTS water_room_delete ON public.water_room;

CREATE POLICY water_room_delete ON public.water_room FOR DELETE TO anon USING (public.auth_ok());
