# -*- coding: utf-8 -*-
"""convert.py — PowerPoint COM 转换核心（本机）

契约唯一真源：``web/ppt/CONTRACT.md``（§5 manifest / §6 转换机 / §7 切换映射）。

职责（不碰网络、不碰云端；OSS 上传在 agent.py）：

1. PowerPoint 忙检测（用户正打开文档 → 抛 ``ConvertBusyError``，调用方保持 queued）；
2. 打开临时副本（只读），读取页尺寸 / 每页动画 / 切换 / 备注；
3. 逐页逐「点击步」设置目标形状 ``Shape.Visible`` 后 ``Slide.Export`` JPG 快照；
   - 初始画面隐藏所有「首个效果为单击入场」的形状；
   - trigger==1/4 开新 step，2/3 并入当前 step；
   - 相邻两步导出字节相同 → 去重；
   - 每页 step 上限 12；整份图片上限 260（超出统一降级为每页 1–2 步，内容不丢）；
4. ``SaveCopyAs`` 临时 .pptx → 解包 ``<a:videoFile>/<a:audioFile>`` + ``<a:xfrm>``
   归一化热区 → ffmpeg 转 H.264 MP4 / AAC m4a（失败重试 remux，仍失败跳过并记日志）；
5. Pillow 转 WebP（display 最长边 ≤1600 q72；thumb 宽 400 q65）；
6. 组装 CONTRACT §5 manifest + 资产清单，计算 buildId（base 目录前置）。

不变量：单任务 15 分钟（``timeout_s``，分步检查）；只结束本函数自己创建的
PowerPoint 实例（开始前若已有实例且 Presentations.Count>0 直接跳过）。

``convert_deck(src_path, work_dir, opts)`` 返回::

    {"manifest": {...}, "assets": [{"name","path","size","content_type","kind"}...],
     "build_id": "...", "stats": {...}, "warnings": [...], "aspect": "16:9",
     "slide_count": n, "step_count": n, "cover": "t1.webp", "src_ext": ".pptx"}
"""
import json
import os
import shutil
import subprocess
import time
import traceback
import zipfile

try:  # 包内/脚本两种运行方式都支持
    from . import pptx_xml
except ImportError:  # pragma: no cover
    import pptx_xml

HERE = os.path.dirname(os.path.abspath(__file__))

OSS_BASE = "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/"
SRC_PREFIX = "ppt/src/"
ASSET_PREFIX = "ppt/a/"

DEFAULT_OPTIONS = {
    "deck_id": "testdeck",
    "display_width": 1600,
    "webp_quality": 72,
    "thumb_width": 400,
    "thumb_quality": 65,
    "max_steps_per_slide": 12,
    "max_images": 260,
    "max_slides": 300,
    "export_format": "JPG",
    "timeout_s": 900.0,
    "with_media": True,
    "max_media_file_bytes": 200 * 1024 * 1024,
    "max_media_total_duration_s": 30 * 60,
    "max_media_trim_s": 30 * 60,       # 单段过长只转前 30min（DESIGN §5.1）
    "max_media_files": 60,
    # DESIGN §5.1 性能预算：主图 1600 长边 ≤200KB（超了降 q62 重试一次），
    # 缩略图 400 宽 ≤25KB（超了再降一次 quality）
    "image_max_bytes": 200 * 1024,
    "image_retry_quality": 62,
    "thumb_max_bytes": 25 * 1024,
    "thumb_retry_quality": 55,
    "ffmpeg": "",
    "ffprobe": "",
    "oss_base": OSS_BASE,
    "keep_intermediate": False,
    "notes_max_chars": 2000,
}

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

NO_MEDIA = []  # 空媒体列表常量（避免可变默认值）


class ConvertError(RuntimeError):
    """转换失败（中文 error 直接写云端）。"""


class ConvertBusyError(ConvertError):
    """PowerPoint 被用户占用 / 无响应 → 本轮跳过（deck 保持 queued）。"""


class ConvertTimeout(ConvertError):
    """单任务超时。"""


def _noop(*_a, **_k):
    pass


def normalize_options(opts=None):
    out = dict(DEFAULT_OPTIONS)
    if opts:
        if isinstance(opts, dict):
            out.update({k: v for k, v in opts.items() if v is not None})
        else:  # 简单对象（dataclass/argparse Namespace）
            for key in DEFAULT_OPTIONS:
                if hasattr(opts, key):
                    val = getattr(opts, key)
                    if val is not None:
                        out[key] = val
    out["deck_id"] = str(out.get("deck_id") or "testdeck")
    return out


def _fmt_seconds(sec):
    return "%.2fs" % float(sec)


class _Deadline(object):
    def __init__(self, seconds):
        self.seconds = float(seconds or 0)
        self.started = time.monotonic()
        self.deadline = self.started + self.seconds if self.seconds > 0 else float("inf")

    def check(self, stage=""):
        if time.monotonic() > self.deadline:
            raise ConvertTimeout("转换超时（超过 %d 分钟%s）"
                                 % (int(self.seconds // 60) or 1,
                                    "，阶段：" + stage if stage else ""))

    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())


class _Ctx(object):
    def __init__(self, opts, log=None, progress=None):
        self.opts = opts
        self._log = log if callable(log) else _noop
        self._progress = progress if callable(progress) else _noop
        self.deadline = _Deadline(opts.get("timeout_s"))
        self.warnings = []

    def log(self, msg):
        try:
            self._log(str(msg))
        except Exception:  # noqa: BLE001
            pass

    def warn(self, msg):
        text = str(msg)
        self.warnings.append(text)
        self.log("WARN " + text)

    def progress(self, pct, phase=""):
        try:
            pct = max(0, min(100, int(pct)))
            self._progress(pct, phase)
        except Exception:  # noqa: BLE001
            pass

    def check(self, stage=""):
        self.deadline.check(stage)


