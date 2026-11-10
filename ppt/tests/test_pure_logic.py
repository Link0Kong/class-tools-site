# -*- coding: utf-8 -*-
"""test_pure_logic.py — 纯逻辑单测（不依赖 COM / 网络 / OSS）

覆盖：归一化坐标、切换映射、step 规划/降级、页尺寸/切图、buildId、manifest 校验、
PPTX 包解析（真实 zip 结构）、分片拼装、token 刷新、心跳字段类型、脱敏、URL 构造。

运行::

    python tests/test_pure_logic.py -v
"""
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PPT_DIR = os.path.dirname(HERE)
if PPT_DIR not in sys.path:
    sys.path.insert(0, PPT_DIR)

import pptx_xml  # noqa: E402
import convert  # noqa: E402
import oss_upload  # noqa: E402
import agent  # noqa: E402

P_NS = pptx_xml.P_NS
A_NS = pptx_xml.A_NS
R_NS = pptx_xml.R_NS


# ---------------------------------------------------------------------------
# 工具：构造最小 pptx
# ---------------------------------------------------------------------------
def _slide_xml(shapes=""):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sld xmlns:a="%s" xmlns:r="%s" xmlns:p="%s"><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            '%s</p:spTree></p:cSld></p:sld>' % (A_NS, R_NS, P_NS, shapes))


def _pic_xml(shape_id, name, rel_id, off=(100, 200), ext=(300, 400), kind="video"):
    tag = "videoFile" if kind == "v" else "audioFile"
    return (
        '<p:pic><p:nvPicPr><p:cNvPr id="%d" name="%s"/>'
        '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
        '<p:nvPr><a:%s r:link="%s"/></p:nvPr></p:nvPicPr>'
        '<p:blipFill><a:blip r:embed="rId9"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        '<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
        % (shape_id, name, tag, rel_id, off[0], off[1], ext[0], ext[1]))


RELS_HEAD = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">')
RELS_TAIL = "</Relationships>"


def _rel(rid, typ, target, external=False):
    mode = ' TargetMode="External"' if external else ""
    return '<Relationship Id="%s" Type="%s" Target="%s"%s/>' % (rid, typ, target, mode)


NS_VIDEO = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/video"
NS_AUDIO = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio"
NS_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
NS_SLIDE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"


def make_min_pptx(path, slides, slide_w_emu=12192000, slide_h_emu=6858000):
    """slides: [{"pic": xml or "", "rels": [ (rid,type,target,external) ]}]"""
    with zipfile.ZipFile(path, "w") as z:
        presentation = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:presentation xmlns:a="%s" xmlns:r="%s" xmlns:p="%s">'
            '<p:sldIdLst>%s</p:sldIdLst>'
            '<p:sldSz cx="%d" cy="%d"/></p:presentation>'
            % (A_NS, R_NS, P_NS,
               "".join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, i + 1)
                       for i in range(len(slides))),
               slide_w_emu, slide_h_emu))
        z.writestr("ppt/presentation.xml", presentation)
        pres_rels = [RELS_HEAD]
        for i in range(len(slides)):
            pres_rels.append(_rel("rId%d" % (i + 1), NS_SLIDE, "slides/slide%d.xml" % (i + 1)))
        pres_rels.append(RELS_TAIL)
        z.writestr("ppt/_rels/presentation.xml.rels", "".join(pres_rels))
        for i, slide in enumerate(slides):
            n = i + 1
            z.writestr("ppt/slides/slide%d.xml" % n, _slide_xml(slide.get("pic", "")))
            rels = [RELS_HEAD]
            for rid, typ, target, external in slide.get("rels", []):
                rels.append(_rel(rid, typ, target, external))
            rels.append(RELS_TAIL)
            z.writestr("ppt/slides/_rels/slide%d.xml.rels" % n, "".join(rels))
        z.writestr("ppt/media/image1.png", b"\x89PNG fake")
        z.writestr("ppt/media/media1.mp4", b"fake mp4 bytes")
    return path


# ---------------------------------------------------------------------------
# 1. 归一化 / 尺寸 / 切图
# ---------------------------------------------------------------------------
class TestNormalize(unittest.TestCase):
    def test_probe_values(self):
        # 来自真实探测：slide 960x540pt = 12192000x6858000 EMU；视频 off 2032000,1143000 ext 8128000,4572000
        rect = pptx_xml.normalize_rect(2032000, 1143000, 8128000, 4572000,
                                       12192000, 6858000)
        self.assertAlmostEqual(rect["x"], 0.1667, places=4)
        self.assertAlmostEqual(rect["y"], 0.1667, places=4)
        self.assertAlmostEqual(rect["w"], 0.6667, places=4)
        self.assertAlmostEqual(rect["h"], 0.6667, places=4)

    def test_clamp_overflow(self):
        rect = pptx_xml.normalize_rect(-100, -100, 99999999, 99999999, 1000, 1000)
        self.assertEqual(rect, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0})

    def test_clamp_partial(self):
        rect = pptx_xml.normalize_rect(500, 500, 800, 800, 1000, 1000)
        self.assertAlmostEqual(rect["x"], 0.5)
        self.assertAlmostEqual(rect["w"], 0.5)

    def test_negative_ext_abs(self):
        rect = pptx_xml.normalize_rect(100, 100, -200, -200, 1000, 1000)
        self.assertAlmostEqual(rect["w"], 0.2)
        self.assertAlmostEqual(rect["h"], 0.2)

    def test_invalid(self):
        with self.assertRaises(pptx_xml.PptxParseError):
            pptx_xml.normalize_rect(0, 0, 1, 1, 0, 100)
        with self.assertRaises(pptx_xml.PptxParseError):
            pptx_xml.normalize_rect("x", 0, 1, 1, 100, 100)


class TestRenderTarget(unittest.TestCase):
    def test_16_9(self):
        self.assertEqual(pptx_xml.render_target(960, 540), (1600, 900))

    def test_4_3(self):
        self.assertEqual(pptx_xml.render_target(720, 540), (1600, 1200))

    def test_portrait_capped(self):
        w, h = pptx_xml.render_target(540, 960)
        self.assertEqual(max(w, h), 1600)
        self.assertLess(w, h)

    def test_custom_ratio(self):
        self.assertEqual(pptx_xml.render_target(1000, 500), (1600, 800))

    def test_invalid(self):
        with self.assertRaises(pptx_xml.PptxParseError):
            pptx_xml.render_target(0, 540)


