# -*- coding: utf-8 -*-
"""投票功能独立验收 · 网页 UI（headless Edge + CDP + 独立 mock 云端 fixture）。

独立 QA 编写：不引用实现者 vote_check.py 的 fixture/断言；mock 模拟 §2 RPC 语义（列表/详情/投票/
改票/可见性/管理/一人一票），fixture 专门覆盖极端输入：20 选项、标题 80 字、500 字说明、XSS 文本、
超长无空格文本、非法配图、匿名/实名/三种可见性、已结束、管理权限。
真实云端登录冒烟见 vote_qa_live.py。

覆盖：工具注册/列表筛选排序/空态/发起弹层默认值与边界/时限三态/多选上限/选项配图压缩/
      XSS 转义（列表/详情/投票人/新建回显）/长文本换行/360·390·430·1280 无横向溢出/
      点按区域实测/单选投票与改票/百分比结果条/匿名不显示投票人/倒计时到点自动截止且不能提交/
      管理按钮权限与操作/0 JS 报错/0 外部请求/无学号·手机号泄露。

运行：cd web/tools && python tests\\vote_qa_ui.py
截图：tools/tests/_shots_vote_qa/ui_*.png
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
WEB = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.join(WEB, "tools")
QA = os.path.join(HERE, "_qa_v2")
sys.path.insert(0, QA)
import _cdp  # noqa: E402

SHOTS = os.path.join(HERE, "_shots_vote_qa")
os.makedirs(SHOTS, exist_ok=True)
PORT = 8991
NOW = int(time.time() * 1000)
RESULTS = []


def T(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" | " + str(note)) if note else ""))


def jsq(s):
    return json.dumps(s, ensure_ascii=False)


# ---------------------------------------------------------------- fixture
ME = {"sid": "9000000001", "name": "测试同学01"}
NAMES = {"9000000001": "测试同学01", "9000000002": "张三", "9000000003": "李四",
         "9000000004": "王五<img src=x onerror=window.__voterxss=1>"}
TINY_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
            "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
SET_ANON = {"multi": False, "maxChoices": 1, "anonymous": True, "allowChange": True,
            "resultVisibility": "afterVote"}
SET_REAL_ALWAYS = {"multi": True, "maxChoices": 2, "anonymous": False, "allowChange": True,
                   "resultVisibility": "always"}
SET_AFTERCLOSE = {"multi": False, "maxChoices": 1, "anonymous": True, "allowChange": True,
                  "resultVisibility": "afterClose"}


def opt(oid, text, desc="", img=""):
    return {"id": oid, "text": text, "desc": desc, "img": img}


def poll(pid, title, settings, options, deadline=0, *, owner=None, owner_name=None, desc="",
         mode="long", status="open", closed_at=0, created=None):
    o = owner if owner is not None else "9000000002"
    return {"id": pid, "title": title, "description": desc, "mode": mode, "owner_sid": o,
            "owner_name": owner_name if owner_name is not None else NAMES.get(o, "同学"),
            "settings": settings, "options": options, "deadline": deadline, "status": status,
            "closed_at": closed_at, "deleted": False,
            "created_at": created if created is not None else NOW, "updated_at": NOW}


def build_fixture():
    t = NOW
    p1 = poll("pqf01", "周五还是周六开班会", SET_ANON,
              [opt("o1", "周五 19:00"), opt("o2", "周六 19:00")],
              t + 25 * 60 * 1000, mode="quick", created=t - 8000)
    p2 = poll("pqf02", "团日活动去哪（多选·实名）", SET_REAL_ALWAYS,
              [opt("o1", "博物馆", "免费，需预约", TINY_PNG), opt("o2", "公园"), opt("o3", "校园内")],
              t + 2 * 86400000, created=t - 7000)
    p3 = poll("pqf03", "班服颜色（不限时·截止后可见）", SET_AFTERCLOSE,
              [opt("o1", "藏青"), opt("o2", "雾青")], 0, created=t - 6000)
    p4 = poll("pqf04", "已结束的投票", SET_ANON, [opt("o1", "同意"), opt("o2", "不同意")], 0,
              status="closed", closed_at=t - 3600 * 1000, created=t - 5000)
    p5 = poll("pqf05", "可编辑投票（暂无票）", SET_ANON, [opt("o1", "甲"), opt("o2", "乙")],
              t + 3 * 86400000, owner=ME["sid"], owner_name=ME["name"], created=t - 4000)
    p6 = poll("pqf06",
              '<img src=x onerror="window.__xss=1">班会<script>window.__xss2=1</script>',
              {"multi": False, "maxChoices": 1, "anonymous": True, "allowChange": True,
               "resultVisibility": "always"},
              [opt("o1", "<img src=x onerror=window.__xss6=1>甲",
                   "<script>window.__xss7=1</script>补充"),
               opt("o2", "<script>window.__xss8=1</script>乙")],
              0, owner_name='<b onmouseover=window.__xss5=1>发起人</b>',
              desc='<script>window.__xss3=1</script><img src=x onerror=window.__xss4=1>说明',
              created=t - 3000)
    p7 = poll("pqf07", "长" * 80, SET_REAL_ALWAYS,
              [opt("o1", "选" * 80), opt("o2", "乙")], 0,
              desc="描" * 500, created=t - 2000)
    p8 = poll("pqf08", "二十个选项的投票（多选 2 项·匿名）",
              {"multi": True, "maxChoices": 2, "anonymous": True, "allowChange": True,
               "resultVisibility": "afterVote"},
              [opt("o%d" % i, ("选项%d" % i) + ("补" * (79 - len(str(i))))) for i in range(1, 21)],
              t + 86400000, created=t - 1000)
    p11 = poll("pqf11", "我发起的已有票投票", SET_ANON, [opt("o1", "甲"), opt("o2", "乙")],
               t + 2 * 3600 * 1000, owner=ME["sid"], owner_name=ME["name"], created=t - 900)
    p12 = poll("pqf12", "我发起的已结束投票", SET_ANON, [opt("o1", "甲"), opt("o2", "乙")], 0,
               owner=ME["sid"], owner_name=ME["name"], status="closed",
               closed_at=t - 1000, created=t - 800)
    p13 = poll("pqf13", "非法配图不渲染", SET_REAL_ALWAYS,
               [opt("o1", "带外链图", "", "https://evil.example/x.png"),
                opt("o2", "带合法图", "", TINY_PNG)], 0, created=t - 700)
    polls = [p1, p2, p3, p4, p5, p6, p7, p8, p11, p12, p13]
    votes = {
        "pqf01": [{"sid": "9000000002", "choices": ["o1"]}, {"sid": "9000000003", "choices": ["o2"]}],
        "pqf02": [{"sid": "9000000003", "choices": ["o1", "o2"]},
                  {"sid": "9000000004", "choices": ["o2"]}],
        "pqf03": [{"sid": "9000000003", "choices": ["o1"]},
                  {"sid": ME["sid"], "choices": ["o1"]}],
        "pqf04": [{"sid": "9000000002", "choices": ["o1"]},
                  {"sid": "9000000003", "choices": ["o1"]},
                  {"sid": "9000000004", "choices": ["o2"]}],
        "pqf06": [{"sid": "9000000003", "choices": ["o1"]}],
        "pqf11": [{"sid": "9000000002", "choices": ["o1"]},
                  {"sid": "9000000003", "choices": ["o2"]}],
        "pqf12": [{"sid": "9000000002", "choices": ["o1"]}],
    }
    for p in polls:
        votes.setdefault(p["id"], [])
    return {"me": ME, "names": NAMES, "polls": polls, "votes": votes}


MOCK_JS = r"""
(function(){
window.__errs=[];window.__cerrs=[];window.__QAREQ={reqs:[],external:[],creates:[],submits:[],manages:[]};
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var FIX=__FIX__;
var ME=FIX.me;
try{localStorage.setItem("zq_class_identity",JSON.stringify({token:"qa-ui-token",sid:ME.sid,name:ME.name,role:"",badge:"",is_admin:false,ts:Date.now()}));}catch(e){}
var confirmN=0;window.__QA={confirms:0};
window.confirm=function(){window.__QA.confirms++;return true;};
var M={polls:FIX.polls.map(function(p){return JSON.parse(JSON.stringify(p));}),votes:{}};
Object.keys(FIX.votes).forEach(function(k){M.votes[k]=FIX.votes[k].map(function(v){return {sid:v.sid,choices:v.choices.slice()};});});
function now(){return Date.now();}
function pd(id){for(var i=0;i<M.polls.length;i++)if(M.polls[i].id===id&&!M.polls[i].deleted)return M.polls[i];return null;}
function votesOf(id){return M.votes[id]||[];}
function rec(){return window.__QAREQ;}
function myVote(id){var v=votesOf(id);for(var i=0;i<v.length;i++)if(v[i].sid===ME.sid)return v[i];return null;}
function countsOf(id){var c={},v=votesOf(id);v.forEach(function(x){(x.choices||[]).forEach(function(o){c[o]=(c[o]||0)+1;});});return c;}
function closedOf(p){return !!(p.status==="closed"||(Number(p.deadline)>0&&now()>=Number(p.deadline)));}
function visible(p,has){var mode=(p.settings&&p.settings.resultVisibility)||"afterVote";
  if(mode==="always")return true;if(mode==="afterClose")return closedOf(p);return !!has;}
function votersArr(p){var has=!!myVote(p.id);if(!visible(p,has))return [];
  if(p.settings&&p.settings.anonymous)return [];
  return votesOf(p.id).map(function(v){return {name:FIX.names[v.sid]||"同学",choices:v.choices.slice()};});}
function summary(p){var has=!!myVote(p.id),vis=visible(p,has),m=myVote(p.id);
  return {id:p.id,title:p.title,description:p.description,mode:p.mode,owner_name:p.owner_name,
    settings:p.settings,deadline:p.deadline,status:p.status,closed_at:p.closed_at,
    created_at:p.created_at,updated_at:p.updated_at,closed:closedOf(p),total:votesOf(p.id).length,
    has_voted:has,my_choices:has?m.choices.slice():[],results_hidden:!vis,
    counts:vis?countsOf(p.id):{},mine:p.owner_sid===ME.sid,can_manage:p.owner_sid===ME.sid};}
function detailOf(p){var has=!!myVote(p.id),vis=visible(p,has),m=myVote(p.id);
  return {ok:true,now:now(),poll:{id:p.id,title:p.title,description:p.description,mode:p.mode,
    owner_name:p.owner_name,settings:p.settings,options:p.options,deadline:p.deadline,
    status:p.status,closed_at:p.closed_at,created_at:p.created_at,updated_at:p.updated_at},
    closed:closedOf(p),total:votesOf(p.id).length,counts:vis?countsOf(p.id):{},
    has_voted:has,my_choices:has?m.choices.slice():[],results_hidden:!vis,
    voters:vis?votersArr(p):[],mine:p.owner_sid===ME.sid,can_manage:p.owner_sid===ME.sid};}
function resp(o){return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(o);},
  text:function(){return Promise.resolve("");},headers:{get:function(){return "application/json";}}});}
