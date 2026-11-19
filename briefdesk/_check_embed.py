# -*- coding: utf-8 -*-
"""v2.0.0：模拟 web-dev 的 build_notice_embed.py 提取流程，验证新模板仍可被内嵌。

只读 notice-board-live-demo.html，产物写临时目录；不碰 web/tools/index.html。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
DEMO = Path(r"G:\ClassTools\web\tools\notice-board-live-demo.html")
BOARD = Path(r"G:\ClassTools\briefdesk\data\board-data.json")
OUT = Path(r"G:\ClassTools\briefdesk\data\_v2_template_check")


def main():
    s = DEMO.read_text(encoding="utf-8")
    css = re.search(r"<style[^>]*>(.*?)</style>", s, re.S).group(1)
    body = re.search(r"<body[^>]*>(.*?)</body>", s, re.S).group(1)
    body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<header[^>]*class=\"brand\"[^>]*>.*?</header>", "", body, flags=re.S)
    js = re.search(r"<script[^>]*>(.*?)</script>", s, re.S).group(1)
    idx = js.find("var CATCLS=")
    if idx < 0:
        print("FAIL: build_notice_embed.py marker `var CATCLS=` not found")
        return 1
    code = js[idx:]
    if "var GROUPS=" in code or "__DATA__" in code:
        print("FAIL: extracted code still contains data placeholder")
        return 1
    groups = json.loads(BOARD.read_text(encoding="utf-8"))["groups"]
    data = json.dumps(groups, ensure_ascii=False).replace("</", "<\\/")
    height_js = """
function __noticeHeight(){
  try{var h=Math.max(document.documentElement.scrollHeight,document.body.scrollHeight);
      parent.postMessage({type:'class-notice-height',height:h},'*');}catch(e){}
}
window.addEventListener('load',__noticeHeight);
setTimeout(__noticeHeight,200);
"""
    html = ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>班级通知</title><style>" + css + "</style></head><body>" + body +
            "<script>var GROUPS=" + data + ";var FORMS={};var HOMEWORK=[];var SCHEDULE=[];"
            + code + "\n" + height_js + "</script></body></html>")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "embed_sim.html"
    tmp.write_text(html, encoding="utf-8")

    probe = """
<script>
(function(){
  var out={cards:(document.querySelectorAll('#list .gcard')||[]).length,
           groups:(typeof GROUPS!=='undefined')?GROUPS.length:-1,
           hasHeight:typeof window.__noticeHeight==='function',
           hasAdmin:typeof window.__zqSetAdmin==='function',
           recur:(document.querySelectorAll('.recurline')||[]).length,
           missing:(document.querySelectorAll('.linkrow.missing')||[]).length};
  var pre=document.createElement('pre');pre.id='__testout';pre.textContent=JSON.stringify(out);
  document.body.appendChild(pre);
})();
</script>
"""
    tmp.write_text(html.replace("</body>", probe + "</body>", 1), encoding="utf-8")
    dom_file = OUT / "embed_dom.html"
    cmd = [str(EDGE), "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           "--virtual-time-budget=4000", "--dump-dom",
           "--user-data-dir=" + str(OUT / "edge-embed"), tmp.as_uri()]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    dom = proc.stdout.decode("utf-8", "replace")
    dom_file.write_text(dom, encoding="utf-8")
    m = re.search(r'<pre id="__testout">(.*?)</pre>', dom, re.S)
    if not m:
        print("FAIL: no probe output", proc.stderr.decode("utf-8", "replace")[-500:])
        return 1
    raw = m.group(1).replace("&quot;", '"')
    out = json.loads(raw)
    print("embed sim:", json.dumps(out))
    # 列表默认只渲染「未过期」的通知（过期进折叠区），所以卡片数 <= groups 数
    ok = (out["cards"] > 0 and out["cards"] <= out["groups"] and out["groups"] == len(groups)
          and out["hasHeight"] and out["hasAdmin"] and out["recur"] > 0 and out["missing"] > 0)
    print("== EMBED SIM", "PASS ==" if ok else "FAIL ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
