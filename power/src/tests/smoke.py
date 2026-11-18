# -*- coding: utf-8 -*-
"""离线 smoke 测试：不联网、不登录、不推送、不需要真实账号。

覆盖：
  1) 两个脚本的 --help / status / install 能跑（子进程）
  2) config 校验：缺文件 / 坏 JSON / 示例占位符 / 就绪配置
  3) cloudpay 网关客户端：请求信封与 Lead 实测格式一致、项目/房间树/剩余量解析、
     按名称选项目、max_calls 保护（全部用假网关，不发网络请求）
  4) push 消息构造：HTML→文本、企业微信 4096 字节截断、邮件头、渠道选择、
     未配置渠道不报错、单渠道失败隔离（monkeypatch _execute，不发网络请求）
  5) util：掩码 / scrub / 单实例锁 / 配置校验 / 私密 JSON 写读 + 权限收紧
  6) 台账：report --dry 打印周报但不推送、status 读台账（子进程 + 临时 DB）

跑法： python tests/smoke.py
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
MONITOR = os.path.join(ROOT, "electricity_monitor.py")
LOGIN = os.path.join(ROOT, "wanxiao_login.py")
EXAMPLE_CFG = os.path.join(ROOT, "config.example.json")
sys.path.insert(0, ROOT)

import cloudpay  # noqa: E402
import dashboard  # noqa: E402
import push      # noqa: E402
import util      # noqa: E402

TMP = tempfile.mkdtemp(prefix="pcp-smoke-")
FAILS = []
CHECKS = [0]

FAKE_IDSERIAL = "20260000001"
FAKE_TOKEN = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FAKE_DEVICE = "11111111-2222-3333-4444-555555555555"
FAKE_PASSWORD = "SmokeTestPassword!42"

READY_CFG = {
    "backend": "cloudpay",
    "schoolcode": "769",
    "idserial": FAKE_IDSERIAL,
    "payproid": "2122",
    "channelno": "30",
    "rooms": [
        {"label": "13号楼324", "roomverify": "1-13---324", "occupant": "测试同学"},
        {"label": "23号楼B座423", "roomverify": "4-23B---423"},
    ],
    "default_room": "13号楼324",
    "room": {"roomverify": "", "label": ""},
    "payPro": {"electric": {"name": "用电支出", "businesstype": 2}},
    "threshold_low": 10,
    "snapshot_low_threshold": 30,
    "low_alert_interval_hours": 3,
    "request_timeout": 25,
    "token_max_age": 5400,
}

FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "class_rooms.fixture.json")

HTML_SAMPLE = (
    "<div><p><b>宿舍还剩8.4度电</b></p>"
    "<table><tr><th>日期</th><th>合计</th></tr>"
    "<tr><td>09-07</td><td>24.0</td></tr></table></div>"
)

PROJECTS = [
    {"id": 2122, "flag": 2, "payproname": "旗山用电支出", "description": "上街校区缴电费"},
    {"id": 3518, "flag": 2, "payproname": "屏山用电支出", "description": "屏山教职工生活区缴电费"},
    {"id": 4498, "flag": 2, "payproname": "屏山学生用电", "description": "学生购电"},
]


def check(name, condition, detail=""):
    CHECKS[0] += 1
    if condition:
        print("[ OK ] %s" % name)
    else:
        print("[FAIL] %s%s" % (name, ("  ← %s" % detail) if detail else ""))
        FAILS.append(name)


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)


def clean_env(extra=None):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("DIANFEI_", "WANXIAO_", "CLOUDPAY_", "PUSH_",
                                  "SMTP_", "WECOM_", "SERVERCHAN_"))}
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    env.update(extra or {})
    return env


def run_cli(script, args, extra_env=None, timeout=120):
    result = subprocess.run([sys.executable, script] + list(args),
                            cwd=ROOT, capture_output=True, timeout=timeout,
                            env=clean_env(extra_env))
    out = (result.stdout or b"").decode("utf-8", "replace")
    err = (result.stderr or b"").decode("utf-8", "replace")
    return result.returncode, out, err


# ================================================================ 1) CLI ===
def test_cli():
    print("\n--- 1) CLI 冒烟（子进程） ---")
    code, out, _ = run_cli(MONITOR, ["--help"])
    check("monitor --help 退出 0", code == 0, "exit=%s" % code)
    check("monitor --help 列出 doctor", "doctor" in out)
    check("monitor --help 说明免登录", "免登录" in out)

    code, out, _ = run_cli(LOGIN, ["--help"])
    check("login --help 退出 0", code == 0, "exit=%s" % code)
    check("login --help 有用法说明", "完美校园" in out)

    missing_cfg = os.path.join(TMP, "nope", "config.json")
    env = {"DIANFEI_CONFIG": missing_cfg,
           "DIANFEI_DB": os.path.join(TMP, "status.db"),
           "WANXIAO_STATE": os.path.join(TMP, "nope", "wanxiao_state.json")}
    code, out, _ = run_cli(MONITOR, ["status"], env)
    check("monitor status 无配置也能跑", code == 0, "exit=%s" % code)
    check("monitor status 提示未就绪", "未就绪" in out)
    check("monitor status 显示推送未配置", "未配置" in out)

    code, out, _ = run_cli(LOGIN, ["status"], env)
    check("login status 无配置也能跑", code == 0, "exit=%s" % code)
    check("login status 提示配置文件不存在", "不存在" in out)

    code, out, _ = run_cli(MONITOR, ["install"], env)
    check("install 退出 0", code == 0, "exit=%s" % code)
    check("install 输出 Hourly schtasks", "PerfectCampusPower_Hourly" in out)
    check("install 输出 Weekly schtasks", "PerfectCampusPower_Weekly" in out)
    check("install 优先 pythonw", "pythonw.exe" in out)


# ========================================================== 2) 配置校验 ===
def test_config_validation():
    print("\n--- 2) config 校验（doctor --no-net） ---")
    state_path = os.path.join(TMP, "wanxiao_state.json")
    write_json(state_path, {"deviceId": FAKE_DEVICE, "token": FAKE_TOKEN,
                            "obtained_at": int(time.time()) - 600})
    db_path = os.path.join(TMP, "doctor.db")

    def doctor(config_path):
        env = {"DIANFEI_CONFIG": config_path, "DIANFEI_DB": db_path,
               "WANXIAO_STATE": state_path}
        return run_cli(MONITOR, ["doctor", "--no-net"], env)

    code, out, _ = doctor(os.path.join(TMP, "missing.json"))
    check("缺配置 doctor 退出 1", code == 1, "exit=%s" % code)
    check("缺配置 doctor 明确指出", "[FAIL] 配置文件" in out)

    bad_path = os.path.join(TMP, "bad.json")
    with open(bad_path, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    code, out, _ = doctor(bad_path)
    check("坏 JSON doctor 退出 1", code == 1, "exit=%s" % code)
    check("坏 JSON doctor 报解析失败", "解析失败" in out)

    code, out, _ = doctor(EXAMPLE_CFG)
    check("示例配置（占位符）doctor 退出 1", code == 1, "exit=%s" % code)
    check("示例配置提示填 idserial", "idserial" in out)
    check("示例配置提示填 roomverify", "room.roomverify" in out)

    ready_path = os.path.join(TMP, "config.ready.json")
    write_json(ready_path, READY_CFG)
    code, out, _ = doctor(ready_path)
    check("就绪配置 doctor 退出 0", code == 0, "exit=%s" % code)
    check("就绪配置 doctor 通过", "配置与依赖检查通过" in out)
    check("doctor 提示未配推送是警告", "[WARN] 推送渠道" in out)
    check("doctor 不打印完整学号", FAKE_IDSERIAL not in out)
    check("doctor 不打印完整 token", FAKE_TOKEN not in out)
    check("doctor 不打印完整 deviceId", FAKE_DEVICE not in out)
    check("doctor 不打印密码", FAKE_PASSWORD not in out)

    wanxiao_cfg = dict(READY_CFG)
    wanxiao_cfg.update({"backend": "wanxiao", "phone": "", "password": ""})
    path = os.path.join(TMP, "config.wanxiao.json")
    write_json(path, wanxiao_cfg)
    code, out, _ = doctor(path)
    check("wanxiao 后端缺账密 doctor 退出 1", code == 1, "exit=%s" % code)
    check("wanxiao 后端提示手机号", "phone" in out and "密码" in out)

    return ready_path, state_path, db_path


# ========================================================= 3) cloudpay ===
class FakeGateway:
    """假网关：记录调用并按 method/bizcontent 返回固定 businessData。"""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def call(self, method, bizcontent, source_id=2):
        self.calls.append({"method": method, "bizcontent": bizcontent,
                           "source_id": source_id})
        return self.handler(method, bizcontent)


def tree_handler(method, bizcontent):
    if method == cloudpay.METHOD_PROJECTS:
        return PROJECTS
    if method == cloudpay.METHOD_ROOM_LEVEL:
        optype = str(bizcontent.get("optype"))
        buildid = str(bizcontent.get("buildid"))
        if optype == "1":
            return [{"id": "1", "name": "旗山校区学生公寓"}]
        if optype == "2":
            return [{"id": "11", "name": "11号楼"}, {"id": "12", "name": "12号楼"}]
        if optype == "3":
            return [{"id": "101", "name": "%s号楼1层" % buildid}]
        if optype == "4":
            return [{"id": "1-11--101-616", "name": "616"}]
    return []


def test_cloudpay():
    print("\n--- 3) cloudpay 网关客户端（假网关，离线） ---")
    cfg = {"schoolcode": "769", "idserial": FAKE_IDSERIAL, "payproid": "2122",
           "payPro": {"electric": {"businessType": 2, "businesstype": 2}}}

    gateway = FakeGateway(tree_handler)
    projects = cloudpay.list_projects(cfg, gw=gateway)
    check("projects 解析出 3 个项目", len(projects) == 3, repr(projects))
    check("projects 第一个是 2122", str(projects[0].get("id")) == "2122")
    call = gateway.calls[0]
    check("projects 用 smallProgramPayPro", call["method"] == "smallProgramPayPro")
    check("projects bizcontent 精确匹配实测",
          call["bizcontent"] == {"schoolcode": "769",
                                 "idserial": FAKE_IDSERIAL,
                                 "channelno": "30"},
          repr(call["bizcontent"]))

    preset = cloudpay.resolve_payproid({"payproid": "2122", "schoolcode": "769",
                                        "idserial": FAKE_IDSERIAL},
                                       gw=FakeGateway(lambda *_: (_ for _ in ()).throw(
                                           AssertionError("不应调用网关"))))
    check("显式 payproid 不发请求", preset == "2122")

    auto = cloudpay.resolve_payproid(
        {"schoolcode": "769", "idserial": FAKE_IDSERIAL,
         "payPro": {"electric": {"name": "旗山用电支出"}}},
        gw=FakeGateway(tree_handler))
    check("按项目名精确匹配 2122", auto == "2122", auto)

    ambiguous_raised = False
    try:
        cloudpay.resolve_payproid(
            {"schoolcode": "769", "idserial": FAKE_IDSERIAL,
             "payPro": {"electric": {"name": "用电支出"}}},
            gw=FakeGateway(tree_handler))
    except cloudpay.CloudPayError:
        ambiguous_raised = True
    check("多个候选项目时要求显式填 payproid", ambiguous_raised)

    gateway = FakeGateway(tree_handler)
    hits, calls = cloudpay.search_rooms(cfg, "2122", building="11", room="616",
                                        gw=gateway)
    check("房间树找到 1 个候选", len(hits) == 1, repr(hits))
    check("roomverify 正确", hits and hits[0]["roomverify"] == "1-11--101-616",
          repr(hits[:1]))
    check("房间树下钻 4 次请求", calls == 4, "calls=%s" % calls)
    room_calls = [c for c in gateway.calls if c["method"] == cloudpay.METHOD_ROOM_LEVEL]
    check("房间树方法名是 samllProgramGetRoom",
          room_calls and room_calls[0]["method"] == "samllProgramGetRoom")
    check("房间树 bizcontent 带 idserial/businesstype/schoolno",
          all(k in room_calls[0]["bizcontent"]
              for k in ("idserial", "businesstype", "schoolno", "optype")))

    gateway = FakeGateway(tree_handler)
    hits, calls = cloudpay.search_rooms(cfg, "2122", building="99", gw=gateway)
    check("不匹配楼栋返回 0 候选", hits == [])
    check("不匹配楼栋只请求校区+楼栋", calls == 2, "calls=%s" % calls)

    guarded = False
    try:
        cloudpay.search_rooms(cfg, "2122", max_calls=2, gw=FakeGateway(tree_handler))
    except cloudpay.CloudPayError:
        guarded = True
    check("max_calls 保护生效", guarded)

    state_cfg = dict(cfg)
    state_cfg["room"] = {"roomverify": "1-11--101-616"}

    def state_handler(method, bizcontent):
        assert method == cloudpay.METHOD_ROOM_STATE
        assert bizcontent == {"payproid": "2122", "schoolcode": "769",
                              "roomverify": "1-11--101-616",
                              "businesstype": "2"}
        return {"quantity": "42.5", "quantityunit": "度", "description": "616"}

    kwh, unit, desc = cloudpay.read_kwh(state_cfg, gw=FakeGateway(state_handler))
    check("读剩余量 42.5 度", (kwh, unit, desc) == (42.5, "度", "616"), repr((kwh, unit, desc)))

    def broken_state(method, bizcontent):
        return {"returncode": "100"}

    raised = False
    try:
        cloudpay.read_kwh(state_cfg, gw=FakeGateway(broken_state))
    except cloudpay.CloudPayError:
        raised = True
    check("缺 quantity 时报错而不是瞎猜", raised)

    # 请求信封与 Lead 实测格式逐字段比对
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self.status = 200

        def read(self, amount=None):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    class FakeOpener:
        def __init__(self, payload):
            self.payload = payload
            self.requests = []

        def open(self, request, timeout=None):
            self.requests.append(request)
            return FakeResponse(self.payload)

    opener = FakeOpener(json.dumps({"returncode": "SUCCESS",
                                    "businessData": [{"id": 2122}]}).encode("utf-8"))
    client = cloudpay.Gateway(opener=opener)
    data = client.call("smallProgramPayPro", {"schoolcode": "769"})
    request = opener.requests[0]
    envelope = json.loads(request.data.decode("utf-8"))
    check("网关响应解出 businessData", data == [{"id": 2122}])
    check("信封 method 正确", envelope.get("method") == "smallProgramPayPro")
    check("信封 sourceId=2", envelope.get("sourceId") == 2)
    check("信封 bizcontent 是 JSON 字符串",
          isinstance(envelope.get("bizcontent"), str)
          and json.loads(envelope["bizcontent"]) == {"schoolcode": "769"})
    check("信封 timestamp 格式正确",
          bool(re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                        str(envelope.get("timestamp")))))
    check("请求头带 Origin/Referer",
          request.get_header("Origin") == cloudpay.ORIGIN
          and request.get_header("Referer") == cloudpay.HOMEPAGE,
          "%r %r" % (request.get_header("Origin"), request.get_header("Referer")))

    bad_opener = FakeOpener(json.dumps({"returncode": "FAIL",
                                        "returnmsg": "参数错误"}).encode("utf-8"))
    raised = False
    try:
        cloudpay.Gateway(opener=bad_opener).call("x", {})
    except cloudpay.CloudPayError as exc:
        raised = "参数错误" in str(exc)
    check("网关 returncode!=SUCCESS 时报错", raised)

    missing_opener = FakeOpener(json.dumps({"returncode": "SUCCESS"}).encode("utf-8"))
    raised = False
    try:
        cloudpay.Gateway(opener=missing_opener).call("x", {})
    except cloudpay.CloudPayError:
        raised = True
    check("网关缺 businessData 时报错", raised)


# ============================================================== 4) push ===
def test_push():
    print("\n--- 4) push 消息构造 / 渠道（离线） ---")
    text = push.html_to_text(HTML_SAMPLE)
    check("HTML→文本去掉标签", "<" not in text)
    check("HTML→文本保留表格文字", "日期" in text and "24.0" in text, repr(text))
    check("message_text 标题在前",
          push.message_text("电费不足", HTML_SAMPLE).startswith("电费不足"))

    huge_html = "<p>" + "度" * 5000 + "</p>"
    wecom_text = push.wecom_content("标题", huge_html)
    check("企微内容 ≤ 4096 字节", len(wecom_text.encode("utf-8")) <= 4096,
          "%d bytes" % len(wecom_text.encode("utf-8")))
    check("企微内容带截断标记", "截断" in wecom_text)

    email_cfg = {"push": {"email": {"user": "smoke@qq.com",
                                    "password": "authcode-not-real",
                                    "to": ["smoke@qq.com"],
                                    "from_name": "电费监控"}}}
    message, from_addr, to_addrs = push.email_message("电费不足 8.4度", HTML_SAMPLE, email_cfg)
    check("邮件收件人正确", to_addrs == ["smoke@qq.com"] and from_addr == "smoke@qq.com",
          repr((from_addr, to_addrs)))
    from email.header import decode_header
    subject = "".join(part.decode(enc or "utf-8") if isinstance(part, bytes) else part
                      for part, enc in decode_header(message["Subject"]))
    check("邮件中文标题正确", "电费不足" in subject, subject)

    check("空配置没有渠道", push.resolve_channels({}) == [])
    pp_cfg = {"push": {"pushplus": {"token": "0123456789abcdef0123456789abcdef"}}}
    check("pushplus 自动识别", push.resolve_channels(pp_cfg) == ["pushplus"])
    legacy_cfg = {"pushplus_token": "0123456789abcdef0123456789abcdef"}
    check("兼容顶层 pushplus_token", push.resolve_channels(legacy_cfg) == ["pushplus"])
    wecom_cfg = {"push": {"channels": ["wecom"], "wecom": {
        "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=smoke-key"}}}
    check("显式 channels 生效", push.resolve_channels(wecom_cfg) == ["wecom"])
    incomplete = {"push": {"channels": ["email"], "email": {"user": "smoke@qq.com"}}}
    check("点名但没配好=不启用", push.resolve_channels(incomplete) == [])
    check("缺配渠道会提示", push.missing_channels(incomplete) == ["email"])

    request = push.build_request("pushplus", "标题", HTML_SAMPLE, pp_cfg)
    body = json.loads(request["body"].decode("utf-8"))
    check("pushplus 请求体正确",
          body.get("template") == "html" and body.get("token")
          and body.get("title") == "标题" and request["url"] == push.PUSHPLUS_API)

    request = push.build_request("wecom", "标题", huge_html, wecom_cfg)
    body = json.loads(request["body"].decode("utf-8"))
    check("企业微信请求体是 markdown",
          body.get("msgtype") == "markdown"
          and len(body["markdown"]["content"].encode("utf-8")) <= 4096)
    check("企业微信 endpoint 带 key", "key=smoke-key" in request["url"])

    request = push.build_request("email", "标题", HTML_SAMPLE, email_cfg)
    check("邮件请求走 SMTP", request["kind"] == "smtp"
          and request["host"] == "smtp.qq.com" and request["port"] == 465)

    results = push.send("标题", HTML_SAMPLE, cfg={})
    check("未配置渠道不报错", results and results[0]["channel"] == "none"
          and results[0]["ok"] is True, repr(results))

    two_cfg = {"push": {"channels": ["pushplus", "webhook"],
                        "pushplus": {"token": "0123456789abcdef0123456789abcdef"},
                        "webhook": {"url": "https://example.invalid/hook"}}}
    original_execute = push._execute
    executed = []

    def fake_execute(request):
        executed.append(request["channel"])
        if request["channel"] == "pushplus":
            raise RuntimeError("smoke simulated failure")
        return "smoke ok"

    push._execute = fake_execute
    try:
        results = push.send("标题", HTML_SAMPLE, cfg=two_cfg)
    finally:
        push._execute = original_execute
    check("单渠道失败不影响其它渠道",
          len(results) == 2 and any(item["ok"] for item in results)
          and any(not item["ok"] for item in results), repr(results))
    check("失败详情已脱敏", all("key=smoke-key" not in item["detail"]
                                for item in results))


# ============================================================== 5) util ===
def test_util():
    print("\n--- 5) util 工具（离线） ---")
    check("掩码 token 不等于原文",
          util.mask_secret(FAKE_TOKEN) != FAKE_TOKEN
          and "******" in util.mask_secret(FAKE_TOKEN))
    check("掩码 deviceId 不泄露全文",
          util.mask_secret(FAKE_DEVICE) != FAKE_DEVICE
          and FAKE_DEVICE not in util.mask_secret(FAKE_DEVICE))
    check("手机号掩码", util.mask_phone("12345678901") == "123****8901")
    check("scrub 掩 webhook key", "key=***" in util.scrub("url?key=abcdef&x=1"))
    check("scrub 掩 Server酱 sendkey",
          "SCT123abc" not in util.scrub("https://sctapi.ftqq.com/SCT123abc.send"))
    check("webhook URL 掩码只留 host",
          util.mask_url("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x")
          == "https://qyapi.weixin.qq.com/***")

    check("占位符识别：空", util.is_placeholder_text(""))
    check("占位符识别：中文占位", util.is_placeholder_text("你的学号"))
    check("占位符识别：真实值", not util.is_placeholder_text("2122"))

    check("解析 roomverify 1-13---324",
          util.parse_roomverify("1-13---324")
          == {"areaid": "1", "building": "13", "room": "324"})
    check("解析 roomverify 4-23B---423",
          util.parse_roomverify("4-23B---423")
          == {"areaid": "4", "building": "23B", "room": "423"})
    check("解析非法 roomverify 返回 None",
          util.parse_roomverify("101-07--112-308") is None)

    check("规范名 1-13---324",
          util.canonical_room("1-13---324")
          == {"building": "13号楼", "room": "324", "label": "13号楼324"})
    check("规范名 4-23B---423",
          util.canonical_room("4-23B---423")
          == {"building": "23号楼B座", "room": "423", "label": "23号楼B座423"})
    check("规范名非标准格式返回 None", util.canonical_room("abc") is None)

    rooms_cfg = {"rooms": [
        {"label": "13号楼324", "roomverify": "1-13---324", "occupant": "测试同学"},
        # 故意留一个旧 label，输出应统一成规范名
        {"label": "23B-423", "roomverify": "4-23B---423"},
    ], "default_room": "23B-423"}      # 旧 default_room 也要能匹配
    normalized = util.cfg_rooms(rooms_cfg)
    check("rooms 规范化出规范名 building/room",
          normalized[0]["building"] == "13号楼"
          and normalized[0]["room"] == "324"
          and normalized[1]["label"] == "23号楼B座423"
          and normalized[1]["building"] == "23号楼B座",
          repr(normalized))
    check("旧 label 仍能被 default_room 匹配",
          (util.cfg_active_room(rooms_cfg) or {}).get("roomverify") == "4-23B---423")
    sorted_rooms = util.cfg_rooms({"rooms": [
        {"roomverify": "4-23B---425"}, {"roomverify": "1-16---306"},
        {"roomverify": "1-13---324"}, {"roomverify": "4-23A---330"}]})
    check("房间按楼号自然排序",
          [room["label"] for room in sorted_rooms]
          == ["13号楼324", "16号楼306", "23号楼A座330", "23号楼B座425"],
          repr([room["label"] for room in sorted_rooms]))
    check("没有房间时 active 为 None", util.cfg_active_room({}) is None)

    dash_payload = dashboard.build_payload({"rooms": [
        {"label": "A", "roomverify": "1-13---324", "quantity": 5,
         "occupant": "测试同学"}]})
    check("dashboard 白名单剔除 occupant 并规范化 label",
          "occupant" not in dash_payload["rooms"][0]
          and dash_payload["rooms"][0]["label"] == "13号楼324"
          and "测试同学" not in json.dumps(dash_payload, ensure_ascii=False))
    check("dashboard 按楼栋分组顺序",
          [room["label"] for room in dashboard.build_payload({"rooms": [
              {"roomverify": "4-23B---423"}, {"roomverify": "1-16---305"},
              {"roomverify": "1-13---324"},
              {"roomverify": "4-23A---321"}]})["rooms"]]
          == ["13号楼324", "16号楼305", "23号楼A座321", "23号楼B座423"])
    check("dashboard 空快照也能渲染",
          "<!DOCTYPE html>" in dashboard.render({}))

    lock_path = os.path.join(TMP, "single.lock")
    first = util.FileLock(lock_path)
    check("单实例锁第一次获取", first.acquire() is True)
    second = util.FileLock(lock_path)
    check("单实例锁第二次被拒", second.acquire() is False)
    first.release()
    third = util.FileLock(lock_path)
    check("释放后可再次获取", third.acquire() is True)
    third.release()

    private_path = os.path.join(TMP, "private.json")
    util.write_private_json(private_path, {"k": "v"})
    loaded, error = util.load_json(private_path)
    check("私密 JSON 原子写读", error is None and loaded == {"k": "v"},
          "%r %r" % (loaded, error))
    check("权限收紧不抛异常", isinstance(util.harden_permissions(private_path), str))

    with open(EXAMPLE_CFG, encoding="utf-8") as handle:
        example = json.load(handle)
    fails = [item for item in util.validate_config(example) if item["level"] == "fail"]
    fields = {item["field"] for item in fails}
    check("示例配置标记 idserial 待填", "idserial" in fields)
    check("示例配置标记 roomverify 待填", "room.roomverify" in fields)
    ready = [item for item in util.validate_config(READY_CFG) if item["level"] == "fail"]
    check("就绪配置无 FAIL", ready == [], repr(ready))
    wanxiao_fails = {item["field"] for item in util.validate_config(
        {"backend": "wanxiao", "schoolcode": "769",
         "room": {"roomverify": "1-11--101-616"}}) if item["level"] == "fail"}
    check("wanxiao 后端缺账密标记 phone/password",
          "phone" in wanxiao_fails and "password" in wanxiao_fails)
    bad_backend = [item for item in util.validate_config(
        {"backend": "nope", "schoolcode": "769"}) if item["field"] == "backend"]
    check("非法 backend 被拦", bad_backend and bad_backend[0]["level"] == "fail")


# ==================================================== 6) 台账 / report ===
def seed_ledger(db_path):
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE IF NOT EXISTS samples("
                       "ts INTEGER PRIMARY KEY, kwh REAL, unit TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS events("
                       "ts INTEGER PRIMARY KEY, kind TEXT, detail TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS meta("
                       "k TEXT PRIMARY KEY, v TEXT)")
    now = int(time.time())
    start = now - 9 * 86400
    for hour in range(9 * 24 + 1):
        connection.execute("INSERT OR REPLACE INTO samples(ts,kwh,unit) VALUES(?,?,?)",
                           (start + hour * 3600, 100.0 - hour * 0.4, "度"))
    connection.execute("INSERT OR REPLACE INTO events(ts,kind,detail) VALUES(?,?,?)",
                       (now - 3600, "recharge", "+20.0 度（测试）"))
    connection.commit()
    connection.close()


def test_ledger(ready_config):
    print("\n--- 6) 台账 / report --dry（子进程，不联网） ---")
    db_path = os.path.join(TMP, "ledger.db")
    seed_ledger(db_path)
    state_path = os.path.join(TMP, "wanxiao_state.json")
    env = {"DIANFEI_CONFIG": ready_config, "DIANFEI_DB": db_path,
           "WANXIAO_STATE": state_path}

    code, out, err = run_cli(MONITOR, ["status"], env)
    check("status 读台账退出 0", code == 0, "exit=%s err=%s" % (code, err[:200]))
    check("status 显示样本数", "样本数" in out)

    code, out, err = run_cli(MONITOR, ["report", "--dry", "--force"], env)
    check("report --dry 退出 0", code == 0, "exit=%s err=%s" % (code, err[:200]))
    check("report --dry 输出周报", "本周用电" in out and "时段合计" in out, out[:300])
    check("report --dry 只预览不真发",
          "[推送]" in out and "未配置，仅写日志" in out and " dry-run" not in out,
          out[:300])

    code, out, err = run_cli(MONITOR, ["secure"], env)
    check("secure 退出 0", code == 0, "exit=%s" % code)
    check("secure 输出收紧结果", "收紧" in out)


def test_retry_and_batch():
    print("\n--- 3b) 重试退避 / 批量查询（离线） ---")
    import urllib.error

    class Resp:
        def __init__(self, payload):
            self.payload = payload
            self.status = 200

        def read(self, amount=None):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    class SeqOpener:
        def __init__(self, actions):
            self.actions = list(actions)
            self.calls = 0

        def open(self, request, timeout=None):
            self.calls += 1
            action = self.actions.pop(0) if self.actions \
                else urllib.error.URLError("no more scripted responses")
            if isinstance(action, Exception):
                raise action
            return Resp(json.dumps(action).encode("utf-8"))

    ok_payload = {"returncode": "SUCCESS", "businessData": [{"id": 2122}]}
    sleeps, notes = [], []
    opener = SeqOpener([urllib.error.URLError("timeout"),
                        urllib.error.URLError("timeout"), ok_payload])
    client = cloudpay.Gateway(opener=opener, sleeper=sleeps.append,
                              notify=notes.append)
    data = client.call("smallProgramPayPro", {"schoolcode": "769"})
    check("网络错自动重试并成功", data == [{"id": 2122}] and opener.calls == 3)
    check("退避等待 3s/6s", sleeps == [3, 6], repr(sleeps))
    check("重试有日志提示", len(notes) == 2 and "重试" in notes[0])

    sleeps = []
    opener = SeqOpener([urllib.error.URLError("always")])
    client = cloudpay.Gateway(opener=opener, sleeper=sleeps.append)
    raised = False
    try:
        client.call("m", {})
    except cloudpay.CloudPayError as exc:
        raised = "网关连不上" in str(exc)
    check("重试 3 次后放弃", raised and opener.calls == 4 and sleeps == [3, 6, 12],
          "calls=%s sleeps=%s" % (opener.calls, sleeps))

    sleeps = []
    http405 = urllib.error.HTTPError("url", 405, "Method Not Allowed", {}, None)
    opener = SeqOpener([http405] * 4)
    client = cloudpay.Gateway(opener=opener, sleeper=sleeps.append)
    raised = False
    try:
        client.call("m", {})
    except cloudpay.CloudPayError as exc:
        raised = "WAF" in str(exc) or "限流" in str(exc)
    check("HTTP 405 重试耗尽后提示 WAF", raised)
    check("HTTP 405 也按 3/6/12 退避", sleeps == [3, 6, 12], repr(sleeps))

    sleeps = []
    http400 = urllib.error.HTTPError("url", 400, "Bad Request", {}, None)
    opener = SeqOpener([http400])
    client = cloudpay.Gateway(opener=opener, sleeper=sleeps.append)
    raised = False
    try:
        client.call("m", {})
    except cloudpay.CloudPayError:
        raised = True
    check("HTTP 400 不重试", raised and opener.calls == 1 and sleeps == [])

    sleeps = []
    busy = {"returncode": "9004", "returnmsg": "请求过于频繁，请稍后重试"}
    opener = SeqOpener([busy] * 4)
    client = cloudpay.Gateway(opener=opener, sleeper=sleeps.append)
    raised = False
    try:
        client.call("m", {})
    except cloudpay.CloudPayError as exc:
        raised = "限流" in str(exc) or "WAF" in str(exc)
    check("业务码 9004/频繁请求 触发退避与 WAF 提示",
          raised and sleeps == [3, 6, 12], "sleeps=%s" % sleeps)

    fixture_gw = cloudpay.FixtureGateway(FIXTURE_PATH)
    batch = [
        {"label": "A", "roomverify": "1-13---324"},
        {"label": "B", "roomverify": "1-16---305"},
        {"label": "C", "roomverify": "9-99---999"},
    ]
    sleeps = []
    rows = cloudpay.read_many(
        {"schoolcode": "769", "idserial": FAKE_IDSERIAL, "payproid": "2122"},
        batch, payproid="2122", interval=1.1, gw=fixture_gw,
        sleeper=sleeps.append)
    check("批量查询返回 3 行", len(rows) == 3)
    check("批量查询逐房间间隔 1.1s", sleeps == [1.1, 1.1], repr(sleeps))
    check("批量查询单房间失败不中断",
          rows[0]["ok"] and rows[1]["ok"] and not rows[2]["ok"],
          repr([row["ok"] for row in rows]))
    check("批量查询读到 fixture 真实量",
          rows[0]["quantity"] == 78.97 and rows[1]["quantity"] == 22.25)


def test_fixture_cli():
    print("\n--- 6b) 免登录链路 CLI E2E（fixture，不联网） ---")
    fixture = json.load(open(FIXTURE_PATH, encoding="utf-8"))
    cfg = {
        "backend": "cloudpay",
        "schoolcode": "769",
        "idserial": FAKE_IDSERIAL,
        "payproid": "2122",
        "channelno": "30",
        "request_interval": 0,
        "rooms": [dict(room, occupant="测试同学") for room in fixture["_rooms"]],
        "default_room": "13号楼324",
        "room": {"roomverify": "", "label": ""},
        "payPro": {"electric": {"name": "用电支出", "businesstype": 2}},
        "threshold_low": 10,
        "snapshot_low_threshold": 30,
        "push": {"channels": []},
    }
    cfg_path = os.path.join(TMP, "class.config.json")
    write_json(cfg_path, cfg)
    env = {"DIANFEI_CONFIG": cfg_path,
           "DIANFEI_DB": os.path.join(TMP, "class.db"),
           "WANXIAO_STATE": os.path.join(TMP, "class_state.json")}
    json_out = os.path.join(TMP, "query.json")
    snapshot_path = os.path.join(TMP, "snapshot.json")
    html_path = os.path.join(TMP, "dashboard.html")

    code, out, err = run_cli(MONITOR, [
        "query", "--all", "--fixture", FIXTURE_PATH, "--config", cfg_path,
        "--req-interval", "0", "--json-out", json_out], env)
    check("query --all 退出 0", code == 0, "exit=%s err=%s" % (code, err[:200]))
    check("query --all 成功 17/17", "成功 17 / 17" in out, out[-200:])
    check("query 表格用规范名",
          "23号楼A座321" in out and "23号楼B座423" in out
          and "23A-321" not in out and "23B-423" not in out, out[-500:])
    query_data, error = util.load_json(json_out)
    check("query --json-out 合法 JSON",
          error is None and len(query_data.get("rooms") or []) == 17)
    check("query JSON 用规范名 label/building",
          query_data["rooms"][0]["label"] == "13号楼308"
          and query_data["rooms"][0]["building"] == "13号楼"
          and query_data["rooms"][-1]["label"] == "23号楼B座425"
          and query_data["rooms"][-1]["building"] == "23号楼B座")
    check("query JSON 不含 occupant",
          "occupant" not in json.dumps(query_data, ensure_ascii=False))

    code, out, err = run_cli(MONITOR, ["query", "--fixture", FIXTURE_PATH,
                                      "--config", cfg_path, "--req-interval", "0"], env)
    check("query 默认只查 default_room", code == 0 and "成功 1 / 1" in out,
          out[-200:])
    code, out, err = run_cli(MONITOR, ["query", "--room", "23B",
                                      "--fixture", FIXTURE_PATH,
                                      "--config", cfg_path, "--req-interval", "0"], env)
    check("query --room 关键字过滤", code == 0 and "成功 4 / 4" in out, out[-200:])

    code, out, err = run_cli(MONITOR, [
        "snapshot", "--fixture", FIXTURE_PATH, "--config", cfg_path,
        "--req-interval", "0", "--out", snapshot_path], env)
    check("snapshot 退出 0", code == 0, "exit=%s err=%s" % (code, err[:200]))
    snap, error = util.load_json(snapshot_path)
    check("snapshot 合法 JSON", error is None and isinstance(snap, dict))
    check("snapshot 字段齐全",
          all(key in snap for key in ("generated_at", "payproid",
                                      "payproname", "rooms", "low_threshold")))
    check("snapshot 17 个房间", len(snap.get("rooms") or []) == 17)
    snap_rooms = snap.get("rooms") or [{}]
    check("snapshot 房间字段齐全",
          set(snap_rooms[0]) == {"label", "building", "room", "roomverify",
                                 "quantity", "unit", "low"},
          repr(set(snap_rooms[0])))
    expected_labels = [room["label"] for room in sorted(
        (util.canonical_room(room["roomverify"]) for room in fixture["_rooms"]),
        key=util.room_sort_key)]
    check("snapshot 房间名全为规范名且按楼栋排序",
          [room["label"] for room in snap_rooms] == expected_labels,
          repr([room["label"] for room in snap_rooms[:5]]))
    check("snapshot building 规范名",
          {room["building"] for room in snap_rooms}
          == {"13号楼", "16号楼", "23号楼A座", "23号楼B座"},
          repr({room["building"] for room in snap_rooms}))
    check("snapshot 不含旧命名",
          all(re.fullmatch(r"\d+号楼(?:[A-Z]座)?\d+", room["label"])
              for room in snap_rooms)
          and all(room["label"].startswith(room["building"])
                  for room in snap_rooms))
    low_rooms = [room for room in snap_rooms if room["low"]]
    check("snapshot low 判定 <30 度", len(low_rooms) == 1
          and low_rooms[0]["roomverify"] == "1-16---305"
          and low_rooms[0]["label"] == "16号楼305",
          repr([(room["label"], room["quantity"]) for room in low_rooms]))
    snap_text = json.dumps(snap, ensure_ascii=False)
    check("snapshot 不含 occupant/姓名",
          "occupant" not in snap_text and "测试同学" not in snap_text)

    code, out, err = run_cli(MONITOR, ["dashboard", "--snapshot", snapshot_path,
                                      "--out", html_path], env)
    check("dashboard 退出 0", code == 0, "exit=%s err=%s" % (code, err[:200]))
    with open(html_path, encoding="utf-8") as handle:
        html_text = handle.read()
    check("dashboard 是单文件 HTML",
          html_text.startswith("<!DOCTYPE html>") and "<select" in html_text)
    data_match = re.search(r"const DATA = (\{.*?\});\s*\n", html_text, re.S)
    dash_data = json.loads(data_match.group(1)) if data_match else {}
    dash_labels = [room["label"] for room in dash_data.get("rooms") or []]
    check("dashboard 含全部房间（规范名）",
          "23号楼B座423" in html_text and "13号楼324" in html_text
          and "23号楼A座321" in html_text)
    check("dashboard 按楼栋分组且顺序正确",
          "optgroup" in html_text
          and "23号楼A座" in html_text and "23号楼B座" in html_text
          and dash_labels == expected_labels,
          repr(dash_labels[:5]))
    check("dashboard 无旧命名 label",
          all(re.fullmatch(r"\d+号楼(?:[A-Z]座)?\d+", label)
              for label in dash_labels))
    check("dashboard 零外部请求",
          "http://" not in html_text and "https://" not in html_text
          and "<link" not in html_text and "<script src" not in html_text)
    check("dashboard 不含 occupant/姓名",
          "occupant" not in html_text and "测试同学" not in html_text)
    check("dashboard 内联样式与脚本",
          "<style>" in html_text and "<script>" in html_text)

    code, out, err = run_cli(MONITOR, [
        "dashboard", "--snapshot", os.path.join(TMP, "no-such.json")], env)
    check("dashboard 缺 snapshot 时友好报错",
          code == 1 and "snapshot" in (out + err), (out + err)[:200])

    code, out, err = run_cli(MONITOR, ["now", "--fixture", FIXTURE_PATH,
                                      "--config", cfg_path], env)
    check("now 用 default_room 读数", code == 0 and "78.97" in out, out[:200])

    code, out, err = run_cli(MONITOR, ["doctor", "--no-net", "--config", cfg_path], env)
    check("就绪 class 配置 doctor 退出 0", code == 0,
          "exit=%s out=%s err=%s" % (code, out[-400:], err[:200]))
    check("doctor 显示 rooms 数量", "rooms 已配置 17 个房间" in out)
    check("doctor 提示 occupant 不外泄", "occupant" in out)

    code, out, err = run_cli(MONITOR, [
        "snapshot", "--fixture", os.path.join(TMP, "no-such.json"),
        "--config", cfg_path], env)
    check("fixture 不存在时报错", code == 1 and "fixture" in (out + err).lower(),
          (out + err)[:200])


def main():
    print("=" * 78)
    print("完美校园电费监控 · 离线 smoke 测试")
    print("临时目录：%s" % TMP)
    print("=" * 78)
    try:
        test_cli()
        ready_config, _state, _db = test_config_validation()
        test_cloudpay()
        test_retry_and_batch()
        test_push()
        test_util()
        test_fixture_cli()
        test_ledger(ready_config)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print("\n" + "=" * 78)
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), FAILS))
        return 1
    print("全部通过（%d 项检查）" % CHECKS[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
