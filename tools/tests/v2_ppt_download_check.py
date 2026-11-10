# -*- coding: utf-8 -*-
"""PPT v2.0（网页端）· 下载中心 / 下载详情 / 兼容提示 专项验收 —— `v2_ppt_download_check.py`

契约唯一真源：`web/ppt/CONTRACT.md` §12（v2.0 功能重定义：上传 PPT → 自动兼容性处理 → 多端下载）
§12.2 manifest v2（files.compat/pdf/source + compat.warnings + slides 可为空）、§12.4.1 列表/详情 UI。

覆盖（断言数见文末统计）：
  S 静态：__PPT_DL_V1__ 标记、列表无播放按钮（点击卡片=下载详情）、三行 fileRow/download、
          旧 deck 三态文案、兼容提示、APP_VER 2.0.0、零外部依赖
  A 新 deck（manifest v2，slides=[]）：列表标签「兼容版/PDF」+ 大小；点击卡片=下载详情（不进播放器）；
    三行下载（兼容版 PPTX / PDF / 原始文件）href=base+s、download=name、人类可读大小、PDF 页数；
    兼容提示逐条；无在线预览；Esc/× 关闭；430px 无横向溢出
  B 旧 deck（无 files）：兼容版未生成 + 在线预览 + 重新处理 + 原始文件下载；在线预览可进旧播放器（覆盖保留）；
    旧 deck 无 slides → 无在线预览按钮
  C 状态：queued 详情只显示状态/进度、无下载；failed 显示 error + 重试（PATCH status=queued 真实发出）
  D 汇总：0 JS 报错 / 0 console.error / 0 真实云端写；轻量 hint 查询（manifest->files）确实执行

做法：复用 `v2_ppt_check.py` 的 CDP mock 基座（`B.install_cdp_mock` / `B.MOCK` / `B.Server` / `B.Session`），
只 mock `ppt_decks` / `ppt_upload_chunks` / `site_assets`；注入假 token，非 mock 写请求全部拦截（0 真实云端写）；
下载只校验 `<a href/download>` 属性，不真实下载大文件。截图存 `tests/_shots_ppt_download/`。

用法（cwd 任意）：python web/tools/tests/v2_ppt_download_check.py   （退出码 0 = 全绿）
"""
import json
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))       # tools/tests
TOOLS = os.path.dirname(HERE)                           # tools
SRC = os.environ.get("PPTC_SRC") or os.path.join(TOOLS, "index.html")
SHOTS = os.path.join(HERE, "_shots_ppt_download")

sys.path.insert(0, HERE)
import v2_ppt_check as B  # noqa: E402  （CDP mock 基座 / 断言 / 工具 / svg / Session）

NOW = int(time.time() * 1000)
BASE_URL = "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/ppt/a/dtestdl1/b1/"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
WARN1 = "外链视频 1 处未随文件携带（第 7 页，路径尾 …/v.mp4）"
WARN2 = "字体未嵌入：思源黑体（许可受限）"


def v2_manifest():
    """契约 §12.2 manifest v2：slides=[] + files + compat.warnings。"""
    return {
        "v": 2, "base": BASE_URL, "w": 960, "h": 540,
        "slides": [],
        "files": {
            "compat": {"s": "compat.pptx", "size": 12345678, "sha256": SHA_A,
                       "ext": "pptx", "name": "班会_兼容版.pptx"},
            "pdf": {"s": "preview.pdf", "size": 1234567, "sha256": SHA_B,
                    "pages": 16, "name": "班会.pdf"},
            "source": {"s": "original.pptx", "size": 12345678, "sha256": SHA_C,
                       "ext": "pptx", "name": "班会.pptx"},
        },
        "compat": {"warnings": [WARN1, WARN2], "fonts_embedded": 0, "converted_from": "ppt"},
    }


def legacy_manifest():
    """旧 deck manifest（v1）：有 slides/src/video，但无 files。"""
    man = json.loads(json.dumps(B.MANIFEST))
    return man


NO_PREVIEW_MANIFEST = {"v": 1, "base": "", "w": 1600, "h": 900, "slides": [], "media": []}