# ---------------------------------------------------------------------------
# PowerShell 忙检测 / 实例管理
# ---------------------------------------------------------------------------
def _powerpnt_process_count():
    """当前 POWERPNT.EXE 进程数（tasklist；失败返回 0）。"""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq POWERPNT.EXE", "/NH"],
                             capture_output=True, text=True, timeout=20,
                             creationflags=CREATE_NO_WINDOW)
        text = (out.stdout or "").lower()
        return text.count("powerpnt.exe")
    except Exception:  # noqa: BLE001
        return 0


def _existing_powerpoint():
    """返回已在运行的 PowerPoint COM 实例（无则 None）。

    注意：只用 ``GetActiveObject``（ROT），**绝不用 ``Dispatch``**——后者在
    PowerPoint 未运行时会在探测时悄悄拉起一个进程（每轮心跳都会多开一个）。
    """
    try:
        import win32com.client as win32
    except ImportError as exc:  # pragma: no cover
        raise ConvertError("缺少 pywin32：%s" % exc.__class__.__name__)
    try:
        return win32.GetActiveObject("PowerPoint.Application")
    except Exception:  # noqa: BLE001
        return None


def powerpoint_busy():
    """只读探测（不创建实例）：返回 ``(busy: bool, reason: str)``。

    契约 §6：已存在 POWERPNT 进程且 ``Presentations.Count>0``（用户可能正在编辑）
    → 本轮跳过转换，deck 保持 queued。
    """
    app = _existing_powerpoint()
    if app is None:
        if _powerpnt_process_count() > 0:
            return True, "PowerPoint 进程存在但无法连接（可能正在编辑/无响应）"
        return False, ""
    try:
        count = int(app.Presentations.Count)
    except Exception:  # noqa: BLE001
        return True, "PowerPoint 无响应（COM RPC 繁忙）"
    if count > 0:
        return True, "PowerPoint 正打开 %d 个文档（用户占用）" % count
    return False, ""


def _acquire_powerpoint(ctx):
    """确保拿到一个**没有文档**的 PowerPoint 实例（为空实例则先 Quit 再新建）。"""
    app = _existing_powerpoint()
    if app is not None:
        try:
            count = int(app.Presentations.Count)
        except Exception:  # noqa: BLE001
            raise ConvertBusyError("PowerPoint 无响应（COM RPC 繁忙），本轮跳过")
        if count > 0:
            raise ConvertBusyError("PowerPoint 正打开 %d 个文档（用户占用），本轮跳过" % count)
        ctx.log("发现空 PowerPoint 实例 → Quit 后新建专用实例")
        try:
            app.Quit()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.6)
    elif _powerpnt_process_count() > 0:
        raise ConvertBusyError("PowerPoint 进程存在但无法连接，本轮跳过")

    import win32com.client as win32

    last_exc = None
    for attempt in range(1, 4):
        try:
            app = win32.DispatchEx("PowerPoint.Application")
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            ctx.log("DispatchEx PowerPoint 失败（第 %d 次）：%s" % (attempt, exc.__class__.__name__))
            time.sleep(1.2 * attempt)
    else:  # pragma: no cover
        raise ConvertError("无法启动 PowerPoint：%s" % (last_exc.__class__.__name__
                                                    if last_exc else "unknown"))
    try:
        app.DisplayAlerts = 1  # ppAlertsNone
    except Exception:  # noqa: BLE001
        pass
    try:
        app.Visible = True  # PowerPoint 16 不允许 Visible=False（已实测）
    except Exception:  # noqa: BLE001
        pass
    try:
        app.WindowState = 2  # ppWindowMinimized：尽量少干扰桌面
    except Exception:  # noqa: BLE001
        pass
    return app


def _quiet_shutdown(holder, ctx):
    """收尾：先释放 COM 引用再 Quit/反初始化（顺序很关键）。

    实测（2026-11-09）：PowerPoint Quit 之后再 Release COM 代理偶发卡 ~60s
    （COM RPC 清理）。这里用 holder 集中持有引用并提前置 None、先 gc 再 Quit，
    避免调用方局部变量继续持有代理。绝不 Quit 有用户文档的实例。
    """
    import gc

    app = holder.get("app")
    pres = holder.get("pres")
    holder["pres"] = None
    holder["app"] = None
    t0 = time.monotonic()
    if pres is not None:
        try:
            pres.Close()
        except Exception:  # noqa: BLE001
            pass
        ctx.log("关闭演示文稿 %.0fms" % ((time.monotonic() - t0) * 1000))
    pres = None
    try:
        gc.collect()
    except Exception:  # noqa: BLE001
        pass
    t1 = time.monotonic()
    if app is not None:
        try:
            try:
                count = int(app.Presentations.Count)
            except Exception:  # noqa: BLE001
                count = 0
            if count == 0:
                app.Quit()
                ctx.log("PowerPoint 退出 %.0fms" % ((time.monotonic() - t1) * 1000))
            else:
                ctx.warn("退出时检测到 PowerPoint 有 %d 个文档（用户新开），保留实例" % count)
        except Exception:  # noqa: BLE001
            pass
    app = None
    try:
        gc.collect()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# COM 读取（页尺寸 / 动画 / 切换 / 备注 / 媒体形状）
# ---------------------------------------------------------------------------
def _slide_shapes_by_id(slide, ctx):
    out = {}
    try:
        count = int(slide.Shapes.Count)
    except Exception:  # noqa: BLE001
        return out
    for i in range(1, count + 1):
        try:
            sh = slide.Shapes(i)
            out[int(sh.Id)] = sh
        except Exception as exc:  # noqa: BLE001
            ctx.warn("读取形状失败（第 %d 个）：%s" % (i, exc.__class__.__name__))
    return out


