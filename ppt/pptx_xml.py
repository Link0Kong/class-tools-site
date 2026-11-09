# -*- coding: utf-8 -*-
"""pptx_xml.py — PPTX 包结构解析 / step 规划 / 归一化 / 切换映射（纯函数，无 COM、无网络）

契约唯一真源：``web/ppt/CONTRACT.md``（§5 manifest、§6 渲染规格、§7 切换映射）。

本模块只放**可单测的纯逻辑**：

* presentation.xml 的 ``<p:sldSz cx cy>`` 页面尺寸（EMU）；
* slide 顺序（经 presentation.xml.rels 解析，不假设 slideN 等于第 N 页）；
* ``<p:pic>`` 内嵌视频/音频（``<a:videoFile r:link>`` / ``<a:audioFile r:link>``）与
  ``<a:xfrm>`` 热区归一化（0..1，相对整页）；
* PowerPoint 切换 ``PpEntryEffect`` 数值 → manifest ``tr/trd``；
* 动画效果列表 → 分步计划（每步的绝对可见性快照，含页 step 上限 12 的降级）；
* buildId（资产名+大小+manifest 摘要的 sha1 前 10 位）。

切换家族映射由真实 PowerPoint 探测得出（设置 EntryEffect 后 SaveCopyAs 解包读取
``<p:transition>`` 子元素），见 ``_TRANSITION_FAMILY`` 注释；与 CONTRACT §7 的家族
结论一致（fade/push/wipe/zoom/cover），仅个别"猜测区间"按实测修正：
push 实际是 3852–3855、zoom 是 3073/3074、cover 是 1281–1288、cut 按直切处理(none)。
"""
import hashlib
import json
import posixpath
import zipfile
from xml.etree import ElementTree as ET

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

NS = {"p": P_NS, "a": A_NS, "r": R_NS}

CLICK_TRIGGERS = (1, 4)          # 1=onClick, 4=onShapeClick（都推进一个 step）
AUTO_TRIGGERS = (2, 3)           # withPrevious / afterPrevious → 并入当前 step

DEFAULT_MAX_STEPS_PER_SLIDE = 12
DEFAULT_MAX_IMAGES = 260

# ---------------------------------------------------------------------------
# 切换映射（PpEntryEffect → manifest tr/trd）
# ---------------------------------------------------------------------------
# 实测（2026-11-09，本机 PowerPoint 16.0，写 EntryEffect 后读 OOXML <p:transition>）：
#   257/258/3844        -> cut          （直切）
#   1793, 3849          -> fade
#   1281..1288          -> cover
#   3852..3855          -> push
#   2817..2820, 2561..2564 -> wipe（2561 实为 strips，按 CONTRACT §7 归入 wipe）
#   3073..3074          -> zoom
#   1537 (dissolve) / 3954-3956 (morph) / 其它 -> 按 §7「未知按 fade」
# CONTRACT §7 给的区间是设计期估计；此处以实测为准，输出仍只落在 6 个约定值内。
_TRANSITION_FAMILY = {
    0: "none",
    257: "none",
    258: "none",
    3844: "none",
}
for _v in (1793, 3849):
    _TRANSITION_FAMILY[_v] = "fade"
for _v in range(1281, 1289):
    _TRANSITION_FAMILY[_v] = "cover"
for _v in range(3852, 3856):
    _TRANSITION_FAMILY[_v] = "push"
for _v in list(range(2817, 2821)) + list(range(2561, 2565)):
    _TRANSITION_FAMILY[_v] = "wipe"
for _v in (3073, 3074):
    _TRANSITION_FAMILY[_v] = "zoom"
# 剩余值（含 1537 dissolve、3954-3956 morph、各种 38xx 新切换）统一 fade
TRANSITION_FAMILIES = ("none", "fade", "push", "wipe", "zoom", "cover")
# trd：客户端动画时长建议（CONTRACT §5 示例 fade=450；与 PowerPoint Duration 默认 2s
# 解耦——PPT 默认时长会让网页切页发肉）
TRANSITION_DURATION_MS = {
    "none": 0,
    "fade": 450,
    "push": 400,
    "wipe": 420,
    "zoom": 380,
    "cover": 400,
}


