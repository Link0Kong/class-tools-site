# -*- coding: utf-8 -*-
"""make_fixture_pptx.py — 用 PowerPoint COM 生成转换测试用的 fixture 演示文稿

契约：``web/ppt/CONTRACT.md`` §6/§9。

产物（默认写到 ``tests/_out/``）：

* ``fixture_deck.pptx``（16:9，5 页）
  - 第 1 页：标题（无动画）；
  - 第 2 页：3 个方块，2 个**单击**入场 + 1 个 afterPrevious（验证同 step 合并），
    切换 = fade(3849)；
  - 第 3 页：1 个入场 + 1 个**退场**（验证初始可见→点击后消失），切换 = wipe(2817)；
  - 第 4 页：**内嵌视频**（mp4，ffmpeg 现生成 3 秒 testsrc+正弦音）+ 文案；
  - 第 5 页：中文备注 + 单击强调动画（grow/spin，最终画面不变 → 验证相邻步去重），
    切换 = push(3853)，另尝试插入一个**外链**视频（验证外链跳过不报错）。
* ``fixture_deck_43.pptx``（4:3，3 页，含单击动画与备注）。
* ``media/clip.mp4``：fixture 用短视频（3s 640x360 H.264/AAC）。

用法::

    python tests/make_fixture_pptx.py            # 生成（已存在则覆盖）
    python tests/make_fixture_pptx.py --keep-open
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PPT_DIR = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "_out")
MEDIA_DIR = os.path.join(OUT_DIR, "media")
DEFAULT_OUT = os.path.join(OUT_DIR, "fixture_deck.pptx")
DEFAULT_OUT_43 = os.path.join(OUT_DIR, "fixture_deck_43.pptx")

CLIP_PATH = os.path.join(MEDIA_DIR, "clip.mp4")
FFMPEG_FALLBACK = os.path.join(os.path.expanduser("~"), "bin", "ffmpeg.exe")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

PP_LAYOUT_BLANK = 12
MSO_SHAPE_RECTANGLE = 1


def log(msg):
    print("[fixture] " + msg, flush=True)


def find_ffmpeg():
    import shutil

    path = shutil.which("ffmpeg")
    if path:
        return path
    if os.path.exists(FFMPEG_FALLBACK):
        return FFMPEG_FALLBACK
    raise SystemExit("找不到 ffmpeg（PATH 或 ~/bin/ffmpeg.exe）")


def ensure_clip(path=CLIP_PATH):
    """生成 3 秒 640x360 H.264/AAC 测试视频。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return path
    ffmpeg = find_ffmpeg()
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc=duration=3:size=640x360:rate=25",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
           "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", path]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)
    if proc.returncode != 0:
        raise SystemExit("ffmpeg 生成 clip 失败：%s" % (proc.stderr or "")[-400:])
    log("clip.mp4: %d bytes" % os.path.getsize(path))
    return path


def _add_textbox(slide, left, top, width, height, text, size=28, bold=False):
    box = slide.Shapes.AddTextbox(1, left, top, width, height)
    box.TextFrame.TextRange.Text = text
    box.TextFrame.TextRange.Font.Size = size
    try:
        box.TextFrame.TextRange.Font.Bold = -1 if bold else 0
    except Exception:  # noqa: BLE001
        pass
    return box


def _add_rect(slide, left, top, width, height, name, rgb):
    shape = slide.Shapes.AddShape(MSO_SHAPE_RECTANGLE, left, top, width, height)
    shape.Name = name
    shape.Fill.ForeColor.RGB = rgb
    shape.Line.Visible = False
    return shape


def _blank(pres):
    return pres.Slides.Add(pres.Slides.Count + 1, PP_LAYOUT_BLANK)


