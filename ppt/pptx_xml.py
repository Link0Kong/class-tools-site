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
* buildId（资产名+大小+manifest 摘要的 sha1 前 10 位）；
* **v1.2 原样播放视频**（CONTRACT §11.1/§11.2）纯计算：动画结束时间 ``anim_end``、
  每页 ``advance``、章节时间 ``chapters``、页数/时长上限判断、ffprobe JSON 解析、
  ``manifest.video`` 校验；
* **v2.0 compat**（CONTRACT §12.2）：下载文件名清洗、包内媒体 sha256 图/集合、
  外链媒体告警（页/kind/路径尾）、``manifest.files/compat`` 校验。

切换家族映射由真实 PowerPoint 探测得出（设置 EntryEffect 后 SaveCopyAs 解包读取
``<p:transition>`` 子元素），见 ``_TRANSITION_FAMILY`` 注释；与 CONTRACT §7 的家族
结论一致（fade/push/wipe/zoom/cover），仅个别"猜测区间"按实测修正：
push 实际是 3852–3855、zoom 是 3073/3074、cover 是 1281–1288、cut 按直切处理(none)。
"""
import hashlib
import json
import os
import posixpath
import re
import urllib.parse
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
    """校验 CONTRACT §5/§11/§12 的 manifest 结构，返回错误字符串列表（空 = 合法）。

    * ``v=1``（旧 deck）：slides 非空；files 若存在（v2.0 为旧 deck 补 compat）也校验；
    * ``v=2``（compat 新 deck）：``files.compat`` + ``files.pdf`` 必须存在；slides 可为空数组；
    * ``video`` 可选（仅旧 deck/旧模式）。
    """
    errors = []
    if not isinstance(manifest, dict):
        return ["manifest 不是对象"]
    version = manifest.get("v")
    if version not in (1, 2):
        errors.append("v 必须为 1 或 2")
    is_compat = version == 2
    if not isinstance(manifest.get("base"), str) or not manifest.get("base"):
        errors.append("base 必须是非空字符串")
    for key in ("w", "h"):
        if not isinstance(manifest.get(key), int) or manifest.get(key) <= 0:
            errors.append("%s 必须是正整数" % key)
    slides = manifest.get("slides")
    if slides is None and is_compat:
        slides = []
    if not isinstance(slides, list):
        return errors + ["slides 必须是数组"]
    if not slides and not is_compat:
        return errors + ["slides 必须是非空数组"]
    files = manifest.get("files")
    if files is not None:
        errors.extend(validate_files(files))
    elif is_compat:
        errors.append("compat(v2) manifest 必须包含 files")
    if is_compat and isinstance(files, dict):
        if not isinstance(files.get("compat"), dict):
            errors.append("compat(v2) manifest 必须包含 files.compat")
        if not isinstance(files.get("pdf"), dict):
            errors.append("compat(v2) manifest 必须包含 files.pdf")
    compat = manifest.get("compat")
    if compat is not None:
        if not isinstance(compat, dict):
            errors.append("compat 必须是对象")
        else:
            warnings = compat.get("warnings")
            if warnings is not None and not isinstance(warnings, list):
                errors.append("compat.warnings 必须是数组")
            if not isinstance(compat.get("fonts_embedded", 0), int):
                errors.append("compat.fonts_embedded 必须是整数")
            repairs = compat.get("repairs")
            if repairs is not None:
                if not isinstance(repairs, list):
                    errors.append("compat.repairs 必须是数组")
                else:
                    for k, item in enumerate(repairs):
                        if not isinstance(item, dict):
                            errors.append("compat.repairs[%d] 必须是对象" % k)
                            continue
                        if not isinstance(item.get("slide"), int) or item["slide"] < 1:
                            errors.append("compat.repairs[%d].slide 必须是正整数" % k)
                        if not isinstance(item.get("media"), str) or not item["media"]:
                            errors.append("compat.repairs[%d].media 必须是非空字符串" % k)
                        if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
                            errors.append("compat.repairs[%d].bytes 必须是正整数" % k)
            media_actions = compat.get("media_actions")
            if media_actions is not None:
                if not isinstance(media_actions, list):
                    errors.append("compat.media_actions 必须是数组")
                else:
                    for k, item in enumerate(media_actions):
                        if not isinstance(item, dict):
                            errors.append("compat.media_actions[%d] 必须是对象" % k)
                            continue
                        if not isinstance(item.get("file"), str) or not item["file"]:
                            errors.append("compat.media_actions[%d].file 必须是非空字符串" % k)
                        if item.get("kind") not in ("video", "audio"):
                            errors.append("compat.media_actions[%d].kind 必须是 video/audio" % k)
                        if item.get("action") not in ("keep", "remux", "transcode"):
                            errors.append("compat.media_actions[%d].action 非法" % k)
                        for key in ("bytes_before", "bytes_after"):
                            value = item.get(key)
                            if not isinstance(value, int) or value < 0:
                                errors.append("compat.media_actions[%d].%s 必须是非负整数"
                                              % (k, key))
                        if not isinstance(item.get("lossless"), bool):
                            errors.append("compat.media_actions[%d].lossless 必须是布尔值" % k)
            media_summary = compat.get("media_summary")
            if media_summary is not None:
                if not isinstance(media_summary, dict):
                    errors.append("compat.media_summary 必须是对象")
                else:
                    for key in ("total", "kept", "remux", "transcode"):
                        value = media_summary.get(key)
                        if not isinstance(value, int) or value < 0:
                            errors.append("compat.media_summary.%s 必须是非负整数" % key)
    media_files = manifest.get("media_files")
    if media_files is not None:
        if not isinstance(media_files, list):
            errors.append("media_files 必须是数组")
        else:
            seen_names = set()
            for k, item in enumerate(media_files):
                if not isinstance(item, dict):
                    errors.append("media_files[%d] 必须是对象" % k)
                    continue
                rel = item.get("s")
                if not isinstance(rel, str) or not rel.startswith("media/"):
                    errors.append("media_files[%d].s 必须以 media/ 开头" % k)
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    errors.append("media_files[%d].name 必须是非空字符串" % k)
                elif "/" in name or "\\" in name:
                    errors.append("media_files[%d].name 不能包含路径分隔符" % k)
                elif name in seen_names:
                    errors.append("media_files[%d].name 重复" % k)
                else:
                    seen_names.add(name)
                size = item.get("size")
                if not isinstance(size, int) or size <= 0:
                    errors.append("media_files[%d].size 必须是正整数" % k)
                sha = item.get("sha256")
                if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                    errors.append("media_files[%d].sha256 必须是 64 位十六进制" % k)
                if item.get("kind") not in ("video", "audio"):
                    errors.append("media_files[%d].kind 必须是 video/audio" % k)
                media_slides = item.get("slides")
                if (not isinstance(media_slides, list) or not media_slides
                        or any(not isinstance(x, int) or x < 1 for x in media_slides)):
                    errors.append("media_files[%d].slides 必须是非空正整数数组" % k)
                elif media_slides != sorted(set(media_slides)):
                    errors.append("media_files[%d].slides 必须去重升序" % k)
                dur = item.get("dur")
                if dur is not None and (not isinstance(dur, (int, float)) or dur < 0):
                    errors.append("media_files[%d].dur 必须是非负数" % k)
                for key in ("w", "h"):
                    value = item.get(key)
                    if value is not None and (not isinstance(value, int) or value < 0):
                        errors.append("media_files[%d].%s 必须是非负整数" % (k, key))
                src_name = item.get("src")
                if src_name is not None and not isinstance(src_name, str):
                    errors.append("media_files[%d].src 必须是字符串" % k)
    if not slides:
        # compat 新 deck 无分步 slides：跳过逐页校验，只校验可选 video
        video = manifest.get("video")
        if video is not None:
            errors.extend(validate_video(video, None))
        return errors
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
    # v1.2：manifest.video 是可选字段（缺失=仅分步模式，旧客户端忽略；不得报错）
    video = manifest.get("video")
    if video is not None:
        slide_total = len(slides) if isinstance(slides, list) else None
        errors.extend(validate_video(video, slide_total))
    return errors


# ---------------------------------------------------------------------------
# v1.2 原样播放视频（PowerPoint CreateVideo）纯计算
# ---------------------------------------------------------------------------
VIDEO_MIN_ADVANCE_S = 3.0        # 每页最短停留（没动画的页也留 3s，便于观看/章节跳转）
VIDEO_ADVANCE_PAD_S = 1.5        # 动画/媒体结束后留白，避免章节边界贴边
VIDEO_MAX_ADVANCE_S = 600.0      # 单页最长 10min（超长媒体页按 600s 截断）
VIDEO_MAX_SLIDES = 120           # 页数上限（超过不生成原样播放视频，契约 §11.2.2）
VIDEO_MAX_DURATION_S = 1800.0    # 预估总时长上限 30min
VIDEO_TAG_DEFAULT = "720p"


def compute_anim_end(effects):
    """按 ``TimeLine.MainSequence`` 顺序估算一页动画全部结束的时间（秒）。

    * ``trigger`` 1（单击）/ 4（点形状）/ 3（上一动画之后）：串行，
      ``start = prevEnd + TriggerDelayTime``、``end = start + Duration``；
    * ``trigger`` 2（与上一动画同时）：与上一个串行效果并行（``start = groupStart + delay``），
      结束时间取 ``max(prevEnd, start + Duration)``。
    """
    prev_end = 0.0
    group_start = 0.0
    has_prev = False
    for raw in effects or []:
        get = raw.get if isinstance(raw, dict) else (lambda k, d=None: getattr(raw, k, d))
        try:
            trigger = int(get("trigger") or 0)
        except (TypeError, ValueError):
            trigger = 0
        try:
            duration = max(0.0, float(get("duration") or 0.0))
        except (TypeError, ValueError):
            duration = 0.0
        try:
            delay = max(0.0, float(get("delay") or 0.0))
        except (TypeError, ValueError):
            delay = 0.0
        if trigger == 2 and has_prev:
            end = group_start + delay + duration
            if end > prev_end:
                prev_end = end
        else:
            start = prev_end + delay
            prev_end = start + duration
            group_start = start
            has_prev = True
    return round(prev_end, 3)


def compute_advance(anim_end, media_max_dur, min_s=VIDEO_MIN_ADVANCE_S,
                    pad_s=VIDEO_ADVANCE_PAD_S, max_s=VIDEO_MAX_ADVANCE_S):
    """每页自动换页时长（秒）：``clamp(max(3.0, animEnd+1.5, mediaMaxDur+1.5), 3.0, 600)``。"""
    try:
        anim = float(anim_end or 0.0)
    except (TypeError, ValueError):
        anim = 0.0
    try:
        media = float(media_max_dur or 0.0)
    except (TypeError, ValueError):
        media = 0.0
    advance = max(float(min_s), anim + float(pad_s), media + float(pad_s))
    return round(max(float(min_s), min(advance, float(max_s))), 3)


def slide_media_max_dur(slide_count, hotspots, media_table):
    """每页内嵌媒体最长时长（秒）：hotspots 引用 ``media_table`` 的 ``dur``，同页取 max。

    ``hotspots`` 结构同 ``convert._extract_media_assets``：
    ``[(slide_idx0, step_idx, {"s": "m0.mp4", ...}), ...]``。
    """
    durations = {}
    for item in media_table or []:
        try:
            durations[str(item.get("s"))] = float(item.get("dur") or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
    count = max(0, int(slide_count or 0))
    out = [0.0] * count
    for entry in hotspots or []:
        try:
            slide_idx0 = int(entry[0])
            hotspot = entry[2]
            dur = durations.get(str(hotspot.get("s")), 0.0)
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
        if 0 <= slide_idx0 < count and dur > out[slide_idx0]:
            out[slide_idx0] = dur
    return out


def compute_chapters(advances, trans_durs, dur):
    """章节时间列表（秒，与页数等长）。

    ``chapters[0].t = 0``；``i>0`` 时
    ``t_i = Σ_{j<i} advance_j + Σ_{j<=i} transDur_j``，
    再 clamp 到 ``[0, dur-0.1]`` 且单调不减；计算值超出实测 ``dur`` 时按比例整体压缩。

    PowerPoint 把切换时长插在页之间：``视频总时长 ≈ Σadvance + Σtrans``
    （CONTRACT §11.2 探测结论）。
    """
    advances = [max(0.0, float(a or 0.0)) for a in (advances or [])]
    count = len(advances)
    if count <= 0:
        return []
    trans = []
    for i in range(count):
        try:
            trans.append(max(0.0, float((trans_durs or [])[i] or 0.0)))
        except (IndexError, TypeError, ValueError):
            trans.append(0.0)
    raw = []
    advance_sum = 0.0
    trans_sum = 0.0
    for i in range(count):
        if i > 0:
            advance_sum += advances[i - 1]
        trans_sum += trans[i]
        raw.append(advance_sum + trans_sum)
    try:
        total = float(dur or 0.0)
    except (TypeError, ValueError):
        total = 0.0
    limit = max(0.0, total - 0.1) if total > 0 else None
    if limit is not None and raw[-1] > limit and raw[-1] > 0:
        scale = limit / raw[-1]
        raw = [value * scale for value in raw]
    out = []
    prev = 0.0
    for i, value in enumerate(raw):
        t = 0.0 if i == 0 else float(value)
        if limit is not None:
            t = min(t, limit)
        if t < prev:
            t = prev
        out.append(round(t, 2))
        prev = t
    return out


def video_skip_reason(slide_count, estimated_duration_s,
                      max_slides=VIDEO_MAX_SLIDES,
                      max_duration_s=VIDEO_MAX_DURATION_S):
    """页数/预估时长超限 → 中文原因（空串=可用）。"""
    try:
        count = int(slide_count or 0)
    except (TypeError, ValueError):
        count = 0
    if count > int(max_slides):
        return "页数超限（%d 页 > %d 页），未生成原样播放视频" % (count, int(max_slides))
    try:
        total = float(estimated_duration_s or 0.0)
    except (TypeError, ValueError):
        total = 0.0
    if total > float(max_duration_s):
        return "预估时长超限（%.0fs > %.0fs），未生成原样播放视频" % (total, float(max_duration_s))
    return ""


def parse_ffprobe_json(text):
    """ffprobe ``-show_streams -show_format -of json`` 输出 → 规范化媒体信息。

    返回 ``{"w","h","dur","codec","has_audio","audio_codec","nb_streams"}``；
    解析失败返回 ``None``。
    """
    try:
        data = json.loads(text or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    streams = data.get("streams") or []
    if not isinstance(streams, list):
        streams = []
    video = {}
    audio = {}
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        kind = str(stream.get("codec_type") or "")
        if kind == "video" and not video:
            video = stream
        elif kind == "audio" and not audio:
            audio = stream

    def _num(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _int(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    fmt = data.get("format") or {}
    if not isinstance(fmt, dict):
        fmt = {}
    fps = 0.0
    for frac in (str(video.get("avg_frame_rate") or ""),
                 str(video.get("r_frame_rate") or "")):
        try:
            num, _, den = frac.partition("/")
            den_f = float(den or 1)
            if den_f:
                fps = round(float(num) / den_f, 3)
                break
        except (TypeError, ValueError):
            continue
    return {
        "w": _int(video.get("width")),
        "h": _int(video.get("height")),
        "dur": _num(fmt.get("duration")),
        "codec": str(video.get("codec_name") or ""),
        "has_audio": bool(audio),
        "audio_codec": str(audio.get("codec_name") or ""),
        "nb_streams": len(streams),
        # v2.2 媒体编码兼容补充字段（不改变旧调用语义）
        "format_name": str(fmt.get("format_name") or ""),
        "format_long_name": str(fmt.get("format_long_name") or ""),
        "bit_rate": _int(fmt.get("bit_rate")),
        "audio_bit_rate": _int(audio.get("bit_rate")),
        "audio_channels": _int(audio.get("channels")),
        "fps": fps,
        "profile": str(video.get("profile") or ""),
    }


def validate_video(video, slide_count=None):
    """校验 CONTRACT §11.1 的 ``manifest.video``，返回错误字符串列表（空 = 合法）。"""
    errors = []
    if not isinstance(video, dict):
        return ["video 必须是对象"]
    name = video.get("s")
    if not isinstance(name, str) or not name:
        errors.append("video.s 必须是非空字符串")
    for key in ("w", "h"):
        value = video.get(key)
        if not isinstance(value, int) or value <= 0:
            errors.append("video.%s 必须是正整数" % key)
    dur = video.get("dur")
    dur_ok = isinstance(dur, (int, float)) and float(dur) > 0
    if not dur_ok:
        errors.append("video.dur 必须是正数")
    if video.get("q") is not None and not isinstance(video.get("q"), str):
        errors.append("video.q 必须是字符串")
    chapters = video.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        errors.append("video.chapters 必须是非空数组")
        return errors
    if slide_count is not None and len(chapters) != int(slide_count):
        errors.append("video.chapters 数量（%d）必须等于页数（%d）"
                      % (len(chapters), int(slide_count)))
    prev_t = -1.0
    for k, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            errors.append("video.chapters[%d] 不是对象" % k)
            continue
        if chapter.get("i") != k:
            errors.append("video.chapters[%d].i 必须等于下标 %d" % (k, k))
        value = chapter.get("t")
        if not isinstance(value, (int, float)):
            errors.append("video.chapters[%d].t 必须是数字" % k)
            continue
        t = float(value)
        if t < 0:
            errors.append("video.chapters[%d].t 不能为负" % k)
        if k == 0 and t != 0:
            errors.append("video.chapters[0].t 必须为 0")
        if t < prev_t - 1e-6:
            errors.append("video.chapters[%d].t 必须单调不减" % k)
        prev_t = max(prev_t, t)
        if dur_ok and t > float(dur) + 1e-6:
            errors.append("video.chapters[%d].t（%.2f）超出视频时长（%.2f）"
                          % (k, t, float(dur)))
    return errors


# ---------------------------------------------------------------------------
# v2.0 compat（CONTRACT §12）：下载文件名清洗 / 媒体 sha256 / 外链媒体告警 / files 校验
# ---------------------------------------------------------------------------
COMPAT_MANIFEST_VERSION = 2
_ILLEGAL_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def sanitize_filename(name, fallback="演示", max_len=80):
    """把标题/原文件名清洗成安全的下载文件名（保留 UTF-8 中文，去路径分隔符/控制字符）。"""
    text = _ILLEGAL_FILENAME_RE.sub("_", str(name or ""))
    text = " ".join(text.split()).strip().rstrip(". ")
    if not text:
        text = _ILLEGAL_FILENAME_RE.sub("_", str(fallback or "演示")).strip() or "演示"
    max_len = max(1, int(max_len or 80))
    if len(text) > max_len:
        text = text[:max_len].rstrip(". ")
    return text or "演示"


def path_tail(path, max_len=40):
    """外链媒体路径尾部（优先保留文件名；过长时用 ``…`` 前缀截断）。"""
    text = str(path or "").replace("\\", "/").strip()
    if not text:
        return ""
    base = text.rsplit("/", 1)[-1] or text
    max_len = max(8, int(max_len or 40))
    if len(base) <= max_len:
        return base
    return "…" + base[-(max_len - 1):]


def _media_sha_map_zf(zf, prefix="ppt/media/"):
    out = {}
    for name in zf.namelist():
        if not name.startswith(prefix) or name.endswith("/"):
            continue
        try:
            data = zf.read(name)
        except KeyError:
            continue
        out[name] = hashlib.sha256(data).hexdigest()
    return out


def media_sha256_map(zf_or_path, prefix="ppt/media/"):
    """包内媒体文件 → sha256（``{包内部件名: hex}``）；非 zip（.ppt）返回空 dict。"""
    try:
        zf, owned = open_zip(zf_or_path)
    except PptxParseError:
        return {}
    try:
        return _media_sha_map_zf(zf, prefix)
    finally:
        if owned:
            zf.close()


def media_sha256_set(zf_or_path, prefix="ppt/media/"):
    """包内媒体 sha256 集合（「未重编码」校验：compat 的每个媒体 sha 必须在源集合中）。"""
    return set(media_sha256_map(zf_or_path, prefix).values())


def compat_external_media(media_shapes):
    """外链媒体 → ``(warnings, structured)``。

    ``warnings``：中文提示（按 kind 聚合，每处带页号与路径尾）；
    ``structured``：``[{"slide": 1-based, "kind": "v"|"a", "path_tail": "..."}]``。
    **不删除内容**，只如实告警（CONTRACT §12.1.4）。
    """
    places = []
    for item in media_shapes or []:
        if not item.get("external"):
            continue
        try:
            slide = int(item.get("slide") or 0)
        except (TypeError, ValueError):
            slide = 0
        places.append({"slide": slide,
                       "kind": "v" if item.get("kind") == "v" else "a",
                       "path_tail": path_tail(item.get("media") or "")})
    warnings = []
    labels = {"v": "外链视频", "a": "外链音频"}
    for kind in ("v", "a"):
        group = [p for p in places if p["kind"] == kind]
        if not group:
            continue
        detail = "；".join("第 %d 页，路径尾 %s" % (p["slide"], p["path_tail"] or "（空）")
                          for p in group)
        warnings.append("%s %d 处未随文件携带（%s）" % (labels[kind], len(group), detail))
    return warnings, places


def _validate_sha(value):
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(ch in "0123456789abcdef" for ch in value.lower())


def validate_files(files):
    """校验 ``manifest.files``（v2.0 compat 文件清单），返回错误字符串列表。"""
    errors = []
    if not isinstance(files, dict):
        return ["files 必须是对象"]
    for key in ("compat", "pdf", "source"):
        entry = files.get(key)
        if entry is None:
            if key in ("compat", "pdf"):
                errors.append("files.%s 缺失" % key)
            continue
        if not isinstance(entry, dict):
            errors.append("files.%s 必须是对象" % key)
            continue
        name = entry.get("s")
        if not isinstance(name, str) or not name:
            errors.append("files.%s.s 必须是非空字符串" % key)
        size = entry.get("size")
        if not isinstance(size, int) or size <= 0:
            errors.append("files.%s.size 必须是正整数" % key)
        if not _validate_sha(entry.get("sha256")):
            errors.append("files.%s.sha256 必须是 64 位十六进制" % key)
        if key == "pdf":
            pages = entry.get("pages")
            if pages is not None and (not isinstance(pages, int) or pages <= 0):
                errors.append("files.pdf.pages 必须是正整数")
        ext = entry.get("ext")
        if ext is not None and (not isinstance(ext, str) or not ext):
            errors.append("files.%s.ext 必须是非空字符串" % key)
        dl_name = entry.get("name")
        if dl_name is not None and (not isinstance(dl_name, str) or not dl_name):
            errors.append("files.%s.name 必须是非空字符串" % key)
    if isinstance(files.get("compat"), dict):
        ext = files["compat"].get("ext")
        if ext is not None and str(ext).lower() != "pptx":
            errors.append("files.compat.ext 必须是 pptx（兼容包统一为 pptx）")
    return errors


# ---------------------------------------------------------------------------
# v2.0.1 断链视频修复（CONTRACT §12.1.4 补充）：video External/NULL 关系 → 内嵌副本
# ---------------------------------------------------------------------------
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
REL_VIDEO_SUFFIX = "/relationships/video"
REL_MEDIA_SUFFIX = "/relationships/media"
_MISSING_TARGETS = ("", "null", "none", "(null)", "#null")


def rels_part_name(part_name):
    """``ppt/slides/slide7.xml`` → ``ppt/slides/_rels/slide7.xml.rels``。"""
    folder, fname = posixpath.split(part_name)
    return posixpath.join(folder, "_rels", fname + ".rels")


def parse_rels_text(text):
    """rels XML 文本 → ``{rId: {"type","target","external"}}``（解析失败返回空 dict）。"""
    try:
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    except (ET.ParseError, TypeError, ValueError):
        return {}
    out = {}
    for rel in root:
        rid = rel.get("Id")
        if not rid:
            continue
        out[rid] = {"type": rel.get("Type") or "",
                    "target": rel.get("Target") or "",
                    "external": (rel.get("TargetMode") or "").lower() == "external"}
    return out


def _xml_attr_escape(value):
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def rewrite_rels_target(text, rel_id, new_target):
    """把 rels 文本中 ``Id=rel_id`` 的 Relationship 的 Target 改为 new_target 并去掉 TargetMode。

    只改这一个元素（其余 XML 文本原样保留）；内部化后 video 关系的 Target 指向包内媒体。
    """
    pattern = re.compile(r'<Relationship\b[^>]*\bId="%s"[^>]*/>' % re.escape(str(rel_id)))
    escaped = _xml_attr_escape(new_target)

    def repl(match):
        tag = match.group(0)
        tag = re.sub(r'\s+TargetMode="[^"]*"', "", tag)
        if re.search(r'\s+Target="[^"]*"', tag):
            tag = re.sub(r'\s+Target="[^"]*"', ' Target="%s"' % escaped, tag, count=1)
        else:
            tag = tag[:-2].rstrip() + ' Target="%s"/>' % escaped
        return tag

    return pattern.sub(repl, text, count=1)


def resolve_relationship_target(part_name, target):
    """内部关系 Target（相对部件）→ 包内部件名（posix normpath）；无法解析返回空串。"""
    text = str(target or "").replace("\\", "/").strip()
    if not text:
        return ""
    if text.startswith("/"):
        return posixpath.normpath(text.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(part_name), text))


def _external_target_missing(target):
    """外链 Target 是否断链：空/NULL/本机 file:// 路径不存在 → True；http(s) 等网络链接 → False。"""
    text = str(target or "").strip()
    if text.lower() in _MISSING_TARGETS:
        return True
    low = text.lower()
    if low.startswith(("http://", "https://", "ftp://", "smb://")):
        return False
    if low.startswith("\\\\"):
        return False  # UNC 无法可靠判断，保守保留为外链
    path = text
    if low.startswith("file:"):
        path = urllib.parse.unquote(text)
        if path.lower().startswith("file://"):
            path = path[7:]
        elif path.lower().startswith("file:"):
            path = path[5:]
    try:
        return not os.path.exists(path)
    except (OSError, ValueError):
        return False


