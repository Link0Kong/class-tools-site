"""Headless Edge regression for single-task links, recipient confirmation and clipboard fallback."""
import functools
import html
import http.server
import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from urllib.parse import quote

from _test_account import TEST_NAME, TEST_SID, assert_test_identity
from mobile_tool_session_check import QuietHandler
from task_check import EDGE, build_preview

PAYLOAD = {"t": "<b>共享任务</b>", "d": "明晚截止", "l": "原分组", "n": "步骤说明",
           "s": ["第一步", "第二步", "<img src=x>"], "done": True, "id": "foreign",
           "sourceNoticeId": "private", "attachments": ["foreign"], "sid": "other"}
HASH = "#task-share=" + quote(json.dumps(PAYLOAD, ensure_ascii=False, separators=(",", ":")), safe="")
SETUP = r"""<script>
var shareCase=location.pathname.split('/')[1],seedIdentity=JSON.parse(localStorage.getItem('zq_class_identity'));
if(shareCase==='login'){
  localStorage.removeItem('zq_class_identity');
  var testFetch=window.fetch;
  window.fetch=function(url,opts){
    if(String(url).includes('rpc/class_verify'))return ok(Object.assign({ok:true},seedIdentity));
    return testFetch.apply(this,arguments);
  };
}
window.__copyResult='';
Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:function(){return Promise.reject(Error('denied'));}}});
document.execCommand=function(cmd){if(cmd==='copy'){window.__copyResult=document.activeElement.value;return true;}return false;};
</script>"""

