# -*- coding: utf-8 -*-
"""把 implementation_plan.md 构建成单文件 HTML 报告（零外部请求）。"""
import re
import sys
import html
import datetime
import pathlib

import markdown

BASE = pathlib.Path(r"G:\ClassTools\web\_compliance")
SRC = BASE / "implementation_plan.md"
OUT = pathlib.Path(r"C:\Users\Ko_Li\OneDrive\桌面\班级工具站_合规备案落地实施方案_20261105.html")

md_text = SRC.read_text(encoding="utf-8")

# 去掉首个 H1（由模板自己渲染）
lines = md_text.splitlines()
if lines and lines[0].startswith("# "):
    lines = lines[1:]
body_md = "\n".join(lines).lstrip()

md = markdown.Markdown(
    extensions=["tables", "fenced_code", "sane_lists", "nl2br", "toc"],
    extension_configs={"toc": {"permalink": False}},
)
body = md.convert(body_md)

# 1) 表格包一层可横向滚动容器
body = body.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")

# 2) 任务清单：[ ] / [x] → 带保存状态的复选框
_counter = {"n": 0}


def _todo(m):
    checked = m.group(1).lower() == "x"
    _counter["n"] += 1
    n = _counter["n"]
    rest = m.group(2)
    return (
        f'<li class="todo"><label><input type="checkbox" data-ck="{n}"'
        f'{" checked" if checked else ""}><span>{rest}</span></label></li>'
    )


body = re.sub(r"<li>\[([ xX])\]\s*(.*?)</li>", _todo, body, flags=re.S)

# 3) 生成目录（h2）
heads = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body, flags=re.S)
toc_items = []
for i, (hid, htext) in enumerate(heads, 1):
    plain = re.sub(r"<[^>]+>", "", htext).strip()
    # 去掉标题自带的「0. 」「3. 」编号，避免与目录序号重复
    plain = re.sub(r"^\d+(?:\.\d+)?\s*[\.、·]?\s*", "", plain)
    plain = plain or htext
    toc_items.append(
        f'<a class="toc-item" href="#{hid}"><span class="toc-n">{i:02d}</span><span>{plain}</span></a>'
    )
toc_html = "\n".join(toc_items)

# 4) 首页摘要卡（手工提炼）
summary_cards = """
<div class="summary-grid">
  <div class="s-card"><div class="s-k">现在能备案吗</div><div class="s-v no">不能</div><div class="s-d">香港托管无内地接入资源，且 5 项阻断级合规缺口未清零</div></div>
  <div class="s-card"><div class="s-k">最快上线路径</div><div class="s-v">小程序 3–5 周</div><div class="s-d">先小程序备案 → 提审 → 发布；网站 ICP 备案寒假窗口补齐</div></div>
  <div class="s-card"><div class="s-k">要不要换域名</div><div class="s-v ok">不用</div><div class="s-d">.fun 在工信部批复与阿里云可备案后缀清单内</div></div>
  <div class="s-card"><div class="s-k">首年增量预算</div><div class="s-v">¥280–340</div><div class="s-d">CloudBase 续费 + 阿里云轻量；备案/软著/证书免费</div></div>
</div>
<div class="hero-note"><b>先读这一句：</b>备案是流程问题（2–6 周能办完）；真正决定成败的是三件事——<b>群消息来源合不合法</b>、<b>个人信息同意与删除做没做</b>、<b>这个产品算不算「教育移动应用」</b>。</div>
"""