def make_decks():
    def row(did, title, man, created, **kw):
        r = B.deck(id=did, title=title, manifest=man, created_at=created,
                   slide_count=len(man.get("slides") or []),
                   step_count=sum(len(s.get("steps") or []) for s in (man.get("slides") or [])))
        r.update(kw)
        return r
    return [
        row("dtestdl1", "班会兼容版", v2_manifest(), NOW - 1000,
            slide_count=16, step_count=0, cover_url=B.THUMB2, source_name="班会.pptx",
            source_size=12345678),
        row("dtestdll1", "旧版演示", legacy_manifest(), NOW - 2000,
            slide_count=3, step_count=4, cover_url=B.THUMB1),
        row("dtestdlnone1", "无预览旧版", NO_PREVIEW_MANIFEST, NOW - 2500,
            slide_count=0, step_count=0, cover_url=""),
        row("dtestdlq1", "排队中的演示", {}, NOW - 3000,
            status="queued", progress=0, slide_count=0, step_count=0, cover_url="", manifest={}),
        row("dtestdlf1", "失败演示", {}, NOW - 4000,
            status="failed", progress=0, error="兼容处理失败：文件已加密", slide_count=0,
            step_count=0, cover_url="", manifest={}),
    ]


# ---------------------------------------------------------------- 工具
R = B.Results()


def js(page, expr, await_promise=False):
    return page.evaluate(expr, await_promise=await_promise)


def wait(page, expr, timeout=8.0):
    return B.wait_js(page, expr, timeout=timeout)


def shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    return page.screenshot(os.path.join(SHOTS, name + ".png"))


def open_card(page, did):
    ok = js(page, "(function(){var c=document.querySelector('#pptList [data-deck=\"%s\"] .ppt-bd');"
                  "if(!c)return false;c.click();return true;})()" % did)
    if not ok:
        return False
    return wait(page, "(function(){var d=document.getElementById('pptDl');"
                      "return !!d&&!d.hidden;})()", 6)


def close_detail(page):
    js(page, "(function(){var b=document.querySelector('#pptDl [data-dlact=\"close\"]');"
             "if(b)b.click();return true;})()")
    time.sleep(0.25)


def wait_detail_ready(page, timeout=8.0):
    """等详情懒拉 manifest 完成（出现文件行/未生成/状态/失败之一，且不再骨架）。"""
    return wait(page, "(function(){var b=document.getElementById('pptDlBody');"
                      "if(!b)return false;return b.querySelectorAll('.ppt-dl-skel').length===0;})()", timeout)


def detail_state(page):
    return js(page, r"""(function(){
      var o=document.getElementById('pptDl');
      if(!o||o.hidden)return null;
      var card=document.getElementById('pptDlCard');
      var files=[].slice.call(o.querySelectorAll('.ppt-file')).map(function(r){
        var a=r.querySelector('a[download]');
        var d=r.querySelector('.ppt-file-d');
        return {cls:r.className, label:d?d.querySelector('b').textContent:'',
          sub:d&&d.querySelector('em')?d.querySelector('em').textContent:'',
          href:a?a.getAttribute('href'):'', name:a?a.getAttribute('download'):'',
          hasDl:!!a};
      });
      var warns=o.querySelectorAll('.ppt-warn li');
      var wt=o.querySelector('.ppt-warn');
      return {open:!o.hidden,title:(document.getElementById('pptDlTitle')||{}).textContent||'',
        meta:(document.getElementById('pptDlMeta')||{}).textContent||'',
        txt:(document.getElementById('pptDlBody')||{}).innerText||'',
        files:files, nFiles:files.length,
        warn:!!wt, warnings:[].slice.call(warns).map(function(li){return li.textContent;}),
        warnBg:wt?getComputedStyle(wt).backgroundColor:'',
        preview:!!o.querySelector('[data-dlact="preview"]'),
        retry:!!o.querySelector('[data-dlact="retry"]'),
        close:!!o.querySelector('[data-dlact="close"]'),
        status:(o.querySelector('.ppt-st')||{}).textContent||'',
        err:(o.querySelector('.ppt-dl-err')||{}).textContent||'',
        player:!!document.getElementById('pptPlayer'),
        lock:document.body.classList.contains('ppt-dl-lock'),
        cardRect:card?(function(){var q=card.getBoundingClientRect();
          return [Math.round(q.left),Math.round(q.right),Math.round(q.width),Math.round(q.height)];})():null,
        docSW:document.documentElement.scrollWidth, vw:innerWidth};})()""")


