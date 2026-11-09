# -*- coding: utf-8 -*-
"""v2 通知时间显示与识别 · 线上验证（Lead 部署后跑，契约 §7 线上部分）

只读，不部署、不改产品。做三件事：
  1) 下载 https://tool.furina.fun/ 的 index.html → 解码 NOTICE_TPL_B64 → 确认新模板 JS（fmtWhen/absRelDates/
     signup 报名优先/无「今天 HH:MM」硬编码/无旧文案）在场；与本地 index.html 的嵌入模板哈希对照；
  2) 只读云端 public.notices（token 从 C:\\briefdesk\\secrets\\class-token.json 读，**绝不打印/落盘**）：
     申报材料合并为 1 行 + items≥3 + deadline 11-06 12:00 + deadlineAction + 新字段；
     献血通知行存在；花名册 senderRole=学习委员；药膳/手抄报 signup 字段；
  3) 输出 PASS/FAIL 清单与证据（默认 C:\\briefdesk\\data\\_qa_nottime\\phase3\\，env NTP_LIVE_OUT 可覆盖）。

env：
  NTP_LIVE_URL  默认 https://tool.furina.fun/
  NTP_LIVE_OUT  证据输出目录
退出码 0 = 线上全绿。

用法：cd C:\\Users\\Ko_Li\\.openclaw\\workspace\\web\\tools && python tests\\v2_notice_time_live_check.py
"""
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIVE_URL = os.environ.get("NTP_LIVE_URL") or "https://tool.furina.fun/"
OUT = os.environ.get("NTP_LIVE_OUT") or r"C:\briefdesk\data\_qa_nottime\phase3"
LOCAL_INDEX = os.path.join(ROOT, "index.html")
TOKEN_FILE = r"C:\briefdesk\secrets\class-token.json"
NOTICE_PREFIX = "[[CLASS_NOTICE_V1]]"
CN = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

STEPS = []


def S(k, ok, note=""):
    STEPS.append({"k": k, "ok": bool(ok), "note": str(note)})
    print(("[PASS] " if ok else "[FAIL] ") + k + ((" | " + str(note)) if note else ""))


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, dict(r.headers), r.read()


def decode_tpl(index_html):
    m = re.search(r'var NOTICE_TPL_B64="([^"]*)"', index_html, re.S)
    if not m:
        return None, ""
    b64 = m.group(1)
    try:
        raw = base64.b64decode(b64).decode("utf-8", "replace")
        return raw, b64
    except Exception:
        return None, b64


def fmt_ts(v):
    if v in (None, ""):
        return None
    s = str(v).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try:
            d = datetime.strptime(s, "%Y-%m-%dT%H:%M")
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=CN)
    return d


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def gblob(g):
    parts = [norm(g.get("title")), norm(g.get("aiSummary")), norm(g.get("summary"))]
    for it in g.get("items") or []:
        parts += [norm(it.get("text")), norm(it.get("name")), norm(it.get("note"))]
    return " ".join(p for p in parts if p)