class TestAspectLabel(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(pptx_xml.aspect_label(1600, 900), "16:9")
        self.assertEqual(pptx_xml.aspect_label(1600, 1200), "4:3")
        self.assertIn(":", pptx_xml.aspect_label(1600, 800))
        self.assertEqual(pptx_xml.aspect_label(0, 0), "其他")


# ---------------------------------------------------------------------------
# 2. 切换映射（实测值）
# ---------------------------------------------------------------------------
class TestTransition(unittest.TestCase):
    def test_families(self):
        cases = {
            0: "none", 257: "none", 258: "none", 3844: "none",
            1793: "fade", 3849: "fade", 1537: "fade", 3954: "fade",
            1281: "cover", 1285: "cover", 1288: "cover",
            3852: "push", 3853: "push", 3855: "push",
            2817: "wipe", 2820: "wipe", 2561: "wipe",
            3073: "zoom", 3074: "zoom",
            999: "fade", 769: "fade", 3585: "fade", 513: "fade",
        }
        for value, expected in cases.items():
            self.assertEqual(pptx_xml.transition_family(value), expected,
                             "EntryEffect %s" % value)

    def test_invalid_values(self):
        self.assertEqual(pptx_xml.transition_family(None), "fade")
        self.assertEqual(pptx_xml.transition_family("abc"), "fade")
        self.assertEqual(pptx_xml.transition_family(-5), "fade")

    def test_durations(self):
        self.assertEqual(pptx_xml.map_transition(3849), {"tr": "fade", "trd": 450})
        self.assertEqual(pptx_xml.map_transition(0), {"tr": "none", "trd": 0})
        self.assertEqual(pptx_xml.map_transition(3853)["tr"], "push")
        for family in pptx_xml.TRANSITION_FAMILIES:
            self.assertIn(family, pptx_xml.TRANSITION_DURATION_MS)


# ---------------------------------------------------------------------------
# 3. step 规划
# ---------------------------------------------------------------------------
def eff(i, sid, name="", etype=10, exit_=False, trigger=1):
    return {"i": i, "shape_id": sid, "shape_name": name or "S%d" % sid,
            "effect_type": etype, "exit": exit_, "trigger": trigger, "duration": 0.5}


class TestPlanSteps(unittest.TestCase):
    def test_click_entrances(self):
        plan = pptx_xml.plan_steps([eff(1, 3), eff(2, 4)])
        self.assertEqual(len(plan["steps"]), 3)   # 初始 + 2 次点击
        self.assertFalse(plan["initial_visible"][3])
        self.assertFalse(plan["initial_visible"][4])
        # 初始步两个都不可见
        self.assertEqual(plan["steps"][0]["visible"], {3: False, 4: False})
        # 第一步点击后：3 可见，4 仍隐藏
        self.assertEqual(plan["steps"][1]["visible"], {3: True, 4: False})
        # 第二步点击后都可见
        self.assertEqual(plan["steps"][2]["visible"], {3: True, 4: True})

    def test_after_previous_merges(self):
        # Box2 单击入场，Box3 afterPrevious → 同一 step
        plan = pptx_xml.plan_steps([eff(1, 3), eff(2, 4, trigger=3)])
        self.assertEqual(len(plan["steps"]), 2)
        self.assertEqual(plan["steps"][1]["visible"], {3: True, 4: True})

    def test_with_previous_merges(self):
        plan = pptx_xml.plan_steps([eff(1, 3), eff(2, 4, trigger=2)])
        self.assertEqual(len(plan["steps"]), 2)

    def test_exit_initial_visible(self):
        plan = pptx_xml.plan_steps([eff(1, 3, exit_=True)])
        self.assertTrue(plan["initial_visible"][3])
        self.assertEqual(plan["steps"][0]["visible"], {3: True})
        self.assertEqual(plan["steps"][1]["visible"], {3: False})

    def test_emphasis_no_visibility_change(self):
        plan = pptx_xml.plan_steps([eff(1, 3, etype=61, trigger=1)])
        self.assertTrue(plan["initial_visible"][3])   # 强调不是入场 → 初始可见
        self.assertEqual(len(plan["steps"]), 2)
        self.assertEqual(plan["steps"][1]["visible"], {3: True})

    def test_first_auto_effect_visible_in_step0(self):
        # 真实 deck 常见：全部 afterPrevious（自动播放）→ 1 step 且最终内容可见
        plan = pptx_xml.plan_steps([eff(1, 3, trigger=3), eff(2, 4, trigger=2),
                                    eff(3, 5, trigger=3)])
        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(plan["steps"][0]["visible"], {3: True, 4: True, 5: True})
        self.assertFalse(plan["truncated"])

    def test_unknown_shape_id_ignored_for_visibility(self):
        # 无形状的效果仍按单击开 step；但可见性集合里不出现 -1
        plan = pptx_xml.plan_steps([eff(1, -1), eff(2, 4)])
        self.assertEqual(len(plan["steps"]), 3)
        self.assertEqual(plan["animated_ids"], [4])
        self.assertTrue(all(-1 not in step["visible"] for step in plan["steps"]))

    def test_truncation_keeps_final_state(self):
        effects = [eff(i + 1, 100 + i) for i in range(15)]
        plan = pptx_xml.plan_steps(effects, max_steps=12)
        self.assertTrue(plan["truncated"])
        self.assertEqual(len(plan["steps"]), 12)
        final = plan["steps"][-1]
        self.assertTrue(final.get("truncated_tail"))
        self.assertTrue(all(final["visible"][100 + i] for i in range(15)))

    def test_no_effects(self):
        plan = pptx_xml.plan_steps([])
        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(plan["animated_ids"], [])

    def test_degrade_keep2(self):
        plan = pptx_xml.plan_steps([eff(i + 1, 100 + i) for i in range(5)])
        steps = pptx_xml.degrade_plan(plan["steps"], 2)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["index"], 0)
        self.assertEqual(steps[1]["index"], 1)
        # 末步 = 最终完整状态
        self.assertTrue(all(steps[1]["visible"].values()))

    def test_degrade_keep1(self):
        plan = pptx_xml.plan_steps([eff(i + 1, 100 + i) for i in range(3)])
        steps = pptx_xml.degrade_plan(plan["steps"], 1)
        self.assertEqual(len(steps), 1)
        self.assertTrue(all(steps[0]["visible"].values()))

    def test_degrade_noop_when_small(self):
        plan = pptx_xml.plan_steps([eff(1, 3)])
        self.assertEqual(pptx_xml.degrade_plan(plan["steps"], 2), plan["steps"])


# ---------------------------------------------------------------------------
# 4. buildId / manifest 校验
# ---------------------------------------------------------------------------
def minimal_manifest():
    return {
        "v": 1, "base": "https://x/ppt/a/d1/b1/", "src": "", "w": 1600, "h": 900,
        "slides": [{"tr": "fade", "trd": 450, "notes": "", "thumb": "t1.webp",
                    "steps": [{"img": "s1-1.webp", "media": []}]}],
        "media": [],
    }


class TestBuildId(unittest.TestCase):
    def test_stable_and_sensitive(self):
        assets = [{"name": "s1-1.webp", "size": 100}, {"name": "t1.webp", "size": 10}]
        m = minimal_manifest()
        b1 = pptx_xml.compute_build_id(assets, m)
        b2 = pptx_xml.compute_build_id(list(reversed(assets)), m)
        self.assertEqual(b1, b2, "资产顺序不应影响 buildId")
        self.assertEqual(len(b1), 10)
        b3 = pptx_xml.compute_build_id([{"name": "s1-1.webp", "size": 101},
                                        {"name": "t1.webp", "size": 10}], m)
        self.assertNotEqual(b1, b3)
        m2 = dict(m)
        m2["media"] = [{"s": "m0.mp4", "k": "v", "w": 640, "h": 360, "dur": 3.0}]
        self.assertNotEqual(b1, pptx_xml.compute_build_id(assets, m2))

    def test_base_excluded(self):
        # base 依赖 buildId，计算时必须排除（否则自指）；这里验证改 base 不影响
        assets = [{"name": "a.webp", "size": 1}]
        m1, m2 = minimal_manifest(), minimal_manifest()
        m2["base"] = "https://other/"
        self.assertEqual(pptx_xml.compute_build_id(assets, m1),
                         pptx_xml.compute_build_id(assets, m2))