def card_state(page, did):
    expr = r"""(function(){
      var c=document.querySelector('#pptList [data-deck="__DECK__"]');
      if(!c)return null;
      var tags=[].slice.call(c.querySelectorAll('.ppt-tag')).map(function(t){return t.textContent;});
      return {tags:tags, meta:(c.querySelector('.ppt-meta')||{}).textContent||'',
        txt:(c.innerText||'').replace(/\n/g,' | '),
        play:!!c.querySelector('[data-act="play"]')||!!c.querySelector('.ppt-cvplay'),
        del:!!c.querySelector('[data-act="del"]')};})()""".replace("__DECK__", did)
    return js(page, expr)


def close_player_any(page):
    js(page, "(function(){var b=document.querySelector('#pptPlayer [data-act=\"close\"]');"
             "if(b)b.click();return true;})()")
    time.sleep(0.3)
    st = js(page, "(function(){var c=document.getElementById('pptConfirm');"
                  "return {p:!!document.getElementById('pptPlayer'),c:!!(c&&!c.hidden)};})()")
    if st and st.get("c"):
        js(page, "(function(){var b=document.querySelector('#pptConfirm [data-act=\"leave\"]');"
                 "if(b)b.click();return true;})()")
        time.sleep(0.35)
    return not js(page, "!!document.getElementById('pptPlayer')")


class DlSession(B.Session):
    """在基座 Session 上进入「演示」tab 并等列表加载。"""

    def __init__(self, server, width=430, height=900, mobile=True):
        super(DlSession, self).__init__(server, width, height, mobile)
        try:
            self.js("(function(){var b=document.querySelector('#tabsBar button[data-tab=\"ppt\"]');"
                    "if(b)b.click();return true;})()")
            self.wait("(function(){var s=document.querySelector('section.on');"
                      "return !!s&&s.id==='s-ppt';})()", 8)
            self.wait("document.querySelectorAll('#pptList .ppt-card').length>=5", 12)
            time.sleep(0.45)
        except Exception:
            self.close()
            raise


# ---------------------------------------------------------------- S 静态
def static_checks():
    try:
        html = open(SRC, encoding="utf-8", newline="").read()
    except Exception as e:  # noqa: BLE001
        R.add("静态：能读取 index.html", False, repr(e))
        return
    flat = re.sub(r"\s+", "", html)
    R.add("静态：APP_VER 仍为 2.0.0", 'varAPP_VER="2.0.0"' in flat)
    R.add("静态：v2.0 下载中心块标记 __PPT_DL_V1__（CSS+JS）",
          html.count("__PPT_DL_V1__") >= 2, html.count("__PPT_DL_V1__"))
    R.add("静态：列表不再有列表级播放按钮（点击卡片=下载详情）",
          'data-act="play"' not in html and 'data-dlact="preview"' in html)
    R.add("静态：详情三行下载（兼容版/PDF/原始）+ <a download> + 文件名/大小来自 files",
          all(('fileRow("%s"' % k) in html for k in ("compat", "pdf", "source"))
          and 'download="' in flat and "filesMeta" in flat and "files.compat" in flat)
    R.add("静态：列表标签「兼容版 / PDF」+ 单 deck manifest 懒拉 + manifest->files 轻量提示",
          "ppt-tag" in html and "兼容版" in html and "PDF" in html
          and "ppt_decks?select=" in html and "manifest->files" in flat)
    R.add("静态：旧 deck 三态（兼容版未生成 / 在线预览 / 重新处理）+ 兼容提示",
          all(t in html for t in ("兼容版未生成", "在线预览", "重新处理", "兼容提示")))
    R.add("静态：详情弹层内滑动不切工具（resolveStart 排除 #pptDl）",
          'closest(t,"#pptDl")' in flat)
    R.add("静态：无外部脚本/字体/CDN（单文件零依赖）",
          "<script src=" not in html and "fonts.googleapis" not in html and "cdn." not in html)
    R.add("静态：不新增密钥（无 AccessKey / LTAI）",
          "AccessKey" not in html and "LTAI" not in html)