def _is_video_rel(rel):
    return bool(rel) and str(rel.get("type") or "").lower().endswith(REL_VIDEO_SUFFIX)


def _is_media_rel(rel):
    rel_type = str(rel.get("type") or "").lower()
    return (rel_type.endswith(REL_MEDIA_SUFFIX)
            or rel_type.endswith(REL_VIDEO_SUFFIX)
            or rel_type.endswith("/relationships/audio"))


def _rel_is_broken_video(rel, part_name, package_sizes):
    """video 关系是否断链：External 且 Target 空/NULL/本机不存在，或内部 Target 指向缺失部件。"""
    if not _is_video_rel(rel):
        return False
    target = str(rel.get("target") or "")
    if rel.get("external"):
        return _external_target_missing(target)
    resolved = resolve_relationship_target(part_name, target)
    return not resolved or resolved not in package_sizes


def _iter_pic_video_refs(root):
    """slide XML 里每个 ``<p:pic>`` 的 video/p14:media 关系引用。"""
    out = []
    for pic in root.iter("{%s}pic" % P_NS):
        video_rid = ""
        for node in pic.iter("{%s}videoFile" % A_NS):
            video_rid = node.get("{%s}link" % R_NS) or ""
            break
        if not video_rid:
            for node in pic.iter("{%s}videoFile" % P_NS):
                video_rid = node.get("{%s}link" % R_NS) or ""
                break
        embed_rid = ""
        for node in pic.iter("{%s}media" % P14_NS):
            rid = node.get("{%s}embed" % R_NS)
            if rid:
                embed_rid = rid
                break
        name = ""
        pic_id = ""
        c_nv_pr = pic.find("./{%s}nvPicPr/{%s}cNvPr" % (P_NS, P_NS))
        if c_nv_pr is not None:
            name = str(c_nv_pr.get("name") or "")
            pic_id = str(c_nv_pr.get("id") or "")
        out.append({"name": name, "pic_id": pic_id,
                    "video_rid": video_rid, "embed_rid": embed_rid})
    return out


