-- 2026-11-19 · 宿舍人数放开为 1–6 自选
--
-- 背景：原 `water` / `water_room` 的 persons CHECK 只允许 4 / 6，且 23A/23B 由客户端
--       强制 4。用户要求「宿舍人数为 6 人以下自选」，即 1/2/3/4/5/6 均可写入。
--
-- 本迁移只改 CHECK 约束，不动数据；已有 4/6 数据保持原值。
-- 幂等：先按“包含 persons 的 CHECK”逐个删除，再重建命名约束。

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT conname
      FROM pg_constraint
     WHERE conrelid = 'public.water'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%persons%'
  LOOP
    EXECUTE format('ALTER TABLE public.water DROP CONSTRAINT %I', r.conname);
  END LOOP;

  FOR r IN
    SELECT conname
      FROM pg_constraint
     WHERE conrelid = 'public.water_room'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%persons%'
  LOOP
    EXECUTE format('ALTER TABLE public.water_room DROP CONSTRAINT %I', r.conname);
  END LOOP;
END $$;

ALTER TABLE public.water
  ADD CONSTRAINT water_persons_1_6 CHECK (persons BETWEEN 1 AND 6);

ALTER TABLE public.water_room
  ADD CONSTRAINT water_room_persons_1_6 CHECK (persons BETWEEN 1 AND 6);

COMMENT ON COLUMN public.water.persons IS '宿舍人数 1–6（2026-11-19 起自选；默认 4）';
COMMENT ON COLUMN public.water_room.persons IS '宿舍人数 1–6（2026-11-19 起自选；默认 4）';
