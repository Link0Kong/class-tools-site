#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""同步班级 17 间宿舍的剩余电量到 CloudBase public.power。

数据链路（免登录，2026-11-05 实测）：
  POST https://cloudpaygateway.59wanmei.com:8087/paygateway/smallpaygateway/trade
  body: {"method":"samllProgramGetRoomState",
         "bizcontent":"{\"payproid\":\"2122\",\"schoolcode\":\"769\",
                       \"roomverify\":\"4-23A---321\",\"businesstype\":\"2\"}",
         "timestamp":"yyyy-MM-dd HH:mm:ss","sourceId":2}
  → businessData.quantity / quantityunit

权限：读取 public.power 需有效班级 token；写入仅管理员 token。
      token 走 web/tools/index.html 的 var CB / var CBK + rpc/class_verify，
      缓存于 G:\ClassTools\briefdesk\secrets\class-token.json（仅本机）。

隐私：任何输出/日志都不含姓名、学号、手机号；本表只有楼栋/房间号/电量/时间。

每次成功写 power 后追加一条 power_history 采样（页面趋势/指标用）；历史保留 30 天。
日志：G:\ClassTools\briefdesk\logs\power-sync.log（超过 1MB 轮转为 .1）
用法：
  python  sync_power_cloud.py               # 正常同步一次（写 power + power_history）
  pythonw sync_power_cloud.py               # 计划任务（无窗口）
  python  sync_power_cloud.py --dry-run     # 只查网关，不写云端
  python  sync_power_cloud.py --limit 2     # 只查前 N 间（自检用）
  python  sync_power_cloud.py --backfill-log  # 解析日志回填 power_history（去重，可重复跑）
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------- 路径 / 常量 ----------------
INDEX = Path(r"G:\ClassTools\web\tools\index.html")
TOKEN_FILE = Path(r"G:\ClassTools\briefdesk\secrets\class-token.json")
LOG_FILE = Path(r"G:\ClassTools\briefdesk\logs\power-sync.log")
LOG_MAX_BYTES = 1024 * 1024

try:  # 后端基址/匿名 key 统一入口（默认仍解析 index.html → CloudBase，行为不变）
    import cloud_backend  # noqa: WPS433（同目录模块）
except ImportError:  # pragma: no cover - 同目录文件缺失时保底走旧解析
    cloud_backend = None

GATEWAY = "https://cloudpaygateway.59wanmei.com:8087/paygateway/smallpaygateway/trade"
ORIGIN = "https://cloudpaygateway.59wanmei.com:8087"
REFERER = ORIGIN + "/pay/index.html"
SCHOOLCODE = "769"
PAYPROID = "2122"
BUSINESSTYPE = "2"
LOW_THRESHOLD = 30.0  # < 30 度视为低电（与前端标红阈值一致）
LOCAL_TZ = timezone(timedelta(hours=8))
RETRY_TIMES = 3

# 班级 17 间宿舍：(label, building, room, roomverify)
# 规范化命名（2026-11-05 v2 全链路统一）：{楼号}号楼{座}{房间号}；23 号楼用「23号楼A座 / 23号楼B座」。
# 来源：26信管舍长群成员昵称 + 2026-11-05 逐个实测（不含姓名，也不要加姓名）。
# 云端主键 id = roomverify（稳定），label/building 只作展示；增删宿舍只改这里 + 跑一次同步。
ROOMS = [
    ("13号楼324", "13号楼", "324", "1-13---324"),
    ("13号楼308", "13号楼", "308", "1-13---308"),
    ("16号楼305", "16号楼", "305", "1-16---305"),
    ("16号楼306", "16号楼", "306", "1-16---306"),
    ("23号楼A座321", "23号楼A座", "321", "4-23A---321"),
    ("23号楼A座323", "23号楼A座", "323", "4-23A---323"),
    ("23号楼A座324", "23号楼A座", "324", "4-23A---324"),
    ("23号楼A座325", "23号楼A座", "325", "4-23A---325"),
    ("23号楼A座326", "23号楼A座", "326", "4-23A---326"),
    ("23号楼A座327", "23号楼A座", "327", "4-23A---327"),
    ("23号楼A座328", "23号楼A座", "328", "4-23A---328"),
    ("23号楼A座329", "23号楼A座", "329", "4-23A---329"),
    ("23号楼A座330", "23号楼A座", "330", "4-23A---330"),
    ("23号楼B座422", "23号楼B座", "422", "4-23B---422"),
    ("23号楼B座423", "23号楼B座", "423", "4-23B---423"),
    ("23号楼B座424", "23号楼B座", "424", "4-23B---424"),
    ("23号楼B座425", "23号楼B座", "425", "4-23B---425"),
]

