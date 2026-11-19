# -*- coding: utf-8 -*-
"""班级小管家（banjixiaoguanjia.com）英语作业抓取 —— briefdesk 作业自动识别扩展。

数据源（2026-11-06 用 CDP 实抓确认，列表页只读，不点详情，不产生已读回执）:

    GET https://b.welife001.com/info/getParent
        ?members=<member_id>&type=-1&date=-1&page=N&size=50&isRecent=false

    请求头（缺一不可）:
        authorization: <本机登录 token，明文 JWT，不带 Bearer>
        app-info:      1/3.12.4/1082            # 平台/版本/构建号，取自页面 window.xgjWebBuildInfo
        other-info:    <毫秒时间戳>/<md5("bjxgj@!" + base64(毫秒时间戳))>
        content-type:  application/json; charset=utf-8

    type=-1 全部；type=0 作业（subject=英语）；type=8 练习/测验（subject=选择科目）。
    返回项字段：_id / title / subject / text_content / end_day / create_at / update_at /
               is_feedback（本人已提交）/ creator_name / atype。

用法（PowerShell，建议用 G:\\ClassTools\\briefdesk\\venv\\Scripts\\python.exe）:

    python xgj_homework.py --status                 # 看 token / 上次采集状态
    python xgj_homework.py --refresh                # 检查 token；失效时打开 Edge 等扫码
    python xgj_homework.py --collect                # 拉英语作业 -> data\\xgj-homework.json
    python xgj_homework.py --merge                  # 未完成英语作业并入 data\\auto-homework.json
    python xgj_homework.py --collect --merge        # 采集 + 合并（定时任务用这一条）
    python xgj_homework.py --collect --merge --dry-run

设计约束：
  * token 只写 secrets\\xjg-token.json（本机，不进仓库/日志/聊天），任何输出都做脱敏；
  * 失败不动已有 data 文件，只更新 data\\xjg-collect-status.json；
  * key = xgj_en_<作业id>，subject = 英语1，幂等：内容不变不重写文件；
  * 只并「未完成且未过期」的英语作业，不覆盖其他来源（math/doc/sizheng）的行；
  * 不写云端、不下载附件、不打开详情页。
"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # Windows 控制台默认 GBK，中文会乱码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

try:
    import websocket  # websocket-client：仅 CDP 读取登录态用
except Exception:  # noqa: BLE001
    websocket = None

# ----------------------------------------------------------------------------- 配置
DATA = Path(r"G:\ClassTools\briefdesk\data")
LOGS = Path(r"G:\ClassTools\briefdesk\logs")
SECRETS = Path(r"G:\ClassTools\briefdesk\secrets")

OUT = DATA / "xgj-homework.json"           # 归一化后的英语作业
STATUS = DATA / "xgj-collect-status.json"  # 最近一次采集状态
AUTO = DATA / "auto-homework.json"         # 站点作业栏数据源（本地）
SECRET = SECRETS / "xjg-token.json"        # token 持久化（凭据，勿外传）
LOG = LOGS / "xgj-homework.log"

PROFILE = str(DATA / "xjg_profile")
CDP_PORT = 9333
CDP_BASE = "http://127.0.0.1:%d" % CDP_PORT
APP_HOST = "https://service.banjixiaoguanjia.com"
APP_URL = APP_HOST + "/appweb/?page=open"
API_BASE = "https://b.welife001.com"
APP_INFO = "1/3.12.4/1082"     # 页面 window.xgjWebBuildInfo：app/3.12.4/1082
SALT = "bjxgj@!"
SUBJECT = "英语1"
KEY_PREFIX = "xgj_en_"
SOURCE = "班级小管家 · 英语作业"
AUTHOR = "自动识别 · 英语"

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# 英语判定：科目/标题/正文命中关键词，或本班英语老师发布；显式其它科目则排除
NON_EN_KEYWORDS = ("数学", "语文", "物理", "化学", "生物", "历史", "地理", "政治", "思政",
                   "计算机", "体育", "音乐", "美术", "军事", "心理")
EN_KEYWORDS = ("英语", "English", "english", "unit", "Unit", "UNIT", "四级", "六级",
               "单词", "语法", "听力", "阅读", "作文", "翻译", "预习", "测验", "练习")
EN_TEACHERS = ("花爱阳",)

CN_TZ = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0")


class XgjError(RuntimeError):
    """可读的失败（消息里不得含 token）。"""


# ----------------------------------------------------------------------------- 日志
def log(msg):
    line = "[%s] %s" % (datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass
    print(msg, flush=True)


# ----------------------------------------------------------------------------- 工具
def now_cn():
    return datetime.now(CN_TZ)


def iso(dt):
    return dt.astimezone(CN_TZ).replace(microsecond=0).isoformat()


def json_dump(obj, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def json_load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def other_info(ts_ms=None):
    """页面里 other-info 的算法：ts + '/' + md5('bjxgj@!' + base64(ts))。"""
    ts = str(ts_ms if ts_ms is not None else int(time.time() * 1000))
    inner = base64.b64encode(ts.encode("ascii")).decode("ascii")
    return ts + "/" + hashlib.md5((SALT + inner).encode("utf-8")).hexdigest()


def parse_end_day(text):
    """'2026-11-3 14:30' / '2026-10-28 17:20' -> aware datetime(+08:00)，无时间按 23:59。"""
    if not text:
        return None
    m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", str(text))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4)) if m.group(4) else 23
    mm = int(m.group(5)) if m.group(5) else 59
    try:
        return datetime(y, mo, d, hh, mm, tzinfo=CN_TZ)
    except ValueError:
        return None


def parse_iso_local(text):
    """'2026-10-28T08:33:19.780Z' -> aware datetime(+08:00)。"""
    if not text:
        return None
    s = str(text).strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(CN_TZ)
    except ValueError:
        return None


def token_exp_ms(token):
    """读 JWT exp（该站 exp 是毫秒）。只用于展示/判断，不输出 token。"""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(part.encode("ascii")))
        exp = int(payload.get("exp") or 0)
        if exp > 10 ** 12:  # 毫秒
            return exp
        return exp * 1000
    except Exception:  # noqa: BLE001
        return 0


# ----------------------------------------------------------------------------- API
def api_get(path, params, token, timeout=25):
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET", headers={
        "authorization": token,
        "app-info": APP_INFO,
        "other-info": other_info(),
        "content-type": "application/json; charset=utf-8",
        "origin": APP_HOST,
        "referer": APP_HOST + "/",
        "accept": "*/*",
        "user-agent": UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            status = r.status
            headers = dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
        headers = dict(e.headers)
    except Exception as e:  # noqa: BLE001
        raise XgjError("网络失败：%s" % e)
    if status == 403 and headers.get("invalid-token") == "true":
        raise XgjError("token 已失效（invalid-token）")
    try:
        obj = json.loads(raw)
    except ValueError:
        raise XgjError("接口返回非 JSON（HTTP %s）" % status)
    if status != 200:
        raise XgjError("接口 HTTP %s：%s" % (status, str(obj)[:120]))
    if obj.get("code") not in (0, None):
        raise XgjError("接口 code=%s msg=%s" % (obj.get("code"), obj.get("msg")))
    return obj


def validate_token(token, member_id):
    obj = api_get("/info/getParent", {
        "members": member_id, "type": "-1", "date": "-1",
        "page": "0", "size": "1", "isRecent": "false",
    }, token)
    return isinstance(obj.get("data"), list)


# ----------------------------------------------------------------------------- 浏览器 / 登录态
def cdp_targets():
    try:
        with urllib.request.urlopen(CDP_BASE + "/json/list", timeout=3) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def find_xgj_tab(targets):
    for t in targets or []:
        if t.get("type") == "page" and "banjixiaoguanjia.com/appweb" in (t.get("url") or ""):
            return t
    return None


class CDP:
    def __init__(self, ws_url, timeout=20):
        if websocket is None:
            raise XgjError("缺少 websocket-client，无法读取浏览器登录态")
        self.ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
        self._id = 0

    def call(self, method, params=None, timeout=20):
        self._id += 1
        msg_id = self._id
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:  # noqa: BLE001
                break
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise XgjError("CDP %s 失败：%s" % (method, str(msg["error"])[:160]))
                return msg.get("result") or {}
        raise XgjError("CDP %s 超时" % method)

    def eval(self, expression, timeout=20):
        res = self.call("Runtime.evaluate",
                        {"expression": expression, "returnByValue": True, "awaitPromise": True},
                        timeout=timeout)
        if res.get("exceptionDetails"):
            raise XgjError("页面脚本异常：%s" % str(res["exceptionDetails"])[:160])
        return (res.get("result") or {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


READ_AUTH_JS = r"""(function(){
  try{
    var k = Object.keys(localStorage).find(function(x){return x.indexOf('flutter.selected_user_role_info_')===0;});
    var role = {};
    if (k) {
      role = JSON.parse(localStorage.getItem(k) || '{}');
      if (typeof role === 'string') role = JSON.parse(role);
    }
    var raw = localStorage.getItem('flutter.token') || '';
    var tok = raw;
    try { tok = JSON.parse(raw); } catch(e) {}
    if (typeof tok !== 'string') tok = '';
    return JSON.stringify({
      token: tok,
      member_id: (role.memberIds && role.memberIds[0]) || role.member_id || '',
      cid: role.cid || '',
      roleType: role.roleType || '',
      href: location.href.replace(/(token=)[^&]+/, '$1<REDACTED>')
    });
  }catch(e){ return JSON.stringify({_error:String(e)}); }
})()"""


def read_browser_auth():
    """从已登录的 Edge（CDP 9333）读 token / member_id；失败返回 None。"""
    targets = cdp_targets()
    if not targets:
        return None
    tab = find_xgj_tab(targets)
    if not tab:
        return None
    cdp = None
    try:
        cdp = CDP(tab["webSocketDebuggerUrl"])
        info = json.loads(cdp.eval(READ_AUTH_JS) or "{}")
    except Exception:  # noqa: BLE001
        return None
    finally:
        if cdp:
            cdp.close()
    if info.get("_error") or not info.get("token") or not info.get("member_id"):
        return None
    return info


def ensure_browser(timeout=90):
    """CDP 未启动时用专用 profile 拉起 Edge（不杀已有 Edge，不碰微信）。"""
    if cdp_targets():
        return True
    edge = next((p for p in EDGE_CANDIDATES if Path(p).exists()), None)
    if not edge:
        raise XgjError("找不到 msedge.exe，无法打开班级小管家")
    Path(PROFILE).mkdir(parents=True, exist_ok=True)
    args = [edge, "--remote-debugging-port=%d" % CDP_PORT,
            "--user-data-dir=" + PROFILE, "--no-first-run", "--no-default-browser-check",
            APP_URL]
    try:
        subprocess.Popen(args, close_fds=True,
                         creationflags=0x00000008 if os.name == "nt" else 0)  # DETACHED_PROCESS
    except Exception as e:  # noqa: BLE001
        raise XgjError("启动 Edge 失败：%s" % e)
    end = time.time() + timeout
    while time.time() < end:
        if cdp_targets():
            return True
        time.sleep(1.5)
    return False


def open_login_tab():
    """确保有一个班级小管家标签页；没有就新建/导航。"""
    targets = cdp_targets() or []
    tab = find_xgj_tab(targets)
    if tab:
        return tab
    # 新建标签页（Chrome DevTools HTTP API）
    try:
        req = urllib.request.Request(CDP_BASE + "/json/new?" + urllib.parse.quote(APP_URL, safe=""), method="PUT")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        pass
    # 退而求其次：用 about:blank 标签导航
    for t in targets:
        if t.get("type") == "page":
            cdp = CDP(t["webSocketDebuggerUrl"])
            try:
                cdp.call("Page.enable")
                cdp.call("Page.navigate", {"url": APP_URL})
            finally:
                cdp.close()
            return t
    return None


def login_flow(wait_seconds=300):
    """检查 token；失效时打开 Edge 等待扫码，成功后保存到 secrets。"""
    log("[登录] 检查现有登录态…")
    info = read_browser_auth()
    if info:
        try:
            if validate_token(info["token"], info["member_id"]):
                save_secret(info["token"], info["member_id"], info.get("cid", ""))
                log("[登录] token 有效，已保存（有效期至 %s）" % exp_text(info["token"]))
                return 0
        except XgjError as e:
            log("[登录] 页面 token 不可用：%s" % e)

    sec = load_secret()
    if sec and sec.get("token") and sec.get("member_id"):
        try:
            if validate_token(sec["token"], sec["member_id"]):
                log("[登录] secrets 里的 token 有效（有效期至 %s）" % exp_text(sec["token"]))
                return 0
        except XgjError as e:
            log("[登录] secrets token 已失效：%s" % e)

    log("[登录] 需要扫码：正在打开班级小管家…")
    if not ensure_browser():
        raise XgjError("Edge 调试端口 %d 未就绪；请手动启动带 --remote-debugging-port 的 Edge" % CDP_PORT)
    open_login_tab()
    log("[登录] 请在弹出的 Edge 窗口完成登录（微信扫码/确认）；等待中（最多 %d 秒）…" % wait_seconds)
    end = time.time() + wait_seconds
    last = None
    while time.time() < end:
        time.sleep(5)
        info = read_browser_auth()
        if not info:
            if int(time.time() - (end - wait_seconds)) % 30 < 5:
                log("[登录] 尚未检测到登录 token，继续等待…")
            continue
        if last != info["token"]:
            last = info["token"]
        try:
            if validate_token(info["token"], info["member_id"]):
                save_secret(info["token"], info["member_id"], info.get("cid", ""))
                log("[登录] 登录成功，token 已保存（有效期至 %s）" % exp_text(info["token"]))
                return 0
        except XgjError:
            pass
    raise XgjError("等待扫码超时（%d 秒），请重试 --refresh" % wait_seconds)


# ----------------------------------------------------------------------------- secrets
def load_secret():
    try:
        obj = json_load(SECRET)
        if isinstance(obj, dict) and obj.get("token"):
            return obj
    except Exception:  # noqa: BLE001
        pass
    return None


def save_secret(token, member_id, cid=""):
    old = load_secret()
    if old and old.get("token") == token and old.get("member_id") == member_id:
        return  # 未变化不重写
    SECRETS.mkdir(parents=True, exist_ok=True)
    exp = token_exp_ms(token)
    json_dump({
        "token": token,
        "exp": exp,
        "exp_text": datetime.fromtimestamp(exp / 1000, CN_TZ).isoformat() if exp else "",
        "member_id": member_id,
        "cid": cid,
        "saved_at": iso(now_cn()),
        "note": "班级小管家 appweb 登录 token；仅本机使用，勿提交/外传",
    }, SECRET)


def exp_text(token):
    exp = token_exp_ms(token)
    return datetime.fromtimestamp(exp / 1000, CN_TZ).strftime("%Y-%m-%d %H:%M") if exp else "未知"


# ----------------------------------------------------------------------------- 采集
def normalize(item, now=None):
    """接口 item -> 统一作业结构（只保留英语作业字段）。"""
    now = now or now_cn()
    iid = str(item.get("_id") or "")
    title = (item.get("title") or "").strip()
    text = (item.get("text_content") or "").strip()
    subject_raw = (item.get("subject") or "").strip()
    teacher = (item.get("creator_name") or item.get("creator_wx_name") or "").strip()

    end_dt = parse_end_day(item.get("end_day"))
    created = parse_iso_local(item.get("create_at"))
    updated = parse_iso_local(item.get("update_at"))
    submitted = bool(item.get("is_feedback"))

    end_ts = int(end_dt.timestamp() * 1000) if end_dt else 0
    ts = int(created.timestamp() * 1000) if created else int(now.timestamp() * 1000)

    if submitted:
        status = "已提交"
    elif end_dt and end_dt < now:
        status = "已截止"
    else:
        status = "未完成"

    content = title
    if text and text != title:
        content = "%s：%s" % (title, text)
    content = re.sub(r"\s+", " ", content)[:400]

    raw_type = item.get("type")
    kind = "homework" if raw_type == 0 else ("practice" if raw_type == 8 else "other")

    return {
        "key": KEY_PREFIX + iid,
        "item_id": iid,
        "subject": SUBJECT,
        "title": title,
        "content": content,
        "due": end_dt.strftime("%m-%d %H:%M") if end_dt else "",
        "date": end_dt.strftime("%Y-%m-%d") if end_dt else "",
        "time": end_dt.strftime("%H:%M") if end_dt else "",
        "end_day": (item.get("end_day") or "").strip(),
        "end_ts": end_ts,
        "status": status,
        "submitted": submitted,
        "kind": kind,
        "raw_type": raw_type,
        "raw_subject": subject_raw,
        "teacher": teacher,
        "created_at": iso(created) if created else "",
        "updated_at": iso(updated) if updated else "",
        "ts": ts,
        "author": AUTHOR,
        "source": SOURCE,
    }


def is_english(item):
    subject = (item.get("subject") or "").strip()
    title = (item.get("title") or "").strip()
    text = (item.get("text_content") or "").strip()
    teacher = (item.get("creator_name") or "").strip()
    head = subject + " " + title
    if any(k in subject for k in ("英语", "English", "english")):
        return True
    if any(k in head for k in NON_EN_KEYWORDS):
        return False
    body = " ".join((subject, title, text))
    if any(k in body for k in EN_KEYWORDS):
        return True
    if teacher and any(t and t in teacher for t in EN_TEACHERS):
        return True
    return False


def fetch_feed(token, member_id, size=50, max_pages=20):
    items, seen = [], set()
    for page in range(max_pages):
        obj = api_get("/info/getParent", {
            "members": member_id, "type": "-1", "date": "-1",
            "page": str(page), "size": str(size), "isRecent": "false",
        }, token)
        data = obj.get("data") or []
        if not data:
            break
        for it in data:
            iid = it.get("_id")
            if iid and iid not in seen:
                seen.add(iid)
                items.append(it)
        if len(data) < size:
            break
        time.sleep(0.3)
    return items


def resolve_auth():
    """优先浏览器实时 token，其次 secrets；返回 (token, member_id, cid)。"""
    info = read_browser_auth()
    if info:
        try:
            if validate_token(info["token"], info["member_id"]):
                save_secret(info["token"], info["member_id"], info.get("cid", ""))
                return info["token"], info["member_id"], info.get("cid", "")
        except XgjError:
            pass
    sec = load_secret()
    if sec and sec.get("token") and sec.get("member_id"):
        try:
            if validate_token(sec["token"], sec["member_id"]):
                return sec["token"], sec["member_id"], sec.get("cid", "")
        except XgjError:
            pass
    raise XgjError("没有可用登录态，请先运行：python xgj_homework.py --refresh")


def collect(dry_run=False):
    token, member_id, cid = resolve_auth()
    log("[采集] 登录态有效（有效期至 %s），拉取列表…" % exp_text(token))
    raw_items = fetch_feed(token, member_id)
    log("[采集] 列表共 %d 条（含作业/练习）" % len(raw_items))

    english = [it for it in raw_items if is_english(it)]
    rows = [normalize(it) for it in english]
    rows.sort(key=lambda r: (r.get("ts") or 0), reverse=True)

    classes = {it.get("class_name") for it in raw_items if it.get("class_name")}
    pending = [r for r in rows if r["status"] == "未完成"]
    payload = {
        "generatedAt": iso(now_cn()),
        "source": "班级小管家 info/getParent",
        "class_name": (sorted(classes)[0] if classes else ""),
        "count": len(rows),
        "pending": len(pending),
        "items": rows,
    }

    log("[采集] 英语作业 %d 条，未完成 %d 条" % (len(rows), len(pending)))
    for r in rows[:12]:
        log("  - [%s] %s | 截止 %s | %s" % (r["status"], r["title"] or r["content"][:30],
                                            r["due"] or "无", r["kind"]))

    if dry_run:
        log("[采集] --dry-run：不写 %s" % OUT)
        return payload

    same = False
    try:
        old = json_load(OUT)
        same = old.get("items") == rows
    except Exception:  # noqa: BLE001
        same = False
    if same:
        log("[采集] 内容未变化，跳过写盘（幂等）")
    else:
        json_dump(payload, OUT)
        log("[采集] 已写 %s" % OUT)

    write_status({"ok": True, "count": len(rows), "pending": len(pending), "error": None})
    return payload


def write_status(extra):
    obj = {"at": iso(now_cn()), "source": "xgj"}
    obj.update(extra)
    try:
        json_dump(obj, STATUS)
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------------------- 合并
def merge_row(r):
    return {
        "key": r["key"],
        "subject": r["subject"],
        "content": r["content"],
        "due": r["due"],
        "date": r["date"],
        "time": r["time"],
        "author": r["author"],
        "ts": r["ts"],
        "source": r["source"],
        "status": r["status"],
        "submitted": r["submitted"],
        "kind": r["kind"],
    }


def merge_into_auto(payload=None, dry_run=False, include_done=False):
    if payload is None:
        if not OUT.exists():
            raise XgjError("还没有采集结果，请先运行 --collect")
        payload = json_load(OUT)
    items = payload.get("items") or []
    now = now_cn()

    picked = [it for it in items
              if include_done or (it.get("status") == "未完成"
                                  and (not it.get("end_ts") or it["end_ts"] > int(now.timestamp() * 1000)))]
    picked.sort(key=lambda x: (x.get("ts") or 0))
    new_rows = [merge_row(it) for it in picked]

    data = {"generatedAt": iso(now), "count": 0, "rows": []}
    if AUTO.exists():
        try:
            data = json_load(AUTO)
        except Exception as e:  # noqa: BLE001
            raise XgjError("读取 auto-homework.json 失败：%s" % e)
    old_rows = data.get("rows") or []
    kept = [r for r in old_rows if not str(r.get("key") or "").startswith(KEY_PREFIX)]

    # 冲突：同 key 时更新时间新者胜（xgj 行自己去重后不会重复）
    by_key = {str(r.get("key")): r for r in kept}
    merged = list(kept)
    for row in new_rows:
        old = by_key.get(row["key"])
        if old is None:
            merged.append(row)
        elif int(row.get("ts") or 0) >= int(old.get("ts") or 0):
            merged[merged.index(old)] = row
            log("[合并] 同 key 冲突，新者胜：%s" % row["key"])

    changed = merged != old_rows
    log("[合并] 本次待并入 %d 条（未完成%s）；原文件 %d 条，xgj 旧行 %d 条"
        % (len(new_rows), "/含已完成" if include_done else "", len(old_rows), len(old_rows) - len(kept)))
    for r in new_rows:
        log("  + %s | %s | 截止 %s" % (r["key"], r["content"][:40], r["due"] or "无"))

    if not changed:
        log("[合并] 内容未变化，跳过写盘（幂等）")
        return data
    if dry_run:
        log("[合并] --dry-run：不写 %s" % AUTO)
        return {"generatedAt": iso(now), "count": len(merged), "rows": merged}

    data["rows"] = merged
    data["count"] = len(merged)
    data["generatedAt"] = iso(now)
    json_dump(data, AUTO)
    log("[合并] 已写 %s（%d 条）" % (AUTO, len(merged)))
    return data


# ----------------------------------------------------------------------------- 状态 / 入口
def print_status():
    sec = load_secret()
    if sec:
        remaining = int((sec.get("exp") or 0) / 1000 - time.time())
        log("[状态] secrets token：%s（剩余 %d 天，member_id 长度 %d）"
            % (sec.get("exp_text") or exp_text(sec.get("token", "")),
               max(0, remaining // 86400), len(sec.get("member_id") or "")))
    else:
        log("[状态] secrets 无 token")
    info = read_browser_auth()
    log("[状态] Edge CDP %s" % ("可用" if cdp_targets() else "不可用"))
    if info:
        try:
            validate_token(info["token"], info["member_id"])
            log("[状态] 浏览器登录态有效（有效期至 %s）" % exp_text(info["token"]))
        except XgjError as e:
            log("[状态] 浏览器 token 无效：%s" % e)
    try:
        st = json_load(STATUS)
        log("[状态] 上次采集：%s ok=%s count=%s pending=%s" %
            (st.get("at"), st.get("ok"), st.get("count"), st.get("pending")))
    except Exception:  # noqa: BLE001
        log("[状态] 尚无采集记录")
    try:
        p = json_load(OUT)
        log("[状态] 本地结果：%d 条（pending %s），generatedAt %s"
            % (p.get("count", 0), p.get("pending", 0), p.get("generatedAt")))
    except Exception:  # noqa: BLE001
        log("[状态] 尚无 data/xgj-homework.json")


def main(argv=None):
    ap = argparse.ArgumentParser(description="班级小管家英语作业抓取（briefdesk）")
    ap.add_argument("--collect", action="store_true", help="拉取英语作业到 data/xgj-homework.json")
    ap.add_argument("--merge", action="store_true", help="把未完成英语作业并入 data/auto-homework.json")
    ap.add_argument("--refresh", "--login", dest="login", action="store_true",
                    help="检查 token；失效时打开 Edge 等待扫码")
    ap.add_argument("--status", action="store_true", help="显示登录态与上次采集状态")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    ap.add_argument("--include-done", action="store_true",
                    help="合并时也包含已提交/已截止（默认只并未完成，测试用）")
    args = ap.parse_args(argv)

    if not any((args.collect, args.merge, args.login, args.status)):
        ap.print_help()
        print_status()
        return 0

    rc = 0
    try:
        if args.login:
            rc = login_flow()
        if args.collect or args.merge:
            payload = None
            if args.collect:
                payload = collect(dry_run=args.dry_run)
            if args.merge:
                merge_into_auto(payload=payload, dry_run=args.dry_run,
                                include_done=args.include_done)
        if args.status and not (args.collect or args.merge or args.login):
            print_status()
    except XgjError as e:
        log("[失败] %s" % e)
        write_status({"ok": False, "error": str(e)[:300]})
        rc = 2 if "token" in str(e) or "登录" in str(e) else 1
    except Exception as e:  # noqa: BLE001
        log("[失败] 未预期错误：%r" % e)
        log(traceback.format_exc()[:1200])
        write_status({"ok": False, "error": repr(e)[:300]})
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
