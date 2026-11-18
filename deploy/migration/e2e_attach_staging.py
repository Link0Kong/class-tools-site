# -*- coding: utf-8 -*-
"""附件外置 staging 端到端演练（NOTICE_ATTACH_EXTERNALIZE 的产物形态）。

流程（只碰 staging/自建库 + ECS 附件服务；CloudBase 只读）：
  1) 用本地管线同一套附件客户端上传一张 1×1 测试 PNG 到 ECS `/att/upload`（X-Sync-Token）；
  2) 生成 HMAC 签名 URL（与管线 `externalize_groups` 一致）并本地 GET 校验 200；
  3) 在 staging `notices` 插入一条临时通知（body 带该 `/att/` URL，id=qa_att_*）；
  4) 真实浏览器（?api=next、测试账号 3260799999/测试账号）读 `class_notices_meta`，
     确认临时通知存在、body 里是 `/att/` URL，且页面上下文 fetch 该 URL = 200；
  5) 清理：删临时通知 + ECS 测试附件文件（blob+json），确认 meta 恢复不含该 id。
只读 CloudBase；测试数据仅 staging，finally 清理；不打印 token/附件内容。
"""
import base64
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(WEB, "deploy"))
sys.path.insert(0, os.path.join(WEB, "attachments"))
sys.path.insert(0, os.path.join(WEB, "tools", "tests", "_qa_v2"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import ecs_site                 # noqa: E402
import _cdp                     # noqa: E402
from common import derive_key, signed_url  # noqa: E402
from client import load_sync_token, upload  # noqa: E402

BASE = "http://121.196.47.2"
URL = BASE + "/?api=next"
TEST_SID = "3260799999"
TEST_NAME = "测试账号"
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=")

RESULTS = []


def check(name, ok, note=""):
    RESULTS.append((name, bool(ok)))
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)[:280]) if note else ""))


def _http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def _remote(script, label):
    st, rc, out = ecs_site.run_script(script, label=label, timeout=180, wait=300)
    return st == "Success" and rc in (0, "0"), out or ""


def _cleanup(notice_id, att_id):
    script = r"""#!/bin/bash
set +e
sudo -u postgres psql -q -d class_tools -c "delete from public.notices where id='__NID__'" 2>/dev/null
rm -f "/opt/class-tools/attachments/__AID__" "/opt/class-tools/attachments/__AID__.json" 2>/dev/null
sleep 0.5
echo "cleanup_nid=$(sudo -u postgres psql -Atc "select count(*) from public.notices where id='__NID__'" -d class_tools 2>/dev/null)"
echo "cleanup_aid=$(ls /opt/class-tools/attachments/__AID__* 2>/dev/null | wc -l)"
echo done
""".replace("__NID__", notice_id).replace("__AID__", att_id)
    ok, out = _remote(script, "attach-cleanup")
    print(out)
    return ok


