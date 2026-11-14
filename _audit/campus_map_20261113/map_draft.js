/* ============================================================
   校内地图 · 重绘示意数据（draft v0，2026-11-13）
   依据：用户提供的学校规划图（仅作描摹参考，非直接使用原图）
   坐标：相对画布 800 × 465，无经纬度/无比例尺 → 不构成测绘地图
   教室号规则：楼栋号(2位) + 楼层(1位) + 教室编号(2位)
     例：01203 = 01号楼(自强楼) 2层 03教室
         02101 = 02号楼(厚德楼) 1层 01教室
   ============================================================ */
(function (global) {
  var C = {
    vb: [0, 0, 800, 465],
    tone: {
      teach:  { fill: "#E7F2ED", stroke: "#CBE3DA", ink: "#2E6B5E" },
      lib:    { fill: "#EAF1F8", stroke: "#D6E3F0", ink: "#4E6B87" },
      dorm:   { fill: "#F7F0E4", stroke: "#E7D9C4", ink: "#7C6A52" },
      sport:  { fill: "#EDF2F8", stroke: "#DBE5F1", ink: "#5D7389" },
      food:   { fill: "#F4EDE2", stroke: "#E5D6C0", ink: "#7C6A52" },
      res:    { fill: "#F0EDF6", stroke: "#DED8EA", ink: "#6A5F82" },
      sel:    { fill: "#DCEEE7", stroke: "#4E9082", ink: "#2E6B5E" }
    },
    /* 水面：宋慈湖（西 + 北 + 东）、东侧湖、溪源江、小水塘 */
    water: [
      "M 552.4,94.8 L 531.5,99.2 L 480.6,104.8 L 474.3,113.6 L 492.7,131.4 L 507.4,151.2 L 525.5,162.2 L 539.1,167.8 L 556.9,186.2 L 562.5,187.3 L 569.2,192.2 L 579.7,189.2 L 592.7,192.8 L 598.6,190.3 L 603.2,195.0 L 598.3,200.1 L 599.8,211.3 L 596.8,218.1 L 600.0,221.2 L 609.0,214.3 L 613.6,214.3 L 628.4,231.2 L 630.1,230.3 L 634.7,234.9 L 641.8,245.1 L 645.9,249.2 L 648.1,248.8 L 655.7,256.9 L 663.2,268.0 L 661.3,271.5 L 675.7,289.4 L 674.8,293.0 L 680.6,299.2 L 683.7,295.9 L 681.8,291.1 L 688.7,273.9 L 691.8,252.8 L 692.2,234.4 L 666.3,199.6 L 655.2,179.9 L 643.1,167.3 L 631.0,175.7 L 627.5,173.3 L 625.9,174.2 L 621.5,169.8 L 615.0,169.7 L 608.3,163.0 L 608.2,155.9 L 599.3,147.8 L 595.8,151.0 L 597.2,152.5 L 595.7,155.1 L 589.1,161.7 L 585.5,158.8 L 583.4,159.7 L 576.3,150.9 L 576.3,145.1 L 578.2,141.4 L 575.0,138.3 L 562.9,133.7 L 555.3,125.5 L 558.8,109.0 L 565.8,101.2 L 562.0,97.3 Z",
      "M 389.4,137.3 L 376.9,140.3 L 361.6,153.7 L 359.9,152.3 L 340.1,169.2 L 327.9,176.3 L 312.3,190.9 L 297.3,206.9 L 293.7,213.1 L 281.8,224.4 L 268.7,248.6 L 260.8,257.5 L 260.2,263.0 L 255.8,267.5 L 252.7,276.6 L 244.8,284.5 L 247.2,288.4 L 242.3,295.5 L 241.7,303.4 L 238.2,311.7 L 238.8,319.5 L 242.4,323.2 L 251.9,323.3 L 260.7,328.8 L 271.6,327.2 L 276.2,322.5 L 286.8,295.5 L 295.3,279.4 L 325.4,250.8 L 331.0,246.3 L 349.6,238.3 L 357.4,237.3 L 369.0,241.2 L 372.2,238.1 L 370.3,234.0 L 376.2,224.0 L 374.3,221.5 L 386.2,208.5 L 370.8,190.0 L 366.3,178.4 L 365.8,172.1 L 374.8,157.4 L 380.9,151.3 L 394.7,142.6 Z",
      "M 9.9,263.3 L 7.8,265.2 L -0.2,264.0 L -0.2,291.0 L 35.7,336.9 L 38.8,347.2 L 38.2,361.8 L 34.2,387.9 L 21.3,411.5 L 20.3,416.1 L 20.3,421.5 L 23.5,424.7 L 39.6,416.2 L 66.2,389.1 L 65.8,385.5 L 69.2,382.0 L 69.3,378.0 L 71.7,375.5 L 70.8,372.5 L 76.2,363.5 L 74.3,361.5 L 76.7,359.0 L 75.2,356.2 L 76.8,348.7 L 74.8,346.0 L 74.2,334.0 L 60.2,300.0 L 53.3,289.5 L 52.7,284.4 L 41.5,275.8 L 39.0,277.2 L 34.0,272.3 L 30.5,272.7 L 28.0,270.3 L 26.0,270.7 Z",
      "M 738.9,153.3 L 735.5,156.7 L 729.4,158.3 L 721.0,167.2 L 709.6,167.8 L 706.3,170.9 L 708.3,179.5 L 714.4,187.2 L 717.7,188.8 L 730.3,187.2 L 732.9,189.2 L 746.7,180.1 L 746.3,178.5 L 750.2,174.1 L 746.7,164.0 Z",
      "M 718.9,295.3 L 708.1,306.2 L 698.0,308.8 L 694.8,312.0 L 714.0,331.2 L 717.2,328.0 L 718.3,318.0 L 726.2,304.3 L 724.7,300.4 Z",
      "M 729.4,219.8 L 724.8,225.0 L 721.3,240.0 L 724.5,243.2 L 731.0,237.8 L 738.5,247.2 L 746.7,239.1 L 748.7,232.0 L 745.1,228.3 Z"
    ],
    /* 草坪 / 园林 */
    lawn: [
      "M 552,300 C 592,288 634,294 662,316 C 686,336 688,374 664,394 C 636,416 586,412 562,390 " +
      "C 540,370 536,318 552,300 Z",
      "M 622,108 C 654,98 696,102 716,122 C 734,140 734,174 718,192 C 700,212 660,214 636,196 " +
      "C 614,180 608,128 622,108 Z",
      "M 348,402 C 388,392 428,396 454,410 C 468,418 466,436 450,442 C 418,454 374,450 354,436 " +
      "C 342,428 340,410 348,402 Z",
      "M 640,240 C 660,232 686,236 700,252 C 712,266 710,288 696,300 C 680,314 654,312 640,296 " +
      "C 628,282 626,250 640,240 Z"
    ],
    /* 道路（浅灰，仅示意） */
    roads: [
      { d: "M 0,452 H 800", w: 9 },
      { d: "M 352,452 V 396", w: 7 },
      { d: "M 296,392 C 288,330 288,240 298,190", w: 6 },
      { d: "M 300,142 C 380,128 540,166 620,204", w: 6 },
      { d: "M 620,204 C 652,250 664,320 650,404", w: 6 },
      { d: "M 420,404 V 444", w: 5 }
    ],
    plaza: [
      { cx: 420, cy: 388, rx: 64, ry: 26, label: "董奉广场" }
    ],
    /* 建筑：矩形 / shape / ellipse；lx/ly 可指定标签位置（默认居中） */
    buildings: [
      /* —— 教学区 —— */
      { id: "zq", cat: "teach", x: 430, y: 318, w: 62, h: 50, label: "自强楼", sub: "01号楼 · 5F" },
      { id: "hd", cat: "teach", x: 392, y: 182, w: 60, h: 66, label: "厚德楼", sub: "02号楼 · 5F" },
      { id: "jc", cat: "teach", x: 460, y: 205, w: 50, h: 52, label: "精诚楼", small: 1 },
      { id: "zs", cat: "teach", x: 516, y: 292, w: 58, h: 54, label: "至善楼" },
      { id: "jxz", cat: "teach", x: 502, y: 342, w: 54, h: 46, label: "教学综合楼", small: 1 },
      { id: "wx", cat: "teach", x: 582, y: 268, w: 66, h: 66, label: "五行楼" },
      { id: "b59", cat: "teach", x: 440, y: 412, w: 52, h: 32, label: "明德楼", small: 1 },
      { id: "b60", cat: "teach", x: 700, y: 408, w: 58, h: 36, label: "求真楼", small: 1 },
      /* —— 图书馆 / 文化 —— */
      { id: "lib", cat: "lib", shape: "M 342,304 L 412,304 L 418,332 L 404,368 L 384,392 L 362,370 L 346,334 Z",
        label: "图书馆", lx: 380, ly: 338 },
      { id: "b52", cat: "lib", ellipse: [505, 277, 26, 27], label: "椭圆建筑", tiny: 1, lx: 505, ly: 279 },
      { id: "museum", cat: "lib", x: 566, y: 392, w: 46, h: 26, label: "博物馆", tiny: 1 },
      /* —— 住宿 / 生活 —— */
      { id: "d13a", cat: "dorm", x: 215, y: 85, w: 40, h: 32, label: "13#A", tiny: 1 },
      { id: "d13b", cat: "dorm", x: 258, y: 50, w: 46, h: 34, label: "13#B", tiny: 1 },
      { id: "d12", cat: "dorm", x: 230, y: 132, w: 30, h: 24, label: "12#", tiny: 1 },
      { id: "d11", cat: "dorm", x: 194, y: 158, w: 30, h: 24, label: "11#", tiny: 1 },
      { id: "d10", cat: "dorm", x: 230, y: 176, w: 30, h: 24, label: "10#", tiny: 1 },
      { id: "d9", cat: "dorm", x: 218, y: 232, w: 30, h: 24, label: "9#", tiny: 1 },
      { id: "d8", cat: "dorm", x: 165, y: 198, w: 42, h: 26, label: "8#", tiny: 1 },
      { id: "d10a", cat: "dorm", x: 140, y: 252, w: 24, h: 18, label: "" },
      { id: "d10b", cat: "dorm", x: 118, y: 266, w: 24, h: 18, label: "" },
      { id: "d10c", cat: "dorm", x: 98, y: 304, w: 24, h: 18, label: "" },
      { id: "d10d", cat: "dorm", x: 136, y: 324, w: 24, h: 18, label: "" },
      { id: "d10e", cat: "dorm", x: 174, y: 304, w: 24, h: 18, label: "" },
      { id: "d10f", cat: "dorm", x: 196, y: 280, w: 24, h: 18, label: "" },
      { id: "d10g", cat: "dorm", x: 220, y: 288, w: 22, h: 16, label: "" },
      { id: "act", cat: "food", x: 264, y: 120, w: 44, h: 28, label: "活动中心", small: 1 },
      /* —— 食堂 / 培训 / 后勤 —— */
      { id: "canteen", cat: "food", x: 86, y: 350, w: 56, h: 50, label: "食堂综合楼", small: 1 },
      { id: "b54", cat: "food", x: 148, y: 378, w: 34, h: 34, label: "双创", tiny: 1 },
      { id: "b55", cat: "food", x: 86, y: 424, w: 34, h: 24, label: "" },
      { id: "b56", cat: "food", x: 128, y: 424, w: 34, h: 24, label: "" },
      { id: "b57", cat: "food", x: 240, y: 368, w: 60, h: 24, label: "" },
      { id: "b58", cat: "food", x: 240, y: 398, w: 72, h: 40, label: "培训中心", small: 1 },
      /* —— 运动 —— */
      { id: "b70", cat: "sport", x: 368, y: 30, w: 44, h: 46, label: "体育馆", small: 1 },
      { id: "b72", cat: "sport", x: 415, y: 5, w: 108, h: 48, label: "田径场", stadium: 1 },
      { id: "b72b", cat: "sport", x: 545, y: 10, w: 15, h: 17, label: "" },
      { id: "b72c", cat: "sport", x: 565, y: 10, w: 15, h: 17, label: "" },
      { id: "b72d", cat: "sport", x: 585, y: 10, w: 15, h: 17, label: "" },
      { id: "b72e", cat: "sport", x: 605, y: 10, w: 15, h: 17, label: "" },
      { id: "b72f", cat: "sport", x: 545, y: 32, w: 15, h: 17, label: "" },
      { id: "b72g", cat: "sport", x: 565, y: 32, w: 15, h: 17, label: "" },
      { id: "b72h", cat: "sport", x: 585, y: 32, w: 15, h: 17, label: "" },
      { id: "b72i", cat: "sport", x: 605, y: 32, w: 15, h: 17, label: "" },
      { id: "wcourt", cat: "sport", x: 30, y: 222, w: 26, h: 18, label: "" },
      { id: "wcourt2", cat: "sport", x: 30, y: 246, w: 26, h: 18, label: "" },
      { id: "wcourt3", cat: "sport", x: 30, y: 270, w: 26, h: 18, label: "" },
      /* —— 科研 / 实训 —— */
      { id: "b24", cat: "res", x: 385, y: 140, w: 64, h: 44, label: "康复研究院", small: 1 },
      { id: "b66", cat: "res", x: 748, y: 348, w: 44, h: 42, label: "中医实训楼", tiny: 1 },
      { id: "b86", cat: "res", x: 740, y: 100, w: 34, h: 26, label: "" },
      /* —— 名师苑（住宅/公寓） —— */
      { id: "ms1", cat: "res", x: 628, y: 128, w: 30, h: 22, label: "" },
      { id: "ms2", cat: "res", x: 664, y: 120, w: 30, h: 22, label: "" },
      { id: "ms3", cat: "res", x: 634, y: 158, w: 30, h: 22, label: "" },
      { id: "ms4", cat: "res", x: 670, y: 158, w: 30, h: 22, label: "" },
    ],
    /* 文字标注（区域、水面、道路） */
    labels: [
      { x: 350, y: 232, t: "宋慈湖", size: 11, color: "#6E8CA8", ls: 2 },
      { x: 540, y: 152, t: "宋慈湖", size: 10, color: "#6E8CA8", ls: 1 },
      { x: 660, y: 205, t: "宋慈湖", size: 9, color: "#6E8CA8" },
      { x: 168, y: 150, t: "学生公寓区", size: 10.5, color: "#7C6A52", bold: 1 },
      { x: 664, y: 112, t: "名师苑", size: 9, color: "#6A5F82" },
      { x: 692, y: 336, t: "时珍园", size: 8, color: "#5F8F5B" },
      { x: 575, y: 72, t: "球场", size: 8, color: "#5D7389" },
      { x: 52, y: 302, t: "球场", size: 8, color: "#5D7389" },
      { x: 560, y: 459, t: "华佗路", size: 7.5, color: "#8C9A97", ls: 2 },
      { x: 34, y: 330, t: "溪源江", size: 9, color: "#6E8CA8", rotate: -78 }
    ]
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function labelXY(b) {
    if (b.lx != null) return [b.lx, b.ly];
    if (b.ellipse) return [b.ellipse[0], b.ellipse[1]];
    if (b.shape) return [400, 338];
    return [b.x + b.w / 2, b.y + b.h / 2 + (b.sub ? 1 : 2)];
  }

  function buildingSVG(b, sel, pin) {
    var t = C.tone[b.cat] || C.tone.teach;
    if (sel) t = C.tone.sel;
    var s = "", p = labelXY(b);
    if (b.ellipse) {
      s += '<ellipse cx="' + b.ellipse[0] + '" cy="' + b.ellipse[1] + '" rx="' + b.ellipse[2] +
        '" ry="' + b.ellipse[3] + '" fill="' + t.fill + '" stroke="' + t.stroke +
        '" stroke-width="1.4"' + (b.dashed ? ' stroke-dasharray="4 4"' : '') + '/>';
    } else if (b.shape) {
      s += '<path d="' + b.shape + '" fill="' + t.fill + '" stroke="' + t.stroke +
        '" stroke-width="' + (sel ? 2.5 : 1.6) + '"/>';
    } else {
      var r = b.stadium ? 22 : 5;
      s += '<rect x="' + b.x + '" y="' + b.y + '" width="' + b.w + '" height="' + b.h +
        '" rx="' + r + '" fill="' + t.fill + '" stroke="' + t.stroke +
        '" stroke-width="' + (sel ? 2.5 : 1.6) + '"/>';
    }
    if (b.label) {
      var fs = b.tiny ? 8 : (b.small ? 9.5 : 12);
      var dy = b.tiny ? 0.5 : 0;
      s += '<text x="' + p[0] + '" y="' + (p[1] + dy) + '" text-anchor="middle" font-size="' + fs +
        '" font-weight="' + (b.tiny ? 600 : 800) + '" fill="' + (sel ? "#22624F" : t.ink) +
        '" dominant-baseline="middle">' + esc(b.label) + '</text>';
      if (b.sub) {
        s += '<text x="' + p[0] + '" y="' + (p[1] + 13) + '" text-anchor="middle" font-size="8.5" font-weight="700" fill="' +
          (sel ? "#4E9082" : "#8C9A97") + '" dominant-baseline="middle">' + esc(b.sub) + '</text>';
      }
    }
    if (pin && sel) {
      var px = p[0], py = b.shape ? (p[1] - 48) : (b.ellipse ? (b.ellipse[1] - b.ellipse[3] - 8) : (b.y - 10));
      s += '<g transform="translate(' + px + ',' + py + ')">' +
        '<path d="M0 24 C-12 11 -15 4 -15 -2 A15 15 0 1 1 15 -2 C15 4 12 11 0 24 Z" fill="#4E9082" stroke="#fff" stroke-width="2.4"/>' +
        '<circle cx="0" cy="-2" r="5.2" fill="#fff"/></g>';
    }
    return s;
  }

  function campusSVG(opt) {
    opt = opt || {};
    var vb = opt.viewBox || C.vb;
    var sel = opt.highlight || "";
    var i, h = '<svg viewBox="' + vb.join(" ") + '" role="img" aria-label="校园示意图（重绘，非比例尺）" ' +
      'style="display:block;width:100%;height:auto">';
    h += '<rect x="0" y="0" width="800" height="465" fill="#F4F8EF"/>';
    for (i = 0; i < C.lawn.length; i++) h += '<path d="' + C.lawn[i] + '" fill="#E6F0DF"/>';
    for (i = 0; i < C.roads.length; i++) {
      h += '<path d="' + C.roads[i].d + '" fill="none" stroke="#E3E8E1" stroke-width="' +
        C.roads[i].w + '" stroke-linecap="round"/>';
    }
    for (i = 0; i < C.water.length; i++) {
      h += '<path d="' + C.water[i] + '" fill="#CFE3F0" stroke="#BCD6E6" stroke-width="1.4"/>';
    }
    for (i = 0; i < C.plaza.length; i++) {
      var p = C.plaza[i];
      h += '<ellipse cx="' + p.cx + '" cy="' + p.cy + '" rx="' + p.rx + '" ry="' + p.ry +
        '" fill="#F1E8D8" stroke="#E6D8BE" stroke-width="1.2"/>';
      if (p.label) h += '<text x="' + p.cx + '" y="' + (p.cy + 2) + '" text-anchor="middle" font-size="9.5" font-weight="700" fill="#A08A64" dominant-baseline="middle">' + p.label + '</text>';
    }
    for (i = 0; i < C.buildings.length; i++) {
      var b = C.buildings[i];
      h += buildingSVG(b, b.id === sel, !!(opt.pin !== false));
    }
    for (i = 0; i < C.labels.length; i++) {
      var L = C.labels[i];
      var rot = L.rotate ? ' transform="rotate(' + L.rotate + ' ' + L.x + ' ' + L.y + ')"' : '';
      h += '<text x="' + L.x + '" y="' + L.y + '" text-anchor="middle" font-size="' + (L.size || 9) +
        '" font-weight="' + (L.bold ? 800 : 700) + '" fill="' + (L.color || "#8C9A97") + '"' +
        (L.ls ? ' letter-spacing="' + L.ls + '"' : '') + rot + '>' + esc(L.t) + '</text>';
    }
    h += '</svg>';
    return h;
  }

  global.CAMPUS = C;
  global.campusSVG = campusSVG;
})(typeof window !== "undefined" ? window : globalThis);
