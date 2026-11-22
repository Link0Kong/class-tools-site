# -*- coding: utf-8 -*-
"""通知管理页（仅管理员）网页专项检查（契约 tools/tests/nt_admin_spec.md · 2026-11-22）

方式：headless Edge + CDP；页面里的云 fetch 全部 mock（不碰真实云端、不写任何线上数据）。
覆盖：管理员门禁/通知页入口/全部页卡片、群列表与筛选搜索、采集开关与能力开关、
可见人群（全体/班委/团员/仅管理员/指定座号/群成员名单）、保存防抖与 rev+1、
待获取文件（筛选/复制/复制清单/重新扫描）、添加/移除群聊、无配置空态、
360/390/430 无横向溢出、桌面双栏、0 JS 报错、0 外部请求。

运行：cd web/tools && python tests\\v2_nt_admin_check.py
截图：tools/tests/_shots_ntadmin/
"""
import http.server
import json
import os
import socketserver
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

SHOTS = os.path.join(HERE, "_shots_ntadmin")
os.makedirs(SHOTS, exist_ok=True)
PORT = 8991
RESULTS = []


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class _Srv(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


def serve(d, p):
    h = lambda *a, **kw: Q(*a, directory=d, **kw)  # noqa: E731
    s = _Srv(("127.0.0.1", p), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def jsq(s):
    return json.dumps(s, ensure_ascii=False)


MEMBERS = [
    {"seat": 1, "sid": "9000000001", "name": "测试管理员", "role": "", "badge": "", "is_admin": True},
    {"seat": 2, "sid": "9000000002", "name": "同学乙", "role": "", "badge": "", "is_admin": False},
    {"seat": 3, "sid": "9000000003", "name": "同学丙", "role": "班长", "badge": "班委", "is_admin": False},
    {"seat": 5, "sid": "9000000005", "name": "同学戊", "role": "", "badge": "", "is_admin": False},
    {"seat": 8, "sid": "9000000008", "name": "同学辛", "role": "", "badge": "", "is_admin": False},
]

NOW_ISO = "2026-11-22T16:30:00+08:00"
CFG = {
    "v": 1, "rev": 3, "updatedAt": "2026-11-22T16:20:00+08:00", "updatedBy": "9000000001",
    "groups": [
        {"platform": "qq", "gid": "1101960522", "name": "2026级信息管理与信息系统",
         "capture": {"ai": True, "file": True, "image": False, "doc": True},
         "audience": {"type": "all", "seats": [], "set": ""}, "added": False},
        {"platform": "qq", "gid": "1132554913", "name": "2026运动会志愿者",
         "capture": {"ai": True, "file": False, "image": False, "doc": False},
         "audience": {"type": "set", "seats": [], "set": "volunteer"}, "added": False},
        {"platform": "wx", "gid": "56720123123@chatroom", "name": "26信管班群",
         "capture": {"ai": True, "file": False, "image": False, "doc": False},
         "audience": {"type": "custom", "seats": [5], "set": ""}, "added": False},
        {"platform": "wx", "gid": "", "name": "非班级群（未采集）",
         "capture": {"ai": False, "file": False, "image": False, "doc": False},
         "audience": {"type": "admin", "seats": [], "set": ""}, "added": False},
    ],
}
STATUS = {
    "agentAt": NOW_ISO, "configRev": 3, "configUpdatedAt": "2026-11-22T16:20:00+08:00",
    "appliedAt": "2026-11-22T16:21:00+08:00", "groups": 4, "boardAt": NOW_ISO,
    "pendingCount": 3, "scanAt": 0, "scanResult": "",
    "pending": [
        {"name": "民族器乐大赛招募志愿者名单.xlsx", "group": "26信管班群", "platform": "wx",
         "noticeId": "g1", "title": "民族器乐大赛志愿者入选名单公示", "time": "11-21 11:00", "from": "甲"},
        {"name": "2027年全国两红两优.zip", "group": "2026运动会志愿者", "platform": "qq",
         "noticeId": "g2", "title": "2027全国两红两优申报", "time": "11-20 10:00", "from": "乙"},
        {"name": "新生欢迎会座位安排.xlsx", "group": "2026级信息管理与信息系统", "platform": "qq",
         "noticeId": "g3", "title": "新生欢迎会", "time": "11-19 09:00", "from": "丙"},
    ],
}


def mock_js(admin=True, cfg=None, status=None):
    seed = {"admin": bool(admin), "cfg": cfg, "status": status, "members": MEMBERS}
    return r"""
(function(){
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var SEED=__SEED__;
var ME=SEED.admin?{token:"qa-nt-admin",sid:"9000000001",name:"测试管理员",role:"",badge:"",is_admin:true,ts:Date.now()}
                 :{token:"qa-nt-member",sid:"9000000002",name:"同学乙",role:"",badge:"",is_admin:false,ts:Date.now()};
try{localStorage.setItem("zq_class_identity",JSON.stringify(ME));}catch(e){}
var M=window.__MOCKA={reqs:[],external:[],confirms:0,confirmAnswer:true,clip:"",
  cfg:SEED.cfg?JSON.parse(JSON.stringify(SEED.cfg)):null,
  status:SEED.status?JSON.parse(JSON.stringify(SEED.status)):null,
  req:null,members:SEED.members};
window.confirm=function(){M.confirms++;return M.confirmAnswer!==false;};
try{Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:function(t){M.clip=String(t);return Promise.resolve();}}});}catch(e){
  try{navigator.clipboard.writeText=function(t){M.clip=String(t);return Promise.resolve();};}catch(e2){}
}
var _f=window.fetch.bind(window);
function resp(body,code){return Promise.resolve(new Response(JSON.stringify(body===undefined?[]:body),{status:code||200,headers:{"Content-Type":"application/json"}}));}
function qid(qs){var m=/(?:^|[?&])id=eq\.([^&]+)/.exec(qs||"");return m?decodeURIComponent(m[1]):"";}
function rowOf(id){
  var v=(id==="notice_groups")?M.cfg:(id==="notice_status")?M.status:(id==="notice_request")?M.req:null;
  if(v===null||v===undefined)return [];
  return [{id:id,value:v,updated_at:new Date().toISOString()}];
}
function setRow(id,value){
  if(id==="notice_groups")M.cfg=value;else if(id==="notice_status")M.status=value;else if(id==="notice_request")M.req=value;
}
window.fetch=function(url,opt){
  opt=opt||{};
  var s=String((url&&url.url!==undefined)?url.url:url);
  var method=String(opt.method||"GET").toUpperCase();
  var rest="";
  try{rest=s.split("/v1/rdb/rest/")[1]||"";}catch(e){rest="";}
  if(s.indexOf("tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/")>=0){
    var path=rest.split("?")[0],qs=rest.indexOf("?")>=0?rest.slice(rest.indexOf("?")+1):"";
    if(path==="site_config"){
      var id=qid(qs);
      if(method==="GET"){M.reqs.push({kind:"read",id:id});return resp(rowOf(id));}
      if(method==="PATCH"){
        var b=JSON.parse(opt.body||"null")||{};
        M.reqs.push({kind:"write",id:id,method:"PATCH",value:b.value});
        setRow(id,b.value);return resp(rowOf(id));
      }
      if(method==="POST"){
        var arr=JSON.parse(opt.body||"[]");var r=arr[0]||{};
        M.reqs.push({kind:"write",id:r.id,method:"POST",value:r.value});
        setRow(r.id,r.value);return resp(rowOf(r.id),201);
      }
      return resp([]);
    }
    M.reqs.push({kind:"cb",method:method,path:path});
    if(path==="rpc/class_members")return resp(M.members);
    if(path==="rpc/class_league")return resp({ok:true,seats:[]});
    if(path==="rpc/class_notices_meta")return resp([]);
    if(path==="rpc/class_whoami")return resp({ok:true,sid:ME.sid,name:ME.name,is_admin:ME.is_admin});
    if(path.indexOf("rpc/")===0)return resp({ok:true});
    return resp([]);
  }
  if(s.indexOf(location.origin)===0)return _f.apply(window,arguments);
  if(!/^https?:\/\//i.test(s))return _f.apply(window,arguments);
  M.external.push(s);
  return resp([]);
};
})();
""".replace("__SEED__", json.dumps(seed, ensure_ascii=False))


def ev(pg, expr, ap=False):
    return pg.evaluate(expr, await_promise=ap)


def click(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.click();return true;})()" % jsq(sel))


def set_val(pg, sel, v):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.value=%s;"
                "e.dispatchEvent(new Event('input',{bubbles:true}));return true;})()" % (jsq(sel), jsq(v)))


