# -*- coding: utf-8 -*-
"""v2.0.0 微信附件链路自测（用户反馈「微信通知附件未识别」）。

不依赖当前 weflow 班级群消息可读性：mock weflow REST 响应 + 真实本地明文微信文件，
覆盖 wechat_media → ai_triage 结构 → builder 注入 → 模板渲染 全链路。

跑法：C:\\briefdesk\\venv\\Scripts\\python.exe -X utf8 briefdesk-plan\\_check_wechat_attach.py
"""
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"C:\briefdesk\scripts")
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
CN = timezone(__import__("datetime").timedelta(hours=8))
FAILED = []

# 本地真实明文微信文件（用户微信下载目录里的通知文件，仅用于链路验证，不复制隐私内容）
REAL_WX_FILE = Path(r"C:\Users\Ko_Li\Documents\xwechat_files\wxid_8gkjq1am5n7822_9afa\msg\file\2026-10\关于2026级新生自购军训服装的通知.doc")


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else (" | " + str(detail)[:300])))
    if not cond:
        FAILED.append(name)


def test_wechat_media(tmp):
    import wechat_media
    # 重定向写入路径到临时目录（不碰正式 data）
    wechat_media.OUT_DIR = tmp / "wechat-media"
    wechat_media.MANIFEST = tmp / "wechat-media.json"
    wechat_media.LOG = tmp / "wechat-media.log"
    now = int(time.time())
    fake_sessions = [{"username": "12345@chatroom", "displayName": "26信管班群",
                      "sessionType": "group", "lastTimestamp": now},
                     {"username": "999@chatroom", "displayName": "游戏群",
                      "sessionType": "group", "lastTimestamp": now}]
    fake_msgs = {"12345@chatroom": [
        {"serverId": "s1", "createTime": now - 120, "senderName": "陈玉霞",
         "content": "军训服装通知，附件如下", "media": None},
        {"serverId": "s2", "createTime": now - 60, "senderName": "陈玉霞",
         "content": "[文件]", "media": {"type": "file", "fileName": REAL_WX_FILE.name,
                                        "md5": "abc123def456abc1"}},
        {"serverId": "s3", "createTime": now - 30, "senderName": "陈玉霞",
         "content": "[图片]", "media": {"type": "image", "fileName": "deadbeef00.jpg",
                                        "md5": "deadbeef00deadbeef"}},
    ], "999@chatroom": []}

    def fake_api(path, timeout=90):
        if path.startswith("/api/v1/sessions"):
            return {"sessions": fake_sessions}
        m = re.search(r"talker=([^&]+)", path)
        talker = m.group(1) if m else ""
        import urllib.parse
        talker = urllib.parse.unquote(talker)
        return {"messages": fake_msgs.get(talker, [])}

    wechat_media.api = fake_api
    wechat_media.token = lambda: "fake-token"
    res = wechat_media.run(lookback_minutes=360)
    print("  wechat_media.run ->", res)
    manifest = json.loads((tmp / "wechat-media.json").read_text(encoding="utf-8"))
    items = manifest.get("items") or {}
    check("wechat_media 采集到 2 条媒体", len(items) == 2, len(items))
    files = [v for v in items.values() if v.get("kind") == "file"]
    imgs = [v for v in items.values() if v.get("kind") == "img"]
    check("微信文件命中本地明文文件", bool(files) and files[0].get("status") == "ok"
          and Path(files[0].get("storedPath") or "").exists(), files[:1])
    check("微信图片标记待密钥/待获取", bool(imgs) and imgs[0].get("status") in ("pending_key", "missing"),
          imgs[:1])
    check("群过滤（非班级群不采）", all(v.get("group") == "26信管班群" for v in items.values()))
    return manifest


