# -*- coding: utf-8 -*-
"""公共工具：Windows 控制台 / 文件日志 / 密钥掩码 / 单实例锁 / 权限收紧 / 配置校验。

本文件是本地化新增代码（非 jialiangh 原项目），MIT 许可，来源与改动见 NOTICE。
设计原则：只用标准库；任何"加固"动作都 best-effort，失败只提示不中断。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

PLACEHOLDER_MARKS = (
    "你的", "填这里", "填自己", "填上", "改成", "示例", "抓包", "查出来",
    "形如", "todo", "xxx",
)


# ------------------------------------------------------------- 运行环境 ---
def is_windows():
    return os.name == "nt"


def setup_console():
    """统一 UTF-8：Windows 控制台切 65001 + Python 流 errors=replace。

    计划任务用 pythonw.exe 时没有控制台，这里不会报错；日志由 start_file_log 落盘。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    if is_windows():
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.SetConsoleOutputCP(65001)
            k32.SetConsoleCP(65001)
        except Exception:
            pass
        os.environ.setdefault("PYTHONUTF8", "1")
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")


class _Tee:
    """把 stdout/stderr 同时写到控制台和日志文件；每行加时间戳（便于计划任务排错）。"""

    def __init__(self, stream, logfile):
        self._stream = stream
        self._file = logfile
        self._at_line_start = True

    def write(self, data):
        if not data:
            return 0
        if self._stream is not None:
            try:
                self._stream.write(data)
            except Exception:
                pass
        chunks = []
        for piece in str(data).splitlines(True):
            if self._at_line_start:
                chunks.append(time.strftime("[%Y-%m-%d %H:%M:%S] "))
            chunks.append(piece)
            self._at_line_start = piece.endswith("\n")
        try:
            self._file.write("".join(chunks))
            self._file.flush()
        except Exception:
            pass
        return len(data)

    def flush(self):
        if self._stream is not None:
            try:
                self._stream.flush()
            except Exception:
                pass
        try:
            self._file.flush()
        except Exception:
            pass

    def isatty(self):
        return bool(self._stream is not None and getattr(self._stream, "isatty", lambda: False)())

    def __getattr__(self, item):
        stream = self.__dict__.get("_stream")
        if stream is not None:
            return getattr(stream, item)
        raise AttributeError(item)


def start_file_log(path):
    """给计划任务用：pythonw.exe 没有控制台，把 print 同时落盘。返回文件句柄。"""
    if not path:
        return None
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    handle = open(path, "a", encoding="utf-8", newline="")
    sys.stdout = _Tee(sys.stdout, handle)
    sys.stderr = _Tee(sys.stderr, handle)
    return handle


# --------------------------------------------------------------- 掩码 -----
def mask_secret(value, head=6, tail=4):
    """密码/token/deviceId 一类的掩码：只留头尾各几位，中间固定 6 个 *。"""
    if value is None:
        return "(未设置)"
    text = str(value)
    if not text:
        return "(未设置)"
    if len(text) <= head + tail:
        return "*" * max(len(text), 4)
    return text[:head] + "*" * 6 + text[-tail:]


def mask_phone(phone):
    text = str(phone or "").strip()
    if not text:
        return "(未设置)"
    if len(text) >= 7:
        return text[:3] + "****" + text[-4:]
    return "*" * len(text)


def mask_email(addr):
    text = str(addr or "").strip()
    if "@" not in text:
        return mask_secret(text, 2, 2)
    local, domain = text.split("@", 1)
    return "%s***@%s" % (local[:1], domain)


def mask_url(url):
    """webhook / 推送 URL 只保留 host，路径与 key 全部隐去。"""
    try:
        parts = urllib.parse.urlsplit(str(url))
        return "%s://%s/***" % (parts.scheme, parts.netloc or "?")
    except Exception:
        return "***"


_SECRET_QUERY_RE = re.compile(
    r"(?i)((?:token|key|sendkey|secret|password|passwd|access_token|auth)=)[^&\s\"']+")
