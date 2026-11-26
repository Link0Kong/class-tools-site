"""V05: exercise real task UI and taskdata CAS with two isolated browser stores, no live API."""
import argparse
import json
from copy import deepcopy
from pathlib import Path

from _test_account import TEST_SID
from sync_browser_fixture import browser_fixture, click, screenshot, wait


class TaskService:
    tables = ["taskdata","auth_ok"]

    def __init__(self):
        self.rows = {}
        self.requests = []
        self.zero = 0
        self.collisions = 0
        self.tokens = {"fixture-a":TEST_SID, "fixture-rotate":TEST_SID, "fixture-b":"9999000012"}

    def __call__(self, req):
        self.requests.append(req)
        token, method, query = req["token"], req["method"], req["query"]
        account = self.tokens.get(token)
        if req["table"].split("/")[-1]=="auth_ok": return 200,bool(account),{}
        if not account:
            return (200 if method=="GET" else 403), [], {}
        remote = self.rows.get(account)
        if method == "GET":
            assert query["id"] == "eq."+account and query["select"] == "id,blob,ts", query
            return 200, [deepcopy(remote)] if remote else [], {}
        row = req["body"]
        assert row["id"] == account and isinstance(row["blob"], str)
        if method == "PATCH":
            assert query["id"] == "eq."+account and req["prefer"] == "return=representation"
            conflict = not remote or query["ts"] != "eq."+str(remote["ts"])
        else:
            assert method == "POST" and req["prefer"] == "resolution=ignore-duplicates,return=representation"
            conflict = bool(remote)
        if self.zero or conflict:
            self.collisions += 1
            self.zero = max(0, self.zero-1)
            return 200, [], {}
        assert row["ts"] > (remote or {"ts":0})["ts"]
        self.rows[account] = deepcopy(row)
        return 200, [deepcopy(row)], {}

    def leaf(self, sid=TEST_SID):
        raw = json.loads(self.rows[sid]["blob"])
        return raw.get("data",{}).get("task",raw)

    def writes(self):
        return len([r for r in self.requests if r["table"]=="taskdata" and r["method"] != "GET"])


def sync(page):
    return page.evaluate("TASKSYNC.pull(true)", True)


def quick(page, name):
    page.evaluate("document.querySelector('#tkQuick').value="+json.dumps(name))
    click(page,"#tkQuickAdd")


def edit(page, task_id, field, value, save=True):
    page.evaluate("TASK.open("+json.dumps(task_id)+")")
    page.evaluate("document.querySelector("+json.dumps("#tkF"+field)+").value="+json.dumps(value))
    if save:
        click(page,"#tkFSave")


def hold_write(page):
    page.evaluate("window.hold=r=>r.table==='taskdata'&&r.method!=='GET';void TASKSYNC.pull(true)")
    wait(page,"typeof window.release==='function'")