def build_16x9(out_path):
    import win32com.client as win32  # noqa: F401

    log("生成 16:9 fixture：%s" % out_path)
    clip = ensure_clip()
    if os.path.exists(out_path):
        os.remove(out_path)
    app = _get_app()
    pres = app.Presentations.Add()
    try:
        pres.PageSetup.SlideWidth = 960
        pres.PageSetup.SlideHeight = 540

        # ---- slide 1: 标题 ----
        s1 = _blank(pres)
        _add_textbox(s1, 70, 180, 820, 90, "PPT 转换测试 · 16:9", size=44, bold=True)
        _add_textbox(s1, 70, 290, 820, 60, "步骤图片 / 嵌入视频 / 备注 / 切换", size=22)

        # ---- slide 2: 3 方块（单击 + afterPrevious 合并） ----
        s2 = _blank(pres)
        _add_textbox(s2, 60, 40, 840, 60, "slide2：多形状单击动画", size=28, bold=True)
        for i in range(3):
            _add_rect(s2, 90 + i * 270, 220, 220, 130, "Box%d" % (i + 1),
                      0x3366CC + i * 0x112233)
        seq = s2.TimeLine.MainSequence
        # AddEffect 必须位置参数（shape, EffectId=10 fade, level=0, trigger=1 click）
        seq.AddEffect(s2.Shapes("Box2"), 10, 0, 1)
        # afterPrevious（trigger=3）应并入同一 step
        seq.AddEffect(s2.Shapes("Box3"), 10, 0, 3)
        s2.SlideShowTransition.EntryEffect = 3849  # fade

        # ---- slide 3: 入场 + 退场 ----
        s3 = _blank(pres)
        _add_textbox(s3, 60, 40, 840, 60, "slide3：入场 + 退场", size=28, bold=True)
        _add_rect(s3, 120, 200, 260, 160, "InBox", 0x2E8B57)
        _add_rect(s3, 560, 200, 260, 160, "OutBox", 0xB22222)
        seq3 = s3.TimeLine.MainSequence
        seq3.AddEffect(s3.Shapes("InBox"), 10, 0, 1)     # 单击入场
        exit_eff = seq3.AddEffect(s3.Shapes("OutBox"), 10, 0, 1)  # 单击退场
        exit_eff.Exit = True
        s3.SlideShowTransition.EntryEffect = 2817  # wipe

        # ---- slide 4: 内嵌视频 ----
        s4 = _blank(pres)
        _add_textbox(s4, 60, 40, 840, 60, "slide4：内嵌视频（mp4）", size=28, bold=True)
        try:
            media = s4.Shapes.AddMediaObject2(clip, False, True, 160, 90, 640, 360)
            media.Name = "clip"
            log("内嵌视频形状: %s" % media.Name)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit("插入内嵌视频失败：%r" % (exc,))
        s4.SlideShowTransition.EntryEffect = 0  # 直切

        # ---- slide 5: 备注 + 强调动画（最终画面不变 → 去重） + 外链视频 ----
        s5 = _blank(pres)
        _add_textbox(s5, 60, 40, 840, 60, "slide5：备注 / 强调 / 外链媒体", size=28, bold=True)
        shape5 = _add_rect(s5, 360, 200, 240, 140, "SpinBox", 0x6E8CA8)
        seq5 = s5.TimeLine.MainSequence
        spin = seq5.AddEffect(s5.Shapes("SpinBox"), 61, 0, 1)  # spin（强调，触发用单击）
        try:
            spin.Exit = False
        except Exception:  # noqa: BLE001
            pass
        try:
            s5.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text = (
                "这是演讲者备注：重点讲三点。\n第二行中文备注。")
            log("备注写入成功")
        except Exception as exc:  # noqa: BLE001
            log("WARN 备注写入失败：%r" % (exc,))
        try:
            ext = s5.Shapes.AddMediaObject2(clip, True, False, 640, 380, 240, 135)
            ext.Name = "ExternalClip"
            log("外链视频形状: %s" % ext.Name)
        except Exception as exc:  # noqa: BLE001
            log("WARN 外链视频插入失败（可忽略）：%r" % (exc,))
        s5.SlideShowTransition.EntryEffect = 3853  # push（实测 3852-3855=push）

        if os.path.exists(out_path):
            os.remove(out_path)
        pres.SaveAs(out_path)
        log("已保存 %s（%d 页, %d bytes）"
            % (out_path, pres.Slides.Count, os.path.getsize(out_path)))
        return {"path": out_path, "slides": int(pres.Slides.Count),
                "bytes": os.path.getsize(out_path)}
    finally:
        try:
            pres.Close()
        except Exception:  # noqa: BLE001
            pass


def build_4x3(out_path):
    log("生成 4:3 fixture：%s" % out_path)
    if os.path.exists(out_path):
        os.remove(out_path)
    app = _get_app()
    pres = app.Presentations.Add()
    try:
        pres.PageSetup.SlideWidth = 720
        pres.PageSetup.SlideHeight = 540

        s1 = _blank(pres)
        _add_textbox(s1, 60, 180, 600, 90, "PPT 转换测试 · 4:3", size=40, bold=True)

        s2 = _blank(pres)
        _add_textbox(s2, 50, 40, 620, 60, "4:3 单击动画", size=26, bold=True)
        _add_rect(s2, 90, 200, 220, 140, "A1", 0x3366CC)
        _add_rect(s2, 400, 200, 220, 140, "A2", 0x2E8B57)
        seq = s2.TimeLine.MainSequence
        seq.AddEffect(s2.Shapes("A1"), 10, 0, 1)
        seq.AddEffect(s2.Shapes("A2"), 10, 0, 1)
        s2.SlideShowTransition.EntryEffect = 3849

        s3 = _blank(pres)
        _add_textbox(s3, 50, 40, 620, 60, "4:3 备注页", size=26, bold=True)
        try:
            s3.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text = "4:3 备注文本。"
        except Exception:  # noqa: BLE001
            pass
        s3.SlideShowTransition.EntryEffect = 2817

        if os.path.exists(out_path):
            os.remove(out_path)
        pres.SaveAs(out_path)
        log("已保存 %s（%d 页）" % (out_path, pres.Slides.Count))
        return {"path": out_path, "slides": int(pres.Slides.Count),
                "bytes": os.path.getsize(out_path)}
    finally:
        try:
            pres.Close()
        except Exception:  # noqa: BLE001
            pass


_APP = None


def _get_app():
    global _APP
    if _APP is not None:
        return _APP
    import pythoncom
    import win32com.client as win32

    pythoncom.CoInitialize()
    app = win32.DispatchEx("PowerPoint.Application")
    try:
        app.DisplayAlerts = 1
    except Exception:  # noqa: BLE001
        pass
    try:
        app.Visible = True
    except Exception:  # noqa: BLE001
        pass
    _APP = app
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="生成 PPT 转换 fixture（PowerPoint COM）")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--out-43", default=DEFAULT_OUT_43)
    parser.add_argument("--only", choices=("16", "43"), default="")
    args = parser.parse_args(argv)

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    result = {}
    try:
        if args.only != "43":
            result["fixture_16x9"] = build_16x9(os.path.abspath(args.out))
        if args.only != "16":
            result["fixture_4x3"] = build_4x3(os.path.abspath(args.out_43))
    finally:
        if _APP is not None:
            try:
                _APP.Quit()
            except Exception:  # noqa: BLE001
                pass
        try:
            import pythoncom

            pythoncom.CoUninitialize()
        except Exception:  # noqa: BLE001
            pass
    result["elapsed_s"] = round(time.time() - t0, 2)
    meta_path = os.path.join(OUT_DIR, "fixture_meta.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    log("完成：%s（耗时 %.2fs）" % (json.dumps(result, ensure_ascii=False), result["elapsed_s"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
