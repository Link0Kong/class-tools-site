# -*- coding: utf-8 -*-
"""按手绘地图（河洛易班版）更新：楼栋号标注、名称、POI、桥/门/亭等地标、屋顶配色。"""
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


# 1. 屋顶配色向手绘图靠拢（暖砖红 + 白墙）
rep('''    "教学楼": { wall: "#F1E8D6", roof: "#D8E8DE", ink: "#2E6B5E" },
    "图书馆": { wall: "#EEE5D3", roof: "#D3E2F1", ink: "#4E6B87" },
    "科研":   { wall: "#EFE8DE", roof: "#E2DCEC", ink: "#6A5F82" },
    "宿舍":   { wall: "#F2E5D0", roof: "#EBD9BF", ink: "#7C6A52" },
    "运动":   { wall: "#EDE7DA", roof: "#DAE3F1", ink: "#5D7389" },
    "食堂":   { wall: "#F1E6D3", roof: "#EAD9BF", ink: "#7C6A52" },
    "培训":   { wall: "#F0E7D6", roof: "#E8DCC6", ink: "#8A7358" },
    "生活":   { wall: "#EFE8DC", roof: "#E3DACA", ink: "#7C6A52" },
    "住宅":   { wall: "#EFE9E0", roof: "#E2DCEC", ink: "#6A5F82" },
    "其他":   { wall: "#EEE9DE", roof: "#DFDCD1", ink: "#6E7C78" }''',
    '''    "教学楼": { wall: "#F8F2E7", roof: "#C88D76", ink: "#7A4A3B" },
    "图书馆": { wall: "#F8F3E9", roof: "#B97C66", ink: "#7A4A3B" },
    "科研":   { wall: "#F7F1E8", roof: "#BF8470", ink: "#7A4A3B" },
    "宿舍":   { wall: "#F8F1E4", roof: "#C98A6E", ink: "#7A4A3B" },
    "运动":   { wall: "#F4EFE6", roof: "#A6C2AB", ink: "#5D7389" },
    "食堂":   { wall: "#F7EFE2", roof: "#D09A7E", ink: "#7A4A3B" },
    "培训":   { wall: "#F7F0E5", roof: "#C68D77", ink: "#7A4A3B" },
    "生活":   { wall: "#F6EFE4", roof: "#D2AE8E", ink: "#7A4A3B" },
    "住宅":   { wall: "#F5F0E8", roof: "#B9A98F", ink: "#6A5F82" },
    "其他":   { wall: "#F4F0E6", roof: "#C9B9A4", ink: "#6E7C78" }''', "palette")

# 2. 标签：楼栋号 sub 通用化
rep('''    for (var j = 0; j < cand.length; j++) {
      var c = cand[j], bb = c.b;
      var sub = (bb.id === "B40") ? "01 号楼" : (bb.id === "B20" ? "02 号楼" : null);
      var txt = (bb.id === "B24") ? "康复研究院" : (bb.id === "B04" ? "活动中心" : (bb.n || bb.ln));
      label(txt, c.p[0], c.p[1], bb.id === "B40" || bb.id === "B20" ? 12.5 : 11.5,
        bb.id === SEL ? "#2E6B5E" : "#4A5A55", sub);
    }''',
    '''    for (var j = 0; j < cand.length; j++) {
      var c = cand[j], bb = c.b;
      var sub = bb.no ? (bb.no + " 号楼") : null;
      var txt = (bb.id === "B04") ? "活动中心" : (bb.n || bb.ln);
      label(txt, c.p[0], c.p[1], bb.no ? 12.5 : 11.5,
        bb.id === SEL ? "#7A4A3B" : "#4A5A55", sub);
    }''', "labels-no")

# 3. 区域标签：宿舍区带 11–23 号楼
rep('["学生公寓区", 175, 150, 10.5]', '["学生公寓区（11–23号楼）", 190, 210, 10.5]', "dorm-label")
rep('["学生公寓区", 175, 150, 10]', '["学生公寓区（11–23号楼）", 190, 210, 10]', "dorm-label-m")

# 4. 气泡/卡片名称用楼栋号
rep('''    var text = (b.ln || b.n) + (D.rooms[b.id] ? " · " + D.rooms[b.id].no + " 号楼" : "");''',
    '''    var text = (b.ln || b.n) + (b.no ? " · " + b.no + " 号楼" : "");''', "badge-no")
