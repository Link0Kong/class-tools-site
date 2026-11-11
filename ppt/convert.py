# -*- coding: utf-8 -*-
"""convert.py — PowerPoint COM 转换核心（本机）

契约唯一真源：``web/ppt/CONTRACT.md``（§5 manifest / §6 转换机 / §7 切换映射 /
§11 v1.2 原样播放视频）。

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
6. **v1.2 原样播放视频**（CONTRACT §11.2）：在**临时副本**（绝不保存用户源文件）上
   计算每页 ``animEnd``/``mediaMaxDur`` → ``advance``，设置
   ``SlideShowTransition.AdvanceOnClick=False/AdvanceOnTime=True/AdvanceTime=advance``，
   内嵌媒体 ``AnimationSettings.PlaySettings.PlayOnEntry=True`` → ``CreateVideo(...)``
   轮询完成 → ffmpeg remux/faststart（≥40MB 重编码控体积）→ ``deck.mp4`` + ``manifest.video``
   （含按页章节时间）；失败/超时/超限只跳过视频并记 warning，**不影响分步模式 ready**；
7. 组装 CONTRACT §5 manifest + 资产清单，计算 buildId（base 目录前置）。

不变量：单任务 30 分钟（``timeout_s``，分步检查）；只结束本函数自己创建的
PowerPoint 实例（开始前若已有实例且 Presentations.Count>0 直接跳过）。

``convert_deck(src_path, work_dir, opts)`` 返回::

    {"manifest": {...}, "assets": [{"name","path","size","content_type","kind"}...],
     "build_id": "...", "stats": {...}, "warnings": [...], "aspect": "16:9",
     "slide_count": n, "step_count": n, "cover": "t1.webp", "src_ext": ".pptx",
     "video": {...}|None}

``export_video_only(src_path, work_dir, opts)``（``agent.py --video-only`` 用）只导出
原样播放视频，不渲染图片、不抽取/上传媒体资产；返回::

    {"video": {...}|None, "assets": [deck.mp4 asset], "stats": {...},
     "warnings": [...], "skipped": "原因", "export_s": 1.2}
"""
import hashlib
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
    "timeout_s": 1800.0,               # CONTRACT §11.2.2：单 deck 转换预算放宽到 30min
    "with_media": True,
    "max_media_file_bytes": 200 * 1024 * 1024,
    "max_media_total_duration_s": 30 * 60,
    "max_media_trim_s": 30 * 60,       # 单段过长只转前 30min（DESIGN §5.1）
    "max_media_files": 60,
    # v1.2 原样播放视频（CONTRACT §11.1/§11.2）：PowerPoint CreateVideo 高保真导出
    "video": True,                     # False=跳过原样播放视频（只留分步模式）
    "video_resolution": 720,           # CreateVideo VertResolution（720p）
    "video_fps": 30,
    "video_quality": 80,               # CreateVideo Quality（0-100）
    "video_default_slide_duration": 5, # CreateVideo 默认页时长（我们逐页覆盖 advance）
    "video_export_timeout_s": 1800.0,  # 轮询 CreateVideo 完成的最长时间（契约 30min）
    "video_timeout_reserve_s": 45.0,   # 为 PowerPoint 收尾预留的秒数
    "video_max_slides": 120,           # 超过页数不生成视频（契约 §11.2.2）
    "video_max_duration_s": 1800.0,    # 预估总时长上限 30min
    "video_min_advance_s": 3.0,        # 每页最短停留
    "video_advance_pad_s": 1.5,        # 动画/媒体结束后留白
    "video_max_advance_s": 600.0,      # 单页最长
    "video_faststart_only_bytes": 40 * 1024 * 1024,  # <40MB 只 remux；≥40MB 重编码控体积
    "video_reencode_crf": 24,          # 重编码 CRF（720p 保持）
    "video_reencode_audio_kbps": 96,   # 重编码 AAC 码率
    "video_tag": "720p",               # manifest.video.q 展示标签
    # v2.0 compat 兼容性处理（CONTRACT §12）：不降质标准化 + 字体嵌入 + PDF + 封面
    "compat_embed_fonts": True,        # SaveAs(...,EmbedFonts=msoTrue) 嵌入 TrueType 字体
    "compat_pdf": True,                # 导出 preview.pdf（SaveAs ppSaveAsPDF）
    "compat_cover_width": 1600,        # cover.webp 渲染宽（最长边 1600）
    "compat_filename_max": 80,         # 下载文件名最大字符数
    "compat_pdf_pages_fallback": True, # pypdf 不可用时 PDF 页数按幻灯片数填写（记 warning）
    # v2.2 媒体编码兼容（CONTRACT §12.7）：h264+aac 保留；容器不兼容 remux；编码不兼容高保真转码
    "compat_media_compat": True,
    "compat_media_max_bytes": 200 * 1024 * 1024,   # 单文件 >200MiB 不转换
    "compat_media_max_dur_s": 30 * 60.0,           # 单段 >30min 不转换
    "compat_media_max_total_dur_s": 60 * 60.0,     # 总时长 >60min 不转换
    "compat_media_ffmpeg_timeout": 900,            # 单个媒体转码/remux 超时（秒）
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


def _wait_powerpoint_exit(ctx, timeout_s=120.0, stage=""):
    """等待 POWERPNT 进程完全退出（Quit 后可能延迟数秒~数分钟）。超时返回 False。"""
    started = time.monotonic()
    while time.monotonic() - started < float(timeout_s):
        if _powerpnt_process_count() == 0:
            ctx.log("PowerPoint 进程已退出（等待 %.1fs%s）"
                    % (time.monotonic() - started, "，" + stage if stage else ""))
            return True
        time.sleep(1.0)
    return False