# class_verify 用的管理员身份（仅在本地进程内使用，绝不打印/写日志）
ADMIN_SID = "3260707024"
ADMIN_NAME = "\u9648\u5b50\u9e92"  # 姓名常量按 unicode 转义存放，避免误打印

# ---------------- 历史采样（public.power_history）----------------
HISTORY_TABLE = "power_history"
HISTORY_KEEP_DAYS = 30   # 只保留最近 30 天，避免表无限增长
HISTORY_BATCH = 50       # PostgREST 批量插入大小
LOG_OK_NEW_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+OK\s+(.+?)\s+\[([^\]]+)\]\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*(度?)")
LOG_OK_OLD_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+OK\s+(.+?)\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*(度?)")


def room_aliases():
    """label / 旧 label → roomverify（旧日志里的 23A-321 这类旧命名也能回填）。"""
    out = {}
    for label, building, room, rv in ROOMS:
        out[label] = rv
        if building == "23号楼A座":
            out["23A-" + room] = rv
        elif building == "23号楼B座":
            out["23B-" + room] = rv
    return out


# ---------------- 日志 ----------------
class Logger:
    def __init__(self, path, echo=True):
        self.path = Path(path)
        self.echo = bool(echo and sys.stdout is not None)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate()
        except OSError:
            pass

    def _rotate(self):
        try:
            if self.path.exists() and self.path.stat().st_size > LOG_MAX_BYTES:
                old = self.path.with_name(self.path.name + ".1")
                try:
                    if old.exists():
                        old.unlink()
                except OSError:
                    pass
                self.path.replace(old)
        except OSError:
            pass

    def __call__(self, msg):
        line = "[%s] %s" % (datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"), msg)
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        if self.echo:
            try:
                print(line, flush=True)
            except Exception:
                pass


# ---------------- HTTP ----------------
class GatewayError(Exception):
    pass


def gateway_room(roomverify, timeout=20.0):
    """查一间房的剩余电量，返回 (quantity: float, unit: str)。"""
    biz = {
        "payproid": PAYPROID,
        "schoolcode": SCHOOLCODE,
        "roomverify": roomverify,
        "businesstype": BUSINESSTYPE,
    }
    body = {
        "method": "samllProgramGetRoomState",
        "bizcontent": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
        "timestamp": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "sourceId": 2,
    }
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        GATEWAY,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Origin": ORIGIN,
            "Referer": REFERER,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) sync_power_cloud",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        d = json.loads(raw)
    except ValueError:
        raise GatewayError("bad json: %s" % raw[:120])
    code = str(d.get("returncode") or "")
    if code != "SUCCESS":
        raise GatewayError("returncode=%s msg=%s" % (code, str(d.get("returnmsg"))[:80]))
    bd = d.get("businessData") or {}
    q = bd.get("quantity")
    if q is None or str(q).strip() == "":
        raise GatewayError("empty quantity (description=%s)" % str(bd.get("description"))[:40])
    try:
        quantity = float(q)
    except (TypeError, ValueError):
        raise GatewayError("bad quantity: %r" % (q,))
    unit = str(bd.get("quantityunit") or "度")
    return quantity, unit


def fetch_with_retry(label, roomverify, log, timeout):
    last = None
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            return gateway_room(roomverify, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, GatewayError) as e:
            last = e
            if attempt < RETRY_TIMES:
                wait = 2.0 * attempt
                log("  retry %s (%d/%d): %s" % (label, attempt, RETRY_TIMES, str(e)[:100]))
                time.sleep(wait)
    raise GatewayError(str(last)[:160])