_SCT_KEY_RE = re.compile(r"(?i)(sctapi\.ftqq\.com/)[0-9A-Za-z]+")


def scrub(text):
    """日志兜底：异常信息里若带 token/key，一律掩掉。"""
    if not text:
        return text
    out = _SECRET_QUERY_RE.sub(lambda m: m.group(1) + "***", str(text))
    return _SCT_KEY_RE.sub(lambda m: m.group(1) + "***", out)


def compact(obj, limit=200):
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        text = repr(obj)
    return text if len(text) <= limit else text[:limit] + "…"


def is_placeholder_text(value):
    """配置里没填的占位文本（如「你的学号」）一律当作未填。"""
    text = str(value or "").strip()
    if not text:
        return True
    low = text.lower()
    return any(mark.lower() in low for mark in PLACEHOLDER_MARKS)


# ------------------------------------------------------------- 文件锁 -----
class FileLock:
    """单实例锁：替代原项目的 flock（Windows 没有 flock）。

    计划任务重叠（上一轮没跑完）时直接跳过本轮，避免请求叠加触发 WAF。
    """

    def __init__(self, path, stale_after=3600, verbose=True):
        self.path = os.path.abspath(path)
        self.stale_after = stale_after
        self.verbose = verbose
        self._fd = None
        self.acquired = False

    def acquire(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        except OSError:
            pass
        for _ in range(2):
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(self._fd, ("%d\n" % os.getpid()).encode("ascii"))
                except OSError:
                    pass
                self.acquired = True
                return True
            except FileExistsError:
                age = 0.0
                try:
                    age = time.time() - os.path.getmtime(self.path)
                except OSError:
                    pass
                if age > self.stale_after:
                    try:
                        os.remove(self.path)
                    except OSError:
                        pass
                    continue
                return False
            except OSError as exc:
                # 锁文件所在目录不可写时宁可继续跑，不要静默不采集
                if self.verbose:
                    print("[锁] 无法创建 %s：%s（继续执行）" % (self.path, exc))
                self.acquired = True
                return True
        return False

    def release(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self.acquired:
            try:
                os.remove(self.path)
            except OSError:
                pass
            self.acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc_info):
        self.release()
        return False


# ----------------------------------------------------------- 文件/权限 -----
def write_private_json(path, obj, indent=1):
    """原子写 JSON（先写 .tmp 再 replace），写完整力收紧权限。"""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=indent)
        handle.write("\n")
    os.replace(tmp, path)
    return harden_permissions(path)