def _slide_com_media(slide, slide_w_pt, slide_h_pt, ctx):
    """COM 侧媒体形状（msoMedia=16）：name / id / 归一化矩形（用于对齐 pptx pic）。"""
    out = []
    try:
        count = int(slide.Shapes.Count)
    except Exception:  # noqa: BLE001
        return out
    for i in range(1, count + 1):
        try:
            sh = slide.Shapes(i)
            if int(sh.Type) != 16:  # msoMedia
                continue
            rect = None
            try:
                rect = pptx_xml.normalize_rect(sh.Left, sh.Top, sh.Width, sh.Height,
                                               slide_w_pt, slide_h_pt)
            except Exception:  # noqa: BLE001
                rect = None
            out.append({"name": str(sh.Name), "id": int(sh.Id), "rect": rect})
        except Exception:  # noqa: BLE001
            continue
    return out


def _slide_effects(slide, ctx):
    """读取 MainSequence 动画效果列表（供 pptx_xml.plan_steps）。"""
    out = []
    try:
        seq = slide.TimeLine.MainSequence
        count = int(seq.Count)
    except Exception as exc:  # noqa: BLE001
        ctx.warn("读取动画失败：%s" % exc.__class__.__name__)
        return out
    for j in range(1, count + 1):
        try:
            eff = seq.Item(j)
            item = {"i": j, "effect_type": 0, "exit": False, "shape_name": "",
                    "shape_id": -1, "trigger": 1, "duration": 0.0}
            try:
                item["effect_type"] = int(eff.EffectType)
            except Exception:  # noqa: BLE001
                pass
            try:
                item["exit"] = bool(eff.Exit)
            except Exception:  # noqa: BLE001
                pass
            try:
                item["shape_name"] = str(eff.Shape.Name)
                item["shape_id"] = int(eff.Shape.Id)
            except Exception:  # noqa: BLE001
                pass
            try:
                item["trigger"] = int(eff.Timing.TriggerType)
            except Exception:  # noqa: BLE001
                item["trigger"] = 1
            try:
                item["duration"] = float(eff.Timing.Duration)
            except Exception:  # noqa: BLE001
                pass
            out.append(item)
        except Exception as exc:  # noqa: BLE001
            ctx.warn("读取第 %d 个动画失败：%s" % (j, exc.__class__.__name__))
    return out


def _slide_transition(slide, ctx):
    try:
        return int(slide.SlideShowTransition.EntryEffect)
    except Exception as exc:  # noqa: BLE001
        ctx.warn("读取切换失败（按 fade 处理）：%s" % exc.__class__.__name__)
        return 0


def _slide_notes(slide, ctx, max_chars=2000):
    """备注页文本（去掉页码占位），截断 ``max_chars``。"""
    texts = []
    try:
        notes_page = slide.NotesPage
    except Exception as exc:  # noqa: BLE001
        ctx.warn("读取备注页失败：%s" % exc.__class__.__name__)
        return ""
    try:
        ph = notes_page.Shapes.Placeholders(2)  # ppPlaceholderBody
        if bool(ph.HasTextFrame) and bool(ph.TextFrame.HasText):
            text = str(ph.TextFrame.TextRange.Text or "")
            if text.strip():
                texts.append(text)
    except Exception:  # noqa: BLE001
        pass
    if not texts:
        try:
            for i in range(1, int(notes_page.Shapes.Count) + 1):
                sh = notes_page.Shapes(i)
                try:
                    if not bool(sh.HasTextFrame) or not bool(sh.TextFrame.HasText):
                        continue
                    text = str(sh.TextFrame.TextRange.Text or "")
                except Exception:  # noqa: BLE001
                    continue
                if not text.strip():
                    continue
                # 页码占位（幻灯片编号）通常是纯数字
                if text.strip().isdigit():
                    continue
                texts.append(text)
        except Exception:  # noqa: BLE001
            pass
    text = "\n".join(t.rstrip() for t in texts if t.strip())
    return text[:int(max_chars)]


# ---------------------------------------------------------------------------
# 导出 / 图像
# ---------------------------------------------------------------------------
def _set_shape_visible(shape, visible, ctx, shape_id):
    try:
        current = bool(shape.Visible)
    except Exception:  # noqa: BLE001
        return
    if current == bool(visible):
        return
    try:
        shape.Visible = bool(visible)
    except Exception as exc:  # noqa: BLE001
        ctx.warn("设置形状 %s 可见性失败：%s" % (shape_id, exc.__class__.__name__))


def _export_slide(slide, path, fmt, width, height):
    slide.Export(path, fmt, int(width), int(height))
    if not os.path.exists(path) or os.path.getsize(path) <= 0:
        raise ConvertError("图片导出失败（文件为空）：%s" % os.path.basename(path))


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _save_webp(src_path, dst_path, opts, width=None):
    """JPG/PNG → WebP（可选按宽度等比缩放）。返回 (width, height, size, quality_used)。

    DESIGN §5.1：主图 1600 长边 q72 且**单张 ≤200KB**，超过时降 q62 重试一次；
    仍超则保留并告警（内容清晰度优先）。
    """
    from PIL import Image  # 延迟导入（纯逻辑单测不需要）

    def _encode(im_obj, quality):
        im_obj.save(dst_path, "WEBP", quality=int(quality), method=4)
        return os.path.getsize(dst_path)

    with Image.open(src_path) as im:
        im = im.convert("RGB")
        if width and im.width > int(width):
            ratio = float(width) / float(im.width)
            im = im.resize((int(width), max(1, int(round(im.height * ratio)))),
                           Image.LANCZOS)
        quality = int(opts["webp_quality"])
        size = _encode(im, quality)
        if size > int(opts["image_max_bytes"]):
            retry_q = int(opts["image_retry_quality"])
            size = _encode(im, retry_q)
            quality = retry_q
        return im.width, im.height, size, quality


