# -*- coding: utf-8 -*-
"""完美校园「云支付网关」免登录查询客户端（cloudpay 主后端）。

来源：项目 Lead 2026-11-05 在福建中医药大学（schoolcode=769）用真实学号实测通过，
17 个班级房间全部拿到真实剩余量。**不需要账号密码 / token / deviceId / 短信**，
只需要 schoolcode + 学号(idserial) + payproid + roomverify（或 rooms 数组批量）。

网关：POST https://cloudpaygateway.59wanmei.com:8087/paygateway/smallpaygateway/trade
信封：{"method": "...", "bizcontent": "<JSON 字符串>", "timestamp": "YYYY-MM-DD HH:MM:SS", "sourceId": 2}

关键实测细节：
- 缴费项目：method=smallProgramPayPro，FJTCM 返回 2122 旗山用电支出 / 3518 / 4498。
- 房间树：method=samllProgramGetRoom（服务端拼写就是 samll）。
  所有楼栋 optype=3 只返回一个虚拟楼层 id=-1；optype=4 返回的 id 就是 roomverify，
  形如 `1-13---324`、`4-23B---423`（areaid-楼栋---房间）。
- 查电量：method=samllProgramGetRoomState → businessData.quantity / quantityunit / description。
- 重试：超时 / 网络错 / 5xx / 405 / 「频繁请求」「9004」等可重试错误，
  按 3s→6s→12s 退避，最多重试 3 次；耗尽后提示可能被 WAF 限流，不死循环。
- 批量查询串行执行，每请求间隔默认 1.1 秒（17 个房间约 20 秒），不要并发。

本文件是本地化新增代码（非 jialiangh 原项目），MIT 许可，见 NOTICE。
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime

import util

GATEWAY = (os.environ.get("CLOUDPAY_GATEWAY")
           or "https://cloudpaygateway.59wanmei.com:8087/paygateway/smallpaygateway/trade")
HOMEPAGE = "https://cloudpaygateway.59wanmei.com:8087/pay/index.html"
ORIGIN = "https://cloudpaygateway.59wanmei.com:8087"
SOURCE_ID = 2
CHANNELNO = "30"
DEFAULT_BUSINESSTYPE = "2"
DEFAULT_REQ_INTERVAL = 1.1
RETRY_WAITS = (3, 6, 12)          # 指数退避：3s / 6s / 12s，最多重试 3 次
WAF_HINT = "（可能被 WAF 限流：等几分钟再试；采样频率别超过每小时 1 次）"

# 注意：房间树/房间状态两个方法在服务端就叫 "samll"（拼写如此），别"修正"成 small。
METHOD_PROJECTS = "smallProgramPayPro"
METHOD_ROOM_LEVEL = "samllProgramGetRoom"
METHOD_ROOM_STATE = "samllProgramGetRoomState"

DEFAULT_UA = ("Mozilla/5.0 (Linux; Android 12; 24031PN0DC Build/V417IR; wv) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
              "Chrome/110.0.5481.154 Safari/537.36 Wanxiao/5.8.9 Wmxy/5.8.27")


class CloudPayError(RuntimeError):
    """网关调用失败（连不上 / 返回非 SUCCESS / 字段缺失 / fixture 未命中）。"""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = bool(retryable)


def _looks_like_waf(text):
    text = str(text or "")
    return any(mark in text for mark in
               ("频繁", "频率", "限流", "稍后重试", "熔断", "9004", "405"))


# ------------------------------------------------------------- 配置读取 ---
def _schoolcode(cfg):
    return str((cfg or {}).get("schoolcode") or "769").strip()


def _idserial(cfg):
    value = str((cfg or {}).get("idserial") or "").strip()
    if util.is_placeholder_text(value):
        raise CloudPayError("config.json 里 \"idserial\"（学号）没填")
    return value


def _businesstype(cfg):
    proj = ((cfg or {}).get("payPro") or {}).get("electric") or {}
    return str(proj.get("businesstype") or (cfg or {}).get("businesstype")
               or DEFAULT_BUSINESSTYPE)


def _timeout(cfg):
    try:
        return max(5, int((cfg or {}).get("request_timeout") or 25))
    except (TypeError, ValueError):
        return 25


def make_gateway(cfg, gw=None):
    """返回网关客户端：显式传入 > 环境变量 CLOUDPAY_FIXTURE > 真实 HTTP 网关。"""
    if gw is not None:
        return gw
    fixture = os.environ.get("CLOUDPAY_FIXTURE")
    if fixture:
        return FixtureGateway(fixture)
    return Gateway(timeout=_timeout(cfg))


# --------------------------------------------------------------- 客户端 ---
class Gateway:
    """云支付网关客户端（标准库 urllib，TLS 正常校验，带指数退避重试）。"""

    def __init__(self, timeout=25, gateway=None, ua=DEFAULT_UA, opener=None,
                 sleeper=None, notify=None):
        self.timeout = timeout
        self.gateway = gateway or GATEWAY
        self.ua = ua
        self.opener = opener or urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self.sleeper = sleeper or time.sleep
        self.notify = notify

    def call(self, method, bizcontent, source_id=SOURCE_ID):
        """发一次网关请求（失败按 3/6/12 秒退避重试），返回 businessData。"""
        for attempt in range(len(RETRY_WAITS) + 1):
            try:
                return self._call_once(method, bizcontent, source_id)
            except CloudPayError as exc:
                if not exc.retryable:
                    raise
                if attempt >= len(RETRY_WAITS):
                    message = str(exc)
                    if _looks_like_waf(message) and WAF_HINT not in message:
                        message += WAF_HINT
                    raise CloudPayError(message) from exc
                wait = RETRY_WAITS[attempt]
                if self.notify:
                    self.notify("[重试] %s；%d 秒后再试（%d/%d）"
                                % (str(exc)[:160], wait, attempt + 1, len(RETRY_WAITS)))
                self.sleeper(wait)
        raise CloudPayError("网关请求失败（重试耗尽）")

    def _call_once(self, method, bizcontent, source_id):
        envelope = {
            "method": str(method),
            "bizcontent": json.dumps(bizcontent, ensure_ascii=False,
                                     separators=(",", ":")),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sourceId": source_id,
        }
        body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Origin": ORIGIN,
            "Referer": HOMEPAGE,
            "User-Agent": self.ua,
        }
        request = urllib.request.Request(self.gateway, data=body,
                                         headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            retryable = exc.code in (405, 408, 425, 429) or exc.code >= 500
            raise CloudPayError("网关 HTTP %s：%s"
                                % (exc.code, detail or exc.reason),
                                retryable=retryable)
        except urllib.error.URLError as exc:
            raise CloudPayError("网关连不上（%s）：%s"
                                % (self.gateway, util.scrub(str(getattr(exc, "reason", exc)))),
                                retryable=True)
        except (TimeoutError, OSError) as exc:
            raise CloudPayError("网关请求失败：%s" % util.scrub(str(exc)),
                                retryable=True)

        text = raw.decode("utf-8", "replace").strip()
        try:
            payload = json.loads(text)
        except ValueError:
            raise CloudPayError("网关返回非 JSON（前 200 字）：%s" % text[:200])
        if not isinstance(payload, dict):
            raise CloudPayError("网关返回结构异常：%s" % util.compact(payload))

        code = str(payload.get("returncode") or "").strip()
        if code and code.upper() not in ("SUCCESS", "0000", "0", "200"):
            detail = (payload.get("returnmsg") or payload.get("message")
                      or payload.get("returnmessage") or text[:160])
            extra = " ".join(str(payload.get(key) or "")
                             for key in ("code_", "code", "message_"))
            raise CloudPayError("网关返回 %s：%s" % (code, detail),
                                retryable=_looks_like_waf("%s %s" % (detail, extra)))
        if "businessData" not in payload:
            raise CloudPayError("网关响应缺少 businessData：%s" % text[:160])
        return payload.get("businessData")


class FixtureGateway:
    """离线假网关：从 JSON fixture 按 method + bizcontent 子集匹配返回 businessData。

    fixture 格式（tests/fixtures/*.fixture.json）：
      {"responses": [
         {"method": "smallProgramPayPro", "bizcontent": {"schoolcode": "769"},
          "businessData": [...]},
         {"method": "samllProgramGetRoomState",
          "bizcontent": {"roomverify": "1-13---324"},
          "businessData": {"description": "剩余电量", "quantity": "78.97",
                           "quantityunit": "度"}},
         {"method": "...", "error": "模拟错误"}
      ]}
    用于 --fixture 演示与离线测试，绝不发网络请求。
    """

    def __init__(self, path):
        self.path = os.path.abspath(str(path))
        self.calls = []
        data, error = util.load_json(self.path)
        if error:
            raise CloudPayError("fixture 读取失败：%s（%s）" % (self.path, error))
        responses = data.get("responses") if isinstance(data, dict) else data
        if not isinstance(responses, list):
            raise CloudPayError("fixture 格式错误：需要 responses 数组")
        self.responses = responses

    def call(self, method, bizcontent, source_id=SOURCE_ID):
        self.calls.append({"method": method, "bizcontent": bizcontent,
                           "source_id": source_id})
        for item in self.responses:
            if not isinstance(item, dict) or item.get("method") != method:
                continue
            expect = item.get("bizcontent")
            if isinstance(expect, dict):
                if not all(str(bizcontent.get(key)) == str(value)
                           for key, value in expect.items()):
                    continue
            if item.get("error"):
                raise CloudPayError(str(item["error"]))
            return item.get("businessData")
        raise CloudPayError("fixture 未命中：method=%s bizcontent=%s"
                            % (method, util.compact(bizcontent)))


# --------------------------------------------------------------- 解析 -----
def _as_list(data):
    """把 businessData 统一成 list（兼容 list / dict / JSON 字符串 / 包了一层）。"""
    if data is None:
        return []
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "rows", "items", "data", "roomlist", "payprolist"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                parsed = _as_list(value)
                if parsed:
                    return parsed
        if any(data.get(key) not in (None, "") for key in
               ("id", "quantity", "name")):
            return [data]
        return []
    return []


def _node_id(node):
    for key in ("id", "areaid", "buildid", "unitid", "levelid", "payproid"):
        value = node.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _node_name(node):
    for key in ("name", "roomname", "buildname", "areaname", "levelname",
                "unitname", "description", "title"):
        value = node.get(key)
        if value not in (None, ""):
            return str(value)
    return _node_id(node)


def _find_quantity(data):
    """从 businessData 里找 quantity / quantityunit / description。"""
    if isinstance(data, dict):
        candidates = [data]
    else:
        candidates = [item for item in _as_list(data) if isinstance(item, dict)]
    for item in candidates:
        quantity = item.get("quantity")
        if quantity is None:
            continue
        try:
            value = float(str(quantity).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
        return (value,
                str(item.get("quantityunit") or "度"),
                str(item.get("description") or ""))
    return None


def _roomverify_of(campus_id, building_id, floor_id, room_node):
    """optype=4 返回的 id 通常已经是拼好的 roomverify；没有时按原格式拼。"""
    for key in ("roomverify", "id"):
        value = room_node.get(key)
        if value not in (None, "") and "--" in str(value):
            return str(value)
    room_id = _node_id(room_node)
    return "%s-%s--%s-%s" % (campus_id, building_id, floor_id, room_id)


# --------------------------------------------------------------- 接口 -----
def list_projects(cfg, gw=None):
    """查缴费项目：method=smallProgramPayPro → [{id, payproname, description, ...}]。"""
    client = make_gateway(cfg, gw)
    data = client.call(METHOD_PROJECTS, {
        "schoolcode": _schoolcode(cfg),
        "idserial": _idserial(cfg),
        "channelno": str((cfg or {}).get("channelno") or CHANNELNO),
    })
    return [item for item in _as_list(data) if isinstance(item, dict)]


def payproname(cfg, payproid, gw=None):
    """按 payproid 反查项目名（查不到时退回 config 里的配置名）。"""
    try:
        projects = list_projects(cfg, gw=gw)
    except CloudPayError:
        projects = []
    for item in projects:
        if str(item.get("id") or item.get("payproid") or "") == str(payproid):
            return str(item.get("payproname") or "")
    return str(((cfg or {}).get("payPro") or {}).get("electric", {}).get("name")
               or "用电支出")


def resolve_payproid(cfg, gw=None):
    """payproid 优先级：config 显式填写 > 按项目名匹配（默认「用电支出」）。"""
    configured = str((cfg or {}).get("payproid") or "").strip()
    if configured and not util.is_placeholder_text(configured):
        return configured
    proj_name = str(((cfg.get("payPro") or {}).get("electric") or {}).get("name")
                    or "").strip() or "用电支出"
    projects = list_projects(cfg, gw=gw)
    if not projects:
        raise CloudPayError(
            "没有返回任何缴费项目：检查 schoolcode / idserial 是否正确，"
            "或网关接口是否已变更（先跑 projects 看看）")
    exact = [p for p in projects
             if str(p.get("payproname") or "").strip() == proj_name]
    if len(exact) == 1:
        return str(exact[0].get("id"))
    candidates = exact or [p for p in projects
                           if proj_name in str(p.get("payproname") or "")
                           or "电" in str(p.get("payproname") or "")]
    if len(candidates) == 1:
        return str(candidates[0].get("id"))
    names = "、".join("%s(id=%s)" % (p.get("payproname"), p.get("id"))
                      for p in candidates or projects)
    if len(candidates) > 1:
        raise CloudPayError("有多个候选缴费项目：%s\n请在 config.json 里显式填 \"payproid\""
                            % names)
    raise CloudPayError("没找到名称含 %r 的缴费项目；现有项目：%s\n"
                        "先运行 projects 看看，再把 id 填进 config.json 的 \"payproid\""
                        % (proj_name, names))


def room_level(cfg, optype, payproid, areaid="0", buildid="0",
               unitid="0", levelid="0", gw=None):
    """房间树一层：optype 1 校区 / 2 楼栋 / 3 楼层 / 4 房间。"""
    client = make_gateway(cfg, gw)
    data = client.call(METHOD_ROOM_LEVEL, {
        "schoolno": _schoolcode(cfg),
        "optype": str(optype),
        "payproid": str(payproid),
        "areaid": str(areaid),
        "buildid": str(buildid),
        "unitid": str(unitid),
        "levelid": str(levelid),
        "businesstype": _businesstype(cfg),
        "idserial": _idserial(cfg),
    })
    return [item for item in _as_list(data) if isinstance(item, dict)]


def search_rooms(cfg, payproid, campus=None, building=None, room=None,
                 floor=None, max_calls=400, gw=None, progress=None):
    """按 校区→楼栋→楼层→房间 逐层下钻，返回 (hits, 请求次数)。

    实测 FJTCM：每栋楼的 optype=3 只返回一个虚拟楼层 id=-1，optype=4 的 id 就是
    roomverify（形如 `1-13---324` / `4-23B---423`）。
    campus/building/room/floor 都是**子串关键字**，用于剪枝，避免整棵树全量拉。
    """
    client = make_gateway(cfg, gw)
    calls = [0]
    hits = []

    def fetch(optype, areaid="0", buildid="0", levelid="0"):
        calls[0] += 1
        if calls[0] > max_calls:
            raise CloudPayError("请求数超过 %d，请用 --campus / --building 缩小范围"
                                % max_calls)
        return room_level(cfg, optype, payproid, areaid=areaid, buildid=buildid,
                          levelid=levelid, gw=client)

    for campus_node in fetch(1):
        campus_id = _node_id(campus_node)
        campus_name = _node_name(campus_node)
        if campus and campus not in campus_name and campus not in campus_id:
            continue
        for building_node in fetch(2, areaid=campus_id):
            building_id = _node_id(building_node)
            building_name = _node_name(building_node)
            if building and building not in building_name and building not in building_id:
                continue
            for floor_node in fetch(3, areaid=campus_id, buildid=building_id):
                floor_id = _node_id(floor_node)
                floor_name = _node_name(floor_node)
                if floor and floor not in floor_name and floor not in floor_id:
                    continue
                for room_node in fetch(4, areaid=campus_id, buildid=building_id,
                                       levelid=floor_id):
                    room_id = _node_id(room_node)
                    room_name = _node_name(room_node)
                    if room and room not in room_name and room not in room_id:
                        continue
                    roomverify = _roomverify_of(campus_id, building_id,
                                                floor_id, room_node)
                    tokens = util.parse_roomverify(roomverify) or {}
                    hits.append({
                        "campus": campus_name,
                        "building": building_name,
                        "floor": floor_name,
                        "room": room_name,
                        "roomverify": roomverify,
                        "areaid": tokens.get("areaid", campus_id),
                        "building_no": tokens.get("building", building_id),
                        "room_no": tokens.get("room", room_id),
                    })
                    if progress and len(hits) % 20 == 0:
                        progress("  已找到 %d 个候选（%d 次请求）"
                                 % (len(hits), calls[0]))
    return hits, calls[0]


def room_state(cfg, payproid, roomverify, gw=None):
    """查单个房间状态，返回原始 businessData。"""
    client = make_gateway(cfg, gw)
    return client.call(METHOD_ROOM_STATE, {
        "payproid": str(payproid),
        "schoolcode": _schoolcode(cfg),
        "roomverify": str(roomverify),
        "businesstype": _businesstype(cfg),
    })


def read_room_quantity(cfg, payproid, roomverify, gw=None):
    """查一个房间的剩余量，返回 (数值, 单位, 房间描述)。"""
    data = room_state(cfg, payproid, roomverify, gw=gw)
    found = _find_quantity(data)
    if found is None:
        raise CloudPayError("getRoomState 响应里没有 quantity 字段：%s"
                            % util.compact(data))
    value, unit, description = found
    if value < 0:
        raise CloudPayError("返回剩余量是负数（%g），房间号可能不对或已欠费" % value)
    return value, unit, description


def read_kwh(cfg, gw=None):
    """读「默认房间」一次剩余量，返回 (剩余量 float, 单位, 房间描述)。"""
    client = make_gateway(cfg, gw)
    payproid = resolve_payproid(cfg, gw=client)
    active = util.cfg_active_room(cfg)
    if active is None:
        raise CloudPayError("config.json 里没有可查的房间：填 room.roomverify，"
                            "或用 rooms[] + default_room")
    return read_room_quantity(cfg, payproid, active["roomverify"], gw=client)


def read_many(cfg, rooms, payproid=None, interval=None, gw=None, sleeper=None,
              progress=None, notify=None):
    """串行批量查房间（每请求间隔 ≥ interval 秒），单房间失败不中断整批。

    返回 rows：[{"label","building","room","roomverify","quantity","unit","ok","error"}]
    """
    client = make_gateway(cfg, gw)
    pid = payproid or resolve_payproid(cfg, gw=client)
    if interval is None:
        try:
            interval = float((cfg or {}).get("request_interval") or DEFAULT_REQ_INTERVAL)
        except (TypeError, ValueError):
            interval = DEFAULT_REQ_INTERVAL
    interval = max(0.0, min(float(interval), 60.0))
    sleeper = sleeper or time.sleep
    rows = []
    for index, room in enumerate(rooms):
        if index and interval:
            sleeper(interval)
        roomverify = str(room.get("roomverify") or "").strip()
        row = {
            "label": str(room.get("label") or roomverify),
            "building": str(room.get("building") or ""),
            "room": str(room.get("room") or ""),
            "roomverify": roomverify,
            "quantity": None,
            "unit": "度",
            "ok": False,
            "error": "",
        }
        try:
            value, unit, _description = read_room_quantity(cfg, pid, roomverify,
                                                           gw=client)
            row.update({"quantity": value, "unit": unit, "ok": True})
        except CloudPayError as exc:
            row["error"] = util.scrub(str(exc))
        rows.append(row)
        if progress:
            progress(index + 1, len(rooms), row, notify)
    return rows


def ping(host="cloudpaygateway.59wanmei.com", port=8087, timeout=5):
    """TCP 连通性检查（doctor 用；不发任何请求、不带个人信息）。"""
    import socket
    started = time.time()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            pass
    except OSError as exc:
        return False, "%.0f ms 内连不上：%s" % (timeout * 1000, exc)
    return True, "%.0f ms" % ((time.time() - started) * 1000)
