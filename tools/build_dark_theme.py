# -*- coding: utf-8 -*-
"""生成网页「深色主题」静态覆盖 CSS（零依赖、纯标准库）。

背景（2026-11-15 网页移植 task-64）：
  - 网页此前只有浅色（Monet 暖奶油）主题，没有深色机制；
  - 安卓 App 的「外观：跟随系统 / 浅色 / 深色」需要移植到网页（本机 localStorage）；
  - 为了不破坏既有浅色视觉，深色实现为**纯追加的覆盖层**：
      html[data-appearance="dark"] <原选择器> { 映射后的颜色 }
    浅色（默认）时属性不存在，所有规则不生效，既有样式一行不改。

生成策略：把原样式表里所有硬编码颜色按「角色 + 亮度/色相」映射成深色版本：
  - 背景类：浅色面 → 深色面（保留色相，压暗 + 降饱和）；深色面/品牌中调填充保持不变；
  - 边框类：浅边框 → 深边框；
  - 文字类：深文字 → 浅文字（保留色相，暗色 → 亮色，层级仍按原亮度排序）；
  - 阴影/高光：亮色高光压成低透明度白光，暗色阴影保留；
  - 自定义属性（--x）：按名字后缀（bg/ink/bd/line/tint…）判断角色后同样映射。
  - 原声明里的 !important 会被保留（否则压不过模板自带的 !important）。

用法：
  python build_dark_theme.py                # 生成并注入 tools/index.html 的 __DARK_THEME_BEGIN/END 标记之间
  from build_dark_theme import build_dark_css
  build_dark_css(css_text)                  # 给通知 iframe 模板（build_notice_embed.py 用）

红线：不引入构建链（本脚本只是一次性静态产物生成器，产物直接写进 index.html）；
运行时不发任何请求、不依赖本脚本。
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"
BEGIN = "/* __DARK_THEME_BEGIN__ */"
END = "/* __DARK_THEME_END__ */"
PREFIX = 'html[data-appearance="dark"]'

# 主页面：语义变量基线（品牌色 --cy/--bl/--sd 保持原值，浅底上的白字按钮因此不受影响）
DARK_MANUAL = """/* 深色基线：中性色/卡片/描边/浅色底色变量（品牌雾青/灰蓝/暖沙保持原值） */
html[data-appearance="dark"]{
  color-scheme:dark;
  --bg:#111614;--card:#1A211E;--surface:#1A211E;--line:#2B342F;--line-strong:#35413A;
  --ink:#E9F0EC;--ink2:#B4C1BB;--ink3:#8A9891;
  --mint:#1C2A25;--mint2:#182320;
  --tint-blue:#1B2530;--tint-sand:#2A241B;--tint-rose:#2A1E1D;--tint-violet:#251F2D;
  --tint-panel:#222A25;
  --elev-card:0 1px 2px rgba(0,0,0,.30),0 12px 26px -14px rgba(0,0,0,.55);
}
/* 页面底：中性深色为主 + 极淡品牌光晕（不用暖奶油映射出来的橄榄色） */
html[data-appearance="dark"] body{
  background:
    radial-gradient(1100px 620px at 8% -8%,rgba(78,144,130,.14),transparent 62%),
    radial-gradient(900px 560px at 102% 2%,rgba(120,110,150,.10),transparent 58%),
    radial-gradient(760px 520px at 46% 108%,rgba(150,120,90,.08),transparent 62%),
    linear-gradient(180deg,#121614 0%,#111412 46%,#121613 100%);
  background-attachment:fixed;
}
html[data-appearance="dark"] .tabs{background:#1A201D;box-shadow:0 6px 16px -10px rgba(0,0,0,.60)}
html[data-appearance="dark"] .tabs button.on{background:#232B27}
html[data-appearance="dark"] input[type=text],html[data-appearance="dark"] input[type=password],
html[data-appearance="dark"] input[type=date],html[data-appearance="dark"] input[type=time],
html[data-appearance="dark"] input[type=number],html[data-appearance="dark"] select,
html[data-appearance="dark"] textarea{background:#151B18;border-color:#2F3A34}
html[data-appearance="dark"] ::selection{background:rgba(94,143,135,.38)}
html[data-appearance="dark"] .btn:hover,html[data-appearance="dark"] .mclose:hover{background:#252E2A}
html[data-appearance="dark"] .btn.pri{color:#fff}
html[data-appearance="dark"] #toast{background:rgba(22,29,26,.97);border-color:#35413A}
html[data-appearance="dark"] .nt-progress{background:#222A25}
html[data-appearance="dark"] .ap-ico{background:#252E29;color:#B4C1BB}
html[data-appearance="dark"] .ap-opt.on{border-color:var(--cy);background:rgba(94,143,135,.16)}
html[data-appearance="dark"] .dropctl-card{box-shadow:0 -14px 36px rgba(0,0,0,.55)}
html[data-appearance="dark"] .rst-sheet{box-shadow:0 -14px 40px rgba(0,0,0,.50)}
html[data-appearance="dark"] #s-map .mapframe{background:#0E1412}
html[data-appearance="dark"] .idgate{background:radial-gradient(120% 90% at 12% 0%,#16241F 0%,#111614 46%,#171412 100%)}
html[data-appearance="dark"] .idcard{background:#1A211E;border-color:#2E3A34}
html[data-appearance="dark"] .idfield input{background:#141A18;border-color:#2E3A34;color:#E9F0EC}
html[data-appearance="dark"] .opt-ov,html[data-appearance="dark"] .modal,html[data-appearance="dark"] .notice-modal{background:rgba(6,10,8,.62)}
/* 通知 iframe：深色由模板内置（build_notice_embed 注入），父页只负责切换属性 */
html[data-appearance="dark"] #noticeHost .notice-empty,html[data-appearance="dark"] #noticeHost .notice-fail{color:var(--ink3)}
"""

# 通知 iframe 模板：模板自带 :root 变量 + OVERRIDE（含 !important 浅色），先给出深色变量基线
NOTICE_DARK_MANUAL = """/* 通知 iframe 深色基线（模板内 :root 变量；OVERRIDE 的 !important 由生成段按选择器加权覆盖） */
html[data-appearance="dark"]{
  color-scheme:dark;
  --bg:#111614;--card:#1A211E;--line:#2B342F;--ink:#E9F0EC;--ink2:#B4C1BB;--ink3:#8A9891;
  --cy:#5E8F87;--bl:#7D9EBB;--sd:#C6A475;--danger:#C98780;
  --mint:#1C2A25;--mint2:#182320;
  --tint-blue:#1B2530;--tint-sand:#2A241B;--tint-rose:#2A1E1D;--tint-violet:#251F2D;
}
html[data-appearance="dark"] body{background:#111614!important;background-image:none!important;color:#E9F0EC!important}
html[data-appearance="dark"] .tabs{background:#1A201D!important;box-shadow:none!important}
html[data-appearance="dark"] ::selection{background:rgba(94,143,135,.38)}
"""

COLOR_RE = re.compile(
    r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-fA-F])"
    r"|rgba?\([^()]*\)"
)

BG_PROPS = {
    "background", "background-color", "background-image",
}
BORDER_PROPS = {
    "border", "border-top", "border-right", "border-bottom", "border-left",
    "border-color", "border-top-color", "border-right-color", "border-bottom-color",
    "border-left-color", "outline", "outline-color", "column-rule", "column-rule-color",
    "text-decoration-color", "-webkit-text-stroke", "-webkit-text-stroke-color",
}
TEXT_PROPS = {"color", "caret-color", "fill", "stroke", "accent-color"}
SHADOW_PROPS = {"box-shadow", "text-shadow"}
# 不参与映射的属性（含颜色但不是主题色 / 会破坏布局或动画）
SKIP_PROPS = {
    "content", "background-size", "background-position", "background-repeat",
    "background-clip", "background-origin", "background-attachment", "transition",
    "transition-property", "animation", "font", "font-family", "filter", "transform",
    "grid-template-columns", "grid-template-rows", "flex", "gap", "width", "height",
    "min-width", "max-width", "min-height", "max-height", "box-shadow-none",
}


def _split_top(text, sep):
    out, buf, depth, quote = [], "", 0, ""
    for ch in text:
        if quote:
            buf += ch
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf += ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            out.append(buf)
            buf = ""
            continue
        buf += ch
    out.append(buf)
    return out


def _parse_color(tok):
    """返回 (r,g,b,a) 0..1 或 None。"""
    tok = tok.strip()
    if tok.startswith("#"):
        h = tok[1:]
        if len(h) == 3:
            r, g, b = (int(c * 2, 16) / 255.0 for c in h)
            a = 1.0
        elif len(h) == 4:
            r, g, b = (int(c * 2, 16) / 255.0 for c in h[:3])
            a = int(h[3] * 2, 16) / 255.0
        elif len(h) == 6:
            r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
            a = 1.0
        elif len(h) == 8:
            r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
            a = int(h[6:8], 16) / 255.0
        else:
            return None
        return r, g, b, a
    if tok.startswith(("rgb(", "rgba(")):
        body = tok[tok.index("(") + 1: tok.rindex(")")]
        parts = [p.strip() for p in body.split(",")]
        try:
            if len(parts) == 3:
                r, g, b = (float(p.replace("%", "")) / (255.0 if "%" not in p else 100.0) for p in parts)
                a = 1.0
            elif len(parts) == 4:
                r, g, b = (float(p.replace("%", "")) / (255.0 if "%" not in p else 100.0) for p in parts[:3])
                a = float(parts[3])
            else:
                return None
            return (min(1.0, max(0.0, r)), min(1.0, max(0.0, g)), min(1.0, max(0.0, b)), min(1.0, max(0.0, a)))
        except ValueError:
            return None
    return None


def _hls(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2.0
    if mx == mn:
        return 0.0, l, 0.0
    d = mx - mn
    s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h / 6.0, l, s


def _rgb(h, l, s):
    def f(n):
        k = (n + h * 12) % 12
        a = s * min(l, 1 - l)
        return l - a * max(-1, min(k - 3, 9 - k, 1))
    return f(0), f(8), f(4)


def _fmt(r, g, b, a=1.0):
    r = min(255, max(0, int(round(r * 255))))
    g = min(255, max(0, int(round(g * 255))))
    b = min(255, max(0, int(round(b * 255))))
    if a >= 0.999:
        return "#%02X%02X%02X" % (r, g, b)
    return "rgba(%d,%d,%d,%s)" % (r, g, b, ("%.3f" % a).rstrip("0").rstrip("."))


def _map_color(tok, role):
    c = _parse_color(tok)
    if c is None:
        return tok
    r, g, b, a = c
    if a < 0.02:
        return tok
    h, l, s = _hls(r, g, b)

    # ---- 阴影/高光 ----
    if role == "shadow":
        if l >= 0.78 and s < 0.30:
            return _fmt(1, 1, 1, min(0.16, a * 0.22))
        return tok

    # ---- 半透明色 ----
    if a < 0.995:
        if role == "bg":
            if l >= 0.80 and s < 0.35:  # 白色/亮色蒙层 → 深色主题下压成极淡白光
                return _fmt(1, 1, 1, min(0.14, a * 0.18))
            if l <= 0.32:  # 深色蒙层（遮罩）保留
                return _fmt(0, 0, 0, min(1.0, a * 1.06))
            nl = min(0.22, max(0.10, 0.10 + (1 - l) * 0.18))
            return _fmt(*_rgb(h, nl, min(s, 0.55)), a)
        if role == "border":
            if l >= 0.60:
                if s < 0.22:
                    return _fmt(1, 1, 1, min(0.20, a * 0.30))
                return _fmt(*_rgb(h, 0.30, min(s, 0.50)), min(a, 0.85))
            return tok
        if role == "text":
            if l <= 0.66:
                if s > 0.20:
                    return _fmt(*_rgb(h, min(0.80, 0.60 + (0.62 - l) * 0.30), min(s, 0.55)), a)
                return _fmt(*_rgb(h, min(0.94, 0.70 + (0.70 - l) * 0.45), min(s, 0.14)), a)
            return tok
        return tok

    # ---- 不透明色 ----
    if role == "bg":
        if l >= 0.80:
            return _fmt(*_rgb(h, 0.095 + (1 - l) * 0.26, min(s, 0.30)))
        if l >= 0.62:
            return _fmt(*_rgb(h, 0.16 + (0.80 - l) * 0.25, min(s, 0.35)))
        return tok
    if role == "border":
        if l >= 0.60:
            return _fmt(*_rgb(h, 0.21 + (1 - l) * 0.08, min(s, 0.35)))
        if l < 0.30:
            return _fmt(*_rgb(h, 0.26, min(s, 0.30)))
        return tok
    if role == "text":
        if l > 0.72:
            return tok
        if s > 0.20:
            return _fmt(*_rgb(h, min(0.80, 0.60 + (0.62 - l) * 0.30), min(s, 0.55)))
        return _fmt(*_rgb(h, min(0.94, 0.70 + (0.70 - l) * 0.45), min(s, 0.14)))
    return tok


def _role_of(prop):
    p = prop.strip().lower()
    if p.startswith("--"):
        n = p
        if re.search(r"(bg|background|card|surface|panel|tint|mint|fill)", n):
            return "bg"
        if re.search(r"(bd|border|line)", n):
            return "border"
        if re.search(r"(ink|text|fg|color|dim)", n):
            return "text"
        return "bg"
    if p in BG_PROPS:
        return "bg"
    if p in BORDER_PROPS:
        return "border"
    if p in TEXT_PROPS:
        return "text"
    if p in SHADOW_PROPS:
        return "shadow"
    return None


def _map_value(prop, value):
    role = _role_of(prop)
    if role is None:
        return None
    swapped = COLOR_RE.sub(lambda m: _map_color(m.group(0), role), value)
    return swapped if swapped != value else None


def _map_declarations(body):
    out = []
    for raw in _split_top(body, ";"):
        decl = raw.strip()
        if not decl or ":" not in decl:
            continue
        prop, val = decl.split(":", 1)
        prop = prop.strip()
        val = val.strip()
        if not prop or not val:
            continue
        if prop.lower() in SKIP_PROPS:
            continue
        important = ""
        if val.lower().endswith("!important"):
            val = val[:-len("!important")].strip()
            important = " !important"
        newval = _map_value(prop, val)
        if newval is None:
            continue
        out.append("%s:%s%s" % (prop, newval, important))
    return out


def _iter_rules(css):
    """遍历叶子规则：(context_at_rules, selector, body)。跳过 @keyframes/@font-face。"""
    def walk(text, ctx):
        i, start, n = 0, 0, len(text)
        while i < n:
            ch = text[i]
            if ch == "/" and text[i:i + 2] == "/*":
                j = text.find("*/", i + 2)
                i = (j + 2) if j >= 0 else n
                continue
            if ch == "{":
                prelude = text[start:i].strip()
                depth, j = 1, i + 1
                while j < n and depth:
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                    j += 1
                body = text[i + 1:j - 1]
                low = prelude.lower()
                if prelude.startswith("@"):
                    if low.startswith(("@media", "@supports")):
                        walk(body, ctx + [prelude])
                    # @keyframes/@font-face/@page 等跳过
                elif prelude:
                    yield ctx, prelude, body
                i, start = j, j
                continue
            if ch == "}":
                i += 1
                start = i
                continue
            i += 1
    yield from walk(css, [])


def _clean_selector(selector):
    """去掉选择器前后的 CSS 注释（扫描器会把注释留在 prelude 里）。"""
    return re.sub(r"/\*.*?\*/", "", selector, flags=re.S).strip()


def _prefix_selectors(selector):
    selector = _clean_selector(selector)
    parts = [p.strip() for p in _split_top(selector, ",") if p.strip()]
    out = []
    for p in parts:
        if "data-appearance" in p:
            return None
        if p in (":root", "html"):
            out.append(PREFIX)
        elif p.startswith("html "):
            out.append(PREFIX + p[4:])
        else:
            out.append(PREFIX + " " + p)
    return ", ".join(out)


def build_dark_css(css_text):
    """把一段浅色样式表映射成深色覆盖层（纯追加，不改原规则）。"""
    groups = {}  # (ctx_tuple, declarations_tuple) -> [selectors]

    def add(ctx, selector, decls):
        key = (tuple(ctx), tuple(decls))
        groups.setdefault(key, []).append(selector)

    for ctx, selector, body in _iter_rules(css_text):
        if any("print" in c.lower() for c in ctx):
            continue
        sel_clean = _clean_selector(selector)
        if not sel_clean or sel_clean == ":root":
            continue
        if "data-appearance" in sel_clean:
            continue
        decls = _map_declarations(body)
        if not decls:
            continue
        sel = _prefix_selectors(sel_clean)
        if not sel:
            continue
        add(ctx, sel, decls)

    lines = []
    for (ctx, decls), selectors in groups.items():
        ind = "  "
        if ctx:
            lines.append("\n".join(ctx) + "{")
            ind = "  "
        else:
            ind = ""
        lines.append(ind + ",\n".join(ind + s for s in selectors) + "{" + ";".join(decls) + "}")
        if ctx:
            lines.append("}")
    return "\n".join(lines) + "\n"


def main():
    html = INDEX.read_text(encoding="utf-8")
    if BEGIN not in html or END not in html:
        raise SystemExit("缺少 __DARK_THEME_BEGIN__/END 标记")
    s0 = html.index("<style>")
    se = html.index("</style>", s0)
    css = html[s0 + len("<style>"):se]
    # 去掉上一次生成的深色段与残留标记，避免递归映射/重复标记
    css = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), "", css, flags=re.S)
    css = css.replace(BEGIN, "").replace(END, "")
    css = css.rstrip() + "\n"  # 规范化尾部空行：保证重复生成字节级幂等
    dark = build_dark_css(css)
    block = "\n" + BEGIN + "\n" + dark + "\n" + DARK_MANUAL + END + "\n"
    out = html[:s0 + len("<style>")] + css + block + html[se:]
    INDEX.write_text(out, encoding="utf-8", newline="")
    print("light css:", len(css), "bytes; dark css:", len(dark), "bytes; index.html ->", len(out), "bytes")
    print("提示：通知 iframe 模板的深色覆盖由 build_notice_embed.py 调用 build_dark_css() 生成；")
    print("      改 NOTICE_DARK_MANUAL 或通知模板后需再跑：python build_notice_embed.py")


if __name__ == "__main__":
    sys.exit(main())
