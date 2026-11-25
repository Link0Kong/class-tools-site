"""Exercise mobile tool landing, account isolation and native session delivery in Edge."""
import functools
import html
import http.server
from pathlib import Path
import re
import subprocess
import tempfile
import threading

from _test_account import TEST_SID, assert_test_identity
from task_check import EDGE, build_preview

NATIVE_SID = "9999000025"
CASES = {
    "stored-web": "",
    "injected-tasks": "?mobileTool=hw",
    "injected-notices": "?mobileTool=nt",
    "android-admin": "?mobileTool=ntadmin",
    "android-member": "?mobileTool=ntadmin",
    "missing-session": "?mobileTool=hw",
}

SETUP = r"""<script>
var mobileCase=location.pathname.split('/')[1],nativeUser={sid:'__NATIVE__',name:'测试账号乙',
  token:'fixture-mobile-session',is_admin:mobileCase!=='android-member',ts:Date.now()};
var browserIdentity=localStorage.getItem('zq_class_identity'), sentHeaders=[];
localStorage.setItem('zq_last_identity',browserIdentity);
var foreignBucket=localStorage.getItem('zq_tools_v2___BROWSER__');
localStorage.setItem('zq_tools_v2',foreignBucket);
localStorage.setItem('zq_auto_nt_done',JSON.stringify({legacyForeignMark:true}));
if(mobileCase.startsWith('injected-'))window.__ctMobileSession=nativeUser;
var mockFetch=window.fetch;
window.fetch=function(u,o){
  if(o&&o.headers&&o.headers['X-Device-Id'])sentHeaders.push(o.headers['X-Device-Id']);
  if(String(u).includes('rpc/class_verify'))return ok(Object.assign({ok:true},nativeUser));
  return mockFetch.apply(this,arguments);
};
// A trusted MessagePort event has the same null source as WebView.postWebMessage.
// Mirror delivery to the document's message listeners to exercise that platform path in Edge.
var bridge=new MessageChannel(),addMessage=window.addEventListener;
window.addEventListener=function(type,fn,opts){
  if(type==='message')bridge.port1.addEventListener(type,fn,opts);
  return addMessage.call(this,type,fn,opts);
};
bridge.port1.start();
</script>"""

CHECK = r"""<script>
window.addEventListener('load',async function(){
  var delay=ms=>new Promise(r=>setTimeout(r,ms)),checks=[];
  function check(label,ok){checks.push(label);if(!ok)throw new Error(label);}
  function active(){return document.querySelector('section.on')?.id;}
  function post(s){return JSON.stringify({type:'ct-native-session',session:s});}
  try{
    await delay(150);
    if(mobileCase==='stored-web'){
      check('ordinary web identity',__qrLogin.auth().sid==='__BROWSER__');
      check('ordinary web tabs',getComputedStyle(document.querySelector('#tabsBar')).display!=='none');
    }else{
      if(mobileCase.startsWith('android-')){
        check('stored browser session ignored',!__qrLogin.auth().ready);
        window.postMessage(post(nativeUser),'*');
        await delay(100);
        check('window sender ignored',!__qrLogin.auth().ready);
        bridge.port2.postMessage(post(nativeUser));
        await delay(120);
        check('null-source first message',__qrLogin.auth().sid===nativeUser.sid);
        bridge.port2.postMessage(post(JSON.parse(browserIdentity)));
        await delay(100);
        check('second message ignored',__qrLogin.auth().sid===nativeUser.sid);
        check('direct authorized view',active()===(mobileCase==='android-admin'?'s-ntadmin':'s-nt'));
      }else if(mobileCase==='missing-session'){
        check('missing injection keeps gate',!__qrLogin.auth().ready);
        check('no foreign identity in form',!document.querySelector('#igSid').value);
        document.querySelector('#igSid').value=nativeUser.sid;
        document.querySelector('#igName').value=nativeUser.name;
        var agree=document.querySelector('#igAgree');agree.checked=true;agree.dispatchEvent(new Event('change'));
        document.querySelector('#igGo').click();
        await delay(120);
        check('manual login lands in requested tool',active()==='s-hw');
      }else{
        check('injected page identity',__qrLogin.auth().sid===nativeUser.sid);
        check('matching tool',active()===(mobileCase==='injected-tasks'?'s-hw':'s-nt'));
        if(mobileCase==='injected-notices'){
          var fab=document.querySelector('#ntAdminFab');
          check('admin entry visible',fab.getBoundingClientRect().height>0);
          fab.click();check('admin entry opens',active()==='s-ntadmin');
        }
      }
      check('native layout',document.documentElement.classList.contains('mobile-tool') &&
        getComputedStyle(document.querySelector('#tabsBar')).display==='none');
      check('only current credentials used',sentHeaders.length>0 && sentHeaders.every(x=>x===nativeUser.token));
      check('browser identity preserved',localStorage.getItem('zq_class_identity')===browserIdentity &&
        localStorage.getItem('zq_last_identity')===browserIdentity);
      check('native credentials memory only',!JSON.stringify(localStorage).includes(nativeUser.token) &&
        !('__ctMobileSession' in window));
      check('foreign task bucket isolated',TASK.items().length===0 && localStorage.getItem('zq_tools_v2___BROWSER__')===foreignBucket);
      check('unscoped legacy cache isolated',localStorage.getItem('zq_tools_v2')===foreignBucket &&
        JSON.parse(localStorage.getItem('zq_auto_nt_done')).legacyForeignMark);
    }
    check('no page errors',window.__errs.length===0);
    document.documentElement.dataset.mobileCheck='PASS '+checks.length;
  }catch(err){document.documentElement.dataset.mobileCheck='FAIL '+err.message;}
});
</script>"""


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    assert_test_identity(TEST_SID)
    assert_test_identity(NATIVE_SID)
    document = build_preview(False)
    document = document.replace("</script>", "</script>" + SETUP, 1)
    document = document.replace("</body>", CHECK + "</body>", 1)
    document = document.replace("__BROWSER__", TEST_SID).replace("__NATIVE__", NATIVE_SID)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        for case in CASES:
            (root / case).mkdir()
            (root / case / "index.html").write_text(document, encoding="utf-8")
        handler = functools.partial(QuietHandler, directory=folder)
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                for case, query in CASES.items():
                    url = f"http://127.0.0.1:{server.server_port}/{case}/{query}"
                    run = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                                          "--virtual-time-budget=3500", "--dump-dom", url],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=45)
                    match = re.search(r'data-mobile-check="([^"]*)"', run.stdout.decode("utf-8", "replace"))
                    result = html.unescape(match[1]) if match else "FAIL missing result"
                    print(case, result, flush=True)
                    if not result.startswith("PASS"):
                        return 1
            finally:
                server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
