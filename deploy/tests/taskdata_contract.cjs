// Executable acceptance model for task writers. The SQL suite runs the repository
// migration as-is in ephemeral PostgreSQL. No app, endpoint or credentials needed.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const { isDeepStrictEqual: equal } = require('node:util');
const fixtures = require('./taskdata_conflicts_v1.json');

function unpack(blob, ts) {
  if (blob === '' && ts === 0) return { path: [], leaf: { v: 1, items: [], lists: [] } };
  let leaf;
  try { leaf = typeof blob === 'string' ? JSON.parse(blob) : blob; } catch { return null; }
  const keys = [];
  while (leaf && typeof leaf === 'object' && !Array.isArray(leaf)) {
    if (Array.isArray(leaf.items)) {
      if (leaf.lists !== undefined && !Array.isArray(leaf.lists)) return null;
      try { byId(leaf.items); byId(leaf.lists); } catch { return null; }
      return { path: keys, leaf };
    }
    if (keys.length === 3) break;
    const next = ['task', 'data', 'v'].find(key =>
      leaf[key] && typeof leaf[key] === 'object' && !Array.isArray(leaf[key]));
    if (!next) break;
    keys.push(next);
    leaf = leaf[next];
  }
  return null;
}

function replayFields(before, local, remote) {
  const result = { ...remote };
  for (const [key, value] of Object.entries(local)) {
    if (!equal(before[key], value)) result[key] = value;
  }
  return result;
}

function byId(rows) {
  const indexed = new Map();
  for (const row of rows || []) {
    assert.ok(typeof row.id === 'string' && row.id && !indexed.has(row.id), 'missing/duplicate id');
    indexed.set(row.id, row);
  }
  return indexed;
}

function sameNewTask(candidate, existing) {
  if (candidate.fromId) return existing.fromId === candidate.fromId && existing.due === candidate.due;
  return ['sourceHwId', 'sourceNoticeId'].some(key => candidate[key] && existing[key] === candidate[key]);
}

function replayEntities(base, local, remote, duplicate) {
  const before = byId(base), after = byId(local), merged = byId(remote);
  for (const id of before.keys()) if (!after.has(id)) merged.delete(id);
  for (const [id, row] of after) {
    if (equal(row, before.get(id)) || (before.has(id) && !merged.has(id))) continue;
    if (duplicate && !merged.has(id) && [...merged.values()].some(existing => duplicate(row, existing))) continue;
    merged.set(id, replayFields(before.get(id) || {}, row, merged.get(id)));
  }
  return [...merged.values()];
}

function rebase(base, local, remote) {
  const result = { ...remote, items: replayEntities(base.items, local.items, remote.items, sameNewTask) };
  if (Array.isArray(local.lists)) result.lists = replayEntities(base.lists, local.lists, remote.lists);
  if (local.prefs) {
    const edited = { ...local.prefs };
    if ((edited.sidebarOrderAt || 0) < (remote.prefs?.sidebarOrderAt || 0)) {
      delete edited.sidebarOrder;
      delete edited.sidebarOrderAt;
    }
    result.prefs = replayFields(base.prefs || {}, edited, remote.prefs);
  }
  const groups = byId(result.lists);
  result.items = result.items.map(({ attachments, localFiles, ...row }) =>
    row.list && Array.isArray(result.lists) && !groups.has(row.list) ? { ...row, list: '' } : row);
  return result;
}

function responseEvent(rows, expected) {
  if (!Array.isArray(rows)) return 'unverified';
  if (rows.length === 0) return 'zero';
  const [row] = rows;
  if (rows.length !== 1 || !row || row.id !== expected.id || row.blob !== expected.blob) return 'unverified';
  if (!Number.isSafeInteger(expected.ts) || (row.ts !== expected.ts && row.ts !== String(expected.ts))) return 'unverified';
  return 'row';
}

function receipt(event, sameSession = true, attempt = 1) {
  if (!sameSession) return 'discard';
  if (event === '401' || event === '403') return 'rejected';
  if (event === 'row') return 'confirmed';
  if (event === 'zero' && attempt < 4) return 'reread';
  return 'pending';
}

function nextStamp(oldStamp, clock, localStamp = 0) {
  for (const value of [oldStamp, clock, localStamp]) {
    assert.ok(Number.isSafeInteger(value) && value >= 0, 'invalid stamp');
  }
  const next = Math.max(oldStamp + 1, clock, localStamp);
  assert.ok(Number.isSafeInteger(next), 'stamp overflow');
  return next;
}

