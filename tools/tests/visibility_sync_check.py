"""V02/V06 check the authenticated roster, marks snapshots and notification detail lifecycle."""
import argparse
import json
from pathlib import Path

from _test_account import TEST_SID
from sync_browser_fixture import HERE, browser_fixture, screenshot, wait


class VisibilityService:
    tables=["class_members","marks","class_notices_meta","notices","auth_ok"]
    def __init__(self):
        self.role="合成班委"
        self.hidden=False
        self.archived=False
        self.admin_only=False
        self.edits=0
        self.legacy_notices=False
        self.break_notices=False
        self.override={}
        self.partial=False
        self.break_marks=False
        self.self_admin=True
        self.log=[]

    def row(self,lite):
        group={"id":"qa-g","title":"合成通知","cat":"测试","items":[{"type":"image","lazy":lite,
            "url":"" if lite else "data:image/png;base64,cWE="}]}
        return dict(id="qa-row",title="合成通知",ts=111,body="[[CLASS_NOTICE_V1]]"+json.dumps(group,ensure_ascii=False),
            hidden=self.hidden,archived=self.archived,edited_at=self.edits,override_json=json.dumps(self.override,ensure_ascii=False))

    def __call__(self,r):
        token=r.get("token")
        assert token in ("fixture-a","qa-admin","qa-member"),token
        is_admin=token=="qa-admin" or (token=="qa-member" and self.self_admin)
        table=r["table"]
        self.log.append((token,table,r["method"]))
        if table=="auth_ok": return 200,True,{}
        if table=="class_members":
            rows=[{"seat":i,"sid":"9999"+str(i).zfill(6),"name":"合成成员"+str(i),
                   "role":self.role if i==1 else "","is_admin":False} for i in range(1,7)]
            if token=="qa-member":
                rows[0].update(role="管理员" if self.self_admin else "成员",is_admin=self.self_admin)
            if self.partial:return 206,rows[:2],{"Content-Range":"0-1/6"}
            return 200,rows,{}
        if table=="marks":
            sid="9999000001" if token=="qa-member" else TEST_SID
            data=[dict(id=sid+"|hw|m"+str(i),seat=sid,kind="hw",ref="m"+str(i),val=True) for i in range(7)]
            offset=int((r.get("range") or "0-499").split("-")[0])
            if self.break_marks and offset>0:return 503,{},{}
            taken=data[offset:offset+3]
            return 206 if len(taken)<len(data) else 200,taken,{"Content-Range":f"{offset}-{offset+len(taken)-1}/{len(data)}"}
        if r["method"]=="PATCH":
            if not is_admin:return 403,{},{}
            self.override=json.loads(r["body"].get("override_json") or "{}")
            self.edits+=1
            return 200,[self.row(False)],{}
        if self.archived or (self.admin_only and not is_admin):return 200,[],{}
        if self.legacy_notices and table=="class_notices_meta":return 404,{},{}
        if self.legacy_notices and table=="notices" and "id" not in r["query"]:
            rows=[dict(self.row(False),id="qa-manual-"+str(i),body="合成正文",title="合成条目"+str(i)) for i in range(5)]
            offset=int((r.get("range") or "0-499").split("-")[0])
            if self.break_notices and offset>0:return 503,{},{}
            taken=rows[offset:offset+2]
            return 206,taken,{"Content-Range":f"{offset}-{offset+len(taken)-1}/{len(rows)}"}
        return 200,[self.row(table=="class_notices_meta")],{}


