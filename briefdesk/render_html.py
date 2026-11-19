# -*- coding: utf-8 -*-
"""把方案 Markdown 渲染成单文件 HTML（暖白/雾青配色，零外部请求）。"""

import re
import sys
from pathlib import Path

import markdown

BASE = Path(r"G:\ClassTools\web\briefdesk")
MD_PATH = BASE / "班级通知整合方案.md"
OUT_PATH = BASE / "班级通知整合方案.html"

ARCH_HTML = """
<figure class="arch">
  <div class="arch-title">系统总览 · 数据从哪来、到哪去</div>
  <div class="arch-row">
    <div class="arch-card wechat">
      <h4>微信 4.1.15</h4>
      <p>班级群 / 学院群<br>私聊通知</p>
      <span class="tag">私聊 → 人工转发收件箱</span>
    </div>
    <div class="arch-card qq">
      <h4>QQ NT 9.9.31</h4>
      <p>班级群 / 学院通知群 / 课程群</p>
      <span class="tag">全量自动 · 含非 @ 消息</span>
    </div>
  </div>
  <div class="arch-arrow">↓ 本机只读解密 · 不注入 · 不联网上传</div>
  <div class="arch-row">
    <div class="arch-card svc">
      <h4>weflow-server :5033</h4>
      <p>微信 4.x 本地库只读（可选）</p>
    </div>
    <div class="arch-card svc">
      <h4>qqflow-server :5032</h4>
      <p>QQ NT 本地库只读</p>
    </div>
  </div>
  <div class="arch-arrow">↓ HTTP / SSE</div>
  <div class="arch-card core">
    <h4>Briefdesk 简报台 :3000</h4>
    <p>消息源插件 → 入口过滤 → 图片 OCR → AI 分类 → 语义去重 → 同话题合并 → 富媒体解析（公众号/小程序/文档）→ SQLite</p>
    <span class="tag">AI 默认本机 Ollama（qwen3:14b）· 数据不出本机</span>
  </div>
  <div class="arch-arrow">↓ 网页实时推送</div>
  <div class="arch-row">
    <div class="arch-card out"><h4>网页卡片</h4><p>备忘录 / 忽略 / 改分类</p></div>
    <div class="arch-card out"><h4>日历 · 提醒</h4><p>多截止时间 / 到期</p></div>
    <div class="arch-card out"><h4>问一问 RAG</h4><p>「这周有什么作业」</p></div>
    <div class="arch-card out"><h4>每日简报（新增）</h4><p>邮件 / 微信推送</p></div>
  </div>
  <div class="arch-arrow">↓ 人工确认 · 只同步精选（不走原始聊天）</div>
  <div class="arch-row">
    <div class="arch-card site"><h4>班级工具站 tool.furina.fun</h4><p>通知板块 · CloudBase notices · 同学可见</p><span class="tag">P2 整合</span></div>
    <div class="arch-card channel"><h4>QQ 频道</h4><p>公告栏 / 学习互助 / 活动报名</p><span class="tag">P2 同步发布</span></div>
  </div>
  <figcaption>实线 = P0/P1 必做；「工具站 / QQ 频道」= 完善后的对外通道（P2）。所有采集服务只监听 127.0.0.1。</figcaption>
</figure>
"""