# ---------------------------------------------------------------- A 新 deck（v2 manifest）
def scenario_v2_deck(sess):
    page = sess.page
    card = card_state(page, "dtestdl1")
    R.add("列表：有 files 的 deck 显示「兼容版」「PDF」小标签（不写长句）",
          bool(card) and card.get("tags") == ["兼容版", "PDF"],
          json.dumps(card, ensure_ascii=False)[:240])
    R.add("列表：卡片展示页数 + 人类可读大小（16 页 · 12MB）",
          bool(card) and "16 页" in str(card.get("meta")) and "12MB" in str(card.get("meta")),
          (card or {}).get("meta"))
    R.add("列表：卡片无列表播放按钮/封面 ▶（点击=下载详情）", bool(card) and card.get("play") is False)
    legacy_card = card_state(page, "dtestdll1")
    R.add("列表：旧 deck（无 files）不显示兼容版/PDF 标签", legacy_card.get("tags") == [],
          json.dumps(legacy_card, ensure_ascii=False)[:200])
    shot(page, "A0_list_tags")
    ok = open_card(page, "dtestdl1")
    R.add("详情：点击卡片 → 打开下载详情（不直接进播放器）",
          ok and not js(page, "!!document.getElementById('pptPlayer')"))
    if not wait_detail_ready(page):
        R.add("详情：manifest 懒拉完成", False)
        return
    st = detail_state(page)
    R.add("详情：标题/页数信息（班会兼容版 · 16 页）",
          bool(st) and st.get("title") == "班会兼容版" and "16 页" in str(st.get("meta")),
          json.dumps({k: (st or {}).get(k) for k in ("title", "meta")}, ensure_ascii=False))
    R.add("详情：三行下载（兼容版 PPTX / PDF / 原始文件）",
          bool(st) and st.get("nFiles") == 3
          and [f.get("label") for f in st.get("files") or []] == ["兼容版 PPTX", "PDF", "原始文件"],
          json.dumps([(f.get("label"), f.get("sub")) for f in (st or {}).get("files") or []],
                     ensure_ascii=False))
    files = (st or {}).get("files") or []
    by = {f.get("label"): f for f in files}
    compat = by.get("兼容版 PPTX") or {}
    pdf = by.get("PDF") or {}
    source = by.get("原始文件") or {}
    R.add("详情：兼容版 PPTX href=base+compat.pptx、download=name、大小 12MB",
          compat.get("href") == BASE_URL + "compat.pptx"
          and compat.get("name") == "班会_兼容版.pptx" and "12MB" in str(compat.get("sub"))
          and compat.get("hasDl") is True,
          json.dumps(compat, ensure_ascii=False)[:240])
    R.add("详情：PDF href=base+preview.pdf、download=name、显示页数（16 页 · 1.2MB）",
          pdf.get("href") == BASE_URL + "preview.pdf" and pdf.get("name") == "班会.pdf"
          and "16 页" in str(pdf.get("sub")) and "1.2MB" in str(pdf.get("sub")),
          json.dumps(pdf, ensure_ascii=False)[:240])
    R.add("详情：原始文件 href=base+original.pptx、download=name",
          source.get("href") == BASE_URL + "original.pptx" and source.get("name") == "班会.pptx",
          json.dumps(source, ensure_ascii=False)[:240])
    R.add("详情：兼容提示橙色区逐条显示（外链媒体 / 字体未嵌入）",
          bool(st) and st.get("warn") and len(st.get("warnings") or []) == 2
          and any("外链视频" in w for w in st.get("warnings") or [])
          and any("字体未嵌入" in w for w in st.get("warnings") or [])
          and "251, 244, 233" in str(st.get("warnBg")),
          json.dumps({k: (st or {}).get(k) for k in ("warn", "warnings", "warnBg")}, ensure_ascii=False)[:280])
    R.add("详情：manifest v2（slides=[]）不显示在线预览按钮（下载中心为主）",
          bool(st) and st.get("preview") is False and st.get("player") is False)
    R.add("详情：430px 弹层不横向溢出（页面 scrollWidth ≤ 视口、卡片在视口内）",
          bool(st) and st.get("docSW", 9999) <= st.get("vw", 0) + 1
          and bool(st.get("cardRect")) and st["cardRect"][0] >= 0
          and st["cardRect"][1] <= st.get("vw", 0) + 1, json.dumps(st.get("cardRect")))
    R.add("详情：打开时锁定页面滚动（body.ppt-dl-lock）", bool(st) and st.get("lock") is True)
    time.sleep(0.35)  # 等入场动画结束，截图稳定
    shot(page, "A1_detail_v2")
    # Esc 关闭
    B.press(page, "Escape", "Escape", 27)
    time.sleep(0.3)
    closed = js(page, "(function(){var d=document.getElementById('pptDl');"
                      "return {hidden:!d||d.hidden,lock:document.body.classList.contains('ppt-dl-lock')};})()")
    R.add("详情：Esc 关闭弹层并解除滚动锁定", bool(closed) and closed.get("hidden") and not closed.get("lock"),
          json.dumps(closed, ensure_ascii=False))
    # 再开 → × 关闭
    ok2 = open_card(page, "dtestdl1") and wait_detail_ready(page)
    close_detail(page)
    R.add("详情：右上「×」可关闭", ok2 and js(page, "(function(){var d=document.getElementById('pptDl');"
                                                    "return !d||d.hidden;})()"))
    # 外部 API 兼容：大屏演示等旧调用 PPT.open(新兼容版 deck) → 无在线画面 → 打开下载详情而非报错
    js(page, "(function(){window.PPT.open('dtestdl1');return true;})()")
    wait(page, "(function(){var d=document.getElementById('pptDl');return !!d&&!d.hidden;})()", 4)
    api_open = js(page, "(function(){var d=document.getElementById('pptDl');"
                        "return {dl:!!d&&!d.hidden,player:!!document.getElementById('pptPlayer')};})()")
    R.add("外部调用 PPT.open(兼容版 deck)：打开下载详情（不报错、不进空播放器）",
          bool(api_open) and api_open.get("dl") and not api_open.get("player"),
          json.dumps(api_open, ensure_ascii=False))
    close_detail(page)