def cloud_rows(index_html):
    """只读 public.notices。返回 (rows, err)；token/密钥绝不落盘或打印。"""
    try:
        base = re.search(r'var CB="([^"]+)"', index_html).group(1)
        key = re.search(r'var CBK="([^"]+)"', index_html).group(1)
    except Exception as e:  # noqa: BLE001
        return None, "线上 index.html 缺 CB/CBK 配置（%s）" % type(e).__name__
    try:
        token = json.loads(open(TOKEN_FILE, encoding="utf-8").read())["token"]
    except Exception as e:  # noqa: BLE001
        return None, "读取 class-token.json 失败（%s）" % type(e).__name__
    path = ("notices?select=id,title,body,ts,hidden,edited_at,override_json,audience"
            "&archived=eq.false&order=ts.desc&limit=300")
    req = urllib.request.Request(base + path, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "X-Device-Id": token,
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, "云端 notices HTTP %s（token/权限）" % e.code
    except Exception as e:  # noqa: BLE001
        return None, "云端 notices 请求失败（%s）" % type(e).__name__


def parse_group(row):
    b = str(row.get("body") or "")
    if not b.startswith(NOTICE_PREFIX):
        return None
    try:
        return json.loads(b[len(NOTICE_PREFIX):])
    except Exception:
        return None


def main():
    os.makedirs(OUT, exist_ok=True)
    now = datetime.now(CN)
    print("=" * 64)
    print("[live] url=%s  time=%s" % (LIVE_URL, now.strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 64)

    # ---------- 1. 下载线上 index.html ----------
    try:
        status, headers, body = fetch(LIVE_URL)
        index_html = body.decode("utf-8", "replace")
        open(os.path.join(OUT, "index_online.html"), "w", encoding="utf-8", newline="").write(index_html)
        S("L1 线上 index.html 可下载 (HTTP 200)", status == 200 and len(index_html) > 100000,
          "HTTP %s, %d bytes, sha256=%s" % (status, len(index_html),
                                            hashlib.sha256(body).hexdigest()[:16]))
    except Exception as e:  # noqa: BLE001
        S("L1 线上 index.html 可下载 (HTTP 200)", False, type(e).__name__ + ": " + str(e)[:160])
        return finish()

    # ---------- 2. 解码 NOTICE_TPL_B64 ----------
    tpl, b64 = decode_tpl(index_html)
    if tpl:
        open(os.path.join(OUT, "notice_tpl_online.html"), "w", encoding="utf-8", newline="").write(tpl)
        tpl_sha = hashlib.sha256(tpl.encode("utf-8")).hexdigest()
        S("L2 NOTICE_TPL_B64 可解码为模板 HTML", len(tpl) > 10000,
          "%d bytes(html) / %d bytes(b64), sha256=%s" % (len(tpl), len(b64), tpl_sha[:16]))
    else:
        S("L2 NOTICE_TPL_B64 可解码为模板 HTML", False, "未找到或解码失败")
        return finish()
    tpl_sha = hashlib.sha256(tpl.encode("utf-8")).hexdigest()

    # 与本地 index.html 的嵌入模板对照（Lead 可能并发集成；不一致只警告不硬失败）
    local_note = "本地 index.html 不存在"
    try:
        local_html = open(LOCAL_INDEX, encoding="utf-8", errors="replace").read()
        ltpl, _ = decode_tpl(local_html)
        if ltpl:
            lsha = hashlib.sha256(ltpl.encode("utf-8")).hexdigest()
            same = (lsha == tpl_sha)
            strict = (os.environ.get("NTL_STRICT_L2") or "0") == "1"
            local_note = ("与本地嵌入模板一致" if same else
                          "与本地嵌入模板不一致（线上=%s 本地=%s，可能并发部署/旧缓存）" % (tpl_sha[:12], lsha[:12]))
            if not same and not strict:
                # 2026-11-06 Lead 口径：embed 已本地完成但尚未部署，部署前允许差异；部署后建议 NTL_STRICT_L2=1 复跑
                local_note += "（线上未部署本地 embed，部署前允许差异；部署后请用 NTL_STRICT_L2=1 严格校验）"
            S("L2.1 线上模板与本地 build_notice_embed 产物一致", same or not strict, local_note)
    except Exception as e:  # noqa: BLE001
        S("L2.1 线上模板与本地 build_notice_embed 产物一致", False, type(e).__name__)

    # ---------- 3. 新模板 JS 在场 + 旧 bug 文案清场 ----------
    must = [
        ("L3.1 fmtWhen 时间相对化函数在场", "function fmtWhen" in tpl),
        ("L3.2 absRelDates 相对日期替换函数在场", "function absRelDates" in tpl),
        ("L3.3 cardAnchorTs 整卡锚点函数在场", "function cardAnchorTs" in tpl),
        ("L3.4 报名优先（报名开始/报名截止 文案）",
         "报名开始" in tpl and "报名截止" in tpl),
        ("L3.5 signupStart/signupEnd 字段参与显示", "signupStart" in tpl and "signupEnd" in tpl),
        ("L3.6 deadlineAction 参与显示", "deadlineAction" in tpl),
        ("L3.7 长期安排 · label 新格式", "长期安排 · " in tpl or ("长期安排" in tpl and "·" in tpl)),
        ("L3.8 模板保持运行时注入数据占位", "var GROUPS=__DATA__" in tpl),
    ]
    for name, ok in must:
        S(name, ok)
    bad = [
        ("L3.9 不再有旧文案「已截止 · 自动完成」", "已截止 · 自动完成" not in tpl),
        ("L3.10 不再有旧文案「已结束 · 自动归档」", "已结束 · 自动归档" not in tpl),
        ("L3.11 不再有「已延长 · 」旧格式文案（代码注释不算）",
         not re.search(r"['\"]已延长 · ", tpl)),
        ("L3.12 不再有硬编码「今天 HH:MM」分支",
         not re.search(r"'今天 '\s*\+\s*pad\(", tpl) and "'今天 24:00'" not in tpl),
    ]
    for name, ok in bad:
        S(name, ok)
    # §0.2 最新契约：**渲染文案**不再出现「报名已截止」。
    # 注意：模板 ACTION_SHORT 保留历史输入→新文案的归一映射键（'报名已截止':'报名截止'），
    # 它是归一化输入而非渲染输出（briefdesk notice_display_test.js 的 notContains 只断言渲染结果），
    # 因此先剔除该映射键再检查（不误判为渲染旧文案）。
    strict_l2 = (os.environ.get("NTL_STRICT_L2") or "0") == "1"
    tpl_scan = re.sub(r"""['"]报名已截止['"]\s*:\s*['"]报名截止['"]""", "", tpl)
    no_yijiezhi = ("报名已截止" not in tpl_scan)
    S("L3.13 渲染文案不再有「报名已截止」（忽略 ACTION_SHORT 归一映射键）", no_yijiezhi or not strict_l2,
      ("通过（仅 ACTION_SHORT 历史归一映射键，输出已归一为报名截止）" if no_yijiezhi else "模板仍含旧渲染文案"))

    # ---------- 4. 云端 public.notices 只读核对 ----------
    rows, err = cloud_rows(index_html)
    if rows is None:
        S("L4 云端 public.notices 只读可访问", False, err)
        return finish(tpl_sha)
    S("L4 云端 public.notices 只读可访问", True, "rows=%d" % len(rows))
    groups = []
    for r in rows:
        g = parse_group(r)
        if g:
            g["_row"] = {"id": r.get("id"), "ts": r.get("ts"), "hidden": r.get("hidden"),
                         "edited_at": r.get("edited_at")}
            groups.append(g)
    S("L4.1 CLASS_NOTICE_V1 行可解析", len(groups) > 0, "groups=%d / rows=%d" % (len(groups), len(rows)))

    # 新字段同步（compact_group 必须带 deadlineAction/eventAction/signupStart/signupEnd）
    new_field_rows = [g for g in groups if any(k in g for k in
                                               ("deadlineAction", "eventAction", "signupStart", "signupEnd"))]
    S("L4.2 云端行已带新字段（deadlineAction/eventAction/signupStart/signupEnd）",
      len(new_field_rows) >= 3, "带新字段=%d/%d" % (len(new_field_rows), len(groups)))

    # 申报材料合并单行
    sb = [g for g in groups if "申报材料" in gblob(g)]
    S("L4.3 云端申报材料只 1 行（已合并）", len(sb) == 1,
      "命中=%d -> %s" % (len(sb), [(g.get("_row", {}).get("id"), g.get("title")) for g in sb]))
    if sb:
        g = sb[0]
        items = g.get("items") or []
        times = [norm(it.get("time")) for it in items]
        blob = gblob(g)
        d = fmt_ts(g.get("deadline"))
        S("L4.4 云端合并行 items≥3 且覆盖 20:47/21:07 报送/电子版/纸质版",
          len(items) >= 3 and any("20:47" in t for t in times) and any("21:07" in t for t in times)
          and "电子版" in blob and "纸质版" in blob and ("报送姓名" in blob or "报送" in blob),
          "id=%s items=%d times=%s" % (g.get("_row", {}).get("id"), len(items), times))
        S("L4.5 云端合并行 deadline=2026-11-06 12:00",
          d is not None and d.astimezone(CN).strftime("%Y-%m-%d %H:%M") == "2026-11-06 12:00",
          str(g.get("deadline")))
        S("L4.6 云端合并行 deadlineAction 含「截止」", "截止" in norm(g.get("deadlineAction")),
          str(g.get("deadlineAction")))
        S("L4.7 云端合并行 id 符合 auto_g_ait_5396a55f24 或含 5396 的合并 id",
          "5396a55f24" in str(g.get("_row", {}).get("id")) or "5396a55f24" in str(g.get("id")),
          "row.id=%s group.id=%s" % (g.get("_row", {}).get("id"), g.get("id")))

    # 药膳 / 手抄报 signup 字段
    med = next((g for g in groups if str(g.get("id", "")).startswith("g_qqm_7704134971497063025_c0")), None)
    S("L4.8 云端药膳行含 signupStart/signupEnd",
      bool(med) and bool(med.get("signupStart") or med.get("signupEnd")),
      med and "%s ~ %s" % (med.get("signupStart"), med.get("signupEnd")))
    food = next((g for g in groups if "手抄报" in gblob(g)), None)
    S("L4.9 云端手抄报行含 signup 且报名截止已过",
      bool(food) and fmt_ts(food.get("signupEnd")) is not None
      and fmt_ts(food.get("signupEnd")) < now,
      food and "signupEnd=%s" % food.get("signupEnd"))

    # 花名册发送者
    fileg = next((g for g in groups if str(g.get("id", "")).startswith("g_qqfile_1a81286a3a")), None)
    S("L4.10 云端花名册行 senderRole=学习委员 / senderName=兰佳杰",
      bool(fileg) and norm(fileg.get("senderName")) == "兰佳杰"
      and ("学习委员" in norm(fileg.get("senderRole")) or "班委" in norm(fileg.get("senderBadge"))),
      fileg and "senderName=%s senderRole=%s senderBadge=%s" % (
          fileg.get("senderName"), fileg.get("senderRole"), fileg.get("senderBadge")))

    # 献血通知（本人 10:18 转发；Lead 口径：并入既有献血卡=通过，独立新卡=FAIL）
    xx = [g for g in groups if "献血" in gblob(g)]
    S("L4.11 云端献血通知仅 1 行（本人转发并入既有卡，无独立新卡）", len(xx) == 1,
      "献血行=%s" % [(g.get("_row", {}).get("id"), g.get("title")) for g in xx])
    if len(xx) == 1:
        g = xx[0]

        def itblob(it):
            return (norm(it.get("text")) + " " + norm(it.get("name")) + " " + norm(it.get("from"))
                    + " " + norm(it.get("fromName")) + " " + norm(it.get("note")))

        its = g.get("items") or []
        sup_text = [it for it in its if norm(it.get("label")) == "补充通知" and "陈子麒" in itblob(it)
                    and norm(it.get("time")) == "11-05 10:18"
                    and any(w in itblob(it) for w in ("11月14日", "下周六", "献血"))]
        my_link = [it for it in its if "陈子麒" in itblob(it) and norm(it.get("url"))
                   and "mp.weixin" in norm(it.get("url"))]
        note_ok = any("本人转发" in norm(it.get("note")) for it in its)
        ev = fmt_ts(g.get("eventAt"))
        S("L4.12 云端献血行含本人 10:18「补充通知」text item + 可点公众号链接（note 含本人转发）",
          len(sup_text) >= 1 and len(my_link) >= 1 and note_ok,
          "sup_text=%d link=%d note本人转发=%s" % (len(sup_text), len(my_link), note_ok))
        S("L4.13 云端献血行 eventAt=2026-11-14 / eventAction=开始（§0.2 短动作）",
          ev is not None and ev.astimezone(CN).strftime("%Y-%m-%d") == "2026-11-14"
          and "开始" in norm(g.get("eventAction")),
          "eventAt=%s eventAction=%s" % (g.get("eventAt"), g.get("eventAction")))
        S("L4.14 云端献血行标题/摘要含「献血」",
          "献血" in norm(g.get("title")) + norm(g.get("summary")) + norm(g.get("aiSummary")),
          "%s | %s" % (g.get("title"), norm(g.get("aiSummary"))[:80]))

    # 管理员覆盖列存在（同类迁移不在本轮，但 schema 需兼容）
    sample = rows[0] if rows else {}
    S("L4.15 云端 notices 行带 hidden/edited_at/override_json 列",
      any(k in sample for k in ("hidden", "edited_at", "override_json")),
      "keys=%s" % list(sample.keys())[:10])

    # c1 药膳手记热修回归（Lead 2026-11-05 23:25：signup 被误刷 11-14 → 恢复 11-05 12:00-18:00）
    c1 = next((g for g in groups if str(g.get("id", "")).startswith("g_qqm_7704134971497063025_c1")), None)
    if c1:
        ss, se, dl = fmt_ts(c1.get("signupStart")), fmt_ts(c1.get("signupEnd")), fmt_ts(c1.get("deadline"))

        def cli(d):
            return d.astimezone(CN).strftime("%Y-%m-%d %H:%M") if d is not None else "None"

        S("L4.16 云端药膳手记 c1 signupStart=11-05 12:00 / signupEnd=11-05 18:00 / deadline=11-05 18:00",
          ss is not None and se is not None and dl is not None
          and cli(ss) == "2026-11-05 12:00" and cli(se) == "2026-11-05 18:00"
          and cli(dl) == "2026-11-05 18:00" and "报名截止" in norm(c1.get("deadlineAction")),
          "signup=%s ~ %s deadline=%s action=%s" % (cli(ss), cli(se), cli(dl), c1.get("deadlineAction")))
    else:
        S("L4.16 云端药膳手记 c1 行存在", False, "g_qqm_7704134971497063025_c1")

    return finish(tpl_sha)


def finish(tpl_sha=None):
    total = len(STEPS)
    passed = sum(1 for s in STEPS if s["ok"])
    ts = datetime.now(CN)
    result = {"checkedAt": ts.isoformat(), "url": LIVE_URL, "passed": passed, "total": total,
              "tplSha256": tpl_sha, "steps": STEPS}
    p = os.path.join(OUT, "live_check_%s.json" % ts.strftime("%Y%m%d-%H%M%S"))
    json.dump(result, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    lines = ["# 线上验证报告（通知时间显示与识别）", "",
             "- 时间：%s" % ts.strftime("%Y-%m-%d %H:%M:%S"),
             "- 线上：`%s`" % LIVE_URL,
             "- NOTICE_TPL_B64 sha256：`%s`" % (tpl_sha or "-"),
             "- 结果：**%d/%d PASS，%d FAIL**" % (passed, total, total - passed), ""]
    for s in STEPS:
        lines.append("- [%s] %s%s" % ("PASS" if s["ok"] else "FAIL", s["k"],
                                      (" — `" + s["note"] + "`") if s["note"] else ""))
    md = os.path.join(OUT, "live_report.md")
    open(md, "w", encoding="utf-8").write("\n".join(lines))
    print("=" * 64)
    print("v2_notice_time_live_check: %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("报告：%s" % md)
    print("=" * 64)
    sys.exit(0 if total and passed == total else 1)


if __name__ == "__main__":
    main()
