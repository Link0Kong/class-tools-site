# -*- coding: utf-8 -*-
"""R3 阶段1：基线审计（对当前 web/tools/notice-board-live-demo.html，44 组，只读）。

产出（C:\\briefdesk\\data\\_qa_nottime\\round3\\）：
  - baseline_audit.json：逐卡/逐字段裸时间词命中、chip 动作、内联原文、原始消息按钮条数
  - baseline_audit.md：问题表（汇总/按卡/按字段/重点卡）
  - shots/*.png：重点卡截图（药膳 c0 / 申报合并卡 / 下午招聘会 / 首屏）
做法：复制 demo 到临时目录 + 注入审计脚本（不改源文件），headless Edge 执行，同步 XHR 回传 JSON。
"""
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEMO = os.environ.get("AUDIT_DEMO") or r"C:\Users\Ko_Li\.openclaw\workspace\web\tools\notice-board-live-demo.html"
OUT = os.environ.get("AUDIT_OUT") or r"C:\briefdesk\data\_qa_nottime\round3"
SHOTS = os.path.join(OUT, "shots")
PORT = 0

ERR_JS = r"""
<script>window.__errs=[];window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||"error"));});</script>
"""

AUDIT_JS = r"""
<script>
(function(){
var R={ok:false,now:null,groups:[],hits:[],chipIssues:[],inlineCards:[],keyCards:{},errs:[],stats:{}};
function P(k,ok,note){R.steps=R.steps||[];R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
function norm(s){return String(s==null?"":s).replace(/\s+/g," ").trim();}
var NOW=Date.now(); R.now=NOW; R.nowText=new Date(NOW).toString();
var gs=(typeof GROUPS!=="undefined")?GROUPS:((window.GROUPS)||[]);
R.stats.groups=gs.length;
var origInfo={}; /* gid -> {count: 弹层内原始消息条数, text: 弹层文本} */
function cardOf(id){try{return document.querySelector('.gcard[data-gid="'+id+'"]');}catch(e){return null;}}
function q(sel,root){try{return (root||document).querySelector(sel)}catch(e){return null}}
// ---------------- 裸时间词扫描（契约 §0.1） ----------------
function scanText(text){
  var s=String(text==null?"":text), out=[];
  function add(cat,word,off){out.push({cat:cat,word:word,
    snippet:s.slice(Math.max(0,off-16),Math.min(s.length,off+word.length+20))});}
  var m;
  var reRel=/(大后天|后天|明早|明晚|明天|明日|今晚|今天|今日)/g;
  while((m=reRel.exec(s))){
    if(m[0]==="今日"&&s.slice(m.index+2,m.index+4)==="校园")continue; /* 专名 */
    add("relative",m[0],m.index);
  }
  var reWd=/(?:下|本|这)?(?:周|星期|礼拜)[一二三四五六日天]/g;
  while((m=reWd.exec(s))){
    var off=m.index,before=s.slice(Math.max(0,off-14),off),word=m[0];
    if(/每[^，。；、\s]{0,6}$/.test(before))continue; /* 每周/每月语境 */
    if(/\d{1,2}\s*月\s*\d{1,2}\s*日[^，。；;]{0,10}$/.test(before)||
       /\d{1,2}\s*[-\.]\s*\d{1,2}[^，。；;]{0,10}$/.test(before)){
      add("weekday_annotation",word,off); /* 绝对日期括号注记 → §0.1 需去重 */
    }else add("weekday",word,off);
  }
  var rePer=/(今天)?(上午|中午|下午|晚上|凌晨|今早)/g;
  while((m=rePer.exec(s))){
    var w=m[2]||m[0],off=m.index+(m[1]?3:0);
    var before=s.slice(Math.max(0,off-12),off);
    if(/每天|每周|每月|每日|长期/.test(before))continue;
    if(/\d{1,2}\s*月\s*\d{1,2}\s*日|\d{2}-\d{2}|\d{1,2}\.\d{1,2}/.test(before))continue; /* 已有日期前缀 */
    if(m[1])continue; /* 今天下午 由 relative 捕获 */
    /* 同句已有 MM-DD 且有时钟 HH:MM → 时段词保留（Lead 2026-11-06 白名单，避免误报） */
    var clause=s.slice(0,off).split(/[。；;！？!?\n]/).pop();
    if(/(?:\d{2}-\d{2}|\d{1,2}\s*月\s*\d{1,2}\s*日)/.test(clause)&&/\d{1,2}:\d{2}/.test(clause))continue;
    add("period",w,off);
  }
  var reDay=/(\d{1,2})(号|日)/g;
  while((m=reDay.exec(s))){
    var off2=m.index,before2=s.slice(Math.max(0,off2-12),off2);
    if(/月$/.test(before2))continue;             /* 11月14日：绝对日期 */
    if(/学号|座号|宿舍|楼|班|第|几$/.test(before2.slice(-4)))continue;
    var after=s.slice(off2+m[0].length,off2+m[0].length+8);
    if(!/^\s*(上午|下午|晚上|早上|比赛|活动|当天|点名|中午|凌晨|的|场|日)/.test(after))continue;
    add("daynum",m[0],off2);
  }
  // 专名被错误替换（原「今日校园」→ 10-29校园 等）
  var rePn=/(\d{2}-\d{2}|\d{1,2}月\d{1,2}日|\d{1,2}\.\d{1,2})\s*校园/g;
  while((m=rePn.exec(s))){add("proper_noun_corrupted",m[0],m.index);}
  return out;
}
function fieldScan(g){
  var out=[];
  function scan(field,text){
    var s=String(text==null?"":text);if(!s.trim())return;
    scanText(s).forEach(function(h){h.gid=g.id;h.title=g.title;h.field=field;out.push(h);});
  }
  scan("title",g.title);
  scan("aiSummary",g.aiSummary);
  (g.aiPoints||[]).forEach(function(p,i){scan("aiPoints["+i+"]",p);});
  (g.aiSegments||[]).forEach(function(s,i){scan("aiSegments["+i+"].text",s&&s.text);});
  (g.items||[]).forEach(function(it,i){
    scan("items["+i+"].text",it&&it.text);
    scan("items["+i+"].name",it&&it.name);
    scan("items["+i+"].note",it&&it.note);
    ((it&&it.messages)||[]).forEach(function(m,j){scan("items["+i+"].messages["+j+"]",m&&m.text);});
  });
  (g.messages||[]).forEach(function(m,j){scan("messages["+j+"].text",m&&m.text);});
  return out;
}
// ---------------- chip 动作 ----------------
function chipOf(id){var c=cardOf(id);var s=c?q('.st',c):null;return s?norm(s.textContent):null;}
var ALLOWED_ACTIONS=["报名截止","提交截止","报送截止","投稿截止","缴费截止","选课截止","签到截止","截止",
  "开始","点名","签到","上课","考试","比赛","集合","开会"];
var ACTION_MAP={"报送姓名截止":"报送截止","集合点名":"点名","活动开始":"开始","签到开始":"签到",
  "签到签退":"签到","比赛开始":"比赛","考试开始":"考试","报名已截止":"报名截止"};
function chipAction(label){
  var s=norm(label);
  if(/^长期安排/.test(s))return {action:"",special:"recur"};
  if(s==="无时间"||s==="已处理"||s==="已截止 · 有新名单")return {action:"",special:s};
  var m=/^(?:[1-9]\d* (?:分钟后|小时后|天后)|\d{2}-\d{2} \d{2}:\d{2}) (.+)$/.exec(s);
  if(m)return {action:m[1],special:""};
  return {action:"",special:"format:"+s};
}
function checkChip(g){
  var label=chipOf(g.id);if(label==null)return null;
  var m=chipAction(label);
  var issues=[];
  if(m.special&&m.special.indexOf("format:")===0)issues.push("格式不符:"+label);
  if(m.action){
    if(m.action.length>6)issues.push("动作>6字:"+m.action.length+"字");
    if(m.action.indexOf("已")>=0)issues.push("含「已」:"+m.action);
    if(ACTION_MAP[m.action])issues.push("需缩写:"+m.action+"→"+ACTION_MAP[m.action]);
    if(/(集合点名|活动开始|签到签退|比赛开始|考试开始|报名已截止)/.test(m.action))issues.push("长动作:"+m.action);
    if(ALLOWED_ACTIONS.indexOf(m.action)<0&&m.action.length>4)issues.push("非标准短词:"+m.action);
  }
  return {gid:g.id,title:g.title,label:label,action:m.action,special:m.special,issues:issues};
}
// ---------------- 内联原文检测 ----------------
function firstChars(s,n){var t=norm(s);return t.slice(0,n);}
function stableProbe(t){
  /* 取原文里「第一个时间词之前」的稳定前缀，避免显示层日期替换导致匹配失败 */
  var m=/^(.*?)(大后天|后天|明早|明晚|明天|明日|今晚|今天|今日|本周|这周|下周|周[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天]|\d{1,2}月\d{1,2}日|\d{2}-\d{2}|\d{1,2}号|\d{1,2}日|上午|中午|下午|晚上)/.exec(t);
  var p=m?m[1]:t;
  p=p.replace(/^[\/\s]+/,"").replace(/[，。；、！？\s]+$/,"");
  if(p.length>=6)return p.slice(0,12);
  return t.replace(/^\/[^\s]{1,8}\s*/,"").slice(0,12);
}
function inlineItems(g){
  var c=cardOf(g.id);if(!c)return {inline:0,total:0,hasBtn:false,inlineLabels:[],supInline:0};
  var clone=c.cloneNode(true);
  // 排除标题/摘要/要点/segments/来源/署名/chip，只看时间线内文
  clone.querySelectorAll('.gtitle,.aibrief,.seg-grid,.srcline,.publine,.ghd,.recurline').forEach(function(n){n.parentNode.removeChild(n);});
  var body=norm(clone.textContent);
  var inline=0,labels=[],total=0;
  (g.items||[]).forEach(function(it){
    if(!(it.kind==="text"||it.kind==="follow"))return;
    total++;
    var t=norm(it.text);
    if(!t)return;
    var probe=stableProbe(t);
    if(probe.length>=6&&body.indexOf(probe)>=0){inline++;labels.push(norm(it.label||it.kind));}
  });
  var hasBtn=!!c.querySelector('[data-act="original"]');
  var supInline=(body.match(/补充通知/g)||[]).length;
  return {inline:inline,total:total,hasBtn:hasBtn,inlineLabels:labels,supInline:supInline};
}
// ---------------- 逐卡 ----------------
var domBad=[];
gs.forEach(function(g){
  var c=cardOf(g.id);
  var inline=inlineItems(g);
  var hasSummary=norm(g.aiSummary).length>0;
  var rec={id:g.id,cat:g.cat,title:g.title,titleLen:String(g.title||"").length,
    deadline:g.deadline||null,deadlineAction:g.deadlineAction||null,
    eventAt:g.eventAt||null,eventAction:g.eventAction||null,
    signupStart:g.signupStart||null,signupEnd:g.signupEnd||null,
    recurrence:g.recurrence||null,actionable:g.actionable,
    aiSummary:g.aiSummary||"",aiPoints:(g.aiPoints||[]).slice(0,20),
    aiSegments:(g.aiSegments||[]).map(function(s){return s&&s.text;}).slice(0,20),
    senderName:g.senderName||"",senderRole:g.senderRole||"",senderBadge:g.senderBadge||"",
    itemKinds:(g.items||[]).map(function(it){return it&&it.kind;}),
    itemTexts:(g.items||[]).map(function(it){return norm((it&&(it.text||it.name))||"").slice(0,160);}),
    chip:chipOf(g.id),hasSummary:hasSummary,inline:inline.inline,textItemTotal:inline.total,
    hasOriginalBtn:inline.hasBtn,inlineLabels:inline.inlineLabels,supInline:inline.supInline,
    cardText:norm(c?c.textContent:"").slice(0,600),
    textItemCount:(g.items||[]).filter(function(it){return it.kind==="text"||it.kind==="follow";}).length};
  R.groups.push(rec);
  var hits=fieldScan(g); if(hits.length)R.hits=R.hits.concat(hits);
  var ch=checkChip(g); if(ch&&(ch.issues.length||ch.label!==null)){ if(ch.issues.length)R.chipIssues.push(ch); }
  if(inline.inline>0||inline.supInline>0){
    R.inlineCards.push({id:g.id,title:g.title,inline:inline.inline,total:inline.total,
      labels:inline.inlineLabels,hasSummary:hasSummary,hasBtn:inline.hasBtn,supInline:inline.supInline});
  }
});
// 渲染后正文/弹层扫描（DOM 渲染层）
var renders=[];
gs.forEach(function(g){
  var c=cardOf(g.id);if(!c)return;
  function scanRegion(field,el){
    if(!el)return;
    var s=norm(el.textContent);if(!s)return;
    scanText(s).forEach(function(h){
      renders.push({gid:g.id,title:g.title,region:field,cat:h.cat,word:h.word,snippet:h.snippet});
    });
  }
  scanRegion("rendered_title",c.querySelector('.gtitle'));
  scanRegion("rendered_summary",c.querySelector('.aibrief-sum'));
  scanRegion("rendered_points",c.querySelector('.aipoints'));
  scanRegion("rendered_segments",c.querySelector('.seg-grid'));
  // 原始消息弹层：有按钮才点
  var btn=c.querySelector('[data-act="original"]');
  if(btn){
    try{
      btn.click();
      var box=document.querySelector('#mcard')||document.querySelector('.modal-card');
      var oi=box?box.querySelectorAll('.orig-item'):[];
      origInfo[g.id]={count:oi.length,text:norm(box?box.textContent:"").slice(0,1200)};
      /* 弹层里的「来源/群名」不是原始消息文本（如群名「26级周一89节太极拳」），不参与裸词扫描 */
      if(box){
        var box2=box.cloneNode(true);
        box2.querySelectorAll('.orig-meta,.srcline').forEach(function(n){n.parentNode.removeChild(n);});
        scanRegion("modal",box2);
      }
      var mo=document.querySelector('#modal');if(mo)mo.classList.remove('on');
      var mo2=document.querySelector('.modal');if(mo2)mo2.classList.remove('on');
    }catch(e){}
  }
});
R.hits=R.hits.concat(renders);
// 把弹层条数回填到 groups/key 卡
R.groups.forEach(function(rec){
  var oi=origInfo[rec.id];
  rec.origItemCount=oi?oi.count:null;
  rec.modalText=oi?oi.text:"";
});
// 统计
var cats={};
R.hits.forEach(function(h){cats[h.cat]=(cats[h.cat]||0)+1;});
R.stats.hitByCat=cats;
R.stats.hitTotal=R.hits.length;
var gids={};R.hits.forEach(function(h){gids[h.gid]=1;});
R.stats.hitGroups=Object.keys(gids).length;
R.stats.chipIssueCards=R.chipIssues.length;
R.stats.inlineCards=R.inlineCards.length;
// 重点卡
["g_wxg_c66a85ae46","g_qqimg_6d052014c3","g_qqimg_def2524e9f","g_ideology","g_dorm",
 "g_qqm_7704134971497063025_c0","g_ait_5396a55f24","g_ait_7a3370c5a7","g_ait_7ebae6c1da",
 "g_ait_c6da6536ac","g_ait_4a2dcb5dfe","g_ait_d3117057d2"].forEach(function(id){
  var g=null;gs.forEach(function(x){if(x.id===id)g=x;});
  var c=g?cardOf(id):null;
  if(!g){R.keyCards[id]={missing:true};return;}
  var inline=inlineItems(g);
  R.keyCards[id]={title:g.title,chip:chipOf(id),deadline:g.deadline,deadlineAction:g.deadlineAction,
    eventAt:g.eventAt,eventAction:g.eventAction,signupStart:g.signupStart,signupEnd:g.signupEnd,
    recurrence:g.recurrence,aiSummary:g.aiSummary,aiPoints:g.aiPoints,
    aiSegments:(g.aiSegments||[]).map(function(s){return s.text;}),
    items:(g.items||[]).map(function(it){return {kind:it.kind,label:it.label,time:it.time,from:it.from,
      text:norm(it.text||it.name||"").slice(0,200)};}),
    inline:inline.inline,hasOriginalBtn:inline.hasBtn,
    origItemCount:(origInfo[id]||{}).count==null?null:(origInfo[id]||{}).count,
    hits:fieldScan(g).map(function(h){return {field:h.field,cat:h.cat,word:h.word,snippet:h.snippet};})};
});
R.domBadCount=0;
R.errs=window.__errs||[];
R.ok=true;
try{
  var x=new XMLHttpRequest();x.open("POST","/_report?slot=baseline_audit",false);
  x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(R));
}catch(e){}
})();
</script>
"""

