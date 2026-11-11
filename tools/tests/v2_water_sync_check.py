# -*- coding: utf-8 -*-
r"""v2_water_sync_check.py —— 水量云同步「用户所有内容」独立浏览器实跑回归（task-2）

独立于 water_check.py / sync_check.py 的专项门禁（只读 index.html，不修改生产文件）。
复用 water_check.py 的 CDP headless-Edge 骨架 + 假身份/CloudBase fetch mock：
  sys.path.insert(0, tests) -> import water_check as W
  本进程自行初始化 W.RUN_TMP / W.PREVIEW / W.BASE，W.build_preview() 后给预览页追加
  * 延迟注入包装（localStorage `__wtDelayGetMs`，仅 userdata GET，一次性）
  * `window.__wt` 测试钩子（UD/WATER/D/POWER）

覆盖「用户所有内容」→ 云同步字段：
  A 本机保存第 1/2 条、删除、4↔6 人间切换 → 等 >1.3s 检查最后一次 POST userdata blob：
    water.rooms[<rv>]={p,recs:[{m,r,ts}]}、at.water 递增且本机赢、14 键键序、
    water 值内不镜像 at、power 共用关注宿舍
  B 新设备（清 localStorage + 云端 ud 种子）：2 间宿舍不同人数/记录自动恢复（含未选中房间）
  C 保存后同一 tick 触发 window pagehide → UD.flush 立即推送不丢（不依赖 1200ms 防抖）
  D 无基线 + boot userdata GET 延迟 ~2.5s 竞态：立即保存记录 → 云端旧值不覆盖、最终 blob 含记录
  E 旧数据无 water（v6 但缺第 11 section）→ 默认 {rooms:{}}、首次保存自动补齐 14 键 water
  F 单间抄表上限 120：云端 130 条 → 只渲染 120；改人数后推送上云裁剪为 120
  G 两账号隔离：A/B 各自 water 数据与 userdata GET 过滤、互不覆盖
  H 远端脏值归一（WATER.normWater）：p 非 4/6 → 4、非法月份/读数丢弃、>120 条裁到 120、
    非对象房间（null/字符串/数组）丢弃；归一后回云 POST 也是归一值（不把脏数据写回）
  Z 全程 0 JS 报错 / 0 console.error / 无外部请求（每个场景 + 汇总）

用法（cwd = web\tools）：
  python tests\v2_water_sync_check.py          # 全量浏览器实跑；退出码 0 = 全绿
  set SPEC_CHECK=<副本.html>                   # 复盘任意 index.html 只读副本
结果 JSON：tools\tests\_water_work\sync_audit_result.json
"""
import functools
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import water_check as W
except Exception:
    print("[v2_water_sync_check] 无法 import water_check：", traceback.format_exc()[-800:])
    sys.exit(2)

WORK = os.path.join(HERE, "_water_work")
RESULT_JSON = os.path.join(WORK, "sync_audit_result.json")
RESULTS = []
GLOBAL = {"errs": [], "cerrs": [], "exts": []}
META = {"before": None, "after": None, "startedAt": None, "durationSec": None, "runTmp": "", "base": ""}

SID_A = W.SID_A
SID_B = W.SID_B
RV321 = W.RV321
RV330 = W.RV330
ATW_SEED = 1762300800000        # 云端 water at 种子（2025-11 附近，早于当前）
ATW_OLD = 1700000000000         # 老旧云端时间戳（LWW 必输）

# ---------------------------------------------------------------------------
# 断言 / 错误采集（独立于 water_check.RESULTS）
# ---------------------------------------------------------------------------
def T(key, ok, note=""):
    RESULTS.append({"k": key, "ok": bool(ok), "note": str(note or "")[:420]})
    print(("[PASS] " if ok else "[FAIL] ") + key + (("  -- " + str(note)[:380]) if note != "" else ""))
    try:
        sys.stdout.flush()
    except Exception:
        pass
    return bool(ok)


