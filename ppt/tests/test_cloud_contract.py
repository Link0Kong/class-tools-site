# -*- coding: utf-8 -*-
"""test_cloud_contract.py — CloudBase / OSS 契约冒烟 + 真实链路 E2E

契约：``web/ppt/CONTRACT.md`` §3/§4/§6。测试身份：学号 3260799999 / 姓名 测试账号
（``rpc/class_verify`` 换取 token，token 绝不打印）。

覆盖（Lead 要求）：

1. RLS/分片：建行 → 分片上传/读取 → 管理员读 → 匿名读为空 → 删除分片 → 软删（清理干净）；
2. 失败路径：分片缺失 → agent 认领后 PATCH failed + 中文 error、chunks 已删、下一轮不重复认领；
3. 删除态 deck 不被认领；
4. token 过期刷新（mock 过期 exp，走真实 ``rpc/class_verify``）；
5. 心跳行 ``ppt_agent``（queued 为 int、seen_at 为 ms）；
6. **真实 OSS 链路 E2E**（Lead 要求保留交付验收用）：
   - 嵌入视频 fixture（16:9，含 m0.mp4）→ 上传分片 → queued → agent 真实转换 →
     PATCH ready → manifest media hotspot 0..1 → OSS HEAD mp4 = 200 + Content-Type video/mp4；
   - 4:3 fixture → 同上 → manifest w/h=1600x1200。
   这两个 deck 默认**保留**（标题带「测试·」前缀，交付前由 Lead 统一 soft-delete + 清 OSS）。

运行::

    python tests/test_cloud_contract.py -v

注意：会产生云端临时行（测试统一在 finally 清理），以及两个保留的 ready fixture deck。
"""
import base64
import json
import os
import re
import sys
import time
import unittest
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PPT_DIR = os.path.dirname(HERE)
if PPT_DIR not in sys.path:
    sys.path.insert(0, PPT_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import agent  # noqa: E402
import convert  # noqa: E402
import oss_upload  # noqa: E402
import pptx_xml  # noqa: E402

FIXTURE = os.path.join(HERE, "_out", "fixture_deck.pptx")
FIXTURE_43 = os.path.join(HERE, "_out", "fixture_deck_43.pptx")
TEST_SID = "3260799999"
TEST_NAME = "测试账号"
TITLE_MARKER_VIDEO = "测试·嵌入视频演示"
TITLE_MARKER_43 = "测试·4:3 演示"
CHUNK_RAW = 512 * 1024

_LOG = []


def log(msg):
    _LOG.append(str(msg))
    print("[cloud] " + str(msg), flush=True)


def ensure_fixtures():
    if os.path.exists(FIXTURE) and os.path.exists(FIXTURE_43):
        return
    import make_fixture_pptx
    make_fixture_pptx.main([])


def now_ms():
    return int(time.time() * 1000)


def make_deck_id(prefix="dtest"):
    # 契约：d + base36(ts) + 6 位随机字母数字；测试用固定前缀便于清理
    import random
    import string
    return prefix + base64.b32encode(os.urandom(6)).decode().lower().rstrip("=")[:6] \
        + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def verify_test_token():
    """测试账号 token（只返回 token 本身，不打印）。"""
    import urllib.error

    cloud = agent.Cloud(log=log)
    status, out = cloud.raw("rpc/class_verify", {"p_sid": TEST_SID, "p_name": TEST_NAME}, "POST")
    if status != 200 or not isinstance(out, dict) or not out.get("token"):
        raise RuntimeError("class_verify 测试身份失败：HTTP %s" % status)
    return str(out["token"])


class TestAccountCloud(object):
    """测试账号（成员身份）PostgREST 客户端 —— 仅用于客户端行为模拟。"""

    def __init__(self):
        self._admin = agent.Cloud(log=log)
        self.token = verify_test_token()

    def raw(self, path, body=None, method="GET", prefer=None):
        return self._admin.raw(path, body, method, self.token, prefer)

    def get(self, path):
        return self.raw(path)

    def post(self, path, body, prefer="return=representation"):
        return self.raw(path, body, "POST", prefer)

    def patch(self, path, body, prefer="return=representation"):
        return self.raw(path, body, "PATCH", prefer)

    def delete(self, path):
        return self.raw(path, None, "DELETE")


class TestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
        cls.admin = agent.Cloud(log=log)
        cls.member = TestAccountCloud()
        cls.host = "test-host"
        cls.created_decks = []

    def _new_deck(self, member, title, source_name, source_bytes, status="uploading"):
        deck_id = make_deck_id()
        now = now_ms()
        status_code, out = member.post("ppt_decks", [{
            "id": deck_id, "title": title, "owner_sid": TEST_SID,
            "owner_name": TEST_NAME, "client": "test", "status": status,
            "source_name": source_name, "source_size": len(source_bytes),
            "chunk_count": 0, "created_at": now, "updated_at": now, "deleted": False,
        }], prefer="return=representation")
        self.assertIn(status_code, (200, 201), "建 deck 失败：%s %s" % (status_code, out))
        self.created_decks.append(deck_id)
        return deck_id

    def _upload_chunks(self, member, deck_id, data, chunk_size=CHUNK_RAW):
        rows = []
        total = (len(data) + chunk_size - 1) // chunk_size
        for idx in range(total):
            part = data[idx * chunk_size:(idx + 1) * chunk_size]
            rows.append({"deck_id": deck_id, "owner_sid": TEST_SID, "idx": idx,
                         "data": base64.b64encode(part).decode(), "ts": now_ms()})
        status_code, out = member.post("ppt_upload_chunks", rows,
                                       prefer="resolution=merge-duplicates,return=minimal")
        self.assertIn(status_code, (200, 201, 204), "分片上传失败：%s %s" % (status_code, out))
        return total

    def _submit(self, member, deck_id, chunk_count, source_size):
        status_code, out = member.patch(
            "ppt_decks?id=eq.%s" % deck_id,
            {"status": "queued", "chunk_count": chunk_count,
             "source_size": source_size, "updated_at": now_ms()},
            prefer="return=representation")
        self.assertIn(status_code, (200, 201), "提交转换失败：%s %s" % (status_code, out))

    def _soft_delete(self, deck_id):
        try:
            self.admin.patch("ppt_decks?id=eq.%s" % deck_id,
                             {"deleted": True, "updated_at": now_ms()},
                             prefer="return=minimal")
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def tearDownClass(cls):
        # 清理本轮所有临时 deck（软删 + 分片删除）；保留 fixture ready deck 在子类里另行处理
        for deck_id in getattr(cls, "created_decks", []):
            try:
                cls.admin.delete("ppt_upload_chunks?deck_id=eq.%s" % deck_id)
            except Exception:  # noqa: BLE001
                pass
            try:
                cls.admin.patch("ppt_decks?id=eq.%s" % deck_id,
                                {"deleted": True, "updated_at": now_ms()},
                                prefer="return=minimal")
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# 1. RLS / 分片 / 软删
# ---------------------------------------------------------------------------
class TestRlsAndChunks(TestBase):
    def test_01_member_crud_and_rls(self):
        data = os.urandom(700 * 1024)
        deck_id = self._new_deck(self.member, "测试·RLS 冒烟", "rls.pptx", data)
        count = self._upload_chunks(self.member, deck_id, data)
        self.assertEqual(count, 2)

        # 本人读分片
        status, rows = self.member.get(
            "ppt_upload_chunks?deck_id=eq.%s&select=idx&order=idx.asc" % deck_id)
        self.assertEqual(status, 200)
        self.assertEqual([r["idx"] for r in rows], [0, 1])

        # 管理员（转换机）读分片
        status, rows = self.admin.get(
            "ppt_upload_chunks?deck_id=eq.%s&select=idx&order=idx.asc" % deck_id)
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 2)

        # 匿名读 deck 列表 → 200 + 空数组（RLS 生效）
        status, rows = self.admin.raw(
            "ppt_decks?select=id&deleted=eq.false&id=eq.%s" % deck_id)
        self.assertEqual(status, 200)
        self.assertEqual(rows, [])

        # 本人读自己的 deck（auth_ok）
        status, rows = self.member.get("ppt_decks?select=id,status&id=eq.%s" % deck_id)
        self.assertEqual(status, 200)
        self.assertEqual(rows[0]["id"], deck_id)

        # 提交转换 → 管理员在 queued 队列能看到
        self._submit(self.member, deck_id, count, len(data))
        status, rows = self.admin.get(
            "ppt_decks?select=id&status=eq.queued&deleted=eq.false&limit=100")
        self.assertIn(deck_id, [r["id"] for r in rows])

        # 本人删除分片（RLS pc_delete）
        status, _ = self.member.delete("ppt_upload_chunks?deck_id=eq.%s" % deck_id)
        self.assertIn(status, (200, 204))
        status, rows = self.admin.get("ppt_upload_chunks?deck_id=eq.%s" % deck_id)
        self.assertEqual(rows, [])

        # 软删（owner）
        status, _ = self.member.patch("ppt_decks?id=eq.%s" % deck_id,
                                      {"deleted": True, "updated_at": now_ms()},
                                      prefer="return=minimal")
        self.assertIn(status, (200, 204))
        status, rows = self.admin.get("ppt_decks?select=deleted&id=eq.%s" % deck_id)
        self.assertEqual(rows[0]["deleted"], True)


