# -*- coding: utf-8 -*-
"""预览 v2：建筑贴地（基座/裙边/接触阴影）+ 真实道路图导航 + 路名/POI 标注。"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(HERE, "preview_template.html")
s = io.open(p, encoding="utf-8").read()


def rep(a, b, label, required=True):
    global s
    if a in s:
        s = s.replace(a, b, 1)
        print("OK", label)
    else:
        print("MISS", label)
        if required:
            raise SystemExit("anchor missing: " + label)


# ---------------------------------------------------------------- 1. 常量
rep('''  /* ---------------- camera ---------------- */''',
    '''  var BASE_H = 1.4;                 /* 基座高度：让体块真正坐在场地/湖岸上 */
  var ORIGINS = [
    { id: "south", name: "南门", xy: [326, 458] },
    { id: "east", name: "东侧门", xy: [692, 399] },
    { id: "dorm", name: "宿舍区", xy: [200, 250] }
  ];
  var ORIGIN = "south";
  /* 道路名：依据公开地图截图整理（近似，仅供导航文案） */
  var ROAD_NAME = {
    R01: "环湖路", R02: "修园南路", R03: "杏林大道", R04: "杏林大道", R05: "修园北路",
    R06: "仲景路", R07: "仲景东路", R12: "修园西路", R14: "修园东路", R15: "学府路"
  };
  var ROAD_LABELS = [
    { id: "R05", f: 0.46 }, { id: "R01", f: 0.24 }, { id: "R03", f: 0.58 },
    { id: "R06", f: 0.52 }, { id: "R07", f: 0.55 }, { id: "R12", f: 0.52 },
    { id: "R14", f: 0.45 }, { id: "R02", f: 0.66 }, { id: "R15", f: 0.34 }
  ];

  /* ---------------- camera ---------------- */''', "constants")

# ---------------------------------------------------------------- 2. 多边形外扩助手
rep('''  function projPts(pts, z) {
    var out = [];
    for (var t = 0; t < pts.length; t++) out.push(proj(pts[t][0], pts[t][1], z || 0));
    return out;
  }''',
    '''  function projPts(pts, z) {
    var out = [];
    for (var t = 0; t < pts.length; t++) out.push(proj(pts[t][0], pts[t][1], z || 0));
    return out;
  }
  /* 多边形外扩（用于建筑裙边/基座；L 形也能大致贴合） */
  function offsetPoly(pts, d) {
    var n = pts.length, area = 0, i;
    for (i = 0; i < n; i++) {
      var a = pts[i], b = pts[(i + 1) % n];
      area += a[0] * b[1] - b[0] * a[1];
    }
    var sign = area >= 0 ? 1 : -1, out = [];
    for (i = 0; i < n; i++) {
      var prev = pts[(i - 1 + n) % n], cur = pts[i], next = pts[(i + 1) % n];
      var e1x = cur[0] - prev[0], e1y = cur[1] - prev[1];
      var e2x = next[0] - cur[0], e2y = next[1] - cur[1];
      var l1 = Math.hypot(e1x, e1y) || 1, l2 = Math.hypot(e2x, e2y) || 1;
      var n1x = (e1y / l1) * sign, n1y = (-e1x / l1) * sign;
      var n2x = (e2y / l2) * sign, n2y = (-e2x / l2) * sign;
      var nx = n1x + n2x, ny = n1y + n2y, nl = Math.hypot(nx, ny) || 1;
      out.push([cur[0] + nx / nl * d, cur[1] + ny / nl * d]);
    }
    return out;
  }
  function centerOf(pts) {
    var x = 0, y = 0;
    for (var i = 0; i < pts.length; i++) { x += pts[i][0]; y += pts[i][1]; }
    return [x / pts.length, y / pts.length];
  }''', "offsetPoly")

# ---------------------------------------------------------------- 3. drawFlat: 建筑裙边（铺在场地/湖岸上）
rep('''    flatPass(GROUPS.island, "#D5E6CC", "#C6DDBB", 1);
    /* 广场 */''',
    '''    flatPass(GROUPS.island, "#D5E6CC", "#C6DDBB", 1);
    /* 建筑裙边：把建筑脚下铺成场地，避免体块“漂”在水面上 */
    for (i = 0; i < BLD.length; i++) {
      var bfp0 = polygonOf(BLD[i].id);
      if (!bfp0) continue;
      var apron = offsetPoly(bfp0, 2.4);
      fillPoly(projPts(apron, 0.07), "#F0F2E5", "rgba(150,165,145,.30)", 0.8);
    }
    var ctxF = GROUPS.context || [];
    for (i = 0; i < ctxF.length; i++) {
      var cap = offsetPoly(ctxF[i].p, 2.0);
      fillPoly(projPts(cap, 0.07), "#F0F2E5", "rgba(150,165,145,.22)", 0.7);
    }
    /* 广场 */''', "aprons")

# ---------------------------------------------------------------- 4. 重写 drawObjects（基座 + 楼体）
start = s.index("  function drawObjects() {")
end = s.index("  /* ---------------- shadows + route ---------------- */")
new_objects = '''  function pushPrism(items, fp, h0, h1, topColor, wallColor, stroke, lw, isCtx) {
    var i, j;
    for (i = 0; i < fp.length; i++) {
      var p0 = fp[i], p1 = fp[(i + 1) % fp.length];
      var q = [proj(p0[0], p0[1], h0), proj(p1[0], p1[1], h0), proj(p1[0], p1[1], h1), proj(p0[0], p0[1], h1)];
      if (Math.abs(q[1][0] - q[0][0]) + Math.abs(q[2][1] - q[1][1]) < 0.45) continue;
      var depth = (q[0][2] + q[1][2] + q[2][2] + q[3][2]) / 4;
      var light = (q[1][0] - q[0][0]) >= 0 ? 0.16 : -0.14;
      items.push({ t: "f", d: depth, pts: q, fill: mix(wallColor, light), stroke: stroke, lw: lw });
    }
    var top = [], td = 0;
    for (j = 0; j < fp.length; j++) { var tq = proj(fp[j][0], fp[j][1], h1); top.push(tq); td += tq[2]; }
    td /= fp.length;
    items.push({ t: "f", d: td + 0.01, pts: top, fill: topColor, stroke: stroke, lw: lw, top: 1 });
  }
  function drawObjects() {
    var items = [], i, j;
    /* 建筑：基座（外扩 1.6） + 楼体（从基座顶起） */
    for (i = 0; i < BLD.length; i++) {
      var b = BLD[i], fp = polygonOf(b.id);
      if (!fp) continue;
      var c = wallColorFor(b), h = b.h || 9;
      var base = offsetPoly(fp, 1.6);
      var stone = (b.id === SEL) ? "#E8F1EC" : "#E7E1D0";
      pushPrism(items, base, 0, BASE_H, mix(stone, 0.18), stone, "rgba(120,112,92,.22)", 0.7, false);
      pushPrism(items, fp, BASE_H, BASE_H + h, c.roof, c.wall, "rgba(62,78,66,.26)", 0.9, false);
    }
    /* 红线外周边建筑（低层、灰调，只作环境） */
    var ctxFeatures = GROUPS.context || [];
    for (i = 0; i < ctxFeatures.length; i++) {
      var cfp = ctxFeatures[i].p, ch = 7.5;
      var cbase = offsetPoly(cfp, 1.4);
      pushPrism(items, cbase, 0, 0.8, "#EAE7DE", "#E5E2D8", "rgba(120,130,120,.14)", 0.6, true);
      pushPrism(items, cfp, 0.8, 0.8 + ch, "#E6E4DB", "#EDEBE3", "rgba(120,130,120,.15)", 0.6, true);
    }
    /* 树 */
    for (i = 0; i < TREES.length; i++) {
      var tr = TREES[i], tp = proj(tr[0], tr[1], Math.max(1.6, 2.1));
      items.push({ t: "t", d: tp[2], x: tp[0], y: tp[1], r: Math.max(2.2, tr[2] * 2.0 * scaleNow() / 3.4) });
    }
    items.sort(function (a, b) { return a.d - b.d; });
    for (i = 0; i < items.length; i++) {
      var it = items[i];
      if (it.t === "f") {
        fillPoly(it.pts, it.fill, it.stroke, it.lw);
      } else {
        ctx.beginPath(); ctx.ellipse(it.x, it.y + it.r * 0.85, it.r * 0.95, it.r * 0.4, 0, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(58,74,62,.10)"; ctx.fill();
        ctx.beginPath(); ctx.arc(it.x, it.y, it.r, 0, Math.PI * 2);
        ctx.fillStyle = "#93B17E"; ctx.fill();
        ctx.beginPath(); ctx.arc(it.x - it.r * 0.28, it.y - it.r * 0.3, it.r * 0.6, 0, Math.PI * 2);
        ctx.fillStyle = "#A5C18E"; ctx.fill();
      }
    }
    /* 选中建筑轮廓 */
    if (BYID[SEL]) {
      var sb = BYID[SEL], sfp = polygonOf(SEL);
      if (sfp) {
        var outline = projPts(sfp, BASE_H + (sb.h || 9) + 0.3);
        ctx.save(); ctx.shadowColor = "rgba(78,144,130,.55)"; ctx.shadowBlur = 14;
        polyPath(outline); ctx.strokeStyle = "#3E7E70"; ctx.lineWidth = 2.4; ctx.stroke(); ctx.restore();
      }
    }
  }

'''
s = s[:start] + new_objects + s[end:]
print("OK drawObjects")

# ---------------------------------------------------------------- 5. shadows + 道路图 + 导航渲染
start = s.index("  /* ---------------- shadows + route ---------------- */")
end = s.index("  /* ---------------- labels ---------------- */")
new_route = '''  /* ---------------- shadows + 道路图导航 ---------------- */
  function drawShadows() {
    var i, j;
    for (i = 0; i < BLD.length; i++) {
      var fp = polygonOf(BLD[i].id); if (!fp) continue;
      var pts = [];
      for (j = 0; j < fp.length; j++) pts.push(proj(fp[j][0] + 2.5, fp[j][1] + 3.5, 0.04));
      fillPoly(pts, "rgba(52,70,58,.09)");
    }
  }

  /* 用参考站的道路中心线建图：节点 = 道路顶点/投影点，边 = 沿线距离 */
  var GRAPH = null;
  function buildGraph() {
    var nodes = {};
    function key(x, y) { return (Math.round(x * 2) / 2) + "," + (Math.round(y * 2) / 2); }
    function addNode(x, y) {
      var k = key(x, y);
      if (!nodes[k]) nodes[k] = { x: parseFloat(k.split(",")[0]), y: parseFloat(k.split(",")[1]), adj: [] };
      return nodes[k];
    }
    function addEdge(aId, bId, w, road) {
      if (!aId || !bId || aId === bId) return;
      var a = nodes[aId], b = nodes[bId];
      a.adj.push({ to: bId, w: Math.max(0.1, w), road: road });
      b.adj.push({ to: aId, w: Math.max(0.1, w), road: road });
    }
    var roads = GROUPS.road || [];
    for (var ri = 0; ri < roads.length; ri++) {
      var r = roads[ri], ids = [];
      for (var pi = 0; pi < r.p.length; pi++) {
        var nd = addNode(r.p[pi][0], r.p[pi][1]);
        ids.push(key(r.p[pi][0], r.p[pi][1]));
      }
      for (var si = 1; si < ids.length; si++) {
        var a0 = nodes[ids[si - 1]], b0 = nodes[ids[si]];
        addEdge(ids[si - 1], ids[si], Math.hypot(a0.x - b0.x, a0.y - b0.y), r.id);
      }
    }
    /* 顶点投影到其它道路段，补上路口连接 */
    var all = Object.keys(nodes);
    for (var ai = 0; ai < all.length; ai++) {
      var n = nodes[all[ai]];
      for (var rj = 0; rj < roads.length; rj++) {
        var rr = roads[rj];
        for (var sj = 1; sj < rr.p.length; sj++) {
          var pa = rr.p[sj - 1], pb = rr.p[sj];
          var dx = pb[0] - pa[0], dy = pb[1] - pa[1], L2 = dx * dx + dy * dy;
          if (L2 < 1) continue;
          var t = ((n.x - pa[0]) * dx + (n.y - pa[1]) * dy) / L2;
          if (t < 0.02 || t > 0.98) continue;
          var px = pa[0] + t * dx, py = pa[1] + t * dy;
          var d = Math.hypot(n.x - px, n.y - py);
          if (d > 8.5 || d < 0.05) continue;
          var pk = key(px, py); addNode(px, py);
          addEdge(all[ai], pk, d, rr.id);
          var ak = key(pa[0], pa[1]), bk = key(pb[0], pb[1]);
          if (nodes[ak]) addEdge(pk, ak, Math.hypot(px - pa[0], py - pa[1]), rr.id);
          if (nodes[bk]) addEdge(pk, bk, Math.hypot(px - pb[0], py - pb[1]), rr.id);
        }
      }
    }
    GRAPH = { nodes: nodes, key: key, addNode: addNode, addEdge: addEdge };
  }
  function snapRoad(x, y) {
    /* 找最近的道路段上的点（用于起点/楼栋入口） */
    var roads = GROUPS.road || [], best = null, bd = 1e9;
    for (var ri = 0; ri < roads.length; ri++) {
      var r = roads[ri];
      for (var si = 1; si < r.p.length; si++) {
        var a = r.p[si - 1], b = r.p[si];
        var dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
        if (L2 < 1) continue;
        var t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / L2));
        var px = a[0] + t * dx, py = a[1] + t * dy;
        var d = Math.hypot(x - px, y - py);
        if (d < bd) { bd = d; best = { x: px, y: py, d: d, road: r.id, a: a, b: b }; }
      }
    }
    return best;
  }
  function connectSnap(sn) {
    if (!GRAPH) buildGraph();
    var k = GRAPH.key(sn.x, sn.y);
    var n = GRAPH.addNode(sn.x, sn.y);
    var ak = GRAPH.key(sn.a[0], sn.a[1]), bk = GRAPH.key(sn.b[0], sn.b[1]);
    if (GRAPH.nodes[ak]) GRAPH.addEdge(k, ak, Math.hypot(sn.x - sn.a[0], sn.y - sn.a[1]), sn.road);
    if (GRAPH.nodes[bk]) GRAPH.addEdge(k, bk, Math.hypot(sn.x - sn.b[0], sn.y - sn.b[1]), sn.road);
    return k;
  }
  function dijkstra(start, end) {
    var nodes = GRAPH.nodes, dist = {}, prev = {}, done = {}, ids = Object.keys(nodes);
    for (var i = 0; i < ids.length; i++) dist[ids[i]] = 1e15;
    dist[start] = 0;
    for (var it = 0; it < ids.length; it++) {
      var u = null, best = 1e15;
      for (var j = 0; j < ids.length; j++) {
        var id = ids[j];
        if (!done[id] && dist[id] < best) { best = dist[id]; u = id; }
      }
      if (!u) break;
      if (u === end) break;
      done[u] = 1;
      var adj = nodes[u].adj;
      for (var k = 0; k < adj.length; k++) {
        var e = adj[k];
        var nd = dist[u] + e.w;
        if (nd < dist[e.to]) { dist[e.to] = nd; prev[e.to] = { id: u, road: e.road }; }
      }
    }
    if (dist[end] >= 1e15) return null;
    var path = [end], roads = [], cur = end;
    while (cur !== start && prev[cur]) {
      roads.push(prev[cur].road);
      cur = prev[cur].id;
      path.push(cur);
    }
    path.reverse(); roads.reverse();
    return { path: path, roads: roads, len: dist[end] };
  }
  var ROUTE = null;
  function computeRoute(b) {
    if (!GRAPH) buildGraph();
    var o = null;
    for (var i = 0; i < ORIGINS.length; i++) if (ORIGINS[i].id === ORIGIN) o = ORIGINS[i];
    if (!o || !b) return null;
    var so = snapRoad(o.xy[0], o.xy[1]);
    var sb = snapRoad(b.x, b.y);
    if (!so || !sb) return null;
    var sid = connectSnap(so), tid = connectSnap(sb);
    var g = dijkstra(sid, tid);
    if (!g) return null;
    var pts = [];
    for (var j = 0; j < g.path.length; j++) pts.push([GRAPH.nodes[g.path[j]].x, GRAPH.nodes[g.path[j]].y]);
    var names = [], seen = "";
    for (var k = 0; k < g.roads.length; k++) {
      var nm = ROAD_NAME[g.roads[k]] || "";
      if (nm && nm !== seen) { names.push(nm); seen = nm; }
    }
    /* 入口 → 楼栋的最后一小段（步道） */
    var conn = Math.hypot(b.x - sb.x, b.y - sb.y);
    var total = (g.len + conn) * 0.9;
    return { pts: pts, m: total, mins: Math.max(1, Math.round(total / 78)),
             names: names, originName: o.name, from: o.xy, to: [b.x, b.y] };
  }
  function refreshRoute() {
    var b = BYID[SEL];
    ROUTE = b ? computeRoute(b) : null;
    var dEl = document.getElementById("routeDist");
    var pEl = document.getElementById("routePath");
    if (dEl) dEl.textContent = ROUTE ? ("≈ " + ROUTE.mins + " 分钟 · " + Math.round(ROUTE.m) + " m") : "—";
    if (pEl) {
      if (!ROUTE) { pEl.textContent = "暂无路线"; }
      else {
        var seq = [ROUTE.originName].concat(ROUTE.names);
        var target = (BYID[SEL].ln || BYID[SEL].n || "");
        if (seq[seq.length - 1] !== target) seq.push(target);
        pEl.textContent = seq.join(" → ");
      }
    }
    var chips = document.querySelectorAll("#routeOrigins button");
    for (var i = 0; i < chips.length; i++) chips[i].classList.toggle("on", chips[i].getAttribute("data-origin") === ORIGIN);
  }
  function drawRoute() {
    if (!ROUTE || !ROUTE.pts.length) return;
    var pp = ROUTE.pts.map(function (q) { return proj(q[0], q[1], 0.72); });
    ctx.save();
    ctx.setLineDash([6, 6]); ctx.strokeStyle = "rgba(78,144,130,.88)"; ctx.lineWidth = 2.2; ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.beginPath(); ctx.moveTo(pp[0][0], pp[0][1]);
    for (var j = 1; j < pp.length; j++) ctx.lineTo(pp[j][0], pp[j][1]);
    ctx.stroke(); ctx.setLineDash([]);
    var end = proj(ROUTE.to[0], ROUTE.to[1], 0.72);
    var last = pp[pp.length - 1];
    ctx.beginPath(); ctx.setLineDash([3, 4]); ctx.lineWidth = 1.4;
    ctx.moveTo(last[0], last[1]); ctx.lineTo(end[0], end[1]); ctx.stroke(); ctx.setLineDash([]);
    ctx.beginPath(); ctx.arc(pp[0][0], pp[0][1], 3.6, 0, Math.PI * 2); ctx.fillStyle = "#4E9082"; ctx.fill();
    ctx.beginPath(); ctx.arc(end[0], end[1], 3.4, 0, Math.PI * 2); ctx.fillStyle = "#fff";
    ctx.strokeStyle = "#4E9082"; ctx.lineWidth = 1.8; ctx.fill(); ctx.stroke();
    ctx.restore();
    /* 路线文字（手机交给卡片） */
    if (W >= 820) {
      var mid = pp[Math.floor(pp.length / 2)];
      var txt = ROUTE.originName + " → " + (BYID[SEL].n || BYID[SEL].ln) + " · 约 " + ROUTE.mins + " 分钟";
      ctx.font = '700 11px "Microsoft YaHei", "PingFang SC", sans-serif';
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.lineWidth = 4; ctx.strokeStyle = "rgba(250,250,242,.94)"; ctx.strokeText(txt, mid[0], mid[1] - 8);
      ctx.fillStyle = "#3E7E70"; ctx.fillText(txt, mid[0], mid[1] - 8);
    }
  }
  function roadPoint(roadId, f) {
    var roads = GROUPS.road || [];
    for (var i = 0; i < roads.length; i++) {
      if (roads[i].id !== roadId) continue;
      var p = roads[i].p, total = 0, lens = [];
      for (var j = 1; j < p.length; j++) { var L = Math.hypot(p[j][0] - p[j - 1][0], p[j][1] - p[j - 1][1]); lens.push(L); total += L; }
      var want = total * f, acc = 0;
      for (var k = 1; k < p.length; k++) {
        if (acc + lens[k - 1] >= want) {
          var t = (want - acc) / (lens[k - 1] || 1);
          return { x: p[k - 1][0] + (p[k][0] - p[k - 1][0]) * t, y: p[k - 1][1] + (p[k][1] - p[k - 1][1]) * t,
                   dx: p[k][0] - p[k - 1][0], dy: p[k][1] - p[k - 1][1] };
        }
        acc += lens[k - 1];
      }
      return { x: p[0][0], y: p[0][1], dx: 1, dy: 0 };
    }
    return null;
  }
  function drawRoadLabels() {
    if (W < 820) return;
    for (var i = 0; i < ROAD_LABELS.length; i++) {
      var rl = ROAD_LABELS[i], nm = ROAD_NAME[rl.id];
      if (!nm) continue;
      var sm = roadPoint(rl.id, rl.f); if (!sm) continue;
      var a = proj(sm.x, sm.y, 0.8);
      var bpt = proj(sm.x + sm.dx * 4, sm.y + sm.dy * 4, 0.8);
      var ang = Math.atan2(bpt[1] - a[1], bpt[0] - a[0]);
      if (ang > Math.PI / 2) ang -= Math.PI;
      if (ang < -Math.PI / 2) ang += Math.PI;
      ctx.save();
      ctx.translate(a[0], a[1]); ctx.rotate(ang);
      ctx.font = '700 10px "Microsoft YaHei", "PingFang SC", sans-serif';
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.lineWidth = 3.5; ctx.strokeStyle = "rgba(250,250,242,.92)"; ctx.strokeText(nm, 0, 0);
      ctx.fillStyle = "#9AA7A4"; ctx.fillText(nm, 0, 0);
      ctx.restore();
    }
  }
  function drawPOIs() {
    var pois = [];
    var gates = [
      { n: "南门", x: 326, y: 459, t: "gate" },
      { n: "东侧门", x: 692, y: 399, t: "gate" }
    ];
    for (var g = 0; g < gates.length; g++) pois.push(gates[g]);
    if ((GROUPS.plaza || [])[0]) { var c1 = centerOf(GROUPS.plaza[0].p); pois.push({ n: "董奉广场", x: c1[0], y: c1[1], t: "plaza" }); }
    if ((GROUPS.plaza || [])[1]) { var c2 = centerOf(GROUPS.plaza[1].p); pois.push({ n: "棋盘广场", x: c2[0], y: c2[1], t: "plaza" }); }
    if ((GROUPS.track || [])[0]) { var c3 = centerOf(GROUPS.track[0].p); pois.push({ n: "田径场", x: c3[0], y: c3[1], t: "sport" }); }
    if ((GROUPS.court || [])[0]) { var c4 = centerOf(GROUPS.court[0].p); pois.push({ n: "篮球场", x: c4[0], y: c4[1], t: "sport" }); }
    pois.push({ n: "时珍园", x: 632, y: 148, t: "park" });
    var narrow = W < 820;
    for (var i = 0; i < pois.length; i++) {
      var po = pois[i];
      if (narrow && po.t !== "gate") continue;
      if (po.x < 0 || po.x > CW || po.y < 0 || po.y > CH) continue;
      var p = proj(po.x, po.y, 0.9);
      var col = po.t === "gate" ? "#4E9082" : (po.t === "plaza" ? "#B98F63" : (po.t === "park" ? "#5F8F5B" : "#6E8CA8"));
      ctx.beginPath(); ctx.arc(p[0], p[1], po.t === "gate" ? 3.4 : 2.6, 0, Math.PI * 2);
      ctx.fillStyle = col; ctx.fill();
      if (po.t === "gate") { ctx.beginPath(); ctx.arc(p[0], p[1], 6.2, 0, Math.PI * 2); ctx.strokeStyle = "rgba(78,144,130,.45)"; ctx.lineWidth = 1.2; ctx.stroke(); }
      ctx.font = '700 ' + (po.t === "gate" ? 10.5 : 9.5) + 'px "Microsoft YaHei", sans-serif';
      ctx.textAlign = "left"; ctx.textBaseline = "middle";
      ctx.lineWidth = 3.2; ctx.strokeStyle = "rgba(250,250,242,.92)";
      ctx.strokeText(po.n, p[0] + 7, p[1] - 1);
      ctx.fillStyle = col; ctx.fillText(po.n, p[0] + 7, p[1] - 1);
    }
  }

'''
s = s[:start] + new_route + s[end:]
print("OK route/graph")

# ---------------------------------------------------------------- 6. render 顺序
rep('''    drawGround();
    drawFlat();
    drawShadows();
    drawRoute();
    drawObjects();
    drawLabels();''',
    '''    drawGround();
    drawFlat();
    drawShadows();
    drawRoute();
    drawObjects();
    drawRoadLabels();
    drawPOIs();
    drawLabels();''', "render-order")

# ---------------------------------------------------------------- 7. 拾取与标签高度
rep('''      var top = projPts(fp, b.h || 9);''',
    '''      var top = projPts(fp, BASE_H + (b.h || 9));''', "pick-z")
rep('var p = proj(b.x, b.y, (b.h || 9) + 2.2);',
    'var p = proj(b.x, b.y, BASE_H + (b.h || 9) + 2.2);', "label-z")
rep('var p = proj(b.x, b.y, h + (W < 820 ? 20 : 9));',
    'var p = proj(b.x, b.y, BASE_H + h + (W < 820 ? 20 : 9));', "badge-z")

# ---------------------------------------------------------------- 8. 区域标签去重（南门/广场/时珍园改由 POI 标注）
rep('''      : [["宋慈湖", 400, 250, 11], ["宋慈湖", 545, 160, 10], ["学生公寓区", 175, 150, 10.5],
         ["田径场", 468, 42, 10], ["董奉广场", 420, 392, 9.5], ["南门 · 主入口", 326, 474, 9.5],
         ["名师苑", 700, 150, 9.5], ["时珍园", 690, 330, 9.5]];''',
    '''      : [["宋慈湖", 400, 250, 11], ["宋慈湖", 545, 160, 10], ["学生公寓区", 175, 150, 10.5],
         ["田径场", 455, 52, 10], ["名师苑", 700, 150, 9.5]];''', "area-labels")
rep('''      ? [["宋慈湖", 400, 250, 10.5], ["学生公寓区", 175, 150, 10], ["田径场", 468, 42, 10], ["南门 · 主入口", 326, 474, 9.5]]''',
    '''      ? [["宋慈湖", 400, 250, 10.5], ["学生公寓区", 175, 150, 10], ["田径场", 455, 52, 10]]''', "area-labels-mobile")

# ---------------------------------------------------------------- 9. 卡片：路线导航区
rep('''    <div class="btns">
      <button class="pri" id="btnFloor" type="button">进入楼层视图</button>
      <button id="btnTt" type="button">去课表</button>
    </div>''',
    '''    <div class="routebox">
      <div class="rhd"><span>道路导航</span><b id="routeDist">—</b></div>
      <div class="rchips" id="routeOrigins"></div>
      <div class="rpath" id="routePath">—</div>
    </div>
    <div class="btns">
      <button class="pri" id="btnFloor" type="button">进入楼层视图</button>
      <button id="btnTt" type="button">去课表</button>
    </div>''', "routebox-html")

rep('''  .btns{display:flex;gap:8px;margin-top:13px}''',
    '''  .routebox{margin-top:12px;border-top:1px dashed #E6EAE3;padding-top:10px}
  .routebox .rhd{display:flex;align-items:center;justify-content:space-between;margin-bottom:7px}
  .routebox .rhd span{font-size:9.5px;font-weight:800;letter-spacing:.12em;color:#B98F63}
  .routebox .rhd b{font-size:11px;color:#2E6B5E;font-weight:800;font-variant-numeric:tabular-nums}
  .rchips{display:flex;gap:5px;margin-bottom:7px}
  .rchips button{border:1px solid #E4E9E2;background:#FBFCFB;border-radius:7px;padding:3px 8px;
    font:inherit;font-size:10.5px;font-weight:700;color:#5A6A67;cursor:pointer}
  .rchips button.on{background:#4E9082;border-color:#4E9082;color:#fff}
  .rpath{font-size:11px;line-height:1.55;color:#5A6A67;word-break:break-all}
  .btns{display:flex;gap:8px;margin-top:13px}''', "routebox-css")

# ---------------------------------------------------------------- 10. updateCard 末尾刷新路线
rep('''    var fb = document.getElementById("btnFloor");
    fb.disabled = !room;''',
    '''    refreshRoute();
    var fb = document.getElementById("btnFloor");
    fb.disabled = !room;''', "updateCard-route")

# ---------------------------------------------------------------- 11. 初始化起点 chips
rep('''  /* ---------------- legend ---------------- */''',
    '''  /* ---------------- 起点 chips ---------------- */
  (function () {
    var box = document.getElementById("routeOrigins");
    if (!box) return;
    for (var i = 0; i < ORIGINS.length; i++) {
      (function (o) {
        var btn = document.createElement("button");
        btn.type = "button"; btn.textContent = o.name;
        btn.setAttribute("data-origin", o.id);
        if (o.id === ORIGIN) btn.className = "on";
        btn.addEventListener("click", function () {
          ORIGIN = o.id;
          refreshRoute();
          scheduleRender();
        });
        box.appendChild(btn);
      })(ORIGINS[i]);
    }
  })();

  /* ---------------- legend ---------------- */''', "origin-chips")

# ---------------------------------------------------------------- 12. 关于弹层补充
rep('''      <p><span class="tag">未接入</span>身份门禁、真实课表、楼层平面排列、云端同步。左侧「下一节」为示例数据。</p>''',
    '''      <p><span class="tag">贴地与高度</span>所有体块落在统一基座上，建筑脚下有裙边与接触阴影；高度仍为建模假设。</p>
      <p><span class="tag">道路导航</span>按参考站道路中心线计算最短路；道路名依据公开地图截图整理（近似）。它不是真实导航，只用于「从校门/宿舍到某栋楼大概怎么走」。</p>
      <p><span class="tag">未接入</span>身份门禁、真实课表、楼层平面排列、云端同步。左侧「下一节」为示例数据。</p>''', "about")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched bytes", len(s.encode("utf-8")))
