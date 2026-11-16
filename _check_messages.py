# -*- coding: utf-8 -*-
"""v2.0.0：父页 ↔ iframe 消息契约自测（plan §3.1）。

在临时目录里生成一个「父页」：iframe 载入通知模板，父页监听 postMessage，
模拟管理员点击「编辑→保存 / 删除 / 恢复」，断言收到
class-notice-edit / class-notice-hide / class-notice-restore；
并验证父页可直接调用 __zqSetAdmin / __zqSetHidden / __zqApplyOverride。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
DEMO = Path(r"C:\Users\Ko_Li\.openclaw\workspace\web\tools\notice-board-live-demo.html")
OUT = Path(r"C:\briefdesk\data\_v2_template_check")

PARENT = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>html,body{margin:0}iframe{width:1100px;height:800px;border:0}</style></head>
<body><iframe id="f" src="notice.html"></iframe>
<script>
var got=[];
window.addEventListener('message',function(e){
  if(e.data&&typeof e.data.type==='string'&&e.data.type.indexOf('class-notice-')===0)got.push(e.data);
});
var f=document.getElementById('f');
f.addEventListener('load',function(){
  var out={ok:false};
  try{
    var W=f.contentWindow,D=f.contentDocument;
    out.hasFuncs=typeof W.__zqSetAdmin==='function'&&typeof W.__zqSetHidden==='function'&&
                 typeof W.__zqApplyOverride==='function'&&typeof W.__zqSetScroll==='function';
    W.__zqSetAdmin(true);
    out.adminOn=!!(D.querySelector('[data-act="edit"]'));
    /* 编辑 → 保存 */
    D.querySelector('[data-act="edit"]').click();
    out.editMask=!!(D.getElementById('editMask')&&D.getElementById('editMask').classList.contains('on'));
    D.getElementById('edTitle').value='编辑测试标题';
    D.getElementById('edTimeLabel').value='报名 11-07 12:00';
    D.querySelector('[data-act="edsave"]').click();
    /* 删除（父页模式直接 post） */
    D.querySelector('[data-act="del"]').click();
    /* 已隐藏列表 → 恢复 */
    W.__zqSetHidden([{gid:'g_essay',title:'征文（隐藏）'}]);
    out.hiddenSection=!!(D.getElementById('hiddenWrap')&&D.getElementById('hiddenWrap').style.display!=='none');
    D.querySelector('[data-act="restore"]').click();
    /* 父页直接套用 override */
    W.__zqApplyOverride('g_dorm',{title:'宿舍卫生检查（父页覆盖）'});
    out.overrideTitle=(W.findGroup('g_dorm')||{}).title||'';
    out.ok=true;
  }catch(e){out.err=String(e&&e.stack||e)}
  setTimeout(function(){
    var msgs=got.filter(function(m){return ['class-notice-edit','class-notice-hide','class-notice-restore'].indexOf(m.type)>=0});
    var pre=document.createElement('pre');pre.id='__probe';
    pre.textContent=JSON.stringify({out:out,msgs:msgs});
    document.body.appendChild(pre);
  },250);
});
</script></body></html>"""


def main():
    demo = DEMO.read_text(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "notice.html").write_text(demo, encoding="utf-8")
    shell = OUT / "parent_shell.html"
    shell.write_text(PARENT, encoding="utf-8")
    dom_file = OUT / "parent_dom.html"
    cmd = [str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           "--allow-file-access-from-files", "--virtual-time-budget=5000", "--dump-dom",
           "--user-data-dir=" + str(OUT / "edge-parent"), shell.as_uri()]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    dom = proc.stdout.decode("utf-8", "replace")
    dom_file.write_text(dom, encoding="utf-8")
    m = re.search(r'<pre id="__probe">(.*?)</pre>', dom, re.S)
    if not m:
        print("FAIL: no probe output", proc.stderr.decode("utf-8", "replace")[-600:])
        return 1
    raw = m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    data = json.loads(raw)
    out, msgs = data.get("out") or {}, data.get("msgs") or []
    print("parent->iframe:", json.dumps(out, ensure_ascii=False))
    print("iframe->parent messages:", json.dumps(msgs, ensure_ascii=False)[:1000])
    by_type = {}
    for msg in msgs:
        by_type.setdefault(msg.get("type"), msg)
    checks = [
        ("父页函数齐全", out.get("hasFuncs") is True),
        ("无 JS 错误", not out.get("err")),
        ("adminOn 后有编辑按钮", out.get("adminOn") is True),
        ("编辑弹层打开", out.get("editMask") is True),
        ("收到 class-notice-edit", "class-notice-edit" in by_type),
        ("edit 带 fields.title", (by_type.get("class-notice-edit") or {}).get("fields", {}).get("title") == "编辑测试标题"),
        ("edit 带 gid", bool((by_type.get("class-notice-edit") or {}).get("gid"))),
        ("收到 class-notice-hide", "class-notice-hide" in by_type),
        ("hide 带 gid", bool((by_type.get("class-notice-hide") or {}).get("gid"))),
        ("已隐藏区可见", out.get("hiddenSection") is True),
        ("收到 class-notice-restore", "class-notice-restore" in by_type),
        ("restore 带 gid", (by_type.get("class-notice-restore") or {}).get("gid") == "g_essay"),
        ("__zqApplyOverride 生效", out.get("overrideTitle") == "宿舍卫生检查（父页覆盖）"),
        ("无多余错误消息", out.get("ok") is True),
    ]
    failed = [n for n, ok in checks if not ok]
    print("\n== MESSAGE CONTRACT: %d/%d PASS ==" % (len(checks) - len(failed), len(checks)))
    for n, ok in checks:
        print(("  PASS " if ok else "  FAIL ") + n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
