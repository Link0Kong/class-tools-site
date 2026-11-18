#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jobs_runner.py — ECS 定时任务入口（替代 CloudBase 云函数 power_sync / xgj_sync / health_probe）。

部署位置（deploy/ecs_cron.py 自动安装）：
    /opt/class-tools/jobs/jobs_runner.py
    /opt/class-tools/jobs/<job>/{index.py,...}          ← deploy/functions/<job>/ 的同源副本
    /etc/class-tools/jobs.env                           ← 600 root:root；由 ecs_cron.py 从本机 secrets 生成
    /var/lib/class-tools/jobs/state/<row_id>.json       ← 心跳（health_beat 读取；CLASS_JOB_HEARTBEAT=1 时生效）

systemd：
    class-tools-job-power-sync.timer   hourly   :01
    class-tools-job-xgj-sync.timer     every 2h :20
    class-tools-job-health-probe.timer every 5min
    （全部默认 DISABLED；切流后由 ecs_cron.py enable 启用）

用法（手动/冒烟）：
    python3 /opt/class-tools/jobs/jobs_runner.py health_probe
    python3 /opt/class-tools/jobs/jobs_runner.py power_sync
    python3 /opt/class-tools/jobs/jobs_runner.py --self-check     # 只校验环境/导入（不写库）
    python3 /opt/class-tools/jobs/jobs_runner.py --list

环境变量（全部来自 /etc/class-tools/jobs.env，绝不打印值）：
    目标后端（由 ecs_cron.py 按 --backend 生成；staging 默认）：
        CB_BASE / CB_KEY                 云函数包装层读这两个（cloudbase/{power_sync,xgj_sync,health_probe}/index.py 原样复用）
        CLASS_CB_BASE / CLASS_CB_KEY     本仓库脚本统一读取的后端覆盖（scripts/cloud_backend.py）
    管理员凭据（生产服务凭据，仅脚本内部使用，不入库、不打印）：
        CLASS_ADMIN_SID / CLASS_ADMIN_NAME
    学工记（仅 xgj_sync 需要）：XGJ_TOKEN / XGJ_MEMBER_ID / XGJ_EXP / XGJ_EXP_TEXT / XGJ_CID
    心跳/巡检标记：
        CLASS_JOB_HEARTBEAT=1            health_beat 读取 ECS timer 心跳（默认关闭，ecs_cron 安装时打开）
        CLASS_JOBS_STATE=/var/lib/class-tools/jobs/state
        CLASS_HEALTH_RUNNER=ecs-timer    cloud_health_probe.meta.runner

