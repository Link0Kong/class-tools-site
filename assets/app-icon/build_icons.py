# -*- coding: utf-8 -*-
"""
班级工具站 · 应用图标生成器
================================

一份矢量规格（64×64 视口的三圆点标记）生成全平台、全尺寸图标：

    python build_icons.py

输出目录与本文件同级：source/ png/ web/ android/ harmony/ windows/
以及 manifest.json、preview.png（供人工检查）。

说明
----
* 仅生成图标时使用 Pillow，站点和各端运行时都不依赖本脚本，不引入构建链。
* 几何与颜色必须与网页 favicon、Android 自适应前景、小程序头像保持一致：
  暖白 #F7F8F8 圆角方块（圆角 14/64），雾青 #4E9082 主圆点，
  灰蓝 #6E8CA8 左上圆点，暖沙 #B98F63 右下圆点。
* 改设计请同时改这里和五端图标，不要只改某一个尺寸。

依赖：Pillow
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- 品牌规格
VIEW = 64.0          # 设计视口
CORNER = 14.0        # 圆角半径（14/64 ≈ 21.9%）
BG = (247, 248, 248, 255)    # #F7F8F8 暖白
TEAL = (78, 144, 130, 255)   # #4E9082 雾青
BLUE = (110, 140, 168, 255)  # #6E8CA8 灰蓝
SAND = (185, 143, 99, 255)   # #B98F63 暖沙

# ((圆心 x, 圆心 y), 半径, 颜色)
DOTS = (
    ((32.0, 32.0), 9.0, TEAL),
    ((15.0, 15.0), 5.0, BLUE),
    ((49.0, 49.0), 5.0, SAND),
)

MASTER = 4096                       # 母版边长，4× 于最大成品 1024
PNG_SIZES = (16, 20, 24, 32, 40, 48, 64, 72, 96, 120, 128,
             144, 152, 167, 180, 192, 256, 384, 512, 1024)
WINDOWS_ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
FAVICON_SIZES = (16, 32, 48, 64)     # 网页 favicon 只放常用小帧，避免每次访问下载大文件
ANDROID_DP = (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96),
              ("xxhdpi", 144), ("xxxhdpi", 192))

MASKABLE_SCALE = 0.86     # 内容缩到 40% 安全圆内（29.04/32 × 0.86 ≈ 39.0%）
HARMONY_SCALE = 0.5 * VIEW / 44.0   # 鸿蒙分层前景：内容宽 ≈ 画布 50%
ANDROID_FG_SCALE = 72.0 / 64.0      # 108dp 画布内 72dp 安全区

FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")
FONT_REG = Path(r"C:\Windows\Fonts\msyh.ttc")

RECORDS: list[dict] = []


# ---------------------------------------------------------------- 绘制
def _master(shape: str) -> Image.Image:
    """生成 4096×4096 母版；shape 决定底、遮罩、内容缩放与画布尺寸。

    多数形态是 64×64 画布；Android 自适应前景必须按 108dp 画布出图
    （内容 72dp 居中），否则 PNG 前景会比 XML 矢量大一圈。
    """
    im = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    edge = MASTER - 1
    canvas = VIEW
    center = 32.0
    scale = 1.0

    if shape == "rounded":
        draw.rounded_rectangle((0, 0, edge, edge), radius=CORNER * (MASTER / canvas), fill=BG)
    elif shape == "square":
        draw.rectangle((0, 0, edge, edge), fill=BG)
    elif shape == "round":
        draw.ellipse((0, 0, edge, edge), fill=BG)
    elif shape == "maskable":
        draw.rectangle((0, 0, edge, edge), fill=BG)
        scale = MASKABLE_SCALE
    elif shape in ("glyph", "mono"):
        pass
    elif shape in ("android-fg", "android-mono"):
        canvas = 108.0
        center = 54.0
        scale = ANDROID_FG_SCALE
    elif shape == "harmony-fg":
        scale = HARMONY_SCALE
    elif shape == "harmony-app":
        draw.rectangle((0, 0, edge, edge), fill=BG)
        scale = HARMONY_SCALE
    else:
        raise ValueError("未知图标形态: %s" % shape)

    u = MASTER / canvas
    white = shape in ("mono", "android-mono")
    for (cx, cy), radius, color in DOTS:
        x = center + (cx - 32.0) * scale
        y = center + (cy - 32.0) * scale
        r = radius * scale
        draw.ellipse(
            ((x - r) * u, (y - r) * u, (x + r) * u, (y + r) * u),
            fill=(255, 255, 255, 255) if white else color,
        )
    return im


_MASTERS: dict[str, Image.Image] = {}


def icon(shape: str, size: int) -> Image.Image:
    """取指定形态、指定边长的成品。

    用 BOX（面积平均）而不是 LANCZOS：后者会在圆点边缘产生比底色更亮的
    过冲白边，小尺寸放到深色任务栏上像发光；BOX 只做覆盖率平均，边缘干净。
    """
    if shape not in _MASTERS:
        _MASTERS[shape] = _master(shape)
    return _MASTERS[shape].resize((size, size), Image.BOX)


# ---------------------------------------------------------------- 输出
def _reset(*names: str) -> None:
    for name in names:
        path = ROOT / name
        if path.is_dir() and path.parent == ROOT:
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def save_png(img: Image.Image, rel: str, purpose: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)
    RECORDS.append({
        "path": rel.replace("\\", "/"),
        "type": "png",
        "width": img.width,
        "height": img.height,
        "purpose": purpose,
        "sha256": _sha256(path),
    })


def save_svg(text: str, rel: str, purpose: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    RECORDS.append({
        "path": rel.replace("\\", "/"),
        "type": "svg",
        "viewBox": "0 0 64 64",
        "purpose": purpose,
        "sha256": _sha256(path),
    })


def save_ico(rel: str, purpose: str, sizes, bitmap_format: str | None = None) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = [icon("rounded", s) for s in sizes]
    base = frames[-1]
    kwargs = {"bitmap_format": bitmap_format} if bitmap_format else {}
    base.save(
        path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[:-1],
        **kwargs,
    )
    RECORDS.append({
        "path": rel.replace("\\", "/"),
        "type": "ico",
        "sizes": list(sizes),
        "purpose": purpose,
        "sha256": _sha256(path),
    })


# ---------------------------------------------------------------- SVG
SVG_COMMON = """<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 64 64" role="img" aria-label="班级工具站">
  <title>班级工具站</title>