def main():
    t0 = time.time()
    token = load_sync_token()
    key = derive_key(token)
    att = upload(PNG_1PX, "qa-att-e2e.png", "image/png", BASE, token, timeout=60)
    att_id = str(att.get("id") or (att.get("sha256") or ""))[:64]
    check("A1 上传测试附件到 ECS /att/upload", bool(att_id) and att.get("size") == len(PNG_1PX),
          {k: att.get(k) for k in ("id_len", "size") if k in att} or {"id_len": len(att_id), "size": att.get("size")})
    if not att_id:
        return finish()
    exp = int(time.time()) + 1800
    signed = signed_url(BASE, att_id, exp, key)
    try:
        st, ctype, body = _http_get(signed, timeout=30)
        check("A2 签名 URL 本地 GET 200", st == 200 and body == PNG_1PX and ctype == "image/png",
              "http=%s type=%s bytes=%d" % (st, ctype, len(body)))
    except Exception as exc:  # noqa: BLE001
        check("A2 签名 URL 本地 GET 200", False, type(exc).__name__)
        _cleanup("qa_att_none", att_id)
        return finish()

    notice_id = "qa_att_" + str(int(time.time() * 1000))
    body_obj = {"title": "QA 附件外置演练",
                "items": [{"url": signed, "name": "qa-att-e2e.png", "size": len(PNG_1PX)}]}
    body = "[[CLASS_NOTICE_V1]]" + json.dumps(body_obj, ensure_ascii=False, separators=(",", ":"))
    ts = int(time.time() * 1000)
    body_b64 = base64.b64encode(body.encode("utf-8")).decode("ascii")
    insert = r"""#!/bin/bash
set -e
echo '__BODY_B64__' | base64 -d > /tmp/qa_attach_body.txt
BODY="$(cat /tmp/qa_attach_body.txt)"
sudo -u postgres psql -q -v ON_ERROR_STOP=1 -d class_tools -v nid='__NID__' -v ts='__TS__' -v body="$BODY" <<'SQL'
insert into public.notices(id,title,body,archived,ts,author)
values (:'nid','QA 附件外置演练',:'body',false,:'ts','QA')
on conflict (id) do update set body=excluded.body;
SQL
rm -f /tmp/qa_attach_body.txt
echo "inserted=$(sudo -u postgres psql -Atc "select count(*) from public.notices where id='__NID__'" -d class_tools)"
""".replace("__NID__", notice_id).replace("__TS__", str(ts)).replace("__BODY_B64__", body_b64)
    ok_ins, out = _remote(insert, "attach-insert")
    check("A3 staging 插入临时通知（带 /att URL）", ok_ins and "inserted=1" in out, out.strip().splitlines()[-1:] if out else "")

    browser = _cdp.Browser(window=(430, 900), extra_flags=[
        "--no-proxy-server",
        "--disable-features=HttpsUpgrades,HttpsFirstModeV2,HTTPS-FirstMode,HttpsFirstBalancedModeAutoEnable",
    ])
    try:
        page = browser.new_page("about:blank")
        page.add_init_script(
            "window.__e2e_errs=[];window.addEventListener('error',function(e){window.__e2e_errs.push(String((e&&e.message)||'error'));});",
            run_immediately=True)
        page.navigate(URL)
        page.wait_load(30)
        page.sleep(0.4)
        ver = page.evaluate(
            """(async function(){
              var r=await fetch(location.origin+'/v1/rdb/rest-next/rpc/class_verify',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({p_sid:'%s',p_name:'%s'})});
              var j=await r.json();
              if(!j||!j.token)return {ok:false,err:'verify '+r.status};
              localStorage.setItem('zq_class_identity',JSON.stringify({token:j.token,sid:j.sid,name:j.name,role:j.role||'',badge:j.badge||'',is_admin:!!j.is_admin,ts:Date.now()}));
              return {ok:true,token:j.token};})()""" % (TEST_SID, TEST_NAME), await_promise=True, timeout=60)
        if not ver.get("ok"):
            check("A4 测试账号 staging 登录", False, ver)
            return finish()
        page.navigate(URL)
        page.wait_load(30)
        page.wait_for("!document.body.classList.contains('auth-pending')", timeout=25)
        page.sleep(0.6)
        res = page.evaluate(
            """(async function(){
              var id=JSON.parse(localStorage.getItem('zq_class_identity')||'null')||{};
              var meta=await (await fetch(location.origin+'/v1/rdb/rest-next/rpc/class_notices_meta',{method:'POST',
                headers:{'Content-Type':'application/json','X-Class-Token':id.token},body:'{}'})).json();
              var row=(meta||[]).filter(function(x){return String(x.id)===String('%s');})[0]||null;
              if(!row)return {ok:false,err:'meta 里没有临时通知',n:(meta||[]).length};
              var body=String(row.body||'');
              var prefix='[[CLASS_NOTICE_V1]]';
              var url='';
              try{url=(JSON.parse(body.slice(prefix.length)).items[0]||{}).url||'';}catch(e){}
              var got={status:0,ctype:'',len:0,err:''};
              if(url){
                try{
                  var r2=await fetch(url);got.status=r2.status;got.ctype=r2.headers.get('Content-Type')||'';
                  got.len=(await r2.arrayBuffer()).byteLength;
                }catch(e){got.err=String(e&&e.message||e);}
              }
              var prod=performance.getEntriesByType('resource').filter(function(e){return e.name.indexOf('/v1/rdb/rest/')>=0&&e.name.indexOf('rest-next')<0;}).length;
              return {ok:true,n:(meta||[]).length,url:url,got:got,prod:prod,errs:(window.__e2e_errs||[]).slice(0,5)};
            })()""" % notice_id, await_promise=True, timeout=90)
        check("A4 通知 meta 含临时通知", res.get("ok") is True and res.get("n", 0) > 0, res)
        check("A5 body 内是 /att 签名 URL（不再是 data URI）",
              isinstance(res.get("url"), str) and "/att/" in res.get("url", "") and res.get("url", "").startswith("http"),
              res.get("url"))
        got = res.get("got") or {}
        check("A6 页面上下文 fetch 签名 URL 200 且字节一致",
              got.get("status") == 200 and got.get("len") == len(PNG_1PX), got)
        check("A7 0 个生产 CloudBase API 请求", res.get("prod", 0) == 0, "prod=%s" % res.get("prod"))
        check("A8 无 JS 报错", not res.get("errs"), res.get("errs"))
    finally:
        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        _cleanup(notice_id, att_id)
    elapsed = time.time() - t0
    print("[timing] %.1fs" % elapsed)
    return finish()


def finish():
    total = len(RESULTS)
    passed = sum(1 for _n, ok in RESULTS if ok)
    print("=" * 56)
    print("e2e_attach_staging: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 56)
    return 0 if total and passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
