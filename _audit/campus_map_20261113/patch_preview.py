# -*- coding: utf-8 -*-
"""对 preview_template.html 做视觉/交互修正。"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(HERE, "preview_template.html")
s = io.open(p, encoding="utf-8").read()


def rep(a, b, label):
    global s
    if a in s:
        s = s.replace(a, b, 1)
        print("OK", label)
    else:
        print("MISS", label)


# 1. 默认视角更斜一点
rep('var CAM = { yaw: -0.55, pitch: 0.86, zoom: 1, px: 0, py: 0 };',
    'var CAM = { yaw: -0.55, pitch: 0.72, zoom: 1, px: 0, py: 0 };', "cam")
rep('return { yaw: -0.55, pitch: 0.86, zoom: 1, px: 0, py: 0 };',
    'return { yaw: -0.55, pitch: 0.72, zoom: 1, px: 0, py: 0 };', "modeiso")
rep('{ yaw: -0.55, pitch: 0.86, name: "南向" },',
    '{ yaw: -0.55, pitch: 0.72, name: "南向" },', "viewpreset")

# 2. fit 之后桌面放大一点
rep('''    BASE.s = s;
    BASE.ox = W / 2 - (minX + maxX) / 2 * s;''',
    '''    s *= (W > 820 ? 1.12 : 1.0);
    BASE.s = s;
    BASE.ox = W / 2 - (minX + maxX) / 2 * s;''', "fitzoom")

# 3. 手机：放大聚焦教学区（resize 内）
rep('''    fit();
    render(); drawMini();''',
    '''    fit();
    if (W < 820) {
      CAM.zoom = 1.62;
      var pv = panFor(BYID[SEL] || BLD[0], CAM.zoom);
      CAM.px = pv[0]; CAM.py = pv[1];
    }
    render(); drawMini();''', "mobilezoom")

# 4. panFor 助手（放在 focusBuilding 前）
rep('''  function focusBuilding(id) {''',
    '''  function panFor(b, zoom) {
    var cy = Math.cos(CAM.yaw), syw = Math.sin(CAM.yaw);
    var dx = b.x - CX, dy = b.y - CY;
    var X = dx * cy - dy * syw, Y = dx * syw + dy * cy;
    var s = BASE.s * zoom;
    var tx = W / 2, ty = H * (W > 820 ? 0.45 : 0.33);
    return [tx - (BASE.ox + X * s), ty - (BASE.oy + (Y * sinp() - (b.h || 9) * cosp()) * s)];
  }
  function focusBuilding(id) {''', "panfor")

# 5. focusBuilding 用 panFor
rep('''  function focusBuilding(id) {
    var b = BYID[id]; if (!b) return;
    var zoom = Math.max(1.45, CAM.zoom);
    var cy = Math.cos(CAM.yaw), syw = Math.sin(CAM.yaw);
    var dx = b.x - CX, dy = b.y - CY;
    var X = dx * cy - dy * syw, Y = dx * syw + dy * cy;
    var s = 0;
    /* 先按目标 zoom 估一个 s（BASE.s 不变） */
    s = BASE.s * zoom;
    var targetPx = W / 2 - (BASE.ox + X * s);
    var targetPy = (W > 820 ? H * 0.45 : H * 0.34) - (BASE.oy + (Y * sinp() - (b.h || 9) * cosp()) * s);
    flyTo({ yaw: CAM.yaw, pitch: CAM.pitch, zoom: zoom, px: targetPx, py: targetPy }, 520);
  }''',
    '''  function focusBuilding(id) {
    var b = BYID[id]; if (!b) return;
    var zoom = Math.max(1.55, CAM.zoom);
    var pv = panFor(b, zoom);
    flyTo({ yaw: CAM.yaw, pitch: CAM.pitch, zoom: zoom, px: pv[0], py: pv[1] }, 520);
  }''', "focus")

# 6. 建筑高度：课上楼按真实层数修正（参考模型假设层数偏低）
rep('''  var BLD = D.buildings, BYID = {}, FEAT = D.features;
  for (var i = 0; i < BLD.length; i++) BYID[BLD[i].id] = BLD[i];''',
    '''  var BLD = D.buildings, BYID = {}, FEAT = D.features;
  for (var i = 0; i < BLD.length; i++) {
    if (BLD[i].id === "B40" || BLD[i].id === "B20") BLD[i].h = 15.25;
    BYID[BLD[i].id] = BLD[i];
  }''', "heights")

# 7. 树：更少更小
rep('''    for (var gy = 8; gy < CH - 6; gy += 10) {
      for (var gx = 8; gx < CW - 6; gx += 10) {
        if (rnd() < 0.66) continue;''',
    '''    for (var gy = 10; gy < CH - 8; gy += 13) {
      for (var gx = 10; gx < CW - 8; gx += 13) {
        if (rnd() < 0.52) continue;''', "treedens")
rep('TREES.push([x, y, 0.9 + rnd() * 0.9]);', 'TREES.push([x, y, 0.75 + rnd() * 0.6]);', "treesize")

# 8. 建筑明暗对比
rep('var light = (q[1][0] - q[0][0]) >= 0 ? 0.10 : -0.07;',
    'var light = (q[1][0] - q[0][0]) >= 0 ? 0.14 : -0.11;', "light")
rep('stroke: isCtx ? "rgba(90,105,95,.10)" : "rgba(70,86,74,.16)", lw: 0.7 });',
    'stroke: isCtx ? "rgba(90,105,95,.10)" : "rgba(62,78,66,.25)", lw: 0.9 });', "wallstroke")
rep('stroke: isCtx ? "rgba(90,105,95,.18)" : "rgba(52,70,60,.30)", lw: isCtx ? 0.6 : 1.0, top: 1 });',
    'stroke: isCtx ? "rgba(90,105,95,.18)" : "rgba(46,62,52,.36)", lw: isCtx ? 0.6 : 1.1, top: 1 });', "roofstroke")

# 9. 校区范围淡底
rep('''    fillPoly(projPts(g, 0), "#F2F4E7");''',
    '''    fillPoly(projPts(g, 0), "#EFF2E2");
    var bnd = (GROUPS.bnd || [])[0];
    if (bnd) fillPoly(projPts(bnd.p, 0.08), "#F5F7EB", "rgba(150,168,148,.30)", 1.2);''', "boundary")

# 10. 路线长度用折线
rep('''    var dx = to[0] - from[0], dy = to[1] - from[1];
    var meters = Math.sqrt(dx * dx + dy * dy) * 0.9;
    var mins = Math.max(1, Math.round(meters / 78));''',
    '''    var meters = 0;
    for (var ri = 1; ri < pts.length; ri++) meters += Math.hypot(pts[ri][0] - pts[ri - 1][0], pts[ri][1] - pts[ri - 1][1]);
    meters *= 0.9;
    var mins = Math.max(1, Math.round(meters / 78));''', "routelen")

# 11. 手机工具栏：隐藏关于按钮 + 收窄
rep('''    .toolbar{margin-left:auto;padding:4px}
    .toolbar button{font-size:0;padding:8px}''',
    '''    .toolbar{margin-left:auto;padding:4px;gap:2px}
    .toolbar button{font-size:0;padding:7px 6px}
    .toolbar #btnAbout{display:none}''', "mobtoolbar")

# 12. 手机上少画标签、路线文字
rep('''      if (narrow && !(b.id === "B40" || b.id === "B20" || b.id === "B50" || b.id === "B70")) continue;''',
    '''      if (narrow && !(b.id === "B20" || b.id === "B50" || b.id === "B70")) continue;''', "moblabels")
rep('''    ctx.lineWidth = 4; ctx.strokeStyle = "rgba(250,250,242,.94)"; ctx.strokeText(txt, lp[0], lp[1]);
    ctx.fillStyle = "#3E7E70"; ctx.fillText(txt, lp[0], lp[1]);''',
    '''    if (W >= 820) {
      ctx.lineWidth = 4; ctx.strokeStyle = "rgba(250,250,242,.94)"; ctx.strokeText(txt, lp[0], lp[1]);
      ctx.fillStyle = "#3E7E70"; ctx.fillText(txt, lp[0], lp[1]);
    }''', "mobroute")

# 13. 小地图：裁剪视野层 + 简化
rep('''    mctx.beginPath(); mctx.moveTo(wpts[0][0], wpts[0][1]);
    for (i = 1; i < 4; i++) mctx.lineTo(wpts[i][0], wpts[i][1]);
    mctx.closePath();
    mctx.fillStyle = "rgba(78,144,130,.12)"; mctx.fill();
    mctx.strokeStyle = "rgba(78,144,130,.55)"; mctx.lineWidth = 1.6 / s; mctx.stroke();
    mctx.restore();''',
    '''    mctx.beginPath(); mctx.rect(0, 0, CW, CH); mctx.clip();
    mctx.beginPath(); mctx.moveTo(wpts[0][0], wpts[0][1]);
    for (i = 1; i < 4; i++) mctx.lineTo(wpts[i][0], wpts[i][1]);
    mctx.closePath();
    mctx.fillStyle = "rgba(78,144,130,.10)"; mctx.fill();
    mctx.strokeStyle = "rgba(78,144,130,.50)"; mctx.lineWidth = 1.6 / s; mctx.stroke();
    var cp = unprojectGround(W / 2, H / 2);
    mctx.beginPath(); mctx.arc(cp[0], cp[1], 5 / s, 0, Math.PI * 2);
    mctx.fillStyle = "#4E9082"; mctx.fill();
    mctx.restore();''', "minimap")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched bytes", len(s.encode("utf-8")))
