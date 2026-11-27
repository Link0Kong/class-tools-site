"""CT-08 frozen vectors through the Web merger and the authenticated settings write path."""
import hashlib
import json

from _test_account import TEST_SID
from identity_sync_check import IdentityService
from sync_browser_fixture import HERE, browser_fixture, wait

SHA = "6bbd74410d67d83ef41ab768530b8c2ddd7f12eecd580e472942523ee1b1552c"


def main():
    cases=json.loads((HERE.parents[1]/"contracts/userdata/v1.json").read_bytes())
    packed=json.dumps(cases,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    assert hashlib.sha256(packed).hexdigest()==SHA
    src=(HERE.parent/"index.html").read_bytes()
    needle=b"function enterClass(r){"
    assert src.count(needle)==1
    service=IdentityService()
    sample=next(c for c in cases["cases"] if c["id"]=="section-boundaries")
    service.rows[TEST_SID]={"id":TEST_SID,"blob":json.dumps(sample["remote"])}
    with browser_fixture(service,src.replace(needle,b"window.qaUD={UD,D};"+needle)) as open_page:
        p=open_page()
        for case in cases["cases"]:
            args=json.dumps([case["remote"],case["local"]],ensure_ascii=False)
            result=p.evaluate("qaUD.UD.merge(..."+args+")")
            for path,expected in case["expect"].items():
                value=result
                for key in path.split("."): value=value[key]
                assert value==expected,(case["id"],path,value,expected)
            for path in case.get("absent",[]):
                value=result
                for key in path.split("."):
                    if key not in value: break
                    value=value[key]
                else: raise AssertionError((case["id"],path))
            if case.get("legacyEmptyDraw"): assert result["draw"] in ({},{"names":""})
            print(case["id"],"PASS")
        wait(p,"qaUD.UD.cacheRead()?.prefs?.future?.key==='qa'&&!qaUD.UD._pull&&!qaUD.UD._push")
        p.evaluate("qaUD.D.d.nick='QA-member';qaUD.D.save();qaUD.UD.push(true,['nick']);void 0")
        wait(p,"!qaUD.UD._push&&qaUD.UD.cacheRead()?.nick==='QA-member'")
        saved=json.loads(service.rows[TEST_SID]["blob"])
        assert saved["prefs"]==sample["remote"]["prefs"]
        assert saved["draw"]["optional"]==12 and saved["draw"]["names"]=="QA=fixture"
        assert "marks" not in saved and "marks" not in saved["at"]
        assert not p.evaluate("window.jsErrors")
        print("authenticated pull, edited nick, actual userdata POST, optional sibling fields and separate marks: PASS")
        p.close()


if __name__=="__main__":
    main()
