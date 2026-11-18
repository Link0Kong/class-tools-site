# -*- coding: utf-8 -*-
"""v2.0.0 通知模板 headless 校验（临时脚本，收尾删除）。

把生成的 notice-board-live-demo.html 复制一份，在 </body> 前注入断言脚本，
用 headless Edge --dump-dom 跑真实浏览器 JS，输出 JSON 断言结果。
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
DEMO = Path(r"C:\Users\Ko_Li\.openclaw\workspace\web\tools\notice-board-live-demo.html")
OUT_DIR = Path(r"C:\briefdesk\data\_v2_template_check")

TEST_JS = r"""
<script>
(function(){
  var out={errors:[]};
  window.onerror=function(m,s,l,c,e){out.errors.push(String(m));};
  function q(s){return document.querySelector(s)}
  function qa(s){return Array.prototype.slice.call(document.querySelectorAll(s))}
  try{
    out.groupCount=GROUPS.length;
    out.cards=qa('#list .gcard').length;
    out.listTextLen=(q('#list')?q('#list').textContent.length:0);
    out.recurLines=qa('.recurline').length;
    out.recurNextText=(qa('.recurline .rn')[0]||{}).textContent||'';
    var dorm=findGroup('g_dorm');
    out.dormRecurrence=!!(dorm&&dorm.recurrence&&dorm.recurrence.freq==='monthly_weeks');
    var next=dorm?nextRecurDate(dorm.recurrence, Date.now()):null;
    out.dormNextComputed=next?recDateText(next):'';
    out.dormActionable=dorm?dorm.actionable:'?';
    out.dormStatus=(dorm?statusOf(dorm).label:'?');
    out.missingCount=qa('.linkrow.missing').length;
    out.missingBadges=qa('.missbadge').length;
    out.suppLabels=qa('.gi-type.supp').length;
    /* 契约 §0.3 后补充通知原文收进「原始消息」弹层 → 数据层面断言 */
    out.suppItems=0;GROUPS.forEach(function(g){(g.items||[]).forEach(function(it){if(it&&it.label==='补充通知')out.suppItems++;});});
    out.mergedChips=qa('.srcmore').length;
    out.mergedCards=GROUPS.filter(function(g){return (g.mergedSources||[]).length>1;}).length;
    out.updatedBadges=qa('.badge.upd').length;
    var med=findGroup('g_qqm_7704134971497063025_c0');
    out.medDeadline=med?med.deadline:'?';
    out.medEventAt=med?med.eventAt:'?';
    out.medTimeLabel=med?med.timeLabel:'?';
    out.medUpdatedAt=med?med.updatedAt:'?';
    out.medHasSupplementItem=!!(med&&(med.items||[]).some(function(it){return it.label==='补充通知'}));
    out.medHasFileUrl=!!(med&&(med.items||[]).some(function(it){return it.kind==='file'&&it.url}));
    var roster=findGroup('g_qqfile_1a81286a3a');
    out.rosterHasFileUrl=!!(roster&&(roster.items||[]).some(function(it){return it.kind==='file'&&it.url}));
    /* 展开/收起动画：不整页重渲染，只切 class + max-height */
    var card=document.getElementById('card-g_dorm');
    var box=card?card.querySelector('.gcollapse'):null;
    var btn=card?card.querySelector('[data-act="fold"]'):null;
    out.foldBoxFound=!!box;
    if(card&&box&&btn){
      out.foldOpenMax=box.style.maxHeight;
      out.foldBtnTextOpen=btn.textContent;
      btn.click();
      out.foldedClass=card.classList.contains('folded');
      out.foldBtnTextFolded=btn.textContent;
      btn.click();
      out.foldClassAfterExpand=card.classList.contains('folded');
    }
    /* 待获取点击提示（独立页走内置弹层） */
    var miss=qa('.linkrow.missing')[0];
    if(miss){miss.click();}
    var modal=q('#modal');
    out.missModalOpen=!!(modal&&modal.classList.contains('on'));
    var mtext=modal?modal.textContent:'';
    out.missModalHasHint=mtext.indexOf('暂未获取')>=0&&mtext.indexOf('QQ 群')>=0;
    out.missModalHasCopy=!!(modal&&modal.querySelector('[data-act="copyname"]'));
    if(modal){modal.classList.remove('on');}
    /* 管理员接口（plan §3.1） */
    window.__zqSetAdmin(true);
    out.adminEditBtns=qa('[data-act="edit"]').length;
    out.adminDelBtns=qa('[data-act="del"]').length;
    window.__zqApplyOverride('g_dorm',{title:'宿舍卫生检查安排（编辑测试）'});
    out.overrideApplied=(findGroup('g_dorm').title||'').indexOf('编辑测试')>=0;
    window.__zqSetHidden([{gid:'g_essay',title:'征文（隐藏测试）'}]);
    out.hiddenCountText=(q('#hiddenCount')||{}).textContent||'';
    out.hiddenCardRendered=qa('#list .gcard[data-gid="g_essay"]').length;
    out.hiddenSectionVisible=!!(q('#hiddenWrap')&&q('#hiddenWrap').style.display!=='none');
    window.__zqSetAdmin(false);
    out.hiddenSectionAfterAdminOff=!!(q('#hiddenWrap')&&q('#hiddenWrap').style.display!=='none');
    out.hasApplyDone=typeof window.__zqApplyDone!=='undefined';
    out.hasSetScroll=typeof window.__zqSetScroll==='function';
    /* 编辑弹层 */
    window.__zqSetAdmin(true);
    var eb=qa('[data-act="edit"]')[0];
    if(eb){eb.click();}
    out.editMaskOpen=!!(q('#editMask')&&q('#editMask').classList.contains('on'));
    out.editFields=qa('#editMask input,#editMask textarea,#editMask select').length;
    if(q('#editMask'))q('#editMask').classList.remove('on');
    window.__zqSetAdmin(false);
    out.sigNonEmpty=!!RENDER_SIG;
    out.hasReducedMotionCSS=(document.querySelector('style')||{}).textContent.indexOf('prefers-reduced-motion')>=0;
  }catch(e){out.errors.push('EX:'+(e&&e.message))}
  var pre=document.createElement('pre');pre.id='__testout';
  pre.textContent=JSON.stringify(out);
  document.body.appendChild(pre);
})();
</script>
"""


def main():
    html = DEMO.read_text(encoding="utf-8")
    injected = html.replace("</body>", TEST_JS + "</body>", 1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_DIR / "check.html"
    tmp.write_text(injected, encoding="utf-8")
    dom_file = OUT_DIR / "dom.html"
    cmd = [str(EDGE), "--headless", "--disable-gpu", "--no-first-run",
           "--no-default-browser-check", "--allow-file-access-from-files",
           "--virtual-time-budget=4000", "--dump-dom",
           "--user-data-dir=" + str(OUT_DIR / "edge-profile"),
           tmp.as_uri()]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    dom = proc.stdout.decode("utf-8", "replace")
    dom_file.write_text(dom, encoding="utf-8")
    m = re.search(r'<pre id="__testout">(.*?)</pre>', dom, re.S)
    if not m:
        print("NO TEST OUTPUT; stderr tail:", proc.stderr.decode("utf-8", "replace")[-800:])
        return 1
    raw = m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    data = json.loads(raw)
    print(json.dumps(data, ensure_ascii=False, indent=1))

    checks = [
        ("no js errors", not data.get("errors")),
        ("cards rendered", data.get("cards", 0) >= 1),
        ("g_dorm recurrence", data.get("dormRecurrence") is True),
        ("dorm next computed >= 11-11", data.get("dormNextComputed", "").startswith("11-11")),
        ("dorm status 长期安排", str(data.get("dormStatus", "")).startswith("长期安排")),
        ("dorm actionable false", data.get("dormActionable") is False),
        ("missing file badges > 0", data.get("missingBadges", 0) > 0),
        ("supplement items 数据存在(>0)", data.get("suppItems", 0) > 0),
        ("updated badge > 0", data.get("updatedBadges", 0) > 0),
        ("med deadline 11-07 18:00", data.get("medDeadline") == "2026-11-07T18:00:00+08:00"),
        ("med timeLabel", data.get("medTimeLabel") == "报名 11-07 12:00"),
        ("med has supplement item", data.get("medHasSupplementItem") is True),
        ("med has file url", data.get("medHasFileUrl") is True),
        ("roster has file url", data.get("rosterHasFileUrl") is True),
        ("miss modal hint", data.get("missModalHasHint") is True),
        ("miss modal copy btn", data.get("missModalHasCopy") is True),
        ("admin edit buttons", data.get("adminEditBtns", 0) > 0),
        ("override applied", data.get("overrideApplied") is True),
        ("hidden count text", "1" in str(data.get("hiddenCountText"))),
        ("hidden card removed", data.get("hiddenCardRendered") == 0),
        ("hidden section admin on", data.get("hiddenSectionVisible") is True),
        ("hidden section admin off", data.get("hiddenSectionAfterAdminOff") is False),
        ("__zqSetScroll exists", data.get("hasSetScroll") is True),
        ("edit mask opens", data.get("editMaskOpen") is True),
        ("edit fields >= 8", data.get("editFields", 0) >= 8),
        ("reduced motion css", data.get("hasReducedMotionCSS") is True),
        ("跨源合并卡存在且显示来源标签", data.get("mergedCards", 0) > 0 and data.get("mergedChips", 0) > 0),
    ]
    failed = [name for name, ok in checks if not ok]
    print("\n== TEMPLATE CHECKS: %d/%d PASS ==" % (len(checks) - len(failed), len(checks)))
    for name, ok in checks:
        print(("  PASS " if ok else "  FAIL ") + name)
    if data.get("errors"):
        print("JS ERRORS:", data["errors"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
