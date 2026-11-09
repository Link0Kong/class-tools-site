# 导出卡 v2 设计规格（网页 + 微信小程序同版式）

> 2026-11-05 · 目标：所有导出图片（网页 6 类、小程序 6 类）统一升级为「清爽分享卡」。
> 本文是网页 `exportCard()` 与小程序 `utils/canvas.js drawCard()` 的共同实现依据；
> 两边**版式算法逐像素一致**，仅平台色板、品牌文字、二维码支持不同。
> 硬约束（来自 web/AGENTS.md §2，不得违反）：参数配置区 + 斜向平铺水印 + 页脚生成时间 + 唯一编号；
> 不出现手机号/学号/宿舍号；不改导出命名规则 `<类型>_<YYYYMMDD-HHMM>_<参数>.png`。

## 0. 画布

- 逻辑宽度 `W = 760`，`DPR = 2`（成图宽 1520px，高度自适应）。
- 画布底色：垂直渐变（两端色见色板 `bgTop/bgBottom`）。
- 主卡：`M = 22` 内缩，圆角 `22`，白底、1px 描边、柔和投影
  （投影在填充卡片前设置：`shadowColor` 见色板、`shadowBlur = 26`、`shadowOffsetY = 8`，只用于卡片填充）。
- 内容盒：`X = cardX + 28 = 50`，`RX = W - 50 = 710`，`CW = 660`。

## 1. 色板（两套，按平台取）

| token | 网页 | 小程序 |
|---|---|---|
| bgTop | `#EFF4F2` | `#F2EDE2` |
| bgBottom | `#F7F8F8` | `#F4F0E6` |
| card | `#FFFFFF` | `#FFFFFF` |
| border | `#E6E9E8` | `#E7DED0` |
| ink | `#23302E` | `#303A35` |
| ink2 | `#5A6A67` | `#5C6860` |
| ink3 | `#8C9A97` | `#8B948B` |
| primary | `#4E9082` | `#5E8F87` |
| primary2（渐变第二色） | `#6E8CA8` | `#7D9EBB` |
| sand | `#B98F63` | `#C6A475` |
| panel（参数底） | `#F4F8F7` | `#F7F3EA` |
| panelBorder | `#E8EEEC` | `#E9E2D4` |
| chipBg | `#FFFFFF` | `#FFFFFF` |
| chipBorder | `#E3E9E6` | `#E7DED0` |
| groupBg | `#FAFCFB` | `#FBF8F1` |
| shadow | `rgba(35,48,46,0.13)` | `rgba(48,58,53,0.13)` |
| watermark | `#23302E` | `#303A35` |

品牌文字：网页 `tool.furina.fun`（页脚水印同）；小程序 `班级工具站`（页脚水印同）。

## 2. 版式常量（逻辑 px，自上而下）

头部（相对 cardTop=22）：
- 装饰竖条：`x = cardX+14, y = cardY+28, w = 4, h = 40`，圆角 2，primary→primary2 竖向渐变。
- 品牌行基线 `cardY+34`：3 个圆点（r=3，间距 10，cy=基线-4）颜色 primary / primary2 / sand；
  品牌文字 `X+34` 起，11px/800，ink3。
- 标题基线 `cardY+70`：30px/800，ink；超宽时逐步降字号（30→22）仍超则截断加 `…`。
- 副标题基线 `cardY+94`：13px/500，ink3；超宽降 11.5 再截断加 `…`。
- 分隔线 `cardY+118`，1px border，X→RX。

区块标题（参数配置 / 内容块标签 / 二维码说明）：
- 5×5 圆角方块（r=1.5，primary）位于 `(X, 基线-11)`；文字 `X+13` 起，12.5px/800。
- 参数配置块标题基线 `dividerY + 26 = 166`。

参数配置面板：
- 面板 top = 标题基线 + 12；左右贴 X/RX；圆角 14；填充 panel；1px panelBorder；`pad = 14`。
- 行：标签 12.5px/500 ink3；值 14px/600 ink2；行高 21（首行基线 = 行顶+17）；两列时标签列宽 `LW = 104`；标签与值间距 6。
- 列布局：所有行同时满足「标签实测宽 ≤ 104 且值实测宽 ≤ 190」→ **两列**（列宽 `(CW-28-20)/2 = 306`，
  列间距 20）；否则 **单列**（标签列宽按实测最长标签自适应，取 `min(186, max(110, 最长标签+6))`，值列 = 余宽；
  避免长标签被 104px 硬折成 3 行）。
- 值为长文本时在值列内换行（行高按 `max(1,行数)*21+3`）。
- 两列时按行成对，行高取两格最大值。
- 面板高 = pad*2 + Σ行高。

内容块（按 `blocks` 顺序）：
- 第一个块标题基线 = 参数面板 bottom + 30；后续块 = 上一块内容 bottom + 26。
- 块内容 top = 标题基线 + 14。
- 文本行：普通 14px/400 ink2，行高 24；`mono` 20px/800 primary，行高 30；富文本 run 中
  `dim` → 11.5px/600 ink3，`strong` → 14px/800 ink（mono 块 strong 用 primary）。
  首行基线 = 内容 top + 15。