def file_meta(path):
    try:
        b = open(path, "rb").read()
        return {"path": path, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
    except Exception as e:
        return {"path": path, "error": str(e)}


def jsq(s):
    return W.jsq(s)


def ev(cdp, expr, timeout=40):
    return W.ev(cdp, expr, timeout=timeout)


def collect(cdp, label):
    """采集当前文档的 JS 错误 / console.error / 外部请求，并累计到 GLOBAL。"""
    errs, cerrs, exts = [], [], []
    try:
        errs = ev(cdp, "window.__errs||[]") or []
    except Exception:
        pass
    try:
        cerrs = ev(cdp, "window.__cerrs||[]") or []
    except Exception:
        pass
    try:
        exts = ev(cdp, W.EXTS_JS) or []
    except Exception:
        pass
    GLOBAL["errs"].extend([str(x) for x in errs])
    GLOBAL["cerrs"].extend([str(x) for x in cerrs])
    GLOBAL["exts"].extend([str(x) for x in exts])
    T(label + "：0 JS 报错", len(errs) == 0, " | ".join([str(x) for x in errs[:3]]))
    T(label + "：0 console.error", len(cerrs) == 0, " | ".join([str(x) for x in cerrs[:3]]))
    T(label + "：无外部请求", len(exts) == 0, " | ".join([str(x) for x in exts[:3]]))


# ---------------------------------------------------------------------------
# 预览页：W.build_preview() + 延迟注入包装 + 测试钩子（只写 _water_tmp 子目录）
# ---------------------------------------------------------------------------
DELAY_WRAP = r"""<script>
(function(){
  window.__wtDelayGetMs=0;
  try{window.__wtDelayGetMs=Number(localStorage.getItem("__wtDelayGetMs")||0)||0;}catch(e){}
  var _f=window.fetch;
  window.fetch=function(u,o){
    var s=String((u&&u.url!==undefined)?u.url:u);
    var m=String((o&&o.method)||"GET").toUpperCase();
    if(s.indexOf("/userdata")>=0 && m==="GET" && window.__wtDelayGetMs>0){
      var d=window.__wtDelayGetMs; window.__wtDelayGetMs=0; var args=arguments;
      return new Promise(function(res,rej){
        setTimeout(function(){try{res(_f.apply(window,args));}catch(e){rej(e);}},d);
      });
    }
    return _f.apply(this,arguments);
  };
})();
</script>"""

HOOK_CODE = "window.__wt={UD:UD,WATER:WATER,D:D,POWER:POWER};"


def build_preview_ext():
    W.build_preview()  # 用 water_check 的 INJECT mock，从 W.SRC 生成 W.PREVIEW
    html = open(W.PREVIEW, encoding="utf-8", newline="").read()
    if "</head>" not in html:
        raise RuntimeError("预览页缺少 </head>")
    html = html.replace("</head>", DELAY_WRAP + "</head>", 1)
    # index.html 主脚本整体包在 IIFE 内（末尾 `})();` + `</script>`）→ 钩子必须插在
    # 最外层 IIFE 结束前（与 sync_check.py 同一锚点手法），否则 UD/D/WATER 不在全局作用域。
    import re
    m = list(re.finditer(r"\}\)\(\);\r?\n</script>", html))
    if not m:
        raise RuntimeError("预览页找不到主脚本结尾锚点 })();</script>")
    idx = m[-1].start()
    html = html[:idx] + HOOK_CODE + "\r\n" + html[idx:]
    with open(W.PREVIEW, "w", encoding="utf-8", newline="") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# 数据 / blob 工具
# ---------------------------------------------------------------------------
def seed_blob(power_sel="", rooms=None, atw=ATW_SEED, with_water=True):
    """构造云端 userdata v6 blob（power 带 low 以免制造假脏 section）。"""
    b = W.ud_blob(power_sel=power_sel, water_rooms=rooms or {}, with_water=with_water)
    b["power"] = {"sel": str(power_sel or ""), "at": ATW_SEED if power_sel else 0, "low": 30}
    if with_water:
        b["at"]["water"] = int(atw)
        b["water"] = {"rooms": rooms or {}}
    return b


def wroom(blob, rv):
    try:
        return ((blob.get("water") or {}).get("rooms") or {}).get(rv) or {}
    except Exception:
        return {}


def posts(cdp):
    try:
        return ev(cdp, "(function(){var a=window.__udPosts||[];return a.map(function(p){"
                      "return {id:String(p.id||''),blob:String(p.blob||''),headers:p.headers||{}};});})()") or []
    except Exception:
        return []


def blob_of(p):
    try:
        b = json.loads(p.get("blob") or "null")
        return b if isinstance(b, dict) else None
    except Exception:
        return None


def find_post(cdp, pred, timeout=15, interval=0.12):
    t0 = time.time()
    while time.time() - t0 < timeout:
        ps = posts(cdp)
        for i in range(len(ps) - 1, -1, -1):
            b = blob_of(ps[i])
            if b is not None and pred(b):
                return b
        time.sleep(interval)
    return None


def last_blob(cdp):
    for p in reversed(posts(cdp)):
        b = blob_of(p)
        if b is not None:
            return b
    return None


def recs_of(blob, rv):
    return (wroom(blob, rv).get("recs") or [])


def key_order(blob):
    return ",".join(list(blob.keys())) if blob else ""


CONTRACT_KEYS = "v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,water,homeToolsAt"


# ---------------------------------------------------------------------------
# 页面内状态工具
# ---------------------------------------------------------------------------
JS_SCOPE = ("(function(){var h=window.__wt||{};var UD=h.UD||window.UD;var WATER=h.WATER||window.WATER;"
            "var D=h.D||window.D;var POWER=h.POWER||window.POWER;%s})()")


def state_js(cdp, body):
    try:
        return ev(cdp, JS_SCOPE % body)
    except Exception:
        return None


def water_rooms(cdp):
    v = state_js(cdp, "return JSON.parse(JSON.stringify((D&&D.d&&D.d.water&&D.d.water.rooms)||{}));")
    return v if isinstance(v, dict) else {}


def sections_water(cdp):
    v = state_js(cdp, "return JSON.parse(JSON.stringify(UD.sections().water||null));")
    return v


def cache_read(cdp, sid):
    return ev(cdp, "(function(){try{return JSON.parse(localStorage.getItem(%s)||'null');}catch(e){return null;}})()"
              % jsq("zq_udcache_" + sid))


def clean_state(cdp):
    expr = JS_SCOPE % ("return !UD._push&&!UD._pull&&UD.dirtySections().length===0&&"
                       "!UD.pendRead()&&!!UD.cacheRead();")
    return W.wait_until(cdp, expr, 12, 0.12)


def ensure_base(cdp, sid):
    return W.wait_ud_baseline(cdp, sid)


def force_ud_pull(cdp):
    """主动触发一次 userdata GET（2026-11-11 起 power 恢复后启动不再产生「空值脏推送」，
    两账号隔离用例需要显式强拉一次才能观察到「只按当前 sid 拉取」）。"""
    state_js(cdp, "return (function(){try{UD.pull(true);return true;}catch(e){return false;}})();")
    time.sleep(1.0)


def hard_clear(cdp):
    """清空本 origin 全部 localStorage（等价换新设备），不依赖 INJECT reset（便于先写延迟标记）。"""
    try:
        cdp.send("Storage.clearDataForOrigin", {"origin": W.BASE.rstrip("/"), "storageTypes": "all"})
        return True
    except Exception:
        try:
            ev(cdp, "(function(){try{localStorage.clear();sessionStorage.clear();}catch(e){}return true;})()")
        except Exception:
            pass
        return False


def add_new_doc_script(cdp, source):
    return cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": source})["identifier"]


def remove_new_doc_script(cdp, ident):
    try:
        cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": ident})
    except Exception:
        pass


def badge(cdp):
    try:
        return ev(cdp, "(function(){var e=document.getElementById('wtSync');if(!e)return null;"
                      "return {hidden:!!e.hidden,text:String(e.textContent||'').trim(),"
                      "ds:String(e.getAttribute('data-sync')||'')};})()")
    except Exception:
        return None


# ===========================================================================
# A. 本机保存 / 删除 / 人数切换 → 最后一次 POST blob 内容
# ===========================================================================
def sc_a_local(cdp):
    ok = W.nav(cdp, W.purl(), clear=True)
    T("A01 干净设备启动（清本机存储 / 无云端 userdata）", ok)
    T("A02 boot pull 建立 UD 基线（zq_udcache_<sid>）", ensure_base(cdp, SID_A))
    T("A03 进入水量页", W.open_water_page(cdp))
    T("A04 未选宿舍：#wtCmp 引导「先选择关注宿舍」", "先选择关注宿舍" in W.norm(W.jtext(cdp, "#wtCmp")),
      W.norm(W.jtext(cdp, "#wtCmp"))[:80])

    sel = W.select_water_room(cdp, RV321)
    en = W.wait_until(cdp, "(function(){var e=document.getElementById('wtSave');return !!e&&!e.disabled;})()", 10)
    T("A05 选择关注宿舍 321 → #wtSave 可用", sel and en, "sel=%s en=%s" % (sel, en))

    # 第 1 条（M4）
    W.save_record(cdp, W.M4, "100.00")
    b1 = find_post(cdp, lambda b: len(recs_of(b, RV321)) >= 1, 15)
    T("A06 保存第 1 条 → >1.2s 防抖后 userdata POST 含 water.rooms[321]", b1 is not None,
      "posts=%d" % len(posts(cdp)))
    rw1 = wroom(b1 or {}, RV321)
    T("A07 blob.water.rooms[321]={p:4, recs:[M4 100.00]}",
      b1 is not None and rw1.get("p") == 4 and [x.get("m") for x in recs_of(b1, RV321)] == [W.M4]
      and abs(float(recs_of(b1, RV321)[0].get("r", -1)) - 100.0) < 1e-9,
      json.dumps(rw1, ensure_ascii=False)[:200])
    at1 = ((b1 or {}).get("at") or {}).get("water")
    T("A08 blob.at.water 为数字且 >0", isinstance(at1, (int, float)) and at1 > 0, str(at1))
    T("A09 blob 顶层 14 键键序正确", key_order(b1) == CONTRACT_KEYS, key_order(b1))
    T("A10 water 值内不镜像 at（只有 rooms）",
      isinstance((b1 or {}).get("water"), dict) and list((b1.get("water") or {}).keys()) == ["rooms"]
      and (b1.get("water") or {}).get("at") is None, key_order((b1 or {}).get("water")))

    # 第 2 条（M3）
    W.save_record(cdp, W.M3, "113.74")
    b2 = find_post(cdp, lambda b: len(recs_of(b, RV321)) >= 2, 15)
    T("A11 保存第 2 月 → POST recs 升序 [M4,M3] 读数正确",
      b2 is not None and [x.get("m") for x in recs_of(b2, RV321)] == [W.M4, W.M3]
      and abs(float(recs_of(b2, RV321)[1].get("r", -1)) - 113.74) < 1e-9,
      json.dumps(recs_of(b2 or {}, RV321), ensure_ascii=False)[:220])
    at2 = ((b2 or {}).get("at") or {}).get("water")
    T("A12 at.water 递增（第 2 次 > 第 1 次）", isinstance(at2, (int, float)) and isinstance(at1, (int, float)) and at2 > at1,
      "%s -> %s" % (at1, at2))

    # 删除 M4
    ev(cdp, "window.confirm=function(){return true;};true")
    W.click(cdp, '[data-wdel="%s"]' % W.M4)
    b3 = find_post(cdp, lambda b: len(recs_of(b, RV321)) == 1 and recs_of(b, RV321)[0].get("m") == W.M3, 15)
    T("A13 删除 1 条 → POST recs 仅 [M3]（删除动作同步）",
      b3 is not None and [x.get("m") for x in recs_of(b3, RV321)] == [W.M3],
      json.dumps(recs_of(b3 or {}, RV321), ensure_ascii=False)[:160])
    at3 = ((b3 or {}).get("at") or {}).get("water")
    T("A14 删除后 at.water 继续递增", isinstance(at3, (int, float)) and isinstance(at2, (int, float)) and at3 > at2,
      "%s -> %s" % (at2, at3))

    # 4 → 6 人间
    W.set_select(cdp, "#wtPersons", "6")
    b4 = find_post(cdp, lambda b: wroom(b, RV321).get("p") == 6, 15)
    T("A15 切换 6 人间 → POST water.rooms[321].p=6（人数同步）", b4 is not None,
      json.dumps(wroom(b4 or {}, RV321), ensure_ascii=False)[:160])
    at4 = ((b4 or {}).get("at") or {}).get("water")
    T("A16 人数切换后 at.water 继续递增", isinstance(at4, (int, float)) and isinstance(at3, (int, float)) and at4 > at3,
      "%s -> %s" % (at3, at4))

    # 等 >1.3s 后检查「最后一次」POST 终态
    time.sleep(1.5)
    last = last_blob(cdp)
    rwL = wroom(last or {}, RV321)
    T("A17 等 >1.3s 后最后一次 POST 终态：p=6 / recs=[M3 113.74] / 仅 1 间宿舍",
      last is not None and rwL.get("p") == 6 and [x.get("m") for x in (rwL.get("recs") or [])] == [W.M3]
      and list(((last.get("water") or {}).get("rooms") or {}).keys()) == [RV321],
      json.dumps(rwL, ensure_ascii=False)[:220])
    T("A18 最后一次 POST 仍为 14 键契约", key_order(last) == CONTRACT_KEYS, key_order(last))
    pw = (last or {}).get("power") or {}
    T("A19 power section 共用关注宿舍（sel=321 / at>0）",
      pw.get("sel") == RV321 and isinstance(pw.get("at"), (int, float)) and pw.get("at") > 0,
      json.dumps(pw, ensure_ascii=False)[:160])

    bd = badge(cdp)
    T("A20 同步状态：#wtSync 可见且推送完成后「已同步」（data-sync=1）",
      bool(bd) and not bd.get("hidden") and bd.get("ds") == "1" and "已同步" in str(bd.get("text")),
      json.dumps(bd, ensure_ascii=False)[:200])
    collect(cdp, "A 本机保存/删除/人数")
    return last


# ===========================================================================
# B. 新设备恢复（清 localStorage + 云端 seed；两间宿舍不同数据）
# ===========================================================================
def sc_b_restore(cdp):
    rooms = {
        RV321: {"p": 4, "recs": [W.rec("2025-01", 50.00), W.rec("2025-02", 60.50)]},
        RV330: {"p": 6, "recs": [W.rec("2025-03", 10.00), W.rec("2025-04", 30.00)]},
    }
    seed = seed_blob(power_sel=RV321, rooms=rooms, atw=ATW_SEED)
    T("B01 新设备（清本机 + 云端 v6 ud 种子）启动", W.nav(cdp, W.purl(ud=seed), clear=True))
    T("B02 boot pull 建立基线", ensure_base(cdp, SID_A))
    T("B03 进入水量页", W.open_water_page(cdp))
    rows_ok = W.wait_until(cdp, "(function(){return document.querySelectorAll('#wtList [data-wm]').length>=2;})()", 15)
    T("B04 自动恢复 2 条抄表记录", rows_ok and len(W.rows_of(cdp)) >= 2, len(W.rows_of(cdp)))
    T("B05 恢复关注宿舍 321 / 4 人间", W.jval(cdp, "#wtSel") == RV321 and W.jval(cdp, "#wtPersons") == "4",
      W.jval(cdp, "#wtSel") + "/" + W.jval(cdp, "#wtPersons"))
    row2 = W.row_text(cdp, "2025-02")
    T("B06 恢复历史内容（2025-02 / 60.50 / 用量 10.50 / 水费 7.57）",
      W.has_all(row2, "2025-02", "60.50", "10.50", "7.57"), W.norm(row2)[:140])
    got = water_rooms(cdp)
    ok2 = (RV321 in got and RV330 in got and got[RV321].get("p") == 4 and got[RV330].get("p") == 6
           and len(got[RV321].get("recs") or []) == 2 and len(got[RV330].get("recs") or []) == 2)
    T("B07 未选中房间也恢复（321 p=4 两条 + 330 p=6 两条）", ok2,
      json.dumps(got, ensure_ascii=False)[:260])
    cache = cache_read(cdp, SID_A) or {}
    T("B08 UD 基线 at.water = 云端种子时间戳", ((cache.get("at") or {}).get("water")) == ATW_SEED,
      str((cache.get("at") or {}).get("water")))
    # 切到 330：人数/记录跟随该宿舍
    W.set_select(cdp, "#wtSel", RV330)
    time.sleep(0.6)
    row4 = W.row_text(cdp, "2025-04")
    T("B09 切到 330 号宿舍 → 人数 6 / 记录恢复（2025-04 / 30.00 / 24.24）",
      W.jval(cdp, "#wtSel") == RV330 and W.jval(cdp, "#wtPersons") == "6" and W.has_all(row4, "2025-04", "30.00", "24.24"),
      "%s/%s | %s" % (W.jval(cdp, "#wtSel"), W.jval(cdp, "#wtPersons"), W.norm(row4)[:120]))
    bucket = W.bucket_read(cdp, SID_A) or {}
    got_local = ((bucket.get("water") or {}).get("rooms") or {})
    T("B10 本机桶持久化两间宿舍 water 数据", len(got_local) == 2,
      json.dumps(list(got_local.keys()), ensure_ascii=False)[:160])
    collect(cdp, "B 换设备恢复")


# ===========================================================================
# C. 保存后同一 tick pagehide → flush 立即推送
# ===========================================================================
def sc_c_pagehide(cdp):
    seed = seed_blob(power_sel=RV321, rooms={RV321: {"p": 4, "recs": [W.rec(W.M4, 100.00)]}}, atw=ATW_SEED)
    T("C00 pagehide 场景启动", W.nav(cdp, W.purl(ud=seed), clear=True))
    T("C01 基线就绪（boot pull 完成）", ensure_base(cdp, SID_A))
    T("C02 进入水量页", W.open_water_page(cdp))
    T("C03 无脏 section / 无 pending（flush 前干净）", clean_state(cdp))
    before = len(posts(cdp))
    W.set_input(cdp, "#wtMonth", W.M3)
    W.set_input(cdp, "#wtReading", "110.00")
    t0 = time.time()
    r = ev(cdp, "(function(){var b=document.getElementById('wtSave');if(!b)return 'no';"
                "b.click();window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:false}));"
                "return 'ok';})()")
    b = find_post(cdp, lambda x: any(y.get("m") == W.M3 and abs(float(y.get("r", -1)) - 110.0) < 1e-9
                                    for y in recs_of(x, RV321)), 8, 0.08)
    elapsed = time.time() - t0
    T("C04 pagehide 同一 tick 触发 flush：<1.1s 出现含新记录的 POST（不依赖 1200ms 防抖）",
      b is not None and elapsed < 1.1, "eval=%s elapsed=%.2fs posts=%d->%d" % (r, elapsed, before, len(posts(cdp))))
    recs = recs_of(b or {}, RV321)
    T("C05 flush blob 记录按月升序 [M4 100.00, M3 110.00]",
      [x.get("m") for x in recs] == [W.M4, W.M3]
      and abs(float(recs[1].get("r", -1)) - 110.0) < 1e-9, json.dumps(recs, ensure_ascii=False)[:220])
    T("C06 flush blob at.water > 云端种子（本机赢）",
      isinstance(((b or {}).get("at") or {}).get("water"), (int, float))
      and ((b.get("at") or {}).get("water")) > ATW_SEED,
      str(((b or {}).get("at") or {}).get("water")))
    collect(cdp, "C pagehide flush")


# ===========================================================================
# D. 无基线 + boot userdata GET 延迟竞态：立即保存不被云端旧值覆盖
# ===========================================================================
def sc_d_nobase_race(cdp):
    hard_clear(cdp)
    ident = add_new_doc_script(cdp, "try{localStorage.setItem('__wtDelayGetMs','3000');}catch(e){}")
    old = seed_blob(power_sel=RV330,
                    rooms={RV330: {"p": 6, "recs": [W.rec("2025-03", 10.00)]}}, atw=ATW_OLD)
    T("D01 无基线 + boot GET 延迟 ~3s 场景启动", W.nav(cdp, W.purl(ud=old)))
    remove_new_doc_script(cdp, ident)
    T("D02 进入水量页", W.open_water_page(cdp))
    sel = W.select_water_room(cdp, RV321)
    en = W.wait_until(cdp, "(function(){var e=document.getElementById('wtSave');return !!e&&!e.disabled;})()", 10)
    T("D03 延迟期间选择宿舍 321 且输入可用", sel and en, "sel=%s en=%s" % (sel, en))
    T("D04 保存时仍无 UD 基线（竞态成立）", cache_read(cdp, SID_A) is None,
      "cache=%r" % (cache_read(cdp, SID_A),))
    W.save_record(cdp, W.M2, "50.00")
    time.sleep(6.0)  # 等延迟 GET（~4.5s 内返回）+ pull merge + 补推
    final = last_blob(cdp)
    recs = recs_of(final or {}, RV321)
    T("D05 最终 POST 含本机新记录（云端旧值未覆盖）",
      any(x.get("m") == W.M2 and abs(float(x.get("r", -1)) - 50.0) < 1e-9 for x in recs),
      json.dumps(recs, ensure_ascii=False)[:220] + " | posts=%d" % len(posts(cdp)))
    rooms = water_rooms(cdp)
    T("D06 本机视图保留新记录（321 存在、旧云端 330 未回灌）",
      RV321 in rooms and len(rooms.get(RV321, {}).get("recs") or []) >= 1 and RV330 not in rooms,
      json.dumps(rooms, ensure_ascii=False)[:260])
    T("D07 最终 blob at.water > 云端旧时间戳（本机赢）",
      isinstance(((final or {}).get("at") or {}).get("water"), (int, float))
      and ((final.get("at") or {}).get("water")) > ATW_OLD,
      str(((final or {}).get("at") or {}).get("water")))
    T("D08 最终 blob 仍 14 键契约", key_order(final) == CONTRACT_KEYS, key_order(final))
    collect(cdp, "D 无基线竞态")


# ===========================================================================
# E. 旧数据无 water → 默认 {rooms:{}}，首次保存补齐 14 键
# ===========================================================================
def sc_e_olddata(cdp):
    old = seed_blob(power_sel=RV321, rooms={}, with_water=False)  # v6 13 section（无 water）
    T("E01 旧数据（无 water section）启动", W.nav(cdp, W.purl(ud=old), clear=True))
    T("E02 boot pull 建立基线", ensure_base(cdp, SID_A))
    T("E03 进入水量页空态可用", W.open_water_page(cdp) and W.jcount(cdp, "#wtList [data-wm]") == 0)
    T("E04 D.d.water 默认 {rooms:{}}",
      water_rooms(cdp) == {} and isinstance(water_rooms(cdp), dict), json.dumps(water_rooms(cdp), ensure_ascii=False))
    sw = sections_water(cdp)
    T("E05 UD.sections().water 默认 {rooms:{}}（14 键契约本机视图）",
      isinstance(sw, dict) and sw.get("rooms") == {}, json.dumps(sw, ensure_ascii=False))
    T("E06 基线干净后再保存", clean_state(cdp))
    W.save_record(cdp, W.M3, "88.88")
    b = find_post(cdp, lambda x: any(y.get("m") == W.M3 and abs(float(y.get("r", -1)) - 88.88) < 1e-9
                                    for y in recs_of(x, RV321)), 15)
    T("E07 旧数据首次保存 → POST 自动补齐 water section（14 键 / p=4 / 1 条）",
      b is not None and key_order(b) == CONTRACT_KEYS and wroom(b, RV321).get("p") == 4
      and len(recs_of(b, RV321)) == 1, key_order(b))
    T("E08 首次写入 at.water 为数字 >0", isinstance(((b or {}).get("at") or {}).get("water"), (int, float))
      and ((b.get("at") or {}).get("water")) > 0, str(((b or {}).get("at") or {}).get("water")))
    collect(cdp, "E 旧数据无 water")


# ===========================================================================
# F. 单间上限 120：云端 130 条 → 渲染 120；改人数后推送裁剪为 120
# ===========================================================================
def cap_recs():
    out = []
    y, m = 2010, 1
    for i in range(130):
        out.append(W.rec("%04d-%02d" % (y, m), round(10.0 + i * 0.5, 2), 1))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def sc_f_cap(cdp):
    recs = cap_recs()
    seed = seed_blob(power_sel=RV321, rooms={RV321: {"p": 4, "recs": recs}}, atw=ATW_SEED)
    T("F01 云端 130 条记录场景启动", W.nav(cdp, W.purl(ud=seed), clear=True))
    T("F02 基线就绪", ensure_base(cdp, SID_A))
    T("F03 进入水量页", W.open_water_page(cdp))
    W.wait_until(cdp, "(function(){return document.querySelectorAll('#wtList [data-wm]').length>0;})()", 15)
    time.sleep(0.3)
    n = W.jcount(cdp, "#wtList [data-wm]")
    T("F04 云端 130 条 → 页面只渲染 120 条（normRecs 上限）", n == 120, "rows=%d" % n)
    rows = W.rows_of(cdp)
    T("F05 裁剪保留最近 120 条（最早显示 2010-11，最新 2020-10）",
      len(rows) == 120 and rows[-1].get("m") == "2010-11" and rows[0].get("m") == "2020-10",
      "%s .. %s | %d" % (rows[0].get("m") if rows else "none", rows[-1].get("m") if rows else "none", len(rows)))
    raw = water_rooms(cdp).get(RV321, {}).get("recs") or []
    T("F06 远端 130 条经 applyRemote 归一后本机 raw 已裁到 120（修复后口径）", len(raw) == 120, "raw=%d" % len(raw))
    W.set_select(cdp, "#wtPersons", "6")
    b = find_post(cdp, lambda x: wroom(x, RV321).get("p") == 6 and len(recs_of(x, RV321)) == 120, 15)
    T("F07 改人数后推送上云被裁剪为 120 条（p=6 / ≤120）",
      b is not None and len(recs_of(b, RV321)) == 120, "posts=%d" % len(posts(cdp)))
    collect(cdp, "F 上限 120")


# ===========================================================================
# G. 两账号隔离
# ===========================================================================
def sc_g_isolation(cdp):
    seedA = seed_blob(power_sel=RV321, rooms={
        RV321: {"p": 4, "recs": [W.rec("2025-01", 50.00), W.rec("2025-02", 60.50)]}}, atw=ATW_SEED)
    T("G01 账号 A 启动（云端 A 数据）", W.nav(cdp, W.purl(ud=seedA), clear=True))
    T("G02 A 基线", ensure_base(cdp, SID_A))
    T("G03 A 水量页恢复", W.open_water_page(cdp)
      and W.wait_until(cdp, "(function(){return document.querySelectorAll('#wtList [data-wm]').length>=2;})()", 15))
    seedB = seed_blob(power_sel=RV330, rooms={
        RV330: {"p": 6, "recs": [W.rec("2025-03", 10.00), W.rec("2025-04", 30.00)]}}, atw=ATW_SEED + 1000)
    # 不清 localStorage：验证 A 的本机桶不被 B 覆盖
    T("G04 切账号 B（保留本机 A 桶）启动", W.nav(cdp, W.purl(sid=SID_B, ud=seedB)))
    T("G05 B 基线", ensure_base(cdp, SID_B))
    T("G06 B 水量页恢复", W.open_water_page(cdp)
      and W.wait_until(cdp, "(function(){return document.querySelectorAll('#wtList [data-wm]').length>=2;})()", 15))
    rowB = W.row_text(cdp, "2025-04")
    txtB = W.jtext(cdp, "#s-water")
    T("G07 B 恢复 B 的记录（2025-04 / 30.00 / 24.24）", W.has_all(rowB, "2025-04", "30.00", "24.24"),
      W.norm(rowB)[:140])
    T("G08 B 看不到 A 的记录（2025-01/2025-02）",
      "2025-01" not in W.norm(txtB) and "2025-02" not in W.norm(txtB))
    gets = W.urls_matching(cdp, "/userdata", "GET")
    if not gets:
        force_ud_pull(cdp)
        gets = W.urls_matching(cdp, "/userdata", "GET")
    T("G09 B 的 userdata GET 只按 sid B 过滤", len(gets) >= 1 and all(SID_B in str(r.get("url")) for r in gets),
      "gets=%d" % len(gets))
    bucketA = W.bucket_read(cdp, SID_A) or {}
    recsA = (((bucketA.get("water") or {}).get("rooms") or {}).get(RV321) or {}).get("recs") or []
    T("G10 两账号互不覆盖：本机 A 桶 water 记录保留", len(recsA) == 2,
      json.dumps(recsA, ensure_ascii=False)[:160])
    # 回 A：本机桶恢复
    T("G11 切回账号 A 启动", W.nav(cdp, W.purl(sid=SID_A)))
    T("G12 A 基线/本机桶恢复", ensure_base(cdp, SID_A))
    T("G13 A 水量页", W.open_water_page(cdp)
      and W.wait_until(cdp, "(function(){return document.querySelectorAll('#wtList [data-wm]').length>=2;})()", 15))
    rowA = W.row_text(cdp, "2025-02")
    T("G14 切回 A：本机桶恢复 A 记录（2025-02 / 60.50）", W.has_all(rowA, "2025-02", "60.50"),
      W.norm(rowA)[:140])
    txtA = W.jtext(cdp, "#s-water")
    T("G15 A 看不到 B 的记录（2025-03/2025-04）",
      "2025-03" not in W.norm(txtA) and "2025-04" not in W.norm(txtA))
    force_ud_pull(cdp)
    getsA = W.urls_matching(cdp, "/userdata", "GET")
    T("G16 A 的 userdata GET 只按 sid A 过滤", len(getsA) >= 1 and all(SID_A in str(r.get("url")) for r in getsA),
      "gets=%d" % len(getsA))
    collect(cdp, "G 两账号隔离")


# ===========================================================================
# H. 远端脏值归一（WATER.normWater）：p/recs/房间类型全部归一，回云不回写脏数据
# ===========================================================================
def sc_h_norm(cdp):
    recs = cap_recs()  # 130 条合法月频 2010-01..2020-10
    bad = recs + [
        {"m": "2020-13", "r": 999.0, "ts": 1},   # 非法月份（13 月）
        {"m": "2021-01", "r": -5.0, "ts": 1},    # 非法读数（负数）
        "not-an-object",                          # 非对象条目（应被丢弃）
    ]
    rooms = {
        RV321: {"p": 9, "recs": bad},   # p 只允许 4/6 → 应为 4；recs 归一/裁剪到 120
        "1-13---324": "oops",           # 字符串房间值 → 丢弃
        "1-16---306": None,             # null 房间值 → 丢弃
        "4-23B---422": [],              # 数组房间值 → 丢弃
    }
    seed = seed_blob(power_sel=RV321, rooms=rooms, atw=ATW_SEED)
    T("H00 远端脏值归一场景启动", W.nav(cdp, W.purl(ud=seed), clear=True))
    T("H01 boot pull 建立基线", ensure_base(cdp, SID_A))
    T("H02 进入水量页", W.open_water_page(cdp))
    wait_js = ("(function(){var h=window.__wt||{};var D=h.D;var r=D&&D.d&&D.d.water&&D.d.water.rooms;"
               "return !!(r&&r[%s]&&Number(r[%s].p)===4&&(r[%s].recs||[]).length===120);})()"
               % (jsq(RV321), jsq(RV321), jsq(RV321)))
    applied = W.wait_until(cdp, wait_js, 15, 0.15)
    T("H03 远端 p=9 归一为 4；130+2 条脏 recs 归一/裁剪为 120 条（本机 D.d.water）", applied)
    T("H04 页面人数下拉显示 4 人间（非 9）", W.jval(cdp, "#wtPersons") == "4", W.jval(cdp, "#wtPersons"))
    rows_ok = W.wait_until(cdp, "(function(){return document.querySelectorAll('#wtList [data-wm]').length===120;})()", 15)
    rows = W.rows_of(cdp)
    T("H05 页面渲染 120 行（非法月份/读数不渲染）", rows_ok and len(rows) == 120, "rows=%d" % len(rows))
    T("H06 归一后保留最近 120 条：首 2010-11 / 末 2020-10",
      len(rows) == 120 and rows[-1].get("m") == "2010-11" and rows[0].get("m") == "2020-10",
      "%s .. %s" % (rows[0].get("m") if rows else "none", rows[-1].get("m") if rows else "none"))
    all_txt = W.norm(W.jtext(cdp, "#s-water"))
    T("H07 非法月份 2020-13 / 2021-01 不出现", "2020-13" not in all_txt and "2021-01" not in all_txt)
    bucket = W.bucket_read(cdp, SID_A) or {}
    rooms_b = ((bucket.get("water") or {}).get("rooms") or {})
    r321 = rooms_b.get(RV321) or {}
    try:
        pb = int(float(r321.get("p")))
    except Exception:
        pb = -1
    recs_b = r321.get("recs") or []
    ok_b = (pb == 4 and len(recs_b) == 120
            and bool(recs_b) and recs_b[0].get("m") == "2010-11")
    T("H08 本机桶归一：321={p:4, recs:120}、首条 2010-11", ok_b,
      json.dumps({"p": r321.get("p"), "n": len(recs_b),
                  "first": (recs_b or [{}])[0].get("m")}, ensure_ascii=False))
    T("H09 非对象房间（字符串/null/数组）被丢弃（本机桶只剩 321）",
      set(rooms_b.keys()) == {RV321}, json.dumps(list(rooms_b.keys()), ensure_ascii=False)[:200])
    # 主动走一次「回云」路径（点重试同款 requestSync），确保捕获一次归一后的 POST
    trig = ev(cdp, "(function(){var h=window.__wt||{};var WATER=h.WATER;"
                  "if(!WATER||!WATER.requestSync)return 'no';WATER.requestSync();return 'ok';})()")
    post = find_post(cdp, lambda b: (wroom(b, RV321).get("p") == 4 and len(recs_of(b, RV321)) == 120), 20)
    recs_p = recs_of(post or {}, RV321)
    T("H10 归一后回云 POST 也是归一值（p=4 / 120 条 / 首条 2010-11）",
      post is not None and recs_p and recs_p[0].get("m") == "2010-11"
      and wroom(post, RV321).get("p") == 4 and len(recs_p) == 120,
      "trigger=%s posts=%d" % (trig, len(posts(cdp))))
    T("H11 回云 blob 不含非法房间键（不回写 null/字符串/数组房间）",
      post is not None and set(((post.get("water") or {}).get("rooms") or {}).keys()) == {RV321},
      key_order(((post or {}).get("water") or {}).get("rooms")))
    T("H12 回云 blob at.water > 云端脏种子（本机归一后赢）",
      isinstance(((post or {}).get("at") or {}).get("water"), (int, float))
      and ((post.get("at") or {}).get("water")) > ATW_SEED,
      str(((post or {}).get("at") or {}).get("water")))
    collect(cdp, "H 远端脏值归一")


# ===========================================================================
# 主流程
# ===========================================================================
def write_result(passed, total, fails, extra=None):
    try:
        os.makedirs(WORK, exist_ok=True)
        obj = {
            "task": "task-2 v2_water_sync_check（水量云同步独立浏览器回归）",
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "ok": bool(total > 0 and not fails),
            "pass": passed,
            "total": total,
            "failed": [r["k"] for r in fails],
            "indexHtml": META["before"],
            "indexHtmlAfterRun": META["after"],
            "runStartedAt": META["startedAt"],
            "durationSec": META["durationSec"],
            "baseUrl": META["base"],
            "runTmp": META["runTmp"],
            "specCheck": os.path.abspath(os.environ.get("SPEC_CHECK") or os.path.join(W.ROOT, "index.html")),
            "assertions": RESULTS,
            "globalErrors": GLOBAL,
            "notes": extra or "",
        }
        with open(RESULT_JSON, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        print("结果 JSON:", RESULT_JSON)
    except Exception as e:
        print("[warn] 写结果 JSON 失败:", str(e)[:200])


def report():
    fails = [r for r in RESULTS if not r["ok"]]
    print("")
    print("=" * 66)
    if fails:
        print("失败明细 (%d):" % len(fails))
        for r in fails:
            print("  - %s%s" % (r["k"], ("  -- " + r["note"]) if r["note"] else ""))
    total = len(RESULTS)
    passed = total - len(fails)
    print("index.html: %s B / %s" % ((META["before"] or {}).get("size"), (META["before"] or {}).get("sha256")))
    print("v2_water_sync_check: %d/%d PASS" % (passed, total))
    write_result(passed, total, fails)
    return 0 if (total > 0 and not fails) else 1


def main(argv):
    started = datetime.now().astimezone()
    t_all = time.time()
    os.makedirs(WORK, exist_ok=True)
    if "--list" in argv:
        print("v2_water_sync_check 断言计划（浏览器实跑）：")
        print("  A 本机保存/删除/人数切换 → 最后一次 POST blob（约 23 项）")
        print("  B 新设备恢复（两间宿舍不同数据）（约 13 项）")
        print("  C pagehide 同 tick flush（约 10 项）")
        print("  D 无基线 + boot GET 延迟竞态（约 14 项）")
        print("  E 旧数据无 water → 默认 {rooms:{}} + 首次补齐（约 14 项）")
        print("  F 单间上限 120（约 10 项）")
        print("  G 两账号隔离（约 20 项）")
        print("  H 远端脏值归一（p/非法月份/非对象房间/120 上限/回云归一）（约 17 项）")
        return 0

    if not os.path.exists(W.SRC):
        T("源文件存在", False, W.SRC)
        return report()
    META["before"] = file_meta(W.SRC)
    META["startedAt"] = started.isoformat(timespec="seconds")
    print("[v2_water_sync_check] 被测文件：%s B / %s" % (META["before"].get("size"), META["before"].get("sha256")))

    # --- 初始化 water_check 骨架全局（必须先生成 RUN_TMP/PREVIEW/BASE 再调 W.purl）---
    os.makedirs(W.TMP, exist_ok=True)
    W.RUN_TMP = os.path.join(W.TMP, "run_v2wsync_%d_%d" % (os.getpid(), int(time.time())))
    W.PREVIEW = os.path.join(W.RUN_TMP, "_water_preview.html")
    W.HTTP_PORT = W.free_port()
    W.CDP_PORT = W.free_port()
    W.BASE = "http://127.0.0.1:%d/" % W.HTTP_PORT
    META["base"] = W.BASE
    META["runTmp"] = W.RUN_TMP
    os.makedirs(W.RUN_TMP, exist_ok=True)
    build_preview_ext()

    httpd = None
    proc = None
    cdp = None
    devnull = None
    prof = None
    try:
        class _QuietServer(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass  # Edge CDP 退出时的 ConnectionReset 属正常噪声

        httpd = _QuietServer(("127.0.0.1", W.HTTP_PORT),
                             functools.partial(W.QuietHandler, directory=W.ROOT))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.35)
        prof = os.path.join(W.RUN_TMP, "edgeprof")
        os.makedirs(prof, exist_ok=True)
        devnull = open(os.devnull, "wb")
        proc = subprocess.Popen(
            [W.EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--force-device-scale-factor=1", "--hide-scrollbars",
             "--remote-debugging-port=%d" % W.CDP_PORT, "--user-data-dir=" + prof, "about:blank"],
            stdout=devnull, stderr=devnull)
        cdp = W.CDP(W.get_ws(W.CDP_PORT))
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        try:
            cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        except Exception:
            pass
        W.set_viewport(cdp, 430, 900)
        sc_a_local(cdp)
        sc_b_restore(cdp)
        sc_c_pagehide(cdp)
        sc_d_nobase_race(cdp)
        sc_e_olddata(cdp)
        sc_f_cap(cdp)
        sc_g_isolation(cdp)
        sc_h_norm(cdp)
    except Exception:
        T("脚本执行异常", False, traceback.format_exc()[-700:])
    finally:
        try:
            if cdp:
                cdp.close()
        except Exception:
            pass
        try:
            if proc:
                proc.kill()
        except Exception:
            pass
        try:
            if httpd:
                httpd.shutdown()
                httpd.server_close()
        except Exception:
            pass
        try:
            if devnull:
                devnull.close()
        except Exception:
            pass
        try:
            if W.RUN_TMP:
                shutil.rmtree(W.RUN_TMP, ignore_errors=True)
        except Exception:
            pass
        try:
            META["after"] = file_meta(W.SRC)
        except Exception:
            pass
        META["durationSec"] = round(time.time() - t_all, 1)
        print("运行耗时: %.1fs（被测文件运行后：%s B / %s）"
              % (META["durationSec"], (META["after"] or {}).get("size"), (META["after"] or {}).get("sha256")))

    # Z 汇总
    T("Z01 全程 0 JS 报错", len(GLOBAL["errs"]) == 0, " | ".join(GLOBAL["errs"][:4]))
    T("Z02 全程 0 console.error", len(GLOBAL["cerrs"]) == 0, " | ".join(GLOBAL["cerrs"][:4]))
    T("Z03 全程无外部请求", len(GLOBAL["exts"]) == 0, " | ".join(GLOBAL["exts"][:4]))
    return report()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
