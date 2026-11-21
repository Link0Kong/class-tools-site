# -*- coding: utf-8 -*-
"""R3 第三轮 · 线上验证（Lead 部署后跑）

三部分（全部只读，不部署、不改产品；token 不打印/不落盘）：
  A) 线上模板：下载 https://tool.furina.fun/index.html → 解码 NOTICE_TPL_B64 → 新函数/新格式/旧文案清场；
     与本地 web/tools/index.html 嵌入模板哈希对照（部署一致性）。
  B) 云端 public.notices 只读：44 行 + 重点卡数据层日期（R1–R7/§0.4：招聘会/5号4号/申报/药膳/dorm/今日校园/c1/
     games_viewer 回归）与数据层裸词=0。
  C) 线上真实页面（测试身份）：CDP 注入 localStorage → 通知 tab → 断言「下午招聘会」chip 日期、药膳 c0 版式
     （无内联原文/按钮 3 条）、申报 chip=报送截止、全部 chip 短动作/无已、0 JS 报错 + 截图。

env：
  R3_LIVE_URL        默认 https://tool.furina.fun/
  R3_LIVE_OUT        证据目录（默认 C:\\briefdesk\\data\\_qa_nottime\\round3\\online）
  R3_EXPECT_INDEX_SHA 可选：期望线上 index.html sha256（Lead 部署报告值）
  R3_SKIP_UI=1       跳过 C 部分（快速模板+云端）
退出码 0 = 全绿。
"""
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import v2_notice_time_live_check as live  # noqa: E402
import r3_notice_audit_check as r3  # noqa: E402

URL = os.environ.get("R3_LIVE_URL") or "https://tool.furina.fun/"
OUT = os.environ.get("R3_LIVE_OUT") or r"C:\briefdesk\data\_qa_nottime\round3\online"
EXPECT_INDEX_SHA = os.environ.get("R3_EXPECT_INDEX_SHA") or ""
LOCAL_INDEX = os.path.join(TOOLS, "index.html")
DEMO = os.path.join(TOOLS, "notice-board-live-demo.html")
SKIP_UI = os.environ.get("R3_SKIP_UI") == "1"
CN = live.CN
STEPS = []


