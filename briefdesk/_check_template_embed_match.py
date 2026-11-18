# -*- coding: utf-8 -*-
"""重建后校验：新 demo 提取出的通知模板 是否与「本地已 embed/已上线 index」一致。

做法：把 index.html / 新 demo / build_notice_embed.py 复制到临时目录跑一遍
build_notice_embed.main()（不触碰真实 index.html），分别从「临时生成 index」与
「真实 index」解码 NOTICE_TPL_B64 并比较 sha256。
若一致 → 纯数据变化，无需重新 embed/部署；不一致 → 打印差异信息，交 Lead 重新 embed。

跑法：C:\\briefdesk\\venv\\Scripts\\python.exe -X utf8 C:\\Users\\Ko_Li\\.openclaw\\workspace\\briefdesk-plan\\_check_template_embed_match.py
"""
import base64
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WEB = Path(r"C:\Users\Ko_Li\.openclaw\workspace\web")
INDEX = WEB / "tools" / "index.html"
DEMO = WEB / "tools" / "notice-board-live-demo.html"
EMBED = WEB / "tools" / "build_notice_embed.py"
TMPROOT = Path(r"C:\briefdesk\data\_v2_template_check")


def extract_b64(text):
    m = re.search(r'var NOTICE_TPL_B64="(.*?)";', text, re.S)
    if not m:
        raise SystemExit("NOTICE_TPL_B64 not found")
    return base64.b64decode(m.group(1)), len(m.group(1))


def main():
    TMPROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="embmatch_", dir=str(TMPROOT)) as d:
        tmp = Path(d)
        shutil.copy2(INDEX, tmp / "index.html")
        shutil.copy2(DEMO, tmp / "notice-board-live-demo.html")
        shutil.copy2(EMBED, tmp / "build_notice_embed.py")
        r = subprocess.run([sys.executable, "-X", "utf8", str(tmp / "build_notice_embed.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print("EMBED-SIM FAILED:", (r.stdout or "")[-400:], (r.stderr or "")[-400:])
            return 2
        new_b64, new_b64_len = extract_b64((tmp / "index.html").read_text(encoding="utf-8"))
    live_b64, live_b64_len = extract_b64(INDEX.read_text(encoding="utf-8"))
    new_sha = hashlib.sha256(new_b64).hexdigest()
    live_sha = hashlib.sha256(live_b64).hexdigest()
    demo_sha = hashlib.sha256(DEMO.read_bytes()).hexdigest()
    print("demo:", DEMO.stat().st_size, "B | sha256", demo_sha)
    print("template(new demo -> embed):", len(new_b64), "B | b64", new_b64_len, "| sha256", new_sha[:16])
    print("template(live index):       ", len(live_b64), "B | b64", live_b64_len, "| sha256", live_sha[:16])
    same = new_b64 == live_b64
    print("TEMPLATE MATCH:", "YES (纯数据变化，无需重 embed)" if same else "NO (模板结构变化，需重新 embed/部署)")
    if not same:
        # 找出首个差异位置，便于定位
        n = min(len(new_b64), len(live_b64))
        i = next((k for k in range(n) if new_b64[k] != live_b64[k]), n)
        print("first diff at byte", i)
        print("new:", new_b64[max(0, i - 80):i + 160])
        print("old:", live_b64[max(0, i - 80):i + 160])
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