rep('''    elName.textContent = (b.ln || b.n) + (room ? " · " + room.no + " 号楼" : "");''',
    '''    elName.textContent = (b.ln || b.n) + (b.no ? " · " + b.no + " 号楼" : "");''', "card-no")

# 5. POI：按手绘图补 保卫处 / 健身房 / 校训广场 / 时令广场；校门改名
rep('''    var gates = [
      { n: "南门", x: 326, y: 459, t: "gate" },
      { n: "东侧门", x: 692, y: 399, t: "gate" }
    ];
    for (var g = 0; g < gates.length; g++) pois.push(gates[g]);''',
    '''    var gates = [
      { n: "正大门（东南门）", x: 326, y: 459, t: "gate" },
      { n: "东侧门", x: 692, y: 399, t: "gate" }
    ];
    for (var g = 0; g < gates.length; g++) pois.push(gates[g]);
    pois.push({ n: "保卫处", x: 470, y: 128, t: "life" });
    pois.push({ n: "健身房", x: 330, y: 176, t: "sport" });
    pois.push({ n: "校训广场", x: 470, y: 346, t: "plaza" });
    pois.push({ n: "时令广场", x: 520, y: 300, t: "plaza" });''', "pois")

# 6. 地标：桥 / 校门 / 大医亭（在对象之后绘制）
rep('''  function drawRoadLabels() {''',
    '''  /* ---------------- 地标：桥 / 校门 / 大医亭 ---------------- */
  var BRIDGES = null;
  function findBridges() {
    if (BRIDGES) return BRIDGES;
    var out = [], roads = GROUPS.road || [], waters = GROUPS.water || [], i, j, k, t;
    for (i = 0; i < roads.length; i++) {
      var rp = roads[i].p;
      for (j = 1; j < rp.length; j++) {
        var a = rp[j - 1], b = rp[j];
        var mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
        var inW = false;
        for (k = 0; k < waters.length; k++) if (inPoly(mx, my, waters[k].p)) inW = true;
        if (!inW) continue;
        var dup = false;
        for (k = 0; k < out.length; k++) if (Math.hypot(out[k].x - mx, out[k].y - my) < 12) dup = true;
        if (!dup) out.push({ x: mx, y: my, dx: b[0] - a[0], dy: b[1] - a[1] });
      }
    }
    out.sort(function (p, q) { return p.x - q.x; });
    var names = ["苏颂桥", "土羕桥", "保生桥"];
    for (i = 0; i < out.length && i < 3; i++) out[i].n = names[i];
    BRIDGES = out;
    return out;
  }
  function drawLandmarks() {
    var i;
    /* 桥：石板桥面 + 栏杆 */
    var bs = findBridges();
    for (i = 0; i < bs.length; i++) {
      var b = bs[i], pp = proj(b.x, b.y, 0.9), p2 = proj(b.x + b.dx * 3, b.y + b.dy * 3, 0.9);
      var ang = Math.atan2(p2[1] - pp[1], p2[0] - pp[0]);
      var scale = Math.max(0.7, Math.min(1.6, scaleNow() / 1.1));
      ctx.save(); ctx.translate(pp[0], pp[1]); ctx.rotate(ang);
      ctx.fillStyle = "#D9CDB4"; ctx.strokeStyle = "rgba(120,104,80,.5)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.rect(-13 * scale, -4.5 * scale, 26 * scale, 9 * scale); ctx.fill(); ctx.stroke();
      ctx.strokeStyle = "rgba(110,96,74,.75)"; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.moveTo(-13 * scale, -4.5 * scale); ctx.lineTo(13 * scale, -4.5 * scale); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(-13 * scale, 4.5 * scale); ctx.lineTo(13 * scale, 4.5 * scale); ctx.stroke();
      ctx.restore();
      if (b.n) {
        ctx.font = '700 9.5px "Microsoft YaHei", sans-serif';
        ctx.textAlign = "center"; ctx.textBaseline = "bottom";
        ctx.lineWidth = 3; ctx.strokeStyle = "rgba(250,250,242,.92)";
        ctx.strokeText(b.n, pp[0], pp[1] - 7 * scale);
        ctx.fillStyle = "#8A7358"; ctx.fillText(b.n, pp[0], pp[1] - 7 * scale);
      }
    }
    /* 校门：两根门柱 + 横梁（显示尺寸随缩放微调） */
    function gate(x, y, name) {
      var p = proj(x, y, 0), sc = Math.max(0.8, Math.min(1.5, scaleNow() / 1.2));
      var w = 9 * sc, hgt = 12 * sc;
      ctx.fillStyle = "#B98F63"; ctx.strokeStyle = "rgba(90,70,45,.5)"; ctx.lineWidth = 1;
      ctx.fillRect(p[0] - w - 2, p[1] - hgt, 4, hgt);
      ctx.fillRect(p[0] + w - 2, p[1] - hgt, 4, hgt);
      ctx.strokeRect(p[0] - w - 2, p[1] - hgt, 4, hgt);
      ctx.strokeRect(p[0] + w - 2, p[1] - hgt, 4, hgt);
      ctx.fillStyle = "#C9A87C";
      ctx.fillRect(p[0] - w - 4, p[1] - hgt - 3, 2 * w + 8, 4);
      ctx.font = '700 9.5px "Microsoft YaHei", sans-serif';
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.lineWidth = 3; ctx.strokeStyle = "rgba(250,250,242,.92)";
      ctx.strokeText(name, p[0], p[1] + 4);
      ctx.fillStyle = "#8A7358"; ctx.fillText(name, p[0], p[1] + 4);
    }
    gate(326, 459, "正大门（东南门）");
    gate(692, 399, "东侧门");
    /* 大医亭：双层小亭（示意） */
    (function pavilion() {
      var p = proj(650, 118, 0), sc = Math.max(0.9, Math.min(2, scaleNow() / 1.1));
      ctx.save(); ctx.translate(p[0], p[1]);
      ctx.fillStyle = "#8F5B4A";
      ctx.beginPath(); ctx.moveTo(-11 * sc, 0); ctx.lineTo(-7 * sc, -10 * sc); ctx.lineTo(7 * sc, -10 * sc); ctx.lineTo(11 * sc, 0); ctx.closePath(); ctx.fill();
      ctx.fillStyle = "#6E4438";
      ctx.beginPath(); ctx.moveTo(-13 * sc, -9 * sc); ctx.lineTo(-4 * sc, -20 * sc); ctx.lineTo(4 * sc, -20 * sc); ctx.lineTo(13 * sc, -9 * sc); ctx.closePath(); ctx.fill();
      ctx.fillStyle = "#C9A87C";
      ctx.fillRect(-8 * sc, 0, 16 * sc, 3 * sc);
      ctx.restore();
      ctx.font = '700 10px "Microsoft YaHei", sans-serif';
      ctx.textAlign = "center"; ctx.textBaseline = "bottom";
      ctx.lineWidth = 3; ctx.strokeStyle = "rgba(250,250,242,.92)";
      ctx.strokeText("大医亭", p[0], p[1] - 22 * sc);
      ctx.fillStyle = "#7A4A3B"; ctx.fillText("大医亭", p[0], p[1] - 22 * sc);
    })();
  }
  function drawRoadLabels() {''', "landmarks")

