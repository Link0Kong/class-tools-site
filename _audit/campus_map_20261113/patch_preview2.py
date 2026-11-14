# -*- coding: utf-8 -*-
"""预览第二轮视觉修正。"""
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


# 1. 高度视觉夸张（投影 z 统一放大）
rep('''  function proj(x, y, z) {
    var r = raw(x, y, z), s = scaleNow();''',
    '''  function proj(x, y, z) {
    z = z * 1.18;
    var r = raw(x, y, z), s = scaleNow();''', "heightexag")

# 2. 桌面更满一点
rep('s *= (W > 820 ? 1.12 : 1.0);', 's *= (W > 820 ? 1.18 : 1.0);', "fitzoom2")
rep('var cyc = W > 820 ? 0.52 : 0.40;', 'var cyc = W > 820 ? 0.50 : 0.40;', "center")

# 3. 手机缩放/定位微调
rep('CAM.zoom = 1.62;', 'CAM.zoom = 1.45;', "mobzoom")
rep('var tx = W / 2, ty = H * (W > 820 ? 0.45 : 0.33);',
    'var tx = W / 2, ty = H * (W > 820 ? 0.45 : 0.35);', "mobty")

# 4. 手机只留平面/2.5D 两个按钮（其余手势/双击代替）
rep('''    .toolbar #btnAbout{display:none}''',
    '''    .toolbar #btnAbout, .toolbar #btnView, .toolbar #btnReset{display:none}''', "mobtoolbar2")

# 5. 树只落在校区红线内 + 再稀一点
rep('''        var waters = GROUPS.water || [];
        for (j = 0; j < waters.length && !skip; j++) if (inPoly(x, y, waters[j].p)) skip = true;
        if (skip) continue;''',
    '''        var waters = GROUPS.water || [];
        for (j = 0; j < waters.length && !skip; j++) if (inPoly(x, y, waters[j].p)) skip = true;
        if (skip) continue;
        var bnd0 = (GROUPS.bnd || [])[0];
        if (bnd0 && !inPoly(x, y, bnd0.p)) continue;''', "treebound")
rep('for (var gy = 10; gy < CH - 8; gy += 13) {', 'for (var gy = 10; gy < CH - 8; gy += 15) {', "treestep")
rep('for (var gx = 10; gx < CW - 8; gx += 13) {', 'for (var gx = 10; gx < CW - 8; gx += 15) {', "treestep2")
rep('if (rnd() < 0.52) continue;', 'if (rnd() < 0.58) continue;', "treedens2")

# 6. 双击复位
rep('''  canvas.addEventListener("wheel", function (e) {''',
    '''  canvas.addEventListener("dblclick", function () {
    flyTo(targetForMode(MODE), 480);
  });
  canvas.addEventListener("wheel", function (e) {''', "dblclick")

# 7. 小地图配色更实
rep('mctx.fillStyle = "#F3F5E8"; mctx.fillRect(0, 0, CW, CH);',
    'mctx.fillStyle = "#EDF1E2"; mctx.fillRect(0, 0, CW, CH);', "minibg")
rep('mctx.fillStyle = BLD[i].id === SEL ? "#4E9082" : (BLD[i].g === "residential" ? "#DCC9A8" : (BLD[i].g === "academic" ? "#9CC0B3" : (BLD[i].g === "civic" ? "#AFBECF" : "#C4CCC1")));',
    'mctx.fillStyle = BLD[i].id === SEL ? "#4E9082" : (BLD[i].g === "residential" ? "#D6BE99" : (BLD[i].g === "academic" ? "#8FB9A8" : (BLD[i].g === "civic" ? "#A3B6CC" : "#B9C1B4")));', "minicolors")
rep('for (i = 0; i < (GROUPS.water || []).length; i++) fill(GROUPS.water[i].p, "#BBD8E8");',
    'for (i = 0; i < (GROUPS.water || []).length; i++) fill(GROUPS.water[i].p, "#AFCFE2");', "miniwater")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched", len(s.encode("utf-8")))
