# -*- coding: utf-8 -*-
"""班级工具站法律文件 · 公共模板与样式（标准库，无外部依赖）。

产物是自包含静态 HTML：CSS/JS 内联，零外部字体、零统计脚本、零 CDN。
"""
from __future__ import annotations

import html

BASE = "https://tool.furina.fun/legal/"
DEBUG_BASE = "http://121.196.47.2/legal/"
OPERATOR = "陈子麒"
EMAIL = "Ko_Link@outlook.com"
VERSION = "1.0"
EFFECTIVE = "2026年11月17日"
LAST_UPDATED = "2026年11月23日"
# 网站备案号（2026-11-23 工信部 ICP 备案通过；网站首页底部须展示并链接工信部备案系统）
ICP_SITE = "闽ICP备2026042939号-2"
# 小程序备案号（微信小程序独立备案，与网站备案号不是同一个号）
ICP_MP = "闽ICP备2026042939号"

PLATFORM_ORDER = ["web", "android", "windows", "harmony", "mp"]

PLATFORM_NAMES = {
    "web": "网页端",
    "android": "安卓端",
    "windows": "电脑端",
    "harmony": "鸿蒙端",
    "mp": "微信小程序端",
}


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def table(headers, rows, cls: str = "", caption: str = "") -> str:
    """生成可横向滚动的表格；rows 的单元格允许内嵌安全 HTML。"""
    th = "".join("<th scope=\"col\">%s</th>" % h for h in headers)
    body = []
    for row in rows:
        tds = "".join("<td>%s</td>" % cell for cell in row)
        body.append("<tr>%s</tr>" % tds)
    cap = "<caption>%s</caption>" % caption if caption else ""
    return (
        '<div class="table-wrap"><table class="%s">%s<thead><tr>%s</tr></thead>'
        "<tbody>%s</tbody></table></div>" % (cls, cap, th, "".join(body))
    )


def callout(kind: str, title: str, body: str) -> str:
    return (
        '<div class="callout %s"><div class="callout-title">%s</div>'
        '<div class="callout-body">%s</div></div>' % (kind, title, body)
    )


def tag(text: str, tone: str = "") -> str:
    return '<span class="tag %s">%s</span>' % (tone, text)


def nav_links(current: str, kind: str) -> str:
    """五端切换；kind=privacy/terms，保持当前文档类型。"""
    out = []
    for key in PLATFORM_ORDER:
        name = PLATFORM_NAMES[key]
        cls = ' class="on"' if key == current else ""
        aria = ' aria-current="page"' if key == current else ""
        out.append(
            '<a href="../%s/%s.html"%s%s>%s</a>' % (key, kind, cls, aria, name)
        )
    return '<nav class="ends" aria-label="切换适用端">%s</nav>' % "".join(out)


def header(current: str, kind: str) -> str:
    counterpart = "terms" if kind == "privacy" else "privacy"
    counterpart_label = "用户协议" if kind == "privacy" else "隐私政策"
    return """
<header class="site-head">
  <div class="wrap head-inner">
    <a class="brand" href="../index.html" aria-label="返回法律文件中心">
      <span class="brand-dots" aria-hidden="true"><i></i><i></i><i></i></span>
      <span class="brand-text">班级工具站<small>法律文件</small></span>
    </a>
    <div class="head-actions">
      <a href="../%s/%s.html">%s</a>
      <a href="../index.html">文档中心</a>
      <button type="button" class="btn-print" data-print>打印 / 保存 PDF</button>
    </div>
  </div>
</header>
""" % (current, counterpart, counterpart_label)


def doc_head(p: dict, kind: str) -> str:
    is_privacy = kind == "privacy"
    title = "隐私政策" if is_privacy else "用户协议"
    doc_id = "CT-LEGAL-%s-%s-V%s" % (
        "PRIVACY" if is_privacy else "TERMS",
        p["code"],
        VERSION.replace(".", ""),
    )
    debug_line = ""
    if DEBUG_BASE.rstrip("/") != BASE.rstrip("/"):
        debug_line = (
            '<p class="doc-note">正式入口：<a href="%s%s/%s.html">%s%s/%s.html</a>；'
            '仅运维/本机使用 IP 调试入口 <a href="%s%s/%s.html">%s%s/%s.html</a>。页面内链接为相对路径，两种入口都可正常阅读。</p>'
            % (
                BASE, p["key"], kind,
                BASE, p["key"], kind,
                DEBUG_BASE, p["key"], kind,
                DEBUG_BASE, p["key"], kind,
            )
        )
    return """
<header class="doc-head">
  <div class="kicker">班级工具站 · 法律文件 · %s</div>
  <h1>%s</h1>
  <p class="lead">适用于%s</p>
  <div class="meta-grid">
    <div><span>适用端</span><b>%s</b></div>
    <div><span>文档版本</span><b>V%s</b></div>
    <div><span>生效日期</span><b>%s</b></div>
    <div><span>最近更新</span><b>%s</b></div>
    <div><span>运营者</span><b>%s（个人开发者）</b></div>
    <div><span>当前版本</span><b>%s</b></div>
  </div>
  <p class="doc-note">本页是面向%s的正式文本。若端内旧版说明与本页不一致，以本页为准，并将在下一次版本更新时同步端内。</p>
  %s
</header>
""" % (
        doc_id,
        title,
        p["full"],
        p["name"],
        VERSION,
        EFFECTIVE,
        LAST_UPDATED,
        OPERATOR,
        p["version"],
        p["name"],
        debug_line,
    )


