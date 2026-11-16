# -*- coding: utf-8 -*-
"""宿舍电量监控（FJTCM 定制）：免登录查询 -> 本地台账 -> 低电提醒 + 周报。

主后端（默认）= 完美校园「云支付网关」免登录接口（cloudpay.py）：
  只需要 schoolcode=769 + 学号(idserial) + payproid + roomverify，
  **不需要密码 / token / deviceId / 短信**。
备用后端 = 完美校园账密登录 + CloudPayment（wanxiao_login.py，默认不启用，
  需要 cryptography，首次在新设备登录要一次短信验证码）。

! 本项目 vendor 自 https://github.com/jialiangh/campus-electricity-monitor
! （MIT © 2026 jialiangh），已做 Windows / 双后端 / 推送适配器 / doctor 等本地化
! 修改。来源与改动清单见 NOTICE。统计分析部分基本保持原实现。

CLI（run.bat / run.ps1 已封装）：
  python electricity_monitor.py doctor            # 检查 Python/依赖/配置/台账/网络（不登录、不外发个人信息）
  python electricity_monitor.py projects          # 首次配置：列出本校缴费项目，填 payproid
  python electricity_monitor.py rooms --building 13 --room 324
                                                 # 首次配置：按楼栋/房间关键字剪枝找 roomverify
  python electricity_monitor.py query             # 查默认房间剩余量（表格）
  python electricity_monitor.py query --all       # 串行查 rooms[] 全部房间，--json-out 落 JSON
  python electricity_monitor.py snapshot          # 批量查全部房间 -> 班级站用的精简 snapshot.json
  python electricity_monitor.py dashboard         # snapshot.json -> 单文件 HTML 看板 dashboard.html
  python electricity_monitor.py now               # 只查一次当前剩余电量（不写库、不推送）
  python electricity_monitor.py state             # now 的别名
  python electricity_monitor.py sample            # 采一次入库 + 低电量检查（计划任务用）
  python electricity_monitor.py report --dry      # 按周报格式打印，不真推送
  python electricity_monitor.py status            # 台账概览
  python electricity_monitor.py test              # 读一次 + 推一条部署确认消息
  python electricity_monitor.py watch             # 常驻循环（不用计划任务时）；run 是它的别名
  python electricity_monitor.py secure            # 收紧 config/state/台账 文件权限
  python electricity_monitor.py install           # 打印 Windows 计划任务命令（推荐直接跑 install_task.ps1）

所有命令都支持 `--dry`（只读、只打印，不写库、不推送）与 `--config <路径>`；
`--fixture <json>` 用本地假数据代替真实网关（离线演示/测试，绝不联网）；
调试时可用 `--backend cloudpay|wanxiao` 临时切后端。日志默认只写 stdout，
计划任务用 `--log monitor.log` 落盘（pythonw.exe 没有控制台）。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sqlite3
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import util              # noqa: E402
import push as push_mod  # noqa: E402
import dashboard         # noqa: E402

util.setup_console()

try:
    import cloudpay
    CLOUDPAY_IMPORT_ERROR = None
except Exception as _exc:        # 理论上纯标准库不会失败
    cloudpay = None
    CLOUDPAY_IMPORT_ERROR = _exc

try:
    import wanxiao_login
    WANXIAO_IMPORT_ERROR = None
except Exception as _exc:        # 没装 cryptography 时 cloudpay 后端照样能用
    wanxiao_login = None
    WANXIAO_IMPORT_ERROR = _exc

APP_VERSION = "1.0.0-fjctm"

DB_PATH = os.environ.get("DIANFEI_DB") or os.path.join(HERE, "electricity.db")
CONFIG_PATH = (os.environ.get("DIANFEI_CONFIG")
               or os.environ.get("WANXIAO_CONFIG")
               or os.path.join(HERE, "config.json"))

CFG = {}
CFG_PATH_USED = os.path.abspath(CONFIG_PATH)
CONFIG_ERROR = None

# wanxiao fallback（CloudPayment）用；与原始实现一致
CP_BASE = "https://h5cloud.17wanxiao.com:18443/CloudPayment/"
WEB_UA = ("Mozilla/5.0 (Linux; Android 12; 24031PN0DC Build/V417IR; wv) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/110.0.5481.154 "
          "Safari/537.36 Wanxiao/5.8.9 Wmxy/5.8.27")
VERSIONCODE = "10589101"
VERSIONNUM = "1050827101"

WEEKDAY_CN = "一二三四五六日"
BUCKETS = ("0-8", "8-16", "16-24")

CREATE_NO_WINDOW = 0x08000000


# --------------------------------------------------------------- 配置 -----
def load_config(path=None, required=False):
    """读 config.json；缺失/损坏时记到 CONFIG_ERROR，命令自己决定要不要强退。"""
    global CFG, CFG_PATH_USED, CONFIG_ERROR
    path = os.path.abspath(path or CONFIG_PATH)
    CFG_PATH_USED = path
    CFG = {}
    CONFIG_ERROR = None
    if not os.path.exists(path):
        CONFIG_ERROR = "文件不存在"
        if required:
            raise SystemExit(
                "找不到配置文件：%s\n先复制 config.example.json 为 config.json 并填写"
                "（只要 schoolcode/学号/payproid/roomverify，不需要密码）；见 README_zh.md" % path)
        return CFG
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except ValueError as exc:
        CONFIG_ERROR = "JSON 解析失败：%s" % exc
        if required:
            raise SystemExit("配置文件 %s 解析失败：%s" % (path, exc))
        return CFG
    except OSError as exc:
        CONFIG_ERROR = "读取失败：%s" % exc
        if required:
            raise SystemExit("读取配置文件 %s 失败：%s" % (path, exc))
        return CFG
    if not isinstance(data, dict):
        CONFIG_ERROR = "顶层必须是 JSON 对象"
        if required:
            raise SystemExit("配置文件 %s 顶层必须是 JSON 对象" % path)
        return CFG
    CFG = data
    return CFG


def backend():
    return str(CFG.get("backend") or "cloudpay").strip().lower()


def room_label():
    active = util.cfg_active_room(CFG) if CFG else None
    if active:
        return active.get("label") or "宿舍"
    room = CFG.get("room") if isinstance(CFG.get("room"), dict) else {}
    return str(room.get("label") or "").strip() or "宿舍"


def businesstype():
    proj = (CFG.get("payPro") or {}).get("electric") or {}
    return str(proj.get("businesstype") or CFG.get("businesstype") or "2")


def threshold_low():
    try:
        return float(CFG.get("threshold_low", 10))
    except (TypeError, ValueError):
        return 10.0


def low_alert_interval_seconds():
    try:
        hours = float(CFG.get("low_alert_interval_hours", 3))
    except (TypeError, ValueError):
        hours = 3.0
    return max(60, int(hours * 3600))


def config_summary():
    """status/doctor 用的一句话配置状态（不含隐私）。"""
    problems = [item for item in util.validate_config(CFG) if item["level"] == "fail"]
    if not CFG:
        return "未就绪：%s（%s）" % (CONFIG_ERROR or "配置文件缺失", CFG_PATH_USED)
    if problems:
        return "未就绪（%d 项待填；跑 doctor 看明细）" % len(problems)
    return "已就绪"


def require_config(fields=None):
    if not CFG:
        load_config(required=True)
    fails = [item for item in util.validate_config(CFG) if item["level"] == "fail"]
    if fields is not None:
        fails = [item for item in fails if item["field"] in fields]
    if fails:
        lines = ["配置还没填好（%s）：" % CFG_PATH_USED]
        lines += ["  - %s: %s" % (item["field"], item["msg"]) for item in fails]
        lines.append("按 README_zh.md 的 5 步流程填；先跑 run.bat doctor 看全部检查项。")
        raise SystemExit("\n".join(lines))


# ------------------------------------------- wanxiao fallback：CloudPayment ---
class NoPowerData(RuntimeError):
    pass


class CloudPay:
    """CloudPayment 客户端（仅 backend=wanxiao 时使用；与原始实现一致）。

    必须用真正的 CookieJar：pay.do 是先 302 到 bill/type.do 并在这一跳下发
    HttpOnly 的 SESSION，手工解析最终响应的 Set-Cookie 会把它整条丢掉。
    """

    def __init__(self, schoolcode, timeout=25):
        import http.cookiejar
        import ssl
        import urllib.request
        self.schoolcode = str(schoolcode)
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.referer = CP_BASE + "bill/type.do"
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=context))

    def _get(self, path, referer=None, json_ok=False, **params):
        import urllib.error
        import urllib.parse
        import urllib.request
        url = CP_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"User-Agent": WEB_UA,
                   "Accept": ("application/json, text/javascript, */*; q=0.01"
                              if json_ok else "*/*"),
                   "X-Requested-With": "XMLHttpRequest",
                   "Referer": referer or self.referer}
        request = urllib.request.Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 405:
                raise NoPowerData(
                    "CloudPayment 返回 405（WAF 拦截）：请求太频繁，等几分钟再试；"
                    "采样频率别超过每小时 1 次")
            try:
                return exc.read().decode("utf-8", "replace")
            except Exception:
                return ""

    def session_id(self):
        return next((cookie.value for cookie in self.jar if cookie.name == "SESSION"), None)

    def sso(self, token):
        """token 有效才会下发 CloudPayment 的 SESSION cookie。"""
        self._get("user/pay.do", CP_BASE, versionnum=VERSIONNUM,
                  customerId=self.schoolcode, systemType="Android",
                  UAinfo="wanxiao", versioncode=VERSIONCODE, token=token)
        if not self.session_id():
            raise NoPowerData("token 未被 CloudPayment 接受（SSO 未下发 SESSION）")
        return self.session_id()

    def projects(self):
        import urllib.error
        raw = self._get("bill/querySelfPayList.do", json_ok=True)
        try:
            return json.loads(raw).get("payprolist") or []
        except Exception:
            return []

    def select_project(self, proj):
        import urllib.parse
        params = dict(txcode=proj.get("txcode") or "",
                      interurl=proj.get("interurl") or "",
                      payProId=str(proj["id"]),
                      amtflag=proj.get("amtflag") or "0",
                      payamt=proj.get("payamt") or "0",
                      payproname=proj.get("payproname") or "",
                      img=proj.get("img") or "", subPayProId="")
        # 服务端从 Referer 里的 payProId 反查房间序列号 idserial，
        # 所以后面几个接口必须把这条完整 URL 当 Referer 回传。
        self.referer = (CP_BASE + "bill/selectPayProject.do?"
                        + urllib.parse.urlencode(params))
        self._get("bill/selectPayProject.do", CP_BASE + "bill/type.do", **params)

    def room_state(self, proj, roomverify):
        raw = self._get("user/getRoomState.do", json_ok=True,
                        payProId=str(proj["id"]), schoolcode=self.schoolcode,
                        businesstype=proj.get("businesstype") or "2",
                        roomverify=roomverify)
        try:
            data = json.loads(raw)
        except Exception:
            raise NoPowerData("getRoomState 返回非 JSON：%s" % raw[:120])
        if str(data.get("returncode")) != "100":
            raise NoPowerData("getRoomState：%s"
                              % (data.get("returnmsg") or raw[:120]))
        return data

    def room_level(self, proj, optype, areaid=0, buildid=0, unitid=0, levelid=0):
        """房间树一层：optype 1 校区 / 2 楼栋 / 3 楼层(单元) / 4 房间。"""
        raw = self._get("user/getRoom.do", json_ok=True,
                        payProId=str(proj["id"]), schoolcode=self.schoolcode,
                        businesstype=str(proj.get("businesstype") or "2"),
                        optype=str(optype), areaid=str(areaid),
                        buildid=str(buildid), unitid=str(unitid),
                        levelid=str(levelid))
        try:
            return json.loads(raw).get("roomlist") or []
        except Exception:
            return []

    def open_project(self, token):
        """SSO + 选中电费项目，返回 (全部项目, 选中的那个)。"""
        self.sso(token)
        plist = self.projects()
        if not plist:
            # 实测：token 无效时 CloudPayment 照样发 SESSION，但项目列表为空，
            # 所以“项目列表非空”才是 token 真的被认的唯一判据。
            raise NoPowerData("token 已失效（SSO 后项目列表为空）")
        want_name = str(((CFG.get("payPro") or {}).get("electric") or {})
                        .get("name") or "用电支出")
        proj = next((item for item in plist
                     if item.get("payproname") == want_name), None)
        if proj is None:
            proj = next((item for item in plist
                         if want_name in str(item.get("payproname") or "")), None)
        if proj is None:
            names = "、".join("%s(id=%s)" % (item.get("payproname"), item.get("id"))
                              for item in plist)
            raise NoPowerData(
                "CloudPayment 缴费项目里没有名称含 %r 的项目；现有：%s\n"
                "把 config.json 的 payPro.electric.name 改成对应名称"
                % (want_name, names))
        proj["businesstype"] = businesstype()
        self.select_project(proj)
        return plist, proj

    def read_kwh(self, token, roomverify):
        """返回 (剩余量 float, 单位, 描述)。"""
        _, proj = self.open_project(token)
        data = self.room_state(proj, roomverify)
        return float(data["quantity"]), data.get("quantityunit", "度"), data.get("description", "")


def read_once_wanxiao(token):
    active = util.cfg_active_room(CFG)
    if active is None:
        raise SystemExit("config.json 里没有可查的房间：填 room.roomverify，"
                         "或用 rooms[] + default_room")
    client = CloudPay(CFG.get("schoolcode") or "769")
    return client.read_kwh(token, active["roomverify"])


# ------------------------------------------------------------ 取数入口 -----
def _read_cloudpay(force_login=False):
    if cloudpay is None:
        raise SystemExit("cloudpay 模块导入失败：%s" % CLOUDPAY_IMPORT_ERROR)
    require_config()
    return cloudpay.read_kwh(CFG)


def _read_wanxiao(force_login=False):
    if wanxiao_login is None:
        raise SystemExit(
            "账密 fallback 不可用：导入 wanxiao_login 失败（%s）。\n"
            "cloudpay 免登录后端不需要 cryptography；要用 fallback 先 "
            "pip install -r requirements.txt" % WANXIAO_IMPORT_ERROR)
    require_config()
    wanxiao_login.set_config_path(CFG_PATH_USED)
    token = wanxiao_login.fresh_token(force=force_login)
    try:
        return read_once_wanxiao(token)
    except NoPowerData as exc:
        if force_login:
            raise
        print("[提示] %s，重新登录后重试" % exc)
        return read_once_wanxiao(wanxiao_login.fresh_token(force=True))


def get_kwh(force_login=False):
    """取剩余电量：默认走 cloudpay；配置允许时才降级到账密 fallback。"""
    if backend() == "wanxiao":
        return _read_wanxiao(force_login=force_login)
    try:
        return _read_cloudpay(force_login=force_login)
    except (cloudpay.CloudPayError if cloudpay else RuntimeError) as exc:
        if not CFG.get("wanxiao_fallback"):
            raise
        print("[提示] cloudpay 查询失败（%s），改用账密 fallback 重试" % util.scrub(str(exc)))
        return _read_wanxiao(force_login=force_login)


# ----------------------------------------------------------- 首次配置辅助 ---
def do_projects():
    """列出缴费项目 / 缴费分类，用来填 config.json 的 payproid。"""
    if backend() == "cloudpay":
        require_config(fields=("schoolcode", "idserial"))
        projects = cloudpay.list_projects(CFG)
        idserial = str(CFG.get("idserial") or "")
        print("schoolcode = %s；idserial = 已配置（%d 位学号，不显示）"
              % (CFG.get("schoolcode"), len(idserial)))
        if not projects:
            print("没有返回缴费项目：检查 schoolcode / idserial 是否正确，或网关接口已变更")
            return 1
        current = str(CFG.get("payproid") or "").strip()
        for item in projects:
            pid = str(item.get("id") or item.get("payproid") or "")
            mark = "*" if current and pid == current else " "
            print("  %s payproid=%-6s name=%-12s businesstype=%-2s %s"
                  % (mark, pid, item.get("payproname"),
                     item.get("businesstype") or businesstype(),
                     item.get("description") or ""))
        print("\n把你宿舍对应的项目 id 填进 config.json 的 \"payproid\"：")
        print("  FJTCM 旗山用电支出 = 2122；屏山学生用电 = 4498；屏山教职工 = 3518")
        return 0
    return do_projects_wanxiao()


def do_projects_wanxiao():
    require_config()
    wanxiao_login.set_config_path(CFG_PATH_USED)
    client = CloudPay(CFG.get("schoolcode") or "769")
    projects, chosen = client.open_project(wanxiao_login.fresh_token())
    print("schoolcode = %s" % client.schoolcode)
    for item in projects:
        mark = "*" if item is chosen else " "
        print("  %s payProId=%-6s name=%-10s businesstype=%-2s txcode=%s"
              % (mark, item.get("id"), item.get("payproname"),
                 item.get("businesstype"), item.get("txcode")))
    print("把要监控的那一项的 name / businesstype 填进 config.json 的 payPro.electric")
    return 0


def _keyword_hit(keyword, name, ident):
    if not keyword:
        return True
    keyword = str(keyword)
    return keyword in str(name) or keyword in str(ident)


def do_rooms(args):
    """找 roomverify：cloudpay 走网关房间树，wanxiao 走 CloudPayment 房间树。"""
    if backend() == "cloudpay":
        require_config(fields=("schoolcode", "idserial"))
        payproid = args.payproid or cloudpay.resolve_payproid(CFG)
        print("payproid = %s；按 校区→楼栋→楼层→房间 下钻（上限 %d 次请求，"
              "用 --campus/--building/--room 剪枝）" % (payproid, args.max_calls))
        hits, calls = cloudpay.search_rooms(
            CFG, payproid, campus=args.campus, building=args.building,
            room=args.room, floor=args.floor, max_calls=args.max_calls,
            progress=print)
        if not hits:
            print("\n没找到。试试放宽 --campus / --building / --room，"
                  "或先跑 projects 确认 payproid（当前 %s）" % payproid)
            return 1
        for hit in hits[:80]:
            print("  %s / %s / %s / %s  ->  %s"
                  % (hit["campus"], hit["building"], hit["floor"],
                     hit["room"], hit["roomverify"]))
        if len(hits) > 80:
            print("  …… 只显示前 80 个")
        print("\n共 %d 个候选（用了 %d 次请求）" % (len(hits), calls))
        if len(hits) == 1:
            print("\n把上面那个 roomverify 填进 config.json 的 room.roomverify，"
                  "再跑 run.bat now 验证")
        return 0
    return do_rooms_wanxiao(args)


def do_rooms_wanxiao(args):
    require_config()
    wanxiao_login.set_config_path(CFG_PATH_USED)
    client = CloudPay(CFG.get("schoolcode") or "769")
    _, proj = client.open_project(wanxiao_login.fresh_token())
    calls = 0
    hits = []
    max_calls = args.max_calls

    def bump():
        nonlocal calls
        calls += 1
        if calls > max_calls:
            raise SystemExit("请求数超过 %d，请用 --campus / --building 缩小范围"
                             % max_calls)

    for campus in client.room_level(proj, 1):
        bump()
        if not _keyword_hit(args.campus, campus.get("name"), campus.get("id")):
            continue
        for building in client.room_level(proj, 2, areaid=campus["id"]):
            bump()
            if not _keyword_hit(args.building, building.get("name"), building.get("id")):
                continue
            for floor in client.room_level(proj, 3, areaid=campus["id"],
                                           buildid=building["id"]):
                bump()
                if not _keyword_hit(args.floor, floor.get("name"), floor.get("id")):
                    continue
                for room in client.room_level(proj, 4, areaid=campus["id"],
                                              buildid=building["id"],
                                              levelid=floor["id"]):
                    bump()
                    if not _keyword_hit(args.room, room.get("name"), room.get("id")):
                        continue
                    roomverify = (room["id"] if "--" in str(room.get("id", "")) else
                                  "%s-%s--%s-%s" % (campus["id"], building["id"],
                                                    floor["id"], room["id"]))
                    hits.append("%s / %s / %s / %s  ->  %s"
                                % (campus.get("name"), building.get("name"),
                                   floor.get("name"), room.get("name"), roomverify))
    if not hits:
        print("没找到，试试放宽 --campus / --building / --room")
    for hit in hits[:80]:
        print("  " + hit)
    print("共 %d 个候选（用了 %d 次请求）" % (len(hits), calls))
    return 0


# ---------------------------------------------------- 批量查询 / 快照 / 看板 ---
def snapshot_threshold():
    try:
        return float(CFG.get("snapshot_low_threshold") or 30)
    except (TypeError, ValueError):
        return 30.0


def _row_public(row):
    """输出用的房间行：白名单字段，绝不带 occupant 等个人信息。"""
    return {
        "label": row.get("label") or row.get("roomverify"),
        "building": row.get("building") or "",
        "room": row.get("room") or "",
        "roomverify": row.get("roomverify") or "",
        "quantity": row.get("quantity"),
        "unit": row.get("unit") or "度",
        "low": (row.get("quantity") is not None
                and float(row["quantity"]) < snapshot_threshold()),
        "ok": bool(row.get("ok")),
        "error": row.get("error") or "",
    }


def _select_query_rooms(args):
    rooms = util.cfg_rooms(CFG)
    if args.all:
        return rooms
    keyword = (args.room or "").strip()
    if keyword:
        return [room for room in rooms
                if keyword in room["label"] or keyword in room["roomverify"]]
    active = util.cfg_active_room(CFG)
    return [active] if active else []


def _print_room_rows(rows):
    limit = snapshot_threshold()
    print("%-16s %-18s %10s %-3s %s" % ("房间", "roomverify", "剩余", "单位", "状态"))
    print("-" * 74)
    for row in rows:
        if row.get("ok") and row.get("quantity") is not None:
            status = "低电" if float(row["quantity"]) < limit else "正常"
            print("%-16s %-18s %10.2f %-3s %s"
                  % (row["label"], row["roomverify"], float(row["quantity"]),
                     row["unit"], status))
        else:
            print("%-16s %-18s %10s %-3s 失败：%s"
                  % (row["label"], row["roomverify"], "--", "-",
                     (row.get("error") or "")[:70]))
    print("-" * 74)


def _batch_progress(done, total, row, _notify=None):
    if row.get("ok"):
        print("  [%d/%d] %-14s %.2f %s"
              % (done, total, row["label"], float(row["quantity"]), row["unit"]))
    else:
        print("  [%d/%d] %-14s 失败：%s"
              % (done, total, row["label"], (row.get("error") or "")[:80]))


def do_query(args):
    """query [--all]：串行查一个/全部房间，表格 + 可选 --json-out。"""
    require_config()
    rooms = _select_query_rooms(args)
    if not rooms:
        raise SystemExit(
            "没有匹配的房间：在 config.json 里填 rooms[]（或 room.roomverify），"
            "或用 --room 关键字过滤；房间清单格式见 README_zh.md")
    payproid = cloudpay.resolve_payproid(CFG)
    interval = max(0.0, float(args.req_interval))
    estimate = max(0, len(rooms) - 1) * interval
    print("payproid = %s；房间 %d 个；串行查询，每请求间隔 %.1f 秒（预计 %.0f 秒）"
          % (payproid, len(rooms), interval, estimate))
    rows = cloudpay.read_many(CFG, rooms, payproid=payproid, interval=interval,
                              progress=_batch_progress)
    print()
    _print_room_rows(rows)
    ok_rows = [row for row in rows if row.get("ok")]
    low_count = sum(1 for row in ok_rows
                    if float(row["quantity"]) < snapshot_threshold())
    print("\n成功 %d / %d；低电 %d 间（阈值 %g 度）"
          % (len(ok_rows), len(rows), low_count, snapshot_threshold()))
    if args.json_out:
        path = os.path.abspath(args.json_out)
        util.write_private_json(path, {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "payproid": payproid,
            "rooms": [_row_public(row) for row in rows],
        })
        print("结果 JSON 已写入 %s" % path)
    return 0 if ok_rows else 1


def do_snapshot(args):
    """snapshot：批量查全部房间 → 给班级站用的精简 JSON（不含个人信息）。"""
    require_config()
    rooms = util.cfg_rooms(CFG)
    if not rooms:
        raise SystemExit(
            "config.json 的 rooms[] 是空的：先把班级宿舍清单填进去"
            "（格式见 README_zh.md / tests/fixtures/class_rooms.fixture.json）")
    payproid = cloudpay.resolve_payproid(CFG)
    payproname = cloudpay.payproname(CFG, payproid)
    limit = float(args.low_threshold) if args.low_threshold is not None \
        else snapshot_threshold()
    interval = max(0.0, float(args.req_interval))
    print("payproid = %s（%s）；房间 %d 个；低电阈值 %g 度；间隔 %.1f 秒"
          % (payproid, payproname, len(rooms), limit, interval))
    rows = cloudpay.read_many(CFG, rooms, payproid=payproid, interval=interval,
                              progress=_batch_progress)
    ok_rows = [row for row in rows if row.get("ok")]
    errors = [{"label": row["label"], "roomverify": row["roomverify"],
               "error": row.get("error") or ""}
              for row in rows if not row.get("ok")]
    snapshot = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "timezone": str(CFG.get("timezone") or "Asia/Shanghai"),
        "schoolcode": str(CFG.get("schoolcode") or ""),
        "payproid": payproid,
        "payproname": payproname,
        "low_threshold": limit,
        "rooms": [{
            "label": row["label"],
            "building": row["building"],
            "room": row["room"],
            "roomverify": row["roomverify"],
            "quantity": round(float(row["quantity"]), 2),
            "unit": row["unit"],
            "low": float(row["quantity"]) < limit,
        } for row in ok_rows],
    }
    if errors:
        snapshot["errors"] = errors
    low_count = sum(1 for room in snapshot["rooms"] if room["low"])
    out = os.path.abspath(args.out or os.path.join(HERE, "snapshot.json"))
    print("\n成功 %d / %d；低电 %d 间" % (len(ok_rows), len(rows), low_count))
    if args.dry:
        print("[dry] 将写入 %s；内容预览：" % out)
        print(json.dumps(snapshot, ensure_ascii=False, indent=1))
    else:
        util.write_private_json(out, snapshot)
        print("快照已写入 %s（%d 个房间，不含姓名等个人信息）"
              % (out, len(snapshot["rooms"])))
        print("可继续运行： run.bat dashboard --snapshot \"%s\"" % out)
    return 0 if ok_rows else 1


def do_dashboard(args):
    """dashboard：把 snapshot.json 生成单文件 HTML 看板（纯内联，零外部请求）。"""
    snapshot_path = os.path.abspath(
        args.snapshot or os.path.join(HERE, "snapshot.json"))
    data, error = util.load_json(snapshot_path)
    if error:
        raise SystemExit("读不到 snapshot：%s（%s）\n先跑 run.bat snapshot 生成，"
                         "再跑 run.bat dashboard" % (snapshot_path, error))
    if not isinstance(data, dict) or not (data.get("rooms") or []):
        raise SystemExit("%s 里没有房间数据；先跑 run.bat snapshot" % snapshot_path)
    html_text = dashboard.render(data)
    out = os.path.abspath(args.out or os.path.join(HERE, "dashboard.html"))
    size = len(html_text.encode("utf-8"))
    if args.dry:
        print("[dry] 将生成 %s（%d 字节）" % (out, size))
        return 0
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(html_text)
    print("看板已生成：%s（%d 字节）" % (out, size))
    print("双击用浏览器打开即可；页面纯内联，不向任何服务器发请求。")
    return 0


# --------------------------------------------------------------- 台账 -----
def db():
    connection = sqlite3.connect(DB_PATH)
    connection.execute("CREATE TABLE IF NOT EXISTS samples("
                       "ts INTEGER PRIMARY KEY, kwh REAL, unit TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS events("
                       "ts INTEGER PRIMARY KEY, kind TEXT, detail TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS meta("
                       "k TEXT PRIMARY KEY, v TEXT)")
    return connection


def meta_get(connection, key, default=None):
    row = connection.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(connection, key, value):
    connection.execute("INSERT INTO meta(k,v) VALUES(?,?) "
                       "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                       (key, str(value)))


def hourly_series(connection, start_ts, end_ts):
    """取区间内样本 + 区间起点前最后一个样本，用来算差值。"""
    return connection.execute("SELECT ts,kwh FROM samples WHERE ts<=? ORDER BY ts",
                              (end_ts,)).fetchall()


# ------------------------------------------------------------- 统计分析 ---
def bucket_of(hour):
    return 0 if hour < 8 else (1 if hour < 16 else 2)


def split_interval(t0, t1):
    """把 [t0,t1) 按 0 点 / 8 点 / 16 点切成不跨时段边界的小段。

    返回 [(YYYY-MM-DD, 时段下标, 秒数)]，用来把两次读数的差值按占比摊到
    真正发生的时段，而不是全记在采样那一刻所在的天。
    """
    out = []
    cur = t0
    while cur < t1:
        day0 = datetime.fromtimestamp(cur).replace(
            hour=0, minute=0, second=0, microsecond=0)
        b8 = day0.timestamp() + 8 * 3600
        b16 = b8 + 8 * 3600
        b24 = b16 + 8 * 3600
        nxt = b8 if cur < b8 else (b16 if cur < b16 else b24)
        out.append((day0.strftime("%Y-%m-%d"),
                    0 if cur < b8 else (1 if cur < b16 else 2),
                    min(nxt, t1) - cur))
        cur = min(nxt, t1)
    return out


def usage_breakdown(connection, start_dt, end_dt):
    """按天 + 三时段统计用电量（剩余电量下降量，充值造成的上升记 0）。"""
    rows = hourly_series(connection, 0, int(end_dt.timestamp()))
    lo = start_dt.strftime("%Y-%m-%d")
    hi = (end_dt - timedelta(seconds=1)).strftime("%Y-%m-%d")
    per_day = {}
    recharges = 0.0
    n_in_window = 0
    prev = None
    for ts, kwh in rows:
        if lo <= datetime.fromtimestamp(ts).strftime("%Y-%m-%d") <= hi:
            n_in_window += 1
        if prev is not None:
            p_ts, p_kwh = prev
            delta = p_kwh - kwh
            span = max(ts - p_ts, 1)
            segs = split_interval(p_ts, ts)
            if delta < 0:
                # 充值：读数上升不算用电，单独记一笔
                if segs and lo <= segs[-1][0] <= hi:
                    recharges += -delta
            elif delta > 0:
                for day, idx, dur in segs:
                    if lo <= day <= hi:
                        per_day.setdefault(
                            day, [0.0, 0.0, 0.0])[idx] += delta * dur / span
        prev = (ts, kwh)
    days = sorted(per_day)
    total = round(sum(sum(v) for v in per_day.values()), 2)
    return {"days": days, "per_day": per_day, "total": total,
            "recharges": round(recharges, 2),
            "n_samples": len(rows), "n_in_window": n_in_window}


def week_range(now=None):
    """刚过完的自然周：周一 00:00 ~ 下周一 00:00。"""
    now = now or datetime.now()
    this_mon = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return this_mon - timedelta(days=7), this_mon


# ---------------------------------------------------------------- 推送 -----
def push(title, content, dry=False):
    """推送到所有已配置渠道；未配置渠道时只写日志，不报错。"""
    title = str(title)
    channels = push_mod.resolve_channels(CFG)
    print("[推送] %s（渠道：%s）"
          % (title, "、".join(channels) if channels else "未配置，仅写日志"))
    if dry:
        print(push_mod.message_text(title, content))
        return {"ok": True, "dry": True, "results": []}
    results = push_mod.send(title, content, cfg=CFG)
    for item in results:
        if item["channel"] == "none":
            print("       -> 未配置推送渠道，本条消息只写日志")
        else:
            print("       -> %s %s%s"
                  % (item["channel"], "OK " if item["ok"] else "失败 ",
                     item["detail"]))
    ok = all(item["ok"] for item in results)
    if not ok:
        print("[提示] 有推送渠道失败（不影响采集；检查网络/配置后可重跑 test 验证）")
    return {"ok": ok, "results": results}


def build_weekly(connection, start_dt, end_dt):
    stats = usage_breakdown(connection, start_dt, end_dt)
    room = room_label()
    total = stats["total"]
    col_bucket = [0.0, 0.0, 0.0]
    ndays = 0
    table_rows = []
    # 按周一到周日的时间顺序逐天输出，没有样本的天显式标“无数据”
    for d in range((end_dt - start_dt).days):
        day_dt = start_dt + timedelta(days=d)
        day = day_dt.strftime("%Y-%m-%d")
        label = "%s 周%s" % (day[5:], WEEKDAY_CN[day_dt.weekday()])
        buckets = stats["per_day"].get(day)
        if buckets is None:
            table_rows.append("<tr><td>%s</td>"
                              "<td colspan='4' align='center' "
                              "style='color:#bbb'>无数据</td></tr>" % label)
            continue
        ndays += 1
        for index in range(3):
            col_bucket[index] += buckets[index]
        table_rows.append("<tr><td>%s</td><td align='right'><b>%.1f</b></td>"
                          "<td align='right'>%.1f</td><td align='right'>%.1f</td>"
                          "<td align='right'>%.1f</td></tr>"
                          % (label, sum(buckets), buckets[0], buckets[1], buckets[2]))
    table_rows.append("<tr style='background:#f2f4f7'><td><b>时段合计</b></td>"
                      "<td align='right'><b>%.1f</b></td>"
                      "<td align='right'>%.1f</td><td align='right'>%.1f</td>"
                      "<td align='right'>%.1f</td></tr>"
                      % (sum(col_bucket), col_bucket[0], col_bucket[1], col_bucket[2]))
    last = connection.execute("SELECT kwh,ts FROM samples ORDER BY ts DESC LIMIT 1").fetchone()

    span = "%s ~ %s" % (start_dt.strftime("%m-%d"),
                        (end_dt - timedelta(seconds=1)).strftime("%m-%d"))
    complete = ndays >= (end_dt - start_dt).days
    head = ("<div style='font-size:15px'>"
            "<p><b>%s %s</b>%s</p>"
            "<p>本周总用电 <b>%.1f 度</b>，日均 %.1f 度（有数据 %d 天）%s</p>"
            "<table width='100%%' cellspacing='0' cellpadding='6' "
            "style='border-collapse:collapse;font-size:14px'>"
            "<tr style='background:#f2f4f7'><th align='left'>日期</th>"
            "<th align='right'>合计(度)</th><th align='right'>0-8</th>"
            "<th align='right'>8-16</th><th align='right'>16-24</th></tr>%s</table>"
            % (room, span, "" if complete else "（数据不完整）", total,
               total / max(ndays, 1), ndays,
               "，期间充值 +%.1f 度" % stats["recharges"] if stats["recharges"] else "",
               "".join(table_rows)))
    if last:
        head += ("<p style='color:#666'>当前剩余 %.1f 度（采样于 %s）</p>"
                 % (last[0], datetime.fromtimestamp(last[1]).strftime("%m-%d %H:%M")))
    head += "</div>"
    title = "本周用电%g度" % round(total, 1)
    return title, head, stats


def build_low(kwh):
    title = "电费不足"
    content = ("<div style='font-size:16px'><b>%s还剩%g度电</b>"
               "<p style='color:#888;font-size:13px'>采样 %s</p></div>"
               % (room_label(), round(kwh, 1), datetime.now().strftime("%m-%d %H:%M")))
    return title, content


# --------------------------------------------------------------- 动作 -----
def do_now():
    kwh, unit, desc = get_kwh(force_login=True)
    print("当前剩余 %.2f %s%s" % (kwh, unit, ("（%s）" % desc) if desc else ""))
    return 0


def do_sample(connection, dry=False, verbose=True):
    kwh, unit, desc = get_kwh()
    now = int(time.time())
    prev = connection.execute(
        "SELECT kwh FROM samples ORDER BY ts DESC LIMIT 1").fetchone()
    limit = threshold_low()
    if dry:
        armed = meta_get(connection, "low_armed", "1") == "1"
        last_alert = int(meta_get(connection, "last_low_alert", "0") or 0)
        throttled = time.time() - last_alert < low_alert_interval_seconds()
        print("[dry] 读到剩余 %.2f %s%s"
              % (kwh, unit, ("（%s）" % desc) if desc else ""))
        print("[dry] 本应写入台账：ts=%d kwh=%.2f；当前最新样本=%s"
              % (now, kwh, ("%.2f" % prev[0]) if prev else "无"))
        print("[dry] 低电阈值 %.1f：%s"
              % (limit, "会推送低电提醒" if (kwh < limit and armed and not throttled)
                 else "不推送（%s）"
                 % ("电量正常" if kwh >= limit else
                    ("3 小时节流中" if throttled else "低电提醒已停发"))))
        return kwh
    if prev and kwh - prev[0] > 0.5:
        connection.execute(
            "INSERT OR REPLACE INTO events(ts,kind,detail) VALUES(?,?,?)",
            (now, "recharge", "+%.1f 度（%.1f -> %.1f）"
             % (kwh - prev[0], prev[0], kwh)))
        meta_set(connection, "low_armed", "1")
        if verbose:
            print("检测到充值 +%.1f 度，低电量提醒重新武装" % (kwh - prev[0]))
    connection.execute("INSERT OR REPLACE INTO samples(ts,kwh,unit) VALUES(?,?,?)",
                       (now, kwh, unit))
    connection.commit()
    if verbose:
        print("%s 剩余电量 %.1f%s"
              % (datetime.now().strftime("%m-%d %H:%M"), kwh, unit))
    check_low(connection, kwh, dry=dry)
    return kwh


def check_low(connection, kwh, dry=False):
    limit = threshold_low()
    if kwh >= limit:
        return
    if meta_get(connection, "low_armed", "1") != "1":
        return
    last_alert = int(meta_get(connection, "last_low_alert", "0") or 0)
    if time.time() - last_alert < low_alert_interval_seconds():
        return
    title, content = build_low(kwh)
    push(title, content, dry=dry)
    meta_set(connection, "last_low_alert", int(time.time()))
    if kwh <= 0:
        meta_set(connection, "low_armed", "0")
    connection.commit()


def do_report(connection, dry=False, force=False):
    start, end = week_range()
    stats = usage_breakdown(connection, start, end)
    # 少于 2 个样本就算不出任何差值，推出去只会是一条「本周用电0度」
    if stats["n_in_window"] < 2 and not force:
        print("本周样本不足（%d 个），跳过周报" % stats["n_in_window"])
        return None
    title, content, stats = build_weekly(connection, start, end)
    out = push(title, content, dry=dry)
    if not dry:
        meta_set(connection, "last_report", int(time.time()))
        connection.commit()
    return out


def do_test(connection, dry=False):
    """部署自测：读一次实时电量，入库，并推一条确认消息。"""
    kwh, unit, desc = get_kwh()
    if dry:
        print("[dry] 读到剩余 %.2f %s%s；不写库、不推送，仅预览消息："
              % (kwh, unit, ("（%s）" % desc) if desc else ""))
    else:
        connection.execute(
            "INSERT OR REPLACE INTO samples(ts,kwh,unit) VALUES(?,?,?)",
            (int(time.time()), kwh, unit))
        connection.commit()
    source = ("完美校园云支付网关（免登录）" if backend() == "cloudpay"
              else "完美校园账密登录 + CloudPayment")
    title = "电费监控已上线"
    content = ("<div style='font-size:16px'><b>%s 当前剩余 %g%s电</b>"
               "<p style='color:#888;font-size:13px'>采样 %s · 主机 %s</p>"
               "<p style='font-size:13px;color:#555'>数据源：%s；"
               "每小时自动采样；周一 00:05 推送上周汇总；"
               "剩余不足 %g%s 时每 %g 小时提醒一次</p></div>"
               % (room_label(), round(kwh, 1), unit,
                  datetime.now().strftime("%Y-%m-%d %H:%M"),
                  socket.gethostname(), source, threshold_low(), unit,
                  low_alert_interval_seconds() / 3600.0))
    push(title, content, dry=dry)
    print("%.2f %s（%s）%s" % (kwh, unit, desc or "无描述",
                              "已推送到已配置渠道" if push_mod.resolve_channels(CFG)
                              else "未配置推送渠道，仅写日志"))
    return 0


def do_status(connection):
    print("版本     : %s" % APP_VERSION)
    print("后端     : %s" % backend())
    print("配置文件 : %s" % CFG_PATH_USED)
    print("配置状态 : %s" % config_summary())
    if backend() == "cloudpay":
        print("payproid : %s" % (str(CFG.get("payproid") or "").strip()
                                or "（按项目名自动匹配）"))
        active = util.cfg_active_room(CFG) if CFG else None
        if active:
            print("默认房间 : %s（%s）" % (active["label"], active["roomverify"]))
        else:
            print("默认房间 : （未配置）")
        print("房间总数 : %d" % len(util.cfg_rooms(CFG)))
    print("推送     : %s" % push_mod.describe(CFG))
    print("数据库   : %s" % DB_PATH)
    count = connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    first = connection.execute("SELECT MIN(ts) FROM samples").fetchone()[0]
    last = connection.execute("SELECT kwh,ts FROM samples ORDER BY ts DESC LIMIT 1").fetchone()
    print("样本数   : %d" % count)
    if first:
        print("最早样本 : %s" % datetime.fromtimestamp(first).strftime("%Y-%m-%d %H:%M"))
    if last:
        print("最新读数 : %.1f 度  @ %s"
              % (last[0], datetime.fromtimestamp(last[1]).strftime("%Y-%m-%d %H:%M")))
    last_report = meta_get(connection, "last_report")
    last_low = meta_get(connection, "last_low_alert")
    print("上次周报 : %s" % (datetime.fromtimestamp(int(last_report)).strftime("%Y-%m-%d %H:%M")
                             if last_report else "从未"))
    print("上次低电 : %s" % (datetime.fromtimestamp(int(last_low)).strftime("%Y-%m-%d %H:%M")
                             if last_low else "从未"))
    print("低电武装 : %s" % meta_get(connection, "low_armed", "1"))
    for ts, kind, detail in connection.execute(
            "SELECT ts,kind,detail FROM events ORDER BY ts DESC LIMIT 5").fetchall():
        print("  事件 %s %-9s %s"
              % (datetime.fromtimestamp(ts).strftime("%m-%d %H:%M"), kind, detail))
    return 0


def do_run(connection, interval=3600):
    print("常驻模式：每 %d 秒采一次，周一 00:0x 出周报（Ctrl+C 退出）" % interval)
    while True:
        try:
            do_sample(connection, verbose=True)
            now = datetime.now()
            if now.weekday() == 0 and now.hour == 0 and \
                    meta_get(connection, "report_week") != now.strftime("%Y-%m-%d"):
                do_report(connection)
                meta_set(connection, "report_week", now.strftime("%Y-%m-%d"))
                connection.commit()
        except KeyboardInterrupt:
            print("\n已退出常驻模式")
            return 0
        except Exception as exc:
            print("本轮失败：%s: %s" % (type(exc).__name__, util.scrub(str(exc))))
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n已退出常驻模式")
            return 0


# --------------------------------------------------------------- doctor ---
def _tcp_check(host, port, timeout=5):
    started = time.time()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            pass
        return True, "%.0f ms" % ((time.time() - started) * 1000)
    except OSError as exc:
        return False, "连不上：%s" % exc


def do_doctor(no_net=False):
    rows = []

    def add(level, name, detail=""):
        rows.append((level, name, detail))

    # 1) 运行时
    add("ok", "Python", "%s (%d-bit) @ %s"
        % (platform.python_version(), 64 if sys.maxsize > 2 ** 32 else 32,
           sys.executable))
    if sys.version_info < (3, 8):
        add("fail", "Python 版本", "需要 Python 3.8+（当前 %s）" % platform.python_version())
    if util.is_windows():
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(pythonw):
            add("ok", "pythonw.exe", pythonw)
        else:
            add("warn", "pythonw.exe", "未找到；计划任务会闪黑框（install_task.ps1 -NoPythonw 用 python.exe）")
        add("info", "计划任务", "用 schtasks 注册（PowerShell Register-ScheduledTask 本机可能被拒）")
    else:
        add("info", "平台", "%s（主力目标 Windows；Linux 可自行用 cron）" % platform.system())

    # 2) 依赖
    if cloudpay is not None:
        add("ok", "cloudpay 模块", "已加载（免登录主后端）")
    else:
        add("fail", "cloudpay 模块", "导入失败：%s" % CLOUDPAY_IMPORT_ERROR)
    need_wanxiao = backend() == "wanxiao" or bool(CFG.get("wanxiao_fallback"))
    if wanxiao_login is None:
        add("fail" if need_wanxiao else "info", "账密 fallback",
            "未加载（%s）；cloudpay 后端不需要" % WANXIAO_IMPORT_ERROR)
    else:
        add("ok", "账密 fallback", "cryptography 可用（仅 backend=wanxiao 时才用）")

    # 3) 配置
    exists = os.path.exists(CFG_PATH_USED)
    if not exists:
        add("fail", "配置文件", "%s（不存在：复制 config.example.json 为 config.json）"
            % CFG_PATH_USED)
    else:
        add("ok", "配置文件", CFG_PATH_USED)
        cfg, error = util.load_json(CFG_PATH_USED)
        if error:
            add("fail", "配置解析", error)
        else:
            for item in util.validate_config(cfg):
                add(item["level"], item["field"], item["msg"])
            channels = push_mod.resolve_channels(cfg)
            if channels:
                add("ok", "推送渠道", "已配置：%s（test 会真发一条）" % "、".join(channels))
            else:
                add("warn", "推送渠道",
                    "未配置（只写日志，不报错）；可配 pushplus/企业微信/Server酱/webhook/QQ邮箱")
            missing = push_mod.missing_channels(cfg)
            if missing:
                add("warn", "推送渠道勾选",
                    "push.channels 里写了但没配好：%s" % "、".join(missing))

    # 4) 状态文件（账密 fallback 才有意义；仍然只显示掩码）
    if wanxiao_login is not None:
        state = wanxiao_login.load_state()
        if state.get("deviceId"):
            add("ok", "deviceId", "已绑定（%s）" % util.mask_secret(state["deviceId"]))
        else:
            add("info", "deviceId",
                "无（cloudpay 后端不需要；账密 fallback 首次要短信绑定一次）")
        if state.get("token"):
            add("ok", "token", "有缓存（%s）" % util.mask_secret(state["token"]))
        else:
            add("info", "token", "无缓存（cloudpay 后端不需要）")

    # 5) 台账
    if os.path.exists(DB_PATH):
        try:
            connection = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"),
                                         uri=True)
            try:
                count = connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
                latest = connection.execute(
                    "SELECT kwh,ts FROM samples ORDER BY ts DESC LIMIT 1").fetchone()
            finally:
                connection.close()
            if latest:
                add("ok", "台账", "%d 个样本，最新 %.1f 度 @ %s"
                    % (count, latest[0],
                       datetime.fromtimestamp(latest[1]).strftime("%m-%d %H:%M")))
            else:
                add("ok", "台账", "已创建，还没有样本（跑一次 sample 或 test）")
        except Exception as exc:
            add("warn", "台账", "打不开：%s" % exc)
    else:
        add("info", "台账", "尚未生成（跑一次 sample/test 后出现）")

    # 6) 网络（只做 TCP 连通，不发登录/个人信息）
    if no_net:
        add("info", "网络检查", "已用 --no-net 跳过")
    else:
        targets = [
            ("cloudpaygateway.59wanmei.com", 8087, "云支付网关（主链路）"),
            ("app.17wanxiao.com", 443, "完美校园 App 登录（fallback 用）"),
            ("h5cloud.17wanxiao.com", 18443, "CloudPayment（fallback 用）"),
        ]
        for host, port, label in targets:
            ok, detail = _tcp_check(host, port)
            if ok:
                add("ok", "网络 %s" % label, "%s:%d 连通 %s" % (host, port, detail))
            else:
                add("warn", "网络 %s" % label, "%s:%d %s" % (host, port, detail))

    # 输出
    symbols = {"ok": "[ OK ]", "info": "[INFO]", "warn": "[WARN]", "fail": "[FAIL]"}
    print("=" * 78)
    print("完美校园电费监控 doctor（不登录、不外发个人信息；本机检查）")
    print("=" * 78)
    for level, name, detail in rows:
        print("%s %-26s %s" % (symbols.get(level, "[????]"), name, detail))
    counts = {level: sum(1 for row in rows if row[0] == level)
              for level in ("ok", "info", "warn", "fail")}
    print("-" * 78)
    print("结论：%d 项通过 / %d 项提示 / %d 项警告 / %d 项失败"
          % (counts["ok"], counts["info"], counts["warn"], counts["fail"]))
    if counts["fail"]:
        print("按上面的 [FAIL] 处理；5 步上手见 README_zh.md。")
        return 1
    print("配置与依赖检查通过。下一步：")
    print("  run.bat now     # 读一次剩余电量")
    print("  run.bat test    # 读一次并推一条确认消息")
    print("  powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1")
    print("                  # 装「每小时采样 + 周一 00:05 周报」两条计划任务")
    return 0


# --------------------------------------------------------------- secure ---
def do_secure():
    targets = [CFG_PATH_USED]
    if wanxiao_login is not None:
        targets.append(wanxiao_login.STATE_PATH)
    targets += [DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm",
                os.path.join(HERE, "logs", "monitor.log"),
                os.path.join(HERE, "logs", "report.log")]
    print("收紧以下文件权限（只保留当前用户访问）：")
    for path in targets:
        name = os.path.basename(path) or path
        print("  %-20s %s" % (name, util.harden_permissions(path)))
    print("\n提示：config.json / wanxiao_state.json 等同密码，不要提交仓库或发群里。")
    return 0


# -------------------------------------------------------------- install ---
def _schtasks_command(python_exe, script, command, log_name):
    return ('schtasks /Create /TN "PerfectCampusPower_%s" /SC %s /TR '
            '"\\"%s\\" \\"%s\\" %s --log \\"%s\\"" /F'
            % ("Hourly" if command == "sample" else "Weekly",
               "HOURLY /MO 1" if command == "sample" else "WEEKLY /D MON /ST 00:05",
               python_exe, script, command,
               os.path.join(HERE, "logs", log_name)))


def do_install():
    python_exe = sys.executable
    pythonw = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
    use_pythonw = os.path.exists(pythonw)
    runner = pythonw if use_pythonw else python_exe
    script = os.path.abspath(__file__)
    print("当前 Python  : %s" % python_exe)
    print("pythonw.exe  : %s" % (pythonw if use_pythonw else "未找到，计划任务会闪黑框"))
    print("脚本         : %s" % script)
    print()
    print("推荐用 install_task.ps1 一键注册（自动选 pythonw、写日志、装完自检）：")
    print('  powershell -NoProfile -ExecutionPolicy Bypass -File "%s\\install_task.ps1"'
          % HERE)
    print()
    print("等价的手动 schtasks 命令：")
    print("  " + _schtasks_command(runner, script, "sample", "monitor.log"))
    print("  " + _schtasks_command(runner, script, "report", "report.log"))
    print()
    print("查看任务：")
    print('  schtasks /Query /TN "PerfectCampusPower_Hourly" /V /FO LIST')
    print('  schtasks /Query /TN "PerfectCampusPower_Weekly" /V /FO LIST')
    print("立即跑一次（验证任务配置对不对）：")
    print('  schtasks /Run /TN "PerfectCampusPower_Hourly"')
    print("删除任务：")
    print('  schtasks /Delete /TN "PerfectCampusPower_Hourly" /F')
    print('  schtasks /Delete /TN "PerfectCampusPower_Weekly" /F')
    print()
    print("注意：默认每小时 1 次，别调更密（WAF 会拦，返回 405/9004）。")
    return 0


# ---------------------------------------------------------------- main ----
def build_parser():
    parser = argparse.ArgumentParser(
        prog="electricity_monitor.py",
        description="宿舍电量监控（完美校园云支付网关免登录 + 本地台账 + 低电提醒/周报）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例子：\n"
               "  run.bat doctor\n"
               "  run.bat projects\n"
               "  run.bat rooms --building 11 --room 616\n"
               "  run.bat now\n"
               "  run.bat test\n"
               "  run.bat report --dry\n"
               "  run.bat sample --log monitor.log\n")
    parser.add_argument("cmd", nargs="?", default="status",
                        choices=["projects", "rooms", "query", "snapshot",
                                 "dashboard", "now", "state", "sample", "watch",
                                 "run", "report", "status", "test", "doctor",
                                 "secure", "install"],
                        help="要执行的子命令（默认 status）")
    parser.add_argument("--dry", action="store_true",
                        help="试跑：只读、只打印，不写库、不推送")
    parser.add_argument("--force", action="store_true",
                        help="report：样本不足也推（调试版式）")
    parser.add_argument("--no-net", action="store_true",
                        help="doctor：跳过网络连通性检查")
    parser.add_argument("--interval", type=int, default=3600,
                        help="watch：采样间隔秒数（默认 3600）")
    parser.add_argument("--campus", help="rooms：校区名关键字")
    parser.add_argument("--building", help="rooms：楼栋名关键字")
    parser.add_argument("--room", help="rooms：房间号关键字；query：按房间关键字选房间")
    parser.add_argument("--floor", help="rooms：楼层关键字")
    parser.add_argument("--payproid", help="rooms：临时指定缴费项目 id")
    parser.add_argument("--max-calls", type=int, default=400,
                        help="rooms：最多请求次数（默认 400，防止撞 WAF）")
    parser.add_argument("--all", action="store_true",
                        help="query：查询 config rooms[] 里的全部房间")
    parser.add_argument("--json-out", help="query：把结果写入 JSON 文件")
    parser.add_argument("--out",
                        help="snapshot/dashboard：输出文件路径（默认同目录 snapshot.json / dashboard.html）")
    parser.add_argument("--snapshot",
                        help="dashboard：snapshot JSON 路径（默认同目录 snapshot.json）")
    parser.add_argument("--low-threshold", type=float,
                        help="snapshot：低电阈值（默认 config.snapshot_low_threshold 或 30 度）")
    parser.add_argument("--req-interval", type=float, default=1.1,
                        help="query/snapshot：每请求间隔秒数（默认 1.1，别调太小，WAF 会拦）")
    parser.add_argument("--fixture",
                        help="离线假数据模式：用 fixture JSON 代替真实网关（演示/测试用）")
    parser.add_argument("--config", help="配置文件路径（默认同目录 config.json）")
    parser.add_argument("--backend", choices=["cloudpay", "wanxiao"],
                        help="临时覆盖 config 里的 backend")
    parser.add_argument("--log", help="把输出同时追加到日志文件（计划任务用）")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + APP_VERSION)
    return parser


def run(args):
    load_config(args.config or CONFIG_PATH)
    if args.backend:
        CFG["backend"] = args.backend
    if wanxiao_login is not None:
        wanxiao_login.set_config_path(CFG_PATH_USED)
    if args.fixture:
        os.environ["CLOUDPAY_FIXTURE"] = os.path.abspath(args.fixture)
    else:
        os.environ.pop("CLOUDPAY_FIXTURE", None)

    cmd = args.cmd
    if cmd == "doctor":
        return do_doctor(no_net=args.no_net)
    if cmd == "secure":
        return do_secure()
    if cmd == "install":
        return do_install()
    if cmd == "dashboard":
        return do_dashboard(args)

    lock = util.FileLock(os.path.join(HERE, ".lock"))
    need_lock = cmd in ("sample", "watch", "run", "report", "test",
                        "query", "snapshot")
    if need_lock and not lock.acquire():
        print("[跳过] 上一轮还没跑完（锁文件 %s 存在），本轮不执行" % lock.path)
        return 0
    try:
        if cmd == "query":
            return do_query(args)
        if cmd == "snapshot":
            return do_snapshot(args)
        connection = db()
        try:
            if cmd == "projects":
                return do_projects()
            if cmd == "rooms":
                return do_rooms(args)
            if cmd in ("now", "state"):
                return do_now()
            if cmd == "sample":
                do_sample(connection, dry=args.dry)
                return 0
            if cmd == "test":
                return do_test(connection, dry=args.dry)
            if cmd == "report":
                do_report(connection, dry=args.dry, force=args.force)
                return 0
            if cmd == "status":
                return do_status(connection)
            if cmd in ("watch", "run"):
                return do_run(connection, args.interval)
            raise SystemExit("未知命令：%s" % cmd)
        finally:
            try:
                connection.close()
            except Exception:
                pass
    finally:
        if need_lock:
            lock.release()


def main(argv=None):
    util.setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    log_handle = util.start_file_log(args.log) if args.log else None
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n已取消")
        return 130
    except SystemExit:
        raise
    except Exception as exc:
        print("[错误] %s: %s" % (type(exc).__name__, util.scrub(str(exc))))
        return 1
    finally:
        if log_handle is not None:
            try:
                log_handle.flush()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