# ---------------- CloudBase PostgREST ----------------
def cb_config():
    """PostgREST 基址/匿名 key（默认 index.html → CloudBase；CLASS_CB_BASE/KEY 可覆盖）。"""
    if cloud_backend is not None:
        return cloud_backend.resolve(INDEX)
    s = INDEX.read_text(encoding="utf-8")
    base = re.search(r'var CB="([^"]+)"', s).group(1)
    key = re.search(r'var CBK="([^"]+)"', s).group(1)
    return base, key


def cb_request(base, key, path, body=None, method="GET", token=None):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if token:
        headers["X-Device-Id"] = token
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def get_token(base, key, log, force=False):
    """管理员班级 token：优先读本机缓存，过期/强制时重新 class_verify。不打印 token。"""
    if not force:
        try:
            obj = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            if obj.get("token") and float(obj.get("exp", 0)) > time.time() + 3600:
                return obj["token"]
        except (OSError, ValueError):
            pass
    st, out = cb_request(
        base,
        key,
        "rpc/class_verify",
        {"p_sid": ADMIN_SID, "p_name": ADMIN_NAME},
        "POST",
    )
    if st != 200 or not isinstance(out, dict) or not out.get("token"):
        raise RuntimeError("class_verify failed: HTTP %s" % st)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps({"token": out["token"], "exp": time.time() + 86400 * 25}, ensure_ascii=False),
        encoding="utf-8",
    )
    log("cloud: token refreshed")
    return out["token"]


def load_existing(base, key, token):
    st, rows = cb_request(base, key, "power?select=id", token=token)
    if st == 401:
        raise PermissionError("401")
    if st != 200:
        raise RuntimeError("list power failed: HTTP %s %s" % (st, str(rows)[:160]))
    return {r["id"] for r in (rows or [])}


def cloud_rows_count(base, key, token):
    st, rows = cb_request(base, key, "power?select=id", token=token)
    return len(rows) if st == 200 and isinstance(rows, list) else -1