for (const entry of fixtures.merge) {
  test('merge: ' + entry.name, () => {
    assert.deepEqual(rebase(entry.base, entry.local, entry.remote), entry.expected);
  });
}
for (const entry of fixtures.wire) {
  test('wire: ' + entry.name, () => {
    const decoded = unpack(entry.blob, entry.ts);
    assert.deepEqual(decoded ? decoded.path : null, entry.path);
    if (!decoded || !decoded.path.length) return;
    const root = typeof entry.blob === 'string' ? JSON.parse(entry.blob) : structuredClone(entry.blob);
    const original = structuredClone(root);
    const parent = decoded.path.slice(0, -1).reduce((node, key) => node[key], root);
    const key = decoded.path.at(-1);
    parent[key] = { ...decoded.leaf, items: [{ id: 'qa-updated' }] };
    assert.deepEqual(unpack(root).leaf.items, [{ id: 'qa-updated' }]);
    parent[key] = decoded.leaf;
    assert.deepEqual(root, original);
  });
}
for (const entry of fixtures.receipt) {
  test('receipt: ' + entry.name, () => {
    assert.equal(receipt(entry.event, entry.sameSession, entry.attempt), entry.status);
  });
}
for (const entry of fixtures.returnedRows) {
  test('representation: ' + entry.name, () => {
    const expected = { id: '9999000001', ts: 42, blob: '{"items":[]}' };
    assert.equal(responseEvent(entry.rows, expected), entry.event);
  });
}
test('stamp: tied clocks, behind, ahead, overflow', () => {
  assert.equal(nextStamp(100, 100), 101);
  assert.equal(nextStamp(100, 2), 101);
  assert.equal(nextStamp(100, 108, 115), 115);
  assert.throws(() => nextStamp(Number.MAX_SAFE_INTEGER, 1), /overflow/);
});

test('legacy cache with no baseline cannot imply a deletion or overwrite by omission', () => {
  // An unmarked cache is display-only. Explicit new actions have their own
  // before/after pair; apply only those, then persist the first verified base.
  const cache = { items: [{ id: 'qa-stale' }] };
  const afterEdit = { items: [...cache.items, { id: 'qa-new' }] };
  const remote = { items: [{ id: 'qa-unseen' }] };
  assert.deepEqual(rebase(cache, cache, remote), remote);
  assert.deepEqual(rebase(cache, afterEdit, remote).items, [...remote.items, { id: 'qa-new' }]);
});

test('new token or owner while a write is in flight: old callbacks cannot acknowledge or reject the new session', async () => {
  let active = { sid: '9999000001', generation: 1, status: 'pending' };
  async function write(reply) {
    const owner = active;
    const event = await reply;
    const state = receipt(event, owner === active);
    if (state !== 'discard') owner.status = state;
    return state;
  }
  for (const nextSid of ['9999000001', '9999000002']) {
    const delayed = Promise.withResolvers();
    const sent = write(delayed.promise);
    active = { sid: nextSid, generation: active.generation + 1, status: 'pending' };
    delayed.resolve(nextSid === '9999000001' ? '401' : 'row');
    assert.equal(await sent, 'discard');
    assert.equal(active.status, 'pending');
  }
});

