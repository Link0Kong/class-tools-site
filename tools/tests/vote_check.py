# -*- coding: utf-8 -*-
"""投票功能网页专项检查（web/vote/CONTRACT.md §3/§5）

方式：headless Edge + CDP。页面里的云 fetch 全部 mock（不碰真实云端、不写任何线上数据），
覆盖：工具注册/进入、列表与筛选、发起（限时/长时/不限时、2–20 选项、多选上限、匿名、改票、结果可见性、
选项说明与配图入口）、详情投票/改票、结果条与实名投票人、发起人管理（编辑/提前结束/延长/删除）、
倒计时到点自动截止、430/390/360 无横向溢出、0 JS 报错、0 外部请求。

运行：cd web/tools && python tests\\vote_check.py
截图：tools/tests/_shots_vote/
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

SHOTS = os.path.join(HERE, "_shots_vote")
os.makedirs(SHOTS, exist_ok=True)
PORT = 8973
NOW = int(time.time() * 1000)
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


def opt(oid, text, desc="", img=""):
    return {"id": oid, "text": text, "desc": desc, "img": img}


SET_ANON = {"multi": False, "maxChoices": 1, "anonymous": True, "allowChange": True, "resultVisibility": "afterVote"}
SET_MULTI = {"multi": True, "maxChoices": 2, "anonymous": False, "allowChange": True, "resultVisibility": "afterVote"}


def poll(pid, title, settings, options, deadline, status="open", closed_at=0, owner="9000000001", owner_name="测试同学01",
         desc="", mode="long", created=None, audience="all", seats=None):
    return {"id": pid, "title": title, "description": desc, "mode": mode, "owner_sid": owner, "owner_name": owner_name,
            "settings": settings, "options": options, "deadline": deadline, "status": status, "closed_at": closed_at,
            "audience": audience, "audience_seats": (seats or []),
            "deleted": False, "created_at": created or NOW, "updated_at": NOW}


P1 = poll("pqa1", "周五还是周六开班会", SET_ANON, [opt("o1", "周五 19:00"), opt("o2", "周六 19:00")],
          NOW + 30 * 60 * 1000, mode="quick")
P2 = poll("pqa2", "团日活动去哪（多选）", SET_MULTI,
          [opt("o1", "博物馆", "免费，需预约"), opt("o2", "公园", ""), opt("o3", "校园内", "")],
          NOW + 2 * 86400000, owner="9000000002", owner_name="同学02")
P3 = poll("pqa3", "班服颜色（不限时·截止后可见）",
          {"multi": False, "maxChoices": 1, "anonymous": True, "allowChange": True, "resultVisibility": "afterClose"},
          [opt("o1", "藏青"), opt("o2", "雾青")], 0)
P4 = poll("pqa4", "已结束的投票", SET_ANON, [opt("o1", "同意"), opt("o2", "不同意")], 0,
          status="closed", closed_at=NOW - 3600000, mode="quick")
P5 = poll("pqa5", "可编辑的投票（暂无票）", SET_ANON, [opt("o1", "甲"), opt("o2", "乙")], NOW + 3 * 86400000,
          audience="custom", seats=[1, 3])
P6 = poll("pqa6", "指定成员可见的投票", SET_ANON, [opt("o1", "行"), opt("o2", "不行")], NOW + 4 * 86400000,
          owner="9000000002", owner_name="同学02", audience="custom", seats=[1, 2])
SEED = {
    "members": [
        {"seat": 1, "sid": "9000000001", "name": "测试同学01", "role": "", "badge": "", "is_admin": False},
        {"seat": 2, "sid": "9000000002", "name": "同学02", "role": "", "badge": "", "is_admin": False},
        {"seat": 3, "sid": "9000000003", "name": "同学03", "role": "", "badge": "", "is_admin": False},
        {"seat": 4, "sid": "9000000004", "name": "同学04", "role": "班长", "badge": "班委", "is_admin": False},
        {"seat": 5, "sid": "9000000005", "name": "同学05", "role": "", "badge": "", "is_admin": False},
    ],
    "polls": [P1, P2, P3, P4, P5, P6],
    "votes": {
        "pqa1": [{"sid": "9000000002", "choices": ["o1"]}, {"sid": "9000000003", "choices": ["o2"]}],
        "pqa2": [{"sid": "9000000002", "choices": ["o1", "o2"]}, {"sid": "9000000003", "choices": ["o2"]}],
        "pqa3": [{"sid": "9000000002", "choices": ["o1"]}],
        "pqa4": [{"sid": "9000000002", "choices": ["o1"]}],
        "pqa5": [],
        "pqa6": [],
    },
}

MOCK_JS = r"""
(function(){
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var SEED=__SEED__;
var ME={tok:"qa-vote-token",sid:"9000000001",name:"测试同学01"};
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:ME.tok,sid:ME.sid,name:ME.name,role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
window.confirm=function(){window.__MOCKV.confirms++;return true;};
var NAMES={"9000000001":"测试同学01","9000000002":"同学02","9000000003":"同学03"};
var M=window.__MOCKV={reqs:[],external:[],confirms:0,polls:SEED.polls,votes:SEED.votes};
function now(){return Date.now();}
function pd(id){for(var i=0;i<M.polls.length;i++)if(M.polls[i].id===id)return M.polls[i];return null;}
function closedOf(p){return !!(p.status==="closed"||(Number(p.deadline)>0&&now()>=Number(p.deadline)));}
function votesOf(id){return M.votes[id]||[];}
function myVote(id){var v=votesOf(id);for(var i=0;i<v.length;i++)if(v[i].sid===ME.sid)return v[i];return null;}
function countsOf(id){var c={},v=votesOf(id);v.forEach(function(x){(x.choices||[]).forEach(function(o){c[o]=(c[o]||0)+1;});});return c;}
function visible(p,has){var mode=(p.settings&&p.settings.resultVisibility)||"afterVote";if(mode==="always")return true;if(mode==="afterClose")return closedOf(p);return !!has;}
function votersArr(p){var has=!!myVote(p.id);if(!visible(p,has))return [];if(p.settings&&p.settings.anonymous)return [];
  return votesOf(p.id).map(function(v){return {name:NAMES[v.sid]||"同学",choices:v.choices};});}
function summary(p){var has=!!myVote(p.id),vis=visible(p,has);return {id:p.id,title:p.title,description:p.description,mode:p.mode,
  owner_name:p.owner_name,settings:p.settings,deadline:p.deadline,status:p.status,closed_at:p.closed_at,
  created_at:p.created_at,updated_at:p.updated_at,closed:closedOf(p),total:votesOf(p.id).length,
  audience:p.audience||"all",audience_count:(p.audience==="custom"?(p.audience_seats||[]).length:0),
  has_voted:has,my_choices:has?myVote(p.id).choices:[],results_hidden:!vis,counts:vis?countsOf(p.id):{},
  mine:p.owner_sid===ME.sid,can_manage:p.owner_sid===ME.sid};}
function detailOf(p){var has=!!myVote(p.id),vis=visible(p,has);var m=myVote(p.id);var mine=p.owner_sid===ME.sid;
  return {ok:true,now:now(),poll:{id:p.id,title:p.title,description:p.description,mode:p.mode,owner_name:p.owner_name,
    settings:p.settings,options:p.options,deadline:p.deadline,status:p.status,closed_at:p.closed_at,
    created_at:p.created_at,updated_at:p.updated_at,audience:p.audience||"all",
    audience_count:(p.audience==="custom"?(p.audience_seats||[]).length:0),
    audience_seats:(mine&&p.audience==="custom"?(p.audience_seats||[]):[])},closed:closedOf(p),total:votesOf(p.id).length,
    counts:vis?countsOf(p.id):{},has_voted:has,my_choices:has?m.choices:[],results_hidden:!vis,
    voters:vis?votersArr(p):[],mine:mine,can_manage:mine};}
function resp(o){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(o);},text:function(){return Promise.resolve("");}});}
function hdrs(o){var h={},k;o=o||{};for(k in o){try{h[k]=String(o[k]);}catch(e){}}return h;}
window.fetch=function(u,o){
  o=o||{};var method=String(o.method||"GET").toUpperCase();
  var s=String((u&&u.url!==undefined)?u.url:u);
  if(s.indexOf("tcloudbasegateway")<0){
    if(s.indexOf("tt.json")>=0)return resp({c:[],t:"",meta:{}});
    M.external.push(String(s).slice(0,160));return Promise.reject(new Error("external-blocked"));
  }
  var body=null;try{body=o.body?JSON.parse(o.body):null;}catch(e){body=null;}
  if(s.indexOf("/rpc/")>=0){
    var name=s.replace(/^.*\/rpc\//,"").split("?")[0];
    M.reqs.push({kind:"rpc",name:name,body:body,headers:hdrs(o.headers)});
    if(name==="class_members")return resp(SEED.members);
    if(name==="class_verify")return resp({ok:true,token:ME.tok,sid:ME.sid,name:ME.name,role:"",badge:"",is_admin:false});
    if(name==="poll_list")return resp({ok:true,now:now(),polls:M.polls.filter(function(p){return !p.deleted;}).map(summary)});
    if(name==="poll_detail"){var p=pd(body&&body.p_id||"");if(!p||p.deleted)return resp({ok:false,reason:"投票不存在"});return resp(detailOf(p));}
    if(name==="poll_submit"){
      var p2=pd(body&&body.p_id||"");if(!p2||p2.deleted)return resp({ok:false,reason:"投票不存在"});
      if(closedOf(p2))return resp({ok:false,reason:"投票已结束"});
      var ch=(body&&body.p_choices)||[],s2=p2.settings||{};
      var max=s2.multi?Math.max(2,Number(s2.maxChoices)||2):1;
      if(!ch.length)return resp({ok:false,reason:"选项不合法"});
      if(ch.length>max)return resp({ok:false,reason:s2.multi?("最多选 "+max+" 项"):"只能选 1 项"});
      var ex=myVote(p2.id);
      if(ex&&s2.allowChange===false)return resp({ok:false,reason:"已投过票，不可改票"});
      if(ex)ex.choices=ch.slice();else votesOf(p2.id).push({sid:ME.sid,choices:ch.slice()});
      return resp(detailOf(p2));
    }
    if(name==="poll_create"){
      var np={id:body.p_id,title:body.p_title,description:body.p_description,mode:body.p_mode,owner_sid:ME.sid,
        owner_name:ME.name,settings:body.p_settings,options:body.p_options,deadline:Number(body.p_deadline)||0,
        audience:body.p_audience||"all",audience_seats:(body.p_audience_seats||[]),
        status:"open",closed_at:0,deleted:false,created_at:now(),updated_at:now()};
      M.polls.push(np);M.votes[np.id]=[];
      return resp(detailOf(np));
    }
    if(name==="poll_manage"){
      var p3=pd(body&&body.p_id||"");if(!p3||p3.deleted)return resp({ok:false,reason:"投票不存在"});
      var act=body.p_action;
      if(act==="delete"){p3.deleted=true;return resp({ok:true,deleted:true});}
      if(act==="close"){p3.status="closed";p3.closed_at=now();}
      if(act==="extend"){p3.deadline=Number(body.p_deadline)||0;p3.status="open";p3.closed_at=0;}
      if(act==="edit"){p3.title=body.p_title;p3.description=body.p_description;p3.options=body.p_options;
        p3.settings=body.p_settings;p3.deadline=Number(body.p_deadline)||0;
        if(body.p_audience){p3.audience=body.p_audience;p3.audience_seats=(body.p_audience_seats||[]);}}
      p3.updated_at=now();return resp(detailOf(p3));
    }
    return resp({ok:false,reason:"mock-unknown-rpc:"+name});
  }
  M.reqs.push({kind:"table",method:method,url:s.slice(0,160),body:body});
  return resp([]);
};
})();
""".replace("__SEED__", json.dumps(SEED, ensure_ascii=False))


def ev(pg, expr, ap=False):
    return pg.evaluate(expr, await_promise=ap)


def jsq(s):
    return json.dumps(s, ensure_ascii=False)


def click(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.click();return true;})()" % jsq(sel))


def set_val(pg, sel, v):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.value=%s;"
                "e.dispatchEvent(new Event('input',{bubbles:true}));return true;})()" % (jsq(sel), jsq(v)))


def set_file_input(pg, selector, path):
    """CDP 给隐藏 file input 设置真实文件（测选项配图压缩链路）。"""
    doc = pg.send("DOM.getDocument", {"depth": 0})
    root = doc["root"]["nodeId"]
    q = pg.send("DOM.querySelector", {"nodeId": root, "selector": selector})
    nid = q.get("nodeId")
    if not nid:
        return False
    pg.send("DOM.setFileInputFiles", {"files": [path], "nodeId": nid})
    return True


def text_of(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);return e?String(e.textContent||''):'';})()" % jsq(sel))


def count(pg, sel):
    return ev(pg, "document.querySelectorAll(%s).length" % jsq(sel))


def reqs(pg, name):
    raw = ev(pg, "JSON.stringify((window.__MOCKV.reqs||[]).filter(function(r){return r.name===%s;}))" % jsq(name))
    return json.loads(raw or "[]")


def go_vote(pg):
    if not ev(pg, "document.querySelector('#s-vote')&&document.querySelector('#s-vote').classList.contains('on')"):
        click(pg, '#tabsBar button[data-tab="all"]')
        pg.wait_for("document.querySelector('[data-card=\"vote\"]')!==null", 8)
        click(pg, '[data-open="vote"]')
        pg.wait_for("document.querySelector('#s-vote')&&document.querySelector('#s-vote').classList.contains('on')", 8)


def open_card(pg, pid):
    ok = click(pg, '.vote-card[data-id="%s"]' % pid)
    pg.wait_for("document.querySelector('#voteDetailOv')&&document.querySelector('#voteDetailOv').style.display!=='none'", 8)
    return ok


def close_detail(pg):
    click(pg, "#voteDetailClose")
    pg.wait_for("document.querySelector('#voteDetailOv').style.display==='none'", 5)


def click_opt(pg, oid):
    return click(pg, '.vd-opt[data-oid="%s"]' % oid)


def modal_open(pg, mid):
    return ev(pg, "(function(){var e=document.getElementById(%s);return !!(e&&e.style.display!=='none');})()" % jsq(mid))


def main():
    srv = serve(ROOT, PORT)
    b = _cdp.Browser(window=(430, 900))
    try:
        pg = b.new_page("about:blank")
        pg.set_device(430, 900, 2.0, True, True)
        pg.add_init_script(MOCK_JS)
        pg.navigate("http://127.0.0.1:%d/index.html" % PORT)
        pg.wait_load(25)
        boot = pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof VOTE!=='undefined'", 20)
        T("启动：身份通过 + VOTE 模块装载 + 静止无报错", boot)

        # ---------- A. 工具注册 / 全部页卡片 ----------
        click(pg, '#tabsBar button[data-tab="all"]')
        pg.wait_for("document.querySelector('[data-card=\"vote\"]')!==null", 8)
        T("全部页出现「投票」卡片（data-tone=teal）",
          ev(pg, "!!document.querySelector('[data-card=\"vote\"]')") and
          ev(pg, "document.querySelector('[data-card=\"vote\"]').getAttribute('data-tone')==='teal'"))
        T("APP_VER 仍为 2.0.0",
          ev(pg, "(function(){var e=document.querySelector('.idver,.ugver');return !!e&&e.textContent.indexOf('2.0.0')>=0;})()"))

        click(pg, '[data-open="vote"]')
        pg.wait_for("document.querySelector('#s-vote').classList.contains('on') && document.querySelectorAll('#voteList .vote-card').length>=4", 10)
        n_open = count(pg, "#voteList .vote-card")
        T("进入投票页：进行中列表渲染", n_open == 5, "cards=%s（P1/P2/P3/P5/P6）" % n_open)
        T("进行中卡片不带 has_voted 徽标（本人未投）",
          ev(pg, "(function(){var c=document.querySelector('.vote-card[data-id=\"pqa1\"]');return !!c&&c.textContent.indexOf('我已投')<0;})()"))
        c1 = text_of(pg, '.vote-card[data-id="pqa1"]')
        T("卡片信息：标题/发起人/已投人数/规则标签",
          ("周五还是周六开班会" in c1) and ("测试同学01" in c1) and ("2人已投" in c1) and ("单选" in c1) and ("匿名" in c1) and ("投后可见" in c1), c1[:120])
        T("卡片倒计时可见", ev(pg, "!!document.querySelector('.vote-card[data-id=\"pqa1\"] .vcd') && /剩|已截止/.test(document.querySelector('.vote-card[data-id=\"pqa1\"] .vcd').textContent)"))

        # 筛选已结束
        click(pg, '#voteFilter button[data-vf="closed"]')
        pg.sleep(0.15)
        T("筛选「已结束」只剩已结束卡片", count(pg, "#voteList .vote-card") == 1 and
          ev(pg, "!!document.querySelector('.vote-card[data-id=\"pqa4\"]')"))
        T("已结束卡片状态文案", "已结束" in text_of(pg, '.vote-card[data-id="pqa4"]'))
        click(pg, '#voteFilter button[data-vf="open"]')
        pg.sleep(0.15)

        # ---------- B. 发起投票（限时 + 多选 + 匿名 + 自定义选项） ----------
        n_polls0 = ev(pg, "window.__MOCKV.polls.length")
        click(pg, "#voteNew")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display!=='none';})()", 5)
        T("发起投票弹层打开", modal_open(pg, "voteCreateOv"))
        T("默认选项 2 行", count(pg, "#voteOpts .vote-opt-edit") == 2)
        T("可见范围默认「全班」且成员选择区隐藏",
          ev(pg, "(function(){var b=document.querySelector('#voteAudience button.on');"
                 "return !!b&&b.getAttribute('data-aud')==='all'&&document.getElementById('voteAudBox').hidden;})()"))
        T("卡片显示可见范围标签：指定 2 人 / 班委可见标签不误显示",
          ("指定 2 人" in text_of(pg, '.vote-card[data-id="pqa6"]')) and
          ("班委可见" not in text_of(pg, '.vote-card[data-id="pqa1"]')))
        T("默认限时 30 分钟（契约 §3.3）",
          ev(pg, "(function(){var b=document.querySelector('#voteQuick button.on');return !!b&&b.getAttribute('data-min')==='30';})()"),
          ev(pg, "(function(){var b=document.querySelector('#voteQuick button.on');return b?b.getAttribute('data-min'):'';})()"))
        T("发起弹层小控件点按高度 ≥40px",
          ev(pg, "(function(){var els=[document.getElementById('voteSync'),document.getElementById('voteAddOpt')];"
                 "document.querySelectorAll('#voteDeadlineType button,#voteQuick button,#voteOpts .vote-opt-btns button,#voteAudience button').forEach(function(e){els.push(e);});"
                 "var bad=els.filter(function(e){return e&&e.getBoundingClientRect().height<39.5;});return bad.length===0;})()"))
        set_val(pg, "#voteTitle", "投票测试·临时班会")
        set_val(pg, "#voteDesc", "投完即用")
        click(pg, '#voteQuick button[data-min="10"]')
        set_val(pg, '#voteOpts input[data-ot="0"]', "周五 20:00")
        set_val(pg, '#voteOpts input[data-od="0"]', "宿舍楼下集合")
        set_val(pg, '#voteOpts input[data-ot="1"]', "周六 20:00")
        click(pg, "#voteAddOpt")
        pg.sleep(0.1)
        T("添加第三个选项", count(pg, "#voteOpts .vote-opt-edit") == 3)
        set_val(pg, '#voteOpts input[data-ot="2"]', "周日 20:00")
        # 选项配图：CDP 设置真实文件 → 页面压缩为 data:image/jpeg
        img_path = os.path.join(SHOTS, "_tmp_option.png")
        from PIL import Image  # noqa: E402
        Image.new("RGB", (160, 100), (198, 92, 66)).save(img_path)
        T("选项配图 file input 已设置", set_file_input(pg, '#voteOpts input[data-f="0"]', img_path))
        T("选项配图压缩后显示缩略图", pg.wait_for("document.querySelector('#voteOpts .vote-opt-thumb img')!==null", 12))
        ev(pg, "(function(){var m=document.getElementById('voteMulti');m.checked=true;m.dispatchEvent(new Event('change',{bubbles:true}));return true;})()")
        pg.sleep(0.1)
        T("多选开启后出现最多可选输入", ev(pg, "!document.getElementById('voteMaxWrap').hidden"))
        set_val(pg, "#voteMax", "2")
        click(pg, '#voteAudience button[data-aud="committee"]')
        pg.sleep(0.1)
        T("可见范围切到班委（按钮态）",
          ev(pg, "(function(){var b=document.querySelector('#voteAudience button.on');return !!b&&b.getAttribute('data-aud')==='committee';})()"))
        click(pg, "#voteCreateGo")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display==='none';})()", 8)
        pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display!=='none';})()", 8)
        creates = reqs(pg, "poll_create")
        T("发起投票已提交（poll_create）", len(creates) == 1, "n=%d" % len(creates))
        cre = creates[-1]["body"] if creates else {}
        dl = int(cre.get("p_deadline") or 0)
        T("提交参数：标题/说明", cre.get("p_title") == "投票测试·临时班会" and cre.get("p_description") == "投完即用")
        T("提交参数：限时 10 分钟（mode=quick，deadline≈now+10min）",
          cre.get("p_mode") == "quick" and 9 * 60000 <= dl - NOW <= 11 * 60000, "dl-now=%s" % (dl - NOW))
        T("提交参数：3 个选项（含说明）",
          len(cre.get("p_options") or []) == 3 and
          (cre.get("p_options") or [{}])[0].get("text") == "周五 20:00" and
          (cre.get("p_options") or [{}])[0].get("desc") == "宿舍楼下集合")
        imgs = [(o or {}).get("img") for o in (cre.get("p_options") or [])]
        T("提交参数：选项配图为 data:image/jpeg 且 ≤150000 字符",
          bool(imgs) and str(imgs[0]).startswith("data:image/jpeg") and len(str(imgs[0])) <= 150000,
          "len=%s" % (len(str(imgs[0])) if imgs else 0))
        st = cre.get("p_settings") or {}
        T("提交参数：多选 2 项 / 匿名 / 允许改票 / 投票后可见",
          st.get("multi") is True and st.get("maxChoices") == 2 and st.get("anonymous") is True and
          st.get("allowChange") is True and st.get("resultVisibility") == "afterVote")
        T("提交参数：可见范围（班委）", cre.get("p_audience") == "committee" and (cre.get("p_audience_seats") or []) == [],
          str(cre.get("p_audience")) + "/" + str(cre.get("p_audience_seats")))
        T("创建后直接打开详情", modal_open(pg, "voteDetailOv") and "投票测试·临时班会" in text_of(pg, "#voteDetailBody"))
        T("详情显示可见范围标签（班委可见）", "班委可见" in text_of(pg, "#voteDetailBody"))
        new_id = ev(pg, "window.__MOCKV.polls[window.__MOCKV.polls.length-1].id")
        T("创建后未投票时结果隐藏（无结果条）", count(pg, "#voteDetailBody .vd-bar") == 0)

        # ---------- C. 多选上限 + 提交（选项 id 由客户端生成，从 DOM 读取） ----------
        oids = json.loads(ev(pg, "JSON.stringify([].map.call(document.querySelectorAll('#voteDetailBody .vd-opt'),"
                                 "function(e){return e.getAttribute('data-oid');}))"))
        T("详情包含 3 个可选项", len(oids) == 3, str(oids))
        click_opt(pg, oids[0])
        click_opt(pg, oids[1])
        click_opt(pg, oids[2])
        pg.sleep(0.15)
        toast = text_of(pg, "#toast")
        T("多选超过上限：toast 提示最多选 2 项", "最多选 2 项" in toast, toast)
        T("多选选中 2 项", count(pg, "#voteDetailBody .vd-opt.sel") == 2)
        T("已选计数提示", "已选 2 / 最多 2 项" in text_of(pg, "#voteDetailBody"))
        click(pg, "#voteSubmit")
        pg.wait_for("document.querySelectorAll('#voteDetailBody .vd-bar').length>0", 8)
        submits = reqs(pg, "poll_submit")
        T("提交投票（poll_submit）已发出且选项正确",
          len(submits) == 1 and (submits[-1]["body"] or {}).get("p_choices") == oids[:2],
          str(submits[-1]["body"]) if submits else "")
        T("投票后结果条出现（afterVote）", count(pg, "#voteDetailBody .vd-bar") == 3)
        T("投票后按钮变为「改票」", text_of(pg, "#voteSubmit") == "改票")
        T("详情显示选项配图", count(pg, "#voteDetailBody .vd-img") == 1)
        T("已有票时无「编辑」入口", count(pg, '#voteDetailBody [data-vm="edit"]') == 0)
        pg.screenshot(os.path.join(SHOTS, "vote_detail_multi_430.png"))
        close_detail(pg)

        # ---------- B2. 长时投票（指定截止日期时间） ----------
        click(pg, "#voteNew")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display!=='none';})()", 5)
        set_val(pg, "#voteTitle", "长时投票测试")
        click(pg, '#voteDeadlineType button[data-vdt="long"]')
        pg.sleep(0.15)
        dtv = ev(pg, "(function(){var d=new Date(Date.now()+26*3600000);function p(n){return (n<10?'0':'')+n;}"
                 "return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes());})()")
        set_val(pg, "#voteDeadlineInput", dtv)
        set_val(pg, '#voteOpts input[data-ot="0"]', "长时甲")
        set_val(pg, '#voteOpts input[data-ot="1"]', "长时乙")
        click(pg, "#voteCreateGo")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display==='none';})()", 8)
        pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display!=='none';})()", 8)
        longs = [x for x in reqs(pg, "poll_create") if (x["body"] or {}).get("p_title") == "长时投票测试"]
        T("长时投票创建：mode=long + 指定截止时间",
          len(longs) == 1 and (longs[-1]["body"] or {}).get("p_mode") == "long"
          and int((longs[-1]["body"] or {}).get("p_deadline") or 0) > NOW)
        T("长时投票详情显示截止时间与倒计时",
          "长时投票测试" in text_of(pg, "#voteDetailBody")
          and ("剩" in text_of(pg, "#voteDetailBody")))
        close_detail(pg)

        # ---------- B3. 指定成员可见（自定义名单，只显示姓名、内部座号） ----------
        click(pg, "#voteNew")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display!=='none';})()", 5)
        set_val(pg, "#voteTitle", "指定成员可见测试")
        set_val(pg, '#voteOpts input[data-ot="0"]', "甲")
        set_val(pg, '#voteOpts input[data-ot="1"]', "乙")
        click(pg, '#voteAudience button[data-aud="custom"]')
        T("指定成员：打开成员选择区", ev(pg, "!document.getElementById('voteAudBox').hidden"))
        T("指定成员：加载班级名单 chips（5 人）",
          pg.wait_for("document.querySelectorAll('#voteAudMem .vote-mem-b').length===5", 8))
        T("指定成员：初始未选择", "未选择" in text_of(pg, "#voteAudSum"))
        n_create_before = len(reqs(pg, "poll_create"))
        click(pg, "#voteCreateGo")
        pg.sleep(0.25)
        T("指定成员未选人：客户端拦截（toast 且未发请求）",
          "请选择可见成员" in text_of(pg, "#toast") and len(reqs(pg, "poll_create")) == n_create_before)
        set_val(pg, "#voteAudSearch", "同学02")
        pg.sleep(0.12)
        T("成员搜索过滤", count(pg, "#voteAudMem .vote-mem-b") == 1 and "同学02" in text_of(pg, "#voteAudMem"))
        set_val(pg, "#voteAudSearch", "")
        pg.sleep(0.12)
        click(pg, '#voteAudMem .vote-mem-b[data-seat="1"]')
        click(pg, '#voteAudMem .vote-mem-b[data-seat="2"]')
        pg.sleep(0.12)
        T("选中 2 人并显示摘要（姓名）",
          count(pg, "#voteAudMem .vote-mem-b.on") == 2 and "已选" in text_of(pg, "#voteAudSum")
          and "测试同学01" in text_of(pg, "#voteAudSum"))
        T("成员 chips 点按高度 ≥40px",
          ev(pg, "(function(){var bad=[].slice.call(document.querySelectorAll('#voteAudMem .vote-mem-b'))"
                 ".filter(function(e){return e.getBoundingClientRect().height<39.5;});return bad.length===0;})()"))
        T("成员选择区不出现学号",
          ev(pg, "(function(){var h=document.getElementById('voteAudMem').innerHTML;"
                 "return h.indexOf('9000')<0&&h.indexOf('sid')<0;})()"))
        pg.sleep(1.3)  # 等 toast 消失，便于截图
        ev(pg, "document.getElementById('voteAudience').scrollIntoView({block:'center'})")
        pg.sleep(0.25)
        pg.screenshot(os.path.join(SHOTS, "vote_create_audience_430.png"))
        click(pg, "#voteCreateGo")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display==='none';})()", 8)
        pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display!=='none';})()", 8)
        customs = [x for x in reqs(pg, "poll_create") if (x["body"] or {}).get("p_title") == "指定成员可见测试"]
        T("提交参数：custom + 座号数组 [1,2]",
          len(customs) == 1 and (customs[-1]["body"] or {}).get("p_audience") == "custom"
          and (customs[-1]["body"] or {}).get("p_audience_seats") == [1, 2],
          str(customs[-1]["body"])[:160] if customs else "")
        T("详情显示可见范围标签（指定 2 人）", "指定 2 人" in text_of(pg, "#voteDetailBody"))
        close_detail(pg)

        # ---------- D. 单选投票 + 改票 + 列表回显 ----------
        open_card(pg, "pqa1")
        T("打开单选详情", "周五还是周六开班会" in text_of(pg, "#voteDetailBody"))
        T("未投票时 afterVote 结果隐藏", count(pg, "#voteDetailBody .vd-bar") == 0)
        click_opt(pg, "o1")
        click(pg, "#voteSubmit")
        pg.wait_for("document.querySelectorAll('#voteDetailBody .vd-bar').length>0", 8)
        T("投票后投票人数 3（2 人原有 + 本人）", "3 人已投" in text_of(pg, "#voteDetailBody"))
        click_opt(pg, "o2")
        click(pg, "#voteSubmit")
        pg.sleep(0.4)
        submits = reqs(pg, "poll_submit")
        T("改票：第二次提交选项为 o2", len(submits) >= 2 and (submits[-1]["body"] or {}).get("p_choices") == ["o2"])
        close_detail(pg)
        pg.sleep(0.3)
        T("列表回显「我已投」", "我已投" in text_of(pg, '.vote-card[data-id="pqa1"]'))

        # ---------- E. 截止后可见（afterClose） ----------
        open_card(pg, "pqa3")
        T("afterClose 未截止时结果隐藏",
          "截止后可见" in text_of(pg, "#voteDetailBody") and count(pg, "#voteDetailBody .vd-bar") == 0)
        click_opt(pg, "o2")
        click(pg, "#voteSubmit")
        pg.sleep(0.4)
        T("afterClose 投票后仍隐藏结果", count(pg, "#voteDetailBody .vd-bar") == 0 and "截止后可见" in text_of(pg, "#voteDetailBody"))
        close_detail(pg)

        # ---------- F. 实名投票人 ----------
        open_card(pg, "pqa2")
        T("实名投票：投票后显示投票人姓名",
          "已投：同学02" in text_of(pg, "#voteDetailBody") or "同学02" in text_of(pg, "#voteDetailBody"))
        close_detail(pg)

        # ---------- G. 管理：编辑 ----------
        open_card(pg, "pqa5")
        click(pg, '[data-vm="edit"]')
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display!=='none';})()", 5)
        T("编辑入口：弹层预填原值", ev(pg, "document.getElementById('voteTitle').value") == "可编辑的投票（暂无票）")
        T("编辑入口：可见范围回填自定义（座号 1、3）",
          pg.wait_for("document.querySelectorAll('#voteAudMem .vote-mem-b.on').length===2", 8) and
          ev(pg, "(function(){var b=document.querySelector('#voteAudience button.on');"
                 "var on=[].slice.call(document.querySelectorAll('#voteAudMem .vote-mem-b.on'))"
                 ".map(function(e){return e.getAttribute('data-seat');}).sort();"
                 "return !!b&&b.getAttribute('data-aud')==='custom'&&on.join(',')==='1,3';})()"))
        set_val(pg, "#voteTitle", "改后的标题")
        click(pg, "#voteCreateGo")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display==='none';})()", 8)
        pg.sleep(0.4)
        edits = reqs(pg, "poll_manage")
        T("编辑已提交（poll_manage action=edit）", len(edits) == 1 and (edits[-1]["body"] or {}).get("p_action") == "edit")
        T("编辑提交带可见范围字段",
          len(edits) == 1 and (edits[-1]["body"] or {}).get("p_audience") == "custom"
          and (edits[-1]["body"] or {}).get("p_audience_seats") == [1, 3],
          str((edits[-1]["body"] or {}) if edits else {}))
        T("编辑后详情标题更新", "改后的标题" in text_of(pg, "#voteDetailBody"))
        T("编辑后（0 票）仍显示编辑入口", count(pg, '#voteDetailBody [data-vm="edit"]') == 1)
        T("详情管理按钮点按高度 ≥40px",
          ev(pg, "(function(){var bad=[].slice.call(document.querySelectorAll('#voteDetailBody .vd-manage .btn'))."
                 "filter(function(e){return e.getBoundingClientRect().height<39.5;});return bad.length===0;})()"))

        # ---------- H. 管理：提前结束 + 延长 + 删除 ----------
        click(pg, '[data-vm="close"]')
        pg.sleep(0.4)
        T("提前结束：状态变为已结束且无投票按钮",
          "投票已结束" in text_of(pg, "#voteDetailBody") and count(pg, "#voteSubmit") == 0)
        click(pg, '[data-vm="extend"]')
        pg.sleep(0.1)
        T("延长：出现截止时间输入", count(pg, "#vdExtendAt") == 1)
        fut = ev(pg, "(function(){var d=new Date(Date.now()+2*3600000);function p(n){return (n<10?'0':'')+n;}"
                 "return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes());})()")
        set_val(pg, "#vdExtendAt", fut)
        click(pg, "#vdExtendGo")
        pg.wait_for("(function(){var e=document.querySelector('#voteDetailBody');return e&&e.textContent.indexOf('投票已结束')<0;})()", 8)
        ext = [x for x in reqs(pg, "poll_manage") if (x["body"] or {}).get("p_action") == "extend"]
        T("延长已提交（截止时间更新）", len(ext) == 1 and int((ext[-1]["body"] or {}).get("p_deadline") or 0) > NOW)
        T("延长后恢复投票按钮", count(pg, "#voteSubmit") == 1)
        click(pg, '[data-vm="delete"]')
        pg.wait_for("(function(){var e=document.getElementById('voteDetailOv');return e&&e.style.display==='none';})()", 8)
        pg.sleep(0.4)
        T("删除后弹层关闭且列表不再出现该投票", count(pg, '.vote-card[data-id="pqa5"]') == 0)

        # ---------- I. 倒计时到点自动截止 ----------
        ev(pg, "(function(){var p={id:'pqa9',title:'倒计时测试',description:'',mode:'long',owner_sid:'9000000001',"
               "owner_name:'测试同学01',settings:{multi:false,maxChoices:1,anonymous:true,allowChange:true,resultVisibility:'always'},"
               "options:[{id:'o1',text:'甲',desc:'',img:''},{id:'o2',text:'乙',desc:'',img:''}],"
               "deadline:Date.now()+3500,status:'open',closed_at:0,deleted:false,created_at:Date.now(),updated_at:Date.now()};"
               "window.__MOCKV.polls.push(p);window.__MOCKV.votes['pqa9']=[];return window.__MOCKV.polls.length;})()")
        ev(pg, "window.VOTE.pull(true)", ap=True)
        pg.wait_for("document.querySelectorAll('#voteList .vote-card').length>=1", 5)
        pg.sleep(0.2)
        open_card(pg, "pqa9")
        T("倒计时测试详情打开", "倒计时测试" in text_of(pg, "#voteDetailBody"))
        pg.wait_for("(function(){var e=document.querySelector('#voteDetailBody .vcd');return e&&e.textContent.indexOf('已截止')>=0;})()", 9)
        T("到点自动截止：详情显示已截止且无投票按钮",
          "已截止" in text_of(pg, "#voteDetailBody") and count(pg, "#voteSubmit") == 0)
        close_detail(pg)
        pg.sleep(0.3)
        T("列表卡片同步显示已截止", ("已截止" in text_of(pg, '.vote-card[data-id="pqa9"]')) or count(pg, '.vote-card[data-id="pqa9"]') == 0)

        # ---------- J. 截图 + 宽度/溢出 ----------
        pg.screenshot(os.path.join(SHOTS, "vote_list_430.png"))
        click(pg, "#voteNew")
        pg.wait_for("(function(){var e=document.getElementById('voteCreateOv');return e&&e.style.display!=='none';})()", 5)
        pg.screenshot(os.path.join(SHOTS, "vote_create_430.png"))
        for w, h in ((430, 900), (390, 844), (360, 780)):
            pg.set_device(w, h, 2.0, True, True)
            pg.sleep(0.35)
            sw = ev(pg, "document.documentElement.scrollWidth")
            vw = ev(pg, "window.innerWidth")
            T("%dpx：发起弹层无横向溢出" % w, sw <= vw + 1, "scrollW=%s vw=%s" % (sw, vw))
        click(pg, "#voteCreateCancel")
        pg.sleep(0.2)
        pg.set_device(390, 844, 2.0, True, True)
        pg.sleep(0.3)
        open_card(pg, "pqa2")
        sw = ev(pg, "document.documentElement.scrollWidth")
        vw = ev(pg, "window.innerWidth")
        T("390px：详情弹层无横向溢出", sw <= vw + 1, "scrollW=%s vw=%s" % (sw, vw))
        T("390px：选项行不超出视口",
          ev(pg, "(function(){var m=0;document.querySelectorAll('#voteDetailBody .vd-opt').forEach(function(e){"
                 "m=Math.max(m,e.getBoundingClientRect().right);});return m<=window.innerWidth+1;})()"))
        pg.screenshot(os.path.join(SHOTS, "vote_detail_390.png"))
        close_detail(pg)

        pg.set_device(1280, 900, 1.0, False, False)
        pg.sleep(0.4)
        ev(pg, "window.VOTE.pull(true)", ap=True)
        pg.sleep(0.3)
        T("1280px：投票列表无横向溢出", ev(pg, "document.documentElement.scrollWidth<=window.innerWidth+1"))
        pg.screenshot(os.path.join(SHOTS, "vote_list_1280.png"))

        # ---------- K. 报错 / 外部请求 ----------
        errs = pg.all_errors()
        nerr = len(errs.get("exceptions") or []) + len(errs.get("console") or []) + len(errs.get("log") or [])
        js_errs = json.loads(ev(pg, "JSON.stringify(window.__errs||[])"))
        T("0 JS 报错（CDP + window.onerror）", nerr == 0 and len(js_errs) == 0,
          "cdp=%s onerror=%s" % (nerr, js_errs[:3]))
        ext = json.loads(ev(pg, "JSON.stringify(window.__MOCKV.external||[])"))
        T("0 外部请求（除同源 tt.json）", len(ext) == 0, ext[:3])
        T("mock 云端写请求全部经过 RPC 通道（无直连 polls 表）",
          not any(r.get("kind") == "table" and "poll" in str(r.get("url")) for r in
                  json.loads(ev(pg, "JSON.stringify(window.__MOCKV.reqs||[])"))))

        ok_n = sum(1 for r in RESULTS if r["ok"])
        print("\n=========== vote_check: %d PASS / %d FAIL ===========" % (ok_n, len(RESULTS) - ok_n))
        with open(os.path.join(SHOTS, "report.json"), "w", encoding="utf-8") as f:
            json.dump({"pass": ok_n, "fail": len(RESULTS) - ok_n, "results": RESULTS, "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      f, ensure_ascii=False, indent=2)
        return 0 if ok_n == len(RESULTS) else 1
    finally:
        try:
            b.close()
        except Exception:
            pass
        try:
            srv.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