# ---------------- 历史采样（power_history）----------------
def _epoch(ts):
    """时间戳归一化为 epoch 秒（PostgREST timestamptz 可能是 ISO 字符串/数字）。"""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return int(ts)
    s = str(ts).strip()
    if s.isdigit():
        return int(s)
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def parse_log_history(path):
    """解析 power-sync.log 的 OK 行 → 历史采样（(roomverify, ts) 去重，兼容旧格式无 [roomverify]）。"""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    alias = room_aliases()
    rows, seen = [], set()
    for line in lines:
        m = LOG_OK_NEW_RE.match(line)
        if m:
            ts_s, label, rv, qty, unit = (m.group(1), m.group(2).strip(), m.group(3).strip(),
                                          m.group(4), m.group(5) or "度")
        else:
            m = LOG_OK_OLD_RE.match(line)
            if not m:
                continue
            ts_s, label, qty, unit = m.group(1), m.group(2).strip(), m.group(3), m.group(4) or "度"
            rv = alias.get(label)
            if not rv:  # 非班级宿舍 / 未知旧名：跳过
                continue
        try:
            ts = datetime.strptime(ts_s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
            quantity = float(qty)
        except ValueError:
            continue
        key = (rv, int(ts.timestamp()))
        if key in seen:
            continue
        seen.add(key)
        rows.append({"roomverify": rv, "quantity": round(quantity, 2),
                     "unit": unit or "度", "ts": ts.isoformat()})
    rows.sort(key=lambda r: (r["ts"], r["roomverify"]))
    return rows


def history_existing_keys(base, key, token, since_iso):
    path = ("power_history?select=roomverify,ts&order=ts.asc&ts=gte."
            + urllib.parse.quote(since_iso) + "&limit=10000")
    st, rows = cb_request(base, key, path, token=token)
    if st == 401:
        raise PermissionError("401")
    if st != 200:
        raise RuntimeError("list power_history failed: HTTP %s %s" % (st, str(rows)[:160]))
    keys = set()
    for r in rows or []:
        e = _epoch(r.get("ts"))
        if e is not None and r.get("roomverify"):
            keys.add((r["roomverify"], e))
    return keys


def insert_history(base, key, token, rows, log):
    """分批量插入 power_history；返回 (ok, fail)。"""
    ok = fail = 0
    for i in range(0, len(rows), HISTORY_BATCH):
        chunk = rows[i:i + HISTORY_BATCH]
        try:
            st, out = cb_request(base, key, HISTORY_TABLE, chunk, "POST", token=token)
        except Exception as e:
            st, out = 0, str(e)
        if st in (200, 201, 204):
            ok += len(chunk)
        else:
            fail += len(chunk)
            log("FAIL history insert: HTTP %s %s" % (st, str(out)[:140]))
    return ok, fail


def cleanup_history(base, key, token, log):
    cut = (datetime.now(LOCAL_TZ) - timedelta(days=HISTORY_KEEP_DAYS)).isoformat()
    st, out = cb_request(base, key, HISTORY_TABLE + "?ts=lt." + urllib.parse.quote(cut),
                         None, "DELETE", token=token)
    if st in (200, 204):
        log("history cleanup: %d 天前采样已清理" % HISTORY_KEEP_DAYS)
        return True
    log("FAIL history cleanup: HTTP %s %s" % (st, str(out)[:120]))
    return False


def backfill_log_history(base, key, token, log):
    rows = parse_log_history(LOG_FILE)
    if not rows:
        log("backfill: 日志里没有可回填的 OK 行")
        return 0, 0
    keys = history_existing_keys(base, key, token, rows[0]["ts"])
    todo = [r for r in rows if (r["roomverify"], _epoch(r["ts"])) not in keys]
    ok, fail = insert_history(base, key, token, todo, log)
    log("backfill: log_rows=%d existing=%d inserted=%d fail=%d"
        % (len(rows), len(keys), ok, fail))
    return ok, fail


# ---------------- 主流程 ----------------
def main(argv=None):
    try:  # 控制台输出统一 UTF-8（pythonw 下 stdout 为 None，跳过）
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr is not None:
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="同步班级宿舍剩余电量到 CloudBase public.power")
    ap.add_argument("--dry-run", action="store_true", help="只查网关并打印，不写云端")
    ap.add_argument("--limit", type=int, default=-1, help="只处理前 N 间（自检用；负数=全部）")
    ap.add_argument("--interval", type=float, default=1.1, help="相邻两次网关请求最小间隔秒（默认 1.1）")
    ap.add_argument("--timeout", type=float, default=20.0, help="单次网关请求超时秒")
    ap.add_argument("--no-sleep", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--backfill-log", action="store_true",
                    help="解析 power-sync.log 回填 power_history（按 (roomverify, ts) 去重，可重复跑）")
    args = ap.parse_args(argv)

    log = Logger(LOG_FILE)
    mode = " (dry-run)" if args.dry_run else (" (backfill-log)" if args.backfill_log else "")
    log("===== power sync start%s =====" % mode)

    rooms = ROOMS[: args.limit] if args.limit >= 0 else ROOMS

    base = key = token = None
    existing = set()
    if not args.dry_run:
        try:
            base, key = cb_config()
            token = get_token(base, key, log)
            try:
                existing = load_existing(base, key, token)
            except PermissionError:
                log("cloud: cached token rejected (401), refreshing")
                token = get_token(base, key, log, force=True)
                existing = load_existing(base, key, token)
        except Exception as e:  # 凭据/网络失败：整体退出
            log("FATAL cloud init: %s" % str(e)[:200])
            return 1

    if args.backfill_log:
        try:
            ok_b, fail_b = backfill_log_history(base, key, token, log)
            cleanup_history(base, key, token, log)
        except Exception as e:
            log("FATAL backfill: %s" % str(e)[:200])
            return 1
        log("backfill done: inserted=%d fail=%d" % (ok_b, fail_b))
        log("===== power sync end =====")
        return 0 if fail_b == 0 else 1

    t0 = time.time()
    ok = 0
    low_n = 0
    gw_fail = []
    cl_fail = []
    hist_rows = []
    for idx, (label, building, room, rv) in enumerate(rooms):
        if idx > 0 and not args.no_sleep:
            time.sleep(max(0.0, args.interval))
        try:
            quantity, unit = fetch_with_retry(label, rv, log, args.timeout)
        except GatewayError as e:
            gw_fail.append(label)
            log("FAIL %s gateway: %s（保留旧值）" % (label, str(e)[:140]))
            continue
        low = quantity < LOW_THRESHOLD
        if low:
            low_n += 1
        if args.dry_run:
            ok += 1
            log("DRY  %s = %.2f %s low=%d" % (label, quantity, unit, 1 if low else 0))
            continue

        row = {
            "id": rv,  # 稳定主键 = roomverify（显示名变化不影响行身份）
            "label": label,
            "building": building,
            "room": room,
            "roomverify": rv,
            "quantity": round(quantity, 2),
            "unit": unit,
            "low": low,
            "updated_at": datetime.now(LOCAL_TZ).isoformat(),
        }
        try:
            if rv in existing:
                st, out = cb_request(
                    base, key, "power?id=eq." + urllib.parse.quote(rv), row, "PATCH", token=token
                )
            else:
                st, out = cb_request(base, key, "power", [row], "POST", token=token)
        except Exception as e:
            st, out = 0, str(e)
        if st in (200, 201, 204):
            ok += 1
            log("OK   %s [%s] = %.2f %s low=%d (%s)" % (label, rv, round(quantity, 2), unit,
                                                        1 if low else 0, "PATCH" if rv in existing else "POST"))
            # 同 ts 追加一条历史采样（页面趋势/指标数据源）
            hist_rows.append({"roomverify": rv, "quantity": round(quantity, 2),
                              "unit": unit, "ts": row["updated_at"]})
        else:
            cl_fail.append(label)
            log("FAIL %s cloud write: HTTP %s %s（保留旧值）" % (label, st, str(out)[:140]))

    # 清理不在 ROOMS 里的过期行（仅管理员 token 可删；只跑全量时清理，--limit/--dry-run 不动）
    deleted = []
    if not args.dry_run and args.limit < 0:
        want = {r[3] for r in ROOMS}
        stale = sorted(set(existing) - want)
        for old_id in stale:
            st, out = cb_request(
                base, key, "power?id=eq." + urllib.parse.quote(old_id), None, "DELETE", token=token
            )
            if st in (200, 204):
                deleted.append(old_id)
                log("DEL  %s（不在 ROOMS，已清理）" % old_id)
            else:
                log("FAIL 清理过期行 %s: HTTP %s %s" % (old_id, st, str(out)[:120]))

    # 追加历史采样 + 清理 30 天前历史（只全量运行；--limit/--dry-run 不动历史）
    hist_ok = hist_fail = 0
    if not args.dry_run and hist_rows:
        hist_ok, hist_fail = insert_history(base, key, token, hist_rows, log)
        log("history: appended=%d fail=%d" % (hist_ok, hist_fail))
        if args.limit < 0:
            cleanup_history(base, key, token, log)

    elapsed = time.time() - t0
    rows_n = -1
    if not args.dry_run:
        try:
            rows_n = cloud_rows_count(base, key, token)
        except Exception:
            pass
    log(
        "power sync: ok=%d/%d gateway_fail=%d cloud_fail=%d low=%d stale_deleted=%d "
        "history_ok=%d history_fail=%d elapsed=%.1fs cloud_rows=%s"
        % (ok, len(rooms), len(gw_fail), len(cl_fail), low_n, len(deleted),
           hist_ok, hist_fail, elapsed, rows_n)
    )
    log("===== power sync end =====")
    # 全失败才视为本次失败（个别房间失败只记日志，保留旧值）
    if len(rooms) == 0:
        return 0
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