def text_of(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);return e?String(e.textContent||''):'';})()" % jsq(sel))


def count(pg, sel):
    return ev(pg, "document.querySelectorAll(%s).length" % jsq(sel))


def cfg_of(pg):
    return json.loads(ev(pg, "JSON.stringify(window.__MOCKA.cfg)") or "null")


def group_of(pg, key):
    return json.loads(ev(pg, "(function(){var g=(window.__MOCKA.cfg&&window.__MOCKA.cfg.groups||[])"
                              ".filter(function(x){return (x.platform+':'+(x.gid||('name:'+x.name)))===%s;})[0];"
                              "return JSON.stringify(g||null);})()" % jsq(key)) or "null")


def writes(pg, rid):
    raw = ev(pg, "JSON.stringify((window.__MOCKA.reqs||[]).filter(function(r){return r.kind==='write'&&r.id===%s;}))" % jsq(rid))
    return json.loads(raw or "[]")


def goto_all(pg):
    click(pg, '#tabsBar button[data-tab="all"]')
    pg.wait_for("document.querySelector('#s-all')&&document.querySelector('#s-all').classList.contains('on')", 8)


def goto_admin(pg):
    if not ev(pg, "document.querySelector('#s-ntadmin')&&document.querySelector('#s-ntadmin').classList.contains('on')"):
        goto_all(pg)
        pg.wait_for("document.querySelector('[data-card=\"ntadmin\"]')!==null", 8)
        click(pg, '[data-open="ntadmin"]')
        pg.wait_for("document.querySelector('#s-ntadmin').classList.contains('on')", 8)