class PptxParseError(Exception):
    """PPTX 包结构不符合预期（不是有效 pptx / 缺必需部件）。"""


def transition_family(entry_effect):
    """PpEntryEffect 数值 → CONTRACT §7 的 6 个值之一（未知/非法 → fade）。"""
    try:
        value = int(entry_effect)
    except (TypeError, ValueError):
        return "fade"
    if value < 0:
        return "fade"
    return _TRANSITION_FAMILY.get(value, "fade")


def map_transition(entry_effect):
    """返回 manifest 页切换字段：``{"tr": "fade", "trd": 450}``。"""
    family = transition_family(entry_effect)
    return {"tr": family, "trd": TRANSITION_DURATION_MS[family]}


# ---------------------------------------------------------------------------
# zip / xml 基础
# ---------------------------------------------------------------------------
def open_zip(path_or_zip):
    """接受路径或已打开的 ZipFile，统一返回 (ZipFile, owned)。"""
    if isinstance(path_or_zip, zipfile.ZipFile):
        return path_or_zip, False
    try:
        return zipfile.ZipFile(path_or_zip), True
    except (OSError, zipfile.BadZipFile) as exc:
        raise PptxParseError("不是有效的 pptx/zip：%s" % exc.__class__.__name__)


def _read_xml(zf, name):
    try:
        data = zf.read(name)
    except KeyError:
        raise PptxParseError("缺少部件：%s" % name)
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise PptxParseError("XML 解析失败 %s：%s" % (name, exc))


def _read_rels(zf, part_name):
    """读取部件的关系表；返回 {rId: {"type":..., "target":..., "external":bool}}。"""
    folder, fname = posixpath.split(part_name)
    rels_name = posixpath.join(folder, "_rels", fname + ".rels")
    try:
        root = _read_xml(zf, rels_name)
    except PptxParseError:
        return {}
    out = {}
    for rel in root:
        rid = rel.get("Id")
        if not rid:
            continue
        out[rid] = {
            "type": rel.get("Type") or "",
            "target": rel.get("Target") or "",
            "external": (rel.get("TargetMode") or "").lower() == "external",
        }
    return out