- `chips: [{n, nm}]`（抽签结果等）：
  - chip 高 30、圆角 15、padding 11、chip 间距 7、行距 7；白底 + chipBorder。
  - 数字 13.5px/800 primary；与姓名间距 5；姓名 12px/500 ink2；基线 = chipTop + 20。
  - 无 `nm` 时只画数字；整块高度 = 行数*37 - 7。
- `groups: [[{n,nm}], ...]`（分组结果）：
  - 两列网格，列宽 `(CW-14)/2 = 323`，列间距 14，行间距 14。
  - 组面板：圆角 14、groupBg 底、1px panelBorder、padding 12。
  - 组头：`第 i 组` 12.5px/800 ink（基线 panelTop+20）；右侧 `n 人` 10.5px/500 ink3 右对齐。
  - 成员区 top = panelTop+34：成员横排换行，成员间水平距 10，行高 21；
    数字 11.5px/600 ink3 + 3px 间距 + 姓名 13.5px/700 ink；无姓名只画数字。
  - 组高 = 34 + 行数*21 + 10；同排两卡取等高，奇数个时最后一卡占半宽。
- 二维码（`o.qr`，仅网页抽签有）：
  - 位置：所有内容块之后；`qMod = qr.n < 37 ? 4 : 3`，安静区 4 模块；`qBox = qr.n*qMod + 8*qMod`。
  - 整行面板：**通栏** tinted 面板（宽 CW、高 `qBox+12+20 = plate+20`，圆角 14，panel 底 + panelBorder 描边）。
  - 右侧白底板：`plate = qBox+12`，圆角 10、chipBg 底、chipBorder 描边，距面板右/上各 10；二维码绘于板内 `6+quiet` 处。
  - 左侧：标题「剔除重抽记录」12.5px/800 primary（面板 top+28）；`o.qrNote` 前 3 条每条 12px/500 ink2
    （top+52 起、行高 18，超宽截断加 `…`）；底部说明「扫码查看本次剔除与补抽的完整记录」11px/500 ink3
    （面板 bottom-14）；抽签页同时传 `qr: logStr()` 与 `qrNote: [...]`。
  - 区块 bottom = 面板 top + plate + 20 + 4。
- 内容 bottom = 最后一块内容 bottom。

页脚：
- 分隔线 `footerDividerY = contentBottom + 26`，X→RX，border 色。
- 左：`o.foot`（11.5px/500 ink3，基线 +24）；`编号 <rec>`（11px/500 ink3，基线 +44）。
- 右：3 个小圆点（r=2.5，间距 8，primary/primary2/sand）+ 品牌文字 11.5px/800 primary，
  **右对齐到 RX**，基线与 foot 同基线。
- 卡底 = footerDividerY + 70；画布高 `H = 卡底 + 22`。

水印（必须保留）：
- 先裁剪到主卡圆角路径，再画；alpha 0.03（网页/小程序一致），颜色 watermark，15px/700，旋转 -20°。
- 以画布中心平铺：x 步长 300、y 步长 140，`textAlign = center`。
- 因裁剪在卡内，页面底色上不会出现被切一半的水印字。

## 3. API（两边保持一致）

`exportCard({title, sub, file, rec, config:[[k,v]], blocks:[...], foot, qr})`
- `blocks` 元素三种：
  1. `{label, lines:[string | runs], mono?, atomic?}`（旧的文本块，全保留兼容）
  2. `{label, chips:[{n,nm}]}`（新增）
  3. `{label, groups:[[{n,nm}],...], groupLabel?}`（新增，`groupLabel` 缺省 `第 N 组`）
- 小程序 `drawCard(g, canvas, opt)` / `exportCard(page, selector, opt)` / `exportAndSave(...)` 签名不变。

## 4. 各导出入口改法

网页（web/tools/index.html）：
- 抽签 `#aImg`：`blocks:[{label:"抽签结果", chips:A.result.map(n=>({n:n, nm:nameOf(n)}))}]`。
- 分组 `#gImg`：`blocks:[{label:"分组结果", groups:G.result.map(gp=>gp.map(m=>({n:m.n,nm:m.nm})))}]`。
- 结果单 `#sImg`：抽签用 chips、分组用一个 groups 块（有哪个放哪个）。
- 课表/作业/体测：维持文本块（可保留现 rich runs）。

小程序（mp-class-tools）：
- draw：chips 用 `this.data.rows`（`{n,nm}`）；已剔除块保留 lines。
- group：groups 用 `this.data.groups`（`{i,size,members:[{n,nm}]}`）。
- sum：`drawBlock.items` → chips；`groupBlocks[].items` 合成一个 groups 块。
- hw/tt/ft：维持文本块。

## 5. 验收

- 网页：`python tools/tests/export_check.py draw|group|flow|tt|hw|ft` 全部能落盘；
  逐张肉眼核查：标题/参数/内容/水印/时间/编号/品牌齐全，无右侧溢出、无底部截断、无空底。
- 小程序：`node unit.js`、`python staticcheck.py` 全绿；`python render_export.py draw|group|sum|hw|tt|ft`
  逐张肉眼核查（同一套判据）。
- 两端除色板/品牌/二维码外，结构、间距、字号必须一致。
- 图内不得出现学号、手机号、宿舍号；水印只在卡内。