def _used_relationship_ids(root):
    """slide XML 中被引用的所有关系 id（r:embed/r:link/r:id）。"""
    used = set()
    attrs = ("{%s}embed" % R_NS, "{%s}link" % R_NS, "{%s}id" % R_NS)
    for el in root.iter():
        for attr in attrs:
            value = el.get(attr)
            if value:
                used.add(value)
    return used


def plan_video_link_repairs(slide_xml, rels, package_sizes, slide_part_name, slide_index=1):
    """分析一页，规划断链视频修复（纯逻辑，不写文件）。

    ``package_sizes``: 包内部件名 → 字节数（用于判断内嵌 media 是否存在）。
    返回 ``{"updates": {video_rel_id: new_target}, "repairs": [...], "unresolved": [...]}``。
    """
    plan = {"updates": {}, "repairs": [], "unresolved": []}
    try:
        root = ET.fromstring(slide_xml.encode("utf-8")
                             if isinstance(slide_xml, str) else slide_xml)
    except (ET.ParseError, TypeError, ValueError):
        return plan
    rels = rels or {}
    used = _used_relationship_ids(root)
    # 兜底候选：同 slide 内「未被引用」的内嵌 media/video 关系（文件存在）
    fallback = []
    for rid, rel in rels.items():
        if rid in used or rel.get("external") or not _is_media_rel(rel):
            continue
        resolved = resolve_relationship_target(slide_part_name, rel.get("target"))
        if resolved and resolved in package_sizes:
            fallback.append((rid, rel.get("target"), resolved))
    for pic in _iter_pic_video_refs(root):
        video_rid = pic["video_rid"]
        if not video_rid:
            continue
        if video_rid in plan["updates"]:
            continue
        rel = rels.get(video_rid)
        broken = _rel_is_broken_video(rel, slide_part_name, package_sizes)
        if not broken:
            continue
        # 优先 p14:media 的 r:embed 指向的内嵌副本
        candidate = None
        embed_rid = pic["embed_rid"]
        embed_rel = rels.get(embed_rid)
        if embed_rel is not None and not embed_rel.get("external") and _is_media_rel(embed_rel):
            resolved = resolve_relationship_target(slide_part_name,
                                                   embed_rel.get("target"))
            if resolved and resolved in package_sizes:
                candidate = (embed_rid, embed_rel.get("target"), resolved)
        if candidate is None and len(fallback) == 1:
            candidate = fallback[0]
        if candidate is not None:
            rel_id, target, resolved = candidate
            plan["updates"][video_rid] = target
            plan["repairs"].append({
                "slide": int(slide_index),
                "name": pic["name"],
                "media": posixpath.basename(resolved),
                "bytes": int(package_sizes[resolved]),
            })
            if candidate in fallback:
                fallback.remove(candidate)
        else:
            plan["unresolved"].append({
                "slide": int(slide_index),
                "kind": "v",
                "rel_id": video_rid,
                "name": pic["name"],
                "path_tail": path_tail((rel or {}).get("target") or ""),
            })
    return plan


