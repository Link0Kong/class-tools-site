# -*- coding: utf-8 -*-
"""test_convert_integration.py — 真实 PowerPoint COM 转换 fixture（集成测试）

前置：``python tests/make_fixture_pptx.py``（缺 fixture 时本测试会自动生成）。

断言（CONTRACT §6/§9 + §11.7 v1.2 + Lead 追加要求）：
* fixture 16:9 真实转换：manifest v1 合法、页数、图片实际尺寸 1600x900、thumb 宽 400；
* step 规划：单击入场逐步显示、afterPrevious 合并、退场动画产生独立 step；
* 相邻步去重（强调动画页只留 1 步）；
* 内嵌视频：m0.mp4 可被 ffprobe 读出 H.264、manifest media 表、hotspot 0..1；
* **v1.2 原样播放视频**：manifest.video 存在、ffprobe 断言 h264 + aac、dur>0、
  chapters 数==页数且单调、末章 t<dur；**帧级验证**媒体页视频段内间隔 1s 抽帧
  内容平均差高于阈值（证明真的播放而非海报帧）；
* 外链视频：跳过不报错（warnings 有记录，manifest 无该热点）；
* 中文备注、切换映射（none/fade/wipe/push）；
* 4:3 fixture：manifest w/h=1600x1200 且图片实际 1600x1200；
* **降级路径**：mock ``CreateVideo`` 抛错 → 仍 ready，manifest 无 video + warning；
* **真实 tuanri deck**（16 页动画+切换）：导出视频 chapters=16、dur>0、记录耗时；
* 过程产物写 ``tests/_out/``。
"""
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PPT_DIR = os.path.dirname(HERE)
if PPT_DIR not in sys.path:
    sys.path.insert(0, PPT_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import convert  # noqa: E402
import pptx_xml  # noqa: E402

OUT_DIR = os.path.join(HERE, "_out")
FIXTURE = os.path.join(OUT_DIR, "fixture_deck.pptx")
FIXTURE_43 = os.path.join(OUT_DIR, "fixture_deck_43.pptx")
WORK_16 = os.path.join(OUT_DIR, "work_16x9")
WORK_43 = os.path.join(OUT_DIR, "work_4x3")
WORK_DEGRADED = os.path.join(OUT_DIR, "work_degraded")
WORK_TUANRI = os.path.join(OUT_DIR, "work_tuanri")
TUANRI_DECK = r"C:\Users\Ko_Li\.openclaw\workspace\tuanri_deck\本草孝心_传承岐黄孝道_团日活动.pptx"


def ensure_fixtures():
    if os.path.exists(FIXTURE) and os.path.exists(FIXTURE_43):
        return
    print("[integration] fixture 不存在，先生成 ...", flush=True)
    import make_fixture_pptx
    make_fixture_pptx.main([])


def wait_powerpoint_free(timeout_s=180):
    """等待 PowerPoint 空闲（Quit 后进程可能延迟数秒~数分钟才真正退出）。

    连续转换（测试/补转）时上一轮的 POWERPNT.EXE 可能仍在退出中；此时
    ``powerpoint_busy()`` 会报「进程存在但无法连接」。测试里先等它退出，
    超时则 skip（不误报 ERROR）。
    """
    busy, reason = convert.powerpoint_busy()
    if not busy:
        return True, ""
    print("[integration] 等待 PowerPoint 空闲：%s（最多 %ds）" % (reason, timeout_s),
          flush=True)
    started = time.time()
    while time.time() - started < timeout_s:
        time.sleep(2.0)
        busy, reason = convert.powerpoint_busy()
        if not busy:
            print("[integration] PowerPoint 已空闲（等待 %.1fs）" % (time.time() - started),
                  flush=True)
            return True, ""
    return False, reason


def require_powerpoint_free():
    ok, reason = wait_powerpoint_free()
    if not ok:
        raise unittest.SkipTest("PowerPoint 被占用/未退出（可能用户正在编辑）：%s" % reason)


def pil_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def extract_frame(video_path, t, dst_path):
    """ffmpeg 在 ``t`` 秒抽一帧 JPG（精度 ~0.1s）。"""
    ffmpeg = convert._find_tool("ffmpeg", "")
    proc = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                           "-ss", "%.3f" % float(t), "-i", video_path,
                           "-frames:v", "1", "-q:v", "2", dst_path],
                          capture_output=True, text=True)
    return (proc.returncode == 0 and os.path.exists(dst_path)
            and os.path.getsize(dst_path) > 0)


