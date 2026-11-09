按 HANDOFF.md §5.2 跑基线自检（只验证，不改源码）：

1. 在 `C:\Users\Ko_Li\.openclaw\workspace\web\tools\` 下依次运行：
   - `python tests\selfcheck.py`（① 冒烟：0 JS 报错 + 旧数据迁移 + 无底部栏）
   - `python tests\overflow_check.py 430`（② 横向溢出审计）
   - `python tests\shots.py`（③ 各档宽度截图，含 HUD 读数）
   - `python tests\export_check.py draw`（④ 抓导出 PNG）
2. 按判据核对全绿：① PASS / ERR=(none) / navCount=0；② overflowCount=0；③ 每图 HUD scrollW==viewport 且 overflow=0；④ PNG 落盘、命名/水印/时间/编号齐全。
3. 如有不过项，只记录与定位，不修（冻结期 + 本轮只读）。
4. 汇总基线报告（含 ③④ 截图的视觉核查结论）。

副作用说明：脚本会在 tools/ 根生成临时预览 HTML（跑完自动删除）、在本机 127.0.0.1 起临时 HTTP 服务、并把截图/导出图写入 tests\_shots\；不修改 index.html 及任何源码。全程不触碰 deploy/creds.env、tools/cert/、acme_account_key.pem。