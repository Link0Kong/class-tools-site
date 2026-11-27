(function (root) {
  'use strict';

  const normalize = value => String(value || '').normalize('NFKC').toLowerCase().replace(/\s+/g, '');
  const nameKey = value => normalize(value).replace(/^(\d+)#([a-z]?)$/, '$1号楼$2');

  function roomCode(value) {
    const code = normalize(value).replace(/^教室|(?:教室|室)$/g, '');
    if (/^\d{2}(?:\d|x)\d{2}(?:[a-z]|-\d+)?$/.test(code)) return code.toUpperCase();
    if (/^\d{4}(?:[a-z]|-\d+)?$/.test(code)) return ('0' + code).toUpperCase();
    return '';
  }

  function directory(data) {
    const buildings = data.buildings;
    const byId = new Map(buildings.map(building => [building.id, building]));
    const byName = name => buildings.find(building => [building.n, building.ln].some(key => nameKey(key) === nameKey(name)));
    const roomsById = Object.create(null), aliasesById = Object.create(null), ids = Object.create(null);
    for (const [legacy, group] of Object.entries(data.rooms || {})) {
      const building = byId.get(legacy) || byName(group.name);
      if (!building) continue;
      roomsById[building.id] = group;
      ids[legacy] = building.id;
    }
    for (const [legacy, aliases] of Object.entries(data.alias || {})) {
      const building = byId.get(ids[legacy] || legacy) || aliases.map(byName).find(Boolean)
        || buildings.find(item => /^\d+#\w/.test(item.n) && aliases.some(alias => normalize(alias) === normalize(item.n).replace('#', '')));
      if (!building) continue;
      ids[legacy] = building.id;
      if (!aliasesById[building.id]) aliasesById[building.id] = [];
      aliasesById[building.id].push(legacy, ...aliases);
    }
    const entries = [], indoor = Object.create(null), codes = new Map();
    for (const building of buildings) {
      const group = roomsById[building.id];
      const no = group ? group.no : String(building.no || '');
      const plans = data.indoor && data.indoor[building.id];
      const floors = (plans || (group ? group.floors : []).map(level => ({level, rooms: []})))
        .map(floor => ({...floor, rooms: [...floor.rooms]}));
      for (const code of group ? group.rooms : []) {
        const floor = floors.find(item => item.level === Number(code.charAt(2)));
        if (floor && !floor.rooms.some(item => item.code === code)) floor.rooms.push({code, name: '教室'});
      }
      if (floors.length) indoor[building.id] = floors;
      for (const floor of floors) {
        floor.rooms.sort((a, b) => a.code.localeCompare(b.code));
        floor.rooms = floor.rooms.map((item, index) => ({...item, key: `${building.id}:${floor.level}:${index}`}));
        for (const item of floor.rooms) {
          const entry = {building, room: item.code, level: floor.level, item,
            keys: [item.code, item.name, item.org].map(normalize).filter(Boolean)};
          entries.push(entry);
          const code = roomCode(item.code);
          if (!codes.has(code)) codes.set(code, []);
          codes.get(code).push(entry);
        }
      }
      if (/^(补全建筑\d+|自定义建筑)$/.test(building.n)) continue;
      const dorm = normalize(building.n).match(/^(\d+)#([a-z]?)$/);
      const numbered = no ? [no, String(Number(no)), Number(no) + '号楼', no + '号楼'] : [];
      if (dorm) numbered.push(dorm[1] + dorm[2], dorm[1] + '号楼', dorm[1] + '号楼' + dorm[2]);
      entries.push({building, room: '', keys: [building.id, building.n, building.ln, ...numbered,
        ...(aliasesById[building.id] || [])].map(normalize).filter(Boolean)});
    }

    function search(value) {
      const query = normalize(value);
      if (!query) return [];
      const direct = byId.get(String(value)) || byId.get(ids[String(value)]);
      if (direct) return [{building: direct, room: ''}];
      const code = roomCode(query);
      if (code) {
        if (codes.has(code)) return codes.get(code);
        const building = buildings.find(item => {
          const group = roomsById[item.id];
          return (group ? group.no : String(item.no || '')).padStart(2, '0') === code.slice(0, 2);
        });
        return building ? [{building, room: code, missing: true}] : [];
      }
      return entries.map(entry => ({entry, score: Math.min(...entry.keys.map(key => {
        const index = key.indexOf(query);
        return index < 0 ? Infinity : (key === query ? 0 : index === 0 ? 4 : 8) + (entry.room ? 1 : 0);
      }))})).filter(result => Number.isFinite(result.score)).sort((a, b) => a.score - b.score)
        .slice(0, 12).map(result => result.entry);
    }
    return {search, indoor};
  }

  function parts(building, flat) {
    if (building.parts && building.parts.length) return building.parts.map(part => ({p: part.p, h: flat ? 0 : part.h}));
    return [{p: building.p, h: flat || building.n === '田径场' ? 0 : building.h}];
  }

  function routePlanner(walk) {
    const nodes = walk.p;
    const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
    const edges = nodes.map(() => []);
    for (const [a, b, road] of walk.e) {
      const length = distance(nodes[a], nodes[b]);
      edges[a].push([b, road, length]);
      edges[b].push([a, road, length]);
    }
    let lastSource, cached;

    function snap(point) {
      let best = null;
      for (const [i, j, road] of walk.e) {
        if (road < 0) continue;
        const a = nodes[i], b = nodes[j], dx = b[0] - a[0], dy = b[1] - a[1];
        const t = Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)));
        const target = [a[0] + dx * t, a[1] + dy * t];
        const d = distance(point, target);
        if (!best || d < best.d) best = {target, d, i, j, road};
      }
      return best;
    }

    function tree(from, gps) {
      const start = nodes[walk.stops[from]], done = new Uint8Array(nodes.length);
      const dist = new Float64Array(nodes.length).fill(Infinity);
      const previous = new Int32Array(nodes.length).fill(-1);
      const roadFrom = new Int32Array(nodes.length).fill(-1);
      const onRoad = gps && snap(gps);
      if (onRoad) {
        for (const i of [onRoad.i, onRoad.j]) {
          dist[i] = distance(onRoad.target, nodes[i]);
          roadFrom[i] = onRoad.road;
        }
      } else if (start) dist[walk.stops[from]] = 0;
      else return null;
      for (let i = 0; i < nodes.length; i++) {
        let u = -1, best = Infinity;
        for (let j = 0; j < nodes.length; j++) if (!done[j] && dist[j] < best) [u, best] = [j, dist[j]];
        if (u < 0) break;
        done[u] = 1;
        for (const [v, road, length] of edges[u]) {
          const next = best + length;
          if (done[v] || next >= dist[v]) continue;
          dist[v] = next;
          previous[v] = u;
          roadFrom[v] = road;
        }
      }
      return {dist, previous, roadFrom, onRoad};
    }

    function route(from, to, gps) {
      const end = walk.stops[to];
      if (from === to || end === undefined) return null;
      if (gps || from !== lastSource) {
        cached = tree(from, gps);
        lastSource = gps ? null : from;
      }
      if (!cached || !Number.isFinite(cached.dist[end])) return null;
      const pts = [], names = [];
      for (let i = end; i >= 0; i = cached.previous[i]) {
        pts.push(nodes[i]);
        const name = walk.names[cached.roadFrom[i]];
        if (name && name !== names[names.length - 1]) names.push(name);
      }
      if (cached.onRoad) pts.push(cached.onRoad.target);
      else if (pts.length < 2) pts.push(pts[0]);
      const meters = Math.round((cached.dist[end] + (cached.onRoad ? cached.onRoad.d : 0)) * walk.scale);
      return {pts: pts.reverse(), from: gps || pts[0], to: nodes[end], names: names.reverse(), m: meters,
        mins: Math.max(1, Math.round(meters / 78))};
    }
    return {route, snap};
  }

  function floorScene(ctx, floor, selected, view, dark) {
    const colors = dark ? ['#172823', '#263E34', '#384F43', '#1D6855', '#B6E5D1', '#F2F7F2']
      : ['#F0F4ED', '#DFEAE0', '#FDFDF9', '#A6DCC6', '#287257', '#213B32'];
    const {width, height, scale, x, y} = view;
    ctx.fillStyle = colors[0];
    ctx.fillRect(0, 0, width, height);
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(scale, scale);
    ctx.lineJoin = 'round';
    function shape(points, fill, width) {
      if (!points || !points.length) return;
      ctx.beginPath();
      ctx.moveTo(...points[0]);
      for (const point of points.slice(1)) ctx.lineTo(...point);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.lineWidth = width;
      ctx.strokeStyle = colors[4];
      ctx.stroke();
    }
    function label(text, points, size) {
      const x = points.reduce((sum, point) => sum + point[0], 0) / points.length;
      const y = points.reduce((sum, point) => sum + point[1], 0) / points.length;
      ctx.fillStyle = colors[5];
      ctx.font = `600 ${size}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, x, y);
    }
    shape(floor.outline, colors[1], 1.1);
    shape(floor.court, colors[0], 1.1);
    for (const facility of floor.facilities) {
      shape(facility.p, colors[1], 0.65);
      label(facility.name, facility.p, 9);
    }
    for (const room of floor.rooms) {
      if (!room.p) continue;
      const active = selected === room.key;
      shape(room.p, active ? colors[3] : colors[2], active ? 2 : 0.65);
      label(room.code.replace(/^0(?=[12])/, ''), room.p, active ? 14 : 11);
    }
    ctx.restore();
  }

  function contains(x, y, points) {
    let inside = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const [ax, ay] = points[i], [bx, by] = points[j];
      if ((ay > y) !== (by > y) && x < (bx - ax) * (y - ay) / (by - ay) + ax) inside = !inside;
    }
    return inside;
  }

  const api = {directory, parts, roomCode, routePlanner, floorScene, contains};
  if (typeof module === 'object') module.exports = api;
  else root.CampusLogic = api;
})(typeof globalThis === 'undefined' ? this : globalThis);