# ---------------------------------------------------------------------------
# 2. 失败路径：分片缺失 → failed + 中文 error + chunks 清理 + 不重复认领
# ---------------------------------------------------------------------------
class TestFailurePath(TestBase):
    def test_01_missing_chunk_marks_failed(self):
        data = os.urandom(900 * 1024)          # 需要 2 片
        deck_id = self._new_deck(self.member, "测试·失败路径", "broken.pptx", data)
        count = self._upload_chunks(self.member, deck_id, data)
        self.assertEqual(count, 2)
        self._submit(self.member, deck_id, count, len(data))
        # 模拟上传不完整：删掉第 1 片
        status, _ = self.member.delete("ppt_upload_chunks?deck_id=eq.%s&idx=eq.1" % deck_id)
        self.assertIn(status, (200, 204))

        uploader = oss_upload.OssUploader(log=log)
        summary = agent.run_once(self.admin, uploader, log, self.host,
                                 deck_id=deck_id, dry_run=False)
        self.assertEqual(summary["action"], "failed", summary)
        status, rows = self.admin.get(
            "ppt_decks?select=status,error,progress&id=eq.%s" % deck_id)
        self.assertEqual(status, 200)
        row = rows[0]
        self.assertEqual(row["status"], "failed")
        self.assertRegex(row["error"], r"[\u4e00-\u9fff]", "error 必须是中文：%r" % row["error"])
        self.assertLessEqual(len(row["error"]), 300)
        self.assertIn("分片", row["error"])

        # 分片已被清理
        status, rows = self.admin.get("ppt_upload_chunks?select=idx&deck_id=eq.%s" % deck_id)
        self.assertEqual(rows, [])
        log("失败路径 OK：status=failed error=%r" % row["error"])

        # 下一轮不会重复认领（failed 不在 queued 队列；且无 deck 参数时不应改回 processing）
        summary2 = agent.run_once(self.admin, uploader, log, self.host, dry_run=False)
        self.assertEqual(summary2["action"], "none",
                         "队列为空时下一轮应是 none，而不是重新认领 failed deck：%s" % summary2)
        status, rows = self.admin.get("ppt_decks?select=status,progress&id=eq.%s" % deck_id)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["progress"], 0)