def summary(p: dict, kind: str) -> str:
    cards = []
    for idx, item in enumerate(p["summary"][kind], 1):
        cards.append(
            '<div class="sum-card"><span class="sum-num">%02d</span><b>%s</b><p>%s</p></div>'
            % (idx, item[0], item[1])
        )
    return '<div class="summary-grid">%s</div>' % "".join(cards)


def toc(items) -> str:
    lis = "".join('<li><a href="#%s">%s</a></li>' % (anchor, title) for anchor, title in items)
    return """
<aside class="toc" aria-label="本页目录">
  <details open>
    <summary>目录</summary>
    <ol>%s</ol>
  </details>
  <div class="toc-note">
    <p><b>快速说明</b></p>
    <p>本页无外部字体、无统计脚本、无广告。打印时自动隐藏导航。</p>
  </div>
</aside>
""" % lis


def footer(p: dict, kind: str) -> str:
    counterpart = "terms" if kind == "privacy" else "privacy"
    counterpart_label = "用户协议" if kind == "privacy" else "隐私政策"
    filing = p.get("filing", "")
    filing_html = ('<p class="fine">%s</p>' % filing) if filing else ""
    return """
<footer class="site-foot">
  <div class="wrap">
    <div class="foot-grid">
      <div>
        <p class="foot-brand">班级工具站 · 法律文件</p>
        <p>运营者：%s（个人开发者、班级管理员）<br>
        联系邮箱：<a href="mailto:%s">%s</a><br>
        响应时限：收到有效申请后 15 个工作日内</p>
      </div>
      <div>
        <p><b>本端文档</b><br>
        <a href="../%s/privacy.html">隐私政策</a> · <a href="../%s/terms.html">用户协议</a><br>
        <a href="../index.html">全部端文档</a></p>
        %s
      </div>
      <div>
        <p><b>版本</b><br>V%s · 生效 %s<br>最近更新 %s</p>
        <p class="fine">本站为个人开发的班级辅助工具，<b>不是学校官方平台</b>，不代表学校、学院、班级或任何老师。</p>
      </div>
    </div>
    <p class="foot-line">本页为静态法律文本，不包含跟踪脚本、外部字体、广告或第三方统计。法律文本不构成正式法律意见；发布前请按实际功能与适用法律复核。</p>
    <p class="foot-line"><a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">工信部备案系统</a> · 网站备案号 <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">%s</a> · 文档编号 %s</p>
  </div>
</footer>
""" % (
        OPERATOR,
        EMAIL,
        EMAIL,
        p["key"],
        p["key"],
        filing_html,
        VERSION,
        EFFECTIVE,
        LAST_UPDATED,
        ICP_SITE,
        "CT-LEGAL-%s-%s-V%s"
        % ("PRIVACY" if kind == "privacy" else "TERMS", p["code"], VERSION.replace(".", "")),
    )