退出码：0=成功（心跳 ok=true）；非 0=失败（心跳 ok=false，systemd journal 记录）。
安全：本脚本只输出任务耗时/行数/HTTP 码，绝不输出 token/key/密码。
"""

import json
import os
import socket
import sys
import time
import traceback

JOBS_DIR = os.environ.get("CLASS_JOBS_DIR") or "/opt/class-tools/jobs"
STATE_DIR = os.environ.get("CLASS_JOBS_STATE") or "/var/lib/class-tools/jobs/state"
RUNNER = "ecs-timer"
VERSION = "2026-11-18.p3"

# job → (云函数目录名, service_health 行 id)
JOBS = {
    "power_sync": ("power_sync", "cloud_power_sync"),
    "xgj_sync": ("xgj_sync", "cloud_xgj_sync"),
    "health_probe": ("health_probe", "cloud_health_probe"),
}
LOG_MAX_BYTES = 1_000_000
LOG_TAIL_LINES = 300


# ---------------------------------------------------------------- 小工具
def _now_ms() -> int:
    return int(time.time() * 1000)


def _emit(msg: str) -> None:
    try:
        if sys.stdout is not None:
            sys.stdout.write(str(msg) + "\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def _ensure_dirs() -> None:
    for sub in ("", "logs"):
        try:
            os.makedirs(os.path.join(STATE_DIR, sub), exist_ok=True)
        except OSError:
            pass


def _job_log_path(job: str) -> str:
    return os.path.join(STATE_DIR, "logs", job + ".log")


def log(job: str, msg: str) -> None:
    """任务日志：state/logs/<job>.log，>1MB 保留尾部 300 行；不含任何凭据。"""
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    path = _job_log_path(job)
    try:
        _ensure_dirs()
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                tail = fh.readlines()[-LOG_TAIL_LINES:]
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(tail)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def backend_kind(base: str) -> str:
    low = (base or "").lower()
    if "tcloudbasegateway.com" in low:
        return "cloudbase"
    if "/rest-next/" in low:
        return "staging"
    if low.startswith("http://") or low.startswith("https://"):
        return "selfhosted"
    return "unknown"


def _write_heartbeat(row_id: str, job: str, ok: bool, rc, ms, extra=None) -> None:
    """原子写心跳 JSON（600）；health_beat 在 CLASS_JOB_HEARTBEAT=1 时读取。"""
    rec = {
        "row": row_id,
        "job": job,
        "runner": RUNNER,
        "at_ms": _now_ms(),
        "ok": bool(ok),
        "rc": rc,
        "ms": int(ms),
        "host": socket.gethostname(),
        "version": VERSION,
        "backend": backend_kind(os.environ.get("CB_BASE") or os.environ.get("CLASS_CB_BASE") or ""),
    }
    if isinstance(extra, dict):
        for key in ("rows", "patched", "posted", "summary"):
            if extra.get(key) is not None:
                rec[key] = extra.get(key)
    try:
        _ensure_dirs()
        path = os.path.join(STATE_DIR, row_id + ".json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except OSError as exc:
        log(job, "WARN heartbeat write failed: %r" % (exc,))


# ---------------------------------------------------------------- 各 job 适配
def _run_power_sync() -> dict:
    import index  # noqa: WPS433（/opt/class-tools/jobs/power_sync/index.py）
    sp = getattr(index, "sp", None)
    if sp is not None:
        # 本机脚本里的 TOKEN_FILE/LOG_FILE 是 Windows 路径；ECS 上改到状态目录。
        # （power_sync/index.py 的 _get_token 优先 CLASS_TOKEN 否则 class_verify，不写 token 缓存）
        try:
            from pathlib import Path
            sp.TOKEN_FILE = Path(os.path.join(STATE_DIR, "class-token.json"))
        except Exception:  # noqa: BLE001
            pass
    return index.main_handler({}, None)


def _run_xgj_sync() -> dict:
    import index  # noqa: WPS433
    return index.main_handler({}, None)


def _run_health_probe() -> dict:
    import index  # noqa: WPS433
    return index.main_handler({}, None)


RUNNERS = {
    "power_sync": _run_power_sync,
    "xgj_sync": _run_xgj_sync,
    "health_probe": _run_health_probe,
}


# ---------------------------------------------------------------- 入口
def _setup_path(job: str) -> str:
    folder, _row = JOBS[job]
    # JOBS_DIR 也进 path：job 里的同源脚本 import cloud_backend 时能找到（ECS 上无 index.html，
    # 靠 jobs.env 的 CLASS_CB_BASE/CLASS_CB_KEY 解析）。
    for path in (JOBS_DIR, os.path.join(JOBS_DIR, folder)):
        if path not in sys.path:
            sys.path.insert(0, path)
    return os.path.join(JOBS_DIR, folder)


def _env_names() -> list:
    keys = ("CB_BASE", "CB_KEY", "CLASS_CB_BASE", "CLASS_CB_KEY", "CLASS_ADMIN_SID",
            "CLASS_ADMIN_NAME", "CLASS_TOKEN", "XGJ_TOKEN", "XGJ_MEMBER_ID", "XGJ_EXP",
            "XGJ_CID", "CLASS_JOB_HEARTBEAT", "CLASS_JOBS_STATE", "CLASS_HEALTH_RUNNER")
    return ["%s=%s" % (k, "set" if os.environ.get(k) else "MISSING") for k in keys]


def self_check(job: str = None) -> int:
    """只校验环境与导入（不调用 handler、不写库）。返回 0/1。"""
    _emit("runner=%s version=%s jobs_dir=%s state_dir=%s"
          % (RUNNER, VERSION, JOBS_DIR, STATE_DIR))
    _emit("env: " + ", ".join(_env_names()))
    base = os.environ.get("CB_BASE") or os.environ.get("CLASS_CB_BASE") or ""
    _emit("target backend=%s base=%s" % (backend_kind(base), base or "-"))
    if job:
        targets = [job] if job in JOBS else []
        if not targets:
            _emit("unknown job: %s (choose %s)" % (job, ", ".join(JOBS)))
            return 2
    else:
        targets = list(JOBS)
    fails = 0
    for name in targets:
        job_dir = _setup_path(name)
        try:
            ok = os.path.isfile(os.path.join(job_dir, "index.py"))
            if not ok:
                raise RuntimeError("missing index.py in %s" % job_dir)
            import index  # noqa: WPS433,F401
            _emit("[%s] import OK (%s)" % (name, job_dir))
        except Exception as exc:  # noqa: BLE001
            fails += 1
            _emit("[%s] import FAIL: %r" % (name, exc))
    _emit("self-check %s" % ("OK" if fails == 0 else "FAIL (%d)" % fails))
    return 0 if fails == 0 else 1


def run_job(job: str) -> int:
    folder, row_id = JOBS[job]
    job_dir = _setup_path(job)
    if not os.path.isfile(os.path.join(job_dir, "index.py")):
        _emit(json.dumps({"job": job, "ok": False,
                          "error": "missing job dir %s" % job_dir}, ensure_ascii=False))
        _write_heartbeat(row_id, job, False, "missing-dir", 0)
        return 2
    base = os.environ.get("CB_BASE") or os.environ.get("CLASS_CB_BASE") or ""
    if not base:
        _emit(json.dumps({"job": job, "ok": False,
                          "error": "CB_BASE/CLASS_CB_BASE 未配置（jobs.env 缺失）"},
                         ensure_ascii=False))
        _write_heartbeat(row_id, job, False, "no-base", 0)
        return 2
    if not os.environ.get("CLASS_ADMIN_SID") and not os.environ.get("CLASS_TOKEN"):
        _emit(json.dumps({"job": job, "ok": False,
                          "error": "CLASS_ADMIN_SID/CLASS_TOKEN 未配置"},
                         ensure_ascii=False))
        _write_heartbeat(row_id, job, False, "no-admin", 0)
        return 2

    t0 = time.time()
    log(job, "start runner=%s backend=%s" % (RUNNER, backend_kind(base)))
    try:
        result = RUNNERS[job]()
        ok = bool(isinstance(result, dict) and result.get("ok"))
        rc = 0 if ok else 1
        err = "" if ok else str((result or {}).get("error") or "")[:300]
    except Exception:  # noqa: BLE001
        ok, rc = False, 1
        err = "exception"
        result = {"error": traceback.format_exc()[-800:]}
        log(job, "FAIL exception:\n" + traceback.format_exc()[-1200:])
    ms = int((time.time() - t0) * 1000)

    summary = ""
    if isinstance(result, dict):
        summary = str(result.get("error") or "")[:120]
        if not summary:
            bits = ["%s=%s" % (k, result.get(k)) for k in
                    ("rc", "english", "pending", "cloud_ok", "archived", "rows",
                     "patched", "posted") if result.get(k) is not None]
            summary = " ".join(bits)
    _write_heartbeat(row_id, job, ok, rc, ms,
                     {"rows": (result or {}).get("rows") if isinstance(result, dict) else None,
                      "patched": (result or {}).get("patched") if isinstance(result, dict) else None,
                      "posted": (result or {}).get("posted") if isinstance(result, dict) else None,
                      "summary": summary})
    log(job, "done ok=%s rc=%s ms=%d %s" % (ok, rc, ms, summary))
    out = {"job": job, "row": row_id, "ok": ok, "rc": rc, "ms": ms,
           "backend": backend_kind(base), "runner": RUNNER, "result": result}
    if err:
        out["error"] = err
    _emit(json.dumps(out, ensure_ascii=False, default=str)[:4000])
    return rc


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        _emit(__doc__)
        return 0
    if argv[0] == "--list":
        _emit(json.dumps({k: {"dir": v[0], "row": v[1]} for k, v in JOBS.items()},
                         ensure_ascii=False, indent=1))
        return 0
    if argv[0] == "--self-check":
        job = argv[1] if len(argv) > 1 else None
        return self_check(job)
    job = argv[0]
    if job not in JOBS:
        _emit("unknown job: %s (choose %s)" % (job, ", ".join(JOBS)))
        return 2
    return run_job(job)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        _emit("FATAL: %s" % traceback.format_exc()[-1200:])
        raise SystemExit(1)