def _make_thumb(src_webp, dst_path, opts):
    from PIL import Image

    with Image.open(src_webp) as im:
        im = im.convert("RGB")
        width = int(opts["thumb_width"])
        if im.width > width:
            ratio = float(width) / float(im.width)
            im = im.resize((width, max(1, int(round(im.height * ratio)))), Image.LANCZOS)
        quality = int(opts["thumb_quality"])
        im.save(dst_path, "WEBP", quality=quality, method=4)
        size = os.path.getsize(dst_path)
        if size > int(opts["thumb_max_bytes"]):
            quality = int(opts["thumb_retry_quality"])
            im.save(dst_path, "WEBP", quality=quality, method=4)
            size = os.path.getsize(dst_path)
        return im.width, im.height, size, quality


# ---------------------------------------------------------------------------
# ffmpeg
# ---------------------------------------------------------------------------
def _find_tool(name, configured):
    if configured:
        return configured
    found = shutil.which(name)
    if found:
        return found
    fallback = os.path.join(os.path.expanduser("~"), "bin", name + ".exe")
    if os.path.exists(fallback):
        return fallback
    return name  # 交给 subprocess 报错


def _run_ffmpeg(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW)


def _ffprobe_info(ffprobe, path):
    """返回 {"w","h","dur"}；失败返回 None。"""
    try:
        proc = _run_ffmpeg([ffprobe, "-v", "error",
                            "-select_streams", "v:0",
                            "-show_entries", "stream=codec_name,width,height",
                            "-show_entries", "format=duration",
                            "-of", "json", path], timeout=60)
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams") or []
        stream = streams[0] if streams else {}
        fmt = data.get("format") or {}
        try:
            dur = float(fmt.get("duration") or 0.0)
        except (TypeError, ValueError):
            dur = 0.0
        return {"w": int(stream.get("width") or 0), "h": int(stream.get("height") or 0),
                "dur": dur, "codec": str(stream.get("codec_name") or "")}
    except Exception:  # noqa: BLE001
        return None


def _transcode_media(ffmpeg, ffprobe, src_path, kind, dst_path, ctx, opts):
    """ffmpeg 转码：视频 H.264/AAC mp4（720p、≤2.5Mbps、faststart）；音频 AAC m4a。

    DESIGN §5.1：720p（scale=min(1280,iw)）、H.264 ≤2.5Mbps、faststart；
    单段过长（>30min）只转前 30min 并记录。失败重试 remux，仍失败返回 None。
    """
    info = _ffprobe_info(ffprobe, src_path) or {"w": 0, "h": 0, "dur": 0.0}
    trim = ""
    try:
        max_trim = float(opts.get("max_media_trim_s") or 0)
    except (TypeError, ValueError):
        max_trim = 0.0
    if max_trim > 0 and float(info.get("dur") or 0.0) > max_trim:
        trim = str(int(max_trim))
        ctx.warn("媒体时长 %.0fs 超过 %.0fs，只转前 %.0fs：%s"
                 % (float(info.get("dur") or 0), max_trim, max_trim,
                    os.path.basename(src_path)))
    if kind == "v":
        base_cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src_path,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                    "-maxrate", "2500k", "-bufsize", "5000k",
                    "-vf", "scale='min(1280,iw)':-2", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "96k",
                    "-movflags", "+faststart"]
    else:
        base_cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src_path,
                    "-vn", "-c:a", "aac", "-b:a", "80k",
                    "-movflags", "+faststart"]
    if trim:
        base_cmd += ["-t", trim]
    base_cmd.append(dst_path)
    attempts = [("transcode", base_cmd)]
    if kind == "v":
        remux_cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                     "-i", src_path]
        if trim:
            remux_cmd += ["-t", trim]
        remux_cmd += ["-c", "copy", "-movflags", "+faststart", dst_path]
        attempts.append(("remux", remux_cmd))
    for label, cmd in attempts:
        try:
            proc = _run_ffmpeg(cmd)
        except subprocess.TimeoutExpired:
            ctx.warn("ffmpeg %s 超时（%s）" % (label, os.path.basename(src_path)))
            continue
        if proc.returncode == 0 and os.path.exists(dst_path) and os.path.getsize(dst_path) > 0:
            out_info = _ffprobe_info(ffprobe, dst_path) or info
            if kind == "v" and not out_info.get("w"):
                out_info = info
            ctx.log("ffmpeg %s ok: %s -> %s (%d bytes, %.1fs)"
                    % (label, os.path.basename(src_path), os.path.basename(dst_path),
                       os.path.getsize(dst_path), float(out_info.get("dur") or 0)))
            return out_info
        err = (proc.stderr or "").strip().splitlines()
        ctx.warn("ffmpeg %s 失败（%s）：%s" % (label, os.path.basename(src_path),
                                             (err[-1] if err else "rc=%s" % proc.returncode)[:200]))
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
        except OSError:
            pass
    return None