class TestValidateManifest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(pptx_xml.validate_manifest(minimal_manifest()), [])

    def test_invalid_cases(self):
        cases = []
        m = minimal_manifest(); m["v"] = 2; cases.append(m)
        m = minimal_manifest(); m["w"] = 0; cases.append(m)
        m = minimal_manifest(); m["slides"] = []; cases.append(m)
        m = minimal_manifest(); m["slides"][0]["tr"] = "spin"; cases.append(m)
        m = minimal_manifest(); m["slides"][0]["steps"] = []; cases.append(m)
        m = minimal_manifest(); m["slides"][0]["steps"][0]["img"] = ""; cases.append(m)
        m = minimal_manifest(); m["slides"][0]["steps"][0]["media"] = [
            {"s": "m0.mp4", "k": "v", "x": 1.2, "y": 0, "w": 0.1, "h": 0.1}]
        cases.append(m)
        m = minimal_manifest(); m["media"] = [{"s": "m0.mp4", "k": "x"}]; cases.append(m)
        for i, case in enumerate(cases):
            self.assertTrue(pptx_xml.validate_manifest(case), "case %d 应报错" % i)

    def test_media_reference_must_exist(self):
        m = minimal_manifest()
        m["slides"][0]["steps"][0]["media"] = [
            {"s": "m9.mp4", "k": "v", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]
        self.assertTrue(any("media.s" in e for e in pptx_xml.validate_manifest(m)))


# ---------------------------------------------------------------------------
# 5. PPTX 包解析（真实 zip）
# ---------------------------------------------------------------------------
class TestPptxParse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ppt_pure_")
        self.path = os.path.join(self.tmp, "x.pptx")
        pic = _pic_xml(2, "clip", "rId2", off=(2032000, 1143000),
                       ext=(8128000, 4572000), kind="v")
        audio = _pic_xml(3, "bgm", "rId3", off=(0, 0), ext=(12192000, 6858000), kind="a")
        self.path = make_min_pptx(self.path, [
            {"pic": pic, "rels": [
                ("rId2", NS_VIDEO, "../media/media1.mp4", False),
                ("rId4", NS_IMAGE, "../media/image1.png", False)]},
            {"pic": audio, "rels": [("rId3", NS_AUDIO, "../media/media1.mp4", False)]},
            {"pic": _pic_xml(4, "ext", "rId5", kind="v"),
             "rels": [("rId5", NS_VIDEO, "https://example.com/a.mp4", True)]},
        ])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_slide_size(self):
        self.assertEqual(pptx_xml.read_slide_size(self.path), (12192000, 6858000))

    def test_slide_order(self):
        with zipfile.ZipFile(self.path) as z:
            names = pptx_xml.slide_part_names(z)
        self.assertEqual(names, ["ppt/slides/slide1.xml", "ppt/slides/slide2.xml",
                                 "ppt/slides/slide3.xml"])

    def test_media_shapes(self):
        shapes = pptx_xml.read_media_shapes(self.path)
        self.assertEqual(len(shapes), 3)
        v = shapes[0]
        self.assertEqual(v["slide"], 1)
        self.assertEqual(v["name"], "clip")
        self.assertEqual(v["kind"], "v")
        self.assertEqual(v["media"], "media1.mp4")
        self.assertFalse(v["external"])
        self.assertAlmostEqual(v["rect"]["x"], 0.1667, places=4)
        self.assertEqual(shapes[1]["kind"], "a")
        self.assertEqual(shapes[2]["external"], True)
        self.assertTrue(shapes[2]["media"].startswith("https://"))

    def test_media_bytes(self):
        self.assertEqual(pptx_xml.read_media_bytes(self.path, "media1.mp4"),
                         b"fake mp4 bytes")
        self.assertIsNone(pptx_xml.read_media_bytes(self.path, "nope.mp4"))

    def test_bad_zip(self):
        bad = os.path.join(self.tmp, "bad.pptx")
        with open(bad, "wb") as fh:
            fh.write(b"not a zip")
        with self.assertRaises(pptx_xml.PptxParseError):
            pptx_xml.read_slide_size(bad)


# ---------------------------------------------------------------------------
# 6. agent 纯逻辑：分片拼装 / token / 心跳 / 脱敏
# ---------------------------------------------------------------------------
class FakeCloud(object):
    def __init__(self):
        self.rows = []
        self.calls = []
        self.upserts = []

    def get(self, path, timeout=None):
        self.calls.append(path)
        return 200, list(self.rows.pop(0) if isinstance(self.rows, list) and self.rows else [])

    def patch(self, path, body, prefer=None):
        self.calls.append((path, body))
        return 200, [{"id": "d1"}]

    def delete(self, path):
        self.calls.append(("delete", path))
        return 204, None

    def upsert(self, table, rows, on_conflict="id"):
        self.upserts.append((table, rows))
        return 204, None


class TestChunkAssembly(unittest.TestCase):
    def test_pagination_and_order(self):
        import base64
        chunks = {0: b"AAA", 1: b"BBB", 2: b"CC"}
        cloud = FakeCloud()
        cloud.rows = [
            [{"idx": 0, "data": base64.b64encode(chunks[0]).decode()},
             {"idx": 1, "data": base64.b64encode(chunks[1]).decode()}],
            [{"idx": 2, "data": base64.b64encode(chunks[2]).decode()}],
        ]
        data = agent.fetch_chunks(cloud, "d1", 3, lambda m: None)
        self.assertEqual(data, b"AAABBBCC")
        self.assertEqual(len(cloud.calls), 2)
        self.assertIn("order=idx.asc", cloud.calls[0])

    def test_missing_chunk(self):
        import base64
        cloud = FakeCloud()
        cloud.rows = [[{"idx": 0, "data": base64.b64encode(b"x").decode()}]]
        with self.assertRaises(agent.CloudError) as ctx:
            agent.fetch_chunks(cloud, "d1", 3, lambda m: None)
        self.assertIn("分片不完整", str(ctx.exception))

    def test_no_chunks(self):
        cloud = FakeCloud()
        cloud.rows = []
        with self.assertRaises(agent.CloudError):
            agent.fetch_chunks(cloud, "d1", 1, lambda m: None)

    def test_bad_base64_row(self):
        cloud = FakeCloud()
        cloud.rows = [[{"idx": 0, "data": "!!!notbase64!!!"}]]
        with self.assertRaises(agent.CloudError):
            agent.fetch_chunks(cloud, "d1", 1, lambda m: None)


class TestTokenRefresh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ppt_tok_")
        self.old_file = agent.TOKEN_FILE
        agent.TOKEN_FILE = os.path.join(self.tmp, "class-token.json")
        self.cloud = agent.Cloud(base="http://x/", key="pub")

    def tearDown(self):
        agent.TOKEN_FILE = self.old_file
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_refresh_writes_file_without_printing(self):
        calls = []

        def fake_raw(path, body=None, method="GET", token="", prefer=None, timeout=60):
            calls.append(path)
            return 200, {"token": "T" * 64, "exp": 4102444800}

        self.cloud.raw = fake_raw  # type: ignore
        token = self.cloud.ensure_token()
        self.assertEqual(token, "T" * 64)
        self.assertEqual(calls, ["rpc/class_verify"])
        with open(agent.TOKEN_FILE, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["token"], "T" * 64)
        self.assertGreater(saved["exp"], time.time() + 86400 * 20)
        self.assertEqual(set(saved.keys()), {"token", "exp"})

    def test_valid_cached_token_reused(self):
        with open(agent.TOKEN_FILE, "w", encoding="utf-8") as fh:
            json.dump({"token": "CACHED", "exp": 4102444800}, fh)
        calls = []

        def fake_raw(*a, **k):
            calls.append(1)
            return 200, {}

        self.cloud.raw = fake_raw  # type: ignore
        self.assertEqual(self.cloud.ensure_token(), "CACHED")
        self.assertEqual(calls, [])


class TestHeartbeatAndSanitize(unittest.TestCase):
    def test_heartbeat_body_types(self):
        cloud = FakeCloud()
        ok = agent.send_heartbeat(cloud, lambda m, **k: None, "host1", queued=3)
        self.assertTrue(ok)
        table, rows = cloud.upserts[0]
        self.assertEqual(table, "site_assets")
        row = rows if isinstance(rows, dict) else rows[0]
        self.assertEqual(row["id"], "ppt_agent")
        self.assertIsInstance(row["body"]["queued"], int)
        self.assertIsInstance(row["body"]["seen_at"], int)
        self.assertEqual(row["body"]["online"], True)
        self.assertEqual(row["body"]["version"], agent.AGENT_VERSION)
        self.assertIn("host", row["body"])

    def test_sanitize_masks_tokens(self):
        token = "a" * 64
        text = agent.sanitize("Authorization: Bearer %s and X-Device-Id: %s" % (token, token))
        self.assertNotIn(token, text)
        self.assertIn("***", text)

    def test_sanitize_truncates(self):
        self.assertLessEqual(len(agent.sanitize("x" * 1000, 300)), 300)

    def test_format_error_chinese(self):
        msg = agent.format_error(convert.ConvertError("源文件过大"))
        self.assertEqual(msg, "源文件过大")
        msg = agent.format_error(convert.ConvertBusyError("busy"))
        self.assertIn("PowerPoint", msg)
        msg = agent.format_error(convert.ConvertTimeout("超时"))
        self.assertIn("超时", msg)
        self.assertLessEqual(len(msg), 300)


class TestSourceExt(unittest.TestCase):
    def test_ext(self):
        log = lambda m: None
        self.assertEqual(agent.source_ext_from_name("a.PPTX", log), ".pptx")
        self.assertEqual(agent.source_ext_from_name("a.ppt", log), ".ppt")
        self.assertEqual(agent.source_ext_from_name("noext", log), ".pptx")
        with self.assertRaises(convert.ConvertError):
            agent.source_ext_from_name("a.exe", log)


class TestOssHelpers(unittest.TestCase):
    def test_content_type(self):
        self.assertEqual(oss_upload.content_type_for("a.webp"), "image/webp")
        self.assertEqual(oss_upload.content_type_for("a.mp4"), "video/mp4")
        self.assertEqual(oss_upload.content_type_for("a.m4a"), "audio/mp4")
        self.assertEqual(oss_upload.content_type_for("a.pptx"), oss_upload.CONTENT_TYPES[".pptx"])
        self.assertEqual(oss_upload.content_type_for("a.xyz"), "application/octet-stream")

    def test_asset_url(self):
        url = oss_upload.asset_url("s1-1.webp", "ppt/a/d1/b1/")
        self.assertTrue(url.startswith("https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/"))
        self.assertTrue(url.endswith("ppt/a/d1/b1/s1-1.webp"))


class TestConvertOptions(unittest.TestCase):
    def test_defaults_and_override(self):
        opts = convert.normalize_options({"deck_id": "d1", "timeout_s": 60,
                                          "with_media": False, "unknown": 1})
        self.assertEqual(opts["deck_id"], "d1")
        self.assertEqual(opts["timeout_s"], 60)
        self.assertFalse(opts["with_media"])
        self.assertEqual(opts["image_max_bytes"], 200 * 1024)
        self.assertEqual(opts["thumb_max_bytes"], 25 * 1024)
        self.assertEqual(opts["max_steps_per_slide"], 12)
        self.assertEqual(opts["max_images"], 260)

    def test_none_ignored(self):
        opts = convert.normalize_options({"deck_id": "d1", "timeout_s": None})
        self.assertEqual(opts["timeout_s"], convert.DEFAULT_OPTIONS["timeout_s"])


# ---------------------------------------------------------------------------
# 7. v1.2 原样播放视频纯逻辑：animEnd / advance / chapters / 限流 / ffprobe / video 校验
# ---------------------------------------------------------------------------
class TestAnimEnd(unittest.TestCase):
    def test_no_effects(self):
        self.assertEqual(pptx_xml.compute_anim_end([]), 0.0)

    def test_click_serial(self):
        effects = [{"trigger": 1, "duration": 0.5},
                   {"trigger": 1, "duration": 0.75}]
        self.assertAlmostEqual(pptx_xml.compute_anim_end(effects), 1.25, places=3)

    def test_after_previous_with_delay(self):
        effects = [{"trigger": 3, "duration": 0.5, "delay": 0.2},
                   {"trigger": 3, "duration": 0.4, "delay": 0.1}]
        self.assertAlmostEqual(pptx_xml.compute_anim_end(effects), 1.2, places=3)

    def test_with_previous_parallel(self):
        effects = [{"trigger": 1, "duration": 1.0},
                   {"trigger": 2, "duration": 2.0}]
        self.assertAlmostEqual(pptx_xml.compute_anim_end(effects), 2.0, places=3)

    def test_with_previous_does_not_extend_serial_start(self):
        effects = [{"trigger": 1, "duration": 1.0},
                   {"trigger": 2, "duration": 0.5},
                   {"trigger": 1, "duration": 0.5}]
        # 并行组结束于 1.0，串行下一步从 1.0 开始 → 1.5
        self.assertAlmostEqual(pptx_xml.compute_anim_end(effects), 1.5, places=3)

    def test_shape_click_is_serial(self):
        effects = [{"trigger": 4, "duration": 1.0},
                   {"trigger": 4, "duration": 1.0}]
        self.assertAlmostEqual(pptx_xml.compute_anim_end(effects), 2.0, places=3)

    def test_first_with_previous_acts_serial(self):
        self.assertAlmostEqual(
            pptx_xml.compute_anim_end([{"trigger": 2, "duration": 0.8}]), 0.8, places=3)

    def test_invalid_and_negative_ignored(self):
        effects = [{"trigger": "x", "duration": "bad", "delay": -1},
                   {"trigger": 1, "duration": -2.0}]
        self.assertEqual(pptx_xml.compute_anim_end(effects), 0.0)


class TestComputeAdvance(unittest.TestCase):
    def test_minimum_3s(self):
        self.assertEqual(pptx_xml.compute_advance(0.0, 0.0), 3.0)
        self.assertEqual(pptx_xml.compute_advance(1.0, 1.0), 3.0)

    def test_animation_extends_with_pad(self):
        self.assertAlmostEqual(pptx_xml.compute_advance(2.0, 0.0), 3.5, places=3)

    def test_media_extends_with_pad(self):
        self.assertAlmostEqual(pptx_xml.compute_advance(0.0, 10.0), 11.5, places=3)

    def test_max_clamp_600(self):
        self.assertEqual(pptx_xml.compute_advance(0.0, 5000.0), 600.0)

    def test_media_wins_over_animation(self):
        self.assertAlmostEqual(pptx_xml.compute_advance(5.0, 8.0), 9.5, places=3)

    def test_invalid_inputs(self):
        self.assertEqual(pptx_xml.compute_advance("bad", None), 3.0)

    def test_custom_parameters(self):
        self.assertEqual(pptx_xml.compute_advance(2.0, 0.0, min_s=1.0, pad_s=0.5,
                                                  max_s=10.0), 2.5)


class TestChapters(unittest.TestCase):
    def test_basic_formula(self):
        # i>0: t_i = Σ_{j<i}advance_j + Σ_{j<=i}trans_j
        chapters = pptx_xml.compute_chapters([3.0, 4.0], [0.0, 1.0], 20.0)
        self.assertEqual(chapters, [0.0, 4.0])

    def test_first_always_zero(self):
        self.assertEqual(pptx_xml.compute_chapters([5.0], [2.0], 10.0), [0.0])

    def test_monotonic_even_with_transition_gaps(self):
        chapters = pptx_xml.compute_chapters([3.0, 3.0, 3.0], [0.5, 0.5, 0.5], 30.0)
        self.assertEqual(chapters[0], 0.0)
        for a, b in zip(chapters, chapters[1:]):
            self.assertLessEqual(a, b)

    def test_clamped_when_expected_exceeds_real_duration(self):
        chapters = pptx_xml.compute_chapters([3.0, 3.0], [0.0, 0.0], 2.0)
        self.assertEqual(chapters[0], 0.0)
        self.assertLessEqual(chapters[-1], 2.0 - 0.1 + 1e-9)

    def test_proportional_compression(self):
        # raw = [2, 9, 16] > dur-0.1=12.9 → 整体按比例压缩
        chapters = pptx_xml.compute_chapters([5.0, 5.0, 5.0], [2.0, 2.0, 2.0], 13.0)
        self.assertEqual(chapters[0], 0.0)
        self.assertAlmostEqual(chapters[-1], 12.9, places=2)
        self.assertAlmostEqual(chapters[1], 9.0 * 12.9 / 16.0, places=2)
        self.assertLess(chapters[1], chapters[2])

    def test_empty(self):
        self.assertEqual(pptx_xml.compute_chapters([], [], 10.0), [])

    def test_missing_transition_list_tolerated(self):
        self.assertEqual(pptx_xml.compute_chapters([3.0, 3.0], None, 20.0), [0.0, 3.0])


class TestVideoLimits(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(pptx_xml.video_skip_reason(16, 302.4), "")

    def test_slides_over_limit(self):
        reason = pptx_xml.video_skip_reason(121, 100.0)
        self.assertIn("页数超限", reason)
        self.assertIn("120", reason)

    def test_duration_over_limit(self):
        reason = pptx_xml.video_skip_reason(10, 1801.0)
        self.assertIn("预估时长超限", reason)

    def test_boundary_values_ok(self):
        self.assertEqual(pptx_xml.video_skip_reason(120, 1800.0), "")

    def test_custom_limits(self):
        self.assertIn("页数超限", pptx_xml.video_skip_reason(51, 10.0, max_slides=50))
        self.assertIn("预估时长超限",
                      pptx_xml.video_skip_reason(10, 61.0, max_duration_s=60))


class TestParseFfprobe(unittest.TestCase):
    SAMPLE = json.dumps({
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "23.219932"},
    })

    def test_video_and_audio(self):
        info = pptx_xml.parse_ffprobe_json(self.SAMPLE)
        self.assertEqual((info["w"], info["h"]), (1280, 720))
        self.assertAlmostEqual(info["dur"], 23.219932, places=5)
        self.assertEqual(info["codec"], "h264")
        self.assertTrue(info["has_audio"])
        self.assertEqual(info["audio_codec"], "aac")
        self.assertEqual(info["nb_streams"], 2)

    def test_no_audio_track(self):
        info = pptx_xml.parse_ffprobe_json(json.dumps({
            "streams": [{"codec_type": "video", "codec_name": "h264",
                         "width": 960, "height": 720}],
            "format": {"duration": "5.0"},
        }))
        self.assertFalse(info["has_audio"])
        self.assertEqual(info["audio_codec"], "")

    def test_invalid_json(self):
        self.assertIsNone(pptx_xml.parse_ffprobe_json("not json"))
        self.assertIsNone(pptx_xml.parse_ffprobe_json("[]"))

    def test_empty_streams(self):
        info = pptx_xml.parse_ffprobe_json("{}")
        self.assertEqual((info["w"], info["h"], info["dur"]), (0, 0, 0.0))
        self.assertFalse(info["has_audio"])


def _min_manifest(video=None):
    manifest = {
        "v": 1, "base": "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/a/d1/b1/",
        "src": "", "w": 1600, "h": 900, "media": [],
        "slides": [{"tr": "none", "trd": 0, "notes": "", "thumb": "t1.webp",
                    "steps": [{"img": "s1-1.webp", "media": []}]}],
    }
    if video is not None:
        manifest["video"] = video
    return manifest


def _min_video(**overrides):
    video = {"s": "deck.mp4", "w": 1280, "h": 720, "dur": 12.5,
             "chapters": [{"i": 0, "t": 0.0}], "q": "720p"}
    video.update(overrides)
    return video


class TestValidateVideo(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(pptx_xml.validate_video(_min_video(), 1), [])
        self.assertEqual(pptx_xml.validate_manifest(_min_manifest(_min_video())), [])

    def test_manifest_without_video_still_valid(self):
        # 旧数据兼容：没有 manifest.video 的 ready deck 仍合法（仅分步模式）
        self.assertEqual(pptx_xml.validate_manifest(_min_manifest()), [])

    def test_not_object(self):
        self.assertIn("video 必须是对象", pptx_xml.validate_video("x"))

    def test_bad_name_size_duration(self):
        errors = pptx_xml.validate_video({"s": "", "w": 0, "h": -1, "dur": 0,
                                          "chapters": [{"i": 0, "t": 0.0}]})
        text = "; ".join(errors)
        self.assertIn("video.s", text)
        self.assertIn("video.w", text)
        self.assertIn("video.h", text)
        self.assertIn("video.dur", text)

    def test_chapters_count_must_equal_slides(self):
        errors = pptx_xml.validate_video(_min_video(), 2)
        self.assertTrue(any("数量" in e for e in errors))

    def test_chapters_non_monotonic_and_wrong_index(self):
        video = _min_video(chapters=[{"i": 0, "t": 0.0}, {"i": 5, "t": 9.0},
                                     {"i": 2, "t": 8.0}])
        errors = pptx_xml.validate_video(video, 3)
        text = "; ".join(errors)
        self.assertIn("必须等于下标", text)
        self.assertIn("单调不减", text)

    def test_chapter_exceeds_duration_and_first_not_zero(self):
        video = _min_video(chapters=[{"i": 0, "t": 0.5}, {"i": 1, "t": 99.0}])
        errors = pptx_xml.validate_video(video, 2)
        text = "; ".join(errors)
        self.assertIn("chapters[0].t 必须为 0", text)
        self.assertIn("超出视频时长", text)

    def test_empty_chapters(self):
        errors = pptx_xml.validate_video(_min_video(chapters=[]))
        self.assertTrue(any("非空数组" in e for e in errors))


# ---------------------------------------------------------------------------
# 8. agent --video-only：源文件缺失中文错误 / 只新增 video / 保留原 manifest
# ---------------------------------------------------------------------------
class FakeVideoCloud(object):
    def __init__(self, deck):
        self.deck = deck
        self.gets = []
        self.patches = []
        self.upserts = []

    def get(self, path, timeout=None):
        self.gets.append(path)
        return 200, [dict(self.deck)]

    def patch(self, path, body, prefer=None):
        self.patches.append((path, body, prefer))
        return 204, None

    def delete(self, path):
        return 204, None

    def upsert(self, table, rows, on_conflict="id"):
        self.upserts.append((table, rows))
        return 204, None


class FakeVideoUploader(object):
    def __init__(self, fail=False):
        self.fail = fail
        self.puts = []
        self.downloads = []

    def download_to(self, key, path):
        self.downloads.append(key)
        if self.fail:
            raise RuntimeError("NoSuchKey")
        with open(path, "wb") as fh:
            fh.write(b"fake pptx bytes")
        return {"key": key, "path": path, "size": len(b"fake pptx bytes")}

    def put_file(self, key, path, content_type=None, cache_control=None):
        self.puts.append((key, content_type, path))
        return {"key": key, "size": os.path.getsize(path)}


class _FakeHeartbeat(object):
    def __init__(self, *a, **k):
        self.queued = 0

    def start(self):
        pass

    def stop(self):
        pass


class TestVideoOnlyMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ppt_video_only_")
        self.asset_path = os.path.join(self.tmp, "deck.mp4")
        with open(self.asset_path, "wb") as fh:
            fh.write(b"fake mp4")
        self.deck = {
            "id": "d1", "title": "测试", "status": "ready", "deleted": False,
            "source_name": "a.pptx", "source_key": "ppt/src/d1/source.pptx",
            "manifest": _min_manifest(),
        }
        self.video = {"s": "deck.mp4", "w": 1280, "h": 720, "dur": 12.5,
                      "chapters": [{"i": 0, "t": 0.0}], "q": "720p"}
        self.result = {
            "video": self.video,
            "assets": [{"name": "deck.mp4", "path": self.asset_path, "size": 8,
                        "content_type": "video/mp4", "kind": "video"}],
            "stats": {"audio": "aac", "export_s": 1.0},
            "warnings": [],
            "skipped": "",
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, deck=None, uploader=None, dry_run=False, result=None):
        cloud = FakeVideoCloud(deck or self.deck)
        uploader = uploader or FakeVideoUploader()
        log = lambda msg: None
        with mock.patch.object(agent, "new_work_dir",
                               return_value=tempfile.mkdtemp(prefix="ppt_w_")), \
                mock.patch.object(agent, "cleanup_work_dir", return_value=None), \
                mock.patch.object(agent, "HeartbeatThread", _FakeHeartbeat), \
                mock.patch.object(agent.convert, "export_video_only",
                                  return_value=result or self.result):
            summary = agent.run_video_only(cloud, uploader, log, "host1", "d1",
                                           dry_run=dry_run)
        return summary, cloud, uploader

    def test_merge_only_adds_video_and_uploads_to_same_build(self):
        summary, cloud, uploader = self._run()
        self.assertEqual(summary["action"], "video-added")
        self.assertEqual(len(uploader.puts), 1)
        key, content_type, path = uploader.puts[0]
        self.assertEqual(key, "ppt/a/d1/b1/deck.mp4")
        self.assertEqual(content_type, "video/mp4")
        self.assertTrue(path.endswith("deck.mp4"))
        self.assertEqual(uploader.downloads, ["ppt/src/d1/source.pptx"])
        self.assertEqual(len(cloud.patches), 1)
        _path, body, _prefer = cloud.patches[0]
        self.assertEqual(set(body.keys()), {"manifest", "updated_at"})
        merged = body["manifest"]
        self.assertEqual(merged["video"], self.video)
        # 原有 slides/media/notes/base 原样保留
        self.assertEqual(merged["slides"], self.deck["manifest"]["slides"])
        self.assertEqual(merged["media"], [])
        self.assertEqual(merged["base"], self.deck["manifest"]["base"])

    def test_source_missing_gives_chinese_error(self):
        uploader = FakeVideoUploader(fail=True)
        with self.assertRaises(convert.ConvertError) as ctx:
            self._run(uploader=uploader)
        text = str(ctx.exception)
        self.assertIn("源文件缺失", text)
        self.assertIn("重新上传", text)

    def test_not_ready_rejected(self):
        deck = dict(self.deck)
        deck["status"] = "queued"
        with self.assertRaises(agent.CloudError) as ctx:
            self._run(deck=deck)
        self.assertIn("只有 ready", str(ctx.exception))

    def test_empty_manifest_rejected(self):
        deck = dict(self.deck)
        deck["manifest"] = {}
        with self.assertRaises(agent.CloudError) as ctx:
            self._run(deck=deck)
        self.assertIn("manifest 为空", str(ctx.exception))

    def test_video_skipped_keeps_ready_and_no_patch(self):
        result = dict(self.result)
        result["video"] = None
        result["skipped"] = "页数超限（121 页 > 120 页），未生成原样播放视频"
        summary, cloud, uploader = self._run(result=result)
        self.assertEqual(summary["action"], "video-skip")
        self.assertEqual(uploader.puts, [])
        self.assertEqual(cloud.patches, [])
        self.assertIn("页数超限", summary["skipped"])

    def test_dry_run_no_upload_no_patch(self):
        summary, cloud, uploader = self._run(dry_run=True)
        self.assertEqual(summary["action"], "dry-run")
        self.assertEqual(uploader.puts, [])
        self.assertEqual(cloud.patches, [])
        self.assertEqual(summary["video_dur"], 12.5)

    def test_manifest_prefix_requires_oss_base(self):
        manifest = {"base": "https://example.com/abc/"}
        with self.assertRaises(agent.CloudError):
            agent._manifest_prefix(manifest, lambda m: None)


# ---------------------------------------------------------------------------
# 9. v2.0 compat 纯逻辑：文件名清洗 / 外链告警 / 媒体 sha / manifest v2 / 上传重试
# ---------------------------------------------------------------------------
class TestSanitizeFilename(unittest.TestCase):
    def test_removes_illegal_chars(self):
        out = pptx_xml.sanitize_filename('报告/2026:草稿*?"<>|')
        self.assertNotIn("/", out)
        self.assertNotIn(":", out)
        self.assertNotIn("*", out)
        for ch in '*?"<>|':
            self.assertNotIn(ch, out)
        self.assertIn("报告", out)

    def test_empty_and_fallback(self):
        self.assertEqual(pptx_xml.sanitize_filename(""), "演示")
        self.assertEqual(pptx_xml.sanitize_filename(None, fallback="兼容版"), "兼容版")
        self.assertEqual(pptx_xml.sanitize_filename(" . ", fallback="标题"), "标题")

    def test_length_cap(self):
        out = pptx_xml.sanitize_filename("长" * 200, max_len=20)
        self.assertLessEqual(len(out), 20)

    def test_chinese_and_spaces_preserved(self):
        out = pptx_xml.sanitize_filename("  班会   演示  ")
        self.assertEqual(out, "班会 演示")


class TestPathTail(unittest.TestCase):
    def test_basename(self):
        self.assertEqual(pptx_xml.path_tail("file:///C:/a/b/v.mp4"), "v.mp4")
        self.assertEqual(pptx_xml.path_tail("C:\\Users\\x\\视频一.mp4"), "视频一.mp4")

    def test_truncated(self):
        tail = pptx_xml.path_tail("C:/a/" + "x" * 100 + ".mp4", max_len=20)
        self.assertTrue(tail.startswith("…"))
        self.assertEqual(len(tail), 20)

    def test_empty(self):
        self.assertEqual(pptx_xml.path_tail(""), "")


class TestCompatExternalMedia(unittest.TestCase):
    def test_video_and_audio_grouped(self):
        shapes = [
            {"slide": 5, "kind": "v", "external": True,
             "media": "file:///C:/a/clip.mp4"},
            {"slide": 7, "kind": "v", "external": True,
             "media": "C:/b/视频一_播放.mp4"},
            {"slide": 9, "kind": "a", "external": True, "media": "C:/c/a.mp3"},
            {"slide": 2, "kind": "v", "external": False, "media": "media1.mp4"},
        ]
        warnings, places = pptx_xml.compat_external_media(shapes)
        self.assertEqual(len(warnings), 2)  # 视频 / 音频 各一条
        video_warning = [w for w in warnings if "外链视频" in w][0]
        self.assertIn("2 处", video_warning)
        self.assertIn("第 5 页", video_warning)
        self.assertIn("第 7 页", video_warning)
        self.assertIn("clip.mp4", video_warning)
        audio_warning = [w for w in warnings if "外链音频" in w][0]
        self.assertIn("第 9 页", audio_warning)
        self.assertEqual(len(places), 3)
        self.assertEqual(places[0]["slide"], 5)
        self.assertEqual(places[0]["kind"], "v")

    def test_no_external(self):
        warnings, places = pptx_xml.compat_external_media(
            [{"slide": 1, "kind": "v", "external": False, "media": "x.mp4"}])
        self.assertEqual((warnings, places), ([], []))


class TestMediaSha(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ppt_sha_")
        self.path = make_min_pptx(os.path.join(self.tmp, "m.pptx"),
                                  [{"pic": "", "rels": []}])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_media_sha_map_and_set(self):
        sha_map = pptx_xml.media_sha256_map(self.path)
        expected = hashlib.sha256(b"fake mp4 bytes").hexdigest()
        self.assertEqual(sha_map.get("ppt/media/media1.mp4"), expected)
        self.assertIn(expected, pptx_xml.media_sha256_set(self.path))

    def test_non_zip_returns_empty(self):
        bad = os.path.join(self.tmp, "legacy.ppt")
        with open(bad, "wb") as fh:
            fh.write(b"OLE fake")
        self.assertEqual(pptx_xml.media_sha256_map(bad), {})
        self.assertEqual(pptx_xml.media_sha256_set(bad), set())


def _compat_files(sha="a" * 64, size=1234):
    return {
        "compat": {"s": "compat.pptx", "size": size, "sha256": sha,
                   "ext": "pptx", "name": "班会.pptx"},
        "pdf": {"s": "preview.pdf", "size": size, "sha256": sha,
                "pages": 5, "name": "班会.pdf"},
        "source": {"s": "original.pptx", "size": size, "sha256": sha,
                   "ext": "pptx", "name": "原文件.pptx"},
    }


def _compat_manifest(**overrides):
    manifest = {
        "v": 2, "w": 960, "h": 540, "slides": [],
        "files": _compat_files(),
        "compat": {"warnings": [], "fonts_embedded": 0, "converted_from": None},
        "base": "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/a/d1/b1/",
    }
    manifest.update(overrides)
    return manifest


class TestManifestV2(unittest.TestCase):
    def test_valid_compat_manifest(self):
        self.assertEqual(pptx_xml.validate_manifest(_compat_manifest()), [])

    def test_v2_requires_files(self):
        errors = pptx_xml.validate_manifest(_compat_manifest(files=None))
        self.assertTrue(any("files" in e for e in errors))

    def test_v2_requires_compat_and_pdf(self):
        files = _compat_files()
        del files["compat"]
        del files["pdf"]
        errors = pptx_xml.validate_manifest(_compat_manifest(files=files))
        text = "; ".join(errors)
        self.assertIn("files.compat", text)
        self.assertIn("files.pdf", text)

    def test_bad_sha_and_size(self):
        files = _compat_files(sha="xyz", size=0)
        errors = pptx_xml.validate_files(files)
        text = "; ".join(errors)
        self.assertIn("sha256", text)
        self.assertIn("size", text)

    def test_old_v1_manifest_with_files_ok(self):
        manifest = {
            "v": 1, "base": "https://x/ppt/a/d1/b1/", "w": 1600, "h": 900,
            "media": [], "files": _compat_files(),
            "slides": [{"tr": "none", "trd": 0, "notes": "", "thumb": "t1.webp",
                        "steps": [{"img": "s1-1.webp", "media": []}]}],
        }
        self.assertEqual(pptx_xml.validate_manifest(manifest), [])

    def test_v1_without_files_still_valid(self):
        manifest = {
            "v": 1, "base": "https://x/ppt/a/d1/b1/", "w": 1600, "h": 900,
            "media": [],
            "slides": [{"tr": "none", "trd": 0, "notes": "", "thumb": "t1.webp",
                        "steps": [{"img": "s1-1.webp", "media": []}]}],
        }
        self.assertEqual(pptx_xml.validate_manifest(manifest), [])

    def test_compat_meta_type(self):
        errors = pptx_xml.validate_manifest(_compat_manifest(compat="bad"))
        self.assertTrue(any("compat" in e for e in errors))


class FakeRetryUploader(object):
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = []

    def put_file(self, key, path, content_type=None, cache_control=None):
        self.calls.append((key, content_type))
        if len(self.calls) <= self.failures:
            raise RuntimeError("模拟 OSS 失败")
        return {"key": key, "size": 1}


class TestUploadRetry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ppt_retry_")
        self.path = os.path.join(self.tmp, "a.bin")
        with open(self.path, "wb") as fh:
            fh.write(b"x")
        self.asset = {"name": "compat.pptx", "path": self.path, "size": 1,
                      "content_type": "application/x-test"}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_retry_then_success(self):
        uploader = FakeRetryUploader(failures=2)
        agent._put_with_retry(uploader, "ppt/a/d1/b1/x.bin", self.asset,
                              lambda m: None, retries=2)
        self.assertEqual(len(uploader.calls), 3)

    def test_final_failure_raises_chinese_error(self):
        uploader = FakeRetryUploader(failures=3)
        with self.assertRaises(convert.ConvertError) as ctx:
            agent._put_with_retry(uploader, "ppt/a/d1/b1/x.bin", self.asset,
                                  lambda m: None, retries=2)
        text = str(ctx.exception)
        self.assertIn("上传", text)
        self.assertIn("已重试 2 次", text)
        self.assertEqual(len(uploader.calls), 3)

    def test_upload_compat_assets_uses_prefix(self):
        uploader = FakeRetryUploader(failures=0)
        keys = agent.upload_compat_assets(uploader, "ppt/a/d1/b1/",
                                          [self.asset], lambda m: None, retries=2)
        self.assertEqual(keys, ["ppt/a/d1/b1/compat.pptx"])
        self.assertEqual(uploader.calls[0][1], "application/x-test")


class TestCompatOnlyMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ppt_compat_only_")
        self.compat_path = os.path.join(self.tmp, "compat.pptx")
        self.pdf_path = os.path.join(self.tmp, "preview.pdf")
        self.source_path = os.path.join(self.tmp, "original.pptx")
        for path in (self.compat_path, self.pdf_path, self.source_path):
            with open(path, "wb") as fh:
                fh.write(b"data")
        self.old_manifest = {
            "v": 1, "base": "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/"
                            "ppt/a/d1/b1/",
            "src": "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/"
                   "ppt/src/d1/source.pptx",
            "w": 1600, "h": 900, "media": [],
            "slides": [{"tr": "none", "trd": 0, "notes": "", "thumb": "t1.webp",
                        "steps": [{"img": "s1-1.webp", "media": []}]}],
            "video": {"s": "deck.mp4", "w": 1280, "h": 720, "dur": 10.0,
                      "chapters": [{"i": 0, "t": 0.0}], "q": "720p"},
        }
        self.deck = {"id": "d1", "title": "旧演示", "status": "ready",
                     "deleted": False, "source_name": "旧演示.pptx",
                     "source_key": "ppt/src/d1/source.pptx",
                     "manifest": self.old_manifest}
        self.result = {
            "files": _compat_files(),
            "compat": {"warnings": ["外链视频 1 处未随文件携带（第 7 页，路径尾 v.mp4）"],
                       "fonts_embedded": 3, "converted_from": None,
                       "external_media": [{"slide": 7, "kind": "v",
                                           "path_tail": "v.mp4"}]},
            "stats": {"compat_size": 1234, "compat_sha256": "a" * 64,
                      "pdf_size": 100, "pdf_pages": 5, "fonts_embedded": 3},
            "warnings": [],
            "assets": [
                {"name": "compat.pptx", "path": self.compat_path, "size": 4,
                 "content_type": "application/x", "kind": "compat"},
                {"name": "preview.pdf", "path": self.pdf_path, "size": 4,
                 "content_type": "application/pdf", "kind": "pdf"},
                {"name": "original.pptx", "path": self.source_path, "size": 4,
                 "content_type": "application/x", "kind": "source"},
            ],
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, deck=None, dry_run=False, uploader=None, result=None):
        cloud = FakeVideoCloud(deck or self.deck)
        uploader = uploader or FakeVideoUploader()
        with mock.patch.object(agent, "new_work_dir",
                               return_value=tempfile.mkdtemp(prefix="ppt_w_")), \
                mock.patch.object(agent, "cleanup_work_dir", return_value=None), \
                mock.patch.object(agent, "HeartbeatThread", _FakeHeartbeat), \
                mock.patch.object(agent.convert, "convert_compat",
                                  return_value=result or self.result):
            summary = agent.run_compat_only(cloud, uploader, lambda m: None, "host1",
                                            "d1", dry_run=dry_run)
        return summary, cloud, uploader

    def test_merge_keeps_old_fields_and_only_adds_files_compat(self):
        summary, cloud, uploader = self._run()
        self.assertEqual(summary["action"], "compat-added")
        self.assertEqual(len(uploader.puts), 3)
        keys = [k for k, _c, _p in uploader.puts]
        self.assertEqual(keys, ["ppt/a/d1/b1/compat.pptx",
                                "ppt/a/d1/b1/preview.pdf",
                                "ppt/a/d1/b1/original.pptx"])
        self.assertEqual(uploader.downloads, ["ppt/src/d1/source.pptx"])
        self.assertEqual(len(cloud.patches), 1)
        _path, body, _prefer = cloud.patches[0]
        self.assertEqual(set(body.keys()), {"manifest", "updated_at"})
        merged = body["manifest"]
        # 旧字段原样保留
        self.assertEqual(merged["slides"], self.old_manifest["slides"])
        self.assertEqual(merged["video"], self.old_manifest["video"])
        self.assertEqual(merged["src"], self.old_manifest["src"])
        self.assertEqual(merged["v"], 1)
        self.assertEqual(merged["base"], self.old_manifest["base"])
        # 新增 files/compat
        self.assertEqual(merged["files"], self.result["files"])
        self.assertEqual(merged["compat"], self.result["compat"])

    def test_dry_run_no_upload_no_patch(self):
        summary, cloud, uploader = self._run(dry_run=True)
        self.assertEqual(summary["action"], "dry-run")
        self.assertEqual(uploader.puts, [])
        self.assertEqual(cloud.patches, [])
        self.assertEqual(summary["pdf_pages"], 5)

    def test_not_ready_rejected(self):
        deck = dict(self.deck)
        deck["status"] = "queued"
        with self.assertRaises(agent.CloudError) as ctx:
            self._run(deck=deck)
        self.assertIn("只有 ready", str(ctx.exception))

    def test_manifest_missing_rejected(self):
        deck = dict(self.deck)
        deck["manifest"] = {}
        with self.assertRaises(agent.CloudError):
            self._run(deck=deck)

    def test_source_missing_chinese_error(self):
        uploader = FakeVideoUploader(fail=True)
        with self.assertRaises(convert.ConvertError) as ctx:
            self._run(uploader=uploader)
        text = str(ctx.exception)
        self.assertIn("源文件缺失", text)
        self.assertIn("重新上传", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
