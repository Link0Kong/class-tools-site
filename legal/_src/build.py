# -*- coding: utf-8 -*-
"""生成 legal/ 下的 10 个独立页面、文档中心与 manifest.json。

运行：
    cd web/legal/_src
    python build.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
sys.path.insert(0, str(HERE))

from common import (  # noqa: E402
    BASE,
    DEBUG_BASE,
    EFFECTIVE,
    EMAIL,
    LAST_UPDATED,
    OPERATOR,
    PLATFORM_ORDER,
    VERSION,
    CSS,
    footer,
    page_html,
)
from platforms import PLATFORMS  # noqa: E402
from privacy import render_privacy  # noqa: E402
from terms import render_terms  # noqa: E402

INDEX_CSS = r"""
.index-main{padding-top:34px;padding-bottom:72px}
.index-hero{background:linear-gradient(135deg,color-mix(in srgb,var(--teal) 12%,var(--card)),var(--card) 55%,color-mix(in srgb,var(--sand) 12%,var(--card)));border:1px solid var(--line);border-radius:24px;padding:34px 32px;box-shadow:var(--shadow);margin-bottom:20px}
.index-hero .kicker{margin-bottom:12px}
.index-hero h1{font-size:clamp(30px,4.8vw,46px);line-height:1.1;letter-spacing:-.03em;margin:0 0 10px}
.index-hero .lead{max-width:760px;margin-bottom:20px}
.hero-actions{display:flex;flex-wrap:wrap;gap:10px}
.btn-primary,.btn-ghost{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:9px 16px;font-size:13px;border:1px solid var(--line2);background:var(--card);color:var(--ink)}
.btn-primary{background:var(--teal);border-color:var(--teal);color:#fff}
.btn-primary:hover,.btn-ghost:hover{text-decoration:none;filter:brightness(.98)}
.btn-ghost:hover{border-color:var(--teal);color:var(--teal-d)}
.index-hero .meta-grid{margin-top:22px}
.platform-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:14px;margin:14px 0 26px}
.platform-card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px 18px 16px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:10px}
.platform-card:hover{border-color:color-mix(in srgb,var(--teal) 45%,var(--line))}
.pc-top{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.pc-badge{font:700 10px/1 var(--mono);letter-spacing:.08em;background:var(--bg2);border:1px solid var(--line);color:var(--ink3);border-radius:999px;padding:4px 7px}
.pc-top h3{margin:0;font-size:18px}
.pc-top .tag{margin-left:auto}
.platform-card>p{margin:0;color:var(--ink2);font-size:13px;line-height:1.7}
.platform-card ul{margin:0;padding-left:18px;color:var(--ink2);font-size:12.5px;line-height:1.7}
.platform-card li{margin:2px 0}
.pc-links{display:flex;gap:9px;flex-wrap:wrap;margin-top:auto;padding-top:4px}
.pc-links a{font-size:12.5px;border:1px solid var(--line2);border-radius:999px;padding:5px 11px;background:var(--bg2);color:var(--teal-d)}
.pc-links a:hover{border-color:var(--teal);text-decoration:none}
.index-sec{margin:30px 0 8px}
.url-table td a{word-break:break-all}
.url-table{min-width:780px}
.index-note{font-size:12.5px;color:var(--ink3);line-height:1.7}
.index-foot{border-top:1px solid var(--line);background:var(--bg2);padding:24px 0 30px;margin-top:26px}
.index-foot p{margin:0 0 7px;font-size:12.5px;color:var(--ink2);line-height:1.7}
@media (max-width:520px){.index-hero{padding:24px 18px}.platform-grid{grid-template-columns:1fr}.index-hero .meta-grid{grid-template-columns:1fr}}
@media print{.index-hero{box-shadow:none}.platform-grid{grid-template-columns:1fr 1fr}}
"""

DIFF_ROWS = [
    (
        "网页端",
        "浏览器（手机/平板/桌面）",
        "浏览器 localStorage/IndexedDB；通知权限；文件选择；无定位/通讯录/相机/麦克风",
        "浏览器站点设置；邮件申请云端删除",
        "PPT 存香港 OSS 公共读；无后台推送；大屏现场可见",
    ),
    (
        "安卓端",
        "Android 8.0+ 原生 App",
        "通知、日历、安装未知应用、WorkManager；OPPO 推送/账号；教务密码本机 Keystore",
        "我的 → 数据与隐私；邮件物理删除",
        "OPPO SDK；APK 侧载更新；体测健康数据；一个学号最多 3 个 OPPO 账号",
    ),
    (
        "电脑端",
        "Windows 10/11 x64 原生应用",
        "DPAPI；文件选择/下载；剪贴板；Windows 通知；本机 Office COM；无移动权限",
        "设置 → 清除缓存/数据目录；邮件云端删除",
        "单机单人；DPAPI 绑定 Windows 用户；Office 兼容性；文件传输 72h",
    ),
    (
        "鸿蒙端",
        "HarmonyOS 手机/平板/2in1/手表",
        "华为账号 openID、Push token、日历提醒、振动、网络信息；Asset Store；无定位/通讯录/相机",
        "退出/系统清除应用数据；邮件导出/删除",
        "华为账号/推送；手表轻量端；教务密码可走云端密文队列；当前无数据与隐私页",
    ),
    (
        "微信小程序端",
        "微信内小程序",
        "openid/订阅消息；相册/相机/聊天文件/保存相册/剪贴板；微信 downloadFile",
        "我的 → 数据与隐私；微信授权管理；邮件物理删除",
        "微信平台规则；云开发；访问统计/反馈不能自助删；PPT 香港 OSS 公共读",
    ),
]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote %-46s %8d chars" % (str(path.relative_to(OUT)), len(text)))


def index_html() -> str:
    cards = []
    for key in PLATFORM_ORDER:
        p = PLATFORMS[key]
        points = p["summary"]["privacy"][:3]
        lis = "".join("<li><b>%s</b>：%s</li>" % (a, b) for a, b in points)
        cards.append(
            """
<article class="platform-card">
  <div class="pc-top"><span class="pc-badge">%s</span><h3>%s</h3><span class="tag">%s</span></div>
  <p>%s</p>
  <ul>%s</ul>
  <div class="pc-links">
    <a href="%s/privacy.html">隐私政策</a>
    <a href="%s/terms.html">用户协议</a>
  </div>
</article>"""
            % (
                p["code"],
                p["name"],
                p["version"],
                p["full"],
                lis,
                key,
                key,
            )
        )
    diff_rows = "".join(
        "<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % row
        for row in DIFF_ROWS
    )
    url_rows = []
    for key in PLATFORM_ORDER:
        p = PLATFORMS[key]
        url_rows.append(
            "<tr><td><b>%s</b></td><td><a href=\"%s/privacy.html\">%s%s/privacy.html</a></td>"
            "<td><a href=\"%s/terms.html\">%s%s/terms.html</a></td><td>%s</td><td>%s</td></tr>"
            % (
                p["name"],
                key,
                BASE,
                key,
                key,
                BASE,
                key,
                p["full"],
                p["version"],
            )
        )
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>班级工具站 · 隐私政策与用户协议（五端）</title>
<meta name="description" content="班级工具站网页端、安卓端、电脑端、鸿蒙端、微信小程序端的隐私政策与用户协议统一入口。">
<meta name="robots" content="index,follow">
<meta name="format-detection" content="telephone=no">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="theme-color" content="#F7F8F8" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#111614" media="(prefers-color-scheme: dark)">
<link rel="canonical" href="%sindex.html">
<link rel="icon" href="data:image/svg+xml,%%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%%3E%%3Crect width='64' height='64' rx='14' fill='%%23F7F8F8'/%%3E%%3Ccircle cx='32' cy='32' r='9' fill='%%234E9082'/%%3E%%3Ccircle cx='15' cy='15' r='5' fill='%%236E8CA8'/%%3E%%3Ccircle cx='49' cy='49' r='5' fill='%%23B98F63'/%%3E%%3C/svg%%3E">
<link rel="alternate" type="application/json" href="manifest.json">
<style>%s%s</style>
</head>
<body>
<a class="skip" href="#main">跳到正文</a>
<header class="site-head">
  <div class="wrap head-inner">
    <a class="brand" href="index.html" aria-label="班级工具站法律文件">
      <span class="brand-dots" aria-hidden="true"><i></i><i></i><i></i></span>
      <span class="brand-text">班级工具站<small>法律文件</small></span>
    </a>
    <div class="head-actions">
      <a href="manifest.json">manifest.json</a>
      <button type="button" class="btn-print" data-print>打印 / 保存 PDF</button>
    </div>
  </div>
</header>
<main id="main" class="wrap index-main">
  <section class="index-hero">
    <div class="kicker">班级工具站 · LEGAL DOCUMENTS · V%s</div>
    <h1>隐私政策与用户协议</h1>
    <p class="lead">五个端，各自一份完整文本：网页端、安卓端、电脑端、鸿蒙端、微信小程序端。每端的运行环境、权限、第三方、数据删除路径和特别风险都不同，请不要混用。</p>
    <p class="index-note"><b>当前调试入口：</b><a href="http://121.196.47.2/legal/">http://121.196.47.2/legal/</a> · 域名恢复后使用 <span class="mono">https://tool.furina.fun/legal/</span>（页面内链接为相对路径，两种入口都可正常阅读）。</p>
    <div class="hero-actions">
      <a class="btn-primary" href="#platforms">选择你的端</a>
      <a class="btn-ghost" href="manifest.json">统一调取清单 JSON</a>
      <a class="btn-ghost" href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">工信部备案系统</a>
    </div>
    <div class="meta-grid">
      <div><span>文档版本</span><b>V%s</b></div>
      <div><span>生效日期</span><b>%s</b></div>
      <div><span>最近更新</span><b>%s</b></div>
      <div><span>运营者</span><b>%s（个人开发者）</b></div>
      <div><span>文档数量</span><b>5 端 × 2 份 = 10 页</b></div>
      <div><span>性质</span><b>非学校官方 · 免费 · 无广告</b></div>
    </div>
  </section>

  <div class="callout warn">
    <div class="callout-title">先看三件事</div>
    <div class="callout-body">
      <p><b>1. 不是学校官方：</b>本站由陈子麒个人开发维护，不代表学校、学院、班级或任何老师；课表、成绩、评奖、毕业等以学校正式通知为准。</p>
      <p><b>2. 跨境与公共读：</b>PPT 源文件/转换产物存阿里云 OSS 香港，属于跨境存储；Bucket 为公共读，链接不可枚举但持有者可访问。请勿上传敏感 PPT。</p>
      <p><b>3. 敏感信息与删除：</b>体测健康数据、教务密码、OPPO/华为账号标识等按敏感个人信息规则处理；端内“清除云端”是逻辑清除，物理删除请邮件申请（15 个工作日内）。</p>
    </div>
  </div>

  <h2 id="platforms" class="index-sec">选择你的端</h2>
  <p class="index-note">每张卡片都链接到该端独立的隐私政策和用户协议；页面内可再用顶部“适用端”切换。</p>
  <div class="platform-grid">%s</div>

  <h2 class="index-sec">五端差异速览</h2>
  <div class="table-wrap"><table class="url-table">
    <thead><tr><th>端</th><th>运行环境</th><th>额外信息/权限</th><th>删除本机/云端</th><th>特别风险</th></tr></thead>
    <tbody>%s</tbody>
  </table></div>

  <h2 class="index-sec">统一调取地址</h2>
  <p>域名恢复后，各端可直接加载下列稳定地址；开发者也可读取 <a href="manifest.json">manifest.json</a> 获取版本、路径和适用端。当前域名未恢复时，可把下表中的 <span class="mono">https://tool.furina.fun</span> 替换为 <span class="mono">http://121.196.47.2</span> 访问，路径不变。</p>
  <div class="table-wrap"><table class="url-table">
    <thead><tr><th>端</th><th>隐私政策</th><th>用户协议</th><th>适用环境</th><th>版本</th></tr></thead>
    <tbody>%s</tbody>
  </table></div>

  <h2 class="index-sec">文档说明</h2>
  <p class="index-note">本套文本依据 2026-11-17 的网页、安卓、Windows、HarmonyOS、微信小程序源码/契约编写，重点区分五端的运行环境、权限、第三方 SDK、数据存储、跨境与删除路径。它不是法律意见书；正式上架/发布前，请按《合规落地清单》把端内同意门禁、敏感信息单独同意、跨境单独同意、微信隐私指引、HTTPS、保留期清理等配套项完成，并建议由律师复核。</p>
  <p class="index-note">本页无外部字体、无统计脚本、无广告；打印时自动隐藏导航。运营者：%s；联系邮箱：<a href="mailto:%s">%s</a>；响应时限：15 个工作日内。</p>
</main>
<footer class="index-foot">
  <div class="wrap">
    <p><b>班级工具站 · 法律文件</b> · 运营者：%s（个人开发者） · 非学校官方</p>
    <p>版本 V%s · 生效 %s · 最近更新 %s · <a href="manifest.json">manifest.json</a></p>
    <p class="fine">本页为静态法律文本，不包含跟踪脚本、外部字体、广告或第三方统计。法律文本不构成正式法律意见；发布前请按实际功能与适用法律复核。</p>
  </div>
</footer>
<script>%s</script>
</body>
</html>
""" % (
        BASE,
        CSS,
        INDEX_CSS,
        VERSION,
        VERSION,
        EFFECTIVE,
        LAST_UPDATED,
        OPERATOR,
        "".join(cards),
        diff_rows,
        "".join(url_rows),
        OPERATOR,
        EMAIL,
        EMAIL,
        OPERATOR,
        VERSION,
        EFFECTIVE,
        LAST_UPDATED,
        "document.querySelectorAll('[data-print]').forEach(function(b){b.addEventListener('click',function(){window.print();});});",
    )


def manifest() -> dict:
    return {
        "schema": "class-tools-legal",
        "version": VERSION,
        "effectiveDate": EFFECTIVE,
        "lastUpdated": LAST_UPDATED,
        "operator": {
            "name": OPERATOR,
            "role": "个人开发者、班级管理员",
            "email": EMAIL,
            "official": False,
            "note": "不是学校官方平台，不代表学校、学院、班级或任何老师",
        },
        "baseUrl": BASE,
        "debugBaseUrl": DEBUG_BASE,
        "documents": {
            key: {
                "name": PLATFORMS[key]["name"],
                "full": PLATFORMS[key]["full"],
                "version": PLATFORMS[key]["version"],
                "privacy": "%s/privacy.html" % key,
                "terms": "%s/terms.html" % key,
                "filing": PLATFORMS[key].get("filing", ""),
            }
            for key in PLATFORM_ORDER
        },
        "notes": [
            "PPT 源文件与转换产物存放于阿里云 OSS 香港（公共读），属于跨境存储；首次使用需单独同意。",
            "体测健康数据、教务密码、OPPO/华为账号标识、特定身份等按敏感个人信息规则处理。",
            "端内“清除云端”为逻辑清除（覆盖为空/置否/归档），物理删除需邮件申请（15 个工作日内）。",
            "当前域名未恢复：调试入口为 debugBaseUrl；域名恢复后使用 baseUrl。",
            "本清单供各端统一调取；如域名变更，请同步更新 baseUrl/debugBaseUrl 与各端内置链接。",
        ],
    }


def main() -> None:
    for key in PLATFORM_ORDER:
        write(OUT / key / "privacy.html", render_privacy(key))
        write(OUT / key / "terms.html", render_terms(key))
    write(OUT / "index.html", index_html())
    mf = manifest()
    write(OUT / "manifest.json", json.dumps(mf, ensure_ascii=False, indent=2) + "\n")
    print("done: 10 documents + index + manifest")


if __name__ == "__main__":
    main()
