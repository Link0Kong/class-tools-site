# -*- coding: utf-8 -*-
"""test_compat_integration.py — v2.0 compat 兼容性处理真实 PowerPoint 集成测试

契约：``web/ppt/CONTRACT.md §12``。

覆盖（CONTRACT §12.5.1）：
* fixture（16:9，含内嵌视频+音轨+外链媒体+备注+切换）转换后
  ``files.compat/pdf/source`` 均存在、体积/sha256 正确、页数=源页数；
* **不降质强断言**：compat.pptx 内嵌媒体 sha256 与源包内媒体**逐字节一致**（不重编码）；
* PDF ``%PDF`` 头 + pypdf 页数=slide_count + 文件大小>0；
* cover.webp 是 WebP、最长边 ≤1600、列表可用；
* 外链媒体：warning 含页号/kind/路径尾，且 compat 包内**仍保留**外链（不删内容）；
* 字体：SaveAs(ppSaveAsOpenXML, EmbedFonts=-1) 后字体部件 >0 且不报错；
* ``.ppt`` fixture → compat ext=pptx、converted_from=ppt、页数一致、原件副本逐字节一致；
* 失败路径：SaveAs 抛错 / PDF 导出抛错 / 媒体字节被改动（疑似重编码）→ 中文 ConvertError。

运行：``python tests\\test_compat_integration.py -v``（缺 fixture 时自动生成，需 PowerPoint）。
"""
import os
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
FIXTURE_PPT = os.path.join(OUT_DIR, "fixture_legacy.ppt")
WORK_16 = os.path.join(OUT_DIR, "compat_work_16x9")
WORK_43 = os.path.join(OUT_DIR, "compat_work_4x3")
WORK_PPT = os.path.join(OUT_DIR, "compat_work_ppt")
WORK_FAIL = os.path.join(OUT_DIR, "compat_work_fail")
WORK_FIX = os.path.join(OUT_DIR, "compat_work_fixvid")


def ensure_fixtures():
    if os.path.exists(FIXTURE) and os.path.exists(FIXTURE_43) and os.path.exists(FIXTURE_PPT):
        return
    print("[compat] fixture 不存在，先生成 ...", flush=True)
    import make_fixture_pptx
    make_fixture_pptx.main([])


def wait_powerpoint_free(timeout_s=240):
    """等待残留 PowerPoint 退出（Quit 后进程可能延迟数秒~数分钟）。"""
    busy, reason = convert.powerpoint_busy()
    if not busy:
        return True, ""
    print("[compat] 等待 PowerPoint 空闲：%s（最多 %ds）" % (reason, timeout_s), flush=True)
    started = time.time()
    while time.time() - started < timeout_s:
        time.sleep(2.0)
        busy, reason = convert.powerpoint_busy()
        if not busy:
            return True, ""
    return False, reason


def require_powerpoint_free():
    ok, reason = wait_powerpoint_free()
    if not ok:
        raise unittest.SkipTest("PowerPoint 被占用/未退出：%s" % reason)


def open_slide_count(path):
    """用 PowerPoint 真正打开文件并读页数（验证兼容包可被 PowerPoint 打开）。"""
    opts = convert.normalize_options({})
    ctx = convert._Ctx(opts, log=lambda m: None)
    import pythoncom

    pythoncom.CoInitialize()
    com = {"app": None, "pres": None}
    try:
        com["app"] = convert._acquire_powerpoint(ctx)
        com["pres"] = com["app"].Presentations.Open(os.path.abspath(path), True,
                                                    False, False)
        return int(com["pres"].Slides.Count)
    finally:
        convert._quiet_shutdown(com, ctx)
        pythoncom.CoUninitialize()