"""
SVG_DOTS = """  <circle cx="32" cy="32" r="9" fill="#4E9082"/>
  <circle cx="15" cy="15" r="5" fill="#6E8CA8"/>
  <circle cx="49" cy="49" r="5" fill="#B98F63"/>
</svg>
"""
SVG_ROUNDED = SVG_COMMON + '  <rect width="64" height="64" rx="14" fill="#F7F8F8"/>\n' + SVG_DOTS
SVG_SQUARE = SVG_COMMON + '  <rect width="64" height="64" fill="#F7F8F8"/>\n' + SVG_DOTS
SVG_GLYPH = SVG_COMMON + SVG_DOTS
SVG_MONO = (
    SVG_COMMON
    + '  <circle cx="32" cy="32" r="9" fill="#FFFFFF"/>\n'
    + '  <circle cx="15" cy="15" r="5" fill="#FFFFFF"/>\n'
    + '  <circle cx="49" cy="49" r="5" fill="#FFFFFF"/>\n'
    + "</svg>\n"
)


# ---------------------------------------------------------------- 平台产物
def build_source() -> None:
    save_svg(SVG_ROUNDED, "source/app-icon.svg", "矢量源文件 · 圆角版（透明四角）")
    save_svg(SVG_SQUARE, "source/app-icon-square.svg", "矢量源文件 · 满幅方形（不透明）")
    save_svg(SVG_GLYPH, "source/app-icon-glyph.svg", "矢量源文件 · 仅三圆点（透明底）")
    save_svg(SVG_MONO, "source/app-icon-mono.svg", "矢量源文件 · 单色白（主题/单色图标）")


def build_png() -> None:
    for size in PNG_SIZES:
        save_png(icon("rounded", size), "png/app-icon-%d.png" % size,
                 "通用圆角图标 %dpx（文档 / PPT / 第三方软件）" % size)
    for size in (256, 512, 1024):
        save_png(icon("square", size), "png/app-icon-square-%d.png" % size,
                 "满幅方形 %dpx（系统遮罩 / 商店上传，不透明）" % size)
    save_png(icon("maskable", 512), "png/app-icon-maskable-512.png",
             "PWA maskable 512（内容缩至安全圆内）")
    save_png(icon("glyph", 1024), "png/app-icon-glyph-1024.png",
             "透明三圆点 1024（叠加 / 水印 / 深色底）")
    save_png(icon("mono", 1024), "png/app-icon-mono-1024.png",
             "单色白 1024（Android 单色层 / 主题图标）")


def build_web() -> None:
    save_ico("web/favicon.ico", "浏览器 favicon（16/32/48/64）", FAVICON_SIZES, "png")
    save_svg(SVG_ROUNDED, "web/favicon.svg", "浏览器 favicon · 矢量")
    for size in (16, 32, 48):
        save_png(icon("rounded", size), "web/favicon-%d.png" % size,
                 "浏览器 favicon %dpx" % size)
    for size in (120, 152, 167, 180):
        save_png(icon("square", size), "web/apple-touch-icon-%d.png" % size,
                 "iOS / iPadOS 主屏图标 %dpx（不透明）" % size)
    save_png(icon("square", 180), "web/apple-touch-icon.png",
             "iOS / iPadOS 主屏图标 180px（默认文件名）")
    for size in (192, 512):
        save_png(icon("rounded", size), "web/icon-%d.png" % size,
                 "PWA 图标 %dpx（any）" % size)
    save_png(icon("maskable", 512), "web/icon-maskable-512.png",
             "PWA 图标 512px（maskable 安全区）")


def build_android() -> None:
    for density, size in ANDROID_DP:
        save_png(icon("rounded", size),
                 "android/mipmap-%s/ic_launcher.png" % density,
                 "Android 传统启动图标 %s（%ddp）" % (density, size))
        save_png(icon("round", size),
                 "android/mipmap-%s/ic_launcher_round.png" % density,
                 "Android 圆形启动图标 %s（%ddp）" % (density, size))
    save_png(icon("square", 512), "android/ic_launcher-playstore-512.png",
             "Google Play 商店图标 512（不透明）")
    save_png(icon("android-fg", 432), "android/ic_launcher_foreground-432.png",
             "Android 自适应图标前景 432（108dp × 4）")
    save_png(icon("android-mono", 432), "android/ic_launcher_monochrome-432.png",
             "Android 单色层 432（系统主题取色）")


def build_harmony() -> None:
    save_png(icon("square", 1024), "harmony/background-1024.png",
             "鸿蒙分层图标背景 1024（暖白）")
    save_png(icon("harmony-fg", 1024), "harmony/foreground-1024.png",
             "鸿蒙分层图标前景 1024（内容居中，宽约 50%）")
    save_png(icon("harmony-app", 1024), "harmony/app_icon-1024.png",
             "鸿蒙应用图标 1024（背景 + 前景合成）")
    payload = (
        '{\n'
        '  "layered-image":\n'
        '  {\n'
        '    "background" : "$media:background",\n'
        '    "foreground" : "$media:foreground"\n'
        '  }\n'
        '}\n'
    )
    path = ROOT / "harmony/layered_image.json"
    path.write_text(payload, encoding="utf-8", newline="\n")
    RECORDS.append({
        "path": "harmony/layered_image.json",
        "type": "json",
        "purpose": "鸿蒙分层图标配置（background + foreground）",
        "sha256": _sha256(path),
    })


def build_windows() -> None:
    save_ico("windows/app-icon.ico", "Windows 可执行文件图标（16–256，32bpp）",
             WINDOWS_ICO_SIZES, "bmp")
    for size in (32, 48, 256):
        save_png(icon("square", size), "windows/app-icon-%d.png" % size,
                 "Windows 应用图标 %dpx（不透明）" % size)


# ---------------------------------------------------------------- 预览图
def _font(path: Path, size: int):
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default(size=size)


def _center_text(draw, x: int, width: int, y: int, text: str, font, fill) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((x + (width - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)


def build_preview() -> None:
    """生成一张 1600×1020 的检查图：浅色 / 深色界面、各尺寸、品牌色。"""
    canvas = Image.new("RGB", (1600, 1020), (236, 239, 238))
    draw = ImageDraw.Draw(canvas)
    title = _font(FONT_BOLD, 46)
    sub = _font(FONT_REG, 22)
    small = _font(FONT_REG, 18)
    tiny = _font(FONT_REG, 15)
    ink = (46, 58, 56)
    muted = (110, 124, 120)

    draw.text((80, 52), "班级工具站 · 应用图标", font=title, fill=ink)
    draw.text((80, 118), "三圆点标记 · 暖白圆角底 · 一份矢量源生成全平台尺寸", font=sub, fill=muted)

    chips = (("#F7F8F8", BG), ("#4E9082", TEAL), ("#6E8CA8", BLUE), ("#B98F63", SAND))
    cx = 80
    for label, color in chips:
        draw.rounded_rectangle((cx, 166, cx + 20, 186), radius=6, fill=color[:3],
                               outline=(210, 214, 210))
        draw.text((cx + 28, 163), label, font=small, fill=muted)
        cx += 150

    big = icon("rounded", 320)
    canvas.paste(big, (80, 240), big)
    draw.text((80, 574), "1024px 母版 · 文档 / PPT / 第三方软件", font=small, fill=muted)

    row = (256, 128, 96, 64, 48, 32, 24, 16)
    x, bottom = 470, 560
    for size in row:
        img = icon("rounded", size)
        canvas.paste(img, (x, bottom - size), img)
        _center_text(draw, x, size, bottom + 14, str(size), tiny, muted)
        x += size + 36

    draw.rounded_rectangle((60, 646, 1540, 950), radius=28, fill=(31, 38, 38))
    draw.text((90, 672), "深色界面 / 任务栏 / 深色模式", font=sub, fill=(236, 242, 240))
    x, bottom = 90, 900
    for size in (128, 96, 64, 48, 32, 24, 16):
        img = icon("rounded", size)
        canvas.paste(img, (x, bottom - size), img)
        _center_text(draw, x, size, bottom + 10, str(size), tiny, (178, 190, 186))
        x += size + 32

    for i, (shape, label) in enumerate((("glyph", "透明圆点"), ("mono", "单色白"))):
        img = icon(shape, 128)
        gx = 900 + i * 300
        canvas.paste(img, (gx, 760), img)
        draw.text((gx, 900), label, font=small, fill=(178, 190, 186))

    draw.line((80, 972, 1520, 972), fill=(224, 228, 224), width=1)
    draw.text((80, 984), "assets/app-icon · build_icons.py 生成 · 详见 manifest.json / README.md",
              font=tiny, fill=(150, 160, 156))

    path = ROOT / "preview.png"
    canvas.save(path, "PNG", optimize=True)
    print("已生成 preview.png %dx%d" % canvas.size)


# ---------------------------------------------------------------- 清单
def build_manifest() -> None:
    payload = {
        "name": "班级工具站",
        "slug": "class-tools",
        "version": "1.0.0",
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "brand": {
            "background": "#F7F8F8",
            "teal": "#4E9082",
            "blue": "#6E8CA8",
            "sand": "#B98F63",
            "corner_radius": "14/64",
            "dots": [
                {"cx": 32, "cy": 32, "r": 9, "color": "#4E9082"},
                {"cx": 15, "cy": 15, "r": 5, "color": "#6E8CA8"},
                {"cx": 49, "cy": 49, "r": 5, "color": "#B98F63"},
            ],
        },
        "files": sorted(RECORDS, key=lambda r: r["path"]),
    }
    path = ROOT / "manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    print("已生成 manifest.json（%d 个文件）" % len(RECORDS))


def main() -> None:
    _reset("source", "png", "web", "android", "harmony", "windows")
    build_source()
    build_png()
    build_web()
    build_android()
    build_harmony()
    build_windows()
    build_preview()
    build_manifest()
    print("完成：%s" % ROOT)


if __name__ == "__main__":
    main()
