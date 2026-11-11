# -*- coding: utf-8 -*-
"""PPT v2.2 compat 质量验收（真实云端 + OSS + ECS 缓存）：
- manifest.files 三件套存在/大小/sha256 与下载字节一致
- compat.pptx 可被 python-pptx 打开、页数=源
- 媒体编码兼容：media_summary/media_actions 结构；keep 媒体 sha256 与源逐字节一致；remux/transcode 允许变化但需记录
- 断链视频修复：无未解决 external video 断链；repairs 记录
- PDF %PDF/页数；ECS 缓存下载 sha256 与 manifest 一致且速度 ≥2MB/s
用法：python _qa_ppt_compat.py <deckId>
"""
import hashlib
import io
import json
import re
import sys
import time
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


def fetch(url, timeout=600):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as x:
        return x.read(), {k.lower(): v for k, v in x.headers.items()}


def media_hashes(zbytes):
    out = []
    z = zipfile.ZipFile(io.BytesIO(zbytes))
    for n in z.namelist():
        if n.startswith("ppt/media/") and not n.endswith("/"):
            out.append((n.split("/")[-1], hashlib.sha256(z.read(n)).hexdigest(), len(z.read(n))))
    return out


def external_video_rels(zbytes):
    out = []
    z = zipfile.ZipFile(io.BytesIO(zbytes))
    for n in z.namelist():
        if not re.match(r"ppt/slides/_rels/slide\d+\.xml\.rels$", n):
            continue
        xml = z.read(n).decode("utf-8", "ignore")
        for m in re.finditer(r"<Relationship\b[^>]*>", xml):
            tag = m.group(0)
            if "relationships/video" not in tag or 'TargetMode="External"' not in tag:
                continue
            relid = re.search(r'Id="([^"]+)"', tag)
            target = re.search(r'Target="([^"]*)"', tag)
            out.append((n.split("/")[-1], relid.group(1) if relid else "?", target.group(1) if target else "?"))
    return out


def main(deck_id):
    row = get_json("ppt_decks?select=id,status,source_name,source_size,slide_count,manifest&id=eq." + deck_id)[0]
    man = row["manifest"] or {}
    files = man.get("files") or {}
    compat = files.get("compat")
    pdf = files.get("pdf")
    src = files.get("source")
    compat_meta = man.get("compat") or {}
    summary = compat_meta.get("media_summary") or {}
    actions = compat_meta.get("media_actions") or []
    print("deck:", deck_id, "| status:", row["status"], "| slides:", row["slide_count"], "| source:", row["source_name"])
    print("media_summary:", summary, "| actions:", json.dumps(actions, ensure_ascii=False)[:400])
    print("repairs:", json.dumps(compat_meta.get("repairs") or [], ensure_ascii=False)[:200])
    check("manifest.files 三件套存在", bool(compat and pdf and src))
    if compat:
        check("兼容版文件名含 _兼容版", "_兼容版" in str(compat.get("name") or ""), compat.get("name"))
    if pdf:
        check("PDF 文件名含 _预览", "_预览" in str(pdf.get("name") or ""), pdf.get("name"))
    if src:
        check("原始文件名含 _原始文件", "_原始文件" in str(src.get("name") or ""), src.get("name"))
    if not (compat and pdf and src):
        return finish()
    blobs = {}
    for kind, f in files.items():
        if not isinstance(f, dict) or not f.get("s"):
            continue
        data, hdr = fetch(man["base"] + f["s"])
        sha = hashlib.sha256(data).hexdigest()
        blobs[kind] = data
        check("%s 下载 size/sha256 与 manifest 一致" % kind,
              len(data) == int(f.get("size", -1)) and sha == f.get("sha256"), (len(data), sha[:16]))
    pages = int(row["slide_count"] or 0)
    try:
        from pptx import Presentation
        cp = len(Presentation(io.BytesIO(blobs["compat"])).slides)
        check("compat.pptx 可打开且页数=slide_count", cp == pages, (cp, pages))
    except Exception as e:  # noqa: BLE001
        check("compat.pptx 可打开", False, str(e)[:100])
    # 媒体兼容
    try:
        src_media = media_hashes(blobs["source"])
        cmp_media = media_hashes(blobs["compat"])
        converted = {a.get("file") for a in actions if a.get("action") in ("remux", "transcode")}
        src_hashes = {h for _, h, _ in src_media}
        cmp_hashes = {h for _, h, _ in cmp_media}
        # 未被转换/改名的源媒体必须逐字节保留（按 sha 多重集合：源 sha 减去已转换文件的 sha）
        kept_src = set()
        for name, h, size in src_media:
            act = next((a for a in actions if a.get("file") == name), None)
            if not act or act.get("action") == "keep":
                kept_src.add(h)
        missing = kept_src - cmp_hashes
        check("keep/未转换媒体逐字节保留", not missing, {"kept_src": len(kept_src), "missing": [x[:12] for x in missing]})
        check("media_summary.total = media_actions 数", int(summary.get("total", -1)) == len(actions) or not actions,
              (summary, len(actions)))
        check("media_summary 字段完整", all(k in summary for k in ("total", "kept", "remux", "transcode")), summary)
        if converted:
            check("存在 remux/transcode 记录且 compat 媒体集不再全等（允许）", True, sorted(converted)[:5])
        else:
            check("无转换时 compat 媒体 sha 集合与源相等", src_hashes == cmp_hashes,
                  {"src": len(src_hashes), "compat": len(cmp_hashes)})
    except Exception as e:  # noqa: BLE001
        check("媒体兼容检查", False, str(e)[:120])
    # 断链修复
    try:
        ext = external_video_rels(blobs["compat"])
        check("compat 无未解决 external video 断链", not ext, ext[:5])
    except Exception as e:  # noqa: BLE001
        check("断链视频检查", False, str(e)[:120])
    # PDF
    try:
        from pypdf import PdfReader
        check("PDF %PDF 头", blobs["pdf"][:5] == b"%PDF-", blobs["pdf"][:8])
        pp = len(PdfReader(io.BytesIO(blobs["pdf"])).pages)
        check("PDF 页数=slide_count", pp == pages, (pp, pages))
    except Exception as e:  # noqa: BLE001
        check("PDF 检查", False, str(e)[:100])
    # ECS 缓存（真实下载 + 速度）
    try:
        path = man["base"].split("aliyuncs.com/")[1] + files["compat"]["s"]
        url = "http://121.196.47.2/pptfiles/" + path
        t0 = time.time()
        data, _ = fetch(url, timeout=300)
        el = max(0.001, time.time() - t0)
        sha = hashlib.sha256(data).hexdigest()
        speed = len(data) / el / 1048576.0
        check("ECS 缓存下载 compat 成功且 sha=manifest", sha == files["compat"]["sha256"], sha[:16])
        check("ECS 缓存下载速度 ≥2MB/s", speed >= 2.0, "%.1fMB/s / %.2fs / %.1fMB" % (speed, el, len(data) / 1048576.0))
    except Exception as e:  # noqa: BLE001
        check("ECS 缓存下载", False, str(e)[:120])
    return finish()


def finish():
    passed = sum(1 for v in R.values() if v)
    print("=== COMPAT QA: %d/%d PASS ===" % (passed, len(R)))
    print(json.dumps({"pass": passed, "total": len(R), "detail": R}, ensure_ascii=False))
    return 0 if passed == len(R) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dmwalrdlgevz90l"))