def inspect_media_shape(path, slide_no, shape_id):
    """PowerPoint 打开文件，检查指定页/形状的媒体状态（MediaFormat/LinkFormat）。"""
    opts = convert.normalize_options({})
    ctx = convert._Ctx(opts, log=lambda m: None)
    import pythoncom

    pythoncom.CoInitialize()
    com = {"app": None, "pres": None}
    try:
        com["app"] = convert._acquire_powerpoint(ctx)
        com["pres"] = com["app"].Presentations.Open(os.path.abspath(path), True,
                                                    False, False)
        pres = com["pres"]
        info = {"slides": int(pres.Slides.Count), "found": False, "shape_id": shape_id}
        slide = pres.Slides(int(slide_no))
        for i in range(1, int(slide.Shapes.Count) + 1):
            shape = slide.Shapes(i)
            try:
                if int(shape.Id) != int(shape_id):
                    continue
            except Exception:  # noqa: BLE001
                continue
            info["found"] = True
            try:
                info["type"] = int(shape.Type)
            except Exception:  # noqa: BLE001
                info["type"] = -1
            try:
                info["name"] = str(shape.Name)
            except Exception:  # noqa: BLE001
                info["name"] = ""
            try:
                media = shape.MediaFormat
                for key, attr in (("media_len", "Length"),
                                  ("sample_w", "SampleWidth"),
                                  ("sample_h", "SampleHeight")):
                    try:
                        info[key] = getattr(media, attr)
                    except Exception:  # noqa: BLE001
                        info[key] = None
            except Exception as exc:  # noqa: BLE001
                info["media_err"] = exc.__class__.__name__
            try:
                info["link_source"] = str(shape.LinkFormat.SourceFullName or "")
            except Exception:  # noqa: BLE001
                info["link_source"] = None
        return info
    finally:
        convert._quiet_shutdown(com, ctx)
        pythoncom.CoUninitialize()


def pdf_pages(path):
    from pypdf import PdfReader
    return len(PdfReader(path).pages)