def test_ai_triage_structures(manifest):
    import ai_triage
    file_key, item = next((k, v) for k, v in manifest["items"].items() if v.get("kind") == "file")
    media = {"type": "file", "fileName": item.get("fileName"), "md5": item.get("md5")}
    m = {"serverId": item["serverId"], "createTime": int(item["ts"]),
         "senderName": "陈玉霞", "content": "[文件]", "media": media}
    msg = ai_triage.wx_message_to_msg(m, "26信管班群", "12345@chatroom", 0)
    check("ai_triage: 微信文件消息不被丢弃", msg is not None and msg["kind"] == "file", msg)
    check("ai_triage: mediaKey 与 wechat_media 一致", msg and msg["mediaKey"] == file_key,
          (msg or {}).get("mediaKey"))
    mi = ai_triage.media_item(msg)
    check("ai_triage: 文件 → file item", mi and mi["kind"] == "file" and mi["mediaKey"], mi)
    # 图片
    im = {"serverId": "img1", "createTime": int(item["ts"]), "senderName": "陈玉霞",
          "content": "[图片]", "media": {"type": "image", "fileName": "aa.jpg", "md5": "aa1122334455"}}
    msg2 = ai_triage.wx_message_to_msg(im, "26信管班群", "12345@chatroom", 0)
    check("ai_triage: 微信图片消息保留为 image_media", msg2 and msg2["kind"] == "image_media", msg2)
    # 相邻附件挂载：文字通知 + 同群 ±10min 的图片/文件
    text_msg = {"src": "wx", "key": "wx:12345@chatroom:t1", "gid": "12345@chatroom",
                "group": "26信管班群", "sender": "陈玉霞", "ts": int(item["ts"]),
                "time": "11-06 12:00", "text": "军训服装通知", "kind": "text", "url": ""}
    picked = [text_msg]
    batch = [text_msg, msg, msg2]
    covered = {text_msg["key"]}
    notice = ai_triage.make_notice({"title": "军训服装通知", "summary": "通知原文"}, picked, "军训服装通知")
    added = ai_triage.attach_media_items(notice, picked, batch, covered)
    kinds = [it["kind"] for it in notice["items"]]
    check("ai_triage: 相邻微信附件自动挂载", added == 2 and "file" in kinds and "img" in kinds,
          (added, kinds))
    # 孤立文件消息兜底成通知
    fn = ai_triage.standalone_file_notice(msg)
    check("ai_triage: 孤立微信文件兜底通知", fn is not None and fn["items"][0]["kind"] == "file", fn)
    # 接龙仍过滤
    check("ai_triage: 接龙仍被过滤", ai_triage.wx_message_to_msg(
        {"serverId": "c1", "createTime": int(time.time()), "senderName": "x",
         "content": "#接龙 1. 张三 2. 李四", "media": None}, "26信管班群", "12345@chatroom", 0) is None)


def test_builder_injection(tmp, manifest):
    import build_notice_board as builder
    builder.WECHAT_MEDIA_MANIFEST = tmp / "wechat-media.json"
    builder._WECHAT_MEDIA = None
    key = list(manifest["items"].keys())
    file_key = next(k for k in key if manifest["items"][k]["kind"] == "file")
    img_key = next(k for k in key if manifest["items"][k]["kind"] == "img")
    groups = [{
        "id": "g_test_wx_attach", "cat": "教务", "title": "军训服装通知（微信测试）",
        "summary": "微信通知附件链路测试", "aiSummary": "微信通知附件链路测试",
        "group": "26信管班群", "source": "微信群 · 26信管班群",
        "items": [
            {"kind": "text", "label": "通知", "time": "11-06 12:00", "text": "军训服装通知，附件如下"},
            {"kind": "file", "label": "附件", "time": "11-06 12:00", "name": manifest["items"][file_key]["fileName"],
             "mediaKey": file_key, "note": "微信群文件"},
            {"kind": "img", "label": "图片", "time": "11-06 12:00", "mediaKey": img_key,
             "caption": "微信群图片", "note": "微信群图片"},
        ],
    }]
    builder.apply_wechat_media_items(groups)
    items = {it["kind"]: it for it in groups[0]["items"] if it.get("kind") in ("file", "img")}
    check("builder: 微信文件注入 data URI", str(items["file"].get("url", "")).startswith("data:"),
          str(items["file"].get("url"))[:60])
    check("builder: 微信图片无字节标待获取", items["img"].get("pending") is True
          and not items["img"].get("src"), items["img"])


