-- 2026-11-05 · 宿舍电费 v2：统一命名 + id 改 roomverify + 过期行清理授权（增量迁移）
--
-- 背景（用户 2026-11-05 23:10 新需求）：
--   全链路统一规范化宿舍名（{楼号}号楼{座}{房间号}；23 号楼用「23号楼A座 / 23号楼B座」）；
--   `public.power.id` 改为 **roomverify**（稳定主键，不随显示名变化）；
--   同步脚本按 ROOMS 清理过期行（需要 anon DELETE 授权 + 仅管理员 DELETE 策略）。
--
-- 命名对照（旧 label → 新 label / building；room 列值不变）：
--   13号楼324 → 13号楼324 / 13号楼；13号楼308 → 13号楼308 / 13号楼
--   16号楼305 → 16号楼305 / 16号楼；16号楼306 → 16号楼306 / 16号楼
--   23A-321…330 → 23号楼A座321…330 / 23号楼A座
--   23B-422…425 → 23号楼B座422…425 / 23号楼B座
--
-- 应用（tcb CLI 一次一条语句，每条压成一行；语句与下方一致）：
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "UPDATE public.power SET id='1-13---324',label='13号楼324',building='13号楼' WHERE id='13号楼324'"
--   ……（17 行逐条 UPDATE，旧 id=旧 label，新 id=roomverify，新旧值不重叠，逐行不会主键冲突）
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "GRANT DELETE ON public.power TO anon"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "DROP POLICY IF EXISTS pw_delete ON public.power"
--   tcb db execute -e tool-d4gosudok46e0e081 --sql "CREATE POLICY pw_delete ON public.power FOR DELETE TO anon USING (public.auth_admin())"
--
-- 回滚（把 id/label/building 改回旧命名；删除策略回退）：
--   逐行 UPDATE ... SET id='13号楼324',label='13号楼324',building='13号楼'（旧 building 也与 label 相同前缀：
--   旧值：13号楼/16号楼/23A/23B；23A-321 的旧 label=id='23A-321'、旧 building='23A'）
--   DROP POLICY IF EXISTS pw_delete ON public.power;
--   REVOKE DELETE ON public.power FROM anon;

-- ===== 13 / 16 号楼（旧 id = 旧 label；新 building = 楼栋全名）=====
UPDATE public.power SET id='1-13---324', label='13号楼324', building='13号楼' WHERE id='13号楼324';
UPDATE public.power SET id='1-13---308', label='13号楼308', building='13号楼' WHERE id='13号楼308';
UPDATE public.power SET id='1-16---305', label='16号楼305', building='16号楼' WHERE id='16号楼305';
UPDATE public.power SET id='1-16---306', label='16号楼306', building='16号楼' WHERE id='16号楼306';

-- ===== 23 号楼 A 座 =====
UPDATE public.power SET id='4-23A---321', label='23号楼A座321', building='23号楼A座' WHERE id='23A-321';
UPDATE public.power SET id='4-23A---323', label='23号楼A座323', building='23号楼A座' WHERE id='23A-323';
UPDATE public.power SET id='4-23A---324', label='23号楼A座324', building='23号楼A座' WHERE id='23A-324';
UPDATE public.power SET id='4-23A---325', label='23号楼A座325', building='23号楼A座' WHERE id='23A-325';
UPDATE public.power SET id='4-23A---326', label='23号楼A座326', building='23号楼A座' WHERE id='23A-326';
UPDATE public.power SET id='4-23A---327', label='23号楼A座327', building='23号楼A座' WHERE id='23A-327';
UPDATE public.power SET id='4-23A---328', label='23号楼A座328', building='23号楼A座' WHERE id='23A-328';
UPDATE public.power SET id='4-23A---329', label='23号楼A座329', building='23号楼A座' WHERE id='23A-329';
UPDATE public.power SET id='4-23A---330', label='23号楼A座330', building='23号楼A座' WHERE id='23A-330';

-- ===== 23 号楼 B 座 =====
UPDATE public.power SET id='4-23B---422', label='23号楼B座422', building='23号楼B座' WHERE id='23B-422';
UPDATE public.power SET id='4-23B---423', label='23号楼B座423', building='23号楼B座' WHERE id='23B-423';
UPDATE public.power SET id='4-23B---424', label='23号楼B座424', building='23号楼B座' WHERE id='23B-424';
UPDATE public.power SET id='4-23B---425', label='23号楼B座425', building='23号楼B座' WHERE id='23B-425';

-- ===== 同步脚本清理过期行：anon DELETE 授权 + 仅管理员 DELETE 策略 =====
GRANT DELETE ON public.power TO anon;

DROP POLICY IF EXISTS pw_delete ON public.power;

CREATE POLICY pw_delete ON public.power FOR DELETE TO anon USING (public.auth_admin());
