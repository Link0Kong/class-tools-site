# -*- coding: utf-8 -*-
"""cloud_backend.py — 班级工具站后端基址 / 匿名 key 的**唯一解析入口**。

背景（P3 CloudBase→ECS 迁移，2026-11-18）：
    本机管线有十几个脚本各自从 `web/tools/index.html` 解析
    `var CB="..."` / `var CBK="..."`。切自建 PostgREST 时不能改网页常量
    （网页仍要能在切流前连 CloudBase），所以统一收敛到本模块：

    **默认不设任何覆盖 = 行为与改造前完全一致**（仍解析 index.html → CloudBase）；
    只有显式设置了覆盖（环境变量或 secrets\\cloud.env 文件）才切到自建后端，
    删除/注释覆盖即回滚。

优先级（高 → 低）：
    1. 进程环境变量 `CLASS_CB_BASE` / `CLASS_CB_KEY`（非空才生效）；
    2. `C:\\briefdesk\\secrets\\cloud.env` 里的同名键（KEY=VALUE；可选路径用
       `CLASS_CB_CONFIG` 覆盖，测试用）；
    3. `web/tools/index.html` 的 `var CB` / `var CBK` 字面量（CloudBase，默认）。

    第 2 条是给「长期运行的父进程」准备的：watchdog / detect_docs watcher 是
    常驻 pythonw，改用户环境变量它们看不到；但每次拉起的子进程都会重新读
    cloud.env，所以把切换写进该文件最稳（runbook 见 deploy/migration/PIPELINE.md）。

后端归类 `backend_kind()`：
    cloudbase   *.tcloudbasegateway.com   → 腾讯云 CloudBase 网关（默认）
    staging     路径含 /rest-next/        → ECS 自建 PostgREST 的影子/staging 库
    selfhosted  其它 http(s) 绝对地址      → ECS 自建 PostgREST（切流后 /v1/rdb/rest/）

用法（脚本内）：
    import cloud_backend
    base, key = cloud_backend.resolve()            # 大多数 cb_config() 一行替换
    base, key = cloud_backend.resolve(INDEX_PATH)  # 显式指定 index.html
    info = cloud_backend.describe()                # 只读诊断（**不含 key**）

命令行（只读，绝不给 key 值）：
    python scripts\\cloud_backend.py --status        # 当前后端 / 基址 / 来源
    python scripts\\cloud_backend.py --env-example   # 打印可追加到 cloud.env 的切换片段
    python scripts\\cloud_backend.py --check         # 只读探活 GET <base>service_health?limit=1

红线：
    * 不打印、不落盘、不返回给日志任何 key 内容（describe 只给来源与长度分类）；
    * 不修改 index.html / 不写云；解析失败只抛 RuntimeError，由调用方按原逻辑处理。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("BRIEFDESK_ROOT") or os.path.dirname(HERE)
SECRETS = os.path.join(ROOT, "secrets")

WEB_ROOT = os.environ.get("BRIEFDESK_WEB_ROOT") or r"C:\Users\Ko_Li\.openclaw\workspace\web"
DEFAULT_INDEX = os.path.join(WEB_ROOT, "tools", "index.html")

ENV_BASE = "CLASS_CB_BASE"
ENV_KEY = "CLASS_CB_KEY"
ENV_CONFIG = "CLASS_CB_CONFIG"
ENV_INDEX = "CLASS_CB_INDEX"

# cloud.env 默认位置（与 push_to_cloud.py 的入口一致：secrets\cloud.env）
DEFAULT_CONFIG = os.path.join(SECRETS, "cloud.env")

_CB_RE = re.compile(r'var CB="([^"]+)"')
_CBK_RE = re.compile(r'var CBK="([^"]+)"')

# 只允许覆盖这两个键；cloud.env 里其它内容（ECS 推送 token 等）一概不读进内存返回。
_OVERRIDE_KEYS = (ENV_BASE, ENV_KEY)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _clean(value) -> str:
    """去首尾空白 + 去成对引号（环境变量/文件值都走这里）。"""
    s = "" if value is None else str(value).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    return s


def _index_path(index_path=None) -> str:
    if index_path:
        return str(index_path)
    return os.environ.get(ENV_INDEX) or DEFAULT_INDEX


def _config_path(config_path=None) -> str:
    if config_path:
        return str(config_path)
    return os.environ.get(ENV_CONFIG) or DEFAULT_CONFIG


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 三个来源
# ---------------------------------------------------------------------------
def env_override():
    """进程环境变量覆盖：(base or None, key or None)。"""
    return _clean(os.environ.get(ENV_BASE)) or None, _clean(os.environ.get(ENV_KEY)) or None


def file_override(config_path=None):
    """secrets\\cloud.env 覆盖：(base or None, key or None)。

    只提取 CLASS_CB_BASE / CLASS_CB_KEY 两行；文件不存在/无这两行 → (None, None)。
    绝不把文件其它内容（ECS 推送 token 等）带出本函数。
    """
    path = _config_path(config_path)
    try:
        text = _read_text(path)
    except OSError:
        return None, None
    found = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[len("export "):].strip()
        if k in _OVERRIDE_KEYS and k not in found:
            found[k] = _clean(v)
    return found.get(ENV_BASE) or None, found.get(ENV_KEY) or None


def parse_index(text: str, path: str = "index.html"):
    """从 index.html 文本解析 (base, key)；缺失抛 RuntimeError（与原脚本行为一致）。"""
    base_m = _CB_RE.search(text or "")
    key_m = _CBK_RE.search(text or "")
    if not base_m or not key_m:
        raise RuntimeError("cannot parse CB/CBK from %s" % path)
    return base_m.group(1), key_m.group(1)


def index_override(index_path=None):
    """index.html 字面量：(base or None, key or None)；读不到 → (None, None)。"""
    try:
        return parse_index(_read_text(_index_path(index_path)), _index_path(index_path))
    except (OSError, RuntimeError):
        return None, None


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def normalize_base(base: str) -> str:
    """校验并规范化基址：必须是 http(s) 绝对地址，统一以 `/` 结尾。"""
    s = _clean(base)
    if not s:
        raise RuntimeError("empty backend base")
    low = s.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        raise RuntimeError("backend base must be an absolute http(s) URL")
    return s.rstrip("/") + "/"


def resolve_with_source(index_path=None, config_path=None):
    """解析 (base, key, meta)。

    meta = {"base_source": "env|file|index", "key_source": "env|file|index"}
    只有需要的来源才会被读取（例如两个覆盖都齐时完全不读 index.html，供 Linux/ECS 任务使用）。
    """
    e_base, e_key = env_override()
    f_base, f_key = file_override(config_path)

    base = e_base or f_base
    key = e_key or f_key
    base_src = "env" if e_base else ("file" if f_base else None)
    key_src = "env" if e_key else ("file" if f_key else None)

    if not base or not key:
        i_base, i_key = index_override(index_path)
        if not base and i_base:
            base, base_src = i_base, "index"
        if not key and i_key:
            key, key_src = i_key, "index"

    if not base:
        raise RuntimeError("no backend base (CLASS_CB_BASE / cloud.env / index.html var CB)")
    if not key:
        raise RuntimeError("no publishable key (CLASS_CB_KEY / cloud.env / index.html var CBK)")
    return normalize_base(base), key, {"base_source": base_src, "key_source": key_src}


def resolve(index_path=None, config_path=None):
    """脚本 `cb_config()` 的唯一入口：返回 (base, key)。默认 = index.html（CloudBase）。"""
    base, key, _meta = resolve_with_source(index_path, config_path)
    return base, key


def backend_kind(base: str) -> str:
    """后端归类：cloudbase / staging / selfhosted。"""
    low = (_clean(base) or "").lower()
    if not low:
        return "unknown"
    if "tcloudbasegateway.com" in low or ".tcb." in low or "tcb-api.tencentcloudapi.com" in low:
        return "cloudbase"
    if "/rest-next/" in low or low.rstrip("/").endswith("/rest-next"):
        return "staging"
    if low.startswith("http://") or low.startswith("https://"):
        return "selfhosted"
    return "unknown"


def describe(index_path=None, config_path=None) -> dict:
    """只读诊断信息（**不含 key 值**）。"""
    base, key, meta = resolve_with_source(index_path, config_path)
    return {
        "backend": backend_kind(base),
        "base": base,
        "base_source": meta["base_source"],
        "key_source": meta["key_source"],
        "key_present": bool(key),
        "key_len_class": "jwt-like" if key.count(".") >= 2 else "opaque",
        "index": _index_path(index_path),
        "config": _config_path(config_path),
        "index_var": "CB/CBK",
    }


# ---------------------------------------------------------------------------
# 只读探活
# ---------------------------------------------------------------------------
def check(timeout: float = 8.0) -> dict:
    """只读探活：GET <base>service_health?select=id&limit=1。

    返回 {"backend","base","http","ms","ok","note"}；HTTP 任何响应（含 401/403）都算
    「后端可达」，0 / 异常表示网络不可达。**不打印 key**。
    """
    import time as _time

    info = describe()
    base, key, _meta = resolve_with_source()
    url = base + "service_health?select=id&limit=1"
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "User-Agent": "briefdesk-cloud-backend-check/1.0",
    })
    t0 = _time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(4096)
            http = int(resp.status)
            note = "ok"
    except urllib.error.HTTPError as exc:
        http = int(exc.code)
        # 401/403 说明路由/服务在，鉴权不同 —— 对「切换前探活」仍算可达。
        note = "reachable(auth %s)" % http if http in (401, 403) else "http-error"
    except Exception as exc:  # noqa: BLE001
        http = 0
        note = (str(exc).strip() or exc.__class__.__name__)[:120]
    ms = int((_time.perf_counter() - t0) * 1000)
    info.update({"http": http, "ms": ms, "ok": http != 0, "note": note})
    return info


# ---------------------------------------------------------------------------
# CLI（只读）
# ---------------------------------------------------------------------------
def _emit(text: str) -> None:
    try:
        import sys
        if sys.stdout is not None:
            sys.stdout.write(str(text) + "\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def _env_example() -> str:
    return (
        "# ---- ECS 自建后端切换（追加到 C:\\briefdesk\\secrets\\cloud.env；不打印任何 key）----\n"
        "# staging（P2 影子验证，写 staging 库；默认不启用）：\n"
        "CLASS_CB_BASE=http://121.196.47.2/v1/rdb/rest-next/\n"
        "# 切流后（P4，Caddy /v1/rdb/rest/* 改指向自建 PostgREST）：\n"
        "#CLASS_CB_BASE=http://121.196.47.2/v1/rdb/rest/\n"
        "# 备案 + HTTPS 恢复后（等价写法）：\n"
        "#CLASS_CB_BASE=https://tool.furina.fun/v1/rdb/rest/\n"
        "# CLASS_CB_KEY 可选：自建路由 Caddy 会剥掉 Authorization，一般不需要覆盖。\n"
        "# 回滚：删除/注释以上 CLASS_CB_* 行即可回到 CloudBase（index.html 的 var CB）。\n"
    )


def main(argv=None) -> int:
    import argparse
    import sys as _sys

    # 管道/重定向下强制 UTF-8，避免 Windows 控制台默认 GBK 让下游（runbook/CI）解码失败。
    try:
        if _sys.stdout is not None and not _sys.stdout.isatty():
            _sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(
        prog="cloud_backend.py",
        description="后端基址解析（只读；默认 CloudBase，CLASS_CB_BASE/CLASS_CB_KEY 覆盖）")
    ap.add_argument("--status", action="store_true", help="打印当前后端/基址/来源（不含 key）")
    ap.add_argument("--env-example", action="store_true", help="打印切换 cloud.env 片段")
    ap.add_argument("--check", action="store_true", help="只读探活 <base>service_health")
    ap.add_argument("--json", action="store_true", help="JSON 输出（配合 --status/--check）")
    ns = ap.parse_args(argv)

    if ns.env_example:
        _emit(_env_example())
        return 0
    try:
        if ns.check:
            info = check()
            if ns.json:
                _emit(json.dumps(info, ensure_ascii=False, indent=1))
            else:
                _emit("backend=%s base=%s source=%s/%s http=%s %dms -> %s"
                      % (info["backend"], info["base"], info["base_source"],
                         info["key_source"], info["http"], info["ms"], info["note"]))
            return 0 if info["ok"] else 1
        info = describe()
        if ns.json:
            _emit(json.dumps(info, ensure_ascii=False, indent=1))
        else:
            _emit("backend=%s base=%s base_source=%s key_source=%s key=%s"
                  % (info["backend"], info["base"], info["base_source"],
                     info["key_source"], info["key_len_class"]))
            _emit("index=%s config=%s" % (info["index"], info["config"]))
        return 0
    except Exception as exc:  # noqa: BLE001
        _emit("FAIL %s: %s" % (exc.__class__.__name__, exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