def repair_broken_video_links(path, out_path=None):
    """修复 compat 包内「video 外链断链但存在内嵌副本」的结构（zip 级，不改任何内容字节）。

    * 只重写 ``ppt/slides/_rels/*.xml.rels``（把断链 video 关系的 Target 指向同 slide
      的内嵌 media 并去掉 TargetMode；Type 仍为 relationships/video，对齐正常包结构）；
    * 所有部件（含 media 字节）原样复制；重写后 ``zipfile.testzip()`` + 部件名列表校验；
    * 无修复时**不重写文件**（幂等）；找不到内嵌副本的断链保留 External → 由调用方如实 warning。

    返回 ``{"changed": bool, "repairs": [{"slide","name","media","bytes"}], "unresolved": [...]}``。
    """
    path = os.path.abspath(str(path))
    result = {"changed": False, "repairs": [], "unresolved": []}
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PptxParseError("无法打开兼容包（%s）" % exc.__class__.__name__)
    tmp_path = path + ".repair.tmp"
    zf_closed = False
    try:
        names = zf.namelist()
        package_sizes = {}
        for info in zf.infolist():
            if not info.is_dir():
                package_sizes[info.filename] = int(info.file_size)
        changed_rels = {}
        slide_parts = slide_part_names(zf)
        for slide_index, part_name in enumerate(slide_parts, start=1):
            if part_name not in package_sizes:
                continue
            rels_name = rels_part_name(part_name)
            try:
                rels_text = zf.read(rels_name).decode("utf-8", "replace")
            except KeyError:
                continue
            try:
                slide_xml = zf.read(part_name).decode("utf-8", "replace")
            except KeyError:
                continue
            rels = parse_rels_text(rels_text)
            plan = plan_video_link_repairs(slide_xml, rels, package_sizes,
                                           part_name, slide_index)
            result["repairs"].extend(plan["repairs"])
            result["unresolved"].extend(plan["unresolved"])
            if not plan["updates"]:
                continue
            new_text = rels_text
            for rel_id, target in plan["updates"].items():
                new_text = rewrite_rels_target(new_text, rel_id, target)
            changed_rels[rels_name] = new_text.encode("utf-8")
        if not changed_rels:
            return result
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        with zipfile.ZipFile(tmp_path, "w") as zout:
            for info in zf.infolist():
                data = changed_rels.get(info.filename)
                if data is None:
                    data = zf.read(info.filename)
                zout.writestr(info, data)
        with zipfile.ZipFile(tmp_path) as check:
            bad = check.testzip()
            if bad is not None:
                raise PptxParseError("断链视频修复后 zip 校验失败（坏部件：%s）" % bad)
            if set(check.namelist()) != set(names):
                raise PptxParseError("断链视频修复后部件列表变化（拒绝写入）")
        # Windows 上必须先关闭源 zip 句柄，否则 os.replace 目标被占用（WinError 5）
        zf.close()
        zf_closed = True
        target_path = os.path.abspath(str(out_path)) if out_path else path
        try:
            if os.path.exists(target_path):
                os.chmod(target_path, 0o666)  # 只读属性兜底（不改变内容）
        except OSError:
            pass
        os.replace(tmp_path, target_path)
        result["changed"] = True
        return result
    finally:
        try:
            zf.close()
        except Exception:  # noqa: BLE001
            pass
        if os.path.exists(tmp_path) and not result["changed"]:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

