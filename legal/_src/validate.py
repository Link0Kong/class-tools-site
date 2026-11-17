# -*- coding: utf-8 -*-
"""静态校验：HTML 可解析、锚点/相对链接、无外部自动加载、无真实个人敏感信息。

运行：
    cd web/legal/_src
    python validate.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin

from lxml import html

ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = ["web", "android", "windows", "harmony", "mp"]
KINDS = ["privacy", "terms"]

PII_PATTERNS = [
    ("真实学号", re.compile(r"3260\d{6}")),
    ("11 位手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("具体宿舍号", re.compile(r"宿舍\s*\d{2,}")),
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
]

BAD_TEXT = [
    "data 删除",
    "shared/",
    "TODO",
    "待填写",
    "placeholder",
    "{{",
    "}}",
    "Traceback",
]

REQUIRED = ["陈子麒", "Ko_Link@outlook.com"]


def check_page(path: Path) -> list[str]:
    errors: list[str] = []
    raw = path.read_text(encoding="utf-8")
    try:
        doc = html.fromstring(raw)
    except Exception as exc:  # noqa: BLE001
        return ["HTML 解析失败：%s" % exc]

    if doc.get("lang") != "zh-CN":
        errors.append("html lang 不是 zh-CN")
    if not doc.xpath("//meta[@name='viewport']"):
        errors.append("缺少 viewport meta")
    if not doc.xpath("//title"):
        errors.append("缺少 title")
    if not doc.xpath("//h1"):
        errors.append("缺少 h1")

    ids = doc.xpath("//*[@id]/@id")
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errors.append("重复 id：%s" % ", ".join(dup))

    anchors = set(ids)
    for href in doc.xpath("//a/@href"):
        href = href.strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        if href.startswith("#"):
            if href[1:] and href[1:] not in anchors:
                errors.append("锚点不存在：%s" % href)
            continue
        if href.startswith(("http://", "https://")):
            continue
        # 相对链接：解析到文件，检查文件存在
        target = unquote(urldefrag(href)[0])
        if not target:
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            errors.append("相对链接不存在：%s -> %s" % (href, resolved))

    for tag in doc.xpath("//script[@src] | //img[contains(@src,'http')] | //iframe[contains(@src,'http')]"):
        errors.append("存在外部自动加载资源：%s" % tag.tag)
    for link in doc.xpath("//link[contains(@href,'http')]"):
        rel = (link.get("rel") or "").lower()
        href = (link.get("href") or "").lower()
        # canonical / alternate 是元数据；data URI 图标不是外部请求。
        if rel not in ("canonical", "alternate") and not href.startswith("data:"):
            errors.append("存在外部自动加载资源：link rel=%s" % rel)

    visible = " ".join(
        doc.xpath("//body//text()[not(ancestor::script) and not(ancestor::style)]")
    )
    text = visible
    for label, pattern in PII_PATTERNS:
        match = pattern.search(text)
        if match:
            errors.append("疑似%s：%s" % (label, match.group(0)))
    for bad in BAD_TEXT:
        if bad in text:
            errors.append("出现占位/残留文本：%s" % bad)
    for req in REQUIRED:
        if req not in text:
            errors.append("缺少必要信息：%s" % req)

    # 每个文档页应有 5 个端切换链接
    if path.name in ("privacy.html", "terms.html"):
        ends = doc.xpath("//nav[contains(@class,'ends')]/a")
        if len(ends) != 5:
            errors.append("端切换链接数量不是 5：%d" % len(ends))
        if not any("on" in (a.get("class") or "") for a in ends):
            errors.append("端切换缺少当前端高亮")

    # 表格应有表头
    for table in doc.xpath("//table"):
        if not table.xpath("./thead/tr/th"):
            errors.append("表格缺少 thead/th")

    return errors


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    errors: list[str] = []
    html_files = sorted(ROOT.glob("**/*.html"))
    if len(html_files) != 11:
        errors.append("HTML 数量应为 11（10 文档 + index），实际 %d" % len(html_files))
    for path in html_files:
        for err in check_page(path):
            errors.append("%s：%s" % (path.relative_to(ROOT), err))

    # manifest 路径与文档数量
    mf_path = ROOT / "manifest.json"
    try:
        mf = json.loads(mf_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append("manifest.json 解析失败：%s" % exc)
        mf = {}
    docs = mf.get("documents") or {}
    if set(docs) != set(PLATFORMS):
        errors.append("manifest documents 端不完整：%s" % sorted(docs))
    for key, item in docs.items():
        for field in ("privacy", "terms"):
            target = ROOT / item[field]
            if not target.exists():
                errors.append("manifest %s.%s 文件不存在：%s" % (key, field, item[field]))

    # index 链接 10 个文档
    idx = html.fromstring((ROOT / "index.html").read_text(encoding="utf-8"))
    hrefs = set(idx.xpath("//a/@href"))
    for key in PLATFORMS:
        for kind in KINDS:
            if "%s/%s.html" % (key, kind) not in hrefs:
                errors.append("index 缺少链接：%s/%s.html" % (key, kind))

    if errors:
        print("FAIL %d" % len(errors))
        for err in errors:
            print(" -", err)
        return 1
    print("PASS：%d 个 HTML 页面、%d 个端、manifest 与锚点/资源/敏感信息检查通过" % (len(html_files), len(PLATFORMS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
