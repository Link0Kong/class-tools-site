#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""班级工具站 · 五个端仓库的自动提交守护（本机计划任务调用）

规则：
  1. 逐个检查仓库；工作区干净的直接跳过（不会产生空提交）。
  2. 有改动时要求“最近 5 分钟没有新写入”，避免把正在写一半的文件提交。
  3. 调用该仓库根目录的 sync_repos.py --auto：安全检查 → 提交 → 推 GitHub + Gitee → 核对 SHA。
  4. 有合并 / rebase 进行中、或有 git 锁文件时跳过，不碰别人的操作。
  5. 全程写日志 web/tools/repo_ops/_logs/auto_commit.log；单实例锁防止重入。

用法：
    python auto_commit_all.py            # 正常跑一轮
    python auto_commit_all.py --dry-run  # 只打印将要做的事
    python auto_commit_all.py --repo 网页端
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
IDLE_SECONDS = 300
LOCK_STALE_SECONDS = 30 * 60
REPOS = [
    ("网页端", "web"),
    ("安卓端", "android-class-tools"),
    ("小程序端", "mp-class-tools"),
    ("鸿蒙端", "harmony-class-tools"),
    ("Windows 端", "windows-class-tools"),
]
LOG_DIR = HERE / "_logs"
LOG_FILE = LOG_DIR / "auto_commit.log"
LOCK_FILE = LOG_DIR / "auto_commit.lock"
GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "PYTHONIOENCODING": "utf-8",
}


def now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def force_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5 * 1024 * 1024:
            backup = LOG_FILE.with_suffix(".log.1")
            try:
                backup.unlink(missing_ok=True)
            except OSError:
                pass
            LOG_FILE.replace(backup)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def run_git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        env=GIT_ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def acquire_lock() -> bool:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
                age = time.time() - float(data.get("ts") or 0)
            except (OSError, ValueError):
                age = LOCK_STALE_SECONDS + 1
            if age < LOCK_STALE_SECONDS:
                log("上一轮自动提交仍在运行，本轮跳过")
                return False
            LOCK_FILE.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "ts": time.time()}, fh)
        return True
    return False


def release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def in_progress(repo: Path) -> str:
    gitdir = repo / ".git"
    for marker, label in (
        ("MERGE_HEAD", "合并"),
        ("rebase-merge", "rebase"),
        ("rebase-apply", "rebase"),
        ("CHERRY_PICK_HEAD", "cherry-pick"),
        ("index.lock", "git 锁"),
    ):
        if (gitdir / marker).exists():
            return label
    return ""


def newest_mtime(repo: Path, paths: list[str]) -> float:
    newest = 0.0
    budget = 4000
    for rel in paths:
        target = repo / rel
        try:
            if target.is_dir():
                for root, _dirs, files in os.walk(target):
                    for name in files:
                        budget -= 1
                        if budget <= 0:
                            return newest
                        try:
                            newest = max(newest, (Path(root) / name).stat().st_mtime)
                        except OSError:
                            continue
            elif target.exists():
                newest = max(newest, target.stat().st_mtime)
        except OSError:
            continue
    return newest


def changed_paths(repo: Path) -> list[str]:
    proc = run_git(repo, "status", "--porcelain", "-z")
    if proc.returncode != 0:
        return []
    items = [item for item in proc.stdout.split("\0") if item]
    paths: list[str] = []
    index = 0
    while index < len(items):
        item = items[index]
        status = item[:2]
        path = item[3:] if len(item) > 3 else ""
        if "R" in status or "C" in status:
            index += 1  # 下一个条目是原路径
        if path:
            paths.append(path)
        index += 1
    return paths


def process_repo(name: str, rel: str, dry_run: bool) -> None:
    repo = WORKSPACE / rel
    if not (repo / ".git").exists():
        log(f"{name}：跳过，找不到仓库 {repo}")
        return
    busy = in_progress(repo)
    if busy:
        log(f"{name}：跳过，有 {busy} 正在进行")
        return
    paths = changed_paths(repo)
    if not paths:
        return
    idle = time.time() - newest_mtime(repo, paths)
    if idle < IDLE_SECONDS:
        log(f"{name}：有 {len(paths)} 项改动，但最近 {int(idle)}s 内仍有写入，等下一轮")
        return
    if dry_run:
        log(f"{name}：将自动提交 {len(paths)} 项（空闲 {int(idle)}s）")
        return
    script = repo / "sync_repos.py"
    if not script.exists():
        log(f"{name}：跳过，缺少 {script.name}（先在仓库根放 sync_repos.py）")
        return
    started = time.time()
    proc = subprocess.run(
        [sys.executable, str(script), "--auto"],
        cwd=str(repo),
        env=GIT_ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    elapsed = time.time() - started
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else ""
    if proc.returncode == 0:
        log(f"{name}：自动提交完成（{elapsed:.0f}s）{summary}")
    else:
        detail = (proc.stdout or "") + "\n" + (proc.stderr or "")
        log(f"{name}：自动提交失败（{elapsed:.0f}s）\n{detail.strip()[-2000:]}")


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    only = None
    if "--repo" in sys.argv:
        index = sys.argv.index("--repo")
        if index + 1 < len(sys.argv):
            only = sys.argv[index + 1]
    if not acquire_lock():
        return 0
    try:
        for name, rel in REPOS:
            if only and only not in (name, rel):
                continue
            try:
                process_repo(name, rel, dry_run)
            except subprocess.TimeoutExpired:
                log(f"{name}：超时（15 分钟），本轮放弃")
            except Exception as exc:  # noqa: BLE001 - 守护进程必须继续
                log(f"{name}：异常 {type(exc).__name__}: {exc}")
    finally:
        release_lock()
    return 0


if __name__ == "__main__":
    force_utf8_console()
    sys.exit(main())