def check_absence(html):
    service=TaskService()
    with browser_fixture(service,html) as open_page:
        page=open_page(seed="window.fail=r=>r.table==='auth_ok'")
        wait(page,"TASKSYNC.state().status.includes('暂不可核验')")
        page.evaluate("__diag.gotoTab('hw');TASK.setSeg('my')")
        quick(page,"first-create")
        assert not sync(page) and service.writes()==0
        assert page.evaluate("TASK.items().length===1&&TASKSYNC.state().dirty")
        page.evaluate("window.fail=null;window.fake=r=>r.table==='auth_ok'?new Response('{}'):null")
        assert not sync(page) and "暂不可核验" in page.evaluate("TASKSYNC.state().status")
        page.evaluate("window.fake=null")
        assert sync(page) and service.writes()==1
        item=page.evaluate("TASK.items()[0].id")
        old=deepcopy(service.rows[TEST_SID])
        key=json.dumps("zq_task_cloud_"+TEST_SID)
        checkpoint="JSON.parse(localStorage["+key+"]).base"
        # Both a clean reader and a dirty editor retain the last verified row when RLS masks it.
        service.tokens.pop("fixture-a")
        assert not sync(page) and page.evaluate(checkpoint)==old
        assert page.evaluate("TASK.items().length===1&&!TASKSYNC.state().dirty")
        assert "无权限" in page.evaluate("TASKSYNC.state().status")
        edit(page,item,"Notes","offline-draft")
        assert not sync(page) and page.evaluate(checkpoint)==old
        assert page.evaluate("TASK.items()[0].notes==='offline-draft'&&TASKSYNC.state().dirty")
        page.evaluate("window.fail=r=>r.table==='auth_ok'")
        assert not sync(page) and "暂不可核验" in page.evaluate("TASKSYNC.state().status")
        page.evaluate("window.fail=null")
        assert service.writes()==1
        # An authenticated physical disappearance differs from an explicit, versioned clear.
        service.tokens["fixture-a"]=TEST_SID
        service.rows.pop(TEST_SID)
        assert not sync(page) and "暂不可见" in page.evaluate("TASKSYNC.state().status")
        assert page.evaluate(checkpoint)==old and page.evaluate("TASK.items()[0].notes==='offline-draft'&&TASKSYNC.state().dirty")
        # An obsolete auth probe cannot clear or reject a renewed same-owner session.
        page.evaluate("window.hold=r=>r.table==='auth_ok';void TASKSYNC.pull(true)")
        wait(page,"typeof release==='function'")
        service.rows[TEST_SID]=old
        page.evaluate("fixtureEnterClass({sid:"+json.dumps(TEST_SID)+",name:'测试账号',token:'fixture-rotate'});TASKSYNC.boot()")
        wait(page,"TASKSYNC.state().status==='已同步'&&!TASKSYNC.state().dirty")
        page.evaluate("release()")
        assert service.leaf()["items"][0]["notes"]=="offline-draft"
        # An incoming legitimate clear applies even to the old offline editor's copy.
        edit(page,item,"Notes","stale-after-clear")
        service.rows[TEST_SID]={"id":TEST_SID,"ts":service.rows[TEST_SID]["ts"]+1,"blob":json.dumps({"v":1,"items":[],"lists":[]})}
        assert sync(page) and page.evaluate("TASK.items().length===0&&!TASKSYNC.state().dirty")
        assert page.evaluate(checkpoint)==service.rows[TEST_SID]
        print("PASS RLS HTTP 200 []: clean/dirty existing row preserved, first-create waits for auth, unavailable/denied/unexpected auth differentiated, same-sid token renewed, real versioned clear applied")


