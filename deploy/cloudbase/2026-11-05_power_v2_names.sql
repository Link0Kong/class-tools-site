-- 2026-11-05 · 宿舍电费 v2：统一命名 + id 改 roomverify + 过期行清理授权（增量迁移）
--
-- 背景（2026-11-05 新需求）：
--   全链路统一规范化宿舍名（{楼号}号楼{座}{房间号}；23 号楼用「23号楼A座 / 23号楼B座」）；
--   `public.power.id` 改为 **roomverify**（稳定主键，不随显示名变化）；
--   同步脚本按 ROOMS 清理过期行（需要 anon DELETE 授权 + 仅管理员 DELETE 策略）。
--
-- 说明：本文件中的房号均为**虚构示例**（301/302…），仅用于演示迁移写法；
--       实际部署时按自己的宿舍清单替换对应行即可。
--
-- 命名对照（旧 label → 新 label / building；room 列值不变）：
--   13号楼301 → 13号楼301 / 13号楼；13号楼302 → 13号楼302 / 13号楼
--   16号楼301 → 16号楼301 / 16号楼；16号楼302 → 16号楼302 / 16号楼
--   23A-301…309 → 23号楼A座301…309 / 23号楼A座
--   23B-401…404 → 23号楼B座401…404 / 23号楼B座
--
-- 应用（tcb CLI 一次一条语句，每条压成一行；语句与下方一致）：
--   tcb db execute -e <ENV_ID> --sql "UPDATE public.power SET id='1-13---301',label='13号楼301',building='13号楼' WHERE id='13号楼301'"
--   ……（17 行逐条 UPDATE，旧 id=旧 label，新 id=roomverify，新旧值不重叠，逐行不会主键冲突）
--   tcb db execute -e <ENV_ID> --sql "GRANT DELETE ON public.power TO anon"
--   tcb db execute -e <ENV_ID> --sql "DROP POLICY IF EXISTS pw_delete ON public.power"
--   tcb db execute -e <ENV_ID> --sql "CREATE POLICY pw_delete ON public.power FOR DELETE TO anon USING (public.auth_admin())"
--
-- 回滚（把 id/label/building 改回旧命名；删除策略回退）：
--   逐行 UPDATE ... SET id='13号楼301',label='13号楼301',building='13号楼'（旧 building 也与 label 相同前缀：
--   旧值：13号楼/16号楼/23A/23B；23A-301 的旧 label=id='23A-301'、旧 building='23A'）
--   DROP POLICY IF EXISTS pw_delete ON public.power;
--   REVOKE DELETE ON public.power FROM anon;

-- ===== 13 / 16 号楼（旧 id = 旧 label；新 building = 楼栋全名）=====
UPDATE public.power SET id='1-13---301', label='13号楼301', building='13号楼' WHERE id='13号楼301';
UPDATE public.power SET id='1-13---302', label='13号楼302', building='13号楼' WHERE id='13号楼302';
UPDATE public.power SET id='1-16---301', label='16号楼301', building='16号楼' WHERE id='16号楼301';
UPDATE public.power SET id='1-16---302', label='16号楼302', building='16号楼' WHERE id='16号楼302';

-- ===== 23 号楼 A 座 =====
UPDATE public.power SET id='4-23A---301', label='23号楼A座301', building='23号楼A座' WHERE id='23A-301';
UPDATE public.power SET id='4-23A---302', label='23号楼A座302', building='23号楼A座' WHERE id='23A-302';
UPDATE public.power SET id='4-23A---303', label='23号楼A座303', building='23号楼A座' WHERE id='23A-303';
UPDATE public.power SET id='4-23A---304', label='23号楼A座304', building='23号楼A座' WHERE id='23A-304';
UPDATE public.power SET id='4-23A---305', label='23号楼A座305', building='23号楼A座' WHERE id='23A-305';
UPDATE public.power SET id='4-23A---306', label='23号楼A座306', building='23号楼A座' WHERE id='23A-306';
UPDATE public.power SET id='4-23A---307', label='23号楼A座307', building='23号楼A座' WHERE id='23A-307';
UPDATE public.power SET id='4-23A---308', label='23号楼A座308', building='23号楼A座' WHERE id='23A-308';
UPDATE public.power SET id='4-23A---309', label='23号楼A座309', building='23号楼A座' WHERE id='23A-309';

-- ===== 23 号楼 B 座 =====
UPDATE public.power SET id='4-23B---401', label='23号楼B座401', building='23号楼B座' WHERE id='23B-401';
UPDATE public.power SET id='4-23B---402', label='23号楼B座402', building='23号楼B座' WHERE id='23B-402';
UPDATE public.power SET id='4-23B---403', label='23号楼B座403', building='23号楼B座' WHERE id='23B-403';
UPDATE public.power SET id='4-23B---404', label='23号楼B座404', building='23号楼B座' WHERE id='23B-404';

-- ===== 同步脚本清理过期行：anon DELETE 授权 + 仅管理员 DELETE 策略 =====
GRANT DELETE ON public.power TO anon;

DROP POLICY IF EXISTS pw_delete ON public.power;

CREATE POLICY pw_delete ON public.power FOR DELETE TO anon USING (public.auth_admin());