# ---------------------------------------------------------------- B 旧 deck 兼容
def scenario_legacy_deck(sess):
    page = sess.page
    ok = open_card(page, "dtestdll1")
    ready = wait_detail_ready(page) if ok else False
    st = detail_state(page) if ready else None
    R.add("旧 deck：详情显示「兼容版未生成」", bool(st) and "兼容版未生成" in str(st.get("txt")),
          (st or {}).get("txt", "")[:120])
    R.add("旧 deck：详情提供「在线预览」+「重新处理」+ 原始文件下载（旧 manifest.src）",
          bool(st) and st.get("preview") and st.get("retry") and st.get("nFiles") == 1
          and ((st.get("files") or [{}])[0].get("label") == "原始文件"),
          json.dumps({k: (st or {}).get(k) for k in ("preview", "retry", "nFiles")}, ensure_ascii=False))
    R.add("旧 deck：无兼容提示区（旧 manifest 无 compat.warnings）", bool(st) and st.get("warn") is False)
    screenshot_done = False
    if st and st.get("preview"):
        js(page, "(function(){var b=document.querySelector('#pptDl [data-dlact=\"preview\"]');"
                 "if(b)b.click();return true;})()")
        popen = wait(page, "!!document.getElementById('pptPlayer')", 8)
        time.sleep(0.8)
        pst = js(page, "(function(){var p=document.getElementById('pptPlayer');"
                       "var a=document.querySelectorAll('#pptPlayer .ppt-layer img'),ok=false;"
                       "for(var i=0;i<a.length;i++){if(a[i].naturalWidth>0)ok=true;}"
                       "return {player:!!p,img:ok,"
                       "idx:(document.getElementById('pptIdx')||{}).textContent||''};})()")
        R.add("旧 deck：在线预览入口可进旧播放器（播放器覆盖保留、图片正常）",
              popen and bool(pst) and pst.get("player") and pst.get("img"),
              json.dumps(pst, ensure_ascii=False))
        close_player_any(page)
        R.add("旧 deck：关闭预览后回到列表（播放器移除）",
              not js(page, "!!document.getElementById('pptPlayer')"))
        open_card(page, "dtestdll1") and wait_detail_ready(page)
        time.sleep(0.35)
        shot(page, "B1_legacy_detail")
        screenshot_done = True
        close_detail(page)
    # 无 slides 的旧 deck → 无在线预览
    ok2 = open_card(page, "dtestdlnone1")
    ready2 = wait_detail_ready(page) if ok2 else False
    st2 = detail_state(page) if ready2 else None
    R.add("旧 deck（无 slides/video）：仍显示「兼容版未生成」+「重新处理」，无在线预览",
          bool(st2) and "兼容版未生成" in str(st2.get("txt"))
          and st2.get("preview") is False and st2.get("retry") is True,
          json.dumps({k: (st2 or {}).get(k) for k in ("preview", "retry")}, ensure_ascii=False))
    close_detail(page)


