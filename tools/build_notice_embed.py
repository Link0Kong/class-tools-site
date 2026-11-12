# -*- coding: utf-8 -*-
"""Embed the generated class-notice board into tools/index.html as an isolated iframe template."""
import base64
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"
NOTICE = HERE / "notice-board-live-demo.html"

TOOLS_VARS = """
--bg:#F4F0E6;--card:#FFFCF6;--line:#E7DED0;--ink:#303A35;--ink2:#5C6860;--ink3:#8B948B;
--cy:#5E8F87;--bl:#7D9EBB;--sd:#C6A475;--danger:#B87870;--mint:#EAF2EC;--mint2:#F3F7F1;
--tint-blue:#EDF2F7;--tint-sand:#FAF3E6;--tint-rose:#F7EDEB;--tint-violet:#F1EEF7;--r:16px;
"""

OVERRIDE = """
html,body{background:#F4F0E6!important;color:#303A35!important}
body{padding:0!important;background-image:none!important}
.brand{display:none!important}
.wrap{max-width:none!important;padding:0!important}
.card,.brief,.aibrief,.gcard,.seg-fact,.linkrow,.formrow,.imgrow,.expired-wrap,.lt-wrap,.bstat{background:#FFFFFF!important;border-color:#E0D2BC!important;box-shadow:0 1px 2px rgba(72,64,44,.07),0 12px 26px -14px rgba(72,64,44,.34)!important}
.brief{background:linear-gradient(180deg,#FFFFFF 0%,#FBF7ED 100%)!important}
.bstat{background:#FBF6EC!important;border-color:#E4D6BF!important;box-shadow:0 1px 2px rgba(72,64,44,.05)!important}
.aibrief{background:#F6F9F2!important}
.seg-fact,.linkrow,.formrow,.imgrow{background:#FBF6EC!important;box-shadow:none!important}
.srcchip{background:#FFFFFF!important;border-color:#E0D2BC!important}
.chipf{background:#FFFFFF!important;border-color:#E0D2BC!important}
.gcard::before{background:#5E8F87!important}
.chipf.on{background:#5E8F87!important;border-color:#5E8F87!important}
.aipoints li{background:#EEF6F3!important;border-color:#D9E8E2!important;color:#46776F!important}
"""


def main():
    s = NOTICE.read_text(encoding="utf-8")
    css = re.search(r"<style[^>]*>(.*?)</style>", s, re.S).group(1)
    body = re.search(r"<body[^>]*>(.*?)</body>", s, re.S).group(1)
    body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<header[^>]*class=\"brand\"[^>]*>.*?</header>", "", body, flags=re.S)
    body = body.replace('<div class="right"></div>', "")

    js = re.search(r"<script[^>]*>(.*?)</script>", s, re.S).group(1)
    idx = js.find("var CATCLS=")
    if idx < 0:
        raise SystemExit("notice page code marker not found")
    code = js[idx:]

    css = re.sub(r":root\{[^}]*\}", ":root{" + TOOLS_VARS + "}", css, count=1)
    css += OVERRIDE

    # 模板自带的 __noticeHeight 用 documentElement.scrollHeight 测量并每 1.5s 上报。
    # 父页已改回「固定视口 iframe + iframe 内部原生滚动」，不再消费高度上报；
    # 这里去掉模板内的测量块（保留 setFoldCard 里对 window.__noticeHeight 的调用），
    # 由下方注入的空实现承接，避免无意义的定时器与 postMessage。
    i = code.find("function __noticeHeight()")
    if i >= 0:
        j = code.find("setInterval(__noticeHeight,1500);", i)
        if j >= 0:
            code = code[:i] + code[j + len("setInterval(__noticeHeight,1500);"):]

    # 需求2/4：固定视口 iframe 下，通知页滚动位置改由 iframe 内部自存自恢（sessionStorage，
    # 与父页同源共享；父页只恢复 tab）。加载后多次重试等待内容撑开再恢复；滚动停止 260ms 落盘。
    height_js = """
function __noticeHeight(){ /* 父页固定视口 iframe + iframe 内部原生滚动：忽略高度上报 */ }
(function(){
  var KEY="zq_nt_scroll_v1";
  function readY(){try{var v=parseInt(sessionStorage.getItem(KEY)||"0",10);return (isFinite(v)&&v>0)?v:0;}catch(e){return 0;}}
  function writeY(){try{sessionStorage.setItem(KEY,String(Math.max(0,Math.round(window.pageYOffset||window.scrollY||document.documentElement.scrollTop||0))));}catch(e){}}
  var t=0;
  window.addEventListener("scroll",function(){if(t)return;t=setTimeout(function(){t=0;writeY();},260);},{passive:true});
  window.addEventListener("pagehide",writeY);
  window.addEventListener("beforeunload",writeY);
  document.addEventListener("visibilitychange",function(){if(document.hidden)writeY();});
  var tries=0;
  function restoreOnce(){
    var y=readY();
    if(!(y>0))return true;
    var max=Math.max(document.documentElement.scrollHeight,document.body.scrollHeight)-window.innerHeight;
    if(max<y-2)return false;
    try{window.scrollTo(0,y);}catch(e){}
    return true;
  }
  function tick(){
    if(restoreOnce())return;
    if(++tries<24)setTimeout(tick,150);
  }
  window.addEventListener("load",function(){setTimeout(tick,0);});
  setTimeout(tick,120);
})();
"""
    html = ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>班级通知</title>"
            "<style>" + css + "</style></head><body>"
            + body + "<script>var GROUPS=__DATA__;var FORMS={};var HOMEWORK=[];var SCHEDULE=[];"
            + code + "\n" + height_js + "</script></body></html>")
    b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")

    idxhtml = INDEX.read_text(encoding="utf-8")
    if "var NOTICE_TPL_B64=" not in idxhtml:
        raise SystemExit("NOTICE_TPL_B64 marker missing")
    idxhtml = re.sub(r'var NOTICE_TPL_B64=".*?";',
                     'var NOTICE_TPL_B64="' + b64 + '";', idxhtml, count=1, flags=re.S)
    INDEX.write_text(idxhtml, encoding="utf-8")
    print("embedded notice template:", len(html), "bytes ->", len(b64), "b64")


if __name__ == "__main__":
    main()