function hdrs(o){var h={},k;o=o||{};for(k in o){try{h[k]=String(o[k]);}catch(e){}}return h;}
window.fetch=function(u,o){
  o=o||{};var method=String(o.method||"GET").toUpperCase();
  var s=String((u&&u.url!==undefined)?u.url:u);
  try{
    var isCloud=s.indexOf("tcloudbasegateway")>=0||s.indexOf("/__cb/")>=0;
    if(!isCloud){
      if(s.indexOf("tt.json")>=0)return resp({c:[],t:"",meta:{}});
      rec().external.push(String(s).slice(0,200));
      return resp([]);
    }
    var body=null;try{body=o.body?JSON.parse(o.body):null;}catch(e){body=null;}
    if(s.indexOf("/rpc/")>=0){
      var name=s.replace(/^.*\/rpc\//,"").split("?")[0];
      rec().reqs.push({kind:"rpc",name:name,headers:hdrs(o.headers)});
      if(name==="class_members")return resp([]);
      if(name==="class_verify")return resp({ok:true,token:"qa-ui-token",sid:ME.sid,name:ME.name,
        role:"",badge:"",is_admin:false});
      if(name==="poll_list"){return resp({ok:true,now:now(),
        polls:M.polls.filter(function(p){return !p.deleted;}).map(summary)});}
      if(name==="poll_detail"){var p=pd(body&&body.p_id||"");
        if(!p)return resp({ok:false,reason:"投票不存在"});return resp(detailOf(p));}
      if(name==="poll_submit"){
        var p2=pd(body&&body.p_id||"");if(!p2)return resp({ok:false,reason:"投票不存在"});
        if(closedOf(p2))return resp({ok:false,reason:"投票已结束"});
        var ch=(body&&body.p_choices)||[],s2=p2.settings||{};
        var mx=s2.multi?Math.max(2,Number(s2.maxChoices)||2):1;
        if(!ch.length)return resp({ok:false,reason:"选项不合法"});
        if(ch.length>mx)return resp({ok:false,reason:s2.multi?("最多选 "+mx+" 项"):"只能选 1 项"});
        var ids=p2.options.map(function(x){return x.id;});
        for(var ci=0;ci<ch.length;ci++){if(ids.indexOf(ch[ci])<0)return resp({ok:false,reason:"选项不合法"});}
        var ex2=myVote(p2.id);
        if(ex2&&s2.allowChange===false)return resp({ok:false,reason:"已投过票，不可改票"});
        if(ex2)ex2.choices=ch.slice();else votesOf(p2.id).push({sid:ME.sid,choices:ch.slice()});
        rec().submits.push({p_id:p2.id,choices:ch.slice()});
        return resp(detailOf(p2));}
      if(name==="poll_create"){
        var np={id:body.p_id,title:body.p_title,description:body.p_description||"",mode:body.p_mode,
          owner_sid:ME.sid,owner_name:ME.name,settings:body.p_settings,options:body.p_options,
          deadline:Number(body.p_deadline)||0,status:"open",closed_at:0,deleted:false,
          created_at:now(),updated_at:now()};
        M.polls.push(np);M.votes[np.id]=[];
        rec().creates.push({p_id:body.p_id,title:body.p_title,desc:body.p_description,
          mode:body.p_mode,options:body.p_options,settings:body.p_settings,deadline:body.p_deadline});
        return resp(detailOf(np));}
      if(name==="poll_manage"){
        var p3=pd(body&&body.p_id||"");if(!p3)return resp({ok:false,reason:"投票不存在"});
        if(p3.owner_sid!==ME.sid)return resp({ok:false,reason:"无权管理该投票"});
        var act=body.p_action;
        rec().manages.push({p_id:p3.id,action:act,title:body.p_title,deadline:body.p_deadline});
        if(act==="delete"){p3.deleted=true;return resp({ok:true,deleted:true});}
        if(act==="close"){p3.status="closed";p3.closed_at=now();}
        else if(act==="extend"){p3.deadline=Number(body.p_deadline)||0;p3.status="open";p3.closed_at=0;}
        else if(act==="edit"){p3.title=body.p_title;p3.description=body.p_description||"";
          p3.options=body.p_options;p3.settings=body.p_settings;p3.deadline=Number(body.p_deadline)||0;}
        else return resp({ok:false,reason:"不支持的操作"});
        p3.updated_at=now();return resp(detailOf(p3));}
      return resp({ok:false,reason:"mock-unknown-rpc:"+name});
    }
    rec().reqs.push({kind:"table",method:method,url:s.slice(0,160),body:body});
    if(method==="GET"||method==="HEAD")return resp([]);
    return resp([]);
  }catch(e){
    window.__errs.push("mock:"+String(e&&e.message||e));
    return resp({ok:false,reason:"mock-exception"});
  }
};
window.__QA.addPoll=function(p){M.polls.push(p);M.votes[p.id]=M.votes[p.id]||[];return M.polls.length;};
window.__QA.setVotes=function(id,v){M.votes[id]=v;};
window.__QA.getPolls=function(){return M.polls.map(function(p){return p.id;});};
window.__QA.setPolls=function(ids){M.all=M.polls.slice();M.polls=M.polls.filter(function(p){return ids.indexOf(p.id)>=0;});};
window.__QA.restorePolls=function(){if(M.all){M.polls=M.all;M.all=null;}};
})();
""".replace("__FIX__", json.dumps(build_fixture(), ensure_ascii=False))


# ---------------------------------------------------------------- 静态服务
class _Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class _Srv(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


def serve(d, p):
    h = lambda *a, **kw: _Q(*a, directory=d, **kw)  # noqa: E731
    s = _Srv(("127.0.0.1", p), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


# ---------------------------------------------------------------- CDP 帮助
def ev(pg, expr, ap=False):
    return pg.evaluate(expr, await_promise=ap)


def click(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;e.click();return true;})()" % jsq(sel))


def set_val(pg, sel, v):
    return ev(pg, "(function(){var e=document.querySelector(%s);if(!e)return false;"
                 "var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value');"
                 "var t=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value');"
                 "if(e.tagName==='TEXTAREA'){t.set.call(e,%s);}else{s.set.call(e,%s);}"
                 "e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));"
                 "return true;})()" % (jsq(sel), jsq(v), jsq(v)))


def text_of(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);return e?String(e.textContent||''):'';})()" % jsq(sel))


def html_of(pg, sel):
    return ev(pg, "(function(){var e=document.querySelector(%s);return e?String(e.innerHTML||''):'';})()" % jsq(sel))


def count(pg, sel):
    return ev(pg, "document.querySelectorAll(%s).length" % jsq(sel))


def modal_open(pg, mid):
    return ev(pg, "(function(){var e=document.getElementById(%s);return !!(e&&e.style.display!=='none');})()" % jsq(mid))


def wait_modal(pg, mid, want=True, timeout=8):
    return pg.wait_for("(function(){var e=document.getElementById(%s);return !!(e&&(e.style.display!=='none')===%s);})()"
                       % (jsq(mid), "true" if want else "false"), timeout)


def reqs(pg, arrname):
    return json.loads(ev(pg, "JSON.stringify(window.__QAREQ.%s||[])" % arrname) or "[]")


def go_vote(pg):
    if not ev(pg, "document.querySelector('#s-vote')&&document.querySelector('#s-vote').classList.contains('on')"):
        click(pg, '#tabsBar button[data-tab="all"]')
        pg.wait_for("document.querySelector('[data-card=\"vote\"]')!==null", 10)
        click(pg, '[data-open="vote"]')
        pg.wait_for("document.querySelector('#s-vote')&&document.querySelector('#s-vote').classList.contains('on')", 10)


def close_detail(pg):
    click(pg, "#voteDetailClose")
    wait_modal(pg, "voteDetailOv", False, 6)


def open_card(pg, pid):
    # 先切回进行中/全部可见的筛选：若卡片不在当前筛选里则切到对应筛选
    if count(pg, '.vote-card[data-id="%s"]' % pid) == 0:
        ev(pg, "(function(){var p=window.VOTE.list().filter(function(x){return x.id===%s;})[0];"
               "if(!p)return false;var b=document.querySelector('#voteFilter button[data-vf=\"'+(p.closed?'closed':'open')+'\"]');"
               "if(b)b.click();return true;})()" % jsq(pid))
        pg.sleep(0.15)
    click(pg, '.vote-card[data-id="%s"]' % pid)
    return wait_modal(pg, "voteDetailOv", True, 8)


def new_poll_modal(pg):
    if modal_open(pg, "voteDetailOv"):
        close_detail(pg)
    click(pg, "#voteNew")
    return wait_modal(pg, "voteCreateOv", True, 6)


def rects(pg, sel):
    return json.loads(ev(pg, "(function(){var out=[];document.querySelectorAll(%s).forEach(function(e){"
                             "var r=e.getBoundingClientRect();out.push({w:Math.round(r.width),h:Math.round(r.height)});});"
                             "return JSON.stringify(out);})()" % jsq(sel)) or "[]")


def main():
    srv = serve(ROOT, PORT)
    b = _cdp.Browser(window=(430, 900))
    try:
        pg = b.new_page("about:blank")
        pg.set_device(430, 900, 2.0, True, True)
        pg.add_init_script(MOCK_JS)
        pg.navigate("http://127.0.0.1:%d/index.html" % PORT)
        pg.wait_load(25)
        ok = pg.wait_for("document.body.classList.contains('auth-pending')===false && typeof VOTE!=='undefined'", 25)
        T("A1 启动：身份通过 + VOTE 模块装载", ok)
        T("A2 APP_VER 仍为 2.0.0（未动版本号）",
          ev(pg, "(function(){var e=document.querySelector('.ugver');return !!e&&e.textContent.indexOf('2.0.0')>=0;})()"))
        # 全部页卡片顺序：water < vote < ppt（全部页进入后才渲染卡片）
        click(pg, '#tabsBar button[data-tab="all"]')
        pg.wait_for("document.querySelector('#allCards [data-card=\"vote\"]')!==null", 10)
        order = json.loads(ev(pg, "(function(){var a=[];document.querySelectorAll('#allCards [data-card]')"
                                  ".forEach(function(e){a.push(e.getAttribute('data-card'));});"
                                  "return JSON.stringify({a:a,iv:a.indexOf('vote'),iw:a.indexOf('water'),ip:a.indexOf('ppt')});})()"))
        T("A3 全部页「投票」卡片存在，位于 water 后 ppt 前",
          order.get("iv", -1) >= 0 and order.get("iw", -1) < order["iv"] and
          (order.get("ip", -1) < 0 or order["iv"] < order["ip"]), str(order.get("a")))
        click(pg, '[data-open="vote"]')
        pg.wait_for("document.querySelector('#s-vote')&&document.querySelector('#s-vote').classList.contains('on')", 10)
        pg.wait_for("document.querySelectorAll('#voteList .vote-card').length>=8", 10)
        # ---------- B. 列表 / 筛选 / 排序 / 空态 ----------
        n_open = count(pg, "#voteList .vote-card")
        T("B1 进入投票页：进行中列表渲染（11 场 fixture 中 9 场进行中）", n_open == 9, "n=%s" % n_open)
        c1 = text_of(pg, '.vote-card[data-id="pqf01"]')
        T("B2 卡片信息完整（标题/发起人/已投人数/规则标签/倒计时）",
          ("周五还是周六开班会" in c1) and ("张三" in c1) and ("2人已投" in c1)
          and ("单选" in c1) and ("匿名" in c1) and ("投后可见" in c1) and ("剩" in c1), c1[:130])
        order_ids = json.loads(ev(pg, "JSON.stringify([].map.call(document.querySelectorAll('#voteList .vote-card'),"
                                     "function(e){return e.getAttribute('data-id');}))"))
        # deadline 升序 + 不限时在后：pqf01(25m) < pqf11(2h) < pqf08(1d) < pqf02(2d) < pqf05(3d) < 不限时
        T("B3 进行中排序：按截止时间升序、不限时在后",
          order_ids[:5] == ["pqf01", "pqf11", "pqf08", "pqf02", "pqf05"] and
          set(order_ids[5:]) == {"pqf03", "pqf06", "pqf07", "pqf13"}, str(order_ids))
        click(pg, '#voteFilter button[data-vf="closed"]')
        pg.sleep(0.2)
        clo = json.loads(ev(pg, "JSON.stringify([].map.call(document.querySelectorAll('#voteList .vote-card'),"
                               "function(e){return e.getAttribute('data-id');}))"))
        T("B4 筛选「已结束」只显示已结束投票", set(clo) == {"pqf04", "pqf12"}, str(clo))
        T("B5 已结束卡片状态文案「已结束」", "已结束" in text_of(pg, '.vote-card[data-id="pqf04"]'))
        click(pg, '#voteFilter button[data-vf="open"]')
        pg.sleep(0.2)
        # 空态：临时清空进行中列表
        ev(pg, "window.__QA.setPolls(['pqf04','pqf12'])")
        ev(pg, "window.VOTE.pull(true)", ap=True)
        pg.sleep(0.2)
        T("B6 空态（进行中）：显示「还没有进行中的投票」",
          ev(pg, "(function(){var e=document.getElementById('voteEmpty');return !!e&&!e.hidden;})()")
          and "还没有进行中的投票" == text_of(pg, "#voteEmptyText"))
        click(pg, '#voteFilter button[data-vf="closed"]')
        pg.sleep(0.15)
        ev(pg, "window.__QA.restorePolls();window.__QA.setPolls(['pqf01'])")
        ev(pg, "window.VOTE.pull(true)", ap=True)
        pg.sleep(0.2)
        T("B7 空态（已结束）：显示「没有已结束的投票」",
          ev(pg, "(function(){var e=document.getElementById('voteEmpty');return !!e&&!e.hidden;})()")
          and "没有已结束的投票" == text_of(pg, "#voteEmptyText"))
        ev(pg, "window.__QA.restorePolls()")
        click(pg, '#voteFilter button[data-vf="open"]')
        ev(pg, "window.VOTE.pull(true)", ap=True)
        pg.sleep(0.2)
        pg.screenshot(os.path.join(SHOTS, "ui_list_430.png"))

        # ---------- C. 发起弹层：默认值 / 属性 / 边界 ----------
        T("C1 发起投票弹层打开、默认 2 行选项", new_poll_modal(pg) and count(pg, "#voteOpts .vote-opt-edit") == 2)
        T("C2 默认值：单选 / 匿名 / 允许改票 / 投票后可见 / 多选上限隐藏",
          ev(pg, "(function(){return !document.getElementById('voteMulti').checked"
                 "&&document.getElementById('voteAnon').checked"
                 "&&document.getElementById('voteChange').checked"
                 "&&document.querySelector('#voteVis button[data-vis=\"afterVote\"]').classList.contains('on')"
                 "&&document.getElementById('voteMaxWrap').hidden;})()"))
        T("C2b 限时默认应为 30 分钟（契约 §3.3）",
          ev(pg, "(function(){var b=document.querySelector('#voteQuick button.on');return !!b&&b.getAttribute('data-min')==='30';})()"),
          "实际选中=%s 分钟" % ev(pg, "(function(){var b=document.querySelector('#voteQuick button.on');return b?b.getAttribute('data-min'):'-';})()"))
        T("C3 maxlength 属性：标题 80 / 说明 500 / 选项文字 80 / 选项说明 200",
          ev(pg, "document.getElementById('voteTitle').getAttribute('maxlength')==='80'")
          and ev(pg, "document.getElementById('voteDesc').getAttribute('maxlength')==='500'")
          and ev(pg, "(function(){var a=document.querySelectorAll('#voteOpts input[data-ot]');var b=document.querySelectorAll('#voteOpts input[data-od]');"
                     "return a.length===2&&b.length===2&&a[0].getAttribute('maxlength')==='80'&&b[0].getAttribute('maxlength')==='200';})()"))
        # 20 个选项
        for _ in range(18):
            click(pg, "#voteAddOpt")
        pg.sleep(0.2)
        T("C4 选项上限 20：添加按钮在 20 个时禁用",
          count(pg, "#voteOpts .vote-opt-edit") == 20 and ev(pg, "document.getElementById('voteAddOpt').disabled"))
        T("C5 选项计数文案 20/20", text_of(pg, "#voteOptCount").strip() == "20/20")
        # 填满 20 个选项文字（用 80 字极限 + 说明）
        ev(pg, "(function(){for(var i=0;i<20;i++){var a=document.querySelector('#voteOpts input[data-ot=\"'+i+'\"]');"
               "var d=document.querySelector('#voteOpts input[data-od=\"'+i+'\"]');"
               "a.value=('选项'+(i+1))+('补'.repeat(78-String(i+1).length));a.dispatchEvent(new Event('input',{bubbles:true}));"
               "d.value='说明'+i;d.dispatchEvent(new Event('input',{bubbles:true}));}return true;})()")
        set_val(pg, "#voteTitle", "二" * 7)   # 14 字
        click(pg, '#voteQuick button[data-min="10"]')
        n_cre = len(reqs(pg, "creates"))
        click(pg, "#voteCreateGo")
        pg.wait_for("document.querySelector('#voteDetailOv')&&document.querySelector('#voteDetailOv').style.display!=='none'", 10)
        creates = reqs(pg, "creates")
        cr = creates[-1] if len(creates) > n_cre else {}
        opts = cr.get("options") or []
        T("C6 20 个选项提交成功：payload 20 项且每项文字 80 字",
          len(opts) == 20 and all(len((o or {}).get("text") or "") == 80 for o in opts)
          and all((o or {}).get("desc") for o in opts), "n=%d" % len(opts))
        T("C7 提交参数：限时 10 分钟（mode=quick，deadline-now≈10min）",
          cr.get("mode") == "quick" and 9 * 60000 <= (int(cr.get("deadline") or 0) - int(time.time() * 1000)) <= 11 * 60000,
          "dl-now=%s" % (int(cr.get("deadline") or 0) - int(time.time() * 1000)))
        new_id = ev(pg, "window.VOTE.detail().poll.id")
        T("C8 创建后自动打开详情（新投票 20 选项全渲染）",
          modal_open(pg, "voteDetailOv") and count(pg, "#voteDetailBody .vd-opt") == 20)
        close_detail(pg)
        # 标题 80 字（成功）+ 81 字（客户端拦截）
        new_poll_modal(pg)
        t80 = "题" * 80
        set_val(pg, "#voteTitle", t80)
        set_val(pg, '#voteOpts input[data-ot="0"]', "甲")
        set_val(pg, '#voteOpts input[data-ot="1"]', "乙")
        n_cre = len(reqs(pg, "creates"))
        click(pg, "#voteCreateGo")
        pg.wait_for("document.querySelector('#voteDetailOv')&&document.querySelector('#voteDetailOv').style.display!=='none'", 10)
        creates = reqs(pg, "creates")
        T("C9 标题 80 字边界：可提交且 payload=80 字",
          len(creates) > n_cre and len(creates[-1].get("title") or "") == 80)
        close_detail(pg)
        new_poll_modal(pg)
        set_val(pg, "#voteTitle", "题" * 81)
        set_val(pg, '#voteOpts input[data-ot="0"]', "甲")
        set_val(pg, '#voteOpts input[data-ot="1"]', "乙")
        n_cre = len(reqs(pg, "creates"))
        click(pg, "#voteCreateGo")
        pg.sleep(0.3)
        T("C10 标题 81 字：客户端拦截（不发请求 + toast「标题不能超过 80 字」）",
          len(reqs(pg, "creates")) == n_cre and "标题不能超过 80 字" in text_of(pg, "#toast"),
          text_of(pg, "#toast")[:60])
        # 指定截止 / 不限时
        click(pg, '#voteDeadlineType button[data-vdt="long"]')
        pg.sleep(0.15)
        T("C11 时限切换「指定截止」：显示 datetime-local 且默认预填未来时间",
          ev(pg, "!document.getElementById('voteLongBox').hidden")
          and bool(ev(pg, "document.getElementById('voteDeadlineInput').value")))
        click(pg, '#voteDeadlineType button[data-vdt="none"]')
        pg.sleep(0.1)
        set_val(pg, "#voteTitle", "不限时投票")
        set_val(pg, '#voteOpts input[data-ot="0"]', "甲")
        set_val(pg, '#voteOpts input[data-ot="1"]', "乙")
        n_cre = len(reqs(pg, "creates"))
        click(pg, "#voteCreateGo")
        pg.wait_for("document.querySelector('#voteDetailOv')&&document.querySelector('#voteDetailOv').style.display!=='none'", 10)
        creates = reqs(pg, "creates")
        T("C12 时限「不限时」：payload deadline=0、mode=long",
          len(creates) > n_cre and int(creates[-1].get("deadline") or 0) == 0 and creates[-1].get("mode") == "long")
        close_detail(pg)
        # 多选上限 + 选项配图
        new_poll_modal(pg)
        ev(pg, "(function(){var m=document.getElementById('voteMulti');m.checked=true;m.dispatchEvent(new Event('change',{bubbles:true}));return true;})()")
        pg.sleep(0.1)
        T("C13 多选开启：显示最多可选输入框", ev(pg, "!document.getElementById('voteMaxWrap').hidden"))
        set_val(pg, "#voteMax", "2")
        set_val(pg, "#voteTitle", "多选上限测试")
        set_val(pg, '#voteOpts input[data-ot="0"]', "甲")
        set_val(pg, '#voteOpts input[data-ot="1"]', "乙")
        img_path = os.path.join(SHOTS, "_tmp_ui_opt.png")
        from PIL import Image  # noqa: E402
        Image.new("RGB", (200, 140), (78, 144, 130)).save(img_path)
        doc = pg.send("DOM.getDocument", {"depth": 0})
        nid = pg.send("DOM.querySelector", {"nodeId": doc["root"]["nodeId"],
                                             "selector": '#voteOpts input[data-f="0"]'}).get("nodeId")
        ev(pg, "(function(){document.querySelector('#voteOpts input[data-f=\"0\"]').removeAttribute('hidden');return true;})()")
        if nid:
            pg.send("DOM.setFileInputFiles", {"files": [img_path], "nodeId": nid})
        got_thumb = pg.wait_for("document.querySelector('#voteOpts .vote-opt-thumb img')!==null", 15)
        T("C14 选项配图：真实文件经 canvas 压缩为 data:image/jpeg 缩略图", got_thumb)
        n_cre = len(reqs(pg, "creates"))
        click(pg, "#voteCreateGo")
        pg.wait_for("document.querySelector('#voteDetailOv')&&document.querySelector('#voteDetailOv').style.display!=='none'", 10)
        creates = reqs(pg, "creates")
        cre = creates[-1] if len(creates) > n_cre else {}
        imgs = [(o or {}).get("img") or "" for o in (cre.get("options") or [])]
        T("C15 配图上传：payload img=data:image/jpeg 且 ≤150000 字符、规则多选 2 项",
          len(creates) > n_cre and str(imgs[0]).startswith("data:image/jpeg") and len(imgs[0]) <= 150000
          and (cre.get("settings") or {}).get("multi") is True
          and (cre.get("settings") or {}).get("maxChoices") == 2,
          "len=%d" % (len(imgs[0]) if imgs else 0))
        close_detail(pg)

        # ---------- D. XSS 转义 ----------
        T("D1 列表 XSS：标题/说明/选项文本被 esc 转义，无注入元素、无脚本执行",
          ev(pg, "(function(){var c=document.querySelector('.vote-card[data-id=\"pqf06\"]');"
                 "if(!c)return false;return c.querySelectorAll('img,script,[onerror],[onmouseover]').length===0"
                 "&&c.textContent.indexOf('<img src=x onerror=')>=0;})()")
          and ev(pg, "typeof window.__xss==='undefined'&&typeof window.__xss2==='undefined'"))
        open_card(pg, "pqf06")
        T("D2 详情 XSS：说明/选项文本转义，无脚本执行、无注入 img",
          ev(pg, "(function(){var b=document.getElementById('voteDetailBody');"
                 "return b.querySelectorAll('script').length===0&&b.querySelectorAll('img:not(.vd-img)').length===0"
                 "&&b.textContent.indexOf('<script>window.__xss3=1</script>')>=0;})()")
          and ev(pg, "typeof window.__xss3==='undefined'&&typeof window.__xss6==='undefined'"
                     "&&typeof window.__xss7==='undefined'"))
        T("D3 发起人姓名 XSS 被转义（无 <b onmouseover> 注入）",
          ev(pg, "(function(){var b=document.getElementById('voteDetailBody');"
                 "return b.querySelectorAll('b[onmouseover]').length===0&&typeof window.__xss5==='undefined';})()"))
        close_detail(pg)
        open_card(pg, "pqf13")
        T("D4 非法配图（https 外链）不渲染 <img>，合法 data:image 渲染",
          ev(pg, "(function(){var i=document.querySelectorAll('#voteDetailBody .vd-img');"
                 "return i.length===1&&/^data:image\\//.test(i[0].getAttribute('src'));})()"))
        close_detail(pg)
        # 新建投票走 XSS 回显
        new_poll_modal(pg)
        set_val(pg, "#voteTitle", '<img src=x onerror=window.__cxss=1>标题<script>window.__cxss2=1</script>')
        set_val(pg, "#voteDesc", '<script>window.__cxss3=1</script>说明')
        set_val(pg, '#voteOpts input[data-ot="0"]', '<img src=x onerror=window.__cxss4=1>甲')
        set_val(pg, '#voteOpts input[data-ot="1"]', '<script>window.__cxss5=1</script>乙')
        click(pg, "#voteCreateGo")
        pg.wait_for("document.querySelector('#voteDetailOv')&&document.querySelector('#voteDetailOv').style.display!=='none'", 10)
        T("D5 新建 XSS 文本回显：详情内转义且 0 脚本执行",
          ev(pg, "(function(){var b=document.getElementById('voteDetailBody');"
                 "return b.querySelectorAll('script,img:not(.vd-img)').length===0;})()")
          and ev(pg, "typeof window.__cxss==='undefined'&&typeof window.__cxss2==='undefined'"
                     "&&typeof window.__cxss3==='undefined'&&typeof window.__cxss4==='undefined'"
                     "&&typeof window.__cxss5==='undefined'"))
        close_detail(pg)
        # 实名投票人姓名 XSS（F2 实名 + always）
        open_card(pg, "pqf02")
        T("D6 实名投票人姓名 XSS 转义（无注入 img，姓名以文本展示）",
          ev(pg, "(function(){var v=document.getElementById('voteDetailBody').querySelectorAll('.vd-voters');"
                 "var n=0;for(var i=0;i<v.length;i++){n+=v[i].querySelectorAll('img,script').length;}return n===0;})()"))
        T("D7 实名结果可见：投票人姓名以文本出现（含 XSS 姓名原文，无注入）",
          "已投：" in text_of(pg, "#voteDetailBody")
          and "李四" in text_of(pg, "#voteDetailBody")
          and "<img src=x onerror=window.__voterxss=1>" in text_of(pg, "#voteDetailBody")
          and ev(pg, "typeof window.__voterxss==='undefined'"))
        close_detail(pg)

        # ---------- E. 溢出 / 点按区域 ----------
        def overflow_at(w, h, note):
            pg.set_device(w, h, 2.0, True, True)
            pg.sleep(0.35)
            sw = ev(pg, "document.documentElement.scrollWidth")
            vw = ev(pg, "window.innerWidth")
            mx = ev(pg, "(function(){var m=0;document.querySelectorAll('#s-vote .vote-card,#s-vote .vote-tags,.vote-hd').forEach(function(e){"
                        "var r=e.getBoundingClientRect();if(r.right>m)m=r.right;});return Math.round(m);})()")
            T(note, sw <= vw + 1 and mx <= vw + 1, "scrollW=%s vw=%s maxRight=%s" % (sw, vw, mx))
            return sw <= vw + 1

        overflow_at(360, 780, "E1 360px：列表页无横向溢出")
        overflow_at(390, 844, "E2 390px：列表页无横向溢出")
        overflow_at(430, 900, "E3 430px：列表页无横向溢出")
        pg.screenshot(os.path.join(SHOTS, "ui_list_responsive.png"))
        # 发起弹层（20 选项）在 360 下
        pg.set_device(360, 780, 2.0, True, True)
        pg.sleep(0.3)
        new_poll_modal(pg)
        for _ in range(18):
            click(pg, "#voteAddOpt")
        pg.sleep(0.3)
        sw = ev(pg, "document.documentElement.scrollWidth")
        vw = ev(pg, "window.innerWidth")
        card_r = ev(pg, "(function(){var c=document.querySelector('#voteCreateOv .vote-mcard');var r=c.getBoundingClientRect();return Math.round(r.right);})()")
        T("E4 360px：发起弹层（20 选项）无横向溢出、弹层卡片在视口内",
          sw <= vw + 1 and card_r <= vw + 1, "scrollW=%s vw=%s cardRight=%s" % (sw, vw, card_r))
        pg.screenshot(os.path.join(SHOTS, "ui_create_20opts_360.png"))
        click(pg, "#voteCreateCancel")
        pg.sleep(0.2)
        # 详情弹层（80 字标题 + 500 字说明 + 20 选项）在 390
        pg.set_device(390, 844, 2.0, True, True)
        pg.sleep(0.3)
        open_card(pg, "pqf07")
        open_card(pg, "pqf08")  # 20 选项
        sw = ev(pg, "document.documentElement.scrollWidth")
        vw = ev(pg, "window.innerWidth")
        mx = ev(pg, "(function(){var m=0;document.querySelectorAll('#voteDetailBody .vd-opt,#voteDetailBody h3').forEach(function(e){"
                    "var r=e.getBoundingClientRect();if(r.right>m)m=r.right;});return Math.round(m);})()")
        T("E5 390px：详情弹层（80 字标题 / 500 字说明 / 20 选项）无横向溢出",
          sw <= vw + 1 and mx <= vw + 1, "scrollW=%s vw=%s maxRight=%s" % (sw, vw, mx))
        pg.screenshot(os.path.join(SHOTS, "ui_detail_390.png"))
        close_detail(pg)
        # 点按区域实测
        pg.set_device(430, 900, 2.0, True, True)
        pg.sleep(0.3)
        new_poll_modal(pg)
        taps = {}
        for sel in ("#voteNew", "#voteSync", '#voteFilter button[data-vf="open"]',
                    "#voteCreateGo", "#voteAddOpt", '#voteDeadlineType button[data-vdt="long"]',
                    "#voteQuick button[data-min=\"30\"]", "#voteOpts .vote-opt-btns button"):
            rs = rects(pg, sel)
            taps[sel] = min([x["h"] for x in rs]) if rs else None
        T("E6 发起弹层主操作点按高度 ≥40px（发起按钮 / 筛选 / 提交）",
          all((taps.get(s) or 0) >= 40 for s in ("#voteNew", '#voteFilter button[data-vf="open"]',
                                                "#voteCreateGo")), str(taps))
        T("E7 发起弹层其它控件点按高度（口径实测，偏离 40px 的进报告 P 级）", True,
          "刷新=%s 加选项=%s 时限=%s 快捷分钟=%s 选项操作=%s" % (taps.get("#voteSync"), taps.get("#voteAddOpt"),
                                                  taps.get('#voteDeadlineType button[data-vdt="long"]'),
                                                  taps.get('#voteQuick button[data-min="30"]'),
                                                  taps.get("#voteOpts .vote-opt-btns button")))
        click(pg, "#voteCreateCancel")
        pg.sleep(0.2)
        open_card(pg, "pqf11")
        dtaps = {}
        for sel in ("#voteSubmit", "#voteDetailClose", "#voteDetailBody .vd-manage button"):
            rs = rects(pg, sel)
            dtaps[sel] = min([x["h"] for x in rs]) if rs else None
        T("E8 详情弹层主操作「提交投票」点按高度 ≥40px", (dtaps.get("#voteSubmit") or 0) >= 40, str(dtaps))
        T("E9 详情弹层管理/关闭按钮点按高度（口径实测，偏离 40px 的进报告 P 级）", True,
          "管理=%s 关闭=%s" % (dtaps.get("#voteDetailBody .vd-manage button"), dtaps.get("#voteDetailClose")))
        close_detail(pg)
        pg.set_device(1280, 900, 1.0, False, False)
        pg.sleep(0.4)
        pg.screenshot(os.path.join(SHOTS, "ui_list_1280.png"))
        T("E11 1280px 桌面：列表无横向溢出", ev(pg, "document.documentElement.scrollWidth<=window.innerWidth+1"))
        T("E10 1280px 桌面：投票卡片双栏排布（AGENTS §25）",
          ev(pg, "(function(){var cs=document.querySelectorAll('#voteList .vote-card');"
                 "if(cs.length<2)return false;var a=cs[0].getBoundingClientRect(),b=cs[1].getBoundingClientRect();"
                 "return Math.abs(a.top-b.top)<4&&b.left>a.right-2;})()"))
        pg.set_device(430, 900, 2.0, True, True)
        pg.sleep(0.3)

        # ---------- F. 投票 / 改票 / 结果 / 可见性 ----------
        open_card(pg, "pqf01")
        T("F1 afterVote 未投票：结果隐藏标签「投票后可见」且无结果条",
          "投票后可见" in text_of(pg, "#voteDetailBody") and count(pg, "#voteDetailBody .vd-bar") == 0)
        click(pg, '.vd-opt[data-oid="o1"]')
        click(pg, "#voteSubmit")
        pg.wait_for("document.querySelectorAll('#voteDetailBody .vd-bar').length>=2", 8)
        submits = reqs(pg, "submits")
        T("F2 单选投票提交（poll_submit o1）并出现结果条",
          any(x.get("p_id") == "pqf01" and x.get("choices") == ["o1"] for x in submits)
          and count(pg, "#voteDetailBody .vd-bar") == 2)
        T("F3 投票后按钮变「改票」", text_of(pg, "#voteSubmit") == "改票")
        T("F4 结果数值正确（percent 文本 67% / 33%；票数 2 / 1）",
          json.loads(ev(pg, "JSON.stringify([].map.call(document.querySelectorAll('#voteDetailBody .vd-nums'),"
                            "function(e){return e.textContent;}))")) == ["2 票67%", "1 票33%"],
          str(ev(pg, "JSON.stringify([].map.call(document.querySelectorAll('#voteDetailBody .vd-nums'),function(e){return e.textContent;}))")))
        f4b_n = count(pg, "#voteDetailBody .vd-pct")
        T("F4b 结果百分比输出契约类名 .vd-pct（契约 §3.4）", f4b_n > 0,
          "n=%d（百分比文本位于 .vd-nums 的 span.vd-pct）" % f4b_n)
        T("F5 结果条宽度与百分比一致",
          ev(pg, "(function(){var rs=document.querySelectorAll('#voteDetailBody .vd-bar i');"
                 "return rs.length===2&&rs[0].style.width==='67%'&&rs[1].style.width==='33%';})()"))
        T("F6 匿名投票：投票后结果可见但完全不显示投票人（无 .vd-voters 与「已投：」）",
          count(pg, "#voteDetailBody .vd-voters") == 0
          and "已投：" not in text_of(pg, "#voteDetailBody"))
        click(pg, '.vd-opt[data-oid="o2"]')
        click(pg, "#voteSubmit")
        pg.sleep(0.4)
        submits = reqs(pg, "submits")
        T("F7 改票：第二次提交 o2 且 counts 替换（total 仍 3）",
          submits[-1].get("choices") == ["o2"] and "3 人已投" in text_of(pg, "#voteDetailBody"))
        close_detail(pg)
        # 多选上限（UI 阻止第 3 项）
        open_card(pg, "pqf08")
        click(pg, '.vd-opt[data-oid="o1"]')
        click(pg, '.vd-opt[data-oid="o2"]')
        click(pg, '.vd-opt[data-oid="o3"]')
        pg.sleep(0.2)
        T("F8 多选第 3 项被 UI 阻止（toast 最多选 2 项，选中仍 2）",
          "最多选 2 项" in text_of(pg, "#toast") and count(pg, "#voteDetailBody .vd-opt.sel") == 2,
          text_of(pg, "#toast")[:40])
        close_detail(pg)
        # afterClose
        open_card(pg, "pqf03")
        T("F9 afterClose：未截止时隐藏结果但回显本人选择（选中项 1）",
          "截止后可见" in text_of(pg, "#voteDetailBody")
          and count(pg, "#voteDetailBody .vd-bar") == 0
          and count(pg, "#voteDetailBody .vd-opt.sel") == 1)
        close_detail(pg)
        # 已结束
        open_card(pg, "pqf04")
        T("F10 已结束投票：无提交按钮、显示「投票已结束」",
          count(pg, "#voteSubmit") == 0 and "投票已结束" in text_of(pg, "#voteDetailBody"))
        close_detail(pg)

        # ---------- G. 倒计时到点自动截止且不能提交 ----------
        # 先切回「进行中」筛选（F10 打开已结束投票时 helper 自动切到了已结束）
        click(pg, '#voteFilter button[data-vf="open"]')
        ev(pg, "window.VOTE.pull(true)", ap=True)
        pg.sleep(0.2)
        ev(pg, "window.__QA.addPoll({id:'pqf09',title:'倒计时自动截止',description:'',mode:'long',"
               "owner_sid:'9000000002',owner_name:'张三',settings:{multi:false,maxChoices:1,anonymous:true,"
               "allowChange:true,resultVisibility:'always'},options:[{id:'o1',text:'甲',desc:'',img:''},"
               "{id:'o2',text:'乙',desc:'',img:''}],deadline:Date.now()+4200,status:'open',closed_at:0,"
               "deleted:false,created_at:Date.now(),updated_at:Date.now()})")
        ev(pg, "window.VOTE.pull(true)", ap=True)
        pg.wait_for("document.querySelector('.vote-card[data-id=\"pqf09\"]')!==null", 6)
        pg.sleep(0.25)
        g1_n = count(pg, '.vote-card[data-id="pqf09"]')
        g1_txt = text_of(pg, '.vote-card[data-id="pqf09"]')
        T("G1 倒计时投票卡片出现且显示剩余时间",
          g1_n == 1 and "剩" in g1_txt, "n=%s txt=%s" % (g1_n, g1_txt[:80]))
        open_card(pg, "pqf09")
        T("G2 倒计时投票详情打开时有提交按钮", count(pg, "#voteSubmit") == 1)
        pg.wait_for("(function(){var e=document.querySelector('#voteDetailBody .vcd');return e&&e.textContent.indexOf('已截止')>=0;})()", 12)
        T("G3 到点自动截止：详情显示「已截止」且提交按钮消失",
          "已截止" in text_of(pg, "#voteDetailBody") and count(pg, "#voteSubmit") == 0)
        n_sub = len(reqs(pg, "submits"))
        click(pg, "#voteDetailBody")
        pg.sleep(0.3)
        T("G4 截止后无法提交（无投票请求发出）", len(reqs(pg, "submits")) == n_sub)
        close_detail(pg)
        pg.sleep(0.3)
        T("G5 列表卡片同步显示截止状态（已截止或移除）",
          count(pg, '.vote-card[data-id="pqf09"]') == 0 or "已截止" in text_of(pg, '.vote-card[data-id="pqf09"]'))

        # ---------- H. 管理按钮权限 / 动作 ----------
        open_card(pg, "pqf05")
        T("H1 本人 + 0 票 + 进行中：编辑/提前结束/延长/删除全部可见",
          count(pg, '#voteDetailBody [data-vm="edit"]') == 1 and count(pg, '#voteDetailBody [data-vm="close"]') == 1
          and count(pg, '#voteDetailBody [data-vm="extend"]') == 1 and count(pg, '#voteDetailBody [data-vm="delete"]') == 1)
        close_detail(pg)
        open_card(pg, "pqf11")
        T("H2 本人 + 已有票：无「编辑」，有结束/延长/删除",
          count(pg, '#voteDetailBody [data-vm="edit"]') == 0 and count(pg, '#voteDetailBody [data-vm="close"]') == 1
          and count(pg, '#voteDetailBody [data-vm="extend"]') == 1 and count(pg, '#voteDetailBody [data-vm="delete"]') == 1)
        close_detail(pg)
        open_card(pg, "pqf12")
        T("H3 本人 + 已结束：无结束/编辑，有延长/删除",
          count(pg, '#voteDetailBody [data-vm="close"]') == 0 and count(pg, '#voteDetailBody [data-vm="edit"]') == 0
          and count(pg, '#voteDetailBody [data-vm="extend"]') == 1 and count(pg, '#voteDetailBody [data-vm="delete"]') == 1)
        close_detail(pg)
        open_card(pg, "pqf01")
        T("H4 非发起人：不出现任何管理按钮", count(pg, "#voteDetailBody [data-vm]") == 0)
        close_detail(pg)
        # 编辑 → 保存
        open_card(pg, "pqf05")
        click(pg, '[data-vm="edit"]')
        pg.wait_for("document.querySelector('#voteCreateOv')&&document.querySelector('#voteCreateOv').style.display!=='none'", 8)
        T("H5 编辑：弹层预填原标题/2 个选项", ev(pg, "document.getElementById('voteTitle').value") == "可编辑投票（暂无票）"
          and count(pg, "#voteOpts .vote-opt-edit") == 2)
        set_val(pg, "#voteTitle", "编辑后的标题")
        click(pg, "#voteCreateGo")
        pg.wait_for("document.querySelector('#voteDetailOv')&&document.querySelector('#voteDetailOv').style.display!=='none'", 8)
        manages = reqs(pg, "manages")
        T("H6 编辑保存：poll_manage action=edit 且详情标题更新",
          any(x.get("action") == "edit" and x.get("title") == "编辑后的标题" for x in manages)
          and "编辑后的标题" in text_of(pg, "#voteDetailBody"))
        # 提前结束 → 延长 → 删除
        click(pg, '[data-vm="close"]')
        pg.sleep(0.4)
        T("H7 提前结束（确认后）：详情变为已结束、无提交按钮",
          "投票已结束" in text_of(pg, "#voteDetailBody") and count(pg, "#voteSubmit") == 0
          and any(x.get("action") == "close" for x in reqs(pg, "manages")))
        click(pg, '[data-vm="extend"]')
        pg.sleep(0.2)
        T("H8 延长：出现截止时间输入框", count(pg, "#vdExtendAt") == 1)
        fut = ev(pg, "(function(){var d=new Date(Date.now()+3*3600000);function p(n){return (n<10?'0':'')+n;}"
                     "return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes());})()")
        set_val(pg, "#vdExtendAt", fut)
        click(pg, "#vdExtendGo")
        pg.wait_for("(function(){var e=document.getElementById('voteDetailBody');return e&&e.textContent.indexOf('投票已结束')<0;})()", 8)
        T("H9 延长/重开成功：恢复提交按钮且提交了未来 deadline",
          count(pg, "#voteSubmit") == 1
          and any(x.get("action") == "extend" and int(x.get("deadline") or 0) > int(time.time() * 1000)
                  for x in reqs(pg, "manages")))
        click(pg, '[data-vm="delete"]')
        wait_modal(pg, "voteDetailOv", False, 8)
        pg.sleep(0.4)
        T("H10 删除（软删）：弹层关闭且列表不再出现该投票",
          count(pg, '.vote-card[data-id="pqf05"]') == 0 and any(x.get("action") == "delete" for x in reqs(pg, "manages")))
        # 编辑预填规则：重新打开 qpf11（有票）确认无编辑入口已测
        T("H11 管理操作均需确认（confirm 被调用次数 ≥2）", ev(pg, "window.__QA.confirms") >= 2,
          "confirms=%s" % ev(pg, "window.__QA.confirms"))

        # ---------- I. 隐私 / 报错 / 请求通道 ----------
        body_text = ev(pg, "document.body.innerText")
        sid_leak = [s for s in NAMES if s in body_text]
        T("I1 页面文本无学号泄露（fixture sid 均不出现）", not sid_leak, str(sid_leak))
        import re
        T("I2 页面文本无手机号（11 位 1[3-9] 开头）泄露", not re.search(r"\b1[3-9]\d{9}\b", body_text or ""))
        T("I3 页面文本无「sid」字段名残留", "sid" not in (body_text or "").lower())
        boot_errs = json.loads(ev(pg, "JSON.stringify({e:window.__errs||[],c:window.__cerrs||[]})"))
        allerr = pg.all_errors()
        T("I4 0 JS 报错（CDP exceptions/console/log + window.onerror）",
          len(allerr.get("exceptions") or []) == 0 and len(allerr.get("console") or []) == 0
          and len(allerr.get("log") or []) == 0 and not boot_errs.get("e") and not boot_errs.get("c"),
          json.dumps({"cdp": {k: (v or [])[:2] for k, v in allerr.items()}, "win": boot_errs})[:300])
        ext = reqs(pg, "external")
        T("I5 0 外部请求（全部请求只到 mock 云端与同源）", len(ext) == 0, str(ext[:3]))
        allreq = reqs(pg, "reqs")
        T("I6 所有云端写只走 RPC（无直连 polls/poll_votes 表写请求）",
          not any(r.get("kind") == "table" and "poll" in str(r.get("url")) for r in allreq))
        T("I7 poll_* RPC 全部带班级身份头（X-Device-Id=qa-ui-token）",
          all((r.get("headers") or {}).get("X-Device-Id") == "qa-ui-token"
              for r in allreq if r.get("kind") == "rpc" and str(r.get("name", "")).startswith("poll_")))
        # 收尾截图
        pg.screenshot(os.path.join(SHOTS, "ui_final_430.png"))
        okn = len([r for r in RESULTS if r["ok"]])
        with open(os.path.join(SHOTS, "ui_report.json"), "w", encoding="utf-8") as f:
            json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "pass": okn,
                       "fail": len(RESULTS) - okn, "results": RESULTS}, f, ensure_ascii=False, indent=2)
        print("\n=========== vote_qa_ui: %d PASS / %d FAIL ===========" % (okn, len(RESULTS) - okn))
        return 0 if okn == len(RESULTS) else 1
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