def _media_ext(kind):
    return ".mp4" if kind == "v" else ".m4a"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def _render_slides(ctx, pres, slides_meta, assets_dir, tmp_dir, opts):
    """逐页导出 + WebP；返回 (kept_steps: list[list[dict]], images: list[asset])。"""
    import pythoncom  # noqa: F401  仅用于类型/环境确认

    render_w = slides_meta[0]["render_w"]
    render_h = slides_meta[0]["render_h"]
    fmt = str(opts["export_format"] or "JPG").upper()
    ext = ".jpg" if fmt in ("JPG", "JPEG") else ".png"
    q = int(opts["webp_quality"])
    assets = []
    kept_steps = []
    total = len(slides_meta)
    for slide_idx, meta in enumerate(slides_meta, start=1):
        ctx.check("渲染第 %d/%d 页" % (slide_idx, total))
        t_slide = time.monotonic()
        slide = pres.Slides(slide_idx)
        shapes = _slide_shapes_by_id(slide, ctx)
        plan = meta["plan"]
        kept = []
        deduped = 0
        prev_bytes = None
        # 进度按**已渲染页数比例**推进（DESIGN §5.1）：5 → 85
        ctx.progress(5 + int(80.0 * (slide_idx - 1) / total), "渲染页面 %d/%d" % (slide_idx, total))
        try:
            for k, step in enumerate(plan["steps"]):
                ctx.check("渲染第 %d 页第 %d 步" % (slide_idx, k + 1))
                for sid, visible in step["visible"].items():
                    shape = shapes.get(int(sid))
                    if shape is None:
                        continue
                    _set_shape_visible(shape, visible, ctx, sid)
                jpg_path = os.path.join(tmp_dir, "n%03d_s%02d%s" % (slide_idx, k, ext))
                _export_slide(slide, jpg_path, fmt, render_w, render_h)
                data = _read_bytes(jpg_path)
                if prev_bytes is not None and data == prev_bytes:
                    deduped += 1
                    try:
                        os.remove(jpg_path)
                    except OSError:
                        pass
                    continue
                prev_bytes = data
                name = "s%d-%d.webp" % (slide_idx, len(kept) + 1)
                out_path = os.path.join(assets_dir, name)
                w, h, size, quality = _save_webp(jpg_path, out_path, opts)
                if size > int(opts["image_max_bytes"]):
                    ctx.warn("主图超过 %dKB（%s: %dKB, q=%d）"
                             % (int(opts["image_max_bytes"]) // 1024, name,
                                size // 1024, quality))
                kept.append({"orig": k, "name": name, "w": w, "h": h, "size": size})
                assets.append({"name": name, "path": out_path, "size": size,
                               "content_type": "image/webp", "kind": "image"})
                try:
                    os.remove(jpg_path)
                except OSError:
                    pass
        finally:
            # 恢复可见性（避免影响 SaveCopyAs / 下一页）
            for sid in plan["animated_ids"]:
                shape = shapes.get(int(sid))
                if shape is not None:
                    try:
                        if not bool(shape.Visible):
                            shape.Visible = True
                    except Exception:  # noqa: BLE001
                        pass
        if not kept:  # 理论上第一步必保留
            raise ConvertError("第 %d 页没有可用渲染图" % slide_idx)
        # 缩略图：第一张保留的 step 图 → 宽 400（DESIGN §5.1：≤25KB）
        thumb_name = "t%d.webp" % slide_idx
        thumb_path = os.path.join(assets_dir, thumb_name)
        tw, th, tsize, tq = _make_thumb(os.path.join(assets_dir, kept[0]["name"]),
                                        thumb_path, opts)
        if tsize > int(opts["thumb_max_bytes"]):
            ctx.warn("缩略图超过 %dKB（%s: %dKB, q=%d）"
                     % (int(opts["thumb_max_bytes"]) // 1024, thumb_name, tsize // 1024, tq))
        assets.append({"name": thumb_name, "path": thumb_path, "size": tsize,
                       "content_type": "image/webp", "kind": "image"})
        kept_steps.append(kept)
        ctx.progress(5 + int(80.0 * slide_idx / total), "渲染页面 %d/%d" % (slide_idx, total))
        ctx.log("slide %d/%d: %d step（去重 %d）%.0fms"
                % (slide_idx, total, len(kept), deduped,
                   (time.monotonic() - t_slide) * 1000))
    return kept_steps, assets


def _collect_slides_meta(ctx, pres, opts, tmp_dir):
    """读取每页：页尺寸 / 动画 / 切换 / 备注 / COM 媒体形状 / 渲染尺寸 / step 计划。"""
    try:
        slide_count = int(pres.Slides.Count)
    except Exception as exc:  # noqa: BLE001
        raise ConvertError("无法读取页数：%s" % exc.__class__.__name__)
    if slide_count <= 0:
        raise ConvertError("演示文稿没有幻灯片")
    max_slides = int(opts["max_slides"])
    if slide_count > max_slides:
        raise ConvertError("页数过多（%d 页，上限 %d 页）" % (slide_count, max_slides))
    try:
        slide_w_pt = float(pres.PageSetup.SlideWidth)
        slide_h_pt = float(pres.PageSetup.SlideHeight)
    except Exception as exc:  # noqa: BLE001
        raise ConvertError("无法读取页面尺寸：%s" % exc.__class__.__name__)
    render_w, render_h = pptx_xml.render_target(slide_w_pt, slide_h_pt,
                                                int(opts["display_width"]))
    ctx.log("页面 %.0fx%.0f pt → 渲染 %dx%d px" % (slide_w_pt, slide_h_pt,
                                                render_w, render_h))
    slides_meta = []
    for i in range(1, slide_count + 1):
        ctx.check("读取第 %d 页" % i)
        try:
            slide = pres.Slides(i)
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("读取第 %d 页失败：%s" % (i, exc.__class__.__name__))
        entry_effect = _slide_transition(slide, ctx)
        effects = _slide_effects(slide, ctx)
        plan = pptx_xml.plan_steps(effects, int(opts["max_steps_per_slide"]))
        slides_meta.append({
            "index": i,
            "transition": entry_effect,
            "effects": effects,
            "plan": plan,
            "notes": _slide_notes(slide, ctx, int(opts["notes_max_chars"])),
            "com_media": _slide_com_media(slide, slide_w_pt, slide_h_pt, ctx),
            "render_w": render_w,
            "render_h": render_h,
        })
    # 整份图片预算（资产张数 = 每页 step 图 + 每页 thumb）
    planned = sum(len(m["plan"]["steps"]) for m in slides_meta)
    budget = int(opts["max_images"])
    if planned + slide_count > budget:
        keep = 2 if (slide_count * 3) <= budget else 1
        if keep == 1 and slide_count * 2 > budget:
            ctx.warn("幻灯片过多：%d 页 × 1 步 + thumb = %d 张，超过资产上限 %d；"
                     "完整性优先，仍全部导出" % (slide_count, slide_count * 2, budget))
        for m in slides_meta:
            if len(m["plan"]["steps"]) > keep:
                m["plan"]["steps"] = pptx_xml.degrade_plan(m["plan"]["steps"], keep)
                m["degraded"] = True
        ctx.log("资产上限降级：每页保留 %d 步（planned=%d, slides=%d, budget=%d）"
                % (keep, planned, slide_count, budget))
    total_steps = sum(len(m["plan"]["steps"]) for m in slides_meta)
    ctx.log("计划：%d 页 / %d 步（页 step 上限 %d）"
            % (slide_count, total_steps, int(opts["max_steps_per_slide"])))
    if slide_count >= 60:
        # DESIGN §5.1：页数较多时转换耗时是主因，>=60 页在日志里明确记录耗时
        ctx.log("大 deck（%d 页）：按每页 0.3–0.8s 估算纯渲染约 %d–%d 秒，"
                "结束时记录真实耗时" % (slide_count, int(slide_count * 0.3),
                                      int(slide_count * 0.8)))
    return slides_meta, slide_w_pt, slide_h_pt, render_w, render_h


def _match_media_step(meta, pic, ctx):
    """pptx pic → COM 媒体形状 id → 该媒体第一个可见 step 的原序号。"""
    name = (pic.get("name") or "").strip().lower()
    target = None
    for item in meta.get("com_media") or []:
        if name and item["name"].strip().lower() == name:
            target = item
            break
    if target is None and pic.get("rect"):
        best = None
        for item in meta.get("com_media") or []:
            if not item.get("rect"):
                continue
            d = sum(abs(float(item["rect"][c]) - float(pic["rect"][c]))
                    for c in ("x", "y", "w", "h"))
            if best is None or d < best[0]:
                best = (d, item)
        if best is not None and best[0] <= 0.08:
            target = best[1]
    sid = target["id"] if target else None
    steps = meta["plan"]["steps"]
    if sid is None:
        return 0
    for k, step in enumerate(steps):
        if step["visible"].get(sid):
            return k
    return len(steps) - 1


def _extract_media_assets(ctx, pres, slides_meta, kept_steps, assets_dir, tmp_dir, opts):
    """SaveCopyAs 解包媒体 → ffmpeg 转码 → 返回 (media_assets, media_table, hotspots)。

    ``media_assets``: name -> asset dict；``media_table``: manifest.media 数组；
    ``hotspots``: list[(slide_idx0, step_index0, hotspot_dict)]
    """
    if not bool(opts["with_media"]):
        return {}, [], []
    copy_path = os.path.join(tmp_dir, "media_copy.pptx")
    try:
        pres.SaveCopyAs(copy_path)
    except Exception as exc:  # noqa: BLE001
        ctx.warn("SaveCopyAs 失败，跳过媒体抽取：%s" % exc.__class__.__name__)
        return {}, [], []
    if not zipfile.is_zipfile(copy_path):
        ctx.warn("SaveCopyAs 产物不是有效 zip，跳过媒体抽取")
        return {}, [], []
    try:
        media_shapes = pptx_xml.read_media_shapes(copy_path)
    except Exception as exc:  # noqa: BLE001
        ctx.warn("pptx 媒体解析失败：%s" % exc.__class__.__name__)
        return {}, [], []
    if not media_shapes:
        ctx.log("未发现内嵌视频/音频")
        return {}, [], []
    ctx.log("发现内嵌媒体形状 %d 个" % len(media_shapes))

    ffmpeg = _find_tool("ffmpeg", opts.get("ffmpeg"))
    ffprobe = _find_tool("ffprobe", opts.get("ffprobe"))
    media_assets = {}
    media_table = []
    hotspots = []
    total_dur = 0.0
    seen_media = {}
    for ms in media_shapes:
        if ms.get("external"):
            ctx.warn("外链媒体（跳过，不报错）：%s" % (ms.get("media") or "")[:120])
            continue
        key = (ms["kind"], ms["media"])
        asset = seen_media.get(key)
        if asset is None:
            if len(media_assets) >= int(opts["max_media_files"]):
                ctx.warn("媒体文件数超过上限 %d，跳过 %s"
                         % (int(opts["max_media_files"]), ms["media"]))
                continue
            data = pptx_xml.read_media_bytes(copy_path, ms["media"])
            if data is None:
                ctx.warn("媒体文件在包内缺失：%s" % ms["media"])
                continue
            src_media = os.path.join(tmp_dir, "media_src_" + os.path.basename(ms["media"]))
            with open(src_media, "wb") as fh:
                fh.write(data)
            del data
            if os.path.getsize(src_media) > int(opts["max_media_file_bytes"]):
                ctx.warn("媒体文件过大（>%dMB），跳过：%s"
                         % (int(opts["max_media_file_bytes"]) // (1024 * 1024), ms["media"]))
                continue
            name = "m%d%s" % (len(media_assets), _media_ext(ms["kind"]))
            dst_path = os.path.join(assets_dir, name)
            info = _transcode_media(ffmpeg, ffprobe, src_media, ms["kind"], dst_path,
                                    ctx, opts)
            try:
                os.remove(src_media)
            except OSError:
                pass
            if info is None:
                continue
            dur = float(info.get("dur") or 0.0)
            if total_dur + dur > float(opts["max_media_total_duration_s"]):
                ctx.warn("媒体总时长超过 %d 分钟，跳过 %s"
                         % (int(opts["max_media_total_duration_s"]) // 60, ms["media"]))
                try:
                    os.remove(dst_path)
                except OSError:
                    pass
                continue
            total_dur += dur
            size = os.path.getsize(dst_path)
            asset = {"name": name, "path": dst_path, "size": size,
                     "content_type": "video/mp4" if ms["kind"] == "v" else "audio/mp4",
                     "kind": "media"}
            media_assets[name] = asset
            seen_media[key] = asset
            media_table.append({"s": name, "k": ms["kind"],
                                "w": int(info.get("w") or 0),
                                "h": int(info.get("h") or 0),
                                "dur": round(dur, 1)})
            ctx.log("media %s: %s ▸ %s (%.1fs)" % (name, ms["media"], name, dur))
        # 定位 step：媒体形状首次可见的 step；去重后的图映射到最近的保留 step
        slide_idx0 = int(ms["slide"]) - 1
        if slide_idx0 < 0 or slide_idx0 >= len(slides_meta):
            continue
        meta = slides_meta[slide_idx0]
        target_orig = _match_media_step(meta, ms, ctx)
        kept = kept_steps[slide_idx0]
        chosen = None
        for info in kept:
            if info["orig"] <= target_orig:
                chosen = info
            else:
                break
        if chosen is None:
            chosen = kept[0]
        step_no = kept.index(chosen)  # manifest steps 下标（0-based）
        rect = ms.get("rect") or {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        hotspot = {"s": asset["name"], "k": ms["kind"],
                   "x": float(rect["x"]), "y": float(rect["y"]),
                   "w": float(rect["w"]), "h": float(rect["h"])}
        hotspots.append((slide_idx0, step_no, hotspot))
        ctx.log("hotspot slide %d step %d: %s %.2f,%.2f,%.2f,%.2f"
                % (slide_idx0 + 1, step_no + 1, asset["name"],
                   hotspot["x"], hotspot["y"], hotspot["w"], hotspot["h"]))
    return media_assets, media_table, hotspots


def _build_manifest(opts, slides_meta, kept_steps, media_table, hotspots,
                    render_w, render_h, src_ext):
    deck_id = str(opts["deck_id"])
    manifest = {
        "v": 1,
        "base": "",  # buildId 算出后补
        "src": "%s%s%s/source%s" % (str(opts["oss_base"]), SRC_PREFIX, deck_id, src_ext),
        "w": int(render_w),
        "h": int(render_h),
        "slides": [],
        "media": media_table,
    }
    for meta, kept in zip(slides_meta, kept_steps):
        tr = pptx_xml.map_transition(meta["transition"])
        steps = []
        for info in kept:
            steps.append({"img": info["name"], "media": []})
        manifest["slides"].append({
            "tr": tr["tr"],
            "trd": tr["trd"],
            "notes": meta["notes"],
            "thumb": "t%d.webp" % meta["index"],
            "steps": steps,
        })
    for slide_idx0, step_idx, hotspot in hotspots:
        try:
            manifest["slides"][slide_idx0]["steps"][step_idx]["media"].append(hotspot)
        except (IndexError, KeyError):
            continue
    return manifest


def _cleanup_tmp(tmp_dir, keep_intermediate):
    if keep_intermediate:
        return
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except OSError:
        pass


def convert_deck(src_path, work_dir, opts=None):
    """把 PPT/PPTX 转换成分步图片 + 媒体资产 + manifest。

    :param src_path: 源文件路径（.ppt / .pptx）
    :param work_dir: 工作目录（建议每 deck 独立，转换后清理）；内部创建 ``assets/`` 与 ``tmp/``
    :param opts: 见 ``DEFAULT_OPTIONS``；也可传 dataclass/Namespace
    :returns: dict（见模块 docstring）
    """
    opts = normalize_options(opts)
    log = opts.pop("log", None) if isinstance(opts, dict) else None
    ctx = _Ctx(opts, log=log, progress=opts.get("progress"))
    t0 = time.monotonic()
    src_path = os.path.abspath(str(src_path))
    if not os.path.exists(src_path):
        raise ConvertError("源文件不存在：%s" % os.path.basename(src_path))
    src_ext = os.path.splitext(src_path)[1].lower()
    if src_ext not in (".ppt", ".pptx"):
        raise ConvertError("不支持的文件类型：%s（仅 .ppt/.pptx）" % (src_ext or "无扩展名"))
    work_dir = os.path.abspath(str(work_dir))
    assets_dir = os.path.join(work_dir, "assets")
    tmp_dir = os.path.join(work_dir, "tmp")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(assets_dir, exist_ok=True)
    os.makedirs(tmp_dir, exist_ok=True)

    # COM 对象统一放 holder：收尾时先清 holder 再 Quit/反初始化（见 _quiet_shutdown）
    com = {"app": None, "pres": None}
    pythoncom = None
    try:
        ctx.progress(2, "检查 PowerPoint")
        ctx.check("启动")
        # 临时副本：只读打开，避免用户文件被占用/改动
        local_copy = os.path.join(tmp_dir, "source" + src_ext)
        try:
            shutil.copyfile(src_path, local_copy)
        except OSError as exc:
            raise ConvertError("读取源文件失败：%s" % exc.__class__.__name__)
        try:
            import pythoncom as _pythoncom  # noqa: F401
            pythoncom = _pythoncom
            pythoncom.CoInitialize()
        except ImportError:  # pragma: no cover
            raise ConvertError("缺少 pywin32（pythoncom）")
        com["app"] = _acquire_powerpoint(ctx)
        ctx.log("PowerPoint 就绪（启动+打开准备 %.0fms）"
                % (1000 * (time.monotonic() - t0)))
        ctx.progress(4, "打开演示文稿")
        try:
            com["pres"] = com["app"].Presentations.Open(local_copy, True, False, False)
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("PowerPoint 无法打开该文件（可能加密/损坏）：%s"
                               % exc.__class__.__name__)
        pres = com["pres"]
        ctx.log("已打开：%s" % os.path.basename(src_path))
        slides_meta, slide_w_pt, slide_h_pt, render_w, render_h = _collect_slides_meta(
            ctx, pres, opts, tmp_dir)
        kept_steps, assets = _render_slides(ctx, pres, slides_meta, assets_dir,
                                            tmp_dir, opts)
        ctx.progress(80, "抽取媒体")
        media_assets, media_table, hotspots = _extract_media_assets(
            ctx, pres, slides_meta, kept_steps, assets_dir, tmp_dir, opts)
        for asset in media_assets.values():
            assets.append(asset)
        manifest = _build_manifest(opts, slides_meta, kept_steps, media_table,
                                   hotspots, render_w, render_h, src_ext)
        # buildId：资产名+大小 + manifest（不含 base）
        build_id = pptx_xml.compute_build_id(assets, manifest)
        prefix = "%s%s/%s/" % (ASSET_PREFIX, opts["deck_id"], build_id)
        manifest["base"] = str(opts["oss_base"]) + prefix
        errors = pptx_xml.validate_manifest(manifest)
        if errors:
            raise ConvertError("manifest 校验失败：%s" % "; ".join(errors[:4]))
        step_count = sum(len(slide["steps"]) for slide in manifest["slides"])
        image_count = sum(1 for asset in assets if asset.get("kind") == "image")
        stats = {
            "slides": len(manifest["slides"]),
            "steps": step_count,
            "images": image_count,
            "media": len(media_table),
            "elapsed_s": round(time.monotonic() - t0, 2),
            "render_w": int(render_w),
            "render_h": int(render_h),
            "build_prefix": prefix,
            "planned_steps": sum(len(m["plan"]["steps"]) for m in slides_meta),
            "degraded_slides": sum(1 for m in slides_meta if m.get("degraded")),
            "warnings": len(ctx.warnings),
        }
        ctx.progress(90, "转换完成")
        ctx.log("完成：%d 页 / %d 步 / %d 图片 / %d 媒体，耗时 %s，build=%s"
                % (stats["slides"], stats["steps"], stats["images"], stats["media"],
                   _fmt_seconds(stats["elapsed_s"]), build_id))
        return {
            "manifest": manifest,
            "assets": assets,
            "build_id": build_id,
            "stats": stats,
            "warnings": ctx.warnings,
            "aspect": pptx_xml.aspect_label(render_w, render_h),
            "slide_count": len(manifest["slides"]),
            "step_count": step_count,
            "cover": manifest["slides"][0]["thumb"] if manifest["slides"] else "",
            "src_ext": src_ext,
            "source_key": "%s%s%s/source%s" % (SRC_PREFIX, opts["deck_id"], "", src_ext),
            "render_w": int(render_w),
            "render_h": int(render_h),
        }
    finally:
        # 关键：先把局部 pres 引用放进 holder，再统一清理；否则调用方局部变量
        # 会在 Quit 之后才 Release，偶发卡 ~60s。
        try:
            del pres
        except NameError:
            pass
        _quiet_shutdown(com, ctx)
        try:
            import gc

            gc.collect()
        except Exception:  # noqa: BLE001
            pass
        if pythoncom is not None:
            t_un = time.monotonic()
            try:
                pythoncom.CoUninitialize()
            except Exception:  # noqa: BLE001
                pass
            ctx.log("COM 反初始化 %.0fms" % ((time.monotonic() - t_un) * 1000))
        _cleanup_tmp(tmp_dir, bool(opts.get("keep_intermediate")))


# ---------------------------------------------------------------------------
# CLI（联调用：python convert.py <src.pptx> --deck-id ddemo）
# ---------------------------------------------------------------------------
def _main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="PPT → 分步图片/媒体/manifest 转换（本机）")
    parser.add_argument("src", help="源 .ppt/.pptx 路径")
    parser.add_argument("--work-dir", default="", help="工作目录（默认 web/ppt/work/<basename>）")
    parser.add_argument("--deck-id", default="testdeck")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--no-media", action="store_true", help="跳过媒体抽取")
    parser.add_argument("--keep-intermediate", action="store_true")
    parser.add_argument("--json-out", default="", help="把结果摘要写到该文件")
    parser.add_argument("--opts-json", default="", help="从 JSON 文件加载全部转换选项")
    args = parser.parse_args(argv)

    src = os.path.abspath(args.src)
    work = os.path.abspath(args.work_dir or os.path.join(
        HERE, "work", "cli-" + os.path.splitext(os.path.basename(src))[0]))
    opts = {}
    if args.opts_json:
        try:
            with open(args.opts_json, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                opts.update(loaded)
        except (OSError, ValueError) as exc:
            print("[convert] FAIL: 读取 --opts-json 失败：%s" % exc)
            return 1
    opts.update({
        "deck_id": args.deck_id,
        "timeout_s": args.timeout,
        "with_media": not args.no_media,
        "keep_intermediate": args.keep_intermediate,
        "log": opts.get("log") or (lambda msg: print("[convert] " + msg, flush=True)),
    })
    t0 = time.time()
    try:
        result = convert_deck(src, work, opts)
    except ConvertBusyError as exc:
        print("[convert] BUSY: %s" % exc)
        return 2
    except ConvertError as exc:
        print("[convert] FAIL: %s" % exc)
        return 1
    summary = {
        "ok": True,
        "manifest": result["manifest"],
        "build_id": result["build_id"],
        "stats": result["stats"],
        "warnings": result["warnings"],
        "aspect": result["aspect"],
        "slide_count": result["slide_count"],
        "step_count": result["step_count"],
        "cover": result["cover"],
        "src_ext": result["src_ext"],
        "source_key": result["source_key"],
        "render_w": result["render_w"],
        "render_h": result["render_h"],
        "assets": [{"name": a["name"], "path": a["path"], "size": a["size"],
                    "content_type": a.get("content_type"), "kind": a.get("kind")}
                   for a in result["assets"]],
        "work_dir": work,
        "total_s": round(time.time() - t0, 2),
    }
    print(json.dumps({k: v for k, v in summary.items() if k != "manifest"},
                     ensure_ascii=False, indent=2))
    print("manifest slides:", len(summary["manifest"]["slides"]))
    out = args.json_out or os.path.join(work, "convert_result.json")
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=1)
        print("结果已写入:", out)
    except OSError as exc:
        print("写结果失败:", exc)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main())