# ---------------------------------------------------------------------------
# v2.2 媒体编码兼容（CONTRACT §12.7）：策略纯函数 + 安全 zip 重写
# ---------------------------------------------------------------------------
VIDEO_MEDIA_EXTS = frozenset([
    ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".webm",
    ".mpg", ".mpeg", ".ts", ".3gp", ".vob", ".ogv", ".asf", ".rm", ".rmvb",
])
AUDIO_MEDIA_EXTS = frozenset([
    ".mp3", ".m4a", ".aac", ".wav", ".wma", ".ac3", ".dts", ".mp2",
    ".ogg", ".oga", ".opus", ".flac", ".amr", ".aiff", ".aif", ".mka",
])
VIDEO_CONTAINER_OK = frozenset([".mp4", ".m4v"])
VIDEO_CODEC_KEEP = frozenset(["h264"])
AUDIO_CODEC_KEEP = frozenset(["aac"])
AUDIO_FILE_CODEC_KEEP = frozenset(["aac", "mp3"])
MEDIA_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".aac": "audio/aac",
}
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

MEDIA_DEFAULT_LIMITS = {
    "max_bytes": 200 * 1024 * 1024,
    "max_single_dur": 30 * 60.0,
    "max_total_dur": 60 * 60.0,
}


MEDIA_REL_SUFFIXES = ("/relationships/video", "/relationships/media",
                       "/relationships/audio")


