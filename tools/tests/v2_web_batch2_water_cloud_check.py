"""V09: shared water UI, scoped offline intent and readback using the W07 synthetic fixtures."""
import argparse
import json
from pathlib import Path

from _test_account import TEST_SID
from sync_browser_fixture import browser_fixture, click, screenshot, wait

HERE=Path(__file__).resolve().parent
CASES=json.loads((HERE/"water_shared_v2_cases.json").read_text(encoding="utf8"))
JOURNEY=CASES["journey"]
R,S=JOURNEY["rooms"]
MONTH,NEXT=JOURNEY["month"],JOURNEY["nextMonth"]


class WaterService:
    tables=["auth_ok","class_whoami","water","water_room"]

    def __init__(self):
        self.rows={}
        self.rooms={}
        self.tokens={"fixture-a":TEST_SID,"fixture-b":"9999000012","fixture-rotate":TEST_SID}
        self.requests=[]
        self.fail=set()

    def __call__(self,req):
        self.requests.append(req)
        table=req["table"].split("/")[-1]
        token,method,query=req["token"],req["method"],req["query"]
        sid=self.tokens.get(token)
        if table=="auth_ok": return 200,bool(sid),{}
        if table=="class_whoami": return 200,{"sid":sid} if sid else {},{}
        if table in self.fail: return 503,{},{}
        rv=query.get("roomverify","")[3:]
        if method=="GET":
            assert rv
            data=[r for (room,month),r in sorted(self.rows.items()) if room==rv] if table=="water" else (
                [{"roomverify":rv,"persons":self.rooms[rv]}] if rv in self.rooms else [])
            data=data if sid else []
            start,limit=int(query.get("offset",0)),int(query.get("limit",100))
            part=data[start:start+limit]
            span=f"{start}-{start+len(part)-1}" if part else "*"
            return 200,part,{"Content-Range":f"{span}/{len(data)}"}
        if not sid:return 403,{},{}
        if method=="DELETE":
            assert table=="water" and rv and query["month"].startswith("eq.")
            self.rows.pop((rv,query["month"][3:]),None)
        else:
            assert method=="POST" and "resolution=merge-duplicates" in req["prefer"] and "return=minimal" in req["prefer"]
            body=req["body"]
            if isinstance(body,list):body,=body
            assert int(body["persons"]) in range(1,7)
            if table=="water":
                assert query["on_conflict"]=="roomverify,month"
                self.rows[body["roomverify"],body["month"]]=dict(body)
            else:
                assert table=="water_room" and query["on_conflict"]=="roomverify"
                self.rooms[body["roomverify"]]=int(body["persons"])
        return 200,[],{}

    def writes(self):
        return len([r for r in self.requests if r["method"]!="GET" and r["table"] in ("water","water_room")])


def water_html():
    source=(HERE.parent/"index.html").read_bytes()
    # Test-only catalog and login entry, so a real room is never selected.
    tag=b"  WATER.shared=B2WATER;"
    inject="""
  PW_BLDS=['Fixture'];PW_ROOMS=RV.map(rv=>({rv,label:rv,building:'Fixture'}));POWER.init();
  window.fixtureWater={select:WATER.pickRoom,recs:WATER.recs,privateData:()=>D.d.water,
    chooseSession:enterClass,cost:WATER.cost,summary:()=>document.querySelector('#opt2WaterSum').click()};
""".replace("RV",json.dumps([R,S]))
    assert tag in source
    return source.replace(tag,tag+inject.encode(),1)


def choose(page,room):
    page.evaluate("__diag.gotoTab('water')")
    page.evaluate("var select=document.querySelector('#wtSel');select.value="+json.dumps(room)+";select.dispatchEvent(new Event('change'))")


def pull(page,room=R):
    return page.evaluate("__B2.water.pullRoom("+json.dumps(room)+",true)",True)


def flush(page):
    return page.evaluate("__B2.water.flush()",True)


def save(page,m,r):
    page.evaluate("document.querySelector('#wtMonth').value="+json.dumps(m)+";document.querySelector('#wtReading').value="+json.dumps(str(r)))
    click(page,"#wtSave")


def persons(page,p):
    page.evaluate("var people=document.querySelector('#wtPersons');people.value="+json.dumps(str(p))+";people.dispatchEvent(new Event('change'))")