# ---------------------------------------------------------------------------
# 3. 删除态 deck 不被认领
# ---------------------------------------------------------------------------
class TestDeletedDeckNotClaimed(TestBase):
    def test_01_deleted_queued_not_claimed(self):
        data = b"deleted deck payload" * 100
        deck_id = self._new_deck(self.member, "测试·已删除", "gone.pptx", data)
        count = self._upload_chunks(self.member, deck_id, data)
        self._submit(self.member, deck_id, count, len(data))
        # 先软删（queued + deleted=true）
        status, _ = self.admin.patch("ppt_decks?id=eq.%s" % deck_id,
                                     {"deleted": True, "updated_at": now_ms()},
                                     prefer="return=minimal")
        self.assertIn(status, (200, 204))
        summary = agent.run_once(self.admin, oss_upload.OssUploader(log=log), log,
                                 self.host, dry_run=True)
        self.assertNotEqual(summary.get("deck"), deck_id,
                            "deleted deck 不应被认领")
        status, rows = self.admin.get("ppt_decks?select=status,deleted&id=eq.%s" % deck_id)
        self.assertEqual(rows[0]["deleted"], True)
        self.assertEqual(rows[0]["status"], "queued", "被软删的 deck 不应被改状态")


# ---------------------------------------------------------------------------
# 4. token 过期刷新（mock 过期 exp）
# ---------------------------------------------------------------------------
class TestTokenRefreshReal(unittest.TestCase):
    def test_01_expired_token_refreshes(self):
        import tempfile

        old_file = agent.TOKEN_FILE
        tmpdir = tempfile.mkdtemp(prefix="ppt_tokreal_")
        try:
            agent.TOKEN_FILE = os.path.join(tmpdir, "class-token.json")
            with open(agent.TOKEN_FILE, "w", encoding="utf-8") as fh:
                json.dump({"token": "x" * 64, "exp": time.time() - 10}, fh)
            cloud = agent.Cloud(log=log)
            token = cloud.ensure_token()
            self.assertTrue(token and len(token) > 20)
            self.assertNotEqual(token, "x" * 64)
            with open(agent.TOKEN_FILE, encoding="utf-8") as fh:
                saved = json.load(fh)
            self.assertEqual(saved["token"], token)
            self.assertGreater(saved["exp"], time.time() + 3600)
            # 用刷新后的 token 真的能读（RLS auth_ok）
            status, rows = cloud.raw("ppt_decks?select=id&limit=1", None, "GET", token)
            self.assertEqual(status, 200)
            log("token 过期刷新 OK（新 token 长度 %d，未打印内容）" % len(token))
        finally:
            agent.TOKEN_FILE = old_file
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. 心跳行
# ---------------------------------------------------------------------------
class TestHeartbeat(TestBase):
    def test_01_heartbeat_row(self):
        ok = agent.send_heartbeat(self.admin, log, self.host, queued=2)
        self.assertTrue(ok)
        status, rows = self.admin.get(
            "site_assets?select=id,body&id=eq.%s" % agent.AGENT_ID)
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 1)
        body = rows[0]["body"]
        self.assertEqual(body["online"], True)
        self.assertIsInstance(body["queued"], int)
        self.assertIsInstance(body["seen_at"], int)
        self.assertEqual(body["version"], agent.AGENT_VERSION)
        self.assertIsInstance(body["host"], str)
        self.assertGreater(body["seen_at"], time.time() * 1000 - 600000)


