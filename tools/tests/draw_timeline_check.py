"""W04 authenticated draw mutations, receipts, proof replay and export on loopback."""
import argparse
import hashlib
import json
from pathlib import Path

from sync_browser_fixture import browser_fixture, click, screenshot, wait


class DrawService:
    tables = ["draw_record_create", "draw_record_get", "draw_event_append", "draw_record_list", "auth_ok"]
    def __init__(self):
        self.records = {}
        self.appends = 0

    def __call__(self, req):
        assert req["token"] == "fixture-a"
        name, body = req["table"], req["body"]
        if name == "auth_ok":
            return 200, True, {}
        if name == "draw_record_list":
            return 200, {"ok":True,"rows":[],"today_count":len(self.records)}, {}
        key = body["p_id"]
        if name == "draw_record_create":
            if key not in self.records:
                record = {k[2:]:v for k,v in body.items()}
                canon = "\n".join([key,record["seed"],json.dumps(record["result"])])
                record.update(at=1700000000000,day="2026-11-27",seq_day=1,today_count=1,
                    event_count=0,events=[],canon=canon,hash=hashlib.sha256(canon.encode()).hexdigest())
                self.records[key] = record
        rec = self.records[key]
        if name == "draw_event_append":
            self.appends += 1
            seq = rec["event_count"] + 1
            ev = dict(seq=seq, kind=body["p_kind"], n=body["p_n"], added=body["p_added"])
            rec["events"].append(ev)
            rec["event_count"] = seq
            return 200, dict(ok=True,event_count=seq,event=ev), {}
        return 200, {"ok":True,"record":rec}, {}


def main(out):
    service=DrawService()
    with browser_fixture(service) as open_page:
        page=open_page()
        run=page.evaluate
        run("window.__diag.gotoTab('draw');window.hold=r=>r.table==='draw_record_create';")
        click(page,"#aRun")
        wait(page,"!!window.release")
        original=run("DRAWPROOF.state().result")
        click(page,"#aOut [data-rm]")
        assert original == run("DRAWPROOF.state().result") and not service.appends
        run("release();")
        wait(page,"DRAWPROOF.state().proof?.status==='ok'")
        rid=run("DRAWPROOF.state().proof.id")
        run("window.lose=r=>r.table==='draw_event_append';")
        click(page,"#aOut [data-rm]")
        wait(page,"DRAWPROOF.state().proof?.record.event_count===1")
        assert service.appends==1
        assert original[0] == service.records[rid]["events"][0]["n"]
        click(page,'#aSortRow [data-asort="asc"]')
        assert service.appends==1
        click(page,"#aImg")
        wait(page,"window.__lastDrawExport?.rec===DRAWPROOF.state().proof.id")
        assert run("__lastDrawExport.qr.includes("+json.dumps(rid)+")")
        run("window.__lastDrawExport=null;")
        click(page,"#aImg")
        wait(page,"window.__lastDrawExport?.rec===DRAWPROOF.state().proof.id")
        run("DRAWPROOF.openVerify("+json.dumps(rid)+");")
        wait(page,"document.querySelector('#recReplay')?.classList.contains('ok')&&document.querySelector('#recHash')?.classList.contains('ok')")
        run("window.fail=r=>r.table==='draw_event_append'||r.table==='draw_record_get';")
        click(page,"#aOut [data-rm]")
        wait(page,"!!document.querySelector('#aEventCheck')")
        for i in range(2):
            click(page,"#aEventCheck")
        run("window.__lastDrawExport=null;")
        click(page,"#aImg")
        wait(page,"window.__lastDrawExport?.rec===DRAWPROOF.state().proof.id")
        assert not run("__lastDrawExport.qr")
        assert "未确认" in run("JSON.stringify(__lastDrawExport.config)")
        assert service.appends==1
        print("pending remove blocked; lost ACK reconciled once; sort, two verified exports and replay/hash passed")
        for width in (390,430,1100):
            page.set_device(width,850,1,width<600)
            wait(page,f"innerWidth==={width}")
            run("document.querySelector('#recModal').style.display='none';window.__diag.gotoTab('draw');")
            assert run("document.documentElement.scrollWidth") == width
            screenshot(page,out,f"draw-unknown-{width}")
        run("window.fail=null;")
        click(page,"#aRun")
        wait(page,"DRAWPROOF.state().proof?.status==='ok'&&DRAWPROOF.state().proof.id!=="+json.dumps(rid))
        second=run("DRAWPROOF.state().proof.id")
        run("window.lose=r=>r.table==='draw_event_append';")
        click(page,"#aReset")
        wait(page,"DRAWPROOF.state().result===null")
        assert service.records[second]["events"][0]["kind"] == "reset" and service.appends==2
        run("window.fail=r=>r.table==='draw_record_create'")
        click(page,"#aRun")
        wait(page,"DRAWPROOF.state().proof?.status==='failed'")
        click(page,"#aImg")
        wait(page,"window.__lastDrawExport?.rec===DRAWPROOF.state().proof.id")
        assert not run("__lastDrawExport.qr")
        assert not run("window.jsErrors"),run("window.jsErrors")
        print("unconfirmed and offline export labeled, repeated read adds no event, new ID and reset confirmed, no JS errors")
        page.close()


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--artifacts",type=Path)
    main(ap.parse_args().artifacts)
