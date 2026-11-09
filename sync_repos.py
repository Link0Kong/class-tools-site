#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""班级工具站 · 双远端同步脚本（GitHub + Gitee）

用法：
    python sync_repos.py "feat: 说明本次改了什么"   # 提交并同时推送两个远端
    python sync_repos.py --check                    # 只核对本地与两个远端是否一致
    sync-repos.cmd "feat: 说明"                     # 推荐入口（Windows，等价）

流程：敏感路径 / 凭据特征检查 → git add -A → commit（无改动跳过）
      → 推 origin(GitHub) → 推 gitee(Gitee) → 核对两端 HEAD == 本地 HEAD。
任一必需步骤失败都会非零退出；网络问题自动重试；重跑本脚本不会产生空提交。

用户要求（2026-11-10）：以后每次修改必须同时上传 GitHub + Gitee，并附说明。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent
BRANCH = "master"
REMOTES = (
    ("origin", "GitHub", "https://github.com/Link0Kong/class-tools-site"),
    ("gitee", "Gitee", "https://gitee.com/ko_Link/class-tools-site"),
)
COMMIT_PREFIXES = ("feat", "fix", "docs", "test", "chore", "refactor", "perf", "style", "build", "ci", "revert")
VAGUE_BODIES = {
    "update", "fix", "sync", "changes", "change", "test", "wip", "tmp",
    "更新", "修改", "同步", "修复", "改动", "提交", "测试",
}
FORBIDDEN_PATH_RE = re.compile(
    r"(^|/)(creds\.env|\.git-credentials|id_rsa|id_ed25519|acme_account_key\.pem)(/|$)"
    r"|(^|/)tools/cert/"
    r"|\.(pem|key|env|p12|pfx|jks)$",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    ("GitHub 令牌", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("私钥内容", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("云厂商 AccessKey", re.compile(r"(?:AKIA|LTAI)[0-9A-Za-z]{12,}")),
    ("数据库明文密码", re.compile(r"postgres(?:ql)?://[^:\s/@]+:[^@\s]{4,}@")),
    ("OpenAI 风格密钥", re.compile(r"sk-[A-Za-z0-9]{32,}")),
)
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


def check_branch() -> None:
    current = git_out("rev-parse", "--abbrev-ref", "HEAD")
    if current != BRANCH:
        fail(f"当前分支是 {current}，同步脚本只作用于 {BRANCH}。先执行：git switch {BRANCH}")


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
            "以下敏感 / 凭据类路径出现在提交范围，已中止：\n  "
            + "\n  ".join(bad)
            + "\n处理：git rm --cached <文件>，并确认 .gitignore 已排除（禁止提交密钥与证书）。"
        )
    hits = []
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
    if hits:
        fail(
            "以下文件中发现疑似密钥 / 令牌，已中止（只显示文件名，不显示内容）：\n  "
            + "\n  ".join(hits)
            + "\n若确认是测试用的假数据，请改写为明显无效的占位符后重试。"
        )


def ls_remote(remote: str, attempts: int = 3) -> str:
    last_error = ""
    for attempt in range(1, attempts + 1):
        proc = git("ls-remote", remote, f"refs/heads/{BRANCH}", check=False, timeout=120)
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
        proc = git("push", remote, BRANCH, check=False, timeout=600)
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
                "提交已保存在本地；GitHub 网络偶发中断时，隔 1–2 分钟重跑 sync-repos.cmd 即可（不会产生空提交）。"
            )


def is_ancestor(ancestor: str, descendant: str) -> bool:
    return git("merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0


def check_only() -> None:
    head = git_out("rev-parse", "HEAD")
    say(f"本地 master HEAD：{head[:12]}")
    ok = True
    for remote, label, _url in REMOTES:
        sha = ls_remote(remote)
        same = sha == head
        ok = ok and same
        say(f"  {label:<6}（{remote}）：{(sha or '(空)')[:12]}  {'[OK] 一致' if same else '[!!] 不一致'}")
    sys.exit(0 if ok else 1)


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] in {"-h", "--help"}:
        say(__doc__)
        return
    if "--check" in argv:
        argv = [item for item in argv if item != "--check"]
        if (ROOT / ".git").exists():
            check_branch()
            check_only()
        fail(f"不是 git 仓库：{ROOT}")
    if not (ROOT / ".git").exists():
        fail(f"不是 git 仓库：{ROOT}")
    total = 5
    say("==> 双远端同步：GitHub(origin) + Gitee(gitee) · master")
    say(f"    仓库：{ROOT}")
    check_branch()

    step(1, total, "安全检查（敏感路径 / 凭据特征）")
    git("add", "-A")
    staged = git_z("diff", "--cached", "--name-only", "-z")
    if staged:
        say(f"    待提交 {len(staged)} 个文件")
        check_sensitive(staged)
    else:
        say("    工作区无新改动（仅推送 / 核对远端）")

    message = None
    if staged:
        message = parse_message(argv)
        step(2, total, f"提交：{message}")
        commit = git("commit", "-m", message, check=False)
        if commit.returncode != 0:
            fail(f"git commit 失败：\n{(commit.stderr or commit.stdout).strip()}")
        stat_lines = git("show", "--stat", "--oneline", "--no-color", "-1").stdout.strip().splitlines()
        for line in stat_lines[:20]:
            say("    " + line)
    else:
        step(2, total, "无新改动，跳过 commit")

    head = git_out("rev-parse", "HEAD")
    step(3, total, f"推送两个远端（本地 {head[:12]}）")
    for remote, label, _url in REMOTES:
        remote_sha = ls_remote(remote)
        if remote_sha == head:
            say(f"    {label} 已是 {head[:12]}，无需推送")
            continue
        if remote_sha and not is_ancestor(remote_sha, head):
            fail(
                f"{label} 远端有本地没有的提交（{remote_sha[:12]}），继续推送会破坏远端历史，已中止。\n"
                f"先处理：git fetch {remote} && git rebase {remote}/{BRANCH}"
            )
        push_remote(remote, label)

    step(4, total, "核对两端 HEAD 与本地一致")
    ok = True
    for remote, label, _url in REMOTES:
        sha = ls_remote(remote)
        same = sha == head
        ok = ok and same
        say(f"    {label:<6}（{remote}）：{(sha or '(空)')[:12]}  {'[OK] 一致' if same else '[!!] 不一致'}")
    if not ok:
        fail("两端提交未全部对齐，请重跑本脚本（不会产生空提交）。")

    step(5, total, "完成")
    say("")
    for _remote, label, url in REMOTES:
        say(f"  {label}：{url}/commit/{head}")
    if message:
        say(f"  commit：{message}")
    sys.exit(0)


if __name__ == "__main__":
    force_utf8_console()
    main()
