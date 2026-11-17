# -*- coding: utf-8 -*-
"""把 legal/ 的公开页面同步到 OSS + ECS（只上传公开文件，不上传 README/_src）。

用法（在 web 目录下）：
    python deploy\\sync_legal.py              # OSS + ECS
    python deploy\\sync_legal.py --oss-only   # 只传 OSS
    python deploy\\sync_legal.py --ecs-only   # 只从 OSS 拉到 ECS（重试）

公开文件 = legal/index.html + legal/manifest.json + 5 端目录下的 *.html（共 12 个）。
README.md 与 _src/ 是内部维护文档，不发布到公网。
"""
from __future__ import annotations

import argparse
import hashlib
import posixpath
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
WEB = HERE.parent
LEGAL = WEB / "legal"
sys.path.insert(0, str(HERE))

import sync_tools  # noqa: E402
from ecs_site import ECS_IP, OSS_BASE, run_script  # noqa: E402

PUBLIC_DIRS = ("web", "android", "windows", "harmony", "mp")
CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def public_files() -> list[Path]:
    files = [LEGAL / "index.html", LEGAL / "manifest.json"]
    for name in PUBLIC_DIRS:
        files.extend(sorted((LEGAL / name).glob("*.html")))
    for p in files:
        if not p.is_file():
            raise SystemExit("缺少文件：%s" % p)
    return files


def rel(p: Path) -> str:
    return p.relative_to(LEGAL).as_posix()


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def upload_oss(files: list[Path]) -> None:
    import oss2

    ak, sk = sync_tools.load_creds()
    bucket = oss2.Bucket(oss2.Auth(ak, sk), "https://oss-cn-hongkong.aliyuncs.com", "tool-furina-fun")
    print("== OSS 上传（%d 个公开文件） ==" % len(files))
    for p in files:
        key = "legal/" + rel(p)
        ctype = CTYPES.get(p.suffix.lower(), "application/octet-stream")
        bucket.put_object_from_file(
            key,
            str(p),
            headers={"Content-Type": ctype, "Cache-Control": "no-cache"},
        )
        print("  OSS %-34s %8d B  %s" % (key, p.stat().st_size, sha256(p)[:12]))


def build_remote_script(files: list[Path]) -> str:
    lines = [
        "#!/bin/bash",
        "set -euo pipefail",
        'BASE="%s"' % OSS_BASE,
        'TMP=$(mktemp -d /var/www/tool/legal.new.XXXXXX)',
        'cleanup(){ rm -rf "$TMP"; }',
        "trap cleanup EXIT",
    ]
    for p in files:
        r = rel(p)
        parent = posixpath.dirname(r)
        if parent:
            lines.append('mkdir -p "$TMP/%s"' % parent)
        lines.append(
            'curl -fsSL --retry 3 --retry-delay 2 --max-time 120 -o "$TMP/%s" "$BASE/legal/%s"'
            % (r, r)
        )
    lines.append('cd "$TMP"')
    for p in files:
        lines.append('echo "%s  %s" | sha256sum -c -' % (sha256(p), rel(p)))
    lines.extend(
        [
            'test -s "$TMP/index.html"',
            'test -s "$TMP/manifest.json"',
            'BK="/var/www/tool_backup/legal-$(date +%Y%m%d-%H%M%S)"',
            'mkdir -p /var/www/tool_backup',
            'if [ -d /var/www/tool/legal ]; then mv /var/www/tool/legal "$BK"; fi',
            'mv "$TMP" /var/www/tool/legal',
            'chmod -R a+rX /var/www/tool/legal',
            'echo "FILES=$(find /var/www/tool/legal -type f | wc -l)"',
            'echo "INDEX=$(stat -c%s /var/www/tool/legal/index.html)"',
            'curl -s -m 8 -o /dev/null -w "LOCAL_INDEX=%{http_code}\\n" http://127.0.0.1/legal/',
            'curl -s -m 8 -o /dev/null -w "LOCAL_MANIFEST=%{http_code}\\n" http://127.0.0.1/legal/manifest.json',
            'echo "done: $(date -Is)"',
        ]
    )
    return "\n".join(lines) + "\n"


def deploy_ecs(files: list[Path]) -> None:
    print("== ECS 部署（从 OSS 拉取，原子替换 /var/www/tool/legal） ==")
    script = build_remote_script(files)
    status, code, output = run_script(script, timeout=240, wait=360, label="legal-deploy")
    print(output.strip())
    if status != "Success" or str(code) not in ("0", "None"):
        raise SystemExit("ECS 部署失败：status=%s exit=%s" % (status, code))
    if "LOCAL_INDEX=200" not in output or "LOCAL_MANIFEST=200" not in output:
        raise SystemExit("ECS 本机探测未返回 200，请检查 Caddy/权限")


def probe(url: str, must_contain: str | None = None, is_json: bool = False) -> None:
    r = requests.get(url, timeout=20)
    print("  %-68s HTTP %s  %6d B  %s" % (url, r.status_code, len(r.content), r.headers.get("Content-Type", "")))
    if r.status_code != 200:
        raise SystemExit("探测失败：%s -> HTTP %s" % (url, r.status_code))
    if must_contain and must_contain not in r.text:
        raise SystemExit("探测失败：%s 未包含 %s" % (url, must_contain))
    if is_json:
        r.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oss-only", action="store_true")
    parser.add_argument("--ecs-only", action="store_true")
    args = parser.parse_args()
    if args.oss_only and args.ecs_only:
        raise SystemExit("--oss-only 与 --ecs-only 不能同时使用")

    files = public_files()
    print("公开文件：%d 个（README/_src 不发布）" % len(files))
    if not args.ecs_only:
        upload_oss(files)
    if not args.oss_only:
        deploy_ecs(files)

    print("== 公网探测 ==")
    probe("http://%s/legal/" % ECS_IP, "隐私政策与用户协议")
    probe("http://%s/legal/manifest.json" % ECS_IP, is_json=True)
    probe("http://%s/legal/web/privacy.html" % ECS_IP, "隐私政策")
    probe("http://%s/legal/mp/terms.html" % ECS_IP, "用户协议")
    probe("https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/legal/index.html", "隐私政策与用户协议")
    print("完成：ECS + OSS 已同步；正式域名恢复后只需改回 baseUrl/canonical。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
