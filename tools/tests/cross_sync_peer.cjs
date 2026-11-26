// Adapter for cross_client_sync_check.py. All app requests go to its loopback mock service.
const path = require('node:path');
const { createInterface } = require('node:readline');
const [root, endpoint] = process.argv.slice(2);
const url = new URL(endpoint);
if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1') throw Error('Expected local fixture');
const { device } = require(path.join(root, 'tests/mock_device.js'));
const peer = device({ async respond(req) {
  try {
    const parsed = new URL(req.url);
    const message = { table: parsed.pathname.split('/').pop(), method: req.method, query: Object.fromEntries(parsed.searchParams),
      token: req.header['X-Class-Token'], prefer: req.header.Prefer, range: req.header.Range, body: req.data || null };
    const response = await fetch(endpoint, {method: 'POST', body: JSON.stringify(message), signal: AbortSignal.timeout(8000)});
    req.success({statusCode: response.status, data: await response.json(), header: Object.fromEntries(response.headers)});
  } catch (e) { req.fail(e); }
}});
let water;
async function act({op, sid, token, id, title, room, month, reading}) {
  const t = peer.task;
  switch (op) {
    case 'login': peer.identity.save({sid, name:'测试账号', token}); return true;
    case 'task-pull': await t.pull(true); break;
    case 'task-add': t.upsert(t.emptyItem({id,title})); await t.flush(); break;
    case 'task-edit': t.findTask(id).title = title; t.save(); await t.flush(); break;
    case 'task-homework': t.addFromHW({id,subject:'QA',content:'source'},true); await t.flush(); break;
    case 'task-done': t.setDone(id,true); await t.flush(); break;
    case 'water-room':
      water = peer.page('water/water'); water.onLoad(); water.setData({sel:room}); await water._cloudSync(true); break;
    case 'water-refresh': await water._cloudSync(true); break;
    case 'water-save':
      water.onMonthChange({detail:{value:month}}); water.onReadingInput({detail:{value:String(reading)}});
      await water.saveRecord(); await water._cloudSync(true); break;
    default: throw Error('Unknown test action: '+op);
  }
  if (op.startsWith('water-')) return {data:water.data, room:water._room()};
  return {items:t.items().map(({id,title,done,sourceHwId})=>({id,title,done,sourceHwId})), state:t.state()};
}
(async () => {
  const lines = createInterface({input:process.stdin});
  for await(const line of lines) {
    try { process.stdout.write(JSON.stringify({result:await act(JSON.parse(line))})+'\n'); }
    catch(error) { process.stdout.write(JSON.stringify({error:String(error.stack || error)})+'\n'); }
  }
})();