def slide_part_names(zf):
    """按 presentation.xml 的 sldIdLst 顺序返回 slide 部件名（如 ppt/slides/slide1.xml）。"""
    pres = _read_xml(zf, "ppt/presentation.xml")
    rels = _read_rels(zf, "ppt/presentation.xml")
    names = []
    for sld_id in pres.iter("{%s}sldId" % P_NS):
        rid = sld_id.get("{%s}id" % R_NS)
        if not rid:
            continue
        rel = rels.get(rid)
        if not rel or rel["external"]:
            continue
        target = rel["target"]
        name = posixpath.normpath(posixpath.join("ppt", target))
        names.append(name)
    if names:
        return names
    # 兜底：按 slideN.xml 数字排序
    found = [n for n in zf.namelist()
             if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
    return sorted(found, key=lambda s: int("".join(ch for ch in posixpath.basename(s)
                                                   if ch.isdigit()) or 0))


def read_slide_size(zf_or_path):
    """返回页面 EMU 尺寸 ``(cx, cy)``。"""
    zf, owned = open_zip(zf_or_path)
    try:
        pres = _read_xml(zf, "ppt/presentation.xml")
        sld_sz = pres.find("{%s}sldSz" % P_NS)
        if sld_sz is None:
            raise PptxParseError("presentation.xml 缺少 p:sldSz")
        try:
            cx = int(sld_sz.get("cx"))
            cy = int(sld_sz.get("cy"))
        except (TypeError, ValueError):
            raise PptxParseError("p:sldSz cx/cy 非法")
        if cx <= 0 or cy <= 0:
            raise PptxParseError("p:sldSz 尺寸非正数")
        return cx, cy
    finally:
        if owned:
            zf.close()


# ---------------------------------------------------------------------------
# 媒体（视频/音频）解析
# ---------------------------------------------------------------------------
def _parse_xfrm(pic):
    """从 <p:pic> 取 <a:xfrm> 的 off/ext（EMU）；缺失返回 None。"""
    xfrm = pic.find("./p:spPr/a:xfrm", NS)
    if xfrm is None:
        # 少数包把 xfrm 放在 mc:AlternateContent 里
        for el in pic.iter("{%s}xfrm" % A_NS):
            xfrm = el
            break
    if xfrm is None:
        return None
    off = xfrm.find("{%s}off" % A_NS)
    ext = xfrm.find("{%s}ext" % A_NS)
    if off is None or ext is None:
        return None
    try:
        return {
            "x": int(off.get("x")),
            "y": int(off.get("y")),
            "cx": int(ext.get("cx")),
            "cy": int(ext.get("cy")),
        }
    except (TypeError, ValueError):
        return None


def _pic_name(pic):
    c_nv_pr = pic.find("./p:nvPicPr/p:cNvPr", NS)
    if c_nv_pr is not None and c_nv_pr.get("name") is not None:
        return c_nv_pr.get("name")
    return ""


def _media_kind_from_type(rel_type):
    t = (rel_type or "").lower()
    if t.endswith("/video"):
        return "v"
    if t.endswith("/audio"):
        return "a"
    return ""


def read_media_shapes(zf_or_path):
    """解析每页的内嵌视频/音频占位图片。

    返回 list（按页顺序）：
    ``{"slide": 1-based 页号, "name": pic 名, "kind": "v"|"a", "r_id": ..., 
       "media": 包内相对名(如 media1.mp4) 或外链 URL, "external": bool,
       "rect": {"x","y","w","h"} 0..1 归一化 或 None, "xfrm": {...EMU...}}``

    只解析**内嵌媒体**的 xfrm；``TargetMode="External"`` 的记录 external=True，
    由调用方跳过（CONTRACT §6：外链跳过不报错）。
    """
    zf, owned = open_zip(zf_or_path)
    try:
        slide_w, slide_h = read_slide_size(zf)
        out = []
        slide_names = slide_part_names(zf)
        for idx, part in enumerate(slide_names, start=1):
            rels = _read_rels(zf, part)
            try:
                root = _read_xml(zf, part)
            except PptxParseError:
                continue
            for pic in root.iter("{%s}pic" % P_NS):
                kind = ""
                rid = ""
                for tag, k in (("videoFile", "v"), ("audioFile", "a")):
                    node = pic.find(".//{%s}%s" % (A_NS, tag))
                    if node is None:
                        # audioFile/videoFile 在 p:nvPr 下，命名空间是 a:
                        node = pic.find(".//{%s}%s" % (P_NS, tag))
                    if node is not None:
                        rid = node.get("{%s}link" % R_NS) or ""
                        kind = k
                        break
                if not kind or not rid:
                    continue
                rel = rels.get(rid) or {}
                external = bool(rel.get("external"))
                target = rel.get("target") or ""
                if external:
                    media = target
                else:
                    media = posixpath.basename(target)
                xfrm = _parse_xfrm(pic)
                rect = None
                if xfrm is not None:
                    rect = normalize_rect(xfrm["x"], xfrm["y"], xfrm["cx"], xfrm["cy"],
                                          slide_w, slide_h)
                out.append({
                    "slide": idx,
                    "name": _pic_name(pic),
                    "kind": kind,
                    "r_id": rid,
                    "media": media,
                    "external": external,
                    "rect": rect,
                    "xfrm": xfrm,
                })
        return out
    finally:
        if owned:
            zf.close()


def read_media_bytes(zf_or_path, media_name):
    """读取 ``ppt/media/<media_name>`` 原始字节；找不到返回 None。"""
    zf, owned = open_zip(zf_or_path)
    try:
        wanted = posixpath.basename(media_name)
        for name in zf.namelist():
            if name.startswith("ppt/media/") and posixpath.basename(name) == wanted:
                return zf.read(name)
        return None
    finally:
        if owned:
            zf.close()


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
def normalize_rect(x_emu, y_emu, cx_emu, cy_emu, slide_cx, slide_cy, digits=4):
    """EMU 矩形 → 相对整页的 0..1 归一化（clamp 到页内，保底正宽高）。"""
    try:
        slide_cx = float(slide_cx)
        slide_cy = float(slide_cy)
        if slide_cx <= 0 or slide_cy <= 0:
            raise ValueError("slide size")
        x = float(x_emu) / slide_cx
        y = float(y_emu) / slide_cy
        w = float(cx_emu) / slide_cx
        h = float(cy_emu) / slide_cy
    except (TypeError, ValueError, ZeroDivisionError):
        raise PptxParseError("矩形/页面尺寸非法")
    # 负宽高（极少见，翻转）取绝对值
    w = abs(w)
    h = abs(h)
    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    w = min(max(w, 0.0), 1.0 - x)
    h = min(max(h, 0.0), 1.0 - y)
    if w <= 0 or h <= 0:
        # 退化为整页，保证热点可见
        x, y, w, h = 0.0, 0.0, 1.0, 1.0
    r = lambda v: round(v, digits)  # noqa: E731
    return {"x": r(x), "y": r(y), "w": r(w), "h": r(h)}


def render_target(slide_width_pt, slide_height_pt, display_width=1600):
    """页面尺寸（pt）→ 渲染像素 (w, h)：宽=display_width，最长边不超过 display_width。"""
    try:
        wpt = float(slide_width_pt)
        hpt = float(slide_height_pt)
    except (TypeError, ValueError):
        raise PptxParseError("页面宽高非法")
    if wpt <= 0 or hpt <= 0:
        raise PptxParseError("页面宽高非正数")
    w = int(display_width)
    h = max(1, int(round(display_width * hpt / wpt)))
    if max(w, h) > display_width:
        scale = float(display_width) / float(max(w, h))
        w = max(1, int(round(w * scale)))
        h = max(1, int(round(h * scale)))
    return w, h


def aspect_label(w_px, h_px):
    """渲染宽高 → CONTRACT §3.1 aspect 文本（16:9 / 4:3 / 其他比例文字）。"""
    try:
        ratio = float(w_px) / float(h_px)
    except (TypeError, ValueError, ZeroDivisionError):
        return "其他"
    if abs(ratio - 16.0 / 9.0) < 0.01:
        return "16:9"
    if abs(ratio - 4.0 / 3.0) < 0.01:
        return "4:3"
    return "%.2f:1" % ratio


# ---------------------------------------------------------------------------
# step 规划
# ---------------------------------------------------------------------------
def _norm_effect(raw):
    """把 COM/测试输入的动画效果统一成内部结构。"""
    get = raw.get if isinstance(raw, dict) else lambda k, d=None: getattr(raw, k, d)
    try:
        shape_id = int(get("shape_id"))
    except (TypeError, ValueError):
        shape_id = -1
    try:
        trigger = int(get("trigger") or 0)
    except (TypeError, ValueError):
        trigger = 0
    try:
        effect_type = int(get("effect_type") or 0)
    except (TypeError, ValueError):
        effect_type = 0
    return {
        "i": int(get("i") or 0),
        "shape_id": shape_id,
        "shape_name": str(get("shape_name") or ""),
        "exit": bool(get("exit")),
        "trigger": trigger,
        "effect_type": effect_type,
        "duration": float(get("duration") or 0.0),
    }


def _is_visibility_effect(effect):
    """入场/退场改变可见性；强调动画（Exit=False 且 EffectType>=54）不改。"""
    if effect["exit"]:
        return True
    return effect["effect_type"] < 54  # MsoAnimEffect 入场家族 1..53


def plan_steps(effects, max_steps=DEFAULT_MAX_STEPS_PER_SLIDE):
    """把一页的动画效果列表规划成「点击步」序列。

    返回::

        {
          "steps": [                       # 至少 1 步（默认画面）
            {"index": 0, "effects": [...], "visible": {shape_id: bool}, "truncated_tail": False},
            ...
          ],
          "animated_ids": [shape_id...],   # 需要被 Visible 控制的形状
          "initial_visible": {shape_id: bool},
          "final_visible": {shape_id: bool},
          "truncated": bool,               # 是否触发页 step 上限降级
        }

    * 每步的 ``visible`` 是**该步渲染时的绝对可见性**（覆盖本页所有动画形状），
      渲染器只需按它设置 ``Shape.Visible`` 后导出，不依赖逐步 delta 推理。
    * trigger==1/4（单击/点形状）开新 step；2/3（与上一动画同时/之后）并入当前 step；
    * 第一步（默认画面）之前 trigger 2/3 的自动效果直接计入第 0 步；
    * 页 step 超过 ``max_steps`` 时：保留前 max_steps-1 步 + 末步定格为最终完整画面，
      内容不丢（末步展示全部最终可见形状）。
    """
    norm = [_norm_effect(e) for e in (effects or [])]
    norm.sort(key=lambda e: (e["i"], e["shape_id"]))
    animated = []
    for e in norm:
        if e["shape_id"] >= 0 and e["shape_id"] not in animated:
            animated.append(e["shape_id"])

    initial = {}
    for sid in animated:
        initial[sid] = True
    # 该形状的「首个效果」若是单击入场 → 初始隐藏（等点击才出现）
    seen = set()
    for e in norm:
        sid = e["shape_id"]
        if sid < 0 or sid in seen:
            continue
        seen.add(sid)
        if _is_visibility_effect(e) and not e["exit"] and e["trigger"] in CLICK_TRIGGERS:
            initial[sid] = False

    state = dict(initial)
    steps = [{"index": 0, "effects": [], "visible": dict(state)}]
    cur = 0
    for e in norm:
        if e["trigger"] in CLICK_TRIGGERS:
            cur = len(steps)
            steps.append({"index": cur, "effects": [], "visible": dict(state)})
        step = steps[cur]
        step["effects"].append({
            "i": e["i"], "shape_id": e["shape_id"], "shape_name": e["shape_name"],
            "exit": e["exit"], "trigger": e["trigger"], "effect_type": e["effect_type"],
        })
        sid = e["shape_id"]
        if sid >= 0 and _is_visibility_effect(e):
            state[sid] = not e["exit"]
        step["visible"] = dict(state)

    final_state = dict(state)
    truncated = False
    if max_steps and len(steps) > int(max_steps):
        keep = max(1, int(max_steps) - 1)
        steps = steps[:keep]
        last = {"index": len(steps), "effects": [], "visible": dict(final_state),
                "truncated_tail": True}
        steps.append(last)
        truncated = True
    return {
        "steps": steps,
        "animated_ids": animated,
        "initial_visible": initial,
        "final_visible": final_state,
        "truncated": truncated,
    }


def degrade_plan(steps, keep):
    """页 step 上限/整份资产上限下调时，把某页压缩成 ``keep`` 步（1 或 2）。

    * ``keep>=2``：保留第 0 步（默认画面）+ 末步（最终完整画面）；
    * ``keep==1``：只保留末步（最终完整画面，内容全在）。
    """
    steps = list(steps or [])
    if not steps:
        return []
    keep = int(keep)
    if keep <= 1:
        last = dict(steps[-1])
        last["index"] = 0
        last["truncated_tail"] = True
        return [last]
    if len(steps) <= keep:
        return steps
    out = [dict(steps[0])]
    last = dict(steps[-1])
    last["truncated_tail"] = True
    out.append(last)
    for i, st in enumerate(out):
        st = dict(st)
        st["index"] = i
    out[0]["index"] = 0
    out[-1]["index"] = 1
    return out


# ---------------------------------------------------------------------------
# buildId / manifest 校验
# ---------------------------------------------------------------------------
def compute_build_id(assets, manifest):
    """buildId = sha1(排序后的资产名+大小 + manifest 摘要)[:10]。

    ``manifest`` 里的 ``base`` 依赖 buildId，所以传入的 manifest 通常先置空
    ``base``（本函数只对 ``build`` 字段之外的内容做摘要，调用方保持一致即可）。
    """
    h = hashlib.sha1()
    rows = sorted(((str(a.get("name") or ""), int(a.get("size") or 0)) for a in assets or []))
    for name, size in rows:
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        h.update(str(size).encode("ascii"))
        h.update(b"\x00")
    digest_src = dict(manifest or {})
    digest_src.pop("base", None)
    h.update(json.dumps(digest_src, sort_keys=True, ensure_ascii=False,
                        separators=(",", ":")).encode("utf-8"))
    return h.hexdigest()[:10]


def validate_manifest(manifest):
    """校验 CONTRACT §5 的 manifest 结构，返回错误字符串列表（空 = 合法）。"""
    errors = []
    if not isinstance(manifest, dict):
        return ["manifest 不是对象"]
    if manifest.get("v") != 1:
        errors.append("v 必须为 1")
    if not isinstance(manifest.get("base"), str) or not manifest.get("base"):
        errors.append("base 必须是非空字符串")
    for key in ("w", "h"):
        if not isinstance(manifest.get(key), int) or manifest.get(key) <= 0:
            errors.append("%s 必须是正整数" % key)
    slides = manifest.get("slides")
    if not isinstance(slides, list) or not slides:
        return errors + ["slides 必须是非空数组"]
    media_table = manifest.get("media") or []
    if not isinstance(media_table, list):
        errors.append("media 必须是数组")
        media_table = []
    media_names = {m.get("s") for m in media_table if isinstance(m, dict)}
    for i, slide in enumerate(slides):
        if not isinstance(slide, dict):
            errors.append("slides[%d] 不是对象" % i)
            continue
        if slide.get("tr") not in TRANSITION_FAMILIES:
            errors.append("slides[%d].tr 非法：%r" % (i, slide.get("tr")))
        trd = slide.get("trd")
        if not isinstance(trd, (int, float)) or trd < 0:
            errors.append("slides[%d].trd 非法" % i)
        if not isinstance(slide.get("notes", ""), str):
            errors.append("slides[%d].notes 必须是字符串" % i)
        thumb = slide.get("thumb")
        if not isinstance(thumb, str) or not thumb:
            errors.append("slides[%d].thumb 必须是非空字符串" % i)
        steps = slide.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append("slides[%d].steps 必须是非空数组" % i)
            continue
        for j, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append("slides[%d].steps[%d] 不是对象" % (i, j))
                continue
            if not isinstance(step.get("img"), str) or not step.get("img"):
                errors.append("slides[%d].steps[%d].img 非法" % (i, j))
            for h in step.get("media") or []:
                if not isinstance(h, dict):
                    errors.append("slides[%d].steps[%d].media 项不是对象" % (i, j))
                    continue
                if h.get("s") not in media_names:
                    errors.append("slides[%d].steps[%d].media.s 未在全局 media 表" % (i, j))
                if h.get("k") not in ("v", "a"):
                    errors.append("slides[%d].steps[%d].media.k 非法" % (i, j))
                for c in ("x", "y", "w", "h"):
                    v = h.get(c)
                    if not isinstance(v, (int, float)) or not (0.0 <= float(v) <= 1.0):
                        errors.append("slides[%d].steps[%d].media.%s 越界" % (i, j, c))
    for k, m in enumerate(media_table):
        if not isinstance(m, dict):
            errors.append("media[%d] 不是对象" % k)
            continue
        if not isinstance(m.get("s"), str) or not m.get("s"):
            errors.append("media[%d].s 非法" % k)
        if m.get("k") not in ("v", "a"):
            errors.append("media[%d].k 非法" % k)
    return errors