def test_template_render(tmp, manifest):
    """用 builder.main() 生成临时 demo（注入合成微信附件通知），headless 断言卡片可见。"""
    import build_notice_board as builder
    builder.WECHAT_MEDIA_MANIFEST = tmp / "wechat-media.json"
    builder._WECHAT_MEDIA = None
    key = list(manifest["items"].keys())
    file_key = next(k for k in key if manifest["items"][k]["kind"] == "file")
    img_key = next(k for k in key if manifest["items"][k]["kind"] == "img")
    synthetic = {
        "id": "g_test_wx_attach", "cat": "教务", "title": "军训服装通知（微信附件测试）",
        "summary": "微信群通知附件链路测试：文件可下载、图片待获取", "aiSummary": "微信群通知附件链路测试",
        "aiPoints": ["文件附件", "图片待获取"],
        "group": "26信管班群", "source": "微信群 · 26信管班群",
        "deadline": None, "actionable": True, "aiTriage": True,
        "items": [
            {"kind": "text", "label": "通知", "time": "11-06 12:00", "from": "陈玉霞",
             "text": "军训服装通知，附件如下"},
            {"kind": "file", "label": "附件", "time": "11-06 12:00", "from": "陈玉霞",
             "name": manifest["items"][file_key]["fileName"], "mediaKey": file_key, "note": "微信群文件"},
            {"kind": "img", "label": "图片", "time": "11-06 12:00", "from": "陈玉霞",
             "mediaKey": img_key, "caption": "微信群图片", "note": "微信群图片"},
        ],
    }
    builder.load_ai_triage_notices = lambda: [synthetic]
    builder.OUT = tmp / "demo.html"
    builder.BOARD_DATA = tmp / "board-data.json"
    builder.main()
    html = (tmp / "demo.html").read_text(encoding="utf-8")
    check("模板生成成功（含合成微信附件通知）", "g_test_wx_attach" in html and len(html) > 100000,
          len(html))
    # headless 渲染断言
    probe = """<script>(function(){
      var cards=document.querySelectorAll('#list .gcard');
      var t=document.getElementById('card-g_test_wx_attach');
      var out={cards:cards.length, found:!!t};
      if(t){
        out.links=t.querySelectorAll('.linkrow').length;
        out.imgs=t.querySelectorAll('.imgrow').length;
        out.download=t.querySelectorAll('.linkrow a[download]').length;
        out.dataUri=t.innerHTML.indexOf('data:application/msword')>=0||t.innerHTML.indexOf('data:')>=0;
        out.missBadge=t.querySelectorAll('.imgrow.missing .missbadge').length;
        out.text=t.textContent.slice(0,200);
      }
      var pre=document.createElement('pre');pre.id='__probe';pre.textContent=JSON.stringify(out);
      document.body.appendChild(pre);})();</script>"""
    probe_file = tmp / "probe.html"
    probe_file.write_text(html.replace("</body>", probe + "</body>", 1), encoding="utf-8")
    cmd = [str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           "--virtual-time-budget=4000", "--dump-dom",
           "--user-data-dir=" + str(tmp / "edge"), probe_file.as_uri()]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    dom = proc.stdout.decode("utf-8", "replace")
    (tmp / "dom.html").write_text(dom, encoding="utf-8")
    m = re.search(r'<pre id="__probe">(.*?)</pre>', dom, re.S)
    out = {}
    if m:
        raw = m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        out = json.loads(raw)
    print("  template probe:", json.dumps({k: out.get(k) for k in ("cards", "found", "links", "imgs",
                                                                   "download", "dataUri", "missBadge")},
                                          ensure_ascii=False))
    check("模板: 微信附件通知卡片渲染", out.get("found") is True)
    check("模板: 文件附件有下载链接 + data URI", out.get("download", 0) >= 1 and out.get("dataUri") is True,
          out.get("download"))
    check("模板: 图片附件显示「待获取」", out.get("missBadge", 0) >= 1, out.get("missBadge"))
    # 截图留证
    shot = tmp / "wechat_attach.png"
    subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run",
                    "--no-default-browser-check", "--hide-scrollbars", "--virtual-time-budget=4000",
                    "--user-data-dir=" + str(tmp / "edge2"), "--window-size=1280,900",
                    "--screenshot=" + str(shot), probe_file.as_uri()], capture_output=True, timeout=120)
    if shot.exists():
        import shutil
        keep = Path(r"C:\briefdesk\data\_v2_template_check")
        keep.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shot, keep / "wechat_attach.png")
        print("  screenshot ->", keep / "wechat_attach.png")


def main():
    if not REAL_WX_FILE.exists():
        print("WARN: real WeChat plaintext sample missing:", REAL_WX_FILE)
    with tempfile.TemporaryDirectory(prefix="v2wx_") as d:
        tmp = Path(d)
        manifest = test_wechat_media(tmp)
        test_ai_triage_structures(manifest)
        test_builder_injection(tmp, manifest)
        test_template_render(tmp, manifest)
    print("\n== %d FAILED ==" % len(FAILED) if FAILED else "\n== ALL WECHAT ATTACH TESTS PASS ==")
    for f in FAILED:
        print(" -", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