def check(directory=None):
    service=TaskService()
    html=(Path(__file__).resolve().parents[1]/'index.html').read_bytes()
    html=html.replace(b'function enterClass(r){',b'window.fixtureEnterClass=enterClass;function enterClass(r){',1)
    marker=b'    window.addEventListener("online",function(){boot();pull(true);});'
    assert html.count(marker)==1
    html=html.replace(marker,b'    window.fixtureTaskWire={rebase:rebase,unpack:unpack};'+marker)
    cases=json.loads((Path(__file__).resolve().parents[2]/"deploy/tests/taskdata_conflicts_v1.json").read_text(encoding="utf8"))
    with browser_fixture(service,html) as open_page:
        a=open_page()
        b=open_page("localhost")
        for p in (a,b):
            wait(p,"TASKSYNC.state().status.includes('暂无可见')")
            p.evaluate("__diag.gotoTab('hw');TASK.setSeg('my')")
        for case in cases["merge"]:
            args=",".join(json.dumps(case[key]) for key in ("base","local","remote"))
            assert a.evaluate("fixtureTaskWire.rebase("+args+")")==case["expected"], case["name"]
        for case in cases["wire"]:
            arg=json.dumps({"blob":case["blob"],"ts":case.get("ts",1)})
            ok=a.evaluate("(()=>{try{fixtureTaskWire.unpack("+arg+");return true}catch{return false}})()")
            assert ok==(case["path"] is not None), case["name"]
        quick(a,"device-A")
        hold_write(a)
        quick(b,"device-B")
        assert sync(b)
        a.evaluate("release()")
        wait(a,"TASKSYNC.state().status==='已同步'")
        assert service.collisions==1
        assert sync(b)
        rows={r["title"]:r["id"] for r in service.leaf()["items"]}
        assert set(rows)=={"device-A","device-B"}
        x,y=rows["device-A"],rows["device-B"]
        edit(a,x,"Title","A-edit")
        hold_write(a)
        edit(b,y,"Title","B-edit")
        assert sync(b)
        a.evaluate("release()")
        wait(a,"TASKSYNC.state().status==='已同步'")
        assert sync(b)
        assert {r["title"] for r in service.leaf()["items"]}=={"A-edit","B-edit"}
        edit(a,x,"Title","A-field")
        hold_write(a)
        edit(b,x,"Notes","B-note")
        assert sync(b)
        quick(a,"while-writing")
        a.evaluate("release()")
        wait(a,"TASKSYNC.state().status==='已同步'&&!TASKSYNC.state().dirty")
        row=next(r for r in service.leaf()["items"] if r["id"]==x)
        assert row["notes"]=="B-note" and row["title"]=="A-field"
        assert any(r["title"]=="while-writing" for r in service.leaf()["items"])
        assert sync(b)
        edit(b,x,"Notes","offline-old",False)
        assert not sync(b)
        assert "待保存" in b.evaluate("TASKSYNC.state().status")
        a.evaluate("TASK.open("+json.dumps(x)+")")
        click(a,"#tkFDelete")
        assert sync(a)
        click(b,"#tkFSave")
        assert sync(b)
        assert all(r["id"]!=x for r in service.leaf()["items"])
        quick(a,"lost-ack")
        a.evaluate("window.lose=r=>r.method==='PATCH'")
        assert not sync(a) and a.evaluate("TASKSYNC.state().dirty")
        writes=service.writes()
        assert sync(a) and service.writes()==writes
        quick(a,"bounded")
        service.zero=4
        assert not sync(a) and service.writes()==writes+4
        assert "待同步" in a.evaluate("TASKSYNC.state().status")
        assert sync(a)
        # The origin row can be a legacy wrapper. Keep untouched metadata and device-only files private.
        old=deepcopy(service.leaf())
        for item in old["items"]: item["futureItem"]={"flag":True}
        old.setdefault("prefs",{})["futurePref"]="keep"
        wrapped={"envelope":12,"data":{"futureSibling":True,"task":old}}
        service.rows[TEST_SID].update(blob=json.dumps(wrapped),ts=service.rows[TEST_SID]["ts"]+1)
        assert sync(a)
        att=json.dumps([{"id":"fixture","n":"qa.txt","t":"text/plain","s":1,"d":"data:text/plain;base64,QQ=="}])
        a.evaluate("TASK.items().find(t=>t.id==="+json.dumps(y)+").attachments="+json.dumps(att))
        edit(a,y,"Notes","wrapped")
        assert sync(a)
        raw=json.loads(service.rows[TEST_SID]["blob"])
        assert raw["envelope"]==12 and raw["data"]["futureSibling"]
        assert service.leaf()["prefs"]["futurePref"]=="keep"
        assert all("attachments" not in r and "localFiles" not in r for r in service.leaf()["items"])
        assert "QQ==" in a.evaluate("TASK.items().find(t=>t.id==="+json.dumps(y)+").attachments")
        # Unknown/invalid structures cannot be acknowledged as an empty row.
        good=deepcopy(service.rows[TEST_SID])
        for corrupt in ["{", "null", '{"items":[{"id":"r"},{"id":"r"}]}', ""]:
            service.rows[TEST_SID]["blob"]=corrupt
            before=service.writes()
            assert not sync(a) and service.writes()==before
            assert "异常" in a.evaluate("TASKSYNC.state().status")
        service.rows[TEST_SID]=good
        assert sync(a)
        # Two imports of the same homework keep the confirmed task ID. Completing/removing a copy leaves the source alone.
        assert sync(b)
        hw=json.dumps({"id":"hw-fixture","subject":"合成","content":"作业","date":"2030-12-03"})
        a.evaluate("TASK.addFromHW("+hw+")")
        hold_write(a)
        b.evaluate("TASK.addFromHW("+hw+")")
        assert sync(b)
        a.evaluate("release()")
        wait(a,"TASKSYNC.state().status==='已同步'")
        imported=[r for r in service.leaf()["items"] if r.get("sourceHwId")=="hw-fixture"]
        assert len(imported)==1
        task_id=json.dumps(imported[0]["id"])
        b.evaluate("TASK.complete("+task_id+")")
        assert sync(b)
        assert any(r["id"]==imported[0]["id"] and r["done"] for r in service.leaf()["items"])
        b.evaluate("TASK.open("+task_id+")")
        click(b,"#tkFDelete")
        assert sync(b) and sync(a)
        assert not a.evaluate("TASK.linkedHW('hw-fixture')")
        # Noncanonical acknowledgements require a readback. A denied write remains visibly pending.
        quick(a,"bad-ack")
        a.evaluate("window.fake=r=>r.method==='PATCH'?new Response('[{}]'):null")
        count=len(service.requests)
        assert sync(a)
        assert [r["method"] for r in service.requests[count:]]==["GET","PATCH","GET"]
        a.evaluate("window.fake=null;window.fail=r=>r.method==='GET'")
        quick(a,"offline-kept")
        assert not sync(a)
        a.evaluate("window.fail=null; window.fake=r=>r.method==='GET'?new Response('[]',{status:403}):null")
        assert not sync(a) and "无权限" in a.evaluate("TASKSYNC.state().status")
        a.evaluate("window.fake=null;window.dispatchEvent(new Event('online'))")
        wait(a,"TASKSYNC.state().status==='已同步'")
        # Old responses after switching token/owner cannot acknowledge, reject or replace the new local view.
        for token,sid in [("fixture-rotate",TEST_SID),("fixture-b","9999000012")]:
            a.evaluate("window.hold=r=>r.method==='GET';void TASKSYNC.pull(true)")
            wait(a,"typeof window.release==='function'")
            a.evaluate("window.oldRelease=release;var i=JSON.parse(localStorage.zq_class_identity);"+
                "Object.assign(i,{sid:"+json.dumps(sid)+",token:"+json.dumps(token)+"});"+
                "fixtureEnterClass(i);TASKSYNC.boot()")
            wait(a,"TASKSYNC.state().sid==="+json.dumps(sid)+"&&!TASKSYNC.state().status.includes('同步中')")
            a.evaluate("oldRelease()")
            if sid!=TEST_SID:
                assert a.evaluate("TASK.items().length")==0
        quick(a,"owner-B-only")
        assert sync(a)
        assert [r["title"] for r in service.leaf("9999000012")["items"]]==["owner-B-only"]
        # A timestamp-only old cache is preserved for review. Merely reading the latest cloud row uploads nothing.
        legacy={"items":[{"id":"old-local","title":"local-only","createdAt":1,"updatedAt":1}],"lists":[]}
        seed="if(!sessionStorage.seeded){sessionStorage.seeded='1';localStorage.setItem(" +json.dumps("zq_tools_v2_"+TEST_SID)+",JSON.stringify({task:"+json.dumps(legacy)+"}));localStorage.setItem("+json.dumps("zq_task_cloud_"+TEST_SID)+",JSON.stringify({ts:2}));}"
        count=service.writes()
        old_page=open_page("127.0.0.1",seed="localStorage.removeItem('zq_class_identity');localStorage.zq_class_identity=JSON.stringify({...owner,ts:Date.now()});"+seed)
        wait(old_page,"document.querySelector('#tkCloud button')!==null")
        assert old_page.evaluate("JSON.parse(localStorage["+json.dumps("zq_task_cloud_"+TEST_SID)+"]).legacy.items[0].id")== "old-local"
        assert service.writes()==count and not old_page.evaluate("TASK.items().some(t=>t.id==='old-local')")
        # An existing versioned empty row is a real row. Its next explicit edit must use PATCH.
        empty={"id":TEST_SID,"ts":service.rows[TEST_SID]["ts"]+1,"blob":json.dumps({"v":1,"items":[],"lists":[]})}
        service.rows[TEST_SID]=empty
        assert sync(old_page) and old_page.evaluate("TASK.items().length")==0
        quick(old_page,"after-empty")
        assert sync(old_page) and service.requests[-1]["method"]=="PATCH"
        # A mixed legacy unconditional overwrite can move ts backwards. A clean reader takes the visible row as-is.
        service.rows[TEST_SID]={"id":TEST_SID,"ts":1,"blob":json.dumps({"v":1,"items":[{"id":"old-writer","title":"legacy","createdAt":1}]})}
        assert sync(old_page) and old_page.evaluate("TASK.items()[0].id")== "old-writer"
        old_page.close()
        # Screenshot the visible task page at each actual viewport.
        for width in (390,430,1100):
            b.set_device(width,860,1,width<500)
            b.evaluate("__diag.gotoTab('hw');TASK.setSeg('my')")
            assert b.evaluate("document.documentElement.scrollWidth===innerWidth")
            screenshot(b,directory,f"task-{width}")
        assert not a.evaluate("jsErrors") and not b.evaluate("jsErrors")
        print("PASS V05: paired browsers, insert/PATCH races, field rebase, remote delete, unsaved editor, in-flight edit, homework source, attachments, session rotation, two owners, four retries and recovered acknowledgements")
        print("Confirmed mock rows",len(service.rows),"conditional collisions",service.collisions,"writes",service.writes(),"JS errors 0")
    check_absence(html)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir",type=Path)
    check(parser.parse_args().evidence_dir)