def harden_permissions(path):
    """把凭据文件权限收到只有当前用户可读写（Windows: icacls；POSIX: chmod 600）。

    返回一句人类可读的结果，失败不抛异常（不影响主流程）。
    """
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return "不存在，跳过"
    if not is_windows():
        try:
            os.chmod(path, 0o600)
            return "已 chmod 600"
        except OSError as exc:
            return "chmod 失败：%s" % exc
    user = os.environ.get("USERNAME")
    if not user:
        return "拿不到 USERNAME，跳过"
    try:
        proc = subprocess.run(
            ["icacls", path, "/inheritance:r", "/grant:r", "%s:F" % user, "/Q"],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return "icacls 调用失败：%s" % exc
    if proc.returncode != 0:
        detail = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()
        return "icacls 返回 %d%s" % (proc.returncode, ("：" + detail[0]) if detail else "")
    return "已收紧为仅 %s 可访问" % user


def load_json(path):
    """返回 (data, error_str)。不抛异常，给 doctor / 测试用。"""
    path = os.path.abspath(path)
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, "文件不存在"
    except ValueError as exc:
        return None, "JSON 解析失败：%s" % exc
    except OSError as exc:
        return None, "读取失败：%s" % exc


# ----------------------------------------------------------- 配置校验 -----
def _add(out, level, field, msg):
    out.append({"level": level, "field": field, "msg": msg})


_ROOMVERIFY_RE = re.compile(r"^(\d+)-([^-]+)-+([^-]+)$")


def parse_roomverify(value):
    """解析 FJTCM 的 roomverify：areaid-楼栋---房间。

    实测格式：`1-13---324`（13号楼324）、`4-23B---423`（23号楼B座423）。
    解析不出来返回 None（不猜测，交给 doctor 提示）。
    """
    match = _ROOMVERIFY_RE.match(str(value or "").strip())
    if not match:
        return None
    return {"areaid": match.group(1), "building": match.group(2),
            "room": match.group(3)}


def canonical_room(roomverify):
    """按班级站规范名从 roomverify 生成展示名：{楼号}号楼{座}{房间号}。

    1-13---324  -> building=13号楼,    room=324, label=13号楼324
    4-23B---423 -> building=23号楼B座, room=423, label=23号楼B座423
    解析不出来返回 None（不猜测）。
    """
    tokens = parse_roomverify(roomverify)
    if not tokens:
        return None
    token = tokens["building"]
    room = tokens["room"]
    match = re.fullmatch(r"(\d+)([A-Za-z])", token)
    if match:
        building = "%s号楼%s座" % (match.group(1), match.group(2).upper())
    elif token.isdigit():
        building = token + "号楼"
    else:
        return None
    return {"building": building, "room": room, "label": building + room}


def _natural_key(text):
    """自然排序键：13号楼 < 16号楼 < 23号楼A座 < 23号楼B座，房间号按数字。"""
    text = str(text or "")
    match = re.match(r"^(\d+)(.*)$", text)
    if match:
        return (0, int(match.group(1)), match.group(2))
    return (1, 0, text)


def room_sort_key(room):
    return (_natural_key(room.get("building")), _natural_key(room.get("room")))


def _room_matches(item, keyword):
    keyword = str(keyword or "")
    if not keyword:
        return False
    return (keyword in item.get("roomverify", "")
            or keyword in item.get("label", "")
            or keyword in (item.get("raw_label") or ""))


def cfg_rooms(cfg):
    """把 config 的 rooms[] 规范化成 [{label, raw_label, roomverify, occupant, building, room}]。

    - label / building / room 一律按规范名从 roomverify 派生（保证本机工具与班级站同一套名字）；
      roomverify 解析不了时才退回 config 里手写的 label/building；
    - `occupant`（同宿舍同学姓名）只保留在本机内存里，**任何输出/快照/看板都不得带**；
    - 结果按 楼号 → 房间号 自然排序（13号楼 → 16号楼 → 23号楼A座 → 23号楼B座）。
    """
    raw = (cfg or {}).get("rooms")
    rooms = []
    if not isinstance(raw, list):
        return rooms
    for item in raw:
        if not isinstance(item, dict):
            continue
        roomverify = str(item.get("roomverify") or "").strip()
        if not roomverify:
            continue
        canonical = canonical_room(roomverify)
        raw_label = str(item.get("label") or "").strip()
        rooms.append({
            "label": canonical["label"] if canonical else (raw_label or roomverify),
            "raw_label": raw_label,
            "roomverify": roomverify,
            "occupant": str(item.get("occupant") or "").strip(),
            "building": canonical["building"] if canonical
                        else str(item.get("building") or ""),
            "room": canonical["room"] if canonical
                    else str(item.get("room") or ""),
        })
    rooms.sort(key=room_sort_key)
    return rooms


def cfg_active_room(cfg):
    """当前操作的房间：default_room 匹配 > room.roomverify > rooms[] 第一个。

    default_room 可写规范名、旧 label、或 roomverify 子串（兼容改造前的旧配置）。
    """
    cfg = cfg or {}
    rooms = cfg_rooms(cfg)
    default = str(cfg.get("default_room") or "").strip()
    if default and not is_placeholder_text(default):
        for item in rooms:
            if default in (item["roomverify"], item["label"],
                           item.get("raw_label")):
                return item
        for item in rooms:
            if _room_matches(item, default):
                return item
    room = cfg.get("room") if isinstance(cfg.get("room"), dict) else {}
    roomverify = str(room.get("roomverify") or "").strip()
    if roomverify and not is_placeholder_text(roomverify):
        canonical = canonical_room(roomverify) or {}
        return {
            "label": canonical.get("label")
                     or str(room.get("label") or roomverify).strip(),
            "raw_label": str(room.get("label") or "").strip(),
            "roomverify": roomverify,
            "occupant": "",
            "building": canonical.get("building", ""),
            "room": canonical.get("room", ""),
        }
    return rooms[0] if rooms else None


def validate_config(cfg):
    """离线校验 config.json，返回 [{"level": ok|info|warn|fail, "field", "msg"}]。

    不打印、不联网。doctor 用它逐条展示，监控命令用 fail 项做开跑前检查。
    """
    out = []
    if not isinstance(cfg, dict) or not cfg:
        _add(out, "fail", "config", "配置文件缺失或为空：先复制 config.example.json 为 config.json")
        return out

    backend = str(cfg.get("backend") or "cloudpay").strip().lower()
    if backend not in ("cloudpay", "wanxiao"):
        _add(out, "fail", "backend", "backend 只能填 cloudpay 或 wanxiao（当前 %r）" % backend)
        backend = "cloudpay"
    else:
        _add(out, "ok", "backend", "backend = %s" % backend)

    school = str(cfg.get("schoolcode") or "").strip()
    if not school:
        _add(out, "fail", "schoolcode", "schoolcode 未填（FJTCM = 769）")
    elif school == "769":
        _add(out, "ok", "schoolcode", "schoolcode = 769（福建中医药大学）")
    else:
        _add(out, "ok", "schoolcode", "schoolcode = %s（FJTCM 预置值是 769，请确认）" % school)

    raw_rooms = cfg.get("rooms")
    if raw_rooms is not None and not isinstance(raw_rooms, list):
        _add(out, "fail", "rooms", "rooms 必须是数组：[{label, roomverify, occupant?}, ...]")
    elif isinstance(raw_rooms, list):
        invalid = [index for index, item in enumerate(raw_rooms)
                   if not (isinstance(item, dict)
                           and str(item.get("roomverify") or "").strip())]
        if invalid:
            _add(out, "fail", "rooms",
                 "rooms 第 %s 项缺少 roomverify（形如 1-13---324 / 4-23B---423）"
                 % "、".join(str(index) for index in invalid[:5]))
        valid_rooms = cfg_rooms(cfg)
        if valid_rooms:
            _add(out, "ok", "rooms", "rooms 已配置 %d 个房间" % len(valid_rooms))
            seen = [item["roomverify"] for item in valid_rooms]
            duplicates = sorted({value for value in seen if seen.count(value) > 1})
            if duplicates:
                _add(out, "warn", "rooms",
                     "rooms 里有重复 roomverify：%s" % "、".join(duplicates[:5]))
            if any(item.get("occupant") for item in raw_rooms
                   if isinstance(item, dict)):
                _add(out, "info", "rooms.occupant",
                     "occupant 只存在本机 config，不会进入 query/snapshot/dashboard 输出")
            renamed = []
            for item in raw_rooms:
                if not isinstance(item, dict):
                    continue
                canonical = canonical_room(str(item.get("roomverify") or ""))
                given = str(item.get("label") or "").strip()
                if canonical and given and given != canonical["label"]:
                    renamed.append("%s→%s" % (given, canonical["label"]))
            if renamed:
                _add(out, "warn", "rooms",
                     "rooms 里有 %d 个 label 不是规范名，输出已统一为规范名"
                     "（建议同步 config）：%s"
                     % (len(renamed), "、".join(renamed[:4])))

    active = cfg_active_room(cfg)
    if active is None:
        _add(out, "fail", "room.roomverify",
             "没有可查的房间：填 room.roomverify，或用 rooms[] + default_room"
             "（run.bat rooms --building 楼栋 --room 房间号 查 roomverify）")
    else:
        _add(out, "ok", "room.roomverify",
             "默认房间 = %s（%s）" % (active["label"], active["roomverify"]))
        if parse_roomverify(active["roomverify"]) is None:
            _add(out, "warn", "room.roomverify",
                 "roomverify 格式不像 FJTCM 的 areaid-楼栋---房间"
                 "（例 1-13---324 / 4-23B---423），请再确认")
    default_room = str(cfg.get("default_room") or "").strip()
    if default_room and active is not None:
        matched = (default_room in (active["roomverify"], active["label"],
                                    active.get("raw_label") or "")
                   or _room_matches(active, default_room))
        if not matched:
            _add(out, "warn", "default_room",
                 "default_room=%r 没匹配到任何房间，已退回 %r"
                 % (default_room, active["label"]))

    try:
        threshold = float(cfg.get("threshold_low", 10))
    except (TypeError, ValueError):
        _add(out, "fail", "threshold_low", "threshold_low 必须是数字（默认 10 度）")
        threshold = 10.0
    else:
        if threshold < 0 or threshold > 100000:
            _add(out, "fail", "threshold_low", "threshold_low=%g 不合理（建议 5~30 度）" % threshold)
        else:
            _add(out, "ok", "threshold_low", "低电量阈值 = %g" % threshold)

    try:
        interval = float(cfg.get("low_alert_interval_hours", 3))
        if interval < 0.5 or interval > 168:
            _add(out, "warn", "low_alert_interval_hours",
                 "low_alert_interval_hours=%g 不太合理，建议 1~24" % interval)
    except (TypeError, ValueError):
        _add(out, "warn", "low_alert_interval_hours", "low_alert_interval_hours 不是数字，将用默认 3 小时")

    if backend == "cloudpay":
        idserial = str(cfg.get("idserial") or "").strip()
        if is_placeholder_text(idserial):
            _add(out, "fail", "idserial", "idserial 未填：填你的学号（完美校园绑定的那个）")
        elif idserial.isdigit() and len(idserial) >= 4:
            _add(out, "ok", "idserial", "idserial 已填（%d 位学号）" % len(idserial))
        else:
            _add(out, "warn", "idserial", "idserial 看起来不是纯数字学号（%d 字符），请确认" % len(idserial))

        payproid = str(cfg.get("payproid") or "").strip()
        proj_name = str(((cfg.get("payPro") or {}).get("electric") or {}).get("name") or "").strip()
        if payproid and not is_placeholder_text(payproid):
            _add(out, "ok", "payproid", "payproid = %s（FJTCM 旗山用电支出 = 2122）" % payproid)
        elif proj_name and not is_placeholder_text(proj_name):
            _add(out, "warn", "payproid", "payproid 未填，将按项目名 %r 自动匹配（建议显式填）" % proj_name)
        else:
            _add(out, "fail", "payproid",
                 "payproid 未填：运行 projects 查缴费项目，FJTCM 旗山用电支出 = 2122")
    else:
        phone = str(cfg.get("phone") or "").strip()
        password = str(cfg.get("password") or "").strip()
        if is_placeholder_text(phone):
            _add(out, "fail", "phone", "backend=wanxiao 需要完美校园登录手机号")
        elif re.fullmatch(r"1\d{10}", phone):
            _add(out, "ok", "phone", "手机号已填（%s）" % mask_phone(phone))
        else:
            _add(out, "warn", "phone", "手机号不是 11 位大陆号码，请确认")
        if is_placeholder_text(password):
            _add(out, "fail", "password", "backend=wanxiao 需要完美校园登录密码")
        else:
            _add(out, "ok", "password", "密码已填（长度 %d，不显示）" % len(password))
        _add(out, "info", "wanxiao", "首次在新设备登录会要求短信验证码，绑定 deviceId 后免验证")
    return out


def has_cloudpay_config(cfg):
    """cloudpay 免登录主链路所需字段是否齐。"""
    if not isinstance(cfg, dict):
        return False
    return all(not is_placeholder_text(cfg.get(k))
               for k in ("schoolcode", "idserial"))
