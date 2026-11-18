#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""班级工具站 · 单仓库双远端同步（GitHub + Gitee）

用法（在任一端仓库根目录执行）：
    python sync_repos.py "feat: 说明本次改了什么"   # 提交并同时推送两个远端
    python sync_repos.py --auto                     # 自动生成提交说明（批量/脚本调用用）
    python sync_repos.py --check                    # 只核对本地与两个远端是否一致
    python sync_repos.py --status                   # 只看工作区是否有改动
    sync-repos.cmd "feat: 说明"                     # Windows 推荐入口

流程：敏感路径 / 凭据特征检查 → git add -A → commit（无改动跳过）
      → 推 GitHub(origin) → 推 Gitee(gitee) → 核对两端 HEAD == 本地 HEAD。
任一必需步骤失败都会非零退出；网络问题自动重试；重跑不会产生空提交。

脚本按所在目录识别仓库，自动从 git remote 里找 github.com / gitee.com 两个远端，
因此五个端仓库（site / android / mp / harmony / windows）共用同一份脚本。

用户要求（2026-11-10 / 2026-11-18）：每个端一个仓库，修改必须同时推 GitHub + Gitee，
并附能看懂“改了什么”的说明；每个端都要能自动提交。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent
BRANCH = "master"
COMMIT_PREFIXES = ("feat", "fix", "docs", "test", "chore", "refactor", "perf", "style", "build", "ci", "revert")
VAGUE_BODIES = {
    "update", "fix", "sync", "changes", "change", "test", "wip", "tmp", "auto",
    "更新", "修改", "同步", "修复", "改动", "提交", "测试", "自动提交",
}
FORBIDDEN_PATH_RE = re.compile(
    r"(^|/)(creds\.env|\.git-credentials|id_rsa|id_ed25519|acme_account_key\.pem|keystore\.properties|local\.properties)(/|$)"
    r"|(^|/)(tools/cert|cert|key)/"
    r"|\.(pem|key|env|p12|pfx|jks|keystore|mobileprovision|db|sqlite|sqlite3)$",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    ("GitHub 令牌", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}")),
    ("私钥内容", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("云厂商 AccessKey", re.compile(r"(?:AKIA|LTAI)[0-9A-Za-z]{12,}")),
    ("数据库明文密码", re.compile(r"postgres(?:ql)?://[^:\s/@]+:[^@\s]{4,}@")),
    ("OpenAI 风格密钥", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("Webhook / AppSecret", re.compile(r"(?i)(appsecret|app_secret|webhook[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{24,}['\"]")),
)
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
LOCK_NAME = "sync-repos.lock"
LOCK_STALE_SECONDS = 15 * 60
# 网络命令加低速阈值：Gitee 偶发卡死时 60s 内失败重试，而不是挂 10 分钟
NET_OPTS = ("-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=60")
GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "PYTHONIOENCODING": "utf-8",
}


def force_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def say(msg: str = "") -> None:
    print(msg, flush=True)


def fail(msg: str) -> NoReturn:
    say(f"[x] {msg}")
    sys.exit(1)


def git(*args: str, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        env=GIT_ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        fail(f"git {' '.join(args)} 失败：\n{detail}")
    return proc


def git_out(*args: str) -> str:
    return git(*args).stdout.strip()


def git_z(*args: str) -> list[str]:
    return [item for item in git(*args).stdout.split("\0") if item]


def step(index: int, total: int, msg: str) -> None:
    say(f"==> [{index}/{total}] {msg}")


def detect_remotes() -> list[tuple[str, str]]:
    """返回 [(远端名, 平台名)]：GitHub 在前、Gitee 在后。"""
    out = git("remote", "-v").stdout
    urls: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] != "(fetch)":
            continue
        urls.setdefault(parts[0], parts[1])
    gh = [name for name, url in urls.items() if "github.com" in url]
    ge = [name for name, url in urls.items() if "gitee.com" in url]
    if not gh or not ge:
        fail(
            "没有找到 GitHub + Gitee 两个远端（需要有 github.com 与 gitee.com 各一个）。\n"
            f"当前远端：{urls or '无'}\n"
            "处理：git remote add origin <github-url>；git remote add gitee <gitee-url>"
        )
    if "origin" in gh:
        gh.sort(key=lambda n: n != "origin")
    if "gitee" in ge:
        ge.sort(key=lambda n: n != "gitee")
    return [(gh[0], "GitHub"), (ge[0], "Gitee")]


def check_branch() -> None:
    current = git_out("rev-parse", "--abbrev-ref", "HEAD")
    if current != BRANCH:
        fail(f"当前分支是 {current}，同步脚本只作用于 {BRANCH}。先执行：git switch {BRANCH}")


def acquire_lock() -> None:
    lock = ROOT / ".git" / LOCK_NAME
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                data = json.loads(lock.read_text(encoding="utf-8"))
                age = time.time() - float(data.get("ts") or 0)
            except (OSError, ValueError):
                age = LOCK_STALE_SECONDS + 1
            if age < LOCK_STALE_SECONDS:
                fail("另一个 sync-repos 正在运行（锁未释放）。若确认没有，删除 .git/sync-repos.lock 后重试。")
            lock.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "ts": time.time()}, fh)
        return
    fail("无法获取同步锁，请稍后重试。")