def listed(page):
    return page.evaluate("Array.from(document.querySelectorAll('#wtList [data-wdel]'),b=>b.dataset.wdel).sort()")


def wait_idle(page):
    wait(page,"__B2.water.status().pending===0&&document.querySelector('#wtSync').textContent.includes('共享已同步')")


def check(directory=None):
    svc=WaterService()
    # Build the original account-owned private cache and an ambiguous old pending operation.
    private={"water":{"rooms":{R:{"p":4,"recs":[{"m":"2029-12","r":8,"ts":1}]}}}}
    seed="localStorage.setItem("+json.dumps("zq_tools_v2_"+TEST_SID)+","+json.dumps(json.dumps(private))+");"
    seed+="localStorage.setItem("+json.dumps("zq_water_pend_"+TEST_SID)+","+json.dumps(json.dumps([{"id":"old","k":"save","rv":R,"m":"2029-10","r":4,"p":4}]))+");"
    def row(m,r,p=3):return {"roomverify":R,"month":m,"reading":r,"persons":p}
    svc.rooms[R]=JOURNEY["serverPersons"]
    with browser_fixture(svc,water_html()) as open_page:
        a=open_page(seed=seed)
        b=open_page("localhost","9999000012","fixture-b")
        for page in (a,b):
            choose(page,R);assert pull(page)
            assert page.evaluate("document.querySelector('#wtPersons').value")=="3"
        assert not listed(a) and not listed(b) and svc.writes()==0
        assert "个人旧记录" in a.evaluate("document.querySelector('#wtReviewRows').textContent")
        assert a.evaluate("fixtureWater.privateData().rooms["+json.dumps(R)+"].recs.length")==1
        assert not b.evaluate("document.querySelector('#wtReviewRows').textContent")
        a.set_device(390,860,1,True)
        a.evaluate("document.querySelector('#wtReview').open=true")
        screenshot(a,directory,"water-history-390")
        # Reject ambiguous legacy backfill. The original private ledger remains available for explicit import.
        a.evaluate("[...document.querySelectorAll('#wtReviewRows button')].find(b=>b.textContent==='采用共享值').click()")
        assert svc.writes()==0
        save(a,MONTH,12.34);wait_idle(a);assert pull(b) and listed(b)==[MONTH]
        persons(a,5);wait_idle(a);assert pull(b)
        assert b.evaluate("document.querySelector('#wtPersons').value")=="5"
        for p in CASES["persons"]["valid"]:
            persons(a,p);wait_idle(a)
            assert svc.rooms[R]==p
        persons(a,3);wait_idle(a)
        click(a,"[data-wdel='"+MONTH+"']");wait_idle(a)
        writes=svc.writes()
        b.evaluate("window.dispatchEvent(new Event('online'))")
        assert flush(b) and listed(b)==[] and svc.writes()==writes
        assert b.evaluate("fixtureWater.recs("+json.dumps(R)+").length")==0
        # Offline explicit create after a known absence can be replayed once.
        b.evaluate("window.fail=r=>r.table==='water'||r.table==='water_room'")
        save(b,NEXT,20.5);assert not flush(b)
        assert listed(b)==[NEXT] and svc.writes()==writes
        b.evaluate("window.fail=null;window.dispatchEvent(new Event('online'))")
        wait_idle(b);assert svc.writes()==writes+1 and pull(a) and listed(a)==[NEXT]
        # Delete a row while the other device has an offline edit. Show the shared current value and keep the draft.
        b.evaluate("window.fail=r=>r.table==='water'")
        save(b,NEXT,22);assert not flush(b)
        click(a,"[data-wdel='"+NEXT+"']");wait_idle(a)
        count=svc.writes()
        b.evaluate("window.fail=null")
        flush(b)
        assert not listed(b) and "待核对" in b.evaluate("document.querySelector('#wtReviewRows').textContent")
        assert svc.writes()==count
        b.evaluate("[...document.querySelectorAll('#wtReviewRows button')].find(e=>e.textContent.includes('重新提交')).click()")
        wait_idle(b);assert svc.rows[R,NEXT]["reading"]==22 and svc.writes()==count+1
        # An uncertain response cannot resurrect an intervening delete. Confirm a matching read without a second write.
        b.evaluate("window.lose=r=>r.table==='water'&&r.method==='POST'")
        save(b,MONTH,11);assert not flush(b)
        count=svc.writes()
        assert flush(b) and svc.writes()==count
        b.evaluate("window.lose=r=>r.table==='water'&&r.method==='POST'")
        save(b,MONTH,12);assert not flush(b)
        svc.rows.pop((R,MONTH))
        count=svc.writes();flush(b)
        assert not (R,MONTH) in svc.rows and svc.writes()==count
        b.evaluate("[...document.querySelectorAll('#wtReviewRows button')].find(e=>e.textContent==='采用共享值').click()")
        # Independent remote failures and invalid/partial responses keep the last confirmed resource.
        svc.rooms[R]=6;svc.fail.add("water")
        assert not pull(b) and listed(b)==[NEXT] and b.evaluate("document.querySelector('#wtPersons').value")=="6"
        svc.fail.clear();svc.fail.add("water_room");svc.rows.pop((R,NEXT))
        assert not pull(b) and not listed(b) and b.evaluate("document.querySelector('#wtPersons').value")=="6"
        svc.fail.clear();svc.rows[R,MONTH]=row(MONTH,12);svc.rooms[R]=3;assert pull(b)
        for fake in [
            "new Response('{}')",
            "new Response(JSON.stringify([{roomverify:'another-room',month:'2030-01',reading:1,persons:3}]))",
            "new Response('[]',{headers:{'Content-Range':'*/3'}})",
        ]:
            b.evaluate("window.fake=r=>r.table==='water'&&r.method==='GET'?"+fake+":null")
            assert not pull(b) and listed(b)==[MONTH]
        b.evaluate("window.fake=null")
        for invalid in CASES["persons"]["invalid"]:
            svc.rooms[R]=invalid
            assert not pull(b) and b.evaluate("document.querySelector('#wtPersons').value")=="3"
        svc.rooms.pop(R)
        assert pull(b) and b.evaluate("document.querySelector('#wtPersons').value")=="4"
        persons(b,4);wait_idle(b);assert svc.rooms[R]==4
        # Stale snapshots received after selecting another room cannot modify its UI, queue or cache.
        b.evaluate("window.hold=r=>r.table==='water'&&r.method==='GET';void __B2.water.pullRoom("+json.dumps(R)+",true)")
        wait(b,"typeof release==='function'")
        choose(b,S);assert pull(b,S)
        b.evaluate("release()")
        assert not listed(b) and b.evaluate("document.querySelector('#wtSel').value")==S
        count=svc.writes()
        svc.tokens.pop("fixture-b")
        assert not pull(b,S) and "无权限" in b.evaluate("document.querySelector('#wtSync').textContent")
        assert b.evaluate("document.querySelector('#wtSave').disabled") and svc.writes()==count
        svc.tokens["fixture-b"]="9999000012"
        assert pull(b,S) and not b.evaluate("document.querySelector('#wtSave').disabled")
        # An old unconditional writer can reinsert a record. A new client's refresh accurately reports the backend.
        svc.rows[R,NEXT]=row(NEXT,20)
        choose(b,R);assert pull(b)
        assert listed(b)==[MONTH,NEXT]
        assert b.evaluate("fixtureWater.cost(12,3).fee")==18.18
        a.evaluate("window.canvasTexts=[];const ink=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(t,...r){canvasTexts.push(String(t));return ink.call(this,t,...r)}")
        assert pull(a)
        a.evaluate("fixtureWater.summary()")
        wait(a,"canvasTexts.some(t=>t.includes('本期用水 8.00'))")
        click(a,"[data-wdel='"+NEXT+"']");wait_idle(a)
        a.evaluate("canvasTexts.length=0;fixtureWater.summary()")
        wait(a,"canvasTexts.some(t=>t.includes('缺上期记录 1 间'))")
        assert not any("本期用水 8.00" in t for t in a.evaluate("canvasTexts"))
        assert svc.writes()>=count
        # Read the current shared value before explicitly importing a single item of the private ledger.
        choose(a,R);assert pull(a)
        writes=svc.writes()
        a.evaluate("[...document.querySelectorAll('#wtReviewRows p')].find(p=>p.textContent.includes('2029-12')).querySelector('button').click()")
        wait(a,"calls.some(r=>r.table==='water'&&r.method==='POST'&&r.body.month==='2029-12')")
        wait_idle(a);assert svc.writes()==writes+1 and svc.rows[R,"2029-12"]["reading"]==8
        # A later local save supersedes an in-flight operation, including its delayed acknowledgement.
        a.evaluate("window.hold=r=>r.table==='water'&&r.method==='POST'")
        save(a,"2030-03",30)
        wait(a,"typeof release==='function'")
        save(a,"2030-03",31)
        a.evaluate("release()");wait_idle(a)
        assert svc.rows[R,"2030-03"]["reading"]==31
        # Revoked/stale sessions never apply old results to a new account's UI or pending queue.
        a.evaluate("window.hold=r=>r.table==='water'&&r.method==='GET';void __B2.water.pullRoom("+json.dumps(R)+",true)")
        wait(a,"typeof release==='function'")
        a.evaluate("window.oldRelease=release;fixtureWater.chooseSession({sid:'9999000012',name:'测试账号',token:'fixture-b'});")
        choose(a,S);assert pull(a,S)
        a.evaluate("oldRelease()")
        assert listed(a)==[] and not a.evaluate("document.querySelector('#wtReviewRows').textContent")
        assert svc.rows[R,"2030-03"]["reading"]==31
        # A first offline entry without an observed baseline is retained for confirmation after reopening.
        a.evaluate("window.fail=r=>r.table==='water'")
        choose(a,R)
        # This browser account's R cache has not been populated in this independent storage area.
        save(a,"2030-04",34)
        assert not flush(a)
        a.evaluate("window.oldPageMarker=true;location.reload()")
        wait(a,"!window.oldPageMarker&&document.readyState==='complete'&&window.fixtureWater&&window.__diag")
        choose(a,R);flush(a);wait(a,"document.querySelector('#wtReviewRows').textContent.includes('2030-04')")
        assert (R,"2030-04") not in svc.rows
        # Overlapping same-room reads: the older filtered snapshot cannot replace the accepted later read.
        b.evaluate("window.hold=r=>{if(r.table==='water'&&r.method==='GET'){window.staleRequest=r;return true}};void __B2.water.pullRoom("+json.dumps(R)+",true)")
        wait(b,"typeof release==='function'")
        svc.rows[R,"2030-05"]=row("2030-05",35)
        assert pull(b)
        b.evaluate("window.fake=r=>r===window.staleRequest?new Response('[]',{headers:{'Content-Range':'*/0'}}):null;release()")
        wait(b,"fixtureWater.recs("+json.dumps(R)+").some(x=>x.m==='2030-05')")
        b.evaluate("window.fake=null")
        # Full reads span multiple pages. A broken later page must preserve the last confirmed room.
        svc.rooms[S]=2
        for n in range(105):
            m=f"{2010+n//12}-{n%12+1:02}"
            svc.rows[S,m]={"roomverify":S,"month":m,"reading":n,"persons":2}
        choose(b,S);assert pull(b,S)
        assert len(listed(b))==105
        b.evaluate("window.fake=r=>r.table==='water'&&r.query.offset==='100'?new Response('{}'):null")
        assert not pull(b,S) and len(listed(b))==105
        b.evaluate("window.fake=null")
        # UI and keyboard-accessible history affordances use real CSS sizes.
        for width in (390,430,1100):
            b.set_device(width,860,1,width<500);choose(b,R);assert pull(b)
            wait(b,"innerWidth==="+str(width)+"&&document.documentElement.scrollWidth===document.documentElement.clientWidth")
            print("water viewport / content / scroll",b.evaluate("[innerWidth,document.documentElement.clientWidth,document.documentElement.scrollWidth]"))
            screenshot(b,directory,f"water-{width}")
        assert not a.evaluate("jsErrors") and not b.evaluate("jsErrors")
        print("PASS V09: two authenticated accounts, authoritative deletes and persons 1–6, zero refresh writes, scoped history/queue, retry, lost response, conflict review, auth rejection, room switch and aggregate export")
        print("Shared writes",svc.writes(),"local REST calls",len(svc.requests),"JS errors 0")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir",type=Path)
    check(parser.parse_args().evidence_dir)