CSS = r"""
:root{
  color-scheme: light dark;
  --bg:#F7F8F8; --bg2:#F1F3F2; --card:#FFFFFF; --ink:#23302E; --ink2:#526460;
  --ink3:#7B8C88; --line:#E1E7E5; --line2:#D3DDD9;
  --teal:#4E9082; --teal-d:#3A7267; --blue:#6E8CA8; --sand:#B98F63;
  --warn:#A85B4E; --warn-bg:#FBF1ED; --warn-line:#E9C9BE;
  --note-bg:#EDF5F2; --note-line:#CBE0D9;
  --shadow:0 10px 30px rgba(35,48,46,.06);
  --r:16px; --max:1180px;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",Menlo,monospace;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#111614; --bg2:#151C19; --card:#18211E; --ink:#E7EFEC; --ink2:#B7C6C1;
    --ink3:#8FA19C; --line:#2A3833; --line2:#35453F;
    --teal:#72B6A6; --teal-d:#8DCABC; --blue:#93AEC7; --sand:#D3AC7E;
    --warn:#E0A08F; --warn-bg:#2A1D18; --warn-line:#5B3A30;
    --note-bg:#152521; --note-line:#2E4A42;
    --shadow:0 12px 34px rgba(0,0,0,.24);
  }
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:88px}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.78 var(--font);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:var(--teal-d);text-decoration:none;text-underline-offset:3px}
a:hover{text-decoration:underline}
a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid color-mix(in srgb,var(--teal) 55%,transparent);outline-offset:3px;border-radius:6px}
img{max-width:100%}
.skip{position:absolute;left:-9999px;top:0;background:var(--card);color:var(--ink);padding:10px 14px;z-index:99;border:1px solid var(--line)}
.skip:focus{left:12px;top:12px}
.wrap{width:100%;max-width:var(--max);margin:0 auto;padding:0 22px}
.site-head{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.head-inner{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:64px}
.brand{display:flex;align-items:center;gap:10px;color:var(--ink);text-decoration:none;min-width:0}
.brand:hover{text-decoration:none}
.brand-dots{display:inline-flex;gap:4px;flex:0 0 auto}
.brand-dots i{width:8px;height:8px;border-radius:50%;background:var(--teal);display:block}
.brand-dots i:nth-child(2){background:var(--blue)}
.brand-dots i:nth-child(3){background:var(--sand)}
.brand-text{font-weight:700;font-size:15px;line-height:1.2;white-space:nowrap}
.brand-text small{display:block;font-weight:500;font-size:11px;color:var(--ink3);letter-spacing:.12em;margin-top:3px}
.head-actions{display:flex;align-items:center;gap:14px;font-size:13px;color:var(--ink2);flex-wrap:wrap;justify-content:flex-end}
.btn-print{border:1px solid var(--line2);background:var(--card);color:var(--ink);border-radius:999px;padding:7px 12px;font:inherit;font-size:12px;cursor:pointer}
.btn-print:hover{border-color:var(--teal);color:var(--teal-d)}
.layout{display:grid;grid-template-columns:258px minmax(0,1fr);gap:38px;padding-top:30px;padding-bottom:70px;align-items:start}
.toc{position:sticky;top:88px;max-height:calc(100vh - 110px);overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px;box-shadow:var(--shadow)}
.toc details{margin:0}
.toc summary{list-style:none;cursor:pointer;font-weight:700;font-size:14px;letter-spacing:.04em;color:var(--ink);display:flex;align-items:center;justify-content:space-between;gap:8px;padding:2px 0 10px;border-bottom:1px solid var(--line);margin-bottom:10px}
.toc summary::-webkit-details-marker{display:none}
.toc summary::after{content:"−";color:var(--ink3);font-weight:400}
.toc details:not([open]) summary::after{content:"+"}
.toc ol{list-style:none;margin:0;padding:0;counter-reset:toc}
.toc li{counter-increment:toc;margin:0}
.toc li a{display:block;padding:5px 4px 5px 28px;position:relative;color:var(--ink2);font-size:13px;line-height:1.45;border-radius:7px}
.toc li a::before{content:counter(toc,decimal-leading-zero);position:absolute;left:4px;top:5px;color:var(--ink3);font:11px/1.5 var(--mono)}
.toc li a:hover{background:var(--bg2);color:var(--teal-d);text-decoration:none}
.toc-note{margin-top:14px;padding-top:12px;border-top:1px solid var(--line);font-size:12px;color:var(--ink3);line-height:1.6}
.toc-note p{margin:0 0 6px}
.doc{min-width:0}
.doc-head{background:linear-gradient(135deg,color-mix(in srgb,var(--teal) 10%,var(--card)),var(--card) 58%,color-mix(in srgb,var(--sand) 9%,var(--card)));border:1px solid var(--line);border-radius:22px;padding:30px 30px 24px;box-shadow:var(--shadow);margin-bottom:20px}
.kicker{font:700 11px/1.4 var(--mono);letter-spacing:.12em;color:var(--teal-d);text-transform:uppercase;margin-bottom:10px}
.doc-head h1{font-size:clamp(30px,4.6vw,44px);line-height:1.12;letter-spacing:-.02em;margin:0 0 8px;font-weight:800}
.lead{font-size:17px;color:var(--ink2);margin:0 0 18px}
.meta-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.meta-grid>div{background:var(--card);padding:10px 12px}
.meta-grid span{display:block;font-size:11px;color:var(--ink3);letter-spacing:.04em;margin-bottom:3px}
.meta-grid b{font-size:13px;font-weight:650;line-height:1.4}
.doc-note{font-size:12px;color:var(--ink3);margin:14px 0 0;line-height:1.6}
.ends{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px}
.ends a{border:1px solid var(--line2);background:var(--card);color:var(--ink2);border-radius:999px;padding:6px 12px;font-size:12px;line-height:1.4}
.ends a:hover{border-color:var(--teal);color:var(--teal-d);text-decoration:none}
.ends a.on{background:var(--teal);border-color:var(--teal);color:#fff}
.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:0 0 20px}
.sum-card{position:relative;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 16px 14px;box-shadow:var(--shadow)}
.sum-num{display:block;font:700 11px/1 var(--mono);color:var(--teal);letter-spacing:.08em;margin-bottom:8px}
.sum-card b{display:block;font-size:14px;margin-bottom:4px}
.sum-card p{margin:0;font-size:12.5px;color:var(--ink2);line-height:1.65}
.callout{border:1px solid var(--note-line);background:var(--note-bg);border-radius:14px;padding:14px 16px;margin:18px 0}
.callout.warn{border-color:var(--warn-line);background:var(--warn-bg)}
.callout-title{font-weight:750;font-size:14px;margin-bottom:4px}
.callout.warn .callout-title{color:var(--warn)}
.callout-body{font-size:13.5px;color:var(--ink2);line-height:1.7}
.callout-body p{margin:4px 0}
.callout-body ul{margin:4px 0 4px 18px;padding:0}
.tag{display:inline-block;font-size:11px;line-height:1.5;padding:1px 7px;border-radius:999px;border:1px solid var(--line2);color:var(--ink2);background:var(--bg2);white-space:nowrap}
.tag.ok{color:var(--teal-d);border-color:var(--note-line);background:var(--note-bg)}
.tag.warn{color:var(--warn);border-color:var(--warn-line);background:var(--warn-bg)}
section{scroll-margin-top:88px;margin:0 0 26px}
h2{font-size:23px;line-height:1.3;letter-spacing:-.01em;margin:34px 0 12px;padding-top:14px;border-top:1px solid var(--line);font-weight:800}
h2 .h2num{color:var(--teal);font:700 12px/1 var(--mono);letter-spacing:.08em;display:block;margin-bottom:7px}
h3{font-size:17px;line-height:1.45;margin:20px 0 8px;font-weight:750}
h4{font-size:15px;margin:16px 0 6px;font-weight:700}
p{margin:8px 0}
ul,ol{margin:8px 0 10px 22px;padding:0}
li{margin:4px 0}
li>ul,li>ol{margin-top:3px}
b,strong{font-weight:750}
.small{font-size:12.5px;color:var(--ink3);line-height:1.65}
.mono{font-family:var(--mono);font-size:.92em}
.table-wrap{width:100%;overflow-x:auto;border:1px solid var(--line);border-radius:12px;margin:12px 0 16px;background:var(--card);-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;min-width:720px;font-size:13px;line-height:1.6}
caption{caption-side:top;text-align:left;padding:10px 12px 0;font-weight:700;color:var(--ink2);font-size:12.5px}
th,td{text-align:left;vertical-align:top;padding:9px 11px;border-bottom:1px solid var(--line)}
th{background:var(--bg2);color:var(--ink2);font-weight:700;white-space:nowrap;position:sticky;top:0}
tr:last-child td{border-bottom:0}
td code,th code,p code,li code{font-family:var(--mono);font-size:.9em;background:var(--bg2);border:1px solid var(--line);border-radius:5px;padding:1px 4px;overflow-wrap:anywhere}
.template{font:12.5px/1.7 var(--mono);white-space:pre-wrap;overflow-wrap:anywhere;background:var(--bg2);border:1px dashed var(--line2);border-radius:12px;padding:14px 16px;margin:12px 0;color:var(--ink)}
.defs{display:grid;grid-template-columns:1fr;gap:8px;margin:10px 0}
.defs div{border-left:3px solid var(--note-line);padding:2px 0 2px 12px}
.defs dt{font-weight:750;font-size:14px}
.defs dd{margin:2px 0 0;color:var(--ink2);font-size:13.5px}
.split{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.mini-card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.mini-card b{display:block;margin-bottom:4px}
.mini-card p{margin:0;font-size:13px;color:var(--ink2)}
.site-foot{border-top:1px solid var(--line);background:var(--bg2);padding:28px 0 34px;margin-top:10px}
.foot-grid{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:24px}
.site-foot p{margin:0 0 8px;font-size:12.5px;color:var(--ink2);line-height:1.7}
.foot-brand{font-weight:800;color:var(--ink);font-size:14px}
.fine{font-size:11.5px;color:var(--ink3)}
.foot-line{border-top:1px solid var(--line);padding-top:12px;margin-top:16px!important;font-size:11.5px;color:var(--ink3)}
.nobreak{break-inside:avoid}
@media (max-width:960px){
  .layout{grid-template-columns:1fr;gap:16px;padding-top:18px}
  .toc{position:static;max-height:none;padding:10px 14px}
  .toc-note{display:none}
  .toc summary{padding-bottom:0;border-bottom:0;margin-bottom:0}
  .toc details[open] summary{padding-bottom:10px;border-bottom:1px solid var(--line);margin-bottom:10px}
  .doc-head{padding:22px 20px 18px;border-radius:18px}
  .meta-grid{grid-template-columns:1fr 1fr}
  .head-inner{min-height:58px}
  .brand-text{font-size:14px}
  .head-actions a{display:none}
  .foot-grid{grid-template-columns:1fr;gap:10px}
  .split{grid-template-columns:1fr}
}
@media (max-width:520px){
  .wrap{padding:0 15px}
  .doc-head h1{font-size:29px}
  .lead{font-size:15px}
  .meta-grid{grid-template-columns:1fr}
  .ends a{font-size:11.5px;padding:5px 10px}
  h2{font-size:21px}
  .summary-grid{grid-template-columns:1fr}
  .callout{padding:12px 13px}
  .site-head{position:static}
  .layout{padding-bottom:44px}
}
@media print{
  :root{color-scheme:light}
  body{background:#fff;color:#111;font-size:11pt;line-height:1.65}
  .site-head,.toc,.ends,.btn-print,.skip{display:none!important}
  .layout{display:block;max-width:none;padding:0}
  .wrap{max-width:none;padding:0}
  .doc-head{box-shadow:none;border:1px solid #bbb;background:#fff;padding:16px 18px}
  .doc-head h1{font-size:24pt}
  .summary-grid{grid-template-columns:1fr 1fr}
  .sum-card,.callout,.mini-card{box-shadow:none}
  h2{page-break-after:avoid;border-top:1px solid #ccc}
  h3,h4{page-break-after:avoid}
  table{min-width:0;font-size:9.5pt}
  .table-wrap{overflow:visible;border-color:#bbb}
  th{position:static}
  a{color:#111;text-decoration:underline}
  .site-foot{background:#fff;border-top:1px solid #bbb}
  .foot-grid{grid-template-columns:1fr 1fr}
}
@media (prefers-reduced-motion: reduce){
  html{scroll-behavior:auto}
}
"""