def release_lock() -> None:
    try:
        (ROOT / ".git" / LOCK_NAME).unlink(missing_ok=True)
    except OSError:
        pass


def auto_message(staged: list[str]) -> str:
    counts: dict[str, int] = {}
    for path in staged:
        top = path.split("/")[0] if "/" in path else "(根目录)"
        counts[top] = counts.get(top, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = ordered[:4]
    more = len(ordered) - len(shown)
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    detail = "、".join(f"{name} {n}" for name, n in shown) + (f" 等 {len(ordered)} 处" if more > 0 else "")
    return f"chore: 自动提交 {stamp}（{detail}，共 {len(staged)} 个文件）"


def parse_message(argv: list[str]) -> str:
    raw = " ".join(part.strip() for part in argv).strip()
    if not raw:
        fail('缺少提交说明。用法：sync-repos.cmd "feat: 说明本次改了什么"')
    match = re.match(r"^([A-Za-z]+)(\([^)]+\))?:\s*(.+)$", raw)
    if match and match.group(1).lower() in COMMIT_PREFIXES:
        prefix = match.group(1).lower() + (match.group(2) or "")
        body = match.group(3).strip()
        message = f"{prefix}: {body}"
    else:
        body = raw
        message = f"chore: {raw}"
    if body.rstrip("。.!！?？ ").lower() in VAGUE_BODIES or len(body) < 3:
        fail(f'提交说明太笼统（"{message}"）。请写清改了什么，例如：feat: 通知页新增已过期折叠')
    return message


def check_sensitive(staged: list[str]) -> None:
    tracked = [f for f in git("ls-files", "-z").stdout.split("\0") if f]
    bad = sorted({f for f in tracked if FORBIDDEN_PATH_RE.search(f)} | {f for f in staged if FORBIDDEN_PATH_RE.search(f)})
    if bad:
        fail(
            "以下敏感 / 凭据类路径出现在仓库或提交范围，已中止：\n  "
            + "\n  ".join(bad)
            + "\n处理：git rm --cached <文件>，并确认 .gitignore 已排除（禁止提交密钥与证书）。"
        )

    total = 0
    too_big: list[str] = []
    for path in staged:
        file_path = ROOT / path
        try:
            if not file_path.is_file():
                continue
            size = file_path.stat().st_size
        except OSError:
            continue
        total += size
        if size > MAX_FILE_BYTES:
            too_big.append(f"{path}（{size / 1024 / 1024:.1f}MB）")
    if too_big:
        fail(
            "以下文件超过 50MB，已中止（避免仓库不可用；大文件请放 OSS 或使用说明）：\n  " + "\n  ".join(too_big)
        )
    if total > MAX_TOTAL_BYTES:
        fail(f"本次提交合计 {total / 1024 / 1024:.0f}MB，超过 200MB 上限，已中止。")

    hits: list[str] = []
    for path in staged:
        file_path = ROOT / path
        try:
            if not file_path.is_file() or file_path.stat().st_size > 2 * 1024 * 1024:
                continue
            data = file_path.read_bytes()
            if b"\x00" in data[:8192]:
                continue
            text = data.decode("utf-8", "ignore")
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(f"{path}  （{label}）")
                break
    if hits:
        fail(
            "以下文件中发现疑似密钥 / 令牌，已中止（只显示文件名，不显示内容）：\n  "
            + "\n  ".join(hits)
            + "\n若确认是测试用的假数据，请改写为明显无效的占位符后重试。"
        )


def ls_remote(remote: str, attempts: int = 3) -> str:
    last_error = ""
    for attempt in range(1, attempts + 1):
        proc = git(*NET_OPTS, "ls-remote", remote, f"refs/heads/{BRANCH}", check=False, timeout=120)
        if proc.returncode == 0:
            line = proc.stdout.strip()
            return line.split()[0] if line else ""
        last_error = (proc.stderr or proc.stdout).strip()
        if attempt < attempts:
            wait = 2 * attempt
            tail = last_error.splitlines()[-1] if last_error else ""
            say(f"    {remote} 连接失败，{wait}s 后重试（{attempt}/{attempts}）：{tail}")
            time.sleep(wait)
    fail(f"无法读取远端 {remote} 的分支状态（网络问题），请检查网络后重跑本脚本。\n{last_error}")


def push_remote(remote: str, label: str, attempts: int = 3) -> None:
    for attempt in range(1, attempts + 1):
        proc = git(*NET_OPTS, "push", remote, BRANCH, check=False, timeout=600)
        if proc.returncode == 0:
            say(f"    {label} 推送成功")
            return
        error = (proc.stderr or proc.stdout).strip()
        if attempt < attempts:
            wait = 3 * attempt
            say(f"    {label} 推送失败，{wait}s 后重试（{attempt}/{attempts}）")
            time.sleep(wait)
        else:
            fail(
                f"{label}（{remote}）推送失败：\n{error}\n"
                "提交已保存在本地；网络偶发中断时，隔 1–2 分钟重跑 sync-repos.cmd 即可（不会产生空提交）。"
            )


def is_ancestor(ancestor: str, descendant: str) -> bool:
    return git("merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0


def reconcile(remote: str, label: str, auto: bool) -> None:
    """远端领先或分叉时，自动模式下尝试 rebase；手动模式给出明确提示。"""
    ref = f"refs/remotes/{remote}/{BRANCH}"
    git(*NET_OPTS, "fetch", remote, f"+refs/heads/{BRANCH}:{ref}", check=False, timeout=300)
    fetched = git("rev-parse", "--verify", "--quiet", ref, check=False).stdout.strip()
    if not fetched:
        return
    head = git_out("rev-parse", "HEAD")
    if fetched == head or is_ancestor(fetched, head):
        return
    if not auto:
        fail(
            f"{label} 远端有本地没有的提交（{fetched[:12]}），继续推送会破坏远端历史，已中止。\n"
            f"先处理：git pull --rebase {remote} {BRANCH} 后重跑本脚本。"
        )
    say(f"    {label} 远端领先，先 rebase 到 {fetched[:12]}")
    proc = git("rebase", ref, check=False, timeout=300)
    if proc.returncode != 0:
        git("rebase", "--abort", check=False)
        fail(
            f"自动 rebase 失败（可能有冲突）：\n{(proc.stderr or proc.stdout).strip()}\n"
            "处理：手动 git pull --rebase 解决冲突后重跑。"
        )


def check_only(remotes: list[tuple[str, str]]) -> None:
    head = git_out("rev-parse", "HEAD")
    say(f"仓库：{ROOT}")
    say(f"本地 {BRANCH} HEAD：{head[:12]}")
    ok = True
    for remote, label in remotes:
        sha = ls_remote(remote)
        same = sha == head
        ok = ok and same
        say(f"  {label:<6}（{remote}）：{(sha or '(空)')[:12]}  {'[OK] 一致' if same else '[!!] 不一致'}")
    sys.exit(0 if ok else 1)


def status_only() -> None:
    out = git("status", "--porcelain").stdout.strip()
    if not out:
        say("工作区干净：无待提交改动。")
        return
    lines = out.splitlines()
    say(f"工作区有 {len(lines)} 项改动：")
    for line in lines[:40]:
        say("  " + line)
    if len(lines) > 40:
        say(f"  ...（其余 {len(lines) - 40} 项）")


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] in {"-h", "--help"}:
        say(__doc__)
        return
    if not (ROOT / ".git").exists():
        fail(f"不是 git 仓库：{ROOT}")

    auto = "--auto" in argv
    argv = [item for item in argv if item != "--auto"]
    remotes = detect_remotes()

    if "--check" in argv:
        check_branch()
        check_only(remotes)
        return
    if "--status" in argv:
        status_only()
        return

    total = 5
    acquire_lock()
    try:
        say("==> 双远端同步：GitHub + Gitee · master")
        say(f"    仓库：{ROOT}")
        check_branch()

        step(1, total, "安全检查（敏感路径 / 凭据特征 / 大文件）")
        git("add", "-A")
        staged = git_z("diff", "--cached", "--name-only", "-z")
        if staged:
            say(f"    待提交 {len(staged)} 个文件")
            check_sensitive(staged)
        else:
            say("    工作区无新改动（仅推送 / 核对远端）")

        message = None
        if staged:
            message = auto_message(staged) if auto else parse_message(argv)
            step(2, total, f"提交：{message}")
            commit = git("commit", "-m", message, check=False)
            if commit.returncode != 0:
                fail(f"git commit 失败：\n{(commit.stderr or commit.stdout).strip()}")
            stat_lines = git("show", "--stat", "--oneline", "--no-color", "-1").stdout.strip().splitlines()
            for line in stat_lines[:20]:
                say("    " + line)
        else:
            step(2, total, "无新改动，跳过 commit")

        for remote, label in remotes:
            reconcile(remote, label, auto)

        head = git_out("rev-parse", "HEAD")
        step(3, total, f"推送两个远端（本地 {head[:12]}）")
        for remote, label in remotes:
            remote_sha = ls_remote(remote)
            if remote_sha == head:
                say(f"    {label} 已是 {head[:12]}，无需推送")
                continue
            if remote_sha and not is_ancestor(remote_sha, head):
                fail(
                    f"{label} 远端有本地没有的提交（{remote_sha[:12]}），继续推送会破坏远端历史，已中止。\n"
                    f"先处理：git pull --rebase {remote} {BRANCH}"
                )
            push_remote(remote, label)

        step(4, total, "核对两端 HEAD 与本地一致")
        ok = True
        for remote, label in remotes:
            sha = ls_remote(remote)
            same = sha == head
            ok = ok and same
            say(f"    {label:<6}（{remote}）：{(sha or '(空)')[:12]}  {'[OK] 一致' if same else '[!!] 不一致'}")
        if not ok:
            fail("两端提交未全部对齐，请重跑本脚本（不会产生空提交）。")

        step(5, total, "完成")
        say("")
        for remote, _label in remotes:
            say(f"  {remote}：{git_out('config', '--get', f'remote.{remote}.url')}")
        if message:
            say(f"  commit：{message}")
    finally:
        release_lock()


if __name__ == "__main__":
    force_utf8_console()
    main()