CSS = """
:root {
  --bg: #F7F8F8;
  --ink: #22302E;
  --muted: #647572;
  --line: #E2E8E6;
  --card: #FFFFFF;
  --teal: #4E9082;
  --blue: #6E8CA8;
  --sand: #B98F63;
  --teal-soft: #EAF1EF;
  --warn-soft: #FBF7F0;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", system-ui, -apple-system, sans-serif;
  font-size: 15.5px;
  line-height: 1.78;
  -webkit-font-smoothing: antialiased;
}
.page { max-width: 1000px; margin: 0 auto; padding: 34px 20px 60px; }

/* ── Hero ── */
.hero {
  background: var(--card);
  border-radius: 16px;
  padding: 34px 38px 30px;
  box-shadow: 0 1px 2px rgba(34,48,46,.04), 0 10px 30px rgba(34,48,46,.05);
  border: 1px solid var(--line);
  position: relative;
  overflow: hidden;
}
.hero::before {
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 6px;
  background: linear-gradient(180deg, var(--teal), var(--blue) 55%, var(--sand));
}
.eyebrow {
  font-size: 12px; letter-spacing: 2.5px; text-transform: uppercase;
  color: var(--teal); font-weight: 600; margin-bottom: 12px;
}
.hero h1 {
  margin: 0 0 14px; font-size: 30px; line-height: 1.35; font-weight: 700;
  letter-spacing: .3px; color: #1C2A28;
}
.hero h1 span { color: var(--teal); }
.hero .sub { margin: 0 0 18px; color: var(--muted); font-size: 14.5px; line-height: 1.7; }
.meta { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  display: inline-block; padding: 3px 12px; border-radius: 99px;
  background: var(--teal-soft); color: #35645B; font-size: 12.5px; font-weight: 500;
}
.chip.alt { background: #EFF3F7; color: #4C657E; }
.chip.warm { background: var(--warn-soft); color: #8A6A44; }

/* ── Content ── */
.content { margin-top: 26px; }
.content h2 {
  font-size: 22px; line-height: 1.4; margin: 42px 0 14px; padding: 2px 0 2px 14px;
  border-left: 4px solid var(--teal); color: #1C2A28; scroll-margin-top: 16px;
}
.content h3 { font-size: 17px; margin: 26px 0 10px; color: #2C403C; }
.content h4 { font-size: 15px; margin: 18px 0 8px; color: #2C403C; }
.content p { margin: 10px 0; }
.content ul, .content ol { margin: 10px 0; padding-left: 24px; }
.content li { margin: 4px 0; }
.content hr { border: 0; border-top: 1px solid var(--line); margin: 34px 0; }
.content a { color: #3A7A6E; text-decoration: none; border-bottom: 1px solid #BFD8D2; }
.content a:hover { border-bottom-color: var(--teal); }
.content strong { color: #1B2B28; }

/* 表格 */
.table-wrap { overflow-x: auto; margin: 16px 0; border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
.content table { width: 100%; border-collapse: collapse; font-size: 14px; min-width: 760px; }
.content th, .content td { word-break: break-word; }
.content td:first-child { min-width: 92px; }
.content th {
  background: #EEF4F2; color: #2B4A44; text-align: left; font-weight: 600;
  padding: 10px 14px; border-bottom: 1px solid var(--line); white-space: nowrap;
}
.content td { padding: 10px 14px; border-bottom: 1px solid #EDF1F0; vertical-align: top; line-height: 1.65; }
.content tr:last-child td { border-bottom: 0; }
.content tbody tr:nth-child(even) td { background: #FBFCFC; }

/* 代码 */
.content pre {
  background: #F2F6F5; border: 1px solid #E1E9E7; border-left: 4px solid var(--teal);
  border-radius: 10px; padding: 14px 16px; overflow-x: auto; margin: 14px 0;
  font-size: 13px; line-height: 1.65;
}
.content pre code { background: none; padding: 0; border: 0; color: #23403A; font-size: 13px; }
.content code {
  font-family: "Cascadia Code", Consolas, "Courier New", monospace;
  background: #EDF3F1; color: #2F5D54; padding: 1px 6px; border-radius: 5px; font-size: 13px;
}

/* 引用 / 提示 */
.content blockquote {
  margin: 18px 0; padding: 14px 18px; background: var(--warn-soft);
  border-left: 4px solid var(--sand); border-radius: 10px; color: #5B5044;
}
.content blockquote p { margin: 4px 0; }

/* TOC */
.toc {
  background: var(--card); border: 1px solid var(--line); border-radius: 16px;
  padding: 20px 26px 22px; margin: 0 0 8px;
  box-shadow: 0 1px 2px rgba(34,48,46,.03);
}
.toc-title {
  font-size: 11.5px; letter-spacing: 2px; color: var(--teal); font-weight: 600; margin-bottom: 12px;
}
.toc-list {
  list-style: none; margin: 0; padding: 0;
  display: grid; grid-template-columns: 1fr 1fr; column-gap: 34px; row-gap: 2px;
  counter-reset: toc;
}
.toc-list li { break-inside: avoid; counter-increment: toc; }
.toc-list li a {
  display: flex; gap: 8px; align-items: baseline; color: #3D5A54; font-size: 13.5px;
  text-decoration: none; border-bottom: 0; padding: 3px 0;
}
.toc-list li a::before {
  content: counter(toc, decimal-leading-zero); color: #9DB8B2; font-size: 11px;
  font-family: Consolas, monospace; flex: 0 0 22px;
}
.toc-list li a span { border-bottom: 1px solid transparent; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.toc-list li a:hover span { border-bottom-color: #BFD8D2; }
@media (max-width: 760px) { .toc-list { grid-template-columns: 1fr; } }

/* 架构图 */
.arch {
  margin: 26px 0; padding: 22px 24px 16px; background: var(--card);
  border: 1px solid var(--line); border-radius: 16px;
  box-shadow: 0 6px 22px rgba(34,48,46,.04);
}
.arch-title { font-size: 13px; font-weight: 600; color: var(--teal); letter-spacing: 1px; margin-bottom: 16px; }
.arch-row { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; }
.arch-card {
  flex: 1 1 200px; min-width: 170px; border: 1px solid var(--line); border-radius: 12px;
  padding: 12px 15px; background: #FBFCFC;
}
.arch-card h4 { margin: 0 0 4px; font-size: 14px; color: #1F3330; }
.arch-card p { margin: 0; font-size: 12.5px; color: var(--muted); line-height: 1.55; }
.arch-card .tag {
  display: inline-block; margin-top: 7px; font-size: 11px; padding: 1px 9px;
  border-radius: 99px; background: var(--teal-soft); color: #35645B;
}
.arch-card.wechat { border-top: 3px solid var(--teal); }
.arch-card.qq { border-top: 3px solid var(--blue); }
.arch-card.svc { border-top: 3px solid var(--sand); background: #FDFBF8; }
.arch-card.core {
  flex: 1 1 100%; margin: 0; background: linear-gradient(100deg, #EDF5F3, #F6FAF9 60%, #FBF7F0);
  border-color: #C8DCD6;
}
.arch-card.core h4 { font-size: 15px; color: #234741; }
.arch-card.core p { color: #3E5B55; font-size: 13px; }
.arch-card.out { border-top: 3px solid #9CB3A9; min-width: 150px; }
.arch-card.site { border-top: 3px solid var(--teal); background: #F7FCFA; }
.arch-card.channel { border-top: 3px solid var(--blue); background: #F8FAFD; }
.arch-arrow { text-align: center; color: #7E9A93; font-size: 12px; letter-spacing: 1px; padding: 9px 0; }
.arch figcaption { margin-top: 14px; font-size: 12px; color: #8A9A96; text-align: center; }

/* 页脚 */
.footer {
  margin-top: 44px; padding: 22px 0 0; border-top: 1px solid var(--line);
  color: #8A9A96; font-size: 12.5px; display: flex; justify-content: space-between;
  flex-wrap: wrap; gap: 6px;
}

@media (max-width: 760px) {
  .page { padding: 18px 12px 40px; }
  .hero { padding: 24px 22px; }
  .hero h1 { font-size: 23px; }
  .content h2 { font-size: 19px; margin-top: 32px; }
  .toc ul { columns: 1; }
  .arch-card { flex-basis: 100%; }
  .content table { font-size: 13px; }
}

@media print {
  body { background: #fff; font-size: 12pt; }
  .page { max-width: 100%; padding: 0; }
  .toc { display: none; }
  .hero, .arch, .table-wrap, .content pre { box-shadow: none; }
  .content h2 { break-after: avoid; }
  .content h3, .content h4 { break-after: avoid; }
  .content pre, .content table, .arch { break-inside: avoid; }
  .content a { color: inherit; border-bottom: none; }
}
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
<title>班级通知整合方案 · Briefdesk + 微信人工转发 + QQ 群自动采集</title>
<!-- 单文件报告：零外部请求，双击即可打开 -->
<style>__CSS__</style>
</head>
<body>
<div class="page">
  <header class="hero">
    <div class="eyebrow">BRIEFDESK · 班级通知整合</div>
    <h1>微信人工转发 + QQ 群自动采集<br><span>班级通知整合方案</span></h1>
    <p class="sub">基于 Briefdesk（简报台）的本地化班级信息中枢 · 单机部署 · 零软件成本 · 数据默认不出本机 · 可整合进班级工具站与 QQ 频道</p>
    <div class="meta">
      <span class="chip">v1.1</span>
      <span class="chip alt">2026-11-03</span>
      <span class="chip alt">Windows 11 · 单机</span>
      <span class="chip warm">微信 4.1.15 · QQ NT 9.9.31</span>
      <span class="chip alt">工具站 · QQ 频道 · 富媒体</span>
    </div>
  </header>
  <main class="content">
__BODY__
  </main>
  <footer class="footer">
    <span>Briefdesk 班级通知整合方案 · 芙宁娜整理</span>
    <span>生成于 2026-11-03 · 单文件 HTML</span>
  </footer>
</div>
</body>
</html>
"""


