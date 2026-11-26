"""Run a private Drop conversion on loopback. See drop/CONTRACT.md §9 for the client protocol."""
import argparse
import hashlib
import io
import json
import os
import secrets
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import requests
from pptx import Presentation
from pypdf import PdfReader, PdfWriter

WEB=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(WEB/"tools/tests"),str(WEB/"ppt"),str(WEB/"deploy")]
from _test_account import TEST_NAME, TEST_SID, assert_test_identity
from drop_queue import DropQueue

OWNER="w05-owner-device-1"
PEER="w05-owner-device-2"
OTHER="w05-other-device"
OTHER_SID="9999000003"
MIME="application/vnd.openxmlformats-officedocument.presentationml.presentation"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_bytes():
    slides=Presentation()
    slides.core_properties.author="ClassTools QA"
    slides.core_properties.last_modified_by="ClassTools QA"
    for title in ["W05 source page one","W05 source page two"]:
        slide=slides.slides.add_slide(slides.slide_layouts[0])
        slide.shapes.title.text=title
    raw=io.BytesIO()
    slides.save(raw)
    normalized=io.BytesIO()
    with zipfile.ZipFile(raw) as original, zipfile.ZipFile(normalized,"w") as out:
        for name in sorted(original.namelist()):
            member=zipfile.ZipInfo(name,(2020,1,1,0,0,0))
            member.compress_type=zipfile.ZIP_DEFLATED
            out.writestr(member,original.read(name))
    return normalized.getvalue()


class Space:
    def __init__(self,base):
        self.base=base
        self.client=requests.Session()
        self.client.trust_env=False

    def request(self,method,path,token=PEER,expected=200,**kwargs):
        url=path if path.startswith(self.base+"/") else self.base+path
        result=self.client.request(method,url,headers={"X-Device-Id":token},timeout=15,allow_redirects=False,**kwargs)
        assert result.status_code==expected,(method,path.split("?")[0],result.status_code,expected)
        return result

    def upload(self,session,name,data,mime):
        opened=self.request("POST","/upload/init",OWNER,json={"sessionId":session,"name":name,"size":len(data),"mime":mime,"totalChunks":1}).json()
        uid=opened["uploadId"]
        self.request("POST",f"/upload/chunk?uploadId={uid}&index=0",OWNER,data=data)
        return self.request("POST","/upload/finish",OWNER,json={"sessionId":session,"uploadId":uid}).json()["file"]

    def state(self,sid,ppt=True):
        return self.request("GET",f"/state?sessionId={sid}&all=1&since=0"+("&ppt=1" if ppt else "")).json()

    def detail(self,sid,fid):
        return self.request("GET",f"/ppt/{fid}?sessionId={sid}").json()


def fake_conversion(queue,job,path):
    work,claim,_=queue.claim(job)
    compat=Presentation(str(path/"source.pptx"))
    compat.core_properties.title="fixture compatibility output"
    compat.save(path/"compat.pptx")
    pdf=PdfWriter()
    for _ in compat.slides: pdf.add_blank_page(720,405)
    pdf.write(str(path/"preview.pdf"))
    artifacts={}
    for key,name in (("compat","compat.pptx"),("pdf","preview.pdf")):
        item=path/name
        queue.upload(work,claim,key,str(item))
        artifacts[key]={"name":name,"size":item.stat().st_size,"pages":2}
    queue.update(work,claim,"ready",artifacts=artifacts)