NOW = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>班级工具站 · 转合规可备案 App 落地实施方案</title>
<style>
:root{{
  --bg:#F7F8F6; --bg2:#F1F4F1; --card:#FFFFFF; --ink:#232B28; --ink2:#4A5650; --muted:#7D8A84;
  --line:#E2E9E4; --line2:#D3DED7;
  --cy:#4E9082; --cy-d:#3E7468; --cy-l:#EAF3EF;
  --bl:#6E8CA8; --bl-l:#EDF2F6;
  --sand:#B98F63; --sand-l:#F7F0E7;
  --red:#B4564A; --red-l:#FBEEEC;
  --radius:16px;
  --shadow:0 10px 30px rgba(45,70,60,.07);
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font-family:"PingFang SC","Microsoft YaHei","Hiragino Sans GB",system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:15px;line-height:1.75;-webkit-font-smoothing:antialiased;
  overflow-x:hidden;overflow-wrap:break-word;word-break:normal;}}
main.content, .hero-inner, .wrap{{min-width:0}}
main.content p, main.content li, main.content td, main.content th{{overflow-wrap:break-word}}
a{{color:var(--cy-d);text-decoration:none;border-bottom:1px solid rgba(78,144,130,.28)}}
a:hover{{border-bottom-color:var(--cy)}}
.hero{{position:relative;background:
  radial-gradient(110% 120% at 8% 0%,#E8F2EC 0%,rgba(247,248,246,0) 55%),
  radial-gradient(90% 120% at 98% 0%,#EDF2F6 0%,rgba(247,248,246,0) 55%),
  linear-gradient(180deg,#FBFCFA 0%,var(--bg) 100%);
  border-bottom:1px solid var(--line);padding:54px 22px 30px;}}
.hero-inner{{max-width:1200px;margin:0 auto}}
.eyebrow{{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;letter-spacing:.14em;color:var(--cy-d);
  background:#EAF3EF;border:1px solid #D6E7DF;border-radius:999px;padding:5px 13px;font-weight:700}}
h1.title{{font-size:clamp(26px,4.4vw,40px);line-height:1.22;margin:16px 0 10px;letter-spacing:-.01em;font-weight:800}}
.subtitle{{color:var(--ink2);font-size:15.5px;max-width:880px}}
.meta{{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}}
.chip{{font-size:12.5px;color:var(--ink2);background:#fff;border:1px solid var(--line);border-radius:999px;padding:4px 12px}}
.chip b{{color:var(--ink);font-weight:650}}
.wrap{{max-width:1200px;margin:0 auto;padding:0 22px 70px}}
.summary-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:26px 0 14px}}
@media(max-width:900px){{.summary-grid{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:520px){{.summary-grid{{grid-template-columns:1fr}}}}
.s-card{{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 16px 14px;box-shadow:var(--shadow)}}
.s-k{{font-size:12px;color:var(--muted);letter-spacing:.06em}}
.s-v{{font-size:21px;font-weight:800;margin:5px 0 4px;color:var(--cy-d)}}
.s-v.no{{color:var(--red)}} .s-v.ok{{color:#3E7468}}
.s-d{{font-size:12.5px;color:var(--ink2);line-height:1.6}}
.hero-note{{margin:16px 0 4px;background:linear-gradient(180deg,#FFFDF8,#FBF7EF);border:1px solid #EADFCB;
  border-left:4px solid var(--sand);border-radius:12px;padding:13px 16px;font-size:14px;color:#5A4B36}}
.layout{{display:grid;grid-template-columns:270px minmax(0,1fr);gap:34px;margin-top:34px}}
@media(max-width:980px){{.layout{{grid-template-columns:minmax(0,1fr);gap:18px}}}}
aside.toc{{position:sticky;top:18px;align-self:start;max-height:calc(100vh - 40px);overflow:auto;
  background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:14px 10px;box-shadow:var(--shadow)}}
@media(max-width:980px){{aside.toc{{position:static;max-height:none}}}}
.toc-h{{font-size:12px;letter-spacing:.14em;color:var(--muted);padding:4px 10px 8px;font-weight:700}}
.toc-item{{display:flex;gap:10px;align-items:flex-start;padding:6px 10px;border-radius:9px;color:var(--ink2);
  font-size:13px;line-height:1.45;border-bottom:0}}
.toc-item:hover{{background:var(--cy-l);color:var(--cy-d)}}
.toc-item.active{{background:var(--cy-l);color:var(--cy-d);font-weight:650}}
.toc-n{{font-variant-numeric:tabular-nums;color:var(--muted);font-size:11.5px;padding-top:2px;min-width:18px}}
main.content{{min-width:0}}
main.content h1{{font-size:26px;margin:34px 0 12px;font-weight:800}}
main.content h2{{font-size:23px;margin:44px 0 14px;padding:0 0 10px 13px;border-left:5px solid var(--cy);
  border-bottom:1px solid var(--line);font-weight:800;letter-spacing:-.01em;scroll-margin-top:16px}}
main.content h3{{font-size:17px;margin:28px 0 10px;color:#2E3A34;font-weight:750}}
main.content h4{{font-size:15px;margin:20px 0 8px;color:var(--ink2)}}
main.content p{{margin:10px 0;color:#33403A}}
main.content ul,main.content ol{{padding-left:22px;color:#33403A}}
main.content li{{margin:5px 0}}
main.content li.todo{{list-style:none;margin-left:-22px}}
main.content li.todo label{{display:flex;gap:9px;align-items:flex-start;cursor:pointer}}
main.content li.todo input{{margin-top:5px;width:15px;height:15px;accent-color:var(--cy);flex:none}}
main.content li.todo input:checked + span{{color:var(--muted);text-decoration:line-through}}
main.content blockquote{{margin:16px 0;background:var(--cy-l);border:1px solid #D8E8E1;border-left:4px solid var(--cy);
  border-radius:12px;padding:12px 16px;color:#31443C;font-size:14px}}
main.content blockquote p{{margin:6px 0;color:#31443C}}
main.content code{{background:#EDF2EF;border-radius:5px;padding:1px 5px;font-size:12.5px;
  font-family:Consolas,"Cascadia Mono",monospace;color:#31574B}}
main.content pre{{background:#22302B;color:#E8F1EC;border-radius:12px;padding:16px;overflow:auto;font-size:13px;line-height:1.6}}
main.content pre code{{background:none;color:inherit;padding:0}}
main.content hr{{border:0;border-top:1px solid var(--line);margin:34px 0}}
main.content strong{{font-weight:750;color:#1E2A24}}
.todo .todo-tag{{display:none}}
.tw{{overflow-x:auto;margin:14px 0 20px;border:1px solid var(--line);border-radius:12px;background:var(--card);
  box-shadow:0 4px 14px rgba(45,70,60,.04)}}
table{{border-collapse:collapse;width:100%;min-width:640px;font-size:13.5px;line-height:1.6}}
thead th{{background:#EEF4F1;color:#2C4A40;text-align:left;font-weight:750;padding:10px 12px;
  border-bottom:1px solid var(--line2);white-space:nowrap}}
tbody td{{padding:9px 12px;border-bottom:1px solid #EDF1EE;vertical-align:top;color:#34413B}}
tbody tr:last-child td{{border-bottom:0}}
tbody tr:nth-child(even){{background:#FBFCFB}}
tbody tr:hover{{background:#F5FAF7}}
.tw::-webkit-scrollbar{{height:9px}} .tw::-webkit-scrollbar-thumb{{background:#C9D9D1;border-radius:9px}}
.footer{{max-width:1200px;margin:0 auto;padding:26px 22px 50px;color:var(--muted);font-size:12.5px;
  border-top:1px solid var(--line)}}
.footer b{{color:var(--ink2)}}
.backtop{{position:fixed;right:18px;bottom:18px;width:42px;height:42px;border-radius:12px;background:var(--cy);
  color:#fff;border:0;font-size:16px;cursor:pointer;box-shadow:var(--shadow);opacity:0;pointer-events:none;transition:.2s}}
.backtop.on{{opacity:.92;pointer-events:auto}}
@media print{{
  body{{background:#fff;font-size:12px}} aside.toc,.backtop,.hero-note{{display:none!important}}
  .layout{{display:block}} .hero{{padding:20px 0 8px;border:0;background:#fff}}
  main.content h2{{page-break-after:avoid}} .tw{{overflow:visible;border:0;box-shadow:none}}
  table{{min-width:0;font-size:11px}} a{{color:#111;border:0}}
}}
</style>
</head>
<body>
<header class="hero">
  <div class="hero-inner">
    <span class="eyebrow">合规 · 备案 · 落地</span>
    <h1 class="title">班级工具站 · 转合规可备案 App<br>落地实施方案</h1>
    <p class="subtitle">从现状体检、备案路径、技术整改到预算与验收的一站式执行清单。目标：让 H5 + 微信小程序（+ 可选安卓 App）在 2027 年春节前具备完整备案与个人信息合规能力。</p>
    <div class="meta">
      <span class="chip">版本 <b>v1.0</b></span>
      <span class="chip">日期 <b>2026-11-05</b></span>
      <span class="chip">主体 <b>个人（陈子麒）</b></span>
      <span class="chip">对象 <b>tool.furina.fun · 微信小程序 · 安卓（可选）</b></span>
      <span class="chip">预计 <b>2026-12 上旬上线小程序 · 2027-02 三层备案齐全</b></span>
    </div>
  </div>
</header>
<div class="wrap">
  {summary_cards}
  <div class="layout">
    <aside class="toc">
      <div class="toc-h">目录 NAVIGATION</div>
      {toc_html}
    </aside>
    <main class="content">
      {body}
    </main>
  </div>
</div>
<footer class="footer">
  <b>班级工具站 · 合规备案落地方案 v1.0</b> ｜ 生成时间 {NOW} ｜ 依据三份内部研究报告（监管规则 / 现状审计 / 交付路径）与 2026-11-05 官方公开来源。
  本方案不构成法律意见；管局与平台规则可能调整，提交前请复核官方原文。
</footer>
<button class="backtop" id="backtop" aria-label="回到顶部">↑</button>
<script>
(function(){{
  // 任务清单进度本地保存
  var boxes = document.querySelectorAll('input[data-ck]');
  boxes.forEach(function(b){{
    var key = 'zq_plan_ck_' + b.getAttribute('data-ck');
    try {{ if (localStorage.getItem(key) === '1') b.checked = true; }} catch(e) {{}}
    b.addEventListener('change', function(){{
      try {{ localStorage.setItem(key, b.checked ? '1' : '0'); }} catch(e) {{}}
    }});
  }});
  // 目录高亮
  var items = Array.prototype.slice.call(document.querySelectorAll('.toc-item'));
  var map = {{}};
  items.forEach(function(a){{ var id = a.getAttribute('href').slice(1); map[id] = a; }});
  var hs = document.querySelectorAll('main.content h2[id]');
  if ('IntersectionObserver' in window) {{
    var io = new IntersectionObserver(function(es){{
      es.forEach(function(e){{
        if (e.isIntersecting) {{
          items.forEach(function(x){{ x.classList.remove('active'); }});
          var a = map[e.target.id]; if (a) {{ a.classList.add('active'); }}
        }}
      }});
    }}, {{rootMargin: '-15% 0px -75% 0px', threshold: 0}});
    hs.forEach(function(h){{ io.observe(h); }});
  }}
  // 回到顶部
  var bt = document.getElementById('backtop');
  window.addEventListener('scroll', function(){{
    if (window.scrollY > 600) bt.classList.add('on'); else bt.classList.remove('on');
  }}, {{passive:true}});
  bt.addEventListener('click', function(){{ window.scrollTo({{top:0,behavior:'smooth'}}); }});
}})();
</script>
</body>
</html>
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(HTML, encoding="utf-8")
print("written:", OUT)
print("bytes:", OUT.stat().st_size)
print("toc items:", len(toc_items), "| todos:", _counter["n"])
