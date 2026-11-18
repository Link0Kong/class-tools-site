# -*- coding: utf-8 -*-
"""v2.0.0 压缩包解压识别自测（需求 B）。

覆盖：真实 5.18MB 样本识别 + 安全边界（zip-slip/绝对路径/超大/坏包/嵌套）+ hash 缓存 +
builder 注入 + 模板渲染（包内文件清单/摘要/小文件下载）。

跑法：C:\\briefdesk\\venv\\Scripts\\python.exe -X utf8 briefdesk-plan\\_check_archive.py
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, r"C:\briefdesk\scripts")
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
REAL_ZIP = Path(r"C:\briefdesk\data\qq-files\第十一届全国大学生预防艾滋病知识竞赛暨校园健康行动通知附件.zip")
REAL_SHA = "8e14c71d4092"
FAILED = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else (" | " + str(detail)[:300])))
    if not cond:
        FAILED.append(name)


def test_safety(tmp):
    import archive_scan
    # 恶意构造：zip-slip / 绝对路径 / 正常文件 / 嵌套
    p = tmp / "evil.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("../escape.txt", "escaped")
        z.writestr("/abs/absolute.txt", "absolute")
        z.writestr("C:/win/win.txt", "win")
        z.writestr("ok/安全说明.txt", "这是一份安全说明文本，内容足够长以便识别。")
        inner = tmp / "inner.zip"
        with zipfile.ZipFile(inner, "w") as iz:
            iz.writestr("nested/嵌套通知.txt", "嵌套压缩包内的通知文本。")
        z.write(inner, "bundle/nested.zip")
    rec = archive_scan.analyze_archive(p)
    names = [f.get("name") for f in rec.get("files") or []]
    print("  evil files:", names, "| status:", rec.get("status"))
    check("zip-slip: ../ 条目被拒绝", not any("escape" in (n or "") for n in names), names)
    check("zip-slip: 绝对路径被拒绝", not any((n or "").startswith("/") or "absolute" in (n or "") for n in names), names)
    check("zip-slip: 盘符路径被拒绝", not any("win/win" in (n or "") for n in names), names)
    check("正常/嵌套文件仍可识别", any("安全说明" in (n or "") for n in names)
          and any("嵌套通知" in (n or "") for n in names), names)
    check("恶意包不会写出到 cwd 之外",
          not (tmp.parent / "escape.txt").exists() and not Path("C:/abs/absolute.txt").exists())
    # 坏包
    bad = tmp / "broken.zip"
    bad.write_bytes(b"PK\x03\x04this-is-not-a-zip")
    rec2 = archive_scan.analyze_archive(bad)
    check("坏压缩包 → error 状态（原包保留）", rec2.get("status") == "error" and rec2.get("error"),
          rec2.get("status"))
    check("safe_member_path 纯函数", archive_scan.safe_member_path("a/b.txt") == "a/b.txt"
          and archive_scan.safe_member_path("../x") is None
          and archive_scan.safe_member_path("/x") is None
          and archive_scan.safe_member_path("C:/x") is None)
    # 缓存：同 hash 第二次不重识别
    import importlib
    archive_scan = importlib.reload(archive_scan)
    archive_scan.OUT = tmp / "archive-contents.json"
    archive_scan.FILES_DIR = tmp / "archive-files"
    archive_scan.QQ_FILES = tmp / "qq-files"
    archive_scan.WECHAT_MEDIA = tmp / "wechat-media"
    (tmp / "qq-files").mkdir()
    shutil.copyfile(p, tmp / "qq-files" / "evil.zip")
    r1 = archive_scan.run()
    r2 = archive_scan.run()
    check("hash 缓存：第二次不重复识别", r1["analyzed"] == 1 and r2["analyzed"] == 0,
          (r1, r2))


def test_real_sample():
    import archive_scan
    real = json.loads(Path(r"C:\briefdesk\data\archive-contents.json").read_text(encoding="utf-8"))
    rec = next((v for v in (real.get("items") or {}).values()
                if str(v.get("file") or "").startswith("第十一届")), None)
    check("真实样本已有识别记录", rec is not None)
    if not rec:
        return
    check("真实样本 5 个内部文件", rec.get("entryCount") == 5, rec.get("entryCount"))
    check("真实样本状态 ok", rec.get("status") == "ok", rec.get("status"))
    names = [f.get("name") for f in rec.get("files") or []]
    check("识别出 docx/xlsx/pptx", any(n.endswith(".xlsx") for n in names)
          and any(n.endswith(".docx") for n in names) and any(n.endswith(".pptx") for n in names), names)
    check("AI 摘要非空", bool(rec.get("aiSummary")), rec.get("aiSummary"))
    check("AI 要点 1–6 条且 ≤12 字",
          1 <= len(rec.get("aiPoints") or []) <= 6
          and all(len(p) <= 12 for p in (rec.get("aiPoints") or [])), rec.get("aiPoints"))
    check("内部小文件已持久化可下载", sum(1 for f in rec.get("files") or [] if f.get("saved")) >= 3,
          [f.get("saved") for f in rec.get("files") or []])
    check("压缩包内 xlsx 文本被识别", next((f.get("textLen") for f in rec.get("files") or []
                                             if str(f.get("name")).endswith(".xlsx")), 0) > 500,
          [f.get("textLen") for f in rec.get("files") or []])


def test_builder_and_template(tmp):
    import build_notice_board as builder
    # 只读真实数据构建到临时目录：压缩包附件卡应带 archive 结构
    builder.OUT = tmp / "demo.html"
    builder.BOARD_DATA = tmp / "board-data.json"
    builder.main()
    board = json.loads((tmp / "board-data.json").read_text(encoding="utf-8"))
    target = None
    for g in board.get("groups") or []:
        for it in g.get("items") or []:
            if it.get("kind") == "file" and "预防艾滋病" in str(it.get("name") or ""):
                target = (g, it)
                break
        if target:
            break
    check("真实压缩包附件已挂到通知卡", target is not None)
    if target:
        g, it = target
        arch = it.get("archive") or {}
        check("附件条目带 archive 结构", arch.get("count") == 5, arch.get("count"))
        check("archive 有摘要", bool(arch.get("summary")), arch.get("summary"))
        check("archive 小文件下载链接 ≥3",
              sum(1 for f in arch.get("files") or [] if f.get("url")) >= 3,
              sum(1 for f in arch.get("files") or [] if f.get("url")))
        print("  target group:", g.get("id"), "| archive summary:", arch.get("summary"))
    # headless 渲染断言
    probe = """<script>(function(){
      var t=document.getElementById('card-g_qqfile_8b01d25799')||document.querySelector('.archivecard');
      var out={cards:(document.querySelectorAll('#list .gcard')||[]).length,
               archive:(document.querySelectorAll('.archivecard')||[]).length};
      if(t){
        var card=t.closest?t.closest('.gcard'):t;
        out.card=card?card.id:'';
        var ac=card?card.querySelector('.archivecard'):null;
        out.arcOpen=!!ac;
        out.rows=ac?ac.querySelectorAll('.arc-row').length:0;
        out.downloads=ac?ac.querySelectorAll('.arc-row a[download]').length:0;
        out.sum=ac?((ac.querySelector('.arch-sum')||{}).textContent||''):'';
        out.text=card?card.textContent.slice(0,300):'';
      }
      var pre=document.createElement('pre');pre.id='__probe';pre.textContent=JSON.stringify(out);
      document.body.appendChild(pre);})();</script>"""
    probe_file = tmp / "probe.html"
    probe_file.write_text((tmp / "demo.html").read_text(encoding="utf-8").replace(
        "</body>", probe + "</body>", 1), encoding="utf-8")
    cmd = [str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           "--virtual-time-budget=5000", "--dump-dom",
           "--user-data-dir=" + str(tmp / "edge"), probe_file.as_uri()]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    dom = proc.stdout.decode("utf-8", "replace")
    m = re.search(r'<pre id="__probe">(.*?)</pre>', dom, re.S)
    out = {}
    if m:
        raw = m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        out = json.loads(raw)
    print("  template probe:", json.dumps({k: out.get(k) for k in
          ("archive", "arcOpen", "rows", "downloads", "sum")}, ensure_ascii=False)[:400])
    check("模板: 渲染出压缩包卡片", out.get("arcOpen") is True)
    check("模板: 包内 5 个文件行", out.get("rows") == 5, out.get("rows"))
    check("模板: 小文件下载链接 ≥3", out.get("downloads", 0) >= 3, out.get("downloads"))
    check("模板: 显示解压摘要", bool(out.get("sum")), out.get("sum"))
    # 截图（聚焦压缩包卡）
    focus_js = """<script>(function(){var ac=document.querySelector('.archivecard');if(!ac)return;
      document.querySelectorAll('#list .gcard').forEach(function(c){if(!c.contains(ac))c.style.display='none';});
      var b=document.querySelector('.brief');if(b)b.style.display='none';
      var ex=document.getElementById('expiredWrap');if(ex)ex.style.display='none';})();</script>"""
    focus_file = tmp / "focus.html"
    focus_file.write_text((tmp / "demo.html").read_text(encoding="utf-8").replace(
        "</body>", focus_js + "</body>", 1), encoding="utf-8")
    shot = tmp / "archive.png"
    subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run",
                    "--no-default-browser-check", "--hide-scrollbars", "--virtual-time-budget=5000",
                    "--user-data-dir=" + str(tmp / "edge2"), "--window-size=1280,900",
                    "--screenshot=" + str(shot), focus_file.as_uri()], capture_output=True, timeout=120)
    if shot.exists():
        keep = Path(r"C:\briefdesk\data\_v2_template_check")
        keep.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shot, keep / "archive_card.png")
        print("  screenshot ->", keep / "archive_card.png")


def main():
    check("真实样本存在", REAL_ZIP.exists(), REAL_ZIP)
    with tempfile.TemporaryDirectory(prefix="v2arc_") as d:
        tmp = Path(d)
        test_safety(tmp)
        test_real_sample()
        test_builder_and_template(tmp)
    print("\n== %d FAILED ==" % len(FAILED) if FAILED else "\n== ALL ARCHIVE TESTS PASS ==")
    for f in FAILED:
        print(" -", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
