"""W01 account rollover through real page handlers and an isolated REST fixture."""
import argparse
import json
from pathlib import Path

from _test_account import TEST_SID
from sync_browser_fixture import HERE, browser_fixture, wait, screenshot

OTHER = "9999000001"


class IdentityService:
    tables = ["auth_ok", "marks", "userdata", "class_verify"]

    def __init__(self):
        self.tokens = {"fixture-a": TEST_SID, "fixture-b": OTHER, "fixture-b2": OTHER}
        self.rows = {}
        self.marks = {}

    def __call__(self, r):
        sid = self.tokens.get(r.get("token"))
        table = r["table"]
        if table == "class_verify":
            return 200, {"ok": True, "sid": OTHER, "name": "测试账号", "token": "fixture-b2"}, {}
        if table == "auth_ok":
            return 200, bool(sid), {}
        if not sid:
            return 401, {}, {}
        if r["method"] == "GET":
            if table == "marks":
                assert r["query"]["seat"] == "eq."+sid
                return 200, list(self.marks.get(sid, {}).values()), {}
            assert r["query"]["id"] == "eq."+sid
            return 200, [self.rows[sid]] if sid in self.rows else [], {}
        row = r["body"][0]
        if table == "marks":
            assert row["seat"] == sid
            self.marks.setdefault(sid, {})[row["id"]] = row
        else:
            assert row["id"] == sid
            self.rows[sid] = row
        return 201, [row], {}


def account(token="fixture-b", role=""):
    return json.dumps(dict(sid=OTHER, token=token, name="测试账号", role=role, ts=1700000000000))


def main(out):
    hooks = b"window.qaOwner={UD,D,HW,NT,enterClass,marksPull,setMark,resyncPending,identityClear,active:()=>syncOwner()};"
    raw = (HERE.parent/"index.html").read_bytes()
    needle = b"function enterClass(r){"
    assert raw.count(needle) == 1
    service = IdentityService()
    service.rows[TEST_SID] = {"id":TEST_SID,"blob":json.dumps({"v":6,"at":{"nick":123},"nick":"A-source"})}
    service.rows[OTHER] = {"id":OTHER,"blob":json.dumps({"v":6,"at":{"nick":125},"nick":"B-source"})}
    with browser_fixture(service, raw.replace(needle, hooks+needle)) as open_page:
        p = open_page()
        run = p.evaluate
        wait(p, "qaOwner.D.d.nick==='A-source'&&!qaOwner.UD._pull")
        run("window.hold=r=>r.table==='userdata'&&r.method==='GET';qaOwner.UD.pull(true);void 0")
        wait(p, "!!window.release")
        run("window.oldRead=release;window.hold=r=>r.table==='marks'&&r.method==='POST';qaOwner.setMark('hw',{id:'entry'},true)")
        wait(p, "release&&release!==oldRead")
        run("window.oldMark=release;qaOwner.enterClass("+account()+");void 0")
        wait(p, "qaOwner.D.d.nick==='B-source'")
        run("oldRead();oldMark();")
        wait(p, "!qaOwner.UD._pull&&qaOwner.D.d.nick==='B-source'&&!qaOwner.HW.marks.entry")
        assert not run("JSON.stringify(qaOwner.UD.cacheRead()).includes('A-source')")
        assert not run("qaOwner.D.d.markPend.length")
        print("same-page delayed marks/GET: correct owner, B cache and view")

        run("window.hold=r=>r.table==='marks'&&r.method==='POST';qaOwner.setMark('hw',{id:'entry'},true)")
        wait(p,"!!release")
        run("qaOwner.setMark('hw',{id:'entry'},false);release();")
        wait(p, "!qaOwner.D.d.markPend.length")
        assert not service.marks[OTHER][OTHER+"|hw|entry"]["val"]
        run("window.fail=r=>r.table==='marks'&&r.method==='POST';qaOwner.setMark('hw',{id:'retry'},true)")
        wait(p, "qaOwner.D.d.markPend.length===1&&!Object.keys(qaOwner.active().sending).length")
        run("window.fail=null;qaOwner.resyncPending()")
        wait(p,"!qaOwner.D.d.markPend.length")
        run("window.hold=r=>r.table==='userdata'&&r.method==='POST';qaOwner.D.d.nick='B-pending';qaOwner.D.save();qaOwner.UD.push(true,['nick']);void 0")
        wait(p,"!!release")
        run("window.oldWrite=release;qaOwner.enterClass("+account("fixture-b2","代表")+");oldWrite();void 0")
        wait(p,"qaOwner.active().token==='fixture-b2'&&!qaOwner.UD._pull")
        assert run("qaOwner.active().role==='代表'")
        run("window.fake=r=>r.table==='marks'&&r.method==='POST'?new Response('{}',{status:401}):null;qaOwner.setMark('hw',{id:'expire'},true)")
        wait(p,"qaOwner.D.d.markPend.length===1&&!Object.keys(qaOwner.active().sending).length")
        run("window.fake=null;qaOwner.resyncPending()")
        wait(p,"!qaOwner.D.d.markPend.length")
        print("serialized toggle; 503/401 retain pending; same-sid token and role rotation")

        second = open_page()
        second.evaluate("qaOwner.enterClass("+json.dumps({"sid":TEST_SID,"token":"fixture-a","name":"测试账号"})+");void 0")
        wait(p,"window.qaOwner&&qaOwner.active()?.sid==="+json.dumps(TEST_SID)+"&&qaOwner.D.d.nick==='A-source'")
        wait(p,"qaOwner.D.d.markPend.length===0")
        run("qaOwner.D.d.nick='A-after';qaOwner.D.save();qaOwner.UD.push(true,['nick']);void 0")
        wait(p,"!qaOwner.UD._push&&qaOwner.UD.cacheRead().nick==='A-after'")
        assert json.loads(service.rows[TEST_SID]["blob"])["nick"] == "A-after"
        screenshot(p,out,"identity-reloaded")
        second.close()
        run("document.getElementById('idChip').click();")
        wait(p,"document.readyState==='complete'&&!qaOwner.active()&&document.body.classList.contains('id-locked')")
        wait(p,"document.readyState==='complete'&&!!document.querySelector('#igSid')&&document.body.classList.contains('id-locked')")
        run("document.querySelector('#igSid').value="+json.dumps(OTHER)+";document.querySelector('#igName').value='测试账号';const box=document.querySelector('#igAgree');box.checked=true;box.dispatchEvent(new Event('change'));document.querySelector('#igGo').click();")
        if not p.wait_for("qaOwner.active()?.sid==="+json.dumps(OTHER),8):
            raise AssertionError(run("[location.href,document.body.className,document.querySelector('#igErr')?.textContent,document.querySelector('#igGo')?.disabled,document.querySelector('#igSid')?.value,calls.filter(r=>r.table==='class_verify'),qaOwner.active()?.sid]"))
        assert not run("qaOwner.D.d.nick==='A-after'")
        assert not run("window.jsErrors"), run("window.jsErrors")
        print("same-origin tab change, logout and login form, subsequent owner-only settings write: PASS")
        p.close()


if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--artifacts",type=Path)
    main(ap.parse_args().artifacts)
