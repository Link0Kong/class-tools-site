# -*- coding: utf-8 -*-
"""attachments/common.py + client.externalize_groups 的单元测试（无网络）。

运行：python attachments\\tests\\test_attachments.py
"""
import base64
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import client  # noqa: E402
import common  # noqa: E402

passed = 0
failed = 0


def ok(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print("  PASS", name)
    else:
        failed += 1
        print("  FAIL", name)


def data_uri(mime, blob):
    return "data:%s;base64,%s" % (mime, base64.b64encode(blob).decode("ascii"))


class FakeUploader:
    def __init__(self):
        self.stats = {"files": 0, "bytes": 0, "uploaded": 0, "dedup": 0, "failed": 0, "replaced": 0}
        self.key = common.derive_key("test-token")
        self.exp = int(time.time()) + 86400
        self.base = "https://example.test"
        self.fail_all = False
        self.seen = []

    def url_for_data_uri(self, uri, name="附件"):
        parsed = client.decode_data_uri(uri)
        if not parsed:
            return None
        mime, data = parsed
        att_id = common.content_id(data)
        self.seen.append(att_id)
        self.stats["files"] += 1
        self.stats["bytes"] += len(data)
        if self.fail_all:
            self.stats["failed"] += 1
            return None
        self.stats["replaced"] += 1
        return common.signed_url(self.base, att_id, self.exp, self.key)


def main():
    key = common.derive_key("hello-token")
    att = common.content_id(b"abc")
    ok(len(att) == 32 and att == common.content_id(b"abc"), "content_id 稳定且 32 hex")
    sig = common.sign(att, 1000, key)
    ok(common.verify(att, 1000, sig, key, now=900), "签名验证通过")
    ok(not common.verify(att, 1000, sig, key, now=2000), "过期后拒绝")
    ok(not common.verify(att, 1000, sig + "0", key, now=900), "篡改签名拒绝")
    ok(not common.verify(att, 1000, sig, common.derive_key("other"), now=900), "错误 key 拒绝")
    url = common.signed_url("https://x.test/", att, 1000, key)
    ok(url == "https://x.test/att/%s?exp=1000&sig=%s" % (att, sig), "URL 形态正确")
    ok(common.parse_att_id("/att/" + att) == att, "parse_att_id 正常")
    ok(common.parse_att_id("/att/xyz") is None, "parse_att_id 拒绝非 hex")
    ok(common.parse_att_id("/att/" + att + "/x") is None, "parse_att_id 拒绝多级路径")

    body = b"\x00\x01fake-pdf" * 10
    groups = [{
        "id": "g1",
        "items": [
            {"kind": "img", "src": data_uri("image/jpeg", body), "caption": "图1"},
            {"kind": "file", "name": "a.pdf", "url": data_uri("application/pdf", body)},
            {"kind": "file", "name": "b.docx", "url": "https://already.example/b.docx"},
            {"kind": "file", "name": "c.zip", "url": "", "archive": {"files": [
                {"name": "in.xlsx", "url": data_uri("application/vnd.ms-excel", b"xls-bytes")},
                {"name": "out.txt", "url": "https://already.example/out.txt"}]}},
            {"kind": "link", "url": "https://already.example/link"},
            {"kind": "file", "name": "pending.pdf", "url": ""},
        ],
    }]
    up = FakeUploader()
    stats = client.externalize_groups(groups, up)
    items = groups[0]["items"]
    ok(items[0]["src"].startswith("https://example.test/att/"), "img.src 已替换为 URL")
    ok(items[1]["url"].startswith("https://example.test/att/"), "file.url 已替换")
    ok(items[2]["url"] == "https://already.example/b.docx", "http URL 不变")
    ok(items[3]["archive"]["files"][0]["url"].startswith("https://example.test/att/"), "archive 内 URL 替换")
    ok(items[3]["archive"]["files"][1]["url"] == "https://already.example/out.txt", "archive 外链不变")
    ok(items[4]["url"] == "https://already.example/link", "link.url 不变")
    ok(items[5]["url"] == "", "空 url 维持待获取")
    ok(stats["replaced"] == 3 and stats["files"] == 3, "统计 replaced=3 files=3（3 个内嵌附件）")
    # 同一内容去重：img 与 file 用同一 body，但 FakeUploader 不实现 dedup；真实 Uploader 有 cache
    # 幂等：再跑一次不应再替换
    before = json.dumps(groups, ensure_ascii=False)
    client.externalize_groups(groups, up)
    ok(json.dumps(groups, ensure_ascii=False) == before, "二次执行幂等（URL 不再变）")

    fail_groups = [{"id": "g2", "items": [{"kind": "img", "src": data_uri("image/png", b"zz")}]}]
    up2 = FakeUploader()
    up2.fail_all = True
    client.externalize_groups(fail_groups, up2)
    ok(fail_groups[0]["items"][0]["src"].startswith("data:"), "上传失败保留 data URI（fail-open）")

    # decode/guess
    ok(client.decode_data_uri("data:text/plain;base64,aGk=") == ("text/plain", b"hi"), "decode_data_uri")
    ok(client.decode_data_uri("https://x/y") is None, "decode_data_uri 拒绝非 data")
    ok(client.guess_mime("a.PDF") == "application/pdf", "guess_mime 扩展名")
    ok(client.guess_mime("a.bin", "application/pdf") == "application/pdf", "guess_mime 优先 mime")

    print("\n结果：%d PASS / %d FAIL" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