# ---------------------------------------------------------------- C 状态（queued / failed / 重试）
def scenario_states(sess):
    page = sess.page
    ok = open_card(page, "dtestdlq1")
    if ok:
        wait_detail_ready(page)
    st = detail_state(page) if ok else None
    R.add("状态非 ready：详情只显示「排队转换」状态，不显示下载",
          bool(st) and "排队转换" in str(st.get("status")) and st.get("nFiles") == 0
          and "下载" not in str(st.get("txt")),
          json.dumps({k: (st or {}).get(k) for k in ("status", "nFiles")}, ensure_ascii=False))
    close_detail(page)
    okf = open_card(page, "dtestdlf1")
    if okf:
        wait_detail_ready(page)
    stf = detail_state(page) if okf else None
    R.add("失败 deck：详情显示「转换失败」+ error 原文 + 重试按钮",
          bool(stf) and "转换失败" in str(stf.get("status"))
          and "兼容处理失败：文件已加密" in str(stf.get("err")) and stf.get("retry"),
          json.dumps({k: (stf or {}).get(k) for k in ("status", "err", "retry")}, ensure_ascii=False))
    time.sleep(0.3)
    shot(page, "C1_failed_detail")
    n0 = len(B.MOCK["patches"])
    patches = []
    for _attempt in range(3):
        js(page, "(function(){var b=document.querySelector('#pptDl [data-dlact=\"retry\"]');"
                 "if(b)b.click();return true;})()")
        for _ in range(20):
            time.sleep(0.08)
            with B.MOCK_LOCK:
                patches = [p for p in B.MOCK["patches"][n0:] if p.get("id") == "dtestdlf1"]
            if patches:
                break
        if patches:
            break
        time.sleep(0.2)
    if not patches:
        time.sleep(0.6)
        with B.MOCK_LOCK:
            patches = [p for p in B.MOCK["patches"][n0:] if p.get("id") == "dtestdlf1"]
    R.add("失败 deck：详情「重试」→ PATCH status=queued（重新处理）",
          bool(patches) and patches[-1].get("body", {}).get("status") == "queued",
          json.dumps(patches[-1:] if patches else [], ensure_ascii=False)[:240])
    R.add("失败 deck：重试后关闭详情、回到列表",
          js(page, "(function(){var d=document.getElementById('pptDl');return !d||d.hidden;})()"))


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    print("=" * 72)
    print("v2_ppt_download_check · PPT v2.0 网页下载中心专项验收")
    print("被测文件: %s (%d B)" % (SRC, os.path.getsize(SRC)))
    print("=" * 72)
    static_checks()
    os.makedirs(SHOTS, exist_ok=True)
    with B.MOCK_LOCK:
        B.MOCK["decks"] = make_decks()
        B.MOCK["agent"].update({"online": True, "seen_at": int(time.time() * 1000)})
        B.MOCK["posts"] = []
        B.MOCK["patches"] = []
        B.MOCK["chunks"] = []
        B.MOCK["blocked_writes"] = []
        B.MOCK["hint_gets"] = 0
    server = B.Server()
    server.start()
    sess = None
    try:
        sess = DlSession(server)
        scenario_v2_deck(sess)
        scenario_legacy_deck(sess)
        scenario_states(sess)
        errs = sess.errors()
        R.add("0 JS 报错（window.onerror / unhandledrejection / CDP exception）",
              not errs["js_errs"] and not errs["cdp_exc"],
              json.dumps({"js": errs["js_errs"][:3], "cdp": errs["cdp_exc"][:3]}, ensure_ascii=False))
        R.add("0 console.error", not errs["console_errs"] and not errs["cdp_console"],
              json.dumps({"js": errs["console_errs"][:3], "cdp": errs["cdp_console"][:3]}, ensure_ascii=False))
        with B.MOCK_LOCK:
            hint_gets = B.MOCK.get("hint_gets", 0)
            blocked = list(B.MOCK["blocked_writes"])
        R.add("v2.0 列表标签：轻量 hint 查询（manifest->files）已执行", hint_gets >= 1, "hint_gets=%s" % hint_gets)
        R.add("0 真实云端写（非 mock 写请求全部拦截）",
              all(("ppt_decks" not in x and "ppt_upload_chunks" not in x) for x in blocked),
              json.dumps(blocked[:6], ensure_ascii=False))
        R.add("430px：列表+详情全程无横向溢出",
              js(sess.page, "document.documentElement.scrollWidth<=innerWidth") is True,
              "sw=%s vw=%s" % (js(sess.page, "document.documentElement.scrollWidth"),
                               js(sess.page, "innerWidth")))
    finally:
        if sess:
            sess.close()
    server.stop()
    total, passed, failed = R.summary()
    print("=" * 72)
    print("v2_ppt_download_check: %d 项，PASS %d，FAIL %d（%.1fs）"
          % (total, passed, failed, time.time() - t0))
    print("截图: %s" % SHOTS)
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