# ---------------------------------------------------------------------------
# 6. 真实 OSS 链路 E2E（保留 2 个 ready fixture deck 供 Lead 网页验收）
# ---------------------------------------------------------------------------
def _head(url):
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.headers.get("Content-Type"), int(resp.headers.get("Content-Length") or 0)
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)[:160], 0


class TestE2EFixtures(unittest.TestCase):
    """创建并保留 2 个 ready deck（供网页端真实播放器验收）。"""

    @classmethod
    def setUpClass(cls):
        ensure_fixtures()
        cls.admin = agent.Cloud(log=log)
        cls.member = TestAccountCloud()
        cls.host = "test-host"
        cls.uploader = oss_upload.OssUploader(log=log)

    def _find_ready_fixture(self, title):
        status, rows = self.admin.get(
            "ppt_decks?select=id,title,status,manifest,slide_count,step_count,aspect"
            "&deleted=eq.false&status=eq.ready&order=created_at.desc&limit=20")
        if status == 200 and isinstance(rows, list):
            for row in rows:
                if row.get("title") != title:
                    continue
                manifest = row.get("manifest") or {}
                if manifest.get("slides"):
                    return row
        return None

    def _create_and_convert(self, fixture_path, title, deck_id, expect_aspect):
        with open(fixture_path, "rb") as fh:
            data = fh.read()
        now = now_ms()
        status, out = self.member.post("ppt_decks", [{
            "id": deck_id, "title": title, "owner_sid": TEST_SID,
            "owner_name": TEST_NAME, "client": "test", "status": "uploading",
            "source_name": os.path.basename(fixture_path), "source_size": len(data),
            "chunk_count": 0, "created_at": now, "updated_at": now, "deleted": False,
        }], prefer="return=representation")
        self.assertIn(status, (200, 201), "建 deck 失败：%s %s" % (status, out))
        total = (len(data) + CHUNK_RAW - 1) // CHUNK_RAW
        rows = []
        for idx in range(total):
            part = data[idx * CHUNK_RAW:(idx + 1) * CHUNK_RAW]
            rows.append({"deck_id": deck_id, "owner_sid": TEST_SID, "idx": idx,
                         "data": base64.b64encode(part).decode(), "ts": now_ms()})
        status, out = self.member.post("ppt_upload_chunks", rows,
                                       prefer="resolution=merge-duplicates,return=minimal")
        self.assertIn(status, (200, 201, 204), "分片上传失败：%s %s" % (status, out))
        status, out = self.member.patch(
            "ppt_decks?id=eq.%s" % deck_id,
            {"status": "queued", "chunk_count": total, "source_size": len(data),
             "updated_at": now_ms()}, prefer="return=representation")
        self.assertIn(status, (200, 201), "提交转换失败：%s %s" % (status, out))

        summary = agent.run_once(self.admin, self.uploader, log, self.host,
                                 deck_id=deck_id, dry_run=False)
        self.assertEqual(summary["action"], "converted", "E2E 转换失败：%s" % summary)
        status, rows = self.admin.get(
            "ppt_decks?select=id,title,status,progress,error,slide_count,step_count,"
            "aspect,cover_url,source_key,manifest&id=eq.%s" % deck_id)
        self.assertEqual(status, 200)
        row = rows[0]
        self.assertEqual(row["status"], "ready")
        self.assertEqual(row["progress"], 100)
        self.assertEqual(row["aspect"], expect_aspect)
        self.assertEqual((row["manifest"]["w"], row["manifest"]["h"]),
                         (1600, 900) if expect_aspect == "16:9" else (1600, 1200))
        log("E2E fixture ready：id=%s title=%r %s %d 页 / %d 步"
            % (deck_id, title, row["aspect"], row["slide_count"], row["step_count"]))
        return row

    def _assert_oss_objects(self, row):
        manifest = row["manifest"]
        base = manifest["base"]
        step = manifest["slides"][0]["steps"][0]["img"]
        for name in (step, manifest["slides"][0]["thumb"]):
            status, ctype, size = _head(base + name)
            self.assertEqual(status, 200, "%s HEAD 失败" % name)
            self.assertEqual(ctype, "image/webp")
            self.assertGreater(size, 0)
        # 原件可下载
        status, ctype, size = _head(manifest["src"])
        self.assertEqual(status, 200, "source HEAD 失败")
        self.assertGreater(size, 0)
        return base

    def test_01_video_fixture_e2e(self):
        existing = self._find_ready_fixture(TITLE_MARKER_VIDEO)
        if existing:
            row = existing
            log("复用已存在的视频 fixture deck：%s" % row["id"])
        else:
            row = self._create_and_convert(FIXTURE, TITLE_MARKER_VIDEO,
                                           make_deck_id("dtestvid"), "16:9")
        manifest = row["manifest"]
        base = self._assert_oss_objects(row)
        # 媒体链路：m0.mp4 HEAD 200 + video/mp4 + hotspot 0..1
        self.assertEqual(len(manifest["media"]), 1, "应与 manifest.media 只有 1 个视频")
        media = manifest["media"][0]
        self.assertEqual(media["k"], "v")
        status, ctype, size = _head(base + media["s"])
        self.assertEqual(status, 200, "mp4 HEAD 失败")
        self.assertEqual(ctype, "video/mp4", "mp4 Content-Type 必须是 video/mp4")
        self.assertGreater(size, 0)
        hotspots = [h for slide in manifest["slides"] for step in slide["steps"]
                    for h in step.get("media") or []]
        self.assertEqual(len(hotspots), 1)
        for key in ("x", "y", "w", "h"):
            self.assertGreaterEqual(hotspots[0][key], 0.0)
            self.assertLessEqual(hotspots[0][key], 1.0)
        self.assertAlmostEqual(hotspots[0]["x"], 0.1667, places=3)
        self.assertEqual(hotspots[0]["s"], media["s"])
        video_path = media["s"]
        log("视频 E2E OK：%s%s %d bytes, hotspot=%r"
            % (base, video_path, size, hotspots[0]))
        # 记录给 Lead（打印出可验收信息）
        print("\n[验收 deck 1/2] id=%s title=%r manifest.base=%s"
              % (row["id"], row["title"], base), flush=True)
        print("[验收 deck 1/2] 视频 URL=%s%s" % (base, media["s"]), flush=True)

    def test_02_4x3_fixture_e2e(self):
        existing = self._find_ready_fixture(TITLE_MARKER_43)
        if existing:
            row = existing
            log("复用已存在的 4:3 fixture deck：%s" % row["id"])
        else:
            row = self._create_and_convert(FIXTURE_43, TITLE_MARKER_43,
                                           make_deck_id("dtest43"), "4:3")
        manifest = row["manifest"]
        base = self._assert_oss_objects(row)
        self.assertEqual((manifest["w"], manifest["h"]), (1600, 1200))
        self.assertEqual(len(manifest["media"]), 0)
        log("4:3 E2E OK：%s 1600x1200" % row["id"])
        print("\n[验收 deck 2/2] id=%s title=%r manifest.base=%s"
              % (row["id"], row["title"], base), flush=True)


if __name__ == "__main__":
    import urllib.parse  # noqa: F401  供 _find_ready_fixture 使用

    unittest.main(verbosity=2)