def media_slide_refs(zf_or_path):
    """反查「内嵌媒体部件 → 引用它的幻灯片页码」``{part: [slide,...]}``（CONTRACT §12.8）。

    只统计非外链的 video/media/audio 关系，Target 解析后必须落在 ``ppt/media/`` 且部件存在。
    """
    zf, owned = open_zip(zf_or_path)
    try:
        names = set(zf.namelist())
        refs = {}
        for index, part in enumerate(slide_part_names(zf), start=1):
            rels_name = rels_part_name(part)
            if rels_name not in names:
                continue
            try:
                text = zf.read(rels_name).decode("utf-8", "replace")
            except KeyError:
                continue
            for _rid, rel in parse_rels_text(text).items():
                if rel.get("external"):
                    continue
                rel_type = str(rel.get("type") or "").lower()
                if not rel_type.endswith(MEDIA_REL_SUFFIXES):
                    continue
                target = resolve_relationship_target(part, rel.get("target"))
                if not target or not target.startswith("ppt/media/"):
                    continue
                if target not in names:
                    continue
                refs.setdefault(target, set()).add(index)
        return {part: sorted(pages) for part, pages in sorted(refs.items())}
    finally:
        if owned:
            zf.close()


def media_kind_of(part_name):
    """``ppt/media/media1.mp4`` → ``"video"`` / ``"audio"`` / ``""``（按扩展名）。"""
    ext = posixpath.splitext(str(part_name or ""))[1].lower()
    if ext in VIDEO_MEDIA_EXTS:
        return "video"
    if ext in AUDIO_MEDIA_EXTS:
        return "audio"
    return ""