def wait_save(pg):
    pg.sleep(0.95)


def overflow(pg):
    return ev(pg, "(function(){var d=document.documentElement;return Math.max(d.scrollWidth,"
                  "document.body.scrollWidth)-window.innerWidth;})()")


def main():
    srv = serve(ROOT, PORT)
    b = _cdp.Browser(window=(430, 900))
    try:
        # ================= A. 管理员：入口 / 列表 / 筛选 =================
        pg = b.new_page("about:blank")
        pg.set_device(430, 900, 2.0, True, True)
        pg.add_init_script(mock_js(True, CFG, STATUS))
        pg.navigate("http://127.0.0.1:%d/index.html" % PORT)
        pg.wait_load(25)
        boot = pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof NTADMIN!=='undefined'", 20)
        T("启动：管理员身份通过 + NTADMIN 模块装载", boot)

        T("通知页「管理」浮钮对管理员可见", ev(pg, "(function(){var e=document.getElementById('ntAdminFab');return !!e&&!e.hidden;})()"))
        goto_all(pg)
        pg.wait_for("document.querySelector('[data-card=\"ntadmin\"]')!==null", 8)
        T("全部页出现「通知管理」卡片（admin 工具）",
          ev(pg, "!!document.querySelector('[data-card=\"ntadmin\"]')") and
          text_of(pg, '[data-card="ntadmin"]').find("通知管理") >= 0)
        click(pg, '[data-open="ntadmin"]')
        pg.wait_for("document.querySelector('#s-ntadmin').classList.contains('on')", 8)
        pg.wait_for("document.querySelectorAll('#naList .na-row').length===4", 10)
        T("进入通知管理页：4 个群渲染", count(pg, "#naList .na-row") == 4)
        T("平台计数 QQ2 / 微信2 / 全部4",
          text_of(pg, "#naCntQq") == "2" and text_of(pg, "#naCntWx") == "2" and text_of(pg, "#naCntAll") == "4")
        T("页头摘要含群数与采集数", "4 群" in text_of(pg, "#naSub") and "采集 3" in text_of(pg, "#naSub"),
          text_of(pg, "#naSub"))
        T("采集端状态：已应用 + 待获取 3",
          "已应用" in text_of(pg, "#naState") and "待获取" in text_of(pg, "#naState"),
          text_of(pg, "#naState")[:100])
        T("待获取文件列表 3 条", count(pg, "#naPendList .na-pend-item") == 3,
          text_of(pg, "#naPendList")[:120])

        click(pg, '#naFilter [data-naf="qq"]')
        pg.sleep(0.15)
        T("群列表筛选 QQ → 2 行", count(pg, "#naList .na-row") == 2)
        click(pg, '#naFilter [data-naf="wx"]')
        pg.sleep(0.15)
        T("群列表筛选 微信 → 2 行", count(pg, "#naList .na-row") == 2)
        click(pg, '#naFilter [data-naf="all"]')
        pg.sleep(0.15)
        set_val(pg, "#naSearch", "志愿者")
        pg.sleep(0.2)
        T("搜索群名 → 1 行", count(pg, "#naList .na-row") == 1)
        set_val(pg, "#naSearch", "")
        pg.sleep(0.15)
        T("清空搜索恢复 4 行", count(pg, "#naList .na-row") == 4)

        # ================= B. 采集开关 =================
        click(pg, 'input[data-natg="qq:1101960522"]')
        pg.sleep(0.15)
        T("主开关关闭后本地配置立即为 false", ev(pg, "!window.NTADMIN.state().cfg.groups[0].capture.ai"))
        wait_save(pg)
        g = group_of(pg, "qq:1101960522")
        T("主开关保存：capture.ai=false + rev+1 + PATCH",
          g and g["capture"]["ai"] is False and cfg_of(pg)["rev"] == 4 and len(writes(pg, "notice_groups")) >= 1,
          "rev=%s writes=%d" % (cfg_of(pg)["rev"], len(writes(pg, "notice_groups"))))
        T("保存后状态变「待应用」（rev 4 > status 3）", "待应用" in text_of(pg, "#naState"))
        click(pg, 'input[data-natg="qq:1101960522"]')
        wait_save(pg)
        T("主开关再次开启并保存", group_of(pg, "qq:1101960522")["capture"]["ai"] is True and cfg_of(pg)["rev"] == 5)

        click(pg, '[data-nahead="qq:1101960522"]')
        pg.sleep(0.15)
        if not ev(pg, "(function(){var e=document.querySelector('[data-nabody=\"qq:1101960522\"]');return !!e&&!e.hidden;})()"):
            click(pg, '[data-nahead="qq:1101960522"]')
            pg.sleep(0.15)
        T("展开群行：能力开关可见", ev(pg, "(function(){var e=document.querySelector('[data-nabody=\"qq:1101960522\"]');return !!e&&!e.hidden;})()"))
        T("QQ 群显示 识别/文件/图片/文档 四项", count(pg, '[data-nabody="qq:1101960522"] .na-cap') == 4)
        click(pg, 'input[data-nacap="image"][data-nakey="qq:1101960522"]')
        wait_save(pg)
        T("开启图片采集并保存", group_of(pg, "qq:1101960522")["capture"]["image"] is True)
        T("微信群展开只有「识别」一项",
          (click(pg, '[data-nahead="wx:56720123123@chatroom"]') or True) and
          ev(pg, "(function(){var e=document.querySelector('[data-nabody=\"wx:56720123123@chatroom\"]');"
                 "return !!e&&e.querySelectorAll('.na-cap').length===1;})()"))

        # ================= C. 可见人群 =================
        click(pg, '[data-naaud="qq:1101960522"]')
        pg.wait_for("(function(){var e=document.getElementById('naAudOv');return e&&e.style.display!=='none'&&!e.hidden;})()", 5)
        T("可见人群弹层打开（5 个基础选项）", count(pg, "#naAudOpts .na-aud-opt") == 5)
        T("弹层显示群名", "2026级信息管理与信息系统" in text_of(pg, "#naAudGroup"))
        click(pg, '#naAudOpts [data-naaudtype="custom"]')
        pg.wait_for("document.querySelectorAll('#naSeatGrid .na-seat').length===5", 8)
        T("选择「指定成员」后出现班级名单 5 人", count(pg, "#naSeatGrid .na-seat") == 5)
        click(pg, '#naSeatGrid [data-naseat="1"]')
        click(pg, '#naSeatGrid [data-naseat="3"]')
        T("勾选 2 人：已选 2 人", "已选 2 人" in text_of(pg, "#naSeatSum"))
        pg.screenshot(os.path.join(SHOTS, "audience_seat_sheet.png"))
        click(pg, "#naAudOk")
        pg.sleep(0.2)
        T("弹层关闭", ev(pg, "(function(){var e=document.getElementById('naAudOv');return e.hidden||e.style.display==='none';})()"))
        wait_save(pg)
        g = group_of(pg, "qq:1101960522")
        T("指定成员保存：audience=seats:1,3", g["audience"] == {"type": "custom", "seats": [1, 3], "set": ""},
          json.dumps(g["audience"]))
        T("群行显示「指定 2 人」", "指定 2 人" in text_of(pg, '[data-naaud="qq:1101960522"]'))

        click(pg, '[data-naaud="qq:1101960522"]')
        pg.wait_for("!document.getElementById('naAudOv').hidden", 5)
        click(pg, '#naAudOpts [data-naaudtype="all"]')
        click(pg, "#naAudOk")
        wait_save(pg)
        T("切回全体同学并保存", group_of(pg, "qq:1101960522")["audience"]["type"] == "all")

        click(pg, '[data-naaud="qq:1132554913"]')
        pg.wait_for("!document.getElementById('naAudOv').hidden", 5)
        set_text = text_of(pg, "#naAudOpts")
        T("有群成员名单的群出现「群成员 · 志愿者」选项",
          "群成员 · 志愿者" in set_text and count(pg, "#naAudOpts .na-aud-opt") == 6, set_text[:120])
        click(pg, '#naAudOpts [data-naaudtype="set"]')
        click(pg, "#naAudOk")
        wait_save(pg)
        T("选择群成员名单后保存为 set:volunteer",
          group_of(pg, "qq:1132554913")["audience"] == {"type": "set", "seats": [], "set": "volunteer"})
        T("群行显示「群成员 · 志愿者」", "群成员 · 志愿者" in text_of(pg, '[data-naaud="qq:1132554913"]'))

        click(pg, '[data-naaud="qq:1132554913"]')
        pg.wait_for("!document.getElementById('naAudOv').hidden", 5)
        click(pg, "#naAudCancel")
        pg.sleep(0.15)
        T("取消不改变配置", group_of(pg, "qq:1132554913")["audience"]["set"] == "volunteer")

        click(pg, '[data-naaud="wx:56720123123@chatroom"]')
        pg.wait_for("!document.getElementById('naAudOv').hidden", 5)
        click(pg, '#naAudOpts [data-naaudtype="custom"]')
        pg.wait_for("document.querySelectorAll('#naSeatGrid .na-seat').length===5", 8)
        click(pg, "#naSeatClear")
        click(pg, "#naAudOk")
        pg.sleep(0.2)
        T("指定成员未选人时拒绝保存（弹层保留）",
          ev(pg, "(function(){var e=document.getElementById('naAudOv');return !!e&&!e.hidden;})()") and
          "至少选择" in text_of(pg, "#toast"))
        click(pg, '#naSeatGrid [data-naseat="5"]')
        click(pg, "#naAudOk")
        wait_save(pg)
        T("重新选 1 人后保存成功", group_of(pg, "wx:56720123123@chatroom")["audience"]["seats"] == [5])

        # ================= D. 待获取文件 =================
        click(pg, '#naPendFilter [data-npf="qq"]')
        pg.sleep(0.15)
        T("待获取筛选 QQ → 2 条", count(pg, "#naPendList .na-pend-item") == 2)
        click(pg, '#naPendFilter [data-npf="wx"]')
        pg.sleep(0.15)
        T("待获取筛选 微信 → 1 条", count(pg, "#naPendList .na-pend-item") == 1)
        click(pg, '#naPendFilter [data-npf="all"]')
        pg.sleep(0.15)
        T("待获取恢复 3 条", count(pg, "#naPendList .na-pend-item") == 3)
        click(pg, "#naPendList .na-copy")
        pg.sleep(0.1)
        T("单项复制写入剪贴板", "xlsx" in (ev(pg, "window.__MOCKA.clip") or ""), ev(pg, "window.__MOCKA.clip"))
        click(pg, "#naCopyAll")
        pg.sleep(0.1)
        clip = ev(pg, "window.__MOCKA.clip") or ""
        T("复制清单含全部文件名与群名",
          "民族器乐大赛招募志愿者名单.xlsx" in clip and "26信管班群" in clip and clip.count("\n") == 2, clip[:120])
        click(pg, "#naRescan")
        pg.wait_for("window.__MOCKA.req&&window.__MOCKA.req.scanAt>0", 6)
        T("重新扫描写入 notice_request.scanAt", ev(pg, "window.__MOCKA.req.scanAt") > 0 and
          ev(pg, "window.__MOCKA.req.by") == "9000000001")

        # ================= E. 添加 / 移除群聊 =================
        n0 = count(pg, "#naList .na-row")
        click(pg, "#naAdd")
        pg.wait_for("!document.getElementById('naAddOv').hidden", 5)
        pg.screenshot(os.path.join(SHOTS, "add_group_sheet.png"))
        click(pg, '#naAddPf [data-napf="wx"]')
        set_val(pg, "#naAddName", "新群测试")
        set_val(pg, "#naAddId", "")
        click(pg, "#naAddSave")
        pg.sleep(0.3)
        T("添加微信群：列表 +1（5 行）", count(pg, "#naList .na-row") == n0 + 1, "n0=%s" % n0)
        wait_save(pg)
        g = group_of(pg, "wx:name:新群测试")
        T("新增群默认仅管理员可见 + 仅识别", g and g["audience"]["type"] == "admin" and
          g["capture"]["ai"] is True and g["added"] is True, json.dumps(g, ensure_ascii=False)[:140])
        T("新增群行出现「移除」按钮", ev(pg, "!!document.querySelector('[data-nadel=\"wx:name:新群测试\"]')"))
        click(pg, '[data-nadel="wx:name:新群测试"]')
        wait_save(pg)
        n_after = count(pg, "#naList .na-row")
        still = group_of(pg, "wx:name:新群测试")
        T("移除新增群后恢复 4 行", n_after == 4 and still is None,
          "rows=%s exists=%s confirms=%s" % (n_after, still is not None,
                                             ev(pg, "window.__MOCKA.confirms")))

        click(pg, "#naAdd")
        pg.wait_for("!document.getElementById('naAddOv').hidden", 5)
        set_val(pg, "#naAddName", "坏群号")
        set_val(pg, "#naAddId", "abc")
        click(pg, "#naAddSave")
        pg.sleep(0.2)
        T("QQ 群号非法时拒绝保存（弹层保留）",
          ev(pg, "(function(){var e=document.getElementById('naAddOv');return !!e&&!e.hidden;})()") and
          "群号" in text_of(pg, "#toast"))
        click(pg, "#naAddCancel")

        # ================= F. 通知页入口 =================
        goto_all(pg)
        click(pg, '[data-open="nt"]')
        pg.wait_for("document.querySelector('#s-nt').classList.contains('on')", 8)
        T("通知页「管理」浮钮可见", ev(pg, "(function(){var e=document.getElementById('ntAdminFab');return !!e&&!e.hidden;})()"))
        click(pg, "#ntAdminFab")
        pg.wait_for("document.querySelector('#s-ntadmin').classList.contains('on')", 8)
        T("点「管理」浮钮进入通知管理页", ev(pg, "document.querySelector('#s-ntadmin').classList.contains('on')"))

        # ================= G. 溢出 / 桌面双栏 =================
        for w in (360, 390, 430):
            pg.set_device(w, 820, 2.0, True, True)
            pg.sleep(0.25)
            ov = overflow(pg)
            T("%dpx 无横向溢出" % w, ov <= 1, "overflow=%s" % ov)
        pg.set_device(1280, 900, 1.0, False, False)
        pg.sleep(0.3)
        cols = ev(pg, "(function(){var e=document.querySelector('#s-ntadmin .na-dash');if(!e)return '';"
                      "return getComputedStyle(e).gridTemplateColumns;})()")
        T("桌面 ≥960px 两栏布局", len(str(cols).split()) >= 2, cols)
        T("桌面无横向溢出", overflow(pg) <= 1)
        pg.screenshot(os.path.join(SHOTS, "ntadmin_desktop.png"), full=True)
        pg.set_device(430, 900, 2.0, True, True)
        pg.sleep(0.2)
        pg.screenshot(os.path.join(SHOTS, "ntadmin_430.png"), full=True)

        # ================= H. 无配置空态 =================
        ev(pg, "window.__MOCKA.cfg=null;window.NTADMIN.load(true);")
        pg.sleep(0.3)
        T("云端无配置时显示空态", "等待本机采集端同步配置" in text_of(pg, "#naList"), text_of(pg, "#naList")[:100])
        click(pg, "#naAdd")
        pg.wait_for("!document.getElementById('naAddOv').hidden", 5)
        set_val(pg, "#naAddName", "初始化群")
        set_val(pg, "#naAddId", "123456789")
        click(pg, "#naAddSave")
        pg.sleep(0.2)
        T("无配置新增群会二次确认", ev(pg, "window.__MOCKA.confirms") >= 1)
        wait_save(pg)
        T("确认后创建配置 rev1 + 1 个群", cfg_of(pg)["rev"] == 1 and len(cfg_of(pg)["groups"]) == 1,
          "rev=%s n=%s" % (cfg_of(pg)["rev"], len(cfg_of(pg)["groups"])))

        # ================= I. 错误 / 外部请求 =================
        errs = json.loads(ev(pg, "JSON.stringify(window.__errs)"))
        cerrs = json.loads(ev(pg, "JSON.stringify(window.__cerrs)"))
        T("0 JS 报错", len(errs) == 0, str(errs[:3]))
        T("0 console.error", len(cerrs) == 0, str(cerrs[:3]))
        ext = json.loads(ev(pg, "JSON.stringify(window.__MOCKA.external)"))
        T("0 外部请求", len(ext) == 0, str(ext[:3]))
        T("APP_VER 仍为 2.0.0", "2.0.0" in text_of(pg, ".idver"))
        pg.close()

        # ================= J. 非管理员门禁 =================
        pg2 = b.new_page("about:blank")
        pg2.set_device(430, 900, 2.0, True, True)
        pg2.add_init_script(mock_js(False, CFG, STATUS))
        pg2.navigate("http://127.0.0.1:%d/index.html" % PORT)
        pg2.wait_load(25)
        ok2 = pg2.wait_for("document.body.classList.contains('auth-pending')===false", 20)
        T("非管理员：正常进入班级", ok2)
        T("非管理员：通知页「管理」浮钮隐藏", ev(pg2, "(function(){var e=document.getElementById('ntAdminFab');return !!e&&e.hidden;})()"))
        goto_all(pg2)
        pg2.sleep(0.3)
        T("非管理员：全部页无「通知管理」卡片", count(pg2, '[data-card="ntadmin"]') == 0)
        sc = json.loads(pg2.evaluate(
            "JSON.stringify((window.__MOCKA.reqs||[]).filter(function(r){return r.id==='notice_groups';}))"))
        T("非管理员：0 次通知管理配置请求", len(sc) == 0, str(sc[:2]))
        T("非管理员：配置状态保持空", ev(pg2, "window.NTADMIN.state().loaded===false&&window.NTADMIN.state().cfg===null"))
        T("非管理员：0 JS 报错", len(json.loads(pg2.evaluate("JSON.stringify(window.__errs)"))) == 0)

    finally:
        try:
            b.close()
        except Exception:
            pass
        try:
            srv.shutdown()
        except Exception:
            pass

    passed = sum(1 for r in RESULTS if r["ok"])
    print("\nRESULT: %d/%d PASS" % (passed, len(RESULTS)))
    if passed != len(RESULTS):
        print("FAILED:")
        for r in RESULTS:
            if not r["ok"]:
                print(" -", r["name"], "|", r["note"])
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