# 7. render 调用地标
rep('''    drawObjects();
    drawRoadLabels();''',
    '''    drawObjects();
    drawLandmarks();
    drawRoadLabels();''', "render-landmarks")

# 8. About 说明补充
rep('''      <p><span class="tag">数据来源</span>建筑轮廓与高度：<b>「旗山校园 · 三维空间研究」</b>重建数据（已获授权使用）；校园总平面图：由班级提供。教室号与课表联动数据结构来自班级课表。</p>''',
    '''      <p><span class="tag">数据来源</span>建筑轮廓与高度：<b>「旗山校园 · 三维空间研究」</b>重建数据（已获授权使用）；地名与楼栋号：参照 <b>「福中医（旗山校区）地图」（河洛易班）</b> 校对；校园总平面图：由班级提供。</p>''', "about-source")
rep('''      <p><span class="tag">贴地与高度</span>所有体块落在统一基座上，建筑脚下有裙边与接触阴影；高度仍为建模假设。</p>''',
    '''      <p><span class="tag">贴地与高度</span>所有体块落在统一基座上，建筑脚下有裙边与接触阴影；高度仍为建模假设。</p>
      <p><span class="tag">标注说明</span>1–8 号楼 / 33 号楼按手绘图改为「名称 + 楼栋号」；宿舍楼目前只标了 23 号楼（a/b 区）与 22 号楼，其余按「学生公寓区（11–23 号楼）」归组，等你确认后再逐个编号。</p>''', "about-labels")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched", len(s.encode("utf-8")))
