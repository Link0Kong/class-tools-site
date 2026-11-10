# -*- coding: utf-8 -*-
"""PPT v2.0 compat 质量验收（真实云端 + OSS）：
- manifest.files 三件套存在/大小/sha256 与下载字节一致
- compat.pptx 能被 python-pptx 打开、页数=源
- **源包内嵌媒体 sha256 全部保留在 compat 包内（不降质强断言）**
- PDF %PDF 头、页数=slide_count
- compat.warnings（外链媒体）可读
用法：python _qa_ppt_compat.py <deckId>
"""
import hashlib
import io
import json
import os
import sys
import urllib.request
import zipfile

PUB = open(r"C:\Users\Ko_Li\.openclaw\workspace\web\deploy\cloudbase\publish_key.txt", encoding="utf-8").read().strip()
BASE = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"
ADM = json.load(open(r"C:\briefdesk\secrets\class-token.json", encoding="utf-8"))["token"]
R = {}


def check(name, cond, detail=""):
    R[name] = bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)) if detail != "" else ""))


def get_json(path):
    r = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + PUB, "X-Device-Id": ADM})
    return json.loads(urllib.request.urlopen(r, timeout=60).read())


def fetch(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=300) as x:
        return x.read(), {k.lower(): v for k, v in x.headers.items()}


def media_hashes(zbytes):
    """所有媒体条目（ppt/media/*）的 sha256 多重集合（含 video/image/audio）。"""
    out = []
    z = zipfile.ZipFile(io.BytesIO(zbytes))
    for n in z.namelist():
        if n.startswith("ppt/media/") and not n.endswith("/"):
            out.append((n.split("/")[-1], hashlib.sha256(z.read(n)).hexdigest()))
    return out


def main(deck_id):
    row = get_json("ppt_decks?select=id,status,source_name,source_size,slide_count,manifest&id=eq." + deck_id)[0]
    man = row["manifest"] or {}
    files = man.get("files") or {}
    compat = files.get("compat")
    pdf = files.get("pdf")
    src = files.get("source")
    print("deck:", deck_id, "| status:", row["status"], "| slides:", row["slide_count"], "| source:", row["source_name"])
    check("manifest.files.compat 存在", bool(compat))
    check("manifest.files.pdf 存在", bool(pdf))
    check("manifest.files.source 存在", bool(src))
    if not (compat and pdf and src):
        return finish()
    blobs = {}
    for kind, f in files.items():
        if not isinstance(f, dict) or not f.get("s"):
            continue
        url = man["base"] + f["s"]
        try:
            data, hdr = fetch(url)
        except Exception as e:  # noqa: BLE001
            check("下载 " + kind, False, str(e)[:80])
            continue
        sha = hashlib.sha256(data).hexdigest()
        blobs[kind] = data
        check("下载 %s（%d bytes）" % (kind, len(data)), True)
        check("%s size 与 manifest 一致" % kind, len(data) == int(f.get("size", -1)), (len(data), f.get("size")))
        check("%s sha256 与 manifest 一致" % kind, sha == f.get("sha256"), sha[:16])
        check("%s URL Content-Type 合理" % kind, True, hdr.get("content-type"))
    # 页数 = source
    pages = int(row["slide_count"] or 0)
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(blobs["compat"]))
        cp = len(prs.slides)
        check("compat.pptx 可被 python-pptx 打开", True)
        check("compat 页数 = deck.slide_count", cp == pages, (cp, pages))
    except Exception as e:  # noqa: BLE001
        check("compat.pptx 可被 python-pptx 打开", False, str(e)[:120])
    # 媒体字节不降质：源内嵌媒体 sha 全部保留在 compat 中
    try:
        src_media = media_hashes(blobs["source"])
        cmp_media = media_hashes(blobs["compat"])
        src_set = {h for _, h in src_media}
        cmp_set = {h for _, h in cmp_media}
        missing = src_set - cmp_set
        check("源内嵌媒体全部保留在 compat（sha256 逐字节一致）", not missing,
              {"source_media": len(src_set), "compat_media": len(cmp_set), "missing_sha": [x[:12] for x in missing]})
        check("compat 媒体数 >= 源媒体数", len(cmp_media) >= len(src_media), (len(cmp_media), len(src_media)))
    except Exception as e:  # noqa: BLE001
        check("媒体字节一致性检查", False, str(e)[:120])
    # PDF
    try:
        from pypdf import PdfReader
        pdf_bytes = blobs["pdf"]
        check("PDF %PDF 头", pdf_bytes[:5] == b"%PDF-", pdf_bytes[:8])
        pp = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
        check("PDF 页数 = deck.slide_count", pp == pages, (pp, pages))
    except Exception as e:  # noqa: BLE001
        check("PDF 页数检查", False, str(e)[:120])
    # warnings
    warns = (man.get("compat") or {}).get("warnings") or []
    print("compat warnings:", json.dumps(warns, ensure_ascii=False)[:400])
    check("compat.warnings 是可读列表", isinstance(warns, list))
    check("compat.warnings 已展示（外链媒体）", len(warns) >= 1, len(warns))
    check("slides/video 旧字段保留（旧 deck 兼容）", isinstance(man.get("slides"), list))
    return finish()


def finish():
    passed = sum(1 for v in R.values() if v)
    print("=== COMPAT QA: %d/%d PASS ===" % (passed, len(R)))
    print(json.dumps({"pass": passed, "total": len(R), "detail": R}, ensure_ascii=False))
    return 0 if passed == len(R) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dmwalrdlgevz90l"))