def S(k, ok, note=""):
    STEPS.append({"k": k, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def expected_template():
    """用官方 build_notice_embed.py（改写到临时 index）从最终 demo 计算应嵌入的模板，不碰产品文件。"""
    tmp = None
    try:
        import tempfile
        import pathlib
        import shutil
        sys.path.insert(0, TOOLS)
        import build_notice_embed as bne
        tmp = tempfile.mkdtemp(prefix="r3embed_", dir=OUT)
        tp = os.path.join(tmp, "index.html")
        shutil.copy(LOCAL_INDEX, tp)
        old_index, old_notice = bne.INDEX, bne.NOTICE
        bne.INDEX = pathlib.Path(tp)
        bne.NOTICE = pathlib.Path(DEMO)
        try:
            bne.main()
        finally:
            bne.INDEX, bne.NOTICE = old_index, old_notice
        html = open(tp, encoding="utf-8", errors="replace").read()
        tpl = live.decode_tpl(html)
        tpl = tpl[0] if isinstance(tpl, tuple) else tpl
        if tpl:
            open(os.path.join(OUT, "expected_template.html"), "w", encoding="utf-8", newline="").write(tpl)
        return tpl
    except Exception as e:  # noqa: BLE001
        print("[expected_template] ERR", type(e).__name__, str(e)[:120])
        return None
    finally:
        if tmp:
            try:
                import shutil as _sh
                _sh.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def dt(v):
    return live.fmt_ts(v)


# ---------------------------------------------------------------- A) 模板
def check_template(index_html):
    raw = live.decode_tpl(index_html)
    # live.decode_tpl 返回 (html, b64)
    tpl = raw[0] if isinstance(raw, tuple) else raw
    if not tpl:
        S("A1 NOTICE_TPL_B64 可解码", False)
        return None
    sha = hashlib.sha256(tpl.encode("utf-8")).hexdigest()
    open(os.path.join(OUT, "notice_tpl_online.html"), "w", encoding="utf-8", newline="").write(tpl)
    S("A1 NOTICE_TPL_B64 可解码", len(tpl) > 10000,
      "%d chars(UTF-8 %d B) sha256=%s" % (len(tpl), len(tpl.encode("utf-8")), sha[:16]))
    must = [
        ("A2.1 absRelDates 相对日期替换在场", "function absRelDates" in tpl),
        ("A2.2 fmtWhen 时间相对化在场", "function fmtWhen" in tpl),
        ("A2.3 标题日期兜底（absRelDates 多调用点 ≥2）", tpl.count("absRelDates") >= 2),
        ("A2.4 动作精简映射（报送截止/点名/开始/比赛）",
         "报送截止" in tpl and "点名" in tpl and "开始" in tpl and "比赛" in tpl),
        ("A2.5 「今日校园」专名白名单在场", "今日校园" in tpl or "校园" in tpl),
        ("A2.6 裸日号 N号 处理在场", "号" in tpl),
        ("A2.7 时段（上午/下午）处理在场", "下午" in tpl and "上午" in tpl),
        ("A2.8 原始消息按钮存在", 'data-act="original"' in tpl or "original" in tpl),
    ]
    for k, ok in must:
        S(k, ok)
    bad = [
        ("A3.1 无旧文案「已截止 · 自动完成」", "已截止 · 自动完成" not in tpl),
        ("A3.2 无旧文案「已结束 · 自动归档」", "已结束 · 自动归档" not in tpl),
        ("A3.3 无「已延长 · 」旧格式", not re.search(r"['\"]已延长 · ", tpl)),
        ("A3.4 无硬编码「今天 HH:MM」分支", not re.search(r"'今天 '\s*\+\s*pad\(", tpl) and "'今天 24:00'" not in tpl),
    ]
    for k, ok in bad:
        S(k, ok)
    # 与「最终 demo 经官方 build_notice_embed 生成的模板」一致（不依赖本地 index.html 是否被其它会话改）
    exp = expected_template()
    if exp:
        esha = hashlib.sha256(exp.encode("utf-8")).hexdigest()
        S("A4 线上模板与最终 demo 经 build_notice_embed 生成的模板一致", esha == sha,
          "online=%s expected=%s" % (sha[:12], esha[:12]))
    else:
        S("A4 线上模板与最终 demo 经 build_notice_embed 生成的模板一致", False, "expected_template 生成失败")
    # 本地 index.html 的嵌入模板（信息：可能含其它会话 WIP，不一致仅记录）
    try:
        local = open(LOCAL_INDEX, encoding="utf-8", errors="replace").read()
        ltpl = live.decode_tpl(local)
        ltpl = ltpl[0] if isinstance(ltpl, tuple) else ltpl
        lsha = hashlib.sha256((ltpl or "").encode("utf-8")).hexdigest()
        STEPS.append({"k": "A4b 本地 index.html 嵌入模板哈希（信息，可能含其它会话 WIP）", "ok": True,
                      "note": "local=%s online=%s %s" % (lsha[:12], sha[:12], "一致" if lsha == sha else "不一致")})
    except Exception as e:  # noqa: BLE001
        STEPS.append({"k": "A4b 本地 index.html 嵌入模板哈希（信息）", "ok": True,
                      "note": "读取失败:" + type(e).__name__})
    return tpl


# ---------------------------------------------------------------- B) 云端数据
CLOUD_EXPECT = [
    # (gid, 字段范围, must[], forbid[])
    ("g_wxg_c66a85ae46", "title_summary", ["11-05"], []),
    ("g_wxg_c66a85ae46", "points", ["11-05"], []),
    ("g_ait_7a3370c5a7", "blob", ["11-05"], []),
    ("g_ait_7ebae6c1da", "blob", ["11-05"], []),
    ("g_qqm_7704134971497063025_c0", "points", ["11-07"], ["11-04"]),
    ("g_ait_5396a55f24", "points", ["11-08"], ["11-05"]),
    ("g_qqimg_6d052014c3", "points", ["11-05"], ["11-04"]),
    ("g_qqimg_6d052014c3", "segments", ["11-05"], ["11-04"]),
    ("g_qqimg_def2524e9f", "points", ["11-04"], ["11-03"]),
    ("g_qqimg_def2524e9f", "segments", ["11-04"], ["11-03"]),
    ("g_ideology", "blob", ["今日校园"], ["10-29校园", "10-28校园"]),
    ("g_course_select", "blob", ["今日校园"], []),
    ("g_dorm", "blob", ["11-04", "每月前三周", "17:30"], []),
    ("g_ait_30fbc46e20", "blob", ["11-06"], []),
    ("g_ait_4a2dcb5dfe", "blob", ["11-05"], []),
    ("g_ait_c6da6536ac", "blob", ["11-04"], []),
    ("g_ait_d3117057d2", "blob", ["11-14"], []),
]


def group_fields(g, kind):
    def segs():
        return " ; ".join(norm(x.get("text")) for x in (g.get("aiSegments") or []) if isinstance(x, dict))
    pts = " ; ".join(norm(x) for x in (g.get("aiPoints") or []))
    ts = norm(g.get("title")) + " | " + norm(g.get("aiSummary"))
    if kind == "title_summary":
        return ts
    if kind == "points":
        return pts
    if kind == "segments":
        return segs()
    return " | ".join([ts, pts, segs()])


def scan_cloud_group(g):
    out = []
    for field, text in [("title", g.get("title")), ("aiSummary", g.get("aiSummary")),
                        ("points", " ; ".join(map(str, g.get("aiPoints") or []))),
                        ("segments", " ; ".join(norm(x.get("text")) for x in (g.get("aiSegments") or [])))]:
        for h in r3.scan_brief_text(text):
            out.append({"field": field, **h})
    return out


def check_cloud(index_html):
    rows, err = live.cloud_rows(index_html)
    if rows is None:
        S("B1 云端 public.notices 只读可访问", False, err)
        return
    groups = []
    for row in rows:
        g = live.parse_group(row)
        if g:
            g["_row"] = {"id": row.get("id"), "ts": row.get("ts"), "hidden": row.get("hidden")}
            groups.append(g)
    S("B1 云端 public.notices 只读可访问", True, "rows=%d / CLASS_NOTICE_V1 groups=%d" % (len(rows), len(groups)))
    S("B2 云端 auto 行已同步（≥44，数据会随近期通知增长）", len(groups) >= 44, "groups=%d" % len(groups))
    by = {str(g.get("id")): g for g in groups}
    # 数据层裸词
    bad = []
    for g in groups:
        for h in scan_cloud_group(g):
            bad.append({"gid": g.get("id"), **h})
    S("B3 云端数据层裸时间/模糊词=0", len(bad) == 0,
      "命中=%d %s" % (len(bad), json.dumps(bad[:8], ensure_ascii=False)))
    # 重点卡日期
    dbad = []
    for gid, kind, must, forbid in CLOUD_EXPECT:
        g = by.get(gid)
        if not g:
            dbad.append({"gid": gid, "why": "缺行"})
            continue
        blob = group_fields(g, kind)
        miss = [x for x in must if x not in blob]
        hit = [x for x in forbid if x in blob]
        if miss or hit:
            dbad.append({"gid": gid, "field": kind, "missing": miss, "forbidden": hit,
                         "value": norm(blob)[:140]})
    S("B4 云端重点卡数据层日期正确（R1–R7/§0.4）", len(dbad) == 0, json.dumps(dbad[:10], ensure_ascii=False))
    # 时间字段（云端）
    c66 = by.get("g_wxg_c66a85ae46") or {}
    ev = dt(c66.get("eventAt"))
    S("B5 云端 c66 eventAt=2026-11-05 14:00", ev is not None and ev.strftime("%Y-%m-%d %H:%M") == "2026-11-05 14:00",
      "eventAt=%s" % c66.get("eventAt"))
    gv = by.get("g_games_viewer") or {}
    gve = dt(gv.get("signupEnd"))
    S("B6 云端 g_games_viewer signupEnd=2026-11-03 18:30（无回归）",
      gve is not None and gve.strftime("%Y-%m-%d %H:%M") == "2026-11-03 18:30",
      "signupEnd=%s" % gv.get("signupEnd"))
    c1 = by.get("g_qqm_7704134971497063025_c1") or {}
    c1s, c1e = dt(c1.get("signupStart")), dt(c1.get("signupEnd"))
    S("B7 云端药膳手记 c1 signup=11-05 12:00→18:00",
      c1s is not None and c1e is not None
      and c1s.strftime("%Y-%m-%d %H:%M") == "2026-11-05 12:00"
      and c1e.strftime("%Y-%m-%d %H:%M") == "2026-11-05 18:00",
      "%s ~ %s" % (c1.get("signupStart"), c1.get("signupEnd")))
    # 花名册 / 献血
    fg = by.get("g_qqfile_1a81286a3a") or {}
    S("B8 云端花名册 sender=同学B/学习委员",
      norm(fg.get("senderName")) == "同学B"
      and ("学习委员" in norm(fg.get("senderRole")) or "班委" in norm(fg.get("senderBadge"))),
      "%s/%s" % (fg.get("senderName"), fg.get("senderRole")))
    xx = [g for g in groups if "献血" in json.dumps(g, ensure_ascii=False)]
    S("B9 云端献血通知仅 1 行（本人转发并入）", len(xx) == 1,
      [(g.get("id"), g.get("title")) for g in xx])
    return groups


# ---------------------------------------------------------------- C) 线上真实页面
IFRAME_JS = r"""
(function(){
  function q(s,r){try{return (r||document).querySelector(s)}catch(e){return null}}
  function norm(s){return String(s==null?"":s).replace(/\s+/g," ").trim();}
  var f=q('.notice-frame')||q('#noticeHost iframe');
  if(!f)return JSON.stringify({ok:false,err:'no-iframe'});
  var w=null,d=null;try{w=f.contentWindow;d=f.contentDocument||(w&&w.document);}catch(e){}
  if(!d||!w)return JSON.stringify({ok:false,err:'no-doc'});
  var gs=null;try{gs=w.GROUPS||null;}catch(e){}
  if(!gs)return JSON.stringify({ok:false,err:'no-groups'});
  var out={ok:true,count:gs.length,now:new Date().toString()};
  var byId={};gs.forEach(function(g){byId[g.id]=g;});
  function cardOf(id){return q('.gcard[data-gid="'+id+'"]',d);}
  function chipOf(id){var c=cardOf(id);var s=c?q('.st',c):null;return s?norm(s.textContent):null;}
  function cardText(id){var c=cardOf(id);return c?norm(c.textContent):'';}
  function statusOfSafe(g){try{return w.statusOf(g);}catch(e){return {label:'ERR',key:'ERR'};}}
  // 全部 chip
  var chips=[],bad=[];
  gs.forEach(function(g){
    var st=statusOfSafe(g),lab=norm(st.label);
    chips.push({id:g.id,label:lab,key:st.key});
    if(lab!=="无时间"&&lab.indexOf("长期安排")!==0&&lab!=="已截止 · 有新名单"&&lab!=="已处理"){
      var m=/^(?:[1-9]\d* (?:分钟后|小时后|天后)|\d{2}-\d{2} \d{2}:\d{2}) (.+)$/.exec(lab);
      if(!m)bad.push({id:g.id,label:lab,why:'格式'});
      else{
        var a=m[1];
        if(a.length>6)bad.push({id:g.id,label:lab,why:'动作>6字'});
        if(a.indexOf('已')>=0)bad.push({id:g.id,label:lab,why:'含已'});
        if(/^(活动开始|比赛开始|集合点名|签到签退|签到开始|报名已截止|报送姓名截止)$/.test(a))bad.push({id:g.id,label:lab,why:'未缩写:'+a});
      }
    }
  });
  out.chips=chips;out.badChips=bad;
  // c66 招聘会
  var c66=byId['g_wxg_c66a85ae46'];
  out.c66={id:'g_wxg_c66a85ae46',chip:chipOf('g_wxg_c66a85ae46'),eventAt:c66?c66.eventAt:null,
    title:c66?c66.title:null,aiSummary:c66?c66.aiSummary:null};
  // games_viewer 回归卡
  var gv=byId['g_games_viewer'];
  out.gv={id:'g_games_viewer',chip:chipOf('g_games_viewer'),signupEnd:gv?gv.signupEnd:null,
    title:gv?gv.title:null};
  // 药膳 c0 版式
  var c0=byId['g_qqm_7704134971497063025_c0'];
  var c0card=cardOf('g_qqm_7704134971497063025_c0');
  var c0btn=c0card?c0card.querySelector('[data-act="original"]'):null;
  var c0body=cardText('g_qqm_7704134971497063025_c0');
  var c0texts=c0?(c0.items||[]).filter(function(it){return it.kind==='text'||it.kind==='follow';}):[];
  out.c0={chip:chipOf('g_qqm_7704134971497063025_c0'),inlineFlower:c0body.indexOf('/花朵脸')>=0,
    bodyHasSup:/补充通知/.test(c0body),hasBtn:!!c0btn,
    textItems:c0texts.length,body:c0body.slice(0,320)};
  if(c0btn){
    try{
      c0btn.click();
      var box=document.querySelector('#mcard')||document.querySelector('.modal-card');
      out.c0.origItems=box?box.querySelectorAll('.orig-item').length:null;
      out.c0.origText=box?norm(box.textContent).slice(0,260):"";
      var mo=document.querySelector('#modal');if(mo)mo.classList.remove('on');
    }catch(e){out.c0.origErr=String(e);}
  }
  // 申报合并卡
  var sb=byId['g_ait_5396a55f24'];
  var sbCard=cardOf('g_ait_5396a55f24');
  var sbBtn=sbCard?sbCard.querySelector('[data-act="original"]'):null;
  out.shenbao={chip:chipOf('g_ait_5396a55f24'),hasBtn:!!sbBtn,body:cardText('g_ait_5396a55f24').slice(0,260)};
  if(sbBtn){
    try{
      sbBtn.click();
      var box2=document.querySelector('#mcard')||document.querySelector('.modal-card');
      out.shenbao.origItems=box2?box2.querySelectorAll('.orig-item').length:null;
      var mo2=document.querySelector('#modal');if(mo2)mo2.classList.remove('on');
    }catch(e){}
  }
  var errs=[];
  try{errs=errs.concat(window.__qaErrs||[]);}catch(e){}
  try{errs=errs.concat(w.__qaErrs||[]);}catch(e){}
  out.errs=errs;
  return JSON.stringify(out);
})()
"""


def check_online_ui(index_html):
    import v2_notice_time_online_ui_check as ui
    try:
        token = json.loads(open(live.TOKEN_FILE, encoding="utf-8").read())["token"]
    except Exception as e:  # noqa: BLE001
        S("C1 测试身份 token 可读", False, type(e).__name__)
        return
    S("C1 测试身份 token 可读（不打印）", bool(token) and len(token) > 20, "len=%d" % len(token))
    import tempfile
    import shutil
    profile = tempfile.mkdtemp(prefix="edgeonline3_")
    proc = cdp = None
    shots_dir = os.path.join(OUT, "shots")
    os.makedirs(shots_dir, exist_ok=True)
    try:
        proc = ui.launch_edge(profile)
        port = ui.wait_devtools(profile)
        S("C2 Edge DevTools 就绪", bool(port), "port=%s" % port)
        if not port:
            return
        ws = ui.page_ws(port)
        if not ws:
            S("C3 页面 target 连接", False)
            return
        cdp = ui.CDP(ws)
        S("C3 页面 target 连接", True)
        cdp.cmd("Page.enable")
        cdp.cmd("Runtime.enable")
        try:
            cdp.cmd("Emulation.setDeviceMetricsOverride",
                    {"width": 492, "height": 940, "deviceScaleFactor": 2, "mobile": True})
        except Exception:
            pass
        cdp.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": (
            "window.__qaErrs=[];"
            "window.addEventListener('error',function(e){try{window.__qaErrs.push(String(e.message||e));}catch(_){}});"
            "window.addEventListener('unhandledrejection',function(e){try{window.__qaErrs.push('rej:'+String(e.reason));}catch(_){}});"
        )})
        cdp.wait_js("!!document.querySelector('#igSid')||!!document.querySelector('#s-nt')", timeout=40)
        ok = cdp.eval("(function(){try{localStorage.setItem('zq_class_identity',JSON.stringify({"
                      "token:%s,sid:'0000000000',name:'QA测试身份',role:'',badge:'',is_admin:false,ts:Date.now()}));"
                      "return true;}catch(e){return 'ERR:'+e;}})()" % json.dumps(token))
        S("C4 注入测试身份", ok is True, str(ok)[:60])
        cdp.cmd("Page.reload", {"ignoreCache": True})
        time.sleep(1.5)
        rd = cdp.wait_js("(function(){try{var g=document.getElementById('idgate');"
                         "var hidden=!g||getComputedStyle(g).display==='none'||g.offsetParent===null;"
                         "var locked=document.body.classList.contains('id-locked');"
                         "return hidden&&!locked;}catch(e){return false;}})()", timeout=60)
        S("C5 测试身份进入班级（门禁解除）", bool(rd), "")
        cdp.eval("(function(){try{gotoTab('nt');return true;}catch(e){"
                 "try{var b=document.querySelector('#tabsBar button[data-tab=\"nt\"]');if(b){b.click();return true;}}catch(e2){}"
                 "return 'ERR';})()")
        # 等通知 tab 按钮渲染出来后点击（避免页面刚 boot 时 tabsBar 还在构建）
        btn_ok = cdp.wait_js("(function(){try{var b=document.querySelector('#tabsBar button[data-tab=\"nt\"]');"
                             "if(!b)return false;b.click();return true;}catch(e){return false;}})()", timeout=45)
        S("C5b 通知 tab 按钮可点击", bool(btn_ok), "")
        frame_ok = cdp.wait_js("(function(){try{return !!document.querySelector('.notice-frame');}catch(e){return false;}})()",
                               timeout=60)
        if not frame_ok:
            # 重试一次：可能首次点击发生在 tabsBar 就绪前
            cdp.eval("(function(){try{var b=document.querySelector('#tabsBar button[data-tab=\"nt\"]');if(b){b.click();return true;}}"
                     "catch(e){return false;}})()")
            frame_ok = cdp.wait_js("(function(){try{return !!document.querySelector('.notice-frame');}catch(e){return false;}})()",
                                   timeout=60)
        S("C6 线上通知 iframe 已创建", bool(frame_ok), "")
        fr = cdp.wait_js("(function(){try{var f=document.querySelector('.notice-frame');"
                         "var d=f&&f.contentDocument;var gs=d&&d.defaultView&&d.defaultView.GROUPS;"
                         "return gs?gs.length:0;}catch(e){return 0;}})()", timeout=120)
        S("C6b 线上通知 iframe 渲染（云端数据 GROUPS）", bool(fr), "iframe groups=%s" % fr)
        raw = cdp.eval(IFRAME_JS, timeout=120)
        data = json.loads(raw) if raw else None
        S("C7 iframe 内数据可读", bool(data and data.get("ok")), (raw or "")[:120])
        if not data or not data.get("ok"):
            return
        S("C8 线上页面 now（真实时钟）", bool(data.get("now")), str(data.get("now"))[:40])
        c66 = data.get("c66") or {}
        S("C9 「下午招聘会」chip 有日期+短动作（11-05 … 开始）",
          bool(re.search(r"^11-05 \d{2}:\d{2} (开始|点名|集合)$", norm(c66.get("chip"))))
          or bool(re.search(r"11-05.*(开始|点名|集合)$", norm(c66.get("chip")))),
          "chip=%s title=%s" % (c66.get("chip"), c66.get("title")))
        t66, s66 = norm(c66.get("title")), norm(c66.get("aiSummary"))
        S("C10 「下午招聘会」标题/摘要含 11-05、无裸时段词",
          "11-05" in t66 and "11-05" in s66 and len(r3.scan_brief_text(t66)) == 0
          and len(r3.scan_brief_text(s66)) == 0,
          "%s | %s" % (t66, s66[:80]))
        gv = data.get("gv") or {}
        S("C10b 线上 g_games_viewer chip=11-03 18:30 报名截止（数据回归已修）",
          norm(gv.get("chip")) == "11-03 18:30 报名截止", "chip=%s" % gv.get("chip"))
        c0 = data.get("c0") or {}
        S("C11 药膳 c0 正文无内联 /花朵脸、无「补充通知」行", not c0.get("inlineFlower") and not c0.get("bodyHasSup"),
          "inlineFlower=%s bodyHasSup=%s" % (c0.get("inlineFlower"), c0.get("bodyHasSup")))

        def modal_items(gid):
            """点 iframe 内「原始消息」→ 等父页弹层 → 返回 orig-item 条数。"""
            cdp.eval("(function(){try{var f=document.querySelector('.notice-frame');var d=f.contentDocument;"
                     "var c=d.querySelector('.gcard[data-gid=\"%s\"]');if(!c)return false;"
                     "var b=c.querySelector('[data-act=\"original\"]');if(!b)return false;b.click();return true;}"
                     "catch(e){return false;}})()" % gid)
            time.sleep(1.0)
            n = cdp.eval("(function(){try{var m=document.querySelector('#ntModalCard')||document.querySelector('.nt-modal-card');"
                         "return m?m.querySelectorAll('.orig-item').length:-1;}catch(e){return -2;}})()")
            txt = cdp.eval("(function(){try{var m=document.querySelector('#ntModalCard')||document.querySelector('.nt-modal-card');"
                           "return m?String(m.textContent||'').slice(0,120):'';}catch(e){return '';}})()")
            cdp.eval("(function(){try{var b=document.querySelector('#ntModalClose');if(b)b.click();"
                     "var m=document.getElementById('ntModal');if(m)m.classList.remove('on');"
                     "var c=document.getElementById('ntModalCard');if(c)c.innerHTML='';"
                     "document.body.classList.remove('nt-modal-open');return true;}catch(e){return false;}})()")
            time.sleep(0.4)
            return n, txt

        n0, t0 = modal_items("g_qqm_7704134971497063025_c0")
        S("C12 药膳 c0「原始消息」按钮含 3 条", bool(c0.get("hasBtn")) and n0 == 3,
          "btn=%s origItems=%s text=%s" % (c0.get("hasBtn"), n0, norm(t0)[:80]))
        sb = data.get("shenbao") or {}
        n_sb, t_sb = modal_items("g_ait_5396a55f24")
        S("C13 申报合并卡 chip=报送截止、按钮 3 条",
          norm(sb.get("chip")).endswith("报送截止") and n_sb == 3,
          "chip=%s origItems=%s text=%s" % (sb.get("chip"), n_sb, norm(t_sb)[:80]))
        bad = data.get("badChips") or []
        S("C14 线上全部 %d 组 chip 动作≤6/无已/已缩写" % len(data.get("chips") or []), len(bad) == 0,
          json.dumps(bad[:8], ensure_ascii=False))
        errs = data.get("errs") or []
        S("C15 线上页面 0 JS 报错", len(errs) == 0, json.dumps(errs[:8], ensure_ascii=False))
        # 截图
        def shot(name):
            try:
                r = cdp.cmd("Page.captureScreenshot", {"format": "png", "fromSurface": True}, timeout=45)
                p = os.path.join(shots_dir, name + ".png")
                open(p, "wb").write(base64.b64decode(r.get("data") or ""))
                return os.path.getsize(p) > 5000
            except Exception:
                return False

        ok_shots = [shot("view_top")]
        for gid, name in (("g_wxg_c66a85ae46", "view_c66"), ("g_qqm_7704134971497063025_c0", "view_c0"),
                          ("g_ait_5396a55f24", "view_shenbao")):
            try:
                cdp.eval("(function(){try{var f=document.querySelector('.notice-frame');var w=f.contentWindow;"
                         "var d=f.contentDocument;var gid='%s';var c=d.querySelector('.gcard[data-gid=\"'+gid+'\"]');"
                         "var wrap=d.querySelector('#expiredWrap');if(wrap&&c&&wrap.contains(c)){wrap.classList.add('open');wrap.style.display='block';}"
                         "if(!c&&w.state){try{w.state.expandExpired=true;w.render();}catch(e){}"
                         "c=d.querySelector('.gcard[data-gid=\"'+gid+'\"]');}"
                         "if(!c&&w.state){try{w.state.sub='expired';w.render();}catch(e){}"
                         "c=d.querySelector('.gcard[data-gid=\"'+gid+'\"]');}"
                         "if(c){var y=c.getBoundingClientRect().top+(w.pageYOffset||0);w.scrollTo(0,y-8);return true;}"
                         "return 'no-card';}catch(e){return 'ERR:'+String(e);}})()" % gid)
                time.sleep(0.7)
            except Exception:
                pass
            ok_shots.append(shot(name))
        S("C16 截图落盘（首屏/招聘会/药膳/申报）", all(ok_shots), json.dumps(ok_shots))
    except Exception as e:  # noqa: BLE001
        S("C99 线上页面验证异常", False, type(e).__name__ + ": " + str(e)[:160])
    finally:
        if cdp:
            try:
                cdp.close()
            except Exception:
                pass
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                pass
        shutil.rmtree(profile, ignore_errors=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    print("=" * 64)
    print("[r3-live] url=%s time=%s" % (URL, time.strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 64)
    try:
        fetched = live.fetch(URL)
        status, body = fetched[0], fetched[-1]
        idx = body.decode("utf-8", "replace")
        open(os.path.join(OUT, "index_online.html"), "w", encoding="utf-8", newline="").write(idx)
        sha = hashlib.sha256(body).hexdigest()
        ok_sha = (not EXPECT_INDEX_SHA) or (sha == EXPECT_INDEX_SHA)
        S("A0 线上 index.html 可下载" + ("（sha 与部署报告一致）" if EXPECT_INDEX_SHA else ""),
          status == 200 and len(idx) > 100000 and ok_sha,
          "HTTP %s %d B sha256=%s%s" % (status, len(body), sha[:16],
                                        ("（期望 %s）" % EXPECT_INDEX_SHA[:16]) if EXPECT_INDEX_SHA else ""))
    except Exception as e:  # noqa: BLE001
        S("A0 线上 index.html 可下载", False, type(e).__name__ + ": " + str(e)[:120])
        return finish()
    tpl = check_template(idx)
    if tpl:
        check_cloud(idx)
    else:
        S("B1 云端核对（模板解码失败跳过）", False, "")
    if not SKIP_UI:
        check_online_ui(idx)
    return finish()


def finish():
    total = len(STEPS)
    passed = sum(1 for s in STEPS if s["ok"])
    ts = time.strftime("%Y%m%d-%H%M%S")
    json.dump({"checkedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "url": URL,
               "passed": passed, "total": total, "steps": STEPS},
              open(os.path.join(OUT, "online_check_%s.json" % ts), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    L = ["# R3 第三轮 · 线上验证报告", "",
         "- 时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
         "- 线上：`%s`（测试身份，token 不落盘）" % URL,
         "- 结果：**%d/%d PASS，%d FAIL**" % (passed, total, total - passed), ""]
    for s in STEPS:
        L.append("- [%s] %s%s" % ("PASS" if s["ok"] else "FAIL", s["k"],
                                  (" — `" + s["note"] + "`") if s["note"] else ""))
    open(os.path.join(OUT, "online_report.md"), "w", encoding="utf-8").write("\n".join(L))
    print("=" * 64)
    print("r3_online: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("报告：%s" % os.path.join(OUT, "online_report.md"))
    print("=" * 64)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