RUN = r"""<script>
window.addEventListener('load',async function(){
  const $=sel=>document.querySelector(sel),click=sel=>$(sel).click(),pause=ms=>new Promise(r=>setTimeout(r,ms));
  const visible=sel=>!$(sel).hidden&&getComputedStyle($(sel)).display!=='none';
  var count=0;
  function check(v,k){count++;if(!v)throw Error(k);}
  function paste(){click('#tkMore');click('[data-tkm=sharelink]');}
  async function tryLink(l){$('#tkShareLink').value=l;click('#tkShareAct');await pause(20);}
  try{
    await pause(100);
    if(shareCase==='login'){
      check(!__qrLogin.auth().ready&&!visible('#tkSharePanel')&&!$('#tkShareTaskTitle').textContent,'data shown before login');
      $('#igSid').value='__SID__';$('#igName').value='__NAME__';$('#igAgree').checked=true;
      $('#igAgree').dispatchEvent(new Event('change'));click('#igGo');await pause(120);
    }
    if(shareCase==='sender'){
      click('[data-tab=hw]');TASK.setSeg('my');
      const item=TASK.items()[0],n=TASK.items().length;
      item.title='标'.repeat(59)+'😀';item.notes='PRIVATE_NOTE_SENTINEL';
      item.steps=[{text:'步'.repeat(39)+'😀',done:true,note:'prv'},{text:'第二步'},{text:'第三步'},{text:'第四步'}];
      TASK.openDetail(item.id);click('[data-tkdtshare]');
      const u=$('#tkShareLink').value,obj=JSON.parse(decodeURIComponent(new URL(u).hash.slice('#task-share='.length)));
      check(u.startsWith('https://tool.furina.fun/#task-share='),'canonical URL');
      check(Object.keys(obj).sort().join(',')==='d,l,n,s,t','whitelist sender');
      check(obj.t==='标'.repeat(59)&&obj.s[0]==='步'.repeat(39),'unicode limits');
      check(obj.n===''&&!JSON.stringify(obj).includes('PRIVATE_NOTE')&&obj.s.length===3,'private fields/steps');
      click('#tkShareAct');await pause(25);check(window.__copyResult===u,'copy fallback');
      click('#tkShareClose');click('#tkDtClose');paste();
      await tryLink('https://example.org/#task-share=%7B%22t%22%3A%22x%22%7D');
      check(visible('#tkShareError')&&TASK.items().length===n,'reject wrong origin');
      await tryLink('https://tool.furina.fun/#task-share='+encodeURIComponent('{"t":"   "}'));
      check(visible('#tkShareError')&&!visible('#tkSharePreview'),'reject empty title');
      const large='https://tool.furina.fun/#task-share='+encodeURIComponent(JSON.stringify({t:'A'.repeat(140),n:'B'.repeat(600),l:'C'.repeat(25),d:'D'.repeat(48),s:Array(9).fill('E'.repeat(170))}));
      await tryLink(large);
      check($('#tkShareTaskTitle').textContent.length===100&&$('#tkShareNote').textContent.length===500,'recipient title/note limits');
      check($('#tkShareSteps').children.length===6&&$('#tkShareSteps li').textContent.length===120,'recipient step limits');
      check($('#tkShareMeta').textContent==='C'.repeat(20)+' · '+'D'.repeat(32),'display lengths');
      click('#tkShareCancel');paste();
      await tryLink(u);check(visible('#tkSharePreview'),'paste opens preview');
      click('#tkShareCancel');check(TASK.items().length===n,'paste cancel');
      location.hash='__HASH__';await pause(120);
    }
    check(__qrLogin.auth().ready&&visible('#tkSharePanel')&&visible('#tkSharePreview'),'preview/lifecycle');
    check($('#tkShareTaskTitle').textContent==='<b>共享任务</b>'&&!$('#tkShareTaskTitle b')&&!$('#tkShareSteps img'),'literal text');
    check($('#tkShareMeta').textContent.includes('原分组')&&$('#tkShareMeta').textContent.includes('明晚截止'),'preview metadata');
    check($('#tkShareSteps').children.length===3&&$('#tkShareNote').textContent==='步骤说明','notes/steps');
    check(!location.hash.startsWith('#task-share='),'consumed fragment');
    const before=TASK.items().length;
    if(shareCase==='cold'){
      click('#tkShareCancel');window.dispatchEvent(new HashChangeEvent('hashchange'));
      check(!visible('#tkSharePanel')&&TASK.items().length===before,'cancel duplicate event');
    }else{
      window.dispatchEvent(new HashChangeEvent('hashchange'));click('#tkShareAct');click('#tkShareAct');
      const copy=TASK.items().find(t=>t.title==='<b>共享任务</b>');
      check(TASK.items().length===before+1&&copy.id!=='foreign','one fresh ID');
      check(copy.notes==='步骤说明'&&copy.steps.length===3&&copy.steps.every(s=>!s.done&&!s.note),'copy notes/steps');
      check(!copy.done&&!copy.list&&!copy.due&&!copy.sourceHwId&&!copy.sourceNoticeId&&!copy.attachments,'isolated metadata');
    }
    check(!window.__errs.length,'runtime errors');
    document.documentElement.dataset.taskShareCheck='PASS '+count;
  }catch(e){document.documentElement.dataset.taskShareCheck='FAIL '+e.message;}
});
</script>"""


def main():
    assert_test_identity(TEST_SID, TEST_NAME)
    doc = build_preview(False).replace("</script>", "</script>" + SETUP, 1)
    run = RUN.replace("__HASH__", HASH).replace("__SID__", TEST_SID).replace("__NAME__", TEST_NAME)
    doc = doc.replace("</body>", run + "</body>", 1)
    with tempfile.TemporaryDirectory() as tmp:
        for case in ("cold", "login", "sender"):
            path = Path(tmp) / case
            path.mkdir()
            (path / "index.html").write_text(doc, encoding="utf-8")
        handler = functools.partial(QuietHandler, directory=tmp)
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                for case in ("cold", "login", "sender"):
                    url = f"http://127.0.0.1:{server.server_port}/{case}/" + (HASH if case != "sender" else "")
                    run = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                                          "--virtual-time-budget=4500", "--dump-dom", url],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=45)
                    m = re.search(r'data-task-share-check="([^"]+)"', run.stdout.decode("utf-8", "replace"))
                    result = html.unescape(m[1]) if m else "FAIL missing result"
                    print(case, result, flush=True)
                    if not result.startswith("PASS"):
                        return 1
            finally:
                server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