JS = r"""
(function(){
  document.querySelectorAll('[data-print]').forEach(function(btn){
    btn.addEventListener('click', function(){ window.print(); });
  });
  // 目录在桌面端保持展开；移动端默认收起，点开后可正常跳转。
  try{
    var d=document.querySelector('.toc details');
    if(d && window.matchMedia && window.matchMedia('(max-width:960px)').matches){ d.removeAttribute('open'); }
  }catch(e){}
})();
"""


def page_html(p: dict, kind: str, body: str, toc_items, title: str, desc: str) -> str:
    canonical = "%s%s/%s.html" % (BASE, p["key"], kind)
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>%s</title>
<meta name="description" content="%s">
<meta name="robots" content="index,follow">
<meta name="format-detection" content="telephone=no">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="theme-color" content="#F7F8F8" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#111614" media="(prefers-color-scheme: dark)">
<link rel="canonical" href="%s">
<link rel="icon" href="data:image/svg+xml,%%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%%3E%%3Crect width='64' height='64' rx='14' fill='%%23F7F8F8'/%%3E%%3Ccircle cx='32' cy='32' r='9' fill='%%234E9082'/%%3E%%3Ccircle cx='15' cy='15' r='5' fill='%%236E8CA8'/%%3E%%3Ccircle cx='49' cy='49' r='5' fill='%%23B98F63'/%%3E%%3C/svg%%3E">
<style>%s</style>
</head>
<body>
<a class="skip" href="#main">跳到正文</a>
%s
<main id="main" class="wrap layout">
%s
<article class="doc">
%s
</article>
</main>
%s
<script>%s</script>
</body>
</html>
""" % (
        esc(title),
        esc(desc),
        canonical,
        CSS,
        header(p["key"], kind),
        toc(toc_items),
        body,
        footer(p, kind),
        JS,
    )