def run(args):
    assert_test_identity(TEST_SID)
    assert_test_identity(OTHER_SID)
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=True)
    # All working keys and files belong to this fresh directory, including import-time defaults.
    with tempfile.TemporaryDirectory(prefix="classtools-drop-w05-") as temp, ExitStack() as stack:
        root=Path(temp)
        worker=secrets.token_hex(32)
        key=root/"worker.test"
        key.write_text(worker,encoding="ascii")
        stack.enter_context(patch.dict(os.environ,{"DROP_ROOT":str(root/"store"),"DROP_PORT":"0","DROP_PUBLIC_BASE":"",
            "DROP_PUBLIC_PREFIX":"/drop","DROP_PUBLISH_KEY":"fixture-public","DROP_GATEWAY":"http://127.0.0.1:9/",
            "DROP_PPT_WORKER_KEY_FILE":str(key)}))
        import drop_app as app
        assert Path(app.ROOT)==root/"store" and app.PPT_WORKER_KEY==worker
        def validate(token):
            if token not in (OWNER,PEER,OTHER):raise app.AuthError(401,"测试身份无效")
            return {"sid":OTHER_SID if token==OTHER else TEST_SID,"name":TEST_NAME,"seat":1}
        stack.enter_context(patch.object(app,"validate_token",validate))
        stack.enter_context(patch.object(app,"log",lambda *a,**kw: None))
        if args.web:
            from conversion_web_check import with_fixture_page
            stack.enter_context(patch.object(app,"Handler",with_fixture_page(app.Handler,WEB,OWNER,PEER)))
        server=app.make_server("127.0.0.1",args.port)
        stack.callback(server.server_close)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        stack.callback(server.shutdown)
        endpoint=f"http://127.0.0.1:{server.server_port}/drop"
        space=Space(endpoint)
        stack.callback(space.client.close)
        original=source_bytes()
        (out/"source.pptx").write_bytes(original)
        plain=b"ClassTools loopback plain file\n"
        (out/"ordinary.txt").write_bytes(plain)
        session=space.request("POST","/open",OWNER,json={}).json()["session"]["id"]
        browser_done=None
        if args.web:
            from conversion_web_check import web_sender
            browser_done=stack.enter_context(web_sender(endpoint,out))
        else:
            space.upload(session,"source.pptx",original,MIME)
            space.upload(session,"ordinary.txt",plain,"text/plain")
        ready=space.state(session)
        files={f["name"]:f for f in ready["files"]}
        fid=files["source.pptx"]["id"]
        assert ready["pptConversion"] is True
        legacy=space.state(session,False)
        assert "pptConversion" not in legacy and all("conversion" not in f for f in legacy["files"])
        assert space.request("GET",files["ordinary.txt"]["downloadUrl"]).content==plain
        path="/ppt/"+fid
        body={"sessionId":session}
        if not args.web:space.request("POST",path,OWNER,json=body)
        duplicate=space.request("POST",path,PEER,json=body).json()
        assert duplicate["conversion"]["attempt"]==1
        snapshots={"queued":space.detail(session,fid)}
        assert snapshots["queued"]["conversion"]["status"]=="queued"
        queue=DropQueue(endpoint,worker)
        queue.http.trust_env=False
        stack.callback(queue.http.close)
        job=queue.next()
        route,claim,_=queue.claim(job)
        snapshots["processing"]=space.detail(session,fid)
        queue.update(route,claim,"failed",error="合成可重试失败")
        snapshots["failed"]=space.detail(session,fid)
        space.request("POST",path,json=dict(body,retryAttempt=2))
        assert space.detail(session,fid)["conversion"]["attempt"]==1
        second=space.request("POST",path,json=dict(body,retryAttempt=1)).json()
        assert second["conversion"]["attempt"]==2
        job=queue.next()
        if args.office:
            import agent
            with patch.object(agent,"WORK_DIR",str(root/"office")):
                receipt=agent.run_drop_job(queue,job,lambda msg:print(msg,flush=True),"fixture-office")
            assert receipt["action"]=="converted",receipt
        else:
            fake_conversion(queue,job,out)
        snapshots["ready"]=space.detail(session,fid)
        detail=snapshots["ready"]
        manifest=detail["manifest"]
        assert detail["conversion"]["status"]=="ready" and detail["conversion"]["attempt"]==2
        assert set(manifest["files"])=={"compat","pdf"} and not manifest["media_files"]
        assert "browserProof" not in detail
        space.request("GET",path+"?sessionId="+session,OTHER,403)
        assert space.request("GET",files["source.pptx"]["downloadUrl"]).content==original
        artifacts={"source.pptx":sha(original)}
        for kind,item in manifest["files"].items():
            space.request("GET",item["s"],OTHER,403)
            data=space.request("GET",item["s"]).content
            assert len(data)==item["size"]
            filename="result.pptx" if kind=="compat" else "result.pdf"
            (out/filename).write_bytes(data)
            artifacts[filename]=sha(data)
            if kind=="compat":
                assert [s.shapes.title.text for s in Presentation(io.BytesIO(data)).slides]==["W05 source page one","W05 source page two"]
            else:
                pdf=PdfReader(io.BytesIO(data))
                assert len(pdf.pages)==2
                if args.office:assert all("W05 source page" in page.extract_text() for page in pdf.pages)
        if browser_done:browser_done(fid)
        snapshots["stateV25"]=legacy
        snapshots["stateV26"]=space.state(session)
        # Result URLs expire on a controlled fixture clock; a fresh detail call re-signs the same artifact.
        real_now=app._now_ms()
        with patch.object(app,"_now_ms",return_value=real_now+(app.URL_TTL_SEC+2)*1000):
            for item in manifest["files"].values():space.request("GET",item["s"],expected=403)
            fresh=space.detail(session,fid)["manifest"]["files"]["pdf"]["s"]
            assert sha(space.request("GET",fresh).content)==artifacts["result.pdf"]
        fixture={"base":endpoint,"sessionId":session,"fileId":fid,"ordinaryFileId":files["ordinary.txt"]["id"],
            "mode":"office" if args.office else "fixture-worker","twoDevices":[OWNER,PEER],"otherAccount":OTHER,
            "sha256":artifacts,"responses":snapshots}
        (out/"fixture.json").write_text(json.dumps(fixture,ensure_ascii=False,indent=2),encoding="utf8")
        print("READY",endpoint,session,fid,artifacts,flush=True)
        if args.keep_seconds:time.sleep(args.keep_seconds)
        space.request("DELETE","/file/"+fid+"?sessionId="+session,OWNER)
        for item in manifest["files"].values():space.request("GET",item["s"],expected=404)
        space.request("GET",files["source.pptx"]["downloadUrl"],expected=404)
        assert all(f["id"]!=fid for f in space.state(session)["files"])
        assert space.request("GET",files["ordinary.txt"]["downloadUrl"]).content==plain
        with patch.object(app,"_now_ms",return_value=real_now+(app.TTL_SEC-60)*1000):
            space.request("POST","/open",OWNER,json={})
        with patch.object(app,"_now_ms",return_value=real_now+(app.TTL_SEC+1)*1000):
            expired=space.state(session)
            assert all(f["id"]!=files["ordinary.txt"]["id"] for f in expired["files"])
        print("PASS original hash, two attempts, signed result access, isolated delete, TTL and Office-readable artifacts")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--office",action="store_true",help="Convert the local queue with installed PowerPoint COM")
    parser.add_argument("--web",action="store_true",help="Upload/submit in Web and retrieve from a second Web browser store")
    parser.add_argument("--port",type=int,default=0)
    parser.add_argument("--keep-seconds",type=int,default=0,help="Keep this initialized fixture open for native client QA")
    run(parser.parse_args())