def _automation_powerpoint_pids():
    """返回 ``/AUTOMATION`` 启动的 POWERPNT 进程 PID 列表（只清理 COM 自动化实例）。"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='POWERPNT.EXE'\" | "
             "Where-Object { $_.CommandLine -like '*AUTOMATION*' } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=20,
            creationflags=CREATE_NO_WINDOW)
        return [int(token) for token in (proc.stdout or "").split() if token.strip().isdigit()]
    except Exception:  # noqa: BLE001
        return []


def _kill_lingering_powerpoint(ctx, grace_s=3.0):
    """``Quit()`` 后 PowerShell 自动化实例偶发滞留 ~60s（Office RPC 清理卡顿）。

    先给 ``grace_s`` 秒自然退出；仍滞留则**强制结束 /AUTOMATION 实例**（无文档、
    文件已保存，不会丢数据；用户手动打开的 PowerPoint 不带 /AUTOMATION，不会被误杀）。
    返回强制结束的进程数（0=自然退出，-1=未找到可清理实例）。
    """
    deadline = time.monotonic() + max(0.0, float(grace_s))
    while time.monotonic() < deadline:
        if _powerpnt_process_count() == 0:
            return 0
        time.sleep(0.2)
    if _powerpnt_process_count() == 0:
        return 0
    pids = _automation_powerpoint_pids()
    killed = 0
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=20,
                           creationflags=CREATE_NO_WINDOW)
            killed += 1
        except Exception:  # noqa: BLE001
            pass
    if killed:
        ctx.log("PowerPoint 自动化实例 Quit 后滞留 → 强制结束 %d 个"
                "（无文档，Office RPC 清理卡顿兜底）" % killed)
        _wait_powerpoint_exit(ctx, 10.0, "强制结束后")
        return killed
    ctx.warn("PowerPoint 进程滞留且未找到 /AUTOMATION 实例，保留（下一轮等待/跳过）")
    return -1


def _probe_idle_app(ctx, app):
    """探测「空闲实例」是否真的可用：Add 一个临时空白演示文稿再关掉。

    实测（2026-11-10）：``Quit()`` 后进程仍在慢退出时，ROT 可能返回一个
    ``Presentations.Count==0`` 的**半断开**实例；它能读 Count 但后续
    ``Presentations.Open`` 会报「接口未知」。这种实例不能复用，必须等它退出后重建。
    """
    pres = None
    try:
        pres = app.Presentations.Add()
        count = int(app.Presentations.Count)
        try:
            pres.Close()
        except Exception:  # noqa: BLE001
            pass
        pres = None
        return count > 0
    except Exception as exc:  # noqa: BLE001
        ctx.log("空闲 PowerPoint 实例探测失败（%s），等待其退出后重建"
                % exc.__class__.__name__)
        if pres is not None:
            try:
                pres.Close()
            except Exception:  # noqa: BLE001
                pass
        return False


def _acquire_powerpoint(ctx):
    """确保拿到一个**没有文档且可用**的 PowerPoint 实例（空实例先 Quit 再重建）。

    实测（2026-11-10）：
    * ``Quit()`` 返回后 POWERPNT.EXE 可能还要数秒~数分钟才真正退出（视频/PDF 导出后尤慢），
      期间 ROT 可能返回半断开的空闲实例（能读 Count，但 ``Presentations.Open`` 报「接口未知」）；
    * 因此**不复用**空闲实例：先 Quit，再等旧进程彻底退出，才 DispatchEx 新建，
      避免「孤儿实例被复用后 app 中途失效」与「Quit/DispatchEx 竞态崩溃」。
    """
    app = _existing_powerpoint()
    if app is not None:
        try:
            count = int(app.Presentations.Count)
        except Exception:  # noqa: BLE001
            raise ConvertBusyError("PowerPoint 无响应（COM RPC 繁忙），本轮跳过")
        if count > 0:
            raise ConvertBusyError("PowerPoint 正打开 %d 个文档（用户占用），本轮跳过" % count)
        ctx.log("发现空闲 PowerPoint 实例 → Quit 后重建（不复用，避免半断开实例）")
        try:
            app.Quit()
        except Exception:  # noqa: BLE001
            pass
        app = None
        try:
            import gc

            gc.collect()  # 释放代理
        except Exception:  # noqa: BLE001
            pass
        _kill_lingering_powerpoint(ctx, grace_s=5.0)
        if not _wait_powerpoint_exit(ctx, 15.0, "旧空闲实例"):
            raise ConvertBusyError("PowerPoint 进程存在但无法连接，本轮跳过")
    if _powerpnt_process_count() > 0:
        ctx.log("检测到 POWERPNT 进程但暂时无法连接（可能正在退出），等待并清理 ...")
        _kill_lingering_powerpoint(ctx, grace_s=10.0)
        if not _wait_powerpoint_exit(ctx, 15.0, "等待残留进程"):
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
    quit_called = False
    if app is not None:
        try:
            try:
                count = int(app.Presentations.Count)
            except Exception:  # noqa: BLE001
                count = 0
            if count == 0:
                app.Quit()
                quit_called = True
                ctx.log("PowerPoint 退出 %.0fms" % ((time.monotonic() - t1) * 1000))
            else:
                ctx.warn("退出时检测到 PowerPoint 有 %d 个文档（用户新开或上次崩溃残留），保留实例；"
                         "若列表一直排队且日志出现 PowerPoint busy，请先确认无人编辑后结束 "
                         "POWERPNT.EXE" % count)
        except Exception:  # noqa: BLE001
            pass
    # 注意顺序：**持有 app 代理时先清理滞留进程**；Quit 后立刻释放代理会卡 ~60s（RPC 清理）。
    if quit_called:
        _kill_lingering_powerpoint(ctx, grace_s=3.0)
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
                    "shape_id": -1, "trigger": 1, "duration": 0.0, "delay": 0.0}
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
            try:
                item["delay"] = float(eff.Timing.TriggerDelayTime)
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
    """返回 ``{"w","h","dur","codec","has_audio","audio_codec",...}``；失败返回 None。"""
    try:
        proc = _run_ffmpeg([ffprobe, "-v", "error",
                            "-show_streams", "-show_format", "-of", "json", path],
                           timeout=60)
        if proc.returncode != 0:
            return None
        info = pptx_xml.parse_ffprobe_json(proc.stdout or "")
        if info is None:
            return None
        return info
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
# v2.2 媒体编码兼容（CONTRACT §12.7）
# ---------------------------------------------------------------------------
def _media_limits(opts):
    return {
        "max_bytes": int(opts.get("compat_media_max_bytes") or 200 * 1024 * 1024),
        "max_single_dur": float(opts.get("compat_media_max_dur_s") or 1800.0),
        "max_total_dur": float(opts.get("compat_media_max_total_dur_s") or 3600.0),
    }


def _media_part_basename(part_name):
    return str(part_name or "").rsplit("/", 1)[-1]


def _media_probe_part(ffprobe, part_name, data, tmp_dir):
    """把包内媒体字节写临时文件 → ffprobe，返回 probe dict（失败 None）。"""
    ext = os.path.splitext(_media_part_basename(part_name))[1].lower()
    probe_path = os.path.join(tmp_dir, "media_probe" + (ext or ".bin"))
    try:
        with open(probe_path, "wb") as fh:
            fh.write(data)
        info = _ffprobe_info(ffprobe, probe_path)
    finally:
        _remove_quiet(probe_path)
    if info is None:
        return None
    out = dict(info)
    out["bytes"] = len(data)
    out["ext"] = ext
    out["part"] = part_name
    return out


def _media_encode(ctx, ffmpeg, src_path, plan, src_info, dst_path, timeout):
    """按策略执行 remux/transcode；成功返回输出 probe，失败 None（记 warning）。"""
    kind = plan.get("kind")
    action = plan.get("action")
    has_audio = bool(src_info.get("has_audio"))
    base = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src_path]
    if action == "remux":
        cmd = base + ["-map", "0:v:0", "-map", "0:a?", "-c", "copy",
                      "-movflags", "+faststart", dst_path]
    elif kind == "audio":
        cmd = base + ["-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "192k",
                      "-movflags", "+faststart", dst_path]
    else:
        cmd = base + ["-map", "0:v:0", "-map", "0:a?",
                      "-c:v", "libx264", "-profile:v", "high", "-crf", "18",
                      "-preset", "medium", "-pix_fmt", "yuv420p"]
        cmd += (["-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"])
        cmd += ["-movflags", "+faststart", dst_path]
    try:
        proc = _run_ffmpeg(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        ctx.warn("compat: 媒体 %s %s 超时（%ss）"
                 % (_media_part_basename(src_info.get("part") or ""), action, timeout))
        _remove_quiet(dst_path)
        return None
    if proc.returncode != 0 or not os.path.exists(dst_path) or os.path.getsize(dst_path) <= 0:
        err = (proc.stderr or "").strip().splitlines()
        ctx.warn("compat: 媒体 %s %s 失败：%s"
                 % (_media_part_basename(src_info.get("part") or ""), action,
                    (err[-1] if err else "rc=%s" % proc.returncode)[:200]))
        _remove_quiet(dst_path)
        return None
    info = _ffprobe_info(_find_tool("ffprobe", ctx.opts.get("ffprobe")), dst_path)
    if info is None:
        ctx.warn("compat: 媒体 %s 输出无法解析，保留原样"
                 % _media_part_basename(src_info.get("part") or ""))
        _remove_quiet(dst_path)
        return None
    out = dict(info)
    out["bytes"] = os.path.getsize(dst_path)
    return out


def _media_output_ok(plan, src_info, out_info):
    """转码/remux 输出校验：H.264/AAC、同分辨率、时长差 ≤0.3s、音轨存在性一致。"""
    if out_info is None:
        return False, "probe"
    kind = plan.get("kind")
    if kind == "audio":
        if str(out_info.get("audio_codec") or "").lower() != "aac":
            return False, "audio_codec"
        src_dur = float(src_info.get("dur") or 0.0)
        out_dur = float(out_info.get("dur") or 0.0)
        if src_dur > 0 and out_dur > 0 and abs(src_dur - out_dur) > 0.3:
            return False, "duration"
        return True, ""
    if str(out_info.get("codec") or "").lower() != "h264":
        return False, "vcodec"
    for key in ("w", "h"):
        if int(src_info.get(key) or 0) and int(out_info.get(key) or 0) != int(src_info.get(key)):
            return False, key
    src_dur = float(src_info.get("dur") or 0.0)
    out_dur = float(out_info.get("dur") or 0.0)
    if src_dur > 0 and out_dur > 0 and abs(src_dur - out_dur) > 0.3:
        return False, "duration"
    if bool(src_info.get("has_audio")) != bool(out_info.get("has_audio")):
        return False, "audio_presence"
    if out_info.get("has_audio") and str(out_info.get("audio_codec") or "").lower() != "aac":
        return False, "audio_codec"
    return True, ""


def _media_action_record(plan, src_info, out_info, file_name, bytes_before, bytes_after):
    return {
        "file": file_name,
        "kind": plan.get("kind"),
        "action": plan.get("action"),
        "vcodec_from": plan.get("vcodec_from") or "",
        "acodec_from": plan.get("acodec_from") or "",
        "vcodec_to": (str((out_info or {}).get("codec") or "") or plan.get("vcodec_from") or ""),
        "acodec_to": (str((out_info or {}).get("audio_codec") or "")
                      or plan.get("acodec_from") or ""),
        "width": int((out_info or src_info).get("w") or 0),
        "height": int((out_info or src_info).get("h") or 0),
        "dur": round(float((out_info or src_info).get("dur") or 0.0), 3),
        "bytes_before": int(bytes_before),
        "bytes_after": int(bytes_after),
        "lossless": bool(plan.get("lossless", True)),
    }


def _compat_media(ctx, compat_path, tmp_dir, opts):
    """对 compat 包内 ``ppt/media/*`` 音视频做编码兼容处理（CONTRACT §12.7）。

    返回 ``{"actions": [...], "summary": {...}, "changed": bool}``；
    只改媒体字节/容器与必要的 rels/Content_Types，绝不删媒体/改分辨率。
    """
    actions = []
    summary = {"total": 0, "kept": 0, "remux": 0, "transcode": 0}
    if not bool(opts.get("compat_media_compat", True)):
        ctx.log("compat: media 编码兼容处理已关闭（compat_media_compat=False）")
        return {"actions": actions, "summary": summary, "changed": False}
    try:
        zf = zipfile.ZipFile(compat_path)
    except (OSError, zipfile.BadZipFile) as exc:
        ctx.warn("compat: 媒体兼容处理跳过（包无法打开：%s）" % exc.__class__.__name__)
        return {"actions": actions, "summary": summary, "changed": False}
    try:
        names = zf.namelist()
        media_parts = [n for n in names
                       if n.startswith("ppt/media/") and not n.endswith("/")
                       and pptx_xml.media_kind_of(n)]
        media_names = set(n for n in names
                          if n.startswith("ppt/media/") and not n.endswith("/"))
        blobs = {part: zf.read(part) for part in media_parts}
    finally:
        zf.close()
    if not media_parts:
        ctx.log("compat: 包内无音视频媒体，跳过媒体编码兼容")
        return {"actions": actions, "summary": summary, "changed": False}
    ffmpeg = _find_tool("ffmpeg", opts.get("ffmpeg"))
    ffprobe = _find_tool("ffprobe", opts.get("ffprobe"))
    limits = _media_limits(opts)
    timeout = int(opts.get("compat_media_ffmpeg_timeout") or 900)
    total_dur = 0.0
    replacements = []
    t0 = time.monotonic()
    for part in sorted(media_parts):
        data = blobs[part]
        base_name = _media_part_basename(part)
        src_info = _media_probe_part(ffprobe, part, data, tmp_dir)
        if src_info is None:
            ctx.warn("compat: 媒体 %s 探测失败，未做编码兼容（原样保留）" % base_name)
            actions.append(_media_action_record(
                {"kind": pptx_xml.media_kind_of(part), "action": "keep",
                 "vcodec_from": "", "acodec_from": "", "lossless": True},
                {"w": 0, "h": 0, "dur": 0.0}, None, base_name, len(data), len(data)))
            summary["total"] += 1
            summary["kept"] += 1
            continue
        duration = float(src_info.get("dur") or 0.0)
        total_dur += duration
        plan = pptx_xml.classify_media(src_info, part, limits)
        if plan.get("action") != "keep" and total_dur > limits["max_total_dur"]:
            plan = dict(plan, action="keep", reason="media_total_too_long")
        if plan.get("action") == "keep":
            reason = plan.get("reason") or ""
            if reason in ("media_too_big", "media_too_long", "media_total_too_long"):
                ctx.warn("compat: 媒体 %s 过大/过长，未做编码兼容（原样保留）" % base_name)
            elif reason:
                ctx.warn("compat: 媒体 %s 未做编码兼容（%s，原样保留）"
                         % (base_name, reason))
            else:
                ctx.log("compat: 媒体 %s 已兼容（%s/%s），原字节保留"
                        % (base_name, src_info.get("codec") or "-",
                           src_info.get("audio_codec") or "无音频"))
            actions.append(_media_action_record(plan, src_info, None, base_name,
                                                len(data), len(data)))
            summary["total"] += 1
            summary["kept"] += 1
            continue
        ext = os.path.splitext(base_name)[1].lower()
        target_ext = plan.get("target_ext") or (".m4a" if plan.get("kind") == "audio"
                                                else ".mp4")
        src_tmp = os.path.join(tmp_dir, "media_src" + ext)
        dst_tmp = os.path.join(tmp_dir, "media_out" + target_ext)
        _remove_quiet(dst_tmp)
        try:
            with open(src_tmp, "wb") as fh:
                fh.write(data)
            out_info = _media_encode(ctx, ffmpeg, src_tmp, plan, src_info, dst_tmp, timeout)
        finally:
            _remove_quiet(src_tmp)
        ok, why = _media_output_ok(plan, src_info, out_info)
        if not ok:
            ctx.warn("compat: 媒体 %s %s 输出校验失败（%s），保留原样"
                     % (base_name, plan.get("action"), why))
            _remove_quiet(dst_tmp)
            actions.append(_media_action_record(plan, src_info, None, base_name,
                                                len(data), len(data)))
            summary["total"] += 1
            summary["kept"] += 1
            continue
        with open(dst_tmp, "rb") as fh:
            new_data = fh.read()
        bytes_after = len(new_data)
        _remove_quiet(dst_tmp)
        new_name = base_name
        if target_ext != ext:
            stem = os.path.splitext(base_name)[0]
            candidate = stem + target_ext
            seq = 1
            while candidate in media_names:
                candidate = "%s_%d%s" % (stem, seq, target_ext)
                seq += 1
            new_name = candidate
            media_names.add(new_name)
        new_part = "ppt/media/" + new_name
        replacements.append({"old": part, "new": new_part, "data": new_data,
                             "content_type": pptx_xml.MEDIA_CONTENT_TYPES.get(
                                 target_ext, "application/octet-stream")})
        actions.append(_media_action_record(plan, src_info, out_info, new_name,
                                            len(data), bytes_after))
        summary["total"] += 1
        if plan.get("action") == "remux":
            summary["remux"] += 1
        else:
            summary["transcode"] += 1
        ctx.log("compat: 媒体 %s %s → %s（%.2fMB → %.2fMB，%.0fs，lossless=%s）"
                % (base_name, plan.get("action"), new_name,
                   len(data) / 1048576.0, bytes_after / 1048576.0,
                   float((out_info or {}).get("dur") or 0.0), plan.get("lossless")))
    changed = False
    if replacements:
        result = pptx_xml.rewrite_package_media(compat_path, replacements)
        changed = bool(result.get("changed"))
        if changed:
            ctx.log("compat: 媒体编码兼容完成 %d 个（keep %d / remux %d / transcode %d），"
                    "耗时 %.1fs；已安全更新 rels/Content_Types"
                    % (summary["total"], summary["kept"], summary["remux"],
                       summary["transcode"], time.monotonic() - t0))
        else:
            ctx.warn("compat: 媒体包重写未生效（保留原样）")
    else:
        ctx.log("compat: 全部 %d 个媒体已兼容，字节未变" % summary["total"])
    return {"actions": actions, "summary": summary, "changed": changed}


# ---------------------------------------------------------------------------
# v1.2 原样播放视频（CONTRACT §11.1/§11.2）
# ---------------------------------------------------------------------------
CREATEVIDEO_STATUS_DONE = 3
CREATEVIDEO_STATUS_FAILED = 4


def _collect_video_slide_effects(ctx, pres):
    """只读每页 ``TimeLine.MainSequence``（视频-only 模式需要的最少信息）。"""
    try:
        slide_count = int(pres.Slides.Count)
    except Exception as exc:  # noqa: BLE001
        raise ConvertError("无法读取页数：%s" % exc.__class__.__name__)
    if slide_count <= 0:
        raise ConvertError("演示文稿没有幻灯片")
    max_slides = int(ctx.opts["max_slides"])
    if slide_count > max_slides:
        raise ConvertError("页数过多（%d 页，上限 %d 页）" % (slide_count, max_slides))
    effects_per_slide = []
    for i in range(1, slide_count + 1):
        ctx.check("读取第 %d 页动画" % i)
        try:
            slide = pres.Slides(i)
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("读取第 %d 页失败：%s" % (i, exc.__class__.__name__))
        effects_per_slide.append(_slide_effects(slide, ctx))
    return slide_count, effects_per_slide


def _probe_media_durations(ctx, copy_path, slide_count, tmp_dir, opts):
    """内嵌媒体**原始时长**（SaveCopyAs 包 → ffprobe，不转码）→ 每页最长秒数列表。

    用于 ``advance = mediaMaxDur + 1.5`` 的媒体页延长，避免 PowerPoint 自动延长
    破坏章节公式（CONTRACT §11.2）。
    """
    durations = [0.0] * max(0, int(slide_count or 0))
    try:
        media_shapes = pptx_xml.read_media_shapes(copy_path)
    except Exception as exc:  # noqa: BLE001
        ctx.warn("video: 媒体包解析失败（媒体时长按 0 计）：%s" % exc.__class__.__name__)
        return durations
    if not media_shapes:
        ctx.log("video: 未发现内嵌媒体")
        return durations
    ffprobe = _find_tool("ffprobe", opts.get("ffprobe"))
    max_bytes = int(opts.get("max_media_file_bytes") or 0)
    cache = {}
    for shape in media_shapes:
        if shape.get("external"):
            ctx.log("video: 外链媒体跳过时长探测：%s" % str(shape.get("media"))[:120])
            continue
        key = (shape.get("kind"), shape.get("media"))
        if key in cache:
            dur = cache[key]
        else:
            dur = 0.0
            try:
                data = pptx_xml.read_media_bytes(copy_path, shape["media"])
            except Exception:  # noqa: BLE001
                data = None
            if data is None:
                ctx.warn("video: 媒体文件缺失，时长按 0 计：%s" % str(shape.get("media"))[:120])
            elif max_bytes and len(data) > max_bytes:
                ctx.warn("video: 媒体文件过大（>%dMB），跳过时长探测：%s"
                         % (max_bytes // (1024 * 1024), str(shape.get("media"))[:120]))
            else:
                src = os.path.join(tmp_dir, "probe_" + os.path.basename(str(shape["media"])))
                try:
                    with open(src, "wb") as fh:
                        fh.write(data)
                    info = _ffprobe_info(ffprobe, src)
                    if info:
                        dur = max(0.0, float(info.get("dur") or 0.0))
                finally:
                    try:
                        os.remove(src)
                    except OSError:
                        pass
            cache[key] = dur
        try:
            idx = int(shape.get("slide") or 0) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(durations) and dur > durations[idx]:
            durations[idx] = dur
    if any(d > 0 for d in durations):
        ctx.log("video: 每页媒体最长时长 %s"
                % ", ".join("%d:%.1fs" % (i + 1, d) for i, d in enumerate(durations) if d > 0))
    return durations


def _collect_video_plan(ctx, pres, effects_per_slide, media_max_durs, opts):
    """计算每页 ``advance`` / 切换时长 / 预估总时长（只读 COM 属性，不改文档）。"""
    slide_count = len(effects_per_slide or [])
    advances = []
    trans_durs = []
    anim_ends = []
    media_durs = []
    for i in range(1, slide_count + 1):
        ctx.check("读取第 %d 页动画/切换时序" % i)
        try:
            slide = pres.Slides(i)
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("读取第 %d 页时序失败：%s" % (i, exc.__class__.__name__))
        entry_effect = 0
        trans_dur = 0.0
        try:
            transition = slide.SlideShowTransition
            entry_effect = int(transition.EntryEffect)
            if entry_effect != 0:  # 无切换记 0（CONTRACT §11.2）
                trans_dur = max(0.0, float(transition.Duration))
        except Exception as exc:  # noqa: BLE001
            ctx.warn("video: 读取第 %d 页切换时长失败（按 0 计）：%s"
                     % (i, exc.__class__.__name__))
        try:
            anim_end = pptx_xml.compute_anim_end(effects_per_slide[i - 1])
        except Exception:  # noqa: BLE001
            anim_end = 0.0
        try:
            media_max = max(0.0, float(media_max_durs[i - 1] or 0.0))
        except (IndexError, TypeError, ValueError):
            media_max = 0.0
        advance = pptx_xml.compute_advance(
            anim_end, media_max,
            float(opts.get("video_min_advance_s") or pptx_xml.VIDEO_MIN_ADVANCE_S),
            float(opts.get("video_advance_pad_s") or pptx_xml.VIDEO_ADVANCE_PAD_S),
            float(opts.get("video_max_advance_s") or pptx_xml.VIDEO_MAX_ADVANCE_S))
        advances.append(advance)
        trans_durs.append(round(trans_dur, 3))
        anim_ends.append(round(anim_end, 3))
        media_durs.append(round(media_max, 3))
        ctx.log("video: slide %d/%d animEnd=%.2fs media=%.2fs trans=%.2fs → advance=%.2fs"
                % (i, slide_count, anim_end, media_max, trans_dur, advance))
    estimated = sum(advances) + sum(trans_durs)
    return {"advances": advances, "trans_durs": trans_durs, "anim_ends": anim_ends,
            "media_durs": media_durs, "estimated_s": round(estimated, 2)}


def _open_writable_video_copy(ctx, app, pres, tmp_dir, reuse_path=""):
    """在**临时副本**上以可写方式打开演示文稿（绝不保存用户源文件）。返回 (pres, path)。"""
    copy_path = reuse_path or os.path.join(tmp_dir, "video_deck.pptx")
    if not (reuse_path and os.path.exists(reuse_path)):
        try:
            pres.SaveCopyAs(copy_path)
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("保存视频导出临时副本失败：%s" % exc.__class__.__name__)
    if not os.path.exists(copy_path) or os.path.getsize(copy_path) <= 0:
        raise ConvertError("视频导出临时副本为空")
    try:
        # ReadOnly=False → 可写；Untitled=False、WithWindow=False
        return app.Presentations.Open(copy_path, False, False, False), copy_path
    except Exception as exc:  # noqa: BLE001
        raise ConvertError("打开视频导出临时副本失败：%s" % exc.__class__.__name__)


def _delete_shape_effects(slide, shape_id):
    """删除某形状在 MainSequence 里的动画效果（删形状前清理，避免残留 timing）。"""
    try:
        seq = slide.TimeLine.MainSequence
        count = int(seq.Count)
    except Exception:  # noqa: BLE001
        return 0
    removed = 0
    for j in range(count, 0, -1):
        try:
            if int(seq.Item(j).Shape.Id) == int(shape_id):
                seq.Item(j).Delete()
                removed += 1
        except Exception:  # noqa: BLE001
            continue
    return removed


def _strip_external_media(ctx, pres, copy_path, tmp_dir):
    """移除**外链媒体**形状（CONTRACT §6：外链无法在网页播放）。

    实测（2026-11-10）：外链文件在本机不存在时，PowerPoint CreateVideo 会在该页
    等待约 90s 才继续，导致视频总时长与章节公式严重不符。这里在**临时副本**上把
    外链媒体形状导出为静态图（保留画面）后删除，避免导出被拖住。
    """
    try:
        shapes_info = pptx_xml.read_media_shapes(copy_path)
    except Exception as exc:  # noqa: BLE001
        ctx.warn("video: 读取媒体形状失败（外链媒体未清理）：%s" % exc.__class__.__name__)
        return 0
    externals = [item for item in shapes_info if item.get("external")]
    if not externals:
        return 0
    removed = 0
    for item in externals:
        try:
            slide_no = int(item.get("slide") or 0)
            shape_name = str(item.get("name") or "")
            slide = pres.Slides(slide_no)
            count = int(slide.Shapes.Count)
        except Exception:  # noqa: BLE001
            continue
        target = None
        for j in range(1, count + 1):
            try:
                shape = slide.Shapes(j)
                if int(shape.Type) != 16:  # msoMedia
                    continue
                if shape_name and str(shape.Name) == shape_name:
                    target = shape
                    break
            except Exception:  # noqa: BLE001
                continue
        if target is None:
            ctx.warn("video: 外链媒体形状未找到（第 %d 页 %r），无法清理"
                     % (slide_no, shape_name))
            continue
        pic_path = os.path.join(tmp_dir, "extmedia_%d_%d.png" % (slide_no, removed + 1))
        exported = False
        try:
            target.Export(pic_path, 3)  # ppShapeFormatPNG=3
            exported = os.path.exists(pic_path) and os.path.getsize(pic_path) > 0
        except Exception:  # noqa: BLE001
            exported = False
        try:
            left, top = float(target.Left), float(target.Top)
            width, height = float(target.Width), float(target.Height)
            shape_id = int(target.Id)
        except Exception:  # noqa: BLE001
            left = top = width = height = 0.0
            shape_id = -1
        try:
            _delete_shape_effects(slide, shape_id)
            target.Delete()
        except Exception as exc:  # noqa: BLE001
            ctx.warn("video: 外链媒体形状删除失败（第 %d 页 %r）：%s"
                     % (slide_no, shape_name, exc.__class__.__name__))
            continue
        if exported and width > 0 and height > 0:
            try:
                slide.Shapes.AddPicture(pic_path, False, True, left, top, width, height)
            except Exception:  # noqa: BLE001
                pass
        removed += 1
        ctx.log("video: 清理外链媒体（第 %d 页 %r，%s；外链文件不在本机时导出会等待约 90s）"
                % (slide_no, shape_name, "已用静态图替代" if exported else "直接删除"))
    return removed


def _apply_video_settings(ctx, pres, plan):
    """逐页设置自动换页时长 + 内嵌媒体 PlayOnEntry（让视频真的播放并带音轨）。"""
    slide_count = len(plan["advances"])
    media_shapes = 0
    for i in range(1, slide_count + 1):
        ctx.check("设置第 %d 页视频时序" % i)
        try:
            slide = pres.Slides(i)
            transition = slide.SlideShowTransition
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("读取第 %d 页失败：%s" % (i, exc.__class__.__name__))
        advance = float(plan["advances"][i - 1])
        try:
            transition.AdvanceOnClick = False
            transition.AdvanceOnTime = True
            transition.AdvanceTime = advance
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("设置第 %d 页自动换页失败：%s" % (i, exc.__class__.__name__))
        readback = None
        try:
            readback = float(transition.AdvanceTime)
        except Exception:  # noqa: BLE001
            pass
        if readback is None or abs(readback - advance) > 0.05:
            raise ConvertError("第 %d 页自动换页时间设置失败（期望 %.2fs，实际 %s）"
                               % (i, advance, readback))
        try:
            shapes_count = int(slide.Shapes.Count)
        except Exception:  # noqa: BLE001
            shapes_count = 0
        for j in range(1, shapes_count + 1):
            try:
                shape = slide.Shapes(j)
                if int(shape.Type) != 16:  # msoMedia
                    continue
            except Exception:  # noqa: BLE001
                continue
            try:
                shape.AnimationSettings.PlaySettings.PlayOnEntry = True
            except Exception as exc:  # noqa: BLE001
                # 不设置时 PowerPoint 导出的视频只有海报帧且没有音轨（实测）→ 直接跳过视频
                raise ConvertError("第 %d 页内嵌媒体 PlayOnEntry 设置失败：%s"
                                   % (i, exc.__class__.__name__))
            media_shapes += 1
    ctx.log("video: 已设置 %d 页自动换页 / %d 个内嵌媒体 PlayOnEntry"
            % (slide_count, media_shapes))
    return media_shapes


def _call_create_video(pres, path, opts):
    """``Presentation.CreateVideo`` 调用（独立函数便于测试注入失败）。"""
    pres.CreateVideo(path, True,
                     int(opts.get("video_default_slide_duration") or 5),
                     int(opts.get("video_resolution") or 720),
                     int(opts.get("video_fps") or 30),
                     int(opts.get("video_quality") or 80))


def _wait_create_video(ctx, pres, path, timeout_s):
    """轮询 CreateVideo 完成（优先 CreateVideoStatus，兜底文件大小稳定）；超时返回 False。"""
    started = time.monotonic()
    limit = max(1.0, float(timeout_s))
    last_size = -1
    stable = 0
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= limit:
            ctx.warn("video: PowerPoint 导出视频超时（%.0fs）" % elapsed)
            return False
        time.sleep(1.0)
        status = None
        try:
            status = int(pres.CreateVideoStatus)
        except Exception:  # noqa: BLE001
            status = None
        if status == CREATEVIDEO_STATUS_FAILED:
            ctx.warn("video: PowerPoint 导出视频失败（CreateVideoStatus=Failed）")
            return False
        size = 0
        try:
            if os.path.exists(path):
                size = os.path.getsize(path)
        except OSError:
            size = 0
        if size > 0 and size == last_size:
            stable += 1
        else:
            stable = 0
        last_size = size
        if status == CREATEVIDEO_STATUS_DONE and size > 0 and stable >= 1:
            ctx.log("video: PowerPoint 导出完成 %.1fs（%d bytes）"
                    % (time.monotonic() - started, size))
            return True
        if (status is None or status == 0) and size > 0 and stable >= 3:
            # 老版本无 CreateVideoStatus：文件大小连续 3s 不变视为完成
            ctx.log("video: PowerPoint 导出完成（文件大小稳定）%.1fs（%d bytes）"
                    % (time.monotonic() - started, size))
            return True


def _package_video(ctx, raw_path, dst_path, ffmpeg, ffprobe, opts):
    """PowerPoint 视频 → deck.mp4：<40MB 只 remux；≥40MB（或非 h264）重编码控体积。"""
    try:
        raw_size = os.path.getsize(raw_path)
    except OSError:
        ctx.warn("video: PowerPoint 导出文件不存在")
        return None
    raw_info = _ffprobe_info(ffprobe, raw_path) or {}
    if not raw_info.get("dur"):
        ctx.warn("video: PowerPoint 导出文件无法解析（ffprobe 无时长），跳过原样播放视频")
        return None
    threshold = int(opts.get("video_faststart_only_bytes") or 40 * 1024 * 1024)
    remux_cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", raw_path,
                 "-c", "copy", "-movflags", "+faststart", dst_path]
    reencode_cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", raw_path,
                    "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", str(int(opts.get("video_reencode_crf") or 24)),
                    "-pix_fmt", "yuv420p"]
    if raw_info.get("has_audio"):
        reencode_cmd += ["-c:a", "aac", "-b:a",
                         "%dk" % int(opts.get("video_reencode_audio_kbps") or 96)]
    else:
        reencode_cmd += ["-an"]
    reencode_cmd += ["-movflags", "+faststart", dst_path]
    need_reencode = raw_size >= threshold or str(raw_info.get("codec") or "") != "h264"
    attempts = [("reencode", reencode_cmd), ("remux", remux_cmd)] if need_reencode \
        else [("remux", remux_cmd), ("reencode", reencode_cmd)]
    used = ""
    for label, cmd in attempts:
        try:
            proc = _run_ffmpeg(cmd, timeout=1800)
        except subprocess.TimeoutExpired:
            ctx.warn("video: ffmpeg %s 超时" % label)
            continue
        if (proc.returncode == 0 and os.path.exists(dst_path)
                and os.path.getsize(dst_path) > 0):
            used = label
            break
        err = (proc.stderr or "").strip().splitlines()
        ctx.warn("video: ffmpeg %s 失败：%s"
                 % (label, (err[-1] if err else "rc=%s" % proc.returncode)[:200]))
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
        except OSError:
            pass
    if not used:
        return None
    info = _ffprobe_info(ffprobe, dst_path)
    if info is None or not info.get("dur"):
        ctx.warn("video: deck.mp4 无法解析（ffprobe 失败）")
        return None
    if str(info.get("codec") or "") != "h264":
        ctx.warn("video: deck.mp4 编码不是 h264（%s），跳过原样播放视频"
                 % (info.get("codec") or "unknown"))
        return None
    if raw_info.get("has_audio") and not info.get("has_audio"):
        ctx.warn("video: deck.mp4 丢失音轨（源媒体有音轨）")
    info["size"] = os.path.getsize(dst_path)
    info["raw_bytes"] = raw_size
    info["reencoded"] = used == "reencode"
    ctx.log("video: %s %.2fMB → %.2fMB（%dx%d %.1fs codec=%s audio=%s）"
            % (used, raw_size / 1048576.0, info["size"] / 1048576.0,
               int(info.get("w") or 0), int(info.get("h") or 0),
               float(info["dur"]), info.get("codec") or "?",
               info.get("audio_codec") or "无"))
    return info


def _export_video(ctx, app, pres, effects_per_slide, media_max_durs, assets_dir,
                  tmp_dir, opts, reuse_copy=""):
    """导出原样播放视频（任何失败只跳过视频 + warning，绝不抛给调用方）。"""
    result = {"video": None, "asset": None, "stats": {}, "skipped": ""}
    dst_path = os.path.join(assets_dir, "deck.mp4")
    raw_path = os.path.join(tmp_dir, "deck_raw.mp4")
    if not bool(opts.get("video", True)):
        result["skipped"] = "opts.video=False"
        ctx.log("video: 跳过（opts.video=False）")
        return result
    t0 = time.monotonic()
    try:
        slide_count = len(effects_per_slide or [])
        plan = _collect_video_plan(ctx, pres, effects_per_slide or [], media_max_durs or [], opts)
        reason = pptx_xml.video_skip_reason(
            slide_count, plan["estimated_s"],
            int(opts.get("video_max_slides") or pptx_xml.VIDEO_MAX_SLIDES),
            float(opts.get("video_max_duration_s") or pptx_xml.VIDEO_MAX_DURATION_S))
        if reason:
            result["skipped"] = reason
            ctx.warn("video: " + reason)
            return result
        reserve = float(opts.get("video_timeout_reserve_s") or 45.0)
        remaining = ctx.deadline.remaining() - reserve
        export_timeout = min(float(opts.get("video_export_timeout_s") or 1800.0), remaining)
        if export_timeout < 60:
            result["skipped"] = "剩余转换时间不足"
            ctx.warn("video: 剩余转换时间不足（%.0fs < 60s），跳过原样播放视频"
                     % max(0.0, remaining))
            return result
        ctx.progress(82, "导出原样播放视频（%d 页 / 预估 %.0fs）"
                     % (slide_count, plan["estimated_s"]))
        ctx.log("video: 开始导出（%d 页，预估 %.1fs + 切换 %.1fs = %.1fs；超时预算 %.0fs）"
                % (slide_count, sum(plan["advances"]), sum(plan["trans_durs"]),
                   plan["estimated_s"], export_timeout))
        pres2 = None
        ok = False
        stripped_external = 0
        try:
            pres2, copy_path_used = _open_writable_video_copy(
                ctx, app, pres, tmp_dir, reuse_copy)
            # 外链媒体（本机无源文件）会让 PowerPoint 导出时等待 ~90s/个 → 清理后重算时序
            stripped_external = _strip_external_media(ctx, pres2, copy_path_used, tmp_dir)
            if stripped_external:
                effects2 = []
                for i in range(1, slide_count + 1):
                    ctx.check("清理后重读第 %d 页动画" % i)
                    effects2.append(_slide_effects(pres2.Slides(i), ctx))
                plan = _collect_video_plan(ctx, pres2, effects2, media_max_durs or [], opts)
                ctx.log("video: 清理 %d 个外链媒体后重算时序（预估 %.1fs）"
                        % (stripped_external, plan["estimated_s"]))
            _apply_video_settings(ctx, pres2, plan)
            _call_create_video(pres2, raw_path, opts)
            ok = _wait_create_video(ctx, pres2, raw_path, export_timeout)
        finally:
            if pres2 is not None:
                try:
                    pres2.Close()
                except Exception:  # noqa: BLE001
                    pass
                pres2 = None
        if not ok:
            result["skipped"] = "PowerPoint 导出未完成（超时/失败）"
            return result
        try:
            raw_size = os.path.getsize(raw_path)
        except OSError:
            raw_size = 0
        if raw_size <= 0:
            result["skipped"] = "PowerPoint 导出文件为空"
            ctx.warn("video: PowerPoint 导出文件为空，跳过原样播放视频")
            return result
        ffmpeg = _find_tool("ffmpeg", opts.get("ffmpeg"))
        ffprobe = _find_tool("ffprobe", opts.get("ffprobe"))
        info = _package_video(ctx, raw_path, dst_path, ffmpeg, ffprobe, opts)
        if info is None:
            result["skipped"] = "视频后处理失败"
            return result
        chapters = pptx_xml.compute_chapters(plan["advances"], plan["trans_durs"],
                                             float(info["dur"]))
        # 实测时长 vs 公式预估：偏差过大说明有页被 PowerPoint 自动延长（章节可能漂移）
        duration_drift = round(float(info["dur"]) - float(plan["estimated_s"]), 2)
        drift_limit = max(3.0, 0.02 * float(plan["estimated_s"]))
        if abs(duration_drift) > drift_limit:
            ctx.warn("video: 实测时长与预估偏差 %.1fs（实测 %.1fs / 预估 %.1fs），"
                     "章节时间可能漂移；原因多为媒体页自动延长或外链媒体"
                     % (duration_drift, float(info["dur"]), float(plan["estimated_s"])))
        video = {
            "s": "deck.mp4",
            "w": int(info.get("w") or 0),
            "h": int(info.get("h") or 0),
            "dur": round(float(info["dur"]), 2),
            "chapters": [{"i": i, "t": t} for i, t in enumerate(chapters)],
            "q": str(opts.get("video_tag") or pptx_xml.VIDEO_TAG_DEFAULT),
        }
        errors = pptx_xml.validate_video(video, slide_count)
        if errors:
            result["skipped"] = "manifest.video 校验失败"
            ctx.warn("video: manifest.video 校验失败（已跳过）：%s" % "; ".join(errors[:4]))
            return result
        asset = {"name": "deck.mp4", "path": dst_path, "size": int(info["size"]),
                 "content_type": "video/mp4", "kind": "video"}
        elapsed = round(time.monotonic() - t0, 2)
        stats = {
            "export_s": elapsed,
            "dur": video["dur"],
            "bytes": int(info["size"]),
            "raw_bytes": int(info.get("raw_bytes") or 0),
            "w": video["w"],
            "h": video["h"],
            "audio": str(info.get("audio_codec") or ""),
            "chapters": len(chapters),
            "last_chapter_t": chapters[-1] if chapters else 0.0,
            "estimated_s": plan["estimated_s"],
            "duration_drift": duration_drift,
            "stripped_external": int(stripped_external),
            "reencoded": bool(info.get("reencoded")),
        }
        ctx.log("video: 完成 dur=%.2fs %dx%d audio=%s size=%.1fMB 耗时 %.1fs"
                "（预估 %.1fs，chapters=%d，末章 t=%.1fs，重编码=%s）"
                % (video["dur"], video["w"], video["h"], stats["audio"] or "无",
                   stats["bytes"] / 1048576.0, elapsed, plan["estimated_s"],
                   len(chapters), stats["last_chapter_t"], stats["reencoded"]))
        result.update({"video": video, "asset": asset, "stats": stats})
        return result
    except ConvertTimeout as exc:
        result["skipped"] = "整体转换预算用尽"
        ctx.warn("video: 导出超时/整体预算用尽，跳过原样播放视频（%s）" % exc)
        _remove_quiet(dst_path)
        return result
    except Exception as exc:  # noqa: BLE001
        result["skipped"] = exc.__class__.__name__
        ctx.warn("video: 导出失败，跳过原样播放视频（%s: %s）"
                 % (exc.__class__.__name__, str(exc)[:160]))
        ctx.log(traceback.format_exc()[-1200:])
        _remove_quiet(dst_path)
        return result


def _remove_quiet(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def export_video_only(src_path, work_dir, opts=None):
    """只导出「原样播放」视频（不渲染图片、不抽取/不上传媒体资产）。

    ``agent.py --video-only`` 用：对已 ready 的 deck 从 OSS 下载源文件后补视频，
    合并进现有 manifest（只新增 ``video`` 字段，不动 slides/img/media/notes）。
    """
    opts = normalize_options(opts)
    log = opts.pop("log", None) if isinstance(opts, dict) else None
    ctx = _Ctx(opts, log=log, progress=opts.get("progress"))
    t0 = time.monotonic()
    src_path = os.path.abspath(str(src_path))
    out = {"video": None, "assets": [], "stats": {"slides": 0, "elapsed_s": 0.0},
           "warnings": ctx.warnings, "skipped": "", "export_s": 0.0}
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
    com = {"app": None, "pres": None}
    pythoncom = None
    try:
        ctx.progress(2, "准备源文件")
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
        ctx.log("PowerPoint 就绪（视频-only，%.0fms）"
                % (1000 * (time.monotonic() - t0)))
        ctx.progress(8, "打开演示文稿")
        try:
            com["pres"] = com["app"].Presentations.Open(local_copy, True, False, False)
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("PowerPoint 无法打开该文件（可能加密/损坏）：%s"
                               % exc.__class__.__name__)
        pres = com["pres"]
        slide_count, effects_per_slide = _collect_video_slide_effects(ctx, pres)
        out["stats"]["slides"] = slide_count
        ctx.progress(20, "探测内嵌媒体时长")
        copy_path = os.path.join(tmp_dir, "video_deck.pptx")
        media_durs = [0.0] * slide_count
        try:
            pres.SaveCopyAs(copy_path)
            if zipfile.is_zipfile(copy_path):
                media_durs = _probe_media_durations(ctx, copy_path, slide_count,
                                                    tmp_dir, opts)
        except Exception as exc:  # noqa: BLE001
            ctx.warn("video: 保存临时副本失败（媒体时长按 0 计）：%s"
                     % exc.__class__.__name__)
            copy_path = ""
        ctx.progress(40, "导出原样播放视频")
        result = _export_video(ctx, com["app"], pres, effects_per_slide, media_durs,
                               assets_dir, tmp_dir, opts,
                               reuse_copy=copy_path if copy_path and os.path.exists(copy_path) else "")
        out["video"] = result.get("video")
        out["assets"] = [result["asset"]] if result.get("asset") else []
        out["skipped"] = str(result.get("skipped") or "")
        out["export_s"] = float((result.get("stats") or {}).get("export_s") or 0.0)
        out["stats"].update(result.get("stats") or {})
        return out
    finally:
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
            try:
                pythoncom.CoUninitialize()
            except Exception:  # noqa: BLE001
                pass
        # COM 完全反初始化后 PowerPoint 自动化实例才会真正退出（否则可能挂 60s 等 RPC 超时）
        _wait_powerpoint_exit(ctx, 60.0, "COM 反初始化后")
        _cleanup_tmp(tmp_dir, bool(opts.get("keep_intermediate")))
        out["stats"]["elapsed_s"] = round(time.monotonic() - t0, 2)
        out["warnings"] = ctx.warnings


# ---------------------------------------------------------------------------
# v2.0 compat 兼容性处理（CONTRACT §12）：不降质格式标准化 + 字体嵌入 + PDF + 封面
# ---------------------------------------------------------------------------
PP_SAVEAS_PRESENTATION = 1        # ppSaveAsPresentation（.ppt 97-2003）
PP_SAVEAS_OPENXML = 24            # ppSaveAsOpenXMLPresentation（.pptx）
PP_SAVEAS_PDF = 32                # ppSaveAsPDF（与 ExportAsFixedFormat 同一个 PDF 引擎）
MIME_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MIME_PPT = "application/vnd.ms-powerpoint"
MIME_PDF = "application/pdf"
MIME_WEBP = "image/webp"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pdf_page_count(ctx, path):
    """PDF 页数：优先 pypdf；不可用返回 0（调用方按幻灯片数兜底并记 warning）。"""
    try:
        from pypdf import PdfReader  # 延迟导入（本机已装；不装也能跑）
        return len(PdfReader(path).pages)
    except Exception as exc:  # noqa: BLE001
        if ctx is not None:
            ctx.warn("compat: PDF 页数读取失败（pypdf 未装或 PDF 异常）：%s"
                     % exc.__class__.__name__)
        return 0


def _save_compat_package(ctx, pres, path, opts):
    """``SaveAs(ppSaveAsOpenXMLPresentation)`` 规范化包 + 嵌入 TrueType 字体。

    实测（2026-11-10）：本机 PowerPoint 16 的 Presentation **没有**可写的
    ``EmbedTrueTypeFonts``/``SaveSubsetFonts`` 属性（COM 对象模型未暴露）；
    官方等价入口是 ``SaveAs(FileName, FileFormat, EmbedFonts)`` 的第 3 参数
    （MsoTriState，-1=嵌入）。实测生成 ``ppt/fonts/*.fntdata`` 且
    presentation.xml 带 ``embedTrueTypeFonts="1" saveSubsetFonts="1"``。
    ``.ppt`` 源同样一次 SaveAs 完成「转 pptx + 规范化 + 字体嵌入」。
    """
    embed = bool(opts.get("compat_embed_fonts", True))
    if embed:
        try:
            pres.SaveAs(path, PP_SAVEAS_OPENXML, -1)
            return
        except Exception as exc:  # noqa: BLE001
            ctx.warn("compat: 字体嵌入保存失败（回退为不嵌入字体的兼容包）：%s"
                     % str(exc)[:160])
    try:
        pres.SaveAs(path, PP_SAVEAS_OPENXML, 0)
    except Exception as exc:  # noqa: BLE001
        raise ConvertError("保存兼容包失败（PowerPoint SaveAs）：%s：%s"
                           % (exc.__class__.__name__, str(exc)[:160]))


def _inspect_compat_package(ctx, path):
    """检查兼容包：页数 / 包内媒体 sha256 / 字体部件数 / presentation.xml 嵌入属性。"""
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ConvertError("兼容包不是有效 pptx（%s）" % exc.__class__.__name__)
    try:
        names = zf.namelist()
        fonts = [n for n in names if n.startswith("ppt/fonts/") and not n.endswith("/")]
        try:
            xml = zf.read("ppt/presentation.xml").decode("utf-8", "replace")
        except KeyError:
            xml = ""
        slides = len(pptx_xml.slide_part_names(zf))
        media = pptx_xml.media_sha256_map(zf)
    finally:
        zf.close()
    embed_attr = ('embedTrueTypeFonts="1"' in xml or 'embedTrueTypeFonts="true"' in xml)
    subset_attr = ("saveSubsetFonts" in xml)
    return {"slides": slides, "fonts": len(fonts), "embed_attr": embed_attr,
            "subset_attr": subset_attr, "media": media}


def _export_compat_pdf_and_cover(ctx, app, compat_path, tmp_dir, pdf_path,
                                 cover_jpg, cover_path, opts):
    """重开兼容包副本 → 封面 JPG→WebP + ``SaveAs(ppSaveAsPDF)`` 导出 PDF。

    实测：pywin32 动态绑定调用 ``ExportAsFixedFormat`` 会报
    ``TypeError: The Python instance can not be converted to a COM object``；
    改用同一 PDF 引擎的 ``SaveAs(FileName, ppSaveAsPDF=32)``，输出
    ``%PDF-1.7`` 且页数与幻灯片一致、导出前后 compat.pptx 字节不变。
    """
    pdf_src = os.path.join(tmp_dir, "pdf_src.pptx")
    shutil.copyfile(compat_path, pdf_src)
    pres = None
    try:
        pres = app.Presentations.Open(pdf_src, False, False, False)
        slides = int(pres.Slides.Count)
        cover_ok = False
        try:
            page_w = float(pres.PageSetup.SlideWidth)
            page_h = float(pres.PageSetup.SlideHeight)
            render_w = max(1, int(opts.get("compat_cover_width") or 1600))
            render_h = max(1, int(round(render_w * page_h / page_w)))
            pres.Slides(1).Export(cover_jpg, "JPG", render_w, render_h)
            cw, ch, csize, _q = _save_webp(cover_jpg, cover_path, opts, width=render_w)
            cover_ok = True
            ctx.log("compat: cover.webp %dx%d %d bytes" % (cw, ch, csize))
        except Exception as exc:  # noqa: BLE001
            ctx.warn("compat: 封面导出失败（列表可用默认样式）：%s"
                     % exc.__class__.__name__)
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            pres.SaveAs(pdf_path, PP_SAVEAS_PDF)
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("PDF 兼容副本导出失败：%s：%s"
                               % (exc.__class__.__name__, str(exc)[:160]))
    finally:
        if pres is not None:
            try:
                pres.Close()
            except Exception:  # noqa: BLE001
                pass
            pres = None
    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) <= 0:
        raise ConvertError("PDF 兼容副本导出失败（文件为空）")
    with open(pdf_path, "rb") as fh:
        head = fh.read(8)
    if not head.startswith(b"%PDF"):
        raise ConvertError("PDF 兼容副本文件头非法（%r）" % head[:8])
    pages = _pdf_page_count(ctx, pdf_path)
    return {"slides": slides, "pages": pages, "cover": cover_ok}


def _compat_file_entry(path, name, content_type=None, **extra):
    entry = {"s": os.path.basename(path), "size": os.path.getsize(path),
             "sha256": sha256_file(path)}
    if name:
        entry["name"] = name
    if content_type:
        entry["_content_type"] = content_type  # 内部用，写 manifest 前剔除
    entry.update(extra)
    return entry


def _download_name(base, suffix, ext, max_len=80):
    """v2.2.1 下载文件名区分：``<标题>_兼容版.pptx`` / ``_预览.pdf`` / ``_原始文件.pptx``。

    避免兼容版与原始文件同名导致用户误开旧链接文件（``ext`` 带点）。
    """
    b = str(base or "").strip() or "演示"
    suffix = str(suffix or "")
    keep = max(8, int(max_len or 80) - len(suffix))
    if len(b) > keep:
        b = b[:keep]
    return b + suffix + str(ext or "")


def convert_compat(src_path, work_dir, opts=None):
    """v2.0 兼容性处理（CONTRACT §12.1）：返回 compat.pptx/original.<ext>/preview.pdf/
    cover.webp 资产 + manifest v2（files/compat）。

    **不改变内容质量**：不渲染成图/视频、不重编码媒体、不降分辨率、不动动画/母版/字体样式；
    所有操作都在**临时副本**上（绝不修改源文件），源文件另存一份 ``original.<ext>`` 供下载。
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
    com = {"app": None, "pres": None}
    pythoncom = None
    stats = {"slides": 0, "elapsed_s": 0.0}
    try:
        ctx.progress(2, "准备源文件")
        local_copy = os.path.join(tmp_dir, "source" + src_ext)
        try:
            shutil.copyfile(src_path, local_copy)  # 只读源 → 临时副本（绝不改源文件）
        except OSError as exc:
            raise ConvertError("读取源文件失败：%s" % exc.__class__.__name__)
        try:
            import pythoncom as _pythoncom  # noqa: F401
            pythoncom = _pythoncom
            pythoncom.CoInitialize()
        except ImportError:  # pragma: no cover
            raise ConvertError("缺少 pywin32（pythoncom）")
        com["app"] = _acquire_powerpoint(ctx)
        ctx.progress(10, "打开源文件")
        try:
            com["pres"] = com["app"].Presentations.Open(local_copy, False, False, False)
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("PowerPoint 无法打开该文件（可能加密/损坏）：%s"
                               % exc.__class__.__name__)
        pres = com["pres"]
        try:
            slide_count = int(pres.Slides.Count)
            slide_w = float(pres.PageSetup.SlideWidth)
            slide_h = float(pres.PageSetup.SlideHeight)
        except Exception as exc:  # noqa: BLE001
            raise ConvertError("读取演示文稿信息失败：%s" % exc.__class__.__name__)
        if slide_count <= 0:
            raise ConvertError("演示文稿没有幻灯片")
        if slide_count > int(opts["max_slides"]):
            raise ConvertError("页数过多（%d 页，上限 %d 页）"
                               % (slide_count, int(opts["max_slides"])))
        stats["slides"] = slide_count
        ctx.log("compat: 源 %s（%d 页，页面 %.0fx%.0f pt，%.1fMB）"
                % (os.path.basename(src_path), slide_count, slide_w, slide_h,
                   os.path.getsize(src_path) / 1048576.0))
        # 30 PowerPoint 处理：标准化 + 字体嵌入（一次 SaveAs 完成，源文件不动）
        ctx.progress(30, "PowerPoint 规范化/嵌入字体")
        compat_path = os.path.join(assets_dir, "compat.pptx")
        t_save = time.monotonic()
        _save_compat_package(ctx, pres, compat_path, opts)
        ctx.log("compat: 兼容包已生成 %.1fs（%.2fMB）"
                % (time.monotonic() - t_save,
                   os.path.getsize(compat_path) / 1048576.0))
        try:
            pres.Close()
        except Exception:  # noqa: BLE001
            pass
        com["pres"] = None
        pres = None
        # 冷启动瞬态：首次 SaveAs(EmbedFonts) 偶尔静默不写字体 → 检测到 0 个字体部件时重试一次
        pkg = _inspect_compat_package(ctx, compat_path)
        if bool(opts.get("compat_embed_fonts", True)) and pkg["fonts"] == 0:
            ctx.warn("compat: 首次 SaveAs 未写入嵌入字体（可能 PowerPoint 冷启动瞬态）→ 重试一次")
            retry_pres = None
            try:
                retry_pres = com["app"].Presentations.Open(local_copy, False, False, False)
                _save_compat_package(ctx, retry_pres, compat_path, opts)
            except Exception as exc:  # noqa: BLE001
                ctx.warn("compat: 字体嵌入重试失败：%s" % exc.__class__.__name__)
            finally:
                if retry_pres is not None:
                    try:
                        retry_pres.Close()
                    except Exception:  # noqa: BLE001
                        pass
                    retry_pres = None
            pkg = _inspect_compat_package(ctx, compat_path)
            if pkg["fonts"] == 0:
                ctx.warn("compat: 字体仍未嵌入（可能无可用 TrueType 字体或许可受限）")
        # v2.0.1：断链视频修复（video 关系 External/NULL 但同 slide 有内嵌副本 → 内部化）
        # 必须在 SaveAs 之后、PDF/上传之前；zip 级重写，media 字节不动。
        video_repair = pptx_xml.repair_broken_video_links(compat_path)
        repairs = video_repair.get("repairs") or []
        unresolved = video_repair.get("unresolved") or []
        if repairs:
            for item in repairs:
                ctx.log("compat: 修复断链视频（第 %d 页，形状 %r → 内嵌 %s，%d bytes）"
                        % (item["slide"], item["name"], item["media"], item["bytes"]))
        if unresolved:
            ctx.log("compat: 仍有 %d 处视频外链无法内嵌（无内嵌副本，保留外链并告警）"
                    % len(unresolved))
        # 修复会改动 rels（compat 体积/sha 变化）→ 重新检查兼容包
        pkg = _inspect_compat_package(ctx, compat_path)
        if pkg["slides"] != slide_count:
            raise ConvertError("兼容包页数与原文件不一致（%d / %d）"
                               % (pkg["slides"], slide_count))
        # v2.2 媒体编码兼容（CONTRACT §12.7）：在断链修复之后、计算 size/sha/上传之前
        ctx.progress(40, "媒体编码兼容处理")
        media_result = _compat_media(ctx, compat_path, tmp_dir, opts)
        media_actions = media_result.get("actions") or []
        media_summary = media_result.get("summary") or {
            "total": 0, "kept": 0, "remux": 0, "transcode": 0}
        if media_result.get("changed"):
            pkg = _inspect_compat_package(ctx, compat_path)
            if pkg["slides"] != slide_count:
                raise ConvertError("媒体处理后兼容包页数异常（%d / %d）"
                                   % (pkg["slides"], slide_count))
        # 不降质证据：已兼容（keep）媒体必须逐字节不变；remux/transcode 按 media_actions 允许变化
        src_media = pptx_xml.media_sha256_map(src_path) if src_ext == ".pptx" else {}
        changed_files = set()
        for item in media_actions:
            if item.get("action") and item.get("action") != "keep":
                changed_files.add(str(item.get("file") or ""))
        if src_media:
            src_values = set(src_media.values())
            unexpected = []
            for name, sha in pkg["media"].items():
                if _media_part_basename(name) in changed_files:
                    continue
                if sha not in src_values:
                    unexpected.append(name)
            if unexpected:
                raise ConvertError("兼容包媒体字节与原文件不一致（非 keep 媒体被改动）：%s"
                                   % ", ".join(unexpected[:3]))
            if len(pkg["media"]) != len(src_media):
                ctx.warn("compat: 兼容包媒体部件数与原包不同（源 %d / 兼容 %d），"
                         "PowerPoint 可能合并了重复媒体；字节校验通过"
                         % (len(src_media), len(pkg["media"])))
            same_names = sum(1 for n, sha in pkg["media"].items()
                             if src_media.get(n) == sha)
            if changed_files:
                ctx.log("compat: 媒体编码兼容后 sha 校验通过（源 %d / 兼容 %d 个；"
                        "keep 媒体逐字节不变，remux/transcode 按 media_actions 记录）"
                        % (len(src_media), len(pkg["media"])))
            else:
                ctx.log("compat: 内嵌媒体 sha256 与源包逐字节一致（源 %d / 兼容 %d 个，"
                        "未重编码；部件名同名 %d 个，PowerPoint SaveAs 可能重编号但字节不变）"
                        % (len(src_media), len(pkg["media"]), same_names))
        else:
            ctx.log("compat: 源为 .ppt（OLE 包），跳过包内媒体 sha 对比（PowerPoint 转换，不重采样）")
        if media_summary.get("total"):
            ctx.log("compat: 媒体编码兼容摘要：total=%d keep=%d remux=%d transcode=%d"
                    % (media_summary["total"], media_summary["kept"],
                       media_summary["remux"], media_summary["transcode"]))
        ctx.log("compat: 字体部件 %d 个（embedTrueTypeFonts=%s, saveSubsetFonts=%s）"
                % (pkg["fonts"], pkg["embed_attr"], pkg["subset_attr"]))
        # 55 生成兼容包：原始文件副本 + 外链媒体告警 + 封面
        ctx.progress(55, "生成兼容包/原始副本")
        source_asset_path = os.path.join(assets_dir, "original" + src_ext)
        # 直接从**调用方给的源文件**复制（PPT 打开副本后可能改写副本元数据，
        # 必须保证 original.<ext> 与上传原件逐字节一致）
        shutil.copyfile(src_path, source_asset_path)
        try:
            media_shapes = pptx_xml.read_media_shapes(compat_path)
        except Exception as exc:  # noqa: BLE001
            ctx.warn("compat: 兼容包媒体结构解析失败（外链告警为空）：%s"
                     % exc.__class__.__name__)
            media_shapes = []
        ext_warnings, external_media = pptx_xml.compat_external_media(media_shapes)
        warnings_text = list(ext_warnings)
        for text in ext_warnings:
            ctx.warn("compat: " + text)
        if bool(opts.get("compat_embed_fonts", True)) and pkg["fonts"] == 0:
            text = "字体未嵌入（可能无 TrueType 字体或许可受限），版式可能在其他设备变化"
            warnings_text.append(text)
            ctx.warn("compat: " + text)
        # 75 导出 PDF + 封面
        ctx.progress(75, "导出 PDF/封面")
        pdf_path = os.path.join(assets_dir, "preview.pdf")
        cover_jpg = os.path.join(tmp_dir, "cover.jpg")
        cover_path = os.path.join(assets_dir, "cover.webp")
        exported = _export_compat_pdf_and_cover(ctx, com["app"], compat_path, tmp_dir,
                                                pdf_path, cover_jpg, cover_path, opts)
        if exported["slides"] != slide_count:
            raise ConvertError("兼容包重开页数异常（%d / %d）"
                               % (exported["slides"], slide_count))
        pages = int(exported["pages"] or 0)
        if pages <= 0:
            pages = slide_count
            ctx.warn("compat: PDF 页数读取不可用，按幻灯片数 %d 填写" % pages)
        elif pages != slide_count:
            ctx.warn("compat: PDF 页数（%d）与幻灯片数（%d）不一致（可能导出设置跳过隐藏页），"
                     "以 PDF 实测为准" % (pages, slide_count))
        ctx.log("compat: preview.pdf %.2fMB / %d 页；cover=%s"
                % (os.path.getsize(pdf_path) / 1048576.0, pages,
                   "cover.webp" if exported["cover"] else "无"))
        # 资产 + manifest v2
        title = str(opts.get("title") or "").strip()
        source_name = str(opts.get("source_name") or os.path.basename(src_path))
        max_len = int(opts.get("compat_filename_max") or 80)
        safe_title = pptx_xml.sanitize_filename(
            title or os.path.splitext(os.path.basename(source_name))[0],
            fallback="演示", max_len=max_len)
        safe_source = pptx_xml.sanitize_filename(os.path.basename(source_name),
                                                 fallback="original" + src_ext,
                                                 max_len=max_len)
        if not safe_source.lower().endswith(src_ext):
            safe_source += src_ext
        compat_entry = _compat_file_entry(
            compat_path, _download_name(safe_title, "_兼容版", ".pptx", max_len),
            content_type=MIME_PPTX, ext="pptx")
        pdf_entry = _compat_file_entry(
            pdf_path, _download_name(safe_title, "_预览", ".pdf", max_len),
            content_type=MIME_PDF, pages=pages)
        source_entry = _compat_file_entry(
            source_asset_path,
            _download_name(os.path.splitext(safe_source)[0], "_原始文件", src_ext, max_len),
            content_type=(MIME_PPT if src_ext == ".ppt" else MIME_PPTX),
            ext=src_ext.lstrip("."))
        for entry in (compat_entry, pdf_entry, source_entry):
            entry.pop("_content_type", None)
        files = {"compat": compat_entry, "pdf": pdf_entry, "source": source_entry}
        compat_meta = {
            "warnings": warnings_text,
            "fonts_embedded": int(pkg["fonts"]),
            "converted_from": ("ppt" if src_ext == ".ppt" else None),
            "external_media": external_media,
            # v2.0.1：断链视频已用内嵌副本修复的记录（已从 warnings 移除对应外链提示）
            "repairs": repairs,
            # v2.2：媒体编码兼容处理记录（成功项不进 warnings）
            "media_actions": media_actions,
            "media_summary": media_summary,
        }
        manifest = {
            "v": pptx_xml.COMPAT_MANIFEST_VERSION,
            "w": int(round(slide_w)),
            "h": int(round(slide_h)),
            "slides": [],  # compat 模式不再生成分步图（CONTRACT §12.2）
            "files": files,
            "compat": compat_meta,
        }
        assets = [
            {"name": "compat.pptx", "path": compat_path, "size": compat_entry["size"],
             "content_type": MIME_PPTX, "kind": "compat"},
            {"name": os.path.basename(source_asset_path), "path": source_asset_path,
             "size": source_entry["size"],
             "content_type": (MIME_PPT if src_ext == ".ppt" else MIME_PPTX),
             "kind": "source"},
            {"name": "preview.pdf", "path": pdf_path, "size": pdf_entry["size"],
             "content_type": MIME_PDF, "kind": "pdf"},
        ]
        cover_name = ""
        if exported["cover"] and os.path.exists(cover_path) and os.path.getsize(cover_path) > 0:
            cover_name = "cover.webp"
            assets.append({"name": cover_name, "path": cover_path,
                           "size": os.path.getsize(cover_path),
                           "content_type": MIME_WEBP, "kind": "cover"})
        build_id = pptx_xml.compute_build_id(assets, manifest)
        prefix = "%s%s/%s/" % (ASSET_PREFIX, opts["deck_id"], build_id)
        manifest["base"] = str(opts["oss_base"]) + prefix
        errors = pptx_xml.validate_manifest(manifest)
        if errors:
            raise ConvertError("manifest 校验失败：%s" % "; ".join(errors[:4]))
        stats.update({
            "slides": slide_count,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "compat_size": int(compat_entry["size"]),
            "compat_sha256": compat_entry["sha256"],
            "pdf_size": int(pdf_entry["size"]),
            "pdf_pages": pages,
            "source_size": int(source_entry["size"]),
            "source_sha256": source_entry["sha256"],
            "fonts_embedded": int(pkg["fonts"]),
            "external_media": len(external_media),
            "video_repairs": len(repairs),
            "media_total": int(media_summary.get("total") or 0),
            "media_kept": int(media_summary.get("kept") or 0),
            "media_remux": int(media_summary.get("remux") or 0),
            "media_transcode": int(media_summary.get("transcode") or 0),
            "warnings": len(ctx.warnings),
            "converted_from": compat_meta["converted_from"],
            "build_prefix": prefix,
        })
        ctx.log("compat 完成：%d 页 / compat %.2fMB sha=%s / pdf %d 页 %.2fMB / "
                "字体 %d / 外链媒体 %d 处 / 断链视频修复 %d 处 / "
                "媒体 keep %d remux %d transcode %d / 耗时 %.1fs / build=%s"
                % (slide_count, stats["compat_size"] / 1048576.0,
                   compat_entry["sha256"][:12], pages, stats["pdf_size"] / 1048576.0,
                   stats["fonts_embedded"], len(external_media), len(repairs),
                   stats["media_kept"], stats["media_remux"],
                   stats["media_transcode"], stats["elapsed_s"], build_id))
        return {
            "manifest": manifest,
            "assets": assets,
            "build_id": build_id,
            "stats": stats,
            "warnings": ctx.warnings,
            "aspect": pptx_xml.aspect_label(slide_w, slide_h),
            "slide_count": slide_count,
            "step_count": 0,
            "cover": cover_name,
            "src_ext": src_ext,
            "source_key": "%s%s%s/source%s" % (SRC_PREFIX, opts["deck_id"], "", src_ext),
            "files": files,
            "compat": compat_meta,
            "render_w": int(round(slide_w)),
            "render_h": int(round(slide_h)),
        }
    finally:
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
            try:
                pythoncom.CoUninitialize()
            except Exception:  # noqa: BLE001
                pass
        _wait_powerpoint_exit(ctx, 30.0, "COM 反初始化后")
        _cleanup_tmp(tmp_dir, bool(opts.get("keep_intermediate")))
        stats["elapsed_s"] = round(time.monotonic() - t0, 2)


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
        # v1.2 原样播放视频（CONTRACT §11.2）：同一 PowerPoint 会话内导出（失败只跳过视频）
        media_max_durs = pptx_xml.slide_media_max_dur(
            len(slides_meta), hotspots, media_table)
        video_result = _export_video(
            ctx, com["app"], pres, [meta["effects"] for meta in slides_meta],
            media_max_durs, assets_dir, tmp_dir, opts)
        video_manifest = video_result.get("video")
        video_stats = video_result.get("stats") or {}
        if video_result.get("asset") is not None:
            assets.append(video_result["asset"])
        ctx.progress(89, "原样播放视频完成" if video_manifest else "跳过原样播放视频")
        manifest = _build_manifest(opts, slides_meta, kept_steps, media_table,
                                   hotspots, render_w, render_h, src_ext)
        if video_manifest:
            manifest["video"] = video_manifest
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
            # v1.2 原样播放视频（缺省/失败时全部为 0/false，不影响分步模式）
            "video": bool(video_manifest),
            "video_dur": round(float(video_stats.get("dur") or 0.0), 2),
            "video_bytes": int(video_stats.get("bytes") or 0),
            "video_export_s": float(video_stats.get("export_s") or 0.0),
            "video_audio": str(video_stats.get("audio") or ""),
            "video_chapters": int(video_stats.get("chapters") or 0),
            "video_reencoded": bool(video_stats.get("reencoded")),
            "video_skipped": str(video_result.get("skipped") or ""),
        }
        ctx.progress(90, "转换完成")
        ctx.log("完成：%d 页 / %d 步 / %d 图片 / %d 媒体 / %s，耗时 %s，build=%s"
                % (stats["slides"], stats["steps"], stats["images"], stats["media"],
                   ("视频 %.1fs" % stats["video_dur"]) if stats["video"] else "无视频",
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
            "video": video_manifest,
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
        # COM 完全反初始化后 PowerPoint 自动化实例才会真正退出（否则可能挂 60s 等 RPC 超时）
        _wait_powerpoint_exit(ctx, 60.0, "COM 反初始化后")
        _cleanup_tmp(tmp_dir, bool(opts.get("keep_intermediate")))


# ---------------------------------------------------------------------------
# CLI（联调用：python convert.py <src.pptx> --deck-id ddemo）
# ---------------------------------------------------------------------------
def _main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="PPT → 分步图片/媒体/manifest/原样播放视频（本机）")
    parser.add_argument("src", help="源 .ppt/.pptx 路径")
    parser.add_argument("--work-dir", default="", help="工作目录（默认 web/ppt/work/<basename>）")
    parser.add_argument("--deck-id", default="testdeck")
    parser.add_argument("--timeout", type=float, default=1800.0,
                        help="单任务预算秒数（默认 1800=30min）")
    parser.add_argument("--no-media", action="store_true", help="跳过媒体抽取")
    parser.add_argument("--no-video", action="store_true", help="跳过原样播放视频导出")
    parser.add_argument("--video-only", action="store_true",
                        help="只导出原样播放视频（不渲染图片/不抽媒体，调试 --video-only 用）")
    parser.add_argument("--compat", action="store_true",
                        help="v2.0 兼容性处理（compat.pptx/original/preview.pdf/cover.webp，"
                             "不降质；调试 convert_compat 用）")
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
        "video": not args.no_video,
        "keep_intermediate": args.keep_intermediate,
        "log": opts.get("log") or (lambda msg: print("[convert] " + msg, flush=True)),
    })
    t0 = time.time()
    try:
        if args.video_only:
            result = export_video_only(src, work, opts)
            print(json.dumps({"video": result.get("video"),
                              "stats": result.get("stats"),
                              "skipped": result.get("skipped"),
                              "warnings": result.get("warnings")},
                             ensure_ascii=False, indent=2))
            return 0 if result.get("video") else 3
        if args.compat:
            result = convert_compat(src, work, opts)
            summary = {k: v for k, v in result.items() if k != "assets"}
            summary["assets"] = [{"name": a["name"], "path": a["path"],
                                  "size": a["size"], "content_type": a.get("content_type"),
                                  "kind": a.get("kind")} for a in result["assets"]]
            summary["total_s"] = round(time.time() - t0, 2)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
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
        "video": result.get("video"),
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