SHOT_JS = r"""
<script>
(function(){
  var m=/[?&]shot=([A-Za-z0-9_\-]+)/.exec(location.search||'');
  var gid=m?m[1]:'';
  function go(){
    if(typeof GROUPS==="undefined"||typeof groupHTML!=="function"){setTimeout(go,150);return;}
    var g=null;for(var i=0;i<GROUPS.length;i++)if(GROUPS[i].id===gid){g=GROUPS[i];break;}
    if(!g){document.body.innerHTML='<div style="padding:20px;color:#999">MISS '+gid+'</div>';return;}
    var st=document.createElement('style');
    st.textContent='*{animation:none!important;transition:none!important}.gcard{opacity:1!important;transform:none!important;animation:none!important}.gcollapse{max-height:none!important}body{padding:10px 8px 14px;background:#F7F8F8}.brand{display:none}.wrap{max-width:100%;padding:0}';
    document.head.appendChild(st);
    document.body.innerHTML='<div class="wrap" id="qaShotWrap">'+groupHTML(g)+'</div>';
    window.scrollTo(0,0);
  }
  setTimeout(go,450);
})();
</script>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        qs = urllib.parse.urlparse(self.path).query
        m = re.search(r"slot=([A-Za-z0-9_\-]+)", qs)
        slot = m.group(1) if m else "default"
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, slot + ".json"), "wb") as f:
            f.write(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


class Q(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


def run_edge(url, budget=30000, timeout=240, screenshot=None, size="492,1100"):
    prof = tempfile.mkdtemp(prefix="edgeprof_")
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=" + size,
            "--virtual-time-budget=%d" % budget, "--user-data-dir=" + prof]
    if screenshot:
        args.append("--screenshot=" + screenshot)
    args.append(url)
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout)
    finally:
        pass
    # 新版 Edge 的 --screenshot 可能在进程退出后 ~1s 才落盘 → 轮询等待
    if screenshot:
        t0 = time.time()
        while time.time() - t0 < 15 and not os.path.exists(screenshot):
            time.sleep(0.2)
    shutil.rmtree(prof, ignore_errors=True)
    return r


# ---------------- 卡片特写（静态页截图，稳定） ----------------
OVERRIDE_CSS = ("<style>*{animation:none!important;transition:none!important}"
                ".gcard{opacity:1!important;transform:none!important;animation:none!important}"
                ".gcollapse{max-height:none!important}</style>")


def dump_dom(url):
    prof = tempfile.mkdtemp(prefix="edgeprof_")
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--window-size=492,1100", "--virtual-time-budget=30000",
            "--user-data-dir=" + prof, "--dump-dom", url]
    try:
        r = subprocess.run(args, capture_output=True, timeout=240)
        return r.stdout.decode("utf-8", "replace")
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    raw = open(DEMO, encoding="utf-8", errors="replace").read()
    raw2 = raw.replace("</head>", ERR_JS + "</head>", 1) if "</head>" in raw else ERR_JS + raw
    audit = raw2.replace("</body>", AUDIT_JS + "</body>", 1) if "</body>" in raw2 else raw2 + AUDIT_JS
    shot = raw2.replace("</body>", SHOT_JS + "</body>", 1) if "</body>" in raw2 else raw2 + SHOT_JS
    try:
        os.remove(os.path.join(OUT, "baseline_audit.json"))
    except Exception:
        pass
    tmp = tempfile.mkdtemp(prefix="r3audit_")
    srv = None
    try:
        with open(os.path.join(tmp, "demo.html"), "w", encoding="utf-8", newline="") as f:
            f.write(audit)
        with open(os.path.join(tmp, "shot.html"), "w", encoding="utf-8", newline="") as f:
            f.write(shot)
        os.chdir(tmp)
        srv = Q(("127.0.0.1", PORT), Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d/" % port
        print("serving on", base)
        run_edge(base + "demo.html")
        p = os.path.join(OUT, "baseline_audit.json")
        data = None
        t0 = time.time()
        while time.time() - t0 < 30:
            if os.path.exists(p):
                time.sleep(0.25)
                try:
                    data = json.load(open(p, encoding="utf-8"))
                    break
                except Exception:
                    time.sleep(0.3)
            time.sleep(0.2)
        if not data:
            print("[FAIL] 未拿到基线审计报告")
            sys.exit(2)

        # 截图：把目标卡单独渲染成静态页后截图（headless --screenshot 稳定；避免 dump-dom）
        for name, gid in [("card_yaoshan_c0", "g_qqm_7704134971497063025_c0"),
                          ("card_shenbao_5396", "g_ait_5396a55f24"),
                          ("card_c66a85ae46", "g_wxg_c66a85ae46"),
                          ("card_qqimg_6d052014c3", "g_qqimg_6d052014c3")]:
            fp = os.path.join(SHOTS, name + ".png")
            run_edge(base + "shot.html?shot=" + gid, budget=8000, screenshot=fp, size="492,2600")
            print("shot", name, os.path.getsize(fp) if os.path.exists(fp) else "MISS")

        # 写 markdown
        write_md(data)
        print("=" * 60)
        print("baseline audit: %d groups, %d hits (%d groups), chip issues %d, inline cards %d" % (
            data["stats"]["groups"], data["stats"]["hitTotal"], data["stats"]["hitGroups"],
            data["stats"]["chipIssueCards"], data["stats"]["inlineCards"]))
        print("报告：%s" % os.path.join(OUT, "baseline_audit.md"))
        print("=" * 60)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


def write_md(d):
    L = []
    L.append("# R3 阶段1 · 基线审计（当前 demo 44 组，改前）")
    L.append("")
    L.append("- 时间：%s（now=%s）" % (time.strftime("%Y-%m-%d %H:%M:%S"), d.get("nowText")))
    L.append("- 对象：`%s`（只读）" % DEMO)
    L.append("- 判定口径：契约 §0（第三轮补充）")
    L.append("")
    st = d.get("stats") or {}
    L.append("## 汇总")
    L.append("")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append("| 卡数 | %s |" % st.get("groups"))
    L.append("| 裸时间词命中总数 | %s |" % st.get("hitTotal"))
    L.append("| 受影响卡数 | %s |" % st.get("hitGroups"))
    L.append("| 分类命中 | `%s` |" % json.dumps(st.get("hitByCat") or {}, ensure_ascii=False))
    L.append("| chip 动作问题卡 | %s |" % st.get("chipIssueCards"))
    L.append("| 内联原文卡 | %s |" % st.get("inlineCards"))
    L.append("| JS 报错 | %s |" % len(d.get("errs") or []))
    L.append("")
    L.append("## 裸时间词命中明细（逐条 id+字段+原文）")
    L.append("")
    L.append("| # | id | 卡标题 | 字段 | 类型 | 词 | 原文片段 |")
    L.append("|---|---|---|---|---|---|---|")
    for i, h in enumerate(d.get("hits") or []):
        L.append("| %d | %s | %s | %s | %s | %s | %s |" % (
            i + 1, h.get("gid"), (h.get("title") or "")[:24], h.get("field") or h.get("region"),
            h.get("cat"), h.get("word"), (h.get("snippet") or "").replace("|", "/")[:90]))
    L.append("")
    L.append("## chip 动作问题")
    L.append("")
    L.append("| id | 卡标题 | chip | 动作 | 问题 |")
    L.append("|---|---|---|---|---|")
    for c in d.get("chipIssues") or []:
        L.append("| %s | %s | %s | %s | %s |" % (c.get("gid"), (c.get("title") or "")[:22],
                                                c.get("label"), c.get("action"),
                                                "; ".join(c.get("issues") or [])))
    L.append("")
    L.append("## 内联原始消息的卡（应全部收进「原始消息」按钮）")
    L.append("")
    L.append("| id | 卡标题 | 有 aiSummary | 内联 text/follow 数 | 内联「补充通知」标记 | 按钮 | 内联行类型 |")
    L.append("|---|---|---|---|---|---|---|")
    for c in d.get("inlineCards") or []:
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (c.get("id"), (c.get("title") or "")[:24],
                                                    c.get("hasSummary"), c.get("inline"),
                                                    c.get("supInline"),
                                                    "有" if c.get("hasBtn") else "无",
                                                    ",".join(c.get("labels") or [])))
    L.append("")
    L.append("## 重点卡现状")
    L.append("")
    for k, v in (d.get("keyCards") or {}).items():
        L.append("### %s" % k)
        L.append("")
        if v.get("missing"):
            L.append("- **MISSING**")
            L.append("")
            continue
        L.append("- 标题：`%s`（%s 字）" % (v.get("title"), len(str(v.get("title") or ""))))
        L.append("- chip：`%s`；deadline=%s / action=%s；eventAt=%s / action=%s；signup=%s~%s" % (
            v.get("chip"), v.get("deadline"), v.get("deadlineAction"), v.get("eventAt"),
            v.get("eventAction"), v.get("signupStart"), v.get("signupEnd")))
        L.append("- aiSummary：`%s`" % v.get("aiSummary"))
        L.append("- aiPoints：`%s`" % json.dumps(v.get("aiPoints"), ensure_ascii=False))
        L.append("- aiSegments：`%s`" % json.dumps(v.get("aiSegments"), ensure_ascii=False))
        L.append("- 内联 text/follow：%s；原始消息按钮：%s" % (v.get("inline"), v.get("hasOriginalBtn")))
        if v.get("hits"):
            L.append("- 裸词命中：`%s`" % json.dumps(v.get("hits"), ensure_ascii=False))
        L.append("")
    L.append("## 截图")
    L.append("")
    for f in sorted(os.listdir(SHOTS)) if os.path.isdir(SHOTS) else []:
        if f.endswith(".png"):
            L.append("- shots/%s" % f)
    L.append("")
    L.append("## 逐卡总表（id | chip | 动作 | 标题长度 | 内联数 | 按钮）")
    L.append("")
    L.append("| id | chip | 内联 text/follow | 原始消息按钮 | 标题长度 | 裸词命中卡? |")
    L.append("|---|---|---|---|---|---|")
    hitg = {}
    for h in d.get("hits") or []:
        hitg[h.get("gid")] = 1
    for g in d.get("groups") or []:
        L.append("| %s | %s | %s/%s | %s | %s | %s |" % (
            g.get("id"), g.get("chip"), g.get("inline"), g.get("textItemTotal"),
            "有" if g.get("hasOriginalBtn") else "无", g.get("titleLen"),
            "是" if g.get("id") in hitg else ""))
    open(os.path.join(OUT, "baseline_audit.md"), "w", encoding="utf-8").write("\n".join(L))


if __name__ == "__main__":
    main()
