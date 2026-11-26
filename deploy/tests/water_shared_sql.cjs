const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const { PGlite } = require('@electric-sql/pglite');

const waterMigration = '2026-11-11_water_shared.sql';
const personsMigration = '2026-11-19_water_persons_1_6.sql';
const month = '2030-03';
const room = 'qa-room-one';
const otherRoom = 'qa-room-two';

function applyMigration(db, name) {
  return db.exec(readFileSync(join(__dirname, '..', 'cloudbase', name), 'utf8'));
}

async function openWater(t, { legacy = false } = {}) {
  const db = new PGlite();
  t.after(() => db.close());
  // Only the identity decision is synthetic. Apply the original grants, policies and checks.
  await db.exec(`
    CREATE ROLE anon;
    CREATE FUNCTION public.auth_ok() RETURNS boolean LANGUAGE sql STABLE AS $$
      SELECT coalesce(current_setting('qa.token', true), '') IN ('qa-a', 'qa-b')
    $$;
  `);
  await applyMigration(db, waterMigration);
  if (!legacy) await applyMigration(db, personsMigration);
  await db.exec('SET ROLE anon');

  const rows = async (sql, args) => (await db.query(sql, args)).rows;
  return {
    db, rows,
    as: token => rows("SELECT set_config('qa.token', $1, false)", [token]),
    months: key => rows(
      'SELECT month, reading::text, persons FROM water WHERE roomverify=$1 ORDER BY month', [key]),
    persons: key => rows('SELECT persons FROM water_room WHERE roomverify=$1', [key]),
    saveMonth: (key, record) => rows(`
      INSERT INTO water(roomverify, month, reading, persons) VALUES ($1, $2, $3, $4)
      ON CONFLICT (roomverify, month) DO UPDATE SET reading=excluded.reading, persons=excluded.persons
      RETURNING month, reading::text, persons
    `, [key, record.month, record.reading, record.persons]),
    savePersons: (key, value) => rows(`
      INSERT INTO water_room(roomverify, persons) VALUES ($1, $2)
      ON CONFLICT (roomverify) DO UPDATE SET persons=excluded.persons RETURNING persons
    `, [key, value]),
    deleteMonth: (key, date) => rows(
      'DELETE FROM water WHERE roomverify=$1 AND month=$2 RETURNING month', [key, date]),
    deleteRoom: key => rows('DELETE FROM water_room WHERE roomverify=$1 RETURNING persons', [key]),
  };
}

test('persons migration preserves old rows and allows 1 through 6 in both tables', async t => {
  const water = await openWater(t, { legacy: true });
  const original = { month, reading: '12.30', persons: 4 };
  await water.as('qa-a');
  await water.saveMonth(room, original);
  await water.savePersons(room, 6);
  await assert.rejects(() => water.saveMonth(room, { ...original, persons: 3 }), { code: '23514' });
  await assert.rejects(() => water.savePersons(room, 3), { code: '23514' });

  await water.db.exec('RESET ROLE');
  await applyMigration(water.db, personsMigration);
  await water.db.exec('SET ROLE anon');
  assert.deepEqual(await water.months(room), [original]);
  assert.deepEqual(await water.persons(room), [{ persons: 6 }]);

  for (let persons = 1; persons <= 6; persons++) {
    const reading = { ...original, persons };
    await water.as('qa-a');
    assert.deepEqual(await water.saveMonth(room, reading), [reading]);
    assert.deepEqual(await water.savePersons(room, persons), [{ persons }]);
    await water.as('qa-b');
    assert.deepEqual(await water.months(room), [reading]);
    assert.deepEqual(await water.persons(room), [{ persons }]);
  }
  for (const persons of [0, 7]) {
    await assert.rejects(() => water.saveMonth(room, { ...original, persons }), { code: '23514' });
    await assert.rejects(() => water.savePersons(room, persons), { code: '23514' });
  }
});

test('a deleted month stays absent after reads and returns after legacy upsert', async t => {
  const water = await openWater(t);
  await water.as('qa-a');
  await water.saveMonth(room, { month, reading: '12.30', persons: 6 });
  await water.savePersons(room, 6);
  const [cached] = await water.months(room);
  await water.as('qa-b');
  assert.deepEqual(await water.deleteMonth(room, month), [{ month }]);

  await water.db.exec('BEGIN READ ONLY');
  for (const token of ['qa-a', 'qa-b', 'qa-a', 'qa-b']) {
    await water.as(token);
    assert.deepEqual(await water.months(room), []);
    assert.deepEqual(await water.persons(room), [{ persons: 6 }]);
  }
  await water.db.exec('COMMIT');
  await water.as('qa-a');
  assert.deepEqual(await water.saveMonth(room, cached), [cached]);
  await water.as('qa-b');
  assert.deepEqual(await water.months(room), [cached]);
});

test('a second authenticated account can read, edit and delete another room', async t => {
  const water = await openWater(t);
  const first = { month, reading: '22.00', persons: 2 };
  const edited = { month, reading: '23.00', persons: 3 };
  await water.as('qa-a');
  await water.saveMonth(otherRoom, first);
  await water.savePersons(otherRoom, first.persons);
  await water.as('qa-b');
  assert.deepEqual(await water.months(otherRoom), [first]);
  assert.deepEqual(await water.persons(otherRoom), [{ persons: first.persons }]);
  assert.deepEqual(await water.saveMonth(otherRoom, edited), [edited]);
  assert.deepEqual(await water.savePersons(otherRoom, edited.persons), [{ persons: edited.persons }]);
  assert.deepEqual(await water.deleteMonth(otherRoom, month), [{ month }]);
  assert.deepEqual(await water.deleteRoom(otherRoom), [{ persons: edited.persons }]);
  await water.as('qa-a');
  assert.deepEqual(await water.months(otherRoom), []);
  assert.deepEqual(await water.persons(otherRoom), []);
});

test('RLS hides existing rows and blocks changes when auth_ok() is false', async t => {
  const water = await openWater(t);
  const original = { month, reading: '12.30', persons: 6 };
  const replacement = { month, reading: '0.00', persons: 1 };
  await water.as('qa-a');
  await water.saveMonth(room, original);
  await water.savePersons(room, original.persons);
  for (const token of ['', 'qa-expired', 'qa-unknown']) {
    await water.as(token);
    assert.deepEqual(await water.months(room), []);
    assert.deepEqual(await water.persons(room), []);
    assert.deepEqual(await water.rows('UPDATE water SET persons=1 WHERE roomverify=$1 RETURNING persons', [room]), []);
    assert.deepEqual(await water.rows('UPDATE water_room SET persons=1 WHERE roomverify=$1 RETURNING persons', [room]), []);
    assert.deepEqual(await water.deleteMonth(room, month), []);
    assert.deepEqual(await water.deleteRoom(room), []);
    for (const key of [room, otherRoom]) {
      await assert.rejects(() => water.saveMonth(key, replacement), { code: '42501' });
      await assert.rejects(() => water.savePersons(key, 1), { code: '42501' });
    }
  }
  await water.as('qa-a');
  assert.deepEqual(await water.months(room), [original]);
  assert.deepEqual(await water.persons(room), [{ persons: original.persons }]);
  assert.deepEqual(await water.months(otherRoom), []);
  assert.deepEqual(await water.persons(otherRoom), []);
});