def classify_media(probe, part_name, limits=None):
    """媒体编码兼容策略（CONTRACT §12.7 纯逻辑矩阵）。

    ``probe``: ``{"w","h","dur","codec"(vcodec),"has_audio","audio_codec","bytes"}``。
    返回 ``{"action": "keep"|"remux"|"transcode", "kind", "target_ext", "reason",
    "lossless", "vcodec_from", "acodec_from", "dur", "width", "height"}``。
    """
    limits = dict(MEDIA_DEFAULT_LIMITS, **(limits or {}))
    part_name = str(part_name or "")
    kind = media_kind_of(part_name)
    ext = posixpath.splitext(part_name)[1].lower()
    probe = probe or {}
    try:
        dur = float(probe.get("dur") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    try:
        size = int(probe.get("bytes") or 0)
    except (TypeError, ValueError):
        size = 0
    vcodec = str(probe.get("codec") or "").lower()
    acodec = str(probe.get("audio_codec") or "").lower()
    has_audio = bool(probe.get("has_audio"))
    try:
        width = int(probe.get("w") or 0)
        height = int(probe.get("h") or 0)
    except (TypeError, ValueError):
        width = height = 0
    base = {
        "kind": kind or "video", "target_ext": "", "reason": "",
        "lossless": True, "vcodec_from": vcodec, "acodec_from": acodec,
        "dur": round(dur, 3), "width": width, "height": height,
    }
    if not kind:
        return dict(base, action="keep", reason="非音视频媒体")
    if size and size > int(limits["max_bytes"]):
        return dict(base, action="keep", reason="media_too_big")
    if dur and dur > float(limits["max_single_dur"]):
        return dict(base, action="keep", reason="media_too_long")
    if kind == "audio":
        file_ok = (acodec in AUDIO_FILE_CODEC_KEEP
                   and ext in (".mp3", ".m4a", ".aac", ".mp4"))
        if file_ok:
            return dict(base, action="keep")
        if not acodec:
            return dict(base, action="keep", reason="audio_codec_unknown")
        return dict(base, action="transcode", target_ext=".m4a", lossless=False)
    # 视频
    video_ok = vcodec in VIDEO_CODEC_KEEP
    audio_ok = (not has_audio) or (acodec in AUDIO_CODEC_KEEP)
    container_ok = ext in VIDEO_CONTAINER_OK
    if video_ok and audio_ok and container_ok:
        return dict(base, action="keep")
    if video_ok and audio_ok:
        return dict(base, action="remux", target_ext=".mp4", lossless=True)
    return dict(base, action="transcode", target_ext=".mp4", lossless=False)


def ensure_content_types_defaults(xml_text, ext_types):
    """``[Content_Types].xml`` 补齐 ``Default Extension``（去重，保留其余元素）。

    ``ext_types``: ``{".mp4": "video/mp4", ...}``；返回新 XML 文本。
    """
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    existing = {}
    for el in list(root):
        if el.tag != "{%s}Default" % CT_NS:
            continue
        ext = str(el.get("Extension") or "").lower()
        if not ext:
            continue
        if ext in existing:
            root.remove(el)  # 去重
        else:
            existing[ext] = el
    for ext, content_type in ext_types.items():
        key = str(ext or "").lower().lstrip(".")
        if not key or key in existing:
            continue
        child = ET.SubElement(root, "{%s}Default" % CT_NS)
        child.set("Extension", key)
        child.set("ContentType", content_type)
        existing[key] = child
    ET.register_namespace("", CT_NS)
    body = ET.tostring(root, encoding="unicode")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + body)