def frame_mean_diff(path_a, path_b):
    """两帧平均像素差（0..255）。"""
    from PIL import Image, ImageChops, ImageStat
    with Image.open(path_a) as img_a, Image.open(path_b) as img_b:
        diff = ImageChops.difference(img_a.convert("RGB"), img_b.convert("RGB"))
        return sum(ImageStat.Stat(diff).mean) / 3.0


class TestConvert16x9(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
        require_powerpoint_free()
        t0 = time.time()
        cls.result = convert.convert_deck(FIXTURE, WORK_16, {
            "deck_id": "dtestfix",
            "timeout_s": 300,
            "log": lambda msg: print("[convert] " + msg, flush=True),
        })
        cls.total_s = round(time.time() - t0, 2)
        cls.manifest = cls.result["manifest"]
        cls.assets = {a["name"]: a for a in cls.result["assets"]}
        cls.stats = cls.result["stats"]
        print("[integration] 16:9 转换耗时 %.2fs，stats=%s"
              % (cls.total_s, json.dumps(cls.stats, ensure_ascii=False)), flush=True)

    @classmethod
    def tearDownClass(cls):
        # 过程产物保留在 tests/_out/（交付前统一清理）
        pass

    def test_01_manifest_valid(self):
        errors = pptx_xml.validate_manifest(self.manifest)
        self.assertEqual(errors, [], "manifest 校验失败：%s" % errors)
        self.assertEqual(self.manifest["v"], 1)
        self.assertEqual((self.manifest["w"], self.manifest["h"]), (1600, 900))
        self.assertTrue(self.manifest["base"].startswith(
            "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/a/dtestfix/"))
        self.assertTrue(self.manifest["base"].endswith("/"))
        self.assertIn("/ppt/a/dtestfix/", self.manifest["base"])
        self.assertIn("/ppt/src/dtestfix/source.pptx", self.manifest["src"])

    def test_02_slide_count_and_transitions(self):
        slides = self.manifest["slides"]
        self.assertEqual(len(slides), 5)
        expected = ["none", "fade", "wipe", "none", "push"]
        self.assertEqual([s["tr"] for s in slides], expected)
        self.assertEqual(slides[1]["trd"], 450)
        self.assertGreater(slides[2]["trd"], 0)

    def test_03_image_sizes(self):
        # 每页 step 图 1600x900；缩略图宽 400
        for slide_no in range(1, 6):
            for name, asset in self.assets.items():
                if name.startswith("s%d-" % slide_no):
                    self.assertEqual(pil_size(asset["path"]), (1600, 900), name)
                    self.assertLessEqual(os.path.getsize(asset["path"]), 200 * 1024, name)
        for slide_no in range(1, 6):
            thumb = self.assets["t%d.webp" % slide_no]
            w, h = pil_size(thumb["path"])
            self.assertEqual(w, 400, thumb["name"])
            self.assertEqual(h, 225, thumb["name"])
            self.assertLessEqual(os.path.getsize(thumb["path"]), 25 * 1024, thumb["name"])

    def test_04_step_planning(self):
        slides = self.manifest["slides"]
        # slide1 无动画 → 1 步
        self.assertEqual(len(slides[0]["steps"]), 1)
        # slide2：Box2 单击 + Box3 afterPrevious → 初始 + 1 步 = 2
        self.assertEqual(len(slides[1]["steps"]), 2)
        # slide3：初始（OutBox 可见/InBox 隐藏）+ 入场 + 退场 = 3 步
        self.assertEqual(len(slides[2]["steps"]), 3)
        # slide4 视频页无动画 → 1 步
        self.assertEqual(len(slides[3]["steps"]), 1)
        # slide5 强调动画与上一步字节相同 → 去重为 1 步
        self.assertEqual(len(slides[4]["steps"]), 1)
        # 计划步数 > 实际（去重生效）
        self.assertGreater(self.stats["planned_steps"], self.stats["steps"])

    def test_05_visibility_steps_differ(self):
        # step0 隐藏单击入场形状 → 与后续步图片字节不同（说明 Visible 快照生效）
        s2a = self.assets["s2-1.webp"]["path"]
        s2b = self.assets["s2-2.webp"]["path"]
        with open(s2a, "rb") as fh:
            a = fh.read()
        with open(s2b, "rb") as fh:
            b = fh.read()
        self.assertNotEqual(a, b)
        # 退场页：3 张图两两不同
        s3 = [self.assets["s3-%d.webp" % i]["path"] for i in (1, 2, 3)]
        blobs = []
        for path in s3:
            with open(path, "rb") as fh:
                blobs.append(fh.read())
        self.assertEqual(len(set(blobs)), 3)

    def test_06_embedded_video(self):
        media = self.manifest["media"]
        self.assertEqual(len(media), 1, "应只有 1 个内嵌视频（外链应跳过）")
        item = media[0]
        self.assertEqual(item["s"], "m0.mp4")
        self.assertEqual(item["k"], "v")
        self.assertEqual((item["w"], item["h"]), (640, 360))
        self.assertAlmostEqual(item["dur"], 3.0, places=1)
        asset = self.assets["m0.mp4"]
        self.assertTrue(os.path.exists(asset["path"]))
        info = convert._ffprobe_info(convert._find_tool("ffprobe", ""), asset["path"])
        self.assertIsNotNone(info)
        self.assertEqual(info["codec"], "h264")
        self.assertEqual((info["w"], info["h"]), (640, 360))
        # 视频海报帧在 step 图中；hotspot 在 slide4 第 1 步
        hotspots = [h for slide in self.manifest["slides"] for step in slide["steps"]
                    for h in step.get("media") or []]
        self.assertEqual(len(hotspots), 1)
        hs = hotspots[0]
        self.assertEqual(hs["s"], "m0.mp4")
        for key in ("x", "y", "w", "h"):
            self.assertGreaterEqual(hs[key], 0.0)
            self.assertLessEqual(hs[key], 1.0)
        self.assertAlmostEqual(hs["x"], 0.1667, places=3)
        self.assertAlmostEqual(hs["y"], 0.1667, places=3)
        self.assertAlmostEqual(hs["w"], 0.6667, places=3)
        self.assertAlmostEqual(hs["h"], 0.6667, places=3)
        self.assertEqual(self.manifest["slides"][3]["steps"][0]["media"][0]["s"], "m0.mp4")

    def test_07_external_media_skipped(self):
        # fixture 第 5 页有外链视频：跳过并记录 warning，不产生热点
        warnings = "\n".join(self.result["warnings"])
        self.assertIn("外链媒体", warnings)
        self.assertEqual(len(self.manifest["media"]), 1)
        slide5_media = [h for step in self.manifest["slides"][4]["steps"]
                        for h in step.get("media") or []]
        self.assertEqual(slide5_media, [])

    def test_08_notes(self):
        notes = self.manifest["slides"][4]["notes"]
        self.assertIn("演讲者备注", notes)
        self.assertIn("第二行中文备注", notes)
        self.assertNotIn("\n4", notes)   # 页码占位不混入
        self.assertEqual(self.manifest["slides"][0]["notes"], "")

    def test_09_asset_sizes_and_cover(self):
        self.assertEqual(self.result["cover"], "t1.webp")
        self.assertEqual(self.stats["slides"], 5)
        self.assertEqual(self.stats["media"], 1)
        self.assertEqual(self.stats["degraded_slides"], 0)
        for asset in self.result["assets"]:
            self.assertGreater(asset["size"], 0, asset["name"])
            self.assertTrue(os.path.exists(asset["path"]), asset["name"])
        video_assets = [a for a in self.result["assets"] if a.get("kind") == "video"]
        self.assertEqual(len(self.result["assets"]),
                         self.stats["images"] + self.stats["media"] + len(video_assets))
        self.assertEqual(len(video_assets), 1, "原样播放视频应作为一个资产上传")
        self.assertEqual(video_assets[0]["name"], "deck.mp4")

    def test_10_timing_budget(self):
        # CONTRACT 目标 ≤ 每页 1-2s（含 PowerPoint 启动）；记录真实值供 README
        per_page = self.total_s / max(1, self.stats["slides"])
        print("[integration] 16:9: %.2fs / %d 页 = %.2fs/页"
              % (self.total_s, self.stats["slides"], per_page), flush=True)
        self.assertLess(self.total_s, 300)

    # -- v1.2 原样播放视频（CONTRACT §11.1/§11.7） --------------------------
    def test_11_video_manifest(self):
        video = self.manifest.get("video")
        self.assertIsNotNone(video, "fixture 含内嵌视频+音轨，应生成 manifest.video")
        self.assertEqual(pptx_xml.validate_video(video, len(self.manifest["slides"])), [])
        self.assertEqual(video["s"], "deck.mp4")
        self.assertEqual(video["q"], "720p")
        self.assertGreater(video["dur"], 0)
        self.assertEqual(video["w"], 1280)
        self.assertEqual(video["h"], 720)
        chapters = video["chapters"]
        self.assertEqual(len(chapters), len(self.manifest["slides"]))
        self.assertEqual(chapters[0], {"i": 0, "t": 0.0})
        for k, chapter in enumerate(chapters):
            self.assertEqual(chapter["i"], k)
        times = [c["t"] for c in chapters]
        self.assertEqual(times, sorted(times))
        self.assertLess(times[-1], video["dur"])
        self.assertTrue(self.stats["video"])
        self.assertIn(self.stats["video_audio"], ("aac",))
        self.assertGreater(self.result["video"]["dur"], 0)
        print("[integration] video: dur=%.2fs %dx%d audio=%s bytes=%d chapters=%d "
              "export=%.2fs"
              % (video["dur"], video["w"], video["h"], self.stats["video_audio"],
                 self.stats["video_bytes"], len(chapters),
                 self.stats["video_export_s"]), flush=True)

    def test_12_video_codec_and_audio(self):
        asset = self.assets.get("deck.mp4")
        self.assertIsNotNone(asset, "manifest.video 存在时应有 deck.mp4 资产")
        self.assertEqual(asset["content_type"], "video/mp4")
        info = convert._ffprobe_info(convert._find_tool("ffprobe", ""), asset["path"])
        self.assertIsNotNone(info)
        self.assertEqual(info["codec"], "h264")          # CONTRACT §11.1
        self.assertEqual((info["w"], info["h"]), (1280, 720))
        self.assertGreater(info["dur"], 0)
        self.assertTrue(info["has_audio"], "fixture 内嵌媒体带音轨 → 视频应有音轨")
        self.assertEqual(info["audio_codec"], "aac")      # CONTRACT §11.1

    def test_13_video_frames_really_play(self):
        """帧级验证：媒体页视频段内**间隔 1s** 抽 3 帧，内容确实在变（不是海报定格）。"""
        video = self.manifest["video"]
        asset = self.assets["deck.mp4"]
        chapters = video["chapters"]
        # fixture 第 4 页（0-based 3）是内嵌视频页；advance=media+1.5，媒体在页首 PlayOnEntry
        page_t = float(chapters[3]["t"])
        next_t = float(chapters[4]["t"]) if len(chapters) > 4 else float(video["dur"])
        self.assertGreater(next_t - page_t, 3.0, "媒体页应至少 3s（media+1.5s）")
        # 避开页首切换瞬间（+0.4s 起），在 3s 媒体段内按 1s 间隔取 3 帧
        samples = []
        for k, offset in enumerate((0.4, 1.4, 2.4)):
            path = os.path.join(OUT_DIR, "frame_media_%d.jpg" % k)
            self.assertTrue(extract_frame(asset["path"], page_t + offset, path))
            samples.append(path)
        diffs = [frame_mean_diff(samples[0], samples[1]),
                 frame_mean_diff(samples[1], samples[2])]
        print("[integration] 媒体页 1s 间隔抽帧平均差 = %s" % diffs, flush=True)
        self.assertGreater(max(diffs), 2.0, "媒体页视频段内 1s 后画面应有明显变化"
                                            "（PlayOnEntry 未生效时会定格为海报帧，差值≈0）")


class TestConvert4x3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
        require_powerpoint_free()
        t0 = time.time()
        cls.result = convert.convert_deck(FIXTURE_43, WORK_43, {
            "deck_id": "dtestfix43",
            "timeout_s": 300,
            "log": lambda msg: print("[convert43] " + msg, flush=True),
        })
        cls.total_s = round(time.time() - t0, 2)
        cls.manifest = cls.result["manifest"]
        cls.assets = {a["name"]: a for a in cls.result["assets"]}
        print("[integration] 4:3 转换耗时 %.2fs" % cls.total_s, flush=True)

    def test_01_manifest_4x3(self):
        self.assertEqual(pptx_xml.validate_manifest(self.manifest), [])
        self.assertEqual((self.manifest["w"], self.manifest["h"]), (1600, 1200))
        self.assertEqual(self.result["aspect"], "4:3")
        self.assertEqual(len(self.manifest["slides"]), 3)

    def test_02_image_actual_size(self):
        for slide_no in (1, 2, 3):
            name = self.assets["s%d-1.webp" % slide_no]["path"]
            self.assertEqual(pil_size(name), (1600, 1200), "s%d-1.webp" % slide_no)
        # 缩略图宽 400，高按 4:3 = 300
        w, h = pil_size(self.assets["t1.webp"]["path"])
        self.assertEqual((w, h), (400, 300))

    def test_03_steps_and_transition(self):
        slides = self.manifest["slides"]
        self.assertEqual(len(slides[1]["steps"]), 3)   # 初始 + 2 次单击
        self.assertEqual([s["tr"] for s in slides], ["none", "fade", "wipe"])
        self.assertIn("4:3 备注文本", slides[2]["notes"])

    def test_04_video_4x3(self):
        video = self.manifest.get("video")
        self.assertIsNotNone(video)
        self.assertEqual(video["chapters"][0]["t"], 0.0)
        self.assertEqual(len(video["chapters"]), 3)
        self.assertGreater(video["dur"], 0)
        # VertResolution=720 → 高 720；宽随页面比例（4:3=960，若被 letterbox 则 1280）
        self.assertEqual(video["h"], 720)
        self.assertGreater(video["w"], 0)
        print("[integration] 4:3 video: %dx%d dur=%.2fs"
              % (video["w"], video["h"], video["dur"]), flush=True)


class TestConvertVideoDegraded(unittest.TestCase):
    """CreateVideo 失败 → 只跳过视频，分步模式照常 ready（CONTRACT §11.2.2）。"""

    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
        require_powerpoint_free()
        t0 = time.time()
        with mock.patch.object(convert, "_call_create_video",
                               side_effect=RuntimeError("模拟 CreateVideo 失败")):
            cls.result = convert.convert_deck(FIXTURE_43, WORK_DEGRADED, {
                "deck_id": "dtestdegraded",
                "timeout_s": 300,
                "log": lambda msg: print("[convert-degraded] " + msg, flush=True),
            })
        cls.total_s = round(time.time() - t0, 2)
        cls.manifest = cls.result["manifest"]
        cls.assets = {a["name"]: a for a in cls.result["assets"]}
        print("[integration] 降级路径（CreateVideo 抛错）耗时 %.2fs" % cls.total_s,
              flush=True)

    def test_01_ready_without_video(self):
        self.assertNotIn("video", self.manifest)
        self.assertIsNone(self.result.get("video"))
        self.assertEqual(pptx_xml.validate_manifest(self.manifest), [])
        self.assertEqual(len(self.manifest["slides"]), 3)
        self.assertFalse(self.result["stats"]["video"])
        self.assertNotIn("deck.mp4", self.assets)
        for slide in self.manifest["slides"]:
            self.assertTrue(slide["steps"])
            self.assertIn(slide["steps"][0]["img"], self.assets)

    def test_02_warning_recorded(self):
        warnings = "\n".join(self.result["warnings"])
        self.assertIn("跳过原样播放视频", warnings)
        self.assertIn("CreateVideo", warnings)

    def test_03_images_still_uploaded(self):
        images = [a for a in self.result["assets"] if a.get("kind") == "image"]
        self.assertGreaterEqual(len(images), 3 * 2)  # 每页 ≥1 step 图 + 1 thumb
        for asset in images:
            self.assertGreater(os.path.getsize(asset["path"]), 0)


class TestRealTuanriDeckVideo(unittest.TestCase):
    """真实 tuanri deck（16 页动画+切换）导出原样播放视频（CONTRACT §11.7.1）。"""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(TUANRI_DECK):
            raise unittest.SkipTest("缺少真实 tuanri deck：%s" % TUANRI_DECK)
        require_powerpoint_free()
        t0 = time.time()
        cls.result = convert.export_video_only(TUANRI_DECK, WORK_TUANRI, {
            "deck_id": "dtuanri",
            "timeout_s": 900,
            "log": lambda msg: print("[convert-tuanri] " + msg, flush=True),
        })
        cls.total_s = round(time.time() - t0, 2)
        print("[integration] tuanri 真实 16 页视频导出耗时 %.2fs，stats=%s"
              % (cls.total_s, json.dumps(cls.result.get("stats"), ensure_ascii=False)),
              flush=True)

    def test_01_video_exists(self):
        video = self.result.get("video")
        self.assertIsNotNone(video, "真实 16 页 deck 应导出视频：%s"
                             % (self.result.get("skipped") or ""))
        self.assertEqual(pptx_xml.validate_video(video, 16), [])
        self.assertEqual(len(video["chapters"]), 16)
        self.assertEqual(video["chapters"][0]["t"], 0.0)
        times = [c["t"] for c in video["chapters"]]
        self.assertEqual(times, sorted(times))
        self.assertGreater(video["dur"], 0)
        self.assertLess(times[-1], video["dur"])
        # 记录真实耗时（供 README/交付说明）
        print("[integration] tuanri video: dur=%.2fs %dx%d audio=%s bytes=%d "
              "export=%.2fs chapters=%d"
              % (video["dur"], video["w"], video["h"],
                 self.result.get("stats", {}).get("audio") or "无",
                 self.result.get("stats", {}).get("bytes") or 0,
                 self.result.get("stats", {}).get("export_s") or 0,
                 len(video["chapters"])), flush=True)
        self.assertLess(self.total_s, 600)

    def test_02_video_file_probe(self):
        assets = self.result.get("assets") or []
        self.assertEqual(len(assets), 1)
        asset = assets[0]
        self.assertEqual(asset["name"], "deck.mp4")
        self.assertTrue(os.path.exists(asset["path"]))
        info = convert._ffprobe_info(convert._find_tool("ffprobe", ""), asset["path"])
        self.assertIsNotNone(info)
        self.assertEqual(info["codec"], "h264")
        self.assertGreater(info["dur"], 0)


def tearDownModule():
    """测试结束检查残留 PowerPoint（本套件自己创建的实例都应在 convert 收尾时 Quit）。"""
    try:
        busy, reason = convert.powerpoint_busy()
    except Exception as exc:  # noqa: BLE001
        print("[integration] WARN 残留检查失败：%s" % exc.__class__.__name__, flush=True)
        return
    if busy:
        print("[integration] WARN 检测到残留 PowerPoint：%s"
              "（若为中断残留：确认无人编辑后结束 POWERPNT.EXE）" % reason, flush=True)
    else:
        print("[integration] 收尾检查：无残留 PowerPoint 实例", flush=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
