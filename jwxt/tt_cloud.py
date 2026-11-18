# -*- coding: utf-8 -*-
"""tt_cloud.py — 把课表快照（tools/tt.json）发布到 CloudBase `public.site_assets` 行 id='tt'。

背景（2026-11-07 DNS 暂停改造，契约见 web/tools/tests/dns_pause_tt_health_spec.md §1/§3）：
    小程序/网页原先硬依赖 https://tool.furina.fun/tt.json；站点域名暂停后需改从 CloudBase
    读取课表快照。本模块是**写者**：本机教务同步成功后把 tt.json 原对象 upsert 到云端；
    读路径（网页/小程序）另行实现，不在本文件范围。

写入语义：
    * body = tools/tt.json 的原始 JSON 对象（{c:[...], t:"...", meta:{...}}）；
    * meta = {source:"jwxt", fetchedAt:<ms>, count:<n>, termStart:"YYYY-MM-DD", syncedAt:<ISO>}；
    * updated_at = 发布时刻（now）。
    * 行不存在 → POST `site_assets`；已存在 → PATCH `site_assets?id=eq.tt`。

鉴权（密钥零泄漏）：
    * CB/CBK 从 web/tools/index.html 的 var CB / var CBK 解析（publishable key，设计上公开）；
    * 管理员班级 token 只从 C:\\briefdesk\\secrets\\class-token.json 读取；过期/被拒时用
      rpc/class_verify 自动刷新（管理员身份常量与 sync_power_cloud.py 同源）。
    * 绝不打印/写日志 token 或 key；错误信息只保留状态码/字节数/文案。

CLI（cwd 任意）：
    python tt_cloud.py --tt ..\\tools\\tt.json            # 立即回填/发布一次
    python tt_cloud.py --tt ..\\tools\\tt.json --dry-run  # 只解析并打印将发布的 meta，不联网
    python tt_cloud.py --dry-run --quiet                  # 计划任务里用（只写日志文件）

被 `web/jwxt/sync.py` 在写盘成功后调用：publish(out_path)；失败抛 PublishError，由调用方
只记日志、不得影响 sync.py 退出码与 OSS 上传。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WEB_ROOT = os.path.dirname(HERE)          # web\jwxt → web
WEB_ROOT = os.environ.get("BRIEFDESK_WEB_ROOT") or DEFAULT_WEB_ROOT
INDEX_PATH = os.path.join(WEB_ROOT, "tools", "index.html")
DEFAULT_TT = os.path.join(WEB_ROOT, "tools", "tt.json")

TOKEN_FILE = os.environ.get("CLASS_TOKEN_FILE") or r"C:\briefdesk\secrets\class-token.json"

# class_verify 用的管理员身份（与 scripts/sync_power_cloud.py 同源；仅在进程内存使用，绝不打印）
ADMIN_SID = "3260707024"
ADMIN_NAME = "\u9648\u5b50\u9e92"

CB_RE = re.compile(r'var CB="([^"]+)"')
CBK_RE = re.compile(r'var CBK="([^"]+)"')

HTTP_TIMEOUT = 20.0
UA = "briefdesk-tt-cloud/1.0"
ROW_ID = "tt"

LOGGER = logging.getLogger("jwxt.tt_cloud")

# 每次调用统一的时间戳
def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PublishError(RuntimeError):
    """发布失败（调用方只记日志，不影响自身退出码）。"""


# ---------------------------------------------------------------------------
# 配置 / token（不打印 token）
# ---------------------------------------------------------------------------
def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def cb_config():
    """返回 (base, key)。

    2026-11-18 迁移：优先读环境变量 CLASS_CB_BASE / CLASS_CB_KEY（由
    C:\\briefdesk\\scripts\\cloud_backend.py 同一套约定注入），未设置时回退到
    web/tools/index.html 的 var CB / var CBK（默认仍是 CloudBase，行为不变）。
    """
    base = os.environ.get("CLASS_CB_BASE", "").strip()
    key = os.environ.get("CLASS_CB_KEY", "").strip()
    if base and key:
        return base.rstrip("/") + "/", key
    try:
        text = _read_text(INDEX_PATH)
    except OSError as exc:
        raise PublishError("无法读取 %s：%s" % (INDEX_PATH, exc))
    base_m = CB_RE.search(text)
    key_m = CBK_RE.search(text)
    if not base_m or not key_m:
        raise PublishError("无法从 %s 解析 var CB / var CBK" % INDEX_PATH)
    return base_m.group(1), key_m.group(1)


def _cb_request(base, key, path, body=None, method="GET", token=None, timeout=HTTP_TIMEOUT):
    """PostgREST 请求：返回 (status, parsed_or_text, latency_ms)；status=0 表示网络异常。

    注意：绝不记录/打印 headers（token/key 只在本函数的内存里使用）。
    """
    headers = {"Authorization": "Bearer " + key,
               "Accept": "application/json",
               "User-Agent": UA}
    if token:
        headers["X-Device-Id"] = token
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ms = int((time.perf_counter() - t0) * 1000)
            parsed = None
            if raw:
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except Exception:
                    parsed = raw[:300].decode("utf-8", "replace")
            return int(resp.status), parsed, ms
    except urllib.error.HTTPError as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        try:
            exc.read()
        except Exception:
            pass
        return int(exc.code), None, ms
    except Exception as exc:  # noqa: BLE001
        ms = int((time.perf_counter() - t0) * 1000)
        return 0, (str(exc).strip() or exc.__class__.__name__)[:200], ms


def _verify_admin(base, key, token):
    """rpc/class_verify 换管理员 token，写回本机缓存（内容不打印）。"""
    status, out, _ms = _cb_request(
        base, key, "rpc/class_verify",
        {"p_sid": ADMIN_SID, "p_name": ADMIN_NAME}, "POST")
    if status != 200 or not isinstance(out, dict) or not out.get("token"):
        raise PublishError("class_verify failed: HTTP %s" % status)
    token = out["token"]
    try:
        folder = os.path.dirname(TOKEN_FILE)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
            json.dump({"token": token, "exp": time.time() + 86400 * 25},
                      fh, ensure_ascii=False)
    except OSError as exc:
        LOGGER.warning("token 缓存写入失败（不影响本次发布）：%s", exc)
    LOGGER.info("管理员 token 已通过 class_verify 刷新（值不记录）")
    return token


def get_token(base, key, force=False):
    """返回管理员班级 token：优先本机缓存，过期（<2h 余量）/force 时 class_verify 刷新。"""
    if not force:
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
            token = (obj.get("token") or "").strip()
            exp = float(obj.get("exp") or 0)
            if token and exp > time.time() + 3600:
                return token
        except (OSError, ValueError, TypeError):
            pass
    return _verify_admin(base, key)


# ---------------------------------------------------------------------------
# 读取课表文件 / 组装行
# ---------------------------------------------------------------------------
def load_tt(tt_path: str) -> dict:
    """读取 tools/tt.json 原始对象；结构不合法时抛 PublishError（避免把坏数据发上云）。"""
    path = os.path.abspath(tt_path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError as exc:
        raise PublishError("无法读取课表文件 %s：%s" % (path, exc))
    except ValueError as exc:
        raise PublishError("课表文件不是合法 JSON %s：%s" % (path, exc))
    if not isinstance(doc, dict):
        raise PublishError("课表文件不是 JSON 对象：%s" % path)
    courses = doc.get("c")
    if not isinstance(courses, list) or not courses:
        raise PublishError("课表文件没有课程数组（c 为空）：%s" % path)
    return doc


def build_row(doc: dict, tt_path: str) -> dict:
    """由 tt.json 原对象组装 site_assets 行（body 原样、meta 按 spec §1）。"""
    meta_in = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    fetched_at = int(meta_in.get("fetchedAt") or 0)
    if fetched_at <= 0:
        try:
            fetched_at = int(os.path.getmtime(tt_path) * 1000)
        except OSError:
            fetched_at = int(time.time() * 1000)
    courses = doc.get("c") or []
    return {
        "id": ROW_ID,
        "body": doc,
        "meta": {
            "source": "jwxt",
            "fetchedAt": fetched_at,
            "count": len(courses),
            "termStart": str(doc.get("t") or ""),
            "syncedAt": _utc_iso(),
        },
        "updated_at": _utc_iso(),
    }


# ---------------------------------------------------------------------------
# 发布
# ---------------------------------------------------------------------------
def _fetch_meta(base, key, token):
    """读 site_assets?id=eq.tt&select=id,meta,updated_at；返回 (status, rows, ms)。"""
    return _cb_request(
        base, key, "site_assets?select=id,meta,updated_at&id=eq." + ROW_ID, token=token)


def _upsert(base, key, token, row):
    """存在则 PATCH，不存在则 POST；返回 (method, status, ms)。401/403 会刷新 token 重试一次。"""
    status, rows, ms = _fetch_meta(base, key, token)
    if status in (401, 403):
        token = get_token(base, key, force=True)
        status, rows, ms = _fetch_meta(base, key, token)
    if status != 200:
        raise PublishError("读取 site_assets 失败：HTTP %s（%sms）" % (status, ms))
    exists = isinstance(rows, list) and len(rows) > 0

    if exists:
        st, _out, ms2 = _cb_request(
            base, key, "site_assets?id=eq." + ROW_ID, row, "PATCH", token)
        if st in (200, 204):
            return "PATCH", st, ms2
        LOGGER.warning("PATCH site_assets 返回 HTTP %s，改试 POST", st)
        exists = False
    st, _out, ms2 = _cb_request(base, key, "site_assets", [row], "POST", token)
    if st in (200, 201, 204):
        return "POST", st, ms2
    if st in (401, 403):
        token = get_token(base, key, force=True)
        st, _out, ms2 = _cb_request(base, key, "site_assets", [row], "POST", token)
        if st in (200, 201, 204):
            return "POST", st, ms2
    raise PublishError("写入 site_assets 失败：HTTP %s" % st)


def publish(tt_path: str = DEFAULT_TT, dry_run: bool = False) -> dict:
    """把 tt.json 发布到云端 site_assets 行 id='tt'。

    返回 {"ok":True, "count":n, "termStart":..., "fetchedAt":..., "method":..., "http":..., "ms":...}
    dry_run=True 时只解析并返回将发布的信息，不联网。
    失败抛 PublishError（调用方决定是否吞掉）。
    """
    path = os.path.abspath(tt_path)
    doc = load_tt(path)
    row = build_row(doc, path)
    meta = row["meta"]
    result = {"ok": True, "count": meta["count"], "termStart": meta["termStart"],
              "fetchedAt": meta["fetchedAt"], "dryRun": bool(dry_run)}
    if dry_run:
        LOGGER.info("dry-run：将发布 site_assets.tt（count=%s termStart=%s fetchedAt=%s），不联网",
                    meta["count"], meta["termStart"] or "-", meta["fetchedAt"])
        return result

    t0 = time.perf_counter()
    base, key = cb_config()
    token = get_token(base, key)
    method, status, write_ms = _upsert(base, key, token, row)

    # 回读校验（只记 meta 里的非敏感信息，body 不落日志）
    st2, rows, read_ms = _fetch_meta(base, key, token)
    cloud_meta = None
    if st2 == 200 and isinstance(rows, list) and rows:
        cloud_meta = rows[0].get("meta") or {}
    ok = (isinstance(cloud_meta, dict)
          and int(cloud_meta.get("count") or -1) == meta["count"]
          and int(cloud_meta.get("fetchedAt") or -1) == meta["fetchedAt"])
    result.update({"method": method, "http": status, "writeMs": write_ms,
                   "readHttp": st2, "verified": bool(ok),
                   "ms": int((time.perf_counter() - t0) * 1000)})
    if not ok:
        LOGGER.warning("回读校验未完全一致（write HTTP %s / read HTTP %s），请稍后用诊断页确认",
                       status, st2)
    LOGGER.info("site_assets.tt 发布成功：%s HTTP %s，count=%s termStart=%s，%sms（校验=%s）",
                method, status, meta["count"], meta["termStart"] or "-",
                result["ms"], "ok" if ok else "mismatch")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _setup_cli_logging(quiet: bool):
    if LOGGER.handlers:
        return
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.WARNING if quiet else logging.INFO)
    LOGGER.propagate = False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="tt_cloud.py",
        description="把课表快照 tools/tt.json 发布到 CloudBase public.site_assets 行 id='tt'")
    parser.add_argument("--tt", default=DEFAULT_TT,
                        help="课表 JSON 路径（默认 %s）" % DEFAULT_TT)
    parser.add_argument("--dry-run", action="store_true",
                        help="只解析并打印将发布的信息，不写云端")
    parser.add_argument("--quiet", action="store_true", help="只输出警告/错误")
    args = parser.parse_args(argv)
    _setup_cli_logging(args.quiet)
    try:
        result = publish(args.tt, dry_run=args.dry_run)
    except PublishError as exc:
        LOGGER.error("发布失败：%s", exc)
        if not args.quiet and sys.stdout is not None:
            print("FAIL %s" % exc, file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("未预期错误")
        if not args.quiet and sys.stdout is not None:
            print("FAIL 未预期错误：%s" % exc, file=sys.stderr)
        return 1
    if not args.quiet and sys.stdout is not None:
        print("OK site_assets.tt 已发布：count=%s termStart=%s fetchedAt=%s method=%s http=%s %sms"
              % (result.get("count"), result.get("termStart") or "-",
                 result.get("fetchedAt"), result.get("method", "dry-run"),
                 result.get("http", "-"), result.get("ms", 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