def rewrite_rels_media_targets(text, rename_map):
    """把 rels 文本中 ``Target=".../media/<旧名>"`` 改为新名（其它内容原样保留）。"""
    if not rename_map:
        return text
    pattern = re.compile(r'<Relationship\b[^>]*/>')

    def repl(match):
        tag = match.group(0)
        target_match = re.search(r'\bTarget="([^"]*)"', tag)
        if not target_match:
            return tag
        target = target_match.group(1)
        normalized = target.replace("\\", "/")
        base = posixpath.basename(normalized)
        if base not in rename_map:
            return tag
        if "/media/" not in normalized and not normalized.startswith("media/"):
            return tag
        new_target = normalized[: len(normalized) - len(base)] + rename_map[base]
        return tag.replace('Target="%s"' % target, 'Target="%s"' % new_target, 1)

    return pattern.sub(repl, text)


def rewrite_package_media(path, replacements):
    """安全重写 compat 包：替换/改名 media 部件、更新 Content_Types 与 rels。

    ``replacements``: ``[{"old": "ppt/media/a.wmv", "new": "ppt/media/a.mp4",
    "data": b"...", "content_type": "video/mp4"}, ...]``。
    所有其它部件原样复制；重写后校验 zip 与媒体部件数；返回 ``{"changed","renames"}``。
    """
    import os as _os
    path = _os.path.abspath(str(path))
    result = {"changed": False, "renames": {}, "parts": 0}
    if not replacements:
        return result
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        name_set = set(names)
        entries = {name: zf.read(name) for name in names}
    rename_map = {}
    media_after = set()
    updates = {}
    for item in replacements:
        old = str(item.get("old") or "").replace("\\", "/")
        new = str(item.get("new") or old).replace("\\", "/")
        if old not in entries:
            raise PptxParseError("媒体部件不存在：%s" % old)
        if new != old and new in name_set and new not in {
                str(it.get("old") or "").replace("\\", "/") for it in replacements}:
            raise PptxParseError("媒体新名冲突：%s" % new)
        if new != old:
            rename_map[posixpath.basename(old)] = posixpath.basename(new)
        data = item.get("data")
        updates[new] = entries[old] if data is None else bytes(data)
        media_after.add(new)
    new_names = set(updates.keys())
    # 原有其它 media 保留
    for name in names:
        if name.startswith("ppt/media/") and not name.endswith("/"):
            if name in {str(it.get("old") or "").replace("\\", "/") for it in replacements}:
                continue
            media_after.add(name)
    ext_types = {}
    for item in replacements:
        new = str(item.get("new") or item.get("old") or "")
        ext = posixpath.splitext(new)[1].lower()
        key = ext.lstrip(".")
        if ext in MEDIA_CONTENT_TYPES:
            ext_types[key] = item.get("content_type") or MEDIA_CONTENT_TYPES[ext]
    ct_name = "[Content_Types].xml"
    updated_entries = dict(entries)
    for name in list(updated_entries.keys()):
        if name in {str(it.get("old") or "").replace("\\", "/") for it in replacements}:
            del updated_entries[name]
    for new, data in updates.items():
        updated_entries[new] = data
    if ct_name in updated_entries:
        try:
            old_ct = updated_entries[ct_name].decode("utf-8")
            updated_entries[ct_name] = ensure_content_types_defaults(
                old_ct, ext_types).encode("utf-8")
        except (ET.ParseError, UnicodeDecodeError):
            pass
    for name in names:
        if not name.endswith(".rels") or not name.startswith("ppt/"):
            continue
        try:
            text = entries[name].decode("utf-8")
        except UnicodeDecodeError:
            continue
        new_text = rewrite_rels_media_targets(text, rename_map)
        if new_text != text:
            updated_entries[name] = new_text.encode("utf-8")
    tmp_path = path + ".media.tmp"
    try:
        if _os.path.exists(tmp_path):
            _os.remove(tmp_path)
        with zipfile.ZipFile(tmp_path, "w") as zout:
            for name in names:
                old = str(name)
                out_name = old
                for item in replacements:
                    if old == str(item.get("old") or "").replace("\\", "/"):
                        out_name = str(item.get("new") or old).replace("\\", "/")
                        break
                zout.writestr(out_name, updated_entries[out_name])
        with zipfile.ZipFile(tmp_path) as check:
            bad = check.testzip()
            if bad is not None:
                raise PptxParseError("媒体兼容重写后 zip 校验失败（%s）" % bad)
            new_media = [n for n in check.namelist()
                         if n.startswith("ppt/media/") and not n.endswith("/")]
            if len(new_media) != len(media_after):
                raise PptxParseError("媒体兼容重写后媒体部件数不一致（%d/%d）"
                                     % (len(new_media), len(media_after)))
        _os.replace(tmp_path, path)
        result.update({"changed": True, "renames": rename_map,
                       "parts": len(replacements)})
        return result
    finally:
        if _os.path.exists(tmp_path):
            try:
                _os.remove(tmp_path)
            except OSError:
                pass