test('PostgreSQL: actual taskdata migration and legacy coexistence', async t => {
  const { PGlite } = require('@electric-sql/pglite');
  const db = new PGlite();
  t.after(() => db.close());
  // Session variables stand in only for auth_ok/auth_acc. Policies, schema,
  // privileges, conflict resolution and predicate matching are PostgreSQL's.
  await db.exec(`
    CREATE ROLE anon;
    CREATE FUNCTION public.auth_acc() RETURNS text LANGUAGE sql STABLE
      AS $$ SELECT current_setting('qa.sid', true) $$;
    CREATE FUNCTION public.auth_ok() RETURNS boolean LANGUAGE sql STABLE
      AS $$ SELECT current_setting('qa.auth', true) = 'valid' $$;
  `);
  await db.exec(readFileSync(path.join(__dirname, '../cloudbase/2026-11-22_taskdata.sql'), 'utf8'));
  await db.exec("SET ROLE anon; SET qa.sid = '9999000001'; SET qa.auth = 'valid';");
  const id = '9999000001';
  const initial = { v: 1, items: [], lists: [] };
  const a = { ...initial, items: [{ id:'qa-a' }] };
  const b = { ...initial, items: [{ id:'qa-b' }] };
  async function rows(sql, args) { return (await db.query(sql, args)).rows; }
  const fetch = () => rows('SELECT blob, ts FROM taskdata WHERE id=$1', [id]);
  const insert = (snapshot, stamp, owner = id) => rows(
    'INSERT INTO taskdata(id,blob,ts) VALUES($1,$2,$3) ON CONFLICT(id) DO NOTHING RETURNING id,blob,ts',
    [owner, JSON.stringify(snapshot), stamp]);
  const patch = (expected, snapshot, stamp) => rows(
    'UPDATE taskdata SET blob=$2,ts=$3 WHERE id=$1 AND ts=$4 RETURNING id,blob,ts',
    [id, JSON.stringify(snapshot), stamp, expected]);
  const legacy = (snapshot, stamp) => rows(
    'INSERT INTO taskdata(id,blob,ts) VALUES($1,$2,$3) ON CONFLICT(id) DO UPDATE SET blob=excluded.blob,ts=excluded.ts RETURNING id',
    [id, JSON.stringify(snapshot), stamp]);
  async function saved() {
    const [row] = await fetch();
    return [JSON.parse(row.blob), Number(row.ts)];
  }
  await t.test('two empty reads, one successful insert; stale patch re-reads and preserves both edits', async () => {
    assert.deepEqual(await fetch(), []);
    assert.deepEqual(await fetch(), []);
    assert.equal(responseEvent(await insert(a, 100), { id, blob: JSON.stringify(a), ts: 100 }), 'row');
    assert.deepEqual(await insert(b, 100), []);
    const [remote, stamp] = await saved();
    assert.deepEqual(await patch(0, b, 100), []);
    const merged = rebase(initial, b, remote);
    const next = nextStamp(stamp, 99);
    assert.equal(responseEvent(await patch(stamp, merged, next), { id, blob: JSON.stringify(merged), ts: next }), 'row');
    assert.deepEqual(await saved(), [{ ...initial, items: [...a.items, ...b.items] }, 101]);
  });
  await t.test('lost acknowledgment: read-back proves the saved change; versioned clear survives delayed conditional edit', async () => {
    const [before, stamp] = await saved();
    await patch(stamp, initial, stamp + 1); // discard the response as on a timeout
    assert.equal(receipt('network'), 'pending');
    const [remote, current] = await saved();
    assert.deepEqual(remote, initial);
    assert.equal(current, stamp + 1);
    assert.deepEqual(await patch(stamp, a, current), []);
    assert.deepEqual(rebase(before, a, remote), initial);
  });
  await t.test('four contended attempts have zero rows, no false confirmation', async () => {
    for (let attempt = 1; attempt <= 4; attempt++) {
      const [remote, old] = await saved();
      assert.equal((await patch(old, remote, old + 1)).length, 1); // another writer
      const response = await patch(old, a, old + 1);
      assert.deepEqual(response, []);
      assert.equal(receipt('zero', true, attempt), attempt === 4 ? 'pending' : 'reread');
    }
    assert.deepEqual((await saved())[0], initial);
  });
  await t.test('legacy unconditional writer can roll back ts, reuse it (ABA), or overwrite with a faster clock', async () => {
    const [snapshot, previous] = await saved();
    await legacy(a, 10);
    assert.deepEqual(await saved(), [a, 10]);
    await legacy(b, previous);
    assert.equal((await patch(previous, snapshot, previous + 1)).length, 1);
    await legacy(a, previous + 2000);
    assert.deepEqual(await saved(), [a, previous + 2000]);
  });
  await t.test('two conditional clients interleaved with a legacy writer: recover provable edits only', async () => {
    const [verifiedBase, stamp] = await saved(); // both devices have confirmed qa-a
    const added = { ...initial, items: [...a.items, ...b.items] };
    const renamed = { ...initial, items: [{ id: 'qa-a', title: 'edited offline' }] };
    assert.equal((await patch(stamp, added, stamp + 1)).length, 1);
    await legacy(a, stamp + 100); // the old client drops the new qa-b
    assert.deepEqual(await patch(stamp, renamed, stamp + 1), []);
    const [remote, fresh] = await saved();
    const replayed = rebase(verifiedBase, renamed, remote);
    assert.equal((await patch(fresh, replayed, nextStamp(fresh, 10))).length, 1);
    assert.deepEqual(await saved(), [renamed, fresh + 1]); // qa-b was never seen by the second client
  });
  await t.test('RLS isolates a different owner and an expired session; no DELETE grant', async () => {
    const [before, stamp] = await saved();
    await db.exec("SET qa.sid = '9999000002'");
    assert.deepEqual(await fetch(), []);
    assert.deepEqual(await patch(stamp, b, stamp + 1), []);
    await assert.rejects(() => insert(b, 1), { code: '42501' });
    await db.exec("SET qa.sid = '9999000001'; SET qa.auth = 'expired'");
    assert.deepEqual(await fetch(), []);
    assert.deepEqual(await patch(stamp, b, stamp + 1), []);
    await assert.rejects(() => insert(b, 1), { code: '42501' });
    await db.exec("SET qa.auth = 'valid'");
    await assert.rejects(() => rows('DELETE FROM taskdata WHERE id=$1', [id]), { code: '42501' });
    assert.deepEqual(await saved(), [before, stamp]);
  });
});
