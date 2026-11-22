# 班级工具站 · 通知整合管线（Briefdesk）

班级通知从 QQ 群 / 微信群 / 私聊汇入班级工具站「通知」页的管线归档：

- `build_notice_board.py`：生成通知页 iframe 模板（由 `web/tools/build_notice_embed.py` 嵌入 `tools/index.html`）。
- `notice_course_link.py`：通知 × 课表联动（2026-11-23）——「课程 + 课前动作」类通知
  （如「思政三组 11-23 提前到教室拷演讲内容」）按 `tools/tt.json` 锚到该课上课时间，
  截止动作写成「思政课前」（数据随云端下发三端，无需改模板）；单测 `tests/test_course_link.py`。
- `render_html.py` / `_check_*.py`：模板渲染与校验脚本。
- `tests/`：通知展示、归一化、线程质量测试。
- `班级通知整合方案.md` / `.html`：方案与示例页。

> 实际采集端（Briefdesk 主程序）在本机 `C:\briefdesk`，不在本仓库；本仓库保存站点侧模板生成器与方案。
> 模板脚本含本机绝对路径，运行前按实际路径调整。

主站仓库：GitHub `Link0Kong/class-tools-site` / Gitee `ko_Link/class-tools-site`。