def main(out):
    src=(HERE.parent/"index.html").read_bytes()
    needle=b"function enterClass(r){"
    hook=b"window.scopeQA={D,NT,HW,enterClass,membersPull,marksPull,noticeAdminEdit,canManage,owner:()=>syncOwner(),groups:()=>AUTO_NOTICES,hidden:()=>NT_HIDDEN};"
    service=VisibilityService()
    with browser_fixture(service,src.replace(needle,hook+needle)) as open_page:
        page=open_page()
        run=page.evaluate
        def call(expr):return run(expr,True)
        wait(page,"scopeQA.D.d.members.length===6")
        assert call("scopeQA.membersPull(true)")
        service.partial=True
        call("scopeQA.membersPull(true).catch(()=>false)")
        assert len(run("scopeQA.D.d.members"))==6, "partial roster replaced valid snapshot"
        service.partial=False
        # Capture a genuine response; deliver it only after the next refresh was applied.
        run("""const origFetch=window.fetch;window.fetch=async(u,o)=>{const resp=await origFetch(u,o);
        if(window.afterPredicate&&afterPredicate(String(u),o||{})){window.afterPredicate=null;
        await new Promise(r=>window.afterRelease=r);window.afterRelease=null;}return resp;};""")
        run("window.afterPredicate=u=>u.includes('class_members');window.oldRoster=scopeQA.membersPull(true);void 0")
        wait(page,"!!window.afterRelease")
        service.role="新角色"
        assert call("scopeQA.membersPull(true)")
        call("afterRelease();oldRoster")
        assert run("scopeQA.D.d.members[0].role")=="新角色"
        assert run("scopeQA.D.d.members[0].seat===1&&scopeQA.D.d.members[0].sid==='9999000001'")
        run("scopeQA.owner().forceAt=0;")
        call("scopeQA.marksPull(true)")
        assert len(run("Object.keys(scopeQA.HW.marks)"))==7
        service.break_marks=True
        run("scopeQA.owner().forceAt=0;")
        call("scopeQA.marksPull(true)")
        assert len(run("Object.keys(scopeQA.HW.marks)"))==7
        service.break_marks=False
        # An additional synthetic roster member changes permissions without obtaining a new token.
        member=open_page(host="localhost",sid="9999000001",token="qa-member")
        wait(member,"scopeQA.canManage()")
        service.self_admin=False
        member.evaluate("scopeQA.membersPull(true)",True)
        wait(member,"!scopeQA.canManage()&&scopeQA.owner().role==='成员'")
        member.close()
        print("V02 roster role/reordering/partial responses and paged marks, failed page retains snapshot: PASS")

        call("scopeQA.NT.pull(true)")
        assert run("scopeQA.groups()[0].items[0].lazy===true")
        assert not call("scopeQA.noticeAdminEdit('qa-g',{title:'无权'})")
        run("window.afterPredicate=(u,o)=>u.includes('notices?select=*&id=eq.');window.oldFile=scopeQA.NT.loadBody('qa-g').then(()=>true,()=>false);void 0")
        wait(page,"!!window.afterRelease")
        service.admin_only=True
        call("scopeQA.NT.pull(true)")
        assert not run("scopeQA.groups().length")
        assert not call("afterRelease();oldFile"),"late body still delivered after audience removal"
        identity=dict(sid=TEST_SID,token="qa-admin",is_admin=True,role="管理员",name="测试账号")
        run("scopeQA.enterClass("+json.dumps(identity)+");")
        call("scopeQA.NT.pull(true)")
        assert run("scopeQA.canManage()")
        assert call("scopeQA.noticeAdminEdit('qa-g',{title:'合成修订'})")
        call("scopeQA.NT.pull(true)")
        assert run("scopeQA.groups()[0].title")=="合成修订"
        full=call("scopeQA.NT.loadBody('qa-g')")
        assert full["title"]=="合成修订" and full["items"][0]["url"].startswith("data:")
        assert call("scopeQA.noticeAdminEdit('qa-g',{title:null})")
        service.hidden=True
        call("scopeQA.NT.pull(true)")
        assert not run("scopeQA.groups().length") and len(run("scopeQA.hidden()"))==1
        identity.update(token="fixture-a",is_admin=False,role="")
        run("scopeQA.enterClass("+json.dumps(identity)+");")
        call("scopeQA.NT.pull(true)")
        assert not run("scopeQA.canManage()||scopeQA.groups().length||scopeQA.hidden().length")
        service.hidden=False;service.admin_only=False;service.archived=True
        call("scopeQA.NT.pull(true)")
        assert not call("scopeQA.NT.loadBody('qa-g').then(()=>true,()=>false)")
        service.archived=False;service.legacy_notices=True
        call("scopeQA.NT.pull(true)")
        assert len(run("scopeQA.D.d.notices"))==5
        service.break_notices=True
        call("scopeQA.NT.pull(true)")
        assert len(run("scopeQA.D.d.notices"))==5
        page.evaluate("__diag.gotoTab('nt')")
        screenshot(page,out,"notification-after-revocation")
        assert not run("window.jsErrors"),run("window.jsErrors")
        print("V06 lite + lazy attachment, audience revocation while reading, role, edited/cleared override, hidden and archive: PASS")
        page.close()


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--artifacts",type=Path)
    main(p.parse_args().artifacts)