def ensure_list_spacing(md_text: str) -> str:
    """python-markdown 不认「紧贴段落的列表」，这里给列表前补空行（跳过代码块）。"""
    lines = md_text.splitlines()
    out: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"^\s*(?:[-*+]|\d+\.)\s", line):
            prev = out[-1] if out else ""
            prev_stripped = prev.strip()
            if prev_stripped and not re.match(r"^\s*(?:[-*+]|\d+\.)\s", prev) \
                    and not prev.lstrip().startswith(("#", ">", "|", "```")):
                out.append("")
        out.append(line)
    return "\n".join(out)


def build_toc(html_body: str) -> str:
    """从渲染后的 h2 生成目录卡（两列，只收一级章节）。"""
    headings = re.findall(r'<h2 id="([^"]+)"[^>]*>(.*?)</h2>', html_body, flags=re.S)
    items = []
    for hid, raw in headings:
        text = re.sub(r"<[^>]+>", "", raw).strip()
        items.append(f'<li><a href="#{hid}"><span>{text}</span></a></li>')
    return (
        '<nav class="toc"><div class="toc-title">目录 · CONTENTS</div>'
        '<ol class="toc-list">' + "".join(items) + "</ol></nav>"
    )


def main() -> None:
    src = MD_PATH.read_text(encoding="utf-8")
    # 去掉 Markdown 里的一级标题：Hero 已经有标题，避免重复
    src = re.sub(r"\A#\s+.*?\n", "", src, count=1)
    src = ensure_list_spacing(src)

    html_body = markdown.markdown(
        src,
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
        extension_configs={"toc": {"title": ""}},
    )

    # 架构图占位符替换（markdown 可能把独立行包成 <p>）
    html_body = html_body.replace("<p>@@ARCH@@</p>", ARCH_HTML).replace("@@ARCH@@", ARCH_HTML)

    # 表格包一层横向滚动容器
    html_body = html_body.replace("<table>", '<div class="table-wrap"><table>')
    html_body = html_body.replace("</table>", "</table></div>")

    toc_html = build_toc(html_body)
    html_body = toc_html + html_body

    html = TEMPLATE.replace("__CSS__", CSS).replace("__BODY__", html_body)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"written: {OUT_PATH}  bytes={OUT_PATH.stat().st_size}  toc_items={toc_html.count('<li>')}")


if __name__ == "__main__":
    sys.exit(main())