def pil_info(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.format, im.size


def sha256(path):
    return convert.sha256_file(path)


class TestCompatFixture16x9(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
        require_powerpoint_free()
        t0 = time.time()
        cls.result = convert.convert_compat(FIXTURE, WORK_16, {
            "deck_id": "dcompat",
            "title": "测试·兼容版",
            "source_name": os.path.basename(FIXTURE),
            "timeout_s": 600,
            "log": lambda msg: print("[compat16] " + msg, flush=True),
        })
        cls.total_s = round(time.time() - t0, 2)
        cls.manifest = cls.result["manifest"]
        cls.assets = {a["name"]: a for a in cls.result["assets"]}
        print("[compat] 16:9 转换耗时 %.2fs，stats=%s"
              % (cls.total_s, cls.result["stats"]), flush=True)

    def test_01_manifest_v2(self):
        manifest = self.manifest
        self.assertEqual(pptx_xml.validate_manifest(manifest), [])
        self.assertEqual(manifest["v"], 2)
        self.assertEqual((manifest["w"], manifest["h"]), (960, 540))
        self.assertEqual(manifest["slides"], [])  # compat 不再生成分步图
        self.assertEqual(set(manifest["files"].keys()), {"compat", "pdf", "source"})
        self.assertEqual(self.result["aspect"], "16:9")
        self.assertEqual(self.result["step_count"], 0)

    def test_02_files_exist_and_sha(self):
        manifest = self.manifest
        base = manifest["base"]
        self.assertTrue(base.startswith(
            "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/a/dcompat/"))
        for key, asset_name in (("compat", "compat.pptx"), ("pdf", "preview.pdf"),
                                ("source", "original.pptx")):
            entry = manifest["files"][key]
            self.assertEqual(entry["s"], asset_name)
            asset = self.assets[asset_name]
            self.assertTrue(os.path.exists(asset["path"]), asset_name)
            self.assertGreater(entry["size"], 0)
            self.assertEqual(entry["size"], os.path.getsize(asset["path"]))
            self.assertEqual(entry["sha256"], sha256(asset["path"]), key)
            self.assertEqual(len(entry["sha256"]), 64)
        # 下载文件名（中文可用）
        self.assertEqual(manifest["files"]["compat"]["name"], "测试·兼容版.pptx")
        self.assertEqual(manifest["files"]["compat"]["ext"], "pptx")
        self.assertEqual(manifest["files"]["pdf"]["name"], "测试·兼容版.pdf")
        self.assertEqual(manifest["files"]["source"]["name"], os.path.basename(FIXTURE))
        self.assertEqual(manifest["files"]["source"]["ext"], "pptx")

    def test_03_pages_source_and_compat(self):
        source_slides = len(pptx_xml.slide_part_names(pptx_xml.open_zip(FIXTURE)[0]))
        compat_path = self.assets["compat.pptx"]["path"]
        compat_slides = len(pptx_xml.slide_part_names(pptx_xml.open_zip(compat_path)[0]))
        self.assertEqual(source_slides, 5)
        self.assertEqual(compat_slides, source_slides)
        self.assertEqual(self.result["slide_count"], source_slides)
        # 真正用 PowerPoint 打开兼容包验证可打开 + 页数
        self.assertEqual(open_slide_count(compat_path), source_slides)

    def test_04_no_reencode_media_sha_equal(self):
        """质量红线：compat 包内媒体字节必须与源包逐字节一致（不重采样/不重编码）。"""
        compat_path = self.assets["compat.pptx"]["path"]
        src_map = pptx_xml.media_sha256_map(FIXTURE)
        dst_map = pptx_xml.media_sha256_map(compat_path)
        self.assertGreaterEqual(len(src_map), 2)  # fixture：1 图 + 1 内嵌视频
        self.assertEqual(dst_map, src_map, "兼容包媒体 sha256 与源包不一致（疑似重编码）")
        self.assertIn("ppt/media/media1.mp4", src_map)

    def test_05_pdf(self):
        pdf_path = self.assets["preview.pdf"]["path"]
        with open(pdf_path, "rb") as fh:
            self.assertTrue(fh.read(5).startswith(b"%PDF"))
        pages = pdf_pages(pdf_path)
        self.assertEqual(pages, 5)
        self.assertEqual(self.manifest["files"]["pdf"]["pages"], pages)
        self.assertEqual(self.manifest["files"]["pdf"]["name"], "测试·兼容版.pdf")

    def test_06_cover_webp(self):
        cover = self.assets.get("cover.webp")
        self.assertIsNotNone(cover)
        fmt, size = pil_info(cover["path"])
        self.assertEqual(fmt, "WEBP")
        self.assertLessEqual(max(size), 1600)
        self.assertEqual(size, (1600, 900))
        self.assertEqual(self.result["cover"], "cover.webp")

    def test_07_fonts_embedded(self):
        meta = self.manifest["compat"]
        self.assertGreaterEqual(meta["fonts_embedded"], 1, "应嵌入 TrueType 字体")
        self.assertIsNone(meta["converted_from"])

    def test_08_external_media_warning_kept(self):
        meta = self.manifest["compat"]
        self.assertEqual(meta.get("repairs", []), [])  # 该 fixture 外链目标存在，不应误修复
        self.assertEqual(len(meta["external_media"]), 1)
        place = meta["external_media"][0]
        self.assertEqual(place["slide"], 5)
        self.assertEqual(place["kind"], "v")
        warnings = "\n".join(meta["warnings"])
        self.assertIn("外链视频", warnings)
        self.assertIn("第 5 页", warnings)
        self.assertIn("clip.mp4", warnings)
        # 不删除内容：兼容包内该外链媒体仍然存在
        compat_shapes = pptx_xml.read_media_shapes(self.assets["compat.pptx"]["path"])
        externals = [s for s in compat_shapes if s.get("external")]
        self.assertEqual(len(externals), 1, "外链媒体不得被删除")
        self.assertEqual(externals[0]["slide"], 5)

    def test_09_source_copy_byte_identical(self):
        self.assertEqual(self.manifest["files"]["source"]["sha256"], sha256(FIXTURE))
        self.assertEqual(self.assets["original.pptx"]["size"], os.path.getsize(FIXTURE))

    def test_10_timing_budget(self):
        print("[compat] 16:9: %.2fs / 5 页 = %.2fs/页"
              % (self.total_s, self.total_s / 5.0), flush=True)
        self.assertLess(self.total_s, 300)


class TestCompatFixture43(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
        require_powerpoint_free()
        t0 = time.time()
        cls.result = convert.convert_compat(FIXTURE_43, WORK_43, {
            "deck_id": "dcompat43",
            "title": "4:3兼容",
            "source_name": "4比3.pptx",
            "timeout_s": 600,
            "log": lambda msg: print("[compat43] " + msg, flush=True),
        })
        cls.total_s = round(time.time() - t0, 2)
        cls.manifest = cls.result["manifest"]
        cls.assets = {a["name"]: a for a in cls.result["assets"]}

    def test_01_manifest_and_pages(self):
        self.assertEqual(pptx_xml.validate_manifest(self.manifest), [])
        self.assertEqual((self.manifest["w"], self.manifest["h"]), (720, 540))
        self.assertEqual(self.result["aspect"], "4:3")
        self.assertEqual(self.manifest["files"]["pdf"]["pages"], 3)
        self.assertEqual(pdf_pages(self.assets["preview.pdf"]["path"]), 3)
        self.assertEqual(len(pptx_xml.slide_part_names(
            pptx_xml.open_zip(self.assets["compat.pptx"]["path"])[0])), 3)

    def test_02_cover_4x3(self):
        fmt, size = pil_info(self.assets["cover.webp"]["path"])
        self.assertEqual(fmt, "WEBP")
        self.assertEqual(size, (1600, 1200))

    def test_03_no_media_no_warning(self):
        self.assertEqual(self.manifest["compat"]["external_media"], [])
        self.assertEqual(self.manifest["compat"]["warnings"], [])


class TestCompatFromPpt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
        require_powerpoint_free()
        t0 = time.time()
        cls.result = convert.convert_compat(FIXTURE_PPT, WORK_PPT, {
            "deck_id": "dcompl",
            "title": "旧格式",
            "source_name": os.path.basename(FIXTURE_PPT),
            "timeout_s": 600,
            "log": lambda msg: print("[compatppt] " + msg, flush=True),
        })
        cls.total_s = round(time.time() - t0, 2)
        cls.manifest = cls.result["manifest"]
        cls.assets = {a["name"]: a for a in cls.result["assets"]}
        print("[compat] .ppt 转换耗时 %.2fs" % cls.total_s, flush=True)

    def test_01_converted_pptx(self):
        self.assertEqual(pptx_xml.validate_manifest(self.manifest), [])
        self.assertEqual(self.manifest["v"], 2)
        self.assertEqual(self.manifest["files"]["compat"]["ext"], "pptx")
        self.assertEqual(self.manifest["compat"]["converted_from"], "ppt")
        self.assertEqual(self.manifest["files"]["source"]["ext"], "ppt")
        self.assertEqual(self.manifest["files"]["source"]["s"], "original.ppt")

    def test_02_pages_and_openable(self):
        compat_path = self.assets["compat.pptx"]["path"]
        self.assertEqual(len(pptx_xml.slide_part_names(
            pptx_xml.open_zip(compat_path)[0])), 3)
        self.assertEqual(open_slide_count(compat_path), 3)
        self.assertEqual(self.manifest["files"]["pdf"]["pages"], 3)
        self.assertEqual(self.result["slide_count"], 3)

    def test_03_source_copy_original(self):
        self.assertEqual(self.manifest["files"]["source"]["sha256"], sha256(FIXTURE_PPT))
        self.assertTrue(os.path.exists(self.assets["original.ppt"]["path"]))


def _break_slide_video_rels(path, rels_name="ppt/slides/_rels/slide4.xml.rels",
                             media_target="../media/media1.mp4"):
    """把一个 compat 包里的 video 关系改回「External/NULL 断链」状态（模拟用户 deck slide7）。"""
    import re
    import zipfile
    with zipfile.ZipFile(path) as zf:
        entries = {info.filename: zf.read(info.filename) for info in zf.infolist()}
    text = entries[rels_name].decode("utf-8")

    def repl(match):
        tag = match.group(0)
        if "/relationships/video" in tag and media_target in tag:
            tag = re.sub(r'\s+Target="[^"]*"', ' Target="NULL"', tag, count=1)
            tag = tag[:-2].rstrip() + ' TargetMode="External"/>'
        return tag

    entries[rels_name] = re.sub(r'<Relationship\b[^>]*/>', repl, text).encode("utf-8")
    tmp = path + ".broken.tmp"
    with zipfile.ZipFile(tmp, "w") as zout:
        for name, data in entries.items():
            zout.writestr(name, data)
    os.replace(tmp, path)
    return path


class TestCompatBrokenVideoRepair(unittest.TestCase):
    """断链视频（video 关系 External/NULL）但同页存在内嵌副本 → compat 包内内部化。

    真实用户 deck dmwalrdlgevz90l 的 slide7 即此结构（Lead 证据）：
    `a:videoFile r:link=rId1` → video rel External Target="NULL"，同形状
    `p14:media r:embed=rId2` → ../media/media1.mp4（有效内嵌副本）。
    本机 PowerPoint SaveAs 对 fixture 可能自动修复该结构，因此测试里在 SaveAs 完成后
    再把 slide4 的视频关系改回断链（等价于真实 deck 被 SaveAs 原样保留的情况），
    验证 convert_compat 的修复阶段会内部化并写入 manifest.compat.repairs。
    """

    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
        require_powerpoint_free()
        real_repair = pptx_xml.repair_broken_video_links
        repair_calls = []

        def break_then_repair(path, out_path=None):
            # 模拟「PowerPoint SaveAs 原样保留断链」：修复阶段开始前把 video 关系改回 External/NULL
            _break_slide_video_rels(path)
            repair_calls.append(path)
            return real_repair(path, out_path)

        t0 = time.time()
        with mock.patch.object(convert.pptx_xml, "repair_broken_video_links",
                               side_effect=break_then_repair):
            cls.result = convert.convert_compat(FIXTURE, WORK_FIX, {
                "deck_id": "dfixvid",
                "title": "断链视频修复",
                "source_name": os.path.basename(FIXTURE),
                "timeout_s": 600,
                "log": lambda msg: print("[compat-fixvid] " + msg, flush=True),
            })
        cls.total_s = round(time.time() - t0, 2)
        cls.manifest = cls.result["manifest"]
        cls.assets = {a["name"]: a for a in cls.result["assets"]}
        cls.repair_calls = len(repair_calls)
        print("[compat] 断链视频修复 fixture 转换耗时 %.2fs，repairs=%s（修复阶段调用 %d 次）"
              % (cls.total_s, cls.manifest["compat"].get("repairs"),
                 cls.repair_calls), flush=True)

    def test_00_repair_stage_invoked(self):
        self.assertEqual(self.repair_calls, 1, "compat 流水线必须调用断链视频修复阶段")

    def test_01_repair_recorded(self):
        meta = self.manifest["compat"]
        repairs = meta.get("repairs") or []
        self.assertEqual(len(repairs), 1, "slide4 断链视频应被内嵌副本修复")
        item = repairs[0]
        self.assertEqual(item["slide"], 4)
        self.assertEqual(item["name"], "clip")
        self.assertEqual(item["media"], "media1.mp4")
        import zipfile
        with zipfile.ZipFile(FIXTURE) as zf:
            src_bytes = len(zf.read("ppt/media/media1.mp4"))
        self.assertEqual(item["bytes"], src_bytes)  # fixture 内嵌 clip.mp4 原始字节数
        # fixture 第 5 页另有「目标文件真实存在」的外链媒体，不属断链、保持外部+告警（不误修复）
        self.assertEqual(len(meta["external_media"]), 1)
        self.assertEqual(meta["external_media"][0]["slide"], 5)

    def test_02_rels_internalized(self):
        compat = self.assets["compat.pptx"]["path"]
        import zipfile
        with zipfile.ZipFile(compat) as zf:
            rels = zf.read("ppt/slides/_rels/slide4.xml.rels").decode("utf-8")
            video_lines = [ln for ln in rels.splitlines()
                           if "/relationships/video" in ln]
            self.assertEqual(len(video_lines), 1)
            self.assertIn('Target="../media/media1.mp4"', video_lines[0])
            self.assertNotIn("TargetMode", video_lines[0])
            self.assertIsNone(zf.testzip())
        shapes = pptx_xml.read_media_shapes(compat)
        slide4 = [s for s in shapes if s["slide"] == 4]
        self.assertEqual(len(slide4), 1)
        self.assertFalse(slide4[0]["external"])
        self.assertEqual(slide4[0]["media"], "media1.mp4")

    def test_03_media_bytes_unchanged(self):
        compat = self.assets["compat.pptx"]["path"]
        src_map = pptx_xml.media_sha256_map(FIXTURE)
        dst_map = pptx_xml.media_sha256_map(compat)
        self.assertEqual(dst_map, src_map, "修复不得改动任何媒体字节")
        self.assertEqual(self.manifest["files"]["compat"]["sha256"],
                         sha256(compat))

    def test_04_pdf_fonts_pages_not_regressed(self):
        self.assertEqual(pptx_xml.validate_manifest(self.manifest), [])
        pages = pdf_pages(self.assets["preview.pdf"]["path"])
        self.assertEqual(pages, 5)
        self.assertEqual(self.manifest["files"]["pdf"]["pages"], 5)
        self.assertGreaterEqual(self.manifest["compat"]["fonts_embedded"], 1)
        self.assertGreater(self.assets["compat.pptx"]["size"], 0)

    def test_05_powerpoint_opens_repaired_media(self):
        compat = self.assets["compat.pptx"]["path"]
        info = inspect_media_shape(compat, 4, 3)  # fixture slide4 视频 shape id=3
        self.assertEqual(info["slides"], 5)
        self.assertTrue(info["found"], "slide4 视频形状应存在")
        self.assertEqual(info["type"], 16)
        self.assertIsNotNone(info.get("media_len"))
        self.assertGreater(float(info.get("media_len") or 0), 0)
        self.assertEqual((int(info.get("sample_w") or 0),
                          int(info.get("sample_h") or 0)), (640, 360))
        print("[compat] PowerPoint 打开修复后 compat：slide4 shape3 len=%sms %sx%s"
              % (info.get("media_len"), info.get("sample_w"), info.get("sample_h")),
              flush=True)


class TestCompatFailures(unittest.TestCase):
    """失败路径：中文 ConvertError（不产生 ready 半成品）。"""

    def setUp(self):
        ensure_fixtures()
        require_powerpoint_free()

    def _convert(self, work_name):
        return convert.convert_compat(FIXTURE, os.path.join(OUT_DIR, work_name), {
            "deck_id": "dcompatfail",
            "title": "失败路径",
            "source_name": os.path.basename(FIXTURE),
            "timeout_s": 300,
            "log": lambda msg: None,
        })

    def test_01_saveas_failure(self):
        with mock.patch.object(convert, "_save_compat_package",
                               side_effect=convert.ConvertError("保存兼容包失败（模拟）")):
            with self.assertRaises(convert.ConvertError) as ctx:
                self._convert("compat_work_fail_save")
        self.assertIn("保存兼容包失败", str(ctx.exception))

    def test_02_pdf_failure(self):
        with mock.patch.object(convert, "_export_compat_pdf_and_cover",
                               side_effect=convert.ConvertError("PDF 兼容副本导出失败（模拟）")):
            with self.assertRaises(convert.ConvertError) as ctx:
                self._convert("compat_work_fail_pdf")
        self.assertIn("PDF", str(ctx.exception))

    def test_03_reencode_detected(self):
        real = convert._inspect_compat_package

        def tampered(ctx, path):
            info = real(ctx, path)
            if info["media"]:
                first = sorted(info["media"])[0]
                info["media"] = dict(info["media"])
                info["media"][first] = "0" * 64  # 模拟媒体被重编码
            return info

        with mock.patch.object(convert, "_inspect_compat_package", side_effect=tampered):
            with self.assertRaises(convert.ConvertError) as ctx:
                self._convert("compat_work_fail_tamper")
        self.assertIn("媒体字节与原文件不一致", str(ctx.exception))


def tearDownModule():
    try:
        busy, reason = convert.powerpoint_busy()
    except Exception as exc:  # noqa: BLE001
        print("[compat] WARN 残留检查失败：%s" % exc.__class__.__name__, flush=True)
        return
    if busy:
        print("[compat] WARN 检测到残留 PowerPoint：%s" % reason, flush=True)
    else:
        print("[compat] 收尾检查：无残留 PowerPoint 实例", flush=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
