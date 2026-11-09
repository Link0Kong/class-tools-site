# -*- coding: utf-8 -*-
"""test_convert_integration.py — 真实 PowerPoint COM 转换 fixture（集成测试）

前置：``python tests/make_fixture_pptx.py``（缺 fixture 时本测试会自动生成）。

断言（CONTRACT §6/§9 + Lead 追加要求）：
* fixture 16:9 真实转换：manifest v1 合法、页数、图片实际尺寸 1600x900、thumb 宽 400；
* step 规划：单击入场逐步显示、afterPrevious 合并、退场动画产生独立 step；
* 相邻步去重（强调动画页只留 1 步）；
* 内嵌视频：m0.mp4 可被 ffprobe 读出 H.264、manifest media 表、hotspot 0..1；
* 外链视频：跳过不报错（warnings 有记录，manifest 无该热点）；
* 中文备注、切换映射（none/fade/wipe/push）；
* 4:3 fixture：manifest w/h=1600x1200 且图片实际 1600x1200；
* 过程产物写 ``tests/_out/``。
"""
import json
import os
import subprocess
import sys
import time
import unittest

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


def ensure_fixtures():
    if os.path.exists(FIXTURE) and os.path.exists(FIXTURE_43):
        return
    print("[integration] fixture 不存在，先生成 ...", flush=True)
    import make_fixture_pptx
    make_fixture_pptx.main([])


def pil_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


class TestConvert16x9(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
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
        self.assertEqual(len(self.result["assets"]),
                         self.stats["images"] + self.stats["media"])

    def test_10_timing_budget(self):
        # CONTRACT 目标 ≤ 每页 1-2s（含 PowerPoint 启动）；记录真实值供 README
        per_page = self.total_s / max(1, self.stats["slides"])
        print("[integration] 16:9: %.2fs / %d 页 = %.2fs/页"
              % (self.total_s, self.stats["slides"], per_page), flush=True)
        self.assertLess(self.total_s, 300)


class TestConvert4x3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
